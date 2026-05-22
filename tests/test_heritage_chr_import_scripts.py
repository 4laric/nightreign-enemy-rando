"""Tests for the script-import helpers in dev/heritage_chr_import.py.

Added in v0.24.58 when _chr_import was extended to also copy AI scripts
(previously chr-only). Validates the script-file discovery, prefix
mapping, and .dcx-suffix normalization used by the GUI's spoiler-driven
import path.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'dev'))

from heritage_chr_import import (  # noqa: E402
    cp_to_script_prefix,
    list_script_files_for_prefix,
    script_basename_for_compare,
)


class TestCpToScriptPrefix:
    def test_standard_c_prefix(self):
        assert cp_to_script_prefix('c5210') == '5210'
        assert cp_to_script_prefix('c3000') == '3000'
        assert cp_to_script_prefix('c4377') == '4377'

    def test_invalid_inputs(self):
        assert cp_to_script_prefix('c3') is None  # too short
        assert cp_to_script_prefix('5210') is None  # missing 'c' prefix
        assert cp_to_script_prefix('') is None
        assert cp_to_script_prefix('xx') is None

    def test_longer_prefix_truncates(self):
        """c5210_extra (rare, e.g. div) maps just on the 4-digit core."""
        assert cp_to_script_prefix('c5210_div01') == '5210'


class TestScriptBasenameForCompare:
    def test_strips_dcx(self):
        assert (script_basename_for_compare('521000_battle.luabnd.dcx')
                == '521000_battle.luabnd')

    def test_leaves_uncompressed_alone(self):
        assert (script_basename_for_compare('521000_battle.luabnd')
                == '521000_battle.luabnd')

    def test_normalization_roundtrip(self):
        """If source has .luabnd and target has .luabnd.dcx, both
        normalize to the same key — that's the whole point."""
        a = script_basename_for_compare('521000_battle.luabnd')
        b = script_basename_for_compare('521000_battle.luabnd.dcx')
        assert a == b


class TestListScriptFilesForPrefix:
    @pytest.fixture
    def script_folder(self, tmp_path):
        """Populate a temp dir with realistic ER-style script filenames."""
        files = [
            # c5210 Divine Beast Dancing Lion — multiple variants
            '521000_battle.luabnd.dcx',
            '521000_logic.luabnd.dcx',
            '521001_battle.luabnd.dcx',
            '521001_logic.luabnd.dcx',
            # c3000 (uncompressed for variety, ER source-side variant)
            '300000_battle.luabnd',
            '300000_logic.luabnd',
            # c4377 Battlemage — just one entry
            '437700_battle.luabnd.dcx',
            # Noise that shouldn't match
            'not_a_script.bnd',
            'README.txt',
            '521000_battle.txt',
            # Edge: looks similar but isn't a luabnd
            '521000_battle.hkx',
        ]
        for f in files:
            (tmp_path / f).touch()
        return str(tmp_path)

    def test_finds_all_scripts_for_chr(self, script_folder):
        files = list_script_files_for_prefix(script_folder, 'c5210')
        assert files == [
            '521000_battle.luabnd.dcx',
            '521000_logic.luabnd.dcx',
            '521001_battle.luabnd.dcx',
            '521001_logic.luabnd.dcx',
        ]

    def test_finds_uncompressed_scripts(self, script_folder):
        """ER source ships .luabnd uncompressed; the importer must
        still pick them up."""
        files = list_script_files_for_prefix(script_folder, 'c3000')
        assert files == [
            '300000_battle.luabnd',
            '300000_logic.luabnd',
        ]

    def test_single_script_chr(self, script_folder):
        files = list_script_files_for_prefix(script_folder, 'c4377')
        assert files == ['437700_battle.luabnd.dcx']

    def test_chr_with_no_scripts(self, script_folder):
        """A c-prefix that exists in the chr roster but ships no AI
        scripts (e.g. simple grunts that share a shared AI). Returns []."""
        files = list_script_files_for_prefix(script_folder, 'c9999')
        assert files == []

    def test_does_not_pick_up_non_luabnd(self, script_folder):
        """Files like 521000_battle.hkx or .txt that share the numeric
        prefix must NOT be returned."""
        files = list_script_files_for_prefix(script_folder, 'c5210')
        for f in files:
            assert f.endswith('.luabnd') or f.endswith('.luabnd.dcx')

    def test_missing_folder_returns_empty(self):
        files = list_script_files_for_prefix('/no/such/dir', 'c5210')
        assert files == []

    def test_invalid_prefix_returns_empty(self, script_folder):
        files = list_script_files_for_prefix(script_folder, 'invalid')
        assert files == []

    def test_returned_list_is_sorted(self, script_folder):
        """Stable ordering matters for deterministic logs / copy order."""
        files = list_script_files_for_prefix(script_folder, 'c5210')
        assert files == sorted(files)


class TestIntegrationWithChrCopyFlow:
    """Sanity-check that script discovery integrates with the typical
    spoiler-driven flow: given a list of c-prefixes, you can find their
    scripts and dedupe against an already-populated target dir."""

    def test_dedup_against_target(self, tmp_path):
        source_script = tmp_path / 'source_script'
        target_script = tmp_path / 'target_script'
        source_script.mkdir()
        target_script.mkdir()

        # Source has both variants
        (source_script / '521000_battle.luabnd.dcx').touch()
        (source_script / '521000_logic.luabnd.dcx').touch()
        # Target already has the battle script
        (target_script / '521000_battle.luabnd.dcx').touch()

        src_files = list_script_files_for_prefix(str(source_script), 'c5210')
        tgt_basenames = {
            script_basename_for_compare(f)
            for f in os.listdir(str(target_script))
        }

        to_copy = [f for f in src_files
                   if script_basename_for_compare(f) not in tgt_basenames]
        assert to_copy == ['521000_logic.luabnd.dcx']

    def test_dedup_handles_dcx_mismatch(self, tmp_path):
        """Source .luabnd vs target .luabnd.dcx should be treated as
        the same file (target wins, skip the copy)."""
        source_script = tmp_path / 'source_script'
        target_script = tmp_path / 'target_script'
        source_script.mkdir()
        target_script.mkdir()

        (source_script / '300000_battle.luabnd').touch()  # uncompressed
        (target_script / '300000_battle.luabnd.dcx').touch()  # compressed

        src_files = list_script_files_for_prefix(str(source_script), 'c3000')
        tgt_basenames = {
            script_basename_for_compare(f)
            for f in os.listdir(str(target_script))
        }

        to_copy = [f for f in src_files
                   if script_basename_for_compare(f) not in tgt_basenames]
        # Source's .luabnd should be considered already-present because
        # target has the .luabnd.dcx form.
        assert to_copy == []
