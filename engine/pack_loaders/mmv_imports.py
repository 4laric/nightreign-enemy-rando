"""mmv_imports loader.

mmv_imports.json (More Map Variations — nexusmods.com/eldenring
nightreign/mods/578) ships cross-game boss imports as a true mod: NR
chrs whose chrbnd/anibnd files are present in the mod's payload AND
whose NpcParam rows are live in the modified regulation. Unlike
heritage_pack (toggle-only) and er_heritage (synthetic tag-only),
MMV brings real content.

Merge semantics: AUTHORITATIVE override.
  - tags: every cp in the pack's `tags` REPLACES any existing entry
    for that cp. Opposite of er_heritage's vanilla-wins — MMV's chr at
    a given cp is conceptually a different entity than NR's vanilla
    chr at that ID, so MMV's tag metadata wins.
  - variants: appended if their npc_param_id isn't already in the
    roster. De-dup at the variant level, not the c_prefix level.
  - caliber / strict-NB tier sets: cps tagged tier in {night_boss,
    nightlord} are contributed to caliber; tier='nightlord' alone
    feeds strict.
  - blacklist: three sub-categories from `blacklist_when_active`
    (ctd_unidentified, dlc_assets_missing_in_mmv, ai_broken) are
    unioned into a single blacklist set destined for
    V3_EXCLUDE_TARGET_PREFIXES.
  - cross-engine guard: REMOVED v0.26.x. The historical DS1/BB auto-ban
    via origin_game was deprecated to a no-op in v0.25.0-patch3 (MMV
    ships fully-working cross-engine chrbnds; the v0.23.39 Manus /
    v0.23.72 c1260 CTDs that motivated it were fixed upstream) and is
    now fully excised — constants, guard loop, and the
    `cross_engine_bans` / `cross_engine_origins_seen` stats keys are all
    gone. origin_game is still carried on tags for other consumers
    (heritage-pack DLC-ownership warnings, the Pools & Caps panel); MMV
    just no longer bans on it.
  - mount-component guard: cps with tier='mount_component' and not
    already in blacklist get added too. Auto-catches orphan rider+mount
    pairs.

WHY THIS FUNCTION RETURNS CONTRIBUTIONS INSTEAD OF MUTATING GATE SETS
DIRECTLY
--------------------------------------------------------------------
heritage_pack and er_heritage both confined their mutation to tags +
roster. MMV would need to also mutate V3_NIGHT_BOSS_CALIBER_TARGETS,
V3_NIGHT_BOSS_STRICT_TARGETS, and V3_EXCLUDE_TARGET_PREFIXES — three
extra parameters via reference. Cleaner: this function MUTATES only
tags + roster, RETURNS the contribution sets in stats, and lets the
caller decide where to apply them. This keeps the function pure-ish
(no surprise side effects on caller globals it doesn't see) and aligns
with the Phase 11 plan to have the post-loader auto-extend block
consume each loader's stats rather than reaching into raw pack dicts.
"""
from typing import Any, Dict


def apply_mmv_imports(pack_data: Dict[str, Any], *,
                      tags: Dict[str, Any],
                      roster: Dict[str, Any]) -> Dict[str, Any]:
    """Apply mmv_imports.json semantics to tags + roster, return
    contributions for the caller to fold into engine gate sets.

    Args:
        pack_data: The loaded mmv_imports.json dict, AFTER any
            snapshot overrides have been applied. Caller owns I/O +
            snapshot-override application.
        tags: The tags dict to mutate in place. MMV tags override
            any existing entries (authoritative).
        roster: The roster dict. `roster['all_variants']` is extended
            with MMV variants whose npc_param_id isn't already present.

    Returns:
        Stats dict — the caller folds these into engine gate sets.
            {
                'enabled': bool,
                'n_tags_added': int,
                'n_variants_added': int,
                'caliber_adds': set[str],      # → V3_NIGHT_BOSS_CALIBER_TARGETS
                'strict_adds': set[str],       # → V3_NIGHT_BOSS_STRICT_TARGETS
                'blacklist': set[str],         # union of 3 sub-categories
                'blacklist_breakdown': dict,   # the 3 sub-categories
                'mount_component_bans': set[str],
            }
        Caller unions blacklist + mount_component_bans into
        V3_EXCLUDE_TARGET_PREFIXES.

    Raises:
        Standard dict/list-access errors on malformed pack_data.
        Caller wraps in try/except for graceful degradation.

    Performance note:
        Variant de-dup uses a precomputed `existing_npc_ids` set
        (O(pack_variants + all_variants)) instead of the original's
        per-variant linear scan (O(pack_variants × all_variants)).
        Behaviorally equivalent for well-formed input. Tag iterations
        remain two-pass to match the original semantic structure
        (mount-component guard depends on blacklist).
    """
    enabled = bool(pack_data.get('_meta', {}).get('enabled', True))
    if not enabled:
        return _empty_stats(enabled=False)

    pack_tags = pack_data.get('tags', {})

    # ---- Tag merge (authoritative override) + tier-set collection ----
    n_tags_added = 0
    caliber_adds = set()
    strict_adds = set()
    arena_only_adds = set()
    for cp, t in pack_tags.items():
        # Authoritative: replaces any pre-existing tag at this cp.
        tags[cp] = t
        n_tags_added += 1
        tier = t.get('tier')
        if tier in ('night_boss', 'nightlord'):
            caliber_adds.add(cp)
        if tier == 'nightlord':
            strict_adds.add(cp)
        if t.get('expects_boss_arena'):
            arena_only_adds.add(cp)

    # ---- Variant merge (de-dup at npc_param_id granularity) ----
    n_variants_added = 0
    variants_list = roster.setdefault('all_variants', [])
    existing_npc_ids = {rv.get('npc_param_id') for rv in variants_list}
    for v in pack_data.get('variants', []):
        nid = v.get('npc_param_id')
        if nid in existing_npc_ids:
            continue
        variants_list.append(v)
        existing_npc_ids.add(nid)
        n_variants_added += 1

    # ---- Blacklist (3 sub-categories) ----
    bl = pack_data.get('blacklist_when_active', {})
    blacklist_ctd = set(bl.get('ctd_unidentified', []))
    blacklist_dlc = set(bl.get('dlc_assets_missing_in_mmv', []))
    blacklist_ai = set(bl.get('ai_broken', []))
    blacklist = blacklist_ctd | blacklist_dlc | blacklist_ai

    # ---- Mount-component guard (tier=='mount_component') ----
    # Order dependency: depends on blacklist (avoids double-counting
    # cps already excluded there).
    mount_component_bans = set()
    for cp, t in pack_tags.items():
        if (t.get('tier') == 'mount_component'
                and cp not in blacklist):
            mount_component_bans.add(cp)

    return {
        'enabled': True,
        'n_tags_added': n_tags_added,
        'n_variants_added': n_variants_added,
        'caliber_adds': caliber_adds,
        'strict_adds': strict_adds,
        'arena_only_adds': arena_only_adds,
        'blacklist': blacklist,
        'blacklist_breakdown': {
            'ctd_unidentified': blacklist_ctd,
            'dlc_assets_missing_in_mmv': blacklist_dlc,
            'ai_broken': blacklist_ai,
        },
        'mount_component_bans': mount_component_bans,
        # Phase 12: standardized exclude_target_adds — union of the
        # two exclusion sources (blacklist, mount-component guard).
        # Callers fold this into V3_EXCLUDE_TARGET_PREFIXES. The
        # component sets are kept separately above for per-loader
        # logging. (v0.26.x: cross-engine guard removed — see module
        # docstring.)
        'exclude_target_adds': blacklist | mount_component_bans,
    }


def _empty_stats(*, enabled: bool) -> Dict[str, Any]:
    """Empty-stats shape used by the disabled path.

    Same keys as the enabled return value so callers can `.get()`
    without branching on `enabled` first.
    """
    return {
        'enabled': enabled,
        'n_tags_added': 0,
        'n_variants_added': 0,
        'caliber_adds': set(),
        'strict_adds': set(),
        'arena_only_adds': set(),
        'blacklist': set(),
        'blacklist_breakdown': {
            'ctd_unidentified': set(),
            'dlc_assets_missing_in_mmv': set(),
            'ai_broken': set(),
        },
        'mount_component_bans': set(),
        'exclude_target_adds': set(),
    }
