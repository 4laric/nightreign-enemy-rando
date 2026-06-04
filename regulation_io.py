#!/usr/bin/env python3
"""regulation_io.py - read/patch/write Nightreign's encrypted regulation.bin.

The regulation is layered:  AES-256-CBC( DCX[ZSTD]( BND4( *.param ) ) ).
This module unwraps that stack far enough to overwrite **fixed-width fields**
of existing PARAM rows in place (length-preserving), then re-wraps it. It does
NOT add/remove rows, edit strings, or re-serialize the BND4 / PARAM tables, so
no paramdef and no PARAM/BND4 *writer* is needed - only readers.

Dependencies: `cryptography` (AES) and `zstandard` (DCX ZSTD). Both pip-installable;
no Windows Oodle DLL is required because NR's regulation DCX is ZSTD, not Kraken.

  >>> reg = Regulation.load("regulation.bin")          # decrypt + decompress
  >>> reg.patch_param_field("ShopLineupParam", 600000, EQUIPID_OFF, "<i", 1010000)
  >>> reg.save("regulation.bin")                        # recompress + re-encrypt

Verified against the shipping bundled regulation (Nightreign): the no-edit
decrypt->re-encrypt is byte-identical (see tests), confirming key+IV+padding.

CRYPTO CONSTANT NOTE
--------------------
`NR_REGULATION_KEY` is a public modding constant - the AES-256 regulation key
for ELDEN RING NIGHTREIGN, identical to the one in SoulsFormatsNEXT
(`RegulationDecryptor.cs`, enum `RegulationKey.EldenRingNightreign`), which is
what Smithbox / WitchyBND / ERBM use. It is *data*, like the dvdbnd BHD keys in
`nr_keys.py`. It is **version-sensitive**: FromSoft periodically changes the
regulation crypto. If a game patch breaks loading, refresh this value from
current SoulsFormatsNEXT; the byte-identical round-trip test is the canary.
"""

import io
import struct

# --- ShopLineupParam field offsets within a 64-byte row (empirically derived
#     and validated against the param CSV across all merchant rows). ----------
SHOP_EQUIPID_OFF = 4    # s32  equipId
SHOP_VALUE_OFF = 8      # s32  value (price; -1 = item default)
SHOP_EQUIPTYPE_OFF = 27  # u8   equipType (0 weapon / 1 protector / 2 accessory / 3 goods)

NR_REGULATION_KEY = bytes((
    0x9A, 0x8E, 0xE9, 0x0C, 0x4C, 0x01, 0xA4, 0x31,
    0x68, 0xA1, 0x7D, 0x9D, 0x75, 0xE4, 0xA7, 0xD0,
    0x21, 0x07, 0xEB, 0xCF, 0x43, 0xD5, 0xAC, 0xB0,
    0x55, 0x4F, 0x94, 0x16, 0x01, 0xB5, 0x79, 0x18,
))

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


# --------------------------------------------------------------------------- #
# AES-256-CBC layer
# --------------------------------------------------------------------------- #
def _aes():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        return Cipher, algorithms, modes
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "regulation_io needs the 'cryptography' package "
            "(pip install cryptography)."
        ) from e


def aes_decrypt(data: bytes, key: bytes = NR_REGULATION_KEY) -> bytes:
    """Decrypt a regulation: 16-byte IV prefix + AES-256-CBC body, no de-padding.

    Mirrors SoulsFormatsNEXT: IV is the leading 16 bytes (zero in practice),
    PaddingMode.None, and the ciphertext is zero-padded up to a 16-multiple if
    it isn't already (it always is for FromSoft regulations).
    """
    Cipher, algorithms, modes = _aes()
    iv, body = data[:16], bytearray(data[16:])
    if len(body) % 16:
        body += b"\x00" * (16 - len(body) % 16)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(bytes(body)) + dec.finalize()


def aes_encrypt(plain: bytes, key: bytes = NR_REGULATION_KEY, pkcs7: bool = True) -> bytes:
    """Encrypt a regulation payload, returning IV(zeros)+ciphertext.

    pkcs7=True   : PKCS7-pad to a 16-multiple (use for MODIFIED output; the game
                   reads the inner DCX by its own length, so trailing pad is fine).
    pkcs7=False  : no padding; input must already be 16-aligned. Use this to
                   reproduce a byte-identical no-edit round-trip of an unchanged,
                   already-aligned decrypted blob (the round-trip test).
    """
    Cipher, algorithms, modes = _aes()
    iv = b"\x00" * 16
    buf = bytearray(plain)
    if pkcs7:
        pad = 16 - (len(buf) % 16) or 16
        buf += bytes([pad]) * pad
    elif len(buf) % 16:
        raise ValueError("pkcs7=False requires 16-aligned input")
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return iv + enc.update(bytes(buf)) + enc.finalize()


# --------------------------------------------------------------------------- #
# DCX (ZSTD) layer
# --------------------------------------------------------------------------- #
def dcx_decompress(dcx: bytes) -> bytes:
    """Decompress a FromSoft DCX (ZSTD method) to its inner bytes (the BND4)."""
    if dcx[:4] != b"DCX\x00":
        raise ValueError("not a DCX container")
    method = dcx[0x28:0x2C]
    if method != b"ZSTD":
        raise ValueError(f"unsupported DCX method {method!r} (expected ZSTD)")
    uncompressed = struct.unpack_from(">I", dcx, 0x1C)[0]
    compressed = struct.unpack_from(">I", dcx, 0x20)[0]
    data_start = dcx.find(_ZSTD_MAGIC)
    if data_start < 0:
        raise ValueError("no ZSTD frame found in DCX")
    import zstandard as zstd
    out = zstd.ZstdDecompressor().decompress(
        dcx[data_start:data_start + compressed], max_output_size=uncompressed + 64
    )
    if len(out) != uncompressed:
        raise ValueError(f"DCX size mismatch: header {uncompressed}, got {len(out)}")
    return out


def dcx_compress(inner: bytes, template_dcx: bytes, level: int = 17) -> bytes:
    """Re-wrap `inner` in a DCX, reusing the header of `template_dcx`.

    `inner` length must equal the template's recorded uncompressed size (we only
    ever patch in place, so it does). The 88-byte DCX header (DCX/DCS/DCP/DCA
    blocks) is copied verbatim; only the compressed-size field is rewritten. ZSTD
    level affects only output size, never correctness.
    """
    if template_dcx[0x28:0x2C] != b"ZSTD":
        raise ValueError("template is not a ZSTD DCX")
    uncompressed = struct.unpack_from(">I", template_dcx, 0x1C)[0]
    if len(inner) != uncompressed:
        raise ValueError(
            f"in-place invariant broken: inner len {len(inner)} != template "
            f"uncompressed {uncompressed}"
        )
    data_start = template_dcx.find(_ZSTD_MAGIC)
    import zstandard as zstd
    # NR's regulation DCX uses a ZSTD frame with windowLog=16 (64 KiB window)
    # and no content-size / checksum / dict-id in the frame header (FHD=0x00).
    # The game's decompressor is built for that small window and CRASHES (CTD
    # on regulation load) when handed a frame that declares a larger window —
    # which is what ZstdCompressor's default level-17 settings produce
    # (windowLog ~23). So cap window_log to 16 and match vanilla's frame-header
    # structure. `level` only affects output size now; the window cap is the
    # hard correctness constraint, not an optimization.
    cparams = zstd.ZstdCompressionParameters.from_level(
        level, window_log=16,
        write_content_size=0, write_checksum=0, write_dict_id=0)
    frame = zstd.ZstdCompressor(compression_params=cparams).compress(inner)
    header = bytearray(template_dcx[:data_start])
    struct.pack_into(">I", header, 0x20, len(frame))  # compressedSize (big-endian)
    return bytes(header) + frame


# --------------------------------------------------------------------------- #
# BND4 + PARAM (read-only locators)
# --------------------------------------------------------------------------- #
class _BND4:
    """Minimal read-only BND4 locator for the regulation binder.

    Regulation binder format byte 0x74 => per-file header 0x24 bytes:
      flags(1)+pad(3)+(-1)(4) | compressedSize(8) | uncompressedSize(8) |
      dataOffset(u32) | id(s32) | nameOffset(u32 -> UTF-16LE path).
    Offsets are 32-bit here (HasLongOffsets is false despite compression fields).
    """

    def __init__(self, data: bytes):
        if data[:4] != b"BND4":
            raise ValueError("not a BND4")
        self.data = data
        self.file_count = struct.unpack_from("<i", data, 0x0C)[0]
        self.header_size = struct.unpack_from("<q", data, 0x20)[0]
        self.unicode = bool(data[0x30])
        if self.header_size != 0x24:
            raise ValueError(
                f"unexpected BND4 file-header size 0x{self.header_size:X} "
                "(only the 0x24 regulation layout is implemented)"
            )

    def _name(self, off: int) -> str:
        d = self.data
        if self.unicode:
            e = off
            while d[e:e + 2] != b"\x00\x00":
                e += 2
            return d[off:e].decode("utf-16-le", "replace")
        e = d.find(b"\x00", off)
        return d[off:e].decode("shift-jis", "replace")

    def find(self, basename: str):
        """Return (data_offset, size) of the file whose path ends with basename."""
        target = basename if basename.endswith(".param") else basename + ".param"
        for i in range(self.file_count):
            p = 0x40 + i * self.header_size
            name_off = struct.unpack_from("<I", self.data, p + 32)[0]
            if self._name(name_off).replace("\\", "/").endswith("/" + target):
                size = struct.unpack_from("<q", self.data, p + 8)[0]
                off = struct.unpack_from("<I", self.data, p + 24)[0]
                compressed = self.data[p] & 1
                if compressed:
                    raise ValueError(f"{basename} is DCX-compressed inside the BND4")
                return off, size
        raise KeyError(f"{basename} not found in regulation BND4")


def param_row_offsets(param: bytes) -> dict:
    """Map {row_id: data_offset_within_param} for a 64-bit-offset PARAM.

    ER/NR params: rowCount at 0x0A; ParamType via int64 offset at 0x10; row
    index begins at 0x40 with 24-byte entries (id s32 @+0, dataOffset s64 @+8,
    nameOffset s64 @+16). Falls back to 16-byte unnamed entries if needed, and
    validates that data offsets are in-range and uniformly strided.
    """
    row_count = struct.unpack_from("<H", param, 0x0A)[0]
    for stride in (24, 16):
        rows, offs, ok = {}, [], True
        for i in range(row_count):
            q = 0x40 + i * stride
            rid = struct.unpack_from("<i", param, q)[0]
            doff = struct.unpack_from("<q", param, q + 8)[0]
            if not (0 < doff <= len(param)):
                ok = False
                break
            rows[rid] = doff
            offs.append(doff)
        if ok and len(offs) >= 2 and offs[1] > offs[0] and all(
            offs[k + 1] - offs[k] == offs[1] - offs[0] for k in range(len(offs) - 1)
        ):
            return rows
    raise ValueError("could not parse PARAM row index")


# --------------------------------------------------------------------------- #
# High-level handle
# --------------------------------------------------------------------------- #
class Regulation:
    """Decrypted+decompressed regulation, patchable in place."""

    def __init__(self, dcx: bytes, bnd: bytes):
        self._dcx_template = dcx        # original DCX, header reused on save
        self.bnd = bytearray(bnd)       # the live, patchable BND4 bytes
        self._bnd4 = _BND4(bytes(self.bnd))
        self._param_cache = {}          # name -> (off, size, {row_id: rel_off})

    # -- construction --------------------------------------------------------
    @classmethod
    def from_bytes(cls, raw: bytes, key: bytes = NR_REGULATION_KEY) -> "Regulation":
        dcx = aes_decrypt(raw, key)
        bnd = dcx_decompress(dcx)
        return cls(dcx, bnd)

    @classmethod
    def load(cls, path: str, key: bytes = NR_REGULATION_KEY) -> "Regulation":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read(), key)

    # -- param access --------------------------------------------------------
    def _param(self, name: str):
        if name not in self._param_cache:
            off, size = self._bnd4.find(name)
            rows = param_row_offsets(bytes(self.bnd[off:off + size]))
            self._param_cache[name] = (off, size, rows)
        return self._param_cache[name]

    def param_rows(self, name: str) -> list:
        return sorted(self._param(name)[2].keys())

    def read_param_field(self, name: str, row_id: int, field_off: int, fmt: str):
        off, _size, rows = self._param(name)
        return struct.unpack_from(fmt, self.bnd, off + rows[row_id] + field_off)[0]

    def patch_param_field(self, name: str, row_id: int, field_off: int, fmt: str, value):
        """Overwrite one fixed-width field of one row (length-preserving)."""
        off, _size, rows = self._param(name)
        if row_id not in rows:
            raise KeyError(f"{name} has no row {row_id}")
        struct.pack_into(fmt, self.bnd, off + rows[row_id] + field_off, value)

    # -- serialization -------------------------------------------------------
    def to_bytes(self, key: bytes = NR_REGULATION_KEY, level: int = 17) -> bytes:
        dcx = dcx_compress(bytes(self.bnd), self._dcx_template, level=level)
        # Match vanilla's AES layout: the regulation is zero-padded to a 16-byte
        # multiple and encrypted with NO PKCS7 (the game decrypts PaddingMode.None
        # and reads the inner DCX by its recorded size). PKCS7 would append 0x0e
        # bytes vanilla never has; zero-pad keeps the plaintext byte-for-byte the
        # shape FromSoft / SoulsFormats produce.
        if len(dcx) % 16:
            dcx = dcx + b"\x00" * (16 - len(dcx) % 16)
        return aes_encrypt(dcx, key, pkcs7=False)

    def save(self, path: str, key: bytes = NR_REGULATION_KEY, level: int = 17) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes(key, level))
