"""
test_me3_profile_scaffold.py — Tier 2 UX #7 me3 profile scaffold.

Three layers:
  1. Pure-function tests for _sanitize_profile_name and
     build_me3_profile_template — string transformations, no I/O.
  2. End-to-end scaffold tests against tmp_path: create profile,
     verify directory structure, verify .me3 contents, verify
     no-clobber behavior, error handling.
  3. Source-inspection tests for the GUI _create_me3_profile handler.
"""
import os
import sys
import re
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'dev'))
import install_discovery


# ---------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------

class TestSanitizeProfileName:
    def test_alphanumeric_lowercased(self):
        assert install_discovery._sanitize_profile_name('AbC123') == 'abc123'

    def test_hyphens_preserved(self):
        assert install_discovery._sanitize_profile_name('my-cool-profile') == 'my-cool-profile'

    def test_underscores_preserved(self):
        """Underscores are valid in me3 names — they shouldn't be
        replaced with hyphens like other punctuation."""
        assert install_discovery._sanitize_profile_name('with_underscore') == 'with_underscore'

    def test_spaces_become_hyphens(self):
        assert install_discovery._sanitize_profile_name('my cool profile') == 'my-cool-profile'

    def test_special_chars_replaced(self):
        assert install_discovery._sanitize_profile_name('hello!!!world') == 'hello-world'

    def test_collapses_runs_of_hyphens(self):
        """Multiple separators in a row collapse to a single hyphen."""
        assert install_discovery._sanitize_profile_name('a---b') == 'a-b'
        assert install_discovery._sanitize_profile_name('a   !!! b') == 'a-b'

    def test_strips_leading_trailing_hyphens(self):
        assert install_discovery._sanitize_profile_name('---abc---') == 'abc'

    def test_empty_falls_back_to_default(self):
        """An empty or whitespace-only name must produce a sensible
        default rather than an empty filename (which would create
        a hidden '.me3' file)."""
        assert install_discovery._sanitize_profile_name('') == 'nightreign-rando'
        assert install_discovery._sanitize_profile_name('   ') == 'nightreign-rando'
        assert install_discovery._sanitize_profile_name('!!!') == 'nightreign-rando'

    def test_none_handled(self):
        """Defensive: None shouldn't crash the helper."""
        assert install_discovery._sanitize_profile_name(None) == 'nightreign-rando'


class TestBuildMe3ProfileTemplate:
    def test_returns_string(self):
        result = install_discovery.build_me3_profile_template('test')
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_profile_version(self):
        """me3's parser keys on profileVersion — must be present."""
        result = install_discovery.build_me3_profile_template('test')
        assert 'profileVersion = "v1"' in result

    def test_includes_game_slug(self):
        """The [supports] block declares which game this targets."""
        result = install_discovery.build_me3_profile_template('test', game='nightreign')
        assert 'game = "nightreign"' in result

    def test_custom_game_slug(self):
        """Supporting other From titles in the future — the helper
        accepts a game parameter."""
        result = install_discovery.build_me3_profile_template(
            'test', game='eldenring')
        assert 'game = "eldenring"' in result

    def test_package_id_appears_twice(self):
        """The [[packages]] block sets BOTH id and source to the
        package_id by convention (source is the relative dir name)."""
        result = install_discovery.build_me3_profile_template(
            'test', package_id='custom-pkg')
        # Both id and source should reference custom-pkg
        assert result.count('custom-pkg') == 2
        assert 'id = "custom-pkg"' in result
        assert 'source = "custom-pkg"' in result

    def test_default_package_id_is_rando(self):
        result = install_discovery.build_me3_profile_template('test')
        assert 'id = "rando"' in result

    def test_has_attribution_comment(self):
        """A header comment helps users who poke around the .me3 file
        understand where it came from."""
        result = install_discovery.build_me3_profile_template('test')
        # Should be a TOML comment (starts with #) and mention the rando
        first_line = result.splitlines()[0]
        assert first_line.startswith('#')
        assert 'Nightreign' in result or 'rando' in result.lower()

    def test_valid_toml_shape(self):
        """The output should at least pass a basic TOML structure check:
        section headers in [brackets], key=value pairs, doubled brackets
        for arrays of tables."""
        result = install_discovery.build_me3_profile_template('test')
        # Section header
        assert '[supports]' in result
        # Array-of-tables for packages
        assert '[[packages]]' in result


# ---------------------------------------------------------------------
# Scaffold integration — actual filesystem
# ---------------------------------------------------------------------

class TestScaffoldMe3Profile:
    def test_creates_target_dir(self, tmp_path):
        """Scaffold into a not-yet-existing dir creates it."""
        target = tmp_path / 'new-profile'
        assert not target.exists()
        result = install_discovery.scaffold_me3_profile(str(target))
        assert os.path.isdir(result['profile_dir'])

    def test_creates_me3_config_file(self, tmp_path):
        target = tmp_path / 'p'
        result = install_discovery.scaffold_me3_profile(str(target))
        assert os.path.isfile(result['me3_file'])
        with open(result['me3_file']) as f:
            content = f.read()
        assert 'profileVersion = "v1"' in content

    def test_me3_filename_matches_profile_name(self, tmp_path):
        """The .me3 file is named after the profile (e.g. 'mything.me3')."""
        target = tmp_path / 'my-profile'
        result = install_discovery.scaffold_me3_profile(str(target))
        assert result['me3_file'].endswith('my-profile.me3')

    def test_creates_package_subdir(self, tmp_path):
        target = tmp_path / 'p'
        result = install_discovery.scaffold_me3_profile(str(target))
        assert os.path.isdir(result['package_dir'])

    def test_creates_conventional_subdirectories(self, tmp_path):
        """The rando expects map/mapstudio, chr, event under the package
        dir. Scaffold creates them so first run doesn't have to."""
        target = tmp_path / 'p'
        result = install_discovery.scaffold_me3_profile(str(target))
        pkg = result['package_dir']
        for sub in ('map/mapstudio', 'chr', 'event'):
            assert os.path.isdir(os.path.join(pkg, sub)), (
                f'Conventional subdir {sub!r} not created')

    def test_writes_readme(self, tmp_path):
        """A README.md helps users who explore the new folder."""
        target = tmp_path / 'p'
        install_discovery.scaffold_me3_profile(str(target))
        readme = target / 'README.md'
        assert readme.exists()
        text = readme.read_text()
        # Should explain the directory structure
        assert 'me3' in text.lower()
        assert 'package' in text.lower()

    def test_custom_profile_name(self, tmp_path):
        target = tmp_path / 'whatever'
        result = install_discovery.scaffold_me3_profile(
            str(target), profile_name='my-named-profile')
        assert result['profile_name'] == 'my-named-profile'
        assert result['me3_file'].endswith('my-named-profile.me3')

    def test_profile_name_defaults_to_dir_basename(self, tmp_path):
        target = tmp_path / 'derived-from-dir'
        result = install_discovery.scaffold_me3_profile(str(target))
        assert result['profile_name'] == 'derived-from-dir'

    def test_profile_name_sanitized(self, tmp_path):
        """A messy user-typed name gets cleaned before going into the
        filename (avoids unintentional special chars in path)."""
        target = tmp_path / 'p'
        result = install_discovery.scaffold_me3_profile(
            str(target), profile_name='My Bad! Name!!')
        assert result['profile_name'] == 'my-bad-name'

    def test_custom_package_id(self, tmp_path):
        target = tmp_path / 'p'
        result = install_discovery.scaffold_me3_profile(
            str(target), package_id='custom-pkg')
        assert os.path.basename(result['package_dir']) == 'custom-pkg'
        # Subdirs still created under the custom name
        assert os.path.isdir(os.path.join(result['package_dir'],
                                           'map', 'mapstudio'))

    def test_refuses_to_clobber_nonempty_dir(self, tmp_path):
        """Critical safety property: must not overwrite arbitrary
        existing user files. New users may not realize the consequences."""
        target = tmp_path / 'existing'
        target.mkdir()
        (target / 'something-important.txt').write_text('keep me!')
        with pytest.raises(FileExistsError) as excinfo:
            install_discovery.scaffold_me3_profile(str(target))
        # Error message should be actionable
        msg = str(excinfo.value).lower()
        assert 'not empty' in msg or 'exists' in msg
        # Most importantly: the existing file should be untouched
        assert (target / 'something-important.txt').read_text() == 'keep me!'

    def test_empty_existing_dir_ok(self, tmp_path):
        """An EMPTY existing dir is fine — no risk of clobbering."""
        target = tmp_path / 'empty'
        target.mkdir()
        result = install_discovery.scaffold_me3_profile(str(target))
        assert os.path.isfile(result['me3_file'])

    def test_returns_absolute_paths(self, tmp_path):
        """All returned paths should be absolute so they survive
        cwd changes when the GUI propagates them downstream."""
        target = tmp_path / 'p'
        result = install_discovery.scaffold_me3_profile(str(target))
        for key in ('profile_dir', 'me3_file', 'package_dir'):
            assert os.path.isabs(result[key]), (
                f'{key} is not absolute: {result[key]}')

    def test_returns_required_keys(self, tmp_path):
        """Locks in the contract the GUI relies on."""
        result = install_discovery.scaffold_me3_profile(str(tmp_path / 'p'))
        for key in ('profile_dir', 'me3_file', 'package_dir', 'profile_name'):
            assert key in result


# ---------------------------------------------------------------------
# Source-inspection: GUI button wiring
# ---------------------------------------------------------------------

GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


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


class TestCreateProfileButtonWiring:
    def test_handler_method_exists(self, gui_source):
        assert 'def _create_me3_profile(self):' in gui_source, (
            '_create_me3_profile handler missing — Create new… button '
            'would have no command to call.')

    def test_button_exists_in_path_row_loop(self, gui_source):
        """The Create new… button must be packed in the me3_profile
        row of the Folders section, gated on kind == 'me3_profile'
        so it only appears there (not on game_install / er_install /
        me3_launcher rows)."""
        # Look for the button construction site specifically (not
        # mentions in comments). Pattern: ttk.Button(row, text="Create...
        # is distinctive enough.
        import re
        # Find the actual Button() call with Create new text
        # Comment vs code: button construction uses ttk.Button(...
        m = re.search(r'ttk\.Button\([^)]*text="Create new', gui_source)
        assert m is not None, (
            'No ttk.Button(text="Create new…") found in GUI source — '
            'the Create new… button was never packed.')
        # Look back from the Button construction site for the gating
        # if-statement. Should be within ~200 chars (the if line is
        # the line immediately above).
        button_idx = m.start()
        window = gui_source[max(0, button_idx - 400):button_idx]
        assert "kind == 'me3_profile'" in window, (
            'Create new… button must be gated on kind == "me3_profile" '
            'so it only appears on the me3 package row, not on game/'
            'er install or launcher rows.')


class TestCreateProfileHandlerLogic:
    def test_calls_scaffold(self, gui_source):
        """The handler must actually invoke
        install_discovery.scaffold_me3_profile — otherwise the button
        just opens a dialog and does nothing."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        assert 'scaffold_me3_profile(' in body, (
            'Handler must call install_discovery.scaffold_me3_profile.')

    def test_uses_askdirectory(self, gui_source):
        """Target dir selection should use askdirectory — file picker
        wouldn't let the user create a new folder name inline."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        assert 'askdirectory(' in body, (
            'Handler should use filedialog.askdirectory so the user can '
            'pick or name a new target folder.')

    def test_handles_user_cancellation(self, gui_source):
        """If the user cancels the directory dialog, handler must
        return cleanly — not proceed with an empty target string."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        # The askdirectory return value should be checked before use
        assert 'if not target' in body or 'if target' in body, (
            'Handler must check the askdirectory result before using '
            'it — cancellation returns an empty string.')

    def test_handles_file_exists_error(self, gui_source):
        """The scaffold raises FileExistsError on non-empty target.
        Handler must catch this specifically so the error message can
        suggest picking a different folder rather than dumping a
        traceback."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        assert 'FileExistsError' in body, (
            'Handler must catch FileExistsError specifically — the '
            'scaffold helper raises it for non-empty target dirs.')

    def test_handles_oserror(self, gui_source):
        """Filesystem errors (permission denied, disk full) are OSError."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        assert 'OSError' in body, (
            'Handler must catch OSError — permission denied and disk '
            'full both raise OSError, not the more-specific siblings.')

    def test_populates_me3_package_var(self, gui_source):
        """After a successful scaffold, the me3_package_var should be
        set to the new package_dir so the user can immediately run."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        assert 'me3_package_var.set(' in body, (
            'Handler must populate me3_package_var with the new '
            "package_dir — otherwise the user has to manually browse "
            'to the directory they just created.')

    def test_uses_package_dir_not_profile_dir(self, gui_source):
        """me3_package_var conventionally points at the package
        subdirectory, NOT the profile root. Make sure the handler
        uses the right key from the scaffold result."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        # The set() call should reference package_dir, not profile_dir
        # Find the line containing me3_package_var.set
        for line in body.splitlines():
            if 'me3_package_var.set(' in line:
                # Check this specific line uses 'package_dir'
                assert 'package_dir' in line, (
                    'me3_package_var must be set to package_dir (the '
                    'package subdirectory), not profile_dir (the '
                    'profile root) — these differ by one level.')
                break
        else:
            pytest.fail('No me3_package_var.set() call found in handler')

    def test_shows_success_feedback(self, gui_source):
        """On success, the user should see a confirmation dialog or
        log line — otherwise the button click feels like nothing
        happened (the field updates but the dialog already closed)."""
        body = _extract_method_body(gui_source, '_create_me3_profile')
        # Either showinfo for a dialog, or _log for an in-app message
        assert ('showinfo' in body or '_log(' in body), (
            'Handler should provide visible feedback after a successful '
            'scaffold — showinfo dialog or _log line.')
