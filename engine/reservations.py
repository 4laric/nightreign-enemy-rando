"""Unique-target reservation pre-pass (extracted from oops_v3.py).

WHAT THIS IS
------------
The function `compute_unique_reservations` runs once per shuffle,
before the main placement loop. For every c-prefix in
V3_UNIQUE_TARGET_CAPS, it picks (cap - already_placed_counts) slots
across the MSB inventory and "reserves" them — committing that
chr-prefix to those (msb, pi) slot identities. The runtime picker
later sees these reservations and short-circuits its gate cascade,
which is fine BECAUSE the reservation logic itself already applied
the mirror-semantic gates (via _score_slot_for_unique, which calls
into engine.rejection).

The reservation pass is what gives capped placements geographic
spread (the cap=2 tile-distance scoring) and floor-coverage
guarantees (V3_RESERVATION_FLOORS — every floored chr gets at
least one slot or appears in the unplaced log).

WHY IT WAS EXTRACTED
--------------------
326 lines in the host module, with a clean already-defined external
interface (RunContext as the modern write-target). The function is
heavy on shared run state — the reservation dict / placed counts /
unplaced log are written here, then read elsewhere by the picker
and spoiler writer. Moving the body to engine.reservations gives
this concentrated state-write boundary its own testable seam.

The `ns` namespace (first positional argument) carries:
  - 4 V3_* state constants (V3_EXCLUDE_PREFIXES,
    V3_EXCLUDE_TARGET_PREFIXES, V3_GHOST_EXCLUDE_TARGET_PREFIXES,
    V3_RESERVATION_FLOORS)
  - 3 _V3_* mutable dicts/list (only used on the legacy path when
    run_ctx is None — modern callers pass an explicit RunContext)
  - 4 helper functions imported from oops_v3
    (enumerate_unique_candidate_slots, load_variant_groups,
    populate_variant_names, score_slot_for_unique).
    _score_slot_for_unique transitively calls _reject_target_for_slot
    which delegates to engine.rejection; the dependency chain is
    clean. _tile_xy is a nested function defined inside the body, not
    a module-level helper.

LEGACY-PATH MUTATION INVARIANT
------------------------------
When run_ctx is None, the function reads the three _V3_* dicts/list
from ns and ALIASES them into local names (_reservations,
_placed_counts, _unplaced_log). Mutations through those aliases
propagate to the same dict objects ns returned — so the module-level
_V3_UNIQUE_RESERVATIONS / _V3_UNIQUE_PLACED_COUNTS /
_V3_UNIQUE_UNPLACED_LOG dicts and list end up populated, which is
what every downstream reader (pick_target_cp, write_spoiler_logs)
sees.

This means tests CAN substitute their own ns dicts to capture
reservation activity in isolation — pass {'_V3_UNIQUE_RESERVATIONS':
my_dict, ...} and the mutations land in my_dict. The shim in
oops_v3.py passes globals(), so production callers continue to
mutate module state exactly as before.
"""
from __future__ import annotations


def compute_unique_reservations(ns, input_dir, tags, prefix_variants, rng,
                                 already_placed_counts=None,
                                 run_ctx=None, inventory=None):
    """Pre-pass: pick reservations for every c-prefix in V3_UNIQUE_TARGET_CAPS.

    Mutates _V3_UNIQUE_RESERVATIONS (dict (msb,pi) -> cp), bumps
    _V3_UNIQUE_PLACED_COUNTS for each reservation made (so the runtime
    cap check sees the reservations as already-counted), and appends
    to _V3_UNIQUE_UNPLACED_LOG for any cp where no slot qualified.

    already_placed_counts: optional dict of cp -> count for vanilla source
    preservations that count toward the cap. The reservation pass picks
    cap - already_placed_counts.get(cp, 0) slots for each cp.

    Geographic spread for cap=2: when picking the second slot, prefer
    slots whose position.x is far from the first. Computed via map's
    coordinate offset (m60_44_38 → x_offset=44 in tile-grid).

    v0.23.07-mp: also respects V3_EXCLUDE_TARGET_PREFIXES /
    V3_GHOST_EXCLUDE_TARGET_PREFIXES so reservations don't pick capped
    cps that are blocked at runtime (especially heritage cps when
    multiplayer_safe=True). Without this filter, the pre-pass would
    "successfully" reserve a heritage cp at a non-shifting-earth slot,
    and pick_target_cp's reservation early-return would commit it,
    bypassing mp_safe entirely.

    v0.24.21 (Phase 5): `run_ctx` parameter. When None (default), writes
    to module-level _V3_UNIQUE_RESERVATIONS / _V3_UNIQUE_PLACED_COUNTS /
    _V3_UNIQUE_UNPLACED_LOG — preserves all pre-Phase 5 callers.
    When a RunContext is passed, writes to its dicts/list instead.
    See engine/runctx.py.
    """
    # Bind module-level dependencies into locals. The body
    # below reads identically to the original pre-extraction
    # code; locals also use LOAD_FAST opcodes (faster than
    # LOAD_GLOBAL on hot paths — the reservation scoring
    # loop calls these helpers thousands of times per run).
    #
    # V3_* state — read-only configuration:
    V3_EXCLUDE_PREFIXES = ns['V3_EXCLUDE_PREFIXES']
    V3_EXCLUDE_TARGET_PREFIXES = ns['V3_EXCLUDE_TARGET_PREFIXES']
    V3_GHOST_EXCLUDE_TARGET_PREFIXES = ns['V3_GHOST_EXCLUDE_TARGET_PREFIXES']
    V3_RESERVATION_FLOORS = ns['V3_RESERVATION_FLOORS']
    # Module-level mutable state — only used when run_ctx is None
    # (legacy caller path). Modern callers pass an explicit
    # RunContext, which has its own dicts/list. Mutations through
    # the aliased local refs (see "_reservations = ..." below)
    # propagate to the same dict objects ns returns.
    _V3_UNIQUE_PLACED_COUNTS = ns['_V3_UNIQUE_PLACED_COUNTS']
    _V3_UNIQUE_RESERVATIONS = ns['_V3_UNIQUE_RESERVATIONS']
    _V3_UNIQUE_UNPLACED_LOG = ns['_V3_UNIQUE_UNPLACED_LOG']
    # Helper functions:
    _enumerate_unique_candidate_slots = ns['_enumerate_unique_candidate_slots']
    _load_variant_groups = ns['_load_variant_groups']
    _populate_variant_names = ns['_populate_variant_names']
    _score_slot_for_unique = ns['_score_slot_for_unique']
    # NOTE: _tile_xy is NOT bound from ns — it's defined as a nested
    # function below (~L298 in the body). My initial dependency scan
    # missed nested `def` declarations in local-name collection; left
    # this comment as a reminder for future extractions.
    # Resolve write targets. Same pattern as gates: run_ctx=None means
    # module dicts; explicit RunContext means the context's dicts.
    if run_ctx is None:
        _reservations = _V3_UNIQUE_RESERVATIONS
        _placed_counts = _V3_UNIQUE_PLACED_COUNTS
        _unplaced_log = _V3_UNIQUE_UNPLACED_LOG
    else:
        _reservations = run_ctx.unique_reservations
        _placed_counts = run_ctx.unique_placed_counts
        _unplaced_log = run_ctx.unique_unplaced_log

    print("Building unique-target reservations (v0.23.07)...")
    if already_placed_counts is None:
        already_placed_counts = {}

    # Snapshot the runtime exclude state. multiplayer_safe injects heritage
    # into V3_GHOST_EXCLUDE_TARGET_PREFIXES via the cmd_shuffle_v3 wrapper,
    # so reading this dict here gives us the mp_safe-aware view.
    runtime_target_excludes = (V3_EXCLUDE_PREFIXES
                                | V3_EXCLUDE_TARGET_PREFIXES
                                | V3_GHOST_EXCLUDE_TARGET_PREFIXES)

    slots = _enumerate_unique_candidate_slots(input_dir, inventory=inventory)
    _populate_variant_names(slots, prefix_variants)
    # v0.28: canonical candidate-slot order. The per-cp scoring below
    # tiebreaks equal scores with rng.random() consumed in slot order, so
    # without a stable order the reservations depend on how the input
    # enumerated — the last input-ordering dependency in the pre-pass.
    # Sorting here makes reservations a pure function of (seed, slot set),
    # so a reordered base no longer shifts them and cascades.
    slots.sort(key=lambda s: (s['msb'], s['pi']))
    print(f"  Enumerated {len(slots)} candidate Parts from input MSBs")

    # For each capped cp, score every slot
    reserved_slot_keys = set()  # (msb, pi) already taken — don't double-book
    n_reserved = 0
    n_skipped = 0

    # Process cap=1 cps first (more restrictive picks first), then cap=2.
    # v0.23.11: within each cap tier, RANDOMIZE the c-prefix processing
    # order. Previously sorted by (cap, c-prefix-alphabetical), which meant
    # c4500 always grabbed its top slot before c4501 before c4503, etc.
    # Result: capped chrs with overlapping ideal-slot pools always got the
    # same allocation outcome — the alphabetically-first chr in each tier
    # locked in its preferred slots every run, downstream chrs got
    # second-best, and the standup-GG → Miranda Blossom convergence pattern
    # repeated across seeds.
    #
    # Fix: shuffle. The shuffle distributes which chr gets first pick
    # across seeds (driven by the seeded RNG, so each seed is still
    # deterministic — just no longer always the alphabetically-first one).
    #
    # v0.24.76 secondary sort by size_class — REMOVED in v0.26.x-late.
    # The size-first order pushed M-humanoid chrs (Midra, Romina,
    # Messmer) down in iteration order. Combined with arena_only +
    # NB-strict gates that gave them very narrow pools, by the time
    # their turn came the qualifying slots were taken by earlier
    # bigger chrs and they ended up unplaced. User direction: pure
    # random per-seed order, no size bucketing. Every chr gets the
    # same expected probability of being an early picker across seeds.
    # v0.26.x: reservation pre-pass iterates V3_RESERVATION_FLOORS,
    # NOT V3_UNIQUE_TARGET_CAPS. The floor is the per-seed guarantee
    # — "try to seat at least N quality slots for this chr." The
    # ceiling (V3_UNIQUE_TARGET_CAPS) is enforced separately at the
    # runtime cap-check call sites — it limits the max but doesn't
    # drive reservation. Chrs in V3_UNIQUE_TARGET_CAPS but NOT in
    # V3_RESERVATION_FLOORS get ceiling-only enforcement (no
    # guaranteed reservation; they place organically against the cap).
    #
    # v0.26.x-late: pure random order per seed (no size-bucket sort).
    # The previous code sorted by (cap, size_class) on the theory
    # that bigger chrs need to reserve first to grab their scarce
    # geometry. That backfired for narrow-pool NB chrs (e.g. Midra,
    # Romina): the size sort pushed them down because they're M-size,
    # but their scoring pool was actually narrower than the XL chrs
    # going first. Result: first-pickers got the few qualifying
    # slots, narrow-pool chrs ended up unplaced. Random per-seed
    # order gives every chr the same expected probability of being
    # an early picker across seeds.
    capped_items = list(V3_RESERVATION_FLOORS.items())
    rng.shuffle(capped_items)
    for target_cp, cap in capped_items:
        # Skip cps that runtime would block anyway. Most importantly,
        # multiplayer_safe injects heritage cps into the ghost-excludes,
        # so this gate keeps heritage out of reservations during mp_safe
        # runs. Logged in unplaced so the spoiler reads cleanly.
        if target_cp in runtime_target_excludes:
            _unplaced_log.append({
                'cp': target_cp,
                'cap': cap,
                'reason': 'runtime_excluded (multiplayer_safe or hard-blocklist)',
                'best_attempt': None,
            })
            continue
        # Adjust cap by already-placed-from-source-preservation
        already = already_placed_counts.get(target_cp, 0)
        n_to_reserve = cap - already
        if n_to_reserve <= 0:
            # Cap fully consumed by source preservation — bump count and
            # log the situation.
            _placed_counts[target_cp] = already
            print(f"  {target_cp}: cap={cap} fully consumed by source "
                  f"preservation ({already} preserved); no reservations "
                  f"needed")
            continue

        # Score all slots for this target
        scored = []
        for s in slots:
            key = (s['msb'], s['pi'])
            if key in reserved_slot_keys:
                continue
            score = _score_slot_for_unique(s, target_cp, tags)
            if score is None:
                continue
            scored.append((score, s))
        if not scored:
            _unplaced_log.append({
                'cp': target_cp,
                'cap': cap,
                'reason': 'no_qualifying_slots',
                'best_attempt': None,
            })
            n_skipped += 1
            continue

        # Sort by score desc; rng tiebreak so seeds don't stick to the
        # same first-MSB-alphabetical slot.
        scored.sort(key=lambda sx: (-sx[0], rng.random()))

        # v0.23.11: probabilistic top-K selection. Previously picked
        # scored[0] strictly — which meant if the best slot for a chr
        # was uniquely top-scored (no ties), that slot got reserved
        # every seed regardless of RNG. Result: c4480 Miranda Blossom
        # always landed at m38_00 pi=51 Guardian Golem Cathedral
        # because that was the unique highest-scoring anim-compatible
        # non-CALIBER-gated slot.
        #
        # Fix: pick weighted-random from top-K candidates within
        # SCORE_TOLERANCE points of the best score. Weight by
        # exp(score - best_score) so higher-scored slots are still
        # strongly preferred but not deterministic. Captures the
        # "good slot" intent of the scoring system while breaking
        # the deterministic lock-in.
        #
        # SCORE_TOLERANCE=5 because typical scoring increments are
        # 3 (size), 5 (NB marker), 10 (boss arena) — 5 captures
        # "within one major bonus" of the top.
        SCORE_TOLERANCE = 5
        best_score = scored[0][0]
        top_band = [(s, slot) for s, slot in scored
                    if s >= best_score - SCORE_TOLERANCE]
        if len(top_band) == 1:
            first_score, first_slot = top_band[0]
        else:
            import math
            weights = [math.exp(s - best_score) for s, _ in top_band]
            chosen_idx = rng.choices(range(len(top_band)), weights=weights, k=1)[0]
            first_score, first_slot = top_band[chosen_idx]
        first_key = (first_slot['msb'], first_slot['pi'])
        _reservations[first_key] = target_cp
        reserved_slot_keys.add(first_key)
        # Pre-bump count so the cap-exhausted subtraction in pick_target_cp
        # sees this c-prefix as already-filled BEFORE any per-MSB processing.
        # Without this, the alphabetically-first MSB whose slot rolls a
        # capped cp organically would consume cap room before the reserved
        # slot's turn, causing over-cap placements.
        _placed_counts[target_cp] = _placed_counts.get(target_cp, 0) + 1
        n_reserved += 1

        if n_to_reserve == 1:
            print(f"  {target_cp} (cap={cap}): reserved at "
                  f"{first_slot['msb']} pi={first_slot['pi']} "
                  f"(score={first_score})")
            continue

        # cap=2 path: pick second slot with geographic spread preference.
        # Heuristic: extract m60_XX_YY tile coords if applicable, prefer
        # slots whose tile is far from first_slot's tile. For
        # non-overworld MSBs, just pick second-highest-scored.
        def _tile_xy(msb):
            # m60_44_38_20.msb → (44, 38). Other MSBs return None.
            parts = msb.replace('.msb', '').split('_')
            if len(parts) >= 4 and parts[0] == 'm60':
                try:
                    return (int(parts[1]), int(parts[2]))
                except ValueError:
                    return None
            return None

        first_xy = _tile_xy(first_slot['msb'])
        # Re-score: combine original score with distance bonus
        rescored = []
        for score, s in scored[1:]:
            key = (s['msb'], s['pi'])
            if key in reserved_slot_keys:
                continue
            xy = _tile_xy(s['msb'])
            if first_xy is not None and xy is not None:
                dist = abs(xy[0] - first_xy[0]) + abs(xy[1] - first_xy[1])
                rescored.append((score + dist * 0.5, s))
            else:
                # Different-MSB-class is itself a kind of spread
                if s['msb'] != first_slot['msb']:
                    rescored.append((score + 1, s))
                else:
                    rescored.append((score - 5, s))  # same MSB penalty
        rescored.sort(key=lambda sx: (-sx[0], rng.random()))
        second_score, second_slot = rescored[0]
        second_key = (second_slot['msb'], second_slot['pi'])
        _reservations[second_key] = target_cp
        reserved_slot_keys.add(second_key)
        # Pre-bump count for the second slot too, same reason as first slot.
        _placed_counts[target_cp] = _placed_counts.get(target_cp, 0) + 1
        n_reserved += 1
        print(f"  {target_cp} (cap={cap}): reserved at "
              f"{first_slot['msb']} pi={first_slot['pi']} "
              f"(score={first_score}) AND "
              f"{second_slot['msb']} pi={second_slot['pi']} "
              f"(score={second_score:.1f})")

    print(f"  Total reservations: {n_reserved}; "
          f"skipped (no qualifying slot): {n_skipped}")

    # v0.27.13: VARIANT-GROUP floor pass (Option B — the floor half).
    # The c-prefix floor loop above reserves (msb,pi) -> cp. A group
    # floor needs the reservation to also pin which variant GROUP lands
    # there, so the guarantee is ">=N Divine Bird Warriors", not just
    # ">=N c5250s". The reserved VALUE becomes a (cp, group) tuple for
    # these; pick_target_cp strips it back to cp for its return, and
    # pick_variant_for_tier honors the pinned group.
    #
    # Runs AFTER the c-prefix pass so group floors compete for whatever
    # slots the chr-level reservations didn't take (reserved_slot_keys
    # is shared). Slot scoring reuses _score_slot_for_unique on the bare
    # c-prefix — group is a variant-loadout distinction, so the same
    # chr-asset slot-fit scoring applies; the group only constrains the
    # downstream variant pick, not which slots qualify.
    #
    # Caps still bound the ceiling: a group floor of 1 plus a group cap
    # of 18 means "between 1 and 18". The floor reservation pre-bumps
    # the group count (same pre-bump rationale as the c-prefix path) so
    # the cap filter in pick_variant_for_tier sees the reserved
    # placement.
    _grp_floors = _load_variant_groups()[2]
    if _grp_floors:
        _grp_items = list(_grp_floors.items())
        rng.shuffle(_grp_items)
        _grp_reserved = 0
        for (gcp, gname), gfloor in _grp_items:
            if gcp in runtime_target_excludes:
                continue
            for _ in range(gfloor):
                scored = []
                for s in slots:
                    key = (s['msb'], s['pi'])
                    if key in reserved_slot_keys:
                        continue
                    score = _score_slot_for_unique(s, gcp, tags)
                    if score is None:
                        continue
                    scored.append((score, s))
                if not scored:
                    _unplaced_log.append({
                        'cp': gcp, 'group': gname, 'cap': gfloor,
                        'reason': 'no_qualifying_slots_for_group',
                        'best_attempt': None})
                    continue
                scored.sort(key=lambda sx: (-sx[0], rng.random()))
                _best = scored[0][0]
                _band = [(s, sl) for s, sl in scored if s >= _best - 5]
                if len(_band) == 1:
                    _gs, _gslot = _band[0]
                else:
                    import math as _m
                    _w = [_m.exp(s - _best) for s, _ in _band]
                    _gi = rng.choices(range(len(_band)), weights=_w, k=1)[0]
                    _gs, _gslot = _band[_gi]
                _gkey = (_gslot['msb'], _gslot['pi'])
                # reserved value is the (cp, group) tuple — the signal
                # that pick_variant_for_tier must pin the group.
                _reservations[_gkey] = (gcp, gname)
                reserved_slot_keys.add(_gkey)
                # pre-bump BOTH the c-prefix count (cap-exhaustion gate
                # in pick_target_cp) and the group count (cap filter in
                # pick_variant_for_tier) — the reservation occupies one
                # of each budget.
                _placed_counts[gcp] = _placed_counts.get(gcp, 0) + 1
                _placed_counts[(gcp, gname)] = (
                    _placed_counts.get((gcp, gname), 0) + 1)
                _grp_reserved += 1
                print(f"  {gcp}/{gname} (floor={gfloor}): reserved at "
                      f"{_gslot['msb']} pi={_gslot['pi']} (score={_gs})")
        print(f"  Variant-group floor reservations: {_grp_reserved}")
