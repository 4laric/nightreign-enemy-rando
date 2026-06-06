#!/usr/bin/env python3
"""regulation_rando.py - per-seed in-place randomization of the bundled regulation.bin.

Randomizes three things per seed. (1) The expedition (Nomadic/Wandering) merchant's
shop inventory: every seed the merchant sells a different uniform-random mix of
weapons (plus a small weighted tail of talismans / goods), at random affordable
prices uncorrelated with item quality. (2) Drops: every ItemLotParam_enemy (enemy
on-death) and ItemLotParam_map (map pickups / treasure / breakables) lot has its
items rerolled in-category and its nothing-slot weight shrunk to lift the drop
rate (default x2). (3) Reward mapping: every miniboss-or-above roster chr that
drops nothing is given a tier-appropriate on-death lot (the one NpcParam edit).
Called by the bundled-file installer in oops_rando_gui.py so the installed
regulation matches the run seed.

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
import mob_drop_fill as _drops
import npcparam_reward_fill as _rewards
import npcparam_getsoul_fill as _getsoul

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
                         drop_rate_multiplier=None, log=None, **_legacy):
    """Decrypt in_bin, randomize the expedition-merchant shop, every enemy and
    map drop lot, map a reward onto every miniboss-or-above enemy that drops
    nothing, and floor each roster chr's getSoul to its tier median, all for
    `seed`; write out_bin. One decrypt/recompress/encrypt cycle covers every
    pass. Returns {'shop_slots', 'mob_drop_lots', 'map_drop_lots', 'reward_lots',
    'getsoul_floors': int, 'spoiler', 'drop_spoiler', 'map_spoiler',
    'reward_spoiler', 'getsoul_spoiler': [...]}.

    Shop: each Set slot's equipId is swapped for a random item of the same
    equipType from that merchant family's pool; equipType and value preserved.
    Drops: each ItemLotParam_enemy and ItemLotParam_map lot's items are rerolled
    in-category and its nothing-slot weight shrunk so P(any item) is multiplied
    by `drop_rate_multiplier` (default 2.0). Rewards: every miniboss+ roster chr
    with no drop on any field is assigned a tier-appropriate itemLotId_enemy.
    getSoul: every roster chr whose getSoul is below its tier median is lifted to
    it. Both NpcParam passes are pure floors; getSoul is seed-independent.
    (**_legacy swallows old kwargs.)
    """
    data_dir = data_dir or os.path.join(HERE, "data")
    slot_data = _shop.load_slots(os.path.join(data_dir, "merchant_shop_slots.json"))
    patches, spoiler = _shop.roll(slot_data, seed, price_range=price_range)

    reg = R.Regulation.load(in_bin)
    n = _shop.apply_patches(reg, patches)

    # Drop randomization on the SAME reg (one decrypt/recompress cycle): reroll
    # each lot's items in-category and shrink the nothing-slot weight to lift the
    # drop rate. Two ItemLotParam tables -- enemy on-death lots and map lots
    # (treasure / breakables / secondary enemy lots) -- with the map pass on a
    # derived seed so it isn't a shadow of the enemy pass.
    mult = drop_rate_multiplier or _drops.DEFAULT_RATE_MULTIPLIER
    drop_data = _drops.extract(reg, _drops.ENEMY_PARAM)
    drop_patches, drop_spoiler = _drops.roll(drop_data, seed, rate_multiplier=mult)
    n_drops = _drops.apply_patches(reg, drop_patches, _drops.ENEMY_PARAM)

    map_data = _drops.extract(reg, _drops.MAP_PARAM)
    map_patches, map_spoiler = _drops.roll(map_data, f"{seed}_map", rate_multiplier=mult)
    n_map = _drops.apply_patches(reg, map_patches, _drops.MAP_PARAM)

    # Reward mapping on the SAME reg: ensure every miniboss-or-above roster chr
    # that currently drops nothing gets an on-death lot. This is the only pass
    # that patches NpcParam (the drop passes never do -- drop RATE lives in the
    # lot, but WHICH lot a chr points to is a NpcParam field). Pure floor: a chr
    # already dropping in any reward field is left alone. Per-row seeded.
    reward_data = _rewards.extract(reg, data_dir)
    reward_patches, reward_spoiler = _rewards.roll(reward_data, seed)
    n_reward = _rewards.apply_patches(reg, reward_patches)

    # getSoul flooring on the SAME reg (the second NpcParam pass): lift every
    # roster chr whose authored getSoul sits below its tier's placement-weighted
    # vanilla median up to that median, so a relocated chr's rune reward matches
    # its tier instead of paying the vanilla pity floor. Pure floor -- never
    # lowers. Seed-independent (a fixed correction, not a reroll), so this does
    # not perturb per-seed determinism. Mirrors the static dev emitter
    # (dev/emit_getsoul_overrides.py) that was previously a manual Smithbox CSV.
    getsoul_data = _getsoul.extract(reg, data_dir)
    getsoul_patches, getsoul_spoiler = _getsoul.roll(getsoul_data, seed)
    n_getsoul = _getsoul.apply_patches(reg, getsoul_patches)

    reg.save(out_bin, level=zstd_level)

    lo, hi = price_range or slot_data.get("price_range", _shop.DEFAULT_PRICE_RANGE)
    if spoiler_path:
        json.dump(spoiler, open(spoiler_path, "w", encoding="utf-8"), indent=2)
        base = os.path.splitext(spoiler_path)[0]
        json.dump(drop_spoiler, open(base + "_drops.json", "w", encoding="utf-8"), indent=2)
        json.dump(map_spoiler, open(base + "_mapdrops.json", "w", encoding="utf-8"), indent=2)
        json.dump(reward_spoiler, open(base + "_rewards.json", "w", encoding="utf-8"), indent=2)
        json.dump(getsoul_spoiler, open(base + "_getsoul.json", "w", encoding="utf-8"), indent=2)
    if log:
        log(f"  merchant shop randomized (PURE CHAOS): {n} rows, items + random "
            f"prices {lo}-{hi} (seed {seed})\n")
        log(f"  mob drops randomized: {n_drops} enemy lots + {n_map} map lots, "
            f"drop rate x{mult:g} (seed {seed})\n")
        log(f"  miniboss+ rewards mapped: {n_reward} chrs given an on-death lot "
            f"(seed {seed})\n")
        log(f"  getSoul floored: {n_getsoul} chrs lifted to their tier median\n")
    return {"shop_slots": n, "mob_drop_lots": n_drops, "map_drop_lots": n_map,
            "reward_lots": n_reward, "getsoul_floors": n_getsoul, "spoiler": spoiler,
            "drop_spoiler": drop_spoiler, "map_spoiler": map_spoiler,
            "reward_spoiler": reward_spoiler, "getsoul_spoiler": getsoul_spoiler}


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Per-seed merchant-shop regulation randomizer")
    ap.add_argument("--in", dest="in_bin", required=True)
    ap.add_argument("--out", dest="out_bin", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--spoiler", dest="spoiler_path", default=None)
    ap.add_argument("--drop-rate", dest="drop_rate", type=float, default=None,
                    help="mob-drop rate multiplier (default 2.0)")
    a = ap.parse_args(argv)
    if not deps_available():
        raise SystemExit("needs the 'cryptography' and 'zstandard' packages "
                         "(pip install cryptography zstandard)")
    res = randomize_regulation(a.in_bin, a.out_bin, a.seed, data_dir=a.data_dir,
                               spoiler_path=a.spoiler_path,
                               drop_rate_multiplier=a.drop_rate,
                               log=lambda s: print(s, end=""))
    print(f"wrote {a.out_bin}  ({res['shop_slots']} shop slots, "
          f"{res['mob_drop_lots']} mob-drop lots, {res['map_drop_lots']} map-drop lots, "
          f"{res['reward_lots']} miniboss+ rewards, {res['getsoul_floors']} getSoul floors)")


if __name__ == "__main__":
    _main()
