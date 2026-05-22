# Open Issues

Living document. Tracks open investigation threads and audit blind spots
that aren't blocking a release but need to be carried forward across
sessions. Add new entries at the top of the relevant section. Resolve by
deleting the entry and noting the CHANGELOG version where it landed.

Last updated: v0.26.9.

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
