"""Tests for tier-gated item-drop rarity (drop_tiers + mob_drop_fill +
merchant_shop_fill). All regulation-free — they use the committed data files
and synthetic lot/shop structures, so they run in CI.

Design: dev/DESIGN_tiered_drop_rarity.md.
"""
import collections
import os
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
DATA = os.path.join(REPO_ROOT, "data")

import drop_tiers                       # noqa: E402
import mob_drop_fill as md              # noqa: E402
import merchant_shop_fill as msf        # noqa: E402

MODEL = drop_tiers.DropTierModel(DATA)


# ── rarity-weight renormalization ──────────────────────────────────────
def test_weights_renormalize_over_present_rarities():
    # talismans exist only as Uncommon/Rare → weights restricted + summing to 1
    w = dict(MODEL._rarity_weights("nightlord", "talisman"))
    assert set(w) <= {"Uncommon", "Rare"}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    # weapons have all four
    w2 = dict(MODEL._rarity_weights("grunt", "weapon"))
    assert set(w2) == {"Common", "Uncommon", "Rare", "Legendary"}
    assert abs(sum(w2.values()) - 1.0) < 1e-9


def test_zero_weight_tier_for_kind_falls_back_to_uniform():
    # grunt gives Legendary 0 and talisman has no Common — but Uncommon/Rare
    # both have weight, so this stays well-defined and normalized.
    w = dict(MODEL._rarity_weights("grunt", "talisman"))
    assert abs(sum(w.values()) - 1.0) < 1e-9


# ── pick_item correctness ──────────────────────────────────────────────
def test_pick_item_stays_in_kind_and_is_a_real_id():
    # ids aren't globally unique across kinds, so verify the picked id is in
    # the requested kind's pool (not via the ambiguous id->kind map).
    rng = random.Random(0)
    kind_ids = {k: {i for (kk, _r), ids in MODEL.by_kind_rarity.items()
                    if kk == k for i in ids}
                for k in ("weapon", "talisman", "good")}
    for kind in ("weapon", "talisman", "good"):
        for _ in range(300):
            iid = MODEL.pick_item(rng, kind, "miniboss")
            assert iid in kind_ids[kind]


def test_nearest_bucket_fallback():
    # Legendary talisman doesn't exist; asking for it must resolve to the
    # nearest present rarity (Rare), never crash/None.
    b = MODEL._nearest_bucket("talisman", "Legendary")
    assert b and all(MODEL.id_to_rarity[i] in ("Uncommon", "Rare") for i in b)


# ── statistical: quality tracks tier ───────────────────────────────────
def _dist(tier, kind, n=20000, seed=1):
    rng = random.Random(seed)
    c = collections.Counter(
        MODEL.id_to_rarity[MODEL.pick_item(rng, kind, tier)] for _ in range(n))
    return {r: c[r] / n for r in drop_tiers.RARITIES}


def test_grunt_is_low_rarity_and_never_legendary():
    d = _dist("grunt", "weapon")
    assert d["Common"] > 0.45 and d["Legendary"] == 0.0


def test_nightlord_is_legendary_dominant():
    d = _dist("nightlord", "weapon")
    assert d["Legendary"] > 0.5 and d["Common"] == 0.0


def test_quality_is_monotone_across_tiers():
    # mean "rarity index" should rise grunt < miniboss < field_boss < night_boss
    idx = {r: i for i, r in enumerate(drop_tiers.RARITIES)}
    def mean_idx(tier):
        d = _dist(tier, "weapon")
        return sum(idx[r] * p for r, p in d.items())
    a, b, c, e = (mean_idx("grunt"), mean_idx("miniboss"),
                  mean_idx("field_boss"), mean_idx("night_boss"))
    assert a < b < c < e


def test_unknown_tier_for_unmapped_lot():
    assert MODEL.tier_for_lot(987654321) == "unknown"


# ── mob_drop_fill integration (synthetic, regulation-free) ─────────────
def _synthetic_drop_data():
    # one lot: slot 0 is an ability buff (preserve), slot 1 a normal weapon.
    return {
        "pools": {6: [1000000]},
        "targets": [{
            "row": 6400000,
            "items": [(0, 6, 100), (1, 6, 100)],
            "nothings": [],
            "preserve": [0],
            "orig_ids": {0: 8500100, 1: 2010000},  # buff, weapon
            "tier": "nightlord",
        }],
    }


def test_gated_roll_preserves_buff_and_gates_weapon():
    model = drop_tiers.DropTierModel(DATA)
    model.cat_to_kind[6] = "weapon"          # category 6 is the weapon drop cat
    weapon_ids = {i for (k, _r), ids in model.by_kind_rarity.items()
                  if k == "weapon" for i in ids}
    dd = _synthetic_drop_data()
    patches, _ = md.roll(dd, seed=5, tier_model=model)
    offs = {off for off, _f, _v in patches[6400000]}
    assert md.ID_OFF + 4 * 0 not in offs, "buff slot must be preserved"
    slot1 = [v for off, _f, v in patches[6400000] if off == md.ID_OFF + 4 * 1][0]
    assert slot1 in weapon_ids, "gated slot must draw a real weapon"


def test_gated_roll_is_deterministic():
    model = drop_tiers.DropTierModel(DATA)
    model.cat_to_kind[6] = "weapon"
    dd = _synthetic_drop_data()
    p1, _ = md.roll(dd, seed=5, tier_model=model)
    p2, _ = md.roll(dd, seed=5, tier_model=model)
    assert p1 == p2


def test_legacy_roll_without_model_unchanged():
    # No model → uniform draw from the slot's category pool (legacy behavior).
    dd = _synthetic_drop_data()
    dd["targets"][0]["preserve"] = []  # let both slots reroll
    patches, _ = md.roll(dd, seed=5)   # tier_model=None
    vals = [v for off, _f, v in patches[6400000]]
    assert all(v == 1000000 for v in vals)  # only id in pool[6]


# ── shop top-price compression ─────────────────────────────────────────
def _shop_data():
    return {"pools": {"k": [1, 2, 3, 4, 5]},
            "targets": [{"id": i, "group_key": "g", "pool_key": "k"}
                        for i in range(60)]}


def test_shop_compress_pulls_top_toward_median():
    sd = _shop_data()
    rng_range = (1, 60000)
    mid = (1 + 60000) / 2.0
    comp, _ = msf.roll(sd, seed=3, price_range=rng_range, top_compress=0.5)
    full, _ = msf.roll(sd, seed=3, price_range=rng_range, top_compress=1.0)
    # same seed → same equip + raw price sequence; compare per row
    for rid in comp:
        _, c = comp[rid]
        _, r = full[rid]
        assert c <= r
        if r > mid:
            assert c == int(round(mid + (r - mid) * 0.5))
    assert max(p for _, p in comp.values()) <= mid + (60000 - mid) * 0.5 + 1
