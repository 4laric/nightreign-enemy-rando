# v0.28.0 — what's new

## No more UXM unpacking

The big one: **you no longer need to UXM-unpack your games.** The rando now
reads the vanilla files it needs directly out of your installed copy.

- **Nightreign shuffle:** just point the GUI at your Nightreign `Game/`
  folder on the Generate tab — packed install, straight from Steam, is
  fine. The vanilla maps are read out of the game's archives on your first
  run and cached locally; every run after that reuses the cache.
- **Elden Ring heritage imports:** the heritage dev tools can now read boss
  chr and AI-script files straight from a packed Elden Ring install too
  (`--source-game`), including the Shadow of the Erdtree bosses. No 50 GB
  unpack of either game.

Nothing copyrighted ships in the download — all game data is read from your
own legally-owned install at run time.

## Setup is quieter and more forgiving

- A **packed install no longer trips the Setup Status warning.** "Nightreign
  install" and "Elden Ring install" go green as soon as you point them at a
  real `Game/` folder, unpacked or not.
- The **Paths tab no longer shows the vanilla read-path rows up front** —
  they fill in automatically. They're still there as optional overrides,
  tucked into a collapsible "Vanilla read-path overrides" section if you
  ever need to point at, say, a previous shuffle's maps.
- **me3 package auto-detect:** if you accidentally pick the *parent* of your
  me3 package folder (and that folder is the only package-shaped thing in
  it), the GUI now descends into it for you instead of writing output one
  level too high.

## Fixes in this build

- Manus (c8500) is now correctly held out of the shuffle when MMV is active.
  It had a relocation freeze (a phase-transition that locks up when the boss
  isn't in its home arena), so it's excluded rather than risking a stuck
  encounter.

## Still required

You still need the Oodle DLL (`oo2core_*.dll`) copied next to the tool — it's
needed to decompress the game's `.dcx` files. Everything else now comes from
your install automatically.

---

# v0.26.8 — what's new

User-facing release notes for the v0.26.8 ship. For the engineering-level
detail, see `CHANGELOG.md` (per-version rollup) and `SHIP_NOTES.md`
(files-in-this-bundle manifest).

This covers everything since v0.25.0. The v0.26.x series is one arc: a big
v0.26.1 engine release for boss placement quality, then a run of fixes and
quality-of-life changes driven by fresh-install playtesting on Windows.

## Headline changes

### Zero-setup install

The bundle now ships with `vanilla_msbs/` — 300 vanilla Nightreign map
files — included. You no longer need to UXM-unpack your own NR install
before generating seeds. Install, point the output at your me3 profile,
click Randomize. The GUI's input folder already defaults to the bundled
maps.

This also means the old "Vanilla mapstudio" path field is no longer
needed for normal use — the 23 spawn-pool maps that drive rotation-pool
bosses (Bell-Bearing Hunter at Castle Basement, Tree Sentinels, Death
Rite Bird, etc.) are in the bundle, so those bosses are randomized
automatically. The field is now only relevant if you deliberately point
the rando at your own NR install instead of the bundled maps.

### Test-mode arenas, on by default

The 19 Night 1 / Night 2 boss arenas now run a minimal boss-spawn
template by default: boss spawns, you kill it, night advances. No
cinematic, no wake choreography, no per-Nightlord scripted quirks.

This started as a diagnostic tool to cut engine-validation playtest
cycles from ~18 hours to ~1, but it's now the recommended way to play
the current build — every arena behaves identically and predictably, so
swapped bosses don't get stuck mid-cinematic or fail to wake. Because
this is on by default, the old "pick Tricephalos (Gladius) until other
arenas are validated" recommendation banner has been removed — with
test-mode arenas active, any Nightlord is a safe pick.

If you want the full vanilla cinematic boss experience, the toggle is in
the Diagnostic section of the GUI (collapsed by default — expand it and
uncheck "Test-mode arenas").

Augur (m47_70) is the one exception — its descent doesn't fit the
template, so test-mode runs that roll Augur as the Nightlord still get
vanilla Augur Night 1.

### Better boss placement (v0.26.1 engine work)

The big engine release of this arc. Several changes that together make
marquee Night Boss-tier enemies — Midra, Romina, Maliketh, Fortissax,
Metyr, Dragonslayer Armor, and the rest — show up reliably and at varied
locations from seed to seed:

- **Floor/ceiling reservation system.** The marquee NB roster now gets a
  guaranteed floor (at least one placement per seed) and a ceiling (at
  most two). Previously a narrow-pool boss could just fail to place on
  an unlucky seed.

- **Terrain-derived arenas.** A new audit reads per-slot navmesh data
  and identifies 147 additional "big and flat" slots that can host a
  boss fight even though their vanilla occupant wasn't a boss. The arena
  pool roughly doubled (104 to 251 slots), so big bosses land in more
  varied places — Giant Crab clearings, Mad Pumpkin Head plazas, open
  flats — instead of recycling the same handful of arenas.

- **Size-class corrections.** An audit against the game's own hitbox
  data found that 18 modded-roster enemies were tagged smaller than they
  actually are. Romina, Maliketh, Fortissax, Radahn, and others were
  corrected, which fixes cases where they'd be placed at slots too small
  for their real footprint.

- **Fairer placement order.** The reservation pass no longer processes
  bosses biggest-first — that ordering quietly pushed narrow-pool
  human-sized bosses to the back of the queue where they lost slot
  contention. It's now random per seed, so every boss gets an equal
  shot.

### Reliability fixes

A run of bugs surfaced by fresh-install playtesting on Windows, now
fixed:

- **GUI no longer hangs on first launch.** The first-launch setup wizard
  could come up invisible on Windows — the app would print "starting..."
  and then appear to freeze. Fixed.

- **Windows text-encoding crash fixed.** Toggling the MMV checkbox (and
  potentially other actions) could fail on Windows with a "charmap codec
  can't decode" error, because data files contained characters Windows'
  default encoding couldn't read. Every file the rando reads now uses
  UTF-8 explicitly.

- **Randomize button works.** A missing internal method made every click
  of Randomize throw an error before the run started. Fixed, with a test
  that catches this whole class of bug going forward.

- **A crash during map processing** (`KeyError: 'cp'`) introduced by the
  new terrain-arena work is fixed — it triggered whenever model
  compaction ran on a map containing terrain-derived arena slots.

### Windows quality-of-life

- **No more stray console window.** Launching the GUI no longer leaves a
  command-prompt window sitting in front of it, and the ME3 launch no
  longer pops its own console.

- **Double-click launchers.** The bundle now includes `Launch.bat` and
  `oops_rando_gui.pyw` — either one opens the GUI directly with no
  terminal, for users who'd rather not type a `python` command.

- **The mode selector is harder to flip by accident.** The run-mode
  dropdown (Standard / Oops! All / etc.) used to change if you scrolled
  the mouse wheel over it — easy to do while scrolling the window, and
  it would silently switch you into a destructive "Oops! All" mode.
  Scroll no longer changes it, and switching into an Oops! All mode now
  asks for confirmation.

### Engine fingerprint

Spoilers from this build stamp `"engine_fingerprint": "v0.26.8"`. If
your spoiler still says an older version, you're on a stale install —
verify the new `oops_v3.py` landed and that no `__pycache__/` directory
is shadowing it.

## Note for testers

The five test-mode-arena integration tests are currently marked
`xfail` (expected-fail) — they were written for the previous arena
generation and need rewriting for the current v0.29-v8 generation. This
is tracked and intentional; it doesn't affect the shipped build, only
the dev test suite's bookkeeping.
