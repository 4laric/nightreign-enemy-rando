#!/usr/bin/env python3
"""emit_reward_overrides.py — generate data/npcparam_reward_overrides.csv.

The item-drop companion to emit_getsoul_overrides.py. getSoul handles
rune payout; this handles the on-death item drop.

The rando does not modify NpcParam at runtime (runtime regulation
patching was scoped and declined — see the getSoul thread in
oops_v3.py). Reward overrides are therefore emitted as a one-off
NpcParam patch CSV that the user imports into their own regulation.bin
via Smithbox. This is OPT-IN and MANUAL — not part of any pipeline or
release flow, exactly like npcparam_getsoul_overrides.csv.

Problem
=======
Vanilla NR authors many miniboss-and-above chrs with no item drop at
all: their NpcParam itemLotId_enemy is -1. In vanilla that is fine —
the chr appears in a context where the kill is not loot-facing. When
the rando relocates such a chr to a miniboss arena slot and the player
kills it, it drops nothing, which reads as a stiffed miniboss.

Note: has_reward is a separate thing — a pure ENGINE flag (tier-driven,
biases variant selection) that is never written to regulation. It does
not make an enemy drop loot. The actual in-game drop is the NpcParam
itemLotId_enemy field, which is what this script patches.

Policy
======
For every NpcParam row whose chr tier is miniboss-or-above and whose
itemLotId_enemy is -1 (and which has no drop in rewardItemLot_1/2
either), assign a reward: a RANDOM item lot drawn from the pool of
itemLotId_enemy values that vanilla chrs of the SAME tier actually use.
Pure floor — a row that already has a drop in any reward field is left
untouched, never overwritten.

"Random within the tier pool" means a no-drop miniboss is given the
loot table of some other vanilla miniboss. The pick is deterministic:
seeded by the row's npc_param_id (so re-running yields an identical
CSV) and mixable with --seed (so the assignment set can be rerolled).

Tier set
========
miniboss / field_boss / night_boss / nightlord. Read from
oops_v3.V3_HAS_REWARD_TIERS if defined (mirrors how
emit_getsoul_overrides.py reads V3_GETSOUL_TIER_FLOORS); otherwise the
BOSS_REWARD_TIERS default below is used.

c-prefix resolution
===================
NpcParam IDs are resolved to c-prefixes via nr_enemy_roster.json, NOT
by slicing the ID string. emit_getsoul_overrides.py slices ID[:4],
which is wrong for 5-digit c-prefixes (c70003, c52109, ...). The roster
carries the authoritative npc_param_id -> c_prefix mapping, and roster
scope is also correct scope: the rando only ever places roster
variants, so non-roster NpcParam rows do not need a reward.

Output
======
data/npcparam_reward_overrides.csv with columns ID,itemLotId_enemy.
Only changed rows are emitted (minimal diff vs vanilla). Import in
Smithbox as an NpcParam field patch (itemLotId_enemy) over vanilla
regulation. Stack it with npcparam_getsoul_overrides.csv if desired.

Caveat
======
Assigned lots are borrowed wholesale from other vanilla minibosses, so
a chr will drop another miniboss's loot table — usually fine (runes,
consumables, crafting/smithing materials) but it can occasionally
include a chr-flavoured item. This is an opt-in randomizer reward, not
a hand-balanced one; review the CSV if that matters to you.

Usage
=====
    python3 dev/emit_reward_overrides.py            # default seed 0
    python3 dev/emit_reward_overrides.py --seed 7   # reroll the picks

Reads data/NpcParam.csv, data/nr_enemy_tags.json, data/nr_enemy_roster.json.
Writes data/npcparam_reward_overrides.csv.
"""
import argparse
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

NPCPARAM_CSV = os.path.join(REPO_ROOT, 'data', 'NpcParam.csv')
TAGS_JSON    = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')
ROSTER_JSON  = os.path.join(REPO_ROOT, 'data', 'nr_enemy_roster.json')
OUT_CSV      = os.path.join(REPO_ROOT, 'data', 'npcparam_reward_overrides.csv')

# Fallback if oops_v3 does not expose V3_HAS_REWARD_TIERS. Keep in sync
# with BOSS_REWARD_TIERS in dev/emit_has_reward.py.
BOSS_REWARD_TIERS = frozenset(
    {'miniboss', 'field_boss', 'night_boss', 'nightlord'})

# A drop field counts as "populated" unless it holds this. NR uses -1
# for "no lot"; itemLotId_enemy is never blank or 0 in the data.
NULL_LOT = {'-1', '', None}

# Fields that, if any is populated, mean the row already drops something.
DROP_FIELDS = ('itemLotId_enemy', 'rewardItemLot_1', 'rewardItemLot_2')


def reward_tiers():
    """The miniboss-and-above tier set, preferring the oops_v3 constant."""
    try:
        import oops_v3
        s = getattr(oops_v3, 'V3_HAS_REWARD_TIERS', None)
        if s:
            return frozenset(s)
    except Exception:
        pass
    print("note: oops_v3 does not define V3_HAS_REWARD_TIERS; using the "
          "BOSS_REWARD_TIERS default. To fully mirror the getSoul pattern, "
          "add V3_HAS_REWARD_TIERS to oops_v3.py.")
    return BOSS_REWARD_TIERS


def has_drop(row):
    """True if the NpcParam row already drops something on death."""
    return any(row.get(f) not in NULL_LOT for f in DROP_FIELDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=0,
                    help='reroll the random assignments (default 0)')
    args = ap.parse_args()

    for path in (NPCPARAM_CSV, TAGS_JSON, ROSTER_JSON):
        if not os.path.isfile(path):
            print(f"ERROR: required input missing: {path}")
            sys.exit(1)

    tiers = reward_tiers()
    with open(TAGS_JSON, encoding='utf-8') as f:
        tags = json.load(f)
    with open(ROSTER_JSON, encoding='utf-8') as f:
        roster = json.load(f)

    # Authoritative npc_param_id -> c_prefix from the roster.
    cprefix_of = {str(v['npc_param_id']): v['c_prefix']
                  for v in roster['all_variants']}

    # Read NpcParam rows, keyed by ID.
    npc_rows = {}
    with open(NPCPARAM_CSV, encoding='utf-8', errors='replace', newline='') as f:
        for row in csv.DictReader(f):
            npc_rows[row['ID']] = row

    # tier of each roster row
    def tier_of(npc_id):
        cp = cprefix_of.get(npc_id)
        return tags.get(cp, {}).get('tier') if cp else None

    # Harvest per-tier pools of real itemLotId_enemy values, and find the
    # rows that need a reward — both restricted to roster rows.
    pool = defaultdict(set)
    need = []                       # (npc_id, tier) rows lacking any drop
    scanned = 0
    for npc_id in cprefix_of:
        row = npc_rows.get(npc_id)
        if row is None:
            continue                # roster id not in NpcParam.csv (MMV/ER)
        t = tier_of(npc_id)
        if t not in tiers:
            continue
        scanned += 1
        ie = row.get('itemLotId_enemy')
        if ie not in NULL_LOT:
            pool[t].add(ie)
        if not has_drop(row):
            need.append((npc_id, t))

    combined = set().union(*pool.values()) if pool else set()
    if not combined:
        print("ERROR: no itemLotId_enemy values found to build a reward "
              "pool from — cannot assign rewards.")
        sys.exit(1)

    # Assign. Pool is per-tier; fall back to the combined pool if a tier
    # has none. Pick is deterministic: seeded by (--seed, npc_id), and
    # the pool is sorted so the choice is order-independent.
    patch = []
    by_tier = Counter()
    fallback_used = Counter()
    for npc_id, t in need:
        tier_pool = pool.get(t) or set()
        if tier_pool:
            choices = sorted(tier_pool)
        else:
            choices = sorted(combined)
            fallback_used[t] += 1
        rng = random.Random(f"{args.seed}:{npc_id}")
        patch.append((int(npc_id), rng.choice(choices)))
        by_tier[t] += 1
    patch.sort()

    with open(OUT_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ID', 'itemLotId_enemy'])
        for npc_id, lot in patch:
            w.writerow([npc_id, lot])

    # c-prefix-level coverage: how many miniboss+ c-prefixes had zero
    # drop across ALL their roster rows (the real "stiffed miniboss"
    # set), and confirm every one is now covered.
    cp_rows = defaultdict(list)
    for npc_id in cprefix_of:
        row = npc_rows.get(npc_id)
        if row is not None and tier_of(npc_id) in tiers:
            cp_rows[cprefix_of[npc_id]].append(npc_id)
    fully_uncovered = [cp for cp, ids in cp_rows.items()
                       if not any(has_drop(npc_rows[i]) for i in ids)]
    patched_ids = {pid for pid, _ in patch}
    still_uncovered = [cp for cp in fully_uncovered
                       if not any(int(i) in patched_ids for i in cp_rows[cp])]

    print(f"\nReward tiers: {sorted(tiers)}")
    print(f"miniboss+ roster rows scanned: {scanned}")
    print("per-tier harvested itemLotId_enemy pool:")
    for t in ('nightlord', 'night_boss', 'field_boss', 'miniboss'):
        print(f"  {t:12s} {len(pool.get(t, ()))} lots")
    print(f"\nRows assigned a reward: {len(patch)}")
    for t in ('nightlord', 'night_boss', 'field_boss', 'miniboss'):
        extra = (f"  ({fallback_used[t]} via combined-pool fallback)"
                 if fallback_used[t] else '')
        print(f"  {t:12s} {by_tier[t]}{extra}")
    print(f"\nminiboss+ c-prefixes with zero drop on any row: "
          f"{len(fully_uncovered)}")
    if still_uncovered:
        print(f"  WARNING: {len(still_uncovered)} still uncovered after "
              f"patch: {sorted(still_uncovered)}")
    else:
        print("  all now covered by the patch.")
    print(f"\nWrote {OUT_CSV}  (seed={args.seed})")


if __name__ == '__main__':
    main()
