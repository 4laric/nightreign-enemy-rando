#!/usr/bin/env python3
"""diagnose_problem_slots.py — playtest data feedback tool.

Takes a list of broken (map, part_index) slots from playtest, looks up their
context in the spoiler + tags, and outputs:
  1. A formatted V3_PROBLEM_SLOTS dict entry for each, ready to paste into
     oops_v3.py.
  2. Pattern analysis — common source c-prefixes, qualifiers, position
     ranges, map cells. Helps spot whether the broken slots share a
     structural feature we could detect automatically (Tier 1 or Tier 2)
     instead of needing manual Tier 3 entries.
  3. A "near-miss" report — slots adjacent to broken ones (in the same
     map cell or proximate position) that you might want to verify next
     before they break in another seed.

Usage:
    python diagnose_problem_slots.py \\
        --spoiler /path/to/_spoilers.json \\
        --broken broken_slots.txt

Where broken_slots.txt is one "map_msb,part_index" per line, like:
    m60_43_37_20.msb,23
    m60_43_38_00.msb,15
    # comments allowed
    m38_00_00_00.msb,20  notes about why this one failed

Output goes to stdout. Pipe to a file or copy directly into V3_PROBLEM_SLOTS.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict


def parse_broken_file(path):
    """Each line: 'msb_name,part_index [optional comment]'. Returns list."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Split off comment after pi
            parts = line.split(',', 1)
            if len(parts) != 2:
                print(f'WARN: skipping malformed line: {line}', file=sys.stderr)
                continue
            msb = parts[0].strip()
            rest = parts[1].strip()
            # pi is first token after the comma; rest is comment
            pi_str = rest.split()[0].rstrip(',;')
            try:
                pi = int(pi_str)
            except ValueError:
                print(f'WARN: bad pi {pi_str!r}: {line}', file=sys.stderr)
                continue
            comment = rest[len(pi_str):].strip(' ,;')
            if not msb.endswith('.msb'):
                msb = msb + '.msb'
            entries.append((msb, pi, comment))
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spoiler', required=True,
                    help='Path to _spoilers.json from the playtest seed')
    ap.add_argument('--broken', required=True,
                    help='Path to broken-slots text file')
    ap.add_argument('--roster', default='nr_enemy_roster.json',
                    help='Path to nr_enemy_roster.json (for variant names)')
    ap.add_argument('--tags', default='nr_enemy_tags.json',
                    help='Path to nr_enemy_tags.json')
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    spoiler_path = args.spoiler
    roster_path = args.roster if os.path.isabs(args.roster) else os.path.join(here, args.roster)
    tags_path = args.tags if os.path.isabs(args.tags) else os.path.join(here, args.tags)

    with open(spoiler_path) as f:
        sp = json.load(f)
    with open(roster_path) as f:
        roster = json.load(f)
    with open(tags_path) as f:
        tags = json.load(f)

    npc_to_name = {v.get('npc_param_id'): v.get('mmv_name', '')
                   for v in roster['all_variants']}

    # Index spoiler by (map, pi) for fast lookup
    by_map_pi = {(e['map'], e['part_index']): e for e in sp['entries']}

    broken = parse_broken_file(args.broken)
    print(f'# Loaded {len(broken)} broken slot reports from {args.broken}')
    print(f'# Spoiler seed: {sp.get("seed")}')
    print()

    # ========================================================================
    # Section 1: V3_PROBLEM_SLOTS dict entries
    # ========================================================================
    print('# === Section 1: V3_PROBLEM_SLOTS entries ===')
    print('# Paste these into V3_PROBLEM_SLOTS in oops_v3.py.')
    print()
    print('V3_PROBLEM_SLOTS_ADD = {')
    for msb, pi, comment in broken:
        e = by_map_pi.get((msb, pi))
        if not e:
            print(f"    # ({msb!r}, {pi}): NOT FOUND in spoiler — check map/pi")
            continue
        src = e['original']['c_prefix']
        new = e['new']['c_prefix']
        pos = e.get('position')
        src_npc = e['original'].get('npc_param_id')
        src_name = npc_to_name.get(src_npc, '?')
        reason = comment if comment else f'broken {new} at {src} slot'
        pos_str = f'pos={pos}' if pos else 'no pos'
        print(f"    ({msb!r}, {pi}): "
              f"'{reason} | was {src} ({src_name}) | {pos_str}',")
    print('}')
    print()

    # ========================================================================
    # Section 2: Pattern analysis
    # ========================================================================
    print('# === Section 2: Pattern analysis ===')
    src_cps = Counter()
    qualifiers = Counter()
    map_cells = Counter()
    positions = []
    for msb, pi, _ in broken:
        e = by_map_pi.get((msb, pi))
        if not e:
            continue
        src = e['original']['c_prefix']
        src_cps[src] += 1
        map_cells[msb] += 1
        src_name = npc_to_name.get(e['original'].get('npc_param_id'), '')
        if '(' in src_name and ')' in src_name:
            q = src_name[src_name.index('(') + 1:src_name.rindex(')')]
            qualifiers[q] += 1
        if e.get('position'):
            positions.append(e['position'])

    print(f'\n# Most common source c-prefixes among broken slots:')
    for cp, n in src_cps.most_common(10):
        nm = tags.get(cp, {}).get('name', cp)
        print(f'#   {cp:<8} ({nm[:30]}) — {n} broken slots')

    print(f'\n# Variant qualifiers in broken-slot sources:')
    for q, n in qualifiers.most_common(10):
        print(f'#   ({q}) — {n} broken slots')

    print(f'\n# Map cells with most broken slots:')
    for m, n in map_cells.most_common(10):
        n_total = sum(1 for e in sp['entries'] if e['map'] == m)
        pct = 100 * n / n_total if n_total else 0
        print(f'#   {m}: {n}/{n_total} broken ({pct:.0f}%)')

    if positions:
        ys = [p[1] for p in positions]
        print(f'\n# Y-coordinate distribution of broken slots:')
        print(f'#   min={min(ys):.1f}  max={max(ys):.1f}  median={sorted(ys)[len(ys)//2]:.1f}')
        print(f'#   sub-surface (y<-10): {sum(1 for y in ys if y < -10)}')
        print(f'#   high-y (y>=30): {sum(1 for y in ys if y >= 30)}')
        print(f'#   low-y (0 <= y < 30): {sum(1 for y in ys if 0 <= y < 30)}')

    # Heuristic: if 3+ broken slots all share a (qualifier OR source_cp OR map),
    # that's a candidate for Tier 1/Tier 2 detection upgrade
    print(f'\n# === Section 3: Tier-upgrade candidates ===')
    print('# If a pattern repeats 3+ times, consider promoting to T1 or T2:')
    promoted = False
    for q, n in qualifiers.most_common():
        if n >= 3:
            print(f'#   * Qualifier "({q})" — {n} broken slots. '
                  f'Add to V3_FRAGILE_SOURCE_QUALIFIERS for Tier 1 detection.')
            promoted = True
    for m, n in map_cells.most_common():
        n_total = sum(1 for e in sp['entries'] if e['map'] == m)
        if n >= 3 and n_total > 0 and n / n_total >= 0.3:
            print(f'#   * Map "{m}" — {n}/{n_total} ({100*n/n_total:.0f}%) broken. '
                  f'Add to V3_FRAGILE_MAPS for Tier 2 detection.')
            promoted = True
    if not promoted:
        print('#   No clear pattern — manual T3 entries are the right approach.')


if __name__ == '__main__':
    main()
