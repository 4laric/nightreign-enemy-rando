#!/usr/bin/env python3
"""
rewrite_walk_routes.py — randomize procedural-spawn walk_route events.

NR's procedural Limveld engine spawns chrs at runtime by reading
EVENT_PARAM_ST entries whose name matches `walk_route_cXXXX_NNNN_MM`,
where cXXXX is the c-prefix the engine spawns, NNNN is the expedition
pattern ID (9000=Default, 9001=Mountaintops, 9008=Crater, etc.), and
MM is the route ID. These events are NOT MSB Parts — they spawn from
chrbnd resources independently of any Part swap the rando makes.

This pass rewrites the c-prefix in walk_route event names so the
procedural engine spawns randomized chrs instead of vanilla. Pure
in-place byte substitution: the c-prefix is always 5 chars (cXXXX), so
swapping cXXXX→cYYYY preserves byte length and all MSB offsets stay
valid. EMEVD scripts don't reference walk_route names (verified across
197 EMEVD files), so renaming is side-effect-free.

Investigation findings (v0.23.76):
- 554 walk_route events corpus-wide across 64 distinct c-prefixes
- ~74% in m60_xx Limveld tiles, rest in static maps (m32_10, m34_xx,
  m38_xx, m46_xx, m47_xx, m48_xx, m49_xx)
- Pattern IDs gate by expedition: 9000=Default (always), 9001-9039=
  expedition-specific
- 10 names have Japanese `（自由巡回）` ("free patrol") or `[old]`
  suffix tails — c-prefix is still at the same byte offset, rename works
- Zero NPC param refs in type-data (c-prefix is only in the name)

CLI:
    # Dry-run report only, no writes:
    python3 rewrite_walk_routes.py --in-dir vanilla_msbs --seed 42 --dry-run

    # Rewrite, output to new dir:
    python3 rewrite_walk_routes.py --in-dir vanilla_msbs \\
                                   --out-dir shuffled_msbs --seed 42
"""

from __future__ import annotations
import os
import sys
import struct
import random
import argparse
import json
import re
from collections import Counter, defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from oops_all_anyone import parse_msb_sections


# Built from empirical corpus scan of all 300 NR vanilla MSBs (v0.23.76).
# These are the c-prefixes NR's procedural engine is known to spawn via
# walk_route. Restricting target picks to this set guarantees the target
# c-prefix is engine-preloadable for any tile that already had a walk_route
# (since SOME tile in the corpus uses it).
#
# Regenerate via: dev/scan_walk_route_prefixes.py (corpus scan).
SAFE_WALK_ROUTE_TARGETS = frozenset({
    'c0100', 'c2041', 'c2140', 'c2500', 'c3000', 'c3010', 'c3020', 'c3060',
    'c3080', 'c3170', 'c3181', 'c3251', 'c3451', 'c3471', 'c3500', 'c3661',
    'c3662', 'c3664', 'c3700', 'c3702', 'c3703', 'c3704', 'c3810', 'c3850',
    'c3900', 'c3910', 'c3970', 'c4050', 'c4070', 'c4090', 'c4100', 'c4110',
    'c4120', 'c4161', 'c4166', 'c4180', 'c4191', 'c4200', 'c4241', 'c4300',
    'c4310', 'c4311', 'c4313', 'c4314', 'c4315', 'c4321', 'c4340', 'c4351',
    'c4355', 'c4371', 'c4375', 'c4377', 'c4381', 'c4450', 'c4460', 'c4490',
    'c4505', 'c4570', 'c4600', 'c4680', 'c4770', 'c5011', 'c7000', 'c7100',
})

# c-prefixes that should NOT be picked as walk_route targets even though
# they're in the SAFE pool. Player templates and projectiles don't make
# sense procedurally spawned at random patrol points.
WALK_ROUTE_TARGET_EXCLUDES = frozenset({
    'c0000', 'c0100', 'c0110', 'c0120',  # player nightfarer templates
    'c1000',                              # standin
    'c2150',                              # Lightning Ball projectile
    'c2070',                              # bonfire dummy
})

# Offset of 'c' in the c-prefix within the UTF-16LE name string.
# 'walk_route_' is 11 ASCII chars = 22 bytes in UTF-16LE.
CPREFIX_BYTE_OFFSET_IN_NAME = 22
CPREFIX_BYTE_LEN = 10  # 5 chars × 2 bytes

WALK_ROUTE_NAME_RE = re.compile(r'^walk_route_(c\d{4})_')


def read_utf16le_z(data: bytes, off: int) -> str:
    end = off
    while end + 1 < len(data) and not (data[end] == 0 and data[end+1] == 0):
        end += 2
    try:
        return data[off:end].decode('utf-16-le', errors='replace')
    except Exception:
        return ''


def _uniform_target_picker(target_pool):
    """Default uniform-random picker over the static SAFE_WALK_ROUTE_TARGETS.

    Used for the standalone CLI (dry-run, debugging). The dcx_batch pipeline
    passes a smarter picker that wraps oops_v3.pick_target_cp for tier-aware
    grunt-pool targets that respect the rando's excludes and caps.
    """
    pool_minus_excludes = [cp for cp in target_pool
                           if cp not in WALK_ROUTE_TARGET_EXCLUDES]
    def pick(source_cp: str, rng: random.Random,
             slot_msb_name: str = None) -> str:
        candidate = [cp for cp in pool_minus_excludes if cp != source_cp]
        if not candidate:
            return None
        return rng.choice(candidate)
    return pick


def rewrite_one_msb(in_path: str, out_path: str, rng: random.Random,
                    pick_target_fn=None, target_pool=None,
                    dry_run: bool = False) -> dict:
    """Rewrite walk_route c-prefixes in one MSB.

    `pick_target_fn` is a callable `(source_cp, rng, slot_msb_name=None) ->
    target_cp` that chooses what to swap each walk_route's c-prefix to.
    If None, falls back to uniform random over `target_pool` (which itself
    falls back to SAFE_WALK_ROUTE_TARGETS). The dcx_batch pipeline supplies
    a picker that wraps oops_v3.pick_target_cp so walk_routes get tier-
    aware grunt-pool targets that respect the rando's excludes and caps.

    Returns a dict with per-MSB stats + rename log.
    """
    if pick_target_fn is None:
        pool = sorted(target_pool or SAFE_WALK_ROUTE_TARGETS)
        pick_target_fn = _uniform_target_picker(pool)
    msb_basename = os.path.basename(in_path)

    data = open(in_path, 'rb').read()
    sections = parse_msb_sections(data)
    try:
        events_sec = next(s for s in sections if s['name'] == 'EVENT_PARAM_ST')
    except StopIteration:
        return {'n_walk_routes': 0, 'n_renamed': 0, 'renames': [],
                'error': 'no EVENT_PARAM_ST'}

    new_data = bytearray(data)
    rename_log = []
    n_walk_routes = 0

    for ei, eo in enumerate(events_sec['entry_offsets']):
        try:
            name_off = struct.unpack_from('<q', data, eo)[0]
        except struct.error:
            continue
        if not (0 < name_off < len(data) - 32):
            continue
        name = read_utf16le_z(data, eo + name_off)
        m = WALK_ROUTE_NAME_RE.match(name)
        if not m:
            continue
        n_walk_routes += 1
        source_cp = m.group(1)

        # Pick a target c-prefix. The picker can occasionally return a
        # 6-char heritage import (c52313 etc.) that won't fit the 5-char
        # walk_route name slot — retry a few times before giving up.
        # In practice 5-char targets are >>10x more common, so the retry
        # almost always succeeds on the second attempt.
        target_cp = None
        for _attempt in range(10):
            candidate = pick_target_fn(source_cp, rng, slot_msb_name=msb_basename)
            if candidate is None or candidate == source_cp:
                continue
            if len(candidate.encode('utf-16-le')) == CPREFIX_BYTE_LEN:
                target_cp = candidate
                break
        if target_cp is None:
            rename_log.append({
                'event_idx': ei, 'source': source_cp, 'target': None,
                'skipped_reason': 'no_valid_5char_target_in_10_retries',
                'name': name,
            })
            continue

        # Verify what's actually at the target byte position matches source_cp.
        # Belt-and-suspenders: defends against name layouts I don't know about.
        cprefix_abs = eo + name_off + CPREFIX_BYTE_OFFSET_IN_NAME
        existing_bytes = bytes(new_data[cprefix_abs:cprefix_abs + CPREFIX_BYTE_LEN])
        expected_bytes = source_cp.encode('utf-16-le')
        if existing_bytes != expected_bytes:
            rename_log.append({
                'event_idx': ei, 'source': source_cp, 'target': None,
                'skipped_reason': 'byte_mismatch',
                'expected': expected_bytes.hex(), 'found': existing_bytes.hex(),
                'name': name,
            })
            continue

        # Belt-and-suspenders: defends against name layouts we don't know about.
        target_bytes = target_cp.encode('utf-16-le')
        if not dry_run:
            new_data[cprefix_abs:cprefix_abs + CPREFIX_BYTE_LEN] = target_bytes
        rename_log.append({
            'event_idx': ei, 'source': source_cp, 'target': target_cp,
            'original_name': name,
        })

    if not dry_run:
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        with open(out_path, 'wb') as f:
            f.write(bytes(new_data))

    n_renamed = sum(1 for r in rename_log if r.get('target'))
    return {
        'n_walk_routes': n_walk_routes,
        'n_renamed': n_renamed,
        'renames': rename_log,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--in-dir', required=True,
                    help='Directory of decompressed vanilla *.msb files.')
    ap.add_argument('--out-dir', default=None,
                    help='Directory to write rewritten MSBs. Required unless --dry-run.')
    ap.add_argument('--seed', type=int, default=0,
                    help='RNG seed for deterministic output.')
    ap.add_argument('--dry-run', action='store_true',
                    help='Report rename plan without writing files.')
    ap.add_argument('--report', default=None,
                    help='Write per-MSB rename plan to JSON.')
    ap.add_argument('--only', nargs='+', default=None,
                    help='Restrict to specific MSB filenames.')
    args = ap.parse_args()

    if not args.dry_run and not args.out_dir:
        sys.exit('--out-dir is required unless --dry-run')
    if not os.path.isdir(args.in_dir):
        sys.exit(f'in-dir not found: {args.in_dir}')

    rng = random.Random(args.seed)
    target_pool = sorted(SAFE_WALK_ROUTE_TARGETS - WALK_ROUTE_TARGET_EXCLUDES)
    pick_fn = _uniform_target_picker(target_pool)

    print(f"Walk-route rewrite pass")
    print(f"  seed={args.seed}")
    print(f"  picker: uniform-random over SAFE_WALK_ROUTE_TARGETS")
    print(f"  target pool size: {len(target_pool)}")
    print(f"  dry_run={args.dry_run}")
    print()

    total_walk = 0
    total_renamed = 0
    msbs_touched = 0
    full_log = {}

    for fn in sorted(os.listdir(args.in_dir)):
        if not fn.endswith('.msb'):
            continue
        if args.only and fn not in args.only:
            continue
        in_path = os.path.join(args.in_dir, fn)
        out_path = os.path.join(args.out_dir, fn) if args.out_dir else None
        # Each MSB gets a distinct sub-RNG so file ordering doesn't affect
        # per-file randomization (deterministic but order-independent).
        sub_rng = random.Random(f'{args.seed}:{fn}')
        result = rewrite_one_msb(in_path, out_path or '/dev/null',
                                  sub_rng, pick_target_fn=pick_fn,
                                  dry_run=args.dry_run or out_path is None)
        if result['n_walk_routes'] == 0:
            continue
        total_walk += result['n_walk_routes']
        total_renamed += result['n_renamed']
        if result['n_renamed'] > 0:
            msbs_touched += 1
        full_log[fn] = result

    print(f"Summary:")
    print(f"  MSBs with walk_routes: {len(full_log)}")
    print(f"  MSBs touched: {msbs_touched}")
    print(f"  Total walk_route events seen: {total_walk}")
    print(f"  Total renamed: {total_renamed}")

    if args.report:
        os.makedirs(os.path.dirname(args.report) or '.', exist_ok=True)
        with open(args.report, 'w', encoding='utf-8') as f:
            json.dump(full_log, f, indent=2)
        print(f"\nFull rename log written to: {args.report}")


if __name__ == '__main__':
    main()
