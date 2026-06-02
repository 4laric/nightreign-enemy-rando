# NB Rando-Compat Sweep — v0.28.x

Empirical pass over all 28 Night Boss arenas to record which ones tolerate
engine-side randomization via `V3_NB_RANDOMIZE_WHITELIST` (the third
`_force_rando_nb` opt-in path) and which fail.

## Methodology per arena

1. Flip the whitelist:
   ```
   python dev/set_nb_whitelist_target.py mXX_YY
   ```
2. Run the rando. Spoiler should show the boss slot swapped from the
   vanilla c_prefix to a new c_prefix.
3. Load the seed pinned to route to this arena. Walk to the boss room.
4. Record the outcome in the table below:
   - `OK`     — swapped chr spawns and fights normally
   - `EMPTY`  — nothing spawns (Smelter Demon's signature)
   - `CTD`    — game crashes on arena load or boss spawn
   - `BROKEN` — chr spawns but is invisible / stuck / wrong-scale /
                missing AI / falls through floor / etc.
   - `SKIP`   — couldn't test this run (no seed pin available, etc.)

A single failure mode is enough to mark the arena `EMPTY` / `CTD` /
`BROKEN`. If you want to discriminate between chr-specific and
arena-specific failure, retry with a different seed and note both
target chrs in the spoiler column.

## Status legend

- `OK`     = randomization works cleanly
- `EMPTY`  = swap committed in spoiler but no spawn in-game
- `CTD`    = arena load or boss spawn crashes
- `BROKEN` = chr spawns but fight is non-functional
- `SKIP`   = not yet tested
- `?`      = result ambiguous; needs follow-up

## Results

| Arena            | Vanilla c_prefix | Boss                                                 | Spoiler swap | In-game | Notes |
|------------------|------------------|------------------------------------------------------|--------------|---------|-------|
| m47_70_00_00     | c4950            | Tibia Mariner                                        |              | SKIP    |       |
| m47_80_00_00     | c7700            | Gaping Dragon (DS1 port)                             |              | SKIP    |       |
| m47_90_00_00     | c7710            | Centipede Demon (DS1 port)                           |              | SKIP    |       |
| m48_00_00_00     | c7800            | Duke's Dear Freja (DS2 port)                         |              | SKIP    |       |
| m48_10_00_00     | c7820            | Smelter Demon (DS2 port)                             | c4290        | EMPTY   | Bloodhound Knight target; nothing spawned. First DS-port arena tested. |
| m48_20_00_00     | c7910+c7900      | Nameless King (DS3 port; mounted on Storm King)      |              | SKIP    |       |
| m48_30_00_00     | c7920            | Dancer of the Boreal Valley (DS3 port)               |              | SKIP    |       |
| m48_40_00_00     | c2130            | Morgott (Fell Omen)                                  |              | SKIP    |       |
| m48_50_00_00     | c3250            | Draconic Tree Sentinel + 2 Royal Cavalryman          |              | SKIP    |       |
| m48_60_00_00     | c3251            | Tree Sentinel + 2 Royal Cavalryman                   |              | SKIP    |       |
| m48_70_00_00     | c3560            | Godskin Apostle (Duo)                                |              | SKIP    |       |
| m48_80_00_00     | c3570+c3560      | Godskin Noble + Godskin Apostle (Duo)                |              | SKIP    |       |
| m48_90_00_00     | c4580            | Large Wormface                                       |              | SKIP    |       |
| m49_10_00_00     | c4750            | Grafted Monarch                                      |              | SKIP    | V1 NB1 pick; previously assumed working but never end-to-end confirmed. |
| m49_17_00_00     | c4770            | Valiant Gargoyle                                     |              | SKIP    |       |
| m49_18_00_00     | c4911            | Great Wyrm Theodorix (Magma Wyrm)                    |              | SKIP    |       |
| m49_19_00_00     | c4510            | Ancient Dragon                                       |              | SKIP    |       |
| m49_20_00_00     | c4680            | Full Grown Fallingstar Beast                         |              | SKIP    |       |
| m49_21_00_00     | c4980            | Death Rite Bird                                      |              | SKIP    |       |
| m49_23_00_00     | c4650            | Dragonkin Soldier                                    |              | SKIP    |       |
| m49_24_00_00     | c3100            | Bell Bearing Hunter                                  |              | SKIP    |       |
| m49_25_00_00     | c2500+c5011      | Crucible Knight + Golden Hippopotamus                |              | SKIP    |       |
| m49_26_00_00     | c3050            | Outland Commander (Lightning/Frostbite)              |              | SKIP    |       |
| m49_27_00_00     | c3050            | Battlefield Commander (Scarlet Rot)                  |              | SKIP    |       |
| m49_28_00_00     | c3150+c3160      | Night's Cavalry (Glaive + Flail, mounted)            |              | SKIP    |       |
| m49_29_00_00     | c4130+c5810      | Demi-Human Queen + Demi-Human Swordmaster            |              | SKIP    |       |
| m49_30_00_00     | c4021            | Royal Revenant                                       |              | SKIP    |       |
| m49_90_00_00     | c4640            | Ulcerated Tree Spirit                                |              | SKIP    |       |

## Aggregate

Counts get updated as the table fills in:

- `OK`: 0 / 28
- `EMPTY`: 1 / 28  (m48_10)
- `CTD`: 0 / 28
- `BROKEN`: 0 / 28
- `SKIP`: 27 / 28

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
