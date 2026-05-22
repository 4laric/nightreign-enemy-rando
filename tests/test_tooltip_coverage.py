"""
test_tooltip_coverage.py — locks in the Tier 2 UX #9 tooltip sweep.

Each interactive control on the main flow that the user might hover over
"to find out what this does" must have a Tooltip attached. Without these,
controls like the Seed entry, Mode combobox, or Multiplayer-safe checkbox
require the user to either know what they do already or guess.

These tests use source inspection — they look for the construction pattern
of each control and confirm a Tooltip(...) call lives within a sensible
window after it. Lenient by design: the window is wide enough that
restructuring nearby code won't spuriously fail, but tight enough that
removing a tooltip will.
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


def _has_tooltip_near(src, anchor_text, window=600):
    """Return True if a `Tooltip(` call appears within `window` chars
    after the first occurrence of `anchor_text`. Anchor text picks the
    nearest construction site; the window is generous because Tk
    construction often spans multiple lines (Combobox / Entry have
    several kwargs, then .pack() on its own line, then the Tooltip).

    Returns (found, snippet) so test failures can show what was checked.
    """
    idx = src.find(anchor_text)
    if idx == -1:
        return False, f'(anchor text not found: {anchor_text!r})'
    snippet = src[idx:idx + window]
    return ('Tooltip(' in snippet), snippet


# ---------------------------------------------------------------------
# Main tab — core controls
# ---------------------------------------------------------------------

class TestMainTabCoreTooltips:
    """The Seed / Random / Mode / Oops! All combo bar at the top of the
    Generate tab — these are the first controls a new user touches."""

    def test_seed_entry(self, gui_source):
        # The Seed entry construction pattern is distinct enough to anchor on
        found, _ = _has_tooltip_near(
            gui_source,
            'ttk.Entry(row, textvariable=self.seed_var',
            window=500)
        assert found, ('Seed Entry has no Tooltip — first-time users '
                       'won\'t know if seeds are deterministic.')

    def test_random_seed_button(self, gui_source):
        found, _ = _has_tooltip_near(
            gui_source,
            '"🎲 Random"',
            window=400)
        assert found, ('🎲 Random button has no Tooltip — users may '
                       'expect it to run the rando rather than just '
                       'set a new seed.')

    def test_mode_combobox(self, gui_source):
        found, _ = _has_tooltip_near(
            gui_source,
            'mode_combo = ttk.Combobox(',
            window=900)
        assert found, ('Mode combobox has no Tooltip — the 4 mode '
                       'options need explanation (Standard / Oops! All / '
                       'Oops! All NB / Validation).')

    def test_oops_all_target_combo(self, gui_source):
        found, _ = _has_tooltip_near(
            gui_source,
            'self.oops_all_combo = AutocompleteCombobox(',
            window=700)
        assert found, ('Oops! All target picker has no Tooltip — '
                       'users won\'t know about the c-prefix-then-name '
                       'format or the tier-fallback behavior.')

    def test_oops_all_nb_target_combo(self, gui_source):
        found, _ = _has_tooltip_near(
            gui_source,
            'self.oops_all_nb_combo = AutocompleteCombobox(',
            window=700)
        assert found, 'Oops! All NB target picker has no Tooltip'

    def test_oops_all_nb_scope_combo(self, gui_source):
        found, _ = _has_tooltip_near(
            gui_source,
            'self.oops_all_nb_scope_combo = ttk.Combobox(',
            window=700)
        assert found, ('Oops! All NB scope picker has no Tooltip — '
                       'the strict/broad/extended distinction is the '
                       'main thing users need to understand here.')


# ---------------------------------------------------------------------
# Heritage tab — checkboxes mirrored from existing info icons
# ---------------------------------------------------------------------

class TestHeritageTabTooltips:
    """The Heritage tab's checkboxes previously only had info-icon
    hover help next to them (small ⓘ icon in a label widget). v0.26.x
    added direct Tooltips on the checkboxes themselves for discovery —
    users shouldn't have to find a 12px icon to learn what an option
    does. Both layers are kept: info icon for the full detail, direct
    tooltip for the one-paragraph summary."""

    def test_multiplayer_safe_checkbox(self, gui_source):
        # Anchor on the unique text the checkbox carries
        found, _ = _has_tooltip_near(
            gui_source,
            '"Multiplayer-safe (skip heritage chrs)"',
            window=600)
        assert found, ('Multiplayer-safe checkbox needs a direct '
                       'Tooltip — explaining the coop-desync risk on '
                       'hover is high-leverage since it\'s the default '
                       'ON for safety reasons.')

    def test_mmv_checkbox(self, gui_source):
        found, _ = _has_tooltip_near(
            gui_source,
            '"Enable MMV cross-game boss imports"',
            window=600)
        assert found, ('MMV checkbox needs a direct Tooltip — the '
                       'CTD-on-cell-load risk if MMV isn\'t installed '
                       'must be hover-discoverable.')

    def test_diagnostic_resilient_filter_checkbox(self, gui_source):
        """The 'disable_resilient_filter' diagnostic mode — users
        outside of engine validation should be warned this isn't a
        normal-play setting."""
        found, _ = _has_tooltip_near(
            gui_source,
            '"Diagnostic: untested targets at fragile slots',
            window=700)
        assert found, ('Diagnostic-mode checkbox needs a direct '
                       'Tooltip — users may toggle this without '
                       'realizing it\'s an engine-validation mode.')

    def test_test_mode_arenas_checkbox(self, gui_source):
        found, _ = _has_tooltip_near(
            gui_source,
            '"Test-mode arenas: overlay MMV-style minimal EMEVDs',
            window=700)
        assert found, ('Test-mode arenas checkbox needs a direct '
                       'Tooltip — without one, users may enable it for '
                       'normal play and lose all the cinematic arena '
                       'choreography.')

    def test_diagnostic_batch_entry(self, gui_source):
        """The batch-targets Entry (CTD attribution tool) — the input
        format isn't self-evident."""
        # The Entry construction (line that wires the textvariable) is
        # the right anchor. The BooleanVar declaration in __init__ is
        # far away and would put us in the wrong window.
        found, _ = _has_tooltip_near(
            gui_source,
            'textvariable=self.diagnostic_test_targets_var',
            window=600)
        assert found, ('Batch-targets Entry needs a Tooltip explaining '
                       'the comma-separated c-prefix format.')


# ---------------------------------------------------------------------
# ER Assets tab — Overwrite checkbox
# ---------------------------------------------------------------------

class TestErAssetsTabTooltips:
    def test_overwrite_existing_checkbox(self, gui_source):
        """Overwrite default is OFF (skips already-imported files).
        Users with manually-customized chrs need to know this — and
        users who want a clean re-import need to know flipping it
        does that."""
        found, _ = _has_tooltip_near(
            gui_source,
            '"Overwrite existing files"',
            window=400)
        assert found, ('Overwrite existing files checkbox needs a '
                       'Tooltip — the default OFF behaviour (skipping '
                       'existing files) is non-obvious.')


# ---------------------------------------------------------------------
# Tooltip count sanity check
# ---------------------------------------------------------------------

class TestOverallTooltipCoverage:
    def test_tooltip_count_at_least_baseline(self, gui_source):
        """Locks in a minimum number of tooltips across the GUI. If
        someone later removes tooltips, this catches the regression.
        Baseline of 20 was chosen after the v0.26.x sweep which
        brought the count to 26 (14 direct Tooltip + 12 info-icon),
        leaving headroom for minor renames / restructures."""
        # Count Tooltip( and make_info_icon( instances
        tooltip_count = len(re.findall(r'\bTooltip\(', gui_source))
        info_icon_count = len(re.findall(r'\bmake_info_icon\(', gui_source))
        total = tooltip_count + info_icon_count
        assert total >= 20, (
            f'Total hover-help wires (Tooltip + make_info_icon) is {total}, '
            f'below the v0.26.x baseline of 20. Did a tooltip sweep '
            f'get reverted, or were controls removed without removing '
            f'their wires?')
