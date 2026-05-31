"""Phase 6: Behavior-lock for load_data output across the three pack
configurations.

WHAT THIS LOCKS
---------------
For each of the three pre-built snapshots in data/snapshots/, this
test captures a canonical signature of load_data's output and asserts
it matches a committed fixture. The signature covers:

  - SHA256 of canonically-serialized tags dict (sorted by cp + keys)
  - SHA256 of canonically-serialized variants list (sorted)
  - Tags + variants count
  - _source breakdown across tags
  - Derived module state that load_data computes from input
    (V3_MP_SAFE_BLOCKLIST is recomputed each call from _source tagging,
    so it IS idempotent)
  - A spot-check of canonical cps' _source values

WHAT THIS DOESN'T LOCK
----------------------
The module-level gate sets V3_NIGHT_BOSS_CALIBER_TARGETS,
V3_HERITAGE_ALL_PREFIXES, V3_ARENA_ONLY_TARGETS
ACCUMULATE across load_data calls within a process (the loaders use
`V3_FOO = V3_FOO | new_keys` which never shrinks). The lock test
resets them to pristine values before each snapshot run — but the
contents AFTER load_data run are derived from the input pack JSONs in
a way that's perfectly idempotent given pristine starting state, so
they could be locked too. We're choosing not to lock them here
because they're large and a future refactor to make them
non-accumulating would not be a regression we want to flag here.

WHY THIS EXISTS
---------------
Pack_loaders extraction (Phase 7+) will move ~500 lines of inline
load_data logic into separate files. The per-function parity tests
from Phases 1-5 don't cover this surface — they assert that
`function(gates=GateState.from_module())` matches `function(gates=None)`,
which is silent on changes to what GOES INTO from_module(). This
lock catches "subtle change in which tags get loaded" — exactly the
class of regression pack_loaders extraction creates.

UPDATING FIXTURES
-----------------
When a load_data change is INTENTIONAL (adding a new pack, fixing a
bug, etc.), regenerate the fixture by running:

  python3 tests/test_load_data_lock.py --regenerate

The test asserts equivalence; the script regenerates. Two functions,
same file, separated by purpose.
"""
import hashlib
import io
import json
import os
import sys
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

import pytest

# Add project root to path so we can import oops_v3 / engine.
HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

import oops_v3  # noqa: E402


# -----------------------------------------------------------------------------
# Pristine state capture
# -----------------------------------------------------------------------------
# These get captured at TEST FILE IMPORT TIME, before any pytest fixture
# (including conftest.py's engine fixture) has had a chance to trigger
# load_data. pytest collects test files before running any tests, so
# this snapshot reflects the module-as-imported state.
#
# Caveat: if a future change to oops_v3 causes load_data to run at
# IMPORT time (it doesn't currently), this would no longer reflect
# pristine state. Add an assertion below to catch that case.

# Sanity: these specific gate sets should be POPULATED at import time
# (they're declared with set literals at the top of oops_v3). If any of
# them is empty, something has changed and we need to reconsider.
assert oops_v3.V3_HERITAGE_ALL_PREFIXES, (
    "V3_HERITAGE_ALL_PREFIXES is empty at module-import time — "
    "the pristine-state capture below assumes it's populated by set literal")
assert oops_v3.V3_EXCLUDE_TARGET_PREFIXES, (
    "V3_EXCLUDE_TARGET_PREFIXES is empty at module-import time")

# These start AT IMPORT TIME as either: (a) populated with declared
# values, or (b) empty set/dict and get filled by load_data. The
# pristine value is what they are RIGHT NOW (at this line of code).
# load_data has not been called yet within the test process for the
# first import of oops_v3 in this collection cycle.
_PRISTINE_STATE = {
    name: type(getattr(oops_v3, name))(getattr(oops_v3, name))
    for name in (
        'V3_HERITAGE_ALL_PREFIXES',
        'V3_NIGHT_BOSS_CALIBER_TARGETS',
        'V3_NIGHT_BOSS_STRICT_TARGETS',
        'V3_EXCLUDE_TARGET_PREFIXES',
        'V3_ARENA_ONLY_TARGETS',
        'V3_AVOID_VARIANT_NPC_IDS',
        'V3_MP_SAFE_BLOCKLIST',
        'V3_UNIQUE_TARGET_CAPS',
        'V3_SNAPSHOT_PACK_OVERRIDES',
    )
}


@contextmanager
def isolated_load_data(snapshot_path=None):
    """Run load_data() with module state isolated from the rest of the
    test session.

    Saves the current module state, restores pristine values, applies
    the snapshot (or clears overrides), runs load_data, yields the
    (roster, tags) output, then restores the saved state. Other tests
    are unaffected.

    Snapshot path is optional. None means "no snapshot active" — the
    pack JSONs are loaded with their _meta.enabled values intact (which
    in the canonical repo means all enabled, matching everything_enabled
    semantics).
    """
    # Save the current (possibly-mutated) state so we can put it back.
    saved = {
        name: type(getattr(oops_v3, name))(getattr(oops_v3, name))
        for name in _PRISTINE_STATE
    }
    try:
        # Reset to pristine before applying overrides.
        for name, value in _PRISTINE_STATE.items():
            setattr(oops_v3, name, type(value)(value))
        # Apply or clear the snapshot.
        if snapshot_path is not None:
            oops_v3.apply_pool_snapshot(snapshot_path)
        else:
            oops_v3.clear_pool_snapshot()
        # Run load_data. Suppress its chatty print output — the test
        # output should be quiet on green and verbose on red.
        with redirect_stdout(io.StringIO()):
            roster, tags = oops_v3.load_data()
        yield roster, tags
    finally:
        # Restore. Important to do this even if the test failed —
        # otherwise a leak here would cause every subsequent test in
        # the session to see weird state.
        for name, value in saved.items():
            setattr(oops_v3, name, value)
        # Clear any snapshot overrides we applied.
        oops_v3.V3_SNAPSHOT_PACK_OVERRIDES = saved['V3_SNAPSHOT_PACK_OVERRIDES']


# -----------------------------------------------------------------------------
# Signature computation
# -----------------------------------------------------------------------------

# These are the cps we spot-check the _source of. They span pack
# origins: nr_placed (vanilla), heritage (from heritage_pack), mmv_import
# (from mmv), post_dlc_dump (from the DLC dump section of
# nr_enemy_tags.json). If pack_loaders extraction subtly changes which
# pack a cp ends up sourced from, this list catches it.
_SAMPLE_CPS = [
    'c4500',   # Tree Sentinel — vanilla
    'c2130',   # Margit — vanilla
    'c4720',   # Godfrey — usually mmv_import
    'c5030',   # Romina — usually mmv_import
    'c4801',   # Lord of Blood Spear — usually post_dlc_dump
    'c4385',   # Disciple of Rot — usually heritage
    'c2272',   # Giant Black Crab — usually heritage
    'c5160',   # Fire Knight — usually heritage
]


def _canonical_dumps(obj):
    """Stable JSON serialization — sorted keys, default str fallback for
    non-JSON-native values (frozensets, None handling)."""
    return json.dumps(obj, sort_keys=True, default=str, separators=(',', ':'))


def compute_load_data_signature(roster, tags, module=oops_v3):
    """Produce a canonical, diffable signature of load_data's output.

    Top-level fields are inspectable on failure (counts, breakdowns,
    sample cps); the *_sha256 fields are fast-compare hash digests
    of the canonicalized full dicts/lists.

    When this fails in CI, the per-field diff tells you which axis
    of the load output drifted — count mismatch (a cp got added or
    removed), source-breakdown mismatch (a cp's _source changed),
    sample-cp mismatch (a known cp moved between packs), or finally
    a content-hash mismatch (something at the variant-level changed
    without affecting top-level counts).
    """
    from collections import Counter

    # Canonical sorted-keys serialization for hashing.
    tags_canonical = {
        cp: dict(sorted(t.items())) for cp, t in sorted(tags.items())
    }
    variants_canonical = sorted(
        roster.get('all_variants', []),
        key=lambda v: (v.get('c_prefix', ''),
                       v.get('npc_param_id', 0),
                       v.get('variant_name', ''))
    )

    return {
        'tags_count': len(tags),
        'variants_count': len(roster.get('all_variants', [])),
        'source_breakdown': dict(sorted(
            Counter(t.get('_source', '<no _source>')
                    for t in tags.values()).items())),
        'sample_cps': {
            cp: {
                '_source': tags.get(cp, {}).get('_source'),
                'name': tags.get(cp, {}).get('name'),
            }
            for cp in _SAMPLE_CPS
        },
        'mp_safe_blocklist_count': len(module.V3_MP_SAFE_BLOCKLIST),
        'mp_safe_blocklist_sha256': hashlib.sha256(
            _canonical_dumps(sorted(module.V3_MP_SAFE_BLOCKLIST))
            .encode()).hexdigest()[:16],
        # v0.24.22 (Phase 11 follow-up): lock the engine gate sets that
        # the post-loader auto-extend block populates. Before Phase 11
        # those sets accumulated via `try: except NameError:` reach-into
        # pack dicts; now they're computed from loader-returned stats.
        # The lock catches any drift in either path — load_data's gate-
        # set output is part of its contract, not just tags/variants.
        'arena_only_targets_count': len(module.V3_ARENA_ONLY_TARGETS),
        'arena_only_targets_sha256': hashlib.sha256(
            _canonical_dumps(sorted(module.V3_ARENA_ONLY_TARGETS))
            .encode()).hexdigest()[:16],
        'night_boss_caliber_count': len(module.V3_NIGHT_BOSS_CALIBER_TARGETS),
        'night_boss_caliber_sha256': hashlib.sha256(
            _canonical_dumps(sorted(module.V3_NIGHT_BOSS_CALIBER_TARGETS))
            .encode()).hexdigest()[:16],
        'night_boss_strict_count': len(module.V3_NIGHT_BOSS_STRICT_TARGETS),
        'night_boss_strict_sha256': hashlib.sha256(
            _canonical_dumps(sorted(module.V3_NIGHT_BOSS_STRICT_TARGETS))
            .encode()).hexdigest()[:16],
        'exclude_target_count': len(module.V3_EXCLUDE_TARGET_PREFIXES),
        'exclude_target_sha256': hashlib.sha256(
            _canonical_dumps(sorted(module.V3_EXCLUDE_TARGET_PREFIXES))
            .encode()).hexdigest()[:16],
        'avoid_variant_npc_ids_count': len(module.V3_AVOID_VARIANT_NPC_IDS),
        'avoid_variant_npc_ids_sha256': hashlib.sha256(
            _canonical_dumps(sorted(module.V3_AVOID_VARIANT_NPC_IDS))
            .encode()).hexdigest()[:16],
        'tags_sha256': hashlib.sha256(
            _canonical_dumps(tags_canonical).encode()).hexdigest()[:16],
        'variants_sha256': hashlib.sha256(
            _canonical_dumps(variants_canonical).encode()).hexdigest()[:16],
    }


# -----------------------------------------------------------------------------
# Fixture management
# -----------------------------------------------------------------------------

FIXTURE_PATH = HERE / 'fixtures' / 'load_data_lock.json'

SNAPSHOTS = {
    'vanilla_only': PROJECT_ROOT / 'data/snapshots/vanilla_only.snapshot.json',
    'vanilla_plus_heritage': PROJECT_ROOT / 'data/snapshots/vanilla_plus_heritage.snapshot.json',
    'everything_enabled': PROJECT_ROOT / 'data/snapshots/everything_enabled.snapshot.json',
}


def _load_fixture():
    """Load the committed fixture. Returns None if the file doesn't
    exist (first-run case — use --regenerate to create it)."""
    if not FIXTURE_PATH.exists():
        return None
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def regenerate_fixture():
    """Compute fresh signatures for every snapshot and write to the
    fixture file. Use when a load_data change is intentional.

    Called from the script entry point (python3 tests/test_load_data_lock.py
    --regenerate), not from tests."""
    new_fixture = {}
    for name, path in SNAPSHOTS.items():
        with isolated_load_data(str(path)) as (roster, tags):
            new_fixture[name] = compute_load_data_signature(roster, tags)
    FIXTURE_PATH.parent.mkdir(exist_ok=True)
    with open(FIXTURE_PATH, 'w') as f:
        json.dump(new_fixture, f, indent=2, sort_keys=True)
        f.write('\n')
    return new_fixture


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

@pytest.fixture(scope='module')
def fixture_data():
    """Load the committed fixture once per module."""
    data = _load_fixture()
    if data is None:
        pytest.skip(
            f'Fixture {FIXTURE_PATH} does not exist. Run '
            f'`python3 {__file__} --regenerate` to create it.')
    return data


class TestLoadDataLock:
    """For each snapshot, load_data should produce output matching the
    committed signature. Failure means EITHER (a) load_data semantics
    changed intentionally — regenerate the fixture — OR (b) a refactor
    silently changed what gets loaded — that's the bug.
    """

    @pytest.mark.parametrize('snapshot_name', list(SNAPSHOTS))
    def test_snapshot_locked(self, snapshot_name, fixture_data):
        expected = fixture_data[snapshot_name]
        with isolated_load_data(str(SNAPSHOTS[snapshot_name])) as (roster, tags):
            actual = compute_load_data_signature(roster, tags)

        # Compare field-by-field so the diff is readable on failure.
        # Counts and breakdowns come first — they're easiest to interpret.
        # Hashes come last — they're the silent regressors.
        # `_SENTINEL` distinguishes "field missing from fixture" (fixture
        # is stale — regenerate) from "field present but different value"
        # (a real signature drift). Without it the absent-from-fixture
        # case raises KeyError instead of producing a readable diff.
        _SENTINEL = object()
        mismatches = []
        for key in ('tags_count', 'variants_count',
                    'mp_safe_blocklist_count',
                    # v0.24.22: gate-set counts.
                    'arena_only_targets_count',
                    'night_boss_caliber_count',
                    'night_boss_strict_count',
                    'exclude_target_count',
                    'avoid_variant_npc_ids_count'):
            exp = expected.get(key, _SENTINEL)
            if exp is _SENTINEL:
                mismatches.append(
                    f'  {key}: MISSING FROM FIXTURE (stale — regenerate)')
            elif actual[key] != exp:
                mismatches.append(
                    f'  {key}: expected {exp}, got {actual[key]}')
        if actual['source_breakdown'] != expected['source_breakdown']:
            mismatches.append(
                f'  source_breakdown:\n'
                f'    expected {expected["source_breakdown"]}\n'
                f'    got      {actual["source_breakdown"]}')
        for cp in _SAMPLE_CPS:
            exp = expected['sample_cps'].get(cp, {})
            act = actual['sample_cps'].get(cp, {})
            if exp != act:
                mismatches.append(
                    f'  sample_cps[{cp}]: expected {exp}, got {act}')
        for key in ('tags_sha256', 'variants_sha256',
                    'mp_safe_blocklist_sha256',
                    # v0.24.22: gate-set content hashes.
                    'arena_only_targets_sha256',
                    'night_boss_caliber_sha256',
                    'night_boss_strict_sha256',
                    'exclude_target_sha256',
                    'avoid_variant_npc_ids_sha256'):
            exp = expected.get(key, _SENTINEL)
            if exp is _SENTINEL:
                mismatches.append(
                    f'  {key}: MISSING FROM FIXTURE (stale — regenerate)')
            elif actual[key] != exp:
                mismatches.append(
                    f'  {key}: expected {exp}, got {actual[key]} '
                    f'(content drift not captured by other fields)')

        if mismatches:
            raise AssertionError(
                f'load_data signature mismatch for snapshot {snapshot_name!r}:\n'
                + '\n'.join(mismatches)
                + f'\n\nIf this change was intentional, regenerate the fixture:\n'
                + f'  python3 {__file__} --regenerate')


class TestIsolatedLoadDataContextManager:
    """Sanity checks on the isolation primitive itself. If these fail,
    the lock tests above can't be trusted because their isolation is
    broken.
    """

    def test_isolated_load_data_restores_module_state(self):
        # Before the with-block: capture state.
        before = {
            name: type(getattr(oops_v3, name))(getattr(oops_v3, name))
            for name in _PRISTINE_STATE
        }
        with isolated_load_data(str(SNAPSHOTS['everything_enabled'])):
            # Inside the with-block, module state has been reset to
            # pristine then mutated by load_data. We can't assert much
            # about it without coupling to load_data semantics, just
            # confirm it didn't crash.
            pass
        after = {
            name: getattr(oops_v3, name) for name in _PRISTINE_STATE
        }
        # State after should equal state before. Use sets for comparison
        # to be type-agnostic (frozenset vs set differences).
        for name in _PRISTINE_STATE:
            if isinstance(before[name], (set, frozenset)):
                assert set(after[name]) == set(before[name]), (
                    f'{name} not restored after isolated_load_data')
            else:
                assert after[name] == before[name], (
                    f'{name} not restored after isolated_load_data')

    def test_different_snapshots_produce_different_signatures(self):
        # The whole reason this test file exists is that snapshots
        # matter. Verify they actually produce different outputs.
        sigs = {}
        for name, path in SNAPSHOTS.items():
            with isolated_load_data(str(path)) as (roster, tags):
                sigs[name] = compute_load_data_signature(roster, tags)
        # All three should have different tags_sha256.
        hashes = {name: s['tags_sha256'] for name, s in sigs.items()}
        assert len(set(hashes.values())) == 3, (
            f'Snapshots collapse to same hash: {hashes}')
        # And monotonic count: vanilla_only < heritage < everything_enabled.
        assert (sigs['vanilla_only']['tags_count']
                < sigs['vanilla_plus_heritage']['tags_count']
                < sigs['everything_enabled']['tags_count']), (
            f'Snapshot tag counts not monotonic: '
            f'vanilla_only={sigs["vanilla_only"]["tags_count"]}, '
            f'heritage={sigs["vanilla_plus_heritage"]["tags_count"]}, '
            f'everything={sigs["everything_enabled"]["tags_count"]}')


# -----------------------------------------------------------------------------
# CLI: regenerate the fixture
# -----------------------------------------------------------------------------

if __name__ == '__main__':
    if '--regenerate' in sys.argv:
        print(f'Regenerating fixture: {FIXTURE_PATH}')
        new = regenerate_fixture()
        for name, sig in new.items():
            print(f'  {name}: tags={sig["tags_count"]} '
                  f'variants={sig["variants_count"]} '
                  f'mp_safe={sig["mp_safe_blocklist_count"]} '
                  f'tags_sha={sig["tags_sha256"]}')
        print('Done. Review the diff with git and commit if it looks right.')
    else:
        print(__doc__)
        print(f'\nFixture lives at: {FIXTURE_PATH}')
        print(f'Run `python3 {__file__} --regenerate` to (re)create it.')
        sys.exit(1)
