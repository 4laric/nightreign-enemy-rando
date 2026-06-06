#!/usr/bin/env python3
"""
build_release.py — package the rando as a me3 PROFILE the user drops
straight into their me3 profiles directory and runs from there.

v0.30 distribution pivot
========================
Earlier releases shipped one flat zip and made the user wire the rando
into whatever me3 setup they already had (configure a package path,
click "install bundled files", let the GUI try to edit their .me3).
That composed badly — too many independent state machines to reason
about, and "did my output actually land in the package?" was hard to
answer.

The new model ships the rando AS a me3 profile. Extracted into the
me3 profiles dir it looks like:

    <me3 profiles dir>/
    └── nightreign-enemy-rando/                 ← profile root
        ├── nightreign-enemy-rando.me3          ← pre-wired (generated here)
        ├── randomize.pyw / randomize.sh        ← double-click launchers
        ├── README.md / INSTALL.md / CHANGELOG.md / ...
        ├── package/                            ← the me3 PACKAGE (path = "package/")
        │   ├── regulation.bin                  ← bundled, at deploy path
        │   ├── script/  material/  sfx/  ...   ← bundled deps at deploy paths
        │   ├── map/  chr/                      ← rando output / heritage chrs
        │   └── ...
        └── _rando/                             ← tool code (me3 never looks here)
            ├── oops_rando_gui.py  oops_v3.py  engine/  data/  dev/  ...
            └── bundled_regulation/ bundled_aicommon/ bundled_sfx/  ← reset sources

Why nested `package/` instead of `path = "."`?
-----------------------------------------------
me3 maps a package directory's *contents* into the game VFS ("as if they
were next to eldenring.exe"). Every documented me3 example points a
package at a SUBFOLDER (`path = 'mod'`), never at the profile root. With
`path = "package/"` me3 only ever sees real game-asset dirs; the .me3,
the docs, the launchers and `_rando/` sit OUTSIDE the package where me3
can't trip over them. Cost: one directory level. Benefit: zero ambiguity
— which is the entire point of this pivot. Set PACKAGE_SUBDIR = '' below
to fall back to the flat `path = "."` layout if you ever want it.

This script is manifest-driven (INCLUDE_FILES / INCLUDE_DIRS /
INCLUDE_FROM_DEV) and the bundled-binary placement is driven by
bundle_installer.BUNDLED_INSTALLS — the SAME registry the in-app
"reinstall bundled files" button uses. One source of truth, so the
build and the runtime stay in sync, and adding a module or a bundle is
a one-line manifest edit, not a code change here.

Usage:
    python3 scripts/build_release.py                 # full profile zip
    python3 scripts/build_release.py --no-zip        # stage only (fast; for inspection)
    python3 scripts/build_release.py --no-bundle-refs # also drop the small reset-source copies (regulation/aicommon)
    python3 scripts/build_release.py --out-dir /tmp/x
    python3 scripts/build_release.py --name custom.zip
    python3 scripts/build_release.py --dry-run
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

# bundle_installer lives at the repo root and (by design) imports no
# tkinter — safe to import here so the build and the in-app installer
# share one BUNDLED_INSTALLS registry.
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
try:
    from bundle_installer import BUNDLED_INSTALLS, list_bundle_content_files
except Exception as _e:  # pragma: no cover - surfaced at runtime
    BUNDLED_INSTALLS = []
    def list_bundle_content_files(_d):
        return []
    _BUNDLE_IMPORT_ERROR = _e
else:
    _BUNDLE_IMPORT_ERROR = None


# ---------------------------------------------------------------------
# Layout knobs
# ---------------------------------------------------------------------
PROFILE_DIR_NAME = 'nightreign-enemy-rando'   # top folder in the zip = extracted profile dir
PROFILE_ID = 'nightreign-enemy-rando'         # me3 package id
ME3_FILENAME = 'nightreign-enemy-rando.me3'   # pre-wired profile file at profile root
RANDO_SUBDIR = '_rando'                       # tool code (invisible to me3)
PACKAGE_SUBDIR = 'package'                     # '' => flat `path = "."`; 'package' => nested `path = "package/"`
SHIP_BUNDLE_REFERENCE_COPIES = True            # master switch: ship bundled_*/ under _rando/ as reset-to-defaults sources
# Bundles to deploy to package/ but NOT also ship a reference copy of under
# _rando/. The reference copy only feeds the in-app "reinstall bundled
# files" button; for a large, static dependency that the rando never
# rewrites (the ~182MB sfx blob) the duplication isn't worth it — the
# deploy-path copy is enough, and re-extracting the zip is a fine recovery
# in the rare corruption case. The in-app button degrades gracefully: it
# skips any bundle whose reference dir is absent and logs that it did, while
# still reinstalling the others (regulation, aicommon).
SKIP_REFERENCE_COPY_FOR = {'bundled_sfx'}
SUPPORTED_GAME = 'nightreign'


# ---------------------------------------------------------------------
# Manifest  (source of truth — re-homed into the profile layout below)
# ---------------------------------------------------------------------
# Top-level Python + JSON the rando needs at runtime. Everything here
# EXCEPT the ROOT_DOCS lands under _rando/. The cost of forgetting a
# file is "runtime crash on a user's machine"; the cost of an extra is
# "a few KB".
INCLUDE_FILES = [
    # Runtime entry points
    'oops_rando_gui.py',
    'oops_rando_gui.pyw',   # power-user launcher (run from inside _rando/)
    'check_setup.py',
    # Engine + core
    'oops_v3.py',
    'oops_all_anyone.py',
    'swap_compat.py',
    'bundle_installer.py',   # BUNDLED_INSTALLS registry — imported by the GUI at load AND by this build script
    # Archive reader (read vanilla data straight from a packed install)
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
    # v0.29 merchant / regulation subsystem (imported by the GUI + oops_v3).
    # regulation_rando -> regulation_io + merchant_shop_fill, so all three
    # ship together; night_role is imported by both oops_v3 and the GUI.
    'regulation_rando.py',
    'regulation_io.py',
    'merchant_shop_fill.py',
    'night_role.py',
    # me3-profile relocator/recovery module (imported by the GUI). Under the
    # v0.30 shipped-profile model its auto-register path is vestigial, but the
    # GUI still imports it, so it must ship to avoid a ModuleNotFoundError.
    'me3_profile.py',
    # Auxiliary / debug tools
    'check_patched_deep.py',
    'diff_vanilla_vs_patched.py',
    'dump_vanilla_fmg.py',
    # Documentation (these go to the PROFILE ROOT, not _rando/ — see ROOT_DOCS)
    'README.md',
    'INSTALL.md',
    'CHANGELOG.md',
    'PATCH_NOTES.md',
    'SHIP_NOTES.md',
    'LICENSE',
]

# Of INCLUDE_FILES, these are the user-facing docs that belong at the
# profile root (next to the .me3), not buried in _rando/.
ROOT_DOCS = {
    'README.md', 'INSTALL.md', 'CHANGELOG.md',
    'PATCH_NOTES.md', 'SHIP_NOTES.md', 'LICENSE',
}

# Whole directories that ship under _rando/. Bundle dirs handled by
# BUNDLED_INSTALLS are filtered out of this loop automatically (so
# whether or not the manifest lists bundled_aicommon, bundles are
# placed exactly once, by the bundle stage).
INCLUDE_DIRS = [
    'data',              # JSON catalogs the engine reads at load
    'engine',            # pack_loaders + runtime helpers
    'docs',              # extra user-facing docs (the docs/ dir, not the root README)
    'bundled_aicommon',  # (also a BUNDLED_INSTALLS entry — filtered, placed by bundle stage)
    'patched_emevd',     # "Install pre-patched EMEVD" source
    'healthbar_tools',   # used by dcx_batch
    'healthbar_inplace', # used by check_patched_deep / dcx_batch
]

# Specific dev/ files runtime code imports (dev/ as a whole is excluded).
# Land under _rando/dev/ to preserve `import install_discovery` from the
# `HERE/dev` sys.path insert the GUI does.
#
# pools_caps_panel / boutique_pool_panel: these are runtime GUI tab mixins,
# not dev-only tools. The GUI imports them through the same HERE/dev
# sys.path insert and its own comments say the trick exists "so the import
# works from a packaged install too" — but the pre-v0.30 manifest never
# shipped them, so released builds silently hid the Pools & Caps and
# Boutique Pool tabs (the GUI degrades to a no-op stub on ImportError).
# Shipping them here closes that gap. Both import only oops_rando_gui +
# oops_v3 (already shipped) — no further dev dependencies.
INCLUDE_FROM_DEV = [
    'dev/install_discovery.py',
    'dev/heritage_chr_import.py',
    'dev/import_heritage_ai_scripts.py',
    'dev/pools_caps_panel.py',
    'dev/boutique_pool_panel.py',
    # dev tools imported lazily by shipped runtime code:
    #   apply_slot_repositions <- dcx_batch.py (slot-repositioning step)
    #   chr_asset_resolver     <- dev/heritage_chr_import.py
    'dev/apply_slot_repositions.py',
    'dev/chr_asset_resolver.py',
]

# Included under _rando/ if present, silently skipped if missing.
# vanilla_msbs/ is the big optional one (Alaric populates it at release
# time). Lands at _rando/vanilla_msbs/ so the GUI's HERE/vanilla_msbs
# input default resolves out of the box.
OPTIONAL_DIRS = [
    'vanilla_msbs',
]

EXCLUDE_PATTERNS = [
    '__pycache__', '*.pyc', '*.pyo',
    'tests',
    '.DS_Store', 'Thumbs.db', '*.swp', '*.swo', '*~',
    '*.bak', '*.tmp',
    '.4laric_*.json',     # user-specific GUI state — never ship (keeps fresh-extract defaults clean)
    'oo2core_*.dll',      # Oodle — user provides per NR install
    'vanilla_npcname_dump.txt',
    'build_release.py.*.bak',
]

# Bundle dirs are owned by the bundle stage; never let the generic
# INCLUDE_DIRS loop also stage them.
_BUNDLE_DIRS = {e['bundle_dir'] for e in BUNDLED_INSTALLS}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def read_engine_version(repo_root):
    """Extract V3_ENGINE_FINGERPRINT from oops_v3.py for the zip name +
    the generated .me3 comment. Falls back to a UTC date stamp."""
    path = os.path.join(repo_root, 'oops_v3.py')
    try:
        with open(path) as f:
            for line in f:
                m = re.search(r"V3_ENGINE_FINGERPRINT\s*=\s*['\"]([^'\"]+)['\"]", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return datetime.now(timezone.utc).strftime('%Y%m%d')


def matches_exclude(path, patterns=EXCLUDE_PATTERNS):
    parts = path.replace('\\', '/').split('/')
    for part in parts:
        for pattern in patterns:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def copy_file(src, dst, *, dry_run=False):
    if not os.path.isfile(src):
        return False
    if dry_run:
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def copy_tree(src_dir, dst_dir, *, dry_run=False):
    if not os.path.isdir(src_dir):
        return (0, 0)
    n_copied = n_skipped = 0
    for root, dirs, files in os.walk(src_dir):
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


def package_root_rel():
    """Path of the me3 package root relative to the profile root.
    '' (flat) or 'package'."""
    return PACKAGE_SUBDIR


def me3_package_path_value():
    """The `path` value written into the .me3 [[packages]] entry."""
    return '.' if not PACKAGE_SUBDIR else f'{PACKAGE_SUBDIR}/'


def generate_me3_text(version):
    """Build the pre-wired .me3 profile contents via the shared generator in
    me3_profile, so the shipped baseline and the GUI's runtime rewrite emit an
    identical format. Package-only (no natives) — the GUI adds DLL natives when
    the user configures them."""
    from me3_profile import build_me3_text  # repo-root module (on sys.path)
    header = [
        f'{PROFILE_ID} — me3 profile (engine {version})',
        'Generated by scripts/build_release.py. Edit the build script, not this file.',
        '',
        'Double-click this file to launch Nightreign with the randomizer active.',
        'To (re)generate the randomized maps first, run the launcher in this',
        'folder (randomize.pyw on Windows, ./randomize.sh on Linux/Mac).',
    ]
    return build_me3_text(me3_package_path_value(), game=SUPPORTED_GAME,
                          package_id=PROFILE_ID, header_lines=header)


def generate_randomize_pyw():
    """Windows double-click launcher at the profile root. Puts _rando/
    on sys.path and starts the GUI (no console window via .pyw)."""
    return (
        '#!/usr/bin/env pythonw\n'
        '"""Double-click launcher for the Nightreign Enemy Randomizer.\n'
        '\n'
        'Lives at the me3 profile root. Adds the sibling _rando/ folder\n'
        '(the tool code) to sys.path and starts the GUI. me3 ignores\n'
        'this file — it is not under the package directory.\n'
        '"""\n'
        'import os\n'
        'import sys\n'
        '\n'
        'PROFILE_ROOT = os.path.dirname(os.path.abspath(__file__))\n'
        'RANDO_DIR = os.path.join(PROFILE_ROOT, "_rando")\n'
        'if RANDO_DIR not in sys.path:\n'
        '    sys.path.insert(0, RANDO_DIR)\n'
        'try:\n'
        '    import oops_rando_gui\n'
        '    oops_rando_gui.main()\n'
        'except Exception:\n'
        '    # If the GUI fails to import/launch, surface the traceback in a\n'
        '    # console-less context by writing it next to the launcher.\n'
        '    import traceback\n'
        '    crash = os.path.join(PROFILE_ROOT, "randomize_crash.txt")\n'
        '    with open(crash, "w", encoding="utf-8") as f:\n'
        '        traceback.print_exc(file=f)\n'
        '    raise\n'
    )


def generate_randomize_sh():
    """Linux/Mac launcher at the profile root."""
    return (
        '#!/usr/bin/env bash\n'
        '# Launcher for the Nightreign Enemy Randomizer (Linux/Mac).\n'
        '# Runs the GUI from the sibling _rando/ tool directory.\n'
        'set -euo pipefail\n'
        'PROFILE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'PY="${PYTHON:-python3}"\n'
        'exec "$PY" "$PROFILE_ROOT/_rando/oops_rando_gui.py" "$@"\n'
    )


# ---------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------

def stage_release(repo_root, staging_dir, version, *,
                  dry_run=False, verbose=True, ship_bundle_refs=True):
    """Stage the full me3-profile layout into staging_dir (the profile
    root). Returns stats + warnings."""
    stats = {'files_copied': 0, 'files_skipped': 0, 'dirs_copied': 0,
             'bundles_deployed': 0, 'warnings': []}

    if _BUNDLE_IMPORT_ERROR is not None:
        stats['warnings'].append(
            f"Could not import bundle_installer ({_BUNDLE_IMPORT_ERROR}) — "
            f"bundled binaries will NOT be placed at deploy paths.")

    if os.path.exists(staging_dir):
        if dry_run:
            stats['warnings'].append(
                f"Dry run — staging dir {staging_dir} would be removed first")
        else:
            shutil.rmtree(staging_dir)
    if not dry_run:
        os.makedirs(staging_dir, exist_ok=True)

    rando_dir = os.path.join(staging_dir, RANDO_SUBDIR)
    pkg_dir = (os.path.join(staging_dir, PACKAGE_SUBDIR)
               if PACKAGE_SUBDIR else staging_dir)

    # Create the package and tool dirs up front so the profile layout is
    # well-formed even before any bundle deploys or rando output exists —
    # me3 then always has a real directory at the .me3's declared `path`,
    # and `_rando/` is present for the launcher's sys.path insert. (In a
    # normal release the bundle stage would create package/ anyway; this
    # just makes the layout independent of which bundles happen to ship.)
    if not dry_run:
        os.makedirs(pkg_dir, exist_ok=True)
        os.makedirs(rando_dir, exist_ok=True)

    # --- generated profile-root files --------------------------------
    generated = {
        ME3_FILENAME: generate_me3_text(version),
        'randomize.pyw': generate_randomize_pyw(),
        'randomize.sh': generate_randomize_sh(),
    }
    for name, text in generated.items():
        dst = os.path.join(staging_dir, name)
        if not dry_run:
            with open(dst, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            if name == 'randomize.sh':
                os.chmod(dst, 0o755)
        stats['files_copied'] += 1
        if verbose:
            print(f'  + {name}   (generated)')

    # --- top-level INCLUDE_FILES: docs -> root, rest -> _rando/ -------
    for rel in INCLUDE_FILES:
        src = os.path.join(repo_root, rel)
        if rel in ROOT_DOCS:
            dst = os.path.join(staging_dir, rel)
            where = rel
        else:
            dst = os.path.join(rando_dir, rel)
            where = f'{RANDO_SUBDIR}/{rel}'
        if copy_file(src, dst, dry_run=dry_run):
            stats['files_copied'] += 1
            if verbose:
                print(f'  + {where}')
        else:
            stats['warnings'].append(f"INCLUDE_FILES entry missing: {rel}")
            if verbose:
                print(f'  ! MISSING: {rel}')

    # --- whole dirs -> _rando/ (bundle dirs handled separately) ------
    for rel in INCLUDE_DIRS:
        if rel in _BUNDLE_DIRS:
            continue  # placed by the bundle stage (deploy path + reference copy)
        src = os.path.join(repo_root, rel)
        dst = os.path.join(rando_dir, rel)
        if not os.path.isdir(src):
            stats['warnings'].append(f"INCLUDE_DIRS entry missing: {rel}")
            if verbose:
                print(f'  ! MISSING DIR: {rel}/')
            continue
        n_c, n_s = copy_tree(src, dst, dry_run=dry_run)
        stats['files_copied'] += n_c
        stats['files_skipped'] += n_s
        stats['dirs_copied'] += 1
        if verbose:
            print(f'  + {RANDO_SUBDIR}/{rel}/  ({n_c} files, {n_s} excluded)')

    # --- dev/ picks -> _rando/dev/ ------------------------------------
    for rel in INCLUDE_FROM_DEV:
        src = os.path.join(repo_root, rel)
        dst = os.path.join(rando_dir, rel)
        if copy_file(src, dst, dry_run=dry_run):
            stats['files_copied'] += 1
            if verbose:
                print(f'  + {RANDO_SUBDIR}/{rel}')
        else:
            stats['warnings'].append(f"INCLUDE_FROM_DEV entry missing: {rel}")
            if verbose:
                print(f'  ! MISSING: {rel}')

    # --- optional dirs -> _rando/ -------------------------------------
    for rel in OPTIONAL_DIRS:
        src = os.path.join(repo_root, rel)
        dst = os.path.join(rando_dir, rel)
        if not os.path.isdir(src):
            stats['warnings'].append(
                f"Optional dir absent: {rel}/ "
                f"(bundle works, but users must point at their own NR install)")
            if verbose:
                print(f'  ~ optional missing: {rel}/')
            continue
        n_c, n_s = copy_tree(src, dst, dry_run=dry_run)
        stats['files_copied'] += n_c
        stats['files_skipped'] += n_s
        stats['dirs_copied'] += 1
        if verbose:
            print(f'  + {RANDO_SUBDIR}/{rel}/  ({n_c} files, {n_s} excluded)')
        if rel == 'vanilla_msbs':
            msbs = [f for f in os.listdir(src) if f.endswith('.msb.dcx')]
            if not msbs:
                stats['warnings'].append(
                    "vanilla_msbs/ exists but has no .msb.dcx — default-input "
                    "flow will fall back to user-pick")

    # --- bundled binaries: deploy paths in package/ + reference copies -
    for entry in BUNDLED_INSTALLS:
        bundle_abs = os.path.join(repo_root, entry['bundle_dir'])
        content = list_bundle_content_files(bundle_abs)
        critical = os.path.join(bundle_abs, entry['critical_file'])
        if not content or not os.path.exists(critical):
            stats['warnings'].append(
                f"Bundle '{entry['bundle_dir']}' missing or empty "
                f"(critical: {entry['critical_file']}) — its files will NOT "
                f"be present at the package deploy path. Cross-game / DLC / "
                f"heritage features that depend on it may break.")
            if verbose:
                print(f"  ! BUNDLE MISSING: {entry['bundle_dir']}")
            continue
        # deploy path: <package>/<target_subpath>/<file>
        target_dir = (os.path.join(pkg_dir, entry['target_subpath'])
                      if entry['target_subpath'] else pkg_dir)
        for src in content:
            dst = os.path.join(target_dir, os.path.basename(src))
            if copy_file(src, dst, dry_run=dry_run):
                stats['files_copied'] += 1
        stats['bundles_deployed'] += 1
        deploy_label = (f'{package_root_rel()}/{entry["target_subpath"]}'
                        if entry['target_subpath']
                        else (package_root_rel() or '<package root>'))
        if verbose:
            print(f"  + bundle '{entry['bundle_dir']}' -> {deploy_label}/ "
                  f"({len(content)} file(s) at deploy path)")
        # reference copy under _rando/<bundle_dir>/ (source for the in-app
        # "reinstall bundled files" button; HERE/<bundle_dir> resolves there).
        # Big static bundles in SKIP_REFERENCE_COPY_FOR deploy once only.
        if ship_bundle_refs and entry['bundle_dir'] not in SKIP_REFERENCE_COPY_FOR:
            ref_dst = os.path.join(rando_dir, entry['bundle_dir'])
            n_c, n_s = copy_tree(bundle_abs, ref_dst, dry_run=dry_run)
            stats['files_copied'] += n_c
            stats['files_skipped'] += n_s
            if verbose:
                print(f"      + reference copy -> {RANDO_SUBDIR}/"
                      f"{entry['bundle_dir']}/ ({n_c} file(s))")
        elif ship_bundle_refs and verbose:
            print(f"      ~ reference copy skipped for "
                  f"{entry['bundle_dir']}/ (ships once at deploy path)")

    return stats


# ---------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------

def verify_release(staging_dir, *, ship_bundle_refs=True, verbose=True):
    """Pure filesystem sanity-check of the staged profile layout."""
    issues = []
    rando_dir = os.path.join(staging_dir, RANDO_SUBDIR)
    pkg_dir = (os.path.join(staging_dir, PACKAGE_SUBDIR)
               if PACKAGE_SUBDIR else staging_dir)

    # profile-root: .me3 + launchers + docs
    if not os.path.isfile(os.path.join(staging_dir, ME3_FILENAME)):
        issues.append(f"Profile root missing {ME3_FILENAME}")
    for name in ('randomize.pyw', 'randomize.sh'):
        if not os.path.isfile(os.path.join(staging_dir, name)):
            issues.append(f"Profile root missing launcher: {name}")
    for doc in ROOT_DOCS:
        if not os.path.isfile(os.path.join(staging_dir, doc)):
            issues.append(f"Profile root missing doc: {doc}")

    # .me3 must declare the package path we built
    try:
        me3_txt = open(os.path.join(staging_dir, ME3_FILENAME),
                       encoding='utf-8').read()
        want = f"path = '{me3_package_path_value()}'"
        if want not in me3_txt:
            issues.append(f".me3 does not declare expected package path "
                          f"({want!r})")
        if f'id = "{PROFILE_ID}"' not in me3_txt:
            issues.append(f".me3 missing expected package id {PROFILE_ID!r}")
    except OSError:
        issues.append("Could not read generated .me3")

    # _rando/: the runtime modules must be there (sample the entry points)
    for rel in INCLUDE_FILES:
        if rel in ROOT_DOCS:
            continue
        if not os.path.isfile(os.path.join(rando_dir, rel)):
            issues.append(f"_rando/ missing runtime file: {rel}")
    for rel in INCLUDE_FROM_DEV:
        if not os.path.isfile(os.path.join(rando_dir, rel)):
            issues.append(f"_rando/ missing dev file: {rel}")
    for rel in INCLUDE_DIRS:
        if rel in _BUNDLE_DIRS:
            continue
        d = os.path.join(rando_dir, rel)
        if not os.path.isdir(d) or sum(len(f) for _, _, f in os.walk(d)) == 0:
            issues.append(f"_rando/{rel}/ missing or empty")

    # package/: every bundle's critical file must be at its deploy path
    for entry in BUNDLED_INSTALLS:
        src_content = list_bundle_content_files(
            os.path.join(REPO_ROOT, entry['bundle_dir']))
        if not src_content:
            continue  # already reported as a staging warning
        tgt = (os.path.join(pkg_dir, entry['target_subpath'])
               if entry['target_subpath'] else pkg_dir)
        crit = os.path.join(tgt, entry['critical_file'])
        if not os.path.isfile(crit):
            issues.append(f"package deploy path missing {entry['critical_file']} "
                          f"(expected at {os.path.relpath(crit, staging_dir)})")
        if ship_bundle_refs and entry['bundle_dir'] not in SKIP_REFERENCE_COPY_FOR:
            ref_crit = os.path.join(rando_dir, entry['bundle_dir'],
                                    entry['critical_file'])
            if not os.path.isfile(ref_crit):
                issues.append(f"reference copy missing {entry['critical_file']} "
                              f"under _rando/{entry['bundle_dir']}/")
        elif entry['bundle_dir'] in SKIP_REFERENCE_COPY_FOR:
            # Deliberately shipped once: assert the reference copy is ABSENT
            # so an accidental re-introduction of the 182MB duplicate fails CI.
            ref_dir = os.path.join(rando_dir, entry['bundle_dir'])
            if os.path.isdir(ref_dir):
                issues.append(f"{entry['bundle_dir']}/ reference copy present "
                              f"under _rando/ but is in SKIP_REFERENCE_COPY_FOR "
                              f"(should ship once at the deploy path only)")

    # me3 must not see foreign files: nothing but the package dir (and,
    # in flat mode, the deploy files) should look like a game-asset dir.
    # In nested mode, assert _rando/ is NOT under the package.
    if PACKAGE_SUBDIR:
        if os.path.isdir(os.path.join(pkg_dir, RANDO_SUBDIR)):
            issues.append(f"_rando/ leaked INTO the package dir — me3 would "
                          f"see the tool code")
        if os.path.isfile(os.path.join(pkg_dir, ME3_FILENAME)):
            issues.append(".me3 leaked into the package dir")

    # leakage checks
    leaked = {'pycache': [], 'pyc': [], 'user': [], 'tests': []}
    for root, dirs, files in os.walk(staging_dir):
        if '__pycache__' in dirs:
            leaked['pycache'].append(os.path.relpath(
                os.path.join(root, '__pycache__'), staging_dir))
        if 'tests' in dirs:
            leaked['tests'].append(os.path.relpath(
                os.path.join(root, 'tests'), staging_dir))
        for f in files:
            if f.endswith(('.pyc', '.pyo')):
                leaked['pyc'].append(os.path.relpath(os.path.join(root, f), staging_dir))
            elif f.startswith('.4laric_'):
                leaked['user'].append(os.path.relpath(os.path.join(root, f), staging_dir))
    if leaked['pycache']:
        issues.append(f"__pycache__ leaked: {leaked['pycache'][:3]}"
                      f"{'…' if len(leaked['pycache']) > 3 else ''}")
    if leaked['pyc']:
        issues.append(f".pyc leaked: {leaked['pyc'][:3]}"
                      f"{'…' if len(leaked['pyc']) > 3 else ''}")
    if leaked['user']:
        issues.append(f"User-specific .4laric_* leaked: {leaked['user']}")
    if leaked['tests']:
        issues.append(f"tests/ dirs leaked: {leaked['tests']}")

    return issues


# ---------------------------------------------------------------------
# Zip
# ---------------------------------------------------------------------

def make_zip(staging_dir, zip_path, *, verbose=True):
    """Write a zip whose single top-level folder is PROFILE_DIR_NAME, so
    the user extracts a clean `nightreign-enemy-rando/` profile dir
    regardless of the (versioned) zip filename. me3 finds the .me3 by
    extension, so the fixed dir name is safe even if the user renames it."""
    if os.path.exists(zip_path):
        os.remove(zip_path)
    n_files = n_bytes = 0
    with zipfile.ZipFile(zip_path, 'w',
                         compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, files in os.walk(staging_dir):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, staging_dir)
                arcname = os.path.join(PROFILE_DIR_NAME, rel).replace('\\', '/')
                zf.write(src, arcname)
                n_files += 1
                n_bytes += os.path.getsize(src)
    return (n_files, n_bytes, os.path.getsize(zip_path))


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build the rando as a me3 profile zip.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--no-zip', action='store_true',
        help='Stage to disk only; skip zip creation.')
    parser.add_argument('--no-bundle-refs', action='store_true',
        help='Drop ALL bundled_*/ reference copies under _rando/. The big '
             'sfx blob already ships once by default (see SKIP_REFERENCE_'
             'COPY_FOR); this additionally drops the small regulation/'
             'aicommon reset sources, disabling the in-app reinstall button.')
    parser.add_argument('--out-dir', default=None,
        help='Output dir for staging + zip (default: <repo>/build/)')
    parser.add_argument('--name', default=None,
        help='Archive basename (default: nightreign-enemy-rando-<version>.me3-profile.zip)')
    parser.add_argument('--dry-run', action='store_true',
        help='Show what would be copied without writing anything.')
    parser.add_argument('--quiet', action='store_true',
        help='Suppress per-file output.')
    args = parser.parse_args()

    verbose = not args.quiet
    ship_refs = SHIP_BUNDLE_REFERENCE_COPIES and not args.no_bundle_refs
    version = read_engine_version(REPO_ROOT)
    out_dir = args.out_dir or os.path.join(REPO_ROOT, 'build')
    archive_name = args.name or f'nightreign-enemy-rando-{version}.me3-profile.zip'
    if not archive_name.endswith('.zip'):
        archive_name += '.zip'
    staging_subdir = os.path.splitext(archive_name)[0]
    staging_dir = os.path.join(out_dir, staging_subdir)
    zip_path = os.path.join(out_dir, archive_name)

    print(f'Building me3-profile release: {archive_name}')
    print(f'  Engine version:   {version}')
    print(f'  Profile dir name: {PROFILE_DIR_NAME}/')
    print(f'  Package layout:   path = "{me3_package_path_value()}"'
          f'{"  (nested)" if PACKAGE_SUBDIR else "  (flat)"}')
    if ship_refs:
        _skipped = ', '.join(sorted(SKIP_REFERENCE_COPY_FOR)) or 'none'
        print(f'  Bundle refs:      shipped under _rando/ (ship-once: {_skipped})')
    else:
        print(f'  Bundle refs:      SKIPPED (no reset sources)')
    print(f'  Staging dir:      {staging_dir}')
    print(f'  Output zip:       {zip_path if not args.no_zip else "(skipped)"}')
    if args.dry_run:
        print('  [DRY RUN — no files will be written]')
    print()

    print('Staging files:')
    stats = stage_release(REPO_ROOT, staging_dir, version,
                          dry_run=args.dry_run, verbose=verbose,
                          ship_bundle_refs=ship_refs)
    print()
    print(f'  Files copied:     {stats["files_copied"]}')
    print(f'  Files excluded:   {stats["files_skipped"]}')
    print(f'  Dirs copied:      {stats["dirs_copied"]}')
    print(f'  Bundles deployed: {stats["bundles_deployed"]}')

    if stats['warnings']:
        print()
        print('Warnings:')
        for w in stats['warnings']:
            print(f'  ⚠  {w}')

    if args.dry_run:
        print('\n[dry run complete — no files written]')
        return 0

    print()
    print('Verifying staging:')
    issues = verify_release(staging_dir, ship_bundle_refs=ship_refs, verbose=verbose)
    if issues:
        print()
        print('Verification issues:')
        for issue in issues:
            print(f'  ✗  {issue}')
        return 1
    print('  ✓  Layout correct, all deploy paths populated, no leakage.')

    if not args.no_zip:
        print()
        print(f'Creating zip: {zip_path}')
        n_files, n_bytes, zip_size = make_zip(staging_dir, zip_path, verbose=verbose)
        print(f'  {n_files} files, '
              f'{n_bytes / 1024 / 1024:.1f} MB uncompressed, '
              f'{zip_size / 1024 / 1024:.1f} MB zipped '
              f'({100 * zip_size / max(n_bytes, 1):.1f}% ratio)')

    print()
    print('Done.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
