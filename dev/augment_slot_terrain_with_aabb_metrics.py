#!/usr/bin/env python3
"""augment_slot_terrain_with_aabb_metrics.py — Add AABB-derived per-slot
metrics to slot_terrain.json for the wedged-against-wall and elevated-
rampart composite gates.

Pairs with augment_slot_terrain_with_polygons.py — together those two
augment scripts give slot_terrain.json the full discriminator feature
set from the v0.23.88 work (chat b2e767c9, "Baba booey", 2026-05-13).

ADDS per slot (alongside existing n10/n20/s_xz/s_y from build_slot_terrain.py
and slope_deg/area_*m/reach_count_5m/border_edge_dist from the polygon
augment):

    d_xz_edge    — distance from slot position to the nearest XZ edge of
                   its smallest containing leaf AABB. Small d_xz_edge =
                   slot is wedged against a wall. Combined with low
                   polygon reach_count_5m, this discriminates wedged-on-
                   mesh slots from healthy-near-edge slots (0.3% FP per
                   v0.23.88 calibration on m30_xx Fort tile).

    leaf_xz      — max XZ extent of the smallest containing leaf AABB.
                   Small leaf_xz = slot is on a narrow ledge or platform.

    leaf_y       — Y extent of the smallest containing leaf AABB.

    elev_frac    — vertical position of the slot within its leaf AABB,
                   normalized: (pos.y - leaf.ymin) / leaf.height. High
                   elev_frac = slot is in the top of a tall thin leaf,
                   characteristic of rampart/balcony tops (5.9% FP).

Usage:
    python augment_slot_terrain_with_aabb_metrics.py \\
        --slot-terrain data/slot_terrain.json \\
        --nm-dir /path/to/nightreign_navmesh \\
        --spoiler /path/to/any/spoiler.json \\
        --out data/slot_terrain.json

Runs much faster than the polygon augment — pure-Python AABB scan, no
soulstruct-havok deserialization. ~30-60s for the full corpus.
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from hkx_aabb_check import collect_navmesh_aabbs_from_bnd  # noqa: E402


def aabb_contains(b, p):
    return b[0] <= p[0] <= b[3] and b[1] <= p[1] <= b[4] and b[2] <= p[2] <= b[5]


def aabb_xz_extent(b):
    return max(b[3] - b[0], b[5] - b[2])


def compute_slot_metrics(aabbs, pos):
    """Return dict of AABB-derived metrics for the slot, or None if the
    position has no containing AABBs (off-cell / outside map bounds)."""
    containing = [b for b in aabbs if aabb_contains(b, pos)]
    if not containing:
        return None
    # Smallest-by-xz-extent containing AABB is the most local leaf.
    leaf = min(containing, key=aabb_xz_extent)
    leaf_xz = aabb_xz_extent(leaf)
    leaf_y = leaf[4] - leaf[1]
    y_above_floor = pos[1] - leaf[1]
    elev_frac = y_above_floor / max(leaf_y, 1e-6)
    d_xz_edge = min(
        pos[0] - leaf[0], leaf[3] - pos[0],
        pos[2] - leaf[2], leaf[5] - pos[2],
    )
    return {
        'leaf_xz':   round(leaf_xz, 2),
        'leaf_y':    round(leaf_y, 2),
        'elev_frac': round(elev_frac, 3),
        'd_xz_edge': round(d_xz_edge, 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot-terrain', required=True)
    ap.add_argument('--nm-dir', required=True)
    ap.add_argument('--spoiler', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--only-maps', default=None,
                    help='Comma-separated MSB names to limit (debugging)')
    args = ap.parse_args()

    print(f'Loading slot_terrain: {args.slot_terrain}')
    with open(args.slot_terrain) as f:
        st = json.load(f)
    sr = st.get('slot_roughness', {})

    print(f'Loading spoiler: {args.spoiler}')
    with open(args.spoiler) as f:
        sp = json.load(f)
    by_map = defaultdict(list)
    for e in sp['entries']:
        if not e.get('position'):
            continue
        by_map[e['map']].append(e)
    print(f'  spoiler entries: {sum(len(v) for v in by_map.values())} '
          f'across {len(by_map)} maps')

    only_maps = None
    if args.only_maps:
        only_maps = set(s.strip() for s in args.only_maps.split(','))

    t_total = time.time()
    n_maps = 0
    no_nav = []
    failed_maps = []
    merged = 0
    no_containing = 0

    for msb in sorted(by_map.keys()):
        if only_maps and msb not in only_maps:
            continue
        nm_path = os.path.join(args.nm_dir, msb.replace('.msb', '.nvmhktbnd'))
        if not os.path.isfile(nm_path):
            no_nav.append(msb)
            continue
        t0 = time.time()
        try:
            aabbs = collect_navmesh_aabbs_from_bnd(nm_path)
        except Exception as e:
            print(f'  {msb}: AABB extract failed: {e}')
            failed_maps.append((msb, str(e)))
            continue
        if not aabbs:
            no_nav.append(msb)
            continue
        n_maps += 1
        for e in by_map[msb]:
            pos = tuple(e['position'])
            metrics = compute_slot_metrics(aabbs, pos)
            if metrics is None:
                no_containing += 1
                continue
            pi_str = str(e['part_index'])
            sr.setdefault(msb, {}).setdefault(pi_str, {}).update(metrics)
            merged += 1
        dt = time.time() - t0
        if n_maps % 20 == 0 or n_maps == 1:
            print(f'  [{n_maps}] {msb}: {len(aabbs)} aabbs, {dt:.2f}s',
                  flush=True)

    elapsed = time.time() - t_total
    print(f'\nProcessed {n_maps} maps in {elapsed:.1f}s')
    print(f'Maps without navmesh: {len(no_nav)} (e.g., {no_nav[:3]})')
    print(f'Maps that failed to parse: {len(failed_maps)}')
    print(f'Slot entries augmented with AABB metrics: {merged}')
    print(f'Slot positions with no containing AABB (off-cell): {no_containing}')

    st.setdefault('metadata', {})
    st['metadata']['aabb_augment_version'] = 1
    st['metadata']['aabb_augment_timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
    st['metadata']['aabb_augment_maps_processed'] = n_maps

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or '.', exist_ok=True)
    with open(args.out, 'w') as f:
        json.dump(st, f, indent=2)
    print(f'\nWrote {args.out}')


if __name__ == '__main__':
    main()
