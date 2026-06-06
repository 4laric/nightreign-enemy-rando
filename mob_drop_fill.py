#!/usr/bin/env python3
"""mob_drop_fill.py - per-seed randomization of enemy on-death drops (ItemLotParam_enemy).

Companion to merchant_shop_fill.py. Where the shop randomizes what merchants
sell, this randomizes what MOBS drop, and lifts the drop rate.

For every ItemLotParam_enemy row (the lot an enemy's NpcParam.itemLotId_enemy
points at), each occupied item slot's lotItemId is rerolled to a random id of
the SAME lotItemCategory, pooled from ids that already appear in enemy lots, so
the row stays valid -- same safety model as the shop (every assigned id is one
the game already drops; no quest/key-item or wrong-id-space hazards).
lotItemCategory, the per-item weights, and quantity are all preserved, so the
relative rarity *among* a lot's items is unchanged.

Drop RATE lives in the lot, not in NpcParam: each slot's chance is its
lotItemBasePoint weight over the row's total, and the slot with lotItemId == 0
is "nothing". We lift the rate by SHRINKING the nothing-slot weight so that
P(any item) is multiplied by `rate_multiplier` (default 2.0), capped at 1.0 (a
lot that already drops something >= 1/mult of the time becomes guaranteed). The
item-slot weights are untouched, so every individual item's odds scale by the
same factor as P(any item).

ItemLotParam_enemy row layout (224 B, validated against the shipping regulation):
  lotItemId01-08        s32  @ 0x00   (item id; 0 = "nothing")
  lotItemCategory01-08  s32  @ 0x20
  lotItemBasePoint01-08 u16  @ 0x40   (weight; slot chance = weight / row total)

Mechanics: fixed-width PARAM field patches in place via regulation_io, no row
add/remove and no string edits (length-preserving). Offline / me3 only, like the
shop: a modded regulation.bin is rejected by EAC online.
"""

import random
import struct
from collections import defaultdict

import regulation_io as R

PARAM = "ItemLotParam_enemy"
N_SLOTS = 8
ID_OFF = 0x00      # s32 x8
CAT_OFF = 0x20     # s32 x8
BP_OFF = 0x40      # u16 x8
DEFAULT_RATE_MULTIPLIER = 2.0


def seed_to_int(seed):
    if isinstance(seed, int):
        return seed & 0xFFFFFFFF
    s = str(seed).strip()
    try:
        return int(s) & 0xFFFFFFFF
    except ValueError:
        import hashlib
        return int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16) & 0xFFFFFFFF


def extract(reg):
    """Read ItemLotParam_enemy out of a loaded Regulation into a plain
    {targets, pools} map so roll() can stay pure / reg-free (like the shop's
    baked slot json). Built on the fly because the lots and their valid id
    pools are derivable from the regulation itself -- no bake step needed.

      targets: [{"row": id, "items": [(slot, cat, weight)],
                 "nothings": [(slot, weight)]}]  (rows with >= 1 item only)
      pools:   {category_value: sorted([item_id, ...])}  (lotItemId != 0)
    """
    off, _size, rows = reg._param(PARAM)
    bnd = reg.bnd
    pools = defaultdict(set)
    targets = []
    for rid in sorted(rows):
        base = off + rows[rid]
        ids = struct.unpack_from("<8i", bnd, base + ID_OFF)
        cats = struct.unpack_from("<8i", bnd, base + CAT_OFF)
        bps = struct.unpack_from("<8H", bnd, base + BP_OFF)
        items, nothings = [], []
        for i in range(N_SLOTS):
            if ids[i] != 0:
                items.append((i, cats[i], bps[i]))
                pools[cats[i]].add(ids[i])
            elif bps[i] > 0:
                nothings.append((i, bps[i]))
        if items:                      # nothing to randomize in an item-less lot
            targets.append({"row": rid, "items": items, "nothings": nothings})
    return {"targets": targets, "pools": {c: sorted(v) for c, v in pools.items()}}


def roll(drop_data, seed, *, rate_multiplier=DEFAULT_RATE_MULTIPLIER):
    """Roll new item ids + nothing weights for every enemy lot. Returns
    (patches, spoiler) where patches = {row_id: [(field_off, fmt, value), ...]}.
    Deterministic for `seed`. Item weights, categories, and quantities are
    left untouched, so only WHAT drops and HOW OFTEN (the nothing weight)
    change.
    """
    rng = random.Random(seed_to_int(seed))
    pools = drop_data["pools"]
    patches, spoiler = {}, []
    for t in drop_data["targets"]:
        rid = t["row"]
        fields = []

        # 1) reroll each occupied item slot's id, staying in its category.
        for slot, cat, _w in t["items"]:
            pool = pools.get(cat)
            if not pool:
                continue
            fields.append((ID_OFF + 4 * slot, "<i", rng.choice(pool)))

        # 2) shrink the nothing weight so P(any item) *= rate_multiplier (cap 1).
        #    Item weights are unchanged, so item_w is the same before/after; a
        #    lot with no nothing slot is already guaranteed and is left as-is.
        item_w = sum(w for _, _, w in t["items"])
        nothing_w = sum(w for _, w in t["nothings"])
        if item_w > 0 and nothing_w > 0:
            p_old = item_w / (item_w + nothing_w)
            p_new = min(1.0, rate_multiplier * p_old)
            new_nothing = 0 if p_new >= 1.0 else round(item_w * (1.0 - p_new) / p_new)
            for slot, w in t["nothings"]:
                nw = round(new_nothing * w / nothing_w)
                fields.append((BP_OFF + 2 * slot, "<H", max(0, min(0xFFFF, nw))))
            spoiler.append({"row": rid, "items": len(t["items"]),
                            "p_old": round(p_old, 4), "p_new": round(p_new, 4),
                            "nothing_old": nothing_w, "nothing_new": new_nothing})

        if fields:
            patches[rid] = fields
    return patches, spoiler


def apply_patches(reg, patches):
    """Write each lot's rerolled ids (s32) and shrunk nothing weights (u16)
    in place. Categories, item weights, and quantities are left untouched.
    Returns the number of lots patched."""
    for rid, fields in patches.items():
        for field_off, fmt, value in fields:
            reg.patch_param_field(PARAM, rid, field_off, fmt, value)
    return len(patches)
