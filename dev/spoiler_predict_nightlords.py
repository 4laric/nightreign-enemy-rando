#!/usr/bin/env python3
"""Spoiler predictor — given a spoiler.json from a built run, show
what's at each Night Boss arena (caliber-check + cap status), and
optionally predict per-Nightlord encounters using the matchmaker
expedition table.

Usage:
  python3 dev/spoiler_predict_nightlords.py PATH/TO/_spoilers.json

  # Only show per-arena (skip Nightlord prediction)
  python3 dev/spoiler_predict_nightlords.py PATH/TO/_spoilers.json --no-nightlord

The Nightlord prediction requires data/nightlord_expedition_table.json
to be filled in — empty arena pools (the default ship state) will be
shown as "TABLE EMPTY". Fill in N1/N2 arenas per Nightlord from your
playthrough knowledge, then re-run.

Pre-playtest workflow:
  1. Run the rando, get _spoilers.json
  2. python3 dev/spoiler_predict_nightlords.py output/_spoilers.json
  3. Tool prints what to expect at each arena
  4. Pick a Nightlord whose pool covers arenas you want to verify
  5. Play it, confirm spoiler matches in-game
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oops_v3


# Same arena list as audit, with display labels
NB_ARENAS = [
    ('m47_70_00_00', 'Tibia Mariner'),
    ('m48_40_00_00', 'Morgott'),
    ('m48_50_00_00', 'Draconic Tree Sentinel'),
    ('m48_60_00_00', 'Tree Sentinel'),
    ('m48_70_00_00', 'Godskin Apostle (solo)'),
    ('m48_80_00_00', 'Godskin Duo'),
    ('m48_90_00_00', 'Large Wormface'),
    ('m49_10_00_00', 'Grafted Monarch'),
    ('m49_17_00_00', 'Valiant Gargoyle'),
    ('m49_18_00_00', 'Great Wyrm Theodorix'),
    ('m49_19_00_00', 'Ancient Dragon'),
    ('m49_20_00_00', 'Fallingstar Beast'),
    ('m49_21_00_00', 'Death Rite Bird'),
    ('m49_23_00_00', 'Dragonkin Soldier'),
    ('m49_24_00_00', 'Bell Bearing Hunter'),
    ('m49_25_00_00', 'Crucible Knight + Hippopotamus'),
    ('m49_26_00_00', 'Outland Commander'),
    ('m49_27_00_00', 'Battlefield Commander'),
    ('m49_28_00_00', "Night's Cavalry x2"),
    ('m49_29_00_00', 'Demi-Human Queen + Swordmaster'),
    ('m49_30_00_00', 'Royal Revenant'),
    ('m49_90_00_00', 'Ulcerated Tree Spirit'),
]

ARENA_LABEL = dict(NB_ARENAS)


def collect_arena_picks(spoiler):
    """Return dict: arena_msb -> list of (pi, source_cp, source_name,
    new_cp, new_name) for all NB-marker slots at NB arenas. Skips
    Spirit-summon support entities (they're scripted-spawned by the
    main boss event chain, not direct-randomized headline picks)."""
    out = {arena: [] for arena, _ in NB_ARENAS}
    for e in spoiler['entries']:
        msb = e['map'].replace('.msb', '')
        if msb not in out:
            continue
        src_name = e['original'].get('name', '')
        if 'Night Boss' not in src_name:
            continue
        if 'Spirit' in src_name:
            continue  # support entities — not headline pick
        out[msb].append((
            e['part_index'],
            e['original']['c_prefix'],
            src_name,
            e['new']['c_prefix'],
            e['new'].get('name', ''),
        ))
    return out


def caliber_marker(cp):
    """Return display marker for a c-prefix's caliber status."""
    if cp in oops_v3.V3_NIGHT_BOSS_CALIBER_TARGETS:
        return 'OK'
    return '!! NON-CALIBER !!'


def format_pick(pick):
    """Render one (pi, src_cp, src_name, new_cp, new_name) as a line."""
    pi, src_cp, src_name, new_cp, new_name = pick
    cap_marker = ''
    if new_cp in oops_v3.V3_UNIQUE_TARGET_CAPS:
        cap_marker = f' [cap={oops_v3.V3_UNIQUE_TARGET_CAPS[new_cp]}]'
    return (f'    pi={pi:<3} '
            f'src={src_cp} ({src_name[:32]:<32}) -> '
            f'{new_cp} ({new_name[:32]:<32}) '
            f'{caliber_marker(new_cp)}{cap_marker}')


def cmd_per_arena(picks_by_arena):
    """Print all 22 NB arenas with their placements."""
    print()
    print('=' * 90)
    print(' Per-arena placements (all 22 Night Boss arenas)')
    print('=' * 90)
    n_violations = 0
    for arena, label in NB_ARENAS:
        picks = picks_by_arena[arena]
        if not picks:
            print(f'\n{arena}  {label}')
            print('    (no NB-marker slots in spoiler — '
                  'either source-excluded or arena not shuffled)')
            continue
        print(f'\n{arena}  {label}')
        for pick in picks:
            print(format_pick(pick))
            if pick[3] not in oops_v3.V3_NIGHT_BOSS_CALIBER_TARGETS:
                n_violations += 1
    print()
    print(f'Caliber violations across all NB arenas: {n_violations}')
    return n_violations


def cmd_per_nightlord(picks_by_arena, table):
    """Print per-Nightlord predicted N1/N2 arena exposures."""
    print()
    print('=' * 90)
    print(' Per-Nightlord predictions')
    print('=' * 90)
    # Filter to actual Nightlord entries (skip _comment, _arena_reference)
    nightlords = {k: v for k, v in table.items() if not k.startswith('_')}
    any_filled = False
    for nightlord, pools in nightlords.items():
        n1 = pools.get('n1_arenas', [])
        n2 = pools.get('n2_arenas', [])
        if not n1 and not n2:
            print(f'\n{nightlord}: TABLE EMPTY')
            continue
        any_filled = True
        print(f'\n{nightlord}')
        for night_label, arenas in (('N1', n1), ('N2', n2)):
            if not arenas:
                print(f'  {night_label}: (empty in table)')
                continue
            print(f'  {night_label} pool:')
            for arena in arenas:
                if arena not in ARENA_LABEL:
                    print(f'    {arena}: !! UNKNOWN ARENA !!')
                    continue
                label = ARENA_LABEL[arena]
                picks = picks_by_arena.get(arena, [])
                if not picks:
                    print(f'    {arena} {label}: (no spoiler entry)')
                    continue
                # Headline pick is the lowest-pi non-support entity
                pi, _, _, new_cp, new_name = picks[0]
                cm = caliber_marker(new_cp)
                marker = ''
                if len(picks) > 1:
                    extras = [f'pi={p[0]}:{p[3]}' for p in picks[1:]]
                    marker = f'  +({", ".join(extras)})'
                print(f'    {arena} {label[:32]:<32} '
                      f'-> {new_cp} ({new_name[:30]}) {cm}{marker}')
    if not any_filled:
        print('\n!! All Nightlord pools are empty.')
        print('   Fill in data/nightlord_expedition_table.json from your')
        print('   playthrough knowledge to enable per-Nightlord predictions.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spoiler', help='Path to _spoilers.json')
    ap.add_argument('--no-nightlord', action='store_true',
                    help='Skip per-Nightlord prediction (only show per-arena)')
    ap.add_argument('--table',
                    default='data/nightlord_expedition_table.json',
                    help='Path to nightlord expedition table JSON')
    args = ap.parse_args()

    with open(args.spoiler) as f:
        spoiler = json.load(f)

    print(f'Spoiler: {args.spoiler}')
    print(f'  Seed: {spoiler.get("seed")}')
    print(f'  Engine: {spoiler.get("engine_version")} '
          f'({spoiler.get("engine_fingerprint")})')
    print(f'  Mode: mp_safe={spoiler.get("multiplayer_safe")}')
    print(f'  Entries: {spoiler.get("entry_count")}')
    print(f'  Caliber set size: '
          f'{len(oops_v3.V3_NIGHT_BOSS_CALIBER_TARGETS)}')

    picks_by_arena = collect_arena_picks(spoiler)
    n_violations = cmd_per_arena(picks_by_arena)

    if not args.no_nightlord:
        # Resolve table path relative to repo root
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        table_path = args.table
        if not os.path.isabs(table_path):
            table_path = os.path.join(repo_root, table_path)
        if os.path.exists(table_path):
            with open(table_path) as f:
                table = json.load(f)
            cmd_per_nightlord(picks_by_arena, table)
        else:
            print(f'\nNo expedition table at {table_path}; '
                  f'skipping per-Nightlord prediction.')

    return 0 if n_violations == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
