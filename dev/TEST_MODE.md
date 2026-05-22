# Test Mode — Design Notes & Status

**Status as of v0.25.10 (May 2026):** Implemented but **unvalidated**. The
v0.25.10 build *should* work; awaiting playtest confirmation on a Gaping
Jaw-path seed (which routes through m48_90, the most common boss-init
pattern). v0.25.8 and v0.25.9 both shipped and both failed in playtest
for different reasons. The architectural understanding is now solid; if
you're picking this back up, READ THIS WHOLE DOC before writing code.

---

## TL;DR

- **What it is:** a build mode that overlays modified EMEVDs onto the 19
  scripted N1/N2 expedition arenas (m48_xx + m49_xx, minus Augur m47_70)
  to enable faster iteration on engine changes.
- **What it isn't:** a correctness tool. Vanilla expedition play already
  validates rando swaps end-to-end.
- **Whether to ship it:** Probably no, unless you're doing engine-level
  work that needs cross-arena validation faster than 18h-per-matrix.
- **If you do ship it:** v0.25.10 is the current best attempt. The
  *better* architecture is authoring our own MSB (see "Path B" below) but
  that's more work.

---

## The Core Architectural Insight

**All NR night-boss MSBs are mob-only overlays.** Geometry, assets, and
the playable world live in m60_xx Limveld tiles below. The engine layers
a mob overlay onto a tile when activating a night-boss zone. There is
no "fog wall, enter arena" transition — it's all open Limveld with mobs
appearing on top of the existing terrain.

This is true for **vanilla NR** AND **MMV** (Maple Mountain Variety mod).
Both use the overlay model. They differ only in *which layer* enables
the chrs:

| | Vanilla scripted (m48/m49) | Vanilla Evergaol (m46) | MMV custom |
|---|---|---|---|
| MSB Part state | `Default` disable | `Default` w/ MapVariation | `NeverDisable` |
| MSB `MapStudioLayer` | normal | normal | `0xFFFFFFFF` |
| Chr at map-load | invisible | invisible (variation-gated) | **alive immediately** |
| EMEVD pattern | `9006xxxx` (disable → wait flag → enable + healthbar) | `90045xxx` (variation-gated enable, no healthbar event) | `9001x` (post-spawn dressing only) |
| Best for | Shipping (dramatic reveal) | Multiple potential bosses per slot | Testing (predictable, immediate) |

**The two halves (MSB Part state + EMEVD pattern) are a package deal.**
The single biggest mistake I made early was treating MMV's "minimal"
EMEVD as a portable boss-init template. It's not — it's *post-spawn
dressing predicated on the chr being alive at map-load*. To use it, you
need both halves.

---

## Time and Flag Mechanics

**The expedition clock is engine-managed, not EMEVD-managed.** You
cannot speed up day-1 from EMEVD.

What EMEVDs CAN do is query the clock via `PlayAreaCurrentTimeInRange
(start_h, start_m, start_s, end_h, end_m, end_s)`. The time ranges in
NR's common_func:

- **Day-1 activity window:** `0:00:00 — 20:29:59`
- **Pre-night transition:** `22:40:00 — 23:59:59`
- **Night-1 phase:** `23:00:00 — 23:59:59` (gates most boss machinery)

For each scripted arena, the chain looks like:

```
engine clock → PlayAreaCurrentTimeInRange (23:59 range) returns true
  ↓
90055001 satisfies its WaitFor, calls SetNetworkconnectedEventFlagID(eventFlagId2, ON)
  ↓
flag 48800200 (m48_80) / 48900200 (m48_90) / etc. = ON
  ↓
90065xxx (boss-init) wakes from WaitFor(EventFlag(...))
  ↓
DisableCharacter → EnableCharacter + DisplayBossHealthBar + SetBossBGM
```

To pre-fire the trigger and skip day-1 entirely, you'd need to set the
arena-specific trigger flag at event 0. That requires `SetEventFlag`,
which is NOT `InitializeCommonEvent` (class 2000). It would need
`healthbar_inplace/synth.py` extended to emit a second instruction
class. ~1-2 sessions of work; not done.

---

## Iteration History

### v0.25.8: MMV-style EMEVD overlay (BROKEN)

**Strategy:** Use MMV's 13-event 9001x pattern as a "minimal boss-init
template" for vanilla N1/N2 arenas. Strip vanilla's 9006xxxx machinery.

**Failure mode:** Category error. MMV's pattern is post-spawn dressing
for chrs that are alive at map-load (because MMV's Parts have
`NeverDisable`). On vanilla MSBs (where Parts have `Default` disable
state), the chr stays disabled and never spawns. Music/healthbar events
fire against a chr that doesn't exist.

**Playtest validation:** Seed 855504, Godskin Duo arena (m48_80). User
reported "night 1 boss failed to start." Confirmed: no Wormface
appeared, even after night-1.

**Key user contribution that unblocked the diagnosis:** Alaric witchy'd
MMV's MSBs and uploaded them. Inspecting the XMLs revealed
`GameEditionDisable: NeverDisable` on every MMV Enemy Part. This is
what made it clear MMV's design is a matched-pair, not a portable
template. **31 MMV MSBs total; zero overlap with vanilla N1/N2 arenas.**

### v0.25.9: Extract boss-init calls from vanilla (BROKEN DIFFERENTLY)

**Strategy:** Don't replace vanilla's machinery. Copy `9006xxxx` +
`90015008` calls verbatim from vanilla per-map EMEVDs into a minimal
test-mode EMEVD. Strip cinematics, region triggers, NPC walks.

**Failure mode:** Filter was too aggressive. Stripped `90055001`, which
is the event that *sets* the night-1 trigger flag that `90065xxx` waits
on. So `90065910` (boss-init) sat forever in `WaitFor(EventFlag(...))`
because nothing was ever going to set that flag.

**Playtest validation:** Seed 938248, again m48_80. User reported "night
1 boss failed to start"; expedition got stuck in night-1 because the
m48_80 boss couldn't die because it couldn't spawn.

**Misdiagnosis I made:** Initially suggested the user might have been at
a Limveld field-boss (m46_70 Valiant Gargoyle) and misidentified the
real N1 location. That was wrong — the actual N1 was m48_80 (the seed's
only m48/m49 placement) and the v0.25.9 bug was biting exactly as I'd
just identified one message earlier. Don't make this mistake again.

### v0.25.10: Widened KEEP filter (CURRENT, UNVALIDATED)

**Strategy:** Same extract-from-vanilla approach as v0.25.9, but widen
the filter to keep all event families involved in the boss-init chain.

```python
# dev/extract_boss_init_calls.py
KEEP_EVENT_PREFIXES = ('9006', '9005', '9003')
KEEP_EVENT_EXPLICIT = {90015008, 90015012, 90015020, 90015030}
```

Now keeps:
- `9006xxxx` — boss-init / cleanup / multi-phase
- `9005xxxx` — night-trigger setter (the v0.25.9 fix)
- `9003xxxx` — asset toggles tied to night-1
- `90015008` — death observer (sets post-kill flag for night-2)
- `90015012/020/030` — multiplayer combat scaling, fight-active flag,
  idle anim

Strips:
- `90015070` — cinematic frame triggers (camera/tile cuts)
- `90015442/443/446/460/470/475/476/478` — region triggers + arena
  polish + healthbar dressing
- `90015002/023/026` — aggro despawn timers

Call counts per arena: 14 for simple (was 4 in v0.25.9), 16 for
multi-boss like m48_80, 36 for Tricephalos m48_50/m48_60.

**Pending:** playtest on a Gaping Jaw seed (m48_90 uses `90065910` —
the most common pattern, 13 of 19 arenas).

---

## Two Forward Paths

### Path A: Ship v0.25.10 as-is

If the Gaping Jaw playtest succeeds: ship it. Simplest fix.

Limitations baked in:
- Test cycle is full vanilla day-1 timer (~14 min) per arena
- Bosses gate on real night-1 flag (engine-managed clock)
- We're "parasitic on vanilla machinery we don't control"

### Path B: Author our own MSB (better architecture)

**See `dev/AUTHORED_ARENA_WORKFLOW.md` for the operational how-to.** The
infrastructure is built and tested (see `dev/build_test_arena.py` +
`tests/test_build_test_arena.py`); what remains is the user-side Witchy
round-trip experiment to confirm binary repacking is viable.

If you want fast cycle (no day-1 wait) and/or full architectural
ownership, the right design is:

1. **Mob-only MSB**, modeled on witchy'd MMV references. Key field
   values per Part: `GameEditionDisable: NeverDisable`, `MapStudioLayer:
   0xFFFFFFFF`, `Condition1/2: 0`, `ChrActivateCondParamID: 0`. The
   user's MMV extract at `/tmp/mmv_msb/m*_xx_00_00-msb-dcx/` is the
   canonical reference.

2. **Hijack an existing scripted MSB slot** (e.g., replace vanilla
   m48_80) so the engine loads ours where it would have loaded vanilla.
   Avoids needing new entries in the overlay-selection table.

3. **Match it with MMV-style EMEVD** via the *deprecated-but-valid*
   `dev/emit_mmv_style_arena_emevd.py`. This module is internally
   correct; its v0.25.8 deprecation was about misapplication, not the
   code itself. With an authored matching MSB, this module is suddenly
   the right tool.

**New work needed for Path B:**

- MSB binary round-trip. Two options:
  - **Witchy CLI Repack** (cheap path) — user has Witchy locally for
    extract; the inverse should work. Edit XML, repack, ship. Zero new
    Python code for the MSB format.
  - **Direct hex patching** — find Part struct offsets for
    `GameEditionDisable` (currently undocumented in `oops_all_anyone.py`,
    which only has offsets for MODEL_INDEX, ENTITY_ID, THINK_PARAM,
    NPC_PARAM, POSITION). More work.
  
- **30-min sanity experiment FIRST:** take a witchy'd MMV MSB, modify
  one chr's model in the XML, Witchy-repack, drop into me3 profile,
  confirm the game loads it. Proves the round-trip works before any
  bigger investment.

- **Slot-selection strategy:** which arena(s) to hijack? Want to cover
  the boss-init pattern diversity (90065910, 90065131, 90065050,
  90065121) without doing all 19.

Effort: ~1-2 sessions if Witchy round-trip works. Considerably more if
we need hex patching.

---

## Other Outstanding Issues

### Spoiler reporting bug

`spoilers/<timestamp>_seed*.json` is archived BEFORE Step 4/4 (healthbar
metadata injection) and the test-mode block run. So:

- `pipeline_metadata.test_mode_arenas` is missing from archived spoilers
  even when test mode ran successfully
- Same problem for healthbar nameId-rewrite metadata
- Metadata IS present in `out_dcx_dir/_spoilers.json` (the in-build copy)

Affects diagnosis — the archived spoiler is unreliable for these
fields. Fix: either re-archive after metadata injection, or inject
earlier. Cosmetic, deferred.

### Augur (m47_70) not handled

Augur's expedition descent has 4-wave choreography using `90065000–016`
events that appear to be **map-local** (defined in m47_70's own EMEVD,
not in common_func). The "extract from vanilla per-map EMEVD" strategy
captures them as call sites but their definitions wouldn't exist in
common_func, so the calls would resolve to no-ops in our minimal EMEVD.

Currently `dev/generate_test_mode_arenas.py:N1_N2_ARENAS` omits m47_70
entirely. If Augur is the Nightlord pick, the seed bypasses test-mode
for that arena.

Future task: either special-case Augur (extract map-local events too)
or exclude seeds where Augur is the N1 pick.

---

## File Inventory

### Current canonical files
- `dev/extract_boss_init_calls.py` — v0.25.10 extractor. `extract_calls()`
  parses vanilla .emevd.js source, returns `CallSpec` list. `emit_text()`
  produces DarkScript3 source. `emit_binary()` uses
  `healthbar_inplace/synth.py:healthbar_instruction()` to produce
  Sekiro+ format binary.
- `dev/generate_test_mode_arenas.py` — batch driver. Defines
  `N1_N2_ARENAS` (the 19-arena list). Clears stale outputs, regenerates.
- `dev/test_mode_arenas/` — 19 `.emevd` + 19 `.emevd.js` + `_inventory.json`.
- `oops_v3.py` line 31: `V3_ENGINE_FINGERPRINT = 'v0.25.10'`.
- `tests/test_test_mode_arenas_integration.py` — 14 tests, all pass.
  Notable regression tests:
  - `test_v0_25_9_extracts_90065910_for_simple_arenas` (seed-855504 case)
  - `test_v0_25_10_keeps_night_trigger_machinery` (seed-938248 case)
  - `test_v0_25_9_strips_cinematic_and_dressing_events`

### Still-relevant deprecated files
- `dev/emit_mmv_style_arena_emevd.py` — MMV-pattern EMEVD emitter.
  Deprecated for v0.25.x but **VALID code** that becomes relevant again
  for Path B (authored-MSB approach). 12 tests pass.

### Pipeline integration
- `dcx_batch.py:rando_pipeline()` — runs the test-mode overlay step
  after healthbar Step 4/4. Has the pre-flight warnings for when
  `test_mode_arenas=True` is passed without `emevd_out_dir`. See the
  test `test_test_mode_skip_warning_is_prominent_when_emevd_out_dir_blank`.
- `oops_rando_gui.py` — `test_mode_arenas_var` checkbox in scrollable
  Heritage tab. Pre-flight popup in `_run_shuffle` warns user before
  running if `emevd_out_dir` not set.

### Anchor data (reference, read-only)
- Vanilla NR EMEVDs: `/home/claude/vanilla_emevd/vanilla_decompressed_emevd/`
  (392 files)
- MMV reference: `/home/claude/mmv_extract/mmv/` (~30 arenas +
  common_func)
- User's MMV MSB extract (witchy'd): `/tmp/mmv_msb/m*_xx_00_00-msb-dcx/`
  (31 MSBs total — m45_51, m46_52–95, m49_41–62, m52_01)

### Key boss-init patterns (which arena uses which)
- `90065910` — simple expedition pattern, 13 arenas: m48_40/70/90,
  m49_10/17/18/19/20/21/23/26/27/29
- `90065131/130/132` — Godskin Duo variant, m48_80 only
- `90065121/120/122` — BBH variant, m49_25 only
- `90065050/051..057` — Tricephalos variant, m48_50/m48_60
- `90065090/091/092` — m48_20 only (no 90015008 death observer)
- `90065140` — m48_40 (plus 90065910)
- `90065060/061..064` — m49_26/m49_27 multi-phase
- `90065100/101` — m48_90 multi-phase add-ons
- `90065110/111..113` — m49_28
- `90065040/041` — m49_29 (plus 90065910)

---

## Common Failure Modes & How to Recognize Them

| Symptom | Likely cause | Fix |
|---|---|---|
| "Night 1 boss failed to start" + chr never visible | EMEVD overlay stripped enable mechanism (v0.25.8) or flag-setter (v0.25.9) | Widen KEEP filter (→v0.25.10), OR shift to authored-MSB |
| Chr appears but no healthbar at scripted m48/m49 arena | EMEVD overlay missing `DisplayBossHealthBar` chain | Verify `90065xxx` family present in extracted calls |
| Chr appears + no healthbar at m46 Limveld | Normal — Evergaol-overlay style fights may not have healthbars | Not a bug, vanilla behavior |
| Expedition stuck in night-1 | Boss death cleanup didn't fire → night-2 transition gated | Same root cause as "boss didn't spawn" — chain incomplete |
| Test mode "succeeds" in log but no in-game effect | `emevd_out_dir` blank; warnings exist but were ignored | Check pre-flight popup; check log for "REQUESTED BUT NO emevd_out_dir" |

---

## Open Questions

1. **Does v0.25.10 actually work?** Pending Gaping Jaw playtest. m48_90
   uses `90065910` (most common pattern); if it works there, 13/19
   arenas implicitly validated.
2. **Does Witchy round-trip preserve binary identity for NR MSBs?**
   Untested. 30-min experiment would answer.
3. **For Path B: which arena to hijack first?** Suggests starting with
   m48_90 (most representative) but optimal pick depends on
   Nightlord-pool diversity.
4. **Augur:** worth handling, or accept seeds-where-Augur-is-N1 bypass
   test mode?
5. **Spoiler timing fix:** how invasive? Need to inject metadata before
   the spoiler archive snapshot, or re-archive after.

---

## What NOT To Do

- **Don't go back to v0.25.8's pattern** (MMV-style EMEVD on vanilla
  MSBs). It's a known category error. The only valid use of MMV-style
  EMEVD is paired with a NeverDisable-authored MSB.

- **Don't try to speed up the day-1 timer from EMEVD.** Engine-owned.
  The only EMEVD-side option is pre-firing the night-1 flag, which
  needs a non-class-2000 instruction (i.e., extending `synth.py`).

- **Don't assume "no healthbar at a chr you encountered" = boss didn't
  spawn.** m46_xx Evergaol-style overlays may genuinely not have
  boss-bar UI in vanilla. Need to distinguish "scripted arena with
  expected healthbar didn't show" vs "Limveld overlay without healthbar
  is normal."

- **Don't conflate "Nightlord boss" with "N1/N2 expedition arena boss"
  with "Limveld field-boss."** Three different tiers, three different
  EMEVD scaffolds, three different player experiences. The spoiler tags
  things "(Night Boss)" pretty liberally — that's the rando's pool
  classification, not the game's UI tier.

---

## Final Recommendation

For someone picking this up cold: **read this doc, then ask the user
whether they want test mode at all** before writing code. The
correctness case for test mode is weak (vanilla play validates fine).
The iteration-speed case is real but only if there's active
engine-level work that needs cross-arena coverage. If neither applies,
the right next step is to leave v0.25.10 dormant and work on whatever
else is top-of-mind.

If test mode IS wanted: ship v0.25.10 first (cheap), validate against a
Gaping Jaw seed, then decide whether to invest in Path B based on
whether the day-1 wait is actually painful in practice.
