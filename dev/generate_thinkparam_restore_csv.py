"""generate_thinkparam_restore_csv.py

Generate a Smithbox-importable CSV that restores ER's `rangedAttackId`
values on NpcThinkParam rows where the mod's regulation has neutered
them (`mod_value < er_value`). Each output row is the mod's CURRENT
full row (all 110 columns preserved), with ONLY `rangedAttackId`
replaced by ER's value. Importing this overwrites the affected rows
with corrected attack-selection IDs while preserving every other
mod-specific tuning (sight, memory, backhome, etc.).

WHY ROW-PRESERVATION MATTERS
----------------------------
The mod has deliberately tuned many other ThinkParam fields for NR's
gameplay pace (eye_dist, SightTargetForgetTime, backhomeDist, etc.).
Replacing the full row with ER values would undo those balance
choices. Restoring only `rangedAttackId` is surgical: it puts the AI
back in touch with attack options the chr's behavior table already
has, without touching the rest of the AI persona.

Direction filter:
  - 'lowered' (mod < ER): RESTORE. Mod cut off attack options.
  - 'raised'  (mod > ER): SKIP. Mod deliberately gave the AI more.
  - Equal: SKIP. No diff to write.

Mapping ER → NR schema:
  - ER has column `pad4`; NR/mod don't. We don't read it.
  - NR has columns `unknown_1`/`2`/`3`/`4` that ER doesn't.
    Since we start from the mod row (which has them) and only
    overwrite rangedAttackId, these come along untouched.
"""
import csv, json
from pathlib import Path

MOD = '/home/claude/mod_regulation/regulation'
ER = '/home/claude/vanilla_er/vanilla_er'
PROJECT = '/home/claude/nightreign-enemy-rando'
OUT = '/home/claude/working/NpcThinkParam_rangedAttackId_restore.csv'
REPORT = '/home/claude/working/rangedAttackId_restore_report.json'


def load_by_id(path):
    rows = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                rid = int(r['ID'])
            except (KeyError, ValueError):
                continue
            rows[rid] = r
    return rows


def main():
    mod_t = load_by_id(f'{MOD}/NpcThinkParam.csv')
    er_t = load_by_id(f'{ER}/NpcThinkParam.csv')

    with open(f'{PROJECT}/data/nr_enemy_roster.json') as f:
        roster = json.load(f)
    with open(f'{PROJECT}/data/nr_enemy_tags.json') as f:
        tags = json.load(f)

    roster_cps = {v['c_prefix'] for v in roster['all_variants']}

    # Get the mod's column order (the import CSV must match the table schema
    # the mod's tooling expects).
    with open(f'{MOD}/NpcThinkParam.csv') as f:
        mod_header = next(csv.reader(f))

    # Build the restore set
    to_restore = []
    for tid, mod_row in sorted(mod_t.items()):
        if tid not in er_t:
            continue
        cp = f'c{tid // 10000:04d}'
        if cp not in roster_cps:
            continue
        mv = mod_row.get('rangedAttackId', '0')
        ev = er_t[tid].get('rangedAttackId', '0')
        if mv == ev:
            continue
        # Compare numerically, defaulting -1 (no ranged) → "least"
        try:
            mvi, evi = int(mv), int(ev)
        except ValueError:
            continue
        if mvi >= evi:  # raised or equal-after-coercion — skip
            continue
        # lowered: build restored row
        restored = dict(mod_row)
        restored['rangedAttackId'] = ev
        to_restore.append({
            'id': tid,
            'cp': cp,
            'name': tags.get(cp, {}).get('name', '?'),
            'tier': tags.get(cp, {}).get('tier', '?'),
            'mod_value': mv,
            'er_value': ev,
            'restored_row': restored,
        })

    # Write the CSV in mod schema column order
    with open(OUT, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=mod_header)
        writer.writeheader()
        for item in to_restore:
            writer.writerow(item['restored_row'])

    # Also a human-readable report
    report = {
        '_meta': {
            'description': (
                'Restoration of rangedAttackId field on NpcThinkParam rows '
                'where the mod regulation has lowered the value below ER vanilla. '
                'Each CSV row replaces ONLY the rangedAttackId field; all other '
                'mod-specific tuning is preserved. Suspected cause of the '
                'Valiant Gargoyle missing-poison-breath issue and other muted-AI '
                'reports.'
            ),
            'methodology': (
                '1. For each NpcThinkParam ID present in both the mod and ER, '
                'compare rangedAttackId. '
                '2. If mod < ER (numerically; -1 treated as least), include the '
                'row in the restore set with rangedAttackId = ER value. '
                '3. If mod >= ER, leave it alone (deliberate mod aggression).'
            ),
            'csv_target': 'NpcThinkParam',
            'csv_schema': '110 columns, NR/mod schema (includes unknown_1..4, no pad4)',
            'apply_via': 'Smithbox CSV import on NpcThinkParam',
            'rows_in_csv': len(to_restore),
        },
        'changes': [
            {
                'id': item['id'],
                'cp': item['cp'],
                'name': item['name'],
                'tier': item['tier'],
                'rangedAttackId': {
                    'mod_value': item['mod_value'],
                    'er_value': item['er_value'],
                    'restored_to': item['er_value'],
                },
            }
            for item in to_restore
        ],
    }
    with open(REPORT, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Wrote {OUT} with {len(to_restore)} rows")
    print(f"Wrote {REPORT}")
    print()
    print("=== Summary by chr ===")
    by_cp = {}
    for item in to_restore:
        by_cp.setdefault(item['cp'], []).append(item)
    for cp, items in sorted(by_cp.items()):
        name = items[0]['name']
        print(f"  {cp} {name!r} ({items[0]['tier']}): {len(items)} row(s)")
        for item in items:
            print(f"    ID={item['id']}: {item['mod_value']} -> {item['er_value']}")


if __name__ == '__main__':
    main()
