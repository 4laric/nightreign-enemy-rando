"""Lock test for engine.shuffler.shuffle_msb_v3 (v0.28.x extraction).

WHAT THIS LOCKS
---------------
1. The extracted function is importable from engine.shuffler with
   the expected shape (`ns` as the first positional argument).

2. The shim in oops_v3.py (`shuffle_msb_v3`) delegates with all
   22 kwargs in the right order — defaults match the engine
   function exactly (zero-mismatch on names AND defaults).

3. The engine function makes no `global` writes — it should
   declare zero `global` statements, because all per-run state
   mutation routes through run_ctx (engine.runctx.RunContext) or
   the caller-supplied spoiler_entries list. If a future edit
   introduces a `global X` declaration, this test fires.

The wider behavioral surface (every code path through the MSB
parse → pick_target → model-edit → write loop) is implicitly
covered by the seed-regression and pick_target tests, which exercise
shuffle_msb_v3 end-to-end via the oops_v3 shim. Those don't need
updating for this extraction — the shim preserves the public
symbol name and signature.
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

from engine.shuffler import shuffle_msb_v3 as engine_shuffle  # noqa: E402


class TestExtractedSurface:
    def test_engine_function_importable(self):
        from engine import shuffler
        assert hasattr(shuffler, 'shuffle_msb_v3')

    def test_engine_function_takes_ns_first(self):
        sig = inspect.signature(engine_shuffle)
        params = list(sig.parameters.values())
        assert params[0].name == 'ns', (
            f'first param is {params[0].name!r}; expected "ns"')

    def test_shim_signature_matches_engine_minus_ns(self):
        """Strict signature parity. shuffle_msb_v3 has 22 positional
        and kwarg parameters; default-value mismatches would break
        callers who rely on positional shortcuts."""
        import oops_v3
        shim_sig = inspect.signature(oops_v3.shuffle_msb_v3)
        engine_sig = inspect.signature(engine_shuffle)

        engine_params = list(engine_sig.parameters.values())[1:]
        shim_params = list(shim_sig.parameters.values())

        assert len(shim_params) == len(engine_params), (
            f'Shim has {len(shim_params)} params; engine has '
            f'{len(engine_params)} (excluding ns).'
        )
        for sp, ep in zip(shim_params, engine_params):
            assert sp.name == ep.name, (
                f'Shim param {sp.name!r} != engine param {ep.name!r}'
            )
            assert sp.default == ep.default, (
                f'Default for {sp.name!r}: shim={sp.default!r}, '
                f'engine={ep.default!r}'
            )


class TestNoGlobalWrites:
    """The shuffle driver must not mutate module-level state via
    `global X; X = ...`. All per-run state routes through run_ctx
    or the spoiler_entries list."""

    def test_engine_function_declares_no_globals(self):
        from engine import shuffler
        src = open(shuffler.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name == 'shuffle_msb_v3'
        )

        global_decls = [s for s in ast.walk(fn)
                        if isinstance(s, ast.Global)]
        assert not global_decls, (
            f'engine.shuffler.shuffle_msb_v3 contains '
            f'{len(global_decls)} `global` declaration(s) — adds an '
            f'ns-write surface that would need flush statements. '
            f'Route per-run state through run_ctx or '
            f'spoiler_entries instead.'
        )
