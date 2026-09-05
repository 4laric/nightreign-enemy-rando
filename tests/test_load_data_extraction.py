"""Lock test for engine.load_data.load_data (v0.28.x extraction).

WHAT THIS LOCKS
---------------
1. The extracted function is importable from engine.load_data with
   the expected shape (`ns` as the first positional argument; same
   pattern as the other engine.* extractions).

2. The shim in oops_v3.py (`load_data`) delegates to the engine
   function with `globals()` and returns the same `(roster, tags)`
   tuple shape.

3. The "flush after every write" pattern works: after load_data
   completes, the caller's namespace MUST have the 10 previously-
   global names populated (not stale-empty). This is the critical
   contract that replaces the original `global X; X = ...` mechanism.
   If the flush pattern regresses, downstream V3_FOO lookups via
   `oops_v3.V3_FOO` would see the initial (empty) value instead of
   the loader-populated value.

The wider behavioral surface (every JSON file loaded, every pack
loader's output, every derived set's contents) is implicitly
covered by the full test suite — most tests construct a
`oops_v3.load_data()` fixture and rely on the populated state
being correct. Those tests are the functional lock; this file's
job is the EXTRACTION contract.
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine.load_data import load_data as engine_load_data  # noqa: E402


# ---------------------------------------------------------------------------
# Invariant 1: module surface
# ---------------------------------------------------------------------------

class TestExtractedSurface:
    def test_engine_function_importable(self):
        from engine import load_data
        assert hasattr(load_data, 'load_data')

    def test_engine_function_takes_ns_only(self):
        """The engine function takes ONLY `ns` — no other args. The
        shim's no-args signature `load_data()` is preserved by
        passing `globals()` to the engine function."""
        sig = inspect.signature(engine_load_data)
        params = list(sig.parameters.values())
        assert len(params) == 1, (
            f'engine load_data should take exactly 1 param (ns); '
            f'has {len(params)}: {[p.name for p in params]}'
        )
        assert params[0].name == 'ns'

    def test_shim_signature_preserved(self):
        """The oops_v3.load_data shim must take no arguments —
        matches the pre-extraction signature that every caller uses
        (`roster, tags = oops_v3.load_data()`)."""
        import oops_v3
        sig = inspect.signature(oops_v3.load_data)
        assert len(sig.parameters) == 0, (
            f'shim should take no args; has {list(sig.parameters)}'
        )


# ---------------------------------------------------------------------------
# Invariant 2: the flush pattern populates caller namespace
# ---------------------------------------------------------------------------

# The 10 names that load_data MUST populate via `ns['X'] = X` flushes.
# If the flush regresses (e.g. `global X; X = expr` returns without
# the flush), these will be missing from the module namespace.
FLUSHED_NAMES = [
    'V3_EXCLUDE_TARGET_PREFIXES',
    'V3_NIGHT_BOSS_CALIBER_TARGETS',
    'V3_NIGHT_BOSS_STRICT_TARGETS',
    'V3_MP_SAFE_BLOCKLIST',
    'V3_ARENA_ONLY_TARGETS',
    'V3_AVOID_VARIANT_NPC_IDS',
    'V3_SOTE_PREFIXES',
    'V3_RIDER_PREFIXES',
    'V3_MOUNT_PREFIXES',
    '_V3_SLOT_POI_CLUSTERS',
]


class TestFlushPattern:
    """After load_data runs, every flushed name must be visible in
    the caller's namespace via attribute access — this is the
    pre-extraction contract."""

    @pytest.fixture(scope='class')
    def loaded(self):
        import oops_v3
        roster, tags = oops_v3.load_data()
        return oops_v3, roster, tags

    def test_returns_roster_and_tags(self, loaded):
        engine, roster, tags = loaded
        # roster is a dict with keys like 'all_variants' /
        # 'canonical_targets'; tags is a dict cp -> {tier, ...}.
        assert isinstance(roster, dict)
        assert isinstance(tags, dict)
        assert len(tags) > 0
        assert len(roster) > 0

    @pytest.mark.parametrize('name', FLUSHED_NAMES)
    def test_flushed_name_visible_on_module(self, loaded, name):
        engine, _, _ = loaded
        assert hasattr(engine, name), (
            f'{name} not present on oops_v3 after load_data — the '
            f'flush pattern regressed. The engine function rebinds '
            f'local names but the `ns[...] = X` flush must run too.'
        )

    def test_at_least_one_flushed_set_is_populated(self, loaded):
        """At least V3_MP_SAFE_BLOCKLIST and V3_AVOID_VARIANT_NPC_IDS
        should be non-empty in any healthy data load. If both are
        empty, load_data crashed silently or the flushes didn't run.
        """
        engine, _, _ = loaded
        non_empty = [n for n in FLUSHED_NAMES
                     if isinstance(getattr(engine, n, None),
                                   (set, dict, list))
                     and len(getattr(engine, n)) > 0]
        assert len(non_empty) >= 2, (
            f'Only {non_empty} are non-empty; load_data probably '
            f'crashed silently or the flush pattern regressed.'
        )


# ---------------------------------------------------------------------------
# Invariant 3: AST-check — every write site has a flush companion
# ---------------------------------------------------------------------------

class TestFlushSitesAreComplete:
    """Structural check: every Assign whose target is one of the
    FLUSHED_NAMES must be immediately followed by a matching
    `ns['X'] = X` flush. If a future edit adds a write site
    without the flush, this test fires before downstream tests
    even run."""

    def test_every_write_has_a_flush(self):
        import ast
        from engine import load_data
        src = open(load_data.__file__, encoding="utf-8").read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == 'load_data')

        # Collect write sites (Assign targets that are FLUSHED_NAMES)
        # and their parent body context, so we can find what comes
        # immediately after each.
        flush_targets = set(FLUSHED_NAMES)

        def walk_body(body, path=()):
            """Yield (i, stmt) pairs walking nested blocks too."""
            for i, stmt in enumerate(body):
                yield body, i, stmt
                # Recurse into compound statements
                if isinstance(stmt, (ast.If, ast.For, ast.While)):
                    yield from walk_body(stmt.body, path + (stmt,))
                    yield from walk_body(stmt.orelse, path + (stmt,))
                elif isinstance(stmt, ast.Try):
                    yield from walk_body(stmt.body, path + (stmt,))
                    for handler in stmt.handlers:
                        yield from walk_body(handler.body, path + (stmt,))
                    yield from walk_body(stmt.finalbody, path + (stmt,))
                elif isinstance(stmt, ast.With):
                    yield from walk_body(stmt.body, path + (stmt,))

        unflushed = []
        for body, i, stmt in walk_body(fn.body):
            if not isinstance(stmt, ast.Assign):
                continue
            if len(stmt.targets) != 1:
                continue
            t = stmt.targets[0]
            if not isinstance(t, ast.Name) or t.id not in flush_targets:
                continue
            # Skip the binding-header assignments themselves: those
            # have shape `X = ns['X']` — they READ from ns, they're
            # not write sites that need flushing back.
            if (isinstance(stmt.value, ast.Subscript)
                    and isinstance(stmt.value.value, ast.Name)
                    and stmt.value.value.id == 'ns'
                    and isinstance(stmt.value.slice, ast.Constant)
                    and stmt.value.slice.value == t.id):
                continue
            # Find next statement (could be a flush)
            if i + 1 >= len(body):
                unflushed.append((t.id, stmt.lineno))
                continue
            nxt = body[i + 1]
            # Expected shape: ns['X'] = X
            if not isinstance(nxt, ast.Assign):
                unflushed.append((t.id, stmt.lineno))
                continue
            if len(nxt.targets) != 1:
                unflushed.append((t.id, stmt.lineno))
                continue
            target = nxt.targets[0]
            if not (isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == 'ns'
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == t.id):
                unflushed.append((t.id, stmt.lineno))
                continue
            # Value of flush should be the bare name we just assigned
            if not (isinstance(nxt.value, ast.Name)
                    and nxt.value.id == t.id):
                unflushed.append((t.id, stmt.lineno))

        assert not unflushed, (
            f'Write sites without an immediate ns[\'X\'] = X flush: '
            f'{unflushed}. Every write to a previously-global name '
            f'must be followed by the flush statement — otherwise '
            f'pack loaders and downstream helpers see stale state.'
        )
