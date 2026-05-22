"""
test_splash_screen.py — tests for the v0.26.x startup splash window.

The splash addresses a real UX problem: cold-cache startup takes
~0.5–2 seconds during which the user sees a blank/grey window (or
on Windows, "Not Responding"). The splash gives immediate visual
acknowledgment + status updates at each major milestone.

Three layers:
  1. Source-inspection on the SplashWindow class (structure, key
     methods, attribute names — these matter because main() and
     RandoGUI both reach into them).
  2. RandoGUI.__init__ progress_callback parameter — must be
     optional (backward compat with tests) AND must be called at
     the expected milestones.
  3. main() wires the splash into the actual init flow.
"""
import os
import re
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


def _extract_class_body(src, name):
    needle = f'class {name}'
    start = src.find(needle)
    assert start != -1, f'class {name!r} not found'
    # Next class at module level OR next module-level def
    candidates = []
    for marker in ('\nclass ', '\ndef '):
        idx = src.find(marker, start + 1)
        if idx != -1:
            candidates.append(idx)
    end = min(candidates) if candidates else len(src)
    return src[start:end]


def _extract_method_body(src, name):
    needle = f'def {name}('
    start = src.find(needle)
    assert start != -1, f'method {name!r} not found'
    candidates = []
    for marker in ('\n    def ', '\n    @', '\nclass ', '\ndef '):
        idx = src.find(marker, start + 1)
        if idx != -1:
            candidates.append(idx)
    end = min(candidates) if candidates else len(src)
    return src[start:end]


# ---------------------------------------------------------------------
# SplashWindow class structure
# ---------------------------------------------------------------------

class TestSplashWindowClass:
    def test_class_defined(self, gui_source):
        assert 'class SplashWindow' in gui_source, (
            'SplashWindow class missing — startup will have no '
            'splash and the blank-window UX problem returns.')

    def test_has_update_status_method(self, gui_source):
        """RandoGUI.__init__ calls progress_callback which routes to
        splash.update_status. If the method name changes without
        updating main(), the integration breaks silently."""
        body = _extract_class_body(gui_source, 'SplashWindow')
        assert 'def update_status(self, msg)' in body, (
            'SplashWindow.update_status(msg) is the API main() and '
            'RandoGUI rely on — missing.')

    def test_has_close_method(self, gui_source):
        body = _extract_class_body(gui_source, 'SplashWindow')
        assert 'def close(self)' in body, (
            'SplashWindow.close() must exist — main() calls it in '
            'a finally: block to ensure cleanup.')

    def test_update_status_forces_repaint(self, gui_source):
        """The status updates only become visible if update_idletasks
        is called. Without it, all the messages would be set but
        none would paint until init finishes — defeating the splash."""
        body = _extract_method_body(gui_source, 'update_status')
        assert 'update_idletasks' in body or '_paint(' in body, (
            'update_status must force a repaint (via update_idletasks '
            'or a helper) — without it, status changes won\'t show '
            'during a busy init.')

    def test_uses_toplevel(self, gui_source):
        """The splash is a separate window, not drawn into root."""
        body = _extract_class_body(gui_source, 'SplashWindow')
        assert 'Toplevel(' in body, (
            'Splash should be a Toplevel — drawing into root would '
            'flash the main UI before it\'s ready.')

    def test_undecorated(self, gui_source):
        """overrideredirect(True) strips the OS chrome for a clean
        splash look (no minimize/close buttons that the user might
        click during init)."""
        body = _extract_class_body(gui_source, 'SplashWindow')
        assert 'overrideredirect' in body, (
            'Splash should use overrideredirect for a borderless '
            'splash-screen look. The user shouldn\'t be tempted to '
            'close it mid-init.')

    def test_always_on_top(self, gui_source):
        """A slow init might be interrupted by the user clicking
        another window. Without topmost, the splash hides behind
        the click target and the user thinks the app froze."""
        body = _extract_class_body(gui_source, 'SplashWindow')
        assert "'-topmost'" in body or '-topmost' in body, (
            'Splash should set -topmost so it stays visible if the '
            'user clicks another window during init.')

    def test_centered_on_screen(self, gui_source):
        """Center on screen, NOT on root — root may not be sized/
        positioned yet on first launch."""
        body = _extract_class_body(gui_source, 'SplashWindow')
        # winfo_screenwidth / screenheight indicates screen-relative
        # positioning rather than root-relative
        assert 'winfo_screenwidth' in body, (
            'Splash should center using winfo_screenwidth — '
            'centering on root would mis-position before root is '
            'sized.')

    def test_close_handles_already_closed(self, gui_source):
        """close() may be called from a finally: block after the
        splash was already destroyed (e.g. by user action somehow,
        or by an inner exception). Should not raise."""
        body = _extract_method_body(gui_source, 'close')
        # Either try/except TclError or some guard
        assert 'TclError' in body or 'try:' in body, (
            'close() should tolerate a double-close — wrap destroy() '
            'in try/except TclError.')

    def test_update_status_handles_closed_splash(self, gui_source):
        """A progress_callback call may arrive after the splash was
        closed (init takes longer than expected, splash got destroyed
        early). Must not raise — the callback is a fire-and-forget."""
        body = _extract_method_body(gui_source, 'update_status')
        assert 'TclError' in body, (
            'update_status should tolerate post-close calls — wrap '
            'in try/except TclError so a late progress_callback '
            'doesn\'t crash the init.')


# ---------------------------------------------------------------------
# RandoGUI integration
# ---------------------------------------------------------------------

class TestProgressCallbackParameter:
    def test_init_accepts_progress_callback(self, gui_source):
        """RandoGUI.__init__ must accept progress_callback. Without
        the parameter, main() can't pass the splash callable in."""
        # Find class RandoGUI's __init__
        cls_idx = gui_source.find('class RandoGUI')
        init_idx = gui_source.find('def __init__(', cls_idx)
        sig_end = gui_source.find(')', init_idx)
        signature = gui_source[init_idx:sig_end + 1]
        assert 'progress_callback' in signature, (
            f'RandoGUI.__init__ signature missing progress_callback: '
            f'{signature}')

    def test_progress_callback_is_optional(self, gui_source):
        """Backward compatibility: progress_callback must default to
        None (or a no-op) so existing test code doing RandoGUI(root)
        without a callback still works."""
        cls_idx = gui_source.find('class RandoGUI')
        init_idx = gui_source.find('def __init__(', cls_idx)
        sig_end = gui_source.find(')', init_idx)
        signature = gui_source[init_idx:sig_end + 1]
        # Should be `progress_callback=None` or `progress_callback=...`
        assert re.search(r'progress_callback\s*=\s*\w+', signature), (
            f'progress_callback should have a default value: '
            f'{signature}')

    def test_init_stores_callback(self, gui_source):
        """The init must stash the callback on self so other methods
        (or in-init calls) can use it."""
        cls_idx = gui_source.find('class RandoGUI')
        init_idx = gui_source.find('def __init__(', cls_idx)
        # Look in the first 2000 chars of init body for the assignment
        body = gui_source[init_idx:init_idx + 2000]
        assert '_progress_callback' in body, (
            'Init should store the callback as self._progress_callback '
            '(or similar) so it can be invoked from other methods.')

    def test_callback_invoked_around_load_data(self, gui_source):
        """Progress should be reported BEFORE _load_data starts —
        otherwise the splash sits on "Starting up…" through the
        whole data-loading phase, which is one of the slower parts."""
        cls_idx = gui_source.find('class RandoGUI')
        init_idx = gui_source.find('def __init__(', cls_idx)
        # Find the load_data call and look at the chars right before
        load_data_idx = gui_source.find('self._load_data()', init_idx)
        assert load_data_idx != -1
        # Look back ~200 chars for a progress call
        window = gui_source[max(load_data_idx - 200, init_idx):load_data_idx]
        assert '_progress_callback(' in window, (
            'Progress should be reported before _load_data() — '
            'otherwise the splash text doesn\'t update during the '
            'JSON parsing phase.')

    def test_callback_invoked_around_build_ui(self, gui_source):
        """Same for _build_ui — the slowest init phase (widget
        construction across 6 tabs)."""
        cls_idx = gui_source.find('class RandoGUI')
        init_idx = gui_source.find('def __init__(', cls_idx)
        build_idx = gui_source.find('self._build_ui()', init_idx)
        assert build_idx != -1
        window = gui_source[max(build_idx - 200, init_idx):build_idx]
        assert '_progress_callback(' in window, (
            'Progress should be reported before _build_ui() — this '
            'is the longest init phase.')


class TestProgressCallbackMessages:
    """Verify that the progress messages cover the major phases —
    a single "Loading…" message for 2 seconds is barely better than
    no splash; updated messages prove the app is alive."""

    def test_message_count(self, gui_source):
        """At least 4 distinct progress milestones — coarse enough
        to not be noisy, fine enough to show real progress."""
        cls_idx = gui_source.find('class RandoGUI')
        # Look at first 3000 chars of init body for callback calls
        init_idx = gui_source.find('def __init__(', cls_idx)
        # Capture init body up to next def at class level
        end = gui_source.find('\n    def ', init_idx + 1)
        init_body = gui_source[init_idx:end if end != -1 else init_idx + 5000]
        # Plus the _build_ui body (some progress calls live there too)
        build_ui_body = _extract_method_body(gui_source, '_build_ui')
        combined = init_body + build_ui_body
        call_count = combined.count('_progress_callback(')
        # Account for the assignment line too which shows up as
        # "_progress_callback = ..." — filter to actual call sites
        call_count = len(re.findall(
            r'\._progress_callback\([\'"]', combined))
        assert call_count >= 4, (
            f'Only {call_count} progress callback calls found across '
            f'init + _build_ui. Expected at least 4 distinct '
            f'milestones (e.g. Loading data, Building interface, '
            f'Building Heritage tab, Wiring shortcuts).')


# ---------------------------------------------------------------------
# main() wires the splash in
# ---------------------------------------------------------------------

class TestMainWiring:
    def test_main_creates_splash(self, gui_source):
        body = _extract_method_body(gui_source, 'main')
        assert 'SplashWindow(' in body, (
            'main() must instantiate SplashWindow — otherwise the '
            'splash class is dead code.')

    def test_main_passes_callback(self, gui_source):
        """main() should hand splash.update_status to RandoGUI as
        the progress_callback."""
        body = _extract_method_body(gui_source, 'main')
        # Either splash.update_status or progress_callback=splash...
        assert 'splash.update_status' in body, (
            'main() should pass splash.update_status as the '
            'progress_callback to RandoGUI.')
        assert 'progress_callback=' in body, (
            'main() should explicitly name the progress_callback '
            'kwarg so the contract is clear.')

    def test_main_closes_splash(self, gui_source):
        """The splash MUST be closed after init — leaving it up
        would block the main UI behind a frozen splash."""
        body = _extract_method_body(gui_source, 'main')
        assert 'splash.close()' in body, (
            'main() must call splash.close() after RandoGUI init — '
            'otherwise the splash stays up indefinitely.')

    def test_close_in_finally(self, gui_source):
        """close() must happen even if RandoGUI init raises — otherwise
        an init crash leaves an orphaned splash window. Wrap in
        try/finally."""
        body = _extract_method_body(gui_source, 'main')
        # Find the splash creation and close lines
        splash_idx = body.find('splash = SplashWindow(')
        close_idx = body.find('splash.close()')
        finally_idx = body.find('finally:', splash_idx, close_idx)
        assert finally_idx != -1, (
            'splash.close() must be inside a finally: block so an '
            'init exception doesn\'t orphan the splash.')
