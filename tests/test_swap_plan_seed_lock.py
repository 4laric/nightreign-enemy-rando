"""Integration lock: simulate_engine produces stable swap_plans per seed.

WHAT THIS LOCKS
---------------
End-to-end pipeline regression catcher for the decision layer:

  load_data → _compute_msb_budgets → _compute_unique_reservations →
    (per MSB) begin_msb → (per slot) pick_target_cp → end_msb →
    final placed_counts + swap_plan

For each fixed seed in SEEDS, the test:
  1. Runs dev/simulate_engine.simulate(seed, ...) end-to-end against
     data/nr_slot_inventory.json (MSB-free path; no game data).
  2. Computes a canonical signature (SHA256 of sorted swap_plan,
     plus a handful of human-readable invariants).
  3. Asserts the signature matches the committed fixture
     tests/fixtures/swap_plan_seed_lock.json.

What this catches that fat unit tests don't
-------------------------------------------
Bugs whose surface is the COMBINATION of components — pipeline
ordering issues, state leaking between components, picker/
reservation drift, accidental changes to recycling behavior, etc.
The v0.24.27 mirror-bug class (NB-caliber gate added to runtime
but not to reservation-pass scorer) is exactly this shape — the
runtime path's unit tests passed, the scorer's unit tests passed,
but the pipeline-level "did the reservation pass pick something
the picker would reject" property silently broke.

What this DOESN'T cover
-----------------------
The MSB-binary write path (model-index reassignment, npc_param /
think_param patching at PART_OFF_* offsets, position shifts,
sidecar copying). Those need real MSB binaries and Oodle, which
aren't checkable. The decision layer is the high-leverage half —
once the swap_plan is right, the MSB write is mechanical.

REGENERATING THE FIXTURE
------------------------
When a change to the decision pipeline is intentional (new gate,
new cap policy, new chr added, etc.), run:

  python3 tests/test_swap_plan_seed_lock.py --regenerate

Review the diff with git, sanity-check the new numbers, commit.

The fixture is small (~few KB) — committing the snapshot is fine.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
FIXTURE_PATH = _HERE / 'fixtures' / 'swap_plan_seed_lock.json'

# Seeds locked here. Pick a handful — coverage is per-pipeline, not
# per-seed; each seed exercises the same code paths with different
# RNG draws, and catching one regression typically catches all of
# them. Three is the sweet spot: enough to confirm "not a one-seed
# fluke" but cheap enough to keep test runtime reasonable
# (~5s per seed).
#
# 42:     classic.
# 789157: shared with test_decision_determinism.py — keeps fixtures
#         coherent across the integration-test layer.
# 12345:  arbitrary; exercises a different RNG path.
SEEDS = [42, 789157, 12345]


# Settings-axis cases: (case_id, seed, settings_dict). The settings
# axis exists separately from SEEDS because most settings are
# expensive (each run costs ~5s) and we want to confirm coverage of
# the SETTING'S EFFECT rather than the (seed × setting) cross-
# product.
#
# Each case re-runs seed=42 (so a developer can compare against the
# baseline "42" entry to see what the setting changed). The case_id
# becomes both the parametrize ID and the fixture key.
#
#   mp_safe: V3_GHOST_EXCLUDE_TARGET_PREFIXES is unioned with
#       V3_MP_SAFE_BLOCKLIST via engine.runtime.apply_run_overrides
#       context manager. Heritage cps that are normally selectable
#       become unselectable. The SHA flip vs baseline IS the proof
#       the setting is wired through.
#   sote_mode: V3_SOTE_MODE module flag is toggled to True for the
#       duration of simulate(). The picker reads this flag and
#       applies the v0.24.x SoTE prefix-gating rules. Same shape:
#       the SHA flip vs baseline is the proof.
#   chaos_mode: simulate() takes chaos_mode as a kwarg (added v0.28.x)
#       and forwards to o.pick_target. The picker activates the
#       v0.23.11 asymmetric NB-tier gating (NB chrs leak down to
#       field slots; field bosses can't leak up to NB arenas).
#       Reshuffles ~half the swap_plan vs baseline — heavy axis.
SETTINGS_CASES = [
    ('42_mp_safe',    42, {'multiplayer_safe': True}),
    ('42_sote_mode',  42, {'sote_mode': True}),
    ('42_chaos_mode', 42, {'chaos_mode': True}),
]


# -----------------------------------------------------------------------------
# simulate_engine module loader (dev/, not on path; use spec_from_file_location)
# -----------------------------------------------------------------------------

def _load_simulate_engine():
    """Load dev/simulate_engine.py as a module without polluting sys.modules.

    simulate_engine itself does `spec_from_file_location('o', oops_v3.py)`
    at import time, so loading it triggers oops_v3 load_data() etc. We
    just need it to be importable; the engine's `o` reference is captured
    on the module itself."""
    path = _ROOT / 'dev' / 'simulate_engine.py'
    spec = importlib.util.spec_from_file_location('sim_seed_lock', str(path))
    m = importlib.util.module_from_spec(spec)
    # Silence load_data() and reservation-pass prints — keep test output clean
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(m)
    return m


# -----------------------------------------------------------------------------
# Signature computation
# -----------------------------------------------------------------------------

def compute_swap_plan_signature(result: dict) -> dict:
    """Canonical signature of a simulate() result. The components:

    swap_plan_sha256:
      SHA256 of the sorted swap_plan, serialized as JSON. The plan is
      a list of (msb, pi, target_cp) tuples; sorting makes the hash
      order-independent. Any change to the picker's output for any
      slot flips this hash.

    n_placements / n_reservations / n_no_target:
      Human-readable headline counts. A regression that changes these
      shows up clearly in the diff before you read the SHA.

    n_distinct_targets:
      Distinct c-prefixes placed. Surfaces variety regressions (e.g.
      caps inadvertently removed → fewer distinct targets).

    placed_counts_top_10:
      The 10 most-placed c-prefixes with their counts. Sorted by count
      descending, then by cp ascending for tiebreak. Catches the
      "wrong chr suddenly dominating placements" failure mode that's
      hard to spot from a raw SHA.

    unique_reservation_count:
      Length of the run_ctx.unique_reservations dict. Catches
      reservation-pass regressions (cap=2 spread, floor coverage,
      etc.) independently of the main swap loop.
    """
    swap_plan = result['swap_plan']  # list of (msb, pi, cp)
    swap_plan_sorted = sorted(swap_plan)
    sha = hashlib.sha256(
        json.dumps(swap_plan_sorted, sort_keys=True).encode('utf-8')
    ).hexdigest()

    placed_counts = result.get('placed_counts', {})
    top_10 = sorted(
        placed_counts.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )[:10]

    return {
        'swap_plan_sha256':       sha,
        'n_placements':           result['n_placements'],
        'n_reservations':         result['n_reservations'],
        'n_no_target':            result['n_no_target'],
        'n_distinct_targets':     len(placed_counts),
        'placed_counts_top_10':   [[cp, n] for cp, n in top_10],
        'unique_reservation_count': len(result.get('unique_placed_counts', {})),
    }


def run_one_seed(sim, env: dict, seed: int) -> dict:
    """Run simulate() for a single seed against the shared env, return
    the canonical signature.

    `env` is the (inventory, roster, tags, pv, pc, budgets, pi_to_cid,
    cluster_budgets) bundle that's expensive to compute and is shared
    across seeds.

    Prints from the engine's reservation pre-pass are suppressed.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        result = sim.simulate(
            seed,
            env['inventory'],
            env['roster'],
            env['tags'],
            env['pv'],
            env['pc'],
            msb_budgets=env['msb_budgets'],
            pi_to_cid_by_msb=env['pi_to_cid'],
            cluster_budgets=env['cluster_budgets'],
        )
    return compute_swap_plan_signature(result)


def run_one_seed_with_settings(sim, env: dict, seed: int,
                               settings: dict) -> dict:
    """Run simulate() for a single seed with engine settings applied.

    The settings dict supports:
      multiplayer_safe (bool): union V3_GHOST_EXCLUDE_TARGET_PREFIXES
          with V3_MP_SAFE_BLOCKLIST for the duration of simulate().
          Uses engine.runtime.apply_run_overrides which restores state
          on exit. Non-invasive — no module mutation outlives the call.
      sote_mode (bool): set V3_SOTE_MODE = True for the duration of
          simulate(). Restored in `finally`. The picker reads this
          flag at decision time so the setting takes effect mid-run.
      chaos_mode (bool): forwarded to simulate() as a kwarg, which
          threads it through to o.pick_target. The picker activates
          the v0.23.11 asymmetric NB-tier gating. No module-state
          mutation needed — simulate()'s chaos_mode arg is the
          end-to-end vehicle.

    Other settings (disable_resilient_filter, force_include_targets,
    etc.) aren't plumbed through dev/simulate_engine.simulate() and
    would need either an API extension or a monkey-patch — deferred
    to a follow-up.
    """
    o = sim.o

    # Suppress apply_run_overrides' own status prints.
    silent_log = lambda *a, **k: None  # noqa: E731

    mp_safe = settings.get('multiplayer_safe', False)
    sote    = settings.get('sote_mode', False)
    chaos   = settings.get('chaos_mode', False)

    # sote_mode is a single module flag — flip + restore manually.
    sote_restore_value = None
    if sote:
        sote_restore_value = getattr(o, 'V3_SOTE_MODE', False)
        o.V3_SOTE_MODE = True

    def _do_run():
        # chaos_mode threads through simulate() as a kwarg; pull it
        # into a closure so the run helpers don't need to know about
        # it. When chaos=False, this behaves identically to the
        # default-arg path used by the seed-only tests above.
        with contextlib.redirect_stdout(io.StringIO()):
            result = sim.simulate(
                seed,
                env['inventory'],
                env['roster'],
                env['tags'],
                env['pv'],
                env['pc'],
                msb_budgets=env['msb_budgets'],
                pi_to_cid_by_msb=env['pi_to_cid'],
                cluster_budgets=env['cluster_budgets'],
                chaos_mode=chaos,
            )
        return compute_swap_plan_signature(result)

    try:
        if mp_safe:
            # apply_run_overrides is a context manager that mutates
            # module state and restores on exit. Even if simulate()
            # raises, the original state is put back.
            #
            # `module=o` is required: simulate_engine loads oops_v3
            # via spec_from_file_location which doesn't register in
            # sys.modules, so the implicit fallback would raise
            # RuntimeError (see _resolve_module_or_raise in
            # engine.runtime — designed exactly to catch this
            # footgun loudly).
            with o.apply_run_overrides(o, multiplayer_safe=True,
                                       log=silent_log):
                return _do_run()
        else:
            return _do_run()
    finally:
        if sote:
            o.V3_SOTE_MODE = sote_restore_value


# -----------------------------------------------------------------------------
# Fixture I/O
# -----------------------------------------------------------------------------

def _load_fixture():
    if not FIXTURE_PATH.exists():
        return None
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def regenerate_fixture():
    """Compute fresh signatures for every locked seed and every
    settings case, and write to the fixture file. Use when a
    decision-pipeline change is intentional.

    Called from the script entry point (python3 tests/test_swap_plan_seed_lock.py
    --regenerate), not from tests."""
    sim = _load_simulate_engine()
    env = _build_env(sim)
    new_fixture = {
        '_schema': 'swap_plan_seed_lock_v2',
        '_seeds':  SEEDS,
        '_settings_cases': [
            {'case_id': cid, 'seed': s, 'settings': st}
            for cid, s, st in SETTINGS_CASES
        ],
        'seeds':          {},
        'settings_cases': {},
    }
    for seed in SEEDS:
        sig = run_one_seed(sim, env, seed)
        new_fixture['seeds'][str(seed)] = sig
    for case_id, seed, settings in SETTINGS_CASES:
        sig = run_one_seed_with_settings(sim, env, seed, settings)
        new_fixture['settings_cases'][case_id] = sig
    FIXTURE_PATH.parent.mkdir(exist_ok=True)
    with open(FIXTURE_PATH, 'w', encoding="utf-8") as f:
        json.dump(new_fixture, f, indent=2, sort_keys=True)
        f.write('\n')
    return new_fixture


def _build_env(sim) -> dict:
    """Bundle the per-run env computed once per regenerate or test
    module load. Mirrors what dev/simulate_engine.main() does."""
    o = sim.o
    with contextlib.redirect_stdout(io.StringIO()):
        inventory = sim._load_inventory()
        roster, tags = o.load_data()
        pv, pc = o.build_per_prefix_data(roster)
        msb_budgets = sim._compute_msb_budgets(o, pv, inventory)
        _clusters, pi_to_cid = sim._load_poi_clusters()
        cluster_budgets = sim._compute_cluster_budgets(o, pv, inventory, pi_to_cid)
    return dict(
        inventory=inventory, roster=roster, tags=tags,
        pv=pv, pc=pc,
        msb_budgets=msb_budgets, pi_to_cid=pi_to_cid,
        cluster_budgets=cluster_budgets,
    )


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

@pytest.fixture(scope='module')
def fixture_data():
    data = _load_fixture()
    if data is None:
        pytest.skip(
            f'Fixture {FIXTURE_PATH} does not exist. Run '
            f'`python3 {__file__} --regenerate` to create it.')
    return data


@pytest.fixture(scope='module')
def sim_env():
    """Single-build env shared across all seeds in the test module.
    Building (load_data + budgets + cluster scan) costs ~0.5s; doing
    it once amortizes it across 3 seed tests."""
    sim = _load_simulate_engine()
    env = _build_env(sim)
    env['_sim'] = sim
    return env


class TestSwapPlanSeedLock:
    """For each locked seed, simulate_engine must produce a swap_plan
    matching the committed signature.

    Failure means EITHER (a) the decision pipeline changed in a way
    that altered swap_plan output for at least one seed — regenerate
    if intentional — OR (b) a refactor silently broke the pipeline.
    The headline-count fields (n_placements, n_reservations,
    n_distinct_targets, top-10) usually tell you which one before
    you reach for git blame.
    """

    @pytest.mark.parametrize('seed', SEEDS)
    def test_seed_signature_matches_fixture(self, fixture_data, sim_env, seed):
        sim = sim_env['_sim']
        actual = run_one_seed(sim, sim_env, seed)

        expected = fixture_data['seeds'].get(str(seed))
        assert expected is not None, (
            f'Seed {seed} is locked in SEEDS but not in the fixture. '
            f'Run `python3 {__file__} --regenerate`.'
        )

        # Lead with the human-readable diff so the assert message
        # surfaces the most useful info before the SHA-vs-SHA noise.
        mismatches = []
        for key in (
            'n_placements', 'n_reservations', 'n_no_target',
            'n_distinct_targets', 'unique_reservation_count',
        ):
            if actual[key] != expected[key]:
                mismatches.append(
                    f'  {key}: expected={expected[key]} actual={actual[key]}'
                )
        if actual['placed_counts_top_10'] != expected['placed_counts_top_10']:
            mismatches.append(
                f'  placed_counts_top_10 drifted:\n'
                f'    expected: {expected["placed_counts_top_10"]}\n'
                f'    actual:   {actual["placed_counts_top_10"]}'
            )
        if actual['swap_plan_sha256'] != expected['swap_plan_sha256']:
            # Only report SHA mismatch if other fields are equal —
            # otherwise the headline counts already explain it.
            if not mismatches:
                mismatches.append(
                    f'  swap_plan_sha256: expected={expected["swap_plan_sha256"]} '
                    f'actual={actual["swap_plan_sha256"]} '
                    f'(headline counts unchanged — likely a per-slot pick '
                    f'difference; review with --regenerate + git diff to '
                    f'find which slots flipped)'
                )

        assert not mismatches, (
            f'\nSwap plan signature drift for seed {seed}:\n'
            + '\n'.join(mismatches)
            + f'\n\nIf this change is intentional: '
            f'`python3 {__file__} --regenerate`'
        )


class TestSwapPlanSettingsLock:
    """For each (seed, settings) case in SETTINGS_CASES, simulate_engine
    with those settings applied must produce a swap_plan matching the
    committed signature.

    Failure means EITHER (a) intended change to a setting's effect —
    regenerate the fixture — OR (b) a setting silently stopped taking
    effect, OR (c) a refactor broke pipeline behavior under that
    setting. The differs-from-baseline sanity test in this class
    distinguishes (b) from the other two: if the SHA matches baseline
    seed=42 exactly, the setting probably isn't being applied at all.
    """

    @pytest.mark.parametrize('case_id,seed,settings', SETTINGS_CASES,
                             ids=[c[0] for c in SETTINGS_CASES])
    def test_settings_case_signature_matches_fixture(
            self, fixture_data, sim_env, case_id, seed, settings):
        sim = sim_env['_sim']
        actual = run_one_seed_with_settings(sim, sim_env, seed, settings)

        expected = fixture_data.get('settings_cases', {}).get(case_id)
        assert expected is not None, (
            f'Settings case {case_id!r} is in SETTINGS_CASES but not '
            f'in the fixture. Run `python3 {__file__} --regenerate`.'
        )

        mismatches = []
        for key in (
            'n_placements', 'n_reservations', 'n_no_target',
            'n_distinct_targets', 'unique_reservation_count',
        ):
            if actual[key] != expected[key]:
                mismatches.append(
                    f'  {key}: expected={expected[key]} actual={actual[key]}'
                )
        if actual['placed_counts_top_10'] != expected['placed_counts_top_10']:
            mismatches.append(
                f'  placed_counts_top_10 drifted:\n'
                f'    expected: {expected["placed_counts_top_10"]}\n'
                f'    actual:   {actual["placed_counts_top_10"]}'
            )
        if actual['swap_plan_sha256'] != expected['swap_plan_sha256']:
            if not mismatches:
                mismatches.append(
                    f'  swap_plan_sha256: expected={expected["swap_plan_sha256"]} '
                    f'actual={actual["swap_plan_sha256"]} '
                    f'(headline counts unchanged — per-slot pick difference '
                    f'under settings {settings})'
                )

        assert not mismatches, (
            f'\nSwap plan signature drift for {case_id} '
            f'(seed={seed}, settings={settings}):\n'
            + '\n'.join(mismatches)
            + f'\n\nIf this change is intentional: '
            f'`python3 {__file__} --regenerate`'
        )

    @pytest.mark.parametrize('case_id,seed,settings', SETTINGS_CASES,
                             ids=[c[0] for c in SETTINGS_CASES])
    def test_settings_actually_change_swap_plan(
            self, fixture_data, case_id, seed, settings):
        """A settings case must differ from its corresponding baseline
        seed entry. If they match exactly, the setting isn't being
        applied — the test would otherwise silently pass even when
        the entire override mechanism is broken."""
        baseline = fixture_data['seeds'].get(str(seed))
        case = fixture_data['settings_cases'].get(case_id)
        assert baseline is not None and case is not None, (
            f'Missing fixture entries for comparison: '
            f'baseline_seed={baseline is not None}, case={case is not None}'
        )
        assert baseline['swap_plan_sha256'] != case['swap_plan_sha256'], (
            f'{case_id}: swap_plan SHA matches baseline seed={seed} — '
            f'settings {settings} appears to have no effect on the '
            f'decision pipeline. Either the setting plumbing is broken '
            f'or the setting is genuinely a no-op for this seed (very '
            f'unlikely for the locked seeds).'
        )


class TestFixtureMetadata:
    """Sanity-check the fixture itself — guards against fixture-file
    corruption or stale seed lists."""

    def test_fixture_seeds_match_module_SEEDS(self, fixture_data):
        """The fixture's _seeds list must match the module's SEEDS
        constant. If they drift, the parametrize ID strings would
        line up with stale fixture entries (or vice-versa)."""
        assert fixture_data.get('_seeds') == SEEDS, (
            f'Fixture _seeds {fixture_data.get("_seeds")} != '
            f'module SEEDS {SEEDS}. Either re-sync the constant or '
            f'`python3 {__file__} --regenerate`.'
        )

    def test_fixture_settings_cases_match_module(self, fixture_data):
        """Same drift guard for the settings axis."""
        expected = [
            {'case_id': cid, 'seed': s, 'settings': st}
            for cid, s, st in SETTINGS_CASES
        ]
        assert fixture_data.get('_settings_cases') == expected, (
            f'Fixture _settings_cases {fixture_data.get("_settings_cases")} '
            f'!= module SETTINGS_CASES {expected}. Either re-sync the '
            f'constant or `python3 {__file__} --regenerate`.'
        )

    def test_fixture_schema_version(self, fixture_data):
        assert fixture_data.get('_schema') == 'swap_plan_seed_lock_v2', (
            f'Fixture schema mismatch — got '
            f'{fixture_data.get("_schema")!r}, expected '
            f'"swap_plan_seed_lock_v2". A schema bump means the '
            f'signature shape changed; regenerate.'
        )


# -----------------------------------------------------------------------------
# CLI: regenerate the fixture
# -----------------------------------------------------------------------------

if __name__ == '__main__':
    if '--regenerate' in sys.argv:
        print(f'Regenerating fixture: {FIXTURE_PATH}')
        new = regenerate_fixture()
        for seed_str, sig in sorted(new['seeds'].items(),
                                    key=lambda kv: int(kv[0])):
            print(f'  seed={seed_str:>12}: placements={sig["n_placements"]:>5} '
                  f'reservations={sig["n_reservations"]:>3} '
                  f'distinct={sig["n_distinct_targets"]:>3} '
                  f'sha={sig["swap_plan_sha256"][:16]}...')
        for case_id, sig in sorted(new['settings_cases'].items()):
            print(f'  case={case_id:>12}: placements={sig["n_placements"]:>5} '
                  f'reservations={sig["n_reservations"]:>3} '
                  f'distinct={sig["n_distinct_targets"]:>3} '
                  f'sha={sig["swap_plan_sha256"][:16]}...')
        print('Done. Review with `git diff tests/fixtures/swap_plan_seed_lock.json` '
              'and commit if it looks right.')
    else:
        print(__doc__)
        print(f'\nFixture lives at: {FIXTURE_PATH}')
        print(f'Run `python3 {__file__} --regenerate` to (re)create it.')
        sys.exit(1)
