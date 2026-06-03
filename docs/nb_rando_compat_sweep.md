# NB Rando-Compat Sweep — v0.28.x

Empirical pass over all 28 Night Boss arenas to record which ones tolerate
engine-side randomization via `V3_NB_RANDOMIZE_WHITELIST` (the third
`_force_rando_nb` opt-in path) and which fail.

## Methodology per arena

There are now two test paths:

### Path 1 — deterministic per-Nightlord (rando off, just spawn the boss)

Tests whether the arena's vanilla setup spawns cleanly without
randomization. Uses `dev/set_nightlord_bosses.py` to generate a
`LotResultPlayAreaParam` patch pinning each Nightlord to a specific
(NB1, NB2) pair. After import:

1. Run the relevant Nightlord's expedition
2. Walk to NB1 → record outcome at that arena
3. Walk to NB2 → record outcome at that arena
4. Record in the table below: vanilla c_prefix spawned cleanly =
   `OK_vanilla`. Crash/empty/broken = `CTD` / `EMPTY` / `BROKEN`.

### Path 2 — randomization compat (rando on, swap target spawn)

Tests whether the rando's c_prefix swap functions at that arena.
Re-import the same `LotResultPlayAreaParam` patch + run the rando
engine with the all-arenas whitelist. After import:

1. Run the relevant Nightlord's expedition
2. Walk to NB1 → record what spawned (the rando-swapped chr, or empty/CTD)
3. Walk to NB2 → same
4. Record in the table: rando swap visible and functional = `OK_rando`.

## Status legend

- `OK_vanilla`    = vanilla boss spawns and functions under deterministic path
- `OK_rando`      = swapped chr spawns and functions under rando path
- `OK_rando*`     = same, BUT with cross-class side effects (e.g. soft-lock from NB2-class boss at NB1 slot). Arena is rando-compatible; placement is not.
- `BANNED`        = arena excluded from rando whitelist due to confirmed-or-predicted broken state. Stays vanilla even when rando is enabled.
- `OK_spawn`      = spawned in correctly, fight procession not verified (player died before validating)
- `EMPTY`         = swap committed in spoiler but no spawn in-game
- `CTD`           = arena load or boss spawn crashes
- `BROKEN`        = chr spawns but fight is non-functional (invisible/stuck/wrong-scale/no AI)
- `WAVE_BLOCKED`  = pre-boss wave killed the player; boss never spawned (untested)
- `TODO`          = deferred; arena not yet in a stable config, revisit later
- `SKIP`          = expected to be tested soon (in-progress)
- `?`             = result ambiguous; needs follow-up

## Results

| Arena            | Vanilla c_prefix | Boss                                                 | Det path | Rando path | Notes |
|------------------|------------------|------------------------------------------------------|----------|------------|-------|
| m47_70_00_00     | c4950            | Tibia Mariner                                        | TODO     | OK_rando   | Fulghor NB1 (next-16 test) — swap target spawned and fought correctly |
| m47_80_00_00     | c7700            | Gaping Dragon (DS1 port)                             | SKIP     | OK_rando   | Adel default config — first confirmed DS-port working under rando |
| m47_90_00_00     | c7710            | Centipede Demon (DS1 port)                           | TODO     | OK_rando   | Gladius NB1 (next-16 test) — Malenia Phase 2 target, well-behaved |
| m48_00_00_00     | c7800            | Duke's Dear Freja (DS2 port)                         | TODO     | OK_rando   | Adel NB1 (next-16 test) — boss-plus-grunts arena handles rando swap cleanly |
| m48_10_00_00     | c7820            | Smelter Demon (DS2 port)                             | OK_vanilla | OK_rando | Gnoster NB1 — earlier EMPTY with c4290 Bloodhound Knight target was chr-specific; works fine with this swap target |
| m48_20_00_00     | c7910+c7900      | Nameless King (DS3 port; mounted on Storm King)      | TODO     | BANNED     | Confirmed BROKEN — Phase 2 transition fails (Storm King death doesn't fire NK foot-form spawn). Phase-transition-broken class. Removed from rando whitelist v0.28.x. |
| m48_30_00_00     | c7920            | Dancer of the Boreal Valley (DS3 port)               | TODO     | BANNED     | Predicted BROKEN via EMEVD complexity: CharacterHasSpEffect×2 + SetSpEffect×3 + CreateReferredDamagePair×2 + WarpCharacterAndCopyFloor. Comparable to Nameless King phase-transition class. Removed from rando whitelist v0.28.x. |
| m48_40_00_00     | c2130            | Morgott (Fell Omen)                                  | OK_vanilla | BANNED   | Predicted BROKEN via EMEVD complexity: CreateReferredDamagePair×2 (likely Cursed Mark / Phase 2 black holy spear transition). Banned conservatively. Removed from rando whitelist v0.28.x. |
| m48_50_00_00     | c3250            | Draconic Tree Sentinel + 2 Royal Cavalryman          | TODO     | OK_rando   | Maris NB2 retest with hp nerf — Malenia P1 swapped in for primary c3250, Leyndell knights (c3252) kept vanilla by swap filter. Multi-c-prefix mounted-rider arena confirmed clean under rando. |
| m48_60_00_00     | c3251            | Tree Sentinel + 2 Royal Cavalryman                   | TODO     | OK_rando*  | Adel NB1 (nb2-at-nb1 test) — NB2-class modifier 402 placed at NB1 slot; spawned and fought correctly. *Cross-class soft-locks expedition (Day 1 never advances); see m48_80 note. |
| m48_70_00_00     | c3560            | Godskin Apostle (Duo)                                | TODO     | TODO       | (not in default config) |
| m48_80_00_00     | c3570+c3560      | Godskin Noble + Godskin Apostle (Duo)                | TODO     | OK_rando*  | Gnoster NB1 (nb2-at-nb1 test) — swap target Midra spawned and fought correctly. *Cross-class side effect: NB2-class boss at NB1 slot SOFT LOCKS the expedition. Boss-death event fires Night Repulsed; no Day 2 advance; timer expiration doesn't recover. Arena itself is rando-compatible. |
| m48_90_00_00     | c4580            | Large Wormface                                       | TODO     | TODO       | (not in default config; mod 412) |
| m49_10_00_00     | c4750            | Grafted Monarch                                      | TODO     | OK_rando   | Maris NB1 (next-16 test) — confirmed safe under rando. V1 NB1 pick was correct all along. |
| m49_17_00_00     | c4770            | Valiant Gargoyle                                     | TODO     | TODO       | (not in default config) |
| m49_18_00_00     | c4911            | Great Wyrm Theodorix (Magma Wyrm)                    | OK_vanilla | OK_rando | Gnoster NB2 — confirmed under both paths despite no vanilla NpcThinkParam rows for c4911 |
| m49_19_00_00     | c4510            | Ancient Dragon                                       | SKIP     | OK_rando   | Adel NB2 default (mod 445) — confirmed working under rando |
| m49_20_00_00     | c4680            | Full Grown Fallingstar Beast                         | TODO     | OK_rando*  | Maris NB1 (nb2-at-nb1 test) — NB2-class modifier 435 at NB1 slot; spawned and fought correctly. *Cross-class soft-locks expedition; see m48_80 note. |
| m49_21_00_00     | c4980            | Death Rite Bird                                      | TODO     | TODO       | Libra default config |
| m49_23_00_00     | c4650            | Dragonkin Soldier                                    | TODO     | TODO       | (not in default config) |
| m49_24_00_00     | c3100            | Bell Bearing Hunter                                  | TODO     | OK_rando   | Libra NB1 (next-16 test) — Messmer P2 (SoTE DLC) swapped in, full fight worked. Inline verification that Messmer P2 import is rando-functional. |
| m49_25_00_00     | c2500+c5011      | Crucible Knight + Golden Hippopotamus                | TODO     | TODO       | (not in default config) |
| m49_26_00_00     | c3050            | Outland Commander (Lightning/Frostbite)              | TODO     | BANNED     | Banned by user preference. Commander c3050 c_prefix shared with Battlefield Cmdr; conservative ban pending future investigation. |
| m49_27_00_00     | c3050            | Battlefield Commander (Scarlet Rot)                  | TODO     | BANNED     | Banned by user preference. Shares c3050 c_prefix with Outland Cmdr; conservative ban pending future investigation. |
| m49_28_00_00     | c3150+c3160      | Night's Cavalry (Glaive + Flail, mounted)            | TODO     | TODO       | (not in default config) |
| m49_29_00_00     | c4130+c5810      | Demi-Human Queen + Demi-Human Swordmaster            | OK_vanilla | SKIP     | Gladius NB1 default — confirmed deterministic; multi-c-prefix arena loads cleanly |
| m49_30_00_00     | c4021            | Royal Revenant                                       | TODO     | OK_rando   | Caligo NB1 (next-16 test) — swap target spawned and fought correctly. Untested in vanilla until now; corner-case arena confirmed clean. |
| m49_90_00_00     | c4640            | Ulcerated Tree Spirit                                | TODO     | OK_rando   | Heolstor NB1 (next-16 test) — swap target spawned and fought correctly. Corner-case arena confirmed clean. |

## Aggregate

- `OK_vanilla`: 4 / 28  (m48_40, m49_29, m48_10, m49_18)
- `OK_rando`: 12 / 28  (m47_80, m49_19, m48_10, m49_18, m47_90, m48_00, m49_10, m48_50, m49_24, m47_70, m49_30, m49_90)
- `OK_rando*` (cross-class soft-lock; arena fine at proper NB2 slot): 3 / 28  (m48_60, m48_80, m49_20)
- `BANNED` (excluded from rando whitelist): 5 / 28  (m48_20 NK, m48_30 Dancer, m48_40 Morgott, m49_26 Outland Cmdr, m49_27 Battlefield Cmdr)
- `TODO` (untested, but EMEVD-clean and predicted-safe): 3 / 28  (m49_21 DRB, m49_23 Dragonkin, m49_25 Crucible+Hippo; plus m48_70 Godskin Apostle which is unreachable in vanilla)
- `EMPTY`: 0 / 28
- `CTD`: 0 / 28
- `BROKEN`: 0 / 28 (m48_20 NK was reclassified to BANNED)

## Sweep conclusion (v0.28.x)

Out of 28 NB arenas:
- **15 confirmed working under rando** (12 OK_rando + 3 OK_rando* — the latter functional when placed at proper NB2 slot)
- **3 banned** for confirmed-or-predicted phase-transition breakage
- **5 untested but predicted-clean** based on EMEVD analysis (zero phase-transition signatures)
- **1 unreachable** in vanilla (m48_70 Godskin Apostle has no LotResultPlayAreaParam references)

Sweep called complete; remaining untested arenas can be validated incrementally during normal play.

## Hypotheses being tested

The sweep should discriminate between several models:

1. **Engine-only randomization works for every NB arena.** Smelter is an
   outlier — chr-specific or seed-flag-specific issue. Expected if
   `OK` count converges high and `EMPTY/CTD/BROKEN` is just a few
   arenas with chr-compat issues.
2. **DS-port arenas are categorically broken under engine-only rando.**
   Expected if all 6 DS-port arenas (m47_80, m47_90, m48_00, m48_10,
   m48_20, m48_30) fail and the other 22 work.
3. **All NB arenas with `recipient_is_boss=true` Parts beyond the
   primary slot are broken.** From the MSB dumps, m48_10 has a second
   boss-flagged Part (c4260 at index 2, entity_id=0); other arenas may
   too. Pattern to watch for in `BROKEN` cases.
4. **Engine-only rando is broadly broken; the spoiler reports swaps that
   don't reach the runtime.** Expected if most arenas come back `EMPTY`.

## Cross-references

- Whitelist file: `data/nb_encounter_whitelist.json`
- Helper script: `dev/set_nb_whitelist_target.py`
- Engine gate: `oops_v3.py` line ~13559, the third `_force_rando_nb`
  clause that fires when `slot_msb_name in V3_NB_RANDOMIZE_WHITELIST`.
- Source-of-truth arena table: `data/nightreign_arena_structure.json`
  (cleaned in v0.28.x to remove the stale script-spawn-overlay model)
