#!/usr/bin/env python3
"""audit_heritage_chr_deployment.py — compare heritage_pack chr/ deployment
against ER's chr/ to find systematically-missing files.

Origin (v0.25.5): user investigated "scorpion AI still broken" after
running import_heritage_ai_scripts.py and uploading ER vs mod chr files
for c5190. Initial 4-file upload led to incorrect "missing div_anibnds"
diagnosis. Full dir listing (this session) confirmed c5190 / c5192 /
c5193 deployments are actually complete relative to ER's file set.

But the same audit surfaced 4 chrs (c4541, c5650, c6200, c6230) that
DO have apparent base-trio gaps (missing .behbnd.dcx and/or .chrbnd.dcx).
Most turn out to be shared-anim carriers (ER ships them without
behbnd/chrbnd too — by design, the carriers only hold animations that
their numbered siblings reference). c4541 is the outlier worth checking.

This tool runs the audit live so we don't repeat the manual exercise
every time a heritage chr appears broken.

Categories of "missing":
- BASE_INCOMPLETE: missing one of .anibnd, .behbnd, .chrbnd (the
  trio every spawnable chr needs). If ER also lacks these, the chr
  is likely a shared-anim carrier and the gap is intentional.
- DIV_MISSING: ER ships _divNN.anibnd files but mod doesn't have them
  (AI-CRITICAL — combat anims live here for many chrs).
- TEX_MISSING: ER ships _h.texbnd / _l.texbnd but mod doesn't have them
  (VISUAL only — chr renders untextured/stub).
- OTHER_MISSING: other file types ER has and mod doesn't (rare).

Usage
-----

  python3 dev/audit_heritage_chr_deployment.py \\
      --er-chr   "C:/Program Files (x86)/Steam/.../ELDEN RING/Game/chr" \\
      --nr-chr   "C:/Program Files (x86)/Steam/.../ELDEN RING NIGHTREIGN/Game/chr" \\
      --mod-chr  "C:/Users/<you>/.../me3/.../onlyrando/nrando/chr" \\
      [--show-complete]     # show even chrs with no gaps
      [--only-critical]     # show only AI-CRITICAL gaps
"""
from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict


CHR_FILE_RE = re.compile(r'^(c\d{4,5})((?:_[a-z0-9]+)*)\.([a-z]+)\.dcx$')


def parse_chr_dir(path: str) -> dict[str, set[str]]:
    """Return {chr_id: set(file_suffix)} where file_suffix is e.g.
    '.anibnd.dcx' or '_div00.anibnd.dcx'."""
    out = defaultdict(set)
    if not os.path.isdir(path):
        raise SystemExit(f"Not a directory: {path}")
    for fname in os.listdir(path):
        m = CHR_FILE_RE.match(fname)
        if not m: continue
        chr_id = m.group(1)
        suffix = f'{m.group(2)}.{m.group(3)}.dcx'
        out[chr_id].add(suffix)
    return dict(out)


def categorize_missing(suffix: str) -> str:
    """Bucket missing-file category for prioritization."""
    if suffix in ('.anibnd.dcx', '.behbnd.dcx', '.chrbnd.dcx'):
        return 'BASE_INCOMPLETE'
    if '_div' in suffix and suffix.endswith('.anibnd.dcx'):
        return 'DIV_MISSING'
    if 'texbnd' in suffix:
        return 'TEX_MISSING'
    return 'OTHER_MISSING'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--er-chr',  required=True, help="ER's Game/chr/ directory")
    ap.add_argument('--nr-chr',  required=True, help="NR's Game/chr/ directory")
    ap.add_argument('--mod-chr', required=True, help="me3 mod profile chr/ overlay directory")
    ap.add_argument('--show-complete', action='store_true',
                     help="Also show chrs with no gaps")
    ap.add_argument('--only-critical', action='store_true',
                     help="Only show AI-CRITICAL gaps (BASE_INCOMPLETE + DIV_MISSING)")
    args = ap.parse_args()

    er  = parse_chr_dir(args.er_chr)
    nr  = parse_chr_dir(args.nr_chr)
    mod = parse_chr_dir(args.mod_chr)

    print(f"ER  chrs:   {len(er):>4d}  ({sum(len(v) for v in er.values())} files)")
    print(f"NR  chrs:   {len(nr):>4d}  ({sum(len(v) for v in nr.values())} files)")
    print(f"Mod chrs:   {len(mod):>4d}  ({sum(len(v) for v in mod.values())} files)")
    print()

    # Partition mod chrs
    heritage  = [c for c in sorted(mod) if c not in nr]
    overrides = [c for c in sorted(mod) if c in nr]
    print(f"Heritage chrs in mod (NOT in NR): {len(heritage)}")
    print(f"Override chrs  in mod (also in NR): {len(overrides)}")
    print()

    # Audit each heritage chr
    print("=" * 90)
    print("HERITAGE CHR AUDIT")
    print("=" * 90)
    summary_by_chr = []

    for chr_id in heritage:
        mod_files = mod[chr_id]
        if chr_id not in er:
            summary_by_chr.append((chr_id, 'NOT_IN_ER', mod_files, None, set()))
            continue
        er_files = er[chr_id]
        missing = er_files - mod_files
        cats = defaultdict(int)
        for s in missing:
            cats[categorize_missing(s)] += 1
        is_shared_anim_carrier = (
            '.behbnd.dcx' not in er_files and '.chrbnd.dcx' not in er_files
            and '.anibnd.dcx' in er_files
        )
        status = 'COMPLETE' if not missing else 'INCOMPLETE'
        if is_shared_anim_carrier:
            status += '_SHARED_ANIM_CARRIER'
        summary_by_chr.append((chr_id, status, mod_files, er_files, missing))

    # Filter / display
    for chr_id, status, mod_f, er_f, missing in summary_by_chr:
        if not args.show_complete and 'COMPLETE' in status and not missing:
            continue
        if args.only_critical:
            cats = {categorize_missing(s) for s in missing}
            if not (cats & {'BASE_INCOMPLETE', 'DIV_MISSING'}):
                continue
        if status == 'NOT_IN_ER':
            print(f"  {chr_id}  [NOT IN ER — likely MMV/NR-specific]  mod has {len(mod_f)} files")
            continue
        mc, ec = len(mod_f), len(er_f)
        if missing:
            cat_counts = defaultdict(int)
            for s in missing:
                cat_counts[categorize_missing(s)] += 1
            cat_str = ', '.join(f'{k}={v}' for k, v in sorted(cat_counts.items()))
            tag = ''
            if 'SHARED' in status:
                tag = '  ← shared-anim carrier; missing OK if ER also lacks them'
            print(f"  {chr_id}  mod={mc} er={ec}  missing={len(missing):>2d}  ({cat_str}){tag}")
            for s in sorted(missing):
                cat = categorize_missing(s)
                flag = ''
                if cat == 'BASE_INCOMPLETE' and 'SHARED' not in status:
                    flag = '  ★ AI CRITICAL'
                elif cat == 'DIV_MISSING':
                    flag = '  ★ AI CRITICAL'
                print(f"      missing: c{chr_id[1:]}{s}{flag}")
        else:
            print(f"  {chr_id}  mod={mc} er={ec}  COMPLETE")

    # Roll-up
    critical = [r for r in summary_by_chr
                 if r[4] and any(categorize_missing(s) in ('BASE_INCOMPLETE','DIV_MISSING')
                                  for s in r[4])
                 and 'SHARED' not in r[1]]
    print()
    print("=" * 90)
    print("ROLL-UP — AI-CRITICAL GAPS (excluding shared-anim carriers)")
    print("=" * 90)
    print(f"Heritage chrs with AI-critical missing files: {len(critical)}")
    for chr_id, status, _, _, missing in critical:
        crit_missing = sorted(s for s in missing
                                if categorize_missing(s) in ('BASE_INCOMPLETE','DIV_MISSING'))
        print(f"  {chr_id}: {', '.join(crit_missing)}")


if __name__ == '__main__':
    main()
