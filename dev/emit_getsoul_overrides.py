#!/usr/bin/env python3
"""emit_getsoul_overrides.py — generate data/npcparam_getsoul_overrides.csv.

The rando does not modify NpcParam at runtime. getSoul (rune drop)
floors are applied as a one-off NpcParam patch imported into the user's
regulation.bin via Smithbox. This script emits that patch CSV.

Policy
======
Uplift any NpcParam row whose getSoul is below its chr's tier floor up
to that floor; leave rows at/above the floor untouched. Pure floor —
never lowers a drop. Tier floors live in oops_v3.V3_GETSOUL_TIER_FLOORS
and are the placement-weighted vanilla medians per tier.

Tier-driven, not a hand-curated chr list: this walks every NpcParam row,
resolves the chr's tier from nr_enemy_tags.json, and floors the row if
it's below the tier median. Nothing to hand-maintain, nothing to drift.

Output
======
data/npcparam_getsoul_overrides.csv with columns ID,getSoul. Only rows
that actually change are emitted (minimal diff vs vanilla). Import in
Smithbox as an NpcParam field patch (getSoul) over vanilla regulation.

The script also re-derives and prints the placement-weighted medians so
you can confirm V3_GETSOUL_TIER_FLOORS still matches the current data;
it warns if a hardcoded floor has drifted from the derived median.

Usage
=====
    python3 dev/emit_getsoul_overrides.py

Reads data/NpcParam.csv, data/nr_enemy_tags.json, data/nr_all_slots.json.
Writes data/npcparam_getsoul_overrides.csv.
"""
import csv
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

NPCPARAM_CSV = os.path.join(REPO_ROOT, 'data', 'NpcParam.csv')
TAGS_JSON    = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')
SLOTS_JSON   = os.path.join(REPO_ROOT, 'data', 'nr_all_slots.json')
OUT_CSV      = os.path.join(REPO_ROOT, 'data', 'npcparam_getsoul_overrides.csv')


def npc_id_to_cprefix(npc_id):
    """NpcParam IDs encode the chr: first 4 digits = c-prefix number.
    e.g. 41810000 -> c4181."""
    s = str(npc_id)
    return 'c' + s[:4] if len(s) >= 8 else None


def derive_placement_weighted_medians(npc_rows, tags, placement_count):
    """Re-derive the placement-weighted vanilla median getSoul per tier.
    For each chr: representative getSoul = median of its authored (>0)
    variants. Weight that by the chr's vanilla placement count. Median
    of the weighted distribution is the tier floor."""
    cp_gs = defaultdict(list)
    for npc_id, gs in npc_rows:
        cp = npc_id_to_cprefix(npc_id)
        if cp:
            cp_gs[cp].append(gs)
    cp_repr = {cp: statistics.median([v for v in vals if v > 0])
               for cp, vals in cp_gs.items() if any(v > 0 for v in vals)}

    medians = {}
    for tier in ('nightlord', 'night_boss', 'field_boss', 'miniboss', 'grunt'):
        weighted = []
        for cp, rep in cp_repr.items():
            if tags.get(cp, {}).get('tier') == tier:
                weighted.extend([rep] * placement_count.get(cp, 0))
        if weighted:
            medians[tier] = int(statistics.median(weighted))
    return medians


def main():
    import oops_v3
    floors = oops_v3.V3_GETSOUL_TIER_FLOORS

    for path in (NPCPARAM_CSV, TAGS_JSON, SLOTS_JSON):
        if not os.path.isfile(path):
            print(f"ERROR: required input missing: {path}")
            sys.exit(1)

    with open(TAGS_JSON, encoding='utf-8') as f:
        tags = json.load(f)
    with open(SLOTS_JSON, encoding='utf-8') as f:
        slots = json.load(f)
    placement_count = Counter(s['c_prefix'] for s in slots)

    # Read vanilla NpcParam getSoul
    npc_rows = []
    with open(NPCPARAM_CSV, encoding='utf-8', errors='replace') as f:
        r = csv.reader(f)
        header = next(r)
        try:
            i_id = header.index('ID')
            i_gs = header.index('getSoul')
        except ValueError as e:
            print(f"ERROR: NpcParam.csv missing column: {e}")
            sys.exit(1)
        for row in r:
            if len(row) <= max(i_id, i_gs):
                continue
            try:
                npc_rows.append((int(row[i_id]), int(row[i_gs])))
            except ValueError:
                continue

    # Drift check: re-derive medians, warn if the hardcoded floors differ
    derived = derive_placement_weighted_medians(npc_rows, tags, placement_count)
    print("Placement-weighted vanilla medians (re-derived):")
    drift = []
    for tier in ('nightlord', 'night_boss', 'field_boss', 'miniboss', 'grunt'):
        d = derived.get(tier)
        f = floors.get(tier)
        mark = '' if d == f else f'  <-- DRIFT (table has {f})'
        print(f"  {tier:12s} derived={d}  table={f}{mark}")
        if d != f:
            drift.append(tier)
    if drift:
        print(f"\nWARNING: {len(drift)} tier floor(s) in "
              f"V3_GETSOUL_TIER_FLOORS no longer match the derived "
              f"placement-weighted median: {drift}. The CSV below uses "
              f"the TABLE values; update the table if the drift is real.")

    # Emit: floor every row below its tier floor
    patch = []
    by_tier = Counter()
    for npc_id, vanilla_gs in npc_rows:
        cp = npc_id_to_cprefix(npc_id)
        tier = tags.get(cp, {}).get('tier')
        floor = floors.get(tier)
        if floor is None:
            continue
        if vanilla_gs < floor:
            patch.append((npc_id, floor))
            by_tier[tier] += 1
    patch.sort()

    with open(OUT_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ID', 'getSoul'])
        for npc_id, new_gs in patch:
            w.writerow([npc_id, new_gs])

    print(f"\nNpcParam rows scanned: {len(npc_rows)}")
    print(f"Rows uplifted to floor: {len(patch)}")
    for tier in ('nightlord', 'night_boss', 'field_boss', 'miniboss', 'grunt'):
        print(f"  {tier:12s} {by_tier[tier]}")
    print(f"Wrote {OUT_CSV}")


if __name__ == '__main__':
    main()
