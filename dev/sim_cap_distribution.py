"""
sim_cap_distribution.py — drive a simplified per-slot picker over the
catalog and report cap-fill / swarm / variety distribution across N seeds.

Approach: for each seed, iterate every swap-eligible slot in random order
(after applying v0.25.3 preservation gates). For each slot, build the
compatible-chr pool via engine helpers, apply cap exhaustion, and uniform-
sample. Track per-cprefix counts. Repeat for N seeds; aggregate stats.

This is NOT identical to the real engine — it skips a lot of context
(slot position fragility filters, ghost variants, reservation pre-pass,
multiplayer-safe blocklist, etc.). But it exercises the cap-enforcement
logic which is what we want to measure here.
"""
import importlib.util
import json
import random
from collections import Counter, defaultdict
import statistics

spec = importlib.util.spec_from_file_location('o', 'oops_v3.py')
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)

# v0.27.x fix: load_data() mutates V3_EXCLUDE_TARGET_PREFIXES,
# V3_UNIQUE_TARGET_CAPS, V3_RESERVATION_FLOORS, V3_ARENA_ONLY_TARGETS
# (adding ~80/160/88/30 entries respectively from cinematic auto-excludes,
# the v0.27.3 miniboss tier sweep, MMV/ER pack imports, etc.) and folds
# mmv_imports.json into the tags dict it returns. Reading these globals
# before load_data ran was silently giving the sim the pre-mutation
# values — missing miniboss cap=4, missing the 30 empty-variant
# auto-excludes (c8000/c8100/...), no MMV NB chrs in the tag pool.
_, tags = o.load_data()

# v0.25.3 preservation gates
preserve_msbs = o.V3_OVERLAY_PRESERVE_VANILLA_MSBS
preserve_slots = o.V3_PRESERVE_SLOTS

# v0.26.x: V3_TAG_OVERRIDES removed — tier already in nr_enemy_tags.json

# MMV-only chrs aren't in nr_enemy_tags.json. Add them synthetically with
# best-guess tier/variants so the simulator can place them. Without this,
# c4511/c5000/c5030/c5051/c5200/c8300 would show 0% fill in this sim
# even though the real engine places them. Their actual placement metadata
# lives in mmv_imports.json / heritage pipeline; we just need tier here.
MMV_NB_FALLBACK = {
    'c4511': {'tier': 'night_boss', 'variants': 1, 'name': 'Lichdragon Fortissax'},
    'c5000': {'tier': 'night_boss', 'variants': 1, 'name': 'Commander Gaius'},
    'c5030': {'tier': 'night_boss', 'variants': 1, 'name': 'Romina, Saint of the Bud'},
    'c5051': {'tier': 'night_boss', 'variants': 1, 'name': 'Midra, Lord of Frenzied Flame'},
    'c5200': {'tier': 'night_boss', 'variants': 1, 'name': 'Metyr, Mother of Fingers'},
    'c8300': {'tier': 'night_boss', 'variants': 1, 'name': 'Dragonslayer Armor'},
}
for cp, info in MMV_NB_FALLBACK.items():
    if cp not in tags:
        tags[cp] = info

# Build the swap-eligible slot list
eligible = []
for (msb, pi), entry in o.V3_BOSS_SLOT_CATALOG.items():
    if msb in preserve_msbs: continue
    if (msb, pi) in preserve_slots: continue
    cp = entry.get('cp')
    if not cp: continue
    tier = entry.get('tier', '?')
    # We want boss-tier-ish slots
    if tier in ('remembrance', 'named_boss', 'fieldboss', 'noklateo',
                'ruins_boss', 'castle_interior', 'encampment', 'crater',
                'fort_suffix', 'cathedral', 'mountaintop', 'fort_boss',
                'nightboss', 'boss_suffix'):
        eligible.append({
            'msb': msb, 'pi': pi, 'src_cp': cp, 'tier': tier,
        })

# Tier compatibility map for which target tiers can fill which slot tier
# Modeled loosely on the engine's compatible_pool logic. Boss-tier slots
# accept night_boss/field_boss; lower-tier slots also accept miniboss.
SLOT_TO_TARGET_TIERS = {
    'remembrance':       {'night_boss', 'field_boss', 'miniboss'},
    'named_boss':        {'night_boss', 'field_boss', 'miniboss'},
    'fieldboss':         {'night_boss', 'field_boss', 'miniboss'},
    'noklateo':          {'night_boss', 'field_boss', 'miniboss'},
    'ruins_boss':        {'field_boss', 'miniboss'},
    'castle_interior':   {'night_boss', 'field_boss', 'miniboss'},
    'encampment':        {'field_boss', 'miniboss'},
    'crater':            {'night_boss', 'field_boss', 'miniboss'},
    'fort_suffix':       {'field_boss', 'miniboss'},
    'cathedral':         {'night_boss', 'field_boss', 'miniboss'},
    'mountaintop':       {'night_boss', 'field_boss', 'miniboss'},
    'fort_boss':         {'field_boss', 'miniboss'},
    'nightboss':         {'night_boss'},
    'boss_suffix':       {'night_boss', 'field_boss'},
}

# Build pools per accepted-tier-set, with chrs that pass exclusion gates
excluded = (getattr(o, 'V3_EXCLUDE_PREFIXES', set())
            | getattr(o, 'V3_EXCLUDE_TARGET_PREFIXES', set())
            | getattr(o, 'V3_GHOST_EXCLUDE_TARGET_PREFIXES', set()))

# All eligible target chrs by tier
chrs_by_tier = defaultdict(list)
for cp, info in tags.items():
    t = info.get('tier')
    if t not in ('night_boss', 'field_boss', 'miniboss'): continue
    if cp in excluded: continue
    if info.get('variants', 0) == 0: continue
    chrs_by_tier[t].append(cp)

target_pool_size = sum(len(v) for v in chrs_by_tier.values())
print(f'Total eligible boss-tier targets: {target_pool_size}')
print(f'  night_boss: {len(chrs_by_tier["night_boss"])}')
print(f'  field_boss: {len(chrs_by_tier["field_boss"])}')
print(f'  miniboss:   {len(chrs_by_tier["miniboss"])}')
print(f'Total swap-eligible slots: {len(eligible)}')

# Build slot-to-pool mapping (cached)
slot_pools = {}
for tier_key, target_tiers in SLOT_TO_TARGET_TIERS.items():
    pool = []
    for t in target_tiers:
        pool.extend(chrs_by_tier[t])
    slot_pools[tier_key] = pool

caps = o.V3_UNIQUE_TARGET_CAPS
GLOBAL_CAP = o.V3_TARGET_PLACEMENT_CAP

def run_one_seed(seed):
    """Return Counter(c_prefix -> placement count) for this seed."""
    rng = random.Random(seed)
    placed = Counter()       # ALL placements
    capped_placed = {}       # _placed_counts equivalent (capped-only)
    slot_order = list(eligible)
    rng.shuffle(slot_order)
    for s in slot_order:
        pool = list(slot_pools.get(s['tier'], []))
        # Apply unique-cap exhaustion
        pool = [cp for cp in pool
                if capped_placed.get(cp, 0) < caps.get(cp, 999)]
        # Apply global cap (50 default)
        pool = [cp for cp in pool if placed.get(cp, 0) < GLOBAL_CAP]
        if not pool: continue
        chosen = rng.choice(pool)
        placed[chosen] += 1
        if chosen in caps:
            capped_placed[chosen] = capped_placed.get(chosen, 0) + 1
    return placed

# Run N seeds
N = 25
print(f'\nRunning {N} simulated seeds...')
all_counters = []
for seed in range(50000, 50000 + N):
    all_counters.append(run_one_seed(seed))

# Aggregate stats
print()
print(f'=== Capped-chr fill rates across {N} seeds ===')
print(f'{"chr":7s} {"cap":>4s}  {"name":30s} {"avg":>5s} {"min":>4s} {"max":>4s} {"hit%":>5s}')
for cp in sorted(caps, key=lambda c: (caps[c], c)):
    cap_val = caps[cp]
    counts = [ctr.get(cp, 0) for ctr in all_counters]
    avg = statistics.mean(counts)
    mn, mx = min(counts), max(counts)
    hit_pct = 100.0 * sum(1 for n in counts if n > 0) / N
    name = tags.get(cp, {}).get('name', cp)[:30]
    # Flag anomalies
    flag = ''
    if mx > cap_val: flag = ' ⚠ OVER CAP'
    elif avg < cap_val * 0.4: flag = ' (low fill)'
    print(f'  {cp:6s} {cap_val:>4d}  {name:30s} {avg:>5.2f} {mn:>4d} {mx:>4d} {hit_pct:>4.0f}%{flag}')

# Top uncapped placements (look for swarm potential)
print()
print(f'=== Top uncapped chrs by avg placements/seed ===')
uncapped_totals = Counter()
for ctr in all_counters:
    for cp, n in ctr.items():
        if cp not in caps:
            uncapped_totals[cp] += n
top_uncapped = sorted(uncapped_totals.items(), key=lambda x: -x[1])[:25]
for cp, total in top_uncapped:
    avg = total / N
    counts = [ctr.get(cp, 0) for ctr in all_counters]
    mx = max(counts)
    tier = tags.get(cp, {}).get('tier', '?')
    name = tags.get(cp, {}).get('name', cp)[:30]
    print(f'  {cp:6s} {tier:11s} {name:30s} avg={avg:5.2f} max={mx:3d}')

# Variety per seed
print()
print(f'=== Variety per seed (distinct chr count) ===')
distinct_counts = [len(ctr) for ctr in all_counters]
print(f'  Distinct chrs/seed: avg={statistics.mean(distinct_counts):.1f}, '
      f'min={min(distinct_counts)}, max={max(distinct_counts)}')

# Capped vs uncapped placement distribution
print()
total_placements = sum(sum(ctr.values()) for ctr in all_counters)
capped_placements = sum(sum(n for cp, n in ctr.items() if cp in caps) for ctr in all_counters)
print(f'Total placements across {N} seeds: {total_placements}')
print(f'  from capped chrs:   {capped_placements} ({100*capped_placements/total_placements:.1f}%)')
print(f'  from uncapped chrs: {total_placements-capped_placements} ({100*(total_placements-capped_placements)/total_placements:.1f}%)')
