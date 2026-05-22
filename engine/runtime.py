"""Per-run override application for cmd_shuffle_v3.

WHY THIS EXISTS
---------------
cmd_shuffle_v3 takes 4 kwargs that override module-level gate sets for
the duration of a single run: excluded_prefixes, hub_maps,
multiplayer_safe, force_include_targets. The historical pattern was to
manually save each module global, apply overrides inline, and restore
in a finally block. That worked but had three pain points:

1. The save/apply/restore code was spread across ~80 lines with no
   abstraction boundary. Adding a 5th override meant three separate
   edits (a _saved_X line, the apply block, a restore line) and forgetting
   any one of them would silently leak state.

2. The override COMPOSITION rules — sanitize excluded_prefixes against
   V3_EXCLUDE_SOURCE_PREFIXES (the v0.20.5 bug fix); union
   V3_MP_SAFE_BLOCKLIST into the ghost set for multiplayer_safe;
   subtract force_include_targets from BOTH exclude sets; ensure
   force-include runs LAST so it wins over multiplayer_safe's
   additions — were tangled with the save/restore mechanics, making
   them hard to test in isolation and hard to reason about as a unit.

3. The function had no observable "effective in-scope state" — no
   single object representing "this is what the run actually sees." If
   you wanted to verify that force-include correctly overrode
   multiplayer_safe, you had to instrument the engine or read globals
   at the right moment.

WHAT THIS DOES
--------------
`apply_run_overrides()` is a context manager that owns the entire
per-run override lifecycle:

  - On entry: captures the current values of all module globals it
    might mutate, applies the override composition rules in the
    correct order, and yields a GateState representing the effective
    in-scope state.

  - On exit: restores ALL captured values, whether the body returned
    normally or raised. Atomic — no partial restore.

The composition rules are now in one place, testable without invoking
the picker engine. The save/restore list is closed over a single
SAVED_FIELDS constant — adding a new override means editing this one
file, not three places in cmd_shuffle_v3.

The yielded GateState is a snapshot AFTER overrides apply, so tests
can assert on the effective state directly (e.g. "after
multiplayer_safe is applied, mp_safe_blocklist members are in
ghost_exclude_target_prefixes").
"""
from contextlib import contextmanager

from engine.state import GateState


# Module globals that apply_run_overrides may mutate. Captured on entry,
# restored on exit. Adding a new override here is sufficient — the
# save/restore loop below uses this list as its source of truth.
#
# v0.26.x: V3_UNIQUE_TARGET_CAPS / V3_NIGHT_BOSS_CALIBER_TARGETS added.
# apply_run_overrides does NOT itself *apply* pool/cap overrides — those
# are applied later, inside _cmd_shuffle_v3_impl, by compose_pool_cap_
# overrides() (see its docstring for the load_data-ordering rationale).
# They are listed here purely so this context manager's atomic restore
# also covers them: the override is applied mid-run, this CM's __exit__
# puts the module-default caps/caliber back, so process-global state
# never leaks between runs.
_OWNED_MODULE_FIELDS = (
    'V3_EXCLUDE_PREFIXES',
    'V3_EXCLUDE_TARGET_PREFIXES',
    'V3_GHOST_EXCLUDE_TARGET_PREFIXES',
    'V3_HUB_MAPS',
    'V3_UNIQUE_TARGET_CAPS',
    'V3_NIGHT_BOSS_CALIBER_TARGETS',
)


@contextmanager
def apply_run_overrides(
    module=None,
    *,
    excluded_prefixes=None,
    hub_maps=None,
    multiplayer_safe=False,
    force_include_targets=None,
    log=print,
):
    """Apply per-run overrides to `module` gate state, restore on exit.

    Behavioral parity with the inline pattern in cmd_shuffle_v3 as of
    v0.24.20. Each override applies iff the corresponding kwarg is
    truthy / not None — same semantics as the original code:

      excluded_prefixes (set | None):
          When set, sanitized against module.V3_EXCLUDE_SOURCE_PREFIXES
          (source-only entries stripped — protects against the v0.20.5
          bug) and used as module.V3_EXCLUDE_PREFIXES.

      hub_maps (set | None):
          When set, replaces module.V3_HUB_MAPS for the run.

      multiplayer_safe (bool):
          When True, unions module.V3_MP_SAFE_BLOCKLIST into
          module.V3_GHOST_EXCLUDE_TARGET_PREFIXES. v0.24.20: derived
          from _source tagging, replacing the older
          V3_HERITAGE_ALL_PREFIXES gate.

      force_include_targets (set | None):
          When set, the cps are SUBTRACTED from BOTH
          V3_EXCLUDE_TARGET_PREFIXES and V3_GHOST_EXCLUDE_TARGET_PREFIXES.
          Applied LAST so user-explicit force-includes win over
          multiplayer_safe's heritage block.

      log (callable):
          Function used for operational printing. Defaults to print();
          tests can pass a list.append-style callable to capture logs.

    Yields:
        GateState — snapshot of the effective in-scope state, taken
        AFTER all overrides have been applied. Useful for callers /
        tests that want to introspect or thread the explicit state
        downstream.
    """
    if module is None:
        import oops_v3
        module = oops_v3

    # Capture references to current values. We restore exactly these
    # references on exit, regardless of how the overrides chose to
    # type-coerce (set/frozenset) during the run.
    saved = {name: getattr(module, name) for name in _OWNED_MODULE_FIELDS}

    try:
        # ----- excluded_prefixes -----
        if excluded_prefixes is not None:
            # Sanitize: source-only entries (V3_EXCLUDE_SOURCE_PREFIXES)
            # must NOT leak into the hard-block target set, or they'd
            # never appear as targets either. v0.20.5 bug: GUI was
            # writing user_excluded directly into V3_EXCLUDE_PREFIXES,
            # bloating it with c5110/c4181/c3610/c3620 (Maris cluster
            # source-excludes that should remain valid targets).
            sanitized = (set(excluded_prefixes)
                         - set(module.V3_EXCLUDE_SOURCE_PREFIXES))
            n_stripped = len(set(excluded_prefixes)) - len(sanitized)
            if n_stripped:
                log(f"Sanitized excluded_prefixes: removed {n_stripped} "
                    f"source-only entries that don't belong in V3_EXCLUDE_PREFIXES")
            module.V3_EXCLUDE_PREFIXES = sanitized

        # ----- hub_maps -----
        if hub_maps is not None:
            module.V3_HUB_MAPS = set(hub_maps)

        # ----- multiplayer_safe -----
        # IMPORTANT: union against the SAVED ghost set, not the live
        # one, so re-applying with multiplayer_safe=True after a prior
        # override doesn't accumulate. (The original inline code did the
        # same: _saved_ghost | V3_MP_SAFE_BLOCKLIST.)
        if multiplayer_safe:
            module.V3_GHOST_EXCLUDE_TARGET_PREFIXES = (
                set(saved['V3_GHOST_EXCLUDE_TARGET_PREFIXES'])
                | set(module.V3_MP_SAFE_BLOCKLIST))
            log(f"Multiplayer-safe: ON — blocking "
                f"{len(module.V3_MP_SAFE_BLOCKLIST)} non-vanilla "
                f"c-prefixes as targets")

        # ----- force_include_targets -----
        # MUST be applied AFTER multiplayer_safe, because force-include
        # subtracts from V3_GHOST_EXCLUDE_TARGET_PREFIXES — and we want
        # user explicit choice to win over multiplayer_safe's
        # heritage block. If this ordering reverses, force-include
        # silently has no effect under multiplayer_safe.
        if force_include_targets:
            force_set = set(force_include_targets)
            module.V3_EXCLUDE_TARGET_PREFIXES = (
                set(module.V3_EXCLUDE_TARGET_PREFIXES) - force_set)
            module.V3_GHOST_EXCLUDE_TARGET_PREFIXES = (
                set(module.V3_GHOST_EXCLUDE_TARGET_PREFIXES) - force_set)
            log(f"Force-include: {len(force_set)} c-prefix(es) bypassing "
                f"target excludes — {sorted(force_set)}")

        # Take an "after overrides" snapshot. Yields what the run
        # ACTUALLY sees, not what it was asked to see — invaluable for
        # tests asserting on composition correctness.
        effective = GateState.from_module(module)
        yield effective
    finally:
        # Atomic restore. Even on exception, every owned field goes
        # back to its captured reference. Adding a new owned field
        # only requires extending _OWNED_MODULE_FIELDS above — this
        # loop picks it up automatically.
        for name, value in saved.items():
            setattr(module, name, value)


# =====================================================================
# Pool / cap overrides  (v0.26.x)
# =====================================================================
#
# WHY THIS IS SEPARATE FROM apply_run_overrides
# ---------------------------------------------
# apply_run_overrides composes its state in cmd_shuffle_v3, BEFORE
# _cmd_shuffle_v3_impl runs. But impl calls load_data() a second time
# (see the v0.24.30 hoist comment in cmd_shuffle_v3). load_data folds
# pack-loader contributions into the gate sets:
#
#     V3_NIGHT_BOSS_CALIBER_TARGETS = <current> | _all_caliber
#     V3_UNIQUE_TARGET_CAPS[cp] = 1            # for newly-lifted chrs
#
# Empirically (tested v0.26.9): an *additive* override survives that
# second load_data (the `| _all_caliber` union preserves extras), but a
# *subtractive* one does NOT — a c-prefix removed from the caliber set
# gets unioned straight back in by load_data's pack fold. Same hazard
# applies to force_include's subtraction from V3_EXCLUDE_TARGET_PREFIXES,
# which is a pre-existing latent bug for any force-included cp that also
# lives in the MMV blacklist.
#
# So pool/cap overrides MUST be applied AFTER impl's own load_data(),
# not in the cmd_shuffle_v3-level context manager. compose_pool_cap_
# overrides() is the function impl calls for exactly that. Restoration
# is still handled by apply_run_overrides — V3_UNIQUE_TARGET_CAPS and
# V3_NIGHT_BOSS_CALIBER_TARGETS are in _OWNED_MODULE_FIELDS, so the
# outer CM's atomic __exit__ restore puts the module defaults back even
# though it never applied the override itself.


def compose_pool_cap_overrides(
    module=None,
    *,
    unique_cap_overrides=None,
    caliber_pool_extras=None,
    caliber_pool_removals=None,
    log=print,
):
    """Apply per-run pool/cap overrides to `module`'s gate state.

    Call this from _cmd_shuffle_v3_impl, immediately after the impl's
    own load_data() — see the module comment above for why the timing
    matters. This function only *mutates*; restoration is the caller's
    apply_run_overrides context manager (V3_UNIQUE_TARGET_CAPS and
    V3_NIGHT_BOSS_CALIBER_TARGETS are in _OWNED_MODULE_FIELDS).

    unique_cap_overrides (dict[str, int] | None):
        Per-c-prefix placement-ceiling overrides, merged ON TOP of the
        module's V3_UNIQUE_TARGET_CAPS. An entry here wins over the
        engine default for that cp. A cp absent from the merged dict is
        uncapped (engine default). Values must be >= 1 — a cap of 0
        would starve the reservation pre-pass; use excluded_prefixes /
        the Excluded Enemies list to remove a chr entirely.

    caliber_pool_extras (iterable[str] | None):
        c-prefixes UNIONED into V3_NIGHT_BOSS_CALIBER_TARGETS — i.e.
        made eligible to anchor Night-Boss arena slots. This is the
        "all DLC run" lever: the SoTE bosses are mmv_import chrs that
        the base caliber set doesn't list, so they never reach NB
        anchors without being added here.

    caliber_pool_removals (iterable[str] | None):
        c-prefixes SUBTRACTED from V3_NIGHT_BOSS_CALIBER_TARGETS after
        extras are unioned (so removal wins on conflict). Lets a run
        push a chr OUT of the NB-anchor pool without a full exclude —
        it stays a valid target at field/grunt slots.

    log (callable): operational logging sink; defaults to print().

    Returns:
        dict — a small summary of what changed, for the spoiler / log.
    """
    if module is None:
        import oops_v3
        module = oops_v3

    summary = {
        'caps_overridden': 0,
        'caliber_added': 0,
        'caliber_removed': 0,
    }

    # ----- unique caps -----
    if unique_cap_overrides:
        bad = {cp: v for cp, v in unique_cap_overrides.items()
               if not isinstance(v, int) or v < 1}
        if bad:
            # Don't silently apply a cap that breaks the reservation
            # pass — drop the bad entries and tell the user.
            log(f"compose_pool_cap_overrides: dropped {len(bad)} cap "
                f"override(s) with non-positive / non-int values: "
                f"{sorted(bad)}")
        clean = {cp: v for cp, v in unique_cap_overrides.items()
                 if cp not in bad}
        if clean:
            merged = dict(module.V3_UNIQUE_TARGET_CAPS)
            merged.update(clean)
            module.V3_UNIQUE_TARGET_CAPS = merged
            summary['caps_overridden'] = len(clean)
            log(f"Pool/cap: {len(clean)} per-chr cap override(s) applied "
                f"— {', '.join(f'{cp}={v}' for cp, v in sorted(clean.items()))}")

    # ----- caliber pool -----
    extras = set(caliber_pool_extras or ())
    removals = set(caliber_pool_removals or ())
    if extras or removals:
        before = set(module.V3_NIGHT_BOSS_CALIBER_TARGETS)
        # extras first, removals second — removal is the final veto.
        after = (before | extras) - removals
        added = after - before
        removed = before - after
        module.V3_NIGHT_BOSS_CALIBER_TARGETS = after
        summary['caliber_added'] = len(added)
        summary['caliber_removed'] = len(removed)
        if added:
            log(f"Pool/cap: caliber pool +{len(added)} "
                f"(NB-anchor-eligible) — {sorted(added)}")
        if removed:
            log(f"Pool/cap: caliber pool -{len(removed)} "
                f"(no longer NB-anchor-eligible) — {sorted(removed)}")

    return summary
