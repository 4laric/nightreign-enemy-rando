"""Lock tests for engine.cmd_shuffle.cmd_shuffle_v3_impl and the 5
functions in engine.import_planning (v0.28.x extraction).

Both modules follow the standard pattern:
  - engine function takes `ns` as the first positional argument
  - shim in oops_v3 delegates with globals()
  - shim signature matches the engine signature minus `ns`

cmd_shuffle has 2 globals that get flushed (_V3_RUN_SEED,
_V3_TRACE_BUFFER); import_planning's 5 functions are pure (no
global writes).

The functional surface — every actual import workflow path, every
shuffle-orchestrator path — is covered by the broader test suite
running the public API unchanged via the shims.
"""
from __future__ import annotations

import ast
import inspect
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine.cmd_shuffle import cmd_shuffle_v3_impl  # noqa: E402
from engine import import_planning  # noqa: E402


# ---------------------------------------------------------------------------
# Invariant 1: cmd_shuffle surface + signature parity
# ---------------------------------------------------------------------------

class TestCmdShuffleSurface:
    def test_engine_function_takes_ns_first(self):
        sig = inspect.signature(cmd_shuffle_v3_impl)
        params = list(sig.parameters.values())
        assert params[0].name == 'ns'

    def test_shim_signature_matches_engine_minus_ns(self):
        import oops_v3
        shim_sig = inspect.signature(oops_v3._cmd_shuffle_v3_impl)
        engine_sig = inspect.signature(cmd_shuffle_v3_impl)
        shim_params = list(shim_sig.parameters.values())
        engine_params = list(engine_sig.parameters.values())[1:]

        assert len(shim_params) == len(engine_params)
        for sp, ep in zip(shim_params, engine_params):
            assert sp.name == ep.name, (
                f'{sp.name!r} != {ep.name!r}')
            assert sp.default == ep.default, (
                f'default for {sp.name}: shim={sp.default!r} '
                f'engine={ep.default!r}')

    def test_back_copy_marker_in_engine_module(self):
        """The Phase 5.5 back-copy must still be present in the
        engine module body. This is the contract that
        write_spoiler_logs sees populated state when run_ctx was
        used during shuffle."""
        src = inspect.getsource(cmd_shuffle_v3_impl)
        assert 'Phase 5.5' in src
        assert '_V3_UNIQUE_RESERVATIONS.update' in src
        assert '_V3_UNIQUE_PLACED_COUNTS.update' in src
        assert '_V3_UNIQUE_UNPLACED_LOG.extend' in src


# ---------------------------------------------------------------------------
# Invariant 2: cmd_shuffle flush pattern
# ---------------------------------------------------------------------------

class TestCmdShuffleFlushPattern:
    """The 2 globals (_V3_RUN_SEED, _V3_TRACE_BUFFER) must use the
    flush pattern. AST-level check identical to load_data's lock."""

    FLUSHED = {'_V3_RUN_SEED', '_V3_TRACE_BUFFER'}

    def test_every_write_has_a_flush(self):
        from engine import cmd_shuffle
        src = open(cmd_shuffle.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == 'cmd_shuffle_v3_impl')

        def walk_body(body):
            for i, stmt in enumerate(body):
                yield body, i, stmt
                if isinstance(stmt, (ast.If, ast.For, ast.While)):
                    yield from walk_body(stmt.body)
                    yield from walk_body(stmt.orelse)
                elif isinstance(stmt, ast.Try):
                    yield from walk_body(stmt.body)
                    for h in stmt.handlers:
                        yield from walk_body(h.body)
                    yield from walk_body(stmt.finalbody)
                elif isinstance(stmt, ast.With):
                    yield from walk_body(stmt.body)

        unflushed = []
        for body, i, stmt in walk_body(fn.body):
            if not isinstance(stmt, ast.Assign):
                continue
            if len(stmt.targets) != 1:
                continue
            t = stmt.targets[0]
            if not isinstance(t, ast.Name) or t.id not in self.FLUSHED:
                continue
            # Skip binding-header reads (`X = ns['X']`)
            if (isinstance(stmt.value, ast.Subscript)
                    and isinstance(stmt.value.value, ast.Name)
                    and stmt.value.value.id == 'ns'
                    and isinstance(stmt.value.slice, ast.Constant)
                    and stmt.value.slice.value == t.id):
                continue
            # Look for next statement to be the flush
            if i + 1 >= len(body):
                unflushed.append((t.id, stmt.lineno))
                continue
            nxt = body[i + 1]
            if not (isinstance(nxt, ast.Assign)
                    and len(nxt.targets) == 1
                    and isinstance(nxt.targets[0], ast.Subscript)
                    and isinstance(nxt.targets[0].value, ast.Name)
                    and nxt.targets[0].value.id == 'ns'
                    and isinstance(nxt.targets[0].slice, ast.Constant)
                    and nxt.targets[0].slice.value == t.id
                    and isinstance(nxt.value, ast.Name)
                    and nxt.value.id == t.id):
                unflushed.append((t.id, stmt.lineno))

        assert not unflushed, (
            f'Write sites without immediate flush: {unflushed}')


# ---------------------------------------------------------------------------
# Invariant 3: import_planning — all 5 surfaces
# ---------------------------------------------------------------------------

IMPORT_PLANNING_FNS = [
    'compatibility_preflight',
    'plan_bulk_chr_import',
    'execute_bulk_chr_import',
    'plan_roster_import',
    'execute_roster_import',
]


class TestImportPlanningSurface:
    @pytest.mark.parametrize('name', IMPORT_PLANNING_FNS)
    def test_engine_function_importable(self, name):
        assert hasattr(import_planning, name)

    @pytest.mark.parametrize('name', IMPORT_PLANNING_FNS)
    def test_engine_function_takes_ns_first(self, name):
        fn = getattr(import_planning, name)
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        assert params[0].name == 'ns', (
            f'{name} first param is {params[0].name!r}; expected '
            f'"ns" (the engine module uses uniform ns-first for all '
            f'5 functions, even pure ones, for shim consistency)')

    @pytest.mark.parametrize('name', IMPORT_PLANNING_FNS)
    def test_shim_signature_matches_engine_minus_ns(self, name):
        import oops_v3
        shim_fn = getattr(oops_v3, name)
        engine_fn = getattr(import_planning, name)
        shim_params = list(inspect.signature(shim_fn).parameters.values())
        engine_params = list(inspect.signature(engine_fn).parameters.values())[1:]

        assert len(shim_params) == len(engine_params), (
            f'{name}: shim has {len(shim_params)}, engine has '
            f'{len(engine_params)} (excl ns)')
        for sp, ep in zip(shim_params, engine_params):
            assert sp.name == ep.name, (
                f'{name}: shim {sp.name!r} != engine {ep.name!r}')
            assert sp.default == ep.default, (
                f'{name}: default for {sp.name}: shim={sp.default!r} '
                f'engine={ep.default!r}')


class TestImportPlanningPurity:
    """The 5 functions declare no `global` statements — the import
    workflow is pure I/O over given inputs, no per-run module
    mutation. If a future edit introduces `global X`, this fires."""

    @pytest.mark.parametrize('name', IMPORT_PLANNING_FNS)
    def test_no_global_decls(self, name):
        src = open(import_planning.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        globals_ = [s for s in ast.walk(fn) if isinstance(s, ast.Global)]
        assert not globals_, (
            f'engine.import_planning.{name} declares {len(globals_)} '
            f'global statement(s). Either route the state through '
            f'ns with flush pattern (see engine.load_data) or move '
            f'the function elsewhere.')
