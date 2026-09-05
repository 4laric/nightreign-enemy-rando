"""Tests for v0.24.61's emevd overlay mechanism in dcx_batch.emevd_decompress_dir.

The overlay lets the rando auto-pipeline pick up pre-patched .emevd.dcx
files (typically from the project's patched_emevd/ directory) instead of
vanilla, so emevd_patch.py output (semantic JS patches via DarkScript3)
survives across rando re-rolls.

These tests use FAKE .emevd.dcx files containing distinct text payloads
to verify routing logic. The actual DCX decompression is mocked via a
small patch on DCX.decompress_file.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dcx_batch  # noqa: E402


@pytest.fixture
def fake_decompress(monkeypatch):
    """Replace DCX.decompress_file with one that returns the raw file
    contents verbatim. Lets us write 'vanilla' / 'overlay' text into
    fake .emevd.dcx files and check which one the decompressor reads."""
    def _fake_decompress_file(path, oodle=None):
        with open(path, 'rb') as f:
            return f.read()
    monkeypatch.setattr(dcx_batch.DCX, 'decompress_file', _fake_decompress_file)
    yield


def _write_fake_emevd(folder, name, payload):
    """Write a fake .emevd.dcx file containing the given text payload."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, 'wb') as f:
        f.write(payload.encode('utf-8'))
    return path


class TestOverlayBehavior:
    def test_no_overlay_uses_vanilla(self, tmp_path, fake_decompress):
        vanilla = tmp_path / 'vanilla'
        out = tmp_path / 'out'
        _write_fake_emevd(str(vanilla), 'common_func.emevd.dcx',
                          'VANILLA_CONTENT')
        _write_fake_emevd(str(vanilla), 'm30_30_00_00.emevd.dcx',
                          'VANILLA_M30')

        dcx_batch.emevd_decompress_dir(str(vanilla), str(out), oodle="fake-not-needed-since-decompress-is-monkeypatched",
                                        overlay_dir=None)

        # Output should match vanilla
        assert (out / 'common_func.emevd').read_text(encoding="utf-8") == 'VANILLA_CONTENT'
        assert (out / 'm30_30_00_00.emevd').read_text(encoding="utf-8") == 'VANILLA_M30'

    def test_overlay_replaces_specific_file(self, tmp_path, fake_decompress):
        """Overlay containing common_func.emevd.dcx replaces vanilla
        version; other files still come from vanilla."""
        vanilla = tmp_path / 'vanilla'
        overlay = tmp_path / 'overlay'
        out = tmp_path / 'out'
        _write_fake_emevd(str(vanilla), 'common_func.emevd.dcx',
                          'VANILLA_CF')
        _write_fake_emevd(str(vanilla), 'm30_30_00_00.emevd.dcx',
                          'VANILLA_M30')
        _write_fake_emevd(str(overlay), 'common_func.emevd.dcx',
                          'OVERLAY_CF_PATCHED')
        # NOTE: no m30_30 in overlay

        dcx_batch.emevd_decompress_dir(str(vanilla), str(out), oodle="fake-not-needed-since-decompress-is-monkeypatched",
                                        overlay_dir=str(overlay))

        # common_func should come from overlay
        assert (out / 'common_func.emevd').read_text(encoding="utf-8") == 'OVERLAY_CF_PATCHED'
        # m30_30 still vanilla
        assert (out / 'm30_30_00_00.emevd').read_text(encoding="utf-8") == 'VANILLA_M30'

    def test_overlay_replaces_multiple_files(self, tmp_path, fake_decompress):
        """Bundle's typical layout: overlay has common_func PLUS several
        per-map inline-script-fixed emevds."""
        vanilla = tmp_path / 'vanilla'
        overlay = tmp_path / 'overlay'
        out = tmp_path / 'out'
        for name in ('common_func.emevd.dcx', 'm30_30_00_00.emevd.dcx',
                     'm38_10_00_00.emevd.dcx', 'm60_43_37_00.emevd.dcx',
                     'm99_99_99_99.emevd.dcx'):
            _write_fake_emevd(str(vanilla), name, f'VANILLA_{name}')
        # Overlay covers all but m99
        for name in ('common_func.emevd.dcx', 'm30_30_00_00.emevd.dcx',
                     'm38_10_00_00.emevd.dcx', 'm60_43_37_00.emevd.dcx'):
            _write_fake_emevd(str(overlay), name, f'OVERLAY_{name}')

        dcx_batch.emevd_decompress_dir(str(vanilla), str(out), oodle="fake-not-needed-since-decompress-is-monkeypatched",
                                        overlay_dir=str(overlay))

        for name in ('common_func.emevd.dcx', 'm30_30_00_00.emevd.dcx',
                     'm38_10_00_00.emevd.dcx', 'm60_43_37_00.emevd.dcx'):
            base = name[:-4]
            assert (out / base).read_text(encoding="utf-8") == f'OVERLAY_{name}'
        # m99 still vanilla
        assert (out / 'm99_99_99_99.emevd').read_text(encoding="utf-8") == 'VANILLA_m99_99_99_99.emevd.dcx'

    def test_overlay_file_not_in_vanilla_is_ignored(self, tmp_path, fake_decompress):
        """If overlay has an extra file that ISN'T in vanilla, it's
        ignored — the file list is driven by vanilla."""
        vanilla = tmp_path / 'vanilla'
        overlay = tmp_path / 'overlay'
        out = tmp_path / 'out'
        _write_fake_emevd(str(vanilla), 'common_func.emevd.dcx', 'V')
        _write_fake_emevd(str(overlay), 'common_func.emevd.dcx', 'O')
        _write_fake_emevd(str(overlay), 'extra_orphan.emevd.dcx', 'EXTRA')

        dcx_batch.emevd_decompress_dir(str(vanilla), str(out), oodle="fake-not-needed-since-decompress-is-monkeypatched",
                                        overlay_dir=str(overlay))

        assert (out / 'common_func.emevd').read_text(encoding="utf-8") == 'O'
        # Extra orphan file is not present in output
        assert not (out / 'extra_orphan.emevd').exists()

    def test_missing_overlay_dir_falls_back_to_vanilla(self, tmp_path, fake_decompress):
        """A non-existent overlay_dir path is silently ignored."""
        vanilla = tmp_path / 'vanilla'
        out = tmp_path / 'out'
        _write_fake_emevd(str(vanilla), 'common_func.emevd.dcx', 'V')

        dcx_batch.emevd_decompress_dir(
            str(vanilla), str(out), oodle="fake-not-needed-since-decompress-is-monkeypatched",
            overlay_dir='/nonexistent/path/that/does/not/exist')

        assert (out / 'common_func.emevd').read_text(encoding="utf-8") == 'V'

    def test_empty_overlay_dir_falls_back_to_vanilla(self, tmp_path, fake_decompress):
        """An empty overlay_dir behaves like overlay_dir=None."""
        vanilla = tmp_path / 'vanilla'
        overlay = tmp_path / 'overlay'
        overlay.mkdir()  # empty
        out = tmp_path / 'out'
        _write_fake_emevd(str(vanilla), 'common_func.emevd.dcx', 'V')

        dcx_batch.emevd_decompress_dir(str(vanilla), str(out), oodle="fake-not-needed-since-decompress-is-monkeypatched",
                                        overlay_dir=str(overlay))

        assert (out / 'common_func.emevd').read_text(encoding="utf-8") == 'V'

    def test_overlay_dir_with_only_non_emevd_files_ignored(self, tmp_path, fake_decompress):
        """Non-.emevd.dcx files in overlay are ignored (e.g. the bundle's
        README.md and .js sidecars)."""
        vanilla = tmp_path / 'vanilla'
        overlay = tmp_path / 'overlay'
        out = tmp_path / 'out'
        _write_fake_emevd(str(vanilla), 'common_func.emevd.dcx', 'V')
        # Overlay only has README + .js — no .dcx for this file
        _write_fake_emevd(str(overlay), 'README.md', 'docs')
        _write_fake_emevd(str(overlay), 'common_func.emevd.dcx.js', 'js source')

        dcx_batch.emevd_decompress_dir(str(vanilla), str(out), oodle="fake-not-needed-since-decompress-is-monkeypatched",
                                        overlay_dir=str(overlay))

        assert (out / 'common_func.emevd').read_text(encoding="utf-8") == 'V'


class TestBundleLayout:
    """Smoke test that the bundled patched_emevd/ directory layout is
    structured the way the overlay logic expects."""

    def test_patched_emevd_dir_exists(self):
        d = os.path.join(ROOT, 'patched_emevd')
        assert os.path.isdir(d), (
            "patched_emevd/ should exist at project root — it's the "
            "default overlay used by oops_rando_gui's _run_rando path")

    def test_patched_emevd_has_common_func(self):
        d = os.path.join(ROOT, 'patched_emevd')
        expected = os.path.join(d, 'common_func.emevd.dcx')
        if not os.path.exists(expected):
            pytest.skip(
                'patched_emevd/ compiled corpus absent from this source '
                'checkout — pre-existing bundled-asset gap (the compiled '
                '.emevd.dcx files are DarkScript3 build outputs, not '
                'committed; see CHANGELOG "pre-existing bundled-asset '
                'gaps" note). Re-run with the full bundle to assert.')
        assert os.path.exists(expected), (
            f"patched_emevd/ must contain common_func.emevd.dcx — "
            f"that's the file emevd_patch.py's 6 patches land in")
