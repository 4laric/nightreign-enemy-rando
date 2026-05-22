#!/usr/bin/env python3
"""emit_mmv_style_arena_emevd.py — generate minimal MMV-style arena EMEVDs.

DEPRECATED in v0.25.9. See dev/extract_boss_init_calls.py for the
replacement.

What this module does, internally
---------------------------------
Emits EMEVDs that follow MMV's (Maple Mountain Variety mod) 13-event
9001x pattern. The module is internally consistent — its tests pass,
the binary builder round-trips through DCX, and the output is byte-
perfect against MMV's m46_56 reference. None of that changed.

Why we don't use it for test-mode arenas
----------------------------------------
v0.25.8 used this emitter as a "minimal boss-init template" for the
20 expedition N1/N2 arenas. That was a category error. Confirmed via:

  1. MMV's MSB extraction (witchy'd by Alaric): MMV ships 31 MSBs,
     zero overlap with vanilla NR's N1/N2 expedition arenas (m48_20..
     m49_29). MMV's pattern is for THEIR custom arenas, not ours.
  2. Every MMV Enemy Part has GameEditionDisable=NeverDisable — chrs
     load enabled at map-load. So MMV's 9001x calls are post-spawn
     dressing (music/healthbar/aggro), not a boss-init template.
  3. Vanilla NR expedition arenas have boss chrs that start DISABLED
     and require 90065910 (or 90065131/90065121/90065050 specialized
     variants) to enable on the night-1/N2 trigger flag.
  4. Playtest validation (seed 855504 on the Gaping Jaw expedition
     path): with v0.25.8's MMV overlay, "night 1 boss failed to start"
     — the chr stayed disabled because we'd stripped vanilla's
     90065910 call.

The v0.25.9 replacement (extract_boss_init_calls.py) copies vanilla's
boss-init calls verbatim and strips the cinematic/dressing events.

This module is kept for:
  - Its existing tests, which document the MMV-pattern emit shape
  - Reference if anyone needs to author custom-arena EMEVDs from
    scratch (the use case MMV was built for)
  - The 90015013/015/016/199/468/etc. arg layouts in case we ever
    want to author post-spawn dressing for our own custom arenas

If you're looking for the "make test mode work" path, see
dev/extract_boss_init_calls.py.

────────────────────────────────────────────────────────────────────
Original v0.25.8 module description follows
────────────────────────────────────────────────────────────────────

The vanilla NR N1/N2 EMEVDs use a 20-event template with cinematic camera,
multi-phase tracking, day-3 conditionals, fog-wall locks, and wake
choreography. ~126 lines per arena. The full set of NR's arena scaffolding
has been a pain point for testing: 18 hours of playtest to verify all
N1/N2 arenas across 8 Nightlords because each arena has slightly
different scripted behavior that can fail in non-obvious ways when boss
chrs are randomized.

MMV (the Maple Mountain Variety mod) ships its own minimal EMEVD pattern
across 30+ custom arenas. The pattern uses 12-13 distinct common events
(vs vanilla's 20), no cinematic, no map-variation conditionals, no wake
choreography — boss is active when player enters. The pattern is
field-validated by widespread MMV play.

This generator emits MMV-style EMEVDs parameterized by:
- map_prefix: e.g. "49170" (the m49_17 5-digit prefix)
- bosses: list of (boss_eid_suffix, npc_param_id, death_flag) tuples

The generated EMEVD replaces the vanilla arena EMEVD when test-mode is
enabled, giving us a "boss spawns, fight, advance" minimal substrate
that's identical across all arenas. Test cycle drops from 18 hours to
~1 hour because verifying one arena vouches for the template.

The MMV pattern per boss
------------------------

For each boss in the arena:
  90015000(0, BOSS_EID, NPC_PARAM, 30, 0, 0)         # spawn chr at slot
  90015030(0, BOSS_EID, 30, DEATH_FLAG, 0)           # idle anim during wait
  90015002(0, 0, BOSS_EID, BOSS_EID, 1020,           # HP bar binding
           DEATH_FLAG, 11290, NPC_PARAM, BOSS_EID)
  9005810(BOSS_EID, REGION_BOSS, REGION_WAKE, 5)     # wake on player area
  90015005(REGION_WAKE, REGION_END, BOSS_EID)        # awaken trigger

After all bosses, the S0 jump-target contains death observers:
  90015008(0, ANCHOR_EID, DEATH_FLAG, BOSS_EID, 0, 0) × N bosses

Then arena-wide setup:
  90015013                                            # arena fog/env setup
  90015015(BOSS_EID), 90015016(BOSS_EID) × N         # display variants
  if EventFlag(7604): reward routing × N
  90015199(BOSS_EID) × N                              # display binding 3

Arguments meaning (from MMV source analysis)
--------------------------------------------

90015000 args: (slot_id, boss_eid, npc_param, distance_30, _0, _0)
  - boss_eid: entity ID for the boss instance
  - npc_param: NpcParam row ID (determines what chr/stats/AI)
  - distance_30: wake/aggro radius

90015002 args: (_0, _0, boss_eid, hpbar_anchor_eid, style_1020,
                death_flag, nameId_11290, npc_param, boss_eid)
  - style_1020: HP bar style (1020 = boss bar)
  - nameId_11290: text table reference for boss name
  - death_flag: the per-boss progression flag

9005810 args: (boss_eid, region_boss, region_wake, dist_5)
  - region_boss: MSB region anchor for boss position
  - region_wake: MSB region where player triggers wake

90015005 args: (region_wake, region_end, boss_eid)
  - region_end: MSB region for fight bounds

Usage
-----

Programmatic:
    template = ArenaTemplate(map_prefix="49170")
    template.add_boss(eid_suffix="0800", npc_param=904770000,
                      death_flag=931000)
    print(template.emit())

CLI (dry-run):
    python3 dev/emit_mmv_style_arena_emevd.py --map 49170 \\
        --boss 0800:904770000:931000 \\
        --out /tmp/m49_17_minimal.emevd.js
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BossSpec:
    """Per-boss parameterization."""
    eid_suffix: str        # e.g. "0800", "0810" — appended to map prefix
    npc_param: int          # NpcParam row ID
    death_flag: int         # progression flag fired on death
    name_id: int = 11290    # text table reference (default = MMV's chosen)


@dataclass
class ArenaTemplate:
    """MMV-style minimal arena EMEVD generator.

    map_prefix is the 4-digit prefix derived from the MSB name. For
    m49_17_00_00.msb the prefix is "4917" (because eids look like
    49170800, 49170810, etc — 4-digit prefix + 4-digit suffix = 8-digit eid).

    eid_suffix is 4 digits. The convention is:
      - 0800, 0810, 0820, 0830: boss instances (per-boss block)
      - 0500: boss-position anchor region
      - 1500: wake-trigger region
      - 2800: fight-end region

    So full eid is map_prefix + eid_suffix, e.g. "4917" + "0800" = 49170800.
    """
    map_prefix: str
    bosses: list[BossSpec] = field(default_factory=list)
    # Region eid suffixes — defaults match MMV convention. Override only
    # if the MSB uses different region IDs.
    region_boss_suffix: str = "0500"   # boss-position anchor region
    region_wake_suffix: str = "1500"   # wake-trigger region
    region_end_suffix: str = "2800"    # fight-end region
    # Anchor entity used by 90015008 death observers. MMV's pattern is
    # mixed: m46_56 uses each boss's OWN eid as the anchor, m46_81
    # uses the FIRST boss eid for all death observers. The default
    # here matches m46_56 behavior (per-boss-own-anchor) since it's
    # the structurally cleaner option — each boss death observer is
    # self-contained and doesn't depend on the first boss existing.
    # Set to True only if matching m46_81-family behavior is needed.
    death_anchor_first_boss: bool = False
    # 90015013 (arena-fog/env setup) is conditionally included in MMV
    # via `if (1 != 0)` (always-true) or `if (0 != 0)` (dead). Default
    # to always-true to match the common MMV case (m46_56 et al).
    # Some MMV arenas use the always-false variant (m46_81); set False
    # to match those.
    include_arena_setup: bool = True
    # MMV's IsPlayMode(2) multiplayer-mode setup. Harmless to include.
    include_multiplayer_setup: bool = True
    # MMV's secondary $Event(xxx2200, ...) — the disable-collision-on-
    # area-entry block. MMV ships this in most arenas. For test-mode
    # minimum it's safe to skip, but keeping it on by default matches
    # the canonical MMV pattern for fidelity.
    include_area_disable_event: bool = True

    def add_boss(self, eid_suffix: str, npc_param: int,
                 death_flag: int, name_id: int = 11290) -> 'ArenaTemplate':
        """Add a boss to this arena."""
        self.bosses.append(BossSpec(eid_suffix=eid_suffix,
                                     npc_param=npc_param,
                                     death_flag=death_flag,
                                     name_id=name_id))
        return self

    def _full_eid(self, suffix: str) -> str:
        return f"{self.map_prefix}{suffix}"

    def emit(self) -> str:
        """Generate the EMEVD source as a string."""
        if not self.bosses:
            raise ValueError("ArenaTemplate.emit(): no bosses configured")

        region_boss = self._full_eid(self.region_boss_suffix)
        region_wake = self._full_eid(self.region_wake_suffix)
        region_end = self._full_eid(self.region_end_suffix)
        first_boss_eid = self._full_eid(self.bosses[0].eid_suffix)

        lines: list[str] = []
        # EMEVD header — matches MMV format exactly
        lines.append("// ==EMEVD==")
        lines.append("// @docs    nr-common.emedf.json")
        lines.append("// @compress    DCX_KRAK")
        lines.append("// @game    Sekiro")
        lines.append('// @string    "W:\\\\CL\\\\data\\\\Param\\\\event\\\\common_func.emevd\\u0000W:\\\\CL\\\\data\\\\Param\\\\event\\\\common_macro.emevd\\u0000\\u0000\\u0000\\u0000\\u0000\\u0000"')
        lines.append("// @linked    [0,82]")
        lines.append("// @version    3.6.2")
        lines.append("// ==/EMEVD==")
        lines.append("")
        # The main $Event(0, Default, ...) — auto-fires on map load
        lines.append("$Event(0, Default, function() {")
        lines.append("    ")

        # ---- Per-boss init blocks ----
        for boss in self.bosses:
            beid = self._full_eid(boss.eid_suffix)
            np = boss.npc_param
            df = boss.death_flag
            nm = boss.name_id
            # 1. spawn chr at slot
            lines.append(f"    $InitializeCommonEvent(0, 90015000, 0, {beid}, {np}, 30, 0, 0);")
            # 2. idle anim during pre-wake (waits on death flag NOT set)
            lines.append(f"    $InitializeCommonEvent(0, 90015030, 0, {beid}, 30, {df}, 0);")
            # 3. HP bar + name + music
            lines.append(f"    $InitializeCommonEvent(0, 90015002, 0, 0, {beid}, {beid}, 1020, {df}, {nm}, {np}, {beid});")
            # 4. wake-region binding
            lines.append(f"    $InitializeCommonEvent(0, 9005810, {beid}, {region_boss}, {region_wake}, 5);")
            # 5. awake trigger
            lines.append(f"    $InitializeCommonEvent(0, 90015005, {region_wake}, {region_end}, {beid});")

        # ---- Death-observer block (under S0 jump target) ----
        lines.append("    GotoIf(S0, Signed(0) != 0);")
        lines.append("    GotoIf(S0, 0 != 0);")
        lines.append("    Goto(S1);")
        lines.append("S0:")
        for boss in self.bosses:
            beid = self._full_eid(boss.eid_suffix)
            df = boss.death_flag
            anchor = first_boss_eid if self.death_anchor_first_boss else beid
            lines.append(f"    $InitializeCommonEvent(0, 90015008, 0, {anchor}, {df}, {beid}, 0, 0);")
        lines.append("S1:")

        # ---- Arena setup (env / fog) ----
        # 90015013 conditional matches MMV's authoring per-arena. Default
        # is `1 != 0` (always-true) — most MMV arenas use this form.
        setup_cond = "1 != 0" if self.include_arena_setup else "0 != 0"
        lines.append(f"    if ({setup_cond}) {{")
        lines.append("        $InitializeCommonEvent(0, 90015013);")
        lines.append("    }")

        # ---- Display binding (90015015 + 90015016 per boss) ----
        for boss in self.bosses:
            beid = self._full_eid(boss.eid_suffix)
            lines.append(f"    $InitializeCommonEvent(0, 90015015, {beid});")
            lines.append(f"    $InitializeCommonEvent(0, 90015016, {beid});")

        # ---- Reward routing (event-flag gated, follows MMV) ----
        lines.append("    if (EventFlag(7604)) {")
        for boss in self.bosses:
            beid = self._full_eid(boss.eid_suffix)
            lines.append(f"        $InitializeCommonEvent(0, 90015071, {beid});")
            lines.append(f"        $InitializeCommonEvent(0, 90015468, {beid}, 8270, 8247);")
        lines.append("    }")

        # ---- 90015199 per boss (display binding variant 3) ----
        for boss in self.bosses:
            beid = self._full_eid(boss.eid_suffix)
            lines.append(f"    $InitializeCommonEvent(0, 90015199, {beid});")

        # ---- Multiplayer mode setup (90015040) ----
        if self.include_multiplayer_setup:
            lines.append("    if (IsPlayMode(2)) {")
            lines.append("        $InitializeCommonEvent(0, 90015040, 0);")
            lines.append("    }")

        # Close the main $Event block
        lines.append("});")
        lines.append("")

        # ---- Secondary $Event(xxx2200, ...) area-disable block ----
        # MMV ships this verbatim across arenas. The InArea checks
        # reference world coordinates (10453xxxxx etc) which are NOT
        # parameterized by arena — they're hardcoded MMV map regions.
        # For test-mode use the same hardcoded coords MMV uses; this
        # event only fires if EventFlag(7603) is set, which is a state
        # MMV arenas tickle. Harmless to include.
        if self.include_area_disable_event:
            area_event_id = self._full_eid("2200")
            lines.append(f"$Event({area_event_id}, Default, function(chrEntityId) {{")
            lines.append("    EndIf(")
            lines.append("        !(!EventFlag(7603)")
            lines.append("            && (InArea(chrEntityId, 1045392989)")
            lines.append("                || InArea(chrEntityId, 1045392988)")
            lines.append("                || InArea(chrEntityId, 1044362996)")
            lines.append("                || InArea(chrEntityId, 1045382998)")
            lines.append("                || InArea(chrEntityId, 1045382997)")
            lines.append("                || InArea(chrEntityId, 1045362996)")
            lines.append("                || InArea(chrEntityId, 1045362995)")
            lines.append("                || InArea(chrEntityId, 1045362994))));")
            lines.append("    DisableCharacter(chrEntityId);")
            lines.append("    DisableCharacterCollision(chrEntityId);")
            lines.append("});")
            lines.append("")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────────
    # Binary emitter — outputs raw .emevd bytes (post-DCX, pre-Oodle).
    #
    # The DarkScript-style JS emitter above is for human review. The
    # binary emitter is for the rando pipeline: it produces bytes that
    # plug into `dcx_batch.emevd_compress_dir` directly, no DarkScript3
    # round-trip required.
    #
    # Skips the control-flow shenanigans the JS form uses (GotoIf S0 /
    # Goto S1). At binary level those are dead-code anyway in MMV's
    # template — the conditions are always false, so S0 is never
    # entered; we emit the InitializeCommonEvent calls flat, in
    # registration order. Each common-event registration is a one-shot
    # setup call; "control flow" doesn't change what gets registered
    # at startup.
    #
    # Likewise the `if (1 != 0)` and `if (EventFlag(7604))` wrappers
    # in the JS form are runtime conditionals on whether to FIRE the
    # InitializeCommonEvent. For test mode we just emit them flat —
    # we want the common events registered unconditionally. The
    # behavior change is:
    #   - 90015013 (arena fog/env setup): always registered (was
    #     gated `if (1 != 0)` = always true anyway in canonical MMV)
    #   - 90015071/90015468 (reward routing): always registered
    #     (was gated on EventFlag(7604)). In test mode we don't care
    #     about reward gating — we want the loot to drop regardless.
    #   - 90015040 (multiplayer setup): always registered
    #     (was gated on IsPlayMode(2)). Harmless in single-player.
    # ────────────────────────────────────────────────────────────────────

    def emit_binary(self) -> bytes:
        """Generate raw .emevd binary (Sekiro+ format).

        Returns bytes ready for DCX compression. Use:

            from dcx import DCX
            raw = template.emit_binary()
            dcx_bytes = DCX.compress_bytes(raw)
            open('m49_17_00_00.emevd.dcx', 'wb').write(dcx_bytes)

        This bypasses DarkScript3 entirely. Compatible with the
        pure-Python EMEVD parser at healthbar_inplace/emevd.py.

        Hooks into healthbar_inplace/synth.py for binary layout —
        same builder used to author synthetic test EMEVDs for the
        healthbar parser tests.
        """
        if not self.bosses:
            raise ValueError("ArenaTemplate.emit_binary(): no bosses configured")

        # Lazy import — synth lives in a sibling package; only needed
        # for binary emit. The text emitter above has no dep on it.
        import os, sys
        _here = os.path.dirname(os.path.abspath(__file__))
        _hb_path = os.path.join(_here, '..', 'healthbar_inplace')
        if _hb_path not in sys.path:
            sys.path.insert(0, _hb_path)
        from synth import build_minimal_emevd, healthbar_instruction

        # Resolve fully-qualified eids
        def eid(suffix: str) -> int:
            return int(f"{self.map_prefix}{suffix}")

        region_boss = eid(self.region_boss_suffix)
        region_wake = eid(self.region_wake_suffix)
        region_end = eid(self.region_end_suffix)
        first_boss_eid = eid(self.bosses[0].eid_suffix)

        # Build the instruction list — flat, no control flow.
        instructions = []

        # Per-boss init blocks (5 instructions per boss).
        for boss in self.bosses:
            beid = eid(boss.eid_suffix)
            np = boss.npc_param
            df = boss.death_flag
            nm = boss.name_id
            # spawn chr at slot
            instructions.append(healthbar_instruction(
                0, 90015000, 0, beid, np, 30, 0, 0))
            # idle anim pre-wake
            instructions.append(healthbar_instruction(
                0, 90015030, 0, beid, 30, df, 0))
            # HP bar + name + music
            instructions.append(healthbar_instruction(
                0, 90015002, 0, 0, beid, beid, 1020, df, nm, np, beid))
            # wake-region binding
            instructions.append(healthbar_instruction(
                0, 9005810, beid, region_boss, region_wake, 5))
            # awake trigger
            instructions.append(healthbar_instruction(
                0, 90015005, region_wake, region_end, beid))

        # Death observers (one per boss).
        for boss in self.bosses:
            beid = eid(boss.eid_suffix)
            df = boss.death_flag
            anchor = first_boss_eid if self.death_anchor_first_boss else beid
            instructions.append(healthbar_instruction(
                0, 90015008, 0, anchor, df, beid, 0, 0))

        # Arena setup (90015013, takes no args).
        if self.include_arena_setup:
            instructions.append(healthbar_instruction(0, 90015013))

        # Display bindings (90015015/016) per boss.
        for boss in self.bosses:
            beid = eid(boss.eid_suffix)
            instructions.append(healthbar_instruction(0, 90015015, beid))
            instructions.append(healthbar_instruction(0, 90015016, beid))

        # Reward routing (90015071 + 90015468) per boss. In test mode
        # we register these unconditionally (vs JS form's EventFlag(7604)
        # gate) so loot drops on the test-mode kill.
        for boss in self.bosses:
            beid = eid(boss.eid_suffix)
            instructions.append(healthbar_instruction(0, 90015071, beid))
            instructions.append(healthbar_instruction(
                0, 90015468, beid, 8270, 8247))

        # Display binding variant 3 (90015199) per boss.
        for boss in self.bosses:
            beid = eid(boss.eid_suffix)
            instructions.append(healthbar_instruction(0, 90015199, beid))

        # Multiplayer setup — register unconditionally (JS form gates
        # on IsPlayMode(2); harmless in single-player).
        if self.include_multiplayer_setup:
            instructions.append(healthbar_instruction(0, 90015040, 0))

        # Build the single $Event(0, Default, ...).
        events_spec = [{
            'event_id': 0,
            'rest_behavior': 0,  # Default
            'instructions': instructions,
        }]

        # NOTE: the secondary $Event(xxx2200, ...) area-disable block
        # used by MMV's text form is NOT emitted here. That event uses
        # InArea() / DisableCharacter() calls which are NOT class 2000
        # (InitializeCommonEvent) — they're separate instruction
        # classes that the synth.py builder doesn't currently model.
        # For test-mode minimum, this event is dispensable (it gates
        # on EventFlag(7603), which test mode doesn't tickle).

        return build_minimal_emevd(events_spec)


def _parse_boss_spec(spec: str) -> BossSpec:
    """Parse 'EID_SUFFIX:NPC_PARAM:DEATH_FLAG[:NAME_ID]' from CLI."""
    parts = spec.split(":")
    if len(parts) < 3 or len(parts) > 4:
        raise argparse.ArgumentTypeError(
            f"Bad boss spec {spec!r}: expected 'eid_suffix:npc_param:death_flag[:name_id]'")
    eid_suffix = parts[0]
    try:
        np = int(parts[1])
        df = int(parts[2])
        nm = int(parts[3]) if len(parts) == 4 else 11290
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Bad numeric in {spec!r}: {e}")
    return BossSpec(eid_suffix=eid_suffix, npc_param=np, death_flag=df, name_id=nm)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--map', required=True,
                     help="4-digit map prefix (e.g. 4656 for m46_56)")
    ap.add_argument('--boss', action='append', type=_parse_boss_spec,
                     required=True,
                     help="Boss spec 'eid_suffix:npc_param:death_flag[:name_id]'. Repeat for multi-boss.")
    ap.add_argument('--death-anchor-first-boss', action='store_true',
                     help="Use first boss's eid as death-observer anchor (m46_81 variant). "
                          "Default: each boss uses own eid as anchor (m46_56 variant).")
    ap.add_argument('--no-arena-setup', action='store_true',
                     help="Use `if (0 != 0)` gate on 90015013 (m46_81 variant). "
                          "Default: `if (1 != 0)` (m46_56 variant).")
    ap.add_argument('--no-multiplayer-setup', action='store_true',
                     help="Skip the IsPlayMode(2) / 90015040 block.")
    ap.add_argument('--no-area-disable', action='store_true',
                     help="Skip the secondary $Event(xxx2200) area-disable block.")
    ap.add_argument('--out', help="Write to file instead of stdout")
    args = ap.parse_args()

    template = ArenaTemplate(
        map_prefix=args.map,
        death_anchor_first_boss=args.death_anchor_first_boss,
        include_arena_setup=not args.no_arena_setup,
        include_multiplayer_setup=not args.no_multiplayer_setup,
        include_area_disable_event=not args.no_area_disable,
    )
    for spec in args.boss:
        template.add_boss(eid_suffix=spec.eid_suffix,
                           npc_param=spec.npc_param,
                           death_flag=spec.death_flag,
                           name_id=spec.name_id)
    src = template.emit()

    if args.out:
        with open(args.out, 'w') as f:
            f.write(src)
        print(f"Wrote {args.out} ({len(src)} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(src)


if __name__ == '__main__':
    main()
