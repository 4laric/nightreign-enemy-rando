"""Engine subpackage — incremental extraction from oops_v3.py.

Currently exports:
  - GateState: snapshot of the engine's mutable gate/exclusion state.
  - apply_run_overrides: context manager for per-run override
    application against the cmd_shuffle_v3 module globals.
  - compose_pool_cap_overrides: per-run pool/cap mutation, applied
    post-load_data inside the impl (v0.26.x).
  - RunContext: per-run mutable bookkeeping (counters, reservations).
  - apply_placement_budget_overrides: TODO Step 2 loader. Sources the
    pure-static placement-budget V3_* sets from
    data/placement_budget.json at module-import time, falling back
    to inline literals if the JSON is absent or malformed.

The plan is to grow this package over time as we pull testable pieces
out of oops_v3.py. For now the parent module remains the source of
truth; engine/ holds the new abstractions and the test seams.
"""
from engine.state import GateState
from engine.runtime import apply_run_overrides, compose_pool_cap_overrides
from engine.runctx import RunContext
from engine.placement_budget import (
    apply_static_overrides as apply_placement_budget_overrides,
    build_static_overrides as build_placement_budget_overrides,
    load_budget as load_placement_budget,
)

__all__ = ['GateState', 'apply_run_overrides',
           'compose_pool_cap_overrides', 'RunContext',
           'apply_placement_budget_overrides',
           'build_placement_budget_overrides',
           'load_placement_budget']
