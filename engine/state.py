"""GateState — immutable snapshot of the engine's mutable gate state.

WHY THIS EXISTS
---------------
The oops_v3 module mutates ~10 set-typed globals during load_data() and
cmd_shuffle_v3():

    V3_EXCLUDE_PREFIXES, V3_EXCLUDE_TARGET_PREFIXES,
    V3_GHOST_EXCLUDE_TARGET_PREFIXES, V3_MP_SAFE_BLOCKLIST,
    V3_HERITAGE_ALL_PREFIXES,
    V3_NIGHT_BOSS_CALIBER_TARGETS, V3_NIGHT_BOSS_STRICT_TARGETS,
    V3_ARENA_ONLY_TARGETS, V3_AVOID_VARIANT_NPC_IDS, V3_HUB_MAPS

Pack loaders write to these via the `global` keyword. cmd_shuffle_v3
manually save/restores four of them per run. Predicate functions
(_filter_avoid_npc, is_boss_tier_prefix) read them via direct module
reference. Every recent leak (v0.24.20 MP-safe, the merchant pool
issue) has involved this state-by-side-effect coupling.

WHAT THIS DOES
--------------
GateState packages those globals into an immutable dataclass that
predicate functions can take as an explicit argument. Existing call
sites still work (predicates default to reading from the module when
gates=None), but new code paths — especially tests — can construct a
GateState with just the fields they care about, pass it in, and avoid
both monkeypatching AND coupling to whatever load_data happens to put
in the module.

The dataclass is frozen — every "modification" produces a new instance
via .replace() — so a test that takes a snapshot can never have its
state altered by another code path.

Phase 1 (this file): predicate functions accept gates=None and fall
back to module globals. Tests can opt-in to explicit gates one at a
time.

Phase 2 (Phase 2 shipped): cmd_shuffle_v3's save/restore became a
GateState.scoped() context manager via engine.runtime.apply_run_overrides.

Phase 7 (v0.24.22): BFER compatibility removed. bfer_all_prefixes,
bfer_specific_avoid_npc_ids, and bfer_unrestricted_test_mode fields
all went away with the BFER asset pack itself (none of the
compatibility work ever produced a confirmed-working placement).
"""
from dataclasses import dataclass, field, replace as _dataclass_replace
from typing import FrozenSet, Optional


@dataclass(frozen=True)
class GateState:
    """Snapshot of mutable gate/exclusion state.

    Fields drop the historical V3_ prefix — inside this namespace it
    carried no information. Sets are stored as frozenset for cheap
    aliasing and immutability guarantees.
    """

    # ----- Source-side / target-side hard blocks -----
    # Source-side: c-prefixes whose vanilla MSB Parts will NOT be picked
    # as recipient slots for a swap. Currently mutated only by
    # cmd_shuffle_v3 when excluded_prefixes kwarg is set.
    exclude_prefixes: FrozenSet[str] = frozenset()

    # Target-side: c-prefixes that will NOT be placed at any slot. The
    # most-mutated set in the engine — written by mmv loader (blacklist
    # additions), cinematic auto-exclude, empty-variant auto-exclude,
    # tag-with-no-variants auto-exclude, cmd_shuffle_v3 force-include
    # subtraction.
    exclude_target_prefixes: FrozenSet[str] = frozenset()

    # Target-side "ghost" excludes: heritage-style chrs that aren't on
    # the user's disk. Layered on top of exclude_target_prefixes by
    # apply_merchant_model_swaps and the main picker. When
    # multiplayer_safe=True, cmd_shuffle_v3 unions mp_safe_blocklist
    # into this set for the run.
    ghost_exclude_target_prefixes: FrozenSet[str] = frozenset()

    # ----- MP-safe (v0.24.20) -----
    # Derived at load_data time from `_source` tagging. Any cp whose
    # _source is not in V3_VANILLA_NR_SOURCES ('nr_placed' /
    # 'script_spawn') lands here. Replaces the hand-curated
    # V3_HERITAGE_ALL_PREFIXES for the multiplayer_safe gate's purposes.
    mp_safe_blocklist: FrozenSet[str] = frozenset()

    # ----- Heritage prefix set -----
    # Hand-curated. After the v0.24.20 split, this is no longer the
    # MP-safe gate — it's now only used by is_boss_tier_prefix's
    # heritage+hp_median≥300 leg. Renaming candidate (see flagged
    # divergence with heritage_pack.json v2 manifest).
    heritage_all_prefixes: FrozenSet[str] = frozenset()

    # ----- Tier targeting -----
    # Caliber: cps eligible for NB-anchor slots (broad set).
    night_boss_caliber_targets: FrozenSet[str] = frozenset()
    # Strict: Nightlord-tier cps. Subset of caliber.
    night_boss_strict_targets: FrozenSet[str] = frozenset()
    # Arena-only: cps whose placement is restricted to boss arena slots
    # (expects_boss_arena=True). Auto-extended at load_data.
    arena_only_targets: FrozenSet[str] = frozenset()

    # ----- Variant-level avoids -----
    # NPC param IDs to filter out of pick_variant_for_tier. Mutated by
    # the PROBE_TARGET_VARIANT block in load_data.
    avoid_variant_npc_ids: FrozenSet[int] = frozenset()

    # ----- Per-run config -----
    # Hub maps where ALL part-Parts are passed through unmodified.
    # Saved/restored by cmd_shuffle_v3 like the exclude sets.
    hub_maps: FrozenSet[str] = frozenset()

    # =====================================================================
    # Construction helpers
    # =====================================================================

    @classmethod
    def from_module(cls, module=None) -> 'GateState':
        """Snapshot the current state of an oops_v3-like module.

        This captures the live module globals into an immutable instance.
        After this returns, mutations to the module globals do NOT
        affect the returned GateState — that's the whole point.

        Pass `module` explicitly to snapshot something other than
        oops_v3 (e.g. a mock or a fresh import in a test). Default is
        the real oops_v3.
        """
        if module is None:
            import oops_v3
            module = oops_v3
        return cls(
            exclude_prefixes=frozenset(module.V3_EXCLUDE_PREFIXES),
            exclude_target_prefixes=frozenset(module.V3_EXCLUDE_TARGET_PREFIXES),
            ghost_exclude_target_prefixes=frozenset(
                module.V3_GHOST_EXCLUDE_TARGET_PREFIXES),
            mp_safe_blocklist=frozenset(module.V3_MP_SAFE_BLOCKLIST),
            heritage_all_prefixes=frozenset(module.V3_HERITAGE_ALL_PREFIXES),
            night_boss_caliber_targets=frozenset(
                module.V3_NIGHT_BOSS_CALIBER_TARGETS),
            night_boss_strict_targets=frozenset(
                module.V3_NIGHT_BOSS_STRICT_TARGETS),
            arena_only_targets=frozenset(module.V3_ARENA_ONLY_TARGETS),
            avoid_variant_npc_ids=frozenset(module.V3_AVOID_VARIANT_NPC_IDS),
            hub_maps=frozenset(module.V3_HUB_MAPS),
        )

    @classmethod
    def empty(cls) -> 'GateState':
        """A gate state with all sets empty.

        For tests that want to exercise a predicate against a clean
        state — no pre-loaded heritage list, no MP-safe blocklist,
        nothing. Then `.replace(field=...)` to set just what the test
        cares about.
        """
        return cls()

    def replace(self, **changes) -> 'GateState':
        """Return a copy with field overrides.

        Wraps dataclasses.replace so tests don't need to import it
        directly. Frozenset fields can take any iterable — they're
        coerced via __post_init__-style normalization below.
        """
        # Coerce any set-like overrides to frozenset for consistency
        # with the dataclass's stated invariant. (frozen=True means we
        # can't mutate self, but `replace` constructs a fresh instance.)
        coerced = {}
        for k, v in changes.items():
            current = getattr(self, k)
            if isinstance(current, frozenset) and not isinstance(v, frozenset):
                coerced[k] = frozenset(v)
            else:
                coerced[k] = v
        return _dataclass_replace(self, **coerced)


def _resolve_gates(gates: Optional[GateState]) -> GateState:
    """Internal helper for predicate functions.

    If `gates` is None, snapshot the current module state. Otherwise
    return it as-is. This is the back-compat seam — existing callers
    pass nothing and get the same behavior they always had; new callers
    (especially tests) pass an explicit GateState and decouple from
    module globals entirely.

    PERFORMANCE NOTE: snapshotting from the module is O(total set
    sizes). On hot paths this adds up — measured ~5us per call against
    the live module state. Phase 3 will eliminate this by passing
    GateState through cmd_shuffle_v3's call tree explicitly, so the
    snapshot happens once per run instead of once per predicate call.
    For Phase 1 the overhead is acceptable.
    """
    if gates is None:
        return GateState.from_module()
    return gates
