"""v0.28 — the per-slot cp decision is a pure function of (seed, settings,
slot identity). Permuting the input enumeration order must NOT change the
resulting world. This is the property that kills the contaminated/reordered
base cascade (the old "same seed, different input -> totally different world"
failure): the decision no longer reads its randomness from a shared stream
whose position depends on how many slots came before it.

Implemented via three coupled changes:
  - pick_target_cp draws the cp from a per-slot hashed Random keyed on
    (seed, msb, pi) over a sorted pool (see _slot_decision_rng);
  - shuffle_msb_v3 processes slots in canonical part-index order so the
    order-dependent target_count cap is deterministic;
  - _compute_unique_reservations sorts its candidate slots so the scoring
    tiebreaks are input-order-independent.

Runs the MSB-free engine sim (dev/simulate_engine.py) over the canonical
slot inventory in several shuffled orders and asserts the swap_plan is
identical. No game assets required.
"""
import importlib.util
import json
import os
import random

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


@pytest.fixture(scope="module")
def sim():
    spec = importlib.util.spec_from_file_location(
        "sim_engine_det", os.path.join(_ROOT, "dev", "simulate_engine.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def data(sim):
    # Mirror dev/simulate_engine.py:main() data loading, using the sim's own
    # oops_v3 instance so the engine functions and data are consistent.
    o = sim.o
    roster = json.load(open(os.path.join(_ROOT, "data", "nr_enemy_roster.json")))
    _roster2, tags = o.load_data()
    pv, pc = o.build_per_prefix_data(roster)
    inv = json.load(open(os.path.join(_ROOT, "data", "nr_slot_inventory.json")))
    return roster, tags, pv, pc, inv


def _plan(sim, data, inventory, seed):
    roster, tags, pv, pc, _ = data
    return sim.simulate(seed, inventory, roster, tags, pv, pc)["swap_plan"]


@pytest.mark.parametrize("seed", [789157, 1, 42])
def test_swap_plan_invariant_under_input_reordering(sim, data, seed):
    """Same seed + settings, different input order -> identical swap_plan."""
    inv = data[4]
    base = list(inv)
    sh1 = list(inv); random.Random(seed ^ 0x111).shuffle(sh1)
    sh2 = list(inv); random.Random(seed ^ 0x222).shuffle(sh2)

    a = sorted(_plan(sim, data, base, seed))
    b = sorted(_plan(sim, data, sh1, seed))
    c = sorted(_plan(sim, data, sh2, seed))

    assert a == b == c, (
        "swap_plan changed under input reordering — the decision is not a "
        "pure function of (seed, settings, slot identity)")


def test_repeated_runs_are_identical(sim, data):
    """Determinism sanity: identical inputs run twice -> identical plan."""
    inv = data[4]
    a = _plan(sim, data, list(inv), 789157)
    b = _plan(sim, data, list(inv), 789157)
    assert a == b


def test_distinct_seeds_diverge(sim, data):
    """The decision still depends on the seed (not collapsed to a constant)."""
    inv = data[4]
    a = sorted(_plan(sim, data, list(inv), 1))
    b = sorted(_plan(sim, data, list(inv), 2))
    assert a != b
