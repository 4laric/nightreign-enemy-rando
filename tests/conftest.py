"""Engine test fixtures.

The expensive setup here is `load_data()`, which reads ~5 JSON files,
applies all 5 pack-loader code paths, and derives ~10 module globals
(V3_MP_SAFE_BLOCKLIST, V3_ARENA_ONLY_TARGETS auto-extension, etc.).
Measured at 0.07s on the dev box, but doing it once per test would still
add up across hundreds of tests.

Strategy: session-scoped fixture exposes the `(roster, tags)` return
value plus the derived `(prefix_variants, prefix_count)`. Module-level
V3_* globals also reflect the load (they're mutated by load_data and
we deliberately don't try to roll them back — tests that need a clean
slate should construct their own minimal tags/variants).
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)

import oops_v3  # noqa: E402  — path setup above


@pytest.fixture(scope='session')
def engine():
    """The oops_v3 module itself, post-load_data. Use this when a test
    needs access to module globals (V3_MP_SAFE_BLOCKLIST, etc.) that get
    populated during load.

    Tests should treat the module's globals as READ-ONLY. If a test needs
    to mutate global state to exercise a code path, do it via
    monkeypatch.setattr(oops_v3, 'V3_FOO', ...) so pytest reverts it.
    """
    # Trigger load_data once. The return value is captured in the
    # `loaded_data` fixture below; here we just ensure the module-level
    # globals are populated for downstream tests that read them directly.
    if not hasattr(oops_v3, '_test_loaded'):
        oops_v3.load_data()
        oops_v3._test_loaded = True
    return oops_v3


@pytest.fixture(scope='session')
def loaded_data(engine):
    """(roster, tags) tuple from load_data(). Session-scoped — load_data
    is idempotent in practice but doing it once is cheaper."""
    # load_data() returns fresh dicts; cache the result on the module.
    if not hasattr(engine, '_test_roster_tags'):
        engine._test_roster_tags = engine.load_data()
    return engine._test_roster_tags


@pytest.fixture(scope='session')
def roster(loaded_data):
    return loaded_data[0]


@pytest.fixture(scope='session')
def tags(loaded_data):
    return loaded_data[1]


@pytest.fixture(scope='session')
def prefix_data(engine, roster):
    """Result of build_per_prefix_data(roster) — (prefix_variants,
    prefix_count). Tests that pass prefix_variants to picker functions
    can use this directly."""
    return engine.build_per_prefix_data(roster)


@pytest.fixture(scope='session')
def prefix_variants(prefix_data):
    return prefix_data[0]


@pytest.fixture(scope='session')
def prefix_count(prefix_data):
    return prefix_data[1]
