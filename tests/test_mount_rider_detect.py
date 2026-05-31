"""Tests for the mount/rider pair-detection foundation (v0.26.15, cut 1).

Covers `_detect_mount_rider_slots` — the read-only pre-pass that finds
mount/rider Part pairs in an MSB — plus the V3_MOUNT_CLASS_POOL and
V3_MOUNT_RIDER_PILOT_PAIRS constants it depends on.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import oops_v3


# Synthetic-MSB stride: must exceed PART_OFF_POSITION + 12 so every
# part's model-index and position fields fit inside its slice.
STRIDE = oops_v3.PART_OFF_POSITION + 256


def _make_msb(parts_spec):
    """Build a minimal synthetic MSB for _detect_mount_rider_slots.

    parts_spec: list of (cp, (x, y, z)). Returns (data, parts,
    midx_to_cp) — each part gets a distinct model index, its c-prefix,
    and its world position written at the real engine offsets.
    """
    n = len(parts_spec)
    data = bytearray(n * STRIDE)
    midx_to_cp = {}
    entry_offsets = []
    for i, (cp, pos) in enumerate(parts_spec):
        po = i * STRIDE
        entry_offsets.append(po)
        struct.pack_into('<i', data, po + oops_v3.PART_OFF_MODEL_INDEX, i)
        struct.pack_into('<fff', data, po + oops_v3.PART_OFF_POSITION, *pos)
        midx_to_cp[i] = cp + '_0000'
    return data, {'entry_offsets': entry_offsets}, midx_to_cp


class TestMountClassConstants:
    """The pool / pilot constants the detection depends on."""

    def test_mount_class_pool_is_rider_mount_pairs_mount_halves(self):
        # V3_MOUNT_CLASS_POOL must be exactly the mount half of every
        # RIDER_MOUNT_PAIRS entry — NOT tier=='mount_component' (that
        # tier also tags riders like c4050).
        expected = {mount for _rider, mount in oops_v3.RIDER_MOUNT_PAIRS}
        assert oops_v3.V3_MOUNT_CLASS_POOL == expected
        # sanity: the five known mounts (incl. c5890 Black Knight Horse,
        # fabricated mounted pair added v0.27.13), no riders
        assert oops_v3.V3_MOUNT_CLASS_POOL == {'c3160', 'c3180',
                                               'c4060', 'c4363', 'c5890'}
        assert 'c4050' not in oops_v3.V3_MOUNT_CLASS_POOL  # Kaiden = rider

    def test_pilot_pairs_is_kaiden_only(self):
        # Cut 2's coordinated swap will touch ONLY the pilot pairs.
        assert oops_v3.V3_MOUNT_RIDER_PILOT_PAIRS == {('c4050', 'c4060')}
        # the touchy instances must NOT be pilot-active
        assert ('c3150', 'c3160') not in oops_v3.V3_MOUNT_RIDER_PILOT_PAIRS
        assert ('c4353', 'c4363') not in oops_v3.V3_MOUNT_RIDER_PILOT_PAIRS


class TestDetectMountRiderSlots:
    """_detect_mount_rider_slots — read-only pair detection."""

    def test_detects_kaiden_pair_pilot_active(self):
        data, parts, midx = _make_msb([
            ('c4050', (10.0, 2.0, 10.0)),   # Kaiden (rider)
            ('c4060', (10.0, 2.0, 10.0)),   # Kaiden's Horse (mount)
        ])
        out = oops_v3._detect_mount_rider_slots(data, parts, midx)
        assert len(out) == 1
        d = out[0]
        assert d['rider_pi'] == 0 and d['rider_cp'] == 'c4050'
        assert d['mount_pi'] == 1 and d['mount_cp'] == 'c4060'
        assert d['pilot_active'] is True
        assert d['dist'] == 0.0

    def test_detects_nights_cavalry_pair_not_pilot(self):
        # c3150 + c3160 IS a RIDER_MOUNT_PAIRS entry, so it's detected —
        # but it is NOT pilot-active (the user wants it left vanilla).
        data, parts, midx = _make_msb([
            ('c3150', (0.0, 0.0, 0.0)),
            ('c3160', (0.5, 0.0, 0.3)),
        ])
        out = oops_v3._detect_mount_rider_slots(data, parts, midx)
        assert len(out) == 1
        assert out[0]['rider_cp'] == 'c3150'
        assert out[0]['mount_cp'] == 'c3160'
        assert out[0]['pilot_active'] is False

    def test_ignores_far_apart_pair(self):
        # Right c-prefixes, but >2m apart — not a mounted pair.
        data, parts, midx = _make_msb([
            ('c4050', (0.0, 0.0, 0.0)),
            ('c4060', (10.0, 0.0, 0.0)),
        ])
        assert oops_v3._detect_mount_rider_slots(data, parts, midx) == []

    def test_ignores_non_pair_cps(self):
        # c4050's mount is c4060; c1000 is unrelated.
        data, parts, midx = _make_msb([
            ('c4050', (0.0, 0.0, 0.0)),
            ('c1000', (0.0, 0.0, 0.0)),
        ])
        assert oops_v3._detect_mount_rider_slots(data, parts, midx) == []

    def test_ignores_mount_without_rider(self):
        # A lone mount with no paired rider nearby.
        data, parts, midx = _make_msb([
            ('c4060', (0.0, 0.0, 0.0)),
            ('c4373', (0.5, 0.0, 0.0)),   # Foot Soldier — not a rider
        ])
        assert oops_v3._detect_mount_rider_slots(data, parts, midx) == []

    def test_detects_multiple_pairs(self):
        data, parts, midx = _make_msb([
            ('c4050', (0.0, 0.0, 0.0)),
            ('c4060', (0.0, 0.0, 0.0)),
            ('c4373', (50.0, 0.0, 50.0)),    # unrelated, far away
            ('c3170', (99.0, 0.0, 99.0)),    # Albinauric Archer (rider)
            ('c3180', (99.0, 0.0, 99.5)),    # Wolf (mount)
        ])
        out = oops_v3._detect_mount_rider_slots(data, parts, midx)
        assert len(out) == 2
        pairs = {(d['rider_cp'], d['mount_cp']) for d in out}
        assert pairs == {('c4050', 'c4060'), ('c3170', 'c3180')}
        # only the Kaiden pair is pilot-active
        kaiden = next(d for d in out if d['rider_cp'] == 'c4050')
        wolf = next(d for d in out if d['rider_cp'] == 'c3170')
        assert kaiden['pilot_active'] is True
        assert wolf['pilot_active'] is False

    def test_nearest_mount_wins(self):
        # One rider, two candidate mounts — the rider pairs with the
        # closer one.
        data, parts, midx = _make_msb([
            ('c4050', (0.0, 0.0, 0.0)),
            ('c4060', (1.5, 0.0, 0.0)),     # far-ish (still < 2m)
            ('c4060', (0.2, 0.0, 0.0)),     # closest
        ])
        out = oops_v3._detect_mount_rider_slots(data, parts, midx)
        assert len(out) == 1
        assert out[0]['mount_pi'] == 2   # the closer c4060

    def test_does_not_mutate_data(self):
        data, parts, midx = _make_msb([
            ('c4050', (1.0, 1.0, 1.0)),
            ('c4060', (1.0, 1.0, 1.0)),
        ])
        before = bytes(data)
        oops_v3._detect_mount_rider_slots(data, parts, midx)
        assert bytes(data) == before  # detection is read-only
