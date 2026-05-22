"""Tests for dev/find_derand_seed.py."""
import importlib.util
import json
import os
import sys

import pytest


@pytest.fixture(scope='module')
def fds_module():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    script_path = os.path.join(repo, 'dev', 'find_derand_seed.py')
    spec = importlib.util.spec_from_file_location('find_derand_seed',
                                                  script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['find_derand_seed'] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------
# Shifting-earth classification (MSB prefix → SE)
# ---------------------------------------------------------------------

@pytest.mark.parametrize('msb,expected_se', [
    # Confirmed shifting-earth tiles from Alaric's spoiler manifest
    ('m60_42_36_50.msb', 'crater'),
    ('m60_42_36_00.msb', 'crater'),
    ('m60_42_37_50.msb', 'noklateo'),
    ('m60_43_37_00.msb', 'noklateo'),
    ('m60_43_37_10.msb', 'noklateo'),
    ('m60_43_38_20.msb', 'rotted_woods'),
    # Base-game (non-SE) tiles
    ('m15_00_00_00.msb', None),
    ('m32_20_00_00.msb', None),
    ('m34_30_00_00.msb', None),
    ('m38_00_00_00.msb', None),
    ('m43_50_00_00.msb', None),
    ('m46_50_00_00.msb', None),
    ('m46_71_00_00.msb', None),
])
def test_shifting_earth_for_msb(fds_module, msb, expected_se):
    se, _ = fds_module.shifting_earth_for_msb(msb)
    assert se == expected_se, (
        f'{msb}: expected SE={expected_se}, got {se}')


def test_shifting_earth_accepts_trailing_whitespace(fds_module):
    se, _ = fds_module.shifting_earth_for_msb('  m60_42_36_50.msb  ')
    assert se == 'crater'


# ---------------------------------------------------------------------
# Pattern-range arithmetic (Nightlord + SE → pattern_id range)
# ---------------------------------------------------------------------

def test_pattern_ranges_for_base(fds_module):
    """No-SE patterns: every Nightlord has a 20-pattern base block at
    its offset. Adel (index 1) → 040-059."""
    ranges = fds_module.pattern_ranges_for_se(None)
    assert len(ranges) == 10, '10 Nightlords expected in registry'
    adel = next(r for r in ranges if r.nightlord == 'adel')
    assert adel.lo == 40 and adel.hi == 59
    gladius = next(r for r in ranges if r.nightlord == 'gladius')
    assert gladius.lo == 0 and gladius.hi == 19


def test_pattern_ranges_for_crater(fds_module):
    """Crater patterns: 5-pattern slice at offset 25 within each
    Nightlord's block. Adel → 065-069 (verified against
    thefifthmatt.github.io/nightreign/adel/ page where 065, 066, 067,
    068, 069 are labeled with '(Crater)')."""
    ranges = fds_module.pattern_ranges_for_se('crater')
    adel = next(r for r in ranges if r.nightlord == 'adel')
    assert adel.lo == 65 and adel.hi == 69
    # Cross-check Gladius: 0+25 .. 0+29
    gladius = next(r for r in ranges if r.nightlord == 'gladius')
    assert gladius.lo == 25 and gladius.hi == 29


def test_pattern_ranges_for_noklateo(fds_module):
    """Noklateo: 5-pattern slice at offset 35. Adel → 075-079
    (verified: '(Noklateo)' labels at 075, 076, 077, 078, 079)."""
    ranges = fds_module.pattern_ranges_for_se('noklateo')
    adel = next(r for r in ranges if r.nightlord == 'adel')
    assert adel.lo == 75 and adel.hi == 79


def test_pattern_ranges_for_great_hollow_is_dlc(fds_module):
    """Great Hollow patterns are in the DLC block. Adel → 1010-1019."""
    ranges = fds_module.pattern_ranges_for_se('great_hollow')
    adel = next(r for r in ranges if r.nightlord == 'adel')
    assert adel.lo == 1010 and adel.hi == 1019
    assert adel.is_dlc is True


def test_pattern_range_contains(fds_module):
    """PatternRange.contains is inclusive on both ends."""
    r = fds_module.PatternRange('adel', 'crater', 65, 69, False)
    assert r.contains(65)
    assert r.contains(67)
    assert r.contains(69)
    assert not r.contains(64)
    assert not r.contains(70)


def test_unknown_se_returns_empty_ranges(fds_module):
    """Pasting a nonsense SE name shouldn't crash."""
    assert fds_module.pattern_ranges_for_se('garbage') == []


# ---------------------------------------------------------------------
# Observation cache I/O
# ---------------------------------------------------------------------

def test_observations_roundtrip(fds_module, tmp_path):
    path = str(tmp_path / 'obs.json')
    # Empty start
    obs = fds_module.load_observations(path)
    assert obs == {'observations': []}
    # Record one
    obs['observations'].append({
        'seed': 522250,
        'nightlord': 'adel',
        'pattern_id': 67,
        'visited_msbs': ['m60_42_36_50.msb', 'm60_42_36_10.msb'],
        'notes': 'crater test for c3100',
        'recorded_at': '2026-05-15',
    })
    fds_module.save_observations(path, obs)
    # Reload, lookup by MSB
    obs2 = fds_module.load_observations(path)
    hits = fds_module.observations_for_msb(obs2, 'm60_42_36_50.msb')
    assert len(hits) == 1
    assert hits[0]['seed'] == 522250
    assert hits[0]['nightlord'] == 'adel'
    # Non-hit
    misses = fds_module.observations_for_msb(obs2, 'm15_00_00_00.msb')
    assert misses == []


def test_observations_for_msb_handles_missing_field(fds_module):
    """Old-format entries without visited_msbs shouldn't crash the
    lookup."""
    obs = {'observations': [
        {'seed': 1, 'nightlord': 'adel', 'pattern_id': 40},
        {'seed': 2, 'nightlord': 'adel', 'pattern_id': 41,
         'visited_msbs': ['m60_42_36_50.msb']},
    ]}
    hits = fds_module.observations_for_msb(obs, 'm60_42_36_50.msb')
    assert len(hits) == 1
    assert hits[0]['seed'] == 2


# ---------------------------------------------------------------------
# CLI integration smoke tests
# ---------------------------------------------------------------------

def test_cli_target_msb_no_cache(fds_module, tmp_path, capsys):
    """--target-msb with no cache should print the SE classification,
    the pattern ranges, and GUI guidance."""
    obs_path = str(tmp_path / 'obs.json')
    rc = fds_module.main([
        '--observations', obs_path,
        '--target-msb', 'm60_42_36_50.msb',
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'crater' in out
    assert 'adel' in out  # one of the listed Nightlords
    assert '065-069' in out  # Adel's crater range
    assert 'no cached observations' in out


def test_cli_target_msb_with_cache(fds_module, tmp_path, capsys):
    """After --record, --target-msb surfaces the cached seed."""
    obs_path = str(tmp_path / 'obs.json')
    fds_module.main([
        '--observations', obs_path,
        '--record',
        '--seed', '522250',
        '--nightlord', 'adel',
        '--pattern-id', '67',
        '--visited-msb', 'm60_42_36_50.msb',
    ])
    capsys.readouterr()  # drain
    rc = fds_module.main([
        '--observations', obs_path,
        '--target-msb', 'm60_42_36_50.msb',
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'cached observations' in out
    assert '522250' in out


def test_cli_target_msb_nightlord_filter(fds_module, tmp_path, capsys):
    """--nightlord narrows --target-msb output to one Nightlord."""
    rc = fds_module.main([
        '--observations', str(tmp_path / 'obs.json'),
        '--target-msb', 'm60_42_36_50.msb',
        '--nightlord', 'adel',
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'adel' in out
    # Other Nightlords shouldn't be in the output ranges section
    assert 'gladius' not in out
    assert 'maris' not in out


def test_cli_record_validation(fds_module, tmp_path, capsys):
    """--record without --visited-msb is an error."""
    rc = fds_module.main([
        '--observations', str(tmp_path / 'obs.json'),
        '--record',
        '--seed', '1',
        '--nightlord', 'adel',
        '--pattern-id', '40',
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'visited-msb' in err


def test_cli_no_command_is_error(fds_module, tmp_path, capsys):
    rc = fds_module.main(['--observations', str(tmp_path / 'obs.json')])
    assert rc == 2
