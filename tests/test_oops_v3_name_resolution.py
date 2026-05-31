"""Static lint of shuffle_msb_v3 (and a few other hot paths) for bare-name
references that don't resolve in scope. Cheap regression guard for the
v0.27.46 NameError ("msb_name" used where only "msb_base" is defined inside
shuffle_msb_v3) — the determinism tests run through simulate_engine.py,
which has its own `msb_name` as the iteration variable, so they didn't
catch the typo when it shipped in oops_v3.py:shuffle_msb_v3.

Approach: parse oops_v3.py with `ast`, walk the body of the target
function, collect every Name(Load) reference, and verify it resolves to
one of:
  - the function's own parameters
  - a local assignment anywhere in the function body
  - a module-level name defined in oops_v3
  - a Python builtin

If a bare Name doesn't resolve, raise a clear failure with the line
number. Fast (single AST parse), needs no MSB binaries.

This kind of typo class is exactly what a linter (pyflakes / ruff F821)
would catch, but the project doesn't currently gate on those. The test
below is a project-local equivalent for the functions that matter most.
"""
import ast
import builtins
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OOPS_V3 = os.path.join(_ROOT, "oops_v3.py")


@pytest.fixture(scope="module")
def oops_v3_module_globals():
    """All names defined at module level in oops_v3.py. Parsed
    statically — no execution — so this works even if oops_v3 can't be
    imported in the test environment for other reasons."""
    with open(_OOPS_V3, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=_OOPS_V3)
    names = set()
    for node in tree.body:
        # Module-level imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        # Module-level function / class defs
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
            names.add(node.name)
        # Module-level assignments
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                for n in ast.walk(tgt):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            names.add(node.target.id)
        # Module-level `try:` may wrap imports/defs — recurse one level.
        elif isinstance(node, ast.Try):
            for sub in node.body + node.orelse + node.finalbody:
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        names.add(alias.asname or
                                  alias.name.split(".")[0])
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    for tgt in sub.targets:
                        for n in ast.walk(tgt):
                            if isinstance(n, ast.Name):
                                names.add(n.id)
    return names


@pytest.fixture(scope="module")
def oops_v3_tree():
    with open(_OOPS_V3, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=_OOPS_V3)


def _find_function(tree, name):
    """Top-level FunctionDef with this name, or None."""
    for node in tree.body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name):
            return node
    return None


def _collect_function_locals(fn_node):
    """Every name that's a parameter or an assignment target anywhere
    inside the function (including nested for/with/comprehensions).
    Walrus targets count. Nested defs are recorded by their own name
    (the body of a nested def is treated as its own scope and walked
    when we lint that function separately if needed)."""
    locals_ = set()
    # Parameters
    args = fn_node.args
    for a in (args.posonlyargs + args.args + args.kwonlyargs):
        locals_.add(a.arg)
    if args.vararg:
        locals_.add(args.vararg.arg)
    if args.kwarg:
        locals_.add(args.kwarg.arg)
    # Walk the body
    for n in ast.walk(fn_node):
        if isinstance(n, ast.Assign):
            for tgt in n.targets:
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name):
                        locals_.add(sub.id)
                    elif isinstance(sub, ast.Tuple):
                        for elt in sub.elts:
                            if isinstance(elt, ast.Name):
                                locals_.add(elt.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            locals_.add(n.target.id)
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            locals_.add(n.target.id)
        elif isinstance(n, ast.For):
            for sub in ast.walk(n.target):
                if isinstance(sub, ast.Name):
                    locals_.add(sub.id)
        elif isinstance(n, ast.With):
            for item in n.items:
                if item.optional_vars is not None:
                    for sub in ast.walk(item.optional_vars):
                        if isinstance(sub, ast.Name):
                            locals_.add(sub.id)
        elif isinstance(n, ast.NamedExpr):  # walrus :=
            if isinstance(n.target, ast.Name):
                locals_.add(n.target.id)
        elif isinstance(n, (ast.comprehension,)):
            for sub in ast.walk(n.target):
                if isinstance(sub, ast.Name):
                    locals_.add(sub.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            locals_.add(n.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            if hasattr(n, 'name'):
                locals_.add(n.name)
        elif isinstance(n, ast.Import):
            for alias in n.names:
                locals_.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for alias in n.names:
                locals_.add(alias.asname or alias.name)
    return locals_


def _collect_loaded_names(fn_node):
    """Every Name node read (Load context) in the function, with its
    line number. Skips names inside nested function/class defs — those
    have their own scopes that close over outer names anyway."""
    out = []
    # We want to skip nested function bodies. Walk manually.
    def visit(node, inside_nested):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.Lambda))
                and node is not fn_node):
            # Recurse into defaults / decorator_list but not body
            for d in getattr(node, 'decorator_list', []):
                visit(d, inside_nested)
            for d in getattr(node.args, 'defaults', []) if hasattr(
                    node, 'args') else []:
                visit(d, inside_nested)
            return
        if isinstance(node, ast.ClassDef) and node is not fn_node:
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            out.append((node.id, node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, inside_nested)
    visit(fn_node, False)
    return out


# Functions in oops_v3.py to lint. Limited to the hot decision paths
# where the v0.27.46 NameError class would do the most damage if it
# reappeared. Not a full module lint — keeps the test cheap and the
# diagnostic specific.
FUNCTIONS_TO_LINT = [
    "shuffle_msb_v3",
    "pick_target_cp",
    "_cmd_shuffle_v3_impl",
]


@pytest.mark.parametrize("fn_name", FUNCTIONS_TO_LINT)
def test_function_has_no_undefined_names(fn_name, oops_v3_tree,
                                          oops_v3_module_globals):
    """Static lint: every bare Name(Load) inside the function resolves
    to a parameter, a local assignment, a module global, or a builtin.

    Regression guard for v0.27.46: I shipped Phase 2 with `msb_name`
    referenced where only `msb_base` was defined in shuffle_msb_v3,
    and the determinism tests didn't catch it because they run
    through dev/simulate_engine.py (a different module that DOES have
    its own `msb_name` as the iteration variable). The bug only fired
    when production hit the real MSB-binary path.
    """
    fn = _find_function(oops_v3_tree, fn_name)
    assert fn is not None, (
        f"{fn_name} not found at module top level of oops_v3.py — "
        f"either renamed or moved; update FUNCTIONS_TO_LINT.")
    locals_ = _collect_function_locals(fn)
    builtin_names = set(dir(builtins))
    refs = _collect_loaded_names(fn)
    bad = []
    seen = set()
    for name, lineno in refs:
        if name in locals_ or name in oops_v3_module_globals or name in builtin_names:
            continue
        # De-dupe by (name, lineno) so the failure message is readable
        if (name, lineno) in seen:
            continue
        seen.add((name, lineno))
        bad.append((name, lineno))
    if bad:
        sample = "\n  ".join(
            f"line {ln}: '{n}'" for n, ln in bad[:10])
        pytest.fail(
            f"{fn_name} references {len(bad)} undefined name(s):\n  "
            f"{sample}\n"
            f"Each must be a parameter, local assignment, oops_v3 "
            f"module global, or builtin. Common cause: typo (e.g. "
            f"msb_name vs msb_base) or a name moved into a nested "
            f"block that's no longer in scope at the reference site.")


def test_no_msb_name_outside_known_safe_contexts():
    """Belt-and-braces guard: `msb_name` should NOT appear anywhere
    in shuffle_msb_v3, because that function uses `msb_base`.
    `msb_name` is fine elsewhere (the iteration variable in
    simulate_engine.py and the `slot_msb_name` parameter on
    pick_target_cp), but the engine's own per-MSB processing standardises
    on msb_base. This is a literal grep — fast and dumb on purpose."""
    with open(_OOPS_V3, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=_OOPS_V3)
    fn = _find_function(tree, "shuffle_msb_v3")
    assert fn is not None
    # Slice the source for just the function body lines.
    lines = src.splitlines(keepends=True)
    fn_src = "".join(lines[fn.lineno - 1:fn.end_lineno])
    # Match bare `msb_name` token — not `slot_msb_name`, not in a comment.
    import re
    pattern = re.compile(r"(?<![_A-Za-z0-9])msb_name(?![_A-Za-z0-9])")
    offending = []
    for i, line in enumerate(fn_src.splitlines(), start=fn.lineno):
        # Strip trailing comment to avoid false positives in commentary.
        code = line.split('#', 1)[0]
        if pattern.search(code):
            offending.append((i, line.rstrip()))
    assert not offending, (
        f"`msb_name` appears in shuffle_msb_v3 body — should be "
        f"`msb_base`. Offending lines:\n  " +
        "\n  ".join(f"{ln}: {src}" for ln, src in offending))
