"""Engine integration test: the v0.31 off-mesh wake-rescue restriction holds
over the REAL placement engine, MSB-free.

Runs dev/simulate_engine.py (the full pick_target_cp / reservation /
rejection cascade over the canonical slot inventory — no game assets) and
asserts the core v0.31 invariant on the actual swap plan:

  Every enemy placed at an off-mesh slot is either
    (a) wake-rescuable — a full-backstab humanoid the proximity wake can
        un-freeze in place (data/backstab_tiers.json), OR
    (b) a unique-target RESERVATION (V3_UNIQUE_TARGET_CAPS), which the
        picker places at its reserved slot via the reservation early-return,
        before the off-mesh gate.

A non-rescuable, non-reserved enemy at an off-mesh slot would freeze/float
in-game — exactly the failure the wake-rescue approach replaced slot-
repositioning to avoid.

Slow (~8s per simulated seed). Seeds configurable via SIM_SEEDS.
"""
import contextlib
import importlib.util
import io
import json
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
SEEDS = [int(s) for s in os.environ.get('SIM_SEEDS', '1,7').split(',') if s]


@pytest.fixture(scope="module")
def env():
    spec = importlib.util.spec_from_file_location(
        "sim_offmesh", os.path.join(_ROOT, "dev", "simulate_engine.py"))
    with contextlib.redirect_stdout(io.StringIO()):       # engine is chatty
        sim = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sim)
        o = sim.o
        roster = json.load(
            open(os.path.join(_ROOT, "data", "nr_enemy_roster.json")))
        _r, tags = o.load_data()
        pv, pc = o.build_per_prefix_data(roster)
    inv = json.load(open(os.path.join(_ROOT, "data", "nr_slot_inventory.json")))
    return {
        'sim': sim, 'o': o, 'roster': roster, 'tags': tags,
        'pv': pv, 'pc': pc, 'inv': inv,
        'off': o._load_off_mesh_slots(),
        'resc': set(o._load_backstab_rescuable_prefixes()),
        'caps': o.V3_UNIQUE_TARGET_CAPS,
    }


def _plan(env, seed):
    with contextlib.redirect_stdout(io.StringIO()):
        return env['sim'].simulate(
            seed, env['inv'], env['roster'], env['tags'],
            env['pv'], env['pc'])['swap_plan']


def test_offmesh_placements_are_rescuable_or_reserved(env):
    off, resc, caps = env['off'], env['resc'], env['caps']
    saw_rescuable_offmesh = False
    for seed in SEEDS:
        sp = _plan(env, seed)
        assert sp, f"seed {seed}: engine produced no placements"
        offmesh = [(m, pi, cp) for (m, pi, cp) in sp if (m, pi) in off]
        assert offmesh, f"seed {seed}: no off-mesh placements (invariant vacuous)"
        bad = [(m, pi, cp) for (m, pi, cp) in offmesh
               if cp not in resc and cp not in caps]
        assert not bad, (
            f"seed {seed}: {len(bad)} off-mesh placement(s) neither wake-"
            f"rescuable nor a unique reservation: {bad[:5]}")
        if any(cp in resc for _, _, cp in offmesh):
            saw_rescuable_offmesh = True
    assert saw_rescuable_offmesh, (
        "no wake-rescuable enemy was placed at any off-mesh slot across the "
        "tested seeds — the restriction may be inert (check backstab_tiers / "
        "off-mesh slot loading).")


def test_simulation_is_deterministic(env):
    first = _plan(env, SEEDS[0])
    again = _plan(env, SEEDS[0])
    assert first == again, "same seed produced different swap plans"


def test_all_placements_target_valid_cprefixes(env):
    valid = {v['c_prefix'] for v in env['roster']['all_variants']
             if v.get('c_prefix')}
    sp = _plan(env, SEEDS[0])
    bad = sorted({cp for _, _, cp in sp if cp not in valid})
    assert not bad, f"placed c-prefixes absent from roster: {bad[:10]}"
