"""
sim_cap_ab.py — A/B compare v0.25.2 cap state vs v0.25.3 cap state for
heritage NB hit rates. Same simulator approach as sim_cap_distribution.py
but runs each seed under both cap configurations and reports the delta.

The v0.25.2 cap snapshot is reconstructed by reverting the v0.25.3
changes locally (cap=1 for heritage NBs, no caps for the 18 newly-
capped boss chrs).

Output:
  - Heritage NB hit rates: v0.25.2 vs v0.25.3 side-by-side
  - "Floods unlocked" — did newly-capped chrs really go from uncapped
    swarm to bounded?
  - Aggregate variety stats
"""
import importlib.util
import json
import random
from collections import Counter, defaultdict
import statistics

spec = importlib.util.spec_from_file_location('o', 'oops_v3.py')
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)

preserve_msbs = o.V3_OVERLAY_PRESERVE_VANILLA_MSBS
preserve_slots = o.V3_PRESERVE_SLOTS
tags = json.load(open('data/nr_enemy_tags.json'))
# v0.26.x: V3_TAG_OVERRIDES removed — tier already in JSON

MMV_NB_FALLBACK = {
    'c4511': {'tier': 'night_boss', 'variants': 1, 'name': 'Lichdragon Fortissax'},
    'c5000': {'tier': 'night_boss', 'variants': 1, 'name': 'Commander Gaius'},
    'c5030': {'tier': 'night_boss', 'variants': 1, 'name': 'Romina, Saint of the Bud'},
    'c5051': {'tier': 'night_boss', 'variants': 1, 'name': 'Midra, Lord of Frenzied Flame'},
    'c5200': {'tier': 'night_boss', 'variants': 1, 'name': 'Metyr, Mother of Fingers'},
    'c8300': {'tier': 'night_boss', 'variants': 1, 'name': 'Dragonslayer Armor'},
}
for cp, info in MMV_NB_FALLBACK.items():
    if cp not in tags: tags[cp] = info

# Build eligible slot list
eligible = []
for (msb, pi), entry in o.V3_BOSS_SLOT_CATALOG.items():
    if msb in preserve_msbs: continue
    if (msb, pi) in preserve_slots: continue
    cp = entry.get('cp')
    if not cp: continue
    tier = entry.get('tier','?')
    if tier in ('remembrance','named_boss','fieldboss','noklateo',
                'ruins_boss','castle_interior','encampment','crater',
                'fort_suffix','cathedral','mountaintop','fort_boss',
                'nightboss','boss_suffix'):
        eligible.append({'msb': msb, 'pi': pi, 'src_cp': cp, 'tier': tier})

SLOT_TO_TARGET_TIERS = {
    'remembrance':       {'night_boss','field_boss','miniboss'},
    'named_boss':        {'night_boss','field_boss','miniboss'},
    'fieldboss':         {'night_boss','field_boss','miniboss'},
    'noklateo':          {'night_boss','field_boss','miniboss'},
    'ruins_boss':        {'field_boss','miniboss'},
    'castle_interior':   {'night_boss','field_boss','miniboss'},
    'encampment':        {'field_boss','miniboss'},
    'crater':            {'night_boss','field_boss','miniboss'},
    'fort_suffix':       {'field_boss','miniboss'},
    'cathedral':         {'night_boss','field_boss','miniboss'},
    'mountaintop':       {'night_boss','field_boss','miniboss'},
    'fort_boss':         {'field_boss','miniboss'},
    'nightboss':         {'night_boss'},
    'boss_suffix':       {'night_boss','field_boss'},
}
excluded = (getattr(o,'V3_EXCLUDE_PREFIXES',set())
            | getattr(o,'V3_EXCLUDE_TARGET_PREFIXES',set())
            | getattr(o,'V3_GHOST_EXCLUDE_TARGET_PREFIXES',set()))

chrs_by_tier = defaultdict(list)
for cp, info in tags.items():
    t = info.get('tier')
    if t not in ('night_boss','field_boss','miniboss'): continue
    if cp in excluded: continue
    if info.get('variants', 0) == 0: continue
    chrs_by_tier[t].append(cp)

slot_pools = {}
for tk, tts in SLOT_TO_TARGET_TIERS.items():
    pool = []
    for t in tts: pool.extend(chrs_by_tier[t])
    slot_pools[tk] = pool

GLOBAL_CAP = o.V3_TARGET_PLACEMENT_CAP

# ------------------------------------------------------------
# Reconstruct v0.25.2 cap state from v0.25.3 by reverting changes
# ------------------------------------------------------------
CAPS_v0_25_3 = dict(o.V3_UNIQUE_TARGET_CAPS)

# v0.25.3 heritage bumps (1→2): revert to 1
HERITAGE_BUMPS = ['c7700','c7710','c7800','c7820','c7900','c7920',
                  'c8300','c4511','c5000','c5030','c5051','c5200']

# v0.25.3 newly-added boss caps: remove entirely
NEW_v0_25_3_CAPS = ['c3050','c2500','c4980','c4130','c5810','c4650',
                    'c3100','c4770','c4580','c3560','c3570','c5011',
                    'c4353','c2130','c7100','c4620','c4811','c4140']

CAPS_v0_25_2 = dict(CAPS_v0_25_3)
for cp in HERITAGE_BUMPS:
    if cp in CAPS_v0_25_2: CAPS_v0_25_2[cp] = 1
for cp in NEW_v0_25_3_CAPS:
    CAPS_v0_25_2.pop(cp, None)

# Also need to revert the c4601 Troll Knight retier — in v0.25.2 it was
# tier=grunt so cap=6 was dead. For accurate sim, treat its cap as if
# absent in v0.25.2 (since the grunt tier was filtering it out anyway).
# Actually keep cap=6 in both — the SIM uses miniboss tier (after override)
# so this difference doesn't matter to the simulator. Note in report.

print(f'v0.25.2 caps: {len(CAPS_v0_25_2)} entries')
print(f'v0.25.3 caps: {len(CAPS_v0_25_3)} entries (+{len(CAPS_v0_25_3)-len(CAPS_v0_25_2)})')

def run_one_seed(seed, caps):
    rng = random.Random(seed)
    placed = Counter()
    capped_placed = {}
    slot_order = list(eligible)
    rng.shuffle(slot_order)
    for s in slot_order:
        pool = list(slot_pools.get(s['tier'], []))
        pool = [cp for cp in pool
                if capped_placed.get(cp, 0) < caps.get(cp, 999)]
        pool = [cp for cp in pool if placed.get(cp, 0) < GLOBAL_CAP]
        if not pool: continue
        chosen = rng.choice(pool)
        placed[chosen] += 1
        if chosen in caps:
            capped_placed[chosen] = capped_placed.get(chosen, 0) + 1
    return placed

N = 50  # more seeds for better statistics
seeds = list(range(70000, 70000+N))

results_v2 = [run_one_seed(s, CAPS_v0_25_2) for s in seeds]
results_v3 = [run_one_seed(s, CAPS_v0_25_3) for s in seeds]

def stats(results, cp):
    counts = [r.get(cp, 0) for r in results]
    return {
        'avg': statistics.mean(counts),
        'min': min(counts), 'max': max(counts),
        'hit_pct': 100.0 * sum(1 for c in counts if c > 0) / len(counts),
    }

# Report 1: Heritage NB hit rates (the bump)
print()
print('=' * 78)
print('A/B: HERITAGE NB BUMP (cap=1 → cap=2)')
print('=' * 78)
print(f'{"chr":7s} {"name":28s} {"v0.25.2":>18s} {"v0.25.3":>18s} {"delta":>10s}')
heritage_all = HERITAGE_BUMPS + ['c7910']  # include c7910 (held at cap=1)
for cp in heritage_all:
    nm = tags.get(cp, {}).get('name', cp)[:28]
    s2, s3 = stats(results_v2, cp), stats(results_v3, cp)
    cap2 = CAPS_v0_25_2.get(cp, '-')
    cap3 = CAPS_v0_25_3.get(cp, '-')
    v2 = f'cap={cap2} {s2["avg"]:.2f} ({s2["hit_pct"]:.0f}%)'
    v3 = f'cap={cap3} {s3["avg"]:.2f} ({s3["hit_pct"]:.0f}%)'
    delta = f'+{s3["avg"]-s2["avg"]:.2f}/seed'
    flag = ''
    if cp == 'c7910': flag = '  (held at 1 — paired-only)'
    print(f'  {cp:6s} {nm:28s} {v2:>18s} {v3:>18s} {delta:>10s}{flag}')

# Report 2: Newly-capped chrs (the bounded swarm)
print()
print('=' * 78)
print('A/B: NEWLY-CAPPED BOSS CHRS (uncapped → cap=N)')
print('=' * 78)
print(f'{"chr":7s} {"name":28s} {"v0.25.2 (uncapped)":>22s} {"v0.25.3":>20s}')
for cp in NEW_v0_25_3_CAPS:
    nm = tags.get(cp, {}).get('name', cp)[:28]
    s2, s3 = stats(results_v2, cp), stats(results_v3, cp)
    cap3 = CAPS_v0_25_3[cp]
    v2 = f'avg={s2["avg"]:.2f} max={s2["max"]:d}'
    v3 = f'cap={cap3} avg={s3["avg"]:.2f} max={s3["max"]:d}'
    flag = ''
    if s2['max'] >= 8: flag = '  ← was swarming'
    elif s2['max'] >= cap3 + 2: flag = '  ← bounded down'
    elif s2['avg'] > s3['avg'] * 1.2: flag = '  ← reduced'
    print(f'  {cp:6s} {nm:28s} {v2:>22s} {v3:>20s}{flag}')

# Report 3: Heritage NB pool aggregate fill (how many heritage NBs show up per seed?)
print()
print('=' * 78)
print('AGGREGATE: HERITAGE NB ROSTER FILL PER SEED')
print('=' * 78)
print('  How many of the 13 heritage NBs (DS + SoTE MMVs) appear at all per seed?')
print(f'  (Higher = more variety; sums to <=13 since each chr is binary "appears or not")')
def hit_count(results, cp_list):
    return [sum(1 for cp in cp_list if r.get(cp, 0) > 0) for r in results]
hc_v2 = hit_count(results_v2, heritage_all)
hc_v3 = hit_count(results_v3, heritage_all)
print(f'  v0.25.2: avg {statistics.mean(hc_v2):.1f} / 13 heritage NBs per seed  (min {min(hc_v2)}, max {max(hc_v2)})')
print(f'  v0.25.3: avg {statistics.mean(hc_v3):.1f} / 13 heritage NBs per seed  (min {min(hc_v3)}, max {max(hc_v3)})')
total_v2 = sum(sum(r.get(cp, 0) for cp in heritage_all) for r in results_v2)
total_v3 = sum(sum(r.get(cp, 0) for cp in heritage_all) for r in results_v3)
print(f'  Heritage NB total placements across {N} seeds: v0.25.2={total_v2}, v0.25.3={total_v3} (+{total_v3-total_v2})')

# Report 4: Total swarm of newly-capped chrs
print()
print('=' * 78)
print('AGGREGATE: NEWLY-CAPPED CHR SWARM REDUCTION')
print('=' * 78)
total_swarm_v2 = sum(sum(r.get(cp, 0) for cp in NEW_v0_25_3_CAPS) for r in results_v2)
total_swarm_v3 = sum(sum(r.get(cp, 0) for cp in NEW_v0_25_3_CAPS) for r in results_v3)
print(f'  Newly-capped chrs total placements across {N} seeds:')
print(f'    v0.25.2 (uncapped): {total_swarm_v2}')
print(f'    v0.25.3 (capped):   {total_swarm_v3}  ({total_swarm_v3-total_swarm_v2:+d}, '
      f'{100*(total_swarm_v3-total_swarm_v2)/total_swarm_v2:+.1f}%)')

# Report 5: Variety unchanged?
print()
print('=' * 78)
print('VARIETY HEALTH (distinct chrs / seed)')
print('=' * 78)
v2_var = [len(r) for r in results_v2]
v3_var = [len(r) for r in results_v3]
print(f'  v0.25.2: avg {statistics.mean(v2_var):.1f} distinct chrs/seed '
      f'(min {min(v2_var)}, max {max(v2_var)})')
print(f'  v0.25.3: avg {statistics.mean(v3_var):.1f} distinct chrs/seed '
      f'(min {min(v3_var)}, max {max(v3_var)})')

# Bottom line
print()
print('=' * 78)
print('TLDR')
print('=' * 78)
hb_v2 = sum(s['avg'] for cp in HERITAGE_BUMPS for s in [stats(results_v2,cp)])
hb_v3 = sum(s['avg'] for cp in HERITAGE_BUMPS for s in [stats(results_v3,cp)])
print(f'  Heritage NBs (12 chrs bumped 1→2): {hb_v2:.1f} → {hb_v3:.1f} placements/seed '
      f'(+{hb_v3-hb_v2:.1f})')
print(f'  Newly-capped boss chrs (18 chrs):  {total_swarm_v2/N:.1f} → {total_swarm_v3/N:.1f} placements/seed '
      f'({(total_swarm_v3-total_swarm_v2)/N:+.1f})')
print(f'  Variety unchanged: {statistics.mean(v2_var):.1f} → {statistics.mean(v3_var):.1f} '
      f'distinct chrs/seed ({statistics.mean(v3_var)-statistics.mean(v2_var):+.1f})')
