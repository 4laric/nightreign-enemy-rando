#!/usr/bin/env python3
"""build_slot_repositions.py — Propose on-navmesh relocations for off-mesh slots.

Read-only diagnostic. For every off_mesh / proximity_off_mesh slot in
slot_terrain.json, find the nearest tight navmesh leaf in the same map's
.nvmhktbnd and propose a relocated position. Records displacement, target
leaf size, and a confidence label. Does NOT modify any MSBs — the output
JSON is input data for a separate (future) repositioning pipeline step.

EMPIRICAL FOUNDATION:
hkx_aabb_check.py established that tight leaves (max-xz-extent < 50u) are
walkable navmesh polygons in world space. Slots inside a tight leaf path
correctly; slots only inside coarse internal BVH nodes don't path. If we
move a slot's position from outside any tight leaf to the center of the
nearest tight leaf, the slot becomes walkable — that's the substitution
this tool proposes.

WHAT GETS RELOCATED:
- off_mesh: BVH classified the slot's vanilla position as outside any
  tight leaf in a map that has navmesh data. Relocatable.
- proximity_off_mesh: classified on_mesh by AABB but within K units of an
  off_mesh slot (v0.19.7 proximity rule). Less broken than off_mesh but
  still soft-restricted; relocating to the actual nearest leaf is a small
  correction that may help.
- force_off_mesh: SKIPPED. These slots are in maps with no navmesh data
  at all (hub/cathedral interiors). Can't relocate to navmesh that
  doesn't exist.
- no_match: SKIPPED for now. Position-vs-navmesh mismatch is a different
  failure mode (scripted spawn positions etc.) and needs more thought.

TARGET POSITION CHOICE:
For each relocation we record both:
  - leaf_center: ( (min+max)/2 for each axis ) — natural midpoint
  - leaf_floor:  ( center_x, min_y, center_z ) — Y at the AABB floor
Empirical testing should pick which works better; for narrow leaves the
two are within ~5u of each other and either is probably fine.

CONFIDENCE LABELS:
  - 'tight'    leaf_extent <= 10u — high confidence walkable
  - 'medium'   10 < leaf_extent <= 30u — medium confidence
  - 'loose'    30 < leaf_extent <= 50u — borderline tight; risk of slanted poly
  - 'far'      displacement > 30u — gameplay-visible move; review case-by-case

Usage:
    python build_slot_repositions.py \\
        --slot-terrain data/slot_terrain.json \\
        --nm-dir /path/to/nightreign_navmesh/ \\
        --out data/slot_repositions.json

Output: slot_repositions.json + a summary report to stdout.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hkx_aabb_check import collect_navmesh_aabbs_from_bnd


# A "tight leaf" is a BVH AABB with max-xz-extent below this threshold.
# Matches hkx_aabb_check.py's classify_slot default. Empirically the
# distribution is bimodal — most leaves are <10u (real polygons) and BVH
# internal nodes are >100u (containers). 50 is a safe cutoff between them.
TIGHT_LEAF_MAX_EXTENT = 50.0

# Statuses we attempt to relocate. Other statuses (force_off_mesh, no_match)
# can't or shouldn't be moved by this tool — see module docstring.
RELOCATABLE_STATUSES = {'off_mesh', 'proximity_off_mesh'}

# Flier c-prefixes are excluded from relocation. They're placed off the
# navmesh intentionally — bats perch on cliff faces, dragons hover above
# their arena floor, etc. Relocating them onto the navmesh would visually
# break the encounter (a dragon standing on the dirt instead of flying).
# Built from nr_enemy_tags.json: anything with locomotion=2 (the explicit
# flier flag) or anim_class='flying_dragon'. Computed once at import time
# from the tags file via _build_flier_exclusion(). c-prefixes not in tags
# are not excluded.
_FLIER_PREFIXES_CACHE = None


def _build_flier_exclusion(tags):
    """Return the set of c-prefixes that should not be relocated."""
    fliers = set()
    for cp, t in tags.items():
        if t.get('locomotion') == 2:
            fliers.add(cp)
        elif t.get('anim_class') == 'flying_dragon':
            fliers.add(cp)
    return fliers

# Slots within this distance (in any axis-aligned 3D sense) of each other
# in their vanilla positions are treated as a coordinated cluster — they're
# almost certainly placed at the same gameplay encounter (a campfire, an
# encampment, a noble-team squad, etc.). The naive nearest-leaf relocation
# can split such clusters by sending different members to different leaves,
# even when the leaves are 20+ units apart. The future MSB-surgery step
# should preserve cluster cohesion; this constant defines the cluster
# detection threshold. Tuned empirically to ~8u: noble pi=23-26 at the
# dog-spider tile span ~5u, soldier pi=28/31/32 span ~10u, both real
# clusters.
CLUSTER_THRESHOLD = 8.0


def d3(a, b):
    return ((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5


def msb_to_navmesh_filename(msb_name):
    """m60_43_39_00.msb -> m60_43_39_00.nvmhktbnd"""
    return msb_name.replace('_00.msb', '_00.nvmhktbnd').replace('.msb', '.nvmhktbnd')


def confidence_label(displacement, leaf_extent):
    """Categorize a proposed relocation by how risky it looks."""
    if displacement > 30.0:
        return 'far'
    if leaf_extent <= 10.0:
        return 'tight'
    if leaf_extent <= 30.0:
        return 'medium'
    return 'loose'


def _find_clusters(off_mesh_slots):
    """Group off-mesh slots whose vanilla positions are within CLUSTER_THRESHOLD.

    Single-link clustering: any pair within threshold links into a group.
    Returns {pi_str: cluster_id_or_None}. Singletons get cluster_id=None.
    """
    relocatable_pis = [pi for pi, data in off_mesh_slots.items()
                       if data['status'] in RELOCATABLE_STATUSES]
    positions = {pi: tuple(off_mesh_slots[pi]['pos']) for pi in relocatable_pis}

    cluster_id_of = {pi: None for pi in relocatable_pis}
    next_cluster_id = 0
    visited = set()
    for pi in relocatable_pis:
        if pi in visited:
            continue
        # BFS: build the connected component reachable from pi via
        # CLUSTER_THRESHOLD edges.
        group = [pi]
        frontier = [pi]
        visited.add(pi)
        while frontier:
            new_frontier = []
            for u in frontier:
                up = positions[u]
                for v in relocatable_pis:
                    if v in visited:
                        continue
                    if d3(up, positions[v]) <= CLUSTER_THRESHOLD:
                        group.append(v)
                        new_frontier.append(v)
                        visited.add(v)
            frontier = new_frontier
        if len(group) >= 2:
            for u in group:
                cluster_id_of[u] = next_cluster_id
            next_cluster_id += 1
    return cluster_id_of


def propose_relocations_for_map(off_mesh_slots, aabbs, flier_prefixes=None):
    """Return {pi: relocation_dict} for one map.

    off_mesh_slots: {pi_str: {pos, status, src, extent}} from slot_terrain.json
    aabbs: list of (min_x, min_y, min_z, max_x, max_y, max_z) tuples
    flier_prefixes: set of c-prefixes to skip (intentionally placed off-mesh).
                    None means don't exclude any (legacy / debug behavior).
    """
    if flier_prefixes is None:
        flier_prefixes = set()
    # Tight leaves are AABBs whose max-xz-extent is below the threshold.
    # That's our pool of candidate walkable polygons.
    tight = [b for b in aabbs
             if max(b[3]-b[0], b[5]-b[2]) <= TIGHT_LEAF_MAX_EXTENT]
    if not tight:
        return {}, 'no_tight_leaves', 0

    # Pre-compute leaf centers and max-xz-extents — used for nearest-neighbor.
    leaf_data = []
    for b in tight:
        cx = (b[0] + b[3]) / 2
        cy = (b[1] + b[4]) / 2
        cz = (b[2] + b[5]) / 2
        ext = max(b[3]-b[0], b[5]-b[2])
        leaf_data.append((b, (cx, cy, cz), ext))

    cluster_id_of = _find_clusters(off_mesh_slots)

    out = {}
    n_skipped_flier = 0
    for pi_str, data in off_mesh_slots.items():
        if data['status'] not in RELOCATABLE_STATUSES:
            continue
        if data['src'] in flier_prefixes:
            n_skipped_flier += 1
            continue
        from_pos = tuple(data['pos'])

        # Find the leaf whose CENTER is nearest to the slot. Could also try
        # nearest leaf surface (clamp to AABB), but center is simpler and
        # the leaves are tight enough that center-distance ~= surface-dist.
        best_leaf, best_center, best_ext = min(
            leaf_data, key=lambda ld: d3(ld[1], from_pos))
        displacement = d3(best_center, from_pos)

        leaf_floor = (best_center[0], best_leaf[1], best_center[2])

        out[pi_str] = {
            'from_pos':     list(from_pos),
            'to_pos_center': [round(x, 3) for x in best_center],
            'to_pos_floor':  [round(x, 3) for x in leaf_floor],
            'displacement':  round(displacement, 2),
            'leaf_extent':   round(best_ext, 2),
            'leaf_aabb':     [round(x, 2) for x in best_leaf],
            'status':        data['status'],
            'src':           data['src'],
            'confidence':    confidence_label(displacement, best_ext),
            'cluster_id':    cluster_id_of[pi_str],
        }

    # Second pass: flag cluster splits. A cluster splits if its members get
    # sent to leaves more than CLUSTER_THRESHOLD apart from each other —
    # that's the failure mode where vanilla-clumped Nobles end up scattered
    # across a 20+ unit gap in the relocated MSB.
    by_cluster = defaultdict(list)
    for pi_str, r in out.items():
        if r['cluster_id'] is not None:
            by_cluster[r['cluster_id']].append((pi_str, r))
    for cid, members in by_cluster.items():
        targets = [tuple(m[1]['to_pos_center']) for m in members]
        max_split = max((d3(a, b) for a in targets for b in targets), default=0.0)
        for pi_str, r in members:
            r['cluster_size'] = len(members)
            r['cluster_split_distance'] = round(max_split, 2)
            r['cluster_split'] = max_split > CLUSTER_THRESHOLD

    return out, None, n_skipped_flier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot-terrain', required=True)
    ap.add_argument('--nm-dir', required=True,
                    help='Directory with .nvmhktbnd files (the navmesh zip unpacked)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--tags', default=None,
                    help='nr_enemy_tags.json for flier exclusion (default: '
                         'auto-detect via oops_v3._data_path)')
    args = ap.parse_args()

    # Load tags to build flier exclusion. Default to importing oops_v3's
    # data path resolver so we don't duplicate that knowledge here.
    if args.tags:
        tags_path = args.tags
    else:
        sys.path.insert(0, os.path.dirname(HERE))
        import oops_v3
        tags_path = oops_v3._data_path('nr_enemy_tags.json')
    tags = json.load(open(tags_path))
    flier_prefixes = _build_flier_exclusion(tags)
    print(f'Flier exclusion: {len(flier_prefixes)} c-prefixes '
          f'(locomotion=2 or anim_class=flying_dragon)')

    st = json.load(open(args.slot_terrain))
    off_mesh_by_map = st['off_mesh_slots']
    print(f'Loaded slot_terrain.json: {len(off_mesh_by_map)} maps with off-mesh slots')

    results = {}
    skipped_maps_no_nm = []
    skipped_maps_stub = []
    skipped_maps_no_leaves = []
    total_flier_skipped = 0

    for msb_name in sorted(off_mesh_by_map):
        nm_path = os.path.join(args.nm_dir, msb_to_navmesh_filename(msb_name))
        if not os.path.exists(nm_path):
            skipped_maps_no_nm.append(msb_name)
            continue
        if os.path.getsize(nm_path) < 1000:
            skipped_maps_stub.append(msb_name)
            continue
        try:
            aabbs = collect_navmesh_aabbs_from_bnd(nm_path)
        except Exception as e:
            print(f'  ERROR parsing {nm_path}: {e}')
            continue

        proposals, err, n_flier = propose_relocations_for_map(
            off_mesh_by_map[msb_name], aabbs, flier_prefixes=flier_prefixes)
        total_flier_skipped += n_flier
        if err == 'no_tight_leaves':
            skipped_maps_no_leaves.append(msb_name)
            continue
        if proposals:
            results[msb_name] = proposals

    # ---- summary report ----
    print()
    print(f'Maps with relocation proposals:       {len(results)}')
    print(f'Maps skipped (no navmesh file):       {len(skipped_maps_no_nm)}')
    print(f'Maps skipped (stub / no-mesh maps):   {len(skipped_maps_stub)}')
    print(f'Maps skipped (no tight leaves found): {len(skipped_maps_no_leaves)}')
    print(f'Slots skipped (flier exclusion):      {total_flier_skipped}')

    total_relocations = sum(len(v) for v in results.values())
    print(f'\nTotal proposed relocations: {total_relocations}')

    # Confidence distribution
    conf_counter = Counter()
    disp_buckets = Counter()
    ext_buckets = Counter()
    status_counter = Counter()
    for msb, slots in results.items():
        for pi, r in slots.items():
            conf_counter[r['confidence']] += 1
            status_counter[r['status']] += 1
            d = r['displacement']
            if   d <= 5:   disp_buckets['00 0-5u'] += 1
            elif d <= 10:  disp_buckets['01 5-10u'] += 1
            elif d <= 15:  disp_buckets['02 10-15u'] += 1
            elif d <= 20:  disp_buckets['03 15-20u'] += 1
            elif d <= 30:  disp_buckets['04 20-30u'] += 1
            elif d <= 50:  disp_buckets['05 30-50u'] += 1
            else:          disp_buckets['06 >50u'] += 1
            e = r['leaf_extent']
            if   e <= 2:   ext_buckets['00 <=2u'] += 1
            elif e <= 5:   ext_buckets['01 2-5u'] += 1
            elif e <= 10:  ext_buckets['02 5-10u'] += 1
            elif e <= 20:  ext_buckets['03 10-20u'] += 1
            elif e <= 30:  ext_buckets['04 20-30u'] += 1
            else:          ext_buckets['05 30-50u'] += 1

    print(f'\nBy source status:')
    for s, n in status_counter.most_common():
        print(f'  {s:20s} {n}')

    print(f'\nBy confidence:')
    for c, n in conf_counter.most_common():
        print(f'  {c:8s} {n}')

    print(f'\nDisplacement distribution:')
    for b in sorted(disp_buckets):
        print(f'  {b[3:]:10s} {disp_buckets[b]}')

    print(f'\nTarget leaf-extent distribution:')
    for b in sorted(ext_buckets):
        print(f'  {b[3:]:10s} {ext_buckets[b]}')

    # Cluster impact analysis — how many cluster relocations would split
    # the cluster across leaves?
    cluster_stats = {
        'total_clusters': 0,
        'singleton_slots': 0,
        'clusters_intact': 0,
        'clusters_split':  0,
        'split_distances': [],
    }
    for msb, slots in results.items():
        seen_clusters = set()
        for pi, r in slots.items():
            if r['cluster_id'] is None:
                cluster_stats['singleton_slots'] += 1
                continue
            ck = (msb, r['cluster_id'])
            if ck in seen_clusters:
                continue
            seen_clusters.add(ck)
            cluster_stats['total_clusters'] += 1
            if r['cluster_split']:
                cluster_stats['clusters_split'] += 1
                cluster_stats['split_distances'].append(r['cluster_split_distance'])
            else:
                cluster_stats['clusters_intact'] += 1

    print(f'\nCluster impact (groups within {CLUSTER_THRESHOLD}u of each other in vanilla):')
    print(f'  singleton slots:            {cluster_stats["singleton_slots"]}')
    print(f'  clusters intact (survive):  {cluster_stats["clusters_intact"]}')
    print(f'  clusters split by naive nearest-leaf: {cluster_stats["clusters_split"]}')
    if cluster_stats['split_distances']:
        sd = cluster_stats['split_distances']
        print(f'    split distance: min={min(sd):.1f}u, '
              f'median={sorted(sd)[len(sd)//2]:.1f}u, max={max(sd):.1f}u')

    # Write JSON
    out_payload = {
        'metadata': {
            'tool': 'build_slot_repositions.py',
            'tight_leaf_max_extent': TIGHT_LEAF_MAX_EXTENT,
            'cluster_threshold': CLUSTER_THRESHOLD,
            'relocatable_statuses': sorted(RELOCATABLE_STATUSES),
            'total_relocations': total_relocations,
            'maps_with_proposals': len(results),
            'maps_skipped_no_navmesh': len(skipped_maps_no_nm),
            'maps_skipped_stub':       len(skipped_maps_stub),
            'maps_skipped_no_leaves':  len(skipped_maps_no_leaves),
            'slots_skipped_flier':     total_flier_skipped,
            'flier_prefixes':          sorted(flier_prefixes),
            'confidence_distribution': dict(conf_counter),
            'cluster_stats': {
                'singleton_slots':   cluster_stats['singleton_slots'],
                'clusters_intact':   cluster_stats['clusters_intact'],
                'clusters_split':    cluster_stats['clusters_split'],
            },
        },
        'proposals': results,
    }
    with open(args.out, 'w') as f:
        json.dump(out_payload, f, indent=2)
    print(f'\nWrote {args.out} ({os.path.getsize(args.out):,} bytes)')


if __name__ == '__main__':
    main()