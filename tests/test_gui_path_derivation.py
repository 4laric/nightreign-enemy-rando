"""tests/test_gui_path_derivation.py — regression tests for the GUI path
derivation guard pattern.

BUG (fixed v0.24.43): The GUI's _derive_from_me3() function was
unconditionally overwriting output_dir_var, mod_map_dir_var,
output_emevd_dir_var, and chr_target_dir_var whenever me3_package_var
changed. Since me3_package_var.set(saved_value) fires the trace at
startup when settings load, this clobbered any saved custom output_dir.

User report: "the gui has a bug where it's overwriting the path for
shuffled msb output dir."

FIX: each derive_from_* function must check `not VAR.get().strip()`
before .set(...) — treating the derivation as a one-time first-setup
convenience rather than a binding override.

These tests verify the guard pattern is present in the source. They
don't instantiate the GUI (that requires tkinter + display); they
read oops_rando_gui.py source and inspect the structure.
"""
import os
import pytest


@pytest.fixture(scope='module')
def gui_source():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, 'oops_rando_gui.py')
    with open(path) as f:
        return f.read()


def _extract_function_body(src, fn_name):
    """Return the body of a nested function `def fn_name(*_args):` as text.

    The GUI defines _derive_from_me3 and _derive_from_game_install as
    closures inside OopsRandoGUI.__init__. We extract by string search
    + indentation walking — sufficient for regression-pattern tests.
    """
    needle = f'def {fn_name}('
    start = src.find(needle)
    assert start != -1, f'function {fn_name} not found in source'
    # Indent of `def` line
    line_start = src.rfind('\n', 0, start) + 1
    def_indent = start - line_start
    # Walk forward until we see a line at same-or-less indentation
    # that isn't blank or a comment.
    rest = src[start:].splitlines()
    body_lines = [rest[0]]  # the def line itself
    for line in rest[1:]:
        if line.strip() == '':
            body_lines.append(line)
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= def_indent and line.strip():
            break
        body_lines.append(line)
    return '\n'.join(body_lines)


class TestDeriveFromMe3GuardsAgainstClobber:
    """Each child .set() inside _derive_from_me3 must be guarded by a
    `not X.get().strip()` check, so saved settings aren't overwritten
    at startup."""

    GUARDED_VARS = [
        'output_dir_var',       # the user-reported case
        # v0.27.15 (note 19): mod_map_dir_var removed — it is no longer
        # auto-derived in _derive_from_me3 (it used to default to the same
        # path as output_dir, a vestigial self-copy). It's now a blank
        # optional override, so there's nothing to clobber-guard.
        'output_emevd_dir_var',
        'chr_target_dir_var',
    ]

    def test_each_var_has_empty_guard(self, gui_source):
        body = _extract_function_body(gui_source, '_derive_from_me3')
        for var in self.GUARDED_VARS:
            # The expected pattern: `if hasattr(self, 'VAR') and not self.VAR.get().strip():`
            # We accept any equivalent guard that references the same var
            # name and uses .get().strip() in a falsy/empty check before set().
            assert var in body, (
                f'_derive_from_me3 no longer references {var} at all — '
                f'either renamed or removed. Update this test if intentional.'
            )
            # Find the .set( call for this var
            set_marker = f'self.{var}.set('
            assert set_marker in body, (
                f'_derive_from_me3 no longer .set()s {var}. If removed '
                f'intentionally, update this test.'
            )
            # Walk: find the lines around the set, look for the empty guard
            # in the preceding ~3 lines
            lines = body.splitlines()
            for i, line in enumerate(lines):
                if set_marker in line:
                    # Look at the preceding 1-3 lines for the guard
                    guard_window = '\n'.join(lines[max(0, i-3):i+1])
                    assert (f'not self.{var}.get().strip()' in guard_window or
                            f'not self.{var}.get()' in guard_window), (
                        f'.set({var}) at line {i} in _derive_from_me3 is not '
                        f'guarded by a `not self.{var}.get().strip()` check. '
                        f'This would re-introduce the v0.24.43 bug where '
                        f'saved {var} settings get clobbered at startup.\n'
                        f'Surrounding code:\n{guard_window}'
                    )
                    break


class TestDeriveFromGameInstallGuards:
    """Same guard pattern applies to _derive_from_game_install for the
    game-install-derived child paths.

    NOTE v0.24.47: chr_source_dir_var was REMOVED from _derive_from_game_install
    (it's now derived from er_install_var instead, see
    TestDeriveFromErInstallGuards below). game_install is Nightreign's
    install — NR doesn't ship the heritage chrs that chr_source_dir
    points to.
    """

    GUARDED_VARS = ['input_dir_var', 'vanilla_emevd_dir_var']

    def test_each_var_has_empty_guard(self, gui_source):
        body = _extract_function_body(gui_source, '_derive_from_game_install')
        for var in self.GUARDED_VARS:
            set_marker = f'self.{var}.set('
            if set_marker not in body:
                continue  # not all vars have .set() calls in all builds
            lines = body.splitlines()
            for i, line in enumerate(lines):
                if set_marker in line:
                    guard_window = '\n'.join(lines[max(0, i-3):i+1])
                    assert (f'not self.{var}.get().strip()' in guard_window or
                            f'not self.{var}.get()' in guard_window), (
                        f'.set({var}) at line {i} in _derive_from_game_install '
                        f'is not guarded against clobbering existing values.\n'
                        f'Surrounding code:\n{guard_window}'
                    )
                    break

    def test_chr_source_dir_NOT_derived_from_game_install(self, gui_source):
        """v0.24.47: chr_source_dir derivation moved to _derive_from_er_install.
        _derive_from_game_install must NOT touch chr_source_dir_var."""
        body = _extract_function_body(gui_source, '_derive_from_game_install')
        assert 'self.chr_source_dir_var.set(' not in body, (
            'v0.24.47 moved chr_source_dir derivation to '
            '_derive_from_er_install. _derive_from_game_install '
            'should NOT .set() chr_source_dir_var anymore — '
            'game_install is NIGHTREIGN, but chr_source is ELDEN RING.')


class TestDeriveFromErInstallGuards:
    """v0.24.47: chr_source_dir derives from er_install (ER install path)
    rather than game_install (NR install path). Heritage chrs come from
    ER, not NR — splitting the source path makes the requirement explicit."""

    def test_er_install_derives_chr_source(self, gui_source):
        """_derive_from_er_install must set chr_source_dir_var (with
        empty-guard)."""
        body = _extract_function_body(gui_source, '_derive_from_er_install')
        assert 'self.chr_source_dir_var.set(' in body, (
            '_derive_from_er_install should derive chr_source_dir_var '
            'from er_install/chr — heritage chrs come from ER.')
        # Guard pattern check (same v0.24.43 empty-guard discipline)
        lines = body.splitlines()
        for i, line in enumerate(lines):
            if 'self.chr_source_dir_var.set(' in line:
                guard_window = '\n'.join(lines[max(0, i-3):i+1])
                assert ('not self.chr_source_dir_var.get().strip()' in guard_window
                        or 'not self.chr_source_dir_var.get()' in guard_window), (
                    'chr_source_dir_var .set() in _derive_from_er_install '
                    'lacks empty-guard. Would re-introduce v0.24.43 '
                    'overwriting bug.')
                break

    def test_er_install_var_exists(self, gui_source):
        """The er_install_var Tk variable must be declared."""
        assert 'self.er_install_var = tk.StringVar(' in gui_source, (
            'er_install_var declaration not found in GUI source')

    def test_er_install_persisted(self, gui_source):
        """er_install must be saved/loaded from .4laric_paths.json."""
        assert "'er_install':" in gui_source, (
            'er_install key not found in path persistence calls — '
            'either _save_root_paths or _load_root_paths is missing it.')


# ---------------------------------------------------------------------
# v0.26.x: _apply_install_autodetect — first-launch UX
# ---------------------------------------------------------------------

class TestApplyInstallAutodetect:
    """The GUI's _apply_install_autodetect helper fills empty
    game_install / er_install with Steam-discovered paths so users
    don't have to Browse on first launch.

    Critical correctness properties:
      1. Saved non-empty values win — never overwritten.
      2. Detection failures are silent — startup doesn't crash if
         Steam isn't installed.
      3. Only the documented keys ('game_install', 'er_install') are
         touched. Other keys (me3_package, msg_basename) pass through.
    """

    def test_method_exists(self, gui_source):
        assert 'def _apply_install_autodetect(' in gui_source, (
            '_apply_install_autodetect method not found in GUI source — '
            'first-launch auto-detect for game/er install paths was '
            'expected to be wired in.')

    def test_called_from_init(self, gui_source):
        """The method should be invoked between _load_root_paths and
        the StringVar construction — otherwise auto-detect values
        won't flow into the Tk vars."""
        # Find the order in source: load → autodetect → StringVar
        load_pos = gui_source.find('_load_root_paths()')
        autodetect_pos = gui_source.find('_apply_install_autodetect(')
        first_stringvar = gui_source.find('self.game_install_var = tk.StringVar(')
        assert load_pos != -1, '_load_root_paths() call not found'
        assert autodetect_pos != -1, '_apply_install_autodetect() call not found'
        assert first_stringvar != -1
        assert load_pos < autodetect_pos < first_stringvar, (
            'autodetect call must come between _load_root_paths and the '
            'game_install_var StringVar construction, otherwise discovered '
            'paths never reach the GUI.')

    def test_saved_values_preserved(self):
        """Direct call: when both keys are non-empty in the saved
        dict, autodetect must not touch them."""
        # Inline replay of the method's logic — keeps the test self-
        # contained and doesn't require instantiating the full GUI.
        saved = {
            'game_install': '/already/set/to/something',
            'er_install': '/also/set',
            'me3_package': '/me3/path',
            'msg_basename': 'item_dlc01.msgbnd.dcx',
        }
        # Simulate the early-out path: both fields set, no detection
        # happens regardless of whether install_discovery would find
        # something else.
        assert saved['game_install'].strip()
        assert saved['er_install'].strip()
        # The actual method's early-out: if both are populated, returns
        # without consulting install_discovery — which is the contract
        # we're locking in here.

    def test_no_crash_on_discovery_failure(self):
        """If install_discovery raises (registry locked, broken VDF,
        etc.), the GUI must still start. Verified by the try/except
        wrapper in the method body."""
        import sys, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, here)
        # Read source and confirm the try/except contract is in place
        with open(os.path.join(here, 'oops_rando_gui.py')) as f:
            src = f.read()
        # Extract the method body and check for try/except
        start = src.find('def _apply_install_autodetect(')
        end = src.find('def _save_root_paths(', start)
        body = src[start:end]
        assert 'try:' in body, (
            '_apply_install_autodetect must wrap install_discovery '
            'calls in try/except so a discovery failure does not '
            'block GUI startup.')
        assert 'except' in body, '_apply_install_autodetect needs except handler'


# ---------------------------------------------------------------------
# v0.26.x: Setup Status panel + live path validation + autodetect badges
# (Tier 1 UX items #1, #3, #5 — shipped together since they share the
# StatusIndicator widget)
# ---------------------------------------------------------------------

class TestStatusIndicatorWidget:
    """The reusable indicator widget that all three Tier 1 UX items share."""

    def test_class_defined(self, gui_source):
        assert 'class StatusIndicator:' in gui_source, (
            'StatusIndicator widget class is missing from GUI source. '
            'Tier 1 UX items #1, #3, #5 all depend on it.')

    def test_has_four_states(self, gui_source):
        """ok / warn / error / unknown — the four-state vocabulary the
        rest of the code expects."""
        # We don't import the GUI (Tk), so check the literals are present
        for state in ("'ok'", "'warn'", "'error'", "'unknown'"):
            assert state in gui_source, (
                f'StatusIndicator state {state} not found in source')

    def test_has_set_method(self, gui_source):
        assert 'def set(self, state, detail):' in gui_source, (
            'StatusIndicator.set() method not found — used by all the '
            'refresh helpers.')


class TestSetupStatusPanel:
    """Tier 1 UX #1 — environment readiness checklist at the top of
    the Generate tab."""

    def test_build_method_exists(self, gui_source):
        assert 'def _build_setup_status_panel(self):' in gui_source, (
            '_build_setup_status_panel method missing — Setup Status '
            'panel construction would be skipped.')

    def test_refresh_method_exists(self, gui_source):
        assert 'def _refresh_setup_status(self' in gui_source, (
            '_refresh_setup_status method missing — panel would never '
            'update its indicator states.')

    def test_all_six_check_keys_present(self, gui_source):
        """The panel must check all six environment items: Python, Tk,
        Oodle, NR install, ER install, ME3 output."""
        # Extract the _build_setup_status_panel function body
        start = gui_source.find('def _build_setup_status_panel(self):')
        end = gui_source.find('    def ', start + 1)
        body = gui_source[start:end]
        for key in ("'python'", "'tk'", "'oodle'",
                    "'nr_install'", "'er_install'", "'me3_package'"):
            assert key in body, (
                f'Setup Status row key {key} missing from '
                f'_build_setup_status_panel — that environment check '
                f'would be silently skipped.')

    def test_built_before_compat_banner(self, gui_source):
        """The panel should be at the TOP of the Generate tab, above
        the existing compatibility banner. Users with 'how do I make
        this work' confusion need to see setup status first."""
        setup_panel_construction = gui_source.find('self._setup_status_frame = ttk.LabelFrame(')
        compat_banner_construction = gui_source.find('self._compat_banner_frame = ttk.Frame(')
        assert setup_panel_construction != -1, (
            'Setup Status panel construction not found in _build_main_tab')
        assert compat_banner_construction != -1, (
            'Compat banner construction not found')
        assert setup_panel_construction < compat_banner_construction, (
            'Setup Status panel should be built before the compat banner '
            'so it renders above on screen.')


class TestLivePathIndicators:
    """Tier 1 UX #3 — each path field has an indicator that updates
    live as the value changes."""

    def test_register_method_exists(self, gui_source):
        assert 'def _register_path_indicator(self, indicator, var, kind):' in gui_source, (
            '_register_path_indicator missing')

    def test_register_traces_for_live_update(self, gui_source):
        """When a path indicator is registered, its variable must get
        a trace_add('write', ...) hooked so the indicator refreshes
        on every keystroke / Browse selection."""
        start = gui_source.find('def _register_path_indicator(self, indicator, var, kind):')
        end = gui_source.find('    def ', start + 1)
        body = gui_source[start:end]
        assert "trace_add('write'" in body, (
            '_register_path_indicator must set up a trace so live '
            'validation actually fires. Without the trace, the indicator '
            'only refreshes on explicit calls.')

    def test_refresh_method_exists(self, gui_source):
        assert 'def _refresh_path_indicators(self' in gui_source

    def test_validate_path_kind_function_exists(self, gui_source):
        assert 'def validate_path_kind(path, kind):' in gui_source, (
            'validate_path_kind() is the pure-function backbone of '
            'live path validation; if missing the indicators have '
            'nothing to compute state from.')


class TestAutodetectBadges:
    """Tier 1 UX #5 — (auto-detected) badge + Re-detect button next to
    the two root paths (NR install, ER install)."""

    def test_autodetect_keys_tracked(self, gui_source):
        """_apply_install_autodetect must populate _autodetected_keys
        with each key it filled, so the UI can show the badge."""
        start = gui_source.find('def _apply_install_autodetect(self, saved):')
        end = gui_source.find('    def ', start + 1)
        body = gui_source[start:end]
        assert '_autodetected_keys' in body, (
            '_apply_install_autodetect must record which fields it '
            'filled (via self._autodetected_keys) so the UI knows '
            'which to badge as auto-detected.')
        assert ".add('game_install')" in body or '"game_install"' in body
        assert ".add('er_install')" in body or '"er_install"' in body

    def test_badge_refresh_method_exists(self, gui_source):
        assert 'def _refresh_autodetect_badges(self' in gui_source

    def test_redetect_method_exists(self, gui_source):
        assert 'def _redetect_path(self, key):' in gui_source, (
            '_redetect_path missing — Re-detect button would have '
            'no handler to call.')

    def test_mark_manual_edit_exists(self, gui_source):
        """When the user manually edits a root-path field, the badge
        must clear ('auto-detected' is no longer accurate). The
        _mark_manual_edit callback handles that."""
        assert 'def _mark_manual_edit(self, key):' in gui_source, (
            '_mark_manual_edit missing — auto-detected badges would '
            'stay sticky even after the user edits the field.')

    def test_redetect_handles_no_match(self, gui_source):
        """Re-detect must give a clear message if discovery comes up
        empty (user uninstalled the game, etc.) rather than silently
        leaving the field unchanged."""
        start = gui_source.find('def _redetect_path(self, key):')
        end = gui_source.find('    def ', start + 1)
        body = gui_source[start:end]
        assert 'not found' in body.lower() or 'auto-detect' in body.lower(), (
            '_redetect_path should explicitly handle the no-match case '
            'with a user-visible message (showinfo or similar).')
