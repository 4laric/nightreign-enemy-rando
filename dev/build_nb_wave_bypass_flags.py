#!/usr/bin/env python3
"""
build_nb_wave_bypass_flags.py — Generate data/nb_wave_bypass_flags.json by
scanning vanilla NR EMEVD .js files for the $Event(XXXX2810) pattern.

Each Night Boss arena has an $Event(XXXX2810) handler that gates the preboss
wave / boss spawn on `WaitFor(EventFlag(eventFlagId3))`. The eventFlagId3 value
is supplied via a parameter substitution mechanism we can't statically recover
(XXXX2810 is never explicitly $InitializeEvent'd anywhere — see emevd_patch.py
nb_wave_bypass docstring for the full diagnosis). So the nb_wave_bypass patch
introduces NEW per-arena bypass flags and OR's them into the existing WaitFor
predicate, taking control of the gate ourselves.

This script picks the bypass + guard flags for each NB arena from the per-arena
private flag range (XXX0290 + XXX0291, picked because the XXX029X slot is
empirically unused in every NB arena). It writes the picks to
data/nb_wave_bypass_flags.json which emevd_patch.py loads at patch time.

Usage:
    python dev/build_nb_wave_bypass_flags.py <vanilla_js_dir>

Outputs:
    data/nb_wave_bypass_flags.json  (written relative to repo root)

Re-run when:
    - NR is patched and the per-arena flag layout changes
    - The XXX029X assumption needs to be revalidated (the script asserts the
      slot is empty in every scanned arena and aborts with a clear error if
      not — so a stale data file is impossible to ship silently)
"""
import argparse
import json
import os
import re
import sys


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def discover_nb_arenas(vanilla_dir):
    """Scan vanilla EMEVD JS dir for NB arena files that have an $Event(XXXX2810)
    handler containing WaitFor(EventFlag(eventFlagId3)). Returns a list of
    (filename_stem, event_id) tuples sorted by filename."""
    out = []
    for fname in sorted(os.listdir(vanilla_dir)):
        if not (fname.startswith('m48_') or fname.startswith('m49_')):
            continue
        if not fname.endswith('.emevd.js'):
            continue
        c = _read(os.path.join(vanilla_dir, fname))
        m = re.search(
            r'\$Event\((\d+2810),.*?WaitFor\(EventFlag\(eventFlagId3?\)\);',
            c, re.DOTALL)
        if not m:
            continue  # not all m48/m49 files have an XXXX2810 (m49_40/42 don't)
        # Stem: strip the .emevd.js suffix
        stem = fname[:-len('.emevd.js')]
        out.append((stem, int(m.group(1))))
    return out


def derive_prefix(stem):
    """m48_00_00_00 → 48000   (5-digit per-arena prefix used as flag-ID basis)"""
    m = re.match(r'm(\d{2})_(\d{2})_', stem)
    if not m:
        raise ValueError(f'unrecognized map stem: {stem!r}')
    return int(f'{m.group(1)}{m.group(2)}0')


def assert_slot_free(stem, vanilla_dir, base_flag):
    """Sanity check: the XXX0290-0299 slot must be unused in this arena's
    vanilla .js. If it isn't, the picker rule is wrong for this arena and the
    user needs to manually pick alternative flags."""
    c = _read(os.path.join(vanilla_dir, f'{stem}.emevd.js'))
    all_ints = set(int(x) for x in re.findall(r'\b\d{6,9}\b', c))
    collisions = sorted(n for n in all_ints if base_flag + 290 <= n <= base_flag + 299)
    if collisions:
        raise RuntimeError(
            f'{stem}: XXX029X slot is not free — found {collisions} in vanilla. '
            f'The picker rule (bypass=prefix*1000+290, guard=prefix*1000+291) '
            f'needs a per-arena override for this map.')


def build_arenas_map(vanilla_dir):
    arenas = {}
    for stem, event_id in discover_nb_arenas(vanilla_dir):
        prefix = derive_prefix(stem)
        base = prefix * 1000
        assert_slot_free(stem, vanilla_dir, base)
        arenas[stem] = {
            'event_id': event_id,
            'bypass_flag': base + 290,
            'guard_flag': base + 291,
        }
    return arenas


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('vanilla_dir', help='Directory containing vanilla .emevd.js files')
    p.add_argument('--output', default=None,
                   help='Output path (default: data/nb_wave_bypass_flags.json relative to repo root)')
    args = p.parse_args()

    if not os.path.isdir(args.vanilla_dir):
        print(f'ERROR: vanilla_dir does not exist: {args.vanilla_dir}', file=sys.stderr)
        sys.exit(1)

    arenas = build_arenas_map(args.vanilla_dir)
    if not arenas:
        print('ERROR: no NB arenas with XXXX2810 + WaitFor(eventFlagId3) found.', file=sys.stderr)
        print('Check that vanilla_dir contains decompiled .emevd.js files.', file=sys.stderr)
        sys.exit(1)

    output = {
        '_meta': {
            'schema_version': 1,
            'since_version': 'v0.24.105',
            'purpose': (
                'Per-NB-arena bypass + guard flag picks for the nb_wave_bypass '
                'patch. Each entry maps a per-map .emevd file stem to (a) the '
                'XXXX2810 event ID where the WaitFor gate lives, (b) the '
                'bypass_flag that gets OR-injected into that WaitFor, and (c) '
                'the guard_flag used by common_func event 99055100 for '
                'idempotency.'),
            'picker_rule': (
                'bypass = prefix*1000+290, guard = prefix*1000+291, where '
                'prefix is the 5-digit per-arena ID (m48_00 → 48000, '
                'm49_29 → 49290). The XXX029X slot is empirically unused in '
                'every scanned NB arena; assert_slot_free() verifies this at '
                'build time so a stale file is impossible to ship.'),
            'generator': 'dev/build_nb_wave_bypass_flags.py',
            'arena_count': len(arenas),
        },
        'arenas': arenas,
    }

    if args.output:
        out_path = args.output
    else:
        # Default: data/nb_wave_bypass_flags.json relative to repo root
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out_path = os.path.join(repo_root, 'data', 'nb_wave_bypass_flags.json')

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    print(f'Wrote {out_path} ({len(arenas)} arenas)')


if __name__ == '__main__':
    main()
