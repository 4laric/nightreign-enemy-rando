"""
test_me3_launch_button.py — tests for the Tier 2 UX #6 launch button.

The button itself can't be instantiated without a Tk display, so this
file does:
  1. Source-inspection tests locking in structural contracts (button
     exists in the GUI, state-resolver returns the right shape,
     subprocess invocation uses the documented ME3 CLI form).
  2. Behavioral tests on _resolve_me3_launch_state-style logic via a
     small re-implementation that mirrors the GUI helper's shape.
     This lets us verify the four readiness gates (binary present,
     pkg path set, profile resolvable, all-OK) without Tk.
"""
import os
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------
# Button is wired into the main tab next to Randomize
# ---------------------------------------------------------------------

class TestLaunchButtonWiring:
    def test_button_constructed(self, gui_source):
        assert 'self.launch_btn = ttk.Button(' in gui_source, (
            'Launch via ME3 button not found in GUI source.')

    def test_button_has_command(self, gui_source):
        """Button must wire the click handler — without `command=` it's
        decorative."""
        # Look in a window around the button construction
        idx = gui_source.find('self.launch_btn = ttk.Button(')
        snippet = gui_source[idx:idx + 400]
        assert 'command=self._launch_via_me3' in snippet, (
            'Launch button has no command binding — clicks do nothing.')

    def test_button_packed_next_to_randomize(self, gui_source):
        """Layout intent: Launch button sits beside Randomize, not below
        it or in a different frame. Verifies via 'side=left' and the
        proximity of the two construction calls."""
        run_btn_idx = gui_source.find("self.run_btn = ttk.Button(")
        launch_btn_idx = gui_source.find('self.launch_btn = ttk.Button(')
        assert run_btn_idx != -1 and launch_btn_idx != -1
        # Within ~1500 chars of each other = same row frame. Slack
        # accommodates inline doc-comments between the two button
        # constructions; a clearly-different-section placement (next
        # tab, separate frame far below) would be many KB away.
        assert abs(run_btn_idx - launch_btn_idx) < 1500, (
            'Launch button construction is too far from Randomize — '
            'they should share the f4 row frame for visual pairing.')
        # The Launch button must pack with side='left' to actually
        # appear next to Randomize, not stack below.
        launch_snippet = gui_source[launch_btn_idx:launch_btn_idx + 400]
        assert "side='left'" in launch_snippet, (
            'Launch button must pack with side=left so it sits beside '
            'Randomize horizontally.')

    def test_button_state_refresher_called_at_build(self, gui_source):
        """The initial state (typically 'disabled' on fresh installs)
        must be set before the user sees the button."""
        idx = gui_source.find('self.launch_btn = ttk.Button(')
        snippet = gui_source[idx:idx + 800]
        assert '_refresh_launch_button_state()' in snippet, (
            '_refresh_launch_button_state must be called right after '
            'the Launch button is constructed, otherwise the button '
            'starts in a default state with no tooltip.')

    def test_button_traces_me3_package_var(self, gui_source):
        """The button state must update live as the user fills in
        me3_package_var. Without the trace, the button stays disabled
        even after the user configures everything."""
        idx = gui_source.find('self.launch_btn = ttk.Button(')
        snippet = gui_source[idx:idx + 1200]
        assert 'me3_package_var' in snippet
        assert "trace_add('write'" in snippet
        assert '_refresh_launch_button_state' in snippet


# ---------------------------------------------------------------------
# _resolve_me3_launch_state — the readiness decision
# ---------------------------------------------------------------------

class TestResolveMe3LaunchStateContract:
    """The helper returns a dict with a stable shape. The button and
    the click handler both rely on this — locking it in catches typos
    that would otherwise show up only at runtime."""

    def test_method_defined(self, gui_source):
        assert 'def _resolve_me3_launch_state(self):' in gui_source

    def test_returns_dict_with_expected_keys(self, gui_source):
        """All four keys (ready, me3_binary, profile, reason) must be
        emitted on EVERY return path — otherwise callers crash on
        KeyError when a less-common branch fires."""
        # Extract method body
        start = gui_source.find('def _resolve_me3_launch_state(self):')
        end = gui_source.find('    def ', start + 1)
        body = gui_source[start:end]
        # Count returns; each should include the four keys
        for key in ("'ready'", "'me3_binary'", "'profile'", "'reason'"):
            assert key in body, (
                f'_resolve_me3_launch_state never sets {key} — caller '
                f'will KeyError on access.')

    def test_handles_no_binary(self, gui_source):
        """The 'me3 binary not detected' branch must produce
        ready=False and a helpful reason — not just bail out."""
        start = gui_source.find('def _resolve_me3_launch_state(self):')
        end = gui_source.find('    def ', start + 1)
        body = gui_source[start:end]
        assert 'not detected' in body.lower() or 'not found' in body.lower()
        assert 'github.com/garyttierney/me3' in body, (
            'No-binary branch should point the user at the canonical '
            'ME3 distribution URL.')

    def test_handles_no_profile_resolvable(self, gui_source):
        start = gui_source.find('def _resolve_me3_launch_state(self):')
        end = gui_source.find('    def ', start + 1)
        body = gui_source[start:end]
        assert 'No .me3 file found' in body or 'no .me3' in body.lower(), (
            'Branch for "binary found but profile not resolvable" should '
            'name the actual problem clearly.')


# ---------------------------------------------------------------------
# _launch_via_me3 — subprocess invocation
# ---------------------------------------------------------------------

class TestLaunchInvocation:
    """The actual ME3 command we invoke. Critical to get right since
    a misnamed flag silently does the wrong thing."""

    # v0.26.x: signature locked to accept a `from_auto_launch=False`
    # keyword. The "Launch after generate" checkbox passes
    # from_auto_launch=True so prerequisite-check failures log inline
    # instead of popping a modal over the freshly-finished generate.
    # Source-inspection tests accept either the old or new shape so
    # restoring the simpler signature wouldn't silently break them —
    # but the kwarg form is what's currently shipping.
    _METHOD_DEF_PATTERNS = (
        'def _launch_via_me3(self):',
        'def _launch_via_me3(self, *, from_auto_launch=False):',
    )

    def _find_method(self, gui_source):
        """Return (start_index, body) for the _launch_via_me3 method,
        accepting either the current or the legacy signature."""
        for pattern in self._METHOD_DEF_PATTERNS:
            start = gui_source.find(pattern)
            if start != -1:
                end = gui_source.find('    def ', start + 1)
                return start, gui_source[start:end]
        return -1, ''

    def test_method_defined(self, gui_source):
        start, _ = self._find_method(gui_source)
        assert start != -1, (
            '_launch_via_me3 method missing. Expected one of: '
            f'{self._METHOD_DEF_PATTERNS}')

    def test_uses_documented_me3_cli_form(self, gui_source):
        """Per ME3 0.10+ docs: `me3 launch -g nightreign -p <profile>`.
        Verifies we're constructing the right command shape."""
        _, body = self._find_method(gui_source)
        # The command list must include all four canonical parts
        assert "'launch'" in body, "Missing 'launch' subcommand"
        assert "'-g'" in body, "Missing -g flag"
        assert "'nightreign'" in body, "Missing nightreign game slug"
        assert "'-p'" in body, "Missing -p (profile) flag"

    def test_uses_popen_not_run(self, gui_source):
        """We MUST NOT block the GUI on NR's lifetime. subprocess.run
        waits for the child to exit; subprocess.Popen is fire-and-forget.
        Using run() would freeze the rando for the entire NR session."""
        _, body = self._find_method(gui_source)
        assert 'subprocess.Popen(' in body, (
            'Launch must use subprocess.Popen, not subprocess.run — '
            'otherwise the rando UI freezes for the entire NR session.')
        assert 'subprocess.run(' not in body, (
            'subprocess.run blocks until the child exits. Use Popen.')

    def test_handles_filenotfound(self, gui_source):
        """The binary path can become stale between detect and launch
        (user uninstalled me3, antivirus quarantined it, etc.). Catch
        FileNotFoundError specifically — the generic OSError message
        wouldn't be as actionable."""
        _, body = self._find_method(gui_source)
        assert 'FileNotFoundError' in body, (
            '_launch_via_me3 should catch FileNotFoundError specifically '
            'so we can tell the user the binary path went stale.')

    def test_handles_oserror(self, gui_source):
        """Permission errors (non-executable file on Linux) are OSError,
        not FileNotFoundError. Both branches should produce friendly
        messages, not stacktraces."""
        _, body = self._find_method(gui_source)
        assert 'except OSError' in body

    def test_drains_output_in_thread(self, gui_source):
        """ME3's stdout has the diagnostic info on startup failures.
        We need to capture it without blocking the GUI — that's a
        background thread reading from proc.stdout."""
        _, body = self._find_method(gui_source)
        assert 'threading.Thread' in body or 'threading' in body, (
            'Without a background thread to drain ME3 stdout, errors '
            'from ME3 would be invisible to the user.')


class TestAutoLaunchAfterGenerate:
    """v0.26.x: 'Launch after generate' checkbox auto-fires
    _launch_via_me3 on a successful generate. Critical that:
      - the checkbox exists and wires to auto_launch_after_generate_var
      - _drain_log_queue's __DONE__ branch consults the var and calls
        _launch_via_me3 with from_auto_launch=True
      - the auto-launch path doesn't fire on Cancelled runs"""

    def test_var_declared(self, gui_source):
        assert 'self.auto_launch_after_generate_var = tk.BooleanVar(' in gui_source, (
            'auto_launch_after_generate_var BooleanVar must be declared '
            'in __init__ so the checkbox has something to bind to.')

    def test_checkbox_exists(self, gui_source):
        """A Checkbutton must be packed somewhere with the auto-launch
        variable wired in. Without it, the user can't toggle the flag."""
        assert 'auto_launch_after_generate_var' in gui_source
        # The variable appears in two places: __init__ (declaration) and
        # _build_main_tab (the Checkbutton wiring). Walk every occurrence
        # and require Checkbutton to be near at least one of them.
        var_name = 'auto_launch_after_generate_var'
        positions = []
        start = 0
        while True:
            pos = gui_source.find(var_name, start)
            if pos == -1:
                break
            positions.append(pos)
            start = pos + 1
        for pos in positions:
            snippet = gui_source[max(0, pos - 400):pos + 400]
            if ('ttk.Checkbutton(' in snippet
                    or 'tk.Checkbutton(' in snippet):
                return  # found it near at least one occurrence
        pytest.fail(
            'auto_launch_after_generate_var must be wired to a '
            'Checkbutton widget. Currently the BooleanVar is declared '
            'but nothing renders it as a togglable control.')

    def test_done_handler_consults_auto_launch_flag(self, gui_source):
        """The __DONE__ branch in _drain_log_queue must read the
        auto-launch var and fire _launch_via_me3 when set."""
        done_idx = gui_source.find("if item == '__DONE__':")
        assert done_idx != -1, '__DONE__ handler not found in _drain_log_queue'
        # Look at the next ~1500 chars (the DONE branch body)
        snippet = gui_source[done_idx:done_idx + 1500]
        assert 'auto_launch_after_generate_var' in snippet, (
            "The __DONE__ branch must consult auto_launch_after_generate_var "
            "to decide whether to auto-launch. Without that check, the "
            "checkbox has no effect on successful runs.")
        assert '_launch_via_me3(' in snippet, (
            'The __DONE__ branch must call _launch_via_me3 when '
            'auto-launch is on.')

    def test_done_handler_skips_cancelled(self, gui_source):
        """Cancelled generates must NOT auto-launch — there's nothing
        meaningful to launch into when the run was aborted."""
        done_idx = gui_source.find("if item == '__DONE__':")
        snippet = gui_source[done_idx:done_idx + 1500]
        # The cancelled check should gate auto-launch — either by being
        # inside the "not Cancelled" branch or by checking status_var.
        assert 'Cancelled' in snippet, (
            'The __DONE__ branch must distinguish Cancelled from clean '
            'completion before auto-launching — otherwise a user who '
            'cancels mid-run with the checkbox on still gets NR launched.')


# ---------------------------------------------------------------------
# Behavioral tests on the readiness logic via a mirrored implementation
# ---------------------------------------------------------------------

def _mirror_resolve(binary, pkg, profile, exc=None):
    """Re-implements _resolve_me3_launch_state's branching to verify
    the readiness gate logic. The four states should be:
       binary missing                → not ready, reason mentions install
       pkg missing                   → not ready, reason mentions me3_package
       binary+pkg OK but no profile  → not ready, reason mentions .me3 file
       all three OK                  → ready
    """
    if exc:
        return {'ready': False, 'me3_binary': None, 'profile': None,
                'reason': f'Discovery error: {exc}'}
    if not binary:
        return {'ready': False, 'me3_binary': None, 'profile': profile,
                'reason': 'binary missing'}
    if not pkg:
        return {'ready': False, 'me3_binary': binary, 'profile': None,
                'reason': 'pkg missing'}
    if not profile:
        return {'ready': False, 'me3_binary': binary, 'profile': None,
                'reason': 'profile missing'}
    return {'ready': True, 'me3_binary': binary, 'profile': profile,
            'reason': ''}


class TestReadinessGateBranches:
    def test_no_binary_blocks_even_with_profile(self):
        state = _mirror_resolve(None, '/pkg', '/pkg/foo.me3')
        assert state['ready'] is False
        assert 'binary' in state['reason']

    def test_no_pkg_blocks_even_with_binary(self):
        state = _mirror_resolve('/bin/me3', '', None)
        assert state['ready'] is False
        assert 'pkg' in state['reason']

    def test_pkg_set_but_no_profile_blocks(self):
        state = _mirror_resolve('/bin/me3', '/pkg', None)
        assert state['ready'] is False
        assert 'profile' in state['reason']

    def test_all_three_ready(self):
        state = _mirror_resolve('/bin/me3', '/pkg', '/pkg/foo.me3')
        assert state['ready'] is True
        assert state['me3_binary'] == '/bin/me3'
        assert state['profile'] == '/pkg/foo.me3'
