"""
test_post_run_summary.py — tests for the Tier 3 UX #10 post-run summary
panel.

Two layers:
  1. Pure-function tests for the helpers (_count_msb_dcx_in_dir,
     _find_spoiler_for_run, _build_run_summary's shape) — extracted
     from the GUI source and exercised with real tmp_path filesystems.
  2. Source-inspection tests locking the structural contract: worker
     pushes ('__SUMMARY__', dict) before __DONE__, drain handler
     dispatches the tuple, render method materializes the panel,
     host frame is constructed above the log.
"""
import os
import textwrap
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


def _extract_method_body(src, name):
    needle = f'def {name}('
    start = src.find(needle)
    assert start != -1, f'method {name!r} not found'
    # Stop at the next sibling: either `    def ` or `    @` (decorator).
    # Without the @-check we'd grab the next method's decorator line into
    # this method's body and exec() would choke on indented @staticmethod.
    candidates = []
    for marker in ('\n    def ', '\n    @'):
        idx = src.find(marker, start + 1)
        if idx != -1:
            candidates.append(idx)
    end = min(candidates) if candidates else len(src)
    return src[start:end]


@pytest.fixture(scope='module')
def count_msb_dcx_in_dir(gui_source):
    """Extract the static helper for use in tests."""
    body = _extract_method_body(gui_source, '_count_msb_dcx_in_dir')
    body = textwrap.dedent(body)
    ns = {'os': os}
    exec(body, ns)
    return ns['_count_msb_dcx_in_dir']


@pytest.fixture(scope='module')
def find_spoiler_for_run(gui_source):
    body = _extract_method_body(gui_source, '_find_spoiler_for_run')
    body = textwrap.dedent(body)
    ns = {'os': os}
    exec(body, ns)
    return ns['_find_spoiler_for_run']


# ---------------------------------------------------------------------
# Pure: _count_msb_dcx_in_dir
# ---------------------------------------------------------------------

class TestCountMsbDcx:
    def test_counts_msb_dcx_files(self, count_msb_dcx_in_dir, tmp_path):
        for name in ('m10_00_00_00.msb.dcx',
                     'm60_42_36_00.msb.dcx',
                     'common.emevd.dcx'):  # not counted — wrong extension
            (tmp_path / name).write_text('(stub)')
        assert count_msb_dcx_in_dir(str(tmp_path)) == 2

    def test_empty_dir(self, count_msb_dcx_in_dir, tmp_path):
        assert count_msb_dcx_in_dir(str(tmp_path)) == 0

    def test_missing_dir_returns_zero(self, count_msb_dcx_in_dir, tmp_path):
        """Defensive: a directory that doesn't exist returns 0, not an
        error. The summary panel must be renderable even if the output
        dir went away after the run."""
        ghost = tmp_path / 'no_such_dir'
        assert count_msb_dcx_in_dir(str(ghost)) == 0

    def test_none_or_empty_path(self, count_msb_dcx_in_dir):
        assert count_msb_dcx_in_dir(None) == 0
        assert count_msb_dcx_in_dir('') == 0

    def test_case_insensitive_extension(self, count_msb_dcx_in_dir, tmp_path):
        """Filenames on Windows/macOS may have inconsistent case.
        Match should be case-insensitive."""
        (tmp_path / 'm10.MSB.DCX').write_text('(stub)')
        (tmp_path / 'm20.Msb.Dcx').write_text('(stub)')
        assert count_msb_dcx_in_dir(str(tmp_path)) == 2

    def test_ignores_other_extensions(self, count_msb_dcx_in_dir, tmp_path):
        """Spoilers, sidecar XMLs, intermediate .msb files (no .dcx)
        shouldn't inflate the count."""
        (tmp_path / 'm10.msb').write_text('(stub)')         # decompressed
        (tmp_path / 'spoiler.json').write_text('{}')        # spoiler
        (tmp_path / 'm10.msb.xml').write_text('<xml/>')     # Yabber sidecar
        (tmp_path / 'real.msb.dcx').write_text('(stub)')    # only this counts
        assert count_msb_dcx_in_dir(str(tmp_path)) == 1


# ---------------------------------------------------------------------
# Pure: _find_spoiler_for_run
# ---------------------------------------------------------------------

class TestFindSpoiler:
    def test_finds_seeded_spoiler(self, find_spoiler_for_run, tmp_path):
        """Canonical: <out_dir>/spoiler_<seed>.json"""
        (tmp_path / 'spoiler_12345.json').write_text('{}')
        result = find_spoiler_for_run(str(tmp_path), 12345)
        assert result == str(tmp_path / 'spoiler_12345.json')

    def test_finds_unseeded_spoiler(self, find_spoiler_for_run, tmp_path):
        """Older engines wrote spoiler.json without the seed in the name."""
        (tmp_path / 'spoiler.json').write_text('{}')
        result = find_spoiler_for_run(str(tmp_path), 999)
        assert result == str(tmp_path / 'spoiler.json')

    def test_finds_sibling_spoilers_dir(self, find_spoiler_for_run, tmp_path):
        """Some configs write to <out_parent>/spoilers/<seed>.json."""
        out_dir = tmp_path / 'mod_output'
        out_dir.mkdir()
        spoilers = tmp_path / 'spoilers'
        spoilers.mkdir()
        (spoilers / '777.json').write_text('{}')
        result = find_spoiler_for_run(str(out_dir), 777)
        assert result == str(spoilers / '777.json')

    def test_glob_fallback(self, find_spoiler_for_run, tmp_path):
        """If the standard names don't match, glob for spoiler*.json."""
        (tmp_path / 'spoiler_custom_format.json').write_text('{}')
        result = find_spoiler_for_run(str(tmp_path), 42)
        assert result is not None
        assert 'spoiler' in os.path.basename(result).lower()

    def test_returns_none_when_no_spoiler(self, find_spoiler_for_run, tmp_path):
        assert find_spoiler_for_run(str(tmp_path), 42) is None

    def test_handles_missing_outdir(self, find_spoiler_for_run, tmp_path):
        """Defensive: out_dir might not exist (race after worker
        cleanup, etc.). Don't crash — return None."""
        ghost = tmp_path / 'no_such_dir'
        assert find_spoiler_for_run(str(ghost), 42) is None

    def test_handles_empty_outdir_arg(self, find_spoiler_for_run):
        assert find_spoiler_for_run('', 42) is None
        assert find_spoiler_for_run(None, 42) is None


# ---------------------------------------------------------------------
# Source-inspection: structural contract
# ---------------------------------------------------------------------

class TestSummaryPanelStructure:
    """The summary panel needs: a host frame, a render method, and
    a build method. Drain handler must dispatch __SUMMARY__ tuples."""

    def test_host_frame_constructed(self, gui_source):
        """The host frame must be packed in _build_main_tab so the
        render method has somewhere to draw."""
        assert '_summary_frame_host' in gui_source, (
            '_summary_frame_host attribute missing — summary panel '
            'has no home in the UI.')
        # Construction line should set up the host as a ttk.Frame
        ctor_idx = gui_source.find('self._summary_frame_host = ttk.Frame(')
        assert ctor_idx != -1, (
            'Host frame must be constructed in _build_main_tab.')

    def test_host_frame_above_output_log(self, gui_source):
        """Visual order: summary above log so the user's eyes land
        on it after the worker finishes."""
        host_idx = gui_source.find('self._summary_frame_host = ttk.Frame(')
        output_idx = gui_source.find(
            "ttk.LabelFrame(parent, text=\"Output\"")
        assert host_idx != -1 and output_idx != -1
        assert host_idx < output_idx, (
            "Summary host frame must be constructed BEFORE the Output "
            "log frame so it packs above it visually.")

    def test_build_summary_method_exists(self, gui_source):
        assert 'def _build_run_summary(self, config):' in gui_source

    def test_render_summary_method_exists(self, gui_source):
        assert 'def _render_run_summary(self, summary):' in gui_source

    def test_open_in_file_manager_method_exists(self, gui_source):
        """The Open buttons in the summary panel need this method
        to actually do anything."""
        assert 'def _open_in_file_manager(self, path):' in gui_source

    def test_worker_pushes_summary_before_done(self, gui_source):
        """The worker must push ('__SUMMARY__', summary) to the queue
        BEFORE __DONE__ — otherwise the panel never gets the data."""
        summary_push = gui_source.find("('__SUMMARY__', summary)")
        done_push = gui_source.find("self.log_queue.put('__DONE__')")
        assert summary_push != -1, (
            "Worker must push ('__SUMMARY__', summary) tuple before "
            "__DONE__ so the render method gets called.")
        assert done_push != -1
        assert summary_push < done_push, (
            "Summary push must come before __DONE__ push in the worker. "
            "Otherwise the GUI restores the Run button before the "
            "summary panel renders, creating a visual gap.")

    def test_drain_handler_dispatches_tuples(self, gui_source):
        """The drain handler must check for tuple items and route
        them based on the tag. Without this, the worker's structured
        payload reaches the drain as a string and gets logged as
        gibberish."""
        drain_body = _extract_method_body(gui_source, '_drain_log_queue')
        assert 'isinstance(item, tuple)' in drain_body, (
            'Drain handler must recognise tuple-form queue items. '
            'Otherwise structured payloads get stringified into the log.')
        assert "'__SUMMARY__'" in drain_body, (
            'Drain handler must handle the __SUMMARY__ tag specifically.')

    def test_drain_handler_calls_render(self, gui_source):
        drain_body = _extract_method_body(gui_source, '_drain_log_queue')
        assert '_render_run_summary(' in drain_body, (
            'Drain handler must call _render_run_summary on a '
            '__SUMMARY__ payload to actually paint the panel.')


class TestSummaryDictShape:
    """The summary dict's shape is a contract between worker and
    renderer. If they disagree the renderer KeyErrors on each missing
    key."""

    def test_build_includes_all_required_keys(self, gui_source):
        body = _extract_method_body(gui_source, '_build_run_summary')
        for key in ("'seed'", "'mode_label'", "'out_dir'", "'mod_map_dir'",
                    "'msb_count'", "'spoiler_path'",
                    "'multiplayer_safe'", "'heritage_enabled'"):
            assert key in body, (
                f'_build_run_summary missing key {key} — renderer '
                f'will KeyError when it reaches that field.')

    def test_render_reads_expected_keys(self, gui_source):
        """The renderer must read every key the builder writes (loose
        check: each documented key should appear in the render body
        somewhere)."""
        body = _extract_method_body(gui_source, '_render_run_summary')
        # Required keys to actually display
        for key in ("'seed'", "'msb_count'", "'mode_label'", "'out_dir'",
                    "'spoiler_path'"):
            assert key in body, (
                f"_render_run_summary doesn't read {key} — that data "
                f"would be silently dropped.")


class TestRenderSafety:
    """The render method runs on the GUI thread but the worker thread
    might be in a weird state when it fires. Defensive checks:"""

    def test_render_handles_missing_host(self, gui_source):
        """If _summary_frame_host wasn't constructed (degraded build
        path), render must bail silently — not crash the drain loop."""
        body = _extract_method_body(gui_source, '_render_run_summary')
        assert '_summary_frame_host' in body
        assert ('hasattr' in body or 'is None' in body), (
            'Renderer must check that _summary_frame_host exists '
            'before drawing into it.')

    def test_render_clears_previous_panel(self, gui_source):
        """Re-runs should REPLACE the previous summary, not stack a
        new one beneath it."""
        body = _extract_method_body(gui_source, '_render_run_summary')
        assert ('destroy()' in body or 'winfo_children' in body), (
            'Renderer must clear previous summary widgets before '
            'building the new one — otherwise re-runs accumulate.')

    def test_render_includes_launch_button(self, gui_source):
        """The summary panel's job is partly to provide a natural
        next-action affordance. Launch button must be there."""
        body = _extract_method_body(gui_source, '_render_run_summary')
        assert '_launch_via_me3' in body, (
            'Summary panel must include a Launch button — the "what '
            'do I do next?" affordance is the panel\'s whole point.')

    def test_drain_catches_render_errors(self, gui_source):
        """A render failure must NOT prevent __DONE__ from being
        processed — otherwise the Run button stays stuck on Cancel."""
        drain_body = _extract_method_body(gui_source, '_drain_log_queue')
        # The render call should be inside try/except so failures don't
        # break the rest of drain processing
        # Find the section that handles __SUMMARY__
        summary_section_start = drain_body.find("'__SUMMARY__'")
        # Look for try/except in the next ~500 chars
        summary_section = drain_body[summary_section_start:summary_section_start + 800]
        assert 'try:' in summary_section, (
            'Render call must be inside try/except so a render failure '
            "doesn't poison the drain loop.")
        assert 'except' in summary_section


class TestOpenInFileManager:
    """The Open buttons next to file paths invoke this. Must be
    cross-platform and not crash on missing paths."""

    def test_handles_missing_path(self, gui_source):
        body = _extract_method_body(gui_source, '_open_in_file_manager')
        # Must check existence + show a helpful message, not raise
        assert 'os.path.exists' in body or 'isfile' in body or 'isdir' in body, (
            'Open helper must check path exists before launching the '
            'file manager — otherwise OSError on missing path.')

    def test_handles_all_three_platforms(self, gui_source):
        """Windows / macOS / Linux all have different file-manager
        invocations. All three must be covered."""
        body = _extract_method_body(gui_source, '_open_in_file_manager')
        assert 'win32' in body, 'Windows platform branch missing'
        assert 'darwin' in body, 'macOS platform branch missing'
        # Linux is the implicit fallback — should call xdg-open
        assert 'xdg-open' in body, (
            'Linux branch should use xdg-open for cross-DE compatibility.')
