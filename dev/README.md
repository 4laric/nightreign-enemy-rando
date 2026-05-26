# Dev tooling

> **New to this repo?** Read `ARCHITECTURE.md` (this folder) first — it maps
> the engine, the `data/` file schemas + serialization conventions, the
> heritage-import pipeline, and the gotchas that otherwise cost a session
> real time to rediscover.

These scripts are not part of the rando runtime. They were used during
v0.2 development to measure placement variety and diagnose 0% prefixes.

Kept in the bundle for transparency and so future tuning passes are
reproducible — if you change the at-risk threshold, the rescue pool cap,
or `is_boss_tier_prefix`, re-run these to see the impact.

## coverage_sim.py

Simulates N seeds and reports per-c-prefix placement rate, side-by-side
with and without size-down rescue. Run a 200-seed sweep:

    python3 dev/coverage_sim.py 200

Run a quick 50-seed pass:

    python3 dev/coverage_sim.py 50

Run baseline-only (no rescue comparison):

    python3 dev/coverage_sim.py 200 --no-rescue

Output sections: hard zeros, at-risk tail (<10%), soft tail (10–30%),
top 25 most placed, before/after diff, Tree Spirit slot delta.

## zero_diagnosis.py

Categorizes every 0%-placement c-prefix by structural cause:

- `deliberately_excluded` — in V3_EXCLUDE_PREFIXES /
  V3_EXCLUDE_TARGET_PREFIXES / V3_GHOST_EXCLUDE_TARGET_PREFIXES
- `field_tier` — boss-tier slots filter them out (251/262 slots are
  boss-tier in vanilla NR)
- `untagged` — no anim_class/size data; tagger hasn't reached them
- `aquatic` — no aquatic slots in vanilla NR slot population
- `flying_arena` — flying_dragon arena=True with no compat arena slots
- `reachable_low_freq` — would land in principle, just rare; shows up at
  higher seed counts

Run:

    python3 dev/zero_diagnosis.py

Slow (~2 min for full diagnosis) because it probes every (slot_cp,
candidate_cp) pair under both strict and rescue rules.

## v0.23.06: scripts moved here from project root

The following scripts were at the project root through v0.23.05.2 and
moved here during the v0.23.06 tidy-up. They use bare relative paths
(`open('nr_enemy_tags.json')`) by default, so to run them you typically
need to `cd` to the project root first and invoke as `python3 dev/<name>.py`,
or pass explicit `--tags ../nr_enemy_tags.json` style arguments. Most of
them already accept `--` arguments for any path they touch.

| Script | Purpose |
|--------|---------|
| `audit_encampment_anchors.py` | Scan vanilla MSBs for placeholder cluster anchor candidates that should be added to `data/t1_anchors.json` for SE-tile encampment fragility detection. |
| `audit_placeholder_clusters.py` | Wider audit — finds all multi-Part clusters around T1 anchors. Output proposes candidates for V3_CLUSTER_LOCK_MAPS. |
| `build_slot_terrain.py` | Pre-computes per-slot navmesh-derived off_mesh / roughness data. Produces `slot_terrain.json` (which is at project root). Slow — only re-run after adding new MSBs to the slot population. Imports `bnd4`, `hkx_aabb_check`. |
| `bnd4.py` | BND4 binder reader. Imported only by `build_slot_terrain.py` and `hkx_aabb_check.py`. Not used at runtime. |
| `hkx_aabb_check.py` | Standalone tool to verify hkx AABB classification matches expected slot positions. Sanity-check helper for `build_slot_terrain.py` output. |
| `nva_distance_check.py` | Original v0.18 navmesh-distance tool. Superseded by `build_slot_terrain.py`'s AABB approach but kept for cross-reference. |
| `diagnose_problem_slots.py` | Given a spoiler with reported issues, classifies each problem slot (off-mesh / cramped / encampment / etc) for triage. |
| `heritage_scan.py` | Scans the heritage pack's NpcParam CSV against the local roster to find newly-imported chrs and propose tags. Run when bumping heritage pack version. |
| `terrain_test_seed.py` | Generate a deterministic seed populated only with terrain test markers — useful for verifying off-mesh classification by playing a build that puts a known marker chr at every slot. |
| `test_oodle.py` | Smoke test for the bundled Oodle DLL. Run once after install if `dcx_batch` errors. |
| `vanilla_some_msbs.py` | Utility to copy specific vanilla MSBs into a build, e.g., for "vanilla everything except this one tile" testing. |
