"""Regression tests for the v0.26.4 missing-method hotfix.

The v0.26.2/v0.26.3 builds shipped with `self._hide_post_run_summary()`
called from RandoGUI._run_shuffle but no method definition anywhere.
Every Randomize click on Windows hit AttributeError; on dev (Linux)
the bug went unnoticed because the post-run summary code path is the
SAME on both platforms — Alaric just never hit Randomize in dev after
the call site was added. This is exactly the class of mistake that
AST-walk-tests are cheap insurance against.

These tests walk the AST of the shipped GUI file, collect every
self.<name>() call that looks method-like (starts with verb-y prefix
like _show_/_hide_/_on_/_render_/etc.), and assert every one has a
corresponding `def <name>` in the same class.
"""
import ast
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Method-name prefixes that are unambiguously methods (not attributes).
# Generic prefixes like _ alone match too many false positives so we
# restrict to verb-y prefixes that always denote method/action names.
METHOD_PREFIXES = (
    '_render_', '_build_', '_show_', '_hide_',
    '_on_', '_run_', '_open_', '_browse_',
    '_validate_', '_load_', '_save_', '_apply_',
    '_clear_', '_refresh_', '_update_', '_handle_',
    '_compute_', '_set_', '_get_', '_log',
    '_drain_', '_finish_', '_cancel_', '_check_',
    '_dispatch_', '_format_', '_export_', '_import_',
    '_install_', '_copy_', '_persist_',
)


def find_class(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def collect_self_method_calls(class_node):
    """Walk class body, return {method_name: [linenos]} for every
    self.<name>() invocation where <name> matches METHOD_PREFIXES."""
    calls = {}
    for node in ast.walk(class_node):
        # We want Call nodes whose function is an Attribute on self
        if not isinstance(node, ast.Call): continue
        func = node.func
        if not isinstance(func, ast.Attribute): continue
        if not (isinstance(func.value, ast.Name) and func.value.id == 'self'):
            continue
        name = func.attr
        if not name.startswith(METHOD_PREFIXES): continue
        calls.setdefault(name, []).append(func.lineno)
    return calls


def collect_method_defs(class_node):
    """Return set of names defined as methods (sync or async) in the
    class body. Includes nested class methods, which is a wider net than
    we strictly need but doesn't cause false negatives."""
    defined = set()
    for node in ast.walk(class_node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
    return defined


@pytest.mark.parametrize('class_name', ['RandoGUI', 'FirstLaunchWizard'])
def test_class_has_no_missing_method_calls(class_name):
    """Every self.<method>() call in the class must have a corresponding
    `def <method>` in the same class. Otherwise it's a typo or a method
    that got renamed/deleted without the call site being updated.

    The v0.26.2 bug was _hide_post_run_summary() called but never
    defined. This test would have caught it at suite time."""
    gui_path = os.path.join(REPO_ROOT, 'oops_rando_gui.py')
    with open(gui_path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    cls = find_class(tree, class_name)
    assert cls is not None, f"Class {class_name} not found in GUI"

    called = collect_self_method_calls(cls)
    defined = collect_method_defs(cls)

    missing = {name: lines for name, lines in called.items()
               if name not in defined}

    assert not missing, (
        f"{class_name}: {len(missing)} self.<method>() call(s) have no "
        f"matching `def` in the class. Either rename / restore the method "
        f"or remove the call site. Each will raise AttributeError when "
        f"the corresponding code path runs:\n  " +
        "\n  ".join(f"self.{name}() called at line(s) {lines[:3]}"
                    for name, lines in missing.items()))


def test_hide_post_run_summary_is_defined():
    """Targeted regression test for the specific bug. Belt-and-braces
    on top of the generic test above — explicitly named so a future
    failure tells you exactly which historical bug came back."""
    gui_path = os.path.join(REPO_ROOT, 'oops_rando_gui.py')
    with open(gui_path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    cls = find_class(tree, 'RandoGUI')
    defined = collect_method_defs(cls)
    assert '_hide_post_run_summary' in defined, (
        "RandoGUI._hide_post_run_summary is missing. The v0.26.2 build "
        "shipped with this method called from _run_shuffle but never "
        "defined, causing AttributeError on every Randomize click.")
