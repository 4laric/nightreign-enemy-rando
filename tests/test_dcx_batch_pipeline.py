#!/usr/bin/env python3
"""Unit tests for dcx_batch.py — the pipeline orchestrator's step helpers.

The real Oodle DLL never ships with the repo, so these tests swap
dcx_batch.DCX for a trivial fake codec (magic-prefix strip/add) and pass an
oodle sentinel to bypass _Oodle.get(). That isolates exactly the logic this
module owns — file fan-out, the hub-map passthrough fast path, the
identity-skip fast path and its rewired-file opt-out, failure counting, and
the night-boss healthbar exclusion gate — from the codec itself
(dcx round-trips are covered by tests/test_encoding_explicit.py).

DCX_BATCH_WORKERS=1 keeps most tests on the serial path for determinism;
one test runs the ThreadPoolExecutor path.
"""

import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dcx_batch  # noqa: E402

MAGIC = b"FAKEDCX!"
OODLE = object()   # sentinel — never used by the fake codec


class FakeDCX:
    """Stand-in codec: 'compression' prepends MAGIC, 'decompression' strips it."""

    @staticmethod
    def decompress_file(path, oodle):
        data = open(path, "rb").read()
        if not data.startswith(MAGIC):
            raise ValueError("not a fake dcx")
        return data[len(MAGIC):]

    @staticmethod
    def compress_file(in_path, out_path, oodle=None):
        with open(in_path, "rb") as f:
            data = f.read()
        with open(out_path, "wb") as f:
            f.write(MAGIC + data)


@pytest.fixture
def fake_codec(monkeypatch):
    monkeypatch.setattr(dcx_batch, "DCX", FakeDCX)
    monkeypatch.setenv("DCX_BATCH_WORKERS", "1")


def _mkdcx(d, name, payload):
    p = os.path.join(str(d), name)
    with open(p, "wb") as f:
        f.write(MAGIC + payload)
    return p


# --------------------------------------------------------------------------- #
# _worker_count
# --------------------------------------------------------------------------- #
def test_worker_count_env_override(monkeypatch):
    monkeypatch.setenv("DCX_BATCH_WORKERS", "3")
    assert dcx_batch._worker_count() == 3
    monkeypatch.setenv("DCX_BATCH_WORKERS", "0")
    assert dcx_batch._worker_count() == 1          # floored at 1
    monkeypatch.setenv("DCX_BATCH_WORKERS", "banana")
    assert 1 <= dcx_batch._worker_count() <= 8     # invalid -> cpu default
    monkeypatch.delenv("DCX_BATCH_WORKERS")
    assert 1 <= dcx_batch._worker_count() <= 8     # capped at 8


# --------------------------------------------------------------------------- #
# decompress_dir
# --------------------------------------------------------------------------- #
def test_decompress_dir_basic(fake_codec, tmp_path):
    src, dst = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    _mkdcx(src, "m60_10_10_00.msb.dcx", b"alpha")
    _mkdcx(src, "m60_20_20_00.msb.dcx", b"beta")
    (src / "notes.txt").write_bytes(b"ignored")   # non-.msb.dcx is skipped

    n_ok, n_fail = dcx_batch.decompress_dir(str(src), str(dst), oodle=OODLE)
    assert (n_ok, n_fail) == (2, 0)
    assert (dst / "m60_10_10_00.msb").read_bytes() == b"alpha"
    assert (dst / "m60_20_20_00.msb").read_bytes() == b"beta"
    assert sorted(os.listdir(dst)) == ["m60_10_10_00.msb", "m60_20_20_00.msb"]


def test_decompress_dir_counts_failures(fake_codec, tmp_path):
    src, dst = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    _mkdcx(src, "good.msb.dcx", b"fine")
    (src / "bad.msb.dcx").write_bytes(b"no magic here")   # fake codec raises

    n_ok, n_fail = dcx_batch.decompress_dir(str(src), str(dst), oodle=OODLE)
    assert (n_ok, n_fail) == (1, 1)
    assert os.listdir(dst) == ["good.msb"]


def test_decompress_dir_hub_passthrough(fake_codec, tmp_path):
    """Hub maps skip decompression entirely: copied as DCX to the
    passthrough dest, NOT decompressed into out_dir."""
    src, dst, thru = tmp_path / "in", tmp_path / "out", tmp_path / "thru"
    src.mkdir()
    _mkdcx(src, "m11_10_00_00.msb.dcx", b"hub")     # passthrough
    _mkdcx(src, "m60_10_10_00.msb.dcx", b"world")   # normal

    n_ok, n_fail = dcx_batch.decompress_dir(
        str(src), str(dst), oodle=OODLE,
        passthrough_dcx_dest=str(thru),
        passthrough_set={"m11_10_00_00.msb.dcx"})
    assert (n_ok, n_fail) == (1, 0)                 # passthrough not in n_ok
    assert (thru / "m11_10_00_00.msb.dcx").read_bytes() == MAGIC + b"hub"
    assert os.listdir(dst) == ["m60_10_10_00.msb"]  # hub never decompressed


def test_decompress_dir_parallel_path(fake_codec, tmp_path, monkeypatch):
    monkeypatch.setenv("DCX_BATCH_WORKERS", "2")
    src, dst = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    for i in range(6):
        _mkdcx(src, f"m60_{i:02d}_00_00.msb.dcx", b"x%d" % i)
    n_ok, n_fail = dcx_batch.decompress_dir(str(src), str(dst), oodle=OODLE)
    assert (n_ok, n_fail) == (6, 0)
    assert len(os.listdir(dst)) == 6


# --------------------------------------------------------------------------- #
# compress_dir — identity-skip semantics
# --------------------------------------------------------------------------- #
def _identity_setup(tmp_path):
    """shuffled/, vanilla/, original_dcx/ for two maps: one untouched by the
    shuffle (identical bytes), one swapped (changed bytes)."""
    shuffled = tmp_path / "shuffled"; shuffled.mkdir()
    vanilla = tmp_path / "vanilla"; vanilla.mkdir()
    orig = tmp_path / "orig_dcx"; orig.mkdir()
    out = tmp_path / "out"

    (shuffled / "same.msb").write_bytes(b"untouched")
    (vanilla / "same.msb").write_bytes(b"untouched")
    # The shipped original DCX deliberately does NOT equal what the fake
    # codec would produce, so we can tell copy-from-original from recompress.
    (orig / "same.msb.dcx").write_bytes(b"ORIGINAL-GAME-BYTES")

    (shuffled / "diff.msb").write_bytes(b"swapped!")
    (vanilla / "diff.msb").write_bytes(b"untouched")
    (orig / "diff.msb.dcx").write_bytes(b"ORIGINAL-GAME-BYTES-2")
    return shuffled, vanilla, orig, out


def test_compress_dir_identity_skip(fake_codec, tmp_path):
    shuffled, vanilla, orig, out = _identity_setup(tmp_path)
    n_ok, n_fail = dcx_batch.compress_dir(
        str(shuffled), str(out), oodle=OODLE,
        vanilla_dir=str(vanilla), original_dcx_dir=str(orig))
    assert n_fail == 0
    # untouched map: original game DCX copied verbatim (codec never ran)
    assert (out / "same.msb.dcx").read_bytes() == b"ORIGINAL-GAME-BYTES"
    # swapped map: really recompressed
    assert (out / "diff.msb.dcx").read_bytes() == MAGIC + b"swapped!"


def test_compress_dir_rewired_files_opt_out_of_identity_skip(fake_codec, tmp_path):
    """skip_identity_files forces a real recompress even for identical bytes
    — the v0.23.75 rewired-MSB regression guard (vanilla_dir holds REWIRED
    bytes there; copying the original DCX would silently undo the rewire)."""
    shuffled, vanilla, orig, out = _identity_setup(tmp_path)
    n_ok, n_fail = dcx_batch.compress_dir(
        str(shuffled), str(out), oodle=OODLE,
        vanilla_dir=str(vanilla), original_dcx_dir=str(orig),
        skip_identity_files={"same.msb"})
    assert n_fail == 0
    assert (out / "same.msb.dcx").read_bytes() == MAGIC + b"untouched"


def test_compress_dir_without_identity_dirs_always_compresses(fake_codec, tmp_path):
    shuffled, _vanilla, _orig, out = _identity_setup(tmp_path)
    dcx_batch.compress_dir(str(shuffled), str(out), oodle=OODLE)
    assert (out / "same.msb.dcx").read_bytes() == MAGIC + b"untouched"
    assert (out / "diff.msb.dcx").read_bytes() == MAGIC + b"swapped!"


def test_compress_dir_counts_failures(fake_codec, tmp_path, monkeypatch):
    shuffled = tmp_path / "shuffled"; shuffled.mkdir()
    (shuffled / "a.msb").write_bytes(b"a")
    (shuffled / "b.msb").write_bytes(b"b")

    real = FakeDCX.compress_file

    class Flaky(FakeDCX):
        @staticmethod
        def compress_file(in_path, out_path, oodle=None):
            if os.path.basename(in_path) == "b.msb":
                raise RuntimeError("boom")
            real(in_path, out_path, oodle=oodle)

    monkeypatch.setattr(dcx_batch, "DCX", Flaky)
    n_ok, n_fail = dcx_batch.compress_dir(str(shuffled), str(tmp_path / "out"),
                                          oodle=OODLE)
    assert (n_ok, n_fail) == (1, 1)


# --------------------------------------------------------------------------- #
# night_boss_hb_exclude — healthbar gate mirrors the enemy-swap gate
# --------------------------------------------------------------------------- #
ARENAS = {"m40_00_00_00.msb", "m41_00_00_00.msb", "m42_00_00_00.msb"}


def _ns(**kw):
    base = dict(V3_NIGHT_BOSS_ARENA_MSBS=set(ARENAS),
                V3_NB_RANDOMIZE_WHITELIST=set(),
                V3_RANDOMIZE_ALL_NB_ARENAS=False,
                V3_RANDOMIZE_SAFE_NB_ARENAS=False,
                V3_SAFE_NB_RANDOMIZE_MSBS=set())
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_hb_exclude_all_preserved_when_nothing_randomized():
    out = dcx_batch.night_boss_hb_exclude(_ns())
    assert out == {m.replace(".msb", ".emevd") for m in ARENAS}


def test_hb_exclude_whitelist_removes_arena_from_exclusion():
    out = dcx_batch.night_boss_hb_exclude(
        _ns(V3_NB_RANDOMIZE_WHITELIST={"m40_00_00_00.msb"}))
    assert "m40_00_00_00.emevd" not in out
    assert out == {"m41_00_00_00.emevd", "m42_00_00_00.emevd"}


def test_hb_exclude_randomize_all_excludes_nothing():
    assert dcx_batch.night_boss_hb_exclude(
        _ns(V3_RANDOMIZE_ALL_NB_ARENAS=True)) == set()


def test_hb_exclude_safe_set_respected():
    out = dcx_batch.night_boss_hb_exclude(
        _ns(V3_RANDOMIZE_SAFE_NB_ARENAS=True,
            V3_SAFE_NB_RANDOMIZE_MSBS={"m41_00_00_00.msb"}))
    assert out == {"m40_00_00_00.emevd", "m42_00_00_00.emevd"}
