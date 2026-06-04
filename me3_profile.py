"""me3_profile.py — discover and edit me3 mod profile (.me3) files.

The .me3 profile is a TOML manifest that tells me3 which packages and natives
to load when launching the game (https://me3.help/en/latest/configuration-reference/).
Without a [[packages]] entry pointing at our deploy directory, me3 launches
without our mod loaded — even if our regulation.bin, chr/, etc. files are
sitting in the package dir on disk.

Provides:
    find_profile_for_package(package_dir) -> str | None
        Best-effort search for the .me3 file that owns a given package dir.
        Looks at the package's parent dir and grandparent dir (typical me3
        layouts: profiles/<name>/<name>.me3 next to profiles/<name>/<pkg>/,
        or profiles/<name>.me3 next to profiles/<pkg>/).

    ensure_package_registered(profile_path, package_dir) -> dict
        Read the .me3 file. If no [[packages]] entry already resolves to
        package_dir, append one. Append-only: doesn't reorder, reformat,
        rewrite, or drop comments from existing entries. Returns
        {'action': 'added' | 'noop' | 'error', 'detail': str}.

Reads via tomllib (3.11+ stdlib) when available, falls back to tomli, falls
back to a regex scan for the duplicate check. Writes are always raw text
appends, so the writer has no TOML-lib dependency.
"""

import os
import re


# --- profile discovery ------------------------------------------------------


def find_profile_for_package(package_dir):
    """Return the absolute path of the .me3 file that owns this package dir,
    or None.

    Search order:
      1. Sibling of the package — same dir contains exactly one .me3 file.
      2. Sibling of the package — same dir contains multiple .me3 files;
         prefer the one whose stem matches the parent dir's name.
      3. One level up from the package (so profiles/<name>/<pkg>/ finds
         profiles/<name>.me3).
    """
    if not package_dir:
        return None
    pkg = os.path.abspath(package_dir)
    if not os.path.isdir(pkg):
        return None
    parent = os.path.dirname(pkg)
    grandparent = os.path.dirname(parent)
    # Hit a directory boundary at the root — bail.
    for cand_dir in (parent, grandparent):
        if not cand_dir or not os.path.isdir(cand_dir):
            continue
        try:
            names = os.listdir(cand_dir)
        except OSError:
            continue
        me3s = [n for n in names if n.lower().endswith('.me3')
                                  and os.path.isfile(os.path.join(cand_dir, n))]
        if not me3s:
            continue
        if len(me3s) == 1:
            return os.path.join(cand_dir, me3s[0])
        # Multiple candidates — prefer stem matching the parent's basename.
        # me3's CLI convention is `profiles/<name>/<name>.me3`, so the
        # parent dir name is usually the canonical pick.
        target_stem = os.path.basename(cand_dir).lower()
        for m in me3s:
            if os.path.splitext(m)[0].lower() == target_stem:
                return os.path.join(cand_dir, m)
        # Last resort — alphabetical first, for determinism.
        return os.path.join(cand_dir, sorted(me3s)[0])
    return None


# --- editing ----------------------------------------------------------------


def _load_toml(profile_path):
    """Parse the profile via tomllib (3.11+) or tomli. Returns the parsed
    dict, or None if neither library is available (caller should fall back
    to a text scan)."""
    try:
        import tomllib  # 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # 3.10 backport
        except ImportError:
            return None
    with open(profile_path, 'rb') as f:
        return tomllib.load(f)


def _paths_equal(a, b):
    """Compare two filesystem paths for identity. Normalizes separators
    and case (Windows is case-insensitive in practice). Resolves symlinks
    on a best-effort basis; falls back to normpath if realpath fails."""
    try:
        ra = os.path.realpath(a)
        rb = os.path.realpath(b)
        if os.path.normcase(ra) == os.path.normcase(rb):
            return True
    except OSError:
        pass
    return (os.path.normcase(os.path.normpath(a))
            == os.path.normcase(os.path.normpath(b)))


def _is_registered_toml(parsed, profile_dir, target_pkg_abs):
    """Check whether the parsed profile already has a [[packages]] entry
    pointing at target_pkg_abs."""
    for pkg in parsed.get('packages', []):
        existing = pkg.get('path', '')
        if not existing:
            continue
        if os.path.isabs(existing):
            existing_abs = existing
        else:
            existing_abs = os.path.join(profile_dir, existing)
        if _paths_equal(existing_abs, target_pkg_abs):
            return True
    return False


_PATH_RE = re.compile(
    r"^\s*path\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)


def _is_registered_text(profile_path, profile_dir, target_pkg_abs):
    """Fallback duplicate check when no TOML library is available.
    Regex-scans for path = '...' lines and resolves each against
    profile_dir. Best-effort: misses multi-line strings and other TOML
    edge cases, but those are vanishingly rare in real .me3 files."""
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return False
    for m in _PATH_RE.finditer(text):
        existing = m.group(1)
        if not existing:
            continue
        if os.path.isabs(existing):
            existing_abs = existing
        else:
            existing_abs = os.path.join(profile_dir, existing)
        if _paths_equal(existing_abs, target_pkg_abs):
            return True
    return False


def ensure_package_registered(profile_path, package_dir):
    """Append a [[packages]] entry to profile_path for package_dir if one
    isn't already present. Append-only — never rewrites existing entries.

    Returns:
        {'action': 'added',  'detail': '<written path>'} on append
        {'action': 'noop',   'detail': 'already registered'} when present
        {'action': 'error',  'detail': '<reason>'} on any failure

    The written path is computed relative to the .me3 file's directory
    when both paths live on the same drive (the me3 convention), else
    absolute. Forward slashes always — TOML single-quoted strings don't
    process backslash escapes, but forward slashes work everywhere and
    keep the file human-readable.
    """
    if not profile_path or not os.path.isfile(profile_path):
        return {'action': 'error',
                'detail': f'profile not found: {profile_path}'}
    if not package_dir or not os.path.isdir(package_dir):
        return {'action': 'error',
                'detail': f'package dir not found: {package_dir}'}

    profile_dir = os.path.dirname(os.path.abspath(profile_path))
    pkg_abs = os.path.abspath(package_dir)

    # Duplicate check: prefer TOML parser, fall back to text scan.
    parsed = None
    try:
        parsed = _load_toml(profile_path)
    except Exception as e:
        return {'action': 'error',
                'detail': f'failed to parse {profile_path}: {e}'}
    if parsed is not None:
        if _is_registered_toml(parsed, profile_dir, pkg_abs):
            return {'action': 'noop', 'detail': 'already registered'}
    else:
        if _is_registered_text(profile_path, profile_dir, pkg_abs):
            return {'action': 'noop', 'detail': 'already registered'}

    # Compute the path to write. Relative if same drive, absolute otherwise.
    try:
        rel = os.path.relpath(pkg_abs, profile_dir).replace('\\', '/')
        if not rel.endswith('/'):
            rel += '/'
        path_value = rel
    except ValueError:
        # Different Windows drives — relpath raises.
        path_value = pkg_abs.replace('\\', '/')
        if not path_value.endswith('/'):
            path_value += '/'

    # Read trailing bytes so we know whether to emit a leading newline.
    try:
        with open(profile_path, 'rb') as f:
            try:
                f.seek(-1, os.SEEK_END)
                last = f.read(1)
            except OSError:
                last = b''
    except OSError as e:
        return {'action': 'error',
                'detail': f'failed to read {profile_path}: {e}'}

    leading = b'' if last in (b'\n', b'\r', b'') else b'\n'
    block = (leading + b'\n[[packages]]\n'
             + f"path = '{path_value}'\n".encode('utf-8'))

    try:
        with open(profile_path, 'ab') as f:
            f.write(block)
    except OSError as e:
        return {'action': 'error',
                'detail': f'failed to write {profile_path}: {e}'}

    return {'action': 'added', 'detail': path_value}


# --- bonus: supports-game sanity check --------------------------------------


_NR_GAME_NAMES = {'nightreign', 'nr', 'nightrein'}


def supports_nightreign(profile_path):
    """Return True if the .me3 declares a [[supports]] entry for NR.
    Tri-valued: True (yes), False (no), None (couldn't check — no TOML lib
    or parse error). Callers should treat None as a non-fatal warning."""
    parsed = None
    try:
        parsed = _load_toml(profile_path)
    except Exception:
        return None
    if parsed is None:
        return None
    for s in parsed.get('supports', []):
        game = (s.get('game') or '').lower()
        if game in _NR_GAME_NAMES:
            return True
    return False


# --- full-profile generation (used when the tool OWNS the .me3) --------------
#
# Unlike ensure_package_registered (append-only, safe for a user's hand-authored
# profile), these regenerate the WHOLE file. Use only for the shipped profile's
# own .me3 at a known location — never point write_profile_me3 at a profile the
# user authored, as it replaces the entire file. Regenerating (rather than
# appending) is what lets the DLL-mods list support removal as well as addition:
# the .me3 always reflects the current configured set, the same way thefifthmatt
# regenerates its profile on each run.


def _me3_path_value(p):
    """Path as a me3 TOML value body: forward slashes (single-quoted TOML
    strings don't process backslashes; forward slashes work on Windows in me3
    and keep the file readable)."""
    return str(p).replace('\\', '/')


def build_me3_text(package_path='package/', *, game='nightreign',
                   package_id=None, natives=(), savefile=None, header_lines=()):
    """Generate the full text of a .me3 profile.

    package_path : value for the package's `path` (e.g. 'package/' or '.').
    game         : value for the [[supports]] game key.
    package_id   : optional `id` for the package (a name, not a path).
    natives      : iterable of DLL paths -> one [[natives]] block each
                   (absolute, or relative to the .me3). Blank entries skipped.
    savefile     : optional alt-save filename (e.g. 'NR_rando.sl2'); omitted
                   when falsy. (me3 ignores it if a DLL mod such as Seamless
                   Co-op configures its own save file.)
    header_lines : optional comment lines emitted at the top.

    Path values are single-quoted, which is required so Windows DLL paths
    don't need backslash escaping.
    """
    out = []
    for h in header_lines:
        out.append(f'# {h}' if h else '#')
    out.append('profileVersion = "v1"')
    if savefile:
        out.append(f'savefile = "{savefile}"')
    out.append('')
    out.append('[[supports]]')
    out.append(f'game = "{game}"')
    out.append('')
    out.append('[[packages]]')
    if package_id:
        out.append(f'id = "{package_id}"')
    out.append(f"path = '{_me3_path_value(package_path)}'")
    for dll in natives:
        d = (dll or '').strip()
        if not d:
            continue
        out.append('')
        out.append('[[natives]]')
        out.append(f"path = '{_me3_path_value(d)}'")
    return '\n'.join(out) + '\n'


def write_profile_me3(profile_path, package_path='package/', *,
                      game='nightreign', package_id=None, natives=(),
                      savefile=None, header_lines=()):
    """Overwrite `profile_path` with a freshly generated .me3.

    For a .me3 the tool OWNS (the shipped profile's own file at a known path).
    Replaces the whole file — never point this at a user-authored profile.
    Returns {'action': 'written'|'error', 'detail': str, 'natives': int}.
    """
    try:
        text = build_me3_text(package_path, game=game, package_id=package_id,
                              natives=natives, savefile=savefile,
                              header_lines=header_lines)
        parent = os.path.dirname(os.path.abspath(profile_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(profile_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        n = sum(1 for d in natives if (d or '').strip())
        return {'action': 'written', 'detail': profile_path, 'natives': n}
    except OSError as e:
        return {'action': 'error', 'detail': str(e), 'natives': 0}
