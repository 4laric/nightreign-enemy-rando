#!/usr/bin/env python3
"""
emevd_patch.py — Batch-patch decompiled NR EMEVD JS files to fix rando-introduced
bug classes in encounter event scripts.

Usage:
    # Apply all patches to a folder of decompiled .emevd.dcx.js files:
    python emevd_patch.py patch <input_js_dir> <output_js_dir>

    # Apply only specific patches:
    python emevd_patch.py patch <input> <output> --patch death_timeout

    # List available patches:
    python emevd_patch.py list

After patching, recompile each modified .js back to .emevd.dcx with DarkScript3
(Windows-side, since DarkScript3 is a .NET tool):

    DarkScript3.exe <file>.emevd.dcx.js  → produces <file>.emevd.dcx

Then drop the recompiled .emevd.dcx files into your me3 profile under:
    <profile>/<package>/event/

== Background ==

NR's EMEVDs follow a dispatcher pattern: per-map files are mostly tiny stubs
(~1KB each) that call $InitializeCommonEvent() with parameter sets, while the
actual logic lives in common_func.emevd.dcx. This means a single edit to a
common_func handler can fix entire bug classes globally.

The randomizer modifies MSB Parts to swap NPCParam/ModelIndex while preserving
entity_ids. Most encounter event handlers reference entities by entity_id, so
they still fire correctly. The bug classes that DO break:

1. Death-state hang: encounter handlers wait for CharacterDead(eid) which
   requires the formal "dead" state (death animation completes). If the swapped
   enemy's death anim has any anim_bank mismatch, this never enters → no rune
   award, body persists, Site of Grace stays locked.

2. Wake-trigger gating: encounter activation handlers wait for the entity to
   reach AIStateType.Combat. Some bosses (Abductor Virgin, Marionette Soldier,
   sleeping camp enemies) only transition to Combat via separate scripted
   events that may not fire when the slot is randomized.

This tool patches the relevant handlers in common_func.emevd.dcx.js to be more
permissive about these conditions, recovering most of the broken cases.
"""
import argparse, os, re, sys, shutil, json


# ============================================================================
# Patch infrastructure
# ============================================================================

class PatchResult:
    """Tracks what a patch did to one file."""
    def __init__(self, name, file, before_lines, after_lines, n_substitutions):
        self.name = name
        self.file = file
        self.before_lines = before_lines
        self.after_lines = after_lines
        self.n_substitutions = n_substitutions


def get_event_body(content, event_id):
    """Extract the full body of $Event(event_id, ...) from content. Returns
    (start_offset, end_offset, body) or (None, None, None) if not found."""
    pattern = re.compile(
        rf'^\$Event\({event_id},.*?(?=^\$Event\(|\Z)',
        re.MULTILINE | re.DOTALL)
    m = pattern.search(content)
    if not m: return None, None, None
    return m.start(), m.end(), m.group(0)


def replace_in_event(content, event_id, pattern, replacement):
    """Replace `pattern` (regex) with `replacement` (str) only inside the body
    of the specified $Event(). Returns (new_content, n_substitutions)."""
    start, end, body = get_event_body(content, event_id)
    if body is None: return content, 0
    new_body, n = re.subn(pattern, replacement, body)
    if n == 0: return content, 0
    return content[:start] + new_body + content[end:], n


# ============================================================================
# Patches
# ============================================================================

PATCHES = {}


# v0.25.0 publish-mode gate. When True, suppresses the audible+visible
# tracer/feedback effects added during the v0.24.107–v0.24.113 boss-init
# investigation and the v0.24.111 hold-trigger ship:
#   - nb_boss_init_diag_tracers (PlaySE + DisplayTextEffectId banners
#     in the three common_func boss-init events 90015000/30/02) is
#     skipped entirely.
#   - nb_boss_force_enable_watchdog still injects (the recovery logic
#     is the point of the patch), but its PlaySE pre/post barrage
#     tracers are suppressed via tracers=False.
#   - nb_arena_hold_trigger still injects (the trigger flag still gets
#     set when the player holds at the arena center), but its
#     PlaySE + DisplayTextEffectId(1020) "POWER GAINED"-style feedback
#     banner is suppressed via tracers=False. v0.24.x widened the
#     hold radius from 5m to 25m which made the banner fire reliably
#     in every NB arena per expedition — visually loud, especially
#     since 1020 is semantically the boss-defeat banner.
#
# Flip to False during a playtest investigation when you want the
# diagnostic feedback back. Tests pass either way (they call the
# tracers-on path explicitly via tracers=True).
PUBLISH_MODE = True


def register(name):
    def deco(fn):
        PATCHES[name] = fn
        return fn
    return deco


@register('death_timeout')
def patch_death_timeout(content, filename):
    """Add 5-second timeout to WaitFor(CharacterDead(chrEntityId)) in
    boss/encounter death handlers (90005860, 90005861).

    Symptom this fixes:
        - "Killed boss but didn't get runes" / "body blocks Site of Grace"
        - Encounter shows boss dead (HP=0, ragdoll) but Site-of-Grace activation
          flag never sets, so the player is stuck.
    Cause: CharacterDead(eid) waits for the formal "dead" state, which requires
    the death animation to complete. Randomized enemies with anim_bank
    mismatches can hit HP=0 without ever entering the dead state.
    Fix: Wait for either CharacterDead OR a 5-second timeout, whichever first.

    Only applies to common_func.emevd.dcx.js.
    """
    if not filename.startswith('common_func'):
        return content, 0
    total = 0
    for evid in (90005860, 90005861):
        # Match: WaitFor(CharacterDead(chrEntityId));
        # Replace with: WaitFor(CharacterDead(chrEntityId) || ElapsedSeconds(5));
        # Note: only match exactly this pattern (with the chrEntityId param name)
        # to avoid accidentally patching unrelated CharacterDead waits.
        pattern = r'WaitFor\(CharacterDead\(chrEntityId\)\);'
        replacement = 'WaitFor(CharacterDead(chrEntityId) || ElapsedSeconds(5));'
        content, n = replace_in_event(content, evid, pattern, replacement)
        total += n
    return content, total


# v0.24.102: permissive_boss_wake RETIRED.
# Pulling on the hypothesis that the wake-permissivity work is no longer
# load-bearing. Recent engine-side improvements (anim_compat-at-demotion,
# slot-pool gating, has_reward preservation, V3_PRESERVE_SLOTS hardening,
# and the broader has_reward / sensitive-target work) should mean swapped
# enemies reach AIStateType.Combat through normal vanilla pathways, making
# the Recognition/Alert/HP-damage OR-clauses dead weight. If broken
# encounters (boss healthbar never appears, fight never activates) reappear
# in playtest, re-enable by restoring the @register decorator and consider
# whether it's a specific anim_class issue first.
# Function body kept for reference; @register removed so it doesn't
# get picked up by the apply pipeline.
def patch_permissive_boss_wake(content, filename):
    """Make boss healthbar/BGM activation triggers more permissive.

    Symptom this fixes:
        - Boss healthbar appears late or never (encounter feels broken)
        - Encounter doesn't formally activate even though enemy is hostile
    Cause: Wake handlers (90015000, 90015030) wait for the entity to reach
    AIStateType.Combat. Some swapped enemies sit in Recognition or Alert states
    indefinitely instead of transitioning to Combat.
    Fix: Trigger on Combat OR Recognition OR Alert OR HP-damage-taken.

    Note: CharacterRatioHPRatio returns a value, not a boolean — it must be
    used on the LHS of a comparison. We use `< 1` (HP < 100%, i.e. damaged).
    The `NotEqual, 0` qualifier excludes already-dead entities from the check.

    Only applies to common_func.emevd.dcx.js.
    """
    if not filename.startswith('common_func'):
        return content, 0
    total = 0
    # The exact line in both 90015000 and 90015030:
    #   chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)
    # We add OR-clauses for Recognition/Alert/HP-damage.
    pattern = (
        r'CharacterAIState\(chrEntityId, AIStateType\.Combat, GreaterOrEqual, 1\)\r?\n'
        r'(\s*)&& EntityInRadiusOfEntity\(20000, chrEntityId, targetDistance, 1\)'
    )
    replacement = (
        r'(CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\r\n'
        r'\1   || CharacterAIState(chrEntityId, AIStateType.Recognition, GreaterOrEqual, 1)\r\n'
        r'\1   || CharacterAIState(chrEntityId, AIStateType.Alert, GreaterOrEqual, 1)\r\n'
        r'\1   || CharacterRatioHPRatio(chrEntityId, NotEqual, 0) < 1)\r\n'
        r'\1&& EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1)'
    )
    for evid in (90015000, 90015030):
        content, n = replace_in_event(content, evid, pattern, replacement)
        total += n
    return content, total


# v0.24.102: permissive_spawn_emerge RETIRED.
# Same hypothesis as permissive_boss_wake: with anim_compat-at-demotion,
# slot-pool gating, and SetNetworkUpdateRate AlwaysUpdate now happening
# at appropriate points elsewhere, the blanket EnableCharacterAI injection
# across ~30 spawn handlers (90085002, 90015310, 90015160/163/164,
# pose-idle 90035XXX family, SpecialStandby 90005200/201/211/221) may be
# overkill. If T-pose-stuck enemies or never-wakes-from-pose recurs in
# playtest, re-enable by restoring the @register decorator. Targeted
# anim_compat fixes in the swap layer are preferred over EMEVD blanket
# injection if individual cases need addressing.
# Function body kept for reference; @register removed so it doesn't
# get picked up by the apply pipeline.
def patch_permissive_spawn_emerge(content, filename):
    """Force AI to activate after spawn-emerge events, even if the emerge
    animation was wrong for the swapped-in enemy.

    Symptom this fixes:
        - Tunnel/cave enemies stuck in dormant idle pose (T-pose-with-attitude,
          stuck mid-stumble) and never enter combat
        - Downstream merchants/Sites of Grace gated behind that encounter's
          cleared-flag never unlock because the enemy never died

    Cause: a class of EMEVD spawn handlers calls ForceAnimationPlayback(eid,
    animId) with a hand-tuned animation_id meant for the original c-prefix
    at this slot. When we swap to a different c-prefix, that animation may
    not exist for the new enemy or may freeze them in its start frame —
    the AI loop never runs because EnableCharacterAI was never called.

    Affected handlers (all in common_func.emevd.dcx.js):
      * 90085002 (272 call sites) — generic mission character spawn
      * 90015310 (11 call sites)  — tunnel ambush warp-and-spawn (m30/m32/m34/m43)
      * 90015160/163/164 (27 each) — day/night cycle environmental enemies

    v0.23.10.7: extended to also call SetNetworkUpdateRate(eid, true,
    AlwaysUpdate) right after EnableCharacterAI. Some chrs boot in
    NoUpdate/throttled tick mode by default; without forcing AlwaysUpdate,
    EnableCharacterAI fires but the AI loop never gets enough server
    ticks to transition out of dormant state. Adding it here makes the
    rando's wake injection sufficient for those chrs at vanilla slots.
    Cost is essentially zero for chrs that were already AlwaysUpdate
    (the call is idempotent).

    Fix: add EnableCharacterAI(eid) after each ForceAnimationPlayback so AI
    activates regardless of animation completion. Conservative — doesn't
    affect non-randomized vanilla play because EnableCharacterAI on an
    already-AI-active character is a no-op.

    Only applies to common_func.emevd.dcx.js.
    """
    if not filename.startswith('common_func'):
        return content, 0

    total = 0

    # Pattern A: ForceAnimationPlayback(chrEntityIdN, animationId, false, false, false)
    # — the parameterized form used in 90085002 and similar dispatcher-style handlers.
    pattern_a = (
        r'(ForceAnimationPlayback\((chrEntityId[2-5]?), animationId, false, false, false\);)'
    )
    def repl_a(m):
        eid = m.group(2)
        return (f"{m.group(1)}\r\n"
                f"            EnableCharacterAI({eid});\r\n"
                f"            SetNetworkUpdateRate({eid}, true, "
                f"CharacterUpdateFrequency.AlwaysUpdate);")
    content, n = replace_in_event(content, 90085002, pattern_a, repl_a)
    total += n

    # Pattern B: ForceAnimationPlayback(chrEntityIdN, <literal int>, false, false, false)
    # — handlers like 90015310, 90015160/163/164, 90015300 use literal anim IDs
    # (63020, 30016, 20015, 30025, 30001 etc) tuned to the original enemy.
    # Identified via systematic scan of common_func: every handler that calls
    # EnableCharacter + ForceAnimationPlayback on an entity but never calls
    # EnableCharacterAI on that same entity is a candidate. Filtered to spawn-
    # pattern handlers (not death cleanup, not pure cycle without spawn).
    pattern_b = (
        r'(ForceAnimationPlayback\((chrEntityId[2-9]?), \d+, false, false, false\);)'
    )
    def repl_b(m):
        eid = m.group(2)
        return (f"{m.group(1)}\r\n"
                f"            EnableCharacterAI({eid});\r\n"
                f"            SetNetworkUpdateRate({eid}, true, "
                f"CharacterUpdateFrequency.AlwaysUpdate);")

    # Encounter activation / wake handlers (90015XXX family)
    encounter_handlers = (
        90015310, 90015160, 90015163, 90015164, 90015300, 90015401,
    )
    # Mission character spawn handlers (90085XXX family — siblings of 90085002)
    mission_spawn_handlers = (
        90085012, 90085101, 90085201,
    )
    # Scripted-pose-idle handlers (mining/kneeling/sleeping — 90035XXX, 90075XXX)
    pose_idle_handlers = (
        90035286, 90035202, 90035263, 90075820, 90005705,
        # Day/night cycle siblings of 90015160/163/164
        90035244, 90035247,
        # Other 90035XXX spawn handlers found in audit
        90035204, 90035213, 90035220, 90035221, 90035227, 90035229,
        90035232, 90035250, 90035262,
        # 90065XXX warp/spawn family
        90065009, 90075401,
        # Other tail-end candidates
        90005706, 90005720, 90005725, 90005726, 90005760,
    )
    for evid in encounter_handlers + mission_spawn_handlers + pose_idle_handlers:
        content, n = replace_in_event(content, evid, pattern_b, repl_b)
        total += n

    # Pattern D: SpecialStandby-family wake handlers (sleeping/posed enemies)
    # — these enemies start in a looping pose anim and wait for a wake trigger
    # (proximity / damage), then call SetSpecialStandbyEndedFlag and rely on
    # the engine's SpecialStandby system to resume AI. For vanilla c-prefixes
    # this works; for swapped c-prefixes whose anim library doesn't include
    # the pose anims, the SpecialStandby handshake can fail to resume AI,
    # leaving the enemy frozen even though the player was detected.
    #
    # Affected handlers (high call counts, big impact):
    #   90005200 (17 calls) — area-trigger wake from special standby
    #   90005201 (51 calls) — radius-trigger wake (largest impact)
    #   90005211 (15 calls) — combined area+radius
    #   90005221 (3 calls)  — damage-only trigger
    #
    # Fix: insert EnableCharacterAI right after SetSpecialStandbyEndedFlag,
    # which is the wake-confirm step. Surgical and safe — vanilla AI was
    # already going to resume, so the redundant call is a no-op there;
    # for randomized swaps it forces resumption regardless of anim handshake.
    pattern_d = r'(SetSpecialStandbyEndedFlag\(chrEntityId, ON\);)'
    repl_d = (r'\1\r\n    EnableCharacterAI(chrEntityId);'
              r'\r\n    SetNetworkUpdateRate(chrEntityId, true, '
              r'CharacterUpdateFrequency.AlwaysUpdate);')
    for evid in (90005200, 90005201, 90005211, 90005221):
        content, n = replace_in_event(content, evid, pattern_d, repl_d)
        total += n

    return content, total


# v0.24.100: disable_corpse_collision RETIRED.
# Empirically not working — playtest confirmed corpses still occasionally
# blocked SoG spawns even with the patch loaded. Meanwhile death_timeout
# (which forces the boss-dead branch to fire after 5s regardless of
# death-anim completion) DOES reliably force SoG spawn in practice,
# including in cases where the boss spawned frozen and never took damage.
# The standalone redundant DisableCharacterCollision call wasn't pulling
# its weight. If body-blocked-SoG recurs, investigate why death_timeout's
# cleanup path isn't reaching DisableCharacterCollision rather than
# reviving this patch.


@register('boss_clear_watchdog')
def patch_boss_clear_watchdog(content, filename):
    """Force-resolve boss encounters when AI is frozen and player can't deal
    enough damage to drop HP to 0.

    Symptom this fixes:
        - Boss spawns, healthbar appears, encounter is "active" — but boss AI
          is frozen (no attacks, no tracking, sometimes invulnerable to damage)
        - Player is locked into the arena indefinitely, can't progress the day
        - Concrete case: v0.23.72-playtest, c8300 Dragonslayer Armor as Night 1
          boss at m49_29, AI froze and fight could not be completed
    Cause: Encounter handlers (90015000 + variants) gate completion on
    chr2 = CharacterRatioDead(chrEntityId) — boss HP must reach 0%. If the
    boss can't take damage or refuses to engage, this never fires. The wake
    path may also have similar issues, but our permissive_boss_wake patch
    already addresses those.
    Fix: Append an OR-clause to chr2 such that the predicate also passes when
    the player has been in arena range for BOSS_CLEAR_TIMEOUT_SECONDS
    (default 300s = 5 min). Real boss fights complete well within this; only
    truly stuck encounters trigger the timeout. HandleMinibossDefeat fires
    normally from the existing `if (chr2.Passed)` branch, so reward chain and
    day-advance work as expected.

    Belt-and-suspenders companion to death_timeout (which handles "boss is
    dead but death animation hangs"). This patch handles "boss never dies."

    Tunable: set BOSS_CLEAR_TIMEOUT_SECONDS at the top of this function.

    Only applies to common_func.emevd.dcx.js. Patches all 5 encounter event
    variants in one pass since they share identical predicate syntax.
    """
    if not filename.startswith('common_func'):
        return content, 0

    BOSS_CLEAR_TIMEOUT_SECONDS = 300  # 5 minutes — tune this if needed

    # All encounter events that follow the chr2 = CharacterRatioDead pattern.
    # Each has been verified to use identical syntax for the line we're
    # patching (chr2 = CharacterRatioDead(chrEntityId);).
    #   90015000: named boss / miniboss encounter (post-permissive_boss_wake)
    #   90015007: variant with additional area param
    #   90015021: variant with eventFlagId3 (some duos)
    #   90015023: night boss (1-4 chr support — the duo/trio NB arenas)
    #   90015026: small-arena variant (Evergaol/Walking Mausoleum)
    total = 0
    for evid in (90015000, 90015007, 90015021, 90015023, 90015026):
        # The exact target line, with allowance for leading whitespace.
        pattern = r'chr2 = CharacterRatioDead\(chrEntityId\);'
        # Replace with multi-line OR predicate. The ElapsedSeconds counter
        # starts when chr2 is first evaluated (i.e., when WaitFor on the
        # containing chrAreaFlag begins), which is after healthbar setup —
        # so effectively this counts from "fight started."
        replacement = (
            f'chr2 = CharacterRatioDead(chrEntityId)\r\n'
            f'        || (EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1)\r\n'
            f'            && ElapsedSeconds({BOSS_CLEAR_TIMEOUT_SECONDS}));'
        )
        content, n = replace_in_event(content, evid, pattern, replacement)
        total += n
    return content, total


# v0.24.78: preboss_wake_timeout RETIRED. The patch's defensive value is
# now redundant (v0.24.70 fixed the original Tricephalos root cause via
# anim_compat-at-demotion mirror; v0.24.74 nb_speffect_wait_timeout
# covers the NB-arena variant; boss_clear_watchdog covers the spawned-
# but-frozen variant). Meanwhile the patch's 90s timeout was firing in
# EVERY expedition, in EVERY encounter event registered via
# InitializeCommonEvent (including m60 Limveld field bosses) — causing
# (a) field-boss map icons to reveal on Day 1 instead of Day 2 and
# (b) spurious healthbar flickering when the L0 RestartEvent cycle ran.
# Function body kept for reference; @register removed so it doesn't
# get picked up by the apply pipeline.
def patch_preboss_wake_timeout(content, filename):
    """Force-progress past the outer wake check when the wave-trigger
    chr fails to load.

    Symptom this fixes:
        - Night Boss arena: player enters, but the preboss wave never
          fires. Boss never spawns. Player is stuck in the arena with
          no enemies to fight and no way to progress.
        - Distinct from "boss spawned but AI is frozen" (boss_clear_
          watchdog handles that case). This is "boss never spawned in
          the first place."
        - Confirmed seed 388677 v0.24.69 Tricephalos path: wave failed
          to fire at NB1 (m49_29 or m49_24). v0.24.70 likely fixes the
          root cause via anim_compat-at-demotion mirror; this patch is
          the belt-and-suspenders safety net for any future "boss
          never spawned" case we haven't predicted.

    Cause: each encounter event (90015000 + variants) opens with
        WaitFor(chrHpAreaFlag);   // or chrAreaFlag
    where the flag is built from:
        chrXxxFlag |= chrXxxArea || chr;
    Both chrXxxArea and chr query state on `chrEntityId` — the wave-
    trigger chr. If chrEntityId's chr file fails to load (asset/anim
    mismatch from a rando swap), all queries on it return false. The
    OR predicate never fires. The event stalls indefinitely on the
    outer WaitFor.

    Note: the existing boss_clear_watchdog timeout fires INSIDE the L0
    loop, which only runs AFTER the outer WaitFor passes — i.e., AFTER
    boss healthbars are set up. If we never reach the L0 loop, that
    timeout is dead code for this scenario.

    Fix: append `|| ElapsedSeconds(PREBOSS_WAKE_TIMEOUT_SECONDS)` to
    the chrXxxFlag composition. After N seconds (90 default), the
    outer WaitFor force-fires, and the event proceeds to healthbar
    setup + L0 loop. Inside L0:
      - If chrEntityId still hasn't loaded, `!area` clause in
        chrAreaTimeFlag fires immediately (player "not in range" of
        non-existent chr), and the event RestartEvent()s back to the
        top. Net effect: every PREBOSS_WAKE_TIMEOUT_SECONDS, healthbars
        flicker on/off. Annoying but recoverable — beats permanently
        stuck.
      - If chrEntityId loads late, normal flow resumes after that.
      - If chrEntityId never loads AND the encounter has a non-zero
        eventFlagId2 early-exit flag, the outer EndIf passes that
        branch and the event ends cleanly.

    Tunable: set PREBOSS_WAKE_TIMEOUT_SECONDS at the top of this
    function. Default 90s: long enough that normal slow wake (5-15s)
    never trips it, short enough that broken encounters resolve in
    under ~7 minutes worst-case (90s outer + 300s inner watchdog).

    Only applies to common_func.emevd.dcx.js. Patches all 5 encounter
    event variants using a single regex with optional `Hp` capture
    group, matching both chrAreaFlag (90015007/021/023/026) and
    chrHpAreaFlag (90015000, post-permissive_boss_wake naming).
    """
    if not filename.startswith('common_func'):
        return content, 0

    PREBOSS_WAKE_TIMEOUT_SECONDS = 90  # bail-out wait — tune as needed

    # Pattern matches both naming variants:
    #   chrAreaFlag |= chrArea || chr;        (events 90015007/021/023/026)
    #   chrHpAreaFlag |= chrHpArea || chr;    (event 90015000)
    # Captures the flag/area var prefix so the replacement reuses it.
    pattern = (
        r'(chr(?:Hp)?AreaFlag) \|= (chr(?:Hp)?Area) \|\| chr;'
    )
    replacement = (
        rf'\1 |= \2 || chr || ElapsedSeconds({PREBOSS_WAKE_TIMEOUT_SECONDS});'
    )
    total = 0
    for evid in (90015000, 90015007, 90015021, 90015023, 90015026):
        content, n = replace_in_event(content, evid, pattern, replacement)
        total += n
    return content, total


@register('nb_speffect_wait_timeout')
def patch_nb_speffect_wait_timeout(content, filename):
    """v0.24.74: Add a 10s fallback timer to WaitFor(CharacterHasSpEffect(...))
    in Night Boss arena scripts.

    Symptom this fixes:
        - NB encounter enters fine, boss healthbar appears, boss is fightable
          — but the "preboss wave" or "phase 2 transition" or "paired-chr
          enable" never fires. Encounter is broken or incomplete.
        - Confirmed seed 407417 v0.24.73 at m49_29: Erdtree Avatar
          substituted for Demi-Human Queen at pi=16. Wave grunts inside the
          arena never activated. The boss intro played but the chain that
          spawns the second wave never advanced.

    Cause: vanilla NR's NB arena scripts gate wave/phase chains on
        WaitFor(CharacterHasSpEffect(chrEntityId, <speffect>));
    where <speffect> (10583, 13744, 13731, 5030, 44100, 42030, 42031, ...)
    is applied by the original boss chr's AI behavior tree at a specific
    state transition — typically "combat engaged" or "phase X reached".

    When the rando substitutes a different chr at that slot (Erdtree Avatar
    instead of Demi-Human Queen, Romina instead of Swordmaster Onze, etc.),
    the substituted chr's AI doesn't apply the expected SpEffect. The
    WaitFor blocks forever.

    Important: this is FUNDAMENTALLY DIFFERENT from anim_class mismatch.
    The boss is fightable — anim works, combat works, healthbar works. It's
    just that the wave/phase-progression chain is gated on a SpEffect that
    only vanilla AI applies. No amount of anim_class filtering catches it
    because it's not an anim issue.

    Fix: append `|| ElapsedSeconds(N)` to each affected WaitFor. Vanilla NR
    itself uses this exact pattern in common_func $Event(90015163) with
    N=9s ("WaitFor(CharacterHasSpEffect(chrEntityId, 45832) || ElapsedSeconds(9))")
    — direct precedent that timeout-fallback is a valid mechanic for
    SpEffect-gated waits. We use N=10s as the default, biased toward "fire
    quickly" since the only cost of a too-short timeout is occasionally
    firing the wave before a slow-applying SpEffect (rare, recoverable).

    Scope:
        - common_func.emevd.dcx.js: events 90065040, 90065041 (the
          wave-enabler / partner-related events called from m49_29)
        - m48_00, m48_20, m48_30, m48_50, m48_60, m48_90, m49_29
          (every m48_*/m49_* file with CharacterHasSpEffect waits)
        - m49_42 SKIPPED: its waits target entity 20000 = player, those
          are legitimate "player has buff" checks, not encounter gates

    Skips per-line:
        - Lines already containing `ElapsedSeconds` (already-timed-out,
          either vanilla precedent or earlier patch run)
        - Lines where the WaitFor targets entity 20000 (player) — those
          are buff/status checks, not encounter progression
        - Lines without `WaitFor(` wrapper — bare conditional checks in
          if/EndIf statements are different mechanics, leave them alone

    Tunable: SPEFFECT_WAIT_TIMEOUT_SECONDS at top of function.
    """
    import re as _re

    SPEFFECT_WAIT_TIMEOUT_SECONDS = 10

    # Determine if this file is in scope.
    # common_func gets event-scoped patching; m48/m49 files get whole-file.
    if filename.startswith('common_func'):
        scope = 'common_func'
    elif _re.match(r'^m4[89]_\d+_\d+_\d+\.', filename):
        # m48_XX_XX_XX or m49_XX_XX_XX
        scope = 'per_map'
    else:
        return content, 0

    def _patch_line(line):
        """Return (new_line, n_subs) for a single line."""
        # Match `    WaitFor(<expr>);<trailing>` with leading whitespace.
        # The <expr> must contain CharacterHasSpEffect but NOT ElapsedSeconds.
        m = _re.match(r'^(\s*)WaitFor\((.+)\);(\s*)$', line)
        if not m:
            return line, 0
        prefix, expr, suffix = m.group(1), m.group(2), m.group(3)
        if 'CharacterHasSpEffect' not in expr:
            return line, 0
        if 'ElapsedSeconds' in expr:
            return line, 0  # already has timeout — skip
        # Skip player-buff waits (entity 20000 explicit reference)
        if _re.search(r'CharacterHasSpEffect\(\s*20000\b', expr):
            return line, 0
        # Compose the replacement. If expr is already a parenthesized
        # group, don't double-wrap; otherwise wrap to keep operator
        # precedence correct (|| binds looser than &&).
        if expr.startswith('(') and expr.endswith(')'):
            new_expr = f'{expr} || ElapsedSeconds({SPEFFECT_WAIT_TIMEOUT_SECONDS})'
        else:
            new_expr = f'({expr}) || ElapsedSeconds({SPEFFECT_WAIT_TIMEOUT_SECONDS})'
        return f'{prefix}WaitFor({new_expr});{suffix}', 1

    if scope == 'common_func':
        # Patch only events tied to NB arena chains.
        # 90065040 / 90065041: wave-enabler + partner events for m49_29.
        EVENT_IDS = (90065040, 90065041)
        total = 0
        for evid in EVENT_IDS:
            start, end, body = get_event_body(content, evid)
            if body is None:
                continue
            # Split preserving CRLF — emevd files use \r\n.
            new_lines = []
            ev_count = 0
            for line in body.split('\n'):
                # Each line may have trailing \r from CRLF; preserve it.
                if line.endswith('\r'):
                    base = line[:-1]
                    new_base, n = _patch_line(base)
                    new_lines.append(new_base + '\r')
                else:
                    new_base, n = _patch_line(line)
                    new_lines.append(new_base)
                ev_count += n
            new_body = '\n'.join(new_lines)
            if ev_count > 0:
                content = content[:start] + new_body + content[end:]
                total += ev_count
        return content, total

    else:  # per_map
        # Process every line in the file. Lines that don't match the
        # WaitFor(CharacterHasSpEffect(...)) pattern are passed through
        # untouched by _patch_line.
        new_lines = []
        total = 0
        for line in content.split('\n'):
            if line.endswith('\r'):
                base = line[:-1]
                new_base, n = _patch_line(base)
                new_lines.append(new_base + '\r')
            else:
                new_base, n = _patch_line(line)
                new_lines.append(new_base)
            total += n
        return '\n'.join(new_lines), total



# v0.24.100: boss_reward_inject RETIRED.
# Pivoting to engine-side handling: oops_v3 will (a) gate boss-having
# source slots to boss-having targets only, and (b) a regulation.bin
# edit adds boss-reward configuration to chrs that should have one but
# currently don't. That approach is more precise than the common_func
# blanket-inject (which had known issues: potential double-fire on
# vanilla per-map dungeon bosses, empty pickers on under-configured
# swap-ins, no path to fix the latter at EMEVD layer).
# The HandleMinibossDefeat call site catalog is still recoverable from
# git history of this file at v0.24.99 if needed for reference.


@register('post_intro_aggro_kick')
def patch_post_intro_aggro_kick(content, filename):
    """v0.24.104: Force a fresh AI re-plan after the proximity-wake
    EnableCharacterAI in the 90005250/251/260/261/271 family, so
    substituted bosses whose intrinsic entrance animation completes but
    leaves the AI stuck in Recognition/Alert get kicked back to active
    Combat.

    Symptom this fixes:
        - At a proximity-wake-with-DisableAI slot, a substituted chr
          plays its intrinsic entrance animation to completion (you SEE
          the emerge / fly-in / rise-up), boss healthbar appears, then
          chr just stands in combat-ready idle and never engages.
          Walking around it or hitting it sometimes wakes it.
        - Confirmed v0.24.104 playtest: Magma Wyrm (c4911) substituted
          for Guardian Golem (Cathedral) (c4660) at m38_00 pi=51.
          Magma Wyrm's emerge_from_ground intrinsic anim plays cleanly,
          healthbar appears (90015000 wake gate fires on Recognition),
          then the dragon stays in idle and never attacks.
        - Distinct from the c4490 Jar Warrior / c3100 Bell Bearing
          Hunter cases in dev/WONTFIX.md: those are about NB-anchor
          scripted intros that never fire. This case is about chrs
          whose intrinsic intro DOES fire (and completes) but whose
          post-intro AI plan resolves to "wait" instead of "attack."

    Cause: 90005250/251/260/261/271 are the proximity-wake-with-AI-
    disable handlers. They DisableCharacterAI at boot, wait for player
    proximity (or damage / state / SpEffect), then EnableCharacterAI.
    For the vanilla chr at the slot, EnableCharacterAI followed by
    "play intro anim → transition to combat" works because that chr's
    behavior tree was authored against this exact harness. A
    substituted chr with its own intrinsic entrance animation plays
    the intro fine, but the post-intro escalation to Combat doesn't
    survive the disable-at-boot; the behavior tree settles into a
    stable Recognition or Alert plan with no path to Combat.

    Fix: after the terminal EnableCharacterAI(chrEntityId), inject
        WaitFixedTimeSeconds(POST_INTRO_WAIT_SECONDS);
        RequestCharacterAIReplan(chrEntityId);

    - The wait gives any intrinsic entrance animation time to play
      through (Magma Wyrm emerge ~4s; default 5s covers it with margin).
      Replan during an intro would visually snap the chr out of the
      animation — bad UX, so we wait first.
    - RequestCharacterAIReplan forces the behavior tree to discard its
      current plan and re-evaluate with fresh perception. Player is in
      radius (we just woke via proximity), so the new plan resolves to
      "engage player" → chr aggros.
    - Vanilla precedent for ForceAnimationPlayback → replan as a
      "guarantee re-engage after scripted anim" idiom: common_func
      $Event(90065009) at lines 9917-9918.

    Idempotent for vanilla chrs: a chr already in active Combat after
    its vanilla intro re-evaluates and stays in Combat. No visible
    behavior change for the vanilla case.

    Scope: only common_func.emevd.dcx.js. Patches all five handlers
    even though only one current call site is a true boss (38000850
    Cathedral Guardian Golem at m38_00 line 63). The other call sites
    are mob ambushes (m38_10 cathedral interior 90005250 family, m60
    tile-wakes for 90005261) — same handler shape, same potential
    failure mode if a substitute boots into a stuck Recognition state.
    Mob ambushes already aggro'd correctly hit the replan as a no-op.

    Tunable: POST_INTRO_WAIT_SECONDS at top of function. Bumping it
    higher delays the safety net for broken cases at the cost of
    longer dead time for already-active chrs (invisible — they're
    fighting). Lower risks interrupting still-playing intro anims.
    """
    if not filename.startswith('common_func'):
        return content, 0

    POST_INTRO_WAIT_SECONDS = 5  # Magma Wyrm emerge ~4s; default has margin

    # Match the terminal `    EnableCharacterAI(chrEntityId);` line + the
    # closing `});` of the event. Anchoring on the closing braces ensures
    # we only patch the LAST EnableCharacterAI in the handler (the
    # post-wake one), not any intermediate calls. The handler bodies
    # use `chrEntityId` as the explicit parameter name, so this is also
    # the discriminator against unrelated EnableCharacterAI calls in
    # other events.
    pattern = r'    EnableCharacterAI\(chrEntityId\);\r?\n\}\);'
    replacement = (
        '    EnableCharacterAI(chrEntityId);\r\n'
        f'    WaitFixedTimeSeconds({POST_INTRO_WAIT_SECONDS});\r\n'
        '    RequestCharacterAIReplan(chrEntityId);\r\n'
        '});'
    )
    total = 0
    for evid in (90005250, 90005251, 90005260, 90005261, 90005271):
        content, n = replace_in_event(content, evid, pattern, replacement)
        total += n
    return content, total


# ============================================================================
# nb_wave_bypass (v0.24.105) — RETIRED in v0.24.106
# ============================================================================
# Retired because the architecture was wrong: the new $Event(99055100) is
# Default mode, registered via $InitializeCommonEvent in each per-map Event(0).
# That means it fires ONCE AT MAP LOAD, which sets the bypass flag at map
# load, which releases the XXXX2810 WaitFor at map load — spawning the boss
# the instant the player enters the arena. The intended semantic was "fire
# only as a recovery action triggered by a watcher" but I never built the
# watcher, and Default-mode registration short-circuits straight to fire.
#
# The actual symptom this was meant to fix (N2 minion wave not starting) is
# better addressed by adding a timeout to the WaitFor itself — same pattern
# as nb_speffect_wait_timeout and preboss_wave_timeout. See the new
# xxxx2810_trigger_timeout patch below.
#
# Function body kept for reference. data/nb_wave_bypass_flags.json and
# dev/build_nb_wave_bypass_flags.py are dormant — neither is read at patch
# time anymore. Leaving them in the tree so the design discussion (which
# flag-slot pattern is empirically free across all NB arenas, etc.) isn't
# lost; if a future watcher-based architecture revives the bypass approach,
# the picker and data file are still good.
# ============================================================================

# The new common_func event that the nb_wave_bypass patch injects. Defined as a
# module-level constant so tests can assert on its exact body and the patch
# can render it with the right line endings without juggling escaped strings.
_NB_WAVE_BYPASS_EVENT_BODY = (
    '\r\n'
    '$Event(99055100, Default, function(bypassFlag, guardFlag) {\r\n'
    '    EndIf(EventFlag(guardFlag));\r\n'
    '    SetNetworkconnectedEventFlagID(guardFlag, ON);\r\n'
    '    SetNetworkconnectedEventFlagID(bypassFlag, ON);\r\n'
    '});\r\n'
)


def _load_nb_wave_bypass_flags():
    """Load data/nb_wave_bypass_flags.json relative to this file. Returns the
    `arenas` dict mapping stem → {event_id, bypass_flag, guard_flag}. Raises
    FileNotFoundError with a clear message if the data file is missing —
    callers can decide whether to skip the patch or fail loudly."""
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'data', 'nb_wave_bypass_flags.json')
    if not os.path.exists(path):
        raise FileNotFoundError(
            f'nb_wave_bypass requires {path}. Generate it via:\n'
            f'  python dev/build_nb_wave_bypass_flags.py <vanilla_js_dir>')
    with open(path, encoding='utf-8') as f:
        return json.load(f)['arenas']


def patch_nb_wave_bypass(content, filename):
    """v0.24.105 (RETIRED v0.24.106): Architect a hookable, idempotent "start
    the preboss wave"
    path for every NB arena, via three coordinated edits:

    Symptom this fixes:
        - Night 2 preboss wave fails to start. Arena is empty / stuck — no
          boss spawn, no wave grunts. Player has no fight to engage and no
          clean exit. nb_speffect_wait_timeout and preboss_wave_timeout
          handle two specific stall points; this addresses the case where
          neither of those timeouts is the bottleneck — the per-arena
          XXXX2810 handler's outer gate (WaitFor(EventFlag(eventFlagId3)))
          never releases, so its boss-spawn / wave-spawn body never runs.

    Background — the gate:
        Every NB arena has a per-map $Event(XXXX2810) handler that, after a
        boss-dead early-exit, sits at `WaitFor(EventFlag(eventFlagId3));`
        and only then proceeds to wake the boss, fire the wave (m49_29's
        SFX burst on 49290811-822, m48_XX's EnableGenerator), and show the
        healthbar. The eventFlagId3 parameter is supplied via a parameter
        substitution mechanism that is NOT statically recoverable from the
        binaries — XXXX2810 is never explicitly $InitializeEvent'd anywhere
        I could find (searched every instruction in every per-map and in
        common_func, zero hits on the 4XXX2810 pattern). DarkScript3
        renders the param name from EMEDF type hints applied to the
        parameter substitution table shape, but the actual runtime value
        source is opaque.

    Architecture:
        Instead of trying to fire vanilla's eventFlagId3, we introduce a
        NEW per-arena bypass flag and OR it into the existing WaitFor
        predicate. Each arena gets two flags from its private range:
            bypass_flag = prefix*1000+290   (e.g. 48000290 for m48_00)
            guard_flag  = prefix*1000+291
        The picks are written to data/nb_wave_bypass_flags.json by
        dev/build_nb_wave_bypass_flags.py, which asserts the XXX029X slot
        is empty in every scanned arena.

        Three coordinated edits per arena:

        (1) Common-func: inject the idempotent "start wave" function once.
            $Event(99055100, Default, function(bypassFlag, guardFlag) {
                EndIf(EventFlag(guardFlag));                    // already fired
                SetNetworkconnectedEventFlagID(guardFlag, ON);  // claim atomically
                SetNetworkconnectedEventFlagID(bypassFlag, ON); // release WaitFor
            });

            Network-connected flag operations ensure only one of the 3
            session clients claims the slot, so multiplayer can't double-fire.

        (2) Per-map XXXX2810: widen the gate WaitFor to accept the bypass.
            WaitFor(EventFlag(eventFlagId3));
              -->
            WaitFor(EventFlag(eventFlagId3) || EventFlag(<bypass>));

            Same family of WaitFor-widening as nb_speffect_wait_timeout and
            preboss_wave_timeout — append an OR-clause that's normally OFF
            but can be force-set to release the gate.

        (3) Per-map Event(0): register the function with arena-specific args.
            $InitializeCommonEvent(0, 99055100, <bypass>, <guard>);
            Injected just before Event(0)'s closing `});`.

    Idempotency properties:
        - 99055100's EndIf(EventFlag(guardFlag)) makes repeat calls free
        - SetNetworkconnectedEventFlagID claims the slot atomically — a
          peer client running the same event sees the flag set and exits
        - Vanilla path firing first: eventFlagId3 fires through normal
          NR flow, WaitFor releases on it, bypass flag stays clear, our
          99055100 is never invoked (no watcher triggers it).
        - Forced path firing first: 99055100 sets the bypass flag, WaitFor
          releases on the OR clause, vanilla eventFlagId3 may still fire
          later but XXXX2810 has already passed the WaitFor — harmless.
        - Re-running the patcher: regex in (2) won't re-match a line
          already containing `|| EventFlag(`; (3)'s injected
          InitializeCommonEvent line is detected by a stem-keyed grep
          before re-injection; (1) checks for the 99055100 event marker.

    Scope:
        - common_func.emevd.dcx.js: appends event 99055100 (one-time)
        - 25 NB arena per-map files (m48_00..m48_90, m49_10/17/18/19/20/
          21/23/24/25/26/27/28/29/30/90 — the set in
          data/nb_wave_bypass_flags.json). m49_40 and m49_42 don't have
          XXXX2810 events and are not patched.

    What this does NOT do:
        - Decide WHEN to call 99055100. The patch makes the call POSSIBLE
          and idempotent. The watcher that actually invokes it under
          failure-recovery conditions (e.g. EventFlag(7530) ON + buffer
          delay, or hard timeout on a sibling signal) is a separate piece
          of work and is intentionally not bundled here so the watcher
          policy can evolve independently of the wiring.
        - Help arenas where the failure is upstream of XXXX2810 entirely
          (e.g. the boss chr file fails to load). Those are CTD-shaped
          failures, not stall-shaped.
    """
    arenas = _load_nb_wave_bypass_flags()

    if filename.startswith('common_func'):
        # Edit (1): inject the idempotent start-wave event once.
        if '$Event(99055100,' in content:
            return content, 0  # already injected
        # Append at end of file (after the last event's closing `});`).
        return content + _NB_WAVE_BYPASS_EVENT_BODY, 1

    # Per-map file path. The filename here is the bare filename like
    # "m48_00_00_00.emevd.dcx.js". The data file is keyed by stem
    # "m48_00_00_00" — strip both possible suffixes.
    stem = filename
    for suffix in ('.emevd.dcx.js', '.emevd.js', '.dcx.js', '.js'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break

    if stem not in arenas:
        return content, 0  # not an NB arena we care about

    info = arenas[stem]
    event_id = info['event_id']
    bypass = info['bypass_flag']
    guard  = info['guard_flag']

    total = 0

    # Edit (2): widen the XXXX2810 WaitFor.
    # Pattern: WaitFor(EventFlag(eventFlagId3));  (with leading whitespace)
    # Replacement appends the bypass OR clause. Idempotent: lines already
    # containing `|| EventFlag(` won't re-match.
    waitfor_pattern = r'WaitFor\(EventFlag\(eventFlagId3?\)\);'
    waitfor_replace = f'WaitFor(EventFlag(eventFlagId3) || EventFlag({bypass}));'
    content, n = replace_in_event(content, event_id, waitfor_pattern, waitfor_replace)
    total += n

    # Edit (3): inject the InitializeCommonEvent into Event(0).
    # Insertion point: just before Event(0)'s closing `});`.
    # Idempotent: skip if the line is already present anywhere in Event(0).
    init_line = f'    $InitializeCommonEvent(0, 99055100, {bypass}, {guard});'
    ev0_start, ev0_end, ev0_body = get_event_body(content, 0)
    if ev0_body is None:
        # No Event(0) in this file — unusual but possible. Skip injection.
        return content, total
    if f'99055100, {bypass}, {guard}' in ev0_body:
        return content, total  # already injected
    # Find the LAST `});` in Event(0)'s body. The body string includes the
    # closing `});`. Insert our new line just before it, preserving CRLF.
    closing_match = re.search(r'\}\);\s*$', ev0_body)
    if not closing_match:
        # Couldn't find a clean closing — bail rather than corrupt the file.
        return content, total
    insert_at = ev0_start + closing_match.start()
    # Use CRLF to match the surrounding file's line endings (DarkScript3 emits CRLF).
    new_content = content[:insert_at] + init_line + '\r\n' + content[insert_at:]
    return new_content, total + 1


# ============================================================================
# xxxx2810_trigger_timeout (v0.24.106)
# ============================================================================


@register('xxxx2810_trigger_timeout')
def patch_xxxx2810_trigger_timeout(content, filename):
    """v0.24.106: Add a 90s safety-net timeout to the `WaitFor(EventFlag(
    eventFlagId3))` gate in each NB arena's $Event(XXXX2810).

    Symptom this fixes:
        - "Circle closes, nothing visible. No minion wave, no boss." The
          arena loads, the night phase activates, and then nothing happens.
          The expected flow — circle closes → minion wave spawns → boss
          spawns (gated on all-minions-dead or vanilla's intra-fight
          timeout) — stalls at the first transition.

    Where the stall lives:
        Every NB arena has a per-map $Event(XXXX2810) — the boss-wake-and-
        wave handler. After a boss-already-dead early-exit, it sits at
            WaitFor(EventFlag(eventFlagId3));
        and only then proceeds to wake the boss (anim 20001), enable the
        preboss anchor entity, fire the wave (m48_XX uses
        EnableGenerator(48003800); m49_29 uses a 12-grunt SFX burst gated
        further downstream by CharacterHasSpEffect(boss, 10583)), and
        display the healthbar.

        `eventFlagId3` is supplied via a parameter substitution mechanism
        we can't statically recover from the binaries — XXXX2810 is never
        explicitly $InitializeEvent'd anywhere I could find. In vanilla
        the trigger does fire reliably, but in a randomizer build with
        substituted chrs / non-vanilla MSB layout the upstream chain can
        break in ways that leave eventFlagId3 unset indefinitely. Without
        a timeout the WaitFor just hangs and the player gets an empty
        arena.

    What this patch does:
        Append `|| ElapsedSeconds(90)` to the WaitFor predicate so the
        gate releases after 90s if the vanilla trigger doesn't fire:

            WaitFor(EventFlag(eventFlagId3));
              -->
            WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));

        Same family as nb_speffect_wait_timeout (10s on
        CharacterHasSpEffect waits) and preboss_wave_timeout (90s on
        90015442's tile-night-phase waits). 90s matches the upstream
        preboss_wave_timeout value — chosen for consistency, not for
        any specific physical interpretation.

    Worst-case delivery latency:
        Vanilla path: WaitFor releases the moment eventFlagId3 fires.
        Fallback path: 90s after this WaitFor starts blocking. If the
        upstream preboss_wave_timeout (on 90015442) also has to fire its
        90s fallback, total worst-case wait from "circle closes" to
        "something visible in the arena" is 90 + 90 = 180s. Long but
        bounded — the player gets a fight to engage with eventually
        instead of an empty arena to stand in.

    Scope:
        - Per-map .emevd.dcx.js files matching m4[89]_NN_NN_NN
        - Within each, the line in $Event(XXXX2810) that matches the
          regex (typically exactly one match per file)
        - 25 files in vanilla NR (m48_00..m48_90 + m49_10/17/18/19/20/
          21/23/24/25/26/27/28/29/30/90). m49_40 and m49_42 don't have
          XXXX2810 events and are unaffected.

    Idempotency:
        - `'ElapsedSeconds' in expr` short-circuits re-runs
        - Tolerates the `WaitFor(EventFlag(eventFlagId3) || EventFlag(X))`
          shape left behind by retired-patch nb_wave_bypass artifacts: it
          adds the timeout to whatever flag-only predicate is there and
          leaves the result functional (a bit ugly, but the retired
          bypass flag is never set because 99055100 is unregistered, so
          the extra OR clause is dead weight, not a bug)

    What this does NOT do:
        - Solve a fundamental upstream stall (e.g. arena never receives
          the player teleport, MSB chr file fails to load). Those are
          CTD-shaped failures, not stall-shaped.
        - Address phase transitions inside the boss fight (e.g. m49_29's
          phase-2 trigger on EventFlag(8035) at ev49292920 line 263). If
          a midfight phase trigger stalls, that's a separate problem
          needing a different timeout target.
    """
    import re as _re

    # Per-map files only. common_func / common / other map ranges untouched.
    if not _re.match(r'^m4[89]_\d+_\d+_\d+\.', filename):
        return content, 0

    TIMEOUT = 90

    def _patch_line(line):
        """Return (new_line, n_subs) for a single line. The match is content-
        keyed on 'eventFlagId3' rather than a literal flag value because the
        WaitFor uses the parameter name from XXXX2810's signature."""
        m = _re.match(r'^(\s*)WaitFor\((.+?)\);(\s*)$', line)
        if not m:
            return line, 0
        prefix, expr, suffix = m.group(1), m.group(2), m.group(3)
        if 'eventFlagId3' not in expr:
            return line, 0
        if 'ElapsedSeconds' in expr:
            return line, 0  # already timed
        # Parenthesize the existing expression so `||` precedence is
        # unambiguous, then append the timeout clause.
        if expr.startswith('(') and expr.endswith(')'):
            new_expr = f'{expr} || ElapsedSeconds({TIMEOUT})'
        else:
            new_expr = f'({expr}) || ElapsedSeconds({TIMEOUT})'
        return f'{prefix}WaitFor({new_expr});{suffix}', 1

    new_lines = []
    total = 0
    for line in content.split('\n'):
        # Preserve CRLF endings (DarkScript3 emits CRLF).
        if line.endswith('\r'):
            base = line[:-1]
            new_base, n = _patch_line(base)
            new_lines.append(new_base + '\r')
            total += n
        else:
            new_base, n = _patch_line(line)
            new_lines.append(new_base)
            total += n
    return '\n'.join(new_lines), total


# ============================================================================
# nb_boss_force_enable_watchdog (v0.24.107)
# ============================================================================

# The list of (boss_800, head2_810) entity IDs we'll force-enable. Derived
# from the 25 NB arenas in data/nb_wave_bypass_flags.json. Stored as a
# module-level constant so it's testable and so the JSON doesn't get read
# at patch time (which would couple registration to file presence).
_NB_BOSS_ENTITY_IDS = (
    # (arena_stem, boss_main, boss_head2)
    ('m48_00_00_00', 48000800, 48000810),
    ('m48_10_00_00', 48100800, 48100810),
    ('m48_20_00_00', 48200800, 48200810),
    ('m48_30_00_00', 48300800, 48300810),
    ('m48_40_00_00', 48400800, 48400810),
    ('m48_50_00_00', 48500800, 48500810),
    ('m48_60_00_00', 48600800, 48600810),
    ('m48_70_00_00', 48700800, 48700810),
    ('m48_80_00_00', 48800800, 48800810),
    ('m48_90_00_00', 48900800, 48900810),
    ('m49_10_00_00', 49100800, 49100810),
    ('m49_17_00_00', 49170800, 49170810),
    ('m49_18_00_00', 49180800, 49180810),
    ('m49_19_00_00', 49190800, 49190810),
    ('m49_20_00_00', 49200800, 49200810),
    ('m49_21_00_00', 49210800, 49210810),
    ('m49_23_00_00', 49230800, 49230810),
    ('m49_24_00_00', 49240800, 49240810),
    ('m49_25_00_00', 49250800, 49250810),
    ('m49_26_00_00', 49260800, 49260810),
    ('m49_27_00_00', 49270800, 49270810),
    ('m49_28_00_00', 49280800, 49280810),
    ('m49_29_00_00', 49290800, 49290810),
    ('m49_30_00_00', 49300800, 49300810),
    ('m49_90_00_00', 49900800, 49900810),
)


def _build_force_enable_event_body(timeout_seconds=60, tracers=True):
    """Render the $Event(99055200) text body. Separated for testability —
    the test can call this and assert on exact content.

    v0.24.110 redesign: per-arena registration via $InitializeCommonEvent,
    armed on per-arena trigger flag.

    History of redesigns and why:
    - v0.24.107 (retired): armed on EventFlag(7530) globally. Failed
      because 7530's arming timing was unverified.
    - v0.24.108 (retired): wallclock + !CharacterDead(20000) at session
      level, no per-arena scope. Failed because !CharacterDead(20000) is
      true at character-select screen, so the timeout elapsed during
      menus/loading/N1 and the event finished its body long before the
      player ever reached N2. Tracer fired but in the wrong context;
      player didn't recognize the sound.
    - v0.24.110 (current): event takes (triggerFlag, bossEntity1,
      bossEntity2) parameters and is registered per-arena from each
      arena's Event(0). It blocks on the trigger flag (encounter-start
      signal we already control via vanilla 90015442 OR our arena-entry
      trigger), then runs the 60s timer from THAT moment. Correctly
      scoped to "this arena's encounter started" rather than "session
      has been running 60s."

    Structure:
    - Restart mode; Event(0) registers one instance per arena
    - Phase 1: WaitFor(EventFlag(triggerFlag)) — arm on encounter start
    - Phase 2: WaitFor(ElapsedSeconds(60)) — give vanilla time to win
    - Phase 3 tracer: PlaySE so player knows watchdog fired
    - Phase 4: force-enable that arena's boss entities (boss + head2)
    - Phase 5 tracer: post-fire confirmation
    - Phase 6: WaitFor(!EventFlag(triggerFlag)) — hold for encounter
      end (boss death OR map transition), then Restart re-arms
    """
    lines = [
        '',
        '$Event(99055200, Restart, function(triggerFlag, bossEntity1, bossEntity2) {',
        '    // nb_boss_force_enable_watchdog (v0.24.110)',
        '    //',
        '    // Per-arena force-enable recovery. Registered once per NB',
        '    // arena from that arena\'s Event(0), with (triggerFlag,',
        '    // bossEntity1, bossEntity2) bound to that arena\'s values.',
        '    //',
        '    // Arms on encounter-start (triggerFlag goes ON, via vanilla',
        '    // ring-close OR our nb_arena_entry_trigger). Waits',
        f'    // {timeout_seconds}s for vanilla flow to succeed. If still stuck,',
        '    // fires force-enable barrage on this arena\'s boss entities.',
        '',
        '    // Phase 1: arm on encounter-start.',
        '    WaitFor(EventFlag(triggerFlag));',
        '',
        f'    // Phase 2: give vanilla {timeout_seconds}s to succeed.',
        f'    WaitFor(ElapsedSeconds({timeout_seconds}));',
        '',
        '    // Phase 3 (audible): about to fire force-enable. If you hear',
        '    // this AFTER the trigger flag fired and BEFORE the boss',
        '    // appears, the recovery is engaging.',
    ]
    if tracers:
        lines.append('    PlaySE(20000, SoundType.SFX, 888880000);')
    lines.append('')
    lines.append('    // Phase 4: force-enable this arena\'s boss entity (and')
    lines.append('    // head2 for duo arenas). Idempotent: EnableCharacter on')
    lines.append('    // an already-enabled chr is a no-op; on a nonexistent')
    lines.append('    // entity is also a no-op.')
    lines.append('    EnableCharacter(bossEntity1);')
    lines.append('    EnableCharacterCollision(bossEntity1);')
    lines.append('    EnableCharacterAI(bossEntity1);')
    lines.append('    RequestCharacterAIReplan(bossEntity1);')
    lines.append('    EnableCharacter(bossEntity2);')
    lines.append('    EnableCharacterCollision(bossEntity2);')
    lines.append('    EnableCharacterAI(bossEntity2);')
    lines.append('    RequestCharacterAIReplan(bossEntity2);')
    lines.append('')
    lines.append('    // Phase 5 (audible): post-fire confirmation.')
    if tracers:
        lines.append('    PlaySE(20000, SoundType.SFX, 888880000);')
    lines.append('')
    lines.append('    // Phase 6: hold until encounter ends. Restart mode')
    lines.append('    // re-arms on the next encounter (next map / death).')
    lines.append('    WaitFor(!EventFlag(triggerFlag));')
    lines.append('});')
    lines.append('')
    # CRLF line endings to match DarkScript3 output
    return '\r\n'.join(lines)


@register('nb_boss_force_enable_watchdog')
def patch_nb_boss_force_enable_watchdog(content, filename):
    """v0.24.107: Add a force-enable recovery watchdog for stalled NB boss
    spawn chains.

    Symptom this addresses:
        N2 (or any NB) loads into an empty arena. The ring closes, the
        night-phase activates, but no boss appears, no wave fires, no
        healthbar shows. The xxxx2810_trigger_timeout (v0.24.106) added
        a 90s safety release to the eventFlagId3 gate, but in practice
        that hasn't been the failure point — something further upstream
        in the boss-init chain (e.g. 90065910 or 90065050 stalling on
        a sub-WaitFor we haven't traced, or the boss chr failing to
        instantiate after a substitution) leaves the boss in a disabled
        state that no per-arena event ever unstuck.

    What this does (v0.24.108 redesign):
        Adds a single common_func event $Event(99055200) registered in
        Restart mode. Body:

          - WaitFor(!CharacterDead(20000))  // player alive (out of loads)
          - WaitFor(ElapsedSeconds(60))     // 60s from map-load
          - PlaySE audible tracer           // listen for this in playtest
          - Force-enable barrage            // 25 arenas × 2 entities each
          - PlaySE audible tracer           // confirms barrage completed
          - WaitFor(CharacterDead(20000))   // hold for re-arm
          - (Restart mode auto-restarts on next life / map)

    v0.24.108 dropped the EventFlag(7530) arming gate present in
    v0.24.107: the 7530 hypothesis was plausible (it's network-synced
    and set by 90015020 per-arena) but unconfirmed at playtest, and
    using it created the failure mode "WaitFor(7530) blocks forever
    and watchdog never reaches its body." Wallclock arming is
    unconditional; audible tracers tell you the watchdog body
    actually executed.

    Why this approach (vs per-arena watchdogs or nb_wave_bypass-style
    OR-gate widening):
        - Self-contained in common_func; doesn't need per-map injection
        - Works for ANY arena, including DLC arenas the patch hasn't seen
        - The EnableCharacter calls for nonexistent entities are
          documented engine no-ops — wasted instructions, not bugs
        - Single recovery action covers all 25 NB arenas, including
          duo arenas where head2 (XXX00810) needs separate enable
        - Doesn't depend on knowing WHICH arena is active

    Why 60 seconds (was 120 in v0.24.107):
        - Vanilla wake chain completes within ~10s of arena-load on a
          working seed
        - 60s is long enough that working seeds finish first and the
          watchdog is silent, short enough that playtest doesn't burn
          two minutes per attempt
        - Tunable via _build_force_enable_event_body(timeout_seconds=N)

    Audible tracers (PlaySE on player @ entity 20000, SFX 888880000):
        - Fires immediately before the force-enable barrage and again
          after it completes
        - Useful for distinguishing failure modes:
          * Hear pre-fire tracer, boss appears → recovery worked
          * Hear pre-fire tracer, no boss → entity doesn't exist
            (chr load failure or different bug class)
          * Hear no tracer → watchdog never reached its body (event
            didn't compile, didn't deploy, or compiled wrong)
        - 888880000 is a debug-grade SFX ID vanilla uses internally;
          it'll be audible but unobtrusive
        - To disable: rebuild with _build_force_enable_event_body(
          tracers=False)

    Idempotency:
        - common_func is the only file touched
        - Skips injection if '$Event(99055200,' is already present

    Race conditions handled:
        - EnableCharacter on an already-enabled chr is a no-op
        - EnableCharacterAI on already-enabled AI is a no-op
        - RequestCharacterAIReplan mid-action may interrupt the chr
          briefly, but a working boss recovers within a frame; this is
          acceptable as a recovery-only cost
        - Restart mode: event re-arms after player death / map load

    Caveats / what this does NOT do:
        - Doesn't fire the wave-grunt SFX bursts (those are per-arena
          EMEVD downstream of the boss being alive; if the boss recovers
          via this watchdog, the wave chain should also reach via the
          xxxx2810_trigger_timeout fallback)
        - Doesn't set boss healthbar names (nameId is per-arena;
          per-arena XXXX2810 handles healthbar display once the boss
          is enabled and the chain progresses)
        - Doesn't trigger the boss intro animation (the boss will just
          stand up and start fighting; no cinematic entrance)
        - If the boss chr ID itself failed to load at MSB-parse time,
          force-enabling its entity ID does nothing — the entity has
          no associated chr. The arena will still be empty. This
          watchdog can't recover from chr-load failures, only from
          state-machine stalls.

    Scope: common_func.emevd.dcx.js only.
    """
    if filename.startswith('common_func'):
        if '$Event(99055200,' in content:
            return content, 0  # already injected
        # v0.25.0: tracers gated on PUBLISH_MODE. Recovery logic still
        # injects; only the audible PlaySE pre/post-barrage feedback
        # is suppressed for ship.
        body = _build_force_enable_event_body(
            timeout_seconds=60,
            tracers=not PUBLISH_MODE,
        )
        return content + body, 1

    # Per-map injection: register the watchdog with this arena's
    # (triggerFlag, bossEntity1, bossEntity2) values, adjacent to the
    # existing 90015442 InitializeCommonEvent line for indent matching.
    stem = filename
    for suffix in ('.emevd.dcx.js', '.emevd.js', '.dcx.js', '.js'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break

    nb_stems = {s for s, _, _ in _NB_BOSS_ENTITY_IDS}
    if stem not in nb_stems:
        return content, 0

    if 'InitializeCommonEvent(0, 99055200' in content:
        return content, 0  # already injected

    try:
        anchor, flag = _arena_entry_args(stem)
    except (ValueError, NameError):
        return content, 0

    # Find this arena's boss entities from the constant table
    boss1, boss2 = None, None
    for s, b1, b2 in _NB_BOSS_ENTITY_IDS:
        if s == stem:
            boss1, boss2 = b1, b2
            break
    if boss1 is None:
        return content, 0

    new_line = f'$InitializeCommonEvent(0, 99055200, {flag}, {boss1}, {boss2});'
    indent_pattern = r'^([ \t]*)(\$InitializeCommonEvent\(0, 90015442, \d+, \d+\);)'
    import re as _re
    m = _re.search(indent_pattern, content, _re.MULTILINE)
    if not m:
        return content, 0
    indent = m.group(1)
    replacement = m.group(0) + '\r\n' + indent + new_line
    new_content = _re.sub(indent_pattern, replacement, content, count=1, flags=_re.MULTILINE)
    return new_content, 1


# ============================================================================
# nb_arena_entry_trigger (v0.24.109)
# ============================================================================


_NB_ARENA_ENTRY_TRIGGER_RADIUS = 20  # meters; vanilla 90015442 uses 15m
_NB_ARENA_ENTRY_TRIGGER_EVENT_ID = 99055300


def _build_arena_entry_trigger_event_body(radius=_NB_ARENA_ENTRY_TRIGGER_RADIUS):
    """Render the $Event(99055300) common_func body. The event watches
    the player's proximity to an arena-center anchor and sets the
    arena's trigger flag (the same flag 90015442 sets after ring closure).
    Coexists idempotently with vanilla flow."""
    lines = [
        '',
        f'$Event({_NB_ARENA_ENTRY_TRIGGER_EVENT_ID}, Restart, function(anchorEntity, triggerFlag) {{',
        '    // nb_arena_entry_trigger (v0.24.109)',
        '    //',
        '    // Player-initiated arena trigger: when the player approaches',
        '    // the arena center, set the same trigger flag that vanilla',
        '    // 90015442 sets after ring closure. Lets players initiate the',
        '    // encounter early without waiting for the ring (and provides',
        '    // a backup path if the ring-close chain fails to fire).',
        '    //',
        '    // Idempotent in all interleavings:',
        '    //  - EndIf at top short-circuits if vanilla beat us',
        '    //  - EndIf after WaitFor handles race during proximity check',
        '    //  - SetNetworkconnectedEventFlagID on already-ON flag is a no-op',
        '',
        '    EndIf(EventFlag(triggerFlag));',
        f'    WaitFor(EntityInRadiusOfEntity(20000, anchorEntity, {radius}, 1));',
        '    EndIf(EventFlag(triggerFlag));',
        '    SetNetworkconnectedEventFlagID(triggerFlag, ON);',
        '});',
        '',
    ]
    return '\r\n'.join(lines)


# Per-arena (anchor_entity, trigger_flag) pairs derived from the vanilla
# 90015442 initialization pattern: arg1=anchor (XXX02200), arg2=flag (XXX00200).
# These match what existing per-arena Event(0) already passes to 90015442 —
# we register our 99055300 with the same args.
def _arena_entry_args(stem):
    """Derive (anchor_entity, trigger_flag) from arena stem.

    Pattern: prefix is the 3-or-4 digit arena code derived from the stem.
    - m48_40 → '484' → anchor 48402200, flag 48400200
    - m49_29 → '4929' → anchor 49292200, flag 49290200

    The math is: prefix is the digits of the stem excluding the trailing
    '_00_00', so 'm48_40_00_00' → '4840' → wait that's 4 digits. Let me
    reread my finding from grep output:

    From the grep evidence:
      m48_40_00_00.emevd: 90015442(48402200, 48400200)
      m49_29_00_00.emevd: 90015442(49292200, 49290200)

    So extract the numeric portion of the stem (m48_40 → 4840;
    m49_29 → 4929), then anchor = N*10000 + 2200, flag = N*10000 + 200.
    For 5-digit arena IDs (would never happen with m48/m49), same math
    works regardless of digit count.
    """
    import re as _re
    m = _re.match(r'm(\d+)_(\d+)_', stem)
    if not m:
        raise ValueError(f'unrecognized stem: {stem!r}')
    prefix = int(f'{m.group(1)}{m.group(2)}')   # m48_40 → 4840
    anchor = prefix * 10000 + 2200
    flag = prefix * 10000 + 200
    return anchor, flag


# Sanity-check the derivation against known cases at import time.
def _verify_arena_entry_args():
    for stem, expected_anchor, expected_flag in (
            ('m48_40_00_00', 48402200, 48400200),
            ('m48_60_00_00', 48602200, 48600200),
            ('m49_29_00_00', 49292200, 49290200),
            ('m49_30_00_00', 49302200, 49300200),
    ):
        anchor, flag = _arena_entry_args(stem)
        if (anchor, flag) != (expected_anchor, expected_flag):
            raise RuntimeError(
                f'_arena_entry_args sanity check failed for {stem}: '
                f'got ({anchor},{flag}) expected ({expected_anchor},{expected_flag})')
_verify_arena_entry_args()


@register('nb_arena_entry_trigger')
def patch_nb_arena_entry_trigger(content, filename):
    """v0.24.109: Add player-initiated arena trigger. Lets the player
    start an NB encounter by approaching the arena center, instead of
    waiting for the ring to close.

    Why this exists:
        - Recurring bug: some seeds load into N2 with the arena empty,
          no boss spawn, no minion wave. Diagnosis-in-progress (see
          nb_boss_force_enable_watchdog) suggests the upstream
          ring-close→trigger-flag chain doesn't reach some seeds. This
          patch adds a redundant trigger path so players can force
          the encounter start regardless of whether vanilla flow worked.
        - Quality-of-life: players who want to clear minion camps
          before engaging the boss can now do so on their own timing.

    What it does:
        - Adds a new common_func event $Event(99055300) that watches
          the player's proximity to an arena-center anchor (the
          XXX02200 entity passed to 90015442 in every NB arena).
          When the player enters a 20m radius, it sets the arena
          trigger flag (XXX00200), which is the same flag 90015442
          sets after ring closure.
        - Adds a per-arena $InitializeCommonEvent(0, 99055300, ...)
          to each NB arena's Event(0), wired with that arena's
          anchor and flag values.

    Why it's idempotent with vanilla:
        - The trigger flag set is the same target as the vanilla
          path. If vanilla beat us, our EndIf at the top of
          99055300 short-circuits. If we beat vanilla, vanilla's
          SetNetworkconnectedEventFlagID on the already-ON flag
          is a no-op.
        - SetNetworkconnectedEventFlagID is network-synced — works
          correctly in 3-player co-op without double-firing.

    Why this is layered with the watchdog (v0.24.107/108):
        - Watchdog is the backstop: timer-based, 60s after map load,
          fires force-enable barrage regardless of player input.
        - Entry trigger is player agency: encounter starts when
          player approaches.
        - Vanilla path is unchanged: ring closure still works
          when nothing else has fired first.
        - All three coexist idempotently. Whichever signal arrives
          first wins; the others see the flag already set and exit.

    Scope:
        - common_func.emevd.dcx.js: appends $Event(99055300) once.
        - 25 NB arena per-map files: injects one
          $InitializeCommonEvent(0, 99055300, anchor, flag) into
          each Event(0).
        - Other map files: untouched.

    Idempotency on patch re-run:
        - common_func: skip if '$Event(99055300,' already present.
        - per-map: skip if 'InitializeCommonEvent(0, 99055300' already
          present in the file.

    Caveats:
        - The 20m radius is empirical. Smaller risks the player walking
          past the anchor without triggering; larger risks pre-firing
          before they're really committed.
        - The anchor is an MSB Point at the arena center per vanilla
          convention. If a future game patch moves the anchor or
          changes the XXX02200 convention, the patch's flag-derivation
          will need updating. _verify_arena_entry_args() catches
          obvious regressions at import time.
        - This doesn't actually FIX the empty-arena bug — the boss
          still might not spawn after the flag is set. But it
          eliminates "ring failed to close" as a possible cause and
          gives the player a faster path to find out.
    """
    if filename.startswith('common_func'):
        if f'$Event({_NB_ARENA_ENTRY_TRIGGER_EVENT_ID},' in content:
            return content, 0
        return content + _build_arena_entry_trigger_event_body(), 1

    # Per-map injection
    stem = filename
    for suffix in ('.emevd.dcx.js', '.emevd.js', '.dcx.js', '.js'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break

    # Only inject in known NB arena per-map files
    nb_stems = {s for s, _, _ in _NB_BOSS_ENTITY_IDS}
    if stem not in nb_stems:
        return content, 0

    if f'InitializeCommonEvent(0, {_NB_ARENA_ENTRY_TRIGGER_EVENT_ID}' in content:
        return content, 0  # already injected

    try:
        anchor, flag = _arena_entry_args(stem)
    except ValueError:
        return content, 0

    # Inject after the existing 90015442 InitializeCommonEvent line, which
    # uses the same (anchor, flag) pair we need. That gives us guaranteed
    # placement inside Event(0) and adjacent to the analogous vanilla call.
    pattern = r'(\$InitializeCommonEvent\(0, 90015442, \d+, \d+\);)'
    new_line = f'$InitializeCommonEvent(0, {_NB_ARENA_ENTRY_TRIGGER_EVENT_ID}, {anchor}, {flag});'

    # Preserve the indentation of the existing line by capturing it
    indent_pattern = r'^([ \t]*)(\$InitializeCommonEvent\(0, 90015442, \d+, \d+\);)'
    import re as _re
    m = _re.search(indent_pattern, content, _re.MULTILINE)
    if not m:
        return content, 0  # arena doesn't have the 90015442 call; skip

    indent = m.group(1)
    replacement = m.group(0) + '\r\n' + indent + new_line
    new_content = _re.sub(indent_pattern, replacement, content, count=1, flags=_re.MULTILINE)

    return new_content, 1


# ============================================================================
# nb_arena_hold_trigger (v0.24.111)
# ============================================================================


_NB_ARENA_HOLD_TRIGGER_RADIUS = 25     # was 5m — too tight to find without visual; widened to ~half-arena
_NB_ARENA_HOLD_TRIGGER_HOLD_SEC = 3   # continuous hold duration
_NB_ARENA_HOLD_TRIGGER_EVENT_ID = 99055400


def _build_arena_hold_trigger_event_body(
        radius=_NB_ARENA_HOLD_TRIGGER_RADIUS,
        hold_seconds=_NB_ARENA_HOLD_TRIGGER_HOLD_SEC,
        tracers=True):
    """Render the $Event(99055400) common_func body.

    Mechanic: player stands within `radius` of the anchor for `hold_seconds`
    continuous seconds. On completion: visible+audible feedback (so the
    player KNOWS it triggered, eliminating "did it fire?" ambiguity) and
    set the arena trigger flag.

    v0.25.0: feedback (PlaySE + DisplayTextEffectId banner) is gated on
    the `tracers` parameter, threaded through from the module-level
    PUBLISH_MODE flag at the call site. When PUBLISH_MODE=True, the
    trigger logic still fires (flag still gets set) but the player gets
    no banner/SFX confirmation. Across 25 NB arenas with the v0.24.x
    radius widening (5m → 25m), the banner was firing per-arena and
    visually spamming "POWER GAINED" (DisplayTextEffectId 1020 maps to
    the boss-defeat banner in NR's FMG table). Tests continue to call
    with `tracers=True` explicitly.

    Why "hold" instead of "press E": pure EMEVD (no MSB asset edits needed)
    while still being unambiguously player-initiated (3 seconds of standing
    is a deliberate action). Press-E interactable deferred to future
    polish work — needs MSB Part + ObjAct entries + asset bundle loading,
    which is multi-day scope.

    Idempotency:
        - EndIf(EventFlag(triggerFlag)) at start: if vanilla beat us, exit
        - EndIf after hold completes: if vanilla fired during the hold,
          we'd duplicate the flag-set (no-op via SetNetworkconnectedEventFlagID)
          but waste a tracer/banner. Cheap to guard.
        - SetNetworkconnectedEventFlagID on already-ON: no-op anyway

    Hold cancellation:
        - The hold-WaitFor races ElapsedSeconds(3) against
          !EntityInRadiusOfEntity(...). If player leaves the radius before
          3s elapse, the OR-clause fires first; we EndIf out and Restart
          re-arms the event for the next attempt.
    """
    radius_check = f'EntityInRadiusOfEntity(20000, anchorEntity, {radius}, 1)'
    lines = [
        '',
        f'$Event({_NB_ARENA_HOLD_TRIGGER_EVENT_ID}, Restart, function(anchorEntity, triggerFlag) {{',
        '    // nb_arena_hold_trigger (v0.24.111)',
        '    //',
        '    // Player-deliberate arena trigger: stand within',
        f'    // {radius}m of arena center for {hold_seconds} continuous seconds.',
        '    // On completion: audible + visible feedback, then set the',
        '    // arena trigger flag (the same flag vanilla 90015442 sets',
        '    // after ring closure).',
        '    //',
        '    // Distinct from nb_arena_entry_trigger (which uses a 20m',
        '    // step-into radius with no hold time): this is a smaller',
        '    // inner zone with a deliberate hold, so players can\'t',
        '    // accidentally trigger it just by entering the arena.',
        '',
        '    EndIf(EventFlag(triggerFlag));',
        '',
        '    // Phase 1: wait for player to enter the inner radius.',
        f'    WaitFor({radius_check});',
        '',
        '    // Phase 2: race the hold duration against player leaving.',
        '    // If player leaves before the duration elapses, the OR-clause',
        '    // fires first and the next EndIf cancels.',
        f'    WaitFor(ElapsedSeconds({hold_seconds}) || !{radius_check});',
        f'    EndIf(!{radius_check});',
        '',
        '    // Phase 3: belt-and-suspenders idempotency — flag might have',
        '    // been set by vanilla / entry-trigger / watchdog during the hold.',
        '    EndIf(EventFlag(triggerFlag));',
        '',
    ]
    if tracers:
        lines.extend([
            '    // Phase 4: unmissable feedback. Loud SFX + boss-defeat-style',
            '    // banner so the player KNOWS the trigger fired.',
            '    PlaySE(20000, SoundType.SFX, 888880000);',
            '    DisplayTextEffectId(1020);',
            '',
        ])
    lines.extend([
        '    // Phase 5: set the trigger flag (network-synced for co-op).',
        '    SetNetworkconnectedEventFlagID(triggerFlag, ON);',
        '});',
        '',
    ])
    return '\r\n'.join(lines)


@register('nb_arena_hold_trigger')
def patch_nb_arena_hold_trigger(content, filename):
    """v0.24.111: Player-deliberate "hold-to-trigger" arena starter.

    Stand within 5m of the arena-center anchor for 3 continuous seconds
    to start the encounter early. On completion plays a loud SFX and
    shows an on-screen banner (the boss-defeat banner — semantically
    off but unmissable) so the player KNOWS it fired.

    Distinct from v0.24.109 nb_arena_entry_trigger:
      - Entry trigger: 20m radius, no hold (step-into). Easy to trigger
        accidentally just walking across the arena, no feedback.
      - Hold trigger: 5m radius, 3s hold, AV feedback on completion.
        Deliberate, unambiguous, diagnostically useful.

    The two triggers coexist:
      - If a player rushes through the entry radius without stopping,
        the entry trigger fires first. Watchdog deactivates (flag is
        already set). Hold trigger may still attempt to fire later,
        but EndIf(EventFlag(triggerFlag)) at its start short-circuits.
      - If a player stops at the inner zone deliberately, the hold
        trigger fires within 3s of arriving. Same flag-set, same
        downstream effect.

    Why this exists (the motivating user need):
        - The 60s watchdog timer + N2-broken-arena testing left us
          uncertain whether the watchdog fired silently in the wrong
          context (during N1 rather than N2). A player-action trigger
          eliminates the timing ambiguity entirely: the player presses
          a button (or holds a position), feedback confirms the event
          fired, downstream effects can be observed directly.
        - As a diagnostic tool: lets us test "does setting the trigger
          flag in this arena actually start the encounter?" without
          waiting for vanilla flow or any timer.
        - As a feature: lets players skip the ring closure if they
          want to engage immediately (Risk of Rain 2 teleporter style).

    Scope:
        - common_func.emevd.dcx.js: appends $Event(99055400) once.
        - 25 NB arena per-map files: injects per-arena
          $InitializeCommonEvent(0, 99055400, anchor, flag) into Event(0).

    Idempotency:
        - common_func: skip if event already present.
        - per-arena: skip if InitializeCommonEvent already present.

    Caveats:
        - The 5m radius is empirical. Smaller and players will struggle
          to position; larger and combat positioning may accidentally
          complete the hold.
        - DisplayTextEffectId(1020) is the boss-defeat banner — chosen
          for unmissable visibility, not semantic fit. A future polish
          pass could swap to a less-dramatic but more-appropriate
          text effect ID once we know which is which.
        - This doesn't address the underlying empty-arena bug. It just
          gives us a clean way to verify the trigger-flag-set IS
          sufficient on working seeds, and provides a player-action
          fallback on broken ones.
    """
    if filename.startswith('common_func'):
        if f'$Event({_NB_ARENA_HOLD_TRIGGER_EVENT_ID},' in content:
            return content, 0
        return content + _build_arena_hold_trigger_event_body(
            tracers=not PUBLISH_MODE,
        ), 1

    # Per-map injection
    stem = filename
    for suffix in ('.emevd.dcx.js', '.emevd.js', '.dcx.js', '.js'):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break

    nb_stems = {s for s, _, _ in _NB_BOSS_ENTITY_IDS}
    if stem not in nb_stems:
        return content, 0

    if f'InitializeCommonEvent(0, {_NB_ARENA_HOLD_TRIGGER_EVENT_ID}' in content:
        return content, 0  # already injected

    try:
        anchor, flag = _arena_entry_args(stem)
    except ValueError:
        return content, 0

    new_line = f'$InitializeCommonEvent(0, {_NB_ARENA_HOLD_TRIGGER_EVENT_ID}, {anchor}, {flag});'
    indent_pattern = r'^([ \t]*)(\$InitializeCommonEvent\(0, 90015442, \d+, \d+\);)'
    import re as _re
    m = _re.search(indent_pattern, content, _re.MULTILINE)
    if not m:
        return content, 0
    indent = m.group(1)
    replacement = m.group(0) + '\r\n' + indent + new_line
    new_content = _re.sub(indent_pattern, replacement, content, count=1, flags=_re.MULTILINE)
    return new_content, 1


# ============================================================================
# nb_boss_init_diag_tracers (v0.24.112)
# ============================================================================


# Tracer SFX: 888880000 is the "moment of emphasis" sound vanilla uses for
# boss-defeat (confirmed audible in playtest). Same SFX for all three events;
# the distinguishing signal is the DisplayTextEffectId banner shown
# concurrently. Each banner is distinct so you can VISUALLY identify which
# event fired even though they share an SFX.
_BOSS_INIT_TRACER_SFX = 888880000

# Banner text-effect IDs. Picked from vanilla "important moment" contexts.
# Distinct enough that they should produce different on-screen text.
_BOSS_INIT_TRACER_REGISTRATION_BANNER = 1020   # 90015000 — paired with 888880000 in vanilla boss-kill
_BOSS_INIT_TRACER_PROXIMITY_BANNER    = 2200   # 90015030 — different banner, distinguishable from kill
_BOSS_INIT_TRACER_POSTKILL_BANNER     = 2300   # 90015002 — third banner


@register('nb_boss_init_diag_tracers')
def patch_nb_boss_init_diag_tracers(content, filename):
    """v0.24.112 (revised v0.24.113): Diagnostic-only PlaySE+banner tracers
    in the three common_func boss-init events.

    REVISION NOTE (v0.24.113):
        v0.24.112 used SFX IDs 806740/41/42 (siblings of an "area effect"
        set used elsewhere in vanilla). Playtest confirmed those sounds
        are subaudible — produced no audible feedback during normal
        gameplay even though the events were certainly firing. The
        diagnostic was useless.

        v0.24.113 redesign: use SFX 888880000 (the proven-audible vanilla
        "moment of emphasis" sound used for boss-defeat) paired with
        distinct DisplayTextEffectId banners. All three events share the
        SFX (audible confirmation that SOMETHING fired) but each shows a
        different on-screen banner (distinguishes WHICH fired):

          - 90015000 fires → "boss defeated"-style banner (1020) + SFX
          - 90015030 fires → different banner (2200) + same SFX
          - 90015002 fires → third banner (2300) + same SFX

        Player will see banner text on screen + hear emphasis sound.
        Reading which banner appeared tells us which event fired.

    DIAGNOSTIC INTERPRETATION (unchanged from v0.24.112):
        - Banner 1020 on map load (Limveld field): 90015000 fired
        - Banner 2200 as you approach a boss: 90015030 fired
        - Banner 2300 after boss death: 90015002 fired
        - No banners at all: events never fired (m60 tile's Event(0)
          didn't reach our InitializeCommonEvent calls)

    REMOVAL:
        Diagnostic-only. Once we know what's firing, retire by removing
        the @register decorator (same pattern as nb_wave_bypass).

    v0.25.0: Gated on the module-level PUBLISH_MODE flag. Stays @register'd
    so it's discoverable via `python emevd_patch.py list` and reachable
    via --patch nb_boss_init_diag_tracers, but a no-op while PUBLISH_MODE
    is True. Flip PUBLISH_MODE = False to revive for playtest.
    """
    if PUBLISH_MODE:
        return content, 0
    if not filename.startswith('common_func'):
        return content, 0

    # Idempotency: distinct marker that's UNIQUE to our patch within
    # 90015000's body. The DisplayTextEffectId 1020 by itself isn't enough —
    # vanilla uses it on the boss-kill path. But it doesn't appear at the
    # top of 90015000 in vanilla. So check for the specific TOP-of-90015000
    # injection shape.
    marker = (
        f'$Event(90015000, Default, function('
    )
    # Hard to write a clean idempotency check without parsing; use the
    # combination of injection pattern + count. If we already inserted
    # the 1020 banner immediately after 90015000's DisableNetworkSync,
    # the substitution count will be 0.
    import re as _re
    total = 0

    insertions = (
        (90015000, 'Default', _BOSS_INIT_TRACER_REGISTRATION_BANNER),
        (90015030, 'Restart', _BOSS_INIT_TRACER_PROXIMITY_BANNER),
        (90015002, 'Default', _BOSS_INIT_TRACER_POSTKILL_BANNER),
    )

    for event_id, mode, banner_id in insertions:
        # Pattern: $Event(N, Mode, function(...) {\r\n    DisableNetworkSync();\r\n
        pat = (
            rf'(\$Event\({event_id}, {mode}, function\([^)]*\) \{{\r?\n'
            rf'    DisableNetworkSync\(\);\r?\n)'
        )
        # Build the replacement. Skip injection if our banner+SFX pair
        # is already present right after this event's DisableNetworkSync.
        already_present = _re.search(
            pat + rf'    PlaySE\(20000, SoundType\.SFX, {_BOSS_INIT_TRACER_SFX}\);\r?\n'
                  rf'    DisplayTextEffectId\({banner_id}\);',
            content,
        )
        if already_present:
            continue

        replacement = (
            r'\1'
            f'    PlaySE(20000, SoundType.SFX, {_BOSS_INIT_TRACER_SFX});\r\n'
            f'    DisplayTextEffectId({banner_id});\r\n'
        )
        new_content, n = _re.subn(pat, replacement, content, count=1)
        if n == 1:
            content = new_content
            total += 1

    return content, total


# ============================================================================


@register('preboss_wave_timeout')
def patch_preboss_wave_timeout(content, filename):
    """v0.24.103: Add a 90s timeout to the per-Limveld-tile night-phase
    WaitFors in common_func event 90015442 — the NB arena wave-gate setter.

    Symptom this fixes:
        - Player reaches an NB arena, but the preboss wave never fires AND
          the boss never spawns. Arena is empty / stuck — no progress.
        - Confirmed seed 388677 v0.24.69 Tricephalos N1 (m49_29 or m49_24)
          and seed 417416 v0.24.96 Tricephalos N2. Recurring rare bug.

    Cause: event 90015442 is the per-arena wave-gate setter. It sets the
    `eventFlagId` parameter (= `eventFlagId3` in the XXXX2810 boss-intro
    events) that unblocks the boss-spawn / wave-fire chain. Its body looks
    up which Limveld tile the boss arena entity sits in via a series of
    `if (EntityInRadiusOfEntity(<tile_marker>, entityId, 15, 1))` checks
    and waits on that tile's night-phase flag (1028400200, 1028400205,
    1056400200, ...). When the per-tile night-phase flag doesn't fire
    (broken day/night-cycle script — happens occasionally as rando swap
    fallout), 90015442 stalls indefinitely. eventFlagId never gets set.
    The XXXX2810 boss-intro events stall on their outer
    `WaitFor(EventFlag(eventFlagId3))`. No wave, no boss, stuck arena.

    Fix: append `|| ElapsedSeconds(PREBOSS_WAVE_TIMEOUT_SECONDS)` to each
    per-tile WaitFor inside 90015442. After N seconds, the WaitFor force-
    fires, regardless of whether the per-tile flag ever set. The arena's
    eventFlagId gets set, the boss-intro proceeds, wave + boss are armed.

    Why this doesn't reintroduce the preboss_wake_timeout regression
    (which retired v0.24.78 for revealing field-boss map icons on Day 1):
        - 90015442 is NB-arena-EXCLUSIVE — 28 callers, all m47_7X / m48_XX
          / m49_XX, zero m60 field-boss tiles. Patching it leaves field-
          boss map icon reveal flow completely untouched.
        - NB arena MSBs are not rendered/overlaid into the world until the
          per-tile night-phase transition fires, so even though our timer
          fires 90s into the expedition (during Day 1), the wave/boss
          setup happens in a non-rendered arena. Player sees nothing.
        - When player reaches the NB arena on Night 1 or Night 2 via the
          normal route, arena overlays as usual and the boss is found
          standing in idle pose ready to fight.

    Trade-off (acknowledged): the boss "rise" / "drop-in" intro animation
    inside the XXXX2810 chain fires at 90s into expedition for tonight's
    active NB arenas, into the unrendered arena. When player arrives at
    Night 1/2, boss is in idle pose — no dramatic rise animation. Per
    user discussion, acceptable: the arena isn't rendered at 90s in, so
    the player can't see what they'd lose anyway. Better than stuck arena.

    IsMapVariation(2) gating in each NB arena's Event(0) means only
    tonight's 2 active NB arenas actually invoke 90015442 via
    InitializeCommonEvent — the other 26 NB arena MSBs don't. So exactly
    2 timer fires per expedition, one per active NB arena. Matches the
    "2 fires per expedition" design intent.

    Tunable: PREBOSS_WAVE_TIMEOUT_SECONDS at the top of the function.
    Default 90s. ElapsedSeconds is measured from event registration time
    (expedition start), so this is effectively "force-fire at 90s into
    expedition for the active NB arenas." Bumping it higher delays the
    bailout; the trade-off is broken arenas take longer to recover. The
    wave-fire visibility issue (rise anim into unrendered arena) is
    invariant to this value — any non-infinite N has the same UX impact
    since night transitions happen well after this fires regardless.

    Only applies to common_func.emevd.dcx.js. Patches all per-tile
    `WaitFor(EventFlag(NNNNNNNNN));` occurrences inside event 90015442.
    Idempotent: pre-patched WaitFors (with ElapsedSeconds already present)
    won't match the regex and are skipped.
    """
    if not filename.startswith('common_func'):
        return content, 0

    PREBOSS_WAVE_TIMEOUT_SECONDS = 90  # bail-out wait — tune as needed

    # Match: WaitFor(EventFlag(NNNNNNNN));
    # (8-10 digit per-tile night flags: 1028400200, 1056400200, etc.)
    # Idempotency: requires that the WaitFor's argument is bare — already-patched
    # WaitFors with `|| ElapsedSeconds(...)` won't match the closing `));`.
    pattern = r'WaitFor\(EventFlag\((\d+)\)\);'
    replacement = (
        rf'WaitFor(EventFlag(\1) || ElapsedSeconds({PREBOSS_WAVE_TIMEOUT_SECONDS}));'
    )
    content, n = replace_in_event(content, 90015442, pattern, replacement)
    return content, n


# ============================================================================
# CLI
# ============================================================================

USAGE_BANNER = """\
4laric's NR EMEVD Patcher
==========================

Patches NR's EMEVD event scripts to fix rando-introduced encounter bugs
(boss healthbar gates, death-anim hangs, dormant tunnel mobs, etc).
All patches land in common_func.emevd.dcx.js — a single file recompile.

USAGE
-----
  python emevd_patch.py list
      List available patches with descriptions.

  python emevd_patch.py audit <input_dir>
      Scan an EMEVD for handlers matching the dormant-AI bug shape.
      Reports already-patched and unpatched candidates ranked by impact.

  python emevd_patch.py patch <input_dir> <output_dir>
      Apply ALL patches. Reads .emevd.dcx.js files from <input_dir>,
      writes only modified files to <output_dir>.

  python emevd_patch.py patch <input_dir> <output_dir> --patch <name>
      Apply only one patch. Repeat --patch to combine specific patches.

WORKFLOW
--------
  1. Decompile vanilla EMEVDs to JS via DarkScript3:
       cd <NR install>\\Game\\event
       DarkScript3.exe common_func.emevd.dcx
     This produces common_func.emevd.dcx.js next to it. (Only this file
     needs decompiling — it's where every patch lands.)

  2. Run the patcher:
       python emevd_patch.py patch <folder_with_js> <output_folder>
     Output folder will contain just the modified common_func file.

  3. Recompile via DarkScript3:
       DarkScript3.exe <output_folder>\\common_func.emevd.dcx.js
     Produces common_func.emevd.dcx in the output folder.

  4. Drop into your me3 profile:
       <me3_profile>\\<package>\\event\\common_func.emevd.dcx

  5. Launch via me3 — bug-class fixes are now live.

  Verify the patch landed: open the modified .js and search for
  EnableCharacterAI. You should see it inside event 90085002.
"""


def cmd_list():
    print("Available patches:")
    print()
    for name, fn in PATCHES.items():
        doc = (fn.__doc__ or '').strip()
        first_line = doc.split('\n')[0]
        # Pull the "Symptom this fixes:" block if present, for richer listing
        symptom = ''
        for line in doc.split('\n'):
            if 'Symptom' in line:
                symptom = line.split('Symptom this fixes:', 1)[-1].strip()
                if not symptom:
                    # Symptom is on the next line(s)
                    idx = doc.split('\n').index(line)
                    next_lines = [l.strip() for l in doc.split('\n')[idx+1:idx+3]
                                  if l.strip().startswith('-')]
                    symptom = '; '.join(next_lines).replace('- ', '')
                break
        print(f"  {name}")
        print(f"    {first_line}")
        if symptom: print(f"    Fixes: {symptom}")
        print()


def cmd_audit(input_dir):
    """Scan common_func.emevd.dcx.js for handlers matching the dormant-AI bug
    shape: enables a character + forces an animation but never enables AI.
    Reports candidates ranked by per-map call count (impact), with separate
    columns for already-patched vs unpatched."""
    target_path = None
    for f in os.listdir(input_dir):
        if f.startswith('common_func') and f.endswith('.emevd.dcx.js'):
            target_path = os.path.join(input_dir, f)
            break
    if target_path is None:
        print(f"ERROR: no common_func.emevd.dcx.js found in {input_dir}")
        sys.exit(1)

    with open(target_path, encoding='utf-8') as f:
        content = f.read()

    # Index $Event blocks
    events = []
    for m in re.finditer(r'^\$Event\((\d+),', content, re.MULTILINE):
        events.append((m.start(), int(m.group(1))))
    events.append((len(content), -1))

    def get_event(eid):
        for s, e in events:
            if e == eid:
                for ns, _ in events:
                    if ns > s: return content[s:ns]
                return content[s:]
        return None

    # Per-map call counts for prioritization
    from collections import defaultdict
    call_counts = defaultdict(int)
    for fname in os.listdir(input_dir):
        if not fname.startswith('m'): continue
        if not fname.endswith('.emevd.dcx.js'): continue
        with open(os.path.join(input_dir, fname), encoding='utf-8') as f:
            c = f.read()
        for m in re.finditer(r'\$InitializeCommonEvent\(0,\s*(\d+)', c):
            call_counts[int(m.group(1))] += 1

    # Already-patched handlers, for status display
    already_patched = {
        90085002, 90015310, 90015160, 90015163, 90015164,
        90015300, 90015401, 90085012, 90085101, 90085201,
        90035286, 90035202, 90035263, 90075820, 90005705,
        90035244, 90035247,
        90035204, 90035213, 90035220, 90035221, 90035227, 90035229,
        90035232, 90035250, 90035262,
        90065009, 90075401,
        90005706, 90005720, 90005725, 90005726, 90005760,
        # Wake/death handlers (separate patches)
        90015000, 90015030, 90005860, 90005861,
        # post_intro_aggro_kick (v0.24.104) — proximity-wake replan
        90005250, 90005251, 90005260, 90005261, 90005271,
    }

    # Find all candidates with the dormant-AI bug shape
    candidates = []
    for s_idx, eid in events[:-1]:
        body = get_event(eid)
        if not body: continue
        enable_chr = re.findall(r'EnableCharacter\((\w+)\)', body)
        enable_chr = [c for c in enable_chr
                      if not c.endswith('Collision')
                      and not c.endswith('Immortality')
                      and not c.endswith('AI')]
        force_anim = re.findall(r'ForceAnimationPlayback\((\w+),', body)
        enable_ai = re.findall(r'EnableCharacterAI\((\w+)\)', body)
        if not enable_chr or not force_anim: continue
        risky = (set(enable_chr) & set(force_anim)) - set(enable_ai)
        if not risky: continue
        # Filter: skip pure death/cleanup handlers
        if 'ForceCharacterDeath' in body and call_counts.get(eid, 0) < 5: continue
        candidates.append((eid, sorted(risky), call_counts.get(eid, 0)))

    candidates.sort(key=lambda c: -(c[2] * len(c[1])))

    print(f"Audit of {os.path.basename(target_path)}")
    print(f"Found {len(candidates)} handlers matching dormant-AI bug shape")
    print()
    patched_count = sum(1 for c in candidates if c[0] in already_patched)
    print(f"  {patched_count}/{len(candidates)} already covered by current patch")
    print()
    print(f"{'status':<8} {'eid':<10} {'calls':>6} {'risky':>6}  risky entities")
    print(f"{'-'*8} {'-'*10} {'-'*6} {'-'*6}  {'-'*40}")
    for eid, risky, cnt in candidates:
        status = '✓ patch' if eid in already_patched else '! NEW'
        risky_str = ','.join(risky[:4])
        if len(risky) > 4: risky_str += '...'
        print(f"{status:<8} {eid:<10} {cnt:>6} {len(risky):>6}  {risky_str}")
    print()

    new_count = len(candidates) - patched_count
    if new_count > 0:
        print(f"⚠ {new_count} handler(s) match the bug shape but aren't yet patched.")
        print(f"  These may indicate a game update changed common_func or that")
        print(f"  the patch list needs widening. Pass the new EIDs to claude or")
        print(f"  add them to permissive_spawn_emerge in this script.")
    else:
        print(f"✓ All known dormant-AI bug shapes covered.")


def cmd_patch(in_dir, out_dir, patch_names=None):
    if patch_names is None:
        patch_names = list(PATCHES.keys())
    else:
        for p in patch_names:
            if p not in PATCHES:
                print(f"Unknown patch: {p}")
                print(f"Available: {list(PATCHES.keys())}")
                sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)

    files = sorted(f for f in os.listdir(in_dir) if f.endswith('.emevd.dcx.js'))
    print(f"Found {len(files)} EMEVD JS files in {in_dir}")
    print(f"Applying {len(patch_names)} patches: {patch_names}")
    print()

    summary = {p: 0 for p in patch_names}  # patch_name -> total substitutions
    files_modified = 0

    for fname in files:
        # v0.23.72-late: read/write in binary mode to preserve CRLF line
        # endings. DarkScript3 was decompiled on Windows and emits CRLF
        # throughout. Python's default text-mode I/O on Linux normalizes
        # CRLF→LF on read, then writes LF-only on output — corrupting the
        # whole file's line endings even though the actual patch text was
        # correct. DarkScript3's parser was rejecting the resulting
        # LF-mostly file (with my 10 inserted CRLFs from the patch
        # replacement text mixed in). Binary mode preserves everything
        # exactly as-is and only my explicit `\r\n` replacements land in
        # the output.
        with open(os.path.join(in_dir, fname), 'rb') as f:
            original_bytes = f.read()
        original = original_bytes.decode('utf-8')
        modified = original
        per_file_subs = 0
        for pname in patch_names:
            modified, n = PATCHES[pname](modified, fname)
            summary[pname] += n
            per_file_subs += n

        if modified != original:
            files_modified += 1
            print(f"  {fname}: {per_file_subs} substitution(s)")
            with open(os.path.join(out_dir, fname), 'wb') as f:
                f.write(modified.encode('utf-8'))
        # Unchanged files are NOT copied to output — that way DarkScript3 only
        # needs to recompile what actually changed.

    print()
    if files_modified == 0:
        print("No substitutions made. Possible reasons:")
        print("  - Input directory has no .emevd.dcx.js files (decompile first)")
        print("  - Patches already applied to these files")
        print("  - The handlers we target aren't present in this version of NR")
        print()
        print("Run with --help or `python emevd_patch.py list` for usage.")
        return

    print(f"✓ Patched {files_modified}/{len(files)} files, {sum(summary.values())} total substitutions")
    print()
    print("Substitutions per patch:")
    for pname, n in summary.items():
        marker = '✓' if n > 0 else '·'
        print(f"  {marker} {pname:<28} {n}")
    print()
    print(f"Output written to: {out_dir} ({files_modified} file(s))")
    print()
    print("Next steps:")
    print(f"  1. Recompile via DarkScript3:")
    for fname in sorted(os.listdir(out_dir)):
        if fname.endswith('.emevd.dcx.js'):
            print(f"       DarkScript3.exe \"{os.path.join(out_dir, fname)}\"")
    print(f"  2. Drop the resulting .emevd.dcx file(s) into:")
    print(f"       <me3_profile>/<package>/event/")
    print(f"  3. Launch the game via me3.")


def main():
    # No args → show usage banner instead of an argparse error
    if len(sys.argv) < 2:
        print(USAGE_BANNER)
        return

    p = argparse.ArgumentParser(
        description="Batch-patch NR EMEVD JS files. Run without args for full usage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest='cmd', required=True)

    pl = sub.add_parser('list', help='List available patches with descriptions')

    pa = sub.add_parser('audit', help='Scan EMEVD for handlers matching the dormant-AI bug shape')
    pa.add_argument('input_dir',
                    help='Directory containing .emevd.dcx.js files')

    pp = sub.add_parser('patch', help='Apply patches to a directory of .emevd.dcx.js files')
    pp.add_argument('input_dir',
                    help='Directory containing .emevd.dcx.js files (DarkScript3 output)')
    pp.add_argument('output_dir',
                    help='Where to write modified files (only changed files written)')
    pp.add_argument('--patch', action='append', dest='patches', metavar='NAME',
                    help='Apply only this patch (repeatable). Default: apply all.')

    args = p.parse_args()

    if args.cmd == 'list':
        cmd_list()
    elif args.cmd == 'audit':
        if not os.path.isdir(args.input_dir):
            print(f"ERROR: input_dir does not exist: {args.input_dir}")
            sys.exit(1)
        cmd_audit(args.input_dir)
    elif args.cmd == 'patch':
        # Validate input exists with friendlier error than a stack trace
        if not os.path.isdir(args.input_dir):
            print(f"ERROR: input_dir does not exist: {args.input_dir}")
            print()
            print("If you haven't decompiled the EMEVDs yet:")
            print("  cd <NR install>/Game/event")
            print("  DarkScript3.exe common_func.emevd.dcx")
            print("Then point input_dir at that folder.")
            sys.exit(1)
        cmd_patch(args.input_dir, args.output_dir, args.patches)


if __name__ == '__main__':
    main()
