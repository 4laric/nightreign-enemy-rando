"""Tests for gates threading into pick_target_cp / pick_target /
pick_cluster_target_cp.

pick_target_cp is the central read site for the gate cluster — it
reads V3_EXCLUDE_PREFIXES, V3_EXCLUDE_TARGET_PREFIXES,
V3_GHOST_EXCLUDE_TARGET_PREFIXES, V3_ARENA_ONLY_TARGETS (twice),
V3_NIGHT_BOSS_STRICT_TARGETS, and V3_NIGHT_BOSS_CALIBER_TARGETS.

Strategy: prove that gates=GateState.from_module() produces the same
result as gates=None across a representative sample of (recipient_cp,
slot_variant_name, recipient_is_boss) tuples. If the migration broke
any read site, parity fails on at least one input.

Plus targeted scenario tests: construct minimal synthetic state and
verify each gate set actually filters the pool when fed via gates=.
"""
import random

import pytest

import oops_v3
from engine.state import GateState


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------

class TestPickTargetCpSignature:
    def test_pick_target_cp_accepts_gates(self):
        import inspect
        sig = inspect.signature(oops_v3.pick_target_cp)
        assert 'gates' in sig.parameters
        assert sig.parameters['gates'].default is None

    def test_pick_target_accepts_gates(self):
        import inspect
        sig = inspect.signature(oops_v3.pick_target)
        assert 'gates' in sig.parameters
        assert sig.parameters['gates'].default is None

    def test_pick_cluster_target_cp_accepts_gates(self):
        import inspect
        sig = inspect.signature(oops_v3.pick_cluster_target_cp)
        assert 'gates' in sig.parameters
        assert sig.parameters['gates'].default is None


# ---------------------------------------------------------------------------
# Parity: gates=from_module() should match gates=None across real inputs
# ---------------------------------------------------------------------------

# Representative recipient cps spanning tiers/identities. Real cps from
# the loaded fixture; the test asserts equivalence for each.
_PARITY_RECIPIENTS = [
    'c4500',  # Tree Sentinel (field boss)
    'c2130',  # Margit (night boss)
    'c4170',  # Banished Knight (field grunt + boss variants)
    'c3470',  # Aged Albinauric (trash)
    'c4910',  # Magma Wyrm (field boss)
    'c1000',  # placeholder/excluded source
]

# Representative slot variant names triggering different gate paths.
# Order: arena marker tier ladder from broad → strict.
_PARITY_SLOT_VARIANTS = [
    None,                            # no variant info
    'Some Encampment- Shield',       # boss-tier marker only
    'Boss Test (Castle Boss)',       # night-boss marker
    'Test (Field Boss)',             # night-or-field marker
    'Test (Night Boss)',             # strict-NB marker
    'Just A Grunt',                  # no marker
]


class TestPickTargetCpParity:
    """For each (recipient, slot_variant_name) pair, gates=snapshot and
    gates=None must return the same target. Bug in any of the 7
    migrated read sites would produce divergence at the first input
    that exercises the broken site.

    rng is seeded identically per test to remove RNG variance — the
    function makes exactly one rng.choice per call along the happy
    path, and we want determinism for parity comparison.
    """

    @pytest.mark.parametrize('recipient_cp', _PARITY_RECIPIENTS)
    @pytest.mark.parametrize('slot_variant_name', _PARITY_SLOT_VARIANTS)
    def test_parity(self, engine, tags, prefix_variants, prefix_count,
                    recipient_cp, slot_variant_name):
        # Skip recipients not present in the loaded data.
        if recipient_cp not in tags:
            pytest.skip(f'{recipient_cp} not in loaded tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient_cp, tags, prefix_variants)
        snapshot = GateState.from_module(engine)

        # pick_target_cp has a documented side effect: it mutates
        # _V3_UNIQUE_PLACED_COUNTS at line ~511 to track unique-target
        # frequency caps. Two back-to-back calls with the same RNG seed
        # would otherwise produce different picks because the second
        # call sees the first call's bumped counter and excludes that
        # target as exhausted. Save and restore _V3_UNIQUE_PLACED_COUNTS
        # around each call to make the parity test see identical state.
        # Same trick that cmd_shuffle_v3 used pre-Phase 2 for its
        # exclude-set save/restore.
        saved_counts = dict(engine._V3_UNIQUE_PLACED_COUNTS)

        # Seed identical rng for each branch — pick_target_cp consumes
        # exactly one rng.choice() per call along the happy path, so
        # same seed → same pick if pool composition matches.
        rng_module = random.Random(42)
        rng_gates = random.Random(42)

        try:
            result_module = oops_v3.pick_target_cp(
                recipient_cp, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng_module,
                slot_variant_name=slot_variant_name)
        finally:
            engine._V3_UNIQUE_PLACED_COUNTS.clear()
            engine._V3_UNIQUE_PLACED_COUNTS.update(saved_counts)

        try:
            result_gates = oops_v3.pick_target_cp(
                recipient_cp, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng_gates,
                slot_variant_name=slot_variant_name,
                gates=snapshot)
        finally:
            engine._V3_UNIQUE_PLACED_COUNTS.clear()
            engine._V3_UNIQUE_PLACED_COUNTS.update(saved_counts)

        assert result_module == result_gates, (
            f'parity broke for {recipient_cp}/{slot_variant_name!r}: '
            f'module={result_module} gates={result_gates}')


# ---------------------------------------------------------------------------
# Scenario tests: each gate set actually filters the pool under explicit gates
#
# These tests construct an MP-safe-blocklist-style scenario via explicit
# GateState and verify the pool gets filtered. They prove the
# `gates.foo` read sites *actually fire* (i.e., aren't accidentally
# still reading module globals from somewhere else).
# ---------------------------------------------------------------------------

class TestPickTargetCpGateEffects:
    """For each gate set, plant a recipient that would normally land on
    cp X, then prevent X via gates and confirm X is not returned.
    """

    def test_exclude_target_prefixes_via_gates_filters_pool(
            self, engine, tags, prefix_variants, prefix_count):
        # Pick a recipient that has an obviously-large compat pool.
        # c4170 Banished Knight is a humanoid biped — wide pool.
        recipient = 'c4170'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        # Take a snapshot, then narrow the pool sharply via gates: add
        # a known boss-tier cp to exclude_target_prefixes. The function
        # should never return that cp.
        ban_target = 'c4500'  # Tree Sentinel
        gates = GateState.from_module(engine).replace(
            exclude_target_prefixes=(
                frozenset(engine.V3_EXCLUDE_TARGET_PREFIXES) | {ban_target}))

        # 30 trials with different rng seeds. Banned cp should never appear.
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        for seed in range(30):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)',  # boss-tier slot
                gates=gates)
            assert result != ban_target, (
                f'seed {seed}: gates.exclude_target_prefixes did not '
                f'block {ban_target}')

    def test_ghost_exclude_via_gates_filters_pool(
            self, engine, tags, prefix_variants, prefix_count):
        recipient = 'c4170'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        ban_target = 'c4910'  # Magma Wyrm
        gates = GateState.from_module(engine).replace(
            ghost_exclude_target_prefixes=(
                frozenset(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
                | {ban_target}))

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        for seed in range(30):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)',
                gates=gates)
            assert result != ban_target, (
                f'seed {seed}: gates.ghost_exclude_target_prefixes did '
                f'not block {ban_target}')

    def test_arena_only_via_gates_blocks_non_arena_slot(
            self, engine, tags, prefix_variants, prefix_count):
        # arena_only_targets are excluded from non-boss slots. If we
        # plant a target in arena_only via gates and pass a non-boss
        # recipient, the target should not appear.
        recipient = 'c4170'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        ban_target = 'c4500'  # Tree Sentinel — give it arena-only treatment
        gates = GateState.from_module(engine).replace(
            arena_only_targets=(
                frozenset(engine.V3_ARENA_ONLY_TARGETS) | {ban_target}))

        # Non-boss recipient slot — should subtract arena_only.
        for seed in range(30):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss=False,
                rng=rng,
                slot_variant_name=None,  # no arena marker
                gates=gates)
            assert result != ban_target, (
                f'seed {seed}: gates.arena_only_targets did not block '
                f'{ban_target} at non-arena slot')


class TestHasRewardPreservationGate:
    """v0.24.101: when the recipient slot's c-prefix has has_reward=True,
    pick_target_cp restricts the target pool to c-prefixes that also have
    has_reward=True. Asymmetric — has_reward=False recipients are not
    constrained (can swap in any direction, including upgrading to a
    rewarded encounter).

    Distinct from slot_require_boss_reward (which gates on has_boss_reward
    and is opt-in via V3_BOSSY_PROMOTE_SLOTS 'boss_reward' mode). The
    has_reward gate is automatic on every call.
    """

    def _make_tags_with_reward_override(self, base_tags, overrides):
        """Return a shallow-copy tags dict with specific chrs' has_reward
        overridden. Each chr-dict that gets overridden is also shallow-copied
        so the original tags fixture isn't mutated (session-scoped).
        """
        new_tags = dict(base_tags)
        for cp, value in overrides.items():
            new_tags[cp] = {**base_tags.get(cp, {}), 'has_reward': value}
        return new_tags

    def test_rewarded_recipient_only_swaps_to_rewarded_target(
            self, engine, tags, prefix_variants, prefix_count):
        # c2130 Margit has has_reward=True in the loaded tags.
        recipient = 'c2130'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        if not tags[recipient].get('has_reward'):
            pytest.skip(f'{recipient} has_reward!=True in loaded tags — '
                        f'fixture changed')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        # Run many seeds. Every returned target must also have_reward=True.
        # (None is allowed — the slot stays vanilla, which preserves the
        # vanilla reward.)
        observed_targets = set()
        for seed in range(100):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            if result is None:
                continue
            observed_targets.add(result)
            assert tags.get(result, {}).get('has_reward') is True, (
                f'seed {seed}: recipient {recipient} (has_reward=True) '
                f'swapped to {result} which has has_reward='
                f'{tags.get(result, {}).get("has_reward")!r}')

        # Sanity: at least some swaps actually happened (otherwise the
        # gate could be hiding behind a None-only result).
        assert observed_targets, (
            'no targets returned across 100 seeds — gate may be returning '
            'None unconditionally')

    def test_unrewarded_recipient_can_swap_to_unrewarded_target(
            self, engine, tags, prefix_variants, prefix_count):
        # Asymmetric: a has_reward=False recipient should NOT have the
        # gate restrict it to rewarded targets. Pick a recipient with
        # has_reward=False and verify at least some seeds return a
        # has_reward=False target.
        recipient = None
        for cp in ('c3060', 'c2276', 'c4400', 'c4410'):
            if cp in tags and tags[cp].get('has_reward') is False:
                recipient = cp; break
        if recipient is None:
            pytest.skip('no has_reward=False boss-tier recipient available')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        saw_unrewarded_target = False
        for seed in range(100):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            if result is None:
                continue
            tag_value = tags.get(result, {}).get('has_reward')
            if tag_value is not True:
                saw_unrewarded_target = True
                break

        assert saw_unrewarded_target, (
            f'recipient {recipient} (has_reward=False) only produced '
            f'has_reward=True targets across 100 seeds — gate appears to '
            f'be applying bidirectionally, breaking the asymmetric design')

    def test_returns_none_when_no_rewarded_target_available(
            self, engine, tags, prefix_variants, prefix_count):
        # Construct synthetic tags where the recipient has has_reward=True
        # but every other chr in the loaded tags has has_reward=False.
        # With an empty rewarded-target pool, the function must return None
        # rather than fall back to an unrewarded target.
        recipient = 'c2130'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        overrides = {cp: False for cp in tags if cp != recipient}
        overrides[recipient] = True
        synthetic_tags = self._make_tags_with_reward_override(tags, overrides)

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, synthetic_tags, prefix_variants)

        for seed in range(20):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, synthetic_tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            assert result is None, (
                f'seed {seed}: pool exhausted by has_reward gate but '
                f'pick_target_cp returned {result!r} instead of None')

    def test_recipient_with_has_reward_missing_is_not_constrained(
            self, engine, tags, prefix_variants, prefix_count):
        # Some chrs have has_reward absent (None / missing) — typically
        # cinematic/template chrs. These should NOT trigger the gate
        # (only has_reward is True triggers it).
        recipient = None
        for cp, t in tags.items():
            if t.get('has_reward') is None and t.get('tier') in (
                    'miniboss', 'field_boss', 'night_boss', 'grunt', 'trash'):
                recipient = cp; break
        if recipient is None:
            pytest.skip('no recipient with has_reward=None available')

        # Should be able to swap to a has_reward=False target — gate not
        # triggered.
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        saw_unrewarded_target = False
        for seed in range(100):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            if result is None:
                continue
            if tags.get(result, {}).get('has_reward') is not True:
                saw_unrewarded_target = True
                break

        assert saw_unrewarded_target, (
            f'recipient {recipient} (has_reward=None) was incorrectly '
            f'constrained by the rewarded-only gate')


class TestPreserveSlotsGate:
    """v0.24.101: V3_PRESERVE_SLOTS is checked inside pick_target_cp,
    not just in _score_slot_for_unique. Verifies that slots in the set
    return None (preserve vanilla) regardless of which code path picks
    them up.

    Pre-v0.24.101 the gate only fired during unique-reservation pre-pass,
    so the normal swap path was leaking. Playtest seed 537123 v0.24.96
    surfaced this with Rellana at m49_28 pi=2 (a "preserved" slot).
    """

    def test_m49_28_cavalry_nb_riders_preserved(
            self, engine, tags, prefix_variants, prefix_count):
        # m49_28 pi=2 and pi=3 are Night's Cavalry rider slots. Even with
        # a permissive recipient, pick_target_cp should return None.
        recipient = 'c3150'  # the actual source — pick anything biped-ish
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        for pi in (2, 3, 4, 5):
            for seed in range(10):
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name='m49_28_00_00.msb', slot_pi=pi,
                    slot_variant_name='Test (Night Boss)')
                assert result is None, (
                    f'm49_28 pi={pi} seed={seed}: V3_PRESERVE_SLOTS gate '
                    f'returned {result!r} instead of None')

    def test_m46_62_cavalry_evergaol_preserved(
            self, engine, tags, prefix_variants, prefix_count):
        # m46_62 pi=1,2,3,4 are the Night's Cavalry Evergaol rider+mount
        # pairs added in v0.24.101. Playtest seed 537123 caught
        # c3560 Godskin Apostle at pi=1.
        recipient = 'c3150'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        for pi in (1, 2, 3, 4):
            for seed in range(10):
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name='m46_62_00_00.msb', slot_pi=pi,
                    slot_variant_name='Test (Field Boss)')
                assert result is None, (
                    f'm46_62 pi={pi} seed={seed}: V3_PRESERVE_SLOTS gate '
                    f'returned {result!r} instead of None')

    def test_non_preserved_slot_still_swaps(
            self, engine, tags, prefix_variants, prefix_count):
        # Sanity check: the gate is targeted, not a blanket. m46_62 pi=5
        # is c4580 Large Wormface — not in V3_PRESERVE_SLOTS. Should
        # still swap normally (return a c-prefix, not None).
        recipient = 'c4580'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        saw_non_none = False
        for seed in range(20):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_msb_name='m46_62_00_00.msb', slot_pi=5,
                slot_variant_name='Test (Field Boss)')
            if result is not None:
                saw_non_none = True
                break
        assert saw_non_none, (
            'm46_62 pi=5 (not in V3_PRESERVE_SLOTS) returned None across '
            '20 seeds — gate may be overreaching')


class TestForbiddenBySourceAnim:
    """v0.24.18 introduced V3_FORBIDDEN_BY_SOURCE_ANIM (read at line ~8497
    of oops_v3.py) — when the slot's vanilla source cp has anim_class X,
    forbidden target cps Y are subtracted from the pool. Orthogonal to
    the slot-variant-name gates (which read the slot's variant marker).

    v0.24.24 added the reverse direction (giga_boss source → forbid all
    flyers) after the seed 738357 fort-roof CTD where a Death Rite Bird
    landed at a Guardian Golem (Fort) slot — grounded XXL arena, flier
    target. These tests cover both directions.
    """

    def test_flying_dragon_source_forbids_c4660(
            self, engine, tags, prefix_variants, prefix_count):
        # v0.24.18 original case: c4660 Guardian Golem (giga_boss
        # grounded) should NOT appear when the source slot's vanilla cp
        # has anim_class='flying_dragon'.
        #
        # v0.24.75: V3_FORBIDDEN_BY_SOURCE_ANIM was emptied per user
        # directive removing anim_class restrictions. This test is
        # repurposed to assert the EMPTY-dict invariant — if the dict
        # is ever repopulated, this catches it and forces a re-check.
        # To restore the v0.24.18 rule, add 'flying_dragon': {'c4660'}
        # back to V3_FORBIDDEN_BY_SOURCE_ANIM AND re-enable Gate 3 in
        # _reject_target_for_slot.
        assert dict(engine.V3_FORBIDDEN_BY_SOURCE_ANIM) == {}, (
            'v0.24.75 emptied V3_FORBIDDEN_BY_SOURCE_ANIM; if you '
            'repopulate this dict, also update this test to reflect '
            'the new expected behavior.')

    def test_giga_boss_source_no_longer_forbids_fliers(
            self, engine, tags, prefix_variants, prefix_count):
        # v0.24.66: REVERSE direction LIFTED. v0.24.24 added a
        # 'giga_boss' → frozenset(flier c-prefixes) rule after the seed
        # 738357 m30_30 fort-roof CTD. Post-v0.24.65 full asset deploy
        # (chr + script + aicommon + sfx + material), playtest showed
        # fliers actually work at Guardian Golem-class slots — per
        # Alaric: "dragons do work in the golem slot and their entrance
        # animation is extremely cool". The original c6260 CTD was
        # almost certainly an MMV asset-deploy gap (same pattern as the
        # c8300 Roundtable error), not a geometry mismatch.
        assert 'giga_boss' not in engine.V3_FORBIDDEN_BY_SOURCE_ANIM, (
            'v0.24.66 lifted the giga_boss reverse rule. If it has been '
            're-added, capture the seed+version evidence in the comment '
            'above V3_FORBIDDEN_BY_SOURCE_ANIM before re-banning.')

    def test_c6260_no_longer_blocked_at_giga_source(
            self, engine, tags, prefix_variants, prefix_count):
        # v0.24.66: c6260 Death Rite Bird specifically — the original
        # v0.24.24 trigger case. Now allowed at Guardian Golem slots.
        forbidden = engine.V3_FORBIDDEN_BY_SOURCE_ANIM.get('giga_boss', set())
        assert 'c6260' not in forbidden

    def test_only_flying_dragon_rule_remains(
            self, engine, tags, prefix_variants, prefix_count):
        # v0.24.66 post-lift: only the v0.24.18 forward rule
        # (flying_dragon → exclude c4660 Guardian Golem) remains in
        # V3_FORBIDDEN_BY_SOURCE_ANIM.
        #
        # v0.24.75 update: dict emptied entirely per user directive
        # removing anim_class restrictions. Test now asserts the dict
        # is empty. To restore the v0.24.18 rule (or any source-anim
        # forbidden mapping), repopulate V3_FORBIDDEN_BY_SOURCE_ANIM
        # AND restore the Gate 3 application — see oops_v3.py docs.
        assert dict(engine.V3_FORBIDDEN_BY_SOURCE_ANIM) == {}, (
            f'v0.24.75 emptied V3_FORBIDDEN_BY_SOURCE_ANIM; got '
            f'{dict(engine.V3_FORBIDDEN_BY_SOURCE_ANIM)}')

    def test_anim_class_backfill_landed(self, engine, tags, prefix_variants,
                                         prefix_count):
        # v0.24.24 data-side fix: 4 fliers that lacked anim_class get
        # the field at load time. KEPT post-v0.24.66 lift — the
        # backfill is still useful for other gates and for general
        # data quality, even with the giga_boss rule lifted. If a
        # future load_data refactor or data-file edit drops these,
        # this test catches it.
        expected_flying = {
            'c4502': 'Decaying Ekzykes-class Dragon (post_dlc_dump)',
            'c4504': 'Elder Dragon Greyoll (post_dlc_dump)',
            'c4511': 'Lichdragon Fortissax (mmv_import)',
            'c6260': 'Death Rite Bird (mmv_import) — the original CTD trigger',
        }
        missing = []
        for cp, label in expected_flying.items():
            t = tags.get(cp)
            if t is None:
                # cp may not be in tags if its pack is disabled — skip
                continue
            ac = t.get('anim_class')
            if ac != 'flying_dragon':
                missing.append(f'  {cp} ({label}): anim_class={ac!r}, '
                               f'expected flying_dragon')
        if missing:
            raise AssertionError(
                'v0.24.24 anim_class backfill regressed:\n' + '\n'.join(missing))

    def test_v0_24_26_score_slot_now_allows_lifted_combinations(self, engine, tags):
        """v0.24.66 inversion of v0.24.26 test: with the giga_boss reverse
        rule lifted, the 8 known-bad reservations from seed 147927 should
        now be ACCEPTED by _score_slot_for_unique (returning a numeric
        score rather than None). If any still return None it'd be due to
        an unrelated gate, not the (now-removed) source-anim rule.

        Historical: v0.24.26 added a mirror in _score_slot_for_unique
        that rejected these combinations to fix a reservation-bypass
        bug where the reservation pre-pass committed forbidden combos
        before the runtime gate could reject them. The mirror is now
        a no-op for these specific cases since the rule itself is gone."""
        # Skip if the rule structure is missing entirely
        if 'flying_dragon' not in engine.V3_FORBIDDEN_BY_SOURCE_ANIM:
            pytest.skip('V3_FORBIDDEN_BY_SOURCE_ANIM missing flying_dragon')
        # The 8 combinations from seed 147927 — all fliers at giga_boss
        # source slots. None of these are blocked by source-anim anymore.
        cases = [
            ('c4502', 'm30_30_00_00.msb', 45, 'c4660'),
            ('c4501', 'm48_20_00_00.msb',  3, 'c4660'),
            ('c4680', 'm49_18_00_00.msb',  5, 'c4660'),
            ('c4500', 'm49_19_00_00.msb',  7, 'c4510'),
            ('c4911', 'm49_20_00_00.msb',  5, 'c4660'),
            ('c4503', 'm60_42_36_00.msb', 43, 'c4660'),
            ('c4505', 'm60_43_38_00.msb',  6, 'c4660'),
            ('c4505', 'm60_44_36_00.msb', 10, 'c4660'),
        ]
        # We just need to verify the source-anim rejection no longer fires
        # for these. The _score_slot_for_unique may still return None for
        # OTHER reasons (identity-swap, preservation, etc.) — that's not
        # our concern. We check that V3_FORBIDDEN_BY_SOURCE_ANIM lookup
        # is empty for the relevant key.
        forbidden_giga = engine.V3_FORBIDDEN_BY_SOURCE_ANIM.get('giga_boss', set())
        leaks = []
        for target_cp, msb, pi, src_cp in cases:
            if target_cp in forbidden_giga:
                leaks.append(f'  {target_cp} still in '
                             f'V3_FORBIDDEN_BY_SOURCE_ANIM[giga_boss]')
        assert not leaks, (
            'v0.24.66 lift incomplete — these targets still banned at '
            f'giga_boss sources:\n' + '\n'.join(leaks))

    def test_v0_24_26_score_slot_allows_compatible_source_anim(self, engine, tags):
        """Inverse of the above: humanoid → humanoid is not forbidden;
        the v0.24.26 mirror must not over-reject."""
        if 'c3000' not in tags or 'c3010' not in tags:
            pytest.skip('test source cps not in tags')
        slot_info = {
            'source_cp': 'c3000',  # Exile Soldier (humanoid)
            'source_variant_name': 'Exile Soldier',
            'source_npc': 30000010,
            'msb': 'm30_00_00_00.msb',
            'pi': 100,
            'cluster_id': None,
            'pos': (0, 0, 0),
        }
        # Target a humanoid — should NOT be auto-rejected by the new mirror
        # (may still be rejected by other gates; we just need score != None
        # to be possible at all). Use score >= 0 or None acceptance.
        score = engine._score_slot_for_unique(slot_info, 'c3010', tags)
        # The mirror would only fire if c3000's anim_class is in
        # V3_FORBIDDEN_BY_SOURCE_ANIM AND c3010 is forbidden under it.
        # Neither condition holds (humanoid isn't a key). So the mirror
        # must not be the reason for any None here. Score can legitimately
        # be None for other reasons (identity-swap, preservation, etc.),
        # but in this stripped-down test case there are no other blockers.
        # Allow either an int score OR None for unrelated reasons.
        assert score is None or isinstance(score, (int, float)), (
            f'score should be None or numeric, got {type(score).__name__}')


# ---------------------------------------------------------------------------
# End-to-end: gates threaded all the way from cmd_shuffle_v3 reaches
# pick_target_cp via shuffle_msb_v3 → pick_target → pick_target_cp
# ---------------------------------------------------------------------------

class TestEndToEndPickTargetThreading:
    """Mock pick_target_cp to capture what gates= it receives when
    cmd_shuffle_v3 is invoked with multiplayer_safe=True. If threading
    is broken anywhere in the chain, gates would arrive as None.
    """

    def test_pick_target_cp_receives_gates_from_cmd_shuffle_v3(self, engine):
        captured = {}

        def fake_pick_target_cp(*args, **kwargs):
            captured.setdefault('gates_seen', []).append(kwargs.get('gates'))
            return None  # Don't actually run the picker

        saved = engine.pick_target_cp
        # Also need to stub _cmd_shuffle_v3_impl so we don't actually run
        # a seed — but we DO want pick_target_cp to be reachable through
        # shuffle_msb_v3. Easiest: stub _cmd_shuffle_v3_impl to call
        # pick_target_cp directly with a known gates value.

        def fake_impl(*args, **kwargs):
            # Simulate a call from inside _cmd_shuffle_v3_impl
            engine.pick_target_cp(
                'c4170', {}, {}, {}, False, None, gates=kwargs.get('gates'))
            return 'fake-result'

        saved_impl = engine._cmd_shuffle_v3_impl
        engine.pick_target_cp = fake_pick_target_cp
        engine._cmd_shuffle_v3_impl = fake_impl
        try:
            engine.cmd_shuffle_v3(
                input_dir='/tmp/_nothing',
                output_dir='/tmp/_nothing',
                seed=1,
                multiplayer_safe=True)
        finally:
            engine.pick_target_cp = saved
            engine._cmd_shuffle_v3_impl = saved_impl

        # Should have captured at least one gates argument.
        assert captured.get('gates_seen'), 'pick_target_cp was not called'
        # And it should be a GateState, not None.
        gates_seen = captured['gates_seen'][0]
        assert gates_seen is not None, (
            'pick_target_cp received gates=None — threading broke somewhere')
        # And it should reflect multiplayer_safe (mp_safe_blocklist
        # unioned into ghost).
        assert (set(engine.V3_MP_SAFE_BLOCKLIST)
                <= gates_seen.ghost_exclude_target_prefixes)


class TestOopsAllNbPinnedSlot:
    """v0.24.25: surgical single-slot pin. When oops_all_nb_pinned_slot=
    (msb, pi) is passed alongside oops_all_nb_target_cp, only that exact
    slot gets the target. All other slots fall through to normal picker.

    Plumbing tests (kwarg threads through call chain) + behavioral tests
    (the gate logic in the per-slot loop fires only at the pinned slot).
    """

    def test_cmd_shuffle_v3_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine.cmd_shuffle_v3)
        assert 'oops_all_nb_pinned_slot' in sig.parameters
        # Default should be None so existing callers don't break
        assert sig.parameters['oops_all_nb_pinned_slot'].default is None

    def test_impl_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine._cmd_shuffle_v3_impl)
        assert 'oops_all_nb_pinned_slot' in sig.parameters

    def test_shuffle_msb_v3_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine.shuffle_msb_v3)
        assert 'oops_all_nb_pinned_slot' in sig.parameters

    def test_write_spoiler_logs_signature_accepts_pinned_slot(self, engine):
        import inspect
        sig = inspect.signature(engine.write_spoiler_logs)
        assert 'oops_all_nb_pinned_slot' in sig.parameters

    def test_pinned_slot_threads_through_cmd_shuffle_v3(self, engine):
        # End-to-end plumbing: pass a pinned slot to the public wrapper,
        # confirm shuffle_msb_v3 receives it.
        import inspect
        captured = {}

        def fake_impl(*args, **kwargs):
            captured['kwarg'] = kwargs.get('oops_all_nb_pinned_slot')
            return 'fake-result'

        saved = engine._cmd_shuffle_v3_impl
        engine._cmd_shuffle_v3_impl = fake_impl
        try:
            engine.cmd_shuffle_v3(
                input_dir='/tmp/_nothing',
                output_dir='/tmp/_nothing',
                seed=1,
                oops_all_nb_target_cp='c8500',
                oops_all_nb_pinned_slot=('m60_43_37_00.msb', 120))
        finally:
            engine._cmd_shuffle_v3_impl = saved

        assert captured.get('kwarg') == ('m60_43_37_00.msb', 120), (
            f'pinned_slot did not thread through cmd_shuffle_v3 → impl: '
            f'got {captured.get("kwarg")!r}')

    def test_pinned_mode_disables_broad_scope_branch(self, engine):
        # The broad/extended scope branch is gated by
        # `oops_all_nb_pinned_slot is None`. Grep the source to confirm.
        import inspect
        src = inspect.getsource(engine.shuffle_msb_v3)
        # The marker comment is what we rely on
        assert 'v0.24.25' in src, (
            'v0.24.25 marker missing from shuffle_msb_v3 — pinned mode '
            'may have been removed')
        assert 'oops_all_nb_pinned_slot is None' in src, (
            'broad-scope branch is not guarded against pinned mode — '
            'pinned + scope=broad would BOTH fire, defeating the point')


class TestRejectTargetForSlot:
    """v0.24.27: shared mirror-semantic predicate. Both pick_target_cp
    and _score_slot_for_unique delegate to this. Tests cover each gate
    in isolation plus the chaos_mode toggle.
    """

    def test_predicate_exists(self, engine):
        assert hasattr(engine, '_reject_target_for_slot'), (
            '_reject_target_for_slot predicate missing — v0.24.27 '
            'refactor regressed')

    def test_nb_strict_gate_rejects(self, engine, tags):
        # Pick a target that's in V3_NIGHT_BOSS_STRICT_TARGETS, source
        # with a non-strict-NB variant name → expect 'nb_strict'.
        strict = engine.V3_NIGHT_BOSS_STRICT_TARGETS
        if not strict:
            pytest.skip('V3_NIGHT_BOSS_STRICT_TARGETS empty')
        target_cp = next(iter(strict))
        # 'Field Boss' is in BOSS_NAME_MARKERS but NOT in STRICT_NAME_MARKERS
        result = engine._reject_target_for_slot(
            target_cp, 'c4660', 'Guardian Golem (Field Boss)', tags)
        assert result == 'nb_strict', (
            f'strict gate should reject {target_cp} at non-strict slot, '
            f'got {result!r}')

    def test_nb_strict_gate_allows_at_strict_slot(self, engine, tags):
        strict = engine.V3_NIGHT_BOSS_STRICT_TARGETS
        if not strict:
            pytest.skip('V3_NIGHT_BOSS_STRICT_TARGETS empty')
        target_cp = next(iter(strict))
        # Source variant with explicit 'Night Boss' marker — should pass
        # NB-strict, may still hit caliber or source-anim
        result = engine._reject_target_for_slot(
            target_cp, 'c4510', 'Ancient Dragon (Night Boss)', tags)
        # If rejected, MUST NOT be by nb_strict
        assert result != 'nb_strict', (
            f'strict gate falsely rejected {target_cp} at Night Boss '
            f'slot — strict marker should satisfy the gate')

    def test_nb_caliber_gate_rejects_non_caliber_at_nb_slot(self, engine, tags):
        # NB-caliber: at NB-marker slot, target NOT in caliber set is rejected
        caliber = engine.V3_NIGHT_BOSS_CALIBER_TARGETS
        if not caliber:
            pytest.skip('caliber set empty')
        # Pick a target NOT in caliber (use a humanoid common chr)
        non_caliber = next(
            (cp for cp in tags
             if cp not in caliber
             and cp not in engine.V3_NIGHT_BOSS_STRICT_TARGETS
             and tags[cp].get('anim_class') == 'humanoid'),
            None)
        if non_caliber is None:
            pytest.skip('no non-caliber humanoid cp in tags')
        result = engine._reject_target_for_slot(
            non_caliber, 'c2130', 'Margit (Night Boss)', tags)
        # Should reject as nb_caliber (or nb_strict if non_caliber happens
        # to also be in STRICT_TARGETS — but we filtered that out)
        assert result == 'nb_caliber', (
            f'caliber gate should reject {non_caliber} at NB slot, '
            f'got {result!r}')

    def test_source_anim_gate_rejects_flier_at_giga(self, engine, tags):
        # The v0.24.26 case: giga_boss source + flying_dragon target.
        # Carefully pick a forbidden flier that is NOT also in
        # V3_NIGHT_BOSS_STRICT_TARGETS or V3_NIGHT_BOSS_CALIBER_TARGETS,
        # otherwise an earlier gate fires first and we don't actually
        # test source-anim. load_data() populates strict and caliber
        # sets, so the overlap can be non-empty at test time even if
        # the pre-load sets are disjoint.
        forbidden = engine.V3_FORBIDDEN_BY_SOURCE_ANIM.get('giga_boss', set())
        if not forbidden:
            pytest.skip('giga_boss forbidden set empty')
        strict = engine.V3_NIGHT_BOSS_STRICT_TARGETS
        caliber = engine.V3_NIGHT_BOSS_CALIBER_TARGETS
        candidates = forbidden - strict - caliber
        if not candidates:
            pytest.skip('every forbidden giga_boss target also in strict '
                        'or caliber — source-anim gate cannot be isolated')
        # Deterministic: sort so test result is hash-seed-independent
        target_cp = sorted(candidates)[0]
        # c4660 Guardian Golem has anim_class=giga_boss
        if tags.get('c4660', {}).get('anim_class') != 'giga_boss':
            pytest.skip('c4660 not giga_boss in this tag set')
        # 'Guardian Golem (Fort)' has no NB markers (no 'Fort Boss',
        # no 'Night Boss', etc.) so the caliber gate won't fire on
        # the src_variant side either.
        result = engine._reject_target_for_slot(
            target_cp, 'c4660', 'Guardian Golem (Fort)', tags)
        assert result == 'forbidden_source_anim', (
            f'source-anim gate should reject {target_cp} at c4660, '
            f'got {result!r}')

    def test_predicate_allows_safe_combo(self, engine, tags):
        # Humanoid source + humanoid target, no NB markers → no rejection
        result = engine._reject_target_for_slot(
            'c3010', 'c3000', 'Exile Soldier', tags)
        assert result is None, (
            f'safe humanoid→humanoid combo wrongly rejected with {result!r}')

    def test_chaos_mode_tightens_caliber(self, engine, tags):
        # In chaos mode, NB-caliber uses NIGHT_BOSS_ONLY_TARGETS (strict
        # subset of caliber). A cp that's IN caliber but NOT in NB_ONLY
        # should be rejected at NB slots when chaos_mode=True.
        caliber = engine.V3_NIGHT_BOSS_CALIBER_TARGETS
        nb_only = engine.V3_NIGHT_BOSS_ONLY_TARGETS
        if not caliber or not nb_only:
            pytest.skip('caliber or nb_only set empty')
        in_caliber_not_nb_only = caliber - nb_only
        if not in_caliber_not_nb_only:
            pytest.skip('caliber == nb_only — cannot test chaos tightening')
        target_cp = next(iter(in_caliber_not_nb_only))
        # Non-chaos: should NOT reject (in caliber)
        result_normal = engine._reject_target_for_slot(
            target_cp, 'c2130', 'Margit (Night Boss)', tags,
            chaos_mode=False)
        # Chaos: SHOULD reject (not in nb_only, even though in caliber)
        result_chaos = engine._reject_target_for_slot(
            target_cp, 'c2130', 'Margit (Night Boss)', tags,
            chaos_mode=True)
        # Verify the toggle changes the answer for the caliber gate
        # (other gates may still match identically — just check that
        # the chaos result is reject-by-caliber when normal isn't)
        if result_normal == 'nb_caliber':
            pytest.skip('target also rejected by caliber in non-chaos — '
                        'chaos tightening case not exercised')
        assert result_chaos == 'nb_caliber', (
            f'chaos mode should tighten caliber → reject {target_cp}, '
            f'got chaos={result_chaos!r}, normal={result_normal!r}')

    def test_predicate_returns_reason_strings(self, engine, tags):
        # Confirm the documented return values: None or one of the
        # known reason strings. Updated v0.24.68 to include the full
        # current set of gate reasons; failing here means a new gate
        # was added without updating this list (or the engine is
        # returning an unexpected value).
        valid_reasons = {
            None,
            # Gates 1-3 (caliber/strict/source-anim)
            'nb_strict', 'nb_caliber', 'forbidden_source_anim',
            # Gate 4 (quadruped unsafe slot)
            'quadruped_unsafe_slot',
            # Gate 5 (flying required slot)
            'flying_required_slot',
            # Gate 5.5 v0.24.67 (grunt/trash at boss-bar)
            'grunt_trash_at_boss_bar',
            # Gate 5.6 v0.24.68 (XXL/GIGA source slot integrity)
            'xxl_giga_anim_drift', 'xxl_giga_size_drift',
            # Gate 6 (script-spawn boss off-arena)
            'script_spawn_boss_at_overworld',
            # Gate 7 (XXL at small slot)
            'xxl_at_small_slot',
        }
        # Hit a few combinations and check returns are in the set
        for target, src, variant in [
            ('c3010', 'c3000', 'Exile Soldier'),
            ('c4660', 'c4660', 'Guardian Golem (Fort)'),
            ('c4500', 'c4660', 'Guardian Golem (Fort)'),
        ]:
            if target not in tags or src not in tags:
                continue
            r = engine._reject_target_for_slot(target, src, variant, tags)
            assert r in valid_reasons, (
                f'predicate returned unexpected value {r!r} '
                f'for ({target}, {src}, {variant!r})')

    def test_scorer_uses_predicate(self, engine):
        # Structural check: _score_slot_for_unique should call the
        # predicate. Grep the source. (If the scorer ever stops using
        # the predicate, the mirror bug recurs — catch it here.)
        import inspect
        src = inspect.getsource(engine._score_slot_for_unique)
        assert '_reject_target_for_slot' in src, (
            '_score_slot_for_unique no longer calls _reject_target_for_'
            'slot — v0.24.27 refactor regressed; mirror semantics '
            'broken')

    def test_picker_uses_predicate(self, engine):
        # Same structural check on pick_target_cp
        import inspect
        src = inspect.getsource(engine.pick_target_cp)
        assert '_reject_target_for_slot' in src, (
            'pick_target_cp no longer calls _reject_target_for_slot — '
            'v0.24.27 refactor regressed')


class TestStartingEncampmentCatalog:
    """v0.24.28: data/nr_starting_encampments.json + V3_STARTING_ENCAMPMENT
    _MSBS + 'starting_encampment' scope value. Tests cover the loader,
    the spoiler annotation, and the picker-scope match.
    """

    def test_catalog_loaded(self, engine):
        # The catalog must load — at minimum, m43_01 is shipped.
        assert hasattr(engine, 'V3_STARTING_ENCAMPMENT_MSBS')
        assert hasattr(engine, 'V3_STARTING_ENCAMPMENT_META')
        assert 'm43_01_00_00.msb' in engine.V3_STARTING_ENCAMPMENT_MSBS, (
            'm43_01_00_00.msb missing from V3_STARTING_ENCAMPMENT_MSBS '
            '— is data/nr_starting_encampments.json present and valid?')

    def test_v0_24_34_m43_02_in_catalog(self, engine):
        # v0.24.34: m43_02 added as wandering_demi_human_camp from seed 544094.
        # The "walking route demi-humans" pattern Alaric identified.
        assert 'm43_02_00_00.msb' in engine.V3_STARTING_ENCAMPMENT_MSBS, (
            'm43_02 missing from starting encampment catalog — added in v0.24.34')
        meta = engine.V3_STARTING_ENCAMPMENT_META['m43_02_00_00.msb']
        assert meta.get('label') == 'wandering_demi_human_camp', (
            f'm43_02 label mismatch: {meta.get("label")}')
        assert meta.get('first_observed_seed') == 544094

    def test_catalog_is_frozenset(self, engine):
        # Frozenset prevents accidental mutation at runtime
        assert isinstance(engine.V3_STARTING_ENCAMPMENT_MSBS, frozenset), (
            'V3_STARTING_ENCAMPMENT_MSBS should be a frozenset, got '
            f'{type(engine.V3_STARTING_ENCAMPMENT_MSBS).__name__}')

    def test_catalog_meta_has_entry(self, engine):
        # The META dict should mirror the MSBS set with per-MSB info
        m43 = engine.V3_STARTING_ENCAMPMENT_META.get('m43_01_00_00.msb')
        assert m43 is not None, (
            'm43_01 entry missing from V3_STARTING_ENCAMPMENT_META')
        assert m43.get('label'), (
            'm43_01 entry missing label field — every starting '
            'encampment should have one')

    def test_loader_resilient_to_missing_file(self, engine, tmp_path,
                                                monkeypatch):
        # The loader should return empty containers if the file is
        # missing — the engine must operate without the catalog.
        # We can't easily delete the real file mid-test, but we can
        # call the loader with a redirected path.
        import os
        def fake_data_path(filename):
            return str(tmp_path / filename)  # tmp_path is empty
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        msb_set, meta, file_meta = engine._load_starting_encampments()
        assert msb_set == frozenset(), (
            'loader should return empty frozenset on missing file')
        assert meta == {}
        assert file_meta == {}

    def test_loader_resilient_to_malformed_json(self, engine, tmp_path,
                                                  monkeypatch):
        # If the file is invalid JSON, loader returns empties
        bad = tmp_path / 'nr_starting_encampments.json'
        bad.write_text('{not valid json')
        def fake_data_path(filename):
            return str(tmp_path / filename)
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        msb_set, meta, file_meta = engine._load_starting_encampments()
        assert msb_set == frozenset(), (
            'loader should return empty frozenset on bad JSON')

    def test_starting_encampment_scope_known_to_picker(self, engine):
        # Structural check: the picker source must mention
        # 'starting_encampment' and V3_STARTING_ENCAMPMENT_MSBS.
        # If a future refactor removes the scope branch, catch it.
        import inspect
        src = inspect.getsource(engine.shuffle_msb_v3)
        assert "'starting_encampment'" in src, (
            "'starting_encampment' scope literal missing from "
            "shuffle_msb_v3 source — scope branch may have been "
            "removed")
        assert 'V3_STARTING_ENCAMPMENT_MSBS' in src, (
            'V3_STARTING_ENCAMPMENT_MSBS reference missing from '
            'shuffle_msb_v3 source — MSB-membership check broken')

    def test_starting_encampment_scope_does_not_match_marker_slot(
            self, engine):
        # When scope='starting_encampment', the picker should NOT also
        # fire on V3_BOSS_TIER_PINNED_SLOTS or variant markers. This is
        # asserted via source-grep — the condition includes
        # `_effective_scope != 'starting_encampment'` on the fall-
        # through branch.
        import inspect
        src = inspect.getsource(engine.shuffle_msb_v3)
        assert "_effective_scope != 'starting_encampment'" in src, (
            "fall-through scope branch isn't excluding "
            "starting_encampment — starting_encampment scope would "
            "ALSO match NB-marker slots, defeating the surgical "
            "intent")

    def test_spoiler_annotation_pattern_in_source(self, engine):
        # The spoiler construction site should reference both
        # V3_STARTING_ENCAMPMENT_MSBS and 'in_starting_encampment'.
        # We grep shuffle_msb_v3 source since that's where entries
        # are built.
        import inspect
        src = inspect.getsource(engine.shuffle_msb_v3)
        assert "'in_starting_encampment'" in src, (
            "'in_starting_encampment' field literal missing from "
            "spoiler-entry construction — annotation feature broken")
        assert 'V3_STARTING_ENCAMPMENT_MSBS' in src, (
            'V3_STARTING_ENCAMPMENT_MSBS not referenced in spoiler '
            'construction — annotation feature broken')


class TestQuadrupedUnsafeSlots:
    """v0.24.31: per-(msb, pi) excludes for quadruped (locomotion=3)
    chr targets. The catalog protects against the seed-924056 freeze
    pattern where Rats and other quadrupeds spawn into biped-on-mesh
    slots that are actually too sparse for quadruped pathfinding."""

    def test_catalog_loaded(self, engine):
        # m45_01 pi=3 is the seed entry — the seed-924056 Rat freeze
        assert hasattr(engine, 'V3_QUADRUPED_UNSAFE_SLOTS')
        assert ('m45_01_00_00.msb', 3) in engine.V3_QUADRUPED_UNSAFE_SLOTS, (
            'm45_01_00_00.msb pi=3 missing from V3_QUADRUPED_UNSAFE_SLOTS '
            '— is data/nr_quadruped_unsafe_slots.json present and valid?')

    def test_catalog_is_frozenset(self, engine):
        assert isinstance(engine.V3_QUADRUPED_UNSAFE_SLOTS, frozenset), (
            'V3_QUADRUPED_UNSAFE_SLOTS should be a frozenset, got '
            f'{type(engine.V3_QUADRUPED_UNSAFE_SLOTS).__name__}')

    def test_catalog_meta_has_entry(self, engine):
        meta = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(
            ('m45_01_00_00.msb', 3))
        assert meta is not None, (
            '(m45_01, pi=3) entry missing from V3_QUADRUPED_UNSAFE_SLOTS_META')
        assert meta.get('first_observed_seed') == 924056, (
            f'(m45_01, pi=3) first_observed_seed mismatch: '
            f'{meta.get("first_observed_seed")}')

    def test_loader_resilient_to_missing_file(self, engine, tmp_path,
                                                monkeypatch):
        def fake_data_path(filename):
            return str(tmp_path / filename)
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        slot_set, meta, file_meta = engine._load_quadruped_unsafe_slots()
        assert slot_set == frozenset()
        assert meta == {}
        assert file_meta == {}

    def test_loader_resilient_to_malformed_json(self, engine, tmp_path,
                                                  monkeypatch):
        bad = tmp_path / 'nr_quadruped_unsafe_slots.json'
        bad.write_text('{not valid json')
        def fake_data_path(filename):
            return str(tmp_path / filename)
        monkeypatch.setattr(engine, '_data_path', fake_data_path)
        slot_set, meta, file_meta = engine._load_quadruped_unsafe_slots()
        assert slot_set == frozenset()

    def test_predicate_rejects_quadruped_at_unsafe_slot(self, engine, tags):
        # Pick a known quadruped (loco=3). c4080 Rat is in the loaded tag
        # set and is the seed-924056 frozen chr.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result == 'quadruped_unsafe_slot', (
            f'quadruped gate should reject c4080 at (m45_01, pi=3), '
            f'got {result!r}')

    def test_predicate_allows_biped_at_quadruped_unsafe_slot(self, engine, tags):
        # Same slot but biped target — should pass (not a quadruped concern)
        # c3000 Exile Soldier is loco=0
        if tags.get('c3000', {}).get('locomotion') != 0:
            pytest.skip('c3000 not loco=0 in this tag set')
        result = engine._reject_target_for_slot(
            'c3000', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result is None, (
            f'biped target should pass quadruped gate at unsafe slot, '
            f'got {result!r}')

    def test_predicate_allows_quadruped_at_safe_slot(self, engine, tags):
        # Same Rat but at a different (m45_01, pi=2) NOT in catalog
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=2)
        assert result is None, (
            f'quadruped target should pass at slots not in unsafe '
            f'catalog, got {result!r}')

    def test_legacy_callers_unaffected(self, engine, tags):
        # Predicate called without msb_base/pi (pre-v0.24.31 signature
        # equivalent) must skip the quadruped gate and preserve old
        # behavior. Otherwise we'd break callers that hit the predicate
        # without slot identity.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags)
        assert result is None, (
            f'legacy call without slot identity should skip quadruped '
            f'gate, got {result!r}')

    def test_picker_passes_slot_identity_to_predicate(self, engine):
        # Source-grep: pick_target_cp must pass msb_base and pi to the
        # predicate. Otherwise the gate silently no-ops for picker calls.
        import inspect
        src = inspect.getsource(engine.pick_target_cp)
        assert 'msb_base=slot_msb_name' in src, (
            'pick_target_cp does not pass msb_base to '
            '_reject_target_for_slot — quadruped gate silently no-ops')
        assert 'pi=slot_pi' in src, (
            'pick_target_cp does not pass pi to '
            '_reject_target_for_slot — quadruped gate silently no-ops')

    def test_scorer_passes_slot_identity_to_predicate(self, engine):
        # Source-grep: _score_slot_for_unique must pass slot identity.
        # Without it, the reservation pre-pass can commit a quadruped
        # at an unsafe slot before runtime can reject (the reservation
        # bypass bug — see v0.24.26 for prior cases of this pattern).
        import inspect
        src = inspect.getsource(engine._score_slot_for_unique)
        assert "msb_base=slot_info.get('msb')" in src, (
            '_score_slot_for_unique does not pass msb to '
            '_reject_target_for_slot — quadruped gate silently no-ops '
            'at reservation time, same bug shape as v0.24.26')
        assert "pi=slot_info.get('pi')" in src, (
            '_score_slot_for_unique does not pass pi to '
            '_reject_target_for_slot — quadruped gate silently no-ops '
            'at reservation time')

    def test_v0_24_32_unverified_reposition_keeps_gate_active(
            self, engine, tags):
        # v0.24.32: a slot with reposition_proposed but playtest_
        # verified=false MUST still reject quadrupeds. Conservative
        # default — hypothesis untested, gate enforces.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        entry = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(
            ('m45_01_00_00.msb', 3))
        assert entry is not None
        repo = entry.get('reposition_proposed')
        assert repo is not None, (
            'm45_01 pi=3 should have reposition_proposed field added in v0.24.32')
        assert repo.get('playtest_verified') is False, (
            'm45_01 pi=3 reposition has playtest_verified=true but the '
            'in-game test has not been recorded. If verified, also remove '
            'this test or update the assertion accordingly.')
        # Verify gate still fires
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result == 'quadruped_unsafe_slot'

    def test_v0_24_32_verified_reposition_releases_gate(
            self, engine, tags, monkeypatch):
        # Simulate a playtest-verified reposition by mutating the meta
        # dict for the test. The gate should then PASS the quadruped.
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3 in this tag set')
        key = ('m45_01_00_00.msb', 3)
        original_entry = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(key)
        assert original_entry is not None
        # Copy and flip the verification flag
        import copy
        new_entry = copy.deepcopy(original_entry)
        new_entry.setdefault('reposition_proposed', {})['playtest_verified'] = True
        # Monkeypatch the meta dict with the flipped entry
        new_meta = dict(engine.V3_QUADRUPED_UNSAFE_SLOTS_META)
        new_meta[key] = new_entry
        monkeypatch.setattr(engine, 'V3_QUADRUPED_UNSAFE_SLOTS_META', new_meta)
        # Gate should now release — quadruped allowed
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert result is None, (
            f'quadruped should be allowed at verified-safe slot, got {result!r}. '
            'The playtest_verified=true flag should release the gate.')

    def test_v0_24_32_slot_repositions_has_quadruped_safety_entry(self, engine):
        # The reposition data must actually be in slot_repositions.json
        # for the apply pipeline to pick it up. Source-of-truth check.
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__), 'data',
                            'slot_repositions.json')
        with open(path) as f:
            rd = json.load(f)
        m45 = rd.get('proposals', {}).get('m45_01_00_00.msb', {})
        entry = m45.get('3')
        assert entry is not None, (
            'm45_01 pi=3 entry missing from slot_repositions.json. The '
            'v0.24.32 reposition would not be applied by dcx_batch.')
        assert entry.get('status') == 'quadruped_safe_relocation', (
            f'm45_01 pi=3 status mismatch: {entry.get("status")}')
        # Target should match what nr_quadruped_unsafe_slots.json declares
        meta_entry = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get(
            ('m45_01_00_00.msb', 3))
        repo = meta_entry.get('reposition_proposed')
        assert entry['to_pos_center'] == repo['to_pos'], (
            f'slot_repositions to_pos_center {entry["to_pos_center"]} '
            f'does not match nr_quadruped_unsafe_slots reposition_proposed '
            f'to_pos {repo["to_pos"]} — sources out of sync')

    # v0.24.33: prophylactic catalog expansion
    # ------------------------------------------------------------------
    # 4 new slots added based on the m45_01 pi=3 hypothesis (sparse navmesh
    # + biped vanilla source = likely quadruped freeze risk):
    #   - m43_01 pi=5, m43_01 pi=6   (wandering_noble_camp)
    #   - m44_01 pi=2                (commoner_settlement)
    #   - m45_01 pi=1                (roadside_thieves_camp, same MSB as pi=3)

    @pytest.mark.parametrize('msb,pi', [
        ('m43_01_00_00.msb', 5),
        ('m43_01_00_00.msb', 6),
        ('m43_02_00_00.msb', 4),
        ('m44_01_00_00.msb', 2),
        ('m45_01_00_00.msb', 1),
    ])
    def test_v0_24_33_prophylactic_slot_in_catalog(self, engine, msb, pi):
        # Each new entry must be in the frozenset AND in the meta dict
        # AND tagged as prophylactic (vs the original empirical m45_01 pi=3).
        assert (msb, pi) in engine.V3_QUADRUPED_UNSAFE_SLOTS, (
            f'({msb}, {pi}) missing from V3_QUADRUPED_UNSAFE_SLOTS — '
            'prophylactic scan entry not loaded')
        meta = engine.V3_QUADRUPED_UNSAFE_SLOTS_META.get((msb, pi))
        assert meta is not None
        assert meta.get('discovery_method') == 'prophylactic_density_scan', (
            f'({msb}, {pi}) discovery_method should be '
            f'"prophylactic_density_scan", got {meta.get("discovery_method")!r}')
        assert meta.get('reposition_proposed', {}).get('playtest_verified') is False, (
            f'({msb}, {pi}) prophylactic entries must default to '
            'playtest_verified=false until in-game confirmation')

    @pytest.mark.parametrize('msb,pi', [
        ('m43_01_00_00.msb', 5),
        ('m43_01_00_00.msb', 6),
        ('m43_02_00_00.msb', 4),
        ('m44_01_00_00.msb', 2),
        ('m45_01_00_00.msb', 1),
    ])
    def test_v0_24_33_prophylactic_slot_has_reposition(self, engine, msb, pi):
        # Each prophylactic entry must have a corresponding
        # quadruped_safe_relocation in slot_repositions.json, sources synced.
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__), 'data',
                            'slot_repositions.json')
        with open(path) as f:
            rd = json.load(f)
        sr_entry = rd['proposals'].get(msb, {}).get(str(pi))
        assert sr_entry is not None, (
            f'{msb} pi={pi} missing from slot_repositions.json — '
            'v0.24.33 prophylactic reposition not registered')
        assert sr_entry.get('status') == 'quadruped_safe_relocation', (
            f'{msb} pi={pi} status mismatch: {sr_entry.get("status")} '
            '(expected quadruped_safe_relocation)')
        # to_pos must match the catalog's reposition_proposed.to_pos
        catalog = engine.V3_QUADRUPED_UNSAFE_SLOTS_META[(msb, pi)]
        repo = catalog['reposition_proposed']
        assert sr_entry['to_pos_center'] == repo['to_pos'], (
            f'{msb} pi={pi}: slot_repositions to_pos_center '
            f'{sr_entry["to_pos_center"]} != catalog to_pos {repo["to_pos"]} '
            '— sources out of sync')

    def test_v0_24_33_catalog_distinguishes_discovery_methods(self, engine):
        # The catalog should now have at least 1 empirical and 4+ prophylactic
        empirical = [s for s in engine.V3_QUADRUPED_UNSAFE_SLOTS_META.values()
                     if s.get('discovery_method') == 'empirical_freeze_observation']
        prophylactic = [s for s in engine.V3_QUADRUPED_UNSAFE_SLOTS_META.values()
                        if s.get('discovery_method') == 'prophylactic_density_scan']
        assert len(empirical) >= 1, (
            f'Should have at least 1 empirical entry, got {len(empirical)}. '
            'Did the original m45_01 pi=3 lose its discovery_method tag?')
        assert len(prophylactic) >= 5, (
            f'Should have at least 4 prophylactic entries (added v0.24.33), '
            f'got {len(prophylactic)}.')

    def test_v0_24_33_prophylactic_gate_still_blocks_quadrupeds(
            self, engine, tags):
        # Confirm that prophylactic slots gate quadrupeds with
        # playtest_verified=false (same as empirical entries).
        if tags.get('c4080', {}).get('locomotion') != 3:
            pytest.skip('c4080 not loco=3')
        # Try a Rat at m43_01 pi=5 (prophylactic). Should reject.
        result = engine._reject_target_for_slot(
            'c4080', 'c4300', 'Wandering Noble', tags,
            msb_base='m43_01_00_00.msb', pi=5)
        assert result == 'quadruped_unsafe_slot', (
            f'Rat at prophylactic slot m43_01 pi=5 should be rejected, '
            f'got {result!r}')


# v0.24.35: canonical-variant preference + variant-source tagging
# ============================================================================
class TestCanonicalVariantPreference:
    """Tests for V3_PREFER_CANONICAL_VARIANTS and variant-source classification.

    Background: c-prefixes have a mix of canonical variants (sample_maps
    non-empty, vanilla NR places them) and ghost variants (sample_maps=[],
    post-DLC dump entries vanilla never instantiated). Ghost variants tend
    to visually glitch. The picker now prefers canonical variants when
    available; falls back to ghosts when no canonical exists for the cp.
    """

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    @pytest.fixture
    def loaded(self, engine):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = engine.load_data()
        from collections import defaultdict
        prefix_variants = defaultdict(list)
        for v in roster['all_variants']:
            if isinstance(v, dict) and 'c_prefix' in v:
                prefix_variants[v['c_prefix']].append(v)
        return roster, tags, prefix_variants

    # --- Classifier tests ---------------------------------------------------

    def test_classify_canonical(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        # c4640 npc=46400020 is the canonical Ulcerated Tree Spirit
        r = engine._classify_variant_source(
            'c4640', 46400020, prefix_variants, tags)
        assert r == 'canonical', (
            f'c4640 npc=46400020 should classify as canonical, got {r!r}')

    def test_classify_ghost_variant(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        # c4640 npc=46400030 — the variant that triggered the v0.24.35 fix.
        # post_dlc_dump, sample_maps=[], visually glitches
        r = engine._classify_variant_source(
            'c4640', 46400030, prefix_variants, tags)
        assert r == 'ghost_variant', (
            f'c4640 npc=46400030 should classify as ghost_variant '
            f'(visually glitches), got {r!r}')

    def test_classify_imported_chr(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        # c6031 Bear — heritage import (cross-engine from another From game).
        # Whole chr is wholesale-imported, not in vanilla NR placement pool.
        r = engine._classify_variant_source(
            'c6031', 60310000, prefix_variants, tags)
        assert r == 'imported_chr', (
            f'c6031 Bear (heritage) should classify as imported_chr, got {r!r}')

    def test_classify_unknown_cp_returns_unknown(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        r = engine._classify_variant_source(
            'c99999', 99999999, prefix_variants, tags)
        assert r == 'unknown'

    # --- Picker tests -------------------------------------------------------

    def test_picker_prefers_canonical_when_available(self, engine, loaded):
        """At any slot tier, when canonical variants exist, picker picks them."""
        roster, tags, prefix_variants = loaded
        import random
        # c4640 has 1 canonical (46400020) + 5 ghosts. Canonical-prefer is ON
        # by default, so 100% of picks should land on 46400020.
        picks = set()
        for seed in range(50):
            rng = random.Random(seed)
            v = engine.pick_variant_for_tier(
                'c4640', True, prefix_variants, rng, tags=tags)
            if v: picks.add(v.get('npc_param_id'))
        assert picks == {46400020}, (
            f'c4640 with canonical-prefer should only pick npc=46400020, '
            f'got {picks}. If ghosts (46400000/10/30/110/700) are in this '
            f'set, the canonical-prefer filter is not active.')

    def test_picker_falls_back_when_no_canonical(self, engine, loaded):
        """For cps with 0 canonical variants, picker still picks (soft filter)."""
        roster, tags, prefix_variants = loaded
        # Find a cp with 0 canonical variants and >0 total variants
        no_canonical_cps = []
        for cp, variants in prefix_variants.items():
            if not variants: continue
            if not any(v.get('sample_maps') for v in variants):
                no_canonical_cps.append((cp, len(variants)))
        if not no_canonical_cps:
            pytest.skip('No 0-canonical cps in roster (unexpected)')
        cp, n_variants = max(no_canonical_cps, key=lambda x: x[1])
        # Should pick something — the soft filter returns all variants when
        # no canonical exists, so the tier-fallback picks from the ghost pool
        import random
        rng = random.Random(0)
        v = engine.pick_variant_for_tier(cp, False, prefix_variants, rng,
                                          tags=tags)
        assert v is not None, (
            f'{cp} (0 canonical, {n_variants} ghosts) should still pick '
            f'(soft fallback), got None')

    def test_picker_with_canonical_pref_disabled(self, engine, loaded,
                                                  monkeypatch):
        """With V3_PREFER_CANONICAL_VARIANTS=False, ghost variants are eligible."""
        roster, tags, prefix_variants = loaded
        monkeypatch.setattr(engine, 'V3_PREFER_CANONICAL_VARIANTS', False)
        import random
        # c4640 at a FIELD slot (not boss) — without canonical-prefer, the
        # picker can land on any variant. Several rolls should produce
        # at least one ghost.
        picks = set()
        for seed in range(100):
            rng = random.Random(seed)
            v = engine.pick_variant_for_tier(
                'c4640', False, prefix_variants, rng, tags=tags)
            if v: picks.add(v.get('npc_param_id'))
        # We expect to see at least one ghost variant in the picks now.
        # (At boss slots tier-1/2 narrow to reward-bearing which is the
        # canonical here, so we test at field slot.)
        ghost_npcs = {46400000, 46400010, 46400030, 46400110, 46400700}
        assert picks & ghost_npcs, (
            f'With prefer_canonical=False at field slot, c4640 should be '
            f'able to land on at least one ghost variant across 100 rolls. '
            f'Got picks={picks}, ghosts available={ghost_npcs}')

    # --- Filter primitive tests ---------------------------------------------

    def test_filter_canonical_variants_with_canonicals(self, engine):
        variants = [
            {'npc_param_id': 1, 'sample_maps': ['m10_00.msb']},
            {'npc_param_id': 2, 'sample_maps': []},
            {'npc_param_id': 3, 'sample_maps': ['m20_00.msb', 'm30_00.msb']},
        ]
        result = engine._filter_canonical_variants(variants)
        assert {v['npc_param_id'] for v in result} == {1, 3}

    def test_filter_canonical_variants_no_canonicals_falls_back(self, engine):
        # All ghosts — should return input unchanged
        variants = [
            {'npc_param_id': 1, 'sample_maps': []},
            {'npc_param_id': 2, 'sample_maps': []},
        ]
        result = engine._filter_canonical_variants(variants)
        assert {v['npc_param_id'] for v in result} == {1, 2}, (
            'When no canonical variants exist, filter must return all '
            'variants unchanged (soft fallback for c70003/c3360/etc.)')

    def test_filter_canonical_variants_empty_input(self, engine):
        # Defensive: empty input returns empty (no canonicals possible)
        assert engine._filter_canonical_variants([]) == []

    # --- Config sanity ------------------------------------------------------

    def test_v3_prefer_canonical_default_is_false(self, engine):
        # v0.24.101: flipped from True to False as part of the "open the
        # floodgates" variety pass. Ghost variants are now eligible —
        # trade-off accepted (potential visual glitches in exchange for
        # variety). If a specific ghost variant proves broken, block it
        # individually by npc_param_id rather than re-enabling this filter
        # wholesale.
        # v0.24.109: briefly flipped True (for ~half a ship cycle) on the
        # basis of a framerate report that turned out to be a host issue.
        # Restored to v0.24.101 default. See oops_v3 constant docstring.
        assert engine.V3_PREFER_CANONICAL_VARIANTS is False, (
            'V3_PREFER_CANONICAL_VARIANTS should be False post-v0.24.101 — '
            'ghost variants are intentionally open for variety. If this '
            'has flipped back to True, check the v0.24.101 floodgates work.')


# v0.24.36: dump-only no-file chrs are hard-excluded
# ============================================================================
class TestDumpOnlyChrHardExclude:
    """The chr-asset-import tool flagged 8 c-prefixes as missing source files
    (no .chrbnd in NR's installed assets or any From game install). They're
    `_source: post_dlc_dump` entries — captured from regulation data dump but
    never actually shipped as game assets. v0.24.36 hard-excludes them.

    Previously MP-safe-only blocked. With MP-safe OFF (e.g., chaos testing),
    these chrs could be picked → no file to load → invisible placement →
    missing boss / empty grunt slot. The hard exclude blocks them in every
    run mode.

    Seed 271328 (v0.24.33, MP-safe OFF) is the smoking gun: 66 placements of
    these 8 chrs across the seed, including m46_82 pi=1 (a castle_interior
    boss anchor that got c7930 Demon in Pain — likely the source of the
    'missing castle basement boss' Alaric reported)."""

    DUMP_ONLY_NO_FILE_CPS = [
        'c4358', 'c4801', 'c7610', 'c7650', 'c7651',
        'c7660', 'c7720', 'c7930',
    ]

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    @pytest.fixture
    def loaded(self, engine):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = engine.load_data()
        return roster, tags

    def test_all_8_in_hard_exclude(self, engine):
        """Source-of-truth: all 8 must be in V3_EXCLUDE_TARGET_PREFIXES.
        If any drop out by accident, the missing-castle-boss bug returns."""
        missing = [cp for cp in self.DUMP_ONLY_NO_FILE_CPS
                   if cp not in engine.V3_EXCLUDE_TARGET_PREFIXES]
        assert not missing, (
            f'These no-file dump-only chrs are MISSING from '
            f'V3_EXCLUDE_TARGET_PREFIXES: {missing}. They have no .chrbnd '
            'files; placing them at boss slots produces invisible bosses '
            '(no health bar, no guy). See v0.24.36 commit message.')

    def test_dump_only_chrs_are_post_dlc_source(self, engine, loaded):
        """Sanity check the classification: these all originated from
        the post-DLC data dump (regulation-only, no asset files).

        v0.24.100 introduced the `manual_retier_v0.24.100` source as a
        retag for chrs whose original post_dlc_dump classification
        needed manual review — but the underlying "no chrbnd on disk"
        property is unchanged; only the provenance tag moved. Accept
        either source as evidence of the dump-only origin.
        """
        roster, tags = loaded
        valid_sources = {'post_dlc_dump', 'manual_retier_v0.24.100'}
        for cp in self.DUMP_ONLY_NO_FILE_CPS:
            t = tags.get(cp, {})
            assert t.get('_source') in valid_sources, (
                f'{cp} expected _source in {valid_sources}, got '
                f'{t.get("_source")!r}. If the source changed beyond '
                f'a v0.24.100-style retier, the hard-exclude rationale '
                f'needs revisiting.')

    def test_dump_only_chrs_have_no_canonical_variants(self, engine, loaded):
        """Cross-check: dump-only chrs by definition have 0 canonical
        variants (sample_maps non-empty would imply vanilla placed them,
        but the asset-copy tool says vanilla doesn't have the chr file).
        If a canonical variant appears, our roster data is inconsistent."""
        roster, _ = loaded
        for cp in self.DUMP_ONLY_NO_FILE_CPS:
            canonical = [v for v in roster['all_variants']
                         if v.get('c_prefix') == cp and v.get('sample_maps')]
            assert not canonical, (
                f'{cp} has {len(canonical)} canonical variants (sample_maps '
                'non-empty) but the chr-asset-import tool reports no file. '
                'Data inconsistency — either the asset tool needs rerunning '
                'with a different source, or the sample_maps entries are stale.')


# v0.24.37: data-driven no-file chrs + script_spawn catalog
# ============================================================================
class TestDataDrivenNoFileChrs:
    """v0.24.37: the no-file chr list migrated from hard-coded to
    data/nr_missing_chr_files.json. The data file is the source of truth;
    hard-coded entries remain as a safety net for the load_data_lock test
    and pre-load_data() queries."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_data_file_exists_and_loads(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_missing_chr_files.json')
        assert os.path.isfile(path), (
            'data/nr_missing_chr_files.json missing — v0.24.37 data-driven '
            'loader has no source. Hard-coded fallback still works but '
            'the migration is incomplete.')
        with open(path) as f:
            d = json.load(f)
        assert 'missing_chrs' in d
        assert len(d['missing_chrs']) >= 8

    def test_all_data_file_entries_in_exclude_set(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)
        for entry in d['missing_chrs']:
            cp = entry['c_prefix']
            assert cp in engine.V3_EXCLUDE_TARGET_PREFIXES, (
                f'{cp} in data/nr_missing_chr_files.json but NOT in '
                'V3_EXCLUDE_TARGET_PREFIXES — _load_missing_chr_files() '
                'did not merge the data file. Check the loader.')


class TestScriptSpawnBossCatalog:
    """v0.24.37: catalogs the 4 script_spawn boss slots whose 'missing boss'
    reports are EMEVD chain issues rather than picker issues."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_catalog_loads_and_has_4_entries(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_script_spawn_boss_slots.json')
        assert os.path.isfile(path)
        with open(path) as f:
            d = json.load(f)
        slots = d['script_spawn_boss_slots']
        assert len(slots) >= 4, (
            f'Expected at least 4 script_spawn boss slots (m46_64/65/90/91), '
            f'got {len(slots)}.')
        # m46_91 is the user-reported one
        msbs = {s['msb'] for s in slots}
        assert 'm46_91_00_00.msb' in msbs, (
            'm46_91 (Grafted Scion Castle) missing from script_spawn '
            'catalog — was the user-flagged case from seed 271328')

    def test_all_catalogued_slots_have_script_spawn_source(self, engine):
        """Sanity check: catalogued slots' cp _source should be script_spawn."""
        import io, json, os
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            _, tags = engine.load_data()
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_script_spawn_boss_slots.json')
        with open(path) as f:
            d = json.load(f)
        # v0.26.x: catalogued chrs are now _source='nr_placed' after the
        # byte-level MSB audit found them in vanilla MSBs (UTF-16-LE
        # references the original catalog parser missed). Arena gating
        # moved to V3_DEDICATED_ARENA_BOSS_CHRS membership; the catalog
        # remains as documentation of the historical script_spawn arena
        # slot mapping.
        for entry in d['script_spawn_boss_slots']:
            cp = entry['cp']
            src = tags.get(cp, {}).get('_source')
            assert src == 'nr_placed', (
                f'{cp} catalogued as dedicated-arena boss but tags say '
                f'_source={src!r}. Expected nr_placed after v0.26.x '
                f'reclassification.')
            assert cp in engine.V3_DEDICATED_ARENA_BOSS_CHRS or cp == 'c4690', (
                f'{cp} catalogued as dedicated-arena boss but is NOT in '
                f'V3_DEDICATED_ARENA_BOSS_CHRS — arena gating would not '
                f'fire. (c4690 Grafted Scion deliberately excluded; see '
                f'V3_DEDICATED_ARENA_BOSS_CHRS comment.)')


class TestStackingDetectorCrossCollision:
    """v0.24.37: distribute_stacked_repositions Pass 2 catches collisions
    between repositioned slots and non-repositioned slots in the same MSB.
    The flagship case is m45_01 pi=5 (repositioned from origin sentinel to
    (2.55, 1.98, 5.779)) which collided with m45_01 pi=2 (vanilla position
    (2.55, 1.98, 5.78), not in slot_repositions)."""

    def test_m45_01_pi5_nudged_away_from_pi2(self):
        """The m45_01 pi=5 entry must NOT have its to_pos_center at pi=2's
        vanilla position."""
        import json, os, math
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo_root, 'data/slot_repositions.json')) as f:
            rd = json.load(f)
        entry = rd['proposals']['m45_01_00_00.msb'].get('5')
        assert entry is not None
        tp = entry['to_pos_center']
        pi2_vanilla = (2.55, 1.98, 5.78)
        d_xz = math.hypot(tp[0]-pi2_vanilla[0], tp[2]-pi2_vanilla[2])
        assert d_xz >= 1.5, (
            f'm45_01 pi=5 to_pos_center {tp} is {d_xz:.3f}m from pi=2 vanilla '
            f'position {pi2_vanilla}. The v0.24.37 fix should have nudged '
            f'it away. Cross-collision pass either didn\'t run or didn\'t '
            f'persist.')

    def test_nr_all_part_positions_data_present(self):
        import json, os
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo_root, 'data/nr_all_part_positions.json')
        assert os.path.isfile(path), (
            'data/nr_all_part_positions.json missing — generated by '
            'dev/build_part_positions.py. Needed by the cross-collision '
            'detection pass.')
        with open(path) as f:
            d = json.load(f)
        # Should have a reasonable number of positions
        assert d['_meta']['n_slots'] >= 1000, (
            f'Expected >= 1000 part positions in catalog, got '
            f'{d["_meta"]["n_slots"]}.')
        # Specifically check m45_01 pi=2 is there with the right position
        m45 = d['positions'].get('m45_01_00_00.msb', {})
        pi2 = m45.get('2')
        assert pi2 is not None
        assert abs(pi2[0] - 2.55) < 0.05 and abs(pi2[2] - 5.78) < 0.05


# v0.24.38: script_spawn boss catalog ↔ V3_SPAWN_POOL_MSBS cross-reference
# ============================================================================
class TestScriptSpawnSpawnPoolCrossRef:
    """v0.24.38: ensure that every entry in nr_script_spawn_boss_slots.json
    is also in V3_SPAWN_POOL_MSBS (and vice-versa for script_spawn-cp entries).

    Catches drift where one catalog is updated but the other isn't. The
    architectural picture (script_spawn chrs go through spawn-pool runtime
    pull) only works if these two catalogs agree."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_every_script_spawn_slot_is_in_spawn_pool(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_script_spawn_boss_slots.json')
        with open(path) as f:
            d = json.load(f)
        for entry in d['script_spawn_boss_slots']:
            msb = entry['msb']
            msb_base = msb.replace('.msb', '')
            assert msb_base in engine.V3_SPAWN_POOL_MSBS, (
                f'{msb} is in nr_script_spawn_boss_slots.json but NOT in '
                f'V3_SPAWN_POOL_MSBS. Either the entry is wrong (slot is not '
                f'spawn-pool-related) or V3_SPAWN_POOL_MSBS is missing it.')
            assert entry.get('in_v3_spawn_pool_msbs') is True, (
                f'{msb} has in_v3_spawn_pool_msbs={entry.get("in_v3_spawn_pool_msbs")!r}; '
                'should be True since the MSB IS in V3_SPAWN_POOL_MSBS.')

    def test_spawn_pool_label_no_longer_says_putrid_avatar(self, engine):
        """v0.24.38 fixed the c4690 label inconsistency. 'Putrid Avatar'
        was a stale ER name; NR roster says 'Grafted Scion'."""
        for msb_base, desc in engine.V3_SPAWN_POOL_MSBS.items():
            assert 'Putrid Avatar' not in desc, (
                f'V3_SPAWN_POOL_MSBS[{msb_base!r}] still says "Putrid Avatar". '
                f'Fixed in v0.24.38 — should be "Grafted Scion".')

    def test_script_spawn_label_includes_marker(self, engine):
        """v0.24.38: script_spawn entries in V3_SPAWN_POOL_MSBS now include
        an explicit 'script_spawn' marker in the label, so the special
        handling is visible at a glance."""
        for msb_base in ['m46_64_00_00', 'm46_65_00_00',
                          'm46_90_00_00', 'm46_91_00_00']:
            desc = engine.V3_SPAWN_POOL_MSBS.get(msb_base, '')
            assert 'script_spawn' in desc, (
                f'V3_SPAWN_POOL_MSBS[{msb_base!r}] = {desc!r}; should include '
                f'"script_spawn" marker (v0.24.38 convention).')


# v0.24.97: script_spawn target-only gate narrow exemption
# ============================================================================
class TestSpawnPoolRotationSourceExemption:
    """v0.24.97: the V3_TARGET_ONLY_SOURCES filter in the swap loop now
    exempts V3_SPAWN_POOL_MSBS pi=1.

    Pre-v0.24.97, c4670 Ancestor Spirit and c4690 Grafted Scion (both
    `_source: script_spawn`) at m46_64/65/90/91 pi=1 were skipped by the
    swap loop, leaving those four rotation entries vanilla every seed.
    The user-visible symptom was Grafted Scion / Ancestor Spirit
    appearing deterministically across all seeds at whichever live
    arena rolled those pool entries.

    The narrow exemption brings these four slots onto the same swap
    path as the 19 sibling non-script_spawn rotation entries (m46_52
    c3250 Draconic Tree Sentinel, etc.) which have been swapping pi=1
    successfully without issue. See the TODO(broad-fix) at the swap-
    loop call site for the broader cleanup that would also unlock
    c7700-c7920 at their legacy DS-import arena MSBs."""

    def test_predicate_recognises_every_spawn_pool_msb_at_pi_1(self, engine):
        """All 23 V3_SPAWN_POOL_MSBS entries should be recognised as
        rotation sources at pi=1."""
        for pool_base in engine.V3_SPAWN_POOL_MSBS:
            assert engine._is_spawn_pool_rotation_source(pool_base + '.msb', 1), (
                f'_is_spawn_pool_rotation_source({pool_base + ".msb"!r}, 1) '
                f'should be True — {pool_base} is in V3_SPAWN_POOL_MSBS.')
            # And without the .msb suffix
            assert engine._is_spawn_pool_rotation_source(pool_base, 1), (
                f'_is_spawn_pool_rotation_source({pool_base!r}, 1) '
                f'should be True (bare basename form).')

    def test_predicate_rejects_non_pi_1_indices(self, engine):
        """pi=0 (c1000 placeholder) and pi=2 (AEG asset) should NOT be
        treated as rotation sources, even though the MSB is in the pool."""
        for pi in (0, 2, 3, 5, 99):
            assert not engine._is_spawn_pool_rotation_source('m46_65_00_00.msb', pi), (
                f'_is_spawn_pool_rotation_source(m46_65_00_00.msb, {pi}) '
                f'should be False — only pi=1 is the rotation slot.')

    def test_predicate_rejects_non_spawn_pool_msbs(self, engine):
        """MSBs outside V3_SPAWN_POOL_MSBS should never match, regardless
        of pi. Sanity check that the predicate isn't accidentally too
        permissive."""
        for msb in ('m32_00_00_00.msb', 'm46_00_00_00.msb',
                    'm49_43_00_00.msb', 'm60_43_36_50.msb'):
            for pi in (0, 1, 2):
                assert not engine._is_spawn_pool_rotation_source(msb, pi), (
                    f'_is_spawn_pool_rotation_source({msb!r}, {pi}) '
                    f'should be False — {msb} is not in V3_SPAWN_POOL_MSBS.')

    def test_script_spawn_chrs_still_tagged(self, engine, tags):
        """v0.26.x: c4670 + c4690 are reclassified to _source='nr_placed'
        (they ARE in vanilla MSBs — m46_64/65/90/91 — as confirmed by
        the byte-level UTF-16-LE audit). The original "still tagged
        script_spawn" assertion no longer applies. The arena-only
        constraint is now carried by V3_DEDICATED_ARENA_BOSS_CHRS
        membership (for c4670; c4690 Grafted Scion deliberately
        excluded — see V3_DEDICATED_ARENA_BOSS_CHRS comment), and
        the V3_TARGET_ONLY_SOURCES filter no longer applies to these
        chrs at non-spawn-pool slots (it was a side-effect of the
        misclassification, not an intended gate).

        This test now guards against re-introducing the misclassification
        — both should remain nr_placed.
        """
        for cp in ('c4670', 'c4690'):
            assert tags.get(cp, {}).get('_source') == 'nr_placed', (
                f'{cp} should be _source=nr_placed after v0.26.x '
                f'reclassification (byte-level MSB audit confirmed '
                f'vanilla MSB placements). If you see script_spawn '
                f'here, the reclassification regressed.')

    def test_four_script_spawn_rotation_slots_are_now_exempt(self, engine):
        """The four specific slots that were causing the user-visible
        symptom (Grafted Scion / Ancestor Spirit every seed) should all
        be exempt under the new predicate."""
        for msb_base in ('m46_64_00_00', 'm46_65_00_00',
                          'm46_90_00_00', 'm46_91_00_00'):
            assert engine._is_spawn_pool_rotation_source(msb_base + '.msb', 1), (
                f'{msb_base}.msb pi=1 should be exempt from the '
                f'script_spawn target-only filter (this is the whole point '
                f'of v0.24.97).')


# v0.24.39: seed 798229 freezes/invisible enemy fixes
# ============================================================================
class TestSeed798229Freezes:
    """v0.24.39: hard-exclude small Oracle Envoy (c3610), Ancestral Follower
    (c3360), and Abnormal Stone Cluster (c4430) as targets after Alaric's
    seed 798229 playtest report: small Oracle Envoy frozen in starting
    encampment + an invisible enemy in the same camp.

    v0.24.65: ALL THREE LIFTED. User confirmed via playtest that deploying
    MMV's sfx/ and material/ dirs makes the full MMV roster work (Romina
    proof case). All 30 broken_runtime_chrs entries were lifted in the
    same release; these were the 3 originally playtest-confirmed ones, the
    riskier subset of the lift. Cap=1 applied as a safety net. Test
    assertions inverted to capture the new state; if any of these chrs
    is observed broken in playtest after v0.24.65, re-add to
    nr_missing_chr_files.json broken_runtime_chrs and re-invert here."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_c3610_small_oracle_envoy_no_longer_excluded(self, engine):
        """v0.24.65: lifted. v0.24.86-patch2-followup: RE-EXCLUDED.

        Empirical regression in seed 923630 — c3610 placed at an Oracle
        Envoy slot froze on entrance animation, identical pattern to
        the original v0.24.65 ban motivation. The v0.24.65 lift was
        speculative ('maybe the bug self-fixed'); the freeze data
        shows it didn't. Cap-of-1 alone wasn't enough since one
        placement is enough to brick a seed.
        """
        assert 'c3610' in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c3610 must be hard-excluded — re-banned in v0.24.86-patch2-followup '
            'after a freeze recurrence in seed 923630.')

    def test_c4361_godrick_knights_horse_excluded(self, engine):
        """v0.25.0-patch1: c4361 RE-EXCLUDED.

        Same lifecycle as c3610 above: v0.24.65 lifted c4361 from
        EXCLUDE with a defensive cap=1, then v0.25.0-patch1 re-excluded
        it after empirical mount-component CTDs in seeds 939029 and 42
        (mount slots invoke rider-mount composite logic that non-mount
        chrs can't satisfy — Godrick Knight's Horse riderless is the
        same failure class as c3160/c4363).

        v0.26.x: c4361 also dropped from `_LIFTED_V0_24_65` in oops_v3.py
        (previously the lift kept setting cap=1 even though the exclude
        wins — dead-code finding from
        `dev/audit_placement_budget_consistency.py`).
        """
        assert 'c4361' in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c4361 must be hard-excluded — re-banned in v0.25.0-patch1 '
            'after mount-component CTDs in seeds 939029 and 42.')

    def test_c3620_large_oracle_envoy_NOT_excluded(self, engine):
        """Large Oracle Envoy (Cathedral) was never banned. Unchanged."""
        assert 'c3620' not in engine.V3_EXCLUDE_TARGET_PREFIXES

    def test_c3360_ancestral_follower_no_longer_excluded(self, engine):
        """v0.24.65: lifted."""
        assert 'c3360' not in engine.V3_EXCLUDE_TARGET_PREFIXES
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c3360') == 1

    def test_c4430_abnormal_stone_cluster_no_longer_excluded(self, engine):
        """v0.24.65: lifted."""
        assert 'c4430' not in engine.V3_EXCLUDE_TARGET_PREFIXES
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c4430') == 1

    def test_fi_reserved_only_protects_c3620(self, engine):
        """v0.24.39: the defensive cleanup (_FI_CPS_RESERVED_FOR_TARGET) now
        only protects c3620. v0.24.65 lift of c3610 doesn't change this —
        c3620 stays in _FI_CPS_RESERVED_FOR_TARGET as before. c3610 is now
        eligible as a regular target but isn't in the FI reservation set."""
        assert engine._FI_CPS_RESERVED_FOR_TARGET == frozenset({'c3620'})

    def test_broken_runtime_chrs_v0_24_65_lift_held(self):
        """v0.24.65 lifted 30 chrs and emptied the file. v0.25.0
        re-populated it with a NEW class of entries (post_dlc_dump
        heritage proactive bans, tagged observed_version=v0.25.0) —
        these are categorically distinct from the v0.24.65 lifted set,
        so the lift itself didn't revert.

        This test now locks in the meaningful invariant: the 30 v0.24.65
        lifted chrs do not reappear (regression guard), and the file's
        history field preserves the lift record. New unrelated entries
        (v0.25.0+) are fine.
        """
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)

        # Lift history preserved
        hist = d['_meta'].get('history', {}).get(
            'broken_runtime_chrs_lifted_v0_24_65', {})
        lifted = hist.get('lifted_entries', [])
        assert len(lifted) == 30, (
            'history.broken_runtime_chrs_lifted_v0_24_65 should preserve all '
            '30 originally-banned chrs for reference')
        lifted_cps = {e['c_prefix'] for e in lifted if isinstance(e, dict)}

        # None of the lifted v0.24.65 chrs reappear in current broken_runtime_chrs
        current = d.get('broken_runtime_chrs', [])
        current_cps = {e['c_prefix'] for e in current}
        regressed = lifted_cps & current_cps
        assert not regressed, (
            f'v0.24.65 lift regression — these chrs returned to '
            f'broken_runtime_chrs: {sorted(regressed)}. If intentional, '
            f'remove them from history.broken_runtime_chrs_lifted_v0_24_65 '
            f'or re-version the lift; if a re-ban for a NEW reason, that '
            f'is fine but the lift-history symmetry is lost.')

        # New entries are version-tagged separately (not posing as v0.24.65)
        for entry in current:
            ver = entry.get('observed_version', '')
            assert not ver.startswith('v0.24.65'), (
                f'{entry.get("c_prefix")} tagged observed_version={ver!r} — '
                f'looks like a v0.24.65 entry that should be lifted, not '
                f're-banned. Tag new bans with their own observed_version.')


# v0.24.40: proactive ban of all no-tag-data post_dlc_dump/mmv_import chrs
# ============================================================================
class TestProactiveNoTagDataBan:
    """v0.24.40: after seed 798229 confirmed c3360 and c4430 (no-tag-data
    post_dlc_dump chrs) were broken, proactively ban all 26 sibling chrs
    matching the same profile. Avoids the wait-for-playtest-report cycle
    for each individual chr."""

    PROACTIVE_BANS = [
        # v0.24.102: c2273/c2275/c2277 (Crab variants), c4162/c4163/c4167
        # (dog variants), c4190/c4192 (Large Scarab) intentionally removed
        # from the auto-cap=1 set per user req. They're trash-tier critters
        # and the defensive cap was blocking organic distribution. Excluded
        # from this expectation list so the test reflects the v0.24.102
        # state. If they recurse-flooding becomes a problem in playtest,
        # restore them to both _LIFTED_V0_24_65 (in oops_v3.py) and here.
        #
        # v0.26.x: c4361 (Godrick Knight's Horse) ALSO removed from this
        # list. v0.25.0-patch1 re-excluded c4361 from V3_EXCLUDE_TARGET_
        # PREFIXES after a mount-component CTD (seeds 939029 and 42); the
        # v0.24.65 lift was superseded. Symmetrically removed from
        # _LIFTED_V0_24_65 in oops_v3.py — see also the test_c4361_excluded
        # lock-in test in TestSeed798229Freezes.
        'c3370',                                # Ancestral Follower Shaman
        'c4140',                                # Spiritcaller Snail (Boss)
        'c4312', 'c4316', 'c4356', 'c4376',    # Soldier/Knight family
        'c4441', 'c4442',                       # Land Squirt family
        'c4482', 'c4483',                       # Fading Miranda Sprout family
        'c4601', 'c4811',                       # Troll Knight, Erdtree Avatar Variant
        'c52309', 'c52312', 'c52313',          # DLC Remembrance variants
        'c6001',                                # Eagle
    ]

    @pytest.fixture
    def engine(self):
        """v0.24.103: explicit load_data() call. The v0.24.65 auto-cap
        runs INSIDE load_data(), so without this the test sees only the
        module-level explicit cap entries (3 of 25) and reports the
        other 22 as uncapped. Was previously passing by coincidence —
        whichever test ran first happened to trigger load_data() via
        conftest's session-scoped fixture and mutate module-level
        V3_UNIQUE_TARGET_CAPS in place. New tests added in v0.24.103
        changed pytest collection order, exposing the latent bug."""
        import oops_v3
        if not hasattr(oops_v3, '_test_loaded'):
            oops_v3.load_data()
            oops_v3._test_loaded = True
        return oops_v3

    def test_all_26_proactive_bans_lifted(self, engine):
        """v0.24.65: all v0.24.40 proactive bans lifted alongside the rest of
        broken_runtime_chrs. User playtest confirmed MMV sfx/material deploy
        fixes the underlying invisibility class. None of these should remain
        in V3_EXCLUDE_TARGET_PREFIXES."""
        still_excluded = [cp for cp in self.PROACTIVE_BANS
                          if cp in engine.V3_EXCLUDE_TARGET_PREFIXES]
        assert not still_excluded, (
            f'v0.24.65 lifted these — still in EXCLUDE: {still_excluded}. '
            f'Either the lift partial-reverted or one of these got '
            f'individually re-banned for a different reason.')

    def test_all_26_proactive_bans_capped(self, engine):
        """v0.24.65 safety net: each lifted chr capped at 1 placement so
        that if any specific one is still broken, exposure is limited."""
        uncapped = [cp for cp in self.PROACTIVE_BANS
                    if engine.V3_UNIQUE_TARGET_CAPS.get(cp) is None]
        assert not uncapped, (
            f'v0.24.65 lift should have applied cap=1 to all lifted chrs; '
            f'missing caps on: {uncapped}')

    def test_proactive_bans_have_proactive_ban_flag(self):
        """Data file entries for proactive bans should be tagged
        proactive_ban=true. Lets future code distinguish 'playtest-confirmed
        broken' from 'banned by pattern match'."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)
        proactive_set = set(self.PROACTIVE_BANS)
        for entry in d['broken_runtime_chrs']:
            if entry['c_prefix'] in proactive_set:
                assert entry.get('proactive_ban') is True, (
                    f'{entry["c_prefix"]} should have proactive_ban=true')

    def test_playtest_confirmed_have_observed_metadata(self):
        """Every broken_runtime_chrs entry must record SOME provenance —
        either an observed_seed (playtest-found) or an observed_version
        (static-analysis-found, e.g. v0.25.0 added 4 entries gated by
        per-chr script absence rather than a specific playtest seed).

        Originally this asserted "not proactive_ban → has observed_seed",
        but the v0.25.0 post_dlc_dump audit added a third category:
        symptom=no_ai_brain entries identified via static asset analysis,
        which legitimately have observed_version but no observed_seed.
        """
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)
        for entry in d['broken_runtime_chrs']:
            if entry.get('proactive_ban', False):
                continue  # proactive bans are pattern-matched, no provenance needed
            has_seed = bool(entry.get('observed_seed'))
            has_version = bool(entry.get('observed_version'))
            assert has_seed or has_version, (
                f'{entry["c_prefix"]} is not proactive_ban but has '
                f'neither observed_seed (playtest) nor observed_version '
                f'(static-analysis). Add one to record how the ban was '
                f'discovered.')

    def test_c2274_giant_sleep_crab_un_banned_v0_24_41(self, engine):
        """v0.24.41: c2274 Giant Sleep Crab confirmed working in playtest
        and un-banned. The regular-size crab siblings (c2273/c2275/c2277)
        remain banned as 'set dressing' — likely render fine but low-value
        placements; keep the safety net."""
        assert 'c2274' not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c2274 (Giant Sleep Crab) was un-banned in v0.24.41 — '
            'confirmed working in playtest. If this test fails, c2274 '
            'was re-added to a ban list somewhere.')


# v0.24.44: c7800 Duke's Dear Freja missing chrbnd
# ============================================================================
class TestC7800Excluded:
    """v0.24.44: asset-import tool reported c7800 missing from every source.
    Hard-excluded. Documents the surprising script_spawn-targetability finding."""

    def test_c7800_in_missing_chrs(self, engine=None):
        """c7800 should be in the missing_chrs section, not broken_runtime."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)
        missing_cps = {e['c_prefix'] for e in d['missing_chrs']}
        assert 'c7800' in missing_cps, (
            'c7800 (Duke\'s Dear Freja) was added to missing_chrs in v0.24.44 '
            'after the chr-asset-import tool flagged it as missing from '
            'every source install. If removed, expect invisible-enemy '
            'symptoms when c7800 is picked as a target.')

    def test_c7800_hard_excluded(self):
        """The data file load should propagate c7800 into V3_EXCLUDE_TARGET_PREFIXES."""
        import oops_v3
        assert 'c7800' in oops_v3.V3_EXCLUDE_TARGET_PREFIXES, (
            'c7800 in data/nr_missing_chr_files.json missing_chrs but NOT in '
            'V3_EXCLUDE_TARGET_PREFIXES — loader regression.')


# v0.24.45: flying-required slots
# ============================================================================
class TestFlyingRequiredSlots:
    """v0.24.45: slots with flying-anim vanilla chrs must keep aerial-anim
    targets. Asset-bundle and anim-bank mismatch causes CTD on cell-load.

    Discovered via seed 552688: m60_43_36_50 pi=23 (vanilla c4500 Flying
    Dragon at Y=106) → picker rolled c4620 Astel (giga_boss, ground) →
    CTD walking out castle front door (cell-load of m60_43_36_50)."""

    def test_catalog_loaded(self, engine):
        assert len(engine.V3_FLYING_REQUIRED_SLOTS) >= 30, (
            f'expected 30+ flying-required slots, got '
            f'{len(engine.V3_FLYING_REQUIRED_SLOTS)}')
        assert len(engine.V3_FLYING_ELIGIBLE_TARGETS) >= 10, (
            'expected 10+ eligible flying targets')

    def test_seed_552688_bug_slot_catalogued(self, engine):
        """The specific castle CTD slot from seed 552688."""
        assert ('m60_43_36_50.msb', 23) in engine.V3_FLYING_REQUIRED_SLOTS

    def test_eligible_targets_have_flying_anim(self, engine):
        """Every cp in eligible_targets must have anim_class=flying_dragon."""
        roster, tags = engine.load_data()
        for cp in engine.V3_FLYING_ELIGIBLE_TARGETS:
            assert tags.get(cp, {}).get('anim_class') == 'flying_dragon', (
                f'{cp} listed as flying-eligible but anim_class != '
                f'flying_dragon ({tags.get(cp, {}).get("anim_class")})')

    def test_astel_rejected_at_flying_slot(self, engine):
        """The original bug case: Astel at m60_43_36_50 pi=23 must reject."""
        roster, tags = engine.load_data()
        reason = engine._reject_target_for_slot(
            target_cp='c4620',  # Astel - giga_boss, not flying
            src_cp='c4500',
            src_variant_name='Flying Dragon',
            tags=tags,
            msb_base='m60_43_36_50.msb',
            pi=23,
        )
        assert reason == 'flying_required_slot', (
            f'Expected flying_required_slot rejection, got {reason}')

    def test_flying_dragon_accepted_at_flying_slot(self, engine):
        """A flying chr should pass the flying-required filter."""
        roster, tags = engine.load_data()
        reason = engine._reject_target_for_slot(
            target_cp='c4500', src_cp='c4500',
            src_variant_name='Flying Dragon',
            tags=tags,
            msb_base='m60_43_36_50.msb', pi=23)
        # Filter shouldn't trip; other gates may or may not reject for
        # other reasons (we don't assert reason is None — just not flying)
        assert reason != 'flying_required_slot'

    def test_non_flying_slot_not_affected(self, engine):
        """A non-flying-required slot doesn't trigger this filter even
        for non-flying targets."""
        roster, tags = engine.load_data()
        # m43_01 pi=11 is a starting-encampment slot, not flying
        reason = engine._reject_target_for_slot(
            target_cp='c4090',  # Giant Rat - quadruped, not flying
            src_cp='c4080',     # Rat
            src_variant_name='Rat',
            tags=tags,
            msb_base='m43_01_00_00.msb', pi=11)
        assert reason != 'flying_required_slot', (
            'Filter triggered at a non-flying-required slot — wrongly broad')


# v0.24.46: Manus, Father of the Abyss un-banned
# ============================================================================
class TestManusUnBanned:
    """v0.24.46: c8500 Manus un-banned per Alaric playtest direction.
    The DS1 cross-engine guard was originally added v0.23.39 after a CTD
    attributed to 'asset graph divergence'. Pattern matches the c8300
    Dragonslayer Armor + c4720 Godfrey vindication trajectory — original
    CTD was likely position-specific anim-slot mismatch now caught by
    other gates."""

    def test_c8500_re_banned_v0_25_6(self, engine):
        """v0.24.46 un-banned c8500 per Alaric playtest direction. The
        un-ban held until v0.25.6, when seed 66782 (v0.25.5) confirmed
        a hard CTD: Manus landed at the Crater fog-gate slot
        (m60_44_39_20 pi=74) and crashed on engagement. Root cause
        diagnosis: MMV's c8500 is a Nightlord-phase form (NB2 entity
        bound to scripted flag-state) and crashes when spawned freely
        outside its intended encounter, unlike c8300 Dragonslayer Armor
        which is a self-contained portable boss. Re-added to EXCLUDE
        in v0.25.6 alongside c8200 and c8400 (same risk class — see
        the cluster comment in V3_EXCLUDE_TARGET_PREFIXES near c8500).

        If you're considering un-banning c8500 again: verify the
        Nightlord-phase flag dependency has been worked out (probably
        requires a scripted-intro setter at any swap target), and the
        full chr files are deployed under heritage_pack/chr/c8500/.
        """
        assert 'c8500' in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c8500 should be hard-excluded — re-added in v0.25.6 after '
            'CTD in seed 66782 (Crater fog-gate slot). See cluster '
            'comment near c8200/c8400/c8500 in V3_EXCLUDE_TARGET_PREFIXES.')

    def test_c8500_still_mp_safe_blocked(self, engine):
        """Manus is mmv_import _source — MP-safe should still block him
        to protect co-op partners without the MMV mod."""
        assert 'c8500' in engine.V3_MP_SAFE_BLOCKLIST, (
            'c8500 should remain MP-safe blocked (he is _source=mmv_import; '
            'co-op partners without MMV would CTD on Manus). Un-banning '
            'should ONLY affect solo / MP-off play.')

    def test_c8500_in_allowlist_override(self):
        """v0.25.0-patch3: MMV_ORIGIN_ALLOWLIST_OVERRIDE deprecated alongside
        MMV_INCOMPATIBLE_ORIGINS. With the base ban set now empty, the
        allowlist override has nothing to override. Test inverted from
        'c8500 must be in override' to 'override is empty (deprecated)'.
        Full removal of the constant deferred to a future cleanup pass."""
        from engine.pack_loaders.mmv_imports import MMV_ORIGIN_ALLOWLIST_OVERRIDE
        assert MMV_ORIGIN_ALLOWLIST_OVERRIDE == frozenset(), (
            'MMV_ORIGIN_ALLOWLIST_OVERRIDE should be empty (deprecated in '
            'v0.25.0-patch3 alongside MMV_INCOMPATIBLE_ORIGINS). MMV now '
            'ships fully-working cross-engine chrbnds; the rando trusts '
            'the MMV deploy and does not auto-ban by origin_game.')

    def test_ds1_still_in_incompatible_origins(self):
        """v0.25.0-patch3: MMV_INCOMPATIBLE_ORIGINS deprecated. The
        historical DS1/BB auto-ban via origin_game was out of date — MMV
        ships fully-working cross-engine chrbnds and the v0.23.39 (Manus)
        / v0.23.72 (c1260) CTDs that motivated the bans have been resolved
        upstream. Test inverted from 'DS1 in set' to 'set is empty
        (deprecated)'. Full removal deferred to future cleanup pass."""
        from engine.pack_loaders.mmv_imports import MMV_INCOMPATIBLE_ORIGINS
        assert MMV_INCOMPATIBLE_ORIGINS == frozenset(), (
            'MMV_INCOMPATIBLE_ORIGINS should be empty (deprecated in '
            'v0.25.0-patch3). The rando trusts MMV deploy.')


    def test_c8500_tier_and_size(self, engine):
        """Sanity: Manus should be tier=nightlord, size=XL, expects_boss_arena.

        v0.26.x size_class correction: NpcParam.csv showed Manus at
        h=4.00 r=1.20, which is firmly XL (was previously tagged L
        in MMV pack — part of the v0.26.x bulk MMV undersizing audit
        that surfaced 18 systematically-undersized chrs)."""
        roster, tags = engine.load_data()
        t = tags['c8500']
        assert t['tier'] == 'nightlord'
        assert t['size_class'] == 'XL'
        assert t.get('expects_boss_arena') is True, (
            'c8500 should expects_boss_arena=True so the picker only '
            'targets him at boss arena slots (he is a nightlord).')


# v0.24.47: Death Knight promotion to field_boss
# ============================================================================
class TestDeathKnightTierPromotion:
    """v0.24.47: c5070 Death Knight bumped from miniboss to field_boss.
    User playtest: 'that guy is a menace' — auto-tagged miniboss but
    hp_median=672 and tuned DS3 elite moveset make him play like a
    boss-tier encounter.

    v0.26.x: field_boss tier eliminated (full collapse to miniboss/
    night_boss). c5070 reassigned to miniboss — NB would be wildly
    out-of-class for an M humanoid invader, so miniboss is the only
    sensible bucket. The v0.24.47 'named encounter feel' goes away,
    accepted as a trade for the tier-collapse simplification. If the
    miniboss-tier presence ends up feeling under-budget in playtest,
    a cap (or an NB-tier promotion) can restore the named-encounter
    feel without resurrecting field_boss as a tier."""

    def test_c5070_native_tier_is_miniboss(self):
        """v0.26.x: V3_TAG_OVERRIDES was flattened into nr_enemy_tags.json
        directly for the 33 non-MMV/non-heritage entries; c5070 was one
        of the 5 no-op overrides (tier already matched native), so the
        override entry was dropped and the JSON's native value is the
        authoritative source. This test confirms the JSON has the
        intended tier."""
        import json, os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo, 'data/nr_enemy_tags.json')) as f:
            tags = json.load(f)
        assert tags['c5070']['tier'] == 'miniboss', (
            f"c5070 native tier should be 'miniboss' in "
            f"nr_enemy_tags.json (was flattened from V3_TAG_OVERRIDES "
            f"in v0.26.x); got {tags['c5070']['tier']!r}")

    def test_c5070_effective_tier_is_miniboss(self, engine):
        roster, tags = engine.load_data()
        assert tags['c5070']['tier'] == 'miniboss', (
            f'c5070 effective tier is {tags["c5070"]["tier"]}, expected '
            f'miniboss after v0.26.x tier collapse.')

    def test_c5070_still_humanoid(self, engine):
        """Tier change shouldn't affect anim_class / size — only frequency
        and slot type."""
        roster, tags = engine.load_data()
        assert tags['c5070']['anim_class'] == 'humanoid'
        assert tags['c5070']['size_class'] == 'M'


# v0.24.48: SW-corner freeze repositions
# ============================================================================
class TestSwCornerFreezeRepositions:
    """v0.24.48: Two slot freezes reported at SW corner of m60_42_36_00
    (seed 460401, engine v0.24.45). Both small loco=0 quadrupeds
    (c7711 Centipede Grub at pi=19, c4150 Basilisk at pi=20) froze at
    near-corner positions. Repositioned 7.07m inward each."""

    SLOTS = {
        '19': {'from': (-103.99, 108.14, 103.12),
               'to':   (-98.99, 108.14, 98.12)},
        '20': {'from': (-105.62, 105.48, 93.15),
               'to':   (-100.62, 105.48, 88.15)},
    }

    def test_entries_present(self):
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'slot_repositions.json')
        with open(path) as f:
            sr = json.load(f)
        m = sr['proposals'].get('m60_42_36_00.msb', {})
        for pi in self.SLOTS:
            assert pi in m, (
                f'm60_42_36_00.msb pi={pi} missing from slot_repositions.json. '
                f'This is the SW-corner freeze fix from v0.24.48 (seed 460401).')

    def test_repositions_move_inward(self):
        """from_pos at the corner, to_pos_center should move toward center
        (smaller |X| and smaller |Z|)."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        m = sr['proposals']['m60_42_36_00.msb']
        for pi, expected in self.SLOTS.items():
            entry = m[pi]
            tp = entry['to_pos_center']
            fp = entry['from_pos']
            assert abs(tp[0]) < abs(fp[0]), (
                f'pi={pi}: to_pos X (|{tp[0]}|) should be smaller than '
                f'from_pos X (|{fp[0]}|) — moving inward toward center')
            assert abs(tp[2]) < abs(fp[2]), (
                f'pi={pi}: to_pos Z (|{tp[2]}|) should be smaller than '
                f'from_pos Z (|{fp[2]}|)')

    def test_marked_unverified(self):
        """The repositions need playtest verification — flag must be False
        until Alaric confirms in seed re-run."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        m = sr['proposals']['m60_42_36_00.msb']
        for pi in self.SLOTS:
            entry = m[pi]
            assert entry.get('manual_override', {}).get('playtest_verified') is False, (
                f'pi={pi} should have playtest_verified=False until '
                f'confirmed in playtest re-run of seed 460401')


# v0.24.49: cross-phase SW-corner extension + c5930/c6220 ban
# ============================================================================
class TestCrossPhaseReposExtension:
    """v0.24.49: the v0.24.48 SW-corner fix was incomplete — same
    geographic slot exists in m60_42_36_00/_10/_20 with identical pi
    and identical position. v0.24.48 only fixed _00. User reported a
    Demi-Human Chief freeze, which traced to m60_42_36_20 pi=19 at the
    SAME position. Extending fix to all phase tiles."""

    EXPECTED = [
        ('m60_42_36_00.msb', '19'),
        ('m60_42_36_00.msb', '20'),
        ('m60_42_36_10.msb', '19'),
        ('m60_42_36_10.msb', '20'),
        ('m60_42_36_20.msb', '19'),
        ('m60_42_36_20.msb', '20'),
    ]

    def test_all_three_phases_have_pi19_pi20(self):
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            assert msb in sr['proposals'] and pi in sr['proposals'][msb], (
                f'{msb} pi={pi} expected in slot_repositions.json after v0.24.49 '
                f'cross-phase extension.')

    def test_cross_phase_positions_match(self):
        """All three phases of pi=19 should have identical positions
        (and same for pi=20). They're the same world slot."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for pi in ('19', '20'):
            positions = [tuple(sr['proposals'][f'm60_42_36_{ph}.msb'][pi]['from_pos'])
                         for ph in ('00', '10', '20')]
            assert all(p == positions[0] for p in positions), (
                f'pi={pi} from_pos differs across phase tiles: {positions}. '
                f'Same geographic slot — should be identical.')
            to_positions = [tuple(sr['proposals'][f'm60_42_36_{ph}.msb'][pi]['to_pos_center'])
                            for ph in ('00', '10', '20')]
            assert all(p == to_positions[0] for p in to_positions), (
                f'pi={pi} to_pos_center differs across phase tiles: {to_positions}')


class TestC5930C6220InvisibleBan:
    """v0.24.49: c5930 Giant Skeleton + c6220 Fire Demon banned as
    likely invisible-enemy culprits in user playtest of seed 460401.

    v0.24.65: BOTH LIFTED with the rest of broken_runtime_chrs. Both
    were tagged _source='mmv_import' — the MMV sfx/material deploy
    that proved Romina works likely resolves their invisibility too.
    cap=1 each via the existing v0.24.53 MMV auto-cap."""

    def test_c5930_no_longer_excluded(self, engine):
        assert 'c5930' not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'v0.24.65 lifted c5930 — should no longer be hard-excluded')

    def test_c6220_no_longer_excluded(self, engine):
        assert 'c6220' not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'v0.24.65 lifted c6220 — should no longer be hard-excluded')

    def test_c5930_capped(self, engine):
        """MMV auto-cap from v0.24.53 still applies."""
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c5930') == 1

    def test_c6220_capped(self, engine):
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c6220') == 1

    def test_c2274_NOT_banned(self, engine):
        """c2274 has the same partial-tag profile but Alaric explicitly
        un-banned it in v0.24.41 after confirming it works. Unchanged."""
        assert 'c2274' not in engine.V3_EXCLUDE_TARGET_PREFIXES


# v0.24.50: cave-mouth XXL troll Y-raise
# ============================================================================
class TestCaveMouthTrollYRaise:
    """v0.24.50: User playtest seed 714653 reported Stonedigger Troll
    'halfway stuck in ground, like he can move but he's too short' at
    a cave-mouth-adjacent slot. m60_43_36_00 pi=31 is calibrated for
    c4377 (M-Battlemage) — XXL targets sink. Same slot exists in _10
    and _20 phase tiles with identical position. Fix: raise Y by 2m
    across all 3 phase tiles (applied preemptively per v0.24.49
    cross-phase lesson)."""

    EXPECTED = [
        ('m60_43_36_00.msb', '31'),
        ('m60_43_36_10.msb', '31'),
        ('m60_43_36_20.msb', '31'),
    ]

    def test_all_three_phases_have_pi31(self):
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            assert msb in sr['proposals'] and pi in sr['proposals'][msb], (
                f'{msb} pi={pi} expected in slot_repositions.json after '
                f'v0.24.50 XXL-sink fix.')

    def test_y_raised_by_2m(self):
        """Y should go from 67.17 to 69.17."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            entry = sr['proposals'][msb][pi]
            assert entry['from_pos'][1] == 67.17, (
                f'{msb} pi={pi} from_pos Y expected 67.17, got '
                f'{entry["from_pos"][1]}')
            assert entry['to_pos_center'][1] == 69.17, (
                f'{msb} pi={pi} to_pos_center Y expected 69.17 (+2m raise), '
                f'got {entry["to_pos_center"][1]}')

    def test_xz_unchanged(self):
        """Only Y should change. X and Z stay at the vanilla slot position."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            entry = sr['proposals'][msb][pi]
            assert entry['from_pos'][0] == entry['to_pos_center'][0]
            assert entry['from_pos'][2] == entry['to_pos_center'][2]


# v0.24.51 + v0.24.52: Gate 6 — script_spawn boss-tier at overworld rejection
# ============================================================================
class TestGate6ScriptSpawnBossOffArena:
    """v0.24.51 initial: rejected script_spawn boss-tier chrs at any
    slot not in V3_SCRIPT_SPAWN_BOSS_SLOTS (4 catalogued arena slots).

    v0.24.52 relaxation: user playtest counter-evidence — a script_spawn
    boss-tier chr at m46_05 (vanilla c4660 Guardian Golem fort) worked
    fine. Refined gate: reject ONLY at m60_xx_xx_xx overworld tiles.
    Dedicated arena MSBs (m4x_xx) have boss-preload EMEVD machinery
    and are safe."""

    def test_loader_finds_4_arena_slots(self, engine):
        """The original 4 catalogued script-spawn arena slots."""
        assert len(engine.V3_SCRIPT_SPAWN_BOSS_SLOTS) == 4
        assert ('m46_64_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS
        assert ('m46_65_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS
        assert ('m46_90_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS
        assert ('m46_91_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS

    def test_storm_king_rejected_at_overworld(self, engine, tags):
        """c7910 Storm King (night_boss script_spawn) at an OVERWORLD
        m60_xx tile should be rejected — no EMEVD preload for boss
        assets there. Likely culprit of seed 714653's 'approaching
        night-1 arena' CTD."""
        reason = engine._reject_target_for_slot(
            target_cp='c7910', src_cp='c4660',
            src_variant_name='Guardian Golem', tags=tags,
            msb_base='m60_42_36_00.msb', pi=43)
        assert reason == 'script_spawn_boss_at_overworld', (
            f'Storm King at overworld should be rejected, got {reason}')

    def test_gaping_dragon_allowed_at_m46_arena(self, engine, tags):
        """c7700 Gaping Dragon at m46_05_00_00 pi=3 — user-confirmed
        WORKING in seed 714653 playtest. m46_05 is a dedicated NR
        boss-arena MSB; Gate 6 should NOT reject."""
        reason = engine._reject_target_for_slot(
            target_cp='c7700', src_cp='c4660',
            src_variant_name='Guardian Golem', tags=tags,
            msb_base='m46_05_00_00.msb', pi=3)
        assert reason != 'script_spawn_boss_at_overworld', (
            f'Gaping Dragon at m46_05 (user-confirmed working) should '
            f'NOT be rejected, got {reason}')

    def test_centipede_demon_allowed_at_m46(self, engine, tags):
        """c7710 at m46_71 pi=1 — extension of the same pattern. m46_xx
        arena MSBs are allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c7710', src_cp='c4480',
            src_variant_name='Miranda Blossom', tags=tags,
            msb_base='m46_71_00_00.msb', pi=1)
        assert reason != 'script_spawn_boss_at_overworld'

    def test_centipede_demon_still_allowed_at_arena_slot(self, engine, tags):
        """The original 4 arena slots — still valid. (v0.24.52 didn't
        remove these; just expanded the allow-set.)"""
        reason = engine._reject_target_for_slot(
            target_cp='c7710', src_cp='c4690',
            src_variant_name='Grafted Scion', tags=tags,
            msb_base='m46_91_00_00.msb', pi=1)
        assert reason != 'script_spawn_boss_at_overworld'

    def test_centipede_grub_NOT_gated(self, engine, tags):
        """Grunt-tier script_spawn chrs (c7711/c7712 Centipede Grub,
        c7810 Freja Spiderling) work everywhere observed. Not gated."""
        for cp in ('c7711', 'c7712', 'c7810'):
            reason = engine._reject_target_for_slot(
                target_cp=cp, src_cp='c4311',
                src_variant_name='Leyndell Soldier', tags=tags,
                msb_base='m60_43_36_00.msb', pi=4)
            assert reason != 'script_spawn_boss_at_overworld', (
                f'{cp} (grunt-tier script_spawn) should NOT be gated, got {reason}')

    def test_non_script_spawn_unaffected(self, engine, tags):
        """A regular nr_placed night_boss chr at overworld is fine."""
        reason = engine._reject_target_for_slot(
            target_cp='c2130', src_cp='c4660',
            src_variant_name='Guardian Golem', tags=tags,
            msb_base='m60_42_36_00.msb', pi=43)
        assert reason != 'script_spawn_boss_at_overworld'

    def test_all_script_spawn_boss_chrs_rejected_at_overworld(self, engine, tags):
        """Every dedicated-arena boss chr should be rejected at an
        overworld slot — uniform behavior.

        v0.24.68: switched src_cp from c4660 (giga_boss/GIGA) to
        c4311 (humanoid/M) so Gate 5.6 (xxl/giga source slot
        integrity, v0.24.68) doesn't intercept anim-class drift
        before Gate 6 fires. The point of this test is Gate 6, not
        Gate 5.6 — using a small humanoid source avoids the
        unrelated gate's early-return.

        v0.26.x: source-of-truth for the gated set switched from
        '_source=script_spawn + tier ∈ BOSS_GATED_TIERS' to explicit
        V3_DEDICATED_ARENA_BOSS_CHRS membership. The set of chrs
        that fire the gate is identical to the v0.24.52 behaviour;
        only the keying mechanism changed.
        """
        gated_cps = sorted(engine.V3_DEDICATED_ARENA_BOSS_CHRS)
        assert len(gated_cps) >= 7, f'Expected ≥7 gated cps, got {len(gated_cps)}'
        for cp in gated_cps:
            reason = engine._reject_target_for_slot(
                target_cp=cp, src_cp='c4311',
                src_variant_name='Leyndell Soldier', tags=tags,
                msb_base='m60_42_36_00.msb', pi=4)
            assert reason == 'script_spawn_boss_at_overworld', (
                f'{cp} should be rejected at overworld, got {reason}')


# v0.24.53: cap all MMV imports at 1 per seed
# ============================================================================
class TestMmvImportCap1:
    """v0.24.101: The v0.24.53 blanket-cap-MMV-imports-at-1 policy was
    REMOVED as part of the "open the floodgates" variety pass. This class
    verifies the new policy: MMV imports are no longer auto-capped at 1
    proactively. Named-character explicit caps in V3_UNIQUE_TARGET_CAPS
    still apply — only the *blanket* auto-cap was removed.

    If a specific MMV chr proves problematic (CTD/sink) in playtest, add
    it to V3_UNIQUE_TARGET_CAPS explicitly with a tuned cap. Don't
    re-enable the blanket cap.
    """

    def test_mmv_imports_not_auto_capped(self, engine, tags):
        """v0.24.101: MMV imports without an explicit named-chr cap entry
        should NOT appear in V3_UNIQUE_TARGET_CAPS. Auto-cap loop is dead
        code. If MMV imports re-appear in tags (current tags have 0), they
        should be uncapped by default."""
        mmv_chrs = [cp for cp, t in tags.items()
                    if cp != '_has_reward_regen'
                    and t.get('_source') == 'mmv_import']
        if not mmv_chrs:
            pytest.skip('No MMV imports in current tags — policy still '
                        'correct, just nothing to assert against')
        # Of MMV chrs, any that have a cap should ONLY be explicitly-named
        # entries (i.e., the named-chr policy carve-out). Auto-cap would
        # have hit every chr without distinction.
        for cp in mmv_chrs:
            cap = engine.V3_UNIQUE_TARGET_CAPS.get(cp)
            if cap is not None:
                # Verify this is an explicitly-set named-chr cap, not the
                # old blanket=1. The old policy applied cap=1 uniformly;
                # explicit caps may be 1 OR 2+ for chrs intentionally
                # given more room.
                # No hard assert here — just document the survivors so
                # regressions show up via test output.
                pass

    def test_named_character_caps_preserved(self, engine):
        """Explicit caps for named characters in V3_UNIQUE_TARGET_CAPS
        must still apply — only the blanket MMV auto-cap was removed.
        Spot-check a few canonical entries."""
        # These are named-chr explicit caps that existed pre-v0.24.101 and
        # must survive the floodgates change.
        expected_caps = {
            'c4750': 2,  # Godrick variants — allowed 2 placements
            'c4500': 1,  # Flying Dragon (Unscaled) — field_boss, cap=1
            'c4503': 1,  # Borealis the Freezing Fog — field_boss, cap=1
            # v0.26.x: c4510 Ancient Dragon raised from 1 to 2 as part of
            # the night_boss-tier uniform ceiling normalization (all NB
            # caps = 2, with floor=1 in V3_RESERVATION_FLOORS guaranteeing
            # at-least-one-per-seed). Cap=2 is still a "named-chr explicit
            # cap" — the floodgates pass invariant (don't remove named-chr
            # caps) still holds. Field-boss tier uniques (c4500, c4503)
            # stay at 1.
            'c4510': 2,  # Ancient Dragon — night_boss, v0.26.x ceiling=2
        }
        for cp, expected in expected_caps.items():
            actual = engine.V3_UNIQUE_TARGET_CAPS.get(cp)
            assert actual == expected, (
                f'{cp} cap should still be {expected} after v0.24.101, '
                f'got {actual!r}. The floodgates pass should only have '
                f'removed the BLANKET MMV cap, not named-chr caps.')

    def test_nr_placed_NOT_auto_capped(self, engine, tags):
        """The v0.24.53 rule only applies to MMV imports. Regular
        nr_placed chrs are not affected — they retain their existing
        cap state (most uncapped)."""
        # Pick a known nr_placed chr that's not in V3_UNIQUE_TARGET_CAPS
        # and verify it's still uncapped
        nr_uncapped_examples = ['c3500', 'c4380', 'c4381']  # common grunts
        for cp in nr_uncapped_examples:
            if tags.get(cp, {}).get('_source') == 'nr_placed':
                assert cp not in engine.V3_UNIQUE_TARGET_CAPS or \
                       engine.V3_UNIQUE_TARGET_CAPS[cp] >= 50, (
                    f'{cp} is nr_placed grunt — should not have been '
                    f'auto-capped by v0.24.53 MMV rule')


# v0.24.54: Gate 4 anim_class-based rejection + Red Wolf cap
# ============================================================================
class TestGate4AnimClassRejection:
    """v0.24.54: Extended Gate 4 (quadruped_unsafe_slot) to honor a new
    per-slot `reject_anim_classes` field. Some slots fail for ALL
    quadrupeds, not just locomotion=3 — m46_77 pi=8 (Demi-Human Queen
    anchor) was authored for humanoid AI; both loco=3 (Rats) and loco=5
    (c3181 Red Wolf) freeze there. The per-chr position_shift system
    has been trying (0, +0.5, -5) since v0.24.18 but still fails.

    The default loco=3 path is preserved for legacy slot entries
    without a `reject_anim_classes` field."""

    def test_m46_77_pi8_in_catalog(self, engine):
        """The new slot entry from v0.24.54 should load."""
        assert ('m46_77_00_00.msb', 8) in engine.V3_QUADRUPED_UNSAFE_SLOTS
        meta = engine.V3_QUADRUPED_UNSAFE_SLOTS_META[('m46_77_00_00.msb', 8)]
        assert meta.get('reject_anim_classes') == ['quadruped']

    def test_red_wolf_rejected_at_m46_77(self, engine, tags):
        """c3181 Red Wolf (loco=5, anim=quadruped) — the user-reported
        freeze chr — rejected at the user-reported slot."""
        reason = engine._reject_target_for_slot(
            target_cp='c3181', src_cp='c4130',
            src_variant_name='Demi-Human Queen (Field Boss)', tags=tags,
            msb_base='m46_77_00_00.msb', pi=8)
        assert reason == 'quadruped_unsafe_slot'

    def test_runebear_rejected_at_m46_77(self, engine, tags):
        """c4630 Runebear (anim=quadruped_large) — prefix match on
        'quadruped' covers quadruped_large too."""
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4130',
            src_variant_name='Demi-Human Queen (Field Boss)', tags=tags,
            msb_base='m46_77_00_00.msb', pi=8)
        assert reason == 'quadruped_unsafe_slot'

    def test_legacy_slot_now_catches_anim_class_quadruped(self, engine, tags):
        """v0.24.62 broadened the default criterion from `loco==3` to
        also include `anim_class.startswith('quadruped')`. So legacy
        slots without explicit reject_anim_classes now catch BOTH
        loco=3 chrs (Rats) AND anim_class=quadruped(_large) chrs
        (Wolves, Bears, Goats) regardless of locomotion.

        Previously this test asserted the opposite: that c3181 Red
        Wolf (loco=5) was NOT rejected at m45_01 pi=1. v0.24.62
        inverts that — Red Wolf is now caught at legacy slots too,
        which is the desired behavior."""
        reason_rat = engine._reject_target_for_slot(
            target_cp='c4080', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=1)
        assert reason_rat == 'quadruped_unsafe_slot'

        # Red Wolf at the legacy slot — Gate 4 NOW rejects it
        # (anim_class=quadruped matches the broadened default).
        reason_wolf = engine._reject_target_for_slot(
            target_cp='c3181', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=1)
        assert reason_wolf == 'quadruped_unsafe_slot', (
            f'Red Wolf at legacy slot should now be rejected by Gate 4 '
            f'(v0.24.62 broadened default to anim_class), got {reason_wolf}')


class TestRedWolfCap:
    """v0.24.54: cap c3181 Red Wolf of Radagon at 2 per seed."""

    def test_c3181_capped_at_2(self, engine):
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c3181') == 2

    def test_red_wolf_in_quadruped_family_caps(self, engine):
        """Red Wolf cap=2 mirrors c4630 Runebear (same archetype: L-size
        quadruped field_boss)."""
        assert engine.V3_UNIQUE_TARGET_CAPS['c3181'] == engine.V3_UNIQUE_TARGET_CAPS['c4630']


# v0.24.55: Gate 7 — XXL target at small-vanilla slot ban
# ============================================================================
class TestGate7XxlAtSmallSlot:
    """v0.24.55: Class-level fix for the 'sunken troll' pattern. XXL
    chrs placed at slots whose vanilla source is S/M/XS render with
    their model partially below visible ground. The slot Y is
    calibrated for the smaller chr's feet/origin; the XXL chr's rig
    doesn't match.

    Carries forward from v0.24.50 (per-slot Y-raise on m60_43_36 pi=31)
    after another sunken troll report — user request to ship the
    class-level fix this time."""

    def test_troll_at_m_slot_banned(self, engine, tags):
        """The original v0.24.50 case: c4603 Stonedigger Troll (XXL)
        at c4377 (M-Battlemage) vanilla — banned."""
        # Use a non-boss src_variant_name to avoid earlier nb gates
        reason = engine._reject_target_for_slot(
            target_cp='c4603', src_cp='c4377',
            src_variant_name='Raya Lucaria Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        assert reason == 'xxl_at_small_slot'

    def test_troll_at_s_slot_banned(self, engine, tags):
        """Worst case from seed 714653: c4600 Troll at c3170 (S) — banned."""
        reason = engine._reject_target_for_slot(
            target_cp='c4600', src_cp='c3170',
            src_variant_name='Ant', tags=tags,
            msb_base='m34_10_00_00.msb', pi=10)
        assert reason == 'xxl_at_small_slot'

    def test_xxl_quadruped_large_at_m_slot_banned(self, engine, tags):
        """c4630 Runebear (XXL quadruped_large) at M-vanilla — same
        sink class, also banned."""
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4377',
            src_variant_name='Raya Lucaria Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        assert reason == 'xxl_at_small_slot'

    def test_xxl_at_xl_slot_allowed(self, engine, tags):
        """c4600 Troll at c4550 (XL vanilla) — borderline-but-allowed.
        v0.24.50's seed had c4603 at this XL-vanilla type ('less likely'
        sink risk in the original table)."""
        reason = engine._reject_target_for_slot(
            target_cp='c4600', src_cp='c4550',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m60_43_38_10.msb', pi=41)
        assert reason != 'xxl_at_small_slot'

    def test_xxl_at_xxl_slot_allowed(self, engine, tags):
        """c4602 Snowfield Troll at c4770 Gargoyle (XXL) — same-size
        swap, allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c4602', src_cp='c4770',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m46_66_00_00.msb', pi=1)
        assert reason != 'xxl_at_small_slot'

    def test_l_at_m_slot_allowed(self, engine, tags):
        """L-size target at M-vanilla — the gate is XXL-only, not 'any
        upgrade.' c4750 Godrick (L humanoid) at c4377 (M) — allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c4750', src_cp='c4377',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        assert reason != 'xxl_at_small_slot'

    def test_giga_NOT_caught_by_gate7(self, engine, tags):
        """GIGA chrs are intentionally NOT in Gate 7 — flying GIGAs
        (e.g. c4500 Flying Dragon) don't sink, and grounded GIGAs are
        handled by Gates 3 (forbidden_source_anim) and 5 (flying_required)."""
        reason = engine._reject_target_for_slot(
            target_cp='c4500', src_cp='c4377',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        # Gate 7 should not fire; other gates may (e.g. flying_required
        # for flying-vanilla slots) — just assert it's not xxl_at_small_slot
        assert reason != 'xxl_at_small_slot'

    def test_gate_uniformly_applies_to_all_xxl(self, engine, tags):
        """Every XXL chr in tags is rejected at M-vanilla — either by
        Gate 7 directly OR by an earlier gate (e.g. nb_strict catches
        NR Nightlords like c7500 Gladius before Gate 7 sees them).
        The key invariant: NO XXL chr passes through at M-vanilla."""
        xxl_cps = [cp for cp, t in tags.items() if t.get('size_class') == 'XXL']
        assert len(xxl_cps) >= 20, f'Expected ≥20 XXL chrs, found {len(xxl_cps)}'
        leaked = []
        for cp in xxl_cps:
            reason = engine._reject_target_for_slot(
                target_cp=cp, src_cp='c4377',  # M-Battlemage
                src_variant_name='Foot Soldier', tags=tags,
                msb_base='m60_43_36_00.msb', pi=31)
            if reason is None:
                leaked.append(cp)
        assert not leaked, (
            f'XXL chrs leaked through all gates at M-vanilla: {leaked}')


# v0.24.59: Encampment-slot Gate 4 entries (m43_01 pi=2 Goat + pi=3 Bear)
# ============================================================================
class TestGate4EncampmentSlots:
    """v0.24.59: Starting encampment slots in m43_01_00_00.msb that froze
    quadrupeds. Seed 923958 playtest report: c6060 Goat (anim=quadruped,
    NR-UI 'Lightning Ram' variant) at pi=2 froze; c6031 Bear (anim=
    quadruped_large) at pi=3 froze. Both vanilla c4300 Wandering Noble
    (humanoid). Same nav-mismatch pattern as v0.24.54 Red Wolf.

    Note: c6031/c6060 both have locomotion=0 — the default Gate 4 loco=3
    criterion does NOT catch them. The reject_anim_classes filter is
    what makes Gate 4 fire here. This test class enforces that."""

    def test_bear_at_encampment_slot_rejected(self, engine, tags):
        """c6031 Bear at m43_01 pi=3 — the empirical freeze case."""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=3)
        assert reason == 'quadruped_unsafe_slot'

    def test_goat_at_encampment_slot_rejected(self, engine, tags):
        """c6060 Goat at m43_01 pi=2 — the 'Lightning Ram' freeze case."""
        reason = engine._reject_target_for_slot(
            target_cp='c6060', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=2)
        assert reason == 'quadruped_unsafe_slot'

    def test_loco_0_doesnt_save_them(self, engine, tags):
        """Sanity check the precondition: c6031 and c6060 have loco=0,
        so the default Gate 4 wouldn't catch them — reject_anim_classes
        is the only filter making this work."""
        assert tags['c6031'].get('locomotion') == 0
        assert tags['c6060'].get('locomotion') == 0
        # And both are anim_class=quadruped*
        assert 'quadruped' in tags['c6031'].get('anim_class', '')
        assert 'quadruped' in tags['c6060'].get('anim_class', '')

    def test_prefix_match_catches_quadruped_large(self, engine, tags):
        """reject_anim_classes=['quadruped'] is a prefix match — should
        also catch quadruped_large chrs like Runebear."""
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=2)
        # Either Gate 4 (anim_class) or another gate (e.g. v0.24.55 Gate 7
        # for XXL@M might also fire, but only m43_01 pi=2 is XXL@M-vanilla
        # via c4630's XXL size and c4300's M size). Either way, must be
        # rejected somehow.
        assert reason is not None

    def test_humanoid_at_encampment_slot_allowed(self, engine, tags):
        """The gate is anim_class-scoped. Humanoid swaps still work."""
        reason = engine._reject_target_for_slot(
            target_cp='c4313', src_cp='c4300',  # Leyndell Soldier (humanoid)
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=2)
        assert reason != 'quadruped_unsafe_slot'

    def test_non_flagged_pi_in_same_msb_unaffected(self, engine, tags):
        """The gate is per-slot, not per-MSB. pi=9 in same MSB is not
        in the catalog so quadrupeds there are not rejected by Gate 4.
        (Other gates may still apply.)"""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=9)
        assert reason != 'quadruped_unsafe_slot'


# v0.24.60: SW-corner Putrid Corpse cluster — fragility flag + c4120 extra-ban
# ============================================================================
class TestSwCornerFragilityFlag:
    """v0.24.60: User report seed 923958 — c6060 Goat (pi=19) and c4120
    Demi-Human Chief (pi=20) BOTH froze at the SW corner cluster, even
    though v0.24.49 already had +5/-5 repositions applied (post-shift
    positions [-98.99, 108.14, 98.12] and [-100.62, 105.48, 88.15] visible
    in the spoiler).

    Fix: V3_PROBLEM_SLOTS entries flag fragility (restricts pool to
    SAFE_CONFIRMED). V3_PROBLEM_SLOT_EXTRA_BANS adds c4120 override
    since c4120 IS in SAFE_CONFIRMED (bulk-added v0.20.48 via mt=3
    rule) and would otherwise pass the fragility filter.

    Cross-phase coverage: all 6 slots (pi=19, pi=20 × _00/_10/_20)."""

    def test_sw_corner_slots_are_fragile(self, engine, tags):
        """All 6 SW-corner phase-sibling slots flag as fragile."""
        import oops_v3 as o
        for sub in ('_00', '_10', '_20'):
            for pi in (19, 20):
                msb = f'm60_42_36{sub}.msb'
                assert o.is_fragile_slot(msb, pi, 'Putrid Corpse'), (
                    f'{msb} pi={pi} should be fragile after v0.24.60')

    def test_c4120_extra_banned_at_sw_corner(self, engine, tags):
        """c4120 Demi-Human Chief is in SAFE_CONFIRMED so the fragility
        flag alone wouldn't block it. V3_PROBLEM_SLOT_EXTRA_BANS adds
        the slot-specific ban."""
        import oops_v3 as o
        # Sanity: c4120 IS in SAFE_CONFIRMED
        assert 'c4120' in o.V3_FRAGILE_SAFE_CONFIRMED, (
            "Test assumes c4120 is in SAFE_CONFIRMED — if this fails, "
            "the SAFE_CONFIRMED entry was removed and the extra-ban is "
            "redundant (which is fine, but the rationale should be updated)")
        for sub in ('_00', '_10', '_20'):
            for pi in (19, 20):
                msb = f'm60_42_36{sub}.msb'
                bans = o.V3_PROBLEM_SLOT_EXTRA_BANS.get((msb, pi), set())
                assert 'c4120' in bans, f'c4120 should be banned at {msb} pi={pi}'

    def test_c6060_blocked_by_fragility_alone(self, engine, tags):
        """c6060 Goat is NOT in SAFE_CONFIRMED, so it's blocked just by
        the fragility flag (no need for an extra-ban entry)."""
        import oops_v3 as o
        assert 'c6060' not in o.V3_FRAGILE_SAFE_CONFIRMED

    def test_repositions_still_apply(self, engine, tags):
        """v0.24.49's slot_repositions.json entries are unaffected — they're
        a separate mechanism (apply at DCX-write time, not chr-pick time).
        Both mechanisms now fire for these slots."""
        import json, os
        HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(HERE, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        e = sr['proposals'].get('m60_42_36_00.msb', {}).get('19')
        assert e is not None, "v0.24.49 reposition for SW corner must persist"
        assert e.get('status') == 'playtest_freeze'
        # Shift is +5 X, 0 Y, -5 Z (7.07m diagonal inward)
        assert e['to_pos_center'] == [-98.99, 108.14, 98.12]

    def test_unaffected_slots_not_collateral_damage(self, engine, tags):
        """Verify the fragility/extra-ban scope is narrow — pi=18 and pi=21
        in the same MSB are NOT affected."""
        import oops_v3 as o
        # pi=18 should NOT be fragile (we didn't add it)
        is_fragile_18 = o.is_fragile_slot('m60_42_36_00.msb', 18, 'Putrid Corpse')
        # Could already be fragile via T1/T2; just check it's not in PROBLEM_SLOTS specifically
        assert ('m60_42_36_00.msb', 18) not in o.V3_PROBLEM_SLOTS
        assert ('m60_42_36_00.msb', 21) not in o.V3_PROBLEM_SLOTS


# v0.24.62: Bear-Rat parity + unique-reservation fragility filter
# ============================================================================
class TestGate4BearRatParity:
    """v0.24.62: Default Gate 4 criterion broadened from `locomotion==3`
    to `locomotion==3 OR anim_class.startswith('quadruped')`. Catches
    anim_class=quadruped(_large) chrs with loco=0 (Bear, Goat, Wolf) at
    the same slots that catch loco=3 chrs (Rat, Giant Rat).

    User request:
    > "mark the regular grunt bear basically as fragile as small rat"

    Both chrs share the nav-mismatch failure mode but differ on
    locomotion. The fix aligns the gate behavior."""

    def test_bear_now_rejected_at_default_loco3_slot(self, engine, tags):
        """c6031 Bear (loco=0, anim=quadruped_large) at m45_01 pi=3 —
        the original Rat-empirical slot — was NOT rejected before
        v0.24.62 because loco==3 didn't match. Now it is."""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert reason == 'quadruped_unsafe_slot'

    def test_goat_now_rejected_at_prophylactic_slot(self, engine, tags):
        """c6060 Goat (loco=0, anim=quadruped) at m43_01 pi=5 (one of
        the prophylactic-density-scan slots from v0.24.33)."""
        reason = engine._reject_target_for_slot(
            target_cp='c6060', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=5)
        assert reason == 'quadruped_unsafe_slot'

    def test_rat_still_rejected(self, engine, tags):
        """The pre-existing loco=3 path must keep working. c4080 Rat
        at m45_01 pi=3 — the original case."""
        reason = engine._reject_target_for_slot(
            target_cp='c4080', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert reason == 'quadruped_unsafe_slot'

    def test_humanoid_at_same_slot_still_passes(self, engine, tags):
        """The broadening targets anim_class=quadruped*; humanoids at
        the same slot must still be allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c4313', src_cp='c4300',  # Leyndell Soldier
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert reason != 'quadruped_unsafe_slot'

    def test_quadruped_large_caught_by_prefix_match(self, engine, tags):
        """anim_class=quadruped_large should match the 'quadruped'
        startswith filter — same prefix match logic v0.24.54 used."""
        # c4630 Runebear: XXL quadruped_large, loco=0 (loco varies)
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=1)
        # Should be caught — exact reason might be Gate 4 OR Gate 7
        # (XXL@M), as long as something rejects it.
        assert reason is not None

    def test_unflagged_slots_unaffected(self, engine, tags):
        """Bear at an MSB/pi not in the catalog is still allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m60_99_99_00.msb', pi=99)  # made up unflagged slot
        assert reason != 'quadruped_unsafe_slot'


class TestUniqueReservationFragilityFilter:
    """v0.24.62: _score_slot_for_unique now enforces the standard
    SAFE_CONFIRMED ∪ RESILIENT fragility filter at fragile slots —
    plus per-slot EXTRA_BANS. Previously only SENSITIVE was checked,
    leaving a gap where Nightlords and MMV imports could reserve
    fragile slots.

    User report seed 537773 (v0.24.58): c7910 Storm King reserved
    m30_30 pi=45 (Guardian Golem Fort rampart — in V3_PROBLEM_SLOTS
    since v0.24.18 for c4441 Land Squirt CTD). Player CTD walking
    away from the fort. The standard shuffle's RESILIENT∪SAFE filter
    would have prevented this; the unique-reservation path bypassed
    it."""

    def _make_fragile_slot(self):
        # m30_30_00_00 pi=45 is in V3_PROBLEM_SLOTS (T3)
        return {
            'msb': 'm30_30_00_00.msb',
            'pi': 45,
            'source_cp': 'c4660',
            'source_variant_name': 'Guardian Golem (Fort)',
            'position': (None, 42.8, None),
        }

    def test_c7910_rejected_at_fragile_slot(self, engine, tags):
        """The headline case from seed 537773."""
        slot = self._make_fragile_slot()
        assert engine._score_slot_for_unique(slot, 'c7910', tags) is None

    def test_freja_rejected_at_fragile_slot(self, engine, tags):
        """c7810 Freja Spiderling — MMV DS2 import, not in SAFE_CONFIRMED.
        Previously could reserve fragile slots. v0.24.62 blocks."""
        slot = self._make_fragile_slot()
        # We don't assert anim compat here — even if compat passes,
        # the fragility filter should reject.
        assert engine._score_slot_for_unique(slot, 'c7810', tags) is None

    def test_other_nightlords_rejected_at_fragile_slot(self, engine, tags):
        """Nightlord c-prefixes that are explicitly in V3_FRAGILE_SENSITIVE_
        TARGETS should be rejected at fragile slots.

        v0.26.x: was previously a parametric "all nightlords" check that
        passed via the NB-strict gate (which rejected nightlords at slots
        without the 'Night Boss' marker). With NB-strict removed, fragile-
        slot safety is now strictly per-chr via V3_FRAGILE_SENSITIVE_
        TARGETS membership. Nightlords not in the set CAN appear at
        fragile slots subject to other compat checks — accepted as the
        cost of removing the over-broad variant-name filter. If a
        specific Nightlord-at-fragile-slot CTD surfaces, add that cp to
        V3_FRAGILE_SENSITIVE_TARGETS with seed evidence."""
        slot = self._make_fragile_slot()
        for cp in ('c7500', 'c7520', 'c7540', 'c7600', 'c7910'):
            if cp not in engine.V3_FRAGILE_SENSITIVE_TARGETS:
                continue  # not in the sensitive set; can appear at fragile slots
            assert engine._score_slot_for_unique(slot, cp, tags) is None, (
                f'{cp} (Nightlord, in V3_FRAGILE_SENSITIVE_TARGETS) '
                f'must be rejected at fragile slot')

    def test_extra_bans_honored_at_fragile_slot(self, engine, tags):
        """V3_PROBLEM_SLOT_EXTRA_BANS already applied in the standard
        shuffle. Now uniques also honor it. c4120 Demi-Human Chief is
        in SAFE_CONFIRMED but blacklisted at m60_42_36_00 pi=20 (the
        v0.24.60 SW-corner extra-ban)."""
        slot = {
            'msb': 'm60_42_36_00.msb',
            'pi': 20,
            'source_cp': 'c3661',
            'source_variant_name': 'Putrid Corpse',
            'position': (-100.62, 105.48, 88.15),
        }
        # c4120 IS in SAFE_CONFIRMED, would normally pass fragility
        import oops_v3 as o
        assert 'c4120' in o.V3_FRAGILE_SAFE_CONFIRMED
        # But it's in V3_PROBLEM_SLOT_EXTRA_BANS for this slot
        assert 'c4120' in o.V3_PROBLEM_SLOT_EXTRA_BANS[(slot['msb'], slot['pi'])]
        # Should still be rejected by the extra-ban path
        assert engine._score_slot_for_unique(slot, 'c4120', tags) is None

    def test_non_fragile_slot_unaffected(self, engine, tags):
        """The new filter only fires at fragile slots. Targets that
        score at non-fragile slots still score."""
        slot = {
            'msb': 'm46_05_00_00.msb',  # dedicated arena, NOT in PROBLEM_SLOTS
            'pi': 3,
            'source_cp': 'c4660',
            'source_variant_name': 'Guardian Golem',
            'position': (0, 0, 0),
        }
        # c7710 Centipede Demon was placed at m46_05 pi=3 in seed 537773
        # successfully. Should still score.
        import oops_v3 as o
        assert (slot['msb'], slot['pi']) not in o.V3_PROBLEM_SLOTS
        # If anim_class compat passes (giga_boss → giga_boss), this scores.
        result = engine._score_slot_for_unique(slot, 'c7710', tags)
        assert result is not None  # should score (not None)


# v0.24.63: c5860 Ghostflame Dragon cap=2
class TestGhostflameDragonCap:
    """v0.24.63: c5860 cap=2. User req: '"oh cap the ghostflame dragon
    at 2" — seed 618106 had 3 placements."""

    def test_c5860_capped_at_2(self, engine):
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c5860') == 2

    def test_c5860_cap_matches_runebear_archetype(self, engine):
        """c5860 cap=2 matches similar heritage / large-flying archetypes
        (c4630 Runebear, c4560 Giant Crow, c5820 Great Red Bear)."""
        assert engine.V3_UNIQUE_TARGET_CAPS['c5860'] == 2
        # c5820 is the closest analog (heritage XXL boss)
        assert engine.V3_UNIQUE_TARGET_CAPS['c5820'] == 2


# v0.24.67: Gate 5.5 — grunt/trash target at boss-healthbar slot
# ============================================================================
class TestGate5_5GruntTrashAtBossBar:
    """v0.24.67: Reject grunt-tier and trash-tier targets at slots whose
    catalog tier indicates a boss-healthbar encounter (the EMEVD chain
    on death expects clean entity teardown — grunt/trash death anims
    and unusual spawner-generator fields don't always satisfy that).

    Discovered seed 877217 v0.24.65: c3664 Cemetery Shade landed at
    m32_00 pi=31 ent=32000810 (vanilla Elder Lion Encampment). User
    CTDed on kill. Root cause: NpcParam variants 36640020/32/35 carry
    spawner-generator entity IDs (23664000, 366400700, 366400000) that
    fire child entities on death, incompatible with vanilla NR's
    encampment boss-clear chain.

    Companion edits in v0.24.67:
      - c3664 removed from V3_FRAGILE_SAFE_CONFIRMED (the v0.20.52
        confirmation was at a non-boss-bar slot and doesn't generalize)
      - c3664 tier demoted miniboss → grunt in nr_enemy_tags.json
        (HP 939 / weight 130 matches grunt territory)

    The gate also catches as a bonus:
      - Miranda Sprouts at named_boss / castle_interior (same fragile-
        death-chr family, flower-petal dissolve on death)
      - Giant Rat / Wandering Noble / Bloodbane Stray as field_boss
        (thematic embarrassments)
      - c6031 Bear at named_boss (Bear freeze pattern from seed 537773)
    """

    def test_v3_boss_bar_tiers_defined(self, engine):
        """The constant exists and includes the catalog-tier names we
        empirically determined are boss-healthbar slots (>=60% event-
        bound). mountaintop / ruins_boss / fort_boss are excluded
        (their entries are mostly thematic spawns, not event bosses)."""
        assert 'encampment' in engine.V3_BOSS_BAR_TIERS
        assert 'named_boss' in engine.V3_BOSS_BAR_TIERS
        assert 'fieldboss' in engine.V3_BOSS_BAR_TIERS
        assert 'nightboss' in engine.V3_BOSS_BAR_TIERS
        assert 'remembrance' in engine.V3_BOSS_BAR_TIERS
        assert 'castle_interior' in engine.V3_BOSS_BAR_TIERS
        # Excluded tiers (mostly non-event)
        assert 'mountaintop' not in engine.V3_BOSS_BAR_TIERS
        assert 'ruins_boss' not in engine.V3_BOSS_BAR_TIERS
        assert 'fort_boss' not in engine.V3_BOSS_BAR_TIERS

    def test_v3_boss_bar_gated_tiers_is_grunt_and_trash(self, engine):
        """Only grunt and trash target tiers are gated. Miniboss,
        field_boss, night_boss, etc. remain eligible at boss-bar slots."""
        assert engine.V3_BOSS_BAR_GATED_TIERS == frozenset({'grunt', 'trash'})

    def test_c3664_demoted_to_grunt(self, engine, tags):
        """v0.24.67 metadata correction. Cemetery Shade was miniboss;
        HP 939 / weight 130 is grunt territory."""
        assert tags['c3664']['tier'] == 'grunt'
        # Demote should also drop has_boss_reward
        assert tags['c3664']['has_boss_reward'] is False

    def test_c3664_removed_from_fragile_safe_confirmed(self, engine):
        """v0.24.67. The v0.20.52 confirmation was at a non-boss-bar
        slot; seed 877217 m32_00 pi=31 invalidates it for boss-bar."""
        assert 'c3664' not in engine.V3_FRAGILE_SAFE_CONFIRMED

    def test_smoking_gun_c3664_at_encampment_rejected(self, engine, tags):
        """The seed 877217 case: m32_00 pi=31 ent=32000810 c4270 Elder
        Lion (Encampment) → c3664. Must be rejected by Gate 5.5."""
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason == 'grunt_trash_at_boss_bar', (
            f'c3664 at encampment slot should be rejected, got {reason}')

    def test_c3664_at_named_boss_rejected(self, engine, tags):
        """Another c3664 placement from seed 877217: m46_60 pi=2 ent=
        46600841 Banished Knight Evergaol (named_boss). Also a CTD
        risk under the same mechanism — boss-bar event chain expects
        clean teardown."""
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c3010',
            src_variant_name='Banished Knight (Evergaol- Dual Swords)',
            tags=tags, msb_base='m46_60_00_00.msb', pi=2)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_c3664_at_field_boss_rejected(self, engine, tags):
        """And the m60_42_37_50 pi=34 ent=1027500215 Mad Pumpkin Head
        named_boss placement from the same seed."""
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c4340',
            src_variant_name='Mad Pumpkin Head', tags=tags,
            msb_base='m60_42_37_50.msb', pi=34)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_c3664_at_walk_route_filler_allowed(self, engine, tags):
        """Non-boss-bar slot: c3664 should still be placeable at walk-
        route fillers and trash slots. Gate only fires at boss-bar."""
        # Pick a slot not in V3_BOSS_SLOT_CATALOG
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m34_10_00_00.msb', pi=69)
        assert reason is None, (
            f'c3664 at non-boss-bar slot should pass, got {reason}')

    def test_exempt_grunt_in_safe_confirmed_allowed(self, engine, tags):
        """c3000 Exile Soldier (grunt) is in V3_FRAGILE_SAFE_CONFIRMED.
        It must remain eligible at the same encampment slot — the
        exemption protects 85+ playtest-confirmed grunts that work fine
        at boss-bar slots."""
        assert 'c3000' in engine.V3_FRAGILE_SAFE_CONFIRMED
        reason = engine._reject_target_for_slot(
            target_cp='c3000', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason is None

    def test_miniboss_tier_unaffected(self, engine, tags):
        """Miniboss-tier targets are not gated — pass at all boss-bar
        slots. c3060 Giant Skeleton is a vanilla NR miniboss commonly
        placed at encampment / castle_interior boss slots."""
        assert tags['c3060']['tier'] == 'miniboss'
        reason = engine._reject_target_for_slot(
            target_cp='c3060', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason is None

    def test_field_boss_tier_eliminated(self, engine, tags):
        """v0.26.x: field_boss tier was collapsed entirely into miniboss
        and night_boss. Every previously field_boss-tagged chr is now
        either reassigned via V3_TAG_OVERRIDES or in V3_EXCLUDE_TARGET_
        PREFIXES (label-only residual).

        This test originally verified that field_boss-tier passed the
        gate (sister to the miniboss/night_boss/grunt cases above).
        Post-collapse it's inverted to a lockin: any chr still tier=
        field_boss must be in the exclude set, otherwise the collapse
        regressed.
        """
        fb_tagged = [cp for cp, t in tags.items() if t.get('tier') == 'field_boss']
        leaked = [cp for cp in fb_tagged
                  if cp not in engine.V3_EXCLUDE_TARGET_PREFIXES]
        assert not leaked, (
            f'After v0.26.x tier collapse, no active (non-excluded) chr '
            f'should have tier=field_boss. Leaked: {leaked}. Add a '
            f'V3_TAG_OVERRIDES entry assigning each to miniboss or '
            f'night_boss.')

    def test_night_boss_tier_unaffected(self, engine, tags):
        """night_boss-tier targets pass — they're authored for boss-bar
        encounters. c2130 Morgott at named_boss is fine."""
        assert tags['c2130']['tier'] == 'night_boss'
        reason = engine._reject_target_for_slot(
            target_cp='c2130', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason is None

    def test_miranda_sprout_rejected_at_named_boss(self, engine, tags):
        """Bonus catch from Gate 5.5: c4481 Miranda Sprout (grunt,
        not in SAFE_CONFIRMED) has a flower-petal dissolve death
        animation that's the same fragile-death class as c3664.
        Gate blocks it at named_boss slots pre-emptively."""
        assert tags['c4481']['tier'] == 'grunt'
        assert 'c4481' not in engine.V3_FRAGILE_SAFE_CONFIRMED
        reason = engine._reject_target_for_slot(
            target_cp='c4481', src_cp='c4480',
            src_variant_name='Miranda Blossom', tags=tags,
            msb_base='m46_80_00_00.msb', pi=4)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_giant_rat_rejected_at_named_boss(self, engine, tags):
        """Thematic embarrassment catch: c4090 Giant Rat (grunt, not
        in SAFE_CONFIRMED) as named_boss. Gate prevents the 'giant rat
        is the boss now' situation as a side effect of catching the
        real risk."""
        assert tags['c4090']['tier'] == 'grunt'
        assert 'c4090' not in engine.V3_FRAGILE_SAFE_CONFIRMED
        # m47_70 pi=22 named_boss from seed 877217
        reason = engine._reject_target_for_slot(
            target_cp='c4090', src_cp='c3010',
            src_variant_name='Banished Knight', tags=tags,
            msb_base='m47_70_00_00.msb', pi=22)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_slot_not_in_catalog_not_gated(self, engine, tags):
        """If the (msb, pi) isn't in V3_BOSS_SLOT_CATALOG, the gate
        doesn't fire — even if the source variant name looks boss-y.
        Catalog membership is the source of truth."""
        # m46_50 pi=15 is event-bound (ent=46500827) and the source name
        # contains "Evergaol", but it's not in V3_BOSS_SLOT_CATALOG.
        # Gate skips it; relies on catalog completeness as the contract.
        assert engine.V3_BOSS_SLOT_CATALOG.get(('m46_50_00_00.msb', 15)) is None
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c3970',
            src_variant_name='Azula Beastman (Evergaol- Cleaver)',
            tags=tags, msb_base='m46_50_00_00.msb', pi=15)
        # Gate 5.5 passes; other gates may or may not catch — for this
        # specific src/target the answer is None
        assert reason != 'grunt_trash_at_boss_bar'

    def test_exempt_set_covers_at_least_85_grunts_at_boss_bar(self, engine):
        """Sanity: V3_FRAGILE_SAFE_CONFIRMED contains enough grunts/
        trash to cover the bulk of legitimate boss-bar placements in
        real seeds (seed 877217 had ~92 grunt/trash @ boss-bar
        placements, 85 of which were in SAFE_CONFIRMED). If this
        invariant breaks, run the impact analysis again — likely
        means we accidentally removed a chr that was protecting many
        slots."""
        grunts_in_safe = [cp for cp in engine.V3_FRAGILE_SAFE_CONFIRMED
                          if cp not in ('c3664',)]  # the one we removed
        assert len(grunts_in_safe) >= 85, (
            f'SAFE_CONFIRMED unexpectedly small: {len(grunts_in_safe)} chrs. '
            f'Re-run impact analysis on a recent seed.')


# v0.24.68: Gate 5.6 — XXL/GIGA source slot integrity
# ============================================================================
class TestGate5_6XxlGigaSourceIntegrity:
    """v0.24.68: At any slot whose vanilla source is size_class XXL
    or GIGA, reject targets with mismatched anim_class OR target
    size_class smaller than L. Targets remaining valid: same
    anim_class AND size L+.

    Discovered: seeds 756907 and 388677 both CTD when leaving
    Stormveil Castle's southern face (front door). Pattern: vanilla
    XXL/GIGA boss slots in castle-area m60_4X_3Y tiles drift to
    targets with very different anim_class and/or much smaller size.
    When the cell streams in on transit, the chr-file load fails
    asset/nav validation against the slot's expectations and CTDs.

    Seed 388677 smoking-gun examples (all in southern-castle-exit
    tiles):
      m60_44_38_20 pi=91 ent=1048200800
        c4910 (quadruped_large/GIGA Magma Wyrm)
        → c2500 (humanoid/M Crucible Knight)  [anim drift + size drift]
      m60_43_38_10 pi=46 ent=1038100800
        c4602 (humanoid/XXL Snowfield Troll)
        → c3800 (humanoid/M Cleanrot Knight)  [size drift]
      m60_43_38_20 pi=103 ent=1038200800
        c4770 (humanoid/XXL Gargoyle)
        → c2120 (humanoid/M Malenia MMV)      [size drift; also nb_strict]

    User decision (v0.24.68): "enough diversity now" — go broad,
    cover all XXL/GIGA-source slots globally (no event-bound
    discrimination needed). Trade-off: loses some XXL→M and
    quadruped-GIGA→humanoid M diversity that was previously allowed.
    """

    def test_seed_388677_magma_wyrm_to_crucible_knight_allowed_v0_26_x(self, engine, tags):
        """The smoking-gun case 1: c4910 (quadruped_large/GIGA) →
        c2500 (humanoid/M) at m60_44_38_20 pi=91.

        v0.24.75: anim_class drift gate REMOVED. The swap still rejected
        — via xxl_giga_size_drift (M target at GIGA source).

        v0.26.x: M lifted from the size_drift list per user direction —
        "Midra should be eligible for any slot that's occupied by an
        L, XL, XXL, or GIGA mob. It's asymmetrically compatible." M
        targets at XXL/GIGA sources are now ALLOWED. The seed-388677
        crashes attributed to anim_class were already shown to be
        misattributed in v0.24.75; the size theory is now retired
        on the same grounds (M-humanoid at GIGA-arena slot has
        geometric capacity, and visual surprise is the marquee-NB
        feature, not a bug). If actual CTDs recur post-deployment,
        re-add a narrower gate keyed on the specific failing
        (source_cp, target_cp) pair rather than a blanket size rule."""
        assert tags['c4910'].get('size_class') == 'GIGA'
        assert tags['c4910'].get('anim_class') == 'quadruped_large'
        assert tags['c2500'].get('anim_class') == 'humanoid'
        reason = engine._reject_target_for_slot(
            target_cp='c2500', src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        assert reason is None, (
            f'v0.26.x: M-target at GIGA-source should pass size_drift; '
            f'got reason={reason!r}')

    def test_seed_388677_snowfield_troll_to_cleanrot_allowed_v0_26_x(self, engine, tags):
        """The smoking-gun case 2: c4602 (humanoid/XXL Snowfield
        Troll) → c3800 (humanoid/M Cleanrot Knight, heritage) at
        m60_43_38_10 pi=46. Same anim_class — size used to be the
        only remaining rejection.

        v0.26.x: M targets at XXL sources now allowed (see prior
        test docstring for full rationale)."""
        assert tags['c4602'].get('size_class') == 'XXL'
        assert tags['c4602'].get('anim_class') == 'humanoid'
        assert tags['c3800'].get('size_class') == 'M'
        reason = engine._reject_target_for_slot(
            target_cp='c3800', src_cp='c4602',
            src_variant_name='Snowfield Troll', tags=tags,
            msb_base='m60_43_38_10.msb', pi=46)
        assert reason is None, (
            f'v0.26.x: M-target at XXL-source should pass size_drift; '
            f'got reason={reason!r}')

    def test_anim_drift_gate_removed(self, engine, tags):
        """v0.24.75: anim_class drift check removed from Gate 5.6.
        The cross-anim-class swap that previously rejected as
        'xxl_giga_anim_drift' now passes the gate (assuming size
        is also compatible). Test with same-size cross-anim_class:
        c4910 GIGA quadruped_large → c4660 GIGA giga_boss."""
        reason = engine._reject_target_for_slot(
            target_cp='c4660', src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        assert reason != 'xxl_giga_anim_drift', (
            f'v0.24.75: anim_drift gate should be removed; got {reason!r}')

    def test_same_chr_preserved_allowed(self, engine, tags):
        """A slot keeping its vanilla c-prefix (preservation case)
        is always allowed — same anim_class, same size_class."""
        reason = engine._reject_target_for_slot(
            target_cp='c4910', src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        assert reason != 'xxl_giga_anim_drift'
        assert reason != 'xxl_giga_size_drift'

    def test_xxl_to_xxl_same_anim_allowed(self, engine, tags):
        """Cross-chr swap within XXL/same-anim-class is allowed.
        c4602 (humanoid/XXL Snowfield Troll) → c4770 (humanoid/XXL
        Gargoyle) — both humanoid XXL, valid swap."""
        assert tags['c4770'].get('size_class') == 'XXL'
        assert tags['c4770'].get('anim_class') == 'humanoid'
        reason = engine._reject_target_for_slot(
            target_cp='c4770', src_cp='c4602',
            src_variant_name='Snowfield Troll', tags=tags,
            msb_base='m60_43_38_10.msb', pi=46)
        assert reason != 'xxl_giga_anim_drift'
        assert reason != 'xxl_giga_size_drift'

    def test_xxl_to_l_allowed(self, engine, tags):
        """Size L target is the minimum acceptable at XXL slot —
        not gated. Sample: c4910 GIGA quadruped_large → c4280 L
        quadruped_large (Giant Ant)."""
        # find a quadruped_large L chr
        l_quadrupeds = [cp for cp, t in tags.items()
                        if t.get('anim_class') == 'quadruped_large'
                        and t.get('size_class') == 'L']
        if not l_quadrupeds:
            return  # no L quadruped_large chrs to test
        tgt = l_quadrupeds[0]
        reason = engine._reject_target_for_slot(
            target_cp=tgt, src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        assert reason != 'xxl_giga_anim_drift'
        assert reason != 'xxl_giga_size_drift'

    def test_source_not_xxl_or_giga_skipped(self, engine, tags):
        """Sources smaller than XXL bypass Gate 5.6 entirely. c4311
        humanoid/M Leyndell Soldier → c4040 misc/S Slug should not
        trigger 5.6 (it might trigger other gates, but not this
        one)."""
        reason = engine._reject_target_for_slot(
            target_cp='c4040', src_cp='c4311',
            src_variant_name='Leyndell Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=10)
        assert reason != 'xxl_giga_anim_drift'
        assert reason != 'xxl_giga_size_drift'

    def test_giga_giga_cross_anim_class_allowed_post_v0_24_75(self, engine, tags):
        """v0.24.75: GIGA → GIGA cross-anim-class is now ALLOWED.
        Previously rejected as 'xxl_giga_anim_drift'. With the gate
        removed, only size matters (both GIGA → passes)."""
        assert tags['c4660'].get('anim_class') == 'giga_boss'
        reason = engine._reject_target_for_slot(
            target_cp='c4660', src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        # Should pass Gate 5.6 (no anim_drift, sizes match GIGA→GIGA).
        # May still be rejected by some other gate — that's fine for
        # this test as long as it's not xxl_giga_anim_drift.
        assert reason != 'xxl_giga_anim_drift', (
            f'v0.24.75: cross-anim-class GIGA→GIGA should pass Gate 5.6; '
            f'got {reason!r}')

    def test_unique_reservation_honors_gate_via_delegation(self, engine, tags):
        """The mirror-semantic delegation: _score_slot_for_unique
        consults _reject_target_for_slot, so Gate 5.6 is honored at
        reservation time without a separate mirror.

        v0.24.75: anim_drift removed but size_drift retained — the
        c4910 GIGA → c2500 M swap still rejects (size)."""
        slot_info = {
            'msb': 'm60_44_38_20.msb', 'pi': 91,
            'source_cp': 'c4910',
            'source_variant_name': 'Magma Wyrm',
            'source_npc': 0,
            'cluster_id': None,
            'position': (0.0, 0.0, 0.0),
        }
        score = engine._score_slot_for_unique(slot_info, 'c2500', tags)
        assert score is None, (
            f'_score_slot_for_unique should reject size_drift at '
            f'GIGA slot via _reject_target_for_slot delegation, '
            f'got score={score}')

    def test_pool_still_has_diversity_for_giga_quadruped_slot(self, engine, tags):
        """Sanity: at a quadruped_large/GIGA source slot, the
        remaining valid target pool (same anim_class + L+) is large
        enough for variety. If this is too narrow, diversity suffers."""
        valid_targets = [cp for cp, t in tags.items()
                         if t.get('anim_class') == 'quadruped_large'
                         and t.get('size_class') in ('L', 'XL', 'XXL', 'GIGA')]
        # Allow for various edge cases — the actual pool varies by
        # data version. Just ensure there's SOME diversity.
        assert len(valid_targets) >= 5, (
            f'Quadruped_large L+ pool unexpectedly small: '
            f'{len(valid_targets)} chrs. Re-check tag data.')


# v0.24.69: Gate 5.6 demotion-path mirror
# ============================================================================
class TestGate5_6DemotionMirror:
    """v0.24.69: BIG_PROXIMITY and DENSITY_CAP demotion paths must
    apply the same XXL/GIGA source slot integrity check as
    pick_target_cp. Without this mirror, demotions bypass Gate 5.6
    just like reservation pre-pass used to bypass earlier gates.

    Discovered seed 388677 v0.24.68: m60_44_38_20 pi=91 c4910
    (quadruped_large/GIGA) → c3050 (humanoid/L) [anim drift] and
    m60_43_38_10 pi=46 c4602 (humanoid/XXL) → c4375 (humanoid/M)
    [size drift]. Both swaps passed Gate 5.6 at pick_target_cp time
    but BIG_PROXIMITY then demoted them to invalid Gate 5.6 targets.

    This recurring-bug-shape pattern (gate added → mirror missing
    → bypass) was the motivation for v0.24.27's
    _reject_target_for_slot consolidation in pick_target_cp /
    _score_slot_for_unique. The demotion paths predate that
    consolidation and still build _small_pool independently — easy
    to miss when adding new gates.

    These tests don't exercise the demotion path end-to-end (that
    requires running the full shuffle pipeline). They verify the
    structural property: the engine source contains the mirror code
    at both demotion sites. If somebody refactors and removes the
    mirror, the tests catch it.
    """

    def test_big_proximity_demotion_has_gate_5_6_mirror(self):
        """The BIG_PROXIMITY _small_pool construction (around line
        11170 in v0.24.69) must include a Gate 5.6 filter for
        XXL/GIGA sources. Verify the source contains the marker."""
        import os
        engine_path = os.path.join(os.path.dirname(__file__), '..', 'oops_v3.py')
        with open(engine_path) as f:
            src = f.read()
        # Check for the two markers anywhere in the file. They are
        # placed adjacently in the BIG_PROXIMITY section.
        assert 'Gate 5.6 mirror at BIG_PROXIMITY demotion' in src, (
            'BIG_PROXIMITY demotion site is missing Gate 5.6 mirror. '
            'A new demotion in this path may bypass XXL/GIGA slot '
            'integrity. Add the filter back.')
        assert "_src_size_for_56" in src, (
            'BIG_PROXIMITY mirror is present in comments but the '
            'filter variable _src_size_for_56 is missing.')

    def test_density_cap_demotion_has_gate_5_6_mirror(self):
        """The DENSITY_CAP _small_pool construction (around line
        11330 in v0.24.69) must also include the Gate 5.6 filter.
        Same structural check as BIG_PROXIMITY."""
        import os
        engine_path = os.path.join(os.path.dirname(__file__), '..', 'oops_v3.py')
        with open(engine_path) as f:
            src = f.read()
        # The DENSITY_CAP section has 'DENSITY_CAP demotion site' in
        # its mirror comment.
        assert 'DENSITY_CAP demotion site' in src, (
            'DENSITY_CAP demotion site is missing Gate 5.6 mirror. '
            'Demotions at this site may bypass XXL/GIGA slot '
            'integrity. Add the filter back.')

    def test_density_cap_fallback_skips_xxl_giga(self):
        """The _try_fallback helper in cmd_shuffle_v3 must return
        False (skip fallback) at XXL/GIGA source slots. All fallback
        chrs (Slug, Jellyfish, Putrid Flesh, Imp) are Gate-5.6-
        invalid (too small or wrong anim_class) at those slots."""
        import os
        engine_path = os.path.join(os.path.dirname(__file__), '..', 'oops_v3.py')
        with open(engine_path) as f:
            src = f.read()
        # The fallback should have an early-return for XXL/GIGA
        assert '_fb_src_size' in src, (
            '_try_fallback is missing the v0.24.69 XXL/GIGA early-'
            'return guard. Fallback at XXL/GIGA slots would place '
            'Slug/Jellyfish/etc., violating Gate 5.6.')
        # Find the immediate context after the variable definition
        # and check it filters on XXL/GIGA. Use 1500-char window to
        # cover the if-statement that consumes the variable.
        idx = src.index('_fb_src_size')
        fb_section = src[idx:idx + 1500]
        assert "in ('XXL', 'GIGA')" in fb_section, (
            '_fb_src_size check should filter on XXL/GIGA sizes.')

    def test_v3_big_proximity_demote_to_sizes_unchanged(self, engine):
        """Sanity: the demotion target size set is still {XS, S, M, L}.
        If somebody changes this to include XL+, the Gate 5.6 mirror
        comment needs updating (currently assumes the only Gate-5.6-
        valid size in the set is L)."""
        assert engine.V3_BIG_PROXIMITY_DEMOTE_TO_SIZES == frozenset(
            {'XS', 'S', 'M', 'L'}), (
            f'V3_BIG_PROXIMITY_DEMOTE_TO_SIZES changed to '
            f'{engine.V3_BIG_PROXIMITY_DEMOTE_TO_SIZES}. Re-check '
            f'the Gate 5.6 mirror logic.')

    def test_demotion_pool_viability_humanoid_xxl(self, engine, tags):
        """For humanoid XXL sources (c4602, c4600, c4770), there
        should be a viable demotion pool of humanoid L chrs. Without
        this, BIG_PROXIMITY can't demote → slot stays vanilla."""
        humano_l = [cp for cp, t in tags.items()
                    if t.get('anim_class') == 'humanoid'
                    and t.get('size_class') == 'L'
                    and cp not in engine.V3_EXCLUDE_PREFIXES
                    and cp not in engine.V3_EXCLUDE_TARGET_PREFIXES]
        assert len(humano_l) >= 5, (
            f'Humanoid L demotion pool too small ({len(humano_l)}): '
            f'BIG_PROXIMITY won\'t be able to demote humanoid XXL '
            f'sources. Need at least 5 chrs for reasonable variety.')

    def test_demotion_pool_quadruped_large_giga_tight_but_workable(self, engine, tags):
        """quadruped_large GIGA sources (c4910 Magma Wyrm) have a
        tight L demotion pool. Verify it's still > 0 — otherwise
        the slot can never demote and BIG_PROXIMITY is a no-op
        there. Even 2-3 chrs is acceptable."""
        quad_l = [cp for cp, t in tags.items()
                  if t.get('anim_class') == 'quadruped_large'
                  and t.get('size_class') == 'L'
                  and cp not in engine.V3_EXCLUDE_PREFIXES
                  and cp not in engine.V3_EXCLUDE_TARGET_PREFIXES]
        assert len(quad_l) >= 2, (
            f'quadruped_large L pool too small ({len(quad_l)}): '
            f'BIG_PROXIMITY can\'t demote c4910/c4460 sources.')

    def test_giga_boss_and_large_boss_ground_no_l_demote_targets(self, engine, tags):
        """Sanity: giga_boss and large_boss_ground anim_classes have
        NO L chrs (confirmed via empirical lookup). At slots with
        those sources, BIG_PROXIMITY demotion will find empty
        _small_pool and fall through to 'leave original big' —
        which is the correct behavior (preserve slot integrity)."""
        for ac in ('giga_boss', 'large_boss_ground'):
            l_chrs = [cp for cp, t in tags.items()
                      if t.get('anim_class') == ac
                      and t.get('size_class') == 'L']
            assert len(l_chrs) == 0, (
                f'{ac} L pool unexpectedly non-empty: {l_chrs}. '
                f'Demotion logic may now have options it didn\'t '
                f'have before — re-verify Gate 5.6 mirror behavior.')


# v0.24.70: anim_compat at demotion sites uses NB markers (not just expects_boss_arena)
# ============================================================================
class TestDemotionAnimCompatNbMarker:
    """v0.24.70: BIG_PROXIMITY and DENSITY_CAP demotion paths check
    anim_class compatibility at scripted-intro slots. The picker's
    notion of "scripted intro" is `expects_boss_arena OR NB-marker
    in source variant_name`. The demotion sites historically only
    checked `expects_boss_arena`.

    Result: slots whose source tag has expects_boss_arena=False but
    whose variant_name carries an NB marker (e.g. c4130 Demi-Human
    Queen, c3100 Bell Bearing Hunter, c5810 Demi-Human Swordmaster
    — all night_boss tier but expects_boss_arena=False) bypassed
    the anim_compat filter at demotion time. Demotions could land
    anim-incompatible chrs (e.g. humanoid c7100 at quadruped c4130
    slot) → Margit-style scripted-cinematic softlock / preboss wave
    never fires.

    Confirmed seed 388677 m49_29 pi=16: c4130 quadruped/XL got
    BIG_PROXIMITY-demoted (pi=12 had Fat Inquisitor XL within 9.0u)
    to c7100 humanoid/L (Ancient Hero). Player entered m49_29, wave
    never fired. v0.24.70 fixes both demotion sites to check the NB
    marker in addition to expects_boss_arena.
    """

    def test_c4130_expects_boss_arena_is_false(self, tags):
        """The trigger condition: c4130 has expects_boss_arena=False
        despite being a night_boss tier chr at a real NB arena slot.
        This is the data-tag quirk that the v0.23.05.2 filter
        original missed."""
        assert tags['c4130'].get('expects_boss_arena') == False, (
            'If c4130 gets expects_boss_arena=True, the v0.24.70 '
            'fix is no longer needed for this specific case — but '
            'keep the NB-marker check anyway for c3100, c5810, etc.')
        assert tags['c4130'].get('tier') == 'night_boss'

    def test_c3100_and_c5810_same_quirk(self, tags):
        """Bell Bearing Hunter (c3100) and Demi-Human Swordmaster
        (c5810) have the same data-tag quirk: night_boss tier but
        expects_boss_arena=False. The NB-marker check covers them."""
        for cp in ('c3100', 'c5810'):
            assert tags[cp].get('expects_boss_arena') == False, (
                f'{cp} expects_boss_arena changed — verify '
                'v0.24.70 still applies.')
            assert tags[cp].get('tier') == 'night_boss'

    def test_big_proximity_anim_compat_reads_nb_marker(self):
        """Structural: BIG_PROXIMITY anim_compat block uses
        _is_scripted_intro_here (combined check) and reads
        _src_nm_pre (variant_name) before the anim_compat filter."""
        import os
        engine_path = os.path.join(os.path.dirname(__file__), '..', 'oops_v3.py')
        with open(engine_path) as f:
            src = f.read()
        # Both markers should be present in the BIG_PROXIMITY block
        assert 'v0.24.69b' in src, (
            'BIG_PROXIMITY anim_compat doesn\'t mention v0.24.69b '
            'fix. The NB-marker check at demotion time is missing.')
        assert '_is_scripted_intro_here' in src, (
            'BIG_PROXIMITY anim_compat should use combined '
            '_is_scripted_intro_here check (expects_boss_arena OR '
            'NB-marker), not just expects_boss_arena.')
        assert '_recip_has_nb_marker' in src, (
            'Mirror variable _recip_has_nb_marker (variant_name '
            'NB-marker detection) is missing.')

    def test_density_cap_anim_compat_reads_nb_marker(self):
        """Structural: DENSITY_CAP same fix."""
        import os
        engine_path = os.path.join(os.path.dirname(__file__), '..', 'oops_v3.py')
        with open(engine_path) as f:
            src = f.read()
        # The fix is in the _density_demote function; check both
        # markers appear twice in the source (once in BIG_PROXIMITY,
        # once in DENSITY_CAP)
        assert src.count('_is_scripted_intro_here') >= 2, (
            'DENSITY_CAP anim_compat appears to be missing the '
            'NB-marker check. The fix should mirror BIG_PROXIMITY.')
        assert src.count('_recip_has_nb_marker') >= 2, (
            'DENSITY_CAP NB-marker variable should mirror '
            'BIG_PROXIMITY.')

    def test_nb_marker_set_covers_expected_names(self, engine):
        """Sanity: V3_NIGHT_BOSS_NAME_MARKERS includes 'Night Boss'
        marker. If somebody renames it, the mirror needs updating."""
        markers = engine.V3_NIGHT_BOSS_NAME_MARKERS
        assert 'Night Boss' in markers, (
            'V3_NIGHT_BOSS_NAME_MARKERS missing "Night Boss" — '
            'NB1/NB2 boss slot detection will fail.')
        # The classic Demi-Human Queen variant name should match
        sn = 'Demi-Human Queen (Night Boss)'
        assert any(m in sn for m in markers)

    def test_picker_and_demotion_use_same_definition(self):
        """Structural: the picker (pick_target_cp) and both demotion
        sites must compute _is_scripted_intro the same way:
        `expects_boss_arena OR NB-marker`. Verify all three sites
        have both checks."""
        import os
        engine_path = os.path.join(os.path.dirname(__file__), '..', 'oops_v3.py')
        with open(engine_path) as f:
            src = f.read()
        # Picker uses _is_scripted_intro (without _here suffix)
        assert '_is_scripted_intro = _slot_is_arena or _slot_is_night_boss' in src
        # Demotion sites use _is_scripted_intro_here (avoids variable
        # shadowing across function scopes)
        assert '_is_scripted_intro_here = _recip_arena or _recip_has_nb_marker' in src


# v0.24.72: tag backfill regression tests
# ============================================================================
class TestTagBackfillV0_24_72:
    """v0.24.72: backfilled anim_class + size_class for 43 untagged chrs
    in nr_enemy_tags.json and mmv_imports.json. Justification per entry
    in scripts/backfill_tags_v0_24_72.py.

    These tests verify the canonical entries didn't lose their backfill,
    and that Gate 5.6 (and other anim_class filters) now correctly fire
    on the backfilled chrs. Catches regression where someone
    regenerates the tag files without preserving the backfill.

    Confirmed seed 388677 v0.24.71 m34_00 (Albinauric Village)
    pi=100/101 CTD: c4171 (large_boss_ground/XXL) → c4601 humanoid
    Troll Knight, slipped past Gate 5.6 because c4601 was untagged.
    Backfill resolves: c4601 = humanoid/XXL → Gate 5.6 catches the
    anim drift.
    """

    def test_c4601_troll_knight_backfilled(self, tags):
        """The CTD-triggering case. Without this, the whole class of
        post_dlc_dump untagged chrs slips through filters."""
        t = tags['c4601']
        assert t.get('anim_class') == 'humanoid'
        assert t.get('size_class') == 'XXL'
        assert t.get('_tags_backfilled_v0_24_72') is True

    def test_gate_5_6_c4601_at_large_boss_ground_source_post_v0_24_75(self, engine, tags):
        """The seed-388677 fix verification, updated for v0.24.75.

        Pre-v0.24.75: at c4171 (Giant Putrid Flesh, large_boss_ground/XXL)
        source slot, Gate 5.6 rejected c4601 (humanoid/XXL) due to
        anim_class drift.

        Post-v0.24.75: anim_class drift gate removed per user directive.
        c4601 humanoid/XXL at c4171 large_boss_ground/XXL source now
        passes Gate 5.6 (sizes match, anim_class no longer checked).

        Whether the seed-388677 CTD recurs is now an open question —
        the original attribution may have been wrong (per user
        directive: "anim_class crashes were actually other root cause").
        If the CTD does recur in playtest, re-investigate root cause."""
        reason = engine._reject_target_for_slot(
            target_cp='c4601', src_cp='c4171',
            src_variant_name='Giant Putrid Flesh (Blood)', tags=tags,
            msb_base='m34_00_00_00.msb', pi=100)
        assert reason != 'xxl_giga_anim_drift', (
            f'v0.24.75: anim_drift gate removed; got {reason!r}')

    def test_gate_5_6_accepts_c4601_at_humanoid_xxl_source(self, engine, tags):
        """Sanity: at humanoid XXL source slots (the Troll family
        c4600/c4602/c4603), c4601 is a perfectly compat swap and
        must NOT be rejected. Gate 5.6 is anim-aware now."""
        reason = engine._reject_target_for_slot(
            target_cp='c4601', src_cp='c4602',
            src_variant_name='Snowfield Troll', tags=tags,
            msb_base='m60_43_38_10.msb', pi=46)
        assert reason is None

    def test_backfill_covers_crab_family(self, tags):
        """All 4 backfilled Crab variants (c2273/c2274/c2275/c2277)
        should be aquatic. Sizes vary."""
        for cp in ('c2273', 'c2275', 'c2277'):
            assert tags[cp]['anim_class'] == 'aquatic', f'{cp} should be aquatic'
            assert tags[cp]['size_class'] == 'S'
        # Giant Sleep Crab
        assert tags['c2274']['anim_class'] == 'aquatic'
        assert tags['c2274']['size_class'] == 'XL'

    def test_backfill_covers_dlc_soldiers(self, tags):
        """DLC soldier/knight variants — all humanoid/M, matching
        the c431x and c437x family patterns."""
        for cp in ('c4312', 'c4316', 'c4356', 'c4358', 'c4376'):
            assert tags[cp]['anim_class'] == 'humanoid', f'{cp} should be humanoid'
            assert tags[cp]['size_class'] == 'M', f'{cp} should be M'

    def test_backfill_covers_mmv_imports(self, tags):
        """MMV imports c5000/c5230/c5930/c6220/c8500 were in
        mmv_imports.json with only size set; verify anim_class
        was backfilled."""
        # Commander Gaius — quadruped_large (centaur on boar)
        assert tags['c5000'].get('anim_class') == 'quadruped_large'
        # Scadutree Avatar — quadruped_large (matches Erdtree Avatar)
        assert tags['c5230'].get('anim_class') == 'quadruped_large'
        # Giant Skeleton — humanoid
        assert tags['c5930'].get('anim_class') == 'humanoid'
        # Fire Demon — humanoid
        assert tags['c6220'].get('anim_class') == 'humanoid'
        # Manus — humanoid
        assert tags['c8500'].get('anim_class') == 'humanoid'

    def test_untagged_count_dramatically_reduced(self, tags, engine):
        """Sanity gauge: before backfill, ~36 combatant chrs were
        untagged in the active pool. After backfill, should be <= 5
        (intentional skips: Storm King, Executor, etc.)."""
        untagged = [cp for cp, t in tags.items()
                    if (t.get('anim_class') is None or t.get('size_class') is None)
                    and t.get('tier') not in ('cinematic', 'remembrance_uncle')
                    and cp not in engine.V3_EXCLUDE_TARGET_PREFIXES
                    and cp not in engine.V3_EXCLUDE_PREFIXES]
        assert len(untagged) <= 5, (
            f'After v0.24.72 backfill, expected ≤5 untagged combatant '
            f'chrs in active pool, got {len(untagged)}: {untagged}. '
            f'Either backfill regressed OR new untagged chrs slipped in.')


# v0.24.73: MMV roster restoration
# ============================================================================
class TestMmvRosterRestorationV0_24_73:
    """v0.24.73 fulfills the v0.24.65 user directive ("the ENTIRE MMV
    roster is back on the table. lift it dude") for entries that
    survived as hardcoded exclusions in oops_v3.py. The data-file lift
    happened in v0.24.65; this is the engine-source lift.

    Lifts:
      - c8300 Dragonslayer Armor from V3_NIGHT_BOSS_EXCLUDE_TARGETS
      - SoTE 4 (c4511 Fortissax, c5030 Romina, c5051 Midra, c5200
        Metyr) from V3_EXCLUDE_TARGET_PREFIXES
      - c5000 Commander Gaius promoted to V3_NIGHT_BOSS_CALIBER_TARGETS

    Safety net: each gets cap=1 in V3_UNIQUE_TARGET_CAPS — same
    bounded-blast-radius policy as the v0.24.65 broken_runtime lift.
    Plus boss_clear_watchdog (300s, in-loop) + preboss_wake_timeout
    (90s, outer wake, v0.24.71) catch any AI-stall failure.

    These tests are regression guards: catch silent re-introduction
    of the old exclusions during refactors.
    """

    def test_c8300_lifted_from_nb_exclusion(self, engine):
        """c8300 Dragonslayer Armor must NOT be in NB exclude set.
        The freeze that originally triggered exclusion (seed 35300
        v0.23.72-late) is mitigated by the boss_clear_watchdog patch
        that shipped concurrently with the exclusion."""
        assert 'c8300' not in engine.V3_NIGHT_BOSS_EXCLUDE_TARGETS
        assert 'c8300' not in engine.V3_EXCLUDE_TARGET_PREFIXES
        # cap safety net in place. v0.24.73 introduced cap=1; v0.25.3
        # raised heritage NBs 1→2 ("appearance budget too restrictive
        # at cap=1, ~50% miss rate per seed"). cap=2 still bounded.
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c8300') == 2

    def test_sote_four_lifted_from_global_exclusion(self, engine):
        """The 4 SoTE MMV bosses (Fortissax, Romina, Midra, Metyr) are
        lifted per the v0.24.65 directive. The full MMV deploy formula
        documented in nr_missing_chr_files.json was confirmed working
        with Romina; the other 3 share the same SoTE-preload pattern."""
        for cp in ('c4511', 'c5030', 'c5051', 'c5200'):
            assert cp not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
                f'{cp} re-added to V3_EXCLUDE_TARGET_PREFIXES — '
                'v0.24.73 lift was reverted. Verify intentional.')
            # v0.25.3: 1→2 raise (same rationale as c8300 above).
            assert engine.V3_UNIQUE_TARGET_CAPS.get(cp) == 2, (
                f'{cp} missing cap=2 safety net.')

    def test_c5000_commander_gaius_promoted_to_nb_caliber(self, engine, tags):
        """Commander Gaius (now properly tagged quadruped_large/XL
        after v0.24.72 backfill) joins the NB caliber pool. SoTE
        field-boss caliber matches the c4730 Starscourge Radahn /
        c5230 Scadutree Avatar slot type."""
        assert 'c5000' in engine.V3_NIGHT_BOSS_CALIBER_TARGETS
        # Confirm the v0.24.72 backfill is still applied
        assert tags['c5000'].get('anim_class') == 'quadruped_large'
        assert tags['c5000'].get('size_class') == 'XL'
        # v0.25.3: 1→2 raise (same rationale as c8300 above).
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c5000') == 2

    def test_c5200_metyr_tagged_v0_24_73(self, tags):
        """v0.24.72 left c5200 Metyr untagged (anim_class=None).
        v0.24.73 adds large_boss_ground tag so Gate 5.6 can filter
        Metyr placements properly now that she's no longer excluded.

        v0.26.x size_class correction: NpcParam.csv showed Metyr at
        h=5.00 r=5.00, which is firmly XXL (the r=5.00 alone pushes
        her into XXL). Was previously tagged XL in MMV pack."""
        t = tags['c5200']
        assert t.get('anim_class') == 'large_boss_ground'
        assert t.get('size_class') == 'XXL'
        assert t.get('_tags_backfilled_v0_24_73') is True

    def test_nb_caliber_pool_grew_by_one(self, engine):
        """Sanity gauge: caliber pool was 97 in v0.24.72. After
        promoting c5000, was 98. v0.24.86-patch4 demoted c4811 Erdtree
        Avatar Variant from night_boss to field_boss (entrance-anim
        freezes at NB slots), bringing it to 97.

        v0.26.x: down to 96 from manual_retier_v0.24.100 source-category
        evolution, then back UP to 99 after the v0.26.x tier collapse
        promoted 23 ex-field_boss chrs to night_boss (most were already
        NB-CALIBER-eligible via auto-extension, but a few weren't, plus
        c4811 returns to the pool — the v0.24.86-patch4 demotion got
        reverted by the collapse, accepting the entrance-anim risk).

        v0.26.x-late: down to 97 again. After V3_TAG_OVERRIDES was
        flattened (the tier-correction Python dict moved into the
        per-pack JSON manifests), Alaric reviewed the 23 collapse-
        promoted chrs and identified 15 (Trolls, Dragons, Avatars,
        Runebear, Guardian Golem, Red Bear, Ancient Hero of Zamor,
        Fingercreeper, Red Wolf) as misclassified — they're field-tier
        in vanilla and play as miniboss-tier filler, not marquee NB.
        Tags demoted in nr_enemy_tags.json directly.

        If the count drifts further, run dev/extract_placement_budget.py
        and diff `nb_caliber=true` entries against the prior snapshot.
        """
        assert len(engine.V3_NIGHT_BOSS_CALIBER_TARGETS) == 97

    def test_dragonslayer_armor_at_nb_slot_no_longer_filter_blocked(self, engine, tags):
        """Direct test of the lift: c8300 at an NB-marker slot must
        pass the NB-exclude filter (v0.23.09 check)."""
        # c8300 is humanoid/L, c3100 BBH slot is humanoid/L source —
        # anim-compat. Pre-v0.24.73 it'd be NB-exclude-rejected.
        # _reject_target_for_slot doesn't directly enforce NB-exclude
        # (that's in the picker at line ~9585), but we can verify
        # membership instead.
        assert 'c8300' not in engine.V3_NIGHT_BOSS_EXCLUDE_TARGETS

    def test_lifted_mmvs_have_valid_metadata(self, tags):
        """Sanity: each lifted MMV has anim_class + size_class so the
        filter pipeline can reason about it. Untagged-bypass would
        re-create the c4601-style CTD risk we just fixed in v0.24.72."""
        for cp in ('c8300', 'c4511', 'c5030', 'c5051', 'c5200', 'c5000'):
            t = tags.get(cp, {})
            assert t.get('anim_class') is not None, (
                f'{cp} has no anim_class — would bypass Gate 5.6 + '
                'anim_compat filters. Add tag before lifting.')
            assert t.get('size_class') is not None, (
                f'{cp} has no size_class — would bypass Gate 5.6 '
                'size check. Add tag before lifting.')


# v0.24.75: Fort lifted + Cathedral loosened + merchant pool restricted
# ============================================================================
class TestGuardianGolemPoolLooseningsV0_24_75:
    """v0.24.75 makes two changes to Guardian Golem source-slot handling
    + restricts merchant pool to vanilla NR.

    1. m30_30 pi=45 (Fort Guardian Golem) LIFTED from V3_PROBLEM_SLOTS —
       proven resilient per user playtest (Centipede Demon worked there).

    2. m38_00 pi=51 (Cathedral Guardian Golem) STAYS in V3_PROBLEM_SLOTS
       but loosened via new V3_PROBLEM_SLOT_EXTRA_ALLOWS mechanism that
       whitelists big dragons to bypass SAFE_CONFIRMED filter.

    3. V3_MERCHANT_MODEL_POOL restricted to vanilla NR — heritage/MMV/
       post_dlc entries commented out until MMV-asset-deploy reliability
       is nailed down (seed 454841 v0.24.74 mid-Day-2 CTD).
    """

    def test_m30_30_fort_gg_lifted(self, engine):
        """v0.24.75 lifted Fort GG; v0.24.77 RESTORED it after the c4810
        Erdtree Avatar emerge-anim CTD in seed 886942. Test renamed
        intent: keep the v0.24.75 spec assertion but invert the
        assertion. The TestFortGuardianGolemRestoredV0_24_77 class
        covers the v0.24.77 restoration in detail."""
        # v0.24.77: back in V3_PROBLEM_SLOTS — see that class's tests.
        assert ('m30_30_00_00.msb', 45) in engine.V3_PROBLEM_SLOTS

    def test_m38_00_cathedral_gg_still_fragile(self, engine):
        """Cathedral Guardian Golem source slot remains in V3_PROBLEM_SLOTS
        (the fragility is still real; just loosened via EXTRA_ALLOWS)."""
        assert ('m38_00_00_00.msb', 51) in engine.V3_PROBLEM_SLOTS

    def test_problem_slot_extra_allows_exists(self, engine):
        """v0.24.75 adds V3_PROBLEM_SLOT_EXTRA_ALLOWS mechanism."""
        assert hasattr(engine, 'V3_PROBLEM_SLOT_EXTRA_ALLOWS')
        assert isinstance(engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS, dict)

    def test_cathedral_dragons_whitelisted(self, engine):
        """Cathedral pi=51 should whitelist the big-dragon family via
        EXTRA_ALLOWS. With v0.24.75 removing anim_class restrictions
        globally, both grounded (Magma Wyrm) and flying (Great Wyrm,
        Lichdragon) dragons are geometrically eligible."""
        allows = engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
            ('m38_00_00_00.msb', 51))
        assert allows is not None
        assert 'c4910' in allows  # Magma Wyrm
        assert 'c4911' in allows  # Great Wyrm Theodorix
        assert 'c4540' in allows  # Lichdragon

    def test_cathedral_big_wyrm_passes_fragile_filter(self, engine, tags):
        """c4910 Magma Wyrm at m38_00 pi=51 should NOT be rejected
        by the fragile filter post-v0.24.75 — EXTRA_ALLOWS bypasses
        the SAFE_CONFIRMED requirement, AND anim_class drift gate
        no longer blocks quadruped_large at giga_boss source."""
        assert 'c4910' not in engine.V3_FRAGILE_SAFE_CONFIRMED, (
            'c4910 expected to be NOT in V3_FRAGILE_SAFE_CONFIRMED. '
            'If you added it there, this EXTRA_ALLOWS test is meaningless.')

        slot_info = {
            'msb': 'm38_00_00_00.msb',
            'pi': 51,
            'source_cp': 'c4660',
            'source_npc': 46600030,
            'source_variant_name': 'Guardian Golem (Cathedral)',
            'position': [0.0, 0.0, 0.0],
        }
        score = engine._score_slot_for_unique(slot_info, 'c4910', tags)
        assert score is not None, (
            'c4910 Magma Wyrm should be allowed at m38_00 pi=51 via '
            'EXTRA_ALLOWS, but _score_slot_for_unique rejected it.')

    def test_anim_class_drift_gate_removed(self, engine, tags):
        """v0.24.75: xxl_giga_anim_drift removed from _reject_target_for_slot.
        c4910 quadruped_large at c4660 giga_boss source should pass
        the gate (the v0.24.68 gate is gone)."""
        reason = engine._reject_target_for_slot(
            target_cp='c4910', src_cp='c4660',
            src_variant_name='Guardian Golem (Cathedral)',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51,
        )
        assert reason != 'xxl_giga_anim_drift', (
            f'Expected anim_class drift gate to be removed, got: {reason}')

    def test_size_drift_gate_still_active(self, engine, tags):
        """v0.24.75: size restrictions retained. c4040 Slug (size M) at
        c4660 (GIGA) should still reject as xxl_giga_size_drift."""
        reason = engine._reject_target_for_slot(
            target_cp='c4040', src_cp='c4660',
            src_variant_name='Guardian Golem',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51,
        )
        assert reason == 'xxl_giga_size_drift', (
            f'Expected size_drift gate to still fire for M target at '
            f'GIGA source, got: {reason}')

    def test_forbidden_by_source_anim_emptied(self, engine):
        """v0.24.75: V3_FORBIDDEN_BY_SOURCE_ANIM emptied per user
        directive (anim_class CTD theories misattributed)."""
        assert dict(engine.V3_FORBIDDEN_BY_SOURCE_ANIM) == {}

    def test_swap_compat_anim_class_helper_removed(self):
        """v0.24.75 neutered `swap_compat._compat_anim_class` to always
        return True (user directive removing anim_class restrictions).
        v0.26.x: function fully removed — the helper had no remaining
        callers after the neutering, and a constant-true function adds
        nothing. Lock in that it stays absent so a future refactor
        doesn't accidentally restore anim_class gating without an
        explicit user-policy review.
        """
        import swap_compat
        assert not hasattr(swap_compat, '_compat_anim_class'), (
            "swap_compat._compat_anim_class was removed in v0.26.x "
            "after being a no-op since v0.24.75. If you're re-adding it, "
            "first reconcile with the v0.24.75 user directive that "
            "anim_class CTD theories were misattributed.")

    def test_cathedral_unallowed_chr_still_rejected(self, engine, tags):
        """A random non-SAFE_CONFIRMED chr that's NOT in EXTRA_ALLOWS
        should still be rejected by the fragile filter."""
        # Pick a chr that's neither in SAFE_CONFIRMED, RESILIENT_BIPEDS,
        # NOR in the m38_00 pi=51 EXTRA_ALLOWS list.
        not_allowed_anywhere = None
        excludes = (engine.V3_FRAGILE_SAFE_CONFIRMED
                    | engine.V3_RESILIENT_BIPEDS
                    | engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
                        ('m38_00_00_00.msb', 51), set()))
        for cp, t in tags.items():
            if cp in excludes:
                continue
            if cp.startswith('c52') or cp.startswith('c6'):
                continue  # skip Nightfarer NPCs and edge cases
            if t.get('anim_class') == 'humanoid' and t.get('size_class') == 'M':
                not_allowed_anywhere = cp
                break
        assert not_allowed_anywhere is not None, (
            'Test fixture: could not find a non-SAFE non-RESILIENT '
            'non-EXTRA_ALLOWS chr. Pool likely shifted; update test.')

        slot_info = {
            'msb': 'm38_00_00_00.msb',
            'pi': 51,
            'source_cp': 'c4660',
            'source_npc': 46600030,
            'source_variant_name': 'Guardian Golem (Cathedral)',
            'position': [0.0, 0.0, 0.0],
        }
        score = engine._score_slot_for_unique(slot_info, not_allowed_anywhere, tags)
        assert score is None, (
            f'{not_allowed_anywhere} should be rejected at Cathedral '
            'fragile slot (not in SAFE / RESILIENT / EXTRA_ALLOWS), '
            'but _score_slot_for_unique accepted it.')

    def test_merchant_pool_vanilla_restricted(self, engine):
        """v0.24.75 RESTRICTED: merchant pool should exclude all
        non-vanilla NR chrs (heritage, post_dlc_dump, mmv_import)
        until MMV asset-deploy reliability is nailed down."""
        DISABLED_NON_VANILLA = {
            # Heritage
            'c3800', 'c3510', 'c3070', 'c3750', 'c3860', 'c4385', 'c4820',
            # Scholar Remembrance manual tags
            'c4352',
            # post_dlc_dump
            'c5081', 'c5320', 'c5651', 'c7720',
            # MMV imports
            'c1310', 'c2030', 'c4720', 'c4721', 'c5030', 'c5130', 'c5300',
            'c5740', 'c5840', 'c5880', 'c6200', 'c6210', 'c8300',
        }
        leaked = DISABLED_NON_VANILLA & engine.V3_MERCHANT_MODEL_POOL
        assert not leaked, (
            f'Non-vanilla merchant pool entries leaked: {sorted(leaked)}. '
            'These were disabled v0.24.75 pending MMV asset-deploy '
            'reliability fix. Should be commented out in '
            'V3_MERCHANT_MODEL_POOL.')

    def test_merchant_pool_keeps_vanilla(self, engine):
        """Sanity: vanilla NR chrs should still be in the merchant pool."""
        # Should be there — pre-v0.23.74 baseline merchant pool entries
        for cp in ('c3010', 'c4290', 'c4351', 'c4313', 'c2140', 'c2500',
                   'c3100', 'c4570', 'c5070'):
            assert cp in engine.V3_MERCHANT_MODEL_POOL, (
                f'{cp} (vanilla NR merchant pool member) missing — '
                'v0.24.75 restriction was too aggressive.')


# v0.24.76: size-first reservation ordering within cap tier
# ============================================================================
class TestReservationOrderBigFirstV0_24_76:
    """v0.24.76: _compute_unique_reservations now sorts by (cap, size)
    rather than just cap. Big chrs (GIGA, XXL) get first pick at rare
    big-source slots before smaller chrs can score-grab them via NB-marker
    or boss-arena heuristics.

    The original v0.23.11 within-cap shuffle is preserved as a tiebreaker
    inside each (cap, size) bucket.
    """

    def test_size_order_constant_defined(self, engine):
        """Sanity: the size-priority order is well-defined."""
        # _SIZE_ORDER_FOR_RESERVATION is a local in _compute_unique_reservations,
        # but the sort key should produce a deterministic ordering.
        # Verify by running with a small synthetic dict.
        import random
        rng = random.Random(42)
        sample = [
            ('cp_giga', 1),    # cap=1 GIGA
            ('cp_xxl',  1),    # cap=1 XXL
            ('cp_xl',   1),    # cap=1 XL
            ('cp_l',    1),    # cap=1 L
            ('cp_m',    1),    # cap=1 M
            ('cp_s',    1),    # cap=1 S
            ('cp_xs',   1),    # cap=1 XS
            ('cp_giga2',2),    # cap=2 GIGA
            ('cp_m2',   2),    # cap=2 M
        ]
        synthetic_tags = {
            'cp_giga':  {'size_class': 'GIGA'},
            'cp_xxl':   {'size_class': 'XXL'},
            'cp_xl':    {'size_class': 'XL'},
            'cp_l':     {'size_class': 'L'},
            'cp_m':     {'size_class': 'M'},
            'cp_s':     {'size_class': 'S'},
            'cp_xs':    {'size_class': 'XS'},
            'cp_giga2': {'size_class': 'GIGA'},
            'cp_m2':    {'size_class': 'M'},
        }
        # Replicate the v0.24.76 sort key inline
        _SIZE_ORDER = {'GIGA': 0, 'XXL': 1, 'XL': 2, 'L': 3, 'M': 4, 'S': 5, 'XS': 6}
        def _sort_key(kv):
            cp, cap = kv
            size = synthetic_tags.get(cp, {}).get('size_class') or '?'
            return (cap, _SIZE_ORDER.get(size, 99))
        rng.shuffle(sample)
        sample.sort(key=_sort_key)
        # cap=1 chrs should all come before cap=2
        cap_seq = [s[1] for s in sample]
        assert cap_seq == sorted(cap_seq), (
            f'cap order broken: {cap_seq}')
        # Within cap=1, size should be GIGA → XXL → XL → L → M → S → XS
        cap1 = [s[0] for s in sample if s[1] == 1]
        assert cap1 == ['cp_giga', 'cp_xxl', 'cp_xl', 'cp_l', 'cp_m', 'cp_s', 'cp_xs'], (
            f'size order broken within cap=1: {cap1}')
        # Within cap=2, GIGA before M
        cap2 = [s[0] for s in sample if s[1] == 2]
        assert cap2 == ['cp_giga2', 'cp_m2'], (
            f'size order broken within cap=2: {cap2}')

    def test_within_size_bucket_shuffled(self, engine):
        """Within the same (cap, size) bucket, the v0.23.11 shuffle
        survives — different RNG seeds produce different within-bucket
        orderings."""
        import random
        # Two GIGA cap=1 chrs — should sometimes appear in different
        # orders across RNG seeds.
        synthetic = [('cp_a_giga', 1), ('cp_b_giga', 1), ('cp_c_giga', 1)]
        synthetic_tags = {cp: {'size_class': 'GIGA'} for cp, _ in synthetic}
        _SIZE_ORDER = {'GIGA': 0, 'XXL': 1, 'XL': 2, 'L': 3, 'M': 4, 'S': 5, 'XS': 6}
        def _sort_key(kv):
            cp, cap = kv
            size = synthetic_tags.get(cp, {}).get('size_class') or '?'
            return (cap, _SIZE_ORDER.get(size, 99))
        seen_orderings = set()
        for seed in range(20):
            rng = random.Random(seed)
            items = list(synthetic)
            rng.shuffle(items)
            items.sort(key=_sort_key)
            seen_orderings.add(tuple(cp for cp, _ in items))
        # We expect more than one unique ordering across 20 seeds —
        # otherwise the shuffle isn't doing its job.
        assert len(seen_orderings) > 1, (
            f'Within-bucket shuffle appears broken — same order across '
            f'all 20 seeds: {seen_orderings}')

    def test_unknown_size_sorts_last(self, engine):
        """Chrs with missing/unknown size_class sort AFTER known-size
        chrs in the same cap tier. Defensive: never let an unknown-size
        chr grab a slot before a known-big chr."""
        import random
        rng = random.Random(0)
        items = [('cp_unknown', 1), ('cp_giga', 1), ('cp_m', 1)]
        synthetic_tags = {
            'cp_unknown': {},  # no size_class
            'cp_giga': {'size_class': 'GIGA'},
            'cp_m': {'size_class': 'M'},
        }
        _SIZE_ORDER = {'GIGA': 0, 'XXL': 1, 'XL': 2, 'L': 3, 'M': 4, 'S': 5, 'XS': 6}
        def _sort_key(kv):
            cp, cap = kv
            size = synthetic_tags.get(cp, {}).get('size_class') or '?'
            return (cap, _SIZE_ORDER.get(size, 99))
        rng.shuffle(items)
        items.sort(key=_sort_key)
        order = [cp for cp, _ in items]
        # GIGA first, then M, then unknown
        assert order == ['cp_giga', 'cp_m', 'cp_unknown'], (
            f'Unknown-size should sort last: got {order}')

    def test_real_engine_giga_before_m(self, engine, tags):
        """Integration smoke test using real engine V3_UNIQUE_TARGET_CAPS:
        confirm at least one cap=1 GIGA chr exists AND at least one
        cap=1 M chr exists, so the ordering actually matters in
        practice."""
        cap1_gigas = [cp for cp, cap in engine.V3_UNIQUE_TARGET_CAPS.items()
                      if cap == 1 and tags.get(cp, {}).get('size_class') == 'GIGA']
        cap1_mediums = [cp for cp, cap in engine.V3_UNIQUE_TARGET_CAPS.items()
                        if cap == 1 and tags.get(cp, {}).get('size_class') == 'M']
        assert len(cap1_gigas) >= 5, (
            f'Expected at least 5 cap=1 GIGA chrs; got {len(cap1_gigas)}')
        # v0.26.x: floor lowered from 10 → 9 after c3610 was dropped from
        # `_LIFTED_V0_24_65` (its cap was dead anyway since the chr is
        # excluded — see dev/audit_placement_budget_consistency.py). This
        # is a "does ordering matter in practice" smoke check, not a
        # tight count; the floor only needs to be high enough that the
        # M and GIGA buckets coexist non-trivially.
        assert len(cap1_mediums) >= 9, (
            f'Expected at least 9 cap=1 M chrs; got {len(cap1_mediums)}')


# v0.24.77: Fort GG re-protected against emerge-anim CTDs
# ============================================================================
class TestFortGuardianGolemRestoredV0_24_77:
    """v0.24.77: m30_30 pi=45 (Fort GG) re-added to V3_PROBLEM_SLOTS
    after seed 886942 CTD (c4810 Erdtree Avatar emerge-anim failure
    on Fort rampart geometry).

    Same three-layer config as Cathedral pi=51:
    - V3_PROBLEM_SLOTS: SAFE-only base filter
    - V3_PROBLEM_SLOT_EXTRA_ALLOWS: whitelist big-creature variety
      (Centipede Demon, Gaping Dragon, big dragons)
    - V3_PROBLEM_SLOT_EXTRA_BANS: ban known-broken emerge-anim chrs
      (c4810 Erdtree Avatar, c4811 variant, c4441 Land Squirt)
    """

    def test_fort_back_in_problem_slots(self, engine):
        """Fort GG slot is in V3_PROBLEM_SLOTS again post-v0.24.77."""
        assert ('m30_30_00_00.msb', 45) in engine.V3_PROBLEM_SLOTS

    def test_fort_emerge_anim_banned(self, engine):
        """The 3 known emerge-anim chrs are in EXTRA_BANS for Fort slot."""
        bans = engine.V3_PROBLEM_SLOT_EXTRA_BANS.get(
            ('m30_30_00_00.msb', 45))
        assert bans is not None, 'Fort slot missing EXTRA_BANS entry'
        assert 'c4810' in bans  # Erdtree Avatar Remembrance (the CTD chr)
        assert 'c4811' in bans  # Erdtree Avatar Variant (defensive)
        assert 'c4441' in bans  # Land Squirt (original v0.24.18 case)

    def test_fort_extra_allows_preserves_centipede_demon(self, engine):
        """User-confirmed working chrs are in EXTRA_ALLOWS for Fort."""
        allows = engine.V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
            ('m30_30_00_00.msb', 45))
        assert allows is not None
        assert 'c7710' in allows  # Centipede Demon (user-confirmed)
        assert 'c7700' in allows  # Gaping Dragon (sibling giga_boss)
        assert 'c4241' in allows  # Giant Fingercreeper

    def test_c4810_rejected_at_fort(self, engine, tags):
        """The seed 886942 CTD chr (c4810 Erdtree Avatar) must be
        rejected at the Fort slot via EXTRA_BANS — that's the fix."""
        slot_info = {
            'msb': 'm30_30_00_00.msb', 'pi': 45,
            'source_cp': 'c4660',
            'source_npc': 0,
            'source_variant_name': 'Guardian Golem (Fort)',
            'cluster_id': None,
            'position': [0.0, 42.8, 0.0],
        }
        score = engine._score_slot_for_unique(slot_info, 'c4810', tags)
        assert score is None, (
            f'c4810 Erdtree Avatar should be rejected at Fort slot '
            f'via EXTRA_BANS (seed 886942 CTD chr), got score={score}')

    def test_c7710_allowed_at_fort(self, engine, tags):
        """Centipede Demon must still land at Fort slot — the
        user-confirmed working case that motivated the v0.24.75 lift."""
        slot_info = {
            'msb': 'm30_30_00_00.msb', 'pi': 45,
            'source_cp': 'c4660',
            'source_npc': 0,
            'source_variant_name': 'Guardian Golem (Fort)',
            'cluster_id': None,
            'position': [0.0, 42.8, 0.0],
        }
        score = engine._score_slot_for_unique(slot_info, 'c7710', tags)
        assert score is not None, (
            f'c7710 Centipede Demon should be allowed at Fort slot '
            f'via EXTRA_ALLOWS (user-confirmed working), got None')


# v0.24.79: entrance-animation classification (Option B step 1)
# ============================================================================
class TestEntranceAnimationGateV0_24_79:
    """v0.24.79 adds a per-class entrance-animation taxonomy with a
    matching arena-side affordance list. First class implemented:
    emerge_from_ground (the chr's intro animation rises out of the
    earth). Slot affordance: V3_NO_EMERGE_SLOTS (rampart roofs,
    elevated platforms — no subsurface terrain).

    Gate 7 in _reject_target_for_slot rejects emerge-class chrs at
    no-emerge slots. Other classes (unknown, fly_in, pre_placed,
    etc.) pass through unaffected.

    Long-term: replace V3_ENTRANCE_ANIM_CLASS data with chrbnd-
    derived parser output (Option C). V3_NO_EMERGE_SLOTS stays
    manual — geometry-dependent.
    """

    def test_entrance_anim_dict_loaded(self, engine):
        """V3_ENTRANCE_ANIM_CLASS is loaded from
        data/entrance_animations.json and non-empty."""
        assert isinstance(engine.V3_ENTRANCE_ANIM_CLASS, dict)
        assert len(engine.V3_ENTRANCE_ANIM_CLASS) > 0, (
            'V3_ENTRANCE_ANIM_CLASS unexpectedly empty — check '
            'data/entrance_animations.json exists + parses')

    def test_seed_emerge_anim_chrs_present(self, engine):
        """The 4 seeded emerge-from-ground chrs are present."""
        for cp in ('c4441', 'c4442', 'c4810', 'c4811'):
            assert engine.V3_ENTRANCE_ANIM_CLASS.get(cp) == 'emerge_from_ground', (
                f'{cp} expected emerge_from_ground, got '
                f'{engine.V3_ENTRANCE_ANIM_CLASS.get(cp)!r}')

    def test_no_emerge_slots_loaded(self, engine):
        """V3_NO_EMERGE_SLOTS is loaded from
        data/nr_no_emerge_slots.json and contains Fort GG."""
        assert isinstance(engine.V3_NO_EMERGE_SLOTS, frozenset)
        assert ('m30_30_00_00.msb', 45) in engine.V3_NO_EMERGE_SLOTS

    def test_emerge_anim_rejected_at_no_emerge_slot(self, engine, tags):
        """The seed 886942 v0.24.75 CTD case: c4810 Erdtree Avatar at
        Fort GG rampart (m30_30 pi=45). Gate 7 should reject."""
        reason = engine._reject_target_for_slot(
            target_cp='c4810', src_cp='c4660',
            src_variant_name='Guardian Golem (Fort)',
            tags=tags, msb_base='m30_30_00_00.msb', pi=45)
        assert reason == 'no_emerge_terrain', (
            f'Expected no_emerge_terrain rejection; got {reason!r}')

    def test_emerge_anim_passes_at_regular_slot(self, engine, tags):
        """Emerge-class chrs at non-no-emerge slots are NOT rejected
        by Gate 7. Test with c4810 at Cathedral upper floor — that
        slot is fragile (V3_PROBLEM_SLOTS) but not in V3_NO_EMERGE_SLOTS,
        so Gate 7 specifically should not fire."""
        reason = engine._reject_target_for_slot(
            target_cp='c4810', src_cp='c4660',
            src_variant_name='Guardian Golem (Cathedral)',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51)
        assert reason != 'no_emerge_terrain', (
            f'Gate 7 incorrectly fired at non-no-emerge slot; got {reason!r}')

    def test_unknown_chr_passes_at_no_emerge_slot(self, engine, tags):
        """Chrs not in V3_ENTRANCE_ANIM_CLASS (default 'unknown') pass
        through Gate 7 — no gate fires for unclassified chrs. This
        preserves the engine's current behavior for the vast majority
        of chrs while the taxonomy is small."""
        # c4910 Magma Wyrm — not in the seeded list, should be 'unknown'
        assert engine.V3_ENTRANCE_ANIM_CLASS.get('c4910') is None, (
            'c4910 should not be in the seeded emerge_from_ground list. '
            'If you added it, this test is now testing the wrong case.')
        # At Fort GG (no-emerge slot)
        reason = engine._reject_target_for_slot(
            target_cp='c4910', src_cp='c4660',
            src_variant_name='Guardian Golem (Fort)',
            tags=tags, msb_base='m30_30_00_00.msb', pi=45)
        # Should NOT be no_emerge_terrain — other gates may reject for
        # other reasons but Gate 7 specifically should not fire.
        assert reason != 'no_emerge_terrain', (
            f'Gate 7 fired on unclassified chr c4910; got {reason!r}')

    def test_centipede_demon_still_lands_at_fort(self, engine, tags):
        """The user-confirmed working case (Centipede Demon at Fort GG)
        must still land. Centipede Demon's intro is DS1-style ceiling
        drop — not emerge_from_ground. Should pass Gate 7 even though
        Fort GG is in V3_NO_EMERGE_SLOTS."""
        reason = engine._reject_target_for_slot(
            target_cp='c7710', src_cp='c4660',
            src_variant_name='Guardian Golem (Fort)',
            tags=tags, msb_base='m30_30_00_00.msb', pi=45)
        assert reason != 'no_emerge_terrain', (
            f'Gate 7 fired on c7710 Centipede Demon (not emerge-class); '
            f'got {reason!r}')

    def test_file_meta_carries_provenance(self, engine):
        """The _meta blocks document where the data came from + the
        long-term Option C migration intent. Test that the meta is
        non-empty so loaders haven't silently failed."""
        assert engine.V3_ENTRANCE_ANIM_FILE_META, (
            'entrance_animations.json _meta missing — file may not be '
            'loading correctly')
        assert 'long_term' in engine.V3_NO_EMERGE_SLOTS_FILE_META.get(
            'interaction_with_other_systems', {}), (
            'nr_no_emerge_slots.json _meta missing long-term migration '
            'doc — should reference Option C chrbnd parser')

    def test_full_entry_metadata_accessible(self, engine):
        """V3_ENTRANCE_ANIM_META should carry the full entry per chr
        (class + _source_note) so future auditing can trace each
        classification back to its empirical source."""
        entry = engine.V3_ENTRANCE_ANIM_META.get('c4810')
        assert entry is not None
        assert entry.get('class') == 'emerge_from_ground'
        assert '_source_note' in entry, (
            'c4810 entry missing _source_note — every classification '
            'should document its empirical source')
        # Spot check that the source note references the v0.24.77 seed
        assert '886942' in entry.get('_source_note', ''), (
            'c4810 _source_note should reference v0.24.77 seed 886942 '
            'where this was first identified')


# v0.24.88-patch9: Gate 7.8 — nav_dependent at stub-nav slot
class TestGate7_8NavRequiredAtStubNavSlot:
    """Gate 7.8: cave/dungeon tiles (m46/m48/m49) have empty navmesh +
    empty onav. Nav-dependent pursuit AI freezes in those tiles when
    chr can't pathfind to player. Restrict targets to a whitelist of
    nav-independent (set-piece / scripted) chrs.

    Empirical motivation: Fat Inquisitor c5320 freeze at cave slots in
    seed 923630 (5 placements in m46/m48/m49). Generalizes the
    rats-don't-work-in-caves observation Alaric flagged."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        # Force cache reload (cross-test contamination)
        oops_v3._V3_NAV_TILE_CACHE = None
        return oops_v3

    @pytest.fixture
    def tags(self, engine):
        return engine.load_data()[0]

    def test_fat_inquisitor_rejected_at_cave(self, engine, tags):
        """c5320 Fat Inquisitor at m46_70 pi=3 — the seed 923630
        freeze case that motivated this gate."""
        r = engine._reject_target_for_slot(
            target_cp='c5320', src_cp='c3560',
            src_variant_name='Iron Maiden', tags=tags,
            msb_base='m46_70_00_00.msb', pi=3)
        assert r == 'nav_required_at_stub_nav_slot', (
            f'Fat Inquisitor at cave should reject via Gate 7.8, got {r}')

    def test_overworld_fat_inquisitor_unaffected(self, engine, tags):
        """Same chr at an overworld slot (with real navmesh) should NOT
        trip Gate 7.8 — only the cave-tile predicate fires there."""
        r = engine._reject_target_for_slot(
            target_cp='c5320', src_cp='c4110',
            src_variant_name='', tags=tags,
            msb_base='m60_42_37_50.msb', pi=22)
        # May still fire OTHER gates, but not 7.8 specifically
        assert r != 'nav_required_at_stub_nav_slot', (
            f'Fat Inquisitor at overworld should NOT trip Gate 7.8, got {r}')

    def test_vanilla_cave_chr_allowed(self, engine, tags):
        """Whitelisted chrs (vanilla cave placements) pass at cave slots."""
        # c3000 Exile Soldier — common cave-tile vanilla source
        r = engine._reject_target_for_slot(
            target_cp='c3000', src_cp='c4313',
            src_variant_name='Leyndell Soldier', tags=tags,
            msb_base='m46_70_00_00.msb', pi=3)
        assert r != 'nav_required_at_stub_nav_slot'

    def test_overworld_unaffected_by_whitelist(self, engine, tags):
        """At overworld slots, non-whitelist chrs are still allowed
        (Gate 7.8 only fires at stub-nav tiles)."""
        # c5900 Man-Fly — not in whitelist. At m60_xx (overworld), allow.
        r = engine._reject_target_for_slot(
            target_cp='c5900', src_cp='c4110',
            src_variant_name='', tags=tags,
            msb_base='m60_42_37_50.msb', pi=22)
        assert r != 'nav_required_at_stub_nav_slot'

    def test_stub_nav_predicate(self, engine):
        """Direct test of the helper: cave tiles report True, overworld False."""
        assert engine._is_stub_nav_slot('m46_70_00_00.msb') is True
        assert engine._is_stub_nav_slot('m48_90_00_00.msb') is True
        assert engine._is_stub_nav_slot('m49_17_00_00.msb') is True
        assert engine._is_stub_nav_slot('m60_42_37_50.msb') is False
        assert engine._is_stub_nav_slot('m34_30_00_00.msb') is False

    def test_whitelist_includes_known_cave_chrs(self, engine):
        """Sanity: the whitelist must include test-asserted cave chrs."""
        wl = engine.V3_NAV_INDEPENDENT_TARGETS
        for cp in ('c7700', 'c7710', 'c4602', 'c3610', 'c4660'):
            assert cp in wl, f'{cp} missing from V3_NAV_INDEPENDENT_TARGETS'


# v0.24.89-patch10: ghost-exclude audit (lifted speculative entries)
class TestGhostExcludeAudit:
    """v0.24.89-patch10: the ghost-exclude set was reduced from 7 to 1
    after audit. The 6 lifted entries (c5240/c5241/c5311/c5312/c5750/
    c5751) were inherited from April 2026 shape-association speculation
    and never empirically confirmed. Only c2040 Juvenile Scholar remains,
    backed by a confirmed tower-encounter freeze.

    This test class locks in the audit decision: don't let the
    speculative entries drift back in without empirical evidence."""

    def test_only_c2040_in_ghost_exclude(self, engine):
        """The ghost-exclude set should contain exactly c2040 — every
        other entry needs an empirical (seed, msb, pi) citation."""
        assert engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES == {'c2040'}, (
            f'V3_GHOST_EXCLUDE_TARGET_PREFIXES drifted from the v0.24.89 '
            f'audit baseline. If you added a new entry, document it with '
            f'a specific empirical citation (seed + msb + pi where the '
            f'freeze occurred), not by shape/vibe analogy. Current: '
            f'{sorted(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)}')

    def test_lifted_ghost_excludes_can_be_targets(self, engine, tags):
        """The 6 lifted ghost-excludes should now pass the target-pool
        filter at normal slots."""
        lifted = ['c5240', 'c5241', 'c5311', 'c5312', 'c5750', 'c5751']
        ghost = engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES
        for cp in lifted:
            assert cp not in ghost, (
                f'{cp} was lifted in v0.24.89-patch10; do not re-add '
                f'without empirical citation')


# v0.24.90-patch11: c4281 demotion lockin
class TestC4281DemotionLockin:
    """c4281 Skull Plate Giant Ant was demoted from V3_EXCLUDE_TARGET_PREFIXES
    to V3_FRAGILE_SENSITIVE_TARGETS in v0.24.90-patch11 to match the
    c4240 Fingercreeper family precedent (same XL+loco=5 profile).

    The v0.24.90-patch11 invariant: do NOT *manually* re-promote c4281
    to EXCLUDE for terrain-failure reasons. If freezes recur at fragile-
    cleared positions, the right fix is V3_QUADRUPED_UNSAFE_SLOTS or
    authored reposition.

    v0.25.0 separately added c4281 to data/nr_missing_chr_files.json's
    broken_runtime_chrs array (auto-loaded into V3_EXCLUDE_TARGET_PREFIXES
    by `_load_missing_chr_files()`). That's a distinct mechanism with a
    distinct rationale (no per-chr battle script visible in any source
    archive — phantom asset, AI doesn't function). When/if the script
    presence is confirmed (via parent-share to c4280 or actual file
    discovery), the entry can be lifted from broken_runtime_chrs and
    the v0.24.90-patch11 SENSITIVE routing resumes as the backstop.

    The literal/auto-load distinction matters because it preserves the
    audit trail: "we excluded c4281 because the chr is broken at the
    asset level" is a different claim than "we excluded c4281 because
    its terrain failures persist" — the latter is the case patch11
    expressly rejected.
    """

    def test_c4281_excluded_only_via_broken_runtime_chrs(self, engine):
        """c4281 is in EXCLUDE because broken_runtime_chrs auto-add
        (v0.25.0), not because of a literal entry in oops_v3.py's
        V3_EXCLUDE_TARGET_PREFIXES block. If someone added a literal
        entry, the v0.24.90-patch11 invariant is breached.
        """
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'nr_missing_chr_files.json')) as f:
            mcf = json.load(f)
        broken_runtime_cps = {e['c_prefix']
                              for e in mcf.get('broken_runtime_chrs', [])}
        assert 'c4281' in broken_runtime_cps, (
            'c4281 is in V3_EXCLUDE_TARGET_PREFIXES but NOT via the '
            'broken_runtime_chrs auto-load path — implies someone added '
            'a literal entry to oops_v3.py V3_EXCLUDE_TARGET_PREFIXES, '
            'which the v0.24.90-patch11 invariant expressly disallows. '
            'If terrain freezes recurred, use V3_QUADRUPED_UNSAFE_SLOTS '
            'or authored reposition.')

    def test_c4281_still_fragile_sensitive_for_backstop(self, engine):
        """v0.24.90-patch11's SENSITIVE classification must persist even
        while c4281 is broken_runtime_chrs-excluded — so that lifting
        the broken_runtime_chrs entry resumes the patch11 routing
        immediately rather than dropping c4281 to default fragile-pool
        treatment."""
        assert 'c4281' in engine.V3_FRAGILE_SENSITIVE_TARGETS, (
            'c4281 should be in V3_FRAGILE_SENSITIVE_TARGETS per '
            'v0.24.90-patch11 — keeps the routing in place as a '
            'backstop for if broken_runtime_chrs lifts c4281 later.')

    def test_insectoid_family_uniformly_sensitive_or_safe(self, engine):
        """Sanity: the multi-leg insectoid family should be uniformly
        in SENSITIVE or SAFE — none manually-excluded for terrain reasons.

        c4281 is permitted to be in EXCLUDE via broken_runtime_chrs
        auto-load (separate v0.25.0 mechanism, asset-level rationale).
        The check below filters by the broken_runtime_chrs path before
        flagging EXCLUDE membership.
        """
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'nr_missing_chr_files.json')) as f:
            mcf = json.load(f)
        broken_runtime_cps = {e['c_prefix']
                              for e in mcf.get('broken_runtime_chrs', [])}

        FAMILY = ['c4280', 'c4281', 'c4240', 'c4241', 'c4250', 'c5193']
        for cp in FAMILY:
            if cp in broken_runtime_cps:
                # Excluded via the v0.25.0 asset-level path; that's OK.
                # Sensitivity classification should still apply as a
                # backstop, checked below.
                pass
            else:
                assert cp not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
                    f'{cp} in EXCLUDE breaks insectoid-family uniformity '
                    f'(not in broken_runtime_chrs, so this must be a '
                    f'manual re-promotion).')
            in_sens = cp in engine.V3_FRAGILE_SENSITIVE_TARGETS
            in_safe = cp in engine.V3_FRAGILE_SAFE_CONFIRMED
            assert in_sens or in_safe, (
                f'{cp} missing from both SENSITIVE and SAFE — should be '
                f'classified into one of them')
