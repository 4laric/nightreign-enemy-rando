"""Engine subpackage — incremental extraction from oops_v3.py.

Currently exports:
  - GateState: snapshot of the engine's mutable gate/exclusion state.
  - apply_run_overrides: context manager for per-run override
    application against the cmd_shuffle_v3 module globals.
  - compose_pool_cap_overrides: per-run pool/cap mutation, applied
    post-load_data inside the impl (v0.26.x).
  - RunContext: per-run mutable bookkeeping (counters, reservations).

The plan is to grow this package over time as we pull testable pieces
out of oops_v3.py. For now the parent module remains the source of
truth; engine/ holds the new abstractions and the test seams.
"""
from engine.state import GateState
from engine.runtime import apply_run_overrides, compose_pool_cap_overrides
from engine.runctx import RunContext

__all__ = ['GateState', 'apply_run_overrides',
           'compose_pool_cap_overrides', 'RunContext']
