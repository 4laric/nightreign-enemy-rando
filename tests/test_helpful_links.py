"""
test_helpful_links.py — v0.26.x external link surfacing.

The rando references several external tools/mods in tooltips and help
text (UXM, MMV, me3, etc.). Without clickable affordances or
direct URLs, users have to search for the right repo / Nexus page —
friction that's especially painful for first-time setup.

This test set locks in:
  1. The About tab has a Helpful Links section with all the
     externally-referenced tools.
  2. Each link uses a known-good canonical URL (locks in the
     post-deletion Nordgaren UXM URL, etc.).
  3. The broken "linked in the README" placeholder is gone — any
     reference to UXM in error messages now embeds the URL inline.
  4. Inline MMV mentions (checkbox tooltip, help overlay) include
     the Nexus URL.
"""
import os
import re
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')
INSTALL_PATH = os.path.join(os.path.dirname(HERE), 'INSTALL.md')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


@pytest.fixture(scope='module')
def install_source():
    with open(INSTALL_PATH) as f:
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


# ---------------------------------------------------------------------
# About tab Helpful Links section
# ---------------------------------------------------------------------

# The exact URLs we expect — locked in so a typo or wrong fork URL
# (e.g. a stale UXM mirror) gets caught by tests.
EXPECTED_LINKS = {
    'me3':
        'https://me3-mod.github.io/',
    'UXM Selective Unpacker':
        'https://github.com/Nordgaren/UXM-Selective-Unpack',
    'More Map Variations (MMV)':
        'https://www.nexusmods.com/eldenringnightreign/mods/578',
    'WitchyBND':
        'https://github.com/ividyon/WitchyBND',
    'DarkScript3':
        'https://github.com/AinTunez/DarkScript3',
}


class TestAboutTabHelpfulLinks:
    """The About tab is the canonical 'where do I get the external
    tools' surface. Locks in that every link is present + uses the
    canonical URL."""

    def test_about_tab_has_links_section(self, gui_source):
        body = _extract_method_body(gui_source, '_build_about_tab')
        assert 'Helpful links' in body or 'Helpful Links' in body, (
            'About tab missing Helpful Links section — users have no '
            'in-app path to external tools.')

    @pytest.mark.parametrize('label,url', list(EXPECTED_LINKS.items()))
    def test_link_present(self, gui_source, label, url):
        body = _extract_method_body(gui_source, '_build_about_tab')
        # The label must appear in the links list (matched via the
        # tuple structure) AND so must the URL string
        assert label in body, (
            f'About tab Helpful Links missing label {label!r}.')
        assert url in body, (
            f'About tab Helpful Links missing URL for {label}: '
            f'expected {url!r}. Canonical URL drift is the most '
            f'common silent breakage — locks it in.')

    def test_link_row_helper_exists(self, gui_source):
        """_add_link_row encapsulates the clickable-label pattern.
        Without it, each link would need ~5 lines of boilerplate."""
        assert 'def _add_link_row(' in gui_source

    def test_open_url_helper_exists(self, gui_source):
        """_open_url wraps webbrowser.open so a missing webbrowser
        module / sandbox issue doesn't crash the GUI."""
        assert 'def _open_url(' in gui_source

    def test_open_url_uses_webbrowser_module(self, gui_source):
        body = _extract_method_body(gui_source, '_open_url')
        assert 'webbrowser' in body, (
            '_open_url must import/use webbrowser — that\'s the only '
            'standard-library cross-platform way to open a URL.')

    def test_open_url_handles_failure(self, gui_source):
        """webbrowser.open can fail (no browser, sandboxed env).
        Must wrap in try/except so failure doesn't crash."""
        body = _extract_method_body(gui_source, '_open_url')
        assert 'try:' in body and 'except' in body, (
            '_open_url must catch exceptions — webbrowser.open can '
            'fail on systems without a default browser, and a '
            'traceback in a help link click is a bad UX.')

    def test_link_row_is_clickable(self, gui_source):
        """The link label needs cursor='hand2' to visually signal
        clickability, and a Button-1 binding to actually do the open."""
        body = _extract_method_body(gui_source, '_add_link_row')
        assert "cursor='hand2'" in body or 'cursor="hand2"' in body, (
            'Link label should set cursor=hand2 so users see the '
            'pointer change and realize it\'s clickable.')
        assert '<Button-1>' in body, (
            'Link label needs a Button-1 binding to open the URL — '
            'without it, the label is dead text.')

    def test_link_row_has_tooltip_with_url(self, gui_source):
        """Hovering should show the full URL — useful for users who
        want to copy/paste rather than click."""
        body = _extract_method_body(gui_source, '_add_link_row')
        assert 'Tooltip(' in body, (
            'Each link should have a Tooltip showing the URL — lets '
            'users see where they\'re going before clicking and copy '
            'the URL manually if needed.')


# ---------------------------------------------------------------------
# Broken UXM reference is fixed
# ---------------------------------------------------------------------

class TestBrokenUxmReferenceFixed:
    def test_no_linked_in_the_readme_pointer(self, gui_source):
        """The old GUI error said 'run UXM (linked in the README)' but
        the README had no UXM link — broken pointer. The fix embeds
        the URL inline instead. Lock in the absence of the bad
        phrasing so it doesn't sneak back in."""
        assert 'linked in the README' not in gui_source, (
            'The broken "linked in the README" pointer is back. UXM '
            'should be referenced via its direct URL in error '
            'messages, not via a phantom README link.')

    def test_uxm_url_in_input_dir_error(self, gui_source):
        """The error message that tells users they need to UXM-unpack
        their NR install must now embed the UXM URL directly."""
        # The error fires from inside _run_shuffle. Find the
        # specific error message and check it contains the URL.
        assert 'Nordgaren/UXM-Selective-Unpack' in gui_source, (
            "The UXM URL must appear somewhere in the GUI — the "
            "input-dir error message references it.")


# ---------------------------------------------------------------------
# MMV inline links
# ---------------------------------------------------------------------

class TestMmvInlineLinks:
    """MMV is mentioned by name in the checkbox tooltip, the info
    icon's longer text, and the heritage help overlay. Each should
    embed the URL inline (or reference the About tab) so users have
    a direct path to install."""

    MMV_URL_FRAGMENT = 'nexusmods.com/eldenringnightreign/mods/578'

    def test_mmv_checkbox_tooltip_references_url(self, gui_source):
        """The Tooltip attached to the MMV checkbox is the most
        commonly-seen hint. Must point at the install URL."""
        # Find the MMV Tooltip block
        mmv_tooltip_idx = gui_source.find('mmv_check')
        assert mmv_tooltip_idx != -1
        # Look in the next ~600 chars for the URL
        window = gui_source[mmv_tooltip_idx:mmv_tooltip_idx + 1200]
        assert self.MMV_URL_FRAGMENT in window, (
            'MMV checkbox Tooltip should mention the Nexus URL — '
            'users hovering the checkbox should see where to get '
            'MMV, not just "install MMV first".')

    def test_mmv_info_icon_references_url(self, gui_source):
        """The info icon's longer text is the place users go for
        full detail — must include the URL there too."""
        # Find make_info_icon near MMV
        mmv_section_start = gui_source.find('"MMV integration (optional)"')
        assert mmv_section_start != -1
        # Info-icon text lives within the next ~1500 chars
        window = gui_source[mmv_section_start:mmv_section_start + 2500]
        assert self.MMV_URL_FRAGMENT in window, (
            'MMV info icon text should include the install URL — '
            'this is the canonical "full details" surface.')

    def test_heritage_help_overlay_references_url(self, gui_source):
        """The Heritage tab help overlay (TAB_HELP_CONTENT['heritage'])
        explains MMV — should include the URL for the same reasons."""
        # Find the heritage help content block
        idx = gui_source.find("'heritage':")
        assert idx != -1
        # The next ~3000 chars cover the heritage entry
        window = gui_source[idx:idx + 3000]
        assert self.MMV_URL_FRAGMENT in window, (
            'Heritage help overlay should include the MMV URL — '
            'help text that mentions a tool without a path forward is '
            'just a name-drop.')


# ---------------------------------------------------------------------
# INSTALL.md coverage
# ---------------------------------------------------------------------

class TestInstallMdCoverage:
    def test_install_links_uxm(self, install_source):
        """UXM is needed for advanced workflows (heritage chr import,
        EMEVD inspection). It should be linked in INSTALL.md."""
        assert 'UXM-Selective-Unpack' in install_source, (
            'INSTALL.md should link to UXM Selective Unpacker — '
            'users following the docs need a path to it for the '
            'Elden Ring Assets workflow.')

    def test_install_links_mmv(self, install_source):
        """MMV was already linked — regression guard."""
        assert 'eldenringnightreign/mods/578' in install_source

    def test_install_links_me3(self, install_source):
        """me3 is required — regression guard on its link."""
        assert 'me3-mod.github.io' in install_source
