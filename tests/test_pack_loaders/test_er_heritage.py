"""Tests for engine.pack_loaders.er_heritage.apply_er_heritage.

er_heritage is "vanilla-wins" — additive contributions where existing
tags/variants take precedence over the pack's. Distinct from
heritage_pack (disable-only toggle) in shape and semantics, so the
test surface is correspondingly different.
"""
import copy

import pytest

from engine.pack_loaders.er_heritage import apply_er_heritage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pack(enabled=True, tags=None, variants_per_prefix=None):
    """Build a synthetic er_heritage_imports.json-shaped dict."""
    pack = {'_meta': {'enabled': enabled} if enabled is not None else {}}
    pack['tags'] = tags if tags is not None else {
        'cER1': {'name': 'ER Boss 1', '_source': 'er_heritage_v1'},
        'cER2': {'name': 'ER Boss 2', '_source': 'er_heritage_v1'},
    }
    pack['variants_per_prefix'] = (
        variants_per_prefix if variants_per_prefix is not None else {
            'cER1': [
                {'c_prefix': 'cER1', 'npc_param_id': 20100000,
                 '_source': 'er_heritage_v1'},
                {'c_prefix': 'cER1', 'npc_param_id': 20100001,
                 '_source': 'er_heritage_v1'},
            ],
            'cER2': [
                {'c_prefix': 'cER2', 'npc_param_id': 20200000,
                 '_source': 'er_heritage_v1'},
            ],
        })
    return pack


def _make_state():
    """Synthetic baseline tags + roster with vanilla entries that the
    pack may or may not collide with."""
    tags = {
        'c2130': {'name': 'Margit', '_source': 'nr_placed'},
        'c4500': {'name': 'Tree Sentinel', '_source': 'nr_placed'},
    }
    roster = {
        'all_variants': [
            {'c_prefix': 'c2130', 'npc_param_id': 21300000},
            {'c_prefix': 'c4500', 'npc_param_id': 45000000},
        ],
    }
    return tags, roster


# ---------------------------------------------------------------------------
# Disabled — no-op
# ---------------------------------------------------------------------------

class TestDisabledIsNoOp:
    def test_disabled_adds_nothing(self):
        pack = _make_pack(enabled=False)
        tags, roster = _make_state()
        tags_before = copy.deepcopy(tags)
        roster_before = copy.deepcopy(roster)

        stats = apply_er_heritage(pack, tags=tags, roster=roster)

        assert stats['enabled'] is False
        assert stats['n_tags_added'] == 0
        assert stats['n_variants_added'] == 0
        assert tags == tags_before
        assert roster == roster_before

    def test_disabled_does_not_remove_existing(self):
        # er_heritage disabling is additive-skip, NOT subtractive.
        # Pack-related cps that ALREADY exist in tags (somehow) stay.
        pack = _make_pack(enabled=False,
                          tags={'c2130': {'name': 'OVERRIDE'}})
        tags, roster = _make_state()
        tags_before_margit = tags['c2130']

        apply_er_heritage(pack, tags=tags, roster=roster)

        # c2130 still has its original "Margit" data — disabling didn't
        # remove anything.
        assert tags['c2130'] is tags_before_margit


# ---------------------------------------------------------------------------
# Enabled tag merge — vanilla-wins
# ---------------------------------------------------------------------------

class TestEnabledTagMerge:
    def test_new_cps_added(self):
        pack = _make_pack(enabled=True)
        tags, roster = _make_state()
        stats = apply_er_heritage(pack, tags=tags, roster=roster)

        assert stats['enabled'] is True
        assert stats['n_tags_added'] == 2
        assert 'cER1' in tags
        assert 'cER2' in tags
        assert tags['cER1']['_source'] == 'er_heritage_v1'

    def test_existing_cps_not_overwritten(self):
        # If a pack cp already exists in tags, the pack version is
        # SKIPPED. The existing entry wins.
        pack = _make_pack(enabled=True, tags={
            'c2130': {'name': 'OVERRIDE-FROM-ER',
                      '_source': 'er_heritage_v1'},
            'cER_NEW': {'name': 'New ER',
                        '_source': 'er_heritage_v1'},
        })
        tags, roster = _make_state()
        stats = apply_er_heritage(pack, tags=tags, roster=roster)

        # c2130 untouched.
        assert tags['c2130']['name'] == 'Margit'
        assert tags['c2130']['_source'] == 'nr_placed'
        # cER_NEW added.
        assert tags['cER_NEW']['name'] == 'New ER'
        # Stats reflect: only 1 new (cER_NEW); c2130 was skipped.
        assert stats['n_tags_added'] == 1

    def test_empty_tags_section(self):
        pack = _make_pack(enabled=True, tags={})
        tags, roster = _make_state()
        stats = apply_er_heritage(pack, tags=tags, roster=roster)
        assert stats['n_tags_added'] == 0


# ---------------------------------------------------------------------------
# Enabled variant merge — vanilla-wins at c_prefix granularity
# ---------------------------------------------------------------------------

class TestEnabledVariantMerge:
    def test_new_cps_variants_appended(self):
        pack = _make_pack(enabled=True)
        tags, roster = _make_state()
        # Baseline: cER1 / cER2 have no variants in roster.
        before = len(roster['all_variants'])

        stats = apply_er_heritage(pack, tags=tags, roster=roster)

        # 2 cER1 variants + 1 cER2 variant = 3 added.
        assert stats['n_variants_added'] == 3
        assert len(roster['all_variants']) == before + 3

    def test_existing_cp_variants_skipped_wholesale(self):
        # If ANY variant with this c_prefix already exists, the pack
        # contribution for that cp is skipped IN FULL. Partial-merge
        # is not supported — that's the design.
        pack = _make_pack(enabled=True, variants_per_prefix={
            'c2130': [  # c2130 already has a variant in the roster
                {'c_prefix': 'c2130', 'npc_param_id': 21399999,
                 '_source': 'er_heritage_v1'},
            ],
            'cER_NEW': [  # cER_NEW has no variants
                {'c_prefix': 'cER_NEW', 'npc_param_id': 99999999},
            ],
        })
        tags, roster = _make_state()
        stats = apply_er_heritage(pack, tags=tags, roster=roster)

        # c2130 skipped; cER_NEW added.
        assert stats['n_variants_added'] == 1
        # The c2130 variant added by the pack is NOT in the roster.
        c2130_npc_ids = {v['npc_param_id'] for v in roster['all_variants']
                         if v['c_prefix'] == 'c2130'}
        assert 21399999 not in c2130_npc_ids
        # The vanilla c2130 variant survives.
        assert 21300000 in c2130_npc_ids

    def test_roster_missing_all_variants_key(self):
        # Defensive: if roster has no 'all_variants' key, the function
        # creates one.
        pack = _make_pack(enabled=True)
        tags = {}
        roster = {}
        stats = apply_er_heritage(pack, tags=tags, roster=roster)
        # all_variants now exists with the pack's 3 variants.
        assert len(roster['all_variants']) == 3
        assert stats['n_variants_added'] == 3

    def test_pack_internal_duplicate_cp_not_double_added(self):
        # Edge case: pack lists the same cp twice in variants_per_prefix.
        # Python dicts can't actually have duplicate keys, so this is
        # only relevant if a dict was constructed from items with dups
        # — but defensively, after we've contributed for a cp, a second
        # contribution should be skipped. Validates that the internal
        # existing_cps set gets updated as we go.
        pack = _make_pack(enabled=True, variants_per_prefix={
            'cER_NEW': [
                {'c_prefix': 'cER_NEW', 'npc_param_id': 99999999},
            ],
        })
        tags = {}
        roster = {'all_variants': []}

        # Apply twice — second application should be idempotent because
        # the cp now has variants from the first call.
        stats1 = apply_er_heritage(pack, tags=tags, roster=roster)
        stats2 = apply_er_heritage(pack, tags=tags, roster=roster)
        assert stats1['n_variants_added'] == 1
        assert stats2['n_variants_added'] == 0
        # Total variants = 1, not 2.
        assert len(roster['all_variants']) == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_double_apply_produces_same_state(self):
        pack = _make_pack(enabled=True)
        tags1, roster1 = _make_state()
        tags2, roster2 = _make_state()

        apply_er_heritage(pack, tags=tags1, roster=roster1)
        apply_er_heritage(pack, tags=tags2, roster=roster2)
        apply_er_heritage(pack, tags=tags2, roster=roster2)

        assert tags1 == tags2
        assert roster1 == roster2

    def test_second_apply_reports_zero_added(self):
        pack = _make_pack(enabled=True)
        tags, roster = _make_state()

        stats1 = apply_er_heritage(pack, tags=tags, roster=roster)
        stats2 = apply_er_heritage(pack, tags=tags, roster=roster)

        assert stats1['n_tags_added'] == 2
        assert stats1['n_variants_added'] == 3
        assert stats2['n_tags_added'] == 0
        assert stats2['n_variants_added'] == 0


# ---------------------------------------------------------------------------
# Integration: real er_heritage_imports.json
# ---------------------------------------------------------------------------

class TestAgainstRealErHeritage:
    """Smoke test against the real pack ships in the repo. Catches
    structural drift (missing fields, schema changes) that synthetic
    tests miss.
    """

    def test_real_pack_loads_against_empty_state(self):
        import json
        import os

        REPO_ROOT = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(REPO_ROOT, 'data',
                            'er_heritage_imports.json')
        if not os.path.isfile(path):
            pytest.skip('er_heritage_imports.json not present')

        with open(path, encoding='utf-8') as f:
            pack = json.load(f)
        # Force enabled regardless of file contents.
        pack.setdefault('_meta', {})['enabled'] = True

        # Empty state — every contribution should land.
        tags = {}
        roster = {'all_variants': []}
        stats = apply_er_heritage(pack, tags=tags, roster=roster)

        assert stats['enabled'] is True
        # Should add at least one tag and one variant — proves the
        # function actually reads the pack's structure correctly.
        assert stats['n_tags_added'] >= 1
        assert stats['n_variants_added'] >= 1
        # Tag count should match what the pack declares.
        assert stats['n_tags_added'] == len(pack.get('tags', {}))

    def test_real_pack_vanilla_wins_against_engine_state(self):
        # When applied against the FULL engine state, the pack should
        # contribute fewer entries (vanilla-wins skips overlaps with
        # base nr_enemy_tags.json / heritage_pack / post_dlc_dump).
        import io
        import json
        import os
        import sys
        from contextlib import redirect_stdout

        REPO_ROOT = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(REPO_ROOT, 'data',
                            'er_heritage_imports.json')
        if not os.path.isfile(path):
            pytest.skip('er_heritage_imports.json not present')

        with open(path, encoding='utf-8') as f:
            pack = json.load(f)
        pack.setdefault('_meta', {})['enabled'] = True

        sys.path.insert(0, REPO_ROOT)
        import oops_v3
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = oops_v3.load_data()

        # Copy state so the engine-fixture other tests reuse stays clean.
        tags_copy = dict(tags)
        roster_copy = {'all_variants': list(roster['all_variants'])}

        # Re-apply the pack against the already-loaded state. Should be
        # a no-op: load_data already applied it, so every cp is now in
        # the state. Stats should be 0 added.
        stats = apply_er_heritage(pack,
                                  tags=tags_copy, roster=roster_copy)
        assert stats['enabled'] is True
        assert stats['n_tags_added'] == 0, (
            f'Re-applying er_heritage to already-loaded state added '
            f'{stats["n_tags_added"]} tags — vanilla-wins is broken')
        assert stats['n_variants_added'] == 0, (
            f'Re-applying er_heritage added '
            f'{stats["n_variants_added"]} variants — vanilla-wins is broken')
