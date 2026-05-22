"""Tests for `dev/extract_placement_budget.py`.

Covers:

1. **Round-trip byte stability** — extract → render → re-parse → re-render
   produces identical bytes. Catches non-determinism in serialization.

2. **Reconstruction matches live engine** — running the inverse function
   `reconstruct_sets()` on the extracted budget returns the same V3_*
   set membership as the live engine. This is the "single source of
   truth" guarantee: the JSON faithfully represents the engine.

3. **Committed-file freshness** — the JSON file at `data/placement_
   budget.json` matches what a fresh extraction would produce. If
   someone edits a V3_* constant without re-running the extractor,
   this test catches it.

4. **Schema invariants** — every chr entry has the expected fields with
   the expected types.

5. **Pure-function extraction** — `extract_budget()` works against a
   minimal duck-typed engine, no I/O. Lets future tests construct
   minimal scenarios for the GUI / loader work.
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'dev'))

from extract_placement_budget import (  # noqa: E402
    DEFAULT_OUTPUT_PATH,
    extract_budget,
    reconstruct_sets,
    render_json,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_engine(
    caps: dict | None = None,
    excl: set | None = None,
    ghost: set | None = None,
    arena_only: set | None = None,
    fragile: set | None = None,
    nb_strict: set | None = None,
    nb_caliber: set | None = None,
    map_excl: dict | None = None,
    mp_safe: set | None = None,
    tag_overrides: dict | None = None,
    default_cap: int = 50,
    fingerprint: str = 'mock_engine',
):
    """Build a duck-typed engine object with the minimum surface
    extract_budget() reads. Defaults to empty sets so tests can specify
    just the bits they care about."""
    return SimpleNamespace(
        V3_UNIQUE_TARGET_CAPS=caps if caps is not None else {},
        V3_EXCLUDE_TARGET_PREFIXES=excl if excl is not None else set(),
        V3_GHOST_EXCLUDE_TARGET_PREFIXES=ghost if ghost is not None else set(),
        V3_ARENA_ONLY_TARGETS=arena_only if arena_only is not None else set(),
        V3_FRAGILE_SENSITIVE_TARGETS=fragile if fragile is not None else set(),
        V3_NIGHT_BOSS_STRICT_TARGETS=nb_strict if nb_strict is not None else set(),
        V3_NIGHT_BOSS_CALIBER_TARGETS=nb_caliber if nb_caliber is not None else set(),
        V3_MAP_PREFIX_TARGET_EXCLUDES=map_excl if map_excl is not None else {},
        # v0.26.x schema_version=2 additions
        V3_MP_SAFE_BLOCKLIST=mp_safe if mp_safe is not None else set(),
        V3_TAG_OVERRIDES=tag_overrides if tag_overrides is not None else {},
        V3_TARGET_PLACEMENT_CAP=default_cap,
        V3_ENGINE_FINGERPRINT=fingerprint,
    )


# ---------------------------------------------------------------------------
# Pure-function tests against a minimal mock engine
# ---------------------------------------------------------------------------

class TestExtractWithMock:
    """Schema + behavior tests that don't depend on loading the real engine."""

    def test_empty_engine_produces_empty_chrs(self):
        budget = extract_budget(_make_mock_engine(), tags={})
        assert budget['chrs'] == {}
        assert budget['global_default_cap'] == 50

    def test_single_cap_creates_entry(self):
        budget = extract_budget(
            _make_mock_engine(caps={'c1234': 2}),
            tags={'c1234': {'name': 'Test Mob'}},
        )
        assert set(budget['chrs'].keys()) == {'c1234'}
        e = budget['chrs']['c1234']
        assert e['cap'] == 2
        assert e['name'] == 'Test Mob'
        # All gate booleans default False
        assert e['exclude'] is False
        assert e['ghost_exclude'] is False
        assert e['arena_only'] is False
        assert e['fragile_sensitive'] is False
        assert e['nb_strict'] is False
        assert e['nb_caliber'] is False
        assert e['map_excludes'] == []
        # Editorial placeholders
        assert e['rationale'] is None
        assert e['since'] is None
        assert e['history'] == []
        assert e['tags'] == []

    def test_exclude_only_chr_has_no_cap_but_still_included(self):
        budget = extract_budget(
            _make_mock_engine(excl={'c5555'}),
            tags={},
        )
        assert 'c5555' in budget['chrs']
        assert budget['chrs']['c5555']['cap'] is None
        assert budget['chrs']['c5555']['exclude'] is True
        # Missing tag → name is None, not crash
        assert budget['chrs']['c5555']['name'] is None

    def test_map_excludes_are_sorted_per_chr(self):
        budget = extract_budget(
            _make_mock_engine(
                excl=set(),
                map_excl={'m60_': {'c1111'}, 'm32_': {'c1111'}, 'm47_': {'c1111'}},
            ),
            tags={},
        )
        assert budget['chrs']['c1111']['map_excludes'] == ['m32_', 'm47_', 'm60_']

    def test_chr_in_multiple_gates_aggregates_correctly(self):
        budget = extract_budget(
            _make_mock_engine(
                caps={'c9999': 1},
                excl={'c9999'},
                arena_only={'c9999'},
                fragile={'c9999'},
                nb_strict={'c9999'},
                nb_caliber={'c9999'},
                map_excl={'m60_': {'c9999'}},
            ),
            tags={},
        )
        e = budget['chrs']['c9999']
        assert e['cap'] == 1
        assert e['exclude'] is True
        assert e['arena_only'] is True
        assert e['fragile_sensitive'] is True
        assert e['nb_strict'] is True
        assert e['nb_caliber'] is True
        assert e['map_excludes'] == ['m60_']

    def test_chr_keys_sorted_alphabetically(self):
        budget = extract_budget(
            _make_mock_engine(caps={'c9999': 1, 'c1000': 2, 'c5000': 3}),
            tags={},
        )
        # JSON serialization is sorted via sort_keys=True, but the
        # in-memory order matters too for deterministic iteration.
        rendered = render_json(budget)
        # Verify position ordering in the rendered output
        i1000 = rendered.index('"c1000"')
        i5000 = rendered.index('"c5000"')
        i9999 = rendered.index('"c9999"')
        assert i1000 < i5000 < i9999


# ---------------------------------------------------------------------------
# Round-trip stability
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """The extraction must be byte-stable and information-preserving."""

    def test_render_is_byte_stable_for_mock(self):
        """Rendering the same dict twice gives identical bytes."""
        engine = _make_mock_engine(
            caps={'c1000': 2, 'c2000': 1},
            excl={'c3000', 'c4000'},
            arena_only={'c1000'},
        )
        budget = extract_budget(engine, tags={'c1000': {'name': 'Alpha'},
                                              'c2000': {'name': 'Beta'}})
        a = render_json(budget)
        b = render_json(extract_budget(engine, tags={'c1000': {'name': 'Alpha'},
                                                     'c2000': {'name': 'Beta'}}))
        assert a == b

    def test_json_parses_back_to_equivalent_dict(self):
        """Round-trip via json.dumps/loads loses no information that
        the reconstruct step relies on."""
        engine = _make_mock_engine(
            caps={'c1000': 2, 'c2000': 1},
            excl={'c3000'},
            ghost={'c4000'},
            map_excl={'m32_': {'c5000', 'c6000'}, 'm60_': {'c5000'}},
        )
        budget1 = extract_budget(engine, tags={})
        rendered = render_json(budget1)
        budget2 = json.loads(rendered)
        # Re-render should be identical
        rendered2 = render_json(budget2)
        assert rendered == rendered2

    def test_reconstruct_inverts_extract_on_mock(self):
        """reconstruct_sets() applied to extracted budget gives back the
        original engine state (for the factual fields)."""
        engine = _make_mock_engine(
            caps={'c1000': 2, 'c2000': 1},
            excl={'c3000', 'c4000'},
            ghost={'c5000'},
            arena_only={'c1000', 'c2000'},
            fragile={'c1000'},
            nb_strict={'c2000'},
            nb_caliber={'c1000', 'c2000'},
            map_excl={'m32_': {'c6000'}, 'm60_': {'c6000', 'c7000'}},
            default_cap=42,
        )
        budget = extract_budget(engine, tags={})
        sets = reconstruct_sets(budget)
        assert sets['V3_UNIQUE_TARGET_CAPS'] == engine.V3_UNIQUE_TARGET_CAPS
        assert sets['V3_EXCLUDE_TARGET_PREFIXES'] == engine.V3_EXCLUDE_TARGET_PREFIXES
        assert sets['V3_GHOST_EXCLUDE_TARGET_PREFIXES'] == engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES
        assert sets['V3_ARENA_ONLY_TARGETS'] == engine.V3_ARENA_ONLY_TARGETS
        assert sets['V3_FRAGILE_SENSITIVE_TARGETS'] == engine.V3_FRAGILE_SENSITIVE_TARGETS
        assert sets['V3_NIGHT_BOSS_STRICT_TARGETS'] == engine.V3_NIGHT_BOSS_STRICT_TARGETS
        assert sets['V3_NIGHT_BOSS_CALIBER_TARGETS'] == engine.V3_NIGHT_BOSS_CALIBER_TARGETS
        assert sets['V3_MAP_PREFIX_TARGET_EXCLUDES'] == engine.V3_MAP_PREFIX_TARGET_EXCLUDES
        assert sets['V3_TARGET_PLACEMENT_CAP'] == engine.V3_TARGET_PLACEMENT_CAP

    def test_reconstruct_via_json_inverts_extract(self):
        """Same as above but going through the JSON serialization layer
        — verifies no information is lost in the on-disk representation."""
        engine = _make_mock_engine(
            caps={'c1000': 2},
            excl={'c3000'},
            map_excl={'m60_': {'c4000'}},
        )
        budget = extract_budget(engine, tags={})
        # Round-trip through JSON
        budget2 = json.loads(render_json(budget))
        sets = reconstruct_sets(budget2)
        assert sets['V3_UNIQUE_TARGET_CAPS'] == {'c1000': 2}
        assert sets['V3_EXCLUDE_TARGET_PREFIXES'] == {'c3000'}
        assert sets['V3_MAP_PREFIX_TARGET_EXCLUDES'] == {'m60_': {'c4000'}}


# ---------------------------------------------------------------------------
# Live engine snapshot
# ---------------------------------------------------------------------------

class TestLiveEngine:
    """Tests that consult the real oops_v3 engine post-load_data()."""

    def test_reconstruct_matches_live_engine_sets(self, engine, tags):
        """The extracted budget, when reconstructed, equals the engine's
        live V3_* set membership exactly. If a future engine change
        adds a new V3_* set, this test surfaces it (the extractor and
        this test both need to be updated)."""
        budget = extract_budget(engine, tags=tags)
        sets = reconstruct_sets(budget)

        assert sets['V3_UNIQUE_TARGET_CAPS'] == dict(engine.V3_UNIQUE_TARGET_CAPS)
        assert sets['V3_EXCLUDE_TARGET_PREFIXES'] == set(engine.V3_EXCLUDE_TARGET_PREFIXES)
        assert sets['V3_GHOST_EXCLUDE_TARGET_PREFIXES'] == set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
        assert sets['V3_ARENA_ONLY_TARGETS'] == set(engine.V3_ARENA_ONLY_TARGETS)
        assert sets['V3_FRAGILE_SENSITIVE_TARGETS'] == set(engine.V3_FRAGILE_SENSITIVE_TARGETS)
        assert sets['V3_NIGHT_BOSS_STRICT_TARGETS'] == set(engine.V3_NIGHT_BOSS_STRICT_TARGETS)
        assert sets['V3_NIGHT_BOSS_CALIBER_TARGETS'] == set(engine.V3_NIGHT_BOSS_CALIBER_TARGETS)
        # v0.26.x schema_version=2 additions
        assert sets['V3_MP_SAFE_BLOCKLIST'] == set(engine.V3_MP_SAFE_BLOCKLIST)

        # map_excludes: live engine uses sets/lists per map; normalize for compare
        engine_map = {m: set(cps) for m, cps in engine.V3_MAP_PREFIX_TARGET_EXCLUDES.items()}
        assert sets['V3_MAP_PREFIX_TARGET_EXCLUDES'] == engine_map

    def test_committed_file_matches_engine_state(self, engine, tags):
        """The shipped data/placement_budget.json must reflect the current
        engine state. If you edit a V3_* constant and don't re-run
        `python3 dev/extract_placement_budget.py`, this test fails
        with a directive to re-run it.

        This is the equivalent of `--check` mode in the CLI."""
        if not os.path.exists(DEFAULT_OUTPUT_PATH):
            pytest.fail(
                f'{DEFAULT_OUTPUT_PATH} does not exist. '
                f'Run: python3 dev/extract_placement_budget.py')
        with open(DEFAULT_OUTPUT_PATH, encoding='utf-8') as f:
            committed = f.read()
        live = render_json(extract_budget(engine, tags=tags))
        assert committed == live, (
            f'\ndata/placement_budget.json is out of date with engine state.\n'
            f'Run: python3 dev/extract_placement_budget.py\n'
            f'(Tip: a `git diff` on the file will show which c-prefixes changed.)'
        )

    def test_known_post_v0_26_cleanup_entries(self, engine, tags):
        """Lock in the c-prefix entries that the v0.26.x dead-cap cleanup
        touched. If these regress, audit_placement_budget_consistency.py
        will catch them again — this test catches them here too, in
        budget-file form, which is more directly diff-readable.
        """
        budget = extract_budget(engine, tags=tags)
        chrs = budget['chrs']

        # c7800 Duke's Dear Freja — cap was dropped (chrbnd-missing), still
        # excluded
        assert chrs['c7800']['cap'] is None, (
            'c7800 should have no cap entry after v0.26.x cleanup '
            '(chr has no chrbnd on disk; excluded permanently)')
        assert chrs['c7800']['exclude'] is True

        # c4361 Godrick Knight's Horse — removed from _LIFTED_V0_24_65,
        # still excluded
        assert chrs['c4361']['cap'] is None, (
            'c4361 should have no cap after v0.26.x cleanup of stale '
            'v0.24.65 lift; chr is re-excluded by v0.25.0-patch1')
        assert chrs['c4361']['exclude'] is True

        # c3610 Small Oracle Envoy — same pattern
        assert chrs['c3610']['cap'] is None, (
            'c3610 should have no cap after v0.26.x cleanup of stale '
            'v0.24.65 lift; chr is re-excluded by v0.24.86-patch2-followup')
        assert chrs['c3610']['exclude'] is True

        # c7700 Gaping Dragon — example of a live, non-dead cap
        assert chrs['c7700']['cap'] == 2

    def test_schema_invariants_on_live_extract(self, engine, tags):
        """Every chr entry must have the full field set with correct types."""
        budget = extract_budget(engine, tags=tags)

        required_str_or_null = {'name', 'tier', 'source',
                                'rationale', 'exclude_reason', 'since'}
        required_int_or_null = {'cap'}
        required_bool = {'exclude', 'ghost_exclude', 'arena_only',
                         'fragile_sensitive', 'nb_strict', 'nb_caliber',
                         'mp_safe_blocked', 'tier_override'}
        required_list = {'map_excludes', 'history', 'tags'}

        all_required = (required_str_or_null | required_int_or_null
                        | required_bool | required_list)

        for cp, entry in budget['chrs'].items():
            missing = all_required - set(entry.keys())
            assert not missing, f'{cp} missing fields: {missing}'
            for field in required_str_or_null:
                v = entry[field]
                assert v is None or isinstance(v, str), \
                    f'{cp}.{field} type: {type(v).__name__}'
            for field in required_int_or_null:
                v = entry[field]
                assert v is None or isinstance(v, int), \
                    f'{cp}.{field} type: {type(v).__name__}'
            for field in required_bool:
                assert isinstance(entry[field], bool), \
                    f'{cp}.{field} type: {type(entry[field]).__name__}'
            for field in required_list:
                assert isinstance(entry[field], list), \
                    f'{cp}.{field} type: {type(entry[field]).__name__}'
            # Every entry must have at least one non-default fact —
            # otherwise it shouldn't be in the sparse representation.
            has_fact = (
                entry['cap'] is not None
                or any(entry[f] for f in required_bool)
                or entry['map_excludes']
            )
            assert has_fact, f'{cp} is in chrs/ but has no non-default fact'

    def test_top_level_schema(self, engine, tags):
        budget = extract_budget(engine, tags=tags)
        assert set(budget.keys()) == {'_meta', 'global_default_cap', 'chrs'}
        assert isinstance(budget['_meta'], dict)
        assert isinstance(budget['global_default_cap'], int)
        assert isinstance(budget['chrs'], dict)
        # _meta declares its schema version, so loaders can guard.
        # v0.26.x: schema bumped 1 → 2 to cover mp_safe_blocked,
        # tier_override, tier, source, exclude_reason fields.
        assert budget['_meta'].get('_schema_version') == 2
