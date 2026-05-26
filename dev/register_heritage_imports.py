#!/usr/bin/env python3
"""
register_heritage_imports.py -- register a heritage-import chr into the
rando's data files so the engine can place it.

Usage:
    python3 dev/register_heritage_imports.py --chr c5750 --tier miniboss
    python3 dev/register_heritage_imports.py --chr c5750 --tier grunt \
        --anim-class humanoid --size-class M --dry-run

Registers ONE c-prefix into nr_enemy_tags.json, nr_enemy_roster.json,
heritage_pack.json and batch_import_plan_comprehensive.json, and sets that
chr's batch-plan status to ASSETS_PENDING (params verified complete; the
chr/script asset copy is the only remaining step).

Idempotent: re-running with the same arguments reproduces identical files.

If the chr already has an entry in nr_enemy_tags.json (e.g. from an earlier
heritage-port pass), that tag is authoritative -- it is preserved untouched
and only the roster / heritage_pack / batch-plan entries are filled in. The
--tier / --anim-class / --size-class / --locomotion flags are then ignored.

WHERE EACH TAG FIELD COMES FROM
  derived from data/NpcParam.csv : hp_max, hp_median, hit_height_median,
      hit_radius_median, weight_median, team, move_type, anim_bank,
      variants, n_*_variants, and the per-row roster entries.
  from the batch_import_plan entry : name, locomotion. Overridable with
      --name / --locomotion; if the chr is not yet in the plan these flags
      are required and a new plan entry is created.
  judgement / not derivable here : tier  (--tier; default heuristic:
      heritage + hp_median >= 300 -> miniboss, else grunt -- printed loudly)
                                    anim_class  (--anim-class; default: the
      batch-plan value, unless that is the placeholder "misc")
                                    size_class  (--size-class; default: a
      hitHeight proxy, S/M/L/XL/XXL -- a rough default, verify on a rig)

NOT HANDLED (run the dedicated tools afterward):
  * reward fields default to none (has_reward / has_drops / has_boss_reward
    = false, n_reward_variants = 0). Run dev/emit_has_reward.py to populate
    reward status for reward-bearing chrs.
  * roster variants use think_param_id == npc_param_id (identity mapping):
    a heritage chr is never placed in vanilla NR so no MSB-derived think
    pairs exist; the game reads the real pointer from regulation.bin anyway.
  * variants are not dedup-collapsed; variant_prune_list.json clusters on
    the pick path -- rerun dev/audit_genuine_variants.py.
  * heritage_pack.json is normally rebuilt by dev/build_heritagae_pack.py
    from a chr-folder scan; this script hand-adds a single entry.
"""
import argparse
import csv
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
NEW_STATUS = 'ASSETS_PENDING'
# Marks heritage_pack entries this tool produced. Bump if the registration
# semantics change; kept stable so prior registrations reproduce.
REG_SOURCE = 'manual_register_v0.27.12'


def npcparam_rows(cp_int):
    """Rows of data/NpcParam.csv whose ID is in the cp's 10000-wide band."""
    lo, hi = cp_int * 10000, (cp_int + 1) * 10000
    path = os.path.join(DATA, 'NpcParam.csv')
    with open(path, encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        hdr = next(reader)
        col = {n: hdr.index(n) for n in
               ('ID', 'Name', 'hitHeight', 'hitRadius', 'weight', 'hp',
                'teamType', 'moveType')}
        out = []
        for row in reader:
            if not row or not row[col['ID']].strip().isdigit():
                continue
            rid = int(row[col['ID']])
            if not (lo <= rid < hi):
                continue
            out.append({
                'id': rid,
                'name': row[col['Name']].strip(),
                'hit_height': float(row[col['hitHeight']] or 0),
                'hit_radius': float(row[col['hitRadius']] or 0),
                'weight': float(row[col['weight']] or 0),
                'hp': int(float(row[col['hp']] or 0)),
                'team': int(float(row[col['teamType']] or 0)),
                'move_type': int(float(row[col['moveType']] or 0)),
            })
    return out


def is_usable(name):
    """Placeable in a random pool iff not an '(Unused)' row and not a
    named-boss row (boss variants are deployed by other means)."""
    return '(Unused)' not in name and 'Boss' not in name


def size_class_from_hit_height(h):
    """hitHeight proxy for size_class. Fits the known heritage tags
    (Juvenile Scholar 1.0=S, Black Knight 2.0=M, Giant Beast Skeleton
    2.5=L, Giant Black Crab 3.8=XL). A default only -- verify on a rig."""
    if h < 1.6:
        return 'S'
    if h < 2.4:
        return 'M'
    if h < 3.2:
        return 'L'
    if h < 4.8:
        return 'XL'
    return 'XXL'


def load_json(path):
    """Load JSON, capturing serialization conventions for a minimal diff.
    nr_enemy_tags.json stores literal UTF-8; the others escape non-ASCII;
    trailing newlines vary."""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    return json.loads(text), {
        'non_ascii': any(ord(c) > 127 for c in text),
        'trailing_nl': text.endswith('\n'),
    }


def write_json(path, obj, fmt):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=not fmt['non_ascii'])
        if fmt['trailing_nl']:
            f.write('\n')


def main():
    ap = argparse.ArgumentParser(
        description='Register one heritage-import chr into the rando data '
                    'files.')
    ap.add_argument('--chr', required=True, metavar='cXXXX',
                    help='c-prefix to register, e.g. c5750')
    ap.add_argument('--tier',
                    help='grunt / miniboss / ... (default: hp-based heuristic)')
    ap.add_argument('--name',
                    help='display name (default: batch-plan entry)')
    ap.add_argument('--anim-class', dest='anim_class',
                    help='anim_class (default: batch-plan entry if not "misc")')
    ap.add_argument('--size-class', dest='size_class',
                    help='S/M/L/XL/XXL (default: hitHeight proxy)')
    ap.add_argument('--locomotion', type=int,
                    help='locomotion code (default: batch-plan entry)')
    ap.add_argument('--dry-run', action='store_true',
                    help='print the plan without writing any files')
    args = ap.parse_args()

    cp = args.chr.strip()
    if not (cp.startswith('c') and cp[1:].isdigit()):
        ap.error(f'--chr must look like cXXXX, got {cp!r}')
    cp_int = int(cp[1:])

    rows = npcparam_rows(cp_int)
    if not rows:
        sys.exit(f'{cp}: no NpcParam rows in band {cp_int * 10000}-'
                 f'{(cp_int + 1) * 10000} -- nothing to register')
    usable = [r for r in rows if is_usable(r['name'])]
    if not usable:
        sys.exit(f'{cp}: all {len(rows)} NpcParam rows are Unused/Boss')

    paths = {n: os.path.join(DATA, f) for n, f in (
        ('tags', 'nr_enemy_tags.json'),
        ('roster', 'nr_enemy_roster.json'),
        ('pack', 'heritage_pack.json'),
        ('plan', 'batch_import_plan_comprehensive.json'))}
    tags, fmt_tags = load_json(paths['tags'])
    roster, fmt_roster = load_json(paths['roster'])
    pack, fmt_pack = load_json(paths['pack'])
    plan, fmt_plan = load_json(paths['plan'])

    plan_entry = next((e for e in plan if e.get('c_prefix') == cp), None)

    # resolve display name --------------------------------------------------
    existing = tags.get(cp)
    name = (existing or {}).get('name') or args.name \
        or (plan_entry or {}).get('name')
    if not name:
        sys.exit(f'{cp}: not in nr_enemy_tags or the batch plan and no '
                 f'--name -- cannot resolve a display name')

    hps = [r['hp'] for r in usable]

    # tag --------------------------------------------------------------------
    # An authored tag already in nr_enemy_tags.json is the source of truth: an
    # earlier heritage-port pass may have curated reward splits, team, or a
    # _confidence field that this script cannot reconstruct. Preserve it
    # untouched; derive a tag from NpcParam only when none exists.
    if existing is not None:
        for flag in ('tier', 'anim_class', 'size_class', 'locomotion'):
            if getattr(args, flag) is not None:
                print(f'  note: --{flag.replace("_", "-")} ignored -- {cp} '
                      f'already has a tag; the existing tag is authoritative')
        tag = existing
        tag_src = f"preserved (existing _source={existing.get('_source', '?')})"
        locomotion = existing.get('locomotion', 0)
        anim_class = existing.get('anim_class', 'misc')
        hp_max = existing.get('hp_max', max(hps))
    else:
        if args.locomotion is not None:
            locomotion = args.locomotion
        elif plan_entry and plan_entry.get('locomotion') is not None:
            locomotion = plan_entry['locomotion']
        else:
            sys.exit(f'{cp}: not in batch plan and no --locomotion')

        if args.anim_class:
            anim_class = args.anim_class
        else:
            plan_ac = (plan_entry or {}).get('anim_class')
            if plan_ac and plan_ac != 'misc':
                anim_class = plan_ac
            else:
                sys.exit(f'{cp}: anim_class unresolved (batch plan has '
                         f'{plan_ac!r}) -- pass --anim-class')

        hit_h = statistics.median(r['hit_height'] for r in usable)
        size_class = args.size_class or size_class_from_hit_height(hit_h)
        if args.tier:
            tier, tier_src = args.tier, 'flag'
        else:
            tier = 'miniboss' if statistics.median(hps) >= 300 else 'grunt'
            tier_src = f'heuristic (hp_median={statistics.median(hps):g})'

        tag = {
            '_heritage_imported': True,
            '_source': 'heritage',
            'anim_bank': cp_int * 10,
            'anim_bank_count': 1,
            'anim_class': anim_class,
            'expects_boss_arena': False,
            'has_boss_reward': False,
            'has_drops': False,
            'has_reward': False,
            'hit_height_median': hit_h,
            'hit_radius_median': statistics.median(
                r['hit_radius'] for r in usable),
            'hp_max': max(hps),
            'hp_median': statistics.median(hps),
            'locomotion': locomotion,
            'move_type': statistics.mode(r['move_type'] for r in usable),
            'n_noreward_variants': len(usable),
            'n_reward_variants': 0,
            'name': name,
            'size_class': size_class,
            'team': statistics.mode(r['team'] for r in usable),
            'tier': tier,
            'variants': len(usable),
            'weight_median': statistics.median(r['weight'] for r in usable),
        }
        tags[cp] = tag
        tag_src = f'derived (tier {tier} [{tier_src}])'
        hp_max = tag['hp_max']

    # roster variants -- one per usable NpcParam row ------------------------
    variants = [{
        'c_prefix': cp,
        'npc_param_id': r['id'],
        'think_param_id': r['id'],   # identity mapping -- see module docstring
        'variant_name': name,
        'hp': r['hp'],
        '_heritage_imported': True,
        'has_reward': False,
    } for r in usable]

    av = roster['all_variants']
    before = len(av)
    av[:] = [v for v in av if v.get('c_prefix') != cp]
    av.extend(variants)

    pack['tags'][cp] = {
        'name': name,
        '_inferred_source':
            f"{REG_SOURCE} (orig _source={tag.get('_source', 'heritage')})",
    }

    if plan_entry is None:
        plan.append({
            'c_prefix': cp, 'name': name, 'locomotion': locomotion,
            'status': NEW_STATUS, 'hp_max': hp_max,
            'anim_class': anim_class,
        })
        plan_action = 'appended new entry'
    else:
        plan_entry['status'] = NEW_STATUS
        plan_action = 'status updated'

    if not args.dry_run:
        write_json(paths['tags'], tags, fmt_tags)
        write_json(paths['roster'], roster, fmt_roster)
        write_json(paths['pack'], pack, fmt_pack)
        write_json(paths['plan'], plan, fmt_plan)

    # report ----------------------------------------------------------------
    head = 'DRY RUN -- would register' if args.dry_run else 'registered'
    print(f'{head} {cp} "{name}"')
    print(f'  NpcParam rows    : {len(rows)} ({len(usable)} usable, '
          f'{len(rows) - len(usable)} Unused/Boss excluded)')
    print(f'  nr_enemy_tags    : {tag_src}')
    print(f'  tier / size_class: {tag.get("tier")} / {tag.get("size_class")}'
          f'   (anim_class {tag.get("anim_class")})')
    print(f'  hp_max / median  : {tag.get("hp_max")} / {tag.get("hp_median")}')
    print(f'  nr_enemy_roster  : all_variants {before} -> {len(av)} '
          f'(+{len(variants)})')
    print(f'  heritage_pack    : {cp} upserted ({len(pack["tags"])} tags)')
    print(f'  batch_import_plan: {plan_action}, status={NEW_STATUS}')
    n_rw = tag.get('n_reward_variants', 0)
    if n_rw:
        print(f'  NOTE: tag declares {n_rw} reward variant(s); roster written '
              f'all-noreward -- run dev/emit_has_reward.py to reconcile.')
    else:
        print('  NOTE: reward fields default to none -- run '
              'dev/emit_has_reward.py for reward-bearing chrs.')


if __name__ == '__main__':
    main()
