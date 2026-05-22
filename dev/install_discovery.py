#!/usr/bin/env python3
"""
install_discovery.py — auto-detect Steam install locations for Nightreign
and Elden Ring.

Approach: locate the Steam install root (Windows registry, OS-specific
defaults on Linux/macOS), parse libraryfolders.vdf to find all Steam
library locations the user has configured, then walk each library's
steamapps/common/ looking for known game directory names and verifying
the game exe is present.

The returned path is the conventional "Game" subdirectory the rando GUI
expects — i.e. `<install>/Game/`, the same directory that contains the
exe and the map/, chr/, event/ subdirs.

USAGE

  # As a library:
  from install_discovery import find_nightreign_install, find_elden_ring_install
  nr = find_nightreign_install()   # → '/path/to/.../ELDEN RING NIGHTREIGN/Game' or None
  er = find_elden_ring_install()   # → '/path/to/.../ELDEN RING/Game' or None

  # As a CLI tool:
  python3 dev/install_discovery.py
  # Prints whatever it found, useful for debugging.

DESIGN NOTES

- Detection by directory name + exe presence, not Steam app ID. Steam
  dir names are stable; app IDs are not always easy to look up offline.
- Returns the first match if multiple exist (e.g. one user with two
  Steam libraries both containing ER). Rare enough not to special-case.
- Linux native, macOS native, and Windows native paths covered. Wine
  prefixes for Linux Proton-running-Windows-games NOT auto-detected
  (would need to scan compatdata/<app>/pfx/drive_c/Program Files);
  Proton users running NR through Steam will still get detected via
  the same libraryfolders.vdf since Proton library config is unified.
- Failure mode is always to return None — never raise. The GUI calls
  this opportunistically; an exception here mustn't break startup.
"""

import json
import os
import re
import sys
from typing import Optional


# Game definitions. Probe by directory name (canonical Steam install
# name) and confirm by checking for the exe at the conventional
# location inside <install>/Game/.
_GAME_PROBES = {
    'nightreign': {
        'dir_names': ['ELDEN RING NIGHTREIGN'],
        'exe_relpath': os.path.join('Game', 'nightreign.exe'),
    },
    'elden_ring': {
        'dir_names': ['ELDEN RING'],
        'exe_relpath': os.path.join('Game', 'eldenring.exe'),
    },
}


def find_steam_install_root() -> Optional[str]:
    """Return the path containing Steam's config/ and steamapps/ dirs,
    or None if we can't find Steam at all."""
    if sys.platform == 'win32':
        # Windows: registry has the canonical InstallPath under HKCU.
        # Falls through to default paths if the registry read fails.
        try:
            import winreg  # type: ignore[import-not-found]
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                val = winreg.QueryValueEx(key, 'SteamPath')[0]
                if val and os.path.isdir(val):
                    return val
        except Exception:
            pass
        for p in (r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam'):
            if os.path.isdir(p):
                return p
        return None

    if sys.platform == 'darwin':
        p = os.path.expanduser('~/Library/Application Support/Steam')
        return p if os.path.isdir(p) else None

    # Linux + others
    for p in (os.path.expanduser('~/.steam/steam'),
              os.path.expanduser('~/.local/share/Steam'),
              os.path.expanduser('~/.steam/root')):
        if os.path.isdir(p):
            return p
    return None


def _find_libraryfolders_vdf(steam_root: str) -> Optional[str]:
    """Steam stores library locations in libraryfolders.vdf. The file
    lives in either steamapps/ (newer Steam) or config/ (older), so
    try both."""
    for sub in ('steamapps', 'config'):
        path = os.path.join(steam_root, sub, 'libraryfolders.vdf')
        if os.path.isfile(path):
            return path
    return None


def _parse_library_paths(vdf_path: str) -> list:
    """Extract every `"path" "..."` value from a libraryfolders.vdf.

    Schema (Steam's plain-text VDF):
        "libraryfolders"
        {
            "0"
            {
                "path"          "C:\\Program Files (x86)\\Steam"
                "label"         ""
                ...
            }
            "1"
            {
                "path"          "D:\\SteamLibrary"
                ...
            }
        }

    Regex is fine here — the format is well-defined and we only need
    the path values, not the full tree. Backslash escapes (`\\\\`) are
    decoded to single backslashes.
    """
    try:
        with open(vdf_path, encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return []
    raw_paths = re.findall(r'"path"\s+"([^"]+)"', content)
    # VDF escapes backslashes as \\ — unescape for filesystem use.
    return [p.replace('\\\\', '\\') for p in raw_paths]


def find_steam_libraries() -> list:
    """Return all Steam library paths configured on this machine,
    each pointing at the library root (not the steamapps subdir).
    The main Steam install is included as the first entry when found.
    """
    root = find_steam_install_root()
    if not root:
        return []
    vdf = _find_libraryfolders_vdf(root)
    if not vdf:
        # No vdf — assume only the main install has a library.
        return [root]
    paths = _parse_library_paths(vdf)
    # Dedupe while preserving order. Some setups list the main Steam
    # install inside libraryfolders.vdf, some don't.
    seen = set()
    libraries = []
    for p in [root] + paths:
        norm = os.path.normpath(p)
        if norm in seen or not os.path.isdir(norm):
            continue
        seen.add(norm)
        libraries.append(norm)
    return libraries


def _find_install_under_library(library: str, probe: dict) -> Optional[str]:
    """Look in <library>/steamapps/common/ for any of the probe's dir
    names, returning <install>/Game if the exe is present at the
    expected sub-path. Case-insensitive comparison since Steam's
    directory case isn't guaranteed on all filesystems."""
    common = os.path.join(library, 'steamapps', 'common')
    if not os.path.isdir(common):
        return None
    target_names = {d.lower() for d in probe['dir_names']}
    try:
        entries = os.listdir(common)
    except OSError:
        return None
    for name in entries:
        if name.lower() not in target_names:
            continue
        install = os.path.join(common, name)
        exe = os.path.join(install, probe['exe_relpath'])
        if os.path.isfile(exe):
            # Return the Game/ subdir — that's what the GUI's
            # game_install_var convention expects.
            return os.path.join(install, 'Game')
    return None


def find_game_install(probe_key: str) -> Optional[str]:
    """Search every configured Steam library for the named game.
    Returns the first match (or None). Cross-library priority is
    insertion order from libraryfolders.vdf, which Steam keeps stable.
    """
    if probe_key not in _GAME_PROBES:
        raise ValueError(f'Unknown probe key {probe_key!r}; expected '
                         f'one of {sorted(_GAME_PROBES)}')
    probe = _GAME_PROBES[probe_key]
    for library in find_steam_libraries():
        hit = _find_install_under_library(library, probe)
        if hit:
            return hit
    return None


def find_nightreign_install() -> Optional[str]:
    """Return the path to NR's Game/ dir if it's installed via Steam,
    else None. Use as a first-launch default for the GUI."""
    return find_game_install('nightreign')


def find_elden_ring_install() -> Optional[str]:
    """Return the path to ER's Game/ dir if it's installed via Steam,
    else None. Use as a first-launch default for the GUI (heritage
    chr imports require ER)."""
    return find_game_install('elden_ring')


# ---------------------------------------------------------------------
# Oodle DLL discovery
# ---------------------------------------------------------------------

# Source-of-truth list of game install directories that ship a usable
# Oodle DLL alongside the exe. Order matters — first match wins, so
# preference is NR > ER > Sekiro (newest Oodle version typically lives
# in the most recently released game). All three ship a 2.x-compatible
# Oodle whose OodleLZ_* ABI is stable, so any of them works for our
# decompress/recompress needs.
_OODLE_SOURCE_GAMES = ('nightreign', 'elden_ring')

# Filename glob inside the source-game's Game/ dir.
_OODLE_DLL_GLOB = 'oo2core_*_win64.dll'


def find_oodle_dll() -> Optional[str]:
    """Locate an oo2core_*_win64.dll on this machine.

    Search order:
      1. OODLE_DLL env var (explicit override; never auto-clobbered)
      2. Any oo2core_*.dll alongside install_discovery.py / dcx.py
         (the rando repo root — what the user manually copied, or what
         a previous `copy_oodle_dll_local` call cached)
      3. Steam-installed source games via find_steam_libraries() →
         <library>/steamapps/common/<game>/Game/oo2core_*.dll
      4. None — caller is expected to surface an actionable error.

    The order is "explicit > local > discovered" so a user who pinned
    a specific DLL path via OODLE_DLL is never silently swapped onto
    a different version found by discovery.

    Returns the full absolute path or None.
    """
    import glob

    # 1. Explicit env var override
    env = os.environ.get('OODLE_DLL')
    if env and os.path.exists(env):
        return env

    # 2. Local-to-repo copy (dcx.py / dev/ sibling — same dir as engine)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_matches = sorted(
        glob.glob(os.path.join(repo_root, _OODLE_DLL_GLOB)), reverse=True)
    if local_matches:
        return local_matches[0]

    # 3. Steam install scan — find the DLL inside NR / ER / Sekiro
    for game_key in _OODLE_SOURCE_GAMES:
        game_dir = find_game_install(game_key)
        if not game_dir:
            continue
        # Newest-numbered DLL first if the game ships multiple versions
        cands = sorted(glob.glob(os.path.join(game_dir, _OODLE_DLL_GLOB)),
                       reverse=True)
        if cands:
            return cands[0]

    return None


def copy_oodle_dll_local(dest_dir: Optional[str] = None) -> Optional[str]:
    """Copy a discovered Oodle DLL into dest_dir (defaults to the repo
    root) so subsequent runs don't have to re-scan Steam. Returns the
    destination path on success, or None if no DLL was found or the
    copy failed.

    Idempotent: if a copy already exists in dest_dir, returns its path
    without re-copying. This lets the GUI call it unconditionally at
    startup ("ensure Oodle is locally available") without worrying
    about wasted I/O or filesystem permission noise.
    """
    import glob, shutil
    if dest_dir is None:
        dest_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Already cached locally?
    existing = sorted(
        glob.glob(os.path.join(dest_dir, _OODLE_DLL_GLOB)), reverse=True)
    if existing:
        return existing[0]
    # Find one to copy
    src = find_oodle_dll()
    if not src:
        return None
    # Don't copy onto itself
    if os.path.dirname(os.path.abspath(src)) == os.path.abspath(dest_dir):
        return src
    try:
        dest = os.path.join(dest_dir, os.path.basename(src))
        shutil.copy2(src, dest)
        return dest
    except OSError:
        return None


def detect_all() -> dict:
    """Convenience: run all auto-detect probes, return a single dict
    suitable for stitching into the GUI's root_paths config. Values
    are absolute paths or None when nothing was found.
    """
    return {
        'steam_root': find_steam_install_root(),
        'libraries': find_steam_libraries(),
        'nightreign': find_nightreign_install(),
        'elden_ring': find_elden_ring_install(),
        'oodle_dll': find_oodle_dll(),
        'me3_binary': find_me3_binary(),
        'me3_profiles': find_me3_profiles(),
    }


# ---------------------------------------------------------------------
# ME3 (Mod Engine 3) discovery — for the one-click launch button
# ---------------------------------------------------------------------

# Canonical install paths for the me3 binary across platforms. The
# Windows installer adds me3 to PATH so shutil.which is usually enough,
# but the portable distribution and Linux setups need the fallback list.
def _me3_binary_candidates():
    """Yield candidate paths for the me3 binary based on the platform.
    Order matters — first match wins, so the list goes from 'most likely
    canonical' (installer-managed) to 'portable / less common'."""
    if sys.platform == 'win32':
        return [
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\me3\bin\me3.exe'),
            os.path.expandvars(r'%LOCALAPPDATA%\garyttierney\me3\bin\me3.exe'),
            r'C:\Program Files\me3\bin\me3.exe',
            r'C:\Program Files (x86)\me3\bin\me3.exe',
        ]
    # Linux + macOS
    return [
        os.path.expanduser('~/.local/share/me3/me3'),
        os.path.expanduser('~/.local/bin/me3'),
        os.path.expanduser('~/bin/me3'),
        '/usr/local/bin/me3',
        '/usr/bin/me3',
    ]


def find_me3_binary() -> Optional[str]:
    """Locate the me3 launcher binary.

    Search order:
      1. PATH (shutil.which) — covers the installer's auto-PATH-add case
         on every platform.
      2. Platform-specific install locations (see _me3_binary_candidates).

    Returns the full path on success, None otherwise. Designed to be
    cheap to call repeatedly — no expensive directory walks.
    """
    import shutil
    # Windows uses .exe, Unix doesn't. shutil.which handles both natively
    # if we pass the name without extension on Linux/macOS.
    for name in ('me3', 'me3.exe'):
        hit = shutil.which(name)
        if hit:
            return hit
    for cand in _me3_binary_candidates():
        if os.path.isfile(cand):
            return cand
    return None


def find_me3_profile_root() -> Optional[str]:
    """Return the directory where me3 stores user-created profiles, or
    None if it doesn't exist. me3's docs use this convention:
      Windows: %LOCALAPPDATA%/garyttierney/me3/config/profiles/
      Linux:   $HOME/.config/me3/profiles/
    """
    if sys.platform == 'win32':
        p = os.path.expandvars(
            r'%LOCALAPPDATA%\garyttierney\me3\config\profiles')
    else:
        p = os.path.expanduser('~/.config/me3/profiles')
    return p if os.path.isdir(p) else None


def find_me3_profiles() -> list:
    """Scan the standard profile directory and return a list of
    (display_name, profile_file_path) tuples for every .me3 file found.

    The display name is the parent directory of the .me3 file — this
    matches what `me3 launch -p <name>` expects when invoked with a
    bare profile name. The full path is also captured so the caller
    can pass it directly via `-p <path>` if the user moved the file
    out of the canonical location.
    """
    root = find_me3_profile_root()
    if not root:
        return []
    results = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return []
    for entry in entries:
        subdir = os.path.join(root, entry)
        if not os.path.isdir(subdir):
            continue
        try:
            files = os.listdir(subdir)
        except OSError:
            continue
        for f in files:
            if f.lower().endswith('.me3'):
                results.append((entry, os.path.join(subdir, f)))
    return results


def find_me3_profile_for_package(package_dir: str) -> Optional[str]:
    """Walk up the directory tree from package_dir looking for a .me3
    profile file. Returns the path to the first .me3 found, or None
    if none of the ancestor directories contain one.

    Rationale: the rando's me3_package_var typically points at a
    package directory deep inside an me3 profile (e.g.
    `<profiles>/nightreign-mods/packages/rando/`). Walking up from
    there finds the `.me3` file at the profile root automatically —
    we don't need to ask the user for it separately.
    """
    if not package_dir or not os.path.isdir(package_dir):
        return None
    current = os.path.abspath(package_dir)
    # Safety bound: walk at most 8 levels up. Real profile layouts
    # are rarely more than 3-4 deep; the bound prevents infinite loops
    # on broken filesystems / symlink cycles.
    for _ in range(8):
        try:
            entries = os.listdir(current)
        except OSError:
            break
        for name in sorted(entries):
            if name.lower().endswith('.me3'):
                return os.path.join(current, name)
        parent = os.path.dirname(current)
        if parent == current:
            break  # reached filesystem root
        current = parent
    return None


# ---------------------------------------------------------------------
# me3 profile scaffold (Tier 2 UX #7)
# ---------------------------------------------------------------------
# Creates a minimal but complete me3 profile directory the rando can
# immediately write into. Eliminates the "I don't have a profile yet"
# friction for new users: instead of leaving the app to set one up
# manually, the GUI offers a one-click scaffold that produces a
# .me3 TOML config plus the conventional package subdirectory layout
# (map/mapstudio, chr, event) the rando needs.

_PROFILE_README_TEMPLATE = """# {profile_name}

This is an me3 mod profile auto-generated by 4laric's Nightreign Rando.

## What's in here

- `{profile_name}.me3` — me3 profile config (TOML).
- `{package_id}/` — the actual mod package. The rando writes
  shuffled MSBs to `{package_id}/map/mapstudio/`, heritage chr files
  to `{package_id}/chr/`, and EMEVD overlays to `{package_id}/event/`.

## Using this profile

In the rando GUI, point the **me3 package** field at:

    {package_id}/

(i.e. the `{package_id}` subdir of this folder, not this folder itself).

To launch the game with this mod, click **Launch via ME3** in the
rando, or run me3 directly:

    me3 launch -p {profile_name}

## Editing the package list

If you want to add other mods alongside the rando, edit the
`[[packages]]` blocks in `{profile_name}.me3`.

See me3's documentation at https://github.com/garyttierney/me3 for
the full profile schema.
"""


def _sanitize_profile_name(name):
    """Normalize a user-provided name into a filesystem-safe slug.
    Replaces non-alphanumeric chars with hyphens, collapses runs of
    hyphens, lowercases, falls back to a sensible default if empty.
    """
    import re
    if not name:
        return 'nightreign-rando'
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', name)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug.lower() or 'nightreign-rando'


def build_me3_profile_template(profile_name,
                                 package_id='rando',
                                 game='nightreign'):
    """Pure function — generate the contents of a `.me3` config file.

    Returns the TOML-formatted text as a string. Doesn't write to disk
    (caller does that). Kept pure so unit tests can verify the format
    without touching the filesystem.

    Schema (me3 v1 profile format):
        profileVersion = "v1"
        [supports]
            game = "<game>"
        [[packages]]
            id = "<id>"
            source = "<id>"
    """
    return (
        f'# Auto-generated by 4laric\'s Nightreign Rando.\n'
        f'# See https://github.com/garyttierney/me3 for the full schema.\n'
        f'profileVersion = "v1"\n'
        f'\n'
        f'[supports]\n'
        f'game = "{game}"\n'
        f'\n'
        f'[[packages]]\n'
        f'id = "{package_id}"\n'
        f'source = "{package_id}"\n'
    )


def scaffold_me3_profile(target_dir,
                          profile_name=None,
                          package_id='rando',
                          game='nightreign'):
    """Create a minimal me3 profile in target_dir.

    target_dir:    where the profile lives. Must be empty (or not
                   exist yet — will be created). Refuses to clobber
                   a non-empty directory to avoid wiping user data.
    profile_name:  basename for the .me3 file. Falls back to the
                   target_dir's basename if not given. Sanitized via
                   _sanitize_profile_name.
    package_id:    name of the package subdirectory (also used as the
                   .me3 file's package id). Default 'rando'.
    game:          me3 game slug. Default 'nightreign'.

    Returns a dict:
        profile_dir   absolute path to the created/populated target_dir
        me3_file      path to the written .me3 config file
        package_dir   path to <target_dir>/<package_id>/
        profile_name  the (possibly-sanitized) profile name used

    Raises:
        FileExistsError  if target_dir exists AND is not empty
        OSError          on any filesystem failure (write permissions,
                         disk full, etc.)
    """
    import os
    target_dir = os.path.abspath(target_dir)

    if profile_name is None:
        profile_name = os.path.basename(target_dir) or 'nightreign-rando'
    profile_name = _sanitize_profile_name(profile_name)

    # Refuse to scaffold into a non-empty existing dir — prevents
    # accidental data loss if the user picks a folder they didn't
    # mean to. New users may not realize the consequences.
    if os.path.isdir(target_dir):
        try:
            entries = os.listdir(target_dir)
        except OSError as e:
            raise OSError(
                f"Can't read target directory {target_dir}: {e}") from e
        if entries:
            preview = ', '.join(entries[:5])
            if len(entries) > 5:
                preview += f', … (+{len(entries) - 5} more)'
            raise FileExistsError(
                f"Target directory is not empty:\n"
                f"  {target_dir}\n"
                f"Contains: {preview}\n\n"
                f"Pick an empty (or new) directory. The scaffold refuses "
                f"to clobber existing files to avoid wiping anything you "
                f"don't intend to.")
    else:
        os.makedirs(target_dir)

    me3_path = os.path.join(target_dir, f'{profile_name}.me3')
    package_dir = os.path.join(target_dir, package_id)

    # Create the conventional package subdirectories the rando uses
    for sub in ('map/mapstudio', 'chr', 'event'):
        os.makedirs(os.path.join(package_dir, sub), exist_ok=True)

    # Write the .me3 config
    content = build_me3_profile_template(profile_name, package_id, game)
    with open(me3_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # Write a README explaining what's here. Helps users who poke
    # around the folder understand the structure without leaving the
    # filesystem to consult docs.
    readme_path = os.path.join(target_dir, 'README.md')
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(_PROFILE_README_TEMPLATE.format(
            profile_name=profile_name,
            package_id=package_id,
            game=game))

    return {
        'profile_dir': target_dir,
        'me3_file': me3_path,
        'package_dir': package_dir,
        'profile_name': profile_name,
    }


# ---------------------------------------------------------------------
# CLI for manual testing
# ---------------------------------------------------------------------

def _main():
    info = detect_all()
    print('Steam install detection')
    print('=' * 60)
    print(f'Platform:          {sys.platform}')
    print(f'Steam root:        {info["steam_root"] or "(not found)"}')
    libs = info['libraries']
    if libs:
        print(f'Libraries ({len(libs)}):')
        for p in libs:
            print(f'  {p}')
    else:
        print(f'Libraries:         (none)')
    print()
    print(f'Nightreign:        {info["nightreign"] or "(not found)"}')
    print(f'Elden Ring:        {info["elden_ring"] or "(not found)"}')
    print(f'Oodle DLL:         {info["oodle_dll"] or "(not found)"}')
    print(f'me3 binary:        {info["me3_binary"] or "(not found)"}')
    profiles = info.get('me3_profiles', [])
    if profiles:
        print(f'me3 profiles ({len(profiles)}):')
        for name, path in profiles:
            print(f'  {name:30s} → {path}')
    else:
        print('me3 profiles:      (none found)')
    if not info['nightreign'] and not info['elden_ring']:
        print()
        print('Neither game found. You can still run the GUI by browsing')
        print('to the install path manually.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(_main())
