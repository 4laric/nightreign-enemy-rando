# v0.28.3 (unreleased) — what's new

## DLC heritage chr surfaces fixed

v0.28.2 added MMV's material binders, which got DLC-heritage chr
materials *resolving* to a shader ID. But the shader binder NR
ships in vanilla was missing the actual programs those IDs name, so
DLC-heritage chrs still rendered with broken or black surfaces.
v0.28.3 bundles MMV's `shaderbdle_dlc01.shaderbdlebnd.dcx` (the
compiled shader programs themselves) to close the loop. The "Install
bundled mod files" button now does seven copies in one click; five
bundles travel together (regulation + aicommon + sfx + material +
shader).

## Generate tab pre-flights bundled-file installation

Click Randomize without the bundled mod files installed and you
now get a 3-button modal listing exactly what's missing, with
options to install first, run anyway, or cancel. The same check
runs in the passive compatibility banner on the Generate tab, so
you can spot the issue without clicking Randomize. Skipped when
the me3 package path isn't set — same don't-block behavior the
banner has for that case.

## Import Elden Ring panel: two field-handling fixes

- The "Elden Ring folder" field now auto-populates from the wizard.
  Previously the wizard set the path internally but the panel
  rendered empty, forcing you to re-paste the same value.
- The "me3 mod folder (target)" field no longer gets a stray `/chr`
  suffix appended automatically. The panel's tooltip + helper text
  documented this field as the package root; the auto-derive was
  contradicting that by adding `/chr`, causing the importer to
  produce a nested `<root>/chr/chr` directory where files landed
  one level too deep and the game saw nothing. If your saved
  setting still has `/chr` on the end from a previous launch, the
  importer's smart-resolver handles it correctly now; or just clear
  the field once and the re-derive picks the right root.

## Heritage importer trims down

The Import roster button no longer bulk-copies MMV's `material/`
directory wholesale. The material binders that the heritage chrs
actually need now ship via `bundled_material/` + `bundled_shader/`
and deploy through the install button. The importer used to dump
~GB of `material/` files into your me3 package as a side effect;
now it copies only chr + script + sfx + sd assets (still bulk for
sfx/sd, per-roster for chr/script). The import-results display
notes that material/shader live behind the install button now.



## Heritage chrs look right out of the box

**MMV's material binders now bundle with the rando.** The shipped
"Install bundled mod files" button copies one more thing to your
profile, `<package>/material/allmaterial.matbinbnd.dcx` (+ DLC). Without
these, heritage / cross-game chrs whose models reference shaders
outside NR's base material registry rendered with broken or missing
surfaces. Now they don't. The four bundles — regulation + aicommon +
sfx + material — are the canonical MMV-derived asset base; the
install button does all six file copies in one click.

## Particle effects fixed on base chrs too

The bundled SFX is back to the full MMV bundle (~182 MB, up from the
trimmed ~28 MB that shipped in v0.28.1). The trim missed FFX
references on **base NR chrs** — some of vanilla's own particle
effects were broken without the full bundle deployed. v0.28.2 ships
the full bundle to restore those. The "Install bundled mod files"
button copies it for you; if you previously installed it the .bak
backup path handles the overwrite the same way it does for the other
bundles.

## Two chrs pulled from the rotation

- **Rennala, Queen of the Full Moon** no longer appears in random
  placements. Her field-trip transition (the prelude before the boss
  room) doesn't replicate outside her original encounter, so the
  fight doesn't actually work at a random arena.
- **Giant Crayfish** also pulled, pending a variant audit — some
  variants have visual glitches.

Both are still in the data files (you'll see them in spoilers from
seeds generated against v0.28.1 or earlier); they just won't be
chosen by v0.28.2's shuffle.

## Variant variety on by default

The "Prefer canonical variants" GUI checkbox now starts OFF instead
of ON. With it OFF you'll see the full pool of NPCParam variants
each c-prefix has — more visual variety per seed, more variation in
attack movesets within a single chr type, more interesting
encounters generally. The checkbox itself still exists if you want
to flip it back on for any particular run.

The reason to default it ON used to be "ghost variants are often
broken in subtle ways" — the per-chr scripts (luabnd) on ghost
variants are sometimes missing or incomplete, which can produce
T-poses, missing FFX, broken AI, or worst-case CTDs. Those known-
bad ghosts have now been isolated separately (via per-chr
exclusions, the redundant-variant prune list, and prefix-level
filters), so the soft canonical-prefer filter isn't load-bearing
as a default safety net anymore. If a new bad ghost turns up in
playtest, isolate it surgically at one of those layers rather than
flipping the global filter back on wholesale — that's the
documented playbook in the engine's docstring.

## Hand-tuned caps actually take effect now

If you've been wondering why a miniboss-tier chr with an explicit
cap in `data/placement_budget.json` still showed up four times per
seed — that's because a v0.27.6 engine rule was unconditionally
clamping every miniboss-tier chr to cap=4, silently overriding
whatever the JSON said. v0.28.2 makes the tier rule a *default* (set
cap=4 only when the JSON doesn't specify one) rather than a clamp.
Explicit JSON values now win. The same fix went into the analogous
grunt-tier block as preemptive consistency, though no grunt-tier chr
has a hand-tuned cap today.

**Behavior change for known cases:**
- `c4420` (Giant Crayfish): the rotation-pull above now actually
  takes effect (was being clamped from 0 back to 4 before this fix).
- `c4050` (Kaiden) and `c5840` (Black Knight): both have JSON
  cap=30, and the v0.27.13 mount-role override re-pins them at 30
  anyway, so effective cap is unchanged.

**This fix does NOT explain Onze (Demi-Human Swordmaster, c5810)
appearing 4×/seed despite cap=2.** Onze is field_boss tier, not
miniboss, so neither tier-default rule touches it. The engine
correctly loads c5810 at cap=2 both before and after this fix.
Whatever's causing Onze to exceed cap=2 is a separate bug —
suspect either MSB-boundary recycling (v0.28's frozen-blocked-set
semantics let a cp overshoot mid-MSB) or the reservation pre-pass
placing without re-checking cap. Worth a focused look in v0.28.3.

## Spoilers know which arena is which night boss

Each night-boss arena map now carries its **expedition + role** in the
spoiler. Open `_spoilers.md` (or the spoiler viewer's Spoiler tab) and
the per-map headers read `m49_18_00_00.msb — Tricephalos NB2`,
`m49_30_00_00.msb (1 swaps) — Night Aspect NB1`, and so on. Maps that
aren't a scheduled night-boss slot render unchanged. The full role data
(NB1 / NB2 / NB1-extra / NB2-extra, including the rare extras suppressed
from the compact label) lives in `_spoilers.json` as a new `night_role`
key on each affected entry, so spoiler-tooling consumers can read it
without parsing the markdown.

## Night-boss teleporter (experimental, default OFF)

New toggle on the heritage / coop-safety tab: **"Early night-boss spawn
(RoR2 teleporter)."** When ON, walking up to a boss arena fires the
night-boss spawn early instead of waiting for the 23:00 clock window.
Minimal-by-construction — only `common_func.emevd.dcx` differs between
the clock build and the proximity build; everything else stays byte-
identical. Caveat: the proximity event still scopes to the night gate
flag, so engaging it nudges the whole night sequence early, not just
one arena. Round-trips through saved settings + the shareable settings
code like the other run flags.

## Refreshed regulation

`bundled_regulation/regulation.bin` updated for v0.28.2. Same shape as
before (MMV base + the v0.28.x balance / safety patch overlay), with
the latest tweaks rolled in.

## For modders — regulation dump as a separate download

The release page now offers a **second zip**:
`nightreign-enemy-rando-v0.28.2-regulation-dump.zip` (~3.6 MB). It's a
flat CSV dump of every param table in the shipped regulation —
`NpcParam.csv`, `AtkParam_Npc.csv`, `BehaviorParam.csv`,
`LotResultPlayAreaParam.csv` (the night-boss arena table behind the
new spoiler labels), and 248 more. End-users don't need it; modders
who want CSV-readable params without cracking the .bin open in
Smithbox can grab it alongside the main download. See
`regulation_dump/README.md` for typical workflows.

---

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
