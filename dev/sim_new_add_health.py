#!/usr/bin/env python3
"""Multi-seed simulation: how do the v0.28.x new adds fare across seeds?

Runs the engine's RESERVATION PRE-PASS over N seeds via the
inventory-only path (no MSBs on disk needed). Aggregates:

  - For arena-required chrs, what fraction of seeds got a reservation?
  - For each new-add cp, what's the placement-rate distribution?
  - Which chrs are floors-eligible but consistently failing reservation?

This is the v0.28.x-equivalent of dev/sim_reservation_health.py but
focused on the new-add cps from this session rather than V3_RESERVATION_FLOORS.
The reservation pass is a proxy — chrs that never reserve are heavily
disadvantaged for the main swap loop too, since they're arena-only and
need that pre-pass to land.

Usage:
    python3 dev/sim_new_add_health.py [--seeds N] [--top-n N]
"""
import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


# New-add c-prefixes from this session (Case-B + 10-pick + 38-batch + promoted +
# individual). Grouped for the report.
NEW_ADDS = {
    'case_b': {'c5120', 'c5131', 'c5132', 'c5140', 'c5141', 'c5194'},
    'tenpick': {'c5790', 'c5960', 'c5780', 'c5970', 'c5620', 'c5980',
                'c5950', 'c5730', 'c5680', 'c5690'},
    'tier_a_batch': {
        'c6210','c6220','c6232','c6233','c6270','c6290','c6291','c6300','c6310','c6320',
        'c5550','c5551','c5560','c5390','c5391','c5530','c5580','c5630','c5640',
        'c5710','c5720','c5760','c5761','c5520','c5524','c5526','c5570','c5590',
        'c5591','c5850','c5871','c5930','c5931','c5940','c5990','c5380','c5381','c5421',
    },
    'promoted_mmv': {'c2030','c2031','c2110','c2120','c4511','c4720','c4721',
                     'c4730','c5000','c5030','c5051','c5130','c5200','c5230',
                     'c5300','c5740','c6201','c6231','c6260'},
    'individual': {'c5050', 'c6251', 'c5800', 'c5190', 'c5192', 'c5193', 'c5220'},
}
ALL_NEW = set().union(*NEW_ADDS.values())


def run_sim(n_seeds, verbose=False):
    import oops_v3

    # Load engine state — module loads with caps/floors/arena_only auto-extended
    roster, tags = oops_v3.load_data()
    prefix_variants, _ = oops_v3.build_per_prefix_data(roster)

    # Inventory-based slot enumeration (no MSBs on disk needed)
    inv_path = os.path.join(_ROOT, 'data/nr_slot_inventory.json')
    inventory = json.load(open(inv_path))
    slots = oops_v3._enumerate_unique_candidate_slots('', inventory=inventory)

    if not slots:
        print("ERROR: no slots from inventory", file=sys.stderr)
        return None

    if verbose:
        print(f"  inventory slots:        {len(slots):,}")
        print(f"  V3_RESERVATION_FLOORS:  {len(oops_v3.V3_RESERVATION_FLOORS)}")
        print(f"  V3_UNIQUE_TARGET_CAPS:  {len(oops_v3.V3_UNIQUE_TARGET_CAPS)}")
        print(f"  V3_ARENA_ONLY_TARGETS:  {len(oops_v3.V3_ARENA_ONLY_TARGETS)}")

    from engine.runctx import RunContext

    # Per-cp accumulators across seeds
    reserved_in_n_seeds = Counter()   # cp -> # seeds where reserved >= 1
    total_reservations = Counter()    # cp -> sum of reservations across seeds
    unplaced_seeds = Counter()        # cp -> # seeds in unplaced log

    for seed in range(n_seeds):
        rng = random.Random(seed)
        ctx = RunContext()
        oops_v3._compute_unique_reservations(
            '', tags, prefix_variants, rng, run_ctx=ctx, inventory=inventory)

        seen_this_seed = set()
        for (_msb, _pi), cp in ctx.unique_reservations.items():
            total_reservations[cp] += 1
            seen_this_seed.add(cp)
        for cp in seen_this_seed:
            reserved_in_n_seeds[cp] += 1
        for entry in ctx.unique_unplaced_log:
            unplaced_seeds[entry['cp']] += 1

    return {
        'n_seeds': n_seeds,
        'n_slots': len(slots),
        'tags': tags,
        'reserved_in_n_seeds': reserved_in_n_seeds,
        'total_reservations': total_reservations,
        'unplaced_seeds': unplaced_seeds,
        'floors': dict(oops_v3.V3_RESERVATION_FLOORS),
        'caps': dict(oops_v3.V3_UNIQUE_TARGET_CAPS),
        'arena_only_targets': set(oops_v3.V3_ARENA_ONLY_TARGETS),
    }


def report_batch(result, batch_name, cps, top_only_problems=False):
    n = result['n_seeds']
    tags = result['tags']
    arena_set = result['arena_only_targets']
    caps = result['caps']
    floors = result['floors']

    rows = []
    for cp in sorted(cps):
        tag = tags.get(cp, {})
        n_reserved_seeds = result['reserved_in_n_seeds'].get(cp, 0)
        total_res = result['total_reservations'].get(cp, 0)
        pct = 100.0 * n_reserved_seeds / n
        avg_per_seed = total_res / n if n > 0 else 0
        is_arena = cp in arena_set or tag.get('expects_boss_arena')
        tier = tag.get('tier', '?')
        in_floors = cp in floors
        in_caps = cp in caps
        name = tag.get('name', '?')
        rows.append({
            'cp': cp, 'name': name, 'tier': tier, 'is_arena': is_arena,
            'in_floors': in_floors, 'in_caps': in_caps,
            'pct_reserved': pct, 'avg_per_seed': avg_per_seed,
            'total_reservations': total_res,
        })

    # Sort: arena-required + lowest pct_reserved first (the alarm cases)
    rows.sort(key=lambda r: (not r['is_arena'], r['pct_reserved'], r['cp']))

    print(f"\n=== {batch_name} ({len(cps)} cps) ===")
    print(f"  {'cp':<7} {'tier':<11} {'kind':<7} {'flr':<4} {'cap':<4} "
          f"{'reserve %':>10} {'avg/seed':>9}  name")
    print(f"  {'-'*100}")
    for r in rows:
        kind = 'arena' if r['is_arena'] else 'field'
        flr = 'Y' if r['in_floors'] else '-'
        cap = 'Y' if r['in_caps'] else '-'
        marker = '  '
        if r['is_arena'] and r['pct_reserved'] < 20:
            marker = '⚠ '
        elif r['is_arena'] and r['pct_reserved'] < 50:
            marker = '· '
        print(f"  {marker}{r['cp']:<5} {r['tier']:<11} {kind:<7} {flr:<4} {cap:<4} "
              f"{r['pct_reserved']:>9.1f}% {r['avg_per_seed']:>8.2f}   {r['name']}")


def report_summary(result):
    n = result['n_seeds']
    tags = result['tags']
    arena_set = result['arena_only_targets']

    # Big picture: of the arena-required new adds, what % got at least 1
    # reservation in ANY seed?
    arena_new = [cp for cp in ALL_NEW
                 if cp in arena_set or tags.get(cp, {}).get('expects_boss_arena')]
    field_new = [cp for cp in ALL_NEW if cp not in arena_new]

    pct_threshold_excellent = 80  # placed in ≥80% of seeds
    pct_threshold_acceptable = 30
    pct_threshold_alarm = 5

    def categorize(cp):
        reserved_n = result['reserved_in_n_seeds'].get(cp, 0)
        pct = 100.0 * reserved_n / n
        if pct >= pct_threshold_excellent:
            return 'excellent'
        if pct >= pct_threshold_acceptable:
            return 'acceptable'
        if pct >= pct_threshold_alarm:
            return 'rare'
        return 'never'

    arena_cats = Counter(categorize(cp) for cp in arena_new)
    field_cats = Counter(categorize(cp) for cp in field_new)

    print(f"\n=== Summary across {n} seeds ===")
    print(f"\n  ARENA-REQUIRED new adds ({len(arena_new)} cps):")
    print(f"    excellent  (≥{pct_threshold_excellent}% seeds reserved): {arena_cats['excellent']}")
    print(f"    acceptable (≥{pct_threshold_acceptable}%): {arena_cats['acceptable']}")
    print(f"    rare       (≥{pct_threshold_alarm}%): {arena_cats['rare']}")
    print(f"    never      (<{pct_threshold_alarm}%): {arena_cats['never']}")
    print(f"\n  FIELD-ONLY new adds ({len(field_new)} cps):")
    print(f"    (no arena reservation needed; placement is organic via the picker.")
    print(f"    These won't show in the reservation pre-pass — they rely on grunt/")
    print(f"    miniboss pool draws during the main swap loop.)")
    print(f"    reserved at least once: {sum(field_cats.values()) - field_cats['never']}/{len(field_new)}")

    # Specifically the "never" arena cases — the bug bucket
    never_cases = sorted([cp for cp in arena_new
                          if categorize(cp) == 'never'])
    if never_cases:
        print(f"\n  Arena-required cps NEVER reserved in {n} seeds ({len(never_cases)}):")
        for cp in never_cases:
            tag = tags.get(cp, {})
            tier = tag.get('tier', '?')
            sz = tag.get('size_class', '?')
            fragile = ' fragile' if tag.get('fragile_locomotion') else ''
            print(f"    {cp}  [{tier}, {sz}{fragile}]  {tag.get('name','?')}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--seeds', type=int, default=50)
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()

    print(f"Sim: {args.seeds} seeds, inventory-only enumeration")
    result = run_sim(args.seeds, verbose=args.verbose)
    if result is None:
        return 2

    for batch_name, cps in NEW_ADDS.items():
        report_batch(result, batch_name, cps)
    report_summary(result)
    return 0


if __name__ == '__main__':
    sys.exit(main())
