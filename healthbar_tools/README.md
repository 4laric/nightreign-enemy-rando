# healthbar_tools — status: partially superseded, still shipped

Companion CLI tools for the boss-healthbar-rename feature (see
`DEMO_PREP.md` here and `docs/DEMO_PREP.md` for the workflow).

**This directory still ships** — `scripts/build_release.py` includes it in
`INCLUDE_DIRS` ("used by dcx_batch"), and `dcx_batch.py`'s healthbar
patcher points users at `healthbar_tools/prep_demo.py BUILD-CATALOG` when
`chr_to_nameid.json` is missing. The in-place runtime pipeline lives in
`healthbar_inplace/` (test-locked by `healthbar_inplace/tests/`).

## Status of each file (vs. the `dev/` copy)

| File                          | vs. `dev/` copy | Assessment |
|-------------------------------|-----------------|------------|
| `apply_healthbar_names.py`    | byte-identical  | **`dev/` is canonical**; this is a stale duplicate |
| `simulate_seeds.py`           | byte-identical  | **`dev/` is canonical**; this is a stale duplicate |
| `audit_healthbar_callsites.py`| **diverges**    | **this copy matches the runtime** — see below |
| `prep_demo.py`                | **diverges**    | **neither copy is known-canonical** — see below |

### `audit_healthbar_callsites.py` — this copy is the live one

The copy **here** carries the expanded v0.24.x schema table (28 handlers,
including the auto-derived 9006x family) and is **identical, key for key
and value for value, to `HEALTHBAR_HANDLER_SCHEMAS` in
`healthbar_inplace/emevd.py`** (verified by comparing the dicts directly;
the file's own header also says to keep the two in sync). The `dev/` copy
has only the original 6 schemas and is stale. Treat this copy as canonical
until someone reconciles `dev/`.

### `prep_demo.py` — diverged, neither copy known-canonical

The `dev/` copy has an extra `RANK-LITE` tile-aware ranking mode (no
`callsites.json` needed) that this copy lacks; `docs/DEMO_PREP.md`
advertises `healthbar_tools/prep_demo.py RANK-LITE`, which suggests the
`dev/` copy is newer — but this is the copy that actually ships, and it
does not have that mode. Neither copy strictly supersedes the other in
confirmed history; **neither is known-canonical**. Kept as-is pending
reconciliation.

## History

This directory predates `healthbar_inplace/`. The two byte-identical
files were copied to `dev/` during that consolidation; the two diverging
files drifted afterward in different directions.
