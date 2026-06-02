"""Per-slot target picker (extracted from oops_v3.py).

WHAT THIS IS
------------
`pick_target_cp` is THE main decision function — called once per swap
slot during shuffle_msb_v3 to choose what c-prefix should replace the
slot's vanilla source. It applies the full gate cascade in order:
reservation early-return → tier/family compatibility → mirror-
semantic gates (NB-caliber, source-anim, quadruped-unsafe, field-
boss-at-strict-NB; all delegated to engine.rejection) → frequency
caps → SoTE/sote-mode source-prefix filter → freeze-prone import
gating → starting-encampment trash override → arena-only target
preservation → diagnostic-mode forcing → preserve-slots / preserve-
nightboss-arenas → finally the RNG draw via _choose_with_budget.

It is the runtime mirror counterpart to engine.rejection
.score_slot_for_unique (the reservation-time scorer).

WHY IT WAS EXTRACTED
--------------------
1014 lines — the largest single function in oops_v3.py. Pulling it
out shrinks the host module by the most of any single move, and
gives the runtime pick path its own testable seam.

The dependency surface is large (42 V3_* gate sets, 2 _V3_* state
dicts, 5 private helpers, 3 public helpers) but mechanical — every
name binds from `ns` once at the top of the function, then the body
reads identically to the pre-extraction source.

INTERNAL CALL: engine.rejection.reject_target_for_slot
------------------------------------------------------
The picker calls `_reject_target_for_slot(...)` at multiple points
in the gate cascade. After extraction, those calls are rewritten to
`reject_target_for_slot(ns, ...)` — the engine.rejection function
directly (no shim hop through oops_v3). Both functions now live in
sibling engine modules and the runtime picker / reservation scorer
share one canonical predicate.
"""
from __future__ import annotations

from engine.rejection import reject_target_for_slot


def pick_target_cp(ns, recipient_cp, tags,
                    prefix_variants, prefix_count, recipient_is_boss, rng,
                    target_count=None,
                    slot_y=None,
                    slot_msb_name=None, slot_pi=None, slot_variant_name=None,
                    slot_pos=None,
                    slot_eid=None,
                    slot_require_boss_reward=False,
                    disable_resilient_filter=False,
                    non_fragile_baseline_cp=None,
                    diagnostic_test_targets=None,
                    chaos_mode=False,
                    gates=None,
                    run_ctx=None):
    """Pick a target c-prefix for a swap slot from the compatible pool,
    after applying excludes, tier-preserve, fragility, and frequency caps.

    v0.23.72-late: removed long-vestigial `bank_to_prefixes`,
    `loose_to_prefixes`, and `mode` parameters from the signature. They
    were threaded through to `compatible_pool()` which had been ignoring
    them since v0.20.0 (universal-pool refactor); the placement chain is
    "everything in tags, then post-filter" and has no use for them. See
    `compatible_pool` docstring for the cleanup notes.

    v0.23.72-late: removed the FI tracking scaffolding (FI_TRACKED set,
    _bump_stage per-stage counters, FI_DROP_FIRST_OBSERVED trace event,
    _V3_FI_RETURNED_COUNTS, _V3_FI_STAGE_TRACKER). These had been
    investigation-only tooling for the v0.20.1–v0.20.4 force-include
    debugging series and were no longer load-bearing. The four
    permanent regression guards (TAGS_INTEGRITY, EXCLUDE_INTEGRITY,
    EXCLUDE_SNAPSHOT_AT_RUN_START, TAG_OVERRIDES_APPLIED) remain in
    the trace buffer.

    v0.24.21: `gates` parameter. When None (default), reads
    V3_EXCLUDE_PREFIXES, V3_EXCLUDE_TARGET_PREFIXES,
    V3_GHOST_EXCLUDE_TARGET_PREFIXES, V3_ARENA_ONLY_TARGETS,
    V3_NIGHT_BOSS_STRICT_TARGETS, V3_NIGHT_BOSS_CALIBER_TARGETS from
    the module — preserves pre-existing behavior. When a GateState is
    passed, reads those values from the snapshot instead. See
    engine/state.py.

    v0.24.22: BFER gates (V3_BFER_ALL_PREFIXES,
    BFER_UNRESTRICTED_TEST_MODE) removed with the BFER asset pack
    cleanup (Phase 7)."""
    # Bind module-level dependencies into locals — same pattern
    # as the other engine.* extractions. The hot-path benefit is
    # especially valuable here: pick_target_cp is called once
    # per swap slot (~5000 per shuffle) and each invocation hits
    # ~40 V3_* gate sets and several helper functions.
    #
    # V3_* state — read-only configuration:
    V3_ADD_RANDOMIZE_ARENAS = ns['V3_ADD_RANDOMIZE_ARENAS']
    V3_ARENA_ONLY_TARGETS = ns['V3_ARENA_ONLY_TARGETS']
    V3_BOSS_NAME_MARKERS = ns['V3_BOSS_NAME_MARKERS']
    V3_BOSS_SLOT_CATALOG = ns['V3_BOSS_SLOT_CATALOG']
    V3_BOSS_STRENGTH_TIERS = ns['V3_BOSS_STRENGTH_TIERS']
    V3_CATALOG_BOSS_ARENA_TIERS = ns['V3_CATALOG_BOSS_ARENA_TIERS']
    V3_EXCLUDE_PREFIXES = ns['V3_EXCLUDE_PREFIXES']
    V3_EXCLUDE_TARGET_PREFIXES = ns['V3_EXCLUDE_TARGET_PREFIXES']
    V3_FIELD_STRENGTH_TIERS = ns['V3_FIELD_STRENGTH_TIERS']
    V3_FRAGILE_SAFE_CONFIRMED = ns['V3_FRAGILE_SAFE_CONFIRMED']
    V3_FRAGILE_SENSITIVE_TARGETS = ns['V3_FRAGILE_SENSITIVE_TARGETS']
    V3_FREEZE_PRONE_IMPORTS = ns['V3_FREEZE_PRONE_IMPORTS']
    V3_GHOST_EXCLUDE_TARGET_PREFIXES = ns['V3_GHOST_EXCLUDE_TARGET_PREFIXES']
    V3_MAP_PREFIX_TARGET_EXCLUDES = ns['V3_MAP_PREFIX_TARGET_EXCLUDES']
    V3_MOUNT_PREFIXES = ns['V3_MOUNT_PREFIXES']
    V3_NB_RANDOMIZE_WHITELIST = ns['V3_NB_RANDOMIZE_WHITELIST']
    V3_NIGHT_BOSS_ARENA_MSBS = ns['V3_NIGHT_BOSS_ARENA_MSBS']
    V3_NIGHT_BOSS_CALIBER_TARGETS = ns['V3_NIGHT_BOSS_CALIBER_TARGETS']
    V3_NIGHT_BOSS_EXCLUDE_TARGETS = ns['V3_NIGHT_BOSS_EXCLUDE_TARGETS']
    V3_NIGHT_BOSS_NAME_MARKERS = ns['V3_NIGHT_BOSS_NAME_MARKERS']
    V3_NIGHT_BOSS_ONLY_TARGETS = ns['V3_NIGHT_BOSS_ONLY_TARGETS']
    V3_NIGHT_BOSS_STRICT_TARGETS = ns['V3_NIGHT_BOSS_STRICT_TARGETS']
    V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS = ns['V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS']
    V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS = ns['V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS']
    V3_OVERLAY_PRESERVE_VANILLA_MSBS = ns['V3_OVERLAY_PRESERVE_VANILLA_MSBS']
    V3_PRESERVE_NIGHT_BOSS_ARENAS = ns['V3_PRESERVE_NIGHT_BOSS_ARENAS']
    V3_PRESERVE_SLOTS = ns['V3_PRESERVE_SLOTS']
    V3_PROBLEM_SLOT_EXTRA_ALLOWS = ns['V3_PROBLEM_SLOT_EXTRA_ALLOWS']
    V3_PROBLEM_SLOT_EXTRA_BANS = ns['V3_PROBLEM_SLOT_EXTRA_BANS']
    V3_RANDOMIZE_ALL_NB_ARENAS = ns['V3_RANDOMIZE_ALL_NB_ARENAS']
    V3_RANDOMIZE_SAFE_NB_ARENAS = ns['V3_RANDOMIZE_SAFE_NB_ARENAS']
    V3_RESILIENT_BIPEDS = ns['V3_RESILIENT_BIPEDS']
    V3_RIDER_PREFIXES = ns['V3_RIDER_PREFIXES']
    V3_SAFE_NB_RANDOMIZE_MSBS = ns['V3_SAFE_NB_RANDOMIZE_MSBS']
    V3_SENSITIVE_ONLY_SLOTS = ns['V3_SENSITIVE_ONLY_SLOTS']
    V3_SOTE_MODE = ns['V3_SOTE_MODE']
    V3_SOTE_PREFIXES = ns['V3_SOTE_PREFIXES']
    V3_STARTING_ENCAMPMENT_MSBS = ns['V3_STARTING_ENCAMPMENT_MSBS']
    V3_STARTING_ENCAMPMENT_TRASH_GATE = ns['V3_STARTING_ENCAMPMENT_TRASH_GATE']
    V3_TARGET_PLACEMENT_CAP = ns['V3_TARGET_PLACEMENT_CAP']
    V3_TRASH_PREFIXES = ns['V3_TRASH_PREFIXES']
    V3_UNIQUE_TARGET_CAPS = ns['V3_UNIQUE_TARGET_CAPS']
    # _V3_* state — read-only on this hot path (mutated by the
    # reservation pre-pass and the post-pick bump below). Legacy
    # callers (run_ctx is None) read these; modern callers route
    # through run_ctx instead.
    _V3_UNIQUE_PLACED_COUNTS = ns['_V3_UNIQUE_PLACED_COUNTS']
    _V3_UNIQUE_RESERVATIONS = ns['_V3_UNIQUE_RESERVATIONS']
    # oops_v3 helper functions (underscore-prefixed internals):
    _choose_with_budget = ns['_choose_with_budget']
    _load_off_mesh_slots = ns['_load_off_mesh_slots']
    _selected_swap_family = ns['_selected_swap_family']
    _slot_decision_rng = ns['_slot_decision_rng']
    # oops_v3 public helpers:
    compatible_pool = ns['compatible_pool']
    field_roll_tier_for = ns['field_roll_tier_for']
    is_fragile_slot = ns['is_fragile_slot']
    # Resolve the six mutable gate refs this function reads. The
    # gates=None path reads module globals directly (no GateState
    # coercion overhead — keeps the hot-path call cost identical to
    # pre-v0.24.21). The explicit-gates path reads from the snapshot.
    if gates is None:
        _exclude = V3_EXCLUDE_PREFIXES
        _exclude_target = V3_EXCLUDE_TARGET_PREFIXES
        _ghost_exclude = V3_GHOST_EXCLUDE_TARGET_PREFIXES
        _arena_only = V3_ARENA_ONLY_TARGETS
        _nb_strict = V3_NIGHT_BOSS_STRICT_TARGETS
        _nb_caliber = V3_NIGHT_BOSS_CALIBER_TARGETS
    else:
        _exclude = gates.exclude_prefixes
        _exclude_target = gates.exclude_target_prefixes
        _ghost_exclude = gates.ghost_exclude_target_prefixes
        _arena_only = gates.arena_only_targets
        _nb_strict = gates.night_boss_strict_targets
        _nb_caliber = gates.night_boss_caliber_targets
    # v0.24.21 (Phase 5): runtime bookkeeping refs. Same pattern as gates:
    # run_ctx=None reads/writes module dicts (preserving back-compat for
    # all pre-Phase 5 callers); explicit RunContext reads/writes the
    # snapshot's dicts. See engine/runctx.py.
    if run_ctx is None:
        _placed_counts = _V3_UNIQUE_PLACED_COUNTS
        _reservations = _V3_UNIQUE_RESERVATIONS
    else:
        _placed_counts = run_ctx.unique_placed_counts
        _reservations = run_ctx.unique_reservations
    # v0.20.38: non-fragile-baseline intercept. When this is set and the
    # slot is NOT fragile, return the baseline c-prefix immediately.
    # Used during diagnostic runs to force visual consistency at safe
    # slots — anything visibly different in the world becomes a definite
    # fragile-slot test. Bypasses tier/compat/excludes (similar to
    # oops_all_target_cp). If the slot IS fragile, fall through to the
    # normal flow (which respects disable_resilient_filter / SENSITIVE).
    if non_fragile_baseline_cp and slot_msb_name is not None:
        if not is_fragile_slot(slot_msb_name, slot_pi, slot_variant_name,
                                slot_pos=slot_pos):
            return non_fragile_baseline_cp

    # v0.26.16: NB-arena randomization override. Exempts an arena from
    # ALL THREE NB preservation gates below so its boss Part gets
    # swapped; EMEVD stays vanilla either way (the healthbar step
    # preserves NB-arena EMEVD separately). Three scopes, OR-combined:
    #   V3_RANDOMIZE_SAFE_NB_ARENAS   -- the 12 single-boss arenas only.
    #   V3_RANDOMIZE_ALL_NB_ARENAS    -- all 25, incl. the multi-entity
    #     arenas whose synchronized boss-init is known to break (the
    #     experimental switch).
    #   V3_NB_RANDOMIZE_WHITELIST     -- v0.28.x finer-grained gate. The
    #     specific arenas in data/nb_encounter_whitelist.json, paired
    #     with the param-side LotResultSmallBaseAndSpot patch that
    #     constrains the game's overlay lottery to the same set. See
    #     block comment near V3_NB_RANDOMIZE_WHITELIST for context.
    _force_rando_nb = (
        slot_msb_name is not None
        and ((V3_RANDOMIZE_ALL_NB_ARENAS
              and slot_msb_name in V3_NIGHT_BOSS_ARENA_MSBS)
             or (V3_RANDOMIZE_SAFE_NB_ARENAS
                 and slot_msb_name in V3_SAFE_NB_RANDOMIZE_MSBS)
             or slot_msb_name in V3_NB_RANDOMIZE_WHITELIST))

    # v0.25.1: arena-chr-role catalog whole-MSB vanilla preservation.
    # MSBs in V3_OVERLAY_PRESERVE_VANILLA_MSBS are flagged
    # 'preserve_primary' by data/nr_boss_arena_chr_roles.json — multi-
    # wave / multi-entity / hardcoded-anim arenas where ANY Part swap
    # risks breaking the choreographed wake-handshake chain. Return
    # None for every Part in those MSBs, regardless of pi or tier.
    # See block comment near V3_OVERLAY_PRESERVE_VANILLA_MSBS for context.
    if (slot_msb_name is not None
            and slot_msb_name in V3_OVERLAY_PRESERVE_VANILLA_MSBS
            and not _force_rando_nb):
        # v0.27.0: add-randomize arenas preserve the boss Part only -
        # non-boss (add) Parts fall through to normal randomization.
        if not (slot_msb_name in V3_ADD_RANDOMIZE_ARENAS
                and not recipient_is_boss):
            return None

    # v0.26.16: night-boss-arena whole-MSB preservation. When test-mode
    # arenas are OFF (normal play), V3_PRESERVE_NIGHT_BOSS_ARENAS is True
    # and every Part in a night-boss arena is held vanilla — a catalog-
    # independent backstop. See block comment near V3_NIGHT_BOSS_ARENA_MSBS.
    if (V3_PRESERVE_NIGHT_BOSS_ARENAS and slot_msb_name is not None
            and slot_msb_name in V3_NIGHT_BOSS_ARENA_MSBS
            and not _force_rando_nb):
        # v0.27.0: add-randomize arenas preserve the boss Part only.
        if not (slot_msb_name in V3_ADD_RANDOMIZE_ARENAS
                and not recipient_is_boss):
            return None

    # v0.24.101: V3_PRESERVE_SLOTS strict (msb, pi)-level preservation gate.
    # When the slot is in V3_PRESERVE_SLOTS, return None so the Part stays
    # vanilla. Mirrors the check inside _score_slot_for_unique (line ~9549,
    # added v0.23.74) which only gated the unique-reservation pre-pass —
    # the normal swap path was bypassing the set entirely, so e.g. m49_28
    # pi=2/3 Cavalry NB riders were still getting swapped despite being
    # listed in V3_PRESERVE_SLOTS. Playtest seed 537123 v0.24.96 showed
    # Rellana and Bell Bearing Hunter at the supposedly-preserved m49_28
    # arena. Adding the gate here closes that loop.
    if slot_msb_name is not None and slot_pi is not None:
        if ((slot_msb_name, slot_pi) in V3_PRESERVE_SLOTS
                and not _force_rando_nb):
            return None

    # v0.23.07: Unique-target reservation early-return. If this slot was
    # reserved during the pre-pass for a capped c-prefix, commit that pick
    # directly (bypasses tier/compat — the pre-pass already validated
    # swap compat and source-preservation status). The pre-pass
    # already bumped _V3_UNIQUE_PLACED_COUNTS at reservation time so the
    # cap-exhausted gate sees this cp as filled before any per-MSB
    # processing — don't double-bump here.
    #
    # v0.27.13: skipped under V3_SOTE_MODE. The pre-pass is origin-blind,
    # so a reservation may name a non-SOTE cp; committing it here would
    # bypass the SOTE pool intersection below and leak a non-SOTE enemy
    # into a SOTE run. SOTE mode runs uncapped anyway, so dropping the
    # reservation shortcut costs nothing.
    #
    # v0.27.13: a reservation value is either a cp string (c-prefix
    # floor) or a (cp, group) tuple (variant-group floor). pick_target_cp
    # only deals in c-prefixes, so strip the tuple to its cp here. The
    # group half of the tuple is re-read independently by pick_target
    # (via _reserved_variant_group) to pin the variant pick — keeping
    # this function's contract unchanged (it still returns a bare cp).
    if (slot_msb_name is not None and slot_pi is not None
            and not V3_SOTE_MODE):
        _res_key = (slot_msb_name, slot_pi)
        if _res_key in _reservations:
            _rv = _reservations[_res_key]
            return _rv[0] if isinstance(_rv, tuple) else _rv

    pool = compatible_pool(recipient_cp, tags)
    pool = pool - _exclude - _exclude_target - _ghost_exclude

    # v0.28.x+: hoisted slot-catalog-tier resolution. The original
    # computation lived ~440 lines below at line 14093 (post-tier-filter,
    # pre-arena-only gate). It's needed earlier now for two reasons:
    #   1. Cap-block exemption for nightboss-catalogued slots (the
    #      cap-block gate sits right below) — climactic encounters are
    #      rare to actually face in a seed, so the unique-placement caps
    #      shouldn't shrink the eligible pool for them.
    #   2. Tier-aware fallback for nightboss-catalogued slots — never
    #      degrade an NB slot below field_boss, even when the candidate
    #      pool empties after downstream gates.
    # Cheap dict lookup; safe to compute eagerly. The downstream block
    # that previously did this resolution now reads the value computed
    # here (no duplicate work).
    _slot_catalog_tier = None
    if slot_msb_name is not None and slot_pi is not None:
        _slot_catalog_tier = V3_BOSS_SLOT_CATALOG.get(
            (slot_msb_name, slot_pi), {}).get('tier')
    _is_catalogued_boss_arena = _slot_catalog_tier in V3_CATALOG_BOSS_ARENA_TIERS
    _is_nightboss_slot = (_slot_catalog_tier == 'nightboss')

    # v0.23.07: Subtract cap-exhausted unique-target c-prefixes. Any cp
    # that has already hit its V3_UNIQUE_TARGET_CAPS limit can't be
    # picked at non-reserved slots. Reserved slots already early-returned
    # above. Cheap set-comprehension so the per-slot overhead is minimal.
    #
    # v0.27.13: skipped under V3_SOTE_MODE — SOTE runs are uncapped (the
    # SOTE set is small and meant to repeat freely).
    #
    # v0.28.x+: also skipped at nightboss-catalogued slots. NB encounters
    # are climactic Day-3 events; the player only sees one per seed in
    # actual play, so capping NB-eligible placements globally over-
    # restricts the per-slot pool. The cap-bump at the end of this
    # function is correspondingly gated by the same condition so that NB
    # placements don't burn cap room for non-NB placements either.
    if not V3_SOTE_MODE and not _is_nightboss_slot:
        # v0.28: global-cap gate with MSB-boundary semantics. Use the set
        # frozen at begin_msb (cps already at/over cap when this MSB
        # started). A cp can overshoot its cap mid-MSB via free recycling
        # and only gets blocked from the NEXT MSB on. Falls back to live
        # computation when there is no frozen set (legacy callers / tests),
        # preserving pre-v0.28 behavior exactly.
        _blocked = getattr(run_ctx, 'msb_blocked_cps', None)
        if _blocked is None and _placed_counts:
            _blocked = {cp for cp, n in _placed_counts.items()
                        if n >= V3_UNIQUE_TARGET_CAPS.get(cp, 0)}
        if _blocked:
            pool = pool - _blocked
    # v0.20.20: per-map-prefix target-side excludes. See
    # V3_MAP_PREFIX_TARGET_EXCLUDES for rationale (Limveld Maris-cluster
    # CTD).
    if slot_msb_name:
        for _mp_prefix, _excl in V3_MAP_PREFIX_TARGET_EXCLUDES.items():
            if slot_msb_name.startswith(_mp_prefix):
                pool = pool - _excl
    pool = {cp for cp in pool if cp in prefix_variants and prefix_variants[cp]}
    # v0.27.13: ALL-SOTE MODE — intersect the target pool with the
    # Shadow-of-the-Erdtree set. Runs AFTER the hard excludes, so a
    # CTD-blacklisted / asset-missing SOTE chr stays out (its exclude
    # wins). The tier-preserve filter below still narrows per slot; if
    # the intersection empties the pool the slot falls through to the
    # `not pool` return and stays vanilla — acceptable for the thin
    # tails (e.g. a flier-required slot with no SOTE flier).
    if V3_SOTE_MODE and V3_SOTE_PREFIXES:
        pool = pool & V3_SOTE_PREFIXES

    # v0.27.13: RIDER / MOUNT pool restriction. If the slot's vanilla
    # occupant is a rider, the pool is restricted to riders; if a
    # mount, to mounts. Keeps a rider slot from drawing a mount and
    # vice versa. Runs after the SOTE intersection so under all-SOTE
    # mode the pool is (SOTE ∩ role) — e.g. a mount slot becomes
    # {c5890} alone, which is the whole reason this lightweight
    # approach is correct without cross-slot atomicity (see the
    # V3_RIDER_PREFIXES block comment). HARD: if the intersection
    # empties the pool the slot falls through to the `not pool` return
    # and stays vanilla — correct, a rider slot with no eligible rider
    # should not receive a non-rider.
    if recipient_cp in V3_RIDER_PREFIXES:
        pool = pool & V3_RIDER_PREFIXES
        # v0.27.43: cross-slot family consistency. A mounted cluster's two
        # halves are swapped by INDEPENDENT per-slot picks; the role gate
        # keeps a rider on the rider slot and a mount on the mount slot but
        # never made the two agree. Under all-SOTE the per-role pools were
        # singletons so they always matched, but in non-SOTE the rider pool
        # is {c4050, c5840} while every mount slot is forced to c5890 (c4060
        # Kaiden's-Horse is target-excluded), so a c4050 draw produced a
        # Kaiden on a Black Knight Horse — a mismatched rig that hard-CTDs
        # in game. Fix: decide the whole cluster from GLOBAL placeability
        # (both gates call _selected_swap_family with the same inputs, so
        # they reach the same verdict without talking to each other). If a
        # complete swap family is available, force this rider to the family
        # rider; otherwise pin to the vanilla source rider so the cluster
        # stays a matched vanilla pair (the mount gate pins to vanilla in
        # lockstep). Restores the all-SOTE singleton invariant in every mode.
        _fam = _selected_swap_family(prefix_variants, slot_msb_name)
        if _fam is not None:
            # Force the family rider, bypassing the unique-cap subtraction
            # above: the mounted family must stay a matched pair (like the
            # SOTE singletons, which run uncapped). _selected_swap_family
            # already confirmed it passes the REAL target filters (excludes
            # / SOTE / map), and it is compat with this rider source by
            # design, so only the soft variety cap is bypassed — over-cap
            # standalone Black Knights still stop appearing (the placed
            # count keeps climbing and the general-slot filter still drops
            # them) while the mount slot commits to the matching mount.
            pool = {_fam[0]}
        else:
            pool = pool & {recipient_cp}
    elif recipient_cp in V3_MOUNT_PREFIXES:
        pool = pool & V3_MOUNT_PREFIXES
        # v0.27.43: symmetric half of the family decision above. Same global
        # verdict, applied to the mount: force the family mount (cap-bypassed,
        # see rider branch) when a complete family is available, else pin to
        # the vanilla source mount (c4060, which being target-excluded leaves
        # the pool empty -> the slot keeps its vanilla Kaiden's-Horse), so the
        # mount never lands on a slot whose rider half couldn't become its
        # matching rider.
        _fam = _selected_swap_family(prefix_variants, slot_msb_name)
        if _fam is not None:
            pool = {_fam[1]}
        else:
            pool = pool & {recipient_cp}
    else:
        # v0.27.43: symmetric completion of the gate above. A NON-role
        # source slot must never draw a MOUNT. The horses (c4060/c5890,
        # mount_role='mount') have no standalone AI brain — placed away
        # from a paired rider they spawn frozen / float in place. The
        # one-directional gate above only kept a *mount-source* slot
        # restricted to mounts; it did nothing to stop a mount leaking
        # onto an ordinary slot (Imp, Wolf, Wandering Noble, …), which is
        # exactly the freeze/float placement that
        # _ctd_check_mount_target_at_non_mount_source was flagging AFTER
        # the fact (20+ findings/seed, doing nothing about them). Confining
        # mounts to mount-source slots — where the vanilla mounted-pair
        # adjacency supplies a rider — eliminates the leak at the source.
        # Riders are deliberately NOT excluded here: c4050/c5840 (Kaiden
        # Sellsword, Black Knight) are complete standalone enemies and
        # stay broad-pool targets; only the riderless horse is the hazard.
        if V3_MOUNT_PREFIXES:
            pool = pool - V3_MOUNT_PREFIXES

    # v0.27.43: starting-encampment trash gate. For slots in the spawn-
    # adjacent Expedition camps, restrict the pool to the trash-tier set so
    # the player's first fight can't roll a miniboss/night-boss-strength
    # enemy. Same intersection mechanism as the SOTE / rider-mount blocks
    # above: runs after the hard excludes, before the tier-preserve filter
    # (a no-op for trash — all grunt/field-strength), and an empty result
    # falls through to the `not pool` return leaving the slot vanilla (a
    # vanilla starting camp is grunts, so that's a safe floor). Placed AFTER
    # the v0.27.44 rider/mount family pinning on purpose: if that logic has
    # pinned the pool to a mounted-pair family for a camp slot, intersecting
    # with trash empties it and the slot stays its coherent vanilla pair
    # rather than getting half-randomized — mounts/riders are not trash, so
    # this is the correct interaction. The 16 sponge variants these chrs also
    # carry are handled at the variant level by V3_AVOID_VARIANT_NPC_IDS, so
    # an in-pool trash chr can't roll its beefy variant. slot_msb_name is the
    # '.msb' basename here (the .dcx is already stripped upstream), matching
    # V3_STARTING_ENCAMPMENT_MSBS — the same raw membership test the NB-arena
    # gates use.
    if (V3_STARTING_ENCAMPMENT_TRASH_GATE and V3_TRASH_PREFIXES
            and slot_msb_name is not None
            and slot_msb_name in V3_STARTING_ENCAMPMENT_MSBS):
        pool = pool & V3_TRASH_PREFIXES

    if not pool:
        return None

    # v0.20.0: tier-preserve filter — boss-tier source slots get boss-tier
    # targets, field-tier source slots get field-tier targets. Untyped
    # source falls through unfiltered. v0.23 simplification: prior to
    # retirement of tier modes, the bossy/grunt-promotion overrides could
    # set a more specific filter and skip this block; now the filter
    # always runs.
    src_tier = tags.get(recipient_cp, {}).get('tier')
    # v0.27.13: field-slot tier roll. A non-catalogued slot is decoupled
    # from its vanilla occupant's tier — it rolls grunt-base with a small
    # configurable upgrade chance (V3_FIELD_UPGRADE_*_PCT). Closes the
    # leak where a beefy-but-not-boss occupant tagged 'miniboss' opened
    # the boss-strength pool on an open-field position. recipient_is_boss
    # slots (real boss Parts in non-catalogued MSBs, e.g. add-randomize
    # arenas) keep occupant-tier-preserve.
    _field_roll_tier = (field_roll_tier_for(slot_msb_name, slot_pi)
                        if not recipient_is_boss else None)
    if _field_roll_tier is not None:
        # src_tier carries the rolled value downstream (the v0.25.6
        # remembrance size gate keys on it; rolled values never match
        # 'remembrance' so that gate is unaffected).
        src_tier = _field_roll_tier
        # Match the rolled tier EXACTLY — a miniboss roll must not yield
        # a night_boss — with a fallback ladder so a roll with no compat-
        # fitting candidate degrades toward grunt instead of leaving the
        # slot vanilla. 'grunt' resolves to the whole field-strength
        # bucket (grunt/trash/cluster_member/...).
        #
        # Exact-match deliberately excludes tier='nightlord' from every
        # field roll: the heaviest tier (true Nightlords + arena-bound
        # MMV boss imports — c6200 Gael, c5130 Messmer, c5300 Rellana,
        # all tagged 'nightlord') is never field-eligible. The night_boss
        # roll draws only from the 39 'night_boss'-tagged chrs. This is
        # what makes the c6200 hawk-route CTD structurally impossible
        # rather than merely improbable — no field slot, of any roll
        # outcome, can admit it.
        # v0.28.x: 4-tier ladder. field_boss falls back via field_boss →
        # miniboss → grunt. night_boss is unchanged: a night_boss roll
        # tries night_boss first, falls to miniboss, then grunt. A
        # field_boss roll never falls UP to night_boss (the conditional
        # promote is handled in field_roll_tier_for instead — by the time
        # the fallback ladder sees 'field_boss', the dice are settled).
        _ladder = {'night_boss': ('night_boss', 'miniboss', 'grunt'),
                   'field_boss': ('field_boss', 'miniboss', 'grunt'),
                   'miniboss':   ('miniboss', 'grunt'),
                   'grunt':      ('grunt',)}[_field_roll_tier]
        tier_pool = pool
        for _tname in _ladder:
            if _tname == 'grunt':
                _cand = {cp for cp in pool
                         if tags.get(cp, {}).get('tier')
                         in V3_FIELD_STRENGTH_TIERS}
            else:
                _cand = {cp for cp in pool
                         if tags.get(cp, {}).get('tier') == _tname}
            if _cand:
                tier_pool = _cand
                break
    elif _is_nightboss_slot:
        # v0.28.x+: tighter tier filter for nightboss-catalogued slots.
        # The user-facing principle: an NB slot is a climactic encounter,
        # and reaching down to miniboss for the swap target makes the
        # encounter feel like a field fight in a boss arena. So this
        # branch restricts the candidate pool to night_boss + nightlord
        # (both climactic-tier) as primary, then field_boss as a one-
        # step downstep, and HARD-STOPS there: if all three are empty
        # after the upstream excludes/cap-block, we return None (preserve
        # vanilla) rather than fall to miniboss/grunt.
        #
        # Contrast with the generic V3_BOSS_STRENGTH_TIERS branch below,
        # which includes miniboss as a peer of NB/FB. That branch is
        # appropriate for non-NB boss-arena slots (named_boss, fieldboss,
        # remembrance, etc.) where a miniboss-tier swap is in-character;
        # at NB slots specifically, it isn't.
        #
        # Nightlord stays in the primary bucket: it's the heaviest tier
        # (true Nightlords + arena-bound MMV boss imports like Messmer/
        # Rellana). The spoiler analysis showed nightlord chrs filling
        # NB slots prolifically — by design — so keeping them at peer
        # priority with night_boss preserves that behavior.
        _nb_primary = {cp for cp in pool
                       if tags.get(cp, {}).get('tier')
                       in ('night_boss', 'nightlord')}
        if _nb_primary:
            tier_pool = _nb_primary
        else:
            _nb_fallback = {cp for cp in pool
                            if tags.get(cp, {}).get('tier') == 'field_boss'}
            if _nb_fallback:
                tier_pool = _nb_fallback
            else:
                # No NB/nightlord/FB candidate fits this slot. Preserve
                # vanilla rather than degrade to a miniboss-tier swap.
                return None
    elif src_tier in V3_BOSS_STRENGTH_TIERS:
        tier_pool = {cp for cp in pool
                     if tags.get(cp, {}).get('tier') in V3_BOSS_STRENGTH_TIERS}
    elif src_tier in V3_FIELD_STRENGTH_TIERS:
        tier_pool = {cp for cp in pool
                     if tags.get(cp, {}).get('tier') in V3_FIELD_STRENGTH_TIERS}
    else:
        tier_pool = pool
    if tier_pool:
        pool = tier_pool

    # v0.25.6: size_class restriction for tier=remembrance source slots.
    # Some remembrance catalog entries are based on small humanoid
    # encampments / patrols (e.g. Bloodhound Knight at m60_45_39_20 pi=28
    # — size=S, anim=humanoid), not proper boss arenas. Without a size
    # gate, the picker could place a GIGA chr (e.g. c4503 Borealis,
    # hit_height=20m, anim=flying_dragon) at a humanoid-scaled slot,
    # which CTDs on tile load (chr-init can't reconcile collision/navmesh
    # bounds against the slot's geometry).
    #
    # Rule: candidate's size_class must not exceed source's by more than
    # 2 steps along the ordered ladder [XS, S, M, L, XL, XXL, GIGA]. So
    # S source → up to L candidate; M → up to XL; L → up to XXL; XL/XXL/
    # GIGA → up to GIGA (already at or near top). Candidates with
    # size_class=None (typical of utility/grunt-tier chrs that won't be
    # GIGA anyway) bypass the gate as a safe fallback.
    #
    # Scoped to remembrance only by deliberate choice (user request,
    # v0.25.6 session): named_boss / field_boss / miniboss tiers either
    # have natural size constraints from their arena bounds or have
    # source variety wide enough that adding a gate here would
    # over-restrict legitimate placements. The remembrance tier is the
    # specific failure mode surfaced in playtest.
    #
    # Falls through to the empty-pool case if the gate produces no
    # candidates — better to leave the slot vanilla than force a bad
    # match. Other gates downstream may still narrow the pool further.
    if src_tier == 'remembrance':
        _SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA']
        _src_size = tags.get(recipient_cp, {}).get('size_class')
        if _src_size in _SIZE_ORDER:
            _max_idx = _SIZE_ORDER.index(_src_size) + 2
            def _size_ok(cp):
                _sz = tags.get(cp, {}).get('size_class')
                if _sz not in _SIZE_ORDER:
                    return True  # unknown size — safe fallback
                return _SIZE_ORDER.index(_sz) <= _max_idx
            size_pool = {cp for cp in pool if _size_ok(cp)}
            if size_pool:
                pool = size_pool
            # else: leave pool alone; the source slot will stay vanilla
            # if no other gate produces a fitting candidate downstream.

    # v0.20.22: per-slot has_boss_reward filter. Used by 'boss_reward' mode
    # in V3_BOSSY_PROMOTE_SLOTS — narrows the boss-tier pool to c-prefixes
    # that have a real boss reward / arena event. Filters out e.g. c4377
    # Highwayman whose (Scholar Remembrance) variant tags it as miniboss
    # but doesn't fire the boss-arena event chain. Applied after tier so
    # we're already restricted to V3_BOSS_STRENGTH_TIERS first.
    if slot_require_boss_reward:
        reward_pool = {cp for cp in pool
                       if tags.get(cp, {}).get('has_boss_reward')}
        if reward_pool:
            pool = reward_pool
        # else: leave pool alone, the slot will fall through other filters
        # and likely return None — better than silently losing the constraint.

    # v0.27.40: freeze-prone-import addressability gate. Imports in
    # V3_FREEZE_PRONE_IMPORTS (loaded from data/phase_transition_imports.json,
    # the same file emevd_patch.py derives its re-enable markers from) disable
    # their own AI during a phase transition and need the nb_phase_reenable
    # EMEVD event to recover. That event addresses the boss by ENTITY id, so it
    # can only reach entity-bearing slots; a name-marker slot (entity_id == 0)
    # is unreachable and the boss would freeze post-transition with no remedy.
    # So at a name-marker slot, drop freeze-prone imports from the pool. Single-
    # phase imports (Manus/Romina/etc.) are NOT in the set and stay eligible at
    # name-marker terrain slots. slot_eid is the live MSB read from the caller;
    # only gate when we actually know it's a name-marker slot (eid is not None
    # and <= 0) so a missing eid (older callers) never silently empties a pool.
    if (V3_FREEZE_PRONE_IMPORTS and slot_eid is not None and slot_eid <= 0):
        gated = pool - V3_FREEZE_PRONE_IMPORTS
        # If gating would empty the pool, leave it: the slot falls through and
        # likely returns None (stays vanilla) — never force a freeze-prone
        # import onto an unreachable slot, but also never hard-crash a slot.
        if gated:
            pool = gated

    # v0.24.101: asymmetric has_reward preservation. When the recipient slot's
    # c-prefix has has_reward=True (a rewarded encounter in vanilla), restrict
    # the target pool to has_reward=True c-prefixes too. This prevents the
    # "stiffed boss" failure mode where a vanilla rewarded slot gets swapped
    # to a chr that drops nothing on death.
    #
    # Asymmetric by design: recipients with has_reward=False/None can swap
    # in either direction (so a non-rewarded slot can be upgraded to a
    # rewarded encounter — strictly better for the player). Only the
    # rewarded-source case is constrained.
    #
    # Distinct from the slot_require_boss_reward gate above:
    #   - That gate is opt-in per slot (V3_BOSSY_PROMOTE_SLOTS 'boss_reward'
    #     mode), keys on has_boss_reward (rewardItemLot_1-anchored), and is
    #     about promoting non-boss slots TO real boss arenas.
    #   - This gate is automatic on every call, keys on has_reward (broader
    #     field, includes chaosMatchingRewardLotId), and is about preserving
    #     the source slot's reward when has_reward is already True.
    #
    # If the filtered pool is empty the slot gets None and stays vanilla —
    # we'd rather skip the swap than break the reward.
    #
    # v0.27.42: do NOT reward-preserve a slot that the field-roll has
    # decoupled to a grunt position. The field-roll (v0.27.13,
    # field_roll_tier_for) deliberately severs a non-catalogued field slot
    # from its vanilla occupant — a miniboss-tagged-but-field-placed occupant
    # is re-cast as a grunt-tier slot so it draws grunt-base enemies. But
    # has_reward is TIER-DERIVED (miniboss-and-above => True, per
    # dev/emit_has_reward.py), so the occupant still carries has_reward=True
    # without dropping any real loot, and this gate then re-couples the slot
    # to that spurious reward — contradicting the decoupling the roll just
    # performed. The intersection it forms, (grunt-rolled pool) ∩
    # (has_reward=True), is near-empty because grunts are tier-derived
    # NO-reward: in the full roster it collapses to a tiny rewarded-grunt set
    # (often emptying outright -> vanilla), and under all-SOTE it collapses
    # to a single chr (c5240 Shadowpot) that the downstream nav gate then
    # rejects -> empty -> vanilla. Net effect (bug): every Banished Knight
    # (c3010), Elder Lion (c4270), and Troll (c4600) inside the castle
    # (m49_41/42/43) shipped vanilla — in BOTH modes, but always-vanilla in
    # all-SOTE — while the no-reward grunts beside them (c3000 Exile Soldier,
    # c3020 Large Exile Soldier, c4490 Living Jar Warrior) randomized fine.
    #
    # Fix: skip the gate when _field_roll_tier is a field-strength (grunt)
    # roll. A grunt-rolled slot has no reward expectation, so there is
    # nothing to preserve; this restores the field-roll's intended grunt-base
    # draw. miniboss / night_boss field-rolls and catalogued boss/arena slots
    # (_field_roll_tier is None) are UNCHANGED — there the reward-preserve
    # pool is healthy (miniboss+ chrs are tier-derived has_reward=True) so it
    # never spuriously collapses, and genuine boss rewards stay protected.
    _reward_decoupled = (_field_roll_tier is not None
                         and _field_roll_tier not in V3_BOSS_STRENGTH_TIERS)
    if (tags.get(recipient_cp, {}).get('has_reward') is True
            and not _reward_decoupled):
        reward_preserve_pool = {cp for cp in pool
                                if tags.get(cp, {}).get('has_reward') is True}
        if not reward_preserve_pool:
            return None
        pool = reward_preserve_pool

    # v0.20.8: Arena-only target restriction. Some XXL grounded enemies
    # (Divine Beast Dancing Lion etc.) only function at flat boss-arena
    # slots. Variant marker presence (recipient_is_boss=True) is the
    # arena signal — flat-by-design slots all carry boss markers.
    if not recipient_is_boss:
        pool = pool - _arena_only

    # v0.23.72-late+: SECOND ARENA_ONLY gate — slot-marker-based.
    # The first gate (line ~7759) uses recipient_is_boss, which is the
    # SOURCE c-prefix's tier classification (via is_boss_tier_prefix
    # fallback). That gate catches obvious cases but has false positives:
    # when the source c-prefix appears in some boss-tier variants elsewhere
    # in the game (e.g. c4170 Lordsworn has both grunt 'Lordsworn' and
    # 'Lordsworn Captain Fort' variants), recipient_is_boss can be True
    # even at a non-arena slot. That left 3+ documented leaks in v0.20.78
    # (c4580 Large Wormface at Lordsworn Captain Fort m30_00 pi=17,
    # Banished Knight m49_10 pi=3, Highwayman m60_42_37_10 pi=33).
    #
    # This second gate reads the DESTINATION slot's variant name directly
    # and requires it to carry a V3_BOSS_NAME_MARKERS token. Strictly
    # tighter than the source-side gate above. The two layer: gate-1
    # catches the cheap cases without needing variant-name lookup;
    # gate-2 catches the source-classification false-positives.
    #
    # Marker set is the broad one (includes 'Field Boss', 'Castle Boss',
    # 'Encampment', 'Evergaol', 'Boss' bare, etc.). Chrs needing tighter
    # geometric restrictions escalate to V3_NIGHT_BOSS_ONLY_TARGETS or
    # V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS, which apply below.
    #
    # chaos_mode-overrideable to match NIGHT_BOSS_ONLY's chaos behavior:
    # in chaos mode, ARENA_ONLY chrs can leak to field-tier slots for
    # variety. Pure-geometric concerns escalate to NIGHT_BOSS_STRICT.
    #
    # v0.25.7: catalog-derived `arena` field augments the name-marker
    # check. The two paths are OR'd: either the slot variant name
    # carries a V3_BOSS_NAME_MARKERS token (the existing path, captures
    # named arena slots like "Lordsworn Captain Fort"), OR the slot's
    # catalog entry has `arena: True` (derived at module load from the
    # vanilla chr's expects_boss_arena / size_class — captures arena
    # slots whose variant names don't happen to carry marker tokens).
    # Strictly broadens the arena recognition set; never narrows.
    # v0.27.29: catalogued-spawn-pool-boss signal. The Day-2 rotation
    # MSBs (V3_SPAWN_POOL_MSBS pi=1) ferry a boss into a live arena at
    # runtime. The FIELD-twin tiles are named "... (Field Boss)" and so
    # match the markers below; the CASTLE-variant tiles (m46_86/87/88/90/
    # 91/95) use POI-interior names — "(Castle Basement)", "(Castle)" —
    # that only the EXTENDED marker set recognizes, and their catalog
    # `arena` flag is False. Result (bug, found via seed 670313): the
    # marker checks read these as non-arena / non-NB, the _arena_only and
    # NIGHT_BOSS_ONLY subtractions fire, and in all-SOTE mode the small
    # boss-tier SOTE pool empties → pick returns None → the castle boss
    # ships vanilla (user fought a vanilla Bell Bearing Hunter in the
    # Castle Basement). The slot was ALREADY promoted to recipient_is_boss
    # by the v0.24.98 catalog-membership override in shuffle_msb_v3; this
    # makes the arena / night-boss classification here consistent with
    # that promotion. Catalog membership at ANY scope qualifies — same
    # rule as the recipient_is_boss override — so the broad-vs-extended
    # scope split that hides these from the OOPS_ALL_NB picker doesn't
    # also strip their target pool. Narrow: only fires for the enumerated
    # V3_SPAWN_POOL_MSBS pi=1 slots, so it cannot loosen gating elsewhere.
    # v0.27.32: CONSOLIDATED catalogued-boss-arena signal. Replaces three
    # ad-hoc fixes of identical shape — v0.27.29 (_is_catalogued_spawn_pool_
    # boss: castle rotation tiles), v0.27.31 (_is_catalogued_named_boss:
    # evergaols) — plus the latent gaps they didn't reach (cathedral,
    # fort_suffix, mountaintop, boss_suffix, crater, noklateo,
    # castle_interior non-rotation tiles).
    #
    # Root pattern: a slot can be a genuine, scripted boss arena (catalogued
    # in V3_BOSS_SLOT_CATALOG, and already promoted to recipient_is_boss by
    # the v0.24.98 catalog-membership override in shuffle_msb_v3) yet have a
    # variant name whose tokens DON'T match V3_NIGHT_BOSS_NAME_MARKERS (which
    # deliberately excludes 'Evergaol'/'Encampment'/bare 'Boss'/POI-interior
    # names like '(Castle)'). The arena/NB classification here then diverges
    # from the recipient_is_boss promotion: the _arena_only / NIGHT_BOSS_ONLY
    # subtractions fire and, at nav-constrained slots in all-SOTE, strip the
    # only targets that survive the slot's nav gate → empty pool → the boss
    # ships vanilla. Confirmed three times in the field (seed 670313 Castle
    # BBH, seed 230261 Castle Red Wolf + evergaol Banished Knights).
    #
    # Fix: trust the catalog tier over the name markers for the set of tiers
    # that are GENUINELY sealed/scripted boss arenas (below), promoting both
    # _slot_is_arena and _slot_is_night_boss. This makes classification
    # consistent with the recipient_is_boss override across the whole boss-
    # arena tier family at once, instead of patching one slot-shape per
    # release.
    #
    # EXCLUDED tiers (kept on strict marker-based gating, NOT promoted):
    #   - terrain     (147 non-boss terrain anchors)
    #   - encampment  (7 field camp groups — Elder Lion / Mad Pumpkin camps;
    #                  field encounters, not sealed arenas)
    #   - remembrance (100 scholar/remembrance trash — Wandering Noble,
    #                  Cuckoo Knight, etc.; classify correctly via markers
    #                  already, and must NOT admit NB-only chrs)
    # Including the already-marker-correct boss tiers (nightboss / fieldboss
    # / ruins_boss / fort_boss) is a no-op (True OR True); the only NEW
    # promotions are the marker-missing tiers. Narrow: catalog membership at
    # a boss-arena tier only — cannot loosen gating at field/grunt/terrain
    # slots, which are absent from the catalog or in the excluded tiers.
    #
    # v0.28.x+: _slot_catalog_tier and _is_catalogued_boss_arena are now
    # hoisted to the cap-block gate above; this block originally computed
    # them locally. Kept as in-place comments instead of re-assigning to
    # avoid duplicating the dict lookup. _is_nightboss_slot (same hoist)
    # is used by the new NB-tier filter and cap-exemption gates.
    _slot_is_arena = bool(slot_variant_name) and any(
        m in slot_variant_name for m in V3_BOSS_NAME_MARKERS)
    if not _slot_is_arena and slot_msb_name is not None and slot_pi is not None:
        _slot_is_arena = V3_BOSS_SLOT_CATALOG.get(
            (slot_msb_name, slot_pi), {}).get('arena', False)
    if not _slot_is_arena and _is_catalogued_boss_arena:
        _slot_is_arena = True
    if not _slot_is_arena and not chaos_mode:
        pool = pool - _arena_only

    # v0.20.81: NIGHT_BOSS_ONLY restriction — strict subset of ARENA_ONLY.
    # Computed from slot_variant_name rather than recipient_is_boss
    # because V3_NIGHT_BOSS_NAME_MARKERS is a tighter marker set
    # (excludes 'Encampment'/'Evergaol'/bare 'Boss' to avoid compact
    # sub-arenas). See V3_NIGHT_BOSS_ONLY_TARGETS comment block for
    # the rationale.
    #
    # v0.23.11 chaos_mode: when chaos_mode=True, this subtraction is LIFTED
    # at non-NB slots — true Night Boss chrs (Margit, Maliketh, Astel, etc.)
    # become eligible to land at field-boss / overworld slots. Combined
    # with the tightened NB-slot intersection below, this creates a one-way
    # flow: NB chrs leak DOWN to field slots, but field bosses (Trolls,
    # Runebears) cannot leak UP to NB anchor slots — preserving the
    # climactic NB-arena moments while opening the rest of the world to
    # boss-tier surprises.
    _slot_is_night_boss = bool(slot_variant_name) and any(
        m in slot_variant_name for m in V3_NIGHT_BOSS_NAME_MARKERS)
    if not _slot_is_night_boss and _is_catalogued_boss_arena:
        # v0.27.32: consolidated boss-arena promotion. See the
        # _is_catalogued_boss_arena block above. A catalogued boss-arena
        # slot is a real scripted arena; keep night-boss-tier targets (incl.
        # the SOTE night_boss roster) eligible there so the NIGHT_BOSS_ONLY
        # subtraction can't empty the pool at nav-constrained arenas.
        # Subsumes the v0.27.29 (spawn-pool castle) and v0.27.31 (evergaol)
        # promotions and closes the cathedral / fort_suffix / mountaintop /
        # boss_suffix / crater / noklateo gaps that shared the same shape.
        _slot_is_night_boss = True
    if not _slot_is_night_boss and not chaos_mode:
        pool = pool - V3_NIGHT_BOSS_ONLY_TARGETS

    # v0.20.83: NIGHT_OR_FIELD_BOSS_ONLY tier — tightest gate. Only
    # 'Night Boss' / 'Field Boss' marker slots accept these chrs.
    # Excludes Castle/Fort/Ruins-interior + (Crater)/(Noklateo) +
    # Remembrance, which NIGHT_BOSS_ONLY allows.
    _slot_is_night_or_field_boss = bool(slot_variant_name) and any(
        m in slot_variant_name for m in V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS)
    if not _slot_is_night_or_field_boss:
        pool = pool - V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS

    # NB-strict, NB-caliber, and source-anim gates all now go through
    # the consolidated _reject_target_for_slot predicate below. See
    # v0.24.27 comment.

    # v0.24.27: mirror-semantic gates consolidated. The three gates
    # below (NB-strict from v0.23.11, source-anim from v0.24.18, and
    # NB-caliber from v0.23.07) all enforce a constraint that the
    # reservation pre-pass must mirror at score-time (because the
    # reservation early-return at line ~8395 bypasses runtime
    # enforcement). They're now consolidated via _reject_target_for_
    # slot — both this picker site AND _score_slot_for_unique
    # delegate to the same predicate, so future gate additions can't
    # accidentally bypass at reservation time.
    #
    # Implementation detail: NB-caliber has empty-pool fallback
    # semantics (if the caliber intersection empties the pool, keep
    # the pre-caliber pool — better to place SOMETHING than nothing).
    # NB-strict and source-anim are absolute (no fallback). The
    # predicate returns the reason string, so we partition rejections
    # into "absolute" (always applied) and "caliber" (applied only if
    # non-empty).
    _absolute_rejected = set()
    _caliber_rejected = set()
    for _t in pool:
        _r = reject_target_for_slot(ns, _t, recipient_cp, slot_variant_name,
                                      tags, chaos_mode=chaos_mode,
                                      msb_base=slot_msb_name, pi=slot_pi,
                                      slot_pos=slot_pos, run_ctx=run_ctx)
        if _r is None:
            continue
        if _r == 'nb_caliber':
            _caliber_rejected.add(_t)
        else:
            _absolute_rejected.add(_t)
    # Apply absolute rejections unconditionally — NB-strict and
    # source-anim leak that drained the pool means the slot stays
    # vanilla, which is the desired outcome.
    pool = pool - _absolute_rejected
    # Apply caliber rejection only if non-empty — preserves the
    # original "intersect-or-keep" semantics.
    _caliber_filtered = pool - _caliber_rejected
    if _caliber_filtered:
        pool = _caliber_filtered

    # v0.23.09: NB-arena exclude set — subtract chrs that break specifically
    # at NB anchor slots (scripted-intro fails, chr stands idle). Doesn't
    # affect their availability at field slots.
    if _slot_is_night_boss and V3_NIGHT_BOSS_EXCLUDE_TARGETS:
        pool = pool - V3_NIGHT_BOSS_EXCLUDE_TARGETS

    # v0.23.05.2: compat at scripted-intro boss slots.
    # Margit-style softlock fix. Slots whose vanilla chr has
    # expects_boss_arena=True OR carries a Night Boss name marker run
    # scripted spawn cinematics that hardcode the source chr's family
    # — Margit's intro is a humanoid teleport-and-land, Crucible Knight's
    # is a humanoid sword-plant, Dragonkin's is a quadruped roar, etc.
    # Substituting a chr with an incompatible family (e.g., quadruped
    # Demi-Human Queen at humanoid Margit slot) means the cinematic plays
    # an animation the substitute doesn't have, the cinematic stalls
    # waiting for a "complete" signal that never fires, boss UI locks,
    # fight can't start → softlock.
    #
    # Confirmed in seeds 887995 + 974234: m48_40 pi=0 c2130 Margit Night
    # Boss → c4130 Demi-Human Queen (humanoid → quadruped). Same swap
    # both seeds, same softlock both seeds.
    #
    # v0.20.0 retired pool-level family pre-filtering, accepting the
    # broader cross-class swaps for variety. This fix is targeted: only
    # scripted-intro slots get the strict compat filter; grunt slots
    # and field encounters keep the loose v0.20.0 behavior. Variety cost
    # is contained to ~50-100 boss arena slots.
    #
    # Untagged candidates (no family) bypass — preserves the cluster-
    # member placements (c4181 Maris Jellyfish, c5110 Tendril, c3610
    # Oracle Envoy) that legitimately work via cluster-shape matching.
    # v0.24.100: scripted-intro anim_class compat filter REMOVED. The
    # previous block (v0.23.05.2) narrowed `pool` to candidates whose
    # family was compatible with the recipient's via _compat_rig.
    # Function is gone; the flier-vs-ground split that mattered is now
    # enforced upstream by is_compatible / the flier-required slot gate.
    _slot_is_arena = tags.get(recipient_cp, {}).get('expects_boss_arena', False)
    _is_scripted_intro = _slot_is_arena or _slot_is_night_boss

    chosen_pool = list(pool)

    # v0.20.34: SENSITIVE-only slots — softer than full fragile. Subtracts
    # V3_FRAGILE_SENSITIVE_TARGETS without restricting to RESILIENT.
    # See V3_SENSITIVE_ONLY_SLOTS docstring for design rationale.
    # Mutually exclusive with V3_PROBLEM_SLOTS in practice — full fragile
    # supersedes if a slot is somehow in both, since RESILIENT excludes
    # everything in SENSITIVE anyway.
    if (slot_msb_name is not None and slot_pi is not None
            and (slot_msb_name, slot_pi) in V3_SENSITIVE_ONLY_SLOTS
            and V3_FRAGILE_SENSITIVE_TARGETS):
        chosen_pool = [cp for cp in chosen_pool
                       if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
        if not chosen_pool:
            return None

    # v0.20.64: soft off-mesh slot check. Off-mesh slots are no longer
    # classified as fragile (T2.6 retired in is_fragile_slot), but they
    # still pose a CTD risk for SENSITIVE c-prefixes whose AI specifically
    # breaks at non-vanilla terrain. At slots that are off-mesh but NOT
    # otherwise fragile, just exclude SENSITIVE — don't restrict to SAFE,
    # don't prefer floaters. This keeps full enemy variety at most off-
    # mesh slots while still preventing the known-CTD interactions.
    if (slot_msb_name is not None
            and not is_fragile_slot(slot_msb_name, slot_pi, slot_variant_name,
                                     slot_pos=slot_pos)):
        off_mesh_set = _load_off_mesh_slots()
        if (slot_msb_name, slot_pi) in off_mesh_set:
            if V3_FRAGILE_SENSITIVE_TARGETS:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
                if not chosen_pool:
                    return None

    if slot_msb_name is not None and is_fragile_slot(
            slot_msb_name, slot_pi, slot_variant_name, slot_pos=slot_pos):
        if disable_resilient_filter and diagnostic_test_targets is not None:
            # v0.20.42: explicit batch-test mode. User has named the
            # exact c-prefixes they want to test at fragile slots, so
            # bypass ALL the inclusion/exclusion machinery (RESILIENT,
            # SAFE_CONFIRMED, SENSITIVE) and trust the explicit set.
            # Use case: batching CTD attribution — restrict each run
            # to a small set so CTDs are unambiguously tied to one of
            # those c-prefixes. Or retesting a SENSITIVE entry under
            # different conditions (tunnel-wakeup hypothesis, etc.).
            chosen_pool = [cp for cp in chosen_pool
                           if cp in diagnostic_test_targets]
            if not chosen_pool:
                return None
        elif disable_resilient_filter:
            # v0.20.35: diagnostic mode. v0.20.37: untested-only filter.
            # v0.20.40: also exclude V3_FRAGILE_SAFE_CONFIRMED — those
            # are already-tested-and-safe; re-testing them yields no new
            # info. v0.27.0: SAFE_CONFIRMED was retired as the *fragile
            # gate* (production now uses the SENSITIVE blacklist only),
            # but it is preserved as a data set precisely for this
            # diagnostic path — it is still the "known-tested" record,
            # so subtracting it here still yields the untested pool:
            #   pool - SAFE_CONFIRMED - SENSITIVE = not-yet-tested
            # This is the SENSITIVE-retest workflow's entry point: as
            # chrs are confirmed safe at fragile slots, ADD them to
            # SAFE_CONFIRMED to take them out of the diagnostic pool.
            # If empty, the slot stays vanilla (return None).
            resilient_set = V3_RESILIENT_BIPEDS
            chosen_pool = [cp for cp in chosen_pool
                           if cp not in resilient_set
                           and cp not in V3_FRAGILE_SAFE_CONFIRMED]
            if not chosen_pool:
                return None
            # Apply SENSITIVE blacklist below (untested-only path).
            if V3_FRAGILE_SENSITIVE_TARGETS:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
                if not chosen_pool:
                    return None
        else:
            # v0.20.48: at off-mesh slots in production mode, PREFER
            # floater-class c-prefixes (jellyfish family) — they don't
            # need navmesh, so they work where ground-pathing AI fails.
            # Fall through to standard fragile filter if no compat
            # overlap with floaters.
            # v0.20.40 / v0.24.86-patch7: production fragile-slot filter
            # uses RESILIENT ∪ SAFE_CONFIRMED. Each diagnostic confirmation
            # immediately expands fragile-slot variety in production runs.
            # (Patch7 collapsed the dead v0.20.48 floater-preference if-else
            # branch — V3_OFF_MESH_PREFERRED_TARGETS was empty since v0.20.68
            # and the if-arm never executed. Same filter logic, less code.)
            # v0.27.0: WHITELIST -> BLACKLIST flip. The production
            # fragile-slot filter used to be inclusion-only: a c-prefix
            # had to be in V3_FRAGILE_SAFE_CONFIRMED (a 157-entry hand-
            # curated playtest whitelist) to land at a fragile slot.
            # That whitelist was archived -- it had two fatal problems:
            # it rotted (every new chr / pack needed manual extension,
            # and all 41 MMV chrs were silently locked out of fragile
            # slots, which is what surfaced this), and it conflated
            # three distinct freeze classes under one flag. See the
            # three-freeze-class note at V3_FRAGILE_SENSITIVE_TARGETS.
            #
            # New rule: at a fragile slot, EVERY c-prefix is allowed
            # EXCEPT the V3_FRAGILE_SENSITIVE_TARGETS blacklist (the
            # locomotion/geometry-mismatch chrs a fragile slot genuinely
            # can't host) and the per-slot EXTRA_BANS below. The
            # SENSITIVE subtraction that follows is now the load-bearing
            # guard, not a redundant defensive pass.
            allowed_set = None  # None = "all allowed"; blacklist does the work
            _extra_allows = V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
                (slot_msb_name, slot_pi))
            # EXTRA_ALLOWS is now a no-op for inclusion (everything is
            # already allowed) but harmless; left wired in case a future
            # change reintroduces a per-slot inclusion gate.
            _ = _extra_allows
            # No inclusion filter — chosen_pool passes through. SENSITIVE
            # blacklist + EXTRA_BANS below are the only fragile-slot cuts.
            if V3_FRAGILE_SENSITIVE_TARGETS:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
                if not chosen_pool:
                    return None
            # v0.23.62: per-slot extra c-prefix bans. See
            # V3_PROBLEM_SLOT_EXTRA_BANS docstring. Targets specific
            # SAFE-classified c-prefixes that nonetheless break at
            # particular fragile slots (e.g., large_boss_ground GIGA
            # at Cathedral Guardian Golem source — anim-bank-mismatch
            # freezes despite passing the SAFE filter).
            extra_bans = V3_PROBLEM_SLOT_EXTRA_BANS.get(
                (slot_msb_name, slot_pi))
            if extra_bans:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in extra_bans]
                if not chosen_pool:
                    return None

    if target_count is not None:
        # Global per-cprefix placement cap. v0.24.86-patch7 collapsed
        # the v0.20.65 per-cprefix dispatch — the tighter 25-cap was
        # paired with V3_OFF_MESH_PREFERRED_TARGETS (retired); with
        # floater-preference gone, all c-prefixes share the global cap.
        capped_pool = [cp for cp in chosen_pool
                       if target_count.get(cp, 0) < V3_TARGET_PLACEMENT_CAP]
        if capped_pool:
            chosen_pool = capped_pool

    if not chosen_pool:
        return None

    # v0.28: per-slot hashed pick. Keying the choice on (seed, msb, pi)
    # over a sorted pool makes the cp decision a pure function of slot
    # identity — order-independent, so a contaminated/reordered input no
    # longer cascades, and simulate_engine.py matches the engine. Uniform
    # over the same pool as before; only the per-slot selection is now
    # deterministic. Falls back to the shared rng for callers that don't
    # supply slot identity (slot_msb_name/slot_pi).
    if slot_msb_name is not None and slot_pi is not None:
        _picker = _slot_decision_rng(slot_msb_name, slot_pi).choice
    else:
        _picker = rng.choice  # sorting happens inside _choose_with_budget
    # v0.28 hybrid budget/recycle. No run_ctx or an unset (0) budget => an
    # empty resident set and an unbounded budget, which reduces this to the
    # plain hashed pick over sorted(chosen_pool) — identical to pre-v0.28.
    #
    # v0.28.x Phase 2 (POI recycling): route through active_* helpers so
    # when shuffle_msb_v3 has armed a cluster scope via run_ctx.begin_poi()
    # the picker reads the per-cluster resident set and budget instead of
    # the per-MSB ones. Picker code path unchanged — only the scope of
    # "resident" changes. Falls back to the direct attr read for
    # RunContext snapshots that predate the helpers.
    if run_ctx is None:
        _resident, _budget = set(), 1 << 30
    elif hasattr(run_ctx, 'active_resident_cps'):
        _resident = run_ctx.active_resident_cps() or set()
        _budget = run_ctx.active_distinct_budget() or (1 << 30)
    else:
        _resident = getattr(run_ctx, 'msb_resident_cps', None) or set()
        _budget = getattr(run_ctx, 'msb_distinct_budget', 0) or (1 << 30)
    result, _kind = _choose_with_budget(chosen_pool, _resident, _budget, _picker)
    if result is None:
        return None
    # v0.23.07: bump unique-cap counter for organic picks. Reserved picks
    # already pre-bumped during the reservation pre-pass; this catches
    # picks that landed on a capped cp via normal pool selection.
    #
    # v0.28.x+: NB-slot placements are exempt from the cap. Skipping the
    # bump here pairs with the cap-block-skip at the top of this function
    # (see the hoisted _is_nightboss_slot block) so that NB placements
    # neither shrink the pool for later non-NB slots nor get blocked when
    # the cp's non-NB count is already at cap. Climactic encounters are
    # rare in actual play (one per seed at most), and the spoiler
    # analysis showed cap exhaustion was actively starving the NB pool
    # at indoor-tunnel slots (m47/m48 DS-heritage cluster) — the chrs
    # with cap room left at run-time were mostly oversized/flying NB
    # bosses that couldn't fit the slot terrain, so the slot fell to
    # miniboss. Exempting NB-slot placements keeps eligible NB chrs in
    # the pool for the duration of the seed.
    if result in V3_UNIQUE_TARGET_CAPS and not _is_nightboss_slot:
        _placed_counts[result] = _placed_counts.get(result, 0) + 1
    return result



# ---------------------------------------------------------------------------
# Variant-selection wrapper above pick_target_cp
# ---------------------------------------------------------------------------
#
# v0.28.x: folded in from oops_v3.pick_target. Thin wrapper —
# pick_target_cp picks the c-prefix, then pick_variant_for_tier
# (still in oops_v3) picks a concrete variant of that c-prefix.
# Inside this module pick_target_cp is a direct local call, so the
# shuffler's hot path no longer routes through oops_v3 to reach it.
# pick_variant_for_tier remains in oops_v3 (246 lines, deferred);
# pull it from ns.

def pick_target(ns, recipient_cp, tags,
                prefix_variants, prefix_count, recipient_is_boss, rng,
                target_count=None,
                slot_y=None,
                slot_msb_name=None, slot_pi=None, slot_variant_name=None,
                slot_pos=None,
                slot_eid=None,
                slot_require_boss_reward=False,
                disable_resilient_filter=False,
                non_fragile_baseline_cp=None,
                diagnostic_test_targets=None,
                chaos_mode=False,
                gates=None,
                run_ctx=None):
    """Pick a swap target c-prefix and a variant, matching tier.

    v0.23.72-late: bank_to_prefixes / loose_to_prefixes / mode dropped from
    signature (see pick_target_cp docstring).

    v0.24.21: `gates` parameter — threads through to pick_target_cp.
    See engine/state.py.

    v0.24.21 (Phase 5): `run_ctx` parameter — threads runtime
    bookkeeping (unique counters / reservations) through. See
    engine/runctx.py."""
    # pick_target_cp is a sibling function in this module — call
    # directly with ns to short-circuit the shim hop.
    target_cp = pick_target_cp(
        ns,
        recipient_cp, tags,
        prefix_variants, prefix_count, recipient_is_boss, rng,
        target_count=target_count, slot_y=slot_y,
        slot_msb_name=slot_msb_name, slot_pi=slot_pi,
        slot_variant_name=slot_variant_name,
        slot_pos=slot_pos,
        slot_eid=slot_eid,
        slot_require_boss_reward=slot_require_boss_reward,
        disable_resilient_filter=disable_resilient_filter,
        non_fragile_baseline_cp=non_fragile_baseline_cp,
        diagnostic_test_targets=diagnostic_test_targets,
        chaos_mode=chaos_mode,
        gates=gates,
        run_ctx=run_ctx)
    if target_cp is None:
        return None, None
    # v0.27.13: if this slot was reserved for a specific variant group
    # (group-floor pass in _compute_unique_reservations), read that
    # group back out of the reservation dict and pin the variant pick
    # to it. The reservation value is a (cp, group) tuple for grouped
    # reservations, a bare cp string otherwise. run_ctx.unique_reservations
    # is the same dict pick_target_cp's early-return consults.
    _pinned_group = None
    if (run_ctx is not None and slot_msb_name is not None
            and slot_pi is not None):
        _rv = run_ctx.unique_reservations.get((slot_msb_name, slot_pi))
        if isinstance(_rv, tuple) and _rv[0] == target_cp:
            _pinned_group = _rv[1]
    pick_variant_for_tier = ns['pick_variant_for_tier']
    target_variant = pick_variant_for_tier(target_cp, recipient_is_boss,
                                            prefix_variants, rng, tags=tags,
                                            run_ctx=run_ctx,
                                            pinned_group=_pinned_group)
    if target_variant is None:
        # v0.23.04.1: All variants for this c-prefix were filtered out
        # (e.g., empty-name phantom-only variants). Return (None, None)
        # so the caller's existing target_cp-None guard preserves the
        # slot vanilla. Better than crashing in swap_plan.append, and
        # better than silently picking an invalid variant.
        return None, None
    return target_cp, target_variant
