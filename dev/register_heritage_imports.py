#!/usr/bin/env python3
"""
register_heritage_imports.py -- register heritage-import chrs into the rando's
data files so the engine can place them.

This pass:
  * Registers c5840 (Black Knight) -- an ER heritage chr absent from all four
    data files -- into nr_enemy_tags.json, nr_enemy_roster.json,
    heritage_pack.json and batch_import_plan_comprehensive.json.
  * Corrects the now-stale PARTIAL_ATK / PARTIAL_BHV statuses on the eight
    other target chrs (c5190/c5192/c5193/c5250/c5522/c5523/c5750/c5751).
    A four-table diff of the current mod regulation against vanilla ER
    (NpcParam, NpcThinkParam, BehaviorParam-by-behaviorVariationId, and the
    AtkParam_Npc rows those behaviors reference) found ZERO missing rows for
    every one of these chrs -- their params are complete. The only remaining
    work for all nine is the chr/script asset copy on the user's rig, so every
    target chr is set to status ASSETS_PENDING.

Idempotent: re-running replaces the c5840 entries and re-applies the statuses
without duplicating anything.

CAVEATS (in-container limitations -- regenerate on a full rig to normalize):
  * nr_enemy_roster.json and heritage_pack.json are normally rebuilt by an
    external pipeline that needs decompiled NR MSBs + ER param dumps
    (dev/build_heritagae_pack.py, dev/extract_npc_think_pairs.py). Those cannot
    run here.
  * c5840 is never placed in vanilla NR, so it has no entry in
    nr_vanilla_npc_think_pairs.json and no NpcParam think-pointer column exists
    in the exported CSVs. c5840's roster variants therefore use
    think_param_id == npc_param_id (identity mapping). The game reads the real
    think pointer from regulation.bin's NpcParam at runtime regardless, so this
    affects only the rando's bookkeeping.
  * c5840 variants are registered one-per-usable-NpcParam-row (no dedup
    collapse). Usable == name contains neither '(Unused)' nor 'Boss'.
"""
import csv
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

TARGET_CHRS = ('c5190', 'c5192', 'c5193', 'c5250', 'c5522', 'c5523',
               'c5750', 'c5751', 'c5840')
NEW_STATUS = 'ASSETS_PENDING'
C5840_LO, C5840_HI = 58400000, 58410000


def load_c5840_npcparam():
    """Pull c5840's rows out of data/NpcParam.csv."""
    path = os.path.join(DATA, 'NpcParam.csv')
    with open(path, encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        hdr = next(reader)
        col = {n: hdr.index(n) for n in
               ('ID', 'Name', 'hitHeight', 'hitRadius', 'weight', 'hp',
                'teamType')}
        out = []
        for row in reader:
            if not row or not row[col['ID']].strip().isdigit():
                continue
            rid = int(row[col['ID']])
            if not (C5840_LO <= rid < C5840_HI):
                continue
            out.append({
                'id': rid,
                'name': row[col['Name']].strip(),
                'hit_height': float(row[col['hitHeight']] or 0),
                'hit_radius': float(row[col['hitRadius']] or 0),
                'weight': float(row[col['weight']] or 0),
                'hp': int(float(row[col['hp']] or 0)),
                'team': int(float(row[col['teamType']] or 0)),
            })
    return out


def is_usable(name):
    """Placeable in the grunt pool iff not the leaked '(Unused)' CASTLE
    variant and not a named-boss variant (Garrew / Edredd)."""
    return '(Unused)' not in name and 'Boss' not in name


def build_c5840(rows):
    """Return (tag_entry, roster_variants) for c5840 from its NpcParam rows."""
    usable = [r for r in rows if is_usable(r['name'])]
    if not usable:
        raise SystemExit('c5840: no usable NpcParam rows found -- aborting')
    hps = [r['hp'] for r in usable]

    # tag entry -- keys alphabetical to match the rest of nr_enemy_tags.json
    tag = {
        '_heritage_imported': True,
        '_source': 'heritage',
        'anim_bank': 58400,
        'anim_bank_count': 1,
        'anim_class': 'humanoid',
        'expects_boss_arena': False,
        'has_boss_reward': False,
        'has_drops': False,
        'has_reward': False,
        'hit_height_median': statistics.median(r['hit_height'] for r in usable),
        'hit_radius_median': statistics.median(r['hit_radius'] for r in usable),
        'hp_max': max(hps),
        'hp_median': statistics.median(hps),
        'locomotion': 0,
        'move_type': 3,
        'n_noreward_variants': len(usable),
        'n_reward_variants': 0,
        'name': 'Black Knight',
        'size_class': 'M',
        'team': statistics.mode(r['team'] for r in usable),
        'tier': 'grunt',
        'variants': len(usable),
        'weight_median': statistics.median(r['weight'] for r in usable),
    }

    # roster variants -- fixed field order to match all_variants entries
    variants = [{
        'c_prefix': 'c5840',
        'npc_param_id': r['id'],
        'think_param_id': r['id'],   # identity mapping -- see module docstring
        'variant_name': 'Black Knight',
        'hp': r['hp'],
        '_heritage_imported': True,
        'has_reward': False,
    } for r in usable]

    return tag, variants


def load_json(path):
    """Load JSON, capturing the file's serialization conventions so a
    rewrite produces a minimal diff. These data files were authored by
    different tools: nr_enemy_tags.json stores literal UTF-8 (em-dash,
    arrow), the others escape non-ASCII; trailing newlines also vary."""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    fmt = {
        'non_ascii': any(ord(c) > 127 for c in text),
        'trailing_nl': text.endswith('\n'),
    }
    return json.loads(text), fmt


def write_json(path, obj, fmt):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=not fmt['non_ascii'])
        if fmt['trailing_nl']:
            f.write('\n')


def main():
    p_tags = os.path.join(DATA, 'nr_enemy_tags.json')
    p_roster = os.path.join(DATA, 'nr_enemy_roster.json')
    p_pack = os.path.join(DATA, 'heritage_pack.json')
    p_plan = os.path.join(DATA, 'batch_import_plan_comprehensive.json')

    tags, fmt_tags = load_json(p_tags)
    roster, fmt_roster = load_json(p_roster)
    pack, fmt_pack = load_json(p_pack)
    plan, fmt_plan = load_json(p_plan)

    rows = load_c5840_npcparam()
    c5840_tag, c5840_variants = build_c5840(rows)

    # 1. nr_enemy_tags -- upsert c5840 (new key appends last)
    tags['c5840'] = c5840_tag

    # 2. nr_enemy_roster -- replace any existing c5840 variants
    av = roster['all_variants']
    before = len(av)
    av[:] = [v for v in av if v.get('c_prefix') != 'c5840']
    av.extend(c5840_variants)

    # 3. heritage_pack -- upsert c5840
    pack['tags']['c5840'] = {
        'name': 'Black Knight',
        '_inferred_source': 'manual_register_v0.27.12 (orig _source=heritage)',
    }

    # 4. batch_import_plan -- refresh status for all nine targets
    have = {e.get('c_prefix') for e in plan}
    for e in plan:
        if e.get('c_prefix') in TARGET_CHRS:
            e['status'] = NEW_STATUS
    if 'c5840' not in have:
        plan.append({
            'c_prefix': 'c5840',
            'name': 'Black Knight',
            'locomotion': 0,
            'status': NEW_STATUS,
            'hp_max': c5840_tag['hp_max'],
            'anim_class': 'humanoid',
        })

    write_json(p_tags, tags, fmt_tags)
    write_json(p_roster, roster, fmt_roster)
    write_json(p_pack, pack, fmt_pack)
    write_json(p_plan, plan, fmt_plan)

    print(f'c5840: {len(rows)} NpcParam rows -> {len(c5840_variants)} usable '
          f'variants (excluded {len(rows) - len(c5840_variants)} Unused/Boss)')
    print(f'  nr_enemy_tags     : c5840 upserted ({len(tags)} entries)')
    print(f'  nr_enemy_roster   : all_variants {before} -> {len(av)}')
    print(f'  heritage_pack     : c5840 upserted ({len(pack["tags"])} tags)')
    print(f'  batch_import_plan : {len(plan)} entries, '
          f'9 targets -> status={NEW_STATUS}')


if __name__ == '__main__':
    main()
