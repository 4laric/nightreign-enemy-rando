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

Double-click `Launch.bat` — uses `pythonw` to run the GUI without a console window.

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

### 5. Launch through me3

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

## License

Code in this repository is [MIT](LICENSE). The bundled vanilla
`.msb.dcx` files (if present) are FromSoftware's game data, not
covered by the MIT grant — see `LICENSE` for the full note.
