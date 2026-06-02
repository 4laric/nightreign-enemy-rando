"""Tests for engine.runtime.apply_run_overrides.

These tests exercise the per-run override context manager without
invoking the actual picker engine. The composition rules being tested:

  - excluded_prefixes is sanitized against V3_EXCLUDE_SOURCE_PREFIXES
    before becoming V3_EXCLUDE_PREFIXES (the v0.20.5 bug fix).
  - hub_maps replaces V3_HUB_MAPS verbatim when set.
  - multiplayer_safe unions V3_MP_SAFE_BLOCKLIST into the SAVED ghost
    set (not the live one — re-application doesn't accumulate).
  - force_include_targets subtracts from BOTH V3_EXCLUDE_TARGET_PREFIXES
    and V3_GHOST_EXCLUDE_TARGET_PREFIXES.
  - force_include_targets runs AFTER multiplayer_safe so user choice
    wins over the heritage block.

And the lifecycle rules:

  - All owned fields are restored on normal exit.
  - All owned fields are restored on exception exit.
  - The restore is atomic — no partial state leaks.
  - The yielded GateState is the snapshot AFTER overrides apply.

The tests use a `module=oops_v3` invocation explicitly so they're
self-documenting. Production cmd_shuffle_v3 elides this since the
default resolves to oops_v3 anyway.
"""
import pytest

import oops_v3
from engine.runtime import apply_run_overrides
from engine.state import GateState


# ---------------------------------------------------------------------------
# Lifecycle: save/restore correctness
# ---------------------------------------------------------------------------

class TestApplyRunOverridesLifecycle:
    def test_no_overrides_yields_current_state(self, engine):
        # With no overrides, the yielded state matches the module state
        # both during and after the with-block.
        before = GateState.from_module(engine)
        with apply_run_overrides(module=engine) as effective:
            assert effective == before
        after = GateState.from_module(engine)
        assert after == before

    def test_overrides_restored_on_normal_exit(self, engine):
        # Apply every override, then verify all owned fields return
        # to their pre-call values when the with-block exits normally.
        snapshot_before = GateState.from_module(engine)
        with apply_run_overrides(
                module=engine,
                excluded_prefixes={'cAAA', 'cBBB'},
                hub_maps={'m99_99'},
                multiplayer_safe=True,
                force_include_targets={'cCCC'},
                log=lambda msg: None):  # suppress prints
            # In-scope state must differ from before.
            in_scope = GateState.from_module(engine)
            # (We don't assert on specifics here — just that something changed.
            # Composition correctness is tested below.)
            assert (in_scope.exclude_prefixes != snapshot_before.exclude_prefixes
                    or in_scope.hub_maps != snapshot_before.hub_maps
                    or in_scope.ghost_exclude_target_prefixes != snapshot_before.ghost_exclude_target_prefixes)
        # After exit: every owned field back to original.
        snapshot_after = GateState.from_module(engine)
        assert snapshot_after.exclude_prefixes == snapshot_before.exclude_prefixes
        assert snapshot_after.hub_maps == snapshot_before.hub_maps
        assert (snapshot_after.ghost_exclude_target_prefixes
                == snapshot_before.ghost_exclude_target_prefixes)
        assert (snapshot_after.exclude_target_prefixes
                == snapshot_before.exclude_target_prefixes)

    def test_overrides_restored_on_exception_exit(self, engine):
        # The atomic-restore guarantee under exception. This is the
        # whole point of using a context manager — if the engine raises
        # mid-run, we MUST NOT leave the module in a half-overridden state.
        snapshot_before = GateState.from_module(engine)
        sentinel = RuntimeError('synthetic engine failure')
        with pytest.raises(RuntimeError) as exc_info:
            with apply_run_overrides(
                    module=engine,
                    excluded_prefixes={'cAAA'},
                    hub_maps={'m99_99'},
                    multiplayer_safe=True,
                    force_include_targets={'cBBB'},
                    log=lambda msg: None):
                raise sentinel
        assert exc_info.value is sentinel
        # All owned fields restored, even though the body raised.
        snapshot_after = GateState.from_module(engine)
        assert snapshot_after.exclude_prefixes == snapshot_before.exclude_prefixes
        assert snapshot_after.hub_maps == snapshot_before.hub_maps
        assert (snapshot_after.ghost_exclude_target_prefixes
                == snapshot_before.ghost_exclude_target_prefixes)
        assert (snapshot_after.exclude_target_prefixes
                == snapshot_before.exclude_target_prefixes)

    def test_default_module_is_oops_v3(self):
        # Calling without `module=` should resolve to oops_v3 itself.
        # If this regresses, every cmd_shuffle_v3 call breaks at import.
        with apply_run_overrides(
                hub_maps={'m_default_module_test'},
                log=lambda msg: None):
            assert 'm_default_module_test' in oops_v3.V3_HUB_MAPS
        assert 'm_default_module_test' not in oops_v3.V3_HUB_MAPS


# ---------------------------------------------------------------------------
# excluded_prefixes — sanitization (the v0.20.5 bug fix)
# ---------------------------------------------------------------------------

class TestExcludedPrefixesSanitization:
    def test_source_only_entries_stripped(self, engine):
        # An entry that's in V3_EXCLUDE_SOURCE_PREFIXES must NOT end up
        # in V3_EXCLUDE_PREFIXES — that's the bug this protects against.
        # Pick a real source-only prefix from the live module.
        if not engine.V3_EXCLUDE_SOURCE_PREFIXES:
            pytest.skip('V3_EXCLUDE_SOURCE_PREFIXES is empty')
        source_only = next(iter(engine.V3_EXCLUDE_SOURCE_PREFIXES))
        with apply_run_overrides(
                module=engine,
                excluded_prefixes={source_only, 'cAAA'},
                log=lambda msg: None) as effective:
            # source-only stripped, regular passes through.
            assert source_only not in effective.exclude_prefixes
            assert 'cAAA' in effective.exclude_prefixes

    def test_sanitization_log_emitted_when_stripping_happens(self, engine):
        if not engine.V3_EXCLUDE_SOURCE_PREFIXES:
            pytest.skip('V3_EXCLUDE_SOURCE_PREFIXES is empty')
        source_only = next(iter(engine.V3_EXCLUDE_SOURCE_PREFIXES))
        logs = []
        with apply_run_overrides(
                module=engine,
                excluded_prefixes={source_only, 'cAAA'},
                log=logs.append):
            pass
        # Should have logged the sanitization with a count.
        sanitize_logs = [m for m in logs if 'Sanitized excluded_prefixes' in m]
        assert sanitize_logs, f'no sanitization log in {logs}'

    def test_no_log_when_nothing_stripped(self, engine):
        # If the input has nothing that needs sanitizing, no log line.
        logs = []
        with apply_run_overrides(
                module=engine,
                excluded_prefixes={'cAAA', 'cBBB'},
                log=logs.append):
            pass
        assert not any('Sanitized' in m for m in logs)

    def test_excluded_prefixes_none_leaves_module_default(self, engine):
        # excluded_prefixes=None must mean "don't touch V3_EXCLUDE_PREFIXES."
        before = frozenset(engine.V3_EXCLUDE_PREFIXES)
        with apply_run_overrides(
                module=engine,
                excluded_prefixes=None,
                log=lambda msg: None) as effective:
            assert effective.exclude_prefixes == before


# ---------------------------------------------------------------------------
# hub_maps
# ---------------------------------------------------------------------------

class TestHubMaps:
    def test_hub_maps_replaces_module_default(self, engine):
        with apply_run_overrides(
                module=engine,
                hub_maps={'m12_34', 'm56_78'},
                log=lambda msg: None) as effective:
            assert effective.hub_maps == frozenset({'m12_34', 'm56_78'})

    def test_hub_maps_none_leaves_module_default(self, engine):
        before = frozenset(engine.V3_HUB_MAPS)
        with apply_run_overrides(
                module=engine,
                hub_maps=None,
                log=lambda msg: None) as effective:
            assert effective.hub_maps == before


# ---------------------------------------------------------------------------
# multiplayer_safe — V3_MP_SAFE_BLOCKLIST union, "saved ghost not live"
# ---------------------------------------------------------------------------

class TestMultiplayerSafe:
    def test_mp_safe_blocklist_unioned_into_ghost(self, engine):
        # All V3_MP_SAFE_BLOCKLIST members should be present in the
        # effective ghost_exclude_target_prefixes when multiplayer_safe=True.
        with apply_run_overrides(
                module=engine,
                multiplayer_safe=True,
                log=lambda msg: None) as effective:
            assert (set(engine.V3_MP_SAFE_BLOCKLIST)
                    <= effective.ghost_exclude_target_prefixes)

    def test_pre_existing_ghost_preserved_in_union(self, engine, monkeypatch):
        # The union is "saved_ghost ∪ mp_safe_blocklist" — anything in
        # ghost before the with-block must still be there after the union.
        sentinel = 'cGHOST_SENTINEL_999'
        monkeypatch.setattr(
            engine, 'V3_GHOST_EXCLUDE_TARGET_PREFIXES',
            set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES) | {sentinel})
        with apply_run_overrides(
                module=engine,
                multiplayer_safe=True,
                log=lambda msg: None) as effective:
            assert sentinel in effective.ghost_exclude_target_prefixes

    def test_multiplayer_safe_false_does_not_union(self, engine):
        # Default off: ghost shouldn't pick up mp_safe entries.
        before_ghost = set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
        # Find an mp_safe member that wasn't already in ghost.
        novel = engine.V3_MP_SAFE_BLOCKLIST - before_ghost
        if not novel:
            pytest.skip('Every mp_safe member already in ghost — can\'t test')
        novel_cp = next(iter(novel))
        with apply_run_overrides(
                module=engine,
                multiplayer_safe=False,
                log=lambda msg: None) as effective:
            assert novel_cp not in effective.ghost_exclude_target_prefixes

    def test_multiplayer_safe_logs_count(self, engine):
        logs = []
        with apply_run_overrides(
                module=engine,
                multiplayer_safe=True,
                log=logs.append):
            pass
        mp_logs = [m for m in logs if 'Multiplayer-safe' in m]
        assert mp_logs, f'no multiplayer-safe log in {logs}'
        assert str(len(engine.V3_MP_SAFE_BLOCKLIST)) in mp_logs[0]


# ---------------------------------------------------------------------------
# force_include_targets — subtraction, ordering
# ---------------------------------------------------------------------------

class TestForceIncludeTargets:
    def test_subtracts_from_both_exclude_sets(self, engine, monkeypatch):
        # Plant a sentinel cp in both exclude sets, then force-include it.
        # It must disappear from both.
        sentinel = 'cFORCE_INCLUDE_TEST_999'
        monkeypatch.setattr(
            engine, 'V3_EXCLUDE_TARGET_PREFIXES',
            set(engine.V3_EXCLUDE_TARGET_PREFIXES) | {sentinel})
        monkeypatch.setattr(
            engine, 'V3_GHOST_EXCLUDE_TARGET_PREFIXES',
            set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES) | {sentinel})
        with apply_run_overrides(
                module=engine,
                force_include_targets={sentinel},
                log=lambda msg: None) as effective:
            assert sentinel not in effective.exclude_target_prefixes
            assert sentinel not in effective.ghost_exclude_target_prefixes

    def test_force_include_wins_over_multiplayer_safe(self, engine):
        # The critical ordering test. force_include_targets runs AFTER
        # multiplayer_safe, so a cp can be force-included even when
        # multiplayer_safe would have blocklisted it.
        #
        # Pick a real V3_MP_SAFE_BLOCKLIST member — under multiplayer_safe
        # alone, it ends up in the ghost set. Force-include it: it should
        # NOT be in the ghost set after both apply.
        if not engine.V3_MP_SAFE_BLOCKLIST:
            pytest.skip('V3_MP_SAFE_BLOCKLIST is empty')
        target = next(iter(engine.V3_MP_SAFE_BLOCKLIST))

        # Verify the baseline: multiplayer_safe alone puts it in ghost.
        with apply_run_overrides(
                module=engine,
                multiplayer_safe=True,
                log=lambda msg: None) as without_force:
            assert target in without_force.ghost_exclude_target_prefixes, (
                f'multiplayer_safe alone should ghost {target} — test setup wrong')

        # With force-include: it should NOT be ghosted.
        with apply_run_overrides(
                module=engine,
                multiplayer_safe=True,
                force_include_targets={target},
                log=lambda msg: None) as with_force:
            assert target not in with_force.ghost_exclude_target_prefixes, (
                f'force_include should override multiplayer_safe for {target}')

    def test_empty_force_include_is_noop(self, engine):
        # force_include_targets is "if truthy" — empty set / None /
        # empty list all should be no-ops.
        before = GateState.from_module(engine)
        for empty in (None, set(), [], frozenset()):
            with apply_run_overrides(
                    module=engine,
                    force_include_targets=empty,
                    log=lambda msg: None) as effective:
                assert (effective.exclude_target_prefixes
                        == before.exclude_target_prefixes)
                assert (effective.ghost_exclude_target_prefixes
                        == before.ghost_exclude_target_prefixes)

    def test_force_include_logs_with_cp_list(self, engine):
        logs = []
        with apply_run_overrides(
                module=engine,
                force_include_targets={'cAAA', 'cBBB'},
                log=logs.append):
            pass
        force_logs = [m for m in logs if 'Force-include' in m]
        assert force_logs, f'no force-include log in {logs}'
        # cps appear in sorted order in the log message.
        assert 'cAAA' in force_logs[0]
        assert 'cBBB' in force_logs[0]


# ---------------------------------------------------------------------------
# yielded GateState reflects the post-override snapshot
# ---------------------------------------------------------------------------

class TestYieldedGateState:
    def test_yielded_state_reflects_overrides(self, engine):
        # The whole point of yielding the GateState is to give the
        # caller a single object that describes "what does the run see."
        # That object must reflect overrides, not pre-override state.
        with apply_run_overrides(
                module=engine,
                excluded_prefixes={'cAAA', 'cBBB'},
                multiplayer_safe=True,
                log=lambda msg: None) as effective:
            assert 'cAAA' in effective.exclude_prefixes
            assert 'cBBB' in effective.exclude_prefixes
            # multiplayer_safe should have unioned mp_safe_blocklist into ghost.
            assert (set(engine.V3_MP_SAFE_BLOCKLIST)
                    <= effective.ghost_exclude_target_prefixes)

    def test_yielded_state_is_immutable_snapshot(self, engine):
        # Mutating the module after the snapshot is taken should NOT
        # change the yielded GateState. (It's a frozen dataclass with
        # frozenset fields — but worth explicitly proving.)
        with apply_run_overrides(
                module=engine,
                hub_maps={'m_initial'},
                log=lambda msg: None) as effective:
            assert effective.hub_maps == frozenset({'m_initial'})
            # Mutate the module post-snapshot.
            engine.V3_HUB_MAPS = {'m_different'}
            # Snapshot unchanged.
            assert effective.hub_maps == frozenset({'m_initial'})
        # And of course we still restore correctly afterward.
        # (The mutation above will get reverted to whatever was saved.)


# ---------------------------------------------------------------------------
# Re-entry / nesting — exercises the saved-ghost-not-live invariant
# ---------------------------------------------------------------------------

class TestReentry:
    def test_nested_invocations_dont_accumulate_mp_safe(self, engine):
        # Re-applying multiplayer_safe in a nested with-block must not
        # double-union mp_safe_blocklist. The "union against saved_ghost,
        # not live_ghost" invariant is what protects this.
        before = set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
        with apply_run_overrides(
                module=engine,
                multiplayer_safe=True,
                log=lambda msg: None) as outer:
            outer_ghost = set(outer.ghost_exclude_target_prefixes)
            with apply_run_overrides(
                    module=engine,
                    multiplayer_safe=True,
                    log=lambda msg: None) as inner:
                inner_ghost = set(inner.ghost_exclude_target_prefixes)
                # Inner should equal outer — re-applying didn't add anything.
                assert inner_ghost == outer_ghost
        # After exit: back to original.
        assert set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES) == before


# ---------------------------------------------------------------------------
# v0.24.28: regression — load_data() hoist in cmd_shuffle_v3
# ---------------------------------------------------------------------------
#
# Bug shape (seed-149569, v0.24.27):
#   V3_MP_SAFE_BLOCKLIST is populated at the END of load_data(). cmd_shuffle_v3
#   entered apply_run_overrides BEFORE _cmd_shuffle_v3_impl (which is where
#   load_data ran), so the union saw an empty blocklist and silently no-op'd.
#   multiplayer_safe was effectively dead for the first cmd_shuffle_v3 call in
#   any process (i.e. every GUI run).
#
# Symptom: the diagnostic_trace's EXCLUDE_SNAPSHOT_AT_RUN_START captured
# V3_GHOST_EXCLUDE_TARGET_PREFIXES count=7 (the module default — just the
# 7 ghost cps c2040/c5240/c5241/c5311/c5312/c5750/c5751) when
# multiplayer_safe=True. The correct count is 7 + len(V3_MP_SAFE_BLOCKLIST)
# = 7 + 149 = 156 in v0.24.27 / v0.24.28.
#
# Downstream: cross-engine c-prefixes that V3_MP_SAFE_BLOCKLIST was supposed
# to block became eligible targets. In seed 149569: 24 cross-engine cps
# (c7000/c7650/c7710-c7930/c7810/c8300/c1310) landed in Noklateo Limveld
# tiles, triggering a fly-in CTD reported by the user.
#
# Fix: hoist load_data() in cmd_shuffle_v3 BEFORE apply_run_overrides so the
# union sees the populated blocklist.

class TestMpSafeBlocklistHoist:
    """v0.24.28 regression. The wrapper must call load_data() before
    entering apply_run_overrides so the lazily-populated
    V3_MP_SAFE_BLOCKLIST is in place when the union is composed."""

    def test_blocklist_populated_when_impl_receives_control(
            self, engine, monkeypatch, tmp_path):
        """Simulate the pre-load process state by clearing
        V3_MP_SAFE_BLOCKLIST. Invoke cmd_shuffle_v3 with a stub impl that
        captures live module state at call time. Assert the blocklist
        was repopulated and the ghost-exclude union actually grew.

        Pre-v0.24.28 this would fail: captured blocklist_len would be 0
        and captured ghost_len would be 7.
        """
        # Force the pre-load state. monkeypatch restores after the test.
        monkeypatch.setattr(engine, 'V3_MP_SAFE_BLOCKLIST', set())

        captured = {}

        def stub_impl(*args, **kwargs):
            # Snapshot at the moment apply_run_overrides has finished its
            # union and handed control to _cmd_shuffle_v3_impl. The picker
            # would read these same values.
            captured['blocklist_len'] = len(engine.V3_MP_SAFE_BLOCKLIST)
            captured['ghost_len'] = len(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
            captured['blocklist_sample'] = sorted(engine.V3_MP_SAFE_BLOCKLIST)[:5]
            return None

        monkeypatch.setattr(engine, '_cmd_shuffle_v3_impl', stub_impl)

        engine.cmd_shuffle_v3(
            input_dir=str(tmp_path / 'in'),
            output_dir=str(tmp_path / 'out'),
            seed=0,
            multiplayer_safe=True,
        )

        # The blocklist must be populated by the hoisted load_data()
        # BEFORE apply_run_overrides composes the union.
        assert captured['blocklist_len'] > 100, (
            "V3_MP_SAFE_BLOCKLIST was not populated before "
            "_cmd_shuffle_v3_impl received control. Got "
            f"{captured['blocklist_len']}, expected > 100. This is the "
            "v0.24.20 lazy-init regression resurfacing — cmd_shuffle_v3 "
            "must call load_data() BEFORE apply_run_overrides."
        )

        # And the picker-visible ghost set must contain the union.
        assert captured['ghost_len'] > 100, (
            "V3_GHOST_EXCLUDE_TARGET_PREFIXES did not receive the "
            f"multiplayer_safe union. Got {captured['ghost_len']}, expected "
            "> 100 (7 module default ghost + ~149 mp_safe blocklist). "
            "Seed 149569 was the in-the-wild manifestation: ghost_len was "
            "7 and 24 cross-engine cps reached Noklateo Limveld tiles."
        )

    def test_blocklist_repopulated_with_known_seed149569_offenders(
            self, engine, monkeypatch, tmp_path):
        """The cross-engine c-prefixes from seed 149569 (v0.24.27) that
        landed at Noklateo Limveld tiles AND that V3_MP_SAFE_BLOCKLIST
        should have caught must all be in the post-load blocklist.

        Names the specific failure mode so future refactors that re-break
        the lazy-init dependency are caught by name.

        Note: 9 cross-engine cps reached Noklateo tiles in seed 149569,
        but only these 3 are blocked by V3_MP_SAFE_BLOCKLIST
        (`_source` is `heritage` or `post_dlc_dump`). The other 6
        (c7000/c7711/c7712/c7810/c8300/c1310) are tagged
        `_source: nr_placed`/`script_spawn` and would still be eligible
        with MP-safe ON — those are separate gate concerns, not what this
        test guards.
        """

        SEED_149569_MP_SAFE_LEAKERS = {
            'c7650',  # Dreg Corpse - Straghess (SOTE post_dlc_dump) — 5x at Noklateo
            'c7660',  # Dreg Wormface - Straghess (SOTE post_dlc_dump) — 1x
            'c7930',  # Demon Prince variants (heritage from DS3)     — 4x
        }

        monkeypatch.setattr(engine, 'V3_MP_SAFE_BLOCKLIST', set())
        captured = {}

        def stub_impl(*args, **kwargs):
            captured['blocklist'] = set(engine.V3_MP_SAFE_BLOCKLIST)
            captured['ghost'] = set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
            return None

        monkeypatch.setattr(engine, '_cmd_shuffle_v3_impl', stub_impl)
        engine.cmd_shuffle_v3(
            input_dir=str(tmp_path / 'in'),
            output_dir=str(tmp_path / 'out'),
            seed=0,
            multiplayer_safe=True,
        )

        missing = SEED_149569_MP_SAFE_LEAKERS - captured['blocklist']
        assert not missing, (
            "Seed 149569 MP-safe leakers missing from "
            f"V3_MP_SAFE_BLOCKLIST after the hoist: {sorted(missing)}. "
            "These cross-engine cps must be blocked when multiplayer_safe "
            "is ON — they reached m60_xx_xx_50 tiles in seed 149569 and "
            "(almost certainly) contributed to the fly-in CTD."
        )
        # Also assert they reached the ghost-exclude set (the picker's
        # actual read path) — guards against a future refactor that
        # populates the blocklist but doesn't union it.
        missing_in_ghost = SEED_149569_MP_SAFE_LEAKERS - captured['ghost']
        assert not missing_in_ghost, (
            "Seed 149569 MP-safe leakers populated in blocklist but not "
            f"unioned into ghost: {sorted(missing_in_ghost)}. The picker "
            "reads ghost — the blocklist alone doesn't protect anything."
        )


# =====================================================================
# _resolve_module_or_raise — defensive helper
# =====================================================================

class TestModuleResolver:
    """The default module-resolution path used to be `import oops_v3`,
    which silently returned a FRESH copy of oops_v3 if a caller had
    loaded the real one via importlib.util.spec_from_file_location
    (which doesn't register in sys.modules). The override would then
    mutate the fresh copy's state while the caller continued using the
    spec-loaded one — a silent no-op.

    v0.28.x replaced that with _resolve_module_or_raise which loudly
    rejects the spec-loaded path. These tests pin that contract.
    """

    def test_explicit_module_returned_unchanged(self):
        """When module is not None, return it as-is — no sys.modules
        lookup, no raising. The override-via-explicit-module path is
        the safe one."""
        from engine.runtime import _resolve_module_or_raise
        sentinel = object()
        assert _resolve_module_or_raise(sentinel) is sentinel

    def test_default_path_uses_sys_modules_oops_v3(self):
        """In a normal test environment, oops_v3 is in sys.modules
        (via the standard `import oops_v3` at the top of this file),
        so the None path returns that registered module."""
        import sys
        from engine.runtime import _resolve_module_or_raise
        resolved = _resolve_module_or_raise(None)
        assert resolved is sys.modules['oops_v3']

    def test_default_path_raises_when_oops_v3_not_in_sys_modules(self,
                                                                  monkeypatch):
        """The footgun guard. When oops_v3 isn't in sys.modules (e.g.
        a caller loaded it via spec_from_file_location), the helper
        must raise instead of falling back to a fresh import."""
        import sys
        from engine.runtime import _resolve_module_or_raise

        # Stash and remove oops_v3 from sys.modules to simulate the
        # spec-loaded caller scenario. The monkeypatch fixture
        # restores it on test exit.
        monkeypatch.delitem(sys.modules, 'oops_v3', raising=False)

        with pytest.raises(RuntimeError) as exc:
            _resolve_module_or_raise(None)

        # Message must mention the key facts so the failure is
        # diagnostic, not just "something went wrong."
        msg = str(exc.value)
        assert 'spec_from_file_location' in msg
        assert 'sys.modules' in msg
        assert 'module=' in msg

    def test_raise_message_points_at_explicit_module_fix(self,
                                                          monkeypatch):
        """The error message must tell the caller how to fix it. If
        someone hits this in production-like code, the fix is to pass
        module= explicitly — that's what the message should say."""
        import sys
        from engine.runtime import _resolve_module_or_raise

        monkeypatch.delitem(sys.modules, 'oops_v3', raising=False)

        with pytest.raises(RuntimeError, match=r'module=.*explicitly'):
            _resolve_module_or_raise(None)
