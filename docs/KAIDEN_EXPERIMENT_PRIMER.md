# Kaiden Sellsword experiment — primer

You're being asked to design and implement a small but novel feature in
my Nightreign enemy randomizer: **role-aware paired randomization of
mount + rider cluster sites**. The aesthetic goal is "an albinauric
cartwheeling on top of a horse" — chaos comedy that preserves the
mount+rider archetype while letting both members be randomly picked.

## Who I am

Alaric — I maintain `nightreign-enemy-rando`, a Python toolchain that
swaps enemy NPCs in From Software's *Elden Ring: Nightreign* by modifying
MSB (map static-bin) Parts. Currently on **v0.23.72-late**. I edit from a
bus on mobile sometimes; assume technical depth, skip hand-holding, prefer
decisive recommendations over options-paralysis. Annotate code changes
with v-version tag + rationale + provenance. When in doubt, paraphrase
what I said back before executing.

## Why this matters

Nightreign has several vanilla mount+rider cluster sites:
- **Kaiden Sellsword** (rider, c4050) + **Kaiden Sellsword's Horse**
  (mount, c4060) — overworld field encounters
- **Night's Cavalry** (rider, c3150) + **Funeral Steed** (mount, c3160)
  — Night Boss encounter
- **Albinauric Archer** (rider, c3170) + **Albinauric Archer's Wolf**
  (mount, c3180)
- **Lordsworn Knight** (rider, possibly c4061 — not in our data) +
  **Lordsworn Knight's Horse** (mount, c4363) — used in another Night
  Boss encounter

In current randomizer state these are mostly suppressed — both mount and
rider c-prefixes are target-excluded because riderless mount has no AI
and mountless rider has no horse to ride, so picking either solo at a
random slot breaks. The clusters themselves stay vanilla (via cluster-
aware machinery) or get rolled to two unrelated chrs (with cluster-aware
off).

I want a third option: **mount slot picks any horse-class chr, rider
slot picks any M humanoid, they stay spatially paired in-world**. That
gives the chaos-comedy aesthetic I'm after.

## Current state of the rando (v0.23.72-late)

Key configuration:
- `cluster_aware = False` (default) — each Part rolls independently
- `randomize_clusters = True` (default) — clusters get randomized
- `c4050`, `c4060`, `c3160`, `c4363`, `c3180` all in
  `V3_EXCLUDE_TARGET_PREFIXES` (line 821 of `oops_v3.py`) — never picked
  as targets currently
- `c3150` Night's Cavalry in `V3_EXCLUDE_SOURCE_PREFIXES` — Night
  Cavalry encounters stay vanilla (protected — leave that)

What this means in practice: a vanilla Kaiden cluster (2 Parts: c4050
rider + c4060 horse) currently rolls each Part independently from the
universal pool. Both Parts get random non-mount, non-Kaiden chrs.
Visual result: two random standalone chrs at the cluster position,
neither of which is on a horse. The horse-shape is lost.

I've seen the "guy on a horse" effect happen in earlier playtests (likely
from old cluster_aware=True days), and it's genuinely funny. Want to
make it intentional.

## The mount + rider data

I've audited the tags. Here's what we've got:

```
c3160  Funeral Steed                          tier=mount_component  anim=quadruped_large  size=XL
c3180  Albinauric Archer's Wolf               tier=mount_component  anim=quadruped        size=M
c4050  Kaiden Sellsword                       tier=mount_component  anim=humanoid         size=M  ← MISTAG
c4060  Kaiden Sellsword's Horse               tier=mount_component  anim=quadruped_large  size=L
c4363  Lordsworn Knight's Horse (Night Boss)  tier=mount_component  anim=quadruped_large  size=L
```

**Data correction to do first:** c4050 Kaiden Sellsword is tagged
`tier='mount_component'` but he's the *rider*. It's a heuristic mis-tag
from `post_dlc_dump`. The fix: change his tier to something like
`'miniboss'` or `'grunt'` (he's a field-tier humanoid). Update
`nr_enemy_tags.json` and annotate with `_pre_correction` + a
`_source_override` marker.

**Robust mount detection signal:** the 4 actual mounts have
`anim_class in {quadruped, quadruped_large}` AND `tier='mount_component'`.
Use that intersection, not tier alone. Kaiden gets excluded by the
anim_class check.

**Rider pool:** the user's "M humanoid" target means
`anim_class='humanoid'` AND `size_class='M'` AND
`tier in {grunt, miniboss, trash}`. Pool size in current data is ~60
c-prefixes. Plenty of variety.

## The two implementation approaches

I've designed both in the TODO. The new chat picks one based on context
they have. Brief comparison:

### Approach A — Re-use existing cluster_aware machinery (fast)

Re-enable `cluster_aware` mode for opted-in cluster sites only. Add a
"role-aware cluster swap" mode where mount members can pick from
horse-class targets and rider members from M-humanoid targets
independently within the existing cluster path.

Steps:
1. Read `compute_part_clusters` (line 8487 in `oops_v3.py`) and the
   cluster-aware swap path to see if it already supports per-member
   role-aware retargeting, or if it does whole-cluster atomic swap.
2. If atomic: add a role-aware mode where mount members → horse-class
   targets, rider members → M-humanoid targets, paired in-world.
3. Configure Kaiden as the pilot pair (mount compat = horses,
   rider compat = M-humanoids).
4. Playtest spoiler audit of c4050/c4060 source slots to confirm both
   members got randomized into the right pools.
5. If successful, extend to other paired mounts — but **carefully**:
   c3150+c3160 is the Night's Cavalry Night Boss encounter (user wants
   that LEFT ALONE), and c4363 has a specific touchy night-boss instance
   user has also said leave alone (separate TODO).

**Pro:** fast, re-uses existing machinery.
**Con:** `cluster_aware` mode is on the kill-list per the separate EMEVD
audit TODO. Approach A's mechanism gets obsoleted once the EMEVD audit
ships its Phase 3 engine cleanup.

### Approach B — New role-restricted pool machinery (durable)

Build new machinery that doesn't depend on `cluster_aware`. Survives
the EMEVD-audit-driven cluster removal.

Steps:
1. Build `V3_MOUNT_CLASS_POOL` at load_data time using the
   `tier='mount_component' AND anim_class in {quadruped, quadruped_large}`
   filter. Should yield {c3160, c3180, c4060, c4363}.
2. Build `V3_M_HUMANOID_RIDER_POOL` similarly (anim=humanoid, size=M,
   tier in {grunt, miniboss, trash}).
3. In `pick_target_cp` (line 8013), detect "mount slot" at swap time:
   source cp is in mount-class pool AND there's a paired rider slot in
   the same cluster (pre-cluster-removal: via cluster detection;
   post-cluster-removal: via spatial proximity + size/anim_class
   heuristics).
4. At mount slots, restrict the target pool to V3_MOUNT_CLASS_POOL.
5. At rider slots, restrict to V3_M_HUMANOID_RIDER_POOL.
6. Remove c4060 (and probably the other 3 mounts) from
   `V3_EXCLUDE_TARGET_PREFIXES` so they're valid picks at mount slots.

**Pro:** durable, doesn't depend on doomed `cluster_aware`.
**Con:** more code; needs new spatial-proximity detection if it lives
beyond the cluster_aware removal.

### My recommendation

If the EMEVD audit is going to ship within a few sessions anyway, jump
straight to Approach B and save the migration cost. If you want a
playable Kaiden experiment quickly (this week), Approach A is faster
proof-of-concept, ship-and-iterate.

I lean B for engineering cleanliness, but I'd take either if it gets to
albinauric-on-a-horse this session. Your call based on what the codebase
makes easy.

## Critical constraint: Lordsworn night-boss instance

There's a specific (msb, pi) instance of c4363 Lordsworn Knight's Horse
in a night boss encounter that's been "proven touchy" in past playtests
(per v0.19.3 softlock note). I have explicitly said leave that instance
alone — randomizing it has caused softlocks before.

For either approach: the role-aware mount swap should be configurable to
**opt-IN** specific source cluster sites, not blanket-apply. OR the
touchy instance gets slot-specific exclusion via `V3_PROBLEM_SLOTS`
(line 6165 in `oops_v3.py`).

The specific (msb, pi) of the touchy instance hasn't been pinned down
yet — that's its own TODO. So for this experiment, the safe scope is:
**only opt-in c4050+c4060 (Kaiden) sites** for now. Adding
c4363+rider-pair sites can wait until we identify and exclude the
touchy instance.

## Validation strategy

Once implemented:
1. Run the rando with a known seed (e.g. seed 42 or whatever has Kaiden
   cluster sites visible in spoiler).
2. Check the spoiler log for c4050/c4060 source slots — confirm:
   - Both Parts got randomized (not preserved as vanilla)
   - Mount slot landed on a mount-pool cp (c3160/c3180/c4060/c4363)
   - Rider slot landed on an M-humanoid cp
3. Visual playtest: load the map, find the Kaiden site, confirm the
   pair appears together (not one floating away from the other) and
   the rider is actually on the horse (or at least standing at the
   horse's position).
4. If multiplayer-safe is needed: confirm the swap doesn't introduce
   anything in the `V3_GHOST_EXCLUDE_TARGET_PREFIXES` set.

## Out of scope

- **Mounting/dismounting AI** — I'm not asking for the rider to
  actually ride the horse in the game's physical sense. Just that they
  occupy adjacent positions and look like a pair. If the rider falls
  off and just stands next to the horse, that's still funny.
- **The EMEVD cluster-anim audit** — separate workstream, separate
  primer. Don't confuse the two. EMEVD audit is about patching out
  `ForceAnimationPlayback` calls that cause CTDs in cluster contexts.
  This Kaiden experiment is about adding paired-randomization logic
  to the engine.
- **The Lordsworn touchy instance** — has its own TODO; needs playtest
  data to identify the specific (msb, pi). For Kaiden experiment, just
  scope to c4050+c4060 only.

## Files you'll probably need

- `oops_v3.py` — main engine. Big (~11k lines) but the relevant pieces
  are:
  - `V3_EXCLUDE_TARGET_PREFIXES` definition (line 821)
  - `V3_FIELD_STRENGTH_TIERS` definition (line 6766)
  - `pick_target_cp` function (line 8013) — where target-pool computation
    happens; this is where role-aware filtering would slot in for
    Approach B
  - `compute_part_clusters` function (line 8487) — spatial union-find
    grouping of Parts; Approach A's pivot point
  - `V3_CLUSTER_LOCK_MAPS` (line 5267) — populated by load_data;
    Approach A would extend this
  - `V3_PROBLEM_SLOTS` (line 6165) — slot-specific exclusion mechanism
    for the Lordsworn carveout
- `data/nr_enemy_tags.json` — tag database, for the c4050 mistag fix +
  building mount/rider pools at load time
- `data/nr_enemy_roster.json` — variant database (large; mostly relevant
  for verifying mount cps have variants to roll into)
- `TODO.md` — the full design doc has more context than this primer

## Concrete first deliverable

Whichever approach you pick:

1. **Fix the c4050 mistag first.** Update `nr_enemy_tags.json`: change
   c4050 tier from 'mount_component' to 'miniboss' (Kaiden is a strong
   field-tier humanoid; he carries a katana and has Bushido moves). Add
   `_pre_correction: {tier: 'mount_component'}` + `_source_override:
   'kaiden_experiment_v0_23_72_late'`. This unblocks the mount-class
   detection logic.

2. **Implement the chosen approach** for Kaiden sites only (c4050+c4060).
   Don't touch c3150+c3160 or c4363 placements — those have separate
   protection requirements.

3. **Write a quick test harness or smoke test** that exercises the
   path: load a map with a Kaiden site, dump what targets get picked at
   each slot, verify they come from the right pool.

4. **Annotate the changes with v0.23.72-late tag** + rationale + the
   constraint that this is opt-in for c4050+c4060 only.

5. **Don't ship MSB output to the user's game install yet** — I'll do
   the actual playtest. You just need to make the rando produce
   structurally-correct output for the Kaiden sites.

## TL;DR

Build paired role-aware randomization for c4050 Kaiden Sellsword +
c4060 Kaiden's Horse cluster sites. Mount slot → random horse-class
chr (c3160/c3180/c4060/c4363), rider slot → random M humanoid. Two
approaches available (A: re-use cluster_aware, B: new pool machinery)
— pick based on codebase fit. Don't touch Night's Cavalry (c3150+c3160)
or Lordsworn Night Boss (c4363) instances. Fix the c4050 mistag first.
Goal: visual chaos comedy with albinaurics on horses.
