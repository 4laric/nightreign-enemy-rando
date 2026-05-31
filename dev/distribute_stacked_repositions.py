#!/usr/bin/env python3
"""distribute_stacked_repositions.py — Post-process slot_repositions.json
to spread N>=2 slots that collapsed to the same target XYZ.

PROBLEM:
build_slot_repositions.py sends each off-mesh slot to its nearest tight
navmesh leaf's CENTER. When N slots share the same nearest leaf, all N
get the same to_pos_center. A 4-pi cluster in a 1.77m leaf becomes 4
entities at one XYZ point — and if any are grounded humanoids, the
spawn-stack causes a freeze (seed 469032 m43_41 pi=8 Sanguine Noble).

SOLUTION:
For each stacking target, redistribute the N entries WITHIN the leaf's
bounding region, preserving the vanilla cluster shape (relative offsets
between members) where possible. Footprint-aware separation prevents
humanoid stacking.

ALGORITHM:
For each (msb, target_xyz_rounded) with >= 2 entries:

  1. Read leaf_extent (max XZ extent of the tight leaf).
  2. Compute the vanilla cluster centroid from `from_pos` values
     (excluding origin sentinels at (0,0,0)).
  3. For each entry, compute its vanilla offset from the centroid.
  4. Determine an XZ scale factor:
       usable_radius = leaf_extent/2 - SAFETY_BUFFER
       scale = min(1.0, usable_radius / max_vanilla_offset_xz)
  5. Project new offsets = vanilla_offsets * scale.
  6. Where vanilla offset is degenerate (origin sentinel, or zero
     offset from cluster), generate a deterministic fallback offset
     on a circular layout so the slot isn't co-located with another.
  7. New to_pos = leaf_center + (offset_x, 0, offset_z); Y is unchanged.

The transformation is conservative — when leaf can accommodate vanilla
spacing, vanilla layout is preserved exactly. When the leaf is too
small, layout is uniformly scaled down. Only degenerate origin entries
get synthesized offsets.

PASS 3 — mount/rider pair re-collapse (v0.26.14):
A mount and its rider are co-located in vanilla by design (the rider
sits on the mount). Passes 1 and 2 resolve every Part independently and
so split such pairs apart, leaving the rider standing beside the mount.
Pass 3 detects any mount/rider pair (both members in slot_repositions,
c-prefixes in RIDER_MOUNT_PAIRS, vanilla from_pos co-located) whose
resolved targets ended up apart, and moves the rider back onto the
mount's resolved position. It runs last so it also corrects pairs that
Pass 1 just distributed, and is idempotent.

OUTPUT:
For each modified entry:
  - `to_pos_center` / `to_pos_floor` updated
  - `manual_override` block added documenting:
      - original (pre-distribution) target
      - cluster shape that triggered redistribution
      - scale factor applied

The override block is also the audit trail — entries without it weren't
touched by this script.

USAGE:
    python distribute_stacked_repositions.py \\
        --input data/slot_repositions.json \\
        --output data/slot_repositions.json \\
        [--min-stack 2]  # only redistribute stacks of >= N (default 2)
        [--dry-run]      # report what would change without writing

Exit codes:
    0 — clean run, file written (or dry-run completed)
    1 — input file missing / malformed
    2 — no changes needed (no stacks found at min-stack threshold)
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict


SAFETY_BUFFER = 0.4   # meters of leaf-edge buffer (humanoid radius ~0.35)
ORIGIN_EPSILON = 0.01  # tolerance for treating from_pos as origin sentinel
SCRIPT_VERSION = 'distribute_stacked_repositions v3 (v0.26.14)'

# v0.24.37: non-repositioned-slot collision threshold. Two Parts within this
# XZ distance count as "colliding"; a reposition target that lands here is
# adjusted away from the non-repositioned slot.
NON_REPOS_COLLISION_THRESHOLD_M = 1.5

# Minimum shift magnitude when nudging a reposition target away from a
# non-repositioned slot collision. Just over the collision threshold so the
# new position clears the other Part with breathing room.
COLLISION_AVOIDANCE_NUDGE_M = 2.0

# v0.26.14: mount/rider pair preservation. A mount and its rider are
# co-located in vanilla BY DESIGN — the rider sits on the mount. The
# distribution passes above resolve every Part to its own offset, which
# splits such pairs: the rider ends up standing beside the mount instead
# of on it, and the engine's RIDER_MOUNT_PAIRS proximity collapse no
# longer recognizes them (confirmed: m60_42_38_10 c3170 Albinauric Archer
# + c3180 Wolf, split ~4m). Pass 3 re-collapses any split pair by moving
# the rider onto the mount's resolved position.
#
# Mirror of oops_v3.RIDER_MOUNT_PAIRS — each tuple is (rider_cp, mount_cp).
# Kept as a local copy so this dev tool stays import-light (no 14k-line
# engine import); tests/test_distribute_stacked_repositions.py asserts this
# list stays in sync with the engine's set.
RIDER_MOUNT_PAIRS = [
    ('c3170', 'c3180'),  # Albinauric Archer + Wolf
    ('c4050', 'c4060'),  # Kaiden Sellsword + Horse
    ('c4353', 'c4363'),  # Leyndell Knight + Lordsworn's Horse
    ('c3150', 'c3160'),  # Night's Cavalry + Funeral Steed
    ('c5840', 'c5890'),  # Black Knight + Black Knight Horse (v0.27.13 fabricated mounted pair)
]

# Two co-located entries are treated as a mounted pair only when their
# vanilla from_pos are within this distance — matches the engine's
# RIDER_MOUNT_PAIRS proximity-collapse threshold.
MOUNT_RIDER_PAIR_THRESHOLD_M = 2.0


def _is_origin(pos, eps=ORIGIN_EPSILON):
    """Origin sentinel: from_pos = (0,0,0) means the Part has no
    meaningful vanilla position (placeholder slot). These need a
    synthetic fallback offset."""
    return abs(pos[0]) < eps and abs(pos[1]) < eps and abs(pos[2]) < eps


def _xz_distance(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def _compute_centroid_xz(positions):
    """Centroid of positions, ignoring origin sentinels. Returns
    (cx, cz) or None if no usable positions."""
    real = [p for p in positions if not _is_origin(p)]
    if not real:
        return None
    cx = sum(p[0] for p in real) / len(real)
    cz = sum(p[2] for p in real) / len(real)
    return (cx, cz)


def distribute_stack(entries, leaf_extent, target_xz):
    """Compute new (x, z) offsets for each entry in the stack.

    entries: list of (pi_str, entry_dict). All have the same
        original to_pos_center but distinct from_pos.
    leaf_extent: float, max XZ extent of the tight leaf.
    target_xz: (cx, cz) — leaf center XZ. Y is preserved per entry.

    Returns: list of (pi_str, (new_x, new_z)). Order matches input.

    Strategy:
      - Honor vanilla layout when scale<=1 (preserves natural cluster
        shape — entities stand in roughly the same relative positions
        they had in vanilla).
      - Scale down if cluster wider than leaf.
      - Synthesize fallback positions on a circle for origin-sentinel
        entries.
    """
    n = len(entries)
    cx, cz = target_xz

    # Compute vanilla XZ offsets from cluster centroid
    vanilla_positions = [tuple(e['from_pos']) for _, e in entries]
    centroid = _compute_centroid_xz(vanilla_positions)
    usable_radius = (leaf_extent / 2.0) - SAFETY_BUFFER

    # Case A: usable_radius is too small for ANY separation. Fall back
    # to a tight circular layout — better than co-location.
    min_separation = 0.6  # ~1 humanoid hitbox + breathing room
    if usable_radius <= 0:
        usable_radius = min_separation * 0.5  # squeeze; won't fit perfectly but won't stack

    # Compute vanilla offsets (XZ) from centroid, falling back to None
    # for origin sentinels.
    vanilla_offsets_xz = []
    for pos in vanilla_positions:
        if _is_origin(pos) or centroid is None:
            vanilla_offsets_xz.append(None)
        else:
            vanilla_offsets_xz.append((pos[0] - centroid[0], pos[2] - centroid[1]))

    # Determine scale: ratio of usable_radius to max real-offset magnitude
    real_offsets = [o for o in vanilla_offsets_xz if o is not None]
    if real_offsets:
        max_real_mag = max(math.hypot(ox, oz) for ox, oz in real_offsets)
        if max_real_mag > 0:
            scale = min(1.0, usable_radius / max_real_mag)
        else:
            scale = 1.0
    else:
        scale = 1.0

    # For origin-sentinel entries, generate fallback positions on a
    # circle. Place them at radii that don't collide with real entries.
    # Determine angle slots that aren't occupied by real offsets:
    occupied_angles = []
    for o in vanilla_offsets_xz:
        if o is not None and (o[0]**2 + o[1]**2) > 1e-6:
            occupied_angles.append(math.atan2(o[1], o[0]))

    new_offsets = []
    fallback_idx = 0
    n_sentinels = sum(1 for o in vanilla_offsets_xz if o is None)
    # Spread sentinels around the angle-space, avoiding real-offset angles
    sentinel_radius = max(min_separation, usable_radius * 0.7)
    for vox in vanilla_offsets_xz:
        if vox is not None:
            new_offsets.append((vox[0] * scale, vox[1] * scale))
        else:
            # Synthesize a fallback angle. Spread N sentinels evenly,
            # offset by pi/2 from the most occupied direction (heuristic).
            if n_sentinels == 1:
                base_angle = math.pi  # opposite the origin reference if alone
            else:
                base_angle = (2 * math.pi * fallback_idx) / n_sentinels
            # If this angle collides with a real offset's angle, shift by π/(2N)
            adjusted_angle = base_angle
            for oa in occupied_angles:
                if abs((adjusted_angle - oa + math.pi) % (2 * math.pi) - math.pi) < math.pi / (2 * n):
                    adjusted_angle += math.pi / (2 * n)
            new_offsets.append((
                sentinel_radius * math.cos(adjusted_angle),
                sentinel_radius * math.sin(adjusted_angle),
            ))
            fallback_idx += 1

    # Last safety pass: ensure no two new_offsets are within min_separation
    # of each other. If they are, nudge the later one along the
    # perpendicular axis of the line between them.
    for i in range(len(new_offsets)):
        for j in range(i):
            dx = new_offsets[i][0] - new_offsets[j][0]
            dz = new_offsets[i][1] - new_offsets[j][1]
            d = math.hypot(dx, dz)
            if d < min_separation:
                # Push i away from j to min_separation
                if d < 1e-6:
                    # Degenerate (same offset) — pick a deterministic angle
                    angle = (math.pi / n) * i
                    dx, dz = math.cos(angle), math.sin(angle)
                    d = 1.0
                nx = new_offsets[j][0] + (dx / d) * min_separation
                nz = new_offsets[j][1] + (dz / d) * min_separation
                # Clamp back into leaf bounds
                nmag = math.hypot(nx, nz)
                if nmag > usable_radius:
                    nx *= usable_radius / nmag
                    nz *= usable_radius / nmag
                new_offsets[i] = (nx, nz)

    # Compose final results
    out = []
    for (pi_str, _), (ox, oz) in zip(entries, new_offsets):
        out.append((pi_str, (cx + ox, cz + oz)))
    return out


def find_stacks(rd, min_stack=2):
    """Return list of (msb, target_xyz, [(pi_str, entry), ...])
    for every target XYZ shared by min_stack+ entries."""
    stacks = []
    for msb, pis_dict in rd['proposals'].items():
        by_target = defaultdict(list)
        for pi_str, entry in pis_dict.items():
            # Skip entries that already have a manual_override
            # (someone took care of these manually; respect that).
            if entry.get('manual_override'):
                continue
            tp = entry.get('to_pos_center')
            if not tp:
                continue
            key = (round(tp[0], 2), round(tp[1], 2), round(tp[2], 2))
            by_target[key].append((pi_str, entry))
        for target_xyz, entries in by_target.items():
            if len(entries) >= min_stack:
                stacks.append((msb, target_xyz, entries))
    return stacks


def find_cross_msb_collisions(rd, all_part_positions, threshold_m=NON_REPOS_COLLISION_THRESHOLD_M):
    """v0.24.37: identify reposition targets that collide with non-
    repositioned slots in the same MSB.

    The original distribute_stacked_repositions pass only sees collisions
    WITHIN slot_repositions.json. It misses cases where a repositioned slot
    is moved into the vanilla position of another slot. The classic example
    (and the one this fix addresses) is m45_01 pi=5 — originally an origin-
    sentinel script-spawn placeholder. build_slot_repositions.py gave it a
    real position (2.55, 1.98, 5.78), which happens to be the vanilla
    position of m45_01 pi=2 (a different slot that's not in slot_repositions).
    Result: pi=2 and pi=5 stack at runtime.

    Returns list of (msb, pi_str, entry, colliding_with_pi, colliding_pos).
    Entries in the returned list need their to_pos_center nudged away from
    the colliding non-repositioned slot.

    all_part_positions: dict from nr_all_part_positions.json's `positions`
    key — maps msb name to {pi_str: [x, y, z]}.
    """
    collisions = []
    for msb, pis_dict in rd['proposals'].items():
        msb_positions = all_part_positions.get(msb, {})
        if not msb_positions:
            continue
        for pi_str, entry in pis_dict.items():
            tp = entry.get('to_pos_center')
            if not tp:
                continue
            # Check every OTHER slot in the same MSB
            for other_pi_str, other_pos in msb_positions.items():
                if other_pi_str == pi_str:
                    continue
                # Skip if the other slot is ALSO in slot_repositions
                # (those collisions are handled by find_stacks / its
                # cluster-shape logic). We only care about non-reposed
                # vs reposed collisions here.
                if other_pi_str in pis_dict:
                    continue
                # Skip origin sentinel — those are script-spawn placeholders
                # whose vanilla position is meaningless for collision.
                if _is_origin(other_pos):
                    continue
                d_xz = math.hypot(tp[0] - other_pos[0], tp[2] - other_pos[2])
                d_y = abs(tp[1] - other_pos[1])
                if d_xz < threshold_m and d_y < 3:
                    collisions.append({
                        'msb': msb,
                        'pi_str': pi_str,
                        'entry': entry,
                        'colliding_with_pi': other_pi_str,
                        'colliding_pos': list(other_pos),
                        'd_xz': d_xz,
                    })
    return collisions


def nudge_target_away_from(entry, other_pos, nudge_m=COLLISION_AVOIDANCE_NUDGE_M):
    """Compute a new to_pos_center that's `nudge_m` away from `other_pos`.

    Direction: away from other_pos along the XZ vector from `from_pos`
    toward to_pos_center (preserves intent of the original reposition).
    If from_pos is origin sentinel (no meaningful direction), nudges
    perpendicular to the to_pos→other_pos vector.

    Returns new (x, y, z) tuple — Y preserved from entry's current
    to_pos_center.
    """
    tp = entry['to_pos_center']
    fp = entry.get('from_pos', [0, 0, 0])

    # Direction we'd LIKE to preserve: from_pos → to_pos_center
    intent_x = tp[0] - fp[0]
    intent_z = tp[2] - fp[2]
    intent_mag = math.hypot(intent_x, intent_z)

    # The "away from other" direction
    away_x = tp[0] - other_pos[0]
    away_z = tp[2] - other_pos[2]
    away_mag = math.hypot(away_x, away_z)

    if away_mag < 1e-3:
        # Effectively at the same point — pick an arbitrary perpendicular
        # direction. Use intent direction's perpendicular if available, else
        # default east (+x).
        if intent_mag > 1e-3:
            away_x = -intent_z / intent_mag
            away_z = intent_x / intent_mag
        else:
            away_x = 1.0
            away_z = 0.0
        away_mag = 1.0

    # New position: shift `nudge_m` away from other_pos along the away vector,
    # starting from other_pos (so we end up exactly nudge_m away).
    nx = other_pos[0] + (away_x / away_mag) * nudge_m
    nz = other_pos[2] + (away_z / away_mag) * nudge_m

    return (round(nx, 3), round(tp[1], 3), round(nz, 3))


def _dist3(a, b):
    """3D Euclidean distance between two [x, y, z] points."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                     + (a[2] - b[2]) ** 2)


def _mount_rider_pair_of(cp1, cp2):
    """If c-prefixes cp1/cp2 form a RIDER_MOUNT_PAIRS entry, return the
    (rider_cp, mount_cp) tuple; otherwise None. cp1 == cp2 never pairs."""
    pair = {cp1, cp2}
    for rider, mount in RIDER_MOUNT_PAIRS:
        if pair == {rider, mount}:
            return (rider, mount)
    return None


def find_mount_rider_splits(rd, threshold=MOUNT_RIDER_PAIR_THRESHOLD_M):
    """v0.26.14: find mount/rider pairs whose two reposition entries were
    split apart by the distribution passes.

    A pair = two proposal entries in the same MSB whose `src` c-prefixes
    form a RIDER_MOUNT_PAIRS entry and whose vanilla `from_pos` are
    co-located (within `threshold` — the same proximity the engine uses
    to recognize a mounted pair). A *split* = their resolved
    `to_pos_center` ended up `threshold` or more apart, so the engine's
    RIDER_MOUNT_PAIRS collapse will no longer pair them.

    Returns a list of dicts: {msb, rider_pi, rider_e, mount_pi, mount_e,
    d_xz}. The repair is to move the rider onto the mount's to_pos.

    Note: this detects pairs where BOTH members have reposition entries.
    A pair where only one member was repositioned (moving it away from a
    stationary partner) is a separate case, not handled here — see
    docs/TODO.md.
    """
    splits = []
    for msb, pis_dict in rd.get('proposals', {}).items():
        items = list(pis_dict.items())
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                pi_a, e_a = items[a]
                pi_b, e_b = items[b]
                pair = _mount_rider_pair_of(e_a.get('src'), e_b.get('src'))
                if pair is None:
                    continue
                fa, fb = e_a.get('from_pos'), e_b.get('from_pos')
                ta, tb = e_a.get('to_pos_center'), e_b.get('to_pos_center')
                if not (fa and fb and ta and tb):
                    continue
                # Genuine mounted pair only: co-located in vanilla.
                if _dist3(fa, fb) >= threshold:
                    continue
                # Already together post-distribution — nothing to repair.
                if _dist3(ta, tb) < threshold:
                    continue
                rider_cp, mount_cp = pair
                if e_a.get('src') == mount_cp:
                    mount_pi, mount_e, rider_pi, rider_e = pi_a, e_a, pi_b, e_b
                else:
                    mount_pi, mount_e, rider_pi, rider_e = pi_b, e_b, pi_a, e_a
                splits.append({
                    'msb': msb,
                    'rider_pi': rider_pi, 'rider_e': rider_e,
                    'mount_pi': mount_pi, 'mount_e': mount_e,
                    'd_xz': _xz_distance(ta, tb),
                })
    return splits


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',  default='data/slot_repositions.json')
    p.add_argument('--output', default='data/slot_repositions.json')
    p.add_argument('--min-stack', type=int, default=2)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--part-positions', default='data/nr_all_part_positions.json',
                   help='Path to nr_all_part_positions.json for cross-MSB '
                        'collision detection (v0.24.37). Pass an empty string '
                        'to skip the cross-collision pass.')
    args = p.parse_args()

    if not os.path.isfile(args.input):
        print(f'ERROR: input file not found: {args.input}', file=sys.stderr)
        return 1

    try:
        with open(args.input, encoding='utf-8') as f:
            rd = json.load(f)
    except json.JSONDecodeError as e:
        print(f'ERROR: malformed JSON in {args.input}: {e}', file=sys.stderr)
        return 1

    # --- Pass 1: existing in-list stacking ----------------------------------
    stacks = find_stacks(rd, min_stack=args.min_stack)
    print(f'PASS 1: in-list stacks (size >= {args.min_stack}): {len(stacks)}')
    print()

    changes_per_msb = defaultdict(int)
    total_entries_modified = 0

    for msb, target_xyz, entries in stacks:
        cx, _, cz = target_xyz
        # Use leaf_extent from the first entry (they all share the same
        # target leaf, so they should agree).
        leaf_extents = {e.get('leaf_extent') for _, e in entries}
        leaf_extents.discard(None)
        if not leaf_extents:
            print(f'  SKIP {msb} @ {target_xyz}: no leaf_extent data')
            continue
        # Use min leaf_extent for safety (smallest reported region)
        leaf_extent = min(leaf_extents)

        # Distribute
        new_positions = distribute_stack(entries, leaf_extent, (cx, cz))

        # Build the override description once for this stack
        member_pis = sorted(int(pi) for pi, _ in entries)
        cluster_desc = (
            f'{len(entries)} entries collapsed to leaf center '
            f'{tuple(target_xyz)} by build_slot_repositions.py; '
            f'redistributed across leaf_extent={leaf_extent:.2f}m '
            f'preserving vanilla cluster shape. Cluster member pis: '
            f'{member_pis}.'
        )

        print(f'  {msb} @ {target_xyz} (n={len(entries)}, leaf_extent={leaf_extent:.2f}):')
        for (pi_str, entry), (_, (new_x, new_z)) in zip(entries, new_positions):
            old_xz = (entry['to_pos_center'][0], entry['to_pos_center'][2])
            new_y = entry['to_pos_floor'][1]
            print(f'    pi={pi_str}: ({old_xz[0]:.2f}, _, {old_xz[1]:.2f}) -> '
                  f'({new_x:.2f}, _, {new_z:.2f})  '
                  f'(shift {math.hypot(new_x - old_xz[0], new_z - old_xz[1]):.2f}m)')
            if not args.dry_run:
                entry['to_pos_center'] = [round(new_x, 3),
                                           round(entry['to_pos_center'][1], 3),
                                           round(new_z, 3)]
                entry['to_pos_floor']  = [round(new_x, 3),
                                           round(new_y, 3),
                                           round(new_z, 3)]
                entry['manual_override'] = {
                    'reason': 'stacking_redistribution',
                    'description': cluster_desc,
                    'cluster_member_pis': member_pis,
                    'pre_distribution_target': list(target_xyz),
                    'overridden_by': SCRIPT_VERSION,
                }
                total_entries_modified += 1
                changes_per_msb[msb] += 1

    if args.dry_run:
        print(f'\nDRY RUN (Pass 1): would modify '
              f'{sum(len(e) for _, _, e in stacks)} entries '
              f'across {len(changes_per_msb)} MSBs')

    # --- Pass 2: cross-collision against non-repositioned slots (v0.24.37) --
    print()
    print('=' * 70)
    pass2_modifications = 0
    if args.part_positions and os.path.isfile(args.part_positions):
        try:
            with open(args.part_positions) as f:
                positions_data = json.load(f)
            all_part_positions = positions_data.get('positions', {})
        except Exception as e:
            print(f'WARN: could not load part positions ({e}). Skipping Pass 2.',
                  file=sys.stderr)
            all_part_positions = {}
    elif args.part_positions:
        print(f'WARN: --part-positions={args.part_positions} not found. '
              f'Skipping Pass 2 (cross-collision detection). Run '
              f'dev/build_part_positions.py first.', file=sys.stderr)
        all_part_positions = {}
    else:
        all_part_positions = {}

    if all_part_positions:
        collisions = find_cross_msb_collisions(rd, all_part_positions)
        print(f'PASS 2: cross-collisions vs non-repositioned slots: '
              f'{len(collisions)}')
        if collisions:
            print()
            for c in collisions:
                tp = c['entry']['to_pos_center']
                new_pos = nudge_target_away_from(c['entry'], c['colliding_pos'])
                print(f'  {c["msb"]} pi={c["pi_str"]}: '
                      f'to_pos {tp} collides with pi={c["colliding_with_pi"]} '
                      f'(d_xz={c["d_xz"]:.3f}m) — nudge to {list(new_pos)}')
                if not args.dry_run:
                    entry = c['entry']
                    # Preserve existing manual_override if any (in case
                    # Pass 1 already set one). Stack the cross-collision
                    # context onto a new field.
                    pre_target = list(entry['to_pos_center'])
                    entry['to_pos_center'] = [new_pos[0], new_pos[1], new_pos[2]]
                    # Preserve floor Y but adopt new X/Z
                    old_floor_y = entry.get('to_pos_floor', new_pos)[1]
                    entry['to_pos_floor'] = [new_pos[0], old_floor_y, new_pos[2]]
                    # Override block — replace or merge
                    existing = entry.get('manual_override') or {}
                    cross_block = {
                        'reason': 'cross_collision_nudge',
                        'description': (
                            f'to_pos_center collided with non-repositioned '
                            f'slot pi={c["colliding_with_pi"]} at vanilla '
                            f'pos {c["colliding_pos"]} (d_xz={c["d_xz"]:.3f}m < '
                            f'{NON_REPOS_COLLISION_THRESHOLD_M}m threshold). '
                            f'Nudged {COLLISION_AVOIDANCE_NUDGE_M}m away.'
                        ),
                        'pre_nudge_target': pre_target,
                        'collision_pi': c['colliding_with_pi'],
                        'collision_pos': c['colliding_pos'],
                        'collision_distance_xz': round(c['d_xz'], 3),
                        'overridden_by': SCRIPT_VERSION,
                    }
                    if existing:
                        # Pass 1 already overrode this; nest the new info.
                        existing.setdefault('cross_collision_passes', [])\
                            .append(cross_block)
                    else:
                        # Fresh override for this entry.
                        entry['manual_override'] = cross_block
                    pass2_modifications += 1
                    changes_per_msb[c['msb']] += 1
                    total_entries_modified += 1
    else:
        print('PASS 2: skipped (no part-positions data).')

    # --- Pass 3: mount/rider pair re-collapse (v0.26.14) --------------------
    # Passes 1 and 2 resolve each Part independently, which splits co-located
    # mount/rider pairs. Re-collapse any such split by moving the rider onto
    # the mount's resolved position. Runs last so it also corrects pairs that
    # Pass 1 just distributed; idempotent (a re-collapsed pair has identical
    # to_pos and is skipped on a subsequent run).
    print()
    print('=' * 70)
    splits = find_mount_rider_splits(rd)
    print(f'PASS 3: split mount/rider pairs: {len(splits)}')
    pass3_modifications = 0
    if splits:
        print()
        for s in splits:
            mount_e = s['mount_e']
            rider_e = s['rider_e']
            mount_tc = mount_e['to_pos_center']
            mount_tf = mount_e.get('to_pos_floor', mount_tc)
            pre_target = list(rider_e['to_pos_center'])
            print(f'  {s["msb"]} rider pi={s["rider_pi"]} '
                  f'({rider_e.get("src")}): split {s["d_xz"]:.2f}m from mount '
                  f'pi={s["mount_pi"]} ({mount_e.get("src")}) — '
                  f'recollapse onto mount at {mount_tc}')
            if not args.dry_run:
                rider_e['to_pos_center'] = [round(mount_tc[0], 3),
                                            round(mount_tc[1], 3),
                                            round(mount_tc[2], 3)]
                rider_e['to_pos_floor'] = [round(mount_tf[0], 3),
                                           round(mount_tf[1], 3),
                                           round(mount_tf[2], 3)]
                recollapse_block = {
                    'reason': 'mount_rider_pair_recollapse',
                    'description': (
                        f'rider was split {s["d_xz"]:.2f}m from its mount '
                        f'pi={s["mount_pi"]} ({mount_e.get("src")}) by the '
                        f'distribution passes. Mount and rider are co-located '
                        f'in vanilla by design; moved the rider onto the '
                        f"mount's resolved position so the engine's "
                        f'RIDER_MOUNT_PAIRS collapse still pairs them.'
                    ),
                    'pre_recollapse_target': pre_target,
                    'mount_pi': s['mount_pi'],
                    'overridden_by': SCRIPT_VERSION,
                }
                existing = rider_e.get('manual_override') or {}
                if existing:
                    # Pass 1 / Pass 2 already overrode this entry; nest.
                    existing.setdefault('mount_rider_recollapse_passes', [])\
                        .append(recollapse_block)
                else:
                    rider_e['manual_override'] = recollapse_block
                pass3_modifications += 1
                changes_per_msb[s['msb']] += 1
                total_entries_modified += 1
    else:
        print('PASS 3: no split mount/rider pairs found.')

    if args.dry_run:
        print(f'\nDRY RUN: would modify {total_entries_modified} entries total '
              f'across {len(changes_per_msb)} MSBs')
        return 0

    if total_entries_modified == 0:
        print(f'\nNo modifications needed.')
        return 2

    # Update metadata
    md = rd.setdefault('metadata', {})
    md.setdefault('post_processing', []).append({
        'tool': SCRIPT_VERSION,
        'stacks_redistributed': len(stacks),
        'cross_collisions_nudged': pass2_modifications,
        'mount_rider_pairs_recollapsed': pass3_modifications,
        'entries_modified': total_entries_modified,
        'safety_buffer': SAFETY_BUFFER,
        'non_repos_collision_threshold_m': NON_REPOS_COLLISION_THRESHOLD_M,
    })

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(rd, f, indent=2)

    print(f'\nWrote {args.output}')
    print(f'  Modified {total_entries_modified} entries across {len(changes_per_msb)} MSBs')
    return 0


if __name__ == '__main__':
    sys.exit(main())
