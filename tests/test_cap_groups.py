"""tests/test_cap_groups.py — unit tests for the shared-cap grouping layer.

These tests run the cap_groups module in isolation without the engine,
so they catch:
  - Index correctness (cp -> group lookup, group -> members lookup)
  - Audit findings (cap mismatch, missing members, dup cps, singletons)
  - End-to-end accounting math (simulated placements/reservations)

The engine-integration tests live in test_pick_target.py; these cover
just the standalone module.
"""
import pytest


# ---- Fixtures ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_cap_groups():
    """Ensure each test starts with a fresh module state."""
    from engine import cap_groups
    cap_groups._CONFIG = None
    cap_groups._CP_TO_GROUP = {}
    cap_groups._GROUP_TO_MEMBERS = {}
    yield
    cap_groups._CONFIG = None
    cap_groups._CP_TO_GROUP = {}
    cap_groups._GROUP_TO_MEMBERS = {}


def _config(groups):
    """Build a minimal config dict from a {group_name: [members]} mapping."""
    return {
        '_meta': {'description': 'test fixture'},
        'groups': {
            name: {'members': list(members), 'rationale': 'test'}
            for name, members in groups.items()
        },
    }


# ---- resolve_cap_key ---------------------------------------------------------

class TestResolveCapKey:
    def test_grouped_cp_returns_group_name(self):
        from engine.cap_groups import use_cap_groups_for_test, resolve_cap_key
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        assert resolve_cap_key('c3251') == 'tree_sentinel_iconic'
        assert resolve_cap_key('c6251') == 'tree_sentinel_iconic'

    def test_ungrouped_cp_returns_cp_itself(self):
        from engine.cap_groups import use_cap_groups_for_test, resolve_cap_key
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        assert resolve_cap_key('c4770') == 'c4770'
        assert resolve_cap_key('c0000') == 'c0000'

    def test_empty_config_passthrough(self):
        from engine.cap_groups import use_cap_groups_for_test, resolve_cap_key
        use_cap_groups_for_test(_config({}))
        assert resolve_cap_key('c3251') == 'c3251'

    def test_three_member_group(self):
        from engine.cap_groups import use_cap_groups_for_test, resolve_cap_key
        use_cap_groups_for_test(_config({
            'fingercreeper_family': ['c4240', 'c5550', 'c6240'],
        }))
        assert resolve_cap_key('c4240') == 'fingercreeper_family'
        assert resolve_cap_key('c5550') == 'fingercreeper_family'
        assert resolve_cap_key('c6240') == 'fingercreeper_family'


# ---- is_group_key / group_members --------------------------------------------

class TestGroupQueries:
    def test_is_group_key_true_for_group_name(self):
        from engine.cap_groups import use_cap_groups_for_test, is_group_key
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        assert is_group_key('tree_sentinel_iconic') is True

    def test_is_group_key_false_for_cp(self):
        from engine.cap_groups import use_cap_groups_for_test, is_group_key
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        # Both the cps themselves AND ungrouped cps return False
        assert is_group_key('c3251') is False
        assert is_group_key('c6251') is False
        assert is_group_key('c4770') is False

    def test_group_members_returns_set(self):
        from engine.cap_groups import use_cap_groups_for_test, group_members
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        assert group_members('tree_sentinel_iconic') == frozenset({'c3251', 'c6251'})

    def test_group_members_empty_for_unknown_group(self):
        from engine.cap_groups import use_cap_groups_for_test, group_members
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        assert group_members('not_a_group') == frozenset()


# ---- explain_key -------------------------------------------------------------

class TestExplainKey:
    def test_ungrouped_cp_passthrough(self):
        from engine.cap_groups import use_cap_groups_for_test, explain_key
        use_cap_groups_for_test(_config({}))
        assert explain_key('c4770') == 'c4770'

    def test_group_name_expands(self):
        from engine.cap_groups import use_cap_groups_for_test, explain_key
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        # Members in result are sorted for deterministic output
        assert explain_key('tree_sentinel_iconic') == \
            'tree_sentinel_iconic={c3251, c6251}'


# ---- audit_cap_groups --------------------------------------------------------

class TestAudit:
    def _tags_and_caps(self, cps_with_cap_pairs):
        """Build minimal tags + caps from {cp: cap_value} dict."""
        tags = {cp: {'name': cp} for cp in cps_with_cap_pairs}
        caps = dict(cps_with_cap_pairs)
        return tags, caps

    def test_passes_valid_group(self):
        from engine.cap_groups import use_cap_groups_for_test, audit_cap_groups
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        tags, caps = self._tags_and_caps({'c3251': 2, 'c6251': 2})
        audit_cap_groups(tags, caps)  # should not raise

    def test_passes_with_no_groups(self):
        from engine.cap_groups import use_cap_groups_for_test, audit_cap_groups
        use_cap_groups_for_test(_config({}))
        audit_cap_groups({}, {})  # should not raise

    def test_raises_on_cap_mismatch(self):
        from engine.cap_groups import use_cap_groups_for_test, audit_cap_groups
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        tags, caps = self._tags_and_caps({'c3251': 2, 'c6251': 4})
        with pytest.raises(ValueError) as exc:
            audit_cap_groups(tags, caps)
        assert 'mismatched caps' in str(exc.value)

    def test_raises_on_missing_tag(self):
        from engine.cap_groups import use_cap_groups_for_test, audit_cap_groups
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        # c6251 is missing from tags
        tags = {'c3251': {'name': 'Tree Sentinel'}}
        caps = {'c3251': 2}
        with pytest.raises(ValueError) as exc:
            audit_cap_groups(tags, caps)
        assert 'c6251' in str(exc.value)
        assert 'not in nr_enemy_tags' in str(exc.value)

    def test_raises_on_singleton_group(self):
        from engine.cap_groups import use_cap_groups_for_test, audit_cap_groups
        use_cap_groups_for_test(_config({
            'singleton': ['c3251'],
        }))
        tags, caps = self._tags_and_caps({'c3251': 2})
        with pytest.raises(ValueError) as exc:
            audit_cap_groups(tags, caps)
        assert 'at least 2 members' in str(exc.value)

    def test_raises_on_partial_cap_coverage(self):
        from engine.cap_groups import use_cap_groups_for_test, audit_cap_groups
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        # c6251 lacks a cap entry — partial coverage is ambiguous
        tags = {'c3251': {'name': 'a'}, 'c6251': {'name': 'b'}}
        caps = {'c3251': 2}
        with pytest.raises(ValueError) as exc:
            audit_cap_groups(tags, caps)
        assert 'partial cap coverage' in str(exc.value)

    def test_collated_findings(self):
        """Multiple problems in one config produce one combined error."""
        from engine.cap_groups import use_cap_groups_for_test, audit_cap_groups
        use_cap_groups_for_test(_config({
            'g1': ['c3251', 'c6251'],
            'g2': ['c3251', 'cMISSING'],  # c3251 dup + cMISSING absent
        }))
        tags = {'c3251': {'name': 'a'}, 'c6251': {'name': 'b'}}
        caps = {'c3251': 2, 'c6251': 2}
        with pytest.raises(ValueError) as exc:
            audit_cap_groups(tags, caps)
        msg = str(exc.value)
        # Should accumulate multiple findings, not stop at first
        assert 'multiple groups' in msg or 'listed in multiple' in msg
        assert 'cMISSING' in msg


# ---- Simulated accounting math -----------------------------------------------

class TestSimulatedAccounting:
    """Walk through what the engine does at placement time to verify the
    key-rewrite layer produces correct group accounting end-to-end."""

    def test_grouped_placements_share_cap(self):
        from engine.cap_groups import (
            use_cap_groups_for_test, resolve_cap_key, is_group_key,
            group_members)
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        # Simulate what oops_v3.py does at each placement
        placed_counts = {}
        caps = {'c3251': 2, 'c6251': 2}

        # Place a c3251: bump under the group key
        k = resolve_cap_key('c3251')
        placed_counts[k] = placed_counts.get(k, 0) + 1
        assert placed_counts == {'tree_sentinel_iconic': 1}

        # Place a c6251: bumps the SAME group
        k = resolve_cap_key('c6251')
        placed_counts[k] = placed_counts.get(k, 0) + 1
        assert placed_counts == {'tree_sentinel_iconic': 2}

        # Now check the blocked set computation (group exhausted at 2/2)
        blocked = set()
        for key, n in placed_counts.items():
            if is_group_key(key):
                members = group_members(key)
                member_cap = next((caps.get(m, 0) for m in members
                                   if m in caps), 0)
                if n >= member_cap:
                    blocked |= members
            else:
                if n >= caps.get(key, 0):
                    blocked.add(key)
        # Both cps blocked despite only one being explicitly placed twice
        assert blocked == {'c3251', 'c6251'}

    def test_ungrouped_placements_unchanged(self):
        from engine.cap_groups import use_cap_groups_for_test, resolve_cap_key
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        placed_counts = {}
        # c4770 is NOT in any group — behavior must be identical to pre-patch
        k = resolve_cap_key('c4770')
        placed_counts[k] = placed_counts.get(k, 0) + 1
        assert placed_counts == {'c4770': 1}

    def test_mixed_grouped_and_ungrouped_in_same_dict(self):
        from engine.cap_groups import use_cap_groups_for_test, resolve_cap_key
        use_cap_groups_for_test(_config({
            'tree_sentinel_iconic': ['c3251', 'c6251'],
        }))
        placed_counts = {}
        # Realistic mix: some grouped, some ungrouped placements
        for cp in ['c3251', 'c4770', 'c6251', 'c4770', 'c3251']:
            k = resolve_cap_key(cp)
            placed_counts[k] = placed_counts.get(k, 0) + 1
        # Group has 3 placements (c3251 twice + c6251 once); c4770 has 2
        assert placed_counts == {
            'tree_sentinel_iconic': 3,
            'c4770': 2,
        }
