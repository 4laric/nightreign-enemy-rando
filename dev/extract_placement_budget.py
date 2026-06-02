#!/usr/bin/env python3
"""
extract_placement_budget.py
===========================

One-shot extractor that captures the post-load state of the placement-
budget V3_* constants in `oops_v3.py` and emits it as a single JSON
file at `data/placement_budget.json`.

This is **step 1** of the TODO's "Factor out caps + pools as first-class
data" plan. It's read-only against the engine — no behavior change.
Step 2 (engine reads the JSON if present, falls through to inline
constants otherwise) is a separate piece of work.

What's captured per c-prefix
----------------------------

For each c-prefix that appears in at least one V3_* set or has a cap
entry, an entry is produced with these factual fields:

    cap                 int | null   per-c-prefix placement cap (else global default)
    exclude             bool         in V3_EXCLUDE_TARGET_PREFIXES?
    ghost_exclude       bool         in V3_GHOST_EXCLUDE_TARGET_PREFIXES?
    arena_only          bool         in V3_ARENA_ONLY_TARGETS?
    fragile_sensitive   bool         in V3_FRAGILE_SENSITIVE_TARGETS?
    nb_strict           bool         in V3_NIGHT_BOSS_STRICT_TARGETS?
    nb_caliber          bool         in V3_NIGHT_BOSS_CALIBER_TARGETS?
    map_excludes        list[str]    sorted list of map-prefix keys that
                                     have this c-prefix in their exclude
                                     set (e.g. ["m60_"])

Plus an editorial `name` field sourced from `nr_enemy_tags.json` for
human readability when scanning the file.

What's NOT yet captured (placeholders only, all initialized to null/[]):

    rationale     reason this chr has its current cap/gate stack
    since         version where the current state was reached
    history       list of {version, change, reason} entries
    tags          short-label classifiers (heritage, mmv_import, ds1, etc.)

Those four are *editorial* fields proposed in the TODO. They can't be
mechanically derived from the engine constants — they need maintainer
input. The schema is established here so the GUI later (and any
manual edits in the meantime) have stable fields to write into.

Round-trip property
-------------------

The extraction is byte-stable: running it twice gives identical output.
The companion `reconstruct_sets()` function takes the JSON state and
rebuilds the V3_* sets — `tests/test_extract_placement_budget.py`
asserts those reconstructed sets equal the engine's live state, so any
drift between the engine constants and the committed JSON file fails
tests at commit time.

Usage
-----

    python3 dev/extract_placement_budget.py
        → writes data/placement_budget.json

    python3 dev/extract_placement_budget.py --stdout
        → writes JSON to stdout (no file changes)

    python3 dev/extract_placement_budget.py --check
        → asserts the committed JSON matches what extraction produces.
          Exit 1 if drift detected.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)


# Default location for the output. Tests use this path too.
DEFAULT_OUTPUT_PATH = os.path.join(PROJECT_ROOT, 'data', 'placement_budget.json')


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_budget(engine, tags: dict | None = None,
                   preserve_editorial_from: str | None = None) -> dict:
    """Build the placement-budget dict from a loaded engine module.

    Args:
        engine:  oops_v3-shaped module. Must be post-load_data() —
                 callers either pass `oops_v3` after calling
                 `engine.load_data()` or pass a duck-typed object with
                 the V3_* attrs populated.
        tags:    nr_enemy_tags-shaped dict (chr → tag-row). Used only
                 to source the editorial `name` field. If omitted, the
                 file is loaded from the standard location.
        preserve_editorial_from:
                 Optional path to an existing placement_budget.json.
                 If provided, the editorial fields (rationale,
                 exclude_reason, since, history, tags) are PRESERVED
                 from that file rather than emitted as null/empty.
                 This is what re-running the extractor on the committed
                 JSON should do: regenerate engine-derived facts while
                 leaving the human-managed rationale intact.

                 Defaults to None for back-compat with the round-trip
                 test fixture (which passes a duck-typed engine with no
                 corresponding JSON history); the CLI passes the
                 default path to preserve real editorial content.

    Returns:
        A dict suitable for `json.dump`. Top-level keys:
            _meta              metadata
            global_default_cap V3_TARGET_PLACEMENT_CAP
            chrs               {c_prefix: {...fields...}}
    """
    if tags is None:
        tags_path = os.path.join(PROJECT_ROOT, 'data', 'nr_enemy_tags.json')
        with open(tags_path, encoding='utf-8') as f:
            tags = json.load(f)

    # Load existing editorial fields if a preservation source is given.
    _existing_editorial: dict[str, dict] = {}
    if preserve_editorial_from is not None and os.path.exists(preserve_editorial_from):
        with open(preserve_editorial_from, encoding='utf-8') as f:
            _existing = json.load(f)
        for cp, e in _existing.get('chrs', {}).items():
            _existing_editorial[cp] = {
                'rationale':      e.get('rationale'),
                'exclude_reason': e.get('exclude_reason'),
                'since':          e.get('since'),
                'history':        e.get('history') or [],
                'tags':           e.get('tags') or [],
            }

    caps = dict(engine.V3_UNIQUE_TARGET_CAPS)
    excl = set(engine.V3_EXCLUDE_TARGET_PREFIXES)
    ghost = set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
    arena_only = set(engine.V3_ARENA_ONLY_TARGETS)
    fragile = set(engine.V3_FRAGILE_SENSITIVE_TARGETS)
    nb_strict = set(engine.V3_NIGHT_BOSS_STRICT_TARGETS)
    nb_caliber = set(engine.V3_NIGHT_BOSS_CALIBER_TARGETS)
    # v0.26.x schema_version=2: TODO-wishlist additions.
    # V3_MP_SAFE_BLOCKLIST is populated during load_data() (post pack-
    # loader, ~200 entries) so we read post-load only.
    mp_safe = set(getattr(engine, 'V3_MP_SAFE_BLOCKLIST', set()))
    # v0.26.x post-cleanup: V3_TAG_OVERRIDES removed (flattened into
    # nr_enemy_tags.json and mmv_imports.json). Field kept in the schema
    # but populated from the per-entry _tier_override_v0_26_x annotation
    # on each chr's tag dict. Stable pre/post load (JSON-sourced).
    tag_overrides = {cp: t for cp, t in tags.items()
                     if isinstance(t, dict)
                     and '_tier_override_v0_26_x' in t}
    map_excludes = engine.V3_MAP_PREFIX_TARGET_EXCLUDES
    default_cap = engine.V3_TARGET_PLACEMENT_CAP

    # Reverse map: c_prefix → sorted list of map-prefixes that exclude it
    cp_to_map_excludes: dict[str, list[str]] = {}
    for map_prefix, cps in map_excludes.items():
        for cp in cps:
            cp_to_map_excludes.setdefault(cp, []).append(map_prefix)
    for cp in cp_to_map_excludes:
        cp_to_map_excludes[cp].sort()

    # The universe: every c-prefix touched by at least one budget fact.
    # Caps with a cap value equal to the default_cap don't count as a
    # "fact" but in practice that case doesn't arise (the dict only
    # holds per-c-prefix overrides).
    universe: set[str] = set()
    universe.update(caps.keys())
    universe.update(excl)
    universe.update(ghost)
    universe.update(arena_only)
    universe.update(fragile)
    universe.update(nb_strict)
    universe.update(nb_caliber)
    universe.update(mp_safe)
    universe.update(tag_overrides.keys())
    universe.update(cp_to_map_excludes.keys())

    chrs: dict[str, dict[str, Any]] = {}
    for cp in sorted(universe):
        tag = tags.get(cp, {})
        entry: dict[str, Any] = {
            # Editorial — sourced from tags for human readability and
            # to give the GUI / queries enough context to be useful
            # without joining against tags.json. Post-override values
            # where applicable (e.g. `tier` reflects V3_TAG_OVERRIDES).
            'name':   tag.get('name'),
            'tier':   tag.get('tier'),     # v0.26.x: schema_version=2
            'source': tag.get('_source'),  # v0.26.x: schema_version=2
            # Factual — derived from V3_* sets / caps
            'cap': caps.get(cp),  # None if no override
            'exclude': cp in excl,
            'ghost_exclude': cp in ghost,
            'arena_only': cp in arena_only,
            'fragile_sensitive': cp in fragile,
            'nb_strict': cp in nb_strict,
            'nb_caliber': cp in nb_caliber,
            # v0.26.x: TODO-wishlist additions (schema_version=2)
            'mp_safe_blocked': cp in mp_safe,
            'tier_override':   cp in tag_overrides,
            'map_excludes': cp_to_map_excludes.get(cp, []),
            # Editorial fields — preserved from `preserve_editorial_from`
            # if given (CLI path), otherwise null/empty (used by the
            # round-trip test with a duck-typed engine and no JSON
            # history to preserve from).
            'rationale':      _existing_editorial.get(cp, {}).get('rationale'),
            'exclude_reason': _existing_editorial.get(cp, {}).get('exclude_reason'),
            'since':          _existing_editorial.get(cp, {}).get('since'),
            'history':        _existing_editorial.get(cp, {}).get('history', []) or [],
            'tags':           _existing_editorial.get(cp, {}).get('tags', []) or [],
        }
        chrs[cp] = entry

    engine_fingerprint = getattr(engine, 'V3_ENGINE_FINGERPRINT', None)

    return {
        '_meta': {
            '_generator': 'dev/extract_placement_budget.py',
            '_origin': 'post-load snapshot of oops_v3.V3_* constants',
            '_engine_fingerprint': engine_fingerprint,
            '_schema_version': 2,
            '_notes': [
                'Sparse: only c-prefixes with at least one non-default fact',
                'are included. Anything not in `chrs` uses defaults (cap=',
                'global_default_cap, no excludes, no special pool membership).',
                '',
                'Editorial fields (name, tier, source) are mirrored from',
                'nr_enemy_tags.json (post-override) for human readability.',
                'Editorial *placeholder* fields (rationale, exclude_reason,',
                'since, history, tags) are reserved for human editing and',
                'start null/empty. None of these editorial fields are',
                'validated against engine state by the round-trip test.',
                '',
                'Schema v2 (v0.26.x): added tier, source, mp_safe_blocked,',
                'tier_override, exclude_reason fields per TODO wishlist.',
            ],
        },
        'global_default_cap': default_cap,
        'chrs': chrs,
    }


# ---------------------------------------------------------------------------
# Reconstruction (inverse — for round-trip verification)
# ---------------------------------------------------------------------------

# The set of factual fields the extractor → engine direction must
# round-trip cleanly. Editorial fields are deliberately excluded —
# they don't exist on the engine side, so they have nothing to round-
# trip against.
_FACTUAL_SET_FIELDS = (
    ('exclude',           'V3_EXCLUDE_TARGET_PREFIXES'),
    ('ghost_exclude',     'V3_GHOST_EXCLUDE_TARGET_PREFIXES'),
    ('arena_only',        'V3_ARENA_ONLY_TARGETS'),
    ('fragile_sensitive', 'V3_FRAGILE_SENSITIVE_TARGETS'),
    ('nb_strict',         'V3_NIGHT_BOSS_STRICT_TARGETS'),
    ('nb_caliber',        'V3_NIGHT_BOSS_CALIBER_TARGETS'),
    # v0.26.x schema_version=2 additions
    ('mp_safe_blocked',   'V3_MP_SAFE_BLOCKLIST'),
    # Note: `tier_override` deliberately NOT in this list. The engine's
    # V3_TAG_OVERRIDES is a dict (cp → {field: value}) rather than a
    # membership set, so a boolean budget field can only round-trip the
    # *presence* of an override, not its content. Round-tripping the
    # full override payload would require a separate field-of-dicts in
    # the budget schema; deferred until a concrete use case appears.
)


def reconstruct_sets(budget: dict) -> dict[str, Any]:
    """Inverse of extract_budget(): given a budget dict, rebuild the
    V3_* sets it represents. Used by the round-trip test to verify
    that the JSON faithfully captures the engine state.

    Returns a dict with keys matching the V3_* constant names, so the
    caller can compare element-by-element against the engine module.
    """
    chrs = budget['chrs']

    # Caps: only non-None values
    caps = {cp: e['cap'] for cp, e in chrs.items() if e.get('cap') is not None}

    # Boolean-membership sets
    sets: dict[str, set[str]] = {}
    for field, v3_name in _FACTUAL_SET_FIELDS:
        sets[v3_name] = {cp for cp, e in chrs.items() if e.get(field)}

    # Map-prefix excludes: invert cp → maps to map → cps
    map_excludes: dict[str, set[str]] = {}
    for cp, e in chrs.items():
        for map_prefix in e.get('map_excludes', []):
            map_excludes.setdefault(map_prefix, set()).add(cp)

    return {
        'V3_UNIQUE_TARGET_CAPS': caps,
        'V3_MAP_PREFIX_TARGET_EXCLUDES': map_excludes,
        'V3_TARGET_PLACEMENT_CAP': budget['global_default_cap'],
        **sets,
    }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def render_json(budget: dict) -> str:
    """Deterministic JSON serialization. Returns a string ending in a
    newline. The exact formatting matters for byte-stability tests.

    Note: sort_keys=True is used inside chr entries (alphabetical field
    order). The top-level dict order (_meta, global_default_cap, chrs)
    is preserved by Python's insertion-ordered dicts.
    """
    return json.dumps(budget, indent=2, sort_keys=True, ensure_ascii=False) + '\n'


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_engine_and_extract() -> dict:
    """Import oops_v3, run load_data(), and produce the budget dict.

    Note: we pass the post-load tags dict returned by `load_data()` so
    `extract_budget` sees the same augmented tag set the engine uses
    at runtime (mmv_imports, heritage_pack, and post_dlc_dump all add
    chr entries during load). Falling back to reading the raw
    `nr_enemy_tags.json` would produce `name: null` for hundreds of
    runtime-loaded chrs and the on-disk JSON would drift from what
    tests see via the `tags` fixture.
    """
    import oops_v3
    _, tags = oops_v3.load_data()
    # Preserve editorial fields (rationale, exclude_reason, since,
    # history, tags) from the existing committed JSON if present.
    # Falls through to None on first-time bootstrap.
    return extract_budget(
        oops_v3, tags=tags,
        preserve_editorial_from=DEFAULT_OUTPUT_PATH,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split('\n\n')[0],
    )
    parser.add_argument(
        '--output', metavar='PATH', default=DEFAULT_OUTPUT_PATH,
        help=f'Output path (default: {os.path.relpath(DEFAULT_OUTPUT_PATH, PROJECT_ROOT)})',
    )
    parser.add_argument(
        '--stdout', action='store_true',
        help='Write JSON to stdout instead of a file',
    )
    parser.add_argument(
        '--check', action='store_true',
        help=('Check mode: compare extraction against existing file at '
              '--output. Exit 1 if drift detected. Useful in CI.'),
    )
    args = parser.parse_args(argv)

    budget = _load_engine_and_extract()
    rendered = render_json(budget)

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    if args.check:
        if not os.path.exists(args.output):
            sys.stderr.write(f'ERROR: --check but {args.output} does not exist\n')
            return 1
        with open(args.output, encoding='utf-8') as f:
            existing = f.read()
        if existing != rendered:
            sys.stderr.write(
                f'ERROR: {args.output} is out of date with engine state.\n'
                f'Run: python3 dev/extract_placement_budget.py\n'
            )
            return 1
        print(f'OK: {os.path.relpath(args.output, PROJECT_ROOT)} matches engine state.')
        return 0

    # Default: write to file
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(rendered)
    chr_count = len(budget['chrs'])
    print(f'Wrote {os.path.relpath(args.output, PROJECT_ROOT)} '
          f'({chr_count} c-prefixes).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
