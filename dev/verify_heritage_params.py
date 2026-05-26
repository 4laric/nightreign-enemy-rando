#!/usr/bin/env python3
"""
verify_heritage_params.py -- does the mod regulation already carry every
param row a heritage chr needs, or are regulation edits still required?

For each c-prefix it traces the four enemy param tables and reports any row
present in vanilla ER but MISSING from the mod regulation:

  NpcParam       chr rows = IDs in [cp_int*10000, (cp_int+1)*10000)
  NpcThinkParam  chr rows = IDs in the same band
  BehaviorParam  chr rows = those whose variationId column is one of the
                 chr's NpcParam.behaviorVariationId values
  AtkParam_Npc   chr rows = the BehaviorParam refId values that resolve to a
                 real AtkParam_Npc row

A chr with zero missing rows across all four tables needs NO regulation
edits -- only the chr/script asset copy remains. Any missing rows are
reported (counts, or full IDs with --show-missing).

Usage:
  python3 dev/verify_heritage_params.py                  # every batch-plan chr
  python3 dev/verify_heritage_params.py --chr c5840      # one or more chrs
  python3 dev/verify_heritage_params.py --chr c5840 c5750 --show-missing
  python3 dev/verify_heritage_params.py \
      --mod-regulation /path/to/mod/params --vanilla-er /path/to/er/params

--mod-regulation / --vanilla-er point at folders holding the four param CSVs
(NpcParam.csv, NpcThinkParam.csv, BehaviorParam.csv, AtkParam_Npc.csv) --
Smithbox param-table exports of each regulation.bin. The defaults are the
staging paths from the heritage-import session; override them on a rig.

Exit code 0 if every checked chr is complete, 1 otherwise.
"""
import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Container staging paths from the heritage-import session. Override on a rig.
DEFAULT_MOD = '/home/claude/er_import/mod_reg/regulation'
DEFAULT_ER = '/home/claude/er_import/params/vanilla_er'

TABLES = ('NpcParam.csv', 'NpcThinkParam.csv', 'BehaviorParam.csv',
          'AtkParam_Npc.csv')


def _is_int(s):
    return s.strip().lstrip('-').isdigit()


def _rows(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if row and _is_int(row[0]):
                yield row


def load_regulation(folder):
    """Load the four param tables from one regulation-export folder.

    Returns: npc (list of (id, behaviorVariationId)), think (set of ids),
    beh (list of (id, variationId, refId)), atk (set of ids).
    Column positions verified identical across mod and vanilla-ER exports:
    NpcParam.behaviorVariationId=5, BehaviorParam variationId=2 / refId=7.
    """
    for t in TABLES:
        p = os.path.join(folder, t)
        if not os.path.exists(p):
            sys.exit(f'verify_heritage_params: missing param table: {p}')
    npc = [(int(r[0]), int(r[5])) for r in _rows(
        os.path.join(folder, 'NpcParam.csv')) if len(r) > 5 and _is_int(r[5])]
    think = {int(r[0]) for r in _rows(
        os.path.join(folder, 'NpcThinkParam.csv'))}
    beh = [(int(r[0]), int(r[2]), int(r[7])) for r in _rows(
        os.path.join(folder, 'BehaviorParam.csv'))
        if len(r) > 7 and _is_int(r[2]) and _is_int(r[7])]
    atk = {int(r[0]) for r in _rows(
        os.path.join(folder, 'AtkParam_Npc.csv'))}
    return {'npc': npc, 'think': think, 'beh': beh, 'atk': atk}


def er_chr_rows(er, cp_int):
    """The four ER-side ID sets owned by one c-prefix."""
    lo, hi = cp_int * 10000, (cp_int + 1) * 10000
    bvids = {bv for i, bv in er['npc'] if lo <= i < hi}
    refs = {ref for _, vid, ref in er['beh'] if vid in bvids}
    return {
        'NpcParam': {i for i, _ in er['npc'] if lo <= i < hi},
        'NpcThinkParam': {i for i in er['think'] if lo <= i < hi},
        'BehaviorParam': {i for i, vid, _ in er['beh'] if vid in bvids},
        'AtkParam_Npc': refs & er['atk'],
    }


def main():
    ap = argparse.ArgumentParser(
        description='Verify a heritage chr needs no mod-regulation edits.')
    ap.add_argument('--chr', nargs='+', metavar='cXXXX',
                    help='c-prefix(es) to check (default: every batch-plan chr)')
    ap.add_argument('--mod-regulation', default=DEFAULT_MOD,
                    help='folder of the mod regulation param CSVs')
    ap.add_argument('--vanilla-er', default=DEFAULT_ER,
                    help='folder of the vanilla ER param CSVs')
    ap.add_argument('--show-missing', action='store_true',
                    help='list missing row IDs, not just counts')
    args = ap.parse_args()

    if args.chr:
        chrs = []
        for c in args.chr:
            c = c.strip()
            if not (c.startswith('c') and c[1:].isdigit()):
                ap.error(f'bad c-prefix: {c!r}')
            chrs.append(c)
    else:
        with open(os.path.join(ROOT, 'data',
                  'batch_import_plan_comprehensive.json'), encoding='utf-8') as f:
            chrs = sorted({e['c_prefix'] for e in json.load(f)
                           if e.get('c_prefix')})

    print(f'mod regulation : {args.mod_regulation}')
    print(f'vanilla ER     : {args.vanilla_er}')
    mod = load_regulation(args.mod_regulation)
    er = load_regulation(args.vanilla_er)

    # mod-side full ID sets -- "present in mod" is a flat membership test
    mod_ids = {
        'NpcParam': {i for i, _ in mod['npc']},
        'NpcThinkParam': mod['think'],
        'BehaviorParam': {i for i, _, _ in mod['beh']},
        'AtkParam_Npc': mod['atk'],
    }
    print(f'loaded: mod NpcParam={len(mod["npc"])} rows, '
          f'ER NpcParam={len(er["npc"])} rows\n')

    incomplete = skipped = 0
    for cp in sorted(chrs):
        er_sets = er_chr_rows(er, int(cp[1:]))
        if not any(er_sets.values()):
            print(f'  {cp:8s} N/A         not present in vanilla ER')
            skipped += 1
            continue
        missing = {t: er_sets[t] - mod_ids[t] for t in er_sets}
        if not any(missing.values()):
            print(f'  {cp:8s} COMPLETE    '
                  f'Npc {len(er_sets["NpcParam"])}, '
                  f'Think {len(er_sets["NpcThinkParam"])}, '
                  f'Behavior {len(er_sets["BehaviorParam"])}, '
                  f'Atk {len(er_sets["AtkParam_Npc"])} -- all present in mod')
        else:
            incomplete += 1
            parts = ', '.join(f'{t} -{len(m)}'
                               for t, m in missing.items() if m)
            print(f'  {cp:8s} INCOMPLETE  {parts}')
            if args.show_missing:
                for t, m in missing.items():
                    if m:
                        shown = ', '.join(str(x) for x in sorted(m)[:20])
                        tail = ' ...' if len(m) > 20 else ''
                        print(f'              missing {t}: {shown}{tail}')

    checked = len(chrs) - skipped
    print(f'\n{checked - incomplete}/{checked} checked chrs need no '
          f'regulation edits' + (f'  ({skipped} N/A)' if skipped else ''))
    sys.exit(1 if incomplete else 0)


if __name__ == '__main__':
    main()
