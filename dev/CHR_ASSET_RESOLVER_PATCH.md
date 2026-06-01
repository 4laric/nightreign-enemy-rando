# Patch: chr_asset_resolver.py SHARED_DEPS update (v0.28.x)

To track the dlc02 aicommon variant alongside the existing base + dlc01
entries, replace the SHARED_DEPS list at lines 127-138 with the version
below.

## Find

```python
SHARED_DEPS = [
    ("script/", "aicommon.luabnd.dcx", "AI_REQUIRED",
     "Goal/Logic ID definitions. Vanilla NR is ~75KB; MMV-superset is "
     "~135KB. The MMV-superset is required for cross-game + DLC chrs."),
    ("script/", "aicommon_dlc01.luabnd.dcx", "AI_REQUIRED",
     "DLC-only goal-table manifest. ~5KB. Required for SOTE DLC chrs "
     "(Bayle, Mesmer, Romina, Putrescent Knight, etc.)."),
    ("material/", None, "DIR_DEPLOYED",
     "MMV's material/ dir is required for cross-game chrs whose models "
     "reference shaders/materials not in NR's base material registry. "
     "Checked at directory level — any file present satisfies."),
]
```

## Replace with

```python
SHARED_DEPS = [
    ("script/", "aicommon.luabnd.dcx", "AI_REQUIRED",
     "Core AI Goal/Logic library. Vanilla NR ships ~118 lua files; ER's "
     "is a strict superset at ~169. Importing ER's wholesale (via "
     "dev/import_aicommon_scripts.py) is safe — see that module's "
     "docstring for the replace-not-merge rationale."),
    ("script/", "aicommon_dlc01.luabnd.dcx", "AI_REQUIRED",
     "ER DLC1 goal-table manifest. ~2KB / 1-2 lua files. Vanilla NR "
     "ships nothing under this name; staging is purely additive. The "
     "ER DLC1 == SOTE on ER side (Bayle, Messmer, Romina, Putrescent "
     "Knight, etc.) — required if any heritage chr's battle script "
     "requires() a dlc01 helper."),
    ("script/", "aicommon_dlc02.luabnd.dcx", "AI_REQUIRED",
     "ER DLC2 goal-table manifest. ~31KB / ~5-10 lua files. Ships in "
     "ER but is largely vestigial in current ER releases (DLC1 is the "
     "only released DLC). Stage if your heritage chrs require() any "
     "dlc02 helpers; otherwise its absence is non-blocking."),
    ("material/", None, "DIR_DEPLOYED",
     "MMV's material/ dir is required for cross-game chrs whose models "
     "reference shaders/materials not in NR's base material registry. "
     "Checked at directory level — any file present satisfies."),
]
```

## What changed

1. Base aicommon doc updated to current vocabulary (lua-files count vs
   stale "75KB / 135KB" sizes), references the importer script that's
   the recommended way to stage it.

2. dlc01 doc updated: corrects "DLC-only" (which was vague) to "ER DLC1
   == SOTE", and clarifies that NR ships NOTHING at this filename so
   staging is purely additive (not a replace).

3. dlc02 added as a new SHARED_DEPS entry. The preflight CLI / chr
   asset resolver will now surface dlc02 absence as an AI_REQUIRED gap,
   same severity class as the other two. The doc clarifies that dlc02
   is largely vestigial in ER releases so its absence is "non-blocking"
   — note the chr_asset_resolver's AI_REQUIRED → freeze (not CTD) class
   so worst case is a chr that needs a dlc02 helper sits idle.

## What does NOT need to change

- `_HARD_SEVERITIES`, `_CTD_SEVERITIES`, `_AI_SEVERITIES` — these are
  sets of severity strings, and dlc02 reuses the existing AI_REQUIRED
  severity. No additions needed.

- check_chr() — iterates SHARED_DEPS, so adding a new entry there
  is automatically picked up.

- audit_chr_assets_vs_roster.py — consumes chr_asset_resolver's output,
  no changes needed.
