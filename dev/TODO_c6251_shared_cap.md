# TODO: implement shared-cap mechanism for c6251 ↔ c3251 (v0.28.x)

**Goal**: c6251 (Tree Sentinel, SoTE variant) should share c3251's placement
cap rather than carry its own independent count. Spawning a c6251 should
count against c3251's cap of 2, and vice versa.

**Motivation**: c3251 and c6251 are the same chr from a player-recognition
standpoint — both are mounted Tree Sentinels in gold-blue armor with the
same hit dimensions, identical animation style, and the same iconic
silhouette. Placing 2 of each in a single run would land 4 visually-identical
"Tree Sentinel" encounters, breaking the rarity contract the cap=2 was
chosen for. Separate caps make sense for sibling chrs whose presentation
differs (Horned Warrior c5250 / Horned Shaman c5251 — different weapons,
different size, different roles); they don't for c3251 / c6251 which differ
only in their stat profile and ER source location.

## Current state (v0.28.0)

- c6251 freshly registered in heritage_pack.json + nr_enemy_tags.json +
  nr_enemy_roster.json + placement_budget.json
- placement_budget.json has c6251 with `cap: 2` (mirrors c3251's value as a
  stopgap) plus `_shared_cap_pending: "c3251"` marker
- nr_enemy_tags.json carries the same marker
- Stopgap behavior: each chr can place up to 2 instances independently
  (so up to 4 Tree Sentinels in a run is currently possible — undesired
  but not broken)

## Inverse of the c5250 / c5251 (Horned Warrior) precedent

The Horned Warrior work went the OTHER direction: c5250 (miniboss tier,
cap=4) and c5251 (grunt tier, cap=40) used to share a budget; the
promotion gave each their own cap so the miniboss-tier Horned Warrior
wouldn't get pushed off the board by its abundant shaman sibling. That
pattern was correct because the two chrs are mechanically and visually
distinct.

c6251 needs the reverse: it was effectively given its own implicit cap
on registration. We want it to fold back into c3251's budget instead.

## Implementation options

(Designer's choice; recording the surface area, not prescribing.)

**Option A — `shared_cap_with` field**

Add `shared_cap_with: "c3251"` to placement_budget.json entries that
should share. The placement counter consults the field and, when set,
attributes the placement against the named c-prefix's counter instead
of its own. Lightweight, no schema-level cap groups, easy to audit.

Edge cases: cycles (`A → B`, `B → A`) need detection; chains
(`A → B → C`) need flattening to a single target; the target chr's own
cap stays authoritative.

**Option B — explicit `cap_group` field**

Add `cap_group: "tree_sentinel_iconic"` to BOTH c3251 and c6251. The
placement counter aggregates counts by group when the field is present,
falls back to per-cp counting when absent. Group's cap comes from
either the first member's `cap` or a separate `cap_groups` top-level
section.

More flexible than Option A — supports 3+ chrs sharing a cap, and
avoids the "follow the pointer chain" logic. Slightly more schema
surface.

**Option C — generalize `shares_with` to roster-level**

Move the concept up into nr_enemy_tags.json instead of placement_budget,
where it could affect not just placement caps but also picker
visibility, tier rollups, etc. Probably overengineered for this case
unless other sharing concerns surface.

Recommendation: Option A or B depending on whether you anticipate other
"family pair" cases (probably yes — see below).

## Other "family pair" candidates that may want the same treatment

Reviewing the c6xxx namespace, several c-prefixes look like SoTE re-uses
of c3xxx/c4xxx that may want shared caps:

- **c6201 Scarab ↔ c4191 Scarab** — same chr identity
- **c6210 Albinauric Archer ↔ c3170** — same chr
- **c6220 Wolf ↔ c4070** — same chr
- **c6231 Perfumer ↔ c3701** — same chr
- **c6232 Glintstone Sorcerer ↔ c3702** — same chr
- **c6233 Page ↔ c3703** — same chr
- **c6260 Death Rite Bird ↔ c4980** — same chr
- **c6270 Royal Revenant ↔ c4020** — same chr
- **c6290 Misbegotten ↔ c3450** — same chr
- **c6291 Scaly Misbegotten ↔ c3451** — same chr
- **c6300 Snail ↔ c4140** — same chr
- **c6310 Fallingstar Beast ↔ c4680** — same chr
- **c6320 Wandering Noble ↔ c4300** — same chr

That's at least 12+ pairs. Strong argument for Option B (cap_group) so a
single mechanism handles the whole c6xxx-namespace folding. Each pair
gets `cap_group: "<chr_name>_unified"` or similar; the engine handles the
rest.

## Definition of done

1. Mechanism exists in the engine code (placement counter respects the
   shared-cap config)
2. `_shared_cap_pending` markers in nr_enemy_tags.json and
   placement_budget.json for c6251 are replaced with real
   `shared_cap_with` / `cap_group` entries
3. Stopgap `cap: 2` on c6251 in placement_budget.json is either set to
   null (with cap_group taking over) or kept as the group cap (with
   c3251 deferring to it) — pick one and stay consistent
4. Pass a placement test: 5+ runs, none place more than 2 total
   Tree Sentinels across c3251 and c6251 combined
5. Apply pattern to the other ~12 c6xxx pairs above (probably a
   one-shot batch script once the mechanism is in)

## Risk

Low for the mechanism itself — it's a counter modification. Higher risk
on the migration: making sure the per-cp caps that get folded into
groups don't accidentally reduce overall presence of chrs the budget
intentionally elevated. E.g., if c3251 has cap=2 and c6251 has the same
stopgap cap=2, naively merging them might still produce 2 total
(intended) or 4 total (unintended) depending on implementation. The
"Option B with explicit group cap" formulation makes this least
ambiguous.
