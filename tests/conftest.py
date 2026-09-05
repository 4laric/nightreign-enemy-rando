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
import contextlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)

import oops_v3  # noqa: E402  — path setup above


# ---------------------------------------------------------------------------
# Pool-config baselines
# ---------------------------------------------------------------------------
# The global suite baseline is the SHIPPED default pool:
# data/mmv_imports.json carries _meta.enabled=false (intentional — enabling
# MMV without the mod installed CTDs the game; see the pack's
# _meta.enable_instructions and the GUI's MMV opt-in checkbox), and the
# committed data/placement_budget.json matches a clean-process extraction
# against that MMV-off state (verified 2026-09: byte-identical).
#
# A minority of tests were authored against the dev-canonical
# "everything enabled" pool and reference MMV-only content (c6200 Gael,
# c8500 Manus, c5030 Romina, ...). Those tests opt in via the
# `everything_enabled_engine` fixture below, which applies the shipped
# data/snapshots/everything_enabled.snapshot.json override INSIDE an
# isolated context that restores all mutable module globals afterwards,
# so MMV state never leaks into the rest of the session.

EVERYTHING_ENABLED_SNAPSHOT = os.path.join(
    PROJECT_ROOT, 'data', 'snapshots', 'everything_enabled.snapshot.json')

# load_data() mutates module globals cumulatively (V3_* sets/dicts only
# grow across calls). Rather than enumerate them (the explicit 9-name
# list in test_load_data_lock.py missed V3_RESERVATION_FLOORS,
# V3_SOTE_PREFIXES, V3_RIDER_PREFIXES, V3_MOUNT_PREFIXES,
# _V3_SLOT_POI_CLUSTERS, ...), snapshot every V3_*/_V3_* attribute
# generically and restore on exit, dropping any the block added.
def _save_v3_globals():
    snap = {}
    for name, value in vars(oops_v3).items():
        if name.startswith('V3_') or name.startswith('_V3_'):
            if isinstance(value, (set, frozenset, dict, list)):
                snap[name] = type(value)(value)
            else:
                snap[name] = value
    return snap


def _restore_v3_globals(snap):
    for name in list(vars(oops_v3)):
        if (name.startswith('V3_') or name.startswith('_V3_')) \
                and name not in snap:
            delattr(oops_v3, name)
    for name, value in snap.items():
        setattr(oops_v3, name, value)


@contextlib.contextmanager
def isolated_pool_snapshot(snapshot_path):
    """Apply a pool snapshot (pack _meta overrides) for the duration of
    the block, saving/restoring every load_data-mutable module global so
    the session baseline is untouched afterwards."""
    saved = _save_v3_globals()
    try:
        oops_v3.apply_pool_snapshot(snapshot_path)
        yield oops_v3
    finally:
        _restore_v3_globals(saved)


@pytest.fixture()
def everything_enabled_engine():
    """oops_v3 with all packs (incl. MMV) enabled, for tests authored
    against the dev-canonical pool. Runs a fresh load_data() with the
    everything_enabled snapshot applied, then restores the session's
    MMV-off baseline on teardown."""
    import io
    from contextlib import redirect_stdout
    with isolated_pool_snapshot(EVERYTHING_ENABLED_SNAPSHOT):
        with redirect_stdout(io.StringIO()):
            oops_v3.load_data()
        yield oops_v3


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
