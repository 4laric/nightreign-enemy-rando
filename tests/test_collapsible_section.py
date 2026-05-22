"""
test_collapsible_section.py — tests for the Tier 2 UX #8 collapsible-
section widget and its application to the Heritage tab's diagnostic
controls.

Two layers:
  1. Source-inspection of the CollapsibleSection class (structure,
     glyphs, toggle behavior, default-collapsed state).
  2. Source-inspection of the Heritage tab integration — the diagnostic
     LabelFrame must live inside the section's body, not as a direct
     child of the tab frame.
"""
import os
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


# ---------------------------------------------------------------------
# CollapsibleSection — class structure
# ---------------------------------------------------------------------

class TestCollapsibleSectionClass:
    def test_class_defined(self, gui_source):
        assert 'class CollapsibleSection:' in gui_source

    def test_has_collapsed_and_expanded_glyphs(self, gui_source):
        """Two distinct glyphs differentiate state. ▶ is the canonical
        'click to expand' affordance; ▼ indicates 'click to collapse'."""
        # Find the class body
        class_start = gui_source.find('class CollapsibleSection:')
        class_end = gui_source.find('\ndef validate_path_kind(', class_start)
        body = gui_source[class_start:class_end]
        assert 'GLYPH_EXPANDED' in body, (
            'CollapsibleSection should define explicit GLYPH_EXPANDED / '
            'GLYPH_COLLAPSED class attributes so the visual is consistent.')
        assert 'GLYPH_COLLAPSED' in body
        assert '▼' in body and '▶' in body, (
            'CollapsibleSection should use ▼/▶ glyphs — the standard '
            'collapsible-section affordance recognised across IDEs / docs.')

    def test_default_state_collapsed(self, gui_source):
        """The constructor signature must default expanded=False. The
        primary use case (hiding advanced/diagnostic toggles) requires
        starting collapsed; an expanded=True default would defeat the
        purpose of the widget."""
        class_start = gui_source.find('class CollapsibleSection:')
        # Find __init__ line
        init_idx = gui_source.find('def __init__(self', class_start)
        init_sig_end = gui_source.find(')', init_idx)
        sig = gui_source[init_idx:init_sig_end + 1]
        assert 'expanded=False' in sig, (
            'CollapsibleSection.__init__ must default to expanded=False '
            'so callers get hidden-by-default behaviour without ceremony.')

    def test_toggle_method_exists(self, gui_source):
        class_start = gui_source.find('class CollapsibleSection:')
        class_end = gui_source.find('\ndef validate_path_kind(', class_start)
        body = gui_source[class_start:class_end]
        assert 'def _toggle(self' in body, (
            'CollapsibleSection needs a _toggle method bound to the '
            'header click. Without it the section never collapses/expands.')

    def test_header_click_bindings(self, gui_source):
        """Both the arrow AND the title text must be clickable so users
        with a small target can hit either. cursor='hand2' tells them
        these are interactive."""
        class_start = gui_source.find('class CollapsibleSection:')
        class_end = gui_source.find('\ndef validate_path_kind(', class_start)
        body = gui_source[class_start:class_end]
        # Two bind calls — one for arrow, one for title
        bind_count = body.count("bind('<Button-1>'")
        assert bind_count >= 2, (
            f'Both arrow and title should be clickable to toggle. Found '
            f'only {bind_count} Button-1 binds in CollapsibleSection.')
        assert "cursor='hand2'" in body, (
            "Header widgets should use cursor='hand2' to signal "
            "interactivity.")

    def test_pack_and_grid_passthrough(self, gui_source):
        """The widget should accept .pack() and .grid() calls so it
        composes naturally with existing layouts."""
        class_start = gui_source.find('class CollapsibleSection:')
        class_end = gui_source.find('\ndef validate_path_kind(', class_start)
        body = gui_source[class_start:class_end]
        assert 'def pack(self' in body
        assert 'def grid(self' in body

    def test_body_attribute_exposed(self, gui_source):
        """Callers add child widgets to .body — that attribute is the
        public contract of the section."""
        class_start = gui_source.find('class CollapsibleSection:')
        class_end = gui_source.find('\ndef validate_path_kind(', class_start)
        body = gui_source[class_start:class_end]
        assert 'self.body = ttk.Frame(' in body, (
            'CollapsibleSection must expose a `body` Frame attribute '
            'as the place for caller-supplied content.')


# ---------------------------------------------------------------------
# Heritage tab integration — diagnostic section uses the expander
# ---------------------------------------------------------------------

class TestHeritageDiagnosticExpander:
    def test_diagnostic_section_uses_collapsible(self, gui_source):
        """The Heritage tab's diagnostic block must be wrapped in a
        CollapsibleSection. Otherwise the engine-validation toggles
        are visible by default and clutter the first-launch surface."""
        # Find the Heritage tab build
        ht_start = gui_source.find('def _build_heritage_safety_subtab(')
        if ht_start == -1:
            ht_start = gui_source.find('def _build_heritage_tab(')
        # Or wherever the diagnostic frame is constructed
        assert ht_start != -1, '_build_heritage_tab method missing'
        # Look at the heritage tab body for the CollapsibleSection wire
        ht_end = gui_source.find('\n    def ', ht_start + 1)
        if ht_end == -1:
            ht_end = len(gui_source)
        body = gui_source[ht_start:ht_end]
        # The collapsible may live in a subtab method — check both
        all_heritage_source = gui_source[ht_start:
            gui_source.find('def _build_chr_inventory_tab(', ht_start)]
        assert 'CollapsibleSection(' in all_heritage_source, (
            'Heritage tab must construct a CollapsibleSection for the '
            'diagnostic section. Without it, the diagnostic toggles '
            'remain visible by default.')

    def test_diagnostic_section_collapsed_by_default(self, gui_source):
        """The Heritage tab's CollapsibleSection constructor call must
        either omit `expanded=` (defaults to False) or explicitly pass
        expanded=False. Passing expanded=True defeats the purpose."""
        # Find any CollapsibleSection construction in heritage tab area
        ht_start = gui_source.find('def _build_heritage_tab(')
        ht_end = gui_source.find('def _build_chr_inventory_tab(', ht_start)
        ht_source = gui_source[ht_start:ht_end]
        section_idx = ht_source.find('CollapsibleSection(')
        assert section_idx != -1
        # Look ahead until the closing paren of this constructor call
        depth = 0
        for i, c in enumerate(ht_source[section_idx:]):
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    call = ht_source[section_idx:section_idx + i + 1]
                    break
        else:
            pytest.fail("CollapsibleSection constructor call not closed")
        # If `expanded=` appears in the call, it must be False
        if 'expanded=' in call:
            assert 'expanded=False' in call, (
                'Heritage tab CollapsibleSection must default-collapsed '
                '(omit expanded= or pass expanded=False).')

    def test_diagnostic_label_indicates_advanced(self, gui_source):
        """The section header should make it visually clear that the
        contents are advanced / not for normal play."""
        ht_start = gui_source.find('def _build_heritage_tab(')
        ht_end = gui_source.find('def _build_chr_inventory_tab(', ht_start)
        ht_source = gui_source[ht_start:ht_end]
        section_idx = ht_source.find('CollapsibleSection(')
        # Window after the constructor — look for the label string
        snippet = ht_source[section_idx:section_idx + 300]
        # The label should mention "diagnostic", "advanced", or "engine"
        # to signal "this isn't normal play"
        lowered = snippet.lower()
        assert any(word in lowered
                   for word in ('diagnostic', 'advanced', 'engine')), (
            'CollapsibleSection label should signal advanced content — '
            "users shouldn't have to expand to find out it's diagnostic.")

    def test_diag_frame_lives_in_section_body(self, gui_source):
        """The diag_frame LabelFrame's parent must be the section's
        .body, not the tab's frame `f`. Otherwise wrapping is moot."""
        ht_start = gui_source.find('def _build_heritage_tab(')
        ht_end = gui_source.find('def _build_chr_inventory_tab(', ht_start)
        ht_source = gui_source[ht_start:ht_end]
        # Find the diag_frame construction
        diag_idx = ht_source.find('diag_frame = ttk.LabelFrame(')
        assert diag_idx != -1, 'diag_frame not found in heritage tab'
        # The parent argument should reference _diagnostic_section.body
        # (or similar). Look at first ~200 chars of the constructor
        diag_call = ht_source[diag_idx:diag_idx + 300]
        assert '_diagnostic_section.body' in diag_call \
            or 'section.body' in diag_call.lower(), (
            'diag_frame must be parented to the CollapsibleSection\'s '
            ".body, not the tab's outer frame `f`. Otherwise it stays "
            "always-visible and the wrapping has no effect.")


# ---------------------------------------------------------------------
# Heritage tab — Vanilla mapstudio expander (v0.26.x, Tier 2 UX #8)
# ---------------------------------------------------------------------

class TestVanillaMapstudioExpander:
    """The Vanilla mapstudio (spawn pool) override is advanced/optional
    — most users skip it. Collapsing it by default lets the Heritage
    tab show MMV + multiplayer-safe (the actual normal-play options)
    without three unfamiliar sections crowding the page."""

    def test_section_uses_collapsible(self, gui_source):
        """The vanilla mapstudio (spawn pool) override must be wrapped
        in CollapsibleSection — otherwise its Entry + Browse row is
        visible to first-time users alongside the diagnostic and MMV
        sections, defeating the de-noise goal."""
        ht_start = gui_source.find('def _build_heritage_tab(')
        ht_end = gui_source.find('def _build_chr_inventory_tab(', ht_start)
        ht_source = gui_source[ht_start:ht_end]
        # Look specifically near the spawn_pool_source_dir_var Entry —
        # that's the row that should now live inside a collapsible.
        sp_var_idx = ht_source.find('spawn_pool_source_dir_var')
        assert sp_var_idx != -1, (
            'spawn_pool_source_dir_var usage not found on Heritage tab')
        # Walk back from there to find the enclosing section construction
        back_window = ht_source[max(0, sp_var_idx - 800):sp_var_idx]
        assert 'CollapsibleSection(' in back_window, (
            'The spawn_pool_source_dir_var Entry must be packed inside '
            'a CollapsibleSection.body — currently it lives in a bare '
            'LabelFrame, visible to all users.')

    def test_section_collapsed_by_default(self, gui_source):
        """Same default-collapsed rule as the Diagnostic section: if
        the section gets expanded=True we lose the de-noise benefit."""
        ht_start = gui_source.find('def _build_heritage_tab(')
        ht_end = gui_source.find('def _build_chr_inventory_tab(', ht_start)
        ht_source = gui_source[ht_start:ht_end]
        # Find ALL CollapsibleSection construction calls in the heritage tab
        # and verify none of them go expanded=True
        idx = 0
        constructions = []
        while True:
            idx = ht_source.find('CollapsibleSection(', idx)
            if idx == -1:
                break
            # Capture until balanced parens close
            depth = 0
            for i, c in enumerate(ht_source[idx:]):
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0:
                        constructions.append(ht_source[idx:idx + i + 1])
                        idx = idx + i + 1
                        break
            else:
                break
        assert constructions, (
            'No CollapsibleSection constructions found on heritage tab')
        for call in constructions:
            if 'expanded=' in call:
                assert 'expanded=False' in call, (
                    f'CollapsibleSection construction defaults to expanded — '
                    f'should be expanded=False:\n  {call[:200]}')

    def test_section_label_marks_optional_or_advanced(self, gui_source):
        """The header text should signal that this is advanced/optional —
        same UX cue as the Diagnostic section."""
        ht_start = gui_source.find('def _build_heritage_tab(')
        ht_end = gui_source.find('def _build_chr_inventory_tab(', ht_start)
        ht_source = gui_source[ht_start:ht_end]
        # Find the Vanilla mapstudio CollapsibleSection
        sp_idx = ht_source.find('_vanilla_mapstudio_section')
        if sp_idx == -1:
            # Allow alternate attribute name; just check the label string
            # near spawn_pool_source_dir_var contains "Vanilla mapstudio"
            sp_idx = ht_source.find('spawn_pool_source_dir_var')
        assert sp_idx != -1
        # Look in the surrounding ~600 chars for the section label text
        window = ht_source[max(0, sp_idx - 600):sp_idx + 400]
        # Should mention "optional", "advanced", or similar marker
        lowered = window.lower()
        assert ('optional' in lowered or 'advanced' in lowered), (
            'Vanilla mapstudio section label should indicate the '
            'content is advanced/optional so users know they can skip it.')


class TestExpanderRegression:
    """Lock in that we don't accidentally remove ANY of the heritage-tab
    collapsibles in a future refactor. The Diagnostic + Vanilla
    mapstudio sections are both supposed to be collapsed by default,
    and both reduce front-page noise for new users."""

    def test_heritage_tab_has_at_least_two_collapsibles(self, gui_source):
        """The heritage tab currently hosts 2 collapsibles: Diagnostic
        and Vanilla mapstudio. If a future change drops below 2, the
        UX de-noise goal regresses."""
        ht_start = gui_source.find('def _build_heritage_tab(')
        ht_end = gui_source.find('def _build_chr_inventory_tab(', ht_start)
        ht_source = gui_source[ht_start:ht_end]
        n = ht_source.count('CollapsibleSection(')
        assert n >= 2, (
            f'Heritage tab has only {n} CollapsibleSection wires — '
            f'expected at least 2 (Diagnostic, Vanilla mapstudio). '
            f'Removing either undoes the de-noise UX goal.')
