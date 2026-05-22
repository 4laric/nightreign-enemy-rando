#!/usr/bin/env python3
"""audit_encampment_anchors.py — v0.21

Scan vanilla MSBs for tiles containing tight clusters of encampment-archetype
source c-prefixes (Highwayman, Stonedigger, Glintstone Digger, Soldier
families) without a nearby T1-qualifier anchor. Emits proposed synthetic
'Encampment' anchors to add to t1_anchors.json so the v0.21 m60_44_39_30
fix gets generalized to sibling tiles before they CTD.

Why this exists: bandit camps in Limveld have generic-named source variants
('Highwayman' / 'Stonedigger' / 'Godrick Soldier') with no '(Encampment)'
qualifier, so the T1 variant-qualifier check misses them. The v0.20.74
cathedral patch added per-tile prefixes to V3_FRAGILE_MAP_PREFIXES; this
script finds the analogous gaps for encampment tiles and emits a more
surgical anchor-based fix instead of whole-tile prefixes.

Usage:
    python audit_encampment_anchors.py                  # report only
    python audit_encampment_anchors.py --emit-json out.json  # emit anchor JSON

Reads:
    vanilla msbs/*.msb.dcx        — needs Oodle DLL on PATH
    t1_anchors.json               — for cross-referencing existing anchors
    nr_enemy_tags.json            — for size_class lookups (sanity check)

Notes:
    * The encampment-archetype set is derived from m60_44_39_30 user CTD
      analysis. Add c-prefixes here as new archetypes surface.
    * Tight cluster threshold = 4+ archetype slots within a 60u sphere.
      Tuning: set lower (e.g. 3 within 50u) for more aggressive coverage,
      higher for stricter. The m60_44_39_30 west camp had 17 archetype
      slots in a ~70u radius; east camp had 3 in <10u.
    * A cluster is flagged as a NEW gap if its centroid is >100u from
      every existing anchor in the same MSB (matches V3_T1_PROXIMITY_RADIUS).
"""
import argparse, json, math, os, struct, sys
from collections import defaultdict

# Set of source c-prefixes that mark bandit-camp / encampment scaffolding.
# These appear together at fragile camp slots in Limveld (and elsewhere)
# with bare names — no '(Encampment)' qualifier — so T1 misses them.
ENCAMPMENT_ARCHETYPE_PREFIXES = frozenset({
    'c4311',  # Godrick Soldier
    'c4313',  # Leyndell Soldier
    'c4371',  # Godrick Foot Soldier
    'c4373',  # Leyndell Foot Soldier
    'c4377',  # Highwayman
    'c4382',  # Stonedigger
    'c4383',  # Glintstone Digger
    'c4384',  # Glintstone Digger (Small Sack)
})

# Cluster detection tunables
MIN_CLUSTER_SIZE = 4         # archetype-slot count to qualify as a "camp"
MAX_INTRA_CLUSTER_DIST = 60.0  # archetype slots within this 3D distance cluster together
ANCHOR_GAP_RADIUS = 100.0    # match V3_T1_PROXIMITY_RADIUS in oops_v3.py

# MSB binary offsets (mirrors oops_v3.py constants)
PART_OFF_MODEL_INDEX = 0x014  # was 0x40 in v0.21 — wrong, parsing junk
POS_OFF = 0x400


def load_existing_anchors(path='t1_anchors.json'):
    if not os.path.exists(path):
        return {}
    return json.load(open(path)).get('maps', {})


def parse_msb_archetype_positions(msb_path, oops_v3_module):
    """Parse an MSB (raw or DCX-compressed) and return [(pi, c_prefix,
    (x, y, z)), ...] for every Part whose model is in
    ENCAMPMENT_ARCHETYPE_PREFIXES. Auto-detects raw vs DCX by extension."""
    if msb_path.endswith('.dcx'):
        from dcx import DCX
        data = DCX.decompress_file(msb_path)
    else:
        with open(msb_path, 'rb') as f:
            data = f.read()
    sections = oops_v3_module.parse_msb_sections(data)
    if len(sections) != 6:
        return []
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]
    midx_to_cp = {gi: oops_v3_module.parse_model_entry(data, eo)['name']
                  for gi, eo in enumerate(models['entry_offsets'])}
    out = []
    for pi, po in enumerate(parts['entry_offsets']):
        midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        cp = midx_to_cp.get(midx)
        if cp not in ENCAMPMENT_ARCHETYPE_PREFIXES:
            continue
        if po + POS_OFF + 12 > len(data):
            continue
        try:
            x, y, z = struct.unpack_from('<fff', data, po + POS_OFF)
        except struct.error:
            continue
        if any(v != v for v in (x, y, z)):  # NaN
            continue
        out.append((pi, cp, (x, y, z)))
    return out


def cluster_positions(positions, eps=MAX_INTRA_CLUSTER_DIST):
    """Single-link spatial clustering on archetype positions. Two points
    join the same cluster if within eps. Returns list of clusters, each a
    list of (pi, cp, (x,y,z)) tuples. Naive O(n^2) — fine for ~50 slots."""
    clusters = []
    eps_sq = eps * eps
    assigned = [-1] * len(positions)
    for i, (_, _, pi_pos) in enumerate(positions):
        if assigned[i] >= 0:
            continue
        # Start a new cluster, expand transitively
        cluster_idx = len(clusters)
        clusters.append([])
        stack = [i]
        while stack:
            j = stack.pop()
            if assigned[j] >= 0:
                continue
            assigned[j] = cluster_idx
            clusters[cluster_idx].append(positions[j])
            jx, jy, jz = positions[j][2]
            for k in range(len(positions)):
                if assigned[k] >= 0:
                    continue
                kx, ky, kz = positions[k][2]
                dsq = (jx-kx)**2 + (jy-ky)**2 + (jz-kz)**2
                if dsq <= eps_sq:
                    stack.append(k)
    return clusters


def cluster_centroid(cluster):
    n = len(cluster)
    cx = sum(p[2][0] for p in cluster) / n
    cy = sum(p[2][1] for p in cluster) / n
    cz = sum(p[2][2] for p in cluster) / n
    return (cx, cy, cz)


def has_nearby_anchor(centroid, anchors, radius=ANCHOR_GAP_RADIUS):
    cx, cy, cz = centroid
    rsq = radius * radius
    for a in anchors:
        ax, ay, az = a['pos']
        if (cx-ax)**2 + (cy-ay)**2 + (cz-az)**2 <= rsq:
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vanilla-dir', default='vanilla msbs',
                    help='Directory containing vanilla *.msb.dcx files')
    ap.add_argument('--anchors', default='t1_anchors.json',
                    help='Existing T1 anchors file')
    ap.add_argument('--emit-json', default=None,
                    help='If set, emit suggested anchors to this JSON file')
    ap.add_argument('--map-filter', default=None,
                    help='Substring filter on MSB filenames (e.g. m60_44 to scan one tile coord)')
    ap.add_argument('--min-cluster', type=int, default=MIN_CLUSTER_SIZE,
                    help=f'Minimum archetype slots per cluster (default {MIN_CLUSTER_SIZE})')
    args = ap.parse_args()

    # Import oops_v3 lazily — needs the parse_msb helpers
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import oops_v3

    existing = load_existing_anchors(args.anchors)

    msb_files = sorted(f for f in os.listdir(args.vanilla_dir)
                       if f.endswith('.msb.dcx') or f.endswith('.msb'))
    if args.map_filter:
        msb_files = [f for f in msb_files if args.map_filter in f]

    suggestions = defaultdict(list)
    n_scanned = 0
    n_archetype_total = 0
    n_decompress_fail = 0
    n_clusters_seen = 0

    for fname in msb_files:
        msb_path = os.path.join(args.vanilla_dir, fname)
        msb_name = fname[:-4] if fname.endswith('.dcx') else fname  # strip .dcx
        try:
            archs = parse_msb_archetype_positions(msb_path, oops_v3)
        except Exception as e:
            n_decompress_fail += 1
            continue
        n_scanned += 1
        n_archetype_total += len(archs)
        if len(archs) < args.min_cluster:
            continue

        clusters = cluster_positions(archs)
        for cluster in clusters:
            if len(cluster) < args.min_cluster:
                continue
            n_clusters_seen += 1
            centroid = cluster_centroid(cluster)
            existing_for_msb = existing.get(msb_name, [])
            if has_nearby_anchor(centroid, existing_for_msb):
                continue  # Already covered
            archetype_counts = defaultdict(int)
            for _, cp, _ in cluster:
                archetype_counts[cp] += 1
            suggestions[msb_name].append({
                'pos': [round(centroid[0], 1),
                        round(centroid[1], 1),
                        round(centroid[2], 1)],
                'cluster_size': len(cluster),
                'archetype_breakdown': dict(archetype_counts),
                'pi_list': [t[0] for t in cluster],
            })

    print(f"Scanned {n_scanned} MSBs ({n_decompress_fail} decompress failures)")
    print(f"Total archetype-source slots seen: {n_archetype_total}")
    print(f"Total qualifying clusters seen:   {n_clusters_seen}")
    print(f"Clusters MISSING an anchor:       {sum(len(v) for v in suggestions.values())}")
    print(f"MSBs with new gaps:               {len(suggestions)}")
    print()
    if not suggestions:
        print("No new anchor gaps found — all encampment-archetype clusters are within "
              f"{ANCHOR_GAP_RADIUS}u of an existing anchor.")
        return
    print(f"{'MSB':<28} {'pos':>26} {'n':>3} {'breakdown'}")
    print('-' * 100)
    for msb_name in sorted(suggestions):
        for s in suggestions[msb_name]:
            x, y, z = s['pos']
            pos_str = f"({x:>6.1f},{y:>6.1f},{z:>6.1f})"
            bd = ', '.join(f"{cp}×{n}" for cp, n in
                           sorted(s['archetype_breakdown'].items()))
            print(f"{msb_name:<28} {pos_str:>26} {s['cluster_size']:>3}  {bd}")

    if args.emit_json:
        emitted = {}
        for msb_name, items in suggestions.items():
            emitted[msb_name] = [{
                'pos': s['pos'],
                'quals': ['Encampment'],
                '_synthetic': True,
                '_provenance': (f"v0.21 audit_encampment_anchors.py — "
                                f"cluster of {s['cluster_size']} archetype slots "
                                f"({', '.join(f'{c}×{n}' for c, n in sorted(s['archetype_breakdown'].items()))}) "
                                f"with no T1 anchor within {ANCHOR_GAP_RADIUS}u. Verify via playtest."),
            } for s in items]
        with open(args.emit_json, 'w') as f:
            json.dump(emitted, f, indent=2)
        print(f"\nWrote {args.emit_json} ({sum(len(v) for v in emitted.values())} suggested anchors)")
        print("To merge: hand-review, then load t1_anchors.json, extend "
              "data['maps'][msb_name] with the suggestions, save.")


if __name__ == '__main__':
    main()
