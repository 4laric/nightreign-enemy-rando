"""Tests for gates threading into pick_target_cp / pick_target.

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
            # Gate 7 (geometry-aware size gate)
            'geometry_clip',
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
        # Structural check: the scorer must call the predicate. If
        # the scorer ever stops using the predicate, the v0.24.27
        # mirror bug recurs — catch it here.
        #
        # v0.28.x: the scorer body has been folded into
        # engine.rejection.score_slot_for_unique. The shim in
        # oops_v3 doesn't itself reference the predicate; check the
        # engine module where the real body lives.
        import inspect
        from engine import rejection
        src = inspect.getsource(rejection.score_slot_for_unique)
        assert 'reject_target_for_slot' in src, (
            'engine.rejection.score_slot_for_unique no longer calls '
            'reject_target_for_slot — v0.24.27 refactor regressed; '
            'mirror semantics broken')

    def test_picker_uses_predicate(self, engine):
        # Same structural check on pick_target_cp.
        # v0.28.x: the picker body has been extracted to
        # engine.picker.pick_target_cp; the shim in oops_v3 delegates
        # but doesn't itself reference the predicate. Check the
        # engine module where the real body lives.
        import inspect
        from engine import picker
        src = inspect.getsource(picker.pick_target_cp)
        assert 'reject_target_for_slot' in src, (
            'engine.picker.pick_target_cp no longer calls '
            'reject_target_for_slot — v0.24.27 refactor regressed')
