"""Spoiler-log writer (extracted from oops_v3.py).

WHAT THIS IS
------------
The function `write_spoiler_logs` emits two files at the end of a run:

  _spoilers.json  machine-readable, full detail (every placement,
                  diagnostic_trace buffer, unique reservation map,
                  unaccounted-vanilla log, preserved-source log,
                  unique-placed counts).

  _spoilers.md    human-readable summary organized by map, with
                  per-section tables for boss/cluster/field swaps.

Both files share an engine_version + engine_fingerprint header so a
spoiler can be matched back to the build that produced it.

WHY IT WAS EXTRACTED
--------------------
424 lines in the host module — pure output formatting (no state
mutation), self-contained, and well-shaped for extraction. Moving it
shrinks oops_v3.py and gives the spoiler logic its own testable
seam.

The function takes its module namespace (`ns`) as the first
argument — same pattern as engine.rejection. The caller passes
`globals()`; this loader binds the V3_* state and the six per-run
`_V3_*` mutable log/counter dicts into locals at the top of the
function body, so the rest of the body reads identically to the
pre-extraction source.

NOTES ON `__file__`
-------------------
The function uses `os.path.dirname(os.path.abspath(__file__))` to
locate the project directory for the spoiler archive. After
extraction, `__file__` resolves to engine/spoilers.py — wrong
directory. The shim in oops_v3.py passes `__file__` explicitly via
the namespace dict so the archive lands in the same place it always
did (the project root that contains oops_v3.py).
"""
from __future__ import annotations

import json
import os


def write_spoiler_logs(ns, output_dir, entries, seed,
                        multiplayer_safe=False,
                        sote_mode=False,
                        disable_resilient_filter=False,
                        non_fragile_baseline_cp=None,
                        diagnostic_test_targets=None,
                        oops_all_nb_target_cp=None,
                        oops_all_nb_marker_scope=None,
                        oops_all_nb_pinned_slot=None):
    """Write _spoilers.json (full) + _spoilers.md (organized summary).

    v0.23.72-late: dropped vestigial `mode` parameter (was always 'loose'
    since v0.20.0's universal-pool refactor).

    multiplayer_safe: bool — surfaced into the spoiler so users can
    confirm what mode the run used. Defaults to False so any caller
    who hasn't been updated still works (older callers from CLI tools
    or scripts won't pass the flag, and a False default is fine for
    those — the spoiler will say "OFF" which matches the engine's
    default behavior when no kwarg is set).

    disable_resilient_filter: bool — v0.20.35 diagnostic mode marker.
    v0.20.37: when True, fragile slots use UNTESTED-only filter
    (pool - RESILIENT - SENSITIVE). Surfaced in spoiler so freeze
    reports tied to a diagnostic run are unambiguously identifiable.

    non_fragile_baseline_cp: str | None — v0.20.38 diagnostic-mode
    companion. When set (e.g. 'c4373' Foot Soldier), every non-
    fragile slot is forced to that c-prefix instead of being randomized.
    Combined with disable_resilient_filter, this means the world is
    visually uniform at safe slots, so any non-baseline enemy the
    user sees in-game is by definition a fragile-slot test. Surfaced
    so the user can confirm the run was a diagnostic-instrumented one.
    """
    # Bind module-level dependencies into locals. The body
    # below reads identically to the original pre-extraction
    # code; locals also use LOAD_FAST opcodes (faster than
    # LOAD_GLOBAL on hot paths).
    #
    # V3_* state — read-only configuration:
    V3_BOSS_SLOT_CATALOG = ns['V3_BOSS_SLOT_CATALOG']
    V3_BOSS_SLOT_CATALOG_META = ns['V3_BOSS_SLOT_CATALOG_META']
    V3_ENGINE_FINGERPRINT = ns['V3_ENGINE_FINGERPRINT']
    V3_ENGINE_VERSION = ns['V3_ENGINE_VERSION']
    V3_PIPELINE_METADATA = ns['V3_PIPELINE_METADATA']
    V3_SPAWN_POOL_MSBS = ns['V3_SPAWN_POOL_MSBS']
    V3_TRACKED_C_PREFIXES = ns['V3_TRACKED_C_PREFIXES']
    V3_UNIQUE_TARGET_CAPS = ns['V3_UNIQUE_TARGET_CAPS']
    # Per-run mutable log/counter state populated during shuffle:
    _V3_PRESERVED_SOURCE_LOG = ns['_V3_PRESERVED_SOURCE_LOG']
    _V3_TRACE_BUFFER = ns['_V3_TRACE_BUFFER']
    _V3_UNACCOUNTED_VANILLA_LOG = ns['_V3_UNACCOUNTED_VANILLA_LOG']
    _V3_UNIQUE_PLACED_COUNTS = ns['_V3_UNIQUE_PLACED_COUNTS']
    _V3_UNIQUE_RESERVATIONS = ns['_V3_UNIQUE_RESERVATIONS']
    _V3_UNIQUE_UNPLACED_LOG = ns['_V3_UNIQUE_UNPLACED_LOG']
    # Helper functions:
    _data_path = ns['_data_path']
    # Caller's __file__ (used for spoiler archive dir lookup —
    # must resolve to oops_v3.py, not engine/spoilers.py).
    __file__ = ns['__file__']
    # v0.20.2 fix: tags is needed by the markdown tracker section but
    # not in this function's scope. Load it here.
    try:
        with open(_data_path('nr_enemy_tags.json'), 'r', encoding='utf-8') as f:
            tags = json.load(f)
    except Exception:
        tags = {}
    # JSON: machine-readable, full detail
    json_path = os.path.join(output_dir, '_spoilers.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            # v0.19.22: explicit engine version so spoilers self-identify the
            # build that produced them. Add a hash of a fix-marker string so
            # bad cache loads (stale .pyc) can be detected from the header.
            'engine_version': V3_ENGINE_VERSION,
            'engine_fingerprint': V3_ENGINE_FINGERPRINT,
            # v0.19.24: dump the trace buffer (TAGS_INTEGRITY, EXCLUDE_INTEGRITY,
            # FI-drop events, etc.) so we can see what happened without
            # needing the GUI log.
            'diagnostic_trace': list(_V3_TRACE_BUFFER),
            'seed': seed,
            # v0.23.72-late: 'mode' field dropped — the parameter was removed
            # from write_spoiler_logs's signature in the same revision (was
            # always 'loose' since v0.20.0's universal-pool refactor). The
            # body reference here was missed and produced NameError at
            # spoiler-write time. Confirmed no Python consumer reads this
            # spoiler key; historical spoilers showed mode='loose' uniformly,
            # so the field carried zero signal.
            # v0.20.27: explicit multiplayer_safe kwarg from cmd_shuffle_v3.
            # Was structurally inferred in v0.20.26 because the GUI mutated
            # V3_GHOST_EXCLUDE_TARGET_PREFIXES directly; that mutation now
            # happens engine-side under the kwarg, so we just record the
            # kwarg value.
            'multiplayer_safe': multiplayer_safe,
            # v0.23.31: oops-all-NB target — emitted so playtests are tagged.
            'oops_all_nb_target_cp': oops_all_nb_target_cp,
            'oops_all_nb_use_strict_markers': (oops_all_nb_marker_scope == 'strict'),
            'oops_all_nb_marker_scope': oops_all_nb_marker_scope,
            # v0.24.25: pinned-slot mode — when set, only one specific
            # (msb, pi) gets oops_all_nb_target_cp; all other slots roll
            # normally. Stored as [msb, pi] in JSON (tuples → lists).
            'oops_all_nb_pinned_slot': (list(oops_all_nb_pinned_slot)
                                         if oops_all_nb_pinned_slot is not None
                                         else None),
            # v0.23.54: boss-slot catalog summary — number of catalogued boss
            # slots in this build. Helps verify the catalog is loaded (a 0
            # here means data/nr_boss_slots.json wasn't found or failed to
            # parse, in which case OOPS_ALL_NB falls back to marker
            # heuristics for everything not in V3_BOSS_TIER_PINNED_SLOTS).
            'boss_slot_catalog_total': len(V3_BOSS_SLOT_CATALOG),
            'boss_slot_catalog_meta':  V3_BOSS_SLOT_CATALOG_META,
            # v0.23.56: spawn-pool MSB inventory total. Independent of the
            # main catalog — these are the rotation-source MSBs the rando
            # auto-includes when spawn_pool_source_dir is set in the GUI.
            # See V3_SPAWN_POOL_MSBS docstring for the list.
            'spawn_pool_msbs_total': len(V3_SPAWN_POOL_MSBS),
            # v0.23.57: full pipeline-metadata dump. dcx_batch + the engine
            # cooperatively populate V3_PIPELINE_METADATA as the run
            # progresses. Includes input/output paths, auto-include results,
            # input MSB listing, per-MSB result tuples, and per-spawn-pool
            # status. Use this to debug runs where MSBs you expected to be
            # processed didn't end up in the spoiler.
            'pipeline_metadata': dict(V3_PIPELINE_METADATA),
            # v0.20.35: diagnostic flag — RESILIENT whitelist disabled at
            # fragile slots when True. Used to expand SENSITIVE based on
            # observed freezes. Identifies a diagnostic run vs production.
            'disable_resilient_filter': disable_resilient_filter,
            # v0.20.38: diagnostic-mode companion. When set, non-fragile
            # slots were forced to this single c-prefix (e.g. 'c4373' Foot
            # Soldier) for visual-baseline diagnostic runs. Anything visible
            # in-game that isn't this c-prefix is, by construction, a
            # fragile-slot test placement.
            'non_fragile_baseline_cp': non_fragile_baseline_cp,
            # v0.20.42: diagnostic batch — when set, fragile slots were
            # restricted to ONLY these c-prefixes. Critical for CTD
            # attribution since the spoiler tells you which c-prefixes
            # could possibly be the cause.
            'diagnostic_test_targets': (sorted(diagnostic_test_targets)
                                         if diagnostic_test_targets else None),
            # v0.23.07: unique-target reservation state. Three sub-keys:
            # caps: the active cap dict at run time (so a regenerated
            #   spoiler from the same seed but different caps is
            #   identifiable). placed_counts: actual placements per
            #   capped cp at end of run. unplaced: list of cps that
            #   couldn't get a reservation, with the reason (so the user
            #   can decide whether to relax criteria for those cps).
            'unique_caps': dict(V3_UNIQUE_TARGET_CAPS),
            # v0.27.13: _V3_UNIQUE_PLACED_COUNTS now contains both string
            # c-prefix keys AND (c_prefix, group_name) tuple keys from the
            # variant-group accounting. JSON keys must be strings, so a
            # tuple key is rendered "c_prefix/group_name" (the same
            # display form used in the reservation-pass log lines). String
            # c-prefix keys pass through unchanged.
            'unique_placed_counts': {
                (f'{k[0]}/{k[1]}' if isinstance(k, tuple) else k): v
                for k, v in _V3_UNIQUE_PLACED_COUNTS.items()
            },
            'unique_unplaced': list(_V3_UNIQUE_UNPLACED_LOG),
            # v0.27.13: a reservation VALUE is either a cp string
            # (c-prefix floor) or a (cp, group) tuple (variant-group
            # floor). Emit cp always, plus group when the reservation
            # was group-scoped, so the spoiler distinguishes the two.
            'unique_reservations': [
                {'msb': k[0], 'pi': k[1],
                 'cp': (v[0] if isinstance(v, tuple) else v),
                 **({'group': v[1]} if isinstance(v, tuple) else {})}
                for k, v in sorted(_V3_UNIQUE_RESERVATIONS.items())
            ],
            'entry_count': len(entries),
            'entries': entries,
        }, f, indent=2, ensure_ascii=False)

    # Markdown: organized summary
    md_path = os.path.join(output_dir, '_spoilers.md')
    boss_entries = [e for e in entries if e['is_boss']]
    cluster_entries = [e for e in entries if e['cluster_id'] is not None and not e['is_boss']]
    field_entries = [e for e in entries if e['cluster_id'] is None and not e['is_boss']]

    # Group by map for easier scanning
    from collections import defaultdict
    def group_by_map(es):
        g = defaultdict(list)
        for e in es: g[e['map']].append(e)
        return dict(sorted(g.items()))

    def fmt(side):
        n = side['name']; cp = side['c_prefix']
        return n if n == cp else f"{n} ({cp})"

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# Spoiler log — seed {seed}\n\n")
        f.write(f"Total swaps: **{len(entries)}** "
                f"(bosses: {len(boss_entries)}, "
                f"clustered: {len(cluster_entries)}, "
                f"field: {len(field_entries)})\n\n")
        # v0.20.27: surface multiplayer-safe state directly from the
        # kwarg passed to cmd_shuffle_v3. Was structurally inferred in
        # v0.20.26 (heritage subset of ghost-excludes) but now that
        # multiplayer-safe is applied engine-side, the kwarg is the
        # source of truth.
        f.write(f"Multiplayer-safe: **{'ON' if multiplayer_safe else 'OFF'}**"
                f"{'' if multiplayer_safe else ' — heritage chrs allowed; coop partners need the heritage pack'}"
                f"\n\n")
        # v0.27.24: surface all-SOTE mode state so a run's spoiler makes it
        # obvious whether the SOTE restriction was active. The seed-505991
        # report ambiguity (was SOTE mode on or not?) is resolved by this
        # line existing. Sourced from V3_SOTE_MODE at write time (still set
        # — the restore happens in cmd_shuffle_v3's finally, after the impl
        # that calls this returns).
        if sote_mode:
            f.write("All-SOTE mode: **ON** — targets restricted to the "
                    "Shadow-of-the-Erdtree roster; unique-target caps/floors "
                    "bypassed. Requires MMV + heritage SOTE assets staged.\n\n")
        # v0.23.07: unique-target cap summary. Renders cleanly even if no
        # capped cps got reservations — the unplaced list tells the user
        # which caps to relax. Order: cap=1 first, alphabetical within.
        if V3_UNIQUE_TARGET_CAPS:
            f.write("## Unique-target caps\n\n")
            f.write("Capped c-prefixes are limited to N placements per run "
                    "(named bosses cap=1, unnamed archetypes cap=2). The "
                    "reservation pre-pass picks quality slots up front.\n\n")
            placed = dict(_V3_UNIQUE_PLACED_COUNTS)
            unplaced_cps = {u['cp'] for u in _V3_UNIQUE_UNPLACED_LOG}
            sorted_caps = sorted(V3_UNIQUE_TARGET_CAPS.items(),
                                  key=lambda kv: (kv[1], kv[0]))
            for cp, cap in sorted_caps:
                cnt = placed.get(cp, 0)
                if cp in unplaced_cps:
                    badge = '⊘ unplaced'
                elif cnt == 0:
                    badge = '○ unreserved'
                elif cnt == cap:
                    badge = '✓ filled'
                else:
                    badge = f'~ partial ({cnt}/{cap})'
                tag_name = tags.get(cp, {}).get('name', cp)
                f.write(f"- **{cp}** {tag_name} (cap={cap}): "
                        f"placed {cnt}/{cap} — {badge}\n")
            if _V3_UNIQUE_UNPLACED_LOG:
                f.write("\n### Unplaced (no qualifying slot)\n\n")
                f.write("These c-prefixes couldn't get a reservation this "
                        "run. To enable them, either relax the scoring "
                        "criteria in `_score_slot_for_unique` or add slot "
                        "candidates via tag adjustments.\n\n")
                for u in _V3_UNIQUE_UNPLACED_LOG:
                    f.write(f"- **{u['cp']}** (cap={u['cap']}): "
                            f"{u['reason']}\n")
            f.write("\n")
        # v0.20.35: surface diagnostic-mode state. Loud marker because
        # diagnostic spoilers should be obvious — they're for capturing
        # freeze evidence, not regular play.
        if disable_resilient_filter:
            f.write("> ⚠ **DIAGNOSTIC MODE** — `disable_resilient_filter=True`. "
                    "Fragile slots used UNTESTED-only filter (pool - RESILIENT - "
                    "SENSITIVE). Every fragile-slot placement is a candidate "
                    "test. Report c-prefixes that freeze so they can be added "
                    "to `V3_FRAGILE_SENSITIVE_TARGETS`.\n\n")
        if non_fragile_baseline_cp:
            f.write(f"> ⚠ **DIAGNOSTIC BASELINE** — `non_fragile_baseline_cp="
                    f"{non_fragile_baseline_cp}`. Every non-fragile slot was "
                    f"forced to this single c-prefix. **Anything you see in-game "
                    f"that is NOT `{non_fragile_baseline_cp}` is a fragile-slot "
                    f"test placement** — note its c-prefix and the freeze.\n\n")
        if diagnostic_test_targets:
            cps = sorted(diagnostic_test_targets)
            f.write(f"> ⚠ **DIAGNOSTIC BATCH** — `diagnostic_test_targets` ({len(cps)} c-prefixes). "
                    f"Fragile slots restricted to: `{', '.join(cps)}`. "
                    f"**Any CTD this run is attributable to one of these {len(cps)} "
                    f"c-prefixes — note which slot/area triggered it and we can "
                    f"narrow further by binary-searching the batch.**\n\n")
        f.write(f"To find a specific encounter: search this file or "
                f"`_spoilers.json` for the c-prefix or name of what you fought.\n\n")

        # v0.20.1: Tracker section — for c-prefixes the user wants to keep
        # an eye on, list every slot where they appeared as source (vanilla
        # was → now is) and as target (vanilla was → now this enemy).
        # Set V3_TRACKED_C_PREFIXES to extend.
        tracked = sorted(V3_TRACKED_C_PREFIXES)
        if tracked:
            f.write("## Tracked enemies\n\n")
            for cp in tracked:
                name = tags.get(cp, {}).get('name', cp)
                tier = tags.get(cp, {}).get('tier', '?')
                src_es = [e for e in entries if e['original']['c_prefix'] == cp]
                tgt_es = [e for e in entries if e['new']['c_prefix'] == cp]
                f.write(f"### {name} (`{cp}`, {tier})\n\n")
                f.write(f"Source slots (where vanilla {name} was) — "
                        f"{len(src_es)} placements:\n\n")
                if src_es:
                    f.write("| map | pi | original variant | → | new |\n")
                    f.write("|---|---|---|---|---|\n")
                    for e in src_es:
                        f.write(f"| {e['map']} | {e['part_index']} "
                                f"| {fmt(e['original'])} | → "
                                f"| **{fmt(e['new'])}** |\n")
                    f.write("\n")
                f.write(f"Target placements (where {name} now appears) — "
                        f"{len(tgt_es)} placements:\n\n")
                if tgt_es:
                    f.write("| map | pi | replaced | → | new variant |\n")
                    f.write("|---|---|---|---|---|\n")
                    for e in tgt_es:
                        f.write(f"| {e['map']} | {e['part_index']} "
                                f"| {fmt(e['original'])} | → "
                                f"| **{fmt(e['new'])}** |\n")
                    f.write("\n")
                if not src_es and not tgt_es:
                    f.write("*(no occurrences this run)*\n\n")

                # v0.20.18: preserved-source subsection — slots whose vanilla
                # cp was source-excluded (so they stayed vanilla and won't
                # appear in src_es above). Useful for tracking c3610/c3620
                # Oracle Envoys etc. — shows where they're still standing
                # in the user's seed.
                pres_es = [p for p in _V3_PRESERVED_SOURCE_LOG
                           if p['c_prefix'] == cp]
                if pres_es:
                    f.write(f"Source slots (preserved as vanilla — "
                            f"source-excluded) — {len(pres_es)} placements:\n\n")
                    f.write("| map | pi | variant | position |\n")
                    f.write("|---|---|---|---|\n")
                    for p in pres_es:
                        pos = p['position']
                        pos_str = f"({pos[0]}, {pos[1]}, {pos[2]})" if pos else "—"
                        # The variant name field can be empty for synthetic
                        # variants — fall back to just the c-prefix for
                        # readability.
                        variant_str = p['name'] or p['c_prefix']
                        f.write(f"| {p['map']} | {p['part_index']} "
                                f"| {variant_str} | {pos_str} |\n")
                    f.write("\n")

        # v0.20.19: unaccounted-vanilla section. Empty on a healthy run.
        # Non-empty entries are bug candidates: slots that fell through
        # the swap loop without a documented reason. Grouped by reason
        # so each leak class is visible at a glance. See
        # _V3_UNACCOUNTED_VANILLA_LOG docstring for what each reason means.
        if _V3_UNACCOUNTED_VANILLA_LOG:
            f.write("## Unaccounted vanilla slots\n\n")
            f.write(f"*{len(_V3_UNACCOUNTED_VANILLA_LOG)} slot(s) fell through "
                    f"the swap loop without producing a swap entry. The "
                    f"`script_spawn_target_only_at_msb` reason is expected "
                    f"architecture (heritage script-only c-prefixes at fixed "
                    f"arena slots). Other reasons indicate probable bugs.*\n\n")
            from collections import defaultdict as _dd
            by_reason = _dd(list)
            for u in _V3_UNACCOUNTED_VANILLA_LOG:
                by_reason[u['reason']].append(u)
            for reason in sorted(by_reason):
                rows = by_reason[reason]
                f.write(f"### {reason} ({len(rows)})\n\n")
                f.write("| map | pi | c_prefix | variant | npc | eid | position |\n")
                f.write("|---|---|---|---|---|---|---|\n")
                for u in rows:
                    pos = u['position']
                    pos_str = f"({pos[0]}, {pos[1]}, {pos[2]})" if pos else "—"
                    eid_str = (str(u['entity_id']) if u['entity_id'] is not None
                               else "—")
                    name = u['name'] or u['c_prefix']
                    f.write(f"| {u['map']} | {u['part_index']} | {u['c_prefix']} "
                            f"| {name} | {u['npc_param_id']} | {eid_str} | {pos_str} |\n")
                f.write("\n")
        else:
            # Visible "all clear" header so the absence is informative
            # (otherwise an unaccounted bug class that gets routed to a
            # different log might masquerade as a clean run).
            f.write("## Unaccounted vanilla slots\n\n")
            f.write("*No unaccounted slots — every Part either swapped or "
                    "had a documented reason to stay vanilla.*\n\n")

        # Boss-tier first — most interesting
        if boss_entries:
            f.write("## Boss-tier swaps\n\n")
            for map_name, es in group_by_map(boss_entries).items():
                f.write(f"### {map_name}\n\n")
                f.write("| entity_id | original | → | new | position |\n")
                f.write("|---|---|---|---|---|\n")
                for e in sorted(es, key=lambda x: x['entity_id'] or -1):
                    p = e['position']
                    pos_str = f"({p[0]}, {p[1]}, {p[2]})" if p else "—"
                    f.write(f"| `{e['entity_id']}` "
                            f"| {fmt(e['original'])} "
                            f"| → "
                            f"| **{fmt(e['new'])}** "
                            f"| {pos_str} |\n")
                f.write("\n")

        # Clustered swaps — multi-Part encounters
        if cluster_entries:
            f.write("## Clustered swaps (multi-part encounters)\n\n")
            f.write("Members of the same cluster share an encounter. Look for matching `cluster_id` in JSON.\n\n")
            for map_name, es in group_by_map(cluster_entries).items():
                f.write(f"### {map_name}\n\n")
                # Group by cluster within map
                by_cluster = defaultdict(list)
                for e in es: by_cluster[e['cluster_id']].append(e)
                for cid, members in sorted(by_cluster.items()):
                    f.write(f"**Cluster {cid}** ({len(members)} members):\n")
                    for m in members:
                        f.write(f"- entity `{m['entity_id']}`: "
                                f"{fmt(m['original'])} → **{fmt(m['new'])}**\n")
                    f.write("\n")

        # Field swaps — collapsed table per map
        if field_entries:
            f.write("## Field swaps\n\n")
            for map_name, es in group_by_map(field_entries).items():
                f.write(f"### {map_name} ({len(es)} swaps)\n\n")
                f.write("<details><summary>Show swaps</summary>\n\n")
                f.write("| entity_id | original | → | new |\n")
                f.write("|---|---|---|---|\n")
                for e in sorted(es, key=lambda x: x['entity_id'] or -1):
                    f.write(f"| `{e['entity_id']}` "
                            f"| {fmt(e['original'])} "
                            f"| → "
                            f"| {fmt(e['new'])} |\n")
                f.write("\n</details>\n\n")

    # v0.24.19: Persistent spoiler archive. The output_dir spoiler is volatile
    # — it gets overwritten on the next run, so users who re-shuffle before
    # grabbing the file lose their diagnostic data. Solution: also drop a
    # timestamped copy into <project>/spoilers/ as a permanent searchable log.
    #
    # Naming: YYYYMMDD_HHMMSS_seed<seed>_<fingerprint>.{json,md}
    # — sortable by time (newest at bottom), seed-searchable, engine-version
    # tagged so we can quickly tell which build produced a given spoiler.
    #
    # Failure is non-fatal: archive errors print a warning and the run still
    # succeeds. The output_dir spoiler (what the GUI surfaces and what the
    # user normally looks at) is the authoritative copy; the archive is
    # belt-and-suspenders.
    #
    # Pruning is intentionally not done here. The archive grows unbounded
    # until the user manually cleans it up — same model as a build log.
    # Rough storage footprint: ~150-300 KB per run (mostly the JSON), so
    # 1000 runs ≈ 150-300 MB. If that becomes a problem, add a retention
    # cap (keep newest N) in a future revision.
    try:
        import datetime, shutil
        _project_dir = os.path.dirname(os.path.abspath(__file__))
        _archive_dir = os.path.join(_project_dir, 'spoilers')
        os.makedirs(_archive_dir, exist_ok=True)
        _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        _stem = f"{_ts}_seed{seed}_{V3_ENGINE_FINGERPRINT}"
        shutil.copy2(json_path, os.path.join(_archive_dir, f"{_stem}.json"))
        shutil.copy2(md_path,   os.path.join(_archive_dir, f"{_stem}.md"))
        print(f"[v0.24.19] Spoiler archived: spoilers/{_stem}.json")
    except Exception as _archive_err:
        # Don't let archive failure break the run; just warn.
        print(f"[v0.24.19] WARNING: spoiler archive failed: {_archive_err}")
