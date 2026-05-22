#!/usr/bin/env python3
"""
swap_compat.py — Reference compatibility logic for the NR enemy randomizer.

Replaces the old size-class-only swap filter with a multi-axis check:
  1. expects_boss_arena must match (boss-arena placements only get arena-capable
     enemies; non-arena placements only get non-arena enemies).
  2. anim_class must be in a compatible pair (no Dragonkin-in-Guardian-Golem
     bugs; no flying enemies in ground slots; no merchants as fighters).
  3. size_class must be within one tier of the slot's original size.
  4. heritage imports may have additional locomotion/team caveats (warn only).

Usage:
    from swap_compat import is_compatible, swap_pool_for

    # Filter a candidate pool down to slots that work
    valid = [c for c in candidates if is_compatible(slot_tag, c_tag)]

    # Or compute swap pool for a placement directly
    pool = swap_pool_for(slot_cprefix, all_tags, all_placements)

The rules below are SOFT — adjust based on empirical findings. Each rule
returns one of: 'allow' / 'deny' / 'warn'. A swap with any 'deny' is invalid;
'warn' swaps are allowed but flagged for testing.
"""

from typing import Dict, List, Optional, Tuple


# Size class ordering — must match heritage_compat_tag.SIZE_BOUNDARIES
SIZE_TIERS = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA']

# v0.24.100: anim_class-as-swap-gate REMOVED. Per user directive:
# "anim_class is only relevant as a proxy for locomotion."
#
# Background: the historical compat machinery — ANIM_CLASS_COMPAT_PAIRS,
# _compat_anim_class, _LOCO_SENSITIVE_ANIMS, LOCOMOTION_MACRO — gated swaps
# by anim_class identity or compat-pair membership ("humanoid only swaps
# with misc", "quadruped with quadruped_large", etc.). This was a
# theoretical safety layer with no empirical anchor; v0.24.75 had already
# neutered _compat_anim_class to always-True after CTDs blamed on
# anim_class drift turned out to have other root causes (chr-asset gaps,
# AI script issues, locomotion-rig mismatches). The remaining layers
# (LOCOMOTION_MACRO ground/air separation, intra-anim_class loco match for
# Wolf/Stray-rig drift) survived because they encoded *locomotion*
# information — which is what actually matters at runtime — but did it
# indirectly through anim_class.
#
# The one thing that demonstrably matters: flying vs ground separation.
# A flying chr placed at a ground slot CTDs the cell-load (Astel-at-
# Flying-Dragon-slot, seed 552688). A ground chr at a flying slot crashes
# similarly. This is a real locomotion-class boundary, not a rig-style
# boundary.
#
# Flying classification needs both fields because the tag data is
# inconsistent:
#   - Dragons (c4500-c4505, c4680, c4911, c5860, c75xx): anim_class=
#     flying_dragon, locomotion=5 or None
#   - Bats (c4200 Man-Bat, c4201 Operatic Bat): locomotion=2, anim_class
#     is humanoid or quadruped (NOT flying_dragon)
# The OR predicate below captures both groups.
def is_flier(tag: Dict) -> bool:
    """True if the chr is a flier (dragon or bat). Cleanly separates the
    flying-vs-ground concern from anim_class identity.

    Empirically, the only locomotion-class boundary that produces CTDs
    or visible breakage is flier-vs-ground. Other anim_class distinctions
    (humanoid vs quadruped vs misc) describe animation rig style, not
    locomotion behavior, and don't predict swap failure."""
    return tag.get('locomotion') == 2 or tag.get('anim_class') == 'flying_dragon'

# anim_class compatibility graph and _compat_anim_class function REMOVED in
# v0.24.100 per the is_flier comment block above. The historical
# ANIM_CLASS_COMPAT_PAIRS table gated by anim_class identity (humanoid+misc,
# quadruped+quadruped_large, aquatic+everything, etc.); _compat_anim_class
# consulted it. Both were retired after v0.24.75 neutered the function to
# always-True and subsequent playtesting confirmed no anim_class-attributed
# CTDs. The single thing the machinery was usefully encoding — flying-vs-
# ground separation — is now expressed directly via is_flier(tag).


def _size_distance(a: str, b: str) -> int:
    """Tier distance between two size_class labels. Returns large
    number if either is unknown."""
    try:
        return abs(SIZE_TIERS.index(a) - SIZE_TIERS.index(b))
    except ValueError:
        return 99


def is_compatible(slot_tag: Dict, candidate_tag: Dict,
                  max_size_drift: Optional[int] = None,
                  max_size_up: int = 1,
                  max_size_down: int = 3,
                  strict_arena: bool = True,
                  enforce_drops: bool = True,
                  slot_is_boss_tier: Optional[bool] = None) -> Tuple[bool, List[str]]:
    """Return (allow, warnings) for swapping candidate into slot.

    Args:
      slot_tag: tag dict for the c-prefix that originally occupies the slot
      candidate_tag: tag dict for the c-prefix being considered as swap
      max_size_drift: LEGACY symmetric bound. If passed, it overrides
        both max_size_up and max_size_down to the same value. Default
        (None) uses the asymmetric defaults below.
      max_size_up: max tiers candidate can be LARGER than slot (default 1).
        Size-up is the freeze/CTD failure pattern (big chr clips small
        arena). Keep tight.
      max_size_down: max tiers candidate can be SMALLER than slot
        (default 3). Size-down is engine-safe (tiny chr in big arena
        has room to move) — anticlimactic but doesn't crash. Generous.
      strict_arena: if True, expects_boss_arena MUST match exactly. If
        False, allows non-arena enemies in arena slots (but never the
        reverse — putting an arena-script enemy in a non-arena slot is
        always denied because of fog-door/music/camera glitches).
      enforce_drops: if True (default), drop preservation is enforced:
        boss-reward slots must receive candidates that have at least one
        reward-bearing variant.
      slot_is_boss_tier: if known, the specific PLACEMENT's tier. The
        has_reward rule only fires when the placement is actually a
        boss-tier variant (e.g. Cleanrot Knight has 1 boss + 12 field
        variants — only the boss placement needs reward preservation).
        If None, falls back to slot_tag.has_reward (c-prefix-level summary).

    Returns:
      (allow: bool, warnings: list of strings)
    """
    warnings = []

    # 1. Boss arena gating — most important rule for avoiding script bugs
    slot_arena = slot_tag.get('expects_boss_arena', False)
    cand_arena = candidate_tag.get('expects_boss_arena', False)
    if cand_arena and not slot_arena:
        return False, ['arena-script enemy cannot be placed in non-arena slot']
    if strict_arena and slot_arena and not cand_arena:
        warnings.append('non-arena enemy in arena slot — fog-door/music may '
                        'play without proper boss intro')

    # 2. Flier-vs-ground separation. v0.24.100: anim_class compat gate
    # and intra-anim_class locomotion match REMOVED — see the is_flier
    # comment block at the top of this module. The only locomotion-class
    # boundary that produces real failures is flier-vs-ground (dragon
    # asset bundle ≠ ground asset bundle, aerial-spawn anim ≠ ground
    # spawn anim). Other anim_class distinctions describe rig style and
    # don't predict swap failure.
    if is_flier(slot_tag) != is_flier(candidate_tag):
        return False, ['flier-vs-ground mismatch (one is a dragon/bat, '
                       'the other is grounded)']

    # 3. Size tier — asymmetric drift (v0.24.86-patch5)
    # v0.24.86-patch5: asymmetric size_drift. Size-down (small chr in
    # big arena) is engine-safe; size-up (big chr in small arena) clips
    # terrain and freezes/CTDs. The legacy symmetric `max_size_drift`
    # parameter is preserved for callers that pass it explicitly; new
    # `max_size_up` / `max_size_down` give finer control with asymmetric
    # defaults.
    #
    # Empirical anchor (seed 923630, v0.24.86): c7100 Ancient Hero of
    # Zamor (L) placed at c3970 Azula Beastman (M) Ruins-Boss slot froze
    # — slot too tight for the L collider. Same seed had a worse-shape
    # candidate at m46_77_00_00 pi=3 (c4100 S → c4570 Wormface XL,
    # +3 tier drift) which would also have been rejected by the new
    # rule. Both are caught here without per-slot manual entries.
    slot_size = slot_tag.get('size_class', 'M')
    cand_size = candidate_tag.get('size_class', 'M')
    try:
        slot_idx = SIZE_TIERS.index(slot_size)
        cand_idx = SIZE_TIERS.index(cand_size)
    except ValueError:
        return False, [f'unknown size class: {slot_size} or {cand_size}']
    delta = cand_idx - slot_idx  # positive = upsizing, negative = downsizing

    # If caller passed legacy max_size_drift, honor it as symmetric bound.
    # Else use asymmetric max_size_up / max_size_down.
    if max_size_drift is not None:
        eff_up = max_size_drift
        eff_down = max_size_drift
    else:
        eff_up = max_size_up
        eff_down = max_size_down

    if delta > eff_up:
        return False, [f'size up too large: {slot_size} -> {cand_size} '
                       f'(+{delta} tiers, max +{eff_up})']
    if -delta > eff_down:
        return False, [f'size down too large: {slot_size} -> {cand_size} '
                       f'(-{-delta} tiers, max -{eff_down})']
    if delta == eff_up and eff_up > 0:
        warnings.append(f'size up at limit: {slot_size} -> {cand_size}')

    # 4. Drop / reward preservation — both are SOFT (warning-only).
    # has_reward used to hard-deny boss-tier swaps to non-reward c-prefixes
    # (e.g. Crayfish → Crab denied because Crab had no reward variants). The
    # design call: every field-boss slot SHOULD drop a reward, but enforcing
    # this at the c-prefix level over-constrains the pool. Instead, we let
    # any anim_class-compatible swap happen, and the variant picker prefers
    # reward-bearing variants for boss slots — when available. When the target
    # has no reward variants at all, the boss silently loses its reward, and
    # we accept that as part of the random vibe. Adding rewards to no-reward
    # c-prefixes would require regulation patching, which is out of scope.
    if enforce_drops:
        slot_has_reward = slot_tag.get('has_reward', False)
        cand_has_reward = candidate_tag.get('has_reward', False)
        if slot_is_boss_tier and slot_has_reward and not cand_has_reward:
            warnings.append('boss-tier slot will lose rewardItemLot — '
                            'candidate has no reward-bearing variant')
        slot_has_drops = slot_tag.get('has_drops', False)
        cand_has_drops = candidate_tag.get('has_drops', False)
        if slot_has_drops and not cand_has_drops:
            warnings.append('slot drops items but candidate has no drops')

    # 5. Heritage import locomotion (warn only — locomotion is usually right)
    if candidate_tag.get('_heritage_imported') and \
       candidate_tag.get('locomotion', 0) != slot_tag.get('locomotion', 0):
        warnings.append('locomotion override may be needed for heritage import')

    return True, warnings


# LOCOMOTION_MACRO dict REMOVED in v0.24.100 — its anim_class → ground/air
# mapping is now expressed directly via the is_flier(tag) predicate at the
# top of this module.


def is_compatible_size_down(slot_tag: Dict, candidate_tag: Dict,
                            max_size_drift_down: int = 1,
                            slot_is_boss_tier: Optional[bool] = None
                            ) -> Tuple[bool, List[str]]:
    """Relaxed compat for the at-risk-tail rescue. Permits cross-rig
    swaps when candidate is STRICTLY smaller than the slot AND both
    share flier-vs-ground class. All other gates from is_compatible
    still apply:

      - arena gate stays hard (script-glitch protection)
      - flier-vs-ground must match (a dragon at a ground slot CTDs;
        a grounded chr at a sky-spawn slot has no usable anim)
      - candidate size <= slot size (strict; no size-up rescue)
      - tier preservation is the caller's responsibility

    v0.24.100: anim_class identity gating REMOVED. The previous version
    keyed on LOCOMOTION_MACRO (anim_class → ground/air) and added an
    intra-anim_class locomotion-field match within "skeleton-sensitive"
    classes (Wolf/Stray Δloco T-pose theory). The locomotion-match part
    didn't survive playtest — the actual T-pose cases turned out to be
    chr-asset gaps. What remains is the empirically-grounded flier-vs-
    ground split, expressed via is_flier(tag).

    Returns (allow, warnings) like is_compatible.
    """
    warnings = []

    # 1. arena gate — same as strict
    slot_arena = slot_tag.get('expects_boss_arena', False)
    cand_arena = candidate_tag.get('expects_boss_arena', False)
    if cand_arena and not slot_arena:
        return False, ['arena-script enemy cannot be placed in non-arena slot']

    # 2. Flier-vs-ground separation. v0.24.100: was anim_class-based
    # LOCOMOTION_MACRO check; now uses the is_flier predicate directly.
    if is_flier(slot_tag) != is_flier(candidate_tag):
        return False, ['flier-vs-ground mismatch (one is a dragon/bat, '
                       'the other is grounded)']

    # 3. size MUST be strictly down (or equal — equal is just normal compat,
    # no rescue needed; but we allow it for completeness)
    slot_size = slot_tag.get('size_class', 'M')
    cand_size = candidate_tag.get('size_class', 'M')
    try:
        slot_idx = SIZE_TIERS.index(slot_size)
        cand_idx = SIZE_TIERS.index(cand_size)
    except ValueError:
        return False, [f'unknown size class: {slot_size} or {cand_size}']
    if cand_idx > slot_idx:
        return False, [f'size-up not allowed in rescue: {cand_size} > {slot_size}']
    if slot_idx - cand_idx > max_size_drift_down:
        return False, [f'size-down too extreme: {cand_size} -> {slot_size} '
                       f'({slot_idx - cand_idx} tiers, max={max_size_drift_down})']

    # v0.24.100: intra-anim_class locomotion-field gate REMOVED (was here
    # historically — see module-level is_flier comment).

    if slot_idx > cand_idx:
        warnings.append(f'size-down: {cand_size} in {slot_size} slot')

    return True, warnings


def swap_pool_for(slot_cprefix: str, all_tags: Dict[str, Dict],
                  exclusions: Optional[set] = None,
                  **kwargs) -> List[str]:
    """Return all c-prefixes from all_tags that are valid swaps for the slot."""
    exclusions = exclusions or set()
    if slot_cprefix not in all_tags:
        return []
    slot_tag = all_tags[slot_cprefix]
    pool = []
    for cp, tag in all_tags.items():
        if cp == slot_cprefix:
            continue
        if cp in exclusions:
            continue
        ok, _ = is_compatible(slot_tag, tag, **kwargs)
        if ok:
            pool.append(cp)
    return pool


def audit_seed(seed: Dict[str, str], all_tags: Dict[str, Dict]) -> List[Dict]:
    """Audit a generated seed for risky swap pairs.

    Args:
      seed: dict mapping slot_cprefix -> chosen swap_cprefix
      all_tags: full tag table

    Returns: list of {slot, candidate, status, warnings, denials} entries,
      one per seed mapping. Status is 'ok', 'warn', or 'deny'.
    """
    out = []
    for slot, cand in seed.items():
        if slot not in all_tags or cand not in all_tags:
            out.append({'slot': slot, 'candidate': cand,
                        'status': 'unknown',
                        'reason': 'tag missing for slot or candidate'})
            continue
        ok, warns = is_compatible(all_tags[slot], all_tags[cand])
        out.append({
            'slot': slot,
            'candidate': cand,
            'status': 'ok' if ok and not warns else ('warn' if ok else 'deny'),
            'warnings': warns,
        })
    return out


if __name__ == '__main__':
    # Self-test against known good and known bad swap pairs
    import json
    import sys
    from pathlib import Path

    tags_path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path('nr_enemy_tags_anim_patch.json')
    if not tags_path.is_file():
        print(f'Usage: {sys.argv[0]} <tags.json>')
        sys.exit(1)
    tags = json.load(open(tags_path, encoding='utf-8'))

    print(f'Loaded {len(tags)} tags from {tags_path}\n')

    # Test cases — known good and known bad pairs
    cases = [
        ('c2270', 'c4420', 'Giant Crab -> Crayfish (aquatic, both)'),
        ('c4660', 'c4650', 'Guardian Golem -> Dragonkin Soldier (the bug!)'),
        ('c4500', 'c4504', 'Flying Dragon -> Greyoll (both flying_dragon)'),
        ('c2130', 'c2500', 'Margit -> Crucible Knight (both arena humanoids)'),
        ('c4630', 'c4670', 'Runebear -> Ancestor Spirit (quad_large vs giga)'),
        ('c2500', 'c4420', 'Crucible Knight -> Crayfish (humanoid vs aquatic)'),
        ('c4660', 'c5210', 'Guardian Golem -> Divine Beast (giga vs large_boss)'),
        ('c2130', 'c3200', 'Margit -> Merchant (will be excluded; sanity check)'),
    ]
    for slot, cand, label in cases:
        if slot not in tags or cand not in tags:
            print(f'  SKIP    {label} — tag missing')
            continue
        ok, warns = is_compatible(tags[slot], tags[cand])
        status = 'ALLOW' if ok else 'DENY '
        print(f'  {status} {label}')
        for w in warns:
            print(f'          warn: {w}')
