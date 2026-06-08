# TODO: c2030 / c2031 Rennala — two-entity-swap phase transition

**Status:** BANNED (temporary) as of v0.31. Both `c2030` and `c2031` added to
`V3_EXCLUDE_TARGET_PREFIXES` in `engine/load_data.py` immediately after the
`c6201` add. Un-ban both once the work below lands.

## Symptom
Phase-2 anomaly during Rennala's summon attack. Presents as texture issues,
but those are suspected to be *masking* a phase-transition failure rather than
being the root problem — i.e. the visible glitch is a side effect of the
phase-2 entity not being seated/handled correctly in a relocated context.

## Why she is NOT in the single-entity re-enable system
Rennala is a **two-entity swap**, not a single-entity marker re-enable:

- `c2030` = phase 1 (Rennala, the projected form).
- `c2031` = phase 2 (the real Rennala) — **warped in as a separate chr**.

This is the class already called out in
`data/phase_transition_imports.json -> _excluded.two_entity_swaps`
("Rennala c2030->c2031 and Godfrey c4720->Hoarah Loux c4721 use a different
mechanism (second chr warped in) and need second-entity placement handling,
NOT this re-enable"). So the `nb_phase_reenable` marker path (the one that
gates c2110 Maliketh on 15299, c5130 Messmer on 20010612, etc.) does **not**
apply here. Adding a marker for Rennala would be the wrong fix.

## Root-cause gap
`_excluded.two_entity_swaps` is documentation only. `emevd_patch.py`'s
`_load_phase_transition_imports()` reads only the `markers` dict and never the
`_excluded` block, so nothing in the live pipeline ever excluded Rennala or
arranged for the second entity. She stayed live in the heritage pool with no
second-entity placement handling — hence the phase-2 break.

## What the real fix needs
Second-entity placement handling for warped-in phase-2 chrs:
1. When `c2030` is placed at a slot, also stage/place `c2031` as the partnered
   phase-2 entity at that slot (analogous to the rider/mount pairing work, but
   triggered by phase transition rather than proximity).
2. Make `_excluded.two_entity_swaps` an *active* gate, not just docs — either
   exclude these prefixes from the normal single-pick pool automatically, or
   route them through the (future) paired-placement path. Same fix would also
   un-stick Godfrey `c4720`->`c4721`.

## To verify before un-banning
- Home-arena (Raya Lucaria, m14) control fight — does phase 2 work at home?
  (Establishes broken-import vs relocation-dependency, same discipline as the
  c8300 note.)
- Confirm whether the texture artifact persists once c2031 is placed correctly,
  or whether it was purely a symptom of the missing second entity.

## Cross-refs
- `data/phase_transition_imports.json` -> `_excluded.two_entity_swaps`
- `data/mmv_imports.json` `_note` (MMV-side c2030 "floating-in-air pose"
  ai_broken entry — a *different, milder* symptom from the disabled MMV path;
  do not conflate).
- Godfrey/Hoarah Loux `c4720`/`c4721` — same two-entity-swap class, same fix.
