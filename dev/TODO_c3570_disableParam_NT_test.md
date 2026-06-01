# Test: Godskin Noble disableParam_NT restore (v0.28.x)

**Hypothesis**: NR's `disableParam_NT=1` on c3570 NpcThinkParam rows
suppresses the rolling-attack sub-state. Restoring to 0 (ER's value) will
re-enable the roll.

**Scope**: c3570 only. 10 of 12 c3570 NpcThinkParam rows have the flag set
to 1 — IDs 35700000, 35700005, 35700010, 35700020, 35700030, 35700100,
35700110, 35700120, 35700130, 35700140. Two rows (35700900, 35700910) already
have it at 0 and are left untouched.

**Apply via**: Smithbox CSV import on NpcThinkParam, using
`NpcThinkParam_c3570_disableParam_NT_off.csv`. Rebuild regulation.

**Risk**: Low. `disableParam_NT` is an explicit disable flag. If NT happens
to control something unrelated to rolling, expected outcome is "no visible
behavior change," not "regression." Other fields (sight, memory, FOV) remain
at NR values, so the chr's general awareness is unchanged.

**What to look for in-game**:

1. **Positive signal — rolling attack present**: Spawn a Godskin Noble.
   Engage at melee range to verify normal moveset still works (no
   regression). Then back off to ~15-25 units. In ER, this is the
   distance threshold where Godskin enters the ball-form and rolls.
   If the roll fires, the patch worked.

2. **Negative signal — still no roll**: If the roll doesn't appear after
   several encounters across different arena geometries, the flag isn't
   the gating mechanism. Next experiments:
   - Restore `SightTargetForgetTime` (8 → 16) so the chr doesn't forget
     the player as fast — roll might need sustained pursuit context
   - Restore the full sight/memory profile (eye_dist, eye_angY,
     nose_dist) — more invasive but matches ER's persistence model
   - If neither works: the issue is downstream of NpcThinkParam
     (anibnd missing the roll animation, or hardcoded engine table)

3. **Regression signal — something else broke**: e.g., chr becomes
   non-functional, freezes, or starts using ER's full aggression
   profile in NR's compressed gameplay loop. Rollback by reverting
   the 10 ThinkParam rows to disableParam_NT=1.

**Test conditions**:

- At least 3 separate Godskin Noble encounters (different runs)
- Mix of melee and kite playstyle
- Note any HP threshold transitions (the roll might be HP-gated)
- Time-bound: if no roll appears across 5+ separate fights, declare
  the negative outcome and move to next experiment

**Adjacent chrs that share the same NR-dialed-down AI pattern** (next
candidates if this works):

- c4770 Valiant Gargoyle (the original case — already has separate
  rangedAttackId fix queued)
- All chrs in the `nr_thinkparam_gap_audit.json` "empty" tier
  (c5170 Furnace Golem, c5500 Living Magma, c2120 Malenia,
  c2110 Beast Clergyman, etc.) that had AI imports but might have
  disableParam_NT=1 set across the board

**Follow-up if positive**: extend disableParam_NT restore to other
heritage/MMV chrs systematically (script is reusable, just change the
c-prefix range filter).

**Follow-up if negative on rolling but no regression**: try the
sight/memory restore as the next-most-conservative step.
