"""Per-MSB shuffler (extracted from oops_v3.py).

WHAT THIS IS
------------
`shuffle_msb_v3` is the main per-MSB driver. Called once per
playable MSB file by `_cmd_shuffle_v3_impl`, it:

  1. Parses the MSB binary, walking the PART table to find every
     enemy slot — identifying tier (Night Boss / Field Boss /
     Cluster / Field / Ghost), the slot's source c-prefix, variant
     name, position, group/cluster membership, and special-case
     flags (boss-arena, starting-encampment, fragile, problem-slot,
     density-capped tunnel, ...)
  2. For each swap-eligible slot, calls pick_target(ns, ...) (a
     thin variant-selection wrapper above engine.picker
     .pick_target_cp). Honors V3_BOSS_TIER_PINNED_SLOTS and
     V3_BOSSY_PROMOTE_SLOTS overrides, the reservation pre-pass
     results, density caps for L+/XL+ targets, problem-slot bans,
     POI-cluster recycling (v0.28.x), and the binary-search
     vanilla-pin path used by `--bisect` to locate misbehaving
     placements.
  3. Applies cluster-coherent swaps (every Part in a cluster
     receives the same target) and the rider/mount pair preservation
     pass.
  4. Patches the MSB byte stream in-place: model-index reassignment
     via add_model_entry / find_model_index, npc_param and
     think_param overwrites at PART_OFF_NPC_PARAM /
     PART_OFF_THINK_PARAM offsets, position shifts via
     lookup_position_shift, model Y-offsets via lookup_model_y_offset.
  5. Optionally calls apply_merchant_model_swaps for the merchant-
     model-swap path (v0.21.x) and remove_unused_model_entries to
     clean up the model table when V3_REMOVE_UNUSED_ENEMY_MODELS is
     on.
  6. Writes the patched MSB bytes to output_path, appends spoiler
     entries to the caller-supplied list, returns
     (n_swaps, n_added_model_entries, n_skipped_compat, n_clusters).

WHY IT WAS EXTRACTED
--------------------
1220 lines — the largest single function in oops_v3.py. After the
picker / reservations / spoilers / load_data / rejection
extractions, this function's callees all live in engine.* but the
shuffle driver itself was still in the host module. Extracting it
shrinks oops_v3.py the most of any remaining move and gives the
per-MSB pipeline its own module.

The dependency surface is large (28 V3_* gate sets, 4 _V3_*
read-only state, 10 underscore helpers, 6 MSB-offset UPPER
constants, 15 public helpers) but mechanical — all bind from `ns`
once at the top.

CALLS INTO ENGINE
-----------------
The body calls `pick_target(ns, ...)` from ns. `pick_target` is
the variant-selection wrapper around engine.picker.pick_target_cp;
it still lives in oops_v3 (200 lines, on the "maybe extract later"
list). That call goes ns → oops_v3.pick_target → engine.picker
.pick_target_cp via the existing shim, adding one function-call
layer. A follow-up could fold pick_target into engine.picker to
eliminate the hop, but that's outside this extraction.

NO GLOBAL WRITES
----------------
Unlike load_data, shuffle_msb_v3 has zero `global` declarations.
Every V3_* / _V3_* reference is a read; per-run state mutation
happens via the run_ctx parameter (engine.runctx.RunContext) or
through the spoiler_entries list the caller passes in. So this
extraction uses the simple binding-header pattern only (no flush
needed).
"""
from __future__ import annotations

import os
import struct
from collections import Counter, defaultdict


def shuffle_msb_v3(ns, input_path, output_path, rng, tags, prefix_variants, prefix_count,
                    spoiler_entries=None,
                    oops_all_target_cp=None,
                    target_count=None,
                    merchant_model_swap=False,
                    terrain_test_targets=None,
                    disable_resilient_filter=False,
                    non_fragile_baseline_cp=None,
                    diagnostic_test_targets=None,
                    chaos_mode=False,
                    mount_rider_swap=False,
                    oops_all_nb_target_cp=None,
                    oops_all_nb_marker_scope=None,
                    oops_all_nb_pinned_slot=None,
                    pinned_only_in_hub=False,
                    gates=None,
                    run_ctx=None):
    """Returns (n_swaps, n_models_added, n_skipped_compat, n_clusters) on success,
    or None on parse fail.

    v0.23.72-late: bank_to_prefixes / loose_to_prefixes / mode dropped from
    signature (see compatible_pool docstring).

    pinned_only_in_hub:
      False (default) — process every Part normally.
      True — only process Parts whose (msb, pi) is in
              V3_BOSS_TIER_PINNED_SLOTS. All other Parts stay vanilla.
              Set internally by rando_pipeline when a HUB_MAP has
              pinned slots; preserves NPC dialogues / quest triggers
              while still randomizing explicitly-listed boss-tier
              slots inside hubs.
    """
    # Bind module-level dependencies into locals — same pattern
    # as engine.picker etc. The body below reads identically to
    # the original; LOAD_FAST opcodes replace LOAD_GLOBAL on a
    # function that processes thousands of MSB parts per call.
    #
    # V3_* state — read-only configuration:
    V3_BINARY_SEARCH_VANILLA_PINS = ns['V3_BINARY_SEARCH_VANILLA_PINS']
    V3_BOSSY_PROMOTE_SLOTS = ns['V3_BOSSY_PROMOTE_SLOTS']
    V3_BOSS_SLOT_CATALOG = ns['V3_BOSS_SLOT_CATALOG']
    V3_BOSS_TIER_PINNED_SLOTS = ns['V3_BOSS_TIER_PINNED_SLOTS']
    V3_DENSITY_CAP_L_PLUS = ns['V3_DENSITY_CAP_L_PLUS']
    V3_DENSITY_CAP_XL_PLUS = ns['V3_DENSITY_CAP_XL_PLUS']
    V3_DENSITY_L_SIZE_CLASSES = ns['V3_DENSITY_L_SIZE_CLASSES']
    V3_DIAGNOSTIC_INVENTORY_MSBS = ns['V3_DIAGNOSTIC_INVENTORY_MSBS']
    V3_EXCLUDE_PREFIXES = ns['V3_EXCLUDE_PREFIXES']
    V3_EXCLUDE_SOURCE_NPC_PARAMS = ns['V3_EXCLUDE_SOURCE_NPC_PARAMS']
    V3_EXCLUDE_SOURCE_PREFIXES = ns['V3_EXCLUDE_SOURCE_PREFIXES']
    V3_MERCHANT_MODEL_SWAP_ENABLED = ns['V3_MERCHANT_MODEL_SWAP_ENABLED']
    V3_NIGHT_BOSS_EXTENDED_NAME_MARKERS = ns['V3_NIGHT_BOSS_EXTENDED_NAME_MARKERS']
    V3_NIGHT_BOSS_NAME_MARKERS = ns['V3_NIGHT_BOSS_NAME_MARKERS']
    V3_NIGHT_BOSS_STRICT_NAME_MARKERS = ns['V3_NIGHT_BOSS_STRICT_NAME_MARKERS']
    V3_OOPS_ALL_NB_PLACEHOLDER_CAP = ns['V3_OOPS_ALL_NB_PLACEHOLDER_CAP']
    V3_PLACEHOLDER_POSITION_THRESHOLD = ns['V3_PLACEHOLDER_POSITION_THRESHOLD']
    V3_POI_SCOPE_RECYCLE = ns['V3_POI_SCOPE_RECYCLE']
    V3_PROBLEM_SLOTS = ns['V3_PROBLEM_SLOTS']
    V3_PROBLEM_SLOT_EXTRA_BANS = ns['V3_PROBLEM_SLOT_EXTRA_BANS']
    V3_REMOVE_UNUSED_ENEMY_MODELS = ns['V3_REMOVE_UNUSED_ENEMY_MODELS']
    V3_STARTING_ENCAMPMENT_MSBS = ns['V3_STARTING_ENCAMPMENT_MSBS']
    V3_TARGET_ONLY_SOURCES = ns['V3_TARGET_ONLY_SOURCES']
    V3_TRACKED_C_PREFIXES = ns['V3_TRACKED_C_PREFIXES']
    V3_TUNNEL_DENSITY_CAP_L_PLUS = ns['V3_TUNNEL_DENSITY_CAP_L_PLUS']
    V3_TUNNEL_DENSITY_CAP_XL_PLUS = ns['V3_TUNNEL_DENSITY_CAP_XL_PLUS']
    V3_TUNNEL_MAPS = ns['V3_TUNNEL_MAPS']
    V3_UNIQUE_TARGET_CAPS = ns['V3_UNIQUE_TARGET_CAPS']
    # _V3_* state — read-only here (logs/counters are populated
    # upstream by load_data and the reservation pre-pass):
    _V3_PRESERVED_SOURCE_LOG = ns['_V3_PRESERVED_SOURCE_LOG']
    _V3_SLOT_POI_CLUSTERS = ns['_V3_SLOT_POI_CLUSTERS']
    _V3_TRACE_BUFFER = ns['_V3_TRACE_BUFFER']
    _V3_UNIQUE_PLACED_COUNTS = ns['_V3_UNIQUE_PLACED_COUNTS']
    # oops_v3 underscore helpers:
    _classify_variant_source = ns['_classify_variant_source']
    _detect_mount_rider_slots = ns['_detect_mount_rider_slots']
    _effective_nb_target_cp = ns['_effective_nb_target_cp']
    _effective_scope = ns['_effective_scope']
    _effective_size_class = ns['_effective_size_class']
    _emit_msb_part_inventory_trace = ns['_emit_msb_part_inventory_trace']
    _is_spawn_pool_rotation_source = ns['_is_spawn_pool_rotation_source']
    _log_unaccounted = ns['_log_unaccounted']
    _preserve_detected_rider_mount_pairs = ns['_preserve_detected_rider_mount_pairs']
    _variant_name = ns['_variant_name']
    # MSB byte-offset constants (defined as module-level UPPER):
    OOPS_ALL_NB_MARKER_SCOPE = ns['OOPS_ALL_NB_MARKER_SCOPE']
    OOPS_ALL_NB_TARGET_CP = ns['OOPS_ALL_NB_TARGET_CP']
    PART_OFF_ENTITY_ID = ns['PART_OFF_ENTITY_ID']
    PART_OFF_MODEL_INDEX = ns['PART_OFF_MODEL_INDEX']
    PART_OFF_NPC_PARAM = ns['PART_OFF_NPC_PARAM']
    PART_OFF_THINK_PARAM = ns['PART_OFF_THINK_PARAM']
    # Public helpers (model-table editing, MSB parsing, pick_target
    # variant-selection wrapper above engine.picker, etc.):
    add_model_entry = ns['add_model_entry']
    apply_merchant_model_swaps = ns['apply_merchant_model_swaps']
    field_roll_tier_for = ns['field_roll_tier_for']
    find_model_index = ns['find_model_index']
    is_boss_tier_prefix = ns['is_boss_tier_prefix']
    is_boss_tier_variant = ns['is_boss_tier_variant']
    is_catalogued_boss_slot = ns['is_catalogued_boss_slot']
    lookup_model_y_offset = ns['lookup_model_y_offset']
    lookup_position_shift = ns['lookup_position_shift']
    lookup_slot_terrain = ns['lookup_slot_terrain']
    parse_model_entry = ns['parse_model_entry']
    parse_msb_sections = ns['parse_msb_sections']
    pick_target = ns['pick_target']
    pick_variant_for_tier = ns['pick_variant_for_tier']
    remove_unused_model_entries = ns['remove_unused_model_entries']
    # v0.24.22 (Phase 5.5): runtime bookkeeping refs. Same resolve
    # pattern as pick_target_cp — run_ctx=None reads/writes the module
    # dicts (preserving back-compat for any direct caller that hasn't
    # been updated), explicit RunContext reads/writes its dicts. The
    # production cmd_shuffle_v3 path constructs a RunContext at the
    # top of every run and threads it through, so module-dict writes
    # are unreachable in production except via the final back-copy
    # at end of cmd_shuffle_v3 (kept for spoiler-emit observability).
    if run_ctx is None:
        _placed_counts = _V3_UNIQUE_PLACED_COUNTS
    else:
        _placed_counts = run_ctx.unique_placed_counts
    with open(input_path, 'rb') as f: data = bytearray(f.read())  # mutable for v0.23.04 collapse pass
    sections = parse_msb_sections(data)
    if len(sections) != 6: return None

    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]
    midx_to_cp = {gi: parse_model_entry(data, eo)['name']
                  for gi, eo in enumerate(models['entry_offsets'])}

    # v0.23.04: Rider+mount collapse pass — runs before cluster detection and
    # before the swap loop. Suppresses the mount Part of each detected pair
    # (npc_param := 0, vanilla "no spawn" convention) and copies the mount's
    # world position onto the rider Part so the rider's eventual swap target
    # spawns at the player-engagement coords. Already-preserved pairs (per
    # V3_EXCLUDE_SOURCE_PREFIXES / V3_EXCLUDE_SOURCE_NPC_PARAMS) are skipped,
    # so Tree Sentinel arenas and Night's Cavalry arena remain fully vanilla
    # in current ship.
    #
    # v0.24.101: DISABLED. The collapse pass zeroes the *combat* mount's
    # npc_param but doesn't address the visual mount that comes through the
    # rider's spawn cluster — playtest seed 537123 caught Godskin Apostle
    # visibly on the Cavalry horse at m46_62 Evergaol even though the c3160
    # combat Part was zeroed. Falling back to broad c-prefix exclusion of
    # all rider+mount pairs while this is debugged. After v0.24.101, with
    # c3150/c3160/c3170/c3180/c4050/c4060/c4363 all in both
    # V3_EXCLUDE_SOURCE_PREFIXES and V3_EXCLUDE_TARGET_PREFIXES, the
    # collapse pass would have nothing to do anyway (its first skip clause
    # at line ~1042 catches all 4 RIDER_MOUNT_PAIRS entries). Kept around
    # as dead code so the implementation isn't lost when revisited.
    #
    # TODO(v0.25+): re-enable the collapse pass after investigating the
    # rider-cluster visual-mount issue. Likely needs to also reset the
    # rider Part's cluster_id or break its anim cluster binding so the
    # new chr doesn't inherit the mount visual. May also need handling
    # for the Tree Sentinel-style "rider cluster includes pre-attached
    # mount model" pattern more generally. Once that lands, the broad
    # c3150 source-exclude (added v0.24.101) can be lifted again.
    rider_mount_collapses = []  # _collapse_rider_mount_pairs(data, parts, midx_to_cp)  # v0.24.101: disabled
    if rider_mount_collapses:
        _V3_TRACE_BUFFER.append({
            'event': 'RIDER_MOUNT_COLLAPSE',
            'msb': os.path.basename(input_path),
            'n_pairs': len(rider_mount_collapses),
            'pairs': rider_mount_collapses,
        })

    # v0.27.44 (Alaric): preserve EVERY rider+mount pair at the SLOT level.
    # Supersedes the v0.27.43 c5840<->c5890 coordinated-swap family AND avoids
    # the blunt c-prefix source-exclude: those would freeze the FOOT instances
    # of riders that also appear dismounted (Kaiden c4050, Leyndell/Lordsworn
    # Knight c4353, Albinauric Archer c3170) vanilla too. Instead, detect the
    # actual paired Parts (RIDER_MOUNT_PAIRS prefix combo + proximity; the
    # detector's 2.0u threshold is validated against vanilla — every known
    # pair sits <=1.78u apart) and add BOTH the rider Part and its mount Part
    # to V3_PRESERVE_SLOTS for this MSB. The existing strict (msb, pi) preserve
    # gate (see ~line 13180) then returns None for exactly those two slots, so
    # they stay vanilla. A SOLO rider or SOLO mount is never matched, so it
    # keeps randomizing normally. Runs every MSB (the old mount_rider_swap
    # toggle only logged the detection; it never acted on it). Reuses the
    # existing preserve gate, so spoiler/audit reporting stays consistent.
    _mr_detected = _detect_mount_rider_slots(data, parts, midx_to_cp)
    if _mr_detected:
        _mr_msb_key = os.path.basename(input_path)
        if _mr_msb_key.endswith('.dcx'):
            _mr_msb_key = _mr_msb_key[:-4]
        _mr_added = _preserve_detected_rider_mount_pairs(_mr_detected, _mr_msb_key)
        _V3_TRACE_BUFFER.append({
            'event': 'RIDER_MOUNT_PAIR_PRESERVE',
            'msb': _mr_msb_key,
            'n_pairs': len(_mr_detected),
            'n_newly_preserved': len(_mr_added),
            'preserved_pis': sorted(
                {_d['rider_pi'] for _d in _mr_detected}
                | {_d['mount_pi'] for _d in _mr_detected}),
            'pairs': _mr_detected,
        })


    # v0.26.13: cluster system removed. Every Part rolls independently.
    # n_clusters retained as a vestigial 0 in the return tuple to avoid a
    # return-arity change across callers / pipeline metadata / tests.
    n_clusters = 0

    # v0.20.15: shared-position placeholder pre-pass.
    # Some MSBs author script-spawn placeholder blocks where many Parts share
    # the same authored position; the spawn script reads NPCParam from each
    # placeholder slot at runtime to type-check what model to summon. The
    # v0.20.11/.12 heuristic only catches the eid==0 subset. The castle
    # m15_00 has a 39-Part block at (52.11, 0.3, 26.57) with sequential eids
    # 15000430–468 (basement boss event waves) that has eid != 0 and so
    # leaks through the older heuristic. m46_70 and m49_27 show the same
    # pattern at smaller scale.
    # Cluster-managed Parts are excluded from the count (they go through
    # the cluster path) so we don't accidentally flag e.g. Crystalian
    # triplets that happen to share a spawn point.
    placeholder_pos_counts = Counter()
    for _spi, _spo in enumerate(parts['entry_offsets']):
        if _spo + 0x400 + 12 > len(data):
            continue
        try:
            _sx, _sy, _sz = struct.unpack_from('<fff', data, _spo + 0x400)
            # NaN check without importing math
            if _sx != _sx or _sy != _sy or _sz != _sz:
                continue
            _rp = (round(_sx * 2) / 2,
                   round(_sy * 2) / 2,
                   round(_sz * 2) / 2)
            placeholder_pos_counts[_rp] += 1
        except struct.error:
            pass
    placeholder_positions = {p for p, n in placeholder_pos_counts.items()
                          if n >= V3_PLACEHOLDER_POSITION_THRESHOLD}
    # v0.23.60: per-MSB intercept counter for the placeholder-position cap.
    # Keyed by rounded position; values count OOPS_ALL_NB intercepts
    # that have fired at that position. See V3_OOPS_ALL_NB_PLACEHOLDER_CAP.
    _placeholder_intercept_counts = {}

    # === Build swap plan ===
    swap_plan = []
    n_skipped_compat = 0
    # v0.23.72-late+: n_skipped_aerial was removed. The aerial-skip filters
    # were ripped out in the v0.23.72 NB-boss-anchor bypass work (see comment
    # block ~line 9042 area, formerly here). The counter was kept at 0 for
    # a release cycle to avoid a return-signature churn, now cleaned up.
    # v0.23.51: hoist msb_base to outer scope so per-slot lookups
    # (V3_PROBLEM_SLOTS, V3_BOSS_TIER_PINNED_SLOTS) work in any branch
    # of the loop, not just the terrain_test branch where it was
    # originally defined.
    msb_base = os.path.basename(input_path)
    if msb_base.endswith('.dcx'):
        msb_base = msb_base[:-4]
    # v0.23.54: hoist effective OOPS_ALL_NB target/scope to function scope.
    # The pre-cluster intercept reads these per-slot, but the big-proximity
    # post-pass also needs them to know which slots to exempt from demotion.
    # Defining once at the top makes both accesses cheap and unambiguous.
    _eff_nb_target = (oops_all_nb_target_cp
                      if oops_all_nb_target_cp is not None
                      else OOPS_ALL_NB_TARGET_CP)
    _eff_nb_scope = (oops_all_nb_marker_scope
                     if oops_all_nb_marker_scope is not None
                     else OOPS_ALL_NB_MARKER_SCOPE) or 'broad'
    # v0.23.52: full MSB Part inventory diagnostic. When this MSB matches
    # the V3_DIAGNOSTIC_INVENTORY_MSBS set, log EVERY Part to the trace.
    # Resolves "where the hell is BBH in this MSB" questions without
    # needing Oodle for offline DCX decompression. Runs at zero cost
    # when the set is empty. v0.23.68: extracted to helper.
    if msb_base in V3_DIAGNOSTIC_INVENTORY_MSBS:
        _emit_msb_part_inventory_trace(data, parts, midx_to_cp, msb_base)
    # v0.28.x Phase 2: default POI scope vars to None at the outer level
    # so the slot loop below can reference them when run_ctx is None
    # (legacy/test paths that don't arm per-MSB state at all).
    _pi_to_cid = None
    _cluster_budgets = None
    # v0.27.5: arm the placement-time proximity/density gates for this
    # MSB. Caps follow the tunnel-vs-default profile the DENSITY_CAP
    # post-pass used.
    if run_ctx is not None:
        # v0.28: derive the per-MSB distinct budget + forced-vanilla
        # resident seed from a cheap read-only pre-scan of the same slots
        # the swap loop visits. budget = the count of distinct enemy
        # c-prefixes vanilla loads here; the loop introduces no more than
        # that, so the tile's chrbnd fan-out can't exceed vanilla's.
        # _preserved = enemy c-prefixes the loop keeps vanilla (excluded /
        # source-only / no-variants / pinned); they are already loaded, so
        # they seed resident and count against the budget.
        # v0.28: per-MSB rando-distinct budget. Working assumption: the
        # engine loads its own vanilla assets cheaply (bundled with the map,
        # not stressing the dynamic chr-registration path the respawn CTD
        # overflowed), so forced-vanilla slots are NOT charged against the
        # budget. The budget counts only distinct enemy c-prefixes on
        # SWAPPABLE slots — how many distinct *rando* chrbnds this tile may
        # introduce. Preserved slots still keep vanilla in the output.
        #
        # v0.28.x Phase 2 POI recycling: when V3_POI_SCOPE_RECYCLE is on
        # and slot_poi_clusters.json has an entry for this MSB, the same
        # pre-scan loop also builds a per-cluster swappable-distinct set
        # so the picker's resident/budget can scope to the smaller POI
        # cluster instead of the whole MSB. _pi_to_cid is the inverse map
        # from part_index to cluster_id within this MSB (-1 for slots
        # outside the cluster file, typically non-enemy parts).
        _poi_active = (V3_POI_SCOPE_RECYCLE
                       and _V3_SLOT_POI_CLUSTERS is not None
                       and _V3_SLOT_POI_CLUSTERS.get(msb_base) is not None)
        if _poi_active:
            _msb_clusters_for_iter = _V3_SLOT_POI_CLUSTERS[msb_base]
            _pi_to_cid = {}
            for _cid, _members in enumerate(_msb_clusters_for_iter):
                for _pi_m in _members:
                    _pi_to_cid[_pi_m] = _cid
            _cluster_swappable = defaultdict(set)
        else:
            _msb_clusters_for_iter = None
            _pi_to_cid = None
            _cluster_swappable = None

        _swappable_distinct = set()
        for _pi, _po in enumerate(parts['entry_offsets']):
            try:
                _npc = struct.unpack_from('<I', data, _po + PART_OFF_NPC_PARAM)[0]
                if _npc == 0 or _npc == 0xFFFFFFFF:
                    continue
                _midx = struct.unpack_from('<i', data, _po + PART_OFF_MODEL_INDEX)[0]
            except struct.error:
                continue
            _ccp = midx_to_cp.get(_midx, '?')
            if not (_ccp and _ccp[0] == 'c' and len(_ccp) > 1 and _ccp[1].isdigit()):
                continue
            if ((msb_base, _pi) in V3_BINARY_SEARCH_VANILLA_PINS
                    or (pinned_only_in_hub
                        and (msb_base, _pi) not in V3_BOSS_TIER_PINNED_SLOTS)
                    or _ccp in V3_EXCLUDE_PREFIXES
                    or _ccp in V3_EXCLUDE_SOURCE_PREFIXES
                    or _npc in V3_EXCLUDE_SOURCE_NPC_PARAMS
                    or _ccp not in prefix_variants):
                continue  # vanilla-kept: cheap, not charged against the budget
            _swappable_distinct.add(_ccp)
            if _cluster_swappable is not None:
                _cluster_swappable[_pi_to_cid.get(_pi, -1)].add(_ccp)
        _msb_budget = len(_swappable_distinct)
        if _cluster_swappable is not None:
            _cluster_budgets = {cid: len(cps)
                                for cid, cps in _cluster_swappable.items()}
        else:
            _cluster_budgets = None
        if msb_base in V3_TUNNEL_MAPS:
            run_ctx.begin_msb(V3_TUNNEL_DENSITY_CAP_XL_PLUS,
                              V3_TUNNEL_DENSITY_CAP_L_PLUS,
                              distinct_budget=_msb_budget,
                              caps=V3_UNIQUE_TARGET_CAPS)
        else:
            run_ctx.begin_msb(V3_DENSITY_CAP_XL_PLUS,
                              V3_DENSITY_CAP_L_PLUS,
                              distinct_budget=_msb_budget,
                              caps=V3_UNIQUE_TARGET_CAPS)
    # v0.27.13: per-MSB random slot order. The swap loop previously
    # iterated parts in strict ascending pi. That gave low-pi slots a
    # systematic advantage in any order-sensitive per-MSB accounting —
    # most notably the density caps (run_ctx.register_big /
    # V3_DENSITY_CAP_*), which accumulate as the loop runs: a big chr at
    # a low pi always got first crack at the density budget, a big chr
    # at a high pi was more often density-blocked, purely by Part index.
    # Shuffling the (pi, po) PAIRS per MSB removes that positional bias —
    # every slot has equal expected position in the processing order.
    #
    # Scope is within-MSB only: MSBs themselves stay in their original
    # order, because begin_msb/end_msb scopes the density caps per MSB
    # and a cross-MSB shuffle would interleave that accounting. pi stays
    # paired with its po (pi is an identity key downstream — catalog
    # lookups, spoiler entries, swap_plan); only the visit order changes.
    # swap_plan is applied in a separate pass that re-derives po from pi,
    # so the output is identical regardless of visit order — this shifts
    # only the order in which order-sensitive runtime state is touched.
    # Uses the shared seeded rng, so it is reproducible per seed.
    # v0.28: canonical (natural part-index) slot order. Previously this was
    # rng.shuffle'd off the shared stream, which made the processing order —
    # and thus the order-dependent target_count cap — input-dependent. With
    # the per-slot hashed pick (_slot_decision_rng) the order no longer
    # affects which enemy a slot gets, and a canonical order makes cap
    # consumption deterministic and identical to simulate_engine.py's
    # sorted(part_index) pass.
    #
    # v0.28.x Phase 2 POI recycling: when POI scope is active, slots are
    # reordered so same-cluster slots are adjacent. Order is still fully
    # canonical: clusters in cluster_id order (which the builder assigns
    # by min(part_index) within MSB), slots in pi order within cluster.
    # 50/124 multi-cluster MSBs already have pi-contiguous clusters; the
    # rest interleave (worst m60_42_36_50 at 60% pi-boundaries). The
    # cluster-grouped order produces ONE begin_poi/end_poi pair per
    # cluster instead of N inline transitions. -1 (slots outside the
    # cluster file, e.g. non-enemy parts that get filtered out in the
    # slot body anyway) is placed LAST so they pick up no POI scope.
    if _pi_to_cid is not None:
        _grouped = defaultdict(list)
        for _pi_g, _po_g in enumerate(parts['entry_offsets']):
            _grouped[_pi_to_cid.get(_pi_g, -1)].append((_pi_g, _po_g))
        _slot_order = []
        for _cid_o in sorted(_grouped, key=lambda c: (c == -1, c)):
            _slot_order.extend(_grouped[_cid_o])
    else:
        _slot_order = list(enumerate(parts['entry_offsets']))
    _current_cluster = None  # tracks POI scope transitions inside the loop
    for pi, po in _slot_order:
        # v0.28.x Phase 2: cluster-transition detection. When the
        # cluster_id for this pi differs from the active one, close the
        # previous POI scope and open the new one. -1 (slots outside the
        # cluster file) means no POI scope active — picker falls back
        # to MSB-level resident/budget. With cluster-grouped order
        # above, this fires exactly once per real cluster.
        if _pi_to_cid is not None and run_ctx is not None:
            _this_cluster = _pi_to_cid.get(pi, -1)
            if _this_cluster != _current_cluster:
                if (_current_cluster is not None and _current_cluster != -1
                        and hasattr(run_ctx, 'end_poi')):
                    run_ctx.end_poi()
                if (_this_cluster != -1 and hasattr(run_ctx, 'begin_poi')
                        and _cluster_budgets is not None):
                    run_ctx.begin_poi(
                        _this_cluster,
                        _cluster_budgets.get(_this_cluster, _msb_budget))
                _current_cluster = _this_cluster
        # v0.24.109 binary-search vanilla pins. For diagnostic A/B testing
        # of specific (msb, pi) slots — pinned slots skip the picker
        # entirely and remain vanilla in the output MSB. Used to bisect
        # framerate / CTD issues to specific slot subsets without
        # re-running the full rando. Set V3_BINARY_SEARCH_VANILLA_PINS
        # to the (msb_base, pi) tuples you want forced-vanilla, then
        # reroll with the same seed for a clean diff.
        if (msb_base, pi) in V3_BINARY_SEARCH_VANILLA_PINS:
            continue
        npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0]
        if npc == 0 or npc == 0xFFFFFFFF: continue  # placeholder
        # v0.23.68: HUB_MAPS pinned-only mode. When this flag is set
        # (rando_pipeline routes hub MSBs with pinned entries here), only
        # process slots that appear in V3_BOSS_TIER_PINNED_SLOTS for this
        # MSB. Every other Part stays vanilla — preserves NPC dialogues,
        # quest triggers, merchant interactions in hub interiors while
        # still randomizing explicitly-listed boss-tier slots inside.
        if pinned_only_in_hub and (msb_base, pi) not in V3_BOSS_TIER_PINNED_SLOTS:
            continue
        midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        cur_cp = midx_to_cp.get(midx, '?')
        if cur_cp in V3_EXCLUDE_PREFIXES: continue
        if cur_cp in V3_EXCLUDE_SOURCE_PREFIXES:
            # v0.20.18: log preserved-source slots for tracked c-prefixes
            # so the spoiler MD can render "Source slots (preserved as
            # vanilla)" for c3610/c3620 (Oracle Envoys), etc. Read the
            # position once for the log; we don't need slot_pos parsed
            # the same way the heuristic does.
            if cur_cp in V3_TRACKED_C_PREFIXES:
                _pres_pos = None
                if po + 0x400 + 12 <= len(data):
                    try:
                        _px, _py, _pz = struct.unpack_from('<fff', data, po + 0x400)
                        if not (_px != _px or _py != _py or _pz != _pz):
                            _pres_pos = [round(_px, 2), round(_py, 2), round(_pz, 2)]
                    except struct.error:
                        pass
                _pres_eid = (struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0]
                             if po + PART_OFF_ENTITY_ID + 4 <= len(data) else None)
                _V3_PRESERVED_SOURCE_LOG.append({
                    'map':           os.path.basename(input_path),
                    'part_index':    pi,
                    'entity_id':     _pres_eid,
                    'position':      _pres_pos,
                    'c_prefix':      cur_cp,
                    'npc_param_id':  npc,
                    'name':          _variant_name(cur_cp, npc, prefix_variants),
                })
            continue  # source-only exclusion
        if npc in V3_EXCLUDE_SOURCE_NPC_PARAMS: continue   # per-variant source exclusion
        if cur_cp not in prefix_variants:
            # v0.20.20: only log Enemy-class Parts (cur_cp starts with 'c'
            # followed by a digit). MSB Asset Parts (AEG_xxx geometry
            # decorations, AEG570_xxx world FX) and Collision Parts (h_xxx)
            # also iterate through this loop because parts['entry_offsets']
            # spans multiple Part subtypes; they correctly have no variants
            # and never get swapped, but logging them as bug candidates
            # drowns the signal. ~864 false-positive entries in seed-42
            # made this section unusable until the filter was added.
            if cur_cp and cur_cp[0] == 'c' and len(cur_cp) > 1 and cur_cp[1].isdigit():
                _log_unaccounted('no_variants',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
            continue
        # v0.19: target-only-promoted c-prefixes (script_spawn,
        # er_heritage_v1, etc.) keep their (rare/zero) MSB placements
        # vanilla. Their synthesized prefix_variants entries are for
        # picking npc/think IDs when chosen as a target — never used
        # as sources. Stays vanilla at any rare MSB placements like
        # Ancestor Spirit / Nameless King at special arena maps.
        #
        # v0.24.97: NARROW EXEMPTION for V3_SPAWN_POOL_MSBS pi=1.
        # The original "no MSB placements" rationale for this gate
        # (see V3_TARGET_ONLY_SOURCES docstring at line ~388) was
        # empirically wrong — c4670 and c4690 have 2 placements each
        # at m46_64/65/90/91 pi=1 (the spawn-pool rotation entries),
        # and the 19 sibling rotation entries (m46_52 c3250, m46_53
        # c3251, ...) already swap pi=1 successfully via this same
        # per-Part path. Without this exemption Grafted Scion and
        # Ancestor Spirit appear deterministically across every seed
        # at whichever live arena rolls those rotation entries,
        # defeating the randomization at those two pool slots each.
        #
        # TODO(broad-fix): drop `_source: script_spawn` from
        # V3_TARGET_ONLY_SOURCES entirely. That additionally unlocks
        # c7700/c7710/c77xx/c78xx/c79xx as sources at dedicated legacy
        # DS-import arena MSBs (m47_80, m47_90, m48_00, m48_10, m48_20,
        # m48_30). Different risk profile — those arenas are designed
        # around the specific boss footprint, so source-swap geometry
        # / chrbnd-preload mismatch is more plausible than the
        # rotation case. Audit case-by-case before lifting.
        if (cur_cp in tags
                and tags[cur_cp].get('_source') in V3_TARGET_ONLY_SOURCES
                and not _is_spawn_pool_rotation_source(msb_base, pi)):
            # v0.20.20: this is expected-vanilla architecture, not a bug.
            # See unaccounted-vanilla-log docstring — kept as a separate
            # reason so we can still surface unexpected occurrences but
            # they no longer count toward the "probable bugs" framing.
            _log_unaccounted('script_spawn_target_only_at_msb',
                             os.path.basename(input_path), pi, cur_cp, npc,
                             data, po, prefix_variants)
            continue

        # v0.23.58: PRE-CLUSTER OOPS_ALL_NB INTERCEPT — hoisted ABOVE the
        # eid==0 + near-origin filter and the shared-position placeholder
        # filter. Background:
        #
        # NR's spawn-pool MSBs (m46_5x_00_00 etc.) pack pi=0 c1000 +
        # pi=1 boss (+ pi=2 asset on the 3-Part FIELD tiles), all at world
        # origin (0,0,0). The shared-position placeholder pre-pass counts
        # how many Parts share a rounded position; >= V3_PLACEHOLDER_POSITION
        # _THRESHOLD (3) at one position marks it a script-spawn placeholder
        # block and the boss Part there is left vanilla. With all Parts
        # stacked at origin a 3-Part tile can trip this; pi=1 then stays
        # vanilla and the rotation chr appears un-randomized in-game.
        # (Historical: a separate eid==0 + near-origin filter and a cluster
        # builder also used to drop pi=1 here; both were removed —
        # near-origin v0.23.72, clustering v0.26.13. The placeholder
        # pre-pass is the one still live.)
        #
        # Mitigation: catalogued boss slots (V3_BOSS_SLOT_CATALOG) and
        # pinned slots (V3_BOSS_TIER_PINNED_SLOTS) are AUTHORITATIVE — if
        # the catalog/pin says this is a boss slot, the rando trusts that
        # over the placeholder heuristic and force-swaps it.
        #
        # Note: this force-swap intercept is gated on `_eff_nb_target`
        # (OOPS_ALL_NB boss-probe mode), so in a normal or all-SOTE run it
        # doesn't fire. That is BY DESIGN and was NOT the cause of the
        # castle-variant 0-swap bug (initially suspected here, but ruled
        # out — see the "castle-variant spawn-pool MSBs now swap" block
        # above; the real cause was name-marker classification in
        # pick_target_cp, fixed in v0.27.29). In normal/SOTE runs the
        # spawn-pool slots swap through the standard pick_target_cp path
        # like any other catalogued boss slot.
        #
        # _eff_nb_target / _eff_nb_scope hoisted to function scope above.
        _is_pinned = (msb_base, pi) in V3_BOSS_TIER_PINNED_SLOTS
        _is_catalogued = is_catalogued_boss_slot(msb_base, pi, _eff_nb_scope)
        # v0.23.60: pre-compute rounded position for the placeholder cap. We
        # need this BEFORE the intercept fires (the slot_pos read further
        # down is also fine, but it's after the early aerial/none-pos
        # skips, which we want to keep in front of the heavier work).
        _intercept_pos_key = None
        if po + 0x400 + 12 <= len(data):
            try:
                _ix, _iy, _iz = struct.unpack_from('<fff', data, po + 0x400)
                if not (_ix != _ix or _iy != _iy or _iz != _iz):  # NaN-safe
                    _intercept_pos_key = (round(_ix * 2) / 2,
                                          round(_iy * 2) / 2,
                                          round(_iz * 2) / 2)
            except struct.error:
                pass
        # Cap: if this slot's position is already a placeholder cluster AND
        # the intercept has fired V3_OOPS_ALL_NB_PLACEHOLDER_CAP times for
        # that position in this MSB, don't intercept this slot. Falls
        # through to the standard path; the placeholder filter below will
        # leave the slot vanilla. Prevents N-stacks of XL chrs at script-
        # spawn placeholder blocks (m15_00 (52.11,0.3,26.57) — 39 Parts).
        _intercept_capped = (
            _intercept_pos_key is not None
            and _intercept_pos_key in placeholder_positions
            and _placeholder_intercept_counts.get(_intercept_pos_key, 0)
                >= V3_OOPS_ALL_NB_PLACEHOLDER_CAP
        )
        if (_eff_nb_target
                and not terrain_test_targets
                and not oops_all_target_cp
                and (_is_pinned or _is_catalogued)
                and not _intercept_capped):
            # Force this slot to the OOPS_ALL_NB target, bypassing the
            # cluster-vanilla-preserve and solo-pick_target paths below.
            target_cp = _eff_nb_target
            target_variant = pick_variant_for_tier(
                target_cp, True, prefix_variants, rng, tags=tags,
                run_ctx=run_ctx)
            if target_variant is None:
                # Target c-prefix not loaded (e.g., MMV-only target with
                # MMV disabled). Log and fall through to standard handling.
                # This is NOT a silent failure — _log_unaccounted records
                # it, and the slot continues to the cluster/solo branches
                # so it still gets a swap (not left vanilla unexpectedly).
                _log_unaccounted('oops_all_nb_target_unavailable',
                                 msb_base, pi, cur_cp, npc,
                                 data, po, prefix_variants)
                # Fall through — don't 'continue' or 'append' here;
                # let cluster/solo branches handle the slot normally.
            else:
                swap_plan.append((pi, target_cp,
                                  target_variant['npc_param_id'],
                                  target_variant['think_param_id']))
                # v0.23.60: bump the per-position counter so subsequent
                # slots at this same placeholder cluster will hit the cap.
                if _intercept_pos_key is not None and _intercept_pos_key in placeholder_positions:
                    _placeholder_intercept_counts[_intercept_pos_key] = (
                        _placeholder_intercept_counts.get(_intercept_pos_key, 0) + 1)
                # Trace event so the spoiler shows the intercept fired
                _V3_TRACE_BUFFER.append({
                    'event':  'OOPS_ALL_NB_INTERCEPT',
                    'msb':    msb_base,
                    'pi':     pi,
                    'source': 'pin' if _is_pinned else 'catalog',
                    'tier':   (V3_BOSS_SLOT_CATALOG.get((msb_base, pi), {}).get('tier')
                               if _is_catalogued else 'pin'),
                    'target_cp':    target_cp,
                    'target_npc':   target_variant['npc_param_id'],
                })
                continue
        elif (_eff_nb_target
              and not terrain_test_targets
              and not oops_all_target_cp
              and (_is_pinned or _is_catalogued)
              and _intercept_capped):
            # v0.23.60: cap fired. Trace it (one entry per capped slot)
            # and fall through to the standard path; the placeholder filter
            # will leave this slot vanilla.
            _V3_TRACE_BUFFER.append({
                'event': 'OOPS_ALL_NB_INTERCEPT_CAPPED',
                'msb': msb_base,
                'pi': pi,
                'pos_key': list(_intercept_pos_key) if _intercept_pos_key else None,
                'cap': V3_OOPS_ALL_NB_PLACEHOLDER_CAP,
                'hits_at_pos': _placeholder_intercept_counts.get(_intercept_pos_key, 0),
            })

        # v0.20.0: slot_y read removed. Position-aware source skip and
        # AERIAL_SOURCE_SKIP are obsolete — empirical breakages handled
        # by V3_PROBLEM_SLOTS / V3_FRAGILE_MAPS / V3_EXCLUDE_*.
        slot_y = None

        # v0.23.72: AERIAL-SKIP / SPAWN-MARKER FILTERS REMOVED.
        #
        # Two filter blocks used to live here:
        #   1. eid==0 + near-origin (v0.20.11/.12) — caught EMEVD script-
        #      spawn placeholders by signature. The original v0.20.11 bug
        #      report ("frozen guy on overworld traversal") motivated this,
        #      but the actual CTD root cause was addressed elsewhere
        #      (swap_compat layer / merchant-model handling), so this filter
        #      stopped earning its keep.
        #   2. shared-position placeholder (v0.20.15) — caught eid!=0 slots
        #      that share position with N+ siblings. Same script-spawn-
        #      placeholder pattern by a different signature.
        #
        # The v0.23.71 pin-bypass tried to rescue legitimate slots that hit
        # these filters (spawn-pool m46 tiles with pi=1 boss at origin),
        # but pin coverage is incomplete — m49 NB arenas (and probably
        # others) aren't in t1_anchors, so their boss slots were silently
        # dropped from the swap pool. Symptom: NB1/NB2 encounter doesn't
        # start when the circle closes because the boss MSB part is missing
        # from the output. Confirmed via user playtest: Sentient Pest seed
        # 35300, m49_27 pi=? (entity 49270800) Battlefield Commander absent
        # from output MSB → empty arena.
        #
        # We still read slot_eid + slot_pos here because slot_pos is used
        # downstream (edge-sentinel detection in is_fragile_slot, line
        # ~8379). The reads are kept; only the early-exit filters were
        # removed.
        #
        # v0.23.72-late+: n_skipped_aerial counter removed from return
        # tuple. Was preserved-at-zero for one release cycle to avoid
        # signature churn; now cleaned out.
        slot_eid = struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0] \
                   if po + PART_OFF_ENTITY_ID + 4 <= len(data) else -1
        slot_pos = None
        if po + 0x400 + 12 <= len(data):
            try:
                _x, _y, _z = struct.unpack_from('<fff', data, po + 0x400)
                import math as _math
                if not (_math.isnan(_x) or _math.isnan(_y) or _math.isnan(_z)):
                    slot_pos = (_x, _y, _z)
            except struct.error:
                pass

        # Determine THIS Part's tier (used for variant selection regardless of clustering)
        recipient_variant = next((v for v in prefix_variants[cur_cp]
                                   if v['npc_param_id'] == npc), None)
        if recipient_variant is None:
            recipient_is_boss = is_boss_tier_prefix(cur_cp, tags, prefix_variants)
        else:
            recipient_is_boss = is_boss_tier_variant(recipient_variant)
        # v0.24.98: V3_BOSS_SLOT_CATALOG override. The catalog is the
        # authoritative source for slot-tier classification (per the
        # v0.23.58 comment block at line ~11584: "the catalog was built
        # from a careful inventory of NR's MSBs; if it says this is a
        # boss slot, the rando trusts that classification"). Pre-v0.24.98
        # that authoritativeness only flowed into the OOPS_ALL_NB intercept
        # — the normal recipient_is_boss decision relied on
        # is_boss_tier_variant's V3_BOSS_NAME_MARKERS substring check,
        # which misses the parenthesized-suffix tier categories: (Fort),
        # (Castle), (Cathedral), (Crater), (Noklateo), (Mountaintop),
        # plus the curated 'named_boss' entries (Crucible Knight,
        # Fallingstar Beast Random Encounter, etc.). 104 of 340 catalog
        # entries fell into that gap, including the three (Fort) slots
        # not already in V3_BOSSY_PROMOTE_SLOTS — m30_00 pi=17 (Lordsworn
        # Captain Fort), m30_00 pi=36 (Abductor Virgin Fort), m30_30 pi=7
        # (Crystalian Fort) — which were swapping to grunt/trash targets
        # like Mushroom Dog because the picker didn't restrict to
        # boss-strength tiers. With this override, catalog membership at
        # any scope promotes the slot's recipient_is_boss to True.
        #
        # Plain 'bossy' equivalent (V3_BOSS_STRENGTH_TIERS restriction
        # only). The four (Fort), three (Cathedral), and ten (Castle)
        # interior slots are likely also fog-wall encounters that would
        # benefit from 'boss_reward' mode (the stricter has_boss_reward
        # filter that excludes Highwayman/Bloodhound miniboss-class
        # humanoids), but that's an empirical playtest question per-tier.
        # V3_BOSSY_PROMOTE_SLOTS still applies below for per-slot
        # boss_reward upgrades when audit-confirmed.
        if (msb_base, pi) in V3_BOSS_SLOT_CATALOG:
            recipient_is_boss = True
        # v0.27.1: NB-anchor boss promotion. NR's Night Boss arenas use
        # entity_id % 10000 == 800 for the primary boss anchor (the same
        # signature the emerge-marker bypass below relies on). For some
        # vanilla boss c-prefixes — notably c3050 Commander — the variant
        # carries an empty variant_name, so is_boss_tier_variant returns
        # False and is_boss_tier_prefix('c3050') also fails (no reward, sub-4m
        # hit height, not heritage). That left recipient_is_boss=False for
        # the actual night boss. Harmless until v0.27.0's add-randomize
        # carve-out, which keys on recipient_is_boss: in V3_ADD_RANDOMIZE_
        # ARENAS the Commander anchor was being read as an add and SWAPPED
        # OUT (seed 791285: m49_26 pi8 + m49_27 pi13 c3050 -> Watchdog /
        # Elder Lion). Promote any 800-anchor in an m48_/m49_ map to
        # boss-tier so the carve-out preserves it. Unconditional — does not
        # depend on recipient_variant being empty-named.
        if (msb_base is not None
                and (msb_base.startswith('m48_')
                     or msb_base.startswith('m49_'))
                and slot_eid > 0 and slot_eid % 10000 == 800):
            recipient_is_boss = True
        # v0.23.22: source-side emerge-marker skip. The engine already has
        # filter_emerge_variants for TARGETS (so we never write an emerge-
        # placeholder NPCParam) but no equivalent for SOURCES. A source slot
        # whose vanilla NPCParam has an empty variant_name is by FromSoft convention
        # an event-driven spawn placeholder — vanilla EMEVD owns the spawn
        # via ForceAnimationPlayback + a follow-up "is the chr still the
        # expected NPCParam" check that despawns if not. Swapping those slots
        # produces visible bugs: the event fires, the swapped chr appears
        # briefly, then despawns when the verify step finds an unexpected
        # NPCParam. User-confirmed example (seed 373504, m48_40_00_00 pi=1):
        # vanilla c2140 emerge-marker (npc_param 21400220, empty name) was
        # swapped to c2271 Crab during Morgott Night Boss. EMEVD fired "A
        # Fell Omen Has Appeared", spawned the crab, then despawned it when
        # the recognition check failed.
        #
        # Detection: source variant's variant_name is empty/whitespace. This
        # mirrors the v0.23.04.1 target-side empty-name filter at
        # pick_variant_for_tier:1726.
        if (recipient_variant is not None
                and not (recipient_variant.get('variant_name') or '').strip()):
            # v0.23.72: NB-boss-anchor bypass. NR's Night Boss arena maps
            # (m49_xx, m48_xx) consistently use entity_id ending in 800 for
            # the primary boss anchor slot — e.g. m49_10 Grafted Monarch at
            # 49100800, m49_27 Battlefield Commander at 49270800. These are
            # NOT emerge-markers; they're the actual boss chr at the actual
            # boss slot. The empty-variant_name signal is a false positive
            # caused by missing metadata in nr_all_slots.json for some
            # vanilla boss c-prefixes (data-pipeline issue to fix
            # separately — see TODO). Confirmed via user playtest seed
            # 35300, Sentient Pest expedition: m49_27 pi=13 c3050
            # Battlefield Commander was filtered here and the NB1
            # encounter failed to start (empty arena when circle closed).
            #
            # Bypass criterion: slot is in an NB arena map (m48_/m49_) AND
            # entity_id mod 10000 == 800. This is narrow enough to not
            # rescue actual emerge-markers (which sit in field/grunt slot
            # entity ranges) but covers all 16 Nightlord NB1+NB2 anchors.
            _map_base = os.path.basename(input_path)
            _is_nb_anchor = (
                (_map_base.startswith('m48_') or _map_base.startswith('m49_'))
                and slot_eid > 0
                and slot_eid % 10000 == 800
            )
            if not _is_nb_anchor:
                n_skipped_compat += 1  # bucketed with compat skips for stat purposes
                _log_unaccounted('source_emerge_marker',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        # v0.20.21: per-slot bossy-tier promotion. Forces the slot to draw
        # from boss-strength target pools regardless of source-variant
        # tagging. See V3_BOSSY_PROMOTE_SLOTS docstring.
        # v0.20.22: dict-of-modes — 'bossy' or 'boss_reward'.
        _promote_mode = V3_BOSSY_PROMOTE_SLOTS.get(
            (os.path.basename(input_path), pi))
        if _promote_mode is not None:
            recipient_is_boss = True
        _slot_require_boss_reward = (_promote_mode == 'boss_reward')

        # Non-clustered: independent roll
        if (oops_all_nb_pinned_slot is not None
                and oops_all_nb_target_cp
                and (msb_base, pi) == oops_all_nb_pinned_slot):
            # v0.24.25: surgical single-slot pin. When oops_all_nb_
            # pinned_slot=(msb, pi) is set AND this is that slot, force
            # the target. Every other slot in this run rolls normally.
            # Use case: test a specific MMV / cross-engine boss at one
            # known-stable arena slot, without confounding the result
            # with the same chr appearing at other slots that might
            # CTD. Bypasses tier/compat/exclude gates entirely — the
            # whole point is to force-test a specific placement.
            #
            # Pairs naturally with oops_all_nb_target_cp; ignores
            # oops_all_nb_marker_scope (the pin IS the marker).
            target_cp = oops_all_nb_target_cp
            target_variant = pick_variant_for_tier(
                target_cp, recipient_is_boss, prefix_variants, rng,
                tags=tags, run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        elif terrain_test_targets:
            # v0.19.6: terrain test mode — pick c-prefix purely from
            # navmesh classification, bypass all fragile/problem/resilient
            # heuristics. Used to validate that terrain status alone is
            # sufficient for broken-slot detection.
            # v0.23.51: msb_base hoisted to loop top.
            terrain_status = lookup_slot_terrain(msb_base, pi)
            # v0.19.9: V3_PROBLEM_SLOTS manual blocklist also forces Jelly.
            # User can pin specific (msb, pi) entries (e.g., known-broken
            # encampment positions) without needing a whole-map flag.
            if (msb_base, pi) in V3_PROBLEM_SLOTS:
                target_cp = terrain_test_targets['off_mesh']
            elif terrain_status == 'no_match':
                # Sentinel — keep vanilla
                continue
            elif terrain_status in ('off_mesh', 'proximity_off_mesh', 'force_off_mesh'):
                target_cp = terrain_test_targets['off_mesh']
            else:
                # on_mesh OR unknown (slot not in cache) → on_mesh target
                target_cp = terrain_test_targets['on_mesh']
            target_variant = pick_variant_for_tier(
                target_cp, recipient_is_boss, prefix_variants, rng,
                tags=tags, run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        elif oops_all_target_cp:
            # Force every slot to the chosen c-prefix; bypass compat check.
            target_cp = oops_all_target_cp
            target_variant = pick_variant_for_tier(
                target_cp, recipient_is_boss, prefix_variants, rng,
                tags=tags, run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        elif (oops_all_nb_pinned_slot is None  # v0.24.25: pinned mode is exclusive
              and (_effective_nb_target_cp := (oops_all_nb_target_cp
                                            if oops_all_nb_target_cp is not None
                                            else OOPS_ALL_NB_TARGET_CP))
              and (_effective_scope := (oops_all_nb_marker_scope
                                        if oops_all_nb_marker_scope is not None
                                        else OOPS_ALL_NB_MARKER_SCOPE))
              and (
                  # v0.24.28: starting_encampment scope. When set,
                  # match is strictly MSB-membership. Does NOT also
                  # fire on V3_BOSS_TIER_PINNED_SLOTS or variant
                  # markers — the whole point of this scope is to
                  # test ONLY the starting encampment, surgically.
                  (_effective_scope == 'starting_encampment'
                   and msb_base in V3_STARTING_ENCAMPMENT_MSBS)
                  or
                  # Other scopes (strict/broad/extended): the
                  # existing fall-through chain — BOSS_TIER_PINNED
                  # slot match OR variant-marker match for the
                  # scope's marker set.
                  (_effective_scope != 'starting_encampment'
                   and (
                       (msb_base, pi) in V3_BOSS_TIER_PINNED_SLOTS
                       or (
                           recipient_variant is not None
                           and any(
                               _m in recipient_variant.get('variant_name', '')
                               for _m in (
                                   V3_NIGHT_BOSS_STRICT_NAME_MARKERS
                                   if _effective_scope == 'strict'
                                   else V3_NIGHT_BOSS_EXTENDED_NAME_MARKERS
                                   if _effective_scope == 'extended'
                                   else V3_NIGHT_BOSS_NAME_MARKERS
                               )
                           )
                       )
                   ))
              )):
            # v0.23.31: Force every Night Boss slot to OOPS_ALL_NB_TARGET_CP.
            # v0.23.38: marker scope is now tri-valued
            # (strict/broad/extended). Extended adds Castle interior,
            # Encampment, Evergaol, Mountaintop Ruins, Duo Night Boss
            # markers — useful for CTD probes that need to hit Day-2
            # Castle slots and POI bosses.
            # v0.23.39: kwargs override module-global fallback. GUI
            # passes config-driven values via the kwarg path; CLI /
            # legacy callers without these kwargs fall back to the
            # OOPS_ALL_NB_TARGET_CP / OOPS_ALL_NB_MARKER_SCOPE module
            # globals (preserves old direct-edit-the-source workflow).
            # Non-matching slots fall through to the normal pick_target path.
            target_cp = _effective_nb_target_cp
            target_variant = pick_variant_for_tier(
                target_cp, True, prefix_variants, rng, tags=tags,
                run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        else:
            target_cp, target_variant = pick_target(
                cur_cp, tags,
                prefix_variants, prefix_count, recipient_is_boss, rng,
                target_count=target_count, slot_y=slot_y,
                slot_msb_name=os.path.basename(input_path),
                slot_pi=pi,
                slot_variant_name=(recipient_variant.get('variant_name', '')
                                   if recipient_variant else ''),
                slot_pos=slot_pos,  # v0.20.16: edge-sentinel detection
                slot_eid=slot_eid,  # v0.27.40: freeze-prone addressability gate
                slot_require_boss_reward=_slot_require_boss_reward,  # v0.20.22
                disable_resilient_filter=disable_resilient_filter,  # v0.20.35
                non_fragile_baseline_cp=non_fragile_baseline_cp,  # v0.20.38
                diagnostic_test_targets=diagnostic_test_targets,  # v0.20.42
                chaos_mode=chaos_mode,  # v0.23.11
                gates=gates,  # v0.24.21
                run_ctx=run_ctx,  # v0.24.21 (Phase 5)
            )
            if target_cp is None:
                n_skipped_compat += 1
                _log_unaccounted('no_target_found',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
            if target_count is not None:
                target_count[target_cp] = target_count.get(target_cp, 0) + 1

        swap_plan.append((pi, target_cp,
                          target_variant['npc_param_id'],
                          target_variant['think_param_id']))
        # v0.27.5: register the committed placement into per-MSB size
        # state so later slots in this MSB see it for the proximity /
        # density gates. Covers every commit path — pick_target,
        # oops_all, NB-forced, pinned — since it follows the unified
        # swap_plan.append.
        if run_ctx is not None:
            # v0.28: record the committed c-prefix as resident so later
            # slots in this MSB can recycle it (and so it counts against
            # the distinct budget). Idempotent; covers every commit path.
            #
            # v0.28.x Phase 2: add_resident_cp updates the per-cluster
            # resident set too when a POI scope is armed (begin_poi() was
            # called by the cluster-grouped swap loop). Falls back to a
            # direct msb_resident_cps.add for older RunContext snapshots.
            if hasattr(run_ctx, 'add_resident_cp'):
                run_ctx.add_resident_cp(target_cp)
            else:
                run_ctx.msb_resident_cps.add(target_cp)
            _committed_sz = _effective_size_class(target_cp, tags)
            if _committed_sz in V3_DENSITY_L_SIZE_CLASSES:
                run_ctx.register_big(_committed_sz, slot_pos)

    if run_ctx is not None:
        # v0.28.x Phase 2: close any active POI scope before end_msb.
        # end_msb() also clears POI state defensively, but closing
        # explicitly here keeps current_poi_id=None for any code between
        # the swap loop and end_msb that reads run_ctx state.
        if _pi_to_cid is not None and hasattr(run_ctx, 'end_poi'):
            run_ctx.end_poi()
        run_ctx.end_msb()  # v0.27.5: disarm per-MSB size gates
    if not swap_plan:
        with open(output_path, 'wb') as f: f.write(data)
        return (0, 0, n_skipped_compat, n_clusters)

    # v0.27.5: the v0.21 BIG_PROXIMITY and v0.23.61 DENSITY_CAP
    # swap-plan post-passes were removed here. Their work is now done
    # at placement time by Gates 8 (proximity) and 9 (density) in
    # _reject_target_for_slot — a big that would clip a neighbour or
    # bust the per-MSB budget drops out of the candidate pool and the
    # picker selects a smaller chr through its normal pipeline. Because
    # the gates never fire for reservations, a reserved big chr can no
    # longer be demoted (closes the reservation-floor-demotion bug).

    # === v0.23.66 FINAL-PASS EXTRA_BANS ENFORCEMENT ===
    # Belt-and-suspenders: scan the final swap_plan and revert any
    # entry whose (msb, pi, target_cp) lands in V3_PROBLEM_SLOT_EXTRA_BANS
    # to vanilla. This catches cases where pick_target_cp's per-slot ban
    # got bypassed by a code path I didn't anticipate (cluster picks,
    # intercept paths, demote post-passes that don't consult the ban).
    # Empirical motivation: seed 342245 v0.23.65 playtest had c5010 Hippo
    # land at m38_00 pi=51 despite the ban being in EXTRA_BANS — root
    # cause unidentified, but a final-pass check is robust regardless.
    #
    # When triggered, the slot is preserved as vanilla (entry removed
    # from swap_plan) and a trace event is logged so the failure mode is
    # visible.
    _msb_basename_for_finalpass = os.path.basename(input_path)
    _filtered_swap_plan = []
    for entry in swap_plan:
        _pi, _tcp = entry[0], entry[1]
        _bans_at_slot = V3_PROBLEM_SLOT_EXTRA_BANS.get(
            (_msb_basename_for_finalpass, _pi))
        if _bans_at_slot and _tcp in _bans_at_slot:
            _V3_TRACE_BUFFER.append({
                'event': 'FINALPASS_EXTRA_BANS_REVERT',
                'map': _msb_basename_for_finalpass,
                'pi': _pi,
                'attempted_cp': _tcp,
                'attempted_npc': entry[2],
            })
            continue  # drop this entry → slot stays vanilla
        _filtered_swap_plan.append(entry)
    swap_plan = _filtered_swap_plan

    # Step 1: ensure all target c-prefixes exist in Models section
    n_added = 0
    for cp in sorted(set(t for _, t, _, _ in swap_plan)):
        if find_model_index(data, cp) < 0:
            sib = f'W:\\CL\\data\\Model\\chr\\{cp}\\sib\\{cp}.sib'
            data, _ = add_model_entry(data, cp, sib, model_type=2)
            n_added += 1

    # Step 2: rebuild offsets after Models additions
    sections = parse_msb_sections(data)
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]
    target_to_idx = {parse_model_entry(data, eo)['name']: gi
                     for gi, eo in enumerate(models['entry_offsets'])}

    # Step 3: rewrite Parts in one pass
    out = bytearray(data)
    map_name = os.path.basename(input_path)
    # v0.23.72-late: track position shifts applied. Used by both the spoiler
    # write (each affected entry gets a 'position_shift' field) and the
    # end-of-MSB trace event.
    _pos_shifts_applied = []
    for pi, target_cp, target_npc, target_think in swap_plan:
        po = parts['entry_offsets'][pi]
        new_idx = target_to_idx[target_cp]
        old_idx = struct.unpack_from('<i', out, po + PART_OFF_MODEL_INDEX)[0]

        # v0.23.72-late: POSITION SHIFT — look up the slot's shift entry
        # (if any) and decide whether to apply it. Skipped if:
        #   - No shift entry for this (msb, pi)
        #   - Position field is past end of Part record (DummyEnemy etc.)
        #   - Position is NaN (treated as "no static position")
        #   - Part is in a cluster (cluster aesthetics > shift benefit)
        # All decisions are logged into the trace event regardless of
        # outcome so we can audit why a shift didn't apply.
        # v0.27.0: two independent contributions stack into one write:
        #   - V3_POSITION_SHIFTS slot dxyz (slot-specific geometry fix)
        #   - V3_MODEL_Y_OFFSET per-c-prefix dy (chr-specific origin fix)
        # Either may be absent; if both are, nothing is written.
        _shift_entry = lookup_position_shift(map_name, pi)
        _model_dy = lookup_model_y_offset(target_cp)
        _shift_applied = None
        _shift_skipped_reason = None
        if _shift_entry or _model_dy:
            if po + 0x400 + 12 > len(out):
                _shift_skipped_reason = 'no_position_field'
            else:
                _ox, _oy, _oz = struct.unpack_from('<fff', out, po + 0x400)
                import math as _m
                if _m.isnan(_ox) or _m.isnan(_oy) or _m.isnan(_oz):
                    _shift_skipped_reason = 'nan_position'
                else:
                    if _shift_entry:
                        _sdx, _sdy, _sdz = _shift_entry['dxyz']
                    else:
                        _sdx, _sdy, _sdz = 0.0, 0.0, 0.0
                    # model Y-offset stacks onto the slot shift's Y
                    _dx, _dy, _dz = _sdx, _sdy + _model_dy, _sdz
                    _nx, _ny, _nz = _ox + _dx, _oy + _dy, _oz + _dz
                    struct.pack_into('<fff', out, po + 0x400, _nx, _ny, _nz)
                    _shift_applied = {
                        'from': (round(_ox, 3), round(_oy, 3), round(_oz, 3)),
                        'to':   (round(_nx, 3), round(_ny, 3), round(_nz, 3)),
                        'dxyz': (_dx, _dy, _dz),
                        'slot_dxyz': (_sdx, _sdy, _sdz),
                        'model_dy': _model_dy,
                        'note': (_shift_entry.get('note', '')
                                 if _shift_entry else
                                 f'model Y-offset only ({target_cp})'),
                    }
            _pos_shifts_applied.append({
                'pi': pi,
                'target_cp': target_cp,
                'applied': _shift_applied,
                'skipped_reason': _shift_skipped_reason,
            })

        # Capture original values BEFORE overwriting (for spoiler log)
        if spoiler_entries is not None:
            orig_npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0]
            orig_cp = midx_to_cp.get(old_idx, '?')
            entity_id = (struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0]
                         if po + PART_OFF_ENTITY_ID + 4 <= len(data) else None)
            # Position field at 0x400 may be past end of some Part subtypes.
            # v0.23.72-late: read from `data` (original) not `out` (already
            # shifted above) so the spoiler shows the AUTHORED position. The
            # shift, if any, is recorded separately in 'position_shift'.
            position = None
            if po + 0x400 + 12 <= len(data):
                x, y, z = struct.unpack_from('<fff', data, po + 0x400)
                # NaN values break json.dump; treat them as missing
                import math
                if not (math.isnan(x) or math.isnan(y) or math.isnan(z)):
                    position = [round(x, 2), round(y, 2), round(z, 2)]
            new_variant = next((v for v in prefix_variants.get(target_cp, [])
                                if v.get('npc_param_id') == target_npc), None)
            is_boss = is_boss_tier_variant(new_variant) if new_variant else \
                      is_boss_tier_prefix(target_cp, tags, prefix_variants)
            # v0.23.54: tag spoiler entries with their boss-slot catalog
            # tier (or None for non-boss slots). Makes it trivial to
            # filter the spoiler for "all catalogued boss slots" or
            # "what got placed at the Castle Field Boss arena" without
            # re-classifying.
            _cat_entry = V3_BOSS_SLOT_CATALOG.get((map_name, pi))
            from_catalog_tier = _cat_entry.get('tier') if _cat_entry else None
            from_catalog_scope = _cat_entry.get('scope') if _cat_entry else None
            # v0.27.13: rolled field-slot tier. Mirrors the roll
            # pick_target_cp made for this slot (same pure function), so
            # the spoiler shows which non-catalogued slots were upgraded.
            # Annotated only on actual upgrades — base grunt rolls and
            # catalogued/boss slots omit the field (None) to keep the
            # spoiler lean, matching the in_starting_encampment pattern.
            # NOTE (merge): the uploaded oops_v3.py used `recipient_is_boss`
            # here, which is NOT in scope in the spoiler writer — a latent
            # NameError. `is_boss` (computed just above from the actual
            # placed variant) is the correct in-scope value and is what
            # the field-roll exclusion wants anyway.
            _field_roll = (field_roll_tier_for(map_name, pi)
                           if not is_boss else None)
            _entry = {
                'map':         map_name,
                'part_index':  pi,
                'entity_id':   entity_id,
                'position':    position,
                'cluster_id':  None,  # v0.26.13: cluster system removed
                'is_boss':     is_boss,
                'catalog_tier':  from_catalog_tier,
                'catalog_scope': from_catalog_scope,
                **({'field_roll': _field_roll}
                   if _field_roll in ('miniboss', 'night_boss') else {}),
                # v0.24.28: starting-encampment annotation. True when this
                # placement is inside an MSB tagged as a starting encampment
                # in data/nr_starting_encampments.json. Helps post-run
                # CTD attribution ("I crashed near spawn — what was at
                # the starting encampment?") and serves as the filter
                # for oops_all_nb_marker_scope='starting_encampment'.
                # Omitted (rather than False) when not applicable so old
                # parsers don't see new fields they don't expect.
                **({'in_starting_encampment': True}
                   if map_name in V3_STARTING_ENCAMPMENT_MSBS
                   else {}),
                'original':    {'c_prefix': orig_cp,
                                'name': _variant_name(orig_cp, orig_npc, prefix_variants),
                                'npc_param_id': orig_npc},
                'new':         {'c_prefix': target_cp,
                                'name': _variant_name(target_cp, target_npc, prefix_variants),
                                'npc_param_id': target_npc,
                                # v0.24.35: classify the variant source so
                                # spoilers visibly distinguish canonical /
                                # ghost-variant / imported-chr placements.
                                # See _classify_variant_source docstring.
                                'variant_source': _classify_variant_source(
                                    target_cp, target_npc, prefix_variants, tags)},
            }
            # v0.23.72-late: surface the position shift in the spoiler so
            # users can tell at a glance which placements were shifted and
            # by how much (vs. originals).
            if _shift_applied is not None:
                _entry['position_shift'] = {
                    'applied': True,
                    'shifted_to': list(_shift_applied['to']),
                    'dxyz': list(_shift_applied['dxyz']),
                    'note': _shift_applied['note'],
                }
            elif _shift_entry is not None and _shift_skipped_reason:
                _entry['position_shift'] = {
                    'applied': False,
                    'skipped_reason': _shift_skipped_reason,
                    'note': _shift_entry.get('note', ''),
                }
            spoiler_entries.append(_entry)
        struct.pack_into('<i', out, po + PART_OFF_MODEL_INDEX, new_idx)
        struct.pack_into('<I', out, po + PART_OFF_NPC_PARAM, target_npc)
        struct.pack_into('<I', out, po + PART_OFF_THINK_PARAM, target_think)
        # Update instance counts on old + new
        old_e = models['entry_offsets'][old_idx]; new_e = models['entry_offsets'][new_idx]
        c_old = struct.unpack_from('<i', out, old_e + 0x18)[0]
        struct.pack_into('<i', out, old_e + 0x18, c_old - 1)
        c_new = struct.unpack_from('<i', out, new_e + 0x18)[0]
        struct.pack_into('<i', out, new_e + 0x18, c_new + 1)

    # v0.23.72-late: surface the per-MSB position-shift summary into the
    # trace buffer. Empty when V3_POSITION_SHIFTS is empty (current state).
    if _pos_shifts_applied:
        _V3_TRACE_BUFFER.append({
            'event': 'POSITION_SHIFTS',
            'msb': map_name,
            'shifts': _pos_shifts_applied,
        })

    # Merchant model swap (v0.12) — post-pass that swaps the visual model
    # of merchant Parts without touching their NPCParam/ThinkParam. The
    # merchant continues to function as a merchant; it just looks
    # different. Optional, off by default.
    n_merchants_swapped = 0
    if merchant_model_swap and V3_MERCHANT_MODEL_SWAP_ENABLED:
        merchant_data, n_merchants_swapped = apply_merchant_model_swaps(
            bytes(out), rng,
            spoiler_entries=spoiler_entries,
            map_name=map_name,
            gates=gates)
        out = bytearray(merchant_data)

    # v0.24.101: Model entry compaction post-pass. After all Part swaps
    # (including merchant model swap above), remove Enemy-type Model
    # entries that have zero Part references. Reduces .chrbnd load count
    # at map load and shrinks MSB size. See V3_REMOVE_UNUSED_ENEMY_MODELS
    # for kill switch.
    #
    # v0.25.0-patch3: pass `protect_names` derived from the boss-slot
    # catalog so chrs that the boss-init EMEVD spawns dynamically
    # (SpawnNPC + chr template) survive even when their static Parts
    # were all swapped away. Catalog entries are documented as
    # arena-relevant; ambient Limveld chrs (Perfumer, Wandering Noble)
    # outside the catalog are still compacted normally.
    #
    # Empirical motivation: across all 5 audited spoilers (seeds 42,
    # 939029, 650833, 49804, 628653), m48_40 Morgott reliably had
    # c4353 (Leyndell Knight Prelude) removed because the pi=4 Part
    # was swapped to another chr — but the catalog lists c4353 at
    # pi=4 as "Leyndell Knight (Night Boss Prelude)", suggesting the
    # boss-init flow expects c4353 to remain template-available.
    # Without the protection, seed 628653 N2 stall (Tricephalos rolled
    # m48_40 Morgott as N2; boss never spawned). Documented bug at
    # emevd_patch.py:1469-1474 cites "no boss spawn, no minion wave"
    # which matches a failed-prelude-then-stalled-boss-init signature.
    if V3_REMOVE_UNUSED_ENEMY_MODELS:
        pre_compact_size = len(bytes(out))
        msb_basename = os.path.basename(input_path)
        # v0.25.0-patch3: build protect set from boss-slot catalog entries
        # for this MSB. V3_BOSS_SLOT_CATALOG is flat keyed by (msb, pi);
        # iterate and filter.
        #
        # v0.26.5-patch: skip cp-less entries. The v0.26.x terrain-arena
        # merge (_load_boss_slot_catalog) injects entries from
        # nr_terrain_arena_slots.json that lack a 'cp' key — they're
        # promoted by geometry alone, with no vanilla chr identity to
        # protect. Pre-patch this raised KeyError: 'cp' on the first
        # affected MSB (147 such entries across 30 MSBs in v0.26.x data).
        protect = {entry['cp']
                   for (msb_key, _pi), entry in V3_BOSS_SLOT_CATALOG.items()
                   if msb_key == msb_basename and 'cp' in entry}
        compact_data, removed_models, _model_remap = remove_unused_model_entries(
            bytes(out), model_type_filter=2, protect_names=protect)
        if removed_models or protect:
            if removed_models:
                out = bytearray(compact_data)
            _V3_TRACE_BUFFER.append({
                'event': 'MODEL_COMPACTION',
                'msb': msb_basename,
                'n_removed': len(removed_models),
                'bytes_saved': pre_compact_size - len(compact_data) if removed_models else 0,
                'removed_names': [r['name'] for r in removed_models],
                'protected_names': sorted(protect),  # v0.25.0-patch3
            })

    with open(output_path, 'wb') as f: f.write(bytes(out))
    return (len(swap_plan), n_added, n_skipped_compat, n_clusters)
