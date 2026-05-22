"""Tests for v0.24.66's bulk dir-to-dir file copy.

Used by _chr_import and _chr_bulk_import to deploy MMV's SFX and
material directories alongside chr files + scripts + aicommon. Without
these, cross-game chrs spawn invisible or freeze on first SFX-triggering
animation.

Discovered via user playtest: copying MMV's entire sfx/ and material/
dirs unlocked the full MMV roster (Romina proof case, leading to the
v0.24.65 broken_runtime_chrs lift). v0.24.66 automates the copy as
part of chr-import.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'dev'))

from heritage_chr_import import copy_bulk_dir_files  # noqa: E402


class TestCopyBulkDirFiles:
    def test_basic_copy(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        (src / 'a.ffxbnd.dcx').write_bytes(b'A' * 100)
        (src / 'b.ffxbnd.dcx').write_bytes(b'B' * 50)

        res = copy_bulk_dir_files(str(src), str(dst))

        assert set(res['copied']) == {'a.ffxbnd.dcx', 'b.ffxbnd.dcx'}
        assert res['skipped'] == []
        assert res['errors'] == []
        assert res['bytes'] == 150
        assert (dst / 'a.ffxbnd.dcx').read_bytes() == b'A' * 100
        assert (dst / 'b.ffxbnd.dcx').read_bytes() == b'B' * 50

    def test_ext_filter_includes_only_matching(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        (src / 'sfx.ffxbnd.dcx').write_bytes(b'SFX')
        (src / 'metadata.xml').write_text('<xml/>')
        (src / 'debug.txt').write_text('debug')

        res = copy_bulk_dir_files(
            str(src), str(dst),
            ext_filter=('.ffxbnd.dcx',))

        assert res['copied'] == ['sfx.ffxbnd.dcx']
        assert not (dst / 'metadata.xml').exists()
        assert not (dst / 'debug.txt').exists()

    def test_ext_filter_case_insensitive(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        # Mixed case extensions in the wild — case-insensitive match
        (src / 'BUNDLE.FFXBND.DCX').write_bytes(b'X')
        (src / 'lowercase.ffxbnd.dcx').write_bytes(b'Y')

        res = copy_bulk_dir_files(
            str(src), str(dst),
            ext_filter=('.ffxbnd.dcx',))

        assert set(res['copied']) == {'BUNDLE.FFXBND.DCX', 'lowercase.ffxbnd.dcx'}

    def test_ext_filter_multiple_extensions(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        (src / 'a.ffxbnd.dcx').write_bytes(b'1')
        (src / 'b.ffxbnd').write_bytes(b'2')
        (src / 'c.xml').write_text('<x/>')

        res = copy_bulk_dir_files(
            str(src), str(dst),
            ext_filter=('.ffxbnd.dcx', '.ffxbnd'))

        assert set(res['copied']) == {'a.ffxbnd.dcx', 'b.ffxbnd'}
        assert 'c.xml' not in res['copied']

    def test_no_filter_copies_everything(self, tmp_path):
        # For material dir — no extension filter, copy all regular files
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        (src / 'a.matbinbnd.dcx').write_bytes(b'1')
        (src / 'b.matbin').write_bytes(b'2')
        (src / 'c.mtdbnd.dcx').write_bytes(b'3')

        res = copy_bulk_dir_files(str(src), str(dst))

        assert len(res['copied']) == 3

    def test_skips_subdirectories(self, tmp_path):
        # Flat dir copy only — nested subdirs are not recursed
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        (src / 'top.dcx').write_bytes(b'top')
        (src / 'nested').mkdir()
        (src / 'nested' / 'deep.dcx').write_bytes(b'deep')

        res = copy_bulk_dir_files(str(src), str(dst))

        assert res['copied'] == ['top.dcx']
        assert not (dst / 'nested').exists()

    def test_idempotent_skip_existing(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir(); dst.mkdir()
        (src / 'a.dcx').write_bytes(b'NEW')
        (dst / 'a.dcx').write_bytes(b'EXISTING')

        res = copy_bulk_dir_files(str(src), str(dst), overwrite=False)

        # Target unchanged, recorded as skipped
        assert (dst / 'a.dcx').read_bytes() == b'EXISTING'
        assert res['skipped'] == ['a.dcx']
        assert res['copied'] == []
        assert res['bytes'] == 0

    def test_overwrite_replaces_existing(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir(); dst.mkdir()
        (src / 'a.dcx').write_bytes(b'NEW')
        (dst / 'a.dcx').write_bytes(b'OLD')

        res = copy_bulk_dir_files(str(src), str(dst), overwrite=True)

        assert (dst / 'a.dcx').read_bytes() == b'NEW'
        assert res['copied'] == ['a.dcx']
        assert res['skipped'] == []

    def test_dry_run_does_not_write(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()
        (src / 'a.dcx').write_bytes(b'X' * 100)

        res = copy_bulk_dir_files(str(src), str(dst), dry_run=True)

        # Recorded as copied (or would-be-copied), but no actual writes
        assert res['copied'] == ['a.dcx']
        assert res['bytes'] == 100
        # Target dir not created, target file not present
        assert not (dst / 'a.dcx').exists()

    def test_creates_target_dir_if_missing(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'deep' / 'nested' / 'dst'
        src.mkdir()
        (src / 'a.dcx').write_bytes(b'1')

        copy_bulk_dir_files(str(src), str(dst))

        assert dst.exists()
        assert (dst / 'a.dcx').exists()

    def test_missing_source_returns_empty(self, tmp_path):
        # If user hasn't pointed at a real source SFX/material dir,
        # the function should return empty results without raising.
        # This matches the "best-effort copy" pattern of _chr_import.
        res = copy_bulk_dir_files('/nonexistent', str(tmp_path / 'dst'))

        assert res == {'copied': [], 'skipped': [], 'bytes': 0, 'errors': []}

    def test_empty_source_dir(self, tmp_path):
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir()

        res = copy_bulk_dir_files(str(src), str(dst))

        assert res == {'copied': [], 'skipped': [], 'bytes': 0, 'errors': []}

    def test_none_source_returns_empty(self, tmp_path):
        # Resolvers may return None or '' for unconfigured paths
        assert copy_bulk_dir_files(None, str(tmp_path)) == {
            'copied': [], 'skipped': [], 'bytes': 0, 'errors': []}
        assert copy_bulk_dir_files('', str(tmp_path)) == {
            'copied': [], 'skipped': [], 'bytes': 0, 'errors': []}

    def test_mixed_filtered_and_skipped(self, tmp_path):
        # Realistic scenario: some files already in target, some new,
        # some excluded by filter. All accounting should be correct.
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        src.mkdir(); dst.mkdir()
        (src / 'a.ffxbnd.dcx').write_bytes(b'A' * 100)  # new
        (src / 'b.ffxbnd.dcx').write_bytes(b'B' * 200)  # already in target
        (src / 'c.xml').write_text('x')                  # filtered out
        (dst / 'b.ffxbnd.dcx').write_bytes(b'OLD')

        res = copy_bulk_dir_files(
            str(src), str(dst),
            ext_filter=('.ffxbnd.dcx',),
            overwrite=False)

        assert res['copied'] == ['a.ffxbnd.dcx']
        assert res['skipped'] == ['b.ffxbnd.dcx']
        # Filtered c.xml doesn't appear in either list
        assert 'c.xml' not in res['copied']
        assert 'c.xml' not in res['skipped']
        assert res['bytes'] == 100  # only the copied file counts
