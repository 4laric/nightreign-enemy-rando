#!/usr/bin/env python3
"""
audit_source_tags.py — verify each chr's _source tag in nr_enemy_tags
against actual byte-level evidence in vanilla NR MSBs.

WHY THIS EXISTS

The _source tag is a behavioral classification used by the engine to
decide how chrs participate in swaps:

  nr_placed       — placed in vanilla NR MSB Part lists (full swap)
  script_spawn    — spawned via EMEVD scripts only (target-only via
                    V3_TARGET_ONLY_SOURCES, auto-promoted to
                    V3_ARENA_ONLY_TARGETS if expects_boss_arena)
  mmv_import      — imported from More Map Variations mod
  er_heritage_v1  — imported from Elden Ring (target-only)
  ...

Misclassification matters: 'script_spawn' shrinks the chr's
placement opportunities significantly. If a chr is actually MSB-
placed but mis-tagged as script_spawn, it's getting routed through
the narrow arena-only-target path when it should be in the full
nr_placed pool.

ENCODING NOTE

NR MSB files store chr-reference strings as UTF-16-LE (not UTF-8).
A naive ASCII grep ('grep c7920 file.msb') will find ZERO hits even
when the chr is heavily referenced. This script handles both
encodings; current evidence is that UTF-16-LE is the format and
UTF-8 occurrences are noise.

USAGE

  python3 dev/audit_source_tags.py
        Audit against /vanilla_msbs/ (the bundled snapshot).

  python3 dev/audit_source_tags.py --msb-dir /path/to/unpacked/map/mapstudio
        Audit against a UXM-unpacked NR install's mapstudio directory.

  python3 dev/audit_source_tags.py --verbose
        Show full placement details (every (msb, count) pair).

  python3 dev/audit_source_tags.py --json
        Emit a JSON report for tooling.

EXIT CODES

  0  no misclassifications found
  1  at least one chr is mis-tagged as script_spawn but appears in MSBs
  2  MSB directory not found or no .msb / .msb.dcx files in it

CAVEATS

  - This scans MSB byte content for c-prefix string occurrences. It
    catches the chr being REFERENCED in the MSB (as a Model name or
    similar). It does not distinguish between a chr being placed as
    an actual Part versus being referenced as a model template.
    Both are signals that the chr is MSB-resident, which is what the
    _source classification cares about.
  - .msb.dcx files are skipped if Oodle isn't available; only raw
    .msb files (already-decompressed) are inspected. Run dcx_batch
    decompression first if you only have .dcx files.
  - Lower-tier chrs (trash, grunt) can appear at non-boss slots; the
    audit still surfaces those legitimately. Combine with the chr's
    tier tag for triage.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


# -------------------------------------------------------------------
# Encoding handling
# -------------------------------------------------------------------

# Pattern for c-prefix strings: c followed by 4-5 digits.
# Inside MSB binaries this lands inside Model/Part name fields.
_CP_REGEX_UTF8 = re.compile(rb'c[0-9]{4,5}')
# UTF-16-LE: each ASCII char becomes byte + \x00
_CP_REGEX_UTF16LE = re.compile(rb'c\x00(?:[0-9]\x00){4,5}')


def find_cps_in_msb(msb_bytes):
    """Scan an MSB's raw bytes for c-prefix references in BOTH UTF-8
    and UTF-16-LE. Returns dict {cp: {'utf8': n, 'utf16le': n}}.

    Vanilla NR MSBs use UTF-16-LE for chr references. UTF-8 paths
    here exist mainly to catch malformed / dev-edited files and to
    confirm-by-absence that the file is well-formed."""
    found = defaultdict(lambda: {'utf8': 0, 'utf16le': 0})

    for m in _CP_REGEX_UTF8.finditer(msb_bytes):
        cp = m.group().decode('ascii')
        found[cp]['utf8'] += 1

    for m in _CP_REGEX_UTF16LE.finditer(msb_bytes):
        cp = m.group().decode('utf-16-le')
        found[cp]['utf16le'] += 1

    return dict(found)


# -------------------------------------------------------------------
# MSB enumeration
# -------------------------------------------------------------------

def list_msbs(msb_dir):
    """Return sorted list of MSB filenames in msb_dir. Only includes
    raw .msb files; .msb.dcx is skipped (needs decompression first)."""
    if not os.path.isdir(msb_dir):
        return None  # caller decides how to message this
    msbs = sorted(f for f in os.listdir(msb_dir)
                  if f.endswith('.msb') and not f.endswith('.msb.dcx'))
    return msbs


def scan_all(msb_dir, verbose=False):
    """Walk every MSB in msb_dir and aggregate c-prefix occurrences.
    Returns dict {cp: {msb: {'utf8': n, 'utf16le': n}}}."""
    by_cp = defaultdict(lambda: defaultdict(
        lambda: {'utf8': 0, 'utf16le': 0}))

    msbs = list_msbs(msb_dir)
    if msbs is None:
        return None, 0
    if not msbs:
        return by_cp, 0

    for fname in msbs:
        path = os.path.join(msb_dir, fname)
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError as e:
            if verbose:
                print(f"  ! couldn't read {fname}: {e}", file=sys.stderr)
            continue
        per_msb = find_cps_in_msb(data)
        for cp, counts in per_msb.items():
            by_cp[cp][fname]['utf8'] += counts['utf8']
            by_cp[cp][fname]['utf16le'] += counts['utf16le']

    return by_cp, len(msbs)


# -------------------------------------------------------------------
# Audit logic
# -------------------------------------------------------------------

def load_tags():
    """Load nr_enemy_tags.json from the repo root."""
    with open(os.path.join(REPO_ROOT, 'data', 'nr_enemy_tags.json')) as f:
        return json.load(f)


def audit(msb_dir, verbose=False):
    """Cross-reference _source=script_spawn tags against MSB evidence.
    Returns a result dict for downstream rendering."""
    tags = load_tags()
    script_spawn_cps = {cp for cp, t in tags.items()
                        if isinstance(t, dict)
                        and t.get('_source') == 'script_spawn'}

    by_cp, n_msbs = scan_all(msb_dir, verbose=verbose)

    if by_cp is None:
        return {'error': 'msb_dir_missing', 'msb_dir': msb_dir}
    if n_msbs == 0:
        return {'error': 'no_msbs', 'msb_dir': msb_dir}

    misclassified = []   # script_spawn-tagged but found in MSBs
    correctly_tagged = []  # script_spawn-tagged and absent from MSBs

    for cp in sorted(script_spawn_cps):
        per_msb = by_cp.get(cp, {})
        total_utf8 = sum(v['utf8'] for v in per_msb.values())
        total_utf16le = sum(v['utf16le'] for v in per_msb.values())
        total = total_utf8 + total_utf16le
        if total > 0:
            misclassified.append({
                'c_prefix': cp,
                'name': tags[cp].get('name', '?'),
                'total_refs': total,
                'utf8_refs': total_utf8,
                'utf16le_refs': total_utf16le,
                'in_msbs': sorted(
                    [(msb, v['utf8'] + v['utf16le'])
                     for msb, v in per_msb.items() if v['utf8'] + v['utf16le']],
                    key=lambda x: -x[1]),
            })
        else:
            correctly_tagged.append({
                'c_prefix': cp,
                'name': tags[cp].get('name', '?'),
            })

    return {
        'msb_dir': msb_dir,
        'n_msbs_scanned': n_msbs,
        'n_script_spawn_tags': len(script_spawn_cps),
        'misclassified': misclassified,
        'correctly_tagged': correctly_tagged,
    }


# -------------------------------------------------------------------
# Reporting
# -------------------------------------------------------------------

def render_text(result, verbose=False):
    if result.get('error') == 'msb_dir_missing':
        print(f"✗ MSB directory not found: {result['msb_dir']}",
              file=sys.stderr)
        print(f"  Pass --msb-dir to point at a UXM-unpacked NR "
              f"install's map/mapstudio/ directory.", file=sys.stderr)
        return 2
    if result.get('error') == 'no_msbs':
        print(f"✗ No .msb files found in: {result['msb_dir']}",
              file=sys.stderr)
        print(f"  This directory may contain only .msb.dcx — "
              f"run decompression first via dcx_batch.", file=sys.stderr)
        return 2

    print(f"=== _source='script_spawn' audit ===")
    print(f"  MSB directory:       {result['msb_dir']}")
    print(f"  MSBs scanned:        {result['n_msbs_scanned']}")
    print(f"  script_spawn tags:   {result['n_script_spawn_tags']}")
    print(f"  Misclassified:       {len(result['misclassified'])}")
    print(f"  Correctly tagged:    {len(result['correctly_tagged'])}")
    print()

    if result['misclassified']:
        print("=== MISCLASSIFIED — tagged script_spawn but present in MSBs ===")
        for entry in result['misclassified']:
            cp = entry['c_prefix']
            name = entry['name']
            n = entry['total_refs']
            n_utf8 = entry['utf8_refs']
            n_utf16le = entry['utf16le_refs']
            print(f"\n  {cp} ({name})")
            print(f"    {n} total refs ({n_utf16le} utf-16-le, "
                  f"{n_utf8} utf-8) across {len(entry['in_msbs'])} MSBs")
            if verbose:
                for msb, count in entry['in_msbs'][:10]:
                    print(f"      {msb}: {count} refs")
                if len(entry['in_msbs']) > 10:
                    print(f"      ... +{len(entry['in_msbs']) - 10} more")
            else:
                top = ', '.join(f"{msb}({c})"
                                for msb, c in entry['in_msbs'][:5])
                print(f"    Top MSBs: {top}"
                      + (' ...' if len(entry['in_msbs']) > 5 else ''))
        print()
        print("FIX: reclassify these chrs by editing data/nr_enemy_tags.json:")
        print("  _source: 'script_spawn'  →  'nr_placed'")
        print("Then regenerate downstream caches via:")
        print("  python3 dev/extract_placement_budget.py")
        return 1
    else:
        print("✓ No misclassifications. All script_spawn-tagged chrs "
              "are absent from MSBs.")
        return 0


def render_json(result):
    print(json.dumps(result, indent=2))
    return 1 if result.get('misclassified') else 0


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--msb-dir',
        default=os.path.join(REPO_ROOT, 'vanilla_msbs'),
        help='Path to MSB directory (default: <repo>/vanilla_msbs)')
    p.add_argument('--verbose', action='store_true',
        help='Show full per-MSB breakdown for each misclassified chr.')
    p.add_argument('--json', action='store_true',
        help='Emit JSON for tooling consumption.')
    args = p.parse_args()

    result = audit(args.msb_dir, verbose=args.verbose)

    if args.json:
        return render_json(result)
    return render_text(result, verbose=args.verbose)


if __name__ == '__main__':
    sys.exit(main())
