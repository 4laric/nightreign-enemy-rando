# CTD Report Template

**Purpose.** When a CTD or quality issue is reported (in-game freeze, idle
chr, frozen pose, softlock, sunken model, missing aggro, etc.), every
investigation answers the same structured questions before any patch
goes in. This template is what enforces that — copy it, fill it out,
then write the patch.

**Workflow.**

1. Copy this file to `dev/ctd_reports/YYYY-MM-DD_<slug>.md`
2. Fill in sections 1-6 from the spoiler, screenshot, and validator output
3. Make the decision in section 7 — **especially the anti-pattern check**
4. Write the patch only AFTER section 7 is filled
5. Confirm via section 8 once playtested
6. Leave the filled report in `dev/ctd_reports/` as the audit trail

**Why this exists.** Per the systematic-stability reframe (see
`CHANGELOG.md` v0.24.86 and the validator at `dev/validate_placements.py`):
every previous wave of stability work patched CTDs by adding the
problematic slot to `V3_PROBLEM_SLOTS` with a per-slot rationale comment.
This is reactive: each CTD that fits the same family pattern requires
its own slot entry, with no generalization. The new discipline forces
the investigator to first ask "which structural axis explains this?" so
fixes scale to the whole family instead of one slot.

**Anti-pattern guardrail.** The discipline is: a CTD becomes a
`V3_PROBLEM_SLOTS` entry ONLY when section 5 confirms no existing axis
explains it AND section 7's "define new axis" cost is too high to pay
right now. Adding a slot to `V3_PROBLEM_SLOTS` without that confirmation
is the failure mode this template prevents.

---

# CTD Report: <one-line slug — e.g. "centipede_demon_fort_rampart_v0_24_77">

## 1. Quick reference

**Filed:** YYYY-MM-DD
**Engine fingerprint at time of CTD:** v0.XX.YY
**Reporter:** <Alaric / playtest source>
**Seed:** <int>
**Status:** open | patched-pending-validation | resolved | wontfix
**Sibling reports:** <links to dev/ctd_reports/... if part of a family>

One-sentence symptom: <e.g. "Player CTD on leaving Fort after stable Day 1
exploration. Suspected chr: c4810 Erdtree Avatar at m30_30 pi=45.">

---

## 2. Symptom classification

Different symptoms point at different root-cause families. Tick exactly
one of these (add a new bullet if none fit — that itself is signal):

- [ ] **Hard CTD on cell load** (engine resource issue — chr asset
      bundle missing, anim bank mismatch, navmesh budget overflow)
- [ ] **Hard CTD on chr aggro** (animation/state transition — the
      chr's behavior tree tries to play a transition it can't satisfy)
- [ ] **Hard CTD on chr intro** (scripted-intro / cinematic failure —
      EMEVD trigger fires, animation expects environment that isn't
      there)
- [ ] **Hard CTD on player approach** (proximity event, trigger volume,
      asset preload from `SmallBaseAttached` or similar)
- [ ] **Hard CTD on chr kill / boss-clear** (EMEVD boss-clear chain
      expects clean teardown — child entity spawner, missing reward
      AwardItemLot, etc. See v0.24.67 Gate 5.5.)
- [ ] **Softlock during boss intro** (cinematic stalls waiting for an
      animation "complete" signal the substitute chr can't emit. See
      v0.23.05.2 anim_class compat gate.)
- [ ] **Frozen pose / idle** (chr loaded fine, model renders, but
      aggro-state transition never fires — usually scripted-intro
      gap. See `dev/WONTFIX.md` "NB-tier chr idle at Crater/shifting-
      earth Cathedral slots".)
- [ ] **Idle roar / docile** (heritage chr stands still and bellows
      instead of engaging. Aggro-trigger volume gap.)
- [ ] **Sunken model / model clip** (XXL chr at small-vanilla slot —
      see v0.24.55 Gate 7 xxl_at_small_slot.)
- [ ] **Spawn freeze at spawn-time pathfinding** (quadruped at
      sparse-navmesh slot — see v0.24.31 Gate 4 quadruped_unsafe_slot.)
- [ ] **Other** — describe and propose a new symptom family:

---

## 3. Placement context

From the spoiler entry that contains the offending placement:

```
MSB:                 <m??_??_??_??.msb>
Part index (pi):     <int>
Position:            [<x>, <y>, <z>]
Vanilla source cp:   <cXXXX>
Vanilla source name: <variant_name>
Vanilla npc_param:   <int>
Substituted cp:      <cXXXX>
Substituted name:    <variant_name>
Substituted npc_param: <int>
entity_id:           <int>
is_boss:             <true/false>
catalog_tier:        <named_boss/fieldboss/grunt/etc.>
catalog_scope:       <broad/extended/narrow>
```

**Named location** (from `data/nr_named_locations.json` or
`data/nr_starting_encampments.json` if applicable):

- Location slug: <e.g. `digger_tunnel_lake`>
- Category: <e.g. `tunnel`>
- Past CTD history at this location: <count + dates>

**Spoiler path:** `spoilers/<filename>.json`

**Screenshot / video evidence:** <paste filename or link>

---

## 4. Validator lookup

Before forming a hypothesis, check what the validator says about this
placement. Run:

```
python dev/validate_placements.py spoilers/<filename>.json --filter SUSPICIOUS
python dev/validate_placements.py spoilers/<filename>.json --filter WOULD_REJECT
```

Then grep the manifest for the (msb, pi) pair:

```
python dev/validate_placements.py spoilers/<filename>.json --manifest - \
  | jq '.[] | select(.msb=="<msb>" and .pi==<pi>)'
```

Record the verdict here:

- **Validator status:** CLEAN / RELEASED / SUSPICIOUS / WOULD_REJECT
- **Gates fired:** <list of gate names + released_by>
- **Suspicious tags:** <list>

**Interpretation:**

- **WOULD_REJECT** — validator caught it but the picker leaked through.
  This is a picker-side bug (the gate isn't firing at swap time when it
  should). Investigate the picker bypass, not the gate model. Common
  culprits: unique-reservation early-return at `pick_target_cp:9741`,
  OOPS_ALL_NB intercept at `shuffle_msb_v3`, hub-map passthrough.
- **RELEASED** — validator flagged it, but a release mechanism let it
  through. The release may be wrong. Check the `released_by` field
  against the actual failure: e.g. if `released_by=problem_slot_extra_
  allows` and the failure happened anyway, the EXTRA_ALLOWS entry is
  too permissive.
- **SUSPICIOUS** — validator surfaced a watch-list pattern but didn't
  reject. Often the right answer is "add this specific (chr, slot) or
  family to one of the gates so future seeds catch it preemptively."
- **CLEAN** — validator saw no gate signal. This is the most important
  case: there is a fragility axis the validator (and therefore the
  engine) doesn't model yet. Section 5 must identify the missing axis.

---

## 5. Axis attribution — which existing axis should have caught this?

For each axis below, write either "applies" with a one-line explanation,
"doesn't apply" with the reason, or "applies but classifier incomplete"
if the axis exists but the chr/slot isn't classified yet.

The point of this section: if any axis "applies but classifier
incomplete" → the fix is a one-line data file edit, not a code change.
If everything is "doesn't apply" → section 6 has to propose a new axis.

### Entrance animation (chr-side: `data/entrance_animations.json`, slot-side: `data/nr_no_emerge_slots.json`)

Gate: `no_emerge_terrain`. The chr has an entrance-anim classification
(emerge_from_ground / fly_in / scripted_intro / pre_placed / walk_in /
unknown) and the slot has or lacks the geometric affordance for it.

- Substituted chr's classification: <emerge_from_ground / unknown / ...>
- Slot in `V3_NO_EMERGE_SLOTS`: <yes / no>
- Verdict: <applies and gate should have caught it (picker bug) / classifier incomplete (chr missing) / doesn't apply>

### Quadruped / navmesh footprint (chr-side: anim_class+locomotion; slot-side: `data/nr_quadruped_unsafe_slots.json`)

Gate: `quadruped_unsafe_slot`. Quadrupeds and quadruped_large chrs
sample a wider footprint at spawn-time pathfinding than bipeds — slots
that are biped-safe can be quadruped-unsafe.

- Substituted chr's anim_class / locomotion: <values>
- Slot in `V3_QUADRUPED_UNSAFE_SLOTS`: <yes / no / yes-but-released-by-reposition>
- Verdict:

### Flying required (chr-side: anim_class=flying_dragon; slot-side: `data/nr_flying_required_slots.json`)

Gate: `flying_required_slot`. Slots designed for flying_dragon vanilla
chrs need flying targets. Non-flying chrs at aerial slots CTD on cell
load.

- Slot in `V3_FLYING_REQUIRED_SLOTS`: <yes / no>
- Substituted chr's anim_class: <value>
- Verdict:

### Scripted-intro dependence (chr-side: `data/scripted_intro_chrs.json` — **Track B done as of v0.24.86, but small and empirical**; slot-side: `data/nr_boss_slots.json` schema v2 + `data/scripted_intro_slots.json` — **Track C done as of v0.24.85+**)

Gate: *not yet wired into `_reject_target_for_slot` as of v0.24.86;
slot-side data lives in `nr_boss_slots.json` per-entry `intro_anchored:
bool`. Chr-side data lives in `scripted_intro_chrs.json` with two
classes: `scripted_intro_required` (chr freezes at non-anchored slots
because it expects an intro) and `scripted_intro_intolerant` (chr
freezes at anchored slots because an unwanted intro fires). Validator
fires `scripted_intro_required_at_non_anchored` and
`scripted_intro_intolerant_at_anchored` suspicions as high-precision
signals; NB_CALIBER proxy is the lower-precision fallback for chrs
not yet in the JSON.*

**Methodology note.** Behbnd-template-hash classification — the
v0.24.82 approach that expanded `entrance_animations.json` from 4
seeds to 25 chrs in one pass — DID NOT REPLICATE for this failure
mode. The behavior tree at `Behaviors/{cp}.hkx` is intrinsic
state-machine logic; scripted-intro dependence lives one layer
further out (NpcParam ThinkID / NpcThinkParam / per-chr EMEVD wiring).
Template 472b076cb7 contains both c4355 (freezes at non-anchored)
and c4351/c4354/c4356 (which don't), so template membership isn't a
sufficient signature. The classifier stays small and grows
empirically; promotion candidates use the "exact display-name match
within shared template" heuristic that promoted c5750 in v0.24.85.

If the symptom looks like "frozen pose / NB chr at non-NB slot" /
"idle in combat pose" / "boss-shaped geometry but no fog wall fired",
this is almost certainly the relevant axis.

- Slot in `V3_BOSS_SLOT_CATALOG` with `intro_anchored=False`:
  *(check the catalog entry)*
- Target chr in `scripted_intro_chrs.json` as
  `scripted_intro_required`:
- Target chr in `scripted_intro_chrs.json` as
  `scripted_intro_intolerant`:
- Target chr in NB_CALIBER (proxy, lower precision):
- Verdict:

### Wakeup-dormant (chr-side: `data/wakeup_chrs.json` — **Track B side-discovery, v0.24.86; AXIS AUDIT-CLOSED v0.24.86-late**)

**Status: closed for vanilla content.** Empirical audit recorded in
`wakeup_chrs.json` _meta.empirical_audit_v0_24_86 scanned all 300
vanilla NR MSBs and 194 per-map EMEVD files; found 103/103 vanilla
wakeup-chr placements covered by existing patches (6 via the v0.24.86
`permissive_boss_wake` allowlist, 97 via the chr-agnostic spawn
handlers covered by `permissive_spawn_emerge`, 0 cinematic-only). No
slot-side data file (`nr_no_wake_slots.json`) was warranted; not
built.

If the symptom is "chr loaded into a dormant pose (kneeling, sitting,
half-buried) and never wakes" AND the chr is in `wakeup_chrs.json`,
this CTD is evidence the audit missed a case. Reopen with care:

- Target chr in `wakeup_chrs.json` as `wakeup_dormant`:
- The slot's wake handshake (from per-map EMEVD): does it dispatch
  through one of the 8 `permissive_boss_wake` allowlisted events
  (90015000/7/21/23/26/30/31/406), one of the spawn handlers
  (90085XXX/90035XXX) covered by `permissive_spawn_emerge`, or one
  of the orchestrators (90075351/352) with explicit EnableCharacterAI?
  If none of those, this is a genuinely new case — open
  `nr_no_wake_slots.json` with this slot as seed 1 and re-evaluate
  the gate proposal in `wakeup_chrs.json`.
- Verdict: *(should be "doesn't apply" unless a genuine audit gap)*

### Boss-bar tier / boss-reward EMEVD

Gate: `grunt_trash_at_boss_bar` (v0.24.67 Gate 5.5). Grunt/trash-tier
chrs at boss-healthbar slots crash the EMEVD boss-clear chain on kill.

- Slot's `catalog_tier` (V3_BOSS_BAR_TIERS membership):
- Substituted chr's tier (V3_BOSS_BAR_GATED_TIERS):
- Substituted chr in V3_FRAGILE_SAFE_CONFIRMED (exemption):
- Verdict:

### Size class drift (chr-side: tags `size_class`; slot-side: vanilla source `size_class`)

Gates: `xxl_giga_size_drift` (v0.24.68), `xxl_at_small_slot` (v0.24.55).

- Source size_class:
- Target size_class:
- Verdict:

### Source-anim forbidden (chr-side: anim_class; slot-side: derived from source anim_class)

Gate: `forbidden_source_anim` (v0.24.18 / v0.24.24).

- Source anim_class in `V3_FORBIDDEN_BY_SOURCE_ANIM`:
- Target anim_class in the forbidden set for that source:
- Verdict:

### Script-spawn boss off-arena

Gate: `script_spawn_boss_at_overworld` (v0.24.51 / v0.24.52). Targets
the script-spawn boss family at m60_xx_xx overworld tiles.

- Target's `_source == 'script_spawn'` and tier in
  V3_SCRIPT_SPAWN_BOSS_GATED_TIERS:
- MSB is m60_xx:
- Verdict:

### Fragile map / fragile slot

Gate: `fragile_slot_filter`. Maps/slots that need RESILIENT∪SAFE_CONFIRMED.

- MSB in V3_FRAGILE_MAPS or any V3_FRAGILE_MAP_PREFIXES match:
- Source variant_name contains any V3_FRAGILE_SOURCE_QUALIFIERS marker:
- Slot at edge-sentinel position pattern:
- Slot in V3_PROBLEM_SLOTS (current manual blocklist):
- Verdict:

### Other axes / new axis

If none of the above explain the failure mode, this CTD reveals a new
axis. Describe what chr property and what slot property the new axis
would track, and how each could be derived from binary data
(behbnd template hash, EMEVD scan, MSB navmesh extraction, NpcParam
field, etc.) so the axis can be expanded beyond the single CTD seed.

- Proposed chr-side property:
- Proposed slot-side property:
- Derivation source:
- Other CTDs that retroactively fit this axis:

---

## 6. Hypothesis

Based on section 5, what is the most likely root cause? One paragraph.
Reference the specific gate / classifier / picker line that should have
caught this, OR identify the new axis that's missing.

<paragraph>

---

## 7. Decision

**Anti-pattern check before deciding.** Re-read the WONTFIX criteria
in `dev/WONTFIX.md` and re-read the validator's interpretation of the
problem-slot mechanism. **STOP** before choosing "add to V3_PROBLEM_SLOTS"
and confirm all three are true:

- [ ] The CTD is NOT explained by any existing axis in section 5 (no
      "applies but classifier incomplete" verdict was reached)
- [ ] There is no behbnd template hash, EMEVD signature, MSB property,
      or NpcParam field that would generalize the fix — i.e., adding
      this slot alone really does prevent the failure family at all
      similar slots (which is rarely true)
- [ ] The next 5 chrs that could organically land at this slot would
      ALSO need this slot's V3_PROBLEM_SLOTS protection — i.e., it's
      truly slot-specific, not chr-specific

If any of those is false, the right fix is one of the first four
options below, NOT `V3_PROBLEM_SLOTS`.

Pick exactly one decision:

- [ ] **Expand chr classification on existing axis**
      *Fix:* add chr to `data/<axis>.json` (e.g. add `c4810` to
      `entrance_animations.json` as `emerge_from_ground`).
      *Generalizes:* this chr at all similar slots, future seeds. Best
      outcome.
- [ ] **Expand slot classification on existing axis**
      *Fix:* add `(msb, pi)` to the slot-side data file (e.g. add
      `m30_30:45` to `nr_no_emerge_slots.json`).
      *Generalizes:* all chrs with the relevant classification at this
      slot, future seeds.
- [ ] **Define new axis**
      *Justification:* section 5 confirms no existing axis applies AND
      section 6's hypothesis describes a recurring failure mode (not a
      one-off).
      *Cost:* new chr classifier, new slot classifier, new gate in
      `_reject_target_for_slot`. ~1 day of work. Worth it ONLY if the
      new axis explains >3 prior CTDs retroactively (note them).
- [ ] **Fix gate bypass (picker bug)**
      *Justification:* validator said WOULD_REJECT — the gate model is
      correct; the picker is leaking past it.
      *Common bypasses:* unique-reservation early-return at
      `pick_target_cp:~9741`; OOPS_ALL_NB intercept; hub-map
      passthrough; chaos-mode lift; empty-pool fallback.
      *Fix:* the gate has to fire in the bypass path too. See the
      v0.24.27 consolidation pattern (`_reject_target_for_slot`).
- [ ] **V3_PROBLEM_SLOTS quarantine** — last resort
      *Required:* explicit note here describing the classifier work
      that's owed once data permits. The quarantine is temporary.

**Decision rationale:** <paragraph>

---

## 8. Action items

Concrete patch list. Each item links to the file + line where the change
goes, or names the data file to update.

- [ ] <file:line — change description>
- [ ] <data/foo.json — entry to add>
- [ ] Test: <how the unit test will catch the regression>
- [ ] CHANGELOG.md entry under next version
- [ ] If this CTD belongs to a family with other reports in
      `dev/ctd_reports/`, link them and consider promoting the family
      to a new axis if you didn't already

---

## 9. Validation plan

How will the fix be confirmed?

- **Pre-fix baseline:** run the original seed, confirm the CTD
  reproduces. (If it doesn't, this CTD is non-deterministic and the
  axis attribution above may be wrong — re-investigate.)
- **Post-fix seed:** <seed N — run again, expected behavior at
  `(msb, pi)`>.
- **Validator regression check:** the placement should now classify as
  CLEAN or RELEASED (with a documented release). If it's still
  WOULD_REJECT, the fix didn't actually thread the gate.
- **Family playtest:** if section 5 produced a chr-family or slot-family
  expansion, run 5+ seeds and confirm the family no longer surfaces
  WOULD_REJECT.

---

## 10. Follow-ups

Anything that's NOT this patch but emerged from the investigation:

- New axis ideas, broader refactor opportunities
- WONTFIX entries to revise
- Tooling gaps (validator missed it, behbnd corpus needs expanding,
  etc.)
- Other slots/chrs to playtest preemptively

---

*Template version: v0.24.86 (initial). Per the systematic-stability
plan in `CHANGELOG.md`.*
