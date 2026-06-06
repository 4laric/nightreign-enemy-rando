#!/usr/bin/env python3
"""npcparam_getsoul_fill.py - per-seed getSoul (rune-reward) flooring.

Runtime companion to dev/emit_getsoul_overrides.py. Where that dev script emits a
one-off NpcParam getSoul patch CSV for manual Smithbox import, this applies the
same floor in the regulation pipeline so the installed reg matches the policy
with no manual import step -- the same static->runtime move already made for
reward mapping (npcparam_reward_fill).

This is the SECOND NpcParam pass. Where the reward fill assigns WHICH lot a
no-drop chr points to (itemLotId_enemy), this floors HOW MANY runes a chr awards
(getSoul). When the rando relocates a chr authored with a low/zero getSoul (swarm
mobs, scripted intro chrs, Nightlords whose drops never mattered) to an isolated
overworld kill, its rune reward is lifted to its tier's placement-weighted
vanilla median, killing the "this beefy chr dropped 80 runes" disconnect. Pure
floor: a getSoul already at/above its tier floor is never lowered.

Policy (mirrors emit_getsoul_overrides.py):
  - Floor = oops_v3.V3_GETSOUL_TIER_FLOORS[tier] (placement-weighted vanilla
    median per tier).
  - Every roster row whose tier carries a floor and whose CURRENT getSoul is
    below it is set to the floor.
  - Deterministic and seed-INDEPENDENT: a floor is a fixed correction, not a
    reroll, so the same patch lands every seed (the `seed` arg is accepted for
    parity with the reward/drop passes and ignored). This keeps
    randomize_regulation byte-deterministic per seed.

getSoul is read from the LIVE reg, not data/NpcParam.csv: the bundled (modded)
reg carries its own getSoul values that differ from the vanilla dump, and the
floor must be applied to what is actually there. Field offset derived
empirically and validated against the bundled reg's NpcParam (value-plausibility
-- non-negative, bounded, discrete -- plus adjacency to hp@0x24 and
itemLotId_enemy@0x30, matching the CSV field order hp -> getSoul ->
itemLotId_enemy):
  getSoul 0x2c (s32).

c-prefix / tier resolution is via nr_enemy_roster.json (npc_param_id -> c_prefix)
and nr_enemy_tags.json (c_prefix -> tier), NOT id-string slicing (NR has 5-digit
c-prefixes). Both ship in data/ (build_release INCLUDE_DIRS).

Mechanics: a single fixed-width s32 patch per floored row via regulation_io
(length-preserving). Offline / me3 only, like the rest of the pipeline.
"""

import json
import os
import struct

NPCPARAM = "NpcParam"
GS_OFF = 0x2c          # getSoul (s32, the rune reward on death)

ROSTER_JSON = "nr_enemy_roster.json"
TAGS_JSON = "nr_enemy_tags.json"


def default_floors():
    """The tier floors from oops_v3.V3_GETSOUL_TIER_FLOORS -- the single source
    of truth shared with the dev emitter. Imported lazily so this module loads
    in contexts that pass floors explicitly (tests) without importing oops_v3."""
    import oops_v3
    return dict(oops_v3.V3_GETSOUL_TIER_FLOORS)


def load_meta(data_dir):
    """Load roster + tags from data_dir.

      tier_of: {npc_param_id(int) -> tier or None}
    """
    with open(os.path.join(data_dir, ROSTER_JSON), encoding="utf-8") as f:
        roster = json.load(f)
    with open(os.path.join(data_dir, TAGS_JSON), encoding="utf-8") as f:
        tags = json.load(f)
    cprefix_of = {int(v["npc_param_id"]): v["c_prefix"]
                  for v in roster["all_variants"]}
    return {nid: tags.get(cp, {}).get("tier") for nid, cp in cprefix_of.items()}


def extract(reg, data_dir, floors=None):
    """Read getSoul for the floor-eligible roster rows out of a loaded
    Regulation. Returns
        {"current": {npc_id: (tier, getSoul)}, "floors": floors}
    over the rows whose tier carries a floor (others can't be floored)."""
    floors = floors if floors is not None else default_floors()
    tier_of = load_meta(data_dir)
    off, _size, rows = reg._param(NPCPARAM)
    bnd = reg.bnd
    current = {}
    for nid, tier in tier_of.items():
        if tier not in floors or nid not in rows:
            continue
        gs = struct.unpack_from("<i", bnd, off + rows[nid] + GS_OFF)[0]
        current[nid] = (tier, gs)
    return {"current": current, "floors": floors}


def roll(getsoul_data, seed=None):
    """Compute the floor patches. Returns (patches, spoiler) where patches =
    {npc_id: floored_getSoul}. Pure floor: only rows strictly below their tier
    floor are patched, and only up to the floor -- a getSoul at/above the floor
    is left untouched. Deterministic and seed-independent (`seed` accepted for
    API parity with the reward/drop passes, ignored)."""
    floors = getsoul_data["floors"]
    patches, spoiler = {}, []
    for nid, (tier, gs) in getsoul_data["current"].items():
        floor = floors.get(tier)
        if floor is None or gs >= floor:
            continue
        patches[nid] = floor
        spoiler.append({"npc_param_id": nid, "tier": tier,
                        "getSoul_was": gs, "getSoul": floor})
    spoiler.sort(key=lambda d: d["npc_param_id"])
    return patches, spoiler


def apply_patches(reg, patches):
    """Write getSoul (s32) for each floored row. Floor only -- callers pass rows
    that were below their tier floor, so nothing is ever lowered. Returns the
    number of rows patched."""
    for nid, gs in patches.items():
        reg.patch_param_field(NPCPARAM, nid, GS_OFF, "<i", gs)
    return len(patches)
