#!/usr/bin/env python3
"""emit_has_reward.py — re-derive the has_reward engine flag from chr tier.

Unlike getSoul (a one-off regulation.bin patch emitted as a CSV),
has_reward is *pure engine data*: a boolean the rando's variant-selection
logic reads to bias slot assignments toward rewarded encounters. It is
NEVER written to regulation.bin. This script re-derives it across the
three data files that carry it, from a single rule, so the flag stops
drifting between files and between derivation definitions.

This replaces the field-sniffing in dev/patch_mmv_has_reward.py, which
(a) used a different rule than the nr_enemy_tags.json scan, (b) only
covered mmv_imports.json, and (c) was destructive — it had no way for a
manual value to survive a re-run.

Rule
====
A chr is has_reward=True iff its tier is miniboss or above:

    BOSS_REWARD_TIERS = {miniboss, field_boss, night_boss, nightlord}

Everything at grunt / trash / cinematic / non_combat / mount_component
is has_reward=False.

Tier comes from data/nr_enemy_tags.json. MMV variants carry no tier —
MMV is a cross-game *boss-port* mod, so every import is boss-tier by
construction — so the rule yields True for them. Genuine exceptions go
in data/has_reward_overrides.json and are applied LAST; they survive
re-derivation.

Source of truth for the tier set
================================
If oops_v3 defines V3_HAS_REWARD_TIERS, that is used (mirrors how
emit_getsoul_overrides.py reads V3_GETSOUL_TIER_FLOORS from oops_v3).
Otherwise the BOSS_REWARD_TIERS default below is used and the script
prints a note suggesting you promote it into oops_v3.py.

Files updated
=============
  data/nr_enemy_tags.json     — has_reward per c-prefix
  data/nr_enemy_roster.json   — has_reward per variant in all_variants
  data/mmv_imports.json       — has_reward per MMV variant

Override file
=============
data/has_reward_overrides.json:
  { "by_c_prefix":     { "c4640": true  },
    "by_npc_param_id": { "20300000": false } }
Precedence: by_npc_param_id  >  by_c_prefix  >  tier rule.

Usage
=====
    python3 dev/emit_has_reward.py            # apply, write the three files
    python3 dev/emit_has_reward.py --check    # report only, write nothing

Deterministic and idempotent: a second run with no override edits is a
no-op.
"""
import json
import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

TAGS_JSON      = os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')
ROSTER_JSON    = os.path.join(REPO_ROOT, 'data', 'nr_enemy_roster.json')
MMV_JSON       = os.path.join(REPO_ROOT, 'data', 'mmv_imports.json')
OVERRIDES_JSON = os.path.join(REPO_ROOT, 'data', 'has_reward_overrides.json')

# Default tier set — "miniboss and above". Used only if oops_v3 does not
# expose V3_HAS_REWARD_TIERS. To fully mirror the getSoul pattern, add
#     V3_HAS_REWARD_TIERS = frozenset({'miniboss','field_boss','night_boss','nightlord'})
# to oops_v3.py and this script will pick it up automatically.
BOSS_REWARD_TIERS = frozenset({'miniboss', 'field_boss', 'night_boss', 'nightlord'})

# Tiers that legitimately exist below the boss line. Any tier NOT in
# BOSS_REWARD_TIERS and NOT here is "unknown" and gets flagged loudly
# rather than silently treated as has_reward=False.
KNOWN_NONBOSS_TIERS = frozenset({'grunt', 'trash', 'cinematic',
                                 'non_combat', 'mount_component'})


def load_json(path, required=True):
    if not os.path.isfile(path):
        if required:
            print(f"ERROR: required input missing: {path}")
            sys.exit(1)
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def resolve_tier_set():
    """Mirror emit_getsoul_overrides.py: prefer the constant in oops_v3."""
    try:
        import oops_v3
        s = getattr(oops_v3, 'V3_HAS_REWARD_TIERS', None)
        if s:
            return frozenset(s), 'oops_v3.V3_HAS_REWARD_TIERS'
    except Exception:
        pass
    return BOSS_REWARD_TIERS, 'emit_has_reward.BOSS_REWARD_TIERS (default)'


def main():
    check_only = '--check' in sys.argv[1:]

    boss_tiers, tier_src = resolve_tier_set()
    print(f"Tier set source: {tier_src}")
    print(f"has_reward=True tiers: {sorted(boss_tiers)}\n")

    tags   = load_json(TAGS_JSON)
    roster = load_json(ROSTER_JSON)
    mmv    = load_json(MMV_JSON)
    ov     = load_json(OVERRIDES_JSON, required=False) or {}
    ov_cp  = ov.get('by_c_prefix', {})
    ov_id  = {str(k): v for k, v in ov.get('by_npc_param_id', {}).items()}

    # --- the rule -----------------------------------------------------
    def rule_for_tier(tier):
        return tier in boss_tiers

    def decide(tier_value, c_prefix, npc_param_id, mmv_default):
        """Return (value, reason). Override > tier rule > mmv default."""
        if npc_param_id is not None and str(npc_param_id) in ov_id:
            return bool(ov_id[str(npc_param_id)]), 'override:npc_param_id'
        if c_prefix in ov_cp:
            return bool(ov_cp[c_prefix]), 'override:c_prefix'
        if tier_value is not None:
            return rule_for_tier(tier_value), f'tier:{tier_value}'
        return mmv_default, 'mmv-default(boss-port mod)'

    unknown_tiers = Counter()
    flips = {'tags': 0, 'roster': 0, 'mmv': 0}
    ov_applied = Counter()

    # --- nr_enemy_tags.json (per c-prefix) ----------------------------
    tag_true = 0
    for cp, entry in tags.items():
        if not isinstance(entry, dict):
            continue
        tier = entry.get('tier')
        if tier is not None and tier not in boss_tiers \
                and tier not in KNOWN_NONBOSS_TIERS:
            unknown_tiers[tier] += 1
        val, reason = decide(tier, cp, None, mmv_default=False)
        if reason.startswith('override'):
            ov_applied[reason] += 1
        if entry.get('has_reward') != val:
            flips['tags'] += 1
        if not check_only:
            entry['has_reward'] = val
        tag_true += int(val)

    # --- nr_enemy_roster.json (all_variants) --------------------------
    ros_true = 0
    for v in roster.get('all_variants', []):
        cp = v.get('c_prefix')
        tier = tags.get(cp, {}).get('tier') if isinstance(tags.get(cp), dict) else None
        val, reason = decide(tier, cp, v.get('npc_param_id'), mmv_default=True)
        if reason.startswith('override'):
            ov_applied[reason] += 1
        if v.get('has_reward') != val:
            flips['roster'] += 1
        if not check_only:
            v['has_reward'] = val
        ros_true += int(val)

    # --- mmv_imports.json (variants) ----------------------------------
    # MMV carries no tier; MMV is a cross-game boss-port mod, so absent
    # an override every MMV variant is boss-tier -> has_reward=True.
    mmv_true = 0
    mmv_default_count = 0
    for v in mmv.get('variants', []):
        cp = v.get('c_prefix')
        tier = tags.get(cp, {}).get('tier') if isinstance(tags.get(cp), dict) else None
        val, reason = decide(tier, cp, v.get('npc_param_id'), mmv_default=True)
        if reason.startswith('override'):
            ov_applied[reason] += 1
        if reason.startswith('mmv-default'):
            mmv_default_count += 1
        if v.get('has_reward') != val:
            flips['mmv'] += 1
        if not check_only:
            v['has_reward'] = val
        mmv_true += int(val)

    # --- write --------------------------------------------------------
    if not check_only:
        for path, obj in ((TAGS_JSON, tags), (ROSTER_JSON, roster),
                           (MMV_JSON, mmv)):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(obj, f, indent=2, ensure_ascii=False)
                f.write('\n')

    # --- report -------------------------------------------------------
    mode = 'CHECK (no files written)' if check_only else 'APPLIED'
    print(f"=== {mode} ===")
    print(f"nr_enemy_tags.json    {len(tags)} prefixes   "
          f"has_reward=True: {tag_true}   flips: {flips['tags']}")
    print(f"nr_enemy_roster.json  {len(roster.get('all_variants', []))} variants  "
          f"has_reward=True: {ros_true}   flips: {flips['roster']}")
    print(f"mmv_imports.json      {len(mmv.get('variants', []))} variants   "
          f"has_reward=True: {mmv_true}   flips: {flips['mmv']}")
    print(f"  (of which {mmv_default_count} MMV variants took the "
          f"boss-port default; the rest were overridden)")
    if ov_applied:
        print("\nOverrides applied:")
        for r, n in sorted(ov_applied.items()):
            print(f"  {r}: {n}")
    else:
        print("\nNo overrides applied (data/has_reward_overrides.json "
              "empty or absent).")
    if unknown_tiers:
        print(f"\nWARNING: tier value(s) not in BOSS_REWARD_TIERS or "
              f"KNOWN_NONBOSS_TIERS — treated as non-boss, please verify: "
              f"{dict(unknown_tiers)}")
    if tier_src.endswith('(default)'):
        print("\nNote: oops_v3 has no V3_HAS_REWARD_TIERS. To make oops_v3 "
              "the single source of truth (as it is for getSoul floors), "
              "add:\n    V3_HAS_REWARD_TIERS = frozenset("
              f"{set(sorted(boss_tiers))})")


if __name__ == '__main__':
    main()
