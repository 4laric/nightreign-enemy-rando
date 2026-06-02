# v0.28.x: Field-boss / Night-boss tier separation

## Motivation

The night_boss tier was historically overloaded. It carried two
conceptually distinct chr classes:

  1. **True arena bosses** — the Day-3 climactic encounters that spawn
     in dedicated NB arenas with wake-handshake EMEVD scripting:
     Margit, Maliketh, Malenia, Godfrey, Rellana, Mohg, Bayle,
     Promised Consort Radahn, Crucible Knight, etc.

  2. **Open-world boss-fight encounters** — chrs you find walking
     around the map, with a fixed location but no arena gating:
     Tree Sentinel, Tibia Mariner, Magma Wyrm, Borealis, Death Bird,
     Ulcerated Tree Spirit, Putrescent Knight, Furnace Golem,
     Hippopotamus Golden Wings, Ancient Dragon, Fallingstar Beast,
     Dragonkin Soldier (Ice Lightning), Demi-Human Queen, etc.

Sharing one tier label meant the picker couldn't distinguish between
"this slot should host a climactic arena boss" and "this slot should
host an overworld field boss." A Tibia Mariner showing up in Margit's
spot is jarring; same problem in reverse.

## Resolution

### Data: 24 chrs demoted night_boss → field_boss

Demotion criterion: `expects_boss_arena=False` in the chr's tag.

Demoted list (24 chrs):
- c3100 Elemer of the Briar *(flagged for review)*
- c3250 Draconic Tree Sentinel
- c3251 Tree Sentinel
- c3570 Godskin Noble *(flagged for review)*
- c4130 Demi-Human Queen *(flagged for review)*
- c4503 Borealis the Freezing Fog
- c4510 Ancient Dragon
- c4580 Giant Wormface
- c4640 Ulcerated Tree Spirit
- c4650 Dragonkin Soldier (Ice Lightning)
- c4680 Full-Grown Fallingstar Beast
- c4911 Great Wyrm Theodorix
- c4950 Tibia Mariner
- c4980 Death Bird
- c5011 Golden Hippopotamus (Golden Wings)
- c5020 Putrescent Knight
- c5170 Furnace Golem
- c52309 Priestess (Duchess)
- c52312 Witch of the Wheel
- c52313 Executor?
- c5810 Demi-Human Swordmaster Onze
- c6251 Tree Sentinel (SoTE)
- c7931 c7931
- c7932 c7932

Three chrs carry a `_review_note` in their tags marking them for
playtest review (c3100 Elemer, c4130 Demi-Human Queen, c3570 Godskin
Noble) — they're arguably arena-class encounters in vanilla ER, but
their `expects_boss_arena` tag is False. If playtest shows them
under-tiered, promote back to night_boss.

### Tier distribution after demotion

| tier | count | change |
| --- | --- | --- |
| grunt | 189 | (unchanged) |
| miniboss | 107 | (unchanged) |
| night_boss | 42 | -24 |
| field_boss | 32 | +24 |
| cinematic | 41 | (unchanged) |
| nightlord | 17 | (unchanged) |
| non_combat | 10 | (unchanged) |
| mount_component | 6 | (unchanged) |

### Engine: new tier-roll constants

```python
V3_FIELD_UPGRADE_MINIBOSS_PCT          = 0.015   # unchanged
V3_FIELD_UPGRADE_FIELDBOSS_PCT         = 0.005   # NEW
V3_FIELD_UPGRADE_NIGHTBOSS_PCT         = 0.002   # unchanged
V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT  = 0.0     # NEW
```

#### Probability model

Each non-catalogued field slot rolls once over a unit interval split
into 4 cumulative buckets (layout `[NB | MB | FB | grunt]`):

```
[0,                                NB)              → night_boss
[NB,                               NB + MB)         → miniboss
[NB + MB,                          NB + MB + FB)    → field_boss (possibly promoted)
[NB + MB + FB,                     1)               → grunt
```

When the field_boss bucket is hit, a second roll (keyed off a distinct
`fbpromote` hash namespace) consults `V3_FIELDBOSS_TO_NIGHTBOSS_
PROMOTE_PCT` — if it passes, the result upgrades to `night_boss`. This
is the "rare moment when a field encounter turns out to be a real
fight" knob:

- **promote=0.0** (default): field_boss and night_boss tiers are fully
  independent. A field_boss roll always picks from the field_boss-tier
  pool.
- **promote=0.05–0.20**: occasional scary encounters.
- **promote=0.5+**: field bosses feel as menacing as night bosses.
- **promote=1.0**: collapses field_boss back into night_boss (every
  field_boss roll becomes a night_boss roll).

#### Why the `[NB | MB | FB | grunt]` order?

Putting `field_boss` just before `grunt` in the roll layout means
that BUMPING `V3_FIELD_UPGRADE_FIELDBOSS_PCT` only steals from grunt
territory — it never reclassifies an already-rolled NB or MB outcome.
This makes the "make field encounters more common" knob safe to tune
without disturbing the boss-tier rates.

### Engine: fallback ladder

`field_roll_tier_for()` now returns one of
`grunt | miniboss | field_boss | night_boss`. The fallback ladder in
`pick_target_cp` extended:

```python
_ladder = {'night_boss': ('night_boss', 'miniboss', 'grunt'),
           'field_boss': ('field_boss', 'miniboss', 'grunt'),
           'miniboss':   ('miniboss', 'grunt'),
           'grunt':      ('grunt',)}[_field_roll_tier]
```

A `field_boss` roll never falls UP to night_boss — the conditional
promote is handled in `field_roll_tier_for` itself, so by the time
the fallback ladder sees `'field_boss'` the dice are settled.

### getSoul tier floors

Re-derived from placement-weighted vanilla medians:

| tier | v0.27.13 | v0.28.x |
| --- | --- | --- |
| nightlord | 4375 | 4375 |
| **night_boss** | **3750** | **2910** |
| **field_boss** | **1605** | **4687** |
| miniboss | 450 | 450 |
| grunt | 100 | 100 |

Interesting outcome: post-separation, field_boss has a HIGHER median
than night_boss. This is because the demoted overworld bosses (Tree
Sentinel, Fallingstar Beast, etc.) have high rune values, while the
remaining night_boss tier is anchored by c2500 Crucible Knight (17
placements at rep=2910). The medians honestly reflect what those
specific encounters pay in vanilla.

### Tests

- **`test_field_boss_tier_active`** (renamed from
  `test_field_boss_tier_eliminated`, inverted)
- **`TestFieldRollTierWithFieldBoss`** (new class, 5 tests):
  - `test_four_outcomes_reachable_at_defaults`
  - `test_promote_zero_field_boss_stays_field_boss`
  - `test_promote_one_all_field_boss_becomes_night_boss`
  - `test_roll_is_deterministic_per_slot`
  - `test_promote_draw_independent_of_primary_roll`
- **Updated**: `test_c4130_expects_boss_arena_is_false` and
  `test_c3100_and_c5810_same_quirk` accept tier ∈ {night_boss,
  field_boss} — invariant is the arena-flag quirk, not the tier label.

### Files touched

| file | change |
| --- | --- |
| `oops_v3.py` | added 2 constants, rewrote `field_roll_tier_for`, extended fallback ladder, updated `V3_GETSOUL_TIER_FLOORS` |
| `data/nr_enemy_tags.json` | 24 chrs tier `night_boss → field_boss`, 3 carry `_review_note` |
| `data/placement_budget.json` | regenerated |
| `data/npcparam_getsoul_overrides.csv` | regenerated |
| `dev/sim_per_run.py` | added `field_boss` to tier-bucketing logic |
| `tests/test_pick_target.py` | renamed/inverted one test, updated two, added 5 new tests |
| `dev/audit_placement_budget_consistency.py` | added c6200 to allowlist (separate v0.28.x MMV change) |

### Net test count

| | before | after |
| --- | --- | --- |
| Pre-existing pass | 1370 | 1370 |
| Fixed by v0.28.x | 0 | +2 |
| Added by v0.28.x | 0 | +5 |
| **Total passing** | **1370** | **1372** |
| Pre-existing fail | 24 | 21 |
| Regressions | 0 | 0 |

(GUI/tkinter test files excluded — environment doesn't have tkinter.)
