#!/usr/bin/env python3
"""Generate a LotResultPlayAreaParam patch that forces each Nightlord's
NB1 and NB2 to specific bosses. Result is deterministic: every run of a
given Nightlord delivers the same NB1 + NB2 pair regardless of seed.

Patches LotResultPlayAreaParam (the authoritative NB selection table -
empirically verified). Leaves rows 400+ (chaos match / special game modes)
alone.

    python dev/set_nightlord_bosses.py --default
    python dev/set_nightlord_bosses.py --config my_config.json
    python dev/set_nightlord_bosses.py --list-bosses
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_VANILLA = '/home/claude/vanilla_dump/vanilla_nightreign_dump/LotResultPlayAreaParam.csv'
DEFAULT_OUT = os.path.join(REPO, 'regulation_fixes',
                           'LotResultPlayAreaParam_per_nightlord_smithbox.csv')

# Per-Nightlord row blocks (vanilla + DLC), inclusive ranges.
NIGHTLORD_BLOCKS = {
    'Gladius':  [(0, 39), (320, 329)],
    'Adel':     [(40, 79), (330, 339)],
    'Gnoster':  [(80, 119), (340, 349)],
    'Maris':    [(120, 159), (350, 359)],
    'Libra':    [(160, 199), (360, 369)],
    'Fulghor':  [(200, 239), (370, 379)],
    'Caligo':   [(240, 279), (380, 389)],
    'Heolstor': [(280, 319), (390, 399)],
}

# Boss catalog: modifier -> (bossId/smallBaseMapId, label, arena_msb)
BOSS_CATALOG = {
    400: (4840, 'Morgott',                              'm48_40', 'NB2'),
    402: (4860, 'Tree Sentinel + Royal Cavalrymen',     'm48_60', 'NB2'),
    403: (4850, 'Draconic Tree Sentinel + Royal Cav',   'm48_50', 'NB2'),
    406: (4930, 'Royal Revenant',                       'm49_30', 'NB1'),
    412: (4890, 'Large Wormface',                       'm48_90', 'NB1'),
    413: (4990, 'Ulcerated Tree Spirit',                'm49_90', 'NB1'),
    416: (4917, 'Valiant Gargoyle',                     'm49_17', 'NB1'),
    418: (4918, 'Great Wyrm Theodorix (Magma Wyrm)',    'm49_18', 'NB2'),
    427: (4780, 'Gaping Dragon (DS1)',                  'm47_80', 'NB1'),
    428: (4790, 'Centipede Demon (DS1)',                'm47_90', 'NB1'),
    429: (4800, "Duke's Dear Freja (DS2)",              'm48_00', 'NB1'),
    430: (4810, 'Smelter Demon (DS2)',                  'm48_10', 'NB1'),
    431: (4820, 'Nameless King (DS3)',                  'm48_20', 'NB2'),
    432: (4830, 'Dancer of the Boreal Valley (DS3)',    'm48_30', 'NB2'),
    434: (4880, 'Godskin Duo Noble + Apostle',          'm48_80', 'NB2'),
    435: (4920, 'Fallingstar Beast',                    'm49_20', 'NB2'),
    436: (4910, 'Grafted Monarch',                      'm49_10', 'NB1'),
    437: (4770, 'Tibia Mariner',                        'm47_70', 'NB1'),
    439: (4924, 'Bell Bearing Hunter',                  'm49_24', 'NB1'),
    440: (4928, "Night's Cavalry Duo",                  'm49_28', 'NB1'),
    443: (4921, 'Death Rite Bird',                      'm49_21', 'NB2'),
    444: (4929, 'Demi-Human Queen + Swordmaster',       'm49_29', 'NB1'),
    445: (4919, 'Ancient Dragon',                       'm49_19', 'NB2'),
    446: (4923, 'Dragonkin Soldier',                    'm49_23', 'NB2'),
    447: (4925, 'Crucible Knight + Hippopotamus',       'm49_25', 'NB2'),
    448: (4927, 'Battlefield Commander',                'm49_27', 'NB1'),
    449: (4926, 'Outland Commander',                    'm49_26', 'NB2'),
}

# Default per-Nightlord assignment: 16 unique arenas (57% coverage of 28 NBs).
# Each Nightlord run delivers a unique (NB1, NB2) pair.
DEFAULT_CONFIG = {
    'Gladius':  {'NB1': 444, 'NB2': 400},    # DHQ + Morgott (vanilla baseline pair)
    'Adel':     {'NB1': 427, 'NB2': 445},    # Gaping Dragon + Ancient Dragon
    'Gnoster':  {'NB1': 430, 'NB2': 418},    # Smelter Demon + Great Wyrm
    'Maris':    {'NB1': 436, 'NB2': 435},    # Grafted Monarch + Fallingstar
    'Libra':    {'NB1': 437, 'NB2': 443},    # Tibia Mariner + Death Rite Bird
    'Fulghor':  {'NB1': 428, 'NB2': 431},    # Centipede Demon + Nameless King
    'Caligo':   {'NB1': 429, 'NB2': 432},    # Duke's Dear Freja + Dancer
    'Heolstor': {'NB1': 406, 'NB2': 449},    # Royal Revenant + Outland Cmdr
}


def validate_config(cfg):
    """Verify config has all 8 Nightlords with valid modifier values."""
    missing = set(NIGHTLORD_BLOCKS) - set(cfg)
    if missing:
        raise ValueError(f"config missing Nightlords: {sorted(missing)}")
    for nl, picks in cfg.items():
        for slot in ('NB1', 'NB2'):
            if slot not in picks:
                raise ValueError(f"{nl} missing {slot} pick")
            mod = picks[slot]
            if mod not in BOSS_CATALOG:
                raise ValueError(f"{nl}/{slot}: modifier {mod} not in catalog")


def apply_config(vanilla_path, out_path, cfg):
    """Read vanilla, patch per-Nightlord blocks, write Smithbox CSV."""
    with open(vanilla_path, encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # Column indices
    name_idx = header.index('Name')
    bid1_idx = header.index('bossId1')
    bid2_idx = header.index('bossId2')
    bm1_idx = header.index('bossModifier1')
    bm2_idx = header.index('bossModifier2')

    # Build row -> nightlord mapping
    row_to_nl = {}
    for nl, blocks in NIGHTLORD_BLOCKS.items():
        for lo, hi in blocks:
            for i in range(lo, hi + 1):
                row_to_nl[i] = nl

    # Patch
    patched = []
    for idx, r in enumerate(rows):
        nl = row_to_nl.get(idx)
        if nl is None:
            continue   # rows 400+, chaos match etc — leave alone
        n1_mod = cfg[nl]['NB1']
        n2_mod = cfg[nl]['NB2']
        n1_sbmid, n1_label, _, _ = BOSS_CATALOG[n1_mod]
        n2_sbmid, n2_label, _, _ = BOSS_CATALOG[n2_mod]
        new_r = list(r)
        # Only patch if vanilla row has a non-zero NB assignment.
        if r[bm1_idx] not in ('0','') and r[bid1_idx] not in ('0',''):
            new_r[bid1_idx] = str(n1_sbmid)
            new_r[bm1_idx] = str(n1_mod)
        if r[bm2_idx] not in ('0','') and r[bid2_idx] not in ('0',''):
            new_r[bid2_idx] = str(n2_sbmid)
            new_r[bm2_idx] = str(n2_mod)
        new_r[name_idx] = f"{nl}: NB1={n1_label} NB2={n2_label}"
        patched.append(new_r)

    # Write
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\r\n')
        w.writerow(header)
        for r in patched:
            w.writerow(r)
    return len(patched)


def print_config_summary(cfg):
    print("\nPer-Nightlord assignment:")
    arenas_hit = set()
    for nl in NIGHTLORD_BLOCKS:
        n1 = cfg[nl]['NB1']
        n2 = cfg[nl]['NB2']
        n1_sbmid, n1_label, n1_arena, _ = BOSS_CATALOG[n1]
        n2_sbmid, n2_label, n2_arena, _ = BOSS_CATALOG[n2]
        arenas_hit.add(n1_arena)
        arenas_hit.add(n2_arena)
        print(f"  {nl:9}  NB1: {n1_label:42}  ({n1_arena})")
        print(f"             NB2: {n2_label:42}  ({n2_arena})")
    print(f"\nUnique arenas exercised: {len(arenas_hit)} of 28 ({100*len(arenas_hit)//28}%)")
    print(f"Arenas: {sorted(arenas_hit)}")


def list_bosses():
    print("Boss catalog (modifier -> info):\n")
    print(f"{'mod':>4}  {'arena':>7}  {'class':>5}  boss")
    for mod in sorted(BOSS_CATALOG):
        sbmid, label, arena, cls = BOSS_CATALOG[mod]
        print(f"  {mod:>3}  {arena:>7}  {cls:>4}  {label}")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--vanilla', default=DEFAULT_VANILLA,
                   help='Vanilla LotResultPlayAreaParam.csv path')
    p.add_argument('--out', default=DEFAULT_OUT,
                   help=f'Output CSV (default: {DEFAULT_OUT})')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--default', action='store_true',
                   help='Use built-in default config (16-arena coverage)')
    g.add_argument('--config', type=str,
                   help='Path to custom JSON config: {Nightlord: {NB1: mod, NB2: mod}}')
    g.add_argument('--list-bosses', action='store_true',
                   help='Print the boss catalog and exit')
    args = p.parse_args()

    if args.list_bosses:
        list_bosses()
        return

    if args.default:
        cfg = DEFAULT_CONFIG
    else:
        with open(args.config) as f:
            cfg = json.load(f)
        # JSON keys are strings; convert NB1/NB2 values to ints
        cfg = {nl: {k: int(v) for k, v in picks.items()}
               for nl, picks in cfg.items()}

    validate_config(cfg)
    print_config_summary(cfg)

    n = apply_config(args.vanilla, args.out, cfg)
    print(f"\nWrote {args.out}")
    print(f"Patched rows: {n}")


if __name__ == '__main__':
    main()
