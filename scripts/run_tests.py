#!/usr/bin/env python3
"""Chunked test runner: run each test file in its own pytest subprocess.

Why: full single-process `pytest` runs intermittently die on this machine
with "Windows fatal exception: access violation" at random points
(ast.parse/json.load). Running one file per subprocess contains the
crash and lets the rest of the suite report normally.

Usage:
    python scripts/run_tests.py                # whole suite
    python scripts/run_tests.py tests/test_dcx_batch_pipeline.py
    python scripts/run_tests.py tests/test_pack_loaders
    python scripts/run_tests.py -v             # pass -v through to pytest

Exit code is nonzero if any file had failures, errors, or crashed.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIRS = ["tests", "healthbar_inplace/tests"]
PER_FILE_TIMEOUT = 600  # seconds

COUNT_RE = re.compile(
    r"(\d+) (passed|failed|skipped|error|errors|deselected)\b")


def discover(paths):
    """Expand dirs to sorted lists of test_*.py files; keep files as-is."""
    files = []
    for raw in paths:
        p = (REPO_ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("test_*.py")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"warning: no such path: {raw}", file=sys.stderr)
    # De-dup, keep stable order.
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def parse_counts(text):
    """Pull passed/failed/skipped/error tallies out of pytest's summary."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for n, kind in COUNT_RE.findall(text):
        key = {"passed": "passed", "failed": "failed", "skipped": "skipped"}.get(
            kind, "errors")
        counts[key] += int(n)
    return counts


def run_file(path, extra_args):
    cmd = [sys.executable, "-m", "pytest", str(path), "-q",
           "-p", "no:cacheprovider", *extra_args]
    # healthbar_inplace tests do `sys.path.insert(0, '..')`, so they must
    # run with their own directory as cwd; everything else runs from root.
    cwd = path.parent if "healthbar_inplace" in path.parts else REPO_ROOT
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True,
                              text=True, timeout=PER_FILE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"crashed": True, "note": f"timeout > {PER_FILE_TIMEOUT}s",
                "counts": parse_counts("")}
    out = proc.stdout + proc.stderr
    counts = parse_counts(out)
    crashed = (proc.returncode not in (0, 1, 5)  # 5 = no tests collected
               or "Windows fatal exception" in out)
    return {"crashed": crashed, "returncode": proc.returncode,
            "counts": counts, "tail": "\n".join(out.splitlines()[-15:])}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*",
                    help="test files or dirs to run (default: whole suite)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="pass -v through to each pytest subprocess")
    args = ap.parse_args()

    files = discover(args.paths or DEFAULT_DIRS)
    if not files:
        print("no test files found", file=sys.stderr)
        return 2

    extra = ["-v"] if args.verbose else []
    totals = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    bad = []  # (file, reason)

    for i, f in enumerate(files, 1):
        rel = f.relative_to(REPO_ROOT)
        r = run_file(f, extra)
        for k in totals:
            totals[k] += r["counts"][k]
        c = r["counts"]
        status = (f"{c['passed']} passed"
                  + (f", {c['failed']} failed" if c["failed"] else "")
                  + (f", {c['errors']} errors" if c["errors"] else "")
                  + (f", {c['skipped']} skipped" if c["skipped"] else ""))
        if r["crashed"]:
            status = "CRASHED " + r.get("note", f"(rc={r.get('returncode')})")
        print(f"[{i:3}/{len(files)}] {rel}: {status}")
        if r["crashed"] or c["failed"] or c["errors"] or r.get("returncode") not in (0, 5):
            bad.append((str(rel), status))

    print("\n" + "=" * 60)
    print(f"TOTAL: {totals['passed']} passed, {totals['failed']} failed, "
          f"{totals['skipped']} skipped, {totals['errors']} errors "
          f"across {len(files)} files")
    if bad:
        print("\nFiles with failures/errors/crashes:")
        for rel, why in bad:
            print(f"  {rel}: {why}")
        return 1
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
