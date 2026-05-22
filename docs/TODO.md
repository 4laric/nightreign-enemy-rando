# TODO / Future Work

Living list of open items, deferred fixes, and ideas worth circling back to.
Add date next to entries when noted; remove when resolved (and document the
fix in CHANGELOG.md).

## High priority — known bugs awaiting data

- **Guardian Golem (Cathedra) slot — gate occupants on idle/entrance
  animation** (2026-05-21). The Guardian Golem arena (the "Cathedra"
  slot) breaks characters that are otherwise resilient everywhere else
  in the corpus — Death Knight is the confirmed case. Working
  hypothesis: the slot's EMEVD/spawn setup hard-requires the occupant
  to have an idle/entrance animation, and chrs without one fail there
  specifically (where they're fine elsewhere). Proposed fix: a
  slot-specific gate on this one slot — only allow occupants that have
  an idle/entrance anim; let everything else fall back to vanilla for
  this slot only. Do NOT make this a global filter; it's a property of
  this slot, not of those chrs.

  Plays *really* well with anything that emerges/rises into the fight —
  confirmed-good occupants observed: Sanguine Noble, Magma Wyrm, Giant
  Fingercreeper, dragons. So the gate should be permissive (emergers
  are great here); it's specifically the no-idle/no-entrance chrs that
  need excluding from this slot.

  Action: identify the Cathedra/Guardian Golem slot's entity + map in
  the slot catalog, confirm the idle/entrance-anim hypothesis against
  Death Knight's anibnd vs a working emerger, then add the
  slot-scoped gate. This is a small targeted fix scoped to one slot,
  not an architectural pass.

- **Expunge cluster awareness; replace with mount/rider pair tracking**
  (2026-05-21). Architectural simplification. The general cluster
  abstraction was scaffolding built around the cluster-anim CTD theory,
  which has since been ruled out. With that theory dead, almost none of
  the cluster machinery earns its keep — and the cluster-OFF behaviour
  ("a bunch of randomized guys", each Part rolling independently) is the
  behaviour we actually want for nearly every multi-part encounter:
  Oracle Envoy trios, Alabaster Lords duos, Crystalian groups all play
  fine as independent rolls. So: delete cluster awareness from the
  engine entirely.

  **What gets removed:** `cluster_aware` mode and its GUI toggle, the
  `_cluster_only` tag and all handling of it, `compute_part_clusters`
  and the cluster-aware swap path, `_cluster_only` source/target
  excludes, and any per-map cluster excludes that exist only to paper
  over cluster-anim CTDs. The default (and soon only) behaviour is
  every Part rolls independently from the universal pool.

  **The one real exception — mount/rider pairs.** The *only* structural
  relationship that genuinely must be tracked is a mount and its rider:
  swap them uncoordinated and you get a rider standing on nothing, or a
  horse with a dragon welded to its back. This needs a small, narrow,
  purpose-built system — NOT the general cluster abstraction.

  **Mount/rider pair tracking — design:**
    1. Build `V3_MOUNT_CLASS_POOL` at load_data time. Mount cps:
       c3160 Funeral Steed, c4060 Kaiden's Horse, c4363 Lordsworn Horse
       (all tier=mount_component). NOTE: not all mounts are horses —
       c3180 Albinauric Archer's Wolf is a wolf-class mount with a
       humanoid rider and must be in the pool. "Mount class" is the
       category, not "horse class".
    2. Detect a mount slot at swap time: source cp is in the mount pool
       AND has a paired-rider slot nearby (spatial proximity + size/
       anim_class heuristics — no cluster system needed for this; it's
       a local pairwise check).
    3. At mount slots, restrict the target pool to V3_MOUNT_CLASS_POOL.
       At the paired rider slot, restrict to M humanoid (tier in
       {grunt, miniboss, trash} + anim_class='humanoid' +
       size_class='M').
    4. Remove c4060 (and other mount cps) from
       `V3_EXCLUDE_TARGET_PREFIXES` so they're valid picks at mount
       slots.

  **Kaiden Sellsword is the pilot / canonical case.** c4050 Kaiden
  Sellsword + c4060 Kaiden's Horse — the target aesthetic is "random
  mount-class chr + random M humanoid on top" ("an albinauric
  cartwheeling up there"). Both c4050 and c4060 are currently
  target-excluded, so Kaiden never even appears. This entry's
  mount/rider system is what unblocks that — it's the highest-fun-per-
  line feature remaining.

  **Touchy instances — leave alone.** c3150+c3160 Funeral Steed is the
  Night's Cavalry encounter; c4061+c4363 Lordsworn Knight + Horse is
  the v0.19.3 softlock night-boss instance. User has explicitly said
  leave both alone. So mount/rider swap must be opt-IN per source site
  (or those instances need slot-specific exclusion — see the Lordsworn
  night-boss instance TODO below). Do NOT blanket-apply.

  **Sequencing.** (1) Build mount/rider pair tracking + the Kaiden
  pilot first, while `cluster_aware` still exists, so there's no
  capability gap. (2) Confirm via playtest spoiler audit that Kaiden
  pairs swap correctly and the touchy instances are untouched. (3)
  Then rip out cluster awareness. Doing the removal last means the
  engine is never without a working mount/rider story.

  **Explicitly NOT affected:** type-agnostic mass-spawn EMEVD calls
  ("spawn N chrs of type X" — Tibia skeleton summons, Miranda
  death-spawns, evergaol-style mass spawns). Those never depended on
  cluster awareness; they roll randomized chrs already and play great.
  This entry does not touch them.

- **Lordsworn night-boss instance — slot-specific exclusion**
  (2026-05-12). User notes one specific instance of c4363 Lordsworn
  Knight's Horse in a night-boss encounter has been "proven touchy"
  in playtest. The cp-wide source exclude would over-restrict (c4363
  appears in many random Limveld tiles and other contexts that are
  fine to randomize); we want to protect just the one instance.

  Action item:
    1. Identify the specific (msb_name, part_index) of the touchy
       instance. Likely candidates: c4363 placements at m49_xx night
       boss arenas, or scripted Night Boss intro slots elsewhere.
       Playtest spoiler logs from past sessions probably have the
       slot identified.
    2. Add to `V3_PROBLEM_SLOTS` (the existing slot-specific exclude
       mechanism documented at oops_v3.py:402 — "(msb, pi)-level
       exclusion" framework).
    3. Confirm c4363 randomization elsewhere works fine — the goal is
       NOT to source-exclude c4363 wholesale.

  Same machinery would also let us do (msb, pi)-level cathedral
  exclusion for the c3620 case if we eventually want to randomize
  the non-cathedral c3620 placements while keeping the cathedral
  cluster vanilla — finer-grained than the current source-wide
  exclude.

- **V3_POSITION_SHIFTS curation** (2026-05-12, infrastructure shipped
  v0.23.72-late). The mechanism for fragile-slot rescue via XYZ position
  translation is in place — `V3_POSITION_SHIFTS` data structure,
  `lookup_position_shift` helper, T0 override in `is_fragile_slot`, and
  apply-time write in `shuffle_msb_v3` are all wired. The table itself
  is empty pending playtest data.

  How to populate. After each playtest where a slot was observed
  spawning-into-terrain / sub-surface / clipped against geometry but
  the fragility seems point-specific (not "whole region is rough"),
  add an entry:
  ```
  V3_POSITION_SHIFTS[(msb_name, part_index)] = {
      'dxyz': (dx, dy, dz),
      'note': '<problem observed> — <why shift works>',
      'observed_in': 'seed N playtest',
  }
  ```
  Y-only lifts (e.g. `(0.0, 2.0, 0.0)`) are the safest shift class
  since they rely on gravity to settle the chr onto terrain.
  Horizontal shifts (XZ) need more care — confirm there's open
  geometry in the shift direction.

  Curation rules already documented in the source comment block above
  the V3_POSITION_SHIFTS dict. Key constraint: never shift event-
  anchored slots (the EMEVD will reference the vanilla position).
  When in doubt, check that the slot's entity_id doesn't appear in
  common_func.emevd before adding a shift.

  Will pair with the sensitivity-test seed (separate TODO entry below)
  for systematic discovery: that tool walks fragile slots with a
  candidate-rotation, surfacing problem-shaped slots as "would benefit
  from shift" candidates.

- **Tunnel-wakeup bug hypothesis** (2026-05-04 flagged during diagnostic-
  mode playtesting). User suspects there may be a freeze pattern at
  underground/tunnel slots that is INDEPENDENT from the existing rocky-
  terrain pathing failures we capture as "fragile." Current SENSITIVE
  list is built from observed freezes without distinguishing root cause —
  some entries might actually be tunnel-wakeup victims, not terrain
  victims. Conflating the two would mean SENSITIVE is over-inclusive on
  some axes and under-inclusive on others.

  **Diagnostic plan when we get to it:**

    - Identify tunnel slots specifically (interior dungeon MSBs vs.
      open-field). The `m32_xx` Madness Caves, `m38_xx` Cathedral
      interiors, `m48_xx` mining tunnels, and `m49_xx` evergaol
      interiors are candidate tunnel-class maps. A precise list will
      need pos-data analysis (low-y, walled topology) plus manual
      verification.
    - Restrict the placement pool at tunnel slots to enemies that we
      know pathfind well on flat terrain (RESILIENT-class or further
      validated subset), to remove pathing as a confounding variable.
    - Bisect the entrance-animation axis: fork into two test cohorts —
      (A) enemies with NO entrance animation (immediate spawn,
      idle-stand pose), and (B) enemies with VERY LONG entrance
      animations (multi-second emergence, drop-from-ceiling, rise-
      from-ground). If only one cohort freezes, that localizes the
      bug to entrance-anim length / wake-state interaction with the
      tunnel script timing. If both freeze, it's something else
      (geometry collision, navmesh boundary, etc.). If neither
      freezes, the tunnel-wakeup hypothesis is wrong and the existing
      SENSITIVE entries from tunnel maps are pure terrain failures.
    - Implementation hook: extend the diagnostic-mode kwarg surface
      with a `tunnel_pool_filter` (or similar) that lets us specify
      which entrance-anim category gets to populate tunnel slots.
      Probably wants a small classification of c-prefixes by entrance-
      anim length first — that's a data-tagging task on the roster
      side, similar to how `expects_boss_arena` works today.

  Implication if confirmed: SENSITIVE could split into two sets —
  `V3_TERRAIN_SENSITIVE` and `V3_TUNNEL_WAKEUP_SENSITIVE` — applied
  by slot category instead of unioned at every fragile slot. Some
  c-prefixes currently in SENSITIVE might be safe in open-field
  fragile slots (hard terrain passes, just not tunnels), expanding
  the eligible pool meaningfully at non-tunnel fragile slots. Worth
  investigating once the current SENSITIVE-from-RESILIENT migration
  stabilizes.

- **Bats problem** (2026-05-03 flagged) — circle back. The current
  `V3_AERIAL_SOURCE_ALT` whitelists for c4200/c4201 bats are a partial
  workaround for aerial-source cases, but the full bats compatibility
  story isn't resolved. Symptoms / root cause / scope to be re-investigated
  next playtest cycle.

- **Cathedral / tunnel m60_xx overworld broken slots** — the v0.19.2/3
  fixes catch m38_xx (interior cathedral) + m32_xx (tunnels) + qualifier-
  tagged slots, but the central-east overworld cathedral region
  (m60_43_37_xx, m60_43_38_xx grid cells) has problem slots whose source
  variants are plain-named (`Wolf`, `Demi-Human`, `Starcaller`, `Basilisk`)
  with no qualifier. These escape T1 + T2 detection. Awaiting playtest
  data to populate `V3_PROBLEM_SLOTS` (Tier 3).

- **High-y Rat outliers** — v0.18 fix took Rats from 84% out-of-distribution
  to ~18%. Two surviving outliers at `m60_44_37_50.msb pi=7` (y=31.05) and
  `pi=8` (y=88.05). Both src=c4070 Wolf at same map. Slot_y propagation
  through pick_target_cp suspected; investigation deferred. Low-priority —
  occasional cosmetic, not softlock.

- **m32_20 Madness Encampment "couple frozen Wandering Nobles"**
  (2026-05-04) — partially addressed in v0.20.23 by removing c4300
  Wandering Noble from `V3_RESILIENT_BIPEDS` and adding it to
  `V3_FRAGILE_SENSITIVE_TARGETS`. Open question: is m32_20 just
  generally rough on humanoid bipeds, or are pi=43/44 specific
  bumpy spots that ANY current resilient biped would freeze on?
  The sensitivity-test tool below is the right way to find out.

## Diagnostic methodology

### Sensitivity-test seed (planned, not yet built)

A counterpart to `terrain_test_seed.py` for finding which c-prefixes
break at risky (fragile-classified) slots. Different shape: instead of
a binary on_mesh/off_mesh classifier producing two fixed targets, it
takes a **list of candidate c-prefixes** and **distributes them** across
risky slots so each candidate gets visited by the player at multiple
fragile spots.

Why we want it. Right now the only mechanism for moving a c-prefix
between RESILIENT_BIPEDS and FRAGILE_SENSITIVE_TARGETS is one-off
playtest reports of "this enemy was frozen here." That's noisy,
slow, and biased toward enemies the player happens to remember
fighting. A purpose-built test seed turns sensitivity classification
into a deterministic walk-through:

  1. Pick a candidate list (e.g. 6–10 marginal humanoid bipeds we
     haven't classified — Glintstone Sorcerer, Page, Mausoleum
     Foot Soldier, Putrid Corpse, Erdtree Guardian, Scaly
     Misbegotten, etc.).
  2. Distribute them deterministically across all fragile slots so
     each c-prefix lands on a representative variety of fragile
     terrain (cathedral, encampment, fort, tunnel, cliff perches).
  3. Run the seed in NR. Walk the world.
  4. Note which (c-prefix, msb, pi) combinations are frozen.
  5. Frozen → SENSITIVE_TARGETS; clean → RESILIENT_BIPEDS.

Distribution strategy. For N candidates and M fragile slots, the
seed assigns slot[i] → candidates[i mod N]. Deterministic per slot
so two runs of the same candidate list classify the same slots the
same way; ordering of slots within each map keeps spatially-adjacent
slots on different candidates so the player sees variety walking
through one map.

CLI shape, mirroring `terrain_test_seed.py`:
```
python sensitivity_test_seed.py <vanilla_msb_dir> <output_msb_dir> \
    --candidates c3702,c3703,c3650,c3661,c3451,c4375 \
    [--slot-class fragile]    # default: all fragile slots
    [--include-non-fragile]   # also place at non-fragile slots for control
```

Engine plumbing. Same pattern as `terrain_test_targets`: a kwarg
through `cmd_shuffle_v3` → `shuffle_msb_v3` that, when set, bypasses
`pick_target_cp` for fragile slots and assigns the deterministic
candidate. Non-fragile slots randomize normally.

Spoiler addition. The spoiler should render a "Sensitivity test
candidate placements" section grouped by candidate c-prefix:
each c-prefix's row shows every (msb, pi) it landed at, with
fragile/non-fragile flagged. The user marks frozen ones, sends
the marked-up list back, classifications update.

Roughly a one-day build given how much of the plumbing already
exists for terrain_test_seed. Worth doing when the
SENSITIVE/RESILIENT classification feels under-validated.

### Existing methodology — Oops-all-Rat sweep

- **Oops-all-Rat sweep** — pick a c-prefix known to break occasionally
  (Rat, Octopus, Slug, Spirit Jellyfish), run oops-all in vanilla NR,
  walk the world systematically tagging broken placements. Each broken
  (map, pi) is a Tier 3 candidate for `V3_PROBLEM_SLOTS`. Oops-all
  bypasses pick_target_cp, so fragile-slot restrictions don't apply —
  truly tests every slot.

  Best as a multi-session activity: pick one biome per run (Limveld
  central, mountaintop, crater, cathedral, tunnels) so the dataset
  is geographically organized.

  Tool: `diagnose_problem_slots.py` takes a text file of broken
  (map, pi) entries and outputs (a) ready-to-paste V3_PROBLEM_SLOTS
  dict entries with source context, (b) pattern analysis showing
  common qualifiers / source c-prefixes / map cells, (c) tier-upgrade
  candidates if patterns repeat 3+ times.

  ```
  python diagnose_problem_slots.py \
      --spoiler /path/to/_spoilers.json \
      --broken broken_slots.txt
  ```

  Where `broken_slots.txt` is one `msb_name,part_index [optional comment]`
  per line.

## On terrain detection from MSB alone

MSB files contain Parts (positions, model refs, NpcParam IDs) and Region
trigger volumes — but NOT terrain geometry, navmesh, or slope data. Those
live in separate `.havok` / `.btab` / `.flver` map asset files.

Without raycasting against actual terrain, "is this slot on bumpy
geometry" can only be approximated via proxies:
  - Vanilla source c-prefix navigation profile (Rat slots are flat by
    definition; Wolf slots tolerate moderate slope; Crystalian slots
    are isolated platforms)
  - Y-coordinate distribution within a map cell (anomalous y → perch/dip)
  - Cluster orphan analysis (isolated slots > 30 units from neighbors)
  - Sentinel position detection (`pos = (X, 0.0, 1.0)` is a placeholder,
    not a real placement)

## Deferred features (not bugs)

- **Centipede Demon body-segment randomization** (2026-05-12 update;
  ACTIONABLE-NOW portion shipped, body-segment scope still deferred).
  Centipede Demon (c7710) is a vanilla NR night boss with a body-shed
  mechanic: parts of its body fall off mid-fight and become independent
  hostile ads — the segment c-prefixes are c7711/c7712 (Centipede Grub).
  The detach event chain is hand-authored EMEVD logic in the Centipede
  arena's m4x map, not something the MSB-Part-shuffle engine reaches.

  Randomizing the SEGMENT ADS specifically (model swap on c7711/c7712
  while preserving the detach event) remains pure EMEVD scope and would
  be visually wild. Filing for someone-else's-future-day. Requires:
  (1) identify which entity_ids the detach event chain sets spawn flags
  on, (2) figure out how to swap the chr model at those entity_ids
  without breaking the event, (3) playtest to confirm the swapped ads
  still spawn correctly when the boss sheds segments.

  RESOLVED v0.23.72-late: the prerequisite tag-completion work is done.
  c7710 Centipede Demon is now properly named + tiered as night_boss
  + flagged script_spawn (target-only). c7711/c7712 Centipede Grub are
  tagged as grunt-tier ads. The 3 entries in nightlord_pools.json
  (sentient_pest n1[1], equilibrious_beast n1[2], night_aspect n1[2])
  now carry `c_prefix: c7710` so spoiler tooling can identify them. The
  stale `_note: 'DS1 heritage boss'` was removed — Centipede Demon
  is fully vanilla NR (it was misclassified in nightlord_pools.json
  during the initial pass). Same correction batch fixed Gaping Dragon
  (c7700), Duke's Dear Freja (c7800) + Spiderling (c7810), Smelter
  Demon (c7820), Dancer of the Boreal Valley (c7920), and the
  previously-broken Nameless King (c7900) + Mount (c7910) which had
  empty roster mmv_names and were getting auto-excluded.

- **Heritage tab per-row install action** — subprocess `heritage_install.py`
  from the selected scan row. Currently requires manual command-line
  invocation; would be a quality-of-life upgrade.

- **Manual promotion expansion** — v0.19 added 4 entries (Ancestor
  Spirit, Grafted Scion, Nameless King, Storm King). Other candidates
  if expanded coverage is wanted: Tricephalos variants (c7530, c7541
  — names not in Paramdex but inferred Nightlord-tier), Caligo c4900/c4901
  (already heritage-tagged but worth verifying), additional Field Boss
  c-prefixes per future playtest data.

- **Putrescent Knight (c5020) import** — discussed 2026-05-03 as
  candidate single-c-prefix import via heritage_pack flow. Plan entry
  added to `batch_import_plan_comprehensive.json` with placeholder tag
  values. User to run `heritage_install.py --c-prefix c5020 --dry-run`
  in their Windows shell, then live-fire if dry-run is clean.

- **thefifthmatt's NR randomizer integration** (filed v0.23.07).
  Researched 2026-05-06; not actionable this cycle but worth filing.
  His mod (https://www.nexusmods.com/eldenringnightreign/mods/277,
  source at https://github.com/thefifthmatt/SoulsRandomizers) is a
  file mod that "creates map patterns nearly from scratch" — generates
  randomized map_pattern entries that determine which arenas/camps/
  bosses sit where in the cell grid. Each base Nightlord normally has
  40 patterns (20 baseline + 5 per Shifting Earth × 4); his randomizer
  produces many more.

  Critically, his mod does NOT modify enemies inside MSBs — that's
  explicit future scope on his page ("can be extended to randomizing
  enemies and bosses within maps"). That's exactly our niche. The
  two operate at different layers and don't overlap.

  STACKING ARCHITECTURE (untested):
    vanilla NR files
       → fifthmatt's randomizer (writes randomized map_pattern data)
       → our randomizer (Part-level shuffle on resulting MSB outputs)
       → me3 profile loads the final files

  Open compat questions before integrating:
    - Does his randomizer rename MSBs or always produce the same
      filename set we expect (m48_50_00_00.msb etc.)?
    - Does he modify MSB Parts at all, or strictly map-tile placement?
      If the former, our shuffle could fight his changes.
    - Does cell-grid expansion he does introduce MSBs into positions
      with geometry incompatibilities our shuffle doesn't expect?

  USEFUL SIDE BENEFIT: his https://thefifthmatt.github.io/nightreign/
  publishes per-Nightlord per-pattern dumps (URLs like /gladius/010.html
  through /gladius/040.html). That's exactly the data structure needed
  to fill in `data/nightlord_expedition_table.json` without playing
  through. The site is Jekyll-published from raw data files in
  `thefifthmatt/thefifthmatt.github.io` — fetching the underlying JSON
  would likely give us the canonical Nightlord→arena pool mapping.

  LICENSING NOTE: source is "source-available but ... currently not
  freely licensed. ... contributions are not accepted. Do not
  distribute the randomizer, forks of the randomizer programs, or
  forks of config files." Integration approach: USE his outputs as
  inputs to our pipeline; DON'T fork his code or redistribute his
  config. Reading published reference data on his github.io site
  for our expedition table is fine (publicly hosted reference, not
  source code).

  ACTIONABLE FUTURE STEPS:
    1. Fetch a sample github.io pattern page, see if data structure
       is parseable (probably JSON-in-HTML or static pages we'd scrape)
    2. Build optional `--fifthmatt-input` flag on cmd_shuffle_v3 that
       takes a directory of his outputs as inputs instead of vanilla
    3. Test stack with one seed × all Nightlords; confirm no MSB
       filename collisions
    4. Reach out to thefifthmatt in the Nightreign rando Discord
       (https://discord.gg/QArcYud) for the two open compat questions
       above and to gauge his interest in the integration

- **ER NPC_PARAM import — Pass B: 4 base-faction Lordsworn cps**
  (2026-05-12 narrowed from original v0.23.07 audit). The original
  doc flagged 32 unrostered cps; reconciled to current state:
    - 11 already integrated by post_dlc_dump
    - 16 unlocked in v0.23.72-late "Pass A" via name fill-ins
    - 1 (c4730 Starscourge Radahn) covered by MMV import — done
    - 2 (c4720 Godfrey, c4721 Hoarah Loux) covered by MMV import — done
    - **4 genuinely-unrostered**: c4310 Lordsworn Soldier, c4350
      Lordsworn Knight, c4360 Lordsworn Knight's Horse, c4370 Foot
      Soldier. These are the base-faction variants of the c43XX
      Soldier/Knight family. Chr files exist in vanilla NR's chr/
      folder but no NpcParam rows exist in NR's regulation (likely
      stripped during the ER→NR port since NR uses the faction
      variants — c4311 Godrick Soldier, etc — for all encounters).

  Implementation path for the 4 remaining cps:
    1. Acquire ER's NPC_PARAM_ST rows for c4310/c4350/c4360/c4370 via
       SoulsFormats extraction from a vanilla ER regulation.bin, or
       pull from vawser's ER-Documentation tools.
    2. CSV-author the NpcParam rows into NR's regulation.bin via
       Smithbox (Param Editor → NPC_PARAM_ST → import rows).
    3. Add tag entries + variant entries to nr_enemy_tags.json /
       nr_enemy_roster.json mirroring the faction siblings:
         - c4310 mirror c4311 Godrick Soldier (grunt, M, humanoid, hp~448)
         - c4350 mirror c4351 Godrick Knight (miniboss, M, humanoid, hp~576)
         - c4360 mirror c4363 Lordsworn Knight's Horse (mount_component, XL, quadruped)
         - c4370 mirror c4371 Godrick Foot Soldier (grunt, M, humanoid)
    4. Playtest each in a small map via diagnostic-mode forced placement
       (set `non_fragile_baseline_cp` and confirm clean spawns).

  Yield estimate: 4 new humanoid grunt/knight variants for encampment
  variety. Castle Knight (c4350) specifically is the most-used base
  ER soldier and would look great as a frequent placement. Total scope:
  ~half a session of CSV authoring + playtest if regulation extraction
  is straightforward. Skipped during the v0.23.72-late ER NPC_PARAM
  import pass because the Smithbox workflow isn't in-pipeline.

- **`docs/UNROSTERED_ENEMIES.md` regeneration** (2026-05-12). The
  document was authored against the v0.23.06 roster snapshot and is
  now substantially stale — 28 of its 32 listed cps have either been
  integrated (post_dlc_dump catch + Pass A name fill-ins) or covered by
  MMV. The remaining 4 are documented in the TODO above. Worth
  regenerating from current data so future readers don't get misled.
  Low priority since the live TODO carries the actual remaining scope.

- **`v0.23.72-late tag-but-no-variants auto-exclude` audit**
  (2026-05-12). The new auto-exclude rule caught 4 MMV cps with tag
  claims but no variant data: c4540, c4541, c5650 (likely Hippopotamus
  variant), c6230. All four are tagged "Unknown MMV import" with
  expects_boss_arena=True. Worth tracking down their actual identities
  in MMV's source — if they're real ER/SoTE chrs the MMV manifest just
  failed to extract variants for, completing them would unlock 4 more
  boss-tier placement candidates. If they're orphan claims (MMV
  authored tags for chrs whose assets were later cut), removing the
  tag claims entirely is cleaner. Either way: needs a look at MMV's
  source repo (nexusmods.com/eldenringnightreign/mods/578) to identify
  what each cp was supposed to be.

- **Single-c-prefix import script** — refactor the heritage_pack batch
  flow into a clean single-import path (`import_one.py`) for tighter
  iteration when adding individual ER enemies. Currently the batch tool
  works, but is harder to debug when one chr misbehaves.

- **BFER code removal — dead-integration cleanup** (2026-05-21). BFER
  integration was abandoned (see `docs/OPEN_ISSUES.md`). The support
  code survives in the tree, inert: `bfer_imports.json` /
  `bfer_imports_v2.json` (both `_meta.enabled=false`),
  `dev/audit_bfer_variants.py`, and the BFER-specific engine constants
  and branches (`V3_BFER_*` sets, the boss-tier gate, the OOPS_ALL_NB
  intercept, the prefix-fallback hardening), plus the BFER pack
  references in the GUI's chr Inventory tab. None of it runs, but it's
  confusing dead weight for any future reader. When convenient: grep
  `BFER` / `bfer` across `oops_v3.py`, `oops_rando_gui.py`, and `dev/`,
  remove the inert paths, delete the two manifest files, and drop the
  audit script. Low priority — inert code isn't hurting anything, this
  is pure hygiene. Leave the `CHANGELOG.md` mentions alone (historical
  record, not a live recommendation).
