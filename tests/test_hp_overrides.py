"""Tests for data/npcparam_hp_overrides.csv — the per-variant HP cap
written by dev/emit_hp_overrides.py.

Policy under test: for each non-`nr_placed` cp whose max variant HP
exceeds its tier's vanilla NR p75, scale every variant down uniformly
so the max lands at the tier cap. Vanilla NR chrs are never touched.

These tests don't re-derive the CSV — they guard table↔CSV consistency
so "regenerate via emit_hp_overrides.py and re-import via Smithbox"
stays a reliable instruction. Failures here mean either (a) the CSV
got hand-edited and drifted from policy, (b) tier definitions in
nr_enemy_tags.json shifted and the CSV is stale (regenerate), or
(c) emit_hp_overrides.py developed a bug.
"""
import csv
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

CSV_PATH = os.path.join(REPO_ROOT, 'data', 'npcparam_hp_overrides.csv')
NPCPARAM_PATH = os.path.join(REPO_ROOT, 'data', 'NpcParam.csv')
TAGS_PATH = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')
ROSTER_PATH = os.path.join(REPO_ROOT, 'data', 'nr_enemy_roster.json')

# Tiers eligible for the HP cap rule. Mirror the script's
# DEFAULT_TIER_CAPS keys; if the script's set changes, this needs to
# match.
ELIGIBLE_TIERS = ('miniboss', 'field_boss', 'night_boss', 'nightlord')
VANILLA_SOURCE = 'nr_placed'


@pytest.fixture(scope='module')
def overrides():
    if not os.path.exists(CSV_PATH):
        pytest.skip(f'{CSV_PATH} does not exist — '
                    f'run `python3 dev/emit_hp_overrides.py` to create it')
    out = {}
    with open(CSV_PATH) as f:
        for row in csv.DictReader(f):
            out[int(row['ID'])] = int(row['hp'])
    return out


@pytest.fixture(scope='module')
def tags():
    with open(TAGS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def nid_to_cp():
    """npc_param_id -> c_prefix mapping from roster."""
    with open(ROSTER_PATH) as f:
        roster = json.load(f)
    out = {}
    for v in roster.get('all_variants', []):
        out[int(v['npc_param_id'])] = v.get('c_prefix')
    return out


@pytest.fixture(scope='module')
def vanilla_hp():
    """npc_param_id -> vanilla HP from NpcParam.csv."""
    out = {}
    with open(NPCPARAM_PATH, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                out[int(row['ID'])] = int(row.get('hp', 0))
            except (ValueError, KeyError, TypeError):
                pass
    return out


def test_csv_exists_and_well_formed(overrides):
    assert len(overrides) > 0, 'No HP overrides found — empty CSV'
    # All keys are valid npc param IDs (positive integers).
    for nid, hp in overrides.items():
        assert nid > 0, f'Invalid npc_param_id {nid}'
        assert hp > 0, f'HP override for {nid} must be positive: got {hp}'


def test_no_vanilla_nr_chrs_touched(overrides, nid_to_cp, tags):
    """The policy excludes `_source: nr_placed` chrs. If any vanilla
    NR variant has an override, the CSV breaks scope."""
    violators = []
    for nid in overrides:
        cp = nid_to_cp.get(nid)
        if cp is None: continue
        if (tags.get(cp, {}) or {}).get('_source') == VANILLA_SOURCE:
            violators.append((nid, cp))
    assert not violators, (
        f'Vanilla NR chrs got HP overrides (policy violation):\n  ' +
        '\n  '.join(f'nid={n} cp={c}' for n, c in violators[:10]))


def test_overrides_are_reductions_not_buffs(overrides, vanilla_hp):
    """The script caps DOWNWARD only. If any override raises HP above
    vanilla, the script's policy semantics broke."""
    buffs = []
    for nid, new_hp in overrides.items():
        old_hp = vanilla_hp.get(nid)
        if old_hp is None: continue
        if new_hp > old_hp:
            buffs.append((nid, old_hp, new_hp))
    assert not buffs, (
        f'HP overrides include BUFFS (policy says cap-down only):\n  ' +
        '\n  '.join(f'nid={n} {o} → {h} (+{h-o})' for n, o, h in buffs[:10]))


def test_all_overridden_cps_are_in_eligible_tiers(overrides, nid_to_cp, tags):
    """No grunt / non_combat / cinematic overrides — that would mean
    a chr got retiered without the CSV being regenerated."""
    out_of_tier = []
    for nid in overrides:
        cp = nid_to_cp.get(nid)
        if cp is None: continue
        tier = (tags.get(cp, {}) or {}).get('tier')
        if tier not in ELIGIBLE_TIERS:
            out_of_tier.append((nid, cp, tier))
    assert not out_of_tier, (
        f'Overrides exist for chrs in non-eligible tiers '
        f'(retier without regen?):\n  ' +
        '\n  '.join(f'nid={n} cp={c} tier={t!r}'
                    for n, c, t in out_of_tier[:10]))


def test_per_cp_scaling_is_uniform(overrides, nid_to_cp, vanilla_hp):
    """For each cp with overrides, the ratio new_hp / old_hp should be
    the same across all overridden variants (within rounding tolerance).
    If a cp shows variant-by-variant scaling drift, the script's
    per-cp uniform-ratio assumption broke."""
    from collections import defaultdict
    by_cp = defaultdict(list)
    for nid, new_hp in overrides.items():
        cp = nid_to_cp.get(nid)
        if cp is None: continue
        old_hp = vanilla_hp.get(nid)
        if old_hp is None or old_hp == 0: continue
        by_cp[cp].append((nid, old_hp, new_hp, new_hp / old_hp))

    drifters = []
    for cp, items in by_cp.items():
        if len(items) <= 1: continue
        ratios = [r for _, _, _, r in items]
        spread = max(ratios) - min(ratios)
        # Allow up to 5% spread from rounding (integer hp from a real
        # ratio means small drift). Tighter would false-positive on
        # rounding artifacts; looser hides actual policy bugs.
        if spread > 0.05:
            drifters.append((cp, len(items), min(ratios), max(ratios), spread))
    assert not drifters, (
        f'Per-cp ratio drift exceeds rounding tolerance — '
        f'uniform-scaling assumption violated:\n  ' +
        '\n  '.join(f'{c} ({n} variants): ratios {lo:.3f}..{hi:.3f} '
                    f'(spread {s:.3f})'
                    for c, n, lo, hi, s in drifters[:10]))
