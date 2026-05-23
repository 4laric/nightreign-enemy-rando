#!/usr/bin/env python3
"""build_fragile_slot_entities.py — enumerate every fragile Enemy Part
across the MSB corpus and emit the entity-id list a proximity-wake
emevd patch can consume.

Why this exists
---------------
patch_proximity_wake (emevd_patch.py) currently finds bosses to wake by
parsing $InitializeCommonEvent(0, <encounter event>, ...) calls. That is
brittle: the encounter family has several arg layouts, and the arg that
the common_func signature calls `chrEntityId` is sometimes an ENTITY
GROUP id, not a single chr (verified: m32_00's 90015007 passes
32005800, which is not an Enemy Part — it is a group). So the emevd-
parsing approach cannot cleanly answer "is THIS boss's slot fragile."

Fragility, by contrast, is an MSB-native property: is_fragile_slot()
takes (msb_name, part_index, variant_name, position). This script walks
that the other way round — for every Enemy Part in every MSB, it asks
is_fragile_slot(), and for the fragile parts it records the part's OWN
entity id (the `ent` field extract_enemy_parts reads straight from the
Part struct — unambiguous, no group/area confusion).

The output, fragile_slot_entities.json, is the bridge: a per-map list
of entity ids that sit at a fragile slot. A proximity-wake emevd patch
mode can then inject $InitializeCommonEvent(0, 99055500, eid, R) for
every one of them, regardless of which encounter event (if any)
registered the boss — covering the 90015023 multi-chr remainder and
no-monitored-event fragile slots the encounter-parsing patch misses.

What is filtered OUT (and why)
------------------------------
A raw "every fragile Enemy Part with an entity id" scan returns ~663
entities, but most are not the AI-off-freeze class the wake targets:

  * Tier filter — only miniboss and field_boss tiers are kept. grunt /
    trash do not have the boss-init-handshake freeze, non_combat are
    passive NPCs (force-waking them is mildly risky, not a clean
    no-op), mount_component are not standalone enemies.
  * NB-arena exclusion — night_boss / nightlord tiers AND any entity on
    a V3_NIGHT_BOSS_ARENA_MSBS map are dropped. The proximity-wake
    emevd patch deliberately never touches NB arenas (they use the
    90065XXX family and a different wake handshake); an MSB-side scan
    would otherwise scoop them back in, since is_fragile_slot() neither
    knows nor cares about NB-arena status.

The result is the fragile miniboss / field-boss set — the c5840-Black-
Knight class — which is what actually benefits from a wake handler.
The raw counts (pre-filter) are still reported in _meta for visibility.

Honest limitation
-----------------
A wake handler must target an entity id. Most Enemy Parts have ent=0 —
the engine addresses them by group or event-spawn, not a unique id.
Those fragile parts CANNOT be individually woken by this mechanism;
they are counted and reported under `fragile_no_entity_id` so the gap
is visible, not silently dropped.

Usage
-----
    python dev/build_fragile_slot_entities.py <msb_dir> [-o OUT.json]

<msb_dir> holds DECOMPRESSED .msb files (MSB\\0 magic, not .msb.dcx).
Decompress first with the project's DCX tooling if needed.

This is a dev/diagnostic tool. It imports oops_v3 (is_fragile_slot) and
oops_all_anyone (extract_enemy_parts) from the project root.
"""

import argparse
import json
import os
import sys


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(msb_dir, verbose=True):
    """Walk every .msb in msb_dir; classify each Enemy Part with
    is_fragile_slot(), then keep only the fragile miniboss/field_boss
    entities that have an entity id and are not on an NB arena. Return
    the result dict (see module docstring)."""
    sys.path.insert(0, _project_root())
    import oops_v3 as ov3
    import oops_all_anyone as oa

    # Load tags for the tier filter; suppress load_data's stdout chatter.
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        _roster, tags = ov3.load_data()

    # Tiers a wake handler should target: a swapped-in miniboss/field
    # boss can boot AI-off (the c5840 freeze class). night_boss /
    # nightlord are handled by the NB-arena pipeline, not this one.
    WAKE_TIERS = {'miniboss', 'field_boss'}
    # NB-arena maps are off-limits — see module docstring.
    nb_maps = {m[:-4] if m.endswith('.msb') else m
               for m in getattr(ov3, 'V3_NIGHT_BOSS_ARENA_MSBS', set())}

    msbs = sorted(f for f in os.listdir(msb_dir) if f.endswith('.msb'))
    if not msbs:
        raise SystemExit(f"No .msb files in {msb_dir} — are they still "
                         f".msb.dcx (compressed)? Decompress first.")

    per_map = {}            # stem -> sorted list of kept entity ids
    fragile_total = 0       # all fragile Enemy Parts (pre-filter)
    fragile_with_id = 0     # fragile + has entity id
    fragile_no_id = 0       # fragile + ent==0  (cannot wake)
    nonfragile_total = 0
    dropped_tier = 0        # fragile + id, but tier not in WAKE_TIERS
    dropped_nb = 0          # fragile + id + wake-tier, but on NB arena
    kept = 0

    for fname in msbs:
        stem = fname[:-4]   # drop '.msb'
        path = os.path.join(msb_dir, fname)
        try:
            data = open(path, 'rb').read()
        except OSError as e:
            if verbose:
                print(f"  skip {fname}: {e}")
            continue
        parts = oa.extract_enemy_parts(data)
        map_ids = []
        for pi, p in enumerate(parts):
            frag = ov3.is_fragile_slot(fname, pi, p.get('name', ''),
                                       slot_pos=p.get('pos'))
            if not frag:
                nonfragile_total += 1
                continue
            fragile_total += 1
            ent = p.get('ent') or 0
            if ent in (0, 0xFFFFFFFF):
                fragile_no_id += 1
                continue
            fragile_with_id += 1
            # tier filter — resolve the part's c-prefix, look up tier.
            prefix = (p.get('prefix') or '').rstrip('_')
            if not prefix.startswith('c'):
                prefix = 'c' + prefix.lstrip('c')
            tier = (tags.get(prefix) or {}).get('tier')
            if tier not in WAKE_TIERS:
                dropped_tier += 1
                continue
            # NB-arena exclusion.
            if stem in nb_maps:
                dropped_nb += 1
                continue
            kept += 1
            map_ids.append(ent)
        if map_ids:
            per_map[stem] = sorted(set(map_ids))

    result = {
        '_meta': {
            'description': 'Per-map entity ids of fragile-slot miniboss '
                           '/ field_boss Enemy Parts (NB arenas and '
                           'non-boss tiers excluded). Consumed by the '
                           'proximity-wake emevd patch to inject a wake '
                           'handler per fragile boss. Generated by '
                           'dev/build_fragile_slot_entities.py.',
            'msb_dir': os.path.abspath(msb_dir),
            'msb_count': len(msbs),
            'fragile_parts_total': fragile_total,
            'fragile_with_entity_id': fragile_with_id,
            'fragile_no_entity_id': fragile_no_id,
            'nonfragile_parts_total': nonfragile_total,
            'dropped_non_wake_tier': dropped_tier,
            'dropped_nb_arena': dropped_nb,
            'kept_wakeable_boss_entities': kept,
            'maps_with_kept_entities': len(per_map),
            'wake_tiers': sorted(WAKE_TIERS),
        },
        'fragile_slot_entities': per_map,
    }
    return result


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('msb_dir',
                    help='Directory of DECOMPRESSED .msb files.')
    ap.add_argument('-o', '--out',
                    default=None,
                    help='Output JSON path (default: '
                         '<project>/data/fragile_slot_entities.json).')
    ap.add_argument('-q', '--quiet', action='store_true',
                    help='Suppress the summary printout.')
    args = ap.parse_args()

    if not os.path.isdir(args.msb_dir):
        ap.error(f"Not a directory: {args.msb_dir}")

    out = args.out or os.path.join(_project_root(), 'data',
                                   'fragile_slot_entities.json')

    result = build(args.msb_dir, verbose=not args.quiet)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)

    if not args.quiet:
        m = result['_meta']
        print(f"\nScanned {m['msb_count']} MSBs.")
        print(f"  fragile Enemy Parts (all tiers):  "
              f"{m['fragile_parts_total']}")
        print(f"    no entity id (cannot wake):     "
              f"{m['fragile_no_entity_id']}")
        print(f"    with entity id:                 "
              f"{m['fragile_with_entity_id']}")
        print(f"      dropped — non-wake tier:      "
              f"{m['dropped_non_wake_tier']}")
        print(f"      dropped — NB arena:           "
              f"{m['dropped_nb_arena']}")
        print(f"  KEPT (fragile miniboss/field_boss): "
              f"{m['kept_wakeable_boss_entities']}")
        print(f"  maps in output:                   "
              f"{m['maps_with_kept_entities']}")
        print(f"\nWrote {out}")
        if m['fragile_no_entity_id']:
            print(f"\nNote: {m['fragile_no_entity_id']} fragile parts have "
                  f"no entity id. The engine addresses these by group / "
                  f"event-spawn, so a per-entity wake handler cannot "
                  f"target them. They are NOT in the output list.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
