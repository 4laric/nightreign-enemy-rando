#!/usr/bin/env python3
"""Audit vanilla NR NpcParam.csv for team=26 variants not in V3_AVOID_VARIANT_NPC_IDS.

Scans vanilla NR's own NpcParam.csv for non-aggressive scripted variants
that should never be placed at random combat slots — grace-replay
variants, decorations, friendly NPCs, and other non-combat scripted
forms.

Detection heuristic: teamType == 26 in the NpcParam row.

Empirical: team=26 in NR identifies grace-replay variants, decorations,
friendly NPCs, and other non-combat scripted forms. User playtest seed
713344 hit 25008100 (c2500 Crucible Knight, team=26) at an Abductor
Virgin slot — rendered as a copper-armored figure that ignored the
player. Coverage check confirmed 81 such variants existed across 35
c-prefixes in vanilla NR.

Usage:

    python dev/audit_team26_variants.py path/to/NpcParam.csv

The CSV path is the unpacked vanilla NR NpcParam.csv from regulation.
WitchyBND can extract it. The script prints a report of team=26
variants and which ones are not yet in V3_AVOID_VARIANT_NPC_IDS in
oops_v3.py.

Exits 0 if all team=26 variants are covered; 1 otherwise.

Note: a c-prefix where ALL variants are team=26 (e.g. c4492, c52107)
isn't a problem — the soft-fallback in pick_variant_for_tier will
return the original list when filtered set is empty, preserving
placement coverage. But the report flags those c-prefixes anyway so
they can be considered for full c-prefix-level exclusion via
V3_EXCLUDE_TARGET_PREFIXES.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from collections import defaultdict


def load_avoid_set(repo_root):
    """Parse V3_AVOID_VARIANT_NPC_IDS from oops_v3.py via a source scan.
    Avoids importing the module (heavy side-effects)."""
    path = os.path.join(repo_root, 'oops_v3.py')
    with open(path, encoding='utf-8') as f:
        src = f.read()
    m = re.search(r'V3_AVOID_VARIANT_NPC_IDS\s*=\s*\{(.+?)\n\}', src, re.DOTALL)
    if not m:
        raise RuntimeError("Could not locate V3_AVOID_VARIANT_NPC_IDS")
    body = m.group(1)
    ids = set()
    for tok in re.findall(r'\b(\d{8,})\b', body):
        ids.add(int(tok))
    return ids


def cprefix_for_id(rid):
    """Convert an NpcParam ID to its c-prefix string. NR uses both
    4-digit (c2500) and 5-digit (c52101) c-prefixes; the rule is
    rid // 10000 -> the c-prefix integer. We zero-pad to at least 4
    digits, but use whatever width the result needs."""
    cp_int = rid // 10000
    if 1000 <= cp_int <= 9999:
        return f"c{cp_int:04d}"
    if 10000 <= cp_int <= 99999:
        return f"c{cp_int:05d}"
    return None  # unsupported range


def audit(csv_path, repo_root):
    avoid = load_avoid_set(repo_root)

    with open(csv_path, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if r['ID'].isdigit()]

    if 'teamType' not in rows[0]:
        print("ERROR: NpcParam.csv has no teamType column — wrong CSV?")
        return 2

    team26_by_cp = defaultdict(list)
    total_by_cp = defaultdict(int)
    for r in rows:
        rid = int(r['ID'])
        cp = cprefix_for_id(rid)
        if cp is None:
            continue
        total_by_cp[cp] += 1
        if r.get('teamType') == '26':
            team26_by_cp[cp].append((rid, r.get('Name', '')))

    n_total_team26 = sum(len(v) for v in team26_by_cp.values())
    n_uncovered = 0
    n_full_cinematic = []  # c-prefixes where every variant is team=26

    print(f"team=26 variants in NpcParam.csv: {n_total_team26}")
    print(f"V3_AVOID_VARIANT_NPC_IDS size:    {len(avoid)}")
    print()

    print(f"{'cp':>10} {'team26':>8} {'total':>6} {'covered':>9} {'remaining_combat':>17}")
    print('-' * 60)
    for cp in sorted(team26_by_cp):
        t26_ids = team26_by_cp[cp]
        tot = total_by_cp[cp]
        covered = sum(1 for rid, _ in t26_ids if rid in avoid)
        not_covered = [(rid, name) for rid, name in t26_ids if rid not in avoid]
        remaining = tot - len(t26_ids)
        flag = ''
        if remaining == 0:
            flag = '  ⚠ entirely cinematic'
            n_full_cinematic.append(cp)
        print(f"{cp:>10} {len(t26_ids):>8} {tot:>6} {covered:>9} {remaining:>17}{flag}")
        for rid, name in not_covered:
            print(f"    NOT COVERED: {rid}  name={name!r}")
            n_uncovered += 1

    print()
    if n_uncovered:
        print(f"⚠ {n_uncovered} team=26 variants are NOT in V3_AVOID_VARIANT_NPC_IDS.")
        print(f"  Add them to oops_v3.py and re-run this audit to verify.")
    else:
        print(f"All {n_total_team26} team=26 variants are excluded. ✓")

    if n_full_cinematic:
        print()
        print(f"Note: {len(n_full_cinematic)} c-prefix(es) are entirely team=26:")
        print(f"  {n_full_cinematic}")
        print(f"  These c-prefixes are cinematic-only — consider adding to")
        print(f"  V3_EXCLUDE_TARGET_PREFIXES if they're not already excluded.")

    return 1 if n_uncovered else 0


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    csv_path = sys.argv[1]
    if not os.path.isfile(csv_path):
        print(f"ERROR: not a file: {csv_path}")
        return 2
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    return audit(csv_path, repo_root)


if __name__ == '__main__':
    sys.exit(main())
