# Dev tooling

> **New to this repo?** Read `ARCHITECTURE.md` (this folder) first — it maps
> the engine, the `data/` file schemas + serialization conventions, the
> heritage-import pipeline, and the gotchas that otherwise cost a session
> real time to rediscover.

Nothing in `dev/` is part of the rando runtime. These are the data builders,
audits, and simulators used to produce and validate the catalogs in `data/`.
Most assume the project root as CWD — `cd` to the repo root and run
`python dev/<name>.py`, or pass explicit `--` path arguments.

## Catalog generators (write into `data/`)

- `emit_*.py` — override/slot emitters: `emit_hp_overrides.py`,
  `emit_atk_overrides.py`, `emit_getsoul_overrides.py`,
  `emit_reward_overrides.py` (the four `data/*_overrides.csv` files),
  `emit_slot_inventory.py`, `emit_slot_metadata.py`, `emit_has_reward.py`,
  `emit_nb_encounter_whitelist.py`, `emit_mmv_style_arena_emevd.py`.
- `extract_*.py` — vanilla-data extractors: `extract_placement_budget.py`,
  `extract_msb_slots.py`, `extract_boss_init_calls.py`,
  `extract_npc_think_from_xml.py`, `extract_npc_think_pairs.py`,
  `extract_think_param_ids.py`.
- `build_*.py` — heavier builders: `build_slot_terrain.py` (writes
  `data/slot_terrain.json`; imports `hkx_aabb_check.py`), `build_slot_poi_clusters.py`,
  `build_slot_repositions.py`, `build_part_positions.py`,
  `build_evergaol_wake_entities.py`, `build_fragile_slot_entities.py`,
  `build_nb_wave_bypass_flags.py`, `build_heritagae_pack.py`
  (the `heritagae` typo is historical — intentional as-is, don't rename),
  `build_test_arena.py`.
- Other generators: `set_nightlord_bosses.py` (nightlord_bosses_*.json
  variants), `stamp_name_marker_boss_wakes.py`, `derive_tile_data.py`,
  `generate_test_mode_arenas.py`, `generate_thinkparam_restore_csv.py`,
  `er_to_nr_param_remap.py`, `register_heritage_imports.py`,
  `heritage_chr_import.py`, `import_aicommon_scripts.py`,
  `import_heritage_ai_scripts.py`, `patch_mmv_has_reward.py`,
  `apply_healthbar_names.py`, `apply_slot_repositions.py`,
  `distribute_stacked_repositions.py`,
  `extend_repositions_to_phase_siblings.py`, `msb_authoring.py`,
  `chr_asset_resolver.py`.

## Audits and diagnostics (`audit_*`, `diagnose_*`, misc)

`audit_chr_assets_vs_roster.py`, `audit_encampment_anchors.py`,
`audit_engine_globals.py`, `audit_genuine_variants.py`,
`audit_healthbar_callsites.py`, `audit_heritage_chr_deployment.py`,
`audit_placeholder_clusters.py`, `audit_placement_budget_consistency.py`,
`audit_primary_identity.py`, `audit_source_tags.py`, `audit_team26_variants.py`,
`audit_terrain_arena_candidates.py`, `audit_vanilla_chr.py`, plus
`_diagnose_engine_state.py`, `ctd_lookup.py`, `diagnose_aicommon_gap.py`,
`diagnose_problem_slots.py`, `hkx_aabb_check.py`,
`navmesh_polygon_metrics.py`, `nva_distance_check.py`,
`parse_overlay_emevds.py`, `validate_placements.py`,
`verify_heritage_params.py`, `check_patches_shipped.py`,
`install_discovery.py`, `prune_redundant_chrs.py`, `find_derand_seed.py`,
`replay_carveout.py`, `set_nb_whitelist_target.py`,
`spoiler_predict_nightlords.py`, `pools_caps_panel.py`, `prep_demo.py`,
`arena_to_reroller_inputs.py`, `v0_23_07_audit.py`,
`vanilla_night_bosses.py`, `vanilla_some_msbs.py`, `test_oodle.py`,
`terrain_test_seed.py`.

## Simulators (`sim_*`)

`simulate_engine.py`, `simulate_seeds.py`, `sim_per_run.py`,
`sim_fb_to_nb_promote_sweep.py`, `sim_nb_slot_outcomes.py`,
`sim_new_add_health.py` — engine-level seed sweeps and outcome simulators
used to validate placement/drop changes before shipping.

## Notes, design docs, and sidecars

- `SESSION_NOTES_2026-05-22.md`, `SESSION_NOTES_2026-05-26.md` — active
  session-history location (the older `docs/SESSION_NOTES.md` is frozen).
- Design/workflow docs: `AUTHORED_ARENA_WORKFLOW.md`, `BOUTIQUE_RUN_SPEC.md`,
  `CAP_FOLD_CANDIDATES.md`, `CHR_ASSET_RESOLVER_PATCH.md`,
  `CTD_REPORT_TEMPLATE.md`, `DESIGN_tiered_drop_rarity.md`,
  `HERITAGE_CHR_IMPORT_README.md`, `IMPORT_PLAN_COLLISIONS.md`,
  `PHASE1_STUBS_REVIEW.md`, `PLAYTEST_SESSION_LOG.md`, `TEST_MODE.md`,
  `V0_28_X_FIELD_BOSS_TIER_SEPARATION.md`, `SHARED_CAP_INTEGRATION_PATCHES.md`,
  `GIT_SETUP.md`, `WONTFIX.md`, `TODO.md`, and the per-topic `TODO_*.md`
  threads. `NIGHTREIGN-AP-DESIGN.md` is an Archipelago design draft for a
  separate project, kept here as dev material.
- JSON sidecars: `all_msb_slots.json`, the `*_audit.json` results,
  `heritage_chr_attribution.json`, `mmv_npc_think_pairs.json`,
  `nr_vanilla_npc_think_pairs.json`, `proposed_*_anchors_v0.23.02.json`,
  `terrain_arena_candidates.json`.
- Subfolders: `anibnd_tools/`, `csv_imports/`, `er_heritage_csvs/`,
  `material_merging/`, `archive/` (retired tools and docs).
