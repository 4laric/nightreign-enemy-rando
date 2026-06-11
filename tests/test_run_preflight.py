#!/usr/bin/env python3
"""Tests for run_preflight.py — the pure pre-run logic extracted from
oops_rando_gui._run_shuffle / _worker (v0.33).

No tkinter anywhere: this is exactly the point of the extraction. The
engine-kwargs test doubles as a drift lock — if the GUI's config dict and
the engine's expected kwargs evolve, this is where the contract lives.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_preflight as RP  # noqa: E402


# --------------------------------------------------------------------------- #
# check_input_dir
# --------------------------------------------------------------------------- #
def test_input_dir_missing(tmp_path):
    assert RP.check_input_dir('') == 'missing'
    assert RP.check_input_dir(None) == 'missing'
    assert RP.check_input_dir(str(tmp_path / 'nope')) == 'missing'


def test_input_dir_no_msbs(tmp_path):
    (tmp_path / 'readme.txt').write_text('not a map')
    assert RP.check_input_dir(str(tmp_path)) == 'no_msbs'


def test_input_dir_ok_with_dcx_or_raw(tmp_path):
    (tmp_path / 'm60_10_10_00.msb.dcx').write_bytes(b'x')
    assert RP.check_input_dir(str(tmp_path)) == 'ok'
    raw = tmp_path / 'raw'
    raw.mkdir()
    (raw / 'm60_10_10_00.msb').write_bytes(b'x')
    assert RP.check_input_dir(str(raw)) == 'ok'


# --------------------------------------------------------------------------- #
# ensure_output_dir
# --------------------------------------------------------------------------- #
def test_output_dir_unset():
    assert RP.ensure_output_dir('') == ('unset', None)
    assert RP.ensure_output_dir('   ') == ('unset', None)


def test_output_dir_created(tmp_path):
    target = tmp_path / 'a' / 'b'
    assert RP.ensure_output_dir(str(target)) == ('ok', None)
    assert target.is_dir()
    # idempotent on an existing dir
    assert RP.ensure_output_dir(str(target)) == ('ok', None)


@pytest.mark.parametrize('exc,code', [
    (PermissionError('denied'), 'permission'),
    (FileNotFoundError('no parent'), 'parent_missing'),
    (OSError('disk full'), 'oserror'),
])
def test_output_dir_failure_codes(monkeypatch, exc, code):
    def boom(path, exist_ok=False):
        raise exc
    monkeypatch.setattr(RP.os, 'makedirs', boom)
    status, detail = RP.ensure_output_dir('/somewhere')
    assert status == code
    if code == 'oserror':
        assert 'disk full' in detail


# --------------------------------------------------------------------------- #
# resolve_oops_targets
# --------------------------------------------------------------------------- #
LOOKUP = {'Giant Crayfish (c4420)': 'c4420',
          'Leyndell Foot Soldier (c4373)': 'c4373'}


def test_standard_mode_resolves_nothing():
    targets, err = RP.resolve_oops_targets('Standard', lookup=LOOKUP)
    assert err is None
    assert targets == {'oops_all_target_cp': None,
                       'oops_all_nb_target_cp': None,
                       'oops_all_nb_marker_scope': None}


def test_oops_all_resolves_display_string_and_raw_prefix():
    targets, err = RP.resolve_oops_targets(
        'Oops! All', all_pick='Leyndell Foot Soldier (c4373)', lookup=LOOKUP)
    assert err is None and targets['oops_all_target_cp'] == 'c4373'
    # raw c_prefix not in the lookup falls back to the first token
    targets, err = RP.resolve_oops_targets(
        'Oops! All', all_pick='c9999 some trailing text', lookup=LOOKUP)
    assert err is None and targets['oops_all_target_cp'] == 'c9999'


def test_oops_all_nb_mode_takes_nb_branch_with_scope_default():
    targets, err = RP.resolve_oops_targets(
        'Oops! All NB', nb_pick='Giant Crayfish (c4420)', lookup=LOOKUP)
    assert err is None
    assert targets['oops_all_nb_target_cp'] == 'c4420'
    assert targets['oops_all_target_cp'] is None      # NB branch only
    assert targets['oops_all_nb_marker_scope'] == 'broad'   # default scope
    targets, _ = RP.resolve_oops_targets(
        'Oops! All NB', nb_pick='c4420', nb_scope='strict', lookup=LOOKUP)
    assert targets['oops_all_nb_marker_scope'] == 'strict'


def test_missing_picks_error_codes():
    _, err = RP.resolve_oops_targets('Oops! All NB', nb_pick='  ')
    assert err == 'nb_target_missing'
    _, err = RP.resolve_oops_targets('Oops! All', all_pick='')
    assert err == 'target_missing'


# --------------------------------------------------------------------------- #
# build_engine_kwargs — the GUI->engine contract lock
# --------------------------------------------------------------------------- #
MINIMAL_CONFIG = {
    'seed': 8675309,
    'oops_all_target_cp': None,
    'merchant_model_swap': True,
    'excluded': {'c4420'},
    'hub_maps': {'m11_10_00_00.msb'},
}

EXPECTED_KEYS = {
    'seed', 'oops_all_target_cp', 'oops_all_nb_target_cp',
    'oops_all_nb_marker_scope', 'merchant_model_swap', 'excluded_prefixes',
    'hub_maps', 'multiplayer_safe', 'disable_resilient_filter',
    'non_fragile_baseline_cp', 'diagnostic_test_targets',
    'terrain_test_targets', 'force_include_targets', 'chaos_mode',
    'mount_rider_swap', 'sote_mode', 'unique_cap_overrides',
    'caliber_pool_extras', 'caliber_pool_removals',
    'field_upgrade_miniboss_pct', 'field_upgrade_fieldboss_pct',
    'field_upgrade_nightboss_pct', 'fieldboss_to_nightboss_promote_pct',
}


def test_kwargs_key_set_locked():
    kw = RP.build_engine_kwargs(dict(MINIMAL_CONFIG))
    assert set(kw) == EXPECTED_KEYS


def test_kwargs_minimal_defaults():
    kw = RP.build_engine_kwargs(dict(MINIMAL_CONFIG))
    assert kw['seed'] == 8675309
    assert kw['excluded_prefixes'] == {'c4420'}
    assert kw['hub_maps'] == {'m11_10_00_00.msb'}
    # optional flags default falsy / None
    assert kw['multiplayer_safe'] is False
    assert kw['chaos_mode'] is False
    assert kw['unique_cap_overrides'] is None
    assert kw['field_upgrade_miniboss_pct'] is None


def test_kwargs_values_thread_through():
    cfg = dict(MINIMAL_CONFIG,
               oops_all_nb_target_cp='c4420',
               oops_all_nb_marker_scope='strict',
               multiplayer_safe=1,                 # truthy -> bool
               sote_mode=True,
               unique_cap_overrides={'c4373': 8},
               fieldboss_to_nightboss_promote_pct=15)
    kw = RP.build_engine_kwargs(cfg)
    assert kw['oops_all_nb_target_cp'] == 'c4420'
    assert kw['multiplayer_safe'] is True
    assert kw['sote_mode'] is True
    assert kw['unique_cap_overrides'] == {'c4373': 8}
    assert kw['fieldboss_to_nightboss_promote_pct'] == 15


def test_kwargs_required_keys_fail_loud():
    cfg = dict(MINIMAL_CONFIG)
    del cfg['seed']
    with pytest.raises(KeyError):
        RP.build_engine_kwargs(cfg)


def test_kwargs_match_engine_signatures():
    """Every kwarg must be accepted by BOTH shuffle paths, or the run dies
    deep in the worker with a TypeError. cmd_shuffle_v3 takes seed
    positionally (the GUI pops it); rando_pipeline takes the rest plus
    its own pipeline-only params."""
    import inspect
    import dcx_batch
    import oops_v3

    kw = set(RP.build_engine_kwargs(dict(MINIMAL_CONFIG)))
    pipe_params = set(
        inspect.signature(dcx_batch.rando_pipeline).parameters)
    shuf_params = set(
        inspect.signature(oops_v3.cmd_shuffle_v3).parameters)
    assert kw <= pipe_params, kw - pipe_params
    assert (kw - {'seed'}) <= shuf_params, (kw - {'seed'}) - shuf_params
