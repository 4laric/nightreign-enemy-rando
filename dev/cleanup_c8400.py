"""Surgical cleanup of the c8400 legacy + c5220 manifest gap.

c8400 was MMV's placeholder slot for Promised Consort Radahn (low-
confidence "Unknown MMV import (likely PCR)" entry). Now that the
heritage import for PCR via its real ER c-prefix c5220 has shipped
and is live in nr_enemy_tags + roster, c8400 is dead weight scattered
across 6 data files. This script removes it everywhere, and ALSO
registers c5220 in heritage_pack.json (the manifest gap — c5220 is
in the tag/roster layer but never made it into the heritage-owned
manifest, meaning a heritage_pack disable wouldn't strip it).

Touches:
  - heritage_pack.json: REMOVE c8400 tag, ADD c5220 tag
  - nr_enemy_tags.json: REMOVE c8400 entry
  - nr_enemy_roster.json: REMOVE c8400 variant(s)
  - mmv_imports.json: REMOVE c8400 tag + variant (sync from
    out-of-band edits earlier in the session)
  - has_reward_overrides.json: REMOVE c8400 key
  - placement_budget.json: REMOVE c8400 key

Safety: every mutation is gated on "field is present before removal"
and reports counts. Re-running is idempotent — already-clean files
report 0 removals.
"""
import json
from pathlib import Path


def remove_c8400_from_heritage_pack(path):
    """heritage_pack.json: drop c8400, add c5220 if absent."""
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    tags = d['tags']
    removed = tags.pop('c8400', None) is not None
    added = False
    if 'c5220' not in tags:
        tags['c5220'] = {
            'name': 'Promised Consort Radahn',
            '_inferred_source': ('heritage_register_v0.28.0 (real ER c-prefix; '
                                 'heritage import landed first-try; '
                                 'supersedes the c8400 MMV placeholder)')
        }
        added = True
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return removed, added


def remove_c8400_from_tags(path):
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    removed = d.pop('c8400', None) is not None
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return removed


def remove_c8400_from_roster(path):
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    before = len(d.get('all_variants', []))
    d['all_variants'] = [v for v in d.get('all_variants', [])
                         if v.get('c_prefix') != 'c8400']
    n_removed = before - len(d['all_variants'])
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return n_removed


def remove_c8400_from_mmv(path):
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    tag_removed = d['tags'].pop('c8400', None) is not None
    before = len(d.get('variants', []))
    d['variants'] = [v for v in d.get('variants', [])
                     if v.get('c_prefix') != 'c8400']
    variants_removed = before - len(d['variants'])
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return tag_removed, variants_removed


def remove_c8400_from_has_reward_overrides(path):
    """has_reward_overrides.json has nested structure:
       {"by_c_prefix": {"c8400": true, ...}, "by_npc_param_id": {}}
    """
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    removed = d.get('by_c_prefix', {}).pop('c8400', None) is not None
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return removed


def remove_c8400_from_placement_budget(path):
    """placement_budget.json — c8400 lives under one of the top-level
    keys. Search and drop wherever it appears.
    """
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    n_removed = 0
    # Walk top-level dict and any nested dicts looking for c8400 keys.
    def drop_recursively(obj):
        nonlocal n_removed
        if isinstance(obj, dict):
            if 'c8400' in obj:
                del obj['c8400']
                n_removed += 1
            for v in list(obj.values()):
                drop_recursively(v)
        elif isinstance(obj, list):
            for v in obj:
                drop_recursively(v)
    drop_recursively(d)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return n_removed


def main(project_root: Path, heritage_pack_path: Path):
    data = project_root / 'data'

    print("c8400 → c5220 cleanup")
    print("=" * 60)

    hp_removed, hp_added = remove_c8400_from_heritage_pack(heritage_pack_path)
    print(f"heritage_pack.json: c8400 removed={hp_removed}, c5220 added={hp_added}")

    tags_removed = remove_c8400_from_tags(data / 'nr_enemy_tags.json')
    print(f"nr_enemy_tags.json: c8400 removed={tags_removed}")

    roster_n = remove_c8400_from_roster(data / 'nr_enemy_roster.json')
    print(f"nr_enemy_roster.json: c8400 variants removed={roster_n}")

    mmv_tag, mmv_var = remove_c8400_from_mmv(data / 'mmv_imports.json')
    print(f"mmv_imports.json: tag removed={mmv_tag}, variants removed={mmv_var}")

    hr_removed = remove_c8400_from_has_reward_overrides(
        data / 'has_reward_overrides.json')
    print(f"has_reward_overrides.json: c8400 removed={hr_removed}")

    pb_n = remove_c8400_from_placement_budget(data / 'placement_budget.json')
    print(f"placement_budget.json: c8400 keys removed={pb_n}")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--project-root', default='.')
    p.add_argument('--heritage-pack',
                   help='Path to heritage_pack.json '
                        '(default: <project-root>/data/heritage_pack.json)')
    args = p.parse_args()
    root = Path(args.project_root).resolve()
    hp = Path(args.heritage_pack).resolve() if args.heritage_pack \
        else root / 'data' / 'heritage_pack.json'
    main(root, hp)
