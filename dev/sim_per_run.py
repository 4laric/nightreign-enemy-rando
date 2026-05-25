#!/usr/bin/env python3
"""
sim_per_run.py — picker-distribution sim that respects per-run NR mechanics.

Two refinements over the older sim_cap_distribution.py:
  1. Shifting-earth tiles (Mountaintop / Crater / Rot Forest / Noklateo)
     appear ~5% per Expedition. Other 80% of runs have no shifting earth.
     A chr that only lives in shifting-earth slots gets its placement
     count weighted down accordingly.
  2. Castle variant: only one castle MSB is loaded per run (m13_00 vs
     m13_20 in our catalog; m14_00 hypothetically exists but isn't in
     the boss slot catalog so it's ignored).

Other simplifications inherited from sim_cap_distribution.py: skips
anim_class/fragile/scripted-intro gates, so real-engine counts will be
lower than this sim (gates reject some pairings the sim accepts).

USAGE

  # Run a fresh sim, print to stdout
  python3 dev/sim_per_run.py

  # Run + save to disk
  python3 dev/sim_per_run.py --save sims/v0.26.x_baseline.json

  # Diff a current sim against a saved baseline
  python3 dev/sim_per_run.py --diff sims/v0.26.x_baseline.json

  # Diff two saved sims directly (no fresh sim)
  python3 dev/sim_per_run.py --diff prev.json --against curr.json

  # Adjust seed count + RNG seed
  python3 dev/sim_per_run.py --seeds 500 --rng-seed 12345

CALIBRATION ANCHOR

  c4353 Leyndell Knight (cap=6) is the canonical "miniboss appearance"
  reference. In a freshly-tuned engine state, expect:
    mean ~1.0/seed, max ~4, appears in ~60% of runs.
  If Leyndell drifts well outside that band, something else changed.
"""

import argparse
import importlib.util
import json
import os
import random
import statistics
import sys
from collections import Counter, defaultdict


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
ENGINE_PATH = os.path.join(PROJECT_ROOT, 'oops_v3.py')
TAGS_PATH = os.path.join(PROJECT_ROOT, 'data/nr_enemy_tags.json')
ALL_SLOTS_PATH = os.path.join(PROJECT_ROOT, 'data/nr_all_slots.json')

# Per-NR-mechanics weighting. If Alaric reports different observed rates
# in playtest, edit these.
SHIFTING_EARTH_EVENTS = ['Mountaintop', 'Crater', 'RotForest', 'Noklateo']
SHIFTING_EARTH_PROB_EACH = 0.05  # ~80% of runs have no shifting earth
EVENT_TENS_MAP = {1: 'Mountaintop', 2: 'Crater', 3: 'RotForest', 5: 'Noklateo'}

# MMV-only NB chrs that aren't in nr_enemy_tags.json — needed so the sim
# can place them. Their actual metadata lives in mmv_imports.json /
# heritage pipeline; we just need tier here.
MMV_NB_FALLBACK = {
    'c4511': {'tier': 'night_boss', 'variants': 1, 'name': 'Lichdragon Fortissax'},
    'c5000': {'tier': 'night_boss', 'variants': 1, 'name': 'Commander Gaius'},
    'c5030': {'tier': 'night_boss', 'variants': 1, 'name': 'Romina, Saint of the Bud'},
    'c5051': {'tier': 'night_boss', 'variants': 1, 'name': 'Midra, Lord of Frenzied Flame'},
    'c5200': {'tier': 'night_boss', 'variants': 1, 'name': 'Metyr, Mother of Fingers'},
    'c8300': {'tier': 'night_boss', 'variants': 1, 'name': 'Dragonslayer Armor'},
}


def load_engine():
    """Import oops_v3 fresh — picks up whatever the current state of
    V3_TAG_OVERRIDES, V3_UNIQUE_TARGET_CAPS, V3_EXCLUDE_TARGET_PREFIXES,
    and V3_BOSS_SLOT_CATALOG is on disk."""
    spec = importlib.util.spec_from_file_location('o', ENGINE_PATH)
    o = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    return o


def load_tags_with_overrides(o):
    """Apply V3_TAG_OVERRIDES so the post-override tier is what the sim
    sees, then inject MMV NB fallbacks."""
    with open(TAGS_PATH) as f:
        tags = json.load(f)
    # v0.26.x: V3_TAG_OVERRIDES was removed — tiers now live directly in
    # nr_enemy_tags.json. Guarded so the sim runs whether or not the
    # engine carries the attribute.
    for cp, override in getattr(o, 'V3_TAG_OVERRIDES', {}).items():
        if cp in tags:
            tags[cp].update(override)
    for cp, info in MMV_NB_FALLBACK.items():
        if cp not in tags:
            tags[cp] = info
    return tags


def classify_msb(msb, o):
    """(kind, sub) where kind in {'always', 'shifting_earth', 'castle'}."""
    se = o._shifting_earth_event(msb)
    if se is not None:
        return ('shifting_earth', EVENT_TENS_MAP.get(se, f'?{se}'))
    if msb.startswith('m13'):
        return ('castle', msb)
    return ('always', None)


def bucket_slots(o, tags, include_grunts=False):
    """Group swap-eligible slots by their per-run availability class.

    Boss/miniboss slots come from V3_BOSS_SLOT_CATALOG. When
    include_grunts is set, grunt-tier slots are additionally pulled from
    data/nr_all_slots.json (every enemy Part across the vanilla MSBs):
    a slot counts as a grunt slot when its vanilla source chr is
    grunt-tier. Grunt slots carry src_tier='grunt' and flow through the
    same per-run availability bucketing and cap logic as boss slots.
    """
    slots_by_class = defaultdict(list)
    preserve_msbs = o.V3_OVERLAY_PRESERVE_VANILLA_MSBS
    preserve_slots = o.V3_PRESERVE_SLOTS
    for (msb, pi), entry in o.V3_BOSS_SLOT_CATALOG.items():
        if msb in preserve_msbs:
            continue
        if (msb, pi) in preserve_slots:
            continue
        cp = entry.get('cp')
        if not cp:
            continue
        src_tier = tags.get(cp, {}).get('tier', '?')
        if src_tier not in ('night_boss', 'miniboss'):
            continue
        cls, sub = classify_msb(msb, o)
        slots_by_class[(cls, sub)].append({
            'msb': msb, 'pi': pi, 'src_cp': cp, 'src_tier': src_tier,
        })
    if include_grunts:
        with open(ALL_SLOTS_PATH) as f:
            all_slots = json.load(f)
        for s in all_slots:
            msb, pi, cp = s['map'], s['part_index'], s['c_prefix']
            if msb in preserve_msbs:
                continue
            if (msb, pi) in preserve_slots:
                continue
            if tags.get(cp, {}).get('tier') != 'grunt':
                continue
            cls, sub = classify_msb(msb, o)
            slots_by_class[(cls, sub)].append({
                'msb': msb, 'pi': pi, 'src_cp': cp, 'src_tier': 'grunt',
            })
    return slots_by_class


def run_sim(o, tags, slots_by_class, n_seeds, rng_seed):
    """Run N seeds with realistic per-run MSB weighting. Returns
    (per_seed, pools): per_seed maps cp -> list of per-seed counts
    (length N); pools maps tier -> candidate cp list."""
    caps = o.V3_UNIQUE_TARGET_CAPS
    excl = o.V3_EXCLUDE_TARGET_PREFIXES
    # Night-boss slots additionally subtract V3_NIGHT_BOSS_EXCLUDE_TARGETS
    # (chrs barred from NB arenas but still valid as field content) —
    # mirrors the engine's pool filter in shuffle_msb_v3.
    nb_excl = getattr(o, 'V3_NIGHT_BOSS_EXCLUDE_TARGETS', set())

    def tier_pool(tier):
        extra = nb_excl if tier == 'night_boss' else set()
        return [cp for cp, t in tags.items()
                if t.get('tier') == tier
                and cp not in excl and cp not in extra]

    # Only build pools for tiers that actually have slots this run.
    tiers_present = {slot['src_tier']
                     for slots in slots_by_class.values()
                     for slot in slots}
    pools = {tier: tier_pool(tier) for tier in tiers_present}
    all_cps = set().union(*pools.values()) if pools else set()

    castle_variants = sorted([sub for (cls, sub) in slots_by_class
                              if cls == 'castle'])
    if not castle_variants:
        castle_variants = [None]  # graceful: no castle slots in catalog

    per_seed = defaultdict(list)
    rng = random.Random(rng_seed)
    for _ in range(n_seeds):
        # Roll shifting earth
        r = rng.random()
        active_se = None
        for i, name in enumerate(SHIFTING_EARTH_EVENTS):
            if r < SHIFTING_EARTH_PROB_EACH * (i + 1):
                active_se = name
                break
        # Roll castle variant (uniform across catalog'd variants)
        active_castle = rng.choice(castle_variants)
        # Build this seed's slot pool
        seed_slots = []
        for (cls, sub), slots in slots_by_class.items():
            if cls == 'always':
                seed_slots.extend(slots)
            elif cls == 'shifting_earth' and sub == active_se:
                seed_slots.extend(slots)
            elif cls == 'castle' and sub == active_castle:
                seed_slots.extend(slots)
        # Walk slots in random order, picker uses uniform sample with caps
        rng.shuffle(seed_slots)
        used = Counter()
        placements = Counter()
        for slot in seed_slots:
            pool = pools.get(slot['src_tier'], ())
            avail = [cp for cp in pool
                     if caps.get(cp) is None or used[cp] < caps[cp]]
            if not avail:
                continue
            pick = rng.choice(avail)
            placements[pick] += 1
            used[pick] += 1
        for cp in all_cps:
            per_seed[cp].append(placements[cp])
    return per_seed, pools


def summarize(per_seed, tags, caps):
    """cp -> {tier, name, cap, mean, median, max, appearance_pct, n}."""
    out = {}
    for cp, vals in per_seed.items():
        if not vals:
            continue
        t = tags.get(cp, {})
        cap = caps.get(cp)
        out[cp] = {
            'tier': t.get('tier'),
            'name': t.get('name', '?'),
            'cap': cap,
            'mean': statistics.mean(vals),
            'median': statistics.median(vals),
            'max': max(vals),
            'appearance_pct': sum(1 for v in vals if v > 0) / len(vals) * 100,
            'n': len(vals),
        }
    return out


def build_result(o, n_seeds, rng_seed, summary, slots_by_class,
                 include_grunts=False):
    """Dict that gets saved as JSON. Includes enough metadata that a
    diff can sanity-check it's comparing comparable runs."""
    bucket_sizes = {f'{cls}:{sub}' if sub else cls: len(s)
                    for (cls, sub), s in slots_by_class.items()}
    return {
        'schema_version': 1,
        'engine_fingerprint': getattr(o, 'ENGINE_FINGERPRINT', None)
                              or getattr(o, 'V3_ENGINE_FINGERPRINT', None)
                              or 'unknown',
        'sim_params': {
            'n_seeds': n_seeds,
            'rng_seed': rng_seed,
            'shifting_earth_prob_each': SHIFTING_EARTH_PROB_EACH,
            'include_grunts': include_grunts,
        },
        'bucket_sizes': bucket_sizes,
        'cprefixes': summary,
    }


# ---------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------

def _print_table(summary, cps):
    print(f'  {"cp":<7s} {"tier":<10s} {"name":<32s} {"cap":>4s}'
          f'  {"mean":>5s} {"med":>4s} {"max":>4s}  {"appear%":>8s}')
    for cp in cps:
        r = summary[cp]
        cap_s = str(r['cap']) if r['cap'] is not None else '-'
        print(f'  {cp:<7s} {(r["tier"] or "?"):<10s} '
              f'{(r["name"] or "?")[:30]:<32s} {cap_s:>4s}  '
              f'{r["mean"]:>5.2f} {r["median"]:>4.1f} {r["max"]:>4d}  '
              f'{r["appearance_pct"]:>7.1f}%')


def print_summary(result, focus_cps=None):
    summary = result['cprefixes']
    print(f'Engine: {result["engine_fingerprint"]}; '
          f'seeds={result["sim_params"]["n_seeds"]}, '
          f'rng_seed={result["sim_params"]["rng_seed"]}')
    print(f'\nBucket sizes:')
    for k, v in sorted(result['bucket_sizes'].items()):
        print(f'  {k}: {v} slots')
    print()
    if focus_cps:
        _print_table(summary, [cp for cp in focus_cps if cp in summary])
        return
    # Boss tiers and grunt tier print as separate tables — grunt means
    # run ~10-50x boss means, so a shared sort would bury the bosses.
    boss = sorted([cp for cp in summary
                   if summary[cp]['tier'] in ('night_boss', 'miniboss')],
                  key=lambda cp: (summary[cp]['tier'],
                                  -summary[cp]['mean']))
    grunt = sorted([cp for cp in summary
                    if summary[cp]['tier'] == 'grunt'],
                   key=lambda cp: -summary[cp]['mean'])
    if boss:
        print('BOSS-SLOT distribution (night_boss + miniboss):')
        _print_table(summary, boss[:60])
    if grunt:
        print(f'\nGRUNT-SLOT distribution ({len(grunt)} chrs):')
        _print_table(summary, grunt)


def diff_results(base, curr,
                 mean_delta_threshold=0.15,  # ±0.15 = significant
                 appearance_delta_threshold=10.0,  # ±10 pp
                 max_delta_threshold=2):
    """Compare two sim results. Returns categorized lists of changed
    c-prefixes for reporting. The thresholds filter noise from RNG —
    a 200-seed sim has natural ±0.05 variance in mean."""
    b_cps = set(base['cprefixes'])
    c_cps = set(curr['cprefixes'])
    added = sorted(c_cps - b_cps)
    removed = sorted(b_cps - c_cps)
    common = sorted(b_cps & c_cps)

    significant = []  # list of (cp, base_row, curr_row, delta_mean, ...)
    for cp in common:
        b = base['cprefixes'][cp]
        c = curr['cprefixes'][cp]
        d_mean = c['mean'] - b['mean']
        d_appear = c['appearance_pct'] - b['appearance_pct']
        d_max = c['max'] - b['max']
        if (abs(d_mean) >= mean_delta_threshold
                or abs(d_appear) >= appearance_delta_threshold
                or abs(d_max) >= max_delta_threshold):
            significant.append({
                'cp': cp, 'base': b, 'curr': c,
                'd_mean': d_mean, 'd_appear': d_appear, 'd_max': d_max,
            })
    # Sort: biggest absolute mean delta first
    significant.sort(key=lambda x: -abs(x['d_mean']))
    return added, removed, significant


def print_diff(base, curr):
    added, removed, significant = diff_results(base, curr)
    print(f'BASE:  engine={base["engine_fingerprint"]}, '
          f'seeds={base["sim_params"]["n_seeds"]}, '
          f'rng_seed={base["sim_params"]["rng_seed"]}')
    print(f'CURR:  engine={curr["engine_fingerprint"]}, '
          f'seeds={curr["sim_params"]["n_seeds"]}, '
          f'rng_seed={curr["sim_params"]["rng_seed"]}')
    # Bucket-size diff (catches catalog changes)
    b_buckets = base.get('bucket_sizes', {})
    c_buckets = curr.get('bucket_sizes', {})
    bucket_keys = set(b_buckets) | set(c_buckets)
    bucket_diffs = [(k, b_buckets.get(k, 0), c_buckets.get(k, 0))
                    for k in sorted(bucket_keys)
                    if b_buckets.get(k) != c_buckets.get(k)]
    if bucket_diffs:
        print(f'\nBucket sizes changed:')
        for k, b, c in bucket_diffs:
            print(f'  {k}: {b} → {c}')

    if added:
        print(f'\nNEW chrs in CURR ({len(added)}): {", ".join(added)}')
    if removed:
        print(f'\nDROPPED chrs from BASE ({len(removed)}): {", ".join(removed)}')

    print(f'\nSignificant changes ({len(significant)} c-prefixes):')
    if not significant:
        print('  (no chrs crossed delta thresholds)')
        return
    print(f'  {"cp":<7s} {"name":<28s} {"tier":<10s} '
          f'{"base":>14s}  {"curr":>14s}  {"Δmean":>7s} {"Δapp%":>7s} {"Δmax":>5s}')
    for entry in significant:
        cp = entry['cp']
        b, c = entry['base'], entry['curr']
        b_str = f'{b["mean"]:.2f}/{b["appearance_pct"]:.0f}%/m{b["max"]}'
        c_str = f'{c["mean"]:.2f}/{c["appearance_pct"]:.0f}%/m{c["max"]}'
        sign_mean = '+' if entry['d_mean'] >= 0 else ''
        sign_app = '+' if entry['d_appear'] >= 0 else ''
        sign_max = '+' if entry['d_max'] >= 0 else ''
        print(f'  {cp:<7s} {(c["name"] or b["name"] or "?")[:26]:<28s} '
              f'{(c["tier"] or b["tier"] or "?"):<10s} '
              f'{b_str:>14s}  {c_str:>14s}  '
              f'{sign_mean}{entry["d_mean"]:>5.2f}  '
              f'{sign_app}{entry["d_appear"]:>5.1f}  '
              f'{sign_max}{entry["d_max"]:>3d}')
    print(f'\n(legend: mean/appearance%/max ;  delta thresholds: '
          f'|Δmean|≥0.15, |Δapp%|≥10pp, |Δmax|≥2)')


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seeds', type=int, default=200,
                    help='Number of seeds to simulate (default 200).')
    ap.add_argument('--rng-seed', type=int, default=0,
                    help='RNG seed for reproducibility (default 0).')
    ap.add_argument('--save', metavar='PATH',
                    help='Save the sim result as JSON to PATH.')
    ap.add_argument('--diff', metavar='BASELINE_PATH',
                    help='Compare against a previously-saved baseline. '
                         'If --against is not also given, a fresh sim '
                         'with current engine state acts as the CURR side.')
    ap.add_argument('--against', metavar='CURR_PATH',
                    help='With --diff, compare BASELINE against this '
                         'saved result instead of running a fresh sim.')
    ap.add_argument('--focus', nargs='+', metavar='CPREFIX',
                    help='Restrict the printed table to these c-prefixes.')
    ap.add_argument('--grunts', action='store_true',
                    help='Also simulate grunt-tier slots (from '
                         'data/nr_all_slots.json) and print a separate '
                         'grunt distribution table. Off by default — '
                         'grunt slots are ~2600 vs ~120 boss slots.')
    args = ap.parse_args()

    if args.diff and args.against:
        # Pure diff mode — no fresh sim
        with open(args.diff) as f:
            base = json.load(f)
        with open(args.against) as f:
            curr = json.load(f)
        print_diff(base, curr)
        return 0

    # Run a fresh sim
    o = load_engine()
    tags = load_tags_with_overrides(o)
    slots_by_class = bucket_slots(o, tags, include_grunts=args.grunts)
    per_seed, _ = run_sim(o, tags, slots_by_class,
                          n_seeds=args.seeds, rng_seed=args.rng_seed)
    summary = summarize(per_seed, tags, o.V3_UNIQUE_TARGET_CAPS)
    result = build_result(o, args.seeds, args.rng_seed, summary,
                          slots_by_class, include_grunts=args.grunts)

    if args.diff:
        # Diff fresh-sim vs saved baseline
        with open(args.diff) as f:
            base = json.load(f)
        print_diff(base, result)
    else:
        print_summary(result, focus_cps=args.focus)

    if args.save:
        os.makedirs(os.path.dirname(args.save) or '.', exist_ok=True)
        with open(args.save, 'w') as f:
            json.dump(result, f, indent=2, sort_keys=True)
            f.write('\n')
        print(f'\nSaved to {args.save}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
