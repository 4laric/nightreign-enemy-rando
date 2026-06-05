# INSTALL — first-time setup

The randomizer ships as a **self-contained me3 profile**. The whole flow is:

1. Extract the zip anywhere.
2. Run the GUI (`randomize.pyw`) and click **Randomize**.
3. Double-click **`nightreign-enemy-rando.me3`** to play.

No separate me3 profile to create, no files to copy into place, nothing to
drag anywhere. If anything here is unclear or breaks, see
[`docs/WORKFLOW.md`](docs/WORKFLOW.md) for the longer walkthrough, or open an
issue.

## What you need

- **Python 3.10 or newer.** Get it from [python.org](https://python.org). On
  Windows: tick the **"Add Python to PATH"** box during install.
- **Elden Ring Nightreign** installed via Steam.
- **me3** — the mod loader for Nightreign. Install from
  [me3-mod.github.io](https://me3-mod.github.io/). You do **not** need to
  create a profile by hand — this rando *is* one. me3 only needs to be
  installed so it can launch the bundled `.me3`.

That's it. No compiler, no SDK, no Python packages to pip-install for the
basic randomize-and-play flow.

## What's already in the box

Extract the zip anywhere (your Desktop is fine — it does not have to live in
me3's profiles folder). You get:

```
nightreign-enemy-rando/
├── nightreign-enemy-rando.me3   ← double-click this to launch NR modded
├── randomize.pyw                ← the GUI (Windows: double-click, no console)
├── randomize.sh                 ← the GUI (macOS / Linux)
├── README.md · INSTALL.md · CHANGELOG.md · PATCH_NOTES.md
├── package/                     ← what me3 loads. Ships pre-filled:
│                                   regulation.bin, script/, material/,
│                                   shader/, sfx/. (map/mapstudio/, chr/, and
│                                   event/ are created when you Randomize.)
└── _rando/                      ← the tool + bundled reference copies
                                    (me3 never looks in here)
```

The pre-patched `regulation.bin` and MMV's `aicommon` / `sfx` / `material` /
`shader` bundles are **already deployed inside `package/`** — there is nothing
to copy and no "install bundled files" step. The `.me3` already points at
`package/`. (Curious why these specific bundles? See
[Why these bundles](#why-these-bundles) at the bottom.)

## Setup, in order

### 1. Oodle DLL (usually automatic)

Nightreign compresses its `.msb.dcx` files with Oodle, so the rando needs its
DLL to read and write them. The GUI auto-detects it from your Steam NR install
and the first-run setup wizard confirms it — most people don't touch this. If
auto-detection fails, copy

```
<Steam library>/steamapps/common/ELDEN RING NIGHTREIGN/Game/oo2core_*_win64.dll
```

next to `randomize.pyw`. The exact version (`oo2core_6_win64.dll`,
`oo2core_9_win64.dll`, …) doesn't matter — anything matching the pattern works.

### 2. (Optional) Verify your environment

```
python _rando/check_setup.py
```

Checks Python version, Tk/tkinter, that the Oodle DLL loads, that the engine
and GUI import cleanly, and that the bundled vanilla MSB snapshot is intact.
Each line prints `✓` or `✗` with a hint.

### 3. Randomize

Run the GUI:

- **Windows:** double-click `randomize.pyw` — Windows runs `.pyw` with
  `pythonw`, so it opens with no console window. For the `[gui]` diagnostic
  prints used when reporting bugs, run `python randomize.pyw` from a terminal
  instead.
- **macOS / Linux:** `./randomize.sh` (or `python3 randomize.pyw`).

Set a seed for a reproducible roll, or leave it blank for a fresh random.
Click **Randomize**.

You don't pick an output folder. Because this is the self-contained profile,
the rando writes straight into its own `package/` — creating `map/mapstudio/`,
`chr/`, and `event/` as needed — and drops `_spoilers.json` (machine-readable)
and `_spoilers.md` (human summary) beside the run. The first launch may pop a
short setup wizard for your NR install path; the package itself is already set
for you, so there's no profile to point at.

### 4. (Recommended) EMEVD patches

The MSB swap puts new enemies into slots authored for specific original
occupants, so some encounters can hang (bosses idling, corpses blocking sites
of grace, spawn handlers stuck mid-animation). The bundle includes pre-patched
EMEVDs that fix the common bug classes globally.

Click **Install pre-patched EMEVD** in the GUI. In the shipped profile it
targets `package/event/` automatically and keeps `.bak` backups of anything it
replaces. If a pre-patched file doesn't apply cleanly to your NR build, use
**Apply patches manually (advanced)** and follow the on-screen flow — that path
needs [DarkScript3](https://github.com/AinTunez/DarkScript3) to decompile /
recompile.

### 5. (Optional) DLL mods — Seamless Co-op and friends

To run DLL mods alongside the rando — most commonly **Seamless Co-op** — open
the **Paths** tab → **DLL mods / natives**, click **Add DLL…**, and pick the
DLL (e.g. `nrsc.dll` from your SeamlessCoop folder). One full path per line.

Every time you Randomize, those paths are written into
`nightreign-enemy-rando.me3` as `[[natives]]`, so a **single launch runs the
rando + those DLLs together**. Point at each DLL **in its own mod folder** so
it can find its config — don't copy it into the profile.

### 6. Launch

Double-click **`nightreign-enemy-rando.me3`**. me3's file association launches
NR with the rando (and any DLL mods) active. You can also use the GUI's
**Launch** button, or flip on **auto-launch after generate** so a finished
Randomize starts the game for you.

That's the only launch path. You never drag the folder into another me3
profile — it *is* the profile, and doing so just creates a second, empty
`package/`.

Test-mode arenas are on by default, so all 19 Night 1 / Night 2 boss arenas
run the same validated minimal spawn template — any Nightlord is a safe pick.
If you turn test-mode arenas off (Diagnostic section) to get the full vanilla
cinematic intros, individual Nightlord arenas may hit EMEVD compatibility gaps
with some swaps; that mode is the opt-in/experimental path.

## When things go wrong

- **Game crashes on startup** — almost always a chr without its asset pack in
  `package/`. Check the **chr/ Inventory** tab in the GUI to see which optional
  packs (Heritage Pack, MMV) you have vs are missing, and either install them
  or exclude their c-prefixes.
- **A specific encounter is broken** — open `_spoilers.md`, find the c-prefix
  at that map+entity, exclude it via the GUI's pool membership controls, and
  re-roll. A different seed is usually faster than diagnosing a one-off.
- **`No module named 'tkinter'`** — your Python install is missing Tk. On
  Windows: re-install Python from python.org with the tcl/tk option ticked. On
  Ubuntu/Debian: `sudo apt install python3-tk`.

For more, see [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — the full troubleshooting
catalog and the manual / CLI workflows.

## <a name="why-these-bundles"></a>Why these bundles

This release ships a pre-patched `regulation.bin` (HP/damage balance, NB-arena
whitelist, contamination fixes, plus MMV's cross-game param rows so
MMV-imported chrs work out of the box), MMV's matching `aicommon` AI manifests,
MMV's `sfxbnd_c0000.ffxbnd.dcx` particle bundle, MMV's `allmaterial` material
registries, and MMV's `shaderbdle_dlc01.shaderbdlebnd.dcx` DLC shader binder —
all pre-deployed in `package/`.

They're a hard dependency for the rando's optional MMV cross-game imports,
confirmed in playtest: without `regulation.bin` the param fixes silently no-op;
without `aicommon`, DLC/cross-game chrs whose AI references DLC-only goal-table
constants freeze on spawn; without the SFX bundle, heritage/cross-game attacks
lose their particle effects (silent no-ops or broken-FFX spam); without the
material binders, those chrs render with broken/missing surfaces; and without
the shader binder, DLC material entries resolve the material but not the shader
program, so heritage chrs render black. ER's vanilla aicommon and NR's vanilla
SFX bundle are **not** substitutes. The five MMV-derived bundles are the
canonical asset base — see `bundled_regulation/README.md` for the full
rationale.

## Optional: extra enemy content (MMV)

The rando works fine with just vanilla NR + Forsaken Hollows DLC. For a wider
pool with cross-game ports, install
[More Map Variations (MMV)](https://www.nexusmods.com/eldenringnightreign/mods/578),
then toggle the **MMV** checkbox in the GUI — the rando folds MMV-imported chrs
(Malenia, Maliketh, Slave Knight Gael, Dragonslayer Armor, and more) into the
swap pool. See [`docs/MMV_INTEGRATION.md`](docs/MMV_INTEGRATION.md). Install MMV
**before** generating, so the engine knows its chrs are available targets.

## Optional: per-seed merchant-shop randomization (v0.29)

Check **Randomize merchant shop** (next to the Randomize button, on by default)
and Randomize will re-roll the expedition merchant's stock for the run seed and
write the patched `regulation.bin` into `package/`. Needs two Python packages:

    pip install cryptography zstandard

With them installed, the shop rerolls every run alongside the enemies — same
seed = same shop. If the packages are missing, the run logs a loud "SHOP NOT
RANDOMIZED" warning and skips just that stage; nothing else breaks.
`python _rando/check_setup.py` reports the packages.

## License

Code in this repository is [MIT](LICENSE). The bundled vanilla `.msb.dcx` files
(if present) are FromSoftware's game data, not covered by the MIT grant — see
`LICENSE` for the full note.