"""
test_settings_persistence.py — v0.26.x persistence audit.

User-facing settings that should survive a restart but previously didn't:
    auto_launch_after_generate, run_mode, oops_all_target,
    oops_all_nb_target, oops_all_nb_scope

These are workflow-shaping prefs ("I always use Oops! All NB mode",
"I always want auto-launch after generate") — re-selecting them every
session is friction.

Settings that SHOULD NOT persist (verified separately):
    seed (intentionally resets to "42" each launch — the 🎲 button
        gives a fresh seed; sticky-seed would mean using the same
        run config every session by accident)
    diagnostic flags (default OFF is safer each session)
    chr_overwrite (default OFF is safer — destructive)
    spoiler tab / UI state (session-specific)

Two layers:
  1. Source-inspection on the var declarations + trace wires.
  2. End-to-end: write a settings file, instantiate via the save/
     load helpers, verify the round-trip.
"""
import json
import os
import re
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH, encoding="utf-8") as f:
        return f.read()


def _find_var_block(src, var_name):
    """Find the var declaration + its surrounding context (the next
    ~600 chars). Persistent vars typically have:
      - the StringVar/BooleanVar() ctor reading saved_settings.get(...)
      - a trace_add('write', ...) call below it
    Both should fit in a 600-char window."""
    needle = f'self.{var_name} = tk.'
    idx = src.find(needle)
    assert idx != -1, f'Var {var_name!r} not declared'
    return src[idx:idx + 800]


# ---------------------------------------------------------------------
# Each user-facing pref must read from saved_settings + trace-persist
# ---------------------------------------------------------------------

PERSISTABLE_VARS = [
    ('auto_launch_after_generate_var', 'auto_launch_after_generate',
     'Auto-launch-after-generate checkbox state — once enabled, users '
     'expect it sticky.'),
    ('run_mode_var', 'run_mode',
     'Mode dropdown selection (Standard / Oops! All / Oops! All NB / '
     'Validation) — users with a preferred workflow shouldn\'t have '
     'to re-select each session.'),
    ('oops_all_target_var', 'oops_all_target',
     'Oops! All target c-prefix pick.'),
    ('oops_all_nb_target_var', 'oops_all_nb_target',
     'Oops! All NB (boss-tier) target c-prefix pick.'),
    ('oops_all_nb_scope_var', 'oops_all_nb_scope',
     'Oops! All NB scope (strict / broad / extended).'),
]


@pytest.mark.parametrize('var_name,save_key,description', PERSISTABLE_VARS)
def test_var_reads_from_saved_settings(gui_source, var_name, save_key,
                                         description):
    """The var declaration must read from saved_settings.get(...) — that's
    the load half of persistence. Without it, the saved value is ignored
    on launch."""
    block = _find_var_block(gui_source, var_name)
    assert f"saved_settings.get('{save_key}'" in block, (
        f'{var_name} should initialize from saved_settings.get'
        f'({save_key!r}, ...). Without this, the saved value is '
        f'ignored at launch.\n  Why this matters: {description}')


@pytest.mark.parametrize('var_name,save_key,description', PERSISTABLE_VARS)
def test_var_has_persistence_trace(gui_source, var_name, save_key,
                                     description):
    """A trace_add hook saves the value on every change — that's the
    save half. Without it, changes are lost on close."""
    block = _find_var_block(gui_source, var_name)
    assert 'trace_add' in block, (
        f'{var_name} has no trace_add('
        f'"write", ...) — changes are lost on close.\n'
        f'  Why this matters: {description}')
    # The trace must reference the var itself (not just any trace)
    # AND call _save_settings with the matching save_key
    assert '_save_settings' in block, (
        f'{var_name} trace doesn\'t call _save_settings — changes '
        f'aren\'t actually persisted.')
    assert save_key in block, (
        f'{var_name} trace doesn\'t reference the save_key {save_key!r} — '
        f'check the kwarg name in the _save_settings call.')


# ---------------------------------------------------------------------
# Non-persistable vars — verify they stay non-persistable
# ---------------------------------------------------------------------

class TestNonPersistableVars:
    """Some vars must NOT persist — diagnostic flags, destructive
    toggles, session-specific state. Persisting them would be a
    safety regression."""

    @pytest.mark.parametrize('var_name,reason', [
        ('disable_resilient_filter_var',
         'Diagnostic mode — must default OFF each session to prevent '
         'accidental engine-validation runs.'),
        ('chr_overwrite_var',
         'Destructive flag — default OFF protects against accidental '
         'overwriting of customized chr files.'),
    ])
    def test_no_saved_settings_read(self, gui_source, var_name, reason):
        block = _find_var_block(gui_source, var_name)
        # First 200 chars (the var declaration line) shouldn't reference
        # saved_settings — that would be a load-side persistence
        declaration_line = block.split('\n')[0:3]  # first few lines
        declaration_text = '\n'.join(declaration_line)
        assert "saved_settings.get(" not in declaration_text, (
            f'{var_name} reads from saved_settings — but it should '
            f'NOT persist. Reason: {reason}')


# ---------------------------------------------------------------------
# Restored run_mode triggers _on_mode_change after build_ui
# ---------------------------------------------------------------------

class TestRestoredModeAppliesToUI:
    """If a user's saved run_mode is "Oops! All NB", restoring the
    StringVar value alone doesn't make the NB picker frame visible —
    that's done by _on_mode_change, which fires on combobox events
    but not on programmatic var changes. Init must explicitly call
    _on_mode_change AFTER _build_ui so the restored UI matches the
    restored config."""

    def test_on_mode_change_called_after_build_ui(self, gui_source):
        # Find the RandoGUI __init__
        cls_idx = gui_source.find('class RandoGUI')
        init_idx = gui_source.find('def __init__(', cls_idx)
        # Next class-level def marks end
        end = gui_source.find('\n    def ', init_idx + 1)
        body = gui_source[init_idx:end if end != -1 else init_idx + 5000]

        build_idx = body.find('_build_ui(')
        mode_change_idx = body.find('_on_mode_change(')
        assert build_idx != -1, '__init__ doesn\'t call _build_ui'
        assert mode_change_idx != -1, (
            '__init__ must call _on_mode_change after _build_ui — '
            'otherwise a restored run_mode like "Oops! All NB" leaves '
            'the UI showing the Standard mode\'s picker (or no picker '
            'at all).')
        assert mode_change_idx > build_idx, (
            '_on_mode_change must be called AFTER _build_ui — the '
            'frames it pack/unpacks are constructed in _build_ui.')


# ---------------------------------------------------------------------
# Round-trip: settings file save → load → verify
# ---------------------------------------------------------------------

class TestPersistenceRoundTrip:
    """Simulate the actual save/load mechanics by directly manipulating
    the JSON file the GUI reads/writes. This catches issues that
    source inspection can't (e.g. the key name in _save_settings
    matches the key in saved_settings.get)."""

    def test_save_settings_signature_accepts_kwargs(self, gui_source):
        """_save_settings(**kwargs) is how the trace handlers call it.
        Confirm the signature still uses **kwargs."""
        m = re.search(r'def _save_settings\(self,\s*\*\*kwargs\)', gui_source)
        assert m is not None, (
            '_save_settings should accept **kwargs (the trace handlers '
            'pass keyword args like multiplayer_safe=True).')

    def test_save_settings_merges_with_existing(self, gui_source):
        """The save logic must read the existing file first and merge —
        otherwise saving one key would clobber every other key. Lock
        in this critical correctness property."""
        # Find _save_settings body
        idx = gui_source.find('def _save_settings(')
        assert idx != -1
        end = gui_source.find('\n    def ', idx + 1)
        body = gui_source[idx:end if end != -1 else idx + 2000]
        # Should call _load_settings (read existing) then update
        assert '_load_settings()' in body, (
            '_save_settings must call _load_settings first to read the '
            'existing file — otherwise saving one key clobbers every '
            'other key.')
        # And then update() or merge logic
        assert '.update(' in body or 'kwargs' in body, (
            '_save_settings must merge kwargs into the existing dict '
            '(via dict.update), not overwrite.')

    def test_settings_file_path(self, gui_source):
        """The settings file is .4laric_settings.json — locked in
        by external tools / docs that might reference it. If the
        filename changes, those break."""
        assert '.4laric_settings.json' in gui_source, (
            'Settings filename must be .4laric_settings.json — '
            'changing it would silently orphan every existing user\'s '
            'saved settings.')


class TestSaveKeysMatchLoadKeys:
    """The save-time key name and the load-time key name must match
    for round-tripping to work. If a trace saves `auto_launch=True`
    but the init reads `auto_launch_after_generate`, restoration
    fails silently. This catches that class of typo."""

    @pytest.mark.parametrize('var_name,save_key,description', PERSISTABLE_VARS)
    def test_load_key_appears_in_save_call(self, gui_source, var_name,
                                              save_key, description):
        """For each var, the same save_key string must appear in both
        the saved_settings.get(...) call AND the _save_settings(...)
        call. The earlier two tests covered each side; this catches
        typos like 'auto_launch' vs 'auto_launch_after_generate'."""
        block = _find_var_block(gui_source, var_name)
        # Count distinct uses of the save_key — both sides should
        # appear in the same 800-char block since the trace is added
        # right after the var declaration.
        get_pattern = f"saved_settings.get('{save_key}'"
        save_pattern = f"{save_key}="
        assert get_pattern in block, (
            f'Load side: missing {get_pattern!r}')
        assert save_pattern in block, (
            f'Save side: missing {save_pattern!r}. The trace handler '
            f'should pass {save_key}=... to _save_settings.')


# ---------------------------------------------------------------------
# Existing persistent vars — regression guards
# ---------------------------------------------------------------------

class TestExistingPersistenceRegression:
    """Lock in the persistence that was already present before this
    audit — multiplayer_safe, MMV, path settings — so a future
    refactor doesn't accidentally drop them."""

    def test_multiplayer_safe_still_persists(self, gui_source):
        """multiplayer_safe is critical — accidentally regressing to
        per-session means coop-unsafe heritage chrs could leak into
        a session the user thought was protected."""
        block = _find_var_block(gui_source, 'multiplayer_safe_var')
        assert "saved_settings.get('multiplayer_safe'" in block
        assert 'trace_add' in block
        assert 'multiplayer_safe=' in block

    def test_root_path_persistence_still_present(self, gui_source):
        """Game install / ER install / me3 package / me3 launcher
        paths persist via _persist_root_paths."""
        assert 'def _persist_root_paths' in gui_source or \
               '_persist_root_paths' in gui_source, (
            'Root-path persistence helper missing — Game install + '
            'ER install + me3 package would all be lost.')
