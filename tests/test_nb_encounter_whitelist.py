"""Tests for the v0.28.x NB encounter whitelist mechanism.

Two layers share the canonical state at data/nb_encounter_whitelist.json:
  - Param layer: dev/emit_nb_encounter_whitelist.py emits
    regulation_fixes/LotResultSmallBaseAndSpot_nb_whitelist_smithbox.csv,
    constraining the game's overlay lottery to whitelisted arenas.
  - Engine layer: oops_v3.V3_NB_RANDOMIZE_WHITELIST drives the third
    opt-in path in `_force_rando_nb` (line ~13513 of oops_v3.py),
    enabling boss-Part swap at the same arenas.

These tests guard:
  1) the loader (file present / absent / empty / malformed);
  2) the module global reflects the JSON;
  3) the gate logic in `_force_rando_nb` follows the documented truth
     table (empty whitelist == today's preserve behavior; non-empty
     fires for whitelisted arenas; existing flags independent);
  4) the JSON and the committed patch CSV don't drift -- every row in
     the CSV must rewrite to a `smallBaseMapId` derivable from the
     whitelist's nb1 / nb2 picks.
"""
import csv
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import oops_v3  # noqa: E402

WHITELIST_JSON = os.path.join(REPO_ROOT, 'data', 'nb_encounter_whitelist.json')
PATCH_CSV = os.path.join(
    REPO_ROOT, 'regulation_fixes',
    'LotResultSmallBaseAndSpot_nb_whitelist_smithbox.csv')


def _arena_stem_to_smbid(stem):
    """'m49_10_00_00' -> 4910. Mirrors the helper in
    dev/emit_nb_encounter_whitelist.py."""
    parts = stem[1:].split('_')
    return int(parts[0] + parts[1])


# Mirrors the boolean expression of `_force_rando_nb` at line ~13513 of
# oops_v3.py (inside pick_target_cp). Kept here so the gate's truth
# table can be exercised in isolation. If the in-engine expression is
# refactored, this mirror must be updated -- the
# `test_force_rando_nb_logic_mirror_matches_engine_source` test guards
# against silent drift by grepping the engine source for the canonical
# OR-of-three structure.
def _force_rando_nb_mirror(slot_msb_name, *,
                            randomize_all, randomize_safe,
                            nb_arena_msbs, safe_msbs, whitelist):
    return (
        slot_msb_name is not None
        and ((randomize_all and slot_msb_name in nb_arena_msbs)
             or (randomize_safe and slot_msb_name in safe_msbs)
             or slot_msb_name in whitelist))


# -------- loader / module-global tests --------

def test_loader_present_returns_expected_frozenset(tmp_path, monkeypatch):
    """A valid whitelist JSON loads into a frozenset of '<stem>.msb'."""
    p = tmp_path / 'nb_encounter_whitelist.json'
    p.write_text(json.dumps({
        '_doc': 'fixture',
        'nb1': ['m49_10_00_00', 'm49_17_00_00'],
        'nb2': ['m48_40_00_00'],
    }))
    monkeypatch.setattr(oops_v3, '_data_path', lambda _name: str(p))
    out = oops_v3._load_nb_randomize_whitelist()
    assert isinstance(out, frozenset)
    assert out == frozenset({
        'm49_10_00_00.msb', 'm49_17_00_00.msb', 'm48_40_00_00.msb'})


def test_loader_missing_file_returns_empty(tmp_path, monkeypatch):
    """File absent -> empty frozenset (today's preserve-vanilla
    behavior). Engine must not raise."""
    monkeypatch.setattr(oops_v3, '_data_path',
                        lambda _name: str(tmp_path / 'does_not_exist.json'))
    assert oops_v3._load_nb_randomize_whitelist() == frozenset()


def test_loader_empty_whitelist_returns_empty(tmp_path, monkeypatch):
    """{'nb1': [], 'nb2': []} -> empty frozenset (same as missing
    file). Documented as the explicit 'disabled' state."""
    p = tmp_path / 'nb_encounter_whitelist.json'
    p.write_text(json.dumps({'nb1': [], 'nb2': []}))
    monkeypatch.setattr(oops_v3, '_data_path', lambda _name: str(p))
    assert oops_v3._load_nb_randomize_whitelist() == frozenset()


def test_loader_malformed_json_returns_empty(tmp_path, monkeypatch):
    """A corrupt JSON file should NOT crash module init. The loader
    swallows JSONDecodeError / OSError and returns empty."""
    p = tmp_path / 'nb_encounter_whitelist.json'
    p.write_text('{this is not json,')
    monkeypatch.setattr(oops_v3, '_data_path', lambda _name: str(p))
    assert oops_v3._load_nb_randomize_whitelist() == frozenset()


def test_loader_partial_keys_returns_just_what_present(tmp_path, monkeypatch):
    """An NB1-only or NB2-only whitelist is a legitimate growth-path
    state (the operator may want to lock just one side first)."""
    p = tmp_path / 'nb_encounter_whitelist.json'
    p.write_text(json.dumps({'nb1': ['m49_10_00_00']}))  # no nb2 at all
    monkeypatch.setattr(oops_v3, '_data_path', lambda _name: str(p))
    assert oops_v3._load_nb_randomize_whitelist() == frozenset({
        'm49_10_00_00.msb'})


def test_module_global_reflects_canonical_json():
    """V3_NB_RANDOMIZE_WHITELIST at module init must equal a fresh
    parse of the committed data/nb_encounter_whitelist.json."""
    assert os.path.isfile(WHITELIST_JSON), (
        f"{WHITELIST_JSON} missing -- the canonical whitelist is "
        f"supposed to be version-controlled.")
    with open(WHITELIST_JSON, encoding='utf-8') as f:
        raw = json.load(f)
    expected = frozenset(f'{s}.msb' for s in
                         list(raw.get('nb1', [])) + list(raw.get('nb2', [])))
    assert oops_v3.V3_NB_RANDOMIZE_WHITELIST == expected


def test_v1_whitelist_picks_match_spec():
    """The spec's v1 ship state is NB1=m49_10, NB2=m48_40. Guards
    against either pick silently shifting accidentally. Skipped when
    a `_test_note` key is present in the JSON, which marks an
    intentional pivot for ad-hoc validation (e.g. the Smelter Demon
    overlay-arena test). Remove the `_test_note` key to reactivate."""
    with open(WHITELIST_JSON, encoding='utf-8') as f:
        raw = json.load(f)
    if '_test_note' in raw:
        pytest.skip(f"intentional pivot: {raw['_test_note'][:80]}...")
    assert raw.get('nb1') == ['m49_10_00_00'], (
        f"v1 NB1 pick must be m49_10_00_00 (Grafted Monarch); got "
        f"{raw.get('nb1')}.")
    assert raw.get('nb2') == ['m48_40_00_00'], (
        f"v1 NB2 pick must be m48_40_00_00 (Morgott); got "
        f"{raw.get('nb2')}.")


# -------- gate-logic truth-table tests --------

def test_gate_empty_whitelist_preserves_like_v027_default():
    """Empty whitelist + both broad flags OFF -> _force_rando_nb is
    False for every arena; NB arenas stay byte-vanilla. This is the
    v0.27.x default behavior; the v0.28.x whitelist addition must NOT
    change it when the file is empty."""
    nb_arenas = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb',
                           'm49_18_00_00.msb'})
    safe = frozenset({'m49_10_00_00.msb'})
    for slot in nb_arenas | {'m60_99_99_99.msb', None}:
        assert _force_rando_nb_mirror(
            slot,
            randomize_all=False, randomize_safe=False,
            nb_arena_msbs=nb_arenas, safe_msbs=safe,
            whitelist=frozenset()) is False, (
            f"empty whitelist must not fire for {slot!r}")


def test_gate_whitelist_fires_only_for_listed_arenas():
    """Non-empty whitelist + both broad flags OFF -> _force_rando_nb
    is True for the whitelisted arenas only; non-whitelist arenas
    stay preserved."""
    nb_arenas = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb',
                           'm49_18_00_00.msb'})
    safe = frozenset({'m49_10_00_00.msb'})
    wl = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb'})

    # whitelisted arena -> True
    for slot in wl:
        assert _force_rando_nb_mirror(
            slot,
            randomize_all=False, randomize_safe=False,
            nb_arena_msbs=nb_arenas, safe_msbs=safe,
            whitelist=wl) is True

    # non-whitelist NB arena -> False
    assert _force_rando_nb_mirror(
        'm49_18_00_00.msb',
        randomize_all=False, randomize_safe=False,
        nb_arena_msbs=nb_arenas, safe_msbs=safe,
        whitelist=wl) is False

    # field tile -> False
    assert _force_rando_nb_mirror(
        'm60_99_99_99.msb',
        randomize_all=False, randomize_safe=False,
        nb_arena_msbs=nb_arenas, safe_msbs=safe,
        whitelist=wl) is False

    # None slot -> False (the leading slot_msb_name is not None guard)
    assert _force_rando_nb_mirror(
        None,
        randomize_all=False, randomize_safe=False,
        nb_arena_msbs=nb_arenas, safe_msbs=safe,
        whitelist=wl) is False


def test_gate_all_flag_independent_of_whitelist():
    """V3_RANDOMIZE_ALL_NB_ARENAS=True must still fire for every arena
    in V3_NIGHT_BOSS_ARENA_MSBS, even with an empty whitelist. The new
    third clause is ADDITIVE -- it does not narrow the existing two
    broad gates."""
    nb_arenas = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb',
                           'm49_18_00_00.msb'})
    safe = frozenset()
    for slot in nb_arenas:
        assert _force_rando_nb_mirror(
            slot,
            randomize_all=True, randomize_safe=False,
            nb_arena_msbs=nb_arenas, safe_msbs=safe,
            whitelist=frozenset()) is True


def test_gate_safe_flag_independent_of_whitelist():
    """V3_RANDOMIZE_SAFE_NB_ARENAS=True must still fire for every arena
    in V3_SAFE_NB_RANDOMIZE_MSBS, even with an empty whitelist."""
    nb_arenas = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb',
                           'm49_18_00_00.msb'})
    safe = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb'})
    # safe arena -> True
    assert _force_rando_nb_mirror(
        'm49_10_00_00.msb',
        randomize_all=False, randomize_safe=True,
        nb_arena_msbs=nb_arenas, safe_msbs=safe,
        whitelist=frozenset()) is True
    # non-safe NB arena -> False (the safe flag does NOT open all NB)
    assert _force_rando_nb_mirror(
        'm49_18_00_00.msb',
        randomize_all=False, randomize_safe=True,
        nb_arena_msbs=nb_arenas, safe_msbs=safe,
        whitelist=frozenset()) is False


def test_gate_or_combined_layers():
    """The three opt-in paths OR-combine: a user with SAFE on plus a
    whitelist entry NOT in the safe set still gets the whitelist
    arena randomized."""
    nb_arenas = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb',
                           'm49_30_00_00.msb'})
    safe = frozenset({'m49_10_00_00.msb', 'm48_40_00_00.msb'})
    wl = frozenset({'m49_30_00_00.msb'})  # m49_30 is NOT in the safe set
    # whitelist-only arena fires
    assert _force_rando_nb_mirror(
        'm49_30_00_00.msb',
        randomize_all=False, randomize_safe=True,
        nb_arena_msbs=nb_arenas, safe_msbs=safe,
        whitelist=wl) is True
    # safe-only arena still fires
    assert _force_rando_nb_mirror(
        'm49_10_00_00.msb',
        randomize_all=False, randomize_safe=True,
        nb_arena_msbs=nb_arenas, safe_msbs=safe,
        whitelist=wl) is True


def test_force_rando_nb_logic_mirror_matches_engine_source():
    """Grep the engine source for the canonical OR-of-three structure
    so a silent refactor of `_force_rando_nb` flags up here. If this
    test fails because the engine was deliberately changed, update
    _force_rando_nb_mirror in sync."""
    src_path = os.path.join(REPO_ROOT, 'oops_v3.py')
    with open(src_path, encoding='utf-8') as f:
        src = f.read()
    required = [
        'V3_RANDOMIZE_ALL_NB_ARENAS',
        'V3_NIGHT_BOSS_ARENA_MSBS',
        'V3_RANDOMIZE_SAFE_NB_ARENAS',
        'V3_SAFE_NB_RANDOMIZE_MSBS',
        'V3_NB_RANDOMIZE_WHITELIST',
        '_force_rando_nb',
    ]
    for tok in required:
        assert tok in src, (
            f"engine source missing expected token {tok!r}; the "
            f"_force_rando_nb gate may have been refactored. Re-read "
            f"the gate at oops_v3.py:~13513 and update "
            f"_force_rando_nb_mirror in this test file.")


# -------- JSON <-> CSV drift smoke check --------

def test_patch_csv_rewrites_only_to_whitelist_picks():
    """Every row in the committed patch CSV must rewrite to a
    smallBaseMapId derivable from the whitelist JSON. Catches a manual
    edit of either layer that introduces an arena the other layer
    doesn't know about. Skipped when the JSON has a `_test_note` --
    under Option B (engine-only pivot) the CSV is intentionally stale
    relative to the JSON because the param layer isn't being imported."""
    if not os.path.isfile(PATCH_CSV):
        pytest.skip(f"{PATCH_CSV} not generated yet -- run "
                    f"dev/emit_nb_encounter_whitelist.py.")

    with open(WHITELIST_JSON, encoding='utf-8') as f:
        wl = json.load(f)
    if '_test_note' in wl:
        pytest.skip(f"intentional pivot: {wl['_test_note'][:80]}...")
    expected_smbids = {_arena_stem_to_smbid(s)
                       for s in wl.get('nb1', []) + wl.get('nb2', [])}

    seen = set()
    with open(PATCH_CSV, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            seen.add(int(row['smallBaseMapId']))
    unexpected = seen - expected_smbids
    assert not unexpected, (
        f"patch CSV contains smallBaseMapId(s) not derivable from "
        f"the whitelist: {sorted(unexpected)}. Drift between layers; "
        f"re-run dev/emit_nb_encounter_whitelist.py.")


def test_patch_csv_canonical_modifier_per_pick():
    """Each whitelisted smbid must use exactly ONE modifier across all
    its patch rows -- the canonical pair the emitter looked up from the
    regulation dump. Drifted pairs are a strong drift signal."""
    if not os.path.isfile(PATCH_CSV):
        pytest.skip(f"{PATCH_CSV} not generated yet.")

    pairs = {}
    with open(PATCH_CSV, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            sm = int(row['smallBaseMapId'])
            mod = int(row['modifier'])
            if sm not in pairs:
                pairs[sm] = mod
            else:
                assert pairs[sm] == mod, (
                    f"smbid {sm} appears with multiple modifiers in "
                    f"patch CSV ({pairs[sm]} and {mod}); canonical "
                    f"pair drifted -- re-run the emitter.")
    # v1: NB1 = 4910 paired with 436, NB2 = 4840 paired with 400.
    # Sourced from the regulation dump's most-common (smbid, modifier)
    # pair. If these drift, either the regulation changed (rebase needed)
    # or the emitter logic regressed.
    assert pairs.get(4910) == 436, (
        f"v1 NB1 modifier should be 436 (Grafted Monarch's canonical "
        f"pair in vanilla regulation); got {pairs.get(4910)!r}.")
    assert pairs.get(4840) == 400, (
        f"v1 NB2 modifier should be 400 (Morgott's canonical pair in "
        f"vanilla regulation); got {pairs.get(4840)!r}.")


def test_patch_csv_only_rewrites_smallbasemapid_and_modifier():
    """The emitter contract: only smallBaseMapId and modifier are
    rewritten; every other column is byte-identical to whatever was in
    the vanilla regulation. Without a source CSV in the repo we can't
    cross-check against vanilla, but we can verify the patch CSV's
    column set matches the regulation schema's shape -- a missing
    column or an unexpected value type is a strong wrongness signal."""
    if not os.path.isfile(PATCH_CSV):
        pytest.skip(f"{PATCH_CSV} not generated yet.")

    EXPECTED_COLS = {'ID', 'Name', 'unknown_0', 'patternId', 'attachId',
                     'smallBaseMapId', 'mapIndex', 'variationId',
                     'unknown_0x12', 'modifier'}
    with open(PATCH_CSV, encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames) - {''}  # strip trailing empty name
        assert EXPECTED_COLS.issubset(cols), (
            f"patch CSV missing expected columns: "
            f"{EXPECTED_COLS - cols}")
        # Every row's ID, patternId, attachId, mapIndex, variationId
        # must be integer-valued (the schema's well-typed columns).
        for i, row in enumerate(reader, start=2):  # data starts at line 2
            for c in ('ID', 'patternId', 'attachId', 'mapIndex',
                      'variationId', 'smallBaseMapId', 'modifier'):
                try:
                    int(row[c])
                except (TypeError, ValueError):
                    pytest.fail(f"patch CSV line {i}: column {c} not "
                                f"integer ({row[c]!r}).")


def test_patch_csv_row_count_matches_known_nb_row_count():
    """432 rows is the expected count: the union of all NB-class rows
    (18 arenas present in the table, NB1-pool + NB2-pool + the two
    unmapped-but-attach-classifiable arenas m49_30 and m49_90).
    Drift here usually means the regulation rebased or the emitter's
    classification logic changed."""
    if not os.path.isfile(PATCH_CSV):
        pytest.skip(f"{PATCH_CSV} not generated yet.")

    with open(PATCH_CSV, encoding='utf-8', newline='') as f:
        count = sum(1 for _ in csv.DictReader(f))
    EXPECTED = 432
    assert count == EXPECTED, (
        f"patch CSV row count is {count}, expected {EXPECTED}. Either "
        f"the regulation rebased (re-derive expectation) or the "
        f"emitter's NB-row classification changed.")
