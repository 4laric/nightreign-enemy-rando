"""Tests for dev/distribute_stacked_repositions.py — the stacking-aware
reposition distributor."""
import math
import sys
from pathlib import Path

import pytest

# Make dev/ importable
HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE / 'dev'))
import distribute_stacked_repositions as ds


class TestDistributeStack:
    """The core algorithm — given a stack and a leaf extent, produce
    N distinct positions within the leaf that preserve vanilla layout
    where possible."""

    def test_simple_two_entry_stack(self):
        # Two entries with vanilla offsets that fit in the leaf
        entries = [
            ('5', {'from_pos': [0, 2, -5]}),  # offset (5, 0) from centroid
            ('8', {'from_pos': [10, 2, -5]}),  # offset (-5, 0)
        ]
        leaf_extent = 10.0
        center = (5.0, -5.0)  # vanilla centroid = leaf center
        new = ds.distribute_stack(entries, leaf_extent, center)
        assert len(new) == 2
        (pi5, p5), (pi8, p8) = new
        assert pi5 == '5' and pi8 == '8'
        # New positions should differ from each other
        d = math.hypot(p5[0] - p8[0], p5[1] - p8[1])
        assert d > 0.1, f'entries co-located: {p5} vs {p8}'

    def test_origin_sentinel_gets_fallback(self):
        # One entry has from_pos=(0,0,0) — origin sentinel
        entries = [
            ('5', {'from_pos': [3, 2, -5]}),
            ('11', {'from_pos': [0, 0, 0]}),  # sentinel
        ]
        leaf_extent = 5.0
        center = (1.0, -2.0)
        new = ds.distribute_stack(entries, leaf_extent, center)
        # Both should have distinct, finite positions
        assert all(isinstance(x, (int, float)) for _, (x, z) in new for x in (x, z))
        d = math.hypot(new[0][1][0] - new[1][1][0],
                       new[0][1][1] - new[1][1][1])
        assert d > 0.1, 'sentinel entry stacked with real entry'

    def test_no_two_entries_co_located(self):
        # 4-entry stack with vanilla offsets that should preserve shape
        entries = [
            ('0', {'from_pos': [1, 2, 1]}),
            ('1', {'from_pos': [-1, 2, 1]}),
            ('2', {'from_pos': [-1, 2, -1]}),
            ('3', {'from_pos': [1, 2, -1]}),
        ]
        leaf_extent = 5.0
        center = (0.0, 0.0)
        new = ds.distribute_stack(entries, leaf_extent, center)
        # All 4 positions should be pairwise distinct (>= 0.05m apart)
        for i in range(len(new)):
            for j in range(i):
                d = math.hypot(new[i][1][0] - new[j][1][0],
                               new[i][1][1] - new[j][1][1])
                assert d > 0.05, f'pi={new[i][0]} and pi={new[j][0]} too close ({d:.3f}m)'

    def test_tight_leaf_with_many_entries(self):
        # Worst case: 5 entries in a 1m leaf. Geometrically constrained.
        # Should still produce 5 distinct positions, even if cramped.
        entries = [
            (f'{i}', {'from_pos': [i, 2, i]}) for i in range(5)
        ]
        leaf_extent = 1.0
        center = (2.0, 2.0)
        new = ds.distribute_stack(entries, leaf_extent, center)
        # All distinct (> 0.01m apart — minimum threshold for game engine)
        positions = [p for _, p in new]
        for i in range(len(positions)):
            for j in range(i):
                d = math.hypot(positions[i][0] - positions[j][0],
                               positions[i][1] - positions[j][1])
                assert d > 0.01, (
                    f'entries {i} and {j} effectively co-located ({d:.4f}m) '
                    'even with tiny leaf — algorithm regression')

    def test_all_positions_within_leaf(self):
        # No entry should be pushed outside the leaf radius
        entries = [
            ('0', {'from_pos': [10, 2, 10]}),   # far from leaf
            ('1', {'from_pos': [-10, 2, 10]}),
            ('2', {'from_pos': [-10, 2, -10]}),
            ('3', {'from_pos': [10, 2, -10]}),
        ]
        leaf_extent = 2.0
        center = (0.0, 0.0)
        new = ds.distribute_stack(entries, leaf_extent, center)
        radius_limit = leaf_extent / 2.0
        for pi, (x, z) in new:
            dist = math.hypot(x - center[0], z - center[1])
            assert dist <= radius_limit + 0.01, (
                f'pi={pi} pushed beyond leaf radius: '
                f'dist={dist:.3f}, limit={radius_limit:.3f}')

    def test_preserves_vanilla_shape_when_feasible(self):
        # When the vanilla cluster fits within the leaf, the relative
        # offsets should be preserved (scale ≈ 1.0). The result should
        # be a translation, not a deformation.
        entries = [
            ('0', {'from_pos': [10.5, 2, 10]}),
            ('1', {'from_pos': [9.5, 2, 10]}),
            ('2', {'from_pos': [10, 2, 10.5]}),
        ]
        # Compute the real vanilla centroid (not assumed)
        positions = [e[1]['from_pos'] for e in entries]
        cx_van = sum(p[0] for p in positions) / len(positions)  # 10.0
        cz_van = sum(p[2] for p in positions) / len(positions)  # 10.167
        # Max vanilla offset magnitude = max(|(p - centroid)|)
        offsets = [(p[0] - cx_van, p[2] - cz_van) for p in positions]
        max_mag = max(math.hypot(*o) for o in offsets)
        # leaf_extent = 2.0 → usable_radius = 0.6 (after SAFETY_BUFFER)
        # If max_mag < 0.6, scale = 1.0 (vanilla shape preserved exactly).
        leaf_extent = 2.0
        usable_radius = leaf_extent / 2.0 - ds.SAFETY_BUFFER  # 0.6
        assert max_mag < usable_radius, (
            'test precondition: vanilla cluster fits leaf without scaling')
        center = (5.0, 5.0)
        new = ds.distribute_stack(entries, leaf_extent, center)
        # Translated offsets should match vanilla offsets exactly
        for (pi, (x, z)), pos in zip(new, positions):
            expected_x = center[0] + (pos[0] - cx_van)
            expected_z = center[1] + (pos[2] - cz_van)
            assert abs(x - expected_x) < 0.05, (
                f'pi={pi} X drifted from vanilla shape: '
                f'got {x:.3f}, expected ~{expected_x:.3f}')
            assert abs(z - expected_z) < 0.05, (
                f'pi={pi} Z drifted from vanilla shape: '
                f'got {z:.3f}, expected ~{expected_z:.3f}')


class TestFindStacks:
    """The scanner — find target XYZs shared by 2+ entries."""

    def test_finds_obvious_stack(self):
        rd = {
            'proposals': {
                'm00.msb': {
                    '1': {'to_pos_center': [1, 2, 3], 'from_pos': [0, 0, 0]},
                    '2': {'to_pos_center': [1, 2, 3], 'from_pos': [0, 0, 0]},
                    '3': {'to_pos_center': [9, 9, 9], 'from_pos': [0, 0, 0]},
                }
            }
        }
        stacks = ds.find_stacks(rd, min_stack=2)
        assert len(stacks) == 1
        msb, pos, entries = stacks[0]
        assert msb == 'm00.msb'
        assert pos == (1.0, 2.0, 3.0)
        assert len(entries) == 2
        pis = {e[0] for e in entries}
        assert pis == {'1', '2'}

    def test_skips_entries_with_manual_override(self):
        # Manual overrides should be respected — don't second-guess them
        rd = {
            'proposals': {
                'm00.msb': {
                    '1': {'to_pos_center': [1, 2, 3], 'from_pos': [0, 0, 0],
                          'manual_override': {'reason': 'test'}},
                    '2': {'to_pos_center': [1, 2, 3], 'from_pos': [0, 0, 0]},
                }
            }
        }
        stacks = ds.find_stacks(rd, min_stack=2)
        # Only one entry at (1,2,3) after filtering out the overridden one
        assert len(stacks) == 0

    def test_min_stack_threshold(self):
        # min_stack=3 should NOT match a 2-entry stack
        rd = {
            'proposals': {
                'm00.msb': {
                    '1': {'to_pos_center': [1, 2, 3], 'from_pos': [0, 0, 0]},
                    '2': {'to_pos_center': [1, 2, 3], 'from_pos': [0, 0, 0]},
                }
            }
        }
        stacks = ds.find_stacks(rd, min_stack=3)
        assert len(stacks) == 0
        stacks = ds.find_stacks(rd, min_stack=2)
        assert len(stacks) == 1


class TestMountRiderPairRecollapse:
    """v0.26.14 Pass 3 — re-collapse mount/rider pairs that the
    distribution passes split apart."""

    def test_rider_mount_pairs_in_sync_with_engine(self):
        """The local RIDER_MOUNT_PAIRS mirror must match the engine's
        oops_v3.RIDER_MOUNT_PAIRS exactly (same pairs, same rider/mount
        order — Pass 3 relies on tuple[0]=rider, tuple[1]=mount)."""
        sys.path.insert(0, str(HERE))
        import oops_v3
        assert set(ds.RIDER_MOUNT_PAIRS) == set(oops_v3.RIDER_MOUNT_PAIRS), (
            'dev/distribute_stacked_repositions.py RIDER_MOUNT_PAIRS has '
            'drifted from oops_v3.RIDER_MOUNT_PAIRS — keep them in sync')

    def test_mount_rider_pair_of(self):
        # a real pair, either argument order
        assert ds._mount_rider_pair_of('c3170', 'c3180') == ('c3170', 'c3180')
        assert ds._mount_rider_pair_of('c3180', 'c3170') == ('c3170', 'c3180')
        # rider-type + mount-type that aren't a registered pair
        assert ds._mount_rider_pair_of('c3170', 'c4060') is None
        # unrelated c-prefixes
        assert ds._mount_rider_pair_of('c0000', 'c1000') is None
        # the same c-prefix twice is never a pair
        assert ds._mount_rider_pair_of('c4050', 'c4050') is None

    def test_detects_split_pair(self):
        # rider + mount, co-located in vanilla, resolved ~4m apart —
        # the m60_42_38_10 c3170/c3180 case.
        rd = {'proposals': {'m00.msb': {
            '10': {'src': 'c3170', 'from_pos': [-63.3, 233.8, -82.9],
                   'to_pos_center': [-84.8, 233.7, -85.0],
                   'to_pos_floor': [-84.8, 233.7, -85.0]},
            '14': {'src': 'c3180', 'from_pos': [-63.3, 233.8, -82.9],
                   'to_pos_center': [-84.8, 233.7, -81.0],
                   'to_pos_floor': [-84.8, 233.7, -81.0]},
        }}}
        splits = ds.find_mount_rider_splits(rd)
        assert len(splits) == 1
        s = splits[0]
        # c3170 is the rider, c3180 the mount (per RIDER_MOUNT_PAIRS order)
        assert s['rider_pi'] == '10' and s['mount_pi'] == '14'
        assert s['d_xz'] > 2.0

    def test_ignores_already_colocated_pair(self):
        # rider + mount whose resolved targets are still together (< 2m)
        rd = {'proposals': {'m00.msb': {
            '10': {'src': 'c3170', 'from_pos': [10, 2, 10.0],
                   'to_pos_center': [5, 5, 5.0]},
            '14': {'src': 'c3180', 'from_pos': [10, 2, 10.5],
                   'to_pos_center': [5, 5, 5.3]},
        }}}
        assert ds.find_mount_rider_splits(rd) == []

    def test_ignores_far_apart_vanilla_positions(self):
        # c3170 + c3180 but NOT co-located in vanilla — two unrelated
        # chrs of rider/mount type, not an actual mounted pair.
        rd = {'proposals': {'m00.msb': {
            '10': {'src': 'c3170', 'from_pos': [0, 2, 0.0],
                   'to_pos_center': [5, 5, 5.0]},
            '14': {'src': 'c3180', 'from_pos': [50, 2, 50.0],
                   'to_pos_center': [5, 5, 99.0]},
        }}}
        assert ds.find_mount_rider_splits(rd) == []

    def test_ignores_non_pair_cprefixes(self):
        # two co-located, split entries that are not a mount/rider pair
        rd = {'proposals': {'m00.msb': {
            '1': {'src': 'c0000', 'from_pos': [0, 2, 0.0],
                  'to_pos_center': [5, 5, 5.0]},
            '2': {'src': 'c1000', 'from_pos': [0, 2, 0.0],
                  'to_pos_center': [5, 5, 99.0]},
        }}}
        assert ds.find_mount_rider_splits(rd) == []
