"""Tests for npcparam_getsoul_fill - the runtime getSoul (rune-reward) floor.

Pure tests exercise roll() against synthetic getsoul_data and never need a
regulation. The end-to-end tests run only when the bundled regulation.bin and
the crypto/zstd deps are present, and verify the floor lands on the real reg.
"""
import importlib
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GS = importlib.import_module("npcparam_getsoul_fill")
R = importlib.import_module("regulation_io")
RR = importlib.import_module("regulation_rando")

REG = os.path.join(ROOT, "bundled_regulation", "regulation.bin")
DATA = os.path.join(ROOT, "data")

need_reg = pytest.mark.skipif(not os.path.exists(REG), reason="no bundled regulation.bin")
need_deps = pytest.mark.skipif(not RR.deps_available(),
                               reason="cryptography/zstandard not installed")

FLOORS = {"grunt": 100, "miniboss": 450, "field_boss": 4687,
          "night_boss": 2910, "nightlord": 4375}


def _data(current):
    return {"current": current, "floors": FLOORS}


# --------------------------------------------------------------------------- #
# pure roll() - the floor policy
# --------------------------------------------------------------------------- #
def test_floors_only_below_and_up_to_floor():
    # below -> floored to the floor; equal -> untouched; above -> untouched.
    data = _data({1: ("grunt", 50), 2: ("grunt", 100), 3: ("grunt", 250),
                  4: ("nightlord", 0), 5: ("miniboss", 451)})
    patches, spoiler = GS.roll(data)
    assert patches == {1: 100, 4: 4375}
    assert spoiler == [
        {"npc_param_id": 1, "tier": "grunt", "getSoul_was": 50, "getSoul": 100},
        {"npc_param_id": 4, "tier": "nightlord", "getSoul_was": 0, "getSoul": 4375},
    ]


def test_never_lowers_any_row():
    data = _data({i: ("field_boss", v) for i, v in
                  enumerate([0, 100, 4686, 4687, 4688, 50000])})
    patches, _ = GS.roll(data)
    for nid, new in patches.items():
        old = data["current"][nid][1]
        assert new > old and new == FLOORS["field_boss"]
    # rows at/above the floor are absent from patches (indices 3,4,5).
    assert 3 not in patches and 4 not in patches and 5 not in patches


def test_deterministic_and_seed_independent():
    data = _data({1: ("grunt", 0), 2: ("miniboss", 10), 3: ("nightlord", 9000)})
    p_none, _ = GS.roll(data)
    p_a, _ = GS.roll(data, seed="8675309")
    p_b, _ = GS.roll(data, seed="42")
    # a floor is a fixed correction: identical regardless of seed (or no seed).
    assert p_none == p_a == p_b == {1: 100, 2: 450}


def test_unknown_tier_is_skipped():
    data = _data({1: ("__bogus__", 0), 2: ("grunt", 0)})
    patches, _ = GS.roll(data)
    assert patches == {2: 100}


def test_offset_constant_guard():
    # getSoul sits between hp@0x24 and itemLotId_enemy@0x30; a silent edit here
    # would corrupt a different field, so pin it.
    assert GS.GS_OFF == 0x2c and GS.NPCPARAM == "NpcParam"


# --------------------------------------------------------------------------- #
# end-to-end (real regulation + deps)
# --------------------------------------------------------------------------- #
@need_reg
@need_deps
def test_extract_reads_plausible_getsoul():
    reg = R.Regulation.load(REG)
    data = GS.extract(reg, DATA)
    assert data["current"], "no roster rows resolved"
    for _nid, (tier, gs) in data["current"].items():
        assert tier in data["floors"]
        assert 0 <= gs <= 1_000_000          # non-negative, bounded: offset net


@need_reg
@need_deps
def test_apply_floors_on_real_reg():
    import oops_v3
    v3 = oops_v3.V3_GETSOUL_TIER_FLOORS
    reg = R.Regulation.load(REG)
    before = dict(GS.extract(reg, DATA)["current"])   # {nid: (tier, gs)}
    patches, _ = GS.roll(GS.extract(reg, DATA))
    n = GS.apply_patches(reg, patches)
    assert n == len(patches) and n > 0

    off, _sz, rows = reg._param(GS.NPCPARAM)
    bnd = reg.bnd

    def cur(nid):
        return struct.unpack_from("<i", bnd, off + rows[nid] + GS.GS_OFF)[0]

    for nid, (tier, was) in before.items():
        now = cur(nid)
        assert now >= was                              # never lowered
        if nid in patches:
            assert now == patches[nid] == v3[tier] and now > was
        else:
            assert now == was                          # untouched

    # idempotent: re-rolling after applying the floor yields nothing more.
    again, _ = GS.roll(GS.extract(reg, DATA))
    assert again == {}
