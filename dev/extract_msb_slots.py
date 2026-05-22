#!/usr/bin/env python3
"""
extract_msb_slots.py — Build dev/all_msb_slots.json from vanilla_msbs/.

This cache lists every Part in every vanilla MSB as (map_name, part_index,
c_prefix). Used by coverage_sim_full.py for accurate coverage measurement
against the actual slot population, not just boss slots.

Re-run when vanilla MSBs change (e.g. game update with new content).
"""
import os, sys, struct, json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from oops_all_anyone import (parse_msb_sections, parse_model_entry,
                              PART_OFF_MODEL_INDEX)

VANILLA_DIR = os.path.join(PROJECT_ROOT, 'vanilla_msbs')
OUT_PATH = os.path.join(PROJECT_ROOT, 'dev', 'all_msb_slots.json')

all_slots = []
n_msbs = 0
for fn in sorted(os.listdir(VANILLA_DIR)):
    if not fn.endswith('.msb'): continue
    with open(os.path.join(VANILLA_DIR, fn), 'rb') as f:
        data = f.read()
    try:
        sections = parse_msb_sections(data)
    except Exception:
        continue
    if len(sections) != 6: continue
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]
    midx_to_cp = {gi: parse_model_entry(data, eo)['name']
                  for gi, eo in enumerate(models['entry_offsets'])}
    for pi, po in enumerate(parts['entry_offsets']):
        midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        if midx < 0: continue
        cp = midx_to_cp.get(midx, '')
        if not cp.startswith('c'): continue
        all_slots.append([fn, pi, cp.split('_')[0]])
    n_msbs += 1

with open(OUT_PATH, 'w') as f:
    json.dump(all_slots, f)
print(f"Scanned {n_msbs} MSBs, wrote {len(all_slots)} slots to {OUT_PATH}")
