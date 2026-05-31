"""
test_settings_code.py — locks the v0.27.15 (note 18) settings export/import
and the run-output "Active settings" summary.

The helpers are module-level and Tk-free (importing tkinter itself is fine,
no display needed), so they can be exercised directly.

Two contracts matter:
  1. encode -> decode is a faithful round-trip for every known key, and
     decode rejects anything that isn't a well-formed NRR1 code.
  2. summarize_run_settings flags exactly the NON-DEFAULT settings (the
     "left on by accident" set) and nothing else — this is what gets
     printed prominently at the top of each run.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from oops_rando_gui import (  # noqa: E402
    SETTINGS_CODE_PREFIX,
    encode_settings_code,
    decode_settings_code,
    normalize_run_settings,
    summarize_run_settings,
    format_run_settings_block,
)


# ---------------------------------------------------------------------------
# normalize: defaults present + typed
# ---------------------------------------------------------------------------
class TestNormalize:
    def test_empty_fills_defaults(self):
        d = normalize_run_settings({})
        assert d['run_mode'] == 'Standard'
        assert d['multiplayer_safe'] is True
        assert d['mmv_enabled'] is False
        assert d['randomize_all_nb_arenas'] is False
        assert d['excluded'] == []
        assert d['unique_cap_overrides'] == {}

    def test_none_is_safe(self):
        d = normalize_run_settings(None)
        assert d['run_mode'] == 'Standard'

    def test_collections_sorted(self):
        d = normalize_run_settings({'excluded': ['c2', 'c1'],
                                    'force_include': ['c9', 'c3']})
        assert d['excluded'] == ['c1', 'c2']
        assert d['force_include'] == ['c3', 'c9']

    def test_bools_coerced(self):
        d = normalize_run_settings({'multiplayer_safe': 0, 'mmv_enabled': 1})
        assert d['multiplayer_safe'] is False
        assert d['mmv_enabled'] is True

    def test_garbage_caps_dont_crash(self):
        d = normalize_run_settings({'unique_cap_overrides': 'not-a-dict'})
        assert d['unique_cap_overrides'] == {}


# ---------------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------------
class TestRoundTrip:
    def test_prefix(self):
        assert encode_settings_code({}).startswith(SETTINGS_CODE_PREFIX)

    def test_default_round_trip(self):
        code = encode_settings_code({})
        assert decode_settings_code(code) == normalize_run_settings({})

    def test_rich_config_round_trip(self):
        raw = {
            'run_mode': 'Oops! All NB (boss probe) …',
            'oops_all_nb_target': 'c4500',
            'oops_all_nb_scope': 'broad',
            'multiplayer_safe': False,
            'mmv_enabled': True,
            'sote_mode': True,
            'disable_resilient_filter': True,
            'randomize_all_nb_arenas': False,
            'merchant_model_swap': False,
            'excluded': ['c1234', 'c0001'],
            'force_include': ['c9999'],
            'diagnostic_targets': ['c4090'],
            'unique_cap_overrides': {'c4500': 3},
            'caliber_pool_extras': ['c7777'],
            'caliber_pool_removals': ['c8888'],
        }
        out = decode_settings_code(encode_settings_code(raw))
        expected = normalize_run_settings(raw)
        assert out == expected

    def test_code_is_reasonably_short(self):
        # Sanity bound: zlib+base64 has fixed overhead, so a small default
        # config lands a few hundred chars — fine for copy-paste. The bound
        # just guards against accidentally embedding uncompressed blobs.
        assert len(encode_settings_code({})) < 600


# ---------------------------------------------------------------------------
# decode rejects junk
# ---------------------------------------------------------------------------
class TestDecodeRejectsJunk:
    @pytest.mark.parametrize("bad", [
        "", "   ", "hello world", "NRR1-!!!not-base64!!!",
        "NRR9-abc", "v1-deadbeef", "NRR1-",
    ])
    def test_bad_codes_raise_valueerror(self, bad):
        with pytest.raises(ValueError):
            decode_settings_code(bad)

    def test_non_string_raises(self):
        with pytest.raises(ValueError):
            decode_settings_code(12345)


# ---------------------------------------------------------------------------
# summary flags exactly the non-defaults
# ---------------------------------------------------------------------------
class TestSummary:
    def test_default_is_all_default(self):
        notable, all_default = summarize_run_settings({})
        assert all_default is True
        assert notable == []

    def test_flags_multiplayer_off(self):
        notable, all_default = summarize_run_settings(
            {'multiplayer_safe': False})
        assert all_default is False
        assert any('Multiplayer-safe: OFF' in n for n in notable)

    def test_flags_mmv_on(self):
        notable, _ = summarize_run_settings({'mmv_enabled': True})
        assert any('MMV' in n and 'ON' in n for n in notable)

    def test_nb_arena_randomize_toggle_on_is_flagged(self):
        # randomize_all_nb_arenas defaults False (NB arenas preserved);
        # turning it ON is the notable deviation, and leaving it at the
        # default is not flagged.
        notable, _ = summarize_run_settings(
            {'randomize_all_nb_arenas': True})
        assert any('Randomize all NB arenas: ON' in n for n in notable)
        notable_default, _ = summarize_run_settings(
            {'randomize_all_nb_arenas': False})
        assert not any('Randomize all NB arenas' in n for n in notable_default)

    def test_mode_includes_target(self):
        notable, _ = summarize_run_settings({
            'run_mode': 'Oops! All NB (boss probe) …',
            'oops_all_nb_target': 'c4500', 'oops_all_nb_scope': 'broad'})
        line = next(n for n in notable if n.startswith('Mode:'))
        assert 'c4500' in line and 'broad' in line

    def test_collections_summarized_by_count(self):
        notable, _ = summarize_run_settings(
            {'excluded': ['c1', 'c2', 'c3']})
        assert any('Pool exclusions: 3' in n for n in notable)

    def test_setting_at_default_not_flagged(self):
        # multiplayer_safe True is the default — must NOT appear.
        notable, _ = summarize_run_settings({'multiplayer_safe': True,
                                             'mmv_enabled': True})
        assert not any('Multiplayer-safe' in n for n in notable)
        assert any('MMV' in n for n in notable)


# ---------------------------------------------------------------------------
# format block: tags drive coloring
# ---------------------------------------------------------------------------
class TestFormatBlock:
    def test_header_is_accent(self):
        block = format_run_settings_block({})
        assert block[0] == ('accent', '=== Active settings ===')

    def test_all_default_single_dim_line(self):
        block = format_run_settings_block({})
        # header + one dim reassurance line, no warn lines
        assert not any(tag == 'warn' for tag, _ in block)
        assert any(tag == 'dim' for tag, _ in block)

    def test_non_default_lines_are_warn(self):
        block = format_run_settings_block({'multiplayer_safe': False})
        assert any(tag == 'warn' for tag, _ in block)

    def test_code_line_present_when_supplied(self):
        block = format_run_settings_block({}, code='NRR1-xyz')
        assert any('NRR1-xyz' in text for _, text in block)

    def test_no_code_line_when_absent(self):
        block = format_run_settings_block({})
        assert not any('Settings code' in text for _, text in block)
