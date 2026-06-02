#!/usr/bin/env python3
"""sim_nb_slot_outcomes.py — focused diagnostic for v0.28.x+ NB-slot
tier-ladder + cap-exemption changes.

Question: at every NB-catalogued slot, what's the distribution of placed-
tier outcomes across N run seeds? Pre-change, many slots fell to miniboss
(observed in the user's spoiler — m47/m48 DS-heritage cluster). Post-
change, the ladder should never reach miniboss for an NB slot.

Unlike sim_per_run.py (placement-distribution sim that doesn't reproduce
the full picker), this calls into the real pick_target_cp with realistic
run-seed variation. Reports per-slot and aggregate tier breakdowns.

USAGE
  python3 dev/sim_nb_slot_outcomes.py --seeds 50
  python3 dev/sim_nb_slot_outcomes.py --seeds 100 --cluster m47_m48
  python3 dev/sim_nb_slot_outcomes.py --seeds 50 --save sims/nb_post_changes.json
  python3 dev/sim_nb_slot_outcomes.py --diff sims/nb_pre_changes.json
"""
import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import oops_v3
from engine.runctx import RunContext


def is_recipient_boss(recipient_cp, tags, prefix_variants):
    return oops_v3.is_boss_tier_prefix(recipient_cp, tags, prefix_variants)


def collect_nb_slots(engine, cluster=None):
    """Enumerate every NB-catalogued slot. Returns list of (msb, pi, entry).
    cluster='m47_m48' restricts to the DS-heritage cluster."""
    nb_slots = []
    for (msb, pi), entry in engine.V3_BOSS_SLOT_CATALOG.items():
        if entry.get('tier') != 'nightboss':
            continue
        if cluster == 'm47_m48' and not msb.startswith(('m47_', 'm48_0')):
            continue
        nb_slots.append((msb, pi, entry))
    return sorted(nb_slots, key=lambda s: (s[0], s[1]))


def run_slot(engine, tags, prefix_variants, prefix_count,
             msb, pi, entry, n_seeds):
    """Roll `n_seeds` run seeds against a single (msb, pi). Returns
    {seed -> (result_cp, result_tier)} dict. None result encoded as
    (None, None)."""
    recipient = entry.get('cp')
    if recipient is None or recipient not in tags:
        return None  # can't sim this slot
    rip_boss = is_recipient_boss(recipient, tags, prefix_variants)
    slot_variant_name = entry.get('name')

    outcomes = {}
    orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
    try:
        for seed in range(n_seeds):
            engine._V3_RUN_SEED = 0x51_C0_DE ^ seed  # distinct namespace
            ctx = RunContext()
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                rip_boss, rng,
                slot_msb_name=msb, slot_pi=pi,
                slot_variant_name=slot_variant_name,
                run_ctx=ctx)
            tier = tags.get(result, {}).get('tier') if result else None
            outcomes[seed] = (result, tier)
    finally:
        engine._V3_RUN_SEED = orig_seed
    return outcomes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seeds', type=int, default=50,
                   help='run seeds per slot (default 50)')
    p.add_argument('--cluster',
                   choices=('all', 'm47_m48'), default='all',
                   help='which slots to sim')
    p.add_argument('--save', metavar='PATH',
                   help='write JSON result to PATH')
    p.add_argument('--diff', metavar='PATH',
                   help='diff fresh run against saved baseline')
    args = p.parse_args()

    engine = oops_v3
    engine.load_data()
    roster, tags = engine.load_data()
    prefix_variants, prefix_count = engine.build_per_prefix_data(roster)

    slots = collect_nb_slots(engine, cluster=args.cluster)
    print(f'\n{len(slots)} NB-catalogued slot(s) to sim'
          f' ({args.cluster!r} filter, {args.seeds} seeds each)\n')

    per_slot_dist = {}    # (msb, pi) -> {tier: count}
    per_slot_unique = {}  # (msb, pi) -> set of result_cps
    aggregate_dist = Counter()
    aggregate_unique = set()
    none_count = 0
    total_calls = 0
    miniboss_offenders = []  # (msb, pi, seed, cp) tuples — should be empty post-fix
    grunt_offenders = []
    preserved_slots = []  # (msb, pi) tuples that always returned None

    for msb, pi, entry in slots:
        outcomes = run_slot(engine, tags, prefix_variants, prefix_count,
                            msb, pi, entry, args.seeds)
        if outcomes is None:
            continue
        dist = Counter()
        unique = set()
        for seed, (cp, tier) in outcomes.items():
            total_calls += 1
            if cp is None:
                dist['_none'] += 1
                none_count += 1
                continue
            dist[tier or '_untagged'] += 1
            unique.add(cp)
            aggregate_dist[tier or '_untagged'] += 1
            aggregate_unique.add(cp)
            if tier == 'miniboss':
                miniboss_offenders.append((msb, pi, seed, cp))
            elif tier in ('grunt', 'trash', 'cluster_member',
                           'mount_component', 'non_combat'):
                grunt_offenders.append((msb, pi, seed, cp))
        per_slot_dist[(msb, pi)] = dict(dist)
        per_slot_unique[(msb, pi)] = sorted(unique)
        if dist.get('_none', 0) == args.seeds:
            preserved_slots.append((msb, pi))

    # Render
    print(f'{"Slot":<35} {"NB":>4} {"NL":>4} {"FB":>4} {"MB":>4} '
          f'{"GR":>4} {"NONE":>5}  unique cps')
    print('-' * 100)
    for msb, pi, entry in slots:
        if (msb, pi) not in per_slot_dist:
            continue
        d = per_slot_dist[(msb, pi)]
        unique = per_slot_unique[(msb, pi)]
        label = f'{msb} pi={pi}'[:34]
        nb = d.get('night_boss', 0)
        nl = d.get('nightlord', 0)
        fb = d.get('field_boss', 0)
        mb = d.get('miniboss', 0)
        gr = (d.get('grunt', 0) + d.get('trash', 0)
              + d.get('cluster_member', 0)
              + d.get('mount_component', 0)
              + d.get('non_combat', 0))
        none = d.get('_none', 0)
        u_short = ','.join(unique[:6]) + ('...' if len(unique) > 6 else '')
        u_str = f'{len(unique)} ({u_short})'
        print(f'{label:<35} {nb:>4} {nl:>4} {fb:>4} {mb:>4} {gr:>4} '
              f'{none:>5}  {u_str}')

    print()
    print(f'AGGREGATE across {len(per_slot_dist)} slots × {args.seeds} seeds '
          f'= {total_calls} calls:')
    for tier, n in aggregate_dist.most_common():
        print(f'  {tier:<15}{n:>5}  ({n / max(1, total_calls):.1%})')
    print(f'  {"_none":<15}{none_count:>5}  '
          f'({none_count / max(1, total_calls):.1%})')
    print(f'  Unique placed cps: {len(aggregate_unique)}')

    print()
    if miniboss_offenders:
        print(f'⚠ {len(miniboss_offenders)} miniboss-tier placements at NB slots:')
        for msb, pi, seed, cp in miniboss_offenders[:10]:
            name = tags.get(cp, {}).get('name', cp)
            print(f'    {msb} pi={pi} seed={seed}: {cp} {name}')
        if len(miniboss_offenders) > 10:
            print(f'    ... and {len(miniboss_offenders) - 10} more')
    else:
        print('✓ Zero miniboss-tier placements at NB slots — ladder invariant holds')
    if grunt_offenders:
        print(f'⚠ {len(grunt_offenders)} field-strength placements at NB slots')
    else:
        print('✓ Zero field-strength placements at NB slots')
    if preserved_slots:
        print(f'\n{len(preserved_slots)} slots ALWAYS returned None '
              f'(vanilla preserved every seed):')
        for msb, pi in preserved_slots[:20]:
            print(f'  {msb} pi={pi}')

    payload = {
        'engine_version': getattr(engine, 'ENGINE_VERSION', '?'),
        'seeds_per_slot': args.seeds,
        'slot_count': len(per_slot_dist),
        'cluster': args.cluster,
        'aggregate': dict(aggregate_dist),
        'aggregate_none': none_count,
        'aggregate_unique_cps': sorted(aggregate_unique),
        'per_slot': {f'{msb}|pi={pi}': per_slot_dist[(msb, pi)]
                     for (msb, pi) in per_slot_dist},
        'miniboss_offender_count': len(miniboss_offenders),
        'grunt_offender_count': len(grunt_offenders),
        'preserved_slot_count': len(preserved_slots),
    }

    if args.save:
        os.makedirs(os.path.dirname(args.save) or '.', exist_ok=True)
        with open(args.save, 'w') as f:
            json.dump(payload, f, indent=2)
        print(f'\nSaved: {args.save}')

    if args.diff:
        with open(args.diff) as f:
            baseline = json.load(f)
        print(f'\n=== DIFF vs {args.diff} ===')
        for tier in set(aggregate_dist) | set(baseline.get('aggregate', {})):
            before = baseline.get('aggregate', {}).get(tier, 0)
            after = aggregate_dist.get(tier, 0)
            delta = after - before
            arrow = '↑' if delta > 0 else ('↓' if delta < 0 else '=')
            print(f'  {tier:<15}{before:>5} → {after:<5}  {arrow} {delta:+}')
        b_mb = baseline.get('miniboss_offender_count', 0)
        a_mb = len(miniboss_offenders)
        print(f'  miniboss_offenders: {b_mb} → {a_mb}  '
              f'{"✓ FIXED" if a_mb == 0 and b_mb > 0 else ""}')


if __name__ == '__main__':
    sys.exit(main())
