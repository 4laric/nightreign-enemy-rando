"""sim_per_run.py determinism. The picker-distribution sim is a research
tool — its outputs (saved as sims/v0.27.45_baseline.json, etc.) are the
basis for cap-tuning A/B comparisons via the --diff workflow. A diff is
only meaningful if same (seed, settings) twice produces same numbers, so
this property is load-bearing.

Properties asserted:
  1. Same (seeds, rng_seed) twice -> identical result dict.
  2. Same (seeds, rng_seed) twice -> byte-identical saved JSON.
  3. Different rng_seed -> different result (the rng_seed actually matters).
  4. --grunts on a seed exercises v0.28 recycling (kind_totals['recycle'] > 0).
  5. --grunts off -> recycle rate is low (boss slots too sparse to saturate
     the per-MSB budget on their own; see the calibration anchor note in
     sim_per_run.py).

A small seed count is used (8 seeds) so the test runs in a few seconds.
The determinism property is binary — it either holds at 8 seeds or it
doesn't — so larger samples wouldn't surface anything more.
"""
import importlib.util
import io
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


@pytest.fixture(scope="module")
def sim_per_run():
    """Import dev/sim_per_run.py once; load_data() mutates engine globals
    so re-importing per-test would be wasteful and would also pollute the
    module-level oops_v3 across tests in unpredictable ways."""
    spec = importlib.util.spec_from_file_location(
        "sim_per_run_det", os.path.join(_ROOT, "dev", "sim_per_run.py"))
    m = importlib.util.module_from_spec(spec)
    # The module's load_data() chatter goes to stdout; suppress it here so
    # pytest output stays clean. Module import itself is silent — only
    # load_engine() inside the module triggers prints, and that happens
    # inside the helpers below, not at import time.
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def engine_and_tags(sim_per_run):
    """One-shot engine load; load_data() is expensive and idempotent
    enough that sharing across tests is safe."""
    # Silence load_data prints to keep test output clean.
    _real_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        o, tags = sim_per_run.load_engine()
        tags = sim_per_run.load_tags_with_overrides(o, tags)
    finally:
        sys.stdout = _real_stdout
    return o, tags


def _run(sim, o, tags, seeds, rng_seed, include_grunts=False,
         track_kinds=False):
    """Drive run_sim + summarize + build_result the same way main() does,
    so the test exercises the actual code path that produces saved JSON."""
    slots_by_class = sim.bucket_slots(o, tags, include_grunts=include_grunts)
    if track_kinds:
        per_seed, _, kinds = sim.run_sim(
            o, tags, slots_by_class,
            n_seeds=seeds, rng_seed=rng_seed,
            track_recycle_kinds=True)
    else:
        per_seed, _ = sim.run_sim(
            o, tags, slots_by_class,
            n_seeds=seeds, rng_seed=rng_seed)
        kinds = None
    summary = sim.summarize(per_seed, tags, o.V3_UNIQUE_TARGET_CAPS)
    result = sim.build_result(o, seeds, rng_seed, summary, slots_by_class,
                              include_grunts=include_grunts)
    return result, kinds


def test_same_settings_identical_result(sim_per_run, engine_and_tags):
    """Same (seeds, rng_seed) twice -> identical result dict."""
    o, tags = engine_and_tags
    a, _ = _run(sim_per_run, o, tags, seeds=8, rng_seed=0)
    b, _ = _run(sim_per_run, o, tags, seeds=8, rng_seed=0)
    assert a == b, (
        "sim_per_run produced different results for the same (seeds, "
        "rng_seed). Determinism broken — A/B diffs against saved baselines "
        "are no longer trustworthy.")


def test_same_settings_byte_identical_json(sim_per_run, engine_and_tags,
                                            tmp_path):
    """Same (seeds, rng_seed) twice -> byte-identical saved JSON.
    Catches dict-key-order drift that == comparison wouldn't notice but
    that would corrupt baseline diffs (which JSON-compare on disk)."""
    o, tags = engine_and_tags
    a, _ = _run(sim_per_run, o, tags, seeds=8, rng_seed=0)
    b, _ = _run(sim_per_run, o, tags, seeds=8, rng_seed=0)
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    for path, result in ((path_a, a), (path_b, b)):
        with open(path, 'w', encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=True)
            f.write('\n')
    bytes_a = path_a.read_bytes()
    bytes_b = path_b.read_bytes()
    assert bytes_a == bytes_b, (
        "JSON output differs byte-for-byte across identical-settings runs. "
        "Likely set-iteration leaking into key order somewhere despite "
        "sort_keys=True — check that no list-of-dicts is being saved with "
        "internal field ordering coming from a set.")


def test_different_rng_seed_diverges(sim_per_run, engine_and_tags):
    """rng_seed actually changes the output (sanity that the parameter
    isn't being ignored)."""
    o, tags = engine_and_tags
    a, _ = _run(sim_per_run, o, tags, seeds=8, rng_seed=0)
    b, _ = _run(sim_per_run, o, tags, seeds=8, rng_seed=42)
    assert a['cprefixes'] != b['cprefixes'], (
        "rng_seed change produced identical cprefixes — either rng_seed "
        "is being ignored or the sim collapsed to a deterministic constant.")


def test_grunts_mode_exercises_recycling(sim_per_run, engine_and_tags):
    """v0.28 hybrid picker: --grunts mode should fire 'recycle' kind
    substantially. The per-MSB budget (median 4 distinct cps) saturates
    within the first few grunt picks; subsequent slots in that MSB recycle.
    Production runs at ~75% recycle in grunts mode (see sim_per_run
    docstring); 30% is a generous floor that catches the case where
    recycling was wired but not actually firing."""
    o, tags = engine_and_tags
    _, kinds = _run(sim_per_run, o, tags, seeds=8, rng_seed=0,
                    include_grunts=True, track_kinds=True)
    total = sum(kinds.values())
    recycle = kinds.get('recycle', 0)
    fresh = kinds.get('fresh', 0)
    assert total > 0, "no picks at all — sim is degenerate"
    assert recycle / total > 0.30, (
        f"recycle rate {100 * recycle / total:.1f}% is suspiciously low for "
        f"--grunts mode (expect ~75%). Counts: {dict(kinds)}. Either the "
        f"per-MSB budget is unbounded (msb_budgets dict empty or all-large) "
        f"or _choose_with_budget isn't being called.")
    assert fresh > 0, "fresh count is zero — budget might be zero everywhere"


def test_boss_only_mode_mostly_fresh(sim_per_run, engine_and_tags):
    """Inverse of the grunts test: boss-only mode should rarely recycle
    because boss slots are sparse per MSB (often 1-2) and don't saturate
    the per-MSB budget. Production runs ~5% recycle in boss-only mode."""
    o, tags = engine_and_tags
    _, kinds = _run(sim_per_run, o, tags, seeds=8, rng_seed=0,
                    include_grunts=False, track_kinds=True)
    total = sum(kinds.values())
    recycle = kinds.get('recycle', 0)
    assert total > 0, "no picks at all"
    assert recycle / total < 0.20, (
        f"recycle rate {100 * recycle / total:.1f}% is suspiciously high for "
        f"boss-only mode (expect ~5%). Counts: {dict(kinds)}. Boss slots "
        f"shouldn't typically saturate the per-MSB budget on their own.")


def test_determinism_under_hash_randomization(tmp_path):
    """Cross-process determinism with PYTHONHASHSEED varying. Python's
    set/dict hash randomization is process-scoped — the same-process
    determinism tests above can't catch a bug where set iteration order
    leaks into output (because the test process has one fixed hash seed).
    Running the sim as a subprocess with different PYTHONHASHSEED values
    is the only way to surface that class of bug.

    Runs four subprocess invocations of dev/sim_per_run.py with different
    PYTHONHASHSEED values and asserts the saved JSON is byte-identical.
    A few seconds per subprocess; total ~5-10s with seeds=8."""
    import subprocess
    sim_path = os.path.join(_ROOT, "dev", "sim_per_run.py")
    hashes = {}
    for hash_seed in ('0', '1', '2', '3'):
        out_path = tmp_path / f"sim_h{hash_seed}.json"
        env = os.environ.copy()
        env['PYTHONHASHSEED'] = hash_seed
        # --rng-seed 0 keeps the picker rng identical; only PYTHONHASHSEED
        # varies, so anything that differs is from set/dict hash ordering.
        r = subprocess.run(
            [sys.executable, sim_path,
             '--seeds', '8', '--rng-seed', '0',
             '--save', str(out_path)],
            env=env, capture_output=True, text=True, cwd=_ROOT,
            timeout=120)
        assert r.returncode == 0, (
            f"sim subprocess failed (PYTHONHASHSEED={hash_seed}):\n"
            f"stdout: {r.stdout[-500:]}\nstderr: {r.stderr[-500:]}")
        hashes[hash_seed] = out_path.read_bytes()
    # All four byte-identical
    unique = set(hashes.values())
    assert len(unique) == 1, (
        f"sim_per_run output is hash-seed-dependent — {len(unique)} distinct "
        f"outputs across 4 PYTHONHASHSEED values. Some set or dict iteration "
        f"order is leaking into output. Suspect any list comprehension over "
        f"a set, dict.values() being json-dumped without sort_keys, or "
        f"set().union(*...) used as iteration order downstream.")
