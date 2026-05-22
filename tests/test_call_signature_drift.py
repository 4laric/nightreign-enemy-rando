"""Static guard against call-signature drift on the randomize path.

Twice now a kwarg has been added on one side of a call boundary without
the other side being updated, crashing a run mid-pipeline with
"unexpected keyword argument ..." (mount_rider_swap, then the retired
cluster triad). Both were invisible until a user clicked Randomize.

This test parses the source with `ast` — no engine import, no run — and
asserts that every kwarg passed across the two boundaries on the DCX
randomize path is actually accepted by the callee:

    oops_rando_gui._worker  --rando_pipeline-->  dcx_batch.rando_pipeline
    dcx_batch.rando_pipeline --cmd_shuffle_v3--> oops_v3.cmd_shuffle_v3

If a callee declares **kwargs the check is skipped for that boundary
(anything is accepted). Keep this green: when you add a flag, thread it
through every layer in the same commit.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _accepted_kwargs(path, fname):
    """(set of accepted keyword names, has_var_keyword) for a top-level def."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8', errors='replace'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            a = node.args
            names = {p.arg for p in a.args} | {p.arg for p in a.kwonlyargs}
            return names, (a.kwarg is not None)
    raise AssertionError(f"{fname} not found in {path}")


def _call_kwargs(path, callee, inside=None):
    """Keyword names passed to `callee` calls, optionally only within `inside`."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8', errors='replace'))
    scopes = [tree]
    if inside:
        scopes = [n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == inside]
        assert scopes, f"{inside} not found in {path}"
    out = set()
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.Call):
                f = node.func
                name = (f.attr if isinstance(f, ast.Attribute)
                        else f.id if isinstance(f, ast.Name) else None)
                if name == callee:
                    for kw in node.keywords:
                        if kw.arg is not None:
                            out.add(kw.arg)
    return out


def _dict_var_keys(path, varname):
    """Keys of a `varname = dict(...)` assignment."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8', errors='replace'))
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == varname for t in node.targets):
            if isinstance(node.value, ast.Call):
                keys |= {kw.arg for kw in node.value.keywords if kw.arg}
    return keys


def test_rando_pipeline_to_cmd_shuffle_v3():
    """Every kwarg dcx_batch.rando_pipeline passes to cmd_shuffle_v3 must exist."""
    accepted, has_var_kw = _accepted_kwargs('oops_v3.py', 'cmd_shuffle_v3')
    if has_var_kw:
        return
    passed = _call_kwargs('dcx_batch.py', 'cmd_shuffle_v3', inside='rando_pipeline')
    unaccepted = passed - accepted
    assert not unaccepted, (
        f"rando_pipeline passes kwargs cmd_shuffle_v3 does not accept: "
        f"{sorted(unaccepted)}")


def test_gui_to_rando_pipeline():
    """Every kwarg the GUI passes to rando_pipeline must exist on its signature."""
    accepted, has_var_kw = _accepted_kwargs('dcx_batch.py', 'rando_pipeline')
    if has_var_kw:
        return
    # GUI passes explicit kwargs in the call plus the engine_kwargs dict, splatted.
    passed = _call_kwargs('oops_rando_gui.py', 'rando_pipeline')
    passed |= _dict_var_keys('oops_rando_gui.py', 'engine_kwargs')
    passed.discard('seed')  # consumed positionally on the non-DCX branch
    unaccepted = passed - accepted
    assert not unaccepted, (
        f"GUI passes kwargs rando_pipeline does not accept: {sorted(unaccepted)}")


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    test_rando_pipeline_to_cmd_shuffle_v3()
    test_gui_to_rando_pipeline()
    print("call-signature drift checks: clean")
