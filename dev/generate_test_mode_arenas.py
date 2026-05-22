#!/usr/bin/env python3
"""generate_test_mode_arenas.py — emit minimal test-mode EMEVDs for ALL
vanilla NR expedition arenas (N1 + N2).

v0.25.9 — replaces v0.25.8's MMV-style template with direct extraction
of boss-init calls from vanilla.

See dev/extract_boss_init_calls.py for the design rationale (TL;DR:
copy vanilla's boss-init calls verbatim, strip the cinematic/dressing
events).

Output: dev/test_mode_arenas/<arena>.emevd.js + <arena>.emevd
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from typing import Optional


_HERE = os.path.dirname(os.path.abspath(__file__))
_EXTRACT_PATH = os.path.join(_HERE, 'extract_boss_init_calls.py')
spec = importlib.util.spec_from_file_location('extract_boss_init_calls', _EXTRACT_PATH)
_extract_mod = importlib.util.module_from_spec(spec)
sys.modules['extract_boss_init_calls'] = _extract_mod
spec.loader.exec_module(_extract_mod)

extract_calls = _extract_mod.extract_calls
emit_text = _extract_mod.emit_text
emit_binary = _extract_mod.emit_binary
ArenaEmevdSpec = _extract_mod.ArenaEmevdSpec


# v0.25.9 expedition-arena set. Each is an N1 or N2 arena across the
# eight Nightlord expedition paths.
#
# m47_70 (Augur descent) is OMITTED. Augur uses 17 single-arena events
# (90065000..016) for the 4-wave choreography. The wave logic is map-
# local rather than common_func, so our "preserve 9006xxxx calls"
# strategy doesn't fully capture it.
N1_N2_ARENAS = [
    'm48_20_00_00',
    'm48_40_00_00',
    'm48_50_00_00',
    'm48_60_00_00',
    'm48_70_00_00',
    'm48_80_00_00',
    'm48_90_00_00',
    'm49_10_00_00',
    'm49_17_00_00',
    'm49_18_00_00',
    'm49_19_00_00',
    'm49_20_00_00',
    'm49_21_00_00',
    'm49_23_00_00',
    'm49_25_00_00',
    'm49_26_00_00',
    'm49_27_00_00',
    'm49_28_00_00',
    'm49_29_00_00',
]


def generate_arena(arena_short: str, vanilla_emevd_dir: str,
                    out_dir: str) -> Optional[dict]:
    """Generate one arena's test-mode EMEVD. Returns inventory entry."""
    # DarkScript3 names its output based on the input filename. If you
    # decompiled `m49_25.emevd.dcx`, the .js is `m49_25.emevd.dcx.js`.
    # If you decompiled `m49_25.emevd` (already-decompressed), the .js
    # is `m49_25.emevd.js`. Try both.
    candidates = [
        os.path.join(vanilla_emevd_dir, f'{arena_short}.emevd.js'),
        os.path.join(vanilla_emevd_dir, f'{arena_short}.emevd.dcx.js'),
    ]
    vp = next((p for p in candidates if os.path.exists(p)), None)
    if vp is None:
        print(f'  {arena_short}: vanilla EMEVD not found at any of: '
              f'{candidates}')
        return None
    with open(vp) as f:
        vsrc = f.read()
    calls = extract_calls(vsrc)
    if not calls:
        print(f'  {arena_short}: 0 calls extracted — skipping')
        return None
    spec = ArenaEmevdSpec(map_short_name=arena_short, calls=calls)

    # Text emit (human review)
    txt_path = os.path.join(out_dir, f'{arena_short}.emevd.js')
    with open(txt_path, 'w') as f:
        f.write(emit_text(spec))

    # Binary emit (pipeline input)
    bin_path = os.path.join(out_dir, f'{arena_short}.emevd')
    try:
        raw = emit_binary(spec)
        with open(bin_path, 'wb') as f:
            f.write(raw)
    except Exception as e:
        print(f'  {arena_short}: binary emit failed ({e}); .emevd.js still written')
        return {
            'arena': arena_short,
            'n_calls': len(calls),
            'binary_failed': True,
        }

    event_ids = sorted(set(c.event_id for c in calls))
    return {
        'arena': arena_short,
        'n_calls': len(calls),
        'event_ids': event_ids,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vanilla-emevd-dir',
                     default='/home/claude/vanilla_emevd/vanilla_decompressed_emevd',
                     help='Directory containing vanilla NR .emevd.js files')
    ap.add_argument('--out-dir', default='dev/test_mode_arenas',
                     help='Output directory for generated EMEVDs')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # Clear stale files so the new batch is the single source of truth.
    for fn in os.listdir(args.out_dir):
        if fn.endswith('.emevd') or fn.endswith('.emevd.js'):
            os.remove(os.path.join(args.out_dir, fn))

    print(f'Generating {len(N1_N2_ARENAS)} N1/N2 minimal EMEVDs (v0.26.1)...')
    inventory = []
    n_ok = 0
    n_fail = 0
    for arena_short in N1_N2_ARENAS:
        try:
            result = generate_arena(arena_short, args.vanilla_emevd_dir, args.out_dir)
            if result:
                inventory.append(result)
                n_ok += 1
                if args.verbose:
                    print(f'  {arena_short}: {result["n_calls"]} calls, '
                          f'events={result.get("event_ids", "?")}')
            else:
                n_fail += 1
        except Exception as e:
            print(f'  {arena_short}: ERROR {e}')
            import traceback; traceback.print_exc()
            n_fail += 1

    print(f'\nResults: {n_ok} generated, {n_fail} failed/skipped')

    if n_ok:
        inv_path = os.path.join(args.out_dir, '_inventory.json')
        with open(inv_path, 'w') as f:
            json.dump({
                'version': 'v0.26.1',
                'strategy': 'extract-vanilla-strip-chr-disablers',
                'generated': inventory,
            }, f, indent=2)
        print(f'Inventory: {inv_path}')


if __name__ == '__main__':
    main()