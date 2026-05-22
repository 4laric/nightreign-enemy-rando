"""heritage_pack loader.

heritage_pack.json is a DISABLE-ONLY pool toggle. It lists the
c-prefixes that ship in vanilla NR's regulation but require external
chr/anibnd assets (typically SoTE files staged via the Elden Ring
Assets tab) to render correctly. When the pack is enabled (default),
this loader is a no-op — heritage cps already live in the canonical
nr_enemy_tags.json and the roster JSON, this loader doesn't add to
them. When the pack is disabled (either via on-disk _meta.enabled
or via a snapshot pack_override), this loader removes those cps
from the engine's tags + roster so friends-without-SoTE can run a
pure-vanilla pool without the older engine_kwargs.excluded_prefixes
workaround.

This is the simplest of the four pack loaders — single mode of
operation (remove-on-disable), no gate-set mutation, no merge
semantics. Extracted first as a spike to validate the
loader-extraction pattern before tackling er_heritage and mmv,
which have richer merge logic.
"""
from typing import Any, Dict, Set


def apply_heritage_pack(pack_data: Dict[str, Any], *,
                        tags: Dict[str, Any],
                        roster: Dict[str, Any]) -> Dict[str, Any]:
    """Apply heritage_pack.json semantics to the loaded tags + roster.

    Args:
        pack_data: The loaded heritage_pack.json dict. Caller is
            responsible for the JSON file load AND for applying any
            snapshot overrides (`_apply_snapshot_overrides_to_pack`)
            BEFORE handing the dict to this function. This separation
            of concerns is intentional — snapshot override application
            is a cross-cutting load_data concern, not a per-loader one.
        tags: The tags dict to mutate in place. When the pack is
            disabled, heritage cps are removed from this dict.
        roster: The roster dict to mutate in place. `roster['all_variants']`
            is rewritten without variants whose c_prefix is in the
            pack's tag set when the pack is disabled.

    Returns:
        A stats dict for the caller's log line:
            {
                'enabled': bool,         # what _meta.enabled resolved to
                'hp_cps': set[str],      # cps the pack owns (always
                                         # the same set regardless of
                                         # enabled state)
                'n_tag_removed': int,    # 0 when enabled
                'n_variant_removed': int,  # 0 when enabled
            }

    Raises:
        Standard dict-access / type errors on malformed pack_data.
        Caller wraps the call in try/except for graceful degradation.
        We don't catch internally — "pack data is malformed" is a real
        problem the caller should know about, not silently swallow.

    Idempotency:
        Calling this twice with the same pack_data + same tags +
        roster produces the same final state. (First call removes the
        cps; second call sees they're already absent and removes 0
        more.) This matters for the behavior lock — the lock runs
        load_data once, and the loader's invariants need to hold
        whether or not state was previously mutated.
    """
    hp_cps: Set[str] = set(pack_data.get('tags', {}).keys())
    enabled = bool(pack_data.get('_meta', {}).get('enabled', True))

    # Cps with expects_boss_arena=True in the pack manifest. These get
    # promoted to V3_ARENA_ONLY_TARGETS by the caller's post-loader
    # auto-extend, regardless of enabled state — the manifest IS the
    # source of truth for arena-only intent, even though heritage_pack
    # itself doesn't merge tag data when enabled (the cps already live
    # in base nr_enemy_tags.json). Returning this set lets the caller
    # apply the override without reaching back into pack_data.
    arena_only_adds: Set[str] = {
        cp for cp, t in pack_data.get('tags', {}).items()
        if isinstance(t, dict) and t.get('expects_boss_arena')
    }

    if enabled:
        # Pack enabled — heritage cps stay in. No-op since they're
        # already in tags/roster via the base data files.
        return {
            'enabled': True,
            'hp_cps': hp_cps,
            'arena_only_adds': arena_only_adds,
            # Standardized loader-stats shape (Phase 12): heritage_pack
            # doesn't contribute to tier sets or exclusion sets — these
            # empty fields exist so the registry-driven post-loader fold
            # can iterate every loader's stats uniformly without per-
            # loader branching. Empty unions are no-ops.
            'caliber_adds': set(),
            'strict_adds': set(),
            'exclude_target_adds': set(),
            'n_tag_removed': 0,
            'n_variant_removed': 0,
        }

    # Pack disabled — strip heritage cps from tags + roster.
    n_tag_removed = 0
    for cp in list(tags.keys()):
        if cp in hp_cps:
            del tags[cp]
            n_tag_removed += 1

    variants = roster.get('all_variants', [])
    before = len(variants)
    roster['all_variants'] = [
        v for v in variants if v.get('c_prefix') not in hp_cps
    ]
    n_variant_removed = before - len(roster['all_variants'])

    return {
        'enabled': False,
        'hp_cps': hp_cps,
        # When disabled, hp's arena_only_adds are moot (the cps got
        # removed). Return empty so the caller's auto-extend is a no-op.
        'arena_only_adds': set(),
        'caliber_adds': set(),
        'strict_adds': set(),
        'exclude_target_adds': set(),
        'n_tag_removed': n_tag_removed,
        'n_variant_removed': n_variant_removed,
    }
