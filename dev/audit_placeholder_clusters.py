#!/usr/bin/env python3
"""audit_placeholder_clusters.py — v0.22 (proposed)

Scan vanilla MSBs for tiles where a large number of Part slots share a single
(y, z) coordinate line — the signature of script-spawn-target slots with
deferred coord resolution. Emits proposed synthetic anchors at x-clumps along
each placeholder line so the v0.21 m60_44_39_30 encampment fix gets
generalized to the analogous shape we just hit at the castle (tile 43, 37,
seed 764264).

Why this exists: at the castle, 58 of 111 slots in m60_43_37_00 sit at
(?, 0.0, 1.0). They're script-spawn-target slots whose actual position is
resolved at runtime; the rando never sees real coords for them, so spatial
fragility detection (T1 anchors / T2 cluster / V3_FRAGILE_MAP_PREFIXES) has
no way to flag the slot as fragile. The result was 8 SAFE_CONFIRMED chrs
clustered at the front-door arc still CTDing on castle exit. Same shape of
gap as encampments pre-v0.21, but the encampment audit is c-prefix-driven
(detects camp-archetype source variants) and won't catch this — castles use
the canonical "Banished Knight (Castle-)" / "Exile Soldier" originals which
aren't in the encampment archetype set. This audit is position-driven
instead: any tile with ≥N slots on a (y, z) line gets flagged regardless of
what c-prefixes are at those slots.

Usage:
    python audit_placeholder_clusters.py                              # report only
    python audit_placeholder_clusters.py --emit-json out.json         # emit anchor JSON
    python audit_placeholder_clusters.py --map-filter m60_43          # scan one tile coord
    python audit_placeholder_clusters.py --min-line 12 --xclump 50    # tune

Reads:
    vanilla msbs/*.msb.dcx        — needs Oodle DLL on PATH
    t1_anchors.json               — for cross-referencing existing anchors

Notes:
    * "Placeholder line" = any (y, z) value (rounded to 0.5u) shared by >=
      MIN_LINE_SIZE slots in a single MSB. Default 10.
    * Within each placeholder line, x positions are single-link clustered
      with eps=XCLUMP_EPS (default 60u). Each x-clump becomes one anchor
      proposal — same coverage convention as audit_encampment_anchors.py.
    * "Looks placeholdery" gate: by default |y| < 5 AND |z| < 5. Real
      flat-terrain slots typically have y > 30 in Limveld tiles. Disable
      with --no-placeholder-gate to surface ALL high-concentration lines
      for manual review.
    * An x-clump is flagged as a NEW gap if its 3D centroid is >100u from
      every existing anchor in the same MSB (matches V3_T1_PROXIMITY_RADIUS).
    * Output emits anchors with quals=[] (untyped) since the placeholder
      pattern isn't tied to a specific architectural type — castle, ruins,
      and fort all share the shape. Mark with type after manual review.
"""
import argparse, json, math, os, struct, sys
from collections import defaultdict

# Cluster detection tunables
MIN_LINE_SIZE = 10           # slots sharing a (y, z) to qualify as a placeholder line
MIN_CLUMP_SIZE = 3           # slots within a single x-clump to qualify (filters
                             # out 1-slot outliers within larger placeholder lines)
YZ_BUCKET_RES = 0.5          # rounding bucket for (y, z) deduplication
XCLUMP_EPS = 40.0            # x-clumping distance for anchor proposals
ANCHOR_GAP_RADIUS = 100.0    # match V3_T1_PROXIMITY_RADIUS in oops_v3.py
PLACEHOLDER_Y_ABS = 5.0      # |y| < this to look placeholdery
PLACEHOLDER_Z_ABS = 5.0      # |z| < this to look placeholdery

# MSB binary offsets (per PART_OFF_MODEL_INDEX / PART_OFF_POSITION in
# oops_all_anyone.py). NOTE: audit_encampment_anchors.py uses 0x40 which is
# wrong — should be 0x014. That audit's been parsing junk; needs the same fix.
PART_OFF_MODEL_INDEX = 0x014
POS_OFF = 0x400


def load_existing_anchors(path='t1_anchors.json'):
    if not os.path.exists(path):
        return {}
    return json.load(open(path)).get('maps', {})


def parse_msb_all_positions(msb_path, oops_v3_module):
    """Parse a vanilla MSB (raw or DCX-compressed) and return
    [(pi, c_prefix, (x, y, z)), ...] for every Part with a valid position.
    Auto-detects raw vs DCX by extension."""
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
        if midx < 0:
            continue
        cp = midx_to_cp.get(midx, '?')
        # Filter to chr models only — MSB assets (AEGxxx prefixes) are scenery
        # not enemies, and they cluster on (0,0,0) by the thousands.
        if not cp.startswith('c'):
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


def bucket_by_yz(positions, res=YZ_BUCKET_RES):
    """Group positions by rounded (y, z) bucket. Returns
    {(y_bucket, z_bucket): [(pi, cp, (x,y,z)), ...]}."""
    buckets = defaultdict(list)
    for entry in positions:
        _, _, (x, y, z) = entry
        key = (round(y / res) * res, round(z / res) * res)
        buckets[key].append(entry)
    return buckets


def xclump(line_entries, eps=XCLUMP_EPS):
    """Single-link clustering on x within a placeholder line. Returns list of
    clumps, each a list of (pi, cp, (x,y,z))."""
    n = len(line_entries)
    assigned = [-1] * n
    clumps = []
    eps_sq = eps * eps  # 1D distance squared, same scale
    for i in range(n):
        if assigned[i] >= 0:
            continue
        ci = len(clumps)
        clumps.append([])
        stack = [i]
        while stack:
            j = stack.pop()
            if assigned[j] >= 0:
                continue
            assigned[j] = ci
            clumps[ci].append(line_entries[j])
            jx = line_entries[j][2][0]
            for k in range(n):
                if assigned[k] >= 0:
                    continue
                kx = line_entries[k][2][0]
                if (jx - kx) ** 2 <= eps_sq:
                    stack.append(k)
    return clumps


def clump_centroid(clump):
    n = len(clump)
    cx = sum(p[2][0] for p in clump) / n
    cy = sum(p[2][1] for p in clump) / n
    cz = sum(p[2][2] for p in clump) / n
    return (cx, cy, cz)


def clump_x_span(clump):
    xs = [p[2][0] for p in clump]
    return min(xs), max(xs)


def cover_clump_with_anchors(clump, radius=ANCHOR_GAP_RADIUS):
    """Generate enough anchors to cover every slot in the clump within `radius`.
    Returns list of (x, y, z) anchor positions.

    Strategy: a single anchor covers a span of 2*radius. For a clump of x-span
    L, we need ceil(L / (2*radius)) anchors. Place them evenly along the span
    so each slot is within `radius` of its nearest anchor. y, z are taken from
    the clump centroid (placeholder lines have constant y, z so this is fine).
    """
    if not clump:
        return []
    x_min, x_max = clump_x_span(clump)
    span = x_max - x_min
    _, cy, cz = clump_centroid(clump)
    if span <= 2 * radius:
        # One anchor suffices — place at midpoint, not centroid, to ensure
        # endpoints are covered (centroid is biased toward dense regions).
        return [(round((x_min + x_max) / 2.0, 1), round(cy, 1), round(cz, 1))]
    n = int(math.ceil(span / (2 * radius)))
    step = span / n
    return [(round(x_min + step * (i + 0.5), 1), round(cy, 1), round(cz, 1))
            for i in range(n)]


def has_nearby_anchor(centroid, anchors, radius=ANCHOR_GAP_RADIUS):
    cx, cy, cz = centroid
    rsq = radius * radius
    for a in anchors:
        ax, ay, az = a['pos']
        if (cx - ax) ** 2 + (cy - ay) ** 2 + (cz - az) ** 2 <= rsq:
            return True
    return False


# Archetype heuristics for qualifier inference. The c-prefix breakdown of a
# clump's source slots is a strong signal — castle perimeters are populated
# with Banished Knights / Exile Soldiers; encampments use the standard
# bandit-camp archetype set; etc. Hand-labeling can refine these post hoc, but
# the heuristic gets us most of the way.
ARCHETYPE_PREFIXES = {
    # Castle (Stormveil-archetype): Banished Knights and Exile Soldiers form
    # the perimeter. c3000/c3010/c3020 dominate the front-door arc.
    'Castle': frozenset({'c3000', 'c3010', 'c3020'}),
    # Encampment (bandit camp): same set used by audit_encampment_anchors.py.
    'Encampment': frozenset({'c4311', 'c4313', 'c4371', 'c4373', 'c4377',
                             'c4382', 'c4383', 'c4384'}),
}


def infer_qualifier(cp_counts):
    """Best-guess qualifier for a clump given its source c-prefix histogram.
    Returns a single qualifier string or None if nothing looks dominant.

    Heuristic: an archetype wins if >= 60% of clump slots match its prefix
    set. Threshold is conservative to avoid mislabeling mixed/ambiguous clumps.
    """
    if not cp_counts:
        return None
    total = sum(cp_counts.values())
    if total == 0:
        return None
    best_label = None
    best_share = 0.0
    for label, prefixes in ARCHETYPE_PREFIXES.items():
        share = sum(n for cp, n in cp_counts.items() if cp in prefixes) / total
        if share > best_share:
            best_share = share
            best_label = label
    return best_label if best_share >= 0.6 else None


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
                    help='Substring filter on MSB filenames (e.g. m60_43 to scan one tile coord)')
    ap.add_argument('--min-line', type=int, default=MIN_LINE_SIZE,
                    help=f'Minimum slots on a (y,z) line to qualify (default {MIN_LINE_SIZE})')
    ap.add_argument('--xclump', type=float, default=XCLUMP_EPS,
                    help=f'X-clumping distance for anchor proposals (default {XCLUMP_EPS}u)')
    ap.add_argument('--min-clump', type=int, default=MIN_CLUMP_SIZE,
                    help=f'Minimum slots per x-clump to qualify (default {MIN_CLUMP_SIZE}). '
                         f'Filters out 1-slot outliers within larger placeholder lines.')
    ap.add_argument('--no-placeholder-gate', action='store_true',
                    help='Show ALL high-concentration (y,z) lines, not just placeholder-y/z. '
                         'Useful for surfacing flat-terrain false positives during tuning.')
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import oops_v3

    existing = load_existing_anchors(args.anchors)

    msb_files = sorted(f for f in os.listdir(args.vanilla_dir)
                       if f.endswith('.msb.dcx') or f.endswith('.msb'))
    if args.map_filter:
        msb_files = [f for f in msb_files if args.map_filter in f]

    suggestions = defaultdict(list)
    n_scanned = 0
    n_decompress_fail = 0
    n_lines_seen = 0
    n_clumps_seen = 0
    n_clumps_below_min = 0
    n_total_slots = 0

    for fname in msb_files:
        msb_path = os.path.join(args.vanilla_dir, fname)
        msb_name = fname[:-4] if fname.endswith('.dcx') else fname
        try:
            positions = parse_msb_all_positions(msb_path, oops_v3)
        except Exception:
            n_decompress_fail += 1
            continue
        n_scanned += 1
        n_total_slots += len(positions)

        buckets = bucket_by_yz(positions)
        for (yb, zb), entries in buckets.items():
            if len(entries) < args.min_line:
                continue
            if (not args.no_placeholder_gate
                    and (abs(yb) >= PLACEHOLDER_Y_ABS or abs(zb) >= PLACEHOLDER_Z_ABS)):
                continue  # Looks like real flat terrain, not placeholder
            n_lines_seen += 1

            for clump in xclump(entries, eps=args.xclump):
                if len(clump) < args.min_clump:
                    n_clumps_below_min += 1
                    continue
                n_clumps_seen += 1
                centroid = clump_centroid(clump)
                existing_for_msb = existing.get(msb_name, [])
                if has_nearby_anchor(centroid, existing_for_msb):
                    continue
                cp_counts = defaultdict(int)
                for _, cp, _ in clump:
                    cp_counts[cp] += 1
                x_min, x_max = clump_x_span(clump)
                proposed_anchors = cover_clump_with_anchors(clump)
                inferred_qual = infer_qualifier(cp_counts)
                suggestions[msb_name].append({
                    'pos': [round(centroid[0], 1),
                            round(centroid[1], 1),
                            round(centroid[2], 1)],
                    'x_span': round(x_max - x_min, 1),
                    'line_yz': [yb, zb],
                    'clump_size': len(clump),
                    'line_total': len(entries),
                    'cp_breakdown': dict(cp_counts),
                    'pi_list': [t[0] for t in clump],
                    'proposed_anchors': proposed_anchors,
                    'inferred_qual': inferred_qual,
                })

    # Pool-level dedup: across all clumps in the same MSB, suppress any
    # proposed anchor whose coverage is already provided by another anchor
    # we'd emit for the same MSB. This catches the case where two distinct
    # x-clumps end up with anchors close enough that one covers both — e.g.
    # m60_43_37_50 had clumps at x=-68 and x=-137 emitting anchors 83u apart.
    # Defensive merge-side check used to handle this; doing it here so the
    # audit's own output is correct.
    n_anchors_deduped = 0
    finalized = {}
    for msb_name, items in suggestions.items():
        kept_anchors = []  # list of (x, y, z) finalized for this MSB
        existing_for_msb = existing.get(msb_name, [])
        existing_pts = [tuple(a['pos']) for a in existing_for_msb]
        for s in items:
            kept_for_clump = []
            for ax, ay, az in s['proposed_anchors']:
                # Check against (a) existing anchors, (b) already-kept anchors
                # for this MSB. Distance check uses ANCHOR_GAP_RADIUS — same
                # threshold the runtime uses to decide T2.7 coverage, so
                # de-duping here matches the actual coverage semantics.
                rsq = ANCHOR_GAP_RADIUS ** 2
                clash = False
                for ex_x, ex_y, ex_z in existing_pts + kept_anchors:
                    if (ax-ex_x)**2 + (ay-ex_y)**2 + (az-ex_z)**2 <= rsq:
                        clash = True
                        break
                if clash:
                    n_anchors_deduped += 1
                    continue
                kept_for_clump.append((ax, ay, az))
                kept_anchors.append((ax, ay, az))
            s['proposed_anchors'] = kept_for_clump
        finalized[msb_name] = items
    suggestions = {m: v for m, v in finalized.items()
                   if any(s['proposed_anchors'] for s in v)}

    print(f"Scanned {n_scanned} MSBs ({n_decompress_fail} decompress failures), "
          f"{n_total_slots} parts total")
    print(f"Placeholder lines flagged: {n_lines_seen}")
    print(f"X-clumps within those lines: {n_clumps_seen} "
          f"(plus {n_clumps_below_min} below --min-clump={args.min_clump} threshold, dropped)")
    n_anchors_proposed = sum(len(s['proposed_anchors'])
                             for items in suggestions.values() for s in items)
    print(f"Clumps MISSING an anchor: {sum(len(v) for v in suggestions.values())}")
    print(f"Anchors proposed: {n_anchors_proposed} "
          f"(multi-anchor where x-span > {2*ANCHOR_GAP_RADIUS:.0f}u; "
          f"{n_anchors_deduped} suppressed by pool dedup)")
    print(f"MSBs with new gaps: {len(suggestions)}")
    print()
    if not suggestions:
        print(f"No new anchor gaps found — all placeholder x-clumps are within "
              f"{ANCHOR_GAP_RADIUS}u of an existing anchor.")
        return

    print(f"{'MSB':<28} {'centroid':>26} {'span':>6} {'line':>16} "
          f"{'n':>3}/{'tot':<3} {'#a':>2}  {'qual':<10}  top c-prefixes")
    print('-' * 130)
    for msb_name in sorted(suggestions):
        for s in suggestions[msb_name]:
            if not s['proposed_anchors']:
                continue  # all anchors for this clump were deduped
            x, y, z = s['pos']
            pos_str = f"({x:>6.1f},{y:>6.1f},{z:>6.1f})"
            yb, zb = s['line_yz']
            line_str = f"y={yb:.1f},z={zb:.1f}"
            top_cps = sorted(s['cp_breakdown'].items(), key=lambda kv: -kv[1])[:3]
            cp_str = ', '.join(f"{cp}×{n}" for cp, n in top_cps)
            qual_str = s.get('inferred_qual') or '?'
            print(f"{msb_name:<28} {pos_str:>26} {s['x_span']:>6.0f} {line_str:>16} "
                  f"{s['clump_size']:>3}/{s['line_total']:<3} {len(s['proposed_anchors']):>2}  "
                  f"{qual_str:<10}  {cp_str}")

    if args.emit_json:
        emitted = defaultdict(list)
        for msb_name, items in suggestions.items():
            for s in items:
                n_a = len(s['proposed_anchors'])
                if n_a == 0:
                    continue
                quals = [s['inferred_qual']] if s.get('inferred_qual') else []
                for i, (ax, ay, az) in enumerate(s['proposed_anchors']):
                    emitted[msb_name].append({
                        'pos': [ax, ay, az],
                        'quals': quals,
                        '_synthetic': True,
                        '_provenance': (
                            f"v0.23.02 audit_placeholder_clusters.py — "
                            f"anchor {i+1}/{n_a} for x-clump of {s['clump_size']} slots "
                            f"on placeholder line (y={s['line_yz'][0]:.1f}, z={s['line_yz'][1]:.1f}; "
                            f"x-span {s['x_span']:.0f}u, {s['line_total']} slots on full line). "
                            f"No T1 anchor within {ANCHOR_GAP_RADIUS}u. "
                            f"Qualifier {'inferred from c-prefix breakdown' if quals else 'left blank — hand-review'}."),
                    })
        with open(args.emit_json, 'w') as f:
            json.dump(dict(emitted), f, indent=2)
        print(f"\nWrote {args.emit_json} ({n_anchors_proposed} suggested anchors "
              f"across {len(emitted)} MSBs)")
        print("Inferred qualifiers are best-effort heuristic from source c-prefix "
              "breakdown; review during playtest. Anchors with empty `quals` need "
              "hand-labeling — `_provenance` carries the diagnostic context.")


if __name__ == '__main__':
    main()
