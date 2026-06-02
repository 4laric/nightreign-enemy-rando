#!/usr/bin/env python3
"""Translate NB arena IDs into fm's reroller inputs (Nightlord + Shifting
Earth + Map pattern id) for the rando-compat sweep.

fm's reroller exposes 'Map pattern id 0-39' which is the offset WITHIN
the currently-active Nightlord's 40-pattern pool. The community pattern
CSV (Elden_Ring_Nightreign_map_patterns_-_Patterns.csv) uses a global
0-319 index; converting:

    global_idx = csv col 0
    nightlord  = NIGHTLORDS[global_idx // 40]
    offset     = global_idx % 40   <- this is what the reroller wants

To use the lookup for a sweep: pick the arena you want to test, look up
the (Nightlord, ShiftingEarth, offset) tuples below, switch to that
expedition in-game, open the reroller, set the offset, click Reroll
pattern, Hot reload.

Usage:
    python dev/arena_to_reroller_inputs.py                 # full table
    python dev/arena_to_reroller_inputs.py m48_10          # one arena
    python dev/arena_to_reroller_inputs.py --csv PATH      # custom CSV
    python dev/arena_to_reroller_inputs.py --slot NB1      # filter
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

NIGHTLORDS = ['Gladius', 'Adel', 'Gnoster', 'Maris',
              'Libra', 'Fulghor', 'Caligo', 'Heolstor']

# NB-arena -> boss-name string as it appears in the CSV's NB1/NB2 columns.
# Labels verified against the community CSV; m48_70/m48_80 both map to
# "Godskin Duo" in the CSV (the CSV doesn't distinguish them), so a
# Godskin Duo match could be either arena -- the sweep needs to look at
# which one the game actually loaded.
ARENA_TO_BOSS = {
    'm47_70_00_00': 'Tibia Mariner',
    'm47_80_00_00': 'Gaping Dragon',
    'm47_90_00_00': 'Centipede Demon',
    'm48_00_00_00': "The Duke's Dear Freja",
    'm48_10_00_00': 'Smelter Demon',
    'm48_20_00_00': 'Nameless King',
    'm48_30_00_00': 'Dancer of the Boreal Valley',
    'm48_40_00_00': 'Morgott',
    'm48_50_00_00': 'Draconic Tree Sentinel and Royal Cavalrymen',
    'm48_60_00_00': 'Tree Sentinel and Royal Cavalrymen',
    'm48_70_00_00': 'Godskin Duo',       # ambiguous w/ m48_80
    'm48_80_00_00': 'Godskin Duo',       # ambiguous w/ m48_70
    'm48_90_00_00': 'Wormface',          # CSV uses bare 'Wormface' for Large Wormface
    'm49_10_00_00': 'Grafted Monarch',
    'm49_17_00_00': 'Valiant Gargoyle',
    'm49_18_00_00': 'Great Wyrm',
    'm49_19_00_00': 'Ancient Dragon',
    'm49_20_00_00': 'Fallingstar Beast',
    'm49_21_00_00': 'Death Rite Bird',
    'm49_23_00_00': 'Dragonkin Soldier',
    'm49_24_00_00': 'Bell Bearing Hunter',
    'm49_25_00_00': 'Crucible Knight and Golden Hippopotamus',
    'm49_26_00_00': 'Outland Commander',
    'm49_27_00_00': 'Battlefield Commander',
    'm49_28_00_00': "Night's Cavalry Duo",
    'm49_29_00_00': 'Demi-Human Queen and Swordmaster',
    'm49_30_00_00': 'Royal Revenant',
    'm49_90_00_00': 'Ulcerated Tree Spirit',
}

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(REPO, 'data',
                           'Elden_Ring_Nightreign_map_patterns.csv')


def load_csv(path):
    with open(path, encoding='utf-8') as f:
        rows = list(csv.reader(f))
    # rows[0] is the header row, rows[1] is a sub-header; data starts at rows[2]
    return rows[2:]


def find_matches(boss_label, data_rows, slot_filter=None):
    """Return list of (Nightlord, ShiftingEarth, offset, slot) for every
    pattern row that has boss_label as NB1, NB2, or Extra."""
    matches = []
    for r in data_rows:
        if len(r) < 8:
            continue
        try:
            global_idx = int(r[0])
        except ValueError:
            continue
        nl, se, _sp, _ev, nb1, nb2, extra = r[1:8]
        offset = global_idx % 40
        if boss_label == nb1:
            slot = 'NB1'
        elif boss_label == nb2:
            slot = 'NB2'
        elif boss_label == extra:
            slot = 'Extra'
        else:
            continue
        if slot_filter and slot != slot_filter:
            continue
        matches.append((nl, se, offset, slot))
    return matches


def render_arena(arena_stem, matches):
    boss = ARENA_TO_BOSS.get(arena_stem, '?')
    if not matches:
        print(f"{arena_stem}  ({boss}): no CSV matches")
        return
    by_group = defaultdict(list)
    for nl, se, off, slot in matches:
        by_group[(nl, se, slot)].append(off)
    print(f"{arena_stem}  ({boss})")
    for (nl, se, slot) in sorted(by_group):
        offs = sorted(by_group[(nl, se, slot)])
        print(f"  Nightlord={nl:9} ShiftingEarth={se:12} {slot}  "
              f"Map pattern id  = {offs}")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('arena', nargs='?',
                   help='Arena stem (e.g. m48_10 or m48_10_00_00). '
                        'Omit for full table.')
    p.add_argument('--csv', default=DEFAULT_CSV,
                   help=f'Pattern CSV path. Default: {DEFAULT_CSV}')
    p.add_argument('--slot', choices=['NB1', 'NB2', 'Extra'],
                   help='Only show matches at this slot.')
    args = p.parse_args()

    if not os.path.isfile(args.csv):
        print(f"ERROR: CSV not found: {args.csv}", file=sys.stderr)
        print(f"       Pass --csv with the path to the patterns sheet.",
              file=sys.stderr)
        sys.exit(2)

    data = load_csv(args.csv)

    if args.arena:
        stem = args.arena if args.arena.endswith('_00_00') else f'{args.arena}_00_00'
        if stem not in ARENA_TO_BOSS:
            print(f"ERROR: unknown arena {args.arena!r}.", file=sys.stderr)
            print(f"       Valid arenas: {sorted(ARENA_TO_BOSS)}",
                  file=sys.stderr)
            sys.exit(2)
        matches = find_matches(ARENA_TO_BOSS[stem], data, args.slot)
        render_arena(stem, matches)
        return

    for stem in ARENA_TO_BOSS:
        matches = find_matches(ARENA_TO_BOSS[stem], data, args.slot)
        render_arena(stem, matches)
        print()


if __name__ == '__main__':
    main()
