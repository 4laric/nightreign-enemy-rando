#!/usr/bin/env python3
"""Tests for me3_coherence - the profile/package/output coherence core.

These reproduce the reported bug (output left pointing at the previous profile
after a switch) and lock in the fix: diagnose() flags it as blocking + fixable.
Pure/offline; uses tmp dirs and a stub finder so nothing touches a real install.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import me3_coherence as C  # noqa: E402


def _make_profile(profile_dir, name, packages=()):
    os.makedirs(profile_dir, exist_ok=True)
    p = os.path.join(profile_dir, name)
    lines = ['profileVersion = "v1"', '', '[[supports]]', 'game = "nightreign"']
    for pkg in packages:
        lines += ['', '[[packages]]', f"path = '{pkg}'"]
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return p


def _make_package(pkg_dir, *, canonical=True):
    subs = ["map/mapstudio", "event", "chr"] if canonical else ["foo"]
    for s in subs:
        os.makedirs(os.path.join(pkg_dir, s), exist_ok=True)
    return pkg_dir


# --- path math ------------------------------------------------------------
def test_package_paths_are_canonical():
    pp = C.package_paths("/profiles/p1/nrando")
    assert pp["output"].endswith(os.path.join("nrando", "map", "mapstudio"))
    assert pp["event"].endswith(os.path.join("nrando", "event"))
    assert C._norm(pp["chr"]) == C._norm("/profiles/p1/nrando")


def test_is_within_is_separator_anchored():
    assert C.is_within("/a/b/c", "/a/b")
    assert not C.is_within("/a/bc", "/a/b")        # substring, not descendant
    assert C.is_within("/a/b", "/a/b")


# --- the reported bug -----------------------------------------------------
def test_stale_output_after_profile_switch_is_blocking_and_fixable(tmp_path):
    old = _make_package(str(tmp_path / "old" / "nrando"))
    new = _make_package(str(tmp_path / "new" / "nrando"))
    prof = _make_profile(str(tmp_path / "new"), "rando.me3", packages=["nrando/"])

    # Simulate post-"Add to existing": package switched to NEW, but output_dir
    # still points at OLD/map/mapstudio (the stale saved value).
    stale_output = os.path.join(old, "map", "mapstudio")
    d = C.diagnose(profile_path=prof, package_dir=new,
                   output_dir=stale_output,
                   event_dir=os.path.join(new, "event"))

    assert not d.coherent
    codes = {p.code for p in d.problems}
    assert "OUTPUT_NOT_CANONICAL" in codes
    assert d.blocking and all(p.code in {p2.code for p2 in d.problems}
                              for p in d.blocking)
    # The output problem is auto-fixable (repoint into the package).
    assert any(p.code == "OUTPUT_NOT_CANONICAL" and p.fixable for p in d.problems)
    assert C.paths_equal(d.expected_output, os.path.join(new, "map", "mapstudio"))


def test_coherent_layout_has_no_problems(tmp_path):
    pkg = _make_package(str(tmp_path / "p" / "nrando"))
    prof = _make_profile(str(tmp_path / "p"), "rando.me3", packages=["nrando/"])
    d = C.diagnose(profile_path=prof, package_dir=pkg,
                   output_dir=os.path.join(pkg, "map", "mapstudio"),
                   event_dir=os.path.join(pkg, "event"))
    assert d.coherent, [p.code for p in d.problems]


def test_output_inside_package_but_wrong_subdir_flagged(tmp_path):
    pkg = _make_package(str(tmp_path / "p" / "nrando"))
    prof = _make_profile(str(tmp_path / "p"), "rando.me3", packages=["nrando/"])
    d = C.diagnose(profile_path=prof, package_dir=pkg,
                   output_dir=os.path.join(pkg, "foo"),   # inside pkg, wrong place
                   event_dir=os.path.join(pkg, "event"))
    out = [p for p in d.problems if p.code == "OUTPUT_NOT_CANONICAL"]
    assert out and "not at map/mapstudio" in out[0].message


def test_unregistered_package_flagged_fixable(tmp_path):
    pkg = _make_package(str(tmp_path / "p" / "nrando"))
    prof = _make_profile(str(tmp_path / "p"), "rando.me3", packages=[])  # empty
    d = C.diagnose(profile_path=prof, package_dir=pkg,
                   output_dir=os.path.join(pkg, "map", "mapstudio"),
                   event_dir=os.path.join(pkg, "event"))
    miss = [p for p in d.problems if p.code == "PROFILE_MISSING_PACKAGE"]
    assert miss and miss[0].fixable


# --- single-finder behaviour: tracked profile beats discovery -------------
def test_tracked_profile_wins_over_discovery(tmp_path):
    pkg = _make_package(str(tmp_path / "p" / "nrando"))
    tracked = _make_profile(str(tmp_path / "p"), "user.me3", packages=["nrando/"])
    # A finder that would pick a DIFFERENT file must be overridden by the
    # explicitly-tracked profile.
    bogus = os.path.join(str(tmp_path / "p"), "other.me3")
    open(bogus, "w", encoding="utf-8").close()
    assert C.resolve_profile(tracked, pkg, finder=lambda _p: bogus) == \
        os.path.abspath(tracked)


def test_resolve_falls_back_to_finder_when_untracked(tmp_path):
    pkg = _make_package(str(tmp_path / "p" / "nrando"))
    disc = _make_profile(str(tmp_path / "p"), "disc.me3", packages=["nrando/"])
    assert C.resolve_profile("", pkg, finder=lambda _p: disc) == \
        os.path.abspath(disc)


def test_no_package_short_circuits(tmp_path):
    d = C.diagnose(profile_path="", package_dir=str(tmp_path / "nope"),
                   output_dir="", event_dir=None)
    assert [p.code for p in d.problems] == ["NO_PACKAGE"]
