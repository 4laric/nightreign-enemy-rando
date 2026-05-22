"""Tests for the run-mode combobox stickiness guards (v0.26.x).

The run-mode Combobox switches between Standard and the destructive
Oops! All diagnostic modes. A readonly ttk.Combobox changes selection
on mouse-wheel scroll and on arrow keys whenever it has focus, so a
stray scroll while reading the window would silently flip a run into
Oops! All mode (every slot replaced with one enemy).

Two guards were added:
  1. Mouse-wheel events on the combobox are eaten (bind returns
     'break') so scrolling doesn't change the selection.
  2. _on_mode_change prompts for confirmation when switching INTO an
     Oops mode, and reverts to the last confirmed mode on cancel.

These are AST/source-level checks — consistent with the other GUI
structure tests, no Tk instantiation needed.
"""
import ast
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_PATH = os.path.join(REPO_ROOT, 'oops_rando_gui.py')


def _gui_source():
    with open(GUI_PATH, encoding='utf-8') as f:
        return f.read()


def _on_mode_change_body():
    """Return the source text of RandoGUI._on_mode_change."""
    src = _gui_source()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_on_mode_change':
            return ast.get_source_segment(src, node)
    return None


def test_mousewheel_eaten_on_mode_combo():
    """The mode combobox must bind MouseWheel / Button-4 / Button-5 so
    scroll events don't flip the selection."""
    src = _gui_source()
    # All three scroll bindings should be present near the mode combo
    assert "'<MouseWheel>'" in src, "mode combo missing <MouseWheel> bind"
    assert "'<Button-4>'" in src, "mode combo missing <Button-4> bind (Linux scroll)"
    assert "'<Button-5>'" in src, "mode combo missing <Button-5> bind (Linux scroll)"


def test_mode_change_has_confirmation():
    """_on_mode_change must prompt for confirmation before entering an
    Oops mode."""
    body = _on_mode_change_body()
    assert body is not None, "_on_mode_change not found"
    assert 'askyesno' in body, (
        "_on_mode_change must call messagebox.askyesno to confirm "
        "switching into an Oops mode")
    assert 'startswith("Oops")' in body or "startswith('Oops')" in body, (
        "_on_mode_change must gate the confirmation on Oops modes")


def test_mode_change_reverts_on_cancel():
    """If the user cancels the confirmation, the mode must revert to the
    last confirmed value via run_mode_var.set()."""
    body = _on_mode_change_body()
    assert '_last_confirmed_mode' in body, (
        "_on_mode_change must track _last_confirmed_mode")
    assert 'run_mode_var.set(self._last_confirmed_mode)' in body, (
        "_on_mode_change must revert run_mode_var to _last_confirmed_mode "
        "when the user cancels the Oops-mode confirmation")


def test_last_confirmed_mode_initialized_early():
    """_last_confirmed_mode must be set when run_mode_var is created, not
    only in _build_ui — otherwise the startup _on_mode_change() call
    spuriously prompts for a restored Oops! All setting."""
    src = _gui_source()
    tree = ast.parse(src)
    # Find the RandoGUI.__init__ and confirm _last_confirmed_mode is
    # assigned in it (before _build_ui, which is also called in __init__).
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'RandoGUI':
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                    init_src = ast.get_source_segment(src, item)
                    assert '_last_confirmed_mode' in init_src, (
                        '_last_confirmed_mode must be initialized in '
                        'RandoGUI.__init__ (alongside run_mode_var) so the '
                        'startup _on_mode_change() does not spuriously '
                        'prompt')
                    # And it should appear before the _build_ui() call
                    idx_set = init_src.find('_last_confirmed_mode')
                    idx_build = init_src.find('_build_ui()')
                    assert idx_build == -1 or idx_set < idx_build, (
                        '_last_confirmed_mode must be set BEFORE _build_ui() '
                        'is called in __init__')
                    return
    raise AssertionError('RandoGUI.__init__ not found')
