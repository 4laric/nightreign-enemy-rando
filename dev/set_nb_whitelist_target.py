#!/usr/bin/env python3
"""Flip data/nb_encounter_whitelist.json to target a single NB arena
for the rando-compat sweep. Convenience wrapper so the per-test cycle is
one CLI command instead of hand-editing JSON.

    python dev/set_nb_whitelist_target.py m48_40
    python dev/set_nb_whitelist_target.py m48_10 --bucket nb1
    python dev/set_nb_whitelist_target.py --restore-v1

Reads the canonical arena table from nightreign_arena_structure.json
so any unrecognized stem is rejected before the JSON gets clobbered.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STRUCT = os.path.join(REPO, 'data', 'nightreign_arena_structure.json')
WHITELIST = os.path.join(REPO, 'data', 'nb_encounter_whitelist.json')


def _load_arenas():
    with open(STRUCT, encoding='utf-8') as f:
        s = json.load(f)
    out = {}
    for k, v in s['night_boss_arenas'].items():
        if k.startswith('_'):
            continue
        out[k] = v
        # also let user pass the short form (m48_40 instead of m48_40_00_00)
        out[k.removesuffix('_00_00')] = v
    return out


def _write_whitelist(stem_full, bucket, info):
    bucket_other = 'nb2' if bucket == 'nb1' else 'nb1'
    payload = {
        '_doc': ('NB rando-compat sweep target. Single arena under test; '
                 'expand by editing nb1/nb2 by hand or rerunning '
                 'dev/set_nb_whitelist_target.py.'),
        '_version': 'v0.28.x',
        '_test_note': (f'Sweep target: {stem_full} '
                       f'({info["c_prefix"]} {info["boss"]}, tier={info["tier"]}). '
                       f'Restore V1 picks via --restore-v1.'),
        bucket: [stem_full],
        bucket_other: [],
    }
    with open(WHITELIST, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
        f.write('\n')


def _restore_v1():
    payload = {
        '_doc': ('V1 ship state: NB1=m49_10 (Grafted Monarch), '
                 'NB2=m48_40 (Morgott). Restored via --restore-v1.'),
        '_version': 'v0.28.x',
        'nb1': ['m49_10_00_00'],
        'nb2': ['m48_40_00_00'],
    }
    with open(WHITELIST, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
        f.write('\n')


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('arena', nargs='?',
                   help='Arena stem, e.g. m48_40 or m48_40_00_00.')
    p.add_argument('--restore-v1', action='store_true',
                   help='Restore the V1 spec picks (NB1=m49_10, NB2=m48_40).')
    p.add_argument('--all', action='store_true',
                   help='Set the whitelist to every known NB arena (28 of '
                        'them). Useful for one-seed-many-Nightlords sweeps '
                        'where you want any arena the seed routes to to '
                        'be randomized.')
    p.add_argument('--bucket', choices=['nb1', 'nb2'], default='nb1',
                   help='Which bucket to file the target under (default: nb1). '
                        'Engine treats both buckets identically, so this is '
                        'just metadata for human readers.')
    p.add_argument('--list', action='store_true',
                   help='Print the 28 known arenas and exit.')
    args = p.parse_args()

    arenas = _load_arenas()

    if args.list:
        seen = set()
        for k, v in sorted(arenas.items()):
            if k in seen or not k.endswith('_00_00'):
                continue
            seen.add(k)
            print(f"  {k}: {v['c_prefix']:14} {v['boss']}")
        return

    if args.restore_v1:
        _restore_v1()
        print("Restored V1 whitelist (NB1=m49_10, NB2=m48_40).")
        return

    if args.all:
        # Partition the 28 arenas by which slot (NB1 or NB2) they appear in
        # most commonly, so the JSON's nb1/nb2 buckets are at least
        # human-readable. The engine treats both buckets identically; this
        # split is purely metadata. Pulls the classification from the
        # structure JSON's expedition pool data.
        with open(STRUCT, encoding='utf-8') as f:
            s = json.load(f)
        from collections import Counter
        nb1_cnt = Counter()
        nb2_cnt = Counter()
        # arena_id -> known c_prefix lookup, used to match pool entries back
        cprefix_to_arena = {}
        for k, v in s['night_boss_arenas'].items():
            if k.startswith('_'):
                continue
            cprefix_to_arena[v['c_prefix']] = k
        # walk the per-Nightlord pools
        for exp, pools in s.get('expedition_to_night_boss_pool', {}).items():
            if exp.startswith('_'):
                continue
            for entry in pools.get('nb1_pool', []) or []:
                arena = entry.get('arena', '').rstrip('?')
                stem = arena if arena.endswith('_00_00') else f'{arena}_00_00'
                if stem in cprefix_to_arena.values():
                    nb1_cnt[stem] += 1
            for entry in pools.get('nb2_pool', []) or []:
                arena = entry.get('arena', '').rstrip('?')
                stem = arena if arena.endswith('_00_00') else f'{arena}_00_00'
                if stem in cprefix_to_arena.values():
                    nb2_cnt[stem] += 1
        all_arenas = [k for k in s['night_boss_arenas']
                      if not k.startswith('_')]
        nb1, nb2 = [], []
        for stem in all_arenas:
            if nb1_cnt[stem] >= nb2_cnt[stem]:
                nb1.append(stem)
            else:
                nb2.append(stem)
        payload = {
            '_doc': ('All-arenas whitelist for one-seed-many-Nightlords '
                     'sweeps. Buckets are split by pool-majority for '
                     'readability; engine treats nb1 and nb2 identically.'),
            '_version': 'v0.28.x',
            '_test_note': ('Sweep mode: all 28 NB arenas active. Restore V1 '
                           'picks via --restore-v1 when sweep is complete.'),
            'nb1': sorted(nb1),
            'nb2': sorted(nb2),
        }
        with open(WHITELIST, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
            f.write('\n')
        print(f"Whitelist set to all {len(nb1) + len(nb2)} NB arenas.")
        print(f"  nb1 bucket ({len(nb1)}): {nb1}")
        print(f"  nb2 bucket ({len(nb2)}): {nb2}")
        return

    if not args.arena:
        p.error("one of: arena, --all, --restore-v1, --list")

    stem_in = args.arena
    if stem_in not in arenas:
        print(f"ERROR: unknown arena {stem_in!r}.", file=sys.stderr)
        print(f"       Run with --list to see the 28 valid stems.",
              file=sys.stderr)
        sys.exit(2)

    info = arenas[stem_in]
    stem_full = (stem_in if stem_in.endswith('_00_00')
                 else f'{stem_in}_00_00')
    _write_whitelist(stem_full, args.bucket, info)
    print(f"Whitelist target -> {stem_full}")
    print(f"  c_prefix:  {info['c_prefix']}")
    print(f"  boss:      {info['boss']}")
    print(f"  tier:      {info['tier']}")
    print(f"  entity_id: {info['entity_id']}")
    print(f"  bucket:    {args.bucket}")


if __name__ == '__main__':
    main()
