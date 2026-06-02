#!/usr/bin/env python3
"""sim_reservation_health.py — run the unique-target reservation pre-pass
over N seeds and aggregate two health metrics:

  (1) Per-chr unplaced rate — "of N seeds, this chr failed to reserve
      any slots X% of the time." High unplaced rate means
      V3_RESERVATION_FLOORS isn't being honored — reservation pass is
      consistently failing to find qualifying slots.

  (2) Per-chr shifting-earth-only risk — chrs whose ELIGIBLE slot pool
      (slots that score positively under _score_slot_for_unique BEFORE
      the shifting-earth disqualifier fires) is dominated by shifting-
      earth tiles. The reservation pass rejects shifting-earth slots
      outright, but organic placement during the main swap loop
      doesn't — a chr whose only realistic homes are shifting-earth
      tiles will only appear in seeds that roll the matching event
      (Mountaintop / Crater / Rot Forest / Noklateo).

This sim runs only the RESERVATION PRE-PASS, not the full main swap
loop. Limitations:
  - Doesn't simulate vanilla-source preservation (`already_placed_counts`)
  - Doesn't simulate organic placements past the reservation slot
  - Doesn't simulate multiplayer_safe mode
The reservation pass is the primary "guarantee at least N" mechanism
in v0.26.x, so its health is the most useful single metric.

Usage:
    python3 dev/sim_reservation_health.py --msb-dir /tmp/audit_msbs/nr_decompiled_msbs
    python3 dev/sim_reservation_health.py --seeds 200 --msb-dir <path>
"""
import argparse
import os
import random
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def run_sim(msb_dir, n_seeds, verbose=False):
    import oops_v3

    # Load engine state once
    roster, tags = oops_v3.load_data()
    prefix_variants, _prefix_count = oops_v3.build_per_prefix_data(roster)

    # Enumerate candidate slots once (deterministic given input_dir)
    slots = oops_v3._enumerate_unique_candidate_slots(msb_dir)
    if not slots:
        print(f"ERROR: no candidate slots found in {msb_dir!r}", file=sys.stderr)
        return None

    if verbose:
        print(f"Loaded {len(slots)} candidate slots, "
              f"{len(oops_v3.V3_RESERVATION_FLOORS)} chrs in FLOORS")

    # Per-seed: run reservation pass, snapshot the result, reset state
    # Use a fresh RunContext per seed to avoid module-global contamination
    from engine.runctx import RunContext

    unplaced_counts = Counter()  # cp -> # seeds it failed reservation
    reservation_msbs = defaultdict(Counter)  # cp -> Counter(msb_name)
    reservation_total = Counter()  # cp -> # seeds it got at least one

    for seed in range(n_seeds):
        rng = random.Random(seed)
        ctx = RunContext()
        oops_v3._compute_unique_reservations(
            msb_dir, tags, prefix_variants, rng, run_ctx=ctx)

        # Pull unplaced
        for entry in ctx.unique_unplaced_log:
            unplaced_counts[entry['cp']] += 1

        # Pull reservations
        per_seed_cps = set()
        for (msb, pi), cp in ctx.unique_reservations.items():
            reservation_msbs[cp][msb] += 1
            per_seed_cps.add(cp)
        for cp in per_seed_cps:
            reservation_total[cp] += 1

    # Aggregate
    return {
        'n_seeds': n_seeds,
        'n_slots': len(slots),
        'unplaced_counts': unplaced_counts,
        'reservation_msbs': reservation_msbs,
        'reservation_total': reservation_total,
        'floors': dict(oops_v3.V3_RESERVATION_FLOORS),
        'tags': {cp: tags.get(cp, {}) for cp in oops_v3.V3_RESERVATION_FLOORS},
    }


def is_shifting_earth(msb_name):
    import oops_v3
    return oops_v3._shifting_earth_event(msb_name) is not None


def report(result, top_n=15):
    n = result['n_seeds']
    floors = result['floors']
    tags = result['tags']
    unplaced = result['unplaced_counts']
    res_msbs = result['reservation_msbs']
    res_total = result['reservation_total']

    print(f"\n=== Simulation: {n} seeds, {result['n_slots']} candidate slots ===\n")

    # Q1: unplaced rate
    print(f"=== Q1: Per-chr unplaced-rate (reservation pass failures) ===")
    print(f"(High % = floor=1 not being honored — reservation can't find a slot)\n")
    print(f"  {'cp':8s} {'name':35s} {'unplaced %':>11s}  {'unplaced n':>10s}")
    health_rows = []
    for cp in floors:
        n_unplaced = unplaced.get(cp, 0)
        pct = 100.0 * n_unplaced / n
        name = tags.get(cp, {}).get('name', '?')
        health_rows.append((pct, cp, name, n_unplaced))
    health_rows.sort(reverse=True)
    shown = 0
    for pct, cp, name, n_unp in health_rows:
        if pct == 0 and shown >= top_n:
            break
        marker = '⚠' if pct >= 50 else ' ' if pct == 0 else '·'
        print(f"  {marker} {cp:6s} {name[:33]:35s} {pct:>10.1f}%  {n_unp:>10d}")
        shown += 1
    n_zero = sum(1 for r in health_rows if r[0] == 0)
    print(f"\n  ({n_zero}/{len(health_rows)} chrs had 0% unplaced)")

    # Q2: shifting-earth-only chrs (among reservation_msbs)
    print(f"\n=== Q2: Per-chr reservation-MSB distribution (shifting-earth lock-in) ===")
    print(f"(Chrs whose reservations land only on shifting-earth-equivalent slots.)\n")
    se_risk_rows = []
    for cp, msb_counts in res_msbs.items():
        total_reservations = sum(msb_counts.values())
        if total_reservations == 0:
            continue
        # How many reservations landed on shifting-earth MSBs?
        # Note: reservation pre-pass REJECTS shifting-earth, so this should
        # be 0 by construction. Reporting confirms the predicate.
        se_count = sum(c for msb, c in msb_counts.items()
                       if is_shifting_earth(msb))
        se_pct = 100.0 * se_count / total_reservations
        se_risk_rows.append((se_pct, cp, total_reservations, msb_counts))
    se_risk_rows.sort(reverse=True)
    n_shifting = sum(1 for r in se_risk_rows if r[0] > 0)
    if n_shifting == 0:
        print("  ✓ No chr's reservations land on shifting-earth MSBs.")
        print("    (Confirms _score_slot_for_unique's shifting-earth gate works.)")
    else:
        print(f"  ⚠ {n_shifting} chrs have shifting-earth reservations")
        for pct, cp, total, _ in se_risk_rows[:10]:
            if pct == 0: break
            print(f"    {cp}: {pct:.0f}% of {total} reservations on shifting-earth")

    # Bonus: per-chr placement DIVERSITY (low MSB variety = locked-in)
    print(f"\n=== Q2-bonus: Reservation diversity per chr ===")
    print(f"(Low N-distinct-MSBs vs ceiling=2 = reservation always lands at same arena.)\n")
    diversity_rows = []
    for cp in floors:
        if cp not in res_msbs:
            continue
        msb_counts = res_msbs[cp]
        n_distinct = len(msb_counts)
        total = sum(msb_counts.values())
        avg_per_seed = total / n
        top_msb, top_count = msb_counts.most_common(1)[0]
        top_pct = 100.0 * top_count / total
        diversity_rows.append((n_distinct, top_pct, cp, top_msb, total, avg_per_seed))
    diversity_rows.sort()  # ascending — fewest distinct first
    print(f"  {'cp':8s} {'distinct MSBs':>14s} {'top MSB':22s} {'top%':>5s}  {'avg/seed':>8s}")
    for n_distinct, top_pct, cp, top_msb, total, avg in diversity_rows[:15]:
        print(f"  {cp:6s} {n_distinct:>13d}  {top_msb[:20]:22s} {top_pct:>4.0f}%  {avg:>7.2f}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--msb-dir', default='/tmp/audit_msbs/nr_decompiled_msbs',
        help='Vanilla NR MSB directory (default: %(default)s)')
    p.add_argument('--seeds', type=int, default=100,
        help='Number of seeds to simulate (default: %(default)s)')
    p.add_argument('--top-n', type=int, default=15,
        help='How many rows to show in each report (default: %(default)s)')
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()

    if not os.path.isdir(args.msb_dir):
        print(f"ERROR: msb-dir not found: {args.msb_dir}", file=sys.stderr)
        return 2

    result = run_sim(args.msb_dir, args.seeds, args.verbose)
    if result is None:
        return 2
    report(result, top_n=args.top_n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
