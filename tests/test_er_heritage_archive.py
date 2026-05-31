"""Tests for reading Elden Ring heritage assets straight from the ER archives
(er_keys / er_chr_manifest / er_source) and the --source-game wiring in the two
heritage import dev-tools.

No real ER install is needed: the archive layer (data_archive.DataArchive) is
replaced with an in-memory fake, and the manifest-driven enumeration runs against
the real er_chr_manifest.json. The one thing only a real install can confirm —
that the embedded ER keys decrypt the actual .bhd/.bdt — is covered separately by
`er_source.py --validate`; here we prove every layer above the raw read.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "dev")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def er_archive(monkeypatch):
    """Replace data_archive.DataArchive with an in-memory fake. The returned dict
    is the archive's contents: fill it with {'/chr/cXXXX...': bytes} and any
    EldenRingSource built afterwards reads from it. has_archive is True iff the
    dict is non-empty (mirrors the real 'indexed > 0 files' check)."""
    import data_archive
    store = {}

    class FakeArchive:
        def __init__(self, game_dir, keys=None, archives=None):
            self.game_dir, self.keys, self.archives = game_dir, keys, archives

        def __len__(self):
            return len(store)

        def get(self, path):
            if path in store:
                return store[path]
            raise KeyError(path)

    monkeypatch.setattr(data_archive, "DataArchive", FakeArchive)
    return store


def _fill_from_manifest(store, prefixes, kinds=("chr",)):
    """Populate the fake archive with the real manifest paths for these prefixes."""
    import er_source
    src = er_source.EldenRingSource(None)  # manifest-only, no archive
    rels = src.files_for_prefixes(prefixes, kinds=kinds)
    for rel in rels:
        store[rel] = b"DATA:" + rel.encode()
    return rels


# ---------------------------------------------------------------- keys + manifest

def test_er_keys_all_parse():
    from data_archive import parse_rsa_public_key_pem
    from er_keys import ELDEN_RING_KEYS, ELDEN_RING_ARCHIVES
    assert set(ELDEN_RING_ARCHIVES) <= set(ELDEN_RING_KEYS)
    assert {"Data0", "Data1", "Data2", "Data3", "DLC"} <= set(ELDEN_RING_KEYS)
    for name, pem in ELDEN_RING_KEYS.items():
        modulus, exp = parse_rsa_public_key_pem(pem)
        assert modulus.bit_length() == 2048, f"{name} not 2048-bit"
        assert exp > 1


def test_manifest_has_chr_script_sfx():
    from er_source import load_manifest
    m = load_manifest()
    assert len(m["chr"]) > 1000
    assert len(m["script"]) > 100
    assert len(m["sfx"]) > 50


def test_files_for_prefixes_catches_phase_and_texture_banks():
    import er_source
    src = er_source.EldenRingSource(None)
    files = src.files_for_prefixes(["c5210"])  # Divine Beast Dancing Lion
    assert "/chr/c5210.chrbnd.dcx" in files
    assert "/chr/c5210.anibnd.dcx" in files
    assert "/chr/c5210.behbnd.dcx" in files
    # variable banks an unpacked-dir glob would catch but a hash index cannot enumerate:
    assert "/chr/c5210_div00.anibnd.dcx" in files
    assert "/chr/c5210_div01.anibnd.dcx" in files
    assert "/chr/c5210_h.texbnd.dcx" in files
    # the validated script + its sfx bundle:
    assert "/script/521000_battle.luabnd.dcx" in files
    assert "/sfx/sfxbnd_c5210.ffxbnd.dcx" in files


def test_kinds_filter():
    import er_source
    src = er_source.EldenRingSource(None)
    only_chr = src.files_for_prefixes(["c5210"], kinds=("chr",))
    assert only_chr and all(p.startswith("/chr/") for p in only_chr)
    only_script = src.files_for_prefixes(["c5210"], kinds=("script",))
    assert only_script and all(p.startswith("/script/") for p in only_script)


# -------------------------------------------------------------- EldenRingSource

def test_read_archive_first_then_loose(er_archive, tmp_path):
    import er_source
    er_archive["/chr/c5210.chrbnd.dcx"] = b"ARCHIVE"
    loose_chr = tmp_path / "chr"
    loose_chr.mkdir()
    (loose_chr / "c5210_div00.anibnd.dcx").write_bytes(b"LOOSE")
    src = er_source.EldenRingSource("FAKE_ER_GAME", loose_chr_dir=str(loose_chr))
    assert src.has_archive
    assert src.read("chr/c5210.chrbnd.dcx") == b"ARCHIVE"          # archive hit
    assert src.read("/chr/c5210_div00.anibnd.dcx") == b"LOOSE"     # miss -> loose fallback
    with pytest.raises(KeyError):
        src.read("chr/c9999.chrbnd.dcx")                          # neither


def test_no_game_dir_degrades():
    import er_source
    assert er_source.EldenRingSource(None).has_archive is False


def test_materialize_preserves_layout(er_archive, tmp_path):
    import er_source
    er_archive["/chr/c5210.chrbnd.dcx"] = b"C"
    er_archive["/script/521000_battle.luabnd.dcx"] = b"S"
    er_archive["/sfx/sfxbnd_c5210.ffxbnd.dcx"] = b"F"
    src = er_source.EldenRingSource("FAKE")
    dest = tmp_path / "cache"
    n_ok, failed = src.materialize(
        ["/chr/c5210.chrbnd.dcx", "/script/521000_battle.luabnd.dcx",
         "/sfx/sfxbnd_c5210.ffxbnd.dcx", "/chr/c9999.chrbnd.dcx"], dest)
    assert (dest / "chr" / "c5210.chrbnd.dcx").read_bytes() == b"C"
    assert (dest / "script" / "521000_battle.luabnd.dcx").read_bytes() == b"S"
    assert (dest / "sfx" / "sfxbnd_c5210.ffxbnd.dcx").read_bytes() == b"F"
    assert n_ok == 3 and failed == ["chr/c9999.chrbnd.dcx"]


# ----------------------------------------------- heritage_chr_import --source-game

def test_chr_import_materializes_requested_and_carrier(er_archive, tmp_path):
    """Requesting a dependent (c4311) must also pull its anim carrier (c4310,
    an anibnd-only chr), or it T-poses in-game."""
    import heritage_chr_import as hci
    _fill_from_manifest(er_archive, ["c4311", "c4310"], kinds=("chr",))
    cache = tmp_path / "ercache"
    chr_dir = hci._materialize_er_for_import(
        ["c4311"], "FAKE_ER_GAME", cache_root=str(cache))
    assert chr_dir and os.path.isdir(chr_dir)
    names = os.listdir(chr_dir)
    assert any(n.startswith("c4311.") for n in names), "dependent not materialized"
    assert any(n.startswith("c4310.") for n in names), "carrier c4310 missing"


def test_carrier_cache_satisfies_real_build_carrier_map(er_archive, tmp_path):
    """The materialized cache must satisfy the importer's OWN carrier detection:
    build_carrier_map(cache) should resolve c4311 -> c4310."""
    import heritage_chr_import as hci
    from chr_asset_resolver import build_carrier_map
    _fill_from_manifest(er_archive, ["c4311", "c4310"], kinds=("chr",))
    cache = tmp_path / "ercache"
    chr_dir = hci._materialize_er_for_import(
        ["c4311"], "FAKE_ER_GAME", cache_root=str(cache))
    cmap = build_carrier_map(chr_dir)  # no regulation -> family heuristic
    assert "c4311" in cmap, "build_carrier_map didn't see the dependent"
    assert cmap["c4311"]["carrier"] == "c4310"


def test_chr_import_returns_none_when_archive_unopenable(er_archive, tmp_path):
    # empty store -> FakeArchive len 0 -> has_archive False -> helper returns None
    import heritage_chr_import as hci
    assert hci._materialize_er_for_import(
        ["c4311"], "FAKE_ER_GAME", cache_root=str(tmp_path / "x")) is None


# -------------------------------------------- import_heritage_ai_scripts --source-game

def test_scripts_import_materializes_plan_luabnds(er_archive, tmp_path):
    import import_heritage_ai_scripts as ias
    # two known IMPORT_PLAN scripts present in the (fake) ER archives:
    er_archive["/script/521000_battle.luabnd.dcx"] = b"L1"   # c5210 (validated)
    er_archive["/script/504000_battle.luabnd.dcx"] = b"L2"   # c5040
    cache = tmp_path / "ercache"
    script_dir = ias._materialize_er_scripts("FAKE_ER_GAME", cache_root=str(cache))
    assert script_dir and os.path.isdir(script_dir)
    got = set(os.listdir(script_dir))
    assert "521000_battle.luabnd.dcx" in got
    assert "504000_battle.luabnd.dcx" in got


def test_scripts_import_returns_none_when_archive_unopenable(er_archive, tmp_path):
    import import_heritage_ai_scripts as ias
    assert ias._materialize_er_scripts(
        "FAKE_ER_GAME", cache_root=str(tmp_path / "x")) is None
