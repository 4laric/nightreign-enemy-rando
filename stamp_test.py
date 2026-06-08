#!/usr/bin/env python3
"""stamp_test.py — MAXIMAL entity-id stamp pass (v0.31, experimental).

Companion to dev/stamp_name_marker_boss_wakes.py, but deliberately
indiscriminate. Where that script stamps only the ~42 name-marker BOSS
slots, this stamps EVERY Enemy Part whose entity id is 0, on every map,
and emits a wake catalog for all of them. Gated behind V3_STAMP_TEST
(default False): it is a "see what happens" probe for unfreezing the
overworld enemies vanilla never issues an EnableCharacterAI for, NOT a
shipping default. Expect side effects — see CAVEATS at the bottom.

Two coupled outputs, both derived from ONE allocation so they always agree:
  1. The MSB bytes, with a reserved, per-map, collision-free entity id
     written onto each previously-EID-0 Enemy Part.
  2. A {map_stem: [entity_id, ...]} catalog
     (data/stamp_test_wake_entities.json) that
     emevd_patch.patch_proximity_wake unions in, emitting a proximity wake
     ($InitializeCommonEvent(0, 99055500, eid, R)) for each stamped id.

Allocation
----------
Per map: base = (min existing enemy-part eid on the map) // 10000 * 10000
(the map's prefix block — same rule as the boss-wake stamp). New ids are
handed out starting at base + RESERVED_OFFSET (9000), skipping any id
already live on the map AND any id already handed out on this map — a
collision-avoidance walk rather than a flat base+9000+i, because a
maximal pass can hit ~150 parts on dense interiors (m34_10) and a few
maps carry stray high existing ids that a flat offset could clip. Entity
ids only need to be unique WITHIN a map for the per-map emevd wake to
resolve (each map's .emevd.js references only its own entities), so the
walk is sufficient without a global namespace.

A map with no existing enemy-part eid has no inferable base and is
skipped (returns []), the same lone-case handling the boss-wake stamp
uses for m60_10_09_12.

CAVEATS (this is a probe, hence default-off)
  - Stamping + waking EVERYTHING includes parts that are EID-0 on purpose:
    intro/cutscene actors, despawned-by-default ambushers, script-spawn
    placeholders, scenery-adjacent dummies. Waking those can produce enemies
    standing in odd spots, double-spawns, or behavior the map never expected.
  - Performance: up to ~150 extra always-evaluating proximity WaitFors on the
    dense maps. Fine to probe; watch frame time on the m34 interiors.
  - This activates AI; it does not vet that each woken part is a sensible
    combatant. Use the spoiler/catalog to see exactly what got stamped.
"""
import json
import os
import struct

import oops_all_anyone as oaa   # extract_enemy_parts + ENEMY_PART_ENTITY_ID_OFFSET

RESERVED_OFFSET = 9000          # reserved sub-range start within a map's block
PREFIX_BLOCK = 10000            # entity-id prefix block size (one map)

# Default catalog location — the file emevd_patch.patch_proximity_wake reads.
DEFAULT_CATALOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'data', 'stamp_test_wake_entities.json')


def _base_from_parts(parts):
    existing = [p['ent'] for p in parts if p['ent']]
    if not existing:
        return None
    return min(existing) // PREFIX_BLOCK * PREFIX_BLOCK


def stamp_msb_all_eid0(data, reserved_offset=RESERVED_OFFSET):
    """Stamp every EID-0 Enemy Part in one MSB's bytes.

    Returns (new_bytes, [stamped_eid, ...]). Never overwrites a non-zero
    entity id. Returns (data, []) unchanged if no base is inferable (no
    existing enemy-part eid on the map) or there is nothing to stamp.
    """
    parts = oaa.extract_enemy_parts(data)
    base = _base_from_parts(parts)
    if base is None:
        return data, []
    used = {p['ent'] for p in parts if p['ent']}
    buf = bytearray(data)
    nxt = base + reserved_offset
    stamped = []
    for p in parts:
        if p['ent']:                       # already has an id — leave it alone
            continue
        while nxt in used:                 # collision-avoidance walk
            nxt += 1
        eid = nxt
        used.add(eid)
        nxt += 1
        struct.pack_into(
            '<I', buf, p['off'] + oaa.ENEMY_PART_ENTITY_ID_OFFSET, eid)
        stamped.append(eid)
    return bytes(buf), stamped


def stamp_dir(msb_dir, catalog_path=DEFAULT_CATALOG):
    """Stamp every .msb in msb_dir IN PLACE; write the wake catalog.

    Returns (n_maps, n_stamped). Maps with nothing to stamp are simply
    absent from the catalog. Intended to run over the SHUFFLED MSBs
    (after the swap, before recompress) so stamped ids ride along with
    whatever boss/enemy the randomizer placed.
    """
    catalog = {}
    n_stamped = 0
    for fn in sorted(os.listdir(msb_dir)):
        if not fn.endswith('.msb'):
            continue
        path = os.path.join(msb_dir, fn)
        with open(path, 'rb') as f:
            data = f.read()
        new_data, eids = stamp_msb_all_eid0(data)
        if not eids:
            continue
        with open(path, 'wb') as f:
            f.write(new_data)
        catalog[fn[:-4]] = eids
        n_stamped += len(eids)
    _write_catalog(catalog_path, catalog, n_stamped)
    return len(catalog), n_stamped


def write_empty_catalog(catalog_path=DEFAULT_CATALOG):
    """Stamp test OFF: write an empty catalog so a stale on-run catalog can
    never leak wakes into an off-run's EMEVD bake. Cheap and idempotent."""
    _write_catalog(catalog_path, {}, 0)


def _write_catalog(path, catalog, n_stamped):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            '_meta': {
                'description':
                    'MAXIMAL stamp-test wake catalog (v0.31, experimental). '
                    'Every EID-0 Enemy Part was given a reserved per-map '
                    'entity id; patch_proximity_wake emits a wake for each. '
                    'Generated by stamp_test.py when V3_STAMP_TEST is on; '
                    'empty when the feature is off.',
                'reserved_offset': RESERVED_OFFSET,
                'maps': len(catalog),
                'stamped': n_stamped,
                'experimental': True,
            },
            'stamp_test_wake_entities': catalog,
        }, f, indent=2)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('msb_dir', help='Directory of DECOMPRESSED .msb files '
                                     '(stamped in place).')
    ap.add_argument('--catalog', default=DEFAULT_CATALOG)
    args = ap.parse_args()
    n_maps, n = stamp_dir(args.msb_dir, args.catalog)
    print(f"[stamp_test] stamped {n} parts across {n_maps} maps")
    print(f"  catalog -> {args.catalog}")
