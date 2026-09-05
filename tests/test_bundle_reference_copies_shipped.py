"""Regression: every BUNDLED_INSTALLS entry must be installable by the in-app
"Install bundled mod files" button — into ANY me3 package, including a
separate profile chosen via the "point at an existing me3 profile" feature.

The button (oops_rando_gui._install_bundled_files) resolves each bundle's
source via bundle_installer.resolve_bundle_source, which accepts two sources:
  1. the _rando/<bundle_dir>/ reference copy (shipped for most bundles), or
  2. a fallback to the bundle's single deploy-path copy in the rando's OWN
     package (PACKAGE_DIR) — used for ship-once bundles in
     build_release.SKIP_REFERENCE_COPY_FOR (e.g. the ~182MB sfx blob, never
     duplicated as a reference copy).

This is the bundled_sfx regression guard: sfx ships ONCE (no 182MB dupe),
but the button must STILL be able to deploy it into a pointed-at profile via
the deploy-path fallback. These tests fail loudly if a bundle becomes
un-installable, or if a ship-once bundle loses its deploy-path fallback.
"""
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))
sys.path.insert(0, REPO_ROOT)

import build_release as br                                  # noqa: E402
from bundle_installer import (                              # noqa: E402
    BUNDLED_INSTALLS, list_bundle_content_files, resolve_bundle_source)


def test_reference_copies_master_switch_on():
    assert br.SHIP_BUNDLE_REFERENCE_COPIES is True, (
        "SHIP_BUNDLE_REFERENCE_COPIES is off — no bundle ships a reference "
        "copy, so the install button loses its primary source.")


def _stage_shipped_layout(tmp):
    """Build a minimal shipped-profile layout in tmp: a _rando/ with a
    reference copy for every NON-ship-once bundle, and a package dir
    (PACKAGE_DIR analogue) with a deploy-path copy for every bundle."""
    rando = os.path.join(tmp, '_rando')
    pkg = os.path.join(tmp, 'nrando')
    for e in BUNDLED_INSTALLS:
        deploy = (os.path.join(pkg, e['target_subpath'])
                  if e['target_subpath'] else pkg)
        os.makedirs(deploy, exist_ok=True)
        open(os.path.join(deploy, e['critical_file']), 'w', encoding="utf-8").write('x')
        if e['bundle_dir'] not in br.SKIP_REFERENCE_COPY_FOR:
            ref = os.path.join(rando, e['bundle_dir'])
            os.makedirs(ref, exist_ok=True)
            open(os.path.join(ref, e['critical_file']), 'w', encoding="utf-8").write('x')
            open(os.path.join(ref, 'README.md'), 'w', encoding="utf-8").write('doc')
    return rando, pkg


def test_every_bundle_is_installable_in_a_shipped_layout():
    with tempfile.TemporaryDirectory() as tmp:
        rando, pkg = _stage_shipped_layout(tmp)
        for e in BUNDLED_INSTALLS:
            resolved = resolve_bundle_source(e, rando, pkg)
            assert resolved is not None, (
                f"{e['bundle_dir']} has no install source in a shipped "
                "layout — the button would skip it.")
            src_dir, files = resolved
            assert files, f"{e['bundle_dir']} resolved to an empty file list"


def test_ship_once_bundles_use_the_deploy_path_fallback():
    # For every SKIP_REFERENCE_COPY_FOR bundle: with NO reference copy the
    # resolver must still find it via the deploy path, and must return None
    # if the package dir is unavailable (proving it relies on the fallback).
    with tempfile.TemporaryDirectory() as tmp:
        rando, pkg = _stage_shipped_layout(tmp)
        for e in BUNDLED_INSTALLS:
            if e['bundle_dir'] not in br.SKIP_REFERENCE_COPY_FOR:
                continue
            assert not os.path.isdir(os.path.join(rando, e['bundle_dir']))
            via_deploy = resolve_bundle_source(e, rando, pkg)
            assert via_deploy is not None and e['target_subpath'] in via_deploy[0], (
                f"{e['bundle_dir']} did not resolve via the deploy path")
            assert resolve_bundle_source(e, rando, None) is None, (
                f"{e['bundle_dir']} resolved without a package dir")


def test_install_button_sources_exist_in_repo():
    # Some critical files are gitignored game-derived binaries
    # (e.g. bundled_aicommon/*.dcx) and are absent from fresh source
    # checkouts (CI). Per AGENTS.md, asset-dependent checks must skip,
    # not fail, when the assets are absent — so verify every bundle whose
    # critical file IS present, then skip if any were missing.
    missing = []
    for e in BUNDLED_INSTALLS:
        bundle_dir = os.path.join(REPO_ROOT, e['bundle_dir'])
        critical = os.path.join(bundle_dir, e['critical_file'])
        assert os.path.isdir(bundle_dir), f"missing bundle dir: {e['bundle_dir']}"
        if not os.path.isfile(critical):
            missing.append(f"{e['bundle_dir']}/{e['critical_file']}")
            continue
        assert list_bundle_content_files(bundle_dir), (
            f"{e['bundle_dir']}/ has no deployable files after filtering")
    if missing:
        pytest.skip("gitignored game asset(s) not in source checkout: "
                    + ", ".join(missing))
