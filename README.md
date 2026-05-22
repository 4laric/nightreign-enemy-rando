# Nightreign Enemy Randomizer

A boss and enemy randomizer for Elden Ring: Nightreign. It shuffles the
enemies and Night Bosses placed across every map, so each seed plays
differently — Maliketh in a Giant Crab clearing, an Erdtree Avatar where
a Tree Sentinel used to be, a different Nightlord fight every run.

Current release: **v0.26.10**. For what changed, see `PATCH_NOTES.md`
(user-facing release notes) and `CHANGELOG.md` (full per-version
history).

## Install

`INSTALL.md` has the full walkthrough. The short version:

1. Install **Python 3.10 or newer** (on Windows, tick "Add Python to
   PATH" during install) and set up a me3 profile for Nightreign.
2. Unzip this bundle anywhere.
3. Copy your game's Oodle DLL — `oo2core_*_win64.dll`, from the
   Nightreign `Game/` folder — into the bundle folder.
4. Run `python check_setup.py` to confirm the environment is healthy.
5. Launch the GUI: double-click `Launch.bat` or `oops_rando_gui.pyw`,
   or run `python oops_rando_gui.py` from a terminal (use this one for
   diagnostic output).
6. Point the output at your me3 profile's `map/mapstudio/` directory,
   click Randomize, then click **Install pre-patched EMEVD**.

The bundle ships `vanilla_msbs/` — 300 vanilla Nightreign map files — so
you do **not** need to UXM-unpack your own install first. The GUI's
input folder defaults to the bundled maps.

## What it does

- **Enemy + boss shuffle.** Every catalogued MSB enemy/boss slot can be
  swapped. Marquee Night Bosses (Midra, Romina, Maliketh, Fortissax,
  Metyr, and the rest) get a reservation floor/ceiling so they appear
  reliably and at varied locations from seed to seed.
- **Test-mode arenas (on by default).** The 19 Night 1 / Night 2 boss
  arenas run a minimal spawn template — boss spawns, you kill it, night
  advances — so swapped bosses behave predictably in every arena.
  Toggle off in the Diagnostic section for the full vanilla cinematic
  experience. Augur (m47_70) always runs vanilla; its descent doesn't
  fit the template.
- **Oops! All modes.** Replace every slot — or every Night Boss slot —
  with a single chosen enemy. Switching into an Oops mode asks for
  confirmation first.
- **Cross-game imports.** With MMV in your me3 profile, the target pool
  includes cross-game boss imports (ER, SoTE, DS3, DS1). The heritage
  pack adds ~47 SoTE chr prefixes.
- **Spoiler logs.** Every run writes a spoiler so you can see — or
  derandomize — what landed where.

## Project docs

- `PATCH_NOTES.md` — user-facing release notes.
- `CHANGELOG.md` — full per-version engineering history.
- `docs/TODO.md` — open work and deferred features.
- `docs/OPEN_ISSUES.md` — investigation threads carried across sessions.
- `docs/` — deeper design notes (EMEVD patches, MMV integration,
  mounted-boss architecture, healthbar rewrite, and more).

## License

The rando code, GUI, data catalogs, and authored content in this
repository are released under the [MIT License](LICENSE). Do whatever
you want; just keep the copyright notice; no warranty.

**Bundled vanilla `.msb.dcx` files are FromSoftware's, not mine.** The
`vanilla_msbs/` directory contains copyrighted game map data, included
as a convenience for people who own Nightreign. If you don't own a
licensed copy, delete that folder and point the GUI at your own NR
install. See [LICENSE](LICENSE) for the full note.
