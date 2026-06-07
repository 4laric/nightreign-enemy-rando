#!/usr/bin/env python3
"""emit_hp_overrides.py — generate data/npcparam_hp_overrides.csv.

Heritage and post-DLC imports run hotter than vanilla NR's own boss
tier. Audit numbers (HP medians by source × tier, June 2026):

    tier         vanilla NR   heritage    post_dlc_dump
    -----------  -----------  ----------  --------------
    field_boss          1943        1599           1551
    night_boss          1745        2489 (+43%)    2880 (+65%)
    miniboss             668         767 (+15%)    1429 (+114%)

Plus two extreme outliers:
    c5170 Furnace Golem  (er_heritage)  HP 12800   = 5.70x vanilla p75
    c4504 Elder Greyoll  (post_dlc_dump) HP 12440   = 4.93x vanilla p75

The dump-of-ER-NpcParam approach used by the heritage pipeline copied
HP unchanged from the source game. ER's HP curve is calibrated for a
single-player run with rune-leveled stats; NR runs at fixed
session-rank scaling where HP-as-difficulty translates to
slog-tax-as-difficulty. Bringing imports onto NR's own HP curve makes
them feel like NR bosses rather than ER tourists.

Policy
======
Per tier, set HP cap to the vanilla NR (source == 'nr_placed', base-
game origin only) p75 for that tier. Apply only to imports — vanilla
NR chrs are never touched, even when individual outliers exceed the
cap (e.g. some nr_placed nightlords).

Caps (computed from current data/nr_enemy_tags.json + regulation):

    miniboss     1164
    field_boss   2247
    night_boss   2521
    nightlord    3686

For each in-scope cp:
  - Inspect ALL variants' hp values.
  - If max(variant_hps) > tier_cap: scale ratio = tier_cap / max_hp.
  - Apply ratio uniformly to every variant of the cp. Preserves the
    within-cp ranking (phase-2 boss stays harder than phase-1, etc.)
    while flattening the cap-violating peak.

This is per-cp not per-variant: scaling each variant independently
would flatten phase transitions and break the relative profile of
multi-stage bosses.

Scope (which sources get scaled)
================================
Anything whose tags `_source` is NOT 'nr_placed'. In practice that's:
  heritage / post_dlc_dump / er_heritage_port_v0_27_0 / manual_tag /
  manual_retier_v0.24.100

The 'manual_*' sources are small (≤16 entries total) but get included
on the same rule for consistency. Empirically all are below the cap
anyway.

Output
======
data/npcparam_hp_overrides.csv with columns ID,hp. Only variants
whose hp actually changed are emitted (minimal diff vs vanilla).
Import in Smithbox as a NpcParam field patch (hp).

Caveats
=======
- Phase-transition thresholds in EMEVD are typically expressed as %HP,
  so a uniform scaling preserves them. If an EMEVD event keys off an
  ABSOLUTE HP number (rare but possible), this scaling would shift
  that trigger. None known at time of writing.
- Some bosses have hp set deliberately low for cinematic / staged
  encounters (e.g. 1-HP phase placeholders). The cap is one-sided
  (upper bound only) — these are unaffected.
- `defenseScale` and other tankiness fields are NOT touched. If
  bosses still feel slog-y after this pass, those are the next levers.

Usage
=====
    python3 dev/emit_hp_overrides.py            # apply, write the CSV
    python3 dev/emit_hp_overrides.py --check    # report only, write nothing
    python3 dev/emit_hp_overrides.py --tier-caps miniboss=1300  field_boss=2500
                                                # override per-tier caps

Deterministic and idempotent: a second run with no underlying changes
produces an identical CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

TAGS_JSON = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')
ROSTER_JSON = os.path.join(REPO_ROOT, 'data', 'nr_enemy_roster.json')
NPC_CSV = os.path.join(REPO_ROOT, 'data', 'NpcParam.csv')
OUT_CSV = os.path.join(REPO_ROOT, 'data', 'npcparam_hp_overrides.csv')

# Vanilla baselines — recomputed from the current data each run. These
# are FALLBACK defaults that can be overridden via --tier-caps; the
# runtime audit (--check or normal mode) reprints the live numbers.
DEFAULT_TIER_CAPS = {
    'miniboss':    1164,   # vanilla NR p75
    'field_boss':  2247,   # vanilla NR p75
    'night_boss':  2521,   # vanilla NR p75
    'nightlord':   3686,   # vanilla NR p75
}

VANILLA_SOURCE = 'nr_placed'
# v0.31: tiers that get a two-sided clamp (p50 floor + p75 cap) on the
# per-cp-max basis. Other tiers keep the legacy variant-level cap (reduce-only).
BAND_TIERS = ('field_boss', 'night_boss')


def load_inputs():
    with open(TAGS_JSON) as f:
        tags = json.load(f)
    with open(ROSTER_JSON) as f:
        roster = json.load(f)
    npc_by_id = {}
    with open(NPC_CSV, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                npc_by_id[int(row['ID'])] = row
            except (ValueError, KeyError):
                pass
    return tags, roster, npc_by_id


def cp_to_variants(roster):
    """Build cp -> [npc_param_id, ...] from the roster's all_variants."""
    out = defaultdict(list)
    variants = roster.get('all_variants', [])
    for v in variants:
        cp = v.get('c_prefix')
        nid = v.get('npc_param_id')
        if cp and nid is not None:
            out[cp].append(int(nid))
    return out


def hp_of(npc_by_id, nid):
    row = npc_by_id.get(nid)
    if row is None:
        return None
    try:
        return int(row.get('hp', '0'))
    except (ValueError, TypeError):
        return None


def parse_tier_caps_arg(args_list):
    """Parse --tier-caps name=value strings, return dict overlay."""
    out = {}
    for s in args_list:
        if '=' not in s:
            raise SystemExit(f'--tier-caps arg malformed: {s!r}')
        k, v = s.split('=', 1)
        out[k.strip()] = int(v.strip())
    return out


def percpmax_band(tags, cp_variants, npc_by_id, tier, source=VANILLA_SOURCE):
    """Return (p50, p75) of the PER-CP representative HP (max variant per cp)
    for `source` chrs in `tier`, or None. Per-cp-max is the right lens for a
    boss's full-health value — pooling raw variants (the legacy cap basis)
    mixes each boss's difficulty-variants together and understates the tier.
    """
    reps = []
    for cp, t in tags.items():
        if (t or {}).get('tier') != tier:
            continue
        if (t or {}).get('_source') != source:
            continue
        hs = [hp_of(npc_by_id, nid) for nid in cp_variants.get(cp, [])]
        hs = [h for h in hs if h is not None and h > 100]
        if hs:
            reps.append(max(hs))
    if not reps:
        return None
    reps.sort()
    pct = lambda p: reps[min(len(reps) - 1, int(round(p * (len(reps) - 1))))]
    return pct(0.50), pct(0.75)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true',
                    help='Report only; do not write the CSV.')
    ap.add_argument('--tier-caps', nargs='*', default=[],
                    help='Override per-tier HP caps (downward clamp). '
                    'Format: miniboss=1300 field_boss=2500 ...')
    ap.add_argument('--tier-floors', nargs='*', default=[],
                    help='Override per-tier HP floors (upward clamp, band '
                    'tiers only). Format: field_boss=2400 night_boss=2500 ...')
    args = ap.parse_args()

    tier_caps_override = parse_tier_caps_arg(args.tier_caps)
    tier_floors_override = parse_tier_caps_arg(args.tier_floors)

    tags, roster, npc_by_id = load_inputs()
    cp_variants = cp_to_variants(roster)

    # Compute caps from live data unless overridden. This keeps the
    # tool self-consistent — if vanilla NR's roster shifts (new chr
    # added, retier, etc.), the caps move with it.
    computed_caps = {}
    for tier in DEFAULT_TIER_CAPS:
        live_hps = []
        for cp, t in tags.items():
            if (t or {}).get('tier') != tier: continue
            if (t or {}).get('_source') != VANILLA_SOURCE: continue
            for nid in cp_variants.get(cp, []):
                hp = hp_of(npc_by_id, nid)
                if hp is not None and hp > 100:
                    live_hps.append(hp)
        if live_hps:
            live_hps.sort()
            computed_caps[tier] = live_hps[3*len(live_hps)//4]
        else:
            # Fallback to hardcoded if no data available
            computed_caps[tier] = DEFAULT_TIER_CAPS[tier]

    # v0.31: two-sided clamp for the boss tiers the player measures imports
    # against. For BAND_TIERS, recompute the cap on the consistent per-cp-max
    # basis (p75) and add a p50 FLOOR so cold imports — the ER/SoTE "tourists"
    # that ran below vanilla — are scaled UP to the median placed vanilla boss
    # rather than left soft. Other tiers keep the legacy variant-level cap and
    # stay reduce-only. Floors apply to imports only (vanilla is never touched)
    # and scale uniformly per cp, so phase-2 stays above phase-1.
    tier_floors = {}
    for tier in BAND_TIERS:
        band = percpmax_band(tags, cp_variants, npc_by_id, tier)
        if band:
            p50, p75 = band
            tier_floors[tier] = p50
            computed_caps[tier] = p75

    tier_caps = dict(computed_caps)
    tier_caps.update(tier_caps_override)
    tier_floors.update(tier_floors_override)

    print(f'HP overrides — tier caps (downward): {tier_caps}')
    print(f'               band floors (p50, upward): {tier_floors}')
    if tier_caps_override:
        print(f'  (caller overrode --tier-caps: {tier_caps_override})')
    if tier_floors_override:
        print(f'  (caller overrode --tier-floors: {tier_floors_override})')
    print(f'  (live vanilla NR caps from current data: {computed_caps})')
    print(f'Loaded: {len(tags)} cps in tags, '
          f'{sum(len(v) for v in cp_variants.values())} variants, '
          f'{len(npc_by_id)} NpcParam rows\n')

    # Plan the override set
    overrides = []  # (variant_id, old_hp, new_hp, cp, tier)
    n_scaled_cps = 0
    n_skipped = 0
    for cp, t in sorted(tags.items()):
        tier = (t or {}).get('tier')
        source = (t or {}).get('_source')
        if tier not in tier_caps:
            continue
        if source == VANILLA_SOURCE:
            continue
        # Collect variants
        var_hps = []
        for nid in cp_variants.get(cp, []):
            hp = hp_of(npc_by_id, nid)
            if hp is not None and hp > 0:
                var_hps.append((nid, hp))
        if not var_hps:
            continue
        max_hp = max(h for _, h in var_hps)
        cap = tier_caps[tier]
        floor = tier_floors.get(tier)
        if max_hp > cap:
            ratio = cap / max_hp          # hot import — clamp down to p75
        elif floor is not None and max_hp < floor:
            ratio = floor / max_hp        # cold import — floor up to vanilla p50
        else:
            n_skipped += 1
            continue
        n_scaled_cps += 1
        for nid, old_hp in var_hps:
            new_hp = max(1, int(round(old_hp * ratio)))
            if new_hp != old_hp:
                overrides.append((nid, old_hp, new_hp, cp, tier))

    # Print summary
    print(f'\n=== balance pass result ===')
    print(f'  cps scaled (max > tier cap):     {n_scaled_cps}')
    print(f'  cps in-scope but under cap:      {n_skipped}')
    print(f'  variant overrides written:       {len(overrides)}')

    # Show the worst-affected cps
    by_cp = defaultdict(list)
    for o in overrides:
        by_cp[o[3]].append(o)
    worst = sorted(by_cp.items(),
                   key=lambda kv: -max(o[1] for o in kv[1]))[:15]
    print(f'\n=== top 15 cps by old-max HP ===')
    print(f'  {"cp":<8}{"tier":<12}{"max_old":>9}  →  {"max_new":>9}   {"name":<30}')
    for cp, items in worst:
        old_max = max(o[1] for o in items)
        new_max = max(o[2] for o in items)
        name = (tags.get(cp, {}) or {}).get('name', '')[:28]
        print(f'  {cp:<8}{items[0][4]:<12}{old_max:>9}  →  {new_max:>9}   {name}')

    if args.check:
        print(f'\n--check mode: not writing {OUT_CSV}')
        return

    # Write CSV
    with open(OUT_CSV, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ID', 'hp'])
        for nid, old_hp, new_hp, cp, tier in sorted(overrides):
            w.writerow([nid, new_hp])
    print(f'\nWrote {OUT_CSV} ({len(overrides)} rows).')
    print(f'Import via Smithbox: open NpcParam, paste-overlay this CSV.')


if __name__ == '__main__':
    main()
