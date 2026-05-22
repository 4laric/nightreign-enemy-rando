# Mount/rider feature — cut 2 investigation findings

Read-only investigation done 2026-05-22, after shipping cut 1 (v0.26.15).
Goal: establish what cut 2 (the coordinated swap) actually requires, so it
can be implemented from evidence rather than a guess. No code changed by
this investigation.

## TL;DR

- The design fork from the cut-1 handoff ("embrace the visual mount" vs.
  "randomize the mount too") is **resolved: only the embrace path is
  viable.** The engine cannot randomize the mount a rider visually rides
  — see "The visual-mount mechanism" below.
- Cut 2 is therefore well-defined and fairly small: re-enable the
  `_collapse_rider_mount_pairs` mechanism scoped to the Kaiden pilot
  pair, lift one source-exclude skip, and gate the rider pick. Precise
  hooks are listed in "Cut-2 implementation plan".
- One genuine unknown remains — the exact attachment mechanism of the
  visual mount — but it does **not block** the embrace-path build; it
  only affects whether the result looks good, which is a playtest call.

## What cut 1 shipped (recap)

`mount_rider_swap` toggle (GUI diagnostic section, default OFF; also
`--mount-rider-swap`). When on, `_detect_mount_rider_slots()` finds
mount/rider Part pairs and logs `MOUNT_RIDER_DETECT` to the spoiler
trace. `V3_MOUNT_CLASS_POOL` and `V3_MOUNT_RIDER_PILOT_PAIRS` defined.
No swap behaviour — audit only.

## The mount/rider Part structure

A vanilla mounted enemy is **two MSB Parts**: a rider (e.g. c4050 Kaiden
Sellsword) and a mount (c4060 Kaiden's Horse), authored at near-identical
positions (`_collapse_rider_mount_pairs` docstring: 0.00u apart for 11 of
16 vanilla pairs, <=1.78u for the rest). Both currently sit in
`V3_EXCLUDE_SOURCE_PREFIXES`, so both slots stay vanilla today.

The disabled `_collapse_rider_mount_pairs` (v0.23.04, shelved v0.24.101)
encodes the intended swap model: **zero the mount Part's npc_param**
(`struct.pack_into('<I', data, mount_po + PART_OFF_NPC_PARAM, 0)`) so the
engine's `npc == 0` skip suppresses the redundant standalone horse, then
let the rider Part swap normally through the pick path.

## The visual-mount mechanism — the key finding

The engine parses exactly **five** Part fields (`oops_v3` PART_OFF_*):
`MODEL_INDEX` (20), `THINK_PARAM` (696), `NPC_PARAM` (700), `ENTITY_ID`
(608), `POSITION` (1024). It does **not** read draw groups, a draw-parent
reference, dummy-poly attachment, or any "cluster"/"anim binding" field.

This explains the v0.24.101 bug that shelved the collapse pass: seed
537123 spawned a Godskin Apostle visibly on the Night's Cavalry horse
**even though the c3160 mount Part's npc_param was zeroed.** The horse a
rider rides is therefore *not* the paired mount Part — suppressing that
Part removed a standalone horse, not the ridden one. The ridden mount
comes through what the v0.24.101 note calls the rider's "anim cluster
binding": something attached to the rider that the engine neither parses
nor edits.

Consequences:

1. **"Randomize the mount" is out of scope.** The mount a rider rides is
   not an MSB slot the rando controls. Making "random humanoid on a
   random mount" would require editing NPCParam / regulation.bin, which
   the rando explicitly does not touch.
2. **"Embrace the visual mount" is the only viable path** — and seed
   537123 is evidence it already works mechanically: the swapped rider
   *does* appear correctly mounted. Whether it looks good is a playtest
   judgement (prior playtests suggest M humanoids and even a Godskin
   Apostle read fine on a horse).
3. The rando cannot *remove* the mount either — so a swapped rider will
   always be mounted. That is the feature, not a bug, under the embrace
   framing.

## Cut-2 implementation plan (embrace path)

Scope: pilot-active pairs only (`V3_MOUNT_RIDER_PILOT_PAIRS` = Kaiden
c4050/c4060). Night's Cavalry and the Lordsworn night-boss instance stay
fully vanilla. All behind the existing `mount_rider_swap` toggle.

1. **Suppress the redundant mount Part.** In `shuffle_msb_v3`, when
   `mount_rider_swap` is on, for each detected pilot-active pair, zero
   the mount Part's npc_param — i.e. re-enable the
   `_collapse_rider_mount_pairs` mutation, but gated to pilot-active
   pairs only. `_detect_mount_rider_slots` already returns `mount_pi`;
   resolve `mount_po` from `parts['entry_offsets'][mount_pi]`.

2. **Lift the rider slot's source-exclude.** The swap loop skips
   source-excluded slots at `oops_v3.py` ~line 11789
   (`if cur_cp in V3_EXCLUDE_SOURCE_PREFIXES: ... continue`). This skip
   must be bypassed when `mount_rider_swap` is on AND `pi` is a
   pilot-active `rider_pi` from the detection. Build a
   `pilot_rider_pis` set from the detection result before the loop and
   add `and pi not in pilot_rider_pis` (or equivalent) to the skip
   condition. NB: a second source-exclude check exists in the per-slot
   validation path at ~line 10472 (`if src_cp in
   V3_EXCLUDE_SOURCE_PREFIXES: return None`) — verify which path the
   rider slot takes and gate whichever fires.

3. **Gate the rider pick to an M humanoid.** At the rider slot, restrict
   the target to `anim_class == 'humanoid'` + `size_class == 'M'`
   (playtest may justify widening). Cleanest: a new gate in
   `_reject_target_for_slot` keyed on `pi` being a pilot-active rider
   (mirrors Gate 8 / `requires_intro_anim`, which is already slot-keyed
   via `pi`). Thread the `pilot_rider_pis` set into the gate the way the
   intro-anim required-slots set is threaded.

4. **Do NOT touch the mount slot's pick.** It is suppressed in step 1;
   `V3_MOUNT_CLASS_POOL` is not consumed by the embrace path. Keep the
   constant — it documents the mount set and is harmless — but cut 2
   does not pick from it.

5. **Tests.** Extend `tests/test_mount_rider_detect.py` (or a sibling):
   the npc_param-zero is applied only to pilot-active mounts; non-pilot
   pairs are untouched; the rider gate rejects non-M-humanoid targets at
   a pilot rider slot and nothing elsewhere.

6. **Version.** Cut 2 is an engine behaviour change → bump
   `V3_ENGINE_FINGERPRINT`, CHANGELOG entry, update this doc + the TODO.

Risk note: cut 2 randomizes the **rider** slot (c4050) only. It does not
randomize **mount** slots — the v0.20.27 "mount-slot CTD class" was
specifically mount slots, so the embrace path stays clear of it. Behind
a default-OFF experimental toggle regardless.

## Remaining unknown + how to resolve it

The exact attachment mechanism of the visual mount (the "anim cluster
binding") is not determinable from the engine code — the engine does not
parse the relevant field. Resolving it needs one of:

- A **decompressed** Kaiden MSB, to inspect the c4050 rider Part's full
  record including fields the engine does not currently parse (draw
  parent, dummy-poly attachment, etc.). NOTE: this could not be done in
  the investigation environment — `vanilla_msbs/*.msb.dcx` are Oodle-
  compressed and no Oodle decompressor was available; the only
  uncompressed MSB on hand (`reference/m60_45_37_20.msb`) has no
  mount/rider parts.
- Or a **playtest of cut 1's audit** plus an in-game look at a Kaiden
  pair: confirm the `MOUNT_RIDER_DETECT` entries match what is on the
  ground, and judge whether a swapped rider on the inherited mount reads
  acceptably.

Neither blocks the cut-2 build above — the embrace path does not depend
on understanding the attachment, only on suppressing the redundant mount
Part and swapping the rider. The unknown only affects polish (does it
look right) and a possible future "remove the mount entirely" option,
which would require resolving it first.
