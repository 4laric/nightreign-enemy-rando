"""Regression: every BUNDLED_INSTALLS entry must ship a reference copy under
_rando/ so the in-app "Install bundled mod files" button can deploy it.

Why this matters — the bundled_sfx bug:
  The install button sources each bundle from `<rando>/_rando/<bundle_dir>/`
  (oops_rando_gui._install_bundled_files) and copies it into whatever me3
  package the user has selected. When that package is a SEPARATE profile
  chosen via the "point at an existing me3 profile" feature, the button is
  the ONLY path that gets the bundled deps into it — the build's one-time
  deploy-path copy went to the rando's OWN shipped profile, not the
  pointed-at one.

  bundled_sfx used to be in SKIP_REFERENCE_COPY_FOR (no reference copy
  shipped, to save ~182MB), so it was the single bundle the button could
  not deploy into a pointed-at profile — "one file not getting copied".

These tests fail loudly if any bundle is excluded from the reference copy
again, or if a bundle's button-source goes missing. If an exclusion is ever
intentional (to shrink the zip), update this test deliberately — that's the
point: it must not regress silently.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))
sys.path.insert(0, REPO_ROOT)

import build_release as br                                  # noqa: E402
from bundle_installer import (                              # noqa: E402
    BUNDLED_INSTALLS, list_bundle_content_files)


def test_reference_copies_master_switch_on():
    assert br.SHIP_BUNDLE_REFERENCE_COPIES is True, (
        "SHIP_BUNDLE_REFERENCE_COPIES is off — no bundle ships a reference "
        "copy, so the in-app install button is disabled entirely.")


def test_every_bundle_ships_a_reference_copy():
    excluded = set(br.SKIP_REFERENCE_COPY_FOR)
    offenders = sorted(e['bundle_dir'] for e in BUNDLED_INSTALLS
                       if e['bundle_dir'] in excluded)
    assert not offenders, (
        f"{offenders} are in SKIP_REFERENCE_COPY_FOR, so the 'Install "
        "bundled mod files' button can't deploy them into a me3 package "
        "selected via 'point at an existing me3 profile' (the source dir "
        "_rando/<bundle>/ won't be shipped). If this exclusion is "
        "intentional to shrink the zip, update this test on purpose.")


def test_ship_reference_predicate_true_for_all_bundles():
    # Mirror the exact predicate build_release uses at staging + verify time
    # (build_release.py: `ship_bundle_refs and bundle_dir not in
    # SKIP_REFERENCE_COPY_FOR`). True for every bundle == every bundle gets a
    # reference copy AND verify_release requires it present (rather than
    # asserting it absent).
    for e in BUNDLED_INSTALLS:
        ships_ref = (br.SHIP_BUNDLE_REFERENCE_COPIES
                     and e['bundle_dir'] not in br.SKIP_REFERENCE_COPY_FOR)
        assert ships_ref, f"{e['bundle_dir']} would not ship a reference copy"


def test_install_button_sources_exist_in_repo():
    """Each bundle's source dir + critical_file must exist in the repo, or
    the button has nothing to copy even with the reference copy enabled."""
    for e in BUNDLED_INSTALLS:
        bundle_dir = os.path.join(REPO_ROOT, e['bundle_dir'])
        critical = os.path.join(bundle_dir, e['critical_file'])
        assert os.path.isdir(bundle_dir), f"missing bundle dir: {e['bundle_dir']}"
        assert os.path.isfile(critical), (
            f"missing critical file {e['critical_file']} in {e['bundle_dir']}/")
        assert list_bundle_content_files(bundle_dir), (
            f"{e['bundle_dir']}/ has no deployable files after filtering")
