#!/usr/bin/env python3
"""merchant_shop_fill.py - per-seed-randomize the expedition merchant's shop.

Overwrites the ShopLineupParam rows of the Nomadic/Wandering merchant (c3200)
in a regulation.bin with a fresh, seed-deterministic roll of weapons (and an
optional weighted tail of talismans / goods). Pure chaos: uniform draws, random
affordable prices uncorrelated with item power (a junk weapon can out-cost a
Legendary). Each merchant entry in the slot manifest rolls independently, so if
NR routes different field merchants to different shop ranges they show different
stock in the same run.

This is the per-seed step the GUI / dcx_batch should call instead of plain-
copying the bundled regulation: read bundled regulation -> roll(seed) -> write
to the run output. The roll is reproducible from the run seed and emits a
spoiler list.

  python3 merchant_shop_fill.py \
      --in  bundled_regulation/regulation.bin \
      --out <run>/regulation.bin \
      --param-dump /path/to/regulation/csv-dump \
      --seed 8675309 \
      --type-weights 0.85:0.10:0.05 --price-range 100 2000

Pools are derived from the param dump CSVs (so MoreWeapons weapons are included
automatically when you point --param-dump at the shipping regulation's dump).
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re

import regulation_io as R

_LOOT_RE = re.compile(r"^\[(Common|Uncommon|Rare|Legendary)\]")


def _rarity(name: str):
    m = _LOOT_RE.match(name or "")
    return m.group(1) if m else None


def _read_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def load_pools(param_dump: str):
    """Return {'weapon': [...], 'talisman': [...], 'good': [...]} of clean,
    sellable, loot-rarity rows. Each item is (equip_id:int, name:str, rarity:str)."""
    def pool(filename, base_only=False):
        rows = _read_csv(os.path.join(param_dump, filename))
        out = []
        for r in rows:
            rid = int(r["ID"])
            if base_only and rid % 10000 != 0:
                continue
            rar = _rarity(r.get("Name", ""))
            if rar:
                out.append((rid, r["Name"], rar))
        return out
    return {
        "weapon": pool("EquipParamWeapon.csv", base_only=True),   # base +0 rows only
        "talisman": pool("EquipParamAccessory.csv"),
        "good": pool("EquipParamGoods.csv"),                      # loot-rarity only
    }


def load_pools_baked(json_path):
    """Load the clean pools from a baked data/regulation_pools.json (the shipped
    path, since the regulation itself carries no row names). Returns the same
    {'weapon'|'talisman'|'good': [(equip_id, name, rarity), ...]} shape as
    load_pools()."""
    d = json.load(open(json_path, encoding="utf-8"))
    return {k: [tuple(x) for x in d[k]] for k in ("weapon", "talisman", "good")}


# shop equipType code per pool
_EQUIPTYPE = {"weapon": 0, "talisman": 2, "good": 3}


def seed_to_int(seed) -> int:
    if isinstance(seed, int):
        return seed
    return int.from_bytes(hashlib.sha256(str(seed).encode()).digest()[:8], "big")


def roll(manifest: dict, pools: dict, seed, type_weights, price_range, allow_dups):
    """Produce {row_id: (equipType, equip_id, value)} plus a spoiler list."""
    rng = random.Random(seed_to_int(seed))
    types = ["weapon", "talisman", "good"]
    weights = [type_weights[t] for t in types]
    # drop empty pools from the weighting
    avail = [(t, w) for t, w in zip(types, weights) if pools[t] and w > 0]
    if not avail:
        raise SystemExit("no non-empty pools selected")
    a_types, a_weights = [t for t, _ in avail], [w for _, w in avail]

    patches, spoiler = {}, []
    for m in manifest["merchants"]:
        used = {t: set() for t in a_types}  # distinct per type, per merchant
        for rid in m["slots"]:
            t = rng.choices(a_types, a_weights)[0]
            pool = pools[t]
            # distinct within this merchant unless allow_dups or this pool is exhausted
            choice = None
            if allow_dups or len(used[t]) >= len(pool):
                choice = rng.choice(pool)
            else:
                for _ in range(64):
                    c = rng.choice(pool)
                    if c[0] not in used[t]:
                        choice = c
                        break
                if choice is None:
                    choice = rng.choice(pool)
            used[t].add(choice[0])
            equip_id, name, rar = choice
            value = rng.randint(price_range[0], price_range[1])
            patches[rid] = (_EQUIPTYPE[t], equip_id, value)
            spoiler.append({
                "merchant": m["name"], "row": rid, "type": t,
                "equip_id": equip_id, "name": name, "rarity": rar, "price": value,
            })
    return patches, spoiler


def apply_patches(reg: "R.Regulation", patches: dict):
    for rid, (etype, equip_id, value) in patches.items():
        reg.patch_param_field("ShopLineupParam", rid, R.SHOP_EQUIPTYPE_OFF, "<B", etype)
        reg.patch_param_field("ShopLineupParam", rid, R.SHOP_EQUIPID_OFF, "<i", equip_id)
        reg.patch_param_field("ShopLineupParam", rid, R.SHOP_VALUE_OFF, "<i", value)


def fill_regulation(in_path, out_path, param_dump, seed, *,
                    type_weights=(0.85, 0.10, 0.05), price_range=(100, 2000),
                    allow_dups=False, manifest_path=None, zstd_level=17,
                    spoiler_path=None, dry_run=False, key=R.NR_REGULATION_KEY):
    here = os.path.dirname(os.path.abspath(__file__))
    manifest_path = manifest_path or os.path.join(here, "data", "merchant_shop_slots.json")
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    pools = load_pools(param_dump)
    tw = {"weapon": type_weights[0], "talisman": type_weights[1], "good": type_weights[2]}
    patches, spoiler = roll(manifest, pools, seed, tw, price_range, allow_dups)

    if not dry_run:
        reg = R.Regulation.load(in_path, key)
        apply_patches(reg, patches)
        reg.save(out_path, key, level=zstd_level)
    if spoiler_path:
        json.dump(spoiler, open(spoiler_path, "w", encoding="utf-8"), indent=2)
    return {"pools": {k: len(v) for k, v in pools.items()},
            "slots": len(patches), "spoiler": spoiler}


def _parse_weights(s):
    parts = [float(x) for x in s.split(":")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("type-weights must be W:T:G (weapon:talisman:good)")
    return tuple(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="in_path", required=True, help="source regulation.bin")
    ap.add_argument("--out", dest="out_path", help="output regulation.bin (omit with --dry-run)")
    ap.add_argument("--param-dump", required=True, help="dir of regulation CSVs (EquipParam*.csv)")
    ap.add_argument("--seed", required=True, help="run seed (int or string)")
    ap.add_argument("--type-weights", type=_parse_weights, default=(0.85, 0.10, 0.05),
                    help="weapon:talisman:good draw weights (default 0.85:0.10:0.05)")
    ap.add_argument("--price-range", type=int, nargs=2, metavar=("LO", "HI"),
                    default=(100, 2000), help="random price band (default 100 2000)")
    ap.add_argument("--allow-dups", action="store_true",
                    help="allow the same item more than once per merchant")
    ap.add_argument("--slots", dest="manifest_path", help="slot manifest json")
    ap.add_argument("--zstd-level", type=int, default=17)
    ap.add_argument("--spoiler", dest="spoiler_path", help="write the roll spoiler json here")
    ap.add_argument("--dry-run", action="store_true", help="roll + print, don't write")
    args = ap.parse_args(argv)
    if not args.dry_run and not args.out_path:
        ap.error("--out is required unless --dry-run")

    res = fill_regulation(
        args.in_path, args.out_path, args.param_dump, args.seed,
        type_weights=args.type_weights, price_range=tuple(args.price_range),
        allow_dups=args.allow_dups, manifest_path=args.manifest_path,
        zstd_level=args.zstd_level, spoiler_path=args.spoiler_path, dry_run=args.dry_run,
    )
    print(f"pools: {res['pools']}   slots rolled: {res['slots']}")
    by_m = {}
    for s in res["spoiler"]:
        by_m.setdefault(s["merchant"], []).append(s)
    for m, items in by_m.items():
        print(f"\n[{m}]")
        for s in items:
            tag = {"weapon": "WPN", "talisman": "TAL", "good": "GD "}[s["type"]]
            print(f"  {s['row']}  {tag} {s['rarity'] or '-':<9} {s['equip_id']:>9}  "
                  f"{s['price']:>5}g  {s['name']}")
    if not args.dry_run:
        print(f"\nwrote {args.out_path}")


if __name__ == "__main__":
    main()
