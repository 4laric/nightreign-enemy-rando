# Nightreign Enemy Randomizer

A boss and enemy randomizer for Elden Ring: Nightreign. It shuffles the
enemies and Night Bosses placed across every map, so each seed plays
differently — Maliketh in a Giant Crab clearing, an Erdtree Avatar where
a Tree Sentinel used to be, a different Nightlord fight every run.

Current release: **v0.28.0**. For what changed, see `PATCH_NOTES.md`
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
5. Launch the GUI: double-click `oops_rando_gui.pyw`, or run
   `python oops_rando_gui.py` from a terminal (use this one for
   diagnostic output).
6. On the **Generate** tab, point "Nightreign install" at your NR `Game/`
   folder (packed is fine — no UXM unpack needed) and "ME3 mod profile" at
   your me3 package. The output dir and vanilla read-paths auto-fill (and
   if you accidentally pick the package's parent folder, it descends into
   the package for you). Click Randomize, then **Install pre-patched EMEVD**.

You do **not** need to UXM-unpack your install. The GUI reads vanilla map
and event data straight from your own Nightreign install's `.bhd`/`.bdt`
archives at run time — packed or unpacked, auto-detected — so this bundle
ships no FromSoftware game data. Point the GUI at your NR install and click
Randomize; the maps are pulled from the archives on the first run and cached
locally.

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
- **No UXM unpack required.** Vanilla map/event data is read directly from
  your installed Nightreign copy's archives, and heritage chr/AI-script
  imports can read straight from a packed Elden Ring install (the dev
  tools' `--source-game`). You never have to unpack tens of GB of game
  files for either game.
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

**This bundle ships no FromSoftware game data.** Vanilla map, event, and
chr data is read at run time from your own legally-owned install — never
redistributed here. (The optional `vanilla_msbs/` fallback folder ships
empty; you don't need to populate it.) You must own licensed copies of the
games whose data you read. See [LICENSE](LICENSE) for the full note.

## Dedication

*In loving memory of Toast (2009–2026) — sixteen years of good company,
asleep on my lap through every late-night build.*
