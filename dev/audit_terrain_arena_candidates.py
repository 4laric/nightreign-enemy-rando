#!/usr/bin/env python3
"""audit_terrain_arena_candidates.py — identify slots whose terrain is
"big and flat" enough to host a boss arena, even if their source variant
name doesn't carry an existing arena marker.

Driven by user direction from the reservation-health arc:
  > "now that we have more terrain data we can use it to identify more
     arena slots. criteria is big and flat."

Data sources (all read-only):
  data/slot_terrain.json   — per-slot navmesh roughness metrics
                              (slope_deg, area_3m/5m/10m, d_xz_edge,
                              leaf_xz/leaf_y, face_dist, border_edge_dist)
  data/nr_boss_slots.json  — existing arena catalog (to dedupe)
  data/NpcParam.csv        — chr hitbox dimensions (size grouping)
  data/nr_enemy_tags.json  — chr metadata (name, size_class, anim_class)

Output: dev/terrain_arena_candidates.json — list of slot keys
        (msb, pi) that pass the big-and-flat criteria but aren't
        already catalogued as boss arenas. Each entry carries the
        terrain metrics + vanilla-occupant context so a human (or
        engine extension) can decide what to do with them.

Criteria for "big and flat" arena candidate:
  - slope_deg < 10°  (mild slope, acceptable for ground-boss combat)
  - area_10m >= 200  (≥200 m² open at 10m radius — ≈8m clear footprint)
  - area_5m  >= 70   (consistent open footprint at the inner ring too)
  - d_xz_edge > 2.0  (at least 2m from navmesh edge — boss can move)
  - face_dist > 1.0  (at least 1m from collision face — no wall-clip)
  - NOT in slot_terrain.off_mesh_slots
  - NOT in slot_terrain.metadata.no_navmesh_maps (interior MSBs etc.)
  - NOT a shifting-earth tile (m60_XX_YY_NX where N>=1)

Bonus context: vanilla occupant size — if vanilla source chr is L+ or
the slot is already known to FromSoft as boss-arena-class (in the
existing catalog), it's an even stronger signal.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_shifting_earth_msb(msb_name):
    """m60_XX_YY_NX where N>=1 is a shifting-earth tile.
    m60_XX_YY_0X is always-active overworld."""
    parts = msb_name.replace('.msb', '').split('_')
    if len(parts) < 4: return False
    if parts[0] != 'm60': return False
    suffix = parts[3]
    if len(suffix) == 2 and suffix.isdigit():
        return int(suffix[0]) >= 1
    return False


def load_chr_sizes_from_npcparam():
    """Build c-prefix → median hit dimensions map from NpcParam.csv."""
    npc_path = os.path.join(REPO_ROOT, 'data', 'NpcParam.csv')
    npc = {}
    with open(npc_path, newline='') as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row['ID'])
                npc[nid] = (float(row.get('hitHeight', 0) or 0),
                            float(row.get('hitRadius', 0) or 0))
            except (ValueError, TypeError, KeyError):
                continue
    # Aggregate per c-prefix
    by_cp = {}
    seen_cps = set(nid // 10000 for nid in npc)
    for cp_num in seen_cps:
        base = cp_num * 10000
        heights = [npc[nid][0] for nid in range(base, base+10000)
                   if nid in npc and npc[nid][0] > 0.6]
        radii = [npc[nid][1] for nid in range(base, base+10000)
                 if nid in npc and npc[nid][0] > 0.6]
        if heights:
            cp_key = f'c{cp_num:04d}'
            by_cp[cp_key] = (sorted(heights)[len(heights)//2],
                             sorted(radii)[len(radii)//2])
    return by_cp


def size_bucket(h, r):
    """Same bucketing rules as v0.26.x MMV audit."""
    if h is None: return None
    if h >= 8 or (h >= 6 and r >= 4): return 'GIGA'
    if h >= 5.5 or r >= 3.0: return 'XXL'
    if h >= 3.5 or r >= 2.0: return 'XL'
    if h >= 2.5: return 'L'
    if h >= 1.5: return 'M'
    if h >= 0.8: return 'S'
    return 'XS'


def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--slope-max', type=float, default=10.0,
        help='Max slope in degrees (default %(default)s)')
    p.add_argument('--area-10m-min', type=float, default=200.0,
        help='Min open area at 10m radius in m² (default %(default)s)')
    p.add_argument('--area-5m-min', type=float, default=70.0,
        help='Min open area at 5m radius in m² (default %(default)s)')
    p.add_argument('--edge-min', type=float, default=2.0,
        help='Min distance from navmesh edge in m (default %(default)s)')
    p.add_argument('--face-min', type=float, default=1.0,
        help='Min distance from collision face in m (default %(default)s)')
    p.add_argument('--output', default='dev/terrain_arena_candidates.json')
    args = p.parse_args()

    # --- Load inputs ---
    with open(os.path.join(REPO_ROOT, 'data', 'slot_terrain.json')) as f:
        terrain = json.load(f)
    with open(os.path.join(REPO_ROOT, 'data', 'nr_boss_slots.json')) as f:
        boss_catalog = json.load(f)
    with open(os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')) as f:
        tags_nr = json.load(f)
    with open(os.path.join(REPO_ROOT, 'data', 'mmv_imports.json')) as f:
        tags_mmv = json.load(f)['tags']
    tags = {**tags_nr, **tags_mmv}

    npc_sizes = load_chr_sizes_from_npcparam()

    # --- Build the catalog-known set of slot keys (msb, pi) ---
    catalog_known = set()
    for msb_key, msb_slots in boss_catalog.items():
        if msb_key == '_meta': continue
        # nr_boss_slots.json: each MSB maps directly to a list of slot
        # dicts with 'pi', 'cp', 'name', 'tier' etc.
        if not isinstance(msb_slots, list): continue
        for s in msb_slots:
            pi = s.get('pi')
            if pi is not None:
                catalog_known.add((msb_key, int(pi)))

    no_navmesh_maps = set(terrain['metadata'].get('no_navmesh_maps', []))
    off_mesh_slots = terrain.get('off_mesh_slots', {})

    # --- Enumerate vanilla occupants from nr_all_slots.json ---
    # Each entry: {'map': 'mXX_YY_ZZ_NN.msb', 'c_prefix': 'cXXXX', 'part_index': N}
    occupant_by_slot = {}
    slots_file = os.path.join(REPO_ROOT, 'data', 'nr_all_slots.json')
    if os.path.isfile(slots_file):
        with open(slots_file) as f:
            all_slots = json.load(f)
        for entry in all_slots:
            msb = entry.get('map')
            pi = entry.get('part_index')
            cp = entry.get('c_prefix')
            if msb and pi is not None and cp:
                occupant_by_slot[(msb, int(pi))] = cp

    # --- Walk slot_roughness, apply criteria ---
    candidates = []
    stats = Counter()
    slot_roughness = terrain.get('slot_roughness', {})

    for msb_name, slots in slot_roughness.items():
        if msb_name in no_navmesh_maps:
            stats['skip_interior'] += len(slots) if isinstance(slots, dict) else 0
            continue
        if is_shifting_earth_msb(msb_name):
            stats['skip_shifting_earth'] += len(slots) if isinstance(slots, dict) else 0
            continue
        if not isinstance(slots, dict): continue
        msb_off_mesh = off_mesh_slots.get(msb_name, {})
        for pi_str, metrics in slots.items():
            try:
                pi = int(pi_str)
            except ValueError:
                continue
            stats['total_considered'] += 1

            if pi_str in msb_off_mesh:
                stats['fail_off_mesh'] += 1
                continue

            slope = metrics.get('slope_deg')
            area_10m = metrics.get('area_10m')
            area_5m = metrics.get('area_5m')
            d_edge = metrics.get('d_xz_edge')
            face_dist = metrics.get('face_dist')

            # Some slots have incomplete metrics (e.g. m31_90 pi=5 has
            # no n10/n20/s_xz fields, just the high-level area/edge data).
            # Treat missing fields as failing the filter for that field.
            if slope is None or slope > args.slope_max:
                stats['fail_slope'] += 1
                continue
            if area_10m is None or area_10m < args.area_10m_min:
                stats['fail_area_10m'] += 1
                continue
            if area_5m is None or area_5m < args.area_5m_min:
                stats['fail_area_5m'] += 1
                continue
            if d_edge is None or d_edge < args.edge_min:
                stats['fail_d_edge'] += 1
                continue
            if face_dist is None or face_dist < args.face_min:
                stats['fail_face_dist'] += 1
                continue

            stats['pass'] += 1

            already_catalogued = (msb_name, pi) in catalog_known
            occupant_cp = occupant_by_slot.get((msb_name, pi))
            occupant_tag = tags.get(occupant_cp, {}) if occupant_cp else {}
            occupant_size = occupant_tag.get('size_class')
            npc_sz = None
            if occupant_cp and occupant_cp in npc_sizes:
                h, r = npc_sizes[occupant_cp]
                npc_sz = (h, r, size_bucket(h, r))

            candidate = {
                'msb': msb_name,
                'pi': pi,
                'slope_deg': round(slope, 2),
                'area_5m': round(area_5m, 1),
                'area_10m': round(area_10m, 1),
                'd_xz_edge': round(d_edge, 2),
                'face_dist': round(face_dist, 2),
                'leaf_xz': round(metrics.get('leaf_xz', 0), 1),
                'leaf_y': round(metrics.get('leaf_y', 0), 1),
                'border_edge_dist': metrics.get('border_edge_dist'),
                'already_catalogued': already_catalogued,
                'vanilla_occupant_cp': occupant_cp,
                'vanilla_occupant_name': occupant_tag.get('name'),
                'vanilla_occupant_size_tag': occupant_size,
                'vanilla_occupant_size_npcparam': (
                    f'{npc_sz[2]} (h={npc_sz[0]:.2f}, r={npc_sz[1]:.2f})'
                    if npc_sz else None),
            }
            candidates.append(candidate)

    # --- Report ---
    new_cands = [c for c in candidates if not c['already_catalogued']]
    new_with_big_occupant = [c for c in new_cands
        if c['vanilla_occupant_size_tag'] in ('L', 'XL', 'XXL', 'GIGA')]
    print(f"\n=== Terrain arena audit ===")
    print(f"Filters: slope<{args.slope_max}°, area_10m>={args.area_10m_min}, "
          f"area_5m>={args.area_5m_min}, d_edge>{args.edge_min}, "
          f"face_dist>{args.face_min}")
    print()
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    print()
    print(f"Total slots passing terrain filters: {len(candidates)}")
    print(f"  Already in boss-arena catalog:    {len(candidates) - len(new_cands)}")
    print(f"  NEW arena candidates:              {len(new_cands)}")
    print(f"  ...of which vanilla occupant is L+ size: {len(new_with_big_occupant)}")

    # Per-MSB breakdown of new candidates
    print(f"\n=== NEW candidates by MSB (top 15) ===")
    by_msb = Counter(c['msb'] for c in new_cands)
    for msb, count in by_msb.most_common(15):
        # And of those, how many have L+ occupant?
        big = sum(1 for c in new_cands
                  if c['msb'] == msb and c['vanilla_occupant_size_tag']
                                       in ('L', 'XL', 'XXL', 'GIGA'))
        print(f"  {msb}: {count} new, {big} with L+ occupant")

    # Sample of high-confidence candidates
    print(f"\n=== High-confidence NEW candidates (L+ occupant, top 12) ===")
    new_with_big_occupant.sort(key=lambda c: (-c['area_10m'], c['slope_deg']))
    for c in new_with_big_occupant[:12]:
        occ = c['vanilla_occupant_name'] or c['vanilla_occupant_cp'] or '?'
        sz = c['vanilla_occupant_size_tag'] or '?'
        print(f"  {c['msb']:30s} pi={c['pi']:>3d}  "
              f"slope={c['slope_deg']:>5.1f}°  area10m={c['area_10m']:>6.1f}  "
              f"occ={occ[:24]:24s} ({sz})")

    # --- Write output ---
    out_path = os.path.join(REPO_ROOT, args.output)
    out = {
        '_meta': {
            'generator': 'dev/audit_terrain_arena_candidates.py',
            'criteria': {
                'slope_max_deg': args.slope_max,
                'area_10m_min': args.area_10m_min,
                'area_5m_min': args.area_5m_min,
                'edge_min': args.edge_min,
                'face_min': args.face_min,
            },
            'totals': {
                'passing': len(candidates),
                'new_candidates': len(new_cands),
                'new_with_big_occupant': len(new_with_big_occupant),
            },
            'description': (
                'Slots passing big-and-flat terrain criteria, sorted by '
                'area_10m descending. "already_catalogued" indicates the '
                'slot is in nr_boss_slots.json already; "new" candidates '
                'are unsurfaced. high-confidence candidates have L+ '
                'vanilla occupant — geometry pre-vetted by FromSoft.'),
        },
        'candidates': sorted(candidates,
            key=lambda c: (c['already_catalogued'], -c['area_10m'])),
    }
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {out_path} ({len(candidates)} candidates)")


if __name__ == '__main__':
    main()
