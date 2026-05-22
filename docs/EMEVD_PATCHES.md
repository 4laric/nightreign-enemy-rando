# EMEVD Patcher reference

`emevd_patch.py` is a Python tool that surgically modifies Nightreign's
`common_func.emevd.dcx` (the global event-handler library) to fix the encounter
bugs that arise from randomizing enemies into hand-tuned slots.

## Why this is necessary

NR's per-map EMEVDs are mostly tiny dispatcher stubs — `~1KB` each, just
`$InitializeCommonEvent(0, <handler_id>, <args...>)` calls. The actual logic
lives in `common_func.emevd.dcx` (`~963KB`, 651 handlers). This is huge leverage:
a single edit to a `common_func` handler propagates the fix to every map that
calls it.

But it also means the rando's bug surface is concentrated in a few high-traffic
handlers. When we change which c-prefix occupies a slot, the slot's encounter
script (which lives in `common_func`) tries to call animations, AI states, and
event flags tuned for the *original* occupant. If the new occupant doesn't have
that animation in their library, or doesn't transition through that AI state on
the same triggers, the handler hangs partway through.

## The patches

### `death_timeout`
**Substitutions:** 2  
**Handlers:** 90005860, 90005861  
**Trigger:** `WaitFor(CharacterDead(chrEntityId));`  
**Replaced with:** `WaitFor(CharacterDead(chrEntityId) || ElapsedSeconds(5));`

`CharacterDead(eid)` waits for the formal "dead" state — which requires the
death animation to complete. If the swapped enemy's animation library doesn't
have a properly-flagged death anim, the handler hangs forever on this wait. HP
is at 0, body is on the ground, but the death-state never enters → no encounter
flag set, no rune award, persistent corpse.

The timeout escapes after 5 seconds.

### `permissive_boss_wake`
**Substitutions:** 2  
**Handlers:** 90015000 (197 calls), 90015030 (195 calls)  
**Trigger:** `CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)`  
**Replaced with:** the same condition OR Recognition state OR Alert state OR
damage-taken (`CharacterRatioHPRatio(chrEntityId, NotEqual, 0) < 1`)

The boss healthbar / BGM activation handlers wait for the entity to reach
`Combat` AI state. Some enemies (Abductor Virgin, Marionette Soldier) only
transition to Combat via separate scripted events that may not fire when the
slot is randomized. They sit in Recognition or Alert indefinitely, encounter
never formally activates.

The patch makes any of those AI states (or simply taking damage) sufficient.

### `permissive_spawn_emerge`
**Substitutions:** 55  
**Handlers:** 90085002, 90015310, 90015160/163/164, 90015300, 90015401,
90085012/101/201, 90035202/204/213/220-232/244/247/250/262/263/286,
90065009, 90075820/401, 90005200/201/211/221, 90005705/706/720/725/726/760

**Two patterns:**

**Pattern A (after ForceAnimationPlayback with literal anim ID):**  
inserts `EnableCharacterAI(chrEntityId)` immediately after the forced animation.

**Pattern B (after SetSpecialStandbyEndedFlag):**  
inserts `EnableCharacterAI(chrEntityId)` after the wake-confirm step in the
SpecialStandby family (sleeping/posed enemies).

These handlers play hand-tuned emerge / wake / stand-up animations meant for
the original c-prefix at this slot. When the rando swaps a different c-prefix
in, that animation either doesn't exist or freezes the entity in its start
frame. The AI loop never engages → enemy stays dormant indefinitely.

The fix forces AI activation regardless of whether the animation completed,
ensuring the entity transitions to active behavior even if it can't play the
expected emerge anim.

### `disable_corpse_collision` — RETIRED v0.24.100

Empirically not working — playtest confirmed corpses still occasionally
blocked Site-of-Grace spawns even with the patch loaded. Meanwhile
`death_timeout` (which forces the boss-dead branch to fire after 5s
regardless of death-anim completion) DOES reliably force SoG spawn in
practice, including when the boss spawned frozen and never took damage.
The standalone redundant DisableCharacterCollision call wasn't pulling
its weight. If body-blocked-SoG recurs, investigate why `death_timeout`'s
cleanup path isn't reaching DisableCharacterCollision rather than
reviving this patch.

## Total impact (common_func)

66 substitutions across `common_func.emevd.dcx`. Most of NR's other ~200
EMEVD files in `event/` are dispatcher stubs that route to the patched
handlers automatically and need no per-map changes.

## Per-map EMEVD patches

A small number of maps contain **inline event scripts** — events written
directly into the map's own `.emevd.dcx` rather than dispatched through
`common_func`. The patches above can't reach inline events, so each
affected map gets its own pre-patched `.emevd.dcx` shipped in
`patched_emevd/`.

| Map | What it patches |
|-----|-----------------|
| `m30_30_00_00.emevd.dcx` | Guardian Golem (Fort) stand-up cinematic + arena collision proxies (laying-down `npc=46601010` variant). Without this, swapped occupants freeze on the inline cinematic event. |
| `m38_10_00_00.emevd.dcx` | Cathedral interior 2 inline encounter / cutscene scripts. |
| `m60_43_37_00 / 10 / 20.emevd.dcx` | Three time variants of the same overworld cell (~110 slots each). All three share the same inline scripts and need identical patches. |

The `emevd_patch.py` tool currently does NOT cover per-map files — it
only patches `common_func`. The per-map files were patched separately
via DarkScript3-edited `.js` source and recompiled. Re-patching them
from a fresh vanilla requires the same DarkScript3 manual flow.

## Safety profile

All patches are **conservative additions**, never removals or behavioral
changes. They make conditions more permissive (logical OR) or add safety
fallbacks (timeouts, redundant cleanup). Vanilla NR play with these patches
loaded is functionally identical to unpatched vanilla, with one cosmetic
difference:

1. Boss healthbars may activate slightly faster in some encounters (when the
   swapped enemy reaches Recognition before reaching Combat — vanilla also
   shows the bar but it's gated through Combat).

Has not been observed to break vanilla encounters.

## Adding new patches

Each patch is a Python function decorated with `@register('name')`. It receives
file content + filename and returns `(modified_content, n_substitutions)`. See
existing patches for the pattern.

Key helpers:

- `replace_in_event(content, event_id, regex, replacement) -> (new_content, n)`
  scoped substitution within a specific `$Event(<id>, ...)` block, so changes
  don't bleed across handlers.
- Patches gate on `filename.startswith('common_func')` to avoid touching
  per-map EMEVDs.

## Verifying the patch loaded

Search the installed `common_func.emevd.dcx.js` (after decompiling) for
`EnableCharacterAI` — should see ~210 occurrences. Vanilla baseline is ~155.

Or compare file sizes — patched is roughly 3KB larger than vanilla.
