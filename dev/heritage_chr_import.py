#!/usr/bin/env python3
"""heritage_chr_import.py — copy chr/ files from a source game install (ER, SOTE,
DS3, etc.) into a me3 mod profile's chr/ folder.

Use case: NR ships a subset of chr files in its base chr/ folder. Heritage chrs
(ER/SOTE-extracted enemies that the rando may place) need their chrbnd / anibnd
/ behbnd / texbnd files physically present in the me3 profile to avoid CTD on
cell-load. This tool copies them from your unpacked ER install (or wherever)
without contaminating your vanilla NR install.

Typical workflow:
    # Find what's missing relative to your me3 profile (or your NR install)
    python dev/heritage_chr_import.py --target /path/to/me3-profile/chr \
        --diagnose-spoiler /path/to/_spoilers.json

    # Copy the needed chrs from your unpacked ER chr folder
    python dev/heritage_chr_import.py \
        --source /path/to/elden-ring-unpacked/chr \
        --target /path/to/me3-profile/chr \
        --prefixes c5040,c5080,c5081,c5870,c5900 \
        [--dry-run]

    # Or auto-derive prefixes from a spoiler file
    python dev/heritage_chr_import.py \
        --source /path/to/elden-ring-unpacked/chr \
        --target /path/to/me3-profile/chr \
        --from-spoiler /path/to/_spoilers.json

Conventions:
  Each chr's full asset set is its c-prefix glob: cXXXX*. This catches:
    cXXXX.chrbnd.dcx       — model + skeleton (REQUIRED)
    cXXXX.anibnd.dcx       — animation bundle (REQUIRED)
    cXXXX.behbnd.dcx       — behavior bundle (REQUIRED)
    cXXXX_h.texbnd.dcx     — high-res textures (recommended)
    cXXXX_l.texbnd.dcx     — low-res textures (recommended)
    cXXXX_aXX.anibnd.dcx   — additional animation banks
    cXXXX_divNN.anibnd.dcx — divisional animations (multi-phase bosses)

The tool copies every file matching cXXXX* for each requested c-prefix,
preserving the source's folder structure (flat — chr/ has no subdirs).

This tool does NOT convert chr files. ER chr files are loaded by NR directly
(same engine generation). If you need format conversion (e.g., DS3 → ER), use
the heritage_pack mod's conversion tooling first, then point --source at the
converted output.
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict


CHR_FILE_RE = re.compile(r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')
SCRIPT_FILE_RE = re.compile(r'^(\d{4})\d{2}_(battle|logic)\.luabnd(\.dcx)?$')


def cp_to_script_prefix(cp):
    """c5210 → '5210'. Script files use the 4-digit numeric prefix without
    the leading 'c' (filenames are like 521000_battle.luabnd.dcx).
    Returns None if cp doesn't look like a valid c-prefix."""
    return cp[1:5] if len(cp) >= 5 and cp.startswith('c') else None


def list_chr_prefixes(folder):
    """Return set of c-prefixes (e.g., 'c5040') with at least one .chrbnd.dcx in folder."""
    if not os.path.isdir(folder):
        return set()
    prefixes = set()
    for fname in os.listdir(folder):
        m = CHR_FILE_RE.match(fname)
        if m:
            prefixes.add(m.group(1))
    return prefixes


def list_files_for_prefix(folder, cp):
    """Return all filenames in folder that belong to chr `cp` (c-prefix)."""
    if not os.path.isdir(folder):
        return []
    out = []
    for fname in os.listdir(folder):
        m = CHR_FILE_RE.match(fname)
        if m and m.group(1) == cp:
            out.append(fname)
    return sorted(out)


def list_script_files_for_prefix(folder, cp):
    """Return all script filenames in folder for chr `cp`.

    Matches files like '521000_battle.luabnd.dcx' / '521000_logic.luabnd'
    for cp='c5210'. Returns sorted list, empty if folder absent or no
    matching scripts."""
    if not os.path.isdir(folder):
        return []
    prefix = cp_to_script_prefix(cp)
    if not prefix:
        return []
    out = []
    for fname in os.listdir(folder):
        m = SCRIPT_FILE_RE.match(fname)
        if m and m.group(1) == prefix:
            out.append(fname)
    return sorted(out)


def script_basename_for_compare(fname):
    """Normalize filename for present-in-target comparison: strip .dcx
    suffix so that source-side .luabnd and target-side .luabnd.dcx are
    treated as the same file."""
    return fname[:-4] if fname.endswith('.dcx') else fname


# v0.24.66: bulk dir-to-dir file copy for SFX + material auto-deploy.
#
# Cross-game chrs need their SFX bundles (sfxbnd_c<NNNN>.ffxbnd.dcx)
# and material files deployed to NR's mod folder, alongside chr files
# and scripts. v0.24.64 bundled aicommon resolves the AI-script
# manifest layer; this adds the visual-resource layer.
#
# Discovery: user playtest post-v0.24.64 reported that copying MMV's
# entire `sfx/` and `material/` directories made the full MMV roster
# work, including Romina (Saint of the Bud, SoTE final boss). User:
# "the ENTIRE MMV roster is back on the table".
#
# Unlike aicommon which is tiny (~140KB total) and bundled directly
# in the rando project, SFX and material directories are large
# (potentially gigabytes for the full MMV set). They're NOT bundled
# in the project — instead, the user points the chr-import GUI at
# MMV's source folder and chr-import copies what's there.
#
# Idempotent skip-existing means re-running the import is cheap: only
# new files get copied. First run is slow (full GB-scale transfer);
# subsequent runs are fast (file existence check + skip).
#
# We do a bulk dir-to-dir sync rather than per-chr matching because:
# 1. The user proved bulk works (per the v0.24.65 lift)
# 2. SFX dirs contain shared bundles (sfxbnd_commoneffects, dlc01_*)
#    not matchable by per-chr prefix — easier to copy everything
# 3. Material dirs don't use per-chr file naming consistently —
#    bulk is the only reliable approach

def copy_bulk_dir_files(source_dir, target_dir, ext_filter=None,
                         overwrite=False, dry_run=False):
    """Copy every file in source_dir to target_dir. Optional extension
    filter (case-insensitive). Idempotent skip-existing.

    Args:
        source_dir: source directory path
        target_dir: target directory path
        ext_filter: optional iterable of file extensions to include.
                    e.g. ('.ffxbnd.dcx',) to copy only SFX bundles.
                    None = copy all regular files.
                    Matching is case-insensitive against filename suffix.
        overwrite: if True, replace existing target files; if False, skip
        dry_run: if True, log but don't actually copy

    Returns:
        dict with keys:
          'copied':  list[str] of filenames written (or would-be in dry_run)
          'skipped': list[str] of filenames skipped (already in target)
          'bytes':   total byte count of copied files
          'errors':  list[str] of error messages (per-file failures)

    Missing source_dir returns empty results — caller can treat as
    "no SFX/material to deploy from this source".
    """
    result = {'copied': [], 'skipped': [], 'bytes': 0, 'errors': []}
    if not source_dir or not os.path.isdir(source_dir):
        return result
    if not dry_run:
        os.makedirs(target_dir, exist_ok=True)
    # Normalize ext_filter for case-insensitive matching
    if ext_filter is not None:
        ext_filter_lower = tuple(e.lower() for e in ext_filter)
    else:
        ext_filter_lower = None
    for fname in sorted(os.listdir(source_dir)):
        src = os.path.join(source_dir, fname)
        if not os.path.isfile(src):
            # Skip subdirectories — we don't recurse. If MMV ships
            # nested SFX/material structures, this would need recursion.
            # Conservative: flat dir copy only.
            continue
        if ext_filter_lower is not None:
            fname_lower = fname.lower()
            if not any(fname_lower.endswith(e) for e in ext_filter_lower):
                continue
        dst = os.path.join(target_dir, fname)
        if os.path.exists(dst) and not overwrite:
            result['skipped'].append(fname)
            continue
        try:
            sz = os.path.getsize(src)
        except OSError as e:
            result['errors'].append(f'{fname}: stat failed: {e}')
            continue
        if not dry_run:
            try:
                import shutil
                shutil.copy2(src, dst)
            except OSError as e:
                result['errors'].append(f'{fname}: copy failed: {e}')
                continue
        result['copied'].append(fname)
        result['bytes'] += sz
    return result


def required_prefixes_from_spoiler(spoiler_path):
    """Return set of c-prefixes that LANDED as targets in the spoiler. Caller can
    diff against target dir to find what's missing."""
    with open(spoiler_path, encoding='utf-8') as f:
        data = json.load(f)
    return {e['new']['c_prefix'] for e in data.get('entries', [])}


# v0.24.64: bundled aicommon distribution.
#
# MMV's `aicommon.luabnd.dcx` and `aicommon_dlc01.luabnd.dcx` are
# strict supersets of NR's vanilla aicommon (every NR-defined goal-ID
# name is present with the same value; verified by 3-way diff across
# ER + NR + MMV — 922 names shared by all three, 0 value conflicts).
#
# Cross-game and DLC chrs (c8300 DSA, c8500 Manus, c5230, c5210, etc.)
# register goals using constants defined only in aicommon_dlc01. If
# the player lacks SoTE installed, the game doesn't load its own
# aicommon_dlc01, the constants resolve to nil, RegisterTableGoal
# silently no-ops, and the chr spawns with no goal table → freeze.
#
# Bundling MMV's versions in the rando project (under bundled_aicommon/)
# and shipping them as part of every chr-import sidesteps the DLC
# install requirement and resolves the freeze for any cross-game chr
# the rando might place.
#
# Discovery: user playtest seed 618106 (v0.24.62) — c8300 Dragonslayer
# Armor froze at m49_29 NB1-duo slot. Decompiled MMV scripts revealed
# 830000_battle.luabnd's RegisterTableGoal references
# GOAL_DragonGuardianKnight_316000, defined only in
# aicommon_dlc01.luabnd. Same root cause for the "Roundtable error
# without DLC" report. Deploying MMV's aicommon files resolved both.

AICOMMON_FILE_RE = re.compile(r'^aicommon(?:_dlc\d+)?\.luabnd(\.dcx)?$')


def list_bundled_aicommon_files(bundle_dir):
    """Return sorted list of (filename, fullpath) tuples for every
    aicommon*.luabnd(.dcx)? file in bundle_dir. Empty list if
    bundle_dir is None or doesn't exist."""
    if not bundle_dir or not os.path.isdir(bundle_dir):
        return []
    out = []
    for fname in sorted(os.listdir(bundle_dir)):
        if AICOMMON_FILE_RE.match(fname):
            out.append((fname, os.path.join(bundle_dir, fname)))
    return out


def copy_bundled_aicommon(bundle_dir, target_script_dir,
                          overwrite=False, dry_run=False):
    """Copy every aicommon*.luabnd(.dcx)? in bundle_dir into
    target_script_dir.

    Returns a dict with keys:
      'copied':  list[str] of filenames written (or would-be-written if dry_run)
      'skipped': list[str] of filenames skipped because target already had them
                 and overwrite=False
      'bytes':   total byte count of copied files (not counting skipped)

    If bundle_dir is missing or empty, returns empty results — caller
    can treat as "no bundled scripts available, fall back to vanilla."

    The copy uses shutil.copy2 to preserve mtime/perms, matching the
    behavior of the per-chr script copy in _chr_import."""
    result = {'copied': [], 'skipped': [], 'bytes': 0}
    files = list_bundled_aicommon_files(bundle_dir)
    if not files:
        return result
    if not dry_run:
        os.makedirs(target_script_dir, exist_ok=True)
    # Pre-index target for present-check (normalized basename so
    # source .luabnd and target .luabnd.dcx are treated as same file,
    # matching script_basename_for_compare).
    target_basenames = set()
    if os.path.isdir(target_script_dir):
        for tfn in os.listdir(target_script_dir):
            target_basenames.add(script_basename_for_compare(tfn))
    for fname, src in files:
        dst = os.path.join(target_script_dir, fname)
        base = script_basename_for_compare(fname)
        try:
            sz = os.path.getsize(src)
        except OSError:
            continue
        if base in target_basenames and not overwrite:
            result['skipped'].append(fname)
            continue
        if not dry_run:
            import shutil
            shutil.copy2(src, dst)
        result['copied'].append(fname)
        result['bytes'] += sz
    return result


def main():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                  description=__doc__)
    ap.add_argument('--source', help="Source chr/ folder (e.g., unpacked ER chr/).")
    ap.add_argument('--target', required=True,
                     help="Target chr/ folder (typically your me3 profile's chr/).")
    ap.add_argument('--regulation',
                     help="Path to NpcParam.csv (dumped from regulation.bin). When given, "
                          "anim-carrier detection reads RetargetReferenceChrId authoritatively, "
                          "catching cross-family retargets (c5701->c4100) and same-family ones "
                          "(c5661->c5660) that the filename heuristic misses. STRONGLY recommended: "
                          "without it the importer falls back to the c[:-1] family guess and can "
                          "silently drop an anim source, T-posing the dependent in-game.")
    ap.add_argument('--prefixes', help="Comma-separated c-prefixes to copy (e.g., c5040,c5080).")
    ap.add_argument('--from-spoiler',
                     help="Auto-derive needed prefixes from this spoiler JSON (target c-prefixes "
                          "minus what target already has).")
    ap.add_argument('--diagnose-spoiler',
                     help="Print which spoiler-required prefixes are missing from target. "
                          "No copy. (Use without --source to plan ahead.)")
    ap.add_argument('--dry-run', action='store_true',
                     help="List what would be copied, don't actually copy.")
    ap.add_argument('--overwrite', action='store_true',
                     help="Overwrite files that already exist in target. Default: skip.")
    args = ap.parse_args()

    # Diagnose-only mode: report missing prefixes against a spoiler
    if args.diagnose_spoiler:
        required = required_prefixes_from_spoiler(args.diagnose_spoiler)
        target_have = list_chr_prefixes(args.target)
        missing = sorted(required - target_have)
        print(f"Spoiler requires {len(required)} distinct c-prefixes as placement targets")
        print(f"Target has {len(target_have)} c-prefixes")
        print(f"Missing from target: {len(missing)}")
        if missing:
            print("\nMissing c-prefixes:")
            for cp in missing:
                print(f"  {cp}")
        return 0

    # Real copy modes need source
    if not args.source:
        ap.error("--source is required unless using --diagnose-spoiler")
    if not os.path.isdir(args.source):
        ap.error(f"Source folder doesn't exist: {args.source}")

    # Determine prefix list
    if args.from_spoiler:
        required = required_prefixes_from_spoiler(args.from_spoiler)
        target_have = list_chr_prefixes(args.target)
        prefixes = sorted(required - target_have)
        print(f"Auto-derived from spoiler: {len(prefixes)} c-prefix(es) missing from target")
    elif args.prefixes:
        prefixes = sorted(p.strip() for p in args.prefixes.split(',') if p.strip())
    else:
        ap.error("Specify either --prefixes or --from-spoiler")

    if not prefixes:
        print("Nothing to copy — target already has everything.")
        return 0

    # Verify each requested prefix is in source
    source_have = list_chr_prefixes(args.source)
    in_source = [p for p in prefixes if p in source_have]
    not_in_source = [p for p in prefixes if p not in source_have]

    if not_in_source:
        print(f"\n⚠ {len(not_in_source)} c-prefix(es) NOT FOUND in source — may need a different source game:")
        for cp in not_in_source:
            print(f"    {cp}")
        print()

    if not in_source:
        print("No requested prefixes found in source. Aborting.")
        return 1

    # Anim-carrier expansion. A dependent chr (e.g. c5661 Shadow Militia)
    # whose animations live in a separate carrier bundle (c5660) T-poses
    # unless that carrier's anibnd-class files ship alongside it. With
    # --regulation, carriers are read from RetargetReferenceChrId (catches
    # cross-family retargets); without it, a filename-family heuristic is
    # used (same-family only — can miss sources and T-pose the dependent).
    from chr_asset_resolver import build_carrier_map  # noqa: E402
    if args.regulation and os.path.isfile(args.regulation):
        carrier_map = build_carrier_map(args.source, regulation_csv=args.regulation)
        print(f"  anim-carrier detection: authoritative (RetargetReferenceChrId "
              f"from {os.path.basename(args.regulation)})")
    else:
        carrier_map = build_carrier_map(args.source)
        print("  ⚠ anim-carrier detection: filename-heuristic fallback "
              "(no --regulation). Cross-family retargets may be missed; "
              "pass --regulation NpcParam.csv to catch all anim sources.")
    carrier_adds = {}      # carrier prefix -> [dependents needing it]
    carrier_missing = {}   # dependent -> carrier prefix absent from source
    for cp in list(in_source):
        dep = carrier_map.get(cp)
        if not dep:
            continue
        carrier = dep["carrier"]
        if carrier in source_have:
            carrier_adds.setdefault(carrier, []).append(cp)
        else:
            carrier_missing[cp] = carrier
    for carrier in sorted(carrier_adds):
        if carrier not in in_source:
            in_source.append(carrier)
        print(f"  + anim carrier {carrier} (needed by "
              f"{', '.join(sorted(carrier_adds[carrier]))})")
    if carrier_missing:
        print(f"\n⚠ {len(carrier_missing)} dependent(s) need an anim "
              f"carrier NOT in source — import is INCOMPLETE, these will "
              f"T-pose in-game:")
        for cp, carrier in sorted(carrier_missing.items()):
            print(f"    {cp} needs carrier {carrier}")
        print()

    # Make target if needed
    if not args.dry_run:
        os.makedirs(args.target, exist_ok=True)

    # Copy files
    copied = 0
    skipped_exists = 0
    total_bytes = 0
    print(f"\nCopying {len(in_source)} c-prefix(es) from {args.source} → {args.target}\n")
    for cp in in_source:
        files = list_files_for_prefix(args.source, cp)
        if not files:
            print(f"  ⚠ {cp}: no matching files (despite chrbnd presence — odd)")
            continue
        print(f"  {cp}: {len(files)} files")
        for fname in files:
            src = os.path.join(args.source, fname)
            dst = os.path.join(args.target, fname)
            sz = os.path.getsize(src)
            total_bytes += sz
            if os.path.exists(dst) and not args.overwrite:
                print(f"    skip (exists): {fname} ({sz/(1024*1024):.1f} MB)")
                skipped_exists += 1
                continue
            if args.dry_run:
                print(f"    would copy: {fname} ({sz/(1024*1024):.1f} MB)")
            else:
                shutil.copy2(src, dst)
                print(f"    copied: {fname} ({sz/(1024*1024):.1f} MB)")
            copied += 1

    print(f"\nDone. {copied} file(s) copied, {skipped_exists} skipped (already present).")
    print(f"Total size: {total_bytes/(1024*1024):.1f} MB")
    if not_in_source:
        print(f"\n{len(not_in_source)} prefix(es) still missing — try a different source game.")
    return 0


if __name__ == '__main__':
    sys.exit(main())