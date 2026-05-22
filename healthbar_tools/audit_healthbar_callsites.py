#!/usr/bin/env python3
"""
audit_healthbar_callsites.py — Scan decompiled NR EMEVD .js files for boss-wake
handler call sites that drive on-screen healthbar nameIds.

NR's boss/miniboss healthbar lifecycle runs through a small family of common
events. Each one accepts one or more chrEntityIds plus one or more nameIds; the
nameId determines what text appears on the healthbar. After randomization the
chrEntityIds resolve to different chrs than vanilla intended, so the displayed
text desyncs from the actual enemy.

Several handlers also support SHARED healthbars (90015023, 90015026, 90015406)
where multiple chrEntityIds are bound to the same nameId — one bar, many chrs.
Vanilla uses this for encounters like Redmane Knight squads where N copies of
the same chr share an HP pool. After randomization, the same callsite can bind
N DIFFERENT chrs to a shared bar, exaggerating the desync. This tool surfaces
that structure so downstream rewriters can produce composite squad names.

USAGE:
  python audit_healthbar_callsites.py SCAN <emevd_js_dir> [--out callsites.json]

OUTPUT:
  A JSON manifest where each entry is one (event_id, name_group) instance:

    {
      "file": "m48_50_00_00.emevd.dcx.js",
      "line": 68,
      "event_id": 90015023,
      "name_group_index": 0,
      "name_id_arg_position": 5,
      "name_id_arg_value": 903251600,
      "chr_entity_id_arg_positions": [3, 4],
      "chr_entity_id_arg_values": [48505800, 48500800],
      "raw_call_args": [48500200, 40, 0, 48505800, 48500800, 903251600, ...],
      "is_shared_bar": true
    }

  A 90015023 call produces THREE such entries (one per name group). A 90015000
  call produces one. The rewriter consumes this manifest and rewrites the
  nameId arg at name_id_arg_position based on what the chrEntityIds swapped to.
"""

import argparse
import json
import os
import re
import sys


# Event ID -> list of name groups. Each group is (nameId_arg_pos, [chrEntityId_arg_pos, ...]).
# Argument positions are 0-indexed into the call's argument list AFTER the slot and
# event_id args have been stripped. Source: $Event() function signatures in
# common_func.emevd.dcx.js shipped with the rando.
#
# v0.24.x post-investigation: expanded from 6 entries to 28 after MMV's
# common_func.emevd revealed that ~40% of NR's healthbar-driving callsites
# use 9006x family handlers (dominantly 90065910 / 90065911 at 19-20 calls
# each × 3 slots each, accounting for most of the missed nameIds). The
# runtime byte-scan (healthbar_inplace/emevd.py: HEALTHBAR_HANDLER_SCHEMAS)
# uses the same dict — keep these two in sync.
#
# Original event signatures the first 6 schemas derive from:
# 90015000 (eventFlagId, chrEntityId, nameId, targetDistance, bgmBossConvParamId, eventFlagId2)
# 90015007 (eventFlagId, chrEntityId, areaEntityId, targetDistance, nameId, bgmBossConvParamId, eventFlagId2)
# 90015021 (eventFlagId, chrEntityId, nameId, targetDistance, bgmBossConvParamId, eventFlagId2, eventFlagId3)
# 90015023 (eventFlagId, targetDistance, eventFlagId2, chrEntityId, chrEntityId2, nameId,
#                                                     chrEntityId3, nameId2,
#                                                     chrEntityId4, nameId3)
# 90015026 (eventFlagId, targetDistance, eventFlagId2, chrEntityId, chrEntityId2, nameId)
# 90015406 (eventFlagId, chrEntityId, chrEntityId2, areaEntityId, targetDistance, nameId,
#                                                                  bgmBossConvParamId, eventFlagId2)
HEALTHBAR_EVENT_SCHEMAS = {
    # ── original 6 (chr_positions hand-tuned to be permissive: include
    # all chrs logically in the same fight, not just the ones in
    # explicit Display/Link calls). ──
    90015000: [(2, [1])],
    90015007: [(4, [1])],
    90015021: [(2, [1])],
    90015023: [(5, [3, 4]), (7, [6]), (9, [8])],
    90015026: [(5, [3, 4])],
    90015406: [(5, [1, 2])],

    # ── v0.24.x: 9006x family. Auto-derived from MMV's common_func.emevd
    # by parsing each event body for DisplayBossHealthBar(_, chr, _, name)
    # and LinkToBossHealthBar(_, name, chr) bindings. chr_positions
    # reflect exact bindings in those calls. ──
    90005870: [(1, [0])],
    90035219: [(3, [2])],
    90065050: [(6, [5]), (8, [7]), (10, [9])],
    90065120: [(4, [1])],
    90065121: [(7, [6]), (9, [8]), (11, [10])],
    90065122: [(4, [1])],
    90065123: [(4, [0, 1])],
    90065124: [(7, [5, 6]), (9, [8]), (11, [10])],
    90065125: [(4, [0, 1])],
    90065130: [(4, [1])],
    90065131: [(7, [6]), (9, [8]), (11, [10])],
    90065132: [(4, [1])],
    90065201: [(7, [6]), (9, [8])],
    90065202: [(5, [4]), (7, [6])],
    90065211: [(6, [3, 4])],
    90065220: [(6, [5])],
    90065221: [(6, [5]), (8, [7]), (10, [9])],
    90065222: [(5, [4]), (7, [6]), (9, [8])],
    90065254: [(7, [6])],
    90065910: [(7, [6]), (9, [8]), (11, [10])],
    90065911: [(5, [4]), (7, [6]), (9, [8])],
    90065912: [(7, [5])],
}


# Match $InitializeCommonEvent(slot, event_id, ...args). We do NOT care about the
# slot value; we use it to identify the call boundary. The body is a comma-separated
# arg list which may contain whitespace and trailing comments — we strip those.
_CALL_RE = re.compile(
    r'\$InitializeCommonEvent\s*\(\s*'   # opener
    r'(\d+)\s*,\s*'                      # slot
    r'(\d+)\s*'                          # event_id
    r'((?:,[^)]*)?)'                     # rest (may be empty)
    r'\)\s*;?',
    re.DOTALL
)


def _parse_arg_value(s):
    """Parse an EMEVD arg literal. Most are decimal ints; some are negative or hex.
    Anything that doesn't parse as an int (e.g. identifier references like
    Hero.Executor) is returned as the raw string. Healthbar args are always
    numeric in practice, but we don't want to crash on the unusual ones."""
    s = s.strip()
    if not s:
        return None
    try:
        if s.startswith('0x') or s.startswith('-0x'):
            return int(s, 16)
        return int(s)
    except ValueError:
        return s


def _split_args(args_blob):
    """Split the inside of a $InitializeCommonEvent(...) call into individual
    args. Naive comma-split is fine for the EMEVD output DSAS3 produces — args
    are literals, no nested calls, no string literals."""
    out = []
    for tok in args_blob.split(','):
        tok = tok.strip()
        if tok == '':
            continue
        out.append(_parse_arg_value(tok))
    return out


def scan_file(path):
    """Return a list of audit entries for one .js file."""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()

    # Pre-compute line offsets so we can report line numbers.
    line_starts = [0]
    for i, c in enumerate(text):
        if c == '\n':
            line_starts.append(i + 1)

    def offset_to_line(off):
        # Binary search would be faster but the files are small. Linear is fine.
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1  # 1-indexed

    fname = os.path.basename(path)
    entries = []
    for m in _CALL_RE.finditer(text):
        slot = int(m.group(1))
        event_id = int(m.group(2))
        if event_id not in HEALTHBAR_EVENT_SCHEMAS:
            continue
        rest = m.group(3).lstrip(', ')
        args = _split_args(rest)
        schema = HEALTHBAR_EVENT_SCHEMAS[event_id]
        line = offset_to_line(m.start())
        for grp_idx, (name_pos, chr_positions) in enumerate(schema):
            # Defensive: some maps may use degenerate forms with truncated args.
            # If the requested arg position is past the end of the call's args,
            # skip the group rather than crash — emit a warning to stderr.
            if name_pos >= len(args):
                sys.stderr.write(
                    f"  WARN: {fname}:{line} event {event_id} group {grp_idx} "
                    f"name_pos={name_pos} but only {len(args)} args; skipping group.\n"
                )
                continue
            # Some name groups may be unused (chrEntityId=0 → group not active).
            # We still emit them so the manifest is consistent with the schema,
            # but mark them inactive.
            chr_vals = []
            chr_pos_actual = []
            for cpos in chr_positions:
                if cpos < len(args):
                    chr_vals.append(args[cpos])
                    chr_pos_actual.append(cpos)
            active = any(isinstance(v, int) and v != 0 for v in chr_vals)
            entries.append({
                'file': fname,
                'line': line,
                'event_id': event_id,
                'name_group_index': grp_idx,
                'name_id_arg_position': name_pos,
                'name_id_arg_value': args[name_pos],
                'chr_entity_id_arg_positions': chr_pos_actual,
                'chr_entity_id_arg_values': chr_vals,
                'raw_call_args': args,
                'is_shared_bar': len(chr_pos_actual) > 1,
                'is_active': active,
            })
    return entries


def scan_dir(emevd_js_dir):
    """Walk a directory of .emevd.dcx.js files and return one combined entry list."""
    all_entries = []
    files_scanned = 0
    for root, _dirs, files in os.walk(emevd_js_dir):
        for fname in sorted(files):
            if not fname.endswith('.emevd.dcx.js'):
                continue
            full = os.path.join(root, fname)
            entries = scan_file(full)
            all_entries.extend(entries)
            files_scanned += 1
    return all_entries, files_scanned


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p_scan = sub.add_parser('SCAN', help='Scan a directory of .emevd.dcx.js files')
    p_scan.add_argument('emevd_js_dir')
    p_scan.add_argument('--out', default='callsites.json',
                        help='Output manifest path (default: callsites.json)')
    args = ap.parse_args()

    if args.cmd == 'SCAN':
        entries, n_files = scan_dir(args.emevd_js_dir)
        # Sort for deterministic output: by file, then line, then group index.
        entries.sort(key=lambda e: (e['file'], e['line'], e['name_group_index']))
        # Summary printed to stderr so the JSON on stdout (if redirected) is clean.
        sys.stderr.write(f"Scanned {n_files} .js files\n")
        sys.stderr.write(f"Total callsite-groups: {len(entries)}\n")
        active = sum(1 for e in entries if e['is_active'])
        sys.stderr.write(f"Active (non-zero chrEntityId): {active}\n")
        shared = sum(1 for e in entries if e['is_active'] and e['is_shared_bar'])
        sys.stderr.write(f"Shared-bar (multi-chr): {shared}\n")
        per_event = {}
        for e in entries:
            if not e['is_active']:
                continue
            per_event[e['event_id']] = per_event.get(e['event_id'], 0) + 1
        for ev, n in sorted(per_event.items()):
            sys.stderr.write(f"  event {ev}: {n} active\n")

        manifest = {
            '_schema': {ev: groups for ev, groups in HEALTHBAR_EVENT_SCHEMAS.items()},
            '_summary': {
                'files_scanned': n_files,
                'total_groups': len(entries),
                'active_groups': active,
                'shared_bar_groups': shared,
                'per_event_id': per_event,
            },
            'callsites': entries,
        }
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        sys.stderr.write(f"Wrote {args.out}\n")


if __name__ == '__main__':
    main()
