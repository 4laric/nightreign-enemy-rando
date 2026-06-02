# TODO

Forward-looking work items that aren't urgent enough to block a release
but are worth doing when the budget allows. Distinct from `WONTFIX.md`
(known limitations we're accepting) and `IMPORT_PLAN_COLLISIONS.md`
(specific tactical triage). Listed roughly by impact.

---

## Factor out caps + pools as first-class data; GUI to edit them

**Status:** flagged v0.25.4 — fully unstarted, just shape-of-the-thing
described below.

### What "factored out" looks like

Today the cap and pool system is split across multiple constants in
`oops_v3.py` with overlapping/redundant gates:

- `V3_UNIQUE_TARGET_CAPS` (69 entries) — per-c-prefix cap=N
- `V3_TARGET_PLACEMENT_CAP = 50` — global default for everything else
- `V3_EXCLUDE_TARGET_PREFIXES` — hard-excludes, overrides any cap
- `V3_GHOST_EXCLUDE_TARGET_PREFIXES` — ghost-variant-only exclude
- `V3_ARENA_ONLY_TARGETS` — pool-restricted-to-arenas
- `V3_NIGHT_BOSS_STRICT_TARGETS` / `V3_NIGHT_BOSS_CALIBER_TARGETS`
- `V3_FRAGILE_SENSITIVE_TARGETS`
- `V3_MAP_PREFIX_TARGET_EXCLUDES`
- `V3_HERITAGE_ALL_PREFIXES` (MP-safe gate)
- `V3_OVERLAY_PRESERVE_VANILLA_MSBS` / `V3_PRESERVE_SLOTS`
  (slot-side preservation, but interacts with caps via dead-code overlap)

These accumulated over time. Each was introduced for a real reason and
each has correct behavior individually. But the surface area is now
large enough that:

1. **Dead-code caps exist.** v0.25.3 sim surfaced c7800 Duke's Dear Freja
   (in BOTH `V3_UNIQUE_TARGET_CAPS` cap=2 AND `V3_EXCLUDE_TARGET_PREFIXES`
   — exclude wins so cap is dead), c4601 Troll Knight (cap=6 was dead at
   grunt tier until v0.25.4 retier), c4170/c4171/c4240 Putrid Flesh /
   Fingercreeper (cap=2 on trash/grunt tier — dead).

2. **No single place to ask "what's the effective placement budget for
   chr X?"** Today you have to mentally union the constants.

3. **Cap rationale is comment-buried.** Each cap entry has a comment
   explaining why (named singular / safety-net / swarm-bounding / dead
   archetype) — but those rationales aren't queryable. If you want all
   caps that exist "because of v0.23.74 script-spawn boss-tier audit",
   you grep.

### Proposed shape

A `data/placement_budget.json` (or similar) that captures all of this:

```json
{
  "c7700": {
    "cap": 2,
    "rationale": "heritage_named_singular",
    "since": "v0.25.3",
    "history": [
      {"version": "v0.23.74", "cap": 1, "reason": "script-spawn boss-tier safety net"},
      {"version": "v0.25.3", "cap": 2, "reason": "playtest showed 50% miss rate at cap=1"}
    ],
    "tier_override": null,
    "exclude": false,
    "exclude_reason": null,
    "ghost_exclude": false,
    "arena_only": false,
    "mp_safe_blocked": false,
    "fragile_sensitive": false,
    "tags": ["heritage", "ds1_mmv", "night_boss"]
  },
  ...
}
```

Engine reads this file at module load and reconstructs the existing
`V3_*` sets from it. Behavior stays identical; representation collapses
to one source of truth.

**Benefits:**
- Single-table view of "what does the engine think about chr X"
- Dead-code detection is automatic (cap entry on excluded chr → warning
  at load time)
- History trail is data-readable, not comment-spelunked
- A/B sim tooling can swap whole budget files in/out instead of
  patching `V3_UNIQUE_TARGET_CAPS` manually like
  `dev/archive/sim_cap_ab.py` historically did (v0.25.2-vs-v0.25.3
  cap A/B; archived in v0.28.x — version-locked, but the harness
  pattern is the reference)
- Migration to per-chr JSON files (one file per c-prefix) if the
  single-table form gets unwieldy

### Migration path

1. Build a one-shot extractor `dev/extract_placement_budget.py` that
   reads all the current `V3_*` sets + `V3_UNIQUE_TARGET_CAPS` and
   emits the JSON. Snapshot tests confirm round-tripping is byte-stable.
2. Engine adds a loader path that reads the JSON if present, otherwise
   falls through to the existing inline constants. Behavior unchanged.
3. Once the JSON is the single source of truth, the engine constants
   become derived (computed from JSON at module load).
4. Old inline constants get demoted to internal caches; new code reads
   from the JSON.

This is mostly a refactor — no behavior change, no new features. But
it's a prerequisite for the GUI work below.

### GUI tooling

Once caps + pools are a data file, build a small GUI:

- **Cap editor:** browse-and-filter the budget table. Click a chr → see
  its rationale, history, current cap, related gates (exclude/etc).
  Edit cap with a slider 0-50, save back to the JSON.
- **Pool view:** for each tier (night_boss/field_boss/miniboss/grunt),
  show which chrs are eligible, which are excluded, and what their
  caps are. Filter by anim_class, size, source (vanilla NR / heritage /
  MMV). Quick toggle to exclude/include.
- **A/B preview:** "If I change c4980 Death Bird cap from 2 to 3, what
  does my next 50 seeds look like?" Wires into a new
  `sim_cap_ab.py`-style harness (the v0.25.2-vs-v0.25.3 original
  archived in v0.28.x; pattern lives in `dev/archive/sim_cap_ab.py`)
  as a non-blocking background run.
- **Dead-code finder:** scans for cap entries that can't fire (excluded
  chrs, trash-tier with cap, etc.) and flags them with a one-click
  "remove this dead entry" action.
- **Variant grouping:** Bloodbane Giant Crow (c4561) and Giant Crow
  (c4560) are sibling variants but have inconsistent caps. The GUI
  highlights such pairs ("c4560 cap=2, c4561 uncapped — fix?") and
  offers to align them.

The existing `oops_rando_gui.py` is the natural home (or sibling). It
already has the build/test/launch UX; adding a "Placement Budget" tab
fits the existing pattern.

### Scope / non-goals

This is NOT about making caps user-facing in the released rando. The
GUI is dev tooling — for the maintainer (and any future collaborators),
not for randomizer end-users who shouldn't be hand-editing chr caps.

### Effort estimate

- Factoring: ~1 session if the inline constants are clean (a few hours
  of extractor + loader + tests)
- GUI: ~2-3 sessions for a Tkinter or PyQt panel that's good enough to
  actually use
- Total: a small project, not a multi-week thing. But "not blocking
  anything immediate" is why it lives here.

---

## See also (other forward-looking items)

These are deferred from specific recent work sessions, listed here to
keep them visible without forcing a triage decision:

- **MMV-style minimal test-mode arena EMEVDs.** ✓ AUTHORED (not yet
  integrated). The motivation: cut N1/N2 playtest cycle from 18 hours
  to ~1 hour by replacing per-arena scripted scaffolding with a uniform
  minimal template (5 events per boss + arena setup + display bindings).
  Pattern lifted from MMV's own minimal-arena template (12-13 events
  vs vanilla NR's 20), field-validated by widespread MMV play.

  Shipped artifacts:
    - `dev/emit_mmv_style_arena_emevd.py`: `ArenaTemplate` class with
      both `emit()` (DarkScript text) and `emit_binary()` (raw .emevd
      bytes via `healthbar_inplace/synth.py`). 12 tests pass including
      byte-perfect round-trip vs MMV's m46_56.
    - `dev/generate_test_mode_arenas.py`: batch driver that extracts
      per-arena boss params from vanilla NR (90065910 + 90065911
      patterns) and generates 20 test-mode EMEVDs in both forms.
      Output: `dev/test_mode_arenas/` (.emevd.js + .emevd per arena
      + `_inventory.json`).
    - `tests/test_emit_mmv_style_arena_emevd.py`: covers single-boss,
      multi-boss, anchor variants, MMV round-trip, binary parse round-
      trip, and DCX-compression round-trip (skips on Linux/no-Oodle).

  Not yet done (next session):
    1. Engine integration: a `--test-mode-arenas` flag on dcx_batch's
       `rando_pipeline()` that, when set, overlays our 20 generated
       binary EMEVDs into the output `event/` dir using the existing
       `emevd_compress_dir` step. Architecture mirrors the healthbar
       in-place patcher (`dcx_batch.py` Step 4/4).
    2. Playtest validation: load one generated arena in-game, confirm
       boss spawns, can be killed, night advances correctly. The
       generator's correctness is mechanically verified (parser round-
       trip + DCX round-trip both pass) but the semantic correctness
       — does NR's progression engine actually accept this minimal
       template? — needs a live run. If it doesn't, we learn what's
       missing from MMV's pattern that vanilla progression actually
       requires.
    3. Augur (m47_70) special case: the descent uses 17 single-arena
       events for the 4-wave choreography. Currently skipped by the
       batch generator. Options: author a custom Augur template OR
       skip-Augur-in-test-mode policy (seed exclusions when Augur is
       the Nightlord-N1 pick).

  See `dev/test_mode_arenas/_inventory.json` for the current generated
  set. See `healthbar_inplace/synth.py` for the binary EMEVD builder
  used by `emit_binary()`. See `dcx_batch.py:rando_pipeline` for the
  integration point (the existing healthbar patcher's Step 4/4 is the
  template for the test-mode-arena overlay flow).

- **Files-deployed-but-not-tagged is a silent leak path.** v0.25.6
  fixed a CTD where c8500 Manus (NB2) crashed at the Crater fog gate.
  Root cause: chr files + battle.luabnd were deployed in heritage_pack
  but the chr was never tagged in `nr_enemy_tags.json`, never capped,
  never excluded — so the engine swept it into the swap pool by default
  because the files were on disk. c8200 and c8400 were in the same
  state (also added to V3_EXCLUDE_TARGET_PREFIXES in v0.25.6).

  Proposal: add a load-time audit that walks the chr inventory in
  `heritage_pack/chr/`, compares against `nr_enemy_tags.json`, and
  WARNS for any deployed chr that has no tag entry AND isn't in any
  V3_EXCLUDE_* set. That'd surface this class at engine startup instead
  of via crash. ~30 lines of code. Fits naturally in the same audit
  pipeline as `audit_heritage_chr_deployment.py`. Could also reject
  the run with a hard error rather than warn — depends on appetite for
  strict-mode startup.

- **Derive arena-slot designation from vanilla chr placements.** ✓ SHIPPED
  in v0.25.7. `V3_BOSS_SLOT_CATALOG` entries now carry an `arena: bool`
  field derived at module load via the two rules Alaric proposed:
    1. Vanilla chr at slot has `expects_boss_arena=True`.
    2. Vanilla chr at slot has `size_class` in {XXL, GIGA}.
  104 of 344 slots (~30%) marked arena. The `pick_target_cp` gate at
  line ~10935 now OR's the catalog signal with the existing slot-variant-
  name marker check; the new path uniquely catches 48 slots that
  variant-name matching missed (e.g. unnamed Limveld GIGA-chr slots,
  Crucible Knight interior slots). Tests: `test_arena_slot_derivation.py`.

  Follow-on policy NOT shipped in v0.25.7 (deliberate):
  - "XXL+ chrs only at arena slots" would over-restrict — many vanilla
    field bosses (Trolls c4600/c4601/c4602/c4603, Runebear c4630, etc.)
    are XXL+ and roam Limveld; hard-locking them to arena slots
    eliminates field-boss variety. The catalog field is precomputed and
    available if a future calibration wants to use it as a soft signal
    (e.g. weighted preference rather than hard ban).
  - Wiring the arena field into other gates (proximity-demote,
    slope-up size-up, wedged/elevated) — currently those gates infer
    "boss arena" from src.tier + expects_boss_arena directly. Could be
    unified to read the catalog field. Code-cleanup scope; no behavior
    change.

- **Heritage AI script imports still pending.** Per memory: 8 remaining
  from ER unpack. v0.25.4 covered Spider Scorpions (c5190/c5192/c5193).
  See `dev/import_heritage_ai_scripts.py` IMPORT_PLAN for full
  AFFECTED + PARTIAL list. Bulk-run with `--skip-confirmed` would do
  most of the work in one go.

- **heritage chr deployment audit findings (v0.25.5 session).** Ran
  `dev/audit_heritage_chr_deployment.py` against the user's mod chr
  dir, ER chr, NR chr. Most heritage chrs deployed correctly. Anomalies
  worth investigating individually:
  - **c4541** (NR/MMV-specific, not in ER): mod has anibnd + chrbnd but
    no behbnd. Source of the gap unclear — needs investigation.
  - **c5650, c6200, c6230**: missing behbnd + chrbnd in mod. ER ALSO
    lacks these — these are shared-anim carriers (anim files only,
    used via redirect by numbered siblings c5651, c6201, c6231-3).
    The "incomplete" reading is actually correct deployment.
    Resolves the memory note "c6200 Slave Knight Gael incomplete
    deployment to fix (missing chrbnd + behbnd)" — c6201 is Gael
    (already complete), c6200 is the shared base (intentionally
    files-light).

- **Spider Scorpion AI bug remains unsolved.** v0.25.5 session ruled
  out aicommon dependencies (MMV's aicommon covers all referenced
  identifiers) AND ruled out missing chr files (full asset set
  matches ER per dir listing). Remaining candidates:
  1. Mod's c5190 div_anibnd/texbnd file CONTENTS differ from ER
     (hash-check pending — only base trio confirmed byte-identical)
  2. NpcParam.ThinkParamId mismatch in regulation.bin
  3. Runtime model swap landing wrong chr_id at spawn

- **`IMPORT_PLAN_COLLISIONS.md` ★★★ triage cases.** 5 high-priority
  naming collisions awaiting deliberate resolution.

- **Phase 1 stubs promotion** from `data/phase1_v0.25.0_stubs.json` to
  live tables.

- **B2 model-table compact feature** (deferred from earlier session).

- **Companion/prelude positions for patch2 catalog arenas** (null in
  the catalog, deferred).

- **MSB-binary inventory validation** for the EMEVD-parser role
  catalog. v0.25.1's `build_arena_chr_roles.py` uses pattern-based
  heuristics to identify chr eids; cross-checking against actual MSB
  Part lists would catch any false positives in the role
  classification.

- **anim-compat check on swap targets** (option B v2 from v0.25.1
  roadmap). Per-chr anim catalog + slot-required-anim cross-check to
  enable swap_actual_chr arenas to be smarter about which targets land
  where (currently any boss-tier chr can take any swap_actual_chr
  slot).

- **ER dragon heritage imports** (v0.26.x). With c4500/c4504/c4505
  banned for being uninteresting / too-big, the dragon swap pool
  is down to c4501/c4502 (Ekzykes-class), c4503 (Borealis), c4510
  (Ancient), c5860 (Ghostflame), c7700 (Gaping). Investigate which
  Elden Ring dragons could be heritage-imported to widen the pool:

  - **Smarag** (Glintstone Dragon, magic) — high probability of
    working since the c-prefix lineage shares anim_bank with c4500.
  - **Adula** (Glintstone Dragon, magic + ice attacks) — same.
  - **Glintstone Dragon (base)** — generic magic dragon.
  - ~~**Lichdragon Fortissax** (death lightning)~~ — already imported
    as **c4511** (SoTE/MMV pack). Confirmed working by user
    playtest. Already in V3_UNIQUE_TARGET_CAPS at cap=2.
  - **Dragonlord Placidusax** (probably too big and arena-specific,
    similar concern to Greyoll — likely a no).
  - **Magma Wyrm** (Makar, the generic ones) — different anim_class
    (wyrm vs flying dragon) so probably already imported under
    different c-prefix. Worth confirming the existing wyrm coverage.
  - **Crucible Knight Dragonkin** (if a distinct c-prefix from
    c4650 Dragonkin Soldier) — investigate.

  For each candidate: confirm the chr exists in vanilla ER (UXM-
  unpacked), check anim_bank compatibility with c4500's flying_dragon
  class, add to `data/heritage_pack.json` with the appropriate
  NPCParam mappings. Effort: probably a session per dragon family
  once the heritage import pipeline is warm.

- **Heritage NB visibility audit** (v0.26.x). Three DS heritage
  bosses bumped to cap=3 this session (c7820 Smelter, c7900 Nameless,
  c7920 Dancer) after user reported "haven't seen Dancer in a while."
  Root cause: arena_only_target gate + ~25-chr night_boss pool
  competing for arena slots means reservation often fails to seat
  multiple instances. cap=3 is a stopgap; the real fix would be:
  (a) a guaranteed-placement reservation pass for under-represented
  heritage chrs, OR (b) widening the arena-slot pool so reservation
  has more options to score, OR (c) reducing the night_boss pool
  size if any chrs aren't pulling their weight. Need empirical data
  from a few v0.26.x playtests to know which approach.

- **`_source` tag audit pass** (v0.26.x). The `_source='script_spawn'`
  tag was authored based on a boss-slot catalog that turned out to be
  incomplete (missing 5 m48/m49 MSBs) AND on grep-based investigations
  that missed UTF-16-LE-encoded c-prefix strings in vanilla MSBs.
  Net effect: some chrs may be mis-tagged script_spawn (forcing
  them through narrow arena_only-target placement) when they're
  actually MSB-placed and should be `nr_placed`.

  Confirmed misclassifications:
  - **c7712** (Centipede Grub) — 3 UTF-16-LE refs in m60_45_37_20.msb
    (the one MSB available to inspect in-repo at audit time).

  Suspected misclassifications (need vanilla_msbs/ to verify):
  - **c7700, c7820, c7900, c7910, c7920** — DS-heritage bosses;
    Alaric reports their boss-arena MSBs live in m48_00/m48_10/
    m48_20 range, not in the catalog. Reservation pass failures
    for c7920 (Dancer) point at exactly this.
  - **c4670 (Ancestor Spirit), c4690 (Grafted Scion)** — both
    surfaced in boss-slots catalog as having 2 vanilla placements
    each at m46_64 / m46_90 / m46_65 / m46_91. May not need
    reclassification (the script_spawn tag may also serve as an
    arena-preservation marker), but worth a deliberate review.

  Workflow:
    1. `python3 dev/audit_source_tags.py --msb-dir <unpacked NR>/map/mapstudio --verbose`
    2. Review misclassifications, decide reclassify vs preserve
       per-chr.
    3. Edit `data/nr_enemy_tags.json` to flip `_source: 'script_spawn'`
       → `'nr_placed'` for confirmed misclassifications.
    4. Run `python3 dev/extract_placement_budget.py` to regenerate
       the cached snapshot.
    5. Playtest to confirm placement frequency improves.

- **Split `V3_UNIQUE_TARGET_CAPS` into floor + ceiling semantics**
  (v0.26.x). The current `V3_UNIQUE_TARGET_CAPS = {cp: N}` constant
  is doing double duty:

  - **Floor semantics**: the reservation pre-pass uses N to decide
    "try to reserve up to N quality slots for this chr." This is
    really a *minimum guarantee* — "make sure this chr appears N
    times per seed."
  - **Ceiling semantics**: runtime placement enforcement uses the
    same N as a hard cap — "never have more than N placements of
    this chr per seed."

  These are conceptually distinct. The Dancer (c7920) case is the
  motivating example: we want a FLOOR of 3 (guarantee Dancer always
  appears in arena slots) but no CEILING beyond the global default
  (if natural rolls produce a 4th Dancer at an organic slot, that's
  fine, not a constraint to enforce). Conversely, Borealis (c4503)
  wants both — floor=1 (guarantee it shows up) AND ceiling=1
  (never more than one per seed, since it's a named unique).

  Proposed shape:

    V3_RESERVATION_FLOORS = {
        'c4503': 1,  # guarantee at least 1 Borealis per seed
        'c7920': 3,  # guarantee at least 3 Dancers per seed
        ...
    }

    V3_PLACEMENT_CEILINGS = {
        'c4503': 1,  # never more than 1 Borealis per seed
        # c7920 not listed → falls back to V3_TARGET_PLACEMENT_CAP=50
        ...
    }

  Migration:
    1. Add the two new constants alongside `V3_UNIQUE_TARGET_CAPS`.
    2. Default both to the existing value: for any cp in
       V3_UNIQUE_TARGET_CAPS, set FLOORS[cp] = CEILINGS[cp] = N.
       Behaviour-preserving by construction.
    3. Update the reservation pre-pass to read FLOORS, the runtime
       cap check to read CEILINGS.
    4. Diverge the two values for cases that want different floor /
       ceiling (Dancer first, since it's the empirical motivator).
    5. Keep `V3_UNIQUE_TARGET_CAPS` as a deprecated alias for one
       release cycle, then remove.

  Tests would parametrize over (cp, floor, ceiling) tuples; the
  current parametrize over `V3_UNIQUE_TARGET_CAPS.items()` should
  still pass for the floor==ceiling default cases.

## v0.26.x: shipped this arc

- **`_source` tag audit + reclassification** — 12 chrs flipped from
  `script_spawn` to `nr_placed` in `data/nr_enemy_tags.json` after
  `dev/audit_source_tags.py` confirmed every one had actual vanilla
  MSB placements (UTF-16-LE-encoded, missed by the original catalog
  parser). Arena-gating moved from `_source='script_spawn'` to
  explicit `V3_DEDICATED_ARENA_BOSS_CHRS` membership in `oops_v3.py`
  — same set of chrs gated, different keying mechanism. Each
  reclassified entry has `_source_override_v0_26_x` annotation
  marking the change.

- **V3_TAG_OVERRIDES flatten** — 33 of 45 tier overrides flattened
  directly into `data/nr_enemy_tags.json` (with `_tier_override_v0_26_x`
  annotation per entry). 5 no-op overrides dropped (tier already
  matched native). 7 remaining entries are runtime-loaded
  heritage/MMV chrs that aren't in `nr_enemy_tags.json` and still
  need the override application after pack loaders run. `tier`
  field in the JSON is now the single source of truth for native
  vs MSB-scan-derived chrs.

- **Floor/ceiling cap split** — new constant `V3_RESERVATION_FLOORS`
  (31 entries, all `=1`) drives the reservation pre-pass.
  `V3_UNIQUE_TARGET_CAPS` (73 entries) is now strictly the runtime
  ceiling. Policy: marquee NB roster (NR + DS-heritage + NB-caliber
  MMV) gets `floor=1, ceiling=2`. c7910 Storm King excluded from
  FLOORS (paired-only with c7900). Field-bosses, mini-bosses,
  grunts, trash: ceiling-only enforcement with no floor.
  `_compute_unique_reservations` now iterates FLOORS, not CAPS.

## v0.26.x: not-yet-done from this arc

- **Catalog rebuild for missing m48/m49/m19 MSBs.** The audit
  surfaced that `data/nr_boss_slots.json` was missing 5 m48/m49
  MSBs (m48_00, m48_10, m48_20, m49_41, m49_43) because the
  catalog parser had a UTF-16-LE blind spot. The catalog still
  works for the chrs it captured, but rebuilding it with a parser
  aware of both encodings would surface boss slots the engine
  doesn't currently know about. Use the same byte-level
  methodology from `dev/audit_source_tags.py`.

- **Move remaining V3_TAG_OVERRIDES into pack manifests.** The 7
  runtime overrides for heritage/MMV chrs (c1310, c5000, c5840,
  c5930, c6210, c6220, c6260) could be moved into
  `data/heritage_pack.json` / `data/mmv_imports.json` if the pack
  manifest schema supports per-cp tier overrides. Would eliminate
  V3_TAG_OVERRIDES entirely. Low priority since 7 entries is
  small and the override pattern is now scope-clear.

- **Playtest validation of the floor system.** The whole point of
  the split was to fix Dancer (c7920) not appearing reliably. With
  floor=1 the reservation pre-pass only needs to find ONE
  qualifying slot per marquee NB — much easier to satisfy than the
  previous attempts (floor=2 or floor=3 via cap-bumps). A few
  seeds of playtest will tell whether Dancer + Smelter + Nameless
  + the rest now show up consistently. If they still go unplaced,
  the next move is to look at why `_score_slot_for_unique` is
  rejecting all candidates (probably arena-only-target gate
  interacting with reservation slot pool).

- **Identify additional arena slots from terrain data** (v0.26.x+).
  With the full vanilla MSB dump now in hand
  (`/tmp/audit_msbs/nr_decompiled_msbs` from user upload, or the
  release-bundle `vanilla_msbs/` dir), we can scan slots for
  "big and flat" geometry — open terrain with adequate vertical
  clearance and a flat enough surface to host a large boss arena
  without ground-clipping or unreachable-position issues.

  Why: the v0.26.x reservation-health sim (`dev/sim_reservation_
  health.py`) surfaced that several NB-strict-tagged chrs have
  extremely narrow qualifying-slot pools — c4510 Ancient Dragon
  scored positively on 3 of 5136 slots; c4511 Fortissax /
  c8300 Dragonslayer Armor scored 0. Most of the strict pool
  hinges on the "Night Boss" marker substring in source-variant
  names, which is a thin source-side filter. Terrain-based slot
  identification would let us catalogue additional arena-quality
  slots WITHOUT depending on variant-name markers.

  Criteria sketch:
  - Position has open ground in a radius of ~15-20m (no collision
    geometry overhead)
  - Y-slope under ~10° (Erdtree Avatar / Ancient Dragon need flat
    landing pad)
  - Not in a cave/dungeon interior (m4x_xx interior or m30/m32
    cave sublocations) unless the cave has known boss-arena
    geometry (Stonedigger Troll cave etc.)
  - Bonus: cross-reference with `data/nr_all_part_positions.json`
    to find slots whose vanilla occupant is already large
    (XL+ size class) — those vanilla picks already vetted the
    geometry for a big chr.

  Output: extension of V3_BOSS_TIER_PINNED_SLOTS / boss-slots
  catalog with "geometric-arena" tier, accepted by the NB-strict
  gate as an alternative qualifier to the variant-name marker.

## Reservation-health snapshot (100 seeds, v0.26.x, vanilla MSBs)

Captured 2026-05-20 via `dev/sim_reservation_health.py` (archived in
v0.28.x to `dev/archive/sim_reservation_health.py`; superseded by
`dev/sim_new_add_health.py` which uses inventory JSON instead of
raw MSBs).

Reserves reliably (0% unplaced, 24/31 marquee NB chrs):
  c2130, c2500, c3050, c3100, c3250, c3251, c3560, c3570,
  c4130, c4640, c4650, c4680, c4750, c4770, c4911, c4980,
  c5000, c5011, c5810, c7700, c7710, c7820, c7900, c7920

Reserves usually (5% unplaced, 2 chrs):
  c4510 Ancient Dragon, c4580 Giant Wormface
  — both fragile_sensitive / GIGA / NB-strict; only ~3 slots out
  of 5136 score positively. Falling through to organic placement
  most of the time. Workable but worth widening their slot pool
  via the arena-slot-from-terrain task above.

Never reserves (100% unplaced, 5 chrs):
  c4511 Fortissax, c5030 Romina, c5051 Midra, c5200 Metyr,
  c8300 Dragonslayer Armor
  — all NB-caliber MMV imports with arena_only_target + NB-strict
  constraints. Score 0/5136 slots in the reservation pre-pass.
  Confirmed working in playtest (per user), so organic placement
  IS succeeding — but the floor=1 guarantee is structurally
  unsatisfiable for them with the current slot pool. Either
  (a) expand the strict-NB slot catalog so these can reserve, or
  (b) accept reservation-failure as expected and lean on organic
  placement for these chrs explicitly.

## v0.26.x-late: reservation health update (post-nav-independent fix)

After 100-seed sim revealed the 5 MMV NB chrs were 100% unplaced from
reservation, root cause was traced to V3_NAV_INDEPENDENT_TARGETS
missing the MMV-imported arena bosses. NB-strict markers in vanilla
NR land mostly at cave/dungeon-tile MSBs which have stub navmesh —
nav-required chrs get rejected at those slots. Margit was on the
nav-independent list (vanilla NR work), Midra/Romina/Metyr/Fortissax/
Dragonslayer/etc were not.

Shipped in this turn:
  - 13 chrs added to V3_NAV_INDEPENDENT_TARGETS: c2030 Rennala, c2031
    Rennala-P2, c2110 Maliketh, c2120 Malenia, c4511 Fortissax, c5000
    Gaius (already 0% from previous turn — defense in depth), c5030
    Romina, c5051 Midra, c5130 Messmer, c5200 Metyr, c5300 Rellana,
    c6200 Gael, c8300 Dragonslayer Armor.
  - M-humanoid arena_only lift (9 chrs, no behavior change because
    nav was the actual gate — but architecturally correct, leaves
    these chrs with wider eligibility for organic placement).
  - Reservation iteration order: pure random per-seed (was size-
    sorted with GIGA-first priority).

Post-fix reservation health (100 seeds):
  Floor reservation rate (% of seeds with at least one reservation):
    c5051 Midra:        29% (was 0%)
    c5030 Romina:       35% (was 0%)
    c5200 Metyr:        30% (was 0%)
    c4511 Fortissax:    19% (was 0%)
    c8300 Dragonslayer: 37% (was 0%)
    c4510 Ancient Dragon: 27% (was 95% — REGRESSION from random order)
    c4580 Giant Wormface: 36% (was 95% — REGRESSION from random order)
    Remaining 24 chrs:  100% reservation rate (no change)

Net: total unplaced/seed is approximately constant; the random-order
change spread the reservation-failure burden across more chrs rather
than concentrating it on 5. The 24-chr core is unaffected.

Decision deferred: should ordering be (a) pure random per Alaric's
direction, (b) restored to size-first, or (c) a hybrid that priors
the chrs with the narrowest qualifying-slot pools? Awaiting playtest
feedback — the arena-slot-from-terrain task above would loosen the
NB-strict gate enough that contention drops and all variants of
ordering converge to "everyone reserves."

## v0.26.x-late: NB-strict gate removed

Removed `V3_NIGHT_BOSS_STRICT_TARGETS` runtime gate. Was a variant-name
string filter ("source slot variant must contain 'Night Boss'") originally
introduced (v0.23.11) as a "strictest geometric gate" to keep XXL/GIGA
chrs out of Field Boss slots. Sim revealed it was actually a thin string
filter that blocked 7 marquee NB chrs (Midra, Romina, Metyr, Fortissax,
Dragonslayer Armor + vanilla c4510 Ancient Dragon and c4580 Giant
Wormface) from finding qualifying reservation slots at 65-81% rates.
Real geometric concerns are covered by V3_ARENA_ONLY_TARGETS (arena
requirement), V3_FRAGILE_SENSITIVE_TARGETS (rough-terrain rigs), and
anim_class/size_class compat in scoring. Per user direction: "I want
night bosses at field boss slots, as long as they can traverse" —
traversal IS what arena_only/fragile_sensitive handle.

Reservation health snapshot after removal (100 seeds):
  31/31 chrs in V3_RESERVATION_FLOORS now reserve at 0% unplaced rate.

If specific CTD patterns resurface (e.g., c4510 wingspan collision at
Miranda Blossom that the v0.23.11 entry mentioned, or c4580 Giant
Wormface visible at Death Rite Bird POI), add targeted V3_FORBIDDEN_BY_
SOURCE_ANIM rules or V3_FRAGILE_SENSITIVE_TARGETS entries with seed
evidence rather than resurrecting the variant-name filter.

## v0.26.x: reservation-health re-baseline (post-NB-strict-retirement)

100 seeds, vanilla MSBs, clean pyc cache:

  **31/31 marquee NB chrs at 0% unplaced.** ✓

The earlier 65-81% unplaced rates for Midra / Fortissax / Romina /
Metyr / Dragonslayer Armor / Ancient Dragon / Wormface were a stale-
`.pyc` artifact. `V3_NIGHT_BOSS_STRICT_TARGETS` had been retired to
`set()` at module-load (see line 8814 rationale block: "v0.23.11 →
v0.26.x: retired. Originally a 'strictest geometric gate'… Real
geometric concerns are handled by V3_ARENA_ONLY_TARGETS / V3_FRAGILE_
SENSITIVE_TARGETS / anim_class compat"), but the cached bytecode in
`__pycache__/` was holding the pre-retirement state. `find . -name
__pycache__ -exec rm -rf {} +` resolved.

Debug discipline: when the engine load output shows `caliber+=N`
but no `strict+=M`, the strict gate is already retired and any
diagnostic showing nb_strict rejections is reading stale .pyc.

The terrain-arena TODO above is still valid for future pool
widening (more arena-quality slots = more reservation diversity,
fewer cap=2 chrs landing at the same MSB across seeds), but it's
no longer load-bearing — every floored chr currently reserves
reliably without it.

## v0.26.x: xxl_giga_size_drift M-lift + 7-chr unfloor

Two coupled changes per user direction:

**(1) Size-drift gate relaxed for M targets.** Line ~10210 in
`oops_v3.py`: `if tgt_size in ('XS', 'S', 'M'):` → `if tgt_size in
('XS', 'S'):`. Per "Midra should be eligible for any slot that's
occupied by an L, XL, XXL, or GIGA mob. It's asymmetrically
compatible." Removes ~76 false rejections per M-humanoid chr at
XXL/GIGA-source slots. Visual surprise of M-humanoid at GIGA-arena
is the marquee-NB feature, not a bug.

Two seed-388677 unit tests updated (test_pick_target.py
TestGate5_6XxlGigaSourceIntegrity) — the case for size-based
rejection has been retired on the same evidence basis as the
anim_class theory was in v0.24.75 (the actual seed-388677 CTDs
appear to be misattributed; if they recur, narrower per-pair
gates can be added on real evidence rather than blanket size
rules).

**(2) 7 big-boy floors removed.** Field-tier or generic large
enemies that don't need a guaranteed slot — they compete freely
with M-humanoid marquee NBs (Midra/Romina/Metyr/Dragonslayer
Armor/Fortissax) in the XXL/GIGA pool now that M-lift is in
place:
  c3250 Draconic Tree Sentinel (XL)
  c3251 Tree Sentinel (XL)
  c4640 Ulcerated Tree Spirit (XXL)
  c4650 Dragonkin Soldier (XXL)
  c4680 Fallingstar Beast (GIGA)
  c4770 Gargoyle (XXL)
  c4980 Death Bird (XXL)
V3_RESERVATION_FLOORS shrunk 31 → 24 entries. tests/test_v3_
reservation_floors.py marquee set updated. Each unfloored chr
keeps cap=2 in V3_UNIQUE_TARGET_CAPS (ceiling-only enforcement);
they still appear, just not guaranteed.

**Reservation health post-changes** (100 seeds, fresh pyc):
  24/24 floored chrs at 0% unplaced. ✓
  Shifting-earth lockup: clean. ✓
  Diversity: Midra now lands at 10+ distinct MSBs per 100 seeds
  (was 2-3 before M-lift); other M-humanoid NBs similar.

## v0.26.x: MMV size_class bulk correction (18 chrs)

Audit (`data/NpcParam.csv` median hitHeight/hitRadius per c-prefix vs
tagged `size_class`) found systematic undersizing in
`data/mmv_imports.json`: 19 of 33 chrs with hit data mismatched, 18
of those undersized (95% one-directional bias). For comparison, NR
vanilla showed 25% mismatch rate with mixed direction (47 undersized
+ 22 oversized) — noise, not systematic. Heritage pack: zero hit
data matches in the audit (deferred for separate investigation —
likely an NpcParam-ID-range issue or missing data on import).

Corrections applied to `data/mmv_imports.json` with per-entry
`_size_correction_v0_26_x` annotation (cites the NpcParam median
hitHeight/hitRadius that drove the bucket assignment):

  c1310 Outrider Knight                M   → L     (h=3.00, r=1.00)
  c2030 Rennala P1                     M   → XL    (h=4.00, r=0.60)
  c2031 Rennala P2                     M   → XL    (h=4.00, r=0.80)
  c2110 Beast Clergyman / Maliketh     M   → XL    (h=3.60, r=2.50)
  c3110 Unknown (low confidence)       M   → XL    (h=4.00, r=1.90)
  c4511 Lichdragon Fortissax           XXL → GIGA  (h=14.10, r=7.00)
  c4720 Godfrey                        L   → XL    (h=3.70, r=1.10)
  c4721 Hoarah Loux                    L   → XL    (h=3.70, r=1.10)
  c4730 Starscourge Radahn             XL  → GIGA  (h=8.00, r=3.00)
  c5030 Romina                         M   → XL    (h=3.90, r=1.50)
  c5060 Lamprey                        L   → XL    (h=3.50, r=1.00)
  c5061 Lamprey (Large)                L   → XL    (h=3.50, r=1.00)
  c5200 Metyr                          XL  → XXL   (h=5.00, r=5.00)
  c5230 Scadutree Avatar               XXL → GIGA  (h=8.00, r=4.95)
  c5890 Black Knight Horse             L   → XL    (h=3.50, r=0.70)
  c6220 Fire Demon                     L   → XL    (h=4.00, r=1.80)
  c6260 Death Rite Bird                L   → GIGA  (h=8.00, r=3.00)
  c8500 Manus, Father of the Abyss     L   → XL    (h=4.00, r=1.20)

Bucket boundaries used (consistent with NR vanilla anchors):
  M:    h < 2.5
  L:    2.5 <= h < 3.5
  XL:   3.5 <= h < 5.5 OR r >= 2.0
  XXL:  5.5 <= h < 8 OR r >= 3.0
  GIGA: h >= 8 OR (h >= 6 AND r >= 4)

Side effect: 4 chrs (c2030, c2031, c2110, c5030) that were M-humanoid
and got bumped to XL no longer get lifted by the M-humanoid arena_only
auto-lift (the lift fires only for M). They re-entered V3_ARENA_ONLY_
TARGETS via expects_boss_arena=True. Sim confirms they still reserve
at 0% unplaced — just confined to arena slots, which is appropriate
for remembrance-tier bosses.

Two tests updated for new tags:
  test_pick_target.py::TestManusUnBanned::test_c8500_tier_and_size (L → XL)
  test_pick_target.py::TestMmvRosterRestorationV0_24_73::test_c5200_metyr_tagged_v0_24_73 (XL → XXL)

## TODO: heritage_pack size_class verification

The MMV audit script returned **0 chrs with hit data** for
heritage_pack — out of 41 tags. Three possible explanations:
  1. Heritage NpcParam IDs use a different range than the audit's
     `c<prefix> * 10000` mapping
  2. Heritage chrs have placeholder NpcParam data (h <= 0.6 was
     the audit's filter)
  3. Heritage import legitimately doesn't carry hit data

Worth investigating because heritage_pack has 35 chrs blocked by
multiplayer_safe and the size tags affect placement-budget cap
choices. Probably a single afternoon's work to extend the audit
script with a fallback NpcParam-ID lookup strategy and check.

## v0.26.x: terrain arena candidates wired in

Per user direction ("now that we have more terrain data we can use it
to identify more arena slots. criteria is big and flat"):

**Pipeline shipped:**

  dev/audit_terrain_arena_candidates.py
    - Reads data/slot_terrain.json (per-slot navmesh roughness:
      slope_deg, area_3m/5m/10m, d_xz_edge, face_dist, etc.)
    - Filters: slope < 10°, area_10m >= 200, area_5m >= 70,
      d_xz_edge > 2.0, face_dist > 1.0
    - Skips shifting-earth tiles + already-off-mesh slots
    - Cross-references nr_boss_slots.json (dedupe) + nr_all_slots.json
      (vanilla occupant) + NpcParam.csv (occupant size bucket)
    - Output 1: dev/terrain_arena_candidates.json (audit-format,
      includes per-slot metrics for review)
    - Output 2: data/nr_terrain_arena_slots.json (engine-format, 147
      slots to merge into V3_BOSS_SLOT_CATALOG)

  oops_v3.py _load_boss_slot_catalog()
    - Now also reads data/nr_terrain_arena_slots.json
    - For terrain slots already in nr_boss_slots.json: promote arena=True
      if not already (counter: arena_slot_via_terrain_promoted)
    - For new slots: add entry with arena=True, tier='terrain',
      scope='terrain', _source='terrain_audit_v0_26_x', _slope_deg,
      _area_10m, _vanilla_occupant (counter: arena_slot_via_terrain_new)
    - Feeds the existing slot-side arena gate in pick_target_cp at
      line ~11234: `V3_BOSS_SLOT_CATALOG.get((msb, pi), {}).get('arena')`
      — no separate gate logic needed.

**v0.26.x baseline numbers (vanilla NR, default expedition):**
  Catalog size:       344 → 491 slots (+147 terrain-new + 0 promoted)
  arena=True total:   104 → 251 (+147 terrain contribution)
  arena_slot_via_expects:    41
  arena_slot_via_size:       76
  arena_slot_via_terrain_new: 147
  arena_slot_via_terrain_promoted: 0

**Tests added** (4 new in tests/test_arena_slot_derivation.py):
  TestTerrainArenaMerge — file-exists, all-slots-flagged, count-matches,
  source-tag-present.

**What this unlocks:**
  arena_only_targets (Romina/Maliketh/Midra/Metyr/Dragonslayer Armor/
  etc., the marquee NB roster post-MMV-size-correction) can now land
  at terrain-quality slots that lack a variant-name marker. The 15
  high-confidence candidates (vanilla occupant L+) are the clearest
  wins: e.g. Giant Crab slots at m60_44_38 pi=10 (area_10m=349, slope=
  3.3°) are now valid arena destinations.

**Re-tuning knobs** (CLI args in dev/audit_terrain_arena_candidates.py):
  --slope-max          (default 10.0°)
  --area-10m-min       (default 200.0 m²)
  --area-5m-min        (default 70.0 m²)
  --edge-min           (default 2.0 m)
  --face-min           (default 1.0 m)
  Tightening to slope < 5° + area_10m >= 300 would prune to a
  smaller, more conservative set if playtest shows the broader set
  produces problem placements.

## Closed by this work

- "arena-slot-from-terrain task above" (from the original terrain-
  arena TODO in this file) — closed by the shipped pipeline.
