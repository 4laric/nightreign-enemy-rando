"""Data loader (extracted from oops_v3.py).

WHAT THIS IS
------------
`load_data` is the workhorse called once at engine startup. It reads:
  - data/placement_budget.json (via engine.placement_budget loader,
    which writes ~20 V3_* caps/exclude/etc. sets)
  - data/nr_enemy_tags.json (the tag database)
  - data/nr_enemy_roster.json (the roster)
  - data/nr_slot_inventory.json (optional slot tile-position cache)
  - every registered pack loader in _PACK_LOADERS (er_heritage,
    heritage_pack, mmv_imports, ...)

It also computes a handful of derived sets that aren't pack-driven:
the multiplayer-safe blocklist, mount/rider/SOTE prefix tag-derived
sets, shifting-earth / starting-encampment auto-additions to the
arena-only target set, the dead-think NPC-id avoid set, and the
POI cluster cache.

Returns (roster, tags).

NS-WRITE PATTERN
----------------
The original used 10 `global` declarations + 15 assignment sites
to publish derived state to oops_v3 module globals. After
extraction:
  1. Binding header pulls the 10 names from ns into locals (so
     reads run unchanged — LOAD_FAST opcodes).
  2. Every assignment to a previously-global name is followed by
     a `ns['X'] = X` flush so module state stays in sync with the
     local rebind. Pack loaders invoked during load_data look up
     V3_* in their own module globals (= ns), so the flush makes
     live state visible to them.

The shim in oops_v3.load_data passes `globals()` for ns; production
callers see exactly the same module-state mutation behavior as
pre-extraction.
"""
from __future__ import annotations

import json
import os


def load_data(ns):
    """Load data and populate the caller's V3_* state."""
    # Bind globally-declared names from ns into locals. The
    # original used `global X` to make assignments mutate
    # module state; after extraction we use `ns['X'] = X`
    # flushes at every write site (see flush comments below)
    # so the caller namespace stays in sync. Pack loaders
    # and other helpers invoked during load_data read live
    # state from their own module globals — the flush is
    # what makes that work.
    V3_EXCLUDE_TARGET_PREFIXES = ns['V3_EXCLUDE_TARGET_PREFIXES']
    V3_NIGHT_BOSS_CALIBER_TARGETS = ns['V3_NIGHT_BOSS_CALIBER_TARGETS']
    V3_NIGHT_BOSS_STRICT_TARGETS = ns['V3_NIGHT_BOSS_STRICT_TARGETS']
    V3_MP_SAFE_BLOCKLIST = ns['V3_MP_SAFE_BLOCKLIST']
    V3_ARENA_ONLY_TARGETS = ns['V3_ARENA_ONLY_TARGETS']
    V3_AVOID_VARIANT_NPC_IDS = ns['V3_AVOID_VARIANT_NPC_IDS']
    V3_SOTE_PREFIXES = ns['V3_SOTE_PREFIXES']
    V3_RIDER_PREFIXES = ns['V3_RIDER_PREFIXES']
    V3_MOUNT_PREFIXES = ns['V3_MOUNT_PREFIXES']
    _V3_SLOT_POI_CLUSTERS = ns['_V3_SLOT_POI_CLUSTERS']
    # Read-side V3_* state (these aren't mutated by load_data; the
    # placement_budget loader and pack loaders populate them earlier
    # in load_data's flow, and the rest of the function reads them):
    V3_ARENA_ONLY_FORCE_LIFT = ns['V3_ARENA_ONLY_FORCE_LIFT']
    V3_DEDICATED_ARENA_BOSS_CHRS = ns['V3_DEDICATED_ARENA_BOSS_CHRS']
    V3_EXCLUDE_PREFIXES = ns['V3_EXCLUDE_PREFIXES']
    V3_GHOST_EXCLUDE_TARGET_PREFIXES = ns['V3_GHOST_EXCLUDE_TARGET_PREFIXES']
    V3_POI_SCOPE_RECYCLE = ns['V3_POI_SCOPE_RECYCLE']
    V3_RESERVATION_FLOORS = ns['V3_RESERVATION_FLOORS']
    V3_SOTE_MODE = ns['V3_SOTE_MODE']
    V3_UNIQUE_TARGET_CAPS = ns['V3_UNIQUE_TARGET_CAPS']
    V3_VANILLA_NR_SOURCES = ns['V3_VANILLA_NR_SOURCES']
    # Module-level diagnostic / probe constants:
    OOPS_ALL_NB_MARKER_SCOPE = ns['OOPS_ALL_NB_MARKER_SCOPE']
    OOPS_ALL_NB_TARGET_CP = ns['OOPS_ALL_NB_TARGET_CP']
    PROBE_TARGET_VARIANT = ns['PROBE_TARGET_VARIANT']
    # Pack-loader registry and helper functions defined in oops_v3:
    _PACK_LOADERS = ns['_PACK_LOADERS']
    _apply_snapshot_overrides_to_pack = ns['_apply_snapshot_overrides_to_pack']
    _assemble_exclude_target_prefixes = ns['_assemble_exclude_target_prefixes']
    _data_path = ns['_data_path']
    build_per_prefix_data = ns['build_per_prefix_data']

    # v0.23.34: globals declared at function top so all later assignments work,
    # even those in nested conditional blocks earlier in the function.
    # (global decl removed — engine version writes to ns instead)

    # Resolve JSON paths relative to this script's location, not cwd —
    # so it works regardless of where the GUI / shell launches Python from.
    # v0.23.71: routes through _data_path() so JSONs in data/ resolve
    # cleanly while pre-v0.23.71 layouts (JSONs at project root) still
    # work via the fallback. See _data_path() docstring.
    here = os.path.dirname(os.path.abspath(__file__))
    with open(_data_path('nr_enemy_roster.json'), encoding='utf-8') as f: roster = json.load(f)
    with open(_data_path('nr_enemy_tags.json'), encoding='utf-8') as f: tags = json.load(f)

    # v0.24.22 (Phase 12): registry-driven pack-loader dispatch.
    #
    # The three nearly-identical inline loader blocks (heritage_pack,
    # er_heritage, mmv) collapsed into a single loop over _PACK_LOADERS
    # at module top. Each loader returns a uniform stats dict (see
    # engine/pack_loaders/ docstrings); per-loader log formatting goes
    # through the spec's log_fn; gate-set folding happens once at the
    # end. Same observable behavior as the pre-Phase-12 inline layout —
    # validated by the load_data lock fixture across all three snapshots.
    #
    # The `loader_stats` dict accumulates each loader's return value
    # keyed by filename. Downstream blocks (the auto-extend block at
    # line ~2575 and the PROBE_TARGET_VARIANT block) consume this via
    # `loader_stats.get(filename, {})`. Three named convenience aliases
    # (hp_stats / er_stats / mmv_stats) are also bound for backwards
    # readability of the consumer sites.
    loader_stats: dict = {}
    for spec in _PACK_LOADERS:
        path = _data_path(spec.filename)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                pack = json.load(f)
            _apply_snapshot_overrides_to_pack(pack, spec.filename)
            stats = spec.apply_fn(pack, tags=tags, roster=roster)
            spec.log_fn(stats)
            loader_stats[spec.filename] = stats
        except Exception as e:
            print(f"{spec.filename}: load FAILED ({e!r}) — "
                  f"proceeding without it.")

    # Named aliases for downstream consumers. Default to empty-shape
    # dicts when a loader didn't run (file absent or load failed) so
    # consumers can `.get('arena_only_adds', set())` uniformly.
    _empty_loader_stats = {
        'arena_only_adds': set(),
        'caliber_adds': set(),
        'strict_adds': set(),
        'exclude_target_adds': set(),
    }
    hp_stats = loader_stats.get('heritage_pack.json', _empty_loader_stats)
    er_stats = loader_stats.get('er_heritage_imports.json',
                                _empty_loader_stats)
    mmv_stats = loader_stats.get('mmv_imports.json', _empty_loader_stats)

    # Fold per-loader contributions into the engine's gate sets. This
    # used to be inline in the mmv block (since mmv was the only loader
    # that contributed); now any loader can contribute and the fold
    # iterates uniformly.
    # Fold per-loader caliber contributions into the NB caliber gate.
    # (v0.26.x: pack-loader exclude_target_adds are no longer folded here
    # -- they are merged by _assemble_exclude_target_prefixes() below, the
    # single assembly point for V3_EXCLUDE_TARGET_PREFIXES. NB-strict gate
    # removed; strict_adds no longer collected.)
    _all_caliber: set = set()
    for stats in loader_stats.values():
        _all_caliber |= stats.get('caliber_adds', set())
    if _all_caliber:
        V3_NIGHT_BOSS_CALIBER_TARGETS = (
            V3_NIGHT_BOSS_CALIBER_TARGETS | _all_caliber)
        ns['V3_NIGHT_BOSS_CALIBER_TARGETS'] = V3_NIGHT_BOSS_CALIBER_TARGETS  # flush to caller namespace

    # v0.23.72-late: manual_promotions.json mechanism removed. Historically
    # this file held synthetic tag + variant entries for scripted-spawn
    # c-prefixes (Ancestor Spirit c4670, Grafted Scion c4690, Nameless King
    # c7900, Storm King c7910) that had no MSB Parts. As of this engine
    # version, all four entries are present directly in nr_enemy_tags.json
    # and nr_enemy_roster.json with `_source: 'script_spawn'` to gate them
    # as target-only via V3_TARGET_ONLY_SOURCES. The manual_promotions
    # "skip if exists" merge semantics meant the pack was a no-op for
    # c-prefixes auto-detected by post_dlc_dump, so consolidating into the
    # canonical data files removes a layer of confusion without changing
    # the effective pool. See CHANGELOG for the v0.23.72-late entry.

    # v0.23.72-late: vanilla_promotions_v1.json mechanism removed. Same
    # retirement story as manual_promotions: post_dlc_dump now auto-detects
    # every cp the pack covered (c3360, c3370, c4190, c4192, c4441, c4442,
    # c4502, c4641), so the "skip if exists" merge semantics turned the
    # pack into a no-op for tag data. The only remaining value was
    # supplying variant_names for 4 cps whose canonical roster variants
    # arrived from post_dlc_dump with empty names (c4192/c4441/c4442/c4502
    # were sitting in the v0.23.71 auto-exclude as a result). That data
    # has been migrated into nr_enemy_roster.json directly with the
    # variant naming aligned to the canonical tag's name (e.g. c4502 was
    # "Flying Dragon (Unscaled, Field Boss)" in vp but is now
    # "Decaying Ekzykes-class Dragon (Field Boss)" matching the canonical
    # post_dlc_dump-detected name). c4641 deliberately NOT migrated — vp
    # called it "Tree Spirit (Unscaled, ...)" but post_dlc_dump correctly
    # identifies it as "Weapon-Bequeathed Harmonia (Everdark Worm)", which
    # is the better source of truth.


    # v0.20.18 → v0.26.x: V3_TAG_OVERRIDES apply loop REMOVED. The
    # original 45-entry tier-override dict was flattened in v0.26.x —
    # 33 entries into data/nr_enemy_tags.json directly, 7 entries into
    # data/mmv_imports.json's `tags` section directly, 5 no-op entries
    # dropped. Tier is now sourced from the per-pack JSON manifests in
    # a single pass via the normal pack-loader merge, no
    # post-application override step needed.

    # v0.24.20: derive V3_MP_SAFE_BLOCKLIST from the merged tags dict, now
    # that every pack loader has run. See the module-level comment block
    # near V3_VANILLA_NR_SOURCES for rationale. Strict policy: any c-prefix
    # whose `_source` is not in V3_VANILLA_NR_SOURCES — including unsourced
    # entries — gets blocked when multiplayer_safe is ON.
    #
    # Diagnostic print breaks the blocked set down by `_source` so the
    # next leak (e.g. a future import pack landing tags with a brand-new
    # `_source` string) shows up immediately in the load log rather than
    # waiting for a coop-CTD playtest report.
    # (global decl removed — engine version writes to ns instead)
    _mp_blocked = set()
    _mp_blocked_by_source = {}
    for cp, t in tags.items():
        src = t.get('_source')  # None for unsourced — treated as non-vanilla
        if src not in V3_VANILLA_NR_SOURCES:
            _mp_blocked.add(cp)
            _mp_blocked_by_source.setdefault(src or '<no _source>', []).append(cp)
    V3_MP_SAFE_BLOCKLIST = _mp_blocked
    ns['V3_MP_SAFE_BLOCKLIST'] = V3_MP_SAFE_BLOCKLIST  # flush to caller namespace
    _src_summary = ', '.join(
        f"{src}={len(cps)}" for src, cps in sorted(_mp_blocked_by_source.items()))
    print(f"V3_MP_SAFE_BLOCKLIST: {len(_mp_blocked)} c-prefixes "
          f"(vanilla sources allowed: {sorted(V3_VANILLA_NR_SOURCES)}; "
          f"blocked by source: {_src_summary})")

    # v0.23.72: auto-extend V3_ARENA_ONLY_TARGETS from `expects_boss_arena`
    # tags. Discovered during user playtest seed 35300 (Sentient Pest): the
    # aerial-skip rip exposed a gap where the `expects_boss_arena` flag is
    # only used as a +10 preference score at line ~6391, not as a hard gate.
    # Result: 12 nightlord-tier MMV chrs landed at non-arena slots in one
    # seed (Rellana, Malenia, Rennala, Maliketh, etc.), 5 of them clustered
    # in m34_10 — cumulative giga-class asset load on cell unload caused a
    # tunnel-exit CTD.
    #
    # The manual V3_ARENA_ONLY_TARGETS set above covers 5 hand-picked
    # giga-class chrs but doesn't track the ~19 MMV nightlord-tier imports.
    # Auto-extension closes the gap: any chr tagged expects_boss_arena=true
    # in heritage_pack or mmv_imports gets added to V3_ARENA_ONLY_TARGETS at
    # load time, so the line ~6881 pool subtraction filters them out of
    # non-arena slot candidate pools.
    # (global decl removed — engine version writes to ns instead)
    # v0.23.72: auto-extend V3_ARENA_ONLY_TARGETS from `expects_boss_arena`
    # tags across all loaded packs. This runs AFTER every loader so we
    # see the merged tags dict + any pack-side overrides.
    #
    # v0.24.22 (Phase 11): the original implementation reached into the
    # raw hp/mmv pack dicts via `try: except NameError:`, which was a
    # fragile dependency on those variables surviving in load_data's
    # local scope across hundreds of lines. Now each loader returns
    # `arena_only_adds` in its stats dict and this block consumes the
    # stats — clean, explicit, no scope dependency. See the loader
    # docstrings in engine/pack_loaders/ for the contract.
    _arena_auto_adds = set()
    # v0.23.74: also iterate the canonical nr_enemy_tags.json dict,
    # filtered to _source=script_spawn. The original v0.23.72 implementation
    # below only saw mmv and heritage_pack manifests, missing the 8
    # script_spawn DS-heritage bosses tagged expects_boss_arena=True in
    # nr_enemy_tags.json (c4670 Ancestor Spirit, c7700 Gaping Dragon, c7710
    # Centipede Demon, c7800 Freja, c7820 Smelter, c7900 Nameless, c7910
    # Storm King, c7920 Dancer). Result: those chrs leaked into overworld
    # tiles despite the authored arena-only intent — seed 443972 placed 2
    # Gaping Dragons at m60_43_xx and a quad-Storm-King run across m46
    # Evergaol slots, causing the east-approach CTD.
    #
    # Filter to _source=script_spawn rather than iterating tags wholesale
    # because nr_enemy_tags.json's expects_boss_arena is a SOFT preference
    # for vanilla chrs (used as a +10 placement score, not a hard gate —
    # see line ~6391). Promoting all 37 expects_boss_arena=True entries
    # would retroactively arena-lock 25+ vanilla chrs (c2130 Morgott,
    # c2500 Crucible Knight, c3050 Commander, etc.) that have been
    # working fine at field slots since v0.20.0. The script_spawn subset
    # is different: those chrs genuinely need EMEVD scaffolding and the
    # tag was authored as a hard constraint when the v0.23.72-late
    # consolidation moved them out of manual_promotions.json.
    # Arena-only auto-adds for the dedicated-arena boss chrs. These are
    # _source='nr_placed' (reclassified v0.26.x) but carry a real
    # arena-only constraint (dedicated arena MSB residents — overworld
    # placement → CTD), tracked explicitly in V3_DEDICATED_ARENA_BOSS_CHRS.
    # (A legacy `_source == 'script_spawn'` loop used to live here too; it
    # was removed in v0.27.x because no chr carries that _source anymore.)
    for cp in V3_DEDICATED_ARENA_BOSS_CHRS:
        if cp not in V3_ARENA_ONLY_TARGETS:
            _arena_auto_adds.add(cp)
    # v0.24.22 (Phase 11): consume pack-loader stats instead of reaching
    # into raw pack dicts via `try: except NameError:`. Each loader
    # returns its expects_boss_arena cps in stats['arena_only_adds'] —
    # safe to access via .get() with a default since the stats dicts
    # were initialized empty at the top of load_data.
    _arena_auto_adds |= (
        mmv_stats.get('arena_only_adds', set())
        - V3_ARENA_ONLY_TARGETS)
    _arena_auto_adds |= (
        hp_stats.get('arena_only_adds', set())
        - V3_ARENA_ONLY_TARGETS)
    if _arena_auto_adds:
        V3_ARENA_ONLY_TARGETS = V3_ARENA_ONLY_TARGETS | _arena_auto_adds
        ns['V3_ARENA_ONLY_TARGETS'] = V3_ARENA_ONLY_TARGETS  # flush to caller namespace
        print(f"V3_ARENA_ONLY_TARGETS: auto-extended +{len(_arena_auto_adds)} "
              f"from expects_boss_arena tags "
              f"({sorted(_arena_auto_adds)})")

    # v0.26.x: lift arena_only for M-size chrs. Sim
    # (dev/sim_reservation_health.py) surfaced that several NB-caliber
    # MMV imports (Midra, Romina, etc.) score 0/5136 slots in the
    # reservation pre-pass because of the combined arena_only +
    # NB-strict + size constraints. Arena-only was inherited via
    # expects_boss_arena=True in MMV pack tags, but for M-size chrs
    # the constraint is unnecessary — they don't have the geometric
    # footprint problems that motivated arena_only for XL+ chrs
    # (sunken trolls, ground-clipping dragons).
    #
    # v0.27.28: was restricted to M-size AND anim_class=='humanoid'; now
    # lifts every M-size chr regardless of rig. anim_class is expunged, and
    # per Alaric the rig distinction was never load-bearing here — an M
    # enemy fits an M slot whether it's humanoid, quadruped, or anything
    # else. Their slot pool widens and they can reserve at regular NB-marker
    # slots.
    _m_size_lift = set()
    for cp in list(V3_ARENA_ONLY_TARGETS):
        t = tags.get(cp, {})
        if t.get('size_class') == 'M':
            _m_size_lift.add(cp)
    if _m_size_lift:
        V3_ARENA_ONLY_TARGETS = V3_ARENA_ONLY_TARGETS - _m_size_lift
        ns['V3_ARENA_ONLY_TARGETS'] = V3_ARENA_ONLY_TARGETS  # flush to caller namespace
        print(f"V3_ARENA_ONLY_TARGETS: lifted -{len(_m_size_lift)} "
              f"M-size chrs ({sorted(_m_size_lift)})")

    # v0.27.2: explicit arena_only lift for the five MMV nightlord imports
    # (see V3_ARENA_ONLY_FORCE_LIFT docstring). 98-seed sim (2026-05-26)
    # showed them at 0 placements — arena_only + v0.27.1 whole-MSB NB-arena
    # preservation left them with no eligible slots. Alaric direction:
    # pool gap, lift it. Runs last so it overrides the expects_boss_arena
    # auto-extend that put them in the set.
    _force_lift = V3_ARENA_ONLY_TARGETS & V3_ARENA_ONLY_FORCE_LIFT
    if _force_lift:
        V3_ARENA_ONLY_TARGETS = V3_ARENA_ONLY_TARGETS - _force_lift
        ns['V3_ARENA_ONLY_TARGETS'] = V3_ARENA_ONLY_TARGETS  # flush to caller namespace
        print(f"V3_ARENA_ONLY_TARGETS: force-lifted -{len(_force_lift)} "
              f"MMV nightlord imports ({sorted(_force_lift)})")

    # v0.23.72: PROBE_TARGET_VARIANT application. After all variant data
    # is loaded (heritage + MMV + post_dlc_dump), if PROBE_TARGET_VARIANT
    # is set, narrow V3_AVOID_VARIANT_NPC_IDS to leave ONLY the target
    # variant eligible within its c-prefix. See the constant definition
    # near line 1290 for workflow notes.
    # (global decl removed — engine version writes to ns instead)
    if PROBE_TARGET_VARIANT is not None:
        probe_cp, probe_npc = PROBE_TARGET_VARIANT
        # v0.24.22 (Phase 11): iterate the merged roster directly
        # instead of reaching back into raw pack dicts via `try: except
        # NameError:`. Every loaded variant (vanilla NR + heritage + ER
        # heritage + MMV + post_dlc_dump) is in roster['all_variants']
        # by this point, so the merged view is the right place to look.
        # This is slightly broader than the pre-Phase-11 behavior (which
        # only considered mmv + hp variant lists) — variants contributed
        # by other sources for the probe cp now also get covered by the
        # ban-others logic, which is closer to the intent of "leave only
        # this variant eligible". Block is guarded by `PROBE_TARGET_VARIANT
        # is not None` which is False in production, so this scope change
        # doesn't affect normal load_data output.
        probe_cp_variants = set()
        for v in roster.get('all_variants', []):
            if isinstance(v, dict) and v.get('c_prefix') == probe_cp:
                npc = v.get('npc_param_id')
                if npc is not None:
                    probe_cp_variants.add(npc)
        if probe_npc not in probe_cp_variants:
            print(f"PROBE_TARGET_VARIANT: WARNING — target npc {probe_npc} "
                  f"not found in c-prefix {probe_cp} variant pool "
                  f"({sorted(probe_cp_variants)[:10]}{'…' if len(probe_cp_variants) > 10 else ''}). "
                  f"Probe will fall back to vanilla. Check the tuple.")
        else:
            # Unban the target, ban every other variant of the same
            # c-prefix. This guarantees pick_variant_for_tier can only
            # land on the target within this c-prefix.
            others = probe_cp_variants - {probe_npc}
            n_newly_banned = len(others - V3_AVOID_VARIANT_NPC_IDS)
            n_unbanned = 1 if probe_npc in V3_AVOID_VARIANT_NPC_IDS else 0
            V3_AVOID_VARIANT_NPC_IDS = (
                (V3_AVOID_VARIANT_NPC_IDS - {probe_npc}) | others)
            ns['V3_AVOID_VARIANT_NPC_IDS'] = V3_AVOID_VARIANT_NPC_IDS  # flush to caller namespace
            print(f"PROBE_TARGET_VARIANT: active — {probe_cp} npc={probe_npc} "
                  f"is the only eligible variant of {probe_cp} "
                  f"(banned {n_newly_banned} sibling variants, "
                  f"unbanned target: {bool(n_unbanned)}). "
                  f"Pair with OOPS_ALL_NB_TARGET_CP='{probe_cp}' via the GUI.")

    # ---- Single assembly point for V3_EXCLUDE_TARGET_PREFIXES (v0.26.x) ----
    # The MMV blacklist fold + the three computed unions (cinematic /
    # all-empty-variant / tag-but-no-variant) were previously merged by |=
    # mutations scattered across ~300 lines of load_data(). They now all
    # land in one function, called once here with tags + roster + loader
    # stats finalized. See _assemble_exclude_target_prefixes() docstring.
    V3_EXCLUDE_TARGET_PREFIXES = _assemble_exclude_target_prefixes(
        tags, roster, loader_stats)
    ns['V3_EXCLUDE_TARGET_PREFIXES'] = V3_EXCLUDE_TARGET_PREFIXES  # flush to caller namespace

    # v0.23.34: auto-extend NB caliber set with tier-tagged boss-tier c-prefixes.
    # The caliber set is otherwise populated from manifests (heritage_pack etc).
    # Without this, post-DLC chrs tagged tier='night_boss' or 'nightlord' would
    # never appear at NB-marker slots even though they're proper boss-caliber.
    # Strict set gets 'nightlord' tier specifically (Nightlord-caliber gates).
    _boss_tier_cps = {cp for cp, t in tags.items()
                      if isinstance(t, dict)
                      and t.get('tier') in ('night_boss', 'nightlord')
                      and cp not in V3_EXCLUDE_TARGET_PREFIXES}
    # v0.26.x: nightlord-tier auto-extend of NB-strict removed alongside
    # the gate itself. Nightlord-tier chrs (DLC remembrance bosses
    # etc.) are now placeable at any compatible slot per their size /
    # anim / arena tags, not gated by the variant-name string filter.
    _cal_added = len(_boss_tier_cps - V3_NIGHT_BOSS_CALIBER_TARGETS)
    V3_NIGHT_BOSS_CALIBER_TARGETS = V3_NIGHT_BOSS_CALIBER_TARGETS | _boss_tier_cps
    ns['V3_NIGHT_BOSS_CALIBER_TARGETS'] = V3_NIGHT_BOSS_CALIBER_TARGETS  # flush to caller namespace
    if _cal_added:
        print(f"v0.23.34: caliber+={_cal_added} (now {len(V3_NIGHT_BOSS_CALIBER_TARGETS)})")

    if OOPS_ALL_NB_TARGET_CP:
        cp_name = tags.get(OOPS_ALL_NB_TARGET_CP, {}).get('name', '?')
        marker_set = {
            'strict': 'strict (Night Boss only, ~22 slots)',
            'broad':  'broad (NB/Field/Castle/Fort/Ruins/Crater/Noklateo/Remembrance, ~39 slots)',
            'extended': 'extended (broad + Castle interior + Castle Basement + Encampments + Cathedrals + Mountaintop + Underground Forts + Group Bosses + bare (Boss) Nightlord forms)',
        }.get(OOPS_ALL_NB_MARKER_SCOPE, OOPS_ALL_NB_MARKER_SCOPE)
        print("=" * 64)
        print(f"OOPS_ALL_NB_TARGET_CP = {OOPS_ALL_NB_TARGET_CP!r}  ({cp_name})")
        print(f"  - Marker scope: {OOPS_ALL_NB_MARKER_SCOPE!r} — {marker_set}")
        print(f"  - Every matching slot will be forced to {OOPS_ALL_NB_TARGET_CP}")
        print(f"  - Non-matching slots fall through to normal random swap")
        print(f"  - Set OOPS_ALL_NB_TARGET_CP=None in oops_v3.py to disable")
        print("=" * 64)

    # v0.24.53: cap all MMV imports at 1 per seed (user request).
    #
    # MMV imports (heritage chrs from BB/DS1/DS2/DS3 ported via the
    # ModernModVeritas pipeline; _source='mmv_import' in tags) are
    # cross-game chrs that often have partial-tag profiles, anim_bank
    # incompatibilities, or scripted-intro requirements that don't carry
    # over cleanly into NR. Even when an individual MMV chr works fine
    # at one slot, having multiple instances scattered around the seed
    # amplifies the surface area for sink/freeze/CTD issues.
    #
    # cap=1 makes each MMV import a singular encounter — limits failure
    # rate to one die roll per seed per chr. Explicit caps already in
    # V3_UNIQUE_TARGET_CAPS (e.g. c5300, c5130, c4720) are preserved as-is,
    # which keeps room for chrs whose vanilla design supports more than
    # one placement.
    #
    # v0.24.101: DISABLED — "open the floodgates" pass for variety.
    # Named-character explicit caps in V3_UNIQUE_TARGET_CAPS still apply
    # (those are unchanged). What this removes is the *blanket* auto-cap
    # that hit every MMV chr regardless of whether they'd actually been
    # problematic in playtest. If a specific MMV import shows up as a
    # CTD/sink offender, add it to V3_UNIQUE_TARGET_CAPS explicitly with
    # a tuned cap instead of capping the whole roster proactively. The
    # _LIFTED_V0_24_65 defensive caps below are unaffected — those are
    # for specific chrs lifted from broken_runtime_chrs, not MMV-blanket.
    mmv_capped_count = 0
    mmv_skipped_count = 0
    # for _cp, _t in tags.items():
    #     if _t.get('_source') != 'mmv_import':
    #         continue
    #     if _cp in V3_UNIQUE_TARGET_CAPS:
    #         mmv_skipped_count += 1
    #         continue
    #     V3_UNIQUE_TARGET_CAPS[_cp] = 1
    #     mmv_capped_count += 1
    if mmv_capped_count or mmv_skipped_count:
        print(f"v0.24.53: capped {mmv_capped_count} MMV imports at 1 placement "
              f"({mmv_skipped_count} skipped — explicit cap already in "
              f"V3_UNIQUE_TARGET_CAPS).")

    # v0.24.65: cap-1 safety net for chrs newly lifted from
    # broken_runtime_chrs.
    #
    # User playtest after v0.24.64 (chr-import + script + bundled aicommon)
    # confirmed that with MMV's sfx/ and material/ directories also deployed,
    # the full cross-game roster works — Romina playtest verified. The 30
    # chrs in nr_missing_chr_files.json broken_runtime_chrs were lifted to
    # the _meta.history.broken_runtime_chrs_lifted_v0_24_65 archive.
    #
    # Cap=1 each is a defensive measure: if any individual lifted chr is
    # STILL broken despite the SFX/material fix, cap=1 means at most ONE
    # failure per seed instead of the chr proliferating across the map.
    # The MMV entries (c5930, c6220) already have cap=1 via the v0.24.53
    # auto-cap above; they get skipped here.
    _LIFTED_V0_24_65 = frozenset({
        # Originally playtest-confirmed (seed 798229, v0.24.39) — riskier
        # v0.26.x cleanup: c3610 REMOVED from lift set. The v0.24.65 lift
        # gave it a defensive cap=1 as a safety net for the cluster_only
        # standalone-freeze risk; subsequent playtest (seed 923630 m49_43_00_00
        # pi=7) confirmed the freeze, and c3610 was re-added to
        # V3_EXCLUDE_TARGET_PREFIXES (see "Small Oracle Envoy" entry there).
        # The exclude wins; this cap entry was dead code from v0.24.86 onward.
        # Surfaced by `dev/audit_placement_budget_consistency.py`.
        # 'c3610',  # small Oracle Envoy — re-excluded; lift superseded
        'c3360',  # Ancestral Follower (was: no-tag-data, invisible)
        'c4430',  # Abnormal Stone Cluster (was: no-tag-data, invisible)
        # v0.24.40 proactive all-None-tag bans (25)
        # v0.24.102: crab/dog/bug caps removed (user req — these are
        # trash-tier critters and the cap=1 defensive measure was
        # blocking organic distribution. The auto-cap rationale was
        # "limit failure rate if broken" but these have been playtested
        # since v0.24.40 with no reported CTDs. Removed:
        #   crabs:  c2273, c2275, c2277
        #   dogs:   c4162, c4163, c4167
        #   bugs:   c4190, c4192
        'c3370',
        'c4140',
        # v0.26.x cleanup: c4361 REMOVED from lift set. Same pattern as c3610
        # above — v0.24.65 lifted it from EXCLUDE with defensive cap=1, but
        # v0.25.0-patch1 re-excluded c4361 Godrick Knight's Horse after
        # empirical CTDs in seeds 939029 and 42 (mount slots invoke rider-
        # mount composite logic that non-mount chrs can't satisfy). The
        # re-exclude is correct; this lift entry was overridden, cap dead.
        # 'c4361',  # Godrick Knight's Horse — re-excluded v0.25.0-patch1
        'c4312', 'c4316', 'c4356', 'c4376',
        'c4441', 'c4442',
        'c4482', 'c4483',
        'c4601', 'c4811',
        'c52309', 'c52312', 'c52313',
        'c6001',
        # v0.24.49 mmv_import bans (already capped via v0.24.53 — listed for completeness)
        'c5930', 'c6220',
    })
    # v0.27.8: the _LIFTED_V0_24_65 defensive cap=1 loop is REMOVED.
    # Alaric direction — the cap=1 blast-radius limiter was suppressing
    # organic distribution (the 20-seed sim showed 10 grunt/trash chrs
    # pinned at exactly 1/seed) and the lifted chrs have been playtested
    # since v0.24.40 with no reported CTDs. The frozenset above is kept
    # purely as a record of the historical lift. Each former-cap=1 chr
    # now falls to its tier cap below: grunt -> 32, miniboss -> 4.
    # NOTE: this re-exposes c5930 Giant Skeleton / c6220 Fire Demon
    # (invisible-render history) at up to 4x/seed.

    # v0.27.8: exclude c6201 Scarab — it carries a tag but has no roster
    # variants (an orphan; the 20-seed sim placed it 0/20). The picker
    # cannot place a variantless chr, so it only ever wasted a pool slot.
    V3_EXCLUDE_TARGET_PREFIXES.add('c6201')

    # v0.27.8: 'trash' tier collapsed into 'grunt'. As of v0.27.13 this is
    # baked into the source data (dev/dump_runtime_tier_overrides.py wrote
    # the collapse into nr_enemy_tags.json / mmv_imports.json, marked
    # _tier_collapse_v0_27_8). The runtime rewrite is therefore redundant —
    # kept only as a guard so a future data edit that reintroduces 'trash'
    # is caught and normalized rather than silently flowing through with an
    # unknown tier. Expected to retag 0 in normal operation.
    _retagged = 0
    for _t in tags.values():
        if isinstance(_t, dict) and _t.get('tier') == 'trash':
            _t['tier'] = 'grunt'
            _retagged += 1
    if _retagged:
        print(f"v0.27.8 guard: collapsed {_retagged} stray 'trash' tier(s) "
              f"into 'grunt' — these should be dumped to data via "
              f"dev/dump_runtime_tier_overrides.py")

    # v0.27.3: miniboss tier — reservation floor + cap normalization.
    # The 98-seed audit (dev/SESSION_NOTES_2026-05-26.md) showed the
    # miniboss tier is healthy in pool size (76 eligible) but badly
    # top-heavy: ~8 uncapped M-humanoid vanilla chrs land 11-15x/seed
    # while ~30 sit below 1x/seed, and the tier carried ZERO reservation
    # floors. Alaric direction: give every eligible miniboss a floor of 1
    # (guarantees the rare tail appears).
    #
    # v0.27.6: cap policy was "4 across the board" — every miniboss-tier
    # chr was capped at 4, overriding the v0.27.3 cap=6 default AND every
    # pre-existing hand-tuned 1/2/8 value. Power-of-2 ceiling; pairs with
    # the floor=1 (guarantee 1, allow up to 4).
    #
    # v0.28.2: tier-default-only — explicit JSON caps now win. The
    # v0.27.6 unconditional clamp silently overrode hand-tuned
    # placement_budget.json values (Onze cap=2 was bumped to 4; c4420
    # cap=0 was bumped to 4 — the latter discovered when c4420's pull-
    # from-rotation edit didn't take effect). The fix is one line: the
    # cap branch now uses the same `not in` guard the floor branch right
    # above it has always used. Tier defaults still apply to every
    # miniboss without an explicit cap in the JSON; mount-role override
    # below still wins unconditionally for c4050 / c5890.
    #
    # Slot budget: ~360 boss-strength slots/seed vs 100 floored chrs
    # (24 pre-existing + 76 miniboss) — ~3.6x headroom.
    #
    # CAVEAT: 26 of the 76 are XL+/XXL and exposed to the reservation-
    # floor-demotion bug (docs/OPEN_ISSUES.md — BIG_PROXIMITY / DENSITY
    # post-passes evict reserved big chrs). Their floors will NOT reliably
    # hold until that bug is fixed; the floor is fully effective for the
    # ~50 S/M/L minibosses immediately. Fixing the demotion bug is the
    # natural follow-up to make this tier-wide floor land for everyone.
    #
    # Idempotent: re-running load_data() in the same process is a no-op
    # (the `not in` guards skip already-set entries).
    _mb_exclude = (V3_EXCLUDE_PREFIXES | V3_EXCLUDE_TARGET_PREFIXES
                   | V3_GHOST_EXCLUDE_TARGET_PREFIXES)
    _mb_floored = 0
    _mb_capped = 0
    for _cp, _t in tags.items():
        if not isinstance(_t, dict) or _t.get('tier') != 'miniboss':
            continue
        if _cp in _mb_exclude:
            continue
        if _cp not in V3_RESERVATION_FLOORS:
            V3_RESERVATION_FLOORS[_cp] = 1
            _mb_floored += 1
        # v0.28.2: tier default only — leave explicit JSON caps alone.
        # Was `!= 4` (unconditional clamp); see the v0.28.2 docstring
        # block above for the Onze / c4420 motivation.
        if _cp not in V3_UNIQUE_TARGET_CAPS:
            V3_UNIQUE_TARGET_CAPS[_cp] = 4
            _mb_capped += 1
    if _mb_floored or _mb_capped:
        print(f"v0.27.3/.6: miniboss tier — floor=1 added to {_mb_floored} "
              f"chrs, cap=4 set on {_mb_capped} chrs")

    # v0.27.13: mount-role cap exemption. The miniboss block above sets
    # cap=4 on every miniboss, including c4050 Kaiden and c5840 Black
    # Knight (both bumped to miniboss for the rider/mount feature). But
    # the rider pool under the SOTE filter is {c5840} ALONE — a cap of
    # 4 would leave 20 of the 24 Kaiden rider slots vanilla, defeating
    # the whole point of the swap. Mount-role chrs get a cap sized to
    # their slot population instead: 24 rider slots + 12 mount slots in
    # the inventory, so cap=30 gives comfortable headroom for either
    # role to fill every slot of its type. Overrides the miniboss cap=4
    # for these chrs specifically. (A role chr that is also reservation-
    # floored keeps its floor — floor and cap are independent.)
    _role_capped = 0
    for _cp, _t in tags.items():
        if not isinstance(_t, dict):
            continue
        if _t.get('mount_role') in ('rider', 'mount'):
            if V3_UNIQUE_TARGET_CAPS.get(_cp) != 30:
                V3_UNIQUE_TARGET_CAPS[_cp] = 30
                _role_capped += 1
    if _role_capped:
        print(f"v0.27.13: mount-role chrs — cap=30 set on {_role_capped} "
              f"chrs (overrides miniboss cap=4 so role slots can fill)")

    # v0.27.8: grunt tier (grunt + the now-collapsed trash) — tier-wide
    # cap=40. Alaric direction. The 20-seed sim showed the tier
    # saturating: 52 of 105 eligible chrs flatlined at the old implicit
    # global cap of 50 — 74% of all grunt placements — with no shaping
    # below it. cap=40 reshapes the top end.
    #
    # v0.27.9: cap raised 32 -> 40. cap=32 was leaving ~10% of grunt
    # slots vanilla (no-target) — 104 grunts x 32 = 3,328 capacity vs
    # ~3,506 non-hub grunt slots, plus uneven cap fill across MSBs. 40
    # gives 4,160 capacity — comfortable headroom. This is an INTERIM
    # value: the durable fix is enlarging the grunt pool by importing
    # more ER grunt assets (each new eligible grunt = +40 capacity),
    # after which the cap can come back down.
    #
    # v0.27.13: grunt floor=4 REMOVED — tier-collapse regression. The
    # v0.27.8 floor put all ~103 grunt chrs into V3_RESERVATION_FLOORS,
    # so the reservation pre-pass started reserving slots for them. But
    # _score_slot_for_unique is tier-blind — it scores boss-catalog
    # membership (+10), NB markers (+5) and size, never tier match — so
    # grunt reservations landed *preferentially* on boss-strength slots,
    # and the reservation early-return in pick_target_cp commits them,
    # bypassing the tier-preserve filter entirely. dev/sim_tier_transitions.py
    # (25 seeds, v0.27.12) measured 16.1% of miniboss-source placements
    # downgraded to a grunt enemy — ~37/seed, every seed — 100% via the
    # reservation path, 0 via the organic picker. Dropping the grunt
    # floor removes grunts from the pre-pass; they place organically
    # (tier-preserve keeps them in grunt slots) and cap=40 still shapes
    # the top end. Cost: the ~14-chr rare-grunt tail loses its >=4x
    # guarantee. The tier-respecting fix (gate _score_slot_for_unique on
    # tier bucket) would let the floor return safely and is the better
    # long-term option — see docs/OPEN_ISSUES.md — but per Alaric only
    # the miniboss/night_boss floors are load-bearing, so the grunt
    # floor is simply dropped here.
    _gr_exclude = (V3_EXCLUDE_PREFIXES | V3_EXCLUDE_TARGET_PREFIXES
                   | V3_GHOST_EXCLUDE_TARGET_PREFIXES)
    _gr_capped = 0
    for _cp, _t in tags.items():
        if not isinstance(_t, dict) or _t.get('tier') != 'grunt':
            continue
        if _cp in _gr_exclude:
            continue
        # v0.28.2: tier default only — same fix as the miniboss block
        # above (explicit JSON caps win). No grunt-tier hand-tunes
        # exist in placement_budget.json today; this is preemptive.
        # _RARE_NOVELTY_CAPS below intentionally STILL wins over this
        # default — it's an explicit grunt-tier override, not a JSON
        # hand-tune, and runs after this loop on purpose.
        if _cp not in V3_UNIQUE_TARGET_CAPS:
            V3_UNIQUE_TARGET_CAPS[_cp] = 40
            _gr_capped += 1
    if _gr_capped:
        print(f"v0.27.8/.9: grunt tier — cap=40 set on {_gr_capped} chrs "
              f"(floor removed v0.27.13 — tier-collapse fix)")

    # v0.27.27: rare-novelty cap overrides — applied AFTER the grunt sweep
    # above so they aren't clobbered back to 40. These are grunt-tier chrs
    # that FromSoft never spawns in vanilla NR (they exist only in the
    # post_dlc_dump regulation data) and that the rando is the sole source
    # of. Left uncapped they fill ~11 grunt slots/seed (measured), which is
    # too frequent for an easter-egg creature. A low cap makes each one a
    # rare surprise rather than wallpaper while keeping it in the pool.
    #   c4442 Giant Rotten Land Squirt — the rot variant of the Giant Land
    #   Squirt, fixed/un-benched in v0.27.26 (think repointed to 44410000).
    #   Zero vanilla source Parts; cap=4 (matching the miniboss-tier rarity
    #   tier) per Alaric — a couple of sightings/seed, not a dozen.
    _RARE_NOVELTY_CAPS = {
        'c4442': 4,
    }
    _rn_capped = 0
    for _cp, _cap in _RARE_NOVELTY_CAPS.items():
        if _cp in _gr_exclude:
            continue
        if V3_UNIQUE_TARGET_CAPS.get(_cp) != _cap:
            V3_UNIQUE_TARGET_CAPS[_cp] = _cap
            _rn_capped += 1
    if _rn_capped:
        print(f"v0.27.27: rare-novelty caps — {_rn_capped} chr(s) capped "
              f"below grunt-40 ({', '.join(f'{k}={v}' for k, v in _RARE_NOVELTY_CAPS.items())})")

    # v0.27.13: build the all-SOTE target set from the fully-merged tag
    # DB. Computed every load_data() so it tracks tag edits with no
    # separate data file to keep in sync. Drives V3_SOTE_MODE in
    # pick_target_cp.
    #
    # v0.27.21: membership is the UNION of two signals, so the SOTE-mode
    # roster is decoupled from the origin_game provenance field:
    #
    #   (a) origin_game == 'SoTE' — the historical signal. The MMV boss
    #       ports carry it via the mmv_imports.json merge above, and the
    #       heritage SOTE field enemies carry it directly in
    #       nr_enemy_tags.json.
    #
    #   (b) sote_eligible == True — an explicit opt-in flag. Added so a
    #       chr can be SOTE-mode-eligible WITHOUT lying about its
    #       provenance. Two cases need this: (1) genuinely-SoTE imports
    #       whose origin_game was never stamped (the er_heritage_port_v0_27_0
    #       round — Putrescent Knight, Furnace Golem, Divine Beast Dancing
    #       Lion, the SoTE Demi-Humans, etc.), and (2) cross-lineage models
    #       that ship as SoTE encounters but originate elsewhere (the
    #       Black Knight + Horse are DS3-lineage; flagging them sote_eligible
    #       is honest where flipping origin_game to 'SoTE' was not). Keeping
    #       origin_game accurate means dev/tag_sote_origin.py and any
    #       provenance audit stay correct; this flag is purely a
    #       SOTE-mode-roster switch.
    # (global decl removed — engine version writes to ns instead)
    V3_SOTE_PREFIXES = {_cp for _cp, _t in tags.items()
                        if isinstance(_t, dict)
                        and (_t.get('origin_game') == 'SoTE'
                             or _t.get('sote_eligible') is True)}
    ns['V3_SOTE_PREFIXES'] = V3_SOTE_PREFIXES  # flush to caller namespace

    # v0.27.13: rider/mount pools from the mount_role tag.
    # v0.27.44 (Alaric): the RIDER pool is now intentionally left EMPTY. The
    # rider-role restriction (`pool &= V3_RIDER_PREFIXES` in pick_target_cp)
    # only existed to keep a SWAPPED mounted cluster's two halves coherent.
    # Pairs are now PRESERVED vanilla at the SLOT level (see
    # _preserve_detected_rider_mount_pairs + the strict (msb, pi) gate), and a
    # preserved slot returns None long before the rider/mount gate is reached.
    # So any rider that DOES reach the gate is SOLO — a dismounted Kaiden
    # (c4050) or a foot Black Knight (c5840) — and must randomize like a normal
    # enemy. Keeping it in the rider pool would freeze it vanilla now that the
    # c5840<->c5890 swap family is banned (c5890): the rider branch would pin
    # the pool to {recipient_cp} (or empty it under the unique cap) and the
    # slot would never swap. The MOUNT pool stays populated: mounts
    # (c4060/c5890) are still stripped from every non-role target pool below
    # (the riderless-mount freeze/CTD guard) and pinned to vanilla as sources.
    # (global decl removed — engine version writes to ns instead)
    V3_RIDER_PREFIXES = set()
    ns['V3_RIDER_PREFIXES'] = V3_RIDER_PREFIXES  # flush to caller namespace
    V3_MOUNT_PREFIXES = {_cp for _cp, _t in tags.items()
                         if isinstance(_t, dict)
                         and _t.get('mount_role') == 'mount'}
    ns['V3_MOUNT_PREFIXES'] = V3_MOUNT_PREFIXES  # flush to caller namespace
    if V3_RIDER_PREFIXES or V3_MOUNT_PREFIXES:
        print(f"v0.27.13: mount-role pools — rider={sorted(V3_RIDER_PREFIXES)}, "
              f"mount={sorted(V3_MOUNT_PREFIXES)}")
    if V3_SOTE_MODE:
        print(f"*** ALL-SOTE MODE: target pool restricted to "
              f"{len(V3_SOTE_PREFIXES)} Shadow-of-the-Erdtree chrs ***")
        print(f"***   {', '.join(sorted(V3_SOTE_PREFIXES))} ***")
        print(f"***   caps/floors bypassed — expect heavy repeats. "
              f"Requires MMV + heritage assets staged. ***")

    # v0.27.24: think-param validation guard. The durable backstop for the
    # c5251 / v0.27.23 AI-inert failure class. The engine writes a variant's
    # roster think_param_id straight into the MSB Part at swap time with NO
    # runtime validation against the regulation, so any variant pointing at
    # a think id that doesn't exist in the regulation's NpcThinkParam table
    # spawns a chr with no AI (loads, may aggro, never runs battle logic).
    # Both c5251 (manually fixed in v0.27.22) and the six chrs swept in
    # v0.27.23 reached players because nothing checked this at load time.
    #
    # The guard validates every roster think_param_id against the bundled
    # data/valid_think_param_ids.json manifest (the set of IDs present in
    # the regulation's NpcThinkParam, regenerated by
    # dev/extract_think_param_ids.py) and auto-adds any variant whose think
    # id is absent to V3_AVOID_VARIANT_NPC_IDS — keyed on npc_param_id, the
    # same hard filter _filter_avoid_npc already enforces. This turns the
    # whole failure class into "the dead variant is silently skipped"
    # instead of "the dead variant spawns inert in someone's game":
    #   - a chr with SOME valid-think variants keeps them; the picker routes
    #     around the dead ones.
    #   - a chr whose variants are ALL dead-think no-targets (the slot stays
    #     vanilla) — correct, better than an AI-inert placement.
    #
    # Fail-open: a missing/malformed manifest skips the guard entirely (the
    # static V3_AVOID_VARIANT_NPC_IDS entries from v0.27.23 still cover the
    # known cases). Idempotent: a set union, so repeated load_data() calls
    # in one process converge to the same set. The manifest only needs
    # regenerating when the regulation's NpcThinkParam table changes; the
    # static entries are the safety net in the interim.
    _think_manifest_path = _data_path('valid_think_param_ids.json')
    if os.path.isfile(_think_manifest_path):
        try:
            with open(_think_manifest_path, encoding='utf-8') as _f:
                _valid_think = set(json.load(_f).get('valid_think_param_ids', []))
        except Exception as _e:
            print(f"v0.27.24: think-param guard SKIPPED — manifest load "
                  f"failed ({_e!r}); relying on static avoid-list.")
            _valid_think = None
        if _valid_think:
            _dead_think_npc = set()
            _dead_by_cp = {}
            for _v in roster.get('all_variants', []):
                if not isinstance(_v, dict):
                    continue
                _th = _v.get('think_param_id')
                _npc = _v.get('npc_param_id')
                if _th is None or _npc is None:
                    continue
                if int(_th) not in _valid_think:
                    _dead_think_npc.add(int(_npc))
                    _dead_by_cp.setdefault(_v.get('c_prefix'), set()).add(int(_th))
            _newly = _dead_think_npc - V3_AVOID_VARIANT_NPC_IDS
            if _dead_think_npc:
                V3_AVOID_VARIANT_NPC_IDS = (
                    V3_AVOID_VARIANT_NPC_IDS | _dead_think_npc)
                ns['V3_AVOID_VARIANT_NPC_IDS'] = V3_AVOID_VARIANT_NPC_IDS  # flush to caller namespace
                # Report c-prefixes that LOSE EVERY variant to the guard —
                # those fully no-target (slot stays vanilla). Compute against
                # the post-trigger-filter variant view so the warning matches
                # what the picker can actually draw.
                _pv_chk, _ = build_per_prefix_data(roster)
                _fully_dead = []
                for _cp, _ths in sorted(_dead_by_cp.items()):
                    _cp_variants = _pv_chk.get(_cp, [])
                    if _cp_variants and all(
                            int(_vv.get('npc_param_id')) in V3_AVOID_VARIANT_NPC_IDS
                            for _vv in _cp_variants
                            if _vv.get('npc_param_id') is not None):
                        _fully_dead.append(_cp)
                print(f"v0.27.24: think-param guard — {len(_dead_think_npc)} "
                      f"variant(s) across {len(_dead_by_cp)} c-prefix(es) point "
                      f"at think ids absent from the regulation; avoid-listed "
                      f"({len(_newly)} not already static).")
                if _fully_dead:
                    print(f"v0.27.24: think-param guard — fully no-target "
                          f"c-prefixes (all variants dead-think, stay vanilla): "
                          f"{', '.join(_fully_dead)}")

    # v0.28.x (Phase 2 POI recycling): load the spatial cluster table.
    # Optional — if data/slot_poi_clusters.json is absent (e.g. older
    # data layouts, or fresh install before build_slot_poi_clusters.py
    # has been run), the engine silently falls back to per-MSB scope.
    # Format: {msb_name: [[part_index, ...], ...]} with each inner list
    # being one cluster, 0-indexed by min part_index within the MSB.
    # (global decl removed — engine version writes to ns instead)
    _clusters_path = _data_path('slot_poi_clusters.json')
    if os.path.isfile(_clusters_path):
        try:
            with open(_clusters_path, encoding='utf-8') as f:
                _clusters_data = json.load(f)
            _V3_SLOT_POI_CLUSTERS = _clusters_data.get('clusters', {})
            ns['_V3_SLOT_POI_CLUSTERS'] = _V3_SLOT_POI_CLUSTERS  # flush to caller namespace
            _n_msbs = _clusters_data.get('_meta', {}).get('n_msbs', '?')
            _n_clusters = _clusters_data.get('_meta', {}).get('n_clusters_total', '?')
            _radius = _clusters_data.get('_meta', {}).get('radius_m', '?')
            print(f"v0.28.x POI scope: loaded {_n_clusters} clusters across "
                  f"{_n_msbs} MSBs (R={_radius}m). V3_POI_SCOPE_RECYCLE="
                  f"{V3_POI_SCOPE_RECYCLE}.")
        except Exception as e:
            print(f"v0.28.x POI scope: failed to load slot_poi_clusters.json "
                  f"({e}); falling back to per-MSB scope.")
            _V3_SLOT_POI_CLUSTERS = None
            ns['_V3_SLOT_POI_CLUSTERS'] = _V3_SLOT_POI_CLUSTERS  # flush to caller namespace
    else:
        _V3_SLOT_POI_CLUSTERS = None
        ns['_V3_SLOT_POI_CLUSTERS'] = _V3_SLOT_POI_CLUSTERS  # flush to caller namespace

    return roster, tags
