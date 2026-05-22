#!/usr/bin/env python3
"""
preflight_chr_assets.py — validate that every chr in the active roster
has all file-class dependencies present in either the me3 target dir
or the c-prefix's expected source install.

Diagnoses CTD risks by category (load-time miss, AI freeze, combat-FFX
miss, soft RECOMMENDED miss) so an observed CTD can be traced back to
a specific missing-data class without playtest iteration.

The dependency model is documented in dev/chr_asset_resolver.py
(FILE_CLASSES + SHARED_DEPS). This module is the CLI / human-readable
front-end.

Usage:
    python preflight_chr_assets.py \\
        --nr-install   /path/to/nightreign/Game \\
        --er-install   /path/to/elden-ring/Game \\
        --mmv-install  /path/to/me3/profile/mods/mmv \\
        --me3-package  /path/to/me3/profile/mods/oops_rando \\
        --json-out     /tmp/preflight.json

    # Triage one c-prefix:
    python preflight_chr_assets.py --only c5840 [other args...]

Exit code: 1 if any roster chr has at least one MISSING-everywhere
file in a hard severity class (REQUIRED / AI_BATTLE / AI_LOGIC /
COMBAT_FFX); 0 otherwise. v0.24.86-patch1: the summary now distinguishes
probable-CTD (REQUIRED + COMBAT_FFX misses) from probable-freeze
(AI_BATTLE + AI_LOGIC misses after the union rule) — these are
different runtime failure modes that warrant different remediation.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Add dev/ to path so we can import the resolver
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO / "dev"))

from chr_asset_resolver import build_roster, check_chr, check_shared  # noqa: E402


def render_console(report):
    out = []
    out.append("=" * 70)
    out.append("Preflight chr-asset check")
    out.append("=" * 70)
    out.append("")

    # Shared deps
    out.append("Shared dependencies:")
    for s in report["shared"]:
        if s["kind"] == "file":
            sz = (f" ({s['target_size']/1024:.0f}KB)"
                  if s["target_size"] else "")
            line = (f"  [{s['status']:<8}] {s['subdir']}{s['filename']}"
                    f"{sz}")
            if s["status"] == "COPYABLE":
                src_str = ", ".join(
                    f"{c['label']}={c['size']/1024:.0f}KB"
                    for c in s["copyable_from"])
                line += f"  copy from: {src_str}"
            out.append(line)
            if (s["filename"] == "aicommon.luabnd.dcx"
                    and s["target_size"] and s["target_size"] < 100_000):
                out.append(
                    f"           ! aicommon is small "
                    f"(~{s['target_size']/1024:.0f}KB); expected MMV-superset "
                    f"(~135KB). Cross-game / DLC chrs may freeze.")
        else:
            line = f"  [{s['status']:<8}] {s['subdir']}"
            if s["status"] == "COPYABLE":
                line += f"  copy from: {', '.join(s['sources_with_files'])}"
            out.append(line)
    out.append("")

    # Per-chr summary
    counts = defaultdict(int)
    by_status = defaultdict(list)
    for r in report["chrs"]:
        counts[r["worst_status"]] += 1
        by_status[r["worst_status"]].append(r)

    # v0.24.86-patch1: split MISSING into probable-CTD vs probable-FREEZE
    # before reporting the headline counts. CTD = REQUIRED or COMBAT_FFX
    # absent (hard crash). Freeze = AI scripts absent but chr files
    # present (chr stands idle).
    ctd_severities = {"REQUIRED", "COMBAT_FFX"}
    freeze_severities = {"AI_BATTLE", "AI_LOGIC"}
    ctd_count = sum(
        1 for r in by_status["MISSING"]
        if any(f["status"] == "MISSING" and f["severity"] in ctd_severities
               for f in r["findings"]))
    freeze_only_count = sum(
        1 for r in by_status["MISSING"]
        if not any(f["status"] == "MISSING" and f["severity"] in ctd_severities
                   for f in r["findings"])
        and any(f["status"] == "MISSING" and f["severity"] in freeze_severities
                for f in r["findings"]))

    out.append(f"Per-chr summary: "
               f"{counts['OK']} OK, "
               f"{counts['COPYABLE']} need copy, "
               f"{ctd_count} probable CTD, "
               f"{freeze_only_count} probable freeze")
    out.append("")

    hard_severities = {"REQUIRED", "AI_BATTLE", "AI_LOGIC", "COMBAT_FFX"}
    ctd_severities  = {"REQUIRED", "COMBAT_FFX"}
    freeze_severities = {"AI_BATTLE", "AI_LOGIC"}

    # v0.24.86-patch1: split the by_status["MISSING"] bucket by whether
    # the chr is a probable CRASH (REQUIRED or COMBAT_FFX miss) or a
    # probable FREEZE (AI miss only — chr loads but stands idle). Same
    # chr can be in both buckets if it has both classes of miss.
    probable_ctd = []
    probable_freeze = []
    for r in by_status["MISSING"]:
        has_ctd_miss = any(
            f["status"] == "MISSING" and f["severity"] in ctd_severities
            for f in r["findings"])
        has_freeze_miss = any(
            f["status"] == "MISSING" and f["severity"] in freeze_severities
            for f in r["findings"])
        if has_ctd_miss:
            probable_ctd.append(r)
        elif has_freeze_miss:
            probable_freeze.append(r)

    if probable_ctd:
        out.append(f"Probable-CTD c-prefixes ({len(probable_ctd)} — "
                   f"REQUIRED or COMBAT_FFX miss in all sources):")
        for r in probable_ctd:
            hard_missing = [f for f in r["findings"]
                            if f["status"] == "MISSING"
                            and f["severity"] in ctd_severities]
            soft_missing = [f for f in r["findings"]
                            if f["status"] == "MISSING"
                            and f["severity"] not in hard_severities]
            copyable = [f for f in r["findings"]
                        if f["status"] == "COPYABLE"]
            out.append(f"  {r['c_prefix']:<7} ({r['expected_source']}):")
            for m in hard_missing:
                out.append(f"    [{m['severity']:<11}] {m['subdir']}{m['pattern']}")
            if copyable:
                sources_used = sorted(set(c["from"] for c in copyable))
                out.append(f"    (+{len(copyable)} other files copyable "
                           f"from {', '.join(sources_used)})")
            if soft_missing:
                out.append(f"    (+{len(soft_missing)} RECOMMENDED files "
                           f"missing — soft, won't CTD)")
        out.append("")

    if probable_freeze:
        out.append(f"Probable-FREEZE c-prefixes ({len(probable_freeze)} — "
                   f"AI scripts (battle AND logic) miss in all sources; "
                   f"chr loads but stands idle, no crash):")
        # Only show the first ~10 of these — they're usually a long
        # tail dominated by roster phantoms or chrs with intentionally-
        # external AI (e.g. player chrs c0XXX).
        for r in probable_freeze[:10]:
            ai_missing = [f for f in r["findings"]
                          if f["status"] == "MISSING"
                          and f["severity"] in freeze_severities]
            out.append(f"  {r['c_prefix']:<7} ({r['expected_source']}): "
                       f"{len(ai_missing)} AI script(s) absent")
        if len(probable_freeze) > 10:
            out.append(f"  ...and {len(probable_freeze) - 10} more "
                       f"(use --json-out for full list)")
        out.append("")

    if by_status["COPYABLE"]:
        out.append("Copyable c-prefixes (present in a source dir, "
                   "absent from target):")
        for r in by_status["COPYABLE"][:20]:
            copyable = [f for f in r["findings"]
                        if f["status"] == "COPYABLE"]
            sources_used = sorted(set(c["from"] for c in copyable))
            out.append(f"  {r['c_prefix']:<7} ({r['expected_source']}): "
                       f"{len(copyable)} files from "
                       f"{', '.join(sources_used)}")
        if len(by_status["COPYABLE"]) > 20:
            out.append(f"  ...and {len(by_status['COPYABLE']) - 20} more")
        out.append("")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--nr-install",  type=str, default="")
    ap.add_argument("--er-install",  type=str, default="")
    ap.add_argument("--mmv-install", type=str, default="")
    ap.add_argument("--me3-package", type=str, required=True)
    ap.add_argument("--nr-enemy-tags",     type=str,
                    default="data/nr_enemy_tags.json")
    ap.add_argument("--mmv-imports",       type=str,
                    default="data/mmv_imports.json")
    ap.add_argument("--heritage-pack",     type=str,
                    default="data/heritage_pack.json")
    ap.add_argument("--missing-chr-files", type=str,
                    default="data/nr_missing_chr_files.json")
    ap.add_argument("--only", type=str, default=None,
                    help="Restrict to a single c-prefix for triage")
    ap.add_argument("--json-out", type=str, default=None)
    args = ap.parse_args()

    sources = {
        "nr":  args.nr_install.strip()  or None,
        "er":  args.er_install.strip()  or None,
        "mmv": args.mmv_install.strip() or None,
    }
    target = args.me3_package.strip()

    roster = build_roster(
        args.nr_enemy_tags, args.mmv_imports,
        args.heritage_pack, args.missing_chr_files,
    )

    if args.only:
        if args.only not in roster:
            print(f"c-prefix {args.only} not in roster — treating as 'nr' "
                  f"for triage")
            roster = {args.only: "nr"}
        else:
            roster = {args.only: roster[args.only]}

    report = {
        "sources": {k: v for k, v in sources.items() if v},
        "target": target,
        "shared": check_shared(sources, target),
        "chrs": [],
    }
    for cp in sorted(roster):
        if roster[cp] == "skip":
            continue
        report["chrs"].append(check_chr(cp, roster[cp], sources, target))

    print(render_console(report))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Wrote JSON report: {args.json_out}")

    any_missing = any(r["worst_status"] == "MISSING"
                      for r in report["chrs"])
    return 1 if any_missing else 0


if __name__ == "__main__":
    sys.exit(main())
