#!/usr/bin/env python3
"""emit_atk_overrides.py — generate data/atkparam_npc_damage_overrides.csv.

The outgoing-damage companion to emit_hp_overrides.py. HP capping
shipped first because the heritage cohort was systematically over-HP'd.
This pass addresses the SECOND playtest finding: monsters dealing too
much damage per hit, with a small set of specific over-cap attacks
producing one-shot deaths.

Diagnosis
=========
Audit data (max-attack per chr, aggregated source × tier; max-attack
defined as max over (atkPhys + atkMag + atkFire + atkThun + atkDark)
across that chr's AtkParam_Npc rows):

    tier         vanilla NR   heritage    post_dlc_dump
    -----------  -----------  ----------  --------------
    field_boss   p75=450      p75=380     p75=521
    miniboss     p75=450      p75=390     p75=500
    night_boss   p75=450      p75=500     p75=999
    nightlord    p75=420      —           p75=480

Unlike HP, heritage is at parity or below on damage; the problem is
concentrated in post_dlc_dump night_boss (~2x vanilla) and a few
named individual outliers:

    c7720  Artorias            atk 7720916  =  999 phys + 999 stam
    c5220  Promised Consort R. atk 5220440  =  800 phys + 100 stam
    c4730  Starscourge Radahn  max 630
    c2120  Malenia             max 610
    c5170  Furnace Golem       max 600
    c5390  Troll (SoTE)        max 600

These read as one-shot moves in NR's session-scaled play, where the
player can't level past the source-game-tuned thresholds.

Policy
======
PER-ATTACK cap. For each AtkParam_Npc row whose:
  - row's c-prefix is in roster, tagged tier ∈ ELIGIBLE_TIERS,
  - tags `_source` ≠ 'nr_placed' (vanilla untouched),
  - row's total (phys + mag + fire + thun + dark) > tier cap,
emit a scaled-down replacement. Scale ratio = cap / total. Apply
uniformly to all damage components AND atkStam (stamina damage stays
proportional, so a "this hits hard and staggers" move stays
"this hits hard and staggers", just both reduced).

PER-ATTACK (not per-chr uniform) because attacks are different moves,
not variants of the same encounter. Clipping the single 999 move on
Artorias without touching his ~480 normal moves is precisely the goal
— preserving his combat profile while removing the one-shot risk.
This is the opposite granularity from emit_hp_overrides.py (per-cp
uniform) and intentionally so.

Caps
====
Vanilla NR p75 max-attack per tier, live-computed from current data.
Hardcoded fallback: 450 across all tiers (the live curve is flat at
~450 for miniboss/field_boss/night_boss; nightlord ~420 but only 3
chrs, not worth a special case).

Scope (which sources get scaled)
================================
Same as emit_hp_overrides.py: everything except `_source: nr_placed`.

Out of scope by exclusion:
  - c4450 Walking Mausoleum's 9999-damage kill-zone attacks
    (intentional stage-hazard mechanic, vanilla NR)
  - c8420/c8421/c8700/c8701 environmental hazards / training dummies
    (filtered by "not in tags / not in roster")

Output
======
data/atkparam_npc_damage_overrides.csv with columns:
    ID, atkPhys, atkMag, atkFire, atkThun, atkDark, atkStam

Only attacks whose damage actually changed are emitted (minimal diff).
Import via Smithbox: open AtkParam_Npc, paste-overlay this CSV.

Caveats
=======
- Status-effect buildup (atkPoison, atkBleed, etc.) is NOT touched.
  Frostbite buildup on PCR's icestorm move stays the same; only the
  raw damage falls.
- Some attacks may be "charge attacks" deliberately designed to be
  punishing but telegraphed. Clipping them to 450 removes the
  high-end of NR's risk-reward curve. If certain attacks should
  remain devastating-but-telegraphed, hand-edit the CSV after
  generation; subsequent re-runs will re-clip them (the script is
  policy-driven; per-attack carveouts aren't first-class).
- Multi-hit AOE attacks (where each tick deals damage_field amount
  per frame) compound. atkPhys=200 on a 10-tick move = 2000 cumulative.
  The single-row cap is a per-instance limit only.

Usage
=====
    python3 dev/emit_atk_overrides.py            # apply, write CSV
    python3 dev/emit_atk_overrides.py --check    # report only
    python3 dev/emit_atk_overrides.py --cap 500  # use a fixed cap
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

TAGS_JSON = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')
ROSTER_JSON = os.path.join(REPO_ROOT, 'data', 'nr_enemy_roster.json')
ATK_CSV = os.path.join(REPO_ROOT, 'data', 'AtkParam_Npc.csv')
OUT_CSV = os.path.join(REPO_ROOT, 'data', 'atkparam_npc_damage_overrides.csv')

DMG_FIELDS = ('atkPhys', 'atkMag', 'atkFire', 'atkThun', 'atkDark')
STAM_FIELD = 'atkStam'
ALL_SCALED_FIELDS = DMG_FIELDS + (STAM_FIELD,)
ELIGIBLE_TIERS = ('miniboss', 'field_boss', 'night_boss', 'nightlord')
VANILLA_SOURCE = 'nr_placed'

# Fallback if live computation fails. Flat 450 — see policy notes.
DEFAULT_TIER_CAPS = {
    'miniboss':   450,
    'field_boss': 450,
    'night_boss': 450,
    'nightlord':  450,
}


def load_inputs():
    with open(TAGS_JSON) as f:
        tags = json.load(f)
    with open(ROSTER_JSON) as f:
        roster = json.load(f)
    return tags, roster


def load_attacks():
    """Yield (id, row_dict) for every AtkParam_Npc row."""
    with open(ATK_CSV, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                nid = int(row['ID'])
            except (ValueError, KeyError):
                continue
            yield nid, row


def cp_of_attack(atk_id):
    """AtkParam_Npc convention: leading 4 digits of ID = c-prefix digits.
    e.g. 7720916 -> c7720, 5220440 -> c5220. IDs under 7 digits don't
    map to a chr (some are generic AI tick / training rows)."""
    s = str(atk_id)
    if len(s) < 7:
        return None
    return 'c' + s[:4]


def get_int(row, field):
    try:
        return int(row.get(field, 0) or 0)
    except (ValueError, TypeError):
        return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true',
                    help='Report only; do not write the CSV.')
    ap.add_argument('--cap', type=int, default=None,
                    help='Single cap value applied to all tiers '
                         '(overrides per-tier caps).')
    ap.add_argument('--tier-caps', nargs='*', default=[],
                    help='Per-tier caps. Format: miniboss=400 night_boss=500.')
    ap.add_argument('--full-row', action='store_true',
                    help='Emit the full AtkParam_Npc row for each clipped '
                         'attack (all 223 columns), with the 6 scaled fields '
                         'updated. The default 7-column CSV is enough for '
                         'Smithbox paste-overlay; --full-row is for review / '
                         'context inspection / merge into a hand-edited param.')
    args = ap.parse_args()

    tags, roster = load_inputs()

    # Build cp -> tier and tier set of in-scope cps
    in_scope_cps = {}  # cp -> tier
    for cp, t in tags.items():
        tier = (t or {}).get('tier')
        src = (t or {}).get('_source')
        if tier not in ELIGIBLE_TIERS: continue
        if src == VANILLA_SOURCE: continue
        in_scope_cps[cp] = tier

    # Load attacks and bucket by cp for vanilla-baseline computation
    attacks_by_cp = defaultdict(list)
    raw_attacks = []
    for nid, row in load_attacks():
        cp = cp_of_attack(nid)
        if cp is None: continue
        # Cache stripped row for processing
        stripped = {f: get_int(row, f) for f in ALL_SCALED_FIELDS}
        stripped['_id'] = nid
        stripped['_cp'] = cp
        raw_attacks.append(stripped)
        total = sum(stripped[f] for f in DMG_FIELDS)
        attacks_by_cp[cp].append(total)

    # Compute live caps from vanilla NR chrs' max-attack p75 per tier.
    computed_caps = {}
    for tier in ELIGIBLE_TIERS:
        max_attacks = []
        for cp, t in tags.items():
            if (t or {}).get('tier') != tier: continue
            if (t or {}).get('_source') != VANILLA_SOURCE: continue
            cp_atks = attacks_by_cp.get(cp, [])
            cp_atks = [a for a in cp_atks if a > 0]
            if cp_atks:
                max_attacks.append(max(cp_atks))
        if max_attacks:
            max_attacks.sort()
            computed_caps[tier] = max_attacks[3*len(max_attacks)//4]
        else:
            computed_caps[tier] = DEFAULT_TIER_CAPS[tier]

    # Cap resolution: --cap > --tier-caps > computed > default
    tier_caps = dict(computed_caps)
    for s in args.tier_caps:
        if '=' not in s:
            raise SystemExit(f'--tier-caps arg malformed: {s!r}')
        k, v = s.split('=', 1)
        tier_caps[k.strip()] = int(v.strip())
    if args.cap is not None:
        tier_caps = {t: args.cap for t in ELIGIBLE_TIERS}

    print(f'Damage overrides — tier caps: {tier_caps}')
    print(f'  (live vanilla NR p75 max-attack: {computed_caps})')
    print(f'Loaded: {len(tags)} cps in tags, {len(raw_attacks)} attack rows, '
          f'{len(in_scope_cps)} in-scope cps')

    # Apply per-attack cap
    overrides = []   # (atk_id, cp, tier, old_vals, new_vals, old_total, new_total)
    n_attacks_clipped = 0
    n_cps_affected = set()
    for atk in raw_attacks:
        cp = atk['_cp']
        if cp not in in_scope_cps: continue
        tier = in_scope_cps[cp]
        cap = tier_caps[tier]
        total = sum(atk[f] for f in DMG_FIELDS)
        if total <= cap: continue
        ratio = cap / total
        old_vals = {f: atk[f] for f in ALL_SCALED_FIELDS}
        new_vals = {f: max(0, int(round(atk[f] * ratio))) for f in ALL_SCALED_FIELDS}
        if new_vals == old_vals: continue
        overrides.append({
            '_id': atk['_id'], '_cp': cp, '_tier': tier,
            'old': old_vals, 'new': new_vals,
            'old_total': total, 'new_total': sum(new_vals[f] for f in DMG_FIELDS),
        })
        n_attacks_clipped += 1
        n_cps_affected.add(cp)

    # Summary
    print(f'\n=== damage cap result ===')
    print(f'  attacks clipped: {n_attacks_clipped}')
    print(f'  cps affected:    {len(n_cps_affected)}')

    # Top 15 individual attacks affected
    print(f'\n=== top 15 individual attacks by old damage ===')
    print(f'  {"atk_id":<10}{"cp":<8}{"tier":<12}{"old":>6}  →  {"new":>5}   name')
    top = sorted(overrides, key=lambda o: -o['old_total'])[:15]
    for o in top:
        name = (tags.get(o['_cp'], {}) or {}).get('name', '')[:25]
        print(f'  {o["_id"]:<10}{o["_cp"]:<8}{o["_tier"]:<12}'
              f'{o["old_total"]:>6}  →  {o["new_total"]:>5}   {name}')

    # Top 10 cps by count of clipped attacks
    by_cp = defaultdict(list)
    for o in overrides: by_cp[o['_cp']].append(o)
    print(f'\n=== top 10 cps by # clipped attacks ===')
    print(f'  {"cp":<8}{"tier":<12}{"n":>4}  {"worst_old":>9}  →  {"new":>5}   name')
    for cp, items in sorted(by_cp.items(), key=lambda kv: -len(kv[1]))[:10]:
        worst = max(items, key=lambda x: x['old_total'])
        name = (tags.get(cp, {}) or {}).get('name', '')[:25]
        print(f'  {cp:<8}{items[0]["_tier"]:<12}{len(items):>4}  '
              f'{worst["old_total"]:>9}  →  {worst["new_total"]:>5}   {name}')

    if args.check:
        print(f'\n--check mode: not writing {OUT_CSV}')
        return

    if args.full_row:
        # Re-read AtkParam_Npc.csv to grab the vanilla row schema + values.
        # For each clipped attack: copy the full row, swap the 6 scaled fields.
        with open(ATK_CSV, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames)
            vanilla_rows = {}
            for row in reader:
                try:
                    nid = int(row['ID'])
                except (ValueError, KeyError):
                    continue
                vanilla_rows[nid] = row

        # Sanity: every override's ID must exist in vanilla (it must,
        # we read it from there originally — but assert anyway).
        missing = [o['_id'] for o in overrides if o['_id'] not in vanilla_rows]
        if missing:
            raise SystemExit(f'BUG: override IDs not in AtkParam_Npc.csv: '
                             f'{missing[:5]}')

        with open(OUT_CSV, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for o in sorted(overrides, key=lambda x: x['_id']):
                row = dict(vanilla_rows[o['_id']])
                for fld in ALL_SCALED_FIELDS:
                    row[fld] = str(o['new'][fld])
                w.writerow(row)
        print(f'\nWrote {OUT_CSV} ({len(overrides)} rows, '
              f'{len(fieldnames)} cols — full AtkParam_Npc schema).')
    else:
        with open(OUT_CSV, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['ID'] + list(ALL_SCALED_FIELDS))
            for o in sorted(overrides, key=lambda x: x['_id']):
                w.writerow([o['_id']] + [o['new'][f] for f in ALL_SCALED_FIELDS])
        print(f'\nWrote {OUT_CSV} ({len(overrides)} rows).')
    print(f'Import via Smithbox: open AtkParam_Npc, paste-overlay this CSV.')


if __name__ == '__main__':
    main()
