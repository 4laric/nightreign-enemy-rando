#!/usr/bin/env python3
"""npcparam_reward_fill.py - per-seed reward mapping for miniboss-and-above enemies.

Runtime companion to dev/emit_reward_overrides.py. Where that dev script emits a
one-off NpcParam patch CSV for manual Smithbox import, this does the same job in
the regulation pipeline: every seed, ensure every miniboss-or-above roster chr
that currently drops NOTHING gets an on-death reward lot assigned.

This is the one pass that patches NpcParam. The drop randomizer deliberately
never does -- drop RATE lives in the lot, not NpcParam -- but WHICH lot a chr
points to is a NpcParam field (itemLotId_enemy), and that is what gets assigned
here. Pure floor: a chr that already drops something in any of itemLotId_enemy /
rewardItemLot_1 / rewardItemLot_2 is left untouched, never overwritten.

Policy (mirrors emit_reward_overrides.py):
  - Tier set "miniboss or above" = miniboss / field_boss / night_boss / nightlord.
  - need = miniboss+ roster rows with no drop on ANY of the three fields.
  - For each need row, assign itemLotId_enemy = a random lot drawn from the pool
    of itemLotId_enemy values that miniboss+ chrs of the SAME tier actually use
    (fall back to the combined pool if a tier pool is empty). A no-drop miniboss
    thus inherits some other vanilla miniboss's loot table.
  - Deterministic: rng seeded by f"{seed}:{npc_id}", pool sorted -> order-free.

NpcParam field values are read from the regulation directly, NOT from
data/NpcParam.csv: the bundled (modded) reg's itemLotId_enemy differs from that
vanilla dump on ~11% of rows, so the live reg is the only correct source for
both the need set and the per-tier pools. Field offsets were derived empirically
and validated against NpcParam.csv (itemLotId_map / rewardItemLot_1 match 100%):
  itemLotId_enemy 0x30, rewardItemLot_1 0x6c, rewardItemLot_2 0x48  (all s32).

c-prefix / tier resolution is via nr_enemy_roster.json (npc_param_id -> c_prefix)
and nr_enemy_tags.json (c_prefix -> tier), NOT by slicing the id string (NR has
5-digit c-prefixes). Both ship in data/ (build_release INCLUDE_DIRS).

Mechanics: a single fixed-width s32 patch per assigned row via regulation_io
(length-preserving). Offline / me3 only, like the rest of the pipeline.
"""

import json
import os
import random
import struct
from collections import defaultdict

NPCPARAM = "NpcParam"
IE_OFF = 0x30          # itemLotId_enemy   (s32, the on-death drop lot)
RW1_OFF = 0x6c         # rewardItemLot_1   (s32)
RW2_OFF = 0x48         # rewardItemLot_2   (s32)
NULL_LOT = -1          # "no lot"; itemLotId_enemy is never 0 in the data

DEFAULT_REWARD_TIERS = frozenset(
    {"miniboss", "field_boss", "night_boss", "nightlord"})

ROSTER_JSON = "nr_enemy_roster.json"
TAGS_JSON = "nr_enemy_tags.json"


def load_meta(data_dir):
    """Load roster + tags from data_dir.

      cprefix_of: {npc_param_id(int) -> c_prefix}
      tier_of:    {npc_param_id(int) -> tier or None}
    """
    with open(os.path.join(data_dir, ROSTER_JSON), encoding="utf-8") as f:
        roster = json.load(f)
    with open(os.path.join(data_dir, TAGS_JSON), encoding="utf-8") as f:
        tags = json.load(f)
    cprefix_of = {int(v["npc_param_id"]): v["c_prefix"]
                  for v in roster["all_variants"]}
    tier_of = {nid: tags.get(cp, {}).get("tier")
               for nid, cp in cprefix_of.items()}
    return cprefix_of, tier_of


def extract(reg, data_dir, tiers=DEFAULT_REWARD_TIERS):
    """Read NpcParam for the miniboss+ roster rows out of a loaded Regulation.

      need:     [(npc_id, tier)]   rows with no drop on ANY of the three fields
      pools:    {tier: sorted([itemLotId_enemy, ...])}   real lots that tier uses
      combined: sorted([...])      union of all tier pools (empty-pool fallback)
    """
    _cp, tier_of = load_meta(data_dir)
    off, _size, rows = reg._param(NPCPARAM)
    bnd = reg.bnd

    def field(nid, foff):
        return struct.unpack_from("<i", bnd, off + rows[nid] + foff)[0]

    pools = defaultdict(set)
    need = []
    for nid, tier in tier_of.items():
        if tier not in tiers or nid not in rows:
            continue
        ie = field(nid, IE_OFF)
        if ie != NULL_LOT:
            pools[tier].add(ie)
        if (ie == NULL_LOT
                and field(nid, RW1_OFF) == NULL_LOT
                and field(nid, RW2_OFF) == NULL_LOT):
            need.append((nid, tier))

    combined = sorted(set().union(*pools.values())) if pools else []
    return {"need": need,
            "pools": {t: sorted(s) for t, s in pools.items()},
            "combined": combined}


def roll(reward_data, seed):
    """Assign each need row a tier-appropriate itemLotId_enemy. Returns
    (patches, spoiler) where patches = {npc_id: lot}. Deterministic: each row's
    pick is seeded by f"{seed}:{npc_id}" over the sorted pool, so the assignment
    is reproducible and order-independent, and rerolls cleanly with the seed."""
    pools = reward_data["pools"]
    combined = reward_data["combined"]
    patches, spoiler = {}, []
    for nid, tier in reward_data["need"]:
        choices = pools.get(tier) or combined
        if not choices:
            continue
        lot = random.Random(f"{seed}:{nid}").choice(choices)
        patches[nid] = lot
        spoiler.append({"npc_param_id": nid, "tier": tier,
                        "itemLotId_enemy": lot})
    spoiler.sort(key=lambda d: d["npc_param_id"])
    return patches, spoiler


def apply_patches(reg, patches):
    """Write itemLotId_enemy (s32) for each assigned row. Floor only -- callers
    pass rows that had no drop on any field, so nothing is ever overwritten.
    Returns the number of rows patched."""
    for nid, lot in patches.items():
        reg.patch_param_field(NPCPARAM, nid, IE_OFF, "<i", lot)
    return len(patches)
