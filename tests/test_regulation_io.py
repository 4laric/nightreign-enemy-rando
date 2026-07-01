#!/usr/bin/env python3
"""Unit tests for regulation_io.py — the AES/DCX/BND4/PARAM regulation stack.

Everything here runs against a SYNTHETIC regulation built in-test (a real
BND4+PARAM layout, ZSTD-DCX-wrapped, AES-256-CBC-encrypted with the NR key),
so no game data is required. The BND4/PARAM locator tests are pure stdlib;
the crypto/compression and end-to-end tests skip if cryptography/zstandard
are missing (same convention as test_regulation_rando.py).

The atomic-save tests lock the v0.33 partial-write fix: the GUI's shop stage
patches the deployed regulation.bin IN PLACE (src == dest), so a failed save
must leave the destination byte-identical and drop no temp files.
"""

import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import regulation_io as R  # noqa: E402

try:
    import cryptography  # noqa: F401
    import zstandard     # noqa: F401
    HAVE_DEPS = True
except Exception:
    HAVE_DEPS = False

need_deps = pytest.mark.skipif(not HAVE_DEPS,
                               reason="cryptography/zstandard not installed")


# --------------------------------------------------------------------------- #
# synthetic regulation builders
# --------------------------------------------------------------------------- #
ROW_SIZE = 16
PARAM_NAME = "ShopLineupParam"
FIELD_OFF = 4          # test field: <i at +4 within each row
ROW_IDS = (100, 200, 350)


def make_param(row_ids=ROW_IDS, row_size=ROW_SIZE):
    """Minimal 64-bit-offset PARAM: 0x40 header, 24-byte index entries, rows.
    Each row's bytes are derived from its id so reads are verifiable."""
    n = len(row_ids)
    data_base = 0x40 + 24 * n
    buf = bytearray(data_base + row_size * n)
    struct.pack_into("<H", buf, 0x0A, n)               # rowCount
    for i, rid in enumerate(row_ids):
        q = 0x40 + i * 24
        doff = data_base + i * row_size
        struct.pack_into("<i", buf, q, rid)            # id
        struct.pack_into("<q", buf, q + 8, doff)       # dataOffset
        struct.pack_into("<q", buf, q + 16, 0)         # nameOffset (unused)
        struct.pack_into("<B", buf, doff, rid % 251)   # row payload byte 0
        struct.pack_into("<i", buf, doff + FIELD_OFF, rid * 7)  # test field
    return bytes(buf)


def make_bnd4(files, compressed_flags=None):
    """Minimal regulation-layout BND4 (0x24 file headers, UTF-16LE names).
    `files` is {basename: param_bytes}; names get a GameParam-style path."""
    names = {k: f"N:/test/param/GameParam/{k}.param" for k in files}
    n = len(files)
    entries_base = 0x40
    names_base = entries_base + 0x24 * n
    name_blobs, name_offs, pos = [], {}, names_base
    for k in files:
        b = names[k].encode("utf-16-le") + b"\x00\x00"
        name_offs[k] = pos
        name_blobs.append(b)
        pos += len(b)
    data_base = (pos + 15) & ~15
    buf = bytearray(data_base)
    buf[0:4] = b"BND4"
    struct.pack_into("<i", buf, 0x0C, n)               # file_count
    struct.pack_into("<q", buf, 0x20, 0x24)            # per-file header size
    buf[0x30] = 1                                      # unicode names
    buf[names_base:pos] = b"".join(name_blobs)
    out = bytearray(buf)
    off = data_base
    for i, (k, payload) in enumerate(files.items()):
        p = entries_base + i * 0x24
        flag = (compressed_flags or {}).get(k, 0x40)   # bit0 clear = stored
        struct.pack_into("<B", out, p, flag)
        struct.pack_into("<i", out, p + 4, -1)
        struct.pack_into("<q", out, p + 8, len(payload))   # compressedSize
        struct.pack_into("<q", out, p + 16, len(payload))  # uncompressedSize
        struct.pack_into("<I", out, p + 24, off)           # dataOffset
        struct.pack_into("<i", out, p + 28, i)             # id
        struct.pack_into("<I", out, p + 32, name_offs[k])  # nameOffset
        out += payload
        off += len(payload)
    return bytes(out)


def make_dcx(inner):
    """Wrap `inner` in a ZSTD DCX with the same frame params dcx_compress
    uses (window_log=16, no content-size/checksum/dict-id)."""
    import zstandard as zstd
    cparams = zstd.ZstdCompressionParameters.from_level(
        17, window_log=16,
        write_content_size=0, write_checksum=0, write_dict_id=0)
    frame = zstd.ZstdCompressor(compression_params=cparams).compress(inner)
    header = bytearray(0x4C)
    header[0:4] = b"DCX\x00"
    struct.pack_into(">I", header, 0x1C, len(inner))   # uncompressedSize
    struct.pack_into(">I", header, 0x20, len(frame))   # compressedSize
    header[0x28:0x2C] = b"ZSTD"
    return bytes(header) + frame


def make_regulation_bytes():
    """Full synthetic regulation.bin: AES-256-CBC( DCX[ZSTD]( BND4 ) )."""
    bnd = make_bnd4({PARAM_NAME: make_param()})
    dcx = make_dcx(bnd)
    if len(dcx) % 16:
        dcx += b"\x00" * (16 - len(dcx) % 16)
    return R.aes_encrypt(dcx, pkcs7=False), bnd


# --------------------------------------------------------------------------- #
# pure: PARAM + BND4 locators (no deps needed)
# --------------------------------------------------------------------------- #
def test_param_row_offsets_synthetic():
    rows = R.param_row_offsets(make_param())
    assert sorted(rows) == sorted(ROW_IDS)
    offs = [rows[r] for r in ROW_IDS]
    assert offs[1] - offs[0] == offs[2] - offs[1] == ROW_SIZE


def test_param_row_offsets_rejects_garbage():
    with pytest.raises(ValueError):
        R.param_row_offsets(b"\x00" * 0x40 + b"\xff" * 96)


def test_bnd4_find_and_reject():
    bnd = R._BND4(make_bnd4({PARAM_NAME: make_param(), "NpcParam": make_param()}))
    off, size = bnd.find(PARAM_NAME)               # basename without .param
    assert size == len(make_param())
    off2, _ = bnd.find(PARAM_NAME + ".param")      # and with
    assert off2 == off
    with pytest.raises(KeyError):
        bnd.find("NoSuchParam")


def test_bnd4_rejects_bad_magic_and_compressed_entries():
    with pytest.raises(ValueError):
        R._BND4(b"BND3" + b"\x00" * 0x60)
    raw = make_bnd4({PARAM_NAME: make_param()},
                    compressed_flags={PARAM_NAME: 0x41})   # bit0 set
    with pytest.raises(ValueError):
        R._BND4(raw).find(PARAM_NAME)


# --------------------------------------------------------------------------- #
# crypto + compression layers
# --------------------------------------------------------------------------- #
@need_deps
def test_aes_round_trip_no_padding():
    data = bytes(range(256)) * 2                   # 16-aligned
    enc = R.aes_encrypt(data, pkcs7=False)
    assert enc[:16] == b"\x00" * 16                # zero IV prefix
    assert R.aes_decrypt(enc) == data


@need_deps
def test_aes_pkcs7_pads_and_unaligned_rejected():
    data = b"x" * 20
    dec = R.aes_decrypt(R.aes_encrypt(data, pkcs7=True))
    assert dec[:20] == data and len(dec) % 16 == 0
    with pytest.raises(ValueError):
        R.aes_encrypt(data, pkcs7=False)


@need_deps
def test_dcx_round_trip_and_length_invariant():
    inner = make_bnd4({PARAM_NAME: make_param()})
    dcx = make_dcx(inner)
    assert R.dcx_decompress(dcx) == inner
    redone = R.dcx_compress(inner, dcx)
    assert R.dcx_decompress(redone) == inner
    with pytest.raises(ValueError):                # in-place invariant
        R.dcx_compress(inner + b"\x00", dcx)
    with pytest.raises(ValueError):
        R.dcx_decompress(b"notadcx" + dcx[8:])


# --------------------------------------------------------------------------- #
# end-to-end Regulation handle
# --------------------------------------------------------------------------- #
@need_deps
def test_regulation_read_patch_round_trip():
    raw, _bnd = make_regulation_bytes()
    reg = R.Regulation.from_bytes(raw)
    assert reg.param_rows(PARAM_NAME) == sorted(ROW_IDS)
    assert reg.read_param_field(PARAM_NAME, 200, FIELD_OFF, "<i") == 1400

    reg.patch_param_field(PARAM_NAME, 200, FIELD_OFF, "<i", 99999)
    reg2 = R.Regulation.from_bytes(reg.to_bytes())
    assert reg2.read_param_field(PARAM_NAME, 200, FIELD_OFF, "<i") == 99999
    # neighbours untouched
    assert reg2.read_param_field(PARAM_NAME, 100, FIELD_OFF, "<i") == 700
    assert reg2.read_param_field(PARAM_NAME, 350, FIELD_OFF, "<i") == 2450
    with pytest.raises(KeyError):
        reg.patch_param_field(PARAM_NAME, 12345, FIELD_OFF, "<i", 1)


@need_deps
def test_regulation_noedit_round_trip_byte_identical():
    # The canary documented in regulation_io's header: decrypt -> re-encrypt
    # with no edits must be byte-identical (same zstd params, zero IV).
    raw, _ = make_regulation_bytes()
    assert R.Regulation.from_bytes(raw).to_bytes() == raw


# --------------------------------------------------------------------------- #
# atomic save (the in-place GUI shop-stage scenario)
# --------------------------------------------------------------------------- #
@need_deps
def test_save_writes_atomically(tmp_path):
    raw, _ = make_regulation_bytes()
    dest = tmp_path / "regulation.bin"
    dest.write_bytes(b"OLD JUNK")
    reg = R.Regulation.from_bytes(raw)
    reg.save(str(dest))
    assert dest.read_bytes() == raw
    assert [p.name for p in tmp_path.iterdir()] == ["regulation.bin"]


@need_deps
def test_save_in_place_load_patch_save(tmp_path):
    raw, _ = make_regulation_bytes()
    dest = tmp_path / "regulation.bin"
    dest.write_bytes(raw)
    reg = R.Regulation.load(str(dest))
    reg.patch_param_field(PARAM_NAME, 100, FIELD_OFF, "<i", -5)
    reg.save(str(dest))                            # src == dest, like the GUI
    assert R.Regulation.load(str(dest)).read_param_field(
        PARAM_NAME, 100, FIELD_OFF, "<i") == -5
    assert [p.name for p in tmp_path.iterdir()] == ["regulation.bin"]


@need_deps
def test_failed_replace_preserves_dest_and_cleans_temp(tmp_path, monkeypatch):
    raw, _ = make_regulation_bytes()
    dest = tmp_path / "regulation.bin"
    dest.write_bytes(raw)
    reg = R.Regulation.load(str(dest))
    reg.patch_param_field(PARAM_NAME, 100, FIELD_OFF, "<i", 42)

    def boom(src, dst):
        raise OSError("disk on fire")
    monkeypatch.setattr(R.os, "replace", boom)
    with pytest.raises(OSError):
        reg.save(str(dest))
    assert dest.read_bytes() == raw                # untouched
    assert [p.name for p in tmp_path.iterdir()] == ["regulation.bin"]  # no .tmp


@need_deps
def test_serialization_error_never_touches_dest(tmp_path, monkeypatch):
    raw, _ = make_regulation_bytes()
    dest = tmp_path / "regulation.bin"
    dest.write_bytes(raw)
    reg = R.Regulation.load(str(dest))
    monkeypatch.setattr(reg, "to_bytes",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("nope")))
    with pytest.raises(ValueError):
        reg.save(str(dest))
    assert dest.read_bytes() == raw
    assert [p.name for p in tmp_path.iterdir()] == ["regulation.bin"]
