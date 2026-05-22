"""
test_spoiler_viewer.py — tests for the Tier 3 UX #11 Spoiler viewer tab.

Three layers:
  1. Pure-function tests for the spoiler-data helpers (_summarize_spoiler_metadata,
     _group_spoiler_entries_by_map, _filter_spoiler_entries) with realistic
     spoiler-shaped data.
  2. Source-inspection tests locking in the tab construction (notebook
     wiring, file picker, filter controls, scrolled text widget).
  3. Cross-tab integration: the post-run summary panel's View button
     must call _open_spoiler_in_viewer, which loads + switches tabs.
"""
import os
import textwrap
import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
GUI_PATH = os.path.join(os.path.dirname(HERE), 'oops_rando_gui.py')


@pytest.fixture(scope='module')
def gui_source():
    with open(GUI_PATH) as f:
        return f.read()


def _extract_method_body(src, name):
    needle = f'def {name}('
    start = src.find(needle)
    assert start != -1, f'method {name!r} not found'
    end_def = src.find('\n    def ', start + 1)
    end_at = src.find('\n    @', start + 1)
    candidates = [e for e in (end_def, end_at) if e != -1]
    end = min(candidates) if candidates else len(src)
    return src[start:end]


def _compile_static(gui_source, name, extra_ns=None):
    body = _extract_method_body(gui_source, name)
    body = textwrap.dedent(body)
    ns = dict(extra_ns or {})
    exec(body, ns)
    return ns[name]


@pytest.fixture(scope='module')
def summarize_spoiler_metadata(gui_source):
    return _compile_static(gui_source, '_summarize_spoiler_metadata')


@pytest.fixture(scope='module')
def group_spoiler_entries_by_map(gui_source):
    return _compile_static(gui_source, '_group_spoiler_entries_by_map')


@pytest.fixture(scope='module')
def filter_spoiler_entries(gui_source):
    return _compile_static(gui_source, '_filter_spoiler_entries')


def _make_sample_spoiler():
    """A realistic-shape spoiler dict for use across tests."""
    return {
        'engine_fingerprint': 'v0.26.0',
        'engine_version': 'v0.26.0',
        'seed': 42,
        'multiplayer_safe': True,
        'entry_count': 4,
        'entries': [
            {'map': 'm10_00_00_00', 'part_index': 1, 'is_boss': False,
             'catalog_tier': 'foot_soldier',
             'original': {'name': 'Soldier', 'c_prefix': 'c4373'},
             'new': {'name': 'Death Knight', 'c_prefix': 'c5070'}},
            {'map': 'm10_00_00_00', 'part_index': 99, 'is_boss': True,
             'catalog_tier': 'NB',
             'original': {'name': 'Maris', 'c_prefix': 'c5400'},
             'new': {'name': 'Mohg the Omen', 'c_prefix': 'c4800'}},
            {'map': 'm11_00_00_00', 'part_index': 4, 'is_boss': False,
             'catalog_tier': 'mob',
             'original': {'name': 'Wolf', 'c_prefix': 'c4070'},
             'new': {'name': 'Banished Knight', 'c_prefix': 'c5160'}},
            {'map': 'm60_42_36_00', 'part_index': 12, 'is_boss': True,
             'catalog_tier': 'field_boss',
             'original': {'name': 'Erdtree Avatar', 'c_prefix': 'c4811'},
             'new': {'name': 'Crucible Knight', 'c_prefix': 'c4210'}},
        ],
    }


# ---------------------------------------------------------------------
# Pure: _summarize_spoiler_metadata
# ---------------------------------------------------------------------

class TestSummarizeMetadata:
    def test_returns_list_of_tuples(self, summarize_spoiler_metadata):
        rows = summarize_spoiler_metadata(_make_sample_spoiler())
        assert isinstance(rows, list)
        for r in rows:
            assert isinstance(r, tuple) and len(r) == 2
            assert isinstance(r[0], str) and isinstance(r[1], str)

    def test_includes_engine_seed_entries_mp(self, summarize_spoiler_metadata):
        rows = summarize_spoiler_metadata(_make_sample_spoiler())
        labels = {label for label, _ in rows}
        for required in ('Engine', 'Seed', 'Entries', 'Multiplayer-safe'):
            assert required in labels, (
                f'Required field {required!r} missing from metadata '
                f'summary. The Run info panel will be missing context.')

    def test_multiplayer_safe_translated_to_on_off(self,
                                                   summarize_spoiler_metadata):
        """The raw bool gets shown as ON/OFF (user-friendly) rather
        than as 'True' / 'False'."""
        rows_on = summarize_spoiler_metadata(
            {'multiplayer_safe': True, 'entries': []})
        mp_on = next(v for k, v in rows_on if k == 'Multiplayer-safe')
        assert mp_on == 'ON'
        rows_off = summarize_spoiler_metadata(
            {'multiplayer_safe': False, 'entries': []})
        mp_off = next(v for k, v in rows_off if k == 'Multiplayer-safe')
        assert mp_off == 'OFF'

    def test_oops_all_nb_surfaced_when_set(self, summarize_spoiler_metadata):
        spoiler = _make_sample_spoiler()
        spoiler['oops_all_nb_target_cp'] = 'c5070'
        spoiler['oops_all_nb_marker_scope'] = 'broad'
        rows = summarize_spoiler_metadata(spoiler)
        nb_row = next((v for k, v in rows if k == 'Oops! All NB'), None)
        assert nb_row is not None
        assert 'c5070' in nb_row
        assert 'broad' in nb_row

    def test_oops_all_nb_hidden_when_not_set(self,
                                              summarize_spoiler_metadata):
        rows = summarize_spoiler_metadata(_make_sample_spoiler())
        labels = {label for label, _ in rows}
        assert 'Oops! All NB' not in labels, (
            "Oops! All NB row should only appear when a target is "
            "actually set — otherwise users see noise on normal runs.")

    def test_diagnostic_modes_surfaced(self, summarize_spoiler_metadata):
        """Diagnostic flags (disable_resilient_filter, non_fragile_baseline_cp,
        diagnostic_test_targets) must be visible — a run with these flags
        is NOT a normal play session, and freeze reports need to identify
        diagnostic context."""
        spoiler = _make_sample_spoiler()
        spoiler['disable_resilient_filter'] = True
        spoiler['non_fragile_baseline_cp'] = 'c4373'
        spoiler['diagnostic_test_targets'] = ['c3000', 'c3500']
        rows = summarize_spoiler_metadata(spoiler)
        text = ' '.join(f'{k}: {v}' for k, v in rows)
        assert 'DIAGNOSTIC' in text
        assert 'c4373' in text
        assert 'c3000' in text

    def test_handles_missing_keys(self, summarize_spoiler_metadata):
        """Old / partial spoilers may not have every key. The helper
        must not raise — show '(unknown)' or sensible defaults."""
        rows = summarize_spoiler_metadata({})
        # Should still return something
        assert len(rows) >= 3
        # No crash on missing engine / seed
        labels = dict(rows)
        assert 'unknown' in (labels.get('Engine') or '').lower() \
            or labels.get('Engine') == '(unknown)'

    def test_non_dict_returns_empty(self, summarize_spoiler_metadata):
        """Defensive: passing None or a non-dict (e.g. parse error
        returning a list) returns an empty list, not a crash."""
        assert summarize_spoiler_metadata(None) == []
        assert summarize_spoiler_metadata([]) == []
        assert summarize_spoiler_metadata('not a dict') == []


# ---------------------------------------------------------------------
# Pure: _group_spoiler_entries_by_map
# ---------------------------------------------------------------------

class TestGroupByMap:
    def test_groups_by_map_field(self, group_spoiler_entries_by_map):
        spoiler = _make_sample_spoiler()
        groups = group_spoiler_entries_by_map(spoiler['entries'])
        assert 'm10_00_00_00' in groups
        assert 'm11_00_00_00' in groups
        assert 'm60_42_36_00' in groups
        assert len(groups['m10_00_00_00']) == 2
        assert len(groups['m11_00_00_00']) == 1

    def test_empty_input(self, group_spoiler_entries_by_map):
        assert group_spoiler_entries_by_map([]) == {}
        assert group_spoiler_entries_by_map(None) == {}

    def test_skips_non_dict_entries(self, group_spoiler_entries_by_map):
        """Defensive: a malformed spoiler with stray non-dict items
        in 'entries' shouldn't crash the grouping."""
        mixed = [
            {'map': 'm10_00_00_00', 'part_index': 1},
            'this should be skipped',  # not a dict
            None,                      # also not a dict
            {'map': 'm11_00_00_00', 'part_index': 2},
        ]
        groups = group_spoiler_entries_by_map(mixed)
        assert len(groups) == 2

    def test_entries_without_map_get_unknown_label(self,
                                                    group_spoiler_entries_by_map):
        """Entries with no 'map' field are bucketed under '(unknown map)'
        rather than dropped — surfaces malformed data so the user knows
        it's there."""
        groups = group_spoiler_entries_by_map([
            {'part_index': 1, 'is_boss': False},  # no map field
            {'map': 'm10', 'part_index': 2},
        ])
        assert '(unknown map)' in groups


# ---------------------------------------------------------------------
# Pure: _filter_spoiler_entries
# ---------------------------------------------------------------------

class TestFilterEntries:
    def test_no_filters_returns_all(self, filter_spoiler_entries):
        entries = _make_sample_spoiler()['entries']
        assert filter_spoiler_entries(entries) == entries

    def test_search_matches_new_enemy_name(self, filter_spoiler_entries):
        entries = _make_sample_spoiler()['entries']
        result = filter_spoiler_entries(entries, search_text='death')
        assert len(result) == 1
        assert result[0]['new']['name'] == 'Death Knight'

    def test_search_matches_original_enemy_name(self, filter_spoiler_entries):
        """A user might search for 'Wolf' to find what replaced their
        beloved vanilla wolves. The match should look at the 'original'
        side too."""
        entries = _make_sample_spoiler()['entries']
        result = filter_spoiler_entries(entries, search_text='wolf')
        assert len(result) == 1
        assert result[0]['original']['name'] == 'Wolf'

    def test_search_case_insensitive(self, filter_spoiler_entries):
        entries = _make_sample_spoiler()['entries']
        assert len(filter_spoiler_entries(entries, search_text='KNIGHT')) == 3
        assert len(filter_spoiler_entries(entries, search_text='knight')) == 3
        assert len(filter_spoiler_entries(entries, search_text='Knight')) == 3

    def test_map_filter(self, filter_spoiler_entries):
        entries = _make_sample_spoiler()['entries']
        result = filter_spoiler_entries(entries, map_filter='m10_00_00_00')
        assert len(result) == 2
        for e in result:
            assert e['map'] == 'm10_00_00_00'

    def test_boss_only_filter(self, filter_spoiler_entries):
        entries = _make_sample_spoiler()['entries']
        result = filter_spoiler_entries(entries, boss_only=True)
        assert len(result) == 2
        for e in result:
            assert e['is_boss'] is True

    def test_combined_filters_intersect(self, filter_spoiler_entries):
        """Multiple filters AND together — bosses on m10_00_00_00 only."""
        entries = _make_sample_spoiler()['entries']
        result = filter_spoiler_entries(
            entries, map_filter='m10_00_00_00', boss_only=True)
        assert len(result) == 1
        assert result[0]['part_index'] == 99

    def test_no_match_returns_empty(self, filter_spoiler_entries):
        entries = _make_sample_spoiler()['entries']
        assert filter_spoiler_entries(
            entries, search_text='this enemy does not exist') == []

    def test_empty_entries_returns_empty(self, filter_spoiler_entries):
        assert filter_spoiler_entries([]) == []
        assert filter_spoiler_entries(None) == []

    def test_whitespace_search_ignored(self, filter_spoiler_entries):
        """A search field containing only whitespace shouldn't act as
        a filter — treat it the same as empty."""
        entries = _make_sample_spoiler()['entries']
        assert filter_spoiler_entries(entries, search_text='   ') == entries
        assert filter_spoiler_entries(entries, search_text='\t\n') == entries


# ---------------------------------------------------------------------
# Source-inspection: structural locks
# ---------------------------------------------------------------------

class TestSpoilerTabStructure:
    def test_tab_added_to_notebook(self, gui_source):
        """The Spoiler tab must be registered in the notebook with
        a recognisable label."""
        assert "nb.add(tab_spoiler, text='  Spoiler  ')" in gui_source, (
            'Spoiler tab not registered in the notebook. The build '
            'method exists but the tab is never visible.')

    def test_build_method_exists(self, gui_source):
        assert 'def _build_spoiler_tab(self, parent):' in gui_source

    def test_supporting_methods_exist(self, gui_source):
        for method in ('_spoiler_browse', '_spoiler_load_latest',
                        '_spoiler_reload', '_spoiler_load',
                        '_render_spoiler_info', '_render_spoiler_entries',
                        '_spoiler_clear_filters'):
            assert f'def {method}(' in gui_source, (
                f'Spoiler-tab method {method} missing.')

    def test_open_spoiler_in_viewer_method_exists(self, gui_source):
        assert 'def _open_spoiler_in_viewer(self, path):' in gui_source

    def test_summary_panel_uses_view_button(self, gui_source):
        """The post-run summary panel's spoiler row must include a
        'View' button wired to _open_spoiler_in_viewer — that's the
        primary entry point from a successful run."""
        render_body = _extract_method_body(gui_source, '_render_run_summary')
        assert '_open_spoiler_in_viewer' in render_body, (
            'Post-run summary spoiler row must include a View button '
            'wired to _open_spoiler_in_viewer.')


class TestSpoilerLoadSafety:
    """Loading a spoiler can fail in three distinct ways. All three
    must be handled with actionable errors, not stacktraces."""

    def test_handles_filenotfound(self, gui_source):
        body = _extract_method_body(gui_source, '_spoiler_load')
        assert 'FileNotFoundError' in body, (
            '_spoiler_load must handle FileNotFoundError specifically '
            '(file moved/deleted between path-set and load).')

    def test_handles_jsondecodeerror(self, gui_source):
        body = _extract_method_body(gui_source, '_spoiler_load')
        assert 'JSONDecodeError' in body, (
            'Corrupted/truncated spoiler JSON must surface a clear '
            'error rather than crash the GUI.')

    def test_handles_oserror(self, gui_source):
        body = _extract_method_body(gui_source, '_spoiler_load')
        assert 'OSError' in body, (
            'Permission/IO errors reading the spoiler file must be '
            'caught — not all read failures are FileNotFoundError.')


class TestSpoilerTabInteractivity:
    def test_search_is_live(self, gui_source):
        """The search var must trace_add re-renders so filtering is
        live as the user types."""
        body = _extract_method_body(gui_source, '_build_spoiler_tab')
        assert 'spoiler_search_var' in body
        assert "trace_add('write'" in body, (
            'Search field should re-render on every keystroke. Without '
            'the trace, users have to press Enter to filter.')

    def test_map_combo_re_renders_on_select(self, gui_source):
        body = _extract_method_body(gui_source, '_build_spoiler_tab')
        assert "'<<ComboboxSelected>>'" in body
        assert '_render_spoiler_entries' in body

    def test_filter_controls_present(self, gui_source):
        """Three filters: search text, map dropdown, boss-only toggle.
        All three must be wired into _render_spoiler_entries."""
        body = _extract_method_body(gui_source, '_build_spoiler_tab')
        # Search var
        assert 'spoiler_search_var' in body
        # Map dropdown
        assert 'spoiler_map_filter_var' in body
        # Boss-only toggle
        assert 'spoiler_boss_only_var' in body


class TestFindSpoilerCanonicalName:
    """The engine writes _spoilers.json (note leading underscore).
    The _find_spoiler_for_run helper must look for that name first."""

    @pytest.fixture
    def find_spoiler_for_run(self, gui_source):
        return _compile_static(gui_source, '_find_spoiler_for_run',
                                {'os': os})

    def test_finds_underscored_spoilers_json(self, find_spoiler_for_run,
                                              tmp_path):
        """The canonical engine output filename. Without this fix the
        post-run summary would always say '(not found)' on real runs."""
        (tmp_path / '_spoilers.json').write_text('{}')
        result = find_spoiler_for_run(str(tmp_path), 42)
        assert result == str(tmp_path / '_spoilers.json'), (
            'Engine writes _spoilers.json (with leading underscore). '
            'The helper must check this name first — without it, real '
            'runs report "spoiler not found" even when one exists.')
