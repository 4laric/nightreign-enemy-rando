# Architecture orientation

**Read this first.** This file exists so a new session can orient in a minute
or two instead of rediscovering the same facts. It is hand-maintained — if the
engine or the data schemas change, update it.

## What this is

`nightreign-enemy-rando` randomizes Elden Ring Nightreign's enemy placements.
The engine (`oops_v3.py`, ~15k lines) reads decompiled NR map files (MSBs),
swaps the enemy at each placement slot for another one chosen from a roster
under tier / size / animation constraints, and writes the MSBs back.
`oops_rando_gui.py` and `dcx_batch.py` drive it.

## Repo map

- `oops_v3.py` — the engine. Version constants near the top: `V3_ENGINE_VERSION`
  (line ~30) and `V3_ENGINE_FINGERPRINT` (line ~31 — bump on every release).
- `data/` — the JSON/CSV data the engine reads (schemas below).
- `dev/` — tooling and audits; NOT part of the runtime. Index: `dev/README.md`.
- `engine/` — pack loaders (`engine/pack_loaders/`).
- `tests/` — pytest suite. Baseline is **56 pre-existing failures**; a change
  should not raise that count (`python3 -m pytest -q --tb=no`).
- `CHANGELOG.md` — prepend an entry per engine release.

## The data files (`data/`)

All are 2-space-indented JSON. **Serialization conventions differ per file, and
a mismatch produces a huge spurious diff** — match them exactly:

| file | shape | unicode | trailing newline |
|------|-------|---------|------------------|
| `nr_enemy_tags.json` | `{c_prefix: tag}` — within-entry keys alphabetical; top-level mostly sorted, heritage appended last | **literal UTF-8** (`ensure_ascii=False`) | yes |
| `nr_enemy_roster.json` | `{all_variants:[...], canonical_targets:[...]}` — variant fields in fixed order | escaped (`ensure_ascii=True`) | no |
| `heritage_pack.json` | `{_meta, tags:{c_prefix:{name,_inferred_source}}}` | escaped | no |
| `batch_import_plan_comprehensive.json` | `[{c_prefix,name,locomotion,status,hp_max,anim_class}]` | escaped | no |

- `nr_enemy_tags.json` — one entry per c-prefix: tier, hp/hit/weight medians,
  anim_class, size_class, locomotion, move_type, team, variant counts. **This
  is the engine's enemy database.**
- `nr_enemy_roster.json` `all_variants` — one entry per placeable NpcParam row
  (`c_prefix, npc_param_id, think_param_id, variant_name, hp, ...`). The roster
  keeps **every** row; deduplication happens at pick time (see prune list).
- `NpcParam.csv` — 356-col enemy param export. Key columns: ID=0, Name=1,
  behaviorVariationId=5, hitHeight=9, hitRadius=10, weight=11, hp=13,
  getSoul=15, itemLotId_enemy=16, teamType=107, moveType=108. **No think-param
  column exists** — `think_param_id` is not derivable from this CSV.
- `variant_prune_list.json` — clusters of redundant NpcParam rows; the engine
  soft-filters these on the random pick path. Built by
  `dev/audit_genuine_variants.py`. Gated by `V3_APPLY_VARIANT_PRUNE_LIST`.
- `batch_import_plan_comprehensive.json` — the heritage-import queue. Its
  `anim_class` is often the placeholder `"misc"` — do not trust it as real.

## Key concepts

- **c-prefix** (`c5840`) = one chr asset; the engine reasons at this
  granularity. `cp_int * 10000` is the base of that chr's NpcParam ID band;
  `cp_int * 10` is its `anim_bank`.
- **tier** — `grunt` / `miniboss` / `field_boss` / `night_boss` / etc. The
  `tier` field in `nr_enemy_tags.json` drives which placement pool a chr is
  picked from. `is_boss_tier_prefix()` (oops_v3.py ~4530) is a *separate*
  predicate, used for recipient-slot classification and spoiler annotation —
  it does NOT override the `tier` field for target-pool eligibility.
- **variant prune** — the roster has ~3000+ NpcParam rows, mostly the same
  enemies re-authored per placement context. The prune list marks redundant
  rows so the random pick path doesn't over-represent duplicate-heavy chrs.
- **heritage chrs** — enemies imported from Elden Ring that vanilla NR's `chr/`
  folder doesn't ship (`_heritage_imported: true`, listed in
  `heritage_pack.json`, set `V3_HERITAGE_ALL_PREFIXES`).
- **think_param_id** — the NpcParam→NpcThinkParam link. No exported CSV carries
  it; `dev/nr_vanilla_npc_think_pairs.json` holds MSB-placement-derived pairs,
  but chrs never placed in vanilla NR (all heritage chrs) are absent from it.

## Heritage chr import — three independent stages

1. **Regulation params** — NpcParam / NpcThinkParam / BehaviorParam /
   AtkParam_Npc rows. Verify with `dev/verify_heritage_params.py` — does the
   mod regulation already cover vanilla ER for this chr? (For the c5xxx
   heritage grunts the answer was yes: no regulation edits needed.) The trace
   is NpcParam → `behaviorVariationId` → `BehaviorParam.variationId` →
   `refId` → `AtkParam_Npc`.
2. **The four data files** — register a chr with
   `dev/register_heritage_imports.py --chr cXXXX --tier T`.
3. **chr/ + script/ asset copy** — `dev/heritage_chr_import.py`, run on a rig
   with an unpacked ER install. Cannot run in-container.

`heritage_pack.json` and `nr_enemy_roster.json` are normally rebuilt by
pipelines that need decompiled MSBs + ER chr folders (`dev/build_heritagae_pack.py`
— note the misspelled filename — and `dev/extract_npc_think_pairs.py`); those
are rig-only.

## Gotchas (these cost real time)

- **The container filesystem resets between sessions** — only committed git
  state survives. Commit before the session ends.
- `nr_enemy_tags.json` stores literal em-dashes/arrows; dump it with
  `ensure_ascii=False` or every note line churns in the diff.
- `NpcParam.csv` has no think-param column; the batch plan's `anim_class` is
  mostly placeholder `"misc"`.
- The roster is not deduplicated — registering all of a chr's rows is correct.
- Commit with the project identity:
  `git -c user.name="oops-rando dev" -c user.email="dev@localhost" commit`.
- `fmg_additions.json` at the repo root is intentionally untracked — leave it.

## Where to look

- engine tier / placement logic — `oops_v3.py`; search `is_boss_tier_prefix`,
  `pick_variant_for_tier`, `tier`.
- dev tooling index — `dev/README.md`.
- heritage asset workflow — `dev/HERITAGE_CHR_IMPORT_README.md`.
- recent history — `dev/SESSION_NOTES_*.md`, `CHANGELOG.md`.