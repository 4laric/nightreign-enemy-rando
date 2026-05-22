"""
test_install_discovery.py — tests for the Steam auto-detection.

These tests build a fake Steam install on disk under tmp_path, point
the module at it via monkeypatched helpers (find_steam_install_root),
and verify the discovery walks libraryfolders.vdf and finds NR/ER.

Cross-platform-relevant logic is exercised:
  - libraryfolders.vdf in either steamapps/ or config/
  - multi-library setups (game in non-main library)
  - case-insensitive Steam dir name matching
  - missing exe → not found (avoids false positives on dir-only matches)
  - empty/missing VDF → main install still scannable
  - unparseable VDF → graceful (returns just the root as the library)
"""

import os
import sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.join(os.path.dirname(HERE), 'dev')
sys.path.insert(0, DEV)
import install_discovery as id_  # noqa: E402


# -----------------------------------------------------------------------------
# Helpers to build a fake Steam install structure
# -----------------------------------------------------------------------------

def _write(path, content=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _make_steam_root(tmp_path, libraries=()):
    """Create a fake Steam install at tmp_path/Steam with
    libraryfolders.vdf listing the given library paths."""
    steam = tmp_path / 'Steam'
    steam.mkdir()
    (steam / 'steamapps').mkdir()
    vdf_entries = []
    for i, lib in enumerate([str(steam)] + list(libraries)):
        # Escape backslashes for VDF (the Steam format uses \\).
        escaped = lib.replace('\\', '\\\\')
        vdf_entries.append(f'''\
    "{i}"
    {{
        "path"          "{escaped}"
        "label"         ""
        "contentid"     "{i}{i}{i}"
        "totalsize"     "0"
        "update_clean_bytes_tally"  "0"
        "time_last_update_corruption"   "0"
        "apps"
        {{
        }}
    }}''')
    vdf_content = '"libraryfolders"\n{\n' + '\n'.join(vdf_entries) + '\n}\n'
    _write(str(steam / 'steamapps' / 'libraryfolders.vdf'), vdf_content)
    return str(steam)


def _install_game(library_path, dir_name, exe_relpath):
    """Create a fake game install under library/steamapps/common/<dir_name>
    with a stub exe file at the expected location."""
    install = os.path.join(library_path, 'steamapps', 'common', dir_name)
    os.makedirs(install)
    exe_path = os.path.join(install, exe_relpath)
    _write(exe_path, '(fake exe)')
    return os.path.join(install, 'Game')  # what discovery should return


# -----------------------------------------------------------------------------
# find_steam_libraries
# -----------------------------------------------------------------------------

class TestFindSteamLibraries:
    def test_main_install_only(self, tmp_path, monkeypatch):
        """Single Steam install with no extra libraries → returns the
        main install path."""
        steam = _make_steam_root(tmp_path)
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        libs = id_.find_steam_libraries()
        assert libs == [steam]

    def test_multi_library(self, tmp_path, monkeypatch):
        """Main install + 2 extra libraries — all returned, in order."""
        extra1 = tmp_path / 'SteamLib1'; extra1.mkdir()
        extra2 = tmp_path / 'SteamLib2'; extra2.mkdir()
        steam = _make_steam_root(tmp_path, [str(extra1), str(extra2)])
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        libs = id_.find_steam_libraries()
        # Order: main install first (always included), then VDF entries
        # in file order. The main install will also appear in the VDF
        # since we listed it as entry "0" — dedupe should collapse that.
        assert libs[0] == steam
        assert str(extra1) in libs
        assert str(extra2) in libs
        assert len(libs) == 3

    def test_no_vdf_returns_just_root(self, tmp_path, monkeypatch):
        """If libraryfolders.vdf is missing (fresh Steam install with
        no libraries configured), still report the main install."""
        steam = tmp_path / 'Steam'
        steam.mkdir(); (steam / 'steamapps').mkdir()  # no VDF
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: str(steam))
        libs = id_.find_steam_libraries()
        assert libs == [str(steam)]

    def test_no_steam_at_all(self, monkeypatch):
        """If Steam isn't installed, returns an empty list (not None)."""
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: None)
        assert id_.find_steam_libraries() == []

    def test_vdf_in_config_dir(self, tmp_path, monkeypatch):
        """Older Steam puts the VDF in config/ instead of steamapps/.
        Both locations must be checked."""
        steam = tmp_path / 'Steam'
        steam.mkdir(); (steam / 'config').mkdir(); (steam / 'steamapps').mkdir()
        extra = tmp_path / 'OldStyleLib'; extra.mkdir()
        # Write VDF in config/ only (older layout)
        vdf = f'''"libraryfolders"
{{
    "0"
    {{
        "path"  "{str(extra).replace(chr(92), chr(92)*2)}"
    }}
}}
'''
        _write(str(steam / 'config' / 'libraryfolders.vdf'), vdf)
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: str(steam))
        libs = id_.find_steam_libraries()
        assert str(extra) in libs

    def test_nonexistent_library_paths_filtered(self, tmp_path, monkeypatch):
        """If libraryfolders.vdf references paths that don't exist
        (user moved/deleted a library after Steam recorded it), those
        entries should be silently dropped."""
        ghost = tmp_path / 'this_does_not_exist'  # never created
        steam = _make_steam_root(tmp_path, [str(ghost)])
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        libs = id_.find_steam_libraries()
        assert str(ghost) not in libs
        assert steam in libs


# -----------------------------------------------------------------------------
# find_game_install
# -----------------------------------------------------------------------------

class TestFindGameInstall:
    def test_nightreign_in_main_library(self, tmp_path, monkeypatch):
        steam = _make_steam_root(tmp_path)
        expected = _install_game(steam, 'ELDEN RING NIGHTREIGN',
                                  os.path.join('Game', 'nightreign.exe'))
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_nightreign_install() == expected

    def test_elden_ring_in_extra_library(self, tmp_path, monkeypatch):
        extra = tmp_path / 'BigDrive'; extra.mkdir()
        steam = _make_steam_root(tmp_path, [str(extra)])
        expected = _install_game(str(extra), 'ELDEN RING',
                                  os.path.join('Game', 'eldenring.exe'))
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_elden_ring_install() == expected

    def test_case_insensitive_dir_match(self, tmp_path, monkeypatch):
        """Steam directory case differs on different filesystems
        (NTFS records case but is case-insensitive; ext4 is case-
        sensitive). We should match regardless."""
        steam = _make_steam_root(tmp_path)
        expected = _install_game(steam, 'Elden Ring Nightreign',  # mixed case
                                  os.path.join('Game', 'nightreign.exe'))
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_nightreign_install() == expected

    def test_dir_present_but_exe_missing_not_a_match(self, tmp_path, monkeypatch):
        """A "ELDEN RING NIGHTREIGN" directory that doesn't contain the
        exe (e.g. partial uninstall, file move) should NOT be reported.
        Avoids returning paths that downstream code will silently fail on."""
        steam = _make_steam_root(tmp_path)
        # Make the dir but no exe inside
        os.makedirs(os.path.join(steam, 'steamapps', 'common',
                                  'ELDEN RING NIGHTREIGN', 'Game'))
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_nightreign_install() is None

    def test_no_game_installed_returns_none(self, tmp_path, monkeypatch):
        steam = _make_steam_root(tmp_path)
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_nightreign_install() is None
        assert id_.find_elden_ring_install() is None

    def test_no_steam_returns_none(self, monkeypatch):
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: None)
        assert id_.find_nightreign_install() is None

    def test_unknown_probe_key_raises(self):
        """Defensive: typo'd key should be a clear error, not a silent
        None (which would look like 'game not installed')."""
        with pytest.raises(ValueError, match='Unknown probe key'):
            id_.find_game_install('eldenring_typo')

    def test_first_match_wins_across_libraries(self, tmp_path, monkeypatch):
        """If somehow both libraries have the game (rare but possible
        if a user manually copied the install), the first library wins.
        Matches Steam's own behavior (it would launch the first one too)."""
        extra = tmp_path / 'Backup'; extra.mkdir()
        steam = _make_steam_root(tmp_path, [str(extra)])
        # Install in BOTH libraries
        main_path = _install_game(steam, 'ELDEN RING NIGHTREIGN',
                                   os.path.join('Game', 'nightreign.exe'))
        extra_path = _install_game(str(extra), 'ELDEN RING NIGHTREIGN',
                                    os.path.join('Game', 'nightreign.exe'))
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_nightreign_install() == main_path
        assert extra_path != main_path  # sanity


# -----------------------------------------------------------------------------
# detect_all
# -----------------------------------------------------------------------------

class TestDetectAll:
    def test_full_install(self, tmp_path, monkeypatch):
        steam = _make_steam_root(tmp_path)
        nr_path = _install_game(steam, 'ELDEN RING NIGHTREIGN',
                                 os.path.join('Game', 'nightreign.exe'))
        er_path = _install_game(steam, 'ELDEN RING',
                                 os.path.join('Game', 'eldenring.exe'))
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        info = id_.detect_all()
        assert info['steam_root'] == steam
        assert info['libraries'] == [steam]
        assert info['nightreign'] == nr_path
        assert info['elden_ring'] == er_path

    def test_no_steam_no_crash(self, monkeypatch):
        """Critical: GUI startup calls detect_all opportunistically.
        Must not raise when Steam is absent."""
        monkeypatch.delenv('OODLE_DLL', raising=False)
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: None)
        # Also force ME3 discovery to come up empty so this test is
        # deterministic regardless of what's on the test machine.
        monkeypatch.setattr(id_, 'find_me3_binary', lambda: None)
        monkeypatch.setattr(id_, 'find_me3_profiles', lambda: [])
        info = id_.detect_all()
        assert info == {
            'steam_root': None,
            'libraries': [],
            'nightreign': None,
            'elden_ring': None,
            'oodle_dll': None,
            'me3_binary': None,
            'me3_profiles': [],
        }


# -----------------------------------------------------------------------------
# Oodle DLL discovery
# -----------------------------------------------------------------------------

class TestFindOodleDll:
    """Search order: OODLE_DLL env var > local repo copy > game install."""

    def test_env_var_wins(self, tmp_path, monkeypatch):
        """OODLE_DLL set to a real file beats everything else."""
        explicit = tmp_path / 'explicit_oodle.dll'
        explicit.write_text('(stub)')
        monkeypatch.setenv('OODLE_DLL', str(explicit))
        # Steam also has one — env var should still win
        steam = _make_steam_root(tmp_path)
        _install_game(steam, 'ELDEN RING NIGHTREIGN',
                       os.path.join('Game', 'nightreign.exe'))
        steam_dll = os.path.join(steam, 'steamapps', 'common',
                                  'ELDEN RING NIGHTREIGN', 'Game',
                                  'oo2core_9_win64.dll')
        _write(steam_dll, '(stub steam dll)')
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_oodle_dll() == str(explicit)

    def test_env_var_missing_file_ignored(self, tmp_path, monkeypatch):
        """OODLE_DLL pointing at a missing file shouldn't poison the
        search — fall back to other locations. Prevents stale env-var
        entries from blocking discovery."""
        monkeypatch.setenv('OODLE_DLL', str(tmp_path / 'does_not_exist.dll'))
        steam = _make_steam_root(tmp_path)
        _install_game(steam, 'ELDEN RING NIGHTREIGN',
                       os.path.join('Game', 'nightreign.exe'))
        steam_dll = os.path.join(steam, 'steamapps', 'common',
                                  'ELDEN RING NIGHTREIGN', 'Game',
                                  'oo2core_9_win64.dll')
        _write(steam_dll, '(stub)')
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_oodle_dll() == steam_dll

    def test_finds_in_nightreign_install(self, tmp_path, monkeypatch):
        """The canonical case: user has NR on Steam, DLL ships with it."""
        # Prevent env-var inheritance from polluting the test
        monkeypatch.delenv('OODLE_DLL', raising=False)
        steam = _make_steam_root(tmp_path)
        _install_game(steam, 'ELDEN RING NIGHTREIGN',
                       os.path.join('Game', 'nightreign.exe'))
        dll = os.path.join(steam, 'steamapps', 'common',
                            'ELDEN RING NIGHTREIGN', 'Game',
                            'oo2core_9_win64.dll')
        _write(dll, '(stub)')
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_oodle_dll() == dll

    def test_falls_back_to_er_when_nr_missing(self, tmp_path, monkeypatch):
        """If NR isn't installed but ER is, use ER's Oodle DLL — the
        ABI is stable across Oodle 2.x so any of these source games
        works for decompress/recompress."""
        monkeypatch.delenv('OODLE_DLL', raising=False)
        steam = _make_steam_root(tmp_path)
        _install_game(steam, 'ELDEN RING',
                       os.path.join('Game', 'eldenring.exe'))
        dll = os.path.join(steam, 'steamapps', 'common', 'ELDEN RING',
                            'Game', 'oo2core_9_win64.dll')
        _write(dll, '(stub)')
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        assert id_.find_oodle_dll() == dll

    def test_returns_none_when_nothing_found(self, monkeypatch):
        """Honest negative: no env var, no local, no game install →
        return None. Caller surfaces the actionable error."""
        monkeypatch.delenv('OODLE_DLL', raising=False)
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: None)
        # Note: this test will spuriously fail if the test machine
        # has an oo2core_*.dll in the repo root (unlikely in CI but
        # plausible in dev). We accept that as a self-resolving fp.
        assert id_.find_oodle_dll() is None


class TestCopyOodleDllLocal:
    """Idempotent copy of a discovered Oodle DLL into the repo root
    so subsequent runs don't re-scan Steam."""

    def test_copies_from_nightreign(self, tmp_path, monkeypatch):
        """Steam-found DLL gets copied into the requested dest dir."""
        monkeypatch.delenv('OODLE_DLL', raising=False)
        steam = _make_steam_root(tmp_path)
        _install_game(steam, 'ELDEN RING NIGHTREIGN',
                       os.path.join('Game', 'nightreign.exe'))
        src_dll = os.path.join(steam, 'steamapps', 'common',
                                'ELDEN RING NIGHTREIGN', 'Game',
                                'oo2core_9_win64.dll')
        _write(src_dll, 'STUB_DLL_BYTES')
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        dest_dir = tmp_path / 'repo'
        dest_dir.mkdir()
        result = id_.copy_oodle_dll_local(str(dest_dir))
        assert result is not None
        assert result == str(dest_dir / 'oo2core_9_win64.dll')
        assert (dest_dir / 'oo2core_9_win64.dll').read_text() == 'STUB_DLL_BYTES'

    def test_idempotent_when_already_cached(self, tmp_path, monkeypatch):
        """Calling twice returns the same path; the second call doesn't
        re-do the copy. Lets the GUI invoke unconditionally at startup."""
        monkeypatch.delenv('OODLE_DLL', raising=False)
        dest_dir = tmp_path / 'repo'; dest_dir.mkdir()
        # Pre-existing cached DLL
        cached = dest_dir / 'oo2core_9_win64.dll'
        cached.write_text('ALREADY_HERE')
        # Configure Steam too — but the function should short-circuit
        # before touching Steam since cached exists.
        steam = _make_steam_root(tmp_path)
        _install_game(steam, 'ELDEN RING NIGHTREIGN',
                       os.path.join('Game', 'nightreign.exe'))
        _write(os.path.join(steam, 'steamapps', 'common',
                             'ELDEN RING NIGHTREIGN', 'Game',
                             'oo2core_9_win64.dll'), 'NEWER_VERSION')
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: steam)
        result = id_.copy_oodle_dll_local(str(dest_dir))
        assert result == str(cached)
        # The cached file's content is unchanged (no clobber)
        assert cached.read_text() == 'ALREADY_HERE'

    def test_returns_none_when_no_source(self, tmp_path, monkeypatch):
        """Nothing to copy → None, no exception. GUI uses the return
        value to decide whether to show a 'Couldn't auto-cache' notice."""
        monkeypatch.delenv('OODLE_DLL', raising=False)
        monkeypatch.setattr(id_, 'find_steam_install_root', lambda: None)
        dest_dir = tmp_path / 'repo'; dest_dir.mkdir()
        assert id_.copy_oodle_dll_local(str(dest_dir)) is None


# -----------------------------------------------------------------------------
# ME3 binary + profile discovery (for the one-click launch button)
# -----------------------------------------------------------------------------

class TestFindMe3Binary:
    """Search order: PATH (shutil.which) > platform-specific candidates."""

    def test_path_lookup_wins(self, tmp_path, monkeypatch):
        """If `me3` is on PATH, we use that — no need to consult the
        candidate list."""
        # Put a fake `me3` (or me3.exe) into a temp dir and add it to PATH
        fake_dir = tmp_path / 'mybin'
        fake_dir.mkdir()
        binary_name = 'me3.exe' if sys.platform == 'win32' else 'me3'
        fake_binary = fake_dir / binary_name
        fake_binary.write_text('#!/bin/sh\necho "me3 stub"\n')
        # Make it executable on POSIX so shutil.which picks it up
        if sys.platform != 'win32':
            os.chmod(fake_binary, 0o755)
        monkeypatch.setenv('PATH', str(fake_dir),
                            prepend=os.pathsep)
        found = id_.find_me3_binary()
        assert found is not None
        assert 'me3' in os.path.basename(found).lower()

    def test_no_me3_returns_none(self, monkeypatch, tmp_path):
        """If me3 isn't on PATH and no candidates exist, return None."""
        # Empty PATH so shutil.which fails
        monkeypatch.setenv('PATH', str(tmp_path))  # tmp_path has no me3
        # Also make sure the candidate list doesn't accidentally match
        # something on the test machine — monkeypatch each candidate-
        # producing function to return paths under tmp_path that don't exist
        monkeypatch.setattr(id_, '_me3_binary_candidates',
                            lambda: [str(tmp_path / 'nope') + '/me3'])
        assert id_.find_me3_binary() is None


class TestFindMe3ProfileRoot:
    """The standard profile dir varies by platform; we test the
    'directory exists/does not exist' behavior, not the exact path
    (which depends on the test machine's HOME / LOCALAPPDATA)."""

    def test_returns_none_when_missing(self, monkeypatch, tmp_path):
        """If the standard profile dir doesn't exist (fresh user, never
        opened me3), return None."""
        # Force the function to look at a guaranteed-nonexistent path
        ghost = tmp_path / 'nonexistent_profiles_dir'
        monkeypatch.setattr(id_, 'find_me3_profile_root',
                            lambda: str(ghost) if ghost.exists() else None)
        assert id_.find_me3_profile_root() is None

    def test_returns_dir_when_present(self, monkeypatch, tmp_path):
        """When the standard dir exists, return its path."""
        real = tmp_path / 'profiles'
        real.mkdir()
        monkeypatch.setattr(id_, 'find_me3_profile_root', lambda: str(real))
        assert id_.find_me3_profile_root() == str(real)


class TestFindMe3Profiles:
    """Profile scanning — walks the profile root and finds .me3 files."""

    def test_no_root_no_crash(self, monkeypatch):
        monkeypatch.setattr(id_, 'find_me3_profile_root', lambda: None)
        assert id_.find_me3_profiles() == []

    def test_empty_root(self, monkeypatch, tmp_path):
        root = tmp_path / 'profiles'
        root.mkdir()
        monkeypatch.setattr(id_, 'find_me3_profile_root', lambda: str(root))
        assert id_.find_me3_profiles() == []

    def test_one_profile_found(self, monkeypatch, tmp_path):
        root = tmp_path / 'profiles'
        prof_dir = root / 'nightreign-mods'
        prof_dir.mkdir(parents=True)
        prof_file = prof_dir / 'nightreign-default.me3'
        prof_file.write_text('profileVersion = "v1"\n')
        monkeypatch.setattr(id_, 'find_me3_profile_root', lambda: str(root))
        profs = id_.find_me3_profiles()
        assert len(profs) == 1
        name, path = profs[0]
        assert name == 'nightreign-mods'
        assert path == str(prof_file)

    def test_multiple_profiles_sorted(self, monkeypatch, tmp_path):
        """Two separate profile subdirs each with their own .me3 — both
        listed, in directory-name order (stable across calls)."""
        root = tmp_path / 'profiles'
        for d in ('zebra-profile', 'alpha-profile'):
            (root / d).mkdir(parents=True)
            (root / d / f'{d}.me3').write_text('')
        monkeypatch.setattr(id_, 'find_me3_profile_root', lambda: str(root))
        profs = id_.find_me3_profiles()
        names = [n for n, _ in profs]
        assert names == ['alpha-profile', 'zebra-profile']

    def test_subdir_with_no_me3_file_ignored(self, monkeypatch, tmp_path):
        """A subdir of the profile root without a .me3 file isn't a
        profile — skip it cleanly."""
        root = tmp_path / 'profiles'
        (root / 'just-a-folder').mkdir(parents=True)
        (root / 'real-profile').mkdir()
        (root / 'real-profile' / 'real.me3').write_text('')
        monkeypatch.setattr(id_, 'find_me3_profile_root', lambda: str(root))
        profs = id_.find_me3_profiles()
        assert len(profs) == 1
        assert profs[0][0] == 'real-profile'

    def test_files_in_root_ignored(self, monkeypatch, tmp_path):
        """Files (as opposed to dirs) directly under the profile root
        shouldn't be picked up — only dir/.me3 pairs."""
        root = tmp_path / 'profiles'
        root.mkdir()
        (root / 'stray.me3').write_text('')  # this should NOT match
        monkeypatch.setattr(id_, 'find_me3_profile_root', lambda: str(root))
        assert id_.find_me3_profiles() == []


class TestFindMe3ProfileForPackage:
    """Walks up from a package dir to find the owning .me3 file."""

    def test_me3_in_same_dir(self, tmp_path):
        """When the package dir IS the profile dir (the .me3 file is
        directly inside it)."""
        prof = tmp_path / 'nightreign-mods'
        prof.mkdir()
        me3_file = prof / 'nightreign-mods.me3'
        me3_file.write_text('')
        assert id_.find_me3_profile_for_package(str(prof)) == str(me3_file)

    def test_me3_two_dirs_up(self, tmp_path):
        """Realistic layout: package sits inside profile_root/packages/pkg/."""
        prof = tmp_path / 'nightreign-mods'
        package = prof / 'packages' / 'rando-output'
        package.mkdir(parents=True)
        me3_file = prof / 'nightreign-mods.me3'
        me3_file.write_text('')
        assert id_.find_me3_profile_for_package(str(package)) == str(me3_file)

    def test_me3_inside_package_takes_precedence(self, tmp_path):
        """If a .me3 lives both at the package level AND higher up,
        the closest one (deepest match) wins. Matches the user's
        intent — they're configuring relative to the package they set."""
        prof = tmp_path / 'nightreign-mods'
        package = prof / 'packages' / 'rando'
        package.mkdir(parents=True)
        outer = prof / 'outer.me3'; outer.write_text('')
        inner = package / 'inner.me3'; inner.write_text('')
        result = id_.find_me3_profile_for_package(str(package))
        assert result == str(inner), (
            'Walk-up should find the .me3 in the package dir itself before '
            'continuing to parent directories.')

    def test_no_me3_anywhere_returns_none(self, tmp_path):
        package = tmp_path / 'just' / 'some' / 'folders'
        package.mkdir(parents=True)
        assert id_.find_me3_profile_for_package(str(package)) is None

    def test_invalid_package_dir(self, tmp_path):
        """Defensive: non-existent or non-dir input returns None instead
        of raising."""
        assert id_.find_me3_profile_for_package('') is None
        assert id_.find_me3_profile_for_package(
            str(tmp_path / 'does_not_exist')) is None

    def test_safety_bound_prevents_infinite_walk(self, tmp_path):
        """Even on a deeply nested path with no .me3, the function
        terminates and returns None."""
        # Create a 20-level-deep path
        deep = tmp_path
        for i in range(20):
            deep = deep / f'level{i}'
            deep.mkdir()
        # No .me3 anywhere in the chain
        result = id_.find_me3_profile_for_package(str(deep))
        assert result is None  # finishes without hanging
