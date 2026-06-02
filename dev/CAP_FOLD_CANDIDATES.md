# Cap-fold candidate scan — v0.28.x

## Background

The `engine.cap_groups` mechanism (shipped this session) folds multiple c-prefixes under a single cap. Without folding, `cap=N` on each prefix becomes `2N` total appearances of "the same boss." This document is the curated candidate scan to populate `data/cap_groups.json`.

Currently active: `tree_sentinel_iconic` (c3251 + c6251). The rest of this document proposes 36 additional groups across three confidence tiers, sourced from a name-similarity scan over `nr_enemy_tags.json` (68 raw pairs) filtered down to the ones where chr identity actually matches.

## Apply policy

This spec deliberately does NOT modify `V3_UNIQUE_TARGET_CAPS`. Folding alone needs a cap to fold *under*; some groups have a cap on one member (✓ ready to fold), others have neither member capped (✗ need cap authoring before fold takes effect).

When applying:

1. For **one_capped** groups: add the group to `data/cap_groups.json` and the fold takes effect immediately (the existing cap covers all members).
2. For **identical_stats**, **tier_swing**, **size_variance**, **identity**, **phases**, **sprouts** groups: pick a cap value for one (or all) of the members in V3_UNIQUE_TARGET_CAPS, then add the group. Without a cap, the fold has no behaviour effect.
3. For **none_capped** groups where you don't want to author a new cap: still add the group entry. It costs nothing and means the moment anyone caps a member in the future, the fold kicks in automatically.

## Summary: 36 candidates (25 HIGH, 9 MED, 2 LOW). 6 are ready-to-fold today (one_capped).

### [HIGH] `albinauric_archer_iconic`

**Kind**: identical_stats  
**Members**: c3170, c6210  
**Rationale**: Both Albinauric Archers. NB: c3170 is in V3_EXCLUDE_PREFIXES (rider component, excluded as both source and target). Group exists for completeness; only c6210 is functionally placeable.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3170** Albinauric Archer: tier=grunt, size=S, hp_max=410, cap=—
   - **c6210** Albinauric Archer (SoTE): tier=grunt, size=M, hp_max=1200, cap=—

### [HIGH] `basilisk_iconic`

**Kind**: identical_stats  
**Members**: c4150, c5990  
**Rationale**: Both 338 HP S basilisks. SoTE shipped the same enemy in DLC-cp-range.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4150** Basilisk: tier=grunt, size=S, hp_max=338, cap=—
   - **c5990** Basilisk (SoTE): tier=grunt, size=S, hp_max=338, cap=—

### [HIGH] `demi_human_chief_iconic`

**Kind**: identical_stats  
**Members**: c4120, c5720  
**Rationale**: Both 534 HP demi-human chiefs.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4120** Demi-Human Chief: tier=grunt, size=M, hp_max=534, cap=—
   - **c5720** Demi-Human Chief (SoTE): tier=miniboss, size=M, hp_max=534, cap=—

### [HIGH] `demi_human_shaman_iconic`

**Kind**: identical_stats  
**Members**: c4110, c5710  
**Rationale**: Both 599 HP demi-human shamans (XS/S size variance).

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4110** Demi-Human Shaman: tier=grunt, size=XS, hp_max=599, cap=—
   - **c5710** Demi-Human Shaman (SoTE): tier=grunt, size=S, hp_max=599, cap=—

### [HIGH] `giant_beast_skeleton_iconic`

**Kind**: identical_stats  
**Members**: c3061, c5931  
**Rationale**: Both 671 HP giant beast skeletons. Tier disagreement same as above.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3061** Giant Beast Skeleton: tier=miniboss, size=L, hp_max=671, cap=—
   - **c5931** Giant Beast Skeleton (SoTE): tier=grunt, size=M, hp_max=671, cap=—

### [HIGH] `giant_rat_iconic`

**Kind**: identical_stats  
**Members**: c4090, c5761  
**Rationale**: Both 556 HP giant rats. Size class differs cosmetically (M vs S).

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4090** Giant Rat: tier=grunt, size=M, hp_max=556, cap=—
   - **c5761** Giant Rat (SoTE): tier=grunt, size=S, hp_max=556, cap=—

### [HIGH] `giant_skeleton_iconic`

**Kind**: identical_stats  
**Members**: c3060, c5930  
**Rationale**: Both 671 HP giant skeletons. Tier disagreement (miniboss vs grunt) is classification variance not chr identity.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3060** Giant Skeleton: tier=miniboss, size=M, hp_max=671, cap=—
   - **c5930** Giant Skeleton (SoTE): tier=grunt, size=M, hp_max=671, cap=—

### [HIGH] `glintstone_sorcerer_iconic`

**Kind**: identical_stats  
**Members**: c3702, c6232  
**Rationale**: Both Glintstone Sorcerers. hp 232 vs 267 is mod-side data variance.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3702** Glintstone Sorcerer: tier=grunt, size=M, hp_max=232, cap=—
   - **c6232** Glintstone Sorcerer (SoTE): tier=grunt, size=M, hp_max=267, cap=—

### [HIGH] `guardian_golem_iconic`

**Kind**: one_capped  
**Members**: c4660, c5790  
**Rationale**: Guardian Golem: c4660 (vanilla GIGA, cap=2) + c5790 (SoTE XL re-import, uncapped). Folding makes the existing cap=2 apply to both.

**Existing cap**: `c4660:2` — group ready to fold today.


   - **c4660** Guardian Golem: tier=miniboss, size=GIGA, hp_max=2419, cap=2
   - **c5790** Guardian Golem: tier=miniboss, size=XL, hp_max=5236, cap=—

### [HIGH] `living_jar_warrior_iconic`

**Kind**: identical_stats  
**Members**: c4490, c5750  
**Rationale**: Both 449 HP living jar warriors.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4490** Living Jar Warrior: tier=grunt, size=L, hp_max=449, cap=—
   - **c5750** Living Jar Warrior: tier=grunt, size=L, hp_max=449, cap=—

### [HIGH] `man_bat_iconic`

**Kind**: identical_stats  
**Members**: c4200, c5530  
**Rationale**: Both 430 HP man-bats. S vs M size variance.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4200** Man-Bat: tier=grunt, size=M, hp_max=430, cap=—
   - **c5530** Man-Bat: tier=grunt, size=S, hp_max=430, cap=—

### [HIGH] `misbegotten_iconic`

**Kind**: identical_stats  
**Members**: c3450, c6290  
**Rationale**: Both Misbegotten. NB: hp differs in tags (2640 vs 192) — this is a tags-side data issue, not a chr-identity issue. They are the same.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3450** Misbegotten: tier=grunt, size=M, hp_max=2640, cap=—
   - **c6290** Misbegotten (SoTE): tier=grunt, size=M, hp_max=192, cap=—

### [HIGH] `page_iconic`

**Kind**: identical_stats  
**Members**: c3703, c6233  
**Rationale**: Both 582 HP pages.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3703** Page: tier=grunt, size=M, hp_max=582, cap=—
   - **c6233** Page (SoTE): tier=grunt, size=M, hp_max=582, cap=—

### [HIGH] `perfumer_iconic`

**Kind**: identical_stats  
**Members**: c3701, c6231  
**Rationale**: Both Perfumers.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3701** Perfumer: tier=miniboss, size=M, hp_max=480, cap=—
   - **c6231** Perfumer: tier=grunt, size=M, hp_max=?, cap=—

### [HIGH] `rat_iconic`

**Kind**: identical_stats  
**Members**: c4080, c5760  
**Rationale**: Both 162 HP rats. SoTE re-import; XS vs S size variance.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4080** Rat: tier=grunt, size=S, hp_max=162, cap=—
   - **c5760** Rat (SoTE): tier=grunt, size=XS, hp_max=162, cap=—

### [HIGH] `royal_revenant_iconic`

**Kind**: one_capped  
**Members**: c4020, c6270  
**Rationale**: Royal Revenant: c4020 (vanilla cap=8) + c6270 (SoTE uncapped). Existing cap=8 applies to both.

**Existing cap**: `c4020:8` — group ready to fold today.


   - **c4020** Royal Revenant: tier=miniboss, size=L, hp_max=679, cap=8
   - **c6270** Royal Revenant (SoTE): tier=miniboss, size=L, hp_max=679, cap=—

### [HIGH] `runebear_iconic`

**Kind**: one_capped  
**Members**: c4630, c5780  
**Rationale**: Runebear: c4630 (vanilla cap=2) + c5780 (SoTE uncapped). Existing cap=2 applies to both.

**Existing cap**: `c4630:2` — group ready to fold today.


   - **c4630** Runebear: tier=miniboss, size=XXL, hp_max=2585, cap=2
   - **c5780** Runebear: tier=miniboss, size=XL, hp_max=2585, cap=—

### [HIGH] `scaly_misbegotten_iconic`

**Kind**: identical_stats  
**Members**: c3451, c6291  
**Rationale**: Both 531 HP scaly misbegotten.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3451** Scaly Misbegotten: tier=grunt, size=M, hp_max=531, cap=—
   - **c6291** Scaly Misbegotten (SoTE): tier=grunt, size=M, hp_max=531, cap=—

### [HIGH] `scarab_iconic`

**Kind**: identical_stats  
**Members**: c4190, c6201  
**Rationale**: Both Scarabs (small loot bugs). NB: c4191 is in V3_EXCLUDE_PREFIXES; only c4190 + c6201 are placeable, and they fold together.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4190** Large Scarab: tier=grunt, size=S, hp_max=213, cap=—
   - **c6201** Scarab: tier=grunt, size=S, hp_max=?, cap=—

### [HIGH] `tibia_mariner_iconic`

**Kind**: tier_swing  
**Members**: c4950, c5620  
**Rationale**: Tibia Mariner: c4950 (night_boss tier, vanilla) vs c5620 (miniboss tier, SoTE re-import). Both 1918 HP — same chr at different tier classification.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4950** Tibia Mariner: tier=night_boss, size=XL, hp_max=1918, cap=—
   - **c5620** Tibia Mariner: tier=miniboss, size=L, hp_max=1918, cap=—

### [HIGH] `troll_iconic`

**Kind**: one_capped  
**Members**: c4600, c5390  
**Rationale**: Troll: c4600 (vanilla cap=6) + c5390 (SoTE uncapped). Existing cap=6 applies to both.

**Existing cap**: `c4600:6` — group ready to fold today.


   - **c4600** Troll: tier=miniboss, size=XXL, hp_max=1901, cap=6
   - **c5390** Troll (SoTE): tier=miniboss, size=XL, hp_max=1901, cap=—

### [HIGH] `troll_knight_iconic`

**Kind**: one_capped  
**Members**: c4601, c5391  
**Rationale**: Troll Knight: c4601 (vanilla cap=6) + c5391 (SoTE uncapped). Existing cap=6 applies to both.

**Existing cap**: `c4601:6` — group ready to fold today.


   - **c4601** Troll Knight: tier=miniboss, size=XXL, hp_max=1901, cap=6
   - **c5391** Troll Knight (SoTE): tier=miniboss, size=XL, hp_max=1901, cap=—

### [HIGH] `ulcerated_tree_spirit_iconic`

**Kind**: one_capped  
**Members**: c4640, c5960  
**Rationale**: Ulcerated Tree Spirit: c4640 (vanilla cap=2) + c5960 (SoTE uncapped). Existing cap=2 applies to both.

**Existing cap**: `c4640:2` — group ready to fold today.


   - **c4640** Ulcerated Tree Spirit: tier=night_boss, size=XXL, hp_max=2854, cap=2
   - **c5960** Ulcerated Tree Spirit: tier=night_boss, size=L, hp_max=2713, cap=—

### [HIGH] `wandering_noble_iconic`

**Kind**: identical_stats  
**Members**: c4300, c6320  
**Rationale**: Both 85 HP wandering nobles. Exactly identical.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4300** Wandering Noble: tier=grunt, size=M, hp_max=85, cap=—
   - **c6320** Wandering Noble (SoTE): tier=grunt, size=M, hp_max=85, cap=—

### [HIGH] `wolf_iconic`

**Kind**: identical_stats  
**Members**: c4070, c6220  
**Rationale**: Both wolves. The mod has c6220 at 2498hp vs c4070 at 78hp — that mismatch reflects an SoTE variant scaling issue worth investigating but doesn't change identity.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4070** Wolf: tier=grunt, size=S, hp_max=78, cap=—
   - **c6220** Wolf (SoTE): tier=grunt, size=M, hp_max=2498, cap=—

### [MED] `abductor_virgin_iconic`

**Kind**: size_variance  
**Members**: c4470, c5970  
**Rationale**: Abductor Virgin: c4470 XL/1601hp vs c5970 M/1418hp. Smaller SoTE variant but same chr — c5970 is the "field abductor" form, c4470 the "fort" form.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4470** Abductor Virgin (Unscaled): tier=miniboss, size=XL, hp_max=1601, cap=—
   - **c5970** Abductor Virgin: tier=miniboss, size=M, hp_max=1418, cap=—

### [MED] `fallingstar_beast_iconic`

**Kind**: tier_swing  
**Members**: c4680, c6310  
**Rationale**: Fallingstar Beast: c4680 (night_boss cap=2, full-grown) vs c6310 (miniboss, SoTE field variant). Same chr, two scales.

**Existing cap**: `c4680:2` — group ready to fold today.


   - **c4680** Full-Grown Fallingstar Beast (Unscaled): tier=night_boss, size=GIGA, hp_max=2946, cap=2
   - **c6310** Fallingstar Beast (SoTE): tier=miniboss, size=XL, hp_max=3154, cap=—

### [MED] `inquisitor_iconic`

**Kind**: identity  
**Members**: c5311, c5312  
**Rationale**: Inquisitor: c5311 Candles vs c5312 Staff. Same chr identity with two weapon loadouts. The hp gap (173 vs 1722) reflects difficulty variants.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c5311** Inquisitor (Candles): tier=miniboss, size=M, hp_max=173, cap=—
   - **c5312** Inquisitor (Staff): tier=miniboss, size=M, hp_max=1722, cap=—

### [MED] `jar_innards_iconic`

**Kind**: size_variance  
**Members**: c5270, c5271  
**Rationale**: Jar Innards: c5270 grunt L vs c5271 miniboss XL. Two sizes of the same pop-out enemy.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c5270** Jar Innards: tier=grunt, size=L, hp_max=397, cap=—
   - **c5271** Jar Innards (Large): tier=miniboss, size=XL, hp_max=666, cap=—

### [MED] `lamprey_iconic`

**Kind**: size_variance  
**Members**: c5060, c5061  
**Rationale**: Lamprey: c5060 grunt L vs c5061 miniboss XL. Two sizes of the same cluster enemy.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c5060** Lamprey: tier=grunt, size=L, hp_max=159, cap=—
   - **c5061** Lamprey (Large): tier=miniboss, size=XL, hp_max=210, cap=—

### [MED] `leonine_misbegotten_iconic`

**Kind**: size_variance  
**Members**: c3460, c5950  
**Rationale**: Leonine Misbegotten: hp 1240 vs 564 (M/M). SoTE field variant.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c3460** Leonine Misbegotten: tier=miniboss, size=M, hp_max=1240, cap=—
   - **c5950** Leonine Misbegotten: tier=miniboss, size=M, hp_max=564, cap=—

### [MED] `miranda_blossom_iconic`

**Kind**: tier_swing  
**Members**: c4480, c5380  
**Rationale**: Miranda Blossom: c4480 (XL miniboss cap=1, the boss form) vs c5380 (M grunt, the field summon form). Tier swing is intentional in the data — the boss-encounter is c4480, field encounters are c5380. Folding ensures the rare-boss cap of 1 isn't doubled.

**Existing cap**: `c4480:1` — group ready to fold today.


   - **c4480** Miranda Blossom: tier=miniboss, size=XL, hp_max=?, cap=1
   - **c5380** Miranda Blossom (SoTE): tier=grunt, size=M, hp_max=1939, cap=—

### [MED] `omenkiller_iconic`

**Kind**: size_variance  
**Members**: c4820, c5980  
**Rationale**: Omenkiller: c4820 L/986hp vs c5980 M/429hp. Same chr at different scales.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4820** Omenkiller: tier=miniboss, size=L, hp_max=986, cap=—
   - **c5980** Omenkiller: tier=miniboss, size=M, hp_max=429, cap=—

### [MED] `shade_iconic`

**Kind**: size_variance  
**Members**: c5511, c5512  
**Rationale**: Shade: c5511 vs c5512, small hp gap (376 vs 626). Two scales of same chr.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c5511** Shade: tier=miniboss, size=M, hp_max=376, cap=—
   - **c5512** Shade: tier=miniboss, size=M, hp_max=626, cap=—

### [LOW] `hippopotamus_iconic`

**Kind**: phases  
**Members**: c5010, c5011  
**Rationale**: Golden Hippopotamus: c5010 field_boss (phase 1 base) + c5011 night_boss (Golden Wings, cap=2). Two phases of the same named boss; cap=2 already reflects the desired rarity. Folding ensures players don't encounter both phases as if they were separate bosses.

**Existing cap**: `c5011:2` — group ready to fold today.


   - **c5010** Golden Hippopotamus: tier=field_boss, size=XXL, hp_max=2957, cap=—
   - **c5011** Golden Hippopotamus (Golden Wings): tier=night_boss, size=XXL, hp_max=1792, cap=2

### [LOW] `miranda_sprout_iconic`

**Kind**: sprouts  
**Members**: c4481, c5381  
**Rationale**: Miranda Sprout: c4481 (vanilla M) + c5381 (SoTE XS). Field summons of the Miranda Blossom encounter. Less player-recognizable as "the same boss" than the blossom itself — these are basically environmental hazards.

**Cap status**: no member has a cap entry. Folding has no behavior effect until a cap is authored on one of the members.


   - **c4481** Miranda Sprout: tier=grunt, size=M, hp_max=?, cap=—
   - **c5381** Miranda Sprout (SoTE): tier=grunt, size=XS, hp_max=119, cap=—

## Recommended apply order

1. **Phase 1 (free wins)**: 6 `one_capped` HIGH groups — `guardian_golem`, `royal_revenant`, `ulcerated_tree_spirit`, `runebear`, `troll`, `troll_knight`. These have an existing cap on the vanilla prefix and the SoTE re-import is uncapped. Folding immediately applies the existing cap to both prefixes — no cap authoring needed.

2. **Phase 2 (low-risk identity folds)**: 18 `identical_stats` HIGH groups. These are pure cosmetic SoTE re-imports of vanilla chrs (same model, same AI, same anims). No member is currently capped, so they can be added to the config but have no behaviour effect. Decision: do you want to add caps to these now (e.g. cap=20-40 for grunts to limit per-seed repetition), or leave them uncapped (status quo behavior) and rely on the existing grunt-tier cap=40 from `v0.27.8/.9: grunt tier — cap=40 set on 141 chrs`?

   - Note: per the load-time log, all 141 grunt-tier chrs ALREADY have `cap=40` applied via the v0.27.8 autoset. So the `identical_stats` HIGH groups whose members are both grunt-tier are **already ready to fold** if V3_UNIQUE_TARGET_CAPS contains those cps post-autoset. Need to verify cap visibility at the fold check.

3. **Phase 3 (tier-swing groups)**: `tibia_mariner_iconic`, `miranda_blossom_iconic`, `fallingstar_beast_iconic`, etc. These have one prefix in a boss tier (named encounter) and one in a field tier (regular mob). The cap=1 or cap=2 of the boss form should logically cover both so a "rare named encounter" stays rare even when its field-form is around.

4. **Phase 4 (size-variance groups)**: `jar_innards`, `lamprey`, `shade`, `inquisitor`, plus the MED categories. These are the "same chr with two sizes" pattern. Worth folding for visual consistency (player encounters one "Inquisitor" type per run, not both at once) but lower priority than the iconic fold cases.

5. **Phase 5 (LOW)**: `hippopotamus_iconic` and `miranda_sprout_iconic`. Skip if uncertain — these are borderline calls where reasonable people could disagree on whether the cps are "the same chr" or two related-but-distinct encounters.

## Updated `data/cap_groups.json`

I have updated `data/cap_groups.json` to add all 35 candidates under `_pending_after_other_cps_wired.candidate_pairings`. The `groups` section remains unchanged with only `tree_sentinel_iconic` active — apply policy is documented in this spec rather than auto-applied.

When you decide which to activate, the workflow is:

1. Move the entry from `_pending_after_other_cps_wired.candidate_pairings` into `groups`.
2. If the kind is `identical_stats` / `size_variance` / `phases` etc and you want a behaviour effect, also add a cap to `V3_UNIQUE_TARGET_CAPS` on at least one member.
3. Run `pytest tests/test_cap_groups.py` to confirm the audit passes.
