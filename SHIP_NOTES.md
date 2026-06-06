# v0.25.0 ship notes (HISTORICAL)

> **This is the files-in-bundle manifest for the v0.25.0 release and is
> kept only as a historical record.** The current release is v0.26.10.
> For what's new since v0.25.0, see `PATCH_NOTES.md`; for the full
> per-version history, see `CHANGELOG.md`. The "Pending next-version
> items" list at the bottom of this file is superseded by `docs/TODO.md`
> — do not treat it as the live backlog.

First public release since v0.23.58. The v0.24.x arc was internal — engine
fingerprint walked from v0.24.21 through v0.24.111+ during development, with
per-session notes accumulated in this file and PATCH_NOTES.md and rolled into
the CHANGELOG.md v0.25.0 entry at ship time. This document is the
files-in-this-bundle manifest for the bumped release; for the cross-cutting
"what's new since v0.23.58" rollup, see `CHANGELOG.md`.

## What's in this bundle vs v0.23.58

### Engine

```
oops_v3.py                      V3_ENGINE_FINGERPRINT bumped to v0.25.0.
                                Body changes during v0.24.x: V3_BOSS_SLOT_
                                CATALOG authoritative-score path, narrow
                                V3_TARGET_ONLY_SOURCES exemption for c4670/
                                c4690, 'Unused' variant marker added to
                                V3_VARIANT_TRIGGER_MARKERS (eliminates the
                                c5840 misdiagnosis), V3_PRESERVE_SLOTS
                                refinements.

swap_compat.py                  size + boss-arena compat only. All rig/
                                family ("anim_class") gating and the
                                flier-vs-ground split were removed
                                (v0.27.28); locomotion-fragility moved to
                                the fragile_locomotion tag.

oops_all_anyone.py              Unchanged core; reused by oops_v3 for MSB
                                primitives.

dcx_batch.py                    Step 1c (slot repositioning) added.
                                Step 2a/3 (walk_route_rewrite) flag-gated
                                off by default. vanilla_msg_bundle wired
                                so the FMG splice can fall back to the
                                bundled data/vanilla_msg/.

emevd_patch.py                  nb_wave_bypass patch added.
                                permissive_boss_wake scope expanded from
                                2 events to 8. disable_corpse_collision
                                retired. permissive_spawn_emerge updated.
```

### Data files

```
data/slot_repositions.json      NEW. ~25,000 entries. Off-navmesh part
                                positions repositioned to nearest tight
                                navmesh leaf. Built by dev/build_slot_
                                repositions.py.

data/scripted_intro_chrs.json   NEW (v0.24.86). 4 entries. Behbnd template
                                hashing did not replicate for this axis —
                                _meta.methodology_findings documents the
                                negative result. List grows empirically.

data/wakeup_chrs.json           NEW (v0.24.86). 5 entries. _meta.empirical_
                                audit_v0_24_86 records 103/103 coverage
                                proof.

data/nb_wave_bypass_flags.json  NEW (v0.24.105). Per-arena bypass + guard
                                flags picked from the empirically-unused
                                XXX029X private flag range.

data/nr_script_spawn_boss_slots.json
                                NEW since v0.23.58 (v0.24.37 initial;
                                v0.24.38 integrated with V3_SPAWN_POOL_MSBS).

data/nr_boss_slots.json         Schema v2 with intro_anchored enrichment
                                (v0.24.85). enrich_boss_slots_with_intro_
                                anchored.py is the build script.

data/nr_all_part_positions.json NEW. Built by dev/build_part_positions.py.

data/slot_terrain.json          NEW. Augmented with AABB metrics and
                                polygons by the two augment_slot_terrain_
                                with_* scripts in dev/.

data/mmv_imports.json           Lifted broken_runtime_chrs en masse
                                (v0.24.65) after MMV SFX + material deploy
                                proved Romina works. 30 lifted entries
                                preserved at _meta.history.broken_runtime_
                                chrs_lifted_v0_24_65 for reference. Cap=1
                                applied to all lifted chrs as a safety net.

data/nr_missing_chr_files.json  Schema v2 (broken_runtime_chrs category
                                added v0.24.39). Lifted en masse in
                                v0.24.65 alongside mmv_imports.

data/heritage_pack.json         Heritage pack manifest (~47 SOTE chr
                                prefixes).
```

### Dev / audit tooling

```
dev/build_slot_repositions.py   Build the slot_repositions.json file.
dev/apply_slot_repositions.py   Apply at MSB-patch time (Step 1c).
dev/distribute_stacked_repositions.py
                                Distribute repositions across phase
                                siblings to avoid stacked overlaps.
dev/extend_repositions_to_phase_siblings.py
                                Propagate repositions to phase-sibling
                                slots (testable via tests/test_extend_
                                repositions_to_phase_siblings.py).

dev/build_part_positions.py     Build nr_all_part_positions.json.
dev/build_slot_terrain.py       Build slot_terrain.json.
dev/augment_slot_terrain_with_aabb_metrics.py
                                Add AABB metrics to slot_terrain.
dev/augment_slot_terrain_with_polygons.py
                                Add polygon footprints to slot_terrain.

dev/build_nb_wave_bypass_flags.py
                                Build nb_wave_bypass_flags.json.
dev/import_heritage_ai_scripts.py
                                Import heritage chr AI scripts from an
                                ER unpack.
dev/heritage_chr_import.py      Heritage chr import planner; uses
                                chr_asset_resolver for severity split.

dev/chr_asset_resolver.py       NR file-convention-aware asset
                                resolver. Severity classes:
                                AI_BATTLE, AI_LOGIC, CTD, FREEZE,
                                NOT_NEEDED. Union rule: either AI
                                sibling present downgrades the
                                missing one.

dev/audit_chr_assets_vs_roster.py
                                NEW. Cross-checks tag roster against
                                me3 mod folder chr/ assets. Reports
                                PRESENT / MISSING-CRITICAL /
                                PRESENT-UNUSED / SCRIPT-GAPS buckets.

dev/audit_*.py                  Various per-axis audits (bfer_variants,
                                encampment_anchors, healthbar_callsites,
                                placeholder_clusters, primary_identity,
                                team26_variants, vanilla_chr).

dev/check_patches_shipped.py    Greps a patched-EMEVD bundle for each
                                registered patch's fingerprint. Reports
                                per-patch coverage so "did the build
                                pipeline run emevd_patch.py?" has a
                                fast answer.

dev/validate_placements.py      Offline placement validator. Per-
                                placement CLEAN / RELEASED /
                                SUSPICIOUS / WOULD_REJECT.

dev/ctd_lookup.py               Prefill CTD report sections 1, 3, 4, 5
                                from (spoiler, msb, pi).

dev/find_derand_seed.py         Map target MSB → Shifting Earth →
                                Nightlord+pattern_id range to filter a
                                derandomizer GUI to.

dev/CTD_REPORT_TEMPLATE.md      Structured 10-section CTD report
                                template. Methodology learnings encoded
                                (scripted_intro template-hash dead end
                                documented, wakeup section marked AXIS
                                AUDIT-CLOSED).

dev/PLAYTEST_SESSION_LOG.md     Capture template bridging "CTD
                                happened" → "use ctd_lookup.py to
                                investigate."

dev/_diagnose_engine_state.py   Engine-state diagnostic. Internal/dev
                                only (prefixed `_`).

dev/anibnd_tools/               Behavior template catalog + bnd4 reader
                                + tae anim ID resolver. Used during the
                                v0.24.84 emerge-candidate audit;
                                catalogued findings persist in
                                emerge_candidates_for_playtest.json /
                                high_confidence_not_emerge.json.

dev/heritage_chr_attribution.json
                                Attribution for the heritage chr bundle.
```

### Healthbar in-place rewrite system

```
healthbar_inplace/              Self-contained pipeline for in-place
                                healthbar-name rewriting. Splits
                                bnd.py, fmg.py, emevd.py, rewriter.py,
                                synth.py, oracle.py, pipeline.py.
                                Integration entry: bnd_splice_driver.py +
                                dcx_batch_integration.py. Tests in
                                healthbar_inplace/tests/.

healthbar_tools/                Companion CLI + demo prep scripts.
```

### Zero-config bundles (must be present in the RELEASE zip)

For the "unzip and it runs, no extra config" guarantee, the release zip
MUST include these binary bundles. They are large and are NOT in the
dev/working zips passed around during development — add them when cutting
the release:

```
vanilla_msbs/      The spawn-pool + shuffle-source MSBs (m*.msb.dcx).
                   GUI defaults Input dir here (oops_rando_gui input_dir_var).
                   WITHOUT THIS the rando has nothing to shuffle out of the
                   box — the user must point Input at their own NR install.
                   THE critical zero-config bundle.

vanilla_event/     v0.27.15: 197 .emevd.dcx + eventflag/ (~924K). GUI
                   defaults the Vanilla event/ field here. Enables the
                   in-pipeline EMEVD step (boss rewards + healthbar names)
                   with no config once the me3 output profile is set.

patched_emevd/     Sparse overlay: must be .emevd.dcx (+ .emevd.dcx.js)
                   for the rando_pipeline overlay matcher (it looks for
                   .emevd.dcx names matching vanilla_event/). If shipped
                   decompressed (.emevd only), the overlay is INERT — the
                   base vanilla_event still runs, but the boss-encounter
                   fix patches on top do NOT apply. RECOMPRESS before
                   release with a Windows build (oodle DLL required):
                     python3 -c "import dcx_batch; dcx_batch.emevd_compress_dir('patched_emevd_raw','patched_emevd')"
                   then confirm `find patched_emevd -name '*.emevd.dcx'`
                   is non-empty. (Can't be done on Linux/CI — oo2core is
                   a win64 DLL.)
                   v0.28.2: optional subdir patched_emevd/early_spawn/ holds
                   the night-boss-teleporter common_func.emevd.dcx (proximity
                   trigger). NOT part of the top-level overlay glob (the GUI
                   only reaches it when the "Early night-boss spawn" toggle is
                   on, and swaps it in for the default common_func). Ships if
                   present; absent = toggle falls back to the clock build.
                   Regen: emevd_patch.py --early-boss-spawn (see that dir's
                   README.md).

bundled_aicommon/  aicommon.luabnd.dcx etc. (test_bundled_aicommon).

bundled_regulation/ regulation.bin — MMV base + v0.28.x balance / safety
                   patches pre-applied. End-user drop-in for
                   `<me3 profile>/<package>/regulation.bin`. Companion
                   to bundled_aicommon and bundled_sfx. Lock test:
                   test_bundled_regulation.

bundled_sfx/       sfxbnd_c0000.ffxbnd.dcx — MMV's c0000 SFX bundle.
                   Required for cross-game / DLC / heritage chr
                   particle effects (playtest-confirmed v0.28.x: ER's
                   sfxbnd is not a substitute, same reasoning as ER's
                   aicommon). End-user drop-in for `<me3 profile>/
                   <package>/sfx/sfxbnd_c0000.ffxbnd.dcx`. ~182 MB —
                   dominates release zip size. Lock test:
                   test_bundled_sfx.
```

Release checklist: verify all six dirs exist AND contain content
(not just the dir). A quick gate:
  for d in vanilla_msbs vanilla_event patched_emevd bundled_aicommon bundled_regulation bundled_sfx; do
    n_files=$(find "$d" -type f -not -name 'README.md' 2>/dev/null | wc -l)
    echo "$d: $n_files content files"; done

### Patched EMEVD bundle

```
patched_emevd/                  26 .emevd.dcx files + 26 .emevd.dcx.js
                                companions. Drop-in install destination
                                for users who can't run the patcher
                                themselves (e.g. macOS, no .NET runtime
                                for DSAS3). .js files referenced by
                                tests/test_emevd_patches.py and
                                healthbar_inplace docs.
```

### Tests

```
tests/                          746 tests across pick_target,
                                chr_asset_resolver, emevd_patches,
                                extend_repositions_to_phase_siblings,
                                validate_placements, find_derand_seed,
                                permissive_boss_wake, unused_variant
                                _filter, plus the long-standing core
                                shuffle tests. All pass on the v0.25.0
                                tree.

tests/test_unused_variant_filter.py
                                NEW (v0.24.95-patch16). Lock-in for the
                                'Unused' variant marker filter that
                                resolved c5840.

tests/test_chr_asset_resolver.py
                                34 tests covering NR script variant
                                globbing, ER-pattern regression guard,
                                sfx exact-prefix match, AI union rule,
                                severity split, roster phantom detection.

tests/test_extend_repositions_to_phase_siblings.py
                                Coverage for the phase-sibling
                                propagation logic.

healthbar_inplace/tests/        13 tests for the in-place rewriter
                                (compose_name, rewriter, roundtrip).
```

## Pending next-version items

Carried over from the v0.24.86 ship notes plus items surfaced during
the v0.24.x arc:

1. **c6200 Slave Knight Gael incomplete deployment** — chrbnd + behbnd
   missing from the bundled heritage pack. Currently usable only when
   the user has MMV deployed; if v0.26 ships heritage Gael standalone,
   these two BNDs are the gap.
2. **8 heritage chr script imports** from the ER unpack still pending.
   `dev/import_heritage_ai_scripts.py` is the tool; the list lives in
   `dev/heritage_chr_attribution.json`.
3. **c8200 / c8400 chr identity questions** — see
   `dev/audit_primary_identity.py` outputs.
4. **B2 model-table compact feature** — deferred from late v0.24.x.
   Not blocking; would reduce MSB Models section bloat in shuffled
   output.
5. **Engine-wire V3_SCRIPTED_INTRO_SLOTS** so the picker rejects
   rather than just the validator flagging. Move #3 from the v0.24.86
   four-move plan.