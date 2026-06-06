#!/usr/bin/env python3
"""stamp_name_marker_boss_wakes.py — stamp reserved entity ids onto the
name-marker boss slots so the proximity-wake emevd patch can reach them.

The problem
-----------
72 Enemy Part slots across the corpus carry recipient_is_boss=True but have
entity_id==0 (a "name-marker" slot: vanilla addresses the boss by name, not by
entity id). patch_proximity_wake wakes a boss by injecting
$InitializeCommonEvent(0, 99055500, <entityId>, <radius>) — it can only target
a slot that HAS an entity id. So a boss the randomizer places into a
name-marker slot never gets an EnableCharacterAI and freezes until a player
backstabs it. (It is also why picker.py drops freeze-prone imports from these
slots — they're unreachable by the wake.)

The fix
-------
A static pre-pass that writes a reserved, per-map, collision-free entity id
onto each name-marker boss slot's Enemy Part, BEFORE the randomizer runs. The
shuffler preserves entity ids across a swap, so whatever boss lands there
inherits the stamped id, and the proximity-wake catalog
(data/stamped_boss_wake_entities.json, also emitted here) lists those ids for
the emevd patch to wake. Static is intentional — the ids never need to change
seed to seed.

Allocation
----------
Per map, base = (min existing entity id on that map) // 10000 * 10000 — i.e.
the map's entity-id prefix block (m32_00 -> 32000000, m46_01 -> 46010000, the
m60 overworld tiles -> 10xxxxx000). Each name-marker boss slot, ordered by its
inventory part_index, gets base + RESERVED_OFFSET + i. RESERVED_OFFSET defaults
to 9000, sitting well above every vanilla local id (the corpus tops out around
+1250) and below the next prefix block (+10000). Audited collision-free across
all maps with existing ids. A map with NO existing entity id (m60_10_09_12, the
sole case) has no inferable base and is SKIPPED with a warning unless a
--base-override is supplied.

Night-boss arena maps (m48_*, m49_*) are excluded by default: patch_proximity_
wake early-returns on them (their bosses run off the NB machinery, not the
proximity wake), so a stamp there would never fire. Of the 72 name-marker boss
slots, 29 sit on those maps; the remaining 42 across 13 field/overworld maps are
the ones stamped. Pass --include-nb-maps to stamp them anyway.

Matching
--------
(prefix, npc_param_id) is NOT unique among these slots — e.g. m46_01 has five
identical c4550/45500030 placements — so each target is matched to its Enemy
Part by prefix + npc + entity_id==0 + position (within --tol metres). No target
shares (prefix, npc) with a slot that already has an entity id, so the
entity_id==0 guard never risks hitting a live boss; the write is additionally
refused on any part whose current entity id is non-zero.

Usage
-----
    # Catalog-only (no MSBs touched) — preview the allocation + emit the catalog:
    python dev/stamp_name_marker_boss_wakes.py

    # Stamp a decompressed MSB corpus, write stamped copies + the catalog:
    python dev/stamp_name_marker_boss_wakes.py \
        --msb-dir /path/to/decompressed/msb \
        --out-dir /path/to/stamped/msb

Run against DECOMPRESSED .msb files (unpack the .msb.dcx first). Stamped MSBs go
to --out-dir; the catalog + a human-readable spoiler go next to it / into data/.
"""

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import oops_all_anyone as oaa   # noqa: E402  (extract_enemy_parts + offsets)

RESERVED_OFFSET = 9000          # reserved sub-range start within a map's block
PREFIX_BLOCK = 10000            # entity-id prefix block size (one map)
DEFAULT_TOL = 0.01              # metres; position-match tolerance


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stem(map_name):
    return map_name[:-4] if map_name.endswith('.msb') else map_name


def _load_inventory(path):
    with open(path, encoding='utf-8') as f:
        inv = json.load(f)
    return inv if isinstance(inv, list) else next(
        v for k, v in inv.items() if k != '_meta')


def compute_allocation(rows, reserved_offset=RESERVED_OFFSET,
                       base_overrides=None, exclude_maps=None):
    """Pure: from the inventory rows, return
        (alloc, skipped)
    where alloc = {map_name: [ {part_index, c_prefix, npc_param_id,
                                position, eid}, ... ]}  (deterministic order)
    and skipped = {map_name: reason} for maps with no inferable base.

    Both this generator and the MSB stamp run off the same inventory + sort, so
    the eid assigned to each slot is identical whether or not the MSBs are
    present — the emitted catalog and the stamped ids always agree.
    """
    base_overrides = base_overrides or {}
    # all existing entity ids per map -> base; and the per-map name-marker bosses
    existing = {}
    targets = {}
    for s in rows:
        m = s['map']
        eid = s.get('entity_id') or 0
        if eid:
            existing.setdefault(m, []).append(eid)
        if not eid and s.get('recipient_is_boss'):
            targets.setdefault(m, []).append(s)

    alloc, skipped = {}, {}
    exclude = {_stem(x) for x in (exclude_maps or ())}
    for m in sorted(targets):
        if _stem(m) in exclude:
            skipped[m] = 'night-boss arena map (proximity wake early-returns)'
            continue
        if m in base_overrides:
            base = int(base_overrides[m])
        elif existing.get(m):
            base = min(existing[m]) // PREFIX_BLOCK * PREFIX_BLOCK
        else:
            skipped[m] = 'no existing entity id on this map -> base not inferable'
            continue
        used = set(existing.get(m, []))
        slots = sorted(targets[m], key=lambda s: s.get('part_index', 0))
        out = []
        for i, s in enumerate(slots):
            eid = base + reserved_offset + i
            if eid in used:
                raise ValueError(
                    f"{m}: reserved id {eid} collides with an existing id "
                    f"(raise --reserved-offset)")
            out.append({
                'part_index': s.get('part_index'),
                'c_prefix': s['c_prefix'],
                'npc_param_id': s.get('npc_param_id'),
                'position': list(s.get('position') or []),
                'source_variant_name': s.get('source_variant_name'),
                'eid': eid,
            })
        alloc[m] = out
    return alloc, skipped


def _read_entity_id(data, struct_start):
    return struct.unpack_from(
        '<I', data, struct_start + oaa.ENEMY_PART_ENTITY_ID_OFFSET)[0]


def _write_entity_id(data, struct_start, eid):
    """Write a u32 entity id at the Enemy Part's entity-id field — the exact
    offset extract_enemy_parts reads it back from, so reads round-trip."""
    struct.pack_into(
        '<I', data, struct_start + oaa.ENEMY_PART_ENTITY_ID_OFFSET, eid)


def _match(parts, tgt, tol):
    """Find the unique ent==0 part matching tgt by prefix + npc + position.
    Returns the part dict, or None (not found / ambiguous)."""
    pos = tgt['position']
    cands = [p for p in parts
             if p['prefix'] == tgt['c_prefix']
             and p['npc'] == tgt['npc_param_id']]
    if pos and len(cands) > 1:
        cands = [p for p in cands
                 if all(abs(a - b) <= tol for a, b in zip(p['pos'], pos))]
    return cands[0] if len(cands) == 1 else None


def stamp_msb(data, slot_allocs, tol=DEFAULT_TOL):
    """Stamp one MSB's bytes. slot_allocs is the alloc list for this map.
    Returns (new_bytes, results) where results is a list of
    {eid, part_index, status, ...}. Never overwrites a non-zero entity id."""
    buf = bytearray(data)
    parts = oaa.extract_enemy_parts(bytes(buf))
    results = []
    for a in slot_allocs:
        p = _match(parts, a, tol)
        if p is None:
            results.append({**a, 'status': 'not_found_or_ambiguous'})
            continue
        if _read_entity_id(buf, p['off']) != 0:
            results.append({**a, 'status': 'occupied_skipped',
                            'off': p['off']})
            continue
        _write_entity_id(buf, p['off'], a['eid'])
        results.append({**a, 'status': 'stamped', 'off': p['off'],
                        'name': p['name']})
    return bytes(buf), results


def _find_msb(msb_dir, map_name):
    """Locate the on-disk file for an inventory map name (with or without the
    .msb suffix; tolerate a .dcx that the caller forgot to unpack only by
    name — we do not decompress here)."""
    stem = _stem(map_name)
    for cand in (map_name, stem + '.msb', stem):
        p = os.path.join(msb_dir, cand)
        if os.path.isfile(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--inventory', default=None,
                    help='nr_slot_inventory.json (default: data/...).')
    ap.add_argument('--msb-dir', default=None,
                    help='Directory of DECOMPRESSED .msb files. If omitted, '
                         'runs catalog-only (no MSBs read or written).')
    ap.add_argument('--out-dir', default=None,
                    help='Where stamped .msb copies are written '
                         '(default: ./stamped_msb). Only used with --msb-dir.')
    ap.add_argument('--catalog', default=None,
                    help='Catalog output path (default: '
                         'data/stamped_boss_wake_entities.json).')
    ap.add_argument('--spoiler', default=None,
                    help='Human-readable spoiler JSON (default: next to the '
                         'catalog, .spoiler.json).')
    ap.add_argument('--reserved-offset', type=int, default=RESERVED_OFFSET)
    ap.add_argument('--tol', type=float, default=DEFAULT_TOL)
    ap.add_argument('--base-override', action='append', default=[],
                    metavar='MAP=BASE',
                    help='Force a map\'s entity-id base, e.g. '
                         'm60_10_09_12.msb=1009120000. Repeatable.')
    ap.add_argument('--include-nb-maps', action='store_true',
                    help='Also stamp night-boss arena maps. By default they '
                         'are skipped: patch_proximity_wake early-returns on '
                         'them (their bosses are driven by the NB machinery), '
                         'so stamps there would never fire.')
    ap.add_argument('-q', '--quiet', action='store_true')
    args = ap.parse_args()

    root = _project_root()
    inv = args.inventory or os.path.join(root, 'data', 'nr_slot_inventory.json')
    catalog_path = args.catalog or os.path.join(
        root, 'data', 'stamped_boss_wake_entities.json')
    spoiler_path = args.spoiler or (
        os.path.splitext(catalog_path)[0] + '.spoiler.json')
    overrides = dict(o.split('=', 1) for o in args.base_override)

    # Night-boss arena maps are early-returned by patch_proximity_wake, so a
    # stamp there is dead weight. Pull the NB stem list from emevd_patch and
    # exclude them unless --include-nb-maps overrides.
    nb_exclude = set()
    if not args.include_nb_maps:
        try:
            import emevd_patch as _ep
            nb_exclude = {s for s, _, _ in _ep._NB_BOSS_ENTITY_IDS}
        except Exception:
            nb_exclude = set()

    rows = _load_inventory(inv)
    alloc, skipped = compute_allocation(
        rows, args.reserved_offset, overrides, exclude_maps=nb_exclude)

    # The catalog the emevd patch consumes: {map_stem: [eid, ...]}.
    catalog = {_stem(m): [a['eid'] for a in items]
               for m, items in sorted(alloc.items())}
    n_slots = sum(len(v) for v in catalog.values())

    stamp_results = None
    if args.msb_dir:
        out_dir = args.out_dir or os.path.join(os.getcwd(), 'stamped_msb')
        os.makedirs(out_dir, exist_ok=True)
        stamp_results = {}
        catalog = {}                       # rebuild from what actually stamped
        for m, items in sorted(alloc.items()):
            src = _find_msb(args.msb_dir, m)
            if not src:
                stamp_results[m] = [{**a, 'status': 'msb_missing'}
                                    for a in items]
                continue
            with open(src, 'rb') as f:
                data = f.read()
            new_data, results = stamp_msb(data, items, args.tol)
            stamp_results[m] = results
            stamped = [r['eid'] for r in results if r['status'] == 'stamped']
            if stamped:
                catalog[_stem(m)] = stamped
            with open(os.path.join(out_dir, _stem(m) + '.msb'), 'wb') as f:
                f.write(new_data)
        n_slots = sum(len(v) for v in catalog.values())

    os.makedirs(os.path.dirname(os.path.abspath(catalog_path)), exist_ok=True)
    with open(catalog_path, 'w', encoding='utf-8') as f:
        json.dump({
            '_meta': {
                'description': 'Per-map reserved entity ids stamped onto '
                               'name-marker boss slots (recipient_is_boss + '
                               'entity_id==0) so patch_proximity_wake can wake '
                               'them. Generated by '
                               'dev/stamp_name_marker_boss_wakes.py. The same '
                               'static ids must be stamped into the shipped '
                               'MSBs (--msb-dir run) for these wakes to '
                               'resolve in game.',
                'reserved_offset': args.reserved_offset,
                'maps': len(catalog),
                'slots': n_slots,
                'skipped_maps': skipped,
                'stamped_from_msbs': bool(args.msb_dir),
            },
            'stamped_boss_wake_entities': catalog,
        }, f, indent=2)

    with open(spoiler_path, 'w', encoding='utf-8') as f:
        json.dump(stamp_results if stamp_results is not None else alloc,
                  f, indent=2)

    if not args.quiet:
        mode = 'STAMP' if args.msb_dir else 'catalog-only'
        print(f"[{mode}] slots: {n_slots}  maps: {len(catalog)}")
        if skipped:
            for m, why in skipped.items():
                print(f"  SKIPPED {m}: {why}")
        if stamp_results is not None:
            from collections import Counter
            st = Counter(r['status'] for rs in stamp_results.values()
                         for r in rs)
            print("  stamp status:", dict(st))
        print(f"  catalog -> {catalog_path}")
        print(f"  spoiler -> {spoiler_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
