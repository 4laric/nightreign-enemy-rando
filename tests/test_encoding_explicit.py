"""Regression tests for the v0.26.3 Windows codepage hotfix.

When Python's `open()` is called without `encoding=`, it uses the
platform default — UTF-8 on Linux/macOS, cp1252 on Windows. If a
JSON/text file contains non-ASCII bytes (em-dashes, accented chars,
etc.) the cp1252 reader hits UnicodeDecodeError.

Bug reproduction: v0.26.x size-correction annotations added em-dashes
to mmv_imports.json. v0.26.1's GUI tried to read mmv_imports.json
without specifying encoding, which worked on dev (Linux) but threw
'charmap codec can't decode byte 0x9d in position 220' on user
machines running Windows.

These tests ensure every shipped Python file's `open()` calls on text
files specify encoding= explicitly. AST-walks the source files rather
than running them, so it's fast and platform-agnostic.
"""
import ast
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Top-level Python files that ship in the release bundle. Mirrors
# scripts/build_release.py INCLUDE_FILES. Any open() in these MUST
# specify encoding= (for text modes) since end users may run them
# on Windows where cp1252 is the default.
SHIPPED_FILES = [
    'oops_rando_gui.py',
    'check_setup.py',
    'oops_v3.py',
    'oops_all_anyone.py',
    'swap_compat.py',
    'dcx.py',
    'dcx_batch.py',
    'emevd_patch.py',
    'check_patched_deep.py',
    'diff_vanilla_vs_patched.py',
    'dump_vanilla_fmg.py',
]


# Worker-script run in a SUBPROCESS to do the AST walk. ast.parse() on a
# 500 KB module (oops_rando_gui.py / oops_v3.py) builds a large tree; late
# in a full-suite run — with the engine's post-load state resident and
# Windows commit charge nearly exhausted — the parser's arena allocation
# intermittently dies with a native access violation and takes the whole
# pytest process down. A short-lived subprocess gets a clean address
# space and lets the OS reclaim everything on exit, making the test
# insensitive to the parent process's memory state.
_WORKER = r'''
import ast, json, sys

def find_text_opens_without_encoding(source):
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == 'open'):
            continue
        if any(kw.arg == 'encoding' for kw in node.keywords):
            continue
        if len(node.args) >= 2:
            mode = node.args[1]
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                if 'b' in mode.value:
                    continue
            else:
                continue
        bad.append([node.lineno, ast.unparse(node)
                    if hasattr(ast, 'unparse')
                    else f'open() @ line {node.lineno}'])
    return bad

src = sys.stdin.buffer.read().decode('utf-8')
json.dump(find_text_opens_without_encoding(src), sys.stdout)
'''


def find_text_opens_without_encoding(source):
    """Walk AST, return list of (lineno, call_repr) for every open()
    Call that's text-mode AND lacks encoding= kwarg.

    Runs in a subprocess — see _WORKER comment above."""
    import json
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, '-c', _WORKER],
        input=source.encode('utf-8'),
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f'AST worker subprocess failed (rc={proc.returncode}): '
            f'{proc.stderr.decode("utf-8", "replace")[:500]}')
    return [tuple(pair) for pair in json.loads(proc.stdout.decode('utf-8'))]
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call): continue
        if not (isinstance(node.func, ast.Name) and node.func.id == 'open'):
            continue
        # Skip if encoding= is already specified
        if any(kw.arg == 'encoding' for kw in node.keywords):
            continue
        # Check mode arg (2nd positional). If absent → defaults to 'r' (text).
        # If present and constant string with 'b' → binary, skip.
        # If present and not a constant → can't determine, skip to be safe.
        if len(node.args) >= 2:
            mode = node.args[1]
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                if 'b' in mode.value:
                    continue  # binary mode is fine without encoding
            else:
                continue  # computed mode — skip
        # Text-mode open without encoding=. Report.
        bad.append((node.lineno, ast.unparse(node)
                    if hasattr(ast, 'unparse') else f'open() @ line {node.lineno}'))
    return bad


@pytest.mark.parametrize('filename', SHIPPED_FILES)
def test_all_text_opens_specify_encoding(filename):
    """Every text-mode open() in a shipped file must specify encoding=.

    This prevents the v0.26.1→v0.26.3 Windows cp1252 hang where
    mmv_imports.json couldn't be read on user machines because the
    file had em-dashes (0xE2 0x80 0x94 in UTF-8 → bytes that cp1252
    can't decode)."""
    path = os.path.join(REPO_ROOT, filename)
    if not os.path.isfile(path):
        pytest.skip(f"{filename} not present in repo")
    with open(path, encoding='utf-8') as f:
        src = f.read()
    bad = find_text_opens_without_encoding(src)
    assert not bad, (
        f"{filename}: {len(bad)} text-mode open() call(s) missing "
        f"encoding= kwarg. These will fail on Windows when reading "
        f"files with non-ASCII content (UTF-8 em-dashes, accented "
        f"chars, etc.). Sites:\n  " +
        "\n  ".join(f"line {ln}: {repr_}" for ln, repr_ in bad[:10]))


def test_mmv_imports_has_non_ascii():
    """Sanity check: mmv_imports.json actually contains the non-ASCII
    bytes that triggered the original bug, so the regression test
    above isn't trivially passing on a clean-content file."""
    path = os.path.join(REPO_ROOT, 'data', 'mmv_imports.json')
    with open(path, 'rb') as f:
        content = f.read()
    # Should contain at least one byte outside the ASCII range (0x80+)
    non_ascii = [i for i, b in enumerate(content) if b >= 0x80]
    assert non_ascii, (
        'mmv_imports.json has no non-ASCII bytes — either the v0.26.x '
        'size-correction annotations were stripped, or the regression '
        'test is trivially passing. Re-add the test data dependency.')


def test_cp1252_fails_to_read_mmv_imports():
    """Direct proof that the original bug exists: reading mmv_imports.json
    as cp1252 (Windows default) raises UnicodeDecodeError."""
    path = os.path.join(REPO_ROOT, 'data', 'mmv_imports.json')
    with pytest.raises(UnicodeDecodeError):
        with open(path, encoding='cp1252') as f:
            f.read()


def test_utf8_succeeds_to_read_mmv_imports():
    """And the fix: reading the same file with encoding='utf-8' works."""
    path = os.path.join(REPO_ROOT, 'data', 'mmv_imports.json')
    with open(path, encoding='utf-8') as f:
        content = f.read()
    assert len(content) > 1000, f"unexpectedly short: {len(content)}"
