## v0.27.8

Grunt/trash tier collapse + re-cap. The 20-seed sim
(dev/simulate_engine.py) showed the grunt/trash tier had no shaping
below a flat cap of 50 — 52 of 105 eligible chrs saturated at the
ceiling (74% of all grunt placements) while ~14 sat at <=2/seed.

### Changes

- The 'trash' tier is collapsed into 'grunt'. load_data() retags every
  trash chr to grunt (50 chrs), so the whole engine — caps, floors,
  the boss-bar gate, target pools — treats them as one tier. The
  grunt/trash distinction is gone.
- Grunt tier (now incl. former trash): cap=32 and reservation floor=4
  for every eligible chr (104), applied across the board, overriding
  any prior hand-tuned cap. cap 32 trims the saturated band (down from
  the implicit global 50); floor 4 lifts the cameo tail.
- The _LIFTED_V0_24_65 defensive cap=1 mechanism is removed. The lifted
  chrs have been playtested since v0.24.40 without reported CTDs; each
  now takes its tier cap (grunt 32, miniboss 4). The frozenset is kept
  only as a record of the historical lift. NOTE: this re-exposes c5930
  Giant Skeleton / c6220 Fire Demon (invisible-render history) at up
  to 4x/seed.
- c6201 Scarab is excluded — it carries a tag but has no roster
  variants (an orphan; the sim placed it 0/20).
- Miniboss tier: with the _LIFTED exemption removed, all 76 eligible
  minibosses are now uniformly cap=4 (was 70 + 6 exempt at cap=1).

### Validated

Real engine, 3 seeds: 0 grunt cap>32 violations; grunt placements
~2,990/seed (down from ~3,300). floor=4 lifts the rare tail from 14
sub-2/seed chrs to 1. Two genuinely compat-starved grunts (c4171
Giant Putrid Flesh, c4481 Miranda Sprout) still land 2-3 — the
reservation pre-pass cannot find 4 compatible slots for them, so the
floor is best-effort, not a hard guarantee. Test suite at the
53-failure baseline.

## v0.27.7

MSB-free decision simulation. Tooling — the engine's placement
behaviour is unchanged (the one engine edit is a behaviour-neutral
optional parameter).

### What it adds

The placement engine reads two things from the binary MSBs: a per-Part
slot inventory (source c-prefix, npc/think params, entity id, position,
variant) and the Models section (needed only to write output). v0.27.7
makes the *decision* path runnable without the binaries:

- dev/emit_slot_inventory.py -> data/nr_slot_inventory.json — the
  complete per-Part decision input (5,329 enemy Parts across 195 MSBs),
  emitted once from the decompressed MSBs. Superset of
  nr_slot_metadata.json: adds think_param_id, position, and the
  resolved source variant_name.
- dev/simulate_engine.py — reproduces the shuffle decisions (swap_plan,
  reservations, placement counts, the v0.27.4-6 size gates) from that
  JSON, with no MSBs and no Oodle. It calls the engine's own
  pick_target / _reject_target_for_slot / _compute_unique_reservations
  / RunContext, so the decision logic IS the engine's.
- _enumerate_unique_candidate_slots / _compute_unique_reservations gain
  an optional inventory= parameter (default None = unchanged binary
  path) so the reservation pre-pass runs inventory-fed.

### Fidelity

Validated against the real engine on 3 seeds: total placements within
-0.4%, distribution correlation r = 0.96-0.98, 0 cap violations, 100
reservations honoured. It is a faithful decision-logic model, not a
per-seed byte clone — exact reproduction would require replicating the
rider/mount collapse pass and bit-matching rng consumption across the
full pipeline (merchant swaps, MSB iteration order), which a
decision-sim omits. For cap/distribution tuning and CI it is what is
wanted: change a cap, see the distribution response, no corpus and no
decompression.

### Not covered

Output .msb byte generation (inherently needs the binaries); the
diagnostic-only oops_all / terrain_test / pinned modes; hub MSBs
(pinned-only in production, normally empty).

## v0.27.6

Miniboss caps — "4 across the board". Follows the v0.27.3 floor pass.

### The change

v0.27.3 floored the whole miniboss tier (floor=1) but left caps
uneven — 6 for the previously-uncapped bulk, plus pre-existing
hand-tuned 1/2/8 values. v0.27.6 sets every miniboss-tier chr to a
uniform cap of 4 (a power of 2): the v0.27.3 cap=6 default comes down
to 4, Elder Lion (c4270) and Royal Revenant (c4020) come down from 8,
and the prior single-boss feel-caps (Red Wolf c3181, Great Red Bear
c5820, etc.) are raised from 2. Floor=1 + ceiling=4 across the tier —
guarantee one, allow up to four.

Exempt: the _LIFTED_V0_24_65 defensive cap=1 chrs (c5930 Giant
Skeleton, c6220 Fire Demon, c4140, c4441, c4811, ...). That cap limits
the blast radius of a chr that may still be runtime-broken — a
different concern from miniboss feel-tuning — so it stands. Night-boss
and field-boss tiers are untouched.

Result: 70 miniboss-tier chrs set to cap=4 (6 lifted/defensive-cap
chrs exempt; 11 hard-excluded chrs have no live cap either way).

### Validation

3-seed sim (714653 / 628653 / 42): 0 unplaced, no cap-4 miniboss
exceeds 4 placements, ~220 miniboss placements/seed across the 70
capped chrs. Full test suite at its 53-failure baseline — three tests
pinning superseded pre-v0.27.6 caps (Red Wolf cap=2, Ghostflame
archetype, the cap=1-GIGA smoke threshold) updated to the new policy.

Minor effect: ~40 fewer placements/seed (~3,660 -> ~3,620) — tighter
caps exhaust the dominant minibosses sooner, so a few late slots stay
vanilla rather than place a 5th/6th copy. ~1%, intended direction.

## v0.27.5

Size-handling refactor, Stage 2 — the BIG_PROXIMITY and DENSITY_CAP
swap-plan post-passes are converted to placement-time gates. Completes
the refactor begun in v0.27.4 (geometry gate) and resolves the
reservation-floor-demotion bug.

### The problem

Two of the five size mechanisms were swap-plan POST-passes: they ran
after a whole MSB was placed, then walked the finished plan and
*demoted* big chrs — BIG_PROXIMITY (v0.21) demoted the higher-pi of any
two XL+ within 30u; DENSITY_CAP (v0.23.61) demoted excess once an MSB
exceeded 3 XL+ / 10 L+ (tunnels 0 / 4). Demoting after the fact meant a
big was placed badly and then evicted, and — the real bug — the
post-passes ran after the reservation pre-pass, so a reserved big chr
sitting in its guaranteed slot could be demoted right back out. The
v0.27.2 98-seed audit measured this: Smelter Demon below its floor in
50% of seeds, Dancer 40%, despite both being reserved every seed. The
post-passes also carried ~250 lines of demotion machinery (caliber
mirror, cap accounting, Gate-5.6 mirror, slug fallback) that existed
only to re-implement, badly, what the picker already does.

### The change

BIG_PROXIMITY and DENSITY_CAP are now Gates 8 and 9 in
`_reject_target_for_slot`, evaluated at pick time against per-MSB
running state on the RunContext (placed-big positions, XL+/L+ counts,
per-MSB caps). When a big would clip a neighbour or bust the budget it
drops out of the candidate pool and the picker selects a smaller chr
through its normal pipeline — so there is no separate demotion path and
none of the mirror machinery is needed. The slot loop is pi-ascending,
so "low-pi wins" matches the post-passes' "first-pi wins / highest-pi
demoted" exactly.

The gates are inert unless `run_ctx.msb_size_gate_active` is set, which
`begin_msb()` does only inside `shuffle_msb_v3`'s slot loop. The
reservation pre-pass and the reservation early-return never arm them —
so a reserved big chr is never proximity/density-rejected and can no
longer be demoted. This closes the reservation-floor-demotion bug
(docs/OPEN_ISSUES.md).

Both post-passes (487 lines) are deleted. `RunContext` gains per-MSB
size state plus `begin_msb()` / `end_msb()` / `register_big()`.

### Validation

5-seed sim (714653 / 628653 / 42 / 394059 / 877217): 0 proximity
violations (no XL+ pair within 30u), 0 density over-cap MSBs, 100
reservations honored and 0 below-floor each seed. Full test suite back
to its pre-session 53-failure baseline (all 53 predate this work).

Known minor effect: ~40 fewer placements per seed (~3,700 -> ~3,660).
Slots whose entire compatible pool is big-and-over-budget now stay
vanilla rather than receive the old DENSITY_DEMOTE_FALLBACK slug — a
~1% diversity reduction at genuinely over-budget slots, in exchange for
never force-placing a slug. `V3_DENSITY_DEMOTE_FALLBACK_CPS` and
`V3_BIG_PROXIMITY_DEMOTE_TO_SIZES` are now dead constants (trivial
follow-up sweep).

## v0.27.4

Geometry-aware size gate (Stage 1 of the size-handling refactor). The
first of two stages replacing scattered, blunt size logic with
placement-time gates driven by the slot-terrain data the engine now has.

### The problem

Size handling was spread across five mechanisms: the BIG_PROXIMITY and
DENSITY_CAP swap-plan post-passes, plus three placement-time gates in
`_reject_target_for_slot` (Gate 6 XXL/GIGA-source integrity, Gate 7
"XXL at XS/S/M/L-source -> reject", Gate 7.5 slope-aware size-up).
Gate 7 was the bluntest: it banned XXL at every non-XXL/GIGA vanilla
slot with no geometry check at all, threw away ~46 legitimate L-source
slots by its own comment's admission, and never covered GIGA.

### The change

Gate 7 is now a geometry-aware size gate. A slot's size capacity is the
LARGER of (a) the vanilla occupant's size class — strict baseline, no
grace step: an XL-vanilla slot does NOT auto-qualify for XXL — and
(b) the geometry-derived capacity from `slot_terrain.json` `face_dist`
(metres to nearest collision face), mapped through median per-class
footprint radii (M 0.5 / L 0.84 / XL 1.4 / XXL 3.25 / GIGA 7.0 m). An
XXL/GIGA target is rejected ('geometry_clip') unless its size class is
within that capacity. XS..XL are not gated — they clear essentially any
navmesh slot. Slots with no terrain data fall back to the strict
vanilla baseline. The gate never rejects a target <= the vanilla
occupant's size, so it cannot drain a candidate pool.

Net effect vs the blunt gate: XXL/GIGA are now allowed wherever the
navmesh geometry proves the clearance (recovering legit big slots the
old gate discarded) and blocked everywhere it doesn't — including the
XL-vanilla slots Gate 7 let XXL through on unconditionally, and now
GIGA, which Gate 7 never touched.

New: `V3_GEOMETRY_GATE_ENABLED`, `V3_SIZE_RANK`,
`V3_SIZE_FOOTPRINT_RADIUS`, `V3_GEOMETRY_GATED_SIZES`; loader
`_load_slot_face_dist()` and helper `_geometry_capacity_rank()`.

### Validation

Per-size slot capacity (vanilla baseline + geometry recovery, 5,510
slots): XXL 748 (14%), GIGA 556 (10%), XL 2,062 (37%), L 3,048 (55%) —
big chrs keep ample homes; the v0.27.3 reservation floors for XXL
minibosses are not slot-starved. `TestGate7XxlAtSmallSlot` rewritten
for the geometry gate, 8/8 pass.

### Pending

Stage 2 — convert the BIG_PROXIMITY and DENSITY_CAP post-passes to
placement-time gates with per-MSB running state; this also closes the
reservation-floor-demotion bug (the post-pass is what evicts reserved
big chrs).

## v0.27.3

Miniboss tier — reservation floor + cap normalization. Follows the
v0.27.2 98-seed audit, which found the tier healthy in pool size (76
eligible chrs) but badly top-heavy.

### The problem

A cap/floor survey of the miniboss tier: 32 of 76 capped, 44 uncapped,
and ZERO reservation floors. Result was a steep distribution — ~8
uncapped M-humanoid vanilla chrs (Perfumer, Leonine Misbegotten, Black
Knife Assassin, Depraved Perfumer, Grave Warden Duelist, Azula Beastman,
Omen, Banished Knight) landed 11-15x per seed each, a mid-band sat ~7x,
and a ~30-chr tail sat below 1x/seed with nothing to rescue it. The
"miniboss tier feels small" complaint was a distribution problem, not a
pool-size one.

### The change

In load_data(), after the exclude sets and prior cap blocks are
finalized: every eligible miniboss-tier chr (tier='miniboss', not
excluded) gets `V3_RESERVATION_FLOORS` = 1, and every previously-
uncapped miniboss gets `V3_UNIQUE_TARGET_CAPS` = 6. Existing caps are
left alone — the hand-tuned 1/2 on singular bosses + archetype giants
and the 6/8 values are preserved; only the 44 uncapped chrs get cap=6.
Implemented as a computed loop (idempotent — re-running load_data is a
no-op) rather than 120 dict literals, matching the v0.24.65 auto-cap
pattern. Floor=1 added to 76 chrs, cap=6 added to 44.

Slot budget checked first: ~360 boss-strength slots per seed (357 with a
boss-strength vanilla source, 361 catalogued) vs 100 floored chrs total
(24 pre-existing night_boss/nightlord + 76 miniboss) — ~3.6x headroom.
Capping the top-8 also frees ~60 slots, so the change nets more variety,
not a slot crunch.

### Validation

12-seed run (seeds 400001-400012): the formerly-uncapped top-8 now sit
at 5.75-6.00 mean (cap binding); Aged Albinauric went 0.00 -> 6.00 in
every seed (floor working). Of the 76 floored minibosses, 16 still miss
at least one seed and 14 of those are XL+/XXL/GIGA — see caveat.

### Caveat — XL+ floors and the demotion bug

26 of the 76 floored minibosses are XL+/XXL/GIGA and exposed to the
reservation-floor-demotion bug (docs/OPEN_ISSUES.md): the BIG_PROXIMITY
/ DENSITY post-passes evict reserved big chrs. Their floors do NOT
reliably hold yet — the 12-seed check shows 14 of them still missing
seeds. The floor is fully effective for the ~50 S/M/L minibosses
immediately. Fixing the demotion bug is the natural follow-up to make
the tier-wide floor land for the big chrs too; v0.27.3 substantially
raises that bug's priority since it now governs 76 floors, not ~10.

### Notes

- Engine fingerprint bumped to v0.27.3.
- Survey + slot-budget detail: dev/SESSION_NOTES_2026-05-26.md.

## v0.27.2

98-seed placement-budget audit and four pool-gap / mis-tag fixes. Run
against the full set of decompressed vanilla MSBs with the production
config (multiplayer_safe=False, MMV pack loaded, prefer-canonical OFF).

### The audit

98 seeds simulated through the real `cmd_shuffle_v3` (seeds
200001-200098). ~3,708 swaps/seed, very stable. Two clean results and
two problem classes:

- Unique caps: zero violations. No `V3_UNIQUE_TARGET_CAPS` ceiling was
  exceeded in any seed. The reservation pre-bump + exhaustion gate hold.
- Global cap (`V3_TARGET_PLACEMENT_CAP=50`): soft, behaving as designed.
  58 grunt/trash c-prefixes brushed 51-54 in their hottest seed (the
  `if capped_pool` fallback firing when every under-cap candidate is
  exhausted). Means sit 45-49. Not changed.
- Reservation floors missed (DEFERRED — see docs/OPEN_ISSUES.md): 10
  floor=1 chrs come back below floor in a chunk of seeds despite the
  pre-pass reserving a slot — Smelter Demon 50%, Dancer 40%, the four
  MMV night bosses 15-23%. Likely the BIG_PROXIMITY / DENSITY_CAP
  post-passes demoting the reserved chr out of its slot. Not fixed this
  revision; logged as an open issue with the measured rates.
- Pool gaps / mis-tags: fixed below.

### Fix 1 — MMV nightlord pool gap

c4720 Godfrey, c4721 Hoarah Loux, c4730 Starscourge Radahn, c5230
Scadutree Avatar, c8500 Manus placed 0x across all 98 seeds. Root cause:
they are tagged `expects_boss_arena=true` in mmv_imports.json, so
load_data folds them into `V3_ARENA_ONLY_TARGETS`; v0.27.1's whole-MSB
night-boss arena preservation then left them with zero eligible slots.
New `V3_ARENA_ONLY_FORCE_LIFT` set, subtracted from
`V3_ARENA_ONLY_TARGETS` at the end of the load_data auto-extend block
(mirrors the M-humanoid lift). The `expects_boss_arena` tag is left
intact (still feeds the +10 placement score); only the hard arena-lock
is lifted. Post-fix 12-seed check: Godfrey / Scadutree / Manus now place;
Hoarah Loux and Radahn are low-frequency and need the full sweep to
confirm rate.

### Fix 2 — Storm King + Ancestor Spirit re-enabled

c4670 Ancestor Spirit and c7910 Storm King (both `_source='nr_placed'`,
night_boss tier) also placed 0x — same mechanism, but their arena-lock
came through `V3_DEDICATED_ARENA_BOSS_CHRS`. Both lifted from that set
and given `cap=1` in `V3_UNIQUE_TARGET_CAPS` so they read as singular
encounters at night_boss-tier world slots. c7900 Nameless King — the
vanilla pair-partner of c7910 — was deliberately left in
`V3_DEDICATED_ARENA_BOSS_CHRS`; revisit if the pair should move together.

### Fix 3 — Aged Albinauric placeable again

c3670 Aged Albinauric placed 0x. Its only named/canonical variant
(36708100, 'Aged Albinauric (Scholar Remembrance)', sample_maps
['m10_00_00_00']) was in `V3_AVOID_VARIANT_NPC_IDS` from a v0.23.24
'team=26 cinematic' attribution; the other three c3670 ids are empty-name
placeholders culled upstream anyway. With the only named variant
avoid-listed, `pick_variant_for_tier` returned None every time and the
slot fell back to vanilla. 36708100 removed from the avoid-list. CAVEAT
noted inline: the roster entry carries think_param_id=0 — if playtest
shows the placed chr is AI-inert outside m10, the avoid-add was right
and the line should be restored. Post-fix: c3670 places ~7/seed, every
seed.

### Fix 4 — playable-character models excluded

c52309 Priestess (Duchess), c52312 Witch of the Wheel (Recluse), c52313
Executor are NR playable Nightfarer class models that post_dlc_dump
scraped into the target pool as tier='grunt' enemies. Added to
`V3_EXCLUDE_TARGET_PREFIXES`. (Alaric named Duchess + Executor; c52312
Recluse was excluded on the same grounds — same class family. Flag if
that read is wrong.)

### Notes

- Engine fingerprint bumped to v0.27.2.
- Full audit methodology and per-chr numbers: dev/SESSION_NOTES_2026-05-26.md.

## v0.26.15

Mount/rider pair tracking — cut 1 (detection foundation). Adds an
experimental dev-section toggle that detects mount/rider Part pairs and
logs them for playtest audit. No swap behaviour changes yet.

### Why staged

The mount/rider coordinated swap is the highest-fun feature remaining,
but it is CTD-sensitive and has a known hard blocker:

- All mount and rider c-prefixes (c3150/c3160/c3170/c3180/c4050/c4060/
  c4363) currently sit in V3_EXCLUDE_SOURCE_PREFIXES — their vanilla
  slots are deliberately NOT randomized, because doing so caused the
  v0.20.27 "mount-slot CTD class".
- The disabled v0.23.04 collapse pass (`_collapse_rider_mount_pairs`)
  was shelved at v0.24.101 because zeroing the combat mount's npc_param
  doesn't remove the *visual* mount welded to the rider Part's spawn
  cluster (seed 537123: Godskin Apostle visibly on the Cavalry horse).

Whether to fight or embrace that pre-attached visual mount is a design
call that needs playtest input. So the feature is staged: cut 1 is a
safe, fully-tested foundation; cut 2 is the actual coordinated swap.

### Cut 1 — what shipped

- New experimental toggle in the GUI diagnostic section, "Mount/rider
  pair detection". Default OFF. Threaded through cmd_shuffle_v3 →
  _cmd_shuffle_v3_impl → shuffle_msb_v3 (mirrors chaos_mode); also a
  `--mount-rider-swap` CLI flag.
- `V3_MOUNT_CLASS_POOL` — the c-prefixes pickable as a mount, derived
  as the mount half of every RIDER_MOUNT_PAIRS entry: c3160 Funeral
  Steed, c3180 Albinauric Wolf, c4060 Kaiden's Horse, c4363 Lordsworn's
  Horse. Deriving it from tier=='mount_component' was rejected — that
  tier also tags riders such as c4050 Kaiden, so it is not a clean
  "is a mount" signal.
- `V3_MOUNT_RIDER_PILOT_PAIRS = {('c4050','c4060')}` — Kaiden is the
  pilot; cut 2's swap will touch only this pair. Night's Cavalry and
  the Lordsworn night-boss instance are deliberately excluded.
- `_detect_mount_rider_slots()` — a read-only pre-pass that finds
  mount/rider Part pairs (c-prefixes in RIDER_MOUNT_PAIRS, within 2m of
  each other) and tags each with `pilot_active`. When the toggle is on,
  shuffle_msb_v3 runs it and appends a MOUNT_RIDER_DETECT event to the
  spoiler trace. It does not mutate MSB data or change any swap target.

Net effect with the toggle ON: identical randomization output to OFF,
plus a MOUNT_RIDER_DETECT audit entry per MSB that has a pair. This
lets the detection be playtest-validated before cut 2 wires the swap.

### Cut 2 — deferred

The coordinated swap: at a detected mount slot restrict the target to
V3_MOUNT_CLASS_POOL; at the paired rider slot restrict to an M
humanoid; conditionally lift the source-exclusion for the Kaiden pair
only. Needs playtest input on the visual-mount behaviour first.

### Notes

- Full test suite: 28 failures, identical to the clean-HEAD baseline —
  zero regressions; +10 new tests (tests/test_mount_rider_detect.py).

## v0.26.14

Slot-reposition mount/rider pair fix. `distribute_stacked_repositions.py`
gains a Pass 3 that re-collapses mount/rider pairs the distribution
passes had split apart; `data/slot_repositions.json` regenerated with
the one affected pair repaired.

### The bug

`distribute_stacked_repositions.py` de-stacks co-located reposition
targets (its motivating case was a humanoid spawn-stack freeze, seed
469032). It resolves every Part to its own offset with no mount/rider
awareness, so a mount and its rider — co-located in vanilla by design —
get split apart. The rider then renders standing beside the mount
instead of on it, and the engine's RIDER_MOUNT_PAIRS proximity collapse
(2.0m) no longer pairs them.

Confirmed case: `m60_42_38_10.msb`, c3170 Albinauric Archer (pi=10) +
c3180 Wolf (pi=14). Both sat at the identical vanilla position
`[-63.33, 233.79, -82.95]`; the distribution passes moved them to
targets ~4.0m apart.

### Fix

New Pass 3 in `distribute_stacked_repositions.py`:
`find_mount_rider_splits` scans every MSB's proposals for two entries
whose `src` c-prefixes form a RIDER_MOUNT_PAIRS entry and whose vanilla
`from_pos` are co-located (within 2.0m, the engine's pairing threshold)
but whose resolved `to_pos_center` ended up 2.0m or more apart. For each
such split, the rider is moved onto the mount's resolved position — the
mount drives ground placement, the rider sits on it. Pass 3 runs last,
so it also corrects pairs Pass 1 just distributed, and is idempotent (a
re-collapsed pair is skipped on a subsequent run).

`data/slot_repositions.json` was regenerated through the v3 tool — one
entry changed: the c3170 rider in m60_42_38_10 recollapsed onto its
c3180 mount. Pass 1 (in-list stacks) and Pass 2 (cross-collisions) found
nothing to change.

### Scope / limitation

Pass 3 handles the case where BOTH pair members have reposition
entries. A pair where only one member was repositioned — moving it away
from a stationary partner — is a separate vector, not addressed here;
noted in `docs/TODO.md`.

### Notes

- `RIDER_MOUNT_PAIRS` is mirrored locally in the dev tool to keep it
  import-light (no 14k-line engine import);
  `tests/test_distribute_stacked_repositions.py` asserts the mirror
  stays in sync with `oops_v3.RIDER_MOUNT_PAIRS`.
- Full test suite: 28 failures, identical to the clean-HEAD baseline —
  zero regressions; +6 new tests for Pass 3.

## v0.26.13

Cluster-awareness removal. No runtime behaviour change — the cluster
swap path was already dead code in every real run. Pure engine surface
reduction ahead of the planned mount/rider pair-tracking feature.

### Context

"Cluster awareness" let multi-Part encounters get coordinated swaps
(all members locked to one target c-prefix, or catalog shape-matched).
Four independent layers had already retired it:

- `cluster_aware` defaulted False.
- The GUI checkbox was removed from the UI at v0.19.27 — no way for a
  normal user to enable it.
- The force-on path (`V3_CLUSTER_LOCK_MAPS` autopopulate) was disabled
  at v0.20.70 (`AUTOPOPULATE_CLUSTER_LOCKS = False`) — the lock set was
  never populated.
- `_collapse_rider_mount_pairs`, the dedicated mount/rider mechanism,
  was itself disabled at v0.24.101.

So `effective_cluster_aware` was always False and `compute_part_clusters`
plus the entire cluster swap path never executed. The v0.20.70 note
already recorded that cluster-integrity protection became "largely
redundant" once paired-chr breakers moved into
`V3_EXCLUDE_TARGET_PREFIXES`. There is no mount/rider capability gap —
mount/rider pairs are handled by target-exclusion, independent of
clustering.

### Removed

- Six cluster-only functions (~353 lines): `compute_part_clusters`,
  `_compute_clusters_spatial_then_cprefix`, `pick_cluster_target_cp`,
  `build_vanilla_cluster_catalog`, `pick_replacement_cluster`,
  `pair_cluster_members`.
- The cluster setup block in `shuffle_msb_v3` (the
  `effective_cluster_aware` computation, `cluster_to_parts`,
  `cluster_target_cp` / `cluster_target_variant`, `cluster_member_swaps`,
  the `randomize_clusters` pre-pick loop) and the swap-loop cluster
  branch (the per-Part `if cid is not None:` path). Every Part now rolls
  independently — which is what already happened at runtime.
- `cluster_aware`, `cluster_threshold`, `randomize_clusters`,
  `cluster_shape`, `cluster_catalog` parameters from `shuffle_msb_v3`,
  `cmd_shuffle_v3`, and `_cmd_shuffle_v3_impl`.
- `V3_CLUSTER_LOCK_MAPS` and the dead `AUTOPOPULATE_CLUSTER_LOCKS` block.
- CLI flags `--randomize-clusters`, `--no-randomize-clusters`,
  `--cluster-shape`, `--cluster-aware`, `--no-clusters`.
- GUI `cluster_aware_var` and its config / engine-kwarg plumbing; the
  stale "cluster-shape preserving" text in the About-tab banner.
- `pick_cluster_target_cp` references in `test_runctx.py` and
  `test_pick_target.py` (one dead test method).

### Kept (deliberately — out of scope for this piece)

- `RIDER_MOUNT_PAIRS` (data dict) and `_collapse_rider_mount_pairs`
  (already-inert prototype). These belong to the mount/rider feature,
  not the general cluster system. `RIDER_MOUNT_PAIRS` is also needed by
  the pending slot-reposition-split fix (see `docs/TODO.md`).
- `n_clusters` is retained as a vestigial `0` in the `shuffle_msb_v3`
  return tuple, `V3_PIPELINE_METADATA`, and the spoiler `cluster_id`
  field — kept literal-`0`/`None` to avoid a return-arity / schema
  change across callers and tests for zero functional benefit.
- The `_cluster_only` tag on 7 chrs in `nr_enemy_tags.json` — no code
  reads it post-removal, but it remains as accurate metadata
  documenting a real standalone-placement fragility class (also
  referenced by `nr_missing_chr_files.json`).

### Verification

`ast.parse` clean on all modified files; engine imports. Full test
suite: 28 failures, byte-identical to the clean-HEAD baseline — all 28
pre-exist this work and are unrelated. Zero regressions.

## v0.26.12

BFER dead-code cleanup. No runtime behaviour change for vanilla NR or
MMV users; removes inert code, dead data, and a misleading GUI link.

### Context

The BFER (Boss for Elden Ring) integration was abandoned (see
`docs/OPEN_ISSUES.md`). The heavy removal — the `V3_BFER_*` gate
constants, the boss-tier gate, the OOPS_ALL_NB intercept — already
happened at v0.24.22 (Phase 7). The `bfer_imports.json` /
`bfer_imports_v2.json` manifests no longer exist. This pass clears the
residue.

### Removed

- `dev/audit_bfer_variants.py` and `dev/BFER_AUDIT.md` — the audit
  script (read a manifest that no longer exists) and its doc.
- GUI About-tab "Helpful links" entry for BFER — it advertised BFER as
  a pack that "adds 30+ bosses as placement targets," but with no
  manifest and no gates BFER contributes nothing to the pool. The link
  was misleading users into installing a no-op dependency.
- `V3_AVOID_VARIANT_NPC_IDS`: 19 of the original v0.23.17/v0.23.20
  scripted-variant IDs that were BFER-only — verified absent from
  vanilla NR's `NpcParam`, from `nr_enemy_roster.json`, and from
  `mmv_imports.json`, so they matched nothing once BFER was retired
  (13 Margit c2010 9xxx, c2110 Maliketh statue, c2180 Melina, c5051
  Midra statue, 3 Margit c2010 8xxx ghost-recall).
- `tests/test_helpful_links.py::test_install_links_bfer` and the BFER
  entry in `EXPECTED_LINKS`.
- Dead `bfer_imports*` rows from `data/README.md`'s asset-pack table.

### Kept (verified live — would have been a regression to remove)

- **8 avoid-IDs that are also shipped by `mmv_imports.json`**: c2110
  Maliketh (21109000/21109042), c2120 Malenia (21209000), c2031
  Rennala P2 (20310024/20310124), c4720 Godfrey/Hoarah Loux
  (47200070/47200100/47200134). MMV ports those bosses from vanilla ER
  using the same NpcParam IDs, so the entries still suppress 1hp
  scripted variants whenever MMV is loaded. Their comments were
  re-attributed from BFER to MMV.

### Comment / doc fixes

- `detect_asset_packs` docstring example switched from the stale
  `bfer_imports_v1` to a real pack. `audit_team26_variants.py` docstring
  dropped its "companion to audit_bfer_variants.py" references.
  `INSTALL.md` optional-packs mention de-BFER'd. Engine-side BFER
  removal-history comments (v0.24.22 markers, `engine/state.py` Phase 7
  note) left in place — they document why those paths are gone and
  guard against re-introduction.

## v0.26.11

Cathedra slot gate — keep no-intro-anim chrs out of the Guardian Golem
"Cathedral" slot.

### Gate 8: requires_intro_anim

The m38_00 Guardian Golem "Cathedra" slot (pi=51) breaks chrs that are
otherwise resilient everywhere else in the corpus — Death Knight (c5070)
is the confirmed case. Working hypothesis: the slot's EMEVD spawn setup
hard-requires the occupant to have an idle/entrance animation; chrs that
emerge or rise into the fight (Sanguine Noble, Magma Wyrm, Giant
Fingercreeper, dragons) play well there, chrs without an idle/entrance
anim fail. The anibnd-level root-cause confirmation is a documented
follow-up (see docs/TODO.md, dev/anibnd_tools/) — but the fix is sound
regardless: Death Knight is empirically confirmed-broken at that slot.

The gate is the mirror image of the v0.24.79 no-emerge system. Where
V3_NO_EMERGE_SLOTS rejects a chr class (emerge_from_ground) at slots that
can't host it, V3_INTRO_ANIM_REQUIRED_SLOTS rejects chrs that lack what
the slot requires.

- entrance_animations.json: new entrance-anim class `no_intro_anim`.
  First member c5070 Death Knight. Default-`unknown` chrs are unaffected.
- data/nr_intro_anim_required_slots.json: new slot-affordance file →
  V3_INTRO_ANIM_REQUIRED_SLOTS. One slot: m38_00 pi=51 (Cathedra).
- oops_v3.py: `_load_intro_anim_required_slots()` loader + Gate 8 in
  `_reject_target_for_slot` (so both the picker and the reservation
  scorer inherit it). Gate fires only for explicitly-classified
  `no_intro_anim` chrs at slots in the set — a negative gate, not a
  positive allowlist, so the slot still randomizes widely.
- Composes with the slot's existing V3_PROBLEM_SLOTS / EXTRA_ALLOWS
  gates (which address a different root cause — cathedral-interior
  geometry / body size, the v0.20.69 c4620 Astel freeze).
- tests/test_pick_target.py: TestIntroAnimRequiredGateV0_26_11, 10 tests.

Scoped to one slot by design — not an architectural pass. The slot list
and the `no_intro_anim` membership both grow by playtest evidence.

## v0.26.10

Optional getSoul rune-drop tooling. No runtime/engine change.

### Rune-drop floors — opt-in manual tool

Adds an optional, user-run tool for making rune drops consistent on
relocated enemies. The rando does NOT ship or patch a regulation.bin;
rune rewards on relocated chrs are intentionally left a little wacky
in the default experience.

- V3_GETSOUL_TIER_FLOORS in oops_v3.py: per-tier placement-weighted
  vanilla median getSoul (nightlord 4375, night_boss 3750, field_boss
  2500, miniboss 475, grunt 100), derived from NpcParam getSoul
  weighted by each chr's vanilla placement count.
- dev/emit_getsoul_overrides.py: emits data/npcparam_getsoul_overrides
  .csv, uplifting any NpcParam row below its tier floor. Tier-driven,
  so coverage can't miss a chr the way the old hand-curated table
  missed Maris' Jellyfish.
- data/npcparam_getsoul_overrides.csv ships in the bundle so a user
  who wants consistent rune drops can Smithbox-import it into their
  own regulation. Purely opt-in — the engine never reads it.

Runtime regulation-patching was scoped and declined: it would need a
WitchyBND/AES dependency that cuts against the mod's zero-setup
direction.

## v0.26.9

Critical fix: test-mode arena bosses were not being randomized.

### Stale slot catalog missed 4 Night Boss arenas

The randomizer swaps enemies by editing MSB part placements; a slot
is only swapped if it's in V3_BOSS_SLOT_CATALOG. data/nr_all_slots.json
(the slot catalog the engine loads) had drifted stale at 3932 slots,
built from an MSB snapshot that predated the boss parts in four Night
Boss arenas: m47_80 (Gaping Dragon, c7700), m47_90 (Centipede Demon,
c7710), m48_00 (Duke's Dear Freja, c7800), m48_10 (Smelter Demon,
c7820).

Effect: with test-mode arenas on by default (v0.26.7), those four
arenas overlaid the minimal lifecycle EMEVD but had no catalogued
boss slot — so the picker never swapped them and they spawned the
vanilla boss. The whole point of the v0.26.1 NB-placement work
(reservation floors, terrain arenas, size corrections) was bypassed
for these marquee fights.

Fix: regenerated data/nr_all_slots.json from dev/all_msb_slots.json
(the correct extract, 5510 slots) and added the four missing boss-
slot entries to data/nr_boss_slots.json with the standard nightboss/
strict classification and XXXX0800 entity IDs. All 19 test-mode
arenas now have catalogued boss slots and randomize correctly.

### Regression test

tests/test_test_mode_arenas_integration.py gains
test_all_test_mode_arenas_have_catalogued_boss_slot, which asserts
every one of the 19 arenas has at least one chr slot in
V3_BOSS_SLOT_CATALOG. Catches future slot-catalog drift at suite
time instead of in a playtest.

## v0.26.8

Run-mode combobox stickiness.

### Mode combobox no longer flips on accidental scroll

The run-mode selector (Standard / Oops! All / Oops! All NB /
Validation) is a readonly Combobox, which by default changes
selection on mouse-wheel scroll whenever the pointer is over it.
Scrolling the window with the pointer near the selector silently
switched runs into a destructive Oops! All mode (every slot replaced
with one enemy). Two guards added:

  1. Mouse-wheel events (MouseWheel on Windows/macOS, Button-4/5 on
     Linux) are eaten on the combobox — scrolling no longer changes
     the selection, but the window still scrolls.
  2. Switching INTO an Oops mode now prompts for confirmation. The
     dialog spells out that the mode replaces every (or every Night
     Boss) slot with one chosen enemy. Cancelling reverts to the last
     confirmed mode. Switching back to Standard / Validation is
     non-destructive and doesn't prompt.

Restored-settings startup is unaffected — _last_confirmed_mode is
initialized alongside run_mode_var so a saved Oops! All setting
doesn't trigger a spurious prompt when the UI applies it on launch.

## v0.26.7

GUI defaults + stale-text cleanup.

### Test-mode arenas ON by default

The test-mode arena overlay checkbox now defaults to ON. With the
v0.29-v8 generation, all 19 N1/N2 arenas run the same minimal boss-
spawn template (boss spawns, you kill it, night advances) — no
cinematic, no wake choreography, no per-Nightlord EMEVD quirks. This
is the recommended way to play the current build, so it's the
default rather than an opt-in diagnostic toggle.

### Tricephalos recommendation removed

The "pick Tricephalos (Gladius) until other arenas are validated"
banner is disabled (RECOMMENDED_EXPEDITION_ACTIVE = False). It
existed because, pre-test-mode-default, most Night Boss arenas could
CTD or hang on rando swaps. With test-mode arenas now ON by default,
all 19 arenas use the validated minimal template and the per-
Nightlord guidance no longer applies. The banner, post-run-summary
row, and help-overlay section all hide via the existing flag check.
Strings + plumbing kept in case a non-test-mode build needs the
guidance back.

### Stale UI text fixes

- Test-mode arena label/tooltip corrected from "20" to "19" arenas
  (the 20 count mistakenly included the shared common_func.emevd).
- Vanilla mapstudio help text rewritten. Since vanilla_msbs/ is now
  bundled with all 23 spawn-pool MSBs included, rotation-pool bosses
  (Bell-Bearing Hunter, Tree Sentinels, Death Rite Bird, etc.) are
  randomized automatically with no path needed. The field is now
  only relevant when a user points the input folder at their own NR
  install that's missing the spawn-pool maps.

## v0.26.6

Merge of today's emevd work + the cp KeyError fix.

### cp KeyError fix in model compaction

The v0.26.x terrain-arena merge injects ~147 catalog entries from
nr_terrain_arena_slots.json that have no 'cp' key (they're promoted
by geometry, not chr identity). The model-compaction protect-set
builder in emevd_patch did `entry['cp']` unguarded, raising
KeyError: 'cp' on the first affected MSB. Now guards with
`'cp' in entry`. The _load_boss_slot_catalog docstring is updated
to document the two entry shapes (catalog-native vs terrain-merged).

### Test-mode arenas regenerated to v0.29-v8

dev/test_mode_arenas/ replaced with the v0.29-v8 engine-synced
generation (v5.3 engine-synced spawn 90015442+90015002, v5.6 day-
advance fix). 19 arenas, ships a shared common_func.emevd, marked
rando_compatible. Five integration tests in
test_test_mode_arenas_integration.py are xfail-marked because they
were written against the previous authored-option-A-v1 generation
(hardcoded 19-file count, version=='v0.26.1', per-arena event_ids
in the inventory manifest). The v8 generation uses a different
inventory schema and calls 90015442/90065911 as common-func
invocations rather than inline events. The tests need rewriting to
scan the binaries directly; xfail keeps the suite honest until then.

### prune_redundant_chrs dev tool

dev/prune_redundant_chrs.py added — removes chr/script overlays
that duplicate vanilla NR, preventing the partial-overlay null-deref
CTD class (e.g. the c4161 Stray missing-logic.luabnd case). Lives in
dev/ as a standalone tool.

### vanilla_msbs bundled

300 vanilla NR MSBs bundled at the repo root so users can install
and run without UXM-unpacking their own NR install first. The GUI's
default_input already points at repo-root vanilla_msbs/. Shipped via
the build's OPTIONAL_DIRS path.

### WONTFIX consolidated

The multi-entity arena test_mode spawn dead-end (m48_50/m48_60/
m48_80/m48_20/m49_25/m49_28 — multi-entity boss-spawn common_funcs
that resist the test-mode overlay) merged into dev/WONTFIX.md.

## v0.26.5

Windows console-window cleanup.

### Tk window raised to foreground at startup

main() now lifts the root, focus-forces it, and sets topmost True then
False on the next idle frame. Without this the launching terminal
(PowerShell, cmd, or the brief cmd flash from a double-clicked .bat)
stays in front of the newly-created Tk window — annoying, since the
user has to alt-tab to find the GUI. The set-topmost-then-clear pattern
is the standard Tk recipe: one-time raise without leaving the window
stuck always-on-top.

### CREATE_NO_WINDOW for the ME3 subprocess

The ME3 launch (oops_rando_gui.py line ~4884) was Popen-ing without
creationflags. On Windows that pops a separate console window for ME3
that flashes or stays in front. Now passes
subprocess.CREATE_NO_WINDOW on win32 (no-op on other platforms).

### Launch.bat and oops_rando_gui.pyw

Two launch options for users who don't want to type python at a
terminal:

- `Launch.bat` — double-click, runs `pythonw oops_rando_gui.py`.
  Brief cmd flash on launch (the .bat itself), then no console.
  Falls back to `python` if `pythonw` isn't on PATH.
- `oops_rando_gui.pyw` — Windows associates .pyw with pythonw by
  default, so double-clicking this opens the GUI with no console
  window at all (no flash). Re-imports oops_rando_gui.py so any
  code changes apply to both launch paths from a single source.

INSTALL.md updated with the three launch options (Launch.bat, pythonw
from PowerShell, and python for diagnostic output).

## v0.26.4

Hotfix: AttributeError on every Randomize click + stale help text.

### _hide_post_run_summary missing method

RandoGUI._run_shuffle called self._hide_post_run_summary() at the
start of each new run (to clear the previous run's summary panel
before the new one populates), but the method was never defined.
Symptom: every click on Randomize raised AttributeError before any
work started; the shuffle never began. Bug shipped silently because
the dev workflow (Linux, repeated test runs) didn't exercise the
Randomize button after the call site was added.

Fix: added the method. Body is what the call site expected — clear
all children of self._summary_frame_host. Safe-guarded against
missing attribute (older _build_main_tab path) and tk.TclError
(window torn down mid-clear).

### Regression test for the class of bug

tests/test_no_missing_methods.py AST-walks RandoGUI and
FirstLaunchWizard, collects every self.<method>() call with a
verb-y prefix (_show_/_hide_/_on_/_render_/etc), and asserts each
has a matching def in the class. Plus a named-after-the-bug test
for _hide_post_run_summary specifically. Future calls-without-defs
get caught at suite time, not at runtime on a user's first click.

### Stale help text corrections

"Tree Sentinels at castle" in three places (the visible Vanilla
mapstudio section help, the inline code comment, and the missing-
path skip dialog) pointed at the wrong example — Tree Sentinels
are field-boss rotation (m46_52/53), not castle rotation. Reworded
to "Bell-Bearing Hunter at Castle Basement, Tree Sentinels in the
field, ..." which matches the actual V3_SPAWN_POOL_MSBS contents.
Tightened "~24" to "23" since the dict has exactly that count
(m46_5x, m46_72/74, m46_8x, m46_9x — 17 field + 6 castle = 23).

## v0.26.3

Hotfix: Windows codepage decode errors when reading data files.

### encoding='utf-8' specified on all shipped text opens

Python's `open()` defaults to the platform locale encoding when no
explicit `encoding=` is passed — UTF-8 on Linux/macOS, but cp1252
(Windows-1252) on Windows. The v0.26.x size-correction annotations
added UTF-8 em-dashes (—) to `data/mmv_imports.json`, which cp1252
can't decode. Symptom on Windows: GUI shows
`(couldn't update mmv_imports.json: 'charmap' codec can't decode
byte 0x9d in position 220)` when toggling the MMV checkbox, and the
toggle state doesn't persist.

The same latent issue affected ~35 other text opens scattered
across `oops_v3.py`, `oops_rando_gui.py`, `oops_all_anyone.py`,
`dcx_batch.py`, `rewrite_walk_routes.py`, and `swap_compat.py`.
Anything that read `nr_enemy_tags.json`, the wizard's saved-paths
file, settings files, etc. would have hit the same error sooner or
later on Windows once any UTF-8 content sneaked in.

Audited and fixed via AST-walk across the shipped Python files:
every text-mode `open()` call now specifies `encoding='utf-8'`.
Binary opens (`'rb'`, `'wb'`) left alone — they don't take encoding.

### Regression test added

`tests/test_encoding_explicit.py` AST-walks every shipped Python
file and asserts no text-mode `open()` call is missing the
`encoding=` kwarg. Also includes a direct repro that confirms
cp1252 raises UnicodeDecodeError on the current `mmv_imports.json`
content, and a passing-case check that UTF-8 reads fine. Future
changes that drop `encoding=` get flagged immediately.

## v0.26.2

Hotfix: silent hang at first launch on fresh installs.

### First-launch wizard visibility fix

`oops_rando_gui.py::FirstLaunchWizard.__init__` was calling
`self.top.transient(parent)` unconditionally. The `main()` flow that
hosts the wizard withdraws the root before constructing the wizard
(to keep the half-built main window from peeking through). On
Windows + some Linux WMs, `transient(withdrawn_parent)` causes the
Toplevel to never map to the display — the window exists in Tk's
object graph and `wait_window` blocks on it, but no pixels render.
Symptom: GUI prints "[gui] engine ok, starting..." then hangs
silently; Ctrl+C doesn't break out on Windows because Python is
inside the Tcl/Tk event loop.

Fix: skip the `transient(parent)` binding when the parent isn't
viewable (`parent.winfo_viewable()` False). Modal behavior is
preserved via `grab_set()` regardless. Reproduced under Xvfb on
Linux during diagnosis, confirmed fix with virtual-display
screenshot of the welcome screen.

Diagnosis path documented in dev/TODO.md for future "the GUI hangs
on a fresh install" reports.

## v0.26.1

Reservation health + arena-pool widening release. Focused on making
marquee Night Boss-tier chrs (Midra, Romina, Maliketh, Fortissax,
Metyr, Dragonslayer Armor, etc.) appear reliably and at diverse
locations across seeds, while cleaning up architectural debt around
tag overrides and floor/ceiling semantics.

### Floor/ceiling cap split

New `V3_RESERVATION_FLOORS` constant (24 entries, all `=1`) drives the
reservation pre-pass. `V3_UNIQUE_TARGET_CAPS` is now strictly the
runtime ceiling. Policy: marquee NB roster gets `floor=1, ceiling=2`
(guarantee at least one, allow up to two per seed). Non-marquee chrs
get ceiling-only enforcement. c7910 Storm King excluded from floors
(paired-only with c7900 Nameless King). `_compute_unique_reservations`
now iterates FLOORS instead of CAPS.

### V3_TAG_OVERRIDES flattened and removed

The 45-entry tier-correction Python dict that compensated for
incorrect auto-tagging in `nr_enemy_tags.json` was a longstanding
source of dual-source-of-truth confusion. Flattened entirely:
33 entries moved into `data/nr_enemy_tags.json` directly with
`_tier_override_v0_26_x` annotation, 7 entries (heritage/MMV
runtime-loaded chrs) moved into `data/mmv_imports.json`, 5 no-op
entries dropped. `V3_TAG_OVERRIDES` constant deleted entirely from
`oops_v3.py` along with its load-time apply loop. Tier in the JSON
manifests is now the single source of truth.

### Tier demotions

Trolls (c4600/c4602/c4603) and 12 field-boss-promoted chrs (c3181
Red Wolf, c4241 Fingercreeper, c4500/4501/4502/4505 Flying Dragons,
c4630 Runebear, c4660 Guardian Golem, c4810/4811 Erdtree Avatars,
c5820 Great Red Bear, c7100 Ancient Hero of Zamor) demoted from
night_boss → miniboss. They had been promoted to NB-tier by the old
override system for engine-routing reasons but play as miniboss-tier
filler in vanilla NR. Existing caps retained as miniboss-tier
ceilings.

### NB-strict gate retirement (carried forward)

`V3_NIGHT_BOSS_STRICT_TARGETS` reduced to `set()` — the gate had
been keyed on the source slot's variant name string containing
"Night Boss", which is a string filter rather than a geometric one.
Real geometric concerns are handled by `V3_ARENA_ONLY_TARGETS`
(arena-room dependency) and `V3_FRAGILE_SENSITIVE_TARGETS` (rough/
narrow terrain). The retirement work shipped earlier; v0.26.1
confirms via simulation that all 24 floored NB chrs reserve at 0%
unplaced across 100 seeds.

### xxl_giga_size_drift M-lift

Asymmetric-compat fix: M-sized humanoid targets are now allowed at
XXL/GIGA-source slots. The gate retained S/XS rejection (grunt-scale
visual jar) but lifts M. Effect: Midra, Romina, Maliketh, and the
rest of the M-humanoid NB roster gain access to ~76 additional
qualifying slots per chr (XXL/GIGA source occupants whose vanilla
geometry has the capacity for an M target). Two seed-388677 unit
tests rewritten to match the new policy.

### Big-boy floor cleanup

Seven big chrs that had floors but felt field-tier or generic
(c3250 Draconic Tree Sentinel, c3251 Tree Sentinel, c4640 Ulcerated
Tree Spirit, c4650 Dragonkin Soldier, c4680 Fallingstar Beast,
c4770 Gargoyle, c4980 Death Bird) had their floor entries removed.
They compete freely with M-humanoid marquee NBs in the XXL/GIGA
pool now that M-lift is in place. They keep their cap=2 ceiling
from `V3_UNIQUE_TARGET_CAPS` (ceiling-only enforcement), but no
longer get a guaranteed reservation slot. `V3_RESERVATION_FLOORS`
shrank from 31 to 24 entries.

### MMV size_class bulk correction

Cross-referencing `data/NpcParam.csv` median `hitHeight` / `hitRadius`
against tagged `size_class` surfaced systematic undersizing in
`data/mmv_imports.json`: 18 of 33 chrs with hit data were tagged
smaller than the NpcParam data warrants (95% one-directional bias,
vs NR-vanilla's 25% mismatch rate with mixed direction). Corrections
applied with per-entry `_size_correction_v0_26_x` annotation citing
the source hitbox dimensions. Notable: Romina M→XL (h=3.90, matching
Tree Sentinel), Maliketh M→XL (h=3.60, radius 2.50), Fortissax
XXL→GIGA (h=14.10, r=7.00), Radahn XL→GIGA (h=8.00), Manus L→XL,
Metyr XL→XXL (r=5.00 spider footprint), and 13 more.

### Terrain arena candidates

New `dev/audit_terrain_arena_candidates.py` reads per-slot navmesh
roughness from `data/slot_terrain.json` and identifies "big and flat"
arena candidates (slope < 10°, open area ≥ 200 m² at 10m radius,
navmesh edge ≥ 2m, face distance ≥ 1m, not shifting-earth, not
already off-mesh). 147 new arena slots surfaced and merged into
`V3_BOSS_SLOT_CATALOG` via `data/nr_terrain_arena_slots.json` —
each carrying `_source='terrain_audit_v0_26_x'` for traceability.
The catalog's arena=True count grew from 104 to 251. The picker's
existing slot-side arena gate (line ~11234) consumes the merged
catalog without needing a separate gate.

15 of the 147 new candidates are high-confidence (vanilla occupant
is L+ size — FromSoft already vetted the geometry for a big chr):
Giant Crab clearings on m60_44_38/m60_45_36/m60_45_39, Mad Pumpkin
Head plazas on m60_44_39/m35_90, Spirit Jellyfish flats on m34_00,
Giant Putrid Flesh / Miranda Blossom / Ancient Hero of Zamor at
various m34_00/m34_10 positions.

### Reservation health simulation tool

New `dev/sim_reservation_health.py` runs the unique-target
reservation pre-pass over N seeds against a vanilla MSB directory
and aggregates per-chr unplaced rate, shifting-earth lockup risk,
and reservation MSB diversity. Used throughout this release to
verify changes don't regress reservation success and to guide
the design of the floor system, M-lift, and terrain-arena work.

### Reservation iteration order randomized

`_compute_unique_reservations` now uses `rng.shuffle(capped_items)`
(pure random per seed) instead of size-sorted iteration. Previous
size-first ordering pushed narrow-pool M-humanoid chrs to the back
of the priority list, where they consistently lost slot contention
to wider-pool chrs scoring the same. Pure random gives every chr
equal expected first-pick probability across seeds.

### Architectural cleanup

- `V3_DEDICATED_ARENA_BOSS_CHRS` introduced as the explicit
  arena-resident set, replacing the old `_source='script_spawn'`
  keying that became stale after the source-tag audit reclassified
  12 chrs to `nr_placed`.
- 12 `_source` tags in `data/nr_enemy_tags.json` corrected from
  `script_spawn` to `nr_placed` after byte-level UTF-16-LE audit
  of vanilla MSB references confirmed they have actual vanilla
  placements. Each annotated with `_source_override_v0_26_x`.
- `dev/audit_source_tags.py` shipped as a reproducible audit tool
  (UTF-16-LE-aware MSB scanning).

## v0.25.0

First public release since v0.23.58. The engine fingerprint walked the gap
across the v0.24.x series (v0.24.21 through v0.24.111+) during active
development; individual patch notes lived in PATCH_NOTES.md and the
session-by-session SHIP_NOTES.md during that period and were not backfilled
into this changelog. This entry rolls up the headline themes that landed
across the arc. Anything called out below is anchored in code, data, or
docs in the shipped tree; minor patches and dead ends are omitted.

### Slot repositioning

`data/slot_repositions.json` + Step 1c in `dcx_batch.py` move parts off
off-navmesh positions onto the center of the nearest tight navmesh leaf
before the shuffle runs. Built by `dev/build_slot_repositions.py`, applied
by `dev/apply_slot_repositions.py`. Eliminates a class of "swapped chr
spawns inside terrain and never reaches the player" failures that were
visible as silent no-shows in earlier seeds.

### walk_route_rewrite disabled by default

The Step 2a/3 c-prefix rewrite in `walk_route_cXXXX` event names is now
opt-in (`WALK_ROUTE_REWRITE_ENABLED = False` in `dcx_batch.py`).
Suspected contributor to a Day-2 explore-CTD class; was never demonstrably
effective and was kept only on "no obvious downsides" grounds. Set the
flag to `True` to revive — the Step 2a/3 block guards on it cleanly and
falls through to Step 3/4 when disabled.

### NB caliber pool refinement

Field-boss-tier cuts and an MMV-supplant gate for c2200. The Night Boss
arena swap pool is now a tighter curation, less prone to "this is technically
a boss tag but it's a regular-field-encounter chr that doesn't carry
the arena fight" mismatches.

### EMEVD analysis tooling

Two chr-side classifiers landed during the v0.24.85–v0.24.86 audit:

  * `data/scripted_intro_chrs.json` — chrs whose AI gates on a scripted
    intro signal (NB fog-wall cinematic, SmallBase attach, NPC dialogue
    trigger). 4 entries; the behbnd template-hashing approach used for
    other classifiers did not replicate for this axis, so the list grows
    empirically. `_meta.methodology_findings` documents the negative
    result.
  * `data/wakeup_chrs.json` — chrs whose AI starts in a dormant pose
    (kneeling, sitting, curled, half-buried) and needs an external wake
    handshake. 5 entries. `_meta.empirical_audit_v0_24_86` records the
    103/103 coverage proof from the audit-closing methodology pass.

Both are loaded by `dev/validate_placements.py` (offline placement
validator emitting per-placement CLEAN/RELEASED/SUSPICIOUS/WOULD_REJECT)
alongside the Track C intro-anchored slot catalog.

The structured CTD-report flow ships as `dev/CTD_REPORT_TEMPLATE.md` +
`dev/ctd_lookup.py` (prefills sections 1, 3, 4, 5 from a (spoiler, msb,
pi) triple). `dev/find_derand_seed.py` maps target MSB → Shifting Earth
→ which Nightlord+pattern_id range to filter a derandomizer GUI to.

### permissive_boss_wake scope expansion

From 2 events to 8: `90015000/7/21/23/26/30/31/406`. The
`90015301` event was confirmed during the v0.24.86 wakeup audit to be
a player-aggression watcher rather than the cinematic encounter the
older docstring described — comment fixed in `emevd_patch.py`.

### Multiplayer-safe mode

GUI checkbox that excludes all 47 heritage chr prefixes from the
placement pool. Heritage chrs are chrbnd-bundled with the rando rather
than coming from vanilla, so a co-op partner without the mod installed
cannot resolve them at sync time. Toggling the checkbox restricts the
pool to chrs every NR install has on disk.

### chr_asset_resolver: NR file convention

`dev/chr_asset_resolver.py` previously used ER conventions
(`cXXXX_battle.luabnd.dcx`, sfx substring glob). NR's actual data uses
numeric IDs with leading zeros + 2-digit variant
(`435000_battle.luabnd.dcx`) and exact `sfxbnd_cXXXX.ffxbnd.dcx`
matching. Three rubric bugs eliminated; the AI severity split into
`AI_BATTLE` + `AI_LOGIC` with post-loop union resolution (either
sibling present downgrades the missing one to `NOT_NEEDED`); CLI
preflight summary now splits "probable CTD" from "probable freeze" so
the actionable set is visible. 34 tests in
`tests/test_chr_asset_resolver.py`, all pass.

### nb_wave_bypass

`data/nb_wave_bypass_flags.json` + an `emevd_patch.py` patch take
control of the NB-arena `$Event(XXXX2810)` wave/boss gate. The vanilla
gate `WaitFor(EventFlag(eventFlagId3))` is parameter-substituted and
not statically recoverable; the patch OR's in a new per-arena bypass
flag picked from the empirically-unused `XXX029X` private flag range.
Built by `dev/build_nb_wave_bypass_flags.py`.

### anim_class identity gating removed

In `swap_compat.py`, the `LOCOMOTION_MACRO` (anim_class →
ground/air) check plus the intra-anim_class locomotion-field match
within "skeleton-sensitive" classes (Wolf/Stray Δloco T-pose theory)
did not survive playtest. The T-pose cases turned out to be chr-asset
gaps. What remains is the empirically-grounded flier-vs-ground split
expressed via `is_flier(tag)`.

### c5840 Black Knight: misdiagnosis resolved

The "AI unreliable in field placements" attribution chain dating from
v0.23.72 was wrong. The MMV variant `58400000 "Black Knight CASTLE
(Unused)"` — deliberately non-functional in MMV — was leaking into the
placement pool sometimes; the rest of the c5840 variants work fine.
The `'Unused'` token was added to `V3_VARIANT_TRIGGER_MARKERS`,
eliminating the bad pick. c5840 lifted from `ai_broken`. Documented
in `data/mmv_imports.json` `_note`; pattern (variant-marker
filtering as a class of fix) generalizes.

### Audit tooling

`dev/audit_chr_assets_vs_roster.py` cross-checks the rando's tag
roster against the chr/script assets actually deployed in the me3 mod
folder; surfaces gaps where the rando might place a chr whose assets
are not installed. Complements `chr_asset_resolver.py` from the
shipping side.

`dev/check_patches_shipped.py` greps a patched-EMEVD bundle for the
expected fingerprint of each registered EMEVD patch and reports
per-patch coverage. Useful for verifying the build pipeline ran
`emevd_patch.py` before DSAS3 recompile and the output got copied
into the running event/ dir.

### disable_corpse_collision retired

Patch retired in v0.24.100 — the persistent-corpse-blocking-Sites-of-
Grace bug class it targeted was eliminated by an upstream NR patch.
See `docs/EMEVD_PATCHES.md`.

### Engine fingerprint

v0.25.0.

## v0.23.58

### Spawn-pool intercept fired before sentinel filter

v0.23.57's diagnostic spoiler answered the question. Every spawn-pool
MSB came back with `was_in_input=True`, `status='ok'`, and `n_swaps=0`.
The smoking gun was in the per-MSB `msb_results` dict: the spawn-pool
maps had `n_aerial_skip=1` (or 2) and `n_clusters=0`, while my own
test environment on what should have been the same MSBs had
`n_aerial_skip=0` and `n_clusters=1`. The shared-position sentinel
filter was silently catching pi=1 of every spawn-pool map, so the
OOPS_ALL_NB intercept never even ran on those slots.

### What was happening

NR's spawn-pool MSBs pack three Parts at world origin (0,0,0):

  pi=0  c1000          (placeholder, npc_param=10000000 in vanilla)
  pi=1  the actual boss chr (Tree Sentinel, BBH, Death Rite Bird, etc.)
  pi=2  AEG099_060     (asset, npc_param=0, eid=0)

The cluster builder filters on `npc != 0`, so in vanilla NR pi=0 and
pi=1 both qualify as cluster candidates and union-find at threshold
2.0 puts them in the same 2-Part cluster. The sentinel pre-pass then
excludes clustered Parts from its position count, leaving only pi=2
contributing to (0,0,0). Count of 1 is below the threshold of 3, no
sentinel triggers, the pre-cluster intercept gets to run on pi=1 and
the swap goes through.

In environments where pi=0's npc_param has been zeroed — FIA mod's
modified spawn-pool MSBs are the case I confirmed locally — pi=0
falls out of cluster candidacy. The cluster builder returns 0 clusters.
The sentinel pre-pass now counts all three Parts at (0,0,0): count
of 3, sentinel triggers, pi=1's position lookup hits sentinel_positions
at line 7026 and the slot gets aerial-skipped before the intercept
ever runs. Result: zero spawn-pool MSBs swap, regardless of what
target the user picked, regardless of MMV state, regardless of seed.

### Fix

The pre-cluster OOPS_ALL_NB intercept moves to BEFORE the eid==0 +
near-origin filter and the shared-position sentinel filter. The
catalog (V3_BOSS_SLOT_CATALOG) and pin set (V3_BOSS_TIER_PINNED_SLOTS)
are now authoritative for slot identification: if either says "this
is a boss slot," the intercept fires regardless of whether the slot's
position-cluster shape happens to look like a script-spawn marker.

The sentinel filter is still useful — it correctly catches script-spawn
placeholder patterns at non-catalogued slots. Hoisting just changes
the priority for catalogued slots, not the filter's existence.

### Regression check

End-to-end test with target=c6200 broad scope, MMV ON, 23 spawn-pool
MSBs in input including a synthetic m46_52 with pi=0 npc_param zeroed
to reproduce the FIA-modification case:

  m46_52 (FIA-modified): swaps=1   (was 0 in v0.23.57 — fix works)
  m46_53 (vanilla):       swaps=1
  m46_56 (vanilla):       swaps=1
  m46_69 (vanilla):       swaps=1

17/23 broad-eligible MSBs swap. Same count as v0.23.57 on pure-vanilla
input — the fix doesn't regress the vanilla path.

### Spawn-pool MSB inventory dumps

V3_DIAGNOSTIC_INVENTORY_MSBS now includes all 23 spawn-pool MSBs in
addition to the castle. Each dumps a MSB_PART_INVENTORY trace event
into the spoiler showing every Part's c-prefix, npc_param_id,
entity_id, and position. Cheap (~3 Parts × 23 maps = ~70 trace
entries) and high-signal: if a future user's spawn-pool MSBs have
been further modified (different npc_param values, extra Parts, etc.),
the inventory dump shows it explicitly.

### Engine fingerprint

v0.23.58.
## v0.23.57

### Diagnostic build — no behavior changes

Fingerprint bumps to v0.23.57. The engine and pipeline now write
comprehensive run-state to the spoiler header so we can debug runs where
MSBs that should produce swaps don't end up in the spoiler. No new
features, no behavior changes — just instrumentation. Hopefully one
diagnostic run is enough to localize whatever's keeping the spawn-pool
MSBs out of the v0.23.56 spoiler in your environment.

### What gets logged

The spoiler header gains a `pipeline_metadata` block populated cooperatively
by `dcx_batch.rando_pipeline` and `oops_v3.cmd_shuffle_v3`:

  in_dcx_dir              the GUI/CLI input dir (which decompress reads)
  out_dcx_dir             where compressed output lands
  spawn_pool_source_dir   what was passed as the Vanilla mapstudio path
                          (None if unset)
  pipeline                'dcx_batch.rando_pipeline' or absent for direct calls
  vanilla_dir             the staging dir where decompressed .msb files live
  input_msb_count         how many .msb files the per-MSB loop iterated
  input_msb_listing       sorted list of all those filenames
  spawn_pool_in_input     {pool_msb: bool} per V3_SPAWN_POOL_MSBS — True
                          means the file existed in vanilla_dir at shuffle time
  msb_results             {filename: result} for every file the loop touched.
                          Result is one of:
                          - 'hub_passthrough' (HUB_MAP, copied not shuffled)
                          - 'parse_fail' (shuffle_msb_v3 returned None)
                          - dict with n_swaps, n_models_added, n_skipped_compat,
                            n_clusters, n_aerial_skip
  spawn_pool_include      {n_added, n_already_present, n_missing,
                           added_msbs, missing_msbs} — auto-include results
  spawn_pool_results      {pool_msb: {was_in_input, status, n_swaps,
                           description}} — high-signal summary, one row per
                           V3_SPAWN_POOL_MSBS entry. status values:
                           - 'not_in_input': pool MSB wasn't in vanilla_dir
                             (auto-include didn't fire, or fired and the
                             file is missing from the source)
                           - 'not_processed': in input but no result
                             recorded (shouldn't happen — bug if seen)
                           - 'parse_fail': shuffle_msb_v3 couldn't parse it
                           - 'hub_passthrough': MSB was in V3_HUB_MAPS
                             (shouldn't happen for pool MSBs)
                           - 'ok': ran cleanly. n_swaps tells you whether
                             the intercept fired and produced a swap.

### Reading the diagnostic

For a target=c6200 broad-scope run with all 23 spawn-pool MSBs in input,
expect:
  spawn_pool_results: 23 entries
    17 with status='ok', n_swaps=1 (broad-eligible: m46_52..69, m46_72,
       m46_74)
    6  with status='ok', n_swaps=0 (extended-only: m46_86..95)

If you see status='not_in_input' on any, those weren't in your vanilla_dir
when shuffle ran — auto-include either didn't fire or didn't find the
source. Check spawn_pool_include for n_added/n_missing.

If you see status='ok' but n_swaps=0 across the broad-eligible ones,
the engine processed them but pre-cluster intercept didn't fire OR
fell through to vanilla. That points at pick_variant_for_tier returning
None or a slot-filter ahead of the intercept. The msb_results dict shows
n_clusters and n_aerial_skip per file, which narrows it further.

### Engine fingerprint

v0.23.57.
## v0.23.56

### Spawn-pool MSB auto-inclusion

User insight from previous session, after seeing a Draconic Tree Sentinel at
the castle rooftop in a c6200 Gael run despite the spoiler showing a Scarab
at every catalogued castle slot:

> "Vanilla spawns a bunch of bosses at origin and then pulls them into
> arenas based on EMEVD, right? Our randomization eliminates the need for
> that by randomizing at the msb level."

After analyzing the EMEVD dump, the architecture turned out to be slightly
different than I expected: rotation chrs (Tree Sentinels at castle rooftop,
BBH at Castle Basement, Death Rite Bird at Field Boss arenas, etc.) live in
~23 tiny ~4.7KB "spawn-pool" MSBs (`m46_5x_00_00`, `m46_8x_00_00`,
`m46_72/74`). Each contains exactly one boss-tier chr Part at world origin
(0,0,0). NR's engine-internal SmallBase attach system loads them as
overlays at runtime, teleporting the chr to per-expedition attach points
on the live world maps. EMEVD doesn't do the teleporting — it only queries
`SmallBaseAttached(attachPoint, poolId)` to detect bindings and gate
progression on death flags.

Every one of these spawn-pool MSBs is already in `data/nr_boss_slots.json`
tagged correctly (fieldboss, named_boss, castle_interior). The OOPS_ALL_NB
intercept fires correctly when they reach `shuffle_msb_v3`. The problem:
**most users' me3 profiles only contain the live world MSBs they want
randomized.** The spawn-pool maps ship from vanilla NR un-overridden, so
the rotation bosses always appear in their vanilla form regardless of what
the rando placed in the world maps.

This release fixes the deployment gap.

### How it works

New optional GUI field: "Vanilla mapstudio" (right under "Mod
map/mapstudio"). Point it at the vanilla NR map/mapstudio directory.
When set, before the shuffler runs, `dcx_batch.rando_pipeline` walks
`V3_SPAWN_POOL_MSBS` (the canonical list of 23 rotation-source maps),
finds any that aren't already in the user's input directory, decompresses
them from the vanilla source (or copies if already raw .msb), and stages
them in the work-vanilla dir alongside the user's input MSBs. The shuffler
treats them as normal inputs from there. Catalog hits, OOPS_ALL_NB
intercept, big-proximity exemptions, all work the same way they do for
any other catalogued boss slot.

Output: shuffled spawn-pool MSBs land in the user's output directory and
get auto-copied to me3 alongside the live world maps if a mod_map_dir is
also configured.

### V3_SPAWN_POOL_MSBS

23 maps in the canonical list:

  Field-Boss tier rotation (17):
    m46_52: c3250 Draconic Tree Sentinel
    m46_53: c3251 Tree Sentinel
    m46_54: c3252 Royal Carian Knight
    m46_55: c3460 Leonine Misbegotten
    m46_56: c3100 Bell Bearing Hunter
    m46_57: c4270 Elder Lion
    m46_58: c4500 Flying Dragon
    m46_59: c4021 Royal Revenant
    m46_63: c4640 Demi-Human Queen
    m46_64: c4670 Ancestor Spirit
    m46_65: c4690 Putrid Avatar
    m46_66: c4770 Onyx Lord
    m46_67: c4810 Ulcerated Tree Spirit
    m46_68: c4910 Magma Wyrm
    m46_69: c7100 Crucible Knight Ordovis
    m46_72: c5011
    m46_74: c4980 Death Rite Bird

  Castle-variant rotation (6, extended-scope):
    m46_86: c3460 Leonine Misbegotten (Castle-variant)
    m46_87: c3100 Bell Bearing Hunter (Castle Basement)
    m46_88: c4021 Royal Revenant (Castle-variant)
    m46_90: c4670 Ancestor Spirit (Castle-variant)
    m46_91: c4690 Putrid Avatar (Castle-variant)
    m46_95: c7100 Crucible Knight Ordovis (Castle-variant)

m48_20_00_00 was originally on the list (it has c7910 at world origin
matching the spawn-pool signature) but turned out to be a full Night Boss
arena with c3970, c4505, and c7900 also at real positions. It's not a
rotation source. Excluded from V3_SPAWN_POOL_MSBS with an explanatory
comment.

### What this does

End-to-end test, broad scope, target=c4500: 17 of 17 broad-eligible
spawn-pool maps fire the OOPS_ALL_NB intercept. Extended scope: 23 of
23 fire. Tree Sentinels become c4500 at all attach points. BBH at Castle
Basement (m46_87) becomes c4500 (or whatever target you pick). Death Rite
Bird (m46_74) becomes c4500. The "rotation surprise" is gone — the rando
is now authoritative for what shows up at every rotation slot.

### Spoiler header gains

  spawn_pool_msbs_total: 23

So you can verify the constant loaded correctly. Spawn-pool spoiler entries
also carry the standard `catalog_tier` / `catalog_scope` fields like any
other catalogued slot, plus `is_spawn_pool: true` (TODO — added in next
patch as needed for filtering).

### Backwards compatibility

`spawn_pool_source_dir` defaults to None. Users who don't set it run
exactly v0.23.55's behavior — spawn-pool maps stay vanilla. No
existing run is affected. Setting the field is opt-in.

### Long-term backlog (deferred)

Strategy C — full EMEVD patching to strip the rotation system entirely
so only MSB Part placements determine what's where. With DarkScript3
available for compilation, this is feasible in principle. Deferred
because Strategy B (this release) achieves the user's actual goal
(rotation chrs become rando-controlled) with less risk and less invasive
changes. Revisit if Strategy B yields chrs whose npc_param tunings are
visibly wrong (Godfrey acting like a Tree Sentinel HP-wise, etc.).

Engine fingerprint v0.23.56.
## v0.23.55

### c4720 Godfrey banned (CTD on Castle approach)

User probe (seed 961158, v0.23.54): target=c4720, scope=broad, MMV
enabled. Catalog fired correctly — 130 intercepts, 135 c4720
placements distributed across vanilla NR boss arenas.

Result: **CTD on Castle approach.** The castle MSB had 6 c4720
placements concentrated this seed (pi=21/23/24/59/60/70 across the
basement-to-rooftop elevation stack). Crash fires when the player
crosses the streaming boundary into m60_43_36_50.

Banned in `mmv_imports.blacklist_when_active.ctd_unidentified`. With
MMV enabled, c4720 is now in V3_EXCLUDE_TARGET_PREFIXES at load_data
time and won't appear as a swap target.

### Catalog system worked exactly as designed

This is the first negative result run with v0.23.54's catalog. The
spoiler made the diagnosis trivial:

- Engine fingerprint v0.23.54 confirmed in spoiler header
- `boss_slot_catalog_total: 340` confirmed catalog loaded
- 130 `OOPS_ALL_NB_INTERCEPT` events in diagnostic_trace, broken down
  by source (8 pin / 122 catalog) and tier (remembrance, fieldboss,
  nightboss, noklateo, ruins_boss, crater, fort_boss)
- `catalog_tier` field on every spoiler entry made "what placed at
  every Field Boss arena" a single-line filter
- 0 `oops_all_nb_target_unavailable` log entries — c4720 was a valid
  target with variants (Godfrey - First Elden Lord (Field Boss)
  (Tier 4), npc 47200080 confirmed)

CTD root cause is one of:
1. A specific c4720 placement geometry incompatibility (basement
   stair geometry at pi=70, etc.)
2. Multi-instance load — 6 simultaneous c4720 spawns in one MSB
   exceeding model-instance count or memory ceiling
3. c4720 + something else in the streaming cell triggering an asset
   graph clash

To disambiguate would require scope=strict probe (skips all named_boss
extended pins + the Field Boss catalog hits), reducing castle
placements to 0 since the castle MSB has no strict-scope catalog
entries. If c4720 still CTDs at empty-castle approach, chr is broken
at any placement; if it loads fine, the failure mode is per-slot or
per-instance-count.

Probe deferred — moving to next target. v0.23.55 catalog tools make
the strict-vs-broad disambiguation a one-line GUI scope toggle when
needed.

### Updated probe queue

Confirmed working (3):
  c2120 Malenia (full oops-all)
  c6220 Fire Demon (soft-confirm via field placements)
  c6200 Slave Knight Gael (boutique probe, 239 placements)

Confirmed broken (3):
  c8500 Manus (DS1, asset graph divergent)
  c8300 Dragonslayer Armor (DS3, NULL+0x24 access violation)
  c4720 Godfrey (ER, Castle approach CTD — concentration or per-slot)

Next probe queue (priority):
  c5840 Black Knight (DS3) — has Castle (Banished Knight Castle-Shield)
    catalog placements that'd be a clean test if Banished Knights are
    a fair surrogate
  c5930 Giant Skeleton (DS3)
  c1310 Outrider Knight (DS3)
  c4730 Starscourge Radahn (ER, XL)
  c4670 Ancestor Spirit (NR-DLC)
  c4721 Hoarah Loux (ER) — sibling chr to c4720 Godfrey, useful
    test of "is the Godfrey family broken or just c4720"
  c5230 Scadutree Avatar (SoTE)
  c5200 Metyr (SoTE)
  c5130 Messmer (SoTE)
  c5051 Midra (SoTE)
  c5030 Romina (SoTE)
  c5300 Rellana (SoTE)
  c2110 Maliketh (ER)

Engine fingerprint v0.23.55.
## v0.23.54

### Authoritative boss-slot catalog

User insight from previous session: "we have all the boss slots tagged
somewhere... I want the script to know where all the boss slots are.
everywhere a boss goes in vanilla."

This release builds that catalog. New file `data/nr_boss_slots.json`
contains every vanilla boss-tier slot in NR, keyed by (msb, pi), tagged
with tier and OOPS_ALL_NB scope:

```
{
  "_meta": { "total_slots": 340, "scope_counts": {"strict": 43,
             "broad": 188, "extended": 109}, ... },
  "m60_43_36_50.msb": [
    {"pi": 21, "cp": "c4340", "name": "Mad Pumpkin Head",
     "pos": [15.4, 116.8, 34.6], "tier": "named_boss", "scope": "extended"},
    {"pi": 23, "cp": "c4500", "name": "Flying Dragon (Field Boss)",
     "pos": [-13.8, 106.1, 44.0], "tier": "fieldboss", "scope": "broad"},
    ...
  ],
  "m60_44_36_00.msb": [
    {"pi": 16, "cp": "c3350", "name": "Crystalian (Remembrance)",
     "pos": [-113.1, 101.7, 101.0], "tier": "remembrance", "scope": "broad"},
    ...
  ],
  ...
}
```

Built from a direct binary parse of all 244 vanilla NR MSBs uploaded
in m13_00_00_00.zip. 5,382 chr Parts enumerated, 340 classified as
boss-tier and swap-eligible (after filtering V3_EXCLUDE_PREFIXES like
Nightlord arena chrs c75xx that are permanently source-protected).

Tier distribution:
  remembrance      100 (broad)
  named_boss        78 (extended) — BKA, Astel, Mad Pumpkin Head, Troll, etc.
  fieldboss         49 (broad)
  nightboss         43 (strict)
  noklateo          18 (broad)
  castle_interior   10 (extended)
  ruins_boss        12 (broad)
  encampment         7 (extended)
  crater             8 (broad)
  fort_suffix        4 (extended)
  boss_suffix        4 (extended)
  cathedral          3 (extended)
  mountaintop        3 (extended)
  fort_boss          1 (broad)
  enhanced_boss      1 (extended)

The catalog replaces the variant-name marker-substring check that was
the sole signal pre-v0.23.54. Three concrete improvements:

1. **'Mad Pumpkin Head' (m60_43_36_50 pi=21)** — vanilla variant has no
   tier marker, was missed by every scope. Now tagged `named_boss`,
   fires at scope=extended.
2. **'Troll' (m60_43_36_50 pi=70)** — Castle basement Troll has eid
   1036500820 (script-bound boss), no marker. Tagged `named_boss`.
3. **'Black Knife Assassin' (m60_43_36_50 pi=59)** — only got the
   manual pin in v0.23.49 because there was no other path. Now also
   in catalog as `named_boss`.

### Pre-cluster intercept rewrite

Pre-v0.23.54 the OOPS_ALL_NB intercept lived inside the per-Part loop's
`else: # Non-clustered` branch, meaning clustered slots silently
bypassed the pin/marker check. Cathedral pi=16 (Crystalian Remembrance,
clustered with adjacent Coffin/Generic Object Parts) and Castle
basement pi=59/70 (BKA + Troll, clustered together) never fired their
intercept in v0.23.53.

The intercept is now hoisted to fire BEFORE the cluster-or-not branch.
Resolution order:
  1. Effective NB target — kwarg, or OOPS_ALL_NB_TARGET_CP module global
  2. Effective scope — kwarg, or OOPS_ALL_NB_MARKER_SCOPE module global
  3. (msb, pi) is in V3_BOSS_TIER_PINNED_SLOTS, OR
     is_catalogued_boss_slot(msb, pi, scope) returns True
  4. If matched: pick variant, append to swap_plan, continue.

Verified: castle MSB with target=c4500/scope=extended now correctly
fires all 6 boss slots (pi=21, 23, 24, 59, 60, 70). Cathedral pi=16
(clustered) also fires. Pre-fix: only the 4 solo non-clustered slots
fired (and only if MMV target was loaded — see next section).

### KeyError safety in pick_variant_for_tier

User reported v0.23.53 spoiler emitted target_cp=c4720 but no Godfrey
placements. Root cause: `pick_variant_for_tier` did raw-key access
`prefix_variants[target_cp]`, raising KeyError mid-MSB if the requested
target wasn't loaded (typically: MMV-only target with MMV disabled).
The exception was swallowed by the GUI worker's outer try/except,
leaving the spoiler half-written and confusing.

Fix: `prefix_variants.get(target_cp)` with explicit None-fallback.
Caller's existing None-handling path now correctly logs the slot via
`_log_unaccounted('oops_all_nb_target_unavailable', ...)` and falls
through to standard cluster/solo handling instead of crashing.

Verified: target=c4720 with MMV off no longer crashes; the 6 boss
slots in castle MSB are logged as `oops_all_nb_target_unavailable`
in the unaccounted-vanilla log, slot processing continues normally.

### Big-proximity demotion exempts pinned/catalogued slots

Discovered while validating the cluster-fix: castle pi=70 was firing
the intercept correctly (pre-cluster, swap_plan has pi=70 -> c4500)
but the v0.21 BIG_PROXIMITY post-pass was demoting it because pi=23
(Flying Dragon, also c4500/XXL) is within radius and pi=70 is the
higher-pi entry. Demotion silently rewrote pi=70's swap_plan entry
from c4500 to c3950 (Man-Serpent), negating the user's intent.

Fix: collect a `_exempt_pis` set at demotion-time of all swap_plan
entries whose target_cp matches OOPS_ALL_NB target AND whose (msb, pi)
is in pins or catalog. Skip those during demotion candidate selection.

The post-pass still works for organic random rolls (where multiple
random XL chrs land near each other). Only OOPS_ALL_NB intent is
exempted, which is the right semantic — when the user pins, they
mean it.

### Spoiler emits catalog tier per entry

Each spoiler entry now carries `catalog_tier` and `catalog_scope`
fields:

```
{
  "map": "m60_43_36_50.msb",
  "part_index": 23,
  "catalog_tier": "fieldboss",
  "catalog_scope": "broad",
  "original": {"c_prefix": "c4500", "name": "Flying Dragon (Field Boss)"},
  "new": {"c_prefix": "c4500", ...}
}
```

Mob slots have `catalog_tier: null`. This makes spoiler-based
diagnostics (like "what placed at every Field Boss slot this run")
trivial — filter by `catalog_tier in ('fieldboss', 'castle_boss',
'fort_boss', 'ruins_boss', 'remembrance', 'crater', 'noklateo')` for
broad-scope, etc.

The spoiler header also gains `boss_slot_catalog_total` (340) and
`boss_slot_catalog_meta` (the catalog's _meta dict). A 0 here means
catalog file missing/malformed and the engine fell back to marker-only
detection.

### Open issue (deferred)

In v0.23.53, user's spoiler reported `oops_all_nb_target_cp='c4720'`
but zero c4720 placements anywhere. With MMV off (user-confirmed), the
engine should have crashed mid-MSB via KeyError. Two possibilities:

1. The kwarg was None at engine layer despite spoiler header saying
   c4720 — possible state mismatch between dcx_batch and cmd_shuffle_v3
2. The kwarg DID reach but our walk through the elif chain missed
   something — but we traced this exhaustively and confirmed crashes
   on c4720 with MMV off

In v0.23.54, the KeyError is now safely None-returning, AND the
catalog-based intercept fires from a more deterministic path. If the
state mismatch is still present in v0.23.54, it'll show up as
`oops_all_nb_target_unavailable` log entries instead of a missing
intercept entirely. That makes it diagnosable from the next spoiler.

Engine fingerprint v0.23.54.
## v0.23.53

### Castle MSB audit — boss-tier slot inventory expansion

User uploaded the full vanilla NR MSB dump (244 raw .msb files, ~131MB).
This let me parse the castle-region MSBs directly without needing
Oodle/DCX decompression. 8 castle-region MSBs were audited:
m60_43_36_00/_10/_20/_50 (the "Castle" expedition variants) and
m60_44_36_00/_20/_30/_50 (cathedral / extended-castle area).

Across all 8 MSBs, 454 chr Parts were enumerated and segmented by
elevation. After filtering ambient mobs (Scarabs, Exile Soldiers,
Commoners, Stonediggers) and scenery placeholders (Coffins, Generic
Interactables, Condemned Invader Standins), 26 boss-tier
script-bound slots remain.

**The premium test arena**: m60_43_36_50 pi=23 at Y=106. Vanilla
hosts c4500 Flying Dragon (Field Boss) — a flat XL-class arena
on the castle rooftop. Single chr per run. Castle is one of the
most common POIs across expeditions, so pinning here means every
run with a castle has a guaranteed boss-import test target right
on the rooftop.

User's strategy: oops-all-NB sledgehammer rules out anything with
weird placement causing CTDs. By pinning premium slots, each
expedition's castle visit becomes a controlled test for one
import. Combined with existing v0.23.49 castle basement BKA pin,
the castle now has 4 pinned probe locations across the elevation
stack (basement-Y0, basement-Y0, upper-Y87, rooftop-Y106, top-Y117)
plus 3 cathedral remembrance pins at Y=102.

### V3_BOSS_TIER_PINNED_SLOTS additions (7 new pins, total 8)

```
('m60_43_36_50.msb', 21): top tower Mad Pumpkin Head (Y=117)
('m60_43_36_50.msb', 23): rooftop Flying Dragon arena (Y=106) ★ PREMIUM TEST SLOT
('m60_43_36_50.msb', 24): upper Astel-Naturalborn (Y=87)
('m60_43_36_50.msb', 70): basement Troll (Y=0)
('m60_44_36_00.msb', 16): cathedral Crystalian Remembrance (Y=102)
('m60_44_36_20.msb', 16): cathedral Crystalian Remembrance (Y=102)
('m60_44_36_50.msb', 16): cathedral Crystalian Remembrance (Y=102)
```

These pins fire in the OOPS_ALL_NB intercept logic — when running an
oops-all-NB campaign, any pinned slot is force-swapped to the target
chr regardless of the current variant's marker tier. Outside
OOPS_ALL_NB the pins have no effect; standard randomization continues.

### Castle layout variant analysis

**m60_43_36_00/_10/_20** (552KB each, identical content): "small
castle" layouts. NO Y >= 85 chr Parts. Only Exile Soldiers + Scarabs
at ground level (Y=64-67) plus Interactable Objects. These appear
to be approach/preview MSB tiles, not the boss-fight layout. The
rooftop/upper-castle chrs only exist in the _50 variant.

**m60_43_36_50** (1.8MB, "full castle"): the actual boss-fight tile
with all the elevation-stacked rotation slots. This is the MSB that
loads when an expedition hits the Castle POI.

**m60_44_36_00/_20/_50** (1.18MB each, identical content): cathedral
/ extended-castle area. Contains a Libra Nightlord arena (basement,
4 Libra Parts at pi=85-88) plus a Crystalian Remembrance at the
upper-cathedral floor (pi=16, Y=102). Identical Parts across all
three variants — the basement Nightlord arena is the same vanilla
layout regardless of which expedition picks this map.

**m60_44_36_30** (1.3MB): different layout, contains the Magma Wyrm
mine area's Stoneditters and ambient mobs. No castle-rooftop slots
(no Y>=85 boss-tier eid-bound Parts). This appears to be a
crystalline mine variant, not a castle proper.

### What's NOT pinned

The Libra Nightlord arena (m60_44_36_xx pi=85-88) is intentionally
NOT pinned. It's a Nightlord boss arena — already has its own
expedition-pool entry in nightlord_pools.json. Pinning it would
bias the campaign toward the Libra arena specifically when
OOPS_ALL_NB is on, which would skip players' normal expedition
flow. Standard randomization still hits these slots correctly.

### BBH at castle basement — clarification

User's report of "BBH at castle basement in this seed" was
investigated last release. Direct binary parse confirmed
m60_43_36_50.msb has NO c3100 (Bell Bearing Hunter) Parts. Only
13 chr models loaded: c1000, c2100, c4021, c4150, c4191, c4300,
c4315, c4340, c4355, c4500, c4600, c4620, c7000.

The BBH visual at basement is best explained by: **previous seed
(non-OOPS-ALL) where pi=59 random-swapped TO c3100**. That's the
same slot we pinned in v0.23.49. With the pin active, that slot
is now forced to OOPS_ALL_NB target — no BBH leak unless the
target chr is itself c3100.

The c3100 'Bell Bearing Hunter (Castle Basement)' variant in
roster (npc=31000030, sample_maps empty) was never observed
placed in any MSB Part during scrape. It may be EMEVD-spawned;
if so, it's outside MSB-Part swap reach.

Engine fingerprint v0.23.53.
## v0.23.52

### Diagnostic — MSB Part inventory trace for castle MSB

User's c6200 probe seed 257798 (v0.23.51 spoiler) confirmed:
- 239 Slave Knight Gael placements across all extended-scope buckets
- v0.23.49 castle basement BKA pin (m60_43_36_50 pi=59) firing as designed
- 0 blacklist leaks across 2900+ swaps
- Slave Knight Gael CONFIRMED WORKING (third positive MMV import after
  c2120 Malenia and c6220 Fire Demon).

User then reported: "the bell bearing hunter is in castle basement in
this seed. we can pin that slot too."

Investigation: searched the spoiler for any Bell Bearing Hunter
placements. Only one BBH slot in the run, at m49_24_00_00 pi=0 with
marker 'Bell Bearing Hunter (Night Boss)' — that's the Night 1
expedition arena, not the castle basement. Searched the m60_43_36_50
castle MSB content; NO c3100 (Bell Bearing Hunter) Parts present.
The slot at pi=59 is unambiguously c2100 (Black Knife Assassin) in
vanilla, and it swapped to c6200 correctly in this seed.

But the user is confident they saw BBH at the castle basement during
playtest. Two possibilities:

1. **Different MSB tile.** Castle is multi-tile in NR. The Day-2
   Castle complex spans m60_43_36_xx, with our local copy showing
   only tiles _00, _10, _20, _50. The DLC region may add additional
   castle subtiles (m60_43_36_60+) where BBH spawns at a basement-
   tier slot.

2. **EMEVD-driven spawn.** Some POI bosses in NR spawn via Event
   Script triggers rather than MSB Parts. The roster has variant
   c3100 npc=31000030 'Bell Bearing Hunter (Castle Basement)' with
   EMPTY sample_maps — meaning our scrape never saw it placed in any
   MSB. Combined with the castle MSB having no c3100 Parts at all,
   this strongly suggests an EMEVD spawn that bypasses the rando's
   MSB-Part swap path entirely.

Hypothesis 2 is most likely. Slot pinning won't help if the chr
isn't in any MSB Part — there's no slot to pin. EMEVD reach would
require reading SpawnEnemy event-script calls and substituting
npc_param refs there; that's a different release-arc (v0.24
territory; emevd_patch.py can be extended for it).

### Diagnostic added

Spoiler 257798 also showed a 16-pi gap in m60_43_36_50 (pi=43-58
all missing). These are usually placeholder Parts (npc=0) or
source-excluded preservations, but to confirm there's no hidden
c3100 in that range, this release adds a diagnostic trace.

New module-global `V3_DIAGNOSTIC_INVENTORY_MSBS` (set of MSB
filenames). When an MSB matches, the engine writes every Part —
including npc=0, source-excluded, and aerial-skipped Parts — to the
spoiler's `diagnostic_trace` under event name `MSB_PART_INVENTORY`.

Pre-populated with m60_43_36_50.msb. The next user run will produce
a spoiler with full Part listing for the castle. Empty pi gaps
become explicit (each will appear as `npc=0` placeholder), and any
hidden c3100 source-excluded Part will be visible.

When empty, the diagnostic has zero overhead. After investigation
concludes, the set can be cleared without removing the
infrastructure (so future "where is X in this MSB" questions have
the same primitive available).

Engine fingerprint v0.23.52.
## v0.23.51 (audit follow-up)

### No code changes — confirming architecture is complete

User asked v0.23.51: "we should have logic already for horse and rider
cluster swap, we developed it earlier and its confirmed working for
non-bosses". Audit confirms the user's intuition is right but there's
nothing left to wire — v0.23.50's surgical narrowing brought Tree
Sentinels into compatibility with the existing system without needing
any new cluster-swap mechanism.

The handling per encounter type:

- **Tree Sentinel arena (m48_50/m48_60)**: 6 NPCParam IDs preserved
  vanilla via V3_EXCLUDE_SOURCE_NPC_PARAMS (boss + 4 horses + named
  riders + spirit summons). Cluster grouping runs but is a no-op since
  all Parts are source-excluded.
- **Limveld Tree Sentinels**: self-contained-mount chrs, no separate
  horse Part to coordinate. Swap normally without cluster handling.
- **Albinauric+Wolf, Kaiden+Horse pairs**: handled by
  `_collapse_rider_mount_pairs` (rider rolls solo, mount suppressed).
- **Night's Cavalry**: full c-prefix source-exclude (dismount/remount
  phase logic too sensitive to disturb).
- **Royal Carian Knight**: never excluded, always swappable.

Full architecture diagram in `docs/MOUNTED_BOSS_ARCHITECTURE.md`.

The user's earlier suggestion to "swap the horse and rider to one boss
entity" maps directly to what `_collapse_rider_mount_pairs` already
does for Albinauric/Kaiden pairs. Tree Sentinels never needed that
mechanism because they're self-contained.

No engine fingerprint bump — this is documentation only, the v0.23.51
release packaging stays as-is.
## v0.23.51

### Hotfix — UnboundLocalError on msb_base in V3_BOSS_TIER_PINNED_SLOTS lookup

User v0.23.50 GUI run: `UnboundLocalError: cannot access local variable
'msb_base' where it is not associated with a value` at the new
`(msb_base, pi) in V3_BOSS_TIER_PINNED_SLOTS` check inside the
OOPS_ALL_NB intercept condition.

Root cause: `msb_base` was originally defined only inside the
`if terrain_test_targets:` branch of the per-Part loop (line ~6857
pre-fix). The v0.23.49 introduction of `V3_BOSS_TIER_PINNED_SLOTS`
into the OOPS_ALL_NB intercept condition referenced `msb_base` in a
sibling branch where it was never assigned. Worked fine in any test
where terrain_test_targets was set; broke immediately when
OOPS_ALL_NB ran without terrain testing (the normal case).

Fix: hoist `msb_base` computation to the top of the per-Part loop in
`shuffle_msb_v3`. The same value is now available in every branch.
Removed the redundant inner assignment in the terrain_test branch.

Engine fingerprint v0.23.51.
## v0.23.50

### Tree Sentinel Limveld variants now swappable as sources

User noted that the v0.19.13 fix for the Tree Sentinel Day-3 NB arenas
was overly broad: c-prefix-level source-exclusion on c3250 (Draconic
Tree Sentinel), c3251 (Tree Sentinel), and c4363 (Lordsworn Knight's
Horse) was preventing ALL of those chrs' Limveld overworld instances
from being shuffled out, when only the 4 Day-3 arena slots actually
need protection.

The user's observation: Tree Sentinel and Draconic Tree Sentinel ALSO
appear in Limveld overworld (m60_xx tiles) where there's no NB-arena
phase script, no shared-eid coordination, and no fixed mount-up
cinematic. They randomize fine there, just like Royal Carian Knight
(c3252 / Loretta), which never had the c-prefix-level exclude in the
first place.

### Surgical narrowing

Removed c3250, c3251, c4363 from `V3_EXCLUDE_SOURCE_PREFIXES`. Added
the 4 specific NB-arena NPCParam IDs to `V3_EXCLUDE_SOURCE_NPC_PARAMS`:

```
32500110  'Draconic Tree Sentinel (Night Boss)'         @ m48_50
32510110  'Tree Sentinel (Night Boss)'                  @ m48_60
43630010  "Lordsworn Knight's Horse (Night Boss)"       @ both
43630400  "Lordsworn Knight's Horse (Night Boss Spirit)" @ both
```

Sibling pattern to the v0.19.14 Leyndell Knight Night-Boss-Spirit
exclude (npc=43531400) and the v0.23.03 active-rider exclude
(npc=43531110) — both for the same Tree Sentinel arena.

### What this does for variety

Now swappable as sources (15+ Limveld/Field-Boss/Underground-Fort
variants):

```
c3250: 4 Limveld + 1 Field Boss = 5 slots restored
c3251: 6 Limveld + 1 Field Boss + 1 Underground Fort = 8 slots restored
c4363: 4 Limveld variants restored
```

Plus c3252 Royal Carian Knight (Loretta) was already swappable —
confirmed during this audit, no change needed.

### Day-3 NB arenas still protected

The 4 NPCParam IDs above stay vanilla. Plus cluster_aware in m48_50 /
m48_60 still coordinates the rider+4-horse cluster as a single unit.
The previous "ungodly noise" failure mode (rider swapped while horses
remain vanilla → infinite mount-up animation cycle) only triggers when
the rider+horses share a coordinated phase script, which only exists
at the NB arena tiles.

Engine fingerprint v0.23.50.

### Castle rooftop pin still pending

User mentioned that the castle rooftop slot rotates between Royal
Carian Knight (c3252), Ancestor Spirit (c4670), Ulcerated Tree Spirit
(c4500 Flying Dragon family in our roster), and Death Rite Bird
(c4980). None of those have variant names tagged with castle/rooftop
markers, so to pin the rooftop slot we need the (msb, pi) coordinates
from a spoiler where one of those chrs appears at the rooftop. v0.23.49
pinned the castle basement BKA slot using the same mechanism; the
rooftop pin is one playtest away from being addable.

## v0.23.49

### V3_BOSS_TIER_PINNED_SLOTS — per-slot OOPS_ALL_NB qualifier

User v0.23.48 c6200 probe spoiler showed castle basement Black Knife
Assassin slot at m60_43_36_50 pi=59 swapping to c3701 Perfumer (random
field-tier swap) instead of being forced to c6200 Slave Knight Gael by
the OOPS_ALL_NB intercept. Investigated:

The chr at that slot uses NPCParam 21000000, which has the bare variant
name `'Black Knife Assassin'` — no slot-tier marker like `(Castle)` or
`(Castle Basement)`. The roster does have `'Black Knife Assassin
(Castle)'` at NPCParam 21000030, but that's a different param ID assigned
to a different MSB Part. NR's data didn't tag this specific slot.

Marker-string expansion (v0.23.47/48 approach) wouldn't help here — the
issue isn't a missing string pattern, it's that the slot's variant-name
field carries no marker at all. Adding more substring matches risks
catching the same chr at non-boss-tier slots (every Black Knife Assassin
in the world becomes OOPS_ALL_NB-eligible, including the ambush ones in
Liurnia overworld).

### Solution

New `V3_BOSS_TIER_PINNED_SLOTS` set, sibling to `V3_PROBLEM_SLOTS`:

```python
V3_BOSS_TIER_PINNED_SLOTS = {
    ('m60_43_36_50.msb', 59): 'castle basement Black Knife Assassin (no marker in NR data)',
}
```

Wired into the OOPS_ALL_NB intercept condition. The condition now fires
when EITHER (a) the slot's `(msb, pi)` is in this pin set, OR (b) the
recipient_variant's mmv_name carries a scope marker. Pinning a slot
bypasses the marker check entirely for that slot.

### What user reported

- **Castle basement Black Knife Assassin** — added to pin set. Will be
  forced to OOPS_ALL_NB target on next run.
- **Castle rooftop Tree Sentinel** — couldn't localize the slot in
  spoiler. No Tree Sentinel placement in the m60_43_36_50 castle MSB
  this seed; possibly a different castle subtile (m60_43_36_60 or the
  chrs visible from the ramparts may live in a sibling MSB). Pin entry
  deferred until user can identify the (msb, pi).

To localize the rooftop slot: in a future seed, when the user spots a
chr at the castle rooftop, search the spoiler for that chr's c-prefix
in the `m60_43_36_xx` MSB tiles to find the (msb, pi) — then add to
the pin set.

### Future expansion

This is the right primitive for any "I see a chr at a real boss arena
but it's not getting OOPS_ALL_NB'd" report. The pattern:

1. User reports specific slot
2. Find (msb, pi) in spoiler
3. Add to V3_BOSS_TIER_PINNED_SLOTS with a description string
4. Ship hotfix

Engine fingerprint v0.23.49.
## v0.23.48

### Extend EXTENDED scope to bare (Fort) POI bosses

User noted that Guardian Golem (Fort) and Abductor Virgin (Fort) — and
the other bare-`(Fort)` POI variants — are common, geometrically-safe
arenas worth probing. The v0.23.47 extended set caught `Fort Boss` and
`Underground Fort` but missed the bare-paren `(Fort)` convention used
by 4 chrs: Guardian Golem, Abductor Virgin, Crystalian, Lordsworn
Captain.

Added `'(Fort)'` to V3_NIGHT_BOSS_EXTENDED_NAME_MARKERS. Coverage:
237 → 241 caught variant names.

Engine fingerprint v0.23.48.
## v0.23.47

### EXTENDED scope coverage widened — answers user's "is castle rooftop / basement covered?" question

User asked whether OOPS_ALL_NB scope='extended' covers Castle rooftop
and Castle Basement slots. Audit of the actual variant names in the
roster revealed the answer was "partially":

- "Castle Rooftop" doesn't exist as a literal substring anywhere — but
  the chrs that fight on the castle rooftop (Red Wolf of Radagon,
  Black Knife Assassin, Royal Revenant, etc.) appear with bare
  `(Castle)` markers, NOT `Castle-` hyphenated. The v0.23.38 extended
  set caught only the hyphenated form.
- "Castle Basement" exists exactly once as
  `'Bell Bearing Hunter (Castle Basement)'` — uses literal
  `Castle Basement` substring with a space. Was missed by both `Castle-`
  (no hyphen) and `Castle Boss` (different convention).

Same gap pattern existed for several other POI conventions: bare
`(Encampment)`, `(Cathedral)`, `(Mountaintop)`, `Underground Fort`
(both Eastern and Western), `Group Boss` (Blacksmith / Marsh / Ruins /
Great Church multi-chr encounters), and crucially `(Boss)` /
`(Boss Phase X)` — the bare-Boss suffix that names the actual
Nightlord forms (Caligo, Gladius, Adel, Libra, Fulghor, Maris,
Heolstor, Mountaintop Ice Dragon, etc.). 74 bossy variants in total
were not caught.

### Markers added to V3_NIGHT_BOSS_EXTENDED_NAME_MARKERS

11 new markers:

```
'(Castle)'           - bare-paren Castle interior + rooftop
'Castle Basement'    - the literal Bell Bearing Hunter slot
'(Encampment)'       - bare-paren Encampment POI
'(Cathedral)'        - Cathedral POI bosses
'(Mountaintop)'      - Mountaintop overworld bosses
'Underground Fort'   - Eastern + Western Underground Forts
'Group Boss'         - multi-Part POI encounters
'(Boss)'             - Nightlord forms with bare-Boss suffix
'(Boss Phase'        - phase-split Nightlords (Gnoster, Faurtis)
'Shrouded- Boss'     - shrouded Nightlord variants (Libra)
'(Enhanced Boss)'    - enhanced raid forms (Caligo)
```

### Coverage delta (against current 704-variant roster)

```
strict   ('Night Boss' only):   37 variants
broad    (8-marker set):       129 variants
extended OLD (v0.23.38):       171 variants
extended NEW (v0.23.47):       237 variants  [+66 over OLD]
```

Extended now also catches the all-important `(Boss)` markers, which
means OOPS_ALL_NB probes will finally hit the actual end-of-day
Nightlord arenas instead of bouncing off them. This fixes a real gap
for the c8500/c8300 probe results — those CTDs happened on Day 1 / 2
slots, but the Day 3 Nightlord arena was never being probed.

### GUI updates

- Inline help text on the Oops! All NB picker now describes the new
  extended scope coverage in plain English.
- Worker banner's `scope_descs` mapping updated similarly so users see
  the accurate description in the run log.

### What this means for active CTD-isolation work

The next probe target (c6200 Slave Knight Gael) will now have ~38%
more boss-tier slots forced to it under scope='extended', including
the Day-3 Nightlord arena. Higher signal-to-noise ratio, more chances
to reproduce a CTD if one exists, faster verdicts.

Engine fingerprint v0.23.47.
## v0.23.46

### Ban c8300 Dragonslayer Armor

User v0.23.45 boutique-probe seed targeting c8300 with scope='extended'
hit a textbook access violation almost immediately after Limveld load:

```
nightreign.exe - Application Error
The instruction at 0x00007FFDF9ACAA73 referenced memory at
0x0000000000000024. The memory could not be written.
```

The user reported seeing the DS3 Demon Prince loading-screen asset
flash before the crash, confirming Dragonslayer Armor was the chr
being loaded when the violation fired. Memory write to (NULL+0x24)
is the canonical "field offset on a null pointer" pattern — the
chr/anibnd/behbnd loaded but a downstream lookup against NR's
expected behavior/anim/chr-pointer table didn't find what it expected
and dereferenced a null.

Same failure mode as c8500 Manus (DS1 → NR jump too far). Two of two
DS3-era ports we've tested have CTD'd — DS3 ports as a class look
like the highest-risk cluster in MMV's import set.

`mmv_imports.blacklist_when_active.ctd_unidentified` now 10 entries:
c2240, c3110, c4540, c4541, c5650, c6230, c8200, c8300, c8400, c8500.
Total blacklist 17 (10 CTD + 7 DLC-asset-missing).

Engine fingerprint v0.23.46.
## v0.23.45

### MMV integration toggle in the GUI

User asked to wire the `mmv_imports.json _meta.enabled` flag into the GUI
since editing the JSON manually for every dev-build refresh is a friction
point. v0.23.45 adds a first-class checkbox.

### What changed

New checkbox in the **Heritage / Multiplayer-safety** tab, in its own
`MMV integration (optional)` LabelFrame below the existing Multiplayer-
safe toggle. Label: "Enable MMV cross-game boss imports". Tooltip
explains the requirement (MMV mod installed in me3 profile, OR MMV
assets copied into your active mod) and the consequence of enabling
without those assets (CTD on cell load).

The checkbox state IS the manifest state — no intermediate persistence
layer. On init, the checkbox reads `mmv_imports.json _meta.enabled` and
reflects whatever's there. On toggle, it writes the new value back to
the JSON, preserving all other manifest content (tags, variants,
blacklist_when_active, _meta description, etc.).

### Restart-required prompt

Toggling the checkbox at runtime updates the JSON immediately, so the
NEXT run of the engine sees the new state. But the GUI's c-prefix
picker dropdowns are built once at init from a `load_data()` call —
they won't surface (or hide) MMV chrs until restart. To avoid the
"why isn't c8300 in the picker after I enabled MMV" confusion, toggling
shows an info dialog explaining that the next run will use the new
setting and that the picker needs a GUI restart to update.

The dialog only fires when the new state actually differs from the
initial state — flipping twice and ending up where you started doesn't
trigger it. The initial-state snapshot updates after each fired dialog
so subsequent toggles compare against the most recent confirmed state.

### Why not refresh the picker live

Considered, rejected. The picker rebuild would require: re-running
`load_data()`, rebuilding `prefix_display`, re-populating
`oops_all_options` + `oops_all_lookup`, and calling `set_completion_list`
on three different combo widgets (oops_all_combo, oops_all_nb_combo,
force_include_combo). That's doable but expands the surface for bugs
significantly. A restart prompt is cheaper, clearer, and matches what
the user already does when they edit the JSON manually.

### Verification

Unit-tested the read/write helpers:
- Initial read returns the existing manifest state
- Write False → read False, Write True → read True
- All other manifest content (41 tags, 374 variants, 16-entry blacklist)
  preserved through write cycles

Engine fingerprint v0.23.45.
## v0.23.44

### GUI fixes — autocomplete focus + picker labels

Two related fixes after the user noted that "the lookup on the main tab
is a little annoying" during c8300 probe testing.

### 1. Autocomplete combobox doesn't lose focus on each keystroke

The v0.23.05 AutocompleteCombobox subclass posts the dropdown via
`ttk::combobox::Post` after each filtered keystroke, so the user gets
visual feedback that filtering is happening. But Tk's combobox post
moves keyboard focus to the dropdown listbox — so every subsequent
keystroke went into the listbox (which interpreted it as a typeahead
selection seek) rather than the entry field. User experience: type a
character, click back into the box, type the next character, repeat.

Fix: after posting the dropdown, capture the entry's current cursor
position and use `after_idle` to restore focus and re-anchor the
insertion cursor at the same position. The dropdown stays visible and
filterable but typing continues uninterrupted.

### 2. Picker labels now use authoritative tag names

c6200's picker label was showing "Scarab" instead of "Slave Knight
Gael" because the label-population code took the alphabetically-first
mmv_name across all variants of a c-prefix. For most c-prefixes this is
fine (single variant family) but for c-prefixes that aggregate
unrelated variants (cross-c-prefix naming collisions in the modded
NpcParam dump) it picks the wrong one.

Fix: prefer the tag's `name` field when available — these are
hand-curated for headline c-prefixes (DLC bosses, MMV imports). Fall
back to alphabetically-first variant name only when the tag has no
name or the name is a placeholder ('?', or starts with 'c' suggesting
auto-generated).

Verified labels for all MMV imports now show the proper boss name:

```
c2120  Malenia, Blade of Miquella
c8300  Dragonslayer Armor
c6200  Slave Knight Gael       (was 'Scarab')
c4720  Godfrey, First Elden Lord
c5130  Messmer the Impaler
c2110  Beast Clergyman / Maliketh
c8500  Manus, Father of the Abyss
c5230  Scadutree Avatar
c4730  Starscourge Radahn
```

### MMV picker visibility

Confirmed for the user: when `mmv_imports.json _meta.enabled=true`,
all 41 MMV c-prefixes appear in the picker (picker count goes from
349 → 386). When disabled, MMV c-prefixes are hidden — the user
without MMV doesn't see chrs they can't actually use. This is the
correct behavior for both states.

Engine fingerprint v0.23.44.
## v0.23.43

### Quality-of-life — Multiplayer-safe toggle now persists across launches

User v0.23.42 c8300 probe ran without multiplayer-safe re-enabled,
because the checkbox was always defaulting to True at launch (the
`tk.BooleanVar(value=True)` literal) regardless of the user's last
session. Saving folder picks across launches but not the toggle states
that affect every run was an oversight.

Two changes:

1. `multiplayer_safe_var` reads from `saved_settings` on init, with
   `True` as the fallback default for first-time users. The same pattern
   used for `oops_all_nb_target` and `oops_all_nb_scope` since v0.23.39.

2. A `trace_add("write", ...)` hook auto-saves the setting whenever the
   checkbox is toggled, not just when Run is clicked. This way users who
   toggle the box and close the app without running still keep the
   change.

Both `multiplayer_safe` and the existing folder picks now persist via
`.4laric_settings.json`.

Engine fingerprint v0.23.43.
## v0.23.42

### Hotfix — NB values weren't reaching write_spoiler_logs scope

User v0.23.41 GUI run completed the full shuffle (293 files, 2670 swaps,
1488 model entries) and then crashed at the very last step with
`NameError: name '_eff_nb_target' is not defined`. The shuffle output
was already written to disk; the spoiler-write step at the end is what
failed, so the user could have copied the .msb.dcx files manually but
not via the normal flow.

Root cause: the v0.23.39 NB-feature plumbing introduced two locals
inside `_cmd_shuffle_v3_impl`:
- `_eff_nb_target` — kwarg-or-module-global resolution
- `_eff_nb_scope` — same for scope

These were correctly scoped for the mode_label inside `_impl`. But the
spoiler-emit code, originally written to read module globals
(`OOPS_ALL_NB_TARGET_CP`), was changed to read the new locals — except
that emit code lives inside `write_spoiler_logs`, a separate function
called BY `_impl`. The function call doesn't carry locals across; the
two `_eff_*` names didn't exist in `write_spoiler_logs`'s namespace,
so the spoiler write raised NameError on its first reference.

Fix: thread `oops_all_nb_target_cp` and `oops_all_nb_marker_scope`
explicitly as kwargs through the `write_spoiler_logs` call. Both
default to `None` so legacy callers (CLI scripts, tests) continue to
work unchanged. Spoiler emit reads from the kwargs directly, no more
phantom-local references.

Engine fingerprint v0.23.42. Validated with three smoke tests covering
the GUI path, legacy path (no kwargs), and strict-scope path.
## v0.23.41

### Release-readiness pass — MMV integration disabled by default + docs

Pre-Nexus audit revealed that `mmv_imports.json` was shipping with
`_meta.enabled=true`. A user who downloaded this without having MMV
installed would have the rando reference c-prefixes that don't exist in
their regulation, causing CTDs on cell load. Three fixes for safe public
release:

### 1. MMV manifest disabled by default

`mmv_imports.json _meta.enabled` flipped to `false`. Default state for
fresh installs:
- 0 MMV variants/tags loaded
- MMV blacklist not applied (vanilla NR + DLC content is the floor)
- Engine prints `mmv_imports: skipped (_meta.enabled=false)` at startup

Users with MMV installed: open `mmv_imports.json` in any text editor,
change `"enabled": false` to `"enabled": true`, save, run normally.

The `_meta.description` and new `_meta.enable_instructions` fields in
the manifest tell users exactly when to enable and when to leave alone.

### 2. Documentation

- New `docs/MMV_INTEGRATION.md` with the full picture: what the
  integration does, how to enable, what's in the blacklist, the
  ranked CTD-probe order for cross-game imports, and limitations.
- `README.md` gains a Compatibility section pointing to the MMV doc
  with clear "do not enable without MMV installed" warning.
- `docs/NEXUS_LISTING.txt` gains a Compatibility section near the
  end, with the same warning, formatted in BBCode for the Nexus
  description block.

### 3. Worker startup banner

The GUI worker now logs a clear MMV state line near the top of every
run output:
- `MMV integration: ON — cross-game bosses in pool ...` when enabled
- `MMV integration: OFF — vanilla NR + DLC content only ...` when disabled

Mirrors the existing `Multiplayer-safe: ON/OFF` banner. Users can see
at a glance whether their MMV setting is what they expect, no more
hunting through engine startup output for the `mmv_imports: skipped`
line.

### Audit summary (all checks green)

- 4 cross-mod-dependent manifests disabled: `mmv_imports`,
  `bfer_imports`, `bfer_imports_v2`, `er_heritage_imports`.
- 2 self-contained manifests stay enabled: `heritage_pack`,
  `vanilla_promotions_v1`. Both reference only NR-internal content.
- All probe-mode module globals confirmed disabled defaults
  (`OOPS_ALL_NB_TARGET_CP=None`, `OOPS_ALL_NB_MARKER_SCOPE='broad'`,
  `BFER_UNRESTRICTED_TEST_MODE=False`, `OOPS_ALL_NB_FROM_BFER_POOL=False`).
- Default-state engine load: 3018 variants, 349 c-prefixes, 100% swap
  success at boss tier in 500-trial simulation.
- Documentation present and references MMV in all three places (README,
  MMV_INTEGRATION.md, Nexus listing).

Engine fingerprint v0.23.41.
## v0.23.40

### Hotfix — thread NB kwargs through dcx_batch.rando_pipeline

User v0.23.39 GUI run hit `TypeError: rando_pipeline() got an unexpected
keyword argument 'oops_all_nb_target_cp'`. The v0.23.39 plumbing wired
the new kwargs through the engine entry chain (cmd_shuffle_v3 →
_cmd_shuffle_v3_impl → shuffle_msb_v3) but missed the alternate path
the GUI takes when input is `.msb.dcx` (the common case): GUI →
`dcx_batch.rando_pipeline` → `cmd_shuffle_v3`. The pipeline function
didn't know about the new kwargs and rejected them at its own front
door before the engine ever saw them.

`rando_pipeline` signature extended with `oops_all_nb_target_cp` and
`oops_all_nb_marker_scope`, both forwarded to the inner
`oops_v3.cmd_shuffle_v3` call. Mode-label resolution updated to
include the NB scope when the feature is active.

Engine fingerprint bumped to v0.23.40 for diagnostic traceability.

## v0.23.39

### Two changes: ban Manus + promote OOPS_ALL_NB to a GUI feature

User's v0.23.38 boutique probe (`OOPS_ALL_NB_TARGET_CP = 'c8500'`,
scope=`'extended'`, every boss-tier slot forced to Manus) reproduced
a CTD almost immediately on Limveld load. Clean signal: c8500 (DS1
Manus) cannot be safely placed at any slot. Banning him brings the
MMV ctd_unidentified blacklist to 9 entries (16 total blocks
including the 7 DLC-asset-missing list).

Conclusion isn't surprising in hindsight — Manus is the only DS1
source in MMV's import set, and DS1's chr asset graph (skeleton
bone IDs, behavior state machine conventions, animation event
dispatcher patterns) diverges further from NR than ER/SoTE/DS3.
The other ER/SoTE/DS3 imports already have at least one confirmed
working chr each (Malenia, Slave Knight Gael presumably given that
seed 968523 ran cleanly), so the cross-game-import process itself
isn't broken — DS1 just happens to be too far.

### OOPS_ALL_NB promoted to first-class GUI feature

The probe pattern (force every boss-tier slot to one specific chr
under a chosen scope) is too useful to leave as a source-edit ritual.
v0.23.39 wires it into the run-mode dropdown:

- New mode: **`Oops! All NB (boss probe) …`** alongside Standard /
  Oops! All / Validation.
- When selected, two pickers appear:
  - **Target enemy** — same autocomplete combobox as the everything-
    mode oops-all picker, sharing the same c-prefix lookup table.
  - **Scope** — `strict` / `broad` / `extended` dropdown:
    - `strict` ≈ 22 NB anchor slots (Night Boss markers only)
    - `broad` ≈ 39 NB+Field+Castle Boss/Fort/Ruins/Crater/Noklateo/Remembrance
    - `extended` ≈ 51 (broad + Castle interior, Encampment towers,
      Evergaol, Mountaintop Ruins, Duo Night Boss)
- Picks persist across launches via the existing settings file
  (`oops_all_nb_target` + `oops_all_nb_scope`).
- Worker emits a clear diagnostic banner when NB mode fires:
  `*** OOPS! ALL NB: every boss-tier slot under <scope> forced to
  <target>. Field/grunt slots randomize normally; this is a surgical
  CTD-isolation mode for cross-game imports. ***`
- Spoiler emit gains an `oops_all_nb_marker_scope` field alongside
  the target.

### Engine plumbing

`oops_all_nb_target_cp` and `oops_all_nb_marker_scope` are now kwargs
through `cmd_shuffle_v3` → `_cmd_shuffle_v3_impl` → `shuffle_msb_v3`.
The intercept reads kwargs first, falling back to the module globals
`OOPS_ALL_NB_TARGET_CP` and `OOPS_ALL_NB_MARKER_SCOPE` for direct-CLI
or source-edit workflows. Module-global defaults reset to disabled
(target=None, scope='broad') so default behavior is exactly Standard
mode unless the user opts in.

`mode_label` includes target + scope when NB mode is active. Spoiler
header still emits both `oops_all_nb_target_cp` and the legacy
`oops_all_nb_use_strict_markers` bool alias for diagnostic continuity.

### Walking the rest of the MMV pool

Suggested order for the user's CTD-isolation tour, ranked by source-
asset-divergence-from-NR (highest CTD risk first):

1. ~~c8500 Manus~~ ← banned this release
2. c8300 Dragonslayer Armor (DS3)
3. c6200 Slave Knight Gael (DS3) — already worked once in seed
   968523, but worth confirming under boutique-probe load
4. c5840 Black Knight (DS3)
5. c5930 Giant Skeleton (DS3)
6. c1310 Outrider Knight (DS3)
7. c5930 Catacombs Sorcerer (DS3) — actually c5880, fix in next pass
8. c4730 Starscourge Radahn (ER, but very large skeleton)
9. c4511 Lichdragon Fortissax (ER, dragon class)
10. c5230 Scadutree Avatar (SoTE, custom skeleton)
11. c5200 Metyr (SoTE)
12. c5130 Messmer (SoTE)
13. c5051 Midra (SoTE)
14. c5030 Romina (SoTE)
15. c5300 Rellana (SoTE)
16. c4720 Godfrey (ER)
17. c4721 Hoarah Loux (ER)
18. c2110 Maliketh (ER)
19. ~~c2120 Malenia~~ ← already confirmed working

ER/SoTE imports last because they share the most skeleton/anim
conventions with NR (same engine generation, mostly humanoid).

## v0.23.38

### Boutique CTD probe — OOPS_ALL c8500 Manus, extended scope

User's v0.23.37 playtest CTD'd approaching the Day-2 Castle, but the
seed had 19 different MMV chrs placed across 72 boss-tier slots —
impossible to isolate which one is the culprit from a single run. This
release ships a controlled probe: every boss-tier slot in the run gets
forced to one specific MMV chr, so a Day-2 Castle CTD cleanly
implicates that chr.

### Scope expansion: 'strict' / 'broad' / 'extended'

The old `OOPS_ALL_NB_USE_STRICT_MARKERS` bool toggle (True = ~22
slots, False = ~39 slots) had no way to hit Castle interior /
Encampment / Evergaol POIs — exactly where the user's CTD reproduced.
Replaced with a tri-valued `OOPS_ALL_NB_MARKER_SCOPE`:

- `'strict'`  → Night Boss markers only (~22 slots: dedicated NB anchors)
- `'broad'`   → Night/Field/Castle Boss/Fort/Ruins/Crater/Noklateo/Remembrance (~39 slots, was the old default)
- `'extended'` → broad + Castle-/Encampment-/Evergaol/Mountaintop Ruins/Duo Night Boss (~51 slots)

`'extended'` adds substring matching for hyphenated POI markers like
`'Crucible Knight (Castle- Sword)'` (Day-2 Castle interior) and
`'Banished Knight (Encampment- Shield)'` (Encampment tower bosses) and
`'Bloodhound Knight (Evergaol)'` (Evergaol POIs).

Validated against seed 784451 spoiler:
- strict: 11 / 72 boss slots match
- broad: 39 / 72
- extended: 51 / 72

The 12-slot expansion to 'extended' is exactly the Castle/Encampment/
Evergaol surface the user wants under stress.

### Default settings shipped enabled

Bypass for the user's CTD-isolation workflow: this build defaults to
`OOPS_ALL_NB_TARGET_CP = 'c8500'` (Manus, Father of the Abyss — the
DS1 cross-game import, highest CTD-suspicion-per-slot ratio of any
MMV nightlord) and `OOPS_ALL_NB_MARKER_SCOPE = 'extended'`. Run a
seed; approach Day-2 Castle:

- If it CTDs at the same spot → c8500 confirmed broken under MMV's
  regulation. Blacklist via `mmv_imports.json` and bump fingerprint.
- If it doesn't CTD → c8500 exonerated. Edit `OOPS_ALL_NB_TARGET_CP`
  to the next nightlord candidate (suggested order: c2120 Malenia →
  c4720 Godfrey → c5230 Scadutree Avatar → c8300 Dragonslayer Armor →
  c5130 Messmer → c5051 Midra → c5200 Metyr → c4730 Starscourge
  Radahn → c4511 Fortissax → c5300 Rellana). Ranked by
  cross-game-asset-divergence likelihood (DS1/DS3 imports first,
  ER/SoTE imports last since those share more skeleton/anim conventions
  with NR).

### Backward compat

`OOPS_ALL_NB_USE_STRICT_MARKERS` retained as an alias
(`OOPS_ALL_NB_USE_STRICT_MARKERS = (OOPS_ALL_NB_MARKER_SCOPE == 'strict')`).
Spoiler emit gains an `oops_all_nb_marker_scope` field alongside the
old bool for diagnostic continuity.

### To disable the probe

Set `OOPS_ALL_NB_TARGET_CP = None` in `oops_v3.py` to return to
normal random swap behavior. The scope flag stays at `'extended'` but
becomes inert without a target.

## v0.23.37

### Hotfix — extend MMV blacklist to remaining Dreglord ad chrs

User v0.23.36 playtest surfaced two more missing-asset c-prefixes: c7651
(Large Dreg Corpse) and c7660 (Dreg Wormface). Both are part of the
Dreglord encounter family alongside c7610 (Straghess) and c7650 (Dreg
Corpse), already in the v0.23.36 blacklist. The full Dreglord ad set
now flagged.

`mmv_imports.blacklist_when_active.dlc_assets_missing_in_mmv` extended
from 5 → 7. Engine fingerprint v0.23.37. 1500-trial validation: 0 leaks.

## v0.23.36

### Hotfix — blacklist 13 c-prefixes broken under MMV regulation

User playtest of v0.23.35 reported CTDs. Two failure categories
identified, both fixed via manifest blacklist.

### Category 1: 8 unidentified MMV imports (CTD on placement)

The v0.23.35 release tagged 33 of MMV's 41 imports confidently from
the modded NpcParam dump and 8 unidentified ones with `_confidence:
'low'` and conservative tier defaults. User CTD'd; root cause was one
or more of those 8 entries getting picked at a swap target without
proper anim/skeleton/behavior alignment for the recipient slot.
Without per-chr asset inspection we can't isolate which specific one,
so all 8 go to the blacklist together:

c2240, c3110, c4540, c4541, c5650, c6230, c8200, c8400.

### Category 2: 5 NR-DLC c-prefixes whose chr/ assets MMV doesn't bundle

User ran MMV's source-availability check (`Source available at
.../ELDEN RING/Game/chr: 0 of 5 present`). The 5 missing entries are
NR Forsaken Hollows DLC content — they exist in the regulation
(MMV's regulation is post-DLC-based) but the chrbnd/anibnd/behbnd
bundles aren't shipped with MMV's mod payload. With MMV's regulation
active, references to these break:

c4801 Lord of Blood Spear, c7610 Traitorous Straghess, c7650 Dreg Corpse,
c7720 Knight Artorias, c7930 Demon from Below.

This is a side effect of "run MMV's regulation as-is" — when the user
later switches back to vanilla NR regulation (or merges DLC chr/
assets into their MMV setup), these would work again.

### Implementation

New `blacklist_when_active` field in `mmv_imports.json` with two named
arrays (`ctd_unidentified`, `dlc_assets_missing_in_mmv`) plus a
descriptive `_note`. The MMV load block in `load_data` reads both
arrays and adds their union to `V3_EXCLUDE_TARGET_PREFIXES`. Scoped
to `_meta.enabled=true` so disabling MMV also disables the blacklist.

Engine fingerprint bumped to `v0.23.36`. Load message expanded to
report blacklist size: `mmv_imports: 41 tags + 373 variants loaded;
caliber +19, strict-NB +19, blacklist +13 (8 CTD + 5 DLC-asset-missing)`.

### Verification

1500-trial swap simulation across three source profiles (c3010 Banished
Knight, c3360 Ancestral Follower, c2010 Margit) at boss-tier and
field-tier slots: **0 blacklist leaks**.

500-trial NB-tier roll on Banished Knight source: 95/500 hits land on
valid MMV imports (Scadutree Avatar 23, Manus 20, Messmer 16, Gael 15,
Godfrey 13, Malenia 8). Down from 244/500 at v0.23.35 because half the
MMV nightlord pool got blacklisted, but valid imports still surface at
~19% rate.

### When the blacklist becomes wrong

If the user pulls DLC chr/ assets into their MMV setup (or runs
vanilla NR regulation alongside MMV's added chrs through proper
regulation merge), the 5 DLC c-prefixes become functional. At that
point edit `mmv_imports.json` and clear the `dlc_assets_missing_in_mmv`
array. The 8 CTD-unidentified entries are still legitimately broken
until proper MMV regulation extract identifies them.
## v0.23.35

### MMV chr imports integrated — cross-game boss roster expansion

User confirmed Path 1 strategy: route swaps INTO MMV's already-imported
chrs rather than replicate the full FromSoft chr asset porting workflow
ourselves. MMV ("More Map Variations" by Team Daybreak, Nexus #578)
brings 41 new c-prefixes worth of cross-game bosses into NR — ER main
bosses, SoTE DLC bosses, several DS3 imports, plus DS1's Manus.

### What changed

User supplied the MMV mod payload (`material.zip` + chr/ directory
listing). Cross-referencing the chr/ asset bundles against vanilla
post-DLC NR identified 41 c-prefixes that don't exist in NR but DO
exist when MMV is loaded into the user's me3 profile. The Smithbox
NpcParam dump from v0.23.34 cycle had names for 33 of those 41
(81%); the other 8 were tagged with conservative defaults and
`_confidence: 'low'`.

#### New manifest: `mmv_imports.json`

Mirrors the bfer_imports.json / heritage_pack.json gated-extension
pattern. `_meta.enabled=true` by default (user has MMV installed).
Disabling is a one-line edit if MMV ever gets removed from the
profile.

41 c-prefixes hand-curated with tier / arena / anim_class /
size_class / origin_game:

**ER main bosses (Nightlord-tier, 8)**: c2030 Rennala, c2031 Rennala P2,
c2110 Beast Clergyman/Maliketh, c2120 Malenia, c4511 Fortissax,
c4720 Godfrey, c4721 Hoarah Loux, c4730 Starscourge Radahn.

**SoTE bosses (Nightlord-tier, 6)**: c5030 Romina, c5051 Midra, c5130
Messmer, c5200 Metyr, c5230 Scadutree Avatar, c5300 Rellana.

**DS3 boss imports (mixed-tier, 7)**: c5840 Black Knight, c5880 Catacombs
Sorcerer, c5930 Giant Skeleton, c6200 Slave Knight Gael (nightlord),
c6210 Corvian Knight, c6220 Fire Demon, c8300 Dragonslayer Armor
(nightlord).

**DS1 boss import**: c8500 Manus, Father of the Abyss (nightlord).

**Field/mid bosses (5)**: c1260 Hollow Manserving Servant (Saw),
c1310 Outrider Knight, c5000 Commander Gaius, c5060/c5061 Lamprey,
c6260 Death Rite Bird.

**Grunt/trash (4)**: c5651 Messmer Foot Soldier, c5740 Kindred of Rot
(MMV variant), c6201 Scarab, c6231 Perfumer.

**Mount component (1)**: c5890 Black Knight Horse — `tier='mount_component'`,
auto-excluded as standalone target.

**Unidentified (8)**: c2240, c3110, c4540, c4541, c5650, c6230, c8200,
c8400 — no names in the dump. Tagged conservatively with
`_confidence='low'`. Best guesses included in tag names ("likely
Hippopotamus", "likely Promised Consort Radahn") for future review.

#### Engine changes

- `V3_ENGINE_FINGERPRINT` bumped to `'v0.23.35'`
- New `mmv_imports.json` load block in `load_data` after the BFER v2
  block. Same shape as bfer_imports loading: tags merged into the
  active manifest, variants appended to roster (with NPC-param-id
  dedup against existing roster), `V3_NIGHT_BOSS_CALIBER_TARGETS` and
  `V3_NIGHT_BOSS_STRICT_TARGETS` extended for boss-tier entries.
- MMV imports are AUTHORITATIVE — they replace any pre-existing tag
  for those c-prefixes. Vanilla NR's content at the same numerical
  c-prefix is overridden by MMV's chr at runtime, so the manifest
  reflects what the player will actually encounter.
- Unlike BFER, MMV does NOT get added to V3_HERITAGE_ALL_PREFIXES.
  MMV chrs work fine in coop as long as all peers have MMV (the mod
  enforces a Roundtable check that blocks expedition starts when peers
  don't have the DLC + MMV). No need for our multiplayer_safe gate.

### Verification

500-trial swap simulation at a boss-tier source (c3010 Banished Knight,
"Night Boss" variant marker):

- **244 / 500 rolls hit MMV imports (49%)**, distributed across:
  - Godfrey 27, Fortissax 17, Rennala 17, Manus 16, Scadutree Avatar 16,
    Romina 15, Slave Knight Gael 15, Malenia 15, Dragonslayer Armor 15,
    Maliketh 14, Messmer 13, Hoarah Loux 13, Midra 13, Starscourge
    Radahn 12, Rellana 9.
- Caliber set extended from 87 → 102 (with overlap deduplication).
  19 MMV nightlords added directly; 29 more entries auto-extended via
  the v0.23.34 tier-based caliber-set logic.
- Strict-NB set extended from 25 → 44 (19 MMV nightlords).

Combined with v0.23.34's DLC integration, the rando's target pool now
includes everything in vanilla post-DLC NR plus MMV's cross-game
imports. A boss-tier source slot has roughly equal probability of
swapping to a vanilla NR Nightlord, a Forsaken Hollows DLC boss, or
an MMV-imported ER/SoTE/DS3 boss.

### Limitations / open follow-ups

- **8 unidentified MMV imports**: c2240, c3110, c4540, c4541, c5650,
  c6230, c8200, c8400. No names in the modded NpcParam dump. Tagged
  with low confidence. A more thorough dump pass (full MMV regulation
  unpack, not just whatever was in the user's me3 setup) would
  resolve these.
- **MSB awareness still missing**: same as v0.23.34. We can swap INTO
  MMV chrs at vanilla NR slots, but MMV's added MSB content (new map
  tiles, new field boss spawns under their normalized 22→87 / 35→54
  count claims) isn't represented in our placement dataset because we
  haven't pulled the MMV-modified MSBs.
- **MMV version pinned**: this integration is built against MMV 2.0.5.
  Future MMV updates could add more c-prefixes or change tier
  characteristics. Not a runtime issue — extra MMV chrs would just
  be unrecognized and skipped — but tag accuracy could drift.

## v0.23.34

### Post-DLC content integrated — Forsaken Hollows roster expansion

The Forsaken Hollows DLC released Dec 4 2025 with two new Nightlords
(Balancers / Dreglord), new Day-1/2 bosses, the Great Hollow Shifting
Earth tile, ten Roundtable NPCs for all Nightfarers including Scholar
and Undertaker, plus extensive variant additions to base-game c-prefixes.
The rando had no awareness of any of this content.

### What changed

User supplied a vanilla post-DLC regulation export (252 CSV param tables
via WitchyBND from a RelicFilter-modded reg) plus a Smithbox project
export with FMG-resolved chr names. Cross-referencing those two dumps
let us identify the new content by ID and label it.

#### Roster

- `nr_enemy_roster.json` extended from 963 variants → **3018 variants**
- 2055 new variant entries, every one tagged `_source: 'post_dlc_dump'`
  for traceability
- 1555 of those have proper names (e.g. `'Knight Artorias (Night Boss)'`,
  `'Caligo - Miasma of Night (Boss)'`, `'Dreg Wormface'`)
- 500 are unnamed (emerge-markers / cinematic-only / template variants)
  — kept in roster but won't surface as picks because they have no
  variant name for the engine to match
- `think_param_id` derived as `(npc_param_id // 10000) * 10000` per
  NR convention; `has_reward` derived from `rewardItemLot_1 > 0`

#### Tags

- `nr_enemy_tags.json` extended with **112 new c-prefixes**, all with
  `_source: 'post_dlc_dump'`. 184 existing c-prefixes gained DLC variants
  and got `_source_dlc: 'post_dlc_dump_added_variants'` markers.
- 66 c-prefixes hand-curated as DLC headline entries with explicit
  tier / arena / anim_class / size_class. Highlights:
  - **DLC Nightlords**: c4900/c4901 Caligo (Balancers), c4641 Harmonia
    (Everdark Worm). Plus the previously-placeholder-named c7560 Libra,
    c7580 Heolstor, c7600 Fulghor.
  - **DLC bosses**: c7720 Knight Artorias, c7930 Demon from Below,
    c4670 Ancestor Spirit, c4690 Grafted Scion, c4140 Spiritcaller Snail,
    c4504 Greyoll-class Dragon (was previously BFER-tagged).
  - **Dreglord encounter family**: c7610 Traitorous Straghess, c7650 Dreg
    Corpse, c7651 Large Dreg Corpse, c7660 Dreg Wormface.
  - **Nightfarer Roundtable NPCs**: c52101-c52110 (Wylder/Guardian/Ironeye/
    Duchess/Raider/Revenant/Recluse/Executor/**Scholar**/**Undertaker**),
    all `tier='cinematic'`.
  - **Revenant summons**: c13703 Helen, c14340 Frederick, c14961 Sebastian
    — also cinematic (player-summoned, not slot-placeable).
- The rest auto-classified by HP / reward / soul heuristics: HP > 5000 or
  soul > 5000 → night_boss; HP > 1500 + reward + soul > 1500 → field_boss;
  HP > 500 + reward → miniboss; etc.

#### Engine

- `V3_ENGINE_FINGERPRINT` bumped to `'v0.23.34'`
- `load_data` now auto-extends three sets at load time, all driven from
  the tag manifest:
  - `V3_EXCLUDE_TARGET_PREFIXES` += all `tier='cinematic'` c-prefixes
    (41 added: 25 system/template, 10 Roundtable NPCs, 3 Revenant summons,
    plus a handful of player-tier objects)
  - `V3_NIGHT_BOSS_CALIBER_TARGETS` += all `tier in {'night_boss',
    'nightlord'}` c-prefixes (29 added; total now 87)
  - `V3_NIGHT_BOSS_STRICT_TARGETS` += all `tier='nightlord'` c-prefixes
    (24 added; total now 25)
- All three globals declared at the top of `load_data` so existing
  manifest-driven inner-block updates and the new auto-extend block
  coexist cleanly.

### Why this matters for the rando

Before v0.23.34, post-DLC chrs simply didn't exist in the target pool.
A user playing on a Forsaken Hollows install would never see Artorias
swap into a slot, even though Artorias was sitting right there in the
regulation. The rando's data was stuck at pre-DLC.

The integration unblocks DLC-aware swaps without requiring access to
post-DLC MSBs. Map placements (which slot exists at which coordinate)
still come from the existing pre-DLC MSB scrape, but the **target pool**
the engine swaps INTO now includes everything in post-DLC NR.

### Verification

500-trial swap simulation at a boss-tier source (c3010 Banished Knight,
"Night Boss" variant marker):

- **75 / 500 rolls hit DLC headline content**:
  Greyoll Dragon (31), Knight Artorias (23), Demon from Below (21)
- Other DLC nightlord-tier c-prefixes (Caligo, Libra, Heolstor, Fulghor,
  Harmonia) require strict-set or anim_class compatibility that c3010
  doesn't trigger — they'll surface at slots seeded with matching
  source c-prefixes (Maliketh-tier, Margit-tier sources)

500-trial swap simulation at a field-boss source: 2 / 500 DLC hits
(Dreg Corpse). Field-tier slots correctly avoid night_boss-tier targets.

600-trial grunt-tier roll: **0 cinematic-tier leaks**. Auto-exclude is
correctly preventing Roundtable NPCs and system templates from being
picked as swap targets.

### What's still pending (not in v0.23.34)

- **Post-DLC MSBs**: the Great Hollow Shifting Earth tiles
  (`m6X_xx_xx_xx`) aren't in the pre-DLC MSB scrape. New chrs CAN swap
  into existing slots, but the new map regions are invisible to the
  rando until UXM dictionary update or Smithbox MSB export becomes
  available. User has a path forward via the FromSoft Modding Discord
  but hasn't pulled MSBs yet.
- **Re-export with FMG resolution**: 500 of the 2055 new variants are
  unnamed in the modded dump. Most are emerge-markers / templates that
  don't matter for the rando, but a Smithbox-with-Resolve-Names export
  would let us label them precisely.
- **EMEVD-spawned grunts** (Misbegotten ambush etc): still deferred,
  separate release arc.

## v0.23.33

### BFER cut from rando — manifests disabled

User request after CTD frustration on the v0.23.32 build: "screw
this i want all of the BFER stuff out! Cut it all!" Done.

### What changed

- `bfer_imports.json` `_meta.enabled` set to **false**
- `bfer_imports_v2.json` `_meta.enabled` set to **false**
- `OOPS_ALL_NB_FROM_BFER_POOL = False` (was True; pointless with BFER
  out of the pool — would just retry 8 times and fall through)

### Effect

Both manifests are now skipped at load. `V3_BFER_ALL_PREFIXES` ends up
empty. None of BFER's 32 c-prefixes (Margit-overrides through
Promised Consort Radahn) are in the rando's target pool. None of
BFER's 197 NPCParam variants (~2,963 entries when paired with their
regulation) get considered. The 97 size-class overrides from v2 also
don't apply, so vanilla NR's own size_class tags are used.

The rando now uses vanilla NR's roster + `vanilla_promotions_v1`
(8 tags / 15 variants — small curated set, unrelated to BFER).
Heritage pack remains disabled (was already off).

### Verification

200-trial simulation at a boss-tier slot post-disable: **0 BFER c-prefixes
returned**. Banner system correctly silent (no BFER_UNRESTRICTED banner,
no OOPS_ALL_NB banner).

### What this DOESN'T do

This is the **rando-side** disable only. If you have BFER's chr/
parts/ sfx/ files installed in your me3 profile, those still load
when vanilla NR's c-prefixes are referenced — e.g., vanilla NR's
c2010 Margit slot will still load BFER's Margit chr because that's
the file your me3 profile is pointing at. Vanilla c-prefixes that
overlap with BFER (c2010, c2031, c2050, c2110, c2120, c2180, c2190,
c2200) keep loading BFER's versions IF you have BFER installed.

To fully remove BFER from the game (not just from rando shuffle):
disable or uninstall the BFER asset pack in your me3 profile. That's
outside the rando's scope.

But for this v0.23.33 build's purposes — no BFER chr will ever be
SHUFFLED to a non-original slot. The chrs at vanilla c-prefix slots
will be whatever the chr/ files in your me3 profile dictate. The
rando is no longer a source of BFER chaos.

### Reverting

To re-enable BFER in the rando: flip both manifests' `_meta.enabled`
back to `true`, or roll back to v0.23.32 / v0.23.29 (last build with
the BFER gate active and manifests on).

### State as of v0.23.33

```python
BFER_UNRESTRICTED_TEST_MODE  = False
OOPS_ALL_NB_TARGET_CP        = None
OOPS_ALL_NB_USE_STRICT_MARKERS = False
OOPS_ALL_NB_FROM_BFER_POOL   = False
```

All test-mode flags off. BFER manifests off. Clean baseline. The
v0.23.27 boss-tier gate code path is preserved but inert (nothing to
gate — pool is empty). v0.23.29's prefix-fallback hardening also
preserved. If BFER gets re-enabled later, both gates remain in place
and effective.

### OPEN_ISSUES.md update

Adding a top-level note that BFER integration is currently disabled
pending a clean working theory. The 4-month arc of work on BFER
support (manifests, tier-tagging, gates, avoid-lists, EMEVD
investigation) is preserved in code as-is — easy to re-enable when /
if a path forward becomes clear. The empirical signal accumulated
across this arc:

- Regulation merge alone insufficient: dormant chrs at field slots
  even with BFER's regulation values active
- EMEVD-scaffolding hypothesis partially supported: arena-tier slots
  hosted BFER better than field-tier slots, but not reliably enough
  to ship
- CTD source unidentified: at least one variant in the BFER pool
  (post avoid-filter) was producing CTDs in the v0.23.31/v0.23.32
  builds. Would need targeted bisection to localize

If interest revives, the path forward is probably (a) bisect the
remaining variants by enabling them one c-prefix at a time, (b)
identify which BFER chrs work at which slot tier, (c) build a
positive-allowlist rather than a negative-avoid-list. Significant
work; not warranted right now.

---

## v0.23.32

### `OOPS_ALL_NB_FROM_BFER_POOL` — every arena gets a (random) BFER chr

User request, after CTD on the v0.23.31 all-Malenia seed: "let's
restrict the BFER bosses to arena, but have them populate all
arenas". Two coordinated changes.

### Defaults flipped

`BFER_UNRESTRICTED_TEST_MODE = False` (was True). The v0.23.27/v0.23.29
boss-tier gate is back on — BFER excluded from field-tier and prefix-
fallback (Prelude / event-trigger) slots. Vanilla NR team=26 entries
and BFER-specific avoid entries are both filtering again, which cuts
the previously-CTD-prone variants from the pool: cinematic-P2 Malenia
(21209000), Midra arena statue (50510002), Maliketh Black Blade arena
statue (21101073), Margit ghost-recall family (8 IDs), Hoarah Loux
phase-2 family (3 IDs), Rennala P2 cocoon (20310024 / 20310124).
Likely culprits for the CTD on the v0.23.31 build.

`OOPS_ALL_NB_TARGET_CP = None` (was 'c2120'). Single-c-prefix mode
disabled — variety restored.

### New flag: `OOPS_ALL_NB_FROM_BFER_POOL = True`

When set, every arena slot rolls a random c-prefix from
`V3_BFER_ALL_PREFIXES` (32 BFER c-prefixes). Each arena gets a
different BFER chr. Variant within the chosen c-prefix is rolled via
`pick_variant_for_tier(boss_tier=True)`, which respects
`V3_AVOID_VARIANT_NPC_IDS` — so the broken cinematic / statue /
phase-locked variants stay filtered out.

Net result with both flags set as defaulted in v0.23.32:

- BFER chrs land at arenas only (89 broad-marker slots, or 33 if
  `OOPS_ALL_NB_USE_STRICT_MARKERS=True`)
- Every arena gets a BFER chr — no arena stays vanilla
- Pool diversity: simulation across 89 slots produced 30/32 unique
  BFER c-prefixes used
- No avoid-list-flagged variants land at any slot

### Mechanics

The intercept condition was relaxed from `OOPS_ALL_NB_TARGET_CP and ...`
to `(OOPS_ALL_NB_TARGET_CP or OOPS_ALL_NB_FROM_BFER_POOL) and ...`.
Inside the branch, pool mode shuffles `V3_BFER_ALL_PREFIXES`, takes
the first 8 candidates, and returns the first one whose
`pick_variant_for_tier` yields a non-None variant. After 8 failures,
falls back to vanilla (slot stays unswapped) — but the simulation
shows this never triggers in practice; all 32 BFER c-prefixes have a
usable boss-tier variant under the active avoid filter.

Pool mode and fixed-target mode are mutually exclusive at the slot
level: pool mode wins when both flags are set. A startup banner makes
the active mode unambiguous.

### Spoiler

Spoiler emits `oops_all_nb_from_bfer_pool` alongside the existing
`oops_all_nb_target_cp` and `oops_all_nb_use_strict_markers`.

### Use case

This is the safest stress-test configuration for BFER chrs. It
maximizes BFER exposure (every arena = some BFER chr) while
constraining BFER to slots with proper EMEVD scaffolding (the gate
and avoid list both active). If BFER chrs at this config still
produce widespread dormancy / CTD, the EMEVD-scaffolding hypothesis
itself is wrong — BFER fundamentally needs more than scaffolding to
work. If they fight cleanly here, then v0.23.27's gate is the right
permanent boundary and we can lock in this config as steady-state.

### Reverting

Set `OOPS_ALL_NB_FROM_BFER_POOL = False` to disable. Both
`BFER_UNRESTRICTED_TEST_MODE` and `OOPS_ALL_NB_TARGET_CP` remain
flippable independently.

---

## v0.23.31

### `OOPS_ALL_NB_TARGET_CP` — force-target every boss slot

User request: "can you give me a version of the script that puts
malenia as every night boss". Sibling of the existing
`oops_all_target_cp` mechanism (which forces all slots to one
c-prefix), but scoped to boss-anchor slots only. Non-NB slots fall
through to the normal random swap path so the rest of the seed stays
varied.

### Two new flags at the top of `oops_v3.py`

```python
OOPS_ALL_NB_TARGET_CP = 'c2120'     # Malenia (BFER) — None disables
OOPS_ALL_NB_USE_STRICT_MARKERS = False
```

When `OOPS_ALL_NB_TARGET_CP` is set:

- Every slot whose source variant carries a boss-arena name marker
  gets force-routed to that c-prefix
- Variant within the c-prefix is rolled per-slot via
  `pick_variant_for_tier(boss_tier=True)` — different Malenia variant
  at each NB slot, picked from the 9 c2120 NPCParams BFER ships
- Non-marker slots (field grunts, evergaol-prelude, etc.) are
  unaffected — they continue to use `pick_target` with all the normal
  gating

`OOPS_ALL_NB_USE_STRICT_MARKERS=False` (default) uses
`V3_NIGHT_BOSS_NAME_MARKERS` — the broad set: Night Boss + Field Boss
+ Castle Boss + Fort Boss + Ruins Boss + Remembrance + (Crater) +
(Noklateo). 89 matching slots in current data. Best for "test Malenia
under various boss-arena scaffoldings."

`OOPS_ALL_NB_USE_STRICT_MARKERS=True` uses
`V3_NIGHT_BOSS_STRICT_NAME_MARKERS = ['Night Boss']` — strict
interpretation. 33 matching slots. Use this if you want Malenia ONLY
at the day-end Night Boss anchors.

### Mechanics

Intercept added between `oops_all_target_cp` and the standard
`pick_target` path in the swap loop's non-cluster branch (around line
6595). The intercept matches on the source variant's mmv_name against
the chosen marker set; misses fall through to the next branch.

Pairs naturally with `BFER_UNRESTRICTED_TEST_MODE=True` (now the
established default while you're stress-testing BFER) — the BFER gate
isn't even consulted on this path, but the global avoid-list bypass
still applies, so Malenia's cinematic-only `21209xxx` variant remains
in the c2120 pool.

### Spoiler

Spoiler metadata now emits both `oops_all_nb_target_cp` and
`oops_all_nb_use_strict_markers` so playtest results are unambiguous.

### Reverting

Set `OOPS_ALL_NB_TARGET_CP = None` to disable. Or roll back to
v0.23.30 if cleaner.

### Use case for diagnosing the dormant-Malenia case

Seed 779001 had three Malenia placements at non-boss-arena slots, all
dormant per playtest. With this build:

- Re-roll any seed
- Every boss-arena slot is now Malenia
- Walk the world and observe Malenia at NB anchors, Field Boss
  arenas, Castle Boss arenas, Crater bosses, Noklateo bosses
- Compare: at which scaffolding tier does Malenia activate vs stay
  dormant?

This isolates "what level of EMEVD scaffolding is enough for BFER
chrs to wake up" with a controlled c-prefix variable. A definitive
answer here calibrates the v0.23.27 gate's marker set going forward
(currently V3_BFER_ALL_PREFIXES is gated on `recipient_is_boss` —
might need tightening to `_slot_is_night_boss` or similar if only the
strictest scaffolding works).

---

## v0.23.30

### BFER unrestricted test mode

User request: "for now can you remove all the restrictions on the BFER
enemies? i want to really put them to the test." Empirical pivot —
with regulation merge happening on the user's side, the prior
diagnoses of BFER bugs (1hp, dormant, untextured) may have been
artifacts of running BFER chrs against vanilla NR's regulation
(missing 2,963 NPCParam entries). Time to stress-test under the
correct conditions.

### New flag: `BFER_UNRESTRICTED_TEST_MODE`

Module-level boolean at the top of `oops_v3.py`, defaulted to True.
When True:

1. **v0.23.27 boss-tier-only gate is disabled.** BFER c-prefixes can
   land at field grunts, evergaol slots, prefix-fallback (Prelude /
   event-trigger) slots — any tier the engine offers them.
2. **BFER-specific avoid entries (V3_BFER_SPECIFIC_AVOID_NPC_IDS,
   27 entries) are bypassed.** Margit ghost-recall variants (8000-
   8562, 9000-9410), Rennala P2 cocoon (20310024 / 20310124),
   Maliketh / Beast Clergyman cinematic (21101073 / 21109000 /
   21109042), Malenia (21209000), Melina (21809000), Hoarah Loux
   phase-2 family (47200070 / 47200100 / 47200134), Midra statue
   (50510002) — all eligible to roll.

Vanilla NR team=26 entries (the 81-entry bulk add from v0.23.24)
remain filtered. Those are independent of regulation merge state and
were diagnosed against vanilla NR's own NpcParam.csv, not BFER's.

### Mechanics

`V3_BFER_SPECIFIC_AVOID_NPC_IDS` is a new constant containing exactly
the BFER-derived avoid entries, separated from the general avoid set.
`_filter_avoid_npc` now computes `active_avoid =
V3_AVOID_VARIANT_NPC_IDS - V3_BFER_SPECIFIC_AVOID_NPC_IDS` when the
flag is on, and uses the full set otherwise. Surgical — non-BFER avoid
behavior is identical.

The boss-tier gate gets a `not BFER_UNRESTRICTED_TEST_MODE` short-
circuit added alongside the existing `not _bfer_gate_open` condition.

### Diagnostics

`load_data()` prints a 4-line banner whenever the flag is True, so
runs are clearly tagged. The spoiler emits
`bfer_unrestricted_test_mode` in the metadata block alongside
`chaos_mode`, `multiplayer_safe`, etc — playtest reports stay
unambiguous.

### Verified

- 500-trial simulation at field-tier source slot (c3010 'Banished
  Knight'): **158/500 BFER hits** (was 0/500 in v0.23.29). BFER
  spreading across tiers as intended.
- BFER-specific avoid bypass: c2010 npc 20108000 (Margit ghost-recall)
  passes the filter (was filtered in v0.23.29).
- Vanilla NR team=26 still filtered: c2500 npc 25008100 (Crucible
  Knight Memory of Grace) correctly stays excluded.

### Reverting

When the test concludes, set `BFER_UNRESTRICTED_TEST_MODE = False` at
the top of `oops_v3.py` (around line 925, in the
V3_BFER_ALL_PREFIXES declaration block) and re-run. Or roll back to
v0.23.29 if cleaner. The flag is intentionally code-level not GUI-
level — this isn't intended steady-state behavior.

### What to watch in playtest

With this build + BFER's regulation merged + BFER's event scripts
installed, every BFER chr placement should now be running on the
correct param values. Expected outcomes:

- **BFER chrs at NB arenas**: should fight properly with full HP /
  proper AI / proper attacks. The cosmetic mismatches (wrong music,
  wrong name banner, wrong drops) remain expected per the v0.23.27
  CHANGELOG analysis.
- **BFER chrs at field grunt slots**: this is the genuinely-untested
  case. With proper regulation, they MIGHT work — the EMEVD-
  scaffolding hypothesis would predict no, but we can now actually
  test it rather than assume.
- **Phase-2 / cinematic variants** (47200100 Hoarah Loux, 21109042
  Beast Clergyman, etc): with regulation merged, BFER's own param
  values for these IDs are loaded. They might no longer be 1HP. If
  they are still 1HP, the issue is intrinsic to those variants rather
  than a regulation lookup failure.

Failure modes to file as bugs (with seed + slot context):

- BFER chr loads dormant / no AI
- BFER chr 1HPs to first hit
- BFER chr renders untextured / partial-mesh
- BFER chr despawns mid-fight
- BFER chr fight deadlocks in phase 1

Cosmetic mismatches at swapped slots (wrong music / banner / drops)
are NOT bugs to file.

---

## v0.23.29

### v0.23.27 BFER gate hardening — Prelude/event-trigger bypass closed

Validation playtest of v0.23.27 (seed 992767) showed mostly-working
gate behavior — 11 BFER placements at boss-tier slots (test
candidates), but **5 leaks at slots my classifier read as field-tier
and the engine read as boss-tier-by-prefix-fallback**.

### Root cause

`build_per_prefix_data` (line 1687) filters out variants whose
mmv_name contains an event-trigger marker — `'Prelude'`, `'Night
Horde'`, `'Sparring'`, `'Dummy'`, `'Unlock Fight'`, `'Cutscene'`,
`'Story'`, `'Hidden'`, `'Trigger'` (V3_VARIANT_TRIGGER_MARKERS, line
928). These are vanilla NR's event-driven setpiece variants — EMEVD
owns them, they shouldn't be in the rando's swap-target pool.

But the same filter creates an asymmetric blind spot: when the engine
processes a SOURCE slot whose vanilla NPCParam is a filtered variant,
the `recipient_variant` lookup at line 6377 misses (because the
variant was dropped at build time), and line 6380 falls back to
`is_boss_tier_prefix(cur_cp, ...)`. For source c-prefixes tagged
'miniboss' tier (c2140 Omen, c3010 Banished Knight, c3700 Depraved
Perfumer, c4260 Erdtree Burial Watchdog), `is_boss_tier_prefix` returns
True. So `recipient_is_boss=True` gets passed to `pick_target_cp`, and
v0.23.27's BFER gate (which checks only `recipient_is_boss`) lets BFER
through.

The 5 seed-992767 leaks all matched this pattern:

```
m48_10 pi=2  c4260 'Erdtree Burial Watchdog (Smelter Demon Prelude)' → c5220
m49_24 pi=1  c3700 'Depraved Perfumer (Bell Bearing Hunter Prelude)' → c5220
m49_24 pi=2  c3700 'Depraved Perfumer (Bell Bearing Hunter Prelude)' → c4721
m49_26 pi=4  c3010 'Banished Knight'                                  → c5800
m49_28 pi=0  c2140 "Omen (Night's Cavalry Prelude)"                   → c5030
```

(Note c3010 is unmarked but the source NPCParam ID was filtered for
other reasons. Same prefix-fallback path.)

### Fix

The BFER gate now requires both `recipient_is_boss` AND
`slot_variant_name` non-empty:

```python
_bfer_gate_open = recipient_is_boss and bool(slot_variant_name)
if not _bfer_gate_open:
    pool = pool - V3_BFER_ALL_PREFIXES
```

Conservative-by-design: any slot whose source variant was filtered
out as event-trigger now defaults to BFER-excluded, regardless of
what the source c-prefix's tier tag says. Other gates (V3_ARENA_ONLY,
V3_NIGHT_BOSS_ONLY, etc) keep their existing behavior — they were
tuned over many releases against the prefix-fallback case and don't
need this hardening.

### Verified

Direct repro of the leak parameters:

- **Prefix-fallback case** (recipient_is_boss=True, slot_variant_name=''):
  500 trials × 4 source c-prefixes (c4260, c3700, c3010, c2140) →
  **0/500 BFER hits each**. Pre-fix would have ~30% BFER hit rate.
- **Real boss-tier case** (recipient_is_boss=True, slot_variant_name=
  'Banished Knight (Night Boss)'): 290/500 BFER hits. BFER still
  allowed at properly-classified boss slots.
- **Field-tier case** (recipient_is_boss=False): 0/500 BFER hits.
  Unchanged from v0.23.27.

### Implication for empirical loop

The seed-992767 11 boss-tier BFER placements remain valid test
candidates. Top of the list is still **`m49_25_00_00 pi=6 ent=49250810
c2031 'Rennala P2 (BFER)' npc 20310000`** at the Hippopotamus Night
Boss arena — strongest possible EMEVD scaffolding, base Rennala P2
variant. With BFER's regulation merged + event scripts installed,
this is the cleanest available test of the option-2 hypothesis.

The 5 ex-leaks (Smelter Demon Prelude, Bell Bearing Hunter Prelude
×2, m49_26 Banished Knight, m49_28 Night's Cavalry Prelude) would no
longer get BFER targets on a fresh re-roll under v0.23.29 — they'd
route to non-BFER chrs.

### OPEN_ISSUES.md update

Removing the "prefix-fallback path through `is_boss_tier_prefix` lets
BFER through at slots whose source variant isn't in `prefix_variants`"
item from the audit-script blind spots section — that's now addressed
by this gate hardening. Adding a new note: the same prefix-fallback
pattern affects the v0.23.22 source-side emerge-marker filter too —
that filter also gates on `recipient_variant is not None`, meaning
event-trigger variants that get filtered out by build_per_prefix_data
ALSO bypass the emerge-marker filter. If a future bug surfaces where
a Prelude slot's BFER chr despawns mid-fight (Fell Omen pattern), the
emerge-marker filter needs the same hardening.

---

## v0.23.28

### OPEN_ISSUES.md added

Doc-only release. The verbal ledger of open threads has been getting
unwieldy across the v0.23.20 → v0.23.27 arc, and reconstructing the
backlog from CHANGELOG entries plus conversation memory was costing
real session-time. `OPEN_ISSUES.md` is the durable home for:

- **Active dormancy / EMEVD bug class** — Adula, Avionette, c4502
  dragon, c4441 Land Squirt — all share one underlying mechanism
  (`permissive_spawn_emerge` matches entrance opcodes but misses
  boss-intro handoff). One diagnostic pass against Adula at
  ent 38000850 should fix the whole class.
- **v0.23.27 BFER gate empirical loop** — what to test in the next
  playtest, contingencies for "NB works but Castle/Fort doesn't" vs
  "even NB broken."
- **Audit-script blind spots** — low-suffix arithmetic-inheritance
  variants that the >=8000 threshold misses; cluster-path source-side
  emerge-marker filter gap; Chinese-name marker expansion candidates.
- **c-prefixes that should be excluded outright** — the 9 entirely-
  team=26 prefixes flagged by the v0.23.24 audit but masked behind
  the soft-fallback's removal in v0.23.25 rather than properly
  excluded.
- **vanilla_promotions_v1.json audit** — c4441/c4442/c4502 are tagged
  as vanilla but empirically absent from vanilla NR's chr/.
- **Investigation threads** that need more data before fixing —
  Ulcerated Tree Spirit "missing skin", Rennala P2 untextured
  rendering (likely chr-asset issue, not engine), me3 chr-file
  fallback semantics.
- **Closed observations** — Battlefield Commander summoning its own
  ads (working as intended, hilarious side effect of swap), seed-
  deterministic NPCParam reuse across maps (just RNG, not a bug),
  v0.23.21 hard avoid filter trade-off (correct choice, documented
  here so future-us doesn't relitigate).

The "Closed observations" section is deliberately included so future
sessions don't re-trace ground we've already covered. Behaviors that
look buggy at first glance, design decisions whose trade-offs we
accepted, edge cases we explicitly chose to leave as-is — all worth
not re-debating.

Engine fingerprint bumped per convention (any release bumps, even
doc-only).

---

## v0.23.27

### Option 2: BFER chrs gated to boss-tier slots only

User feedback: across v0.23.20 → v0.23.26 we excluded a steadily
growing list of cinematic / phase-locked BFER variants from
`V3_AVOID_VARIANT_NPC_IDS` (now 109 entries). The 1hp / ghost / despawn
bugs got rarer with each fix, but **no confirmed-working BFER
placement was ever observed**. Margit ghosted, Rennala P2 1hp'd,
Beast Clergyman 1hp'd, Hoarah Loux 1hp'd. Heritage chrs worked fine
(Fat Inquisitor was the user's first explicit "this is working"
confirmation, c5320 from heritage_pack v2). BFER didn't.

Whack-a-mole on individual NPCParam variants reduces obvious symptoms
but doesn't address the underlying class. The hypothesis worth testing:
**BFER chrs need EMEVD scaffolding to function correctly** — boss-intro
events, phase-transition triggers, recognition checks — and that
scaffolding only exists at slots originally authored as boss
encounters in vanilla NR. Field grunt slots have none of it.

### Engine fix

New global `V3_BFER_ALL_PREFIXES`, populated at `load_data()` time from
`bfer_imports.json` + `bfer_imports_v2.json` `tags` keys. Currently
contains 32 c-prefixes covering the full BFER import set (c2010
Margit, c2031 Rennala P2, c2050 Ranni, c2110 Maliketh, c2120 Malenia,
c2180 Melina, c2190 Radagon, c2200 Elden Beast, c4604 Strategist Iji,
c4720 Godfrey/Hoarah Loux, c5051 Midra, c5220 Promised Consort
Radahn, plus heritage-imported sub-prefixes c4504/c4511/c4520/c4601/
c4710/c4721/etc).

New gate in `pick_target_cp`, mirroring the existing `V3_ARENA_ONLY_TARGETS`
pattern from v0.20.8:

```python
if not recipient_is_boss:
    pool = pool - V3_BFER_ALL_PREFIXES
```

Gate position: immediately after the arena-only gate, before the NB
caliber gates. Same logical level as arena-only — "this set of chrs
doesn't function at field-tier slots." Different motivation
(EMEVD-dependence vs geometric arena-shape), identical mechanism.

The cluster path (`pick_cluster_target_cp`) routes through
`pick_target_cp` with `cluster_is_boss` as the tier signal, so the
gate fires correctly there too. No bypass.

### Empirical impact (seed 356064 spoiler simulation)

Re-applying the gate to last seed's spoiler placements:

- **8 BFER placements would survive** at boss-tier source slots —
  c4721 'Hoarah Loux Warrior' at evergaol (m46_50 / m46_60), c5300
  'Twin Moon Knight' at evergaol, c5000 'Commander Gaius' at Death
  Bird Night Boss arena, c2050 Ranni at Castle Banished Knight slot,
  c4604 Strategist Iji at Castle Troll slot, c2180 Melina at Castle
  Banished Knight + Death Rite Bird Night Boss slots.
- **29 BFER placements would be cut** at field-tier source slots,
  redirected to non-BFER targets via the standard pool selection.

The 8 survivors are the empirical test population for next playtest:
do BFER chrs work when given boss-tier slot context? If yes, the
hypothesis is confirmed and we keep the gate. If they STILL break at
boss-tier slots — at least at non-NB-arena boss-tier slots like
Castle / Fort / Evergaol — we tighten the gate to NB-arena-only by
intersecting with `V3_NIGHT_BOSS_NAME_MARKERS` at the slot side.

### Followup possibilities (filed forward)

- **Tighten to NB-arena-only**: if Castle/Fort/Evergaol BFER
  placements still misbehave, replace `recipient_is_boss` with the
  tighter `_slot_is_night_boss` signal already computed for the
  v0.23.11 chaos_mode gate.
- **Per-prefix whitelist**: if specific BFER c-prefixes prove robust
  at field slots in some empirical set (e.g. "Stonedigger Troll
  always works"), exempt them via a `V3_BFER_FIELD_SAFE_OVERRIDES`
  whitelist subtracted from `V3_BFER_ALL_PREFIXES` at gate time.
- **GUI toggle**: a "BFER strict mode" checkbox that flips the gate
  off (returns to v0.23.26 behavior) for users who explicitly want
  to gamble on BFER variety.

None of these are needed for the v0.23.27 ship. The gate is the
right starting position — narrower than the previous behavior,
broader than complete BFER ban, with a clear empirical loop for
calibration.

---

## v0.23.26

### "1hp Hoarah Loux in evergaol" — c4720 phase-locked variants excluded

User playtest seed 356064 (chained from the previous round of fixes,
this time a clean v0.23.24 run) reported three encounter notes:

1. **"Fat Jory guy at Night 1 pre-boss, working"** — confirmed: this
   was `c4720 'Godfrey (BFER)'` placed at `m48_80_00_00 pi=2`
   (Stormveil pre-boss area). BFER's Godfrey rendered correctly with
   full HP and combat AI. The slot's local EMEVD context was
   forgiving.
2. **"1hp Hoarah Loux in an evergaol"** — same chr, same NPCParam
   (`47200100`), different placement: `m49_19_00_00 pi=2`. m49_19 is
   a small evergaol arena with no boss-intro EMEVD. The chr loaded in
   pre-transition 1hp state.
3. **"Ulcerated Tree Spirit missing skin"** — `c4640 'Ulcerated Tree
   Spirit (Night Boss)'` at `m46_71_00_00 pi=1` (npc_param 46400010,
   the base combat variant). Investigation deferred — see "Open
   threads" below.

### Diagnosis

BFER ships c4720 (an unused vanilla NR slot) as Godfrey/Hoarah Loux
imported from vanilla ER. Four NPCParams in the manifest:

```
47200000  'Godfrey (BFER)'        — base, phase 1, full HP
47200070  '初王' (First King)     — cinematic intro variant
47200100  'Godfrey (BFER)'        — phase 2 (Hoarah Loux), 1hp without intro
47200134  'Godfrey (BFER)'        — suffix-100-derived phase-2 variant
```

The 47200100 variant is the Hoarah Loux phase-2 form. In vanilla ER,
its HP starts at 1 because phase-1 Godfrey's death-cutscene fires the
phase transition that boosts HP back up. At a randomized slot with no
boss-intro EMEVD (any evergaol or non-arena placement), the cutscene
doesn't fire — the chr loads at 1hp and dies to the first hit.
47200134 inherits from 47200100 the same way 20310124 inherited from
20310024 in the v0.23.20 Rennala P2 case. 47200070 is the cinematic
"First King" intro variant (parallel to the 9xxx-suffix scripted
variants on c2110 Maliketh and c2120 Malenia).

The same 47200100 worked at m48_80 because that map has its own
EMEVD context (Stormveil-area boss arena). Slot-level EMEVD environment,
not the chr or NPCParam, determines whether phase-2 forms can fire
their transition. We can't rely on slot EMEVD to bail us out — exclude
the unsafe variants and let placements route to 47200000 (base).

### Engine fix

Added `47200070`, `47200100`, `47200134` to `V3_AVOID_VARIANT_NPC_IDS`.
`47200000` (base, full-HP combat phase 1) stays available.

`V3_AVOID_VARIANT_NPC_IDS` is now 109 entries (was 106).

### Audit script extension

Added `c4720` to `PHASE_LOCKED_BFER_PREFIXES` in
`dev/audit_bfer_variants.py`. This means future BFER manifest updates
will be checked against c4720's variant family — but with a known
limitation: the suffix-based heuristic only catches >=8000-suffix
variants. The c4720 problem variants are suffix 70, 100, and 134 —
ALL below the 8000 threshold. They were caught by manual review +
named-entity inspection (`'初王'` for 47200070), not by the
algorithmic part of the audit.

### Open audit-script gap (filed forward)

Three c-prefixes have now demonstrated low-suffix phase-locked
variants that the suffix heuristic misses:

- **c2031 Rennala P2**: 20310024 (cocoon, suffix 24) → 20310124
  (suffix 124, derived). Caught manually in v0.23.20.
- **c4720 Godfrey/Hoarah Loux**: 47200100 (phase 2, suffix 100) +
  47200134 (derived). Caught manually here.
- **c2030/c2031 vanilla**: not yet tested but conceptually same risk.

The pattern is **arithmetic inheritance**: variant X100/X134/X034
inherits phase state from variant X000 via the FromSoft phase-
transition mechanism. Suffix in [70, 100, 134] is a meaningful flag
when the c-prefix is a multi-phase boss; it's noise on a single-phase
chr. A fully algorithmic detector would need a "multi-phase boss"
classification list — same data we'd need anyway. Filed as a future
v0.23.27+ improvement; for now manual review fills the gap.

### Open threads carried forward

- **Adula dormancy** (Cathedral, entity_id 38000850) — same EMEVD
  bug class as Avionette and the c4502 dragon. Needs a
  `permissive_spawn_emerge` diagnostic pass that catches the boss-intro
  opcodes after the entrance-anim handoff. Separate session.
- **c4441 Large Land Squirt suspected dormancy** — user reported
  "died into a big poison cloud, maybe that's all it does". Vanilla NR
  Land Squirt has a real fight (full HP, opens up with poison emit as
  an attack, retreat-into-shell defensive state). The "die instantly
  into cloud" pattern suggests dormancy — same class. Needs spoiler
  context to identify the placement; likely unscaled c4441 variant.
- **c4640 Ulcerated Tree Spirit "missing skin"** — single placement
  at m46_71_00_00 pi=1, NPCParam 46400010 (the base combat variant —
  no obvious bug class). Two possible interpretations: (a) Ulcerated
  Tree Spirit canonically looks "flayed/rotted" by design and the user
  is unfamiliar with the chr's intended appearance, or (b) genuine
  texture/shader/mesh issue. Needs a follow-up screenshot or "patches
  vs whole-body" detail to disambiguate. Filed but no fix shipped.

---

## v0.23.25

### Hard avoid filter — c3670 leak in v0.23.24

Validation playtest of v0.23.24 (seed 356064) showed all the c2500 /
c3200 / etc team=26 fixes working correctly, EXCEPT for c3670: 4 boss
slots in the seed got `c3670 'Aged Albinauric (Scholar Remembrance)'
npc_param 36708100` — exactly the team=26 variant we just added to the
avoid set.

### Root cause

c3670 in `nr_enemy_tags.json` has `variants: 1` — vanilla NR's
regulation has exactly ONE NPCParam for c3670, and it IS the team=26
cinematic one. The v0.23.21 upfront avoid filter correctly removed it,
but the v0.20.86 SOFT-fallback semantic (`return filtered if filtered
else variants`) then returned the original list with the bad variant
back in it.

The soft-fallback was originally introduced as a hedge: "if filtering
would empty the variant pool, return the original to preserve
placement coverage." That worked when most c-prefixes had at least one
good variant. But the bulk team=26 add in v0.23.24 created a class of
c-prefixes (c3670 plus the 9 entirely-team=26 ones from the audit:
c4492, c52101 / c52102 / c52107 / c52309 / c52312 / c52313, c8910,
c8911) where ALL variants were avoid-listed. The soft-fallback then
guaranteed the bad placement, defeating the avoid filter's entire
purpose.

### Fix

`_filter_avoid_npc` is now a HARD filter — soft-fallback removed. If
filtering empties the variant pool, returns empty. `pick_variant_for_tier`
then returns None, and the caller falls back to vanilla preserve via
the standard None-return path (the same path used for empty-name
variants since v0.23.04.1).

Trade-off documented in the function docstring: c-prefixes with ONLY
avoid-listed variants are no longer placement candidates in practice.
The slots they would have populated stay vanilla. This is correct —
those c-prefixes have no usable combat variant, and were producing
visible bugs (non-interactable enemies, ghost replays). Reduced
placement variety for ~10 c-prefixes is a much better trade than
guaranteed-bad placements for them.

### Verified

End-to-end simulation:

- c3670 (1 variant, all team=26): boss + field both return None →
  vanilla preserve. Pre-fix would have placed 36708100 every time.
- c2500 (5 variants, 2 team=26): unchanged from v0.23.24 — field
  picks split between 25001010 / 25001110, boss picks always
  25000020.
- c7100 (2 variants, 1 in avoid set since v0.20.86): unchanged from
  v0.23.21 — all 100 field picks route to 71000010.

### About the merchant "leaks" in seed 356064

Initial leak detection script flagged 24 entries with avoid-listed
NPCParams. 20 of those were `npc_param=32000000` placements with
displayed name "cXXXX (still merchant — model only)". These are
correct merchant_model_swap behavior — that path writes only
MODEL_INDEX, never NPC_PARAM, so the merchant base param 32000000
(which IS in the avoid set since v0.23.24) stays preserved on the
slot. The leak detector had a false positive — the engine was doing
the right thing for merchants. No fix needed; documenting here so
future audits don't chase the same false trail.

---

## v0.23.24

### Crucible Knight at Abductor Virgin slot — non-interactable team=26 variant

User playtest seed 713344 (engine v0.23.22, the previous build with all
prior fixes) reported a Crucible Knight rendered as a copper-armored
figure at a Fort Abductor Virgin slot (m30_00_00_00 pi=36, originally
c4470 'Abductor Virgin (Fort)'). The chr was visible but ignored the
player — couldn't aggro, couldn't be hit. NPCParam 25008100.

Diagnosis: **non-cluster slot, non-empty source mmv_name, non-BFER
target** — three conditions that ruled out all our existing bug
classes. Eventually traced to **teamType == 26** in vanilla NR's
NpcParam.csv. Team 26 is the non-aggressive/cinematic team used by
grace-replay variants, decorations, and friendly NPCs. NR's "Stormveil
Memory of Grace" replay system reuses the Crucible Knight model with
a team=26 variant that's intended to play out a fixed combat sequence
on a recall trigger — not to be placed at random combat slots.

### Bulk audit of vanilla NR NpcParam.csv

Found **81 team=26 entries across 35 c-prefixes** in vanilla NR. None
were in `V3_AVOID_VARIANT_NPC_IDS`. All 81 added to the avoid set,
grouped by c-prefix with inline comments. Highlights:

- **c2500 Crucible Knight**: 25008000, 25008100 (the user-reported case)
- **c3200 / c3210 Nomadic Merchant family**: 24 IDs total — these are
  the merchant base NPCParams, which the merchant_model_swap path
  preserves separately (writes only MODEL_INDEX, never NPC_PARAM), so
  excluding them from variant selection doesn't break merchants.
- **c3850 Lobster**: full 3xxx subfamily is team=26 — 4 IDs.
- **c4180 Spirit Jellyfish**: 1 ID — the model is already a "spirit"
  in name, the team=26 variant rendered as a fully translucent / non-
  combat form.
- **c521xx / c523xx / c61003**: staged-form sub-prefixes of phase-
  split bosses (Promised Consort Radahn, Heolstor cinematic phases,
  mounts/vehicles). Many entirely team=26 — the c-prefix itself is
  cinematic-only.
- **c8910 / c8911 / c4492**: entirely team=26 c-prefixes — system /
  decoration chrs that shouldn't be placement candidates at all.
  Soft-fallback in `pick_variant_for_tier` handles them correctly
  (returns the original list when filter empties it), but flagged in
  the audit report for potential c-prefix-level exclusion via
  `V3_EXCLUDE_TARGET_PREFIXES` in a future pass.

### Coverage check

After the bulk add, `V3_AVOID_VARIANT_NPC_IDS` grew from 25 → 106.
Verified end-to-end with a simulation:

- 200 field-slot picks for c2500 → all routed to 25001010 / 25001110
  (the legitimate combat field-tier variants). 25008000 and 25008100
  never appeared.
- 50 boss-slot picks for c2500 → all routed to 25000020 (the
  Field-Boss-marked + reward-bearing combat variant).

### Audit script: `dev/audit_team26_variants.py`

Companion to the existing `audit_bfer_variants.py` (which works on the
BFER manifest). The new script reads vanilla NR's `NpcParam.csv`
directly and reports any team=26 variant not currently in
`V3_AVOID_VARIANT_NPC_IDS`. Standalone — no dependencies beyond the
csv module + the regex parse of `oops_v3.py`. Same coverage-check
exit-code semantics as the BFER auditor (0 if all team=26 covered,
1 if any are missing).

Future workflow: when a new NR patch ships, unpack `regulation.bin`
with WitchyBND, point the script at the new `NpcParam.csv`, and the
delta surfaces immediately.

### team=26 vs the BFER ghost-recall pattern

These are distinct mechanisms with overlapping symptoms. The v0.23.20
BFER Margit ghost-recall variants (20108000 etc.) **don't show up
under team=26** in vanilla NR's NpcParam.csv — those live in BFER's
separate regulation, with a different team value. The two audits are
complementary:

- `audit_bfer_variants.py`: catches BFER-specific cinematic variants
  via suffix patterns + statue-name detection.
- `audit_team26_variants.py`: catches vanilla NR cinematic variants
  via teamType field.

If a future report surfaces a third class (e.g., team=26 in BFER's
own regulation), extending the BFER auditor to consume a CSV from
that regulation would close the symmetry.

### Caveat — heuristic risk

team=26 is an empirically-derived heuristic. In principle a legitimate
team=26 placement could exist that the user wants to keep — for
example, a friendly NPC that the rando would normally route through
some special handling. If post-v0.23.24 a previously-reliable
placement disappears, that's the place to look first: maybe it was
team=26 and got swept up. Easy to whitelist exceptions back in by
removing the specific ID from the avoid set.

---

## v0.23.23

### GUI: verbose dim labels → info-icon tooltips + Heritage essay collapsible

User noted "there's some text in the GUI that definitely would be better
off in an 'i' or a hover-over tooltip". Several dim-label descriptions
had grown into 5+ line explainers that visually dominated the surrounding
controls. They earn their keep when a user actually wants to read them
but get in the way when the user is just trying to flip a checkbox.

### New helpers

`Tooltip` class and `make_info_icon()` factory added to
`oops_rando_gui.py`. `Tooltip` is the underlying primitive — bind any
widget to show a borderless `Toplevel` near the cursor on `<Enter>`,
hide on `<Leave>`. 350ms delay before showing so quick mouse passes
don't flash tooltips. Wraps at 360px so long bodies stay readable
without being walls of text. macOS gets the `noActivates` window-style
hint to avoid focus-stealing.

`make_info_icon(parent, tooltip_text)` packs a small "ⓘ" Label into
the parent container and attaches the tooltip — the standard pattern
for inline help affordances.

### Conversions

Three multi-line dim labels promoted to info-icon tooltips:

- **Cinematic Chaos** description (5 lines → tooltip on a "ⓘ" next to
  the checkbox).
- **Diagnostic mode** description (6 lines → tooltip).
- **Diagnostic batch field** description (5 lines → tooltip on a "ⓘ"
  in the field's row).

Two compound dim labels reformulated: chr/ Inventory tab's **paths
explainer** and **actions explainer**. Each had 4 lines of dim text
below their respective sections; replaced with single-word "Path help"
/ "What do these do?" anchors plus info icons. Same content, tenth the
visual weight.

One short dim label slimmed: **Force-include** description trimmed
from 4 lines to 1; the implementation detail (tier-preserve still
applies, glitch-class context, example use case) moved to the icon's
tooltip.

### Heritage essay → "Read more" expander

The "What is heritage?" body in the Heritage tab — a ~24-line essay
covering when heritage chrs are safe, when they break coop, what the
toggle does, and the recommendation — was always visible. Too long for
a tooltip, too useful to delete, but visually overwhelming for users
who already understand what they're toggling.

New behavior: the body is collapsed by default behind a "▶ Read more"
button. One-line dim summary alongside the button: "When heritage chrs
are safe, when they break coop, what the toggle does." Click the
button to expand inline; click again to collapse. Toggle method is
`_toggle_heritage_essay` (BooleanVar-tracked, button label flips
between "▶ Read more" and "▼ Hide").

The body content is unchanged — same words, same coverage. Just no
longer dominates the tab on first render.

### Kept inline

Short single-line dim labels stay where they are — they're the
at-a-glance defaults annotation (e.g., "(default ON — safest setting
for any session that might involve coop)") and the friction of
hovering an icon to read 6 words isn't worth it. The conversion
threshold was roughly: anything more than one line of explanation, or
anything that's implementation detail rather than user-facing
default-context, becomes a tooltip.

### Out of scope for this pass

- About-tab dim labels (lines 1401, 1439, 1481 in pre-patch source).
  These are short attributions and version notes — fine inline.
- Excluded-targets tab dim labels — short single-line. Fine inline.

---

## v0.23.22

### Fell Omen + blue crab — emerge-marker source slots

User playtest seed 373504 reported "A Fell Omen Has Appeared" event
firing during the Morgott Night Boss fight (m48_40), followed by a
blue crab spawning and immediately disappearing. Tracked to a new bug
class: **emerge-marker source slots being swapped**.

In FromSoft MSB convention, certain Part placements have their vanilla
NPCParam set to a placeholder with an empty `mmv_name`. These are
event-driven spawn anchors — vanilla EMEVD owns the spawn via
`ForceAnimationPlayback`, and a follow-up event verifies the chr's
NPCParam is the expected one and despawns if not. The Fell Omen
narration in the Morgott fight is exactly this pattern: event fires →
spawn happens → recognition check → if the NPCParam is unexpected
(because rando swapped it), despawn.

The engine already had `filter_emerge_variants` for **targets** —
prevents writing emerge-placeholder NPCParams as swap destinations —
but no equivalent for **sources**. So the rando happily swapped chrs
AT vanilla emerge-marker slots, breaking the event-driven spawn loop.

User-confirmed example: m48_40_00_00.msb pi=1, vanilla c2140 emerge-
marker (npc_param 21400220, empty mmv_name) → swapped to c2271 Crab.
EMEVD fired during the boss fight, the crab appeared briefly, then
vanished when the recognition check found the wrong NPCParam.

### Fix

Source-side emerge-marker skip in the swap loop, mirroring the
existing target-side filter at `pick_variant_for_tier:1726`. After
looking up the source `recipient_variant`, if its `mmv_name` is empty
or whitespace, the slot is skipped — preserves vanilla, avoids
breaking the event spawn/despawn loop.

Counted impact: **100 emerge-marker slots in seed 373504 alone** would
have been swapped pre-fix. Post-fix they all stay vanilla. Affected
maps span:

- `m15_00` (Roundtable Hold area, c3661/c4021 placeholders — 9 slots)
- `m35_90` (Limveld entry, c3703/c4340 — 2 slots)
- `m46_00` (Limveld overworld, c4313/c4353/c4373/c4600 — 14 slots)
- `m46_01`/`m46_02`/`m46_03` (overworld, c4550/c4280/c4250 — 24 slots)
- `m46_05` (Guardian Golem area, c4660 — 2 slots)
- `m46_70`/`m46_78` (small castles, c4650/c2130 — 2 slots)
- `m48_xx` Stormveil-area emerge anchors including the user's
  m48_40 Morgott Night Boss arena — 12 slots
- `m49_xx` Limveld emerge anchors — multiple slots
- And so on.

The skip is logged via `_log_unaccounted` with reason
`source_emerge_marker` for diagnostic visibility.

### Side notes from the same seed

- **Ghost at evergaol** in the screenshot (c7100 Ancient Hero spirit-
  rendered) was the v0.23.21 soft-filter-bypass bug. The user's run
  was on engine fingerprint v0.23.14 (pre-fix; the fingerprint had
  been stale for six versions). v0.23.21 routes c7100 to 71000010
  ('Ancient Hero (Field Boss)') at all field slots — re-rolling on
  v0.23.22 will eliminate the ghost-at-evergaol case alongside the
  emerge-marker fix.
- **Cluster path** is not yet covered by the source-side emerge skip.
  If a clustered Part is a vanilla emerge marker, it currently still
  gets swapped via the cluster swap path. Filed as v0.23.23 work.

---

## v0.23.21

### Spirit-spring CTD diagnosed — soft-filter bypass in pick_variant_for_tier

Triggered by user playtest seed 373504, "CTD when jumping into a spirit
spring near a smaller fort". Diagnosis traced to `m60_44_36_00.msb pi=63
y=89.16` (fort tower altitude) where c7100 Ancient Hero variant
71000110 ("Ancient Hero (Ruins)") was placed despite that NPCParam
being in `V3_AVOID_VARIANT_NPC_IDS` since v0.20.86.

Seven c7100 placements in this seed used 71000110, all at non-Ruins
slots. The variant has spirit/ghost rendering baked in (Ruins-arena fog
context); outside that arena, render dependencies are unsatisfied. At
the spirit-spring destination cell, the streaming-load path apparently
exercises a code path that doesn't tolerate the missing dependencies →
hard CTD. Walking into the same cell on foot would presumably show a
ghost-translucent Ancient Hero (cosmetic-only).

### Bug

`pick_variant_for_tier` applied `_filter_avoid_npc` *inside* each
tier-fallback path (Tier-1/2/3/4 for boss slots, the field-tier branch
for non-boss). Tier filtering ran first, narrowing the variant pool by
boss/field markers; the avoid filter ran second, on the already-narrow
pool. When tier filtering left only avoid-listed variants in the pool,
the soft-fallback semantics of `_filter_avoid_npc` (`return filtered
if filtered else variants`) returned the bad variant rather than no
variant.

Concrete c7100 trace: it has two NPCParams in the regulation —
71000010 ("Ancient Hero (Field Boss)") and 71000110 ("Ancient Hero
(Ruins)"). At a non-boss field slot:

  1. Field-tier filter `[v for v in variants if not is_boss_tier_variant(v)]`
     removed 71000010 because the "Field Boss" name marker classifies
     it as boss-tier.
  2. Field-tier-restricted set was then `[71000110]`.
  3. `_filter_avoid_npc([71000110])` produced `[]` after avoid-list
     removal, then soft-fell-back to the input list `[71000110]`.
  4. `rng.choice([71000110])` → bad placement.

The avoid filter never had a chance to redirect to 71000010 because
71000010 was already gone by the time avoid filtering ran.

### Fix

Move the avoid filter to run ONCE globally at the top of
`pick_variant_for_tier`, before any tier filtering. The five inner
`_filter_avoid_npc` calls in the tier-fallback branches are removed
since the input is already filtered. New behavior: avoid-listed
variants are pruned first; tier filtering operates on the cleaned set;
if tier filtering empties the set, the existing tier-fallback paths
still fire but now fall back to OTHER GOOD variants instead of
avoid-listed bad ones.

Verified end-to-end: 100/100 simulated picks of c7100 at a non-boss
field slot now route to 71000010 ("Field Boss" variant). Pre-fix
behavior was reliably picking 71000110 (sole survivor of tier
filtering) → 100% bad placement rate at any field slot.

### Stale fingerprint fixed

`V3_ENGINE_FINGERPRINT` had been hardcoded to `'v0.23.14'` since v0.23.14
shipped, never bumped after. Spoilers from any v0.23.15 → v0.23.20
build were misleadingly reporting the wrong version. Bumped to
`'v0.23.21'` and inline-commented as "MUST bump on each release —
appears in spoilers" so future versions don't drift.

### Side notes from the same seed

- **c4502 dragon dormancy / lag at m30_30 Guardian Golem arena** still
  open. Same class as the Avionette/Adula bug from the verbal ledger —
  `permissive_spawn_emerge` EMEVD patch handles `ForceAnimationPlayback`
  but misses dragon boss-intro opcodes. Diagnostic pass against
  entity_id 30300800 is queued for a future EMEVD-focused session. The
  lag is c4502's persistent ambient VFX, not Borealis freezing fog
  (c4503 wasn't in this seed at all).
- **No phantom-prefix placements** in this seed (c4021/c4181/c4641 all
  excluded as expected since v0.23.15). The me3 chr-fallback question
  remains indirectly answered.

---

## v0.23.20

### "Blue Margit" + "1hp Godfrey" — five new BFER variants excluded

Triggered by user playtest seed 767092 (chaos_mode=ON, FIA + BFER +
Heritage profile). Two distinct symptoms across the same run:

- "Blue Margit" appearing at field slots — visually translucent /
  ghost-tinted Margit, jarring at non-Stormveil placements.
- "1hp Godfrey" at m60_44_39_20 — actually **c2031 Rennala P2**, not
  Godfrey. BFER repurposes c2031 (which is Hoarah Loux in vanilla ER)
  for Rennala phase 2. The robed-figure-in-distress visual is a
  reasonable misread of Rennala P2 in 1hp pre-transition state.

### Diagnosis

Spoiler dump showed the run placed three c2010 Margit variants in the
8xxx-suffix family (20108000, 20108500, 20108562) and one c2031 Rennala
P2 variant 20310124. Cross-referencing against
`bfer_imports.json`'s `variants_per_prefix` block:

**c2010 Margit family (19 BFER variants total).** v0.23.17 caught all
13 9xxx-suffix variants (cinematic phase-lock — friendly NPC, statue,
post-cutscene state). The 8xxx-suffix family was missed entirely.
Empirical evidence + ER convention: 8xxx Margits are tied to the
Stormveil "memory of grace" recall sequence — sit at certain
Stormveils graces and replay the Margit fight as a vision. The
vision-Margit has a translucent blue ghost VFX baked into the variant.
Three placements in this run all rendered as ghost-blue at non-NB
slots.

**c2031 Rennala P2 family (4 BFER variants).** Variant 20310024 is
"满月女王" (Full Moon Queen) — Rennala's phase-1 cocoon form, scripted
non-combat by default. Variant 20310124 arithmetically inherits state
from 024 (124 = 100 + 24) and empirically loaded in 1hp pre-
transition state at a random NR slot. Both unsafe at random
placements. Base 20310000 and scaling-tier 20310100 left available —
those are the legitimate combat variants.

### Engine fix

Five new entries added to `V3_AVOID_VARIANT_NPC_IDS` (now 25 total):

- c2010 Margit ghost-recall: 20108000, 20108500, 20108562
- c2031 Rennala P2 cocoon-derived: 20310024, 20310124

The 7xxx-suffix range for c2010 (e.g., 20107500) is left untouched —
suspected NG+ scaling tier rather than a render variant, but no
empirical data either way. Pending playtest evidence.

### Audit script broadened

`dev/audit_bfer_variants.py` updated:

- `PHASE_LOCKED_BFER_PREFIXES` now includes `c2031` (with a comment
  noting BFER's repurposing from vanilla ER's Hoarah Loux). This means
  future BFER manifest updates will be checked against c2031 too.
- Suspicious-suffix threshold lowered from `>=9000` to `>=8000`. The
  9xxx range catches scripted/cinematic phase-lock; the 8xxx range
  catches ghost-recall variants. Both are unsafe at random placements
  for the prefixes in `PHASE_LOCKED_BFER_PREFIXES`. The lower bound is
  exposed as a module-level constant `SUSPICIOUS_SUFFIX_THRESHOLD` for
  easy future adjustment.
- Re-running the audit passes: all 22 suffix-flagged + statue-flagged
  variants are in the avoid set.

### Audit-heuristic blind spot worth noting

The 20310024 / 20310124 case demonstrates a class of bug the
suffix-based heuristic can't catch on its own: **low-suffix variants
that arithmetically inherit state from other low-suffix variants**.
The audit caught the 8xxx Margits via the broadened threshold, but the
c2031 Rennala variants were added based on empirical playtest evidence
+ named-entity inspection (the Chinese name "满月女王" identifying
20310024 as the cocoon form). Future audit improvements could include:

- Per-prefix manual-exclude maps for cases where suffix patterns alone
  don't carry enough information.
- Pattern-matching on Chinese NPC names that indicate non-combat /
  cinematic state (e.g., 雕像 = statue, 友好 = friendly, 主城 = main
  castle / scripted fight, 满月女王 = Full Moon Queen / phase-1 form).
  The 雕像 statue rule is already in place; extending to other markers
  would tighten coverage.
- A script that reads the spoiler from a playtest run and flags any
  placed NPCParams that aren't already in the avoid set as
  potential post-hoc audit candidates.

Filed forward as v0.23.21+ work.

---

## v0.23.19

### Cinematic Chaos — GUI exposure landed

The `chaos_mode` engine flag has been in the codebase since v0.23.11, but
the GUI never exposed it — only programmatic API access (`cmd_shuffle_v3
(..., chaos_mode=True)` or `dcx_batch.rando_pipeline(..., chaos_mode=
True)`) could turn it on. v0.23.19 closes the loop.

**Recap of what chaos_mode does** (engine logic itself unchanged from
v0.23.11): asymmetric NB-tier gating. When ON, two simultaneous shifts
in `pick_target_cp`:

- At non-NB slots, the `pool - V3_NIGHT_BOSS_ONLY_TARGETS` subtraction
  is **lifted** — true Night Boss chrs (Margit, Maliketh, Astel,
  Promised Consort Radahn, Midra, etc.) become eligible to land at
  field-boss / overworld slots.
- At NB-arena slots, the gate **tightens** from
  `V3_NIGHT_BOSS_CALIBER_TARGETS` (the broader set including field-tier
  giants) down to `V3_NIGHT_BOSS_ONLY_TARGETS` (the strict purpose-built
  arena subset). Field-tier giants can no longer leak UP into Night
  arenas.

The asymmetry is the point — Night 1 / Night 2 stay strict-epic; the
day expedition gets cinematic ambushes.

### GUI plumbing

Four touch points in `oops_rando_gui.py`:

1. `chaos_mode_var = tk.BooleanVar(value=False)` declared next to
   the other run-flavor BooleanVars in `__init__`.
2. New "Run flavor" `LabelFrame` on the main Generate tab,
   immediately above the Randomize button, hosting the
   "Cinematic Chaos — Night Boss chrs spawn at field slots"
   checkbox plus a 5-line dim-label description explaining the
   asymmetric flow.
3. `'chaos_mode': bool(self.chaos_mode_var.get())` added to the
   config dict alongside `cluster_aware` / `merchant_model_swap`.
4. `chaos_mode=bool(config.get('chaos_mode'))` added to the
   `engine_kwargs` dict so both the DCX path
   (`dcx_batch.rando_pipeline`) and the direct path
   (`oops_v3.cmd_shuffle_v3`) receive the flag. Both functions
   already accepted the kwarg from v0.23.11 — no engine changes
   needed.

A banner print fires when chaos_mode is ON so runs explicitly announce
what flavor they're producing — same pattern as the existing
`multiplayer_safe` / `disable_resilient_filter` / diagnostic-batch
banners.

### Where it lives + why

The toggle is on the main Generate tab, breaking the v0.19.27 "compact
main tab" convention that put `cluster_aware` / `merchant_model_swap`
behind programmatic-only access. The reasoning: those niche toggles
have defaults that are right for almost everyone, so hiding them
preserved UX cleanliness without sacrificing real choice. `chaos_mode`
is fundamentally different — it's a deliberate gameplay-character
choice users will actively want to discover and toggle, not a
power-user knob with a calibrated default. Burying it on a subtab
would undersell the feature.

---

## v0.23.18

### heritage_pack.json — empirical v2 manifest

User ran `dev/audit_vanilla_chr.py` against a vanilla NR install (209
prefixes) and a modded me3 profile chr/ (250 prefixes), then `--diff`'d
the two. Diff: 141 in both, 68 only in vanilla, 109 only in modded.

`heritage_pack.json` rebuilt from the empirical data. Selection rule:
**c-prefix in `nr_enemy_tags.json` AND only-in-modded AND not declared
by `bfer_imports.json` / `bfer_imports_v2.json`**. Result: 41 entries
(up from v1's 36 heuristic entries).

`_meta.confidence` upgraded from `heuristic_v1` to `empirical_v2`.

**Net additions** (not in v1, confirmed empirically): c2272 Giant Black
Crab, c3670 Aged Albinauric, c4341 Thin Mad Pumpkin Head, c4352 Cuckoo
Knight (Scholar Remembrance), c4561 Bloodbane Giant Crow, c4603
Stonedigger Troll, c5190 / c5192 / c5193 Spider Scorpion variants, c5522
/ c5523 Stray variants.

**Net removals** (in v1's conservative-add list but turned out to be in
vanilla NR's chr/): c5240 Commoner (Pot), c5241 Commoner, c5311
Inquisitor (Candles), c5312 Inquisitor (Staff), c5750 Living Jar Warrior,
c5751 Living Jar. v1 had pattern-matched these as SOTE-flavored from
their c-prefix range; vanilla NR actually ships them. Heuristic
false-positives that empirical data corrected.

**Collision noted, kept**: c3330 Giant Silver Tear (Unscaled) is in both
`heritage_pack.json` (Heritage Pack ships it) and
`V3_EXCLUDE_TARGET_PREFIXES` (excluded from placement since v0.23.11
because shape-shifting mimics have no valid mimic-target at random NR
slots, render as broken meshes). The two systems are orthogonal — pack
membership describes "where the chr file comes from", placement-exclusion
describes "we never place this chr". Both correct, both kept.

### Phantom set re-validated

Empirical diff confirms the v0.23.15 phantom exclusion list (c4021,
c4181, c4641) for the user's setup. c4641 is genuinely absent from both
vanilla NR and the modded chr/ folder. c4021 and c4181 are absent from
modded but present in vanilla NR — whether me3's overlay falls back to
vanilla for chr files is the question their post-v0.23.15 playtest
indirectly answers (no further CTDs of the same class reported, so
exclusion stays). No new phantoms detected from this audit.

### TODO carried forward

- `vanilla_promotions_v1.json` premise needs an audit. v1 entries c4441
  Land Squirt (Unscaled), c4442 (Unscaled, variant), and c4502 Flying
  Dragon (Unscaled, variant) are tagged as "vanilla NR promotions" but
  are empirically absent from the vanilla NR chr/ folder — they're in
  the modded folder only. Either v1's premise was wrong for these
  specific chrs (they're heritage-pack content mistagged as vanilla),
  or the user's FIA profile happens to bundle them. Defer to a
  dedicated audit pass.

---

## v0.23.17

### Fixed: 1hp Beast Clergyman class — BFER scripted/cinematic variants

User playtest report: "saw a 1hp Beast Clergyman night 1." Spoiler analysis
located the placement at m48_10 (Night 1 NB arena), where c2110 Maliketh
(BFER) was assigned NPCParam variant **21109042**. The 9xxx suffix range
in FromSoft's NpcParam convention encodes scripted/cinematic state — for
phase-locked bosses, those rows are typically the phase-1 form (Beast
Clergyman → Maliketh) hardcoded at 1hp because the phase transition is
supposed to fire on a hit-detect cutscene. The cutscene doesn't trigger
at random NR slots, so the rando produced a 1hp idle boss instead of a
combat encounter.

Audit pass surfaced **19 suspicious variants** across BFER's manifest:

- **13 Margit (c2010) 9xxx variants** — Stormveil castle script states,
  including the friendly-NPC variant ("狼哥友好") and main-castle event
  state ("狼哥主城"). These are story-event-locked and don't function as
  random combat placements.
- **3 Maliketh (c2110) 9xxx variants** including the user-reported 9042
  (Beast Clergyman 1hp) and a 1073 arena statue ("黑剑竞技场雕像").
- **Malenia (c2120) 9000** — Blade-of-Miquella → Goddess-of-Rot phase form.
- **Melina (c2180) 9000** — friendly-NPC scripted variant (twice-placed in
  the playtest spoiler). Melina is non-hostile by default in vanilla; the
  9000 variant carries that state.
- **Midra (c5051) 0002** — arena statue ("米德拉竞技场雕像"), decoration.

All 19 added to `V3_AVOID_VARIANT_NPC_IDS` (extending the v0.20.86
mechanism originally written for c7100 ghost-render avoidance). The
variant-picker prefers non-avoid-listed variants but falls back if a
c-prefix has no alternatives — for c2110 and the others, BFER ships
multiple variants, so the avoid set steers selection without losing the
chr from the placement pool.

Detection pattern documented in `dev/audit_bfer_variants.py` for re-runs
when BFER publishes new variant manifests:

  - npc_param_id where `(id % 10000) >= 9000` AND c-prefix in the
    phase-locked BFER set {c2010, c2050, c2110, c2120, c2180, c2190,
    c2200, c5220}
  - OR `mmv_name` contains 雕像 (Chinese for "statue")

Audit script also reads V3_AVOID_VARIANT_NPC_IDS back from oops_v3.py to
verify coverage — exits non-zero if any suspicious variant has slipped
in unannounced.

---

## v0.23.16

### heritage_pack.json — first-pass manifest for SOTE-flavored chrs

Closes the structural gap flagged in v0.23.14 / v0.23.15: the chr/
Inventory tab status panel could only enumerate declared asset packs (BFER
v1/v2, vanilla_promotions, deprecated er_heritage_imports), but base
`nr_enemy_tags.json` references ~89 c-prefixes that vanilla NR does not
place via MSBs. Many of those need an external Heritage Pack mod to ship
as actual chr files. Without a manifest, users without Heritage Pack got
silent CTDs with no proactive warning — Diagnose-against-spoiler caught
them after the fact, but the panel said nothing at install time.

`heritage_pack.json` is now registered in `KNOWN_PACKS` and ships 36 tagged
c-prefixes:

- **20 high-confidence** entries promoted from `_source: heritage` tags
  already present in `nr_enemy_tags.json`. Examples: Cleanrot Knight,
  Death Knight, Gravebird, Divine Beast Dancing Lion, Messmer Soldier,
  Ghostflame Dragon, Man-Fly, Disciple of Rot, Giant Crayfish, Omenkiller,
  Avionette, Warhawk, Goat.
- **16 conservative additions** from the `_source: <none>` bucket where
  the c-prefix is in the SOTE-flavored c50xx-c58xx / c60xx range and the
  name is unambiguously SOTE: Bloodfiend, Chief Bloodfiend, Fire Knight,
  Curseblade, Inquisitor variants (Candles/Staff/Fat), Living Jar +
  Living Jar Warrior, Great Red Bear, Imp (Lion Head), Bear, Mohg the Omen,
  Horned Warrior, Commoner + Commoner (Pot).

Marked `_meta.confidence: heuristic_v1`. The remaining 25 ambiguous chrs
(Bloodbane Giant Crow c4561, Stonedigger Troll c4603, Spider Scorpion
variants, c8911, etc.) are left out of this pass — without empirical
chr-file evidence they could be vanilla-NR-but-unplaced rather than
heritage-pack-only, and false-flagging would cause spurious "missing
Heritage Pack" warnings for users who have nothing wrong.

### dev/audit_vanilla_chr.py — empirical refinement tool

Standalone script for upgrading `heritage_pack.json` from heuristic to
empirical. Takes a `--chr-dir` path, walks the directory once, emits a
JSON listing of c-prefixes present (detected by chrbnd / anibnd / behbnd /
texbnd file presence — same permissive rule as the Inventory tab's
`detect_asset_packs`). Run twice — once on a vanilla NR install, once on
a modded me3 profile chr/ — then `--diff` the two outputs to identify
the optional-pack contribution (heritage + BFER + etc.) authoritatively.

The script is purely diagnostic — no decompression, no parsing, just
file presence by name. The output JSON feeds future heritage_pack v2
authoring (where ambiguous c-prefixes get classified by direct evidence
rather than name pattern).

### chr/ Inventory tab — Diagnose / Dry-run / Import buttons hoisted

Action buttons block was below the Asset packs status panel, where users
couldn't find them at a glance — a few chats with the maintainer kept
ending in "use the Diagnose button" but the user couldn't see it without
scrolling. Three changes:

1. **Reordered**: Actions block now sits directly after the Paths frame,
   before Asset packs. Workflow visually: pick paths → click action →
   read asset pack status as supporting context.
2. **Restyled**: All three buttons widened to 14ch, padded with `ipady=2`,
   row spacing increased. Reads as a CTA row rather than a footer.
3. **Diagnose promoted to Accent style**. It's the primary diagnostic
   action — runs against a spoiler and tells the user which c-prefixes
   are missing on disk. This is exactly what surfaced the v0.23.15
   model-variant phantom CTD class. Import retains its Accent style
   (final/destructive step indicator).

---

## v0.23.15

### Fixed: model-variant phantom CTDs (c4021, c4181, c4641)

Three c-prefixes have been promoted to `V3_EXCLUDE_TARGET_PREFIXES`. The
tagger surfaced them as standalone placeable chrs from chrModelParam /
NpcParam / cluster-shape rows, but their `.chrbnd.dcx` files don't actually
ship with vanilla NR (verified via the chr/ Inventory tab Diagnose flow:
target chr/ folder had 250 prefixes on disk, the spoiler required 197, of
which exactly these three were missing). Cross-checked against an unpacked
ER chr/ folder — also absent there. They're behbnd-internal model variants
of their parent c-prefix, not independent chrs.

This is a third chr-availability failure mode beyond "user needs Heritage
Pack" and "user needs BFER" — these chrs **aren't anywhere**, regardless
of mod setup. Any user who triggered cell-load on a tile hosting one of
them was getting CTDs that no asset-pack install could fix.

The three:

- **c4021** — Royal Revenant (variant). Was in `V3_FRAGILE_SENSITIVE_TARGETS`
  + `V3_NIGHT_BOSS_CALIBER_TARGETS` (NB-arena eligible). Spoiler 726484
  placed it 5x across m46/m49/m60 cells.
- **c4181** — Maris' Jellyfish. Was in `V3_FRAGILE_SAFE_CONFIRMED` (positively
  listed for fragile slots) AND `_FI_CPS_RESERVED_FOR_TARGET` (force-included
  diagnostic). Spoiler 726484 placed it 11x, including 6 in the m34_xx
  Rotting Woods cluster — matches the v0.23.12 spoiler 412746 "Rotting Woods
  Day 2 CTD" exactly. Highest impact of the three.
- **c4641** — Tree Spirit (Unscaled, variant). Was in `V3_UNIQUE_TARGET_CAPS`
  with cap=1; vanilla_promotions_v1 entry. Single-placement lurker — only
  crashes if the user actually traverses the cell hosting that one
  placement, so the v-promotions origin had survivorship-bias coverage.

**Defensive-cleanup interaction.** `_FI_CPS_RESERVED_FOR_TARGET` had c4181
in it from the v0.20.3 stale-pyc-detection era, where the module-load
cleanup loop actively *un-excludes* anything in the reserved set from
`V3_EXCLUDE_TARGET_PREFIXES`. Adding c4181 to excludes without dropping it
from the reserved set would no-op — same trap v0.20.69 hit when promoting
c5110. Resolved the same way: c4181 removed from reserved set with v0.20.69-
style commentary linking the two events. c3610 (Oracle Envoy) and c3620
(Oracle Envoy Cathedral) remain reserved — those are vanilla NR placed
chrs and ship correctly.

### chr/ Inventory tab — resizable Output pane (slider)

`_build_chr_inventory_tab` is now a vertical `ttk.PanedWindow` with controls
in the top pane and the Output log in the bottom pane, separated by a
draggable sash. The v0.23.14 Asset packs panel pushed cumulative content
height enough that the Output log dropped below the fold on shorter
windows — the user couldn't see Diagnose results without resizing the
window.

Sash placement: deferred 60ms after first paint, set to ~66% from top so
the Output log is visible from launch. Resize weights are 2:1 (controls
get more of any window-grow space, log keeps its initial proportion until
the user drags the sash). chr_log retains its `height=14` ScrolledText
default; PanedWindow lets the user opt into more.

Pattern note: the main tab uses Canvas+Scrollbar (added v0.19.27 for the
same too-tall problem). Different solution chosen for the chr/ Inventory
tab because the use case is different: main tab wants "scroll down to find
controls below the fold" (read-only navigation), chr/ Inventory tab wants
"give the Output log more area to actually read it" (which a scrollable
canvas doesn't help with — the log would still be 14 lines tall, just
scrolled-into-view).

---

## v0.23.14

### Asset pack detection (chr/ Inventory tab)

New "Asset packs" status panel in the chr/ Inventory tab. Scans the
user's target chr/ folder against each loaded asset pack's c-prefix
manifest and reports per-pack detection status:

```
Asset packs
  ✓ Boss for Elden Ring (BFER) v1: 30/30 chr-prefixes
  ✓ BFER v2 (Greyoll, Troll variant, size_class overrides): 2/2 chr-prefixes
```

Or when missing:

```
  ✗ Boss for Elden Ring (BFER) v1: 0/30 chr-prefixes  (https://...)
        missing: c2010, c2031, c2050, c2110, c2120 (+25 more)
```

Auto-refreshes when the user picks a new Target chr folder via the path
picker. Manual refresh button covers other cases (path edited by hand,
mod files added/removed externally). Filtered to only show packs that
require external chr files (i.e. the ones where missing assets cause
cell-load CTDs); skips vanilla_promotions_v1 since those chrs ship with
the base game, and skips disabled packs.

The detection logic is in a new top-level engine function
`detect_asset_packs(target_chr_dir)` so other tools (CLI, future
spoiler-side warnings) can reuse it. Pack metadata (user-facing name,
URL, requires-external flag) is read from each JSON's `_meta` block
where present, with KNOWN_PACKS fallbacks for files that predate the
convention.

Detection rule: a c-prefix is "detected" if any chr file matching that
prefix exists in the target dir (chrbnd, anibnd, behbnd, OR texbnd).
Permissive on purpose — NR sometimes ships only anibnd standalone while
the chrbnd lives in a packed bundle. Conservative detection would
false-flag every chr.

### README — optional dependencies section

New section explaining that the rando is functional with vanilla NR
alone, with BFER as the optional dependency for ER+SOTE bosses (link
to Nexus mod 422). Disabling instructions for users who don't want
optional content.

The deprecation note for `er_heritage_imports.json` is now also in the
README's file manifest, pointing at `dev/BFER_AUDIT.md` for the
structural reasons it was disabled (no Bullet/SpEffect rows shipped,
chr file dependency was implicit/contaminated).




### bfer_imports_v2.json — Greyoll + Troll variant + size_class realignment

Acting on the v0.23.12 BFER audit findings (`dev/BFER_AUDIT.md`).

**2 high-confidence boss-tier additions:**
- **c4504 Greyoll, Dragon of Caelid** — bvId=45000 matches Flying Dragon
  family; geometry h=42 r=17 hp=12440 is the only chr in ER big enough
  for that profile (the colossal sleeping dragon). Tagged GIGA
  flying_dragon nightlord, added to caliber + strict-NB sets.
- **c4601 Troll Variant** — bvId=46000 matches c4600 Troll family;
  geometry h=7.2 r=1.8 hp=1901 matches NR's c4600 exactly. Likely an
  SOTE Troll variant or Headless Troll re-skin. Tagged XL humanoid
  field_boss, added to caliber.

**97 size_class overrides applied to vanilla NR overlap chrs.** Vanilla
NR's tagger used looser thresholds than ours, classifying many boss
chrs as larger than their actual hitbox geometry warrants. Example:
c2130 Margit at h=3.6 r=0.9 was tagged XL but is geometrically M-tier
under our consistent thresholds. forget909's BFER independently
classifies him at the same M scale, validating the formula.

Transition matrix:
- L → M:    28 chrs (Margit-tier humanoids)
- XXL → XL: 20 chrs (large bosses one tier oversized)
- XL → L:   19 chrs
- XL → M:   10 chrs
- S → M:    10 chrs (small chrs that were undersized)
- XXL → L:   5 chrs
- M → S:     3 chrs
- XXL → GIGA: 1 chr (one chr was actually undersized!)
- XS → S:    1 chr

Notable shifts:
- Margit (c2130): XL → M
- Tree Sentinel (c3251): XL → M
- Funeral Steed (c3160): XL → M
- Giant Crab (c2270): XL → L
- Giant Death Crab (c2276): XXL → L
- Silver Tear (c3320): S → M

The shift is systematically toward smaller classifications. This means
chrs like Margit now compete in the M humanoid pool (against Bell
Bearing Hunter, banished knights, etc.) rather than the XL pool with
Tree Sentinels and Trolls. Better matches actual encounter scale.

Override scope is narrow: only OVERLAP c-prefixes (in both NR roster
AND BFER NpcParam), only where size_class differs. Does not touch chrs
BFER doesn't have (no second opinion = leave alone). Does not touch
chrs already authored in bfer_imports.json v1.

Each overridden tag carries `_size_overridden_by: bfer_imports_v2`
and `_size_was: <previous>` for forensic clarity.

**Engine state:**
- roster: 1196 → 1202 (+6 from c4504/c4601 variants)
- tags: 279 → 281 (+2)
- V3_NIGHT_BOSS_CALIBER_TARGETS: 77 → 79 (+2)
- V3_NIGHT_BOSS_STRICT_TARGETS: 9 → 10 (+1)
- V3_HERITAGE_ALL_PREFIXES: 82 → 84 (+2)

To revert: set `_meta.enabled=false` in bfer_imports_v2.json or
delete the file entirely. v1 stays unaffected.




### bfer_imports.json — Boss for Elden Ring asset pack integration

Integrated forget909's "Boss for Elden Ring" mod
(`nexusmods.com/eldenringnightreign/mods/422`) as a third-party asset
pack. BFER imports 30+ ER and SOTE bosses into Nightreign with
authentic chr files, behavior chains, intro scripts, etc. Our role:
recognize their c-prefixes, place them at appropriate slots.

This is a **strategic shift** away from authoring chrs from scratch
(`er_heritage_imports.json` was the proof-of-concept) toward
treating other mods as authoritative asset sources. We focus on
randomization; they focus on import work.

**30 high-confidence boss tags added.** All named in BFER's NpcParam
(Chinese names translated), geometry-classified from hitbox medians,
anim_class hand-curated by chr family.

Headliners new to the rando — chrs we previously had no path to:
- c5051 Midra, Lord of Frenzied Flame (humanoid M)
- c5200 Metyr, Mother of Fingers (large_boss_ground GIGA)
- c5120 Bayle the Dread (flying_dragon GIGA, nightlord-tier)
- c4760 Fire Giant (giga_boss GIGA, nightlord-tier)
- c4520 Placidusax (giga_boss GIGA, nightlord-tier)
- c4710 Rykard, Lord of Blasphemy (giga_boss GIGA, nightlord-tier)
- c2200 Elden Beast (giga_boss GIGA, nightlord-tier)
- c5030 Romina, Saint of the Bud (humanoid L)
- c5130 Messmer the Impaler (humanoid)
- c5170 Wicker Man / Furnace Golem (giga_boss GIGA, nightlord-tier)
- c5230 Scadutree Avatar (large_boss_ground XL)
- c5220 Promised Consort Radahn (humanoid M)
- c5020 Putrescent Knight (quadruped_large M)
- c5000 Commander Gaius (quadruped_large M)
- c4730 Starscourge Radahn (quadruped_large XL)
- c4511 Lichdragon Fortissax (flying_dragon GIGA)
- c4720 Godfrey + c4721 Hoarah Loux Warrior (humanoid)
- c2180 Melina (humanoid M)
- c2050 Ranni (humanoid M, was wrongly tagged Radagon in er_heritage_v1)
- c5300 Twin Moon Knight, c4604 Strategist Iji, c5840 Black Knight, etc.

**Engine integration:**
- Loader follows the `er_heritage_imports.json` / `vp_v1.json` pattern.
  `_meta.enabled=true` by default; flip to `false` to disable without
  deleting the file.
- Auto-additions to `V3_NIGHT_BOSS_CALIBER_TARGETS` (+26 entries) via
  the JSON's `include_in_caliber_set` array — boss-tier chrs eligible
  for true NB anchor placement.
- Auto-additions to `V3_NIGHT_BOSS_STRICT_TARGETS` (+8 entries) via
  `include_in_strict_nb_set` — geometric-too-big chrs (Bayle,
  Fortissax, Placidusax, Rykard, Fire Giant, Elden Beast, Wicker Man,
  Starscourge Radahn) restricted to true Night Boss anchor slots only.
- Auto-additions to `V3_HERITAGE_ALL_PREFIXES` (+30 entries) — BFER
  chrs need the BFER mod's chr files installed, so multiplayer_safe
  mode gates them to prevent coop CTDs.

### er_heritage_imports.json deprecated

`er_heritage_imports.json` was authored as a from-scratch proof of
concept in v0.23.11. With BFER integrated, it's now redundant and
contains 3 wrong c-prefix→chr mappings caught only via collision
audit:

```
c2050: er_heritage_v1 said Radagon, BFER says Ranni     ← er_v1 WRONG
c2190: er_heritage_v1 said Godrick, BFER says Radagon   ← er_v1 WRONG
c2200: er_heritage_v1 said Godfrey, BFER says Elden Beast ← er_v1 WRONG
```

I had guessed at c-prefix assignments based on conventions; BFER
ships actual chr files at those c-prefixes, making it authoritative.
The wrong mappings would have produced placement issues if anyone
had matched chr files to my er_heritage_v1 tags.

`er_heritage_imports.json` set to `_meta.enabled=false` by default
with a deprecation note pointing to BFER. Re-enable only if BFER is
NOT installed (e.g., for fallback testing of the template-inheritance
authoring path).

The c2160 Astel placement that empirically worked in your v0.23.11
playthrough did so because BFER was already on disk — your seed was
picking up Astel from BFER's chr files, not from my synthetic
template-inheritance authoring. Good news: validates BFER as a
working asset source. Less-good news: er_heritage_v1's authoring
approach was never actually tested in isolation.


 — Cleanup + ER heritage imports + chaos mode

Three landings, primarily a major cleanup of failed experimental work, plus
two new feature additions.

### Cleanup of expunged experimental work

Removed ~21 files and 232 variants tied to the failed MMV import attempt,
the chr_restore_v1 ER/SOTE blanket-copy attempt, the forget909/Tier B
boss mod attempt, and the dormant_imported Tier A. Net effect on the
roster: 1166 → 963 variants, 270 → 237 tags. Engine-side: removed
`V3_MMV_ALL_PREFIXES`, `_load_mmv_prefixes`, mmv chrbnd-remap entries
(c4601, c2110), all `V3_DIAGNOSTIC_*ROMINA*` constants and three
injection blocks, forget909 commented-out heritage extension blocks,
dormant uniqueness cap entries. GUI: removed MMV tab, heritage scanner
subtab (~401 lines bulk-deleted), `__SCAN_DONE__` log branch, scanner
StringVars; flattened heritage tab.

The diagnostic Romina injection in particular was identified as a
potential CTD source — it placed an XXL chr at non-arena slots
unconditionally. Its removal eliminates one class of cell-load CTDs.

### ER heritage imports v1 — c2xxx Night-Boss-tier batch

New `er_heritage_imports.json` adds 12 ER NB-tier bosses whose chr
files NR ships in `chr/` but whose NpcParam rows vanilla NR omits.
Tags + 24 synthetic variants authored with `_source: "er_heritage_v1"`.
The chrs: c2010 Margit, c2030/c2031 Rennala P1/P2, c2050 Radagon,
c2060 Mohg LoB, c2110 Maliketh, c2120 Malenia, c2131 Morgott P2,
c2160 Astel (empirical anchor — confirmed working in playtest),
c2190/c2191 Godrick + P2, c2200 Godfrey/Hoarah Loux.

Engine plumbing: new `V3_TARGET_ONLY_SOURCES = {'script_spawn', 'er_heritage_v1'}`
near `V3_HUB_MAPS`. Replaced two hardcoded `_source == 'script_spawn'`
checks with frozenset-membership checks. New loader after manual_promotions
in `load_data()`.

Companion CSVs at `dev/er_heritage_csvs/`: 24 NpcParam rows + 12
NpcThinkParam rows authored by template-inheritance from same-family
NR analogs (Morgott c2130, Godrick c4750, Astel c4620). All synthetic
IDs collision-free against vanilla NR. Smithbox-importable; format
matches Smithbox's exact CSV quirks (trailing-comma header, naive
comma-split data parsing, no quoted fields).

The 12 c2xxx chrs are also added to `V3_HERITAGE_ALL_PREFIXES` so
`multiplayer_safe` mode properly gates them. Same risk profile as
heritage_pack chrs — host placing one of these CTDs any coop client
that doesn't have the ER chr assets locally. Set went from 47 → 59
entries.

### Chaos mode — asymmetric tier mixing

New `chaos_mode` parameter on `cmd_shuffle_v3` (default False). When
True: the `pool - V3_NIGHT_BOSS_ONLY_TARGETS` subtraction at non-NB
slots is lifted (true Night Boss chrs leak DOWN to field-boss /
overworld slots), AND the NB-slot intersection tightens from
`V3_NIGHT_BOSS_CALIBER_TARGETS` (broad — includes field-tier giants)
to `V3_NIGHT_BOSS_ONLY_TARGETS` (strict — only true NB-arena bosses,
field bosses can't leak UP). Result: one-way flow, NBs roam the
world, field bosses can't dilute NB anchor moments.

### Target exclusions — Silver Tear (c3320/c3330), c7580 unknown

Three c-prefixes added to `V3_EXCLUDE_TARGET_PREFIXES` (now 22 entries
total) based on playtest reports.

**c3320 Silver Tear (Unscaled) + c3330 Giant Silver Tear.** User
reported visual glitching at randomized slots. Silver Tears are ER
shape-shifting mimics whose default behavior is to identify a
nearby chr/player and morph into a copy of it. The transform-target
identification is tied to ER's specific area scripts (Nokron Eternal
City, Sellia Crystal Cave); at NR randomized slots there's no valid
mimic anchor, so the chr renders as a broken/incomplete mesh. Mimic
behaviors are categorically risky for rando — the "what to look
like" data is event-script-bound rather than chr-bound.

**c7580 (unknown).** Empirical anchor for a deeper-than-expected
classification bug. The tag had `_unknown: True` (scanner flagged
identity unknown), `name: 'c7580'` (no human name), `hp_max: 0`,
`anim_class: misc`, `expects_boss_arena: False` — clearly a
non-combat NPC. But also `tier: 'nightlord'` (highest boss-strength
classification), which passed every tier filter and let it compete
at NB anchor slots.

User playtest report: c7580 replaced a Bell Bearing Hunter NB anchor,
didn't aggro, died in 1 hit, visually resembled Two Fingers / Metyr
(decorative companion NPC). Almost certainly a NR Recluse-summon /
companion-NPC model that an earlier scanner mis-classified as a
nightlord. Until we identify what c7580 actually is and whether it
has any legitimate combat variant, full target exclusion.

**Why excluded vs gated:** Tagging fix would require diagnosing the
scanner's tier-inference rule that produced the bad classification
in the first place; doing that without breaking other untyped-chr
edge cases needs more careful work. Excluding target-side now stops
the in-game symptom while leaving the source-side untouched (any
vanilla c7580 placements stay vanilla).




User-reported issue from seed 999846 spoiler audit: only 2 of 12 ER
heritage v1 chrs landed (c2030 Rennala P1, c2060 Mohg LoB). The other
10 were silently absent from every shuffle since v0.23.11 release.

Two root causes identified:

**Missing `tier` field on all 12 entries.** When I authored
`er_heritage_imports.json`, each tag included anim_class, size_class,
hp, expects_boss_arena, etc. — but no `tier` field, so it defaulted
to `None`. The tier-preservation filter in `pick_target_cp` then
intersected the pool with `V3_BOSS_STRENGTH_TIERS` at every boss-tier
source slot, and `tier=None` chrs got filtered out at the very slots
they were authored to land at. The 2 placements that did succeed
slipped through via the defensive `if tier_pool: pool = tier_pool`
fallback when intersection produced edge cases — and one of those
(Rennala at a Godrick Foot Soldier slot) was actually off-tier.

Fix: added `tier: "field_boss"` to all 12 ER heritage v1 tags.
field_boss is in `V3_BOSS_STRENGTH_TIERS` (alongside night_boss /
miniboss / nightlord), so the tier filter now accepts them at any
boss-strength source slot. field_boss chosen over night_boss because
it's slightly more permissive — they'll appear at NB AND field-boss
arena slots, with the NB caliber gate handling NB-anchor steering
from the source side.

**Not in `V3_NIGHT_BOSS_CALIBER_TARGETS`.** The caliber gate is a
source-side restriction at NB anchor slots — when the source variant
carries a Night Boss marker, the pool intersects with the caliber
set. ER shardbearers + late-game NB-tier bosses are textbook caliber
material (full movesets, plot intro cinematics), but I'd missed
adding them. Result: even after the tier fix, they'd be subtracted
from the pool at every true NB anchor slot.

Fix: added all 12 to `V3_NIGHT_BOSS_CALIBER_TARGETS` (set grew 46 →
58 entries).

Both fixes applied. ER heritage v1 chrs now compete at:
- All boss-strength source slots (tier filter accepts them)
- True NB anchor slots specifically (caliber gate accepts them)
- All MSBs that don't have anim_class incompatibility / fragility issues

Expected outcome next run: 12 chrs each landing 5-15 times depending
on RNG. Astel (c2160) is the empirical anchor — confirmed working in
prior playtest, so any other ER heritage chr that lands and works
visually validates the entire batch.




`vanilla_promotions_v1.json` adds 8 chrs whose NpcParam +
behaviorVariationId chains exist in vanilla NR's regulation but
weren't surfaced by the MSB-scan-driven roster build (they have
no vanilla MSB Parts, so the scanner never saw them). These need
**only tagging** to enter the rando — no Smithbox CSV imports
required, in contrast to `er_heritage_imports.json` (c2xxx ER
bosses) which needed authored CSV rows because the regulation
data didn't exist.

**High-confidence (named, multi-variant — safe to ship):**
- c3360 Ancestral Follower (M humanoid miniboss, HP 316)
- c3370 Ancestral Follower Shaman (M humanoid miniboss, HP 450)
- c4190 Large Scarab (S quadruped grunt, HP 213)

**Medium-confidence (unnamed in NpcParam, geometry-clear):**
- c4192 Large Scarab variant (M quadruped grunt)
- c4441/c4442 Land Squirt (Unscaled) variants (XL large_boss_ground field_boss)
- c4502 Flying Dragon (Unscaled) variant (GIGA flying_dragon field_boss)
- c4641 Tree Spirit (Unscaled) variant (GIGA large_boss_ground field_boss)

Boss-tier promotions (c4441, c4442, c4502, c4641) added to
`V3_UNIQUE_TARGET_CAPS` at cap=1 — prevents flooding pre-playtest
and gives each a quality reservation slot. If broken, the
reservation stays vanilla (fail-safe). Increase caps after
playtest confirms each is well-behaved.

Roster grew 1008 → 1023 (+15 variants). Tags grew 253 → 261 (+8).

Removal: set `_meta.enabled=false` in vanilla_promotions_v1.json
or delete the file. `_source: "vanilla_promotions_v1"` flag on
each entry makes the batch greppable.




User-reported issue from seed 711300: c4510 Ancient (Lightning) Dragon
landed at "Miranda Blossom (Field Boss)" slot at m46_71 pi=1 and was
geometrically unplayable — the Field Boss arena couldn't accommodate
the dragon's wingspan + tail, leading to terrain collision and AI
breakage.

Root cause: `V3_NIGHT_BOSS_NAME_MARKERS` is **broad** — accepts Night
Boss, Field Boss, Castle Boss, Fort Boss, Ruins Boss, (Crater),
(Noklateo), and Remembrance markers. So `V3_NIGHT_BOSS_ONLY_TARGETS`
chrs (which use that marker list) can land at any of those slot types,
not just true Night Boss anchors. For most chrs this is fine — Castle
Boss / Fort Boss / Ruins arenas still have boss-tier geometry. But for
the largest GIGA flyers (Ancient Dragon), even a Field Boss arena is
too small.

New tier added: `V3_NIGHT_BOSS_STRICT_NAME_MARKERS = ['Night Boss']` —
the tightest gate, just the literal "Night Boss" string. Companion
target set `V3_NIGHT_BOSS_STRICT_TARGETS` currently contains just
c4510 Ancient Dragon. Gate fires in `pick_target_cp` after the
NIGHT_OR_FIELD_BOSS gate, and is mirrored in `_score_slot_for_unique`
so the cap-reservation pre-pass also respects it.

NOT chaos_mode-overrideable. Geometric constraint, not thematic —
chaos lifts at the NIGHT_BOSS_ONLY tier (Field/Castle Boss tier-mixing
is fine for variety) but the strict gate stays firm because Ancient
Dragon at Field Boss = terrain CTD regardless of chaos preference.

Hierarchy now:
- `V3_NIGHT_BOSS_NAME_MARKERS` (broadest, 8 markers): Night/Field/Castle/Fort/Ruins Boss + Crater/Noklateo/Remembrance — gates `V3_NIGHT_BOSS_ONLY_TARGETS`
- `V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS` (2 markers): just Night Boss + Field Boss — gates `V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS`
- `V3_NIGHT_BOSS_STRICT_NAME_MARKERS` (1 marker): just "Night Boss" — gates `V3_NIGHT_BOSS_STRICT_TARGETS`




Two related fixes to the unique-target-cap reservation pre-pass.

**c4480 Miranda Blossom dropped to cap=1.** At cap=2, the reservation
pre-pass scored two specific slots highest every run (m30_30 pi=45
Guardian Golem Fort, m38_00 pi=51 Guardian Golem Cathedral) and locked
both in regardless of seed — Miranda always landed at the same two
interior fragile slots, producing the "standup Guardian Golem always
becomes Miranda Blossom" pattern. Reducing to cap=1 frees one of those
slots for the general boss-tier pool. Miranda still gets a reserved
quality slot, just one instead of two.

**Cap-allocation order randomized within tier.** Previously the
reservation loop processed capped c-prefixes in
`(cap, c-prefix-alphabetical)` order — meaning all cap=1 chrs went
in alphabetical order (c4500 → c4501 → c4503 → c4510 → c4640 → c4680
→ c4910 → c4911), then all cap=2 chrs alphabetical. The deterministic
order meant capped chrs with overlapping ideal-slot pools always got
the same allocation: c4500 always claimed its top slot first, c4501
got second-pick from what's left, c4503 third, etc. Across many seeds,
the same alphabetically-first chr always won.

Fix: shuffle the cap items via the seeded RNG, then stable-sort by
cap. Within each cap tier, the chr-processing order is now randomized
per seed (still deterministic given the seed), so different chrs
get first pick across runs. Cap=1 chrs still process before cap=2,
preserving the "more-restrictive picks first" design intent.

**Probabilistic top-K reservation selection.** Even after the cap=1
drop and tier shuffle, c4480 was STILL landing at m38_00 pi=51
(Cathedral GG slot) every run because that slot was *uniquely*
top-scored among c4480's compatible slots — once c4480 got its turn
to reserve, the greedy `scored[0]` picker locked that slot in.

Root cause: `scored.sort(...); first_slot = scored[0]` is strictly
greedy. The rng-tiebreak only helps when multiple slots share the
top score.

Fix: pick weighted-random from the top-K candidates within
SCORE_TOLERANCE=5 points of the best score. Weight by
`exp(score - best_score)` so higher-scored slots are still strongly
preferred but not deterministic. Captures the "good slot" intent of
the scoring system while breaking the lock-in.

Empirical distribution across 100 seeds for c4480 (3 score-13 slots,
2 score-10 slots, 1 score-3 slot):
- Old (greedy):   100% → top slot
- New (top-K):    38% / 30% / 30% / 2% / 0% / 0% — top-tier still wins 98%, but spread

SCORE_TOLERANCE=5 chosen because typical scoring increments are 3
(size_class XL+), 5 (NB marker), 10 (boss_arena) — 5 captures
"within one major bonus" of the top.



New `dev/heritage_chr_import.py` standalone tool + GUI integration. The
problem it solves: the rando places heritage chrs (Bloodfiend, Curseblade,
Dancing Lion, Imp, Man-Fly, etc.) whose chr files (`cXXXX.chrbnd.dcx` +
sidecars) NR doesn't ship in its base `chr/` folder. Without those files
in the user's me3 profile, every cell containing a heritage placement
CTDs on cell-load.

The tool:
- **Diagnose mode**: read a spoiler JSON, list which target c-prefixes
  are missing from a target `chr/` folder. No source needed.
- **Import mode**: copy missing chr files (full sidecar set per c-prefix —
  chrbnd + anibnd + behbnd + texbnd_h/_l + any `_divNN` divisional
  anims + `_aXX` aux anim banks) from a source game's `chr/` folder
  (typically unpacked Elden Ring) into the target. Idempotent —
  re-runs skip files already present unless `--overwrite`. Threaded
  on the GUI side so large copies don't freeze the UI.

New GUI tab "chr/ Inventory" between Heritage and About. Three path
fields (Source / Target / Spoiler with auto-pick from Output dir),
three buttons (Diagnose / Dry-run / Import), Overwrite toggle, scrolling
log output. Source + Target paths persist across launches via
`.4laric_settings.json` keys `chr_source_dir` / `chr_target_dir`.

Documentation: `dev/HERITAGE_CHR_IMPORT_README.md` (full workflow + ER
→ NR format compatibility notes), `dev/heritage_chr_attribution.json`
(per-c-prefix source-game map for the 47 V3_HERITAGE_ALL_PREFIXES set
plus the 12 c2xxx ER heritage v1 chrs).

Why me3 profile and not vanilla NR install: profile overlays vanilla
files at runtime without modifying them. Uninstall = remove profile,
no residue. Profile is portable. Survives NR patches. The original
"copy heritage chrs into NR install" approach contaminated vanilla
files and broke when NR patched.




Four landings, all aimed at making the rando feel more curated and run faster.

### Per-c-prefix uniqueness caps

New constant `V3_UNIQUE_TARGET_CAPS` — 27 entries — limits how many times
specific c-prefixes can appear across a run. cap=1 for named bosses
(Borealis, Ekzykes, Ancient Dragon, Wyrms, Tree Spirit, Fallingstar
Beast). cap=2 for archetypes (regular Trolls, Crows, Crabs, Fingercreepers,
Hippos, Astel, Mausoleum, Walking Mausoleum, etc.). Eliminates the
"three Tree Spirits in one run" perception and turns rare encounters
into rare encounters.

Implementation: pre-pass scores candidate slots upfront via
`_score_slot_for_unique` (anim_class compat, terrain, MSB class,
shifting-earth disqualification). Best slot per cap unit gets
reserved before the main shuffle runs. Reserved slots commit
directly; all other slots subtract exhausted-cap c-prefixes from
their pool. Vanilla preservation counts toward the cap.

Module-level state: `_V3_UNIQUE_RESERVATIONS`, `_V3_UNIQUE_PLACED_COUNTS`,
`_V3_UNIQUE_UNPLACED_LOG`. Reset via `_reset_unique_run_state()` at
shuffle start. Spoiler header records `unique_caps`, `unique_reservations`,
`unique_placed_counts`, `unique_unplaced` for debugging.

Mp_safe interaction: heritage prefixes are subtracted before the
reservation pool so reservations never lead to leaked-heritage
placements at coop slots.

### Night Boss caliber pool

New constant `V3_NIGHT_BOSS_CALIBER_TARGETS` — 48 hand-curated
c-prefixes. At Night Boss arena slots (source variant carries
'Night Boss' marker), the candidate pool is intersected with this
set. Restricts the 22 dedicated NB arenas to genuinely epic
encounters: the 22 vanilla NR Night Bosses + 26 epic field bosses
(Astel, Borealis, Ekzykes, Walking Mausoleum, Mohg, Dancing Lion,
Trolls, Erdtree Avatar, etc.).

Anti-pattern this gates against: the existing `is_boss_tier_prefix`
returns True for any c-prefix with a stray Boss-marker variant
somewhere in its variant list. So Depraved Perfumer (which has a
Castle Boss variant) was passing the boss-tier filter and landing
at e.g. the Bell Bearing Hunter Night Boss arena — anticlimactic
on every dimension. Caliber gate fixes that surgically.

c2276 Giant Death Crab considered for inclusion but dropped: not
quite epic enough to anchor an arena solo; better as a field boss
target where the cap=2 still gates abundance. m49_25 Crucible+Hippo
arena now reliably picks two distinct epic targets.

The gate fires in three places — main pick path, reservation
scoring, BIG_PROXIMITY demotion — because reservation early-return
and post-pick demotion both bypassed the runtime filter. All three
paths are now caliber-aware. Source-side restriction only: caliber
c-prefixes still appear at non-NB slots normally.

### Dead-code purge

Cut the at-risk-tail rescue system — was a no-op since v0.20.86
(V3_AT_RISK_SMALL_WEIGHT=1.0, V3_VARIETY_TRICKLE_ADDITIONS=0
disabled the rescue logic entirely). Removed `compute_at_risk_tail`,
`rescue_pool_for_slot` (never called), `_AT_RISK_CACHE`, all
V3_AT_RISK_*/V3_RESCUE_*/V3_FORCE_RESCUE_*/V3_VARIETY_TRICKLE_*
constants, the design comment block, and the `at_risk_set=` /
`size_down_rescue=` parameters from pick_target / pick_target_cp /
pick_cluster_target_cp / shuffle_msb_v3 / cmd_shuffle_v3 signatures.

Net: ~150 lines removed. Same 5-seed × mp_safe ON/OFF regression
shows identical behavior — the dead code really was inert.

Deleted dev/ scripts: `zero_diagnosis.py`, `coverage_sim.py`,
`coverage_sim_full.py`. Each was a 200–500 line helper for an
investigation that has long since concluded.

### DCX pipeline fast paths

Two new optimizations in `dcx_batch.py`:

**Fix A — identity-skip at compress_dir.** New optional kwargs
`vanilla_dir` + `original_dcx_dir`. For each shuffled MSB whose
bytes match the corresponding vanilla MSB, copy the original
.msb.dcx straight from `in_dcx_dir` instead of re-compressing.
Saves the DCX deflate cycle for unchanged outputs.

**Fix B — HUB_MAPS passthrough at decompress_dir.** New kwargs
`passthrough_dcx_dest` + `passthrough_set`. Files in the set
get copied straight without ever being decompressed. The 7
V3_HUB_MAPS (m10_00, m11_00, m12_00, m13_00, m18_00, m19_00,
m20_00) are pure player-hub maps that never get shuffled, so
decompressing them just to recompress identical bytes was waste.

Pipeline simulation results: decompress 293 calls (saved 7 from
HUB_MAPS), compress 131 calls (saved 169 from identity-skip). All
300 output files present, HUB_MAPS verified byte-identical with
vanilla, spoilers correctly placed.

CLI standalone calls still work — both kwargs are optional, so
direct invocations that don't supply `vanilla_dir` / `passthrough_set`
fall back to full processing.



Removes the v0.19.16 tier-based mode system: `bossy_clusters`,
`grunt_promotion`, `expand_resilient`. All three were opt-in,
default-off, and stayed off across roughly four months of v0.20–v0.22
playtest. The plumbing they required (module-level mode globals, a
GUI mutation API, two support tables, an `_expanded_resilient_pool`
fork in the fragile-slot filter, a startup self-test, a bossy trace
counter, spoiler header fields) was paying recurring complexity cost
for zero observed shipping use.

### What's gone

In `oops_v3.py`:
  - Globals: `_TIER_MODE_BOSSY_CLUSTERS`, `_TIER_MODE_GRUNT_PROMOTION`,
    `_TIER_MODE_EXPAND_RESILIENT`, `_TIER_MODE_PROMOTE_RATE`,
    `_V3_BOSSY_TRACE_REMAINING`.
  - Tables: `V3_TIER_BOSSY_CLUSTER_SOURCES`,
    `V3_TIER_RESILIENT_EXPAND_BLOCKLIST`.
  - Functions: `set_tier_modes`, `_v3_self_test_bossy_fix`,
    `_expanded_resilient_pool`.
  - The bossy / grunt-promotion injection block in `pick_target_cp`,
    plus the `mode_target_tiers` re-filter pass downstream of the
    cap stage. Tier-preserve filter still runs unchanged — it's
    foundational, not modes.
  - Self-test invocation at run start (the `v0.19.22 SELF-TEST FAILED`
    diagnostic for stale `.pyc` was tier-mode-specific; the more
    general `EXCLUDE_INTEGRITY` / `TAGS_INTEGRITY` traces still run).
  - `tier_modes` block in JSON spoiler header.
  - "Tier modes" line in markdown spoiler.

In `oops_rando_gui.py`:
  - 3 `BooleanVar`s (`tier_bossy_clusters_var` etc.).
  - The "Tier modes (v0.19.16)" UI region (separator, label, three
    checkbutton rows).
  - 3 config-dict entries in `_collect_config`.
  - The `set_tier_modes` call + log line in the worker.

### What survives

The underlying tier metadata (`tags[cp]['tier']`),
`V3_BOSS_STRENGTH_TIERS`, `V3_FIELD_STRENGTH_TIERS`, and the
tier-preserve filter in `pick_target_cp` (boss-tier source slots get
boss-tier targets; field-tier source slots get field-tier targets)
all stay. That's the foundational backbone, not the modes layer.

`_V3_TRACE_BUFFER` stays — it carries non-tier-mode events
(`TAG_OVERRIDES_APPLIED`, `TAGS_INTEGRITY`, `EXCLUDE_INTEGRITY`,
FI-drop events). Bossy-trace appends are gone with their containing
block; the buffer continues to populate from other sources.

### Behavioral parity

End-to-end fragility audit on the v0.21 spoiler (3792 placed slots):

```
                v0.22       v0.23
  fragile        2579        2579
  T2.8 releases   276         276
```

Identical, since modes were off in the source spoiler. The
simplification is invisible at runtime; the win is in source-tree
weight (~150 lines removed across two files) and one fewer place
where state can leak between runs.

### Spoiler schema

JSON: `tier_modes` field removed from header. Spoilers from v0.22 and
earlier still parse fine — nothing else reads the field.

Markdown: "Tier modes: …" line removed. Multiplayer-safe line is now
the first metadata line under the swap counts.




Refines coarse-fragile zone classification (T1 variant qualifiers, T2
fragile maps, T2.7 anchor proximity) by reading per-slot navmesh AABB
shape and releasing slots that sit on a wide flat polygon — the flat
plaza inside a Cathedral footprint, the cleared dirt inside a bandit
camp — back to the full target pool.

### Background — why a fourth tier of refinement

T1 / T2 / T2.7 paint with a coarse brush: any slot whose source variant
carries a `(Cathedral)` / `(Encampment)` / etc. qualifier, every slot
inside a flagged map, every slot within 100u of a T1 anchor. Inside
those zones the geometry isn't uniformly hostile — most fragile zones
have benign pockets that the coarse rules over-restrict.

User framing from the v0.21 → v0.22 handoff: "Cathedral for example is
rocky outside the building but some flat ground within. My dream is to
take our fragile zones and refine to just marking the sensitive spots
within those zones."

### Pipeline — pure-Python navmesh AABB stats

New `bnd4.py` module parses `.nvmhktbnd` binders directly (no Yabber /
WitchyBND unpack required, no Oodle DLL required — NR navmesh binders
ship uncompressed). Existing `extract_aabbs_from_hkx` in
`hkx_aabb_check.py` consumes the embedded `n_*.hkx` payload bytes
unchanged.

`build_slot_terrain.py` extended: for every slot it computes
`slot_roughness(aabbs, position)` returning four signals from
`hkx_aabb_check.py`:

  - `s_y`  — y-extent of smallest containing leaf AABB
  - `s_xz` — xz-area of same
  - `n10` — leaf-AABB count within 10u xz
  - `n20` — leaf-AABB count within 20u xz

Stored sparsely in `slot_terrain.json["slot_roughness"]` only for slots
that have a containing leaf (~2000 entries on the m60_xx procedural set
in this drop).

### Calibration — s_y dominates

n=442 coarse-fragile-on-mesh slots vs n=1545 unrestricted-on-mesh slots
in m60_xx maps, distributions:

```
                  fragile median   safe median   ratio
  s_y                 14.1            2.9         5x
  s_xz              2289            2738          ~1
  n10                165             148          ~1
  n20                293             272          ~1
```

s_y carries essentially all the separation. Physical reading: a flat
horizontal navmesh polygon has near-zero y-extent because horizontals
are thin in y; a sloped or cliff polygon has y-extent proportional to
its size × slope. Polygon-normal slope extraction (deferred from
the handoff plan) would yield the same signal at materially higher
parser cost — skipped.

### Threshold — conservative, single-knob

`V3_T2_8_S_Y_THRESHOLD = 1.0` for ship. Sweep:

```
  s_y < 0.3     9% of fragile released, 13% of safe slots qualify
  s_y < 1.0    15% of fragile released, 25% of safe slots qualify  ← ship
  s_y < 2.0    22% of fragile released, 35% of safe slots qualify
  s_y < 3.0    26% of fragile released, 51% of safe slots qualify
```

1.0 sits inside the safe-distribution p25, so a slot with s_y < 1.0 is
in the part of the AABB shape distribution that's almost exclusively
populated by genuinely flat slots. Loosen in v0.23 if playtest shows
the cut is too tight; tighten if a release turns out to be a false
positive.

### Runtime — narrowly-scoped override

In `is_fragile_slot`, T2.8 fires AFTER each of T2 / T1 / T2.7 returns
True, releasing the slot if `_is_t2_8_releasable(msb, pi)` agrees.
Explicit non-overrides:

  - T3 (V3_PROBLEM_SLOTS) — hand-curated, never overridden.
  - T2.5 (edge sentinel) — coordinate-pattern signal independent of
    terrain, never overridden.
  - V3_OFF_MESH_SLOTS — out of scope. Soft SENSITIVE-exclusion in
    pick_target_cp continues to govern off-mesh slots.

Tier ordering in `is_fragile_slot` adjusted: T3 → T2.5 → T2 → T1 →
T2.7. T2.5 moved up alongside T3 to make the "never overridden by T2.8"
group visually contiguous. No behavioral change at the T3 / T2.5 layer.

### Spoiler-level effect

Ran v0.22 against the v0.21 spoiler (3792 placed slots):

```
  fragile under v0.21 baseline   2855
  fragile under v0.22 (T2.8)     2579
  released by T2.8                276    9.7% of fragile slots
```

Release tier breakdown:
  - 267 from T2 (whole-map fragile, mostly Shifting Earth maps)
  - 8 from T2.7 (proximity to anchors)
  - 1 from T1 (variant qualifier)

Sample of release-eligible slots: `Mausoleum Knight (Noklateo)` on the
Noklateo plaza, `Wolf` and `Demi-Human` slots inside m60_42_36_x at
y=90 (open-field sub-region of a fragile map). These match the
intended pattern — flat ground inside a notionally-rocky zone.

### Coverage caveat — m30 / m32 / m34 / m38 not in this drop

The navmesh upload covers the 100 m60_xx procedural tiles. Dungeon /
cathedral binders (m30_*, m32_*, m34_*, m38_*, etc.) weren't in the
drop, so slots in those maps have no `slot_roughness` entry and T2.8
does not fire for them. Those maps fall back to the v0.21 fragility
behavior unchanged. Most cathedral / dungeon maps are
`FORCE_OFF_MESH_MAPS` anyway and never entered T2.8 candidacy. m30 /
m34 dungeons currently rely on V3_FRAGILE_MAPS / T1 qualifiers; ship a
binder dump for those next time and rebuild slot_terrain.json to extend
T2.8 coverage.

### Files

  - **new** `bnd4.py` — minimal pure-Python BND4 reader
  - **modified** `hkx_aabb_check.py` — `extract_aabbs_from_bytes`,
    `collect_navmesh_aabbs_from_bnd`, `slot_roughness`
  - **modified** `build_slot_terrain.py` — reads `.nvmhktbnd` directly
    (with legacy unpacked-dir fallback), writes `slot_roughness` block
  - **modified** `oops_v3.py` — `_load_slot_roughness`,
    `_is_t2_8_releasable`, T2.8 hooks in `is_fragile_slot`
  - **regenerated** `slot_terrain.json` — added `slot_roughness` block
    (~2000 entries, ~150 KB)




User CTD: load-in crash at m60_44_39_30, a Limveld bandit camp.
Spoiler audit showed nine SENSITIVE chrs landing in this map — c4240
Fingercreeper × 3, c4241 Giant Fingercreeper × 1, c4171 Giant Putrid
Flesh × 1, c4570 Wormface × 2, c4150 Basilisk × 1 — despite all being
classified SENSITIVE.

### Diagnosis: every fragility tier missed this slot

Tier-by-tier check on the smoking-gun slot pi=43 (Highwayman →
Giant Fingercreeper):

  - T3 (V3_PROBLEM_SLOTS): not listed.
  - T2 (V3_FRAGILE_MAPS / _PREFIXES): tile coord (44, 39) absent.
    Existing prefixes cover m60_44_37 + m60_45_37/38/39 (cathedral
    patch v0.20.74) but skip (44, 39).
  - T2.5 (edge sentinel): position y=88.5, doesn't match.
  - T1 (variant qualifier): source variants are 'Highwayman',
    'Stonedigger', 'Godrick Soldier', 'Leyndell Foot Soldier',
    'Glintstone Digger (Small Sack)' — all bare or with non-fragile
    qualifiers.
  - T2.7 (T1 proximity): the only anchor in this MSB is a 'Mine' at
    (-106.55, 154.45, -7.42) — 134u from the crash slot, outside the
    100u radius.

Same gap pattern as the v0.20.74 cathedral patch (generic source
variants at a Limveld tile not on the fragile-prefix list).

### Fix 1: synthetic Encampment anchors

Added two synthetic anchors per procedural variant of the m60_44_39
tile, matching the bandit-camp positions:

  - West camp: (-25, 90, -85), covers pi 22-58 minus high-tier outliers.
  - East camp: (120, 110, 0), covers pi 35, 36, 39.

Propagated to all four extant procedural variants (_00, _20, _30, _50;
_10 has zero slots). Anchors carry `_synthetic: true` and `_provenance`
fields to distinguish them from spoiler-derived anchors and to record
the gap they're patching.

This is more surgical than adding `m60_44_39_` to V3_FRAGILE_MAP_PREFIXES
— the tile has cliff/cathedral content at y >= 135 that doesn't share
the encampment's geometry constraints, so a whole-tile prefix would
over-restrict ~28 non-camp slots. Two anchors restrict the ~22 actually
fragile slots only.

### Fix 2: big-enemy proximity post-pass

The encampment had one GIGA, one XXL, two XL Fingercreepers, one XL
Wormface, and two M Bears within ~50u of each other. Even slot-level
fragility isn't sufficient if multiple big chrs cluster — density itself
is a crash trigger on cluttered geometry.

Added `V3_BIG_PROXIMITY_RADIUS = 30.0` post-pass: walks `swap_plan`,
finds pairs of XL/XXL/GIGA placements within radius in the same MSB,
demotes the higher-pi entry to a size <= L target drawn from the same
compatible pool. Deterministic given seeded order (sort by pi for the
conflict-resolution pass).

Defense-in-depth with the slot-level fragility filter — the anchors
catch SENSITIVE leaks at known-fragile slots; the proximity rule catches
density issues at slots that aren't individually fragile but become so
when stacked.

`BIG_PROXIMITY_DEMOTIONS` events emit to spoiler `diagnostic_trace` for
visibility into how often the rule fires.

### Fix 3: walked back wrong sweep proposal

Initial spoiler-only diagnosis suggested demoting c4241 / c4171 / c4570
/ c4250 to SENSITIVE. Review of source confirmed all four were already
SENSITIVE. The crash wasn't a missing classification — it was the slot
being invisible to fragility detection. No demotions in v0.20.91.

### Audit: `audit_encampment_anchors.py`

New script. Scans vanilla MSBs for tight clusters of encampment-archetype
source c-prefixes (c4311/c4313/c4371/c4373/c4377/c4382/c4383/c4384)
without a nearby T1 anchor. Emits proposed synthetic 'Encampment'
anchors. Run before next playtest to surface sibling tiles with the same
gap before they CTD.

### Files changed

  - `oops_v3.py`
      version bump to v0.20.91
      `V3_BIG_PROXIMITY_*` constants added near `V3_AT_RISK_*`
      post-pass block inserted in `shuffle_msb_v3` after `swap_plan`
        finalization, before Models additions
  - `t1_anchors.json`
      4 entries added (2 anchors × 2 sibling MSBs); m60_44_39_30 also
      gained 2 anchors next to its existing Mine entry
      Top-level `note` updated to mention synthetic anchors
  - `audit_encampment_anchors.py` (new)
      Standalone audit script for sibling encampment tiles




Two follow-ups to v0.20.0 based on first spoiler audit (seed 371955).

### Fix 1: tier-preserve uses source c-prefix tier, not variant marker

v0.20.0 spoiler showed c4171 (trash) placing at boss-tier source slots:
Albinauric Archer, Highwayman, Giant Crow (Bloodbane), Fire Monk,
Godskin Apostle. Cause: `recipient_is_boss` is set from the slot's
variant name marker ("(Field Boss)" / "(Encampment)" etc.), which
returns False for plain "Bloodbane Giant Crow". Tier-preserve then
sent the slot to the field bucket and trash candidates qualified.

Fix: tier-preserve in pick_target_cp now reads the SOURCE c-prefix's
tier directly from tags. c4560 Giant Crow is field_boss-tier as a
c-prefix regardless of which variant is at this specific slot, so
all targets are restricted to boss-strength tier. Variant-level
appropriateness is still handled by pick_variant_for_tier downstream
(it uses recipient_is_boss to pick a non-boss variant of the chosen
target c-prefix).

Verified: Giant Crow source 100 picks under v0.20.1 = 100/100 boss-tier.

### Diagnostic: FI return counter in spoiler header

The c5110/c4181/c3610/c3620 cps still showed 0 placements in the
v0.20.0 spoiler despite being in the universal pool with valid
variants and no target excludes. Offline simulation against the same
seed produces 13-41 placements per cp. Bats (c4200/c4201) work in
both sim and production. Some production-only filter is dropping
the four ex-cluster_member cps between pick_target_cp and the
spoiler write — this counter will localize where.

`_V3_FI_RETURNED_COUNTS` increments at the end of pick_target_cp for
seven tracked c-prefixes (c5110, c4181, c3610, c3620, c4200, c4201,
c4481). Counter dumps to `fi_returned_counts` in the spoiler header.

Read after run: if a cp shows nonzero in `fi_returned_counts` but
0 placements in entries, the drop is in the write pipeline (variant
pick / cluster handling / model addition / MSB write). If a cp
shows 0 in both, the drop is in pick_target_cp itself (something is
filtering it out before the return).

## v0.20.0 — Universal pool + tag-driven tier-preserve (architectural simplification)

User insight: with fragile-slot detection mature, the size/anim/loco
machinery is doing more harm than good. Empirical breakages map to
3 categories — scripted-only AI, locomotion incompat, mount-component
standalone — all handled cleanly by per-c-prefix excludes. The pre-
filter pool was dropping legit candidates (the FI mystery: tendrils/
jellyfish/Oracle Envoys never appearing in spoilers despite the
v0.19.22 force-include bypass) and forcing rescue/cap workarounds.

Changes:
- compatible_pool() now returns ALL c-prefixes from tags (universal).
- pick_target_cp() collapsed to: pool → excludes → modes → tier-preserve
  → fragile → cap → mode-reapp → sample. Removed: swap_compat strict,
  size-down rescue, AERIAL filters, SUBSURFACE filter, force-include
  bypass, COMPAT_BLACK_HOLE rescue.
- Tier-preserve now tag-driven (V3_BOSS_STRENGTH_TIERS / V3_FIELD_STRENGTH_TIERS)
  instead of structural is_boss_tier_prefix. Boss-tier sources get
  miniboss+field_boss+night_boss+nightlord candidates only; field-tier
  sources get grunt+trash only. Fixes the c4171 castle-rooftop bug
  structurally (trash never reaches boss arenas).
- cluster_member tier retired. c5110/c4181/c3610 → grunt,
  c3620 (Oracle Envoy Large; Cathedral) → miniboss, c4481 → grunt.
- slot_y plumbing removed. V3_AERIAL_*, V3_SUBSURFACE_*, V3_EMERGENCE_*
  emptied (constants kept as no-op for backwards compat).

Validation (seed 33104, all modes ON):
- Wolf source 200 picks: 74 distinct c-prefixes (was ~10 in v0.19.x).
- Hippo night_boss 50 picks: 50/50 boss-tier (no trash leak).
- c4481 bossy clusters with cap pressure: 50/50 miniboss, 24 distinct.
- Tendrils/jellyfish/Oracle Envoys appear naturally.
- Existing excludes (c2100, c3300, c3600, c3850, c4281) still respected.
- Self-test still passes.

# Changelog
## v0.20.0 — Universal pool + tag-driven tier-preserve (architectural simplification)  User insight: with fragile-slot detection mature, the size/anim/loco machinery is doing more harm than good. Empirical breakages map to 3 categories — scripted-only AI, locomotion incompat, mount-component standalone — all handled cleanly by per-c-prefix excludes. The pre- filter pool was dropping legit candidates (the FI mystery: tendrils/ jellyfish/Oracle Envoys never appearing in spoilers despite the v0.19.22 force-include bypass) and forcing rescue/cap workarounds.  Changes: - compatible_pool() now returns ALL c-prefixes from tags (universal). - pick_target_cp() collapsed to: pool → excludes → modes → tier-preserve   → fragile → cap → mode-reapp → sample. Removed: swap_compat strict,   size-down rescue, AERIAL filters, SUBSURFACE filter, force-include   bypass, COMPAT_BLACK_HOLE rescue. - Tier-preserve now tag-driven (V3_BOSS_STRENGTH_TIERS / V3_FIELD_STRENGTH_TIERS)   instead of structural is_boss_tier_prefix. Boss-tier sources get   miniboss+field_boss+night_boss+nightlord candidates only; field-tier   sources get grunt+trash only. Fixes the c4171 castle-rooftop bug   structurally (trash never reaches boss arenas). - cluster_member tier retired. c5110/c4181/c3610 → grunt,   c3620 (Oracle Envoy Large; Cathedral) → miniboss, c4481 → grunt. - slot_y plumbing removed. V3_AERIAL_*, V3_SUBSURFACE_*, V3_EMERGENCE_*   emptied (constants kept as no-op for backwards compat).  Validation (seed 33104, all modes ON): - Wolf source 200 picks: 74 distinct c-prefixes (was ~10 in v0.19.x). - Hippo night_boss 50 picks: 50/50 boss-tier (no trash leak). - c4481 bossy clusters with cap pressure: 50/50 miniboss, 24 distinct. - Tendrils/jellyfish/Oracle Envoys appear naturally. - Existing excludes (c2100, c3300, c3600, c3850, c4281) still respected. - Self-test still passes.  

## v0.19.25 — Mode re-application before frequency cap (full bossy/grunt fix)

User audit on v0.19.24 spoiler — diagnostic_trace confirmed:
- Self-test passed (engine had v0.19.22 fix)
- BOSSY_FIRED for c4481 with mode_target_tiers correctly set
- Yet spoiler still showed only 12/35 miniboss for c4481 solo entries

Root cause: cap filter (V3_TARGET_PLACEMENT_CAP=50) interacting with the
v0.19.22 fix in a way I missed. With pool restricted to miniboss/field_boss,
field_pool ends up small (3-5 minibosses without boss markers). Size-down
rescue fires (chosen_pool < 5 threshold) and extends with at-risk
candidates of any tier. The frequency cap then prefers non-capped
candidates — and the popular minibosses (Fire Monk c3901: 92 placements,
Giant Skeleton c3060: 88) blow past cap quickly, so cap filter drops
them, leaves the rescue's at-risk grunts. The post-fragile mode re-app
then finds an empty refilter set and falls through, keeping grunts.

Fix: re-apply mode_target_tiers right after rescue, BEFORE the cap
filter. This way:
  1. Rescue extends chosen_pool with at-risk (any tier)
  2. Mode re-app #1 strips off-tier rescue additions
  3. Cap filter operates on on-tier-only pool — its empty-fallback
     keeps capped minibosses rather than pivoting to off-tier
  4. (existing v0.19.22) Mode re-app #2 after fragile filter as
     final safety net

Validation against seed 33104 c4481 entries with cap pressure simulated
(c3060/c3901 at 80 placements each, well over cap):
- Pre-fix: post-rescue chosen_pool has minibosses + grunts → cap drops
  the capped minibosses → grunts win → 23% miniboss observed
- Post-fix: post-rescue mode re-app strips grunts → cap operates on
  miniboss-only → falls back to capped minibosses (still on-tier) →
  100% miniboss

Modes-off baseline unchanged.


## v0.19.22 — Tier modes firing bug fix + force-include compat bypass

### Tier modes firing (Bossy Clusters, Grunt Promotion)

User audit: enabled all three opt-in tier modes (Bossy Clusters,
Grunt Promotion, Expand Resilient), spoiler header confirmed all
three set ON, but the actual swap distribution showed only Expand
Resilient firing. Bossy was 21% miniboss+field_boss (vs expected
~100%); grunt promotion was 18.9% miniboss share (vs expected ~40%
at the 30% promote rate) — both indistinguishable from baseline
mode-off behavior.

Root cause traced via direct simulation against the user's actual
c4481 entries: the v0.19.16 mode filters ran *after* the
tier-preserve `boss_pool`/`field_pool` split. Most miniboss-tier
c-prefixes have at least one boss-marker variant (`Encampment`,
`Field Boss`, `Remembrance`, `Evergaol`, etc — see
`V3_BOSS_NAME_MARKERS`), so `is_boss_tier_prefix()` returns True
and they end up in `boss_pool`. For non-boss recipient variants
(e.g., "Miranda Sprout (Ruins)" — `is_boss_tier_variant()` → False),
`chosen_pool = field_pool`, which had at most ~2 minibosses for
c4481's compat space. The bossy filter then had nothing to keep.

Fix is two-part:
1. **Pre-tier-preserve filter** — bossy/grunt mode filters now run
   on `pool` *before* the tier split, ensuring miniboss candidates
   survive into both `boss_pool` and (via the empty-`field_pool` →
   `pool` fallback) the chosen path for non-boss recipients.
2. **Post-fragile re-application** — the size-down rescue can
   re-introduce off-tier candidates via at-risk-tail injection
   when `tier_pool_was_empty=True` (which becomes common after
   the pre-filter narrows pool to one tier). A `mode_target_tiers`
   flag is set in step 1 if a mode actually fired, and re-filters
   `chosen_pool` after fragile-filter, eliminating the rescue
   pollution while preserving the fragile-slot resilient guarantee.

Validation against user's actual seed 589157 c4481 entries (42
solo): pre-fix produced 9/42 miniboss; post-fix simulation produces
42/42 miniboss. Grunt-source miniboss share improves from 18.9%
baseline to 35.3% (close to the theoretical ~40% at 30% promote
rate; residual gap is grunt sources where rescue+fragile+compat
intersection has no on-tier candidates, which is the correct
fail-safe behavior).

Modes-off sanity: baseline c4481 distribution unchanged.

### Force-include compat bypass (Maris pool + bats)

User audit: 0 placements of Maris' Tendril (c5110), Maris' Jellyfish
(c4181), Oracle Envoy (c3610), Oracle Envoy Large (c3620). Also
flagged: bat clusters (c4200 Man-Bat, c4201 Operatic Bat) "never
get randomized." Vanilla NR has 115 c4200 slots and 13 c4201 slots;
spoiler showed only 1 of 128 swapping, the other 127 stayed vanilla.

Root cause: the v0.11 `V3_FORCE_INCLUDE_UNTAGGED_TARGETS` mechanism
adds these 4 c-prefixes to any slot's pool when the natural pool is
narrow (< `V3_FORCE_INCLUDE_NARROW_THRESHOLD`, currently 60). The
set name reflected the original design intent — the 4 c-prefixes
were meant to be untagged (no anim_class, no size_class) so the
swap_compat layer's untagged-bypass would let them through. But
they're all *tagged* (Maris' Tendril is anim=misc, Maris' Jellyfish
=aquatic, Oracle Envoy=humanoid). swap_compat's strict anim+size+
hitbox match silently filtered them back out for almost all slot
types.

For bats (c4200/c4201), the second filter that killed them was the
v0.10 V3_AERIAL_SOURCE_ALT mechanism: bat slots at high y or
off-mesh require chosen_pool to intersect a curated aerial-capable
whitelist (which includes c4181 Maris' Jellyfish). Since c4181 was
being filtered out by swap_compat upstream, the intersection was
usually empty and `pick_target_cp` returned None → swap skipped →
vanilla preserved.

Fix: explicit early-return in `_filter()` for cp in
V3_FORCE_INCLUDE_UNTAGGED_TARGETS — they bypass swap_compat the
same way truly-untagged candidates do. This makes the force-include
mechanism work as documented.

Validation: c4200 Man-Bat sim across 115 vanilla slots — 1 swapped
pre-fix → **106 swapped post-fix** (9 remaining are terrain-
sentinel slots that correctly preserve). c4201 Operatic Bat: 0/13
→ **13/13**. Grunt-source Maris contribution: 0 → **39/145** for
c4070 Wolf sources (27% Maris share, dominated by c4181 because
swap_compat-bypass is per-c-prefix, so c4181 + c5110 + c3610 +
c3620 all become eligible for any narrow-pool source).

## v0.19.21 — Cancel button + cooperative cancellation

GUI feature request. Run button now becomes a state-machine:
"⚙ Generate Rando" idle → "✕ Cancel" while running → "Cancelling..."
(disabled) while propagating. Engine adds `set_cancel_requested()`
/ `clear_cancel_request()` / `is_cancel_requested()` /
`CancelledError` primitives, with a `threading.Event` flag checked
at per-map boundaries in `cmd_shuffle_v3` and per-file boundaries
in `dcx_batch.decompress_dir` / `compress_dir`. Cancel latency is
typically 1-3 seconds (one map's processing time). Output dir
keeps any partial files; re-running with the same seed regenerates.
Worker catches `CancelledError` separately from real errors and
emits a `__CANCELLED__` sentinel so the status reads "Cancelled"
rather than "Done".

## v0.19.20 — Flying-dragon target exclusion (class-wide)

User: "softlocked, whatever fullgrown fallingstar beast was supposed
to be disappeared again."

Spoiler trace: m49_20 pi=5 (Fallingstar Beast Night Boss source) →
**c4503 Borealis the Freezing Fog**. Same arena-entry pattern as
c4910 Magma Wyrm in v0.19.11: GIGA flying_dragon with a scripted
"fly in from above and land in arena" intro. At non-dragon-arena
slots the flight path resolves to no valid landing → dragon flies
out of bounds → culled.

The reactive whack-a-mole here (Magma Wyrm in v0.19.11, Greyll added
preemptively, now Borealis) is the same bug class. Pulling the whole
flying_dragon anim_class proactively this time:

```
V3_EXCLUDE_TARGET_PREFIXES additions:
  c4500  Flying Dragon (Unscaled)
  c4501  Decaying Ekzykes (Unscaled)
  c4503  Borealis the Freezing Fog (confirmed culprit)
  c4505  Flying Dragon (Small)
  c4911  Great Wyrm Theodorix (also night_boss tier — double protection)
```

c4910 Magma Wyrm and c4510 Ancient Dragon (Greyll) were already
excluded; with these 5 added, the entire flying_dragon class is
target-locked. They keep randomizing as SOURCES — their own slots
still get swapped to other things — but won't land at random target
slots that lack the arena geometry they expect.

The Fallingstar Beast slot at m49_20 pi=5 still randomizes; just no
longer to anything with a fly-in entry animation.

## v0.19.19 — Wormface tier fix + spoiler mode flags

### c4570 Wormface: miniboss → grunt

User feedback: "small wormface should not be able to sub in for a
royal revenant, feels like a different tier."

In NR's encounter design Wormface is encampment fodder — 13 vanilla
slots in m34_20 deathblight encampment, no `has_reward`, no arena
variants. Royal Revenant by contrast has its own arena variants
(c4021 Royal Revenant Night Boss) with `has_reward=True`. They sit at
genuinely different tiers despite both being unique-looking creatures.

Reclassified c4570 to grunt. The (Giant) Wormface c4580 stays at
night_boss tier (correctly). Effect:

- c4570 no longer eligible as a swap target at miniboss-tier source
  slots (Royal Revenant, Battlemage, etc.)
- c4570 IS eligible as a target at grunt-tier source slots (foot
  soldier camps), which fits the "deathblight encampment fodder"
  vibe better
- c4570 source slots (m34_20 cluster) keep randomizing as before

Counts shift: miniboss 54 → 53, grunt 51 → 52.

### Spoiler header records tier modes

Confused state from v0.19.16 playtest: spoiler showed clear evidence
that `Expand Resilient` was on (48 new minibosses landing in cathedrals)
but ambiguous evidence on `Bossy Clusters` and `Grunt Promotion`. No
way to confirm what was actually toggled in the GUI.

Added `tier_modes` field to spoiler JSON header:

```json
{
  "seed": 12345,
  "mode": "loose",
  "tier_modes": {
    "bossy_clusters": false,
    "grunt_promotion": true,
    "expand_resilient": true,
    "promote_rate": 0.30
  },
  "entry_count": 3618,
  "entries": [...]
}
```

And a corresponding line in the markdown summary:
"Tier modes: **grunt_promotion, expand_resilient** (promote_rate=0.30)"

Now any spoiler is self-describing — easy to confirm what config
produced a given run without re-launching the GUI.

## v0.19.18 — Maris pool fix (real this time)

v0.19.14's threshold bump from 8 → 16 didn't actually land the Maris
reactivation. New seed (518131) audit showed 0 placements of c5110
Maris' Tendril, c4181 Maris' Jellyfish, c3610 Oracle Envoy, c3620
Oracle Envoy (Large) — same as the seed it was supposed to fix.

Diagnosis from the new spoiler:

```
Pool size distribution (134 unique source c-prefixes in the seed):
  Smallest pool: 4 (c4200 Man-Bat)
  Median pool:   37
  Largest pool:  69
  Pools < 16 (the v0.19.14 threshold): 20 of 134 sources
```

The 20 sources that DID trigger force-include are all small quadrupeds
(Wolves, Rats, Man-Bat, Giant Rat, etc) where size-down at-risk
weighting then starves the Maris c-prefixes out anyway — they're
S/L sized untagged but the sources weight S-class at-risk picks
heavily.

Threshold needed to be much higher to reach mid-sized pools where
Maris stuff would actually compete for selection. Bumped from 16 → 60.

`V3_TARGET_PLACEMENT_CAP = 50` already enforces a per-c-prefix
saturation ceiling, so the threshold can be aggressive without
returning to the v0.10 "192 placements" overshoot. Each Maris
c-prefix should land somewhere between 20-50 placements per seed —
visible variety without dominating.

If next playtest shows them at the cap (50/50/50/50 = 200 total
Maris stuff), threshold can dial back to ~40. If still under-shooting,
the cap itself is the bottleneck and would need lifting.

## v0.19.17 — Tier reclassifications round 1

User feedback on borderline calls from v0.19.16:

| c-prefix | name | v0.19.16 | v0.19.17 | reason |
|---|---|---|---|---|
| c4550 | Giant Dog | grunt | **miniboss** | big Caelid dog, boss-tier feel like Giant Crow |
| c4490 | Living Jar Warrior | miniboss | **grunt** | big but not scary |
| c5750 | Living Jar Warrior (variant) | miniboss | **grunt** | same call |
| c3361 | Putrid Ancestral Follower | miniboss | **grunt** | regular variant — c3371 Shaman remains miniboss |

c4241 Giant Fingercreeper stays at field_boss — confirmed as
"miniboss in difficulty but giga-size makes it impractical for
random placements."

Counts shift: miniboss 56 → 54, grunt 49 → 51. Net effect: Bossy
Clusters and Expand Resilient pools both lose 2 candidates each
(Living Jar Warrior ×2, Putrid Ancestral Follower regular) but gain
nothing (Giant Dog isn't humanoid+M/L so doesn't enter resilient
expansion).

## v0.19.16 — Tier classification + 3 opt-in tier modes

### `tier` field added to nr_enemy_tags.json

Every c-prefix now carries a tier classification. Vocabulary:

| tier | definition |
|---|---|
| trash | critters, item-drops (Slugs, Strays, Larvae, Land Squirts) |
| grunt | foot soldiers, regular hostile mobs |
| miniboss | evergaol-tier — unique kit, often named, drops something |
| field_boss | overworld healthbar bosses (Tree Sentinel, Magma Wyrm) |
| night_boss | per-night encounter bosses with arena maps |
| nightlord | Day 3 Nightlords (always excluded) |
| cluster_member | `_cluster_only` entities |
| non_combat | NPCs, projectiles, training dummies |
| mount_component | rider/horse paired pieces |
| player_template | player models |

Final counts: miniboss 56, grunt 49, field_boss 35, trash 28,
night_boss 24, nightlord 24, non_combat 11, cluster_member 5,
mount_component 5. No remaining unknowns.

### Three tier-based modes (all default-off)

**Bossy clusters** (`tier_bossy_clusters`): cluster sources listed in
`V3_TIER_BOSSY_CLUSTER_SOURCES` (currently just c4481 Miranda Sprout)
restrict their target pool to miniboss/field_boss tier only. Eliminates
trash/grunt dilution that was making Miranda encounters feel like a
bag-of-everything rather than a boss swarm.

**Grunt promotion** (`tier_grunt_promotion`): when the source slot's
c-prefix is tier=grunt, the target pool gets a 30% chance to upgrade
to miniboss-tier. Random foot-soldier camps occasionally seed a named
miniboss this way — Battlemage in a Godrick Foot Soldier slot, etc.

**Expand resilient pool** (`tier_expand_resilient`): adds miniboss-tier
humanoid M/L candidates to `V3_RESILIENT_BIPEDS`, so cathedral / tunnel
fragile slots can host Battlemages, Bloodhound Knights, Perfumers,
Mausoleum Knights, etc. Empirical bad-list (`V3_TIER_RESILIENT_EXPAND_BLOCKLIST`)
excludes c4110 Demi-Human Shaman from the expansion based on the
playtest cathedral-freeze evidence.

GUI: three new checkboxes on the main tab below the merchant model
swap row, under a "Tier modes (v0.19.16)" header. Each mode is
independently toggleable. Mode flags persist via the run config dict
and feed `set_tier_modes()` at run start.

### Implementation

Module-level globals in `oops_v3.py` hold mode state:
`_TIER_MODE_BOSSY_CLUSTERS`, `_TIER_MODE_GRUNT_PROMOTION`,
`_TIER_MODE_EXPAND_RESILIENT`, `_TIER_MODE_PROMOTE_RATE`. Setter
function `set_tier_modes()` is called from the worker thread before
any pick_target_cp invocations. State is reset on every run (no leak
between consecutive runs with different mode combos).

`pick_target_cp` consults the modes after standard pool filtering and
before weighted sampling — modes shrink the pool but never empty it
(falls back to the unfiltered pool if a tier restriction would leave
nothing valid).

## v0.19.15 — Marionette reactivation

c3850 Marionette removed from `V3_EXCLUDE_PREFIXES`. The previous
exclusion comment ("Reported broken when roaming") cited a
proximity-trigger wake bug that's now addressed by the
`permissive_spawn_emerge` patch family — the same EMEVD work that
already rescued c4470 Abductor Virgin Fort and c5110 Maris Tendril
from the original "wake-trigger / dormant-spawn bugs" exclusion list.

c3850 was also already listed in `V3_RESILIENT_BIPEDS` (dead code while
hard-excluded) — that entry is now actually active. 41 vanilla slots
reactivated:

  - m10_00: 32 slots
  - m34_10: 9 slots

Neither map is in `V3_FRAGILE_MAPS`, so the variety effect is full —
Marionette slots will randomize freely as both source and target, and
Marionette can also be picked as a fallback target in fragile maps via
the resilient pool.

Visual change worth flagging: Marionette slots used to be statue-like
puppets that activated on player proximity. After this change, those
slots get whatever the rando picks (regular hostile-from-start
enemies). The "dormant statue then springs to life" set-piece is lost
in exchange for variety. If this loss bothers playtest, source-exclude
c3850 to keep the statue surprise while leaving it valid as a target.

## v0.19.14 — Maris pool reactivation + spirit knight safety net

### Maris Tendril + Jellyfish actually appearing as targets

User: "can you make sure Maris tendril and jellyfish are in their pools?
havent seen them in a while". Audit confirmed: 0 placements of c5110
(Maris' Tendril) and 0 of c4181 (Maris' Jellyfish) across ~3700 swaps
in seed 246135.

Root cause: both prefixes are listed in `V3_FORCE_INCLUDE_UNTAGGED_TARGETS`
but gated by `V3_FORCE_INCLUDE_NARROW_THRESHOLD = 8`. The threshold was
introduced (v0.11) to fix over-appearance — at threshold=∞ they
appeared 192 times vs a 50-target cap. But threshold=8 went too far the
other way: most overworld slots have natural compat pools larger than 8
candidates, so the widening never triggers and Maris stuff effectively
disappears.

Bumped to threshold=16. Mid-density pools (8-16 natural candidates)
now get the force-include widening; richly-populated pools still
preserve native variety. Should land between the over- and
under-shoots. Watch placement counts in next playtest spoilers — if
counts overshoot 50, drop to 12; if still undershooting, push to 20.

### Ghost soldier safety net

User clarified the previous "ghost soldier pre-night 2 boss" report:
"frozen, not hittable. different than the terrain freeze." So it was
a real malfunction, not a working-as-intended Spirit summon.

The likely cause is the v0.19.12 seed where c3250 was still randomizable
— with the rider swapped to a non-mounted boss, the spirit summon
trigger fires (calls c4353-Spirit at the slot's entity_id) but the
follow-up phase-coordination events expect a c3250 source for activation
sync. v0.19.13 already keeps the rider vanilla, which should resolve
the summon coordination. But as belt-and-suspenders:

Added `npc=43531400` (Leyndell Knight Night Boss Spirit) to
`V3_EXCLUDE_SOURCE_NPC_PARAMS`. The spirit slots themselves now stay
vanilla regardless of broader c4353 randomization. Granular fix —
c4353 has 8 other variants (regular Leyndell Knights at encampments,
fortifications, ruins) that continue to randomize freely. Only the
4 Spirit slots in m48_50 + m48_60 are locked.

## v0.19.13 — Tree Sentinel arena rider+mount preservation

Playtest report on the Draconic Tree Sentinel Night Boss encounter
(m48_50): "draconic tree sentinel night boss now not softlocked, but
you gotta get rid of the horses. they were glitching and making an
ungodly noise, plus the riders couldnt do anything."

Root cause: when c3250 (Draconic Tree Sentinel rider) got swapped to a
non-mounted boss model, the 4 vanilla c4363 Lordsworn Knight's Horse
(Night Boss) entities continued executing their mount-coordination
script targeting the rider's entity_id. Without a proper mount-capable
rider model:

  - Horses loop their "mount up with my rider" animation (visible
    glitching)
  - Looped voice/SFX bank fires on a tight cycle (the ungodly noise)
  - Rider's mounted-combat AI can't engage from atop a non-horse

Same rider+mount-pair preservation pattern that c3150/c3160 (Night's
Cavalry) already uses.

Source-excluded c3250 (Draconic) + c3251 (regular Tree Sentinel) +
c4363 (their shared horse mount). Both c-prefixes are entirely "(Night
Boss)" content with no overworld presence, so the variety cost is
limited to 12 vanilla slots locked across the two Tree Sentinel arenas
(m48_50 + m48_60). Three of the 11 at-risk Night Boss c-prefixes from
the v0.19.11 audit are now resolved; 8 remain pending playtest
evidence.

### Aside: ghost soldier in lead-up

User also reported "ghost soldier pre-night 2 boss." This is almost
certainly the c4353 Leyndell Knight (Night Boss Spirit) variant
(npc=43531400) — 4 such entities exist in m48_50 + m48_60 by design as
ethereal summoned phantoms, working as intended. No fix needed unless
they specifically misbehave.

## v0.19.12 — Revert demi-human removal (wrong suspect)

Playtest screenshot identified the cathedral-freeze culprit as **c4110
Demi-Human Shaman** — the horned, hunched, sickle-wielding variant —
not c4101 Large Demi-Human or c4120 Demi-Human Chief, which v0.19.11
preemptively removed from `V3_RESILIENT_BIPEDS` on suspicion.

Restored c4101 + c4120 to the resilient pool. They're cleared of
suspicion: the silhouette in the screenshot is unambiguously a Shaman
(horned head, curved blade, spiky hunched stance) and not the smooth-
headed regular demi-human or the headdressed Chief.

c4110 is already in `V3_EXCLUDE_SOURCE_PREFIXES` (Shaman slots stay
vanilla) but **is allowed as a target** in non-fragile slots — that's
how it ended up at the precarious overworld spot in the screenshot.
Holding off on target-excluding c4110 until next playtest confirms
this is reproducible and not a one-off bumpy-terrain unluck. If
Shamans keep freezing on natural overworld bumps, target-exclude
becomes the fix — it'd cost 0 source variety (Shaman is already
source-excluded for monotony) but would lose ~2-3 placements per seed.

## v0.19.11 — Source/target exclusion audit from playtest 246135

Multiple findings from the v0.19.10 production playtest seed 246135.

### Commander Night Boss spawn (c3050) — source-excluded

User: "spawns are broken for commander night boss". c3050 Commander has
2 vanilla slots (m49_26 Outland Commander, m49_27 Battlefield Commander),
both Night Boss arenas with hard-coded scripted spawn handlers. In
playtest the slot got swapped (c3050 → c4750 Grafted Monarch, then to
c3704 Battlemage) and the boss froze at spawn.

Added c3050 to `V3_EXCLUDE_SOURCE_PREFIXES`. Both variants are
themselves "(Night Boss)" — no overworld presence, so source-excluding
the whole c-prefix has zero variety cost.

### Magma Wyrm + Greyll target-excluded

User: Night 2 boss (Fallingstar Beast Night Boss at m49_20 pi=5)
"spawned in and then disappeared." Spoiler shows the swap was c4680
→ c4910 Magma Wyrm (Crater).

Magma Wyrm's "rise from magma" entry animation requires a magma surface
to push it up. At a non-magma slot the animation fires but the wyrm
dives down through the floor and gets culled by out-of-bounds checks.

Added `c4910` (Magma Wyrm) to `V3_EXCLUDE_TARGET_PREFIXES`. 3
placements affected (m46_04, m49_20, m60_44_38_20).

User asked whether c4510 (Greyll/Ancient Dragon Night Boss) was
similarly excluded. It wasn't. 4 placements in the playtest at random
dragon slots. Since Ancient Dragon Night Boss has the same scripted-
entry profile, target-excluded it preemptively.

### Demi-humans removed from V3_RESILIENT_BIPEDS

User: "medium sized anthropomorphic demi human frozen in one of the
unsafe cathedral spots. probably need to come out of the safe bipeds
list." c4101 Large Demi-Human and c4120 Demi-Human Chief were both in
the resilient pool, used as fallback targets in fragile maps.

Their hunched gait and crouch-and-leap attack pattern collides with
cathedral column-and-altar geometry that other resilient bipeds (Exile
Soldier, Wandering Noble, Misbegotten, etc.) navigate cleanly. 26
placements were going to fragile maps before this change.

Removed c4101 + c4120 from `V3_RESILIENT_BIPEDS`. They remain valid
targets for non-fragile slots — only the cathedral/tunnel/castle pool
is affected.

### Miranda Bosom cluster — happy accident, no fix

User: "with cluster protection off, Miranda bossom is spawning i
believe a cluster of boss-tier enemies. Don't fix, its awesome. I
fought like a ton of bloodhound knights in a different seed."

Per-Part rolling on Miranda Sprout clusters and similar
multi-source `_cluster_only` placements creates emergent boss-tier
swarms (Bloodhound Knight cluster, etc.) when the user disables
cluster protection in the GUI. This is the intended chaotic-mode
behavior — calling it out here as documented and good.

### Audit: Night Boss exposure

Previous v0.19.10 changelog flagged 11 other Night Boss c-prefixes with
arena-only placements. The Commander/Magma Wyrm/Greyll fixes don't
preemptively exclude those — only the c-prefixes confirmed broken in
this playtest were touched. List remaining at-risk:

```
c3100 Bell Bearing Hunter (Night Boss)      3 slots
c3250 Draconic Tree Sentinel (Night Boss)   2 slots
c3251 Tree Sentinel (Night Boss)            2 slots
c3560 Godskin Apostle (Duo Night Boss)      4 slots
c3570 Godskin Noble (Duo Night Boss)        3 slots
c4750 Grafted Monarch (Night Boss)          1 slot
c4911 Great Wyrm (Night Boss)               1 slot
c4950 Tibia Mariner (Night Boss)            1 slot
c4980 Death Rite Bird (Night Boss)          4 slots
```

Total exposure: 21 slots. These are still empirically untested. If
they break in playtest, source-excluding follows the c3050 pattern.

## v0.19.10 — Roll back speculative m30 dungeon flagging

User reviewed the m30_00 / m30_30 contents and decided they don't fit
the dungeon profile:

- **m30_00**: Compact (66×29×64u) area, all Godrick soldiers
  (18 Foot Soldier + 11 Soldier + 1 Knight + 1 Abductor Virgin).
  Could be either an indoor fort interior or an outdoor castle
  courtyard — ambiguous.

- **m30_30**: Larger (115×47×48u) mixed-enemy area with vanilla Slugs
  (6) and Giant Rats (3) alongside Godrick soldiers, Glintstone
  Sorcerers, Living Jar Warriors, etc. Vanilla NR placing open-ground
  enemies (Slugs, Rats) here strongly implies the navmesh is valid for
  ground locomotion.

Removed both from `FORCE_OFF_MESH_MAPS` and `V3_FRAGILE_MAPS`. Lets
the AABB+proximity classifier handle them organically. If specific
slots in those maps turn out to be broken in playtest, they go in
`V3_PROBLEM_SLOTS` (the manual override path added in v0.19.9).

### What stays force-flagged

```
Cathedrals + subterranean (5 maps): m32_00, m32_10, m32_20, m38_00, m38_10
Castle interior (1 map): m15_00
Tunnels (16 maps): m20_00–m20_90, m21_00–m21_50
```

### Cache regenerated

```
v0.19.9:  on=2402, off=415, prox=89, force=434, no_match=57
v0.19.10: on=2471, off=415, prox=89, force=364, no_match=58
```

70 slots returned to AABB-controlled classification (the m30_00 + m30_30
combined population).

### Pre-release fixup: restored per-map EMEVDs

The bundle had been shipping with only `patched_emevd/common_func.emevd.dcx`
present; the per-map patched `.emevd.dcx` files (m30_30, m38_10,
m60_43_37_00/10/20) had been dropped at some point. Restored:

```
patched_emevd/
  common_func.emevd.dcx       (68 subs across global handlers)
  m30_30_00_00.emevd.dcx      (Guardian Golem Fort inline-script fix)
  m38_10_00_00.emevd.dcx      (Cathedral interior 2 inline scripts)
  m60_43_37_00.emevd.dcx      (overworld cell, time variant 00)
  m60_43_37_10.emevd.dcx      (overworld cell, time variant 10)
  m60_43_37_20.emevd.dcx      (overworld cell, time variant 20)
```

Extended the GUI's **Install pre-patched EMEVD** button to copy ALL six
files instead of only `common_func`. Existing files at the destination
still get backed up to `*.bak` first; behavior is otherwise identical.

Updated docs to match: `patched_emevd/README.md`, `WORKFLOW.md`,
`EMEVD_PATCHES.md`, top-level `README.md`. The patched_emevd/README now
describes per-map patch contents; EMEVD_PATCHES.md gained a per-map
section that notes `emevd_patch.py` itself doesn't cover per-map files
(those still need the DarkScript3 manual flow if rebuilding from scratch).

Also dropped the `.dcx` files from `vanilla_msbs/` in the release zip
(originally pre-release pruning). The rando never reads those — only
`.msb` and `.xml` (sidecar manifests for Yabber recompression). Saves
3.7 MB unpacked / 36% of the zip size since DCX compresses poorly inside
zip.

## v0.19.9 — Tunnels + dungeons + castle in force-off-mesh, manual override path

User playtest report: "tunnel too, same issue some working mostly frozen.
Also encampments, at least the flame chariots encampment map is bumpy
enough that most of these rats are broken."

### Maps added to FORCE_OFF_MESH_MAPS / V3_FRAGILE_MAPS

```python
# Castle interior
'm15_00_00_00.msb',  # Stormveil-equivalent, 52 slots, c3661-dominant

# Tunnel connectors — m20_xx series (10 maps)
'm20_00_00_00.msb' through 'm20_90_00_00.msb',

# More tunnels — m21_xx series (6 maps)
'm21_00_00_00.msb' through 'm21_50_00_00.msb',

# Underground dungeons
'm30_00_00_00.msb',  # 31 slots
'm30_30_00_00.msb',  # 39 slots
```

Total slot coverage: 288 → 434 (+146 cathedrals → cathedrals + tunnels +
dungeons).

Picked these because v0.19.8 spoiler analysis showed all of them at 0%
Jelly with 5+ slots and confirmed navmesh data — same signature as
cathedrals. Conservatively didn't add the m43_xx fort series (mostly
small, 6-18 slots each) without playtest confirmation.

### V3_PROBLEM_SLOTS now respected in test mode

User can manually pin specific (msb, pi) tuples to force off_mesh
treatment, bypassing terrain classification entirely. Useful for known-
broken positions that aren't covered by FORCE_OFF_MESH_MAPS — encampment
clusters in overworld maps, specific platforms, etc.

```python
# In oops_v3.py:
V3_PROBLEM_SLOTS = {
    ('m60_44_38_20.msb', 87): 'flame chariot encampment - confirmed broken',
    ...
}
```

In terrain test mode dispatch, V3_PROBLEM_SLOTS is checked BEFORE the
slot_terrain.json lookup — so manual entries always win.

### Re: the flame chariot encampment

Investigated m60_44_38_20 (3 chariot slots) and m60_44_39_20 (1 chariot)
as candidates for "the flame chariots encampment map." Found:

- 3 chariots in m60_44_38_20 are SCATTERED, not clustered (sub-surface
  positions at y=-51, y=-43, y=21 in different cell quadrants)
- The 4 chariots in m32_20 ARE clustered at y=16 in a tight group —
  this looks like the actual flame chariot encampment, and m32_20 is
  already force-off-mesh as a cathedral

So the flame chariot encampment user is referring to may already be
covered (it's in the cathedral set). Worth confirming in the next
test seed walk: check whether all rats around the flame chariots are
now Jellies. If still Rats somewhere, log the (msb, pi) and add
manually to V3_PROBLEM_SLOTS.

### Cache regenerated

```
v0.19.8: on=2539, off=415, prox=89, force=288, no_match=66 (3397)
v0.19.9: on=2402, off=415, prox=89, force=434, no_match=57 (3397)
```

137 slots moved on_mesh → force_off_mesh due to expanded map list.

## v0.19.8 — Categorical force-off-mesh for cathedral maps

v0.19.7 playtest revealed cathedral maps were catastrophically misclassified:

```
v0.19.7 terrain test placement breakdown:
  m32_00 (Cathedral):    66/66 Rat,   0 Jelly  ← all broken
  m32_20 (Cathedral):    67/67 Rat,   0 Jelly  ← all broken
  m38_10 (Cathedral):    35/35 Rat,   0 Jelly  ← all broken
  m32_10 (Mountaintop):  66 Rat,     23 Jelly  ← partial
  m38_00 (Cathedral):    21 Rat,     10 Jelly  ← partial
  TOTAL:                255 Rat,     33 Jelly
```

User report from playtest: "bro there's like one working rat and 8 frozen
ones in this entire cathedral, i think we categorically mark all the
cathedral spots fragile."

### Why navmesh AABB approach fails for cathedrals

Cathedrals have navmesh that covers the whole building footprint as a
single tight AABB region. The actual walkable surface is fragmented
around columns, altars, steps, and barriers — geometric detail at a
scale below the BVH leaf granularity. A slot inside a column's
footprint is "in" a tight leaf AABB (= classified on_mesh) but has no
walkable connection in the actual triangle mesh.

Proximity expansion (v0.19.7) didn't help because there are no nearby
off_mesh slots in cathedral interiors — the BVH classifies the whole
interior as one solid on_mesh region.

### Force-off-mesh map list

Added `FORCE_OFF_MESH_MAPS` in `build_slot_terrain.py`. All slots in
these maps are categorically marked `force_off_mesh` regardless of
AABB classification:

```python
FORCE_OFF_MESH_MAPS = {
    'm38_00_00_00.msb',  # Cathedral of the Forsaken Dead
    'm38_10_00_00.msb',  # Cathedral
    'm32_00_00_00.msb',  # Mountaintop / cathedral interior
    'm32_10_00_00.msb',  # Mountaintop
    'm32_20_00_00.msb',  # Cathedral / similar interior
}
```

Same set as `oops_v3.py V3_FRAGILE_MAPS` — kept in sync manually since
importing oops_v3 in build_slot_terrain.py would cause a circular dep.

Disable with `--no-force-off-mesh` if you ever want to test the pure
AABB-only classification.

### Cache regenerated

```
v0.19.7:  on=2782, off=442, prox=92,  no_match=1   (3317 total)
v0.19.8:  on=2539, off=415, prox=89,  force=288, no_match=66 (3397)
```

288 cathedral slots now force-flagged. (The no_match jump is unrelated
spoiler-input variance — different seed, different slot subset.)

### Engine

`force_off_mesh` is recognized as off-mesh-equivalent in:
- Bat AERIAL trigger (V3_AERIAL_SOURCE_ALT routing)
- Terrain test mode dispatch (rat/jelly selection)

### Test mode prediction

After regenerating the test seed with v0.19.8:
- All 288 cathedral slots become Jellies
- Walking through cathedrals should show essentially zero Rats
- If any frozen Rats remain, they're outside cathedral maps and need
  a separate fix

## v0.19.7 — Proximity expansion for navmesh classification

First playtest of the v0.19.6 terrain test seed (Rat on-mesh, Jelly
off-mesh) surfaced two false-negative on_mesh slots in a rocky castle-
ruins area where Rats spawned frozen. The Spirit Jellyfish at off-mesh
slots performed correctly (one woke up after being hit, confirming
the float-based classification).

User observation: "you can tell the ground is rocky here. so maybe
theres a way to parse that for on-navmesh spots." The hypothesis: a
slot adjacent to a known off-mesh slot is likely also on bumpy/rocky
terrain, even if its own AABB happens to be tight.

### Proximity expansion rule

After the AABB-based pass, on_mesh slots within K units of any
off_mesh / no_match slot in the same map get reclassified as
`proximity_off_mesh`. Engine treats this status identically to
`off_mesh` for routing decisions (bat AERIAL trigger, terrain test
mode), but it's tracked separately for diagnostics so we can tell
which protections came from extent vs proximity.

Default K = 10.0 units. Empirical analysis on the user's spoiler:
within-10u expansion adds 92 new flagged slots (442 → 534) without
flagging the densely-clustered safe areas. Tunable via
`--proximity-expand N` on `build_slot_terrain.py`.

### Bundled cache regenerated

`slot_terrain.json` rebuilt with `--tight-extent 50 --proximity-expand
10`:
  - 2782 on_mesh (was 2840 — 58 fewer due to proximity-flagged drop)
  - 442  off_mesh (extent >= 50)
  - 92   proximity_off_mesh (within 10u of off_mesh)  ← NEW
  - 1    no_match (sentinel)
  - 476  no_navmesh_data (excluded arenas)

### Tuning guidance

If the v0.19.7 default still leaves frozen Rats:

```
# More aggressive — 15-unit proximity catches +73 more slots:
python build_slot_terrain.py ... --proximity-expand 15

# Even more — combine with tighter extent:
python build_slot_terrain.py ... --tight-extent 40 --proximity-expand 15

# No proximity (back to v0.19.4-6 behavior):
python build_slot_terrain.py ... --proximity-expand 0
```

Re-run `terrain_test_seed.py` after rebuilding the cache.

### Implementation

- `build_slot_terrain.py` now accepts `--proximity-expand N` (default 10)
- `lookup_slot_terrain()` now returns 'proximity_off_mesh' for the new
  tier (in addition to the existing 'off_mesh' and 'no_match')
- Both engine consumers (bat AERIAL trigger, terrain test mode dispatch)
  treat `('off_mesh', 'proximity_off_mesh')` as equivalent

### Re: the demi-human running around

Probably a scripted-spawn slot in an excluded arena, or part of a
cluster the rando left vanilla. Terrain test mode disables cluster
preservation, but excluded maps (Nightlord, Roundtable) still pass
through unmodified. If it persisted in the test seed at a non-arena
location, that's worth a separate look — log the (map, pi) if it
shows up.

## v0.19.6 — Terrain test mode (Rat on-mesh / Jelly off-mesh)

New CLI tool `terrain_test_seed.py` for validating the navmesh AABB
classifier in isolation. Generates a seed where every spawnable enemy
slot becomes one of two targets based purely on terrain status:

- **on_mesh** (or unknown / not in cache) → c4080 Rat
- **off_mesh** → c4180 Spirit Jellyfish
- **no_match** → vanilla preserved (sentinel slot)

All other rules disabled for this mode: V3_FRAGILE_*, V3_PROBLEM_*,
V3_RESILIENT_*, cluster preservation. Each Part rolls independently so
multi-Part bosses might split between Rat and Jelly — that's the design,
since the test isolates per-slot accuracy.

### Test design

All Rats in this seed should be MOVING. A frozen Rat anywhere in the
world is a false negative in the on-mesh classifier — the slot was
classified on_mesh but actually has no walkable surface. Walk the world,
log frozen-Rat positions, paste into V3_PROBLEM_SLOTS for v0.19.7+.

Jellies on off_mesh slots: bonus signal. Jellies float, so should handle
off-mesh better than ground enemies, but bumpy/walled terrain might still
trap them. Non-frozen jellies confirm "this off_mesh slot is at least
viable for floaters" — meaning V3_AERIAL_SOURCE_ALT can fill it.

### Usage

```
python terrain_test_seed.py <vanilla_msb_dir> <output_msb_dir>
python terrain_test_seed.py <vanilla_dcx_dir> <output_dcx_dir>
```

Detects .msb vs .msb.dcx automatically. Custom targets:

```
python terrain_test_seed.py <in> <out> --on-mesh c4080 --off-mesh c4180
```

### Implementation

- New `terrain_test_targets={'on_mesh': cp, 'off_mesh': cp}` param on:
  - `oops_v3.shuffle_msb_v3` (worker)
  - `oops_v3.cmd_shuffle_v3` (orchestrator)
  - `dcx_batch.rando_pipeline` (DCX wrapper)
- Inner loop dispatch: when terrain_test_targets is set, lookup terrain
  via `lookup_slot_terrain(msb_basename, pi)`, branch to Rat/Jelly/skip
  before reaching the normal pick_target_cp logic.
- Forces `effective_cluster_aware = False` so cluster preservation
  doesn't override per-slot terrain decisions.
- No GUI control — CLI-only since it's a diagnostic mode.

## v0.19.5 — Bat aerial trigger uses navmesh status, plus Maris' Jellyfish

Promoted the v0.19.4 navmesh AABB classification from diagnostic-only to
production engine logic, scoped to bat slots (c4200 Man-Bat, c4201
Operatic Bat). Fixes a long-standing axis confusion in the aerial-source
restriction rule.

### Old rule (v0.10 — v0.19.4)

Bat-source slots at `y >= 50` got restricted to V3_AERIAL_SOURCE_ALT
(the climbers/floaters/clingers whitelist). Bat slots below y=50 used
the standard pool with no aerial-specific filtering.

### Why y >= 50 was the wrong axis

Cross-tabulating the 128 bat slots from oops-all-Rat seed 309746 against
navmesh AABB containment showed:

```
y-band                 on_mesh  off_mesh  no_match
y 0-30 (low)               48        11         2
y 30-50 (mid)               1         9         0
y 50-100 (perch)           15         9         0
y >= 100 (cliff)           33         0         0
```

Two distinct miscalibrations:

1. **All 33 high-cliff bats (y >= 100) are on-mesh.** They sit on
   walkable cliff edges with full navmesh coverage. The old rule
   pointlessly restricted these to the alt pool, blocking 47 c-prefixes
   that would have worked fine.

2. **22 low-y bats (y < 50) are off-mesh** — they're on rooftops,
   columns, perches over water, etc. The old rule sent them to the
   standard pool, which includes ground-locomotion enemies that have
   no navmesh path to those positions.

### New rule (v0.19.5)

Trigger is now driven by terrain status from `slot_terrain.json`:

- `off_mesh` → apply alt-pool restriction (regardless of y)
- `on_mesh` (or absent from cache) → no aerial restriction
- `no_match` → skip the swap entirely (preserves vanilla; these are
  sentinel placeholders at positions like `(*, 0, 1)` that never spawn)

Falls back to the legacy `y >= alt_cfg['threshold']` rule if a slot
isn't covered by the terrain cache. The cache currently covers all
slots seen in the spoiler (3819 placements across 172 maps), so this
fallback rarely engages in practice.

### Behavioral delta on 128 bat slots

- **20 slots GAIN aerial protection** (y<50 but off-mesh — the
  previously-unprotected rooftop/perch group)
- **48 slots LOSE needless restriction** (y>=50 but on-mesh — high
  cliff bats now free to use full standard pool)
- **2 slots get vanilla preservation** (no_match sentinels)
- **29 slots remain in alt-pool restriction** (truly off-mesh,
  regardless of y)

### Pool addition: c4181 Maris' Jellyfish

Added small floating jelly to both bat alt pools per user request
("jellyfish plus one of the floating blue things should be in aerial
substitutes. anything that floats"). c4181 was already in
V3_FORCE_INCLUDE_UNTAGGED_TARGETS for narrow pools and is excluded as
a SOURCE (Maris area scripted slots) but is valid as a TARGET.

Other "anything that floats" candidates evaluated:
- c3320 Silver Tear (Unscaled) — vanilla y_median=-0.1, all 5 vanilla
  placements are at ground level. Adding it as an aerial substitute
  would be out-of-distribution; rejected.
- c3330 Giant Silver Tear (Unscaled) — XL size + heritage source, no
  vanilla placement data to validate; rejected.
- c4170 Putrid Flesh (clings) — already in pool.

### Implementation

- New `_SLOT_TERRAIN_CACHE` lazy-loader in `oops_v3.py` reads
  `slot_terrain.json` once on first lookup. ~512 entries cached;
  on-mesh slots return None (absence from dict by convention).
- New `lookup_slot_terrain(msb_name, pi)` helper returns 'off_mesh',
  'no_match', or None.
- `pick_target_cp` aerial trigger block updated to consult terrain
  cache first, fall back to y-threshold for unknown slots.
- No GUI changes. Engine-only.

### Not in this release

The terrain-status trigger is currently scoped to V3_AERIAL_SOURCE_ALT
recipients (just bats). Other slot types still use legacy heuristics:

- V3_FRAGILE_MAPS / V3_FRAGILE_SOURCE_QUALIFIERS (Cathedral, Mine,
  Crater, etc. preservation) — unchanged
- V3_PROBLEM_SLOTS (manual blocklist) — unchanged
- V3_RESILIENT_BIPEDS (humanoid fragility tier) — unchanged

Future versions can promote terrain-status to other rule heads as the
heuristic earns confidence through playtest validation. For now,
deliberate scope: just bats.

## v0.19.4 — Navmesh AABB terrain detection (Path A breakthrough)

Pre-computed per-slot terrain classification using world-space AABB
extraction from Havok navmesh files. Diagnostic-only this release —
results need empirical playtest validation before integrating into the
shuffle engine.

### Background

Across v0.18-v0.19.3, broken-slot detection relied on heuristic source
qualifiers (FRAGILE_SOURCE_QUALIFIERS, FRAGILE_MAPS) and manually-curated
V3_PROBLEM_SLOTS entries. This worked for known patterns (Cathedral
runtops, Mine cavern walls, etc.) but missed novel fragile geometry.

The empirical playtest sweep methodology surfaces broken slots ground-
truth-correctly but is labor-intensive (oops-all-Rat across the whole
world). We wanted a way to PREDICT which slots would break before
walking.

### Investigation summary

Spent v0.19.3 exploring NR's actual navmesh files:
- `.nva.dcx` (manifest) — small, decompresses cleanly via pyooz, gives
  ~14 navmesh tile transforms per cell. Useful as coarse "is this
  position near the navmesh" heuristic but high noise floor.
- `.nvmhktbnd.dcx` (Havok navmesh bundle) — multi-block Kraken, requires
  WitchyBND or Windows-side Oodle to decompress.
- `.hkxbhd/.hkxbdt` (collision binder pair) — BHF4/BDF4 format, parses
  cleanly (36-byte entries, Python-side).
- Internal `.hkx` files — Havok TAG0 format, SDKV2018-01-00, content is
  hkaiNavMesh instances (Havok AI library).

### Breakthrough — world-space AABBs

The hkaiNavMesh's BVH structure stores per-leaf AABBs in WORLD COORDINATES
(not tile-local). A scan of the DATA section for 8-float patterns matching
(min.xyz, _, max.xyz, _) where min<max recovers ~2700 AABBs per map cell:
the root AABB plus per-leaf navmesh region bounds.

**Crucial property**: a slot contained by a tight leaf AABB (extent <50
units in all dims) is on the navmesh. A slot contained by ONLY large
internal BVH nodes (extent >100) is in dead terrain — the BVH had to
expand internal nodes to bridge gaps where no triangles exist.

Empirical validation on m60_44_38_30 (oops-all-Rat seed 309746):
- 9 slots flagged off_mesh: 8 cathedral peak (y=143-155) + 1 sentinel
- 20 slots classified on_mesh: all confirmed-working ground placements
- 100% match against playtest ground truth

Across all 172 maps in the seed:
- 2840 on_mesh
- 431 off_mesh (cliffs, peaks, sub-surface, geometric gaps)
- 81 no_match (sentinel placeholders at `(x, 0, 1)` patterns)
- 67 maps without navmesh data (Nightlord arenas, Roundtable — excluded
  by rando anyway)

### Shipped

- **`hkx_aabb_check.py`** — interactive diagnostic. Takes a spoiler +
  navmesh root dir, classifies each placement, emits ready-to-paste
  V3_PROBLEM_SLOTS suggestions.
- **`build_slot_terrain.py`** — one-shot cache builder. Walks all slots,
  outputs `slot_terrain.json`.
- **`slot_terrain.json`** (95KB) — pre-built classification for all
  placements. Slot positions are intrinsic to (msb, pi) regardless of
  seed, so this cache is permanent until rando rules change which slots
  are eligible.

### Why diagnostic-only this release

Want to validate against more playtest data before auto-merging into
V3_PROBLEM_SLOTS or making it a hard rule in pick_target_cp. Specifically
unclear:

1. Are 50-unit "tight extent" cutoffs right for ALL terrain types? Some
   small caves might have legitimately narrow leaf AABBs.
2. The 81 no_match slots are obvious sentinels — but are there CASES
   where a real slot is no_match because the navmesh just happens to be
   sparse there (not actually broken)?
3. Off-mesh ≠ broken. Some off-mesh slots may use scripted-spawn
   (script_spawn source flag) and bypass navmesh.

Plan: walk a normal-rando seed, for each off_mesh slot the tool flagged
that ALSO broke in playtest, paste into V3_PROBLEM_SLOTS. After 2-3
seeds of validation, integrate into pick logic.

### Manifest dependency removed

Earlier path explored using `.nva` manifests + Vec3 distance heuristic
for off-mesh detection. That approach is now superseded — AABBs in the
.hkx files are in world coordinates and don't need tile transforms.
`nva_distance_check.py` retained for backward compat but marked as
deprecated.

## v0.19.3 — Sub-surface emergence + Cluster-lock + Refined resilient bipeds

Three fixes addressing distinct fragility patterns identified in v0.19.1
playtest seed 162498.

### 1. Sub-surface emergence-slot detection

Vanilla NR uses negative y-coordinates for slots whose authored enemies
have rise-from-ground / burst / emergence animations: Slugs, Fingercreepers,
magma Fire Prelates, Guilty (magma-earth respawn), Magma Wyrm. The slot's
spawn script fires the emergence animation and elevates the entity to
surface y on player proximity.

Playtest report: at `m60_43_38_20 pi=18` (Fire Prelate Crater slot, y=-137.4),
the rando swapped the source to a c-prefix without emergence animation —
the entity spawned underground but never rose. Appeared as a stuck partial
mesh, not killable, encounter softlocks.

74 sub-surface slots in this seed (y < -10, threshold). Sources are
dominated by emergence-class enemies: c4381 Guilty (24), c4040 Slug (17),
c4250/c4240/c4241 Fingercreepers (18), c3900 Fire Monk (5), c3910 Fire
Prelate Crater (2), c4910 Magma Wyrm (1), etc.

**Fix**: when slot_y < V3_SUBSURFACE_Y_THRESHOLD (-10.0), restrict the
target candidate pool to V3_EMERGENCE_COMPATIBLE_TARGETS (17 c-prefixes
with rise-from-ground intros). Empty intersection → vanilla preservation.

### 2. Auto-derived cluster-lock for multi-Part scripted arenas

The Night 2 boss arena (m48_60_00_00) softlocked: 3 healthbars (Tree
Sentinel + 2 Royal Cavalrymen) but only 2 visible enemies. Root cause:
m48_60 has 4 Lordsworn Knight's Horse Parts (c4363, tagged `_cluster_only`)
paired with 4 Leyndell Knight rider Parts (c4353). In cluster-blind mode
(v0.19.1 default), c4363 horses preserve as vanilla while c4353 riders
randomize independently to non-rider c-prefixes (Glintstone Sorcerer,
Mausoleum Knight, etc). The pairing is broken — riders aren't on horses,
horses don't have riders. The encounter's death-detection script can't
resolve and the fog gate stays up.

**Fix**: auto-derive `V3_CLUSTER_LOCK_MAPS` at load time. Walk slots data,
find every (map, c-prefix) where c-prefix has `_cluster_only=True`, add
that map to the set. When a map in this set is randomized, force
cluster-aware behavior locally regardless of the GUI setting. Preserves
multi-Part scripted encounters end-to-end.

Auto-protected maps (currently 13):
  - **m48_50, m48_60** — Night 2 Tree Sentinel arenas (c4363 Knight's Horse)
  - **m34_10, m46_71** — Miranda Blossom + Sprouts (c4481 Sprout)
  - **9 m60_xx cells** — Overworld Kaiden Sellsword horse pairings (c4060)

The auto-derivation means future tag changes (adding new `_cluster_only`
entries) automatically extend the protected map set without manual list
maintenance.

### 3. Refined V3_RESILIENT_BIPEDS — Skeletons removed

Playtest revealed Skeleton family enemies (c3060 Giant Skeleton, c3500
Large Skeleton (Spear)) break when placed at fragile slots they should
have handled. Root cause: Skeletons have rise-from-grave emergence
animations that require slot-specific spawn-volume scripting. At the
crater Fire Prelate slot, c3060 stuck mid-rise, never activated AI.

User clarified that other bipeds at the same slot type (c3371 Putrid
Ancestral Shaman, others) worked correctly — only Skeleton family broke.

**Fix**: remove c3060, c3500 from V3_RESILIENT_BIPEDS (down from 29 → 27
c-prefixes). Keep c3371 Putrid Ancestral Shaman + c3661 Putrid Corpse
(confirmed working).

### Verification (smoke test on seed 162498)

  - Sub-surface slots: 74 detected, all targets restricted to V3_EMERGENCE_COMPATIBLE_TARGETS or vanilla preserved
  - V3_CLUSTER_LOCK_MAPS: 13 maps auto-derived, m48_60 cluster-aware behavior verified
  - V3_RESILIENT_BIPEDS: 0 c3060/c3500 placements at fragile slots
  - All v0.19.x earlier fixes hold: 0 source-side script_spawn placements,
    0 cluster-only c-prefixes randomized as source, promotions still firing.

---

## v0.19.2 — Fragile-slot resilience layer

Some MSB slots in NR were authored with specific spawn-volume requirements
or scripted-context dependencies that break complex spawns when randomized.
The classic failure mode: a Land Octopus, Slug, or Spirit Jellyfish placed
at one of these slots renders flat on the ground with its emergence
animation never firing, AI never activating, totally unkillable. Bipeds
with simple stand-and-walk AI handle these slots reliably.

This release adds a 3-tier detection system that identifies fragile slots
at swap time and restricts the target candidate pool to a known-resilient
biped set (29 c-prefixes — the common humanoid mob bestiary).

### Detection tiers (any match triggers restriction)

**Tier 1 — Source variant qualifier** (`V3_FRAGILE_SOURCE_QUALIFIERS`):
The source variant's mmv_name contains `(Cathedral)`, `(Mine)`, `(Crater)`,
`(Encampment)`, `(Fort)`, `(Mountaintop)`, `(Ruins)`, or `(Noklateo)`.
These are scripted-context placements with unique authoring. ~95 source
slots in vanilla NR carry one of these qualifiers.

**Tier 2 — Fragile maps** (`V3_FRAGILE_MAPS`):
Whole-MSB restriction. Pre-populated based on map naming convention:
  - `m38_00_00_00.msb`, `m38_10_00_00.msb` — Cathedral interior
  - `m32_00_00_00.msb`, `m32_10_00_00.msb`, `m32_20_00_00.msb` — Subterranean / tunnels
Total 288 slots. m32_10 already partially-protected via shared-arena rules
(Maris fight); FRAGILE_MAPS protects the surrounding non-Tendril slots.

**Tier 3 — Manual blocklist** (`V3_PROBLEM_SLOTS`):
`(msb_name, part_index)` tuples for slots that escape T1 + T2 detection.
Most precise tier — populate as playtest reveals new problem locations.
Currently empty.

### Resilient biped pool (`V3_RESILIENT_BIPEDS`)

29 c-prefixes selected from tags using:
  - `anim_class == 'humanoid'`, `locomotion == 0` (foot)
  - `size_class in {'M', 'L'}`
  - Not boss-tier (no `expects_boss_arena`, no `has_boss_reward`)
  - Not script-spawn (no MSB placements anyway)
  - Not heritage-imported (avoid chr-import quirks)
  - HP < 1500 (excludes incidentally-large boss-tier entries)

Covers Exile/Banished Soldiers, Skeleton variants, Wandering Nobles, all
ER soldier-tier (Godrick/Leyndell/Radahn/Mausoleum/Raya Lucaria foot),
Misbegotten, Albinauric, Page, Marionette, Fire Monk, Man-Serpent, etc.

### Implementation

  - 3 new constants + `is_fragile_slot()` helper added to `oops_v3.py`
    near `V3_AERIAL_TARGET_SKIP`.
  - `pick_target_cp()` signature extended with `slot_msb_name`, `slot_pi`,
    `slot_variant_name` kwargs. Restriction applied right after the aerial-
    skip block.
  - `pick_target()` wrapper and `pick_cluster_target_cp()` forward the new
    params. Cluster path uses T2 (whole-map) only — T1/T3 don't apply
    cleanly when one target is locked across multiple Parts.
  - Main shuffle call site passes `os.path.basename(input_path)`,
    current `pi`, and `recipient_variant.get('mmv_name', '')`.

### Known not-fixed

  - Existing v0.18 high-y Rat outliers (2/11 placements at y>=30 on
    m60_44_37_50). Slot_y propagation issue, separate from fragile-slot.
  - Specific cathedral wolf/humanoid slots in `m60_43_37_xx` /
    `m60_43_38_xx` overworld grid cells that broke Octopus in playtest
    seed 162498. These are NOT in V3_FRAGILE_MAPS (those cells contain
    plenty of working slots too), and source variants are plain
    (`Wolf`, `Demi-Human`, `Starcaller`) without qualifiers — escaping
    T1 + T2. Will populate `V3_PROBLEM_SLOTS` in subsequent patches as
    playtest pinpoints them.

---

## v0.19.1 — Cluster-blind by default

The "Cluster-aware swaps" GUI default flips from ON to OFF. Every Part
now rolls independently unless you explicitly check the box.

Rationale: cluster preservation was originally default-ON out of caution
about shared-healthbar fights (Crystalian Alliance, Oracle Envoys, Maris
Tendrils). v0.12 testing confirmed Tendrils function independently
without Maris, and the Maris fight itself is protected separately via
`V3_EXCLUDE_SOURCE_PREFIXES`. Cluster-blind mode delivered 2–3x more
variety per shared-arena map in that testing.

Theoretical risks (Crystalians etc.) remain untested, so the toggle
stays available — flip it back ON if a multi-Part fight breaks in
playtest. The label and tooltip are updated to reflect the new framing
("turn ON to coordinate" rather than "turn OFF for chaos").

No code changes other than the GUI default + label text. All other
v0.19 behavior unchanged.

---

## v0.19 — Manual tag promotion for scripted-spawn boss-tier c-prefixes

### What changed

Some NR boss-tier enemies are spawned by event scripts at fixed arena
locations rather than being placed in MSB Parts data. These never appear
in the rando's tag database (which is built from MSB scanning), so they
can't be selected as swap targets — even though their chr files,
NpcParam rows, and animations are all fully present in NR's regulation.

This release adds a `manual_promotions.json` file that authors tag +
variant data for these script-spawn c-prefixes from regulation data
directly, then merges them into the tag/roster pools at load time.

Promoted entries are **target-only**. They never appear as source slots
even when they have rare MSB placements (e.g. Ancestor Spirit at certain
field locations) — those stay vanilla so we don't disrupt scripted
encounters.

### Identification work (cross-referenced against Smithbox Paramdex)

Cloned `soulsmods/Paramdex` and read `NR/Names/NpcParam.txt` (2013 named
rows) to build a definitive c-prefix → name table for NR. Major findings:

  - **c52101–c52110 are the playable Nightfarers** (Wylder, Guardian,
    Ironeye, Duchess, Raider, Revenant, Recluse, Executor) — NOT enemies.
    These were previously suspected as Night Bosses; they're player chrs.

  - **c4670 in NR is Ancestor Spirit, not Crucible Knight.** NR reassigned
    the c-prefix relative to ER. ER's c4670 = Crucible Knight; NR's
    c4670 = Ancestor Spirit. The actual NR Crucible Knight is c2500
    (already MSB-placed and tagged).

  - **6 Dark Souls Night Boss imports** confirmed: c7700 Gaping Dragon
    (DS1), c7710/c7711/c7712 Centipede Demon + Grubs (DS1), c7800 Duke's
    Dear Freja (DS2), c7820 Smelter Demon (DS2), c7900 Nameless King
    + c7910 Storm King (DS3), c7920 Dancer of the Boreal Valley (DS3).

  - **Full Nightlord roster** mapped: c7500 Gladius, c7510/c7511 Adel,
    c7520 Gnoster, c7540 Maris, c7560/c7561/c7570 Libra, c7580 Heolstor,
    c7600 Fulghor, c4900/c4901 Caligo. Tricephalos likely lives at
    c7530 / c7541 (names not yet in Paramdex).

  - **c60003 + c70003 are NPC-Nightfarer enemies** (Night Assassin,
    Night Hunter, Night Idol, etc.) — the rival-Nightfarer-style
    invaders, not Nightlords.

After cross-referencing all 52 script-spawn boss-tier c-prefixes against
the existing tag set + heritage_pack v9 imports, only 4 were genuinely
missing from the rando's reach:

| c-prefix | name                              | category          |
|----------|-----------------------------------|-------------------|
| c4670    | Ancestor Spirit                   | Field Boss (NR)   |
| c4690    | Grafted Scion                     | Field Boss (NR)   |
| c7900    | Nameless King                     | Night Boss (DS3)  |
| c7910    | Storm King (Nameless King Mount)  | Night Boss (DS3)  |

### Implementation

  - New file `manual_promotions.json` with tag fields + synthesized
    variants for the 4 c-prefixes. Tag fields derived from real NR
    NpcParam (hp, hit_height, team, behaviorVariationId), variant names
    from Paramdex.

  - `oops_v3.load_data()` now merges `manual_promotions.json` into
    `tags{}` and `roster.all_variants{}`. Auto-detected tags take
    precedence — promotion entries skip merge if c-prefix is already
    MSB-placed.

  - Three source-side guards added to skip script_spawn-tagged entries
    when iterating Parts:
      - In `analyze_at_risk_set` (line ~905)
      - In `build_cluster_catalog` source iteration (line ~1670)
      - In main `shuffle_msb_v3` per-Part loop (line ~1733)
    These keep rare MSB placements of these c-prefixes vanilla.

### Verification (seed 715768 + 5 alternate seeds)

  - All 4 promoted c-prefixes: 0 source slots ✓ (target-only)
  - c4690 Grafted Scion: 2–5 placements per seed
  - c7900 Nameless King: 3–9 placements per seed
  - c7910 Storm King: 3–8 placements per seed
  - c4670 Ancestor Spirit: 0–3 placements per seed (rare due to narrow
    XL quadruped_large loco=3 bucket competing with c3160 Funeral Steed,
    c3250/c3251/c3252 Tree Sentinel variants, c4950 Tibia Mariner —
    6 candidates for ~7 slots)
  - All v0.17 fixes hold: 0 intra-anim_class loco mismatches; 0 c3150 /
    c3160 source randomizations

### Known issues (carrying over from v0.18)

  - **2 high-y Rat placements survive the v0.18 fix.** Down from
    42/50 (84%) to 2/11 (18%) but two outliers at y=31.05 and y=88.05
    on m60_44_37_50 still slip through. Both at the same map, same
    src=c4070 Wolf. Slot_y read path investigation deferred.
  - **Cathedral Land Octopus** issue still pending — needs map ID from
    user. Vanilla c4230 goes high-y (max=156) so blanket rule wrong.
  - **Tunnel slots** still need screenshot + characterization.

---

## v0.18 — Rat-on-cathedral-ruins fix

### Single-fix release while we sort out the broader cathedral / tunnel issue

**Bug**: Reported in playtest — Rats placed at elevated cathedral ruins
behave broken (stuck / unreachable / pathfinding fails). Confirmed via
y-distribution audit on seed 715768:

  c4080 Rat vanilla source placements:  15 slots, max_y=4, mean=2 (all
                                         ground-floor sewer/cellar)
  c4080 Rat target placements in seed:  50 slots, 42 at y>=30 (84%)

Vanilla NR never places Rats above y=4. The rando was scattering them
across rooftops, towers, ruined balconies — totally out-of-distribution.

**Fix**: Added `'c4080': 30.0` to `V3_AERIAL_TARGET_SKIP`. Rats now skipped
as targets when slot vanilla y >= 30. They still fill the ~50% of vanilla
Rat-source slots at low-y (which are correctly low-y placements in the
seed).

### Still pending

The wider "cathedral ruins / tunnel slot" issue mentioned in the same
playtest is not addressed in this version — it's not a generalizable
high-y problem (Land Octopus, the other reported case, has vanilla
placements up to y=156 so a y-threshold rule wouldn't catch it). Need
more specifics on which maps / what failure mode to write a targeted
rule.

## v0.17 — Visual coherence fixes (loco compat + rider+mount preservation)

Two fixes informed by playtest feedback from a v0.16 cluster_aware=False run.

### 1. Intra-anim_class locomotion match

**Bug**: A Wolf-source slot (c4070, quadruped, locomotion=3) was randomized
to Stray (c4161, quadruped, locomotion=0). Both pass the broad anim_class
gate (quadruped) and the locomotion macro gate (ground), but their
underlying animation rigs are skeleton-incompatible — Stray's loco=0
walking rig doesn't retarget cleanly onto a slot expecting loco=3 running
animations. Result: visible T-pose / animation freeze on placement.

The bug only manifests through stage-2 fallback (when the strict-tuple
pool is small enough to trigger the wider anim_class+size pool) or
through the size-down rescue. Stage-1 strict pool already enforces exact
locomotion match via the loose tuple `(size, loco, team)`, so naturally-
populated pools were fine.

**Fix**: New `_LOCO_SENSITIVE_ANIMS` set in `swap_compat.py` — anim_classes
where intra-class locomotion mismatch breaks rendering: humanoid,
quadruped, quadruped_large, misc.

When slot and candidate share an anim_class in this set AND have differing
locomotion field values, both `is_compatible` (strict) and
`is_compatible_size_down` (rescue) now return `False`. Cross-anim_class
swaps stay unaffected — when rescue brings a humanoid into a quadruped
slot, the candidate's full skeleton replaces the slot's, so loco doesn't
need to align.

**Verification (seed 715768)**:
- Before: 4 intra-quadruped-S loco mismatches in the seed (one of which
  was the playtest-reported pi=21 c4070→c4161 at m38_00)
- After: 0 mismatches
- Wolf slot (154 occurrences) target distribution stays diverse
  (20 distinct targets vs 24 before; same 154 slots filled)
- Top picks now correctly skew toward loco=3 peers (Rat, White Wolf)
  with cross-class fillers (Maris Jellyfish, Putrid Flesh, etc) — these
  all bring their own skeletons so they render fine

### 2. Night's Cavalry rider+mount preservation

**Bug**: At m49_28_00_00 (Twin Cavalry Night Boss arena), vanilla NR has 4
entity slots forming 2 rider+mount pairs:

  pi=2 c3150 (rider) + pi=4 c3160 (Funeral Steed)
  pi=3 c3150 (rider) + pi=5 c3160 (Funeral Steed)

NR's encounter logic ties all 4 entity_ids into the boss event AND has
EMEVD scripts handling mid-fight dismount/remount. The remount logic
references the c3160 mount entity by entity_id; when the rando swaps
that entity to a non-mount enemy (in the playtest: Draconic Tree
Sentinel, Tibia Mariner), the rider's remount call still fires but
mounts something visibly wrong, AND the encounter completion graph
expects all 4 entity_ids to be defeated, which fails when paired
semantics are broken.

The user reported this as "made it to night 2 boss and it was tree
sentinel + 2 royal cavalrymen, only two of them were wired up to boss
health bars and i couldnt get through the encounter". The Night's
Cavalry rider was unable to resummon their horse mid-fight.

**Fix**: Added `c3150` (Night's Cavalry rider) and `c3160` (Funeral
Steed) to `V3_EXCLUDE_SOURCE_PREFIXES`. These slots now stay vanilla
everywhere they appear — both at the dedicated boss arena (m49_28) and
at overworld Cavalry encounters.

Trade-off: loses variety on Night's Cavalry placements specifically,
but eliminates the unwinnable-encounter hazard. They're highly
recognizable boss encounters that arguably deserve to stay
canonical anyway.

### What didn't change

- Cluster_aware mode toggle remains unchanged. The wolf cluster bug was
  a compat issue, not a clustering issue — fix #1 makes Wolf slots
  render correctly under both `cluster_aware=True` and `False`.
- The shared-arena ghost issue from a previous screenshot is unaddressed
  in this version. Need a map identifier to add it to
  `V3_SHARED_ARENA_MAPS`.

## v0.16 — Heritage tab: ER → NR import scanner

### What's new

The Heritage tab is split into two sub-tabs:

  - **Multiplayer safety** — the existing toggle + heritage explainer
  - **ER import scanner** — diff Elden Ring + Nightreign regulation
    Smithbox dumps to find c-prefixes that are GO-tier in NR (full param
    data) but missing from the heritage_pack import set. These are ideal
    chr-copy candidates that don't need regulation patches.

### Workflow

1. Fill in the four paths (paths persist across sessions):
   - ER regulation dump dir (Smithbox CSV export of base ER `regulation.bin`)
   - NR regulation dump dir (Smithbox CSV export of vanilla NR `regulation.bin`)
   - ER chr/ folder (optional — adds file-presence check)
   - NR chr/ folder (optional — detects already-shipped chrs)

2. Click 🔍 Scan. Diff runs in a worker thread (CSV loading takes 3-5s
   for the full ER NpcParam table). Status bar shows progress; Generate
   Rando is unaffected.

3. Sortable results table with columns: c-prefix, name (from heritage
   plan), status (GO/WARN/HARD/NR-ONLY), ER+NR variant counts, max HP,
   already-in-heritage, in-rando-tags, ER chr present, NR chr present,
   notes. Click any column header to sort by it; click again to reverse.

4. Filters: status (GO / WARN / HARD / NR-only / All), hide-already-imported
   (default ON, so the table shows only candidates worth working on),
   only-if-ER-files-present (filters to candidates you can actually
   chr-copy right now).

5. "Save manifest as JSON..." writes the current scan to a file the
   batch_import flow can consume.

### Status meanings

  - **GO** — NR has full NpcParam + ThinkParam. heritage_pack chr-copy
    alone will work; no regulation patch needed.
  - **WARN** — NR has NpcParam but ThinkParam is missing (or other
    dependencies). Use heritage_pack with `--allow-warnings`. AI may
    have gaps.
  - **HARD** — NR has zero regulation data. Needs
    `heritage_regulation_patch.py` to extract ER rows and Smithbox
    import them before chr-copy will work.
  - **NR-ONLY** — c-prefix exists in NR but not in ER (NR-original or
    NR DLC addition). Informational; nothing to import.

### What the v0.16 scan reveals against vanilla NR (no DLC)

  - GO unimported: **48 c-prefixes** with full NR param support but not
    in the current heritage set. Top 5 by ER variant count: c3360, c4190,
    c3210, c4192, c4316. Includes c4670 Crucible Knight and c8100
    Pumpkin Head (both flagged as future targets in heritage_pack README).
  - HARD-blocked: 446 ER c-prefixes need regulation patches. Highest-
    variant boss-tier candidates: c5170 (16000 hp), c5790 (5236 hp),
    c2010 (3491 hp).
  - NR-only: 66 c-prefixes including the c52101-c52110 block (likely
    NR DLC's Knight Artorias / Demon Prince / Mohg port targets) and
    c70003 (60 variants — probably NR Dreglord with all phases).

### Caching

Scan results cache to `heritage_scan_cache.json` next to the GUI
script. Reopening the GUI loads the cached scan immediately, so the
table is populated without re-running. Click Scan to refresh.

### CLI mode

heritage_scan.py also runs standalone for scripting:

  python heritage_scan.py \
      --er-reg-dir /path/to/er/dump \
      --nr-reg-dir /path/to/nr/dump \
      --heritage-plan batch_import_plan_comprehensive.json \
      --rando-tags nr_enemy_tags.json \
      --out import_candidates.json \
      [--er-chr-dir ...] [--nr-chr-dir ...] \
      [--status GO]

### Bundled

`batch_import_plan_comprehensive.json` from heritage_pack v9 ships
alongside the rando — gives the scanner human-readable names for the
47 already-imported prefixes.

## v0.15 — UI: mod folder auto-deploy + Heritage tab

### Mod map folder auto-copy

New "Mod map/mapstudio" picker on the main tab. When set, the GUI copies
the finished `*.msb.dcx` files from the output folder into this directory
right after a successful run — no more manual drag-and-drop into the me3
profile.

Behavior:

  - Optional. Leave blank to keep the old workflow (manual deploy).
  - Validates the path exists before kicking off the run; if missing,
    prompts the user to skip auto-copy or cancel and fix the path.
  - Copies only `.msb.dcx` files. Doesn't touch unrelated files in the
    target directory (vanilla .dcx for hub-passthrough maps, other mod
    files, etc.) — only files we generate get overwritten.
  - Persisted across sessions via `.4laric_settings.json` next to the
    GUI script. Same file also persists Vanilla MSBs and Output paths
    so the user only has to pick them once.

### Heritage / Multiplayer tab

Moved the "Multiplayer-safe" toggle off the cluttered main tab onto a
dedicated tab. The toggle still works the same way — what changed is:

  - Full explainer text on the tab covering what the heritage_pack is,
    when heritage chrs are safe, when they break coop, and what the
    multiplayer-safe toggle actually does at runtime.
  - Live count of known heritage prefixes in the current build (read
    from `oops_v3.V3_HERITAGE_ALL_PREFIXES`).
  - Default is still ON (safe-by-default for any session that might
    involve coop).

### Settings persistence

New `.4laric_settings.json` file (next to the GUI script) stores:

  - `input_dir` — Vanilla MSBs path
  - `output_dir` — shuffled MSBs path
  - `mod_map_dir` — mod profile map/mapstudio/ path

Saved automatically when Generate Rando is clicked. Read on launch to
pre-fill the picker entries. Existing `.4laric_emevd_paths.json` for
EMEVD installs is unchanged — separate file, separate concern.

## v0.14 — Coverage diagnostic accuracy + Maris cluster unblock + Wolf rescue

### Investigation: the "33 hard zeros" were mostly fake

Earlier coverage_sim runs reported 33 c-prefixes never placed across 200
seeds. Real rando spoiler analysis showed 26 of those 33 were getting
30-65 placements per seed in actual gameplay. The diagnostic was running
against `nr_boss_slots.json` (~120 boss slots) instead of the full
~3886-Part vanilla MSB population, which is what the real rando
processes. Boss slots skew M/L/XL/XXL, so size=S c-prefixes that have
plentiful overworld slot positions (Small Land Octopus, Crab, Stray,
Imp, Commoner, etc) appeared as "hard zeros" purely due to slot
sub-population bias.

### What's actually fixed in v0.14

**1. Maris cluster arena flag — real bug from v0.11**

Setting `expects_boss_arena: True` for cluster-member tags (c5110
Tendril, c4181 Jellyfish, c3610/c3620 Oracle Envoy, c4060/c4363 horses)
turned out to be wrong. That flag means "this candidate REQUIRES an
arena slot," so `is_compatible` was hard-rejecting all 16 non-arena
slots that wanted these prefixes.

Fixed: set `expects_boss_arena: False` on all six cluster-member tags.

Result on seed 78699 real rando:
  Maris' Jellyfish (c4181):    0 → 61 placements
  Oracle Envoy (c3610):        0 → 16 placements
  Oracle Envoy Large (c3620):  2 → 27 placements
  Maris' Tendril (c5110):      6 → 36 placements

**2. Wolf compat-black-hole rescue**

Wolf (c4070) had 154 vanilla source slots but only 5 placements as a
target across the seed 78699 spoiler. Its loose-tuple (quadruped, S,
loco=3, team=6) is shared only with c4071 White Wolf (8 vanilla) and
c4080 Rat (15 vanilla) — small total tuple group, and quadruped S is
rare in slot populations so Wolf rarely gets sampled.

`V3_COMPAT_BLACK_HOLE_PREFIXES = {'c4070'}` adds Wolf to slot pools
whenever the slot's anim_class+size matches (via stage-2 fallback
intersection), regardless of whether stage-1 strict pool was already
non-empty. Single c-prefix added per-slot to avoid pool inflation.

Initially tested with 6 c-prefixes (Wolf, White Wolf, Rat, Avionette,
DoR, Stray DLC), but humanoid prefixes (Avionette, DoR) overshot to
250+ placements/seed because humanoid is a large slot class and they're
the only humanoid loco=5 candidates. Trimmed to Wolf only.

Result on seed 78699 real rando: Wolf 5 → 50 placements (10x).

**3. coverage_sim accuracy**

Now uses `nr_all_slots.json` (full 3886-Part vanilla slot list) by
default. Boss-slot-only mode preserved via `--boss-only` flag for
boss-tier specific coverage measurement.

Generated `nr_all_slots.json` once from a vanilla MSB scan; the slot
distribution is seed-independent so the file is static reference data.

### What was tried and reverted

- **Variety trickle (V3_VARIETY_TRICKLE_ADDITIONS)**: forced injection of
  2 random at-risk candidates per slot regardless of pool size. Caused
  Avionette/DoR overshoot to 250+/seed. Disabled (set to 0).
- **At-risk-S weight boost (V3_AT_RISK_SMALL_WEIGHT)**: 2.5x sampling
  weight for at-risk size=S candidates. Same overshoot problem when
  applied broadly to humanoid pools. Disabled (set to 1.0).

The diagnostic showed natural distributions are mostly fine once the
Maris arena flag and Wolf BH issues are fixed. Aggressive boost
mechanisms aren't needed.

## v0.13 — Merchant model swap

User feedback: "Merchant: want to get back into shuffling the model for the
merchant in limveld without regressing the issue where merchants would
replace enemies"

### What it does

New post-pass that swaps the visual MODEL of merchant Parts to one of a
curated humanoid pool, while leaving NPCParam/ThinkParam intact. The
merchant continues to function as a merchant (same shop, same dialogue,
same interaction) but visually appears as a different enemy.

### Why a separate pass (vs main shuffle)

The previous attempt at merchant model swap regressed by going through
the main rando, which swaps NPCParam alongside MODEL_INDEX. Result:
merchants got their NPCParam swapped to enemy NPCParam and turned
hostile (or worse, enemies got merchant NPCParam and stopped fighting).

The v0.13 mechanism explicitly only writes MODEL_INDEX:

  struct.pack_into('<i', out, po + PART_OFF_MODEL_INDEX, new_midx)
  # NPCParam (0x6c) and ThinkParam untouched

Identifies merchant Parts by NPCParam ID (32000000 Nomadic, 44910000
Small Jar) rather than c-prefix — guarantees we're targeting actual
merchants, not a Part that happens to use the c3200 model elsewhere.

### Curated pool

`V3_MERCHANT_MODEL_POOL` — ~30 humanoids selected for variety + comedic
value:

  - Knights (Banished, Bloodhound, Godrick, Leyndell, Redmane, Mausoleum)
  - Soldiers + bandits (Leyndell, Radahn, Highwayman, Vulgar Militia)
  - Bosses-as-merchants (Omen, Crucible Knight, Elemer, Godrick the
    Grafted, Death Knight, Wormface, Man-Serpent)
  - Beasts (Large Demi-Human, Demi-Human Chief, Mad Pumpkin Head x2)
  - Undead/cultish (Giant Skeleton, Putrid Corpse, Albinauric, Perfumer,
    Glintstone Sorcerer, Page, Battlemage, Fire Monk x2)
  - DLC roster (Fire Knight, Imp Lion Head, Man-Fly, Curseblade,
    Horned Warrior)

If a model isn't already loaded in the merchant's MSB, `find_or_add_model`
adds it (same mechanism the main rando uses).

### Verification (seed 78699)

Pool draw delivered:
  Mausoleum Knight, Radahn Soldier, Omen, Putrid Corpse, Elemer of the
  Briar, Fire Monk, Godrick Knight, Mad Pumpkin Head, Curseblade, Omen
  again, Leyndell Knight, Albinauric, Perfumer, Page, Godrick the
  Grafted, Large Demi-Human

20 of 22 merchants swapped (the other 2 are at hub-passthrough maps:
m10_00 Roundtable Hold and m37_90).

### Access

  CLI: `oops_v3.py shuffle <in> <out> --merchant-models`
  GUI: New checkbox "Shuffle merchant models" in the main window.
       Default OFF (preserves vanilla merchants until opted in).
  Programmatic: `cmd_shuffle_v3(..., merchant_model_swap=True)` or
                `rando_pipeline(..., merchant_model_swap=True)`

### Compatibility

Stacks cleanly with all other v0.12 features (cluster_aware, etc.) and
v0.10 (aquatic compat opening). Verified end-to-end with cluster_aware=
False + merchant_model_swap=True together.

## v0.12 — Cluster-blind mode (cluster_aware=False)

User feedback: "the tendrils do function independently eh even without maris
present. maybe other cluster members too tbh. can we add a mode that is just
not cluster aware at all? i want to test if cluster preservation is still
necessary."

### What it does

New parameter `cluster_aware` (default `True`) on `cmd_shuffle_v3`,
`shuffle_msb_v3`, and `rando_pipeline`. When `False`:

  - Cluster computation skipped entirely (`compute_part_clusters`
    returns empty dict)
  - `cluster_to_parts` is empty → all Parts go through the solo-roll
    path in the swap loop
  - Cluster catalog also skipped (no expensive vanilla cluster scan)
  - Each Part picks its own target independently regardless of spatial
    proximity to other Parts

### Effect (seed 78699, cluster_aware True vs False)

  Total distinct targets:    163 → 172 (+9)
  Top 5 placement counts:    similar (cap still active)

  m46_50 (Evergaol arena):    9 → 18 distinct targets per map
  m46_60 (Evergaol arena):    4 → 12 distinct targets per map
  m32_10 (encampment hub):   23 → 37 distinct targets per map

Within-arena variety is the big win. Each member of a 3-knight
encampment can now become a different enemy. The 6 Evergaol slots at
m46_60 produce 12 different enemies instead of 4.

### Maris arena still preserved

m19_00 (Maris boss arena) keeps its 0 swap entries even in
cluster-blind mode. The Maris cluster members (c5110, c4181, c3610,
c3620) are protected by `V3_EXCLUDE_SOURCE_PREFIXES`, which is a
separate concern from clustering. cluster_aware=False doesn't override
that. If we want Maris's tendrils to randomize too, we'd remove from
that exclusion in a future iteration.

### Caveats

Multi-Part shared-healthbar encounters may behave oddly with
cluster_aware=False. Specifically:

  - Crystalian Alliance: 3 Crystalians sharing one healthbar event
    script. With cluster-blind mode, each becomes a different
    enemy; healthbar logic may target the wrong entity or the
    fight may end early/late.
  - Oracle Envoy clusters at m45_52: 47 jellyfish acting as one
    encounter. Shared spawn-trigger event could fire incorrectly.
  - Pest Threads cluster: similar shared-script multi-Part design.

User has stated previously that cluster members appear to function
fine standalone in playtest, including Tendrils placed at non-Maris
slots. cluster_aware=False is for testing whether this generalizes
across all the cluster-coupled encounters or whether some break.

### Access

  CLI: `oops_v3.py shuffle <in> <out> --no-clusters`
  GUI: New checkbox "Cluster-aware swaps" in the main window. ON by
       default; uncheck to enable cluster-blind mode.
  Programmatic: `cmd_shuffle_v3(..., cluster_aware=False)` or
                `rando_pipeline(..., cluster_aware=False)`

## v0.11 — Untagged-prefix tagging pass

User feedback after v0.10 playtest:
> "any tendril anywhere in the seed? i haven't seen tendril in a while"
> "we can just tag the tendrils and remaining untagged"

### Diagnostic

In v0.10, 18 c-prefixes appeared in `nr_enemy_roster.json` (i.e., they
have NPCParam variants and vanilla MSB placements) but had NO entries
in `nr_enemy_tags.json`. As a result, they were invisible to most of
the randomizer:

  - `compatible_pool()` is built from `bank_to_prefixes` which is derived
    from tag data — untagged prefixes don't appear in any pool, so they
    never get picked as swap targets.
  - As sources, they go through swap with `tags.get(cp, {}) → empty
    dict`, which makes them treated as `'misc'` anim_class by default.
    Compat checks may pass but pool quality is degraded.

The 18 untagged prefixes break down as:

  Cluster-only / mount entities (still excluded as targets even with tags):
    c5110 Maris' Tendril         (94 placements)
    c4181 Maris' Jellyfish       (56 placements)
    c3610 Oracle Envoy            (21 placements)
    c3620 Oracle Envoy (Large; Cathedral) (4 placements)
    c4060 Kaiden Sellsword's Horse  (12 placements, mount)
    c4363 Lordsworn Knight's Horse (Night Boss)  (8 placements, mount)

  Non-combat entities (now properly excluded everywhere):
    c2150 Lightning Ball          (projectile)
    c3200 Nomadic Merchant         (NPC, candidate for merchant model swap)
    c4191 Scarab                   (loot bug)
    c4491 Small Jar Merchant       (NPC; was already excluded)
    c4961 Sebastian                (special story; was already excluded)
    c8130/c8131/c8132 Training Post (already excluded)
    c8911 (unknown)                (1 placement; safe-skip)
    c7580 (unknown)                (Nightlord-tier, already excluded)

  Regular enemies that just hadn't been tagged:
    c4480 Miranda Blossom         (XL plant Field Boss with reward)
    c4481 Miranda Sprout          (M plant mob, cluster member with c4480)

### What v0.11 does

1. Adds the 18 missing tags to `nr_enemy_tags.json` with size_class,
   anim_class, expects_boss_arena, locomotion, team. Cluster-only
   entries get an informational `_cluster_only: true` flag.

2. Updates V3_EXCLUDE_PREFIXES to explicitly include the non-combat
   entities (c2150, c3200, c4191, c8911) — previously these were
   randomization-undefined; now their behavior is predictable.

3. The 4 Maris cluster prefixes (c5110, c4181, c3610, c3620) had
   already been removed from V3_EXCLUDE_TARGET_PREFIXES per prior
   user request, but were not appearing because they had no tags
   to be reachable through `compatible_pool`. With v0.11's tags,
   they're reachable; the v0.10 spoiler had 0 placements; the same
   seed under v0.11 has:

     c5110 Maris' Tendril:   0 → 6 placements (at m34_00, m60_44_36)
     c3620 Oracle Envoy (L): 0 → 2 placements
     c4480 Miranda Blossom:  source-only (5 vanilla parts swapped out)
     c4481 Miranda Sprout:   53 source / 4 target (now appears at non-Miranda slots)

   c4181 (Maris' Jellyfish) and c3610 (Oracle Envoy) still 0 in this
   seed but the candidate pool now includes them — variance across
   seeds.

4. m19_00 (Maris boss arena) still has 0 swap entries — the Tendril
   cluster's enormous size (~150 members) prevents the cluster system
   from finding a target. Original Maris encounter is preserved.

### Coverage delta (100-seed sweep)

  Eligible target pool: 183 → 187 (+4 newly-reachable c-prefixes)
  Hard zeros (never placed): 35 → 33 (-2 — Miranda Sprout + Tendril
  now appearing in some seeds)

### Standalone Tendril behavior

User had previously confirmed: "i've seen it work in a lot of slots
already, including the like giant rat in small castle basement that
doesn't have a ton of candidates." So standalone Tendrils visually
work as ground-rooted whip enemies even without a Maris parent body.
Same applies to Oracle Envoy Large.

If a specific Tendril or Oracle Envoy placement looks broken in
playtest (rooted in midair, missing animations, etc.), tag the
specific c-prefix with stricter constraints or move to
V3_AERIAL_TARGET_SKIP / V3_GHOST_EXCLUDE_TARGET_PREFIXES.

## v0.10 — Aquatic class opening + bat aerial alternatives

Two related variety improvements from user feedback after playtesting v0.9:

> "Bats: would be interested in trying some other flying enemies: jellyfish,
>  scorpion spiders, flying ants, some of the floating blobs"
>
> "Aquatic tag: can probably just get rid of eh, game doesn't really have
>  swimming or water beyond cosmetic"

### Fix 1: Aquatic anim_class compat opening

Original swap_compat held `aquatic` as a closed pool with no cross-class
swaps. Justification at the time: "Crayfish/Crab/Octopus share movement
physics that don't translate to ground or flying."

Reality check for NR specifically: the game has no underwater/swim
mechanics. "Aquatic" enemies (Crab, Octopus, Spider Scorpion, Land
Squirt, Crayfish, Spirit Jellyfish) are placed all over terrestrial
maps in vanilla — they walk around on land like quadrupeds. The
"aquatic" tag is a vestige from base ER mechanics that don't
materialize in NR.

#### The change

Added five new compat pairs in swap_compat.py:

  frozenset({'aquatic', 'humanoid'})
  frozenset({'aquatic', 'quadruped'})
  frozenset({'aquatic', 'quadruped_large'})
  frozenset({'aquatic', 'misc'})
  frozenset({'aquatic', 'large_boss_ground'})

Also remapped `LOCOMOTION_MACRO['aquatic']` from 'water' to 'ground' so
the size-down rescue treats aquatic candidates as ground-locomoting
for cross-class rescue eligibility.

#### Effect (seed 78699 v0.9 vs v0.10)

  Aquatic-as-target placements at non-aquatic slots:  0 → 323
  Spirit Jellyfish placements:                       19 → 21 (now appearing at 9 different humanoid/quadruped source types)
  Land Squirt placements:                            27 → 85
  Coverage hard zeros (100-seed sweep):              42 → 35 (variety reaches 7 more prefixes)

Notable new placements: Spirit Jellyfish at Crystalian/Omen/Wormface
slots, Land Squirt at Foot Soldier slots, Spider Scorpion replacing
encampment grunts. Aquatic enemies were previously locked away from
~90% of the slot pool; they now fill slots all over the map.

### Fix 2: Bat aerial alternatives

Replaced V3_AERIAL_SOURCE_SKIP for bats (c4200/c4201) with a new
V3_AERIAL_SOURCE_ALT mechanism. Where the v0.3 mechanism kept bat
positions vanilla at y >= 50 (because ground-loco swaps would freeze
on the perch), v0.10 allows swaps at those positions but restricts
the candidate pool to a curated whitelist of c-prefixes that vanilla
NR validates as aerial-capable.

#### The whitelist

Empirically validated against vanilla y-distribution:

  c4180 Spirit Jellyfish:        12/32 vanilla at y>=30 (floats)
  c4280 Giant Ant:               37/48 vanilla at y>=30 (climbs cliffs)
  c4170 Putrid Flesh:            27/41 vanilla at y>=30 (clings to walls)
  c4440 Land Squirt:             27/27 vanilla at y>=30 (clings everywhere)
  c4040 Slug:                    18/47 vanilla at y>=30 (climbs)
  c2041 Kindred of Rot Larva:    22/25 vanilla at y>=30 (on walls)

Plus the original bats themselves (c4200 Man-Bat, c4201 Operatic Bat —
6/13 of c4201 placements at y>=30) so seeds with bats at high-y can
still roll bat→bat. Spider Scorpion (c5190/c5192/c5193) included
experimentally despite no vanilla data; user wishlist match.

#### The mechanism

When pick_target_cp evaluates a slot whose recipient is c4200 or
c4201 AND the slot's vanilla y >= 50.0:

  1. Compute chosen_pool normally (compat + cap + tier-preserve)
  2. Filter chosen_pool to V3_AERIAL_SOURCE_ALT[recipient_cp]['alternatives']
  3. If filtered pool non-empty: pick from it
  4. If filtered pool empty: return None (caller treats as skip,
     n_skipped_aerial++ — preserves v0.3 fallback semantics)

#### Effect (seed 78699 with v0.10)

  Bat slots at y>=50:        6 (was kept-vanilla in v0.9)
  Targets picked:            6× c4280 Giant Ant (cluster picked once)

The Giant Ant choice is reasonable — sz=L matches c4201 Operatic Bat
exactly, vanilla design includes 37/48 high-y placements. In other
seeds the rng will distribute among the whitelist for variety.

If aerial-capable swap targets need expansion (more enemy types feel
right at perch positions), append to V3_AERIAL_SOURCE_ALT[cp]
['alternatives'] — curated whitelist, no global side effects.

### Compat changes are bidirectional

Note that the aquatic compat opening is two-way. Previously:
  - Aquatic source → aquatic target only
  - Non-aquatic source → non-aquatic target only

Now:
  - Aquatic source → can become humanoid/quadruped/misc enemies
  - Humanoid/quadruped/misc/large_boss_ground source → can become aquatic

So expect to see Wandering Nobles in Crab positions on coastlines, Foot
Soldiers in Spider Scorpion positions, etc. — that's intentional.

If a specific aquatic enemy (e.g. Octopus, Crayfish) breaks at a
non-aquatic slot in playtest, add to V3_AERIAL_TARGET_SKIP with an
appropriate y threshold or to V3_EXCLUDE_TARGET_PREFIXES for full
exclusion.

## v0.9 — Quadruped aerial-target skip extension

User playtest report on v0.8: "still noticed like a swivel/frozen erdtree
burial watchdog and a dlc shadow dog. still some issues there."

### Diagnostic

Same y-distribution audit as v0.8's Albinauric fix, applied to quadrupeds:

  c4260 Erdtree Burial Watchdog:  3 vanilla parts, ALL at y < 30
  c5522 Stray (DLC):              0 vanilla parts (DLC roster)
  c5523 Stray (DLC):              0 vanilla parts (DLC roster)
  c4080 Rat:                     15 vanilla parts, ALL at y < 5
  c4250 Small Fingercreeper:     33 vanilla parts, 32/33 at y < 5

c4260 confirmed in vanilla as ground-only — same FromSoft design pattern
as Albinauric (sedentary AI, small footprint, simple loco=0). c5522 and
c5523 have no vanilla data but match user's "DLC shadow dog" report and
share the quadruped sz=S loco=0 profile.

### Fix

Extended `V3_AERIAL_TARGET_SKIP` with three additions:

  c4260: 30.0  # Erdtree Burial Watchdog (confirmed)
  c5522: 30.0  # DLC Stray (matches user report)
  c5523: 30.0  # DLC Stray (same family)

Same fallback policy as before: filtering empty → keep unfiltered pool.

### Verification

Seed 78699 with v0.9:

  c3470 Albinauric:                 57 placements, 0 at y>=30 ✓
  c4260 Erdtree Burial Watchdog:   13 placements, 0 at y>=30 ✓
  c5522 Stray:                      6 placements, 0 at y>=30 ✓
  c5523 Stray:                     13 placements, 0 at y>=30 ✓

### Quadrupeds NOT added (kept watching)

c4080 Rat (vanilla all y<5, 27 high-y in seed 78699), c4250 Small
Fingercreeper (vanilla 32/33 at y<5, 15 high-y), and c4150 Basilisk
(actually vanilla 21/28 at y>=100 — designed for high places) are
NOT yet added. No in-game freeze reports for these. Adding speculative
entries over-restricts the candidate pool; only added on confirmed
breakage.

## v0.8 — Albinauric aerial-target skip + m32_10 shared-arena coherence

Two fixes from in-game playtest of seeds 451358 and 78699.

### Fix 1: Albinauric aerial-target skip (the swiveling-but-frozen Albinauric)

User confirmed: at certain elevated positions (rooftops, towers, balconies),
swapped-in c3470 Albinaurics activate AI (track player, swivel head,
recognize threat) but never engage and don't react to direct hits. Same
behavior pattern as the v0.3 bat freeze, but for a regular ground enemy.

#### The diagnostic

Ran `compute vanilla y-distribution by c-prefix` against the unmodified
NR MSBs:

  c3470 Albinauric:        21 vanilla parts.  y<5: 1   5-30: 20   y>=30: 0
  c4300 Wandering Noble:  278 vanilla parts.  y<5: 43  5-30: 27   y>=30: 208
  c3661 Putrid Corpse:    192 vanilla parts.  y<5: 70  5-30: 61   y>=30: 61
  c3500 Skeletal Militia: 117 vanilla parts.  y<5: 24  5-30: 28   y>=30: 65
  c4311 Godrick Soldier:  104 vanilla parts.  y<5: 8   5-30: 18   y>=30: 78

c3470 is the only humanoid M field-tier source whose vanilla placement
distribution NEVER reaches y >= 30. From-Software clearly designed
Albinauric for ground-only patrol — its sedentary AI and small-footprint
collision capsule don't navigate elevated terrain. Wandering Noble,
Putrid Corpse, Foot Soldier etc. are designed for tower-guard duty
(hence ~50-75% of their vanilla placements at y >= 30) and they navigate
elevated patrol fine.

When the randomizer placed Albinauric at slots vacated by elevated-design
sources (Wandering Noble guard tower → Albinauric on tower rim),
the result was AI-active-but-pathfind-stuck — exactly what the user saw.

In seed 451358, 36 of 79 c3470 placements landed at y >= 30. User
verified the freeze in-game.

#### The fix

New constant `V3_AERIAL_TARGET_SKIP = {'c3470': 30.0}` — a target-side
position-aware filter. When `pick_target_cp` evaluates a slot's
chosen_pool, it filters out target c-prefixes whose `V3_AERIAL_TARGET_SKIP`
threshold is at-or-below the slot's vanilla y. Albinauric specifically
gets removed from candidate consideration for any slot at y >= 30.

Same fallback policy as the cap and the source skip: if filtering would
empty the pool entirely, keep the unfiltered pool (don't stall narrow
slots that have no other valid candidate).

For clusters, we use the cluster's *max* y across all members — if any
member is high-y, the whole cluster is treated as high-y, since all
members swap to the same target c-prefix.

This is distinct from the existing `V3_AERIAL_SOURCE_SKIP` (which keeps
bat *source* positions vanilla because their vanilla y is at perch
level no ground enemy can navigate). The bat fix prevents *outbound*
swaps; the Albinauric fix prevents *inbound* swaps.

#### Verification

Same seed (78699) with v0.7 vs v0.8:

  c3470 placements:        80 → 65  (-15, freed slots picked other targets)
  c3470 at y >= 30:        37 → 0   (zero high-y placements, fix complete)
  y range of Albinauric:   [0.0, 209.9]  →  [-0.1, 28.1]  (within vanilla)
  Top placement count:     112 → ~100  (redistributed pool flattens curve)

Coverage sweep (100 seeds): no regressions. Hard zeros 90 → 42 baseline
unchanged. Tree Spirit 3.30 → 2.66 avg/seed unchanged.

### Fix 2: m32_10 added to shared-arena coherence

User saw a ghostly figure during a "Royal Army Knights" encampment fight
on the overworld (m32_10_00_00 = the central NR field-encampment hub).
Same pattern as m46_60 — disabled-template alternates render as ghosts
of cluster targets — but at a different map.

Bonus engine detail: the user noticed an enemy (Leonine Misbegotten —
that fight's active swap target) hit the ghostly figure and it FLINCHED.
So disabled-template alternates aren't pure visual artifacts — they
have full collision and AI responsiveness, just team-suppressed against
the player. The engine behavior is more nuanced than I previously
documented in the v0.7 changelog.

#### The diagnostic

Surveyed all maps for co-located encampment-template alternate pairs
(within 30u radius). m32_10 has **28 distinct co-located pairs** —
nearly 3x m46_60's 10 pairs. Field-encampment scale rather than
Evergaol-arena scale. Multiple distinct encampment LOCATIONS spread
across the overworld map, each location with its own template-alternate
set (Misbegotten, Leyndell Knight, Redmane Knight Encampment, Leonine
Misbegotten, Pumpkin Head, etc.).

Pure c-prefix grouping (the v0.7 strategy) would WRONGLY merge all
Leonine Misbegottens across separate encampments into one swap target,
which loses encampment-by-encampment variety.

#### The fix

Refactored `compute_part_clusters` for shared-arena maps: now does
**spatial clustering at a wider threshold (V3_SHARED_ARENA_THRESHOLD =
20u) followed by c-prefix subdivision within each spatial cluster**.
The wider threshold groups encampment-local template alternates while
keeping distinct encampments apart. C-prefix subdivision then preserves
each encampment's template-group coherence.

For pure-arena maps (m46_50, m46_60) where all entries are within 5u,
spatial clustering at 20u still produces ONE cluster, and c-prefix
split yields the v0.7 behavior unchanged (verified: same per-cluster
output).

For m32_10 in seed 78699, the result is **14 distinct encampment-template
cluster groups** spread across positions like (34.1, 0.2) Misbegotten×6
→ Bear; (-46.2, 1.5) Misbegotten×9 → Cemetery Shade; (-32.3, 28.6)
Leyndell Soldier×10 → Putrid Corpse; etc. Each encampment is now
internally coherent.

Added `V3_SHARED_ARENA_THRESHOLD = 20.0` as the spatial-cluster radius
for these maps. Empirically calibrated: m32_10 encampment locations
are 60-100u apart (so they stay separate at 20u) and template
alternates within an encampment are within 5-15u (so they merge).

If more shared-arena maps surface in playtest, append them to
`V3_SHARED_ARENA_MAPS`. The other 1-pair candidates from the survey
(m32_20, m46_00, m48_50, m49_17) are borderline — only 1 co-located
pair each — and aren't included until report-driven evidence appears.

### Extending the aerial-target list

If new "swivel-but-frozen" reports appear in future seeds, run
`dev/ground_only_audit.py` (TODO) which compares each c-prefix's
vanilla y-distribution against its randomized placements. Add a
c-prefix to V3_AERIAL_TARGET_SKIP only when:

  (a) Vanilla NR places it ONLY at low y AND
  (b) In-game reports confirm it freezes/breaks at elevated positions

Without (b), avoid adding entries — most "ground-only in vanilla"
c-prefixes navigate elevated positions fine. (c4314 Radahn Soldier
has 12 vanilla parts all at y<30 yet appears 87+ times in randomized
seeds at all elevations without issue.)

## v0.7 — shared-arena coherence + target frequency cap

Two fixes from in-game playtest of seed 34874.

### Fix 1: Shared-arena map cluster split (the "ghostly Redmane")

Issue: at the Banished Knights camp encounter on m46_60_00_00, the user
saw a fully-active Redmane Knight (correct active-template enemy) plus a
ghostly non-interactable Redmane standing nearby.

Root cause: m46_60 is a **shared-arena map** that hosts multiple
encampment templates in the same MSB — Banished Knights, Crystalians,
Nox Monks, Alabaster/Onyx Lord, Bloodhound Knight, Crucible Knight all
have entities in the same area. The engine selects ONE template per
playthrough and disables the others, but disabled entities still load
their model.

Our spatial cluster algorithm (union-find with 2.0-unit threshold)
saw all these tightly-packed entities and grouped them into 3 spatial
clusters by proximity:

  - cluster 0 (north side): Banished Knights pi=1,3 + Crystalian pi=7
    + Alabaster Lord pi=9 → all swapped to Fire Monk
  - cluster 1 (south side): Banished Knight pi=2 + Nox Monk pi=4
    + Onyx Lord pi=10 → all swapped to Redmane Knight
  - cluster 2: Crystalian pi=8 + Nox Swordstress pi=5 → both Redmane

Result for the active Banished Knights template: 1 Redmane (pi=2) + 2
Fire Monks (pi=1, pi=3) — 3 vanilla Banished Knights becoming THREE
DIFFERENT enemies. AND the disabled-template alternates from clusters
1, 2 still rendered as ghosts of their cluster targets, so the player
saw a ghostly Redmane (pi=4 Nox Monk → Redmane, never enabled).

Fix: new constant `V3_SHARED_ARENA_MAPS = {m46_50_00_00, m46_60_00_00}`
(survey-identified — both have 6+ distinct boss c-prefixes packed
within a small area). For these maps, `compute_part_clusters` now
groups by **source c-prefix** instead of spatial proximity. All parts
with the same c-prefix go into one cluster, so all 3 Banished Knights
swap to the same target, all 3 Crystalians swap to a different
target, etc.

In practice, m46_60 in seed 34874 now produces:

  - cluster 0: 3× c3010 Banished Knight → all Godrick Knight
  - cluster 1: 2× c3300 Nox Monk → all Redmane Knight
  - cluster 2: 3× c3350 Crystalian → all Bell Bearing Hunter
  - cluster 3: 2× c3600 Lord → all Bell Bearing Hunter
  - cluster 5: 2× c2500 Crucible Knight → all Leyndell Knight

Each template is internally coherent. Disabled-template ghosts still
render (they're disabled-but-modeled), but at least the active fight
is consistent and all ghosts in a template-group look identical.

Caveat: this is a partial fix. Disabled-template alternates still
ghost-render visually. Eliminating them entirely would require not
swapping them at all, which means knowing at swap-time which template
will be active — and that's rolled at runtime by the engine, not
known at swap-time.

If more shared-arena maps are discovered during play, append them to
`V3_SHARED_ARENA_MAPS`.

### Fix 2: Target-prefix frequency cap (the "skeleton everywhere" problem)

Issue: c3500 Large Skeleton (Skeletal Militiaman/Bandit/Knight/Grave
Warden) placed 119 times in seed 34874 — top of the leaderboard with
a noticeable visual presence advantage.

Root cause: c3500 is humanoid M field-tier with 118 vanilla parts.
The "humanoid M field-tier rabble" pool is the largest in the game,
fed by ~750 source slots (Putrid Corpse, Wandering Noble, Exile
Soldier, Godrick Foot Soldier, etc.). Uniform sampling within that
pool gives c3500 ~17% of those rolls = ~119 placements.

Fix: new constant `V3_TARGET_PLACEMENT_CAP = 50`. The shuffle
maintains a per-target-prefix counter across all maps in a single
seed. When `pick_target_cp` evaluates a slot's chosen_pool, it
filters out target c-prefixes already at-or-above the cap. Falls
back to the unfiltered pool only if the cap would empty it (so we
don't stall on legitimately-narrow slots that have no other valid
candidate).

Counter is incremented after a successful pick. For cluster picks,
the counter increments by cluster_size at once (one per member),
which means a 30-member cluster picking c3500 right at the cap
boundary will push c3500 to 79 in one shot — the cap is a soft
upper bound, not a hard one.

Empirically on seed 34874: **c3500 dropped from 119 → 93 (-22%)**.
Top placement counts flattened: in v0.6 the spread was
119/112/97/91/90/89/89; in v0.7 it's 93/88/88/86/85/84/83/83.
The redistributed slots picked second-tier candidates from the same
field-tier humanoid M pool — Mausoleum Foot Soldier, Large Exile
Soldier, Raya Lucaria Foot Soldier, etc.

If 50 still feels too many on subsequent playtests, lower the
constant. If you want to preserve the natural Wandering Noble /
Skeleton "rabble vibe," raise it.

## v0.6 — variety pass two

Two surgical rescue extensions in response to playtest feedback.

### Fix 1: c4600 Troll → Snowfield Troll lockout

User reported "oops all snowfield troll" — too many Trolls becoming
Snowfield Trolls. Trace:

1. c4600 Troll has 18 vanilla Part placements (Castle / Mine / Plain
   variants + Headless Troll Remembrance + Frenzied Flame Troll
   Encampment).
2. The strict swap_compat filter for c4600 humanoid XXL drops 9 of
   10 raw compat candidates (cross-anim_class mismatches + arena gate
   on Gargoyle), leaving exactly **one** strict candidate: Snowfield
   Troll (sister humanoid XXL via shared anim_bank).
3. Boss-tier source variants (Remembrance, Encampment) trigger rescue
   normally — chosen_pool grows from 1 to 5 with rescue candidates
   (Bear, Pumpkin Head, etc.), Snowfield Troll drops to ~20%.
4. **But field-tier source variants** (Castle / Mine / Plain Troll —
   12 of 18 source slots) hit a quirk: the rescue function's tier-
   match check (`cand_is_boss != slot_is_boss: continue`) finds zero
   field-tier humanoid XXL candidates in the at-risk set, so rescue
   adds nothing. Those 12 slots get 100% Snowfield Troll.

Math: 12 always-Snowfield + ~1 from boss-tier rolls = ~13 Snowfield
Trolls per seed. Confirmed in seed 34874 (13 placements observed).

**Fix:** Added `relax_tier=False` parameter to `rescue_pool_for_slot`.
In `pick_target_cp`, detect when the strict tier_pool was empty and
chosen_pool fell back to the wider pool — at that point the tier-
preserve invariant has already broken, so rescue's tier check would
only block the variety we need. Pass `relax_tier=True` for that path.

Effect: **Snowfield Troll drops from 4.60 → 1.32 avg per seed (-71%).**
Still appears in 77% of seeds, just no longer dominates. The 12
field-tier Troll slots now distribute across Bear, Flame Chariot,
Giant Dog, Pumpkin Head, Godskin Noble, Stonedigger Troll, etc.

### Fix 2: Guardian Golem fort slots

Same playtest, observation: rooftop fort Guardian Golem positions
have a healthy 11-candidate strict pool, but every candidate is
"another giga ground beast" (Magma Wyrm, Decaying Ekzykes, Ancient
Dragon, Astel, Borealis, Wormface, etc). Visually monotone variety.

The existing rescue threshold (`V3_RESCUE_POOL_THRESHOLD = 5`) was
designed to fire only when the strict pool was small — 11 ≥ 5
satisfied the guardrail, so rescue never fired for these slots.
The guardrail caught "few candidates" but didn't catch "many
candidates of the same shape."

**Fix:** Added `V3_FORCE_RESCUE_ANIM_CLASSES = {'giga_boss',
'flying_dragon'}`. Slots with these anim_classes always trigger
rescue regardless of strict pool size, adding up to
`V3_FORCE_RESCUE_ADDITIONS = 4` candidates. For Guardian Golem
slots, the chosen_pool grows from 11 (all dragons / giga-beasts) to
~15 candidates including Stonedigger Troll, Great Red Bear, Golden
Hippopotamus, Divine Beast Dancing Lion. Each at ~4-5% probability —
genuine flavor variety without overwhelming the dominant giga-class
characters.

### Coverage impact

200-seed sweep before/after:

```
Hard zeros (eligible):   86 → 42  (-44 — 48 prefixes promoted out of 0%)
At-risk tail (<10%):      2 → 22  (more low-rate placements showing)
Snowfield Troll:        4.60 → 1.32 avg/seed (-71%)
Tree Spirit:            3.18 → 2.48 avg/seed (-22%)
Guardian Golem slots:   11-candidate pool → 15-candidate pool
```

The increase in at-risk tail (2 → 22) is *good* — those are 20
prefixes that previously sat at 0% now placing in 1-9% of seeds.
They moved from "never appears" to "rare but possible."

## v0.5 — packaging cleanup

Removed the `modded_emevds/` directory from the bundle. It was leftover
scratch from earlier development — held a stale copy of
`common_func.emevd.dcx.js` plus a handful of compiled `.dcx` files that
weren't referenced from the documented workflow or any code path. Its
presence was actively confusing because the stale `common_func.js`
copy made it look like a second canonical patcher output.

The documented workflow (per `WORKFLOW.md`) is unchanged: `patched_emevd/`
holds the patcher output, recompile its `common_func.emevd.dcx.js` with
DarkScript3, drop the resulting `.dcx` into your me3 profile's
`<package>/event/` folder.

Zero behavioral changes from v0.4.

## v0.4 — boss reward fix

The v0.2/v0.3 boss-reward injection was using the wrong instruction.

### Symptom

On boss kills, items were being granted directly to the player's
inventory — not the expected NR choice-of-3 reward picker. Two
failure modes observed:

1. **Wrong category.** Got Remembrances and other items that don't
   render or function correctly when received as direct inventory
   grants in NR (Remembrances expect a usage flow that randomized
   slots don't establish).
2. **Inaccessible weapons.** Even when the granted item was a
   reasonable category, weapons given via direct inventory grant
   ended up in slots NR's UI doesn't surface — player has no path
   to access them.

### Root cause

The injection was using `AwardItemLot(105030)` — an EMEVD instruction
that delivers a specific lot's contents directly to the player's
inventory. This is a real NR instruction (used in the m10 hub for
quest-style item gifts), but it's the wrong abstraction for "boss
killed → boss reward."

NR's actual boss reward mechanism is the choice-of-3 picker UI: three
items float at the boss's death location, player picks one. The
canonical instruction for this is `HandleMinibossDefeat(chrEntityId)`,
called from every vanilla per-map boss death handler (e.g. m46_50,
m34_10, m35_90, m60_4X). It routes through NR's internal reward
selection logic, which knows the correct categories and presentation.

Vanilla `common_func.emevd.dcx.js` never calls `HandleMinibossDefeat`
itself — that's why we were confused into using `AwardItemLot`. NR's
design splits the responsibilities: `common_func` runs the healthbar
and BGM lifecycle (events 90015000, 90015007, etc), and per-map files
explicitly call `HandleMinibossDefeat` for vanilla boss positions.
Randomized boss slots that lack a per-map handler got nothing.

### Fix

Replaced `AwardItemLot(105030)` with `HandleMinibossDefeat(chrEntityId)`
in both injection points:

- The 6 boss-wake handlers (90015000 family) — fires when chr2.Passed
  confirms boss death.
- The encampment-clear handler (90085016) — fires when the encampment
  leader dies and "AREA CLEARED" displays.

`chrEntityId` is in scope as a function parameter in both events.
Removed the `BOSS_REWARD_LOT_ID` constant entirely — the new
instruction takes no lot argument.

### Conflict detection

The injection marker bumped from `boss_reward_inject` →
`boss_reward_inject_v2`. The patcher now detects v0.2/v0.3-style v1
injections in the input and refuses to apply on top (would corrupt
the event flow). Re-patch from clean vanilla EMEVD.

### Trade-offs (unchanged from v0.2 architecture)

- About 28 vanilla dungeon-boss positions already have map-specific
  `HandleMinibossDefeat` calls. Those positions will trigger the picker
  twice — once from their map handler, once from this common_func
  hook. NR appears to coalesce repeat triggers; worst case is a
  redundant picker.
- If a randomized swap-in's NpcParam lacks the boss-reward-set
  config, the picker may appear empty. Not observed yet — known
  unknown.

## v0.3 — bat aerial-spawn fix

Fixes a freeze (well, a "looks frozen but is actually pathfind-stuck") for
non-flying enemies that were swapped into bat slots placed at cliff-perch
or mid-air positions.

### Symptom

In seed 614841 (v0.2 output), an Operatic Bat slot at
`m60_42_39_00 pos=(68.66, 209.78, -37.58)` was randomized to a Giant Rat.
The rat ended up on the ground at the bat's authored XZ coordinate —
visibly alive, AI-active, swiveling to face the player. But it never
moved to attack: the pathfinder couldn't compute a route from where the
rat had landed to wherever the player was approaching from.

### Root cause

Man-Bat (c4200) and Operatic Bat (c4201) are the only two enemies in the
entire roster with `locomotion=2` (the engine's flying flag). The other
flying enemies are tagged `anim_class=flying_dragon`; the bats are tagged
`humanoid M` and `quadruped L` respectively, so the size-down rescue's
locomotion macro check (which uses `anim_class`) saw them as ground-class
and allowed swaps with non-flying enemies.

The actual breakage is geometric, not engine-level: bat MSB positions
are authored for flying creatures that traverse 3D airspace (or perch
on cliffs/ledges and dive at distant targets). When a ground enemy is
swapped in, gravity drops it onto whatever surface exists at that XZ
coordinate — typically a cliff top or rooftop with no walking
connection to the surrounding terrain. The rat is now standing on a
navmesh island authored for a flier; from there, the pathfinder can't
reach the player. The rat senses the player (Recognition state fires →
visible swivel) but its movement subsystem has no valid destination.

There is no script-side fix available: zero EMEVDs reference any bat
NPCParam ID. Bats are pure MSB-spawn entities — the engine reads them
from the MSB and instantiates them at the listed positions with their
NPCParam, no scripted activation. Whether a bat slot is "safely
swappable" depends entirely on whether the surface beneath the spawn
point is connected to walkable terrain.

### Fix

New module-level config `V3_AERIAL_SOURCE_SKIP`: dict mapping c-prefix to
y-coordinate threshold. When a Part's source c-prefix is in the dict and
its MSB y-coordinate is ≥ threshold, the slot stays vanilla (skips the
swap). Lower-y placements of the same c-prefix randomize normally.

```python
V3_AERIAL_SOURCE_SKIP = {
    'c4200': 50.0,   # Man-Bat
    'c4201': 50.0,   # Operatic Bat
}
```

Threshold of 50 is a heuristic based on observed altitude distribution:
out of 128 vanilla bat parts, 57 are at y ≥ 50 (cliff-perch / mid-air —
now skipped) and 71 are at y < 50 (gliding-near-ground — still
randomize). The remaining 71 swappable bat positions cluster around
y < 35, well below any observed problem altitude.

If a y < 50 bat slot still freezes in-game on a future seed, lower the
threshold further or move the affected c-prefix to
`V3_EXCLUDE_SOURCE_PREFIXES` to bench it entirely.

The shuffle summary now reports both skip categories separately:
```
Skipped (no compat targets found): 189
Skipped (aerial source position, kept vanilla): 57
```

### What stays unchanged

- Bats can still be swap targets (no change to `V3_EXCLUDE_TARGET_PREFIXES`).
  This is intentional but slightly risky — a Bat placed in a ground slot
  will fly above the encounter point. Hasn't been reported as a problem
  yet; revisit if it becomes one.
- Coverage statistics unchanged — the at-risk computation operates on
  c-prefix granularity, not Part-position granularity.

## v0.2 — variety pass

Two changes that work together to cut the long tail of "this enemy never
shows up." Coverage data: 200-seed sweep shrank the eligible-but-unplaced
set from 106 c-prefixes to 86, and flattened the placement leaderboard
from a 6.7-per-seed top-end to ~4.2.

### Boss-tier classifier — additional signals

Previously, `is_boss_tier_prefix` only checked `has_boss_reward`,
`hit_height_median >= 4m`, or boss-marker substrings in variant names. This
mis-classified heritage imports whose variant names lack markers — Pumpkin
Head, Bloodfiend, Burial Watchdog, Battlemage, Bear, Giant Beast Skeleton —
and they all sat at 0% placement because they got filtered out of every
boss-tier slot's chosen_pool.

New rule additionally promotes:

- Anything with `has_reward=True` (the engine has a reward item lot for the
  encounter — high-confidence boss signal). Catches Burial Watchdog (HP
  1052, was 0%, now 95.5% / 2.4 placements per seed) and Battlemage.
- Heritage prefixes with `hp_median >= 300`. Heritage_pack curated these as
  significant enemies, and that HP threshold cleanly separates them from
  the 78–150 HP foot-soldier baseline. Catches Pumpkin Head (was 0%, now
  97.5%), Bloodfiend (was 0%, now 91%), Giant Beast Skeleton (was 0%, now
  94%), Bear (was 0%, now 92.5%).

The rule does not promote White Wolf, Operatic Bat, Foot Soldiers, etc. —
those still read as field-tier rabble.

### Size-down rescue

Some slot types have very small strict pools — Tree Spirit slots
(`large_boss_ground` XXL, non-arena) had exactly 4 candidates
(Hippopotamus, Death Bird, Dragonkin Soldier Ice, Giant Putrid Flesh), so
those four were guaranteed to flood every seed. Meanwhile humanoid bosses
like Mohg, Cleanrot Knight, and Death Knight had nowhere to go.

The size-down rescue allows a strictly-smaller candidate from the same
*locomotion macro* (ground / air / water — humanoid, quadruped,
quadruped_large, large_boss_ground, giga_boss all fall under "ground") to
fill a larger slot, even when the specific anim_class differs. The arena
gate still applies as a hard rule — arena=True candidates can't go into
non-arena slots, since that triggers fog-door / camera / music script
glitches.

Two guardrails to keep the rescue from over-firing:

1. **At-risk-tail only.** Computed once at startup: a c-prefix is
   "at-risk" if its expected placements per seed under strict rules is
   below 1.0. Healthy-placement enemies (Snowfield Troll, Runebear, etc.)
   keep their strict shape identity — only the long tail gets rescued.
2. **Slack-bounded augmentation.** Rescue only fires when the slot's
   `chosen_pool` is below 5 candidates, and adds at most
   `(5 - len(chosen_pool))` rescue candidates. So a 4-candidate Tree
   Spirit slot grows to 8 candidates, not 30. Bounds the per-rescue
   placement frequency.

Net effect on the Tree Spirit slot pool: 4 candidates → 12 candidates.
Ulcerated Tree Spirit's average appearances dropped from 3.54 to 2.68 per
seed (-24%), and the other three Tree Spirit-class enemies (Death Bird,
Dragonkin Soldier Ice, Giant Putrid Flesh) all dropped 15–22%.

13 c-prefixes rescued from 0% in addition to the classifier promotions:
- Royal Revenant, Cleanrot Knight, Death Knight, Mohg, Crucible Knight,
  Margit, Dancing Lion, Hippopotamus, Loretta Tree Sentinel, Godskin
  Apostle, Godskin Noble, Flame Chariot, Great Red Bear

### Tagging cleanup

The v0.1 tag set had 12 c-prefixes with no `anim_class`/`size_class` data,
which prevented them from being either placed or rescued. Walked through
each by hand:

- **2 tagged** (added to `nr_enemy_tags.json`): Cuckoo Knight (Scholar
  Remembrance) c4352 and Aged Albinauric (Scholar Remembrance) c3670.
  Both tagged as humanoid M, boss-tier via `has_reward=True`. Anim_bank
  mirrors the same-family parent (Godrick Knight 43500 for Cuckoo,
  Albinauric 34700 for Aged Albinauric). Coverage: Cuckoo Knight Scholar
  now at 93% / 3.0 placements per seed; Aged Albinauric Scholar similar.
- **9 added to `V3_EXCLUDE_TARGET_PREFIXES`**: 4 cluster-only members
  (Maris' Jellyfish, Maris' Tendril, Oracle Envoy x2 — these spawn only
  as cluster companions and have no standalone AI), 3 non-enemies
  (Lightning Ball projectile, Scarab item-drop critter, Nomadic
  Merchant NPC), and c8911 (single roster entry, no slots, unknown).
- **2 left untagged by design**: Miranda Sprout c4481 and Miranda
  Blossom c4480. These are rooted plants — they can't move. Tagging
  them as humanoid M would put random roving bosses in their slots
  (fine), but it would also let Miranda Sprout itself appear as a
  randomized boss elsewhere (motionless plant in a Crucible Knight
  slot — bad vibe). Their 11 vanilla slots stay vanilla.

### Remaining 0% enemies (intentional)

Of the 76 c-prefixes still at 0%:

- **53** are deliberate exclusions (Nightlord/Raid bosses, mount
  components, freeze-suspect heritage prefixes pending in-game test,
  cluster-only members, non-enemy entities — all intentional).
- **67** are genuine field-tier rabble — wait, that's not right.

OK, recount: of 129 total c-prefixes diagnosed (which is the full
`prefix_variants` set including deliberate exclusions):

- **53** deliberately excluded (the v0.1 set + 9 added in v0.2 tagging
  pass; see "Tagging cleanup" above).
- **67** genuine field-tier rabble (foot soldiers, Wolf, Crab, Larva,
  etc.). NR has effectively zero field-tier slots in its randomizable
  population, so giving these placements would mean promoting them to
  boss slots — Wolves and Foot Soldiers occasionally appearing as the
  boss of a small dungeon. That vibe call is left for a future version.
- **5** aquatic prefixes — vanilla NR has no aquatic slots, so there's
  nowhere for them to go without remapping locomotion at NPCParam-swap
  time.
- **2** reachable but rare (Gargoyle, Ghostflame Dragon — arena=True
  GIGA, fits very few slots; shows up at higher seed counts).
- **2** untagged Mirandas (left untagged by design).

### Tooling added

- `coverage_sim.py` — simulates N seeds and reports per-c-prefix
  placement rate, hard zeros, soft tail, top placements. Side-by-side
  before/after rescue diff.
- `zero_diagnosis.py` — categorizes every 0% prefix by structural cause
  (deliberately_excluded, field_tier, untagged, aquatic, flying_arena,
  reachable_low_freq).

## v0.1 — initial public release

First public release.

### What works

- **Vanilla-aware shuffle.** Every enemy slot in the world gets a swap target
  with matching size class, locomotion class, and animation library. Boss-tier
  swaps are restricted to boss-tier targets where possible.
- **Cluster handling, three modes:**
  - *Vanilla clusters (safest)* — multi-Part encounters left intact (default).
  - *Coordinated swap* — every cluster member becomes one shared c-prefix.
  - *Shape-matched* — clusters paired against a vanilla cluster catalog (235
    cluster instances across 38 unique shape signatures), preserving rider+mount
    semantics.
- **Oops! All mode.** Pick a single enemy, every slot becomes that enemy.
  Bypasses compatibility checking — for the chaos-pilled.
- **Standalone DCX layer.** No Yabber dependency. Python `dcx.py` finds Oodle
  via glob (any `oo2core_*_win64.dll` works) and handles compress/decompress.
- **EMEVD patches** — 4 surgical edits to `common_func.emevd.dcx` covering 61
  substitutions across the four bug classes:
  - Boss death-state hangs (no rune award, persistent corpses)
  - Wake-trigger gating (Abductor Virgin T-pose, sleeping camp enemies)
  - Spawn-emerge dormancy (mining enemies, tunnel mobs, scripted-pose idle,
    SpecialStandby family — covers ~25 distinct handlers)
  - Corpse collision blocking Sites of Grace
- **Pre-patched EMEVD shipped in the bundle** at `patched_emevd/` for
  one-click install via the GUI. Patcher script also included for advanced
  users / different NR builds.
- **Spoiler logs** — every generation produces machine-readable JSON and
  human-readable Markdown listing every swap by map, entity_id, position,
  cluster ID, and tier.
- **Dark-themed GUI** with bonfire-amber accent, color-coded log output,
  searchable target picker for Oops! All mode, cluster mode selector.
- **Multi-tier exclusion architecture:**
  - Bidirectional exclude (never source, never target)
  - Source-only exclude (slot stays vanilla; c-prefix can appear elsewhere)
  - Target-only exclude (cp never placed elsewhere; original slots randomize)
  - Per-NPCParam source exclude (granular variant-level — used for Guardian
    Golem Fort while leaving Cathedral/Remembrance variants randomizable)

### Known weirdness (intended)

- **Visual chimeras.** When the rando swaps a c-prefix into a slot, NPCParam
  attachment fields don't always sync — Mad Pumpkin Heads in Maris Tendril
  hats, Crucible Knights with Vulgar Militia legs, etc. Cosmetic only,
  encounters function normally. Embraced as part of the rando's aesthetic.
- **Position-offset preservation in clusters.** Some vanilla cluster designs
  use vertical offsets (Oracle Envoy pyramid: small Envoy floats above big
  one). When randomized in cluster modes, the new occupant of the elevated
  slot keeps the elevation — so a Wandering Noble might float in the air.
  Looks goofy, mechanically fine.

### Known limitations

- **Some encounter slots stay vanilla** because their encounter scripts use
  per-map inline EMEVD that doesn't go through `common_func`'s dispatcher
  pattern. Our EMEVD patches can't reach these. Affected:
  - **Guardian Golem (Fort)** at m30_30 — the laying-down variant has a
    unique stand-up cinematic and arena collision proxies. Excluded by
    NPCParam (npc=46601010); the standing Cathedral/Remembrance variants
    randomize freely.
  - **Demi-Human Shaman** (`c4110`) slots — only one compatible swap target
    exists (Demi-Human Swordmaster), which would dominate the entire
    Shaman pool. Keeping Shamans vanilla preserves the Demi-Human family
    encounter ecosystem (Queen + Swordmaster + Shaman + Chiefs + grunts).
- **Some XXL boss-tier swaps may freeze** in slots whose per-map inline
  EMEVDs play scripted-emerge anims keyed to the original occupant
  (e.g., Wormface → Death Rite Bird at a Wormface camp). Affects ~1–2
  encounters per typical seed at most. Workarounds: re-roll, or just
  parry/exploit the frozen enemy for free damage.
- **Some enemies are excluded from being placed as targets** because they
  exhibit dormant-spawn behavior outside their native context — but their
  vanilla slots are still randomized normally:
  - **Sellsword's Horse** (`c4060`) and **Albinauric Wolf** (`c3180`) — mount
    components, only function as cluster members in vanilla. Cluster-shape
    mode still places them correctly in mount+rider cluster swaps.
  - **Demi-Human Swordmaster** (`c5810`) — paired with Demi-Human Queen Night
    Boss; kept at its native arena only.
- Equipment / weapon attachment data not synchronized on swap — produces the
  visual chimeras above.
- Item drops not randomized (the rando doesn't touch `regulation.bin`).
- Day 3 Nightlord arena passthroughs randomize the non-Nightlord enemies in
  the arena, which can produce thematically-mismatched adds.

### Compatibility

- Game version: Elden Ring Nightreign (any patch since launch)
- me3: required for installing the rando into the game
- DarkScript3: optional — only needed for re-patching against a newer NR
  build (pre-patched DCX shipped in `patched_emevd/`)
- Yabber: not required — Python DCX layer ships in this bundle
- Python: 3.10 or later
