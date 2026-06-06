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


class TestEnsureSupportsNightreign:
    """Append-only [[supports]] insertion for a user-authored profile."""

    def _write(self, tmp_path, text):
        p = tmp_path / 'prof.me3'
        p.write_text(text, encoding='utf-8')
        return str(p)

    def test_appends_when_absent(self, tmp_path):
        p = self._write(tmp_path,
            'profileVersion = "v1"\n\n[[packages]]\npath = \'mymod/\'\n')
        assert m.supports_nightreign(p) is False
        res = m.ensure_supports_nightreign(p)
        assert res['action'] == 'added'
        assert m.supports_nightreign(p) is True
        body = open(p, encoding='utf-8').read()
        assert '[[supports]]' in body and 'game = "nightreign"' in body

    def test_noop_when_present(self, tmp_path):
        p = self._write(tmp_path,
            'profileVersion = "v1"\n\n[[supports]]\ngame = "nightreign"\n'
            '\n[[packages]]\npath = \'mymod/\'\n')
        before = open(p, encoding='utf-8').read()
        assert m.ensure_supports_nightreign(p)['action'] == 'noop'
        assert open(p, encoding='utf-8').read() == before  # untouched

    def test_append_only_preserves_existing(self, tmp_path):
        # A hand-authored profile with a package + a DLL native.
        original = ('profileVersion = "v1"\n\n[[packages]]\n'
                    "path = 'seamless/'\n\n[[natives]]\n"
                    "path = 'C:/SeamlessCoop/nrsc.dll'\n")
        p = self._write(tmp_path, original)
        assert m.ensure_supports_nightreign(p)['action'] == 'added'
        body = open(p, encoding='utf-8').read()
        assert body.startswith(original)          # nothing rewritten
        assert "path = 'C:/SeamlessCoop/nrsc.dll'" in body
        assert m.supports_nightreign(p) is True

    def test_error_when_missing(self, tmp_path):
        assert m.ensure_supports_nightreign(
            str(tmp_path / 'nope.me3'))['action'] == 'error'

    def test_variant_game_name_is_noop(self, tmp_path):
        # _NR_GAME_NAMES includes 'nr' — recognised, not duplicated.
        p = self._write(tmp_path,
            'profileVersion = "v1"\n\n[[supports]]\ngame = "nr"\n')
        assert m.ensure_supports_nightreign(p)['action'] == 'noop'
