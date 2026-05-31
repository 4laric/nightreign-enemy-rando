"""
test_help_overlays.py — v0.26.x per-tab help overlays.

Each major tab (Generate, Heritage, ER Assets) carries a "?" button
that opens a modal explaining what the tab is for, key options, and
common pitfalls. The modal is driven by TAB_HELP_CONTENT — single
source of truth for help text so adding/editing content is one place.

Three layers:
  1. TAB_HELP_CONTENT shape — dict keyed by tab name, each entry has
     'title' + 'body' strings. Lock in that adding a tab without
     content surfaces as a visible error rather than an empty modal.
  2. _show_tab_help + _add_help_button methods exist and behave
     defensively.
  3. The three target tabs actually wire ? buttons via _add_help_button.
"""
import ast
import os
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


@pytest.fixture(scope='module')
def tab_help_content(gui_source):
    """Parse TAB_HELP_CONTENT out of the source via AST so we can
    introspect entries without instantiating Tk."""
    tree = ast.parse(gui_source)
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == 'RandoGUI':
            for item in cls.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if (isinstance(target, ast.Name)
                                and target.id == 'TAB_HELP_CONTENT'):
                            return ast.literal_eval(item.value)
    pytest.fail('TAB_HELP_CONTENT class attribute not found on RandoGUI')


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
# TAB_HELP_CONTENT structure
# ---------------------------------------------------------------------

class TestTabHelpContent:
    def test_is_dict(self, tab_help_content):
        assert isinstance(tab_help_content, dict)

    def test_has_entries(self, tab_help_content):
        """Locks in non-empty — empty dict would make every ? button
        no-op silently."""
        assert len(tab_help_content) >= 7, (
            f'TAB_HELP_CONTENT has only {len(tab_help_content)} entries — '
            f'at least 7 expected (Generate, Paths, Excluded, Hub Maps, '
            f'Heritage, ER Assets, Spoiler — all user-facing tabs).')

    @pytest.mark.parametrize('tab_key', [
        'generate', 'heritage', 'er_assets',
        # v0.26.x extension — help coverage for the remaining tabs
        'paths', 'excluded', 'hub_maps', 'spoiler',
    ])
    def test_required_tab_has_content(self, tab_help_content, tab_key):
        """The target tabs (which call _add_help_button) MUST have
        matching entries — otherwise their ? button opens an empty
        modal."""
        assert tab_key in tab_help_content, (
            f"Tab key {tab_key!r} missing from TAB_HELP_CONTENT — "
            f"its ? button has nothing to show.")

    def test_each_entry_has_title_and_body(self, tab_help_content):
        for key, entry in tab_help_content.items():
            assert isinstance(entry, dict), (
                f'TAB_HELP_CONTENT[{key!r}] should be a dict, got '
                f'{type(entry).__name__}')
            assert 'title' in entry, (
                f'TAB_HELP_CONTENT[{key!r}] missing title')
            assert 'body' in entry, (
                f'TAB_HELP_CONTENT[{key!r}] missing body')
            assert isinstance(entry['title'], str) and entry['title'], (
                f'TAB_HELP_CONTENT[{key!r}].title must be a non-empty '
                f'string')
            assert isinstance(entry['body'], str) and entry['body'], (
                f'TAB_HELP_CONTENT[{key!r}].body must be a non-empty '
                f'string')

    def test_bodies_are_substantial(self, tab_help_content):
        """Helps catch placeholder-only content. A real help body
        should be at least a few sentences."""
        for key, entry in tab_help_content.items():
            assert len(entry['body']) >= 200, (
                f'TAB_HELP_CONTENT[{key!r}].body is only '
                f'{len(entry["body"])} chars — probably a placeholder. '
                f'Help text should be at least a few sentences.')

    def test_bodies_have_section_headers(self, tab_help_content):
        """The modal styles ALL-CAPS lines as section headers. Each
        body should have at least one to give the help structure."""
        for key, entry in tab_help_content.items():
            body = entry['body']
            has_header = any(
                line and line == line.upper() and not line.startswith(' ')
                and any(c.isalpha() for c in line)
                for line in body.splitlines())
            assert has_header, (
                f'TAB_HELP_CONTENT[{key!r}].body has no ALL-CAPS '
                f'section headers — the modal\'s section-styling tag '
                f'has nothing to highlight.')


# ---------------------------------------------------------------------
# _show_tab_help method
# ---------------------------------------------------------------------

class TestShowTabHelpMethod:
    def test_method_exists(self, gui_source):
        assert 'def _show_tab_help(self, tab_key' in gui_source, (
            '_show_tab_help method missing — _add_help_button buttons '
            'would call into nothing.')

    def test_reads_from_tab_help_content(self, gui_source):
        body = _extract_method_body(gui_source, '_show_tab_help')
        assert 'TAB_HELP_CONTENT' in body, (
            '_show_tab_help should look up content via TAB_HELP_CONTENT '
            '— otherwise the help text is hardcoded somewhere unmaintainable.')

    def test_handles_unknown_tab_key(self, gui_source):
        """If a tab_key isn't in TAB_HELP_CONTENT, the method must
        no-op gracefully (silent return) rather than crash with
        KeyError or open an empty modal."""
        body = _extract_method_body(gui_source, '_show_tab_help')
        # Either a `.get()` lookup or an `if entry is None` guard
        assert ('.get(tab_key' in body) or ('is None' in body) or \
               ('if entry' in body), (
            '_show_tab_help should handle an unknown tab_key gracefully '
            '— neither .get() nor an explicit None check found.')

    def test_uses_toplevel_modal(self, gui_source):
        body = _extract_method_body(gui_source, '_show_tab_help')
        assert 'Toplevel(' in body, (
            'Help should open as a Toplevel modal, not draw into the '
            'main window.')

    def test_esc_closes_modal(self, gui_source):
        """Consistent with the shortcuts cheatsheet — Esc closes."""
        body = _extract_method_body(gui_source, '_show_tab_help')
        assert '<Escape>' in body, (
            '_show_tab_help should bind <Escape> to close — standard '
            'modal convention.')

    def test_has_close_button(self, gui_source):
        """Mouse-only users need an explicit Close button."""
        body = _extract_method_body(gui_source, '_show_tab_help')
        assert 'text="Close"' in body or "text='Close'" in body, (
            '_show_tab_help should include a Close button for '
            'mouse-only users.')

    def test_returns_break(self, gui_source):
        """Like other shortcut/modal handlers, return 'break' so any
        bound keyboard sequence doesn't trigger Tk default behaviour."""
        body = _extract_method_body(gui_source, '_show_tab_help')
        assert "return 'break'" in body, (
            '_show_tab_help should return "break" so future keyboard '
            'bindings don\'t trigger Tk default behaviour.')


# ---------------------------------------------------------------------
# _add_help_button helper
# ---------------------------------------------------------------------

class TestAddHelpButtonHelper:
    def test_method_exists(self, gui_source):
        assert 'def _add_help_button(self, parent, tab_key)' in gui_source

    def test_creates_button(self, gui_source):
        body = _extract_method_body(gui_source, '_add_help_button')
        assert 'ttk.Button(' in body, (
            '_add_help_button should construct a ttk.Button.')

    def test_button_label_is_question_mark(self, gui_source):
        """The standard UX convention is a "?" icon button. Locks
        in that we don't accidentally lose the visual affordance."""
        body = _extract_method_body(gui_source, '_add_help_button')
        assert 'text="?"' in body or "text='?'" in body, (
            '_add_help_button should label the button "?" — the '
            'standard help-icon convention.')

    def test_button_wires_to_show_tab_help(self, gui_source):
        body = _extract_method_body(gui_source, '_add_help_button')
        assert '_show_tab_help(' in body, (
            '_add_help_button must wire the click to _show_tab_help — '
            'otherwise it\'s a dead button.')

    def test_button_has_tooltip(self, gui_source):
        """Even a "?" button benefits from a hover tooltip — first-time
        users may not be sure what clicking does."""
        body = _extract_method_body(gui_source, '_add_help_button')
        assert 'Tooltip(' in body, (
            '_add_help_button should attach a Tooltip — explains the '
            '"?" before the user has to click it.')


# ---------------------------------------------------------------------
# Tab integrations — the three target tabs actually use the helper
# ---------------------------------------------------------------------

class TestTabIntegrations:
    """Each of the tabs that have TAB_HELP_CONTENT must actually call
    _add_help_button. Without this, the content exists but no button
    to surface it."""

    def test_generate_tab_has_help_button(self, gui_source):
        body = _extract_method_body(gui_source, '_build_main_tab')
        assert "_add_help_button(" in body, (
            'Generate tab (_build_main_tab) must call _add_help_button '
            'or the "generate" help content is unreachable.')
        assert "'generate'" in body, (
            'Generate tab should pass tab_key="generate" to '
            '_add_help_button.')

    def test_heritage_tab_has_help_button(self, gui_source):
        body = _extract_method_body(gui_source, '_build_heritage_safety_subtab')
        assert "_add_help_button(" in body, (
            'Heritage tab (_build_heritage_safety_subtab) must call '
            '_add_help_button or the "heritage" help content is '
            'unreachable.')
        assert "'heritage'" in body

    def test_er_assets_tab_has_help_button(self, gui_source):
        body = _extract_method_body(gui_source, '_build_chr_inventory_tab')
        assert "_add_help_button(" in body, (
            'ER Assets tab (_build_chr_inventory_tab) must call '
            '_add_help_button or the "er_assets" help content is '
            'unreachable.')
        assert "'er_assets'" in body

    # v0.26.x — full-coverage extension to the four remaining tabs
    def test_paths_tab_has_help_button(self, gui_source):
        body = _extract_method_body(gui_source, '_build_paths_tab')
        assert "_add_help_button(" in body, (
            'Paths tab (_build_paths_tab) must call _add_help_button '
            'so the "paths" help content is reachable.')
        assert "'paths'" in body



    def test_spoiler_tab_has_help_button(self, gui_source):
        body = _extract_method_body(gui_source, '_build_spoiler_tab')
        assert "_add_help_button(" in body, (
            'Spoiler tab (_build_spoiler_tab) must call _add_help_button '
            'so the "spoiler" help content is reachable.')
        assert "'spoiler'" in body


class TestNoOrphanContent:
    """Every key in TAB_HELP_CONTENT should be referenced by at least
    one _add_help_button call. Catches orphan content (text written
    for a removed tab, etc.) and orphan buttons (button calls a key
    that doesn't exist)."""

    def test_each_content_key_has_a_button(self, gui_source, tab_help_content):
        for key in tab_help_content.keys():
            quoted = f"'{key}'"
            assert quoted in gui_source, (
                f'Tab help content key {key!r} exists in TAB_HELP_CONTENT '
                f'but no _add_help_button call references it — orphan '
                f'help text.')

    def test_each_button_call_references_real_key(self, gui_source,
                                                    tab_help_content):
        """Find every _add_help_button call and confirm the key it
        passes exists in TAB_HELP_CONTENT."""
        import re
        # _add_help_button(parent, 'key') — capture the quoted key
        pattern = r"_add_help_button\([^,]+,\s*['\"](\w+)['\"]\)"
        for m in re.finditer(pattern, gui_source):
            key = m.group(1)
            assert key in tab_help_content, (
                f'_add_help_button(..., {key!r}) references a key not '
                f'present in TAB_HELP_CONTENT — orphan button. Either '
                f'add the content or remove the button call.')
