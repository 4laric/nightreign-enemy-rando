"""Unit tests for the v0.32.x grunt-tier density cap (Gate 9b).

WHAT THIS LOCKS
---------------
The size-based density cap (L+/XL+) leaves the grunt tier uncapped, so a
single MSB can fill with grunts. Gate 9b adds a per-MSB count-cap on
grunt-tier chrs. Contract pinned here:

1. When ARMED (V3_DENSITY_CAP_GRUNT_ENABLED=True) and the MSB's grunt
   count has reached msb_grunt_cap, a grunt-tier target is rejected
   ('density_grunt').
2. Under the cap, a grunt target passes.
3. The cap keys on the chr's INTRINSIC tier == 'grunt' — a non-grunt
   target is never grunt-capped, even when the grunt count is maxed.
4. When DISABLED (the default), the gate is a no-op regardless of count.
5. RunContext.register_grunt / begin_msb wire the counter + cap correctly.

Fast: synthetic `ns` + stub run_ctx, no oops_v3 data load (mirrors
tests/test_rejection_extraction.py).
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from engine.rejection import reject_target_for_slot  # noqa: E402
from engine.runctx import RunContext  # noqa: E402
from test_rejection_extraction import _make_minimal_ns  # noqa: E402


class _GruntCtx:
    """Minimal run_ctx arming the size gate with a grunt counter/cap."""
    def __init__(self, count, cap):
        self.msb_size_gate_active = True
        self.msb_grunt_count = count
        self.msb_grunt_cap = cap
        # size-gate fields the other branches read (kept inert)
        self.msb_xl_count = 0
        self.msb_xl_cap = 99
        self.msb_l_count = 0
        self.msb_l_cap = 99
        self.msb_big_positions = []


def _ns(enabled):
    # _effective_size_class default returns 'M' → never enters the L+
    # size gate, so we isolate the grunt branch.
    return _make_minimal_ns(V3_DENSITY_CAP_GRUNT_ENABLED=enabled)


GRUNT_TAGS = {'c1000': {'tier': 'grunt'}, 'c2000': {'tier': 'miniboss'}}


def test_grunt_rejected_at_cap():
    ns = _ns(True)
    r = reject_target_for_slot(
        ns, 'c1000', 'c1000', 'Grunt', GRUNT_TAGS,
        run_ctx=_GruntCtx(count=25, cap=25))
    assert r == 'density_grunt'


def test_grunt_rejected_over_cap():
    ns = _ns(True)
    r = reject_target_for_slot(
        ns, 'c1000', 'c1000', 'Grunt', GRUNT_TAGS,
        run_ctx=_GruntCtx(count=40, cap=25))
    assert r == 'density_grunt'


def test_grunt_allowed_under_cap():
    ns = _ns(True)
    r = reject_target_for_slot(
        ns, 'c1000', 'c1000', 'Grunt', GRUNT_TAGS,
        run_ctx=_GruntCtx(count=24, cap=25))
    assert r is None


def test_non_grunt_never_grunt_capped():
    # A miniboss-tier target at a maxed grunt count is NOT grunt-rejected.
    ns = _ns(True)
    r = reject_target_for_slot(
        ns, 'c2000', 'c2000', 'Miniboss', GRUNT_TAGS,
        run_ctx=_GruntCtx(count=99, cap=25))
    assert r is None


def test_disabled_is_noop():
    # Default (disabled): even a grunt far over cap passes the grunt gate.
    ns = _ns(False)
    r = reject_target_for_slot(
        ns, 'c1000', 'c1000', 'Grunt', GRUNT_TAGS,
        run_ctx=_GruntCtx(count=999, cap=25))
    assert r is None


def test_unknown_tier_not_grunt_capped():
    # A target with no tags entry has tier None → not grunt → passes.
    ns = _ns(True)
    r = reject_target_for_slot(
        ns, 'c9999', 'c9999', '?', GRUNT_TAGS,
        run_ctx=_GruntCtx(count=99, cap=25))
    assert r is None


# --- RunContext wiring -----------------------------------------------------

def test_runctx_begin_msb_sets_grunt_state():
    ctx = RunContext()
    ctx.begin_msb(xl_cap=3, l_cap=10, grunt_cap=25)
    assert ctx.msb_grunt_count == 0
    assert ctx.msb_grunt_cap == 25


def test_runctx_register_grunt_increments():
    ctx = RunContext()
    ctx.begin_msb(xl_cap=3, l_cap=10, grunt_cap=25)
    for _ in range(3):
        ctx.register_grunt()
    assert ctx.msb_grunt_count == 3


def test_runctx_begin_msb_grunt_cap_defaults_unbounded():
    # Omitting grunt_cap (legacy callers) leaves the gate effectively off.
    ctx = RunContext()
    ctx.begin_msb(xl_cap=3, l_cap=10)
    assert ctx.msb_grunt_cap >= (1 << 30)


def test_runctx_begin_msb_resets_grunt_count():
    ctx = RunContext()
    ctx.begin_msb(xl_cap=3, l_cap=10, grunt_cap=25)
    ctx.register_grunt()
    ctx.begin_msb(xl_cap=3, l_cap=10, grunt_cap=25)  # new MSB
    assert ctx.msb_grunt_count == 0
