"""Step 2 / 2b / 3 of the TODO placement-budget refactor — JSON loader.

WHAT THIS DOES
--------------
At engine module-import time, reads `data/placement_budget.json` and
populates the JSON-sourced `V3_*` constants in `oops_v3.py`. The
inline definitions in oops_v3 are now empty placeholders (post-Step-3);
this loader is the sole population path.

If the JSON is missing or malformed, `apply_static_overrides` returns
False without mutating the target. In oops_v3.py that triggers a
RuntimeError at module-load — production engine cannot start without
the JSON. Tests that exercise dummy modules can still observe the
False return path; only the live engine treats the JSON as mandatory.

SCOPE: WHICH SETS, WHY
----------------------
The placement_budget JSON covers 10 `V3_*` constants in total. NINE
are sourced from JSON here; one (V3_MP_SAFE_BLOCKLIST) is excluded as
pure-derived.

  PURE STATIC (Step 2 — JSON-sourced; one source of truth):
      V3_GHOST_EXCLUDE_TARGET_PREFIXES
      V3_FRAGILE_SENSITIVE_TARGETS
      V3_MAP_PREFIX_TARGET_EXCLUDES
      V3_TARGET_PLACEMENT_CAP

  IDEMPOTENTLY MUTATED (Step 2b — JSON pre-loads post-load snapshot;
  load_data's derivations re-apply identically and the net effect is
  a no-op):
      V3_UNIQUE_TARGET_CAPS         — load_data item-assigns by tier
                                      (miniboss=4, mount=30, grunt=40,
                                      rare-novelty=4); same chr always
                                      gets the same cap.
      V3_EXCLUDE_TARGET_PREFIXES    — load_data does `|= new_cps` and
                                      `= _assemble_exclude_target_prefixes(
                                      tags, roster, loader_stats)`,
                                      both unions on top of the base.
      V3_NIGHT_BOSS_STRICT_TARGETS  — retired in v0.26.x; empty.
      V3_NIGHT_BOSS_CALIBER_TARGETS — load_data does `= self | adds`;
                                      idempotent.
      V3_ARENA_ONLY_TARGETS         — load_data does `| auto_adds`, then
                                      `- m_size_lift`, then `- force_lift`.
                                      Net-zero on post-load JSON state.

  DERIVED, NOT JSON-SOURCED:
      V3_MP_SAFE_BLOCKLIST  — load_data computes this entirely from
                              the per-tag `_source` field via a hard
                              replacement, wiping any pre-loaded
                              value. The JSON's `mp_safe_blocked`
                              field is snapshot-only.

POST-STEP-3 OPERATIONAL NOTES
-----------------------------
- To edit an editorial decision (cap, ban, etc.): edit the JSON
  directly. The change takes effect on next engine import.
- To bootstrap the JSON from scratch: revert oops_v3.py to a
  pre-Step-3 revision (git), let it populate from the inline literals,
  then run `python3 dev/extract_placement_budget.py` to regenerate.
- The per-chr editorial fields (`rationale`, `since`, `history`,
  `exclude_reason`) are populated lazily as entries are revisited.
  Pre-Step-3 inline comments are preserved in oops_v3.py's git
  history; future entries should document their rationale in the
  JSON.

IDEMPOTENCE INVARIANT
---------------------
For the five idempotently-mutated sets, calling `load_data()` after
this loader has run must produce the same final state as calling
`load_data()` against the pre-Step-3 inline-literal bases. The
round-trip test in `tests/test_extract_placement_budget.py
::TestLiveEngine::test_committed_file_matches_engine_state` enforces
that the JSON IS in sync. If a future load_data edit introduces a
non-idempotent op for any of these five sets, that test will break
and the set needs to be removed from this loader's scope (or the
load_data op needs to be reworked).
"""
from __future__ import annotations

import json
import os
from typing import Any


_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_DEFAULT_BUDGET_PATH = os.path.join(_PROJECT_ROOT, 'data', 'placement_budget.json')


# (json_field, V3_const_name) for boolean-membership sets that this
# loader is authoritative for. Order matters only for the print summary;
# values are independent.
#
# NOTE: 'mp_safe_blocked' is INTENTIONALLY ABSENT — see the docstring's
# "DERIVED, NOT JSON-SOURCED" section. load_data computes
# V3_MP_SAFE_BLOCKLIST entirely from per-tag _source rules and wipes
# any pre-loaded value. The JSON's mp_safe_blocked field is a snapshot
# for tooling only.
_JSON_SOURCED_BOOLEAN_SETS = (
    # Step 2 (pure-static):
    ('ghost_exclude',     'V3_GHOST_EXCLUDE_TARGET_PREFIXES'),
    ('fragile_sensitive', 'V3_FRAGILE_SENSITIVE_TARGETS'),
    # Step 2b (idempotently mutated by load_data):
    ('exclude',           'V3_EXCLUDE_TARGET_PREFIXES'),
    ('nb_strict',         'V3_NIGHT_BOSS_STRICT_TARGETS'),
    ('nb_caliber',        'V3_NIGHT_BOSS_CALIBER_TARGETS'),
    ('arena_only',        'V3_ARENA_ONLY_TARGETS'),
)


def load_budget(path: str | None = None) -> dict | None:
    """Read a placement_budget JSON file. Returns the parsed dict, or
    None if the file is missing/malformed/wrong-shape. The caller
    interprets None as "fall back to inline literals."
    """
    if path is None:
        path = _DEFAULT_BUDGET_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    # Shape validation — must have a `chrs` dict. Anything else is
    # treated as malformed.
    if not isinstance(d, dict) or not isinstance(d.get('chrs'), dict):
        return None
    return d


def build_static_overrides(budget: dict) -> dict[str, Any]:
    """Build the V3_* override values from a parsed budget dict.
    Returns {V3_name: value}; caller assigns each onto the engine
    module (or namespace dict).

    Covered sets are listed in the module docstring under "SCOPE: WHICH
    SETS, WHY". Returns one entry per covered set IFF the JSON has
    data for it. The 'global_default_cap' field is optional in the
    schema (older snapshots may omit it) — if absent,
    V3_TARGET_PLACEMENT_CAP is omitted from the result and the inline
    fallback stands.

    Types match the inline-literal types in oops_v3.py:
      V3_UNIQUE_TARGET_CAPS:               dict[str, int]
      V3_GHOST_EXCLUDE_TARGET_PREFIXES:    set[str]
      V3_FRAGILE_SENSITIVE_TARGETS:        set[str]
      V3_EXCLUDE_TARGET_PREFIXES:          set[str]
      V3_NIGHT_BOSS_STRICT_TARGETS:        set[str]
      V3_NIGHT_BOSS_CALIBER_TARGETS:       set[str]
      V3_ARENA_ONLY_TARGETS:               set[str]
      V3_MAP_PREFIX_TARGET_EXCLUDES:       dict[str, set[str]]
      V3_TARGET_PLACEMENT_CAP:             int
    """
    chrs = budget['chrs']  # validated by load_budget
    out: dict[str, Any] = {}

    # Caps — dict[cp -> int], excluding null entries (which mean "no
    # override, use the global default"). Composition with load_data:
    # the tier loops in load_data item-assign caps deterministically
    # (same chr always gets the same cap), so re-running them after
    # this loader's dict-replacement is identity.
    caps = {cp: e['cap'] for cp, e in chrs.items() if e.get('cap') is not None}
    out['V3_UNIQUE_TARGET_CAPS'] = caps

    # Boolean-membership sets — plain `set` (not `frozenset`) to match
    # the inline-literal types. Several of these are mutated by
    # load_data via set unions / item-additions; those ops are
    # idempotent on a JSON-pre-loaded post-load state.
    for field, v3_name in _JSON_SOURCED_BOOLEAN_SETS:
        out[v3_name] = {cp for cp, e in chrs.items() if e.get(field)}

    # Map-prefix excludes: invert per-chr's `map_excludes` list into
    # per-map sets.
    map_excludes: dict[str, set[str]] = {}
    for cp, e in chrs.items():
        for map_prefix in e.get('map_excludes', []):
            map_excludes.setdefault(map_prefix, set()).add(cp)
    out['V3_MAP_PREFIX_TARGET_EXCLUDES'] = map_excludes

    # Default placement cap (optional in schema).
    if 'global_default_cap' in budget:
        out['V3_TARGET_PLACEMENT_CAP'] = budget['global_default_cap']

    return out


def apply_static_overrides(target, path: str | None = None,
                           verbose: bool = True) -> bool:
    """Read placement_budget.json (if present) and override the pure-
    static V3_* sets on `target`.

    `target` accepts either:
      - a module object (uses setattr to install V3_* names); or
      - a dict, typically `globals()` at module-init time (uses item
        assignment).

    Both are supported because `oops_v3.py` can be imported either via
    the normal import system (where `sys.modules[__name__]` works) or
    via `importlib.util.spec_from_file_location` (where it doesn't —
    `dev/simulate_engine.py` uses this path with name='o'). Passing
    `globals()` from the engine module sidesteps the import-mode
    difference.

    Returns True if the override was applied, False if the JSON was
    absent or malformed and inline fallbacks remain in effect.

    Idempotent: calling twice with the same JSON yields the same
    engine state. The override REPLACES rather than extends, so no
    accumulation across calls (unlike the load_data-touched sets).
    """
    budget = load_budget(path)
    if budget is None:
        if verbose:
            print('placement_budget.json: not loaded — '
                  'caller should treat this as fatal (post-Step-3 '
                  'the JSON is the sole source of truth; placeholders '
                  'are empty)')
        return False
    overrides = build_static_overrides(budget)
    if isinstance(target, dict):
        target.update(overrides)
    else:
        for v3_name, value in overrides.items():
            setattr(target, v3_name, value)
    if verbose:
        n_caps = len(overrides.get('V3_UNIQUE_TARGET_CAPS', {}))
        n_ghost = len(overrides.get('V3_GHOST_EXCLUDE_TARGET_PREFIXES', set()))
        n_fragile = len(overrides.get('V3_FRAGILE_SENSITIVE_TARGETS', set()))
        n_exclude = len(overrides.get('V3_EXCLUDE_TARGET_PREFIXES', set()))
        n_arena = len(overrides.get('V3_ARENA_ONLY_TARGETS', set()))
        n_nbcal = len(overrides.get('V3_NIGHT_BOSS_CALIBER_TARGETS', set()))
        n_nbstr = len(overrides.get('V3_NIGHT_BOSS_STRICT_TARGETS', set()))
        n_map_excl = len(overrides.get('V3_MAP_PREFIX_TARGET_EXCLUDES', {}))
        default_cap = overrides.get('V3_TARGET_PLACEMENT_CAP', '<inline>')
        print(
            f'placement_budget.json: loaded; '
            f'caps={n_caps}, exclude={n_exclude}, ghost_exclude={n_ghost}, '
            f'arena_only={n_arena}, nb_caliber={n_nbcal}, '
            f'nb_strict={n_nbstr}, fragile_sensitive={n_fragile}, '
            f'map_excludes={n_map_excl}, default_cap={default_cap}'
        )
    return True
