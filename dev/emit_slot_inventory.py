#!/usr/bin/env python3
"""Emit the consolidated per-Part slot inventory for every enemy Part in
a directory of decompressed NR MSBs, into data/nr_slot_inventory.json.

This is the complete *decision input* for the placement engine. Once
emitted, dev/simulate_engine.py can reproduce the engine's shuffle
decisions (swap_plan, reservations, placement counts, gate behaviour)
with NO MSBs and no Oodle — the JSON is the input.

Superset of nr_slot_metadata.json: that file carries
(map, part_index, c_prefix, entity_id, npc_param_id, recipient_is_boss);
this one adds think_param_id, position, and the resolved source
variant_name — the remaining fields the picker / reservation pre-pass /
proximity gate read from the binary.

What it deliberately does NOT capture: the Models-section layout and
byte offsets. Those are needed only to *write* output MSBs, which a
decision simulator does not do.

Usage:
    python3 dev/emit_slot_inventory.py <decompressed_msb_dir>
"""
import sys, os, json, struct
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('o', os.path.join(_ROOT, 'oops_v3.py'))
o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(o)

from oops_all_anyone import (parse_msb_sections, PART_OFF_ENTITY_ID,
                             PART_OFF_NPC_PARAM, PART_OFF_THINK_PARAM,
                             PART_OFF_MODEL_INDEX, PART_OFF_POSITION)


def emit(msb_dir):
    tags = json.load(open(os.path.join(_ROOT, 'data/nr_enemy_tags.json')))
    roster = json.load(open(os.path.join(_ROOT, 'data/nr_enemy_roster.json')))
    pv, pc = o.build_per_prefix_data(roster)

    out = []
    files = sorted(f for f in os.listdir(msb_dir) if f.endswith('.msb'))
    n_unresolved = 0
    for fn in files:
        msb_name = fn                    # 'mXX_XX_00_00.msb'
        msb_base = fn[:-4]
        data = bytearray(open(os.path.join(msb_dir, fn), 'rb').read())
        try:
            sections = parse_msb_sections(data)
        except Exception:
            continue
        if len(sections) != 6:
            continue
        parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
        models = sections[0]
        midx_cp = {gi: o.parse_model_entry(data, eo).get('name', '')
                   for gi, eo in enumerate(models['entry_offsets'])}

        for pi, po in enumerate(parts['entry_offsets']):
            midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
            cp = midx_cp.get(midx, '')
            if not cp.startswith('c') or cp == 'c0000':
                continue                  # not an enemy Part

            def _u32(off):
                return (struct.unpack_from('<I', data, po + off)[0]
                        if po + off + 4 <= len(data) else 0)

            def _i32(off):
                return (struct.unpack_from('<i', data, po + off)[0]
                        if po + off + 4 <= len(data) else -1)

            npc = _u32(PART_OFF_NPC_PARAM)
            think = _u32(PART_OFF_THINK_PARAM)
            eid = _i32(PART_OFF_ENTITY_ID)

            pos = None
            if po + PART_OFF_POSITION + 12 <= len(data):
                try:
                    x, y, z = struct.unpack_from('<fff', data,
                                                 po + PART_OFF_POSITION)
                    if not (x != x or y != y or z != z):  # NaN guard
                        pos = [x, y, z]
                except struct.error:
                    pass

            # Resolve source variant + recipient_is_boss exactly the way
            # the engine's swap loop does (npc -> roster variant join).
            rv = next((v for v in pv.get(cp, [])
                       if v['npc_param_id'] == npc), None)
            if rv is None:
                is_boss = o.is_boss_tier_prefix(cp, tags, pv)
                variant_name = ''
                n_unresolved += 1
            else:
                is_boss = o.is_boss_tier_variant(rv)
                variant_name = rv.get('variant_name', '')
            if (msb_base, pi) in o.V3_BOSS_SLOT_CATALOG:
                is_boss = True
            # v0.27.1 NB-anchor promotion
            if ((msb_base.startswith('m48_') or msb_base.startswith('m49_'))
                    and eid > 0 and eid % 10000 == 800):
                is_boss = True

            out.append({
                'map': msb_name,
                'part_index': pi,
                'c_prefix': cp,
                'npc_param_id': npc,
                'think_param_id': think,
                'entity_id': eid,
                'position': pos,
                'source_variant_name': variant_name,
                'recipient_is_boss': bool(is_boss),
            })

    dest = os.path.join(_ROOT, 'data/nr_slot_inventory.json')
    with open(dest, 'w') as f:
        json.dump(out, f, separators=(',', ':'), sort_keys=False)
    print(f"emitted {len(out)} enemy-Part records from {len(files)} MSBs "
          f"({n_unresolved} with unresolved source variant) -> {dest}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    emit(sys.argv[1])
