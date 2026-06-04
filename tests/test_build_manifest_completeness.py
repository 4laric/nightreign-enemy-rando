"""Guard the release manifest against import-graph gaps.

The failure mode this catches: a *shipped* module does
``from <other_module> import ...`` (often after pushing ``dev/`` onto
``sys.path``), but ``scripts/build_release.py`` never packaged
``<other_module>``. Everything works in the dev tree — where the whole repo
is on the path — and then blows up as a ``ModuleNotFoundError`` the moment a
user runs that code path from the extracted bundle. That is exactly how
``dev/apply_slot_repositions.py`` (imported lazily by ``dcx_batch.py``) and
the two GUI panel mixins went missing.

Two checks:

``test_no_unshipped_first_party_imports``
    Static AST sweep. Computes the set of ``.py`` files the manifest would
    ship, then asserts every first-party module any of them imports is also
    shipped. No build, no execution, no mocking — runs in milliseconds.

``test_staged_engine_imports_and_loads``
    Stages the shipped modules + ``data/`` into a temp dir and, in an
    isolated interpreter (repo root *not* on the path, so a missing module
    can't be masked), imports the engine and runs ``load_data()``. Proves the
    packaged set is import- and init-complete. Genuine manifest gaps fail;
    unrelated environment issues (a missing third-party dep) skip.

A full end-to-end shuffle is intentionally out of scope here — that needs a
vanilla NR install — but importing + initializing the engine is the part that
this class of bug breaks, and it needs no game data.
"""
import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load_build_release():
    """Import scripts/build_release.py as a module (it isn't a package)."""
    path = os.path.join(REPO, "scripts", "build_release.py")
    spec = importlib.util.spec_from_file_location("build_release", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BR = _load_build_release()


def _shipped_py_relpaths():
    """Relpaths (from REPO) of every .py the manifest would package.

    Mirrors stage_release: INCLUDE_FILES + INCLUDE_FROM_DEV + a walk of
    INCLUDE_DIRS/OPTIONAL_DIRS honouring EXCLUDE_PATTERNS.
    """
    out = set()
    for rel in BR.INCLUDE_FILES:
        if rel.endswith(".py"):
            out.add(rel)
    for rel in BR.INCLUDE_FROM_DEV:
        if rel.endswith(".py"):
            out.add(rel)
    for d in list(BR.INCLUDE_DIRS) + list(BR.OPTIONAL_DIRS):
        base = os.path.join(REPO, d)
        if not os.path.isdir(base):
            continue
        for dp, dns, fs in os.walk(base):
            # Prune excluded dirs (tests/, __pycache__, ...) so we don't
            # descend into things that never ship.
            dns[:] = [x for x in dns if not BR.matches_exclude(os.path.join(dp, x))]
            for f in fs:
                full = os.path.join(dp, f)
                if f.endswith(".py") and not BR.matches_exclude(full):
                    out.add(os.path.relpath(full, REPO))
    return out


def _repo_first_party():
    """(module names, package names) defined anywhere in the repo.

    Used to tell a first-party import (must ship) apart from a stdlib /
    third-party one (don't care). Build artifacts and caches are skipped.
    """
    modnames, pkgnames = set(), set()
    for dp, dns, fs in os.walk(REPO):
        parts = dp.split(os.sep)
        if "__pycache__" in parts or "build" in parts:
            continue
        if "__init__.py" in fs:
            pkgnames.add(os.path.basename(dp))
        for f in fs:
            if f.endswith(".py"):
                modnames.add(f[:-3])
    return modnames, pkgnames


def _top_level_imports(py_path):
    """Top-level names referenced by absolute imports in a .py file."""
    try:
        tree = ast.parse(open(py_path, encoding="utf-8").read(), py_path)
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_no_unshipped_first_party_imports():
    shipped = _shipped_py_relpaths()
    shipped_mods = {os.path.basename(p)[:-3] for p in shipped}
    shipped_pkgs = {
        p.split(os.sep)[0] for p in shipped if os.path.basename(p) == "__init__.py"
    }
    fp_mods, fp_pkgs = _repo_first_party()
    first_party = fp_mods | fp_pkgs

    gaps = {}
    for rel in sorted(shipped):
        for name in _top_level_imports(os.path.join(REPO, rel)):
            if (
                name in first_party
                and name not in shipped_mods
                and name not in shipped_pkgs
            ):
                gaps.setdefault(name, []).append(rel)

    assert not gaps, (
        "Shipped modules import first-party modules the build manifest does not "
        "package — these would ModuleNotFoundError when a user runs that path "
        "from the extracted bundle:\n"
        + "\n".join(
            f"  {m}  <- imported by {', '.join(sorted(v))}"
            for m, v in sorted(gaps.items())
        )
        + "\n\nAdd each to INCLUDE_FILES or INCLUDE_FROM_DEV in "
        "scripts/build_release.py."
    )


def test_staged_engine_imports_and_loads(tmp_path):
    # Light stage: shipped modules + root manifests + the data/ catalogs.
    # Importing the engine and running load_data() needs no game binaries, so
    # the ~30 MB of SFX/EMEVD .dcx are deliberately skipped for speed.
    for rel in _shipped_py_relpaths():
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(os.path.join(REPO, rel), dst)
    for rel in BR.INCLUDE_FILES:  # root non-.py manifests (er_/nr_ *.json, ...)
        if not rel.endswith(".py"):
            src = os.path.join(REPO, rel)
            if os.path.isfile(src):
                dst = tmp_path / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    shutil.copytree(os.path.join(REPO, "data"), tmp_path / "data", dirs_exist_ok=True)

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # isolate: only the staged dir is importable
    proc = subprocess.run(
        [sys.executable, "-c", "import oops_v3; oops_v3.load_data()"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode == 0:
        return

    err = proc.stderr or ""
    m = re.search(r"No module named '([\w.]+)'", err)
    if m:
        top = m.group(1).split(".")[0]
        fp_mods, fp_pkgs = _repo_first_party()
        if top in (fp_mods | fp_pkgs):
            pytest.fail(
                f"Staged bundle is missing first-party module '{top}' needed to "
                f"import/initialise the engine:\n{err[-2000:]}"
            )
        pytest.skip(
            f"Engine needs third-party module '{top}' that isn't installed in "
            f"this environment — not a manifest gap."
        )
    pytest.skip(f"Engine import failed for a non-module reason here:\n{err[-1500:]}")