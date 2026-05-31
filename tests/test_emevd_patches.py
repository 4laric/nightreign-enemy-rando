"""Tests for emevd_patch.py timeout patches.

Focus: preboss_wake_timeout (v0.24.71) — verify it correctly injects
an ElapsedSeconds(N) clause into the chrAreaFlag/chrHpAreaFlag
composition at all 5 encounter event variants, matches the proper
naming variants, and is filename-scoped to common_func.emevd.dcx.js.
"""
import os
import sys
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import emevd_patch  # noqa: E402


# Minimal synthetic content covering both naming variants. Mirrors the
# structure of vanilla NR common_func.emevd.dcx.js so the patch regex
# matches realistically.
_SYNTHETIC_COMMON_FUNC = """\
$Event(90015000, Default, function(eventFlagId, chrEntityId, nameId, targetDistance, bgmBossConvParamId, eventFlagId2) {
    DisableNetworkSync();
    chrHpArea = (CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)
        || CharacterAIState(chrEntityId, AIStateType.Recognition, GreaterOrEqual, 1))
        && EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1);
    chr = CharacterRatioDead(chrEntityId);
    chrHpAreaFlag |= chrHpArea || chr;
    WaitFor(chrHpAreaFlag);
});

$Event(90015007, Default, function(eventFlagId, chrEntityId, areaEntityId, targetDistance, nameId, bgmBossConvParamId, eventFlagId2) {
    DisableNetworkSync();
    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)
        && InArea(20000, areaEntityId);
    chr = CharacterRatioDead(chrEntityId);
    chrAreaFlag |= chrArea || chr;
    WaitFor(chrAreaFlag);
});

$Event(90015021, Default, function(eventFlagId, chrEntityId, nameId, targetDistance, bgmBossConvParamId, eventFlagId2, eventFlagId3) {
    DisableNetworkSync();
    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1);
    chr = CharacterRatioDead(chrEntityId);
    chrAreaFlag |= chrArea || chr;
    WaitFor(chrAreaFlag);
});

$Event(90015023, Default, function(eventFlagId, targetDistance, eventFlagId2, chrEntityId, chrEntityId2, nameId, chrEntityId3, nameId2, chrEntityId4, nameId3) {
    DisableNetworkSync();
    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1);
    chr = CharacterRatioDead(chrEntityId);
    chrAreaFlag |= chrArea || chr;
    WaitFor(chrAreaFlag);
});

$Event(90015026, Default, function(eventFlagId, targetDistance, eventFlagId2, chrEntityId, chrEntityId2, nameId) {
    DisableNetworkSync();
    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1);
    chr = CharacterRatioDead(chrEntityId);
    chrAreaFlag |= chrArea || chr;
    WaitFor(chrAreaFlag);
});

$Event(90099999, Default, function() {
    // Unrelated event — should NOT be patched
    chrAreaFlag |= chrArea || chr;
    WaitFor(chrAreaFlag);
});
"""


class TestPrebossWakeTimeoutRetiredV0_24_78:
    """v0.24.78: preboss_wake_timeout RETIRED.

    The patch was added in v0.24.71 as a "belt-and-suspenders safety
    net" for the v0.24.69 Tricephalos seed 388677 case (boss never
    spawned). The root cause was fixed properly in v0.24.70 via the
    anim_compat-at-demotion mirror.

    Meanwhile preboss_wake_timeout was actively degrading every
    expedition: its 90s ElapsedSeconds fallback fires in every
    encounter event registered via InitializeCommonEvent — including
    m60 Limveld field-boss tiles. Result: 90 seconds into every
    expedition, every field boss "wakes up" briefly, registering its
    healthbar (→ map icon revealed Day 1 instead of Day 2) and
    cycling through the L0 RestartEvent loop (→ spurious healthbar
    flicker). Confirmed via user playtest screenshot showing red-
    bordered Night Boss markers visible on Day 1.

    Other timeout safety nets remain in place for the cases
    preboss_wake_timeout was meant to cover:
    - nb_speffect_wait_timeout (v0.24.74) covers NB-arena wave stalls
    - boss_clear_watchdog (300s) covers spawned-but-frozen bosses
    - permissive_boss_wake covers AI-state wake issues

    If a "boss never spawned" case recurs, investigate root cause
    rather than re-registering this patch. The collateral damage
    isn't worth the defensive value.
    """

    def test_patch_no_longer_registered(self):
        """preboss_wake_timeout must NOT be in PATCHES registry —
        retirement is enforced at the @register decorator level."""
        assert 'preboss_wake_timeout' not in emevd_patch.PATCHES, (
            'preboss_wake_timeout was retired in v0.24.78 due to '
            'field-boss map-icon-on-Day-1 + healthbar-flicker '
            'regression. If you re-registered it, also restore the '
            'previous tests AND address the regression first.')

    def test_function_still_exists_for_reference(self):
        """The function body is kept for historical reference even
        though the @register decorator was removed. If someone needs
        to revive it (after addressing the field-boss regression),
        the implementation is still here."""
        assert hasattr(emevd_patch, 'patch_preboss_wake_timeout'), (
            'patch_preboss_wake_timeout function body removed — '
            'this is fine for cleanup but if you want to revive the '
            'patch, you\'ll need to rewrite it.')


class TestEmevdPatchRegistry:
    """Sanity tests on the patch registry — these catch regression
    where a patch silently disappears from PATCHES (e.g., forgotten
    @register decorator)."""

    def test_required_patches_registered(self):
        """All timeout/safety patches must be registered. If any of
        these disappear, the rando pipeline silently skips them and
        the corresponding bug class returns.

        v0.24.78: preboss_wake_timeout REMOVED from required list —
        retired because its 90s timeout was firing on every expedition
        in every encounter event registered via InitializeCommonEvent
        (including m60 Limveld field-boss tiles), causing field-boss
        map icons to reveal on Day 1 and spurious healthbar flickering.
        See TestPrebossWakeTimeoutRetiredV0_24_78.

        v0.24.100: boss_reward_inject REMOVED from required list —
        pivoting to engine-side handling (slot-pool gating + regulation.bin
        boss-reward config) which is more precise than the common_func
        blanket-inject. The blanket inject had unresolved trade-offs
        (potential double-fire on vanilla dungeon bosses, empty pickers
        on under-configured swap-ins) that the engine-side approach
        addresses at the source. See TestBossRewardInjectRetiredV0_24_100.

        v0.24.102: permissive_boss_wake REMOVED from required list —
        retired alongside permissive_spawn_emerge on the hypothesis that
        the engine-side improvements (anim_compat-at-demotion, slot-pool
        gating, has_reward preservation, V3_PRESERVE_SLOTS hardening) make
        the wake-permissivity safety nets redundant. Reverting is one
        @register decorator restoration away if playtest shows otherwise.
        See TestPermissiveBossWakeRetiredV0_24_102.

        v0.24.103: preboss_wave_timeout ADDED. Per-NB-arena safety net
        targeting common_func event 90015442 (the per-Limveld-tile wave-
        gate setter). Distinct from the retired preboss_wake_timeout
        (which targeted 90015000/030/etc. and caused the field-boss map
        icon Day-1 regression). 90015442 is NB-arena-exclusive so no
        field-boss collateral. See TestPrebossWaveTimeoutV0_24_103."""
        required = (
            'death_timeout',
            'boss_clear_watchdog',
            # 'preboss_wake_timeout',     # RETIRED v0.24.78
            # 'boss_reward_inject',       # RETIRED v0.24.100
            # 'permissive_boss_wake',     # RETIRED v0.24.102
            # 'permissive_spawn_emerge',  # RETIRED v0.24.102 (was not in
            #                                required, but listed here for
            #                                completeness alongside its sibling)
            'nb_speffect_wait_timeout',   # v0.24.74
            'preboss_wave_timeout',       # v0.24.103
        )
        missing = [p for p in required if p not in emevd_patch.PATCHES]
        assert not missing, (
            f'Required patches missing from registry: {missing}. '
            'Check @register decorators.')


class TestBossRewardInjectRetiredV0_24_100:
    """v0.24.100: boss_reward_inject RETIRED.

    The patch hooked common_func boss-wake handlers and the encampment-
    clear handler to fire HandleMinibossDefeat on every confirmed boss
    kill, providing universal NR choice-of-3 reward UI coverage for
    randomized boss slots.

    Replaced by an engine-side approach:
    1. oops_v3 gates boss-having source slots to boss-having targets only,
       so every kept boss slot has a c-prefix that natively triggers a reward.
    2. A regulation.bin edit adds boss-reward configuration to chrs that
       should have one but don't natively, expanding the boss-having pool.

    Engine-side is more precise than the blanket common_func inject:
    - No double-fire risk on vanilla per-map dungeon bosses (~28 known
      call sites that already had map-specific HandleMinibossDefeat).
    - No empty-picker risk on under-configured swap-ins — the regulation
      edit gives them a proper reward set.
    - Doesn't need to gate inside common_func at all; the source-target
      pool is the gate.

    The HandleMinibossDefeat call site catalog and BOSS_WAKE_HANDLER_EVENTS
    list are recoverable from git history at v0.24.99 if a future revival
    is needed.
    """

    def test_patch_no_longer_registered(self):
        """boss_reward_inject must NOT be in PATCHES registry —
        retirement is enforced at the @register decorator level
        (the function and its decorator were removed in v0.24.100)."""
        assert 'boss_reward_inject' not in emevd_patch.PATCHES, (
            'boss_reward_inject was retired in v0.24.100 in favor of '
            'engine-side slot-pool gating + regulation.bin boss-reward '
            'config. If you re-registered it, also confirm whether the '
            'engine-side replacement is incomplete and surface that.')

    def test_function_body_removed(self):
        """Unlike preboss_wake_timeout (which kept its body for reference),
        boss_reward_inject is fully removed. If revival is needed, restore
        from git history at v0.24.99."""
        assert not hasattr(emevd_patch, 'patch_boss_reward_inject'), (
            'patch_boss_reward_inject function reappeared. If revived '
            'intentionally, restore the @register decorator AND update '
            'the required-patches list in TestEmevdPatchRegistry.')


# ============================================================================
# v0.24.102: permissive_boss_wake + permissive_spawn_emerge retirement
# ============================================================================
class TestPermissiveBossWakeRetiredV0_24_102:
    """v0.24.102: permissive_boss_wake RETIRED.

    The patch widened boss healthbar/BGM activation triggers (events
    90015000 + 90015030) from `AIStateType.Combat` only to a four-way
    OR of Combat | Recognition | Alert | HP-damage. This was a safety
    net for swapped enemies that sat in non-Combat AI states.

    Retirement hypothesis: the engine-side improvements (anim_compat-at-
    demotion, slot-pool gating, has_reward preservation, V3_PRESERVE_SLOTS
    hardening, V3_EXCLUDE_TARGET_PREFIXES + V3_EXCLUDE_SOURCE_PREFIXES
    coverage of mount/rider chrs) mean swapped enemies should reach
    AIStateType.Combat through normal vanilla pathways. The
    Recognition/Alert/HP-damage OR-clauses are dead weight.

    Function body kept for reference (unlike boss_reward_inject which
    was fully removed). Revival is one @register decorator restoration
    away if playtest shows wake-state regressions.
    """

    def test_patch_no_longer_registered(self):
        """permissive_boss_wake must NOT be in PATCHES registry."""
        assert 'permissive_boss_wake' not in emevd_patch.PATCHES, (
            'permissive_boss_wake was retired in v0.24.102. If you '
            're-registered it, document the playtest evidence that '
            'reverted the retirement hypothesis.')

    def test_function_still_exists_for_reference(self):
        """The function body is kept for historical reference."""
        assert hasattr(emevd_patch, 'patch_permissive_boss_wake'), (
            'patch_permissive_boss_wake function body removed — '
            'this is fine for cleanup but if you want to revive the '
            'patch, you\'ll need to rewrite it.')


class TestPermissiveSpawnEmergeRetiredV0_24_102:
    """v0.24.102: permissive_spawn_emerge RETIRED.

    The patch injected EnableCharacterAI + SetNetworkUpdateRate
    (AlwaysUpdate) after ForceAnimationPlayback calls in ~30 spawn/wake
    handlers (90085002, 90015310, 90015160/163/164, pose-idle 90035XXX
    family, SpecialStandby 90005200/201/211/221). This was a safety
    net for swapped enemies whose anim_bank was missing the required
    spawn-emerge animation, causing them to freeze in T-pose-stuck or
    pose-idle state.

    Retired alongside permissive_boss_wake on the same hypothesis. If
    T-pose-stuck or never-wakes-from-pose recurs in playtest, prefer
    a targeted anim_compat fix in the swap layer over reviving the
    blanket EMEVD inject.
    """

    def test_patch_no_longer_registered(self):
        """permissive_spawn_emerge must NOT be in PATCHES registry."""
        assert 'permissive_spawn_emerge' not in emevd_patch.PATCHES, (
            'permissive_spawn_emerge was retired in v0.24.102. If you '
            're-registered it, document the playtest evidence.')

    def test_function_still_exists_for_reference(self):
        """The function body is kept for historical reference."""
        assert hasattr(emevd_patch, 'patch_permissive_spawn_emerge'), (
            'patch_permissive_spawn_emerge function body removed — '
            'this is fine for cleanup but if you want to revive the '
            'patch, you\'ll need to rewrite it.')


# ============================================================================
# v0.24.74: nb_speffect_wait_timeout
# ============================================================================
class TestNbSpeffectWaitTimeoutV0_24_74:
    """v0.24.74 adds a 10s fallback timer to WaitFor(CharacterHasSpEffect(...))
    in Night Boss arena scripts.

    Root cause discovered seed 407417 v0.24.73: m49_29 $Event(49292810)
    has `WaitFor(CharacterHasSpEffect(chrEntityId, 10583))` that gates
    wave-fire SFX + chr2 enable. SpEffect 10583 is applied only by DH
    Queen's vanilla AI behavior. When the rando substitutes Erdtree
    Avatar (or any other chr) at her slot, the SpEffect is never applied
    and the wait blocks forever.

    Vanilla NR itself uses this exact pattern in common_func 90015163:
    `WaitFor(CharacterHasSpEffect(chrEntityId, 45832) || ElapsedSeconds(9))`.
    Direct precedent. We use 10s default.

    Scope:
      - common_func.emevd.dcx.js: events 90065040, 90065041 (NB chains)
      - m48_00/20/30/50/60/90, m49_29 (per-map files)
      - SKIPS m49_42 (player-entity waits) + all other maps

    Regression guards: ensure the patch applies exactly where expected
    and skips where it shouldn't.
    """

    def test_patch_registered(self):
        import emevd_patch
        assert 'nb_speffect_wait_timeout' in emevd_patch.PATCHES

    def test_patches_m49_29_boss_intro(self):
        import emevd_patch
        # The wave-fire wait in $Event(49292810)
        sample = (
            '$Event(49292810, Restart, function(chrEntityId, ...) {\r\n'
            '    DisplayBossHealthBar(Enabled, chrEntityId, 1, nameId);\r\n'
            '    WaitFor(CharacterHasSpEffect(chrEntityId, 10583));\r\n'
            '    SpawnOneshotSFX(...);\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](
            sample, 'm49_29_00_00.emevd.dcx.js')
        assert n == 1
        assert 'ElapsedSeconds(10)' in patched
        assert '|| ElapsedSeconds(10)' in patched

    def test_patches_common_func_90065040(self):
        import emevd_patch
        sample = (
            '$Event(90065040, Restart, function(chrEntityId, ...) {\r\n'
            '    WaitFor(EventFlag(eventFlagId));\r\n'
            '    WaitFor(CharacterHasSpEffect(chrEntityId, 10583));\r\n'
            '    EnableCharacter(chrEntityId2);\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](
            sample, 'common_func.emevd.dcx.js')
        assert n == 1
        # The EventFlag WaitFor should be UNTOUCHED (only SpEffect ones get timeout)
        assert 'WaitFor(EventFlag(eventFlagId));' in patched

    def test_skips_m49_42_player_waits(self):
        """m49_42 has WaitFor(CharacterHasSpEffect(20000, 99210)) — entity
        20000 is the player. That's a legitimate player-buff wait, not an
        encounter gate. Must NOT be patched."""
        import emevd_patch
        sample = (
            '$Event(49420010, Default, function() {\r\n'
            '    WaitFor(CharacterHasSpEffect(20000, 99210));\r\n'
            '    WaitFor(!CharacterHasSpEffect(20000, 99210));\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](
            sample, 'm49_42_00_00.emevd.dcx.js')
        assert n == 0, 'Player-entity waits must not be patched'
        assert 'ElapsedSeconds' not in patched

    def test_skips_already_patched(self):
        """Idempotent — lines already with `|| ElapsedSeconds(N)` are skipped."""
        import emevd_patch
        sample = (
            '$Event(49292810, Restart, function(chrEntityId, ...) {\r\n'
            '    WaitFor(CharacterHasSpEffect(chrEntityId, 45832) || ElapsedSeconds(9));\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](
            sample, 'm49_29_00_00.emevd.dcx.js')
        assert n == 0, 'Already-timed-out waits must not be re-patched'

    def test_skips_out_of_scope_files(self):
        """Patch only applies to common_func + m48_*/m49_* files."""
        import emevd_patch
        sample = '    WaitFor(CharacterHasSpEffect(chrEntityId, 12345));\r\n'
        for fname in ('m30_30_00_00.emevd.dcx.js',
                      'm60_43_37_00.emevd.dcx.js',
                      'm11_00_00_00.emevd.dcx.js',
                      'unrelated.txt'):
            _, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](sample, fname)
            assert n == 0, f'Out-of-scope file {fname} should not be patched'

    def test_preserves_compound_conditions(self):
        """`WaitFor(EventFlag(X) && CharacterHasSpEffect(Y, Z))` must keep the AND
        binding correct: parenthesize the inner expression before OR-ing the timer."""
        import emevd_patch
        sample = (
            '$Event(48502310, Restart, function(chrEntityId, ...) {\r\n'
            '    WaitFor(EventFlag(48502300) && CharacterHasSpEffect(chrEntityId, 13744));\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](
            sample, 'm48_50_00_00.emevd.dcx.js')
        assert n == 1
        # Outer parens wrap the AND, then the timer is OR'd
        assert ('WaitFor((EventFlag(48502300) && CharacterHasSpEffect(chrEntityId, 13744)) '
                '|| ElapsedSeconds(10))') in patched

    def test_skips_endif_constructs(self):
        """EndIf(CharacterHasSpEffect(...)) is a CONDITIONAL EXIT, not a blocking
        wait. If SpEffect never applies, the EndIf doesn't fire — the event just
        proceeds. That's the OPPOSITE of a stall. Must not be patched."""
        import emevd_patch
        sample = (
            '$Event(90065041, Restart, function(chrEntityId, ...) {\r\n'
            '    EndIf(CharacterHasSpEffect(chrEntityId, 10581));\r\n'
            '    WaitFor(EventFlag(eventFlagId));\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](
            sample, 'common_func.emevd.dcx.js')
        assert n == 0

    def test_full_bundle_substitution_count(self):
        """Sanity gauge: applying the patch to the full v0.24.74 NB-arena
        bundle should produce exactly 18 substitutions across 8 files (per
        the v0.24.74 release notes)."""
        import emevd_patch, os
        bundle_dir = 'patched_emevd'
        files = ['common_func.emevd.dcx.js',
                 'm48_00_00_00.emevd.dcx.js',
                 'm48_20_00_00.emevd.dcx.js',
                 'm48_30_00_00.emevd.dcx.js',
                 'm48_50_00_00.emevd.dcx.js',
                 'm48_60_00_00.emevd.dcx.js',
                 'm48_90_00_00.emevd.dcx.js',
                 'm49_29_00_00.emevd.dcx.js']
        for f in files:
            assert os.path.exists(f'{bundle_dir}/{f}'), f'missing bundled {f}'

        # Re-apply on the bundle — should be 0 because we already applied
        total = 0
        for f in files:
            with open(f'{bundle_dir}/{f}') as fh:
                content = fh.read()
            _, n = emevd_patch.PATCHES['nb_speffect_wait_timeout'](content, f)
            total += n
        assert total == 0, f'Bundle should be idempotent; got {total} new subs'


# ============================================================================
# v0.24.103: preboss_wave_timeout
# ============================================================================
class TestPrebossWaveTimeoutV0_24_103:
    """v0.24.103 adds a 90s ElapsedSeconds bailout to each per-Limveld-tile
    WaitFor inside common_func event 90015442.

    This patch is SPECIFICALLY designed to avoid the regression that
    retired preboss_wake_timeout in v0.24.78:
    - preboss_wake_timeout targeted 90015000/007/021/023/026 — events used
      by BOTH field bosses (m60 tiles) and NB arenas. Day-1-into-expedition
      ElapsedSeconds fire revealed field-boss map icons on Day 1.
    - preboss_wave_timeout targets 90015442, which is NB-ARENA-EXCLUSIVE
      (28 callers, all m47_7X/m48_XX/m49_XX, zero m60). No field-boss
      collateral possible.

    Within the NB arena: the MSB isn't rendered/overlaid into the world
    until night-phase transition fires, so the 90s-into-expedition wave-
    fire happens into a non-visible arena. Player sees nothing during
    Day 1. When player reaches the arena via the normal Night 1/2 route,
    boss is found pre-armed in idle pose — same as normal flow minus the
    intro animation.

    Tests below catch:
    - Accidental scope creep (patch firing on common.emevd or non-90015442
      events in common_func)
    - Regex over-permissiveness (patching WaitFors that already have a
      timeout, or non-EventFlag WaitFors)
    - Substitution count drift (vanilla 90015442 has exactly 6 per-tile
      WaitFors — if vanilla changes this, our test catches it)
    """

    def test_patch_registered(self):
        """preboss_wave_timeout must be in PATCHES registry."""
        assert 'preboss_wave_timeout' in emevd_patch.PATCHES, (
            'preboss_wave_timeout missing from registry. '
            'Check @register decorator.')

    def test_substitutes_six_in_common_func_event_90015442(self):
        """Vanilla 90015442 has 6 per-Limveld-tile WaitFors. Patch should
        substitute exactly 6."""
        # Synthetic fixture matching the vanilla shape
        vanilla = (
            "$Event(90015442, Restart, function(entityId, eventFlagId) {\n"
            "    EndIf(EventFlag(eventFlagId));\n"
            "    if (EntityInRadiusOfEntity(1028402600, entityId, 15, 1)) {\n"
            "        WaitFor(EventFlag(1028400200));\n"
            "    }\n"
            "    if (EntityInRadiusOfEntity(1028402601, entityId, 15, 1)) {\n"
            "        WaitFor(EventFlag(1028400205));\n"
            "    }\n"
            "    if (EntityInRadiusOfEntity(1028402602, entityId, 15, 1)) {\n"
            "        WaitFor(EventFlag(1028400210));\n"
            "    }\n"
            "    if (EntityInRadiusOfEntity(1056402601, entityId, 15, 1)) {\n"
            "        WaitFor(EventFlag(1056400200));\n"
            "    }\n"
            "    if (EntityInRadiusOfEntity(1056402602, entityId, 15, 1)) {\n"
            "        WaitFor(EventFlag(1056400205));\n"
            "    }\n"
            "    if (EntityInRadiusOfEntity(1056402603, entityId, 15, 1)) {\n"
            "        WaitFor(EventFlag(1056400210));\n"
            "    }\n"
            "    SetNetworkconnectedEventFlagID(eventFlagId, ON);\n"
            "});\n"
        )
        patched, n = emevd_patch.patch_preboss_wave_timeout(
            vanilla, 'common_func.emevd.dcx.js')
        assert n == 6, f'Expected 6 substitutions in 90015442, got {n}'
        # Each WaitFor should now end with `|| ElapsedSeconds(90))`
        for flag in ('1028400200', '1028400205', '1028400210',
                     '1056400200', '1056400205', '1056400210'):
            expected = f'WaitFor(EventFlag({flag}) || ElapsedSeconds(90));'
            assert expected in patched, (
                f'Missing patched form for flag {flag}: {expected!r}')

    def test_skips_non_common_func_filenames(self):
        """Patch only applies to common_func.emevd.dcx.js. Other filenames
        skipped via early return."""
        vanilla = (
            "$Event(90015442, Restart, function(entityId, eventFlagId) {\n"
            "    WaitFor(EventFlag(1028400200));\n"
            "});\n"
        )
        patched, n = emevd_patch.patch_preboss_wave_timeout(
            vanilla, 'm49_29_00_00.emevd.dcx.js')
        assert n == 0, 'Patch should skip non-common_func files'
        assert patched == vanilla, 'Content should be unchanged'

    def test_skips_already_patched(self):
        """Idempotency: WaitFors that already have ElapsedSeconds should
        not match the regex (which requires a closing `));` immediately
        after the EventFlag arg)."""
        already_patched = (
            "$Event(90015442, Restart, function(entityId, eventFlagId) {\n"
            "    if (EntityInRadiusOfEntity(1028402600, entityId, 15, 1)) {\n"
            "        WaitFor(EventFlag(1028400200) || ElapsedSeconds(90));\n"
            "    }\n"
            "});\n"
        )
        _, n = emevd_patch.patch_preboss_wave_timeout(
            already_patched, 'common_func.emevd.dcx.js')
        assert n == 0, f'Already-patched content should not re-match; got {n}'

    def test_scoped_to_event_90015442_only(self):
        """Regex is `WaitFor(EventFlag(NNN));` — generic enough that we
        rely on `replace_in_event` to scope it to 90015442. Confirm
        identical WaitFors in OTHER events are not touched."""
        mixed = (
            "$Event(90015442, Restart, function(entityId, eventFlagId) {\n"
            "    WaitFor(EventFlag(1028400200));\n"
            "});\n"
            "\n"
            "$Event(90015999, Default, function() {\n"
            "    WaitFor(EventFlag(1028400200));\n"  # should NOT be patched
            "});\n"
        )
        patched, n = emevd_patch.patch_preboss_wave_timeout(
            mixed, 'common_func.emevd.dcx.js')
        assert n == 1, f'Expected 1 substitution (only in 90015442), got {n}'
        # 90015999's WaitFor should still be bare
        assert (
            'WaitFor(EventFlag(1028400200));\n});' in patched or
            'WaitFor(EventFlag(1028400200));' in patched.split(
                '$Event(90015999')[1]
        ), '90015999 WaitFor should NOT have been patched'

    def test_does_not_apply_to_common_dot_emevd(self):
        """common.emevd.dcx.js is a sibling file with similar event IDs
        but different scope. Patch should only fire on common_func."""
        vanilla = (
            "$Event(90015442, Restart, function(entityId, eventFlagId) {\n"
            "    WaitFor(EventFlag(1028400200));\n"
            "});\n"
        )
        # 'common.emevd.dcx.js' does NOT start with 'common_func'
        patched, n = emevd_patch.patch_preboss_wave_timeout(
            vanilla, 'common.emevd.dcx.js')
        assert n == 0, (
            f'common.emevd.dcx.js should be skipped (not common_func); got {n}')


# ============================================================================
# v0.24.104: post_intro_aggro_kick
# ============================================================================
class TestPostIntroAggroKickV0_24_104:
    """v0.24.104 forces an AI re-plan after the terminal EnableCharacterAI
    in the proximity-wake-with-DisableAI family (90005250/251/260/261/271)
    so substituted bosses whose intrinsic entrance anim plays cleanly but
    leaves the AI stuck in Recognition/Alert get kicked back to Combat.

    Empirical trigger: Magma Wyrm (c4911) substituted for Guardian Golem
    (Cathedral) (c4660) at m38_00 pi=51. The cathedral slot wires the
    golem entity (38000850) through 90005251 with animationId=-1 — chr
    starts DisableAI, player approaches radius 13, EnableAI fires. Magma
    Wyrm's intrinsic emerge plays to completion (visible), healthbar
    appears (90015000 fires on Recognition), then chr idles indefinitely.

    Fix shape: append `WaitFixedTimeSeconds(5); RequestCharacterAIReplan(
    chrEntityId);` after the terminal EnableCharacterAI in each of the
    five handlers.

    Regression guards: scope, count, idempotency, file-filename gating.
    """

    # Synthetic minimal versions of the five proximity-wake-with-disable-AI
    # handlers — preserve exactly the lines the regex anchors on.
    _SYNTHETIC = """\
$Event(90005250, Restart, function(chrEntityId, areaEntityId, timeSeconds, animationId) {\r
    EndIf(ThisEventSlot());\r
    DisableCharacterAI(chrEntityId);\r
    WaitFor(area || HasDamageType(chrEntityId, 0, DamageType.Any));\r
    SetNetworkconnectedThisEventSlot(ON);\r
L1:\r
    EnableCharacterAI(chrEntityId);\r
});\r
\r
$Event(90005251, Restart, function(chrEntityId, targetDistance, timeSeconds, animationId) {\r
    EndIf(ThisEventSlot());\r
    DisableCharacterAI(chrEntityId);\r
    WaitFor(area);\r
    SetNetworkconnectedThisEventSlot(ON);\r
L1:\r
    EnableCharacterAI(chrEntityId);\r
});\r
\r
$Event(90005260, Restart, function(chrEntityId, areaEntityId, targetDistance, timeSeconds, animationId) {\r
    EndIf(ThisEventSlot());\r
    DisableCharacterAI(chrEntityId);\r
    WaitFor(area);\r
    SetNetworkconnectedThisEventSlot(ON);\r
L1:\r
    EnableCharacterAI(chrEntityId);\r
});\r
\r
$Event(90005261, Restart, function(chrEntityId, areaEntityId, targetDistance, timeSeconds, animationId) {\r
    EndIf(ThisEventSlot());\r
    DisableCharacterAI(chrEntityId);\r
    WaitFor(area);\r
    SetNetworkconnectedThisEventSlot(ON);\r
L1:\r
    EnableCharacterAI(chrEntityId);\r
});\r
\r
$Event(90005271, Restart, function(chrEntityId, timeSeconds, animationId) {\r
    EndIf(ThisEventSlot());\r
    DisableCharacterAI(chrEntityId);\r
    WaitFor(HasDamageType(chrEntityId, 0, DamageType.Any));\r
    SetNetworkconnectedThisEventSlot(ON);\r
L1:\r
    EnableCharacterAI(chrEntityId);\r
});\r
"""

    def test_patch_registered(self):
        import emevd_patch
        assert 'post_intro_aggro_kick' in emevd_patch.PATCHES

    def test_patches_all_five_handlers(self):
        """One substitution per handler — 5 total."""
        import emevd_patch
        patched, n = emevd_patch.patch_post_intro_aggro_kick(
            self._SYNTHETIC, 'common_func.emevd.dcx.js')
        assert n == 5, f'Expected 5 substitutions (one per handler), got {n}'

    def test_injects_correct_sequence(self):
        """After EnableCharacterAI: WaitFixedTimeSeconds(5) then
        RequestCharacterAIReplan, in that order."""
        import emevd_patch
        patched, _ = emevd_patch.patch_post_intro_aggro_kick(
            self._SYNTHETIC, 'common_func.emevd.dcx.js')
        # Each handler should contain the exact sequence
        for evid in ('90005250', '90005251', '90005260', '90005261', '90005271'):
            body_start = patched.index(f'$Event({evid},')
            body_end = patched.index('});', body_start) + 3
            body = patched[body_start:body_end]
            assert 'EnableCharacterAI(chrEntityId);' in body, evid
            assert 'WaitFixedTimeSeconds(5);' in body, evid
            assert 'RequestCharacterAIReplan(chrEntityId);' in body, evid
            # Order: EnableAI < Wait < Replan
            i_enable = body.index('EnableCharacterAI(chrEntityId);')
            i_wait = body.index('WaitFixedTimeSeconds(5);')
            i_replan = body.index('RequestCharacterAIReplan(chrEntityId);')
            assert i_enable < i_wait < i_replan, (
                f'Sequence wrong in {evid}: enable={i_enable} wait={i_wait} '
                f'replan={i_replan}')

    def test_idempotent(self):
        """Running the patch a second time must produce 0 substitutions —
        the anchor is `EnableCharacterAI(chrEntityId);\\r\\n});` and after
        the first pass the closing `});` is no longer immediately after
        the EnableCharacterAI line."""
        import emevd_patch
        once, n1 = emevd_patch.patch_post_intro_aggro_kick(
            self._SYNTHETIC, 'common_func.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_post_intro_aggro_kick(
            once, 'common_func.emevd.dcx.js')
        assert n1 == 5
        assert n2 == 0, f'Second pass should be 0; got {n2}'

    def test_filename_scoped_to_common_func(self):
        """Patch must only apply to common_func.emevd.dcx.js."""
        import emevd_patch
        for fname in ('m38_00_00_00.emevd.dcx.js',
                      'm60_42_36_50.emevd.dcx.js',
                      'common.emevd.dcx.js',  # sibling, NOT common_func
                      'random.txt'):
            _, n = emevd_patch.patch_post_intro_aggro_kick(
                self._SYNTHETIC, fname)
            assert n == 0, f'Patch must skip {fname} (got {n} subs)'

    def test_does_not_patch_unrelated_enable_character_ai(self):
        """EnableCharacterAI calls in other events must be untouched —
        the regex requires the closing `});` immediately after, scoping
        it to the LAST EnableCharacterAI in a handler. An intermediate
        EnableCharacterAI in another event (with code after it) must not
        be matched."""
        import emevd_patch
        sample = (
            '$Event(90099999, Default, function(chrEntityId) {\r\n'
            '    EnableCharacterAI(chrEntityId);\r\n'  # intermediate, NOT terminal
            '    WaitFixedTimeSeconds(10);\r\n'
            '    DisableCharacterAI(chrEntityId);\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.patch_post_intro_aggro_kick(
            sample, 'common_func.emevd.dcx.js')
        assert n == 0, 'Intermediate EnableCharacterAI must not be patched'

    def test_full_bundle_substitution_count(self):
        """Applied to patched_emevd/common_func.emevd.dcx.js, exactly 5
        substitutions (one terminal EnableCharacterAI per scoped event)."""
        import emevd_patch
        path = os.path.join(ROOT, 'patched_emevd', 'common_func.emevd.dcx.js')
        if not os.path.exists(path):
            pytest.skip('patched_emevd/common_func.emevd.dcx.js not in repo')
        with open(path, 'rb') as f:
            original = f.read().decode('utf-8')
        _, n = emevd_patch.patch_post_intro_aggro_kick(
            original, 'common_func.emevd.dcx.js')
        assert n == 5, (
            f'Expected exactly 5 substitutions on full bundle; got {n}. If '
            f'the upstream common_func structure changed (handler renamed, '
            f'EnableCharacterAI moved, closing braces refactored), the '
            f'regex anchor needs updating.')

    def test_landing_in_audit_already_patched_set(self):
        """The 90005250-271 EIDs must be listed in the audit's
        already_patched set so the audit command shows ✓ rather than ⚠
        new-candidate for them."""
        import emevd_patch, inspect
        src = inspect.getsource(emevd_patch.cmd_audit)
        # Crude but sufficient — the set literal is in cmd_audit's body
        for evid in ('90005250', '90005251', '90005260', '90005261', '90005271'):
            assert evid in src, (
                f'cmd_audit already_patched set missing {evid}; audit '
                f'output will misclassify it as an unpatched candidate.')


# ============================================================================
# v0.24.105 (RETIRED v0.24.106): nb_wave_bypass
# ============================================================================
class TestNbWaveBypassRetiredV0_24_106:
    """v0.24.105 nb_wave_bypass was retired in v0.24.106 because the
    architecture was wrong: $Event(99055100) is Default mode and is
    registered per-arena via $InitializeCommonEvent in each Event(0),
    which means it fires ONCE AT MAP LOAD — setting the bypass flag at
    map load, which would release the XXXX2810 WaitFor at map load and
    spawn the boss the instant the player enters the arena. The intended
    semantic was "fire only as a recovery action triggered by a watcher"
    but the watcher was never built and Default-mode registration
    short-circuits straight to fire.

    The actual symptom (N2 minion wave not starting) is better addressed
    by adding a timeout to the WaitFor itself — see
    TestXxxx2810TriggerTimeoutV0_24_106 below.

    These tests assert nb_wave_bypass is unregistered and confirm the
    function body is kept for reference (matching the retirement pattern
    used by permissive_boss_wake / permissive_spawn_emerge / boss_reward_inject
    / disable_corpse_collision / preboss_wake_timeout).
    """

    def test_patch_no_longer_registered(self):
        import emevd_patch
        assert 'nb_wave_bypass' not in emevd_patch.PATCHES, (
            'nb_wave_bypass was retired in v0.24.106 — it should no longer '
            'appear in the PATCHES registry. If you re-registered it, '
            'either the retirement was reverted intentionally (update '
            'this test) or by accident (remove the @register decorator).')

    def test_function_still_exists_for_reference(self):
        """The function body is kept in the source for design-discussion
        value (the bypass-flag picker rule, the 99055100 atomic-claim
        ordering) — it's just not registered. If a future watcher-based
        architecture revives the approach, the function is the starting
        point."""
        import emevd_patch
        assert hasattr(emevd_patch, 'patch_nb_wave_bypass'), (
            'patch_nb_wave_bypass function body removed entirely — keep '
            'it in the source per the retirement convention (see '
            'permissive_boss_wake, etc.)')


# ============================================================================
# v0.24.106: xxxx2810_trigger_timeout
# ============================================================================
class TestXxxx2810TriggerTimeoutV0_24_106:
    """v0.24.106 adds a 90s safety-net timeout to the
    WaitFor(EventFlag(eventFlagId3)) gate in each NB arena's
    $Event(XXXX2810). Replaces the retired nb_wave_bypass approach with
    the simpler timeout pattern shared by nb_speffect_wait_timeout
    (10s on CharacterHasSpEffect waits) and preboss_wave_timeout
    (90s on 90015442's tile waits).
    """

    def test_patch_registered(self):
        import emevd_patch
        assert 'xxxx2810_trigger_timeout' in emevd_patch.PATCHES

    # Minimal m49_29-shaped stub: just $Event(49292810) with the
    # WaitFor we're targeting. Real m49_29 is 267 lines; we don't need
    # the rest.
    _M49_29_STUB = """\
$Event(49292810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5, chrEntityId2, chrEntityId3) {\r
    DisableCharacter(chrEntityId);\r
    DisableCharacterAI(chrEntityId);\r
    WaitFor(EventFlag(eventFlagId3));\r
    EnableCharacterAI(chrEntityId);\r
});\r
"""

    def test_widens_m49_29_waitfor(self):
        """The eventFlagId3 WaitFor gets `|| ElapsedSeconds(90)` appended,
        with the original expression parenthesized for operator-precedence
        safety (|| binds looser than &&, so the outer parens make the
        precedence explicit even though it doesn't affect this specific
        expression)."""
        import emevd_patch
        patched, n = emevd_patch.patch_xxxx2810_trigger_timeout(
            self._M49_29_STUB, 'm49_29_00_00.emevd.dcx.js')
        assert n == 1, f'Expected 1 substitution for m49_29; got {n}'
        assert 'WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));' in patched
        # Original (un-timed) line should be replaced, not duplicated
        assert 'WaitFor(EventFlag(eventFlagId3));' not in patched

    def test_widens_m48_arenas_too(self):
        """Every m48_NN arena has the same WaitFor pattern; the patch
        is map-agnostic. Test with m48_50 (Cathedral) which is a
        canonical single-boss NB arena."""
        import emevd_patch
        m48_50_stub = self._M49_29_STUB.replace('49292810', '48502810')
        patched, n = emevd_patch.patch_xxxx2810_trigger_timeout(
            m48_50_stub, 'm48_50_00_00.emevd.dcx.js')
        assert n == 1
        assert 'ElapsedSeconds(90)' in patched

    def test_idempotent(self):
        """Re-running on patched content adds zero substitutions. The
        idempotency guard is `'ElapsedSeconds' in expr` — anything that
        already has a timeout is left alone."""
        import emevd_patch
        once, n1 = emevd_patch.patch_xxxx2810_trigger_timeout(
            self._M49_29_STUB, 'm49_29_00_00.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_xxxx2810_trigger_timeout(
            once, 'm49_29_00_00.emevd.dcx.js')
        assert n1 == 1
        assert n2 == 0, f'second pass should be 0; got {n2}'
        assert twice == once, 'second pass must not modify content'

    def test_skips_already_patched_with_other_timeouts(self):
        """Lines that already have ElapsedSeconds (e.g. from
        nb_speffect_wait_timeout's 10s timeout on CharacterHasSpEffect)
        are not re-patched. The match is content-keyed on
        'eventFlagId3', not on the WaitFor shape, so we won't
        accidentally re-time the SpEffect wait."""
        import emevd_patch
        sample = (
            '$Event(49292810, Restart, function(...) {\r\n'
            '    WaitFor((CharacterHasSpEffect(chrEntityId, 10583)) || ElapsedSeconds(10));\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.patch_xxxx2810_trigger_timeout(
            sample, 'm49_29_00_00.emevd.dcx.js')
        assert n == 0
        assert patched == sample

    def test_tolerates_retired_nb_wave_bypass_artifact(self):
        """If a file has the nb_wave_bypass artifact left from a stale
        build — `WaitFor(EventFlag(eventFlagId3) || EventFlag(NNNNNNNN))`
        — the new patch still adds a timeout. The result is functional
        (the bypass flag is never set because 99055100 is unregistered,
        so the extra OR clause is dead weight but not harmful)."""
        import emevd_patch
        sample = (
            '$Event(49292810, Restart, function(...) {\r\n'
            '    WaitFor(EventFlag(eventFlagId3) || EventFlag(49290290));\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.patch_xxxx2810_trigger_timeout(
            sample, 'm49_29_00_00.emevd.dcx.js')
        assert n == 1
        assert 'ElapsedSeconds(90)' in patched
        # Bypass-flag OR still present (we don't try to scrub it)
        assert 'EventFlag(49290290)' in patched

    def test_skips_non_per_map_files(self):
        """common_func, common, m30, m38, etc. should all be untouched.
        The patch filename filter is m4[89]_\\d+_\\d+_\\d+\\."""
        import emevd_patch
        sample = self._M49_29_STUB  # has eventFlagId3 in it
        for fname in ('common_func.emevd.dcx.js',
                      'common.emevd.dcx.js',
                      'm30_30_00_00.emevd.dcx.js',
                      'm38_10_00_00.emevd.dcx.js',
                      'm60_43_37_00.emevd.dcx.js',
                      'm32_00_00_00.emevd.dcx.js',
                      'm47_70_00_00.emevd.dcx.js'):
            patched, n = emevd_patch.patch_xxxx2810_trigger_timeout(sample, fname)
            assert n == 0, f'{fname}: expected 0 subs, got {n}'
            assert patched == sample

    def test_does_not_touch_other_waitfors_in_same_file(self):
        """A file with multiple WaitFors should only get the one tied to
        eventFlagId3 timed. Other WaitFors (e.g. CharacterHasSpEffect,
        EventFlag with a different parameter, or EventFlag with a literal)
        are left alone."""
        import emevd_patch
        sample = (
            '$Event(49292810, Restart, function(...) {\r\n'
            '    WaitFor(EventFlag(eventFlagId3));\r\n'  # ← should be patched
            '    WaitFor(EventFlag(eventFlagId));\r\n'    # ← different param, untouched
            '    WaitFor(EventFlag(8035));\r\n'           # ← literal flag, untouched
            '    WaitFor(CharacterRatioDead(chrEntityId));\r\n'  # ← death wait, untouched
            '});\r\n'
        )
        patched, n = emevd_patch.patch_xxxx2810_trigger_timeout(
            sample, 'm49_29_00_00.emevd.dcx.js')
        assert n == 1, f'Expected exactly 1 sub; got {n}'
        assert 'WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));' in patched
        assert 'WaitFor(EventFlag(eventFlagId));' in patched  # untouched
        assert 'WaitFor(EventFlag(8035));' in patched  # untouched
        assert 'WaitFor(CharacterRatioDead(chrEntityId));' in patched  # untouched

    def test_full_vanilla_bundle_substitution_count(self):
        """Apply to a vanilla-shaped bundle (every NB arena file with the
        eventFlagId3 pattern) and confirm exactly 25 substitutions —
        the count of NB arenas in vanilla NR with XXXX2810 events.
        Skips m49_40 and m49_42 (no XXXX2810)."""
        import emevd_patch
        # 25 NB arena stems from vanilla NR
        nb_arena_stems = (
            'm48_00_00_00', 'm48_10_00_00', 'm48_20_00_00', 'm48_30_00_00',
            'm48_40_00_00', 'm48_50_00_00', 'm48_60_00_00', 'm48_70_00_00',
            'm48_80_00_00', 'm48_90_00_00',
            'm49_10_00_00', 'm49_17_00_00', 'm49_18_00_00', 'm49_19_00_00',
            'm49_20_00_00', 'm49_21_00_00', 'm49_23_00_00', 'm49_24_00_00',
            'm49_25_00_00', 'm49_26_00_00', 'm49_27_00_00', 'm49_28_00_00',
            'm49_29_00_00', 'm49_30_00_00', 'm49_90_00_00',
        )
        total_subs = 0
        for stem in nb_arena_stems:
            fname = f'{stem}.emevd.dcx.js'
            event_id_str = stem.replace('m', '').replace('_', '')[:5] + '2810'
            stub = (
                f'$Event({event_id_str}, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3) {{\r\n'
                f'    WaitFor(EventFlag(eventFlagId3));\r\n'
                f'}});\r\n'
            )
            _, n = emevd_patch.patch_xxxx2810_trigger_timeout(stub, fname)
            total_subs += n
        assert total_subs == 25, (
            f'Expected 25 substitutions (one per NB arena); got {total_subs}. '
            f'A mismatch usually means the regex pattern stopped matching '
            f'one of the arenas — re-inspect _patch_line in '
            f'patch_xxxx2810_trigger_timeout.')


# ============================================================================
# v0.24.107: nb_boss_force_enable_watchdog
# ============================================================================
class TestNbBossForceEnableWatchdogV0_24_107:
    """v0.24.107 adds a force-enable recovery watchdog for stalled NB boss
    spawns. New common_func event $Event(99055200, Restart, ...) that fires
    on EventFlag(7530) ON + 120s timeout, then EnableCharacter's every
    known NB arena boss entity ID (50 entities across 25 arenas).

    Regression guards: registration, event body structure, scope (common_func
    only), idempotency, entity coverage, restart-mode WaitFor pattern.
    """

    def test_patch_registered(self):
        import emevd_patch
        assert 'nb_boss_force_enable_watchdog' in emevd_patch.PATCHES

    def test_entity_id_constant_complete(self):
        """The _NB_BOSS_ENTITY_IDS constant must cover all 25 NB arenas.
        Each entry must be (stem, boss_800, boss_810) where the entity IDs
        match the canonical XXX00800 / XXX00810 pattern."""
        import emevd_patch
        ids = emevd_patch._NB_BOSS_ENTITY_IDS
        assert len(ids) == 25, f'Expected 25 NB arenas; got {len(ids)}'
        for stem, b800, b810 in ids:
            # Format check: every stem is mXX_XX_00_00
            import re as _re
            assert _re.match(r'^m4[89]_\d+_00_00$', stem), \
                f'Stem {stem!r} doesn\'t match expected m4X_XX_00_00 pattern'
            # boss_810 must be boss_800 + 10
            assert b810 == b800 + 10, \
                f'{stem}: head2={b810}, expected boss+10={b800+10}'
            # Sanity: must end in 800
            assert b800 % 1000 == 800, \
                f'{stem}: boss={b800} doesn\'t end in 800'
        # Spot-check known cases
        ids_dict = {stem: (b800, b810) for stem, b800, b810 in ids}
        assert ids_dict['m48_40_00_00'] == (48400800, 48400810)
        assert ids_dict['m48_60_00_00'] == (48600800, 48600810)
        assert ids_dict['m49_29_00_00'] == (49290800, 49290810)

    def test_event_body_structure(self):
        """v0.24.110 redesign: per-arena event taking (triggerFlag,
        bossEntity1, bossEntity2) parameters, armed on trigger flag.

        Body must contain:
        - $Event(99055200, Restart, function(triggerFlag, bossEntity1, bossEntity2) {
        - WaitFor(EventFlag(triggerFlag)) — encounter-start arming
        - WaitFor(ElapsedSeconds(N)) — give vanilla time
        - PlaySE tracers (audible)
        - EnableCharacter / EnableCharacterAI / etc on bossEntity1, bossEntity2
        - WaitFor(!EventFlag(triggerFlag)) — cooldown until encounter ends
        - No literal entity IDs in body (substituted at runtime via params)
        - No 7530 (the v107 EventFlag arming gate, dropped in v108)
        - No !CharacterDead(20000) (the v108 wallclock+alive gate, dropped
          in v110 because it was firing during menus/N1 not N2)
        """
        import emevd_patch
        body = emevd_patch._build_force_enable_event_body(timeout_seconds=60)

        # Header takes parameters
        assert '$Event(99055200, Restart, function(triggerFlag, bossEntity1, bossEntity2) {' in body
        # Arming on encounter-start flag (parameter, not literal)
        assert 'WaitFor(EventFlag(triggerFlag));' in body
        # Timeout
        assert 'WaitFor(ElapsedSeconds(60));' in body
        # Force-enable uses parameters (not literal entity IDs)
        assert 'EnableCharacter(bossEntity1);' in body
        assert 'EnableCharacter(bossEntity2);' in body
        # Cooldown on encounter-end
        assert 'WaitFor(!EventFlag(triggerFlag));' in body
        # PlaySE tracers
        assert 'PlaySE(20000, SoundType.SFX, 888880000);' in body
        # Retired arming gates must not return
        assert 'EventFlag(7530)' not in body, (
            "v107 7530 arming was retired — should not be in v110 body.")
        assert 'CharacterDead(20000)' not in body, (
            "v108 !CharacterDead(20000) arming was retired in v110 — "
            "should not be in the body.")
        # No explicit RestartEvent
        assert 'RestartEvent()' not in body

    def test_tracers_can_be_disabled(self):
        """Audio tracers add value at playtest but can be disabled for
        production. With tracers=False, no PlaySE calls appear."""
        import emevd_patch
        body_with = emevd_patch._build_force_enable_event_body(tracers=True)
        body_without = emevd_patch._build_force_enable_event_body(tracers=False)
        assert 'PlaySE(20000' in body_with
        assert 'PlaySE(20000' not in body_without
        # EnableCharacter on the parameter names is unchanged either way
        assert 'EnableCharacter(bossEntity1);' in body_with
        assert 'EnableCharacter(bossEntity1);' in body_without

    def test_timeout_is_configurable(self):
        """Timeout value flows through to the rendered body."""
        import emevd_patch
        body_30 = emevd_patch._build_force_enable_event_body(timeout_seconds=30)
        body_120 = emevd_patch._build_force_enable_event_body(timeout_seconds=120)
        assert 'ElapsedSeconds(30)' in body_30
        assert 'ElapsedSeconds(120)' in body_120
        assert 'ElapsedSeconds(120)' not in body_30
        assert 'ElapsedSeconds(30)' not in body_120

    def test_per_arena_registration_count(self):
        """v0.24.110: the patch registers 99055200 per-arena via
        $InitializeCommonEvent in each NB arena's Event(0). Apply to
        25 stubs (one per arena) and verify each gets exactly one
        registration with that arena's (triggerFlag, bossEntity1,
        bossEntity2)."""
        import emevd_patch, re as _re
        nb_stems_and_entities = list(emevd_patch._NB_BOSS_ENTITY_IDS)
        assert len(nb_stems_and_entities) == 25
        total_subs = 0
        for stem, boss1, boss2 in nb_stems_and_entities:
            anchor, flag = emevd_patch._arena_entry_args(stem)
            stub = (
                f'$Event(0, Default, function() {{\r\n'
                f'    $InitializeCommonEvent(0, 90015442, {anchor}, {flag});\r\n'
                f'}});\r\n'
            )
            patched, n = emevd_patch.patch_nb_boss_force_enable_watchdog(
                stub, f'{stem}.emevd.dcx.js')
            total_subs += n
            # Verify this arena's registration uses its own (flag, boss1, boss2)
            expected = f'$InitializeCommonEvent(0, 99055200, {flag}, {boss1}, {boss2});'
            assert expected in patched, (
                f'{stem}: missing registration with its own values. '
                f'Expected {expected!r}')
        assert total_subs == 25, (
            f'Expected 25 per-arena registrations; got {total_subs}')

    def test_inject_into_common_func(self):
        """Apply patch to a minimal common_func stub; one substitution
        expected, parameterized event appended."""
        import emevd_patch
        sample = (
            '// ==EMEVD==\r\n'
            '$Event(1000, Default, function() {\r\n'
            '    NoOp();\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.patch_nb_boss_force_enable_watchdog(
            sample, 'common_func.emevd.dcx.js')
        assert n == 1
        # v110: parameterized event signature
        assert '$Event(99055200, Restart, function(triggerFlag, bossEntity1, bossEntity2) {' in patched
        assert sample in patched

    def test_idempotent(self):
        """Re-running on already-patched common_func is a no-op."""
        import emevd_patch
        once, n1 = emevd_patch.patch_nb_boss_force_enable_watchdog(
            'common_func sample\r\n', 'common_func.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_nb_boss_force_enable_watchdog(
            once, 'common_func.emevd.dcx.js')
        assert n1 == 1
        assert n2 == 0
        assert twice == once

    def test_skips_non_arena_per_map_files(self):
        """v0.24.110: per-map files that ARE NB arenas get a per-arena
        registration; per-map files that are NOT NB arenas (m30, m38,
        m47_70 Tibia, etc.) must be untouched."""
        import emevd_patch
        # Stub with 90015442 line that the patch would normally inject near,
        # but with a non-NB-arena filename
        sample = (
            '$Event(0, Default, function() {\r\n'
            '    $InitializeCommonEvent(0, 90015442, 47702200, 47700200);\r\n'
            '});\r\n'
        )
        for fname in ('m47_70_00_00.emevd.dcx.js',  # Tibia, not NB
                      'm30_30_00_00.emevd.dcx.js',
                      'common.emevd.dcx.js'):
            patched, n = emevd_patch.patch_nb_boss_force_enable_watchdog(
                sample, fname)
            assert n == 0, f'{fname}: expected 0 subs; got {n}'
            assert patched == sample

    def test_per_arena_registers_known_failing_arenas(self):
        """m48_40 and m48_60 are the two Tricephalos N2 candidates. Both
        must get registered with their correct (flag, boss1, boss2)
        triples."""
        import emevd_patch
        for stem, expected_flag, expected_boss1, expected_boss2 in (
                ('m48_40_00_00', 48400200, 48400800, 48400810),
                ('m48_60_00_00', 48600200, 48600800, 48600810),
                ('m49_29_00_00', 49290200, 49290800, 49290810),
        ):
            stub = (
                f'$Event(0, Default, function() {{\r\n'
                f'    $InitializeCommonEvent(0, 90015442, {expected_flag - 200 + 2200}, {expected_flag});\r\n'
                f'}});\r\n'
            )
            patched, n = emevd_patch.patch_nb_boss_force_enable_watchdog(
                stub, f'{stem}.emevd.dcx.js')
            assert n == 1
            expected_line = f'$InitializeCommonEvent(0, 99055200, {expected_flag}, {expected_boss1}, {expected_boss2});'
            assert expected_line in patched, (
                f'{stem}: registration missing or wrong. Expected: {expected_line!r}')


# ============================================================================
# v0.24.109: nb_arena_entry_trigger
# ============================================================================
class TestNbArenaEntryTriggerV0_24_109:
    """v0.24.109 adds a player-initiated arena trigger. New common_func
    event $Event(99055300, Restart) watches player proximity to an
    arena-center anchor and sets the arena trigger flag when the player
    approaches. Coexists idempotently with vanilla 90015442 ring-close flow.

    Regression guards: registration, derivation math, event body shape,
    per-arena injection, idempotency, scope (NB arenas only).
    """

    def test_patch_registered(self):
        import emevd_patch
        assert 'nb_arena_entry_trigger' in emevd_patch.PATCHES

    def test_anchor_flag_derivation_known_cases(self):
        """Anchor + flag derivation must match the values vanilla
        90015442 InitializeCommonEvent passes for each NB arena.
        These are the same pairs the new InitializeCommonEvent(0,
        99055300, ...) registrations use."""
        import emevd_patch
        cases = (
            # (stem, expected_anchor, expected_flag)
            ('m48_00_00_00', 48002200, 48000200),
            ('m48_40_00_00', 48402200, 48400200),
            ('m48_60_00_00', 48602200, 48600200),
            ('m48_90_00_00', 48902200, 48900200),
            ('m49_10_00_00', 49102200, 49100200),
            ('m49_29_00_00', 49292200, 49290200),
            ('m49_30_00_00', 49302200, 49300200),
            ('m49_90_00_00', 49902200, 49900200),
        )
        for stem, exp_anchor, exp_flag in cases:
            anchor, flag = emevd_patch._arena_entry_args(stem)
            assert (anchor, flag) == (exp_anchor, exp_flag), (
                f'{stem}: derived ({anchor}, {flag}), '
                f'expected ({exp_anchor}, {exp_flag})')

    def test_event_body_shape(self):
        """The rendered event body must contain the idempotent guards
        (two EndIfs around the WaitFor) and the network-synced flag
        write."""
        import emevd_patch
        body = emevd_patch._build_arena_entry_trigger_event_body()
        assert '$Event(99055300, Restart, function(anchorEntity, triggerFlag) {' in body
        # Two idempotency guards
        assert body.count('EndIf(EventFlag(triggerFlag));') == 2, (
            'Expected two EndIf guards (one pre-WaitFor, one post)')
        # Proximity check
        assert 'EntityInRadiusOfEntity(20000, anchorEntity, 20, 1)' in body
        # Network-synced flag set
        assert 'SetNetworkconnectedEventFlagID(triggerFlag, ON);' in body
        # Should NOT use plain SetEventFlag (would break in co-op)
        assert 'SetEventFlag(triggerFlag' not in body

    def test_radius_is_20m_for_player_agency(self):
        """20m chosen empirically: larger than vanilla 90015442's 15m
        so the player triggers it before the ring naturally would,
        ensuring player agency. If this changes, retune in playtest."""
        import emevd_patch
        body = emevd_patch._build_arena_entry_trigger_event_body()
        assert 'EntityInRadiusOfEntity(20000, anchorEntity, 20, 1)' in body
        # Configurable
        custom = emevd_patch._build_arena_entry_trigger_event_body(radius=10)
        assert 'EntityInRadiusOfEntity(20000, anchorEntity, 10, 1)' in custom

    def test_common_func_injection(self):
        """common_func gets the new $Event(99055300) appended; one sub."""
        import emevd_patch
        sample = '$Event(1, Default, function() {});\r\n'
        patched, n = emevd_patch.patch_nb_arena_entry_trigger(
            sample, 'common_func.emevd.dcx.js')
        assert n == 1
        assert '$Event(99055300, Restart, function(anchorEntity, triggerFlag) {' in patched

    def test_common_func_idempotent(self):
        """Second pass on common_func is no-op."""
        import emevd_patch
        once, n1 = emevd_patch.patch_nb_arena_entry_trigger(
            '$Event(1, Default, function() {});\r\n', 'common_func.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_nb_arena_entry_trigger(
            once, 'common_func.emevd.dcx.js')
        assert n1 == 1
        assert n2 == 0
        assert twice == once

    # Real-shape m48_60 Event(0) stub, includes the 90015442 line we
    # piggy-back on for indent-preserving injection.
    _M48_60_STUB = """\
$Event(0, Default, function() {\r
    if (IsMapVariation(2)) {\r
        $InitializeCommonEvent(0, 90015442, 48602200, 48600200);\r
    }\r
    $InitializeCommonEvent(0, 90065050, 48600200, 48600205);\r
});\r
"""

    def test_per_arena_injection(self):
        """Per-arena patch injects a new InitializeCommonEvent line
        adjacent to (and with the same indent as) the existing 90015442
        line, using that arena's anchor + flag."""
        import emevd_patch
        patched, n = emevd_patch.patch_nb_arena_entry_trigger(
            self._M48_60_STUB, 'm48_60_00_00.emevd.dcx.js')
        assert n == 1
        # m48_60: anchor 48602200, flag 48600200
        assert '$InitializeCommonEvent(0, 99055300, 48602200, 48600200);' in patched
        # Should be inside Event(0), adjacent to the 90015442 line
        idx_90015442 = patched.index('90015442, 48602200, 48600200')
        idx_99055300 = patched.index('99055300, 48602200, 48600200')
        # 99055300 line comes AFTER the 90015442 line (we insert just after)
        assert idx_99055300 > idx_90015442
        # Both inside Event(0) — before the closing });
        ev0_end = patched.rindex('});')
        assert idx_99055300 < ev0_end

    def test_per_arena_uses_correct_per_arena_values(self):
        """When patching m49_29, the registration must use m49_29's
        anchor + flag, NOT m48_60's. Catches a class of lookup bugs."""
        import emevd_patch
        m49_29_stub = self._M48_60_STUB.replace('48602200', '49292200').replace('48600200', '49290200').replace('48600205', '49290205').replace('90065050', '90065910')
        patched, n = emevd_patch.patch_nb_arena_entry_trigger(
            m49_29_stub, 'm49_29_00_00.emevd.dcx.js')
        assert n == 1
        assert '$InitializeCommonEvent(0, 99055300, 49292200, 49290200);' in patched
        # m48_60's flag must NOT appear in m49_29's output
        assert '48602200' not in patched
        assert '48600200' not in patched

    def test_per_arena_idempotent(self):
        """Re-running on patched per-arena content is a no-op."""
        import emevd_patch
        once, n1 = emevd_patch.patch_nb_arena_entry_trigger(
            self._M48_60_STUB, 'm48_60_00_00.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_nb_arena_entry_trigger(
            once, 'm48_60_00_00.emevd.dcx.js')
        assert n1 == 1
        assert n2 == 0, f'Second pass expected 0; got {n2}'
        assert twice == once

    def test_skips_non_nb_arenas(self):
        """Per-map files that aren't NB arenas (m30, m38, m47_70 Tibia,
        etc.) are untouched even if they happen to contain a 90015442
        InitializeCommonEvent (m47_70 does)."""
        import emevd_patch
        # m47_70 has the same shape but isn't an NB arena in our scope
        sample = self._M48_60_STUB.replace('48602200', '47702200').replace('48600200', '47700200')
        for fname in ('m47_70_00_00.emevd.dcx.js',
                      'm30_30_00_00.emevd.dcx.js',
                      'm38_10_00_00.emevd.dcx.js',
                      'common.emevd.dcx.js'):
            patched, n = emevd_patch.patch_nb_arena_entry_trigger(sample, fname)
            assert n == 0, f'{fname}: expected 0 subs, got {n}'
            assert patched == sample

    def test_skips_arena_without_90015442_line(self):
        """If an NB arena somehow lacks the 90015442 anchor line, the
        patch skips gracefully rather than injecting in a weird spot.
        (Defensive — shouldn't happen for the known 25 arenas, but a
        future game patch could change the convention.)"""
        import emevd_patch
        sample = (
            '$Event(0, Default, function() {\r\n'
            '    NoOp();\r\n'
            '});\r\n'
        )
        patched, n = emevd_patch.patch_nb_arena_entry_trigger(
            sample, 'm48_60_00_00.emevd.dcx.js')
        assert n == 0
        assert patched == sample

    def test_full_bundle_substitution_count(self):
        """Apply to a per-arena bundle for each of the 25 NB arenas;
        should get 25 subs (1 per arena). Plus 1 in common_func = 26
        when applied to a full bundle."""
        import emevd_patch
        total = 0
        nb_stems = sorted({s for s, _, _ in emevd_patch._NB_BOSS_ENTITY_IDS})
        assert len(nb_stems) == 25
        for stem in nb_stems:
            anchor, flag = emevd_patch._arena_entry_args(stem)
            stub = (
                f'$Event(0, Default, function() {{\r\n'
                f'    $InitializeCommonEvent(0, 90015442, {anchor}, {flag});\r\n'
                f'}});\r\n'
            )
            _, n = emevd_patch.patch_nb_arena_entry_trigger(
                stub, f'{stem}.emevd.dcx.js')
            total += n
        assert total == 25, (
            f'Expected 25 per-arena subs; got {total}. A mismatch means '
            f'_arena_entry_args() or the injection regex broke for one arena.')


# ============================================================================
# v0.24.111: nb_arena_hold_trigger
# ============================================================================
class TestNbArenaHoldTriggerV0_24_111:
    """v0.24.111 adds a player-deliberate hold-to-trigger arena starter.
    Player stands within 5m of arena center for 3 continuous seconds;
    on completion, AV feedback (loud SFX + boss-defeat banner) plus
    setting the arena trigger flag. Distinct from v0.24.109 entry trigger
    (20m, no hold, no feedback) — this one is the diagnostic-grade
    deliberate trigger.

    Regression guards: registration, event body shape (AV feedback,
    hold-cancellation), per-arena injection, idempotency.
    """

    def test_patch_registered(self):
        import emevd_patch
        assert 'nb_arena_hold_trigger' in emevd_patch.PATCHES

    def test_event_body_av_feedback(self):
        """The hold trigger's defining feature is unmissable AV feedback
        on completion. Verify both SFX and on-screen banner are present."""
        import emevd_patch
        body = emevd_patch._build_arena_hold_trigger_event_body()
        # Audible: PlaySE on the player entity (20000)
        assert 'PlaySE(20000, SoundType.SFX, 888880000);' in body
        # Visible: boss-defeat banner (DisplayTextEffectId(1020))
        assert 'DisplayTextEffectId(1020);' in body

    def test_event_body_hold_cancellation(self):
        """Player leaving the radius mid-hold must cancel the trigger.
        Achieved via OR-clause in the hold WaitFor + EndIf guard."""
        import emevd_patch
        body = emevd_patch._build_arena_hold_trigger_event_body()
        # OR-clause races duration against leaving
        # v0.24.x tuning: hold-radius is 25 (was 5 in the original draft)
        assert 'WaitFor(ElapsedSeconds(3) || !EntityInRadiusOfEntity(20000, anchorEntity, 25, 1));' in body
        # EndIf cancels if player left
        assert 'EndIf(!EntityInRadiusOfEntity(20000, anchorEntity, 25, 1));' in body

    def test_event_body_idempotency_guards(self):
        """Two EndIf(EventFlag(triggerFlag)) guards: one at top (if
        vanilla already fired), one after hold (if vanilla fired
        during hold). Network-synced flag set."""
        import emevd_patch
        body = emevd_patch._build_arena_hold_trigger_event_body()
        assert body.count('EndIf(EventFlag(triggerFlag));') == 2
        assert 'SetNetworkconnectedEventFlagID(triggerFlag, ON);' in body
        assert 'SetEventFlag(triggerFlag' not in body  # would break in co-op

    def test_radius_and_hold_configurable(self):
        """5m radius and 3s hold are empirical defaults; tunable at
        the function level for future polish."""
        import emevd_patch
        custom = emevd_patch._build_arena_hold_trigger_event_body(
            radius=8, hold_seconds=2)
        assert 'EntityInRadiusOfEntity(20000, anchorEntity, 8, 1)' in custom
        assert 'ElapsedSeconds(2)' in custom

    def test_common_func_injection(self):
        import emevd_patch
        sample = '$Event(1, Default, function() {});\r\n'
        patched, n = emevd_patch.patch_nb_arena_hold_trigger(
            sample, 'common_func.emevd.dcx.js')
        assert n == 1
        assert '$Event(99055400, Restart, function(anchorEntity, triggerFlag) {' in patched

    def test_common_func_idempotent(self):
        import emevd_patch
        once, n1 = emevd_patch.patch_nb_arena_hold_trigger(
            '$Event(1, Default, function() {});\r\n', 'common_func.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_nb_arena_hold_trigger(
            once, 'common_func.emevd.dcx.js')
        assert n1 == 1
        assert n2 == 0
        assert twice == once

    _M48_60_STUB = """\
$Event(0, Default, function() {\r
    if (IsMapVariation(2)) {\r
        $InitializeCommonEvent(0, 90015442, 48602200, 48600200);\r
    }\r
});\r
"""

    def test_per_arena_injection(self):
        import emevd_patch
        patched, n = emevd_patch.patch_nb_arena_hold_trigger(
            self._M48_60_STUB, 'm48_60_00_00.emevd.dcx.js')
        assert n == 1
        # m48_60: anchor 48602200, flag 48600200
        assert '$InitializeCommonEvent(0, 99055400, 48602200, 48600200);' in patched

    def test_per_arena_idempotent(self):
        import emevd_patch
        once, n1 = emevd_patch.patch_nb_arena_hold_trigger(
            self._M48_60_STUB, 'm48_60_00_00.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_nb_arena_hold_trigger(
            once, 'm48_60_00_00.emevd.dcx.js')
        assert n1 == 1
        assert n2 == 0
        assert twice == once

    def test_skips_non_nb_arenas(self):
        import emevd_patch
        sample = self._M48_60_STUB
        for fname in ('m47_70_00_00.emevd.dcx.js',
                      'm30_30_00_00.emevd.dcx.js',
                      'common.emevd.dcx.js'):
            _, n = emevd_patch.patch_nb_arena_hold_trigger(sample, fname)
            assert n == 0
