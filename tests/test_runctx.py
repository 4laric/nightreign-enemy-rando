"""Tests for engine.runctx.RunContext and the explicit-run_ctx code
path on the functions that consume it.

RunContext encapsulates per-run mutable bookkeeping:
  - unique_reservations  ((msb, pi) -> cp)
  - unique_placed_counts (cp -> count)
  - unique_unplaced_log  (list of failure-log dicts)

The Phase 4 parity test caught a divergence caused by pick_target_cp
mutating _V3_UNIQUE_PLACED_COUNTS across calls. The fix in test code
was a manual save/restore. Now, with RunContext, the same test can
just pass run_ctx=RunContext.fresh() per call — no boilerplate.

This module proves:
  1. RunContext construction / mutation semantics work as advertised
  2. pick_target_cp's three runtime-state references all route
     through run_ctx when provided
  3. _compute_unique_reservations writes go to run_ctx instead of
     module dicts when provided
  4. Test isolation: parity test that previously needed save/restore
     of module state now needs only RunContext.fresh()
"""
import inspect
import random

import pytest

import oops_v3
from engine.runctx import RunContext
from engine.state import GateState


# ---------------------------------------------------------------------------
# RunContext construction and semantics
# ---------------------------------------------------------------------------

class TestRunContextConstruction:
    def test_fresh_has_empty_state(self):
        rc = RunContext.fresh()
        assert rc.unique_reservations == {}
        assert rc.unique_placed_counts == {}
        assert rc.unique_unplaced_log == []

    def test_fresh_returns_distinct_instances(self):
        # Each fresh() call returns a new mutable container — a test
        # mutating one shouldn't affect another. Catches the "default
        # mutable argument" footgun if someone ever changes the
        # dataclass field defaults.
        a = RunContext.fresh()
        b = RunContext.fresh()
        a.unique_reservations[('m_test', 0)] = 'cTEST'
        assert b.unique_reservations == {}

    def test_from_module_snapshots_live_state(self, engine):
        # engine fixture has triggered load_data() at minimum. Module
        # state may not have reservations populated unless a run has
        # happened, but the snapshot should still mirror whatever is
        # there.
        rc = RunContext.from_module(engine)
        assert rc.unique_reservations == dict(engine._V3_UNIQUE_RESERVATIONS)
        assert rc.unique_placed_counts == dict(engine._V3_UNIQUE_PLACED_COUNTS)
        assert rc.unique_unplaced_log == list(engine._V3_UNIQUE_UNPLACED_LOG)

    def test_from_module_isolated_from_subsequent_mutation(
            self, engine, monkeypatch):
        # Snapshot captures the dict contents. Later mutating module
        # state must not change the snapshot. Mirrors the GateState
        # isolation property.
        rc = RunContext.from_module(engine)
        # Mutate the live module dict.
        monkeypatch.setattr(
            engine, '_V3_UNIQUE_PLACED_COUNTS',
            {**engine._V3_UNIQUE_PLACED_COUNTS, 'cFAKE_TEST_999': 42})
        # Snapshot unchanged.
        assert 'cFAKE_TEST_999' not in rc.unique_placed_counts


class TestRunContextMutation:
    def test_bump_unique_increments(self):
        rc = RunContext.fresh()
        rc.bump_unique('c4500')
        assert rc.unique_placed_counts['c4500'] == 1
        rc.bump_unique('c4500')
        assert rc.unique_placed_counts['c4500'] == 2
        rc.bump_unique('c2130')
        assert rc.unique_placed_counts['c2130'] == 1
        assert rc.unique_placed_counts['c4500'] == 2

    def test_reserve_and_get(self):
        rc = RunContext.fresh()
        rc.reserve('m_test.msb', 5, 'c4500')
        assert rc.get_reservation('m_test.msb', 5) == 'c4500'
        # Different slot returns None.
        assert rc.get_reservation('m_test.msb', 6) is None
        # Different msb returns None.
        assert rc.get_reservation('m_other.msb', 5) is None

    def test_get_reservation_with_none_args(self):
        # Mirrors the guard in pick_target_cp line ~8721.
        rc = RunContext.fresh()
        rc.reserve('m_test.msb', 5, 'c4500')
        assert rc.get_reservation(None, 5) is None
        assert rc.get_reservation('m_test.msb', None) is None
        assert rc.get_reservation(None, None) is None

    def test_is_exhausted(self):
        rc = RunContext.fresh()
        rc.bump_unique('c4500')
        assert rc.is_exhausted('c4500', 1) is True
        assert rc.is_exhausted('c4500', 2) is False
        # Never-placed cp at cap > 0: not exhausted.
        assert rc.is_exhausted('c2130', 1) is False
        # Never-placed cp at cap = 0: exhausted (degenerate but valid).
        assert rc.is_exhausted('c2130', 0) is True

    def test_reset_clears_all_state(self):
        rc = RunContext.fresh()
        rc.bump_unique('c4500')
        rc.reserve('m_test.msb', 0, 'c2130')
        rc.unique_unplaced_log.append({'cp': 'c4910'})
        rc.reset()
        assert rc.unique_reservations == {}
        assert rc.unique_placed_counts == {}
        assert rc.unique_unplaced_log == []


# ---------------------------------------------------------------------------
# Signature checks — every function in the chain accepts run_ctx
# ---------------------------------------------------------------------------

class TestRunCtxSignatures:
    """Each function in the threading chain should accept run_ctx=None."""

    @pytest.mark.parametrize('fn_name', [
        'pick_target_cp', 'pick_target',
        'shuffle_msb_v3', '_cmd_shuffle_v3_impl',
        '_compute_unique_reservations',
    ])
    def test_function_accepts_run_ctx(self, fn_name):
        fn = getattr(oops_v3, fn_name)
        sig = inspect.signature(fn)
        assert 'run_ctx' in sig.parameters, f'{fn_name} missing run_ctx kwarg'
        assert sig.parameters['run_ctx'].default is None


# ---------------------------------------------------------------------------
# pick_target_cp uses run_ctx for all three read/write sites
# ---------------------------------------------------------------------------

class TestPickTargetCpRunCtxThreading:
    """Three things pick_target_cp does with runtime state:
      1. Read unique_reservations for early-return at slot match
      2. Read unique_placed_counts for cap-exhausted exclusion
      3. Write unique_placed_counts after picking a capped cp organically
    """

    def test_run_ctx_reservation_triggers_early_return(
            self, engine, tags, prefix_variants, prefix_count):
        # Plant a reservation in run_ctx, call pick_target_cp with
        # matching slot, verify the reserved cp comes back regardless
        # of compat/tier (the early-return bypasses those).
        rc = RunContext.fresh()
        rc.reserve('m_test.msb', 7, 'c2130')

        # Recipient + slot combination that would NOT normally pick
        # c2130. The reservation forces it.
        result = oops_v3.pick_target_cp(
            'c4170', tags, prefix_variants, prefix_count,
            recipient_is_boss=False,
            rng=random.Random(0),
            slot_msb_name='m_test.msb', slot_pi=7,
            run_ctx=rc)
        assert result == 'c2130'

    def test_run_ctx_exhausted_set_excludes_capped_cps(
            self, engine, tags, prefix_variants, prefix_count):
        # If unique_placed_counts says a cp hit its cap, the cp must
        # not appear in 30 trials. Use a cp with a real V3_UNIQUE_TARGET_CAPS
        # entry so the exhausted-set logic actually fires.
        if not oops_v3.V3_UNIQUE_TARGET_CAPS:
            pytest.skip('V3_UNIQUE_TARGET_CAPS is empty')
        capped_cp = next(iter(oops_v3.V3_UNIQUE_TARGET_CAPS))
        cap = oops_v3.V3_UNIQUE_TARGET_CAPS[capped_cp]

        rc = RunContext.fresh()
        rc.unique_placed_counts[capped_cp] = cap  # at the cap

        recipient = 'c4170'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        for seed in range(30):
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, random.Random(seed),
                slot_variant_name='Test (Field Boss)',
                run_ctx=rc)
            assert result != capped_cp, (
                f'seed {seed}: capped {capped_cp} (n={cap}) should be '
                f'exhausted but was picked')

    def test_run_ctx_counter_bumped_after_capped_pick(
            self, engine, tags, prefix_variants, prefix_count):
        # When pick_target_cp picks an organic cp that's in
        # V3_UNIQUE_TARGET_CAPS, it should bump the counter on
        # run_ctx, NOT on the module dict.
        if not oops_v3.V3_UNIQUE_TARGET_CAPS:
            pytest.skip('V3_UNIQUE_TARGET_CAPS is empty')
        capped_cp = next(iter(oops_v3.V3_UNIQUE_TARGET_CAPS))

        rc = RunContext.fresh()
        recipient = 'c4170'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        # Snapshot module counter before
        module_before = dict(engine._V3_UNIQUE_PLACED_COUNTS)

        # Force the pick by planting a reservation. The early-return
        # path bypasses bump (per the docstring), so this doesn't
        # actually test what we want. Use the organic path: roll many
        # seeds until we land on capped_cp organically. If we never
        # land on it, the test is uninformative — skip.
        landed_seed = None
        for seed in range(100):
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, random.Random(seed),
                slot_variant_name='Test (Field Boss)',
                run_ctx=RunContext.fresh())  # fresh per trial
            if result == capped_cp:
                landed_seed = seed
                break
        if landed_seed is None:
            pytest.skip(f'No seed in [0..99] landed on {capped_cp}; '
                        f'cannot test organic-pick bump')

        # Reproduce the landing with a non-fresh RunContext to capture the bump.
        rc = RunContext.fresh()
        result = oops_v3.pick_target_cp(
            recipient, tags, prefix_variants, prefix_count,
            recipient_is_boss, random.Random(landed_seed),
            slot_variant_name='Test (Field Boss)',
            run_ctx=rc)
        assert result == capped_cp
        # Counter bumped on rc, not on module.
        assert rc.unique_placed_counts.get(capped_cp) == 1
        assert engine._V3_UNIQUE_PLACED_COUNTS == module_before, (
            'pick_target_cp leaked a bump into module state despite run_ctx')


# ---------------------------------------------------------------------------
# Demonstration: parity test no longer needs save/restore
# ---------------------------------------------------------------------------

class TestParityViaRunCtx:
    """The Phase 4 parity test surfaced that pick_target_cp mutates
    _V3_UNIQUE_PLACED_COUNTS. Tests had to save/restore module state.
    With RunContext, the same test works without save/restore — each
    branch just gets its own fresh RunContext.

    This is the practical demonstration of why RunContext earns its
    keep. If this test passes without manual state management, the
    abstraction is doing real work.
    """

    @pytest.mark.parametrize('recipient_cp', ['c4500', 'c2130', 'c4170'])
    @pytest.mark.parametrize('slot_variant_name',
                              ['Test (Field Boss)', 'Test (Night Boss)', None])
    def test_parity_without_save_restore(
            self, engine, tags, prefix_variants, prefix_count,
            recipient_cp, slot_variant_name):
        if recipient_cp not in tags:
            pytest.skip(f'{recipient_cp} not in tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient_cp, tags, prefix_variants)
        snapshot = GateState.from_module(engine)

        # Two calls, both with FRESH RunContext — no state pollution
        # between them. No save/restore needed.
        result_module = oops_v3.pick_target_cp(
            recipient_cp, tags, prefix_variants, prefix_count,
            recipient_is_boss, random.Random(42),
            slot_variant_name=slot_variant_name,
            run_ctx=RunContext.fresh())
        result_gates = oops_v3.pick_target_cp(
            recipient_cp, tags, prefix_variants, prefix_count,
            recipient_is_boss, random.Random(42),
            slot_variant_name=slot_variant_name,
            gates=snapshot,
            run_ctx=RunContext.fresh())
        assert result_module == result_gates


# ---------------------------------------------------------------------------
# _compute_unique_reservations writes to run_ctx when provided
# ---------------------------------------------------------------------------

class TestComputeUniqueReservationsRunCtx:
    """The pre-pass mutates 3 module dicts when run_ctx=None, and 3
    fields of run_ctx when explicit. Verify the writes route correctly.
    """

    def test_run_ctx_path_does_not_mutate_module_dicts(
            self, engine, tmp_path):
        # Snapshot module state before the call.
        module_reservations_before = dict(engine._V3_UNIQUE_RESERVATIONS)
        module_counts_before = dict(engine._V3_UNIQUE_PLACED_COUNTS)
        module_log_before = list(engine._V3_UNIQUE_UNPLACED_LOG)

        # Run the pre-pass with explicit run_ctx. The input_dir doesn't
        # need real MSBs — for a directory with no MSBs, the pre-pass
        # logs "no_qualifying_slots" for every capped cp but doesn't
        # crash. Sufficient to exercise the write paths.
        rc = RunContext.fresh()
        empty_dir = tmp_path / 'empty_input'
        empty_dir.mkdir()

        # Suppress prints
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            engine._compute_unique_reservations(
                str(empty_dir), {}, {}, random.Random(0),
                run_ctx=rc)

        # Module state untouched.
        assert dict(engine._V3_UNIQUE_RESERVATIONS) == module_reservations_before
        assert dict(engine._V3_UNIQUE_PLACED_COUNTS) == module_counts_before
        assert list(engine._V3_UNIQUE_UNPLACED_LOG) == module_log_before

        # RunContext got the unplaced-log entries (no_qualifying_slots
        # for every entry in V3_UNIQUE_TARGET_CAPS, since the empty dir
        # has no MSBs to score).
        if oops_v3.V3_UNIQUE_TARGET_CAPS:
            assert len(rc.unique_unplaced_log) > 0
            for entry in rc.unique_unplaced_log:
                assert entry['reason'] in (
                    'no_qualifying_slots',
                    'runtime_excluded (multiplayer_safe or hard-blocklist)')

    def test_run_ctx_none_path_still_mutates_module_dicts(
            self, engine, tmp_path, monkeypatch):
        # Backwards-compat: with run_ctx=None, the module dicts are
        # still the write target. Otherwise pre-Phase 5 callers break.
        empty_dir = tmp_path / 'empty_input'
        empty_dir.mkdir()

        # Start from clean module state for predictability.
        monkeypatch.setattr(engine, '_V3_UNIQUE_RESERVATIONS', {})
        monkeypatch.setattr(engine, '_V3_UNIQUE_PLACED_COUNTS', {})
        monkeypatch.setattr(engine, '_V3_UNIQUE_UNPLACED_LOG', [])

        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            engine._compute_unique_reservations(
                str(empty_dir), {}, {}, random.Random(0))

        # With caps configured, at least one log entry should land.
        if oops_v3.V3_UNIQUE_TARGET_CAPS:
            assert len(engine._V3_UNIQUE_UNPLACED_LOG) > 0


# ---------------------------------------------------------------------------
# End-to-end: cmd_shuffle_v3 threads run_ctx into _cmd_shuffle_v3_impl
# ---------------------------------------------------------------------------

class TestEndToEndRunCtxThreading:
    def test_cmd_shuffle_v3_can_thread_run_ctx_to_impl(self, engine):
        # The wiring: cmd_shuffle_v3 → _cmd_shuffle_v3_impl always has a
        # run_ctx kwarg in the impl's signature, even if the public
        # wrapper doesn't forward an explicit one. The impl is
        # responsible for constructing a fresh RunContext when
        # run_ctx=None (Phase 5.5 flip — see test_cmd_shuffle_v3_*
        # tests below).
        captured = {}

        def fake_impl(*args, **kwargs):
            captured['run_ctx_param_present'] = 'run_ctx' in kwargs
            return 'fake-result'

        saved = engine._cmd_shuffle_v3_impl
        engine._cmd_shuffle_v3_impl = fake_impl
        try:
            engine.cmd_shuffle_v3(
                input_dir='/tmp/_nothing',
                output_dir='/tmp/_nothing',
                seed=1)
        finally:
            engine._cmd_shuffle_v3_impl = saved

        sig = inspect.signature(engine._cmd_shuffle_v3_impl)
        assert 'run_ctx' in sig.parameters


class TestPhase5_5_RunContextConstruction:
    """v0.24.22 Phase 5.5: _cmd_shuffle_v3_impl now constructs a fresh
    RunContext at run-start (or resets an explicitly-passed one). Module
    dicts are no longer authoritative mid-run; they get back-copied from
    run_ctx before spoiler emit.

    These tests don't run a full shuffle (that needs MSB files). They
    intercept _compute_unique_reservations to confirm it sees a
    RunContext instance — the smallest observable signal that the flip
    is wired up correctly. Full shuffle behavior is covered by the
    existing parity tests in test_pick_target.py (which all pass).
    """

    def _make_minimal_run_env(self, tmp_path):
        """Build the smallest input dir _cmd_shuffle_v3_impl will accept.
        It needs an os.makedirs-able output and an os.listdir-able input
        with at least zero .msb files."""
        in_dir = tmp_path / 'in'
        out_dir = tmp_path / 'out'
        in_dir.mkdir()
        return str(in_dir), str(out_dir)

    def test_impl_constructs_run_ctx_when_none_passed(self, engine, tmp_path):
        # Intercept _compute_unique_reservations to capture what
        # run_ctx it received. Since the empty input dir means no MSBs
        # to shuffle, the reservation pass is the only place we'll see
        # the RunContext in action — except V3_UNIQUE_TARGET_CAPS
        # being non-empty is a precondition. We satisfy it by inspecting
        # whether the impl reached the reservation block at all.
        captured = {}

        def fake_compute(*args, **kwargs):
            captured['run_ctx'] = kwargs.get('run_ctx')

        saved = engine._compute_unique_reservations
        engine._compute_unique_reservations = fake_compute
        try:
            in_dir, out_dir = self._make_minimal_run_env(tmp_path)
            try:
                engine.cmd_shuffle_v3(
                    input_dir=in_dir, output_dir=out_dir, seed=1)
            except Exception:
                # The shuffle will fail downstream (no MSBs to process)
                # but the reservation pre-pass runs before that. We
                # only need to see what it got.
                pass
        finally:
            engine._compute_unique_reservations = saved

        if 'run_ctx' not in captured:
            pytest.skip('reservation pre-pass did not fire — '
                        'V3_UNIQUE_TARGET_CAPS may be empty or '
                        'oops_all_target_cp is set')
        assert captured['run_ctx'] is not None, (
            'Phase 5.5: impl should construct a RunContext when '
            'caller passes None')
        assert isinstance(captured['run_ctx'], RunContext)

    def test_impl_resets_run_ctx_when_one_passed(self, engine, tmp_path):
        # If the caller passes a RunContext (e.g. a test holding a
        # reference for assertions), the impl resets it in place
        # rather than replacing it. The reference should remain valid
        # and the same object should be threaded into the picker chain.
        pre_supplied_ctx = RunContext.fresh()
        # Plant some pre-run state so we can detect the reset.
        pre_supplied_ctx.unique_placed_counts['cMARKER'] = 99
        pre_supplied_ctx.unique_reservations[('mFAKE_MAP', 0)] = 'cMARKER'

        captured = {}

        def fake_compute(*args, **kwargs):
            captured['run_ctx'] = kwargs.get('run_ctx')

        saved = engine._compute_unique_reservations
        engine._compute_unique_reservations = fake_compute
        try:
            in_dir, out_dir = self._make_minimal_run_env(tmp_path)
            try:
                engine._cmd_shuffle_v3_impl(
                    input_dir=in_dir, output_dir=out_dir, seed=1,
                    run_ctx=pre_supplied_ctx)
            except Exception:
                pass  # downstream shuffle failure is expected
        finally:
            engine._compute_unique_reservations = saved

        if 'run_ctx' not in captured:
            pytest.skip('reservation pre-pass did not fire')
        # SAME object — caller's reference is preserved.
        assert captured['run_ctx'] is pre_supplied_ctx
        # Pre-run state was wiped by the reset.
        assert 'cMARKER' not in pre_supplied_ctx.unique_placed_counts
        assert ('mFAKE_MAP', 0) not in pre_supplied_ctx.unique_reservations


class TestPhase5_5_ModuleDictBackCopy:
    """The back-copy from run_ctx to module dicts before spoiler emit
    is the seam that keeps write_spoiler_logs working without taking a
    run_ctx parameter. Tests that the back-copy mechanism exists at the
    expected source location — if someone removes it accidentally,
    spoilers would silently lose the unique-placement summary."""

    def test_back_copy_block_present_in_impl_source(self, engine):
        # Grep test — fragile if someone refactors the function, but
        # the comment-tag is searchable so this is the cheap insurance
        # against accidental removal.
        src = inspect.getsource(engine._cmd_shuffle_v3_impl)
        assert 'Phase 5.5' in src, (
            'Phase 5.5 marker missing from _cmd_shuffle_v3_impl — '
            'the RunContext flip and/or back-copy was removed')
        assert '_V3_UNIQUE_RESERVATIONS.update' in src, (
            'back-copy from run_ctx to module dicts is missing — '
            'spoiler emit will see empty placement state')
        assert '_V3_UNIQUE_PLACED_COUNTS.update' in src
        assert '_V3_UNIQUE_UNPLACED_LOG.extend' in src
