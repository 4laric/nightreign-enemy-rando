# v0.23.07 — Test Plan

The naive approach — "play full Expeditions and note what shows up" —
has a bad sample-rate problem. One Expedition visits **2 of 22** Night
Boss arenas (one Night 1, one Night 2). With ~15 minutes per run, full
22-arena coverage takes a minimum of 11 runs and realistically 20+ to
account for matchmaker repeats. That's 5+ hours of play to get one
confidence cycle.

This plan replaces playtesting-as-coverage with **spoiler-based
offline coverage** + **playtesting-as-confirmation**. The spoiler
already records exactly which c-prefix lands at every NB arena slot
across 300 MSBs in 5–7 seconds. We verify the *placement* layer
exhaustively offline and use playtesting to confirm the
*encounter-runs-to-completion* layer at a small sample.

The split:

- Offline (deterministic, exhaustive): does the engine pick caliber
  targets at NB arenas? Does it respect uniqueness caps? Heritage
  leaks? Cap-compatible cluster picks?
- In-game (high-cost, low-bandwidth): do the chosen targets actually
  *fight* properly when the encounter loads? Specifically — do
  multi-bar arenas zero out, do scripted intros play, do summons
  spawn?

### Phase 1 — offline coverage (no playtest needed)

Three checks run via `dev/v0_23_07_audit.py` (to be added) over a
seed sweep. 5 seeds confirms determinism; 50+ seeds gives an
empirical distribution.

#### 1a. NB-caliber gate audit

For each seed, enumerate the 22 NB arenas. At every slot whose
source variant carries a `'(Night Boss'` marker, check that the
placement c-prefix is in `V3_NIGHT_BOSS_CALIBER_TARGETS`. Expected:
zero violations.

The 22 arenas (entity_id-sorted):

```
m47_70  Tibia Mariner
m48_40  Morgott
m48_50  Draconic Tree Sentinel
m48_60  Tree Sentinel
m48_70  Godskin Apostle solo
m48_80  Godskin Duo
m48_90  Large Wormface
m49_10  Grafted Monarch
m49_17  Valiant Gargoyle
m49_18  Great Wyrm Theodorix
m49_19  Ancient Dragon
m49_20  Fallingstar Beast
m49_21  Death Rite Bird
m49_23  Dragonkin Soldier
m49_24  Bell Bearing Hunter
m49_25  Crucible Knight + Hippopotamus
m49_26  Outland Commander
m49_27  Battlefield Commander
m49_28  Night's Cavalry x2 (mounted)
m49_29  Demi-Human Queen + Swordmaster
m49_30  Royal Revenant
m49_90  Ulcerated Tree Spirit
```

A violation = a non-caliber c-prefix landed at one of these slots.
Failure modes already known:

- Reservation pre-pass put a non-caliber capped chr there
  (gate added v0.23.07 in `_score_slot_for_unique`)
- BIG_PROXIMITY post-pass demoted a caliber pick to a non-caliber
  small chr (gate added v0.23.07 in the demotion `_pool` filter)
- Cluster path bypassed the runtime gate (would need
  `slot_variant_name` plumbing if found)

Passing v0.23.07 ship: 0 violations across 5 seeds × mp_safe ON/OFF.

#### 1b. Uniqueness cap audit

For each seed, count placements per c-prefix. Compare to
`V3_UNIQUE_TARGET_CAPS`. Any cp where `count > cap` is a violation.

Expected: zero violations. Typical placement distributions for
capped chrs sit at exactly the cap or below.

Also tracks **unplaced reservations** — the spoiler header's
`unique_unplaced` field lists capped chrs that didn't get a
reservation slot. Some unplaced is normal (engine source-skip
rules); 5–7 per run is baseline. >15 per run would indicate the
reservation pre-pass is failing to find quality slots.

#### 1c. Heritage leak audit

For each seed run with `multiplayer_safe=True`, every placement
c-prefix should be in vanilla NR's MSB Models (the 232 c-prefixes
that ship with base NR). Any leak means a heritage chr that the
coop client doesn't have made it past the mp_safe filter.

Expected: 0 leaks. Known historical hot path was the
merchant_model_swap path (uses V3_MERCHANT_MODEL_POOL which still
has 7 heritage entries — workaround: turn off merchant model swap
in mp_safe coop). Audit catches this.

#### 1d. Multi-entity arena diversity

For the 6 multi-entity arenas (m48_50, m48_60, m48_70+m48_80,
m49_25, m49_28, m49_29), check that the boss-slot placements at
each arena are **distinct c-prefixes**. Same-target-twice within
a multi-entity arena is the failure mode that motivated dropping
c2276 from the caliber pool. Any seed where two slots in the
same arena get the same c-prefix is a finding (not necessarily a
bug — could be a legitimate cap=2 reservation collision — but
worth surfacing).

#### 1e. Performance regression

Time `cmd_shuffle_v3` per seed. v0.23.06 baseline was 5.4–6.6s.
v0.23.07 should be similar or slightly faster (DCX fast paths
help the full-pipeline path; in-engine-only this measure is
comparable). >8s/run for in-engine alone would indicate a
regression.

### Phase 2 — playtest confirmation (small sample)

Phase 1 confirms placement correctness. Phase 2 confirms
encounter functionality. The goal is to stress-test the
softlock-prone arenas — specifically:

#### 2a. The 3 unprotected multi-entity arenas

These are the highest-risk softlock candidates per the v0.23.06
audit:

- **m48_70 / m48_80 Godskin** — solo Apostle and Duo (Apostle +
  Noble). If duo coordination event keys on c3560+c3570 specifically
  and shuffle picks different c-prefixes, the second healthbar
  may not zero out.
- **m49_25 Crucible Knight + Golden Hippopotamus** — cross-species
  duo. Same death-event coordination concern.
- **m49_29 Demi-Human Queen + Swordmaster** — Queen summons
  Swordmaster mid-fight via scripted spawn. If spawn target is
  wrong c-prefix, summon SFX without a unit appearing.

**Goal: 1 successful clear at each arena.** Three Expeditions
biased to pull these arenas (matchmaker isn't directly
controllable, but seed selection + game time-of-day biases can
help). If any of the three softlock, surgical npc_param exclusion
is ready to ship per v0.23.06 analysis (35600010, 35700010,
25000020, 50110020, 41301010, 58100910).

#### 2b. The 4 solo-with-ads arenas

- **m47_70 Tibia Mariner** — boss has its own Torso part (c4960)
  + Death Rite Bird summon (c4980 npc=49801110)
- **m48_90 Large Wormface** — environmental ads only, low risk
- **m49_26 Outland Commander** — summons Exile Soldier ads mid-fight
- **m49_27 Battlefield Commander** — summons Exile Soldier ads
  mid-fight

**Goal: 1 successful clear at Tibia Mariner.** Mariner Torso is
the highest-risk solo-with-ads case because c4960 IS the boss's
body — if shuffled wrong, the boss's idle state breaks. The
others are lower priority.

#### 2c. Dragon arenas

- **m49_18 Great Wyrm Theodorix** (c4911 vanilla)
- **m49_19 Ancient Dragon** (c4510 vanilla)
- **m49_20 Fallingstar Beast** (c4680 vanilla)

These are now eligible to receive any of c4500/c4501/c4503/c4505/c4910
across runs (cap=1 each, so one dragon per run). Geometry concern:
c4503 Borealis has a mountain-peak descent intro that may not
fire properly at every dragon arena. **Goal: 1 successful clear
at each dragon arena to confirm no scripted-intro softlocks.**

#### 2d. Bell Bearing Hunter (the original problem case)

The starting motivation for v0.23.07's caliber pool was the
"BBH → Perfumer" complaint. **Goal: 1 BBH arena visit per run
showing a caliber chr.** Spoiler-confirm before the run (no
re-randomization needed mid-run; if the seed places a caliber
chr there, the visit confirms it).

### Phase 3 — when failures occur

If Phase 1 catches a placement violation: spoiler has full data
(seed + arena MSB + pi). Localized fix.

If Phase 2 catches an encounter softlock: capture the seed +
arena + which c-prefix landed. Three escalation paths:

- **Boss won't activate / scripted intro stalls** → anim_class
  scripted-intro fix already exists at line 4462 (v0.23.05.2);
  may need expansion.
- **Healthbar won't zero** → multi-entity arena event chain
  broken; surgical npc_param exclusion is the fix.
- **Boss spawns but uninteractable** → fragile-target rule;
  add c-prefix to V3_FRAGILE_SENSITIVE_TARGETS.

### Sample sizes

- Phase 1: **5 seeds × mp_safe ON/OFF** = 10 runs minimum, 50
  seeds for empirical confidence. Runs in ~30s total.
- Phase 2 (per-Nightlord): **8 Expeditions with one carefully-chosen
  seed**. ~2h total play time. Spoiler-confirmed in advance via
  `dev/predict_nightlord_runs.py`.

This is roughly **10x faster** than naive playtest-only coverage
(5+ hours for one cycle of randomly-rolled coverage vs ~2h here,
with placement-layer guarantees from Phase 1 and arena-coverage
guarantees from Phase 2).

### The "one seed × all Nightlords" approach

Each Nightlord Expedition draws from a small pool of N1 / N2 boss
arenas (typically 2–5 entries per night, per the PC Gamer table
in `data/nightlord_pools.json`). Across all 8 Expeditions, the
pools collectively cover ~20 of the 23 NB arena MSBs in a single
seed's shuffle — meaning **one seed is enough to test most of
the Night Boss arena coverage**.

Workflow:

1. Run a shuffle: `python3 oops_v3.py --seed N --output dir/`
2. Predict outcomes: `python3 dev/predict_nightlord_runs.py dir/_spoilers.json --skip-heritage`
3. Pick the Expedition you want to test next from the prediction output.
4. Play that Expedition. The tool tells you exactly which arena will
   land at N1 / N2 and what c-prefix to expect.
5. Confirm in-game that the encounter runs to completion.

The 3 unreachable arenas (m48_70 Godskin solo, m49_30 Royal
Revenant, m49_90 Ulcerated Tree Spirit) appear to be invasion-event
exclusive encounters per the PC Gamer note on Gnoster/Maris/Libra
having special cross-pool invasions. Coverage of these requires
triggering those invasions, which is matchmaker-driven.

### Tooling shipped

- `dev/v0_23_07_audit.py` — Phase 1 audit; 30s for 5 seeds.
- `dev/predict_nightlord_runs.py` — Phase 2 predictor; reads a
  spoiler and tells you what each Expedition will roll.
- `data/nightlord_pools.json` — per-Expedition arena pools. Edit
  this to add heritage entries (e.g., Centipede Demon's MSB once
  the chr is imported via thefifthmatt or ER→NR param tooling).

