#!/usr/bin/env python3
"""regulation_rando.py - per-seed in-place randomization of the bundled regulation.bin.

Currently randomizes the expedition (Nomadic/Wandering) merchant's shop inventory:
every seed the merchant sells a different uniform-random mix of weapons (plus a
small weighted tail of talismans / goods), at random affordable prices uncorrelated
with item quality. Called by the bundled-file installer in oops_rando_gui.py so the
installed regulation matches the run seed.

Mechanics: fixed-width PARAM field patches in place (AES-256-CBC + ZSTD-DCX, via
regulation_io) - no row add/remove, no string edits, length-preserving. Offline /
me3 only: a modded regulation.bin is rejected by EAC online.

Pools come from data/regulation_pools.json (baked, rarity-filtered, intersected
with the shipping regulation) because the regulation itself carries no row names.
Slot targets come from data/merchant_shop_slots.json.

Deps: cryptography (AES) + zstandard (DCX ZSTD). If either is missing, callers
should fall back to copying the bundled regulation unchanged (see deps_available).

Dev CLI:
    python3 regulation_rando.py --in bundled_regulation/regulation.bin \
        --out /tmp/regulation.bin --seed 8675309 [--spoiler /tmp/shop.json]
"""

import json
import os

import regulation_io as R
import merchant_shop_fill as _shop

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TYPE_WEIGHTS = (0.85, 0.10, 0.05)   # weapon : talisman : good
DEFAULT_PRICE_RANGE = (100, 2000)


def deps_available():
    """True iff the crypto + compression deps for regulation editing import."""
    try:
        import cryptography  # noqa: F401
        import zstandard     # noqa: F401
        return True
    except Exception:
        return False


def randomize_regulation(in_bin, out_bin, seed, *, data_dir=None,
                         price_range=None, zstd_level=17, spoiler_path=None,
                         log=None, **_legacy):
    """Decrypt in_bin, randomize every expedition-merchant Set slot for `seed`,
    write out_bin. One decrypt/recompress/encrypt cycle. Returns
    {'shop_slots': int, 'sets': int, 'spoiler': [...]}.

    Each Set slot's equipId is swapped for a random item of the same equipType
    from that merchant family's pool; equipType and value are preserved. The
    engine picks one Set per seed, so randomizing all Sets covers whatever the
    player rolls. (**_legacy swallows old type_weights/price_range kwargs.)
    """
    data_dir = data_dir or os.path.join(HERE, "data")
    slot_data = _shop.load_slots(os.path.join(data_dir, "merchant_shop_slots.json"))
    patches, spoiler = _shop.roll(slot_data, seed, price_range=price_range)

    reg = R.Regulation.load(in_bin)
    n = _shop.apply_patches(reg, patches)
    reg.save(out_bin, level=zstd_level)

    lo, hi = price_range or slot_data.get("price_range", _shop.DEFAULT_PRICE_RANGE)
    if spoiler_path:
        json.dump(spoiler, open(spoiler_path, "w", encoding="utf-8"), indent=2)
    if log:
        log(f"  merchant shop randomized (PURE CHAOS): {n} rows, items + random "
            f"prices {lo}-{hi} (seed {seed})\n")
    return {"shop_slots": n, "spoiler": spoiler}


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Per-seed merchant-shop regulation randomizer")
    ap.add_argument("--in", dest="in_bin", required=True)
    ap.add_argument("--out", dest="out_bin", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--spoiler", dest="spoiler_path", default=None)
    a = ap.parse_args(argv)
    if not deps_available():
        raise SystemExit("needs the 'cryptography' and 'zstandard' packages "
                         "(pip install cryptography zstandard)")
    res = randomize_regulation(a.in_bin, a.out_bin, a.seed, data_dir=a.data_dir,
                               spoiler_path=a.spoiler_path, log=lambda s: print(s, end=""))
    print(f"wrote {a.out_bin}  ({res['shop_slots']} shop slots)")


if __name__ == "__main__":
    _main()
