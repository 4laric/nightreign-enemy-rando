"""Shuffle-command orchestrator (extracted from oops_v3.py).

WHAT THIS IS
------------
`cmd_shuffle_v3_impl` is the per-run orchestrator above
shuffle_msb_v3. The CLI / GUI path looks like:

  cmd_shuffle_v3(...) [arg parsing + pool snapshot]
    -> cmd_shuffle_v3_impl(...)   [THIS FUNCTION — per-run setup]
       -> for each MSB:
            -> shuffle_msb_v3(...) [engine.shuffler]

What this function does:
  1. Resolve input/output directories, seed handling, RNG init.
  2. Run pool-cap overrides via engine.runtime.compose_pool_cap_
     overrides (per-run gate-set composition).
  3. Initialize per-run state: _V3_TRACE_BUFFER = [], _V3_RUN_SEED
     (= seed), reset the unique-placed counters / preserved-source
     log / unaccounted-vanilla log / unique-unplaced log.
  4. Call _compute_unique_reservations (engine.reservations) to
     populate the pre-pass reservation map. Honors run_ctx if one
     was passed in.
  5. For each MSB in V3_SPAWN_POOL_MSBS (and V3_DIAGNOSTIC_INVENTORY_
     MSBS in diagnostic mode), call shuffle_msb_v3 — collecting
     spoiler entries into a list.
  6. After all MSBs processed, call write_spoiler_logs to emit the
     _spoilers.json + _spoilers.md files.
  7. Optionally run run_seed_ctd_checks (per-seed CTD detection),
     copy sidecar files via SIDECAR_SUFFIXES, etc.

WHY IT WAS EXTRACTED
--------------------
408 lines — the orchestrator above the now-extracted shuffler.
Pulling it out completes the engine-layer extraction of the
shuffle pipeline. Every callee is already in engine.* or stays in
oops_v3 as a helper accessed via ns.

NS-WRITE PATTERN
----------------
Two globals (_V3_RUN_SEED, _V3_TRACE_BUFFER) get flushed via the
same `ns['X'] = X` pattern as engine.load_data. All other state
is read-only.
"""
from __future__ import annotations

import json
import os
import random
import shutil


def cmd_shuffle_v3_impl(ns, input_dir, output_dir, seed,
                          oops_all_target_cp=None,
                          merchant_model_swap=False,
                          terrain_test_targets=None,
                          multiplayer_safe=False,
                          disable_resilient_filter=False,
                          non_fragile_baseline_cp=None,
                          diagnostic_test_targets=None,
                          chaos_mode=False,
                          mount_rider_swap=False,
                          oops_all_nb_target_cp=None,
                          oops_all_nb_marker_scope=None,
                          oops_all_nb_pinned_slot=None,
                          unique_cap_overrides=None,
                          caliber_pool_extras=None,
                          caliber_pool_removals=None,
                          gates=None,
                          run_ctx=None):
    """Internal implementation — see cmd_shuffle_v3 for kwarg semantics.

    v0.24.21: `gates` parameter — the effective GateState snapshot
    yielded by apply_run_overrides in the public wrapper. When passed,
    threaded into call sites that accept gates= (currently
    apply_merchant_model_swaps; future picker migrations will extend
    this). When None, callees fall back to reading module globals —
    which are still mutated by apply_run_overrides for the duration
    of the run, so behavior is unchanged for un-threaded callees.

    Caller is responsible for save/restore of V3_EXCLUDE_PREFIXES /
    V3_HUB_MAPS / V3_GHOST_EXCLUDE_TARGET_PREFIXES around this call;
    the public cmd_shuffle_v3 wrapper handles that via
    apply_run_overrides.

    v0.23.72-late: dropped the long-vestigial `mode='loose'` parameter
    (placement chain has been universal-pool/post-filter since v0.20.0;
    mode never reached any code that branched on its value). Also no
    longer calls build_compat_lookups (its outputs were unused)."""
    # Bind module-level deps into locals. Two globals
    # (_V3_RUN_SEED, _V3_TRACE_BUFFER) get flushed to ns
    # at their write sites below (see flush comments).
    # Everything else is read-only.
    #
    # Flush targets (mutated by this function):
    _V3_RUN_SEED = ns['_V3_RUN_SEED']
    _V3_TRACE_BUFFER = ns['_V3_TRACE_BUFFER']
    # V3_* read-only state:
    V3_DIAGNOSTIC_INVENTORY_MSBS = ns['V3_DIAGNOSTIC_INVENTORY_MSBS']
    V3_ENGINE_FINGERPRINT = ns['V3_ENGINE_FINGERPRINT']
    V3_ENGINE_VERSION = ns['V3_ENGINE_VERSION']
    V3_EXCLUDE_PREFIXES = ns['V3_EXCLUDE_PREFIXES']
    V3_EXCLUDE_TARGET_PREFIXES = ns['V3_EXCLUDE_TARGET_PREFIXES']
    V3_GHOST_EXCLUDE_TARGET_PREFIXES = ns['V3_GHOST_EXCLUDE_TARGET_PREFIXES']
    V3_HUB_MAPS = ns['V3_HUB_MAPS']
    V3_PIPELINE_METADATA = ns['V3_PIPELINE_METADATA']
    V3_SOTE_MODE = ns['V3_SOTE_MODE']
    V3_SPAWN_POOL_MSBS = ns['V3_SPAWN_POOL_MSBS']
    V3_UNIQUE_TARGET_CAPS = ns['V3_UNIQUE_TARGET_CAPS']
    # _V3_* read-only state:
    _V3_PRESERVED_SOURCE_LOG = ns['_V3_PRESERVED_SOURCE_LOG']
    _V3_UNACCOUNTED_VANILLA_LOG = ns['_V3_UNACCOUNTED_VANILLA_LOG']
    _V3_UNIQUE_PLACED_COUNTS = ns['_V3_UNIQUE_PLACED_COUNTS']
    _V3_UNIQUE_RESERVATIONS = ns['_V3_UNIQUE_RESERVATIONS']
    _V3_UNIQUE_UNPLACED_LOG = ns['_V3_UNIQUE_UNPLACED_LOG']
    # Underscore helpers:
    _check_cancel = ns['_check_cancel']
    _compute_unique_reservations = ns['_compute_unique_reservations']
    _emit_msb_part_inventory_trace = ns['_emit_msb_part_inventory_trace']
    _msb_has_pinned_slots = ns['_msb_has_pinned_slots']
    _v3_dropped_from_excludes = ns['_v3_dropped_from_excludes']
    # UPPER constants:
    OOPS_ALL_NB_MARKER_SCOPE = ns['OOPS_ALL_NB_MARKER_SCOPE']
    OOPS_ALL_NB_TARGET_CP = ns['OOPS_ALL_NB_TARGET_CP']
    SIDECAR_SUFFIXES = ns['SIDECAR_SUFFIXES']
    # Public helpers / module functions:
    RunContext = ns['RunContext']
    build_per_prefix_data = ns['build_per_prefix_data']
    compose_pool_cap_overrides = ns['compose_pool_cap_overrides']
    load_data = ns['load_data']
    parse_model_entry = ns['parse_model_entry']
    parse_msb_sections = ns['parse_msb_sections']
    run_seed_ctd_checks = ns['run_seed_ctd_checks']
    shuffle_msb_v3 = ns['shuffle_msb_v3']
    write_spoiler_logs = ns['write_spoiler_logs']

    # v0.23.57: capture the input dir as soon as we have it. Other diagnostic
    # fields (input_msb_listing, msb_results, spawn_pool_*) get populated as
    # the run progresses. dcx_batch may have already set 'in_dcx_dir' and
    # 'spawn_pool_*' before calling us — preserve those.
    V3_PIPELINE_METADATA.setdefault('vanilla_dir', input_dir)
    rng = random.Random(seed)
    # v0.27.13: expose the run seed for field-slot tier rolls (a pure
    # function of seed + slot identity — see field_roll_tier_for).
    # (global decl removed — engine version flushes to ns instead)
    _V3_RUN_SEED = seed
    ns['_V3_RUN_SEED'] = _V3_RUN_SEED  # flush to caller namespace
    roster, tags = load_data()
    # v0.26.x: pool/cap overrides MUST be applied here — AFTER the impl's
    # own load_data() — not in the cmd_shuffle_v3-level apply_run_overrides
    # context manager. load_data folds pack-loader caliber/cap additions
    # into the gate sets, which clobbers any subtractive override applied
    # before it ran. See engine/runtime.compose_pool_cap_overrides for the
    # full rationale. Restoration is still the outer apply_run_overrides
    # CM's job (both gate sets are in its _OWNED_MODULE_FIELDS).
    if unique_cap_overrides or caliber_pool_extras or caliber_pool_removals:
        compose_pool_cap_overrides(
            unique_cap_overrides=unique_cap_overrides,
            caliber_pool_extras=caliber_pool_extras,
            caliber_pool_removals=caliber_pool_removals)
    prefix_variants, prefix_count = build_per_prefix_data(roster)

    # v0.23.39: NB target may come via kwargs (GUI) OR module global (CLI).
    # Resolve the effective values once for use in mode_label / spoiler emit.
    _eff_nb_target = (oops_all_nb_target_cp if oops_all_nb_target_cp is not None
                      else OOPS_ALL_NB_TARGET_CP)
    _eff_nb_scope = (oops_all_nb_marker_scope if oops_all_nb_marker_scope is not None
                     else OOPS_ALL_NB_MARKER_SCOPE)

    if terrain_test_targets:
        mode_label = (f"Terrain test (on_mesh→{terrain_test_targets['on_mesh']}, "
                      f"off_mesh→{terrain_test_targets['off_mesh']})")
    elif oops_all_target_cp:
        mode_label = f'Oops! All {oops_all_target_cp}'
    elif _eff_nb_target:
        mode_label = (f'Oops! All NB ({_eff_nb_target}, '
                      f'scope={_eff_nb_scope})')
    else:
        mode_label = 'Standard'
    # v0.19.22: print engine version up front so log scrubs reveal stale
    # installs immediately. If the GUI says v0.19.22 but this line says
    # v0.19.21, there's a stale .pyc / wrong-folder loading issue.
    print(f"Engine: {V3_ENGINE_VERSION}  ({V3_ENGINE_FINGERPRINT})")

    # Reset run-scoped diagnostic state.
    # (global decl removed — engine version flushes to ns instead)
    _V3_TRACE_BUFFER = []  # v0.19.24: reset buffer (gets dumped into spoiler)
    ns['_V3_TRACE_BUFFER'] = _V3_TRACE_BUFFER  # flush to caller namespace
    _V3_PRESERVED_SOURCE_LOG.clear()  # v0.20.18
    _V3_UNACCOUNTED_VANILLA_LOG.clear()  # v0.20.19

    # v0.20.2: data integrity check — log the loaded tier for each FI cp.
    # If a stale tags.json (still has cluster_member tier for these) is
    # loaded, the FI cps would be filtered out by tier-preserve. The
    # cluster_member compat shim in V3_FIELD_STRENGTH_TIERS makes this
    # not-fatal, but we log the loaded values so the user can confirm
    # they're running the v0.20+ tags or the legacy ones.
    integrity = {cp: tags.get(cp, {}).get('tier', '<missing>')
                 for cp in ['c5110', 'c4181', 'c3610', 'c3620', 'c4481',
                            'c4200', 'c4201', 'c4660', 'c4580']}
    _V3_TRACE_BUFFER.append({'event': 'TAGS_INTEGRITY', 'tiers': integrity})
    # v0.20.3: log if any FI cps were defensively removed from exclude sets
    # at module load. If this list is non-empty, the user has a stale .pyc
    # in __pycache__ that was loaded with old buggy excludes.
    _V3_TRACE_BUFFER.append({
        'event': 'EXCLUDE_INTEGRITY',
        'fi_cps_in_excludes_at_load': list(_v3_dropped_from_excludes),
        'pyc_cleaned': bool(_v3_dropped_from_excludes),
    })
    # v0.20.4: snapshot exact contents of all three exclude sets so we can
    # see whether they're mutated between module-load (when EXCLUDE_INTEGRITY
    # records "clean") and pick_target_cp call time. v0.20.3 showed the
    # paradox: empty cleanup list AND FI cps drop at after_excludes anyway.
    # If these snapshots show FI cps in the sets, mutation happened between
    # load and run-start. If they don't, mutation is happening AFTER this
    # snapshot but before pick_target_cp's exclude line.
    _V3_TRACE_BUFFER.append({
        'event': 'EXCLUDE_SNAPSHOT_AT_RUN_START',
        'V3_EXCLUDE_PREFIXES': sorted(V3_EXCLUDE_PREFIXES),
        'V3_EXCLUDE_TARGET_PREFIXES': sorted(V3_EXCLUDE_TARGET_PREFIXES),
        'V3_GHOST_EXCLUDE_TARGET_PREFIXES': sorted(V3_GHOST_EXCLUDE_TARGET_PREFIXES),
        'fi_in_any': {
            cp: (cp in V3_EXCLUDE_PREFIXES
                 or cp in V3_EXCLUDE_TARGET_PREFIXES
                 or cp in V3_GHOST_EXCLUDE_TARGET_PREFIXES)
            for cp in ('c5110', 'c4181', 'c3610', 'c3620')
        },
    })

    print(f"v3 vanilla-aware shuffle  seed={seed}  mode={mode_label}")
    print(f"Per-prefix data: {len(prefix_variants)} c-prefixes with usable variants")


    # v0.23.07: Unique-target reservation pre-pass. Walks all input MSBs,
    # picks one or two quality slots per V3_UNIQUE_TARGET_CAPS entry. Must
    # run AFTER tags/roster load (uses swap compat scoring) but
    # BEFORE per-MSB shuffle loop (so reservations are visible to
    # pick_target_cp).
    #
    # v0.24.22 (Phase 5.5): RunContext flip. cmd_shuffle_v3 used to call
    # _reset_unique_run_state() to clear the module-level
    # _V3_UNIQUE_RESERVATIONS / _V3_UNIQUE_PLACED_COUNTS /
    # _V3_UNIQUE_UNPLACED_LOG dicts at the top of each run. Phase 5
    # introduced RunContext as an OPTIONAL alternative — predicate
    # functions accept run_ctx=None and fall back to module dicts. The
    # flip: construct a fresh RunContext here unless one was passed in
    # explicitly (legacy call paths or tests), and thread it through to
    # _compute_unique_reservations + the per-MSB shuffle loop. Module
    # dicts still get a final back-copy at end-of-run for spoiler-emit
    # observability (see ~line 11385), but are no longer authoritative
    # mid-run. Concurrent shuffles are now race-free as long as each
    # gets its own RunContext.
    if run_ctx is None:
        run_ctx = RunContext.fresh()
    else:
        # Caller passed an explicit RunContext (e.g. a test). Reset its
        # state so this is a clean run, but don't replace the object —
        # the caller is holding a reference.
        run_ctx.reset()
    # Keep module dicts in sync at run-start for downstream code paths
    # that haven't been migrated. The end-of-run back-copy at the
    # spoiler emit reconciles them.
    _V3_UNIQUE_RESERVATIONS.clear()
    _V3_UNIQUE_PLACED_COUNTS.clear()
    _V3_UNIQUE_UNPLACED_LOG.clear()
    if V3_UNIQUE_TARGET_CAPS and not oops_all_target_cp:
        # Skip in oops_all mode — that mode bypasses pool selection
        # entirely, so reservations are meaningless. Same reasoning for
        # diagnostic_test_targets / non_fragile_baseline_cp paths.
        if not (diagnostic_test_targets or non_fragile_baseline_cp):
            _compute_unique_reservations(input_dir, tags, prefix_variants, rng,
                                          run_ctx=run_ctx)

    os.makedirs(output_dir, exist_ok=True)
    total_files = total_swaps = total_added = total_skipped_compat = total_passthrough = 0
    target_count = {}  # cumulative target c-prefix placements across all maps
    total_clusters = 0
    n_parse_fail = 0
    spoiler_entries = []  # accumulated across all maps
    # v0.23.57: build the input MSB listing for diagnostics. We capture this
    # BEFORE the per-MSB loop so even an early-failing run records what was
    # in scope. spawn_pool_in_input answers "did the file we expected to
    # process actually exist in the input dir?" (True/False per pool MSB).
    _input_listing = sorted(f for f in os.listdir(input_dir) if f.endswith('.msb'))
    V3_PIPELINE_METADATA['input_msb_count'] = len(_input_listing)
    V3_PIPELINE_METADATA['input_msb_listing'] = _input_listing
    V3_PIPELINE_METADATA['spawn_pool_in_input'] = {
        b + '.msb': (b + '.msb') in set(_input_listing)
        for b in V3_SPAWN_POOL_MSBS
    }
    V3_PIPELINE_METADATA['msb_results'] = {}
    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith('.msb'): continue
        # v0.19.21: check for cancellation at each map boundary. Latency
        # is one map's processing time (~1-3 seconds typical). Output
        # directory will contain whatever was processed before cancel.
        _check_cancel()
        ip = os.path.join(input_dir, fname)
        op = os.path.join(output_dir, fname)

        # v0.23.68: hub MSBs without pinned slots get full passthrough;
        # hubs WITH pinned slots fall through to shuffle_msb_v3 in
        # pinned-only mode (only listed Parts get randomized, all others
        # stay vanilla — preserves NPC dialogues, quest triggers, etc.).
        _is_hub = fname in V3_HUB_MAPS
        _hub_pinned_mode = _is_hub and _msb_has_pinned_slots(fname)
        if _is_hub and not _hub_pinned_mode:
            shutil.copy(ip, op)
            total_passthrough += 1
            V3_PIPELINE_METADATA['msb_results'][fname] = 'hub_passthrough'
            # v0.23.68: even though we're passing through this hub
            # unchanged, dump its Part inventory if the user has flagged
            # this MSB for diagnostics (V3_DIAGNOSTIC_INVENTORY_MSBS).
            # Lets the user identify boss-tier interior pi indices to
            # add to V3_BOSS_TIER_PINNED_SLOTS without having to flip
            # the hub out of passthrough.
            if fname in V3_DIAGNOSTIC_INVENTORY_MSBS:
                try:
                    with open(ip, 'rb') as _fp:
                        _hub_data = _fp.read()
                    _hub_sections = parse_msb_sections(_hub_data)
                    _hub_models = _hub_sections[0]
                    _hub_midx_to_cp = {}
                    for _gi, _eo in enumerate(_hub_models['entry_offsets']):
                        _info = parse_model_entry(_hub_data, _eo)
                        _hub_midx_to_cp[_gi] = _info.get('name', '')
                    _hub_parts = next(s for s in _hub_sections
                                       if s['name'] == 'PARTS_PARAM_ST')
                    _hub_msb_base = fname[:-4] if fname.endswith('.dcx') else fname
                    _emit_msb_part_inventory_trace(
                        _hub_data, _hub_parts, _hub_midx_to_cp, _hub_msb_base)
                except Exception:
                    pass  # diagnostic best-effort; never block passthrough
            continue

        res = shuffle_msb_v3(ip, op, rng, tags, prefix_variants, prefix_count,
                              spoiler_entries=spoiler_entries,
                              oops_all_target_cp=oops_all_target_cp,
                              target_count=target_count,
                              merchant_model_swap=merchant_model_swap,
                              terrain_test_targets=terrain_test_targets,
                              disable_resilient_filter=disable_resilient_filter,
                              non_fragile_baseline_cp=non_fragile_baseline_cp,
                              diagnostic_test_targets=diagnostic_test_targets,
                              chaos_mode=chaos_mode,
                              mount_rider_swap=mount_rider_swap,
                              oops_all_nb_target_cp=oops_all_nb_target_cp,
                              oops_all_nb_marker_scope=oops_all_nb_marker_scope,
                              oops_all_nb_pinned_slot=oops_all_nb_pinned_slot,
                              pinned_only_in_hub=_hub_pinned_mode,
                              gates=gates,
                              run_ctx=run_ctx)
        if res is None:
            shutil.copy(ip, op)
            n_parse_fail += 1
            V3_PIPELINE_METADATA['msb_results'][fname] = 'parse_fail'
        else:
            n_swaps, n_added, n_skipped, n_clust = res
            # v0.25.5: byte-identical passthrough for zero-change MSBs.
            # Bug surfaced in v0.25.4 with Gaping Jaw N1 fail-to-start
            # (seeds 349984, 755964): both m48_90 and m49_17 arenas had
            # n_swaps=0/n_added=0 (preserve_primary via v0.25.1 role
            # catalog) and were running through the full MSB recompile
            # pipeline — parse_msb_sections → rebuild offsets → write
            # bytes(out) — even though `out` was a vanilla copy of `data`.
            # The recompilation output evidently isn't byte-identical to
            # the input file (subtle differences in section padding,
            # offset table emission, or merchant-pass byte-handling), and
            # the boss-init for these arenas reads the MSB at a level
            # that's sensitive to those byte differences. Result: arena
            # loads, but the EnableCharacter() / boss-init chain never
            # fires; player walks into an empty room.
            #
            # The fix: when no actual changes happened (no swaps, no
            # model adds, no cluster moves), overwrite the output with
            # a byte-copy of the input. Guarantees the output file is
            # byte-identical to vanilla NR, matching what the boss-init
            # chain expects. No risk of regressing non-zero-change MSBs:
            # those still go through the recompile pipeline normally
            # (their content is meant to be different from vanilla, so
            # byte-drift from recompilation doesn't matter).
            #
            # n_skipped_compat is NOT checked — that just counts Parts
            # rejected by the preserve gates and doesn't mutate the
            # binary. Only the three change-counts that can mutate `out`
            # are gating: n_swaps (Parts modified), n_added (models
            # appended), n_clust (cluster post-pass moves).
            if n_swaps == 0 and n_added == 0 and n_clust == 0:
                shutil.copy(ip, op)
                _V3_TRACE_BUFFER.append({
                    'event': 'ZERO_CHANGE_PASSTHROUGH',
                    'msb': fname,
                    'reason': 'shuffle_msb_v3 reported no changes — byte-copying input to avoid recompilation drift',
                })
            total_files += 1
            total_swaps += n_swaps
            total_added += n_added
            total_skipped_compat += n_skipped
            total_clusters += n_clust
            # v0.23.57: store result tuple as a tagged dict so JSON
            # consumers can read fields by name.
            V3_PIPELINE_METADATA['msb_results'][fname] = {
                'n_swaps':         n_swaps,
                'n_models_added':  n_added,
                'n_skipped_compat': n_skipped,
                'n_clusters':      n_clust,
                'mode': ('hub_pinned_only' if _hub_pinned_mode else 'shuffled'),
            }

        # Always copy sidecar
        for suffix in SIDECAR_SUFFIXES:
            sc = ip + suffix
            if os.path.exists(sc):
                shutil.copy(sc, op + suffix)
                break

    print(f"\nProcessed {total_files} files, {total_swaps} swaps, {total_added} new model entries")
    print(f"Skipped (no compat targets found): {total_skipped_compat}")
    print(f"Hub passthrough: {total_passthrough}, Parse failures: {n_parse_fail}")

    # v0.23.57: build the spawn-pool diagnostic summary. For every MSB in
    # V3_SPAWN_POOL_MSBS, record:
    #   - was_in_input: did we see this filename in the input dir?
    #   - was_processed: did shuffle_msb_v3 run on it (vs. hub-passthrough/skip)?
    #   - parse_status: ok / parse_fail / not_processed
    #   - n_swaps: 0 if not processed or no swaps, otherwise count
    # This is the high-signal block the user asked us to capture so we can
    # see exactly what happened to each rotation-source MSB.
    _spawn_pool_results = {}
    for pool_base in V3_SPAWN_POOL_MSBS:
        pool_msb = pool_base + '.msb'
        was_in_input = V3_PIPELINE_METADATA['spawn_pool_in_input'].get(pool_msb, False)
        result = V3_PIPELINE_METADATA['msb_results'].get(pool_msb)
        if result is None:
            status = 'not_processed' if was_in_input else 'not_in_input'
            n_swaps = 0
        elif result == 'parse_fail':
            status = 'parse_fail'
            n_swaps = 0
        elif result == 'hub_passthrough':
            status = 'hub_passthrough'
            n_swaps = 0
        elif isinstance(result, dict):
            status = 'ok'
            n_swaps = result.get('n_swaps', 0)
        else:
            status = f'unknown_result:{type(result).__name__}'
            n_swaps = 0
        _spawn_pool_results[pool_msb] = {
            'was_in_input':   was_in_input,
            'status':         status,
            'n_swaps':        n_swaps,
            'description':    V3_SPAWN_POOL_MSBS[pool_base],
        }
    V3_PIPELINE_METADATA['spawn_pool_results'] = _spawn_pool_results

    # Write spoiler logs
    if spoiler_entries:
        # v0.24.22 (Phase 5.5): back-copy run_ctx state into the module
        # dicts so write_spoiler_logs's existing reads (line ~11423-11427)
        # see this run's results. The module dicts are no longer
        # authoritative during the run — run_ctx is — but write_spoiler_logs
        # hasn't been migrated to take a run_ctx parameter directly, so
        # this is the seam. Future: thread run_ctx into write_spoiler_logs
        # and drop the back-copy.
        _V3_UNIQUE_RESERVATIONS.clear()
        _V3_UNIQUE_RESERVATIONS.update(run_ctx.unique_reservations)
        _V3_UNIQUE_PLACED_COUNTS.clear()
        _V3_UNIQUE_PLACED_COUNTS.update(run_ctx.unique_placed_counts)
        _V3_UNIQUE_UNPLACED_LOG.clear()
        _V3_UNIQUE_UNPLACED_LOG.extend(run_ctx.unique_unplaced_log)
        write_spoiler_logs(output_dir, spoiler_entries, seed,
                           multiplayer_safe=multiplayer_safe,
                           sote_mode=V3_SOTE_MODE,
                           disable_resilient_filter=disable_resilient_filter,
                           non_fragile_baseline_cp=non_fragile_baseline_cp,
                           diagnostic_test_targets=diagnostic_test_targets,
                           oops_all_nb_target_cp=_eff_nb_target,
                           oops_all_nb_marker_scope=_eff_nb_scope,
                           oops_all_nb_pinned_slot=oops_all_nb_pinned_slot)
        print(f"Spoiler logs: {os.path.join(output_dir, '_spoilers.json')} "
              f"({len(spoiler_entries)} entries)")
        print(f"             {os.path.join(output_dir, '_spoilers.md')}")

        # v0.27.34: run the seed CTD-risk checker on every generated seed.
        # Static audit of the finished placement set against known crash
        # signatures. Findings are written to _ctd_risk.json and summarized
        # to the console. Non-fatal: a flagged seed still gets written (the
        # user decides whether to reroll), but the risk is surfaced now.
        _ctd_findings = run_seed_ctd_checks(spoiler_entries, tags)
        _ctd_path = os.path.join(output_dir, '_ctd_risk.json')
        try:
            with open(_ctd_path, 'w', encoding='utf-8') as _cf:
                json.dump({'seed': seed,
                           'engine': V3_ENGINE_FINGERPRINT,
                           'finding_count': len(_ctd_findings),
                           'findings': _ctd_findings}, _cf, indent=2)
        except OSError:
            pass
        if _ctd_findings:
            _n_ctd = sum(1 for f in _ctd_findings if f.get('severity') == 'ctd')
            print(f"*** CTD RISK CHECK: {len(_ctd_findings)} finding(s) "
                  f"({_n_ctd} ctd-severity) — see {_ctd_path} ***")
            for f in _ctd_findings:
                print(f"      [{f.get('severity')}] {f.get('map')} "
                      f"pi={f.get('part_index')} eid={f.get('entity_id')}: "
                      f"{f.get('detail')}")
        else:
            print(f"CTD risk check: clean ({os.path.basename(_ctd_path)})")
