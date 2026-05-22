"""Tests for engine.pack_loaders.heritage_pack.apply_heritage_pack.

These tests exercise the loader function directly with synthetic pack
data — no oops_v3 module state involved. That's the win: the function
is testable in complete isolation, and the behavior-lock in
test_load_data_lock.py validates that the extraction didn't drift
from the inline original.
"""
import copy

import pytest

from engine.pack_loaders.heritage_pack import apply_heritage_pack


# ---------------------------------------------------------------------------
# Fixtures: synthetic pack / tags / roster for isolation
# ---------------------------------------------------------------------------

def _make_pack(enabled=True, owned_cps=('cHERIT1', 'cHERIT2', 'cHERIT3')):
    """Build a synthetic heritage_pack.json-shaped dict."""
    meta = {'enabled': enabled} if enabled is not None else {}
    return {
        '_meta': meta,
        'tags': {cp: {'name': f'Heritage-{cp}'} for cp in owned_cps},
    }


def _make_state():
    """Build synthetic tags + roster with a mix of pack-owned and
    vanilla cps. Returns (tags, roster) — caller mutates these
    and asserts after."""
    tags = {
        # Vanilla cps (should always survive)
        'c2130': {'name': 'Margit', '_source': 'nr_placed'},
        'c4500': {'name': 'Tree Sentinel', '_source': 'nr_placed'},
        # Heritage-owned cps (should be removed when pack disabled)
        'cHERIT1': {'name': 'Heritage-cHERIT1', '_source': 'heritage'},
        'cHERIT2': {'name': 'Heritage-cHERIT2', '_source': 'heritage'},
        'cHERIT3': {'name': 'Heritage-cHERIT3', '_source': 'heritage'},
    }
    roster = {
        'all_variants': [
            {'c_prefix': 'c2130', 'npc_param_id': 21300000},
            {'c_prefix': 'c2130', 'npc_param_id': 21300001},
            {'c_prefix': 'c4500', 'npc_param_id': 45000000},
            {'c_prefix': 'cHERIT1', 'npc_param_id': 99990000},
            {'c_prefix': 'cHERIT1', 'npc_param_id': 99990001},
            {'c_prefix': 'cHERIT2', 'npc_param_id': 99990100},
            {'c_prefix': 'cHERIT3', 'npc_param_id': 99990200},
        ],
    }
    return tags, roster


# ---------------------------------------------------------------------------
# Enabled path — no-op
# ---------------------------------------------------------------------------

class TestEnabledIsNoOp:
    def test_enabled_does_not_remove_anything(self):
        pack = _make_pack(enabled=True)
        tags, roster = _make_state()
        tags_before = copy.deepcopy(tags)
        roster_before = copy.deepcopy(roster)

        stats = apply_heritage_pack(pack, tags=tags, roster=roster)

        assert stats['enabled'] is True
        assert stats['n_tag_removed'] == 0
        assert stats['n_variant_removed'] == 0
        # State unchanged.
        assert tags == tags_before
        assert roster == roster_before

    def test_meta_absent_defaults_to_enabled(self):
        # No _meta key at all → defaults to enabled.
        pack = {'tags': {'cHERIT1': {}}}
        tags, roster = _make_state()
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        assert stats['enabled'] is True
        # cHERIT1 still in tags.
        assert 'cHERIT1' in tags

    def test_meta_present_but_enabled_unset_defaults_to_enabled(self):
        # _meta present but no 'enabled' key → defaults to enabled.
        # Mirrors the original `hp.get('_meta', {}).get('enabled', True)`.
        pack = {'_meta': {'other_field': 'irrelevant'},
                'tags': {'cHERIT1': {}}}
        tags, roster = _make_state()
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        assert stats['enabled'] is True


# ---------------------------------------------------------------------------
# Disabled path — remove pack-owned cps
# ---------------------------------------------------------------------------

class TestDisabledRemovesCps:
    def test_disabled_removes_heritage_cps_from_tags(self):
        pack = _make_pack(enabled=False)
        tags, roster = _make_state()
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)

        assert stats['enabled'] is False
        assert stats['n_tag_removed'] == 3
        assert set(tags.keys()) == {'c2130', 'c4500'}

    def test_disabled_removes_heritage_variants_from_roster(self):
        pack = _make_pack(enabled=False)
        tags, roster = _make_state()
        before = len(roster['all_variants'])
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)

        assert stats['n_variant_removed'] == 4  # 2 for cHERIT1, 1 each for the others
        # Only vanilla variants survive.
        surviving = {v['c_prefix'] for v in roster['all_variants']}
        assert surviving == {'c2130', 'c4500'}
        assert len(roster['all_variants']) == before - 4

    def test_disabled_returns_pack_cps_in_stats(self):
        # hp_cps is always populated regardless of enabled state — it
        # describes "which cps does this pack own", not "which were
        # removed".
        pack = _make_pack(enabled=False,
                          owned_cps=('cA', 'cB', 'cC'))
        tags, roster = _make_state()
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        assert stats['hp_cps'] == {'cA', 'cB', 'cC'}


class TestArenaOnlyAddsContract:
    """v0.24.22 (Phase 11): apply_heritage_pack returns the cps with
    expects_boss_arena=True so the caller's post-loader auto-extend can
    consume them without reaching into raw pack_data."""

    def test_enabled_pack_populates_arena_only_adds(self):
        pack = {
            '_meta': {'enabled': True},
            'tags': {
                'cArena1': {'name': 'A1', 'expects_boss_arena': True},
                'cArena2': {'name': 'A2', 'expects_boss_arena': True},
                'cField':  {'name': 'F',  'expects_boss_arena': False},
                'cMisc':   {'name': 'M'},  # field absent
            },
        }
        tags, roster = _make_state()
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        assert stats['arena_only_adds'] == {'cArena1', 'cArena2'}

    def test_disabled_pack_returns_empty_arena_only_adds(self):
        # Disabled = cps removed from tags entirely; arena contribution
        # is moot.
        pack = {
            '_meta': {'enabled': False},
            'tags': {
                'cHERIT1': {'expects_boss_arena': True},
            },
        }
        tags, roster = _make_state()
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        assert stats['arena_only_adds'] == set()


# ---------------------------------------------------------------------------
# Edge cases — partial overlap, empty pack, missing keys
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_pack_cp_not_in_tags_is_skipped_silently(self):
        # heritage_pack.json may list a cp that isn't in tags (e.g.,
        # the pack ships with a future cp not yet in base data).
        # Should not crash, should still remove the ones that ARE there.
        pack = _make_pack(enabled=False,
                          owned_cps=('cHERIT1', 'cNOT_IN_TAGS'))
        tags, roster = _make_state()
        # cHERIT2 and cHERIT3 are in tags but NOT in pack.tags this run
        # — so they shouldn't be removed.
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)

        assert stats['n_tag_removed'] == 1  # only cHERIT1
        assert 'cHERIT1' not in tags
        assert 'cHERIT2' in tags  # not pack-owned this run
        assert 'cHERIT3' in tags  # not pack-owned this run

    def test_empty_pack_tags_section(self):
        # Pack has _meta.enabled=False but its tags section is empty.
        # Should no-op (nothing to remove) without crashing.
        pack = {'_meta': {'enabled': False}, 'tags': {}}
        tags, roster = _make_state()
        tags_before = copy.deepcopy(tags)
        roster_before = copy.deepcopy(roster)

        stats = apply_heritage_pack(pack, tags=tags, roster=roster)

        assert stats['enabled'] is False
        assert stats['n_tag_removed'] == 0
        assert stats['n_variant_removed'] == 0
        assert tags == tags_before
        assert roster == roster_before

    def test_pack_tags_section_missing(self):
        # Pack has no 'tags' key at all. Treat as empty.
        pack = {'_meta': {'enabled': False}}
        tags, roster = _make_state()
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        assert stats['n_tag_removed'] == 0
        assert stats['hp_cps'] == set()

    def test_roster_missing_all_variants(self):
        # roster doesn't have an 'all_variants' key. Treat as empty
        # list — function should not crash.
        pack = _make_pack(enabled=False)
        tags = {'cHERIT1': {}}
        roster = {}
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        assert stats['n_variant_removed'] == 0
        # all_variants got created (empty).
        assert roster.get('all_variants') == []

    def test_variant_without_c_prefix_field(self):
        # Defensive: a malformed variant entry lacking c_prefix should
        # not crash; .get returns None, None is not in any cp set.
        pack = _make_pack(enabled=False,
                          owned_cps=('cHERIT1',))
        tags = {'cHERIT1': {}}
        roster = {
            'all_variants': [
                {'c_prefix': 'cHERIT1'},
                {'npc_param_id': 9999},  # malformed — no c_prefix
            ],
        }
        stats = apply_heritage_pack(pack, tags=tags, roster=roster)
        # cHERIT1 variant removed; malformed entry retained (its
        # c_prefix is None, which isn't in {cHERIT1}).
        assert len(roster['all_variants']) == 1
        assert roster['all_variants'][0].get('npc_param_id') == 9999


# ---------------------------------------------------------------------------
# Idempotency — double-application produces the same state
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_double_disable_is_same_as_single_disable(self):
        pack = _make_pack(enabled=False)
        tags1, roster1 = _make_state()
        tags2, roster2 = _make_state()

        # Single application.
        apply_heritage_pack(pack, tags=tags1, roster=roster1)

        # Double application.
        apply_heritage_pack(pack, tags=tags2, roster=roster2)
        apply_heritage_pack(pack, tags=tags2, roster=roster2)

        # Final states match.
        assert tags1 == tags2
        assert roster1 == roster2

    def test_second_disable_call_reports_zero_removed(self):
        pack = _make_pack(enabled=False)
        tags, roster = _make_state()

        stats1 = apply_heritage_pack(pack, tags=tags, roster=roster)
        stats2 = apply_heritage_pack(pack, tags=tags, roster=roster)

        # First call removed; second call found nothing left to remove.
        assert stats1['n_tag_removed'] == 3
        assert stats1['n_variant_removed'] == 4
        assert stats2['n_tag_removed'] == 0
        assert stats2['n_variant_removed'] == 0
        # But hp_cps is the same — the pack STILL owns those cps,
        # even if they're already absent from this state.
        assert stats1['hp_cps'] == stats2['hp_cps']


# ---------------------------------------------------------------------------
# Integration: the function uses the real heritage_pack.json
# ---------------------------------------------------------------------------

class TestAgainstRealHeritagePack:
    """One smoke test against the actual heritage_pack.json shipped
    with the repo. Catches structural issues (missing _meta, wrong
    field types) that synthetic tests miss.
    """

    def test_real_pack_disable_path(self):
        # Apply the real heritage_pack.json with enabled=False against
        # a copy of the real (loaded) tags + roster. Sanity check that
        # the loader produces the expected count of removed cps — which
        # we know from the lock fixture's source_breakdown.
        import io
        import json
        import os
        import sys
        from contextlib import redirect_stdout

        REPO_ROOT = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        hp_path = os.path.join(REPO_ROOT, 'data', 'heritage_pack.json')
        if not os.path.isfile(hp_path):
            pytest.skip('heritage_pack.json not present')

        with open(hp_path, encoding='utf-8') as f:
            pack = json.load(f)

        # Force disabled regardless of file content.
        pack.setdefault('_meta', {})['enabled'] = False

        sys.path.insert(0, REPO_ROOT)
        import oops_v3
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = oops_v3.load_data()

        # Copy state so we don't mutate the module-level loaded state
        # (other tests reuse the engine fixture).
        tags_copy = dict(tags)
        roster_copy = {'all_variants': list(roster['all_variants'])}

        stats = apply_heritage_pack(pack, tags=tags_copy, roster=roster_copy)

        assert stats['enabled'] is False
        # Heritage pack ships with ~41 cps per the load_data comment.
        # Don't assert exactly 41 — the pack manifest can grow. Assert
        # the function actually removed some.
        assert stats['n_tag_removed'] > 0
        assert stats['n_variant_removed'] > 0
        # Removed count should match the size of the intersection.
        intersection = stats['hp_cps'] & set(tags.keys())
        assert stats['n_tag_removed'] == len(intersection)
