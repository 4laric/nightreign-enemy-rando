"""Lock test for engine.picker.pick_target_cp (v0.28.x extraction).

WHAT THIS LOCKS
---------------
1. The extracted function is importable from engine.picker with
   the expected shape (`ns` as the first positional argument).

2. The shim in oops_v3.py (`pick_target_cp`) delegates to the
   engine function with arguments in the correct order. Shim
   signature parity must match the engine function minus `ns`.

3. The engine function imports engine.rejection (the sibling
   predicate module) at module load time — both mirror functions
   live in the engine namespace and the picker's hot-path
   rejection check is a local function call, not a shim hop
   through oops_v3.

The wider behavioral surface (every gate's correctness, the full
RNG sequence, reservation honoring, cap enforcement, NB-arena
preservation) is covered by tests/test_pick_target*.py — 300+
tests that run unchanged because the shim preserves the public
symbol name and signature.
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine.picker import pick_target_cp  # noqa: E402


# ---------------------------------------------------------------------------
# Invariant 1: module surface
# ---------------------------------------------------------------------------

class TestExtractedSurface:
    def test_engine_function_importable(self):
        from engine import picker
        assert hasattr(picker, 'pick_target_cp')

    def test_engine_function_takes_ns_first(self):
        sig = inspect.signature(pick_target_cp)
        params = list(sig.parameters.values())
        assert params[0].name == 'ns', (
            f'first param is {params[0].name!r}; expected "ns"')

    def test_shim_signature_matches_engine_minus_ns(self):
        """Shim must accept every kwarg the engine function accepts,
        in the same order. A drift causes mysterious TypeError at
        runtime."""
        import oops_v3
        shim_sig = inspect.signature(oops_v3.pick_target_cp)
        engine_sig = inspect.signature(pick_target_cp)

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


# ---------------------------------------------------------------------------
# Invariant 2: engine.rejection is the predicate source, called directly
# ---------------------------------------------------------------------------

class TestEngineSiblingCall:
    """The picker should call engine.rejection.reject_target_for_slot
    directly — not the oops_v3 shim. This is the hot-path benefit of
    co-locating the picker and predicate in the engine subpackage."""

    def test_picker_imports_from_engine_rejection(self):
        """Module-level import: engine.picker must reference
        reject_target_for_slot from engine.rejection (the source of
        truth), not from oops_v3 (which would reintroduce the shim
        hop on a hot path called ~5000× per shuffle).
        """
        import ast
        from engine import picker
        src = open(picker.__file__).read()
        tree = ast.parse(src)

        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module == 'engine.rejection'
                        and any(a.name == 'reject_target_for_slot'
                                for a in node.names)):
                    found = True
                    break
        assert found, (
            'engine.picker does not import reject_target_for_slot '
            'from engine.rejection — the hot-path mirror call would '
            'go through the oops_v3 shim, adding a function-call '
            'layer per gate check.'
        )

    def test_picker_calls_reject_target_for_slot_with_ns(self):
        """Source-grep: the picker body must call
        reject_target_for_slot(ns, ...) — passing the namespace dict
        so the predicate can read V3_* state from the same source
        the picker is reading. A bare reject_target_for_slot(...)
        without `ns` would AttributeError at call time."""
        import inspect
        src = inspect.getsource(pick_target_cp)
        assert 'reject_target_for_slot(ns,' in src, (
            'engine.picker.pick_target_cp does not pass ns to '
            'reject_target_for_slot — the predicate would have no '
            'state to read.'
        )
