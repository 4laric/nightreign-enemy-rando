"""
test_first_launch_wizard.py — tests for the Tier 1 UX #2 wizard.

Two layers:
  1. Pure-function tests for should_run_wizard() and wizard_summary_lines()
     — extracted from the GUI source without importing Tk.
  2. Source-inspection tests locking in the FirstLaunchWizard class's
     structural contract (4 named screens, modal grab, Back/Next/Skip nav)
     and the main() integration (--setup flag, calls should_run_wizard,
     persists config before RandoGUI starts).
"""
import os
import importlib.util
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


def _extract_func(src, fn_name):
    """Pull a top-level function definition out of the source by name.
    Returns the source text; raises AssertionError if not found."""
    needle = f'def {fn_name}('
    start = src.find(needle)
    assert start != -1, f'function {fn_name} not found in source'
    lines = src[start:].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith('#'):
            break
        body.append(line)
    return '\n'.join(body)


@pytest.fixture(scope='module')
def should_run_wizard(gui_source):
    """Extract and compile the pure function. validate_path_kind is a
    dependency for wizard_summary_lines but not for this one — keep
    them separate so a regression in one doesn't kill the other's tests."""
    func_src = _extract_func(gui_source, 'should_run_wizard')
    ns = {}
    exec(func_src, ns)
    return ns['should_run_wizard']


@pytest.fixture(scope='module')
def wizard_summary_lines(gui_source):
    """Extract wizard_summary_lines AND its dependency (validate_path_kind)
    into a shared namespace so the function can call its dependency."""
    ns = {}
    # validate_path_kind first (dependency)
    exec(_extract_func(gui_source, 'validate_path_kind'), ns)
    # Then the function under test
    exec(_extract_func(gui_source, 'wizard_summary_lines'), ns)
    return ns['wizard_summary_lines']


# ---------------------------------------------------------------------
# should_run_wizard — the gate that decides whether to intercept startup
# ---------------------------------------------------------------------

class TestShouldRunWizard:
    """The wizard runs ONLY when no root paths are configured.
    Any saved value in any of the three root keys means the user has
    been here before — show the main GUI instead of a modal."""

    def test_empty_config_runs_wizard(self, should_run_wizard):
        assert should_run_wizard({}) is True

    def test_all_three_blank_runs_wizard(self, should_run_wizard):
        """Blank-string values count as 'not configured' — likely a
        config from a previous abandoned attempt or a manual reset."""
        cfg = {
            'game_install': '',
            'er_install': '',
            'me3_package': '',
        }
        assert should_run_wizard(cfg) is True

    def test_whitespace_only_blank_runs_wizard(self, should_run_wizard):
        """A user who clears a field by selecting + deleting may leave
        whitespace; treat that as blank."""
        cfg = {
            'game_install': '   ',
            'er_install': '\t',
            'me3_package': '\n ',
        }
        assert should_run_wizard(cfg) is True

    def test_game_install_set_skips_wizard(self, should_run_wizard):
        """Even if only NR is set, the user has been here before."""
        cfg = {'game_install': '/some/path'}
        assert should_run_wizard(cfg) is False

    def test_er_install_alone_skips_wizard(self, should_run_wizard):
        cfg = {'er_install': '/some/path'}
        assert should_run_wizard(cfg) is False

    def test_me3_alone_skips_wizard(self, should_run_wizard):
        cfg = {'me3_package': '/some/path'}
        assert should_run_wizard(cfg) is False

    def test_non_dict_defensive_true(self, should_run_wizard):
        """If saved is None (load failure) or some unexpected type, run
        the wizard as the safe default. Better to over-show than to
        silently skip on a corrupted config."""
        assert should_run_wizard(None) is True
        assert should_run_wizard('not a dict') is True
        assert should_run_wizard([]) is True

    def test_ignores_other_keys(self, should_run_wizard):
        """Keys we don't care about (msg_basename, custom user keys,
        etc.) don't affect the decision."""
        cfg = {'msg_basename': 'item_dlc01.msgbnd.dcx',
               'some_other_key': 'value'}
        assert should_run_wizard(cfg) is True


# ---------------------------------------------------------------------
# wizard_summary_lines — Done-screen content builder
# ---------------------------------------------------------------------

class TestWizardSummaryLines:
    def test_returns_three_lines(self, wizard_summary_lines):
        """Always 3 entries: NR, ER, ME3 — even if some are blank."""
        lines = wizard_summary_lines({})
        assert len(lines) == 3

    def test_each_line_is_state_text_tuple(self, wizard_summary_lines):
        lines = wizard_summary_lines({})
        for entry in lines:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            state, text = entry
            assert state in ('ok', 'warn', 'error', 'unknown')
            assert isinstance(text, str) and text

    def test_er_blank_specifically_marked_skipped(self, wizard_summary_lines):
        """ER is optional; a blank ER should read as 'skipped' not as
        a generic 'not set' (which would feel like an error). The other
        two read as plain 'not set'."""
        lines = wizard_summary_lines({})
        labels = {text.split(':')[0]: (state, text) for state, text in lines}
        er_state, er_text = labels['Elden Ring install']
        assert er_state == 'unknown'
        assert 'skipped' in er_text.lower() or 'heritage' in er_text.lower()

    def test_blank_nr_marked_warn(self, wizard_summary_lines):
        """NR is required; a blank NR is a 'warn' not an 'unknown' —
        it's a real gap not an explicit opt-out."""
        lines = wizard_summary_lines({})
        labels = {text.split(':')[0]: (state, text) for state, text in lines}
        nr_state, nr_text = labels['Nightreign install']
        assert nr_state == 'warn'
        assert 'not set' in nr_text.lower()

    def test_set_path_uses_validator(self, wizard_summary_lines, tmp_path):
        """When a path is set, summary uses validate_path_kind state."""
        # Build a real NR-shaped dir so validator returns 'ok'
        install = tmp_path / 'NIGHTREIGN'
        mapstudio = install / 'map' / 'mapstudio'
        mapstudio.mkdir(parents=True)
        (mapstudio / 'm10_00_00_00.msb.dcx').write_text('(stub)')
        cfg = {'game_install': str(install)}
        lines = wizard_summary_lines(cfg)
        labels = {text.split(':')[0]: (state, text) for state, text in lines}
        nr_state, _ = labels['Nightreign install']
        assert nr_state == 'ok'


# ---------------------------------------------------------------------
# FirstLaunchWizard — source-inspection structural locks
# ---------------------------------------------------------------------

class TestFirstLaunchWizardStructure:
    """The wizard is a Tk Toplevel modal — we can't instantiate without
    a display, but we can lock in its structure."""

    def test_class_defined(self, gui_source):
        assert 'class FirstLaunchWizard:' in gui_source

    def test_has_three_screens(self, gui_source):
        """SCREEN_NAMES must declare all 3 screens. If a future edit
        adds/drops one, the integration test for main() may also need
        to update — fail loud here. (The Oodle screen was removed once
        Oodle resolution moved to an on-demand check at run time.)"""
        # The class-level attribute should be present as a list literal
        # with exactly these 3 names in order
        idx = gui_source.find('class FirstLaunchWizard:')
        snippet = gui_source[idx:idx + 2000]
        assert "SCREEN_NAMES = ['welcome', 'output', 'done']" in snippet

    def test_all_three_screen_builders_exist(self, gui_source):
        for screen in ('welcome', 'output', 'done'):
            assert f'def _build_{screen}(self):' in gui_source, (
                f'_build_{screen} method missing — screen "{screen}" '
                f'would error on display.')

    def test_modal_with_grab_set(self, gui_source):
        """A wizard that doesn't grab the focus isn't really modal;
        users can click into the main window behind it and get
        confused about state ownership."""
        idx = gui_source.find('class FirstLaunchWizard:')
        class_body = gui_source[idx:gui_source.find('\nclass ', idx + 1)
                                  if gui_source.find('\nclass ', idx + 1) != -1
                                  else idx + 30000]
        assert 'grab_set()' in class_body, (
            'FirstLaunchWizard must call grab_set() to enforce modality.')
        assert "transient(parent)" in class_body, (
            'FirstLaunchWizard must call transient() so window manager '
            'treats it as a child of the main window (stays on top, '
            'minimises with parent, etc.).')

    def test_nav_buttons(self, gui_source):
        """Back, Next, Skip — all three must exist for the nav flow."""
        idx = gui_source.find('class FirstLaunchWizard:')
        class_body = gui_source[idx:idx + 30000]
        # Back button: ttk.Button with text containing 'Back'
        assert "text='← Back'" in class_body or "text=\"← Back\"" in class_body
        # Next button — text becomes 'All set.' on last screen
        assert "'Next →'" in class_body or '"Next →"' in class_body
        # Skip link — Label with hand cursor + click binding
        assert 'Skip' in class_body
        assert "cursor='hand2'" in class_body

    def test_completed_flag(self, gui_source):
        """The wizard exposes a `completed` attribute the caller checks
        to distinguish 'user finished' from 'user closed via X or Skip'."""
        idx = gui_source.find('class FirstLaunchWizard:')
        class_body = gui_source[idx:idx + 30000]
        assert 'self.completed = False' in class_body
        assert 'self.completed = True' in class_body, (
            "Wizard's _finish must set completed=True; without that "
            "the caller can't tell if the user clicked through or skipped.")

    def test_config_attribute_writeback(self, gui_source):
        """The wizard exposes a `config` attribute holding what the
        user entered — the caller reads this back and saves it."""
        idx = gui_source.find('class FirstLaunchWizard:')
        class_body = gui_source[idx:idx + 30000]
        assert 'self.config = dict(initial_config' in class_body, (
            "Wizard's __init__ must initialise self.config from "
            "initial_config so the main GUI can pre-populate fields "
            "from saved values.")


# ---------------------------------------------------------------------
# main() integration — wizard is actually invoked at startup
# ---------------------------------------------------------------------

class TestMainIntegration:
    def test_main_imports_argparse(self, gui_source):
        """main() needs argparse for the --setup flag."""
        main_src = _extract_func(gui_source, 'main')
        assert 'argparse' in main_src

    def test_main_recognises_setup_flag(self, gui_source):
        main_src = _extract_func(gui_source, 'main')
        assert "'--setup'" in main_src or '"--setup"' in main_src

    def test_main_calls_should_run_wizard(self, gui_source):
        main_src = _extract_func(gui_source, 'main')
        assert 'should_run_wizard(' in main_src, (
            'main() must call should_run_wizard to decide whether to '
            'intercept startup. Without that call, the wizard never '
            'runs even for fresh installs.')

    def test_main_instantiates_wizard_before_randogui(self, gui_source):
        """The wizard runs BEFORE the main GUI loads. Otherwise the
        user sees a half-built window flicker behind the modal."""
        main_src = _extract_func(gui_source, 'main')
        wiz_pos = main_src.find('FirstLaunchWizard(')
        rando_pos = main_src.find('RandoGUI(')
        assert wiz_pos != -1, 'main() must instantiate FirstLaunchWizard'
        assert rando_pos != -1, 'main() must instantiate RandoGUI'
        assert wiz_pos < rando_pos, (
            'FirstLaunchWizard must be constructed before RandoGUI so '
            'the modal sits over the startup, not over a built GUI.')

    def test_main_persists_wizard_result(self, gui_source):
        """After the wizard closes, main() must save the result to
        disk so RandoGUI's _load_root_paths picks it up."""
        main_src = _extract_func(gui_source, 'main')
        assert '_save_paths_to_disk(' in main_src, (
            'main() must persist the wizard result before launching '
            'RandoGUI — otherwise the wizard work is lost on startup.')

    def test_main_withdraws_root_during_wizard(self, gui_source):
        """The Tk root window must be hidden while the wizard is open
        so it doesn't flash an empty frame behind the modal."""
        main_src = _extract_func(gui_source, 'main')
        assert 'root.withdraw()' in main_src
        assert 'root.deiconify()' in main_src, (
            'After the wizard closes, root.deiconify() must restore '
            'the main window before RandoGUI builds into it.')

    def test_main_wizard_exception_doesnt_block_startup(self, gui_source):
        """A wizard failure (e.g. discovery crash) must NOT prevent the
        main GUI from opening. User can always configure manually."""
        main_src = _extract_func(gui_source, 'main')
        # The wizard invocation should be wrapped in try/except so any
        # failure falls through to RandoGUI.
        # Find the wizard invocation block
        wiz_idx = main_src.find('FirstLaunchWizard(')
        # Look back from there to find an enclosing try; look forward
        # to find an except.
        head = main_src[:wiz_idx]
        tail = main_src[wiz_idx:]
        assert 'try:' in head, (
            'The wizard invocation should be wrapped in try/except so a '
            'discovery or Tk failure does not block startup.')
        assert 'except' in tail, (
            'No except clause after the wizard invocation — a wizard '
            'crash will propagate and kill main().')
