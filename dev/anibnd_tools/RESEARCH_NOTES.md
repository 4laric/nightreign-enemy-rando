# Option C research notes — entrance-animation classification from anibnds

**Status:** ~70% complete. Tooling built, corpus scanned (396 chrs), v0.24.79 seed validated, Miranda family added (v0.24.80). Full auto-derivation blocked at the anim-ID level — the actual emerge signature lives in Havok keyframe data or behavior-tree (.behbnd) files, which require deeper reverse-engineering than the anibnd alone.

## Hypotheses tested

### H1 — Animation ID 9000 is the emerge signature

**Initial result (4-chr sample):** Promising. c4810 + c4440 both had anim 9000, while c4500/c4660/c4910/c4510 did not.

**At corpus scale (396 chrs):** Failed. 291 of 396 chrs (73%) have anim 9000. It is the standard "encounter wake-up" animation used by most enemies, not specifically emerge_from_ground.

**Salvageable signal:** Anim 9000 ABSENCE is a high-confidence NOT-emerge filter (105 chrs). These all have bespoke cinematic intros — all GIGA bosses, most XXL bosses, all flying_dragon class, aquatic crabs, trolls. See `high_confidence_not_emerge.json`.

### H2 — Anim ID intersection (anims shared across all 4 emerge chrs that are rare elsewhere)

**Result:** Failed. 24 anim IDs are shared across all 4 confirmed emerge (c4440, c4480, c4481, c4810). The rarest of them (1003002) still appears in 37% of all chrs. No anim ID is rare enough to be a discriminative signature.

### H3 — Structural counts pattern in anim 9000 record

The anim record has 3 counts (event_group_count, event_count, time_count). Emerge chrs all have counts (1, 1, 2). But so do many non-emerge chrs (Wolves, Rats, Demi-Humans, Banished Knights). Pattern (2, 2, 2) appears in Slugs and Jellyfish; (2, 2, 3) in Grafted Scion + Godrick. **Counts are an architecture detail, not an emerge classifier.**

### H4 — Event payload bytes differ at specific offsets

**Result:** Failed. Direct byte-level comparison of anim 9000 records between emerge and non-emerge chrs with the same counts pattern shows **structurally identical** payloads. The pointer chain pattern, magic value (129 at +0x18), event count (1 at +0x28), terminators (0xFFFFFFFF), flag bits (0x01000000 at +0x38), event type byte (255 at +0x44) are all the same. The only differences are the absolute pointer addresses (which differ because chrs have different total file sizes).

### H5 — HKX file size (longer emerge animations)

**Result:** Failed at corpus scale. The top of the size-ranked anim 9000 HKX list is dominated by scripted-intro bosses (Tree Sentinels, Godskin Noble, Divine Beast Dancing Lion) which are NOT emerge_from_ground. Emerge chrs scatter through the ranking (c4810 at rank 51, c4481 at rank 177). HKX size correlates with "scripted intro complexity" generally, not emerge specifically.

### H6 — Combination signature: "has 9000 AND lacks 9400-range locomotion variants"

**Result:** Tightest filter, but still too broad. 99 chrs match (all 4 confirmed emerge plus ~95 false positives). The locomotion-variants check separates "trash mobs with full directional movesets" from "scripted-intro bosses with simpler movesets." Emerge_from_ground is a strict subset of scripted-intro-boss, and the distinction within that set isn't visible at this layer.

## What we proved

| Question | Answer |
|---|---|
| Does emerge classification live in the anibnd? | **Partially.** Necessary condition (anim 9000 presence) is in anibnd. Sufficient condition is not. |
| Where is the rest? | Almost certainly in the chr's **behavior tree (.behbnd)** — the AI state machine that decides WHEN to play anim 9000 and what state to enter beforehand. OR in **Havok HKX keyframe data** — the actual Y-axis displacement curve during the animation. |
| Is variant inheritance real? | **Yes.** 71 of 150 chrs in the 4xxx range have skeleton-only anibnds (no TAE). They inherit animations from their parent chr at runtime. Pattern: last-digit zeroing (c4441 → c4440). Validated for all v0.24.79 seed entries. |
| Was Miranda family a correct addition? | **Yes.** Strong evidence: TAE shows anim 9000 in all 4 (c4480, c4481, c4482, c4483), and game knowledge confirms they canonically rise from flower pods. v0.24.80 ships them. |

## What remains for full Option C

Either of these would crack the problem:

1. **Parse Havok keyframe data** — extract Y-axis displacement of the root bone during anim 9000. If first-frame Y is significantly below resting Y, chr is emerge. Cost: 3-6 hours; Havok format is complex but the soulsformats project has Python bindings. Reliable but expensive.

2. **Parse behavior tree (.behbnd)** — the AI state machine. Look for a "BurrowedState" or "EmergingState" transition. Cost: similar complexity; behbnd format is partially documented. Direct semantic signal.

3. **Game-knowledge augmentation** — manually classify each of the 99 scripted-intro-boss candidates from gameplay knowledge. Slow but reliable. Could draw on the `emerge_candidates_for_playtest.json` list for the highest-priority subset.

For now, the recommended path is **(3) supplemented by playtest CTD reports**. The `entrance_animations.json` schema supports organic growth, and the gate at Fort GG is the main empirical hot spot.

## Reusable artifacts

- `bnd4_reader.py` — BND4 archive parser (0x24-byte entries, UTF-16-LE names)
- `tae_anim_ids.py` — Skim anim IDs from a chr's TAE  
- `emerge_candidates_for_playtest.json` — 8 game-knowledge candidates for review
- `high_confidence_not_emerge.json` — 105 chrs definitively not emerge (for future fly_in/scripted_intro classification)
- This file — the research log

---

## v0.24.83 update — Refined signature (template + anim 9000)

User uploaded behbnds for c3xxx, c5xxx, c6xxx, c7xxx, c8xxx, c9xxx ranges, extending the behbnd corpus from 149 (c4xxx only) to **459 files** spanning c0xxx-c9xxx.

Running the chr-id-normalized template-hash analysis across the full corpus revealed **template c880d10143 has 112 members, not 25**. This is much larger than expected and includes obvious non-emerge chrs:

- **System objects** (c0110, c0120, c0130, c1000, c9001) — framework/player templates
- **Crab family** (c2270-c2277) — sit-and-attack enemies that DO NOT emerge
- **Training Posts** (c8130, c8131, c8132) — static dummies
- **Lightning Ball** (c2150) — a projectile, not an enemy

**Conclusion: template c880d10143 is the DEFAULT MINIMAL-AI archetype**, not specifically the emerge_from_ground signature. Emerge chrs use this template because their AI is minimal ("sit idle until triggered → play scripted reveal → engage"), but so do many non-emerge chrs with similar minimal AI ("sit idle until triggered → engage without intro").

### Refined signature

Cross-referencing with anim 9000 presence (the standard wake-up animation):

| Filter | Count | Interpretation |
|---|---|---|
| Template c880d10143 alone | 112 | Necessary but not sufficient |
| Template + has anim 9000 | 50 | **Plausible emerge candidates** |
| Template + LACKS anim 9000 | 35 | Non-emerge (System, Crabs, Training Posts, etc.) |
| Template + no anim data (c6+ range) | 27 | Coverage gap — anibnds not scanned for these |

The **(template ∩ anim 9000)** intersection is the refined emerge signature. v0.24.82's 19-chr expansion was based on template-alone analysis (limited to c4xxx); the c4xxx-only scope masked the over-inclusion problem because most c4xxx template members also had anim 9000.

### v0.24.82 retroactive assessment

Of the 19 v0.24.82 additions:
- **13 still hold up** under the refined signature (template + anim 9000): c4040, c4080, c4090, c4140, c4170, c4171, c4190, c4191, c4192, c4250, c4440, c4690, c4950
- **6 are false positives** (template only, no anim 9000): c4220 Octopus, c4230 Small Octopus, c4470 Abductor Virgin, c4640 Ulcerated Tree Spirit, c4711, c4751

**Decision (v0.24.83): NO rollback of v0.24.82 false positives.** Game-knowledge for c4220 (octopus sit-and-attack, no scripted intro) suggests it's safe at any slot, but the cost of false-positive classification (slightly fewer placement options) is much lower than the cost of false-negative (real CTDs). Conservative bias kept. If empirical evidence later shows these chrs are safe at no-emerge slots, they can be downgraded.

### v0.24.83 addition

**c3730 Graven School** added based on:
1. Refined signature match (template c880d10143 + anim 9000) ✓
2. Empirical CTD report from user during v0.24.80 playtest: "CTD near scholar head big ball of faces"
3. Spoiler analysis: c3730 placed at 4 slots in user's seed 308132, two at suspicious elevations (Y=22.44, Y=93.63)
4. Game knowledge: Graven School is a sphere of fused scholarly faces that appears via scripted reveal in vanilla ER

Two new slots added to `nr_no_emerge_slots.json`: m34_10_00_00 pi=90 (Y=22.44) and m60_44_38_00 pi=30 (Y=93.63). Both are SUSPECTED — user could not pin the exact failure location, so defensively blocking both.

## v0.24.83 coverage summary

- Anibnd corpus scanned: 396 chrs (c0xxx-c5xxx)
- Behbnd corpus scanned: 459 chrs (c0xxx-c9xxx)
- entrance_animations.json entries: 28 (27 from v0.24.82 + c3730)
- nr_no_emerge_slots.json entries: 3 (Fort GG + 2 suspected from c3730 CTD)

## Open coverage gaps

- Anibnds not yet scanned for c6xxx-c9xxx (27 template members in that range — could include legitimate emerge chrs)
- Many c5xxx template+anim-9000 chrs are unnamed in tag data — game-knowledge classification pending
- Refined signature suggests ~50 total emerge candidates corpus-wide vs 28 currently classified
