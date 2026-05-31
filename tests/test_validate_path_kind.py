"""
test_validate_path_kind.py — unit tests for the path-kind validator.

validate_path_kind() is the pure-function half of the GUI's live path
validation feature. It returns (state, detail) tuples describing
whether a path matches the expected shape for its role (NR install,
ER install, ME3 output, etc.). The GUI calls it on every path-field
change to update the StatusIndicator next to that field.

These tests don't touch Tk — they build fake directory layouts under
tmp_path and assert validate_path_kind classifies them correctly.
"""
import os
import importlib.util
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def validate_path_kind():
    """Extract validate_path_kind from oops_rando_gui without
    triggering Tk imports (no display in this env).

    Strategy: read the source, locate the function definition,
    compile just that function into a namespace. Avoids importing the
    whole GUI module."""
    with open(GUI_PATH) as f:
        src = f.read()
    # Find `def validate_path_kind(` and walk to end of function
    start = src.find('def validate_path_kind(')
    if start == -1:
        pytest.skip('validate_path_kind not found in GUI source')
    # End: first line at column 0 that isn't blank/comment after start
    lines = src[start:].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith('#'):
            break
        body.append(line)
    func_src = '\n'.join(body)
    ns = {}
    exec(func_src, ns)
    return ns['validate_path_kind']


# ---------------------------------------------------------------------
# Empty / missing paths
# ---------------------------------------------------------------------

class TestEmptyPath:
    def test_empty_string(self, validate_path_kind):
        state, detail = validate_path_kind('', 'nr_install')
        assert state == 'unknown'
        assert 'not set' in detail.lower()

    def test_whitespace_only(self, validate_path_kind):
        state, detail = validate_path_kind('   ', 'nr_install')
        assert state == 'unknown'

    def test_none(self, validate_path_kind):
        state, detail = validate_path_kind(None, 'nr_install')
        assert state == 'unknown'


class TestNonexistentPath:
    def test_nr_install_missing_dir(self, validate_path_kind, tmp_path):
        ghost = tmp_path / 'no_such_dir'
        state, detail = validate_path_kind(str(ghost), 'nr_install')
        # v0.27.x: validation never returns 'error' (see test_never_returns_error);
        # a missing path is a 'warn' that explains recovery via the Vanilla MSBs field.
        assert state == 'warn'
        assert 'not found' in detail.lower()


# ---------------------------------------------------------------------
# nr_install — looks for Game/map/mapstudio with .msb*
# ---------------------------------------------------------------------

class TestNrInstall:
    def test_uxm_unpacked_layout_ok(self, validate_path_kind, tmp_path):
        """Conventional UXM layout: <install>/map/mapstudio/m*.msb.dcx"""
        install = tmp_path / 'NIGHTREIGN'
        mapstudio = install / 'map' / 'mapstudio'
        mapstudio.mkdir(parents=True)
        (mapstudio / 'm10_00_00_00.msb.dcx').write_text('(stub)')
        (mapstudio / 'm60_42_36_00.msb.dcx').write_text('(stub)')
        state, detail = validate_path_kind(str(install), 'nr_install')
        assert state == 'ok'
        assert 'NR install OK' in detail
        assert 'MSBs' in detail

    def test_install_root_with_game_subdir(self, validate_path_kind, tmp_path):
        """User might pick the install ROOT (parent of Game/), not Game/.
        We accept either."""
        install = tmp_path / 'NIGHTREIGN'
        mapstudio = install / 'Game' / 'map' / 'mapstudio'
        mapstudio.mkdir(parents=True)
        (mapstudio / 'm10_00_00_00.msb.dcx').write_text('(stub)')
        state, detail = validate_path_kind(str(install), 'nr_install')
        assert state == 'ok'

    def test_unpacked_but_empty_mapstudio(self, validate_path_kind, tmp_path):
        """The mapstudio dir exists but has no .msb files — UXM started
        unpacking but didn't finish, or this is an empty mod profile.
        warn, not error: path is plausible just incomplete."""
        install = tmp_path / 'NIGHTREIGN'
        (install / 'map' / 'mapstudio').mkdir(parents=True)
        state, detail = validate_path_kind(str(install), 'nr_install')
        assert state == 'warn'
        assert 'map/mapstudio' in detail.lower()

    def test_no_mapstudio_at_all(self, validate_path_kind, tmp_path):
        """Path exists but has no map/mapstudio anywhere — wrong dir or
        NR isn't UXM-unpacked. error: not a valid input regardless."""
        not_an_install = tmp_path / 'random_folder'
        not_an_install.mkdir()
        state, detail = validate_path_kind(str(not_an_install), 'nr_install')
        # v0.27.x: never 'error' — warns and explains recovery via Vanilla MSBs field.
        assert state == 'warn'
        assert 'map/mapstudio' in detail.lower() or 'mapstudio' in detail.lower()


# ---------------------------------------------------------------------
# er_install — looks for Game/chr with .chrbnd*
# ---------------------------------------------------------------------

class TestErInstall:
    def test_uxm_unpacked_layout_ok(self, validate_path_kind, tmp_path):
        install = tmp_path / 'ELDEN_RING'
        chr_dir = install / 'chr'
        chr_dir.mkdir(parents=True)
        (chr_dir / 'c2110.chrbnd.dcx').write_text('(stub)')
        (chr_dir / 'c5070.chrbnd.dcx').write_text('(stub)')
        state, detail = validate_path_kind(str(install), 'er_install')
        assert state == 'ok'
        assert '2 chr files' in detail

    def test_install_root_with_game_subdir(self, validate_path_kind, tmp_path):
        install = tmp_path / 'ELDEN_RING'
        (install / 'Game' / 'chr').mkdir(parents=True)
        (install / 'Game' / 'chr' / 'c2110.chrbnd.dcx').write_text('(stub)')
        state, detail = validate_path_kind(str(install), 'er_install')
        assert state == 'ok'

    def test_empty_chr_dir(self, validate_path_kind, tmp_path):
        install = tmp_path / 'ELDEN_RING'
        (install / 'chr').mkdir(parents=True)
        state, detail = validate_path_kind(str(install), 'er_install')
        assert state == 'warn'

    def test_no_chr_dir(self, validate_path_kind, tmp_path):
        # v0.28.x: ER is optional (heritage only) and packed installs are read
        # straight from the archives, so a non-ER folder is a soft 'warn', not
        # a hard 'error' — consistent with nr_install.
        nope = tmp_path / 'random_folder'
        nope.mkdir()
        state, detail = validate_path_kind(str(nope), 'er_install')
        assert state == 'warn'


# ---------------------------------------------------------------------
# me3_profile — output dir, allowed to not exist if parent does
# ---------------------------------------------------------------------

class TestMe3Profile:
    def test_existing_dir_ok(self, validate_path_kind, tmp_path):
        profile = tmp_path / 'me3_profile'
        profile.mkdir()
        state, detail = validate_path_kind(str(profile), 'me3_profile')
        assert state == 'ok'

    def test_missing_but_parent_exists_warns(self, validate_path_kind, tmp_path):
        """ME3 output gets created by the Run pipeline, so a not-yet-
        existing dir whose parent IS a real directory should be 'warn'
        (incomplete but recoverable), not 'error'."""
        profile = tmp_path / 'will_be_created_on_run'
        state, detail = validate_path_kind(str(profile), 'me3_profile')
        assert state == 'warn'
        assert 'created on Run' in detail or 'created' in detail.lower()

    def test_missing_with_missing_parent_errors(self, validate_path_kind, tmp_path):
        """If even the parent doesn't exist, this is a real problem
        (drive typo, broken symlink) and we should flag it as error."""
        ghost = tmp_path / 'nope_parent' / 'profile'
        state, detail = validate_path_kind(str(ghost), 'me3_profile')
        assert state == 'error'


# ---------------------------------------------------------------------
# Content-shape kinds (mapstudio_dir / event_dir / chr_dir)
# ---------------------------------------------------------------------

class TestContentShapeKinds:
    def test_mapstudio_dir_with_msbs(self, validate_path_kind, tmp_path):
        d = tmp_path / 'ms'; d.mkdir()
        (d / 'm10_00_00_00.msb').write_text('')
        (d / 'm60_42_36_00.msb.dcx').write_text('')
        state, detail = validate_path_kind(str(d), 'mapstudio_dir')
        assert state == 'ok'
        assert '2 MSB' in detail

    def test_event_dir_with_emevd(self, validate_path_kind, tmp_path):
        d = tmp_path / 'ev'; d.mkdir()
        (d / 'common.emevd.dcx').write_text('')
        state, detail = validate_path_kind(str(d), 'event_dir')
        assert state == 'ok'

    def test_chr_dir_with_chrbnd(self, validate_path_kind, tmp_path):
        d = tmp_path / 'ch'; d.mkdir()
        (d / 'c0000.chrbnd.dcx').write_text('')
        state, detail = validate_path_kind(str(d), 'chr_dir')
        assert state == 'ok'

    def test_empty_content_dirs_warn(self, validate_path_kind, tmp_path):
        """Existing dir with no matching content → warn (not error).
        The dir might be valid for a different purpose, but isn't a
        useful source for this role."""
        d = tmp_path / 'empty'; d.mkdir()
        for kind in ('mapstudio_dir', 'event_dir', 'chr_dir'):
            state, _ = validate_path_kind(str(d), kind)
            assert state == 'warn', f'kind={kind} got {state}, expected warn'


class TestGeneralDir:
    def test_general_dir_just_checks_existence(self, validate_path_kind, tmp_path):
        d = tmp_path / 'whatever'; d.mkdir()
        state, _ = validate_path_kind(str(d), 'general_dir')
        assert state == 'ok'


class TestUnknownKind:
    def test_unknown_kind_returns_unknown_state(self, validate_path_kind, tmp_path):
        """Defensive: an unknown kind shouldn't raise, should return
        'unknown' so the indicator just shows the · glyph."""
        d = tmp_path / 'x'; d.mkdir()
        state, detail = validate_path_kind(str(d), 'made_up_kind')
        assert state == 'unknown'
        assert 'made_up_kind' in detail or 'unknown' in detail.lower()


class TestMe3LauncherExe:
    """v0.27.0: the me3 launcher row never reports 'error' — the binary
    is auto-discovered at launch, so the field is a pure override and a
    missing/odd value caps at 'warn' (yellow)."""

    def test_missing_file_is_warn_not_error(self, validate_path_kind,
                                            tmp_path):
        missing = tmp_path / 'nope' / 'me3.exe'
        state, detail = validate_path_kind(str(missing), 'me3_launcher_exe')
        assert state == 'warn', f'expected warn, got {state}'
        assert 'auto-discovered' in detail

    def test_recognised_binary_is_ok(self, validate_path_kind, tmp_path):
        for name in ('me3.exe', 'me3', 'modengine2_launcher.exe'):
            f = tmp_path / name
            f.write_text('')
            state, _ = validate_path_kind(str(f), 'me3_launcher_exe')
            assert state == 'ok', f'{name} -> {state}'

    def test_uppercase_extension_is_ok(self, validate_path_kind, tmp_path):
        """basename match is case-folded — me3.EXE must read as ok."""
        f = tmp_path / 'me3.EXE'
        f.write_text('')
        state, _ = validate_path_kind(str(f), 'me3_launcher_exe')
        assert state == 'ok'

    def test_unrecognised_name_is_warn(self, validate_path_kind, tmp_path):
        f = tmp_path / 'something_else.exe'
        f.write_text('')
        state, _ = validate_path_kind(str(f), 'me3_launcher_exe')
        assert state == 'warn'

    def test_never_returns_error(self, validate_path_kind, tmp_path):
        """The whole point: no input shape yields a red row."""
        cases = [
            str(tmp_path / 'missing.exe'),
            str(tmp_path),  # a directory, not a file
        ]
        odd = tmp_path / 'weird.bin'; odd.write_text('')
        cases.append(str(odd))
        for c in cases:
            state, _ = validate_path_kind(c, 'me3_launcher_exe')
            assert state != 'error', f'{c} -> error (should never)'
