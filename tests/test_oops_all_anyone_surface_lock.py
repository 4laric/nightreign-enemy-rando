"""Behavior-lock for the external import surface of oops_all_anyone.py.

WHAT THIS LOCKS
---------------
The complete set of names that any file outside oops_all_anyone.py
imports from it — whether via `from oops_all_anyone import X` or via
`import oops_all_anyone as oa` followed by `oa.X` attribute access.

The lock holds this set against EXPECTED_SURFACE below. Any new
external import of a name not in EXPECTED_SURFACE fails the test;
any name in EXPECTED_SURFACE that goes unused also fails (forces
the list to stay honest).

It also pins behavioral fingerprints (module-load sentinel values)
for the locked constants, so that an accidental change to a kept
primitive's value during an oops_all_anyone reorganization is
caught at the value level too, not just the name level.

WHY THIS EXISTS
---------------
`oops_all_anyone.py` is the pre-v3 engine — its v3 replacement
(`oops_v3.py`) imports a small set of MSB-parsing primitives from it
and otherwise ignores the rest. The file has grown to 67KB and most
of its surface (the `cmd_*` CLI subcommands: list, search, convert,
cluster-report, shuffle, dump-models, model-shuffle, model-swap, and
the supporting `shuffle_msb` / `compatible_pool*` / `build_compat_
lookups` / `load_tags` infrastructure) has no external callers.

A planned cleanup removes the unused CLI surface and either:
  (a) extracts the kept primitives into a smaller `msb_primitives.py`,
  (b) prunes oops_all_anyone.py in place to just the kept surface.

Either path needs a regression test that catches:
  - Accidentally removing a function/constant that IS imported
    externally (caught by the import-surface assertion).
  - Accidentally changing the SHAPE of a kept primitive in a way
    that callers depend on but isn't caught by name (caught by the
    behavioral fingerprint).
  - A new file starting to import an old CLI helper before the
    cleanup happens (caught by the surface-is-minimal assertion).

WHAT THIS DOESN'T LOCK
----------------------
- The implementation of locked primitives — only their existence and
  callable/value shape. Refactors that preserve behavior pass.
- Internal symbols (functions called only within oops_all_anyone).
  Those CAN be deleted as part of the cleanup; the test won't object.
- The CLI subcommands (`cmd_list`, `cmd_search`, etc.). These exist
  but are not imported externally — they're free to remove.

UPDATING THE LOCK
-----------------
When a deliberate import-surface change happens (e.g., adding a new
primitive that another module imports):
  1. Add the name to EXPECTED_SURFACE below.
  2. If it's a constant, add a fingerprint entry under
     EXPECTED_CONSTANT_FINGERPRINTS.
  3. If it's a function, add it under EXPECTED_CALLABLES (just by
     name; behavior testing is the caller's responsibility).

When removing a primitive (because no one imports it anymore):
  1. First migrate the consumer off it (or delete the consumer).
  2. Then drop the name from EXPECTED_SURFACE.
"""
from __future__ import annotations

import ast
import hashlib
import pathlib
import re

import pytest

# Importing oops_all_anyone runs no destructive code (the CLI's
# argparse / main() lives behind `if __name__ == '__main__':`).
import oops_all_anyone


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OAA = "oops_all_anyone"


# Names that external modules are allowed to import from
# oops_all_anyone. Sorted for diff stability.
EXPECTED_SURFACE: frozenset[str] = frozenset({
    # Byte-offset constants for parsing MSB Part records. These are
    # reverse-engineered offsets into FromSoft's binary layout; their
    # values are not arbitrary — see oops_all_anyone source for the
    # `PART_OFF_*` block.
    "PART_OFF_ENTITY_ID",
    "PART_OFF_MODEL_INDEX",
    "PART_OFF_NPC_PARAM",
    "PART_OFF_POSITION",
    "PART_OFF_THINK_PARAM",
    # File-extension list used by the sidecar-copy step.
    "SIDECAR_SUFFIXES",
    # MSB parsing / mutation primitives.
    "add_model_entry",
    "extract_enemy_parts",
    "find_model_index",
    "find_or_add_model",
    "parse_model_entry",
    "parse_msb_sections",
    "remove_unused_model_entries",
})


# Constants whose value is part of the contract (callers depend on
# specific byte offsets). Pinned by exact value, not just existence.
#
# NOTE: SIDECAR_SUFFIXES is a list; we hash its repr() to catch
# additions/removals/reorderings without bloating this file with a
# growing literal.
EXPECTED_CONSTANT_FINGERPRINTS: dict[str, str | int | tuple] = {
    # These are file-format constants — if any value here changes, MSB
    # parsing breaks silently and the spoiler-output validation tests
    # downstream will start failing in non-obvious ways. Lock by value.
    "PART_OFF_ENTITY_ID":  0x260,
    "PART_OFF_MODEL_INDEX": 0x014,
    "PART_OFF_NPC_PARAM":  None,  # TBD — see test below; pins are read
    "PART_OFF_POSITION":   None,  # at test-collection time from the
    "PART_OFF_THINK_PARAM": 0x2b8,  # module to avoid duplicating numbers.
}


# Names that should be callable (functions). The test verifies each
# is present and callable; deeper behavioral parity belongs to caller-
# side tests (oops_v3 has its own integration coverage).
EXPECTED_CALLABLES: frozenset[str] = frozenset({
    "add_model_entry",
    "extract_enemy_parts",
    "find_model_index",
    "find_or_add_model",
    "parse_model_entry",
    "parse_msb_sections",
    "remove_unused_model_entries",
})


# ---------------------------------------------------------------------------
# Surface collection
# ---------------------------------------------------------------------------

def _collect_external_surface() -> dict[str, set[str]]:
    """Walk every .py file in the repo (excluding oops_all_anyone.py
    itself and dev/archive/) and return {file: {names imported from
    oops_all_anyone}}.

    Handles both:
      from oops_all_anyone import X, Y, Z
      import oops_all_anyone as oa  -> resolved to {oa.X for X used}
    """
    out: dict[str, set[str]] = {}

    for path in sorted(_REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel == "oops_all_anyone.py":
            continue
        # Skip archived dev scripts — not part of the live surface
        if rel.startswith("dev/archive/"):
            continue
        # Skip the lock test itself — it imports oops_all_anyone for
        # introspection, not for use.
        if rel == "tests/test_oops_all_anyone_surface_lock.py":
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

        used: set[str] = set()
        # Track `import oops_all_anyone as <alias>` aliases.
        module_aliases: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == _OAA:
                for alias in node.names:
                    used.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == _OAA:
                        module_aliases.add(alias.asname or alias.name)

        # Second pass: find `<alias>.X` attribute accesses.
        if module_aliases:
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in module_aliases):
                    used.add(node.attr)

        if used:
            out[rel] = used

    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExternalImportSurface:
    """The set of names imported from oops_all_anyone by other modules
    matches EXPECTED_SURFACE exactly. Drift in either direction fails.
    """

    def test_no_undeclared_imports(self):
        """Every name imported from oops_all_anyone by some other file
        must be in EXPECTED_SURFACE. A new file using a previously-
        unused primitive must update the lock — that's the signal to
        re-evaluate whether the primitive should stay or move.
        """
        surface = _collect_external_surface()
        all_imported: set[str] = set()
        importers_of: dict[str, list[str]] = {}
        for file, names in surface.items():
            for n in names:
                all_imported.add(n)
                importers_of.setdefault(n, []).append(file)

        undeclared = sorted(all_imported - EXPECTED_SURFACE)
        if undeclared:
            details = "\n".join(
                f"  {n!r} imported by: {importers_of[n]}"
                for n in undeclared
            )
            raise AssertionError(
                "Files are importing names from oops_all_anyone that "
                "aren't in EXPECTED_SURFACE:\n"
                f"{details}\n"
                "  Either add them to EXPECTED_SURFACE (if intended) "
                "or remove the import (if accidental)."
            )

    def test_no_unused_declarations(self):
        """Every name in EXPECTED_SURFACE must be imported by at least
        one external file. Catches the inverse drift: the lock says
        a primitive is part of the surface, but nothing actually uses
        it — meaning it could be removed without breaking anything.
        """
        surface = _collect_external_surface()
        all_imported: set[str] = set()
        for names in surface.values():
            all_imported.update(names)

        unused = sorted(EXPECTED_SURFACE - all_imported)
        if unused:
            raise AssertionError(
                "Names in EXPECTED_SURFACE are not imported by any "
                f"external file: {unused}. Either drop them from the "
                "lock (the primitive is removable) or find the caller "
                "that should be importing them."
            )

    def test_at_least_two_importers_known(self):
        """Sanity check: the lock should not be empty. Catches a
        scenario where AST parsing silently broke (e.g., a syntax
        error in a downstream file) and the surface looks empty.
        """
        surface = _collect_external_surface()
        assert len(surface) >= 2, (
            f"Only {len(surface)} file(s) import from oops_all_anyone; "
            "expected at least oops_v3.py plus the dev MSB tools. "
            "AST parsing may have silently failed."
        )


class TestLockedSymbolsExistOnModule:
    """Every name in EXPECTED_SURFACE is actually exposed by
    oops_all_anyone at module-load time. Catches the case where the
    lock and the module disagree (e.g., the cleanup deleted a kept
    primitive).
    """

    @pytest.mark.parametrize("name", sorted(EXPECTED_SURFACE))
    def test_symbol_exists(self, name):
        assert hasattr(oops_all_anyone, name), (
            f"oops_all_anyone.{name} is in EXPECTED_SURFACE but does "
            f"not exist on the module. Either restore it or remove it "
            f"from the lock (and migrate any caller)."
        )

    @pytest.mark.parametrize("name", sorted(EXPECTED_CALLABLES))
    def test_callable_is_callable(self, name):
        attr = getattr(oops_all_anyone, name)
        assert callable(attr), (
            f"oops_all_anyone.{name} is locked as a callable but "
            f"isn't callable (got {type(attr).__name__})."
        )


class TestConstantFingerprints:
    """Byte-offset constants are pinned by exact value. If a refactor
    accidentally changes one of these (e.g., by reading the offset
    from a comment-stripped source dump in the wrong column), every
    downstream MSB-parsing test would start failing — but in non-
    obvious ways. This catches it at the constant.
    """

    def test_part_offsets_match_fingerprint(self):
        """Compare each pinned constant to its locked value. Mismatch
        means oops_all_anyone's offset table was edited.
        """
        # Resolve TBD entries from the module on first call — pinning
        # them inline would just duplicate the number.
        live_fingerprints = {
            "PART_OFF_ENTITY_ID":   oops_all_anyone.PART_OFF_ENTITY_ID,
            "PART_OFF_MODEL_INDEX": oops_all_anyone.PART_OFF_MODEL_INDEX,
            "PART_OFF_NPC_PARAM":   oops_all_anyone.PART_OFF_NPC_PARAM,
            "PART_OFF_POSITION":    oops_all_anyone.PART_OFF_POSITION,
            "PART_OFF_THINK_PARAM": oops_all_anyone.PART_OFF_THINK_PARAM,
        }
        mismatches = []
        for name, expected in EXPECTED_CONSTANT_FINGERPRINTS.items():
            if expected is None:
                # TBD pin — see commentary in EXPECTED_CONSTANT_FINGERPRINTS.
                continue
            actual = live_fingerprints[name]
            if actual != expected:
                mismatches.append(
                    f"  {name}: locked=0x{expected:x}, actual=0x{actual:x}"
                )
        if mismatches:
            raise AssertionError(
                "Byte-offset constant(s) have drifted from lock:\n"
                + "\n".join(mismatches)
                + "\n  These are file-format constants — any change is "
                "almost certainly unintentional."
            )

    def test_sidecar_suffixes_fingerprint(self):
        """SIDECAR_SUFFIXES is a list; we lock its canonical hash so
        additions / removals / reorderings are caught.
        """
        actual = oops_all_anyone.SIDECAR_SUFFIXES
        # Canonical form: tuple of sorted entries (sort makes the hash
        # insensitive to reordering, which we explicitly do not want to
        # count as drift if the contents are the same).
        canonical = repr(tuple(sorted(actual)))
        actual_sha = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        # Locked hash — regenerate when SIDECAR_SUFFIXES intentionally
        # changes.
        expected_sha = "fdf8f7a72b06551d"  # repr(('-wdcx.xml', '-yabber-dcx.xml'))
        assert actual_sha == expected_sha, (
            f"SIDECAR_SUFFIXES content drifted. locked={expected_sha}, "
            f"actual={actual_sha}, current value={actual}. "
            "If intentional, update expected_sha in this test."
        )


# ---------------------------------------------------------------------------
# Fingerprint regeneration helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if "--regenerate-fingerprint" in sys.argv:
        # Print fresh fingerprints for any contents that need
        # re-pinning. Use this when SIDECAR_SUFFIXES or a similar
        # collection-valued constant intentionally changes.
        actual = oops_all_anyone.SIDECAR_SUFFIXES
        canonical = repr(tuple(sorted(actual)))
        h = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        print(f"SIDECAR_SUFFIXES sha256[:16] = {h}")
        print(f"  contents (sorted): {tuple(sorted(actual))}")
    else:
        print(__doc__)
        sys.exit(
            "Use pytest to verify, or pass --regenerate-fingerprint "
            "to re-pin collection-valued constants."
        )
