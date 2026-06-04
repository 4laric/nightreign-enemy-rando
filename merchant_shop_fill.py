#!/usr/bin/env python3
"""merchant_shop_fill.py - per-seed PURE-CHAOS randomization of the NR expedition merchant.

The expedition merchant's stock is spread across 21 numbered "Sets" per merchant
family ([Common Merchant - Set N], [Rare Merchant - Set N], the Deep of Night
variants, [Final Merchant]) plus per-family "Always" rows; the engine rolls one
Set per seed/expedition. We randomize EVERY merchant row (Always + all Sets):

  * equipId  -> random item of the SAME equipType, from a chaos pool. Weapons
    (equipType 6) are split by realm - normal merchants draw the 5xxxxx weapon
    space, Deep of Night draws the 6xxxxx space - because those id spaces are
    disjoint and the 6xxxxx (Everdark) ids are mode-specific. Goods (3) and
    talismans (2) share one id space across families, so they pool globally.
  * value -> a fully random price (default 1..60000), uncorrelated with the item
    (value_Magnification is 1 and value_Add is 0 on every merchant row, so the
    written value is exactly the displayed buy price).

equipType is preserved, so each row's ancillary fields (sellQuantity, mtrlId,
cost flags) stay valid for its slot type and every assigned id is one the game
already sells -> no invalid-entry / wrong-id-space hazards. Row map + pools come
from data/merchant_shop_slots.json (baked from a regulation dump).
"""

import json
import random
from collections import defaultdict

import regulation_io as R

DEFAULT_PRICE_RANGE = (1, 60000)


def seed_to_int(seed):
    if isinstance(seed, int):
        return seed & 0xFFFFFFFF
    s = str(seed).strip()
    try:
        return int(s) & 0xFFFFFFFF
    except ValueError:
        import hashlib
        return int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16) & 0xFFFFFFFF


def load_slots(json_path):
    """Load the baked {targets, pools, price_range} chaos map."""
    d = json.load(open(json_path, encoding="utf-8"))
    return {"targets": d["targets"], "pools": d["pools"],
            "price_range": tuple(d.get("price_range", DEFAULT_PRICE_RANGE))}


def roll(slot_data, seed, *, price_range=None, distinct_per_group=True):
    """Roll a new (equipId, value) for every merchant row. Returns
    (patches, spoiler) where patches = {row_id: (equip_id, price)}.
    Deterministic for `seed`."""
    rng = random.Random(seed_to_int(seed))
    pools = slot_data["pools"]
    targets = slot_data["targets"]
    lo, hi = price_range or slot_data.get("price_range", DEFAULT_PRICE_RANGE)

    by_group = defaultdict(list)
    for t in targets:
        by_group[t["group_key"]].append(t)

    patches, spoiler = {}, []
    for gk in sorted(by_group):
        by_pool = defaultdict(list)
        for t in by_group[gk]:
            by_pool[t["pool_key"]].append(t)
        for pool_key, ts in sorted(by_pool.items()):
            pool = pools.get(pool_key, [])
            if not pool:
                continue
            k = len(ts)
            ids = (rng.sample(pool, k) if distinct_per_group and k <= len(pool)
                   else [rng.choice(pool) for _ in ts])
            for t, eid in zip(ts, ids):
                price = rng.randint(lo, hi)
                patches[t["id"]] = (eid, price)
                spoiler.append({"row": t["id"], "group": gk, "pool": pool_key,
                                "equip_id": eid, "price": price})
    return patches, spoiler


def apply_patches(reg, patches):
    """Write each row's equipId (s32 @ SHOP_EQUIPID_OFF) and value/price
    (s32 @ SHOP_VALUE_OFF) in place. equipType is left untouched."""
    for row_id, (equip_id, price) in patches.items():
        reg.patch_param_field("ShopLineupParam", row_id, R.SHOP_EQUIPID_OFF, "<i", equip_id)
        reg.patch_param_field("ShopLineupParam", row_id, R.SHOP_VALUE_OFF, "<i", price)
    return len(patches)
