"""Tests for dev/extend_repositions_to_phase_siblings.py.

Exercises the cross-phase auto-extension tool with synthetic data:
position-match success path, position-mismatch skip, already-has-entry
skip, missing-pi skip.
"""
import json
import os
import sys
import tempfile

import pytest

# Add dev/ to import path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'dev'))
import extend_repositions_to_phase_siblings as ext  # noqa: E402


# --- helpers ------------------------------------------------------------

def make_playtest_entry(from_pos, to_pos, reason='playtest_freeze_reposition',
                        status='playtest_freeze'):
    return {
        'from_pos': list(from_pos),
        'to_pos_center': list(to_pos),
        'to_pos_floor': list(to_pos),
        'displacement': 7.07,
        'status': status,
        'src': 'playtest_seed_TEST',
        'confidence': 'manual',
        'tier': 1,
        'evidence': 'Test fixture',
        'manual_override': {
            'reason': reason,
            'description': 'Test entry',
            'playtest_verified': False,
            'set_by': 'test',
        },
    }


# --- core function tests ------------------------------------------------

class TestParseTileId:
    def test_overworld_msb_parses(self):
        assert ext.parse_tile_id('m60_43_36_00.msb') == ('m60_43_36', '00')
        assert ext.parse_tile_id('m60_42_36_50.msb') == ('m60_42_36', '50')

    def test_non_overworld_returns_none(self):
        assert ext.parse_tile_id('m46_77_00_00.msb') is None
        assert ext.parse_tile_id('m43_50_00_00.msb') is None
        assert ext.parse_tile_id('garbage') is None


class TestPositionsMatch:
    def test_exact_match(self):
        assert ext.positions_match([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])

    def test_within_tolerance(self):
        assert ext.positions_match([1.0, 2.0, 3.0], [1.005, 2.0, 3.0])

    def test_outside_tolerance(self):
        assert not ext.positions_match([1.0, 2.0, 3.0], [1.1, 2.0, 3.0])

    def test_one_axis_off(self):
        assert not ext.positions_match([1.0, 2.0, 3.0], [1.0, 2.0, 3.5])

    def test_none_arg(self):
        assert not ext.positions_match(None, [1.0, 2.0, 3.0])
        assert not ext.positions_match([1.0, 2.0, 3.0], None)


# --- end-to-end tests ---------------------------------------------------

class TestFindExtensionCandidates:
    @pytest.fixture
    def synthetic_data(self):
        """Three phase tiles m60_99_99_00/_10/_20 share pi=5 position.
        m60_99_99_50 has different content at pi=5. Only the _00 entry
        exists; we expect _10 and _20 to be candidates."""
        slot_repos = {
            'metadata': {'total_relocations': 1},
            'proposals': {
                'm60_99_99_00.msb': {
                    '5': make_playtest_entry(
                        from_pos=[100.0, 50.0, 200.0],
                        to_pos=[95.0, 50.0, 195.0]),
                },
            }
        }
        all_positions = {
            'positions': {
                'm60_99_99_00.msb': {'5': [100.0, 50.0, 200.0]},
                'm60_99_99_10.msb': {'5': [100.0, 50.0, 200.0]},  # same → extend
                'm60_99_99_20.msb': {'5': [100.0, 50.0, 200.0]},  # same → extend
                'm60_99_99_50.msb': {'5': [-30.0, 80.0, -50.0]},  # different
            }
        }
        return slot_repos, all_positions

    def test_finds_two_phase_siblings(self, synthetic_data):
        slot_repos, all_positions = synthetic_data
        candidates = ext.find_extension_candidates(
            slot_repos, all_positions, ext.is_manual_playtest_entry)
        actionable = [c for c in candidates if c['skip_reason'] is None]
        assert len(actionable) == 2
        sibling_msbs = sorted(c['sibling_msb'] for c in actionable)
        assert sibling_msbs == ['m60_99_99_10.msb', 'm60_99_99_20.msb']

    def test_50_phase_skipped_by_position_mismatch(self, synthetic_data):
        slot_repos, all_positions = synthetic_data
        candidates = ext.find_extension_candidates(
            slot_repos, all_positions, ext.is_manual_playtest_entry,
            verbose=True)
        # In verbose mode we get skips too
        skip_50 = [c for c in candidates
                   if c['sibling_msb'] == 'm60_99_99_50.msb'
                   and c['skip_reason'] is not None]
        assert len(skip_50) == 1
        assert 'position_mismatch' in skip_50[0]['skip_reason']

    def test_already_has_entry_skipped(self, synthetic_data):
        """If _10 already has an entry, only _20 should be a candidate."""
        slot_repos, all_positions = synthetic_data
        # Add a pre-existing entry at _10
        slot_repos['proposals']['m60_99_99_10.msb'] = {
            '5': make_playtest_entry(
                from_pos=[100.0, 50.0, 200.0],
                to_pos=[99.0, 51.0, 199.0])  # different shift
        }
        candidates = ext.find_extension_candidates(
            slot_repos, all_positions, ext.is_manual_playtest_entry)
        actionable = [c for c in candidates if c['skip_reason'] is None]
        # _00→_20 and _10→_20 are both actionable; _00→_10 skipped (already_has)
        sibling_msbs = sorted(c['sibling_msb'] for c in actionable)
        assert sibling_msbs == ['m60_99_99_20.msb', 'm60_99_99_20.msb']

    def test_missing_pi_in_sibling_skipped(self):
        """If sibling MSB exists but doesn't have a part at this pi,
        no candidate."""
        slot_repos = {
            'metadata': {'total_relocations': 1},
            'proposals': {
                'm60_99_99_00.msb': {
                    '5': make_playtest_entry([0,0,0], [1,0,0]),
                }
            }
        }
        all_positions = {
            'positions': {
                'm60_99_99_00.msb': {'5': [0.0, 0.0, 0.0]},
                'm60_99_99_10.msb': {},  # no pi=5 here
            }
        }
        candidates = ext.find_extension_candidates(
            slot_repos, all_positions, ext.is_manual_playtest_entry)
        actionable = [c for c in candidates if c['skip_reason'] is None]
        assert len(actionable) == 0

    def test_non_overworld_msb_ignored(self):
        """Source MSB that isn't m60_* (e.g. m46_77 arena MSB) is
        not processed — there's no phase-sibling concept for it."""
        slot_repos = {
            'metadata': {'total_relocations': 1},
            'proposals': {
                'm46_77_00_00.msb': {
                    '8': make_playtest_entry([0,0,0], [1,0,0])
                }
            }
        }
        all_positions = {'positions': {'m46_77_00_00.msb': {'8': [0,0,0]}}}
        candidates = ext.find_extension_candidates(
            slot_repos, all_positions, ext.is_manual_playtest_entry)
        assert len(candidates) == 0

    def test_non_playtest_entry_ignored_by_default(self):
        """A reposition entry with status='elevated_narrow' (auto-built)
        is NOT considered for extension by default."""
        slot_repos = {
            'metadata': {'total_relocations': 1},
            'proposals': {
                'm60_99_99_00.msb': {
                    '5': {
                        'from_pos': [100.0, 50.0, 200.0],
                        'to_pos_center': [95.0, 50.0, 195.0],
                        'status': 'elevated_narrow',
                        # no manual_override block
                    }
                }
            }
        }
        all_positions = {
            'positions': {
                'm60_99_99_00.msb': {'5': [100.0, 50.0, 200.0]},
                'm60_99_99_10.msb': {'5': [100.0, 50.0, 200.0]},
            }
        }
        candidates = ext.find_extension_candidates(
            slot_repos, all_positions, ext.is_manual_playtest_entry)
        assert len(candidates) == 0


class TestBuildExtensionEntry:
    def test_extension_preserves_shift_and_position(self):
        source = make_playtest_entry(
            from_pos=[100.0, 50.0, 200.0],
            to_pos=[95.0, 50.0, 195.0])
        new = ext.build_extension_entry(
            source, 'm60_99_99_00.msb', '5', 'm60_99_99_10.msb',
            version_tag='v0.24.99')
        assert new['from_pos'] == [100.0, 50.0, 200.0]
        assert new['to_pos_center'] == [95.0, 50.0, 195.0]

    def test_extension_annotates_manual_override(self):
        source = make_playtest_entry([0,0,0], [1,0,0],
                                       reason='playtest_freeze_reposition')
        new = ext.build_extension_entry(
            source, 'm60_99_99_00.msb', '5', 'm60_99_99_10.msb',
            version_tag='v0.24.99')
        mo = new['manual_override']
        assert mo['reason'] == 'auto_phase_sibling_extension'
        assert mo['parent_fix']['msb'] == 'm60_99_99_00.msb'
        assert mo['parent_fix']['pi'] == '5'
        assert mo['parent_fix']['reason'] == 'playtest_freeze_reposition'
        assert mo['set_by'] == 'v0.24.99'
        assert mo['playtest_verified'] is False

    def test_extension_marks_src_field(self):
        source = make_playtest_entry([0,0,0], [1,0,0])
        new = ext.build_extension_entry(
            source, 'm60_99_99_00.msb', '5', 'm60_99_99_10.msb',
            version_tag='v0.24.99')
        assert new['src'].endswith('_phase_ext')

    def test_extension_does_not_mutate_source(self):
        """Important: deep-copy means the source entry stays unchanged."""
        source = make_playtest_entry([0,0,0], [1,0,0])
        source_copy = json.loads(json.dumps(source))
        ext.build_extension_entry(
            source, 'm60_99_99_00.msb', '5', 'm60_99_99_10.msb', 'v0')
        assert source == source_copy


class TestIdempotence:
    """Running the tool twice produces no new changes."""

    def test_second_run_finds_no_candidates(self, tmp_path):
        slot_repos_path = tmp_path / 'slot_repositions.json'
        positions_path = tmp_path / 'nr_all_part_positions.json'

        slot_repos = {
            'metadata': {'total_relocations': 1},
            'proposals': {
                'm60_99_99_00.msb': {
                    '5': make_playtest_entry([100.0, 50.0, 200.0],
                                              [95.0, 50.0, 195.0]),
                },
            },
        }
        all_positions = {
            'positions': {
                'm60_99_99_00.msb': {'5': [100.0, 50.0, 200.0]},
                'm60_99_99_10.msb': {'5': [100.0, 50.0, 200.0]},
                'm60_99_99_20.msb': {'5': [100.0, 50.0, 200.0]},
            }
        }
        slot_repos_path.write_text(json.dumps(slot_repos))
        positions_path.write_text(json.dumps(all_positions))

        # First pass — should find 2 candidates
        with open(slot_repos_path) as f:
            sr = json.load(f)
        with open(positions_path) as f:
            ap = json.load(f)
        candidates = ext.find_extension_candidates(
            sr, ap, ext.is_manual_playtest_entry)
        actionable = [c for c in candidates if c['skip_reason'] is None]
        assert len(actionable) == 2

        # Simulate apply (add entries directly)
        for c in actionable:
            new_entry = ext.build_extension_entry(
                c['source_entry'], c['source_msb'], c['source_pi'],
                c['sibling_msb'], 'test')
            sr['proposals'].setdefault(c['sibling_msb'], {})[c['sibling_pi']] = new_entry

        # Second pass — no new actionable candidates
        candidates_2 = ext.find_extension_candidates(
            sr, ap, ext.is_manual_playtest_entry)
        actionable_2 = [c for c in candidates_2 if c['skip_reason'] is None]
        assert len(actionable_2) == 0


class TestDuplicateProposals:
    """When two source entries both propose the same target, dedupe."""

    def test_two_sources_one_target_only_dedupe_in_apply(self):
        """If we already have entries at _00 AND _20, both propose
        extending to _10. find_extension_candidates returns 2 candidates
        (one per source), but the apply path dedupes to 1."""
        slot_repos = {
            'metadata': {'total_relocations': 2},
            'proposals': {
                'm60_99_99_00.msb': {
                    '5': make_playtest_entry([100.0, 50.0, 200.0],
                                              [95.0, 50.0, 195.0]),
                },
                'm60_99_99_20.msb': {
                    '5': make_playtest_entry([100.0, 50.0, 200.0],
                                              [95.0, 50.0, 195.0]),
                },
            },
        }
        all_positions = {
            'positions': {
                'm60_99_99_00.msb': {'5': [100.0, 50.0, 200.0]},
                'm60_99_99_10.msb': {'5': [100.0, 50.0, 200.0]},
                'm60_99_99_20.msb': {'5': [100.0, 50.0, 200.0]},
            }
        }
        candidates = ext.find_extension_candidates(
            slot_repos, all_positions, ext.is_manual_playtest_entry)
        actionable = [c for c in candidates if c['skip_reason'] is None]
        # Both sources propose extending to _10
        assert len(actionable) == 2
        # Both target the same (msb, pi)
        keys = {(c['sibling_msb'], c['sibling_pi']) for c in actionable}
        assert keys == {('m60_99_99_10.msb', '5')}
