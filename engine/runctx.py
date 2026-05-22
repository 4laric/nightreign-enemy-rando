"""RunContext — per-run mutable state. Counters and reservations
accumulated during a shuffle run.

WHY THIS EXISTS
---------------
This is the second half of the architectural separation that started
with GateState. They split per-run state into two categories:

  GateState (engine/state.py) — IMMUTABLE per-run *configuration*.
      Snapshots the gate sets and flags at run start, doesn't change
      until run end. Frozen dataclass.

  RunContext (this file) — MUTABLE per-run *bookkeeping*. Counters
      that get bumped as the run progresses; reservations that get
      committed as the pre-pass executes; logs that get appended to
      when unique targets fail to place.

The Phase 4 migration of pick_target_cp surfaced this distinction. A
parity test caught a divergence between gates=None and explicit
gates: identical inputs, different outputs. Cause: pick_target_cp
mutates `_V3_UNIQUE_PLACED_COUNTS[result]` after each pick to track
unique-target frequency caps. Back-to-back calls in a test polluted
the shared module-level counter. The fix in test code was a manual
save/restore, mirroring the pattern cmd_shuffle_v3 used pre-Phase 2
for its gate sets. RunContext lets tests just construct
`RunContext.fresh()` per call — no save/restore boilerplate.

WHAT THIS DOES
--------------
Three module-level dicts/lists get encapsulated:

  _V3_UNIQUE_RESERVATIONS: dict (msb_name, pi) -> reserved cp
      Populated by _compute_unique_reservations during the pre-pass.
      Read by pick_target_cp's early-return path.

  _V3_UNIQUE_PLACED_COUNTS: dict cp -> placement count
      Bumped by _compute_unique_reservations (at reservation time)
      AND by pick_target_cp (at non-reserved-pick time). Read by
      pick_target_cp to determine cap-exhausted cps.

  _V3_UNIQUE_UNPLACED_LOG: list of dicts (per failed reservation)
      Appended to during _compute_unique_reservations when a capped
      cp couldn't get any valid slot. Emitted in spoiler header.

The RunContext is MUTABLE — methods bump_unique(), reserve(), etc.
mutate self in place. This is intentional: the production call chain
(_cmd_shuffle_v3_impl → shuffle_msb_v3 → pick_target_cp) needs the
counter state to accumulate across calls without threading a return
value through every layer. Reference-passing is the simplest pattern
that preserves current semantics.

MIGRATION PATTERN
-----------------
Same as Phase 1-4 for GateState. Each function gets an optional
`run_ctx=None` parameter:

  run_ctx=None  -> reads/writes module-level dicts (back-compat).
  run_ctx=RunContext(...)  -> reads/writes the explicit context.

Tests construct RunContext.fresh() to isolate themselves from module
state. Production cmd_shuffle_v3 will eventually construct a single
RunContext per run, thread it through, and let the module dicts go
unused. For now the module dicts are still authoritative — the
gates=None / run_ctx=None backwards-compat paths preserve all
pre-existing callers verbatim.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class RunContext:
    """Per-run mutable bookkeeping. NOT frozen — counters mutate
    during the run. Construct fresh() at run start; thread by
    reference through the call chain; let it accumulate.
    """

    # Slot (msb_name, part_index) -> reserved c-prefix.
    # Populated by _compute_unique_reservations during the pre-pass.
    # pick_target_cp's early-return path consults this.
    unique_reservations: Dict[Tuple[str, int], str] = field(default_factory=dict)

    # c-prefix -> count of placements committed during this run.
    # Bumped at reservation-commit time (in the pre-pass) AND at
    # non-reserved-pick time (in pick_target_cp). Read by
    # pick_target_cp to compute the exhausted-set for cap enforcement.
    unique_placed_counts: Dict[str, int] = field(default_factory=dict)

    # Diagnostic log of unique caps that couldn't get a reservation.
    # Per-entry shape: {'cp': str, 'cap': int, 'reason': str,
    #                   'best_attempt': dict | None}
    # Emitted in spoiler header so the user can decide whether to
    # relax the cap criteria.
    unique_unplaced_log: List[dict] = field(default_factory=list)

    # =====================================================================
    # Construction
    # =====================================================================

    @classmethod
    def fresh(cls) -> 'RunContext':
        """A clean RunContext with all counters/dicts/logs empty.

        For tests that want to exercise the picker against a known-empty
        runtime state. Same role as GateState.empty().
        """
        return cls()

    @classmethod
    def from_module(cls, module=None) -> 'RunContext':
        """Snapshot module state into a new RunContext.

        Mostly useful for tests that want to inspect what the module
        sees, but COPIES the dicts (so mutating the returned RunContext
        does not affect the module). For production, prefer fresh() and
        thread the RunContext through; only use from_module when you
        actually want the current module state.
        """
        if module is None:
            import oops_v3
            module = oops_v3
        return cls(
            unique_reservations=dict(module._V3_UNIQUE_RESERVATIONS),
            unique_placed_counts=dict(module._V3_UNIQUE_PLACED_COUNTS),
            unique_unplaced_log=list(module._V3_UNIQUE_UNPLACED_LOG),
        )

    # =====================================================================
    # Mutation helpers
    # =====================================================================
    # These exist for readability at call sites — pick_target_cp can write
    # `run_ctx.bump_unique(cp)` instead of the longhand
    # `run_ctx.unique_placed_counts[cp] = run_ctx.unique_placed_counts.get(cp, 0) + 1`.
    # The dict is also directly accessible if a caller needs raw access.

    def bump_unique(self, cp: str) -> None:
        """Increment the placement count for `cp`."""
        self.unique_placed_counts[cp] = (
            self.unique_placed_counts.get(cp, 0) + 1)

    def reserve(self, slot_msb_name: str, slot_pi: int, cp: str) -> None:
        """Reserve a slot for `cp`. Use during the pre-pass."""
        self.unique_reservations[(slot_msb_name, slot_pi)] = cp

    def get_reservation(self, slot_msb_name: Optional[str],
                        slot_pi: Optional[int]) -> Optional[str]:
        """Return the reserved cp for a slot, or None.

        Returns None if either slot field is None — matches the
        pick_target_cp guard at line ~8684 ('if slot_msb_name is not
        None and slot_pi is not None'). Centralizes the None-handling
        so callers don't have to repeat the guard.
        """
        if slot_msb_name is None or slot_pi is None:
            return None
        return self.unique_reservations.get((slot_msb_name, slot_pi))

    def is_exhausted(self, cp: str, cap: int) -> bool:
        """True if cp has hit its cap. Cap is the value from
        V3_UNIQUE_TARGET_CAPS (a static module constant; not
        per-run state)."""
        return self.unique_placed_counts.get(cp, 0) >= cap

    def reset(self) -> None:
        """Clear all counters/dicts/logs in place.

        For callers that want to reuse a RunContext object across runs
        rather than constructing a new one. Mirrors the module-level
        _reset_unique_run_state() function's behavior.
        """
        self.unique_reservations.clear()
        self.unique_placed_counts.clear()
        self.unique_unplaced_log.clear()
