# regulation_fixes/

Smithbox-importable CSVs that heal regulation contamination found 2026-05-22.

## The contamination

The live regulation = MMV base + FIA's full layer + clean getSoul + one
contaminated param. The ONLY contamination is in NpcParam:

- `chaosMatchingCorrectParamId` — 862 rows overwritten with a crude
  5-bucket scheme
- `hp` — 19 rows flattened to 314 / 162

877 distinct ids, 881 field-cells. Most likely a debug/test artifact
co-imported alongside the getSoul CSV. getSoul values themselves are NOT
contaminated. No repo script reproduces it, so the fix is a one-time import.

## Files

- **`NpcParam_decontaminate_smithbox.csv`** — THE FIX. 877 rows = current
  mod rows with only `chaosMatchingCorrectParamId` / `hp` healed back to MMV
  values; every other field byte-identical to the current regulation.
  Import into the existing regulation in Smithbox = surgical fix, FIA +
  getSoul untouched. Verified: 0 rows change any other field.

- **`regulation_contamination_npcparam.csv`** — the audit. Columns:
  `NpcParam_ID, Name, field, intended_value(MMV), current_value(mod)`.
  Explains exactly what the fix changes and why.

- **`NpcParam_getsoul_smithbox.csv`** — OPTIONAL. 2807 full NpcParam rows
  with getSoul applied + contamination healed. Only for a from-scratch
  regulation rebuild; REDUNDANT if you patch the live regulation (getSoul is
  already correct there). 3 MB — ignore unless rebuilding.

- **`LotResultSmallBaseAndSpot_nb_whitelist_smithbox.csv`** — NB encounter
  whitelist (v0.28.x). Companion to the engine-side
  `V3_NB_RANDOMIZE_WHITELIST` in `oops_v3.py` -- both layers read the
  same `data/nb_encounter_whitelist.json` so they cannot drift. The CSV
  rewrites every row of `LotResultSmallBaseAndSpot` that carries one of
  the 22 dedicated NB arena IDs, redirecting it to the whitelist's NB1
  or NB2 pick (every other column byte-identical). v1 picks: NB1 →
  `m49_10_00_00` (Grafted Monarch), NB2 → `m48_40_00_00` (Morgott). 432
  rows total. The engine layer enables boss-Part swap at the same two
  arenas, so each run loads one of the two whitelisted arenas per night
  and the boss inside is randomized by the existing NB-caliber pool
  with all safety filters applied (`V3_NIGHT_BOSS_EXCLUDE_TARGETS`, the
  Margit-fix anim-family compat, unique-cap reservation).

  Regenerate via:

      python3 dev/emit_nb_encounter_whitelist.py \
          --param-dump /path/to/regulation/csv-dir

  Import order in Smithbox: MMV layer FIRST, this CSV LAST -- the patch
  is row-patch semantics, so only listed rows change; non-NB rows stay
  vanilla. Reverting is independent on each side: re-import the vanilla
  `LotResultSmallBaseAndSpot.csv` from the regulation dump to undo the
  param layer, or empty `data/nb_encounter_whitelist.json` to
  `{"nb1": [], "nb2": []}` and restart to undo the engine layer.

## Notes

Smithbox CSV import is a row-patch — only listed rows change. If your
importer wants headerless rows, drop line 1. Schema is the 356-column NR
NpcParam layout matching the param dumps.
