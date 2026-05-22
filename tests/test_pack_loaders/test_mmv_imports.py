"""Tests for engine.pack_loaders.mmv_imports.apply_mmv_imports.

mmv has the broadest behavior surface of the three loaders:
  - Authoritative tag override (NOT vanilla-wins)
  - npc_param_id variant dedup
  - Caliber + strict-NB tier-set contributions
  - Three-category blacklist
  - Cross-engine origin_game guard (DS1, BB)
  - Mount-component tier guard
  - Order dependencies between the three exclusion paths

Tests cover each path independently plus the order dependencies.
"""
import copy

import pytest

from engine.pack_loaders import mmv_imports as mmv_mod
from engine.pack_loaders.mmv_imports import apply_mmv_imports


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pack(enabled=True, **overrides):
    """Build a synthetic mmv_imports.json-shaped dict.

    Defaults to a small pack with one nightlord, one night_boss, one
    miniboss, no exclusions. Override individual sections via kwargs.
    """
    pack = {
        '_meta': {'enabled': enabled} if enabled is not None else {},
        'tags': {
            'cMMV_NL':  {'name': 'MMV Nightlord',  'tier': 'nightlord',
                         'origin_game': 'ER'},
            'cMMV_NB':  {'name': 'MMV NightBoss',  'tier': 'night_boss',
                         'origin_game': 'SoTE'},
            'cMMV_MID': {'name': 'MMV Miniboss',   'tier': 'miniboss',
                         'origin_game': 'DS3'},
        },
        'variants': [
            {'c_prefix': 'cMMV_NL',  'npc_param_id': 10000000},
            {'c_prefix': 'cMMV_NB',  'npc_param_id': 20000000},
            {'c_prefix': 'cMMV_MID', 'npc_param_id': 30000000},
        ],
        'blacklist_when_active': {
            'ctd_unidentified': [],
            'dlc_assets_missing_in_mmv': [],
            'ai_broken': [],
        },
    }
    for k, v in overrides.items():
        pack[k] = v
    return pack


def _make_state():
    """Synthetic baseline state."""
    tags = {
        'c2130': {'name': 'Margit', '_source': 'nr_placed',
                  'tier': 'night_boss'},
    }
    roster = {
        'all_variants': [
            {'c_prefix': 'c2130', 'npc_param_id': 21300000},
        ],
    }
    return tags, roster


# ---------------------------------------------------------------------------
# Disabled path
# ---------------------------------------------------------------------------

class TestDisabledIsNoOp:
    def test_disabled_adds_nothing(self):
        pack = _make_pack(enabled=False)
        tags, roster = _make_state()
        tags_before = copy.deepcopy(tags)
        roster_before = copy.deepcopy(roster)
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['enabled'] is False
        assert tags == tags_before
        assert roster == roster_before

    def test_disabled_stats_shape_matches_enabled(self):
        # Caller .get() on stats keys without branching — both paths
        # need the same keys.
        pack = _make_pack(enabled=False)
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        # All the keys callers might read.
        for k in ('caliber_adds', 'strict_adds', 'blacklist',
                  'cross_engine_bans', 'mount_component_bans',
                  'blacklist_breakdown', 'cross_engine_origins_seen',
                  'n_tags_added', 'n_variants_added'):
            assert k in stats, f'disabled stats missing key {k!r}'


# ---------------------------------------------------------------------------
# Tag merge — authoritative override (NOT vanilla-wins)
# ---------------------------------------------------------------------------

class TestTagMergeAuthoritative:
    def test_new_cps_added(self):
        pack = _make_pack()
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['n_tags_added'] == 3
        assert 'cMMV_NL' in tags
        assert 'cMMV_NB' in tags
        assert 'cMMV_MID' in tags

    def test_existing_cps_overwritten(self):
        # Authoritative: if a pack cp already exists in tags, MMV's
        # version REPLACES it. Opposite of er_heritage's vanilla-wins.
        pack = _make_pack(tags={
            'c2130': {'name': 'MMV-Margit-Override', 'tier': 'nightlord',
                      'origin_game': 'ER'},
        })
        tags, roster = _make_state()
        apply_mmv_imports(pack, tags=tags, roster=roster)
        # MMV's tag wins.
        assert tags['c2130']['name'] == 'MMV-Margit-Override'
        assert tags['c2130']['tier'] == 'nightlord'


# ---------------------------------------------------------------------------
# Tier set contributions — caliber / strict-NB
# ---------------------------------------------------------------------------

class TestTierSetContributions:
    def test_night_boss_and_nightlord_feed_caliber(self):
        pack = _make_pack()
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['caliber_adds'] == {'cMMV_NL', 'cMMV_NB'}

    def test_only_nightlord_feeds_strict(self):
        pack = _make_pack()
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['strict_adds'] == {'cMMV_NL'}

    def test_miniboss_and_lower_feed_neither(self):
        # cMMV_MID (miniboss) is in tags but feeds neither set.
        pack = _make_pack()
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cMMV_MID' not in stats['caliber_adds']
        assert 'cMMV_MID' not in stats['strict_adds']

    def test_expects_boss_arena_feeds_arena_only_adds(self):
        # v0.24.22 (Phase 11): apply_mmv_imports returns the cps with
        # expects_boss_arena=True in stats so the caller's post-loader
        # auto-extend can consume them without reaching into raw mmv dict.
        pack = _make_pack(tags={
            'cArenaNL': {'name': 'AN', 'tier': 'nightlord',
                         'origin_game': 'ER',
                         'expects_boss_arena': True},
            'cArenaNB': {'name': 'AB', 'tier': 'night_boss',
                         'origin_game': 'ER',
                         'expects_boss_arena': True},
            'cFieldNB': {'name': 'FB', 'tier': 'night_boss',
                         'origin_game': 'ER'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['arena_only_adds'] == {'cArenaNL', 'cArenaNB'}


# ---------------------------------------------------------------------------
# Variant merge — npc_param_id dedup
# ---------------------------------------------------------------------------

class TestVariantMerge:
    def test_new_variants_added(self):
        pack = _make_pack()
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['n_variants_added'] == 3
        npc_ids = {v['npc_param_id'] for v in roster['all_variants']}
        assert {10000000, 20000000, 30000000}.issubset(npc_ids)

    def test_duplicate_npc_id_skipped(self):
        # If npc_param_id already exists in roster, skip — even if
        # other fields differ (e.g., a c_prefix change).
        pack = _make_pack(variants=[
            {'c_prefix': 'cOVERRIDE', 'npc_param_id': 21300000},  # vanilla c2130 nid
            {'c_prefix': 'cMMV_NL', 'npc_param_id': 99999999},     # new
        ])
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['n_variants_added'] == 1
        # Vanilla c2130 entry not overwritten.
        v_21300000 = next(v for v in roster['all_variants']
                          if v['npc_param_id'] == 21300000)
        assert v_21300000['c_prefix'] == 'c2130'  # not cOVERRIDE

    def test_pack_internal_duplicates_handled(self):
        # Pack lists the same npc_param_id twice. Second occurrence
        # should be skipped because existing_npc_ids grows as we go.
        pack = _make_pack(variants=[
            {'c_prefix': 'cMMV_NL', 'npc_param_id': 12345},
            {'c_prefix': 'cMMV_NL', 'npc_param_id': 12345},  # dup
        ])
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['n_variants_added'] == 1

    def test_roster_missing_all_variants_key(self):
        pack = _make_pack()
        tags = {}
        roster = {}
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'all_variants' in roster
        assert stats['n_variants_added'] == 3


# ---------------------------------------------------------------------------
# Blacklist (three sub-categories)
# ---------------------------------------------------------------------------

class TestBlacklist:
    def test_three_categories_unioned(self):
        pack = _make_pack(blacklist_when_active={
            'ctd_unidentified': ['cBL_CTD_1', 'cBL_CTD_2'],
            'dlc_assets_missing_in_mmv': ['cBL_DLC_1'],
            'ai_broken': ['cBL_AI_1', 'cBL_AI_2', 'cBL_AI_3'],
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['blacklist'] == {
            'cBL_CTD_1', 'cBL_CTD_2',
            'cBL_DLC_1',
            'cBL_AI_1', 'cBL_AI_2', 'cBL_AI_3',
        }

    def test_breakdown_preserved_in_stats(self):
        pack = _make_pack(blacklist_when_active={
            'ctd_unidentified': ['cCTD'],
            'dlc_assets_missing_in_mmv': ['cDLC'],
            'ai_broken': ['cAI'],
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        bd = stats['blacklist_breakdown']
        assert bd['ctd_unidentified'] == {'cCTD'}
        assert bd['dlc_assets_missing_in_mmv'] == {'cDLC'}
        assert bd['ai_broken'] == {'cAI'}

    def test_missing_blacklist_section(self):
        pack = _make_pack()
        # Default fixture has empty lists; remove the whole section.
        del pack['blacklist_when_active']
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['blacklist'] == set()


# ---------------------------------------------------------------------------
# Cross-engine guard
# ---------------------------------------------------------------------------

class TestCrossEngineGuard:
    def test_ds1_origin_banned(self):
        pack = _make_pack(tags={
            'cMANUS': {'name': 'Manus', 'tier': 'nightlord',
                       'origin_game': 'DS1'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cMANUS' in stats['cross_engine_bans']

    def test_bb_origin_banned(self):
        pack = _make_pack(tags={
            'cBB_MOB': {'name': 'BB Mob', 'tier': 'miniboss',
                        'origin_game': 'BB'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cBB_MOB' in stats['cross_engine_bans']

    def test_er_sote_ds3_not_banned(self):
        # The default fixture has ER, SoTE, DS3 origins. None should
        # be in the cross-engine ban set.
        pack = _make_pack()
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['cross_engine_bans'] == set()

    def test_unknown_origin_not_banned(self):
        # The MMV manifest contains some entries with origin_game='?'.
        # These are placeholders, NOT confirmed cross-engine, so the
        # ban-list policy says: don't ban.
        pack = _make_pack(tags={
            'cUNK': {'name': 'Unknown', 'tier': 'miniboss',
                     'origin_game': '?'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats['cross_engine_bans'] == set()

    def test_allowlist_override_bypasses_guard(self, monkeypatch):
        # If a cp's origin is DS1 but it's in the allowlist override,
        # don't ban.
        monkeypatch.setattr(mmv_mod, 'MMV_ORIGIN_ALLOWLIST_OVERRIDE',
                            frozenset({'cMANUS_OK'}))
        pack = _make_pack(tags={
            'cMANUS_OK':  {'name': 'OK Manus', 'tier': 'nightlord',
                           'origin_game': 'DS1'},
            'cMANUS_BAN': {'name': 'Ban Manus', 'tier': 'nightlord',
                           'origin_game': 'DS1'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cMANUS_OK' not in stats['cross_engine_bans']
        assert 'cMANUS_BAN' in stats['cross_engine_bans']

    def test_origins_seen_grouped_by_origin(self):
        pack = _make_pack(tags={
            'cDS1_A': {'origin_game': 'DS1', 'tier': 'miniboss'},
            'cDS1_B': {'origin_game': 'DS1', 'tier': 'miniboss'},
            'cBB_X':  {'origin_game': 'BB',  'tier': 'miniboss'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        seen = stats['cross_engine_origins_seen']
        assert set(seen.keys()) == {'DS1', 'BB'}
        assert set(seen['DS1']) == {'cDS1_A', 'cDS1_B'}
        assert set(seen['BB']) == {'cBB_X'}

    def test_already_blacklisted_not_double_counted(self):
        # If a DS1 origin cp is ALSO in the blacklist, the cross-engine
        # guard skips it (already excluded — no double count).
        pack = _make_pack(
            tags={
                'cBOTH': {'origin_game': 'DS1', 'tier': 'miniboss'},
            },
            blacklist_when_active={
                'ctd_unidentified': ['cBOTH'],
                'dlc_assets_missing_in_mmv': [],
                'ai_broken': [],
            })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cBOTH' in stats['blacklist']
        assert 'cBOTH' not in stats['cross_engine_bans']


# ---------------------------------------------------------------------------
# Mount-component guard
# ---------------------------------------------------------------------------

class TestMountComponentGuard:
    def test_mount_component_tier_banned(self):
        pack = _make_pack(tags={
            'cMOUNT': {'name': 'Black Knight Horse',
                       'tier': 'mount_component',
                       'origin_game': 'ER'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cMOUNT' in stats['mount_component_bans']

    def test_already_blacklisted_not_in_mount_bans(self):
        pack = _make_pack(
            tags={'cMOUNT': {'tier': 'mount_component',
                             'origin_game': 'ER'}},
            blacklist_when_active={
                'ctd_unidentified': ['cMOUNT'],
                'dlc_assets_missing_in_mmv': [],
                'ai_broken': [],
            })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cMOUNT' in stats['blacklist']
        assert 'cMOUNT' not in stats['mount_component_bans']

    def test_already_cross_engine_banned_not_in_mount_bans(self):
        # mount_component + DS1 origin: cross-engine catches it first.
        pack = _make_pack(tags={
            'cMOUNT_DS1': {'tier': 'mount_component',
                           'origin_game': 'DS1'},
        })
        tags, roster = _make_state()
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert 'cMOUNT_DS1' in stats['cross_engine_bans']
        assert 'cMOUNT_DS1' not in stats['mount_component_bans']


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_double_apply_produces_same_state(self):
        pack = _make_pack()
        tags1, roster1 = _make_state()
        tags2, roster2 = _make_state()

        apply_mmv_imports(pack, tags=tags1, roster=roster1)
        apply_mmv_imports(pack, tags=tags2, roster=roster2)
        apply_mmv_imports(pack, tags=tags2, roster=roster2)

        assert tags1 == tags2
        assert roster1 == roster2

    def test_second_apply_reports_zero_variants_added(self):
        # Tags will still be n=3 because AUTHORITATIVE override
        # re-writes them every time. But variants are dedup'd by
        # npc_param_id, so second apply finds them all present.
        pack = _make_pack()
        tags, roster = _make_state()
        stats1 = apply_mmv_imports(pack, tags=tags, roster=roster)
        stats2 = apply_mmv_imports(pack, tags=tags, roster=roster)
        assert stats1['n_variants_added'] == 3
        assert stats2['n_variants_added'] == 0
        # But authoritative tag writes always happen.
        assert stats1['n_tags_added'] == 3
        assert stats2['n_tags_added'] == 3


# ---------------------------------------------------------------------------
# Integration against the real mmv_imports.json
# ---------------------------------------------------------------------------

class TestAgainstRealMmv:
    def test_real_pack_against_engine_state(self):
        # Smoke test: the real mmv_imports.json loads against the
        # already-loaded engine state. Caller can't expect exact
        # contribution counts (manifest content evolves), but
        # structural sanity (returns enabled stats, contributes
        # non-zero to at least caliber OR strict OR variants) is
        # checkable.
        import io
        import json
        import os
        import sys
        from contextlib import redirect_stdout

        REPO_ROOT = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(REPO_ROOT, 'data', 'mmv_imports.json')
        if not os.path.isfile(path):
            pytest.skip('mmv_imports.json not present')

        with open(path, encoding='utf-8') as f:
            pack = json.load(f)
        pack.setdefault('_meta', {})['enabled'] = True

        sys.path.insert(0, REPO_ROOT)
        import oops_v3
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = oops_v3.load_data()
        # Copy so we don't mutate the engine fixture other tests use.
        tags_copy = dict(tags)
        roster_copy = {'all_variants': list(roster['all_variants'])}

        # Apply against already-loaded state — variant additions
        # should be 0 (already merged at load_data time), tag adds
        # should equal the pack's tag count (authoritative re-writes).
        stats = apply_mmv_imports(pack,
                                  tags=tags_copy, roster=roster_copy)
        assert stats['enabled'] is True
        assert stats['n_variants_added'] == 0, (
            f"Re-applying MMV added {stats['n_variants_added']} "
            f"variants — dedup is broken")
        assert stats['n_tags_added'] == len(pack.get('tags', {}))

    def test_real_pack_against_empty_state(self):
        # Same pack against empty state — should contribute everything.
        import json
        import os

        REPO_ROOT = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(REPO_ROOT, 'data', 'mmv_imports.json')
        if not os.path.isfile(path):
            pytest.skip('mmv_imports.json not present')

        with open(path, encoding='utf-8') as f:
            pack = json.load(f)
        pack.setdefault('_meta', {})['enabled'] = True

        tags = {}
        roster = {'all_variants': []}
        stats = apply_mmv_imports(pack, tags=tags, roster=roster)

        assert stats['enabled'] is True
        assert stats['n_tags_added'] > 0
        assert stats['n_variants_added'] > 0
        # The real pack has at least some boss-tier content.
        assert (stats['caliber_adds'] or stats['strict_adds']), (
            "Real MMV pack didn't contribute any caliber/strict cps")
