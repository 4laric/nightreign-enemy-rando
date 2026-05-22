#!/usr/bin/env python3
"""build_part_positions.py — Aggregate Part positions from spoiler files.

Produces data/nr_all_part_positions.json — a (msb, part_index) → position
map that the stacking detector consults to check for collisions against
non-repositioned slots.

The blind-spot bug this addresses: distribute_stacked_repositions.py only
groups slots that share a target XYZ WITHIN slot_repositions.json. If a
repositioned slot's to_pos_center happens to coincide with the VANILLA
position of a non-repositioned slot, the detector misses it. Concrete
case (v0.24.29-era): m45_01 pi=2 vanilla at (2.55, 1.98, 5.78) and
m45_01 pi=5 (origin sentinel → repositioned to 2.55, 1.98, 5.779) stack at
the same point. XZ distance 0.001m. Stacking detector didn't see it
because pi=2 isn't in slot_repositions.json.

DATA SOURCE:
Spoilers (in --spoilers-dir, default /mnt/user-data/uploads) are the
authoritative source for Part positions. Each spoiler entry records the
position of (msb, part_index) as written to the MSB.

POSITION RESOLUTION:
For each (msb, pi):
  1. If the slot is in slot_repositions.json: use slot_repositions.from_pos
     (the authoritative vanilla position; spoiler position would be
     post-reposition).
  2. Otherwise: use any spoiler position (positions don't change across
     seeds for non-repositioned slots — vanilla MSB is read-only input).

OUTPUT:
{
  "_meta": {
    "generator": "build_part_positions.py",
    "version": "v1",
    "input_spoilers": [...],
    "n_slots": ...,
    "n_origin_sentinel": ...,  # slots whose vanilla pos is (0,0,0)
    "n_from_slot_repositions": ...,  # slots resolved via slot_repositions.from_pos
    "n_from_spoiler": ...,           # slots resolved via spoiler position
    "n_inconsistent": ...,           # slots with conflicting spoiler positions
  },
  "positions": {
    "msb_name.msb": {
      "0": [x, y, z],
      "1": [x, y, z],
      ...
    },
    ...
  }
}

USAGE:
    python dev/build_part_positions.py \\
        --spoilers-dir /path/to/spoilers \\
        --slot-repositions data/slot_repositions.json \\
        --output data/nr_all_part_positions.json
"""
import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict


SCRIPT_VERSION = 'build_part_positions v1 (v0.24.37)'
ORIGIN_EPSILON = 0.01


def _is_origin(pos):
    return all(abs(c) < ORIGIN_EPSILON for c in pos)


def _xz_distance(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def collect_spoiler_positions(spoilers_dir):
    """Read every spoiler JSON in spoilers_dir; collect Part positions.

    Returns (positions_by_slot, spoiler_paths) where positions_by_slot is
    {(msb, pi): [(seed, position_tuple), ...]} and spoiler_paths is the
    list of files consulted.
    """
    positions_by_slot = defaultdict(list)
    spoiler_paths = sorted(glob.glob(os.path.join(spoilers_dir, '*_spoilers.json')))
    if not spoiler_paths:
        # Try alternate naming
        spoiler_paths = sorted(glob.glob(os.path.join(spoilers_dir, '*__spoilers.json')))
    for path in spoiler_paths:
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception as e:
            print(f'  WARN: could not parse {path}: {e}', file=sys.stderr)
            continue
        seed = d.get('seed')
        for e in d.get('entries', []):
            msb = e.get('map')
            pi = e.get('part_index')
            pos = e.get('position')
            if msb is None or pi is None or pos is None:
                continue
            positions_by_slot[(msb, pi)].append((seed, tuple(pos)))
    return positions_by_slot, spoiler_paths


def build_positions(spoilers_dir, slot_repositions_path):
    """Build the merged positions data."""
    positions_by_slot, spoiler_paths = collect_spoiler_positions(spoilers_dir)
    print(f'Loaded {len(spoiler_paths)} spoiler files; '
          f'{len(positions_by_slot)} unique slots observed.')

    # Load slot_repositions for authoritative vanilla positions on repositioned slots
    repositioned = {}  # (msb, pi) -> from_pos
    if os.path.isfile(slot_repositions_path):
        with open(slot_repositions_path) as f:
            rd = json.load(f)
        for msb, props in rd.get('proposals', {}).items():
            for pi_str, entry in props.items():
                fp = entry.get('from_pos')
                if fp:
                    repositioned[(msb, int(pi_str))] = fp
        print(f'Loaded {len(repositioned)} slot_repositions entries.')

    out_positions = defaultdict(dict)
    n_from_repos = 0
    n_from_spoiler = 0
    n_origin = 0
    n_inconsistent = 0

    for (msb, pi), observations in positions_by_slot.items():
        if (msb, pi) in repositioned:
            # Use slot_repositions.from_pos — authoritative vanilla position
            chosen = list(repositioned[(msb, pi)])
            source = 'slot_repositions.from_pos'
            n_from_repos += 1
        else:
            # Use spoiler positions. Check consistency: most slots agree
            # across seeds; warn on disagreement.
            unique = set(tuple(round(c, 3) for c in pos) for _, pos in observations)
            if len(unique) > 1:
                n_inconsistent += 1
                # Use the most-frequent position
                from collections import Counter
                pc = Counter(tuple(round(c, 3) for c in pos)
                             for _, pos in observations)
                chosen = list(pc.most_common(1)[0][0])
            else:
                chosen = list(next(iter(unique)))
            source = 'spoiler'
            n_from_spoiler += 1

        if _is_origin(chosen):
            n_origin += 1

        out_positions[msb][str(pi)] = chosen

    return {
        '_meta': {
            'generator': 'build_part_positions.py',
            'version': SCRIPT_VERSION,
            'input_spoilers': [os.path.basename(p) for p in spoiler_paths],
            'n_slots': sum(len(d) for d in out_positions.values()),
            'n_msbs': len(out_positions),
            'n_from_slot_repositions': n_from_repos,
            'n_from_spoiler': n_from_spoiler,
            'n_origin_sentinel': n_origin,
            'n_inconsistent': n_inconsistent,
            'note': (
                'For repositioned slots, position is the from_pos field '
                'of the slot_repositions entry (authoritative vanilla). '
                'For non-repositioned slots, position is the most-frequent '
                'value observed across spoiler files (should be consistent '
                'across seeds since vanilla MSBs are read-only inputs).'
            ),
        },
        'positions': dict(out_positions),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--spoilers-dir', default='/mnt/user-data/uploads',
                   help='Directory containing spoiler JSON files')
    p.add_argument('--slot-repositions', default='data/slot_repositions.json')
    p.add_argument('--output', default='data/nr_all_part_positions.json')
    args = p.parse_args()

    data = build_positions(args.spoilers_dir, args.slot_repositions)
    # Sort MSBs and pis for deterministic output
    sorted_positions = {}
    for msb in sorted(data['positions']):
        pis = data['positions'][msb]
        sorted_positions[msb] = {pi: pis[pi] for pi in sorted(pis, key=int)}
    data['positions'] = sorted_positions

    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

    m = data['_meta']
    print(f'\nWrote {args.output}')
    print(f'  Slots:               {m["n_slots"]} across {m["n_msbs"]} MSBs')
    print(f'  From slot_repositions: {m["n_from_slot_repositions"]}')
    print(f'  From spoiler:        {m["n_from_spoiler"]}')
    print(f'  Origin sentinels:    {m["n_origin_sentinel"]}')
    print(f'  Inconsistent across seeds: {m["n_inconsistent"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
