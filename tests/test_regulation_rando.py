#!/usr/bin/env python3
"""Tests for the v0.29 per-seed merchant-shop regulation randomizer.

Pure tests (baked-pool loading, seeded roll) always run against the shipped
data/regulation_pools.json. The end-to-end tests run only when the bundled
regulation is present AND the crypto/compression deps are installed:

    pip install cryptography zstandard
    pytest tests/test_regulation_rando.py -v

(The randomizer falls back to copying the bundled regulation unchanged if the
deps are missing, so these tests skip rather than fail in that case.)
"""

import hashlib
import importlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RR = importlib.import_module("regulation_rando")
R = importlib.import_module("regulation_io")
SHOP = importlib.import_module("merchant_shop_fill")

REG = os.path.join(ROOT, "bundled_regulation", "regulation.bin")
POOLS = os.path.join(ROOT, "data", "regulation_pools.json")
MANIFEST = os.path.join(ROOT, "data", "merchant_shop_slots.json")

need_reg = pytest.mark.skipif(not os.path.exists(REG), reason="no bundled regulation.bin")
need_deps = pytest.mark.skipif(not RR.deps_available(),
                               reason="cryptography/zstandard not installed")


# --------------------------------------------------------------------------- #
# pure (use the shipped baked pools)
# --------------------------------------------------------------------------- #
def test_baked_pools_present_and_sane():
    pools = SHOP.load_pools_baked(POOLS)
    assert set(pools) == {"weapon", "talisman", "good"}
    assert len(pools["weapon"]) == 377 and len(pools["talisman"]) == 61 and len(pools["good"]) == 92
    eid, name, rar = pools["weapon"][0]
    assert isinstance(eid, int) and rar in ("Common", "Uncommon", "Rare", "Legendary")


def test_manifest_has_46_rows():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    rows = [r for m in man["merchants"] for r in m["slots"]]
    assert len(rows) == 46 and len(set(rows)) == 46


def test_roll_deterministic_and_priced():
    pools = SHOP.load_pools_baked(POOLS)
    man = json.load(open(MANIFEST, encoding="utf-8"))
    tw = {"weapon": 0.85, "talisman": 0.10, "good": 0.05}
    p1, _ = SHOP.roll(man, pools, 8675309, tw, (100, 2000), allow_dups=False)
    p2, _ = SHOP.roll(man, pools, 8675309, tw, (100, 2000), allow_dups=False)
    p3, _ = SHOP.roll(man, pools, 42, tw, (100, 2000), allow_dups=False)
    assert p1 == p2 and p1 != p3 and len(p1) == 46
    for etype, _eid, price in p1.values():
        assert 100 <= price <= 2000 and etype in (0, 2, 3)


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
    assert res["shop_slots"] == 46

    reg = R.Regulation.load(out)
    code = {"weapon": 0, "talisman": 2, "good": 3}
    for s in res["spoiler"]:
        rid = s["row"]
        got = (reg.read_param_field("ShopLineupParam", rid, R.SHOP_EQUIPTYPE_OFF, "<B"),
               reg.read_param_field("ShopLineupParam", rid, R.SHOP_EQUIPID_OFF, "<i"),
               reg.read_param_field("ShopLineupParam", rid, R.SHOP_VALUE_OFF, "<i"))
        assert got == (code[s["type"]], s["equip_id"], s["price"])

    base = R.Regulation.load(REG)
    for rid in (100004, 900000):
        assert (base.read_param_field("ShopLineupParam", rid, R.SHOP_EQUIPID_OFF, "<i")
                == reg.read_param_field("ShopLineupParam", rid, R.SHOP_EQUIPID_OFF, "<i"))


@need_reg
@need_deps
def test_randomize_determinism_bytes(tmp_path):
    a = str(tmp_path / "a.bin"); b = str(tmp_path / "b.bin"); c = str(tmp_path / "c.bin")
    RR.randomize_regulation(REG, a, "8675309")
    RR.randomize_regulation(REG, b, "8675309")
    RR.randomize_regulation(REG, c, "999")
    h = lambda p: hashlib.sha256(open(p, "rb").read()).digest()
    assert h(a) == h(b) and h(a) != h(c)
