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

CALIBRATION ANCHORS

  c4353 Leyndell Knight (cap=4 from v0.27.3) is the canonical
  "miniboss appearance" reference. Targets shift by mode:

  Boss-only (--seeds 500):                     mean~0.82, max=4, appear~52%
  Boss + grunts (--seeds 500 --grunts):        mean~0.74, max=4, appear~41%

  The grunts-mode drop is the v0.28 hybrid-picker recycling at work:
  big MSBs saturate the per-MSB distinct budget on grunt picks (median
  4 vanilla cps/MSB), then later slots in that MSB skew toward already-
  resident cps. The fresh branch also EXCLUDES resident cps while
  under budget, so a chr that doesn't get picked early in an MSB tends
  to get zero picks in that MSB — concentration per MSB up, variety
  per MSB down, total picks per seed roughly flat.

  Use --recycle-stats to see the kind totals (fresh/recycle/overflow).
  Boss-only typically shows ~5% recycle (slots too sparse to saturate);
  --grunts shows ~75% recycle (saturation hits within ~4 picks per MSB).
  If Leyndell drifts well outside these bands, something else changed.
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
INVENTORY_PATH = os.path.join(PROJECT_ROOT, 'data/nr_slot_inventory.json')
CLUSTERS_PATH = os.path.join(PROJECT_ROOT, 'data/slot_poi_clusters.json')

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
    """Import oops_v3 fresh AND run load_data() so the mutated module
    globals (V3_EXCLUDE_TARGET_PREFIXES, V3_UNIQUE_TARGET_CAPS,
    V3_RESERVATION_FLOORS, V3_ARENA_ONLY_TARGETS, etc.) reflect the
    production state. Returns (o, tags) — tags is the post-load_data
    dict that includes MMV/ER pack imports.

    v0.27.x fix: previously this only ran exec_module, which left the
    mutated sets at their pre-load_data sizes — sim was missing ~80
    exclusions, ~160 caps, ~88 floors, and the MMV-augmented tag
    entries. Cap-marked rows printed as 'cap=-' and excluded chrs
    (c8000/c8100/c8110/etc) appeared in placement totals."""
    spec = importlib.util.spec_from_file_location('o', ENGINE_PATH)
    o = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    _, tags = o.load_data()
    return o, tags


def load_tags_with_overrides(o, tags):
    """Inject MMV NB fallbacks for chrs not in tags. After the
    v0.27.x load_engine() fix, load_data's _PACK_LOADERS already fold
    mmv_imports.json into `tags`, so this is normally a no-op — kept
    as a defensive fallback for the case where mmv_imports.json is
    absent or fails to load."""
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
        if src_tier not in ('night_boss', 'field_boss', 'miniboss'):
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


def load_poi_lookup():
    """Phase 1: load data/slot_poi_clusters.json and build a reverse
    lookup `{(msb, part_index): cluster_id}` keyed for the hot loop.
    Returns the dict; raises if the cluster file is absent."""
    with open(CLUSTERS_PATH, encoding='utf-8') as f:
        data = json.load(f)
    lookup = {}
    for msb, clist in data['clusters'].items():
        for cluster_id, members in enumerate(clist):
            for pi in members:
                lookup[(msb, pi)] = cluster_id
    return lookup


def compute_budgets(o, prefix_variants, poi_lookup=None):
    """v0.28 per-scope distinct-c-prefix budget. Same logic as the
    pre-scan in shuffle_msb_v3, but keyed on either msb (MSB scope,
    default) or (msb, cluster_id) (POI scope) depending on whether
    a poi_lookup dict is provided. Forced-vanilla slots (excluded
    sources, no-variants, pinned, dead-npc) don't count — their
    chrbnd is loaded vanilla-cheap and isn't charged against the
    rando-introduced distinct chrbnd cap.

    Phase 1 of POI recycling: pass `poi_lookup` (from
    load_poi_lookup()) to get per-cluster budgets; downstream code
    (run_sim) reads the budget with the matching key type.

    Return shapes:
      poi_lookup=None  -> {msb: int}
      poi_lookup={...} -> {(msb, cluster_id): int}
    """
    excl_pref = o.V3_EXCLUDE_PREFIXES
    excl_src = o.V3_EXCLUDE_SOURCE_PREFIXES
    pinned_va = getattr(o, 'V3_BINARY_SEARCH_VANILLA_PINS', set())
    with open(INVENTORY_PATH) as f:
        inv = json.load(f)
    by_scope = defaultdict(set)
    for r in inv:
        cp = r.get('c_prefix')
        npc = r.get('npc_param_id', 0)
        if not (cp and cp.startswith('c') and len(cp) > 1 and cp[1].isdigit()):
            continue
        if npc == 0 or npc == 0xFFFFFFFF:
            continue
        msb = r['map']
        pi = r['part_index']
        msb_base = msb[:-4] if msb.endswith('.msb') else msb
        if (msb_base, pi) in pinned_va:
            continue
        if cp in excl_pref or cp in excl_src:
            continue
        if cp not in prefix_variants:
            continue
        if poi_lookup is None:
            scope_key = msb
        else:
            cid = poi_lookup.get((msb, pi), -1)
            scope_key = (msb, cid)
        by_scope[scope_key].add(cp)
    return {k: len(v) for k, v in by_scope.items()}


# Back-compat alias for legacy callers / tests.
def compute_msb_budgets(o, prefix_variants):
    return compute_budgets(o, prefix_variants, poi_lookup=None)


def run_sim(o, tags, slots_by_class, n_seeds, rng_seed,
            track_recycle_kinds=False, poi_lookup=None):
    """Run N seeds with realistic per-run MSB weighting + the v0.28
    hybrid distinct-budget/recycle picker. Returns (per_seed, pools[,
    kind_totals]): per_seed maps cp -> list of per-seed counts (length
    N); pools maps tier -> candidate cp list; kind_totals (when
    track_recycle_kinds is set) maps 'fresh'/'recycle'/'overflow'/'none'
    to total counts across all seeds — a diagnostic for how often
    recycling fires.

    v0.28 hybrid: per-MSB iteration with a distinct-c-prefix budget
    (from compute_msb_budgets) and a resident set tracking which
    c-prefixes have been committed in the current MSB. The
    _choose_with_budget helper from oops_v3 is imported and used
    verbatim — same code path the engine and simulate_engine.py run
    through, so the variety/recycle behavior matches by construction."""
    caps = o.V3_UNIQUE_TARGET_CAPS
    excl = o.V3_EXCLUDE_TARGET_PREFIXES
    # Night-boss slots additionally subtract V3_NIGHT_BOSS_EXCLUDE_TARGETS
    # (chrs barred from NB arenas but still valid as field content) —
    # mirrors the engine's pool filter in shuffle_msb_v3.
    nb_excl = getattr(o, 'V3_NIGHT_BOSS_EXCLUDE_TARGETS', set())

    # v0.28: shared picker so sim and engine pick the same way.
    # Fallback to a local inline picker if the engine doesn't carry
    # _choose_with_budget yet (running an older oops_v3).
    _choose = getattr(o, '_choose_with_budget', None)
    if _choose is None:
        def _choose(chosen_pool, resident, budget, picker):
            if not chosen_pool:
                return None, None
            fresh = [c for c in chosen_pool if c not in resident]
            recyc = [c for c in chosen_pool if c in resident]
            if len(resident) < budget and fresh:
                return picker(sorted(fresh)), 'fresh'
            if recyc:
                return picker(sorted(recyc)), 'recycle'
            if fresh:
                return picker(sorted(fresh)), 'overflow'
            return None, None

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

    # v0.28: per-scope distinct-c-prefix budget, computed once from the
    # full slot inventory (the engine's basis, not the sim's filtered
    # slot view).
    #
    # Phase 1: poi_lookup=None -> per-MSB scope (production v0.28
    # default); poi_lookup={(msb,pi):cluster_id} -> per-POI scope
    # (Phase 2 engine behavior with V3_POI_SCOPE_RECYCLE=True).
    prefix_variants, _ = o.build_per_prefix_data(
        json.load(open(os.path.join(PROJECT_ROOT,
                                    'data/nr_enemy_roster.json'))))
    budgets = compute_budgets(o, prefix_variants, poi_lookup=poi_lookup)

    # Slot -> scope-key resolver. MSB scope: key = msb. POI scope:
    # key = (msb, cluster_id) with -1 sentinel for slots missing
    # from the cluster file (shouldn't happen but defensive).
    if poi_lookup is None:
        def scope_key(slot):
            return slot['msb']
    else:
        def scope_key(slot):
            cid = poi_lookup.get((slot['msb'], slot['pi']), -1)
            return (slot['msb'], cid)

    castle_variants = sorted([sub for (cls, sub) in slots_by_class
                              if cls == 'castle'])
    if not castle_variants:
        castle_variants = [None]

    per_seed = defaultdict(list)
    kind_totals = Counter()
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

        # v0.28: group by scope (MSB or POI) so recycling logic has a
        # meaningful per-scope resident set. Scope iteration order is
        # randomized; within each scope slot order is randomized too
        # (mirrors v0.27.13 per-MSB random slot order). In POI mode
        # the grouping is one level finer (one cluster at a time).
        slots_by_scope = defaultdict(list)
        for s in seed_slots:
            slots_by_scope[scope_key(s)].append(s)
        scope_order = list(slots_by_scope)
        rng.shuffle(scope_order)

        used = Counter()         # run-wide cap accumulator
        placements = Counter()   # run-wide placement counts
        for scope in scope_order:
            scope_slots = slots_by_scope[scope][:]
            rng.shuffle(scope_slots)
            resident = set()
            budget = budgets.get(scope, 1 << 30)  # unbounded fallback
            for slot in scope_slots:
                pool = pools.get(slot['src_tier'], ())
                avail = [cp for cp in pool
                         if caps.get(cp) is None or used[cp] < caps[cp]]
                pick, kind = _choose(avail, resident, budget, rng.choice)
                if pick is None:
                    if track_recycle_kinds:
                        kind_totals['none'] += 1
                    continue
                placements[pick] += 1
                used[pick] += 1
                resident.add(pick)
                if track_recycle_kinds:
                    kind_totals[kind] += 1
        for cp in all_cps:
            per_seed[cp].append(placements[cp])
    if track_recycle_kinds:
        return per_seed, pools, kind_totals
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
                 include_grunts=False, poi_scope=False):
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
            'poi_scope': poi_scope,
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
                   if summary[cp]['tier'] in ('night_boss', 'field_boss', 'miniboss')],
                  key=lambda cp: (summary[cp]['tier'],
                                  -summary[cp]['mean']))
    grunt = sorted([cp for cp in summary
                    if summary[cp]['tier'] == 'grunt'],
                   key=lambda cp: -summary[cp]['mean'])
    if boss:
        print('BOSS-SLOT distribution (night_boss + field_boss + miniboss):')
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
    ap.add_argument('--recycle-stats', action='store_true',
                    help='Print v0.28 hybrid-picker kind totals (fresh/'
                         'recycle/overflow/none). Useful for confirming '
                         'budget tuning — boss-only mode typically shows '
                         'near-zero recycle since boss slots rarely '
                         'saturate the per-MSB budget on their own; '
                         '--grunts mode is where recycling actually fires.')
    ap.add_argument('--poi-scope', action='store_true',
                    help='Phase 1 of POI recycling spec: scope the v0.28 '
                         'distinct-budget + resident set per spatial POI '
                         'cluster (from data/slot_poi_clusters.json) '
                         'instead of per-MSB. Mirrors what '
                         'V3_POI_SCOPE_RECYCLE=True in oops_v3 does at '
                         'the engine level (Phase 2). Use with '
                         '--recycle-stats + --save to compare scopes via '
                         '--diff.')
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
    o, tags = load_engine()
    tags = load_tags_with_overrides(o, tags)
    slots_by_class = bucket_slots(o, tags, include_grunts=args.grunts)
    poi_lookup = load_poi_lookup() if args.poi_scope else None
    if args.recycle_stats:
        per_seed, _, kind_totals = run_sim(
            o, tags, slots_by_class,
            n_seeds=args.seeds, rng_seed=args.rng_seed,
            track_recycle_kinds=True, poi_lookup=poi_lookup)
    else:
        per_seed, _ = run_sim(o, tags, slots_by_class,
                              n_seeds=args.seeds, rng_seed=args.rng_seed,
                              poi_lookup=poi_lookup)
        kind_totals = None
    summary = summarize(per_seed, tags, o.V3_UNIQUE_TARGET_CAPS)
    result = build_result(o, args.seeds, args.rng_seed, summary,
                          slots_by_class, include_grunts=args.grunts,
                          poi_scope=args.poi_scope)
    if kind_totals is not None:
        total = sum(kind_totals.values()) or 1
        scope_label = 'POI' if args.poi_scope else 'MSB'
        print(f'\nv0.28 hybrid-picker kind totals across all seeds '
              f'(scope: {scope_label}):')
        for k in ('fresh', 'recycle', 'overflow', 'none'):
            n = kind_totals.get(k, 0)
            print(f'  {k:9s} {n:>9d}  ({100*n/total:5.1f}%)')

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
