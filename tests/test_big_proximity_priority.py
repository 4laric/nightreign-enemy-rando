"""Unit tests for engine.rejection.resolve_big_proximity_priority.

WHAT THIS LOCKS
---------------
The v0.32.x opt-in proximity tie-break replaces the forward Gate 8's
"low-pi wins" (visit-order) survivorship with a deterministic priority
key. The contract this file pins:

1. Order-independence — permuting the input placements yields an
   IDENTICAL demotion set. This is the whole point: the winner of a
   proximity contest must no longer depend on Part-index iteration order.
2. Priority correctness — the highest-priority slot in any neighbourhood
   always survives; lower-priority neighbours within radius are demoted.
3. No false demotions — a slot with no neighbour within radius is never
   demoted; a slot with no usable position is never demoted.
4. Determinism on ties — equal priority keys fall back to higher pi.

The function is pure (no oops_v3, no ns dict), so these tests are fast
and have no data dependency.
"""
from __future__ import annotations

import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine.rejection import (  # noqa: E402
    reject_target_for_slot,
    resolve_big_proximity_priority,
)
from test_rejection_extraction import _make_minimal_ns  # noqa: E402


class _StubRunCtx:
    """Minimal run_ctx that arms the forward proximity gate: size gate
    active, density off, one big already placed at the origin."""
    msb_size_gate_active = True
    msb_xl_count = 0
    msb_xl_cap = 99
    msb_l_count = 0
    msb_l_cap = 99
    msb_big_positions = [(0.0, 0.0, 0.0)]

# A radius of 30.0 (V3_BIG_PROXIMITY_RADIUS) → radius_sq 900.0.
RSQ = 30.0 ** 2


def _priority(mapping):
    """Build a priority_of callable from a {pi: key} dict."""
    return lambda pi: mapping[pi]


def test_no_conflict_demotes_nothing():
    # Three bigs all > 30u apart on the X axis.
    slots = [(0, (0.0, 0.0, 0.0)),
             (1, (100.0, 0.0, 0.0)),
             (2, (200.0, 0.0, 0.0))]
    demoted = resolve_big_proximity_priority(
        slots, RSQ, _priority({0: 10, 1: 20, 2: 30}))
    assert demoted == set()


def test_pair_within_radius_lower_priority_demoted():
    # Two bigs 10u apart (< 30). pi=1 has the higher priority → it wins,
    # pi=0 is demoted.
    slots = [(0, (0.0, 0.0, 0.0)), (1, (10.0, 0.0, 0.0))]
    demoted = resolve_big_proximity_priority(
        slots, RSQ, _priority({0: 5, 1: 99}))
    assert demoted == {0}


def test_winner_is_independent_of_input_order():
    # Same two-slot conflict; whichever order they are supplied in, the
    # higher-priority slot (pi=1) must win every time.
    base = [(0, (0.0, 0.0, 0.0)), (1, (10.0, 0.0, 0.0))]
    prio = _priority({0: 5, 1: 99})
    for perm in itertools.permutations(base):
        assert resolve_big_proximity_priority(list(perm), RSQ, prio) == {0}


def test_permutation_invariance_cluster():
    # Four bigs all mutually within radius (a tight encampment). Only the
    # single highest-priority slot survives; the result is identical for
    # every input permutation.
    slots = [(0, (0.0, 0.0, 0.0)),
             (1, (5.0, 0.0, 0.0)),
             (2, (10.0, 0.0, 0.0)),
             (3, (15.0, 0.0, 0.0))]
    prio = _priority({0: 1, 1: 2, 2: 99, 3: 3})  # pi=2 is the winner
    expected = {0, 1, 3}
    for perm in itertools.permutations(slots):
        assert resolve_big_proximity_priority(list(perm), RSQ, prio) == expected


def test_two_disjoint_clusters_each_keep_their_own_winner():
    # Cluster A around x=0, cluster B around x=200 (far apart). Each keeps
    # its own highest-priority member.
    slots = [(0, (0.0, 0.0, 0.0)), (1, (10.0, 0.0, 0.0)),
             (2, (200.0, 0.0, 0.0)), (3, (210.0, 0.0, 0.0))]
    prio = _priority({0: 50, 1: 10, 2: 7, 3: 80})  # A→pi0, B→pi3 win
    demoted = resolve_big_proximity_priority(slots, RSQ, prio)
    assert demoted == {1, 2}


def test_none_position_never_demoted():
    # A slot with no usable position can't be proximity-tested → it is
    # left alone even though another big sits nearby.
    slots = [(0, (0.0, 0.0, 0.0)), (1, (10.0, 0.0, 0.0)), (2, None)]
    demoted = resolve_big_proximity_priority(
        slots, RSQ, _priority({0: 99, 1: 1, 2: 1}))
    assert 2 not in demoted
    assert demoted == {1}


def test_priority_tie_breaks_on_higher_pi():
    # Equal priority keys: the higher pi must deterministically win so the
    # outcome is total-ordered (no reliance on input order).
    slots = [(3, (0.0, 0.0, 0.0)), (7, (10.0, 0.0, 0.0))]
    prio = _priority({3: 42, 7: 42})
    for perm in itertools.permutations(slots):
        # pi=7 (higher) wins → pi=3 demoted.
        assert resolve_big_proximity_priority(list(perm), RSQ, prio) == {3}


def test_radius_boundary_is_exclusive():
    # Exactly at the radius is NOT a conflict (the gate uses < radius_sq).
    slots = [(0, (0.0, 0.0, 0.0)), (1, (30.0, 0.0, 0.0))]
    demoted = resolve_big_proximity_priority(
        slots, RSQ, _priority({0: 1, 1: 2}))
    assert demoted == set()


def test_empty_and_singleton_are_noops():
    assert resolve_big_proximity_priority([], RSQ, _priority({})) == set()
    assert resolve_big_proximity_priority(
        [(0, (0.0, 0.0, 0.0))], RSQ, _priority({0: 1})) == set()


# ---------------------------------------------------------------------------
# Forward Gate 8 bypass wiring
# ---------------------------------------------------------------------------

def _proximity_ns(**overrides):
    """A synthetic ns where the forward proximity gate WOULD fire: a new
    XL target landing 10u from an already-placed big."""
    ns = _make_minimal_ns(
        V3_BIG_PROXIMITY_ENABLED=True,
        V3_BIG_PROXIMITY_RADIUS=30.0,
        V3_BIG_SIZE_CLASSES=frozenset({'XL', 'XXL', 'GIGA'}),
        V3_DENSITY_L_SIZE_CLASSES=frozenset({'L', 'XL', 'XXL', 'GIGA'}),
        V3_DENSITY_CAP_ENABLED=False,
        _effective_size_class=lambda cp, tags, **kw: 'XL',
    )
    ns.update(overrides)
    return ns


def test_forward_gate_fires_when_flag_absent():
    # Baseline: with no hash-tiebreak flag, the forward gate rejects the
    # second big as 'big_proximity' (the current default behaviour).
    ns = _proximity_ns()
    result = reject_target_for_slot(
        ns, 'c5010', 'c5010', 'Hippo', {},
        slot_pos=(10.0, 0.0, 0.0), run_ctx=_StubRunCtx())
    assert result == 'big_proximity'


def test_forward_gate_bypassed_when_hash_tiebreak_on():
    # With the flag ON, the forward gate stands down (the post-pass owns
    # proximity) — the same call no longer rejects.
    ns = _proximity_ns(V3_BIG_PROXIMITY_HASH_TIEBREAK=True)
    result = reject_target_for_slot(
        ns, 'c5010', 'c5010', 'Hippo', {},
        slot_pos=(10.0, 0.0, 0.0), run_ctx=_StubRunCtx())
    assert result is None
