"""Tests for the packed-install UX relaxations:
  - validate_path_kind accepts a PACKED NR/ER install (dvdbnd archives present,
    no UXM unpack) as 'ok', since the archive reader reads vanilla data directly.
  - find_package_in_single_subdir descends from a wrongly-picked PARENT dir into
    the single package subdir (the one that has map/, chr/, etc.).
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "dev")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from oops_rando_gui import validate_path_kind          # noqa: E402
from install_discovery import find_package_in_single_subdir  # noqa: E402


def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


# ---------------------------------------------- validate_path_kind: packed = ok

def test_nr_packed_install_ok(tmp_path):
    """Packed NR Game/ (dvdbnd archives, no loose map/mapstudio) is now OK."""
    game = tmp_path / "Game"
    game.mkdir()
    _touch(game / "data0.bhd")
    _touch(game / "regulation.bin")
    state, detail = validate_path_kind(str(game), "nr_install")
    assert state == "ok"
    assert "packed" in detail.lower()


def test_nr_unpacked_still_ok(tmp_path):
    game = tmp_path / "Game"
    ms = game / "map" / "mapstudio"
    ms.mkdir(parents=True)
    _touch(ms / "m10_00_00_00.msb.dcx")
    state, _ = validate_path_kind(str(game), "nr_install")
    assert state == "ok"


def test_nr_empty_mapstudio_no_archives_warns(tmp_path):
    """A bare empty mapstudio with no archives/exe is still a warn (regression)."""
    game = tmp_path / "Game"
    (game / "map" / "mapstudio").mkdir(parents=True)
    state, detail = validate_path_kind(str(game), "nr_install")
    assert state == "warn"
    assert "mapstudio" in detail.lower()


def test_er_packed_install_ok(tmp_path):
    """Packed ER Game/ (dvdbnd archives, no loose chr) is OK for --source-game."""
    game = tmp_path / "Game"
    game.mkdir()
    _touch(game / "Data0.bhd")
    state, detail = validate_path_kind(str(game), "er_install")
    assert state == "ok"
    assert "packed" in detail.lower()


def test_er_unpacked_still_ok(tmp_path):
    game = tmp_path / "Game"
    chrd = game / "chr"
    chrd.mkdir(parents=True)
    _touch(chrd / "c2110.chrbnd.dcx")
    state, _ = validate_path_kind(str(game), "er_install")
    assert state == "ok"


def test_er_non_install_is_warn_not_error(tmp_path):
    nope = tmp_path / "random"
    nope.mkdir()
    state, _ = validate_path_kind(str(nope), "er_install")
    assert state == "warn"


# ------------------------------------ find_package_in_single_subdir: descend

def test_descends_into_single_package_subdir(tmp_path):
    parent = tmp_path / "mods"
    parent.mkdir()
    pkg = parent / "nrando-pkg"
    (pkg / "map" / "mapstudio").mkdir(parents=True)
    (pkg / "chr").mkdir()
    got = find_package_in_single_subdir(str(parent))
    assert got is not None
    assert os.path.normpath(got) == os.path.normpath(str(pkg))


def test_no_descend_when_already_a_package(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "map").mkdir(parents=True)
    assert find_package_in_single_subdir(str(pkg)) is None


def test_no_descend_when_ambiguous(tmp_path):
    parent = tmp_path / "mods"
    parent.mkdir()
    (parent / "pkgA" / "map").mkdir(parents=True)
    (parent / "pkgB" / "chr").mkdir(parents=True)
    assert find_package_in_single_subdir(str(parent)) is None


def test_no_descend_when_no_package_subdir(tmp_path):
    parent = tmp_path / "mods"
    parent.mkdir()
    (parent / "junk").mkdir()
    (parent / "readme.txt").write_text("x")
    assert find_package_in_single_subdir(str(parent)) is None


def test_nonexistent_returns_none():
    assert find_package_in_single_subdir("/no/such/dir/xyz123") is None
