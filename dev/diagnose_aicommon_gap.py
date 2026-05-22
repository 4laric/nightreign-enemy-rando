#!/usr/bin/env python3
"""diagnose_aicommon_gap.py — find which aicommon helpers a heritage chr's
battle script needs that the currently-loaded aicommon is missing.

Background
----------

import_heritage_ai_scripts.py only handles the per-chr layer of the
heritage AI fix (NNNNNN_battle.luabnd.dcx). The other layer is the
shared library, `aicommon.luabnd.dcx`. ER's aicommon ships ~169
helper Lua scripts; vanilla NR's ships ~118, and MMV's ships ~120.
Heritage chrs imported from ER may `require()` helpers that exist in
ER's aicommon but not in whatever aicommon the mod profile is loading.
The chr loads, its per-chr battle script tries to `require()` a
missing helper, the load silently fails, and the chr drops to "behbnd
only" — animations work but combat AI doesn't engage.

Symptom: chr spawns but stands idle / doesn't aggro / pack-coordination
absent. Same shape as the bug fixed for Dancing Lion in v0.23.72-late
by importing 521000_battle.luabnd, except here the unmet dependency is
deeper in the script call chain.

What this script does
---------------------

1. Read ER's aicommon.luabnd.dcx (BND4 archive of .lua files).
2. Read the mod profile's aicommon.luabnd.dcx (same).
3. List files in ER not in the mod.
4. For a target chr's per-chr battle script (e.g. 519000_battle.luabnd
   for Spider Scorpion), unpack it and grep every `.lua` file inside
   for `require()` calls.
5. Cross-reference: which `require`d files exist in ER but NOT in the
   mod's aicommon? Those are the broken deps.

Usage
-----

  python3 dev/diagnose_aicommon_gap.py \\
      --er-aicommon  /path/to/unpacked/ER/script/aicommon.luabnd.dcx \\
      --mod-aicommon /path/to/heritage_pack/script/aicommon.luabnd.dcx \\
      --chr-script   /path/to/heritage_pack/script/519000_battle.luabnd.dcx

Outputs (printed):
  - Total file counts in each aicommon
  - Files in ER aicommon not in mod aicommon (the "delta")
  - `require()` calls in the chr battle script
  - Cross-ref: chr requires that resolve in ER but NOT in mod (the gap)

If the gap is empty, the AI breakage is NOT an aicommon issue and we
need to look elsewhere (NpcParam.ThinkParamId, behbnd, etc).
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import tempfile

# Import the existing BND4 reader from the same project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bnd4 import read_bnd4


def _maybe_dcx_inflate(path: str) -> bytes:
    """Read a .dcx-compressed file and return the inflated payload.

    NR's .dcx wraps content with an Oodle layer. We don't ship an Oodle
    decompressor here, so we fall back to: try reading as plain BND4
    first (some .dcx files are misnamed and already uncompressed). If
    that fails, ask the user to pre-decompress.
    """
    with open(path, 'rb') as f:
        head = f.read(4)
    if head == b'BND4':
        # Misnamed .dcx, already a BND4
        with open(path, 'rb') as f:
            return f.read()
    if head == b'DCX\0':
        # True DCX wrapper. We don't have an Oodle decompressor; ask
        # the user to pre-decompress with WitchyBND or UXM.
        raise RuntimeError(
            f"{path} is .dcx-compressed (DCX magic detected).\n"
            f"Pre-decompress it with WitchyBND ('WitchyBND <file>' produces\n"
            f"a <file>.unpacked/ dir with raw .luabnd inside) or use\n"
            f"`dcx.py` from this project if it has decompress support.\n"
            f"Then pass the uncompressed .luabnd path to this script."
        )
    raise RuntimeError(f"{path}: unrecognized magic bytes {head!r}")


def _list_bnd4_files(path: str) -> list[str]:
    """Return the list of embedded filenames in a BND4 archive."""
    # Some BND4 files end in .dcx but are already inflated; handle both
    raw = _maybe_dcx_inflate(path)
    # Write to a temp file so read_bnd4 (which opens by path) works
    with tempfile.NamedTemporaryFile(suffix='.bnd4', delete=False) as tf:
        tf.write(raw)
        tmppath = tf.name
    try:
        results = read_bnd4(tmppath)
    finally:
        os.unlink(tmppath)
    return [name for name, _ in results]


def _extract_bnd4_payloads(path: str) -> dict[str, bytes]:
    """Return {filename: bytes_content} for every embedded file."""
    raw = _maybe_dcx_inflate(path)
    with tempfile.NamedTemporaryFile(suffix='.bnd4', delete=False) as tf:
        tf.write(raw)
        tmppath = tf.name
    try:
        return {name: payload for name, payload in read_bnd4(tmppath)}
    finally:
        os.unlink(tmppath)


_REQUIRE_RE = re.compile(rb'\brequire\s*[(\s]\s*["\']([^"\']+)["\']')


def _find_requires(lua_bytes: bytes) -> list[str]:
    """Return all `require("name")` strings in a Lua source/bytecode blob.

    Works for both source-form .lua (literal strings) and compiled
    luac (the names still appear as literal string-table entries).
    """
    return sorted(set(m.group(1).decode('utf-8', errors='replace')
                      for m in _REQUIRE_RE.finditer(lua_bytes)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--er-aicommon', required=True,
                    help="Path to ER's unpacked aicommon.luabnd (or .dcx if pre-decompressed)")
    ap.add_argument('--mod-aicommon', required=True,
                    help="Path to the mod profile's aicommon.luabnd that me3 currently loads")
    ap.add_argument('--chr-script', required=True,
                    help="Path to the per-chr battle script being diagnosed (e.g. 519000_battle.luabnd.dcx)")
    args = ap.parse_args()

    print(f"== AI common diagnosis ==")
    print(f"ER aicommon:   {args.er_aicommon}")
    print(f"Mod aicommon:  {args.mod_aicommon}")
    print(f"Chr script:    {args.chr_script}")
    print()

    er_files = set(_list_bnd4_files(args.er_aicommon))
    mod_files = set(_list_bnd4_files(args.mod_aicommon))
    print(f"ER aicommon files:   {len(er_files)}")
    print(f"Mod aicommon files:  {len(mod_files)}")
    delta = er_files - mod_files
    print(f"In ER, not in mod:   {len(delta)} files")
    if delta:
        print(f"  Sample delta entries:")
        for f in sorted(delta)[:20]:
            print(f"    {f}")
        if len(delta) > 20:
            print(f"    ... and {len(delta) - 20} more")
    print()

    # Open chr script, find requires across every embedded .lua
    print(f"== Chr script require() analysis ==")
    chr_payloads = _extract_bnd4_payloads(args.chr_script)
    print(f"Chr script contains {len(chr_payloads)} embedded files:")
    for fname in sorted(chr_payloads):
        print(f"  {fname}")

    all_requires = set()
    for fname, payload in chr_payloads.items():
        if fname.endswith('.lua') or fname.endswith('.luab'):
            rs = _find_requires(payload)
            for r in rs:
                all_requires.add(r)

    print(f"\nTotal distinct require() targets: {len(all_requires)}")
    for r in sorted(all_requires):
        print(f"  require '{r}'")

    # Cross-reference: which requires aren't satisfied by mod aicommon?
    # require name typically matches a file like 'X' → X.lua in aicommon
    print(f"\n== Unsatisfied requires (the actual breakage list) ==")
    mod_basenames = {os.path.splitext(os.path.basename(f))[0] for f in mod_files}
    er_basenames  = {os.path.splitext(os.path.basename(f))[0] for f in er_files}
    unsatisfied_by_mod = []
    satisfied_by_er = []
    truly_missing = []
    for r in sorted(all_requires):
        # Some require strings are dotted (e.g. 'common.helpers') — map
        # to expected basename
        candidate = r.rsplit('.', 1)[-1]
        in_mod = candidate in mod_basenames
        in_er = candidate in er_basenames
        if in_mod:
            continue  # already satisfied
        unsatisfied_by_mod.append((r, candidate))
        if in_er:
            satisfied_by_er.append((r, candidate))
        else:
            truly_missing.append((r, candidate))

    print(f"  Requires NOT satisfied by mod's aicommon: {len(unsatisfied_by_mod)}")
    print(f"  Of those, satisfiable by importing from ER:  {len(satisfied_by_er)}")
    print(f"  Truly missing (not even in ER):              {len(truly_missing)}")
    if satisfied_by_er:
        print(f"\n  → THESE FILES NEED TO BE COPIED FROM ER aicommon → mod aicommon:")
        for r, candidate in satisfied_by_er:
            print(f"      {candidate}.lua    (required as '{r}')")
    if truly_missing:
        print(f"\n  Files required but missing from ER too (these are weird):")
        for r, candidate in truly_missing:
            print(f"      {candidate}  (required as '{r}')")
    if not unsatisfied_by_mod:
        print(f"  No unsatisfied requires! The AI breakage is NOT in the aicommon layer.")
        print(f"  Look elsewhere: NpcParam.ThinkParamId, behbnd .hkt files, chrbnd .anibnd.")


if __name__ == '__main__':
    main()
