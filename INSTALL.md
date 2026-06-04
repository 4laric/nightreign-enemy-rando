# INSTALL — first-time setup

This is the one-page beeline for getting the rando running. If anything
here is unclear or breaks, see [`docs/WORKFLOW.md`](docs/WORKFLOW.md) for
the longer walkthrough, or open an issue.

## What you need

- **Python 3.10 or newer.** Get it from [python.org](https://python.org).
  On Windows: tick the "Add Python to PATH" box during install.
- **Elden Ring Nightreign** installed via Steam.
- **me3** — the mod loader for Nightreign. Install from
  [me3-mod.github.io](https://me3-mod.github.io/) and follow its docs to
  set up at least one profile. (A me3 profile is just a folder structure
  that mirrors the game; me3 substitutes any files it finds at runtime.)

That's it. No compiler, no SDK, no Python packages to pip-install.

## Optional tools (for advanced workflows)

These aren't needed for the basic randomize-and-play flow — the rando
ships with bundled vanilla MSBs and uses your me3 profile as the
output target. You only need these if you want to do more than the
default flow:

- **[UXM Selective Unpacker](https://github.com/Nordgaren/UXM-Selective-Unpack)**
  by Nordgaren — unpacks `.bhd`/`.bdt` archives into a loose-file
  layout the rando can read. Needed if you want to:
  - Generate from a non-bundled NR snapshot (e.g. a newer game patch).
  - Import heritage chrs from Elden Ring (the Elden Ring Assets tab
    needs an UXM-unpacked ER install).
  - Inspect / patch EMEVDs by hand.
- **[WitchyBND](https://github.com/ividyon/WitchyBND)** by ividyon —
  unpacks individual FromSoftware file formats once UXM has extracted
  the archives. The rando handles `.msb.dcx` natively, but Witchy is
  useful for inspecting other formats (chrbnd, etc.).

## Setup, in order

### 1. Get the Oodle DLL

Nightreign compresses its `.msb.dcx` files with Oodle, so we need its
DLL to read and write them. Steam puts it here:

```
<Steam library>/steamapps/common/ELDEN RING NIGHTREIGN/Game/oo2core_*_win64.dll
```

Copy that file into the same folder as this README. The exact filename
version (`oo2core_6_win64.dll`, `oo2core_9_win64.dll`, etc.) doesn't
matter — anything matching the pattern works.

### 2. Verify your environment

From this folder:

```
python check_setup.py
```

This checks Python version, that Tk/tkinter works, that the Oodle DLL
loads, that the engine and GUI import cleanly, and that the bundled
vanilla MSB snapshot is intact. Each check prints `✓` or `✗` with a
hint if something's wrong.

If everything is `✓`, continue. If anything is `✗`, fix it before going
on — the rest of the steps assume the environment is healthy.

### 3. Run the GUI

**Windows (recommended — no command prompt window):**

Double-click `oops_rando_gui.pyw` — Windows runs `.pyw` files with `pythonw`, so the GUI opens with no console window.

Or from PowerShell with no console window:
```
pythonw .\oops_rando_gui.py
```

For terminal output (the `[gui]` diagnostic prints used when reporting
bugs), use `python` instead:
```
python .\oops_rando_gui.py
```

**macOS / Linux:**

```
python3 oops_rando_gui.py
```

You'll see fields for input directory (default: the bundled
`vanilla_msbs/`) and output directory. Pick an output directory inside
your me3 profile — it should look something like:

```
<me3 profile>/<package>/map/mapstudio/
```

That's where me3 expects to find replacement `.msb.dcx` files.

Set a seed if you want a reproducible roll, or leave it blank for a
fresh random. Click **Randomize**.

When it finishes:
- Patched `.msb.dcx` files are written to the output directory.
- A `_spoilers.json` (machine-readable) and `_spoilers.md` (human-
  readable summary) appear next to them.

### 4. Install the EMEVD patches (recommended)

The MSB swap puts new enemies into slots that were authored for
specific original occupants, so encounters can hang in odd ways
(bosses idling, corpses blocking sites of grace, spawn handlers stuck
mid-animation). The bundle includes pre-patched EMEVDs that fix the
common bug classes globally.

In the GUI, click **Install pre-patched EMEVD**. Pick your me3
profile's `event/` directory when prompted (typically
`<me3 profile>/<package>/event/`). It copies the pre-patched files
there with `.bak` backups of any existing files.

If the pre-patched file doesn't apply cleanly to your NR build, use
**Apply patches manually (advanced)** and follow the on-screen flow.
That requires [DarkScript3](https://github.com/AinTunez/DarkScript3)
to decompile / recompile.

### 5. Drop the bundled regulation + aicommon + sfx + material + shader files into your profile

This release ships a pre-patched `regulation.bin` (HP/damage balance,
NB-arena whitelist, contamination fixes, plus MMV's cross-game param
rows so MMV-imported chrs work out of the box), MMV's matching
`aicommon.luabnd.dcx` AI manifests, MMV's `sfxbnd_c0000.ffxbnd.dcx`
particle-effect bundle, MMV's `allmaterial.matbinbnd.dcx`
material/shader registries, and MMV's `shaderbdle_dlc01.shaderbdlebnd.dcx`
DLC shader binder. Copy them into your me3 profile package:

```
<me3 profile>/<package>/regulation.bin                            ← from bundled_regulation/
<me3 profile>/<package>/script/aicommon.luabnd.dcx                ← from bundled_aicommon/
<me3 profile>/<package>/script/aicommon_dlc01.luabnd.dcx
<me3 profile>/<package>/sfx/sfxbnd_c0000.ffxbnd.dcx               ← from bundled_sfx/
<me3 profile>/<package>/material/allmaterial.matbinbnd.dcx        ← from bundled_material/
<me3 profile>/<package>/material/allmaterial_dlc01.matbinbnd.dcx
<me3 profile>/<package>/shader/shaderbdle_dlc01.shaderbdlebnd.dcx ← from bundled_shader/
```

The "Install bundled mod files" button on the Generate tab does all
seven copies in one click — it reads the package destination from
your saved me3 path and handles `.bak` backups for any existing
files. Starting in v0.28.2 the Randomize button also pre-flights
this: if any bundle is missing it prompts you to install before the
run kicks off.

Without `regulation.bin` deployed, the param-level fixes (HP nerfs,
damage clips, NB whitelist routing, etc.) silently no-op and you'll
get vanilla MMV behavior. Without the `aicommon` files, DLC and
cross-game chrs whose AI scripts reference DLC-only goal-table
constants will freeze on spawn. Without `sfxbnd_c0000.ffxbnd.dcx`,
heritage / cross-game chr attacks lose their particle effects —
sometimes silent no-ops, sometimes broken-FFX-reference spam.
Without the `allmaterial.matbinbnd.dcx` files, heritage / cross-game
chr models that reference shaders or materials outside NR's base
material registry render with broken / missing surfaces or fail to
load entirely. Without `shaderbdle_dlc01.shaderbdlebnd.dcx`, DLC
material entries that point at DLC-only shader IDs resolve the
material but can't resolve the shader program — the affected
heritage chrs render with broken / black surfaces even when the
material binders are in place.

**Why MMV's bundles and not vanilla NR's?** All five bundles ship
the assets that the rando's optional MMV cross-game imports need to
address. v0.28.x playtest confirmed this is a hard dependency: ER's
vanilla aicommon is **not** a substitute (DLC chr goal-tables fail
to register), and vanilla NR's SFX bundle doesn't carry the FFX
entries cross-game chrs reference. The five MMV-derived bundles
ship together as the canonical asset base — see
`bundled_regulation/README.md` for the full rationale.

### 6. Launch through me3

Start NR via me3 with your profile selected. The randomized world
should load.

Test-mode arenas are on by default, so all 19 Night 1 / Night 2 boss
arenas run the same validated minimal spawn template — any Nightlord is
a safe pick. If you turn test-mode arenas off (Diagnostic section) to
get the full vanilla cinematic intros, individual Nightlord arenas may
hit EMEVD compatibility gaps with some swaps; that mode is the
opt-in/experimental path.

## When things go wrong

- **Game crashes on startup** — almost always a chr without its asset
  pack on your me3 profile. Check the chr/ Inventory tab in the GUI
  to see which optional packs (Heritage Pack, MMV) you have vs are
  missing, and either install them or exclude their c-prefixes.
- **A specific encounter is broken** — open `_spoilers.md`, find the
  c-prefix at that map+entity, exclude it via the GUI's "Excluded
  Enemies" tab, and re-roll. Re-rolling with a different seed is
  usually faster than diagnosing a one-off.
- **"`No module named 'tkinter'`"** — your Python install is missing
  Tk. On Windows: re-install Python from python.org with the tcl/tk
  option ticked. On Ubuntu/Debian: `sudo apt install python3-tk`.

For more, see [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — full
troubleshooting catalog and the manual / CLI workflows.

## Optional: extra enemy content

The rando works fine with just vanilla NR + Forsaken Hollows DLC. If you
want a wider enemy pool with cross-game ports, install
[More Map Variations (MMV)](https://www.nexusmods.com/eldenringnightreign/mods/578)
into your me3 profile. The rando can fold MMV-imported chrs (Malenia,
Maliketh, Slave Knight Gael, Dragonslayer Armor, and more) into the swap
pool — toggle it on with the MMV checkbox in the GUI. See
[`docs/MMV_INTEGRATION.md`](docs/MMV_INTEGRATION.md) for details.

Install MMV to your me3 profile **before** generating the rando output,
so the engine knows its chrs are available targets.

## Optional: per-seed merchant-shop randomization (v0.29)

Check **Randomize merchant shop** (next to the Randomize button, on by
default) and Randomize will re-roll the expedition merchant's stock for the
run seed and write the patched `regulation.bin` into your me3 package. Needs
two Python packages:

    pip install cryptography zstandard

With them installed (and the me3 package path set), the shop rerolls every run
alongside the enemies - same seed = same shop. If the packages or the package
path are missing, the run logs a loud "SHOP NOT RANDOMIZED" warning and skips
just that stage; nothing else breaks. `python check_setup.py` reports the
packages.

## License

Code in this repository is [MIT](LICENSE). The bundled vanilla
`.msb.dcx` files (if present) are FromSoftware's game data, not
covered by the MIT grant — see `LICENSE` for the full note.
