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
from typing import Dict, List, Optional, Set, Tuple


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

    # --- v0.27.5: per-MSB size-budget state for the placement-time
    # proximity / density gates. Ephemeral within one shuffle_msb_v3
    # call (NOT cross-run bookkeeping like the dicts above). begin_msb()
    # resets these and arms the gate; end_msb() disarms it. While
    # disarmed (reservation pre-pass, legacy callers, tests) the gates
    # in _reject_target_for_slot no-op, so reservations are never
    # subject to proximity/density — this is what keeps a reserved big
    # chr from being demoted.
    msb_size_gate_active: bool = False
    msb_big_positions: List[Tuple[float, float, float]] = field(default_factory=list)
    msb_xl_count: int = 0
    msb_l_count: int = 0
    msb_xl_cap: int = 999
    msb_l_cap: int = 999

    # v0.28: c-prefixes already placed in the current MSB (the assets this
    # tile already pays to load). A slot that hits the uniqueness cap
    # recycles one of these instead of reverting to vanilla — zero extra
    # chrbnd load, world stays non-vanilla. Reset by begin_msb(); appended
    # to at each committed placement in shuffle_msb_v3.
    msb_resident_cps: Set[str] = field(default_factory=set)

    # v0.28: per-MSB distinct-c-prefix budget = how many distinct chrbnds
    # vanilla loads in this MSB. The placement loop introduces at most this
    # many, so a randomized tile never out-loads vanilla (this is the
    # by-construction ceiling on the streamed-band fan-out crash). 0 = no
    # budget (legacy/test paths) -> treated as unbounded by the picker.
    msb_distinct_budget: int = 0

    # v0.28: global-cap eligibility FROZEN at begin_msb. A c-prefix already
    # at/over its V3_UNIQUE_TARGET_CAPS limit when the MSB started is in
    # this set and hard-blocked for the whole MSB. A cp that crosses its
    # cap DURING the MSB (free recycling onto resident slots) is NOT in
    # here, so it stays placeable until the next begin_msb re-freezes the
    # snapshot — the "overshoot now, respected next MSB" rule. None = not
    # frozen (legacy/test) -> the picker falls back to live cap computation.
    msb_blocked_cps: Optional[Set[str]] = None

    # v0.28.x (Phase 2 POI recycling): nested POI scope inside MSB scope.
    # When V3_POI_SCOPE_RECYCLE is on, shuffle_msb_v3 calls begin_poi() on
    # each cluster transition so the resident set / distinct budget the
    # picker reads come from the smaller per-cluster scope instead of the
    # whole-MSB scope. Streaming-locality argument: a chr "resident" at
    # one geographic cluster in an open-world MSB isn't free at a distant
    # cluster — the game already unloaded it.
    #
    # current_poi_id: cluster_id currently in scope, or None when we're
    #   between cluster transitions / POI scope disabled (picker falls
    #   back to msb_* state).
    # poi_resident_cps: cluster_id -> set of cps committed in this cluster.
    # poi_distinct_budget: cluster_id -> distinct-cp budget for cluster.
    current_poi_id: Optional[int] = None
    poi_resident_cps: Dict[int, Set[str]] = field(default_factory=dict)
    poi_distinct_budget: Dict[int, int] = field(default_factory=dict)

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

    def begin_msb(self, xl_cap: int, l_cap: int,
                  distinct_budget: int = 0,
                  caps: Optional[Dict[str, int]] = None,
                  resident_seed: Optional[Set[str]] = None) -> None:
        """Reset per-MSB size state and arm the proximity/density gates
        at the start of a shuffle_msb_v3 call. xl_cap/l_cap are the
        per-MSB caps (tunnel profile or global default).

        v0.28 hybrid budget/recycle args (optional; omitting them keeps the
        pre-v0.28 picker behavior for legacy callers and tests):
          distinct_budget — the MSB's vanilla distinct-c-prefix count.
          caps            — V3_UNIQUE_TARGET_CAPS, used to freeze the
                            global-cap block set at MSB entry (see
                            msb_blocked_cps). None => no freeze (live cap
                            computation in the picker).
          resident_seed   — c-prefixes already loaded by forced-vanilla
                            slots in this MSB (excluded / no-variants /
                            pinned). They seed the resident set so recycle
                            can reuse them and they count against the
                            budget.
        """
        self.msb_size_gate_active = True
        self.msb_big_positions = []
        self.msb_xl_count = 0
        self.msb_l_count = 0
        self.msb_xl_cap = xl_cap
        self.msb_l_cap = l_cap
        self.msb_distinct_budget = distinct_budget
        self.msb_resident_cps = set(resident_seed) if resident_seed else set()
        if caps is None:
            self.msb_blocked_cps = None  # no freeze -> picker uses live caps
        else:
            self.msb_blocked_cps = {
                cp for cp, n in self.unique_placed_counts.items()
                if n >= caps.get(cp, 1 << 30)}

    def end_msb(self) -> None:
        """Disarm the per-MSB size gates after a shuffle_msb_v3 call."""
        self.msb_size_gate_active = False
        # v0.28.x: clear per-cluster POI state so the next MSB starts
        # fresh. Repopulated by the next shuffle_msb_v3's pre-scan.
        self.current_poi_id = None
        self.poi_resident_cps.clear()
        self.poi_distinct_budget.clear()

    def begin_poi(self, poi_id: int, distinct_budget: int) -> None:
        """Open a POI (spatial cluster) scope inside the current MSB.
        Seeds the per-cluster budget and ensures a resident set exists
        so the picker's active_*_cps helpers read this scope.

        Idempotent in poi_id — calling begin_poi(7, ...) twice for the
        same cluster doesn't clobber the resident set the first call
        populated. shuffle_msb_v3 only calls this once per cluster but
        tests may exercise re-entry."""
        self.current_poi_id = poi_id
        if poi_id not in self.poi_resident_cps:
            self.poi_resident_cps[poi_id] = set()
        self.poi_distinct_budget[poi_id] = distinct_budget

    def end_poi(self) -> None:
        """Close the current POI scope. Next pick_target_cp sees
        current_poi_id=None and falls back to MSB-level resident/budget."""
        self.current_poi_id = None

    def active_resident_cps(self) -> Set[str]:
        """Resident set the picker reads. POI-scope when a cluster is
        active, MSB-scope otherwise."""
        if self.current_poi_id is not None:
            return self.poi_resident_cps.get(
                self.current_poi_id, self.msb_resident_cps)
        return self.msb_resident_cps

    def active_distinct_budget(self) -> int:
        """Distinct-cp budget the picker reads. POI-scope when a cluster
        is active, MSB-scope otherwise."""
        if self.current_poi_id is not None:
            return self.poi_distinct_budget.get(
                self.current_poi_id, self.msb_distinct_budget)
        return self.msb_distinct_budget

    def add_resident_cp(self, cp: str) -> None:
        """Record `cp` as resident in whichever scope is active. Always
        adds to msb_resident_cps; also adds to poi_resident_cps[
        current_poi_id] when a POI scope is armed. Called from the
        commit site in shuffle_msb_v3."""
        self.msb_resident_cps.add(cp)
        if self.current_poi_id is not None:
            self.poi_resident_cps.setdefault(
                self.current_poi_id, set()).add(cp)

    def register_big(self, size_class: str, pos) -> None:
        """Record a committed placement into per-MSB size state so later
        slots in the same MSB see it for proximity/density. L+ bumps the
        L count; XL+ bumps the XL count and (given a position) joins the
        proximity set."""
        if size_class in ('L', 'XL', 'XXL', 'GIGA'):
            self.msb_l_count += 1
        if size_class in ('XL', 'XXL', 'GIGA'):
            self.msb_xl_count += 1
            if pos is not None:
                self.msb_big_positions.append(pos)

    def reset(self) -> None:
        """Clear all counters/dicts/logs in place.

        For callers that want to reuse a RunContext object across runs
        rather than constructing a new one. Mirrors the module-level
        _reset_unique_run_state() function's behavior.
        """
        self.unique_reservations.clear()
        self.unique_placed_counts.clear()
        self.unique_unplaced_log.clear()
        self.msb_size_gate_active = False
        self.msb_big_positions = []
        self.msb_xl_count = 0
        self.msb_l_count = 0
        self.msb_resident_cps = set()
        self.msb_distinct_budget = 0
        self.msb_blocked_cps = None
        # v0.28.x POI scope.
        self.current_poi_id = None
        self.poi_resident_cps.clear()
        self.poi_distinct_budget.clear()
