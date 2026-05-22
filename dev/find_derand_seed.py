#!/usr/bin/env python3
"""find_derand_seed.py — pair targets from the validator manifest with
derand seed/pattern guidance for in-game testing.

This script is a thin wrapper around thefifthmatt's NR Randomizer +
Derandomizer mod (Nexus 277). It does NOT simulate the seed→pattern
function — that lives in NightreignRandomizer.exe, which we can't run
out-of-band. What it DOES do:

1. Maps each target MSB to the Shifting Earth (or none) that contains it,
   based on NR's MSB-prefix conventions.
2. Maps Nightlord + Shifting Earth to the contiguous pattern-ID range
   that thefifthmatt's site documents. Tells you which patterns in the
   derandomizer GUI's reroller to filter for.
3. Caches (nightlord, pattern_id) → seed observations to `dev/
   derand_observations.json` so a known-good seed is suggested directly
   on subsequent runs.

Usage:
  python dev/find_derand_seed.py --target-msb m60_42_36_50.msb
  python dev/find_derand_seed.py --manifest /tmp/multi_v086_audit.json \\
      --plan
  python dev/find_derand_seed.py --record \\
      --seed 522250 --nightlord adel --pattern-id 67 \\
      --visited-msb m60_42_36_50.msb --visited-msb m60_43_37_10.msb

Workflow:
  - Pick a target placement from the validator's manifest
  - Run with --target-msb to find which (nightlord, pattern-range) to
    select in the derandomizer GUI
  - Use the GUI's reroller to find a seed in that pattern range
  - Run the expedition; while playing, note which MSBs you traversed
  - When done, --record back the observation. Future calls for the same
    target MSB will surface the cached seed directly.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
from typing import Iterable

# Order matches thefifthmatt's index page. The pattern-ID offset is
# `BASE_NIGHTLORD_ID_STRIDE * index` for base patterns and
# `DLC_NIGHTLORD_ID_BASE + DLC_NIGHTLORD_ID_STRIDE * index` for DLC
# patterns. Sequence verified against thefifthmatt/nightreign/<name>/
# pages.
NIGHTLORDS_IN_ORDER = [
    'gladius', 'adel', 'gnoster', 'maris', 'libra',
    'fulghor', 'caligo', 'heolstor', 'harmonia', 'straghess',
]
BASE_NIGHTLORD_ID_STRIDE = 40
DLC_NIGHTLORD_ID_BASE = 1000
DLC_NIGHTLORD_ID_STRIDE = 10

# Within each Nightlord's 40-pattern block, the 5-pattern sub-ranges
# correspond to Shifting Earths in this order. Source:
# thefifthmatt/nightreign/adel/ which clusters spawn-point labels by
# Shifting Earth tag in this exact sequence.
SE_ORDER_IN_PATTERN_BLOCK = [
    None,            # 20 base patterns (offsets 0..19)
    'mountaintop',   # 5 patterns (offsets 20..24)
    'crater',        # 5 patterns (offsets 25..29)
    'rotted_woods',  # 5 patterns (offsets 30..34)
    'noklateo',      # 5 patterns (offsets 35..39)
]

# MSB filename prefix → Shifting Earth (or None). Derived from NR's
# m60_4X_3Y_ZZ map naming conventions. The four shifting earths are
# Mountaintops, Crater, Rotted Woods, and Noklateo (Eternal Cities).
# DLC adds Great Hollow which uses its own (DLC) pattern range.
MSB_PREFIX_TO_SE = [
    # (regex, shifting_earth_name OR None for base; description)
    (r'^m60_42_36_', 'crater',       'Crater shifting earth (Mountaintops sub-region)'),
    (r'^m60_42_37_', 'noklateo',     'Noklateo / Eternal Cities shifting earth'),
    (r'^m60_43_37_', 'noklateo',     'Noklateo / Eternal Cities shifting earth (second cluster)'),
    (r'^m60_43_38_', 'rotted_woods', 'Rotted Woods shifting earth'),
    (r'^m60_42_38_', 'mountaintop',  'Mountaintop shifting earth'),
    (r'^m60_43_36_', 'mountaintop',  'Mountaintop shifting earth (second cluster)'),
    (r'^m20_',       'great_hollow', 'DLC Great Hollow (DLC pattern range)'),
    # Everything else is a base-game tile that any non-SE pattern can
    # surface. The MSB might be a sub-dungeon (m15/m19/m30/m32/m34/m38/
    # m43/m46) or a non-SE Limveld overworld tile (m60_*_*_* without
    # the SE-marked prefixes). Treat as "no shifting earth required".
    (r'^m[0-9]+_',   None,            'Base game tile — any base pattern includes it'),
]


@dataclasses.dataclass
class PatternRange:
    nightlord: str
    shifting_earth: str | None  # None means base patterns
    lo: int                      # inclusive
    hi: int                      # inclusive
    is_dlc: bool

    def contains(self, pid: int) -> bool:
        return self.lo <= pid <= self.hi

    def describe(self) -> str:
        se = self.shifting_earth or 'base / no Shifting Earth'
        dlc = ' (DLC)' if self.is_dlc else ''
        return (f'{self.nightlord} {se}{dlc} → patterns '
                f'{self.lo:03d}-{self.hi:03d}')


def shifting_earth_for_msb(msb: str) -> tuple[str | None, str]:
    """Returns (se_name_or_None, description) for the given MSB."""
    # Normalize: accept m60_42_36_50.msb, m60_42_36_50, or
    # m60_42_36_50_00.msb (NR's full form).
    name = msb.strip()
    for pattern, se, descr in MSB_PREFIX_TO_SE:
        if re.match(pattern, name):
            return se, descr
    return None, ('unrecognized MSB prefix — defaulting to base / no '
                  'shifting earth')


def pattern_ranges_for_se(se: str | None) -> list[PatternRange]:
    """All (nightlord, pattern_id_range) combos that contain the given
    SE. None → every Nightlord's base range (20 patterns each).
    'great_hollow' → every Nightlord's DLC range (10 patterns each).
    Other SE names → 5-pattern slice within each Nightlord's base block.
    """
    ranges: list[PatternRange] = []
    if se == 'great_hollow':
        for i, n in enumerate(NIGHTLORDS_IN_ORDER):
            lo = DLC_NIGHTLORD_ID_BASE + i * DLC_NIGHTLORD_ID_STRIDE
            hi = lo + DLC_NIGHTLORD_ID_STRIDE - 1
            ranges.append(PatternRange(n, 'great_hollow', lo, hi, True))
        return ranges
    # Base-pattern block layout. Each Nightlord's block:
    #   offsets 0..19 → base (None)
    #   offsets 20..24 → SE_ORDER[1]   (mountaintop)
    #   offsets 25..29 → SE_ORDER[2]   (crater)
    #   offsets 30..34 → SE_ORDER[3]   (rotted_woods)
    #   offsets 35..39 → SE_ORDER[4]   (noklateo)
    if se is None:
        for i, n in enumerate(NIGHTLORDS_IN_ORDER):
            base = i * BASE_NIGHTLORD_ID_STRIDE
            ranges.append(PatternRange(n, None, base, base + 19, False))
        return ranges
    # Find which SE block.
    if se not in SE_ORDER_IN_PATTERN_BLOCK:
        return []
    se_index = SE_ORDER_IN_PATTERN_BLOCK.index(se)
    # se_index 1..4 → offsets (20, 25, 30, 35) respectively
    offset_start = 20 + (se_index - 1) * 5
    for i, n in enumerate(NIGHTLORDS_IN_ORDER):
        base = i * BASE_NIGHTLORD_ID_STRIDE
        ranges.append(PatternRange(
            n, se, base + offset_start, base + offset_start + 4, False))
    return ranges


# ---------------------------------------------------------------------
# Observation cache (built up by --record)
# ---------------------------------------------------------------------

def _default_observations_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'derand_observations.json')


def load_observations(path: str) -> dict:
    """Returns:
      {
        "observations": [
          {"seed": int, "nightlord": str, "pattern_id": int,
           "visited_msbs": [str], "notes": str | None,
           "recorded_at": "YYYY-MM-DD"},
          ...
        ]
      }
    """
    if not os.path.isfile(path):
        return {'observations': []}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_observations(path: str, data: dict) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')


def observations_for_msb(observations: dict, target_msb: str) -> list[dict]:
    """All recorded observations whose visited_msbs list includes
    target_msb."""
    target = target_msb.strip()
    out = []
    for entry in observations.get('observations', []):
        for v in entry.get('visited_msbs', []):
            if v.strip() == target:
                out.append(entry)
                break
    return out


# ---------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------

def cmd_lookup(args, observations: dict) -> int:
    """--target-msb mode: print the SE classification, the pattern
    ranges that match, and any cached seeds."""
    se, descr = shifting_earth_for_msb(args.target_msb)
    print(f'target MSB:        {args.target_msb}')
    print(f'shifting earth:    {se if se is not None else "none (base)"}')
    print(f'  ({descr})')
    ranges = pattern_ranges_for_se(se)
    if args.nightlord:
        nl = args.nightlord.lower()
        ranges = [r for r in ranges if r.nightlord == nl]
        if not ranges:
            print(f'\nno pattern ranges for nightlord={nl} + SE={se}')
            return 2
    print(f'\npattern ranges to filter in the derandomizer GUI:')
    for r in ranges:
        print(f'  - {r.describe()}')
    # Cache lookup
    cached = observations_for_msb(observations, args.target_msb)
    if cached:
        print(f'\ncached observations for this MSB '
              f'({len(cached)} entries):')
        for e in cached:
            n = e.get('nightlord', '?')
            pid = e.get('pattern_id', '?')
            seed = e.get('seed', '?')
            notes = e.get('notes', '')
            visited = e.get('visited_msbs', [])
            print(f'  seed={seed} nightlord={n} pattern={pid:03d}'
                  if isinstance(pid, int) else
                  f'  seed={seed} nightlord={n} pattern={pid}')
            print(f'    visited: {", ".join(visited)}')
            if notes:
                print(f'    notes: {notes}')
    else:
        print(f'\nno cached observations yet for {args.target_msb}.')
        print(f'guidance: open NightreignRandomizer.exe → Derandomizer '
              f'tab → set Nightlord to one of the above → reroll seeds '
              f'until "pattern" is in the listed range. Run the '
              f'expedition. Record back with:')
        ranges_to_show = ranges[:2]
        for r in ranges_to_show:
            print(f'  python {sys.argv[0]} --record --seed <YOUR_SEED> '
                  f'--nightlord {r.nightlord} --pattern-id <PID> '
                  f'--visited-msb {args.target_msb}')
    return 0


def cmd_plan(args, observations: dict) -> int:
    """--manifest --plan mode: read the validator manifest and emit a
    structured test queue annotated with shifting-earth needs and
    cached-seed hits.

    Filters to the highest-signal subset:
      - Track B confirmed scripted_intro flags
      - WOULD_REJECT at non-anchored boss catalog slots
      - named_location placements with CTD history
    """
    with open(args.manifest, encoding='utf-8') as f:
        manifest = json.load(f)
    # Bucket targets by the validator-relevant predicates.
    sig_tags = (
        'scripted_intro_required_at_non_anchored',
        'scripted_intro_intolerant_at_anchored',
        'named_location_with_ctd_history',
    )
    queue = []
    seen = set()  # dedupe by (msb, pi, target_cp) — same slot across
                  # seeds is the same test.
    for row in manifest:
        tags = row.get('suspicious_tags', [])
        status = row.get('status', '')
        is_sig = any(any(t.startswith(s) for s in sig_tags) for t in tags)
        is_would_reject = (status == 'WOULD_REJECT')
        if not (is_sig or is_would_reject):
            continue
        key = (row['msb'], row['pi'], row['target_cp'])
        if key in seen:
            continue
        seen.add(key)
        queue.append(row)
    if args.limit:
        queue = queue[:args.limit]
    # Emit
    print(f'# Test plan ({len(queue)} unique placements)')
    print(f'# Source: {args.manifest}')
    print()
    for i, row in enumerate(queue, 1):
        msb = row['msb']
        se, _ = shifting_earth_for_msb(msb)
        cached = observations_for_msb(observations, msb)
        cached_str = ''
        if cached:
            seeds = sorted({str(e.get('seed')) for e in cached})
            cached_str = f'CACHED seeds: {", ".join(seeds)}'
        else:
            ranges = pattern_ranges_for_se(se)
            shown = ranges[:3]
            range_strs = [f'{r.nightlord} {r.lo:03d}-{r.hi:03d}'
                          for r in shown]
            cached_str = (f'no cache — GUI filter: '
                          f'{" | ".join(range_strs)}'
                          + (' | ...' if len(ranges) > 3 else ''))
        tags = row.get('suspicious_tags', [])
        tag_short = next((t.split(':')[0] for t in tags
                          if any(t.startswith(s) for s in sig_tags)),
                         row.get('status', ''))
        print(f'{i:>3}. seed={row["seed"]:<7} {msb}:{row["pi"]:<3} '
              f'{row["target_cp"]}({row["target_name"]})')
        print(f'     {tag_short}  |  SE: {se or "base"}')
        print(f'     {cached_str}')
        print()
    return 0


def cmd_record(args, observations: dict) -> int:
    """--record mode: append an observation."""
    from datetime import date
    entry = {
        'seed': args.seed,
        'nightlord': args.nightlord.lower(),
        'pattern_id': args.pattern_id,
        'visited_msbs': sorted(set(args.visited_msb or [])),
        'notes': args.notes,
        'recorded_at': date.today().isoformat(),
    }
    observations.setdefault('observations', []).append(entry)
    save_observations(args.observations, observations)
    print(f'recorded:')
    print(f'  seed={entry["seed"]} nightlord={entry["nightlord"]} '
          f'pattern_id={entry["pattern_id"]}')
    print(f'  visited_msbs: {", ".join(entry["visited_msbs"])}')
    print(f'(wrote {args.observations})')
    return 0


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--observations', default=_default_observations_path(),
                   help='Path to derand_observations.json (default: '
                        'dev/derand_observations.json)')
    sub_group = p.add_mutually_exclusive_group()
    sub_group.add_argument('--target-msb',
                           help='Look up SE + pattern ranges + cached '
                                'seeds for the given MSB.')
    sub_group.add_argument('--manifest',
                           help='Validator manifest to emit a test '
                                'plan from. Requires --plan.')
    sub_group.add_argument('--record', action='store_true',
                           help='Record a new observation.')
    p.add_argument('--plan', action='store_true',
                   help='With --manifest, print test plan.')
    p.add_argument('--limit', type=int, default=0,
                   help='With --plan, cap output to N entries.')
    p.add_argument('--nightlord',
                   help='Filter --target-msb output to a single '
                        'Nightlord, or attach to --record.')
    p.add_argument('--seed', type=int,
                   help='Seed value for --record.')
    p.add_argument('--pattern-id', type=int,
                   help='Pattern ID observed for --record.')
    p.add_argument('--visited-msb', action='append',
                   help='MSB observed in the recorded expedition. '
                        'Repeatable.')
    p.add_argument('--notes',
                   help='Free-text notes for --record.')
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    observations = load_observations(args.observations)
    if args.target_msb:
        return cmd_lookup(args, observations)
    if args.manifest:
        if not args.plan:
            print('--manifest requires --plan', file=sys.stderr)
            return 2
        return cmd_plan(args, observations)
    if args.record:
        missing = [n for n in ('seed', 'nightlord', 'pattern_id')
                   if getattr(args, n) is None]
        if missing:
            print(f'--record requires: {", ".join("--" + m for m in missing)}',
                  file=sys.stderr)
            return 2
        if not args.visited_msb:
            print('--record requires at least one --visited-msb',
                  file=sys.stderr)
            return 2
        return cmd_record(args, observations)
    print('one of --target-msb / --manifest --plan / --record required',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
