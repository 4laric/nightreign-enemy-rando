# Nightreign Archipelago — Design Doc

*Draft v0.1, 2026-06-23. The de-escalating-scaling roguelite AP. Built on the proven Polycosmos (Hades AP) "Reverse Heat" pattern, ported to Nightreign and driven by the existing nightreign-enemy-rando toolchain.*

---

## 1. North star

Elden Ring Nightreign as a first-class Archipelago game where the received-item fantasy is **the game becoming survivable**, not the map getting bigger. You start each expedition brutally over-scaled, and your checks feed back a steady stream of difficulty-reduction items until the final Nightlord is beatable. It is Hades' meta-progression curve routed through the multiworld, with the Mirror of Night replaced by AP fill.

This is deliberately a different identity from ER AP (which gates *access*). Nightreign AP gates *difficulty*. The two do not overlap, so this is a second, distinct FromSoft AP offering rather than a redundant one.

## 2. Why Nightreign fits AP better than base ER

The roguelite reset. Open-world ER fights AP because the world never resets, so persistent received power is awkward to apply. Nightreign already throws you back to weak at the start of every expedition while relics and unlocks persist between runs. That is exactly AP's model: in-run state is ephemeral, received items are the meta-layer that carries across runs. De-escalation lands cleanly because each new run re-reads the current scaling level.

## 3. Prior art we are porting: Polycosmos "Reverse Heat"

The Hades apworld (NaixGames/Polycosmos) already implements this exact concept and is proven in the wild. We copy its structure directly. Key facts from its source:

- **Reverse Heat:** the run starts with every Pact of Punishment forced on (max difficulty). The item pool contains per-axis "Pact down" items; receiving one steps a single difficulty axis down. Each axis has a configurable count of down-items (e.g. `hard_labor_pact_amount` 0..5).
- **Pool sizing by back-fill:** `create_items` adds the progression items (pact-downs + sanity unlocks), places locked event items on boss-clear events, then computes `total_fillers_needed = len(locations) - len(progression_pool) - len(events) - bosses` and back-fills that remainder with currency/helper/trap filler distributed by percentage. So filler is whatever is needed to exactly match the location count.
- **Logic spine:** `set_rules` gates deeper regions on `calculate_number_of_pact_items()`, the count of de-escalation items received. You are not expected to clear deep content until enough difficulty has been removed. That single rule is what keeps the seed winnable.
- **Composable goal:** victory = `hades_defeats_needed` and/or `weapons_clears_needed` and/or `keepsakes_needed` and/or `fates_needed`.
- **Everything to the client via `fill_slot_data`:** all option values are shipped to the mod so it knows the starting scaling, the location system, and the goal.

We keep all five mechanics. Only the game-specific content (axes, locations, goal targets) changes.

## 4. Location model (what a "check" is)

A roguelite has no stable spatial location set, so checks are a count plus optional milestone layers. Hades runs exactly this hybrid; we mirror it.

### 4a. The count spine (pick one mode)

- **Interception mode** (RoR-style): the runtime client intercepts a configurable percentage of in-run loot pickups (map weapons, talismans, runes) and converts each into the next sequential check (`Pickup Check 0001` .. `N`). Simplest; fully procedural-proof.
- **Score/progress mode** (Hades-style): in-run objectives grant score by depth (reach Day 2, kill a field boss, reach the Nightlord arena). Beating your running high score grants the next check and subtracts. Configurable check count (default ~150, cap ~1000). Gives a smoother "every run makes progress even on a loss" feel.

Recommendation: ship interception first (less game-state to track), keep score mode as a v2 option. Both expose a single `score_rewards_amount`-style count that is the footprint dial.

### 4b. Milestone layers (optional, additive — where structure lives)

Flat counts are structureless; milestone checks give the seed a spine and anchor the goal:

- **Nightlordsanity:** defeating each of the 8 Nightlords is a check.
- **Nightfarersanity:** first expedition clear with each of the 8 Nightfarers is a check; receiving a Nightfarer is the unlock item that lets you play them (this is the "weaponsanity" analog — unlock-gated access).
- **Field-boss / evergaol clears:** first kill of each named field boss or evergaol target.
- **Relic / weapon first-acquisitions:** first time obtaining each notable relic or armament.
- **Run-objective milestones:** Hades-FateSanity analog (survive a run with no deaths, clear a Day under the timer, etc.).

These also give clean priority-fill anchors and good goal options.

## 5. Item pool

### 5a. De-escalation axes ("Reverse Scaling") — grounded in existing tooling

Nightreign has no built-in Pact system, so we synthesize the axes from scaling params. Each axis is a family of N "down" items (configurable count), progression-classed. Start the player at max on every enabled axis; received items step each one down. Mapping to hooks we already have:

| Axis | Effect | Existing hook |
|---|---|---|
| Enemy HP | start inflated HP, step down | `emit_hp_overrides.py` / `NpcParam.csv` HP columns |
| Enemy damage | start inflated damage, step down | `NpcParam` attack columns / SpEffect |
| Enemy density | start with extra spawns, step down | `emevd_patch.py` / `dev/msb_authoring.py` |
| Boss extra attacks / aggression | start with harder boss behavior, ease | EMEVD / NPC think (`extract_npc_think_*`) |
| Storm / day timer | start with less time, step up | EMEVD timers |
| Reward suppression | start with reduced runes/drops, restore upward | `npcparam_reward_fill.py`, `mob_drop_fill.py`, `drop_tiers.py` |
| Death penalty / revives | start harsh, ease | EMEVD / SpEffect |

Ship a subset for v1 (HP, damage, density, timer are the cleanest and you already drive the first three). Each axis count is an option, exactly like the per-pact counts in Hades.

Important behavioral note inherited from Hades: scaling changes likely apply on the **next run**, not mid-run (FromSoft state is baked per load). That is fine for a roguelite and matches Hades' own caveat.

### 5b. Meta-progression / access items

Nightfarer unlocks, notable relics, starting-gear grants. These double as the "sanity" unlock items (you must receive the Nightfarer before you can clear with them). Same role as Hades weaponsanity.

### 5c. Filler, helpers, traps

Back-fill the remainder of the location count (per the Polycosmos `total_fillers_needed` formula). Nightreign-native filler: rune packs, murk, relic-rite materials, smithing materials. Helpers: max-HP boost, extra starting flask charge, starting-rune boost. Traps (optional %): lose runes, a debuff for one run. All configurable by value and percentage, value 0 removes a type.

## 6. Goal gating

Composable victory conditions, defaulting simple:

- `nightlord_defeats_needed` (default 1: beat the expedition's Nightlord once).
- `distinct_nightlords_needed` (0..8, for a marathon "beat them all").
- `distinct_nightfarers_clears_needed` (0..8).
- Optional milestone-count goals (field bosses, relics).

Default seed = beat one Nightlord. Crank the others for long async seeds.

## 7. Winnability and the difficulty floor

Two mechanisms, both copied from Polycosmos:

- **Logic spine:** deeper checks and the Nightlord goal are rule-gated on the count of de-escalation items received (the `calculate_number_of_pact_items` analog). Fill therefore guarantees you receive enough difficulty-down to make the goal reachable before it expects you to clear it.
- **Floor presets:** Easy/Normal/Hard presets set the starting scaling amounts (how many down-items exist per axis = how over-scaled you start) plus filler/helper generosity. This makes "how brutal is the opening wall" an explicit, tunable knob rather than something to nail blind. The opening is *supposed* to feel rough; the presets decide how rough.

## 8. Runtime client architecture

Do **not** copy Polycosmos's transport. It uses a Lua + StyxScribe + Python bridge only because Hades cannot load DLLs. Nightreign is a native FromSoft game you already mod via ME3, so use a native runtime client in the style of the ER AP client, loaded through the existing `me3_profile.py` setup. Copy the *module split*, not the plumbing:

- **Event manager:** detects check conditions (pickup intercepted, objective/boss flag set, run start/end) and reports checks to the AP server.
- **Scaling manager:** holds the current per-axis de-escalation level from received items and applies it to the next run via NpcParam/EMEVD overrides (reuse `emit_hp_overrides` and friends).
- **Item manager:** grants filler, currency, and unlock items.
- **Messages:** native-style on-screen notifications (reuse what the ER client already does).

Generation note: like Hades, Nightreign AP will generate locally first (no website support initially); ship a Template.yaml.

## 9. Options sketch (apworld)

- `location_system`: interception | score (+ `check_count`).
- Per-axis amounts: `enemy_hp_amount`, `enemy_damage_amount`, `enemy_density_amount`, `timer_amount`, ... (each 0..N).
- Sanity toggles: `nightlordsanity`, `nightfarersanity`, `fieldbosssanity`, `relicsanity`.
- Goal: `nightlord_defeats_needed`, `distinct_nightlords_needed`, `distinct_nightfarers_needed`.
- Filler: per-currency value + percentage; `helper_percentage`; `trap_percentage`.
- `deathlink` (+ amnesty), `co_op_mode` (default off / single-player first).
- Presets: Easy / Normal / Hard (set starting axis amounts + filler generosity).

## 10. Build phases

1. **apworld skeleton** — copy the Polycosmos structure: location-count tables + reverse-scaling item pool + back-fill filler + composable goal + `fill_slot_data`. Gen-test it produces winnable seeds with stub logic.
2. **Native runtime client** — port the ER AP client: connect, send checks, receive/grant items, native notifications, through ME3.
3. **Scaling manager** — wire each axis to NpcParam/EMEVD overrides driven by received-item counts; start at max, step down; apply on next run. Reuse `emit_hp_overrides.py` etc.
4. **Location detection** — implement the chosen spine (pickup interception first) plus milestone flags (Nightlord/boss/Nightfarer).
5. **Tuning pass** — Easy/Normal/Hard presets; playtest the floor and the de-escalation granularity (the make-or-break for feel).
6. **Community** — link into the FromSoft AP community (fswap / AP Discord) and the Hades thread (NaixGames is open to people adapting the approach) EARLY, not after building solo.

## 11. Open questions / decisions

- **Spine:** interception vs score for v1. (Leaning interception.)
- **Axis set for v1:** which of the seven axes ship first. (Leaning HP + damage + density + timer.)
- **Mid-run vs next-run application:** confirm Nightreign bakes scaling per load (almost certainly yes); design assumes next-run.
- **Co-op:** how a 3-player session maps to per-slot AP. Punt to single-player-first behind a flag.
- **Goal scope:** single assigned Nightlord vs all-8 marathon as the default shipping mode.
- **Relic persistence interaction:** Nightreign's own relic meta-progression overlapping with AP-granted power; decide whether relics are randomized, suppressed, or left vanilla in v1.

---

*References: NaixGames/Polycosmos (hades/__init__.py, Locations.py, Options.py) for the fill/region/goal/slot_data pattern. nightreign-enemy-rando toolchain (emit_hp_overrides.py, npcparam_reward_fill.py, mob_drop_fill.py, drop_tiers.py, emevd_patch.py, dev/msb_authoring.py, me3_profile.py) for the scaling hooks.*
