"""test_map_scoped_spoiler.py — regression for the cross-variation
entity_id collision that mislabeled boss healthbars (v0.27.43).

NR builds the overworld from map variations (m60_XX_YY_00/_10/_20, ...)
that REUSE the same entity_id for different enemy placements. The old
global {entity_id: chr} flatten (load_spoiler_entity_map) collapsed them
last-write-wins, so a healthbar callsite in one variation resolved to a
DIFFERENT variation's enemy — e.g. a Gaping Dragon rendered under a
"Centipede Demon" bar. The map-scoped loader resolves each .emevd
against its own map, eliminating the collision.
"""

import json
import os
import sys
import tempfile

# Make healthbar_inplace/ importable regardless of CWD (the .emevd, fmg,
# rewriter modules live one level up from this tests/ dir).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rewriter import (
    load_spoiler_entity_map,
    load_spoiler_entity_map_by_map,
)


def _write_spoiler(entries):
    fd, path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w') as f:
        json.dump({'entries': entries}, f)
    return path


def _reused_eid_spoiler():
    """One entity_id (1042360271) reused across three variations of a
    single overworld tile, each placing a DIFFERENT boss, plus a control
    entry with a unique eid in another map."""
    return [
        {'map': 'm60_42_36_00.msb', 'part_index': 5, 'entity_id': 1042360271,
         'original': {'c_prefix': 'c4500', 'name': 'Flying Dragon'},
         'new': {'c_prefix': 'c7700', 'name': 'Gaping Dragon'}},
        {'map': 'm60_42_36_10.msb', 'part_index': 5, 'entity_id': 1042360271,
         'original': {'c_prefix': 'c4500', 'name': 'Flying Dragon'},
         'new': {'c_prefix': 'c7710', 'name': 'Centipede Demon'}},
        {'map': 'm60_42_36_20.msb', 'part_index': 5, 'entity_id': 1042360271,
         'original': {'c_prefix': 'c4500', 'name': 'Flying Dragon'},
         'new': {'c_prefix': 'c4310', 'name': 'Godrick Soldier'}},
        {'map': 'm46_53_00_00.msb', 'part_index': 1, 'entity_id': 46530800,
         'original': {'c_prefix': 'c3251', 'name': 'Tree Sentinel'},
         'new': {'c_prefix': 'c4670', 'name': 'Ancestor Spirit'}},
    ]


def test_by_map_keeps_variations_separate():
    """The core fix: a reused eid resolves to the correct boss in EACH
    variation's own sub-map (not whichever was written last)."""
    path = _write_spoiler(_reused_eid_spoiler())
    try:
        bymap = load_spoiler_entity_map_by_map(path)
    finally:
        os.unlink(path)
    assert bymap['m60_42_36_00'][1042360271]['c_prefix'] == 'c7700'
    assert bymap['m60_42_36_00'][1042360271]['name'] == 'Gaping Dragon'
    assert bymap['m60_42_36_10'][1042360271]['c_prefix'] == 'c7710'
    assert bymap['m60_42_36_10'][1042360271]['name'] == 'Centipede Demon'
    assert bymap['m60_42_36_20'][1042360271]['c_prefix'] == 'c4310'
    # Control: unique eid in its own map is unaffected.
    assert bymap['m46_53_00_00'][46530800]['c_prefix'] == 'c4670'


def test_flat_map_collapses_reused_eid():
    """Documents the old bug the fix addresses: the flat loader keeps only
    the last entry for a reused eid, which is exactly why bars showed a
    different variation's name."""
    path = _write_spoiler(_reused_eid_spoiler())
    try:
        flat = load_spoiler_entity_map(path)
    finally:
        os.unlink(path)
    # Last-write-wins: only m60_42_36_20's placement survives globally.
    assert flat[1042360271]['c_prefix'] == 'c4310'


def test_original_identity_preserved_for_compose():
    """The map-scoped info dict must still carry old_c_prefix/old_name so
    decide_rewrites can build composed "<original> -> <new>" titles."""
    path = _write_spoiler(_reused_eid_spoiler())
    try:
        bymap = load_spoiler_entity_map_by_map(path)
    finally:
        os.unlink(path)
    info = bymap['m60_42_36_00'][1042360271]
    assert info['old_c_prefix'] == 'c4500'
    assert info['old_name'] == 'Flying Dragon'


def test_mapcode_matches_emevd_basename():
    """The map key must equal the basename the pipeline derives from the
    .emevd filename via os.path.splitext, so the per-file lookup hits."""
    path = _write_spoiler([
        {'map': 'm60_42_36_00.msb', 'part_index': 5, 'entity_id': 1042360271,
         'new': {'c_prefix': 'c7700', 'name': 'Gaping Dragon'}},
    ])
    try:
        bymap = load_spoiler_entity_map_by_map(path)
    finally:
        os.unlink(path)
    assert os.path.splitext('m60_42_36_00.emevd')[0] in bymap


def test_zero_and_missing_cprefix_entries_skipped():
    """eid==0 (name-marker-bound, handled MSB-side) and entries with no
    new c_prefix are dropped, same as the flat loader."""
    path = _write_spoiler([
        {'map': 'm60_42_36_00.msb', 'entity_id': 0,
         'new': {'c_prefix': 'c7700', 'name': 'Gaping Dragon'}},
        {'map': 'm60_42_36_00.msb', 'entity_id': 1042360271,
         'new': {'name': 'no c_prefix'}},
        {'map': 'm60_42_36_00.msb', 'entity_id': 1042360272,
         'new': {'c_prefix': 'c7710', 'name': 'Centipede Demon'}},
    ])
    try:
        bymap = load_spoiler_entity_map_by_map(path)
    finally:
        os.unlink(path)
    mc = bymap.get('m60_42_36_00', {})
    assert 0 not in mc
    assert 1042360271 not in mc
    assert mc[1042360272]['c_prefix'] == 'c7710'
