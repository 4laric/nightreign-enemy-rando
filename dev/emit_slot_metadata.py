#!/usr/bin/env python3
"""Emit per-Part slot metadata for every enemy Part in a directory of
decompressed NR MSBs, into data/nr_slot_metadata.json.

This is the static fixture the carve-out / placement-logic tests replay
against (see dev/replay_carveout.py). Emitting it requires the real
decompressed MSBs (KRAK/Oodle) once; thereafter the committed JSON lets
the logic tests run with no MSBs and no Oodle.

What it captures per Part: map, part_index, c_prefix, entity_id,
npc_param_id, and recipient_is_boss computed with the engine's own
classifier (is_boss_tier_variant / is_boss_tier_prefix + the NB-anchor
promotion). What it does NOT capture: byte-level parse correctness — the
dump IS the parser's output, so it can't audit the parser. Logic tests
only.

Usage:
    python3 dev/emit_slot_metadata.py <decompressed_msb_dir>
"""
import sys, os, json, struct
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('o', os.path.join(_ROOT, 'oops_v3.py'))
o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(o)

from oops_all_anyone import parse_msb_sections, PART_OFF_ENTITY_ID, PART_OFF_NPC_PARAM


def emit(msb_dir):
    tags = json.load(open(os.path.join(_ROOT, 'data/nr_enemy_tags.json')))
    roster = json.load(open(os.path.join(_ROOT, 'data/nr_enemy_roster.json')))
    pv, pc = o.build_per_prefix_data(roster)

    out = []
    files = sorted(f for f in os.listdir(msb_dir) if f.endswith('.msb'))
    for fn in files:
        msb_name = fn                    # 'mXX_XX_00_00.msb' — matches
                                         # V3_*_ARENA_MSBS / slot_msb_name
        msb_base = fn[:-4]               # strip .msb
        data = bytearray(open(os.path.join(msb_dir, fn), 'rb').read())
        try:
            sections = parse_msb_sections(data)
        except Exception:
            continue
        if len(sections) != 6:
            continue
        parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
        # model index -> c-prefix
        models = sections[0]
        midx_cp = {}
        for gi, eo in enumerate(models['entry_offsets']):
            midx_cp[gi] = o.parse_model_entry(data, eo).get('name', '')

        for pi, po in enumerate(parts['entry_offsets']):
            midx = struct.unpack_from('<i', data, po + 0x014)[0]
            cp = midx_cp.get(midx, '')
            if not cp.startswith('c') or cp == 'c0000':
                continue                  # not an enemy Part
            eid = struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0] \
                if po + PART_OFF_ENTITY_ID + 4 <= len(data) else -1
            npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0] \
                if po + PART_OFF_NPC_PARAM + 4 <= len(data) else 0

            # recipient_is_boss — mirror the engine (oops_v3.py swap loop)
            rv = next((v for v in pv.get(cp, []) if v['npc_param_id'] == npc), None)
            if rv is None:
                is_boss = o.is_boss_tier_prefix(cp, tags, pv)
            else:
                is_boss = o.is_boss_tier_variant(rv)
            if (msb_base, pi) in o.V3_BOSS_SLOT_CATALOG:
                is_boss = True
            # v0.27.1 NB-anchor promotion
            if (msb_base.startswith('m48_') or msb_base.startswith('m49_')) \
                    and eid > 0 and eid % 10000 == 800:
                is_boss = True

            out.append({
                'map': msb_name,
                'part_index': pi,
                'c_prefix': cp,
                'entity_id': eid,
                'npc_param_id': npc,
                'recipient_is_boss': bool(is_boss),
            })

    dest = os.path.join(_ROOT, 'data/nr_slot_metadata.json')
    with open(dest, 'w') as f:
        json.dump(out, f, separators=(',', ':'), sort_keys=False)
    print(f"emitted {len(out)} enemy-Part records from {len(files)} MSBs -> {dest}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    emit(sys.argv[1])
