# Workflow guide

This is the **longer** walkthrough — the manual / CLI flows, the
EMEVD patcher internals, and the full troubleshooting catalog. For a
quick first-time setup, see [`../INSTALL.md`](../INSTALL.md) at the
project root.

Three layers in this rando, each independent. Use what you want.

## Layer 1 — Enemy randomization (required)

The MSB rando. Swaps enemies within Nightreign's existing world layout.

### Setup

1. Find Nightreign's Oodle DLL. It's at:
   ```
   <Steam library>/steamapps/common/ELDEN RING NIGHTREIGN/Game/oo2core_*_win64.dll
   ```
2. Copy it into the same folder as this bundle's Python files. The exact filename
   doesn't matter — `oo2core_6_win64.dll`, `oo2core_9_win64.dll`, anything with
   that pattern works.
3. Verify the whole environment is healthy:
   ```
   python check_setup.py
   ```
   This checks Python version, Tk, the Oodle DLL, and that the engine
   and GUI import. Each line is a clear ✓ or ✗ with a hint if anything's
   wrong. (If you'd rather just verify Oodle in isolation, the
   lower-level harness `dev/test_oodle.py <some.msb.dcx>` does
   roundtrip decompress/recompress on a single file.)

### Generate

```
python oops_rando_gui.py
```

Or via CLI:

```
python dcx_batch.py rando \
  "<NR install>/Game/map/mapstudio" \
  ./output --seed 42
```

### Cluster handling

The GUI's "Clusters" dropdown controls how multi-Part encounters (paired
bosses, rider+mount combos, Crystalian Alliance trios, paired Tendrils, etc)
get randomized:

- **Vanilla clusters (safest)** — default. Multi-Part encounters are left
  vanilla; only solo Parts get randomized. Every cluster encounter plays
  exactly as designed. Recommended for first run.
- **Coordinated swap (more variety)** — every member of a cluster becomes
  the same new c-prefix. Paired Tendrils → paired (something else). More
  variety than vanilla, but loses rider+mount semantics — a cluster of two
  different enemies all becomes the same enemy.
- **Shape-matched (best fidelity)** — uses a catalog of every vanilla cluster
  shape (235 across 38 unique signatures) and pairs source members to target
  members of matching size+locomotion. Rider+mount becomes a different
  rider+mount. Maximum variety with minimum semantic loss.

CLI equivalents: no flag = vanilla; `--randomize-clusters` = coordinated;
`--cluster-shape` = shape-matched.

This produces:
- A folder of patched `.msb.dcx` files in `./output`
- A `_spoilers.json` listing every swap
- A `_spoilers.md` human-readable summary

### Install

Drop the `.msb.dcx` files into your me3 profile under `<package>/map/mapstudio/`.

If you don't have a me3 profile yet, see the me3 docs for setup. The short
version: a profile is a directory tree that mirrors the game's layout, and me3
substitutes any files it finds at runtime.

## Layer 2 — EMEVD patches (recommended)

The rando swaps enemies into slots whose encounter scripts were tuned for the
original occupants. When the new occupant doesn't match (different animation
library, different AI behavior, different state machine), encounters can hang in
ways that range from cosmetic to game-breaking.

The EMEVD patcher fixes the four main bug classes by editing
`common_func.emevd.dcx` (the central event-handler library that all maps call
into). One file edit, one recompile, fixes apply game-wide.

### Setup

You need DarkScript3 (the .NET EMEVD IDE by AinTunez and TheFifthMatt that
compiles/decompiles Sekiro/ER/NR EMEVDs). Install it from
[its repo](https://github.com/AinTunez/DarkScript3).

### Install via the GUI (recommended)

The bundle includes pre-patched EMEVDs in `patched_emevd/`:
- `common_func.emevd.dcx` (the global handler library, applies 5 patch
  classes with 68 substitutions total)
- 5 per-map files (`m30_30_00_00.emevd.dcx`, `m38_10_00_00.emevd.dcx`,
  `m60_43_37_00/10/20.emevd.dcx`) for maps with inline event scripts
  that the common_func patches can't reach. See `patched_emevd/README.md`
  for what each per-map file fixes.

Use the **Install pre-patched EMEVD** button in the main GUI window. It does:

1. Asks you to pick your me3 profile's `event/` directory.
2. Copies all `*.emevd.dcx` files from `patched_emevd/` there. Any existing
   files at that location are backed up to `*.bak` first.

That's it. One click after picking the destination.

### Apply via the GUI (advanced)

If our pre-patched file doesn't apply (your NR install may be a different
build than we patched against), use the **Apply patches manually (advanced)**
button. It runs a guided flow:

1. Pick your vanilla `common_func.emevd.dcx` and the destination directory.
2. The button copies vanilla into a temp working directory and opens File
   Explorer there.
3. A dialog asks you to decompile the file with DarkScript3 (drag-drop into
   DarkScript3, Ctrl+S). Click OK when done.
4. The patcher runs automatically against the resulting `.js`.
5. A second dialog asks you to recompile with DarkScript3. Click OK when done.
6. The patched `.dcx` is copied to your destination directory. Existing files
   there are backed up to `*.bak`.

You can also do this manually via the CLI, see below.

### Apply via the CLI (manual)

`emevd_patch.py` currently patches `common_func.emevd.dcx` only. The
per-map files in `patched_emevd/` were patched separately via
DarkScript3-edited `.js` files, and there is no automated re-patcher
for them yet. If you're rebuilding from a fresh vanilla, you'll need
to copy the bundled per-map files as-is (or hand-edit the .js files
in DarkScript3 if your NR build version differs).

For `common_func`:

1. Decompile the vanilla EMEVD:
   ```
   cd "<NR install>/Game/event"
   DarkScript3.exe common_func.emevd.dcx
   ```
   Produces `common_func.emevd.dcx.js` next to it.

2. Run the patcher (from this bundle's folder):
   ```
   python emevd_patch.py patch "<NR install>/Game/event" ./patched_emevd
   ```
   Output is a folder with just one modified file (the rest are skipped).

3. Recompile the patched JS:
   ```
   DarkScript3.exe ./patched_emevd/common_func.emevd.dcx.js
   ```
   Produces `common_func.emevd.dcx`.

4. Drop the recompiled `.dcx` into your me3 profile under `<package>/event/`.

### What it patches

Run `python emevd_patch.py list` to see the current set. Summary:

- **death_timeout** — 5-second escape from `WaitFor(CharacterDead)` hangs. Fixes
  killed bosses that don't drop runes / persistent corpses blocking Sites of
  Grace.
- **permissive_boss_wake** — adds Recognition / Alert / damage-taken triggers to
  encounter activation handlers. Fixes bosses that don't activate when their
  vanilla wake conditions don't match the swapped enemy.
- **permissive_spawn_emerge** — forces AI activation after spawn-emerge animations
  in 25+ handlers. Fixes the "dormant tunnel mob" / "frozen mining enemy" /
  "field boss won't engage" bug class.
- **disable_corpse_collision** — force-disables collision at HP=0. Belt-and-
  braces for the Sites-of-Grace blockage symptom.

All patches are conservative (logical OR additions, timeout fallbacks, no
behavioral removals). Vanilla play with these patches loaded is functionally
identical except for slightly more permissive boss wake conditions.

## Performance

The decompress and compress phases (~600 file operations total at the
default content level) are **parallelized across CPU cores** as of
v0.23.71. On modern hardware the full pipeline typically takes under
ten seconds end-to-end.

**Tuning knob:** the worker count defaults to `min(8, os.cpu_count())`.
Override with the `DCX_BATCH_WORKERS` environment variable:

```
DCX_BATCH_WORKERS=12 python oops_rando_gui.py   # bash/zsh
$env:DCX_BATCH_WORKERS=12 ; python oops_rando_gui.py   # PowerShell
set DCX_BATCH_WORKERS=12 && python oops_rando_gui.py   # cmd.exe
```

Setting it to `1` forces serial execution — useful for debugging since
failures print in a predictable order with no inter-thread interleaving.
Setting it higher than your physical core count rarely helps and can
hurt on machines with hyperthreading (Oodle saturates physical cores
fully; SMT siblings just contend for the same execution units).

## Troubleshooting

### "ERROR: 'charmap' codec can't encode character"

Windows default encoding choking on a non-ASCII char. Fixed in current release. If you see
it, you're running an old version — re-grab the bundle.

### Oodle DLL not found

Make sure `oo2core_*_win64.dll` is in the same directory as the Python scripts.
The DLL name pattern is `oo2core_<version>_win64.dll` — version doesn't matter,
glob picks any.

### Game crashes on startup with rando installed

Most likely a Nightlord c-prefix slipped through default exclusions. Verify
you're on the latest bundle (Nightlord exclusions are synced between backend and
GUI). If still crashing, check `_spoilers.md` for any boss-tier swaps
involving c75XX-c79XX or c4900/c4901 — those should be empty.

### Specific encounter still buggy after EMEVD patches

The EMEVD patcher covers the major dispatcher-pattern handlers. Some encounters
have inline event scripts in per-map EMEVDs that we don't touch. Workarounds:

- Find the offending c-prefix in `_spoilers.md`, exclude it via the GUI's
  "Excluded Enemies" tab, re-roll
- Re-roll with a different seed
- Submit a bug report with map+entity_id and we'll narrow the patch

### "Tanky point in space" after killing a boss

Rare residual collision capsule from a model-load failure. Usually clears on
fast-travel or Site of Grace rest. If it permanently blocks progress, narrowly
exclude the offender's c-prefix.

### GUI shows fewer enemies in dropdown than expected

The picker filters out Nightlord-tier and event-locked enemies that always crash
when placed in random slots. To see the full list, check `nr_enemy_roster.json`.
