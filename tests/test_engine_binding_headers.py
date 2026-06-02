"""Tests guarding binding-header integrity across engine/.

The extraction pattern: each engine function `f(ns, ...)` opens with a
binding header that reads its module-global dependencies from the
`ns` dict (which is oops_v3's globals() at the call site):

    def f(ns, ...):
        NAME1 = ns['NAME1']
        NAME2 = ns['NAME2']
        ...

If NAME1 is not actually a global on oops_v3 — say it's a walrus-only
local that was misclassified by the extraction generator — then the
binding-header read raises KeyError as soon as f is called, before
the function body even starts.

This bit us in v0.28.x on shuffler.py with `_effective_nb_target_cp`
and `_effective_scope`, both walrus-only locals. Production runs
crashed at the start of shuffle_msb_v3. The tests in this file lock
against that class of regression for every engine module.

Two checks per module:
  1. Every `NAME = ns['NAME']` pre-load resolves on oops_v3.
  2. Every pre-load LHS matches its ns subscript key (typo guard).
"""
import ast
import io
import os
import re
import sys
import contextlib

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIR = os.path.join(REPO_ROOT, 'engine')

sys.path.insert(0, REPO_ROOT)


@pytest.fixture(scope='module')
def oops_v3_names():
    """All public + private attribute names on the oops_v3 module
    after load_data() has populated derived state."""
    with contextlib.redirect_stdout(io.StringIO()):
        import oops_v3
        oops_v3.load_data()
    return set(dir(oops_v3))


def _engine_python_files():
    """Yield path to every engine/*.py file (top-level only — the
    pack_loaders/ subpackage has its own conventions and is exercised
    by its own tests)."""
    for fname in sorted(os.listdir(ENGINE_DIR)):
        if not fname.endswith('.py') or fname.startswith('__'):
            continue
        yield fname, os.path.join(ENGINE_DIR, fname)


def _ast_preloads(path):
    """Find all `X = ns['X']` pre-loads in `path` using AST so we don't
    false-match commented-out lines or pattern variants. Returns
    list of (line_no, name)."""
    with open(path) as f:
        src = f.read()
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1: continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name): continue
        val = node.value
        if not isinstance(val, ast.Subscript): continue
        if not (isinstance(val.value, ast.Name) and val.value.id == 'ns'):
            continue
        sl = val.slice
        if isinstance(sl, ast.Index):  # 3.8 compat
            sl = sl.value
        if not (isinstance(sl, ast.Constant) and isinstance(sl.value, str)):
            continue
        out.append((node.lineno, tgt.id, sl.value))
    return out


def test_engine_files_exist():
    files = list(_engine_python_files())
    assert files, 'No engine/*.py files found — has the layout changed?'


@pytest.mark.parametrize('fname,path', list(_engine_python_files()))
def test_binding_header_preloads_resolve_on_oops_v3(fname, path, oops_v3_names):
    """For each engine module: every `NAME = ns['NAME']` pre-load must
    refer to a name that actually exists on oops_v3. A missing name
    means the binding header KeyErrors at call time.

    Regression: v0.28.x shuffler.py had _effective_nb_target_cp and
    _effective_scope pre-loaded — both walrus-only locals, never
    module-globals on oops_v3 — causing every shuffle_msb_v3 call to
    crash.
    """
    preloads = _ast_preloads(path)
    missing = [(line, lhs) for line, lhs, key in preloads
               if key not in oops_v3_names]
    assert not missing, (
        f'In engine/{fname}, these pre-loaded names are not module '
        f'globals on oops_v3 — binding header will KeyError at call '
        f'time. Either the name is a walrus-only local (remove the '
        f'pre-load) or there is a missing definition on oops_v3:\n  ' +
        '\n  '.join(f'line {line}: ns[{name!r}]' for line, name in missing))


@pytest.mark.parametrize('fname,path', list(_engine_python_files()))
def test_binding_header_lhs_matches_subscript_key(fname, path):
    """For each engine module: in every `LHS = ns['KEY']` pre-load,
    LHS must equal KEY. A mismatch is a typo bug — the binding header
    pulls the wrong global into the local name.

    This is a static-only check; the previous test catches the runtime
    KeyError consequence, but a mismatched pair where BOTH names exist
    on oops_v3 (e.g. `V3_FOO = ns['V3_BAR']`) would NOT KeyError but
    would silently swap the values. That's the bug this test catches.
    """
    preloads = _ast_preloads(path)
    mismatches = [(line, lhs, key) for line, lhs, key in preloads
                  if lhs != key]
    assert not mismatches, (
        f'In engine/{fname}, these pre-loads have mismatched LHS vs '
        f'ns subscript — likely typo:\n  ' +
        '\n  '.join(f'line {line}: {lhs} = ns[{key!r}]'
                    for line, lhs, key in mismatches))
