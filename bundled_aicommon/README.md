# bundled_aicommon

Shared AI script-table manifests required by cross-game and DLC chrs.

## What's here

| File                        | Source | Purpose                                                                 |
|-----------------------------|--------|-------------------------------------------------------------------------|
| `aicommon.luabnd.dcx`       | MMV    | Goal/Logic ID definitions: NR base chrs + ER DLC chrs + MMV cross-game  |
| `aicommon_dlc01.luabnd.dcx` | MMV    | DLC-only Goal/Logic ID definitions (Bayle, Mesmer, Romina, DSA, Manus)  |

These are MMV's versions and are **strict supersets** of vanilla NR's `aicommon.luabnd.dcx`:

- Every NR-defined goal-ID name is present in MMV's set with the same numeric value
- Every NR's-own DLC chr's goal is present
- Plus ER's SoTE DLC chrs (Bayle, Mesmer, Romina, Putrescent Knight, etc.)
- Plus MMV's cross-game adds (c8200 Crystal Lizard King, c8300 Dragonslayer Armor, c8500 Manus)

No name-value conflicts exist across the three sets (922 names shared between
all three, every one resolves to the same value).

## Why these need to be deployed

Without the right `aicommon` manifest in `<me3_profile>/<package>/script/`, cross-game and DLC chr AI scripts fail at registration:

- `RegisterTableGoal(GOAL_DragonGuardianKnight_316000, ...)` — first arg is a constant defined only in `aicommon_dlc01.luabnd.dcx`
- Without DLC installed, the game doesn't load its own `aicommon_dlc01.luabnd.dcx`
- The constant resolves to `nil`, registration silently fails
- The chr spawns with no goal table → **freeze**

Bundling MMV's versions sidesteps the DLC-install requirement entirely.

## When the auto-pipeline deploys these

`_chr_import` and `_chr_bulk_import` (in `oops_rando_gui.py`) copy these files to the target script directory after the per-chr `_battle.luabnd.dcx` files. As of v0.24.64, this happens automatically whenever either import flow runs.

Independently, the "Install bundled mod files" button on the Generate
tab deploys these alongside `bundled_regulation/` and `bundled_sfx/`
in one click via the BUNDLED_INSTALLS registry.

## MMV's aicommon is required, not "preferred"

v0.28.x playtest confirmed that ER's vanilla `aicommon.luabnd.dcx` is
**not** a viable substitute for MMV's. The 922-name shared base is
identical between the two, but MMV's bundle defines additional
constants that DLC and cross-game chrs' AI scripts reference at
registration time. Substituting ER's bundle produces silent
registration failures → chrs spawn with no goal table → freeze.

Previous versions of this README left this as a "pending confirmation"
caveat. As of v0.28.x it's confirmed: MMV's `aicommon` ships
permanently. The same playtest also confirmed `bundled_sfx/`'s MMV
SFX bundle is required — the three bundles (regulation + aicommon +
sfx) travel together as the canonical MMV-derived asset base.

## Regeneration

If MMV ships an aicommon update (new cross-game chrs or expanded goal tables), drop the new `.dcx` files in here, replacing the existing ones. No code change needed — the import flow reads whatever's in this directory.

## Diagnostic check

If a player reports a cross-game chr freeze or DLC-related error and the chr's `_battle.luabnd.dcx` IS in their mod folder, verify their script dir also has:

```
<me3 profile>/<package>/script/aicommon.luabnd.dcx        (~135KB, MMV-superset)
<me3 profile>/<package>/script/aicommon_dlc01.luabnd.dcx  (~5KB)
```

Missing or vanilla-sized (~75KB for NR's aicommon) → re-run a chr import after v0.24.64.
