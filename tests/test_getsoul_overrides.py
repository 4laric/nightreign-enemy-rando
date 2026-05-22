"""Tests for the getSoul rune-drop floor overrides.

V3_GETSOUL_TIER_FLOORS (in oops_v3.py) holds the per-tier placement-
weighted vanilla median getSoul. dev/emit_getsoul_overrides.py uses it
to emit data/npcparam_getsoul_overrides.csv — the NpcParam patch
imported into the user's regulation.bin via Smithbox.

Policy: uplift any NpcParam row below its chr's tier floor up to that
floor; leave rows at/above alone. Tier-driven (no hand-curated chr
list), so coverage can't silently miss a chr the way it once missed
c4181 Maris' Jellyfish.

These tests guard table<->CSV consistency so "regenerate and re-import"
stays a reliable instruction.
"""
import csv
import os
import statistics
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

CSV_PATH = os.path.join(REPO_ROOT, 'data', 'npcparam_getsoul_overrides.csv')
NPCPARAM_PATH = os.path.join(REPO_ROOT, 'data', 'NpcParam.csv')
TAGS_PATH = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')
SLOTS_PATH = os.path.join(REPO_ROOT, 'data', 'nr_all_slots.json')

ELIGIBLE_TIERS = ('nightlord', 'night_boss', 'field_boss', 'miniboss', 'grunt')


def _floors():
    import oops_v3
    return oops_v3.V3_GETSOUL_TIER_FLOORS


def _npc_id_to_cprefix(npc_id):
    s = str(npc_id)
    return 'c' + s[:4] if len(s) >= 8 else None


def test_tier_floors_cover_all_eligible_tiers():
    floors = _floors()
    for tier in ELIGIBLE_TIERS:
        assert tier in floors, f"V3_GETSOUL_TIER_FLOORS missing tier {tier!r}"
        assert isinstance(floors[tier], int) and floors[tier] > 0


def test_override_csv_exists_and_well_formed():
    assert os.path.isfile(CSV_PATH), (
        f"{CSV_PATH} missing. Run: python3 dev/emit_getsoul_overrides.py")
    with open(CSV_PATH, encoding='utf-8') as f:
        header = next(csv.reader(f))
    assert header == ['ID', 'getSoul'], (
        f"getSoul CSV header should be ['ID','getSoul'], got {header}")


def test_floors_match_placement_weighted_medians():
    """V3_GETSOUL_TIER_FLOORS must equal the placement-weighted vanilla
    median per tier — that's the documented derivation. Catches a floor
    being hand-edited without re-deriving."""
    import json
    if not (os.path.isfile(NPCPARAM_PATH) and os.path.isfile(TAGS_PATH)
            and os.path.isfile(SLOTS_PATH)):
        import pytest
        pytest.skip("data inputs not available")

    with open(TAGS_PATH, encoding='utf-8') as f:
        tags = json.load(f)
    with open(SLOTS_PATH, encoding='utf-8') as f:
        slots = json.load(f)
    placement = Counter(s['c_prefix'] for s in slots)

    cp_gs = defaultdict(list)
    with open(NPCPARAM_PATH, encoding='utf-8', errors='replace') as f:
        r = csv.reader(f)
        h = next(r)
        i_id, i_gs = h.index('ID'), h.index('getSoul')
        for row in r:
            if len(row) <= max(i_id, i_gs):
                continue
            try:
                nid, gs = int(row[i_id]), int(row[i_gs])
            except ValueError:
                continue
            cp = _npc_id_to_cprefix(nid)
            if cp:
                cp_gs[cp].append(gs)
    cp_repr = {cp: statistics.median([v for v in vals if v > 0])
               for cp, vals in cp_gs.items() if any(v > 0 for v in vals)}

    floors = _floors()
    for tier in ELIGIBLE_TIERS:
        weighted = []
        for cp, rep in cp_repr.items():
            if tags.get(cp, {}).get('tier') == tier:
                weighted.extend([rep] * placement.get(cp, 0))
        derived = int(statistics.median(weighted)) if weighted else None
        assert floors[tier] == derived, (
            f"V3_GETSOUL_TIER_FLOORS[{tier!r}]={floors[tier]} but the "
            f"placement-weighted vanilla median is {derived}. Re-derive "
            f"and update the table.")


def test_csv_is_a_complete_emission_of_the_floors():
    """The committed CSV must match a fresh emission: every NpcParam
    row below its tier floor present at exactly the floor value, and
    nothing else."""
    import json
    if not (os.path.isfile(NPCPARAM_PATH) and os.path.isfile(TAGS_PATH)):
        import pytest
        pytest.skip("data inputs not available")

    with open(TAGS_PATH, encoding='utf-8') as f:
        tags = json.load(f)
    floors = _floors()

    expected = {}
    with open(NPCPARAM_PATH, encoding='utf-8', errors='replace') as f:
        r = csv.reader(f)
        h = next(r)
        i_id, i_gs = h.index('ID'), h.index('getSoul')
        for row in r:
            if len(row) <= max(i_id, i_gs):
                continue
            try:
                nid, gs = int(row[i_id]), int(row[i_gs])
            except ValueError:
                continue
            tier = tags.get(_npc_id_to_cprefix(nid), {}).get('tier')
            floor = floors.get(tier)
            if floor is not None and gs < floor:
                expected[nid] = floor

    actual = {}
    with open(CSV_PATH, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            actual[int(row['ID'])] = int(row['getSoul'])

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    wrong = sorted(i for i in (set(expected) & set(actual))
                   if expected[i] != actual[i])
    msg = []
    if missing:
        msg.append(f"{len(missing)} expected rows absent from CSV "
                   f"(first: {missing[:8]})")
    if extra:
        msg.append(f"{len(extra)} CSV rows not derivable (first: {extra[:8]})")
    if wrong:
        msg.append(f"{len(wrong)} rows with wrong value (first: {wrong[:8]})")
    assert not msg, (
        "npcparam_getsoul_overrides.csv is stale — run "
        "dev/emit_getsoul_overrides.py:\n  " + "\n  ".join(msg))


def test_maris_jellyfish_covered():
    """Regression guard for the bug that started this: c4181 Maris'
    Jellyfish (S-size grunt) must be uplifted. Its NpcParam rows are
    41810xxx; all are vanilla getSoul=0, so all must appear in the CSV
    at the grunt floor."""
    floors = _floors()
    grunt_floor = floors['grunt']
    found = []
    with open(CSV_PATH, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['ID'].startswith('4181'):
                found.append((row['ID'], int(row['getSoul'])))
    assert found, (
        "c4181 Maris' Jellyfish has no rows in the getSoul override "
        "CSV — the tier-driven uplift should cover every grunt.")
    for npc_id, val in found:
        assert val == grunt_floor, (
            f"NpcParam {npc_id} (Maris' Jellyfish) uplifted to {val}, "
            f"expected grunt floor {grunt_floor}")
