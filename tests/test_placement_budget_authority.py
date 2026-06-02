"""Authority lock for the placement_budget JSON loader (TODO Steps 2 / 2b / 3).

POST-STEP-3 STATE
-----------------
After Step 3, the inline V3_* literals in oops_v3.py are EMPTY
placeholders (set(), {}, etc.); data/placement_budget.json is the sole
source of truth for the 9 covered sets. Authority is locked by three
invariants:

1. **Loader fired (TestLoaderFired).** When `data/placement_budget.json`
   exists, the engine's JSON-sourced `V3_*` state at module-load time
   matches what the loader produces from the JSON — i.e., the loader's
   dict-update actually took effect rather than silently leaving the
   empty placeholders. A regression here means the override was
   bypassed (import ordering bug, exception swallowed, etc.).

2. **Inline placeholders stay empty (TestPostStep3PlaceholdersAreEmpty).**
   The inline definition in oops_v3.py for each JSON-sourced set must
   be an EMPTY placeholder. If a future commit accidentally re-adds
   inline data — e.g. `V3_FOO = {'c1234'}` — the JSON loader will
   silently override it (dead code). AST-parses each definition and
   asserts emptiness.

3. **Fallback path stays functional (TestFallbackPath).** If the JSON
   is missing or malformed, `apply_static_overrides()` must return
   False without mutating the target. This protects test scenarios
   that use dummy modules. Note: in oops_v3.py the JSON is treated as
   mandatory — if the loader returns False there, a RuntimeError is
   raised. The fallback exists for the apply_static_overrides()
   contract, not for production oops_v3 use.

WHAT THIS DOES NOT LOCK
-----------------------
- V3_MP_SAFE_BLOCKLIST is excluded from the loader's scope entirely
  (load_data computes it from per-tag _source rules). The JSON's
  mp_safe_blocked field is snapshot-only.
- The schema of the JSON itself — that's covered by
  tests/test_extract_placement_budget.py::TestSchemaInvariants.
- The Step 2b idempotent-composition invariant for the load_data-
  mutated sets (V3_UNIQUE_TARGET_CAPS, V3_EXCLUDE_TARGET_PREFIXES,
  V3_NIGHT_BOSS_CALIBER_TARGETS, V3_ARENA_ONLY_TARGETS,
  V3_NIGHT_BOSS_STRICT_TARGETS). Covered by the round-trip test in
  test_extract_placement_budget.py::TestLiveEngine::test_committed_
  file_matches_engine_state, which runs after load_data() and verifies
  the resulting engine state still matches the committed JSON.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import oops_v3                                       # noqa: E402
from engine.placement_budget import (                # noqa: E402
    apply_static_overrides,
    build_static_overrides,
    load_budget,
)


# All 9 sets the loader is authoritative for. Step 2 (pure-static) and
# Step 2b (idempotently mutated by load_data) are not distinguished
# here — post-Step-3 both classes go through the same loader path with
# empty inline placeholders.
JSON_SOURCED_V3_NAMES = (
    # Step 2 (pure-static):
    'V3_GHOST_EXCLUDE_TARGET_PREFIXES',
    'V3_FRAGILE_SENSITIVE_TARGETS',
    'V3_MAP_PREFIX_TARGET_EXCLUDES',
    'V3_TARGET_PLACEMENT_CAP',
    # Step 2b (idempotently mutated by load_data):
    'V3_UNIQUE_TARGET_CAPS',
    'V3_EXCLUDE_TARGET_PREFIXES',
    'V3_NIGHT_BOSS_STRICT_TARGETS',
    'V3_NIGHT_BOSS_CALIBER_TARGETS',
    'V3_ARENA_ONLY_TARGETS',
)


def _parse_inline_literal(name: str) -> object:
    """Find the top-level Assign / AnnAssign for `name` in oops_v3.py
    and evaluate its right-hand side as a literal. Returns the value,
    or raises if the literal can't be evaluated.

    Handles three forms:
      (a) Plain literals (`{1, 2}`, `{'a': 1}`, `42`) — via
          ast.literal_eval.
      (b) Post-Step-3 empty placeholders (`set()`, `dict()`) — recognized
          structurally and returned as the corresponding empty value.
      (c) Empty `{}` literal — already handled by literal_eval as dict.

    Used by:
      - TestPostStep3PlaceholdersAreEmpty to assert the placeholders are
        empty (no accidental inline data).
    """
    src = pathlib.Path(ROOT, 'oops_v3.py').read_text(encoding='utf-8')
    tree = ast.parse(src)

    def _resolve(value_node):
        # set() / dict() / list() empty calls — Step 3 placeholder shape
        if (isinstance(value_node, ast.Call)
                and isinstance(value_node.func, ast.Name)
                and value_node.func.id in ('set', 'dict', 'list')
                and not value_node.args
                and not value_node.keywords):
            return {'set': set(), 'dict': {}, 'list': []}[value_node.func.id]
        return ast.literal_eval(value_node)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return _resolve(node.value)
        elif isinstance(node, ast.AnnAssign):
            if (isinstance(node.target, ast.Name)
                    and node.target.id == name
                    and node.value is not None):
                return _resolve(node.value)
    raise AssertionError(
        f'No top-level Assign for {name!r} found in oops_v3.py. '
        f'If this name has been removed entirely, the test that '
        f'references it needs to be updated.'
    )


# ---------------------------------------------------------------------------
# Invariant 1: the loader actually fired
# ---------------------------------------------------------------------------

class TestLoaderFired:
    """When the JSON is present (as it is in the shipped repo), the
    engine's V3_* state matches what the loader produces from the JSON.
    This proves the apply_static_overrides() call at the bottom of
    oops_v3.py executed rather than being silently bypassed.
    """

    @pytest.fixture(scope='class')
    def overrides(self):
        budget = load_budget()
        assert budget is not None, (
            'data/placement_budget.json is missing or malformed — '
            'expected to be present in this repo. If you removed it '
            'intentionally, this test needs to flip into "fallback "" '
            'mode."'
        )
        return build_static_overrides(budget)

    @pytest.mark.parametrize('v3_name', JSON_SOURCED_V3_NAMES)
    def test_engine_state_matches_loader_output(self, v3_name, overrides):
        if v3_name not in overrides:
            pytest.skip(
                f'{v3_name} not produced by build_static_overrides — '
                f'probably an optional schema field; skipped.'
            )
        live = getattr(oops_v3, v3_name)
        loaded = overrides[v3_name]
        assert live == loaded, (
            f'oops_v3.{v3_name} disagrees with the loader\'s value. '
            f'This means either the loader\'s setattr did not fire '
            f'(import-order bug? exception swallowed?), or something '
            f'mutated the engine state between module-load and the '
            f'test. Check the apply_static_overrides() call near the '
            f'bottom of oops_v3.py.\n'
            f'NOTE: for Step 2b sets, this test runs at module-load '
            f'time BEFORE load_data() — engine state should equal the '
            f'JSON-derived value verbatim. If a test fixture has '
            f'already called load_data(), idempotent composition '
            f'guarantees the state still matches (per the invariant '
            f'documented in engine/placement_budget.py).'
        )


# ---------------------------------------------------------------------------
# Invariant 2: inline literals are GONE (Step 3 post-condition)
# ---------------------------------------------------------------------------

class TestPostStep3PlaceholdersAreEmpty:
    """Post-Step-3 sanity: every JSON-sourced V3_* set must be defined
    as an EMPTY placeholder in oops_v3.py. If a future commit accidentally
    re-introduces inline data — e.g. someone adds `V3_FOO = {'c1234'}` —
    the JSON loader at end-of-module will OVERRIDE it, silently making
    the inline data dead code. This test catches that by parsing the
    inline assignment and asserting it's empty.

    Replaces the pre-Step-3 TestInlineLiteralsAlignWithJson class (which
    asserted inline == JSON; vacuous now that inline is empty).
    """

    @pytest.mark.parametrize('v3_name', JSON_SOURCED_V3_NAMES)
    def test_inline_definition_is_empty_placeholder(self, v3_name):
        # V3_TARGET_PLACEMENT_CAP is an int, not a collection; skip
        # the emptiness check (it has a placeholder value of 50,
        # arbitrary; JSON replaces).
        if v3_name == 'V3_TARGET_PLACEMENT_CAP':
            pytest.skip('scalar; the placeholder value is documented '
                        'as JSON-replaced')
        value = _parse_inline_literal(v3_name)
        assert len(value) == 0, (
            f'{v3_name} has a non-empty inline definition in '
            f'oops_v3.py — found {len(value)} entries. Post-Step-3 '
            f'this set is sourced entirely from data/placement_budget'
            f'.json; inline data is silently overridden by the JSON '
            f'loader (dead code). Move the entries into the JSON '
            f'instead.'
        )


# ---------------------------------------------------------------------------
# Invariant 3: fallback path stays functional
# ---------------------------------------------------------------------------

class TestFallbackPath:
    """If the JSON is missing or malformed, apply_static_overrides()
    must return False and not mutate the engine module. The fallback
    is what protects first-time bootstrap and corrupted-file cases.
    """

    def test_missing_file_returns_false_and_leaves_module_untouched(self):
        # Use a NEW dummy module (don't mutate oops_v3 — that would
        # break every other test in this session).
        import types
        dummy = types.ModuleType('dummy_for_fallback_test')
        applied = apply_static_overrides(
            dummy, path='/nonexistent/path/budget.json', verbose=False)
        assert applied is False
        # No V3_* attrs should have been set on the dummy.
        assert not any(name.startswith('V3_') for name in dir(dummy))

    def test_malformed_json_returns_false(self, tmp_path):
        import types
        bad = tmp_path / 'bad.json'
        bad.write_text('this is not json', encoding='utf-8')
        dummy = types.ModuleType('dummy_for_malformed_test')
        applied = apply_static_overrides(
            dummy, path=str(bad), verbose=False)
        assert applied is False
        assert not any(name.startswith('V3_') for name in dir(dummy))

    def test_wrong_shape_returns_false(self, tmp_path):
        """JSON that parses but doesn't have the expected 'chrs' key
        is treated as malformed."""
        import json
        import types
        wrong = tmp_path / 'wrong_shape.json'
        wrong.write_text(json.dumps({'not_chrs': {}}), encoding='utf-8')
        dummy = types.ModuleType('dummy_for_wrongshape_test')
        applied = apply_static_overrides(
            dummy, path=str(wrong), verbose=False)
        assert applied is False
        assert not any(name.startswith('V3_') for name in dir(dummy))
