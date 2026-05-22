#!/usr/bin/env python3
"""hkx_aabb_check.py — World-space AABB extraction from Havok hkaiNavMesh files.

Path A breakthrough (2026-05-04): inside each .hkx file, the BVH-like
spatial structure stores per-leaf AABBs in WORLD COORDINATES. A slot
contained by a tight leaf AABB (extent < ~50 units in all dims) is on
the navmesh. A slot contained by ONLY large internal BVH nodes (extent
> 100 units) is off-mesh / dead terrain.

Empirical result on m60_44_38_30 oops-all-Rat (seed 309746):
  - 5 of 5 broken Rat slots: only matched root-level AABBs (extent > 130)
  - 23 of 23 working Rat slots: matched a leaf AABB with extent < 35

Crucially: AABBs are in WORLD coordinates, no tile transform required.
.nva manifests are NOT needed for this approach.

Usage:
    python hkx_aabb_check.py \\
        --spoiler /path/to/_spoilers.json \\
        --hkx-root /path/to/nightreign_navmesh \\
        --tight-extent 50.0
"""

import argparse
import json
import os
import struct
import sys
from collections import defaultdict


# Map from spoiler msb name to navmesh directory name.
# spoiler 'm60_44_38_30.msb' -> directory 'm60_44_38_30-nvmhktbnd-dcx'
def msb_to_navmesh_dir(msb_name):
    base = msb_name.replace('.msb', '').replace('_00_00.msb', '')
    return f'{base}-nvmhktbnd-dcx'


def extract_aabbs_from_bytes(raw, world_extent_max=600.0):
    """v0.22: bytes-input core of the AABB extractor. Operates on the raw
    payload of an .hkx file (the existing path-based variant simply reads
    the file then delegates here)."""
    if len(raw) < 8 or raw[4:8] != b'TAG0':
        return []

    # Locate DATA section bounds
    data_off = raw.find(b'DATA')
    if data_off < 0:
        return []
    data_size = struct.unpack('>I', raw[data_off-4:data_off])[0] & 0x3FFFFFFF
    data_start = data_off + 4   # after 'DATA' magic
    data_end = data_off + data_size

    aabbs = []
    # Scan with 4-byte alignment (could be 16-byte aligned in practice; 4 is safer)
    for off in range(data_start, data_end - 32, 4):
        a, b, c, _w0, x, y, z, _w1 = struct.unpack_from('<8f', raw, off)
        # Spatial sanity
        if not all(-world_extent_max < f < world_extent_max for f in (a, b, c, x, y, z)):
            continue
        # Must be a proper AABB (min<max in all axes)
        if not (a < x and b < y and c < z):
            continue
        # Discard near-zero extent (single points, not AABBs)
        ex = x - a; ey = y - b; ez = z - c
        if ex < 0.5 or ez < 0.5:
            continue
        # Discard absurdly large (likely false positive from random floats)
        if ex > world_extent_max or ez > world_extent_max:
            continue
        aabbs.append((a, b, c, x, y, z))
    return aabbs


def extract_aabbs_from_hkx(path, world_extent_max=600.0):
    """Scan a Havok TAG0 .hkx file for AABBs in its DATA section.
    Returns list of (min_x, min_y, min_z, max_x, max_y, max_z) tuples.

    Strategy: AABBs are stored as 32-byte structs (Vec4 min, Vec4 max with
    padding). We find them by scanning for 8-float patterns where:
      - All 6 spatial values in [-world_extent_max, world_extent_max]
      - min < max in all three axes
      - Extent is plausible (>0 in each axis)

    This catches both the root navmesh AABB and the per-leaf BVH AABBs.
    Some false positives possible from coincidental float patterns, but
    they're rare and tend to be wildly out of plausible range.
    """
    with open(path, 'rb') as f:
        raw = f.read()
    return extract_aabbs_from_bytes(raw, world_extent_max=world_extent_max)


def collect_navmesh_aabbs_for_map(navmesh_dir):
    """Collect all AABBs from all n_*.hkx files in a navmesh directory."""
    aabbs = []
    if not os.path.isdir(navmesh_dir):
        return aabbs
    for fname in sorted(os.listdir(navmesh_dir)):
        # Only the n_ (navmesh) files; skip o_ (auxiliary) and q_ (query mediator)
        if not fname.startswith('n') or not fname.endswith('.hkx'):
            continue
        path = os.path.join(navmesh_dir, fname)
        aabbs.extend(extract_aabbs_from_hkx(path))
    return aabbs


def collect_navmesh_aabbs_from_bnd(bnd_path):
    """v0.22: Collect navmesh AABBs from a .nvmhktbnd binder directly,
    no Yabber/WitchyBND unpack required. Pure-Python, runs on any OS.
    Returns the same shape as collect_navmesh_aabbs_for_map().
    Returns [] for placeholder (96-byte) binders or missing files."""
    from bnd4 import read_bnd4
    if not os.path.isfile(bnd_path):
        return []
    aabbs = []
    for name, payload in read_bnd4(bnd_path):
        if name.startswith('n') and name.endswith('.hkx'):
            aabbs.extend(extract_aabbs_from_bytes(payload))
    return aabbs


def slot_roughness(aabbs, position, leaf_max_extent=50.0):
    """v0.22: AABB-derived per-slot roughness signals for T2.8 evaluation.

    Returns dict with keys:
      s_y      — y-extent of the smallest containing leaf AABB. Strong
                 slope-and-cliff proxy: flat ground gives near-zero y-extent
                 because horizontal polygons are thin in y; steep slopes and
                 cliff faces give large y-extent. None if no containing leaf.
      s_xz     — xz-area of the smallest containing leaf AABB. Big = wide
                 plateau quad (safe). Small = tight detail patch (suspect).
                 None if no containing leaf.
      n10      — count of leaf AABBs with min(extent)<leaf_max_extent within
                 10u xz of the position. Local subdivision density.
      n20      — same at 20u xz radius. Broader neighborhood density.

    Calibration (v0.22, m60_xx maps, 442 coarse-fragile vs 1545 safe slots):
        s_y separates the populations by roughly 5x at the median (fragile
        ~14, safe ~3). s_xz / n10 / n20 show heavy distribution overlap and
        contribute little extra signal — kept here for forensics but not
        used in the default scoring rule.

    Slope from polygon normals would be more direct, but parsing Havok
    polygon data is materially harder than the AABB scan and the AABB
    y-extent already encodes the same physical signal (a face with a
    non-horizontal normal has a y-extent proportional to slope * xz-size).
    """
    px, py, pz = position
    contained = [a for a in aabbs
                 if a[0] <= px <= a[3] and a[1] <= py <= a[4] and a[2] <= pz <= a[5]]
    cont_leaves = [a for a in contained
                   if min(a[3]-a[0], a[4]-a[1], a[5]-a[2]) < leaf_max_extent]

    smallest = None
    if cont_leaves:
        smallest = min(cont_leaves,
                       key=lambda a: min(a[3]-a[0], a[4]-a[1], a[5]-a[2]))

    leaves = [a for a in aabbs
              if min(a[3]-a[0], a[4]-a[1], a[5]-a[2]) < leaf_max_extent]

    def xz_dist(a):
        cx = max(a[0], min(px, a[3]))
        cz = max(a[2], min(pz, a[5]))
        return ((cx - px)**2 + (cz - pz)**2) ** 0.5

    n10 = sum(1 for a in leaves if xz_dist(a) < 10.0)
    n20 = sum(1 for a in leaves if xz_dist(a) < 20.0)

    if smallest:
        s_y  = smallest[4] - smallest[1]
        s_xz = (smallest[3] - smallest[0]) * (smallest[5] - smallest[2])
    else:
        s_y, s_xz = None, None

    return {'s_y': s_y, 's_xz': s_xz, 'n10': n10, 'n20': n20}


def aabb_extent(box):
    a, b, c, x, y, z = box
    return (x - a, y - b, z - c)


def aabb_contains(box, point):
    a, b, c, x, y, z = box
    return a <= point[0] <= x and b <= point[1] <= y and c <= point[2] <= z


def classify_slot(aabbs, position, tight_extent=50.0):
    """For a slot, find all AABBs containing it. Return (status, smallest_extent).

    status:
      'on_mesh'    — at least one tight leaf AABB contains the slot
      'off_mesh'   — only large BVH internal nodes contain the slot
      'no_match'   — no AABB contains the slot (off-cell)
    """
    matches = [aabb for aabb in aabbs if aabb_contains(aabb, position)]
    if not matches:
        return 'no_match', float('inf')
    # Smallest min-extent across all axes
    best_extent = min(min(aabb_extent(m)) for m in matches)
    if best_extent < tight_extent:
        return 'on_mesh', best_extent
    return 'off_mesh', best_extent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spoiler', required=True,
                    help='Path to _spoilers.json from a playtest seed')
    ap.add_argument('--hkx-root', required=True,
                    help='Root directory containing m*-nvmhktbnd-dcx/ subdirs')
    ap.add_argument('--tight-extent', type=float, default=50.0,
                    help='Max AABB extent (any axis) to consider a "leaf" (default: 50)')
    ap.add_argument('--target-c-prefix', default=None,
                    help='Filter to only this target c-prefix')
    ap.add_argument('--map-filter', default=None,
                    help='Process only this map (e.g. m60_44_38_30)')
    args = ap.parse_args()

    print(f'Loading spoiler: {args.spoiler}')
    with open(args.spoiler) as f:
        sp = json.load(f)

    # Group spoiler entries by map
    by_map = defaultdict(list)
    for e in sp['entries']:
        if not e.get('position'):
            continue
        if args.target_c_prefix and e['new']['c_prefix'] != args.target_c_prefix:
            continue
        msb = e['map']
        if args.map_filter and msb.replace('.msb', '') != args.map_filter:
            continue
        by_map[msb].append(e)

    print(f'Processing {len(by_map)} maps with placement data')

    flagged = []
    on_mesh_count = 0
    off_mesh_count = 0
    no_match_count = 0
    no_navmesh_count = 0
    no_navmesh_maps = []

    for msb, entries in sorted(by_map.items()):
        nav_dir_name = msb_to_navmesh_dir(msb)
        nav_dir = os.path.join(args.hkx_root, nav_dir_name)
        if not os.path.isdir(nav_dir):
            no_navmesh_count += len(entries)
            no_navmesh_maps.append(msb)
            continue
        aabbs = collect_navmesh_aabbs_for_map(nav_dir)
        if not aabbs:
            no_navmesh_count += len(entries)
            no_navmesh_maps.append(msb)
            continue
        for e in entries:
            status, extent = classify_slot(aabbs, e['position'], args.tight_extent)
            if status == 'on_mesh':
                on_mesh_count += 1
            elif status == 'off_mesh':
                off_mesh_count += 1
                flagged.append((msb, e, extent, 'off_mesh'))
            else:
                no_match_count += 1
                flagged.append((msb, e, extent, 'no_match'))

    print(f'\nTotal: on_mesh={on_mesh_count}  off_mesh={off_mesh_count}  '
          f'no_match={no_match_count}  no_navmesh_data={no_navmesh_count}')
    if no_navmesh_maps:
        print(f'Maps without navmesh data ({len(no_navmesh_maps)}): '
              f'{", ".join(set(no_navmesh_maps[:5]))}{"..." if len(no_navmesh_maps)>5 else ""}')

    if flagged:
        flagged.sort(key=lambda r: -r[2])  # largest extent first
        print(f'\n=== {len(flagged)} flagged slots (off-mesh or no-match) ===')
        print(f'{"map":<22} {"pi":<5} {"pos":<32} {"src":<8} {"target":<8} {"status":<10} {"extent":>8}')
        for msb, e, extent, status in flagged[:80]:
            pos = e['position']
            pos_str = f'({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f})'
            ext_str = f'{extent:.0f}' if extent != float("inf") else 'inf'
            print(f'  {msb:<22} {e["part_index"]:<5} {pos_str:<32} {e["original"]["c_prefix"]:<8} '
                  f'{e["new"]["c_prefix"]:<8} {status:<10} {ext_str:>8}')

        # V3_PROBLEM_SLOTS suggestions
        print('\n# Suggested V3_PROBLEM_SLOTS additions (paste-ready):')
        print('V3_PROBLEM_SLOTS_FROM_AABB = {')
        for msb, e, extent, status in flagged[:50]:
            ext_str = f'{extent:.0f}' if extent != float("inf") else 'inf'
            print(f"    ({msb!r}, {e['part_index']}): "
                  f"'{status} (extent={ext_str}) | was {e['original']['c_prefix']}',")
        print('}')


if __name__ == '__main__':
    main()
