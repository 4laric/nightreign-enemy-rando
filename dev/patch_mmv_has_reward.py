#!/usr/bin/env python3
"""
patch_mmv_has_reward.py — derive has_reward correctly from NpcParam regulation.

mmv_imports.json was shipped with has_reward=False on all 374 variants — a
universal default rather than a real derivation. This means the rando's
pick_variant_for_tier Tier-1 ('reward + boss intro') and Tier-2 ('reward only')
selection paths never pick MMV variants, biasing slot assignments toward
vanilla NR bosses even when MMV bosses have full reward configurations.

This patch re-derives has_reward from the actual NpcParam fields:
  getSoul         — direct rune drop on death
  itemLotId_enemy — generic drop table (can include rune items)
  rewardItemLot_1, rewardItemLot_2 — NR-specific post-fight reward lots
                                      (relic drops, etc.)

A variant is has_reward=True if ANY of these is non-zero / not -1.
This matches the semantics used elsewhere in the engine (the field gates
selection priority — a variant 'has a reward' if killing it grants ANY
gameplay reward, runes or items).

Usage:
    # Run from the rando dir, with NpcParam.csv exported alongside.
    python3 patch_mmv_has_reward.py NpcParam.csv mmv_imports.json

Or to write to a separate output:
    python3 patch_mmv_has_reward.py NpcParam.csv mmv_imports.json out.json
"""
import csv
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    npc_csv = sys.argv[1]
    mmv_path = sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else mmv_path  # in-place by default

    with open(npc_csv) as f:
        npc_by_id = {int(r['ID']): r for r in csv.DictReader(f)}

    with open(mmv_path) as f:
        mmv = json.load(f)

    total = len(mmv['variants'])
    n_in_reg = 0
    n_flipped_to_true = 0
    n_flipped_to_false = 0
    n_unchanged = 0
    n_missing_in_reg = 0
    flipped_examples = []

    for v in mmv['variants']:
        nid = v['npc_param_id']
        was = bool(v.get('has_reward'))
        if nid not in npc_by_id:
            n_missing_in_reg += 1
            # Don't mutate variants whose NpcParam is missing from this
            # regulation export — the field stays as-is. (Could happen if
            # the user exports a stale or partial regulation.)
            continue
        n_in_reg += 1
        r = npc_by_id[nid]
        # A variant has a reward if any of the four reward fields is set.
        # FromSoft uses -1 as "unset" for ItemLot fields and 0 for getSoul.
        def f(c): return int(r[c])
        now = (f('getSoul') > 0
               or f('itemLotId_enemy') > 0
               or f('rewardItemLot_1') > 0
               or f('rewardItemLot_2') > 0)
        v['has_reward'] = now
        if was != now:
            if now:
                n_flipped_to_true += 1
                if len(flipped_examples) < 5:
                    flipped_examples.append(
                        (v['c_prefix'], nid, v.get('mmv_name', ''),
                         f('getSoul'), f('rewardItemLot_2')))
            else:
                n_flipped_to_false += 1
        else:
            n_unchanged += 1

    # Write back
    with open(out_path, 'w') as f:
        json.dump(mmv, f, indent=2)

    print(f"MMV variants:            {total}")
    print(f"  in regulation:         {n_in_reg}")
    print(f"  missing from reg:      {n_missing_in_reg}  (left untouched)")
    print(f"  flipped False → True:  {n_flipped_to_true}")
    print(f"  flipped True → False:  {n_flipped_to_false}")
    print(f"  unchanged:             {n_unchanged}")
    print()
    print(f"Output written: {out_path}")
    if flipped_examples:
        print(f"\nSample flips (False → True):")
        for cp, nid, name, soul, rwd2 in flipped_examples:
            print(f"  {cp:6s} {nid:>10}  soul={soul:>5}  relic_lot={rwd2:>10}  "
                  f"'{name}'")


if __name__ == '__main__':
    main()
