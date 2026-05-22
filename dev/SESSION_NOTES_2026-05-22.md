# Session notes — 2026-05-22

Index of artifacts added this session and the work still open. Engine
fingerprint at time of writing: v0.26.10 (`oops_v3.py` line 31).

## New dev tools (`dev/`)

- **`extract_npc_think_pairs.py`** — mines `NPCParamID -> ThinkParamID`
  pairings from a directory of **binary** `.msb` files, via the repo's own
  `oops_all_anyone.extract_enemy_parts`. Counts each think per npc id so the
  dominant pairing is picked. Run from repo root or pass `--repo-root`.
  Use for Nightreign `.msb` files.

- **`extract_npc_think_from_xml.py`** — same output, but reads
  **WitchyBND-decompiled** MSB dirs (`*/Part/Enemy/*.xml`). Recurses a whole
  tree. Use this for Elden Ring MSBs: the binary tool's struct offsets are
  NR-tuned and would silently misparse ER MSBs; the XML route avoids that.
  Output schema is identical to the binary tool, so they are interchangeable.

- **`er_to_nr_param_remap.py`** — schema-aware ER->NR param row porter.
  ER and NR use different paramdefs (NpcParam 322/356 cols, NpcThinkParam
  107/110, AtkParam_Npc 214/223). Maps by COLUMN NAME, not position; fills
  the 40 NR-only columns from an existing NR row of the same id, else the
  NR row-0 baseline, else 0; drops the 6 ER-only columns. Mirrors how MMV
  imports ER chrs.

- **`emit_has_reward.py`** — re-derives `has_reward` from boss tier
  (`BOSS_REWARD_TIERS = {miniboss, field_boss, night_boss, nightlord}`),
  emitting `data/has_reward_overrides.json`. NOT yet wired into `oops_v3.py`
  — see Pending below. Supersedes `dev/patch_mmv_has_reward.py` (left in
  place; delete only after wiring is done).

## New reference data

- **`dev/nr_vanilla_npc_think_pairs.json`** — npc->think pairing for all
  650 enemy types across the 300 vanilla NR MSBs (4513 placements). Same
  category as `dev/all_msb_slots.json` (a derived MSB cache). Note: `think`
  equals `npc` only ~5.5% of the time and multi-variant humanoids collapse
  npc-blocks onto think rows irregularly — there is no ID formula. 1-2 rows
  are name-pattern false positives (e.g. `5570639`); well-formed ids fine.

- **`dev/mmv_npc_think_pairs.json`** — same, for the 231 enemy types MMV
  places across 31 modded MSB dirs (m45/m46/m49/m52 tiles).

- **`data/has_reward_overrides.json`** — tier-driven `has_reward` table
  emitted by `emit_has_reward.py`. Staged; consumed once wiring lands.

## Regulation decontamination (`regulation_fixes/`)

See `regulation_fixes/README.md`. Short version: the live regulation has
exactly one contaminated param — NpcParam `chaosMatchingCorrectParamId`
(862 rows) and `hp` (19 rows). `NpcParam_decontaminate_smithbox.csv` is the
surgical one-import fix; FIA layer and getSoul stay intact.

## Pending / blocked

1. **c5651 Messmer Foot Soldier think remap.** All 54 c5651 variants in
   `data/mmv_imports.json` have `think_param_id` pinned to 56510000 — a real
   behavioral bug (the field is consumed by the rando and written into MSB
   `<ThinkParamID>`). The correct pairing cannot be derived from params: the
   54 NpcParam rows carry no weapon/loadout columns, and there is no npc->think
   ID formula. Source must be MSBs that place c5651. Vanilla NR never does
   (SoTE import) and the uploaded MMV map subsets don't either. NEXT STEP:
   WitchyBND-decompile ER's SoTE MSBs, run
   `extract_npc_think_from_xml.py --prefix c5651`, then remap the 54 variants
   from verified placements. Watch for: ER thinks not among MMV's 20 shipped
   c5651 NpcThinkParam rows (fold to nearest in-family); variants ER never
   places (principled fallback, not a guess).

2. **`has_reward` wiring into `oops_v3.py` (v0.26.10).** `emit_has_reward.py`
   is ready but unwired — needs re-scoping since `V3_GETSOUL_TIER_FLOORS` no
   longer exists under that name in v0.26.10. After wiring, delete
   `dev/patch_mmv_has_reward.py`.

3. **Regulation rebuild** — user imports
   `regulation_fixes/NpcParam_decontaminate_smithbox.csv` via Smithbox.

4. Backlog, untouched: ~8 heritage script imports from ER unpack; re-run MMV
   bulk import to fix c6200's missing chrbnd/behbnd; B2 model-table compact
   feature (deferred); fill `c5650` `exclude_reason` in
   `data/placement_budget.json` (cosmetic).
