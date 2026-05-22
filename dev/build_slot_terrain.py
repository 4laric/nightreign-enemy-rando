#!/usr/bin/env python3
"""build_slot_terrain.py — Pre-compute per-slot navmesh-derived terrain data.

Walks all enemy slots in a spoiler, classifies each against the navmesh
AABBs in the corresponding map's .hkx files. Produces slot_terrain.json
which is permanent data (positions don't change per seed).

Two pieces of derived data:

  off_mesh_slots — original v0.19 binary classification (on-mesh / off-mesh
                   / proximity-off-mesh / force-off-mesh / no_match), used
                   by T2.6-style soft restriction in pick_target_cp.

  slot_roughness — v0.22 per-slot AABB-derived roughness signals for T2.8.
                   Only stored for slots that have a containing leaf (others
                   are typically off-mesh and handled elsewhere). Populated
                   for every map outside FORCE_OFF_MESH_MAPS.

v0.22: Reads .nvmhktbnd binders directly via bnd4.py (no Yabber/WitchyBND
unpack required). Falls back to the legacy m*-nvmhktbnd-dcx/ unpacked-
directory layout if the binder isn't present, for compat with existing
workflows.

v0.19.8: Force-off-mesh map list. Cathedral / Mountaintop interiors have
navmesh that covers the whole building's footprint as a single AABB,
but the actual walkable area is fragmented around columns, altars,
steps, etc. The BVH classification can't see this fine geometric
detail. v0.19.7 playtest confirmed: 168 of 168 placements in
m32_00, m32_20, m38_10 (cathedral maps) classified as on_mesh by AABB
were actually broken (frozen Rats). All slots in these maps are now
categorically force-marked as off_mesh.

v0.19.7: proximity expansion. After AABB-based classification, optionally
promote on_mesh slots within K units of an off_mesh slot to off_mesh.
Captures the "rocky neighborhood" case where the BVH happens to have a
tight leaf at the slot but the surrounding terrain is bumpy.

Usage:
    # Default: extent=50, proximity=10, force-off-mesh maps applied
    python build_slot_terrain.py \\
        --spoiler /path/to/spoiler.json \\
        --hkx-root /path/to/nightreign_navmesh \\
        --out slot_terrain.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hkx_aabb_check import (
    msb_to_navmesh_dir,
    collect_navmesh_aabbs_for_map,
    collect_navmesh_aabbs_from_bnd,
    classify_slot,
    slot_roughness,
)


# v0.19.8/.9: Maps where ALL slots are categorically off_mesh, regardless of
# what the BVH says. These are interior environments (cathedrals, mountaintop
# arenas, tunnels, dungeons, large castles) where the navmesh covers a
# whole-building bounding region but the actual walkable surface is fragmented
# around columns, altars, steps, etc. The AABB approach can't distinguish
# "inside the building's bounding box" from "on a walkable floor tile".
#
# Categories confirmed via terrain test playtest:
#   - Cathedrals (v0.19.8): 168/168 slots in m32_00, m32_20, m38_10 frozen
#   - Mountaintop / subterranean (v0.19.8): m32_10 partial, m38_00 partial
#   - Tunnels (v0.19.9): m20_xx connector maps; m20_10 had 9/9 frozen
#   - Large castle interiors (v0.19.9): m15_00 (52 slots, 0% jelly classification)
#   - Underground dungeons (v0.19.9): m30_00, m30_30 (large dungeon footprints)
#
# Same set as oops_v3.py V3_FRAGILE_MAPS — kept in sync manually since
# importing oops_v3 in this script would cause circular dep.
FORCE_OFF_MESH_MAPS = {
    # Cathedrals + mountaintop / subterranean (v0.19.8)
    'm38_00_00_00.msb',  # Cathedral of the Forsaken Dead
    'm38_10_00_00.msb',  # Cathedral
    'm32_00_00_00.msb',  # Subterranean / Mountaintop interior
    'm32_10_00_00.msb',  # Mountaintop
    'm32_20_00_00.msb',  # Subterranean / Cathedral
    # Castle interior (v0.19.9)
    'm15_00_00_00.msb',  # Stormveil-equivalent castle (52 slots, c3661 dominant)
    # Tunnels — m20_xx series (v0.19.9)
    'm20_00_00_00.msb', 'm20_10_00_00.msb', 'm20_20_00_00.msb',
    'm20_30_00_00.msb', 'm20_40_00_00.msb', 'm20_50_00_00.msb',
    'm20_60_00_00.msb', 'm20_70_00_00.msb', 'm20_80_00_00.msb',
    'm20_90_00_00.msb',
    # More tunnels — m21_xx series
    'm21_00_00_00.msb', 'm21_10_00_00.msb', 'm21_20_00_00.msb',
    'm21_30_00_00.msb', 'm21_40_00_00.msb', 'm21_50_00_00.msb',
}


def dist3(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2) ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spoiler', required=True,
                    help='Spoiler JSON with all slot positions (any seed works)')
    ap.add_argument('--hkx-root', required=True,
                    help='Root dir containing m*-nvmhktbnd-dcx/ subdirs')
    ap.add_argument('--out', required=True, help='Output JSON path')
    ap.add_argument('--tight-extent', type=float, default=50.0,
                    help='AABB extent threshold for off-mesh (default 50)')
    ap.add_argument('--proximity-expand', type=float, default=10.0,
                    help='Promote on_mesh slots within N units of any off_mesh '
                         'slot to off_mesh. Set 0 to disable. Default 10.')
    ap.add_argument('--no-force-off-mesh', action='store_true',
                    help='Disable categorical force-off-mesh for cathedral maps')
    args = ap.parse_args()

    print(f'Loading spoiler: {args.spoiler}')
    with open(args.spoiler) as f:
        sp = json.load(f)

    by_map = defaultdict(list)
    for e in sp['entries']:
        if not e.get('position'): continue
        by_map[e['map']].append(e)

    print(f'Building terrain classification for {len(by_map)} maps...')
    print(f'  AABB extent threshold: {args.tight_extent}')
    print(f'  Proximity expansion:   {args.proximity_expand} units '
          f'({"disabled" if args.proximity_expand <= 0 else "enabled"})')
    if not args.no_force_off_mesh:
        print(f'  Force off_mesh maps:   {sorted(FORCE_OFF_MESH_MAPS)}')
    print()

    on_mesh = 0
    off_mesh = 0
    proximity_flagged = 0
    force_flagged = 0
    no_match = 0
    no_navmesh_data = 0
    no_navmesh_maps = []
    off_mesh_by_map = defaultdict(dict)
    # v0.22: per-slot roughness, only for slots with a containing leaf
    roughness_by_map = defaultdict(dict)

    use_force = not args.no_force_off_mesh

    for i, (msb, entries) in enumerate(sorted(by_map.items())):
        # Force-off-mesh check: bypass AABB entirely for cathedral/mountaintop maps
        if use_force and msb in FORCE_OFF_MESH_MAPS:
            for e in entries:
                force_flagged += 1
                pos = e['position']
                off_mesh_by_map[msb][str(e['part_index'])] = {
                    'pos': [round(p, 2) for p in pos],
                    'extent': 'forced',
                    'src': e['original']['c_prefix'],
                    'status': 'force_off_mesh',
                }
            continue

        # v0.22: Try .nvmhktbnd direct first; fall back to unpacked dir for
        # legacy compat. This means the same script works on a fresh dump of
        # binders OR on a workflow where Yabber/WitchyBND has already unpacked
        # them to per-map directories.
        bnd_path = os.path.join(args.hkx_root, msb.replace('.msb', '') + '.nvmhktbnd')
        if os.path.isfile(bnd_path):
            aabbs = collect_navmesh_aabbs_from_bnd(bnd_path)
        else:
            nav_dir_name = msb_to_navmesh_dir(msb)
            nav_dir = os.path.join(args.hkx_root, nav_dir_name)
            aabbs = collect_navmesh_aabbs_for_map(nav_dir) if os.path.isdir(nav_dir) else []
        if not aabbs:
            no_navmesh_data += len(entries)
            no_navmesh_maps.append(msb)
            continue

        # Pass 1: AABB-based classification per slot
        per_slot = []  # (entry, status, extent)
        for e in entries:
            status, extent = classify_slot(aabbs, e['position'], args.tight_extent)
            per_slot.append((e, status, extent))

        # Pass 2: proximity expansion
        if args.proximity_expand > 0:
            off_positions = [s[0]['position'] for s in per_slot
                             if s[1] in ('off_mesh', 'no_match')]
            if off_positions:
                for idx, (e, status, extent) in enumerate(per_slot):
                    if status != 'on_mesh': continue
                    nearest = min(dist3(e['position'], op) for op in off_positions)
                    if nearest < args.proximity_expand:
                        per_slot[idx] = (e, 'proximity_off_mesh', nearest)

        # Pass 3 (v0.22): per-slot roughness for T2.8. Compute for every slot
        # in this map regardless of on/off-mesh status — the runtime decides
        # which to apply T2.8 to. Only emit entries that actually have a
        # containing leaf; otherwise s_y is None and T2.8 wouldn't fire anyway.
        for e in entries:
            r = slot_roughness(aabbs, e['position'])
            if r['s_y'] is not None:
                roughness_by_map[msb][str(e['part_index'])] = {
                    's_y':  round(r['s_y'], 2),
                    's_xz': round(r['s_xz'], 1),
                    'n10':  r['n10'],
                    'n20':  r['n20'],
                }

        # Aggregate
        for e, status, extent in per_slot:
            if status == 'on_mesh':
                on_mesh += 1
                continue
            if status == 'off_mesh':       off_mesh += 1
            elif status == 'no_match':     no_match += 1
            elif status == 'proximity_off_mesh': proximity_flagged += 1
            pos = e['position']
            off_mesh_by_map[msb][str(e['part_index'])] = {
                'pos': [round(p, 2) for p in pos],
                'extent': round(extent, 1) if extent != float('inf') else 'inf',
                'src': e['original']['c_prefix'],
                'status': status,
            }

        if (i + 1) % 20 == 0:
            print(f'  Processed {i+1}/{len(by_map)} maps...')

    # v0.22: roughness summary
    rough_total = sum(len(v) for v in roughness_by_map.values())
    print(f'\nslot_roughness entries: {rough_total} (across {len(roughness_by_map)} maps)')

    out = {
        'metadata': {
            'navmesh_root': os.path.abspath(args.hkx_root),
            'tight_extent': args.tight_extent,
            'proximity_expand': args.proximity_expand,
            'force_off_mesh_maps': sorted(FORCE_OFF_MESH_MAPS) if use_force else [],
            'total_slots': on_mesh + off_mesh + proximity_flagged + force_flagged + no_match + no_navmesh_data,
            'on_mesh': on_mesh,
            'off_mesh': off_mesh,
            'proximity_off_mesh': proximity_flagged,
            'force_off_mesh': force_flagged,
            'no_match': no_match,
            'no_navmesh_data': no_navmesh_data,
            'roughness_entries': rough_total,
        },
        'no_navmesh_maps': sorted(set(no_navmesh_maps)),
        'off_mesh_slots': dict(off_mesh_by_map),
        'slot_roughness': dict(roughness_by_map),
    }
    with open(args.out, 'w') as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(f'\n=== Wrote {args.out} ===')
    print(f'  on_mesh:            {on_mesh}')
    print(f'  off_mesh:           {off_mesh}    (extent >= {args.tight_extent})')
    print(f'  proximity_off_mesh: {proximity_flagged}    '
          f'(within {args.proximity_expand}u of off_mesh)')
    print(f'  force_off_mesh:     {force_flagged}    '
          f'(in cathedral/mountaintop maps)')
    print(f'  no_match:           {no_match}')
    print(f'  no_navmesh_data:    {no_navmesh_data}')
    print(f'  roughness entries:  {rough_total}    (T2.8 candidate pool)')


if __name__ == '__main__':
    main()


