#!/usr/bin/env python3
"""augment_slot_terrain_with_polygons.py — Augment slot_terrain.json with
polygon-derived metrics per slot.

Rebuilds from chat 6b45b632 (v0.23.88 session, 2026-05-12).

Reads the AABB-derived slot_terrain.json (n10/n20/s_xz/s_y per slot)
and adds polygon metrics (slope_deg, area_3m, area_5m, area_10m,
border_edge_dist, reach_count_5m) to the same slot_roughness entries.

Walks every map referenced in the spoiler (or every map for which we
have both navmesh + slot positions), parses the .nvmhktbnd once, and
computes per-slot polygon metrics from its hkaiNavMesh polygons.

Slots in FORCE_OFF_MESH maps (m32_xx cathedrals, m20/21_xx tunnels) are
INCLUDED in the polygon pass — those were excluded from AABB roughness
analysis because the BVH leaves were unreliable in those tiles, but
polygon geometry has finer resolution and may give meaningful metrics
where AABBs didn't.

Usage:
    python augment_slot_terrain_with_polygons.py \\
        --slot-terrain /path/to/slot_terrain.json \\
        --nm-dir /path/to/nightreign_navmesh \\
        --spoiler /path/to/any/spoiler.json \\
        --out data/slot_terrain.json [--max-maps N]

Runtime: ~2-4s per map, ~5-10 min for the full ~120-map corpus.
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from navmesh_polygon_metrics import load_navmesh, slot_metrics  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot-terrain', required=True,
                    help='Existing slot_terrain.json with AABB-derived data')
    ap.add_argument('--nm-dir', required=True,
                    help='Directory containing *.nvmhktbnd binders')
    ap.add_argument('--spoiler', required=True,
                    help='Any spoiler with slot positions (positions are '
                         'permanent so any seed works)')
    ap.add_argument('--out', required=True, help='Output augmented JSON')
    ap.add_argument('--max-maps', type=int, default=None,
                    help='Stop after N maps (debugging)')
    ap.add_argument('--only-maps', default=None,
                    help='Comma-separated list of MSB names to limit '
                         "(e.g., 'm34_30_00_00.msb,m32_00_00_00.msb')")
    args = ap.parse_args()

    print(f'Loading slot_terrain: {args.slot_terrain}')
    with open(args.slot_terrain) as f:
        st = json.load(f)
    sr = st.get('slot_roughness', {})
    print(f'  AABB roughness entries: {sum(len(v) for v in sr.values())} '
          f'across {len(sr)} maps')

    print(f'Loading spoiler positions: {args.spoiler}')
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

    polygon_data = defaultdict(dict)   # msb -> { pi_str -> {polygon metrics} }
    map_stats = []
    no_nav = []
    failed_maps = []
    t_total = time.time()
    n_maps = 0
    last_save_t = time.time()

    def _checkpoint_save():
        """Write a snapshot of progress so a timeout doesn't lose work."""
        snap = dict(st)
        snap_sr = {k: dict(v) for k, v in sr.items()}
        for msb, slots in polygon_data.items():
            if msb not in snap_sr:
                snap_sr[msb] = {}
            for pi_str, pm in slots.items():
                snap_sr[msb].setdefault(pi_str, {}).update(pm)
        snap['slot_roughness'] = snap_sr
        snap.setdefault('metadata', {})
        snap['metadata']['polygon_augment_progress_maps'] = n_maps
        snap['metadata']['polygon_augment_progress_partial'] = True
        tmp_path = args.out + '.partial'
        with open(tmp_path, 'w') as fp:
            json.dump(snap, fp, indent=2)
        # atomic-ish move (single-fs)
        os.replace(tmp_path, args.out)

    for msb in sorted(by_map.keys()):
        if only_maps and msb not in only_maps:
            continue
        if args.max_maps and n_maps >= args.max_maps:
            break
        nm_path = os.path.join(args.nm_dir, msb.replace('.msb', '.nvmhktbnd'))
        if not os.path.isfile(nm_path):
            no_nav.append(msb)
            continue
        t0 = time.time()
        try:
            nm = load_navmesh(nm_path)
        except Exception as e:
            print(f'  {msb}: load failed: {type(e).__name__}: {e}')
            failed_maps.append((msb, str(e)))
            continue
        if nm is None:
            no_nav.append(msb)
            continue
        n_slots = 0
        for e in by_map[msb]:
            pos = tuple(e['position'])
            try:
                m = slot_metrics(nm, pos)
            except Exception as exc:
                print(f'  {msb} pi={e["part_index"]}: metric err: {exc}')
                continue
            polygon_data[msb][str(e['part_index'])] = {
                'slope_deg': round(m['slope_deg'], 2)
                              if m['slope_deg'] == m['slope_deg'] else None,
                'border_edge_dist': round(m['border_edge_dist'], 2)
                              if m['border_edge_dist'] == m['border_edge_dist'] else None,
                'face_dist': round(m['face_dist'], 3),
                'area_3m':  round(m['area_3m'], 1),
                'area_5m':  round(m['area_5m'], 1),
                'area_10m': round(m['area_10m'], 1),
                'reach_count_5m': m['reach_count_5m'],
            }
            n_slots += 1
        dt = time.time() - t0
        n_maps += 1
        map_stats.append((msb, nm.n_faces, n_slots, dt))
        if n_maps % 10 == 0 or n_maps == 1:
            print(f'  [{n_maps}] {msb}: {nm.n_faces} faces, '
                  f'{n_slots} slots, {dt:.1f}s', flush=True)
        # Checkpoint every 30s
        if time.time() - last_save_t > 30:
            _checkpoint_save()
            last_save_t = time.time()

    elapsed = time.time() - t_total
    print(f'\nProcessed {n_maps} maps in {elapsed:.1f}s '
          f'({elapsed/n_maps:.2f}s/map avg)')
    print(f'Maps with no navmesh available: {len(no_nav)}')
    if no_nav[:5]:
        print(f'  e.g., {no_nav[:5]}')

    # Merge polygon data into slot_roughness — add new keys alongside
    # existing n10/n20/s_xz/s_y. For slots that had no AABB roughness
    # (FORCE_OFF_MESH maps), CREATE the entry with just polygon fields.
    merged = 0
    created = 0
    for msb, slots in polygon_data.items():
        if msb not in sr:
            sr[msb] = {}
        for pi_str, pmetrics in slots.items():
            if pi_str not in sr[msb]:
                sr[msb][pi_str] = {}
                created += 1
            else:
                merged += 1
            sr[msb][pi_str].update(pmetrics)

    # Bump metadata
    if 'metadata' not in st:
        st['metadata'] = {}
    st['metadata']['polygon_augment_version'] = 1
    st['metadata']['polygon_augment_timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
    st['metadata']['polygon_augment_maps_processed'] = n_maps
    st['slot_roughness'] = sr

    print(f'\nMerged polygon metrics into AABB entries: {merged}')
    print(f'Created new entries (FORCE_OFF_MESH slots): {created}')

    out_path = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(st, f, indent=2)
    print(f'\nWrote {out_path}')


if __name__ == '__main__':
    main()
