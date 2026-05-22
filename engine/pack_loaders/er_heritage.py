"""er_heritage_imports loader.

er_heritage_imports.json carries c2xxx ER NB-tier bosses whose chr
files ship in NR but have NO NpcParam rows in vanilla NR's regulation.
The pack authors synthetic tag entries + variants for those cps so the
randomizer can place them as targets.

Merge semantics: VANILLA-WINS.
  - tags: a cp from the pack is added only if it's NOT already in the
    engine's tags dict. Existing entries (from base nr_enemy_tags.json,
    heritage_pack, post_dlc_dump auto-detect) take precedence.
  - variants_per_prefix: a cp's variant list is added only if NO
    variants for that c_prefix already exist in the roster. Different
    cardinality from the tags rule — partial-match is treated as
    "vanilla covers this" and the pack contribution is skipped wholesale.

When the pack is disabled (via on-disk _meta.enabled=false OR via a
snapshot pack_override), this loader is a no-op — nothing is added.
Unlike heritage_pack, disabling here doesn't REMOVE existing data
(the er_heritage cps wouldn't be in the base data anyway, by design).

The cps loaded here get `_source='er_heritage_v1'`, which puts them
in V3_TARGET_ONLY_SOURCES — they're picked as swap targets but
never swapped OUT (their zero MSB placements stay vanilla).
"""
from typing import Any, Dict


def apply_er_heritage(pack_data: Dict[str, Any], *,
                      tags: Dict[str, Any],
                      roster: Dict[str, Any]) -> Dict[str, Any]:
    """Apply er_heritage_imports.json semantics to tags + roster.

    Args:
        pack_data: The loaded er_heritage_imports.json dict, AFTER any
            snapshot overrides have been applied to _meta. Caller owns
            file I/O + snapshot-override application.
        tags: The tags dict to mutate in place. Pack contributions are
            added with vanilla-wins precedence.
        roster: The roster dict. `roster['all_variants']` is extended
            with pack variants for cps that don't already have any.

    Returns:
        Stats dict:
            {
                'enabled': bool,
                'n_tags_added': int,
                'n_variants_added': int,
            }

    Raises:
        Standard dict/list-access errors on malformed pack_data.
        Caller wraps in try/except for graceful degradation.

    Idempotency:
        Calling this twice with the same pack_data + tags + roster
        produces the same final state. (First call adds the cps not
        already present; second call sees they're now all present and
        adds 0 more.) Important for the behavior lock — load_data
        invariants need to hold whether or not state was previously
        mutated.

    Performance note:
        The original inline code computed `existing = [v for v in
        all_variants if v['c_prefix'] == cp]` inside the per-cp loop —
        O(pack_cps × all_variants). This version precomputes the set
        of existing c_prefixes once before the loop — O(pack_cps +
        all_variants). Behaviorally equivalent for well-formed input.
    """
    enabled = bool(pack_data.get('_meta', {}).get('enabled', True))
    if not enabled:
        return {
            'enabled': False,
            'n_tags_added': 0,
            'n_variants_added': 0,
            # Phase 12: standardized loader-stats shape. er_heritage
            # doesn't contribute to tier sets or exclusion sets, but
            # returns the keys uniformly so the post-loader fold can
            # iterate without per-loader branching.
            'arena_only_adds': set(),
            'caliber_adds': set(),
            'strict_adds': set(),
            'exclude_target_adds': set(),
        }

    # ---- Tag merge (vanilla-wins) + arena_only contribution ----
    n_tags_added = 0
    arena_only_adds = set()
    for cp, t in pack_data.get('tags', {}).items():
        if cp in tags:
            continue
        tags[cp] = t
        n_tags_added += 1
        # Phase 12: collect expects_boss_arena cps for the post-loader
        # auto-extend block (matches the heritage_pack + mmv behavior).
        if isinstance(t, dict) and t.get('expects_boss_arena'):
            arena_only_adds.add(cp)

    # ---- Variant merge (vanilla-wins at c_prefix granularity) ----
    # If ANY variant with this c_prefix exists, the pack's variants for
    # that cp are skipped wholesale. Matches the original semantics.
    n_variants_added = 0
    variants_list = roster.setdefault('all_variants', [])
    existing_cps = {v['c_prefix'] for v in variants_list
                    if 'c_prefix' in v}
    for cp, vs in pack_data.get('variants_per_prefix', {}).items():
        if cp in existing_cps:
            continue
        variants_list.extend(vs)
        n_variants_added += len(vs)
        # Track that we've now contributed for this cp so a degenerate
        # pack with the same cp listed twice (shouldn't happen, but
        # defensively) doesn't double-add.
        existing_cps.add(cp)

    return {
        'enabled': True,
        'n_tags_added': n_tags_added,
        'n_variants_added': n_variants_added,
        'arena_only_adds': arena_only_adds,
        # er_heritage doesn't push to tier sets (entries don't carry
        # tier=nightlord/night_boss in current data) or exclusion sets.
        'caliber_adds': set(),
        'strict_adds': set(),
        'exclude_target_adds': set(),
    }
