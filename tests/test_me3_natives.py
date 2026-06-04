"""Tests for me3_profile.build_me3_text / write_profile_me3 (v0.30 DLL natives).

The DLL-mods feature lets the shipped profile launch the rando alongside DLL
mods like SeamlessCoop's nrsc.dll, by writing one [[natives]] block per
configured DLL into the profile's own .me3. These lock the generator format
and the regenerate-not-append semantics that make removal work.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import me3_profile as m  # noqa: E402


class TestBuildMe3Text:
    def test_minimal_profile_shape(self):
        t = m.build_me3_text('package/')
        assert 'profileVersion = "v1"' in t
        assert '[[supports]]' in t          # array-of-tables, not [supports]
        assert 'game = "nightreign"' in t
        assert '[[packages]]' in t
        assert "path = 'package/'" in t     # single-quoted

    def test_package_id_optional(self):
        assert 'id = ' not in m.build_me3_text('package/')
        assert 'id = "rando"' in m.build_me3_text('package/', package_id='rando')

    def test_no_natives_block_when_empty(self):
        assert '[[natives]]' not in m.build_me3_text('package/', natives=[])

    def test_one_natives_block_per_dll(self):
        t = m.build_me3_text('package/', natives=[
            r'C:\SeamlessCoop\nrsc.dll', r'D:\mods\other.dll'])
        assert t.count('[[natives]]') == 2
        # backslashes folded to forward slashes, single-quoted
        assert "path = 'C:/SeamlessCoop/nrsc.dll'" in t
        assert "path = 'D:/mods/other.dll'" in t
        assert '\\' not in t  # no raw backslashes leak into the TOML

    def test_blank_and_comment_natives_skipped(self):
        t = m.build_me3_text('package/', natives=['', '   ', 'C:/a/x.dll'])
        assert t.count('[[natives]]') == 1

    def test_savefile_optional(self):
        assert 'savefile' not in m.build_me3_text('package/')
        assert 'savefile = "NR_rando.sl2"' in m.build_me3_text(
            'package/', savefile='NR_rando.sl2')

    def test_header_lines_commented(self):
        t = m.build_me3_text('package/', header_lines=['hello', '', 'world'])
        assert t.startswith('# hello')
        assert '# world' in t


class TestWriteProfileMe3:
    def test_writes_file(self, tmp_path):
        p = tmp_path / 'prof' / 'x.me3'
        res = m.write_profile_me3(str(p), 'package/',
                                  natives=['C:/sc/nrsc.dll'])
        assert res['action'] == 'written'
        assert res['natives'] == 1
        assert p.is_file()
        assert "[[natives]]" in p.read_text(encoding='utf-8')

    def test_regenerate_supports_removal(self, tmp_path):
        # The whole point of regenerating (vs appending): removing a DLL from
        # the list removes it from the .me3 on the next write.
        p = tmp_path / 'x.me3'
        m.write_profile_me3(str(p), 'package/',
                            natives=['C:/sc/nrsc.dll', 'C:/m/two.dll'])
        assert p.read_text(encoding='utf-8').count('[[natives]]') == 2
        m.write_profile_me3(str(p), 'package/', natives=['C:/sc/nrsc.dll'])
        txt = p.read_text(encoding='utf-8')
        assert txt.count('[[natives]]') == 1
        assert 'two.dll' not in txt

    def test_regenerate_to_zero_natives(self, tmp_path):
        p = tmp_path / 'x.me3'
        m.write_profile_me3(str(p), 'package/', natives=['C:/sc/nrsc.dll'])
        m.write_profile_me3(str(p), 'package/', natives=[])
        assert '[[natives]]' not in p.read_text(encoding='utf-8')
