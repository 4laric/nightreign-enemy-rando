#!/usr/bin/env python3
"""sim_fb_to_nb_promote_sweep.py — measure the
V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT knob's effect on non-catalogued
field slots.

Two layers reported:

  Layer 1 (rolls) — pure roll outcome distribution. For each promote_pct
    value, sweep every non-catalogued non-boss slot in
    data/nr_slot_inventory.json across N seeds and tabulate the
    field_roll_tier_for() output. Predictable from the probability
    model:
      P(field_boss) = fieldboss_pct * (1 - promote_pct)
      P(night_boss) = nightboss_pct + fieldboss_pct * promote_pct
    miniboss + grunt unchanged.

  Layer 2 (placements) — actual pick_target_cp outcomes on a random
    SAMPLE of non-catalogued slots. The cap system + size/locomotion
    gates may force NB rolls to fall down the ladder (NB → MB → grunt)
    when the pool exhausts. Reveals how the dial translates into
    on-the-ground encounters versus pure roll arithmetic.

USAGE
  python3 dev/sim_fb_to_nb_promote_sweep.py
  python3 dev/sim_fb_to_nb_promote_sweep.py --seeds 30
  python3 dev/sim_fb_to_nb_promote_sweep.py --sample 500 --no-placement
"""
import argparse
import json
import os
import random
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import oops_v3
from engine.runctx import RunContext


# Sweep grid. Includes default (0.0), a few small steps to map the low
# end where the knob is intended to be tuned, then larger steps up to 1.0.
DEFAULT_SWEEP = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 1.0]


def collect_non_cat_slots(engine, inventory):
    """Return inventory rows that fire the field roll: non-catalogued AND
    not recipient_is_boss."""
    out = []
    for e in inventory:
        key = (e['map'], e['part_index'])
        if key in engine.V3_BOSS_SLOT_CATALOG:
            continue
        if e.get('recipient_is_boss'):
            continue
        out.append(e)
    return out


def sweep_rolls(engine, slots, promote_pct, n_seeds):
    """For one promote_pct, count roll outcomes across n_seeds × |slots|
    calls. Returns Counter of tier outcomes plus a per-seed sample."""
    orig = engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT
    orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
    counts = Counter()
    per_seed_nb = []  # list of NB-roll counts per seed
    per_seed_fb = []
    per_seed_mb = []
    try:
        engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = promote_pct
        for seed in range(n_seeds):
            engine._V3_RUN_SEED = 0xF8_2_B0 ^ seed
            seed_counts = Counter()
            for e in slots:
                t = engine.field_roll_tier_for(e['map'], e['part_index'])
                seed_counts[t or '_none'] += 1
            counts.update(seed_counts)
            per_seed_nb.append(seed_counts.get('night_boss', 0))
            per_seed_fb.append(seed_counts.get('field_boss', 0))
            per_seed_mb.append(seed_counts.get('miniboss', 0))
    finally:
        engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = orig
        engine._V3_RUN_SEED = orig_seed
    return counts, per_seed_nb, per_seed_fb, per_seed_mb


def sweep_placements(engine, sample_slots, tags, prefix_variants,
                     prefix_count, promote_pct, n_seeds):
    """For one promote_pct, run pick_target_cp on each sampled slot at
    each seed. Returns a Counter of placed-tier outcomes. Caps applied
    via fresh RunContext per seed."""
    orig = engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT
    orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
    placed = Counter()
    roll_was_nb_total = 0
    roll_was_nb_placed_nb = 0
    try:
        engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = promote_pct
        for seed in range(n_seeds):
            engine._V3_RUN_SEED = 0xF8_2_B0 ^ seed
            # Fresh per-seed cap counter — mimics start-of-run.
            ctx = RunContext()
            for e in sample_slots:
                msb, pi = e['map'], e['part_index']
                recipient = e['c_prefix']
                if recipient not in tags:
                    continue
                rip_boss = bool(e.get('recipient_is_boss'))
                rng = random.Random(seed * 1009 + pi)
                # Pre-check the roll so we can ask "of NB-rolled slots,
                # how many actually got NB placements?"
                rolled = engine.field_roll_tier_for(msb, pi)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    rip_boss, rng,
                    slot_msb_name=msb, slot_pi=pi,
                    slot_variant_name=e.get('source_variant_name') or None,
                    run_ctx=ctx)
                tier = tags.get(result, {}).get('tier') if result else None
                placed[tier or '_none'] += 1
                if rolled == 'night_boss':
                    roll_was_nb_total += 1
                    if tier == 'night_boss':
                        roll_was_nb_placed_nb += 1
    finally:
        engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = orig
        engine._V3_RUN_SEED = orig_seed
    return placed, roll_was_nb_total, roll_was_nb_placed_nb


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seeds', type=int, default=20,
                   help='run seeds per promote_pct value (default 20)')
    p.add_argument('--sample', type=int, default=300,
                   help='non-cat slots to sample for placement sim '
                        '(default 300; layer 1 always uses all slots)')
    p.add_argument('--no-placement', action='store_true',
                   help='skip the slower placement layer (rolls only)')
    p.add_argument('--sweep', type=str, default=None,
                   help='comma-separated promote_pct values to test')
    p.add_argument('--save', metavar='PATH',
                   help='write JSON results to PATH')
    args = p.parse_args()

    engine = oops_v3
    engine.load_data()
    roster, tags = engine.load_data()
    prefix_variants, prefix_count = engine.build_per_prefix_data(roster)
    inventory = json.load(
        open(os.path.join(PROJECT_ROOT, 'data/nr_slot_inventory.json')))

    sweep = ([float(x) for x in args.sweep.split(',')]
             if args.sweep else list(DEFAULT_SWEEP))

    print(f'\nConstants in play:')
    print(f'  V3_FIELD_UPGRADE_MINIBOSS_PCT  = '
          f'{engine.V3_FIELD_UPGRADE_MINIBOSS_PCT}')
    print(f'  V3_FIELD_UPGRADE_FIELDBOSS_PCT = '
          f'{engine.V3_FIELD_UPGRADE_FIELDBOSS_PCT}')
    print(f'  V3_FIELD_UPGRADE_NIGHTBOSS_PCT = '
          f'{engine.V3_FIELD_UPGRADE_NIGHTBOSS_PCT}')

    non_cat = collect_non_cat_slots(engine, inventory)
    print(f'\nNon-catalogued field slots (roll fires): {len(non_cat)}')

    # Sampled subset for layer 2
    rng = random.Random(0xBE5A)
    sample = rng.sample(non_cat, min(args.sample, len(non_cat)))
    print(f'Sample for placement sim: {len(sample)}')

    print(f'\nSweep: {sweep}')
    print(f'Seeds per value: {args.seeds}')

    results = []

    # ---------------------------------------------------------------
    # LAYER 1 — pure roll distribution across all non-cat slots
    # ---------------------------------------------------------------
    print()
    print('=' * 78)
    print('LAYER 1 — ROLL OUTCOMES (pure, all non-cat slots)')
    print('=' * 78)
    print(f'\n{"promote":<10}'
          f'{"%NB roll":<11}{"%FB roll":<11}{"%MB roll":<11}{"%grunt":<11}'
          f'{"NB/seed":<11}{"FB/seed":<11}{"MB/seed":<11}')
    print('-' * 95)

    for pct in sweep:
        counts, ps_nb, ps_fb, ps_mb = sweep_rolls(
            engine, non_cat, pct, args.seeds)
        total = sum(counts.values())
        nb_rate = counts.get('night_boss', 0) / total
        fb_rate = counts.get('field_boss', 0) / total
        mb_rate = counts.get('miniboss', 0) / total
        gr_rate = counts.get('grunt', 0) / total

        # Predicted values from probability model
        nb_pct_const = engine.V3_FIELD_UPGRADE_NIGHTBOSS_PCT
        fb_pct_const = engine.V3_FIELD_UPGRADE_FIELDBOSS_PCT
        mb_pct_const = engine.V3_FIELD_UPGRADE_MINIBOSS_PCT
        nb_pred = nb_pct_const + fb_pct_const * pct
        fb_pred = fb_pct_const * (1 - pct)

        nb_mean = sum(ps_nb) / max(1, len(ps_nb))
        fb_mean = sum(ps_fb) / max(1, len(ps_fb))
        mb_mean = sum(ps_mb) / max(1, len(ps_mb))

        print(f'{pct:<10.2f}'
              f'{nb_rate:<10.3%} '
              f'{fb_rate:<10.3%} '
              f'{mb_rate:<10.3%} '
              f'{gr_rate:<10.3%} '
              f'{nb_mean:<10.1f} '
              f'{fb_mean:<10.1f} '
              f'{mb_mean:<10.1f}')

        results.append({
            'promote_pct': pct,
            'layer1_rates': {'night_boss': nb_rate, 'field_boss': fb_rate,
                             'miniboss': mb_rate, 'grunt': gr_rate},
            'layer1_per_seed_mean': {'night_boss': nb_mean,
                                     'field_boss': fb_mean,
                                     'miniboss': mb_mean},
            'layer1_predicted_nb_rate': nb_pred,
            'layer1_predicted_fb_rate': fb_pred,
        })

    # ---------------------------------------------------------------
    # LAYER 2 — actual placements via pick_target_cp on sampled slots
    # ---------------------------------------------------------------
    if not args.no_placement:
        print()
        print('=' * 78)
        print(f'LAYER 2 — ACTUAL PLACEMENTS '
              f'({args.sample} sampled slots × {args.seeds} seeds = '
              f'{args.sample * args.seeds} calls per value)')
        print('=' * 78)
        print(f'\n{"promote":<10}'
              f'{"%placed NB":<12}{"%placed FB":<12}'
              f'{"%placed MB":<12}{"%placed gr":<12}'
              f'{"NB-roll→NB%":<14}')
        print('-' * 80)

        for i, pct in enumerate(sweep):
            placed, nb_rolled, nb_kept = sweep_placements(
                engine, sample, tags, prefix_variants, prefix_count,
                pct, args.seeds)
            total = sum(placed.values())
            nb_p = placed.get('night_boss', 0) / total
            fb_p = placed.get('field_boss', 0) / total
            mb_p = placed.get('miniboss', 0) / total
            gr_p = sum(placed.get(t, 0) for t in
                       ('grunt', 'trash', 'cluster_member',
                        'mount_component', 'non_combat')) / total
            kept_rate = (nb_kept / nb_rolled) if nb_rolled else 0.0

            print(f'{pct:<10.2f}'
                  f'{nb_p:<11.3%} '
                  f'{fb_p:<11.3%} '
                  f'{mb_p:<11.3%} '
                  f'{gr_p:<11.3%} '
                  f'{kept_rate:<13.1%}')

            results[i]['layer2_placement_rates'] = {
                'night_boss': nb_p, 'field_boss': fb_p,
                'miniboss': mb_p, 'grunt_or_below': gr_p,
            }
            results[i]['layer2_nb_roll_kept_rate'] = kept_rate
            results[i]['layer2_nb_rolled'] = nb_rolled
            results[i]['layer2_nb_placed_after_roll'] = nb_kept

    print()
    if args.save:
        os.makedirs(os.path.dirname(args.save) or '.', exist_ok=True)
        with open(args.save, 'w') as f:
            json.dump({
                'sweep': sweep,
                'seeds': args.seeds,
                'sample_size': args.sample,
                'constants': {
                    'V3_FIELD_UPGRADE_MINIBOSS_PCT':
                        engine.V3_FIELD_UPGRADE_MINIBOSS_PCT,
                    'V3_FIELD_UPGRADE_FIELDBOSS_PCT':
                        engine.V3_FIELD_UPGRADE_FIELDBOSS_PCT,
                    'V3_FIELD_UPGRADE_NIGHTBOSS_PCT':
                        engine.V3_FIELD_UPGRADE_NIGHTBOSS_PCT,
                },
                'results': results,
            }, f, indent=2)
        print(f'Saved: {args.save}')


if __name__ == '__main__':
    sys.exit(main())
