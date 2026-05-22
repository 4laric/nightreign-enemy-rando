#!/usr/bin/env python3
"""Audit BFER variants_per_prefix for suspicious npc_param_ids.

Re-run when a new BFER version ships a new variant manifest. The output
should be cross-checked against V3_AVOID_VARIANT_NPC_IDS in oops_v3.py;
new suspicious variants need to be added to that set.

Detection heuristics (kept simple — manual review still recommended):

  1. npc_param_id suffix >= 9000 on a phase-locked boss c-prefix
     (FromSoft convention: 9xxx range encodes scripted/cinematic state,
     typically phase-transition forms hardcoded at 1hp because the phase
     change is supposed to fire on hit-detect cutscene rather than HP).

  2. mmv_name contains 雕像 (Chinese for "statue") — these are arena
     decorations, not enemies.

Usage:

    python dev/audit_bfer_variants.py

Reads bfer_imports.json and bfer_imports_v2.json from the repo root,
prints a report of suspicious variants. Exits 0 on success; if the
hardcoded V3_AVOID_VARIANT_NPC_IDS set covers all detected suspicious
variants, prints "All suspicious variants are excluded."
"""
from __future__ import annotations

import json
import os
import re
import sys


PHASE_LOCKED_BFER_PREFIXES = {
    'c2010',  # Margit
    'c2031',  # v0.23.20: BFER repurposes c2031 (vanilla ER Hoarah Loux)
              # for Rennala phase 2. Cocoon-derived variants empirically
              # 1hp at random placements (e.g. 20310124 in seed 767092).
    'c2050',  # Ranni (questline-driven; not all variants combat)
    'c2110',  # Maliketh / Beast Clergyman
    'c2120',  # Malenia (Blade of Miquella → Goddess of Rot)
    'c2180',  # Melina (friendly NPC by default)
    'c2190',  # Radagon (paired with Elden Beast)
    'c2200',  # Elden Beast (Radagon phase 2)
    'c4720',  # v0.23.26: BFER Godfrey / Hoarah Loux (phase 1 → phase 2).
              # Phase-2 variant 47200100 empirically 1hp at evergaol slots
              # (seed 356064, m49_19_00_00 pi=2) when no boss-intro EMEVD
              # fires. Cinematic '初王' variant 47200070 same class.
    'c5220',  # Promised Consort Radahn (multi-phase)
}

# v0.23.20: suffix threshold lowered from 9000 to 8000. The 9xxx range
# captures cinematic/scripted phase-lock variants (1hp, statue, friendly
# NPC). The 8xxx range captures ghost-recall variants — for Margit
# specifically, the Stormveil "memory of grace" replay system uses 8xxx
# variants with a translucent blue VFX baked in. Empirically observed
# in seed 767092: 20108000, 20108500, 20108562 all loaded as ghost
# Margits at field slots. Other prefixes in PHASE_LOCKED_BFER_PREFIXES
# may have analogous 8xxx ghost variants — broadening the rule catches
# them by symmetry. The 7xxx range remains untouched (suspected NG+
# scaling tier, not a render variant — pending playtest evidence).
SUSPICIOUS_SUFFIX_THRESHOLD = 8000

STATUE_KEYWORD = '雕像'  # Chinese for "statue"


def load_avoid_set(repo_root):
    """Parse V3_AVOID_VARIANT_NPC_IDS from oops_v3.py without importing
    the module (which has heavy side-effects)."""
    path = os.path.join(repo_root, 'oops_v3.py')
    with open(path, encoding='utf-8') as f:
        src = f.read()
    m = re.search(r'V3_AVOID_VARIANT_NPC_IDS\s*=\s*\{(.+?)\n\}', src, re.DOTALL)
    if not m:
        raise RuntimeError("Could not locate V3_AVOID_VARIANT_NPC_IDS")
    body = m.group(1)
    # Pull integer literals (ignore comments)
    ids = set()
    for tok in re.findall(r'\b(\d{8,})\b', body):
        ids.add(int(tok))
    return ids


def audit(repo_root):
    avoid = load_avoid_set(repo_root)

    suspicious = []  # (pid, cp, name, reasons)
    for fname in ('bfer_imports.json', 'bfer_imports_v2.json'):
        path = os.path.join(repo_root, fname)
        if not os.path.isfile(path):
            continue
        with open(path, encoding='utf-8') as f:
            pack = json.load(f)
        for cp, variants in pack.get('variants_per_prefix', {}).items():
            for v in variants:
                pid = v.get('npc_param_id')
                name = v.get('mmv_name', '')
                if not isinstance(pid, int):
                    continue
                cp_int = int(cp[1:])
                suffix = pid - cp_int * 10000

                reasons = []
                if suffix >= SUSPICIOUS_SUFFIX_THRESHOLD and cp in PHASE_LOCKED_BFER_PREFIXES:
                    reasons.append(f'>={SUSPICIOUS_SUFFIX_THRESHOLD}-suffix on phase-locked boss (suffix {suffix})')
                if STATUE_KEYWORD in name:
                    reasons.append(f'statue ({STATUE_KEYWORD} in name)')
                if reasons:
                    suspicious.append((pid, cp, name, reasons))

    print(f"Suspicious variants detected: {len(suspicious)}")
    print(f"Currently in V3_AVOID_VARIANT_NPC_IDS: {len(avoid)}")
    print()

    uncovered = []
    for pid, cp, name, reasons in suspicious:
        covered = pid in avoid
        marker = '✓' if covered else '✗ NOT COVERED'
        print(f"  {marker}  {pid}  {cp}  '{name}'  ← {'; '.join(reasons)}")
        if not covered:
            uncovered.append((pid, cp, name, reasons))

    print()
    if not uncovered:
        print("All suspicious variants are excluded. ✓")
        return 0
    else:
        print(f"⚠ {len(uncovered)} suspicious variants are NOT in V3_AVOID_VARIANT_NPC_IDS.")
        print("  Add them to oops_v3.py and re-run this audit to verify.")
        return 1


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    return audit(repo_root)


if __name__ == '__main__':
    sys.exit(main())
