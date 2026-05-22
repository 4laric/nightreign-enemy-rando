#!/usr/bin/env python3
"""
validate_placements.py — offline placement gate audit.

v0.24.86 (initial). Reads one or more spoiler JSONs, runs every stability
gate in the engine against each (chr, slot) placement, and emits a manifest
classifying each placement as:

  CLEAN          — no gate would reject. Standard placement.
  RELEASED       — at least one gate would normally reject, but a release
                   mechanism (EXTRA_ALLOWS / position_shift T0 escape /
                   playtest_verified reposition / chaos_mode / empty-pool
                   fallback) let it through. Worth auditing periodically
                   in case the release is now wrong.
  WOULD_REJECT   — at least one gate would reject this placement and no
                   release applies. This means either (a) the picker has a
                   bug (gate didn't fire when it should have at swap time),
                   (b) the validator has a bug (false positive), or (c) the
                   picker has logic the validator doesn't model. Triage
                   manually — every entry here is signal.
  SUSPICIOUS     — not a hard reject, but matches a watch-list pattern:
                   placement in a slot with prior CTD history, placement
                   using a chr classified into a sensitive class very
                   recently (low empirical support), etc.

Why this exists: see CHANGELOG v0.24.86 + the systematic-stability
thread. Per-CTD whack-a-mole was bottlenecked on in-game discovery
("play seed → CTD → patch"). This converts CTD investigation from
playtime-bound to seed-generation-bound: scan an arbitrary number of
seed spoilers offline, find the placements that ALL gates pass but
that share a slot/chr-class signature with past CTDs, and direct
playtest effort accordingly.

Design constraints:
  - The validator IMPORTS oops_v3 and calls load_data(). It then reaches
    into the module globals for every gate constant. This guarantees the
    validator's gate model can never silently drift from the picker's.
  - The master gate runner is oops_v3._reject_target_for_slot, which
    already consolidates 10+ mirror-semantic gates and returns a
    structured reason string. Picker-only gates (arena_only, NB_only,
    fragile-slot RESILIENT∪SAFE filter, EXTRA_BANS, etc.) are added on
    top here, each as its own predicate.

Usage:
    python dev/validate_placements.py <spoiler.json> [<spoiler.json> ...]
    python dev/validate_placements.py spoilers/*.json \
        --manifest manifest.json \
        --report report.md \
        --chaos-mode False
    python dev/validate_placements.py spoilers/*.json --filter WOULD_REJECT
    python dev/validate_placements.py spoilers/*.json --filter SUSPICIOUS

Output:
  - Manifest is line-deterministic, sorted by (status, map, part_index,
    seed). Diff two manifests to find regression signal across versions:
      diff <(... --manifest -) <(... --manifest -)
  - Report is human-readable Markdown with WOULD_REJECT first, then
    SUSPICIOUS, then a summary table of RELEASED counts by gate.

Exit code is 0 if no WOULD_REJECT placements; 1 otherwise. Useful for
CI: simulate_seeds → validate_placements → fail the run if anything
slipped through.
"""

import argparse
import collections
import dataclasses
import glob
import json
import os
import sys
from typing import Optional


# ============================================================================
# Engine import & shared state
# ============================================================================
# v0.24.86: importing oops_v3 triggers load_data() at module init (it's
# called inside the if __name__ guard and from various entry points).
# To stay parity-locked with the picker, we call load_data() explicitly
# here and then reach into module globals for every gate constant.

_engine = None  # populated by _ensure_engine_loaded()


def _ensure_engine_loaded(engine_dir=None):
    """Lazy-load the engine. Calling load_data() costs a few seconds
    because it parses NpcParam.csv + all the JSONs; doing it once at
    validator init is fine. Subsequent calls are no-ops.

    engine_dir: explicit path to the directory containing oops_v3.py.
    If None, defaults to the parent of this script's dir (we're in
    dev/, engine is at the parent). Matches simulate_seeds.py's
    convention of accepting --engine-dir for the same reason."""
    global _engine
    if _engine is not None:
        return _engine
    if engine_dir is None:
        here = os.path.dirname(os.path.abspath(__file__))
        engine_dir = os.path.dirname(here)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    import oops_v3  # noqa: E402
    oops_v3.load_data()
    _engine = oops_v3
    return _engine


# ============================================================================
# Verdict / GateResult dataclasses
# ============================================================================
# Each gate produces a GateResult. The placement's overall Verdict is the
# rollup of all gates' results plus any applicable releases.

@dataclasses.dataclass(frozen=True)
class GateResult:
    """One gate's verdict on one placement.

    name:        gate identifier (matches the picker's reason strings
                 where possible — 'no_emerge_terrain', 'nb_strict',
                 'quadruped_unsafe_slot', etc.)
    rejected:    True if this gate would block the placement
    released_by: if rejected=True but a release applies, the name of
                 the release mechanism. Else None.
    evidence:    structured per-gate facts useful for triage. Kept JSON-
                 safe (no tuples, sets — those serialize as lists).
    """
    name: str
    rejected: bool
    released_by: Optional[str]
    evidence: dict


@dataclasses.dataclass
class Verdict:
    """Rollup verdict for one placement.

    status is the four-way classification:
      CLEAN / RELEASED / WOULD_REJECT / SUSPICIOUS

    gates is the full list of GateResults that fired. Even non-rejected
    results are recorded (rejected=False) when a gate evaluated as
    relevant — e.g., is_fragile_slot=False is silent, but fragile=True
    + chr is RESILIENT records both the fragile finding AND the release.
    """
    status: str   # 'CLEAN' | 'RELEASED' | 'WOULD_REJECT' | 'SUSPICIOUS'
    gates: list   # list[GateResult]
    suspicious_tags: list   # list[str] — reasons for SUSPICIOUS status

    def is_actionable(self):
        return self.status in ('WOULD_REJECT', 'SUSPICIOUS')


# ============================================================================
# Placement extraction from spoiler entry
# ============================================================================

@dataclasses.dataclass(frozen=True)
class Placement:
    """One (chr, slot) assignment from a spoiler entry. Hashable so it
    can be deduplicated across seeds when computing cross-seed stats.

    spoiler_flags carries per-run state from the spoiler header that
    affects gate evaluation. Currently:
      disable_resilient_filter: bool. When True, the picker is in
        diagnostic mode where the fragile-slot RESILIENT∪SAFE filter
        is intentionally bypassed (so untested c-prefixes get to
        land at fragile slots, generating CTD attribution signal).
        The validator skips the fragile_slot_filter gate when this
        is True, because rejecting placements that the run was
        specifically designed to produce is noise."""
    seed: int
    engine_fingerprint: str
    msb: str
    pi: int
    pos: tuple        # (x, y, z) — frozen as tuple for hashability
    src_cp: str
    src_name: str     # variant_name (used by source-qualifier gates)
    src_npc_param: int
    target_cp: str
    target_name: str
    target_npc_param: int
    entity_id: int
    is_boss: bool
    catalog_tier: Optional[str]
    catalog_scope: Optional[str]
    spoiler_flags: tuple  # frozenset-like immutable: (('disable_resilient_filter', False), ...)


def _placement_from_entry(seed, fingerprint, entry, spoiler_flags):
    pos = entry.get('position') or [0.0, 0.0, 0.0]
    return Placement(
        seed=seed,
        engine_fingerprint=fingerprint,
        msb=entry['map'],
        pi=int(entry['part_index']),
        pos=tuple(float(c) for c in pos),
        src_cp=entry['original']['c_prefix'],
        src_name=entry['original'].get('name', '') or '',
        src_npc_param=int(entry['original'].get('npc_param_id', 0) or 0),
        target_cp=entry['new']['c_prefix'],
        target_name=entry['new'].get('name', '') or '',
        target_npc_param=int(entry['new'].get('npc_param_id', 0) or 0),
        entity_id=int(entry.get('entity_id', 0) or 0),
        is_boss=bool(entry.get('is_boss', False)),
        catalog_tier=entry.get('catalog_tier'),
        catalog_scope=entry.get('catalog_scope'),
        spoiler_flags=spoiler_flags,
    )


# ============================================================================
# Gate runners
# ============================================================================
# Each gate function takes (p: Placement, ctx) and returns a GateResult.
# A return of None means the gate is not applicable (slot/chr doesn't
# match the gate's preconditions — common case, kept None to reduce noise
# in the per-placement gate list).
#
# Convention: gate name strings match the picker's reason strings where
# possible. This is how the validator and picker stay legible together —
# `grep no_emerge_terrain` finds the gate in both files.

def gate_mirror_semantic(p, ctx):
    """The big one: runs oops_v3._reject_target_for_slot, which itself
    runs ~10 consolidated gates: nb_strict, nb_caliber, forbidden_source_
    anim, quadruped_unsafe_slot, flying_required_slot, grunt_trash_at_
    boss_bar, xxl_giga_size_drift, script_spawn_boss_at_overworld, xxl_
    at_small_slot, no_emerge_terrain.

    By delegating, the validator stays parity-locked: any new gate added
    inside _reject_target_for_slot is immediately picked up by the
    validator without code change here.

    chaos_mode default False is conservative. Most runs don't use chaos,
    and chaos only loosens — so a False-default may flag SOME placements
    that a chaos-True run would have legitimately produced. That's an
    acceptable false-positive bias for an audit tool. Override with the
    --chaos-mode CLI flag if needed.
    """
    reason = ctx.engine._reject_target_for_slot(
        target_cp=p.target_cp,
        src_cp=p.src_cp,
        src_variant_name=p.src_name,
        tags=ctx.tags,
        chaos_mode=ctx.chaos_mode,
        msb_base=p.msb,
        pi=p.pi,
    )
    if reason is None:
        return None
    # Caliber rejection has empty-pool-fallback semantics in the picker:
    # if every candidate gets caliber-rejected, the picker keeps the
    # pre-caliber pool. We can't replicate that here (we don't have the
    # full candidate pool), so we mark caliber rejections as "released
    # by empty-pool fallback (assumed)" and downgrade them to RELEASED.
    # NB-strict + source-anim are absolute (no fallback).
    if reason == 'nb_caliber':
        return GateResult(
            name=reason,
            rejected=True,
            released_by='empty_pool_fallback_assumed',
            evidence={
                'predicate': '_reject_target_for_slot',
                'reason_returned': reason,
                'note': ('caliber gate has empty-pool fallback in picker. '
                         'Validator cannot recompute the pool intersection, '
                         'so this is marked RELEASED. False-positive rate '
                         'here is acceptable — caliber leaks are rare and '
                         'usually visible elsewhere.'),
            },
        )
    return GateResult(
        name=reason,
        rejected=True,
        released_by=None,
        evidence={'predicate': '_reject_target_for_slot',
                  'reason_returned': reason},
    )


def gate_arena_only(p, ctx):
    """V3_ARENA_ONLY_TARGETS: chr can only land at slots whose variant
    name carries a V3_BOSS_NAME_MARKER. picker subtracts twice (once
    via recipient_is_boss, once via slot variant). Validator checks the
    slot-variant form, which is strictly tighter.

    chaos-overrideable: in chaos mode, the second gate (slot-variant)
    is lifted. The first (recipient_is_boss) is not. For an audit
    default of chaos=False, both fire.
    """
    if p.target_cp not in ctx.engine.V3_ARENA_ONLY_TARGETS:
        return None
    slot_is_arena = bool(p.src_name) and any(
        m in p.src_name for m in ctx.engine.V3_BOSS_NAME_MARKERS)
    if slot_is_arena:
        return None  # passes
    # Chaos lifts only the slot-variant gate; the recipient_is_boss
    # gate above always applies. We approximate by treating chaos as
    # a release ONLY when chaos_mode is True at audit time.
    if ctx.chaos_mode:
        return GateResult(
            name='arena_only',
            rejected=True,
            released_by='chaos_mode',
            evidence={'set': 'V3_ARENA_ONLY_TARGETS',
                      'slot_variant': p.src_name},
        )
    return GateResult(
        name='arena_only',
        rejected=True,
        released_by=None,
        evidence={'set': 'V3_ARENA_ONLY_TARGETS',
                  'slot_variant': p.src_name},
    )


def gate_night_boss_only(p, ctx):
    """V3_NIGHT_BOSS_ONLY_TARGETS: tighter than arena_only. Slot must
    carry a V3_NIGHT_BOSS_NAME_MARKER. Chaos-overrideable."""
    if p.target_cp not in ctx.engine.V3_NIGHT_BOSS_ONLY_TARGETS:
        return None
    slot_is_nb = bool(p.src_name) and any(
        m in p.src_name for m in ctx.engine.V3_NIGHT_BOSS_NAME_MARKERS)
    if slot_is_nb:
        return None
    if ctx.chaos_mode:
        return GateResult(
            name='night_boss_only',
            rejected=True,
            released_by='chaos_mode',
            evidence={'set': 'V3_NIGHT_BOSS_ONLY_TARGETS',
                      'slot_variant': p.src_name},
        )
    return GateResult(
        name='night_boss_only',
        rejected=True,
        released_by=None,
        evidence={'set': 'V3_NIGHT_BOSS_ONLY_TARGETS',
                  'slot_variant': p.src_name},
    )


def gate_night_or_field_boss_only(p, ctx):
    """V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS: tightest. Not chaos-overrideable
    (per the picker code at line ~9861 — the chaos check is absent here)."""
    if p.target_cp not in ctx.engine.V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS:
        return None
    slot_is_match = bool(p.src_name) and any(
        m in p.src_name for m in ctx.engine.V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS)
    if slot_is_match:
        return None
    return GateResult(
        name='night_or_field_boss_only',
        rejected=True,
        released_by=None,
        evidence={'set': 'V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS',
                  'slot_variant': p.src_name},
    )


def gate_nb_exclude_at_nb_slot(p, ctx):
    """V3_NIGHT_BOSS_EXCLUDE_TARGETS: chrs that specifically break at
    NB anchor slots (scripted-intro fails, chr idles). Subtracted only
    at NB-marker slots — they're fine at field slots."""
    if p.target_cp not in ctx.engine.V3_NIGHT_BOSS_EXCLUDE_TARGETS:
        return None
    slot_is_nb = bool(p.src_name) and any(
        m in p.src_name for m in ctx.engine.V3_NIGHT_BOSS_NAME_MARKERS)
    if not slot_is_nb:
        return None
    return GateResult(
        name='nb_exclude_at_nb_slot',
        rejected=True,
        released_by=None,
        evidence={'set': 'V3_NIGHT_BOSS_EXCLUDE_TARGETS',
                  'slot_variant': p.src_name},
    )


def gate_sensitive_only_slot(p, ctx):
    """V3_SENSITIVE_ONLY_SLOTS: softer-than-fragile. Excludes
    V3_FRAGILE_SENSITIVE_TARGETS without restricting to RESILIENT."""
    if (p.msb, p.pi) not in ctx.engine.V3_SENSITIVE_ONLY_SLOTS:
        return None
    if p.target_cp not in ctx.engine.V3_FRAGILE_SENSITIVE_TARGETS:
        return None
    return GateResult(
        name='sensitive_only_slot',
        rejected=True,
        released_by=None,
        evidence={'slot_in': 'V3_SENSITIVE_ONLY_SLOTS',
                  'target_in': 'V3_FRAGILE_SENSITIVE_TARGETS'},
    )


def gate_fragile_slot(p, ctx):
    """The fragile-slot RESILIENT∪SAFE_CONFIRMED filter. Release paths:
      - V3_POSITION_SHIFTS (T0 escape): is_fragile_slot returns False
      - V3_PROBLEM_SLOT_EXTRA_ALLOWS: per-slot whitelist additions
      - disable_resilient_filter spoiler flag: diagnostic mode
        bypasses the entire filter intentionally

    v0.26.x: the V3_OFF_MESH_PREFERRED_TARGETS preferred-floater release
    path was removed alongside the constant's retirement in v0.24.86-
    patch7 (the constant lived empty for 64 minor versions before being
    formally deleted; SAFE_CONFIRMED filter alone was sufficient). The
    paired `_load_off_mesh_slots()` reader call is also dropped — its
    only consumer was this branch.

    Also pairs with V3_PROBLEM_SLOT_EXTRA_BANS to ADD rejections on
    top of the RESILIENT∪SAFE filter. Modelled here as two separate
    gate results: fragile_slot_filter (the SAFE filter) and
    fragile_slot_extra_ban (the EXTRA_BANS additional rejection).
    """
    if not ctx.engine.is_fragile_slot(p.msb, p.pi, p.src_name,
                                       slot_pos=list(p.pos)):
        return None
    # Diagnostic-mode runs intentionally bypass the SAFE filter to
    # exercise untested c-prefixes at fragile slots. Don't flag those.
    flags = dict(p.spoiler_flags)
    if flags.get('disable_resilient_filter'):
        return None
    # Compute the allowed-set the picker would use at this slot.
    allowed = (ctx.engine.V3_RESILIENT_BIPEDS
               | ctx.engine.V3_FRAGILE_SAFE_CONFIRMED)
    extra_allows = ctx.engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
        (p.msb, p.pi)) or set()
    allowed_with_extra = allowed | extra_allows
    if p.target_cp in allowed:
        # In the base SAFE pool — gate passes without needing extras.
        return None  # silent pass
    if p.target_cp in extra_allows:
        return GateResult(
            name='fragile_slot_filter',
            rejected=True,
            released_by='problem_slot_extra_allows',
            evidence={'slot': f'{p.msb}:{p.pi}',
                      'allowed_via_extra_allows': p.target_cp in extra_allows,
                      'extra_allows_set_size': len(extra_allows)},
        )
    # Genuinely rejected.
    return GateResult(
        name='fragile_slot_filter',
        rejected=True,
        released_by=None,
        evidence={'slot': f'{p.msb}:{p.pi}',
                  'allowed_set_size': len(allowed_with_extra),
                  'target_in_RESILIENT': (
                      p.target_cp in ctx.engine.V3_RESILIENT_BIPEDS),
                  'target_in_SAFE_CONFIRMED': (
                      p.target_cp in ctx.engine.V3_FRAGILE_SAFE_CONFIRMED),
                  'target_in_EXTRA_ALLOWS': p.target_cp in extra_allows},
    )


def gate_problem_slot_extra_bans(p, ctx):
    """V3_PROBLEM_SLOT_EXTRA_BANS: per-slot additional bans applied
    on top of the fragile filter. Only fires if slot is fragile."""
    bans = ctx.engine.V3_PROBLEM_SLOT_EXTRA_BANS.get((p.msb, p.pi))
    if not bans:
        return None
    if p.target_cp not in bans:
        return None
    return GateResult(
        name='problem_slot_extra_ban',
        rejected=True,
        released_by=None,
        evidence={'slot': f'{p.msb}:{p.pi}',
                  'banned_set_size': len(bans)},
    )


# Off-mesh non-fragile SENSITIVE exclusion (picker line ~9978).
def gate_off_mesh_sensitive(p, ctx):
    """At off-mesh slots that are NOT otherwise fragile, exclude
    SENSITIVE c-prefixes. Soft restriction; floater-preference branch
    handles the preferred case."""
    if ctx.engine.is_fragile_slot(p.msb, p.pi, p.src_name,
                                   slot_pos=list(p.pos)):
        return None  # fragile-slot gate covers this case
    off_mesh = ctx.engine._load_off_mesh_slots()
    if (p.msb, p.pi) not in off_mesh:
        return None
    if p.target_cp not in ctx.engine.V3_FRAGILE_SENSITIVE_TARGETS:
        return None
    return GateResult(
        name='off_mesh_sensitive',
        rejected=True,
        released_by=None,
        evidence={'slot': f'{p.msb}:{p.pi}',
                  'target_in_SENSITIVE': True},
    )


# Pool-level excludes (cheap to check; should never appear in spoilers
# but the validator surfaces them if they do, which would indicate a
# picker bug).
def gate_excluded_prefix(p, ctx):
    """V3_EXCLUDE_PREFIXES / V3_EXCLUDE_TARGET_PREFIXES /
    V3_GHOST_EXCLUDE_TARGET_PREFIXES: pool-level c-prefix exclusion.
    A spoiler entry containing one of these means the picker leaked
    past its own gate — strong picker-bug signal."""
    if p.target_cp in ctx.engine.V3_EXCLUDE_PREFIXES:
        return GateResult(
            name='excluded_prefix',
            rejected=True,
            released_by=None,
            evidence={'set': 'V3_EXCLUDE_PREFIXES'},
        )
    if p.target_cp in ctx.engine.V3_EXCLUDE_TARGET_PREFIXES:
        return GateResult(
            name='excluded_prefix',
            rejected=True,
            released_by=None,
            evidence={'set': 'V3_EXCLUDE_TARGET_PREFIXES'},
        )
    if p.target_cp in ctx.engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES:
        return GateResult(
            name='excluded_prefix',
            rejected=True,
            released_by=None,
            evidence={'set': 'V3_GHOST_EXCLUDE_TARGET_PREFIXES'},
        )
    return None


def gate_map_prefix_target_exclude(p, ctx):
    """V3_MAP_PREFIX_TARGET_EXCLUDES: per-MSB-prefix exclusion sets."""
    for mp_prefix, excl in ctx.engine.V3_MAP_PREFIX_TARGET_EXCLUDES.items():
        if p.msb.startswith(mp_prefix) and p.target_cp in excl:
            return GateResult(
                name='map_prefix_target_exclude',
                rejected=True,
                released_by=None,
                evidence={'msb_prefix': mp_prefix},
            )
    return None


# Tier-preserve check. The picker enforces this softly (if tier filter
# empties the pool, it falls back to the unfiltered pool). Validator
# surfaces it as a soft signal: a "tier_drift" rejection that's almost
# always released_by=empty_pool_fallback_assumed.
def gate_tier_preserve(p, ctx):
    src_tier = ctx.tags.get(p.src_cp, {}).get('tier')
    tgt_tier = ctx.tags.get(p.target_cp, {}).get('tier')
    if src_tier in ctx.engine.V3_BOSS_STRENGTH_TIERS:
        if tgt_tier not in ctx.engine.V3_BOSS_STRENGTH_TIERS:
            return GateResult(
                name='tier_drift',
                rejected=True,
                released_by='empty_pool_fallback_assumed',
                evidence={'src_tier': src_tier, 'tgt_tier': tgt_tier,
                          'note': ('tier filter is soft (falls back to '
                                   'unfiltered pool if empty). Drift here '
                                   'usually means the boss-tier pool was '
                                   'empty for this slot after other gates.')},
            )
    elif src_tier in ctx.engine.V3_FIELD_STRENGTH_TIERS:
        if tgt_tier not in ctx.engine.V3_FIELD_STRENGTH_TIERS:
            return GateResult(
                name='tier_drift',
                rejected=True,
                released_by='empty_pool_fallback_assumed',
                evidence={'src_tier': src_tier, 'tgt_tier': tgt_tier},
            )
    return None


# Full gate list — order matters only for evidence ordering (no early-
# exit; we run them all to capture every applicable signal).
ALL_GATES = [
    gate_excluded_prefix,
    gate_map_prefix_target_exclude,
    gate_tier_preserve,
    gate_arena_only,
    gate_night_boss_only,
    gate_night_or_field_boss_only,
    gate_nb_exclude_at_nb_slot,
    gate_mirror_semantic,        # the big one — 10+ gates inside
    gate_sensitive_only_slot,
    gate_off_mesh_sensitive,
    gate_fragile_slot,
    gate_problem_slot_extra_bans,
]


# ============================================================================
# SUSPICIOUS heuristics
# ============================================================================
# Not hard rejects — flags worth surfacing for triage. Each returns a
# string tag (or None) describing why the placement is suspicious.

def suspicion_named_location_with_ctd_history(p, ctx):
    """Slot is in a named location (tunnel, encampment, etc.) that has
    a recorded ctd_history. Doesn't mean this specific placement will
    crash — just that the named location has past CTD reports and is
    a known fragility hotspot worth playtesting.

    Data source: nr_named_locations.json (v0.24.85+, loaded directly
    here since the engine doesn't wire it into V3_* constants yet)."""
    loc = ctx.named_locations.get(p.msb)
    if not loc:
        return None
    if not loc.get('ctd_history'):
        return None
    return (f'named_location_with_ctd_history:{loc["slug"]} '
            f'(n_ctds={len(loc["ctd_history"])})')


def suspicion_starting_encampment(p, ctx):
    """Slot is in a starting encampment (player exposure is high — chrs
    here are seen on every expedition). Higher-priority playtest target
    if anything goes wrong."""
    enc = ctx.starting_encampments.get(p.msb)
    if not enc:
        return None
    return f'starting_encampment:{enc.get("label", p.msb)}'


def suspicion_recently_classified_no_emerge(p, ctx):
    """Target chr was added to V3_ENTRANCE_ANIM_CLASS='emerge_from_ground'
    very recently (e.g., v0.24.82-84 behbnd-template expansion). Lower
    empirical confidence than older classifications. If this chr is
    placed at an emerge-friendly slot that's NEAR but not IN the no-
    emerge set, worth manually verifying."""
    anim = ctx.engine.V3_ENTRANCE_ANIM_CLASS.get(p.target_cp)
    if anim != 'emerge_from_ground':
        return None
    meta = ctx.engine.V3_ENTRANCE_ANIM_META.get(p.target_cp, {})
    src_note = meta.get('_source_note', '')
    if 'v0.24.82' in src_note or 'v0.24.83' in src_note or 'v0.24.84' in src_note:
        return f'recently_classified_emerge:{p.target_cp}'
    return None


def suspicion_problem_slot_loosened(p, ctx):
    """Placement is at a slot in V3_PROBLEM_SLOTS that's been loosened
    via EXTRA_ALLOWS. The release worked the last time playtested but
    each new chr that flows in via EXTRA_ALLOWS is effectively
    untested — flag for manual confirmation if the chr is one that
    hasn't appeared at this slot before in this audit."""
    if (p.msb, p.pi) not in ctx.engine.V3_PROBLEM_SLOTS:
        return None
    extra_allows = ctx.engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
        (p.msb, p.pi)) or set()
    if p.target_cp in extra_allows:
        return (f'problem_slot_loosened:{p.msb}:{p.pi} '
                f'(target {p.target_cp} via EXTRA_ALLOWS)')
    return None


def suspicion_position_shifted_fragile(p, ctx):
    """Slot has a position_shift entry, which means it WOULD be fragile
    but the T0 escape lifts the fragile classification. If the chr
    placed here has emerge_from_ground anim, the position shift may
    or may not address the underlying emerge-anim issue depending on
    the shift target. Worth flagging."""
    shift = ctx.engine.lookup_position_shift(p.msb, p.pi)
    if not shift:
        return None
    anim = ctx.engine.V3_ENTRANCE_ANIM_CLASS.get(p.target_cp)
    if anim == 'emerge_from_ground':
        return (f'position_shifted_with_emerge_chr:{p.msb}:{p.pi} '
                f'(target {p.target_cp} anim={anim})')
    return None


def suspicion_non_anchored_boss_slot(p, ctx):
    """v0.24.86: surfaces the slot-side axis from Track C
    (`scripted_intro_slots.json` → enriched into `nr_boss_slots.json`
    schema v2 with per-slot `intro_anchored: bool`).

    Triggers when:
      - slot is in V3_BOSS_SLOT_CATALOG (catalog-tagged boss-tier) AND
      - the slot's `intro_anchored` is explicitly False (catalog tagged
        the geometry as boss-shaped, but the host map's EMEVD doesn't
        wire that chr entity_id through any NB-anchor scripted intro
        template) AND
      - the slot has a non-zero eid (we don't flag placeholder slots) AND
      - the target chr is in V3_NIGHT_BOSS_STRICT_TARGETS OR
        V3_NIGHT_BOSS_CALIBER_TARGETS — i.e., this chr was designed for
        scripted-intro encounters and is likely to stall in pre-aggro
        pose when the expected intro doesn't fire.

    NB_STRICT_TARGETS / NB_CALIBER_TARGETS are the PROXY chr-side
    classifier. The proper chr-side classifier from Track B
    (`data/scripted_intro_chrs.json`) is more precise but much smaller
    — see `suspicion_scripted_intro_confirmed` below for the high-
    precision check. This proxy stays around as the lower-precision /
    higher-recall complement until the JSON list grows.
    """
    entry = ctx.engine.V3_BOSS_SLOT_CATALOG.get((p.msb, p.pi))
    if not entry:
        return None
    if entry.get('intro_anchored') is not False:
        return None  # True or unset → not a known non-anchored slot
    if entry.get('eid', 0) == 0:
        return None  # zero-eid placeholder, no live placement to flag
    in_strict = p.target_cp in ctx.engine.V3_NIGHT_BOSS_STRICT_TARGETS
    in_caliber = p.target_cp in ctx.engine.V3_NIGHT_BOSS_CALIBER_TARGETS
    if not (in_strict or in_caliber):
        return None
    # If the chr is ALSO in the high-precision JSON, the other
    # suspicion will fire too — don't double-flag here. The high-
    # precision tag is the more actionable one.
    if ctx.scripted_intro_class.get(p.target_cp) == 'scripted_intro_required':
        return None
    tier = entry.get('tier', '?')
    proxy = 'strict' if in_strict else 'caliber'
    return (f'non_anchored_boss_slot_intro_dependent:{p.msb}:{p.pi} '
            f'(catalog_tier={tier}, target {p.target_cp} in NB_{proxy}; '
            f'proxy only — not in scripted_intro_chrs.json yet)')


def suspicion_scripted_intro_confirmed(p, ctx):
    """v0.24.86 Track B: high-precision scripted-intro mismatch.

    The Track B chr classifier (`data/scripted_intro_chrs.json`)
    enumerates exactly 4 chrs at v0.24.85: c3100 / c4355
    (`scripted_intro_required` — freeze in pre-aggro pose when the
    slot doesn't fire an NB-anchor scripted intro) and c4490 / c5750
    (`scripted_intro_intolerant` — NPC-style chrs that freeze in
    arms-crossed idle WHEN the slot fires an unwanted scripted intro).

    The axis is two-directional and maps onto the same slot-side
    `intro_anchored` bit with opposite verdicts:
      - required + intro_anchored=False  → REJECT (chr needs intro,
                                                    slot won't fire)
      - intolerant + intro_anchored=True → REJECT (chr breaks at
                                                    intro slot)

    Methodology note (see scripted_intro_chrs.json _meta): the
    behbnd-template hash methodology that successfully expanded
    entrance_animations.json from 4 seeds to 25 chrs DID NOT
    REPLICATE for this failure mode. The behavior tree is intrinsic
    state-machine logic; scripted-intro dependence lives one layer
    further out in NpcParam/NpcThinkParam/EMEVD wiring. This
    classifier therefore stays small and grows empirically; the
    validator's job is just to make sure the few known entries
    are caught reliably.

    For chrs in NB_CALIBER but NOT in the JSON,
    `suspicion_non_anchored_boss_slot` above fires as the lower-
    precision fallback.
    """
    cls = ctx.scripted_intro_class.get(p.target_cp)
    if cls not in ('scripted_intro_required', 'scripted_intro_intolerant'):
        return None
    entry = ctx.engine.V3_BOSS_SLOT_CATALOG.get((p.msb, p.pi))
    if not entry:
        # Chr is classified but slot isn't in catalog — we can't
        # determine intro_anchored. Be conservative and skip; if the
        # chr fails at non-catalog slots we'd need a different
        # slot-side signal anyway.
        return None
    intro_anchored = entry.get('intro_anchored')
    if intro_anchored is None:
        return None  # catalog pre-Track-C schema; no signal
    if cls == 'scripted_intro_required' and intro_anchored is False:
        return (f'scripted_intro_required_at_non_anchored:{p.msb}:{p.pi} '
                f'(chr {p.target_cp} classified as scripted_intro_required '
                f'in scripted_intro_chrs.json; slot intro_anchored=False — '
                f'high-confidence frozen-pose risk)')
    if cls == 'scripted_intro_intolerant' and intro_anchored is True:
        return (f'scripted_intro_intolerant_at_anchored:{p.msb}:{p.pi} '
                f'(chr {p.target_cp} classified as scripted_intro_intolerant '
                f'in scripted_intro_chrs.json; slot fires NB intro — '
                f'high-confidence NPC-style idle risk)')
    return None


def suspicion_wakeup_dormant_placement(p, ctx):
    """v0.24.86 Track B side-discovery — RETIRED v0.24.86-late by audit.

    Initially designed to flag any placement of a wakeup_dormant chr
    (c4470, c4603, c4660, c5110, c5790) as a soft watch-list signal,
    on the theory that some slots' wake handshakes route through
    events outside the `permissive_boss_wake` allowlist and would
    leave the chr dormant.

    The empirical audit recorded in `wakeup_chrs.json` _meta.
    empirical_audit_v0_24_86 closed that theory. Full scan of all 300
    vanilla NR MSBs + 194 per-map EMEVD files identified 103 vanilla
    wakeup-chr placements: 6 route through allowlisted wake events
    (covered by v0.24.86), 97 use no scripted wake handshake at all
    (covered by AI proximity-aggro via `permissive_spawn_emerge` on
    the 90085XXX/90035XXX spawn handlers, or by explicit
    EnableCharacterAI in 90075351/352 multi-entity orchestrators), 0
    cinematic-only. The 11 "at-risk" entities found in the interim
    investigation (`wake_handshake_at_risk_entities_INTERIM.json`)
    resolved as c0100 player-spawn group IDs routed through 90015301,
    which is a player-aggression watcher rather than a chr wake.

    The classifier wakeup_chrs.json stays loaded for documentation
    and for surfacing in the CTD report helper (section 5), but the
    SUSPICION returns None unconditionally. If a future CTD report
    surfaces a frozen wakeup chr (i.e., a vanilla case the audit
    missed), restore this predicate's body and add an entry to
    nr_no_wake_slots.json with the empirical evidence."""
    return None


ALL_SUSPICIONS = [
    suspicion_named_location_with_ctd_history,
    suspicion_starting_encampment,
    suspicion_recently_classified_no_emerge,
    suspicion_problem_slot_loosened,
    suspicion_position_shifted_fragile,
    suspicion_non_anchored_boss_slot,
    suspicion_scripted_intro_confirmed,
    suspicion_wakeup_dormant_placement,
]


# ============================================================================
# Validation context — shared loaded state across all gate evaluations
# ============================================================================

@dataclasses.dataclass
class ValidationContext:
    engine: object   # the oops_v3 module
    tags: dict
    chaos_mode: bool
    named_locations: dict        # msb -> location entry
    starting_encampments: dict   # msb -> encampment entry
    # v0.24.86 Track B chr-side classifiers (data only — not yet wired
    # into engine gates). Validator loads them directly and threads
    # through suspicion predicates. When the engine integration lands
    # these would become V3_SCRIPTED_INTRO_CLASS / V3_WAKEUP_CLASS
    # globals and we'd read from there instead.
    scripted_intro_class: dict   # cp -> 'scripted_intro_required' | 'scripted_intro_intolerant' | 'unknown'
    wakeup_class: dict           # cp -> 'wakeup_dormant' | 'unknown'


def build_context(chaos_mode=False):
    eng = _ensure_engine_loaded()
    # Tags are not a module-level attr; load_data() returned them, but
    # by the time we're here the picker has them. Use the same loader
    # path the engine uses internally.
    here = os.path.dirname(os.path.abspath(eng.__file__))
    tags_path = os.path.join(here, 'data', 'nr_enemy_tags.json')
    with open(tags_path, encoding='utf-8') as f:
        tags = json.load(f)
    # Named locations (v0.24.85). May not exist on older repos.
    nl_path = os.path.join(here, 'data', 'nr_named_locations.json')
    named_locations = {}
    if os.path.isfile(nl_path):
        with open(nl_path, encoding='utf-8') as f:
            nl_data = json.load(f)
        named_locations = nl_data.get('locations', {})
    # Starting encampments.
    se_path = os.path.join(here, 'data', 'nr_starting_encampments.json')
    starting_encampments = {}
    if os.path.isfile(se_path):
        with open(se_path, encoding='utf-8') as f:
            se_data = json.load(f)
        starting_encampments = se_data.get('encampments', {})
    # v0.24.86 Track B: scripted-intro chr classifier. Sparse (4 entries
    # at v0.24.85) — see _meta.methodology_findings for why behbnd
    # template hashing failed to expand this list the way it did for
    # emerge_from_ground. Treat absence as 'unknown' (no signal).
    si_path = os.path.join(here, 'data', 'scripted_intro_chrs.json')
    scripted_intro_class = {}
    if os.path.isfile(si_path):
        with open(si_path, encoding='utf-8') as f:
            si_data = json.load(f)
        scripted_intro_class = {
            cp: entry.get('class', 'unknown')
            for cp, entry in si_data.get('scripted_intro_chrs', {}).items()
        }
    # v0.24.86 Track B side-discovery: wakeup-dormant chr classifier.
    # 5 entries at v0.24.86. Methodology limit: bespoke per-chr behbnd
    # templates (size 1-2), no clustering leverage. Slot-side data
    # (nr_no_wake_slots.json) does not exist yet.
    wk_path = os.path.join(here, 'data', 'wakeup_chrs.json')
    wakeup_class = {}
    if os.path.isfile(wk_path):
        with open(wk_path, encoding='utf-8') as f:
            wk_data = json.load(f)
        wakeup_class = {
            cp: entry.get('class', 'unknown')
            for cp, entry in wk_data.get('wakeup_chrs', {}).items()
        }
    return ValidationContext(
        engine=eng,
        tags=tags,
        chaos_mode=chaos_mode,
        named_locations=named_locations,
        starting_encampments=starting_encampments,
        scripted_intro_class=scripted_intro_class,
        wakeup_class=wakeup_class,
    )


# ============================================================================
# Top-level validate(): one Placement → one Verdict
# ============================================================================

def validate_placement(p, ctx):
    # v0.26.x: hub-map short-circuit. The picker doesn't pick targets
    # for V3_HUB_MAPS slots in production — vanilla source is copied
    # through unchanged (m10–m14, m18 — Roundtable, Stranded Graveyard,
    # the lift hub, etc.). Running rejection gates on hub-map placements
    # is therefore simulating a code path that never runs in production;
    # the v0.24.86-patch9 stub-nav gate would otherwise fire false-
    # positives at e.g. m11 (Roundtable) since hub maps ship with stub
    # navmesh and many vanilla NPCs there aren't in NAV_INDEPENDENT_
    # TARGETS. Treat as CLEAN: by construction the placement is what
    # vanilla ships, so it can't be "incorrectly randomized."
    if p.msb in ctx.engine.V3_HUB_MAPS:
        return Verdict(status='CLEAN', gates=[], suspicious_tags=[])

    gate_results = []
    for fn in ALL_GATES:
        r = fn(p, ctx)
        if r is not None:
            gate_results.append(r)
    # Run suspicions on top.
    suspicions = []
    for fn in ALL_SUSPICIONS:
        tag = fn(p, ctx)
        if tag:
            suspicions.append(tag)
    # Rollup.
    unreleased = [r for r in gate_results
                  if r.rejected and r.released_by is None]
    released = [r for r in gate_results
                if r.rejected and r.released_by is not None]
    if unreleased:
        status = 'WOULD_REJECT'
    elif released:
        status = 'RELEASED'
    elif suspicions:
        status = 'SUSPICIOUS'
    else:
        status = 'CLEAN'
    return Verdict(status=status, gates=gate_results,
                   suspicious_tags=suspicions)


# ============================================================================
# Spoiler ingestion
# ============================================================================

def iter_spoiler_placements(spoiler_path):
    """Yield Placement objects for every entry in a spoiler JSON.

    Reads the spoiler header for per-run flags that affect gate
    evaluation (currently just disable_resilient_filter) and threads
    them through each Placement as spoiler_flags. Future header
    fields that should suppress specific gates go here too."""
    with open(spoiler_path, encoding='utf-8') as f:
        spoiler = json.load(f)
    seed = int(spoiler.get('seed', 0) or 0)
    fingerprint = (spoiler.get('engine_fingerprint')
                   or spoiler.get('engine_version')
                   or 'unknown')
    spoiler_flags = (
        ('disable_resilient_filter',
         bool(spoiler.get('disable_resilient_filter'))),
        ('multiplayer_safe',
         bool(spoiler.get('multiplayer_safe'))),
        ('oops_all_nb_target_cp',
         spoiler.get('oops_all_nb_target_cp')),
    )
    for entry in spoiler.get('entries', []):
        # Skip entries that didn't actually swap. The spoiler can in
        # principle contain pass-through entries; current versions
        # don't, but defensively skip if new == original.
        new_block = entry.get('new') or {}
        orig_block = entry.get('original') or {}
        if not new_block.get('c_prefix'):
            continue  # no swap recorded
        if new_block.get('c_prefix') == orig_block.get('c_prefix'):
            continue
        try:
            yield _placement_from_entry(seed, fingerprint, entry, spoiler_flags)
        except (KeyError, TypeError, ValueError) as e:
            sys.stderr.write(
                f'  WARN: skipped malformed entry in {spoiler_path}: '
                f'{e!r} entry={entry}\n')


# ============================================================================
# Manifest + report emission
# ============================================================================

def manifest_row(p, v, ctx):
    """Compact JSON-safe dict for one (placement, verdict) pair.
    Sortable + diffable across runs.

    named_location is attached when the slot's MSB is in
    nr_named_locations.json — gives the report semantic anchors
    instead of bare MSB filenames."""
    nl = ctx.named_locations.get(p.msb)
    named_location = (
        {'slug': nl['slug'], 'category': nl.get('category'),
         'label': nl.get('label')}
        if nl else None
    )
    return {
        'status': v.status,
        'seed': p.seed,
        'msb': p.msb,
        'pi': p.pi,
        'src_cp': p.src_cp,
        'src_name': p.src_name,
        'target_cp': p.target_cp,
        'target_name': p.target_name,
        'pos': list(p.pos),
        'catalog_tier': p.catalog_tier,
        'named_location': named_location,
        'gates_fired': [
            {'name': r.name, 'released_by': r.released_by,
             'evidence': r.evidence}
            for r in v.gates if r.rejected
        ],
        'suspicious_tags': v.suspicious_tags,
        'engine_fingerprint': p.engine_fingerprint,
    }


def write_manifest(rows, path):
    rows_sorted = sorted(rows, key=lambda r: (
        r['status'], r['msb'], r['pi'], r['seed'], r['target_cp']))
    if path == '-':
        json.dump(rows_sorted, sys.stdout, indent=2)
        sys.stdout.write('\n')
    else:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(rows_sorted, f, indent=2)


def render_report(rows, ctx, summary_stats):
    """Human-readable Markdown report. WOULD_REJECT first (highest
    signal), SUSPICIOUS next, then aggregate counts. CLEAN entries
    are not listed (would be 95%+ of placements)."""
    out = []
    out.append('# Placement validation report')
    out.append('')
    out.append(f'**Total placements scanned:** {summary_stats["total"]}')
    out.append(f'**Seeds:** {summary_stats["n_seeds"]} '
               f'({", ".join(str(s) for s in sorted(summary_stats["seeds"])[:10])}'
               f'{"..." if len(summary_stats["seeds"]) > 10 else ""})')
    out.append(f'**Engine fingerprints:** '
               f'{", ".join(sorted(summary_stats["fingerprints"]))}')
    out.append(f'**chaos_mode:** {ctx.chaos_mode}')
    out.append('')
    out.append('| Status | Count | % |')
    out.append('|---|---:|---:|')
    for st in ('CLEAN', 'RELEASED', 'SUSPICIOUS', 'WOULD_REJECT'):
        n = summary_stats["status_counts"].get(st, 0)
        pct = (100.0 * n / summary_stats["total"]
               if summary_stats["total"] else 0.0)
        out.append(f'| {st} | {n} | {pct:.1f}% |')
    out.append('')

    def _section(status, header):
        entries = [r for r in rows if r['status'] == status]
        if not entries:
            return
        out.append(f'## {header} ({len(entries)})')
        out.append('')
        # Group by (msb, pi, target_cp) to collapse same-pair-across-seeds.
        grouped = collections.defaultdict(list)
        for r in entries:
            key = (r['msb'], r['pi'], r['src_cp'], r['target_cp'])
            grouped[key].append(r)
        for key in sorted(grouped.keys()):
            rs = grouped[key]
            r0 = rs[0]
            seeds = sorted(set(r['seed'] for r in rs))
            seeds_str = (', '.join(str(s) for s in seeds[:5])
                         + (f' (+{len(seeds)-5} more)'
                            if len(seeds) > 5 else ''))
            nl_suffix = ''
            if r0.get('named_location'):
                nl_suffix = (f' — *{r0["named_location"]["label"]}*'
                             f' [`{r0["named_location"]["category"]}`]')
            out.append(f'### `{r0["msb"]}` pi={r0["pi"]} '
                       f'— {r0["src_cp"]} → {r0["target_cp"]}{nl_suffix}')
            out.append('')
            out.append(f'- **Source:** `{r0["src_cp"]}` "{r0["src_name"]}"')
            out.append(f'- **Target:** `{r0["target_cp"]}` '
                       f'"{r0["target_name"]}"')
            out.append(f'- **Position:** `{r0["pos"]}`')
            out.append(f'- **Catalog tier:** `{r0["catalog_tier"]}`')
            out.append(f'- **Seeds:** {len(seeds)} ({seeds_str})')
            if r0['gates_fired']:
                out.append(f'- **Gates fired:**')
                for g in r0['gates_fired']:
                    rel = (f' (released_by=`{g["released_by"]}`)'
                           if g['released_by'] else '')
                    out.append(f'  - `{g["name"]}`{rel} — '
                               f'`{json.dumps(g["evidence"])}`')
            if r0['suspicious_tags']:
                out.append(f'- **Suspicious tags:**')
                for t in r0['suspicious_tags']:
                    out.append(f'  - {t}')
            out.append('')

    _section('WOULD_REJECT', 'WOULD_REJECT — gate said reject, no release')
    _section('SUSPICIOUS', 'SUSPICIOUS — watch-list patterns')

    # Per-gate release counts (aggregate).
    out.append('## Aggregate gate-fire counts')
    out.append('')
    out.append('| Gate | Total fires | Released | Unreleased |')
    out.append('|---|---:|---:|---:|')
    counts = summary_stats['gate_counts']
    for name in sorted(counts.keys()):
        total = counts[name]['total']
        rel = counts[name]['released']
        unr = total - rel
        out.append(f'| `{name}` | {total} | {rel} | {unr} |')
    out.append('')
    return '\n'.join(out)


# ============================================================================
# CLI
# ============================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spoilers', nargs='+',
                    help='Spoiler JSON files (or globs).')
    ap.add_argument('--manifest', default=None,
                    help='Output manifest JSON path (use "-" for stdout). '
                         'If unset, no JSON manifest is written.')
    ap.add_argument('--report', default=None,
                    help='Output Markdown report path. If unset, no report '
                         'is written and a summary is printed to stderr.')
    ap.add_argument('--chaos-mode', default=False,
                    type=lambda s: s.lower() in ('true', '1', 'yes', 'y'),
                    help='Treat the run as chaos_mode=True for gate eval. '
                         'Default False (conservative; matches most runs).')
    ap.add_argument('--engine-dir', default=None,
                    help='Path to the rando engine dir (containing '
                         'oops_v3.py). Defaults to this script\'s parent '
                         'directory. Matches simulate_seeds.py convention.')
    ap.add_argument('--filter', default=None,
                    choices=['CLEAN', 'RELEASED', 'SUSPICIOUS', 'WOULD_REJECT'],
                    help='Print to stdout only entries with this status. '
                         'Useful for quick triage: --filter WOULD_REJECT.')
    args = ap.parse_args(argv)

    # Expand globs (Windows shells don't auto-expand).
    spoiler_paths = []
    for s in args.spoilers:
        if any(c in s for c in '*?['):
            spoiler_paths.extend(sorted(glob.glob(s)))
        else:
            spoiler_paths.append(s)
    if not spoiler_paths:
        sys.stderr.write('ERROR: no spoilers matched\n')
        return 2

    sys.stderr.write(f'Loading engine (oops_v3.load_data)... ')
    sys.stderr.flush()
    _ensure_engine_loaded(engine_dir=args.engine_dir)
    ctx = build_context(chaos_mode=args.chaos_mode)
    sys.stderr.write(f'done. chaos_mode={args.chaos_mode}\n')

    rows = []
    seeds = set()
    fingerprints = set()
    status_counts = collections.Counter()
    gate_counts = collections.defaultdict(lambda: {'total': 0, 'released': 0})

    for i, path in enumerate(spoiler_paths):
        sys.stderr.write(f'[{i+1}/{len(spoiler_paths)}] {path} ... ')
        sys.stderr.flush()
        n_entries = 0
        for p in iter_spoiler_placements(path):
            v = validate_placement(p, ctx)
            n_entries += 1
            seeds.add(p.seed)
            fingerprints.add(p.engine_fingerprint)
            status_counts[v.status] += 1
            for r in v.gates:
                if r.rejected:
                    gate_counts[r.name]['total'] += 1
                    if r.released_by:
                        gate_counts[r.name]['released'] += 1
            if v.status != 'CLEAN':
                rows.append(manifest_row(p, v, ctx))
        sys.stderr.write(f'{n_entries} entries\n')

    summary_stats = {
        'total': sum(status_counts.values()),
        'n_seeds': len(seeds),
        'seeds': seeds,
        'fingerprints': fingerprints,
        'status_counts': dict(status_counts),
        'gate_counts': dict(gate_counts),
    }

    if args.manifest:
        write_manifest(rows, args.manifest)
    if args.report:
        report = render_report(rows, ctx, summary_stats)
        with open(args.report, 'w', encoding='utf-8') as f:
            f.write(report)

    # Stderr summary always.
    sys.stderr.write('\n=== Summary ===\n')
    sys.stderr.write(f'  Total placements: {summary_stats["total"]}\n')
    for st in ('CLEAN', 'RELEASED', 'SUSPICIOUS', 'WOULD_REJECT'):
        n = status_counts.get(st, 0)
        pct = (100.0 * n / summary_stats["total"]
               if summary_stats["total"] else 0.0)
        sys.stderr.write(f'  {st:14s}: {n:6d}  ({pct:5.1f}%)\n')

    if args.filter:
        for r in sorted(rows, key=lambda r: (
                r['status'], r['msb'], r['pi'], r['seed'])):
            if r['status'] == args.filter:
                print(json.dumps(r))

    return 0 if status_counts.get('WOULD_REJECT', 0) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
