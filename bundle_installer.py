"""Bundled-file install registry.

Module-level config + helper for the "Install bundled mod files"
button in oops_rando_gui.py. Lives in its own module (no tkinter
imports) so the lock tests can verify the registry without pulling
in the GUI.

Adding a new bundle:
  1. Create a new top-level directory in the repo (e.g. bundled_chr/)
  2. Drop the deployable files in there + a README.md
  3. Append a single dict to BUNDLED_INSTALLS below

The Generate-tab installer button iterates this list automatically;
no GUI code changes needed. Lock tests
(tests/test_bundle_installer_registry.py) enforce the entry shape +
that the bundle actually exists on disk with its critical_file
present.

Entry shape:
  bundle_dir      relative dir under the repo root containing files
                  to copy
  target_subpath  destination relative to the me3 package root
                  ('' = package root itself)
  description     short human-readable label shown in the confirm modal
  critical_file   the file whose presence the lock test asserts
                  (catches an empty-bundle release packaging mistake)
"""
from __future__ import annotations

import os


BUNDLED_INSTALLS = [
    {
        'bundle_dir':     'bundled_regulation',
        'target_subpath': '',
        'description':    'Pre-patched regulation.bin (HP/damage balance, '
                          'NB whitelist, contamination fix)',
        'critical_file':  'regulation.bin',
    },
    {
        'bundle_dir':     'bundled_aicommon',
        'target_subpath': 'script',
        'description':    'AI manifests (aicommon.luabnd.dcx + DLC) — '
                          'required for cross-game and DLC chr AI to load '
                          '(playtest-confirmed, ER aicommon is not a '
                          'substitute)',
        'critical_file':  'aicommon.luabnd.dcx',
    },
    {
        'bundle_dir':     'bundled_sfx',
        'target_subpath': 'sfx',
        'description':    "MMV's full SFX bundle (sfxbnd_c0000.ffxbnd.dcx, "
                          '~182 MB) — playtest-confirmed dependency for '
                          'base, cross-game, DLC, and heritage chr particle '
                          'effects',
        'critical_file':  'sfxbnd_c0000.ffxbnd.dcx',
    },
    {
        'bundle_dir':     'bundled_material',
        'target_subpath': 'material',
        'description':    "MMV's material binders "
                          '(allmaterial.matbinbnd.dcx + DLC) — required '
                          'for cross-game / heritage chr models that '
                          'reference shaders/materials not in NR\'s base '
                          'material registry (see dev/chr_asset_resolver.py '
                          'SHARED_DEPS "material/")',
        'critical_file':  'allmaterial.matbinbnd.dcx',
    },
    {
        'bundle_dir':     'bundled_shader',
        'target_subpath': 'shader',
        'description':    "MMV's DLC shader binder "
                          "(shaderbdle_dlc01.shaderbdlebnd.dcx, ~39 MB) — "
                          "the compiled shader programs the DLC material "
                          "entries reference. Material binder + shader "
                          "binder travel together; without this, DLC "
                          "heritage chrs render with broken surfaces.",
        'critical_file':  'shaderbdle_dlc01.shaderbdlebnd.dcx',
    },
]


def list_bundle_content_files(bundle_dir_abs: str) -> list[str]:
    """Return sorted absolute paths of the deployable files in a bundle
    directory. Excludes README.md, .md docs, and dotfiles."""
    if not os.path.isdir(bundle_dir_abs):
        return []
    out = []
    for fname in sorted(os.listdir(bundle_dir_abs)):
        if fname.startswith('.'):
            continue
        if fname.lower().endswith('.md'):
            continue
        full = os.path.join(bundle_dir_abs, fname)
        if os.path.isfile(full):
            out.append(full)
    return out


def check_bundled_files_installed(package_root: str) -> dict:
    """Inspect the user's me3 package and report which bundles are
    deployed vs missing.

    For each entry in BUNDLED_INSTALLS, checks whether
    ``<package_root>/<target_subpath>/<critical_file>`` exists. The
    critical_file is the bundle's required-file marker — the same one
    the install button validates against the SOURCE bundle dir. Reusing
    it here means "did the install button actually run successfully"
    is the question being answered: presence of the critical_file at
    the deploy path is the canonical signal.

    Used by:
      - oops_rando_gui._run_shuffle to prompt the user to install
        before a randomize run kicks off
      - compatibility_preflight to surface the same check in the
        passive Generate-tab banner

    Args:
        package_root: absolute path of the me3 package
            (i.e. ``<me3 profile>/<package>``, the directory that
            mirrors the game install)

    Returns dict with keys:
        ``installed``  list[dict] — bundles whose critical_file is present
        ``missing``    list[dict] — bundles whose critical_file is absent
        ``unchecked``  bool — True if ``package_root`` is blank/invalid,
                       in which case ``installed`` + ``missing`` are empty
                       and the caller should treat this as "can't tell"
                       rather than "all missing"

    Each entry dict carries:
        ``bundle_dir``      — registry entry's bundle_dir
        ``target_subpath``  — registry entry's target_subpath
        ``critical_file``   — registry entry's critical_file
        ``description``     — registry entry's description
        ``expected_path``   — the absolute path that was checked
    """
    pkg = (package_root or '').strip()
    if not pkg or not os.path.isdir(pkg):
        return {'installed': [], 'missing': [], 'unchecked': True}

    installed = []
    missing = []
    for entry in BUNDLED_INSTALLS:
        target_dir = (os.path.join(pkg, entry['target_subpath'])
                      if entry['target_subpath'] else pkg)
        expected = os.path.join(target_dir, entry['critical_file'])
        rec = {
            'bundle_dir':     entry['bundle_dir'],
            'target_subpath': entry['target_subpath'],
            'critical_file':  entry['critical_file'],
            'description':    entry['description'],
            'expected_path':  expected,
        }
        if os.path.isfile(expected):
            installed.append(rec)
        else:
            missing.append(rec)
    return {'installed': installed, 'missing': missing, 'unchecked': False}
