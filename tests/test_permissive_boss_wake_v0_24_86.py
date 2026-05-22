"""Behavioral tests for the v0.24.86 permissive_boss_wake scope expansion.

Drop in alongside the existing tests/test_emevd_patches.py registry tests.
These catch:
  - Accidental scope reduction (someone removes a new event from the allowlist)
  - Allowlist-bypass regression (someone removes the per-event loop and
    blanket-applies the regex, hitting the 4 cinematic events that should
    stay UNCHANGED)
  - Regex over-permissiveness (someone widens beyond `&&` and matches non-
    wake-handshake patterns)

v0.24.102 — these tests are now skipped at module load. The patch was
retired (see TestPermissiveBossWakeRetiredV0_24_102 in test_emevd_patches.py
for context). The fixtures and assertions below are still correct for the
patch behavior IF it is revived; revival should un-skip this module by
removing the pytestmark line and confirming all tests pass against the
restored @register decorator.
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="permissive_boss_wake retired in v0.24.102 — see "
           "TestPermissiveBossWakeRetiredV0_24_102. Re-enable this file "
           "if the patch is revived.")

import re

import emevd_patch


# Synthetic minimal fixtures — vanilla-shape event bodies. Real common_func
# bodies are longer but the patch only cares about the wake-gate pattern.

VANILLA_FIXTURES = {
    # 90015000-family: direct radius gate
    90015000: (
        "$Event(90015000, Default, function(eventFlagId, chrEntityId, nameId, "
        "targetDistance, bgmBossConvParamId, eventFlagId2) {\n"
        "    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1);\n"
        "});\n"
    ),
    90015030: (
        "$Event(90015030, Default, function(eventFlagId, chrEntityId, areaEntityId, targetDistance, bgmBossConvParamId, eventFlagId2) {\n"
        "    chrAreaBgm = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1);\n"
        "});\n"
    ),
    # New direct-form additions
    90015023: (
        "$Event(90015023, Default, function(eventFlagId, targetDistance, eventFlagId2, chrEntityId, chrEntityId2, nameId) {\n"
        "    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1);\n"
        "});\n"
    ),
    90015026: (
        "$Event(90015026, Default, function(eventFlagId, targetDistance, eventFlagId2, chrEntityId, chrEntityId2, nameId) {\n"
        "    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1);\n"
        "});\n"
    ),
    # Extra-AND form
    90015021: (
        "$Event(90015021, Default, function(eventFlagId, chrEntityId, nameId, targetDistance, bgmBossConvParamId, eventFlagId2, eventFlagId3) {\n"
        "    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1)\n"
        "        && !InArea(20000, 1043372980);\n"
        "});\n"
    ),
    # Paren'd-OR form
    90015007: (
        "$Event(90015007, Default, function(eventFlagId, chrEntityId, areaEntityId, targetDistance, nameId, bgmBossConvParamId, eventFlagId2) {\n"
        "    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && (InArea(20000, areaEntityId)\n"
        "            || EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1));\n"
        "});\n"
    ),
    90015031: (
        "$Event(90015031, Default, function(eventFlagId, chrEntityId, areaEntityId, targetDistance, bgmBossConvParamId, eventFlagId2) {\n"
        "    chrAreaBgm = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && (InArea(20000, areaEntityId)\n"
        "            || EntityInRadiusOfEntity(20000, chrEntityId, targetDistance, 1))\n"
        "        && CompareBossBGMPriority(LessOrEqual, bgmBossConvParamId);\n"
        "});\n"
    ),
    # chrEntityId2 variant
    90015406: (
        "$Event(90015406, Default, function(eventFlagId, chrEntityId, chrEntityId2, areaEntityId, targetDistance, nameId, bgmBossConvParamId, eventFlagId2) {\n"
        "    chrArea = CharacterAIState(chrEntityId2, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && (InArea(20000, areaEntityId)\n"
        "            || EntityInRadiusOfEntity(20000, chrEntityId2, targetDistance, 1));\n"
        "});\n"
    ),
    # Cinematic — should stay UNCHANGED despite matching the regex
    90015002: (
        "$Event(90015002, Default, function(eventFlagId, eventFlagId2, eventFlagId3, chrEntityId, textEffectParamId, bgmBossConvParamId, userDispLogParamId, logObjectId, entityId) {\n"
        "    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && EntityInRadiusOfEntity(20000, chrEntityId, 30, 1);\n"
        "    hp = CharacterRatioHPValue(chrEntityId) <= 0;\n"
        "    WaitFor(chrArea || hp);\n"
        "});\n"
    ),
    90015301: (
        "$Event(90015301, Default, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, eventFlagId4, value) {\n"
        "    chrArea = CharacterAIState(chrEntityId, AIStateType.Combat, GreaterOrEqual, 1)\n"
        "        && EntityInRadiusOfEntity(20000, chrEntityId, 30, 1);\n"
        "});\n"
    ),
}

EXPECTED_PATCHED = (90015000, 90015007, 90015021, 90015023,
                    90015026, 90015030, 90015031, 90015406)
EXPECTED_UNCHANGED = (90015002, 90015301)


def _build_fixture():
    """Concatenate all fixtures into one file body."""
    return "".join(VANILLA_FIXTURES[eid] for eid in sorted(VANILLA_FIXTURES))


class TestPermissiveBossWakeV0_24_86Scope:
    """v0.24.86: scope expansion from 2 to 8 events."""

    def test_total_substitutions_match_allowlist_size(self):
        """One substitution per event in the allowlist."""
        body = _build_fixture()
        _, n = emevd_patch.patch_permissive_boss_wake(body, 'common_func.emevd.dcx.js')
        assert n == len(EXPECTED_PATCHED), (
            f'Expected {len(EXPECTED_PATCHED)} subs, got {n}. '
            f'Either an allowlist entry was lost or scope was widened.')

    def test_expected_events_are_patched(self):
        body = _build_fixture()
        patched, _ = emevd_patch.patch_permissive_boss_wake(body, 'common_func.emevd.dcx.js')
        for eid in EXPECTED_PATCHED:
            event_body = _extract_event(patched, eid)
            # The post-patch form contains an OR-line for Recognition
            assert 'AIStateType.Recognition' in event_body, (
                f'Event {eid} should be patched but is missing Recognition OR-clause.')

    def test_cinematic_events_stay_unchanged(self):
        """90015002, 90015301 etc. match the regex but must be allowlisted out."""
        body = _build_fixture()
        patched, _ = emevd_patch.patch_permissive_boss_wake(body, 'common_func.emevd.dcx.js')
        for eid in EXPECTED_UNCHANGED:
            event_body = _extract_event(patched, eid)
            assert 'AIStateType.Recognition' not in event_body, (
                f'Event {eid} is a cinematic encounter — patching its first '
                f'gate would fire the chrArea2 termination check prematurely. '
                f'It must remain UNCHANGED. Likely cause of failure: someone '
                f'removed the per-event allowlist loop.')

    def test_chr_entity_id2_variant_handled(self):
        """90015406 uses chrEntityId2 — patch must use chrEntityId2 in
        all four OR-clauses, not chrEntityId."""
        body = _build_fixture()
        patched, _ = emevd_patch.patch_permissive_boss_wake(body, 'common_func.emevd.dcx.js')
        event_body = _extract_event(patched, 90015406)
        assert event_body.count('CharacterAIState(chrEntityId2,') == 3, (
            'Expected 3 chrEntityId2 occurrences in the OR-block.')
        assert 'CharacterRatioHPRatio(chrEntityId2,' in event_body
        # Defensive — no leaked chrEntityId (without the 2) in OR-clauses
        assert 'CharacterAIState(chrEntityId,' not in event_body

    def test_idempotent(self):
        """Running the patch twice produces no additional substitutions."""
        body = _build_fixture()
        once, n1 = emevd_patch.patch_permissive_boss_wake(body, 'common_func.emevd.dcx.js')
        twice, n2 = emevd_patch.patch_permissive_boss_wake(once, 'common_func.emevd.dcx.js')
        assert n1 == len(EXPECTED_PATCHED)
        assert n2 == 0, (
            f'Patch should be idempotent — second run got {n2} subs.')

    def test_non_common_func_filenames_skipped(self):
        """Guard: don't patch per-map EMEVD files."""
        body = _build_fixture()
        _, n = emevd_patch.patch_permissive_boss_wake(body, 'm30_30_00_00.emevd.dcx.js')
        assert n == 0


def _extract_event(content, eid):
    starts = [(m.start(), int(m.group(1))) for m in re.finditer(r'\bEvent\((\d+)', content)]
    starts.sort()
    for i, (s, e) in enumerate(starts):
        if e == eid:
            end = starts[i+1][0] if i+1 < len(starts) else len(content)
            return content[s:end]
    raise KeyError(f'Event {eid} not found in fixture')
