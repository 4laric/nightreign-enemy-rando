#!/usr/bin/env python3
"""Tests for the More Weapons drop-pool GATE (the v0.31.x diagnostic checkbox).

The drop-pool merge itself (mob_drop_fill.extra_pools / load_extra_weapon_pool)
is exercised elsewhere; what's new here is that regulation_rando only folds the
pool in when more_weapons=True, so the GUI checkbox actually controls it and the
default is a strict no-op. Bakes a tiny pool into a temp data dir so the test
needs no MoreWeaponsTM install.
"""
import json
import os
import shutil
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REG = os.path.join(ROOT, "bundled_regulation", "regulation.bin")
need_reg = pytest.mark.skipif(not os.path.exists(REG), reason="no bundled regulation")


def _staged_data(tmp_path, *, pool_ids=None):
    """Copy the real data/ into tmp (so shop/reward/getsoul passes find their
    tables) and optionally bake a More Weapons pool into it. Isolated: never
    mutates the repo's own data/."""
    dst = tmp_path / "data"
    shutil.copytree(os.path.join(ROOT, "data"), dst)
    pool = dst / "more_weapons_pool.json"
    if pool.exists():
        pool.unlink()                      # ensure dormant baseline
    if pool_ids is not None:
        pool.write_text(json.dumps(
            {"_meta": {"weapon_lot_category": 6}, "weapon_drop_ids": pool_ids}))
    return str(dst)


def _deps():
    try:
        import cryptography  # noqa: F401
        import zstandard     # noqa: F401
        return True
    except Exception:
        return False


need_deps = pytest.mark.skipif(not _deps(), reason="needs cryptography + zstandard")

MW_IDS = [2140000, 3090000, 4020000]


def _weapon_ids_in_enemy_lots(path):
    import regulation_io as R
    reg = R.Regulation.load(path)
    off, _s, rows = reg._param("ItemLotParam_enemy")
    found = set()
    for rid in reg.param_rows("ItemLotParam_enemy"):
        b = off + rows[rid]
        ids = struct.unpack_from("<8i", reg.bnd, b)
        cats = struct.unpack_from("<8i", reg.bnd, b + 0x20)
        for i in range(8):
            if cats[i] == 6 and ids[i]:
                found.add(ids[i])
    return found


@need_reg
@need_deps
def test_flag_gates_injection(tmp_path):
    import regulation_rando as RR
    data_dir = _staged_data(tmp_path, pool_ids=MW_IDS)

    off_bin = str(tmp_path / "off.bin")
    on_bin = str(tmp_path / "on.bin")
    # Same seed both runs: the only difference is the flag.
    RR.randomize_regulation(REG, off_bin, seed=42, data_dir=data_dir, more_weapons=False)
    RR.randomize_regulation(REG, on_bin, seed=42, data_dir=data_dir, more_weapons=True)

    off = _weapon_ids_in_enemy_lots(off_bin)
    on = _weapon_ids_in_enemy_lots(on_bin)
    # OFF: none of the baked ids leak into a lot.
    assert not (set(MW_IDS) & off)
    # ON: at least one baked id is now rolled into a weapon lot.
    assert set(MW_IDS) & on


@need_reg
@need_deps
def test_default_is_off(tmp_path):
    """more_weapons defaults to False -> even a baked pool is ignored."""
    import regulation_rando as RR
    data_dir = _staged_data(tmp_path, pool_ids=MW_IDS)
    out = str(tmp_path / "default.bin")
    RR.randomize_regulation(REG, out, seed=42, data_dir=data_dir)  # no flag
    assert not (set(MW_IDS) & _weapon_ids_in_enemy_lots(out))


@need_reg
@need_deps
def test_on_but_unbaked_is_noop(tmp_path):
    """more_weapons=True with no pool file is still a no-op (file-gated loader)."""
    import regulation_rando as RR
    import mob_drop_fill as D
    data_dir = _staged_data(tmp_path)  # real tables, no pool baked
    assert D.load_extra_weapon_pool(data_dir) is None
    out = str(tmp_path / "noop.bin")
    # Should not raise and should produce a valid regulation.
    RR.randomize_regulation(REG, out, seed=42, data_dir=data_dir, more_weapons=True)
    assert os.path.exists(out)
