"""Behavior-lock for the set of emevd_patch.py patches that have been
retired and must NOT reappear in the PATCHES registry.

WHAT THIS LOCKS
---------------
A canonical list of retired patches. For each:
  1. The patch's name does NOT appear in `emevd_patch.PATCHES` at
     module load (i.e., the `@register` decorator was actually
     removed, not just commented).
  2. A `# {patch} RETIRED` comment exists in emevd_patch.py
     (preserves the why-it-was-retired rationale).
  3. SOME tombstone test in `tests/test_emevd_patches.py` asserts
     the patch is not in PATCHES (defense-in-depth — the assertion
     is what runs in CI; the module-level check above is what runs
     once at import).

WHY THIS EXISTS
---------------
`tests/test_emevd_patches.py` currently spends ~4 separate test
classes asserting tombstones for individual retired patches, each
class duplicating the same structural assertion. A planned
consolidation collapses these into a single parametrized test over
a RETIRED_PATCHES table — which is fine for readability but creates
two new failure modes:

  - A retired patch gets dropped from the parametrized table during
    refactor (silent regression: pytest collects fewer tests but
    doesn't fail).
  - A patch in the table gets typo'd, masking the assertion (the
    `not in PATCHES` test passes vacuously for a misspelled name).

This lock catches both. It also catches a third class of bug the
existing tests don't: a `RETIRED` comment present in emevd_patch.py
with no corresponding tombstone test — at least one such gap exists
today (see EXPECTED_RETIRED below; disable_corpse_collision has a
comment but no tombstone in test_emevd_patches.py at v0.28.x).

WHAT THIS DOESN'T LOCK
----------------------
- The REASON each patch was retired. Those rationales live in
  emevd_patch.py comment blocks; auditing them stays an editorial
  exercise.
- Patches that are still active (i.e., currently in PATCHES). Those
  are covered by their own per-patch test classes.
- Whether the retired patch's function body is still in the file.
  Some are kept "for reference" and some are deleted; the lock takes
  no position on that.

UPDATING THE LOCK
-----------------
When retiring a new patch:
  1. Remove the `@register('foo')` decorator in emevd_patch.py.
  2. Add a `# vN.X.Y: foo RETIRED.` comment with the rationale.
  3. Add a tombstone test in test_emevd_patches.py (or, post-
     consolidation, append to the parametrized table).
  4. Add the patch name to EXPECTED_RETIRED below.

When un-retiring a patch (rare; revival case):
  1. Restore the `@register` decorator.
  2. Remove the tombstone.
  3. Remove the patch from EXPECTED_RETIRED.
  4. Update or remove the `RETIRED` comment.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import emevd_patch


# The authoritative list. Each entry: (patch_name, retired_in_version).
# Sorted alphabetically for diff stability.
EXPECTED_RETIRED: list[tuple[str, str]] = [
    ("boss_reward_inject",       "v0.24.100"),
    ("disable_corpse_collision", "v0.24.100"),
    ("nb_wave_bypass",           "v0.24.106"),
    ("permissive_boss_wake",     "v0.24.102"),
    ("permissive_spawn_emerge",  "v0.24.102"),
    ("preboss_wake_timeout",     "v0.24.78"),
]


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_EMEVD_PATCH_PY = _REPO_ROOT / "emevd_patch.py"
_TEST_EMEVD_PATCHES_PY = _REPO_ROOT / "tests" / "test_emevd_patches.py"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRetiredPatchesLock:
    """The set of retired patches matches the lock, and each retired
    patch is verifiably retired (not in PATCHES + has a comment in
    source + has a tombstone test).
    """

    @pytest.mark.parametrize("patch_name,version", EXPECTED_RETIRED,
                             ids=[p for p, _ in EXPECTED_RETIRED])
    def test_retired_patch_absent_from_registry(self, patch_name, version):
        """Module-load assertion: the @register decorator was actually
        removed. If a refactor accidentally re-registers a retired
        patch, this fails on the first emevd_patch import.
        """
        assert patch_name not in emevd_patch.PATCHES, (
            f"Patch {patch_name!r} was retired in {version} but is "
            f"currently registered in emevd_patch.PATCHES. If a "
            f"revival is intentional, also remove {patch_name!r} "
            f"from EXPECTED_RETIRED in this file."
        )

    @pytest.mark.parametrize("patch_name,version", EXPECTED_RETIRED,
                             ids=[p for p, _ in EXPECTED_RETIRED])
    def test_retired_patch_has_source_comment(self, patch_name, version):
        """A `# {patch} RETIRED` comment exists in emevd_patch.py. The
        comment is the place where the retirement rationale lives;
        deleting it makes the retirement undocumented.

        The match is generous — anywhere in the file, any line that
        names the patch and includes the word RETIRED qualifies. The
        existing comment formats are inconsistent (some say
        `# vX.Y: name RETIRED.`, some say `# name (vX.Y) — RETIRED in vA.B`).
        """
        src = _EMEVD_PATCH_PY.read_text(encoding="utf-8")
        # Find a comment line mentioning the patch name AND 'RETIRED'.
        pattern = re.compile(
            rf"^#.*\b{re.escape(patch_name)}\b.*RETIRED",
            re.MULTILINE,
        )
        assert pattern.search(src), (
            f"emevd_patch.py has no `# ... {patch_name} ... RETIRED` "
            f"comment line. The rationale comment is mandatory — it "
            f"explains why the retirement happened and what to "
            f"investigate if the issue recurs."
        )

    @pytest.mark.parametrize("patch_name,version", EXPECTED_RETIRED,
                             ids=[p for p, _ in EXPECTED_RETIRED])
    def test_retired_patch_has_tombstone_test(self, patch_name, version):
        """Some test in tests/test_emevd_patches.py asserts that
        `{patch_name}` is not in emevd_patch.PATCHES. This is the
        CI-level guard.

        The detection is intentionally textual: any line of the form
        `'{patch_name}' not in emevd_patch.PATCHES` counts, whether
        it's an inline assert (current style) or a parametrize
        ID-string after the consolidation refactor.
        """
        src = _TEST_EMEVD_PATCHES_PY.read_text(encoding="utf-8")

        # Strip full-line comments so a commented-out historical entry
        # like `# 'permissive_boss_wake', # RETIRED v0.24.102` doesn't
        # satisfy the check. (Inline end-of-line comments still appear,
        # but the patch name has to be in actual code before any `#`.)
        src_active = re.sub(r"(?m)^\s*#.*$", "", src)

        # Match both quoting styles.
        needle_double = f'"{patch_name}" not in emevd_patch.PATCHES'
        needle_single = f"'{patch_name}' not in emevd_patch.PATCHES"
        # Also match parametrize-table appearance, where the assertion
        # is once but the name appears in the param table.
        param_table = re.compile(
            rf"['\"]({re.escape(patch_name)})['\"]\s*,",
            re.MULTILINE,
        )
        has_assertion = needle_double in src_active or needle_single in src_active
        has_param_entry = bool(param_table.search(src_active))

        assert has_assertion or has_param_entry, (
            f"No tombstone assertion in tests/test_emevd_patches.py "
            f"for retired patch {patch_name!r}. Expected one of:\n"
            f"    assert '{patch_name}' not in emevd_patch.PATCHES\n"
            f"  or a parametrize entry referencing the name.\n"
            f"  (Commented-out entries don't count — strip the `#` "
            f"or add a real assertion.)"
        )

    def test_no_undeclared_retirements_in_source(self):
        """Catch the inverse drift: a `RETIRED` comment in
        emevd_patch.py whose patch name ISN'T in EXPECTED_RETIRED.
        If we add a retirement comment without updating this lock,
        the lock would be silently incomplete.

        The patch-name extractor matches the two comment formats
        currently used in emevd_patch.py:
          # vX.Y: name RETIRED.
          # name (vX.Y) — RETIRED in vA.B
        """
        src = _EMEVD_PATCH_PY.read_text(encoding="utf-8")

        # Format 1: "# vX.Y.Z: name RETIRED."
        fmt1 = re.compile(
            r"^#\s+v[\d.]+\s*:\s+([a-z_][a-z0-9_]*)\s+RETIRED",
            re.MULTILINE,
        )
        # Format 2: "# name (vX.Y) — RETIRED in vA.B"
        fmt2 = re.compile(
            r"^#\s+([a-z_][a-z0-9_]*)\s+\(v[\d.]+\)\s+[—-]+\s*RETIRED",
            re.MULTILINE,
        )

        found = set(fmt1.findall(src)) | set(fmt2.findall(src))
        expected = {name for name, _ in EXPECTED_RETIRED}

        undeclared = sorted(found - expected)
        assert not undeclared, (
            f"emevd_patch.py has RETIRED comments for patches not in "
            f"EXPECTED_RETIRED: {undeclared}. Either add them to the "
            f"lock or remove the comment if the retirement was "
            f"reverted."
        )

    def test_expected_retired_list_is_sorted_unique(self):
        """Cheap convention check — keeps diff noise low."""
        names = [n for n, _ in EXPECTED_RETIRED]
        assert names == sorted(names), (
            f"EXPECTED_RETIRED should be sorted alphabetically; got: {names}"
        )
        assert len(names) == len(set(names)), (
            f"EXPECTED_RETIRED has duplicates: "
            f"{[n for n in names if names.count(n) > 1]}"
        )
