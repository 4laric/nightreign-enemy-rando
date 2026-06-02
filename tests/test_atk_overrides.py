"""Tests for data/atkparam_npc_damage_overrides.csv — per-attack damage
clipping written by dev/emit_atk_overrides.py.

Policy under test: for each non-`nr_placed` cp's AtkParam_Npc rows
whose total damage (phys + mag + fire + thun + dark) exceeds the
tier cap, emit a scaled-down replacement. Per-attack scaling, not
per-cp — Artorias' single 999 move gets clipped while his ~480 normal
moves stay intact. Stamina damage scales proportionally so the
"hits hard and staggers" feel is preserved at the new damage level.

These tests don't re-derive the CSV — they guard the CSV ↔ policy
contract so "regenerate and re-import" stays reliable. Failures mean
either (a) hand-edits drifted from policy, (b) tier/source changes in
nr_enemy_tags.json invalidated the CSV (regenerate), or (c)
emit_atk_overrides.py developed a bug.
"""
import csv
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

CSV_PATH = os.path.join(REPO_ROOT, 'data', 'atkparam_npc_damage_overrides.csv')
ATK_PATH = os.path.join(REPO_ROOT, 'data', 'AtkParam_Npc.csv')
TAGS_PATH = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')

DMG_FIELDS = ('atkPhys', 'atkMag', 'atkFire', 'atkThun', 'atkDark')
STAM_FIELD = 'atkStam'
ELIGIBLE_TIERS = ('miniboss', 'field_boss', 'night_boss', 'nightlord')
VANILLA_SOURCE = 'nr_placed'

# Caps that emit_atk_overrides.py would compute from current data.
# Hardcoded here to keep tests independent of the script's runtime;
# if the script's cap policy changes, this needs to match.
EXPECTED_CAPS = {
    'miniboss':   450,
    'field_boss': 450,
    'night_boss': 450,
    'nightlord':  420,
}


def _atk_id_to_cp(atk_id):
    s = str(atk_id)
    if len(s) < 7:
        return None
    return 'c' + s[:4]


@pytest.fixture(scope='module')
def overrides():
    if not os.path.exists(CSV_PATH):
        pytest.skip(f'{CSV_PATH} does not exist — '
                    f'run `python3 dev/emit_atk_overrides.py` to create it')
    out = {}
    with open(CSV_PATH) as f:
        for row in csv.DictReader(f):
            out[int(row['ID'])] = {f: int(row[f]) for f in DMG_FIELDS + (STAM_FIELD,)}
    return out


@pytest.fixture(scope='module')
def tags():
    with open(TAGS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def vanilla_attacks():
    """atk_id -> {field: int} from AtkParam_Npc.csv."""
    out = {}
    if not os.path.exists(ATK_PATH):
        pytest.skip(f'{ATK_PATH} not in repo — skipping comparison tests')
    with open(ATK_PATH, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row['ID'])
            except (ValueError, KeyError):
                continue
            d = {}
            for fld in DMG_FIELDS + (STAM_FIELD,):
                try: d[fld] = int(row.get(fld, 0) or 0)
                except (ValueError, TypeError): d[fld] = 0
            out[nid] = d
    return out


def test_csv_exists_and_well_formed(overrides):
    assert len(overrides) > 0, 'No damage overrides found — empty CSV'
    for nid, fields in overrides.items():
        assert nid > 0, f'Invalid atk_id {nid}'
        for f in DMG_FIELDS + (STAM_FIELD,):
            assert f in fields, f'Missing column {f} in atk_id {nid}'
            assert fields[f] >= 0, f'Negative value in {f} for {nid}'


def test_no_vanilla_nr_chrs_touched(overrides, tags):
    """Policy excludes `_source: nr_placed`. Walking Mausoleum's
    9999-damage kill-zone attacks should be untouched."""
    violators = []
    for nid in overrides:
        cp = _atk_id_to_cp(nid)
        if cp is None: continue
        if (tags.get(cp, {}) or {}).get('_source') == VANILLA_SOURCE:
            violators.append((nid, cp))
    assert not violators, (
        f'Vanilla NR chrs got damage overrides (policy violation):\n  ' +
        '\n  '.join(f'atk_id={n} cp={c}' for n, c in violators[:10]))


def test_overrides_are_reductions_only(overrides, vanilla_attacks):
    """Cap-down policy: no override may exceed the vanilla value on
    any damage field. A buff means the script's policy semantics
    broke (or the user hand-edited)."""
    buffs = []
    for nid, new in overrides.items():
        old = vanilla_attacks.get(nid)
        if old is None: continue
        for f in DMG_FIELDS + (STAM_FIELD,):
            if new[f] > old[f]:
                buffs.append((nid, f, old[f], new[f]))
                break  # one mismatch per row is enough
    assert not buffs, (
        f'Damage overrides include BUFFS (policy says cap-down only):\n  ' +
        '\n  '.join(f'atk_id={n} {f}: {o} → {h}'
                    for n, f, o, h in buffs[:10]))


def test_only_overcap_attacks_clipped(overrides, vanilla_attacks, tags):
    """If an attack's vanilla total ≤ tier cap, it should NOT be in
    the override set. Touching a within-cap attack means the script
    is over-clipping (e.g. wrong tier lookup)."""
    spurious = []
    for nid, new in overrides.items():
        cp = _atk_id_to_cp(nid)
        if cp is None: continue
        tier = (tags.get(cp, {}) or {}).get('tier')
        if tier not in EXPECTED_CAPS: continue
        old = vanilla_attacks.get(nid)
        if old is None: continue
        old_total = sum(old[f] for f in DMG_FIELDS)
        if old_total <= EXPECTED_CAPS[tier]:
            spurious.append((nid, cp, tier, old_total, EXPECTED_CAPS[tier]))
    assert not spurious, (
        f'Attacks under tier cap got clipped (over-clipping bug):\n  ' +
        '\n  '.join(f'atk_id={n} cp={c} tier={t} total={ot} cap={cap}'
                    for n, c, t, ot, cap in spurious[:10]))


def test_clipped_attacks_land_at_or_below_cap(overrides, tags):
    """Every clipped attack's new total must be ≤ tier cap.
    Tolerance: ±2 from integer rounding (5 fields each rounded
    independently can accumulate small drift)."""
    violations = []
    for nid, new in overrides.items():
        cp = _atk_id_to_cp(nid)
        if cp is None: continue
        tier = (tags.get(cp, {}) or {}).get('tier')
        if tier not in EXPECTED_CAPS: continue
        new_total = sum(new[f] for f in DMG_FIELDS)
        cap = EXPECTED_CAPS[tier]
        if new_total > cap + 2:
            violations.append((nid, cp, tier, new_total, cap))
    assert not violations, (
        f'Clipped attacks exceed tier cap by more than rounding:\n  ' +
        '\n  '.join(f'atk_id={n} cp={c} tier={t} new_total={nt} cap={cap}'
                    for n, c, t, nt, cap in violations[:10]))


def test_known_smoking_gun_clipped(overrides):
    """Regression guard for the named playtest culprits — if these
    drop out of the override set, something fundamental shifted."""
    # Artorias 999 move
    assert 7720916 in overrides, (
        "Artorias' 999-damage atk 7720916 should be in overrides "
        "(known one-shot move)")
    arto_total = sum(overrides[7720916][f] for f in DMG_FIELDS)
    assert arto_total <= 452, (  # 450 cap + rounding
        f"Artorias' 7720916 not clipped enough: total={arto_total}")
    # PCR's 800 hit
    assert 5220440 in overrides, (
        "PCR's 800-damage atk 5220440 should be in overrides")
