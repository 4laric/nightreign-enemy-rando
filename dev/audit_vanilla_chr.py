#!/usr/bin/env python3
"""Audit a chr/ folder for c-prefix presence and produce empirical evidence
about which chrs ship with vanilla NR vs which require optional packs.

Usage
-----

Run twice, once on each chr/ folder, then diff:

    # 1. Scan vanilla NR install (no mods)
    python dev/audit_vanilla_chr.py \
        --chr-dir "C:/Program Files (x86)/Steam/steamapps/common/ELDEN RING NIGHTREIGN/Game/chr" \
        --label vanilla \
        --out dev/chr_audit_vanilla.json

    # 2. Scan your me3 profile chr/ (mods active)
    python dev/audit_vanilla_chr.py \
        --chr-dir "C:/Users/.../AppData/Local/garyttierney/me3/.../chr" \
        --label modded \
        --out dev/chr_audit_modded.json

    # 3. Diff the two
    python dev/audit_vanilla_chr.py \
        --diff dev/chr_audit_vanilla.json dev/chr_audit_modded.json

Detection rule mirrors the Inventory tab's `detect_asset_packs`:
a c-prefix is "present" if any chr file matching that prefix exists
(chrbnd, anibnd, behbnd, OR texbnd). Permissive on purpose — NR sometimes
ships only anibnd standalone while the chrbnd lives in a packed bundle,
and we'd rather false-positive than scare-flag every chr.

The audit is intentionally lightweight — no decompression, no parsing,
just file presence by name. Output JSON is human-readable and feeds the
heritage_pack.json authoring workflow:

  - "vanilla" scan tells us which prefixes ship with NR alone
  - "modded" scan tells us total available
  - diff = optional-pack contribution (heritage + BFER + etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict


CHR_FILE_PATTERN = re.compile(
    r'^c(\d{4})\.(?:chrbnd|anibnd|behbnd|texbnd|hkx)(?:\.dcx)?(?:\.[\w-]+)?$',
    re.IGNORECASE)


def scan_chr_dir(chr_dir):
    """Walk a chr/ folder, return prefix → list of files seen."""
    if not os.path.isdir(chr_dir):
        raise FileNotFoundError(f"chr dir not found: {chr_dir}")

    by_prefix = defaultdict(list)
    for name in os.listdir(chr_dir):
        m = CHR_FILE_PATTERN.match(name)
        if m:
            cp = f"c{m.group(1)}"
            by_prefix[cp].append(name)
    return dict(by_prefix)


def write_audit(chr_dir, label, out_path):
    by_prefix = scan_chr_dir(chr_dir)
    payload = {
        '_meta': {
            'tool': 'audit_vanilla_chr.py',
            'chr_dir': os.path.abspath(chr_dir),
            'label': label,
            'detection_rule': (
                'permissive — present if any chr file matches the prefix '
                '(chrbnd/anibnd/behbnd/texbnd, .dcx optional)'),
        },
        'prefix_count': len(by_prefix),
        'prefixes': sorted(by_prefix.keys()),
        'files_per_prefix': {cp: sorted(fs) for cp, fs in sorted(by_prefix.items())},
    }
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, sort_keys=False)
    print(f"Wrote {out_path}: {len(by_prefix)} prefixes from {chr_dir}")
    return payload


def diff_audits(vanilla_path, modded_path):
    with open(vanilla_path, encoding='utf-8') as f:
        vanilla = json.load(f)
    with open(modded_path, encoding='utf-8') as f:
        modded = json.load(f)

    vanilla_set = set(vanilla['prefixes'])
    modded_set = set(modded['prefixes'])

    only_vanilla = sorted(vanilla_set - modded_set)
    only_modded = sorted(modded_set - vanilla_set)
    both = sorted(vanilla_set & modded_set)

    print(f"\n=== vanilla ({vanilla['_meta']['chr_dir']}) ===")
    print(f"  {len(vanilla_set)} prefixes")
    print(f"\n=== modded  ({modded['_meta']['chr_dir']}) ===")
    print(f"  {len(modded_set)} prefixes")
    print(f"\n=== Diff ===")
    print(f"  Both: {len(both)}")
    print(f"  Only in vanilla (mod removed?): {len(only_vanilla)}")
    if only_vanilla:
        print(f"    {only_vanilla}")
    print(f"  Only in modded (mod added — heritage/BFER/etc): {len(only_modded)}")
    if only_modded:
        print(f"    {only_modded}")
    print()
    print("These 'only in modded' prefixes are optional-pack content. To build")
    print("heritage_pack.json, classify each by source mod (heritage vs BFER).")


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    ap.add_argument('--chr-dir', help='Path to a chr/ folder to scan')
    ap.add_argument('--label', default='unlabeled',
                    help='Tag for this scan (e.g. vanilla, modded)')
    ap.add_argument('--out', help='Output JSON path')
    ap.add_argument('--diff', nargs=2, metavar=('VANILLA', 'MODDED'),
                    help='Diff two audit JSON files (vanilla first, modded second)')
    args = ap.parse_args()

    if args.diff:
        diff_audits(*args.diff)
        return 0

    if not args.chr_dir or not args.out:
        ap.error("--chr-dir and --out required (or use --diff)")

    write_audit(args.chr_dir, args.label, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
