"""
test_recommended_expedition.py — v0.26.x "use Tricephalos until Night
Boss EMEVDs are validated" guidance.

Surfaced in four places:
  1. Class attribute RECOMMENDED_EXPEDITION_* — single source of truth.
  2. Dismissable banner on the Generate tab (between compat banner +
     Seed/Mode frame).
  3. Tip line in the post-run summary panel (right before Launch).
  4. Section in the Generate tab help overlay + INSTALL.md.

All four channels respect:
  - The RECOMMENDED_EXPEDITION_ACTIVE flag — flipping to False kills
    every surface so the codebase isn't carrying stale guidance once
    the validation work completes.
  - The user's dismissal (persisted via _save_settings) — banner +
    post-run tip both check it; help overlay + INSTALL.md don't (those
    are opt-in / docs).
"""
import ast
import os
import re
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')
INSTALL_PATH = os.path.join(os.path.dirname(HERE), 'INSTALL.md')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope='module')
def install_source():
    with open(INSTALL_PATH, encoding="utf-8") as f:
        return f.read()


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


@pytest.fixture(scope='module')
def class_attrs(gui_source):
    """Parse RECOMMENDED_EXPEDITION_* attributes via AST."""
    tree = ast.parse(gui_source)
    attrs = {}
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == 'RandoGUI':
            for item in cls.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and \
                                target.id.startswith('RECOMMENDED_EXPEDITION'):
                            try:
                                attrs[target.id] = ast.literal_eval(item.value)
                            except (ValueError, SyntaxError):
                                # Non-literal (string concat) — skip
                                pass
            break
    return attrs


# ---------------------------------------------------------------------
# Class-level constants
# ---------------------------------------------------------------------

class TestClassConstants:
    """All four surfaces (banner, post-run tip, help overlay, INSTALL.md)
    should reference these constants instead of inlining strings. That
    way a single edit propagates everywhere when the recommendation
    changes."""

    def test_active_flag_exists(self, class_attrs):
        assert 'RECOMMENDED_EXPEDITION_ACTIVE' in class_attrs, (
            'RECOMMENDED_EXPEDITION_ACTIVE flag missing — needed so '
            'this guidance can be cleanly disabled once Night Boss '
            'EMEVDs are validated.')
        assert isinstance(class_attrs['RECOMMENDED_EXPEDITION_ACTIVE'], bool)

    def test_nightlord_name_set(self, class_attrs):
        nightlord = class_attrs.get('RECOMMENDED_EXPEDITION_NIGHTLORD')
        assert nightlord, (
            'RECOMMENDED_EXPEDITION_NIGHTLORD must be set to the '
            'recommended Nightlord name.')
        # Tricephalos is the current pick; lock it in until it changes.
        assert 'Tricephalos' in nightlord, (
            f'Expected Tricephalos as the recommended Nightlord '
            f'(unlocked on fresh save). Got: {nightlord!r}')

    def test_short_and_long_versions_exist(self, gui_source):
        """Two strings — short for inline tips, long for the banner
        body and help overlay. Locked in by attribute name presence."""
        assert 'RECOMMENDED_EXPEDITION_SHORT' in gui_source
        assert 'RECOMMENDED_EXPEDITION_LONG' in gui_source


# ---------------------------------------------------------------------
# Dismissal state
# ---------------------------------------------------------------------

class TestDismissalState:
    """A persistent BooleanVar lets power users hide the banner once
    they're aware of the guidance. Persistence via _save_settings means
    the dismissal survives restarts."""

    def test_dismissal_var_declared(self, gui_source):
        assert 'recommended_expedition_dismissed_var' in gui_source, (
            'No dismissal state var — banner can\'t be hidden, '
            'forever-noise for users who already know.')

    def test_dismissal_persists(self, gui_source):
        """The var should read from saved_settings on init AND have
        a trace_add hook to persist changes back. Tolerates the call
        being split across multiple lines for formatting."""
        # Find the var declaration block
        idx = gui_source.find('self.recommended_expedition_dismissed_var')
        assert idx != -1
        block = gui_source[idx:idx + 800]
        # The .get() call may span multiple lines — check both pieces
        assert 'saved_settings.get(' in block, (
            'Dismissal state must read from saved_settings — '
            'otherwise it resets every launch.')
        assert "'recommended_expedition_dismissed'" in block, (
            'Dismissal state load key must be '
            "'recommended_expedition_dismissed'.")
        assert 'trace_add' in block, (
            'Dismissal state must have a trace_add hook so changes '
            'persist immediately, not just on Run.')
        assert 'recommended_expedition_dismissed=' in block, (
            'trace_add hook should pass recommended_expedition_dismissed '
            'as the save key. Mismatch with the load key would silently '
            'orphan the persisted state.')


# ---------------------------------------------------------------------
# Banner widget
# ---------------------------------------------------------------------

class TestBannerWidget:
    def test_banner_method_exists(self, gui_source):
        assert 'def _refresh_recommended_expedition_banner(' in gui_source, (
            '_refresh_recommended_expedition_banner method missing.')

    def test_banner_host_frame_constructed(self, gui_source):
        """The host frame must be packed in _build_main_tab so the
        refresh method has somewhere to draw."""
        body = _extract_method_body(gui_source, '_build_main_tab')
        assert '_recommended_expedition_frame' in body, (
            'Banner host frame missing from _build_main_tab.')

    def test_banner_below_compat_banner(self, gui_source):
        """Visual hierarchy: setup status > compat banner > recommended
        expedition > seed/mode. Putting recommended expedition above
        compat banner would bury actual problems under aspirational
        guidance."""
        body = _extract_method_body(gui_source, '_build_main_tab')
        compat_idx = body.find('_compat_banner_frame')
        rec_idx = body.find('_recommended_expedition_frame')
        assert compat_idx != -1 and rec_idx != -1
        assert compat_idx < rec_idx, (
            'Compat banner should appear before recommended-expedition '
            'banner — real errors (missing assets) outrank gameplay '
            'guidance.')

    def test_banner_above_seed_mode(self, gui_source):
        """Banner needs to be visible before the user starts configuring
        — packing it BELOW the Seed/Mode frame buries it in the scrolled
        content."""
        body = _extract_method_body(gui_source, '_build_main_tab')
        rec_idx = body.find('_recommended_expedition_frame')
        seed_idx = body.find('Seed & Mode')
        assert rec_idx != -1 and seed_idx != -1
        assert rec_idx < seed_idx, (
            'Banner must appear ABOVE the Seed & Mode frame so it\'s '
            'visible without scrolling.')

    def test_banner_checks_active_flag(self, gui_source):
        """If RECOMMENDED_EXPEDITION_ACTIVE is False, the banner should
        be hidden — that's the clean kill switch for when validation
        completes."""
        body = _extract_method_body(
            gui_source, '_refresh_recommended_expedition_banner')
        assert 'RECOMMENDED_EXPEDITION_ACTIVE' in body, (
            'Banner refresh must check RECOMMENDED_EXPEDITION_ACTIVE — '
            'otherwise the kill switch is broken.')

    def test_banner_checks_dismissal(self, gui_source):
        body = _extract_method_body(
            gui_source, '_refresh_recommended_expedition_banner')
        assert 'recommended_expedition_dismissed_var' in body, (
            'Banner refresh must check the dismissal var — otherwise '
            'the dismiss button does nothing.')

    def test_banner_clears_previous_content(self, gui_source):
        """Re-rendering should not stack — clear children first."""
        body = _extract_method_body(
            gui_source, '_refresh_recommended_expedition_banner')
        assert ('destroy()' in body and 'winfo_children' in body), (
            'Banner refresh should clear previous content before '
            'rebuilding — otherwise re-renders accumulate widgets.')

    def test_banner_has_dismiss_button(self, gui_source):
        body = _extract_method_body(
            gui_source, '_refresh_recommended_expedition_banner')
        assert 'dismiss' in body.lower(), (
            'Banner must include a dismiss button.')

    def test_banner_references_nightlord_name(self, gui_source):
        """The banner should display the recommended Nightlord by
        name — locked in via the class attribute."""
        body = _extract_method_body(
            gui_source, '_refresh_recommended_expedition_banner')
        assert 'RECOMMENDED_EXPEDITION_NIGHTLORD' in body, (
            'Banner should reference the constant, not inline the '
            'Nightlord name. Otherwise changing the recommendation '
            'requires editing multiple places.')


class TestDismissHandler:
    def test_dismiss_method_exists(self, gui_source):
        assert 'def _dismiss_recommended_expedition_banner(' in gui_source

    def test_dismiss_sets_var(self, gui_source):
        body = _extract_method_body(
            gui_source, '_dismiss_recommended_expedition_banner')
        assert 'recommended_expedition_dismissed_var.set(True)' in body, (
            'Dismiss handler must set the dismissal var to True.')

    def test_dismiss_refreshes_banner(self, gui_source):
        """After dismissing, the banner should disappear immediately —
        the refresh method respects the new dismissed state."""
        body = _extract_method_body(
            gui_source, '_dismiss_recommended_expedition_banner')
        assert '_refresh_recommended_expedition_banner' in body, (
            'Dismiss handler should call the refresh method so the '
            'banner disappears immediately rather than waiting for '
            'the next event that triggers a refresh.')


# ---------------------------------------------------------------------
# Post-run summary integration
# ---------------------------------------------------------------------

class TestPostRunSummaryTip:
    """The Generate-tab banner shows the recommendation BEFORE the run.
    The post-run summary should show it RIGHT BEFORE LAUNCH — last
    chance to remind users to pick Tricephalos."""

    def test_summary_references_active_flag(self, gui_source):
        body = _extract_method_body(gui_source, '_render_run_summary')
        assert 'RECOMMENDED_EXPEDITION_ACTIVE' in body, (
            'Post-run summary should suppress the tip when '
            'RECOMMENDED_EXPEDITION_ACTIVE is False — same kill switch '
            'as the banner.')

    def test_summary_respects_dismissal(self, gui_source):
        body = _extract_method_body(gui_source, '_render_run_summary')
        assert 'recommended_expedition_dismissed_var' in body, (
            'Post-run summary tip should respect the same dismissal '
            'state as the banner — re-noticing dismissed guidance is '
            'noise.')

    def test_summary_uses_short_version(self, gui_source):
        """The post-run panel is space-constrained — should use the
        SHORT version of the recommendation, not the LONG."""
        body = _extract_method_body(gui_source, '_render_run_summary')
        assert 'RECOMMENDED_EXPEDITION_SHORT' in body, (
            'Post-run summary should use RECOMMENDED_EXPEDITION_SHORT '
            'for compactness — the LONG version is for the banner.')

    def test_summary_tip_before_launch_button(self, gui_source):
        """The tip should appear right BEFORE the Launch button — that's
        the natural reading order ('here's what happened → quick tip → 
        launch')."""
        body = _extract_method_body(gui_source, '_render_run_summary')
        tip_idx = body.find('RECOMMENDED_EXPEDITION_SHORT')
        launch_idx = body.find('Launch via ME3')
        assert tip_idx != -1 and launch_idx != -1
        assert tip_idx < launch_idx, (
            'Tip should appear before the Launch button in render '
            'order — otherwise it\'s visually below the call-to-action '
            'and gets missed.')


# ---------------------------------------------------------------------
# Help overlay + INSTALL.md
# ---------------------------------------------------------------------

class TestHelpOverlayContent:
    def test_generate_help_mentions_tricephalos(self, gui_source):
        """The Generate tab's help overlay (TAB_HELP_CONTENT['generate'])
        should include a section about the recommended expedition."""
        # Find the generate entry
        idx = gui_source.find("'generate':")
        assert idx != -1
        # The next ~5000 chars cover the entry
        window = gui_source[idx:idx + 5000]
        assert 'Tricephalos' in window, (
            'Generate help overlay should mention Tricephalos as the '
            'recommended expedition.')

    def test_generate_help_has_dedicated_section(self, gui_source):
        """An ALL-CAPS section header lets the section stand out
        in the styled help body."""
        idx = gui_source.find("'generate':")
        window = gui_source[idx:idx + 5000]
        assert 'RECOMMENDED EXPEDITION' in window, (
            'Help overlay should have a dedicated "RECOMMENDED '
            'EXPEDITION" section header — discoverable + styled as '
            'a section title in the modal.')


