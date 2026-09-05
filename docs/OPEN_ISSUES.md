# Open Issues

Living document. Tracks open investigation threads and audit blind spots
that aren't blocking a release but need to be carried forward across
sessions. Add new entries at the top of the relevant section. Resolve by
deleting the entry and noting the CHANGELOG version where it landed.

Last updated: 2026-09-05 triage at v0.32 (previous update: v0.27.3).

## Triage 2026-09-05 (v0.32 revival)

This file predates the revival and the v0.28–v0.32 releases; the table
below records the triage verdict for every thread. Entries themselves
are kept verbatim as a historical log — verify against the current
engine before acting on any thread.

| Thread | Verdict |
|---|---|
| Needs re-confirmation after the v0.26 EMEVD spawn work | UNCLEAR — arena half moot (test-mode arenas default-on since v0.26.7, regenerated to v0.29-v8); overworld cases never re-confirmed |
| Active dormancy / EMEVD bug class — c3860 Avionette | UNCLEAR — proposed fix path (permissive_spawn_emerge) was retired at v0.24.102; any revival should target the v0.31 proximity-wake/entity-id stamping machinery |
| ↳ Adula at Cathedral (38000850, m38_00_00_00) | UNCLEAR — queued diagnostic pass never recorded as run; arena-side probably moot under test-mode arenas |
| ↳ c4441 Large Land Squirt suspected dormancy | UNCLEAR, leaning resolved — failure class structurally closed by v0.27.24 think-param validation + v0.27.23/26 Land-Squirt repoint; original report suspected vanilla behavior |
| Audit blind spot: low-suffix arithmetic-inheritance variants | RESOLVED in substance — anchor cases avoid-listed/excluded (c2030/c2031 excluded v0.31; c4720 phase-2 IDs avoid-listed); data/phase_transition_imports.json is now the source of truth; still no algorithmic detector |
| Audit blind spot: cluster-path emerge-marker filter gap | RESOLVED (moot) — entire cluster swap path removed in v0.26.13 |
| Audit blind spot: Chinese name markers (友好/主城/满月女王/初王) | STILL OPEN but superseded — no current audit script flags these; all known variants now avoid-listed/excluded; matters only for future MMV imports |
| c-prefixes to exclude outright (c4492, c52101/2/7, c52309/12/13, c8910/11) | RESOLVED — all 9 excluded by other mechanisms (V3_EXCLUDE_PREFIXES, broken_runtime_chrs, cinematic tier tag, empty variant_name rule) |
| Reservation-floor chrs demoted out of reserved slot | RESOLVED v0.27.5 — Gates 8/9 in engine/rejection.py; file's own text already said so |
| c4640 Ulcerated Tree Spirit "missing skin" | STILL OPEN — deferred at filing, never revisited; c4640 still in pool (floor removed, cap=2) |
| me3 chr-file fallback semantics | STILL OPEN (low priority) — no definitive answer; v0.30 self-contained profile weakly bears on it |

Note: the reservation-floor thread's own text was already marked
RESOLVED at v0.27.5, but the header/tally was never updated to match —
this triage corrects that bookkeeping.

Real remaining opens: c3860/Adula dormancy re-confirmation (needs
playtest), c4640 skin disambiguation, me3 fallback semantics,
Chinese-marker audit extension. Everything else is resolved or moot.

> **Scope note.** Active feature work and deferred-but-actionable items
> live in `docs/TODO.md`. This file is narrower: open *questions* and
> *uncertainties* — things we don't yet understand well enough to file
> as a concrete task — plus the "closed observations" section at the
> bottom, which exists to stop future sessions from re-litigating
> settled decisions.

---

## Needs re-confirmation after the v0.26 EMEVD spawn work

The v0.26.x arc reworked the EMEVD spawn approach (test-mode arenas with
a minimal spawn template, now on by default) and the wake-handshake
patches. Several older entries below predate that work and may be fully
or partially resolved by it — they are kept until a playtest confirms
either way:

- The **EMEVD dormancy bug class** (below) was written against the old
  cinematic-arena spawn path. With test-mode arenas default-on, the 19
  N1/N2 boss arenas no longer run per-boss intro choreography — so the
  arena-side cases (Adula at Cathedral as a boss encounter, etc.) may be
  moot. The *overworld* cases (Avionette at a Limveld field-boss slot)
  are not arena fights and may still apply. Confirm before spending time
  here.

---

## Active dormancy / EMEVD bug class (pre-v0.26, re-confirm)

Multiple chrs share an underlying mechanism: EMEVD scripts hardcode
chr-specific animation IDs into `ForceAnimationPlayback` calls. When the
occupant is randomized, the anim ID doesn't resolve in the new chr's
bank and the chr plays its spawn animation, then sits dormant in idle
pose at full HP. The `permissive_spawn_emerge` patch matches the
entrance opcode but historically missed the boss-intro / arena-activation
opcodes that hand off combat AI after the entrance.

Anchor cases (verify which still reproduce post-v0.26):

- **c3860 Avionette** — a Limveld field-boss slot. Spawn and death
  animations work; stuck dormant in between. Overworld, not an arena —
  most likely still live.
- **Adula at Cathedral** (`38000850`, `m38_00_00_00`) — filed as the
  canonical test case for the EMEVD diagnostic pass. May be moot under
  test-mode arenas if treated as an arena fight.
- **c4441 Large Land Squirt suspected dormancy** — "died instantly into
  a poison cloud" pattern suggests dormant + chip-killed. Needs spoiler
  context to pin the placement.

If the bug class is still live, the fix is a per-occupant or
slot-scoped EMEVD patch — see the Guardian Golem (Cathedra) entry in
`docs/TODO.md` for the current shape of this kind of fix.

---

## Audit-script blind spots

### Low-suffix arithmetic-inheritance variants

Phase-2 boss forms with low NPCParam suffixes (X100 / X134 / X034)
inherit phase state from X000 and are hardcoded to start at low HP — at
a slot with no phase-1 EMEVD, the transition cutscene never fires and
the chr loads at 1 HP. Suffix-threshold heuristics that only flag high
suffixes miss these. Confirmed cases caught manually by name inspection:
c2031 Rennala P2 (20310024 / 20310124), c4720 Godfrey / Hoarah Loux
(47200100 / 47200134). A fully algorithmic detector needs a "multi-phase
boss" classification list; until that exists, manual review fills the
gap when new boss c-prefixes (e.g. from MMV) enter the pool.

### Cluster-path source-side emerge-marker filter gap

The source-side emerge-marker filter (skips slots whose vanilla NPCParam
has empty `variant_name`) only fires on the non-cluster swap path.
Clustered Parts bypass the empty-name check. Impact is low — cluster
members are usually combat fights — but if a future "chr appeared
briefly then despawned" bug lands at a clustered slot, this is where to
extend the filter.

### Chinese name marker expansion

The audit currently flags one Chinese keyword: 雕像 (statue). Other
markers worth detecting to catch low-suffix phase-locked variants by
name: 友好 (friendly NPC), 主城 (main castle / scripted fight), 满月女王
(Full Moon Queen — Rennala P1 cocoon), 初王 (First King — Godfrey
cinematic intro).

---

## c-prefixes that should be excluded outright

The v0.23.24 audit identified 9 c-prefixes whose every NPCParam variant
is `teamType=26` (non-combat / cinematic / decoration). They're masked
correctly by the hard avoid filter, but cleaner behavior would be to add
them to `V3_EXCLUDE_TARGET_PREFIXES` so they're never even considered:
c4492, c52101 / c52102 / c52107 / c52309 / c52312 / c52313, c8910 /
c8911. Action: add with a `# v0.23.24 audit: entirely team=26` comment.

---

## Investigation threads (need more data before fixing)

### Reservation-floor chrs demoted out of their reserved slot

**RESOLVED in v0.27.5.** The BIG_PROXIMITY and DENSITY_CAP swap-plan
post-passes were the cause: they ran after the reservation pre-pass and
demoted reserved XL+ chrs, decrementing `_placed_counts` below floor.
v0.27.5 replaced both post-passes with placement-time gates (Gates 8 &
9 in `_reject_target_for_slot`). The gates only fire for organic picks
inside `shuffle_msb_v3`'s slot loop — the reservation pre-pass and the
reservation early-return never arm them, so a reserved big chr is never
proximity/density-rejected and can no longer be demoted. A 5-seed
v0.27.5 check (714653/628653/42/394059/877217) returned 100 reservations
honored and 0 below-floor each seed. The original investigation notes
are kept below for history.

<details>
<summary>Original v0.27.2/v0.27.3 investigation (historical)</summary>

**Priority raised in v0.27.3** — this bug now governs 76 miniboss-tier
floors (the v0.27.3 tier-wide floor=1), not the ~10 it was originally
filed against. A 12-seed v0.27.3 check showed 14 XL+/XXL/GIGA minibosses
still missing seeds despite their floors. The tier-wide floor cannot be
considered fully delivered until this is fixed; it is the natural
next task.

Surfaced by the v0.27.2 98-seed placement audit (seeds 200001-200098,
see dev/SESSION_NOTES_2026-05-26.md). Ten chrs carry a
`V3_RESERVATION_FLOORS` guarantee of 1 and the pre-pass successfully
reserves a slot for every one of them every seed (`unique_unplaced` is
empty), yet the *final* `unique_placed_counts` comes back below floor in
a large fraction of seeds:

- c7820 Smelter Demon — below floor 49/98 (50%)
- c7920 Dancer of the Boreal Valley — 39/98 (40%)
- c5000 Commander Gaius — 23/98
- c5030 Romina, Saint of the Bud — 20/98
- c4511 Lichdragon Fortissax — 17/98
- c5200 Metyr, Mother of Fingers — 15/98
- c5011 Golden Hippopotamus — 5/98
- c7710 / c4510 / c7700 — 1-3/98 each

The reservation succeeds (count starts >=1) and final count is 0, so
something decrements it after the pre-pass. The only code that
decrements `_placed_counts` post-reservation is the BIG_PROXIMITY /
DENSITY_CAP demotion passes (`_placed_counts[_old_cp] -= 1` on
demote-out) — and every chr at the top of the list is XL+, exactly the
demote-prone size classes.

</details>

### c4640 Ulcerated Tree Spirit "missing skin"

A placement looked partial / mesh-incomplete. Two possibilities: (a)
intended appearance — Ulcerated Tree Spirit is canonically a rotted
tree-creature with exposed flesh, easy to misread as "missing skin"; or
(b) a genuine texture/mesh binding issue. Disambiguation needs a clearer
screenshot without rune-glow occlusion.

### me3 chr-file fallback semantics

Open question never definitively answered: does me3 overlay vanilla
`chr/` files as a fallback when the modded profile doesn't override
them? Indirectly answered by "no further CTDs of the same class" — the
conservative exclusion of phantom prefixes (c4021, c4181, c4641) is safe
regardless. A definitive answer would let us decide whether that
exclusion is over-aggressive. Low priority; safe in the worst case.

---

## Historical landmarks (resolved or parked — kept for context)

- **BFER integration — abandoned, code removed.** No BFER c-prefixes
  are in the target pool and the integration is not being resumed.
  Empirically, regulation merge alone was insufficient, EMEVD-
  scaffolding helped only partially, and at least one variant CTD'd.
  The cross-game-content niche is served by MMV instead. The support
  arc was removed in stages: the `V3_BFER_*` gate constants / boss-tier
  gate / OOPS_ALL_NB intercept at v0.24.22 (Phase 7), the manifests
  before that, and the last residue (audit script, GUI link, dead
  avoid-IDs, stale doc rows) at v0.26.12. Engine-side history comments
  documenting the removal are intentionally retained.
- **MMV cross-game imports — integrated** (v0.23.35). `mmv_imports.json`
  ships cross-game boss imports tier-classified into the runtime caliber
  sets, active when MMV is in the user's me3 profile. Built against MMV
  2.0.5; later MMV releases could shift tier characteristics. A few
  unidentified imports remain — see the `v0.23.72-late tag-but-no-
  variants` audit entry in `docs/TODO.md`.
- **Post-DLC (Forsaken Hollows) content — integrated** (v0.23.34). DLC
  roster + tags folded in. Remaining gap: the Great Hollow Shifting
  Earth map tiles aren't in the MSB dataset, so new chrs can swap into
  existing slots but the new map regions are invisible.

---

## Closed observations worth preserving (not bugs)

These are *not* open issues. They're patterns that look buggy at first
glance, or design trade-offs explicitly accepted — recorded so future
sessions don't "fix" them by mistake.

- **Bosses summoning their own ads.** A randomized boss (e.g.
  Battlefield Commander) whose vanilla ThinkParam includes a summon
  mechanic will populate the arena with ad chrs even at a swapped slot.
  ThinkParam ships in the chr's chrbnd and is preserved across swaps.
  Working as intended.
- **Same NPCParam ID at multiple slots.** When the engine picks
  c-prefix X and X has only N variants, RNG distributes those N values
  across every slot that picked X — so the same ID recurs across maps.
  Not a bug; just a small variant pool.
- **Hard avoid filter trade-off.** Removing the soft-fallback from
  `_filter_avoid_npc` was correct — it had masked a case where every
  variant of a c-prefix was avoid-listed and the engine placed the bad
  one anyway. The cost is that c-prefixes with only avoid-listed
  variants are no longer placement candidates and their slots stay
  vanilla. Accepted: reduced variety for ~10 c-prefixes beats
  guaranteed-bad placements.

---

## How to use this file

When opening an issue: add to the relevant section above with enough
context that a future session can pick up the thread without losing
state. Cross-reference relevant CHANGELOG versions.

When closing an issue: delete the entry and note the CHANGELOG version
where the fix landed. This file shrinking is itself a signal of
progress.
