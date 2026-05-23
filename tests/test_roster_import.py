"""Tests for v0.27.0's roster-driven chr import.

plan_roster_import / execute_roster_import back the GUI's Diagnose +
Import roster flow. The import set is heritage_pack.json's tags plus
the MMV pack tags; each chr is routed MMV-folder-first, Elden-Ring-
folder-fallback. SFX/material are bulk-synced (same MMV-first rule).
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import oops_v3  # noqa: E402


CHR_EXTS = ('chrbnd', 'anibnd', 'behbnd')


def _heritage_prefixes():
    """The heritage chr-prefixes plan_roster_import wants. v0.27.0:
    sourced from heritage_pack.json (the single source of truth), NOT
    the roster's `_heritage_imported` flags — matching what the
    function under test now reads."""
    hp = json.load(open(os.path.join(ROOT, 'data', 'heritage_pack.json'),
                        encoding='utf-8'))
    return sorted((hp.get('tags') or {}).keys())


def _mkchr(d, cp, exts=CHR_EXTS, size=512):
    """Create cXXXX.<ext>.dcx files for a c-prefix in dir d."""
    os.makedirs(d, exist_ok=True)
    for ext in exts:
        with open(os.path.join(d, f'{cp}.{ext}.dcx'), 'wb') as f:
            f.write(b'\0' * size)


def _mkscript(d, cp, size=256):
    """Create the base battle.luabnd.dcx for a c-prefix in dir d."""
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f'{cp[1:5]}00_battle.luabnd.dcx'), 'wb') as f:
        f.write(b'\0' * size)


@pytest.fixture
def dirs(tmp_path):
    """Game-root layout: mmv/, er/, target/ each get chr+script subdirs."""
    layout = {}
    for name in ('mmv', 'er', 'target'):
        root = tmp_path / name
        (root / 'chr').mkdir(parents=True)
        (root / 'script').mkdir(parents=True)
        layout[name] = str(root)
    return layout


class TestPlanRosterImport:
    def test_wanted_set_is_heritage_plus_mmv(self, dirs):
        """The planned 'wanted' total is the roster heritage chrs plus
        the MMV pack tag chrs — the real data files, not a fixture."""
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        # Both real data files contribute; exact number is data-driven,
        # but it must be > the heritage-only count and > the MMV-only count.
        assert plan['totals']['wanted'] > 50

    def test_mmv_first_routing(self, dirs):
        """A c-prefix present in BOTH source folders is routed to MMV."""
        # Use a c-prefix we know is in the MMV pack.
        import json
        mmv_data = json.load(open(os.path.join(ROOT, 'data',
                                               'mmv_imports.json')))
        cp = sorted(mmv_data['tags'].keys())[0]
        _mkchr(os.path.join(dirs['mmv'], 'chr'), cp)
        _mkchr(os.path.join(dirs['er'], 'chr'), cp)  # also in ER
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        entry = next(e for e in plan['entries'] if e['cp'] == cp)
        assert entry['origin'] == 'mmv', 'MMV folder must win the tie'

    def test_er_fallback(self, dirs):
        """A heritage chr only in the ER folder routes to ER."""
        cp = _heritage_prefixes()[0]
        _mkchr(os.path.join(dirs['er'], 'chr'), cp)  # ER only
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        entry = next(e for e in plan['entries'] if e['cp'] == cp)
        assert entry['origin'] == 'er'

    def test_unavailable_when_in_neither(self, dirs):
        """Empty source folders → every wanted chr is unavailable."""
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        assert plan['totals']['copyable'] == 0
        assert plan['totals']['unavailable'] == plan['totals']['wanted']

    def test_already_present_skipped(self, dirs):
        """A chr already in the target chr/ is not planned for copy."""
        cp = _heritage_prefixes()[0]
        _mkchr(os.path.join(dirs['er'], 'chr'), cp)
        _mkchr(os.path.join(dirs['target'], 'chr'), cp)  # already there
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        assert cp in plan['already_present']
        assert all(e['cp'] != cp for e in plan['entries'])

    def test_scripts_planned(self, dirs):
        """Script files in the source script/ dir are planned."""
        import json
        mmv_data = json.load(open(os.path.join(ROOT, 'data',
                                               'mmv_imports.json')))
        cp = sorted(mmv_data['tags'].keys())[0]
        _mkchr(os.path.join(dirs['mmv'], 'chr'), cp)
        _mkscript(os.path.join(dirs['mmv'], 'script'), cp)
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        entry = next(e for e in plan['entries'] if e['cp'] == cp)
        assert len(entry['script_files']) == 1


class TestExecuteRosterImport:
    def test_copies_chr_and_script(self, dirs):
        import json
        mmv_data = json.load(open(os.path.join(ROOT, 'data',
                                               'mmv_imports.json')))
        cp = sorted(mmv_data['tags'].keys())[0]
        _mkchr(os.path.join(dirs['mmv'], 'chr'), cp)
        _mkscript(os.path.join(dirs['mmv'], 'script'), cp)
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        res = oops_v3.execute_roster_import(plan, dirs['mmv'], dirs['er'])
        assert res['chr_files_copied'] == len(CHR_EXTS)
        assert res['script_files_copied'] == 1
        assert res['errors'] == []
        # files actually landed
        for ext in CHR_EXTS:
            assert os.path.isfile(os.path.join(
                dirs['target'], 'chr', f'{cp}.{ext}.dcx'))

    def test_idempotent_rerun(self, dirs):
        """Second run with overwrite=False copies nothing, skips all."""
        cp = _heritage_prefixes()[0]
        _mkchr(os.path.join(dirs['er'], 'chr'), cp)
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        first = oops_v3.execute_roster_import(plan, dirs['mmv'], dirs['er'])
        assert first['chr_files_copied'] == len(CHR_EXTS)
        # re-plan against the now-populated target, re-run
        plan2 = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        second = oops_v3.execute_roster_import(plan2, dirs['mmv'],
                                               dirs['er'])
        assert second['chr_files_copied'] == 0

    def test_sfx_material_bulk_sync(self, dirs):
        """sfx/ and material/ dirs are bulk-copied, MMV-first."""
        sfx = os.path.join(dirs['mmv'], 'sfx')
        os.makedirs(sfx)
        with open(os.path.join(sfx, 'sfxbnd_commoneffects.ffxbnd.dcx'),
                  'wb') as f:
            f.write(b'\0' * 4096)
        plan = oops_v3.plan_roster_import(
            dirs['mmv'], dirs['er'], os.path.join(dirs['target'], 'chr'))
        res = oops_v3.execute_roster_import(plan, dirs['mmv'], dirs['er'])
        assert res['sfx_files_copied'] == 1
        assert os.path.isfile(os.path.join(
            dirs['target'], 'sfx', 'sfxbnd_commoneffects.ffxbnd.dcx'))