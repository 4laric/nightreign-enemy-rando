"""Tests for v0.24.64's bundled aicommon copy.

The bundled_aicommon/ directory in the project root ships MMV-superset
aicommon files. Any chr-import flow (_chr_import or _chr_bulk_import)
copies these alongside per-chr battle/logic scripts so cross-game and
DLC chrs (c8300 Dragonslayer Armor, c8500 Manus, etc.) get the
goal-table constants they need.

Background: user playtest seed 618106 (v0.24.62) reported c8300
Dragonslayer Armor freeze at m49_29 NB1-duo slot. Decompilation of
MMV scripts showed 830000_battle.luabnd's RegisterTableGoal references
GOAL_DragonGuardianKnight_316000, defined only in
aicommon_dlc01.luabnd. Without that file deployed, the constant
resolves to nil → freeze. 3-way diff (ER/NR/MMV) confirmed MMV's
aicommon is a strict superset of NR's (922 shared names, 0 conflicts,
0 NR-only names missing from MMV).
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'dev'))

from heritage_chr_import import (  # noqa: E402
    AICOMMON_FILE_RE,
    list_bundled_aicommon_files,
    copy_bundled_aicommon,
    script_basename_for_compare,
)


class TestAicommonFileRegex:
    """The regex must match exactly the aicommon files we ship, both .luabnd
    (decompressed dev form) and .luabnd.dcx (deployed form)."""

    def test_matches_aicommon_dcx(self):
        assert AICOMMON_FILE_RE.match('aicommon.luabnd.dcx')

    def test_matches_aicommon_plain(self):
        assert AICOMMON_FILE_RE.match('aicommon.luabnd')

    def test_matches_dlc01(self):
        assert AICOMMON_FILE_RE.match('aicommon_dlc01.luabnd.dcx')

    def test_matches_dlc02(self):
        # ER ships aicommon_dlc02 for SoTE's second DLC. Future-proof.
        assert AICOMMON_FILE_RE.match('aicommon_dlc02.luabnd.dcx')

    def test_does_not_match_per_chr_script(self):
        # Per-chr scripts have a different prefix shape (NNNNNN_battle).
        # These are handled by SCRIPT_FILE_RE, not AICOMMON_FILE_RE.
        assert not AICOMMON_FILE_RE.match('830000_battle.luabnd.dcx')

    def test_does_not_match_random_file(self):
        assert not AICOMMON_FILE_RE.match('README.md')
        assert not AICOMMON_FILE_RE.match('aicommon-yabber-dcx.xml')


class TestListBundledAicommonFiles:
    def test_lists_files_in_dir(self, tmp_path):
        # Write fake aicommon files
        (tmp_path / 'aicommon.luabnd.dcx').write_bytes(b'X' * 100)
        (tmp_path / 'aicommon_dlc01.luabnd.dcx').write_bytes(b'X' * 50)
        # Plus some non-aicommon files that should be ignored
        (tmp_path / 'README.md').write_text('docs')
        (tmp_path / '830000_battle.luabnd.dcx').write_bytes(b'X' * 200)

        result = list_bundled_aicommon_files(str(tmp_path))
        names = [f[0] for f in result]
        assert names == ['aicommon.luabnd.dcx', 'aicommon_dlc01.luabnd.dcx']

    def test_handles_missing_dir(self):
        assert list_bundled_aicommon_files('/nonexistent/path') == []

    def test_handles_none(self):
        assert list_bundled_aicommon_files(None) == []

    def test_empty_dir_returns_empty(self, tmp_path):
        assert list_bundled_aicommon_files(str(tmp_path)) == []


class TestCopyBundledAicommon:
    def test_copy_creates_files(self, tmp_path):
        bundle = tmp_path / 'bundle'
        target = tmp_path / 'target'
        bundle.mkdir()
        (bundle / 'aicommon.luabnd.dcx').write_bytes(b'AC' * 50)
        (bundle / 'aicommon_dlc01.luabnd.dcx').write_bytes(b'DLC' * 20)

        result = copy_bundled_aicommon(str(bundle), str(target))

        assert (target / 'aicommon.luabnd.dcx').exists()
        assert (target / 'aicommon_dlc01.luabnd.dcx').exists()
        assert (target / 'aicommon.luabnd.dcx').read_bytes() == b'AC' * 50
        assert set(result['copied']) == {'aicommon.luabnd.dcx',
                                          'aicommon_dlc01.luabnd.dcx'}
        assert result['skipped'] == []
        assert result['bytes'] == 100 + 60

    def test_dry_run_does_not_write(self, tmp_path):
        bundle = tmp_path / 'bundle'
        target = tmp_path / 'target'
        bundle.mkdir()
        (bundle / 'aicommon.luabnd.dcx').write_bytes(b'X' * 100)

        result = copy_bundled_aicommon(str(bundle), str(target), dry_run=True)

        assert not target.exists() or not (target / 'aicommon.luabnd.dcx').exists()
        assert result['copied'] == ['aicommon.luabnd.dcx']
        assert result['bytes'] == 100

    def test_skip_existing_without_overwrite(self, tmp_path):
        bundle = tmp_path / 'bundle'
        target = tmp_path / 'target'
        bundle.mkdir(); target.mkdir()
        (bundle / 'aicommon.luabnd.dcx').write_bytes(b'NEW')
        (target / 'aicommon.luabnd.dcx').write_bytes(b'OLD')

        result = copy_bundled_aicommon(str(bundle), str(target),
                                        overwrite=False)

        # Target should still have OLD content
        assert (target / 'aicommon.luabnd.dcx').read_bytes() == b'OLD'
        assert result['copied'] == []
        assert result['skipped'] == ['aicommon.luabnd.dcx']
        assert result['bytes'] == 0

    def test_overwrite_replaces_existing(self, tmp_path):
        bundle = tmp_path / 'bundle'
        target = tmp_path / 'target'
        bundle.mkdir(); target.mkdir()
        (bundle / 'aicommon.luabnd.dcx').write_bytes(b'NEW')
        (target / 'aicommon.luabnd.dcx').write_bytes(b'OLD')

        result = copy_bundled_aicommon(str(bundle), str(target),
                                        overwrite=True)

        assert (target / 'aicommon.luabnd.dcx').read_bytes() == b'NEW'
        assert result['copied'] == ['aicommon.luabnd.dcx']
        assert result['skipped'] == []

    def test_handles_dcx_vs_plain_basename_match(self, tmp_path):
        """If target has aicommon.luabnd and bundle has aicommon.luabnd.dcx,
        they're treated as the same file (matching script_basename_for_compare
        semantics — strip trailing .dcx). Skip without overwrite."""
        bundle = tmp_path / 'bundle'
        target = tmp_path / 'target'
        bundle.mkdir(); target.mkdir()
        (bundle / 'aicommon.luabnd.dcx').write_bytes(b'BUNDLE')
        # Target has the same file in .luabnd form (without .dcx)
        (target / 'aicommon.luabnd').write_bytes(b'TARGET')

        result = copy_bundled_aicommon(str(bundle), str(target),
                                        overwrite=False)

        # Original target form should not be overwritten
        assert (target / 'aicommon.luabnd').read_bytes() == b'TARGET'
        # And no new file should appear (since basename matches)
        assert not (target / 'aicommon.luabnd.dcx').exists()
        assert result['skipped'] == ['aicommon.luabnd.dcx']

    def test_missing_bundle_returns_empty(self, tmp_path):
        target = tmp_path / 'target'
        target.mkdir()

        result = copy_bundled_aicommon('/nonexistent/bundle', str(target))

        assert result == {'copied': [], 'skipped': [], 'bytes': 0}

    def test_creates_target_dir_if_missing(self, tmp_path):
        bundle = tmp_path / 'bundle'
        target = tmp_path / 'nested' / 'subdir' / 'target'
        bundle.mkdir()
        (bundle / 'aicommon.luabnd.dcx').write_bytes(b'X')

        copy_bundled_aicommon(str(bundle), str(target))

        assert target.exists()
        assert (target / 'aicommon.luabnd.dcx').exists()


class TestProjectBundleExists:
    """Smoke test that the actual project bundle is correctly shaped."""

    def test_bundle_dir_exists(self):
        d = os.path.join(ROOT, 'bundled_aicommon')
        assert os.path.isdir(d), (
            "bundled_aicommon/ should exist at project root — it's "
            "what _chr_import/_chr_bulk_import deploy as of v0.24.64")

    def test_bundle_has_aicommon(self):
        d = os.path.join(ROOT, 'bundled_aicommon')
        expected = os.path.join(d, 'aicommon.luabnd.dcx')
        assert os.path.exists(expected), (
            f"bundled_aicommon must contain aicommon.luabnd.dcx — "
            f"this is the MMV-superset manifest deployed to user mod folders")

    def test_bundle_has_aicommon_dlc01(self):
        d = os.path.join(ROOT, 'bundled_aicommon')
        expected = os.path.join(d, 'aicommon_dlc01.luabnd.dcx')
        assert os.path.exists(expected), (
            f"bundled_aicommon must contain aicommon_dlc01.luabnd.dcx — "
            f"this defines DLC-only goal constants (GOAL_DragonGuardianKnight_316000, "
            f"GOAL_Manus_850000_Battle, etc.) needed by cross-game chrs")

    def test_bundle_files_are_listable(self):
        d = os.path.join(ROOT, 'bundled_aicommon')
        files = list_bundled_aicommon_files(d)
        names = {f[0] for f in files}
        # At minimum should pick up the two we ship
        assert 'aicommon.luabnd.dcx' in names
        assert 'aicommon_dlc01.luabnd.dcx' in names

    def test_aicommon_file_sizes_reasonable(self):
        """Smoke check that we didn't ship truncated or empty files.
        MMV's aicommon should be ~135KB; aicommon_dlc01 ~5KB."""
        d = os.path.join(ROOT, 'bundled_aicommon')
        sz_main = os.path.getsize(os.path.join(d, 'aicommon.luabnd.dcx'))
        sz_dlc01 = os.path.getsize(os.path.join(d, 'aicommon_dlc01.luabnd.dcx'))
        # Allow generous tolerance — these can grow if MMV ships more chrs
        assert 80_000 < sz_main < 300_000, (
            f"aicommon.luabnd.dcx size {sz_main} outside reasonable range "
            f"— may be truncated, or MMV shipped a much-changed version")
        assert 2_000 < sz_dlc01 < 20_000, (
            f"aicommon_dlc01.luabnd.dcx size {sz_dlc01} outside reasonable range")
