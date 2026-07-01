# Design: tier-gated item-drop rarity

## Goal
Keep enemy drops randomized (and *more* varied than vanilla), but make item
**quality correlate with enemy difficulty** — probabilistically, not as a hard
gate. Trash drops mostly Common/Uncommon; minibosses lean Rare; field bosses
lean Rare with a Legendary tail; night bosses lean Legendary.

## Reality check (from the bundled regulation)
- Rarities present: **Common, Uncommon, Rare, Legendary** — *no "Epic."*
  Your 5-tier ask maps onto 4 buckets; "field boss / Epic" becomes a
  Rare-heavy + Legendary-tail curve.
- Per-category rarity availability is uneven:
  - weapon: Common 98 / Uncommon 141 / Rare 112 / Legendary 26
  - talisman: Uncommon 56 / Rare 5  (no Common, no Legendary)
  - good: Common 33 / Uncommon 25 / Rare 31 / Legendary 3
  → the algorithm MUST renormalize the rarity weights over the rarities a
  category actually has.
- Only ~31% of today's regulation-derived drop ids carry a rarity. So we
  switch the drop reroll to draw from the **rarity-tagged pools**
  (`data/regulation_pools.json`: weapon 377 / talisman 61 / good 92), which is
  also "more random than vanilla."

## Data sources
1. **Item rarity:** `regulation_pools.json` → `id → (rarity, kind)` where
   kind ∈ {weapon, talisman, good}.
2. **Lot → enemy tier:** build once per run:
   `ItemLotParam_enemy.row` ← `NpcParam.itemLotId_enemy` ← `npc_param_id`
   → c-prefix (roster `npc_param_id`→`c_prefix`) → tier
   (`nr_enemy_tags.json[cp].tier`).
   Tiers: grunt / miniboss / fieldboss / nightboss / nightlord (+ unknown).
3. **Slot → kind:** map each lot slot's `lotItemCategory`
   (observed values 0,1,2,3,4,6,7) → {weapon, talisman, good}. **Build + verify
   this mapping** (small, ~7 values) — needed to pick the right rarity pool.

## Tier → rarity weight matrix (proposed defaults, tunable)
Rows sum to 1 before renormalization; renormalized over the rarities the
slot's category actually offers.

| tier       | Common | Uncommon | Rare | Legendary |
|------------|:------:|:--------:|:----:|:---------:|
| grunt      | 0.60   | 0.33     | 0.07 | 0.00      |
| miniboss   | 0.20   | 0.45     | 0.30 | 0.05      |
| fieldboss  | 0.05   | 0.30     | 0.50 | 0.15      |
| nightboss  | 0.00   | 0.12     | 0.43 | 0.45      |
| nightlord  | 0.00   | 0.05     | 0.30 | 0.65      |
| unknown    | 0.45   | 0.35     | 0.17 | 0.03      |  ← neutral fallback

These are knobs; the point is the *shape*, not the exact numbers.

## Algorithm (per occupied, non-preserved slot)
1. Resolve the lot's tier (default `unknown` if no owning NpcParam).
2. Resolve the slot's kind from its `lotItemCategory`.
3. Take the tier's rarity weight vector; **drop rarities the kind lacks** and
   renormalize the remainder.
4. Draw a rarity from that distribution, then draw a uniform item of that
   (kind, rarity) from the rarity-tagged pool.
5. If the chosen (kind, rarity) bucket is empty, fall back to the nearest
   present rarity (step down, then up), then to any item of that kind.
6. Preserve quantity, weights, and category as today.

## Cross-cutting rules
- **Ability buffs (8M band):** still preserved / never pooled (existing fix is
  orthogonal and stays).
- **Nothing-weight shrink:** unchanged (drop-rate lift is independent).
- **Determinism:** per-slot RNG keyed on `(seed, lot_row, slot_index)` —
  order-independent, mirrors the enemy engine's `_slot_decision_rng`.
- **Map pickups (`ItemLotParam_map`):** no enemy tier. Options (pick one):
  (a) leave uniform-random by kind; (b) gate by region/map difficulty if a
  proxy exists; (c) apply the `unknown` neutral curve. Default proposal: (c).
- **Lots owned by multiple npcs / ambiguous tier:** take the *highest* tier
  among owners (so a shared lot doesn't get nerfed by its weakest user).

## Tunability / GUI
- Ship the matrix as data (e.g. `data/drop_rarity_by_tier.json`) so it's
  editable without code.
- Optional GUI: a single "drop quality gating" strength slider that lerps
  between "flat/uniform" (today) and "full tiering" (matrix), plus an off
  switch (= current behavior).

## Testing plan (all runnable in Cowork; deps now installable)
- **Unit:** renormalization correctness (weights over present rarities sum to
  1; empty-bucket fallback resolves; unknown-tier path).
- **Statistical:** over N seeds, the realized rarity distribution per tier is
  within tolerance of the (renormalized) target — e.g. grunts' Legendary rate
  ≈ 0, nightboss Legendary rate high. Use a chi-square / band assertion.
- **Invariants:** category/quantity preserved; ability-buff slots still
  preserved; determinism (same seed → identical patches).
- **Coverage:** every `lotItemCategory` maps to a kind (no slot silently
  skipped).

## Open questions for you
1. Confirm the 4-bucket mapping (Epic→field-boss = Rare+Legendary tail) is what
   you want, or do you want to *synthesize* an Epic tier (e.g. treat top-N
   Legendary-by-value as "Epic")?
2. Map pickups: neutral curve (c), or leave uniform (a)?
3. Should tier gating also apply to the **merchant shop** randomizer, or drops
   only?
4. How hard a gate — keep the small cross-tier tails (a grunt *can* rarely drop
   Legendary), or hard-floor/ceiling per tier?

---

# Revision 2 — decisions locked + chaos/chest/shop findings

## Confirmed decisions
- **Cross-tier tails:** keep the small tails (a grunt *can* rarely drop high
  rarity). Soft gating, no hard floors/ceilings.
- **Map pickups:** apply the `unknown` **neutral curve**.
- **Merchant shop:** do NOT rarity-gate shops. Instead **shrink the top of the
  price range — roughly halve the highest prices** (compress the upper tail so
  expensive items get cheaper; cheap items ~unchanged). Implemented in the shop
  randomizer as a price-cap/scale on the high end, independent of the drop
  rarity system.

## Epic tier from chaos weapons — feasibility
Idea: synthesize an **Epic** rarity from the red "chaos" weapons (2 positive
innate effects + 1 negative).

Findings:
- The clean weapon pool is base rows only (`ID%10000==0`). Chaos/affix variants
  live in the **sub-id space**: sub-ids 500–1100 are the bulk affix tiers
  (~210 rows each); the small-count high tiers **2000/3000/4000/5000/6000/7000**
  (37/34/29/27/18/13 rows) are the likely special-innate rows.
- BLOCKED from here: confirming "2 buffs + 1 debuff" needs the
  `EquipParamWeapon` resident-spEffect fields (residentSpEffectId 1/2/3) **plus**
  SpEffectParam buff/debuff classification, and the *red* color is an item-FMG
  name tag — none of which are readable without a Nightreign paramdef / the
  item FMGs (not in the repo, encrypted in the archives).

Paths to actually build Epic (pick one):
1. **Resident-spEffect detection (most faithful):** with an `EquipParamWeapon`
   + `SpEffectParam` paramdef (or a Smithbox export of both), flag weapon rows
   whose 3 resident spEffects = 2 net-positive + 1 net-negative → Epic set.
2. **Curated id list:** you (or a community list) supply the chaos-weapon ids /
   the exact sub-id band; we tag those Epic. Fast, no paramdef.
3. **Defer:** ship 4 tiers now; add Epic as a follow-up once the set is pinned.

Epic would slot between Rare and Legendary in the matrix (field boss = your
"Epic" tier gets the heaviest Epic weight, with Rare/Legendary tails).

## Rare chests — feasibility
"Chests" are a map-gimmick concept; the lot param has no chest flag, so true
chest detection needs the **map asset→lot mapping** (not in the regulation).
Usable proxy available now: of 4313 `ItemLotParam_map` rows, **3012 are
guaranteed (no nothing-slot)** and **137 of those already contain a
Rare/Legendary** item. Options:
- **Proxy juice (now):** bump the rarity curve for guaranteed map lots that
  already hold a Rare/Legendary (treat them as "good chests").
- **True chests (later):** derive a chest-lot set from the map gimmick/asset
  data and juice exactly those.

## Updated open asks
1. **Epic/chaos:** path 1 (give me an EquipParamWeapon+SpEffect paramdef or
   Smithbox export), path 2 (hand me the chaos-weapon ids / sub-id band), or
   path 3 (defer)?
2. **Chests:** OK with the proxy (guaranteed map lots w/ Rare+ get juiced), or
   hold for true chest detection?
3. **Shop price cut:** "halve the top" — confirm the shape: hard cap at the
   ~50th-percentile price? scale prices above a threshold by 0.5? compress the
   top quartile? (I'd default to: prices above the median are scaled toward the
   median by 50%.)

---

# Revision 3 — MAJOR: ItemTableParam indirection (the scarab bug)

## Root cause (definitive, via Smithbox mod_dump)
`lotItemCategory == 7` does NOT award a direct item — it references an
**ItemTableParam** row that resolves to the real item. Example: the lot named
`[Scarab]` (24191000) awards `category 7, id 4000000`; `ItemTableParam[4000000]`
= "[Rare] Ancestral Spirit's Horn" → `category 4 (talisman), id 6110`. So
scarabs drop a **talisman via the table**, not a direct item.

The drop randomizer (both the pre-existing flat reroll AND the new tiered one)
treated category 7 as a direct item and rerolled the id → a raw weapon, which
the game can no longer resolve as a table → the drop silently breaks. This is
the "scarabs stopped dropping talismans" bug.

## Scope — this is the MAJORITY of drops
Enemy `ItemLotParam` category distribution (all slots):
`cat7=2845, cat1=551, cat6=434, cat2=303, cat3=115, cat4=4`.
So **category 7 (table refs) is ~67% of enemy drop slots.** They resolve to
protectors, accessories, nested tables, etc. The flat randomizer had been
corrupting most table-driven drops mod-wide.

(Also corrects an earlier mistake: the volume heuristic mislabeled cat7 as
"weapon" because table ids like 4000000 collide with weapon ids in the partial
pool. The Smithbox dump is authoritative; cat7 = ItemTableParam.)

## Fix shipped now: PRESERVE table references
`mob_drop_fill` now preserves any slot that is `category 7` OR whose
`lotItemId` is an `ItemTableParam` row (`load_table_item_ids` reads the param's
row ids straight from the regulation — no offsets needed). Preserved slots are
never pooled and never rerolled. This instantly un-breaks scarabs and every
table-driven drop (they revert to correct vanilla behavior). Buff-band (8M)
preservation is unchanged. Tests: `test_is_table_ref_logic`,
`test_scarab_table_drops_preserved` (regulation-gated).

## Consequence + open decision
With table refs preserved, the tier-gated randomization now only touches the
**direct-item** slots (weapon/accessory/good categories) — the majority
(table) drops are vanilla again, NOT randomized.

To ALSO randomize table-driven drops (the real goal — "scarabs keep dropping
*randomized* talismans"), the table-aware approach:
1. Classify every `ItemTableParam` row by its resolved (kind, rarity) — the
   Smithbox `ItemTableParam.csv` gives each table's `itemCategory`/`itemId`
   (resolve nested tables transitively).
2. For a table-ref drop slot, reroll the **table reference** to a different
   table of the **same resolved kind**, tier-gated by rarity (scarab's
   talisman-table → a random talisman-table). Keeps the indirection valid; no
   category rewrite needed.
   (Alternative: resolve→replace with a direct item, rewriting category 7→the
   kind's category. Simpler per-slot but loses the table semantics.)

DECISION NEEDED: ship preserve-only now (tables vanilla, direct items gated),
or build the table-reroll layer so table drops are randomized within-kind too?

---

# Revision 4 — table reroll IMPLEMENTED (scarabs randomize within-kind)

Table-driven drops are now randomized too. `drop_tiers.DropTierModel.load_tables(reg)`
classifies every `ItemTableParam` row by resolved kind+rarity at runtime:
parse each row's entries (10 x 36-byte, itemId @ +8), resolve each item's kind
via the regulation's own EquipParam* membership (recursing nested tables), and
read rarity from `regulation_pools.json` where tagged.

`pick_table(rng, kind, tier)` rerolls a table reference to a *different table of
the same kind*, rarity-gated by the tier curve (renormalized over the rarities
that kind's tables actually have; falls back to any same-kind table incl.
unranked). `mob_drop_fill` routes each table-ref slot: weapon/talisman/good
tables → within-kind reroll; protector/unknown/nested → preserved vanilla.

Result (bundled regulation, enemy lots): 1820 table slots reroll within-kind
(weapon 1366 / good 446 / talisman 8), 1074 preserved. The `[Scarab]` lots
(talisman tables) reroll to other talisman tables — scarabs drop a *randomized*
talisman, exactly as asked. Deterministic; verified by
`test_table_classification_and_pick_table_kind` and
`test_scarab_rerolls_to_a_talisman_table` (regulation-gated).

Net coverage: direct-item slots gate by tier (Rev 1-2); table-ref slots
(the majority) reroll within-kind, tier-gated (Rev 4); ability buffs and
protector/unknown tables preserved.
