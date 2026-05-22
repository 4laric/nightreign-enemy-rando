"""Tests for chr_asset_resolver.py (v0.24.86 deploy-side track).

Synthetic-fixture approach: each test builds a minimal NR / ER / MMV /
target directory tree with empty files at the relevant paths, runs
the resolver, asserts the status the rubric predicts.

Why synthetic fixtures: real installs are 10s of GB and not available
in CI. The resolver is dependency-free stdlib and the FILE_CLASSES
templates encode the entire rubric — synthetic dirs are a complete
test surface for the resolver's logic.
"""
import json
import os
import sys

import pytest

# Add the staged resolver to path so we can import it.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_STAGED = os.path.join(_REPO, 'dev')
sys.path.insert(0, _STAGED)

# Importing happens at module load — surfaces SYNTAX errors fast.
import chr_asset_resolver as car  # noqa: E402


# ---------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------

def _touch(path, size=0):
    """Create an empty (or N-byte) file, including parents."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        if size:
            f.write(b'\0' * size)


def _build_install(root, subdirs=('chr', 'script', 'sfx', 'material')):
    """Create an empty install root with the standard subdirs."""
    for s in subdirs:
        os.makedirs(os.path.join(root, s), exist_ok=True)
    return root


def _write_manifest(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(content, f)


# ---------------------------------------------------------------------
# build_roster — precedence and source-tag resolution
# ---------------------------------------------------------------------

class TestBuildRosterPrecedence:

    def test_blocklist_wins_over_all(self, tmp_path):
        """Handoff line 128: missing_chr_files > mmv > heritage > tags.
        Test target: a chr listed in BOTH mmv_imports and missing_chr_files
        should resolve to 'skip', not 'mmv'."""
        nr = str(tmp_path / 'nr_tags.json')
        mmv = str(tmp_path / 'mmv.json')
        hp = str(tmp_path / 'hp.json')
        mc = str(tmp_path / 'missing.json')
        _write_manifest(nr, {'c5840': {'_source': 'mmv'}})
        _write_manifest(mmv, {'_meta': {'enabled': True},
                              'tags': {'c5840': {}}})
        _write_manifest(hp, {'tags': {}})
        _write_manifest(mc, {'missing_chrs': {'c5840': 'reason'}})
        roster = car.build_roster(nr, mmv, hp, mc)
        assert roster.get('c5840') == 'skip', (
            f'blocklist precedence broken; got {roster.get("c5840")}')

    def test_mmv_wins_over_heritage(self, tmp_path):
        """When a chr appears in BOTH mmv_imports and heritage_pack
        (and isn't blocklisted), expected_source should be 'mmv'."""
        nr = str(tmp_path / 'nr_tags.json')
        mmv = str(tmp_path / 'mmv.json')
        hp = str(tmp_path / 'hp.json')
        mc = str(tmp_path / 'missing.json')
        _write_manifest(nr, {})
        _write_manifest(mmv, {'_meta': {'enabled': True},
                              'tags': {'c5840': {}}})
        _write_manifest(hp, {'tags': {'c5840': {}}})
        _write_manifest(mc, {})
        roster = car.build_roster(nr, mmv, hp, mc)
        assert roster.get('c5840') == 'mmv'

    def test_mmv_disabled_falls_through_to_heritage(self, tmp_path):
        """_meta.enabled=false should cause mmv_imports to be ignored
        entirely (heritage assignment wins)."""
        nr = str(tmp_path / 'nr_tags.json')
        mmv = str(tmp_path / 'mmv.json')
        hp = str(tmp_path / 'hp.json')
        mc = str(tmp_path / 'missing.json')
        _write_manifest(nr, {})
        _write_manifest(mmv, {'_meta': {'enabled': False},
                              'tags': {'c5840': {}}})
        _write_manifest(hp, {'tags': {'c5840': {}}})
        _write_manifest(mc, {})
        roster = car.build_roster(nr, mmv, hp, mc)
        assert roster.get('c5840') == 'er'

    def test_heritage_wins_over_nr_catalog(self, tmp_path):
        """A chr in heritage_pack should resolve to 'er' even if its
        nr_enemy_tags entry exists."""
        nr = str(tmp_path / 'nr_tags.json')
        mmv = str(tmp_path / 'mmv.json')
        hp = str(tmp_path / 'hp.json')
        mc = str(tmp_path / 'missing.json')
        _write_manifest(nr, {'c4500': {'_source': 'nr'}})
        _write_manifest(mmv, {'_meta': {'enabled': True}, 'tags': {}})
        _write_manifest(hp, {'tags': {'c4500': {}}})
        _write_manifest(mc, {})
        roster = car.build_roster(nr, mmv, hp, mc)
        assert roster.get('c4500') == 'er'

    def test_blocklist_handles_list_and_dict_shapes(self, tmp_path):
        """missing_chr_files entries can be dict (cp -> reason) or
        list of strings or list of dicts with c_prefix. Resolver
        should handle all three shapes."""
        nr = str(tmp_path / 'nr_tags.json')
        mmv = str(tmp_path / 'mmv.json')
        hp = str(tmp_path / 'hp.json')
        mc = str(tmp_path / 'missing.json')
        _write_manifest(nr, {})
        _write_manifest(mmv, {'_meta': {'enabled': True}, 'tags': {}})
        _write_manifest(hp, {'tags': {}})
        _write_manifest(mc, {
            'missing_chrs': {'c1000': 'a'},
            'broken_runtime_chrs': ['c2000',
                                    {'c_prefix': 'c3000', 'note': 'x'}],
        })
        roster = car.build_roster(nr, mmv, hp, mc)
        for cp in ('c1000', 'c2000', 'c3000'):
            assert roster.get(cp) == 'skip', f'{cp} not skipped'


# ---------------------------------------------------------------------
# check_chr — file-class resolution per c-prefix
# ---------------------------------------------------------------------

class TestCheckChrSatisfaction:

    def test_nr_chr_satisfied_by_nr_install(self, tmp_path):
        """Handoff line 82: NR-source chrs are satisfied if present in
        target OR NR install (engine reads NR install as me3 fallthrough).
        With files only in NR install: OK status, no copies needed."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr)
        _build_install(target)
        # Put the three REQUIRED chr files in NR install
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        # AI scripts and FFX in NR install too
        for n in ('435000_battle.luabnd.dcx', '435000_logic.luabnd.dcx'):
            _touch(os.path.join(nr, 'script', n))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c4350.ffxbnd.dcx'))
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        assert r['worst_status'] == 'OK', (
            f'nr-source chr with files in nr install should be OK; '
            f'got {r["worst_status"]}, findings: {r["findings"]}')

    def test_er_chr_in_er_install_only_is_copyable_not_ok(self, tmp_path):
        """Handoff line 83: ER and MMV chrs MUST be in target — found-
        only-in-source = COPYABLE. ER-source chr with files only in ER
        install should report COPYABLE worst_status (and copy actions
        for the import flow to act on)."""
        er = str(tmp_path / 'er')
        target = str(tmp_path / 'target')
        _build_install(er)
        _build_install(target)
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(er, 'chr', f'c2110.{ext}.dcx'))
        for n in ('211000_battle.luabnd.dcx', '211000_logic.luabnd.dcx'):
            _touch(os.path.join(er, 'script', n))
        _touch(os.path.join(er, 'sfx', 'sfxbnd_c2110.ffxbnd.dcx'))
        r = car.check_chr('c2110', 'er',
                          {'nr': None, 'er': er, 'mmv': None}, target)
        assert r['worst_status'] == 'COPYABLE'
        copyable = [f for f in r['findings'] if f['status'] == 'COPYABLE']
        assert copyable, 'should have at least one COPYABLE finding'
        # Every COPYABLE should be from 'er' since that's the only source
        assert all(f['from'] == 'er' for f in copyable)

    def test_missing_required_is_missing_status(self, tmp_path):
        """Handoff line 71: missing REQUIRED chr/ files = spawn-time CTD.
        worst_status should be MISSING when chrbnd/anibnd/behbnd absent
        from all sources."""
        target = str(tmp_path / 'target')
        _build_install(target)
        r = car.check_chr('c9999', 'nr',
                          {'nr': None, 'er': None, 'mmv': None}, target)
        assert r['worst_status'] == 'MISSING'
        missing_required = [
            f for f in r['findings']
            if f['status'] == 'MISSING' and f['severity'] == 'REQUIRED'
        ]
        assert len(missing_required) == 3, (
            'expected 3 REQUIRED missing (chrbnd, anibnd, behbnd); '
            f'got {len(missing_required)}')

    def test_combat_ffx_miss_promotes_to_missing(self, tmp_path):
        """Handoff line 71-72: COMBAT_FFX is a hard severity (first-
        action CTD profile of c5840/c5880/c6201). If chr files present
        but sfx is missing everywhere, worst_status is still MISSING."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr)
        _build_install(target)
        # REQUIRED + AI_REQUIRED satisfied
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c5840.{ext}.dcx'))
        for n in ('584000_battle.luabnd.dcx', '584000_logic.luabnd.dcx'):
            _touch(os.path.join(nr, 'script', n))
        # sfx absent — COMBAT_FFX miss
        r = car.check_chr('c5840', 'mmv',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        # mmv-source: not satisfied by NR install, sfx is also missing.
        # Multiple failure modes simultaneously; worst should be MISSING
        # because of the sfx COMBAT_FFX class (or REQUIRED for the chr
        # files, which is also hard severity — either qualifies).
        assert r['worst_status'] == 'MISSING', (
            f'expected MISSING (hard-severity miss); got '
            f'{r["worst_status"]}, findings: {r["findings"]}')
        has_ffx_missing = any(
            f['status'] == 'MISSING' and f['severity'] == 'COMBAT_FFX'
            for f in r['findings'])
        assert has_ffx_missing, (
            'COMBAT_FFX miss should be present in findings — that\'s '
            'the c5840/c5880/c6201 attribution profile')

    def test_recommended_miss_does_not_promote_to_hard(self, tmp_path):
        """Handoff: RECOMMENDED is soft (texbnd → magenta checker, not
        CTD). Missing texbnd shouldn't flip worst_status beyond OK if
        all hard deps are satisfied."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr)
        _build_install(target)
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        for n in ('435000_battle.luabnd.dcx', '435000_logic.luabnd.dcx'):
            _touch(os.path.join(nr, 'script', n))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c4350.ffxbnd.dcx'))
        # texbnd absent everywhere — should be MISSING-recommended
        # but worst_status should stay OK (only hard severities promote)
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        assert r['worst_status'] == 'OK', (
            f'RECOMMENDED miss promoted to {r["worst_status"]}; expected '
            f'OK')
        # Soft miss IS present in findings
        recommended_missing = [
            f for f in r['findings']
            if f['status'] == 'MISSING' and f['severity'] == 'RECOMMENDED']
        assert recommended_missing, 'texbnd misses should still be tracked'

    def test_optional_miss_is_silent(self, tmp_path):
        """OPTIONAL (e.g. _aNN extra anim banks) should NOT even produce
        a MISSING finding — they're conditionally present per chr."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr)
        _build_install(target)
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        for n in ('435000_battle.luabnd.dcx', '435000_logic.luabnd.dcx'):
            _touch(os.path.join(nr, 'script', n))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c4350.ffxbnd.dcx'))
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        # No _aNN.anibnd.dcx files — should be no findings for those
        optional = [f for f in r['findings']
                    if f['severity'] == 'OPTIONAL'
                    and f['status'] == 'MISSING']
        assert not optional, (
            f'OPTIONAL misses should be silent, got {optional}')

    def test_target_takes_priority_over_source(self, tmp_path):
        """If a file is in BOTH target and source, target wins (engine
        reads from target first). Finding should be PRESENT/target."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr)
        _build_install(target)
        # Put chrbnd in both places
        _touch(os.path.join(nr,     'chr', 'c4350.chrbnd.dcx'))
        _touch(os.path.join(target, 'chr', 'c4350.chrbnd.dcx'))
        # Other required files only in NR (so worst_status stays OK)
        for ext in ('anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        for n in ('435000_battle.luabnd.dcx', '435000_logic.luabnd.dcx'):
            _touch(os.path.join(nr, 'script', n))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c4350.ffxbnd.dcx'))
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        # Find the chrbnd finding
        chrbnd = next(f for f in r['findings']
                      if f['pattern'] == 'c4350.chrbnd.dcx')
        assert chrbnd['status'] == 'PRESENT'
        assert chrbnd['location'] == 'target', (
            f'target should win over nr; got location={chrbnd["location"]}')


# ---------------------------------------------------------------------
# check_shared — aicommon + material/
# ---------------------------------------------------------------------

class TestCheckShared:

    def test_aicommon_size_difference_visible(self, tmp_path):
        """Handoff #4: aicommon size is diagnostic. ~75KB = vanilla NR
        (cross-game freezes), ~135KB = MMV-superset (works).
        check_shared should expose the target_size and copyable sizes
        so callers can warn on the small variant."""
        nr = str(tmp_path / 'nr')
        mmv = str(tmp_path / 'mmv')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(mmv); _build_install(target)
        _touch(os.path.join(nr,  'script', 'aicommon.luabnd.dcx'), size=75_000)
        _touch(os.path.join(mmv, 'script', 'aicommon.luabnd.dcx'), size=135_000)
        _touch(os.path.join(target, 'script', 'aicommon.luabnd.dcx'), size=75_000)
        result = car.check_shared(
            {'nr': nr, 'er': None, 'mmv': mmv}, target)
        ac = next(s for s in result if s.get('filename') == 'aicommon.luabnd.dcx')
        assert ac['status'] == 'PRESENT'
        assert ac['target_size'] == 75_000
        sizes_by_label = {c['label']: c['size'] for c in ac['copyable_from']}
        assert sizes_by_label.get('mmv') == 135_000
        assert sizes_by_label.get('nr') == 75_000

    def test_material_directory_level_check(self, tmp_path):
        """Handoff #5: material/ is dir-level, not per-chr.
        Any file in target/material satisfies the check."""
        target = str(tmp_path / 'target')
        _build_install(target)
        _touch(os.path.join(target, 'material', 'any.mtdbnd.dcx'))
        result = car.check_shared(
            {'nr': None, 'er': None, 'mmv': None}, target)
        mat = next(s for s in result if s['subdir'] == 'material/')
        assert mat['status'] == 'PRESENT'

    def test_empty_material_is_missing(self, tmp_path):
        """Empty target/material AND no sources with material →
        MISSING. Doc field surfaces the rationale."""
        target = str(tmp_path / 'target')
        _build_install(target)
        # material dir exists but is empty
        result = car.check_shared(
            {'nr': None, 'er': None, 'mmv': None}, target)
        mat = next(s for s in result if s['subdir'] == 'material/')
        assert mat['status'] == 'MISSING'


# ---------------------------------------------------------------------
# worse_status — minor but load-bearing
# ---------------------------------------------------------------------

@pytest.mark.parametrize('a,b,expected', [
    ('OK', 'OK', 'OK'),
    ('OK', 'COPYABLE', 'COPYABLE'),
    ('COPYABLE', 'OK', 'COPYABLE'),
    ('OK', 'MISSING', 'MISSING'),
    ('COPYABLE', 'MISSING', 'MISSING'),
    ('MISSING', 'COPYABLE', 'MISSING'),
    ('MISSING', 'MISSING', 'MISSING'),
])
def test_worse_status(a, b, expected):
    assert car.worse_status(a, b) == expected


# ---------------------------------------------------------------------
# Integration smoke — multi-chr roster + import-plan shape
# ---------------------------------------------------------------------
#
# v0.26.x: `test_roster_to_plan_end_to_end` removed. The test exercised
# a `heritage_chr_import.plan_roster_import` higher-level function that
# no longer exists — the script was refactored to a CLI-only `main()`
# entrypoint, and the planning is now done via `chr_asset_resolver`'s
# `build_roster()` + `check_chr()` + `worse_status()` building blocks.
# All three building blocks have their own dedicated test classes
# above (TestBuildRosterPrecedence, TestCheckChrSatisfaction,
# test_worse_status), so the coverage isn't lost — just spread across
# the component tests instead of in one integration smoke.


# ---------------------------------------------------------------------
# v0.24.86-patch1: NR convention fixes
# ---------------------------------------------------------------------

class TestNrFilenameConventions:
    """Verified against an UXM-unpacked NR install. Scripts use
    numeric IDs with leading zeros + 2-char variant (e.g. c4350 →
    435000_battle.luabnd.dcx). SFX uses sfxbnd_{cp}.ffxbnd.dcx exact
    naming. Chr files use {cp}.{chrbnd,anibnd,behbnd}.dcx as before."""

    def test_nr_script_variant_00_matches(self, tmp_path):
        """The default variant (00) is the common case. c4350 →
        435000_battle.luabnd.dcx must be findable."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        # Just place the AI script — confirms the resolver finds it
        _touch(os.path.join(nr, 'script', '435000_battle.luabnd.dcx'))
        # Required chr files + sfx to avoid clouding the test
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c4350.ffxbnd.dcx'))
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        ai = [f for f in r['findings'] if f['severity'] == 'AI_BATTLE']
        assert ai and ai[0]['status'] == 'PRESENT', (
            f'expected PRESENT for 435000_battle.luabnd.dcx, got '
            f'{[f["status"] for f in ai]}')

    def test_nr_script_non_zero_variant_matches(self, tmp_path):
        """Non-default variant: c0120 → 012010_battle.luabnd.dcx
        (variant 10 — confirmed in Alaric's actual install)."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        _touch(os.path.join(nr, 'script', '012010_battle.luabnd.dcx'))
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c0120.{ext}.dcx'))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c0120.ffxbnd.dcx'))
        r = car.check_chr('c0120', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        ai_battle = [f for f in r['findings']
                     if f['severity'] == 'AI_BATTLE']
        assert ai_battle and ai_battle[0]['status'] == 'PRESENT', (
            f'variant 10 should match 0120??_battle glob; got '
            f'{[f["status"] for f in ai_battle]}')

    def test_old_er_pattern_does_not_match(self, tmp_path):
        """Regression guard: cXXXX_battle.luabnd.dcx (ER convention,
        what the original handoff rubric used) must NOT match in NR.
        If it did, the bug Alaric hit wouldn't have been a bug —
        confirms we're really checking the new pattern."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        # Drop the OLD-convention file shape; resolver should NOT find it
        _touch(os.path.join(nr, 'script', 'c4350_battle.luabnd.dcx'))
        _touch(os.path.join(nr, 'script', 'c4350_logic.luabnd.dcx'))
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c4350.ffxbnd.dcx'))
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        # Both AI findings should report MISSING because the resolver
        # is looking for the NR-pattern 4350??_*.luabnd.dcx
        ai = [f for f in r['findings']
              if f['severity'] in car._AI_SEVERITIES]
        assert all(f['status'] == 'MISSING' for f in ai), (
            f'old c-prefix-style names should not satisfy NR pattern; '
            f'got {[(f["pattern"], f["status"]) for f in ai]}')

    def test_sfx_exact_sfxbnd_prefix(self, tmp_path):
        """sfxbnd_{cp}.ffxbnd.dcx is the exact match. The old
        substring glob *{cp}*.ffxbnd.dcx would accidentally match
        files like 'f000043500.ffxbnd.dcx' (numeric IDs containing
        the digits) — this test confirms we use exact prefix."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        # Drop a file that would have matched the old substring glob
        # but does NOT match the new exact-prefix pattern.
        _touch(os.path.join(nr, 'sfx', 'f435000.ffxbnd.dcx'))
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        _touch(os.path.join(nr, 'script', '435000_battle.luabnd.dcx'))
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        ffx = [f for f in r['findings'] if f['severity'] == 'COMBAT_FFX']
        assert ffx and ffx[0]['status'] == 'MISSING', (
            f"substring-matching file 'f435000.ffxbnd.dcx' should NOT "
            f"satisfy sfxbnd_c4350.ffxbnd.dcx pattern; got "
            f"{[f['status'] for f in ffx]}")


class TestAiUnionRule:
    """v0.24.86-patch1: a chr is AI-functional if EITHER _battle OR
    _logic exists. NR's actual data has many chrs with only one of
    the pair (e.g. c0100 has 010000_logic but no 010000_battle)."""

    def test_battle_only_chr_is_ok(self, tmp_path):
        """Chr with only _battle (no _logic) should NOT be flagged as
        AI-missing. Mirrors c0120 in Alaric's actual install
        (012010_battle.luabnd.dcx exists, no 012010_logic)."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        _touch(os.path.join(nr, 'script', '012010_battle.luabnd.dcx'))
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c0120.{ext}.dcx'))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c0120.ffxbnd.dcx'))
        r = car.check_chr('c0120', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        assert r['worst_status'] == 'OK', (
            f'battle-only chr should be OK via union rule; got '
            f'{r["worst_status"]}')
        # The missing logic finding should be marked NOT_NEEDED
        logic = [f for f in r['findings'] if f['severity'] == 'AI_LOGIC']
        assert logic and logic[0]['status'] == 'NOT_NEEDED', (
            f'missing AI_LOGIC sibling should be downgraded to '
            f'NOT_NEEDED; got {logic}')

    def test_logic_only_chr_is_ok(self, tmp_path):
        """Inverse: chr with only _logic should also be OK
        (mirrors c0100 → 010000_logic.luabnd.dcx in Alaric's install)."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        _touch(os.path.join(nr, 'script', '010000_logic.luabnd.dcx'))
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c0100.{ext}.dcx'))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c0100.ffxbnd.dcx'))
        r = car.check_chr('c0100', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        assert r['worst_status'] == 'OK'
        battle = [f for f in r['findings'] if f['severity'] == 'AI_BATTLE']
        assert battle and battle[0]['status'] == 'NOT_NEEDED'

    def test_both_ai_missing_is_missing(self, tmp_path):
        """If BOTH _battle and _logic are absent, the chr genuinely
        has no AI — should be MISSING (freeze-class, but still hard
        severity for worst_status purposes)."""
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        # No script files at all
        for ext in ('chrbnd', 'anibnd', 'behbnd'):
            _touch(os.path.join(nr, 'chr', f'c4350.{ext}.dcx'))
        _touch(os.path.join(nr, 'sfx', 'sfxbnd_c4350.ffxbnd.dcx'))
        r = car.check_chr('c4350', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        assert r['worst_status'] == 'MISSING', (
            f'chr with no AI scripts at all should be MISSING; got '
            f'{r["worst_status"]}')
        ai_missing = [f for f in r['findings']
                      if f['severity'] in car._AI_SEVERITIES
                      and f['status'] == 'MISSING']
        assert len(ai_missing) == 2, (
            f'expected 2 MISSING AI findings; got {len(ai_missing)}')


class TestSeveritySplit:
    """v0.24.86-patch1: _CTD_SEVERITIES is a strict subset of
    _HARD_SEVERITIES. AI is hard (bumps worst_status) but NOT CTD
    (it's freeze-class). This split lets the CLI summary count
    probable-CRASH vs probable-FREEZE separately."""

    def test_ctd_severities_subset_of_hard(self):
        assert car._CTD_SEVERITIES.issubset(car._HARD_SEVERITIES)

    def test_ai_in_hard_not_in_ctd(self):
        assert 'AI_BATTLE' in car._HARD_SEVERITIES
        assert 'AI_LOGIC' in car._HARD_SEVERITIES
        assert 'AI_BATTLE' not in car._CTD_SEVERITIES
        assert 'AI_LOGIC' not in car._CTD_SEVERITIES

    def test_required_and_combat_ffx_in_ctd(self):
        assert 'REQUIRED' in car._CTD_SEVERITIES
        assert 'COMBAT_FFX' in car._CTD_SEVERITIES


class TestRosterPhantomDetection:
    """v0.24.86-patch1: roster phantoms (c-prefixes in nr_enemy_tags.
    json that don't have any chr/ files in any source) report as
    MISSING and bump worst_status. We don't filter them out — that's
    a roster-side fix — but we surface them correctly so the user can
    identify which roster entries are stale.

    Concrete examples from Alaric's preflight: c10000, c13703, c14340,
    c14961, c19999 — these are nr-source per the roster but don't
    exist in his vanilla NR install."""

    def test_phantom_chr_reports_missing_required(self, tmp_path):
        nr = str(tmp_path / 'nr')
        target = str(tmp_path / 'target')
        _build_install(nr); _build_install(target)
        # NR install has SOMETHING in it (so it's not 'no source set')
        # but c19999 specifically is absent
        _touch(os.path.join(nr, 'chr', 'c4350.chrbnd.dcx'))
        r = car.check_chr('c19999', 'nr',
                          {'nr': nr, 'er': None, 'mmv': None}, target)
        assert r['worst_status'] == 'MISSING'
        required_missing = [
            f for f in r['findings']
            if f['severity'] == 'REQUIRED' and f['status'] == 'MISSING']
        assert len(required_missing) == 3, (
            f'expected all 3 REQUIRED chr files missing for phantom '
            f'c19999; got {len(required_missing)}')
