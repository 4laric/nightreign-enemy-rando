#!/usr/bin/env python3
"""build_slot_poi_clusters.py — Derive per-MSB spatial POI clusters from
data/nr_slot_inventory.json. Output: data/slot_poi_clusters.json.

Phase 0 of POI-level recycling. Algorithm: deterministic leader /
centroid-link clustering on slot XZ position. For each slot (in
canonical part_index order), join the nearest existing cluster within R
by current centroid distance, else start a new cluster.

Y excluded — vertical separation inside a single dungeon isn't a
streaming boundary. R default 80m, tunable.
"""
import argparse, json, math, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
INVENTORY_PATH = os.path.join(PROJECT_ROOT, 'data/nr_slot_inventory.json')
DEFAULT_OUT = os.path.join(PROJECT_ROOT, 'data/slot_poi_clusters.json')
TIGHT_INTERIOR_PREFIXES = ('m13_',)


def cluster_msb(slots, radius):
    if not slots:
        return []
    r2 = radius * radius
    ordered = sorted(slots, key=lambda s: s['part_index'])
    centroids = []   # (sum_x, sum_z, n) per cluster
    members = []
    for s in ordered:
        x, _y, z = s['position']
        best_idx, best_d2 = -1, r2
        for i, (sx, sz, n) in enumerate(centroids):
            cx, cz = sx / n, sz / n
            d2 = (x - cx) ** 2 + (z - cz) ** 2
            if d2 < best_d2:
                best_idx, best_d2 = i, d2
        if best_idx >= 0:
            sx, sz, n = centroids[best_idx]
            centroids[best_idx] = (sx + x, sz + z, n + 1)
            members[best_idx].append(s['part_index'])
        else:
            centroids.append((x, z, 1))
            members.append([s['part_index']])
    clusters = [sorted(pis) for pis in members]
    clusters.sort(key=lambda c: c[0])
    return clusters


def cluster_diameter_xz(slots):
    if len(slots) < 2:
        return 0.0
    m = 0.0
    for i in range(len(slots)):
        xi, _, zi = slots[i]['position']
        for j in range(i + 1, len(slots)):
            xj, _, zj = slots[j]['position']
            d2 = (xi - xj) ** 2 + (zi - zj) ** 2
            if d2 > m:
                m = d2
    return math.sqrt(m)


def build_all(inventory, radius):
    by_msb = defaultdict(list)
    by_msb_nopos = defaultdict(list)
    for r in inventory:
        (by_msb if r.get('position') else by_msb_nopos)[r['map']].append(r)
    out = {}
    n_clusters_total = 0
    for msb in sorted(set(by_msb) | set(by_msb_nopos)):
        positioned = by_msb.get(msb, [])
        no_position = by_msb_nopos.get(msb, [])
        clusters = cluster_msb(positioned, radius)
        if no_position:
            clusters.append(sorted(s['part_index'] for s in no_position))
        out[msb] = clusters
        n_clusters_total += len(clusters)
    return out, {'n_msbs': len(out), 'n_clusters_total': n_clusters_total}


def validate(clusters, inventory, radius):
    inv_keys = {(r['map'], r['part_index']) for r in inventory}
    seen = set()
    for msb, clist in clusters.items():
        for cluster in clist:
            for pi in cluster:
                assert (msb, pi) not in seen, f"duplicate ({msb}, {pi})"
                seen.add((msb, pi))
    assert seen == inv_keys, (
        f"diverged: missing={len(inv_keys-seen)}, extra={len(seen-inv_keys)}")
    pos_by_msb = defaultdict(list)
    nopos = defaultdict(int)
    for r in inventory:
        if r.get('position'):
            pos_by_msb[r['map']].append(r)
        else:
            nopos[r['map']] += 1
    for msb, slots in pos_by_msb.items():
        if cluster_diameter_xz(slots) <= radius:
            n_sp = len(clusters[msb]) - (1 if nopos[msb] else 0)
            assert n_sp == 1, f"math invariant: {msb} diam<=R but {n_sp} clusters"
    for msb in pos_by_msb:
        if msb.startswith(TIGHT_INTERIOR_PREFIXES):
            n_sp = len(clusters[msb]) - (1 if nopos[msb] else 0)
            assert n_sp == 1, f"tight interior {msb} split into {n_sp}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--radius', type=float, default=80.0)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--inventory', default=INVENTORY_PATH)
    args = ap.parse_args()
    with open(args.inventory, encoding='utf-8') as f:
        inventory = json.load(f)
    clusters, stats = build_all(inventory, args.radius)
    validate(clusters, inventory, args.radius)
    n_nopos = sum(1 for r in inventory if not r.get('position'))
    output = {
        '_meta': {
            'format_version': 1,
            'build_script': 'dev/build_slot_poi_clusters.py',
            'radius_m': args.radius,
            'axis': 'XZ',
            'algorithm': 'deterministic leader/centroid-link',
            'n_msbs': stats['n_msbs'],
            'n_clusters_total': stats['n_clusters_total'],
            'n_slots_total': len(inventory),
            'n_slots_no_position': n_nopos,
        },
        'clusters': clusters,
    }
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, sort_keys=False)
        f.write('\n')
    print(f"Wrote {args.out} ({stats['n_clusters_total']} clusters across "
          f"{stats['n_msbs']} MSBs at R={args.radius}m)", file=sys.stderr)


if __name__ == '__main__':
    main()
