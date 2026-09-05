"""
test_keyboard_shortcuts.py — tests for the v0.26.x keyboard shortcuts.

Three layers:
  1. Introspect the KEYBOARD_SHORTCUTS class attribute via AST (no Tk
     required) — verify the shape, that every listed handler is
     actually defined on the class, that the binding sequences are
     valid Tk syntax.
  2. Source-inspection on the handlers — they must call the right
     underlying actions and return 'break' to prevent event propagation.
  3. Source-inspection on the binding wire-up — _bind_keyboard_shortcuts
     must be called from __init__ AFTER _build_ui (otherwise the
     target buttons don't exist yet).
"""
import ast
import os
import re
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope='module')
def shortcuts_attribute(gui_source):
    """Parse the KEYBOARD_SHORTCUTS class attribute out of the source.
    Returns the literal value as a Python list of tuples."""
    tree = ast.parse(gui_source)
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == 'RandoGUI':
            for item in cls.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if (isinstance(target, ast.Name)
                                and target.id == 'KEYBOARD_SHORTCUTS'):
                            return ast.literal_eval(item.value)
    pytest.fail('KEYBOARD_SHORTCUTS class attribute not found on RandoGUI')


def _extract_method_body(src, name):
    needle = f'def {name}('
    start = src.find(needle)
    assert start != -1, f'method {name!r} not found'
    candidates = []
    for marker in ('\n    def ', '\n    @', '\nclass '):
        idx = src.find(marker, start + 1)
        if idx != -1:
            candidates.append(idx)
    end = min(candidates) if candidates else len(src)
    return src[start:end]


# ---------------------------------------------------------------------
# KEYBOARD_SHORTCUTS table — shape + handler resolution
# ---------------------------------------------------------------------

class TestShortcutsTableShape:
    def test_is_a_list(self, shortcuts_attribute):
        assert isinstance(shortcuts_attribute, list)

    def test_nonempty(self, shortcuts_attribute):
        """Locks in that the shortcuts feature isn't an empty stub."""
        assert len(shortcuts_attribute) >= 4, (
            f'KEYBOARD_SHORTCUTS has {len(shortcuts_attribute)} entries — '
            f'expected at least 4 core shortcuts (Randomize, Launch, '
            f'Random seed, Quit).')

    def test_entry_shape(self, shortcuts_attribute):
        """Each entry: (display_label, sequences_tuple, description,
        handler_name)."""
        for entry in shortcuts_attribute:
            assert isinstance(entry, tuple), (
                f'Each entry should be a tuple — got {type(entry).__name__}')
            assert len(entry) == 4, (
                f'Each entry needs (display, sequences, description, '
                f'handler_name) — got {len(entry)} elements: {entry}')
            display, sequences, description, handler = entry
            assert isinstance(display, str) and display, (
                'display label must be a non-empty string')
            assert isinstance(sequences, tuple) and len(sequences) >= 1, (
                'sequences must be a tuple with at least one binding')
            assert isinstance(description, str) and description, (
                'description must be a non-empty string')
            assert isinstance(handler, str) and handler.startswith('_'), (
                f'handler name must be a private method name, got {handler!r}')


class TestShortcutsBindingSyntax:
    """Every sequence string must be a valid Tk binding syntax —
    starts with '<', ends with '>'."""

    def test_binding_syntax(self, shortcuts_attribute):
        for entry in shortcuts_attribute:
            _, sequences, _, _ = entry
            for seq in sequences:
                assert seq.startswith('<') and seq.endswith('>'), (
                    f'Binding sequence {seq!r} is malformed — Tk '
                    f'requires <Modifier-key> syntax.')

    def test_no_duplicate_sequences(self, shortcuts_attribute):
        """A single key combo can't bind to two different handlers —
        only the last bind() call would take effect. Catches accidental
        collisions like assigning Ctrl+L to two different shortcuts."""
        seen = {}
        for entry in shortcuts_attribute:
            _, sequences, _, handler = entry
            for seq in sequences:
                if seq in seen:
                    pytest.fail(
                        f'Binding {seq!r} is used by both '
                        f'{seen[seq]!r} and {handler!r} — Tk will '
                        f'silently keep only the second one.')
                seen[seq] = handler


class TestShortcutsHandlersExist:
    """Each handler named in KEYBOARD_SHORTCUTS must be defined on
    the class. Otherwise the binding silently fails at runtime."""

    def test_all_handlers_defined(self, gui_source, shortcuts_attribute):
        for entry in shortcuts_attribute:
            _, _, description, handler = entry
            assert f'def {handler}(' in gui_source, (
                f'Handler {handler!r} listed in KEYBOARD_SHORTCUTS '
                f'(for {description!r}) but no method by that name '
                f'exists. _bind_keyboard_shortcuts uses getattr() with '
                f'a None default, so this would silently no-op at '
                f'runtime — without the test, the missing handler '
                f'wouldn\'t surface until someone hit the key.')


class TestCoreShortcutsCovered:
    """Each of the key actions has at least one binding — locks in
    that future refactors don't accidentally drop the headline
    shortcuts."""

    def _find_handler(self, shortcuts_attribute, handler_name):
        for entry in shortcuts_attribute:
            if entry[3] == handler_name:
                return entry
        return None

    def test_randomize_has_shortcut(self, shortcuts_attribute):
        entry = self._find_handler(shortcuts_attribute, '_shortcut_randomize')
        assert entry is not None, (
            'Randomize action has no shortcut — Ctrl+R / F5 missing.')

    def test_launch_has_shortcut(self, shortcuts_attribute):
        entry = self._find_handler(shortcuts_attribute, '_shortcut_launch')
        assert entry is not None, (
            'Launch action has no shortcut — Ctrl+L missing.')

    def test_help_has_shortcut(self, shortcuts_attribute):
        entry = self._find_handler(shortcuts_attribute, '_show_shortcuts_cheatsheet')
        assert entry is not None, (
            'F1 help shortcut missing — there should be a way to '
            'discover the shortcut list from inside the app.')


# ---------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------

class TestShortcutHandlers:
    def test_randomize_invokes_run_btn(self, gui_source):
        """The Randomize handler must invoke the actual button so the
        Cancel-toggle state is respected (the button's command flips
        between _run_shuffle and _cancel_shuffle while running)."""
        body = _extract_method_body(gui_source, '_shortcut_randomize')
        assert 'run_btn.invoke()' in body or 'run_btn.invoke(' in body, (
            'Randomize handler must invoke run_btn so the Cancel-while-'
            'running state is correctly handled. Calling _run_shuffle '
            'directly would bypass the Cancel path.')

    def test_randomize_respects_disabled_state(self, gui_source):
        """If the button is disabled, the shortcut should be a no-op —
        firing the underlying command from a disabled button would
        surprise users (the visual signal says 'wait', the keyboard
        says 'go anyway')."""
        body = _extract_method_body(gui_source, '_shortcut_randomize')
        # Should check state before invoking
        assert "state" in body and ("normal" in body or "'normal'" in body), (
            'Randomize handler must check button state before invoking — '
            'a disabled button should make the shortcut a no-op.')

    def test_launch_respects_disabled_state(self, gui_source):
        """Same logic for Launch — when ME3 isn't configured, the
        button is disabled and Ctrl+L should be a no-op."""
        body = _extract_method_body(gui_source, '_shortcut_launch')
        assert "state" in body and ("normal" in body or "'normal'" in body), (
            'Launch handler must check button state before invoking.')

    def test_handlers_return_break(self, gui_source):
        """Each handler returns 'break' so Tk's default key behaviour
        for that combo doesn't also fire. Without this, Ctrl+R in a
        Text widget would still 'do its thing' in addition to our
        Randomize action."""
        for handler_name in ('_shortcut_randomize', '_shortcut_launch',
                              '_shortcut_random_seed', '_shortcut_quit',
                              '_show_shortcuts_cheatsheet'):
            body = _extract_method_body(gui_source, handler_name)
            assert "return 'break'" in body, (
                f'{handler_name} must end with `return "break"` — '
                f'otherwise Tk\'s default behaviour for the key combo '
                f'fires alongside the shortcut action.')

    def test_random_seed_calls_random_seed(self, gui_source):
        body = _extract_method_body(gui_source, '_shortcut_random_seed')
        assert '_random_seed' in body, (
            'Random-seed shortcut should delegate to _random_seed (the '
            'existing method backing the 🎲 button).')


# ---------------------------------------------------------------------
# Cheatsheet modal
# ---------------------------------------------------------------------

class TestCheatsheetModal:
    def test_modal_uses_toplevel(self, gui_source):
        """The cheatsheet is a modal dialog, not a hijack of the main
        window. Toplevel + grab_set is the standard pattern."""
        body = _extract_method_body(gui_source, '_show_shortcuts_cheatsheet')
        assert 'Toplevel(' in body, (
            'Cheatsheet should be a Toplevel modal, not draw into '
            'the main window.')

    def test_modal_renders_from_table(self, gui_source):
        """The modal must iterate KEYBOARD_SHORTCUTS to render its
        rows — otherwise the cheatsheet and the bindings can drift
        out of sync (adding a shortcut wouldn't update the modal)."""
        body = _extract_method_body(gui_source, '_show_shortcuts_cheatsheet')
        assert 'KEYBOARD_SHORTCUTS' in body, (
            'Cheatsheet must build its rows from KEYBOARD_SHORTCUTS so '
            'adding/removing shortcuts updates the modal automatically.')

    def test_modal_escape_closes(self, gui_source):
        """Esc is the universal "close this modal" convention. Without
        a binding, the user has to mouse over to the Close button."""
        body = _extract_method_body(gui_source, '_show_shortcuts_cheatsheet')
        assert '<Escape>' in body, (
            'Cheatsheet modal should bind <Escape> to close — standard '
            'modal convention.')


# ---------------------------------------------------------------------
# Wire-up
# ---------------------------------------------------------------------

class TestBindingWireup:
    def test_bind_method_exists(self, gui_source):
        assert 'def _bind_keyboard_shortcuts(self):' in gui_source

    def _rando_gui_init_body(self, gui_source):
        """RandoGUI's __init__ starts with `(self, root` — other
        classes in the file take different signatures, so this prefix
        is unique. Tolerates extra parameters after `root` (e.g. the
        v0.26.x progress_callback)."""
        marker = 'def __init__(self, root'
        # First match inside class RandoGUI body
        class_start = gui_source.find('class RandoGUI')
        assert class_start != -1, 'RandoGUI class not found'
        start = gui_source.find(marker, class_start)
        assert start != -1, 'RandoGUI __init__ not found'
        # Look for the next class-level def (4-space indent) as the
        # end marker.
        end = gui_source.find('\n    def ', start + 1)
        return gui_source[start:end if end != -1 else start + 50000]

    def test_bind_method_called_from_init(self, gui_source):
        """The bind method must be called in __init__, otherwise the
        shortcuts never wire up."""
        init_body = self._rando_gui_init_body(gui_source)
        assert '_bind_keyboard_shortcuts(' in init_body, (
            '_bind_keyboard_shortcuts must be called from __init__ — '
            'otherwise none of the shortcuts ever get bound.')

    def test_bind_after_build_ui(self, gui_source):
        """The binding call must come AFTER _build_ui — the target
        widgets (run_btn, launch_btn) don't exist before that."""
        init_body = self._rando_gui_init_body(gui_source)
        build_idx = init_body.find('_build_ui(')
        bind_idx = init_body.find('_bind_keyboard_shortcuts(')
        assert build_idx != -1 and bind_idx != -1, (
            f'Expected both _build_ui and _bind_keyboard_shortcuts '
            f'in __init__; found build={build_idx}, bind={bind_idx}')
        assert build_idx < bind_idx, (
            '_bind_keyboard_shortcuts must be called AFTER _build_ui — '
            'the binding handlers reference run_btn / launch_btn which '
            'don\'t exist until _build_ui completes.')

    def test_bindings_go_on_root(self, gui_source):
        """The bind() calls must target self.root (not a specific
        widget) so the shortcuts fire from anywhere in the window
        regardless of which widget has focus."""
        body = _extract_method_body(gui_source, '_bind_keyboard_shortcuts')
        assert 'self.root.bind(' in body, (
            'Shortcut bindings should go on self.root — binding to a '
            'specific widget would make the shortcut only work when '
            'that widget has focus.')


# ---------------------------------------------------------------------
# Discoverability — surface the F1 hint somewhere visible
# ---------------------------------------------------------------------

class TestShortcutDiscoverability:
    def test_status_bar_mentions_f1(self, gui_source):
        """F1 should be discoverable — a hint label in the status bar
        is the least intrusive way (out of the user's main work area
        but visible)."""
        # Look for "F1" appearing in a Label near the status bar area
        # in _build_ui or close to it. The label text just needs to
        # contain "F1" — exact wording can vary.
        # Skip the F1 binding sequence string itself.
        assert re.search(r'text="[^"]*F1[^"]*shortcuts?', gui_source) or \
               re.search(r'text="[^"]*shortcuts?[^"]*F1', gui_source), (
            'Add a "F1 for shortcuts" (or similar) hint in the status '
            'bar so the cheatsheet is discoverable.')

    def test_run_button_tooltip_mentions_shortcut(self, gui_source):
        """The Randomize button is the most-used action — its tooltip
        should mention the shortcut so power users learn it organically."""
        # Find the Tooltip() call attached to run_btn
        run_btn_idx = gui_source.find('self.run_btn = ttk.Button(')
        assert run_btn_idx != -1
        # The tooltip should appear in the next ~500 chars
        snippet = gui_source[run_btn_idx:run_btn_idx + 600]
        assert 'Ctrl+R' in snippet or 'F5' in snippet, (
            'Run button tooltip should mention Ctrl+R or F5 so power '
            'users discover the shortcut from the most natural place.')
