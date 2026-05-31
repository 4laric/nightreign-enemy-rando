#!/usr/bin/env python3
"""
data_archive.py — read individual files out of Nightreign's encrypted
dvdbnd archives (data0-3.bhd/.bdt, dlc01.bhd/.bdt) WITHOUT a UXM unpack.

Read-only and contained. Given the NR BHD RSA public key, this:
  1. RSA-decrypts each .bhd header table (pure-Python modexp; no deps),
  2. indexes every file by its 64-bit path hash,
  3. fetches a file by its in-archive path
     (e.g. /map/mapstudio/m10_00_00_00.msb.dcx) straight out of the .bdt.

It returns RAW, still-DCX-compressed bytes — hand those to dcx.py exactly
as if you'd read a loose file. The randomizer's OUTPUT path is unchanged;
this only swaps the INPUT side, so vanilla_msbs/ can demote to a fallback.

Format per TKGP's SoulsFormats (BHD5.cs / SFUtil.cs). Two values are marked
CONFIRM — they self-validate via the oracle harness at the bottom.

STATUS: untested until the NR key lands; run --validate against your own
UXM-unpacked map/mapstudio to prove correctness on your machine.
"""
from __future__ import annotations

import base64
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from nr_keys import NIGHTREIGN_KEYS   # public per-archive BHD keys (beside this file)
except ImportError:
    NIGHTREIGN_KEYS = {}                  # or pass keys={archive: PEM} to DataArchive

MASK64 = (1 << 64) - 1

# CONFIRM #1 — ER/NR dvdbnd path hash is 64-bit with this prime (pre-ER was
# 32-bit, prime 37). If the oracle reports MISS on known maps, the fallback
# to try is prime 37 accumulated as u64.
ER_HASH_PRIME = 0x85


# --------------------------------------------------------------------------
# RSA: FromSoft "decrypts" the .bhd with the PUBLIC key (raw modexp), so we
# do c^e mod n per block and apply the known block trim. No crypto deps.
# --------------------------------------------------------------------------

def parse_rsa_public_key_pem(pem: str) -> tuple[int, int]:
    """(modulus, exponent) from a PKCS#1 'RSA PUBLIC KEY' PEM — the form UXM
    ships. Minimal DER walk; no dependencies. (If the key is instead a
    'BEGIN PUBLIC KEY' SPKI blob, this needs an unwrap step — flag it.)"""
    b64 = "".join(line for line in pem.strip().splitlines() if "-----" not in line)
    der = base64.b64decode(b64)

    def read_len(d, p):
        n = d[p]; p += 1
        if n < 0x80:
            return n, p
        k = n & 0x7F
        return int.from_bytes(d[p:p + k], "big"), p + k

    def read_int(d, p):
        assert d[p] == 0x02, "expected INTEGER in RSAPublicKey"
        p += 1
        ln, p = read_len(d, p)
        return int.from_bytes(d[p:p + ln], "big"), p + ln

    assert der[0] == 0x30, "expected SEQUENCE (PKCS#1 RSAPublicKey)"
    _, pos = read_len(der, 1)
    modulus, pos = read_int(der, pos)
    exponent, pos = read_int(der, pos)
    return modulus, exponent


def rsa_decrypt_bhd(enc: bytes, modulus: int, exponent: int) -> bytes:
    """Decrypt a FromSoft .bhd header table. Each block is key-size bytes:
    modexp it, render big-endian, drop the leading byte (FromSoft quirk),
    concatenate. Result must begin with b'BHD5'."""
    block_size = (modulus.bit_length() + 7) // 8
    out = bytearray()
    for i in range(0, len(enc), block_size):
        block = enc[i:i + block_size]
        if len(block) < block_size:
            break
        m = pow(int.from_bytes(block, "big"), exponent, modulus)
        out += m.to_bytes(block_size, "big")[1:]   # CONFIRM #2: drop byte[0]
    return bytes(out)


# --------------------------------------------------------------------------
# Path hashing
# --------------------------------------------------------------------------

def path_hash(path: str, prime: int = ER_HASH_PRIME) -> int:
    h = path.replace("\\", "/").lower()
    if not h.startswith("/"):
        h = "/" + h
    acc = 0
    for ch in h:
        acc = (acc * prime + ord(ch)) & MASK64
    return acc


# --------------------------------------------------------------------------
# BHD5 parse (Elden Ring / Nightreign layout)
# --------------------------------------------------------------------------

@dataclass
class FileEntry:
    name_hash: int
    padded_size: int
    unpadded_size: int
    offset: int
    aes_key: bytes | None = None
    aes_ranges: list[tuple[int, int]] = field(default_factory=list)


class Bhd5:
    """Parsed, already-decrypted BHD5 header (ER/NR format)."""

    def __init__(self, data: bytes):
        if data[:4] != b"BHD5":
            raise ValueError(
                "decrypted header is not BHD5 (bad magic) — the RSA key or "
                "the per-block trim is wrong")
        # 'BHD5', sbyte big-endian flag (0=BE, -1=LE), bool, 0, 0,
        # int32=1, int32 fileSize, int32 bucketCount, int32 bucketsOffset,
        # int32 saltLen, ascii salt.  PC is little-endian.
        endian = ">" if data[4] == 0 else "<"
        bucket_count, buckets_offset = struct.unpack_from(endian + "ii", data, 16)
        self.entries: dict[int, FileEntry] = {}

        pos = buckets_offset
        bucket_descs = []
        for _ in range(bucket_count):
            count, off = struct.unpack_from(endian + "ii", data, pos)
            pos += 8
            bucket_descs.append((count, off))

        for count, off in bucket_descs:
            ep = off
            for _ in range(count):
                (name_hash, padded, unpadded, foff,
                 _sha_off, aes_off) = struct.unpack_from(endian + "QiiQqq", data, ep)
                ep += 40  # ER file header is 8+4+4+8+8+8
                entry = FileEntry(name_hash, padded, unpadded, foff)
                if aes_off != 0:
                    entry.aes_key = bytes(data[aes_off:aes_off + 16])
                    rc = struct.unpack_from(endian + "i", data, aes_off + 16)[0]
                    rp = aes_off + 20
                    for _ in range(rc):
                        s, e = struct.unpack_from(endian + "qq", data, rp)
                        rp += 16
                        entry.aes_ranges.append((s, e))
                self.entries[name_hash] = entry


# --------------------------------------------------------------------------
# AES (only runs for entries that actually carry a key — most don't)
# --------------------------------------------------------------------------

def _aes_decrypt_ranges(data: bytearray, key: bytes, ranges):
    """AES-128-ECB decrypt the given byte ranges in place. Nightreign's map
    MSBs ARE encrypted, so this runs for every map file. Uses a fast backend
    if one is installed, otherwise the bundled pure-Python aes128 — no pip
    install required either way."""
    try:
        from Crypto.Cipher import AES            # pycryptodome, if present (fast)
        decrypt = lambda buf: AES.new(key, AES.MODE_ECB).decrypt(buf)
    except ImportError:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            def decrypt(buf):
                d = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
                return d.update(buf) + d.finalize()
        except ImportError:
            from aes128 import decrypt_ecb        # bundled, dependency-free
            decrypt = lambda buf: decrypt_ecb(key, buf)
    for start, end in ranges:
        if start < 0 or end < 0 or end <= start:
            continue
        n = (end - start)
        n -= n % 16  # ECB works on whole 16-byte blocks
        data[start:start + n] = decrypt(bytes(data[start:start + n]))


# --------------------------------------------------------------------------
# The archive bundle
# --------------------------------------------------------------------------

# NR ships these dvdbnd pairs (from the Game/ listing). dlc01 may use its own
# key; pass dlc_key_pem if UXM lists a separate one.
DEFAULT_ARCHIVES = ["data0", "data1", "data2", "data3", "dlc01"]


class DataArchive:
    def __init__(self, game_dir, keys=None, archives=None):
        """keys: {archive_name: PEM}. Defaults to the embedded Nightreign
        per-archive keys (Data0-3 each differ). An archive whose BHD is already
        plaintext needs no key; an encrypted archive with no key is skipped and
        recorded in .skipped (e.g. dlc01, whose key isn't bundled in this build)."""
        self.game_dir = Path(game_dir)
        archives = archives or DEFAULT_ARCHIVES
        keys = {k.lower(): v for k, v in (NIGHTREIGN_KEYS if keys is None else keys).items()}
        ne_cache: dict[str, tuple[int, int]] = {}

        self._index: dict[int, tuple[str, FileEntry]] = {}
        self.skipped: list[str] = []
        for name in archives:
            bhd = self.game_dir / f"{name}.bhd"
            if not bhd.exists():
                continue
            raw = bhd.read_bytes()
            # Some games ship plaintext BHDs; if it's already BHD5, no key needed.
            if raw[:4] == b"BHD5":
                dec = raw
            else:
                pem = keys.get(name.lower())
                if pem is None:
                    self.skipped.append(name)
                    continue
                if name not in ne_cache:
                    ne_cache[name] = parse_rsa_public_key_pem(pem)
                dec = rsa_decrypt_bhd(raw, *ne_cache[name])
            for h, entry in Bhd5(dec).entries.items():
                self._index.setdefault(h, (name, entry))

    def __len__(self):
        return len(self._index)

    def get(self, archive_path: str) -> bytes:
        """Raw (still DCX-compressed) bytes for an in-archive path such as
        '/map/mapstudio/m10_00_00_00.msb.dcx'."""
        h = path_hash(archive_path)
        hit = self._index.get(h)
        if hit is None:
            raise KeyError(f"{archive_path} (hash {h:#018x}) not found in any archive")
        name, entry = hit
        with open(self.game_dir / f"{name}.bdt", "rb") as f:
            f.seek(entry.offset)
            data = bytearray(f.read(entry.padded_size))
        if entry.aes_key:
            _aes_decrypt_ranges(data, entry.aes_key, entry.aes_ranges)
        # Nightreign leaves unpadded_size = 0; the entry's padded size IS the
        # real file size (UXM writes these same bytes to disk, and SoulsFormats'
        # ReadFile likewise returns the padded bytes), so return the whole
        # decrypted buffer rather than trimming to a zero unpadded_size.
        return bytes(data)


# --------------------------------------------------------------------------
# Oracle: an archive read must byte-match the same file from a UXM unpack.
# This is the whole correctness test — run it against your own install.
# --------------------------------------------------------------------------

def validate_against_loose(archive: DataArchive, loose_mapstudio: str,
                           archive_prefix: str = "/map/mapstudio") -> bool:
    loose = Path(loose_mapstudio)
    files = sorted(loose.glob("*.msb.dcx"))
    if not files:
        print(f"no *.msb.dcx under {loose}")
        return False
    ok = bad = miss = 0
    for f in files:
        ap = f"{archive_prefix}/{f.name}"
        try:
            got = archive.get(ap)
        except KeyError:
            print(f"  MISS  {ap}")
            miss += 1
            continue
        if got == f.read_bytes():
            ok += 1
        else:
            print(f"  DIFF  {ap}  (archive {len(got)}B vs loose)")
            bad += 1
    print(f"\n{ok} match / {bad} differ / {miss} missing  (of {len(files)} loose MSBs)")
    clean = bad == 0 and miss == 0 and ok > 0
    if clean:
        print("Reader matches your install byte-for-byte. vanilla_msbs/ can "
              "become a fallback.")
    return clean


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Read NR dvdbnd files (keys embedded); validate against a UXM unpack.")
    p.add_argument("game_dir", help=".../ELDEN RING NIGHTREIGN/Game")
    p.add_argument("--key-dir", help="override: a dir of <archive>.pem files (else the embedded NR keys)")
    p.add_argument("--validate", metavar="MAPSTUDIO_DIR",
                   help="loose map/mapstudio dir to byte-compare against")
    p.add_argument("--get", metavar="ARCHIVE_PATH",
                   help="fetch one path to stdout, e.g. /map/mapstudio/m10_00_00_00.msb.dcx")
    p.add_argument("--inspect", metavar="ARCHIVE_PATH",
                   help="debug: dump the parsed header + bytes for one path")
    a = p.parse_args()

    keys = None
    if a.key_dir:
        keys = {f.stem: f.read_text() for f in Path(a.key_dir).glob("*.pem")}

    arc = DataArchive(a.game_dir, keys=keys)
    print(f"indexed {len(arc)} files across archives", file=sys.stderr)
    if arc.skipped:
        print(f"(skipped — no bundled key: {', '.join(arc.skipped)})", file=sys.stderr)
    if a.inspect:
        h = path_hash(a.inspect)
        hit = arc._index.get(h)
        if hit is None:
            print(f"{a.inspect} -> NOT indexed (hash {h:#018x})"); sys.exit(1)
        name, e = hit
        print(f"path           {a.inspect}")
        print(f"hash           {h:#018x}")
        print(f"archive        {name}.bdt")
        print(f"offset         {e.offset}")
        print(f"padded_size    {e.padded_size}")
        print(f"unpadded_size  {e.unpadded_size}")
        print(f"aes_key        {'present' if e.aes_key else 'none'}   ranges={e.aes_ranges}")
        with open(arc.game_dir / f"{name}.bdt", "rb") as f:
            f.seek(e.offset)
            raw = bytearray(f.read(e.padded_size))
        print(f"bytes_read     {len(raw)}")
        print(f"raw[:8]        {raw[:8].hex()}   ({bytes(raw[:4])!r})")
        if e.aes_key:
            _aes_decrypt_ranges(raw, e.aes_key, e.aes_ranges)
            print(f"after_aes[:8]  {raw[:8].hex()}   ({bytes(raw[:4])!r})   <- expect b'DCX\\x00'")
        if a.validate:
            loose = Path(a.validate) / Path(a.inspect).name
            if loose.exists():
                lb = loose.read_bytes()
                print(f"loose_size     {len(lb)}   loose[:8] {lb[:8].hex()}")
        sys.exit(0)
    if a.get:
        sys.stdout.buffer.write(arc.get(a.get))
    if a.validate:
        sys.exit(0 if validate_against_loose(arc, a.validate) else 1)
