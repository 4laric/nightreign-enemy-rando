"""audit_engine_globals.py — audit every extracted engine/*.py
function for missing pre-loads.

The extraction pattern: each function `f(ns, ...)` is bound to its
oops_v3 globals via a binding header at the top of the body:

    def f(ns, ...):
        # read deps from ns into locals
        NAME1 = ns['NAME1']
        NAME2 = ns['NAME2']
        ...
        # function body uses NAME1, NAME2 as locals

If the body references a name that:
  (a) is NOT in the function's binding header,
  (b) is NOT a function argument,
  (c) is NOT locally assigned anywhere (Store / AugStore / For / comprehension),
  (d) is NOT a Python builtin,
  (e) is NOT a module-level name in the engine module (imports, top-level defs),

then at runtime the reference falls through to engine module globals,
which don't have it, and Python raises NameError.

This audit finds those gaps statically.

Caveats:
- Comprehension targets are scoped to Python's comprehension scope; we
  treat them as local for the enclosing function so we don't false-
  positive on them.
- Nested functions get their own scope; we visit them as separate units.
- We don't recurse into class bodies (the engine has none).
"""
from __future__ import annotations

import ast
import builtins
import os
import re
import sys
import io
import contextlib


ROOT = '/home/claude/nightreign-enemy-rando'
ENGINE_DIR = os.path.join(ROOT, 'engine')

sys.path.insert(0, ROOT)
with contextlib.redirect_stdout(io.StringIO()):
    import oops_v3

OOPS_NAMES = set(dir(oops_v3))
BUILTIN_NAMES = set(dir(builtins))


def module_level_names(tree: ast.Module) -> set[str]:
    """Names defined at module level via def/class/Import/ImportFrom/
    Assign. Used to filter out same-module references that don't need
    a binding header entry."""
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out.add(tgt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                out.add(node.target.id)
        # Skip If, Try, etc. — keep it conservative
    return out


def collect_targets(node) -> set[str]:
    """Return all names assigned to in a single target spec
    (handles tuple/list unpacking, starred, etc.)."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        out = set()
        for elt in node.elts:
            out |= collect_targets(elt)
        return out
    if isinstance(node, ast.Starred):
        return collect_targets(node.value)
    return set()


class FunctionScope:
    """Collect everything needed to audit one function:
    - arg names
    - locally bound names (assignments, walrus, for-loops, with/as,
      except-as, comprehension targets, nested def/class names)
    - referenced names (Load context)
    - binding-header pre-loads (NAME = ns['NAME'])
    """
    def __init__(self):
        self.args: set[str] = set()
        self.locals: set[str] = set()
        self.refs: set[str] = set()
        self.preloads: set[str] = set()
        self.preload_lines: dict[str, int] = {}


def analyze_function(fn: ast.FunctionDef, source_lines: list[str]) -> FunctionScope:
    sc = FunctionScope()
    # Args
    args = fn.args
    for a in (args.posonlyargs or []) + args.args + (args.kwonlyargs or []):
        sc.args.add(a.arg)
    if args.vararg:
        sc.args.add(args.vararg.arg)
    if args.kwarg:
        sc.args.add(args.kwarg.arg)

    # Walk the body, NOT recursing into nested defs/classes — those have
    # their own scope and we audit them separately.
    for node in fn.body:
        _walk_one_function_body(node, sc, source_lines)

    return sc


PRELOAD_RE = re.compile(r"^(\s*)(\w+)\s*=\s*ns\[['\"](\w+)['\"]\]\s*(#.*)?$")


def _detect_preload(node: ast.Assign) -> str | None:
    """Detect the `X = ns['X']` pre-load pattern at AST level.
    Returns the name X if matched, else None.

    Match requirements:
      - single target, an ast.Name
      - value is Subscript on Name('ns') with a Constant string slice
      - target name == slice constant value
    """
    if len(node.targets) != 1:
        return None
    tgt = node.targets[0]
    if not isinstance(tgt, ast.Name):
        return None
    val = node.value
    if not isinstance(val, ast.Subscript):
        return None
    if not (isinstance(val.value, ast.Name) and val.value.id == 'ns'):
        return None
    # Python 3.9+: Subscript.slice is the inner node directly. Older
    # versions wrapped in ast.Index.
    sl = val.slice
    if isinstance(sl, ast.Index):  # 3.8 compatibility
        sl = sl.value
    if not (isinstance(sl, ast.Constant) and isinstance(sl.value, str)):
        return None
    if tgt.id != sl.value:
        return None
    return tgt.id


def _walk_one_function_body(root, sc: FunctionScope, source_lines):
    """Walk a node tree, collecting refs + local assignments, but
    STOPPING at any FunctionDef/AsyncFunctionDef/ClassDef boundary
    (those are nested scopes; the OUTER scope only sees the binding
    name they introduce)."""

    class V(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Store):
                sc.locals.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                sc.refs.add(node.id)
            elif isinstance(node.ctx, ast.Del):
                # del NAME — name was a local; treat as bound for purposes
                # of "is this a local?"
                sc.locals.add(node.id)
        def visit_NamedExpr(self, node):
            # walrus — target is a local of the ENCLOSING scope
            if isinstance(node.target, ast.Name):
                sc.locals.add(node.target.id)
            self.visit(node.value)
        def visit_Assign(self, node):
            # Detect pre-load pattern `X = ns['X']` and record it
            # without adding X to the generic locals set. The pre-load
            # is a binding from the host module, not a "real" reassign.
            preload_name = _detect_preload(node)
            if preload_name is not None:
                sc.preloads.add(preload_name)
                # Record the line for later reporting
                sc.preload_lines[preload_name] = node.lineno
                # Still visit the value (the ns['X'] expression) so
                # 'ns' is tracked as a Load ref. Don't visit the target.
                self.visit(node.value)
                return
            for tgt in node.targets:
                sc.locals |= collect_targets(tgt)
            self.visit(node.value)
        def visit_AugAssign(self, node):
            sc.locals |= collect_targets(node.target)
            # AugAssign reads the target too — visit as Load
            if isinstance(node.target, ast.Name):
                sc.refs.add(node.target.id)
            self.visit(node.value)
        def visit_AnnAssign(self, node):
            if isinstance(node.target, ast.Name):
                sc.locals.add(node.target.id)
            if node.value is not None:
                self.visit(node.value)
            if node.annotation is not None:
                self.visit(node.annotation)
        def visit_For(self, node):
            sc.locals |= collect_targets(node.target)
            self.visit(node.iter)
            for c in node.body: self.visit(c)
            for c in node.orelse: self.visit(c)
        def visit_AsyncFor(self, node):
            self.visit_For(node)
        def visit_With(self, node):
            for item in node.items:
                if item.optional_vars is not None:
                    sc.locals |= collect_targets(item.optional_vars)
                self.visit(item.context_expr)
            for c in node.body: self.visit(c)
        def visit_AsyncWith(self, node):
            self.visit_With(node)
        def visit_Try(self, node):
            for c in node.body: self.visit(c)
            for h in node.handlers:
                if h.type is not None: self.visit(h.type)
                if h.name is not None: sc.locals.add(h.name)
                for c in h.body: self.visit(c)
            for c in node.orelse: self.visit(c)
            for c in node.finalbody: self.visit(c)
        def visit_TryStar(self, node):
            self.visit_Try(node)
        def visit_Lambda(self, node):
            # Lambda introduces its own scope; treat as a Load
            # boundary — visit its body but track its args so we don't
            # add them to the outer scope's locals.
            inner_args = set()
            for a in (node.args.posonlyargs or []) + node.args.args + (node.args.kwonlyargs or []):
                inner_args.add(a.arg)
            # Visit the lambda body but filter Name refs whose id is in
            # inner_args. Easiest: walk manually and add refs only if
            # not in inner_args.
            for n in ast.walk(node.body):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    if n.id not in inner_args:
                        sc.refs.add(n.id)
        def visit_ListComp(self, node): self._comp(node)
        def visit_SetComp(self, node): self._comp(node)
        def visit_DictComp(self, node): self._comp(node)
        def visit_GeneratorExp(self, node): self._comp(node)
        def _comp(self, node):
            # Comprehensions introduce their own scope.
            inner_targets = set()
            for gen in node.generators:
                inner_targets |= collect_targets(gen.target)
            # Walk the comprehension body but exclude inner_targets
            for n in ast.walk(node):
                if n is node: continue
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    if n.id not in inner_targets:
                        sc.refs.add(n.id)
        def visit_FunctionDef(self, node):
            # Nested def — the enclosing scope only "sees" the def's name
            sc.locals.add(node.name)
            # Decorators evaluate in enclosing scope
            for d in node.decorator_list:
                self.visit(d)
        def visit_AsyncFunctionDef(self, node):
            self.visit_FunctionDef(node)
        def visit_ClassDef(self, node):
            sc.locals.add(node.name)
            for d in node.decorator_list:
                self.visit(d)
            for b in node.bases:
                self.visit(b)
        def visit_Import(self, node):
            # `import X.Y as Z` — Z bound; `import X.Y` — X bound (root)
            for alias in node.names:
                if alias.asname:
                    sc.locals.add(alias.asname)
                else:
                    sc.locals.add(alias.name.split('.')[0])
        def visit_ImportFrom(self, node):
            # `from M import X, Y as Z` — both X and Z bound locally
            for alias in node.names:
                if alias.asname:
                    sc.locals.add(alias.asname)
                else:
                    sc.locals.add(alias.name)

        # Detect binding-header pre-loads via a textual regex over
        # the corresponding source lines. They have already been
        # collected by visit_Assign as locals; here we ALSO record them
        # in preloads so they can be filtered from "missing dep" complaints.
        def visit_Expr(self, node):
            self.generic_visit(node)
    V().visit(root)

    # Pre-load detection — regex on the actual source lines for the
    # function body. We need lineno bounds.
    start = getattr(root, 'lineno', None)
    end = getattr(root, 'end_lineno', None)
    if start is None or end is None: return
    for li in range(start, end + 1):
        if li - 1 >= len(source_lines): break
        ln = source_lines[li - 1]
        m = PRELOAD_RE.match(ln)
        if m:
            lhs = m.group(2)
            rhs = m.group(3)
            if lhs == rhs:  # NAME = ns['NAME'] (the convention)
                sc.preloads.add(lhs)
                sc.preload_lines[lhs] = li


def main():
    findings = []  # (file, fn_name, kind, name, line, detail)

    for fname in sorted(os.listdir(ENGINE_DIR)):
        if not fname.endswith('.py') or fname.startswith('__'):
            continue
        path = os.path.join(ENGINE_DIR, fname)
        with open(path) as f:
            src = f.read()
        lines = src.split('\n')
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            print(f'  SyntaxError in {fname}: {e}')
            continue

        module_locals = module_level_names(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            sc = analyze_function(node, lines)

            # Skip top-level shim functions that only delegate (no
            # binding header) — these have a different pattern.
            if not sc.preloads:
                continue

            # Names referenced but with no source of binding inside the
            # function scope.
            bound = (sc.args | sc.locals | sc.preloads
                     | BUILTIN_NAMES | module_locals
                     | {'ns'}  # ns is the conventional arg
                     # Module dunders are always available — they exist
                     # on every Python module by definition, so a function
                     # referencing them resolves via its own module's
                     # globals regardless of the binding header.
                     | {'__file__', '__name__', '__doc__', '__package__',
                        '__loader__', '__spec__', '__builtins__'})
            missing = sc.refs - bound

            # Of those, the ones that EXIST on oops_v3 are the real
            # bugs — they're meant to come from there but were never
            # threaded through the binding header.
            for name in sorted(missing):
                if name in OOPS_NAMES:
                    findings.append((fname, node.name, 'missing_preload',
                                     name, node.lineno,
                                     f'used in {node.name} but not pre-loaded; '
                                     f'exists on oops_v3'))

            # Pre-loads that aren't actually in oops_v3 (the walrus class)
            for name in sorted(sc.preloads):
                if name not in OOPS_NAMES:
                    findings.append((fname, node.name, 'bogus_preload',
                                     name, sc.preload_lines.get(name, node.lineno),
                                     'pre-load reads ns[X] but X is not '
                                     'in oops_v3 — KeyError at call time'))

            # Missing write-flush: a pre-loaded name that gets reassigned
            # in the body, but the body never writes back via
            # `ns['NAME'] = NAME`. The oops_v3 caller would observe no
            # change to its module global.
            #
            # Heuristic — read the source text inside the function and
            # scan for the flush pattern `ns['NAME'] = NAME` or
            # `ns["NAME"] = NAME` (both quote styles). Don't require
            # the flush to appear after every assignment — just at least
            # ONCE, which is the minimum for the global to be observable
            # after the function returns. Per-assignment flushing is a
            # stricter convention but pre-loaded names are typically
            # batch-flushed at the function's end.
            f_start = node.lineno
            f_end = node.end_lineno or len(lines)
            body_text = '\n'.join(lines[f_start - 1:f_end])
            FLUSH_PATTERNS = [
                re.compile(r"ns\[['\"]{n}['\"]\]\s*=\s*{n}\b".format(n=re.escape(name)))
                for name in sc.preloads
            ]
            # Augment: for each pre-loaded name, check if (a) it is
            # reassigned in the body's locals AND (b) there is no flush.
            # `locals_set` is the locals collected by analyze_function;
            # an assignment to a pre-loaded name shows up in there.
            for name in sorted(sc.preloads):
                if name not in sc.locals:
                    continue  # never reassigned — read-only, no flush needed
                # Look for a flush pattern
                flush_re = re.compile(
                    r"ns\[['\"]" + re.escape(name) + r"['\"]\]\s*=\s*" +
                    re.escape(name) + r"\b")
                if flush_re.search(body_text):
                    continue  # has at least one flush — good
                # No flush AND reassigned — likely a missing write-back
                findings.append((fname, node.name, 'missing_flush', name,
                                 sc.preload_lines.get(name, node.lineno),
                                 f'pre-loaded but reassigned in body with '
                                 f'no ns[X] = X flush — change lost'))

    if not findings:
        print('No issues found across engine/.')
        return

    by_kind = {}
    for f in findings:
        by_kind.setdefault(f[2], []).append(f)

    for kind, items in sorted(by_kind.items()):
        print(f'\n=== {kind}: {len(items)} ===')
        for fname, fn, _, name, lineno, detail in items:
            print(f'  {fname}:{lineno}  {fn}()  {name:<35}  {detail}')


if __name__ == '__main__':
    main()
