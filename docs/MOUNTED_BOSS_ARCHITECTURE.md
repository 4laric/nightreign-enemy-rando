# Mounted-boss randomization — architecture audit

User asked v0.23.51: "we should have logic already for horse and rider
cluster swap, we developed it earlier and its confirmed working for
non-bosses". This doc captures the full audit response so it's not lost.

## TL;DR

The cluster-coordinated rider+mount handling exists and works. v0.23.50's
surgical narrowing brings Tree Sentinels into compatibility with the
existing system. No further code changes needed for the Tree Sentinel
case.

The user's intuition was right that the mechanism existed, but the
mechanism is `_collapse_rider_mount_pairs` (rider rolls solo, mount
gets suppressed) — not a "swap to a different mounted-boss family
cluster" scheme.

## What handles what

### Tree Sentinel arena (m48_50, m48_60) — Day-3 Night Boss

Architecture: 1 self-contained-mount boss (c3250 or c3251), 4 companion
horses (c4363), 2 named active riders (c4353), 2 spirit-summon riders
(c4353), 2 spirit-summon horses (c4363).

Protection layers (post-v0.23.50):

- **Boss preserved** via `V3_EXCLUDE_SOURCE_NPC_PARAMS`:
  - 32500110 (Draconic Tree Sentinel NB)
  - 32510110 (Tree Sentinel NB)
- **Companion horses preserved** via `V3_EXCLUDE_SOURCE_NPC_PARAMS`:
  - 43630010 (Lordsworn Knight's Horse NB)
  - 43630400 (Lordsworn Knight's Horse NB Spirit)
- **Active companion riders preserved** via `V3_EXCLUDE_SOURCE_NPC_PARAMS`:
  - 43531110 (Leyndell Knight NB rider, v0.23.03)
  - 43531400 (Leyndell Knight NB Spirit, v0.19.14)
- **Cluster-aware grouping** runs over the surviving Parts when the user
  has cluster_aware=True (or the GUI toggle was on). Since all 12 Parts
  in the cluster are already excluded as sources, cluster grouping is
  a no-op for this arena — there's nothing to coordinate-swap.
- **`_collapse_rider_mount_pairs`** scans for `(c4353, c4363)` pairs.
  Finds 6 same-position pairs in m48_50/m48_60, but `_is_part_npc_preserved`
  returns True for both Parts in each pair (NPCParams in
  V3_EXCLUDE_SOURCE_NPC_PARAMS), so the collapse skips them. Listed in
  `RIDER_MOUNT_PAIRS` for completeness in case the surgical excludes
  ever get relaxed.

Result: full encounter intact, no rider-on-wrong-mount glitches, no
ungodly noise.

### Limveld field Tree Sentinels (m60_xx tiles)

Architecture: solo c3250/c3251 chr, no separate horse Part (the chr is
self-contained-mount — knight + horse bundled into one entity).

Protection layers (post-v0.23.50):

- **No source-exclude needed** — Limveld variants have NPCParam IDs that
  aren't in V3_EXCLUDE_SOURCE_NPC_PARAMS (32500000, 32500010, 32500090,
  32500100 for c3250; 32510000, 32510020, 32510030, 32510040, 32510100
  for c3251). They flow through the normal swap path.
- **No collapse pass needed** — there's no companion horse Part to
  suppress. The chr is one Part.
- **No cluster grouping needed** — solo Parts.

Result: fully swappable. A Limveld Tree Sentinel can become any other
boss-tier chr with compatible size/locomotion. The chr's bundled-mount
nature doesn't conflict with the swap because there's no eid pairing
or phase-script coordination on overworld instances.

### Albinauric Archer + Wolf pairs (m34_10, m60_42_38_10)

Architecture: rider Part (c3170) and mount Part (c3180) at near-identical
positions. The Wolf's NPCParam is configured for "ride-along" (degenerate
AI without rider).

Protection layers:

- **`_collapse_rider_mount_pairs`** detects 5 pairs across the two MSBs.
  For each, the wolf Part's npc_param gets zeroed (vanilla MSB convention
  for "Part exists but spawns no enemy"). The Albinauric Archer rider
  rolls into the swap path picking ONE standalone target.
- **Variety preserved** — instead of getting the rider+mount semantic,
  you get one varied enemy at the position.

Result: clean swap to a single chr at the pair's position, no
rider-on-wrong-mount, no riderless inert mount.

### Kaiden Sellsword + Horse pairs (m60_44_36_30, m60_44_38_20)

Same as Albinauric+Wolf above with `(c4050, c4060)` pair detection.
3 pairs across the two MSBs.

### Night's Cavalry + Funeral Steed (m46_62)

Architecture: 2 pairs in the Night's Cavalry arena. Both c3150 and c3160
are in `V3_EXCLUDE_SOURCE_PREFIXES` (full c-prefix-level exclude) because
the rider has a dismount/remount mid-fight phase that depends on its
specific eid/script bundle.

`_collapse_rider_mount_pairs` lists `(c3150, c3160)` for completeness but
the entries are inert because both Parts are already source-excluded
at the c-prefix level.

### Royal Carian Knight / Loretta (c3252)

Self-contained-mount, like Tree Sentinel. Was never source-excluded
at the c-prefix level. Always swappable. Confirmed in v0.23.50 audit.

## Why the cluster-swap-to-different-mounted-boss-family idea isn't
implemented

A cluster-coordinated swap scheme (where the entire Tree Sentinel arena
swaps to a Loretta arena, or to a Night's Cav arena) would require:

1. A library of vanilla cluster shapes (already exists:
   `build_vanilla_cluster_catalog` produces it for `cluster_shape=True`).
2. Compatibility tagging for mounted-boss arena clusters specifically
   (so the catalog knows m48_50 ≈ m46_62 ≈ Loretta arena structurally).
3. EMEVD-aware target selection (so the boss-death-event eids resolve
   correctly across the swap).
4. Per-c-prefix arena-cluster-only flags so non-arena slots don't
   become eligible swap targets for arena clusters.

Item 3 is the hard part — the boss-death-event chain at m48_60 references
specific NPCParam IDs and entity_ids that wouldn't survive a wholesale
arena swap. We'd need an EMEVD patch that rewrites the death-event chain
to use the new chr's IDs, similar to the boss-reward EMEVD injections we
did earlier.

This is a v0.24+ feature, not a v0.23 fix. v0.23.50's surgical narrowing
is the right interim — it gives the user Limveld Tree Sentinels (most
of the variety win) without breaking the protected Day-3 arena.

## v0.23.50 verification matrix

| Slot type | NPCParam | Excluded? | Result |
|-----------|----------|-----------|--------|
| m48_50 Draconic Tree Sentinel NB | 32500110 | YES | Vanilla preserved |
| m48_60 Tree Sentinel NB | 32510110 | YES | Vanilla preserved |
| m48_50/60 Lordsworn Horse NB | 43630010 | YES | Vanilla preserved |
| m48_50/60 Lordsworn Horse NB Spirit | 43630400 | YES | Vanilla preserved |
| m48_50/60 Leyndell Knight NB rider | 43531110 | YES (v0.23.03) | Vanilla preserved |
| m48_50/60 Leyndell Knight NB Spirit | 43531400 | YES (v0.19.14) | Vanilla preserved |
| Limveld c3250 (Field/Ruins/regular) | 32500000-100, 32500090 | NO | Swappable |
| Limveld c3251 (Field/Underground/regular) | 32510000-100, 32510020, 32510040 | NO | Swappable |
| Limveld c4363 (overworld horse) | 43630000, 43630100 | NO | Swappable (none exist in MSBs we have indexed, but excluded set won't block them) |
| All c3252 Royal Carian Knight | all | NO | Always swappable |
