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

## Notes

Smithbox CSV import is a row-patch — only listed rows change. If your
importer wants headerless rows, drop line 1. Schema is the 356-column NR
NpcParam layout matching the param dumps.
