#!/usr/bin/env python3
"""Tests for the per-seed merchant-shop regulation randomizer.

Updated for the v0.32 PURE-CHAOS shop model: every merchant row (Always +
all Sets, all families) is randomized in-place from realm-split pools baked
into data/merchant_shop_slots.json ({targets, pools, price_range}), with
top-price compression. The old 46-slot curated manifest + regulation_pools
shop API (load_pools_baked, merchants/slots schema) is gone.

Pure tests (manifest shape, seeded roll) always run. The end-to-end tests
run only when the bundled regulation is present AND the crypto/compression
deps are installed:

    pip install cryptography zstandard
    pytest tests/test_regulation_rando.py -v

(The randomizer falls back to copying the bundled regulation unchanged if the
deps are missing, so these tests skip rather than fail in that case.)
"""

import hashlib
import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RR = importlib.import_module("regulation_rando")
R = importlib.import_module("regulation_io")
SHOP = importlib.import_module("merchant_shop_fill")

REG = os.path.join(ROOT, "bundled_regulation", "regulation.bin")
MANIFEST = os.path.join(ROOT, "data", "merchant_shop_slots.json")

need_reg = pytest.mark.skipif(not os.path.exists(REG), reason="no bundled regulation.bin")
need_deps = pytest.mark.skipif(not RR.deps_available(),
                               reason="cryptography/zstandard not installed")


# --------------------------------------------------------------------------- #
# pure (use the shipped chaos manifest)
# --------------------------------------------------------------------------- #
def test_chaos_manifest_sane():
    sd = SHOP.load_slots(MANIFEST)
    # Realm-split weapon pools + global goods/talisman pools (see
    # merchant_shop_fill module docstring for the id-space rationale).
    assert set(sd["pools"]) == {"W#normal", "W#DoN", "G", "T"}
    for key, pool in sd["pools"].items():
        assert pool and all(isinstance(e, int) for e in pool), key
    ids = [t["id"] for t in sd["targets"]]
    assert len(ids) == 1206 and len(set(ids)) == 1206  # every row, no dupes
    for t in sd["targets"]:
        assert t["pool_key"] in sd["pools"]
        assert t["group_key"]
    lo, hi = sd["price_range"]
    assert 1 <= lo < hi


def test_roll_deterministic_priced_and_in_pool():
    sd = SHOP.load_slots(MANIFEST)
    p1, s1 = SHOP.roll(sd, 8675309)
    p2, _ = SHOP.roll(sd, 8675309)
    p3, _ = SHOP.roll(sd, 42)
    assert p1 == p2 and p1 != p3
    assert len(p1) == len(sd["targets"])  # no pool_key in the manifest is empty

    # Prices respect the range AND the default top_compress=0.5: anything
    # above the median is pulled halfway back toward it.
    lo, hi = sd["price_range"]
    mid = (lo + hi) / 2.0
    cap = int(round(mid + (hi - mid) * 0.5))
    assert any(price > mid for _eid, price in p1.values())  # tail exists
    for _eid, price in p1.values():
        assert lo <= price <= cap

    # Every rolled equipId comes from the target's declared pool.
    pools = sd["pools"]
    for s in s1:
        assert s["equip_id"] in pools[s["pool"]]


def test_roll_no_top_compress_spans_range():
    sd = SHOP.load_slots(MANIFEST)
    p, _ = SHOP.roll(sd, 8675309, top_compress=1.0)
    lo, hi = sd["price_range"]
    mid = (lo + hi) / 2.0
    cap = int(round(mid + (hi - mid) * 0.5))
    prices = [price for _eid, price in p.values()]
    assert all(lo <= price <= hi for price in prices)
    assert max(prices) > cap  # compression off -> the expensive tail survives


# --------------------------------------------------------------------------- #
# end-to-end (real regulation + deps)
# --------------------------------------------------------------------------- #
@need_reg
@need_deps
def test_aes_roundtrip_byte_identical():
    raw = open(REG, "rb").read()
    assert R.aes_encrypt(R.aes_decrypt(raw), pkcs7=False) == raw  # key/IV canary


@need_reg
@need_deps
def test_randomize_writes_and_rereads(tmp_path):
    out = str(tmp_path / "regulation.bin")
    res = RR.randomize_regulation(REG, out, "8675309")
    sd = SHOP.load_slots(MANIFEST)
    assert res["shop_slots"] == len(sd["targets"]) == 1206

    # Every spoiler row's equipId + price landed in the param; equipType
    # is never touched (apply_patches contract).
    reg = R.Regulation.load(out)
    base = R.Regulation.load(REG)
    for s in res["spoiler"]:
        rid = s["row"]
        assert reg.read_param_field("ShopLineupParam", rid,
                                    R.SHOP_EQUIPID_OFF, "<i") == s["equip_id"]
        assert reg.read_param_field("ShopLineupParam", rid,
                                    R.SHOP_VALUE_OFF, "<i") == s["price"]
        assert (reg.read_param_field("ShopLineupParam", rid,
                                     R.SHOP_EQUIPTYPE_OFF, "<B")
                == base.read_param_field("ShopLineupParam", rid,
                                         R.SHOP_EQUIPTYPE_OFF, "<B"))

    # Non-merchant ShopLineupParam rows stay byte-identical to vanilla.
    target_ids = {t["id"] for t in sd["targets"]}
    untouched = [rid for rid in reg.param_rows("ShopLineupParam")
                 if rid not in target_ids][:25]
    assert untouched, "expected some non-merchant rows to exist"
    for rid in untouched:
        assert (base.read_param_field("ShopLineupParam", rid, R.SHOP_EQUIPID_OFF, "<i")
                == reg.read_param_field("ShopLineupParam", rid, R.SHOP_EQUIPID_OFF, "<i"))
        assert (base.read_param_field("ShopLineupParam", rid, R.SHOP_VALUE_OFF, "<i")
                == reg.read_param_field("ShopLineupParam", rid, R.SHOP_VALUE_OFF, "<i"))


@need_reg
@need_deps
def test_randomize_determinism_bytes(tmp_path):
    a = str(tmp_path / "a.bin"); b = str(tmp_path / "b.bin"); c = str(tmp_path / "c.bin")
    RR.randomize_regulation(REG, a, "8675309")
    RR.randomize_regulation(REG, b, "8675309")
    RR.randomize_regulation(REG, c, "999")
    h = lambda p: hashlib.sha256(open(p, "rb").read()).digest()
    assert h(a) == h(b) and h(a) != h(c)
