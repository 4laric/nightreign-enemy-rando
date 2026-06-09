"""Mirror-semantic gate predicate (extracted from oops_v3.py).

WHAT THIS IS
------------
The function `reject_target_for_slot` decides whether a (source slot,
target c-prefix) pair is rejected by any of the mirror-semantic gates
that both pick_target_cp (runtime) and _score_slot_for_unique
(reservation pre-pass) must agree on. The history of this predicate
and the rationale for consolidating these gates is preserved verbatim
in the function docstring below.

WHY IT WAS EXTRACTED
--------------------
529 lines in the host module. Extracting it shrinks oops_v3.py
without changing behavior, and lets the rejection logic be unit-
tested with a synthetic `ns` namespace independent of the rest of
the engine.

The function takes its module namespace (`ns`) as the first argument
— typically `globals()` from the calling module. This avoids both:
  - circular imports (engine.rejection doesn't import oops_v3 at
    module-load time; tests can pass a duck-typed namespace dict)
  - the sys.modules[__name__] failure mode under
    importlib.util.spec_from_file_location loads (dev/simulate_engine.py
    loads oops_v3 as 'o' but doesn't register it in sys.modules).

The body's first ~30 lines bind frequently-used names from `ns` into
locals (V3_NIGHT_BOSS_CALIBER_TARGETS, _effective_size_class, etc.)
so the rest of the function reads identically to the pre-extraction
source, with the speed bonus of LOAD_FAST opcodes over LOAD_GLOBAL.
"""
from __future__ import annotations


def reject_target_for_slot(ns, target_cp, src_cp, src_variant_name, tags,
                            *, chaos_mode=False, msb_base=None, pi=None,
                            slot_pos=None, run_ctx=None):
    """Shared predicate for "mirror-semantic" gates — those that
    pick_target_cp enforces at runtime AND that _score_slot_for_unique
    must replicate at reservation time. The reservation early-return
    in pick_target_cp (line ~8395, returns the reserved cp before any
    gate runs) bypasses runtime enforcement; without the mirror, the
    pre-pass commits placements that the runtime would have rejected.

    v0.24.27 introduced this predicate after the same bug-shape
    recurred three times:
      - v0.23.07: NB-caliber gate added → reservations bypassed it
      - v0.23.11: NB-strict gate added → reservations bypassed it
      - v0.24.24: V3_FORBIDDEN_BY_SOURCE_ANIM added → reservations
                  bypassed it (fixed in v0.24.26)
    Each fix mirrored the new gate into _score_slot_for_unique by hand.
    Easy to forget. By consolidating mirror-semantic gates into this
    predicate, both call sites get the gate for free, and future
    additions live in one place.

    Args:
        target_cp: candidate target c-prefix
        src_cp: vanilla c-prefix at this slot (= recipient_cp in the
            picker; = slot_info['source_cp'] in the scorer)
        src_variant_name: vanilla variant name at this slot (= slot_
            variant_name in the picker; = slot_info['source_variant_
            name'] in the scorer). May be '' or None.
        tags: tag database
        chaos_mode: NB-caliber gate tightens to NIGHT_BOSS_ONLY_TARGETS
            in chaos mode (caliber → strict subset). NB-strict and
            source-anim gates are geometric and don't honor chaos.
            Default False — the reservation path doesn't see
            chaos_mode (it's per-MSB), so the predicate is
            conservative by default. The runtime picker passes
            chaos_mode=True if the run is in chaos mode.
        msb_base: MSB filename (e.g. 'm45_01_00_00.msb'). Required
            for the quadruped-unsafe-slot gate (v0.24.31). If None,
            that gate is skipped — legacy callers that don't pass
            slot identity get pre-v0.24.31 behavior.
        pi: Part index integer. Required alongside msb_base for the
            quadruped-unsafe-slot gate.

    Returns:
        None  if (src, target) is allowed by all mirror-semantic gates.
        'nb_strict'             if rejected by NB-strict gate
        'nb_caliber'            if rejected by NB-caliber gate
        'forbidden_source_anim' if rejected by source-anim gate
        'quadruped_unsafe_slot' if rejected by quadruped-unsafe-slot gate
            (v0.24.31: target is loco=3 quadruped and (msb, pi) is in
            V3_QUADRUPED_UNSAFE_SLOTS catalog)
        'field_boss_at_strict_nb' if rejected by Gate 5.5 (v0.25.0-patch3:
            target is tier='field_boss' and slot is catalogued as
            tier='nightboss', scope='strict' — field-boss chrs lack
            the EMEVD wake-handshake integration strict NB arenas need)

    The caller distinguishes by reason because pick_target_cp's NB-
    caliber gate has empty-pool fallback semantics (caliber empties →
    caliber gate is dropped, original pool restored). NB-strict and
    source-anim are absolute (no fallback). The scorer doesn't care
    about reasons — any non-None means reject the reservation.

    NOT a complete picker gate set. Only the gates with mirror
    semantics are here. Picker-only gates (V3_ARENA_ONLY_TARGETS,
    V3_NIGHT_BOSS_ONLY_TARGETS, V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS,
    V3_NIGHT_BOSS_EXCLUDE_TARGETS, swap compat at scripted-
    intro slots) work on slot-side variant matching and don't need
    mirroring — the reservation pre-pass either won't pick a fragile
    target for those slots, or the rejected target will fail an
    earlier hard-rejection.
    """
    # Bind module-level dependencies into locals for clarity +
    # speed. The body below reads identically to the original
    # pre-extraction code (no ns[] noise); locals also use
    # LOAD_FAST opcodes instead of LOAD_GLOBAL.
    V3_BIG_PROXIMITY_ENABLED = ns['V3_BIG_PROXIMITY_ENABLED']
    # v0.32.x: when the hash tie-break post-pass owns proximity, the
    # forward (visit-order) gate is bypassed so the post-pass is
    # authoritative. .get keeps older synthetic ns dicts working.
    V3_BIG_PROXIMITY_HASH_TIEBREAK = ns.get(
        'V3_BIG_PROXIMITY_HASH_TIEBREAK', False)
    V3_BIG_PROXIMITY_RADIUS = ns['V3_BIG_PROXIMITY_RADIUS']
    V3_BIG_SIZE_CLASSES = ns['V3_BIG_SIZE_CLASSES']
    V3_BOSS_BAR_GATED_TIERS = ns['V3_BOSS_BAR_GATED_TIERS']
    V3_BOSS_BAR_TIERS = ns['V3_BOSS_BAR_TIERS']
    V3_BOSS_SLOT_CATALOG = ns['V3_BOSS_SLOT_CATALOG']
    V3_DEDICATED_ARENA_BOSS_CHRS = ns['V3_DEDICATED_ARENA_BOSS_CHRS']
    V3_DENSITY_CAP_ENABLED = ns['V3_DENSITY_CAP_ENABLED']
    V3_DENSITY_L_SIZE_CLASSES = ns['V3_DENSITY_L_SIZE_CLASSES']
    V3_ENTRANCE_ANIM_CLASS = ns['V3_ENTRANCE_ANIM_CLASS']
    V3_FRAGILE_SAFE_CONFIRMED = ns['V3_FRAGILE_SAFE_CONFIRMED']
    V3_GEOMETRY_GATED_SIZES = ns['V3_GEOMETRY_GATED_SIZES']
    V3_GEOMETRY_GATE_ENABLED = ns['V3_GEOMETRY_GATE_ENABLED']
    V3_INTRO_ANIM_REQUIRED_SLOTS = ns['V3_INTRO_ANIM_REQUIRED_SLOTS']
    V3_NAV_INDEPENDENT_TARGETS = ns['V3_NAV_INDEPENDENT_TARGETS']
    V3_NIGHT_BOSS_CALIBER_TARGETS = ns['V3_NIGHT_BOSS_CALIBER_TARGETS']
    V3_NIGHT_BOSS_NAME_MARKERS = ns['V3_NIGHT_BOSS_NAME_MARKERS']
    V3_NIGHT_BOSS_ONLY_TARGETS = ns['V3_NIGHT_BOSS_ONLY_TARGETS']
    V3_NO_EMERGE_SLOTS = ns['V3_NO_EMERGE_SLOTS']
    V3_QUADRUPED_UNSAFE_SLOTS = ns['V3_QUADRUPED_UNSAFE_SLOTS']
    V3_QUADRUPED_UNSAFE_SLOTS_META = ns['V3_QUADRUPED_UNSAFE_SLOTS_META']
    V3_SIZE_RANK = ns['V3_SIZE_RANK']
    V3_SLOPED_SIZE_UP_THRESHOLD = ns['V3_SLOPED_SIZE_UP_THRESHOLD']
    _effective_size_class = ns['_effective_size_class']
    _geometry_capacity_rank = ns['_geometry_capacity_rank']
    _get_slot_slope_deg = ns['_get_slot_slope_deg']
    _is_slot_elevated = ns['_is_slot_elevated']
    _is_slot_wedged = ns['_is_slot_wedged']
    _is_stub_nav_slot = ns['_is_stub_nav_slot']
    _load_slot_face_dist = ns['_load_slot_face_dist']
    # Gate 1 (REMOVED v0.26.x): NB-strict was a variant-name string filter
    # that required source slots to contain "Night Boss" in their variant
    # name. Originally introduced (v0.23.11) as a "strictest geometric
    # gate" to keep XXL/GIGA chrs out of Field Boss slots whose arena
    # geometry couldn't accommodate them. Removed in v0.26.x: it was
    # masquerading as geometric but actually doing string matching, and
    # the real geometric concerns are covered by V3_ARENA_ONLY_TARGETS
    # (chrs needing arena geometry like Wormface), V3_FRAGILE_SENSITIVE_
    # TARGETS (chrs with rig issues on rough terrain like Ancient Dragon),
    # and the size_class compat checks in scoring. Per user
    # direction: "I want night bosses at field boss slots, as long as
    # they can traverse." The string filter was too restrictive — it
    # blocked NB chrs from ~all source slots in Limveld because almost
    # no source slot's variant name contains literally "Night Boss".
    # Sim showed Midra/Romina/Fortissax/etc. unplaceable at 65-81%
    # purely due to this gate. V3_NIGHT_BOSS_STRICT_TARGETS is now an
    # empty set; the population sites have been removed. If a specific
    # CTD pattern resurfaces (e.g., c4510 wingspan at Miranda Blossom),
    # add a targeted V3_FORBIDDEN_BY_SOURCE_ANIM rule with seed evidence
    # rather than resurrecting the variant-name filter.


    # Gate 2: NB-caliber (v0.23.07). At slots whose source variant
    # carries an NB marker, the target must be in the caliber set —
    # otherwise we'd place a Banished Knight at a Night Boss anchor
    # slot via a stray "Boss" marker variant. Chaos-overrideable: in
    # chaos mode, the set tightens to V3_NIGHT_BOSS_ONLY_TARGETS
    # (strict subset), giving the asymmetric "field giants don't
    # leak UP to NB slots but NB chrs leak DOWN" flow.
    if src_variant_name and any(m in src_variant_name
                                 for m in V3_NIGHT_BOSS_NAME_MARKERS):
        caliber_set = (V3_NIGHT_BOSS_ONLY_TARGETS if chaos_mode
                       else V3_NIGHT_BOSS_CALIBER_TARGETS)
        if caliber_set and target_cp not in caliber_set:
            return 'nb_caliber'

    # v0.27.28: Gate 3 (source-anim forbidden) REMOVED. It read the source
    # chr's family against V3_FORBIDDEN_BY_SOURCE_ANIM, but that table
    # has been empty ({}) since v0.24.x, so the gate never fired — it was
    # pure dead weight reading the now-expunged anim_class field. The
    # historical purpose (keep flying_dragon targets out of grounded-intro
    # giga_boss slots) belonged to the flying-vs-ground machinery, also
    # removed this version.

    # Gate 4: Locomotion-fragile-unsafe slot (v0.24.31, extended v0.24.32).
    # When the candidate target has fragile locomotion (the fragile_locomotion
    # tag, or locomotion=3) AND the (msb, pi) is catalogued in
    # V3_QUADRUPED_UNSAFE_SLOTS, reject UNLESS the slot has a verified-safe
    # reposition proposal. This catches empirically-observed spawn freezes
    # where biped-on-mesh slots turn out to be quadruped-off-mesh at the
    # wider sample radius these chrs use. NOT chaos-overrideable
    # (geometric/engine constraint, not thematic). Skipped if msb_base or
    # pi is None (legacy caller without slot identity).
    #
    # v0.24.32 release path: when an entry's reposition_proposed block
    # has playtest_verified=true, the gate is released for that slot.
    # The slot has been moved to a denser-navmesh position (via
    # slot_repositions.json) and quadrupeds at the new location have
    # been confirmed to spawn correctly. Unverified repositions (the
    # default) keep the gate active — repositioned slot is still safe
    # for bipeds, but the fragile-locomotion chrs remain blocked pending
    # playtest.
    #
    # v0.27.28: this gate used to read anim_class (reject_anim_classes per
    # slot, and a default `family.startswith('quadruped')` check). With
    # anim_class expunged, the "fragile locomotion" property it was a proxy
    # for is now carried explicitly by the fragile_locomotion tag (set on
    # the 70 former quadruped/quadruped_large chrs) — which crucially covers
    # the loco-0/loco-5 quadrupeds (Bear c6031, Runebear, etc.) that a pure
    # locomotion==3 check misses. The default branch keeps the loco==3 half
    # because it independently covers 4 non-quadruped chrs (Godskin
    # Apostle/Noble c3560/c3570, Revenant Follower c4000, Living Jar Warrior
    # c4490) that freeze at the same slots. Per-slot override: an entry's
    # `reject_fragile_locomotion: true` (migrated from the old
    # reject_anim_classes=['quadruped']) rejects every fragile-loco target,
    # which is the same set the default branch catches — kept as an explicit
    # per-slot marker for the slots authored for humanoid bipedal AI (e.g.
    # m46_77 pi=8, the Demi-Human Queen anchor).
    if msb_base is not None and pi is not None and V3_QUADRUPED_UNSAFE_SLOTS:
        if (msb_base, pi) in V3_QUADRUPED_UNSAFE_SLOTS:
            entry = V3_QUADRUPED_UNSAFE_SLOTS_META.get((msb_base, pi), {})
            repo = entry.get('reposition_proposed') or {}
            if not repo.get('playtest_verified'):
                target_tag = tags.get(target_cp, {})
                target_fragile = target_tag.get('fragile_locomotion') is True
                target_loco = target_tag.get('locomotion')
                if target_fragile or target_loco == 3:
                    # Catches fragile_locomotion chrs (former quadruped /
                    # quadruped_large — Bears, Wolves, Goats, etc., across
                    # all locomotion values) AND loco=3 chrs (Rats and the
                    # handful of non-quadruped loco=3 bipeds). Both share
                    # the spawn-time pathfinding failure mode at these
                    # constrained-navmesh slots.
                    return 'quadruped_unsafe_slot'

    # v0.27.28: Gate 5 (flying-required slots) REMOVED. Per Alaric, the
    # flying-vs-ground constraint isn't real — dragons start grounded and a
    # grounded enemy at a former dragon slot is fine. The seed-552688
    # "Astel at a Flying Dragon slot → CTD" was a best-guess attribution
    # that was never confirmed. This was the last consumer of is_flier /
    # the V3_FLYING_REQUIRED_SLOTS catalog, both also removed.

    # v0.24.67 Gate 5.5: grunt/trash target at boss-healthbar slot.
    # Slots whose vanilla catalog tier indicates a boss-healthbar
    # encounter (named_boss, fieldboss, nightboss, encampment,
    # remembrance, castle_interior, noklateo, crater, fort_suffix,
    # boss_suffix, cathedral) run an EMEVD boss-clear chain on kill
    # that expects clean entity teardown. Grunt-tier and trash-tier
    # chrs are not authored for that contract: some have spawner-
    # generator fields in NpcParam that fire child entities on death
    # (c3664 Cemetery Shade variants 36640020/32/35), some dissipate
    # rather than leaving a corpse, some have unusual death anim
    # timing. The mismatch CTDs the boss-clear chain.
    #
    # Discovered seed 877217 v0.24.65: c3664 Cemetery Shade at m32_00
    # pi=31 ent=32000810 (Elder Lion Encampment slot). Player CTDed
    # on kill.
    #
    # V3_FRAGILE_SAFE_CONFIRMED is the exemption — grunts/trash with
    # playtest-confirmed normal death sequences are whitelisted there
    # and remain eligible. c3664 was removed from SAFE_CONFIRMED in
    # this release; its v0.20.52 "working" confirmation was at a non-
    # boss-bar slot type. See V3_BOSS_BAR_TIERS docstring for the
    # empirical derivation of the tier set.
    if msb_base is not None and pi is not None and V3_BOSS_SLOT_CATALOG:
        target_tier = tags.get(target_cp, {}).get('tier')
        if target_tier in V3_BOSS_BAR_GATED_TIERS:
            if target_cp not in V3_FRAGILE_SAFE_CONFIRMED:
                _cat = V3_BOSS_SLOT_CATALOG.get((msb_base, pi))
                if _cat and _cat.get('tier') in V3_BOSS_BAR_TIERS:
                    return 'grunt_trash_at_boss_bar'

    # v0.25.0-patch3 Gate 5.5: Field-boss-tier at strict-NB catalog slot.
    #
    # Catalog-aware tier-vs-scope enforcement. Gate 2 (nb_caliber, line
    # ~9378) uses src_variant_name string-matching to identify NB slots
    # and includes field_boss-tier chrs in V3_NIGHT_BOSS_CALIBER_TARGETS
    # for the broader "boss-quality at boss-marker slots" semantic. But
    # strict-scope NB arenas in V3_BOSS_SLOT_CATALOG (catalog scope=
    # 'strict' AND tier='nightboss') have wake-handshake EMEVD
    # integration — SetNetworkconnectedEventFlagID + per-arena boss-init
    # common_func sequence — that only proper night-boss-tier chrs
    # satisfy. Field-boss-tier chrs (Flying Dragon, Magma Wyrm, Guardian
    # Golem, Astel, Mohg, Erdtree Avatar, etc.) are open-world boss
    # encounters in ER vanilla; they expect a field-spawn flow, not a
    # strict-arena wake handshake. When one lands at a strict slot, the
    # boss never starts and the expedition Night fails-to-start.
    #
    # Empirical discovery: seed 628653 Tricephalos N2 fail-to-start.
    # The m48_40 (Morgott) strict-NB arena got swapped to c4500 Flying
    # Dragon (Field Boss). c4500.tier='field_boss', caliber=True,
    # strict=False — slipped through both the caliber gate (because
    # "Morgott (Night Boss)" matches an NB name marker, activating
    # caliber, which c4500 satisfies) and the strict gate (because
    # c4500 isn't in V3_NIGHT_BOSS_STRICT_TARGETS, so gate 1 doesn't
    # apply to it). Audit shows 26 of 59 caliber-pool chrs are
    # field_boss-tier — this gate prevents that whole class at strict
    # slots without restricting their placement at non-strict (broad/
    # extended) NB-arena slots where they remain valid candidates.
    #
    # The likely earlier N1/N2 failures (seed 650833 m48_40 → c7700
    # Gaping Dragon; seed 42 m49_18 → c5081 Chief Bloodfiend) match
    # the same shape — both are field_boss-tier in caliber. After
    # v0.25.0-patch2 catalogued m49_18 / m49_19 / m49_20 / m48_90 as
    # strict, this gate now covers those slots too.
    #
    # NOT chaos-overrideable (geometric / EMEVD-integration constraint,
    # not thematic). Catalog scope='strict' is a hard structural
    # property of the slot, independent of chaos mode.
    if msb_base is not None and pi is not None and V3_BOSS_SLOT_CATALOG:
        _cat = V3_BOSS_SLOT_CATALOG.get((msb_base, pi))
        if (_cat
                and _cat.get('tier') == 'nightboss'
                and _cat.get('scope') == 'strict'):
            if tags.get(target_cp, {}).get('tier') == 'field_boss':
                return 'field_boss_at_strict_nb'

    # v0.24.68 Gate 5.6: XXL/GIGA source slot integrity.
    # Discovered: seeds 756907 and 388677 both CTD when leaving
    # Stormveil Castle's southern face. Pattern: vanilla XXL/GIGA
    # boss slots in castle-area tiles (m60_4X_3Y) drift to targets
    # with mismatched family and/or much smaller size_class.
    # When the cell streams in on transit, the chr-file load fails
    # asset/nav validation against the slot's expectations and the
    # game CTDs.
    #
    # User decision (v0.24.68): "enough diversity now" — go broad.
    # At any slot where the vanilla source size_class is XXL or GIGA,
    # require the target to:
    #   (a) share the source's family, AND
    #   (b) be size L or larger (i.e., not XS/S/M)
    #
    # No event-bound discrimination needed — source size XXL/GIGA is
    # a reliable proxy for "dedicated boss-tier slot." Non-event XXL/
    # GIGA slots are rare and still expect boss-tier behavior on load,
    # so the gate is uniform.
    #
    # Trade-off: this loses some XXL→M and quadruped-GIGA→humanoid
    # diversity that was previously allowed. The earlier rationale
    # for permitting drift was diversity; with 130 L+ chrs in the
    # pool (45 L, 35 XL, 29 XXL, 21 GIGA) per-anim-class subsets
    # remain large enough for variety.
    src_tag = tags.get(src_cp, {})
    src_size = src_tag.get('size_class', '')
    if src_size in ('XXL', 'GIGA'):
        tgt_tag = tags.get(target_cp, {})
        tgt_size = tgt_tag.get('size_class', '')
        # v0.24.75: anim_class drift check REMOVED. Per user directive,
        # the rig-compat CTD theories of v0.24.18/v0.24.68 were
        # misattributing crashes that had other root causes (missing
        # chr assets, AI script issues). Keeping ONLY the size_drift
        # check — big sources still need big targets so body geometry
        # fits the slot. rig match no longer required.
        #
        # v0.26.x: M lifted from the drift list per user direction —
        # "Midra should be eligible for any slot that's occupied by
        # an L, XL, XXL, or GIGA mob. It's asymmetrically compatible."
        # The slot has the geometric capacity for an M-sized
        # occupant; the visual surprise of an M-humanoid at a GIGA-
        # source slot is a marquee-NB feature, not a bug. Floor-tier
        # protection for the big chrs that NEED these slots is
        # handled by V3_RESERVATION_FLOORS — those chrs get their
        # reserved slot before organic competition kicks in. Non-
        # NB-caliber M-humanoids (Wandering Noble etc.) are still
        # filtered by the NB-CALIBER gate at NB-marker slots, so
        # this widening doesn't open a grunt-flood at NB arenas.
        # XS/S retained on the drift list: those are grunt-scale
        # and would feel jarring at a giga/xxl visual.
        if tgt_size in ('XS', 'S'):
            return 'xxl_giga_size_drift'

    # v0.24.51 Gate 6: dedicated-arena boss off-arena.
    # v0.24.52: RELAXED based on playtest counter-evidence — see below.
    # v0.26.x: switched from _source='script_spawn' check to explicit
    # V3_DEDICATED_ARENA_BOSS_CHRS membership. The _source-based check
    # was made stale by the v0.26.x reclassification pass that flipped
    # the affected chrs to _source='nr_placed' after the byte-level
    # MSB audit confirmed they ARE in vanilla MSBs. The gate's INTENT
    # — protect against placement at overworld tiles that lack the
    # arena's EMEVD preload machinery — is unchanged, and the set of
    # chrs covered is identical to the previous behaviour.
    #
    # Script-spawn _source chrs (c4670, c4690, c7700, c7710, c7800,
    # c7820, c7900, c7910, c7920) need vanilla-NR EMEVD script-side
    # asset preloads (SmallBaseAttached and similar) to load their
    # asset bundles. Initial v0.24.51 hypothesis was that this preload
    # only happens at the 4 catalogued arena slots (m46_64/65/90/91 pi=1).
    #
    # User playtest of seed 714653 (v0.24.50) confirmed this is too
    # narrow: a script_spawn boss-tier chr placed at m46_05 (vanilla
    # c4660 Guardian Golem fort) was fought successfully. That MSB is a
    # dedicated NR boss arena MSB — vanilla content is also boss-tier —
    # and apparently the slot's existing EMEVD machinery preloads any
    # boss-tier replacement.
    #
    # Refined hypothesis (v0.24.52): m4x_xx dedicated arena MSBs have
    # boss-asset preload infrastructure (vanilla content is boss-tier
    # for these slots). m60_xx_xx overworld tiles do NOT — they're
    # open-world streaming tiles with no boss preload. Placing a
    # dedicated-arena boss chr at an overworld slot leaves the asset
    # bundle unloaded → CTD on cell-load when the player approaches.
    #
    # Gate behavior: reject dedicated-arena boss targets ONLY at
    # m60_xx_xx_xx overworld MSBs. Dedicated arena MSBs (m4x_xx) are
    # allowed — they have the EMEVD machinery.
    #
    # The 4 catalogued arena slots in V3_SCRIPT_SPAWN_BOSS_SLOTS remain
    # documented as the original NR script-spawn arena slots but are
    # no longer the exclusive allow-list. They're kept available for
    # future refinement if we discover specific m4x_xx slots that
    # DON'T work (would need another playtest data point).
    #
    # Grunt-tier supporting cast (c7711/c7712/c7810) are NOT gated —
    # they've worked everywhere observed.
    if msb_base is not None and pi is not None:
        if target_cp in V3_DEDICATED_ARENA_BOSS_CHRS:
            # Reject ONLY at overworld m60_xx_xx_xx tiles. Dedicated
            # arena MSBs (m4x_xx) are allowed.
            if msb_base.startswith('m60_'):
                return 'script_spawn_boss_at_overworld'

    # v0.27.4 Gate 7: geometry-aware size gate. Replaces the blunt
    # v0.24.55 'xxl_at_small_slot' gate and extends coverage to GIGA.
    #
    # A slot's size capacity is the LARGER of (a) the vanilla occupant's
    # size class — strict baseline, FromSoft placed that size here so it
    # is proven safe, with NO grace step (an XL-vanilla slot does not
    # auto-qualify for XXL) — and (b) the geometry-derived capacity from
    # slot_terrain.json `face_dist`. An XXL/GIGA target is rejected
    # unless its size class falls within that capacity.
    #
    # This supersedes the old "XXL at XS/S/M/L source -> always reject"
    # rule: XXL/GIGA are now allowed wherever the navmesh geometry
    # demonstrates the clearance (recovering legit big slots the blunt
    # gate discarded) and blocked everywhere it doesn't — including the
    # XL-vanilla slots the blunt gate let XXL through on unconditionally.
    # Slots with no terrain data fall back to the strict vanilla
    # baseline (no upsize without proof). Only XXL/GIGA are gated —
    # XS..XL clear essentially any navmesh slot. Geometric / not chaos-
    # overrideable. The gate never rejects a target whose size class is
    # <= the vanilla occupant's, so the candidate pool can never be
    # fully drained by it.
    if (V3_GEOMETRY_GATE_ENABLED and msb_base is not None
            and pi is not None):
        _tgt_size = (tags.get(target_cp, {}) or {}).get('size_class')
        if _tgt_size in V3_GEOMETRY_GATED_SIZES:
            _src_size = (tags.get(src_cp, {}) or {}).get('size_class')
            _cap_rank = V3_SIZE_RANK.get(_src_size, -1)  # strict baseline
            _fd = _load_slot_face_dist().get((msb_base, pi))
            if _fd is not None:
                _g_rank = _geometry_capacity_rank(_fd)
                if _g_rank > _cap_rank:
                    _cap_rank = _g_rank
            if V3_SIZE_RANK[_tgt_size] > _cap_rank:
                return 'geometry_clip'

    # Gate 7.5 (revised v0.24.86-patch6.1): slope-aware size-up at
    # boss-tier slots. Tighter conjunction than v0.24.86-patch6 — the
    # old form (tier+size-up only) broke test_night_boss_tier_unaffected,
    # which asserts XL Morgott at L Elder Lion Encampment is allowed
    # (geometrically fine, playtest-confirmed). Encampment is flat
    # (3° slope); the freeze case (c7100 Zamor at c3970 Ruins-Boss)
    # is on a 20.1° slope. Polygon data discriminates.
    #
    # Three filters, all must fire to reject:
    #   1. target.size_class > slot.src.size_class (size-up)
    #   2. slot.src.tier in BOSS_ARENA_TIERS or expects_boss_arena
    #   3. slot.slope_deg >= V3_SLOPED_SIZE_UP_THRESHOLD (15.0°)
    #
    # Missing polygon data: gate doesn't fire (better to allow than to
    # reject blind). v0.24.86-patch6.1 ships polygon-augmented
    # slot_terrain.json built via dev/augment_slot_terrain_with_polygons.py.
    _SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA']
    _BOSS_ARENA_TIERS = {
        'miniboss', 'field_boss', 'night_boss', 'nightlord', 'remembrance',
    }
    _src_tag = tags.get(src_cp, {})
    if (_src_tag.get('tier') in _BOSS_ARENA_TIERS
            or _src_tag.get('expects_boss_arena')):
        _src_sz = _src_tag.get('size_class', 'M')
        _tgt_sz = tags.get(target_cp, {}).get('size_class', 'M')
        try:
            _size_up = (_SIZE_ORDER.index(_tgt_sz)
                        > _SIZE_ORDER.index(_src_sz))
        except ValueError:
            _size_up = False
        if _size_up and msb_base is not None and pi is not None:
            _slope = _get_slot_slope_deg(msb_base, pi)
            if _slope is not None and _slope >= V3_SLOPED_SIZE_UP_THRESHOLD:
                return 'sloped_size_up'

    # Gate 7.6 (wedged-against-wall) / Gate 7.7 (elevated-rampart),
    # v0.24.86-patch8. Apply at ALL tiers (unlike slope, which is
    # boss-arena-only) but still only on size-up. May 13 v0.23.88
    # calibration. Both fall through silently on missing slot data.
    if msb_base is not None and pi is not None:
        _SIZE_ORDER_8 = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA']
        _src_sz = tags.get(src_cp, {}).get('size_class', 'M')
        _tgt_sz = tags.get(target_cp, {}).get('size_class', 'M')
        try:
            _is_up = (_SIZE_ORDER_8.index(_tgt_sz)
                      > _SIZE_ORDER_8.index(_src_sz))
        except ValueError:
            _is_up = False
        if _is_up:
            if _is_slot_wedged(msb_base, pi):
                return 'wedged_size_up'
            if _is_slot_elevated(msb_base, pi):
                return 'elevated_size_up'

    # Gate 7.8 (nav_dependent_at_stub_nav_slot), v0.24.86-patch9.
    # If slot is on a stub-nav tile (cave/dungeon family where the game
    # ships empty navmesh + empty onav), reject any target NOT in
    # V3_NAV_INDEPENDENT_TARGETS. Nav-dependent AI (rats, slugs,
    # wandering humanoids) hangs in pursuit-AI-stalled state when
    # navmesh queries return nothing.
    if (msb_base is not None
            and _is_stub_nav_slot(msb_base)
            and target_cp not in V3_NAV_INDEPENDENT_TARGETS):
        return 'nav_required_at_stub_nav_slot'

    # Gate 7: no_emerge_terrain (v0.24.79). Reject emerge-from-ground
    # chr intros at slots that lack the subsurface terrain their
    # animation requires (rampart roofs, elevated platforms, etc.).
    # Data-driven via V3_NO_EMERGE_SLOTS (arena affordance list) +
    # V3_ENTRANCE_ANIM_CLASS (per-chr taxonomy). Defense-in-depth
    # with the per-slot EXTRA_BANS pattern — both can fire for the
    # same case, with EXTRA_BANS being more specific (per-slot).
    if msb_base is not None and pi is not None:
        if (msb_base, pi) in V3_NO_EMERGE_SLOTS:
            anim = V3_ENTRANCE_ANIM_CLASS.get(target_cp)
            if anim == 'emerge_from_ground':
                return 'no_emerge_terrain'

    # Gate 8: requires_intro_anim (v0.26.11). Mirror image of Gate 7.
    # Some slots' EMEVD spawn setup hard-requires the occupant to have an
    # idle/entrance animation; chrs classified 'no_intro_anim' break there
    # while being resilient everywhere else. First slot: the m38_00
    # Guardian Golem "Cathedra" slot (pi=51), where Death Knight (c5070)
    # is the confirmed failure and emergers/risers play well. Data-driven
    # via V3_INTRO_ANIM_REQUIRED_SLOTS (slot list) + V3_ENTRANCE_ANIM_CLASS
    # (per-chr taxonomy). Negative gate — only the explicitly-classified
    # no_intro_anim chrs are rejected; 'unknown'-default chrs pass, so the
    # slot still randomizes widely. Composes with the slot's existing
    # V3_PROBLEM_SLOTS / EXTRA_ALLOWS gates (different root cause).
    if msb_base is not None and pi is not None:
        if (msb_base, pi) in V3_INTRO_ANIM_REQUIRED_SLOTS:
            anim = V3_ENTRANCE_ANIM_CLASS.get(target_cp)
            if anim == 'no_intro_anim':
                return 'requires_intro_anim'

    # v0.27.5 Gate 8 (big-enemy proximity) + Gate 9 (per-MSB density).
    # Placement-time replacement for the BIG_PROXIMITY (v0.21) and
    # DENSITY_CAP (v0.23.61) swap-plan post-passes. Both run off the
    # per-MSB size state carried on run_ctx and armed by begin_msb():
    #
    #   Gate 9 density — once the MSB's XL+ count hits xl_cap, XL+
    #       targets are rejected; once L+ count hits l_cap, L+ targets
    #       are rejected. Tunnel MSBs carry tighter caps.
    #   Gate 8 proximity — an XL+ target landing within
    #       V3_BIG_PROXIMITY_RADIUS of a big already placed in this MSB
    #       is rejected.
    #
    # A rejected big simply drops out of the candidate pool and the
    # picker organically selects a smaller chr through its normal
    # pipeline — no separate demotion path, so the caliber / cap /
    # Gate-5.6 machinery the old post-passes had to re-implement is
    # gone. The gates are inert unless run_ctx.msb_size_gate_active is
    # set, which begin_msb() does only inside shuffle_msb_v3's slot
    # loop. The reservation pre-pass and the reservation early-return
    # never arm it, so a reserved big chr is never proximity/density-
    # rejected — this closes the reservation-floor-demotion bug. Loop
    # order is pi-ascending, so "low-pi wins" matches the post-passes'
    # "first-pi wins" / "highest-pi demoted" exactly. Geometric, not
    # chaos-overrideable.
    if (run_ctx is not None
            and getattr(run_ctx, 'msb_size_gate_active', False)):
        _gsz = _effective_size_class(target_cp, tags)
        if _gsz in V3_DENSITY_L_SIZE_CLASSES:  # L / XL / XXL / GIGA
            _is_xl = _gsz in V3_BIG_SIZE_CLASSES  # XL / XXL / GIGA
            # Gate 9: density
            if V3_DENSITY_CAP_ENABLED:
                if _is_xl and run_ctx.msb_xl_count >= run_ctx.msb_xl_cap:
                    return 'density_xl'
                if run_ctx.msb_l_count >= run_ctx.msb_l_cap:
                    return 'density_l'
            # Gate 8: proximity (XL+ only)
            if (V3_BIG_PROXIMITY_ENABLED
                    and not V3_BIG_PROXIMITY_HASH_TIEBREAK
                    and _is_xl
                    and slot_pos is not None
                    and run_ctx.msb_big_positions):
                _px, _py, _pz = slot_pos
                _rsq = V3_BIG_PROXIMITY_RADIUS ** 2
                for _bx, _by, _bz in run_ctx.msb_big_positions:
                    if ((_px - _bx) ** 2 + (_py - _by) ** 2
                            + (_pz - _bz) ** 2) < _rsq:
                        return 'big_proximity'

    return None



# ---------------------------------------------------------------------------
# Order-independent proximity tie-break (v0.32.x, opt-in)
# ---------------------------------------------------------------------------
#
# The forward Gate 8 (proximity) above resolves big-vs-big overcrowding in
# Part-index visit order: the first XL+ placed in a neighbourhood survives,
# any later XL+ within V3_BIG_PROXIMITY_RADIUS is rejected. That is the
# "low-pi wins" survivorship the TODO flagged — which slot keeps its big is
# an artefact of iteration order, not of anything about the slots.
#
# This helper re-resolves the SAME contest by a deterministic priority key
# instead of visit order. It is a pure function: feed it every committed XL+
# placement in an MSB plus a priority function (a hash of seed+msb+pi), and
# it returns the set of placements to demote. Because it walks slots in
# priority order rather than the order they are supplied, permuting the
# input yields an identical demotion set — the order-dependence is gone.
#
# It does NOT touch Gate 9 (density), which is a counted cap and is left
# strictly in canonical-order consumption so it stays identical to
# simulate_engine.py's sorted(part_index) pass (the v0.28 parity guarantee).
def resolve_big_proximity_priority(big_slots, radius_sq, priority_of):
    """Resolve big-enemy proximity conflicts by priority, not visit order.

    Args:
        big_slots: iterable of (pi, pos) for every committed XL+ placement
            in one MSB. `pi` is the Part index (the identity key used
            downstream — swap_plan, spoilers, repositions). `pos` is the
            slot's (x, y, z) world position, or None if unknown.
        radius_sq: squared proximity radius (V3_BIG_PROXIMITY_RADIUS ** 2).
        priority_of: callable pi -> orderable key, HIGHER wins. Must be a
            pure function of slot identity (e.g. a seed+msb+pi hash) so the
            outcome is reproducible per seed and independent of the order
            `big_slots` is supplied in.

    Returns:
        set[int] of pi to DEMOTE (revert to vanilla) — the losers of each
        proximity contest. Winners are not returned; a slot with no
        neighbour within radius is never demoted.

    Greedy by priority: walk slots highest-priority first; a slot wins iff
    it is not within radius of an already-accepted winner, else it is
    demoted. The globally highest-priority slot in any neighbourhood always
    survives, and the walk order is the priority key (not the input order),
    so the result is permutation-invariant. Ties on the priority key fall
    back to higher pi, keeping the total order fully deterministic.
    """
    slots = sorted(
        ((pi, pos) for pi, pos in big_slots),
        key=lambda s: (priority_of(s[0]), s[0]),
        reverse=True,
    )
    winners = []  # positions of accepted winners so far
    demoted = set()
    for pi, pos in slots:
        if pos is None:
            # No usable position — proximity can't be tested. Mirrors the
            # forward gate, which only fires when slot_pos is not None.
            continue
        px, py, pz = pos
        if any((px - wx) ** 2 + (py - wy) ** 2 + (pz - wz) ** 2 < radius_sq
               for wx, wy, wz in winners):
            demoted.add(pi)
        else:
            winners.append(pos)
    return demoted



# ---------------------------------------------------------------------------
# Second mirror: scoring helper for the reservation pre-pass
# ---------------------------------------------------------------------------
#
# v0.28.x: folded in from oops_v3._score_slot_for_unique. The
# reservation pre-pass calls this to rank candidate slots for each
# cp; the gate-mirror invariant (reject_target_for_slot above) is
# enforced as part of the scoring (a rejected (src, target) returns
# None). Both mirrors now live in this module — the v0.24.27
# consolidation pattern continues.
def score_slot_for_unique(ns, slot_info, target_cp, tags):
    """Score how well slot_info fits target_cp for a unique reservation.

    slot_info is a dict from _enumerate_unique_candidate_slots (see below).
    Higher = better. Returns None for hard-disqualifying slots.

    Hard requirements (return None):
      - source is in V3_EXCLUDE_SOURCE_PREFIXES (slot stays vanilla)
      - source npc_param in V3_EXCLUDE_SOURCE_NPC_PARAMS (preserved)
      - source is in a multi-Part cluster (cluster_id is not None)
      - incompatible with target (size/family)
      - slot is fragile (per is_fragile_slot) AND target is in
        V3_FRAGILE_SENSITIVE_TARGETS — they don't survive together

    Scoring (additive):
      +10  slot (msb, pi) is in V3_BOSS_SLOT_CATALOG (any scope)
      +5   source variant name carries a Night/Field/Castle/Fort Boss marker
      +3   source size_class is XL+ (matches big-creature feel)
      +2   target is flying_dragon AND slot Y altitude > 30 (sky-eligible)
     -10  target is flying_dragon AND slot is interior MSB (m4x_xx_xx
          dungeon/cave) — sky-spawn animation needs open ceiling
    """
    # Bind module-level dependencies into locals. Same
    # pattern as reject_target_for_slot above.
    #
    # V3_* state — read-only configuration:
    V3_BOSS_SLOT_CATALOG = ns['V3_BOSS_SLOT_CATALOG']
    V3_EXCLUDE_SOURCE_NPC_PARAMS = ns['V3_EXCLUDE_SOURCE_NPC_PARAMS']
    V3_EXCLUDE_SOURCE_PREFIXES = ns['V3_EXCLUDE_SOURCE_PREFIXES']
    V3_FRAGILE_SENSITIVE_TARGETS = ns['V3_FRAGILE_SENSITIVE_TARGETS']
    V3_NIGHT_BOSS_NAME_MARKERS = ns['V3_NIGHT_BOSS_NAME_MARKERS']
    V3_PRESERVE_SLOTS = ns['V3_PRESERVE_SLOTS']
    V3_PROBLEM_SLOT_EXTRA_ALLOWS = ns['V3_PROBLEM_SLOT_EXTRA_ALLOWS']
    V3_PROBLEM_SLOT_EXTRA_BANS = ns['V3_PROBLEM_SLOT_EXTRA_BANS']
    # Helper functions imported from oops_v3:
    _shifting_earth_event = ns['_shifting_earth_event']
    is_fragile_slot = ns['is_fragile_slot']
    src_cp = slot_info['source_cp']

    # Hard: identity-swap rejection. If the slot's source already IS the
    # target c-prefix, reserving it accomplishes nothing — the slot would
    # already produce that c-prefix in vanilla, and the engine may even
    # skip the slot entirely (aerial-source preservation, etc.). Worse,
    # the count pre-bump would tie up a cap unit on a no-op reservation.
    if src_cp == target_cp:
        return None

    # Hard: shifting-earth disqualification. Only one shifting-earth event
    # activates per Expedition (Mountaintop OR Crater OR Rot Forest OR
    # Noklateo), so a reservation that lands on, e.g., a Crater tile
    # wouldn't appear if the run rolls Mountaintop. Disqualify all
    # shifting-earth slots from reservations entirely. Caps still apply
    # to organic picks at these slots via _V3_UNIQUE_PLACED_COUNTS, so
    # a cap=1 chr can't appear at both an always-active reservation AND
    # a shifting-earth tile in the same run — they share count budget.
    if _shifting_earth_event(slot_info['msb']) is not None:
        return None

    # v0.24.27: mirror-semantic gates consolidated into
    # _reject_target_for_slot. Previously this function had three
    # inline mirror blocks (NB-caliber from v0.23.07, NB-strict from
    # v0.23.11, source-anim from v0.24.26). Each was added as a hand-
    # written mirror of a new pick_target_cp gate. The pattern broke
    # three times in a row when a new gate landed in the picker but
    # the mirror was forgotten here. The predicate now owns the gate
    # logic; both call sites delegate. Future gate additions add to
    # the predicate and both paths inherit.
    src_variant_name = slot_info.get('source_variant_name') or ''
    if reject_target_for_slot(ns, target_cp, src_cp, src_variant_name,
                                tags,
                                msb_base=slot_info.get('msb'),
                                pi=slot_info.get('pi')) is not None:
        return None

    # Hard: source preservation
    if src_cp in V3_EXCLUDE_SOURCE_PREFIXES:
        return None
    if slot_info.get('source_npc') in V3_EXCLUDE_SOURCE_NPC_PARAMS:
        return None
    # v0.23.74: strict (msb, pi)-level preservation. See V3_PRESERVE_SLOTS
    # docstring. Used to back the m49_28 Night's Cavalry NB exemption
    # after the c3150/c3160 c-prefix-level protections were lifted.
    if (slot_info.get('msb'), slot_info.get('pi')) in V3_PRESERVE_SLOTS:
        return None
    # Hard: clusters skipped for v1 (cluster placements are too entangled
    # with cluster-shape matching to safely reserve a single Part)
    if slot_info.get('cluster_id') is not None:
        return None

    # v0.24.100: anim_class compat gate REMOVED. The historical block
    # imported _compat_rig from swap_compat and disqualified slots
    # whose source/target family differed without a compat-pair entry.
    # Since v0.24.75 the function was always-True (no-op); v0.24.100
    # deletes it outright. Flier-vs-ground separation is now enforced by
    # the flier-required slot gate above and by is_compatible at the
    # main swap-loop layer.
    src_tag = tags.get(src_cp, {})
    tgt_tag = tags.get(target_cp, {})

    # Hard: SENSITIVE-target × fragile-slot incompatibility. If the target
    # is in the SENSITIVE blacklist (Borealis is, c4500 is post-lift, etc.)
    # AND this slot is fragile per is_fragile_slot, the placement would be
    # filtered out at runtime anyway — disqualify upfront.
    #
    # v0.24.62: extended fragility filter for unique reservations.
    # Previously this only rejected SENSITIVE chrs at fragile slots. The
    # standard shuffle's filter restricts the chosen_pool to
    # V3_FRAGILE_SAFE_CONFIRMED ∪ V3_RESILIENT_BIPEDS — but uniques were
    # bypassing that broader restriction because _score_slot_for_unique
    # only consulted SENSITIVE. As a result, Nightlords (c4900/c7500/
    # c7520/c7540/c7600/c7910) and MMV imports could land at fragile
    # slots even though they aren't in SAFE_CONFIRMED. User seed 537773
    # v0.24.58: c7910 Storm King reserved m30_30 pi=45 (Guardian Golem
    # Fort rampart, in V3_PROBLEM_SLOTS since v0.24.18 for c4441 Land
    # Squirt CTD); player CTD walking away from the fort. Bringing
    # uniques onto the same fragility filter the standard shuffle uses.
    # Also honors V3_PROBLEM_SLOT_EXTRA_BANS at fragile slots.
    is_fragile = is_fragile_slot(slot_info['msb'], slot_info['pi'],
                                  slot_info.get('source_variant_name') or '',
                                  slot_pos=slot_info.get('position'))
    if is_fragile:
        # v0.27.0: WHITELIST -> BLACKLIST flip (mirrors the standard-
        # shuffle fragile filter in pick_target_cp). The old gate
        # required target_cp in V3_FRAGILE_SAFE_CONFIRMED; that whitelist
        # was archived. A unique reservation now lands at a fragile slot
        # unless target_cp is in the V3_FRAGILE_SENSITIVE_TARGETS
        # blacklist or the per-slot EXTRA_BANS. EXTRA_ALLOWS still
        # bypasses the SENSITIVE reject (its original purpose).
        extra_allows = V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
            (slot_info['msb'], slot_info['pi']))
        allowed_via_extra = extra_allows and target_cp in extra_allows
        if not allowed_via_extra:
            if target_cp in V3_FRAGILE_SENSITIVE_TARGETS:
                return None
        extra_bans = V3_PROBLEM_SLOT_EXTRA_BANS.get(
            (slot_info['msb'], slot_info['pi']))
        if extra_bans and target_cp in extra_bans:
            return None

    score = 0
    # v0.24.99: V3_BOSS_SLOT_CATALOG-authoritative score. Pre-v0.24.99 the
    # +10 came from src_tag.get('expects_boss_arena'), a prefix-level tag
    # that applies uniformly across all variants of a c-prefix. For
    # prefixes whose roster mixes boss and non-boss variants — c2500
    # Crucible Knight has 22 variants spanning NB1 / Evergaol / Castle
    # grunt (the 10-Part m49_43 Roundtable group) — every castle grunt
    # slot scored +10 equal with real evergaol/NB slots. Result was that
    # cap-bounded uniques (Godrick the Grafted cap=2, Elder Lion cap=8)
    # concentrated at the castle Roundtable because 10 m49_43 slots all
    # tied at 10 with the real boss-arena slots. Catalog membership is
    # slot-level (not prefix-level), built from careful vanilla MSB
    # inventory, and already authoritative for recipient_is_boss at the
    # swap loop (v0.24.98). Using it here distributes uniques across
    # actual catalogued boss arenas instead.
    #
    # NB: 35 vanilla slots have expects_boss_arena=True src_cp but are
    # not in the catalog. ~23 are correctly demoted by this change
    # (m49_43 castle Crucibles, m60_44_36 c3350 grunts, m46_05 c4660
    # field-Guardian-Golem encounters, m60_45_36 c4500 hub-passthrough).
    # ~11 are likely catalog-missing real boss slots (m46_70 pi=3 / m46_80
    # pi=1 Godskin Apostle (Evergaol/Oldest Gaol) — paired bosses with
    # already-catalogued NB1 anchors; m34_10 pi=88-91 Miranda Blossom
    # (Ruins); m34_00 pi=123-125,152-153 Ancient Hero (Ruins); m46_78
    # Morgott Random Encounter). Those slots lose the priority bonus but
    # remain eligible for organic swaps; catalog-add is a separate
    # follow-up.
    if (slot_info['msb'], slot_info['pi']) in V3_BOSS_SLOT_CATALOG:
        score += 10
    src_name = (slot_info.get('source_variant_name') or '')
    if any(m in src_name for m in V3_NIGHT_BOSS_NAME_MARKERS):
        score += 5
    if src_tag.get('size_class') in ('XL', 'XXL', 'GIGA'):
        score += 3

    # v0.27.28: aerial-target scoring REMOVED along with the rest of the
    # flying-vs-ground machinery. This soft preference nudged fliers toward
    # high-Y outdoor slots and penalized them at interior MSBs; with flying
    # no longer a tracked class (per Alaric — dragons start grounded, any
    # enemy is fine at any former dragon slot), there's nothing to score.

    return score
