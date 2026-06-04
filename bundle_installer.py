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
