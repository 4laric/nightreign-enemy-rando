# Session notes — 2026-05-26

98-seed placement-budget audit and the four pool-gap fixes that came out
of it. Engine fingerprint bumped this session: v0.27.0 -> v0.27.2
(`oops_v3.py` line 31). CHANGELOG entry: v0.27.2.

## What was run

The real engine — `cmd_shuffle_v3` — over 98 seeds (200001-200098),
against the full set of decompressed vanilla MSBs, with the production
config:

- `multiplayer_safe=False`
- MMV pack loaded (default; `mmv_imports.json` present)
- `V3_PREFER_CANONICAL_VARIANTS=False`

No simulator / no slot-replay — the genuine per-MSB swap loop, reservation
pre-pass, and post-passes. ~3,708 swaps/seed, range 3699-3714. Validated
the run is faithful by reproducing a known spoiler (seed 654258) — it
matched except for the 218 m48/m49 slots that v0.27.1 NB-arena
preservation now holds vanilla, which is correct.

The aggregation looked at, per c-prefix: mean / max / min / appearance%
of final placement count (post-passes applied), `unique_placed_counts`
vs `V3_UNIQUE_TARGET_CAPS`, `unique_unplaced`, and `V3_RESERVATION_FLOORS`
satisfaction.

## Findings

### Clean

- **Unique caps**: zero violations across 98 seeds. No
  `V3_UNIQUE_TARGET_CAPS` ceiling exceeded. Reservation pre-bump +
  exhaustion gate hold.
- **Global cap** (`V3_TARGET_PLACEMENT_CAP=50`): soft, behaving as
  designed. 58 grunt/trash c-prefixes touched 51-54 in their hottest
  seed (the `if capped_pool` fallback when every under-cap candidate is
  exhausted); means sit 45-49. Left alone.

### Deferred — reservation floors missed

Ten floor=1 chrs come back below floor in a chunk of seeds despite the
pre-pass reserving a slot for each (`unique_unplaced` empty every seed):
Smelter Demon 50%, Dancer 40%, the four MMV night bosses (Gaius / Romina
/ Fortissax / Metyr) 15-23%, Golden Hippo / Centipede Demon / Ancient
Dragon / Gaping Dragon 1-5%. Reservation succeeds then final count is 0
-> something decrements post-reservation; the only such code is the
BIG_PROXIMITY / DENSITY_CAP demotion passes, and every top-of-list chr
is XL+. **Not fixed this session** — logged in `docs/OPEN_ISSUES.md`
under "Investigation threads" with the measured rates and the next
diagnostic step.

## Decisions made and shipped (v0.27.2)

All four were Alaric calls during the audit review.

1. **MMV nightlords are a pool gap — lift arena_only.** c4720 Godfrey,
   c4721 Hoarah Loux, c4730 Starscourge Radahn, c5230 Scadutree Avatar,
   c8500 Manus placed 0x/98. Cause: `expects_boss_arena=true` in
   mmv_imports.json -> auto-folded into `V3_ARENA_ONLY_TARGETS`; v0.27.1
   whole-MSB NB-arena preservation then left them no eligible slot. New
   `V3_ARENA_ONLY_FORCE_LIFT` frozenset, subtracted in load_data after
   the M-humanoid lift. `expects_boss_arena` tag left intact.

2. **Storm King + Ancestor Spirit back in, cap 1.** c4670, c7910 — same
   mechanism, but arena-locked via `V3_DEDICATED_ARENA_BOSS_CHRS`.
   Removed from that set; added `cap=1` in `V3_UNIQUE_TARGET_CAPS`.
   c7900 Nameless King (c7910's vanilla pair-partner) deliberately left
   in `V3_DEDICATED_ARENA_BOSS_CHRS` — revisit if the pair should move
   together.

3. **Aged Albinauric should be placeable.** c3670 placed 0x — its only
   named/canonical variant (36708100) was in `V3_AVOID_VARIANT_NPC_IDS`
   from a v0.23.24 "team=26 cinematic" attribution, so
   `pick_variant_for_tier` returned None every time. Removed 36708100
   from the avoid-list. CAVEAT: roster entry has think_param_id=0 — if
   playtest shows AI-inert placements outside m10, restore the line.

4. **Priestess/Duchess + Executor are playable characters.** c52309,
   c52313 (and c52312 Witch of the Wheel = Recluse class, excluded on
   the same grounds) added to `V3_EXCLUDE_TARGET_PREFIXES`. They are NR
   playable Nightfarer class models that post_dlc_dump scraped in as
   tier='grunt' enemies.

## Post-fix verification

12-seed re-run (seeds 300001-300012) with v0.27.2:

- Aged Albinauric: ~7/seed, every seed. Fixed.
- Player-class models: 0 placements. Excluded.
- MMV nightlords / Storm King / Ancestor Spirit: Godfrey, Scadutree,
  Manus, Ancestor Spirit now place (were structurally 0 before);
  Hoarah Loux, Radahn, Storm King still 0 over the 12-seed window —
  low base rate, needs the full sweep to confirm rate vs. a residual
  gate. The structural gap is closed (4/7 went 0 -> appearing); the
  remaining three want a bigger sample before calling them done.

## Open / next

- Re-run the full sweep (~150-300 seeds) on v0.27.2 to confirm the
  three low-frequency lifted chrs (Hoarah Loux, Radahn, Storm King)
  place at a sane rate, and to re-measure the reservation-floor misses
  now that the arena_only pool widened.
- Trace the reservation-floor demotion (OPEN_ISSUES.md): per-seed
  diagnostic_trace for the Smelter Demon misses — BIG_PROXIMITY vs
  NB-arena orphan.


---

## v0.27.3 — miniboss tier floor + cap (same session)

Followed the audit with a cap/floor survey of the miniboss tier and a
tier-wide normalization. See the v0.27.3 CHANGELOG entry for the full
write-up. Summary:

- Survey: 76 eligible minibosses, 32 capped / 44 uncapped, 0 floors.
  Distribution was top-heavy — 8 uncapped chrs at 11-15x/seed, ~30-chr
  tail below 1x/seed.
- Slot-budget feasibility check (Alaric asked first): ~360 boss-strength
  slots/seed (357 boss-strength vanilla sources, 361 catalogued) vs a
  projected 100 floored chrs (24 existing + 76 miniboss). ~3.6x
  headroom — comfortably enough.
- Change: load_data() now gives every eligible miniboss floor=1 and
  every previously-uncapped miniboss cap=6. Existing caps untouched.
  Computed loop, idempotent.
- 12-seed validation (400001-400012): top-8 now 5.75-6.00 (cap binds),
  Aged Albinauric 0 -> 6 every seed (floor works). 14 of 16 stragglers
  are XL+/XXL/GIGA — the demotion-bug population.

Open: the reservation-floor-demotion bug (docs/OPEN_ISSUES.md) now
gates 76 floors and is the priority follow-up — without it the
tier-wide floor only fully lands for the ~50 S/M/L minibosses.

Also still open from the castle thread: the pi-124 size-M restriction
in the m60_43_37 castle tile (one of four identical Banished Knight
slots restricted to size-M targets; mechanism not yet traced).
