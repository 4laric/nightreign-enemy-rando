# dev/archive/ — completed one-shot scripts

Tools here have served their purpose and are kept for historical
reference rather than reuse. They are NOT referenced from any active
code path, test, or doc; moving one back to `dev/` would break nothing
but should also not be necessary.

## Archival criteria

A script belongs here if all of the following hold:

1. **Job is done.** The work the script automated has been applied to
   the data / source files, and the script is not part of a recurring
   workflow.
2. **Single-target.** The script is hardcoded around a specific
   c-prefix / version / migration that has shipped — not a general
   tool that could be re-pointed at the next case.
3. **No external references.** Nothing in `*.py`, `*.md`, `*.txt`,
   `*.bat`, etc. invokes the script by name. (Quick check:
   `grep -r <script_name> --include="*.py" --include="*.md"` from
   repo root.)

Recurring diagnostic tools (`sim_*.py`, `audit_*.py`, `diagnose_*.py`)
stay in `dev/` even when not currently in active use — they get
re-pointed at new investigations regularly. **Exception:** a sim
that is (a) broken against current data, (b) hardcoded against a
shipped-and-stale version transition, or (c) literally pre-dates a
since-replaced data pipeline (e.g. requires raw MSBs when a
`nr_slot_inventory.json`-based successor exists) does belong here.

## Revival

If a script here needs to come back:

    git mv dev/archive/<script>.py dev/

Don't bother updating the README's archival list — `ls dev/archive/`
is authoritative.

## Current contents

| Script                             | Archived in | Why                                                                                                            |
| ---------------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------- |
| `cleanup_c8400.py`                 | v0.28.x     | One-shot data scrub for the c8400 → c5220 PCR transition. Engine-side removal of c8400 in V3_EXCLUDE shipped alongside. |
| `promote_heritage_from_mmv.py`     | v0.28.x     | One-time-batch heritage-tag promotion from `mmv_imports.json` into `nr_enemy_tags.json`. All in-scope c-prefixes promoted. |
| `verify_dcx_batch.py`              | v0.28.x     | Smoke-checker for early `dcx_batch.py` patch coverage. Superseded by `tests/test_emevd_patches.py` (75 tests). |
| `sim_cap_ab.py`                    | v0.28.x     | A/B compare of v0.25.2-vs-v0.25.3 cap state. Hardcoded `CAPS_v0_25_3` table; KeyErrors on cps added after that snapshot (e.g. `c4140`). The version transition shipped long ago. |
| `sim_cap_distribution.py`          | v0.28.x     | Catalog-only cap-distribution sim. Explicit predecessor of `dev/sim_per_run.py` per the latter's docstring ("Two refinements over the older sim_cap_distribution.py"). Zero references in code or docs. |
| `sim_reservation_health.py`        | v0.28.x     | Pre-MSB-independent reservation-pass health sim — requires `--msb-dir` with decompiled MSBs. Successor `dev/sim_new_add_health.py` does the same job from `data/nr_slot_inventory.json`, no MSBs needed. |
