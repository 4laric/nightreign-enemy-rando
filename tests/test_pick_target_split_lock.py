"""Behavior-lock for the test_pick_target.py test surface.

WHAT THIS LOCKS
---------------
The complete set of (class_name, method_name) pairs across all
`tests/test_pick_target*.py` files. The lock fixture lives at
`tests/fixtures/pick_target_test_index.json` and is keyed by class
name; the value is a sorted list of test method names.

WHY THIS EXISTS
---------------
`tests/test_pick_target.py` is the picker's behavior-pinning suite —
55 classes / 265 methods covering gates, caps, reservation order,
seed-specific freeze repros, and tier-ladder edges. It's the spec for
`pick_target_cp` enforced by tests.

The file is large enough (5,279 lines as of v0.28.x) that a planned
refactor will split it along functional seams:

  - test_pick_target_gates.py        — TestGate4*/5*/6*/7* classes
  - test_pick_target_caps.py         — per-c-prefix cap assertions
  - test_pick_target_reservation.py  — reservation-order + floor/ceiling
  - test_pick_target_seed_regressions.py — specific-seed freeze repros
  - test_pick_target.py              — core Signature/Parity/GateEffects

A mechanical split is risky in one specific way: a test class can get
dropped, renamed, or its methods can get accidentally pruned, and
because pytest doesn't fail on "missing" tests (only on failing ones),
the regression is silent. This lock catches that — the test glob is
`test_pick_target*.py`, so a class moving files is fine, but a class
or method disappearing fails.

WHAT THIS DOESN'T LOCK
----------------------
- Test BODIES. The lock is on identity (class + method name), not on
  what the test asserts. A change to a test's assertions is not a
  regression in the lock's sense.
- Module-level test functions. test_pick_target.py uses only
  class-based tests; the lock enforces that convention.
- `pytest.mark.parametrize` expansion. The lock counts test
  *definitions* (what `ast` sees), not collected nodeids. Parametrize
  expansion changes only at runtime.
- Helper classes / fixtures. Anything not matching the
  Test{Class}.test_{method} convention is invisible to the lock.

UPDATING THE LOCK
-----------------
When a test_pick_target change is INTENTIONAL (adding new coverage,
removing genuinely-dead tests, renaming for clarity), regenerate:

  python3 tests/test_pick_target_split_lock.py --regenerate

Review the resulting diff to `tests/fixtures/pick_target_test_index.json`
before committing — the diff is the audit trail for "what changed in
the test surface."
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "pick_target_test_index.json"
_GLOB = "test_pick_target*.py"


def _collect_index() -> dict[str, list[str]]:
    """Walk every test_pick_target*.py under tests/ and return
    {class_name: sorted_list_of_test_method_names}.

    AST-based — does not import the modules. Side-effect-free.
    Asserts no duplicate class names across files (would be a real
    collision pytest would also flag, but worth catching here).
    """
    tests_dir = _REPO_ROOT / "tests"
    index: dict[str, list[str]] = {}
    seen_in: dict[str, str] = {}  # class_name -> source file

    for path in sorted(tests_dir.glob(_GLOB)):
        # Exclude lock tests themselves — they live in test_pick_target_*_lock.py
        # and aren't part of the picker behavior surface.
        if path.name.endswith("_lock.py"):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            pytest.fail(f"{rel} failed to parse: {e}")

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.startswith("Test"):
                continue
            if node.name in seen_in:
                pytest.fail(
                    f"Duplicate test class {node.name!r} in {rel} "
                    f"(already defined in {seen_in[node.name]}). "
                    f"During the split, each class must live in exactly "
                    f"one file."
                )
            seen_in[node.name] = rel

            methods = sorted(
                c.name for c in node.body
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
                and c.name.startswith("test_")
            )
            index[node.name] = methods

    return index


def _load_fixture() -> dict[str, list[str]]:
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPickTargetSplitLock:
    """Lock the (class, method) surface across test_pick_target*.py."""

    def test_no_classes_dropped_or_added(self):
        """The set of test classes across test_pick_target*.py must
        match the lock fixture exactly. A failure here means a class
        was either renamed, deleted, or added without updating the
        fixture.
        """
        actual = _collect_index()
        expected = _load_fixture()

        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))

        if missing or extra:
            msg = ["test_pick_target*.py class set has drifted from lock:"]
            if missing:
                msg.append(f"  MISSING ({len(missing)}): {missing}")
            if extra:
                msg.append(f"  UNEXPECTED ({len(extra)}): {extra}")
            msg.append(
                "  If this change was intentional, regenerate:\n"
                "    python3 tests/test_pick_target_split_lock.py --regenerate"
            )
            raise AssertionError("\n".join(msg))

    def test_no_methods_dropped_or_added(self):
        """For each locked class, the set of test_* methods must match
        the lock exactly. Catches the most common split-refactor
        regression: dropping a method while moving its class to a new
        file.
        """
        actual = _collect_index()
        expected = _load_fixture()

        drifted: list[str] = []
        for cls in sorted(set(expected) & set(actual)):
            exp = set(expected[cls])
            act = set(actual[cls])
            missing = sorted(exp - act)
            extra = sorted(act - exp)
            if missing or extra:
                detail = f"  {cls}:"
                if missing:
                    detail += f" MISSING={missing}"
                if extra:
                    detail += f" UNEXPECTED={extra}"
                drifted.append(detail)

        if drifted:
            raise AssertionError(
                "Test methods have drifted from lock:\n"
                + "\n".join(drifted)
                + "\n  If intentional, regenerate:\n"
                "    python3 tests/test_pick_target_split_lock.py --regenerate"
            )

    def test_total_method_count_matches_lock(self):
        """Cheap aggregate guardrail — easier to read in a failure
        than the per-class diff if many things moved at once.
        """
        actual = _collect_index()
        expected = _load_fixture()

        actual_count = sum(len(v) for v in actual.values())
        expected_count = sum(len(v) for v in expected.values())

        assert actual_count == expected_count, (
            f"Total test method count: locked={expected_count}, "
            f"actual={actual_count}. The per-class drift tests above "
            f"will pinpoint the difference."
        )


# ---------------------------------------------------------------------------
# Fixture regeneration (CLI)
# ---------------------------------------------------------------------------

def _regenerate() -> int:
    """Rewrite the lock fixture from the current state. Returns the
    new total method count.
    """
    index = _collect_index()
    _FIXTURE_PATH.parent.mkdir(exist_ok=True)
    _FIXTURE_PATH.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return sum(len(v) for v in index.values())


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        n = _regenerate()
        print(
            f"Wrote {_FIXTURE_PATH.relative_to(_REPO_ROOT)}: "
            f"{n} test methods across "
            f"{len(_load_fixture())} classes."
        )
    else:
        print(__doc__)
        sys.exit(
            "Run with --regenerate to rewrite the lock, "
            "or use pytest to verify it."
        )
