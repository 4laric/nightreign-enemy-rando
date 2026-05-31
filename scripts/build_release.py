#!/usr/bin/env python3
"""
build_release.py — package the rando into a publishable zip bundle.

Stages every file the rando needs at runtime into a clean output
directory, strips dev-only / user-specific / cache content, then
optionally zips the result with a versioned name.

Usage:
    python3 scripts/build_release.py                    # full bundle → build/release_<version>.zip
    python3 scripts/build_release.py --no-zip           # stage only
    python3 scripts/build_release.py --out-dir /tmp/x   # custom staging location
    python3 scripts/build_release.py --name custom.zip  # custom archive name

The script is intentionally manifest-driven (INCLUDE_FILES,
INCLUDE_DIRS, EXCLUDE_PATTERNS) so future shape changes (a new
top-level dir, a renamed module, etc.) are one edit not a code rewrite.
"""
import argparse
import fnmatch
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


# ---------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------
# Each entry is a path relative to the repo root. Keep this list small
# and explicit — the cost of forgetting a file is "runtime crashes on
# a user's machine," and the cost of including an extra is "a few KB."

# Top-level Python files that ship.
INCLUDE_FILES = [
    # Runtime entry points
    'oops_rando_gui.py',
    'oops_rando_gui.pyw',   # v0.26.5: Windows double-click launcher (pythonw, no console)
    # v0.27.0: Launch.bat removed from the manifest — Nexus flags bundled
    # .bat files (auto-run / executable-content warnings), so it is no
    # longer shipped. oops_rando_gui.pyw is the Windows double-click path.
    'check_setup.py',
    # Engine + core
    'oops_v3.py',
    'oops_all_anyone.py',
    'swap_compat.py',
    # Archive reader (v0.28.0: read vanilla data straight from a packed
    # install — no UXM unpack). The GUI's _maybe_prefetch_vanilla imports
    # vanilla_source; the heritage dev tools import er_source. Both chain
    # through data_archive -> aes128 and read the JSON manifests, so EVERY
    # one of these must ship or the feature crashes on a user's machine.
    'aes128.py',
    'data_archive.py',
    'nr_keys.py',
    'nr_vanilla_manifest.json',
    'vanilla_source.py',
    'er_keys.py',
    'er_source.py',
    'er_chr_manifest.json',
    # Pipeline modules
    'dcx.py',
    'dcx_batch.py',
    'emevd_patch.py',
    'rewrite_walk_routes.py',
    # Auxiliary / debug tools that users might invoke
    'check_patched_deep.py',
    'diff_vanilla_vs_patched.py',
    'dump_vanilla_fmg.py',
    # Documentation
    'README.md',
    'INSTALL.md',
    'CHANGELOG.md',
    'PATCH_NOTES.md',
    'SHIP_NOTES.md',
    'LICENSE',
]

# Whole directories that ship.
INCLUDE_DIRS = [
    'data',              # JSON catalogs the engine reads at load
    'engine',            # pack_loaders + runtime helpers
    'docs',              # user-facing documentation
    'bundled_aicommon',  # GUI references this for heritage chr import
    'patched_emevd',     # GUI's "Install pre-patched EMEVD" button source
    'healthbar_tools',   # used by dcx_batch
    'healthbar_inplace', # used by check_patched_deep / dcx_batch
]

# Specific files from dev/ that runtime code imports. dev/ as a whole
# is excluded (it's audits + experiments + scratch); only these
# explicit picks are pulled.
INCLUDE_FROM_DEV = [
    'dev/install_discovery.py',     # Steam/game/Oodle/me3 auto-detect
    'dev/heritage_chr_import.py',   # chr-asset import flow (imports er_source)
    'dev/import_heritage_ai_scripts.py',  # AI-script import (imports er_source)
]

# Directories included if present, silently skipped if missing.
# vanilla_msbs/ is the big one — Alaric populates it at release time
# from a vanilla NR install. If absent, the bundle still ships but
# users have to point at their own NR install.
OPTIONAL_DIRS = [
    'vanilla_msbs',
]

# Glob patterns matched against any path component during staging.
# A file is excluded if ANY of its path components matches ANY pattern.
EXCLUDE_PATTERNS = [
    # Python cache + bytecode
    '__pycache__',
    '*.pyc',
    '*.pyo',
    # Test directories — nested ones (e.g. healthbar_inplace/tests/)
    # would otherwise leak into the bundle even though the top-level
    # tests/ dir isn't in INCLUDE_DIRS. Catching the name at any
    # nesting keeps the bundle user-facing only.
    'tests',
    # Editor / OS noise
    '.DS_Store',
    'Thumbs.db',
    '*.swp',
    '*.swo',
    '*~',
    # Backups / temp
    '*.bak',
    '*.tmp',
    # User-specific GUI state
    '.4laric_*.json',
    # Oodle (user provides per NR install — should never ship)
    'oo2core_*.dll',
    # Generated dumps
    'vanilla_npcname_dump.txt',
]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def read_engine_version(repo_root):
    """Extract V3_ENGINE_FINGERPRINT from oops_v3.py — used to name
    the zip. Falls back to a timestamp if the constant isn't found."""
    path = os.path.join(repo_root, 'oops_v3.py')
    try:
        with open(path) as f:
            for line in f:
                m = re.search(r"V3_ENGINE_FINGERPRINT\s*=\s*['\"]([^'\"]+)['\"]",
                              line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return datetime.now(timezone.utc).strftime('%Y%m%d')


def matches_exclude(path, patterns=EXCLUDE_PATTERNS):
    """Return True if any path component matches any exclude pattern.
    Uses fnmatch (shell-style globs)."""
    parts = path.replace('\\', '/').split('/')
    for part in parts:
        for pattern in patterns:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def copy_file(src, dst, *, dry_run=False):
    """Copy src → dst, creating parent dirs as needed. Skips silently
    if src doesn't exist (caller's problem; we log it)."""
    if not os.path.isfile(src):
        return False
    if dry_run:
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def copy_tree(src_dir, dst_dir, *, dry_run=False):
    """Recursively copy src_dir → dst_dir, applying EXCLUDE_PATTERNS
    at every step. Returns (n_copied, n_skipped) counts."""
    if not os.path.isdir(src_dir):
        return (0, 0)
    n_copied = 0
    n_skipped = 0
    for root, dirs, files in os.walk(src_dir):
        # Prune excluded directories in-place so os.walk skips them
        dirs[:] = [d for d in dirs if not matches_exclude(d)]
        for fname in files:
            if matches_exclude(fname):
                n_skipped += 1
                continue
            src_path = os.path.join(root, fname)
            rel = os.path.relpath(src_path, src_dir)
            dst_path = os.path.join(dst_dir, rel)
            if not dry_run:
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copy2(src_path, dst_path)
            n_copied += 1
    return (n_copied, n_skipped)


# ---------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------

def stage_release(repo_root, staging_dir, *,
                   dry_run=False, verbose=True):
    """Copy everything in the manifest into staging_dir. Returns a
    dict of stats + warnings for the caller to display."""
    stats = {
        'files_copied': 0,
        'files_skipped': 0,
        'dirs_copied': 0,
        'warnings': [],
    }

    # Clean staging dir before populating
    if os.path.exists(staging_dir):
        if dry_run:
            stats['warnings'].append(
                f"Dry run — staging dir {staging_dir} would be removed first")
        else:
            shutil.rmtree(staging_dir)
    if not dry_run:
        os.makedirs(staging_dir, exist_ok=True)

    # Top-level files
    for rel in INCLUDE_FILES:
        src = os.path.join(repo_root, rel)
        dst = os.path.join(staging_dir, rel)
        if copy_file(src, dst, dry_run=dry_run):
            stats['files_copied'] += 1
            if verbose:
                print(f'  + {rel}')
        else:
            stats['warnings'].append(
                f"INCLUDE_FILES entry missing: {rel}")
            if verbose:
                print(f'  ! MISSING: {rel}')

    # Whole directories
    for rel in INCLUDE_DIRS:
        src = os.path.join(repo_root, rel)
        dst = os.path.join(staging_dir, rel)
        if not os.path.isdir(src):
            stats['warnings'].append(
                f"INCLUDE_DIRS entry missing: {rel}")
            if verbose:
                print(f'  ! MISSING DIR: {rel}/')
            continue
        n_copied, n_skipped = copy_tree(src, dst, dry_run=dry_run)
        stats['files_copied'] += n_copied
        stats['files_skipped'] += n_skipped
        stats['dirs_copied'] += 1
        if verbose:
            print(f'  + {rel}/  ({n_copied} files, {n_skipped} excluded)')

    # Specific files from dev/
    for rel in INCLUDE_FROM_DEV:
        src = os.path.join(repo_root, rel)
        dst = os.path.join(staging_dir, rel)
        if copy_file(src, dst, dry_run=dry_run):
            stats['files_copied'] += 1
            if verbose:
                print(f'  + {rel}')
        else:
            stats['warnings'].append(
                f"INCLUDE_FROM_DEV entry missing: {rel}")
            if verbose:
                print(f'  ! MISSING: {rel}')

    # Optional dirs — silent skip when missing, but report
    for rel in OPTIONAL_DIRS:
        src = os.path.join(repo_root, rel)
        dst = os.path.join(staging_dir, rel)
        if not os.path.isdir(src):
            stats['warnings'].append(
                f"Optional dir absent: {rel}/  "
                f"(bundle will work but users must point at their own NR install)")
            if verbose:
                print(f'  ~ optional missing: {rel}/')
            continue
        n_copied, n_skipped = copy_tree(src, dst, dry_run=dry_run)
        stats['files_copied'] += n_copied
        stats['files_skipped'] += n_skipped
        stats['dirs_copied'] += 1
        if verbose:
            print(f'  + {rel}/  ({n_copied} files, {n_skipped} excluded)')
        # Specific check: vanilla_msbs/ should have .msb.dcx in it
        if rel == 'vanilla_msbs':
            msbs = [f for f in os.listdir(src) if f.endswith('.msb.dcx')]
            if not msbs:
                stats['warnings'].append(
                    f"vanilla_msbs/ exists but contains no .msb.dcx files — "
                    f"bundle's default-input flow will fall back to user-pick")

    return stats


# ---------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------

def verify_release(staging_dir, *, verbose=True):
    """After staging, sanity-check the result. Returns a list of
    issues — empty means looks good. Doesn't import or run anything;
    pure filesystem inspection."""
    issues = []

    # Every INCLUDE_FILES entry must exist in staging
    for rel in INCLUDE_FILES:
        if not os.path.isfile(os.path.join(staging_dir, rel)):
            issues.append(f"Staged file missing: {rel}")

    # Every INCLUDE_DIRS must exist with at least one file
    for rel in INCLUDE_DIRS:
        d = os.path.join(staging_dir, rel)
        if not os.path.isdir(d):
            issues.append(f"Staged dir missing: {rel}/")
            continue
        # Count files (any nesting)
        n = sum(len(files) for _, _, files in os.walk(d))
        if n == 0:
            issues.append(f"Staged dir empty: {rel}/")

    # Every INCLUDE_FROM_DEV must exist
    for rel in INCLUDE_FROM_DEV:
        if not os.path.isfile(os.path.join(staging_dir, rel)):
            issues.append(f"Staged dev/ file missing: {rel}")

    # No __pycache__ or *.pyc anywhere — strip was effective
    leaked_pycache = []
    leaked_pyc = []
    leaked_user = []
    leaked_tests = []
    for root, dirs, files in os.walk(staging_dir):
        if '__pycache__' in dirs:
            leaked_pycache.append(os.path.relpath(
                os.path.join(root, '__pycache__'), staging_dir))
        if 'tests' in dirs:
            leaked_tests.append(os.path.relpath(
                os.path.join(root, 'tests'), staging_dir))
        for f in files:
            if f.endswith(('.pyc', '.pyo')):
                leaked_pyc.append(os.path.relpath(
                    os.path.join(root, f), staging_dir))
            elif f.startswith('.4laric_'):
                leaked_user.append(os.path.relpath(
                    os.path.join(root, f), staging_dir))
    if leaked_pycache:
        issues.append(f"__pycache__ leaked into staging: "
                       f"{leaked_pycache[:3]}{'…' if len(leaked_pycache) > 3 else ''}")
    if leaked_pyc:
        issues.append(f".pyc files leaked: {leaked_pyc[:3]}"
                       f"{'…' if len(leaked_pyc) > 3 else ''}")
    if leaked_user:
        issues.append(f"User-specific .4laric_* files leaked: {leaked_user}")
    if leaked_tests:
        issues.append(f"tests/ dirs leaked into staging: {leaked_tests}")

    return issues


# ---------------------------------------------------------------------
# Zip
# ---------------------------------------------------------------------

def make_zip(staging_dir, zip_path, *, verbose=True):
    """Walk staging_dir and write a zip. Each entry is stored under
    a top-level folder named after the zip's basename (sans .zip) so
    users get a clean unpack — no zip-bomb of loose files at their cwd."""
    if os.path.exists(zip_path):
        os.remove(zip_path)
    top_folder = os.path.splitext(os.path.basename(zip_path))[0]
    n_files = 0
    n_bytes = 0
    with zipfile.ZipFile(zip_path, 'w',
                          compression=zipfile.ZIP_DEFLATED,
                          compresslevel=6) as zf:
        for root, _, files in os.walk(staging_dir):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, staging_dir)
                arcname = os.path.join(top_folder, rel).replace('\\', '/')
                zf.write(src, arcname)
                n_files += 1
                n_bytes += os.path.getsize(src)
    return (n_files, n_bytes, os.path.getsize(zip_path))


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build a publishable release zip for the rando.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--no-zip', action='store_true',
        help='Stage to disk only; skip zip creation.')
    parser.add_argument('--out-dir', default=None,
        help='Output dir for staging + zip (default: <repo>/build/)')
    parser.add_argument('--name', default=None,
        help='Archive basename (default: nightreign-enemy-rando-<version>.zip)')
    parser.add_argument('--dry-run', action='store_true',
        help='Show what would be copied without writing anything.')
    parser.add_argument('--quiet', action='store_true',
        help='Suppress per-file output.')
    args = parser.parse_args()

    verbose = not args.quiet
    version = read_engine_version(REPO_ROOT)
    out_dir = args.out_dir or os.path.join(REPO_ROOT, 'build')
    archive_name = args.name or f'nightreign-enemy-rando-{version}.zip'
    if not archive_name.endswith('.zip'):
        archive_name += '.zip'
    staging_subdir = os.path.splitext(archive_name)[0]
    staging_dir = os.path.join(out_dir, staging_subdir)
    zip_path = os.path.join(out_dir, archive_name)

    print(f'Building release: {archive_name}')
    print(f'  Engine version: {version}')
    print(f'  Staging dir:    {staging_dir}')
    print(f'  Output zip:     {zip_path if not args.no_zip else "(skipped)"}')
    if args.dry_run:
        print(f'  [DRY RUN — no files will be written]')
    print()

    print('Staging files:')
    stats = stage_release(REPO_ROOT, staging_dir,
                           dry_run=args.dry_run, verbose=verbose)
    print()
    print(f'  Files copied:   {stats["files_copied"]}')
    print(f'  Files excluded: {stats["files_skipped"]}')
    print(f'  Dirs copied:    {stats["dirs_copied"]}')

    if stats['warnings']:
        print()
        print('Warnings:')
        for w in stats['warnings']:
            print(f'  ⚠  {w}')

    if args.dry_run:
        print('\n[dry run complete — no files written]')
        return 0

    # Verify
    print()
    print('Verifying staging:')
    issues = verify_release(staging_dir, verbose=verbose)
    if issues:
        print()
        print('Verification issues:')
        for issue in issues:
            print(f'  ✗  {issue}')
        return 1
    else:
        print('  ✓  All files present, no leakage.')

    # Zip
    if not args.no_zip:
        print()
        print(f'Creating zip: {zip_path}')
        n_files, n_bytes, zip_size = make_zip(staging_dir, zip_path,
                                                verbose=verbose)
        print(f'  {n_files} files, '
              f'{n_bytes / 1024 / 1024:.1f} MB uncompressed, '
              f'{zip_size / 1024 / 1024:.1f} MB zipped '
              f'({100 * zip_size / max(n_bytes, 1):.1f}% ratio)')

    print()
    print('Done.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
