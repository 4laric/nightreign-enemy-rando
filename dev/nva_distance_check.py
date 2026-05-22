#!/usr/bin/env python3
"""nva_distance_check.py — Heuristic navmesh-distance check for problem slots.

Path B from the navmesh investigation: skip parsing Havok TAG0 triangle data
(complex, defer to v0.20+); use the much simpler .nva manifest data which
gives us navmesh transform centers per map cell.

For each enemy placement in a spoiler, find the nearest navmesh transform
in that map cell. Slots whose nearest navmesh is well beyond plausible tile
extent are likely on dead terrain (no walkable surface), strong signal for
"broken in oops-all".

CAVEATS — this is a heuristic, not authoritative:
  - parse_nva_transforms() scans the binary for plausible Vec3 vectors
    rather than implementing the full NVA structured parser. May pick up
    bounding-box corners or scale vectors as false-positive transforms.
  - Navmesh tiles extend ~50-100 units around their center, so a slot at
    ~50 units distance might still be on the tile. Default threshold 100
    aims to flag only HIGH-confidence "off-mesh" slots.
  - For authoritative slope/edge detection, parse the Havok TAG0 triangle
    data (deferred — TODO Path A).

Empirical: on m60_44_38_30 oops-all-Rat (seed 309746), 11 broken Rats had
distance > 100 units (high confidence off-mesh) and 4 confirmed-working
Rats at the same map cell had distance < 20 units.

Usage:
    # Extract .nva.dcx files from your NR install:
    #   <NR install>/map/m60/m60_XX_YY_ZZ/m60_XX_YY_ZZ.nva.dcx
    # Place them in a directory, then run:

    python nva_distance_check.py \\
        --spoiler /path/to/_spoilers.json \\
        --nva-dir /path/to/nva_files/ \\
        --threshold 100

Output: spoiler entries flagged where nearest navmesh distance > threshold.

Can be combined with diagnose_problem_slots.py output to identify whether
a known-broken slot is "off-navmesh" (this tool flags it) vs "on-navmesh-but-
fragile-target" (won't be flagged here, needs other heuristics).
"""

import argparse
import json
import os
import struct
import sys


def decompress_dcx(blob):
    """Decompress a DCX-Kraken-wrapped blob using the ooz Python module.
    Returns raw uncompressed bytes. May fail on multi-block Kraken streams
    (pyooz limitation) — for those, the user can pre-decompress on Windows
    side using dcx.py with the official Oodle DLL."""
    try:
        import ooz
    except ImportError:
        raise RuntimeError("ooz module not available. pip install pyooz")
    if blob[:4] != b'DCX\x00':
        raise ValueError(f'Not DCX (magic={blob[:4]!r})')
    unc_size = struct.unpack('>I', blob[0x1c:0x20])[0]
    cmp_size = struct.unpack('>I', blob[0x20:0x24])[0]
    data_off = struct.unpack('>I', blob[0x14:0x18])[0]
    payload = blob[data_off:data_off+cmp_size]
    return ooz.decompress(payload, unc_size)


def parse_nva_transforms(raw):
    """Extract plausible Vec3 navmesh-transform positions from a decompressed
    .nva (NVMA) manifest. The full structure has 14+ navmesh entries with
    transforms (position+rotation+scale), but rather than reverse-engineering
    the full layout, this scans for plausible Vec3 positions in the binary.

    Returns: list of (x, y, z) tuples for plausible navmesh centers."""
    if raw[:4] != b'NVMA':
        raise ValueError(f'Not NVMA (magic={raw[:4]!r})')

    positions = []
    seen = set()  # dedup
    # Scan for plausible Vec3 — x, y, z all in reasonable ranges, not all-zero,
    # not unit-scale (1.0, 1.0, 1.0).
    for off in range(0x30, len(raw) - 12, 4):
        try:
            x, y, z = struct.unpack('<fff', raw[off:off+12])
        except struct.error:
            continue
        if not (-500 < x < 500 and -500 < y < 500 and -500 < z < 500):
            continue
        if abs(x) < 1.0 or abs(z) < 1.0:
            continue  # filter near-zero scale-like values
        # Round to dedup near-duplicates
        key = (round(x, 1), round(y, 1), round(z, 1))
        if key in seen:
            continue
        seen.add(key)
        positions.append((x, y, z))
    return positions


def load_navmesh_manifests(nva_dir):
    """Walk nva_dir for *.nva.dcx files, decompress, extract transforms.
    Returns dict: msb_name (e.g. 'm60_44_38_30.msb') -> [(x,y,z), ...]"""
    manifests = {}
    failed = []
    for fname in sorted(os.listdir(nva_dir)):
        # Accept both 'm60_44_38_30.nva.dcx' and 'm60_44_38_30_nva.dcx' naming
        if fname.endswith('.nva.dcx'):
            map_name = fname[:-len('.nva.dcx')] + '.msb'
        elif fname.endswith('_nva.dcx'):
            map_name = fname[:-len('_nva.dcx')] + '.msb'
        else:
            continue
        try:
            blob = open(os.path.join(nva_dir, fname), 'rb').read()
            raw = decompress_dcx(blob)
            positions = parse_nva_transforms(raw)
            manifests[map_name] = positions
        except Exception as e:
            failed.append((fname, str(e)))
    return manifests, failed


def nearest_distance(pos, transform_list):
    """Returns the Euclidean distance from pos to the nearest transform."""
    if not transform_list:
        return float('inf')
    px, py, pz = pos
    best_sq = float('inf')
    for tx, ty, tz in transform_list:
        d2 = (tx-px)**2 + (ty-py)**2 + (tz-pz)**2
        if d2 < best_sq:
            best_sq = d2
    return best_sq ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spoiler', required=True,
                    help='Path to _spoilers.json from a playtest seed')
    ap.add_argument('--nva-dir', required=True,
                    help='Directory containing *.nva.dcx files')
    ap.add_argument('--threshold', type=float, default=100.0,
                    help='Distance threshold (units) for flagging slots. '
                         'Default 100 = high-confidence off-mesh only. '
                         'Lower (~30) catches more candidates but with noise.')
    ap.add_argument('--target-c-prefix', default=None,
                    help='Filter to only this target c-prefix (e.g. c4080 for oops-all-Rat)')
    args = ap.parse_args()

    print(f'Loading spoiler: {args.spoiler}')
    with open(args.spoiler) as f:
        sp = json.load(f)
    print(f'Loading navmesh manifests from: {args.nva_dir}')
    manifests, failed = load_navmesh_manifests(args.nva_dir)
    print(f'  Loaded {len(manifests)} maps, {sum(len(v) for v in manifests.values())} total transforms')
    if failed:
        print(f'  {len(failed)} files failed to decompress (likely multi-block Kraken):')
        for fname, err in failed[:5]:
            print(f'    {fname}: {err}')

    if not manifests:
        print('\nNo navmesh manifests parsed — exiting.')
        sys.exit(1)

    # Walk spoiler, compute distances for entries in maps we have manifests for
    flagged = []
    checked = 0
    for e in sp['entries']:
        if not e.get('position'):
            continue
        if e['map'] not in manifests:
            continue
        if args.target_c_prefix and e['new']['c_prefix'] != args.target_c_prefix:
            continue
        checked += 1
        dist = nearest_distance(e['position'], manifests[e['map']])
        if dist > args.threshold:
            flagged.append((dist, e))

    flagged.sort(key=lambda r: -r[0])  # furthest first
    print(f'\nChecked {checked} placements across {len(manifests)} maps.')
    print(f'Flagged {len(flagged)} slots with nearest-navmesh > {args.threshold} units:')
    print()
    print(f"{'distance':>10}  {'map':<22} {'pi':<5} {'pos':<32} {'src':<8} {'target'}")
    for dist, e in flagged[:50]:
        src = e['original']['c_prefix']
        new = e['new']['c_prefix']
        pos = e['position']
        pos_str = f'({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f})'
        print(f"  {dist:>8.1f}  {e['map']:<22} {e['part_index']:<5} {pos_str:<32} {src:<8} {new}")
    if len(flagged) > 50:
        print(f'  ... {len(flagged)-50} more')

    # Suggest V3_PROBLEM_SLOTS additions
    print()
    print('# Suggested V3_PROBLEM_SLOTS entries (paste-ready):')
    print('V3_PROBLEM_SLOTS_FROM_NAVMESH = {')
    for dist, e in flagged[:30]:
        print(f"    ({e['map']!r}, {e['part_index']}): "
              f"'far from navmesh ({dist:.0f} units) | was {e['original']['c_prefix']}',")
    print('}')


if __name__ == '__main__':
    main()
