"""Tests for dev/stamp_name_marker_boss_wakes.py — the allocation is pure and
the MSB write is exercised against a synthetic Enemy Part struct built to the
same offsets extract_enemy_parts reads, so the round-trip proves the write
lands where the wake patch (and the shuffler) will later read it."""

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'dev'))
sys.path.insert(0, ROOT)

import oops_all_anyone as oaa                       # noqa: E402
import stamp_name_marker_boss_wakes as sm           # noqa: E402


# --------------------------------------------------------------------------
# synthetic MSB helpers
# --------------------------------------------------------------------------

def _make_buf(parts):
    """parts: list of (prefix, suffix, npc, ent, (x,y,z)). Lay out Enemy Part
    structs back-to-back at the real offsets. Returns (bytes, [struct_start])."""
    stride = oaa.ENEMY_PART_STRUCT_SIZE + 0x80
    buf = bytearray(stride * len(parts) + 0x100)
    offs = []
    for k, (prefix, suffix, npc, ent, pos) in enumerate(parts):
        ss = 0x40 + k * stride
        offs.append(ss)
        name = (f"{prefix}_{suffix}").encode('utf-16-le') + b'\x00\x00'
        npos = ss + oaa.ENEMY_PART_NAME_OFFSET
        buf[npos:npos + len(name)] = name
        struct.pack_into('<I', buf, ss + oaa.ENEMY_PART_NPC_PARAM_OFFSET, npc)
        struct.pack_into('<I', buf, ss + oaa.ENEMY_PART_ENTITY_ID_OFFSET, ent)
        struct.pack_into('<fff', buf, ss + oaa.ENEMY_PART_POS_OFFSET, *pos)
    return bytes(buf), offs


def _ent_by_pos(data):
    return {p['pos']: p['ent'] for p in oaa.extract_enemy_parts(data)}


# --------------------------------------------------------------------------
# the binary write
# --------------------------------------------------------------------------

def test_write_roundtrips_through_extract():
    data, _ = _make_buf([("c3010", "0001", 30100001, 0, (10.0, 20.0, 30.0))])
    alloc = [{'c_prefix': 'c3010', 'npc_param_id': 30100001,
              'position': [10.0, 20.0, 30.0], 'eid': 32009000}]
    new, results = sm.stamp_msb(data, alloc)
    assert results[0]['status'] == 'stamped'
    assert _ent_by_pos(new)[(10.0, 20.0, 30.0)] == 32009000


def test_write_refuses_occupied_slot():
    # ent already set -> never overwrite a live entity id.
    data, _ = _make_buf([("c3010", "0001", 30100001, 12345, (10.0, 20.0, 30.0))])
    alloc = [{'c_prefix': 'c3010', 'npc_param_id': 30100001,
              'position': [10.0, 20.0, 30.0], 'eid': 32009000}]
    new, results = sm.stamp_msb(data, alloc)
    assert results[0]['status'] == 'occupied_skipped'
    assert _ent_by_pos(new)[(10.0, 20.0, 30.0)] == 12345


def test_position_disambiguates_identical_prefix_npc():
    # Two identical (prefix, npc) ent==0 parts; only the position-matched one
    # is stamped (the m46_01 five-c4550 case in miniature).
    data, _ = _make_buf([
        ("c4550", "0030", 45500030, 0, (0.0, 0.0, 0.0)),
        ("c4550", "0030", 45500030, 0, (100.0, 0.0, 0.0)),
    ])
    alloc = [{'c_prefix': 'c4550', 'npc_param_id': 45500030,
              'position': [100.0, 0.0, 0.0], 'eid': 46019003}]
    new, results = sm.stamp_msb(data, alloc)
    assert results[0]['status'] == 'stamped'
    by_pos = _ent_by_pos(new)
    assert by_pos[(100.0, 0.0, 0.0)] == 46019003
    assert by_pos[(0.0, 0.0, 0.0)] == 0


def test_ambiguous_match_is_skipped_not_guessed():
    # Same (prefix, npc) AND no usable position match -> refuse rather than
    # stamp the wrong part.
    data, _ = _make_buf([
        ("c4550", "0030", 45500030, 0, (0.0, 0.0, 0.0)),
        ("c4550", "0030", 45500030, 0, (100.0, 0.0, 0.0)),
    ])
    alloc = [{'c_prefix': 'c4550', 'npc_param_id': 45500030,
              'position': [999.0, 999.0, 999.0], 'eid': 46019003}]
    new, results = sm.stamp_msb(data, alloc)
    assert results[0]['status'] == 'not_found_or_ambiguous'
    assert all(e == 0 for e in _ent_by_pos(new).values())


# --------------------------------------------------------------------------
# allocation
# --------------------------------------------------------------------------

def _row(m, pi, npc, eid=0, boss=True):
    return {'map': m, 'part_index': pi, 'c_prefix': 'c3010',
            'npc_param_id': npc, 'position': [pi, pi, pi],
            'entity_id': eid, 'recipient_is_boss': boss}


def test_allocation_deterministic_ordered_and_collision_free():
    rows = [
        _row('m32_00_00_00.msb', 5, 1),
        _row('m32_00_00_00.msb', 3, 2),
        _row('m32_00_00_00.msb', 9, 3, eid=32000800, boss=False),  # sets base
    ]
    a1, _ = sm.compute_allocation(rows)
    a2, _ = sm.compute_allocation(rows)
    assert a1 == a2
    eids = [s['eid'] for s in a1['m32_00_00_00.msb']]
    assert eids == [32009000, 32009001]          # base 32000000 +9000, by pi (3,5)
    assert 32000800 not in eids


def test_allocation_skips_baseless_map():
    rows = [_row('m60_10_09_12.msb', 1, 1)]      # no existing eid on the map
    a, skipped = sm.compute_allocation(rows)
    assert a == {}
    assert 'm60_10_09_12.msb' in skipped


def test_base_override_enables_skipped_map():
    rows = [_row('m60_10_09_12.msb', 1, 1)]
    a, skipped = sm.compute_allocation(
        rows, base_overrides={'m60_10_09_12.msb': 1009120000})
    assert skipped == {}
    assert a['m60_10_09_12.msb'][0]['eid'] == 1009129000


def test_reserved_offset_is_configurable():
    rows = [_row('m32_00_00_00.msb', 1, 1),
            _row('m32_00_00_00.msb', 2, 2, eid=32000800, boss=False)]
    a, _ = sm.compute_allocation(rows, reserved_offset=8500)
    assert a['m32_00_00_00.msb'][0]['eid'] == 32008500


def test_exclude_maps_skips_listed_maps():
    # NB-arena maps (passed by stem) are skipped with a reason, not stamped.
    rows = [_row('m49_24_00_00.msb', 1, 1, eid=49240800, boss=False),
            _row('m49_24_00_00.msb', 2, 2)]
    a, skipped = sm.compute_allocation(rows, exclude_maps={'m49_24_00_00'})
    assert a == {}
    assert 'm49_24_00_00.msb' in skipped
