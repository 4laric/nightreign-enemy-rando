#!/usr/bin/env python3
"""apply_slot_repositions.py — Apply slot_repositions.json to vanilla MSBs.

Read-and-modify tool. For each (msb, pi, to_pos) in slot_repositions.json,
locate Part pi's position field at offset 0x400, verify the existing bytes
match the recorded from_pos (sanity check), and substitute the new position
bytes in place. Preserves all other MSB content — the same in-place-byte-sub
discipline used elsewhere in the pipeline.

WHAT THIS DOES IN GAMEPLAY TERMS:
Vanilla NR has many enemy slots placed off the navmesh (BVH classified
'off_mesh' or 'proximity_off_mesh' by build_slot_terrain.py). Enemies at
these slots can't path, leading to frozen mobs in oops-all runs and reduced
encounter density everywhere. This tool moves each off-mesh slot to the
center of the nearest tight navmesh leaf, making the slot walkable so the
shuffle can place randomized enemies there without breaking them.

VERIFICATION:
Before writing, verifies the in-MSB position matches from_pos with float-
tolerance 0.1u. Mismatch means slot_terrain.json was generated against
different MSB binaries — abort that pi rather than write to the wrong slot.

POSITION FIELD CHOICE:
Default writes to_pos_center (leaf AABB midpoint). --use-floor switches
to to_pos_floor (center XZ, AABB min Y) for slots where the center Y is
suspected to float above the actual walkable surface. In tight leaves
(<10u extent) the two are within ~5u of each other and gravity settles
the spawn either way; in loose leaves (30-50u) the difference matters.

USAGE:
    # Apply to all maps in the reposition file
    python apply_slot_repositions.py \\
        --repositions data/slot_repositions.json \\
        --in-dir  vanilla_decompiled_msbs/ \\
        --out-dir relocated_msbs/

    # Apply to only specific maps (castle tile test)
    python apply_slot_repositions.py \\
        --repositions data/slot_repositions.json \\
        --in-dir  vanilla_decompiled_msbs/ \\
        --out-dir relocated_msbs/ \\
        --only m60_43_37_00.msb m60_43_37_10.msb m60_43_37_20.msb m60_43_37_50.msb \\
               m60_44_37_00.msb m60_44_37_20.msb m60_44_37_30.msb

OUTPUT:
- Modified .msb files in --out-dir
- Summary report to stdout: per-map success/fail counts
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from oops_all_anyone import parse_msb_sections

# Position field offset within an Enemy Part. Confirmed empirically against
# slot_terrain.json: reads (-70.54, 180.85, -25.87) for m60_43_39_00 pi=23,
# which matches the vanilla c4300 Wandering Noble in that slot.
# Constant also defined in oops_all_anyone.py.
PART_OFF_POSITION = 0x400
POSITION_FIELD_LEN = 12  # 3 * float32

# Tolerance (in world units) for verifying vanilla position before writing.
# slot_terrain.json rounds positions to ~2 decimal places in some maps,
# so 0.1u is generous enough to absorb rounding without admitting mismatches.
POSITION_VERIFY_TOLERANCE = 0.1


def relocate_one_msb(in_path, out_path, msb_repositions, use_floor=False, dry_run=False):
    """Apply repositions to one MSB. Returns dict with per-MSB stats."""
    data = open(in_path, 'rb').read()
    sections = parse_msb_sections(data)
    try:
        parts_sec = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    except StopIteration:
        return {'error': 'no PARTS_PARAM_ST', 'n_written': 0, 'n_attempted': 0}

    new_data = bytearray(data)
    n_attempted = 0
    n_written = 0
    failures = []

    for pi_str, r in msb_repositions.items():
        pi = int(pi_str)
        n_attempted += 1
        if pi >= len(parts_sec['entry_offsets']):
            failures.append({'pi': pi, 'reason': 'pi_out_of_range',
                             'msb_part_count': len(parts_sec['entry_offsets'])})
            continue
        po = parts_sec['entry_offsets'][pi]
        if po + PART_OFF_POSITION + POSITION_FIELD_LEN > len(data):
            failures.append({'pi': pi, 'reason': 'part_too_short_for_position_field'})
            continue

        # Verify vanilla position bytes match what slot_terrain.json recorded.
        # This catches MSB-version drift (slot_terrain built against one
        # binary, surgery attempted on another).
        cur_x, cur_y, cur_z = struct.unpack_from('<fff', data, po + PART_OFF_POSITION)
        from_x, from_y, from_z = r['from_pos']
        dx, dy, dz = cur_x - from_x, cur_y - from_y, cur_z - from_z
        if max(abs(dx), abs(dy), abs(dz)) > POSITION_VERIFY_TOLERANCE:
            failures.append({
                'pi': pi, 'reason': 'vanilla_position_mismatch',
                'expected': r['from_pos'],
                'actual':  [cur_x, cur_y, cur_z],
            })
            continue

        # Write the new position. Default is to_pos_center; --use-floor
        # gives to_pos_floor (center XZ + AABB min-Y) for steep terrain.
        target = r['to_pos_floor'] if use_floor else r['to_pos_center']
        new_bytes = struct.pack('<fff', *target)
        if not dry_run:
            new_data[po + PART_OFF_POSITION:po + PART_OFF_POSITION + POSITION_FIELD_LEN] = new_bytes
        n_written += 1

    if not dry_run:
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        with open(out_path, 'wb') as f:
            f.write(bytes(new_data))

    return {
        'n_attempted': n_attempted,
        'n_written':   n_written,
        'failures':    failures,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repositions', required=True,
                    help='slot_repositions.json from build_slot_repositions.py')
    ap.add_argument('--in-dir', required=True,
                    help='Directory of vanilla decompiled .msb files')
    ap.add_argument('--out-dir', required=True,
                    help='Output dir for relocated .msb files')
    ap.add_argument('--only', nargs='*', default=None,
                    help='Only process these MSB filenames (default: all)')
    ap.add_argument('--use-floor', action='store_true',
                    help='Use to_pos_floor instead of to_pos_center')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--verbose', action='store_true',
                    help='Print failure details per MSB')
    args = ap.parse_args()

    rp = json.load(open(args.repositions))
    proposals = rp['proposals']
    print(f'Loaded {len(proposals)} maps from {args.repositions}')
    print(f'Position target: {"to_pos_floor" if args.use_floor else "to_pos_center"}')
    if args.dry_run:
        print('DRY RUN — no files will be written')
    print()

    target_maps = sorted(proposals)
    if args.only:
        target_maps = [m for m in target_maps if m in set(args.only)]
        print(f'Filtered to {len(target_maps)} maps via --only')

    total_attempted = 0
    total_written = 0
    total_failed = 0
    failure_reasons = {}

    for msb in target_maps:
        in_path = os.path.join(args.in_dir, msb)
        out_path = os.path.join(args.out_dir, msb)
        if not os.path.exists(in_path):
            print(f'  {msb}: SOURCE MISSING ({in_path})')
            continue
        result = relocate_one_msb(in_path, out_path, proposals[msb],
                                   use_floor=args.use_floor, dry_run=args.dry_run)
        if 'error' in result:
            print(f'  {msb}: ERROR {result["error"]}')
            continue
        total_attempted += result['n_attempted']
        total_written += result['n_written']
        n_failed = len(result['failures'])
        total_failed += n_failed
        for f in result['failures']:
            failure_reasons.setdefault(f['reason'], 0)
            failure_reasons[f['reason']] += 1

        status = 'OK' if n_failed == 0 else f'{n_failed} failed'
        print(f'  {msb}: {result["n_written"]}/{result["n_attempted"]} relocated  [{status}]')
        if args.verbose and result['failures']:
            for f in result['failures']:
                print(f'    pi={f["pi"]}: {f["reason"]} {f}')

    print()
    print(f'Total: {total_written}/{total_attempted} relocations written '
          f'across {len(target_maps)} maps')
    if total_failed:
        print(f'Failures: {total_failed}')
        for reason, n in failure_reasons.items():
            print(f'  {reason}: {n}')


if __name__ == '__main__':
    main()