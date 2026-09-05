"""
test_copy_log_button.py — tests for the Tier 3 UX #12 Copy/Clear log
buttons in the Output frame.

Two layers:
  1. Pure-function tests for _build_log_export_header — the static
     method that constructs the environment-info preamble prefixed to
     every copied log.
  2. Source-inspection tests locking in: the buttons exist, are wired
     to the right methods, the methods exist, and the clipboard call
     uses tk's clipboard primitives.
"""
import os
import re
import textwrap
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH, encoding="utf-8") as f:
        return f.read()


def _extract_method_body(src, name):
    """Pull a method body (def {name}) out of the source as text.
    Returns just the body lines, stripped of method indentation."""
    needle = f'def {name}('
    start = src.find(needle)
    assert start != -1, f'method {name!r} not found'
    # End of method: next sibling `    def ` at same indent
    end = src.find('\n    def ', start + 1)
    if end == -1:
        end = len(src)
    return src[start:end]


@pytest.fixture(scope='module')
def build_log_export_header(gui_source):
    """Extract and compile _build_log_export_header into a namespace
    so we can call it as a pure function (no Tk required)."""
    body = _extract_method_body(gui_source, '_build_log_export_header')
    # Strip method indentation (4 spaces) and the @staticmethod decorator
    body = textwrap.dedent(body)
    # The first line is the decorator if present (we extract from def, so no)
    import sys
    ns = {'sys': sys}
    exec(body, ns)
    return ns['_build_log_export_header']


# ---------------------------------------------------------------------
# Pure function: _build_log_export_header
# ---------------------------------------------------------------------

class TestBuildLogExportHeader:
    def test_returns_string(self, build_log_export_header):
        result = build_log_export_header()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_branding(self, build_log_export_header):
        """The header should announce what tool the log came from —
        otherwise the recipient has to guess context from the lines."""
        result = build_log_export_header()
        assert 'Nightreign' in result or '4laric' in result

    def test_includes_engine_fingerprint(self, build_log_export_header):
        result = build_log_export_header(engine_fingerprint='v0.26.0')
        assert 'v0.26.0' in result

    def test_engine_unknown_when_not_passed(self, build_log_export_header):
        """Defensive: callers may not be able to load oops_v3 (rare but
        possible if the rando is half-installed). The header must still
        be generable — show '(unknown)' rather than crash."""
        result = build_log_export_header()
        assert '(unknown)' in result or 'unknown' in result.lower()

    def test_includes_python_version(self, build_log_export_header):
        result = build_log_export_header()
        assert 'Python' in result
        # Should contain a version number — at minimum two digits + dot
        assert re.search(r'\d+\.\d+', result)

    def test_includes_platform(self, build_log_export_header):
        result = build_log_export_header()
        assert 'Platform' in result
        # OS name — Linux/Darwin/Windows
        assert any(p in result for p in ('Linux', 'Darwin', 'Windows'))

    def test_includes_all_four_path_keys(self, build_log_export_header):
        """All four configured root paths must appear in the header
        even if blank, so the recipient sees the full configuration
        state at a glance."""
        result = build_log_export_header()
        for key in ('game_install', 'er_install', 'me3_package',
                    'me3_launcher'):
            assert key in result, f'Path key {key!r} missing from header'

    def test_paths_dict_values_shown(self, build_log_export_header):
        paths = {
            'game_install': '/a/b/c',
            'er_install':   '/d/e/f',
            'me3_package':  '/g/h/i',
            'me3_launcher': '/j/k/me3.exe',
        }
        result = build_log_export_header(paths=paths)
        for val in paths.values():
            assert val in result

    def test_missing_paths_shown_as_not_set(self, build_log_export_header):
        """Blank/missing path values must read as '(not set)' rather
        than appearing as empty strings, which look like rendering bugs."""
        result = build_log_export_header(paths={})
        # Every path key should be paired with '(not set)' since none provided
        assert result.count('(not set)') == 4

    def test_none_paths_handled(self, build_log_export_header):
        """Defensive: paths=None must not raise."""
        result = build_log_export_header(paths=None)
        assert 'not set' in result.lower()

    def test_includes_timestamp(self, build_log_export_header):
        """Timestamp is useful for support — the recipient knows
        when the run happened relative to recent issues."""
        result = build_log_export_header()
        assert 'Timestamp' in result
        # ISO date format: YYYY-MM-DD
        assert re.search(r'\d{4}-\d{2}-\d{2}', result)

    def test_ends_with_separator(self, build_log_export_header):
        """A visual separator between the header and the log itself
        makes pasted reports much more readable."""
        result = build_log_export_header()
        # Last non-empty line should be a separator (===, ---, or similar)
        non_empty = [l for l in result.splitlines() if l.strip()]
        assert any(c * 10 in non_empty[-1] for c in ('=', '-', '_')), (
            'Header should end with a clear separator line so the '
            'pasted log content is visually distinct.')


# ---------------------------------------------------------------------
# Source-inspection structural locks
# ---------------------------------------------------------------------

class TestCopyLogButtonWiring:
    """The Copy log + Clear buttons must exist in the Output frame
    header row, wired to the right methods."""

    def test_copy_log_method_exists(self, gui_source):
        assert 'def _copy_log_to_clipboard(self):' in gui_source

    def test_clear_log_method_exists(self, gui_source):
        assert 'def _clear_log(self):' in gui_source

    def test_copy_button_packed_in_output_frame(self, gui_source):
        """The Copy log button construction must reference the right
        command and live in the Output LabelFrame's header row."""
        # Locate Output LabelFrame
        idx = gui_source.find("ttk.LabelFrame(parent, text=\"Output\"")
        assert idx != -1, '"Output" LabelFrame not found'
        # Within ~2000 chars of the LabelFrame construction, the Copy
        # log button + command wiring should appear
        snippet = gui_source[idx:idx + 2000]
        assert 'Copy log' in snippet, (
            'Copy log button text not found near Output frame — the '
            'button needs to be packed inside (or adjacent to) the '
            'log widget for discoverability.')
        assert '_copy_log_to_clipboard' in snippet, (
            'Copy log button must wire its command to '
            '_copy_log_to_clipboard.')

    def test_clear_button_packed_in_output_frame(self, gui_source):
        idx = gui_source.find("ttk.LabelFrame(parent, text=\"Output\"")
        snippet = gui_source[idx:idx + 2000]
        assert ('Clear' in snippet and '_clear_log' in snippet), (
            'Clear log button must exist in the Output frame header '
            'row, wired to _clear_log.')


class TestCopyLogImplementation:
    """The copy method must use Tk's clipboard primitives and include
    the environment-info header."""

    def test_uses_clipboard_clear_and_append(self, gui_source):
        body = _extract_method_body(gui_source, '_copy_log_to_clipboard')
        assert 'clipboard_clear()' in body, (
            'Must call clipboard_clear() before clipboard_append() to '
            'avoid concatenating the new content onto whatever was '
            'previously copied.')
        assert 'clipboard_append(' in body

    def test_prepends_header(self, gui_source):
        body = _extract_method_body(gui_source, '_copy_log_to_clipboard')
        assert '_build_log_export_header(' in body, (
            'The copy method must prepend the environment-info header '
            'built by _build_log_export_header.')

    def test_reads_full_log(self, gui_source):
        """The log widget content must be read in full ('1.0' to end),
        not just visible lines."""
        body = _extract_method_body(gui_source, '_copy_log_to_clipboard')
        # tk Text.get('1.0', 'end-1c') is the canonical full-read
        assert "'1.0'" in body and 'end' in body, (
            'Must read the full log via Text.get("1.0", "end-1c"), '
            'not just the visible portion.')

    def test_force_clipboard_update(self, gui_source):
        """Tk's clipboard goes away when the app exits unless we call
        update() to push the data into the system clipboard. Without
        this, the user copies the log and then immediately closes the
        rando, only to find the clipboard empty."""
        body = _extract_method_body(gui_source, '_copy_log_to_clipboard')
        assert 'update()' in body, (
            'Must call root.update() after clipboard_append() so the '
            'clipboard data persists past app close.')

    def test_handles_clipboard_error(self, gui_source):
        """Clipboard access can fail in headless environments / on
        locked-down machines. Surface a useful error, don't crash."""
        body = _extract_method_body(gui_source, '_copy_log_to_clipboard')
        assert 'except' in body
        assert 'TclError' in body, (
            'Must catch tk.TclError specifically — clipboard ops raise '
            'that in headless / permission-denied scenarios.')


class TestClearLogImplementation:
    def test_temporarily_enables_widget(self, gui_source):
        """The log widget is state='disabled' for read-only display.
        Clearing requires temporarily flipping to 'normal' so the
        delete() call doesn't silently no-op."""
        body = _extract_method_body(gui_source, '_clear_log')
        assert "state='normal'" in body or 'state="normal"' in body, (
            'Must temporarily set state=normal to allow delete() to '
            'actually clear the widget.')
        assert "state='disabled'" in body or 'state="disabled"' in body, (
            'Must restore state=disabled after clearing so the user '
            "can't type into the log.")

    def test_deletes_all_content(self, gui_source):
        body = _extract_method_body(gui_source, '_clear_log')
        assert "delete('1.0', 'end')" in body or 'delete("1.0", "end")' in body
