"""Tests for engine.state.GateState and the explicit-gates code path
on the predicate functions that consume it.

This file demonstrates the no-monkeypatch test ergonomics that the
GateState abstraction unlocks. Compare:

    # Old style — monkeypatch the module global (see test_filters.py)
    monkeypatch.setattr(oops_v3, 'V3_AVOID_VARIANT_NPC_IDS', {1001})
    out = oops_v3._filter_avoid_npc(variants)

    # New style — construct an explicit state, pass it in
    gates = GateState.empty().replace(avoid_variant_npc_ids={1001})
    out = oops_v3._filter_avoid_npc(variants, gates=gates)

Both styles work; the new style decouples the test from module mutation
order and makes the dependency explicit in the call signature.
"""
import oops_v3

from engine.state import GateState


# ---------------------------------------------------------------------------
# GateState construction and immutability
# ---------------------------------------------------------------------------

class TestGateStateConstruction:
    def test_empty_has_empty_sets(self):
        g = GateState.empty()
        assert g.exclude_prefixes == frozenset()
        assert g.exclude_target_prefixes == frozenset()
        assert g.ghost_exclude_target_prefixes == frozenset()
        assert g.mp_safe_blocklist == frozenset()
        assert g.heritage_all_prefixes == frozenset()
        assert g.night_boss_caliber_targets == frozenset()
        assert g.night_boss_strict_targets == frozenset()
        assert g.arena_only_targets == frozenset()
        assert g.avoid_variant_npc_ids == frozenset()
        assert g.hub_maps == frozenset()

    def test_from_module_snapshots_live_state(self, engine):
        # engine fixture has already triggered load_data().
        g = GateState.from_module(engine)
        # Sets should be non-empty post-load_data — proves the snapshot
        # actually pulled from the module.
        assert len(g.mp_safe_blocklist) > 0, (
            'mp_safe_blocklist should be populated after load_data')
        assert len(g.heritage_all_prefixes) > 0
        assert len(g.exclude_target_prefixes) > 0
        # Spot-check: a known MP-safe-blocked cp from the breakdown.
        # post_dlc_dump entries are blocked; c4801 'Lord of Blood Spear'
        # was the canonical example in the v0.24.20 changelog.
        # (Don't assert specific membership here — just that the snapshot
        # contains the same identity as the live module.)
        assert g.mp_safe_blocklist == frozenset(engine.V3_MP_SAFE_BLOCKLIST)

    def test_from_module_defaults_to_oops_v3(self, engine):
        # Calling with no arg should resolve to oops_v3 implicitly.
        g_explicit = GateState.from_module(engine)
        g_default = GateState.from_module()
        # Same state.
        assert g_explicit == g_default

    def test_frozen_dataclass_rejects_field_mutation(self):
        # Immutability guarantee: trying to assign to a field raises.
        g = GateState.empty()
        try:
            g.avoid_variant_npc_ids = frozenset({1, 2, 3})
        except Exception as e:
            # dataclasses raises FrozenInstanceError (subclass of AttributeError).
            assert 'frozen' in str(e).lower() or 'cannot assign' in str(e).lower()
        else:
            raise AssertionError('Frozen dataclass should reject field assignment')

    def test_snapshot_isolated_from_subsequent_module_mutation(
            self, engine, monkeypatch):
        # Take a snapshot, then mutate the module, then verify the
        # snapshot is unchanged. This is the core safety property —
        # tests that hold a GateState shouldn't be affected by other
        # code paths' mutations.
        g = GateState.from_module(engine)
        avoid_before = g.avoid_variant_npc_ids
        # Mutate the module to something different.
        monkeypatch.setattr(engine, 'V3_AVOID_VARIANT_NPC_IDS',
                            {999999999})  # synthetic, definitely not in g
        # Snapshot unchanged.
        assert g.avoid_variant_npc_ids == avoid_before
        assert 999999999 not in g.avoid_variant_npc_ids


# ---------------------------------------------------------------------------
# GateState.replace() — override semantics for tests
# ---------------------------------------------------------------------------

class TestGateStateReplace:
    def test_replace_returns_new_instance(self):
        g1 = GateState.empty()
        g2 = g1.replace(avoid_variant_npc_ids={1001})
        # Different objects.
        assert g1 is not g2
        # Original unchanged.
        assert g1.avoid_variant_npc_ids == frozenset()
        # Copy has the override.
        assert g2.avoid_variant_npc_ids == frozenset({1001})

    def test_replace_coerces_set_to_frozenset(self):
        # The dataclass invariant is "frozenset everywhere". Accept any
        # iterable and coerce it for caller convenience — tests can
        # pass {1, 2, 3} or [1, 2, 3] interchangeably.
        g = GateState.empty().replace(avoid_variant_npc_ids={1, 2, 3})
        assert isinstance(g.avoid_variant_npc_ids, frozenset)
        assert g.avoid_variant_npc_ids == frozenset({1, 2, 3})

    def test_replace_passes_through_set_fields(self):
        # Coerces set/iterable into frozenset.
        g = GateState.empty().replace(arena_only_targets={'cARENA'})
        assert isinstance(g.arena_only_targets, frozenset)
        assert g.arena_only_targets == frozenset({'cARENA'})

    def test_replace_preserves_unmentioned_fields(self):
        g1 = GateState.empty().replace(
            avoid_variant_npc_ids={1001},
            heritage_all_prefixes={'cHERIT'})
        g2 = g1.replace(arena_only_targets={'cARENA'})
        # New override applied; old overrides preserved.
        assert g2.arena_only_targets == frozenset({'cARENA'})
        assert g2.avoid_variant_npc_ids == frozenset({1001})
        assert g2.heritage_all_prefixes == frozenset({'cHERIT'})


# ---------------------------------------------------------------------------
# _filter_avoid_npc with explicit gates — proves the new path works
# ---------------------------------------------------------------------------

class TestFilterAvoidNpcWithGates:
    """Same scenarios as TestFilterAvoidNpc in test_filters.py, but using
    explicit GateState instead of monkeypatch. Confirms the new path
    produces equivalent results without touching module state.
    """

    def test_drops_avoid_listed_with_explicit_gates(self):
        gates = GateState.empty().replace(avoid_variant_npc_ids={1001, 1002})
        vs = [
            {'npc_param_id': 1001, 'variant_name': 'banned'},
            {'npc_param_id': 9999, 'variant_name': 'keep'},
            {'npc_param_id': 1002, 'variant_name': 'banned'},
        ]
        out = oops_v3._filter_avoid_npc(vs, gates=gates)
        assert len(out) == 1
        assert out[0]['npc_param_id'] == 9999

    def test_hard_filter_returns_empty_with_explicit_gates(self):
        gates = GateState.empty().replace(avoid_variant_npc_ids={1001, 1002})
        vs = [{'npc_param_id': 1001}, {'npc_param_id': 1002}]
        assert oops_v3._filter_avoid_npc(vs, gates=gates) == []

    def test_gates_none_falls_back_to_module_state(self, monkeypatch):
        # Critical backwards-compat check: when gates is omitted, the
        # function reads from the module globals the same as before.
        # Existing call sites in pick_variant_for_tier rely on this.
        monkeypatch.setattr(oops_v3, 'V3_AVOID_VARIANT_NPC_IDS', {77777})
        vs = [{'npc_param_id': 77777}, {'npc_param_id': 88888}]
        out = oops_v3._filter_avoid_npc(vs)  # no gates= arg
        assert len(out) == 1
        assert out[0]['npc_param_id'] == 88888


# ---------------------------------------------------------------------------
# is_boss_tier_prefix with explicit gates
# ---------------------------------------------------------------------------

class TestIsBossTierPrefixWithGates:
    """The heritage hp_median leg is the gate-dependent path. Tests
    that leg via explicit GateState — no monkeypatch needed."""

    def test_heritage_hp_leg_fires_with_explicit_gates(self):
        gates = GateState.empty().replace(heritage_all_prefixes={'cHERIT'})
        tags = {'cHERIT': {'hp_median': 350}}
        assert oops_v3.is_boss_tier_prefix(
            'cHERIT', tags, {}, gates=gates)

    def test_heritage_hp_leg_does_not_fire_for_non_heritage_cp(self):
        # Same hp_median, but cp not in the heritage set this run.
        gates = GateState.empty().replace(heritage_all_prefixes={'cOTHER'})
        tags = {'cHERIT': {'hp_median': 350}}
        assert not oops_v3.is_boss_tier_prefix(
            'cHERIT', tags, {}, gates=gates)

    def test_hp_threshold_boundary_with_gates(self):
        gates = GateState.empty().replace(heritage_all_prefixes={'cHERIT'})
        # hp_median == 300 fires.
        assert oops_v3.is_boss_tier_prefix(
            'cHERIT', {'cHERIT': {'hp_median': 300}}, {}, gates=gates)
        # hp_median == 299 does not.
        assert not oops_v3.is_boss_tier_prefix(
            'cHERIT', {'cHERIT': {'hp_median': 299}}, {}, gates=gates)

    def test_non_heritage_legs_unaffected_by_gates(self):
        # The has_reward / hit_height / boss-marker legs don't consult
        # gates at all. They should fire regardless of GateState.
        gates_empty = GateState.empty()
        gates_with_heritage = GateState.empty().replace(
            heritage_all_prefixes={'cANY'})
        tags = {'cTEST': {'has_reward': True}}
        # Both should be True via the has_reward leg.
        assert oops_v3.is_boss_tier_prefix(
            'cTEST', tags, {}, gates=gates_empty)
        assert oops_v3.is_boss_tier_prefix(
            'cTEST', tags, {}, gates=gates_with_heritage)

    def test_gates_none_falls_back_to_module_state(self, engine, tags):
        # Backwards compat: pre-existing callers pass no gates= and
        # get the same behavior as before. Test against a real
        # heritage cp from the live module.
        # Pick the first heritage cp that has hp_median >= 300.
        heritage_with_hp = None
        for cp in engine.V3_HERITAGE_ALL_PREFIXES:
            t = tags.get(cp, {})
            if t.get('hp_median', 0) and t['hp_median'] >= 300:
                heritage_with_hp = (cp, t)
                break
        if heritage_with_hp is None:
            # No heritage cp meets the criteria — skip rather than fail.
            # The test is about the call mechanism, not the data.
            import pytest
            pytest.skip('No heritage cp with hp_median≥300 in live data')
        cp, t = heritage_with_hp
        local_tags = {cp: t}
        # With no gates=, reads V3_HERITAGE_ALL_PREFIXES — should hit
        # the heritage leg and return True.
        assert oops_v3.is_boss_tier_prefix(cp, local_tags, {})


# ---------------------------------------------------------------------------
# Parity check: explicit gates from snapshot equals module-globals path
# ---------------------------------------------------------------------------

class TestGatesModuleParity:
    """For any predicate that supports gates=, calling it with a
    from_module() snapshot should produce identical results to calling
    with gates=None. If this fails, the migration isn't safe.
    """

    def test_filter_avoid_npc_parity_against_real_data(self, engine, roster):
        # Take the first 50 real variants from the loaded roster and
        # filter both ways. Results must match.
        sample = roster['all_variants'][:50]
        out_module = oops_v3._filter_avoid_npc(sample)
        out_gates = oops_v3._filter_avoid_npc(
            sample, gates=GateState.from_module(engine))
        assert out_module == out_gates

    def test_is_boss_tier_prefix_parity_against_real_data(
            self, engine, tags, prefix_variants):
        # For 20 real cps, both code paths should agree.
        snapshot = GateState.from_module(engine)
        sample_cps = list(tags.keys())[:20]
        for cp in sample_cps:
            module_result = oops_v3.is_boss_tier_prefix(
                cp, tags, prefix_variants)
            gates_result = oops_v3.is_boss_tier_prefix(
                cp, tags, prefix_variants, gates=snapshot)
            assert module_result == gates_result, (
                f'parity failure for {cp}: module={module_result} '
                f'gates={gates_result}')
