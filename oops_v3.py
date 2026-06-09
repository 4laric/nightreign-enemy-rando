#!/usr/bin/env python3
"""
oops_v3 — vanilla-aware model-shuffle for Nightreign.

Reads each Part's vanilla c-prefix from MSB Models section and matches swap
targets by anim_bank/size/locomotion compatibility, preserving slot identity:

  - Dragon slot (c4500, loco=3, XL) → other dragon-class swap targets
  - Tree Sentinel slot (c3250, loco=3, XL) → other XL mounted bosses
  - Wolf slot (c4070, loco=0, S) → other small humanoid/beast targets
  - Knight slot (c4353, loco=0, M, boss-tier) → other boss-tier humanoid targets

This eliminates the locomotion-mismatch T-pose freezes that plagued the
wolf-build-based v2 rando.

Pipeline integration: same as v2 (works on extracted .msb files, expects sidecar
XMLs alongside or generates them).

USAGE:
    python oops_v3.py shuffle <input_dir> <output_dir> [--seed N] [--tags JSON]
"""
import json, os, struct, random, shutil, sys, threading
from collections import Counter, defaultdict

# v0.19.22: engine version + fingerprint for spoiler self-identification.
# The fingerprint is a short hash derived from a fix-marker string that
# changes every release; if a stale .pyc is being loaded, the fingerprint
# in the spoiler header won't match the source's value, making the
# install-layering bug obvious from the spoiler alone.
V3_ENGINE_VERSION = 'v0.32'
V3_ENGINE_FINGERPRINT = 'v0.32'  # MUST bump on each release — appears in spoilers

# v0.28.x (Phase 2 POI recycling): default on. Flip to False to revert
# the per-cluster scope and restore the v0.27.45 per-MSB-only behavior
# in shuffle_msb_v3's swap loop. The recycle logic itself is unchanged
# — only the scope of "what counts as resident in this picker call".
# See dev/POI_RECYCLING_SPEC.md for the design and Phase 1 measurements.
V3_POI_SCOPE_RECYCLE = True

# v0.28.x: lazy-loaded cluster table. {msb_name: [[part_index, ...], ...]}
# where each inner list is one POI cluster (0-indexed by min part_index
# within the MSB). Populated by load_data() from
# data/slot_poi_clusters.json. Read by shuffle_msb_v3 to drive
# cluster-grouped slot iteration. None when the file isn't present
# (older installs / test environments without Phase 0 data) — engine
# falls back to MSB scope in that case.
_V3_SLOT_POI_CLUSTERS = None

# Re-export primitives from oops_all_anyone (already validated, working)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oops_all_anyone import (
    parse_msb_sections, parse_model_entry, find_model_index, add_model_entry,
    find_or_add_model, remove_unused_model_entries,
    PART_OFF_NPC_PARAM, PART_OFF_MODEL_INDEX, PART_OFF_THINK_PARAM,
    PART_OFF_ENTITY_ID, PART_OFF_POSITION,
    SIDECAR_SUFFIXES,
)

# v0.24.21: per-run override application — context manager owns the
# save/apply/restore lifecycle for the 4 module gate fields that
# cmd_shuffle_v3 swaps in for the duration of a run. Centralizes the
# composition logic (sanitize / union / subtract / ordering) so it's
# testable in isolation and adding a 5th override no longer requires
# threading edits through three places in cmd_shuffle_v3.
from engine.runtime import apply_run_overrides, compose_pool_cap_overrides
from engine.runctx import RunContext
from engine.pack_loaders.heritage_pack import apply_heritage_pack
from engine.pack_loaders.er_heritage import apply_er_heritage
from engine.pack_loaders.mmv_imports import apply_mmv_imports
from engine.placement_budget import apply_static_overrides as _apply_placement_budget_overrides

# v0.28.x: night-boss arena → expedition/role table. Lives at the project
# root next to data_archive / vanilla_source — pure data + helpers, no
# project deps. write_spoiler_logs reads it via `ns['night_role']` to
# stamp entries and label map-section headers. Importing it into module
# globals here makes it visible in vars(oops_v3) which is what the shim
# passes as ns.
import night_role


# v0.24.22 (Phase 12): per-pack loader registry.
#
# Each LoaderSpec packages everything the load_data dispatch loop needs
# to drive one pack: the filename to look for on disk, the apply_fn
# (which does the actual tag/roster mutation and returns a stats dict),
# and a log_fn (which formats the per-loader print line(s) from the
# stats). The dispatch loop in load_data iterates this list, applies
# uniform I/O + snapshot-override + exception handling around each one,
# and accumulates stats so the post-loop gate-set fold can run once.
#
# Adding a new pack means: write the apply_fn following the established
# contract (engine/pack_loaders/), write a log_fn that formats its
# log lines, append a LoaderSpec entry below. No edits to load_data
# itself required — the dispatch loop is data-driven.
#
# Order matters and is preserved from the pre-Phase-12 inline layout:
# heritage_pack runs first (its disable path can remove cps), then
# er_heritage (vanilla-wins additive), then mmv (authoritative override
# whose tags should win over both). The fold of contributions into
# V3_NIGHT_BOSS_CALIBER_TARGETS / V3_NIGHT_BOSS_STRICT_TARGETS /
# V3_EXCLUDE_TARGET_PREFIXES happens AFTER all loaders run, so order
# within those sets is order-independent (set union is commutative).

from collections import namedtuple
LoaderSpec = namedtuple('LoaderSpec', ['filename', 'apply_fn', 'log_fn'])


def _log_heritage_pack(stats):
    """Format the heritage_pack log line. Only the disabled path
    emits — the enabled path is a no-op against the engine's tag set
    (heritage cps live in base nr_enemy_tags.json already)."""
    if stats['enabled']:
        return
    hp_cps = stats['hp_cps']
    extras = (f'... +{len(hp_cps) - 5} more'
              if len(hp_cps) > 5 else '')
    print(f"heritage_pack: skipped (_meta.enabled=false), "
          f"removed {stats['n_tag_removed']} tags + "
          f"{stats['n_variant_removed']} "
          f"variants from pool ({sorted(hp_cps)[:5]}{extras})")


def _log_er_heritage(stats):
    """Format the er_heritage log line."""
    if not stats['enabled']:
        print("er_heritage_imports: skipped (_meta.enabled=false)")
        return
    if stats['n_tags_added'] or stats['n_variants_added']:
        print(f"er_heritage_imports: {stats['n_tags_added']} "
              f"tags + {stats['n_variants_added']} variants "
              f"loaded (_source=er_heritage_v1)")


def _log_mmv_imports(stats):
    """Format the mmv_imports log lines. Two categories: the main
    summary line (tags + variants + caliber/strict/blacklist counts)
    and a mount-component auto-ban line if any cps got banned.

    v0.26.x: cross-engine guard removed — see engine/pack_loaders/
    mmv_imports.py module docstring."""
    if not stats['enabled']:
        print("mmv_imports: skipped (_meta.enabled=false)")
        return
    if stats['mount_component_bans']:
        print(f"mmv_imports: mount_component auto-ban "
              f"{len(stats['mount_component_bans'])} chr(s) — "
              f"{sorted(stats['mount_component_bans'])}")
    if stats['n_tags_added'] or stats['n_variants_added']:
        bl_bd = stats['blacklist_breakdown']
        print(f"mmv_imports: {stats['n_tags_added']} tags + "
              f"{stats['n_variants_added']} variants loaded "
              f"(_source=mmv_import); "
              f"caliber +{len(stats['caliber_adds'])}, "
              f"strict-NB +{len(stats['strict_adds'])}, "
              f"blacklist +{len(stats['blacklist'])} "
              f"({len(bl_bd['ctd_unidentified'])} CTD + "
              f"{len(bl_bd['dlc_assets_missing_in_mmv'])} "
              f"DLC-asset-missing"
              f" + {len(bl_bd['ai_broken'])} AI-broken"
              f" + {len(bl_bd.get('phase_transition_broken', ()))} "
              f"phase-transition-broken)")


_PACK_LOADERS = [
    LoaderSpec('heritage_pack.json', apply_heritage_pack,
               _log_heritage_pack),
    LoaderSpec('er_heritage_imports.json', apply_er_heritage,
               _log_er_heritage),
    LoaderSpec('mmv_imports.json', apply_mmv_imports,
               _log_mmv_imports),
]

# swap_compat — boss-arena / drop-preservation rules.
# Layered on top of the existing anim_bank+size+loco compat for finer-grained
# rejection (Margit-into-Royal-Revenant, Dragonkin-into-Guardian-Golem, etc).
# Optional — falls through to a no-op if the module or tag fields are missing.
try:
    from swap_compat import is_compatible as _swap_compat_is_compatible
    _SWAP_COMPAT_AVAILABLE = True
except ImportError:
    _SWAP_COMPAT_AVAILABLE = False
    def _swap_compat_is_compatible(*a, **kw):
        return True, []


# v0.23.06: project root tidy-up moved auxiliary data files into a `data/`
# subfolder. To keep older layouts working (in case someone has an existing
# install with these files at root), `_data_path` resolves a data-file name
# by checking `data/<name>` first, then falling back to `<name>` at the
# project root. Most engine reads route through this helper now.
def _data_path(filename):
    here = os.path.dirname(os.path.abspath(__file__))
    new_loc = os.path.join(here, 'data', filename)
    if os.path.exists(new_loc):
        return new_loc
    return os.path.join(here, filename)


# ============================================================================
# v0.23.72-late: POOL SNAPSHOTS
# ----------------------------------------------------------------------------
# A "pool snapshot" is a named, persistable configuration that controls
# which asset packs feed into the swap pool. The use case is a/b testing
# different rando configurations (e.g. "vanilla NR only" vs "vanilla NR
# + heritage_pack") without manually editing _meta.enabled in each pack
# JSON, and shipping pre-baked configs to friends so their data/ folder
# doesn't get rewritten by the act of trying out a different pool.
#
# Snapshot schema (pool_snapshot_v1):
#   {
#     '_schema': 'pool_snapshot_v1',
#     'name': str,
#     'description': str,
#     'created': ISO timestamp,
#     'engine_version': str,
#     'pack_overrides': {            # applied at pack load time
#         '<pack_filename.json>': {'enabled': bool, ...},
#     },
#     'engine_kwargs': {              # passed through to cmd_shuffle_v3
#         'excluded_prefixes': [...],
#         'multiplayer_safe': bool,
#         ...
#     },
#   }
#
# Mechanism. `V3_SNAPSHOT_PACK_OVERRIDES` is a module-level dict consulted
# by every pack-load site in load_data() / detect_asset_packs(). When a
# pack file is loaded, its _meta gets overlaid with overrides[filename]
# BEFORE the enabled check fires. Empty dict (default) = no overrides,
# vanilla behavior.
#
# Lifecycle is caller-managed:
#   1. `apply_pool_snapshot(snap)` populates V3_SNAPSHOT_PACK_OVERRIDES
#      and returns engine_kwargs for splatting into cmd_shuffle_v3.
#   2. Run cmd_shuffle_v3 with those kwargs.
#   3. `clear_pool_snapshot()` resets the override dict.
# Callers should call clear_pool_snapshot() in a finally block to avoid
# leaking state into subsequent runs of the same process (matters for
# the GUI which keeps the engine module loaded across runs).
#
# Snapshots NEVER modify pack JSON files on disk. The override layer is
# purely runtime. Ship snapshots to friends as JSON files; they apply
# per-run without polluting persistent state.

V3_SNAPSHOT_PACK_OVERRIDES = {}

V3_SNAPSHOT_SCHEMA = 'pool_snapshot_v1'


def load_pool_snapshot(path):
    """Read a snapshot file from disk and return the parsed dict.

    Raises ValueError if the file doesn't conform to the expected schema.
    No side effects — call apply_pool_snapshot() to actually use the
    overrides for a run."""
    with open(path, encoding='utf-8') as f:
        snap = json.load(f)
    schema = snap.get('_schema')
    if schema != V3_SNAPSHOT_SCHEMA:
        raise ValueError(
            f"Snapshot at {path}: schema {schema!r} not supported. "
            f"Expected {V3_SNAPSHOT_SCHEMA!r}.")
    # Normalize the structure so consumers can splat with confidence.
    snap.setdefault('pack_overrides', {})
    snap.setdefault('engine_kwargs', {})
    return snap


def apply_pool_snapshot(snap_or_path):
    """Apply a pool snapshot's pack_overrides to module state. Returns
    the snapshot's engine_kwargs dict for the caller to splat into
    cmd_shuffle_v3.

    Accepts either a dict (already loaded) or a path string.

    Lifecycle: the caller is responsible for calling clear_pool_snapshot()
    when the run is done, ideally in a finally block. Without that, the
    overrides leak into the next call to load_data() in the same process."""
    global V3_SNAPSHOT_PACK_OVERRIDES
    if isinstance(snap_or_path, str):
        snap = load_pool_snapshot(snap_or_path)
    else:
        snap = snap_or_path
    V3_SNAPSHOT_PACK_OVERRIDES = dict(snap.get('pack_overrides', {}))
    return dict(snap.get('engine_kwargs', {}))


def clear_pool_snapshot():
    """Reset V3_SNAPSHOT_PACK_OVERRIDES to {}. Call from a finally block
    after apply_pool_snapshot() to avoid state leakage between runs."""
    global V3_SNAPSHOT_PACK_OVERRIDES
    V3_SNAPSHOT_PACK_OVERRIDES = {}


def save_pool_snapshot(path, name, description='', engine_kwargs=None,
                        pack_overrides=None):
    """Write a snapshot file to disk.

    If pack_overrides is None, captures the CURRENT effective state of
    every known pack (whatever _meta.enabled is set to on disk) into
    explicit overrides. This makes the snapshot self-contained: applying
    it later will reproduce exactly the same pool regardless of what the
    pack files look like at apply time.

    If engine_kwargs is None, an empty dict is written.

    Args:
      path: filesystem path to write to. The caller is responsible for
            creating intermediate directories.
      name: short human-readable name (e.g. 'vanilla NR only').
      description: longer free-form description.
      engine_kwargs: dict of cmd_shuffle_v3 kwargs to include. Should be
                     JSON-serializable. Common entries: excluded_prefixes
                     (as list, not set), multiplayer_safe, hub_maps.
      pack_overrides: dict of pack-filename → meta-override-dict. If None,
                      auto-captured from disk.

    Returns the path written."""
    import datetime as _dt
    if pack_overrides is None:
        pack_overrides = _capture_current_pack_state()
    snap = {
        '_schema': V3_SNAPSHOT_SCHEMA,
        'name': name,
        'description': description,
        'created': _dt.datetime.now().isoformat(),
        'engine_version': V3_ENGINE_VERSION,
        'pack_overrides': pack_overrides,
        'engine_kwargs': engine_kwargs or {},
    }
    # Ensure the engine_kwargs is JSON-serializable. excluded_prefixes is
    # typically a set in memory; convert to sorted list for round-trip safety.
    if 'excluded_prefixes' in snap['engine_kwargs']:
        ep = snap['engine_kwargs']['excluded_prefixes']
        if isinstance(ep, set):
            snap['engine_kwargs']['excluded_prefixes'] = sorted(ep)
    if 'hub_maps' in snap['engine_kwargs']:
        hm = snap['engine_kwargs']['hub_maps']
        if isinstance(hm, set):
            snap['engine_kwargs']['hub_maps'] = sorted(hm)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(snap, f, indent=2, sort_keys=False)
    return path


def _capture_current_pack_state():
    """Inspect every known pack JSON file on disk and return a dict of
    {filename: {'enabled': bool}} reflecting their current state.

    Used by save_pool_snapshot when no explicit overrides are provided —
    'whatever you have right now becomes the recorded snapshot.'"""
    # Set of pack filenames to capture. Keep aligned with the pack loads
    # in load_data() + detect_asset_packs(). Currently:
    KNOWN_PACK_FILES = (
        'er_heritage_imports.json',
        'heritage_pack.json',
        'mmv_imports.json',
    )
    state = {}
    for fname in KNOWN_PACK_FILES:
        path = _data_path(fname)
        if not os.path.isfile(path):
            # Absent pack — record as disabled-by-absence for snapshot
            # explicitness (consumer can tell it wasn't installed).
            state[fname] = {'enabled': False, '_absent': True}
            continue
        try:
            with open(path, encoding='utf-8') as f:
                pack = json.load(f)
        except Exception:
            state[fname] = {'enabled': False, '_unreadable': True}
            continue
        meta = pack.get('_meta', {})
        state[fname] = {'enabled': bool(meta.get('enabled', True))}
    return state


def _apply_snapshot_overrides_to_pack(pack_dict, pack_filename):
    """In-place: merge V3_SNAPSHOT_PACK_OVERRIDES[pack_filename] into
    pack_dict['_meta']. Used at every pack-load site in load_data() so the
    snapshot's enabled-flag (and any other meta overrides) take effect."""
    override = V3_SNAPSHOT_PACK_OVERRIDES.get(pack_filename)
    if not override:
        return
    # _absent / _unreadable are diagnostic markers on the snapshot side;
    # they don't override actual pack contents (the pack IS present here,
    # so we ignore those flags).
    real_overrides = {k: v for k, v in override.items() if not k.startswith('_')}
    if not real_overrides:
        return
    meta = pack_dict.setdefault('_meta', {})
    meta.update(real_overrides)


# Hub maps where we passthrough vanilla — but with vanilla MSBs, this is now
# more about preserving NPC/quest interactions. Even with proper roster filtering,
# safer to leave hubs alone so dialogue/event triggers don't break.
V3_HUB_MAPS = {
    'm10_00_00_00.msb','m11_00_00_00.msb','m12_00_00_00.msb',
    'm13_00_00_00.msb','m13_20_00_00.msb','m18_00_00_00.msb',
    # m14 hub — not in wolf build but exists in vanilla
    'm14_00_00_00.msb',
}

# v0.23.07: source-tag classes that mark a c-prefix as TARGET-ONLY in the
# rando — picked as a swap target but NEVER swapped OUT (their few/no MSB
# placements stay vanilla). Anything tagged with one of these `_source`
# values in the loaded tags dict gets the target-only treatment.
#
# Members:
#   'script_spawn'      Vanilla NR scripted-spawn chrs that have NpcParam
#                       data but no MSB placements — Ancestor Spirit
#                       (c4670), Grafted Scion (c4690), and the legacy
#                       night bosses Gaping Dragon (c7700), Centipede Demon
#                       (c7710), Centipede Grub (c7711, c7712), Duke's
#                       Dear Freja (c7800), Freja Spiderling (c7810),
#                       Smelter Demon (c7820), Nameless King (c7900),
#                       Storm King (c7910), Dancer of the Boreal Valley
#                       (c7920). All shipped in nr_enemy_tags.json directly
#                       (the v0.19–v0.23.72-late manual_promotions.json
#                       middleware was retired in v0.23.72-late once these
#                       entries were complete in canonical data).
#   'er_heritage_v1'    er_heritage_imports.json — c2xxx ER NB-tier bosses
#                       whose chr files ship in NR's chr/ folder (per
#                       ChrModelParam) but have no NpcParam rows in NR's
#                       regulation. Authored from ER convention. Empirical
#                       anchor: c2160 Astel confirmed working in playtest.
#                       Removable as a unit by deleting the JSON file.
V3_TARGET_ONLY_SOURCES = frozenset({'er_heritage_v1'})  # v0.27.x: dropped 'script_spawn' — no chr carries that _source after the v0.26.x reclassification to nr_placed (dead arm). NOTE: verify 'er_heritage_v1' still matches a live _source; static tags now use 'er_heritage_port_v0_27_0'.

# C-prefixes to never use as a swap source (slot stays vanilla) or target.
V3_EXCLUDE_PREFIXES = {
    # Player + nightfarer templates
    'c0000','c0010','c0100','c0110','c0120','c1000','c2070',
    # Fail on a fresh install (no loadable enemy assets when placed) — v0.31:
    #   c3501, c8101  post_dlc_dump phantoms, no .chrbnd (c8101 dups the
    #                 Wheeled Ballista by name/hp).
    #   c5680         Wheeled Ballista, SoTE heritage, no IMPORT_PLAN path
    #                 (cf. c6031 Bear); not bundled on a fresh install.
    #   c8910         team=26 system/UI chr, not a combat enemy.
    #   c4960, c4961  Giant Skeleton Torso — torso-only, break when relocated
    #                 (c4961 _special_story team=6; c4960 team=33). Reverts the
    #                 v0.29.x c4960 unban; c4961 was also mislabeled "Sebastian
    #                 — safe" in V3_FRAGILE_SAFE_CONFIRMED (removed below). The
    #                 giant_skeleton_torso cap group + _RARE_NOVELTY_CAPS
    #                 entries for c4960/c4961 are now dead config.
    'c3501','c4960','c4961','c5680','c8101','c8910',
    # Sub-components and non-combat
    'c4000','c6001','c8130','c8131','c8132',
    # c4491 unbanned in v0.28.x: had 1 merchant variant + 6 hostile
    # exploding Small Living Jar variants (team=6, 1615x spEffect
    # family). The blanket prefix exclusion was over-broad — the
    # merchant variant (npc=44910000) is already individually filtered
    # via V3_AVOID_VARIANT_NPC_IDS (see line ~2008), and in-world
    # Limveld merchants are protected as SWAP SOURCES via line ~9971
    # (`if cur_cp not in ('c3200', 'c4491')`). Result: the 6 combat
    # variants now land at non-merchant slots; merchants stay merchants.
    # v0.11 newly-tagged non-combat entities (previously untagged, swap behavior
    # was undefined; now explicitly excluded so they're predictable):
    'c2150',  # Lightning Ball — projectile/ability entity, not a real enemy
    'c3200',  # Nomadic Merchant — non-hostile NPC; merchant model swap feature
              #                    will access this c-prefix through a separate
              #                    mechanism, but standard rando excludes it
    'c4191',  # Scarab — small loot bug, no combat behavior
    'c8911',  # unknown special entity, only 1 placement; safe-skip until identified
    # === Nightlord-tier — Day 3 arena bosses, never spawn elsewhere ===
    # These have wake events specific to m19/m15 Nightlord arenas. Putting them
    # at random Night Boss POIs gives you a billion-HP T-pose with the wrong
    # name in the healthbar.
    'c4900','c4901',          # Caligo - Miasma of Night (dragon-range Nightlord)
    'c7500','c7510','c7511',  # Gladius, Adel, Adel Everdark
    'c7520','c7521',          # Gnoster, Animus
    'c7530','c7540','c7541',  # Faurtis, Maris, Maris Phase 2
    'c7560','c7561','c7570',  # Libra (3 variants)
    'c7580','c7600',          # ?, Fulghor
    'c7620',                  # Harmonia (Raid mode, special encounter)
    # v0.23.72-late: c7700/c7710/c7711/c7712/c7800/c7810/c7820/c7920 REMOVED
    # from this exclude list. They were defensively banned with the comment
    # "unknown high-tier (likely Nightlord/Raid)" before their identities
    # were confirmed via the souls-modding wiki. They're actually vanilla
    # NR legacy night bosses (Gaping Dragon c7700, Centipede Demon c7710,
    # Centipede Grub c7711/c7712, Duke's Dear Freja c7800, Freja Spiderling
    # c7810, Smelter Demon c7820, Dancer of the Boreal Valley c7920) —
    # scripted-spawn but conceptually night_boss-tier with proper wake
    # animations. Eligible as swap targets at appropriate slots.
    # NOTE: if any of these turn out to have arena-specific wake events
    # that fail at non-vanilla slots (mirroring the Nightlord issue
    # above), playtest will reveal it and individual c-prefixes can be
    # re-added with a specific reason.
    # NOTE: in nr_enemy_tags they're marked `_source: 'script_spawn'`
    # which puts them in V3_TARGET_ONLY_SOURCES — they're picked as
    # TARGETS only, never replace as SOURCES (which is moot since they
    # have 0 MSB Parts but documents intent).
    # NOTE: c4470 (Abductor Virgin Fort) and c5110 (Maris Tendril) were
    # previously excluded due to wake-trigger / dormant-spawn bugs. Both classes
    # are now covered by EMEVD patches: permissive_boss_wake (90015000/90015030)
    # makes wake-trigger bosses activate on Recognition/Alert/damage; and
    # permissive_spawn_emerge (90085002) force-enables AI on tunnel/cave mobs
    # whose emerge animation would otherwise lock them dormant. Both prefixes
    # are now valid sources AND targets — slots will randomize.

    # NOTE: flying dragons (c4500/c4504/c4505) and the unverified
    # crab imports (c2273/c2275/c2277) were moved OUT of this set to
    # V3_EXCLUDE_TARGET_PREFIXES (v0.26.x-fix). This set excludes as
    # source AND target; only target-exclusion was intended — vanilla
    # dragon/crab slots must stay source-eligible so they randomize.
    # -- Mount / rider components + composites. Moved here v0.26.x from
    # the split SOURCE+TARGET listing (consolidation per exclude audit).
    # Excluded as BOTH: vanilla slots scramble rider-mount pairs / hand-
    # tuned encounters if randomized away (source side); they break
    # standalone -- riderless mounts have no AI, c3610 floats frozen
    # off-cluster, c4450 clips everything (target side). Rider-mount
    # proximity collapse + RIDER_MOUNT_PAIRS still handle in-cluster pairs.
    'c3150',  # Night's Cavalry (rider)
    'c3160',  # Funeral Steed (Night's Cavalry mount)
    'c3170',  # Albinauric Archer (rider)
    'c3180',  # Albinauric Archer's Wolf (mount)
    # v0.27.13: c3170/c3180 Albinauric Archer + Wolf KEPT excluded
    # (both ways) — deliberate. The mount-role pool feature (see
    # V3_RIDER_PREFIXES) lets rider/mount slots randomize within their
    # role, and its correctness rests on every eligible mount being a
    # horse. The Wolf is the one non-horse mount: a knight on a wolf
    # has no mounted-combat moveset and would mismatch destructively.
    # Excluding the Albinauric pair removes that case entirely, so the
    # mount pool is horses-only. Alaric direction.
    #
    # v0.27.13: c4050/c4060 Kaiden Sellsword + Horse, and c5890 Black
    # Knight Horse, LIFTED from this both-ways exclude. They are now
    # mount_role-tagged (rider/mount) and participate in randomization
    # via the role-restricted pool in pick_target_cp. They are NOT
    # added to any other exclude set — the role pool is what bounds
    # them now. c4363 Lordsworn's Horse stays excluded (NB-arena mount,
    # its own preservation reasons, untagged).
    'c4363',  # Lordsworn Knight's Horse (NB-variant mount)
    'c3610',  # Oracle Envoy -- Maris cluster member; floats frozen off-cluster
    'c4450',  # Walking Mausoleum -- 59m tall, clips everything; keep at home
    # v0.28.x: Messmer phase-2 alt prefixes. c5130 (Phase 1) and c5140 (Phase 2,
    # the serpent) are the two canonical Messmer entries surfaced to the rando;
    # c5131/c5132 are alternate humanoid Phase 2 model variants and c5141 is a
    # serpent model variant. Their assets ship in heritage_pack for completeness
    # (so any reference in ER MSBs imported via heritage doesn't break), but
    # from the rando's perspective they're redundant with c5130/c5140 and would
    # just clutter the roster. Excluded as both source AND target — never picked
    # for a swap, slot containing them stays vanilla. Companion data-side fix
    # removes them from nr_enemy_tags / nr_enemy_roster / placement_budget; this
    # set is the engine-level backstop so future data edits can't accidentally
    # surface them.
    'c5131',  # Messmer Phase 2 (humanoid alt — redundant with c5140)
    'c5132',  # Messmer Phase 2 (humanoid alt variant)
    'c5141',  # Messmer Phase 2 (serpent model variant — redundant with c5140)
}

# C-prefixes excluded as SOURCES only (slot stays vanilla) but allowed as targets.
# Use this for slots whose encounter context is too unique for our EMEVD patches
# to handle, but where the c-prefix itself is well-behaved when placed elsewhere.
V3_EXCLUDE_SOURCE_PREFIXES = {
    # v0.23.76: c4110 Demi-Human Shaman REMOVED from source-exclude. The
    # original rationale (single compatible target c5810, causing every
    # Shaman to become a Swordmaster) was authored when the compat pool
    # was narrow. Pool has since expanded (BFER + heritage + tag-aware
    # compat) so Shaman sources now have a healthy spread of targets.
    # c5810 Swordmaster stays target-excluded (still dominates small
    # compat pools when allowed as target) so Shamans won't all become
    # Swordmasters; instead they spread across the full pool.
    # OLD COMMENT (kept for context):
    #   Demi-Human Shaman has only ONE compatible target (c5810 Swordmaster) and
    #   109 source slots, so randomization made every Shaman in the world a
    #   Swordmaster. The Shaman+Swordmaster pairing is a tightly-paired vanilla
    #   encounter design (Demi-Human Queen Night Boss at m49_29). Keeping both
    #   vanilla preserves the pairing and avoids the visual monotony of seeing
    #   Swordmasters everywhere. Pair with c5810 in V3_EXCLUDE_TARGET_PREFIXES.
    # 'c4110',  # LIFTED v0.23.76
    # v0.11: preserve the Maris boss arena (m19_00) by keeping its
    # cluster-member c-prefixes vanilla as sources. They become targets
    # elsewhere via V3_FORCE_INCLUDE_UNTAGGED_TARGETS, but their original
    # placements at the Maris encounter stay coherent — without this,
    # adding them as targets caused m19_00 to scramble (94 vanilla
    # Tendrils + 47 Jellyfish + 13 Envoys all shuffled into each other).
    'c5110',  # Maris' Tendril
    'c4181',  # Maris' Jellyfish
    # v0.20.24: c3620 (Oracle Envoy Large; Cathedral) REMOVED from
    # source-exclude. Playtest evidence: only the SMALL Oracle Envoy
    # (c3610) has the floating-frozen-at-spawn issue at non-cluster
    # placements; the Cathedral-Large variant doesn't share the bug.
    # Letting c3620's vanilla slots randomize like normal source slots.
    # Note: c3620 is still in V3_MAP_PREFIX_TARGET_EXCLUDES['m60_'] —
    # that's the Limveld safety belt for the still-being-investigated
    # Limveld procedural-load CTD. Two orthogonal protections; can be
    # revisited independently.
    #
    # v0.23.71: RE-ADDED. The v0.20.24 finding was correct for non-
    # cluster placements of c3620 (scattered Limveld tiles etc.), but
    # didn't account for the cathedral CLUSTER itself. User playtest
    # of seed 940574 with cluster_aware=False (v0.23.71 default) CTD'd
    # at m38_00 cathedral tile — the 4 c3620 Oracle Envoy slots
    # (pi=11-14) were swapped independently to c3010/c4352/c3460/c4355,
    # all sane M-humanoid picks individually but the cathedral
    # encounter EMEVD invokes cluster-dance ForceAnimationPlayback
    # against c3620's anim bank on those entity_ids. With 4 different
    # chrs at those entities, the anim IDs don't resolve in their
    # banks → undefined behavior → CTD.
    #
    # Re-excluding as a source means the 4 cathedral envoy slots stay
    # vanilla while c3620 remains AVAILABLE as a TARGET in random
    # slots elsewhere (where the cluster-dance EMEVD doesn't fire).
    # Trade-off: lose ability to swap OUT vanilla c3620 placements
    # everywhere they appear (not just the cathedral cluster). The
    # variety cost is acceptable given the cathedral CTD.
    #
    # A finer fix would be (msb, pi)-level exclusion via V3_PROBLEM_SLOTS
    # — only the 4 cathedral envoy slots, not every c3620 in the world.
    # Deferring that until we confirm the CTD only fires at cathedral
    # (other c3620 cluster sites might be equally affected).
    #
    # v0.23.74: PERMANENTLY LIFTED. Phase 1 EMEVD audit + empirical repro
    # test (seed 940574, c3620 source-exclude commented out): the cathedral
    # cluster does NOT CTD on 4-different-chrs. m38_00 has zero direct FAP
    # calls in the EMEVD corpus — the "cluster-dance ForceAnimationPlayback"
    # diagnosis above was wrong. The actual failure mode is per-chr slot
    # fragility (c3970 Azula Beastman froze at pi=14 in the repro; the
    # other 3 chrs at pi=11/12/13 worked fine). Targeted fix moved to
    # V3_PROBLEM_SLOT_EXTRA_BANS m38_00 pi=11-14 entries. The historical
    # commentary above is preserved for context — DO NOT re-add c3620
    # to this set without a new empirical CTD that disproves Phase 1.
    # 'c3620',  # Oracle Envoy (Large; Cathedral) -- LIFTED v0.23.74

    # v0.23.71: Alabaster Lord (c3600) source-exclude — Twin Alabaster
    # Lords duo Night Boss arena (m49_20) CTD class. Same failure mode
    # as the cathedral c3620 cluster fix above.
    #
    # Vanilla NR places 2 c3600 entities at m49_20 pi=0 and pi=1 for the
    # Twin Alabaster Lords duo encounter. The arena EMEVD references
    # both entity_ids by their c3600 identity and triggers synchronized
    # cluster animations (telegraphed dual cast, partner-aware pacing,
    # phase-2 trigger when one is killed). With cluster_aware=False
    # default, both slots get independently swapped to different chrs.
    # When the EMEVD calls ForceAnimationPlayback on the entities, the
    # anim IDs don't resolve in the new chrs' anim banks — CTD mid-fight.
    #
    # User report (seed 549220): m49_20 pi=0 c3600 → c3800 Cleanrot Knight;
    # pi=1 c3600 → c3810 Kindred of Rot (Marsh Group Boss). CTD while
    # engaged with the Cleanrot Knight.
    #
    # Trade-off: loses ability to swap OUT vanilla c3600 placements
    # (Alabaster Lord + Onyx Lord variants — same c-prefix). The variants
    # appear at evergaol slots, Fallingstar Beast prelude slots, and the
    # m49_20 duo. All three contexts preserved vanilla.
    #
    # BROADER PATTERN ALERT: other m49_xx duo arenas have the same cluster
    # shape and are not yet protected:
    #   m49_28  c2140 Omen ×5 + c3150 Night's Cavalry ×2 + c3160 Funeral
    #           Steed ×2 — c3150/c3160 already source-excluded (rider+
    #           mount pair preservation), but c2140 not protected
    #   m49_29  c4100 Demi-Human ×5 + c4101 Large Demi-Human ×4 — Demi-
    #           Human Queen boss arena, multi-Part cluster, no protection
    #   m49_43  c2500 Crucible Knight (Unscaled) ×10 — 10-Part cluster,
    #           no protection
    # If user reports a CTD at one of those, add the relevant c-prefix
    # to this set with similar rationale. The general fix would be a
    # _duo_arena flag on the MSB or per-c-prefix _cluster_only tag for
    # these vanilla duo bosses; deferring until empirical pressure.
    #
    # v0.23.74: LIFTED. Same protocol as c3620 above. Phase 1 audit
    # invalidated the cathedral cluster-dance hypothesis; the m49_20
    # Alabaster duo failure mode (seed 549220 CTD against c3800
    # Cleanrot Knight) might be the same per-chr fragility story rather
    # than a real cluster-dance FAP issue. Lifting to empirically test:
    # if the next playthrough's m49_20 NB encounter holds, the lift
    # stays. If it CTDs, we instrument the specific failure and add a
    # targeted fix (V3_PROBLEM_SLOT_EXTRA_BANS or V3_PRESERVE_SLOTS
    # — see below for the new strict-preserve mechanism). Note: this
    # lift exposes m46_60 Alabaster Evergaol slots too (2 c3600 Parts
    # there). The "two horseback nightboss encounters" user-stipulated
    # exemption covers m49_28 (Cavalry NB) + Tree Sentinel arenas only;
    # m46_60 + m49_20 are deliberately exposed for the test.
    # 'c3600',  # Alabaster Lord — LIFTED v0.23.74
    # v0.17: Night's Cavalry rider+mount pair preservation. The c3150 rider
    # and c3160 Funeral Steed are linked by EMEVD events that handle the
    # rider's dismount/remount mid-fight: when the rider dismounts, an event
    # disables the c3160 entity; later when the rider re-summons, the same
    # event re-enables it. The remount lookup is by entity_id of the c3160
    # mount slot — when the rando swaps that slot to a non-c3160 enemy,
    # the engine still finds an entity at that ID but its model isn't a
    # mount. The rider can still re-summon (the call succeeds), but they
    # mount nothing visible / mount the wrong model. In the m49_28 Twin
    # Cavalry Night Boss arena specifically, the encounter completion
    # logic also wants both rider AND steed entities defeated; with the
    # steed swapped to a free-standing non-mount, that fails too.
    #
    # Keeping c3150+c3160 vanilla preserves the rider+mount semantic
    # everywhere they appear together. Loses variety on Night's Cavalry
    # placements (which also appear as overworld Night Bosses) but trades
    # for encounter-completion safety.
    #
    # v0.23.74: BOTH LIFTED. User authorization "let's rip out horse-rider
    # protection and see what happens is hilarious. my gut is that as
    # long as we maintain the exemption for the two horseback nightboss
    # encounters, we'll be fine." The horseback NB exemptions are now
    # enforced at (msb, pi)-level via V3_PRESERVE_SLOTS (m49_28 Cavalry
    # rider+mount pair preservation) — see that set's docstring. The
    # Tree Sentinel arena Lordsworn pair is already protected via
    # V3_EXCLUDE_SOURCE_NPC_PARAMS (43531400 Lordsworn Knight NB,
    # 43630010+43630400 Lordsworn Horse NB) which remains active.
    # Deliberately NOT protecting m46_62 Night's Cavalry Evergaol; if
    # it breaks, add to V3_PRESERVE_SLOTS in the next round.
    # v0.24.101: c3150 RE-INTRODUCED after playtest seed 537123 v0.24.96
    # showed Godskin Apostle visually "riding" the Cavalry horse at m46_62
    # Evergaol. The collapse pass that was supposed to zero the mount
    # Part's npc_param doesn't fully address the visual issue — Night's
    # Cavalry's spawn cluster appears to carry the horse model as part
    # of the rider's spawn animation, so swapping to a non-mounted rider
    # leaves the visual horse anchored to the new chr. Broad source+target
    # exclusion of c3150 (rider) and c3160 (mount, already excluded both
    # ways) is the conservative fix while the collapse pass is revisited.
    # See _collapse_rider_mount_pairs TODO at line ~969.
    # 'c3160',  # Funeral Steed (mount) — already excluded above
    # 'c3150',  # Night's Cavalry (rider) — LIFTED v0.23.74
    # 'c3160',  # Funeral Steed (mount) — LIFTED v0.23.74
    # v0.19.13: Tree Sentinel Night Boss arena trio (m48_50 + m48_60).
    # Empirically validated by playtest: when c3250 Draconic Tree Sentinel
    # got swapped to a non-mounted boss model (Fat Inquisitor in seed
    # 246135), the 4 vanilla c4363 Lordsworn Knight's Horse (Night Boss)
    # entities continued executing their mount-coordination script
    # targeting the rider entity_id. Result: horses loop their mount-up
    # animation indefinitely (visible glitching), looped voice/SFX bank
    # fires on a tight cycle (the "ungodly noise" reported), and the
    # rider's mounted-combat AI can't engage from atop a non-horse.
    #
    # v0.19.13 fix: c-prefix-level exclude on c3250/c3251/c4363.
    #
    # v0.23.50 NARROWING: c-prefix-level exclude was overly broad. Tree
    # Sentinel and Draconic Tree Sentinel ALSO appear in Limveld
    # overworld (m60_xx tiles) where there's no NB-arena phase script,
    # no shared-eid coordination, and no fixed mount-up cinematic — they
    # randomize fine there, just like Royal Carian Knight (c3252) does.
    # The fix only needs to protect the 4 Day-3 NB arena slots:
    #
    #   c3250 npc=32500110 'Draconic Tree Sentinel (Night Boss)' @ m48_50
    #   c3251 npc=32510110 'Tree Sentinel (Night Boss)'          @ m48_60
    #   c4363 npc=43630010 "Lordsworn Knight's Horse (Night Boss)" @ both
    #   c4363 npc=43630400 "Lordsworn Knight's Horse (Night Boss Spirit)" @ both
    #
    # Those 4 NPCParam IDs go to V3_EXCLUDE_SOURCE_NPC_PARAMS below
    # (sibling pattern to the v0.19.14 Leyndell Knight Night-Boss-Spirit
    # exclude at npc=43531400). Limveld Tree Sentinels (npc=32500000,
    # 32500010, 32500100, 32510000, 32510030, etc.) are now SWAPPABLE
    # as sources, restoring variety in the overworld.
    #
    # The Field Boss variants (npc=32500090, 32510020) — these appear at
    # m60_42_37_50 etc — also stay swappable. They're geometrically
    # similar to the NB arenas but don't have the phase-script
    # coordination, so they can swap without breaking.
    #
    # 'c3250',  # ← REMOVED v0.23.50 — see V3_EXCLUDE_SOURCE_NPC_PARAMS
    # 'c3251',  # ← REMOVED v0.23.50 — see V3_EXCLUDE_SOURCE_NPC_PARAMS
    # 'c4363',  # ← REMOVED v0.23.50 — see V3_EXCLUDE_SOURCE_NPC_PARAMS
    # v0.23.04.1 added c4300 + c3660 here as a blanket guard against the
    # "sit-idle freeze" issue (Bloodfiend-on-stump / Living-Jar-as-statue
    # screenshots from seed 887995). Variety cost was 341 vanilla source
    # slots (276 c4300 + 65 c3660), which is far too much given that only
    # a small subset of those Parts actually carry the sit-idle Part-state
    # flag — most Wandering Nobles and Commoners are walking / standing
    # patrols that swap fine.
    #
    # v0.23.05.1: REVERTED to npc_param-level surgical exclusion. Only the
    # one variant explicitly named as a sitting-merchant ('Wandering Noble
    # - Wandering Merchant (Guardian Remembrance)', npc=43009400) stays
    # source-excluded — see V3_EXCLUDE_SOURCE_NPC_PARAMS below. That's
    # zero variety cost (count=1) and preserves the one obvious case.
    #
    # Other sit-idle Parts that exist in vanilla MSBs (Commoners begging
    # in courtyards, Wandering Nobles seated by campfires, etc.) are
    # NOT identifiable from variant names alone — their sit-state lives
    # in the Part struct's init_state_event field, which oops_all_anyone
    # doesn't currently expose an offset for. Properly fixing those
    # requires a Part-struct mapping audit (research project, deferred).
    # In the meantime, players will occasionally see a frozen chr in a
    # vendor / kneeling / sitting pose — visual only, not a CTD. Trade
    # accepted: the variety win from 341 randomized slots outweighs
    # occasional visual oddness at a small subset of those slots.

    # v0.27.45 (merge fix): c4050 Kaiden Sellsword — the cluster-visual
    # mounted-rider case, SOURCE-excluded (not both-ways) so its mounted
    # vanilla Parts stay vanilla while it remains placeable as a TARGET
    # elsewhere. Same failure mode as the c3150 Night's Cavalry RE-INTRODUCED
    # note above: the horse model rides in on the rider's spawn CLUSTER, not
    # as a separate mount Part, so swapping the rider leaves the visual horse
    # anchored to the new chr. Evidence — spoiler _spoilers.json (v0.27.45)
    # showed c4050 at m60_44_36_00 pi=28 -> c5270 Jar Innards (a Jar Innards
    # visibly on the Kaiden horse); the file has ZERO c4060 Parts in 3779
    # entries, confirming the mount is not a Part, so _detect_mount_rider_slots
    # (Part-to-Part proximity) can never catch it and the v0.27.44 slot-level
    # preserve never fires. ALL 21 c4050 source slots had randomized, and
    # EVERY c4050 variant is isRideAtkTarget=1 (all mounted, scattered across
    # the m60_44_xx overworld field tiles) — so the cluster-horse problem is
    # broad for Kaiden, justifying the c-prefix-level source preserve. SOURCE-
    # only: c4050 stays TARGET-eligible (still in compatible_pool); its solo
    # target instances spawn fresh with no cluster, so no orphaned mount. The
    # c4060 horse target-ban is unchanged.
    #
    # NOTE — c4353 Leyndell Knight is deliberately NOT here. Its only MOUNTED
    # instances are the Tree Sentinel Night-Boss arena riders (m48_50/m48_60),
    # which are ALREADY preserved surgically via V3_EXCLUDE_SOURCE_NPC_PARAMS
    # (43531110 active rider + 43531400 spirit, plus horses 43630010/43630400)
    # — verified: those four npc_params randomized 0 times in the spoiler, and
    # 0 c4353/c4363 randomized in m48/m49. The c4353 instances that DO
    # randomize are the foot variants (43530030 "Encampment- by tower",
    # 43531030 "Encampment- middle", 43530130 "Night Horde", etc.) — no
    # cluster horse to orphan. A blanket c4353 source-exclude would freeze
    # those foot soldiers for no benefit, so it was removed. Per Alaric:
    # mounted Leyndell Knights are confined to the m48/m49 arenas.
    'c4050',  # Kaiden Sellsword — visual mount via spawn cluster (no c4060 Part)
}

# Position-aware source skip. When a Part's source c_prefix matches an entry
# here AND the Part's y-coordinate is >= the threshold, the slot stays vanilla.
# Lower-y placements of the same c_prefix randomize normally.
#
# Why: bats (c4200 Man-Bat, c4201 Operatic Bat) have unique flight locomotion
# (only enemies in the entire roster with locomotion=2). Their MSB parts are
# placed at cliff-perch / ledge / rooftop positions (up to y=224) where
# they hover/perch and glide down on player detection. When a ground enemy
# is swapped in, gravity drops it onto whatever surface exists at that XZ
# coordinate — typically a navmesh island authored for a flier, with no
# walking connection to surrounding terrain. The enemy senses the player
# (visible Recognition swivel) but its pathfinder can't compute a route,
# so it stands stuck.
#
# There is no script-side fix: zero EMEVDs reference any bat NPCParam ID,
# the bats are pure MSB-spawn entities. Whether the slot is "safely
# swappable" depends entirely on whether the surface beneath the spawn
# point connects to walkable terrain. y >= 50 is a heuristic threshold
# based on observed altitude distribution — captures the cliff-perch /
# rooftop cluster without being so strict it benches the gliding-near-
# ground placements that work fine.
#
# Trade-off: about 70-75 of 128 vanilla bat parts stay swappable (the
# ground-level ones); the remaining 50-some stay vanilla. If a y < 50 bat
# slot still freezes in-game, lower the threshold further or move the
# affected c_prefix to V3_EXCLUDE_SOURCE_PREFIXES.
#
# TODO: Bats problem flagged for circle-back (2026-05-03). The current
# V3_AERIAL_SOURCE_ALT whitelist is a partial workaround; full bats
# compatibility story not resolved. See TODO.md for context.
V3_AERIAL_SOURCE_SKIP = {}  # v0.20.0: emptied — slot_y tracking removed

# Per-NPCParam source exclusion: more granular than c-prefix-level.
# Use this when only specific variants of a c-prefix need their slots kept
# vanilla (e.g. only certain spirit-summon variants of a c-prefix while the
# standard variants randomize normally).
V3_EXCLUDE_SOURCE_NPC_PARAMS = {
    # v0.20.13: Guardian Golem (Fort) source-exclusion REMOVED. Original
    # entry (npc=46601010) was added on the assumption that this variant
    # at m30_30 was the laying-down-pretending-dead pose with a unique
    # stand-up cinematic that no other c-prefix could play, which would
    # leave a randomized swap frozen at spawn. Playtest evidence (4laric,
    # 2026-05) contradicts that premise — the Fort variant doesn't
    # actually start prone, so the slot is structurally identical to
    # any other field-boss slot and randomizes safely. The standing
    # Cathedral (npc=46600030) and Remembrance (npc=46600020) variants
    # were already randomizing normally; this just brings Fort into line.
    # v0.19.14: Leyndell Knight (Night Boss Spirit) — c4353, npc=43531400.
    # Belt-and-suspenders for the Tree Sentinel arenas (m48_50 + m48_60).
    # The spirit summon trigger fires on phase-change in the boss event
    # chain, expecting a c4353-Spirit at the slot's entity_id to activate
    # ethereally. With v0.19.13 already source-excluding the rider
    # (c3250/c3251), the trigger should fire correctly — but if the
    # spirit slot itself was randomized to a non-spirit knight, the
    # phase-change event still summons a non-spirit at that slot, which
    # may or may not activate cleanly. Playtest report: "ghost soldier
    # was frozen, not hittable" — the spirit slot stayed vanilla but the
    # boss was randomized in v0.19.12, breaking summon coordination.
    # Source-excluding this NpcParam keeps the spirit slot vanilla
    # regardless of broader c4353 randomization. c4353 has 8 other
    # variants (regular Leyndell Knights at encampments etc) that
    # continue to randomize freely.
    43531400,
    # v0.23.03: Leyndell Knight (Night Boss) active riders — c4353, npc=43531110.
    # Tree Sentinel arena (m48_50 + m48_60) third bug. v0.19.13 preserved
    # the boss (c3250/c3251) and horses (c4363); v0.19.14 preserved the
    # spirit-summon variant (npc=43531400). The named active rider variant
    # was left swappable on the assumption that swapping just the rider
    # would be safe with everything else preserved. Playtest seed 381869:
    # CTD on Tree Sentinel kill in m48_60 — the rider eids (48600810/820)
    # are referenced by the boss death event chain (likely a phase-down
    # cleanup that signals each named rider's eid). With the rider model
    # swapped to Cleanrot Knight (c3800), the game tries to dispatch the
    # event and the non-Leyndell-Knight model can't service it. Same
    # surgical pattern as 43531400 — 4 parts total across both arenas,
    # zero variety cost outside this encounter. c4353 has 7+ other variants
    # (regular Leyndell Knights at encampments etc.) that continue to
    # randomize freely.
    43531110,
    # v0.23.74: Tree Sentinel Night Boss arena surgical excludes
    # NARROWED. The two Tree Sentinel boss-chr Parts at m48_50 (DTS) and
    # m48_60 (TS) are lifted from the exclude — empirical reframing from
    # user playtest: Tree Sentinel and Draconic Tree Sentinel are
    # self-contained big quadrupeds (fragile-locomotion (large), tier=
    # night_boss), taxonomically more like c5210 Divine Beast Dancing
    # Lion than like a true rider+horse pair. The "rider + mount"
    # framing in the original v0.19.13 / v0.23.50 comment block was
    # collateral mislabeling — the actual v0.19.13 "ungodly noise"
    # failure originated from the SIBLING Lordsworn Knight rider Parts
    # (c4353 npc=43531400) getting swapped while their paired horses
    # (c4363 npc=43630010/400) stayed vanilla. That root pair is still
    # double-protected below: rider exclude was added in v0.19.14
    # (43531400, present in this set), horse excludes added v0.23.50
    # (43630010/400, retained). Tree Sentinels were swept up in the
    # v0.19.13 c-prefix blanket and stayed protected as collateral until
    # alaric playtest confirmed they swap cleanly as self-contained
    # entities.
    #
    # Lifted:
    # 32500110,  # 'Draconic Tree Sentinel (Night Boss)'         @ m48_50
    # 32510110,  # 'Tree Sentinel (Night Boss)'                  @ m48_60
    # Retained (true rider+horse pair w/ Lordsworn Knight at 43531400):
    43630010,  # "Lordsworn Knight's Horse (Night Boss)"       @ both
    43630400,  # "Lordsworn Knight's Horse (Night Boss Spirit)" @ both
    # If ungodly noise reappears with the Tree Sentinel lifts in place,
    # restore by un-commenting the 32500110 / 32510110 lines above.
    # v0.23.05.1: surgical narrowing of the v0.23.04.1 sit-idle freeze fix.
    # Only this one explicitly-merchant variant has a name marker we can
    # confidently identify as "sitting vendor pose" — the variant scrape
    # gives us name='Wandering Noble - Wandering Merchant (Guardian
    # Remembrance)' and count=1 (only one MSB Part uses this npc_param,
    # in m10_00_00_00). Excluding the source slot keeps that one Part
    # vanilla; the other 275 c4300 variants randomize normally. The
    # blanket c4300/c3660 source-exclude in v0.23.04.1 was reverted —
    # see comment in V3_EXCLUDE_SOURCE_PREFIXES above.
    43009400,  # Wandering Noble - Wandering Merchant (Guardian Remembrance)
}


# v0.23.74: strict (msb, pi)-level vanilla preservation. Slots listed here
# get `return None` from pick_target_cp — the Part stays vanilla in the
# output, no swap attempted.
#
# DISTINCT from neighboring mechanisms:
#   - V3_EXCLUDE_SOURCE_PREFIXES: c-prefix-level, globally. Too broad
#     when only specific encounter slots need preservation.
#   - V3_EXCLUDE_SOURCE_NPC_PARAMS: NPCParam-level. Strict-preserve at the
#     variant level. Use when you know the specific NPCParam IDs.
#   - V3_PROBLEM_SLOTS: narrows pool to RESILIENT/SAFE — still SWAPS, just
#     to a restricted set. Not strict preservation.
#   - V3_PRESERVE_SLOTS (this set): strict-preserve at the (msb, pi)
#     level. Use when you don't have NPCParam IDs handy but you know the
#     specific slots to lock down. Cheaper than digging into MSB binaries.
#
# Introduced v0.23.74 to back the "two horseback nightboss encounters"
# exemption when c3150/c3160 source-exclude was lifted. The Tree Sentinel
# arenas keep their NPCParam-level protection (already in
# V3_EXCLUDE_SOURCE_NPC_PARAMS). The Night's Cavalry duo arena m49_28 uses
# this new mechanism instead — same effect, simpler to maintain when
# extending to other paired encounters (each new pair = 4 lines of dict
# entries rather than an MSB binary read).
V3_PRESERVE_SLOTS = {
    # m49_28 Night's Cavalry x2 NB arena — preserves the rider+mount pair
    # encounter semantics. The arena EMEVD references c3150/c3160 by
    # entity_id for dismount/remount scripting; swapping either Part to a
    # non-c3150/c3160 breaks the rider's re-summon (mounts wrong model)
    # and the encounter-completion check (steed entity never marked
    # defeated). c2140 Omen ambushers at pi=0,1,6,7,8 are deliberately
    # LEFT swappable — they're encounter trash, not paired with the
    # Cavalry's scripted logic. If Omen swaps break the encounter staging
    # in playtest, add those pi's here too.
    ('m49_28_00_00.msb', 2): "Night's Cavalry rider (NB pair 1) — preserve horseback NB encounter",
    ('m49_28_00_00.msb', 3): "Night's Cavalry rider (NB pair 2) — preserve horseback NB encounter",
    ('m49_28_00_00.msb', 4): "Funeral Steed mount (NB pair 1)  — preserve horseback NB encounter",
    ('m49_28_00_00.msb', 5): "Funeral Steed mount (NB pair 2)  — preserve horseback NB encounter",
    # v0.24.101: m46_62 Night's Cavalry Evergaol — added after playtest
    # seed 537123 showed c3560 Godskin Apostle riding the Cavalry horse
    # at pi=1. The collapse pass zeros the mount's npc_param so the
    # *combat* horse doesn't spawn, but Night's Cavalry's spawn animation
    # appears to include a rendered mount as part of the rider's cluster —
    # swapping to a non-mounted rider leaves the visual horse anchored to
    # the new chr. Preserving the rider Parts (pi=1, 3) and mount Parts
    # (pi=2, 4) keeps the encounter vanilla, matching the m49_28 NB arena
    # treatment. See line ~648 comment ("Deliberately NOT protecting
    # m46_62 ... if it breaks, add to V3_PRESERVE_SLOTS in the next
    # round") — this is that round.
    ('m46_62_00_00.msb', 1): "Night's Cavalry rider (Evergaol pair 1) — preserve horseback Cavalry encounter",
    ('m46_62_00_00.msb', 2): "Funeral Steed mount (Evergaol pair 1)  — preserve horseback Cavalry encounter",
    ('m46_62_00_00.msb', 3): "Night's Cavalry rider (Evergaol pair 2) — preserve horseback Cavalry encounter",
    ('m46_62_00_00.msb', 4): "Funeral Steed mount (Evergaol pair 2)  — preserve horseback Cavalry encounter",
}


# v0.23.04: Rider+mount cluster collapse.
#
# In vanilla NR, several encounters use a (rider Part + mount Part) co-located
# at the same MSB position. The mount Part's NPCParam is configured for
# "ride-along" rather than standalone combat — its AI is degenerate without a
# rider. When the rando swapped rider and mount independently to non-paired
# c-prefixes, the result was either:
#   - rider on weird mount (mount-script eid pairing breaks → looped mount-up
#     animation, ungodly noise — v0.19.13's "Tree Sentinel arena" symptom),
#   - rider gone but mount still there (riderless inert mount trotting around
#     — v0.20.69's "frozen Night's Cav horse" symptom),
#   - or rider gone and mount swapped to non-mount (cluster integrity broken
#     in subtler ways).
#
# Previously addressed by source-excluding either the whole encounter
# (V3_EXCLUDE_SOURCE_PREFIXES on c3150/c3160/c4363, etc.) or the mount cprefix
# as a target (V3_EXCLUDE_TARGET_PREFIXES on c4060/c3160/c3180/c4363). Both
# strategies trade variety for safety.
#
# v0.23.04 takes a different tack: detect rider+mount Part pairs at swap time
# and *suppress* the mount Part by zeroing its npc_param (vanilla-MSB
# convention for "this Part exists but spawns no enemy" — 93% of vanilla
# Parts use npc=0 this way). The rider Part flows through the normal swap
# path picking a single standalone target. Result: one varied enemy
# materializes per pair instead of either glitchy mount-rider mismatch or
# full-vanilla preservation.
#
# The detector matches an explicit allowlist of (rider_cp, mount_cp) cprefix
# pairs grounded in vanilla MSB scan (see scan: 23 same-position pairs across
# 7 MSBs, 4 valid cprefix combinations driving 21 of them, 2 noise pairs
# filtered out).
RIDER_MOUNT_PAIRS = {
    ('c3170', 'c3180'),  # Albinauric Archer + Wolf
                          # — 5 pairs in m34_10 (dungeon) + m60_42_38_10 (overworld)
    ('c4050', 'c4060'),  # Kaiden Sellsword + Horse
                          # — 3 pairs in m60_44_36_30, m60_44_38_20 (field packs)
    ('c4353', 'c4363'),  # Leyndell Knight + Lordsworn's Horse
                          # — 6 pairs in m48_50, m48_60 (Tree Sentinel arenas).
                          #   These are already preserved via v0.23.03
                          #   (npc=43531110), v0.19.14 (npc=43531400), and
                          #   c4363 source-exclude. The collapse pass below
                          #   skips already-preserved pairs, so this entry is
                          #   inert for the Tree Sentinel arenas in current
                          #   ship. Listed here for completeness in case those
                          #   exclusions are relaxed later (e.g., once an
                          #   EMEVD patch removes the boss-death-event eid
                          #   references on the riders).
    ('c3150', 'c3160'),  # Night's Cavalry + Funeral Steed
                          # — 2 pairs in m46_62 (Night's Cav arena). Both
                          #   c3150 and c3160 are already in
                          #   V3_EXCLUDE_SOURCE_PREFIXES; the collapse pass
                          #   skips them. Listed for completeness.
    ('c5840', 'c5890'),  # Black Knight + Black Knight Horse (MMV/NR mounted pair).
                          # v0.27.45: kept as defensive scaffolding only. c5840 is an
                          # IMPORT with ZERO vanilla MSB Parts (confirmed in spoiler:
                          # 0 c5840 sources, 0 c5890 anywhere), so the Part-to-Part
                          # detector never finds this pair in vanilla maps — the entry
                          # is inert today and would only fire if a future MSB authored
                          # a real adjacent c5840+c5890 pair. NOTE: this is NOT the fix
                          # for the reported "random enemy on a horse" — that was Kaiden
                          # (c4050) / Leyndell Knight (c4353), whose mounts ride in on
                          # the spawn CLUSTER with no mount Part at all, so the detector
                          # cannot help them; they are handled by SOURCE-exclusion in
                          # V3_EXCLUDE_SOURCE_PREFIXES instead. The c5890 target-ban and
                          # the (inert) family swap below are unchanged.
}

# v0.26.15: Mount/rider feature (cut 1 - detection foundation).
# V3_MOUNT_CLASS_POOL: the c-prefixes that can be picked AS a mount once
# the coordinated swap (cut 2) is wired in - i.e. the mount half of every
# RIDER_MOUNT_PAIRS entry (c3160 Funeral Steed, c3180 Albinauric Wolf,
# c4060 Kaiden's Horse, c4363 Lordsworn's Horse). NOTE: deriving this from
# tier=='mount_component' was rejected - that tier also tags riders (c4050
# Kaiden) and other encounter components, so it is NOT a clean "is a
# mount" signal. The RIDER_MOUNT_PAIRS mount-half is exact.
V3_MOUNT_CLASS_POOL = {mount_cp for _rider_cp, mount_cp in RIDER_MOUNT_PAIRS}

# Pilot-active mount/rider pairs. The cut-2 coordinated swap will apply
# ONLY to these. Kaiden Sellsword (c4050) + his Horse (c4060) is the
# canonical pilot. Night's Cavalry (c3150/c3160) and the Lordsworn
# night-boss instance (c4353/c4363) are deliberately excluded - the user
# has said leave those vanilla. Detection still REPORTS those pairs
# (pilot_active=False) so the audit trace is complete.
V3_MOUNT_RIDER_PILOT_PAIRS = {('c4050', 'c4060')}


# v0.27.43: rider<->mount TARGET families. Distinct from RIDER_MOUNT_PAIRS
# (which catalogs the vanilla SOURCE clusters the rando reads): this is the
# set of (rider_cp, mount_cp) that must co-place as a SWAP RESULT so the
# mounted pair is internally consistent. A mismatched mounted pair — a rider
# whose rig/saddle doesn't fit the mount, e.g. a Kaiden Sellsword sitting on
# a Black Knight Horse — hard-CTDs in game (NOT merely cosmetic, as the
# pre-v0.27.43 V3_RIDER_PREFIXES comment assumed). The role gate keeps a
# rider on a rider slot and a mount on a mount slot but does not make a
# cluster's two halves agree; under all-SOTE the per-role pools were
# singletons so they always matched, but in non-SOTE the rider pool is
# {c4050, c5840} while every mount slot is forced to c5890 (c4060 Kaiden's-
# Horse is target-excluded), so ~half of Kaiden clusters produced the
# CTD pairing. Co-placeability (below) restores the singleton invariant in
# every mode. Currently the only swap family is the SoTE Black Knight pair.
# v0.27.44 (Alaric): INERT. Two independent v0.27.44 changes make this family
# dead: (1) c5890 is banned outright (V3_EXCLUDE_TARGET_PREFIXES), so the mount
# half is never placeable and _selected_swap_family always returns None; and
# (2) mounted rider+mount pairs are now PRESERVED VANILLA at the slot level
# (_preserve_detected_rider_mount_pairs feeds the strict (msb, pi) gate), so a
# paired rider/mount returns None long before the rider/mount pool gate that
# would consult this family. Riders themselves (c4050/c5840) are NOT excluded —
# their solo (dismounted) instances randomize like any other enemy. Kept as
# defensive scaffolding only. WARNING: un-banning c5890 without first fixing the
# fabricated-mount runtime CTD will resurrect the crash.
V3_RIDER_MOUNT_TARGET_FAMILIES = {('c5840', 'c5890')}
_RIDER_TO_FAMILY_MOUNT = {r: m for r, m in V3_RIDER_MOUNT_TARGET_FAMILIES}
_MOUNT_TO_FAMILY_RIDER = {m: r for r, m in V3_RIDER_MOUNT_TARGET_FAMILIES}


def _placeable_as_target(cp, prefix_variants, slot_msb_name=None):
    """True if `cp` can be placed as a swap target right now. Mirrors the
    target-side filters pick_target_cp applies before the rider/mount role
    gate: has surviving variants, is not hard-excluded, (under all-SOTE mode)
    is a SOTE chr, and — when slot_msb_name is given — is not map-excluded on
    that slot's map. Used to test whether a rider/mount's family partner is
    itself placeable so the pair can never be left half-swapped."""
    if not cp or cp not in prefix_variants or not prefix_variants[cp]:
        return False
    if cp in V3_EXCLUDE_TARGET_PREFIXES or cp in V3_EXCLUDE_PREFIXES:
        return False
    if V3_SOTE_MODE and V3_SOTE_PREFIXES and cp not in V3_SOTE_PREFIXES:
        return False
    if slot_msb_name:
        for _mp_prefix, _excl in V3_MAP_PREFIX_TARGET_EXCLUDES.items():
            if slot_msb_name.startswith(_mp_prefix) and cp in _excl:
                return False
    return True


def _selected_swap_family(prefix_variants, slot_msb_name=None):
    """Return the single (rider_cp, mount_cp) swap family whose BOTH halves
    are placeable at this slot, or None. The rider-source and mount-source
    gates both consult this so they agree on whether a mounted cluster
    becomes a swap pair or stays vanilla WITHOUT cross-slot coordination —
    the decision depends only on global (map-aware) placeability, never on
    per-slot RNG, so the two adjacent Parts (same map) always reach the same
    verdict. Returns the first complete family; at most one family is ever
    simultaneously placeable in the current roster."""
    for fr, fm in V3_RIDER_MOUNT_TARGET_FAMILIES:
        if (_placeable_as_target(fr, prefix_variants, slot_msb_name)
                and _placeable_as_target(fm, prefix_variants, slot_msb_name)):
            return (fr, fm)
    return None


def _is_part_npc_preserved(po, data):
    """Return True if the Part at offset po has an npc_param in
    V3_EXCLUDE_SOURCE_NPC_PARAMS (i.e., would stay vanilla under the
    npc_param-level source exclusion). Used by the collapse pass to avoid
    double-handling pairs the existing exclusions already cover."""
    if po + PART_OFF_NPC_PARAM + 4 > len(data):
        return False
    npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0]
    return npc in V3_EXCLUDE_SOURCE_NPC_PARAMS


def _detect_mount_rider_slots(data, parts, midx_to_cp,
                              threshold_sq=2.0 * 2.0):
    """v0.26.15: read-only detection of mount/rider Part pairs in one MSB.

    A pair = two Parts whose c-prefixes form a RIDER_MOUNT_PAIRS entry and
    that sit within `threshold_sq` (squared distance) of each other - the
    same proximity the engine uses elsewhere to recognize a mounted pair.
    Each rider is matched to its single nearest eligible mount.

    Returns a list of dicts, one per detected pair:
      {rider_pi, rider_cp, mount_pi, mount_cp, dist, pilot_active}
    `pilot_active` is True when (rider_cp, mount_cp) is in
    V3_MOUNT_RIDER_PILOT_PAIRS - the only pairs the cut-2 coordinated
    swap will touch.

    Detection only: does NOT mutate `data` and does NOT change any swap
    target. Cut 1 runs this purely to populate the spoiler audit trace.
    """
    pids = []
    for pi, po in enumerate(parts['entry_offsets']):
        if po + PART_OFF_POSITION + 12 > len(data):
            continue
        midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        if midx < 0:
            continue
        full_name = midx_to_cp.get(midx, '')
        cp = full_name.split('_')[0] if full_name else ''
        if not cp.startswith('c'):
            continue
        try:
            x, y, z = struct.unpack_from('<fff', data, po + PART_OFF_POSITION)
        except struct.error:
            continue
        if x != x or y != y or z != z:  # NaN
            continue
        pids.append((pi, cp, (x, y, z)))

    rider_to_mount = dict(RIDER_MOUNT_PAIRS)
    paired_mount_pis = set()
    detected = []
    for pi_a, cp_a, pos_a in pids:
        expected_mount_cp = rider_to_mount.get(cp_a)
        if expected_mount_cp is None:
            continue
        best = None  # (dsq, pi_b)
        for pi_b, cp_b, pos_b in pids:
            if pi_b == pi_a or pi_b in paired_mount_pis:
                continue
            if cp_b != expected_mount_cp:
                continue
            dsq = sum((pos_a[k] - pos_b[k]) ** 2 for k in range(3))
            if dsq > threshold_sq:
                continue
            if best is None or dsq < best[0]:
                best = (dsq, pi_b)
        if best is None:
            continue
        paired_mount_pis.add(best[1])
        detected.append({
            'rider_pi': pi_a,
            'rider_cp': cp_a,
            'mount_pi': best[1],
            'mount_cp': expected_mount_cp,
            'dist': round(best[0] ** 0.5, 3),
            'pilot_active': (cp_a, expected_mount_cp) in V3_MOUNT_RIDER_PILOT_PAIRS,
        })
    return detected


def _preserve_detected_rider_mount_pairs(detected, msb_key):
    """v0.27.44 (Alaric): given _detect_mount_rider_slots output for one MSB
    and that MSB's preserve-key base (e.g. 'm60_44_38_20.msb'), add BOTH the
    rider Part and the mount Part of every detected pair to V3_PRESERVE_SLOTS,
    so the strict (msb, pi) preserve gate (see ~line 13180) keeps exactly those
    slots vanilla. This is the pair-LEVEL alternative to a c-prefix-wide source
    exclude: only Parts the detector actually paired are frozen, so a SOLO
    rider (Kaiden / Leyndell Knight / Albinauric Archer with no adjacent mount)
    or a solo mount keeps randomizing. Already-present keys (manual
    V3_PRESERVE_SLOTS entries, HP-bar auto-preserves, role-catalog preserves)
    are left untouched. Returns the set of (msb_key, pi) keys newly added."""
    added = set()
    for d in detected:
        for pi, role, partner_cp in (
                (d['rider_pi'], 'rider', d['mount_cp']),
                (d['mount_pi'], 'mount', d['rider_cp'])):
            key = (msb_key, pi)
            if key in V3_PRESERVE_SLOTS:
                continue
            other = 'mount' if role == 'rider' else 'rider'
            V3_PRESERVE_SLOTS[key] = (
                f"v0.27.44 rider+mount pair: {role} paired with {partner_cp} "
                f"{other} at {d['dist']}u — keep the mounted pair vanilla "
                f"(solo instances still randomize)")
            added.add(key)
    return added


def _collapse_rider_mount_pairs(data, parts, midx_to_cp):
    """v0.23.04: Pre-swap pass. Find rider+mount Part pairs at near-same
    position; for each pair where neither Part is already preserved by
    existing exclusion machinery, zero the mount Part's npc_param so the
    engine's existing `if npc == 0: continue` skip gate suppresses its spawn.
    The rider Part flows through the normal swap path, picking a single
    standalone target that materializes at the rider's original world coords.

    v0.24.101: DISABLED at the call site (see ~line 11063). All 4
    RIDER_MOUNT_PAIRS entries now have both rider and mount c-prefixes
    in V3_EXCLUDE_SOURCE_PREFIXES + V3_EXCLUDE_TARGET_PREFIXES, so the
    pass would have nothing to do anyway. Function kept for reference
    while the visual-mount-leak issue is debugged — see TODO at call
    site for what needs to land before re-enabling.

    Mutates `data` in place. Returns a list of dicts describing each
    collapse for spoiler diagnostic logging:
      [{rider_pi, rider_cp, mount_pi, mount_cp, position}, ...]

    Pairs are skipped (no mutation) when:
      - cprefix combination not in RIDER_MOUNT_PAIRS allowlist,
      - either Part's c-prefix is in V3_EXCLUDE_SOURCE_PREFIXES,
      - either Part's npc_param is in V3_EXCLUDE_SOURCE_NPC_PARAMS,
      - distance between the two Parts exceeds the proximity threshold.

    Position note: an earlier draft also copied the mount's world position
    onto the rider Part (so the substitute would spawn exactly where the
    player approached the mount-rider visual). Vanilla scan showed pair
    distances are 0.00u for 11 of 16 active pairs and ≤1.78u for the rest
    — small enough that the spawn-position drift is imperceptible. Mutating
    the rider's position introduced a worse problem: it could move the
    rider into proximity with unrelated nearby Parts (e.g., a Page or
    Miranda Sprout 1.7u from the wolf in m34_10), inflating
    compute_part_clusters' transitive grouping into spurious 3-Part
    cross-cprefix clusters that fail the cluster-pick path entirely. So
    the position is left at the rider's original anchor.
    """
    PROX_THRESHOLD_SQ = 2.0 * 2.0
    collapsed = []

    pids = []
    for pi, po in enumerate(parts['entry_offsets']):
        if po + PART_OFF_POSITION + 12 > len(data):
            continue
        midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        if midx < 0:
            continue
        full_name = midx_to_cp.get(midx, '')
        cp = full_name.split('_')[0] if full_name else ''
        if not cp.startswith('c'):
            continue
        try:
            x, y, z = struct.unpack_from('<fff', data, po + PART_OFF_POSITION)
            if x != x or y != y or z != z:  # NaN check
                continue
        except struct.error:
            continue
        pids.append((pi, cp, (x, y, z), po))

    rider_to_mount = dict(RIDER_MOUNT_PAIRS)
    paired_mount_pis = set()
    paired_rider_pis = set()
    for pi_a, cp_a, pos_a, po_a in pids:
        if cp_a not in rider_to_mount:
            continue
        if pi_a in paired_rider_pis:
            continue
        expected_mount_cp = rider_to_mount[cp_a]
        best = None  # (dist_sq, pi_b, po_b, pos_b)
        for pi_b, cp_b, pos_b, po_b in pids:
            if pi_b == pi_a or pi_b in paired_mount_pis:
                continue
            if cp_b != expected_mount_cp:
                continue
            dsq = sum((pos_a[k] - pos_b[k]) ** 2 for k in range(3))
            if dsq > PROX_THRESHOLD_SQ:
                continue
            if best is None or dsq < best[0]:
                best = (dsq, pi_b, po_b, pos_b)
        if best is None:
            continue
        _, mount_pi, mount_po, mount_pos = best

        if (cp_a in V3_EXCLUDE_SOURCE_PREFIXES
                or expected_mount_cp in V3_EXCLUDE_SOURCE_PREFIXES):
            continue
        if _is_part_npc_preserved(po_a, data) or _is_part_npc_preserved(mount_po, data):
            continue

        # Mutate: zero mount's npc_param. Rider position stays at original
        # anchor (see docstring on why position copy was dropped).
        struct.pack_into('<I', data, mount_po + PART_OFF_NPC_PARAM, 0)

        collapsed.append({
            'rider_pi': pi_a, 'rider_cp': cp_a,
            'mount_pi': mount_pi, 'mount_cp': expected_mount_cp,
            'rider_position': [round(p, 2) for p in pos_a],
            'mount_position': [round(p, 2) for p in mount_pos],
        })
        paired_mount_pis.add(mount_pi)
        paired_rider_pis.add(pi_a)

    return collapsed



# but allowed as sources (their slots get randomized normally).
# Use this for "fragment" or "mount-component" models that only function
# correctly when paired with a rider in a cluster — placed standalone, they
# behave like inert objects with no combat AI.
# v0.28.x TODO Step 3: editorial base sourced from
# data/placement_budget.json at module-load. load_data() still
# folds in tier-derived adds (cinematic, empty-variant, tag-but-
# no-variant) via _assemble_exclude_target_prefixes() and unions
# in pack-loader exclude_target_adds — all idempotent on the
# JSON-pre-loaded post-load snapshot.
#
# The set is mutated by _load_missing_chr_files() at ~L1832
# (module-import time) via `|=`; that mutation lands on the
# empty placeholder here, then the JSON loader at end-of-module
# REPLACES with the post-load snapshot which already includes the
# missing-chr entries. Net effect: identity.
#
# Historical curation (preserved in git history): ~45 hand-picked
# editorial bans across v0.20.x → v0.28.x — mount components
# (c5890, c4060, c5090), cinematic/scripted chrs, AI-broken DLC
# imports, fabricated-asset MMV chrs, and per-version ban additions
# (c5810, c4140, c6201, etc.). The JSON's `exclude` field per chr
# is the current source; the JSON's `exclude_reason` field captures
# the editorial rationale (populated lazily as entries are touched).
V3_EXCLUDE_TARGET_PREFIXES: set[str] = set()


# v0.26.x: drop the now-dead cap entries for c4910 and c5010 below. The
# excludes above shadow these caps so they can't fire; leaving them as
# dead code would surface in dev/audit_placement_budget_consistency.py
# as HIGH-severity findings. Comments retained in-place for git-history
# legibility — the cap-removal lives in V3_UNIQUE_TARGET_CAPS itself.


def _load_missing_chr_files():
    """v0.24.37: load data/nr_missing_chr_files.json and merge the
    c-prefixes into V3_EXCLUDE_TARGET_PREFIXES.

    Data-file representation of chrs that should never be picked as
    targets. Two categories (v0.24.39 schema v2):
      - missing_chrs: NO .chrbnd asset files anywhere → invisible/missing
      - broken_runtime_chrs: have chr files but show in-game freeze/
        invisible symptoms (per playtest reports). Includes specific
        _cluster_only chrs that froze (e.g., small Oracle Envoy c3610
        at standalone slots) and post_dlc_dump chrs with no runtime
        characterization (no locomotion/size_class).

    The hard-coded missing_chrs entries inside V3_EXCLUDE_TARGET_PREFIXES
    above seed the set at import time so pre-load_data() queries see
    them. This loader merges any additional entries from the JSON file
    (the data file is the source of truth — when the asset-import tool
    finds new misses or playtest reports identify broken chrs, only the
    JSON needs updating; this loader picks them up).
    """
    global V3_EXCLUDE_TARGET_PREFIXES
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
    if not os.path.isfile(path):
        return  # Optional file; placeholders above provide fallback
    try:
        with open(path, encoding='utf-8') as _f:
            _data = json.load(_f)
    except (json.JSONDecodeError, OSError):
        return
    _new_cps = set()
    # missing_chrs: chrs with no .chrbnd asset files (v0.24.36+)
    for entry in _data.get('missing_chrs', []):
        cp = entry.get('c_prefix')
        if cp: _new_cps.add(cp)
    # broken_runtime_chrs: chrs with files but in-game freeze/invisible
    # symptoms confirmed in playtest (v0.24.39+)
    for entry in _data.get('broken_runtime_chrs', []):
        cp = entry.get('c_prefix')
        if cp: _new_cps.add(cp)
    V3_EXCLUDE_TARGET_PREFIXES |= _new_cps


_load_missing_chr_files()

# C-prefixes that have heritage tag/roster data but no actual MSB Part
# placements in vanilla NR, AND show symptoms of broken model/animation
# support (chrbnd files may be incomplete in NR even if NpcParam exists).
# Symptom: hard freeze when entering the cell containing such an enemy.
#
# This list is curated from in-game freeze reports — start small, expand
# only when freezes are actually observed. Some "ghost" c-prefixes (no MSB
# placement but a known NR encounter via runtime spawning, e.g. Mohg,
# Chief Bloodfiend, Dancing Lion) work fine and are NOT in this set —
# blanket-excluding all ghosts shrinks compat pools too aggressively
# (e.g. would drop Margit from 3 viable targets to 1).
#
# Confirmed-broken (4laric, April 2026 — tower encounter freezes):
#   c2040 Juvenile Scholar
#
# v0.24.88-patch10: speculative ghost-excludes lifted.
#   The original set had six additional entries (c5240/c5241/c5311/c5312/
#   c5750/c5751) added by shape/vibe association with casual phrases the
#   user used describing the April 2026 freeze. None were individually
#   tested. Audit found 25 same-profile chrs working fine (heritage/
#   post_dlc, S/M humanoid or quadruped, zero MSB placements), so the
#   "ghost profile" is not the actual discriminator. Plus all six were
#   already flagged in V3_MERCHANT_MODEL_AI_BROKEN_OK's deferred block
#   as "pending playtest confirmation — need empirical confirmation that
#   the exclusion is AI-driven, not model-asset-driven." Lifted to give
#   them placement opportunity. If any freezes in playtest, add back with
#   a specific (seed, msb, pi) citation.
#
# Lifted v0.24.88-patch10:
#   c5240, c5241 Commoner / Commoner (Pot)
#   c5750, c5751 Living Jar / Living Jar Warrior
#   c5311, c5312 Inquisitor (Candles/Staff)
#
# Re-add individual prefixes here only after a CONFIRMED freeze in
# playtest. The speculative-by-vibe pattern is exactly what got us
# into the audit-deficit position in the first place.
#
# v0.28.x TODO Step 3: ghost_exclude membership sourced from
# data/placement_budget.json at module-load. Per-chr `ghost_exclude:
# true` flags + the editorial `rationale` / `since` fields per entry
# live in the JSON. Currently 1 entry: c2040 Juvenile Scholar.
V3_GHOST_EXCLUDE_TARGET_PREFIXES: set[str] = set()

# v0.20.20: per-map-prefix target excludes. dict[prefix → set[c-prefix]].
# Slot's MSB basename is checked startswith() against each prefix; if it
# matches, the corresponding c-prefixes are removed from that slot's
# target pool. Lets us exclude a c-prefix from one map range without
# affecting placements at others.
#
# Initial entry: in m60_xx (Limveld), block the Maris-cluster c-prefixes
# (Tendril c5110, Jellyfish c4181, Sprout c4481, Bat-pair c4200/c4201,
# Oracle Envoys c3610/c3620). Limveld is procedurally composed at session
# start and rolls a "night path" — the Maris path runs an event chain
# that references these c-prefixes by class. With the v0.20.x engine
# scattering hundreds of duplicate placements across m60_xx chunks, the
# Maris path's chain breaks at MSB-load time. Confirmed playtest: 4laric
# CTDed twice on launch into Limveld with non-enhanced Maris path
# selected, while the same engine config worked fine on other paths.
# The 173 Maris-cluster TARGET placements in m60_xx in seed 42 was the
# fingerprint.
#
# Restricts these c-prefixes to their natural Heritage / dedicated arena
# habitats (m32_10, m34_xx, m46_xx, m47_xx, m48/m49_xx) where the Maris
# event chain doesn't fire.
# v0.28.x TODO Step 3: per-map-prefix exclusions sourced from
# data/placement_budget.json at module-load. The JSON stores
# `map_excludes: [m60_, ...]` per chr; build_static_overrides
# inverts that into the {map_prefix: {chr_prefixes}} shape this
# constant uses. Historical entries (v0.20.x Limveld Maris-cluster
# CTDs, m32_/m43_/m46_/m47_ Miranda Sprout bans) preserved in git;
# current entries: m60_ (5 chrs), m32_ / m43_ / m46_ / m47_ (1 each).
V3_MAP_PREFIX_TARGET_EXCLUDES: dict[str, set[str]] = {}

# All heritage-imported c-prefixes — chrs whose chrbnd assets the heritage_pack
# tool installs into the local NR install. These are NOT shipped with vanilla
# NR; they're imported from base Elden Ring at heritage-pack-install time.
#
# In multiplayer, the host placing a heritage chr CTDs any client that doesn't
# have the heritage pack installed locally. The engine has no fallback — if
# the chrbnd is missing on the client, it crashes when preloading the cell.
#
# When the rando is run in multiplayer-safe mode, the full heritage set is
# added to the target-exclusion set, restricting placements to only c-prefixes
# every vanilla NR install has on disk.
#
# This list is the union of:
#   - 47 entries from heritage_pack's comprehensive import plan (May 2026)
#   - 12 c2xxx ER NB-tier bosses authored in er_heritage_imports.json
#     (v0.23.11 — same coop-CTD risk profile, same gating treatment)
# If new entries are added (heritage_pack updates, future er_heritage_v2 batch),
# extend this list accordingly.
V3_HERITAGE_ALL_PREFIXES = {
    'c2040',  # Juvenile Scholar
    'c2272',  # Giant Black Crab
    'c3061',  # Giant Beast Skeleton
    'c3070',  # Dominula Celebrant
    'c3330',  # Giant Silver Tear (Unscaled)
    'c3510',  # Skeleton (Sword and Shield)
    'c3730',  # Graven School
    'c3750',  # Clayman - Spear
    'c3800',  # Cleanrot Knight
    'c3860',  # Avionette
    'c4210',  # Warhawk
    'c4220',  # Giant Land Octopus
    'c4341',  # Thin Mad Pumpkin Head
    'c4385',  # Disciple of Rot
    'c4420',  # Giant Crayfish
    'c4561',  # Bloodbane Giant Crow
    # v0.23.72-late: c4602 Snowfield Troll was briefly banned here at the
    # c-prefix level after a user CTD in playtest (Sentient Pest seed
    # 35300). Demoted to variant-level: the Duo variant (npc=46020030)
    # carries co-AI for a paired Mountaintops encounter and was placed
    # at non-duo slots in this seed (m34_10 pi=13 replacing Albinauric
    # Archer; m46_50 pi=26 shared-position placeholder slot). Suspect failure
    # mode is "missing partner" — Duo AI waits for or signals a peer
    # via EMEVD that doesn't exist in randomized non-duo placements.
    # Regular Mountaintop variant (npc=46020050) is allowed; the Duo
    # variant alone is excluded via V3_AVOID_VARIANT_NPC_IDS — see the
    # 46020030 entry there.
    'c4603',  # Stonedigger Troll — heritage import (chrbnd present in
              # NR regulation but 0 vanilla MSB placements; only one
              # variant exists, npc=46030000). Originally banned with
              # no version stamp or rationale comment. v0.23.72-late:
              # user audit considered un-banning to probe (parallel to
              # c8300/c4720 vindications) but elected to keep the ban —
              # troll-shape budget is already covered by c4602 Snowfield
              # Troll (NR-native, 8 variants, full reward chain). Low
              # value to add a single-variant heritage chr in the same
              # role-bucket, especially one with the c5820/c5250-class
              # phase-transition risk profile common to empirically-
              # detected heritage imports. If c4602 ever gets fully
              # banned (e.g. if 46020050 also CTDs in future playtest),
              # revisit c4603 as a fallback.
    'c4800',  # Mohg- the Omen
    'c4820',  # Omenkiller
    'c5010',  # Golden Hippopotamus
    'c5040',  # Curseblade
    'c5070',  # Death Knight
    'c5080',  # Bloodfiend
    'c5081',  # Chief Bloodfiend
    'c5090',  # Gravebird
    'c5160',  # Fire Knight
    # c5190/c5192/c5193 Spider Scorpion — removed from V3_HERITAGE_ALL_PREFIXES
    #   v0.27.36 (Alaric direction). Re-enabled for SOTE-mode placement.
    'c5210',  # Divine Beast Dancing Lion
    'c5240',  # Commoner (Pot)
    'c5241',  # Commoner
    'c5250',  # Horned Warrior
    'c5311',  # Inquisitor (Candles)
    'c5312',  # Inquisitor (Staff)
    'c5320',  # Fat Inquisitor
    'c5522',  # Stray
    'c5523',  # Stray
    'c5750',  # Living Jar Warrior
    'c5751',  # Living Jar
    'c5820',  # Great Red Bear
    'c5830',  # Messmer Soldier
    'c5860',  # Ghostflame Dragon
    'c5870',  # Imp (Lion Head)
    'c5900',  # Man-Fly
    'c6031',  # Bear
    'c6060',  # Goat
    # v0.23.11: ER heritage v1 batch — chr files ship in vanilla ER but NOT in
    # vanilla NR. Same coop-CTD risk profile as the heritage_pack chrs above:
    # host placing one of these CTDs any client without the chr files locally.
    # Technically not heritage_pack-imported (these are authored from scratch
    # via template-inheritance, see er_heritage_imports.json) — but for the
    # purposes of multiplayer_safe gating, "requires external chr assets" is
    # the same property. Safer to gate together than separately.
    'c2010',  # Margit, the Fell Omen
    'c2030',  # Rennala (Phase 1)
    'c2031',  # Rennala (Phase 2)
    'c2050',  # Radagon
    'c2060',  # Mohg, Lord of Blood
    'c2110',  # Maliketh
    'c2120',  # Malenia
    'c2131',  # Morgott (P2)
    'c2160',  # Astel, Naturalborn of the Void
    'c2190',  # Godrick the Grafted
    'c2191',  # Godrick (Phase 2)
    'c2200',  # Godfrey / Hoarah Loux
}


# v0.24.20: STRICT MP-SAFE BLOCKLIST — derived at load_data time from
# nr_enemy_tags.json `_source` tagging. This replaces the hand-curated
# V3_HERITAGE_ALL_PREFIXES as the gate the multiplayer_safe flag consults.
#
# Background: V3_HERITAGE_ALL_PREFIXES was an exclusion list that needed
# manual extension every time a new import pack landed (heritage_pack v2,
# er_heritage, bfer v1/v2, mmv, post_dlc_dump). The hardcoded set rotted —
# in seed 232667 (v0.24.19) mp_safe ON, 24 placements leaked through across
# 4 distinct buckets: c4352 Cuckoo Knight (heritage_pack-listed but missing
# from V3_HERITAGE_ALL_PREFIXES), c5651/c5130/c6210/c4720/c5840/c5880/c5740
# (mmv_imports references, no gate at all), c4801 Lord of Blood Spear
# (`_source: post_dlc_dump`, a category the filter didn't know about).
#
# Fix: allow-list approach. V3_VANILLA_NR_SOURCES enumerates the `_source`
# tag values that count as vanilla NR. Anything in nr_enemy_tags.json with
# a `_source` OUTSIDE that set — or with no `_source` at all — gets dropped
# into V3_MP_SAFE_BLOCKLIST and excluded by the multiplayer_safe gate.
#
# Why allow-list, not exclude-list: the failure mode is "new import pack
# adds c-prefixes the gate doesn't know about." An exclude-list defaults
# to UNSAFE on unknown sources; an allow-list defaults to SAFE. With this
# gate, the next import pack just needs to land its tags with a non-vanilla
# `_source` (the pack loaders already do this by convention) and the gate
# auto-extends.
#
# Strict policy: nr_placed only. (Historically nr_placed + script_spawn, but
# the v0.26.x reclassification pass moved every script_spawn chr to nr_placed
# after a byte-level MSB audit confirmed real MSB placements — the 12
# ex-script_spawn chrs c4670/c4690 + c7700-c7920 DS-ports are all nr_placed
# now — so the script_spawn arm matched nothing and was dropped in v0.27.x.)
# DLC chrs (`_source: post_dlc_dump`) are NOT included — strict mode
# treats Forsaken Hollows as not-everyone-has-it for coop safety.
#
# V3_HERITAGE_ALL_PREFIXES is kept for its other semantic uses (the
# boss-tier detector at line ~3761 uses it to identify heritage_pack
# mid-bosses by hp_median, which is a heritage-specific signal — not the
# same as the broader MP-safe gate).
V3_VANILLA_NR_SOURCES = frozenset({'nr_placed'})
V3_MP_SAFE_BLOCKLIST = set()  # populated at end of load_data()


# v0.23.71: VANILLA-NR HERITAGE AI BUGS — documentation only.
#
# Some heritage chrs in V3_HERITAGE_ALL_PREFIXES have AI behavior that
# only works at their vanilla NR anchor slot. When the rando places
# them at any other slot, they exhibit broken-AI symptoms: idle pose
# never breaks into combat, phase transitions don't fire, the chr
# stands frozen until aggro'd from a specific direction, etc.
#
# === ROOT CAUSE (resolved v0.23.72-late investigation) ===
#
# Heritage_pack initially shipped chr visual + behavior assets
# (chrbnd, anibnd, behbnd, texbnd) for these chrs but did NOT ship
# their ER AI scripts (NNNNNN_battle.luabnd.dcx). The .luabnd files
# weren't known to the heritage_pack maintainer at original authoring
# time. Without the Lua brain, these chrs ran on .behbnd (Havok
# behavior tree) alone — which is enough to drive animations and
# basic combat reactions, but doesn't supply:
#   - Phase-transition state latching (the IsInterupt + HasSpecialEffectId
#     handlers that prevent re-firing the HP-threshold trigger)
#   - Move-selection logic (which attack to use when)
#   - Inter-phase cooldown management (SetCoolTime calls)
#
# Symptom: chr enters phase transition correctly but post-transition
# AI cannot select varied moves or properly latch the new phase state,
# so it repeats whichever attack the behbnd selects by default (often
# the phase signature attack itself).
#
# === FIX (upstream in heritage_pack) ===
#
# Heritage_pack v-next imports the missing chr AI scripts from ER:
#   c5210: 521000_battle.luabnd → fixes Dancing Lion (confirmed working)
#   c5820: 582000_battle.luabnd → fixes Great Red Bear (theoretical)
#   c5250: 525000_battle.luabnd + 525010_battle.luabnd → fixes Horned Warrior
#
# Plus ~23 additional heritage chrs with the same latent issue
# (full list in heritage_pack_ai_audit.md from v0.23.72-late session).
# NR's aicommon.luabnd is compatible with ER chr scripts (validated
# in c5210 playtest — no script load errors, no missing-function
# fallbacks). The bulk import is upstream-safe.
#
# === IMPLICATIONS FOR THE RANDO ===
#
# Once heritage_pack v-next ships these scripts, the SENSITIVE gating
# at V3_FRAGILE_SENSITIVE_TARGETS becomes less load-bearing for these
# specific chrs — they should function correctly at any boss-tier slot
# regardless of arena-specific EMEVD scaffolding. We keep the SENSITIVE
# entries in place as defensive measure (XXL geometry, arena flatness,
# etc. concerns are independent of AI), but the "phase-transition loop"
# specific failure mode listed here is resolved upstream.
#
# The boss_clear_watchdog EMEVD patch (emevd_patch.py, 300s force-
# resolve) was authored as recovery for this specific bug class. It
# remains active as general fault tolerance — useful for any heritage
# chr the upstream fix may have missed, or future BFER imports with
# similar gaps. Low cost to keep, real value when an edge case slips.
#
# === ORIGINAL DIAGNOSIS (PRESERVED FOR PROVENANCE) ===
#
# Pre-fix understanding: the bug was attributed to vanilla NR's data
# layout — specifically that NpcThinkParam and/or EMEVD events were
# authored against vanilla anchor slot coordinates/entity_ids, and
# would fail at non-anchor placements. That framing was WRONG. The
# bug was actually heritage_pack-side: missing AI scripts, not NR
# scaffolding mismatches. The pre-fix annotation that read
# "we can't fix it without rewriting NpcThinkParam or providing a
# generic EMEVD intro shim, both outside the rando's scope" was
# misleading — the fix is none of those things, it's just importing
# the .luabnd file. Documented here so future investigations don't
# re-tread the same wrong-tree barking.
#
# === STILL-OPEN CASES (NOT YET CONFIRMED AS SAME BUG CLASS) ===
#
# These were originally listed as "suspected" in the same bug class.
# v0.23.72-late+ investigation: NONE of them are the same bug class.
# Each shipped its base AI script in vanilla NR — the "idle frozen" or
# "doesn't transition" reports must have a different root cause, likely
# EMEVD intro-trigger gating that only fires at vanilla anchor slots.
#
#   c4980 — Death Rite Bird. 498000_battle.luabnd.dcx IS shipped by
#           vanilla NR (and by ER). AI is fully loaded. Idle-frozen at
#           non-anchor locations is almost certainly EMEVD-side, not
#           script-side: the chr's wake-up depends on a specific EMEVD
#           event that only exists at its vanilla anchor slots.
#           Byte-size evidence (v0.23.72-late investigation):
#             ER uncompressed:  32,048 bytes
#             NR uncompressed:  39,040 bytes  (NR is +22% larger)
#           NR doesn't just SHIP this script — it enhanced it. The chr
#           has MORE AI than the ER version, not less. Confirms the bug
#           is environmental (EMEVD/slot context), not script-level.
#
#   c3252 — Royal Carian Knight. 325200_battle.luabnd.dcx is shipped by
#           vanilla NR, AND heritage_pack already adds 325210_battle.luabnd
#           (its phase-2 script). The chr has both phases of AI loaded.
#           This is actually a hidden c5210-class fix heritage_pack
#           applied for vanilla NR chrs c3251 and c3252 (both had phase-2
#           scripts missing from vanilla NR, both patched in heritage_pack).
#           Same EMEVD-gating hypothesis as c4980.
#           Byte-size evidence (v0.23.72-late investigation):
#             ER uncompressed:  58,400 bytes
#             NR uncompressed:  58,432 bytes  (essentially identical, +0.05%)
#           NR ships ER's script verbatim. Reinforces that the bug is
#           environmental, not script-level.
#
#   c7520/c7521 — Gnoster + Moth (Sentient Pest). 752000_battle.luabnd.dcx
#           is shipped by vanilla NR. ER doesn't have this script at all —
#           these are NR-original chrs (or BFER-imported predating heritage_pack).
#           The Moth-depends-on-Gnoster paired behavior is EMEVD-orchestrated,
#           not script-level. Different bug class entirely.
#
# The bulk-import flow won't fix any of these — they need EMEVD-side
# intervention, not chr/script asset imports.
#
# The set below is kept for historical tracking; once heritage_pack
# v-next ships, the entries become observational ("this chr had the
# bug at one point, now resolved upstream") rather than gating signals.
V3_HERITAGE_AI_KNOWN_ISSUES = frozenset({
    'c5820',  # Great Red Bear — resolved upstream in heritage_pack v-next
    'c5250',  # Horned Warrior — resolved upstream in heritage_pack v-next
    'c5210',  # Divine Beast Dancing Lion — FIX VALIDATED v0.23.72-late
              # (heritage_pack + 521000_battle.luabnd → phase transition + deathblight moveset working)
})


# v0.23.31: OOPS_ALL_NB_TARGET_CP — force every Night Boss slot to a
# specific c-prefix while leaving non-NB slots on the normal random
# swap path. Sibling of `oops_all_target_cp` (which forces ALL slots),
# but scoped to NB anchors via V3_NIGHT_BOSS_NAME_MARKERS detection on
# the source variant's variant_name. NR has ~22 dedicated NB anchor slots
# spread across the maps.
#
# When set: every slot whose vanilla variant name carries an NB marker
# ('Night Boss', 'Field Boss', 'Castle Boss', 'Fort Boss', 'Ruins
# Boss', 'Remembrance', '(Crater)', '(Noklateo)') gets forced to this
# c-prefix. Variant within the c-prefix is rolled per-slot via
# pick_variant_for_tier so each NB slot gets a different variant.
#
# When None: feature disabled, normal NB behavior.
#
# pick_variant_for_tier is called with boss_tier=True so the boss-tier
# variants are preferred.
#
# Marker set: defaults to V3_NIGHT_BOSS_NAME_MARKERS (broad — 89 slots
# in current data: Night Boss + Field Boss + Castle Boss + Fort Boss
# + Ruins Boss + Remembrance + (Crater) + (Noklateo)). For the strict
# interpretation (only the 33 Night Boss anchor slots that drop at
# day-end), set OOPS_ALL_NB_USE_STRICT_MARKERS=True below.
OOPS_ALL_NB_TARGET_CP = None  # v0.23.39: feature now wired through GUI/kwargs
# v0.23.38: replaces the old OOPS_ALL_NB_USE_STRICT_MARKERS bool with a
# tri-valued scope selector. 'broad' (default) = NB/Field/Castle Boss/Fort
# Boss/Ruins Boss/Crater/Noklateo/Remembrance, ~39 slots in a typical seed.
# 'strict' = literal 'Night Boss' anchors only, ~22 slots. 'extended' =
# broad + Castle-/Encampment-/Evergaol/Mountaintop Ruins/Duo Night Boss,
# ~51 slots (catches the Day-2 Castle interior, Encampment towers, and
# Evergaol POIs the broad set misses). Use 'extended' when probing
# CTD-on-castle scenarios.
# v0.23.39: GUI passes scope as a kwarg; this module global is the
# fallback for direct-CLI / source-edit workflows.
OOPS_ALL_NB_MARKER_SCOPE = 'broad'  # 'strict' | 'broad' | 'extended'
# Backward compat: keep the old bool name as an alias readers might
# reference. True == 'strict', False == 'broad'. Tools/spoilers still
# emit it for diagnostic continuity.
OOPS_ALL_NB_USE_STRICT_MARKERS = (OOPS_ALL_NB_MARKER_SCOPE == 'strict')


# v0.27.13: ALL-SOTE MODE
# ----------------------
# When V3_SOTE_MODE is True, pick_target_cp intersects every swap
# target pool with V3_SOTE_PREFIXES — the set of chrs whose tag carries
# origin_game == 'SoTE'. Every placement becomes a Shadow-of-the-
# Erdtree enemy; the tier-preserve filter still runs, so SOTE bosses
# land at boss slots and SOTE field enemies at field slots, with the
# usual empty-pool fallthrough leaving a slot vanilla only when no
# SOTE chr survives the downstream gates (e.g. flier-required slots
# with no SOTE flier).
#
# The SOTE set is small (~26 chrs: 10 MMV boss ports + 16 heritage
# field enemies), so a run repeats the same chrs heavily. That is the
# intended feel — per Alaric, SOTE mode runs with NO caps: the
# reservation early-return and the cap-exhaustion filter in
# pick_target_cp are both bypassed when V3_SOTE_MODE is set, so a SOTE
# chr can fill any number of slots. V3_UNIQUE_TARGET_CAPS /
# V3_RESERVATION_FLOORS are left intact (untouched) — the picker just
# ignores them for the duration of a SOTE run.
#
# HARD DEPENDENCY: the SOTE bosses are MMV imports and the SOTE field
# enemies are heritage chrs — both need their chr/anibnd (and MMV its
# regulation) assets staged. An all-SOTE run on a base install will
# CTD. Treat this like multiplayer_safe: only enable when the asset
# packs are confirmed present.
#
# V3_SOTE_PREFIXES is populated at the end of load_data() from the
# fully-merged tag DB; it stays empty until load_data() runs.
V3_SOTE_MODE = False
V3_SOTE_PREFIXES = set()


# v0.27.13: RIDER / MOUNT pool restriction.
# ----------------------------------------
# A rider+mount encounter (Kaiden Sellsword on his Horse) is two
# proximate Parts. Rather than the full cross-slot-atomicity feature
# (see dev/PAIR_SWAP_SCOPING.md), this is the lightweight approach
# Alaric chose: tag each chr's role and restrict the per-slot pool by
# role. A slot whose vanilla occupant is a `rider` only draws riders;
# a `mount` slot only draws mounts. Same mechanism as V3_SOTE_PREFIXES
# — a pool intersection in pick_target_cp, no new pre-pass.
#
# This does NOT enforce that the rider's pick and the mount's pick
# agree (true cross-slot atomicity). It does not need to *right now*:
# with the SOTE filter active the mount pool is exactly {c5890} Black
# Knight Horse — a one-element pool cannot produce a mismatched draw.
# The only base-ER pair that could mismatch destructively is the
# Albinauric Archer + Wolf (a non-horse mount); c3170/c3180 are hard-
# excluded below so that case is removed entirely. Every remaining
# mount is a horse, so a non-SOTE mismatch is at worst "knight on a
# different horse" — cosmetic, no broken moveset.
#
# !! FUTURE HAZARD !!  This correctness argument holds ONLY while the
# SOTE mount pool has <=1 member. The day a second SOTE rider+mount
# pair is imported, an independent draw CAN mismatch them, and the
# full pair-swap atomicity work (PAIR_SWAP_SCOPING.md) becomes
# necessary. Populated at the end of load_data() from the mount_role
# tag.
V3_RIDER_PREFIXES = set()
V3_MOUNT_PREFIXES = set()


# Variant-level filter: drop event-triggered variants from per-prefix variant lists.
V3_VARIANT_TRIGGER_MARKERS = [
    'Night Horde','Prelude','Sparring','Dummy','Unlock Fight',
    'Cutscene','Story','Hidden','Trigger',
    # v0.24.95-patch16: 'Unused' marker added after c5840 Black Knight
    # diagnostic. MMV's c5840 variant 58400000 is the only NpcParam entry
    # with '(Unused)' in name across the entire regulation. Deliberately
    # non-functional — chr loads visually but has no AI behavior. Was
    # being picked by pick_variant_for_tier because no filter caught the
    # 'Unused' marker. Same filter pattern as 'Prelude' / 'Cutscene'.
    'Unused',
]

# v0.23.72: PROBE_TARGET_VARIANT — reusable boss-probe helper for the
# MMV walkthrough campaign. Pairs with OOPS_ALL_NB_TARGET_CP (GUI: "Oops!
# All NB" mode). Set to a (c_prefix, target_npc_param_id) tuple to force
# pick_variant_for_tier to land on that specific variant at every NB
# slot.
#
# How it works at load time:
#   - REMOVE target_npc_param_id from V3_AVOID_VARIANT_NPC_IDS (so the
#     target is eligible even if previously banned as a suspect)
#   - ADD every OTHER variant of the same c-prefix to V3_AVOID_VARIANT_
#     NPC_IDS (so pick_variant_for_tier can only pick the target)
#
# Workflow per probe iteration:
#   1. PROBE_TARGET_VARIANT = ('c6200', 62000001)  # P1 Gael
#   2. GUI: run mode = "Oops! All NB", target = c-prefix from step 1,
#      scope = 'extended' for max coverage (~51 boss-tier slots)
#   3. Run, playtest, observe at NB slots
#   4. After the probe: set PROBE_TARGET_VARIANT = None to restore the
#      v0.23.71 V3_AVOID_VARIANT_NPC_IDS state (P1 Gael re-banned, etc.)
#
# Set to None to disable (normal randomizer behavior).
PROBE_TARGET_VARIANT = None  # e.g. ('c6200', 62000001) for P1 Gael probe


# v0.20.86: variant-level NPC param IDs to avoid in pick_variant_for_tier.
# These are variants that pick_variant_for_tier would otherwise select but
# which produce visually broken / undesired results when placed at non-vanilla
# slots. Most common case: spirit/ghost-rendered variants where the npc_param
# carries a translucency / spectral rendering flag (an `appearanceType` or
# `disable_renderer_xxx` field that we don't currently extract).
#
# Mechanism: pick_variant_for_tier prefers non-avoid-listed variants at every
# tier, but falls back to the avoid-listed if no alternatives exist for the
# tier (avoids unplaceability). So a c-prefix with multiple variants, only
# some spirit-render, gets steered toward the non-spirit ones automatically.
#
# Detection notes:
#   - No automatic detection from current data — variant names are
#     inconsistent ((Ruins) for c7100 is spirit, but (Ruins) elsewhere is
#     not). The "(Spirit)" suffix is sometimes explicit but not always.
#   - Reliable detection would need npc_param data extraction (a future
#     tooling pass): scan FromSoft NPC param entries for translucency
#     fields and map them back to npc_param_id.
#   - Manual curation via this set is the practical option until then —
#     extend as new ghost-renders are observed in playtest.
#
# v0.20.86 initial entries:
#   c7100 npc=71000110 'Ancient Hero (Ruins)' — observed at "Troll (Mine)"
#     slot rendering as a translucent ghost-knight. The (Field Boss) variant
#     (npc=71000010) is the regular non-spirit appearance for the same chr.
V3_AVOID_VARIANT_NPC_IDS = {
    71000110,  # c7100 Ancient Hero (Ruins) — spirit/ghost render
    # v0.23.17 + v0.23.20 (orig.) — scripted/cinematic/ghost-recall variant
    # IDs for multi-phase bosses, hardcoded to load at 1hp / non-combat
    # state when placed at a slot whose EMEVD doesn't run their phase-
    # transition cutscene. Originally surfaced via BFER playtests.
    #
    # v0.26.12 BFER cleanup: 19 of the original 24 IDs were BFER-only —
    # absent from vanilla NR's NpcParam, from nr_enemy_roster.json, AND
    # from mmv_imports.json — so they matched nothing once the BFER
    # integration was retired, and were removed (13 Margit c2010 9xxx
    # variants, c2110 Maliketh statue 21101073, c2180 Melina 21809000,
    # c5051 Midra statue 50510002, 3 Margit c2010 8xxx ghost-recall).
    #
    # The 5 IDs BELOW survived the cull: they are ALSO shipped by
    # mmv_imports.json (MMV ports c2110 / c2120 / c2031 from vanilla ER
    # using the same NpcParam IDs), so they remain live whenever MMV is
    # in the user's profile. Removing them would let MMV's 1hp scripted
    # Maliketh / Malenia / Rennala variants reach the placement pool.
    21109000, 21109042,  # c2110 Maliketh — scripted / Beast Clergyman phase
    21209000,            # c2120 Malenia — phase-locked (Blade → Goddess of Rot)
    20310024, 20310124,  # c2031 Rennala P2 — cocoon / cocoon-derived 1hp forms

    # v0.23.24: bulk team=26 exclusions from vanilla NR NpcParam.csv audit.
    # Diagnosed via user playtest seed 713344 (engine v0.23.22): a c2500
    # Crucible Knight (npc_param 25008100) was placed at an Abductor Virgin
    # slot (m30_00_00_00 pi=36) and rendered as a copper-armored figure that
    # ignored the player. NpcParam dump showed teamType=26 — the non-
    # aggressive/cinematic team used by grace-replay variants, decorations,
    # and friendly NPCs. Audit found 81 team=26 entries across 35 c-prefixes.
    # All added below, grouped by c-prefix.
    #
    # Coverage check: only 9 c-prefixes lose all variants (c4492, c52101,
    # c52102, c52107, c52309, c52312, c52313, c8910, c8911) — those are
    # entirely-cinematic c-prefixes; the soft-fallback in
    # pick_variant_for_tier handles them correctly (returns the original
    # variant pool if all variants are avoid-listed).
    #
    # team=26 is ADDITIONAL coverage: it catches non-aggressive scripted
    # variants that carry the teamType=26 marker in vanilla NR's own
    # NpcParam, complementing the per-boss scripted/phase-lock IDs above.
    # Merchant code path (apply_merchant_model_swaps) writes only MODEL_INDEX,
    # never NPC_PARAM, so excluding 32000000 / 32100000 etc from variant
    # selection doesn't break merchants.
    #
    # c2500 Crucible Knight (Unscaled) — user-reported:
    25008000, 25008100,
    # c3170 Albinauric Archer:
    31709000,
    # c3180 Albinauric Wolfback:
    31809000,
    # c3200 Nomadic Merchant base + 11 grace-recall variants:
    32000000, 32008900, 32009000, 32009100, 32009200, 32009210,
    32009300, 32009400, 32009500, 32009600, 32009700, 32009800,
    # c3210 (merchant family, parallel to c3200):
    32100000, 32108900, 32109000, 32109010, 32109100, 32109200,
    32109300, 32109400, 32109500, 32109600, 32109700, 32109800,
    # c3400 Grave Warden Duelist:
    34000900,
    # c3450 Misbegotten:
    34509000, 34509100,
    # c3451 Scaly Misbegotten:
    34510100, 34519000,
    # c3660 Commoner:
    36609200,
    # c3670 Aged Albinauric:
    # v0.27.2: 36708100 REMOVED from this list per Alaric direction
    # (98-seed sim 2026-05-26 — Aged Albinauric placed 0× because its
    # only named variant was avoid-listed). 36708100 'Aged Albinauric
    # (Scholar Remembrance)' is the sole canonical variant (sample_maps
    # ['m10_00_00_00'] — vanilla NR places it) and the only one with a
    # non-empty variant_name; the other three c3670 ids are empty-name
    # placeholders already culled by the empty-name filter upstream.
    # The v0.23.24 avoid-add justified 36708100 as a 'team=26 cinematic'
    # variant, but the post-DLC dump and roster scrape since then show
    # it as a real placed enemy. CAVEAT: the roster entry carries
    # think_param_id=0 — if playtest shows the placed chr is AI-inert
    # outside m10, that vindicates the original avoid-add and this line
    # should be restored (cite seed/msb/pi).
    36701200, 36708000, 36709000,
    # c3810 Wandering Noble:
    38109000,
    # c3850 Lobster — full 3xxx subfamily team=26:
    38503000, 38503100, 38503110, 38503120,
    # c4110 Demi-Human Queen:
    41109000, 41109100,
    # c4180 Spirit Jellyfish (already a "spirit" model, unsurprising):
    41809000,
    # c4300 Foot Soldier (one specific variant):
    43000600,
    # c4491 Small Pot Merchant:
    44910000,
    # c4492 (entirely team=26 — c-prefix is fully cinematic):
    44920000, 44920100,
    # c50001 (5-digit c-prefix, sub-form):
    500010000, 500010100, 500010200,
    # c52101 through c52313 — staged-form sub-prefixes of c5210/c5230 boss
    # families (Promised Consort Radahn / Heolstor cinematic phases). Many
    # are 100% team=26, indicating these c-prefixes are cinematic-only:
    521010000, 521020000,
    521030000, 521030100,
    521040000, 521050000,
    521060000, 521060100, 521060200,
    521070000, 521080000,
    521090000, 521090100,
    521100000, 521100100,
    523090000, 523120000, 523130000,
    # c61003 (5-digit, mount/vehicle range — 75% team=26):
    610030000, 610030100, 610030200, 610030400, 610030600, 610030700,
    # c8910 / c8911 (entirely team=26 — system/UI chrs):
    89100000, 89110000,
    # c9001 (system chr range):
    90010000, 90010020,

    # v0.23.26 (orig.) / v0.26.12 (re-attributed): c4720 Godfrey / Hoarah
    # Loux phase-locked variants. User playtest seed 356064 reported "1hp
    # Hoarah Loux in an evergaol" (m49_19_00_00 pi=2, npc_param 47200100).
    # c4720 is an unused slot in vanilla NR; it was first surfaced via the
    # (now-retired) BFER pack and is currently shipped by mmv_imports.json,
    # which ports Godfrey/Hoarah Loux from vanilla ER using the same
    # NpcParam IDs. The three IDs below are verified live in
    # mmv_imports.json — they stay avoid-listed whenever MMV is loaded.
    # Variants of c4720:
    #   47200000  'Godfrey'        — base, presumed safe (combat phase 1)
    #   47200070  '初王' (First King)     — cinematic intro variant
    #   47200100  'Godfrey'        — phase 2 (Hoarah Loux), 1hp without intro
    #   47200134  'Godfrey'        — suffix-100-derived variant, same risk
    # Phase-2 variants of multi-phase bosses are hardcoded to start at low HP
    # because the phase transition is supposed to fire from phase-1 death's
    # hit-detect cutscene. At a randomized slot with no EMEVD intro, those
    # cutscenes don't fire — the chr loads in pre-transition 1hp state.
    # Same bug class as v0.23.20's c2110 21109042 (Beast Clergyman) and the
    # c2031 20310024/20310124 Rennala P2 cocoon-derived variants.
    #
    # Curious data point: the SAME npc_param (47200100) was placed at
    # m48_80_00_00 pi=2 in this seed and worked correctly. m48_80 is a
    # Stormveil-area boss-arena map with its own EMEVD context; m49_19 is
    # a regular evergaol with none. The slot's EMEVD environment, not the
    # chr or NPCParam, is what determines whether the phase-2 form's
    # transition fires. Excluding the unsafe variants is still the right
    # call — we can't rely on slot-level EMEVD to bail us out, and the
    # base 47200000 should work at both contexts.
    47200070, 47200100, 47200134,

    # v0.23.71: Ulcerated Tree Spirit (c4640) context-specific variants.
    # User playtest reported "weird visual glitches" on c4640 placements.
    # c4640 has 6 variants in vanilla NR's regulation; the named-context
    # variants are the suspects for visual oddities at non-vanilla slots:
    #
    #   46400110  'Ulcerated Tree Spirit (Eastern Underground Fort Variant)'
    #             — terrain-context-specific variant. Likely has lighting /
    #             particle FX hooked to the Eastern Underground Fort's
    #             interior dressing (sulfur tint, cave ambient, vault echo).
    #             When placed at a random slot the FX state references missing
    #             environmental cues and renders incorrectly.
    #   46400700  'Ulcerated Tree Spirit (Remembrance)'
    #             — cinematic / Remembrance-context variant. Remembrance
    #             variants in NR typically carry a special-render flag
    #             (golden particle aura, Erdtree-fragment FX) that's
    #             scripted via the Remembrance arena's EMEVD, not the chr
    #             itself. Stripped of that EMEVD context, the variant
    #             either has the aura on always (visual glitch) or renders
    #             without expected FX layering.
    #
    # The base variants (46400000, 46400010 Field Boss, 46400020 Night
    # Boss, 46400030) should be safe — they're the contextless forms used
    # by NR's overworld and rotation systems and aren't expecting
    # arena-specific FX.
    #
    # Conservative addition: if the visual glitch was on a DIFFERENT
    # variant, this won't fix it — user can report which variant they
    # actually saw glitch and we add that ID too.
    46400110, 46400700,

    # v0.23.72-late: Snowfield Troll (c4602) Mountaintop-Duo variant ban.
    # User CTD encountered while fighting a Snow Troll in playtest
    # (Sentient Pest seed 35300). c4602 has 2 variants in vanilla NR:
    #   46020050  Snowfield Troll (Mountaintop)         — regular field
    #             encounter, 1v1 AI. 5 placements this seed across
    #             m34_20 (ruins_boss), m46_60 (named_boss/evergaol),
    #             m48_80 (nightboss), m60_42_38_20 (overworld field).
    #             Believed stable.
    #   46020030  Snowfield Troll (Mountaintop- Duo)    — duo-encounter
    #             AI, designed for the vanilla Mountaintops dual-troll
    #             camp where two trolls fight cooperatively. AI likely
    #             references its partner via EMEVD signal that doesn't
    #             exist at non-duo slots. This seed placed it at m34_10
    #             pi=13 (tunnel interior, replacing Albinauric Archer)
    #             and m46_50 pi=26 (shared-position placeholder slot in
    #             Evergaol map). Same "missing partner" failure class
    #             as the v0.20.69 mount/companion promotions (c3160
    #             Funeral Steed, c4950 Tibia Mariner — see line ~615
    #             in V3_EXCLUDE_TARGET_PREFIXES).
    #
    # Banning Duo variant only preserves Snow Troll as a target via the
    # regular Mountaintop variant. If 46020050 also CTDs in subsequent
    # playtests, escalate to c-prefix-level V3_EXCLUDE_TARGET_PREFIXES.
    46020030,

    # v0.23.71: Ancestor Spirit (c4670) variant 46700200 was previously
    # banned in this session as a CTD-on-grab suspect, but later analysis
    # determined the floating-head-with-beard sightings were Slave Knight
    # Gael (c6200 MMV), not Ancestor Spirit. The Ancestor Spirit's
    # translucent body is by design (DS3-style ghost-stag). Variant
    # un-banned per user feedback. If c4670 grab-CTDs recur after this
    # revert, re-add 46700200 here and continue investigation.
    # 46700200,  # Ancestor Spirit — UNBANNED v0.23.71 (was false positive)

    # v0.23.71: Slave Knight Gael (c6200 MMV) variant 62000001 P1 ban.
    # User playtest pattern: "floating head with beard" CTD-on-grab.
    # c6200 has 2 Gael variants in MMV's manifest:
    #   62000000  Slave Knight Gael P2 (NB2)  — Phase 2, upright halberd
    #             form with deliberate ER-style melee patterns. Stable in
    #             playtest reports — 2 placements this seed (m47_70 pi=120,
    #             m60_42_36_50 pi=50) without reported issues.
    #   62000001  Slave Knight Gael P1 (NB2)  — Phase 1, crawling-on-all-
    #             fours intro form. Hunched silhouette reads as "floating
    #             head with beard" at typical player camera angles. P1
    #             has a primary lunge-grab attack with multi-stage
    #             cinematic anim chain that requires DS3-specific player-
    #             attachment dummypoly handoffs not present in NR. Same
    #             failure class as Ancestor Spirit grab-CTD theory we
    #             discussed: when player ragdoll-attachment routine fires
    #             at a chr without the matching dummypoly setup, the
    #             handoff fails mid-animation → CTD.
    #
    # Banning P1 only preserves Gael as a target (4→2 placements per seed
    # roughly) while removing the CTD-prone variant. If P2 also turns out
    # to be unstable, escalate to c-prefix-level V3_EXCLUDE_TARGET_PREFIXES.
    62000001,

    # v0.24.104: Mohgwyn Palace "Blood Albinauric" variants (scripted-intro
    # AI). Triggered by user playtest report: red albinauric variants from
    # Mohg's realm exhibit broken AI behavior at organic NR slots.
    #
    # Diagnostic process & framework for adding future entries:
    # ---------------------------------------------------------
    # 1. Identify variant name patterns suggesting scripted-context spawn:
    #      'Prelude', 'Remembrance', 'Phase', 'Cinematic', 'Lord of Blood',
    #      'Mohg', 'Cocoon', 'Crawling', 'Sleep', 'Defeated', 'Pre-'.
    #    These are stronger signals than generic '(Boss)' or '(Field Boss)'
    #    suffixes (which appear on many working variants).
    #
    # 2. Cross-check against NpcParam runtime fields. For the c-prefix's
    #    set of placed-in-vanilla-NR variants, compute the envelope of
    #    values for each runtime-affecting field (spEffectID0/28/30,
    #    behaviorVariationId, residentMaterialExParamId00, animIdOffset).
    #    Suspect variants will diverge from the placed envelope.
    #
    # 3. Caveat: divergence direction matters. For some c-prefixes (e.g.,
    #    c3400 Grave Warden Duelist), the PLACED variants are the ones
    #    with the scripted-context spEffect, and vestigial variants lack
    #    it — they may be the SAFER variants for organic placement, not
    #    the broken ones. Don't blindly trust envelope divergence.
    #
    # 4. Ground truth requires inspection of TAE animation event flags and
    #    behavior trees inside the chr's anibnd/behbnd, which we currently
    #    don't have tooling for. Until then, manual entries seeded by
    #    playtest observation are the practical option.
    #
    # The Blood Albinaurics (3 variants total, all 'Lord of Blood Prelude'
    # named, c-prefix c3470 + c3471):
    34702410,  # c3470 'Blood Albinauric - Club (Lord of Blood Prelude)'
    34704230,  # c3470 'Blood Albinauric - Halberd (Lord of Blood Prelude)'
    34715210,  # c3471 'Large Blood Albinauric (Lord of Blood Prelude)'

    # v0.27.0: c3360 Ancestral Follower — variant-level ban. Playtest
    # (oops-all c3360, restored NR install) found only the Axe
    # (33600010) and Archer (33600510) Blacksmith-Group-Boss variants
    # render and fight; the other 32 of 34 variants are broken in-game.
    # NpcParam diff against the working pair found no field that tracks
    # the symptom, so the cause is not isolated — but the empirical
    # split is clear and consistent. c3360 stays placeable via the two
    # working variants; the rest are avoid-listed. (Sibling c3370
    # Ancestral Follower Shaman playtested fully working — not listed.)
    33600000, 33600020, 33600100, 33600200, 33600210, 33600300,
    33600310, 33600500, 33600520, 33600600, 33600700, 33601000,
    33601010, 33601020, 33601100, 33601200, 33601210, 33601300,
    33601310, 33602000, 33602010, 33602100, 33602200, 33602300,
    33605000, 33605200, 33605500, 33605700, 33606000, 33606200,
    33607000, 33607200,

    # v0.27.23: dead-think-param variants — found by a roster-wide sweep
    # (dev/audit_think_param_vs_regulation.py concept) of every roster
    # think_param_id against the shipped regulation's NpcThinkParam after
    # the c5251 Horned Shaman fix (v0.27.22). The engine writes the
    # roster's think_param_id straight into the MSB Part with NO runtime
    # validation, so a variant pointing at a think id absent from the
    # regulation spawns AI-inert (the c5251 signature). Unlike c5251,
    # these have NO correctly-authored same-creature think row to repoint
    # to — the band around each missing id holds only OTHER creatures'
    # rows (e.g. c4071's band is "Rat", c4181's is "Large Scarab", c4442's
    # is "Walking Mausoleum"), so a repoint would graft the wrong AI.
    # Fabricating a think row would mean inventing AI behavior data, which
    # is out of scope for a data fix. Avoid-listing the specific dead
    # variants is the safe, established handling — each affected c-prefix
    # keeps its working variant(s) and the picker (HARD _filter_avoid_npc)
    # routes around the dead ones.
    #
    # c4442 Giant Rotten Land Squirt — FIXED in v0.27.26, no longer listed.
    # Was thought to be unfixable (both variants pointed at the absent think
    # 44420000, and v0.27.23 had no reg dump to find a repoint target). The
    # full reg dump showed c4442 is the Giant Land Squirt's rot variant —
    # identical HP (1429), same family, same 14-row behavior set — so its
    # roster think was repointed to 44410000 (Giant Land Squirt, valid
    # logicId=10000 / battleGoalID=444100) in nr_enemy_roster.json. With a
    # valid think it now passes the v0.27.24 guard and places normally; the
    # static entries here were removed so it is no longer benched.
    # c4071 White Wolf — base variant dead (40710000 absent); working
    # variant 40710010 uses real think 40700000.
    40710000,
    # c4181 Maris' Jellyfish — two variants dead (41810000 absent); three
    # working variants use 41808000.
    41810000, 41810100,
    # c4911 Great Wyrm Theodorix — base dead (49110000 absent; no think
    # row anywhere in the 4911 band); NB variant 49110010 uses 49100010.
    49110000,
    # c5512 Shade — two scaled variants dead (55120098 / 55120198 absent);
    # working variants 55120000 / 55120100 use authored "Shade (ADDED)".
    55120098, 55120198,
    # c5890 Black Knight Horse — four variants dead (58900001 / 090 / 093 /
    # 190 absent); working 58900000 uses authored "Black Knight Horse
    # (ADDED)". A mount has no independent combat AI, so this is lowest-
    # impact, but the dead variants are avoid-listed for consistency so the
    # Kaiden->Black-Knight mount pairing always draws the working variant.
    58900001, 58900090, 58900093, 58900190,

    # v0.27.43: trash-pool sponge variants. A per-chr hp_median audit of the
    # starting-encampment trash pool (data/reconstructed_trash.json) masked
    # high-HP variants — the median said "trash" while a minority variant was
    # a damage sponge. Auditing spawnable hp_MAX per trash chr surfaced 16
    # variants above the 400-HP trash line across 8 chrs. Every one has a
    # normal-HP twin (Exile Soldier 51 variants @230, Misbegotten 17 @192,
    # Bloodfiend 14 @224-346, ...), so all are banned rando-wide (none
    # normalized) — a beefy variant adds nothing the normal twin doesn't.
    # 7 are broken/special (the 63936-HP Exile Soldier debug rows, a Sparring
    # Grounds Dummy Marionette, 9xxx scripted-slot Putrid Ancestral Follower /
    # Demi-Human Shaman); 9 are legit-but-heavy (Bloodfiend 550, Man-Bat 430,
    # Cemetery Shade 939). Banning rando-wide keeps them out of general scatter
    # too, not just encampments. See data/trash_banned_variants.json.
    30009900, 30009999,              # c3000 Exile Soldier — 63936hp debug rows
    34500200,                        # c3450 Misbegotten — 2640hp
    33619000,                        # c3361 Putrid Ancestral Follower — 2560hp (9000 slot)
    36640030,                        # c3664 Cemetery Shade — 939hp
    38502100,                        # c3850 Marionette — 640hp (Sparring Grounds Dummy)
    41109000, 41109100,              # c4110 Demi-Human Shaman — 599hp (9x00 slots)
    50800100, 50801100, 50801110,    # c5080 Bloodfiend — 550hp
    42001000, 42001010, 42001100, 42001110, 42001200,  # c4200 Man-Bat — 430hp
}


# v0.24.35: prefer canonical variants when available.
#
# Many c-prefixes have a mix of canonical variants (sample_maps non-empty —
# vanilla NR has actually instantiated them somewhere) and ghost variants
# (_source='post_dlc_dump' with sample_maps=[] — the chr's NPCParam table
# contains the variant but vanilla NR never placed it).
#
# IMPORTANT — this filter is NOT cosmetic-only. It is easy to skim the
# examples below and conclude ghost variants only glitch visually. They
# don't. `sample_maps` non-empty proxies for "FromSoft instantiated and
# shipped this variant" — which includes its per-chr battle/logic luabnd.
# Ghost variants frequently LACK that script bundle (see nr_missing_chr_
# files.json: many entries are 'no per-chr battle/logic luabnd in
# script/nr|er|mmv' — a broken-AI failure, not a visual one). Empirically
# ghost variants fail across the whole spectrum:
#   - visual:   missing textures, T-pose, off-scale, absent FFX/SFX
#   - behavior: no AI / non-aggressive (e.g. c3471 Large Albinauric's
#               phantom-flag variant spawned non-aggressive enemies)
#   - hard CTD: incomplete asset/param wiring (e.g. c2277 Crab, seed
#               704822 — near-null deref on spawn)
# So: preferring canonical variants culls AI-broken and crash-prone
# placements too, not just ugly ones. Treat it as a STABILITY filter.
#
# Concrete example that triggered this fix (seed 271328, m38_10 pi=19):
# Ulcerated Tree Spirit (c4640) placed with npc_param_id=46400030. c4640 has
# 6 variants total — only npc=46400020 is canonical (sample_maps non-empty,
# has_reward=True). The other 5 (00, 10, 30, 110, 700) are post_dlc_dump
# ghosts. Picker landed on 46400030; chr spawned and worked mechanically but
# visually glitched. With V3_PREFER_CANONICAL_VARIANTS=True the picker would
# have filtered to the 1 canonical, picking 46400020 instead.
#
# Scope: ~2055 of 3391 total variants are ghost variants (60%), spread
# across 296 unique c-prefixes. Some c-prefixes (c70003, c3360, c4312,
# c4376) have ZERO canonical variants — the filter is SOFT (returns input
# unchanged if no canonical exists) so these chrs can still be picked.
#
# Toggle to False to allow ghost variants for visual variety. Default True
# for stability — until each ghost variant is empirically validated.
#
# v0.24.101: FLIPPED to False — "open the floodgates" pass for variety.
# Trade-off acknowledged: ghost variants may produce visual glitches
# (T-pose, missing textures, off-scale, absent FFX). If any specific
# ghost variant turns up bad in playtest, surgically blocklist it via
# its npc_param_id in a per-chr exclusion, rather than re-enabling this
# soft filter wholesale.
#   [CORRECTED v0.26.16] The original v0.24.101 note ended here with
#   "Mechanically the variant still functions — only visuals are at
#   risk." That claim is WRONG and is retracted — see the v0.26.16
#   note below and the framing paragraph at the top of this block.
#   Ghost variants can be AI-broken or crash-prone, not just ugly.
#
# v0.24.109: FLIPPED to True (then reverted). Motivated by seed 599744
# m45_01 framerate report — but that turned out to be a host-machine
# background state issue (laptop reboot fixed it), not a rando issue.
# Restoring the v0.24.101 floodgates default since the diagnostic case
# for the canonical filter evaporated. The per-chr blocklist remains
# the right surgical tool for actually-broken ghost variants.
#
# v0.26.16: default FLIPPED back to True, and the toggle is now exposed
# as a GUI checkbox ("Prefer canonical variants", beside test-mode).
# oops_rando_gui sets this from the checkbox before every run; this
# module-level value is the default for non-GUI / CLI / test callers.
#
# v0.26.16 (doc correction): retitled this filter's purpose. Earlier
# comments (esp. v0.24.101) described it as guarding against "visual
# glitches" only. That undersold it and risked a future reader — human
# or Claude — dismissing it as cosmetic. The canonical/ghost axis tracks
# per-chr script (luabnd) and asset/param completeness, so it culls
# AI-broken and CTD-prone variants as well. CAVEAT for scope: it is a
# WITHIN-PREFIX, SOFT discriminator — it picks the good variant when a
# c-prefix has a canonical/ghost mix, and abstains (returns input
# unchanged) when a c-prefix has ZERO canonical variants. So it does
# NOT protect against an all-ghost / fully-imported c-prefix (every
# variant non-canonical) — that case must be caught upstream at
# prefix-eligibility (V3_EXCLUDE_PREFIXES / nr_missing_chr_files.json).
# This is exactly how c2277 Crab leaked: single imported_chr variant,
# nothing canonical to discriminate against, soft fallback passed it.
#
# v0.28.2: default FLIPPED to False. The bad ghost variants that
# motivated v0.26.16's "default True" stance have been isolated through
# other mechanisms (per-chr exclusions, the redundant-variant prune
# list, prefix-level filters), so the soft canonical-prefer filter is
# no longer load-bearing. Flipping the default to False restores the
# fuller variant pool for variety. The filter, the GUI checkbox, and
# the soft fallback all remain intact — turning the checkbox ON still
# works for anyone who wants the old behavior, and any newly-discovered
# bad ghost should be isolated at its proper level (per-variant
# blocklist or prefix exclusion) rather than re-enabled wholesale.
V3_PREFER_CANONICAL_VARIANTS = False


# v0.31 (Alaric, EXPERIMENTAL): MAXIMAL stamp test. Default OFF.
# When True, rando_pipeline stamps a reserved, per-map, collision-free
# entity id onto EVERY EID-0 Enemy Part in the shuffled corpus (see
# stamp_test.py), writes data/stamp_test_wake_entities.json, and that
# catalog is unioned into patch_proximity_wake so each stamped part gets
# a proximity wake. This is the "unfreeze the overworld and see what
# happens" probe: it wakes ~3,300 parts across 133 maps, including ones
# that are EID-0 deliberately (cutscene actors, despawn-default ambushers,
# script-spawn placeholders), so expect surprises — that is the point.
# The MSB stamp is runtime (this flag, per generate). The matching EMEVD
# wakes are baked from the catalog when patched_emevd/ is (re)generated
# with this flag on — see stamp_test.py header + the writeup.
V3_STAMP_TEST = True
V3_STAMP_TEST_RADIUS = 15        # metres, player-to-part wake radius


# v0.27.x: REDUNDANT-VARIANT PRUNE LIST
# ----------------------------------------------------------------------------
# The NR roster carries ~3100 NpcParam rows, but most are the SAME enemy
# re-authored once per placement context (Castle / Evergaol / Encampment
# / field) plus untested post-DLC-dump "ghost" rows. The model, anims and
# behavior are keyed on the c-prefix, not the NpcParam row, so context-
# duplicate rows are interchangeable in the random pool.
#
# dev/audit_genuine_variants.py clusters rows by genuine identity
# (behaviorVariationId, think_param_id // 1000) and emits
# data/variant_prune_list.json — the npc_param_ids that are redundant
# duplicates of a kept representative. Every genuine variant keeps >=1
# representative row, and within a cluster that has both rewarded and
# non-rewarded rows the rewarded one is kept (so the variant still drops
# its reward). Pruning therefore does NOT remove any genuine variant
# from the pool.
#
# The prune list is applied ONLY in pick_variant_for_tier — the RANDOM
# variant-pick path. Explicitly-targeted placements (manual_promotions,
# boss-arena chr roles, scripted-intro slots) reference specific
# npc_param_ids and go through other code paths; they are unaffected.
#
# Disable by setting this False or by deleting data/variant_prune_list.json
# (an absent file yields an empty set — no-op).
V3_APPLY_VARIANT_PRUNE_LIST = True

_V3_VARIANT_PRUNE_IDS = None  # lazily-loaded cache; None = not yet loaded


# v0.27.13: SECOND prune-id source — data/variant_prune_empirical.json.
# Hand-curated; merged into the same prune set as the audit-generated
# variant_prune_list.json above. Reason for two files: the audit file is
# REGENERATED by dev/audit_genuine_variants.py, so hand-edits there are
# clobbered on the next audit run. Empirical prunes (found by in-game
# observation, not by the genuine-identity audit) need a separate
# never-auto-generated home. v0.27.13 initial use: the 11 wildlife-ghost
# render rows (sheep/ram/goat + ambient fauna) where the chr is
# rendered translucent + non-interactable -- see the file's own
# _v0_27_13_wildlife_ghost_render note for the triple-marker signature
# (SpEffect 13648/11405 + teamType=5 + navmesh=5).
# Same load + apply mechanism as the audit file; both contribute to the
# single merged prune set consumed in pick_variant_for_tier.


# v0.27.13: data/variant_restrict_list.json — per-c-prefix variant
# ALLOWLIST. Distinct from the prune list above: the prune list is a
# blacklist of redundant duplicates that applies globally; this is an
# allowlist that, when a c-prefix is present, restricts that c-prefix's
# random variant pick to ONLY the listed npc_param_ids. Used to pin a
# chr to a known-good variant subset when its other variants are broken
# in-game (the c5651 Messmer Foot Soldier OneHand pin — see the file's
# own _v0_27_13_c5651 note). Allowlist, not blacklist, on purpose: a
# later re-import that adds new variants stays pinned to the tested set
# rather than silently admitting untested rows.
#
# Applied ONLY in pick_variant_for_tier (the random variant-pick path),
# same as the prune list — explicitly-targeted placements reference
# specific npc_param_ids via other paths and are unaffected. SOFT: if
# the restriction would empty a pool the original pool is kept (a
# misconfigured allowlist must never zero out a c-prefix).
#
# Disable by setting this False or deleting the file (absent file =
# empty map = no-op).
V3_APPLY_VARIANT_RESTRICT_LIST = True

_V3_VARIANT_RESTRICT_MAP = None  # lazily-loaded cache; None = not yet loaded


def _variant_restrict_map():
    """Lazily load + cache the per-c-prefix variant allowlist.

    Returns {c_prefix: set(npc_param_id int)}. Empty when the feature is
    off, the file is missing, or the file is malformed (fail-open: a bad
    restrict file must never crash a run, only forgo the restriction).
    """
    global _V3_VARIANT_RESTRICT_MAP
    if _V3_VARIANT_RESTRICT_MAP is None:
        out = {}
        if V3_APPLY_VARIANT_RESTRICT_LIST:
            path = _data_path('variant_restrict_list.json')
            if os.path.exists(path):
                try:
                    with open(path, encoding='utf-8') as f:
                        data = json.load(f)
                    for cp, ids in data.get('restrict_by_c_prefix', {}).items():
                        out[cp] = {int(x) for x in ids}
                except (json.JSONDecodeError, OSError, ValueError, TypeError):
                    out = {}
        _V3_VARIANT_RESTRICT_MAP = out
    return _V3_VARIANT_RESTRICT_MAP


def _variant_prune_ids():
    """Lazily load + cache the redundant-variant prune set.

    Returns a set of npc_param_id ints. Empty when the feature is off,
    the file is missing, or the file is malformed (fail-open: a bad
    prune file must never crash a rando run, only forgo the pruning).
    """
    global _V3_VARIANT_PRUNE_IDS
    if _V3_VARIANT_PRUNE_IDS is None:
        ids = set()
        if V3_APPLY_VARIANT_PRUNE_LIST:
            path = _data_path('variant_prune_list.json')
            if os.path.exists(path):
                try:
                    with open(path, encoding='utf-8') as f:
                        data = json.load(f)
                    ids = {int(x) for x in data.get('prune_npc_param_ids', [])}
                except (json.JSONDecodeError, OSError, ValueError, TypeError):
                    ids = set()
            # v0.27.13: merge the empirical (hand-curated) prune file into
            # the same id set. Two separate files because the audit file
            # above is auto-regenerated; the empirical one must survive
            # audit runs untouched. Fail-open: a missing/malformed
            # empirical file just skips its contribution.
            emp_path = _data_path('variant_prune_empirical.json')
            if os.path.exists(emp_path):
                try:
                    with open(emp_path, encoding='utf-8') as f:
                        emp = json.load(f)
                    ids |= {int(x) for x in emp.get('prune_npc_param_ids', [])}
                except (json.JSONDecodeError, OSError, ValueError, TypeError):
                    pass
            # v0.32.x: KEEP-list — npc_param_ids force-UN-pruned, subtracted
            # from the merged set last so it overrides both the auto file and
            # the empirical file. Needed because variant_prune_list.json is
            # regenerated by dev/audit_genuine_variants.py, whose representative
            # selection (behaviorVariationId, think//1000, has_reward, lowest
            # id) does NOT consider think-param LIVENESS — so it can prune a
            # c-prefix's only think-live variants and keep think-dead ones,
            # which the hard avoid-filter then drops, emptying the pool. The
            # keep-list rescues the live representative(s). Hand-curated;
            # survives audit regeneration. See data/variant_prune_keep.json.
            # Fail-open: a missing/malformed keep file just skips the rescue.
            keep_path = _data_path('variant_prune_keep.json')
            if os.path.exists(keep_path):
                try:
                    with open(keep_path, encoding='utf-8') as f:
                        keep = json.load(f)
                    ids -= {int(x) for x in keep.get('keep_npc_param_ids', [])}
                except (json.JSONDecodeError, OSError, ValueError, TypeError):
                    pass
        _V3_VARIANT_PRUNE_IDS = ids
    return _V3_VARIANT_PRUNE_IDS


# v0.27.x: ROSTER-SUBTYPE MAP (groundwork — see data/nr_roster_subtypes.json)
# ----------------------------------------------------------------------------
# Records c-prefixes whose NpcParam variants split into 2+ distinct gameplay
# identities (e.g. c5250 -> Horned Warrior / Divine Bird Warrior / Divine
# Beast Warrior — three enemies, one chr asset). This is DATA ONLY: the loader
# exposes the map, but no decision path consumes it yet. A later stage will
# let a subtype carry its own attributes (flier flag, cap, ...). c-prefixes
# absent from the file remain a single roster entry == the c-prefix.
_V3_ROSTER_SUBTYPES = None  # lazily-loaded cache; None = not yet loaded


def _roster_subtypes():
    """Lazily load + cache the roster-subtype map.

    Returns the {c_prefix: {base_name, entries: [...]}} dict from
    data/nr_roster_subtypes.json, or {} when the file is absent or
    malformed (fail-open: groundwork data must never crash a run).
    """
    global _V3_ROSTER_SUBTYPES
    if _V3_ROSTER_SUBTYPES is None:
        subtypes = {}
        path = _data_path('nr_roster_subtypes.json')
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
                got = data.get('subtypes', {})
                if isinstance(got, dict):
                    subtypes = got
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                subtypes = {}
        _V3_ROSTER_SUBTYPES = subtypes
    return _V3_ROSTER_SUBTYPES


# v0.27.13: VARIANT GROUPS — the consuming layer the roster-subtype
# groundwork above anticipated ("A later stage will let a subtype carry
# its own attributes (flier flag, cap, ...)"). Where _roster_subtypes()
# is descriptive data only, variant_groups.json carries the cap / floor
# attributes and IS consumed: by pick_variant_for_tier (per-group cap
# exhaustion) and _compute_unique_reservations (per-group floors).
#
# A "variant group" promotes a named loadout family inside one c-prefix
# (e.g. c5250's Divine Bird Warrior) to a first-class identity for the
# cap / floor / diversity machinery, which is otherwise keyed strictly
# on c-prefix. The group KEY used everywhere downstream is the tuple
# (c_prefix, group_name) — a string c-prefix can never collide with it,
# so existing c-prefix-keyed dict logic stays correct for ungrouped
# chrs.
#
# Three lazily-built, cached structures (all keyed off the same file):
#   _V3_VARIANT_GROUP_OF   : npc_param_id(int) -> (c_prefix, group_name)
#   _V3_VARIANT_GROUP_CAPS : (c_prefix, group_name) -> cap(int)
#   _V3_VARIANT_GROUP_FLOORS: (c_prefix, group_name) -> floor(int)
# Fail-open: a missing or malformed file yields three empty dicts and
# the engine behaves exactly as it did pre-feature.
_V3_VARIANT_GROUP_OF = None
_V3_VARIANT_GROUP_CAPS = None
_V3_VARIANT_GROUP_FLOORS = None


def _load_variant_groups():
    """Lazily load + cache the variant-group structures.

    Returns (group_of, caps, floors). group_of maps npc_param_id ->
    (c_prefix, group_name); caps / floors map (c_prefix, group_name) ->
    int. Built by joining variant_groups.json's variant_name lists
    against the roster so the cheap, stable npc_param_id is the runtime
    key (variant_name is display text and not guaranteed unique).

    Fail-open on every error class — a bad groups file forgoes the
    feature, never crashes a run.
    """
    global _V3_VARIANT_GROUP_OF, _V3_VARIANT_GROUP_CAPS, _V3_VARIANT_GROUP_FLOORS
    if _V3_VARIANT_GROUP_OF is not None:
        return _V3_VARIANT_GROUP_OF, _V3_VARIANT_GROUP_CAPS, _V3_VARIANT_GROUP_FLOORS

    group_of, caps, floors = {}, {}, {}
    path = _data_path('variant_groups.json')
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
        # roster join: variant_name -> npc_param_ids, per c-prefix
        roster = {'all_variants': []}
        try:
            with open(_data_path('nr_enemy_roster.json'), encoding='utf-8') as f:
                roster = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
        name_ids = {}  # (c_prefix, variant_name) -> [npc_param_id]
        for v in roster.get('all_variants', []):
            cp = v.get('c_prefix')
            nm = (v.get('variant_name') or '').strip()
            npc = v.get('npc_param_id')
            if cp and nm and isinstance(npc, int):
                name_ids.setdefault((cp, nm), []).append(npc)
        for cp, entry in data.items():
            if cp.startswith('_') or not isinstance(entry, dict):
                continue
            for grp in entry.get('groups', []):
                if not isinstance(grp, dict):
                    continue
                gname = grp.get('name')
                if not gname:
                    continue
                key = (cp, gname)
                for vn in grp.get('variant_names', []):
                    for npc in name_ids.get((cp, vn.strip()), []):
                        group_of[npc] = key
                if isinstance(grp.get('cap'), int):
                    caps[key] = grp['cap']
                if isinstance(grp.get('floor'), int):
                    floors[key] = grp['floor']

    _V3_VARIANT_GROUP_OF = group_of
    _V3_VARIANT_GROUP_CAPS = caps
    _V3_VARIANT_GROUP_FLOORS = floors
    # v0.27.13: caps enforced in pick_variant_for_tier; floors enforced
    # by the variant-group floor pass in _compute_unique_reservations
    # (reserves on the (cp,group) key) + the pinned_group path in
    # pick_target / pick_variant_for_tier. Both halves of Option B live.
    if caps or floors:
        print(f"_load_variant_groups: {len(caps)} group cap(s) + "
              f"{len(floors)} group floor(s) active "
              f"({sorted(set(caps) | set(floors))})")
    return group_of, caps, floors


def _variant_group_key(npc_param_id, c_prefix):
    """Resolve the cap/floor accounting key for one placement.

    Returns (c_prefix, group_name) when this npc_param_id belongs to a
    declared variant group, else the bare c_prefix string. Callers use
    the result directly as a dict key — grouped placements land in a
    tuple bucket, ungrouped ones in the existing string bucket, so the
    two never collide and pre-feature accounting is untouched.
    """
    group_of, _caps, _floors = _load_variant_groups()
    return group_of.get(npc_param_id, c_prefix)


def _filter_canonical_variants(variants):
    """Soft filter: prefer variants with sample_maps non-empty.

    A variant is "canonical" if vanilla NR has placed it somewhere — its
    `sample_maps` list contains at least one MSB path. Empty sample_maps
    means the variant is in the NPCParam table (likely added by the
    post-DLC data dump) but was never actually instantiated by vanilla NR,
    so its integration is untested — not just assets (ResList, FFX, SFX)
    but per-chr battle/logic scripts too. Ghost variants can therefore
    fail as visual glitches, broken/absent AI, OR hard CTDs. This is a
    stability filter, not a cosmetic one.

    Returns input unchanged when no canonical variants exist (so chrs
    with only ghost variants — c70003, c3360, etc. — still get picked).
    """
    canonical = [v for v in variants if v.get('sample_maps')]
    return canonical if canonical else variants


def _classify_variant_source(target_cp, target_npc, prefix_variants, tags):
    """Classify a placement's variant source for spoiler visibility.

    Categories:
      'canonical'      — variant has sample_maps non-empty (vanilla NR
                         has actually placed this chr+variant combo).
                         Safest, no visual glitch concerns.
      'ghost_variant'  — chr is vanilla NR (tags[cp]._source='nr_placed')
                         but this variant has sample_maps=[] (chr's
                         NPCParam exists but vanilla never instantiated
                         it). Visual glitches possible.
      'imported_chr'   — entire c-prefix is imported (heritage / mmv_import /
                         post_dlc_dump at the chr level). The whole chr
                         isn't in vanilla NR's placement pool, not just
                         the variant. Wholesale-import case.
      'unknown'        — fallback when classification fails (shouldn't
                         happen but defensive).
    """
    chr_source = (tags.get(target_cp) or {}).get('_source', '')
    if chr_source in ('heritage', 'mmv_import', 'post_dlc_dump'):
        return 'imported_chr'
    variants = prefix_variants.get(target_cp) or []
    for v in variants:
        if v.get('npc_param_id') == target_npc:
            return 'canonical' if v.get('sample_maps') else 'ghost_variant'
    return 'unknown'
V3_BOSS_NAME_MARKERS = [
    'Boss','Night Boss','Field Boss','Ruins Boss','Fort Boss','Castle Boss',
    'Remembrance','Evergaol','Encampment','Phase 1','Phase 2','(Boss',
]

# v0.20.81: strict subset of boss markers for the NIGHT_BOSS_ONLY tier.
# Excludes 'Encampment' / 'Evergaol' / bare 'Boss' / '(Boss' / 'Phase'
# variants — those qualifiers can attach to compact authored sub-arenas
# (e.g., "Encampment- in tower" Redmane Knight slot, "Evergaol- Halberd"
# Banished Knight slot) where giga-class chrs don't actually fit despite
# the slot technically being a boss-marker. NIGHT_BOSS_ONLY exists for
# chrs that need a true purpose-built large boss arena: Night Boss /
# Field Boss / Castle Boss / Fort Boss / Ruins Boss / (Crater) /
# (Noklateo) / Remembrance markers only. (Crater) and (Noklateo) are
# Shifting Earth boss qualifiers; they're true boss arenas even though
# they don't carry the literal 'Boss' word. 'Remembrance' tags
# heritage-ER bosses which always have purpose-built arenas in vanilla.
V3_NIGHT_BOSS_NAME_MARKERS = [
    'Night Boss',
    'Field Boss',
    'Castle Boss',
    'Fort Boss',
    'Ruins Boss',
    '(Crater)',
    '(Noklateo)',
    'Remembrance',
]

# v0.20.83: tightest tier — Night Boss OR Field Boss markers only.
# Subset of V3_NIGHT_BOSS_NAME_MARKERS. Used for chrs that should ONLY
# appear at Limveld-overworld boss arenas (the Field Bosses you fight
# during the day, and the Night Bosses at end-of-day forced encounters).
# Excludes:
#   - Castle Boss / Fort Boss / Ruins Boss — interior POI bosses, often
#     compact arenas with different geometry.
#   - (Crater) / (Noklateo) — Shifting Earth qualifier slots, also
#     interior or specialized.
#   - Remembrance — heritage-ER boss slots that may live anywhere.
# First user: c4800 Mohg the Omen, who was confirmed working at Field
# Boss slots in vanilla but where the user wants to avoid placement at
# Castle/Fort/Ruins-interior boss slots.
V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS = [
    'Night Boss',
    'Field Boss',
]


# v0.23.11: NIGHT_BOSS_STRICT — strictest marker subset. Only 'Night Boss'.
# Used for chrs whose footprint is geometrically too large even for Field
# Boss / Castle Boss / Fort Boss / Ruins Boss / Crater / Noklateo /
# Remembrance arenas. Only the 22 dedicated Night Boss anchor slots have
# the geometric volume to host them without terrain collision.
#
# First user: c4510 Ancient (Lightning) Dragon — GIGA giga_boss tier.
# Confirmed unplayable at Miranda Blossom (Field Boss) slot in seed 711300:
# the Field Boss arena geometry can't accommodate the Ancient Dragon's
# wingspan + tail, leading to terrain collision and AI breakage.
#
# Strictly tighter than V3_NIGHT_BOSS_NAME_MARKERS (which accepts the
# broader Field/Castle/Fort/Ruins/Crater/Noklateo/Remembrance set) and
# V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS (which still allows Field Boss).
# When chrs need to be more restricted than NIGHT_OR_FIELD_BOSS, this
# is the tier.
V3_NIGHT_BOSS_STRICT_NAME_MARKERS = [
    'Night Boss',
]


# v0.23.38: EXTENDED marker set — broader than V3_NIGHT_BOSS_NAME_MARKERS.
# Adds POI-interior boss markers used by the OOPS_ALL_NB scope='extended'
# setting. These slot types are real boss arenas geometrically but use
# different naming conventions than the broad set:
#   - 'Castle-': Castle interior bosses with hyphenated subtype
#     (e.g. 'Crucible Knight (Castle- Sword)' — the rooftop / basement /
#     courtyard slots inside the Day-2 Castle).
#   - 'Encampment-': Encampment boss POI slots, often in towers or middle
#     rings of an encampment (e.g. 'Banished Knight (Encampment- Shield)').
#   - 'Evergaol': Evergaol boss arenas, compact but boss-tier.
#   - 'Mountaintop Ruins': late-stage Mountaintop boss POIs.
#   - 'Duo Night Boss': two-boss Night Boss arenas (Godskin Apostle/Noble).
# Use this scope when the target chr has a moveset/skeleton compatible
# with compact arena geometry. Don't use for giga-class chrs (Ancient
# Dragon etc) — those break Castle/Encampment geometry.
# v0.23.47: EXTENDED marker set widened. v0.23.38's set caught
# `Castle-`/`Encampment-` hyphenated variants but missed the
# bare-paren convention used by many POI bosses:
#   - 'Ancient Hero (Castle)' — castle rooftop / interior bosses that
#     don't use the subtype-hyphen naming
#   - 'Bell Bearing Hunter (Castle Basement)' — castle basement boss,
#     uses literal 'Castle Basement' substring
#   - 'Mad Pumpkin Head (Encampment)' / 'Elder Lion (Encampment)' —
#     bare-paren Encampment slots
#   - 'Mausoleum Knight (Cathedral)' / 'Guardian Golem (Cathedral)' —
#     Cathedral POI bosses
#   - '(Mountaintop)' bare — Mountaintop overworld bosses
#   - 'Western/Eastern Underground Fort' — underground POI bosses
#   - 'Group Boss' — multi-chr POI encounters (Blacksmith / Marsh /
#     Ruins / Great Church group bosses)
#   - '(Boss)' bare suffix — the actual Nightlord forms (Caligo,
#     Gladius, Adel, Libra, Fulghor, Maris, Heolstor, Mountaintop Ice
#     Dragon, etc.) Important for OOPS_ALL_NB probes that should hit
#     end-of-day Nightlord arenas.
V3_NIGHT_BOSS_EXTENDED_NAME_MARKERS = V3_NIGHT_BOSS_NAME_MARKERS + [
    'Castle-',
    'Encampment-',
    'Evergaol',
    'Mountaintop Ruins',
    'Duo Night Boss',
    # v0.23.47: bare-paren POI markers
    '(Castle)',
    'Castle Basement',
    '(Encampment)',
    '(Cathedral)',
    '(Mountaintop)',
    '(Fort)',  # v0.23.48: bare-paren Fort POI bosses (Guardian Golem,
               # Abductor Virgin, Crystalian, Lordsworn Captain). User
               # noted these are common, geometrically-safe arenas.
               # Distinct from 'Fort Boss' (already in broad set).
    'Underground Fort',
    # v0.23.47: group bosses (multi-Part POI encounters)
    'Group Boss',
    # v0.23.47: bare (Boss) and (Boss Phase X) — Nightlord forms
    '(Boss)',
    '(Boss Phase',
    # v0.23.47: shrouded/enhanced Nightlord variants
    'Shrouded- Boss',
    '(Enhanced Boss)',
]


def _assemble_exclude_target_prefixes(tags, roster, loader_stats):
    """Single assembly point for V3_EXCLUDE_TARGET_PREFIXES (v0.26.x).

    Every target-exclusion source is folded here, in order, and this is
    the ONLY place the set is (re)assigned at load time. Previously the
    sources were merged by `|=` mutations scattered across ~300 lines of
    load_data(), so no single place showed the resolved set.

    Sources, in fold order:
      1. Static base -- the hand-curated V3_EXCLUDE_TARGET_PREFIXES literal
         at the top of the file, ALREADY merged at import time with
         data/nr_missing_chr_files.json by _load_missing_chr_files(). That
         merge stays at import so `cp in V3_EXCLUDE_TARGET_PREFIXES` works
         for pre-load_data() queries; this function takes the seeded set
         as its base.
      2. Pack-loader exclude_target_adds -- currently MMV: the
         blacklist_when_active lists (ctd_unidentified + dlc_assets_
         missing_in_mmv + ai_broken) plus the tier=='mount_component'
         auto-ban. Any loader may contribute; the fold iterates uniformly.
      3. Computed: c-prefixes tagged tier=='cinematic'.
      4. Computed: c-prefixes whose every variant has an empty variant_name.
      5. Computed: c-prefixes with tag data but no roster variants.

    Returns the resolved set; the caller assigns it to the global.
    """
    resolved = set(V3_EXCLUDE_TARGET_PREFIXES)  # (1) static + missing-chr seed

    # (2) pack-loader exclude_target_adds (MMV blacklist + mount-component
    # guard). This used to be a separate fold near the loader pipeline.
    for stats in loader_stats.values():
        resolved |= stats.get('exclude_target_adds', set())

    # (3) v0.23.34: auto-exclude tier='cinematic' c-prefixes. Post-DLC
    # integration introduced ~30 c-prefixes for Roundtable NPCs, Revenant
    # summons, system/template chrs and player-tier objects that break
    # placement at random slots. Tagging tier='cinematic' in the manifests
    # keeps the exclusion declarative.
    _cinematic = {cp for cp, t in tags.items()
                  if isinstance(t, dict) and t.get('tier') == 'cinematic'}
    _n_added = len(_cinematic - resolved)
    if _n_added:
        print(f"v0.23.34: auto-excluded {_n_added} tier='cinematic' c-prefixes "
              f"(plus {len(_cinematic & resolved)} already in exclude set)")
    resolved |= _cinematic

    # (4) v0.23.71: auto-exclude c-prefixes whose every variant has an
    # empty variant_name (post_dlc_dump scrapes the engine cannot name).
    # Conservative: only prefixes whose variants are ALL empty -- a cp
    # with one named variant stays in the pool.
    _named, _all_cps = set(), set()
    for v in roster.get('all_variants', []):
        cp = v.get('c_prefix')
        if not cp:
            continue
        _all_cps.add(cp)
        if (v.get('variant_name') or '').strip():
            _named.add(cp)
    _empty_variant = (_all_cps - _named) - resolved
    if _empty_variant:
        print(f"v0.23.71: auto-excluded {len(_empty_variant)} c-prefixes with "
              f"all-empty variant_name variants from target pool "
              f"({sorted(_empty_variant)})")
        resolved |= _empty_variant

    # (5) v0.23.72-late: auto-exclude c-prefixes that have tag data but NO
    # roster variants. The picker would pick them at boss-arena slots, then
    # pick_variant_for_tier returns None and the slot silently stays
    # vanilla. Engine-side safety net; companion fix is data-side.
    _no_variant = (set(tags.keys()) - _all_cps - resolved - V3_EXCLUDE_PREFIXES)
    if _no_variant:
        print(f"v0.23.72-late: auto-excluded {len(_no_variant)} c-prefixes with "
              f"tag data but no roster variants from target pool "
              f"({sorted(_no_variant)})")
        resolved |= _no_variant

    # (6) v0.28.x: MMV-source chrs that should be excluded when MMV is
    # disabled. Today this is a curated list of one — c6200 Slave Knight
    # Gael (DS3 MMV). When MMV is disabled the chr has no tags/variants
    # so the picker can't pick him anyway, but adding him to the exclude
    # set explicitly:
    #   - makes the intent legible to auditors / spoilers,
    #   - protects against future code paths or data edits that try to
    #     place him without MMV present,
    #   - resists the cap-without-data dead-entry footgun that motivated
    #     V3_RESERVATION_FLOORS / V3_UNIQUE_TARGET_CAPS dead-entry audits.
    # Pattern: probe mmv_imports.json loader stats for the enabled flag.
    # If absent or False, fold the MMV-only-required c-prefixes into the
    # exclude set. Extend this list if other purely-MMV chrs surface.
    _mmv_stats = loader_stats.get('mmv_imports.json', {})
    _mmv_enabled = bool(_mmv_stats.get('enabled', False))
    if not _mmv_enabled:
        _mmv_only_cps = {'c6200'}  # Slave Knight Gael (DS3 MMV)
        _new_mmv_excludes = _mmv_only_cps - resolved
        if _new_mmv_excludes:
            print(f"v0.28.x: MMV disabled — excluded {len(_new_mmv_excludes)} "
                  f"MMV-only c-prefixes from target pool "
                  f"({sorted(_new_mmv_excludes)})")
            resolved |= _new_mmv_excludes

    return resolved


def load_data():
    """Load data and populate this module's V3_* state. Body
    extracted to engine.load_data.load_data in v0.28.x.

    The shim passes `globals()` as ns so the engine function's
    flushes (`ns['V3_FOO'] = value`) mutate THIS module's
    namespace dict — preserving the legacy contract that every
    consumer of oops_v3 sees the populated state via
    oops_v3.V3_FOO attribute access.
    """
    from engine.load_data import load_data as _impl
    return _impl(globals())



def detect_asset_packs(target_chr_dir):
    """v0.23.14: scan target chr/ folder and report which asset packs' chrs
    are present. Used by the GUI's chr/ Inventory tab to give clear feedback
    on whether a user has the optional dependency mods (BFER etc.) installed.

    Returns a dict mapping asset_pack_id → status dict:
        {
            'mmv_imports_v1': {
                'enabled': True,
                'requires_external': True,
                'expected': 41,
                'detected': 39,
                'missing': ['c4604', 'c4730'],
                'description': 'More Map Variations (cross-game boss imports)',
                'url': 'https://www.nexusmods.com/eldenringnightreign/mods/578',
            },
            ...
        }

    A c-prefix is considered "detected" if any chr file matching that prefix
    exists in the target dir (chrbnd, anibnd, behbnd, or texbnd). This is
    permissive on purpose — NR sometimes ships only anibnd in chr/ folders
    while the main chrbnd lives in a packed bundle. Conservative detection
    would false-flag every chr.
    """
    import os, json, re

    # Asset pack JSONs live next to oops_v3.py. Use the same convention
    # load_data() uses, which is the directory containing this module.
    here = os.path.dirname(os.path.abspath(__file__))
    target = (target_chr_dir or '').strip()

    # Inventory the target dir's c-prefixes
    chr_re = re.compile(r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')
    target_have = set()
    if target and os.path.isdir(target):
        for fname in os.listdir(target):
            m = chr_re.match(fname)
            if m:
                target_have.add(m.group(1))

    # Known asset pack JSONs. user_facing_name and url come from each file's
    # _meta block when present; we provide fallbacks here for files that
    # predate that convention.
    #
    # v0.23.72-late: catalog brought up to date with files actually shipped
    # in the current build. The earlier list referenced er_heritage_imports.json,
    # bfer_imports.json, and bfer_imports_v2.json which are no longer present
    # (the BFER integration was paused and the er_heritage_v1 manifest was
    # superseded by heritage_pack.json v2). Adding MMV (More Map Variations)
    # as a first-class pack since mmv_imports.json is the standard cross-game
    # boss-import path in current builds.
    # v0.23.72-late: vanilla_promotions_v1 entry removed — pack was
    # retired since its 8 c-prefixes are all now in canonical
    # nr_enemy_tags.json directly. detect_asset_packs no longer surfaces it.
    KNOWN_PACKS = [
        ('heritage_pack.json',
         'heritage_pack_v1',
         'Heritage Pack (SOTE-flavored chrs)',
         None,  # varies by mod source, no canonical URL
         True),
        ('mmv_imports.json',
         'mmv_imports_v1',
         'More Map Variations (cross-game boss imports)',
         'https://www.nexusmods.com/eldenringnightreign/mods/578',
         True),
    ]

    result = {}
    for fname, pack_id, fallback_name, fallback_url, fallback_external in KNOWN_PACKS:
        path = _data_path(fname)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                pack = json.load(f)
        except Exception as e:
            result[pack_id] = {
                'enabled': False,
                'error': f'failed to read {fname}: {e!r}',
                'description': fallback_name,
                'url': fallback_url,
            }
            continue

        # v0.23.72-late: apply snapshot pack overrides before reading _meta
        _apply_snapshot_overrides_to_pack(pack, fname)
        meta = pack.get('_meta', {})
        enabled = meta.get('enabled', True)
        # User-facing metadata: prefer explicit _meta fields, fall back to
        # KNOWN_PACKS defaults
        description = meta.get('user_facing_name') or fallback_name
        url = meta.get('url') or fallback_url
        requires_external = meta.get('requires_external_chr_assets',
                                      fallback_external)

        cps = sorted(pack.get('tags', {}).keys())
        if not cps:
            # Could be a pure-override pack with no own tags
            result[pack_id] = {
                'enabled': enabled,
                'requires_external': requires_external,
                'description': description,
                'url': url,
                'expected': 0, 'detected': 0, 'missing': [],
                'note': 'overlay pack — applies overrides only, no own tags',
            }
            continue

        if not requires_external:
            result[pack_id] = {
                'enabled': enabled,
                'requires_external': False,
                'description': description,
                'url': url,
                'expected': len(cps),
                'detected': len(cps),  # always "detected" — vanilla
                'missing': [],
                'note': 'ships with base game (no external chr files needed)',
            }
            continue

        present = [cp for cp in cps if cp in target_have]
        missing = [cp for cp in cps if cp not in target_have]

        # v0.23.72-late: origin_game breakdown. Lets the GUI surface a
        # DLC-ownership warning: if a pack contains SoTE-origin chrs and
        # the user's NR install doesn't include SoTE assets (detectable
        # by absence of SoTE-only chrs in their chr/ dir), the placements
        # will CTD even if the heritage pack is "installed."
        from collections import Counter
        origin_breakdown = Counter()
        for cp, tag in pack.get('tags', {}).items():
            origin_breakdown[tag.get('origin_game') or '?'] += 1

        result[pack_id] = {
            'enabled': enabled,
            'requires_external': True,
            'description': description,
            'url': url,
            'expected': len(cps),
            'detected': len(present),
            'missing': missing,
            'origin_breakdown': dict(origin_breakdown),
        }

    return result


def compatibility_preflight(target_chr_dir, reg=None, roster=None, er_available=False):
    """compatibility_preflight: extracted to engine.import_planning in v0.28.x."""
    from engine.import_planning import compatibility_preflight as _impl
    return _impl(globals(), target_chr_dir, reg=reg, roster=roster,
                 er_available=er_available)


def plan_bulk_chr_import(source_chr_dir, target_chr_dir,
                          include_disabled_packs=False,
                          source_script_dir=None,
                          target_script_dir=None):
    """plan_bulk_chr_import: extracted to engine.import_planning in v0.28.x."""
    from engine.import_planning import plan_bulk_chr_import as _impl
    return _impl(
        globals(), source_chr_dir, target_chr_dir,
        include_disabled_packs=include_disabled_packs,
        source_script_dir=source_script_dir,
        target_script_dir=target_script_dir,
    )


def execute_bulk_chr_import(source_chr_dir, target_chr_dir,
                             plan, overwrite=False,
                             progress_cb=None,
                             source_script_dir=None,
                             target_script_dir=None):
    """execute_bulk_chr_import: extracted to engine.import_planning in v0.28.x."""
    from engine.import_planning import execute_bulk_chr_import as _impl
    return _impl(
        globals(), source_chr_dir, target_chr_dir,
        plan, overwrite=overwrite, progress_cb=progress_cb,
        source_script_dir=source_script_dir,
        target_script_dir=target_script_dir,
    )
def plan_roster_import(mmv_dir, er_dir, target_chr_dir,
                        target_script_dir=None):
    """plan_roster_import: extracted to engine.import_planning in v0.28.x."""
    from engine.import_planning import plan_roster_import as _impl
    return _impl(
        globals(), mmv_dir, er_dir, target_chr_dir,
        target_script_dir=target_script_dir,
    )


def execute_roster_import(plan, mmv_dir, er_dir,
                           overwrite=False, progress_cb=None):
    """execute_roster_import: extracted to engine.import_planning in v0.28.x."""
    from engine.import_planning import execute_roster_import as _impl
    return _impl(
        globals(), plan, mmv_dir, er_dir,
        overwrite=overwrite, progress_cb=progress_cb,
    )




def render_compatibility_report_text(report):
    """v0.23.72-late: render a compatibility_preflight() report as plain text,
    suitable for clipboard copy / pasting into Discord / sharing with the friend
    you're sending a build to. Stable, parseable, no ANSI codes."""
    lines = []
    status_icon = {'ok': '✓', 'warn': '⚠', 'fail': '✗', 'info': 'ℹ'}
    lines.append("=" * 60)
    lines.append(f"  Compatibility report — status: {report['status'].upper()}")
    lines.append("=" * 60)
    lines.append(f"  {report['summary']}")
    lines.append("")
    for chk in report.get('checks', []):
        icon = status_icon.get(chk['severity'], '?')
        lines.append(f"  {icon} {chk['name']}: {chk['message']}")
        if chk.get('detail'):
            for dline in chk['detail'].split('\n'):
                lines.append(f"      {dline}")
    lines.append("")
    lines.append("Asset pack inventory:")
    for pack_id, info in report.get('asset_packs', {}).items():
        if not info.get('enabled'):
            continue
        det = info.get('detected', 0); exp = info.get('expected', 0)
        ob = info.get('origin_breakdown') or {}
        ob_str = ', '.join(f"{k}={v}" for k, v in sorted(ob.items())) if ob else ''
        lines.append(f"  - {info.get('description','?')}: {det}/{exp}"
                     + (f" [{ob_str}]" if ob_str else ''))
    return '\n'.join(lines)


def build_per_prefix_data(roster):
    """Return per-c-prefix variant lists (event-trigger filtered) and frequency weights."""
    prefix_variants = defaultdict(list)
    prefix_count = Counter()
    for v in roster['all_variants']:
        cp = v['c_prefix']
        name = v.get('variant_name','')
        if any(m in name for m in V3_VARIANT_TRIGGER_MARKERS):
            continue
        prefix_variants[cp].append(v)
        prefix_count[cp] += v.get('count', 1)
    return prefix_variants, prefix_count


def is_boss_tier_prefix(cp, tags, prefix_variants, gates=None):
    """A c-prefix is boss-tier if any of:
       - has_boss_reward (legacy: variant has Boss in name AND drops reward)
       - has_reward (the engine has a reward item lot for this encounter — high signal)
       - hit_height_median >= 4m (large boss-shaped enemies)
       - heritage prefix with hp_median >= 300 (heritage_pack curated this as a
         significant enemy, and its HP profile is boss-grade — catches Pumpkin
         Head, Bloodfiend, Giant Beast Skeleton, Living Jar Warrior, etc. whose
         variant names lack Boss markers but are unambiguously NR mid-bosses)
       - has any 'Boss'/'Field Boss'/'Encampment'/'Remembrance' marker variant

    v0.24.21: optional `gates` parameter. When None (default), reads
    V3_HERITAGE_ALL_PREFIXES from the module — preserves all
    pre-existing call sites verbatim. When a GateState is passed,
    reads heritage_all_prefixes from the snapshot instead. See
    engine/state.py for the migration plan.
    """
    t = tags.get(cp, {})
    if t.get('has_boss_reward', False): return True
    if t.get('has_reward', False): return True
    h = t.get('hit_height_median', 0) or 0
    if h >= 4.0: return True
    heritage_set = (V3_HERITAGE_ALL_PREFIXES if gates is None
                    else gates.heritage_all_prefixes)
    if cp in heritage_set:
        hp = t.get('hp_median', 0) or 0
        if hp >= 300: return True
    for v in prefix_variants.get(cp, []):
        if any(m in v.get('variant_name','') for m in V3_BOSS_NAME_MARKERS):
            return True
    return False


def is_boss_tier_variant(variant):
    """A specific variant is boss-tier if its variant_name has boss markers."""
    name = variant.get('variant_name','')
    return any(m in name for m in V3_BOSS_NAME_MARKERS)


def is_night_boss_variant(variant):
    """v0.20.81: stricter than is_boss_tier_variant. True only if the
    variant's variant_name carries one of V3_NIGHT_BOSS_NAME_MARKERS — the
    "true purpose-built arena" subset. Used by V3_NIGHT_BOSS_ONLY_TARGETS
    to gate giga-class chrs that don't fit at compact sub-arenas
    (Encampment- in tower, Evergaol- Halberd, etc.) which the broader
    is_boss_tier_variant accepts.
    """
    name = variant.get('variant_name', '')
    return any(m in name for m in V3_NIGHT_BOSS_NAME_MARKERS)


def is_night_or_field_boss_variant(variant):
    """v0.20.83: tightest gate — Night Boss OR Field Boss markers only.
    Subset of is_night_boss_variant. Excludes Castle/Fort/Ruins-interior
    boss markers and Shifting Earth (Crater)/(Noklateo) qualifiers.
    Used by V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS for chrs that should
    ONLY appear at Limveld-overworld boss arena slots.
    """
    name = variant.get('variant_name', '')
    return any(m in name for m in V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS)


def night_boss_pool(prefix_variants):
    """v0.20.81: returns the set of c-prefixes that have at least one
    variant carrying a night-boss-arena marker. This is the "candidate
    population" for V3_NIGHT_BOSS_ONLY_TARGETS — every c-prefix in this
    pool is guaranteed to have at least one valid landing spot when the
    NIGHT_BOSS_ONLY restriction is applied (because variant selection
    can pick the night-boss variant for night-boss-eligible recipients).

    Use this to:
      - Audit which c-prefixes are eligible to be added to
        V3_NIGHT_BOSS_ONLY_TARGETS without becoming unplaceable.
      - Validate that adding a c-prefix to NIGHT_BOSS_ONLY won't
        accidentally exclude it from the entire run.

    NB: a c-prefix in this pool with NO night-boss-eligible recipient
    slot in the current seed will still get TGT_EXCL'd. The pool tells
    you "has night-boss variants" not "will be placed".
    """
    pool = set()
    for cp, variants in prefix_variants.items():
        if any(is_night_boss_variant(v) for v in variants):
            pool.add(cp)
    return pool


def compatible_pool(recipient_cp, tags):
    """v0.20.0: Universal pool. Returns ALL c-prefixes from tags. We no
    longer pre-filter by size / loco / team. The three filters
    that matter — tier-preserve (boss vs field, tag-driven), fragile-slot
    detection, per-c-prefix exclusions — handle "is this a sane swap"
    decisions downstream.

    v0.23.72-late: the historical signature was
        compatible_pool(recipient_cp, tags, bank_to_prefixes,
                        loose_to_prefixes, mode='loose')
    Those three parameters had been vestigial since v0.20.0 — the function
    only ever returned `set(tags) - {recipient_cp}`. Removed in a cleanup
    pass alongside build_compat_lookups (which produced the same vestigial
    dicts). The threaded `mode` parameter was also dropped; placement has
    been "universal pool, post-filter" not "strict bank vs loose pool" for
    many releases."""
    pool = set(tags.keys())
    pool.discard(recipient_cp)
    return pool


# Variant-level emerge markers — variants with these in their names use spawn
# event scripts (rise-from-ground, summon-from-portal, etc) that don't fire
# when the slot is randomized. Spawning at literal MSB position = buried/floating.
V3_EMERGE_VARIANT_MARKERS = [
    '(Spirit)',                    # Spectral variant, summon-emerge
    '(Night Boss Spirit)',         # Cluster-spirit summon (Leyndell Knight, Horse, Tree Spirit)
    '(Silvery)','(Silver)',        # Silvery summon shader
    '(Phantom)','(Apparition)',    # Phantom summon
    '(Echo)',                      # Memory echo summon
    '(Wraith)','(Risen)',          # Resurrection summon
    '(Summoned)','(Summons)',
]


def is_emerge_variant(variant):
    """True if this variant requires an emerge event script that the rando breaks."""
    name = variant.get('variant_name', '')
    return any(m in name for m in V3_EMERGE_VARIANT_MARKERS)


def filter_emerge_variants(variants):
    """Filter out emerge-marker variants. If all are emerge, fall back to original list."""
    filtered = [v for v in variants if not is_emerge_variant(v)]
    return filtered if filtered else variants


def _filter_avoid_npc(variants, gates=None):
    """Hard filter for V3_AVOID_VARIANT_NPC_IDS. Returns variants with
    avoid-listed npc_param_ids removed.

    History:

    v0.20.86: introduced as a soft filter — returned the original list if
    filtering would have emptied it, on the theory that preserving
    placement coverage was worth more than perfectly avoiding a few
    flagged variants.

    v0.23.21: lifted the call to be applied ONCE upfront in
    pick_variant_for_tier instead of inside each tier-fallback (fixed the
    case where tier filtering removed the GOOD variants first, leaving
    only avoid-listed ones for the soft-fallback to leak through).

    v0.23.25: HARD filter — soft-fallback removed. Diagnosed via user
    seed 356064 (engine v0.23.24): c3670 'Aged Albinauric (Scholar
    Remembrance)' npc_param 36708100 was placed at 4 boss slots despite
    being in the avoid set (team=26 cinematic variant added in v0.23.24).
    Root cause: c3670 has `variants: 1` in nr_enemy_tags.json — vanilla
    NR's regulation has exactly one NPCParam for c3670, which IS the
    team=26 one. The v0.23.21 upfront filter correctly removed it, but
    the soft-fallback then returned the original [bad] list. The fix is
    to fail closed: if the filter empties the variant pool, return empty
    — caller (pick_variant_for_tier) returns None, and the slot falls
    back to vanilla preserve via the standard None-return path.

    v0.24.21: optional `gates` parameter for explicit-state callers.
    When None (default), reads V3_AVOID_VARIANT_NPC_IDS from the module
    — preserves all pre-existing call sites verbatim. When a GateState
    is passed, reads the same value from the snapshot. See
    engine/state.py for the migration plan.

    v0.24.22: BFER compat path removed (Phase 7 cleanup). The
    BFER_UNRESTRICTED_TEST_MODE diagnostic branch + the BFER-specific
    avoid carveout (V3_BFER_SPECIFIC_AVOID_NPC_IDS) both went away with
    the BFER asset pack itself. _filter_avoid_npc is now a single-path
    function regardless of gates= source."""
    if not variants:
        return variants
    if gates is None:
        active_avoid = V3_AVOID_VARIANT_NPC_IDS
    else:
        active_avoid = gates.avoid_variant_npc_ids
    return [v for v in variants if v.get('npc_param_id') not in active_avoid]


# v0.23.59: c-prefixes whose primary-identity filter should be SUPPRESSED.
# These are c-prefixes where the tag.name picks one form but other variants
# are equally valid same-creature alternatives (different costume / weapon /
# tier-named) that we don't want filtered away. Distinct from the c6200-
# style trap which is "different creature multiplexed via modelDispMask";
# these are "same creature, different name."
#
# Determined by reading mmv_imports.json variant lists: a c-prefix lands here
# if its variants all skin to overlapping mask groups (no mask-disjoint sub-
# creatures). Adding a c-prefix here is conservative — variants get the old
# unfiltered selection path.
V3_PRIMARY_IDENTITY_NO_FILTER = {
    'c2110',  # Beast Clergyman / Maliketh / Gurranq — same creature, three names
    'c4720',  # Godfrey / Hoarah Loux / Phantom variants — same creature, weapon/form changes
    'c4721',  # Hoarah Loux variants — same
    'c5840',  # Black Knight (Edredd / Garrew / Hammer / Twinblade / Wings) — weapon-mask only
    'c1260',  # Bashy / Slashy / Hollow Manserving Servant — separate names but no head-only failure mode observed
}


def _filter_primary_identity(variants, tag):
    """v0.23.59: soft filter that prefers variants matching the c-prefix's
    primary creature identity (tag.name). Catches the c6200 Slave-Knight-
    Gael / Scarab trap: c6200's chrbnd contains both Gael and his arena
    Scarabs multiplexed by modelDispMask. The 13 Scarab NpcParams have
    masks that hide Gael's body meshes (#04# Body, #04# Cape, #01# Weapon,
    etc.) but the chrbnd's Face/Hair/Beard meshes are untagged and render
    unconditionally — so when the rando picks a Scarab variant for a c6200
    placement, the result is Gael's floating head + beard with no body.

    Mechanism: build a set of identity keys from tag.name and keep variants
    whose variant_name contains any of them (case-insensitive). Keys include
      - the full cleaned name ('slave knight gael')
      - each split-on-' / ' piece for dual-name chrs ('beast clergyman /
        maliketh' -> 'beast clergyman' AND 'maliketh')
      - each individual word of length >= 5 (so 'lichdragon fortissax'
        also matches variants named just 'fortissax (NB2)' which drop
        the qualifier prefix)
    Parentheticals like '(Saw)' / '(NB2)' are stripped from tag.name itself
    before tokenization so they don't lock us out of base-named variants.

    Soft filter — if the result is empty (e.g. tag.name doesn't match any
    variant's variant_name pattern), the original variant list passes through
    unchanged. So the failure mode here is "filter does nothing extra,"
    not "pool emptied unexpectedly."

    Tag may be None (vanilla NR c-prefix not in MMV's pool, or nr_enemy_
    tags entry without a name). In that case the filter is skipped.
    """
    if not tag:
        return variants
    raw = (tag.get('name') or '').strip()
    if not raw:
        return variants
    import re as _re
    # Strip parentheticals and lowercase
    cleaned = _re.sub(r'\s*\([^)]*\)\s*', ' ', raw).strip().lower()
    if not cleaned:
        return variants
    # Dual-form support ('Beast Clergyman / Maliketh' -> 2 pieces)
    pieces = [p.strip() for p in cleaned.split(' / ') if p.strip()]
    keys = set()
    for piece in pieces:
        keys.add(piece)
        # Significant words (>= 5 chars) added as alternatives, so a tag
        # name 'Lichdragon Fortissax' still matches a variant named just
        # 'Fortissax (NB2)'. 4-char words like 'Gael', 'Wolf', 'Fire' get
        # excluded as too generic, but the full piece still acts as a key.
        # Strip trailing punctuation per-word so 'Romina, Saint of the
        # Bud' yields 'romina' (not 'romina,') as a token, allowing it
        # to match variants like 'Romina (Field Boss)' that don't carry
        # the qualifier comma.
        for word in piece.split():
            word = _re.sub(r'[^\w]+$', '', word)  # strip trailing punct
            word = _re.sub(r'^[^\w]+', '', word)  # strip leading punct
            if len(word) >= 5:
                keys.add(word)
    if not keys:
        return variants
    primary = [v for v in variants
               if any(k in (v.get('variant_name') or '').lower()
                      for k in keys)]
    return primary if primary else variants


def _pick_by_identity(variants, rng):
    """v0.27.x: two-stage variant pick. Group the (already tier-filtered)
    variant list by variant_name, choose a named identity uniformly, then
    pick a backing NpcParam row within that identity uniformly.

    Replaces raw rng.choice(variants), which was uniform over NpcParam
    rows and therefore over-weighted identities backed by many placement
    copies (c5360 Giant Beast Skeleton's 51 rows drowned out c5250's
    Divine Beast Warrior). Identity-uniform makes each named enemy
    equally likely regardless of how many rows back it. Tier filtering
    still happens in the caller, so grouping is within the tier set.
    """
    if not variants:
        return None
    by_name = defaultdict(list)
    for v in variants:
        by_name[v.get('variant_name') or ''].append(v)
    identity = rng.choice(sorted(by_name))
    return rng.choice(by_name[identity])


def pick_variant_for_tier(target_cp, recipient_is_boss, prefix_variants, rng,
                          tags=None, run_ctx=None, pinned_group=None):
    """Pick a variant of target_cp whose tier matches the recipient slot's tier.

    Priority for boss-tier slots:
      1. variants with has_reward=True AND boss-tier name marker (best — reward + intro)
      2. variants with has_reward=True (drops a boss reward, even if not "Boss"-marked)
      3. variants with boss-tier name marker (gets the boss intro/animations)
      4. any non-emerge variant (silent reward loss — accepts the random vibe)

    Priority for field-tier slots:
      1. field-tier variants (no boss markers)
      2. any non-emerge variant

    Also filters out emerge-marker variants ((Spirit), (Silvery), etc) which
    require event scripts that don't fire when the slot is randomized.

    v0.20.86: at each tier, V3_AVOID_VARIANT_NPC_IDS is soft-filtered so
    spirit/ghost-rendered variants are skipped when alternatives exist.

    v0.23.04.1: variants with empty/whitespace variant_name are filtered out
    BEFORE all other tier logic. Empty-name variants typically come from
    environmental/summon-spawn npc_params scraped alongside enemy variants
    (e.g. c3471 Large Albinauric had a no-name placeholder variant whose
    npc_param had the phantom-flag set, producing translucent non-aggressive
    "ghost" enemies at boss slots). Hard filter — these variants are never
    valid for enemy spawning. If all variants are empty-name, returns None
    (caller falls back to vanilla preserve via the standard None-return path).

    v0.23.59: when `tags` is supplied, applies a primary-identity soft
    filter (see _filter_primary_identity docstring). Fixes the c6200
    floating-Gael-head bug where 13 of c6200's 15 NpcParam variants are
    Scarabs whose modelDispMask hides Gael's body. Without `tags`, the
    behavior is unchanged (backward compatible).
    """
    # v0.23.54: graceful miss when target_cp isn't in prefix_variants.
    # Previously raw-keyed prefix_variants[target_cp], raising KeyError
    # mid-MSB if an MMV-only target was requested with MMV disabled (or
    # any other "target not loaded" scenario). Now returns None so the
    # caller's standard None-fallback path handles it cleanly. Caller
    # still sees the slot as "unswappable to this target" and can fall
    # through to vanilla or the standard pick_target path.
    pool = prefix_variants.get(target_cp)
    if not pool:
        return None
    # v0.27.x: drop redundant context-duplicate variants via the prune
    # list (data/variant_prune_list.json — see _variant_prune_ids and
    # V3_APPLY_VARIANT_PRUNE_LIST). Each genuine variant keeps a
    # representative row, so this never removes a genuine variant from
    # the pool. SOFT: if pruning somehow empties the pool the original
    # is restored (defensive — by construction every c-prefix retains
    # >=1 row, so this fallback should not trigger).
    #
    # v0.27.13: variant-group-aware. The prune list's dedup key is
    # (behaviorVariationId, think_param_id // 1000) and does NOT include
    # variant_name (audit_genuine_variants.py: has_reward_in_key=false,
    # no name term). For a multi-loadout c-prefix that is wrong: c5250's
    # Divine Bird Warrior and Divine Beast Warrior share the Horned
    # Warrior behaviorVariationId, so the auditor clustered all three
    # loadouts together and the prune list kept only 2 of 18 rows — both
    # Horned Warrior — silently deleting Divine Bird/Beast Warrior from
    # the pool entirely. That defeats the whole variant-group feature
    # (a group with no surviving row can never be picked) and is a
    # latent bug even without it. Fix: after the normal prune, restore
    # one representative row for any variant group that the prune wiped
    # out completely. Picks the lowest npc_param_id for determinism.
    _prune = _variant_prune_ids()
    if _prune:
        _kept = [v for v in pool if v.get('npc_param_id') not in _prune]
        if _kept:
            _group_of = _load_variant_groups()[0]
            if _group_of:
                _surviving_groups = {
                    _group_of.get(v.get('npc_param_id')) for v in _kept}
                _pruned_groups = {}
                for v in pool:
                    _gk = _group_of.get(v.get('npc_param_id'))
                    if _gk is not None and _gk not in _surviving_groups:
                        _pruned_groups.setdefault(_gk, []).append(v)
                for _gk, _rows in _pruned_groups.items():
                    _kept.append(min(
                        _rows, key=lambda r: r.get('npc_param_id', 0)))
            pool = _kept

    # v0.27.13: variant-restriction allowlist. When target_cp is pinned
    # in data/variant_restrict_list.json, drop every variant whose
    # npc_param_id is not in the allowed set. Runs AFTER the prune step
    # so it composes with it (prune removes dup rows; restrict pins to a
    # known-good subset). SOFT: if the restriction empties the pool the
    # pre-restriction pool is kept — a misconfigured allowlist forgoes
    # the pin rather than zeroing the c-prefix. Currently pins c5651
    # Messmer Foot Soldier to its OneHand family (the variant verified
    # working in the oops-all shakedown); see the data file's notes.
    _restrict = _variant_restrict_map().get(target_cp)
    if _restrict:
        _allowed = [v for v in pool
                    if v.get('npc_param_id') in _restrict]
        if _allowed:
            pool = _allowed
    variants = filter_emerge_variants(pool)
    # v0.23.04.1: drop empty-name variants (phantom/summon placeholders).
    variants = [v for v in variants if (v.get('variant_name') or '').strip()]
    if not variants:
        return None

    # v0.27.13: variant-group floor pin. When a slot was reserved for a
    # specific (cp, group) by the group-floor pass in
    # _compute_unique_reservations, pinned_group carries that group name
    # and the pick is restricted to that group's variants — the
    # reservation guaranteed a *group*, not just a c-prefix, so the
    # variant pick must honor it. HARD when the group has surviving
    # rows; SOFT fallback to the unrestricted pool only if pruning /
    # emerge / empty-name filtering wiped the group out entirely (which
    # the v0.27.13 group-aware prune restore is designed to prevent —
    # this fallback is defensive).
    if pinned_group is not None:
        _group_of = _load_variant_groups()[0]
        _pinned = [v for v in variants
                   if _group_of.get(v.get('npc_param_id'))
                   == (target_cp, pinned_group)]
        if _pinned:
            variants = _pinned

    # v0.23.21: apply V3_AVOID_VARIANT_NPC_IDS filter ONCE globally, BEFORE
    # tier filtering. The previous design applied _filter_avoid_npc at each
    # tier-fallback (Tier-1/2/3/4 below + the field-tier branch), which meant
    # avoid-listed variants could still get placed when they happened to be
    # the only ones surviving tier filtering for the given recipient.
    #
    # Concrete example that triggered the v0.23.21 fix (seed 373504,
    # m60_44_36_00 pi=63): c7100 has 2 variants — 71000010 ('Field Boss',
    # safe) and 71000110 ('Ruins', avoid-listed). At non-boss field slots,
    # tier filtering removed 71000010 (boss-tier name marker), leaving
    # only 71000110. The (then-soft) avoid filter returned the bad variant.
    #
    # v0.23.25: the avoid filter is now HARD (see _filter_avoid_npc
    # docstring). If a c-prefix has ONLY avoid-listed variants, this filter
    # returns empty — handled by the early-return below. Caller falls back
    # to vanilla preserve. This was triggered by seed 356064: c3670 had
    # `variants: 1` in nr_enemy_tags and that one variant was team=26
    # cinematic; the previous soft-fallback would still place it.
    variants = _filter_avoid_npc(variants)
    if not variants:
        return None  # all variants avoid-listed — caller preserves vanilla

    # v0.23.59: primary-identity soft filter — see docstring above and
    # _filter_primary_identity. Skipped when tags is None (legacy callers)
    # or when the c-prefix is in V3_PRIMARY_IDENTITY_NO_FILTER.
    if tags is not None and target_cp not in V3_PRIMARY_IDENTITY_NO_FILTER:
        variants = _filter_primary_identity(variants, tags.get(target_cp))
        if not variants:
            # _filter_primary_identity is soft (returns input on empty),
            # so this branch is defensive — shouldn't trigger in practice.
            return None

    # v0.24.35: canonical-prefer soft filter. When V3_PREFER_CANONICAL_VARIANTS
    # is True (default), prefer variants whose `sample_maps` is non-empty
    # (vanilla NR has placed this chr+variant combo). Ghost variants —
    # NPCParam entries from the post-DLC data dump that vanilla never
    # instantiated — tend to have untested asset integration and produce
    # visual glitches. The filter is SOFT: if no canonical variants exist
    # for this c-prefix, the full pool is preserved (so c70003, c3360, and
    # other 0-canonical chrs still get picked). Order matters — the soft
    # filter sits AFTER the hard avoid-list filter (avoid wins) but BEFORE
    # tier-based picking, so tier-1/2 preferences operate within the
    # canonical-only subset when canonicals exist.
    if V3_PREFER_CANONICAL_VARIANTS:
        variants = _filter_canonical_variants(variants)
        # No early-return: filter is soft, returns input on no-canonical,
        # never empty when input was non-empty.

    # v0.27.13: VARIANT-GROUP cap exhaustion (Option B — the cap half).
    # The c-prefix-level cap machinery in pick_target_cp can't see
    # variant groups: the c-prefix is chosen before the variant is, so
    # a group cap can't gate pick_target_cp. It belongs here instead —
    # one level down, where the variant (hence its group) is known.
    # Drop any variant whose (c_prefix, group) bucket has hit its cap;
    # remaining variants stay eligible. Group counts live in the SAME
    # run_ctx.unique_placed_counts dict as c-prefix counts — tuple keys
    # vs string keys never collide, so this needs no new structure.
    #
    # SOFT (deliberate): if EVERY variant is group-exhausted, the pool
    # is restored rather than emptied. Rationale — emptying would make
    # the slot vanilla (or trigger a re-pick), but a variant group is a
    # cosmetic/loadout distinction within one chr asset, not a
    # placement-safety constraint like tier or the avoid-list. Letting
    # the cap "leak" slightly past its target is the lesser evil vs.
    # silently dropping the slot. The cap still does its shaping job in
    # the common case where other groups of the same c-prefix remain.
    _grp_caps = _load_variant_groups()[1]
    if _grp_caps and run_ctx is not None and len(variants) > 1:
        _counts = run_ctx.unique_placed_counts
        _grp_ok = []
        for v in variants:
            _gk = _variant_group_key(v.get('npc_param_id'), target_cp)
            _cap = _grp_caps.get(_gk) if isinstance(_gk, tuple) else None
            if _cap is None or _counts.get(_gk, 0) < _cap:
                _grp_ok.append(v)
        if _grp_ok:
            variants = _grp_ok
        # else: all groups exhausted — keep `variants` as-is (soft).

    if recipient_is_boss:
        # Tier-1: reward AND boss-marked
        best = [v for v in variants if v.get('has_reward') and is_boss_tier_variant(v)]
        if best:
            _chosen = _pick_by_identity(best, rng)
        else:
            # Tier-2: any reward-bearing variant (covers cases where
            # regulation has reward but no Boss-name marker)
            reward_only = [v for v in variants if v.get('has_reward')]
            if reward_only:
                _chosen = _pick_by_identity(reward_only, rng)
            else:
                # Tier-3: boss-name-marked variant (no reward, boss intro)
                boss_only = [v for v in variants if is_boss_tier_variant(v)]
                if boss_only:
                    _chosen = _pick_by_identity(boss_only, rng)
                else:
                    # Tier-4: anything (silent reward loss)
                    _chosen = _pick_by_identity(variants, rng)
    else:
        field_variants = [v for v in variants if not is_boss_tier_variant(v)]
        if field_variants:
            variants = field_variants
        _chosen = _pick_by_identity(variants, rng)

    # v0.27.13: bump the variant-group placement count for the chosen
    # variant. Only bumps when the chosen variant resolves to a real
    # group key (a tuple) — ungrouped variants leave run_ctx untouched,
    # exactly as before the feature. This is the single accounting
    # point feeding the group-cap filter above and is intentionally
    # AFTER all tier branches so every return path is counted once.
    #
    # Skipped when pinned_group is set: a pinned pick came from a
    # group-floor reservation, and _compute_unique_reservations already
    # pre-bumped the group count at reservation time (same rationale as
    # the c-prefix path's "don't double-bump here"). Bumping again would
    # over-count the reserved placement against the group cap.
    if (_chosen is not None and run_ctx is not None
            and pinned_group is None):
        _gk = _variant_group_key(_chosen.get('npc_param_id'), target_cp)
        if isinstance(_gk, tuple):
            run_ctx.unique_placed_counts[_gk] = (
                run_ctx.unique_placed_counts.get(_gk, 0) + 1)
    return _chosen


def pick_target(recipient_cp, tags,
                prefix_variants, prefix_count, recipient_is_boss, rng,
                target_count=None,
                slot_y=None,
                slot_msb_name=None, slot_pi=None, slot_variant_name=None,
                slot_pos=None,
                slot_eid=None,
                slot_require_boss_reward=False,
                disable_resilient_filter=False,
                non_fragile_baseline_cp=None,
                diagnostic_test_targets=None,
                chaos_mode=False,
                gates=None,
                run_ctx=None):
    """Pick a swap target c-prefix and a variant, matching tier.
    Body folded into engine.picker.pick_target in v0.28.x.

    Inside engine.picker, this function calls pick_target_cp
    directly as a sibling — saves the shim hop on the shuffler's
    hot path (~5000× per shuffle).
    """
    from engine.picker import pick_target as _impl
    return _impl(
        globals(), recipient_cp, tags,
        prefix_variants, prefix_count, recipient_is_boss, rng,
        target_count=target_count, slot_y=slot_y,
        slot_msb_name=slot_msb_name, slot_pi=slot_pi,
        slot_variant_name=slot_variant_name,
        slot_pos=slot_pos, slot_eid=slot_eid,
        slot_require_boss_reward=slot_require_boss_reward,
        disable_resilient_filter=disable_resilient_filter,
        non_fragile_baseline_cp=non_fragile_baseline_cp,
        diagnostic_test_targets=diagnostic_test_targets,
        chaos_mode=chaos_mode,
        gates=gates, run_ctx=run_ctx,
    )



# v0.21 BIG-ENEMY PROXIMITY RULE
# ---------------------------------
# Post-pass after swap_plan is built: scan pairs of XL+ size-class
# placements within the same MSB. If two are within
# V3_BIG_PROXIMITY_RADIUS in 3D, the higher-pi placement is demoted to a
# size <= L target drawn from the same compatible pool. Mitigates
# encampment overcrowding crashes (user CTD m60_44_39_30, where one
# GIGA Fingercreeper, one XXL Putrid Flesh, two XL Fingercreepers, one
# XL Wormface, and two M Bears all landed within ~50u of each other in
# a tight bandit camp).
#
# The encampment fragility filter (T2.7 anchors, T2 prefixes) handles
# the slot-level "this geometry breaks SENSITIVE chrs" question. This
# rule handles the orthogonal "even if individually compatible, density
# is the actual crash trigger" question. Both fire — they're not
# mutually exclusive.
#
# 30u is the encampment-cluster scale: catches the obvious overcrowds
# without restricting big-vs-big pairings on open ground (where a
# Troll and a Bear 60u apart is fine). Tunable.
#
# First-pi-wins iteration is deterministic given seeded order: same
# seed produces same demotion set.

V3_BIG_PROXIMITY_ENABLED = True
V3_BIG_PROXIMITY_RADIUS = 30.0
V3_BIG_SIZE_CLASSES = frozenset({'XL', 'XXL', 'GIGA'})
V3_BIG_PROXIMITY_DEMOTE_TO_SIZES = frozenset({'XS', 'S', 'M', 'L'})

# v0.32.x BIG-PROXIMITY HASH TIE-BREAK (opt-in, default OFF)
# ----------------------------------------------------------
# The forward Gate 8 proximity check resolves big-vs-big overcrowding in
# Part-index visit order ("low-pi wins"), so which slot keeps its XL+ enemy
# in a tight cluster is an artefact of iteration order. With this flag ON,
# a post-pass (engine.rejection.resolve_big_proximity_priority) re-resolves
# the same contest by a deterministic seed+msb+pi priority hash instead, so
# the winner is order-independent; the forward gate is bypassed so the
# post-pass is authoritative. Losers revert to vanilla (mirroring the
# historical v0.21 BIG_PROXIMITY post-pass), NOT demoted to a smaller chr.
# Gate 9 density is untouched — its counted cap stays canonical-order so it
# remains identical to simulate_engine.py's sorted(part_index) pass.
# OFF by default pending a playtest pass; behaviour is unchanged when False.
V3_BIG_PROXIMITY_HASH_TIEBREAK = False

# v0.27.4 GEOMETRY-AWARE SIZE GATE
# ---------------------------------
# Placement-time replacement for the blunt v0.24.55 'xxl_at_small_slot'
# gate. A slot's size capacity is the LARGER of (a) the vanilla
# occupant's size class — FromSoft placed that size here, so it is
# proven safe (STRICT vanilla baseline: no grace step, an XL-vanilla
# slot does NOT auto-qualify for XXL) — and (b) the geometry-derived
# capacity from slot_terrain.json `face_dist` (metres to the nearest
# collision face). An XXL/GIGA target is rejected unless its size class
# is within that capacity. The geometry path RECOVERS the legit big
# slots the blunt gate threw away. Slots with no terrain data fall back
# to the strict vanilla baseline (no upsize without proof).
#
# Only XXL/GIGA are gated — XS..XL (<=1.4m footprint radius) clear
# essentially any navmesh slot and were never the clipping concern.
# V3_SIZE_FOOTPRINT_RADIUS values are median NpcParam hit_radius per
# size class.
V3_GEOMETRY_GATE_ENABLED = True
V3_SIZE_RANK = {'XS': 0, 'S': 1, 'M': 2, 'L': 3, 'XL': 4, 'XXL': 5, 'GIGA': 6}
V3_SIZE_FOOTPRINT_RADIUS = {
    'XS': 0.40, 'S': 0.50, 'M': 0.50, 'L': 0.84,
    'XL': 1.40, 'XXL': 3.25, 'GIGA': 7.00,
}
V3_GEOMETRY_GATED_SIZES = frozenset({'XXL', 'GIGA'})

# v0.24.101 MODEL ENTRY COMPACTION
# ---------------------------------
# After the swap loop completes, walk the MSB's MODEL_PARAM_ST section and
# remove any Enemy-type entries (type=2) that no Part references. These are
# dead weight left behind when the rando swaps every instance of a chr out
# of a map — the model entry remains, the game still loads the chr's
# .chrbnd at map-load even though no Part will spawn it.
#
# Scoped to Enemy models only: MapPiece / Object / Collision / Asset
# entries may be referenced out-of-band by collision lookups or route
# bindings, so removing those isn't safe even when no Part references them.
#
# Conservative: uses ACTUAL Part-reference walk as source of truth, not the
# entries' own instance_count field (which can drift if upstream callers
# forgot to call update_model_instance_count).
#
# Off-switch for the kill case. If a CTD report points at the compaction
# pass, flip this False to revert.
V3_REMOVE_UNUSED_ENEMY_MODELS = True


# v0.24.109 BINARY-SEARCH VANILLA PINS
# ------------------------------------
# Diagnostic-only: (msb_base, pi) tuples listed here skip the picker
# entirely during shuffle_msb_v3, leaving those slots vanilla in the
# output. Used to bisect performance / CTD issues without re-rolling
# the whole rando.
#
# Workflow:
#   1. Identify a problem MSB (e.g., framy starting encampment m45_01)
#   2. Pick ~half of the slots to revert; choose to maximize cp-diversity
#      collapse (revert slots whose vanilla cp matches an already-listed
#      cp from a different slot to drop unique-cp count further)
#   3. Add (msb_base, pi) entries to this set
#   4. Reroll with the same seed — diff is exactly the pinned subset
#   5. Playtest the modified version; the framerate delta tells you
#      whether the reverted slots' cp diversity was causal
#
# IMPORTANT: this is a diagnostic mechanism, not a permanent fix. Once
# the investigation completes, clear this set back to frozenset() and
# encode the lesson learned as a proper engine rule (per-MSB cp cap,
# heritage exclusion, particle-fx exclusion, etc.) targeting the actual
# root cause.
#
# Current investigation (v0.24.109): seed 599744 m45_01 starting
# encampment framerate. RESOLVED: laptop reboot fixed it — turned out
# to be a host-machine background state issue, not a rando issue.
# Mechanism kept in place for future bisects; pin set is empty.
V3_BINARY_SEARCH_VANILLA_PINS = frozenset()

# v0.23.61 PER-MSB DENSITY CAP
# ---------------------------------
# Orthogonal to BIG_PROXIMITY: that pass catches pairs of XL+ within ~30u
# (encampment overcrowd). This pass catches MAP-WIDE saturation —
# diffusely-spread big chrs that don't trigger proximity but blow the
# chr-load budget at cell-load time.
#
# Empirical motivation: seed 176803 m60_42_36_50 ended up with 8 XL+
# placements (2 XXL Hippo + 2 XL Crow + Margit + Tree Sentinel + Godskin
# Noble + Abductor Virgin) on a single Limveld tile, none paired close
# enough to trip the 30u proximity rule. User reported severe framerate
# degradation on cell approach — chr-load budget exhaustion, not combat-
# time eval cost.
#
# Two caps:
#   V3_DENSITY_CAP_XL_PLUS:    max XL/XXL/GIGA chrs per MSB
#   V3_DENSITY_CAP_L_PLUS:     max L/XL/XXL/GIGA chrs per MSB
#
# When over cap, demote excess (highest-pi first, deterministic) using
# the same demotion logic as BIG_PROXIMITY. Demotion target pool:
#   - XL+ over cap → demote to L (still feels weighty, halves the cost)
#   - L+ over cap (if XL cap not yet exceeded) → demote to M
#
# Cap values picked from empirical thresholds: NR's vanilla MSBs rarely
# exceed 2-3 XL+ per map even in dense areas. Setting XL cap=3 gives
# headroom for legit boss-arena maps (where a real boss + spectators
# can stack); L cap=10 is generous for open-field tiles.
#
# Same exemption rules as BIG_PROXIMITY: OOPS_ALL_NB-pinned/catalogued
# slots are never demoted. User's explicit boss-target requests win
# over density management.

V3_DENSITY_CAP_ENABLED = True
V3_DENSITY_CAP_XL_PLUS = 3   # max XL/XXL/GIGA per MSB
V3_DENSITY_CAP_L_PLUS = 10   # max L/XL/XXL/GIGA per MSB
V3_DENSITY_L_SIZE_CLASSES = frozenset({'L', 'XL', 'XXL', 'GIGA'})

# v0.28: master kill switch for the merchant model-swap post-pass. Off for
# now — the model-only merchant swaps add chrbnd load for non-combat NPCs
# (and showed up as "(still merchant — model only)" placements). Flip to
# True to re-enable; the per-run --merchant-model-swap flag still gates it
# on top of this, so both must be on for the swap to run.
V3_MERCHANT_MODEL_SWAP_ENABLED = False

# v0.23.63 TUNNEL DENSITY OVERRIDE
# --------------------------------
# Specific maps that are confined-corridor tunnels / catacombs / cave
# systems get tighter caps than the global default. Empirically these
# are reliable CTD-on-approach culprits because their geometry can't
# accommodate even one XL+ chr — narrow corridors, low ceilings, tight
# turns that don't give large bodies room to navigate or render.
#
# Tunnel maps use:
#   XL+/XXL/GIGA cap = 0   (no big chrs at all)
#   L cap = 4              (reduced from 10; L chrs like Bloodfiend,
#                          Putrid Ancestral Follower, Spirit Jellyfish
#                          still take up corridor space even if not
#                          oversized)
#
# The 7 tunnel MSBs identified by combining:
#   - Interior status (not m60 overworld tile)
#   - Original-chr signature ≥ 40% cave fauna (skeletons, fingercreepers,
#     slugs, rats, crabs, octopi, putrid flesh, imps, Death Birds)
#
# Other small interior MSBs (m31_90, m48_xx, m43_xx, etc.) are arena-
# style fixed boss rooms — they accommodate larger chrs by design and
# don't need tunnel restrictions. The signature heuristic correctly
# distinguishes them from cave/corridor maps.

V3_TUNNEL_MAPS = frozenset({
    'm34_30_00_00.msb',   # Catacomb-style: Beastman + Skeleton mix
    'm46_03_00_00.msb',   # Fingercreeper nest
    'm46_80_00_00.msb',   # Catacomb arena: Godskin Apostle + Death Bird
    'm47_70_00_00.msb',   # Skeleton catacombs (largest tunnel, 100+ slots)
    'm47_80_00_00.msb',   # Rat tunnel
    'm47_90_00_00.msb',   # Smaller Fingercreeper nest
    'm49_21_00_00.msb',   # Skeleton + Death Bird arena
})

V3_TUNNEL_DENSITY_CAP_XL_PLUS = 0   # no bigs in tunnels
V3_TUNNEL_DENSITY_CAP_L_PLUS = 4    # tighter L cap

# v0.23.64 DENSITY-DEMOTE FALLBACK
# --------------------------------
# When _density_demote can't find a compatible smaller cp (empty
# compat pool after tier/caliber/size filters), it returns False and
# the cap silently fails to enforce. Empirically this happened on
# multiple m60 tiles in seed 342245 — m60_42_36_50 had 14 L+ but
# the cap could only demote 1, leaving 13 L+ where 10 was the target.
#
# Fallback: when the per-slot compat-derived smaller pool is empty,
# place the safest available chr from a priority-ordered list.
# Priority-ordered (vs single c-prefix) because V3_MAP_PREFIX_TARGET_
# EXCLUDES bans some safe c-prefixes from specific map prefixes (e.g.
# Maris' Jellyfish c4181 is banned from m60_ tiles to avoid the Maris
# event-chain CTD). The fallback walks the list and picks the first
# c-prefix that isn't excluded for the current MSB.
#
# Ordering rationale:
#   c4040 Slug                — misc anim, not excluded anywhere, S size,
#                                stationary, no event dependencies. The
#                                "universal-safest" pick.
#   c4181 Maris' Jellyfish    — small floater, but m60_-excluded for
#                                Maris event chain. Falls through there.
#   c4170 Putrid Flesh        — small misc, no exclusions.
#   c3080 Imp                 — small humanoid, no exclusions.
#
# All four are in V3_FRAGILE_SAFE_CONFIRMED and pass standard fragility
# filters. Set V3_DENSITY_DEMOTE_FALLBACK_CPS to None or empty list to
# disable fallback (revert to v0.23.63 silent-fail behavior).
V3_DENSITY_DEMOTE_FALLBACK_CPS = (
    'c4040',  # Slug — universal-safest
    'c4181',  # Maris' Jellyfish — floater, m60_-excluded
    'c4170',  # Putrid Flesh
    'c3080',  # Imp
)

# v0.14: compat black hole rescue. Targeted fix for c-prefixes whose loose
# tuple (size, locomotion, team) is shared by zero or one
# other variant — and whose size/family doesn't have many peers
# either. These never get picked by stage-1 strict matching from any
# slot, AND stage-2 fallback only fires when stage-1 is empty (rare for
# typical slots). Result: huge under-targeting in the actual rando.
#
# Diagnosis (seed 78699, real rando run):
#   c4070 Wolf            (quad S loco=3): 5 placements / 154 source slots
#   c5523 Stray (DLC)     (quad S loco=0): 10 placements / 0 source slots
#   c4385 Disciple of Rot (hum S loco=5):  11 placements / 0 source slots
#   c3860 Avionette       (hum S loco=5):  12 placements / 0 source slots
#
# Fix: when ANY slot's stage-2 fallback (size/family, ignore loco/team)
# would include one of these c-prefixes, force-add them to that slot's
# stage-1 pool. Stays additive — doesn't replace stage-1, just augments.
# Effect: these c-prefixes become reachable from the broad set of slots
# matching their size/family, not just the rare slots that share
# their exact loose tuple.
#
# v0.20.0: V3_COMPAT_BLACK_HOLE_PREFIXES retired (universal pool obsoletes).
# v0.24.86-patch7: removed; no remaining code references.

# Maps that host MULTIPLE distinct encounter templates in the same MSB —
# the engine selects one template per playthrough and disables the rest,
# but disabled entities still load their model and render as ghosts.
#
# In vanilla NR, when a "Banished Knights camp" template is rolled at an
# overworld encampment, the engine warps the player to one of these arena
# maps and enables the c3010 entities for that encampment. Other entities
# in the same MSB (Crystalians, Nox Monks, Lords, etc — alternates for
# OTHER encampment templates that COULD have rolled) stay disabled but
# remain loaded.
#
# Without our randomizer, disabled entities aren't a problem — they simply
# don't render. WITH the randomizer, our spatial cluster algorithm groups
# all the tightly-packed entities together and swaps them to a common
# target, which leaves disabled-but-modeled entities visible as ghosts of
# that target.
#
# The fix here: for these maps, override the spatial cluster algorithm
# with a c-prefix-based grouping. All parts sharing the same source
# c-prefix swap to the same target, preserving each template's internal
# coherence (e.g., all 3 Banished Knights become the same swap-in, all
# 3 Crystalians become a different swap-in). Disabled-template ghosts
# are still visible, but at least each template's active fight stays
# coherent.
#
# Identified empirically by surveying the spoiler for maps with >=4
# distinct boss-tier source c-prefixes packed within a few units of each
# other. See `dev/find_shared_arena_maps.py` (TODO) for the diagnostic.
V3_SHARED_ARENA_MAPS = {
    'm46_50_00_00',  # 8 boss c-prefixes: Omen, Banished Knight, Nox, Grave Warden, Misbegotten×2, Azula, Bloodhound
    'm46_60_00_00',  # 6 boss c-prefixes: Crucible, Banished, Nox, Crystalian, Alabaster Lord, Bloodhound
    'm32_10_00_00',  # Overworld field-encampment hub. 28 co-located encampment-template
                     # alternate pairs (vs 10 at m46_60). Multiple encampment LOCATIONS
                     # spread across the map; each location has alternate templates
                     # (Leyndell Knight, Redmane Knight, Leonine Misbegotten, Pumpkin
                     # Head, Misbegotten, etc.). The wider-radius spatial clustering
                     # (V3_SHARED_ARENA_THRESHOLD) keeps separate encampments apart
                     # while c-prefix subdivision preserves each encampment's template
                     # coherence.
}

# Spatial-clustering radius applied within shared-arena maps. Empirically
# calibrated: in m32_10 encampments, template alternates are within 5-15u of
# each other while distinct encampment LOCATIONS are 60-100u apart. 20u sits
# safely between those scales. For pure-arena maps (m46_50, m46_60) all
# entries are within 5u, so any threshold >= 5u produces one cluster, then
# c-prefix split yields the v0.7 behavior.
V3_SHARED_ARENA_THRESHOLD = 20.0

# Per-c-prefix placement cap. Once a target c-prefix has been picked this
# many times across a single seed's shuffle, it's removed from chosen_pool
# for subsequent rolls. Forces redistribution of over-represented field
# rabble (Skeletal Militiaman, Wandering Noble, Putrid Corpse, etc.) onto
# less-represented but still-compat alternatives.
#
# Caveat: clusters count as N placements (one per member). A 5-member
# cluster picking c3500 right at the cap boundary will push c3500 over;
# we don't undo that. Cap is a soft upper bound, not a hard one.
#
# Cap of 50 is chosen empirically: the top placed c-prefix in a typical
# seed currently lands around 119 placements (c3500 Large Skeleton).
# Capping at 50 should cut the worst offenders by ~60% while leaving
# medium-frequency placements untouched.
#
# v0.28.x TODO Step 3: scalar value sourced from data/placement_budget.json
# at module-load. The integer here is a placeholder type-hint only; the
# real value is the JSON's `global_default_cap`. Edit there.
V3_TARGET_PLACEMENT_CAP: int = 50

# v0.24.86-patch7: V3_OFF_MESH_PREFERRED_PLACEMENT_CAP removed alongside
# V3_OFF_MESH_PREFERRED_TARGETS (see its retirement note). The tighter
# 25-cap was paired with the floater-preference mechanism — with that
# mechanism gone, floater c-prefixes are bounded by the global
# V3_TARGET_PLACEMENT_CAP=50 like every other c-prefix.

# Position-aware TARGET-side skip. When picking a swap target, if the slot's
# vanilla y >= the threshold for a candidate c-prefix, that c-prefix is
# excluded from chosen_pool.
#
# Distinct from V3_AERIAL_SOURCE_SKIP — that one prevents swapping AT certain
# vanilla source positions (bats on ledges/perches stay vanilla because the
# ground-locomotion swap-in falls or stays stuck on the navmesh-island the
# bat was authored on). This one prevents certain TARGETS from receiving
# placements at elevated positions, regardless of the source the slot came
# from.
#
# Empirically calibrated against vanilla design intent. For c3470 Albinauric:
# vanilla NR places c3470 in 21 positions across the entire game world, ALL
# at y < 30. From-Software clearly designed Albinauric for ground-only patrol
# — the AI doesn't navigate ledges/walls/towers. When our randomizer places
# them at elevated source positions (Wandering Noble guard towers, Putrid
# Corpse rooftop perches, etc.), the AI activates and tracks the player but
# pathfinding breaks: the enemy swivels but never engages.
#
# In seed 451358, 36 of 79 c3470 placements landed at y >= 30. User
# confirmed in-game: at high-y positions, Albinauric is non-responsive
# even to direct hits, while at low-y positions it behaves normally.
#
# To extend this list, run the diagnostic in dev/ground_only_audit.py
# (TODO) which compares each c-prefix's vanilla y-distribution against
# its randomizer-placed distribution. Add a c-prefix here only if (a) it's
# always vanilla-placed at y < threshold AND (b) reports indicate it
# freezes at elevated positions in randomized seeds. Pure (a) without
# (b) over-restricts the candidate pool unnecessarily.
V3_AERIAL_TARGET_SKIP = {}  # v0.20.0: emptied

# v0.19.2: Fragile-slot resilience layer. Some MSB slots in NR were authored
# with specific spawn-volume/scripted-context requirements (cathedral alcoves,
# tunnel chokepoints, scripted-encounter setups). When randomized, fragile
# spawn enemies (Land Octopus, Slug, Spirit Jellyfish, etc) end up rendering
# stuck-mid-emergence — flat on the ground, AI unactivated. Bipeds with
# stand-and-walk AI handle these slots reliably. This 3-tier system detects
# fragile slots and restricts the target pool to a known-resilient biped set.
#
# Tier 1 (T1, V3_FRAGILE_SOURCE_QUALIFIERS): the source variant's variant_name
# contains a slot-context qualifier like (Cathedral)/(Mine)/(Crater). These
# qualifiers exist on ~95 source slots in vanilla and indicate scripted-
# context placements. Auto-detected at swap time.
#
# Tier 2 (T2, V3_FRAGILE_MAPS): the source slot's MSB is in this set. Whole-
# map restriction. Currently set to NR's cathedral interior (m38_xx) and
# subterranean/tunnel maps (m32_xx). These environments have authored
# geometry that breaks complex spawns throughout, not just in qualifier-
# tagged slots.
#
# Tier 3 (T3, V3_PROBLEM_SLOTS): per-slot manual override. (msb_name, pi)
# tuples mapping to a brief reason string (for documentation). Used for
# specific slots that escape T1 + T2 detection but break in playtest.
# Most precise tier, takes precedence over the others.
#
# When ANY of the three tiers fires, the target candidate pool is intersected
# with V3_RESILIENT_BIPEDS. If the intersection is empty, falls back to vanilla
# preservation (returns None from pick_target_cp).
# v0.20.59: V3_RESILIENT_BIPEDS RETIRED. The set was the original
# hardcoded whitelist of "core safe at fragile slots" c-prefixes
# established before V3_FRAGILE_SAFE_CONFIRMED existed. Now that
# SAFE_CONFIRMED has grown to 140+ entries and covers every classified
# safe c-prefix systematically, RESILIENT is redundant. The 24
# original RESILIENT entries have been migrated into SAFE_CONFIRMED
# (see the v0.20.59 RESILIENT migration block in that set), and
# V3_RESILIENT_BIPEDS is now empty. The production fragile-slot
# filter previously took (RESILIENT ∪ SAFE_CONFIRMED) — with RESILIENT
# empty it reduces to SAFE_CONFIRMED, which is the desired final
# architecture. Keeping the variable in place (rather than deleting)
# so existing call sites continue to work and so this retirement is
# a fully reversible change should it need to be unwound. Future
# cleanup pass can remove call sites and the variable entirely.
V3_RESILIENT_BIPEDS = set()


# v0.20.23: confirmed-sensitive target c-prefixes — never let these land
# at fragile slots regardless of other classification. Complement to
# V3_RESILIENT_BIPEDS:
#
#   V3_RESILIENT_BIPEDS         = whitelist (confirmed safe at fragile slots)
#   V3_FRAGILE_SENSITIVE_TARGETS = blacklist (confirmed sensitive)
#
# A c-prefix in NEITHER set is "untested" / "no special handling" — it
# can land at non-fragile slots normally but is excluded from fragile
# slots as a side effect of the RESILIENT-only intersection there. The
# blacklist exists for cases like Wandering Noble / cartwheel Albinauric
# / Large Demi-Human where playtest evidence has confirmed the c-prefix
# breaks at fragile slots even though it looks structurally safe — we
# want the engine to AVOID it at every fragile slot in every map, not
# just stop trusting it.
#
# Application order in pick_target_cp at fragile slots:
#   1. Restrict pool to V3_RESILIENT_BIPEDS ∩ pool. Empty? Skip.
#   2. Subtract V3_FRAGILE_SENSITIVE_TARGETS. (No-op in practice today
#      because the blacklist members aren't in RESILIENT, but the order
#      makes the blacklist apply even if a future RESILIENT addition
#      conflicts.)
#
# Migration log of c-prefixes that moved from RESILIENT to here:
#   c3470 Albinauric (cartwheel)   — v0.20.17
#   c4101 Large Demi-Human         — v0.20.17
#   c4300 Wandering Noble          — v0.20.23
#   c4300 also covers (Wandering Noble - Sorcerer) variant since c-prefix
#   blacklisting is variant-agnostic.
# Direct additions (never were in RESILIENT):
#   c4570 Wormface                 — v0.20.30 (playtest freeze report)
#   c4230 Small Land Octopus       — v0.20.32 (playtest freeze report).
#                                    aquatic-family — fundamental
#                                    incompatibility with most slot
#                                    contexts (slow/no movement on land).
#                                    See also Giant Land Octopus c4220
#                                    which has the same aquatic-on-land
#                                    issue at tier=field_boss.
#   c5210 Divine Beast Dancing Lion — v0.20.33 (Miranda Blossom slot
#                                    freeze, m46_71_00_00.msb pi=1).
#                                    Lion is already in V3_ARENA_ONLY_TARGETS
#                                    which restricts it to boss-tier slots,
#                                    but Miranda's arena is sessile-plant
#                                    patch — flat-combat-arena assumption
#                                    fails. v0.20.34: the Miranda slot
#                                    is in V3_SENSITIVE_ONLY_SLOTS (softer
#                                    than fragile — subtract SENSITIVE
#                                    without RESILIENT restriction so the
#                                    slot still gets a real boss-class
#                                    target, just not Lion).
#   v0.20.36 batch 1 (diagnostic-mode playtest freezes):
#     c4630 Runebear               — XXL field_boss, quadruped_large
#     c4680 Fallingstar Beast      — GIGA night_boss, flying_dragon
#     c5860 Ghostflame Dragon      — GIGA field_boss, flying_dragon
#     c4440 Land Squirt            — M trash, releases poison cloud
#                                    on disturb (squirty bulb critter)
#     Stray family (c4160 Large Stray, c4161 Stray, c4164 Large
#       Bloodbane Stray, c4165 Bloodbane Stray, c4166 Large Rotten
#       Stray, c5522 Stray, c5523 Stray) — quadruped dog-class.
#   v0.20.38 batch 2:
#     c4150 Basilisk               — S trash, quadruped
#     c5193 Spider Scorpion (S)    — S grunt, aquatic-tagged but
#                                    walks on land. Not adding c5190/
#                                    c5192 (L minibosses) yet — same
#                                    anim family but not directly
#                                    confirmed; user has cautioned
#                                    against blanket aquatic adds.
#   v0.20.39 batch 3:
#     c3610 Oracle Envoy (small)   — M grunt, humanoid. NOT c3620
#                                    (Large Cathedral variant, miniboss)
#                                    which has different anim/scale.
#     c4080 Rat                    — S trash, quadruped
#     c4090 Giant Rat              — M grunt, quadruped
#                                    Both rats freezing despite plain
#                                    quadruped foot-loco profile suggests
#                                    something specific to rat anims —
#                                    could be sniff/idle cycles, could
#                                    be small-collider navmesh issues.
#                                    Worth revisiting under the future
#                                    tunnel-wakeup investigation since
#                                    rats appear in tunnel maps a lot.
#   v0.20.44 batch 4 (predicted-broken validation):
#     c4070 Wolf                   — S trash, quadruped
#     c4071 White Wolf             — S trash, quadruped
#                                    User: "wolf broken". Both vanilla
#                                    Wolf variants share the same anim
#                                    family — adding both. Confirms the
#                                    "small actual-4-legged ground
#                                    walker breaks" pattern. Note that
#                                    Misbegotten (c3450, c3460) tagged
#                                    quadruped did NOT break (added to
#                                    SAFE_CONFIRMED instead) — they're
#                                    bipedal-hunched humanoids that the
#                                    tagger mis-keyed as quadruped. The
#                                    real predictor is true 4-legged
#                                    ground locomotion, not the tag.
#
# =====================================================================
# v0.27.0 — FRAGILE-SLOT FILTER: WHITELIST -> BLACKLIST
# =====================================================================
# The production fragile-slot filter was inverted in v0.27.0. It used
# to be inclusion-only: a c-prefix had to be in V3_FRAGILE_SAFE_CONFIRMED
# (a 157-entry hand-curated playtest whitelist) to land at any fragile
# slot. That design had two failures:
#
#   1. It rotted. Every new chr or asset pack needed manual addition.
#      All 41 MMV-pack chrs were silently locked out of every fragile
#      slot because nobody had hand-added them — which is the bug that
#      surfaced this (Black Knight c5840 placing 1x vs Duelist c3400's
#      31x in seed 129442, same tier, same weight, different slot pool).
#   2. It conflated THREE distinct freeze classes under one flag:
#
#      Class 1 — AI-OFF. Swapped-in enemy boots with AI disabled; the
#        vanilla arena emevd has no wake handler for that slot, so
#        EnableCharacterAI never fires and the enemy stands inert. A
#        backstab un-freezes it (the wake). RETIRED as a fragility
#        concern: emevd_patch.py's _PROXIMITY_WAKE patch is the
#        scripted backstab — it injects the missing wake handler.
#
#      Class 2 — GEOMETRY-STUCK. Enemy spawns clipped into / pinned
#        against terrain; AI is awake but it is physically wedged. A
#        backstab's grab-and-reposition shoves it free. The scripted
#        equivalent is V3_POSITION_SHIFTS (per-slot position nudges) —
#        the same mechanism used for the sunken-troll fix. Addressable
#        per-slot, not a reason to whitelist whole c-prefixes.
#
#      Class 3 — LOCOMOTION/GEOMETRY MISMATCH. Enemy is awake AND
#        unstuck and STILL cannot function: its locomotion/anim set has
#        no valid moveset for the slot's terrain (aquatic gait on land,
#        true-quadruped pathing on non-vanilla navmesh), or it simply
#        does not fit (XXL/GIGA at a narrow authored sub-arena), or its
#        AI is anchor-confused (Maris' Tendril at cluttered slots). A
#        backstab does NOT fix this — it wakes/shoves, the enemy lurches
#        once, then re-freezes or T-poses on the next navigation attempt.
#
# Only Class 3 is a genuine c-prefix-level fragility property. The new
# filter therefore treats EVERY c-prefix as fragile-eligible EXCEPT the
# V3_FRAGILE_SENSITIVE_TARGETS blacklist below (Class 3 chrs) and the
# per-slot V3_PROBLEM_SLOT_EXTRA_BANS. SENSITIVE is now the load-bearing
# guard, not the "defensive, should be redundant" pass it once was.
#
# V3_FRAGILE_SAFE_CONFIRMED is NOT deleted — it is demoted. It survives
# as the "known-tested-safe" data set for two remaining consumers: the
# Gate 5.5 grunt-trash-at-boss-bar exemption, and the diagnostic-mode
# untested-pool computation (disable_resilient_filter). It is no longer
# the production fragile gate.
#
# SENSITIVE-RETEST WORKFLOW (the path to shrinking this blacklist):
# Class 3 membership is a hypothesis per entry, not proven law. Several
# entries predate the _PROXIMITY_WAKE patch and may actually have been
# Class 1 (AI-off) all along. To retest: run a diagnostic batch
# (disable_resilient_filter + diagnostic_test_targets naming the chr)
# forcing the suspect into Crater/Cathedral/off-mesh slots. If it no
# longer freezes post-wake-patch, it was Class 1 — remove it here and
# add it to SAFE_CONFIRMED (which removes it from the diagnostic pool).
# If it still freezes, it is genuine Class 3 and stays. The blacklist
# shrinks by evidence, the same way SAFE_CONFIRMED once grew.
# =====================================================================
# v0.28.x TODO Step 3: fragile-sensitive membership sourced from
# data/placement_budget.json at module-load. The flag marks chrs
# whose AI/animation rigs degrade or hard-fail on rough / narrow /
# off-mesh terrain (NPCs with locomotion < humanoid rigs, fragile
# pathfinding, or animation-driven motion that desyncs on slopes).
# Used by the slot-terrain roughness gate (v0.20.x onward) at
# ~line ~6755 in the picker. Historical curation (preserved in
# git): 50 hand-picked c-prefixes from playtest CTD/freeze
# reports — Albinaurics, Wormfaces, jellyfish, sprout-cluster
# c-prefixes, smaller bandits/scavs, and a few specific heritage
# imports (c5500 Living Magma, c5750 Living Jar) confirmed broken
# off the navmesh.
V3_FRAGILE_SENSITIVE_TARGETS: set[str] = set()


# v0.20.40: empirically-confirmed-safe c-prefixes at fragile slots.
# Companion to V3_FRAGILE_SENSITIVE_TARGETS — the empirical *whitelist*
# pair to that empirical blacklist. Each entry is a c-prefix the user
# encountered at a fragile slot during a diagnostic-mode playtest run
# and observed working correctly (no freeze, normal pathing/combat).
#
# WHY THIS EXISTS:
# Without this list, "things confirmed safe at fragile slots" lives only
# in conversation. The diagnostic-mode loop wastes placements re-testing
# the same c-prefixes, and we have no record of how far the SENSITIVE-
# building project has progressed. Persisting the safe confirmations is
# the other half of the bookkeeping.
#
# HOW IT'S USED:
#   1. Production fragile-slot filter: pool ∩ (RESILIENT ∪ SAFE_CONFIRMED).
#      Each new confirmation immediately expands variety at fragile slots
#      in production runs — we earn the diversity we tested for.
#   2. Diagnostic untested-only filter: pool - RESILIENT - SAFE_CONFIRMED -
#      SENSITIVE. Already-tested c-prefixes are excluded from the test
#      pool, so the diagnostic playtest focuses on net-new c-prefixes.
#
# MIGRATION ENDGAME:
# RESILIENT_BIPEDS is a legacy hardcoded whitelist from before the
# diagnostic loop existed. As (SAFE_CONFIRMED + SENSITIVE) covers more
# of the c-prefix space empirically, RESILIENT becomes redundant and
# can be retired. At that point fragile slots use:
#     pool ∩ SAFE_CONFIRMED       (inclusion: only confirmed-safe)
#     - SENSITIVE                  (exclusion: redundant guard)
# and the engine relies entirely on empirical evidence.
# v0.27.0 — DEMOTED. This set is NO LONGER the production fragile-slot
# gate. The fragile filter was flipped from whitelist to blacklist (see
# the three-freeze-class note above V3_FRAGILE_SENSITIVE_TARGETS). This
# set survives only as the "known-tested-safe" data record, consumed by:
#   - the Gate 5.5 grunt-trash-at-boss-bar exemption, and
#   - diagnostic mode's untested-pool computation.
# Do NOT add entries here expecting them to affect fragile-slot
# eligibility — that is now governed by V3_FRAGILE_SENSITIVE_TARGETS
# (the blacklist). Adding here only removes a chr from the diagnostic
# retest pool. The 157 historical entries are kept as the empirical
# playtest record they always were.
V3_FRAGILE_SAFE_CONFIRMED = {
    'c5193',  # Spider Scorpion (insectoid) — reclassified SAFE per Alaric (was unclassified, failing insectoid-uniformity check). v0.27.x.
    # === v0.20.48 BULK ADD: move_type=3 untested → SAFE_CONFIRMED ===
    # 87 c-prefixes added without individual playtest based on the
    # move_type=3 predictor (90% empirical safe rate). Rationale:
    # the existing classified data has 37 working / 4 broken at
    # move_type=3, and those 4 broken (c3470 Albinauric cartwheel,
    # c4101 Demi-Human Large, c4300 Wandering Noble, c4570 Wormface,
    # c3610 Oracle Envoy) are already SENSITIVE-classified, so the
    # bulk-add only includes UNTESTED move_type=3 c-prefixes.
    # Risk: ~10% might have undiscovered anim quirks. Plan: monitor
    # for new freezes that match move_type=3 → move them out of SAFE
    # and into SENSITIVE individually as discovered.
    #
    # v0.20.49 confirmation: user playtested post-bulk-add and reported
    # "kindred of rot works great" — c3810 Kindred of Rot was the
    # crucial test case. fragile-locomotion (tagger over-classified
    # the leg config) but move_type=3 (actually bipedal-walking). The
    # bulk-add caught it correctly. This is the same Misbegotten/Wolf
    # pattern: move_type beats family as the predictor. Strong
    # signal that the rule generalizes.
    'c2130',  # Margit (XL night_boss humanoid heritage)
    'c2140',  # Omen (L miniboss humanoid)
    'c2500',  # Crucible Knight (Unscaled) (M night_boss heritage)
    'c3000',  # Exile Soldier (M grunt)
    'c3050',  # Commander (L night_boss)
    'c3060',  # Giant Skeleton (M miniboss)
    'c3061',  # Giant Beast Skeleton (L miniboss)
    'c3080',  # Imp (S trash)
    'c3100',  # Elemer of the Briar (L night_boss)
    'c3150',  # Night's Cavalry (M night_boss)
    'c3170',  # Albinauric Archer (S miniboss)
    'c3350',  # Crystalian (L field_boss)
    'c3400',  # Grave Warden Duelist (M miniboss)
    'c3471',  # Large Albinauric (M miniboss)
    'c3500',  # Large Skeleton (Spear) (M trash)
    'c3510',  # Skeleton (Sword and Shield) (M grunt)
    'c3550',  # Sanguine Noble (Unscaled) (M miniboss heritage)
    'c3560',  # Godskin Apostle (Unscaled) (L night_boss heritage)
    'c3570',  # Godskin Noble (Unscaled) (XL night_boss heritage)
    'c3660',  # Commoner (S grunt)
    'c3670',  # Aged Albinauric (Scholar Remembrance) (M miniboss)
    'c3700',  # Depraved Perfumer (M miniboss)
    'c3701',  # Perfumer (M miniboss)
    'c3704',  # Battlemage (L miniboss)
    'c3750',  # Clayman - Spear (M grunt)
    'c3800',  # Cleanrot Knight (M miniboss)
    'c3810',  # Kindred of Rot (M miniboss — quadruped-tagged but actual
              #                  bipedal walking, mt=3 catches the truth)
    'c3860',  # Avionette (S grunt)
    'c3970',  # Azula Beastman (M miniboss)
    'c4100',  # Demi-Human (S trash — note c4101 Large Demi-Human is
              #                       already SENSITIVE; small ones safe)
    'c4110',  # Demi-Human Shaman (XS miniboss)
    'c4130',  # Demi-Human Queen (XL night_boss)
    'c4260',  # Erdtree Burial Watchdog (M miniboss — was in predicted-
              #                          broken batch but mt=3 says safe)
    'c4321',  # Vulgar Militia (S grunt)
    'c4340',  # Mad Pumpkin Head (XL miniboss)
    'c4341',  # Thin Mad Pumpkin Head (M miniboss)
    'c4352',  # Cuckoo Knight (Scholar Remembrance) (M miniboss)
    'c4354',  # Redmane Knight (M miniboss)
    'c4355',  # Mausoleum Knight (M miniboss)
    'c4380',  # Starcaller (S trash)
    'c4381',  # Guilty (S trash)
    'c4382',  # Stonedigger (S grunt)
    'c4383',  # Glintstone Digger (S grunt)
    'c4385',  # Disciple of Rot (S grunt)
    'c4386',  # c4386 (S trash, unnamed in roster)
    'c4490',  # Living Jar Warrior (L grunt)
    'c4550',  # Giant Dog (XL miniboss humanoid)
    'c4560',  # Giant Crow (XL field_boss humanoid)
    'c4561',  # Bloodbane Giant Crow (XL field_boss)
    'c4580',  # Giant Wormface (GIGA night_boss — mt=3 surprisingly!)
    'c4600',  # Troll (XXL field_boss humanoid)
    'c4602',  # Snowfield Troll (XXL field_boss)
    'c4603',  # Stonedigger Troll (XXL field_boss)
    'c4660',  # Guardian Golem (GIGA field_boss)
    'c4670',  # Ancestor Spirit (XL)
    'c4690',  # Grafted Scion (L)
    'c4750',  # Godrick the Grafted (Unscaled) (L night_boss heritage)
    'c4770',  # Gargoyle (XXL night_boss humanoid)
    'c4800',  # Mohg- the Omen (XL field_boss heritage)
    'c4810',  # Erdtree Avatar (XL field_boss)
    'c4820',  # Omenkiller (L miniboss)
    'c5040',  # Curseblade (M miniboss)
    'c5070',  # Death Knight (M miniboss)
    'c5080',  # Bloodfiend (L grunt)
    'c5081',  # Chief Bloodfiend (XL miniboss)
    'c5090',  # Gravebird (L miniboss)
    'c5160',  # Fire Knight (M field_boss)
    'c5240',  # Commoner (Pot) (M grunt)
    'c5241',  # Commoner (M grunt)
    'c5250',  # Horned Warrior (M miniboss)
    'c5311',  # Inquisitor (Candles) (M miniboss)
    'c5312',  # Inquisitor (Staff) (M miniboss)
    'c5320',  # Fat Inquisitor (XL miniboss)
    'c5750',  # Living Jar Warrior (L grunt)
    'c5751',  # Living Jar (S grunt)
    'c5830',  # Messmer Soldier (M miniboss heritage)
    'c5870',  # Imp (Lion Head) (S trash)
    'c7000',  # Fallen Hawks Soldier (Base) (S grunt)
    'c7100',  # Ancient Hero of Zamor (Base) (L field_boss)
    'c7520',  # c7520 (XXL nightlord)
    'c7521',  # c7521 (XXL nightlord)
    'c7560',  # c7560 (XL nightlord misc)
    'c7561',  # c7561 (XL nightlord misc)
    'c7570',  # c7570 (M nightlord misc)
    'c7620',  # c7620 (L nightlord humanoid)
    'c7820',  # c7820 (XL nightlord misc)
    'c7900',  # Nameless King (M)

    # === Individual playtest confirmations (chronological) ===
    'c3010',  # Banished Knight        — v0.20.44 (user: "all the
              #                          stormveil knights safe").
              #                          Banished Knights are former
              #                          Stormveil defenders that appear
              #                          as enemies; M humanoid miniboss.
    'c3070',  # Dominula Celebrant     — v0.20.41 (user: "celebrant safe
              #                          (all forms)" — all mmv variants
              #                          of c3070)
    'c3320',  # Silver Tear (S grunt mt=3) — v0.20.41 confirmed working
              #   ("silver blob good"). v0.20.77 demoted to SENSITIVE
              #   on suspicion it caused user's overworld encampment
              #   CTD; v0.20.79 RE-PROMOTED to SAFE_CONFIRMED after
              #   audit redirected the actual CTD culprits to c4171
              #   Giant Putrid Flesh and c6031 Bear M (both demoted
              #   v0.20.78). User: "actually promote silver tear again
              #   i think its chill". Keeping for record that the
              #   demote/repromote round-trip happened.
    # v0.27.0-late: c3361 Putrid Ancestral Follower removed from this
    # list. It was added v0.20.43 on a "ancestral shaman good" note that
    # actually describes the Shaman (c3370). c3361 is now in
    # V3_EXCLUDE_TARGET_PREFIXES (broken-variant family, c3360 kin), so a
    # fragile-safe entry for it is both contradictory and dead.
    'c3450',  # Misbegotten            — v0.20.44 (user: "misbegotten
              #                          safe"). KEY DATA POINT — was in
              #                          predicted-BROKEN bucket per the
              #                          quadruped-tag rule, but observed
              #                          working. Misbegotten is bipedal-
              #                          hunched, not truly 4-legged.
              #                          Refines the rule: the broken
              #                          pattern is genuine 4-legged
              #                          ground locomotion (rats, wolves,
              #                          dogs, basilisks), not "quadruped
              #                          tag" loosely.
    'c3460',  # Leonine Misbegotten    — v0.20.44 (same family; user
              #                          said generic "misbegotten safe"
              #                          and both share anim family)
    'c3900',  # Fire Monk              — v0.20.43 (user: "fire monk good")
    'c3910',  # Fire Prelate           — v0.20.43 (user: "fire prelate"
              #                          confirmed safe)
    'c4170',  # Putrid Flesh           — v0.20.40 (diagnostic playtest;
              #                          user term "putrescent mound")
    'c4180',  # Spirit Jellyfish       — v0.20.40 (user has confirmed
              #                          all jellyfish safe in all slots
              #                          across multiple sessions).
              #                          v0.20.48 ALSO in
              #                          V3_OFF_MESH_PREFERRED_TARGETS —
              #                          jellies are floaters that don't
              #                          need navmesh, ideal at off-mesh.
    'c4181',  # Maris' Jellyfish       — v0.20.40 (same; despite being
              #                          excl_source for Maris-cluster
              #                          event-chain reasons, c4181 as
              #                          a TARGET at fragile slots is
              #                          fine. v0.20.48 also in
              #                          V3_OFF_MESH_PREFERRED_TARGETS.)
    'c4200',  # Man-Bat                — v0.20.40 (diagnostic playtest;
              #                          user term "bat" — both c4200
              #                          and c4201 added since either
              #                          is a plausible referent and
              #                          both appeared at fragile slots
              #                          in the diagnostic spoiler)
    'c4201',  # Operatic Bat           — v0.20.40 (same)
    # c4240 Fingercreeper — was here from v0.20.41 ("big hand safe");
    #   DEMOTED to SENSITIVE in v0.20.87 after user reported overworld
    #   CTD on the v0.20.85 ghost-Ancient-Hero run. Same multi-leg
    #   insectoid locomotion failure pattern as c4280 Giant Ant
    #   (already SENSITIVE) and c4281 Skull Plate Giant Ant (already
    #   EXCLUDED for rubble locomotion). The spider/finger-walking
    #   anim doesn't pathfind cleanly at uneven encampment / Limveld
    #   POI authored geometry. The original "big hand safe" obs was
    #   at a non-fragile slot where the iconic shape worked; the
    #   pattern doesn't hold at fragile-class slots. Open overworld
    #   placements may still work, but encampment-class is blocked.
    'c4351',  # Godrick Knight         — v0.20.44 (user: "all the
              #                          stormveil knights safe").
              #                          Godrick-loyal knights at
              #                          Stormveil; M humanoid miniboss.
    'c4353',  # Leyndell Knight        — v0.20.41 (user: "all leyndell
              #                          knight safe"). Now redundant
              #                          with the bulk move_type=3 add
              #                          but kept for record.
    'c4420',  # Giant Crayfish         — v0.20.38 (user explicit:
              #                          "giant crayfish working!")
    'c4620',  # Astel - Stars of       — v0.20.41 (user: "There's a
              #   Darkness                working astel off in the
              #                          distance!" — GIGA giga_boss
              #                          working at fragile slot.
              #                          Significant data point — even
              #                          GIGA giga_boss anim profile
              #                          can land safely.)
    'c4640',  # Ulcerated Tree Spirit  — v0.20.46 (user: "tree spirit and
              #                          hippo have both worked pretty
              #                          well in my experience"). XXL
              #                          night_boss large_boss_ground —
              #                          mobile serpentine combat, not
              #                          arena-locked. Reinforces the
              #                          arena-locked-sessile-combat rule
              #                          for the broken Lion case.
    'c4980',  # Death Bird (Deathrite) — v0.20.45 (user: "deathrite bird
              #                          safe"). XXL night_boss
              #                          large_boss_ground — same family
              #                          as Dancing Lion (c5210, SENSITIVE)
              #                          but works fine. Mobile/swooping,
              #                          not arena-locked.
    'c5010',  # Golden Hippopotamus    — v0.20.46 (user observed working).
              #                          XXL field_boss large_boss_ground.
              #                          Mobile charge/lunge combat.
    'c5011',  # Golden Hippopotamus    — v0.20.46 (same family as c5010).
              #   (Golden Wings)         XXL night_boss large_boss_ground.
    'c5900',  # Man-Fly                — v0.20.41 (user: "manfly safe").
              #                          M trash humanoid.

    # === v0.20.50 move_type=13 batch results ===
    # User playtested the move_type=13 untested batch and reported specific
    # results. The hypothesis was that move_type=13 might be 100% broken
    # (existing 3 in SENSITIVE: Runebear, Fallingstar, Ghostflame). Result:
    # most move_type=13 in batch worked. The breaking pattern is NOT
    # move_type=13 broadly — it's two specific sub-patterns:
    #   1. Scripted-intro GIGA/XXL singles (Runebear sleep-wake,
    #      Fallingstar drop-from-sky, Ghostflame flight intro)
    #   2. Standalone-component chr — chrs designed to ALWAYS pair with
    #      another chr (e.g. Funeral Steed = Night's Cavalry's horse).
    #      Spawned standalone, the chr is missing its expected
    #      counterpart and breaks. Tagged _cluster_only in roster JSON.
    # Self-contained multi-part chrs (Tree Sentinel = knight+horse bundled
    # into one c-prefix) work fine.
    'c2041',  # Kindred of Rot Larva   — v0.20.50 (user: "kindred working,
              #                          i thought we already had it in
              #                          safe?"). User confused this with
              #                          c3810 Kindred of Rot (adult, in
              #                          SAFE from move_type=3 bulk-add).
              #                          c2041 is the larva — separate
              #                          c-prefix, move_type=13, but
              #                          works fine. S grub-like trash.
    'c3250',  # Draconic Tree Sentinel — v0.20.50 (architectural inference
              #                          from c3251 confirmation). User
              #                          said "tree sentinel good"; the
              #                          three Tree Sentinel c-prefixes
              #                          share the same self-contained
              #                          mounted-knight chr architecture.
              #                          Mark all three SAFE; if Draconic
              #                          or Loretta breaks specifically
              #                          we'll move out individually.
    'c3251',  # Tree Sentinel          — v0.20.50 (user: "tree sentinel
              #                          good"). Self-contained mounted
              #                          chr (knight+horse bundled).
              #                          Refutes the "all mounted units
              #                          break" hypothesis from earlier
              #                          guess. Cf c3160 Funeral Steed
              #                          (BROKEN) where the chr is
              #                          designed as a paired component
              #                          and breaks when spawned solo.
    'c3252',  # Loretta Tree Sentinel  — v0.20.50 (architectural inference
              #                          from c3251 confirmation; same
              #                          chr architecture as c3251).
    'c3330',  # Giant Silver Tear      — v0.20.50 (user: "Big silver ball
              #                          working!"). XL slime/orb. Same
              #                          family as c3320 Silver Tear
              #                          (already SAFE) but bigger size
              #                          class. move_type=13 doesn't
              #                          break for this one.
    'c4210',  # Warhawk                — v0.20.50 (user: "Warhawks good ...
              #                          also white warhawk variant is
              #                          working"). L flying-bird grunt.
              #                          All variants confirmed including
              #                          the white variant. Refutes the
              #                          earlier "move_type=13 = broken"
              #                          assumption; flying creatures with
              #                          mt=13 work fine.
    # c3664 ("Cemetery Shade") REMOVED v0.24.67. Was added in v0.20.52
    # based on a single user playtest report ("c3664 working but its
    # not cemetery shade. its some kind of headless banished knight").
    # Seed 877217 v0.24.65 invalidated this for boss-bar slots: c3664
    # landed at m32_00 pi=31 ent=32000810 (Elder Lion Encampment) and
    # CTDed on kill. Root cause: NpcParam variants 36640020/32/35
    # carry spawner-generator entity IDs (23664000, 366400700,
    # 366400000) that fire child entities on death — incompatible
    # with vanilla NR's encampment boss-clear chain, which expects
    # a clean Elder Lion teardown. The v0.20.52 confirmation was at a
    # non-boss-bar slot type and doesn't generalize.
    # Tier was also demoted miniboss → grunt in nr_enemy_tags.json
    # (HP 939, weight 130 is grunt territory). Gate 5.5 now rejects
    # c3664 at any catalogued boss-bar slot.
    'c4040',  # Slug (S misc mt=1)     — v0.20.54 (user: "slug in the
              #                          sometimes falls through the
              #                          earth category"). Doesn't CTD
              #                          or freeze — works fine as an AI
              #                          target. The fall-through behavior
              #                          is the known DEFERRED slot-position
              #                          bug (Stone Imp / Lava Slug
              #                          variant) — slug's collider /
              #                          y-coordinate handling is fragile
              #                          at some slot positions, but
              #                          this is a slot-side problem
              #                          orthogonal to chr-prefix freeze
              #                          fragility. Mark SAFE with the
              #                          quirk noted; address in the
              #                          fall-through investigation TODO.
    'c4250',  # Small Fingercreeper    — v0.20.54 (user: "fingercreeper
              #                          good"). S quadruped move_type=1.
              #                          Same chr family as c4240
              #                          Fingercreeper (already SAFE) —
              #                          smaller variant, walks on the
              #                          same hand-finger anim. Refutes
              #                          the predicted-broken assumption
              #                          for this c-prefix; works fine.
    'c4000',  # Revenant Follower      — v0.20.55 (user: "C4000 good").
              #                          M humanoid move_type=4 — but
              #                          works despite being in the
              #                          predicted-broken mt=4 cluster.
              #                          Revenant Followers crawl on
              #                          all fours in vanilla so they
              #                          got mt=4-tagged, but the chr
              #                          handles non-vanilla slots fine.
              #                          Refines the rule: mt=4 small-
              #                          quadruped breakage is for
              #                          CANINE/RODENT body plans
              #                          specifically (rats, wolves,
              #                          dogs, basilisks, strays, goats);
              #                          humanoid-on-all-fours is OK.
    'c3620',  # Oracle Envoy (Large;   — v0.20.55 (user: "c3620 good").
              #   Cathedral)             L humanoid mt=None. Counter to
              #                          the c3610 Oracle Envoy small
              #                          (BROKEN, in SENSITIVE). The
              #                          Cathedral-version Large Envoy
              #                          works. Suggests that within the
              #                          Envoy family, only the small
              #                          (c3610) version breaks; large
              #                          (c3620) is fine. Possibly
              #                          related to the "small bubble-
              #                          blower can't breathe at non-
              #                          vanilla slot" failure mode for
              #                          c3610 vs the Large variant
              #                          having different anim handling.

    # === v0.20.57 low-risk batch — all 8 confirmed safe ===
    # Major rule refinement: XL+ size in mt=4 reliably WORKS even though
    # small/medium mt=4 quadrupeds reliably BREAK. The size cutoff for
    # mt=4 breakage is bounded:
    #   * S/M canine-rodent-body-plan mt=4: BROKEN (rats, wolves c4070/
    #     c4071, basilisk, strays c4160-c4166, c5522/c5523, dogs,
    #     bloodhound knight c4290, goat c6060)
    #   * L+ mt=4 (any family): SAFE (Red Wolf of Radagon L,
    #     Royal Revenant L, Giant Ant L, Crayfish XXL, Hippo XXL, all
    #     three giant crabs c2270/c2272/c2276 XL/XL/XXL)
    # The breaking mechanism for small mt=4 appears to be specific to
    # the small-quadruped-on-non-flat-terrain failure — large mt=4
    # chrs have different idle/walk anims that handle non-vanilla
    # slots gracefully.
    'c2270',  # Giant Crab (XL aquatic mt=4) — XL aquatic exception
              #                                  (cf c2271 Crab small,
              #                                  BROKEN).
    'c2272',  # Giant Black Crab (XL aquatic mt=4) — same family.
    'c2276',  # Giant Death Crab (XXL aquatic mt=4) — same family,
              #                                       larger size class.
    # c3181 Red Wolf of Radagon — was here from L+ mt=4 size cutoff
    #   rule (v0.20.57); DEMOTED to SENSITIVE in v0.20.82 after user
    #   "CTD on spawn near mountaintop" pointed at a m60_42_38_10
    #   pi=7 placement (Albinauric Archer src — non-arena Mountaintop
    #   Ruins area). Red Wolf of Radagon is the Caria Manor boss with
    #   a scripted Radagon-transform intro animation; the scripted
    #   intro fails at non-Caria-Manor-shaped slots — same failure
    #   class that put c4630 Runebear and c5820 Great Red Bear in
    #   SENSITIVE (scripted-intro pattern, not pure locomotion). Open
    #   non-fragile placements without the cluster of XL+ neighbours
    #   may still work, but the encampment-tier MT-tile leak class is
    #   blocked.
    'c4020',  # Royal Revenant (L quadruped mt=4) — counter-example to
              #   c4021 (XL Royal Revenant boss-tier, SENSITIVE).
              #   L-tier works; boss-tier XL+ has its own issues.
    # c4280 Giant Ant — was here from v0.20.57 (L+ mt=4 size cutoff
    #   rule); DEMOTED to SENSITIVE in v0.20.76 after user encampment
    #   freeze. The L+ size cutoff rule held for crabs / hippos /
    #   crayfish (all mt=4 large quadrupeds), but the multi-leg
    #   insectoid locomotion fails on encampment scaffolding/stakes
    #   the same way c4281 Skull Plate Giant Ant fails on rubble (the
    #   c4281 entry in V3_EXCLUDE_TARGET_PREFIXES anticipated this
    #   class of failure but only for the larger XL variant). Keeping
    #   c4280 at non-fragile non-off-mesh open-overworld is fine —
    #   the failure mode is uneven authored geometry, not core
    #   locomotion.
    'c4470',  # Abductor Virgin (XL quadruped_large mt=1) — XL works.
    # c6031 Bear M — was here from v0.20.57; DEMOTED to SENSITIVE in
    #   v0.20.78. User v0.20.76 spoiler audit found it landing at
    #   multiple Limveld encampment-themed slots (Demi-Human,
    #   Godrick Soldier, Rotten Stray sources at m60_44_36_30 / 39_00).
    #   User-reported overworld encampment CTD was originally attributed
    #   to Silver Tear but follow-up audit flagged Bear M as a
    #   strong co-suspect in the same maps. Quadruped_large bear
    #   locomotion struggles at uneven encampment scaffolding —
    #   different failure mode from XXL bears (c4630/c5820 SENSITIVE
    #   for scripted-intro reasons), but still encampment-fragile.

    # === v0.20.58 min-risk batch — all 11 confirmed safe ===
    # Final cleanup pass on the untested backlog. User noted that the
    # "fleshes" (c4170, c4171) have an emergence animation that works
    # even spawned in the air — suggesting they're good candidates for
    # the off-mesh preferred set. This insight extends the floater
    # principle: chrs with air-tolerant emergence anims handle off-mesh
    # placements as well as actual floaters do, because their startup
    # state doesn't require ground contact.
    'c2040',  # Juvenile Scholar (S humanoid mt=8) — safe.
    'c3662',  # Putrid Corpse (Large) (M humanoid mt=11) — safe.
    # c3730 Graven School — was here from v0.20.58 batch (L humanoid
    #   mt=0); DEMOTED to SENSITIVE in v0.20.85 after user encountered
    #   it landing at a "Banished Knights" healthbar slot in Limveld
    #   overworld and reported "we gotta give the sensitive treatment
    #   to sphere of faces". The fused-stone-faces sphere has a
    #   floating/rolling locomotion class that doesn't pathfind
    #   correctly at most non-vanilla slots — visually striking but
    #   functionally fragile. Same SENSITIVE-treatment playbook as
    #   prior single-obs SAFE additions that didn't survive systematic
    #   exposure (Giant Ant, Putrid Flesh, Bear M, Red Wolf).
    # c4171 Giant Putrid Flesh — was here from v0.20.58; DEMOTED to
    #   SENSITIVE in v0.20.78. v0.20.60 had already retired this from
    #   V3_OFF_MESH_PREFERRED_TARGETS after a user CTD report ("big
    #   purple gaseous sphere near flask church") but kept it in SAFE
    #   on the assumption that the OFF_MESH_PREFERRED placement was
    #   the proximate cause. User v0.20.76 audit identified 5 c4171
    #   landings across 4 Limveld maps that overlapped with the
    #   overworld-encampment CTD area (m60_42_37_00, m60_43_36_00,
    #   m60_43_39_00, m60_44_36_30 — including Foot Soldier sources
    #   at encampments). The XXL large_boss_ground anim with the
    #   air-emergence intro looks dramatic but doesn't actually
    #   reposition correctly at most non-vanilla slots, including
    #   ground-level encampment positions.
    'c4220',  # Giant Land Octopus (XL aquatic mt=1) — XL aquatic works
              #   like the giant crabs (cf the small octopus c4230 in
              #   SENSITIVE — small aquatic broken, large aquatic safe).
    'c4480',  # Miranda Blossom (XL large_boss_ground mt=None) — XL
              #   variant works despite c4481 Miranda Sprout (M misc)
              #   being SENSITIVE. Within the Miranda family, the XL
              #   bloom-form is fine; the smaller pod-form breaks.
              #   Inverse pattern from the Envoy family (where small
              #   c3610 broke and large c3620 worked) — anim handling
              #   differs per c-prefix.
    'c4491',  # Small Jar Merchant (S humanoid mt=None) — safe.
    'c8130',  # Training Post - Small (S misc mt=None) — safe.
              #   Training posts are inert objects with no real AI;
              #   they "work" in the sense of being placeable but
              #   don't actually move. Marking SAFE for completeness;
              #   they're effectively no-op targets.
    'c8131',  # Training Post - Medium (M misc mt=None) — safe (inert).
    'c8132',  # Training Post - Large (L misc mt=None) — safe (inert).

    # === v0.20.59 RESILIENT_BIPEDS migration ===
    # Migrating the original V3_RESILIENT_BIPEDS hardcoded whitelist
    # into SAFE_CONFIRMED. These 24 c-prefixes were the original
    # "core safe at fragile slots" set established before SAFE_CONFIRMED
    # existed. Now that SAFE_CONFIRMED has grown to 140+ entries and
    # the architecture has evolved, RESILIENT becomes redundant. After
    # this migration V3_RESILIENT_BIPEDS is set to empty — the
    # production fragile filter reduces from (RESILIENT ∪ SAFE) to
    # just SAFE.
    'c3020',  # Large Exile Soldier   (RESILIENT origin: pre-SAFE-list era)
    'c3300',  # Nox Swordstress (Unscaled) (same)
    'c3371',  # Putrid Ancestral Shaman (same)
    'c3451',  # Scaly Misbegotten     (same)
    'c3600',  # Alabaster Lord (Unscaled) (same)
    'c3650',  # Guardian              (same)
    'c3661',  # Putrid Corpse         (same — note: mt=11, only non-mt=3
              #                        in original RESILIENT set)
    'c3702',  # Glintstone Sorcerer   (same)
    'c3703',  # Page                  (same)
    'c3850',  # Marionette            (same)
    'c3901',  # Fire Monk             (same — different chr from c3900
              #                        also Fire Monk also SAFE)
    'c3950',  # Man-Serpent - Whip Cool (same)
    'c4120',  # Demi-Human Chief      (same)
    'c4311',  # Godrick Soldier       (same)
    'c4313',  # Leyndell Soldier      (same)
    'c4314',  # Radahn Soldier        (same)
    'c4315',  # Mausoleum Soldier     (same)
    'c4371',  # Godrick Foot Soldier  (same)
    'c4372',  # Raya Lucaria Foot Soldier (same)
    'c4373',  # Leyndell Foot Soldier (same — the original "baseline"
              #                        c-prefix used for non-fragile
              #                        diagnostic-mode forced placement)
    'c4374',  # Radahn Foot Soldier   (same)
    'c4375',  # Mausoleum Foot Soldier (same)
    'c4377',  # Highwayman            (same)
    'c4384',  # Glintstone Digger     (same — M variant; cf c4383 S
              #                        variant in the v0.20.48 mt=3
              #                        bulk-add)
}


# v0.20.48: floater-class c-prefixes preferred at off-mesh slots.
# Off-mesh slots have no navmesh poly under them; ground-walking AI
# can't path. Floaters/aerial enemies don't need navmesh — they hover
# or drift via positional physics. Spawning a jellyfish at an off-mesh
# slot works; spawning a Foot Soldier at the same slot freezes.
#
# At off-mesh slots in PRODUCTION mode, the engine prefers picking from
# this set IF compat allows. If no compat overlap with the slot's pool,
# falls back to standard fragile filter (RESILIENT ∪ SAFE_CONFIRMED).
#
# Diagnostic mode behavior is unchanged — off-mesh slots follow normal
# diagnostic routing (untested-only or batch). The off-mesh-floater
# preference is production-side only.
# v0.24.86-patch7: V3_OFF_MESH_PREFERRED_TARGETS retired.
# Was the legacy "prefer small floaters at off-mesh+fragile slots" variety
# mechanism (v0.10–v0.20). v0.20.68 emptied it "for a test run" to check
# whether v0.20.66's broader SENSITIVE-exclusion was sufficient on its own.
# After ~64 minor versions with no restoration and no freeze regression,
# the test result is implicit: SAFE filter alone suffices. The 8-entry
# archive (c4180/c4181 Jellyfish, c4200/c4201 Bats, c4170 Putrid Flesh,
# c4040 Slug, c3080/c5870 Imps) is preserved in git history if a future
# floater-preference mechanism wants to consult it.
#
# Removed along with: V3_OFF_MESH_PREFERRED_PLACEMENT_CAP (the paired
# tighter cap), the dead floater-pool branch in pick_target_cp, and the
# dead per-cprefix cap dispatch.


V3_FRAGILE_SOURCE_QUALIFIERS = {
    # Slot-context qualifiers seen in vanilla source variant variant_names.
    # Coverage: ~95 source slots in vanilla NR have one of these.
    'Cathedral', 'Mine', 'Crater', 'Encampment', 'Fort',
    'Mountaintop', 'Ruins', 'Noklateo',
}

# v0.19.3: Sub-surface scripted-emergence detection. Vanilla NR uses negative
# y-coordinates (sub-surface positions) for slots whose authored enemies have
# rise-from-ground emergence animations: Slugs, Fingercreepers, Magma Fire
# Prelates, Guilty (magma-earth respawn), etc. The slot's spawn script fires
# the emergence anim and elevates the entity to surface y on activation.
#
# When randomized to a non-emergence-class target, the new c-prefix spawns at
# the sub-surface position but never rises — appears stuck underground or as
# a flat partial mesh. v0.19.1 playtest seed 162498 had this fail at multiple
# crater slots in m60_43_38_20 (74 sub-surface slots total).
#
# Threshold y < -10 catches all observed emergence slots (the lowest is
# y = -246.9 at m48_50). y between -10 and 0 might be slope artifacts rather
# than emergence slots, so we use -10 as the boundary to avoid false positives.
V3_SUBSURFACE_Y_THRESHOLD = -10.0

# v0.20.0: V3_EMERGENCE_COMPATIBLE_TARGETS retired (sub-surface emergence
# handled by per-slot data / chr-tag attributes, no separate set needed).
# v0.24.86-patch7: removed; no remaining code references.

# v0.23.71: default baseline c-prefix for non-fragile slots when the
# user enables the "diagnostic mode" (disable_resilient_filter=True).
# Forces every non-fragile slot to this c-prefix so the world is
# visually uniform at safe locations and any non-baseline enemy in-game
# is by construction a fragile-slot test placement. c4373 is Leyndell
# Foot Soldier — a recognizable, low-aggression mob that won't
# accidentally one-shot the player while traversing safe slots.
#
# Previously this constant was hardcoded inside the GUI (oops_rando_gui.py
# line 2483). Moved into the engine so balance/content decisions live
# next to other engine constants and the GUI can be a thin presentation
# layer.
V3_DEFAULT_NON_FRAGILE_BASELINE_CP = 'c4373'


# v0.23.71: validation-mode terrain test targets. The "Validation" run
# mode places known-broken c-prefixes everywhere we consider safe; if a
# slot freezes at on_mesh, that slot needs reclassification. This dict
# defines which c-prefixes the engine uses for the test:
#
#   on_mesh  → Giant Rat (c4090)
#       Known SENSITIVE — bumpy terrain / stair geometry / proximity to
#       walls reliably traps low-loco grounded enemies. If c4090 lands at
#       any "should-be on_mesh" slot without freezing, that slot was
#       genuinely safe.
#   off_mesh → Spirit Jellyfish (c4180)
#       Known SAFE everywhere — the gigasafe floater. Ignores ground
#       geometry, climbs walls, doesn't path-fail. At off_mesh slots,
#       c4180 should always work; if it freezes, something else is
#       wrong with the slot beyond terrain.
#
# Previously hardcoded in oops_rando_gui.py (line 2457/2463). Moved
# here so the engine owns content/balance decisions and the GUI is a
# thin presentation layer.
V3_VALIDATION_TERRAIN_TEST_TARGETS = {
    'on_mesh':  'c4090',  # Giant Rat
    'off_mesh': 'c4180',  # Spirit Jellyfish
}


V3_FRAGILE_MAPS = {
    # NR cathedral interior + subterranean/tunnel maps. All slots in these
    # MSBs get target restriction to V3_RESILIENT_BIPEDS (production rando)
    # OR force-off-mesh classification (terrain test mode).
    #
    # v0.19.9: expanded based on terrain-test playtest evidence. Original 5
    # were cathedrals + Maris-area subterranean. Added: tunnels (m20_xx,
    # m21_xx connector maps), Stormveil-equivalent castle (m15_00), and
    # underground dungeons (m30_00, m30_30). Total slot coverage now ~530.
    #
    # Kept in sync with build_slot_terrain.py FORCE_OFF_MESH_MAPS.
    'm38_00_00_00.msb',  # Cathedral interior 1
    'm38_10_00_00.msb',  # Cathedral interior 2
    'm32_00_00_00.msb',  # Subterranean 1
    'm32_10_00_00.msb',  # Subterranean 2 (also Maris arena — V3_SHARED_ARENA_MAPS preserves Maris, this preserves surrounding slots)
    'm32_20_00_00.msb',  # Subterranean 3
    'm15_00_00_00.msb',  # Castle interior (Stormveil-equivalent, 52 slots)
    # Tunnels — m20_xx series (v0.19.9)
    'm20_00_00_00.msb', 'm20_10_00_00.msb', 'm20_20_00_00.msb',
    'm20_30_00_00.msb', 'm20_40_00_00.msb', 'm20_50_00_00.msb',
    'm20_60_00_00.msb', 'm20_70_00_00.msb', 'm20_80_00_00.msb',
    'm20_90_00_00.msb',
    # More tunnels — m21_xx series
    'm21_00_00_00.msb', 'm21_10_00_00.msb', 'm21_20_00_00.msb',
    'm21_30_00_00.msb', 'm21_40_00_00.msb', 'm21_50_00_00.msb',
}


# v0.20.73: Shifting Earth event MSBs auto-added to V3_FRAGILE_MAPS.
# When the user activates Mountaintops/Crater/Noklateo as the run's
# Shifting Earth, the affected m60_xx Limveld tiles get loaded with
# steeply-sloped (Crater), elevated/snowfield (Mountaintop), or
# vertical-architecture (Noklateo) geometry that breaks pathing for
# SENSITIVE-class c-prefixes regardless of POI proximity. User
# requested blanket SAFE-only treatment for those entire tiles after
# a launch CTD on a Mountaintop run.
#
# Detection: scan t1_anchors.json for any anchor whose qualifier is
# in V3_SHIFTING_EARTH_QUALIFIERS. Any MSB containing such an anchor
# is added to V3_FRAGILE_MAPS at module load. Cathedral / Encampment /
# Ruins / Fort / Mine are intentionally excluded — those are static
# overworld POIs that already have proximity coverage and shouldn't
# blanket-fragile their containing m60_xx tile.
V3_SHIFTING_EARTH_QUALIFIERS = ('Crater', 'Mountaintop', 'Noklateo')

def _populate_shifting_earth_fragile_maps():
    """Extend V3_FRAGILE_MAPS with Shifting Earth Limveld variants.

    Convention discovered via anchor scan: m60_xx_xx_10.msb is the
    Mountaintops Shifting Earth variant, _20 is Crater, _50 is Noklateo.
    The convention holds across all m60_xx tile coordinates. Any tile
    that has a Shifting Earth-qualified anchor in one variant means
    that variant suffix represents the Shifting Earth event for ALL
    m60_xx tiles, not just the one with the anchor — because Shifting
    Earth events reshape the entire Limveld map, so every m60_xx tile
    has an _N variant for each event regardless of whether that tile
    contains a qualifier-tagged enemy.

    Discovery: scan t1_anchors.json for which suffixes correlate with
    Shifting Earth qualifiers. Application: enumerate all known
    m60_xx_xx_S.msb where S is in the discovered suffix set, regardless
    of whether that specific tile has an anchor.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    anchors_data_path = _data_path('t1_anchors.json')
    if not os.path.isfile(anchors_data_path):
        return 0
    try:
        with open(anchors_data_path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0
    # Discover suffix → SE-qualifier convention
    se_suffixes = set()
    for msb, lst in data.get('maps', {}).items():
        if not msb.startswith('m60_'):
            continue
        # Suffix is e.g. '_10.msb', '_20.msb', '_50.msb' — last 7 chars.
        suffix = msb[-7:] if len(msb) >= 7 else ''
        for anchor in lst:
            if any(q in V3_SHIFTING_EARTH_QUALIFIERS
                   for q in anchor.get('quals', [])):
                se_suffixes.add(suffix)
                break
    if not se_suffixes:
        return 0
    # Enumerate all m60 MSBs and add ones matching SE suffix.
    # Source the MSB list from nr_all_slots.json (every recipient slot
    # entry carries its msb path) — broader coverage than t1_anchors,
    # which only has anchor-bearing MSBs.
    slots_path = _data_path('nr_all_slots.json')
    msb_list = set()
    if os.path.isfile(slots_path):
        try:
            with open(slots_path, encoding='utf-8') as f:
                slots = json.load(f)
            for s in slots:
                m = s.get('map')
                if m:
                    msb_list.add(m)
        except (OSError, json.JSONDecodeError):
            pass
    added = 0
    for m in msb_list:
        if not m.startswith('m60_'):
            continue
        if any(m.endswith(suf) for suf in se_suffixes):
            if m not in V3_FRAGILE_MAPS:
                V3_FRAGILE_MAPS.add(m)
                added += 1
    return added

_v3_se_added = _populate_shifting_earth_fragile_maps()

# v0.20.47: per-slot navmesh fragility, derived from build_slot_terrain.py.
# slot_terrain.json classifies every vanilla slot by its position relative
# to the navmesh. An enemy spawned off the navmesh can't path to the player
# — even safest-possible c-prefixes (Foot Soldier etc.) freeze when the AI
# can't find a navmesh poly under them. This is INDEPENDENT from c-prefix
# fragility — it's slot-side terrain fragility.
#
# DIAGNOSTIC FINDING: user observed Foot Soldier (c4373, RESILIENT) freezing
# at a Limveld m60_xx Cathedral slot. Cross-ref showed 562 off-mesh slots
# in maps NOT in V3_FRAGILE_MAPS — most in m60_xx procedural. Foot Soldier
# was forced to the off-mesh slot via the diagnostic baseline mode and
# predictably failed.
#
# INTEGRATION: is_fragile_slot consults V3_OFF_MESH_SLOTS in addition to
# V3_FRAGILE_MAPS. A slot is fragile if EITHER the map is fragile OR the
# specific slot is off-mesh. Set is loaded lazily from slot_terrain.json
# on first use.
V3_OFF_MESH_SLOTS = None  # populated on first call to _load_off_mesh_slots()
V3_OFF_MESH_STATUSES = frozenset({
    'force_off_mesh',  # map has no navmesh — fragile by definition
    'off_mesh',        # slot off-mesh in a map with navmesh — likely fragile
    # proximity_off_mesh and no_match deliberately NOT included for now —
    # softer signal, would over-include. Add if data warrants.
})

# v0.20.66: V3_OFF_MESH_FALSE_POSITIVE_MAP_PREFIXES retired and removed
# in v0.28.x. The list previously suppressed off-mesh classification at
# cathedral-interior m60_xx maps when v0.20.47's T2.6 made off-mesh
# slots fragile. v0.20.64 retired T2.6 and replaced it with a soft
# SENSITIVE-exclusion at off-mesh slots; v0.20.65 audit then showed the
# override was masking 60 legitimate SENSITIVE-at-off-mesh CTD vectors,
# so the list was emptied in v0.20.66 and the variable removed entirely
# in v0.28.x. See git history (CHANGELOG v0.20.65/v0.20.66) for the
# original entries and the audit that justified retirement.


# v0.20.71: POI proximity fragility radius. Slots within this distance
# of a T1-qualifier-tagged source slot inherit fragile classification.
# v0.20.71 used 60 unit radius, which caught the Demi-Human Queen
# (Crater) vicinity but missed the larger Mountaintop snowfield POI.
# v0.20.72 bumps to 100 — coverage analysis of m60_43_38_10 (the
# Mountaintop reference map) showed SENSITIVE-class placements
# clustered at d=21–32 (caught at 60) AND d=81–84 (Stray family at
# Misbegotten/Demi-Human source slots, missed at 60). The Snowfield POI
# is physically larger than the Crater Queen arena. 100 catches
# both clusters; bumping further would over-restrict normal overworld
# variety.
V3_T1_PROXIMITY_RADIUS = 100.0

_V3_T1_ANCHORS_CACHE = None


def _load_t1_anchors():
    """Lazy-load t1_anchors.json — POI proximity fragility data.

    Returns dict: msb_name → tuple of (x, y, z) anchor positions.

    Anchors are positions of vanilla source slots whose variant_name carries
    a V3_FRAGILE_SOURCE_QUALIFIERS qualifier (Cathedral, Crater, etc.).
    The qualifier identifies a boss-arena POI; surrounding mob slots
    typically don't carry the qualifier in their own variant names but
    share the geometry constraints. T2.7 in is_fragile_slot uses these
    to extend fragility to the surrounding area.

    Anchor positions are vanilla and stable across seeds — extracted
    once from a representative spoiler, shipped as t1_anchors.json.
    """
    global _V3_T1_ANCHORS_CACHE
    if _V3_T1_ANCHORS_CACHE is not None:
        return _V3_T1_ANCHORS_CACHE
    p = _data_path('t1_anchors.json')
    if not os.path.isfile(p):
        _V3_T1_ANCHORS_CACHE = {}
        return _V3_T1_ANCHORS_CACHE
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _V3_T1_ANCHORS_CACHE = {}
        return _V3_T1_ANCHORS_CACHE
    anchors = {}
    for msb, lst in data.get('maps', {}).items():
        anchors[msb] = tuple(tuple(a['pos']) for a in lst if a.get('pos'))
    _V3_T1_ANCHORS_CACHE = anchors
    return anchors


def _is_t1_proximity_fragile(slot_msb_name, slot_pos):
    """T2.7 (v0.20.71): proximity check against T1-qualifier anchor positions.

    Returns True if slot_pos is within V3_T1_PROXIMITY_RADIUS of any
    anchor in slot_msb_name. False if no anchor data, no map match,
    or out of range.
    """
    if not slot_msb_name or not slot_pos:
        return False
    anchors = _load_t1_anchors().get(slot_msb_name)
    if not anchors:
        return False
    sx, sy, sz = slot_pos
    r2 = V3_T1_PROXIMITY_RADIUS * V3_T1_PROXIMITY_RADIUS
    for ax, ay, az in anchors:
        dx = sx - ax
        dy = sy - ay
        dz = sz - az
        if dx * dx + dy * dy + dz * dz <= r2:
            return True
    return False


# T2.8 (v0.22): per-slot roughness override. Releases coarse-fragile slots
# (fragile via T1 / T2 / T2.7) back to the full target pool when their
# AABB-derived roughness signal is benign — i.e. the slot sits inside a
# wide, flat navmesh polygon, not a sloped or subdivided one.
#
# Motivation: T1/T2/T2.7 paint with a coarse brush. T1 fires for any slot
# in a fragile-zone-named source variant; T2 for whole-map flagged maps;
# T2.7 within 100u of any T1 anchor. Inside those zones there are usually
# pockets of geometrically benign ground — the flat plaza inside a
# bandit camp, the cleared area inside a Cathedral footprint — that
# don't actually break SENSITIVE chrs. T2.8 reads a per-slot navmesh
# signal and frees those benign pockets without changing the coarse
# zone definitions.
#
# Signal source: slot_terrain.json["slot_roughness"][msb][pi]["s_y"], the
# y-extent of the smallest navmesh AABB containing the slot. Generated by
# build_slot_terrain.py from .nvmhktbnd binders. A slot inside a flat
# horizontal polygon has small s_y; a slot on a sloped/cliff polygon has
# large s_y. Calibration on m60_xx (v0.22, n=442 coarse-fragile vs
# n=1545 safe slots): coarse-fragile median s_y=14.1, safe median 2.9 —
# clean 5x separation. s_xz / n10 / n20 also computed but contribute
# little extra signal and aren't used in scoring.
#
# Threshold (V3_T2_8_S_Y_THRESHOLD = 1.0) is conservative for v0.22 ship:
# - releases ~15% of coarse-fragile slots (67/442 in calibration)
# - sits inside the safe-distribution p25 (which is ~1.0)
# - 85% of coarse-fragile slots stay restricted
# Loosen to 1.5–2.0 in v0.23 if playtest shows the conservative cut is
# too tight; tighten to 0.5 if playtest reveals false-positive releases.
#
# Scope: T2.8 releases ONLY slots that became fragile via T1 / T2 / T2.7.
# Off-mesh-classified slots (V3_OFF_MESH_SLOTS) are NOT in scope and
# remain handled by the soft SENSITIVE-exclusion in pick_target_cp.
# V3_PROBLEM_SLOTS (T3) and edge-sentinel positions (T2.5) are also
# never released — those are explicit hand-curated overrides.
V3_T2_8_S_Y_THRESHOLD = 1.0

_V3_ROUGHNESS_CACHE = None


def _load_slot_roughness():
    """Lazy-load the per-slot roughness map from slot_terrain.json.

    Returns dict: (msb_name, part_index) → s_y float. Slots without a
    containing leaf (no entry in slot_roughness) are simply absent — they
    have no T2.8 verdict and the existing fragility tiers govern.
    """
    global _V3_ROUGHNESS_CACHE
    if _V3_ROUGHNESS_CACHE is not None:
        return _V3_ROUGHNESS_CACHE
    path = _data_path('slot_terrain.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _V3_ROUGHNESS_CACHE = {}
        return _V3_ROUGHNESS_CACHE
    out = {}
    for msb, slot_dict in data.get('slot_roughness', {}).items():
        for pi_str, info in slot_dict.items():
            sy = info.get('s_y')
            if sy is None:
                continue
            try:
                out[(msb, int(pi_str))] = float(sy)
            except (ValueError, TypeError):
                pass
    _V3_ROUGHNESS_CACHE = out
    return _V3_ROUGHNESS_CACHE


# v0.24.86-patch6.1: per-slot polygon slope (in degrees), populated by
# dev/augment_slot_terrain_with_polygons.py. Sloped boss-arena floors
# are unsafe for size-up swaps — the L+ chr collider clips or slides
# at slopes >= ~15°. Cached on first access; stays empty {} if the
# slot_terrain.json doesn't have polygon fields yet (pre-patch6.1 data).
_V3_SLOPE_CACHE = None
V3_SLOPED_SIZE_UP_THRESHOLD = 15.0  # degrees; tighter cutoff catches more
                                     # FP. Calibrated to Zamor freeze at
                                     # 20.1° with margin; under threshold:
                                     # test_night_boss_tier_unaffected slot
                                     # m32_00 pi=31 at 3.3°.


def _load_slot_slope():
    """Lazy-load per-slot polygon slope (degrees) from slot_terrain.json
    if the file has been polygon-augmented by patch6.1's build step.

    Returns dict: (msb_name, part_index) -> slope_deg float.
    Slots without polygon data are simply absent.
    """
    global _V3_SLOPE_CACHE
    if _V3_SLOPE_CACHE is not None:
        return _V3_SLOPE_CACHE
    path = _data_path('slot_terrain.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _V3_SLOPE_CACHE = {}
        return _V3_SLOPE_CACHE
    out = {}
    for msb, slot_dict in data.get('slot_roughness', {}).items():
        for pi_str, info in slot_dict.items():
            sl = info.get('slope_deg')
            if sl is None:
                continue
            try:
                out[(msb, int(pi_str))] = float(sl)
            except (ValueError, TypeError):
                pass
    _V3_SLOPE_CACHE = out
    return _V3_SLOPE_CACHE


def _get_slot_slope_deg(msb_name, pi):
    """Return slope_deg for a slot or None if no polygon data."""
    if msb_name is None or pi is None:
        return None
    return _load_slot_slope().get((msb_name, pi))


# v0.24.86-patch8: wedged-against-wall and elevated-rampart gates.
# Both use the AABB+polygon composite signals calibrated by the
# v0.23.88 m30_xx Fort tile analysis (chat b2e767c9, 2026-05-13).
V3_WEDGED_D_XZ_EDGE_MAX = 0.5     # AABB: distance to leaf edge in XZ
V3_WEDGED_REACH_5M_MAX  = 2       # polygon: connected faces within 5m
V3_ELEVATED_FRAC_MIN    = 0.5     # AABB: position in upper half of leaf Y
V3_ELEVATED_LEAF_XZ_MAX = 16.0    # AABB: max XZ extent of leaf

# Gate 7.6 (wedged-against-wall) / Gate 7.7 (elevated-rampart) per-slot
# lookup. Cached on first access. Each entry is (d_xz_edge, reach5m,
# elev_frac, leaf_xz) — None for fields not present in slot_terrain.json
# (e.g. pre-AABB-augment data).
_V3_GEOMETRY_CACHE = None


def _load_slot_geometry():
    """Lazy-load AABB+polygon composite metrics for the wedged and
    elevated gates. Returns dict keyed by (msb_name, part_index) with
    a 4-tuple (d_xz_edge, reach_count_5m, elev_frac, leaf_xz). Slots
    without all four fields default the missing ones to None and the
    relevant gate degrades to no-op for that slot.
    """
    global _V3_GEOMETRY_CACHE
    if _V3_GEOMETRY_CACHE is not None:
        return _V3_GEOMETRY_CACHE
    path = _data_path('slot_terrain.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _V3_GEOMETRY_CACHE = {}
        return _V3_GEOMETRY_CACHE
    out = {}
    for msb, slot_dict in data.get('slot_roughness', {}).items():
        for pi_str, info in slot_dict.items():
            try:
                pi = int(pi_str)
            except (ValueError, TypeError):
                continue
            out[(msb, pi)] = (
                info.get('d_xz_edge'),
                info.get('reach_count_5m'),
                info.get('elev_frac'),
                info.get('leaf_xz'),
            )
    _V3_GEOMETRY_CACHE = out
    return _V3_GEOMETRY_CACHE


def _is_slot_wedged(msb_name, pi):
    """Gate 7.6 predicate: True if slot trips the wedged-against-wall
    composite. False on missing data (safe default)."""
    if msb_name is None or pi is None:
        return False
    geom = _load_slot_geometry().get((msb_name, pi))
    if geom is None:
        return False
    d_xz, reach5, _, _ = geom
    if d_xz is None or reach5 is None:
        return False
    return d_xz < V3_WEDGED_D_XZ_EDGE_MAX and reach5 <= V3_WEDGED_REACH_5M_MAX


def _is_slot_elevated(msb_name, pi):
    """Gate 7.7 predicate: True if slot trips the elevated-rampart
    composite. False on missing data."""
    if msb_name is None or pi is None:
        return False
    geom = _load_slot_geometry().get((msb_name, pi))
    if geom is None:
        return False
    _, _, elev, lxz = geom
    if elev is None or lxz is None:
        return False
    return elev > V3_ELEVATED_FRAC_MIN and lxz < V3_ELEVATED_LEAF_XZ_MAX


# v0.24.86-patch9: stub-nav tile detection. Cave/dungeon tiles
# (m46_/m48_/m49_ family) ship with empty navmesh + empty onav. Any
# tile not represented in slot_terrain.json's slot_roughness map is
# stub-nav by construction (it was processed by the augment pipeline
# but produced no metric entries).
_V3_NAV_TILE_CACHE = None


def _load_nav_tile_set():
    """Lazy-load the set of MSB filenames that DO have non-stub
    navmesh data (i.e. at least one slot in slot_terrain.json's
    slot_roughness). A slot is on a stub-nav tile iff its MSB is
    NOT in this set."""
    global _V3_NAV_TILE_CACHE
    if _V3_NAV_TILE_CACHE is not None:
        return _V3_NAV_TILE_CACHE
    path = _data_path('slot_terrain.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _V3_NAV_TILE_CACHE = set()
        return _V3_NAV_TILE_CACHE
    out = set()
    for msb, slot_dict in data.get('slot_roughness', {}).items():
        if slot_dict:  # has at least one slot entry
            out.add(msb)
    _V3_NAV_TILE_CACHE = out
    return _V3_NAV_TILE_CACHE


def _is_stub_nav_slot(msb_name):
    """True if the given MSB ships with stub navmesh data (cave/dungeon
    family). Defensive: returns False if slot_terrain.json is missing
    or empty, so the gate degrades to no-op rather than rejecting
    everything."""
    if msb_name is None:
        return False
    nav_tiles = _load_nav_tile_set()
    if not nav_tiles:
        # No data loaded — can't classify, don't fire
        return False
    return msb_name not in nav_tiles


# v0.24.86-patch9: c-prefixes whose AI doesn't require navmesh
# pathfinding to function. Empirically derived from vanilla NR cave-
# tile (m46/m48/m49) placements in seed 923630 — any chr vanilla
# ships in a stub-nav tile is by construction set-piece scripted AI
# that works without navmesh queries.
#
# Cave-tile AI failure mode: chr spawns OK (collision-based), wakes
# on aggro (event-driven), then queries navmesh for path-to-player
# and gets nothing back. Pursuit AI state stalls → effective freeze.
#
# Expand this set when playtest confirms additional chrs as
# nav-independent. Contract it (move chrs out) when playtest shows
# a chr in this set DOES freeze in caves.
V3_NAV_INDEPENDENT_TARGETS = frozenset({
    # Empirically derived from vanilla NR cave-tile (m46/m48/m49)
    # placements in seed 923630 spoiler, plus curated variants of
    # set-piece chrs. Expand from playtest reports.
    'c2100',  # vanilla M    Black Knife Assassin (Unscaled
    'c2130',  # vanilla XL   Margit
    'c2140',  # vanilla L    Omen
    'c2276',  # vanilla XXL  Giant Death Crab
    'c2500',  # vanilla M    Crucible Knight (Unscaled)
    'c2510',  # curated ?    ?
    'c2520',  # curated ?    ?
    'c3000',  # vanilla M    Exile Soldier
    'c3010',  # vanilla M    Banished Knight
    'c3020',  # vanilla M    Large Exile Soldier
    'c3030',  # curated ?    ?
    'c3060',  # vanilla M    Giant Skeleton
    'c3080',  # vanilla S    Imp
    'c3100',  # vanilla L    Elemer of the Briar
    'c3150',  # vanilla M    Night's Cavalry
    'c3181',  # vanilla L    Red Wolf of Radagon
    'c3250',  # vanilla XL   Draconic Tree Sentinel (Unscal
    'c3251',  # vanilla XL   Tree Sentinel (Unscaled)
    'c3252',  # vanilla XL   Loretta Tree Sentinel (Unscale
    'c3300',  # vanilla M    Nox Swordstress (Unscaled)
    'c3320',  # vanilla S    Silver Tear (Unscaled)
    'c3350',  # vanilla L    Crystalian
    'c3400',  # vanilla M    Grave Warden Duelist
    'c3450',  # vanilla M    Misbegotten
    'c3451',  # vanilla M    Scaly Misbegotten
    'c3460',  # vanilla M    Leonine Misbegotten
    'c3500',  # vanilla M    Large Skeleton (Spear)
    'c3560',  # vanilla L    Godskin Apostle (Unscaled)
    'c3570',  # vanilla XL   Godskin Noble (Unscaled)
    'c3600',  # vanilla L    Alabaster Lord (Unscaled)
    'c3650',  # vanilla M    Guardian
    'c3661',  # vanilla M    Putrid Corpse
    'c3662',  # vanilla M    Putrid Corpse (Large)
    'c3664',  # vanilla M    Cemetery Shade
    'c3700',  # vanilla M    Depraved Perfumer
    'c3701',  # vanilla M    Perfumer
    'c3703',  # vanilla M    Page
    'c3901',  # vanilla M    Fire Monk
    'c3950',  # vanilla M    Man-Serpent - Whip Cool
    'c3970',  # vanilla M    Azula Beastman
    'c4020',  # vanilla L    Royal Revenant
    'c4021',  # vanilla XL   Royal Revenant
    'c4040',  # vanilla S    Slug
    'c4080',  # vanilla S    Rat
    'c4090',  # vanilla M    Giant Rat
    'c4100',  # vanilla S    Demi-Human
    'c4101',  # vanilla M    Large Demi-Human
    'c4110',  # vanilla XS   Demi-Human Shaman
    'c4120',  # vanilla M    Demi-Human Chief
    'c4130',  # vanilla XL   Demi-Human Queen
    'c4161',  # vanilla S    Stray
    'c4240',  # vanilla XL   Fingercreeper
    'c4241',  # vanilla GIGA Giant Fingercreeper
    'c4250',  # vanilla S    Small Fingercreeper
    'c4270',  # vanilla L    Elder Lion
    'c4280',  # vanilla L    Giant Ant
    'c4281',  # vanilla XL   Skull Plate Giant Ant
    'c4290',  # vanilla S    Bloodhound Knight
    'c4300',  # vanilla M    Wandering Noble
    'c4313',  # vanilla M    Leyndell Soldier
    'c4353',  # vanilla M    Leyndell Knight
    'c4373',  # vanilla M    Leyndell Foot Soldier
    'c4380',  # vanilla S    Starcaller
    'c4480',  # vanilla XL   Miranda Blossom
    'c4481',  # vanilla M    Miranda Sprout
    'c4490',  # vanilla L    Living Jar Warrior
    'c4500',  # vanilla GIGA Flying Dragon (Unscaled)
    'c4510',  # vanilla GIGA Ancient Dragon
    'c4550',  # vanilla XL   Giant Dog
    'c4560',  # vanilla XL   Giant Crow
    'c4580',  # vanilla GIGA Giant Wormface
    'c4600',  # vanilla XXL  Troll
    'c4640',  # vanilla XXL  Ulcerated Tree Spirit
    'c4650',  # vanilla XXL  Dragonkin Soldier (Ice Lightni
    'c4660',  # vanilla GIGA Guardian Golem
    'c4680',  # vanilla GIGA Full-Grown Fallingstar Beast (
    'c4750',  # vanilla L    Godrick the Grafted (Unscaled)
    'c4770',  # vanilla XXL  Gargoyle
    'c4810',  # vanilla XL   Erdtree Avatar
    'c4910',  # vanilla GIGA Magma Wyrm
    'c4911',  # vanilla GIGA Great Wyrm Theodorix
    'c4980',  # vanilla XXL  Death Bird
    'c5011',  # vanilla XXL  Golden Hippopotamus (Golden Wi
    'c5060',  # curated ?    ?
    'c5061',  # curated ?    ?
    'c5161',  # curated ?    ?
    'c5810',  # vanilla XS   Demi-Human Swordmaster Onze
    'c7100',  # vanilla L    Ancient Hero of Zamor (Base)
    'c3610',  # test-confirmed grunt      M    Oracle Envoy (cave-arena slots)
    'c4602',  # test-confirmed field_boss XXL  Snowfield Troll (cave-arena slots)
    'c7700',  # test-confirmed night_boss GIGA Gaping Dragon (cave-arena slots)
    'c7710',  # test-confirmed night_boss GIGA Centipede Demon (cave-arena slots)
    # v0.26.x-late: arena-bound bosses imported via MMV / heritage
    # packs. Sim (dev/sim_reservation_health.py) surfaced that these
    # chrs were 100% unplaced from reservation because NB-strict
    # markers in vanilla NR predominantly land at cave/dungeon-tile
    # MSBs (stub navmesh), and these MMV chrs weren't on the
    # nav-independent list. They're all fixed-arena boss-style chrs
    # (no roaming AI / no patrol patterns) so navmesh queries aren't
    # actually needed by their combat AI — adding them to this set
    # lets the reservation pass seat them at the NB-strict slots
    # they need.
    'c2030',  # MMV ER     M    Rennala, Queen of the Full Moon
    'c2031',  # MMV ER     M    Rennala (Phase 2)
    'c2110',  # MMV ER     M    Beast Clergyman / Maliketh
    'c2120',  # MMV ER     M    Malenia, Blade of Miquella
    'c4511',  # MMV ER     XXL  Lichdragon Fortissax
    'c5000',  # MMV SoTE   XL   Commander Gaius
    'c5030',  # MMV SoTE   M    Romina, Saint of the Bud
    'c5051',  # MMV SoTE   M    Midra, Lord of Frenzied Flame
    'c5130',  # MMV ER     M    Messmer the Impaler
    'c5200',  # MMV SoTE   XL   Metyr, Mother of Fingers
    'c5300',  # MMV SoTE   M    Rellana, Twin Moon Knight
    'c6200',  # MMV DS3    M    Slave Knight Gael
    'c8300',  # MMV DS3    L    Dragonslayer Armor
    # v0.27.35: SOTE miniboss-tier chrs added to unblock the m49_43 castle
    # Crucible room in all-SOTE mode (10 c2500 slots pinned miniboss; the
    # stub-nav gate was rejecting every SOTE miniboss as nav-dependent, so
    # the room shipped vanilla — observed seed 435226). Alaric direction:
    # add all 15 and playtest, reporting any that freeze. NOT yet
    # playtest-confirmed nav-safe; if any of these T-pose/idle in a stub-nav
    # cave/castle tile, remove it from this set with a (seed, msb, pi) cite.
    'c5040',  # SoTE   M    Curseblade
    'c5070',  # SoTE   M    Death Knight
    'c5081',  # SoTE   XL   Chief Bloodfiend
    'c5160',  # SoTE   M    Fire Knight
    'c5250',  # SoTE   M    Horned Warrior
    'c5260',  # SoTE   L    Golem Smith
    'c5311',  # SoTE   M    Inquisitor (Candles)
    'c5312',  # SoTE   M    Inquisitor (Staff)
    'c5360',  # SoTE   L    Giant Beast Skeleton
    'c5450',  # SoTE   L    Ram
    'c5511',  # SoTE   M    Shade
    'c5512',  # SoTE   M    Shade
    'c5820',  # SoTE   XXL  Great Red Bear
    'c5872',  # SoTE   L    Imp (Large)
})


def _is_t2_8_releasable(slot_msb_name, slot_pi):
    """T2.8: returns True if this slot's per-slot roughness is benign
    enough to override coarse-fragile classification.

    Note this only considers the navmesh signal — the caller is
    responsible for ensuring T2.8 is only consulted when the slot is
    coarse-fragile (T1/T2/T2.7) and not in the off-mesh / edge-sentinel /
    V3_PROBLEM_SLOTS scopes.
    """
    sy = _load_slot_roughness().get((slot_msb_name, slot_pi))
    if sy is None:
        return False
    return sy < V3_T2_8_S_Y_THRESHOLD


def _load_off_mesh_slots():
    """Lazy-load the off-mesh slot set from slot_terrain.json.

    Returns frozenset of (msb_name, part_index) tuples whose status is
    in V3_OFF_MESH_STATUSES. Cached as a module-level global so the
    JSON parse only happens once per engine invocation.
    """
    global V3_OFF_MESH_SLOTS
    if V3_OFF_MESH_SLOTS is not None:
        return V3_OFF_MESH_SLOTS
    path = _data_path('slot_terrain.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Engine should still work without slot_terrain.json — just no
        # off-mesh fragility detection. Cache empty set so we don't
        # retry on every call.
        V3_OFF_MESH_SLOTS = frozenset()
        return V3_OFF_MESH_SLOTS
    out = set()
    for msb, slot_dict in data.get('off_mesh_slots', {}).items():
        for pi_str, info in slot_dict.items():
            if info.get('status') in V3_OFF_MESH_STATUSES:
                try:
                    out.add((msb, int(pi_str)))
                except ValueError:
                    pass
    V3_OFF_MESH_SLOTS = frozenset(out)
    return V3_OFF_MESH_SLOTS


# v0.31: wake-rescuable enemy set, derived from ThrowParam backstab data.
# An enemy that the proximity wake can actually un-freeze is one a player
# could backstab — both force the same AI state transition. backstab_tiers.json
# (generated from ThrowParam: throwType 24 = backstab-from-behind) tiers every
# throwable chr; the `full_backstab` tier (24-count >= 4, the humanoid 8-
# directional cluster) is the set that empirically wakes. Used to gate off-mesh
# slots: with slot repositions retired, an off-mesh part is left at its vanilla
# position, so only enemies the wake can rescue are allowed to land there.
V3_BACKSTAB_RESCUABLE_PREFIXES = None  # populated on first call to the loader


def _load_backstab_rescuable_prefixes():
    """Lazy-load the full-backstab (wake-rescuable) c-prefix set.

    Returns a frozenset of c-prefixes (e.g. 'c4373') whose tier in
    data/backstab_tiers.json is 'full_backstab'. Cached as a module-level
    global so the JSON parse only happens once per engine invocation
    (mirrors _load_off_mesh_slots).
    """
    global V3_BACKSTAB_RESCUABLE_PREFIXES
    if V3_BACKSTAB_RESCUABLE_PREFIXES is not None:
        return V3_BACKSTAB_RESCUABLE_PREFIXES
    path = _data_path('backstab_tiers.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Without the tier file we can't identify the rescuable pool. Cache
        # an empty set; the off-mesh gate treats empty as "no restriction
        # data" and falls through (see pick_target_cp) rather than blanking
        # every off-mesh slot.
        V3_BACKSTAB_RESCUABLE_PREFIXES = frozenset()
        return V3_BACKSTAB_RESCUABLE_PREFIXES
    out = {cp for cp, info in data.get('chrs', {}).items()
           if isinstance(info, dict) and info.get('tier') == 'full_backstab'}
    V3_BACKSTAB_RESCUABLE_PREFIXES = frozenset(out)
    return V3_BACKSTAB_RESCUABLE_PREFIXES


# v0.27.4: per-slot face_dist cache for the geometry-aware size gate.
_V3_SLOT_FACE_DIST = None  # populated on first call to _load_slot_face_dist()


def _load_slot_face_dist():
    """Lazy-load per-slot `face_dist` (metres to the nearest collision
    face) from slot_terrain.json's `slot_roughness` block.

    Returns a dict {(msb_name, part_index): face_dist}. Slots absent
    from the map have no terrain data — the geometry size gate treats a
    missing entry as "no geometry proof available" and falls back to the
    strict vanilla baseline. Cached as a module global so the JSON parse
    happens once per engine invocation (mirrors _load_off_mesh_slots).
    """
    global _V3_SLOT_FACE_DIST
    if _V3_SLOT_FACE_DIST is not None:
        return _V3_SLOT_FACE_DIST
    out = {}
    path = _data_path('slot_terrain.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Engine still works without slot_terrain.json — the geometry
        # gate just degrades to the pure vanilla-occupant baseline.
        _V3_SLOT_FACE_DIST = out
        return out
    for msb, slot_dict in data.get('slot_roughness', {}).items():
        if not isinstance(slot_dict, dict):
            continue
        for pi_str, metrics in slot_dict.items():
            if not isinstance(metrics, dict):
                continue
            fd = metrics.get('face_dist')
            if fd is None:
                continue
            try:
                out[(msb, int(pi_str))] = float(fd)
            except (ValueError, TypeError):
                continue
    _V3_SLOT_FACE_DIST = out
    return out


def _geometry_capacity_rank(face_dist):
    """Highest V3_SIZE_RANK a slot can host given `face_dist` — the
    largest size class whose V3_SIZE_FOOTPRINT_RADIUS fits within the
    distance to the nearest collision face. Returns -1 if not even XS
    fits. Footprint radius is monotonic in rank, so the scan can stop
    at the first class that doesn't fit.
    """
    cap = -1
    for sc in ('XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA'):
        if V3_SIZE_FOOTPRINT_RADIUS[sc] <= face_dist:
            cap = V3_SIZE_RANK[sc]
        else:
            break
    return cap


# v0.20.14: prefix-based companion to V3_FRAGILE_MAPS. Same effect (T2
# whole-map fragility — restricts targets to V3_RESILIENT_BIPEDS) but
# matches by msb-name prefix instead of exact name. Use this when an
# entire map range is known to be fragile but the exact file list hasn't
# been enumerated yet — we'll convert to explicit entries above once
# build_slot_terrain.py is updated and we know which m45_XX files
# actually exist.
#
# 'm45_' added after the v0.20.12 spawn-marker fix surfaced that m45_xx
# tunnels still have a separate problem class: real-placement slots
# accepting non-resilient targets (Maris' Tendril standalone, Giant
# Silver Tear in tunnel boss room, Rotten Stray Large in chamber). The
# v0.19.9 m20_xx/m21_xx FRAGILE_MAPS expansion missed m45_xx by
# omission — same kind of map, same kind of fix.
#
# TODO: enumerate explicit m45_XX_00_00.msb entries and move them into
# V3_FRAGILE_MAPS above; sync with build_slot_terrain.py FORCE_OFF_MESH_MAPS.
V3_FRAGILE_MAP_PREFIXES = {
    'm45_',  # Tunnel range — see note above.
    # NOTE: trailing '_' is load-bearing. 'm45_' won't match 'm450_xx',
    # 'm451_xx', etc. — only 'm45_XX_YY_ZZ.msb'. Don't strip the
    # underscore unless you intentionally want broader coverage.
    # v0.20.74: Limveld cathedral POI tile coordinates. These tile
    # coords (44,37 / 45,37 / 45,38 / 45,39) host indoor cathedral
    # POIs across all 5 procedural variants (_00/_10/_20/_30/_50). The
    # source variant names are generic ('Exile Soldier', 'Putrid
    # Corpse', etc.) — no '(Cathedral)' qualifier — so neither T1
    # qualifier-fragility nor the Shifting Earth blanket catches them.
    # User CTD report: cathedral CTD on a run where Shifting Earth was
    # NOT cathedral-aligned, meaning the baseline (_00) or Rotted Woods
    # (_30) variant was loaded. Spoiler audit confirmed heavy SENSITIVE
    # placement at these tiles (24 in m60_45_37_30 alone). Trailing '_'
    # is load-bearing — 'm60_44_37_' matches all 5 variants but not
    # 'm60_44_370_' or other coord prefixes.
    'm60_44_37_',  # original cathedral tile (user screenshot, m60_44_37 cluster)
    'm60_45_37_',  # adjacent cathedral coord
    'm60_45_38_',  # ditto
    'm60_45_39_',  # ditto
}

# v0.20.15: shared-position placeholder threshold. Per-MSB pre-pass counts
# how many non-clustered Parts share each rounded position; any position
# shared by >= this many Parts is treated as a script-spawn placeholder
# block (the spawn script reads NPCParam from each placeholder to type-
# check what to summon). Threshold 3 catches the m15_00 castle 39-block
# cleanly while leaving real twin spawns alone. Tighten to 2 only if a
# spoiler shows a 2-Part cluster causing real bugs.
V3_PLACEHOLDER_POSITION_THRESHOLD = 3

# v0.23.60: cap on OOPS_ALL_NB intercepts at the same placeholder position.
# Background: v0.23.58 hoisted the OOPS_ALL_NB catalog intercept ABOVE
# the placeholder-position skip so catalogued boss slots in FIA-modified
# spawn-pool MSBs wouldn't get silently dropped. Side effect: m15_00's
# 39-Part script-spawn placeholder block at (52.11, 0.3, 26.57) — which
# IS catalogued as boss-tier (each Part is a placeholder slot the spawn
# script reads to type-check what to summon) — now gets ALL its slots
# stamped with the OOPS_ALL_NB target c-prefix. With XL targets like
# c4720 Godfrey, the engine tries to load 30+ instances at one point
# and CTDs on cell load (chr-load budget exhaustion).
#
# Cap fires only when a slot's rounded position is in placeholder_positions
# (i.e., already identified as a script-spawn placeholder cluster).
# First N=1 intercepts at that position fire normally (so the user gets
# their boss), the remainder fall through to the standard path which
# applies the placeholder skip and leaves them vanilla. Set this to a
# large value (e.g. 999) to disable and restore v0.23.58/v0.23.59
# behavior — useful for diagnosing whether a stacking CTD is what
# you're actually seeing.
V3_OOPS_ALL_NB_PLACEHOLDER_CAP = 1

# v0.23.49: V3_BOSS_TIER_PINNED_SLOTS — per-slot OOPS_ALL_NB qualifier.
# Some boss-tier slots in vanilla NR don't carry the slot-tier markers
# (Field Boss / Castle Boss / etc.) we'd need for OOPS_ALL_NB scope
# matching. The chr at that slot is named with a bare variant name
# like 'Black Knife Assassin', and our marker-based scope detection
# can't tell it's actually a castle-basement boss arena.
#
# This set lets the user pin specific (msb, pi) coordinates as
# OOPS_ALL_NB-eligible. When OOPS_ALL_NB mode is active, slots in this
# set get forced to the target c-prefix regardless of their
# variant-name marker (or lack of one).
#
# Distinct from V3_PROBLEM_SLOTS (T3 fragile-restrict) — that's for
# slots whose terrain breaks placement. V3_BOSS_TIER_PINNED_SLOTS is
# for slots that ARE legitimate boss arenas but have no marker text.
V3_BOSS_TIER_PINNED_SLOTS = {
    # (msb_name, part_index): 'description'
    ('m60_43_36_50.msb', 59): 'castle basement Black Knife Assassin (no marker in NR data)',
    # v0.23.53: castle rooftop / cathedral remembrance audit. Identified
    # via direct MSB binary parse on user's m13_00_00_00.zip dump (all
    # 244 NR vanilla MSBs). Castle rooftop slot at m60_43_36_50 pi=23
    # hosts c4500 Flying Dragon (Field Boss) in vanilla — premium flat
    # arena, single chr per run, the "test bench" slot. Pinning ensures
    # OOPS_ALL_NB target lands here every run for boss probe campaigns.
    # The pi=21 slot at Y=116 (Mad Pumpkin Head, top of castle) and
    # the cathedral pi=16 slot at Y=101 (Crystalian Remembrance,
    # identical across m60_44_36_00/_20/_50) are also pinned for
    # complete castle-region coverage.
    ('m60_43_36_50.msb', 21): 'castle top tower Mad Pumpkin Head (Y=117)',
    ('m60_43_36_50.msb', 23): 'castle rooftop Flying Dragon arena (Y=106, premium boss-test slot)',
    ('m60_43_36_50.msb', 24): 'castle upper Astel-Naturalborn (Y=87)',
    ('m60_43_36_50.msb', 70): 'castle basement Troll (Y=0)',
    ('m60_44_36_00.msb', 16): 'cathedral rooftop Crystalian Remembrance (Y=102)',
    ('m60_44_36_20.msb', 16): 'cathedral rooftop Crystalian Remembrance (Y=102)',
    ('m60_44_36_50.msb', 16): 'cathedral rooftop Crystalian Remembrance (Y=102)',
    # v0.23.70 / v0.23.71: SPAWN-POOL ROTATION SOURCES.
    # The Day 2 field-boss / castle rooftop / castle basement rotation
    # system pulls from m46_xx template MSBs. The FIELD-boss tiles pack
    # pi=0 c1000 (player marker) + pi=1 boss + pi=2 AEG asset; the CASTLE
    # tiles pack pi=0 marker + pi=1 boss (no asset). pi=1 is the rotation
    # chr, teleported into the live arena at runtime.
    #
    # These slots are pinned so the swap loop treats them as AUTHORITATIVE
    # boss slots rather than running them through the placeholder/position
    # heuristics that the origin-stacked Part layout would otherwise trip.
    # (Historical note: earlier engines had a near-origin spawn-marker
    # filter and a cluster builder that silently dropped pi=1; both were
    # removed — near-origin in v0.23.72, clustering in v0.26.13 — so the
    # pin is now about boss-tier classification + the placeholder-position
    # intercept, not bypassing those deleted filters.)
    #
    # KNOWN-OPEN history (FIXED v0.27.29): the CASTLE-variant tiles
    # (m46_86/87/88/90/91/95) used to report n_swaps=0 in normal/all-SOTE
    # runs while their FIELD twins swapped. Root cause was NOT the pin —
    # it was a name-marker classification gap in pick_target_cp (the
    # arena/night-boss pool gates keyed on broad name markers the castle
    # POI-interior names don't carry). Fixed there by treating catalogued
    # spawn-pool rotation sources as arena/NB regardless of name. See the
    # "castle-variant spawn-pool MSBs now swap" block below.
    #
    # Caveat (unchanged): the live arenas these rotations teleport into
    # (m48_50, m48_60, Castle proper, etc.) preload chrbnds based on
    # vanilla rotation expectations. A swap target whose chrbnd ISN'T in
    # the live arena's preload set may CTD on encounter approach. Test on
    # safe seeds first; if a specific target reliably CTDs at a specific
    # arena, file it as V3_PROBLEM_SLOTS or extend chrbnd-preload awareness.
    ('m46_52_00_00.msb',  1): 'spawn-pool rotation: Draconic Tree Sentinel',
    ('m46_53_00_00.msb',  1): 'spawn-pool rotation: Tree Sentinel',
    ('m46_54_00_00.msb',  1): 'spawn-pool rotation: Royal Carian Knight',
    ('m46_55_00_00.msb',  1): 'spawn-pool rotation: Leonine Misbegotten',
    ('m46_56_00_00.msb',  1): 'spawn-pool rotation: Bell Bearing Hunter (Field)',
    ('m46_57_00_00.msb',  1): 'spawn-pool rotation: Elder Lion',
    ('m46_58_00_00.msb',  1): 'spawn-pool rotation: Flying Dragon',
    ('m46_59_00_00.msb',  1): 'spawn-pool rotation: Royal Revenant',
    ('m46_63_00_00.msb',  1): 'spawn-pool rotation: Demi-Human Queen',
    ('m46_64_00_00.msb',  1): 'spawn-pool rotation: Ancestor Spirit',
    ('m46_65_00_00.msb',  1): 'spawn-pool rotation: Putrid Avatar',
    ('m46_66_00_00.msb',  1): 'spawn-pool rotation: Onyx Lord',
    ('m46_67_00_00.msb',  1): 'spawn-pool rotation: Erdtree Avatar',
    ('m46_68_00_00.msb',  1): 'spawn-pool rotation: Magma Wyrm',
    ('m46_69_00_00.msb',  1): 'spawn-pool rotation: Crucible Knight Ordovis',
    ('m46_72_00_00.msb',  1): 'spawn-pool rotation: c5011 (Hippo, suspected)',
    ('m46_74_00_00.msb',  1): 'spawn-pool rotation: Death Rite Bird',
    ('m46_86_00_00.msb',  1): 'spawn-pool rotation: Leonine Misbegotten (Castle)',
    ('m46_87_00_00.msb',  1): 'spawn-pool rotation: Bell Bearing Hunter (Castle Basement)',
    ('m46_88_00_00.msb',  1): 'spawn-pool rotation: Royal Revenant (Castle)',
    ('m46_90_00_00.msb',  1): 'spawn-pool rotation: Ancestor Spirit (Castle)',
    ('m46_91_00_00.msb',  1): 'spawn-pool rotation: Putrid Avatar (Castle)',
    ('m46_95_00_00.msb',  1): 'spawn-pool rotation: Crucible Knight Ordovis (Castle)',
}


# v0.23.68: HUB_MAPS bypass for pinned slots.
#
# V3_HUB_MAPS files (m13_00, m13_20, m14_00, m18_00 etc. — castle
# interiors, Roundtable hub) are normally passed through unchanged so
# NPC dialogues, quest triggers, and merchant interactions stay intact.
# That preservation has a side effect: boss-tier chrs INSIDE hubs (e.g.
# the Black Knife Assassin in Castle Watering Hole's basement) never get
# randomized, even though they're not part of any NPC quest chain.
#
# When V3_BOSS_TIER_PINNED_SLOTS contains entries pointing into a HUB
# MSB, the pipeline switches that MSB from full passthrough to a
# "pinned-only" shuffle: only the explicitly-pinned (msb, pi) slots
# get randomized; all other Parts stay vanilla. NPC dialogues and quest
# state are preserved because we only touch deliberately-listed slots.
#
# To enable pinned-slot randomization in a HUB MSB:
#   1. Identify the boss-tier (msb, pi) coordinates inside the hub.
#      Add the hub MSB to V3_DIAGNOSTIC_INVENTORY_MSBS, run the rando
#      once, and inspect the MSB_PART_INVENTORY trace event in the
#      spoiler to find boss-tier c-prefixes and their pi indices.
#   2. Add (msb, pi): 'description' entries to V3_BOSS_TIER_PINNED_SLOTS
#      above, with the same format used for the m60_xx pinned slots.
#   3. The pipeline detects them via _msb_has_pinned_slots() and
#      routes that MSB through shuffle_msb_v3(pinned_only_in_hub=True).

def _msb_has_pinned_slots(fname):
    """Return True if any (msb, pi) entry in V3_BOSS_TIER_PINNED_SLOTS
    targets the given MSB filename. Used by the rando_pipeline to decide
    whether a HUB MSB should be passed through unchanged or routed
    through shuffle_msb_v3 in pinned-only mode."""
    return any(msb == fname for (msb, _pi) in V3_BOSS_TIER_PINNED_SLOTS)


# v0.23.54: AUTHORITATIVE BOSS-SLOT CATALOG.
# Loaded from data/nr_boss_slots.json — built from a vanilla NR MSB dump,
# 444 boss-tier slots across 126 MSBs. Each entry is keyed by (msb, pi)
# and tagged with tier (nightlord, nightboss, fieldboss, named_boss, etc.)
# and scope (strict/broad/extended).
#
# This replaces the variant-name marker-substring heuristic that was the
# sole signal pre-v0.23.54. Issues with the old approach:
#  - 'Mad Pumpkin Head' has no marker → not caught (now: tier=named_boss)
#  - 'Troll' at Castle basement is boss-tier but has no marker
#  - 'Black Knife Assassin' is boss-tier in some places, mob in others
#  - clustered slots bypassed the marker check entirely
#
# The catalog provides a single source of truth: is_boss_slot(msb, pi)
# returns the tier+scope from the catalog, regardless of variant name.
# OOPS_ALL_NB intercept now consults the catalog FIRST, then falls back
# to marker matching for slots not in the catalog.
#
# V3_BOSS_TIER_PINNED_SLOTS is preserved as a manual override layer —
# entries there are guaranteed to fire OOPS_ALL_NB regardless of catalog
# state, and survive cluster-path branches where the catalog check
# wouldn't normally apply.
V3_BOSS_SLOT_CATALOG = {}  # populated below
V3_BOSS_SLOT_CATALOG_META = {}

def _load_boss_slot_catalog():
    """Load data/nr_boss_slots.json into a (msb, pi) -> dict map.

    Returns: ({(msb, pi): entry_dict}, meta_dict). Catalog-native entries
    (from nr_boss_slots.json) have keys: 'tier', 'scope', 'cp', 'npc',
    'eid', 'name', 'pos', and as of v0.25.7 also 'arena' (bool). The
    v0.26.x terrain-arena merge below adds entries from nr_terrain_arena_
    slots.json that DO NOT have 'cp'/'npc'/'eid'/'name'/'pos' — only
    'pi', 'arena', 'tier'='terrain', 'scope'='terrain', '_source', and
    a few '_'-prefixed audit fields. Readers that touch 'cp' etc. must
    guard with `'cp' in entry` or `entry.get('cp')`.
    Returns ({}, {}) on missing/malformed file (engine still operates,
    just falls back to marker-based detection).

    v0.25.7: `arena` field derivation. Two rules, OR-combined:
      1. The vanilla chr at the slot has `expects_boss_arena=True`.
      2. The vanilla chr at the slot has `size_class` in {XXL, GIGA}.

    Rule 1 captures arena-context dependency (e.g. Crucible Knight is
    size_class=M but its encounter needs the camera/animation space of
    an arena room). Rule 2 captures pure geometric size — XXL+ chrs
    physically can't fit in most non-arena slots.

    The derived `arena` field feeds the slot-side gate at pick_target_cp
    line ~10935. Pre-v0.25.7 the gate only consulted slot_variant_name
    for V3_BOSS_NAME_MARKERS tokens, which misses arena slots whose
    variant names don't carry marker tokens (e.g. unnamed Limveld field
    boss slots that nonetheless host XXL chrs in vanilla).

    Tag-source note: this uses `nr_enemy_tags.json` only (vanilla NR
    tags). load_data() runs heritage_pack / mmv loaders later and
    extends the tag database, but slot-side classification is purely
    a function of the VANILLA chr at the slot — heritage/mmv extensions
    don't change what occupied the slot in vanilla, so reading only
    `nr_enemy_tags.json` here is correct.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    catalog_path = _data_path('nr_boss_slots.json')
    if not os.path.isfile(catalog_path):
        return {}, {}
    try:
        with open(catalog_path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}, {}
    meta = raw.pop('_meta', {})
    flat = {}
    for msb, entries in raw.items():
        if not isinstance(entries, list): continue
        for e in entries:
            pi = e.get('pi')
            if pi is None: continue
            flat[(msb, pi)] = e

    # v0.25.7: derive `arena: bool` field per entry. See docstring above
    # for rationale. Reads vanilla nr_enemy_tags.json directly (the
    # globally-loaded `tags` dict isn't yet populated at module import).
    try:
        with open(_data_path('nr_enemy_tags.json'), encoding='utf-8') as f:
            _vanilla_tags = json.load(f)
    except (json.JSONDecodeError, OSError):
        _vanilla_tags = {}
    _ARENA_SIZES = {'XXL', 'GIGA'}
    _n_arena_expects = 0
    _n_arena_size = 0
    _n_arena_total = 0
    for key, entry in flat.items():
        cp = entry.get('cp')
        info = _vanilla_tags.get(cp, {}) if cp else {}
        by_expects = info.get('expects_boss_arena') is True
        by_size = info.get('size_class') in _ARENA_SIZES
        entry['arena'] = by_expects or by_size
        if entry['arena']: _n_arena_total += 1
        if by_expects: _n_arena_expects += 1
        if by_size: _n_arena_size += 1
    meta['arena_slot_via_expects'] = _n_arena_expects
    meta['arena_slot_via_size'] = _n_arena_size
    meta['arena_slot_via_terrain_new'] = 0      # set below if file exists
    meta['arena_slot_via_terrain_promoted'] = 0  # set below if file exists

    # v0.26.x: merge terrain-derived arena slots. These are (msb, pi) keys
    # that passed big-and-flat terrain criteria (slope < 10°, open area
    # >= 200m² at 10m radius, navmesh edge clearance, etc.) but weren't
    # already in nr_boss_slots.json. Most have small vanilla occupants;
    # the audit promotes them based purely on geometry, not chr identity.
    # Effect: the picker's slot-side arena gate (~line 11234) treats them
    # as arena=True, so arena_only_targets (Romina/Maliketh/etc. post-
    # MMV-size-correction) can land at terrain-qualifying slots beyond
    # the variant-name-marker pool. Generated by dev/audit_terrain_
    # arena_candidates.py from data/slot_terrain.json + nr_boss_slots.json.
    terrain_path = _data_path('nr_terrain_arena_slots.json')
    _n_terrain_added = 0
    _n_terrain_promoted = 0
    if os.path.isfile(terrain_path):
        try:
            with open(terrain_path, encoding='utf-8') as f:
                terrain_raw = json.load(f)
            for slot_entry in terrain_raw.get('slots', []):
                msb = slot_entry.get('msb')
                pi = slot_entry.get('pi')
                if msb is None or pi is None:
                    continue
                key = (msb, pi)
                if key in flat:
                    if not flat[key].get('arena'):
                        flat[key]['arena'] = True
                        _n_terrain_promoted += 1
                else:
                    flat[key] = {
                        'pi': pi,
                        'arena': True,
                        'tier': 'terrain',
                        'scope': 'terrain',
                        '_source': 'terrain_audit_v0_26_x',
                        '_slope_deg': slot_entry.get('slope_deg'),
                        '_area_10m': slot_entry.get('area_10m'),
                        '_vanilla_occupant': slot_entry.get('vanilla_occupant'),
                    }
                    _n_terrain_added += 1
            meta['arena_slot_via_terrain_new'] = _n_terrain_added
            meta['arena_slot_via_terrain_promoted'] = _n_terrain_promoted
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARN: terrain arena slots load failed: {e}")

    # Final arena count after all derivations + terrain merge. Earlier
    # code populated _n_arena_total from the expects/size rules; now
    # add the terrain contribution. This becomes the authoritative
    # meta['arena_slot_count'] value (tests read this key).
    meta['arena_slot_count'] = _n_arena_total + _n_terrain_added + _n_terrain_promoted
    return flat, meta


V3_BOSS_SLOT_CATALOG, V3_BOSS_SLOT_CATALOG_META = _load_boss_slot_catalog()


# v0.27.32: the set of V3_BOSS_SLOT_CATALOG `tier` values that denote a
# GENUINE sealed/scripted boss arena — used by pick_target_cp to trust the
# catalog over name markers when classifying a slot as arena / night-boss
# (see _is_catalogued_boss_arena). These are the tiers where a vanilla boss
# fight happens behind a fog gate / in an evergaol / in a sealed interior,
# so night-boss-tier targets must stay eligible and the _arena_only /
# NIGHT_BOSS_ONLY subtractions must NOT fire.
#
# DELIBERATELY EXCLUDED (kept on strict marker-based gating):
#   'terrain'     — non-boss terrain anchors (147 slots)
#   'encampment'  — field camp groups (Elder Lion / Mad Pumpkin etc.); field
#                   encounters, not sealed arenas
#   'remembrance' — scholar/remembrance trash (Wandering Noble, Cuckoo
#                   Knight, ...); classify correctly via markers already and
#                   must NOT admit NB-only chrs
# This frozenset is the slot-CATALOG tier vocabulary (named_boss /
# castle_interior / ...), which is distinct from the chr-TAG tier vocabulary
# (miniboss / field_boss / night_boss / ...) used by the _BOSS_ARENA_TIERS
# set in is_compatible's size-up filter. Don't conflate them.
V3_CATALOG_BOSS_ARENA_TIERS = frozenset({
    'named_boss', 'nightboss', 'fieldboss', 'ruins_boss', 'fort_boss',
    'fort_suffix', 'boss_suffix', 'castle_interior', 'cathedral',
    'crater', 'noklateo', 'mountaintop',
})


# v0.25.0-patch3: auto-extend V3_PRESERVE_SLOTS with HP-bar-ref pattern
# entries. Catalog slots whose entity_id matches `eid % 10000 == 800` are
# the "boss-event-tracker" entities referenced by NR's boss-init helpers
# (events 90015000, 90065910, 90065911, 90065900, 90065050, 90015442,
# 90015443, etc.). For multi-variant overlay arenas (m48_xx, m49_xx,
# m46_xx — basically every Night Boss arena that uses IsMapVariation(2)
# expedition activation), the EMEVD chain passes these eids around as
# chrEntityId2 (HP-bar display anchor) AND/OR chrEntityId3/4 (multi-body
# boss reference anchors) and AT LEAST ONE of them (chrEntityId / arg6 of
# 90065910) drives EnableCharacter / ForceAnimationPlayback for the actual
# spawned chr. Whether that "actual spawn eid" equals the xxx800 entity
# (m48_40 — single-eid) or splits to a different xxx5xxx eid (m48_60,
# m49_24, m49_29) is encounter-specific.
#
# Empirically (seed 628653, Tricephalos): swapping the xxx800 eid for
# arenas where it's NOT the actual spawn chr causes the entire spawn
# chain to break — not just an HP-bar display mismatch, but the
# EnableCharacter at the actual spawn eid never fires (or the chr never
# transitions to a visible state). Confirmed by playtest: m48_60 swap of
# pi=0 eid=48600800 c3251→c4580 produced NO Tree Sentinel, NO HP bar,
# nothing at all. The downstream entity 48605800 should have stayed
# vanilla c3251 and spawned a Tree Sentinel; instead the whole chain is
# gated on the xxx800 entity's chr being intact.
#
# For arenas where xxx800 IS the actual spawn chr (m48_40 Morgott), the
# same preservation rule means vanilla Morgott spawns instead of a
# rando target. That's an acceptable trade — losing randomization at
# the primary NB-slot for that arena, gaining a working expedition.
#
# Cross-seed scope: 93 catalog entries match this pattern out of 344
# total (27%). All four Tricephalos arenas (m48_40 / m48_60 / m49_24 /
# m49_29) match. Two N1 candidates (m49_24, m49_29) worked in playtest
# despite their xxx800 being swapped — apparently the chrEntityId2 in
# their NR-original-arena layouts isn't on the spawn-gate chain the
# same way m48_60's is. Conservative preserve-all is safer for v0.25
# ship; future patches can refine to only-multi-entity-overlay-arenas
# after EMEVD-by-EMEVD audit.
#
# Side effects:
#   - All 4 Tricephalos arenas preserve their primary boss vanilla
#   - All m48_xx / m49_xx NB arenas with xxx800 primary preserve vanilla
#   - 16 m20/m21 Fallingstar Beast Random Encounter slots stay vanilla
#     (probably overkill — these are simple single-entity field bosses
#     and may swap cleanly. If observed-fine in playtest, those 16 can
#     be carved back out via an MSB-prefix allowlist below)
#   - 33 m46_xx MMV-added arenas with xxx800 primary preserve vanilla
#     (this is the biggest variety hit; MMV designed these for vanilla
#     chrs and they may have similar multi-entity wake-handshake gates)
#
# If variety loss is too steep in playtest, refine by:
#   (a) carving out specific MSB prefixes (e.g. m20_/m21_) from this
#       preservation if they prove to swap cleanly
#   (b) auditing each overlay's EMEVD to identify which xxx800 eids
#       are actual-spawn vs HP-bar-ref-only, and only preserving the
#       latter
#   (c) parsing EMEVDs at catalog-build time to derive the "actual
#       spawn chrEntityId" and swap THAT instead of xxx800
def _is_hp_bar_ref_eid(eid):
    """v0.25.0-patch3: eid pattern matching the boss-init helpers'
    HP-bar-anchor / event-tracker entity. See block comment above."""
    return isinstance(eid, int) and (eid % 10000) == 800


def _extend_preserve_slots_with_hp_bar_refs():
    """Walk V3_BOSS_SLOT_CATALOG, add each HP-bar-ref-pattern entry to
    V3_PRESERVE_SLOTS so they stay vanilla through the swap pipeline.
    Returns the count added so the load summary can log it."""
    n_added = 0
    for (msb, pi), entry in V3_BOSS_SLOT_CATALOG.items():
        eid = entry.get('eid', 0)
        if not _is_hp_bar_ref_eid(eid): continue
        key = (msb, pi)
        if key in V3_PRESERVE_SLOTS: continue  # already manually preserved
        reason = (
            f"v0.25.0-patch3 auto-preserve: eid={eid} matches HP-bar-ref "
            f"pattern (eid%10000==800). Boss-init helpers (90015000 / "
            f"90065910 / 90065050 family) reference this eid as the boss-"
            f"event-tracker anchor; swapping breaks the spawn chain. See "
            f"block comment in oops_v3.py near _is_hp_bar_ref_eid."
        )
        V3_PRESERVE_SLOTS[key] = reason
        n_added += 1
    return n_added


V3_HP_BAR_REF_AUTO_PRESERVED = _extend_preserve_slots_with_hp_bar_refs()


# v0.25.1: arena chr-role catalog. Refines v0.25.0-patch3's broad
# "preserve every xxx800 eid" heuristic with EMEVD-derived per-arena
# data. The catalog file (data/nr_boss_arena_chr_roles.json) is built
# by dev/build_arena_chr_roles.py from vanilla decompiled EMEVDs and
# captures, per MSB, the chr entities involved in the boss-spawn chain
# and the role each plays (actual_chr / hp_bar_ref / companion).
#
# Three strategies emerge per MSB:
#
#   preserve_primary  — multi-wave / multi-entity / hardcoded-anim
#                       arenas (m48_xx headline boss arenas, m49_xx
#                       NR-original NB arenas, m18/m19 Nightlord arenas).
#                       Entire MSB preserved vanilla; no Part swaps in
#                       this MSB at all (option D).
#
#   swap_actual_chr   — single-entity-style arenas where the
#                       actual_chr_eid is distinct from any complex
#                       multi-wave dependency. Swap actual_chr_eids
#                       normally, but preserve hp_bar_ref + companion
#                       eids (option B).
#
#   none / swap_normal — no boss-init helpers in EMEVD; not relevant
#                       to this catalog.
#
# This LOOSENS v0.25.0-patch3's preservation for arenas where the
# role catalog confirms the actual_chr_eid is swap-safe (the role
# data overrides the broad xxx800 pattern). It TIGHTENS preservation
# for preserve_primary MSBs (the whole MSB is now preserved, not just
# the xxx800 primary), preventing companion-eid swaps that v0.25.0-
# patch3 was missing.
V3_ARENA_CHR_ROLES = {}                # populated below
V3_ARENA_CHR_ROLES_META = {}
V3_OVERLAY_PRESERVE_VANILLA_MSBS = frozenset()  # populated below; option D
V3_OVERLAY_ROLE_PRESERVED_SLOTS = {}    # (msb, pi) -> reason; option B's per-slot

def _load_arena_chr_roles():
    """Load data/nr_boss_arena_chr_roles.json. Returns (catalog, meta)."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = _data_path('nr_boss_arena_chr_roles.json')
    if not os.path.isfile(path):
        return {}, {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}, {}
    meta = raw.pop('_meta', {})
    return raw, meta


def _apply_arena_role_catalog():
    """Use V3_ARENA_CHR_ROLES to refine the preserve sets.

    Returns: (vanilla_msbs_frozenset, role_preserved_slots_dict, lifted_count)
      vanilla_msbs        — MSBs to fully vanilla-preserve (option D)
      role_preserved_slots — (msb, pi) -> reason for slot-level preserve (option B)
      lifted_count        — # of v0.25.0-patch3 entries lifted from
                            V3_PRESERVE_SLOTS because the role catalog
                            says they're actually swap-safe
    """
    global V3_PRESERVE_SLOTS
    vanilla_msbs = set()
    slot_preserve = {}
    lifted = 0

    for msb, info in V3_ARENA_CHR_ROLES.items():
        strategy = info.get('recommended_strategy', 'none')
        if strategy == 'preserve_primary':
            # Option D: entire-MSB preservation.
            vanilla_msbs.add(msb)
            # The pick_target_cp gate will check V3_OVERLAY_PRESERVE_VANILLA_MSBS
            # by MSB name and return None for any slot in those MSBs. This
            # covers ALL Parts in the MSB, including companions and the
            # primary boss. The xxx800 entries that v0.25.0-patch3 added
            # to V3_PRESERVE_SLOTS for this MSB stay there (redundant
            # but harmless — both gates return None).

        elif strategy == 'swap_actual_chr':
            # Option B: preserve hp_bar_ref + companion eids, allow swap
            # at actual_chr_eids. Join role-eid lists to V3_BOSS_SLOT_CATALOG
            # to get (msb, pi) keys for V3_PRESERVE_SLOTS.
            actual_set = set(info.get('actual_chr_eids', []))
            preserve_set = set(info.get('hp_bar_ref_eids', [])) | \
                           set(info.get('companion_eids', []))
            # Don't preserve eids that are ALSO in actual_chr (those are
            # the swap targets); per role catalog those slots get
            # randomized normally.
            preserve_set -= actual_set
            for (m, pi), entry in V3_BOSS_SLOT_CATALOG.items():
                if m != msb: continue
                eid = entry.get('eid', 0)
                if eid in preserve_set:
                    reason = (
                        f"v0.25.1 role-catalog preserve: eid={eid} marked "
                        f"as hp_bar_ref/companion at msb={msb} per role "
                        f"catalog (strategy={strategy}). actual_chr_eids "
                        f"at this msb={sorted(actual_set)} remain swap-eligible."
                    )
                    slot_preserve[(m, pi)] = reason
                    # Also add to V3_PRESERVE_SLOTS so the existing gate fires
                    if (m, pi) not in V3_PRESERVE_SLOTS:
                        V3_PRESERVE_SLOTS[(m, pi)] = reason
                elif eid in actual_set:
                    # v0.25.1 LIFTS v0.25.0-patch3's preservation of this
                    # eid — role catalog confirms it's the actual chr that
                    # should be swappable. Only lift if patch3 had added it
                    # (we can tell by checking the reason string contains
                    # "v0.25.0-patch3").
                    existing = V3_PRESERVE_SLOTS.get((m, pi), '')
                    if 'v0.25.0-patch3' in existing:
                        del V3_PRESERVE_SLOTS[(m, pi)]
                        lifted += 1

    return frozenset(vanilla_msbs), slot_preserve, lifted


V3_ARENA_CHR_ROLES, V3_ARENA_CHR_ROLES_META = _load_arena_chr_roles()
(V3_OVERLAY_PRESERVE_VANILLA_MSBS,
 V3_OVERLAY_ROLE_PRESERVED_SLOTS,
 V3_OVERLAY_ROLE_PATCH3_LIFTED) = _apply_arena_role_catalog()


# v0.26.16: Night-boss-arena whole-MSB preservation, gated on test-mode.
#
# The 25 N1/N2 night-boss arenas (m48_00..m48_90 + the m49_xx NR-original
# NB arenas) are choreographed multi-entity fights. When the test-mode
# arena overlay is OFF — i.e. a normal play build — the randomizer must
# not touch them at all: no Part swaps here, the arena ships byte-vanilla
# (and dcx_batch's healthbar step skips them in parallel). This is a hard,
# catalog-independent guarantee — it does NOT rely on each arena being
# correctly classified preserve_primary in nr_boss_arena_chr_roles.json
# (the m48_80 Godskin Duo misclassification, v0.26.16, is exactly the
# failure this backstops).
#
# Canonical arena set: the `arenas` key of data/nb_wave_bypass_flags.json
# — the same 25 arenas emevd_patch.py drives from. Single source of
# truth; no hardcoded list to drift.
#
# V3_PRESERVE_NIGHT_BOSS_ARENAS is the live gate. Default True (preserve
# the NB-arena EMEVDs byte-vanilla). dcx_batch.rando_pipeline sets it
# True before the shuffle; the healthbar step applies the matching
# EMEVD-side exclusion. NB-arena MSB *Parts* still randomize when the
# V3_RANDOMIZE_*_NB_ARENAS flags are set -- this gate is EMEVD-only.
def _load_night_boss_arena_msbs():
    """Return frozenset of '<stem>.msb' for the 25 NB arenas."""
    path = _data_path('nb_wave_bypass_flags.json')
    if not os.path.isfile(path):
        return frozenset()
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset()
    arenas = raw.get('arenas', {})
    return frozenset(f'{stem}.msb' for stem in arenas)


V3_NIGHT_BOSS_ARENA_MSBS = _load_night_boss_arena_msbs()
V3_PRESERVE_NIGHT_BOSS_ARENAS = True


# v0.28.x: third NB-arena randomization opt-in path, finer-grained than
# V3_RANDOMIZE_ALL_NB_ARENAS / V3_RANDOMIZE_SAFE_NB_ARENAS. Reads the
# canonical whitelist at data/nb_encounter_whitelist.json -- the SAME
# file the param-side emitter (dev/emit_nb_encounter_whitelist.py)
# consumes when generating the LotResultSmallBaseAndSpot patch CSV that
# constrains the game's overlay lottery. Lock-step coupling: the game
# can only ever route to a whitelisted arena, and inside that arena the
# engine swaps the boss using the existing NB-caliber pool with all
# current safety filters applied (V3_NIGHT_BOSS_EXCLUDE_TARGETS for
# known-broken chrs, the Margit-fix anim-family compat filter for
# scripted-intro slots, unique-cap reservation).
#
# Non-empty whitelist -> randomize-at-whitelist is active. Empty
# whitelist (or missing file) -> V3_NB_RANDOMIZE_WHITELIST is empty,
# the third _force_rando_nb clause never fires, NB arenas stay
# preserved -- same as today's v0.27.x default. No new flag; the
# whitelist file's contents IS the flag.
def _load_nb_randomize_whitelist():
    """Return frozenset of '<stem>.msb' for whitelisted NB arenas.
    Source of truth shared with the param-side emitter."""
    path = _data_path('nb_encounter_whitelist.json')
    if not os.path.isfile(path):
        return frozenset()
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset()
    stems = list(raw.get('nb1', [])) + list(raw.get('nb2', []))
    return frozenset(f'{s}.msb' for s in stems)


V3_NB_RANDOMIZE_WHITELIST = _load_nb_randomize_whitelist()


# v0.26.16: safe single-boss N1/N2 arenas — eligible for MSB
# randomization under VANILLA emevd.
#
# Derived from the v0.25.9 N1/N2 expedition-arena set (19 arenas)
# minus the 6 multi-entity arenas whose vanilla emevd runs a
# synchronized multi-
# healthbar / multi-boss init that breaks when the primary boss chr is
# swapped (the m48_80 Godskin Duo failure class):
#   m48_50  Draconic Tree Sentinel + 2x Royal Cavalryman
#   m48_60  Tree Sentinel + 2x Royal Cavalryman
#   m48_80  Godskin Duo (Noble + Apostle)
#   m49_25  Crucible Knight + Golden Hippopotamus
#   m49_28  Night's Cavalry x2 (Glaive + Flail)
#   m49_29  Demi-Human Queen + Swordmaster
# Nameless King (m48_20) is also EXCLUDED — although a single headline
# boss, its phase-1-on-Storm-King / phase-2-dismounted structure (the
# arena carries both c7900 and the c7910 mount) is a two-entity, two-
# phase fight whose vanilla init may not survive a boss swap. Pulled
# out of caution; revisit if a swap there is empirically validated.
#
# When V3_RANDOMIZE_SAFE_NB_ARENAS is True these 12 arenas are exempted
# from all three NB-preservation gates in pick_target_cp, so their boss
# Part gets swapped. Their EMEVD is NOT touched — the healthbar step
# preserves NB-arena EMEVD vanilla independently. dcx_batch sets the
# flag and only enables it when test-mode arenas are OFF (test-mode
# would overlay the EMEVD and void the vanilla-EMEVD guarantee).
V3_SAFE_NB_RANDOMIZE_MSBS = frozenset({
    'm48_40_00_00.msb', 'm48_70_00_00.msb',
    'm48_90_00_00.msb', 'm49_10_00_00.msb', 'm49_17_00_00.msb',
    'm49_18_00_00.msb', 'm49_19_00_00.msb', 'm49_20_00_00.msb',
    'm49_21_00_00.msb', 'm49_23_00_00.msb', 'm49_26_00_00.msb',
    'm49_27_00_00.msb',
})
V3_RANDOMIZE_SAFE_NB_ARENAS = False

# v0.26.16: randomize ALL 25 night-boss arenas, including the 6
# multi-entity arenas (Godskin Duo etc.) and Nameless King. When
# True, _force_rando_nb in pick_target_cp fires for any arena in
# V3_NIGHT_BOSS_ARENA_MSBS (all 25), exempting them from the NB
# preservation gates so their boss Parts get swapped. EMEVD stays
# vanilla either way (the healthbar step preserves NB-arena EMEVD
# separately).
#
# v0.26.x: DEFAULT TRUE -- randomize-all-NB is now normal play.
# The multi-entity boss-init breakage (the Godskin Duo failure
# class) is RESOLVED: the synchronized multi-healthbar / multi-boss
# spawn manifest lives in regulation.bin, not the arena MSBs, and
# the regulation.bin modification handles it. The investigation
# that kept this flag experimental is closed -- all-NB randomization
# is normal play. Supersedes the safe-NB flag -- all 25 includes the
# safe 12.
#
# v0.27.0: SET FALSE. NB-arena boss swaps produce a recurring CTD
# class — XXL large_boss_ground bosses (Ulcerated Tree Spirit, Golden
# Hippo, Death Bird) land on arenas whose scripted intro expects a
# different anim class and lack the matching wake-up anim bank
# (confirmed seeds 677311, 740664). Until the swap compat fix
# lands, NB arenas are held vanilla: with both V3_RANDOMIZE_*_NB_ARENAS
# False, _force_rando_nb is never True and the whole-MSB preservation
# gate holds all 25 arenas byte-vanilla. Field / grunt / non-NB-boss
# randomization is unaffected.
V3_RANDOMIZE_ALL_NB_ARENAS = False



# v0.27.0: add-heavy night-boss encounters where the rando preserves
# the boss Part(s) but DOES randomize the surrounding adds. The boss
# anim-mismatch CTD class is avoided entirely (the boss is never
# swapped); the adds are plain enemy Parts that go through normal
# randomization. Add-Part swaps preserve entity_ids and Part count,
# so wave-complete EMEVD ("entities [list] dead") still resolves.
#
# In the whole-MSB preserve gates in pick_target_cp, an arena in this
# set preserves a Part only when recipient_is_boss; every other Part
# falls through. All four are 'preserve_primary' in
# nr_boss_arena_chr_roles.json (-> V3_OVERLAY_PRESERVE_VANILLA_MSBS);
# the three m48/m49 arenas are also in V3_NIGHT_BOSS_ARENA_MSBS, so
# both preserve gates carry the carve-out.
V3_ADD_RANDOMIZE_ARENAS = frozenset({
    'm48_00_00_00.msb',   # Duke's Dear Freja  - randomize the spider swarm
    'm49_26_00_00.msb',   # Commander          - randomize the Exile Soldier army
    'm49_27_00_00.msb',   # Commander          - randomize the Exile Soldier army
    'm47_70_00_00.msb',   # Tibia Mariner      - randomize the skeleton catacomb
})

 


# v0.24.28: Starting encampment catalog. Asset MSBs that get instantiated
# near the wagon spawn at the start of a Limveld Expedition. Used by:
#
#   1. Spoiler annotation: each spoiler entry whose `map` matches one of
#      these MSBs gets `in_starting_encampment: true`. Lets users (and
#      CTD investigation) correlate post-run "I crashed early" reports
#      to specific placements without needing to know map layout.
#
#   2. Picker scope: `oops_all_nb_marker_scope='starting_encampment'`
#      causes `oops_all_nb_target_cp` to fire at every slot whose MSB
#      is in V3_STARTING_ENCAMPMENT_MSBS, regardless of NB-marker
#      status. Test-mode for "does cp X cause issues at any of the
#      slots a player would hit in the first few minutes?"
#
# Tagging is per-MSB, not per-(msb, pi). This works because asset MSBs
# in NR are typically instantiated at a single point per Expedition;
# tagging the whole template covers every Part in it. If a future data
# point shows the same MSB used both as a starting encampment AND
# elsewhere, we refine to range-based tagging.
#
# This catalog is manually maintained (added to as Alaric identifies
# starting encampments in playtest spoilers). It's expected to grow.
V3_STARTING_ENCAMPMENT_MSBS = frozenset()  # populated below
V3_STARTING_ENCAMPMENT_META = {}  # per-MSB metadata dict
V3_STARTING_ENCAMPMENT_FILE_META = {}  # _meta from the JSON file


def _load_starting_encampments():
    """Load data/nr_starting_encampments.json.

    Returns: (msb_set, per_msb_meta_dict, file_meta_dict).
      msb_set       — frozenset of MSB filenames (e.g. 'm43_01_00_00.msb')
      per_msb_meta  — dict mapping MSB filename to the entry dict (label,
                      size, n_parts, first_observed_seed, notes, etc.)
      file_meta     — the _meta block from the JSON file
    Returns ({}, {}, {}) on missing/malformed file — engine operates
    normally without the catalog (just no encampment-scope, no spoiler
    annotation).
    """
    path = _data_path('nr_starting_encampments.json')
    if not os.path.isfile(path):
        return frozenset(), {}, {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset(), {}, {}
    file_meta = raw.get('_meta', {})
    encampments = raw.get('encampments', {})
    if not isinstance(encampments, dict):
        return frozenset(), {}, file_meta
    msb_set = frozenset(encampments.keys())
    return msb_set, dict(encampments), file_meta


(V3_STARTING_ENCAMPMENT_MSBS,
 V3_STARTING_ENCAMPMENT_META,
 V3_STARTING_ENCAMPMENT_FILE_META) = _load_starting_encampments()


# v0.27.43: STARTING-ENCAMPMENT TRASH GATE.
# -----------------------------------------
# When V3_STARTING_ENCAMPMENT_TRASH_GATE is True, pick_target_cp intersects
# the target pool with V3_TRASH_PREFIXES for any slot whose MSB is in
# V3_STARTING_ENCAMPMENT_MSBS — the spawn-adjacent asset MSBs instantiated
# beside the player wagon at the start of a Limveld Expedition. The effect:
# the player's very first fight can only roll trash-tier enemies, never a
# miniboss/night-boss-strength occupant. (Vanilla camps are Wandering Nobles
# + Foot Soldiers; before this gate a starting camp could randomize to e.g.
# Man-Bat + Troll Knight + Skeleton — seed 612394.)
#
# Mechanism is the same lightweight pool-intersection as V3_SOTE_MODE and the
# rider/mount restriction — no new pre-pass. It runs in pick_target_cp AFTER
# the hard excludes (so a CTD-blacklisted trash chr stays out, its exclude
# wins) and BEFORE the tier-preserve filter (a no-op here: every trash chr is
# grunt/field-strength, so tier-preserve can't widen back out). If the
# intersection empties the pool the slot falls through to the existing
# `not pool` return and stays vanilla — and vanilla starting camps are
# grunts, so that's a safe floor rather than a CTD risk.
#
# Variant safety is layered: the c-prefix set keeps the pool to trash chrs,
# and the 16 sponge-variant npc_param_ids that those chrs also carry are in
# V3_AVOID_VARIANT_NPC_IDS (variant-level, v0.27.43), so an in-pool trash chr
# still can't roll its beefy variant. See data/reconstructed_trash.json.
#
# V3_TRASH_PREFIXES is file-backed (loaded at import, like the encampment
# catalog above). It stays empty if the file is missing — in which case the
# gate is inert and every starting-camp slot randomizes normally.
V3_STARTING_ENCAMPMENT_TRASH_GATE = True


def _load_trash_prefixes():
    """Load the trash-tier c-prefix set from data/reconstructed_trash.json.

    Returns a frozenset of c-prefixes (e.g. 'c3000'). Reads the flat
    'trash_prefixes' list. Returns an empty frozenset on missing/malformed
    file — the starting-encampment trash gate is inert without it.
    """
    path = _data_path('reconstructed_trash.json')
    if not os.path.isfile(path):
        return frozenset()
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset()
    prefixes = raw.get('trash_prefixes', [])
    if not isinstance(prefixes, list):
        return frozenset()
    return frozenset(p for p in prefixes if isinstance(p, str) and p.startswith('c'))


V3_TRASH_PREFIXES = _load_trash_prefixes()


# v0.24.31: quadruped-unsafe slot catalog. Per-(msb, pi) excludes for
# locomotion=3 (quadruped) chr targets. Quadrupeds in NR/ER's engine
# sample a wider spawn-time footprint than bipeds — body extends further
# forward/back from the anchor point — so a slot that's on-mesh by
# biped classification can still fail quadruped spawn validation if the
# surrounding walkable area is sparse. The empirical data point: seed
# 924056 placed c4080 Rat (loco=3) at m45_01 pi=3 (a former c4300
# Wandering Noble slot, the sparsest navmesh slot in the encampment with
# s_xz=165.6 m²). The Rat froze on spawn.
#
# Picker behavior: when a quadruped chr (locomotion=3) is the candidate
# target for a slot, check (msb_base, pi) ∈ V3_QUADRUPED_UNSAFE_SLOTS.
# If yes, the picker rejects this target and rolls again. The reject
# treats the slot like the chr is forbidden — same semantics as the
# nb_strict/nb_caliber/forbidden_source_anim gates.
#
# This is a manually-maintained catalog. Adds happen as freezes are
# reported in playtests. The threshold approach (auto-exclude any slot
# with s_xz < N for quadruped targets) is the natural generalization
# once we have more data points to calibrate N — for now, per-slot is
# surgical and reversible.
V3_QUADRUPED_UNSAFE_SLOTS = frozenset()  # populated below — set of (msb, pi) tuples
V3_QUADRUPED_UNSAFE_SLOTS_META = {}  # per-slot metadata (notes, observed seed, etc.)
V3_QUADRUPED_UNSAFE_SLOTS_FILE_META = {}  # _meta from the JSON file


def _load_quadruped_unsafe_slots():
    """Load data/nr_quadruped_unsafe_slots.json.

    Returns: (slot_set, slot_meta, file_meta).
      slot_set   — frozenset of (msb_filename, pi_int) tuples
      slot_meta  — dict mapping (msb, pi) to the entry dict (notes, etc.)
      file_meta  — the _meta block from the JSON file
    Returns (frozenset(), {}, {}) on missing/malformed file — engine
    operates normally without the catalog (no quadruped excludes
    applied, freeze risk re-emerges but no worse than pre-v0.24.31).
    """
    path = _data_path('nr_quadruped_unsafe_slots.json')
    if not os.path.isfile(path):
        return frozenset(), {}, {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset(), {}, {}
    file_meta = raw.get('_meta', {})
    slots = raw.get('slots', [])
    if not isinstance(slots, list):
        return frozenset(), {}, file_meta
    slot_set = set()
    slot_meta = {}
    for entry in slots:
        if not isinstance(entry, dict): continue
        msb = entry.get('msb')
        pi = entry.get('pi')
        if not msb or pi is None: continue
        try:
            pi_int = int(pi)
        except (ValueError, TypeError):
            continue
        slot_set.add((msb, pi_int))
        slot_meta[(msb, pi_int)] = entry
    return frozenset(slot_set), slot_meta, file_meta


(V3_QUADRUPED_UNSAFE_SLOTS,
 V3_QUADRUPED_UNSAFE_SLOTS_META,
 V3_QUADRUPED_UNSAFE_SLOTS_FILE_META) = _load_quadruped_unsafe_slots()


# ---------------------------------------------------------------------------
# v0.27.28: Flying-required slots catalog REMOVED.
#
# This whole apparatus (V3_FLYING_REQUIRED_SLOTS + _META + _FILE_META +
# V3_FLYING_ELIGIBLE_TARGETS, the _load_flying_required_slots() loader, and
# data/nr_flying_required_slots.json) enforced that catalogued vanilla
# dragon slots could only receive flier targets — the seed-552688
# "Astel at a Flying Dragon slot → CTD" gate. Per Alaric that constraint
# isn't real (dragons start grounded; any enemy is fine at any former
# dragon slot) and the CTD was never confirmed to be flying-related. With
# Gate 5 and the swap_compat is_flier checks gone, none of this is read
# anymore, so it's all removed. This was also the last reader of the
# anim_class tag field, which is now fully expunged.
# ---------------------------------------------------------------------------


# v0.24.79: entrance-animation classification (Option B step 1).
#
# Two data files, both loaded once at module init:
#   - data/entrance_animations.json → V3_ENTRANCE_ANIM_CLASS
#   - data/nr_no_emerge_slots.json  → V3_NO_EMERGE_SLOTS
#
# Boss-side: V3_ENTRANCE_ANIM_CLASS maps c-prefix → entrance-anim class.
# Values: 'emerge_from_ground', 'fly_in', 'scripted_intro', 'pre_placed',
# 'walk_in', 'unknown'. Default for any chr not in the map: 'unknown'
# (no gate fires). Seeded manually from empirical CTD reports. Eventual
# replacement: chrbnd-derived parser (Option C — multi-day project to
# reverse-engineer TAE / behavior-tree binary format).
#
# Arena-side: V3_NO_EMERGE_SLOTS lists (msb, pi) slots that lack
# subsurface terrain. Emerge-from-ground intros fail at these slots.
# Seeded from empirical CTDs (Fort GG rampart). Stays manual long-
# term — geometry-dependent, not derivable from chr data.
#
# Gate logic (in _reject_target_for_slot, Gate 7 below):
#   if (msb, pi) in V3_NO_EMERGE_SLOTS
#   and V3_ENTRANCE_ANIM_CLASS.get(target_cp) == 'emerge_from_ground':
#       reject 'no_emerge_terrain'
# Effectively: per-slot ban list scoped to one specific failure class,
# data-driven instead of per-incident manual entry.

V3_ENTRANCE_ANIM_CLASS = {}        # cp → class string
V3_ENTRANCE_ANIM_META = {}          # cp → entry dict (class + _source_note)
V3_ENTRANCE_ANIM_FILE_META = {}     # _meta block from the JSON
V3_NO_EMERGE_SLOTS = frozenset()    # set of (msb, pi)
V3_NO_EMERGE_SLOTS_META = {}        # (msb, pi) → entry dict
V3_NO_EMERGE_SLOTS_FILE_META = {}   # _meta block from the JSON

# v0.26.11: intro-anim-required slots. Mirror image of V3_NO_EMERGE_SLOTS —
# instead of REJECTING a chr class at certain slots, these slots REQUIRE
# the occupant to have an idle/entrance animation. Chrs classified
# 'no_intro_anim' in V3_ENTRANCE_ANIM_CLASS break here. First slot:
# the m38_00 Guardian Golem "Cathedra" slot. See Gate 8 in
# _reject_target_for_slot and data/nr_intro_anim_required_slots.json.
V3_INTRO_ANIM_REQUIRED_SLOTS = frozenset()    # set of (msb, pi)
V3_INTRO_ANIM_REQUIRED_SLOTS_META = {}        # (msb, pi) → entry dict
V3_INTRO_ANIM_REQUIRED_SLOTS_FILE_META = {}   # _meta block from the JSON


def _load_entrance_animations():
    """Load data/entrance_animations.json.

    Returns: (cp_to_class, cp_to_entry, file_meta).
      cp_to_class — dict mapping c-prefix → class string
      cp_to_entry — dict mapping c-prefix → full entry (class + _source_note)
      file_meta   — _meta block from the JSON file
    Returns empty values on missing/malformed file (graceful degradation —
    engine still works, just no entrance-anim gate fires).
    """
    path = _data_path('entrance_animations.json')
    if not os.path.isfile(path):
        return {}, {}, {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}, {}, {}
    file_meta = raw.get('_meta', {})
    entries = raw.get('entrance_animations', {})
    if not isinstance(entries, dict):
        return {}, {}, file_meta
    cp_to_class = {}
    cp_to_entry = {}
    for cp, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        cls = entry.get('class')
        if not cls:
            continue
        cp_to_class[cp] = cls
        cp_to_entry[cp] = entry
    return cp_to_class, cp_to_entry, file_meta


def _load_no_emerge_slots():
    """Load data/nr_no_emerge_slots.json.

    Returns: (slot_set, slot_meta, file_meta).
      slot_set  — frozenset of (msb_filename, pi_int) tuples
      slot_meta — dict mapping (msb, pi) → full entry (description + failures)
      file_meta — _meta block from the JSON file
    Returns empty values on missing/malformed file.
    """
    path = _data_path('nr_no_emerge_slots.json')
    if not os.path.isfile(path):
        return frozenset(), {}, {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset(), {}, {}
    file_meta = raw.get('_meta', {})
    slots = raw.get('slots', [])
    if not isinstance(slots, list):
        return frozenset(), {}, file_meta
    slot_set = set()
    slot_meta = {}
    for entry in slots:
        if not isinstance(entry, dict):
            continue
        msb = entry.get('msb')
        pi = entry.get('part_index')
        if not msb or pi is None:
            continue
        try:
            pi_int = int(pi)
        except (ValueError, TypeError):
            continue
        slot_set.add((msb, pi_int))
        slot_meta[(msb, pi_int)] = entry
    return frozenset(slot_set), slot_meta, file_meta


def _load_intro_anim_required_slots():
    """Load data/nr_intro_anim_required_slots.json.

    Returns: (slot_set, slot_meta, file_meta).
      slot_set  — frozenset of (msb_filename, pi_int) tuples
      slot_meta — dict mapping (msb, pi) → full entry
      file_meta — _meta block from the JSON file
    Returns empty values on missing/malformed file (graceful degradation —
    the engine still works, just no intro-anim gate fires).

    Mirrors _load_no_emerge_slots (same schema: a `slots` list of
    {msb, part_index, ...} entries). Kept as a dedicated loader rather
    than a shared helper to match the per-data-file loader convention
    already established for the entrance-anim system.
    """
    path = _data_path('nr_intro_anim_required_slots.json')
    if not os.path.isfile(path):
        return frozenset(), {}, {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset(), {}, {}
    file_meta = raw.get('_meta', {})
    slots = raw.get('slots', [])
    if not isinstance(slots, list):
        return frozenset(), {}, file_meta
    slot_set = set()
    slot_meta = {}
    for entry in slots:
        if not isinstance(entry, dict):
            continue
        msb = entry.get('msb')
        pi = entry.get('part_index')
        if not msb or pi is None:
            continue
        try:
            pi_int = int(pi)
        except (ValueError, TypeError):
            continue
        slot_set.add((msb, pi_int))
        slot_meta[(msb, pi_int)] = entry
    return frozenset(slot_set), slot_meta, file_meta


(V3_ENTRANCE_ANIM_CLASS,
 V3_ENTRANCE_ANIM_META,
 V3_ENTRANCE_ANIM_FILE_META) = _load_entrance_animations()

(V3_NO_EMERGE_SLOTS,
 V3_NO_EMERGE_SLOTS_META,
 V3_NO_EMERGE_SLOTS_FILE_META) = _load_no_emerge_slots()

(V3_INTRO_ANIM_REQUIRED_SLOTS,
 V3_INTRO_ANIM_REQUIRED_SLOTS_META,
 V3_INTRO_ANIM_REQUIRED_SLOTS_FILE_META) = _load_intro_anim_required_slots()


# v0.24.51: script-spawn boss arena slots.
#
# The 4 catalogued (msb, pi) slots in data/nr_script_spawn_boss_slots.json
# are the ONLY slots where script_spawn _source chrs of boss tier can
# be safely placed as targets. Vanilla NR uses EMEVD script-side spawns
# (SmallBaseAttached and similar) at these slots; the spawned chr's asset
# bundle and animation banks are preloaded by the script. Placing a
# script_spawn boss chr (e.g. c7710 Centipede Demon, c7900 Nameless King,
# c7910 Storm King) at a regular MSB Part slot bypasses this preload
# pipeline — the chr appears in the MSB, but its asset bundle never
# loads, and the cell-load CTDs when the player approaches.
#
# Discovered seed 714653 (v0.24.50): c7710 Centipede Demon was placed
# at m46_71_00_00 pi=1 (vanilla c4480 Miranda Blossom). User CTDed when
# approaching the night-1 boss arena.
#
# v0.26.x: gate now keys on V3_DEDICATED_ARENA_BOSS_CHRS membership
# (an explicit set), not _source='script_spawn'. After the v0.26.x
# byte-level MSB audit (dev/audit_source_tags.py) reclassified the
# previously-script_spawn-tagged DS-heritage NBs to _source='nr_placed'
# — they DO appear in vanilla MSBs, just in UTF-16-LE-encoded c-prefix
# references the original catalog parser missed — the _source signal
# is no longer correct for "needs arena scaffolding to spawn." This
# explicit set captures the actual constraint: these chrs live in
# dedicated boss-arena MSBs (m47_80, m47_90, m48_00, m48_10, m48_20,
# m48_30, m19_00) where the surrounding EMEVD machinery preloads
# their asset bundles. Placing them at m60_xx overworld tiles leaves
# the asset bundle unloaded → CTD on cell-load.
#
# Reject filter (Gate 6 in _reject_target_for_slot): if target is in
# V3_DEDICATED_ARENA_BOSS_CHRS AND msb_base is m60_xx (overworld),
# reject.
# Grunt-tier supporting cast (c7711/c7712 Centipede Grub, c7810 Freja
# Spiderling) are NOT covered — they've been observed working at
# regular slots in many seeds, and their asset bundles are lighter
# weight. They share their parent boss's chrbnd.
V3_SCRIPT_SPAWN_BOSS_SLOTS = frozenset()  # set of (msb_filename, pi_int)
V3_SCRIPT_SPAWN_BOSS_SLOTS_META = {}
V3_SCRIPT_SPAWN_BOSS_GATED_TIERS = frozenset({'field_boss', 'miniboss', 'night_boss'})

# v0.26.x: boss-tier chrs whose vanilla MSB placements live exclusively
# in dedicated boss-arena MSBs (m47_xx, m48_xx, m49_xx, m19_xx). These
# need the arena's EMEVD machinery to preload their assets — placing
# them at m60_xx overworld tiles is the documented CTD-on-cell-load
# failure mode. Previously inferred from _source='script_spawn'; now
# explicit since the reclassification (see dev/audit_source_tags.py).
V3_DEDICATED_ARENA_BOSS_CHRS = frozenset({
    # v0.27.2: c4670 Ancestor Spirit and c7910 Storm King LIFTED from this
    # set per Alaric direction (98-seed sim 2026-05-26). Both are
    # _source='nr_placed' night_boss-tier chrs; their arena_only constraint
    # flowed only through this set. With v0.27.1's whole-MSB night-boss
    # arena preservation (V3_PRESERVE_NIGHT_BOSS_ARENAS), arena_only chrs
    # whose only valid slots are NB arenas became a pool gap — 0 placements
    # across 98 seeds. Lifting both: they now place organically at
    # night_boss-tier world slots. Each carries a fresh cap=1 in
    # V3_UNIQUE_TARGET_CAPS so they read as singular encounters.
    # NOTE: c7900 Nameless King was the vanilla pair-partner of c7910
    # (m48_20 + m19_00). It is deliberately LEFT in this set — Alaric
    # named only Storm King. Revisit c7900 if the pair should move together.
    'c7700',  # Gaping Dragon               — m47_80
    'c7710',  # Centipede Demon             — m47_90
    'c7800',  # Duke's Dear Freja           — m48_00
    'c7820',  # Smelter Demon               — m48_10
    'c7900',  # Nameless King               — m48_20 + m19_00 (pair-partner of lifted c7910)
    'c7920',  # Dancer of the Boreal Valley — m48_30
    # c4690 Grafted Scion (m46_65, m46_91) is in vanilla NR boss-arena
    # MSBs but plays as a miniboss / non-script-spawn class; v0.23.72
    # comments noted Grafted Scion was script_spawn-tagged
    # provisionally and historical playtest hasn't surfaced overworld
    # CTDs for it. Left out of this strict set for now; revisit if
    # CTDs are observed.
})


# v0.27.2: explicit arena_only LIFT set. The five MMV nightlord-tier
# imports below are tagged expects_boss_arena=true in mmv_imports.json,
# so the load_data() auto-extend block folds them into
# V3_ARENA_ONLY_TARGETS. Combined with v0.27.1's whole-MSB night-boss
# arena preservation that left them with zero eligible slots — confirmed
# 0 placements across the 98-seed sim (2026-05-26). Alaric direction:
# this is a pool gap, not intended scarcity — remove arena_only from
# them. This set is subtracted from V3_ARENA_ONLY_TARGETS at the end of
# the load_data() auto-extend block (mirrors the M-humanoid lift). The
# expects_boss_arena tag is intentionally left intact in mmv_imports.json
# (it still feeds the +10 placement-preference score); only the hard
# arena-lock is lifted. They now place at boss-tier world slots.
V3_ARENA_ONLY_FORCE_LIFT = frozenset({
    'c4720',  # Godfrey, First Elden Lord  (XL humanoid, nightlord, MMV)
    'c4721',  # Hoarah Loux                (XL humanoid, nightlord, MMV)
    'c4730',  # Starscourge Radahn         (GIGA quadruped_large, nightlord, MMV)
    'c5230',  # Scadutree Avatar           (GIGA quadruped_large, nightlord, MMV)
    'c8500',  # Manus, Father of the Abyss (XL humanoid, nightlord, MMV)
    # v0.27.13: c5200 Metyr, Mother of Fingers. XL nightlord. Was
    # arena-locked via the v0.23.72 expects_boss_arena auto-extend (not
    # the M-humanoid auto-lift's reach — Metyr is XL). The all-SOTE
    # mode sims (dev/sim_tier_transitions.py --sote) repeatedly showed
    # c5200 as the lone non-placing SOTE chr: 0/12 seeds at 31-chr
    # coverage. Same pool-gap reasoning as the five above — Alaric
    # direction, lift the hard arena-lock. expects_boss_arena stays in
    # the source tag (still feeds the +10 placement-preference score),
    # so Metyr still prefers real arenas but is no longer locked out of
    # boss-tier world slots.
    'c5200',  # Metyr, Mother of Fingers   (XL, nightlord, MMV→heritage-adjacent)
    # v0.27.37: c5030 Romina, Saint of the Bud. XL nightlord, arena-locked
    # via the v0.23.72 expects_boss_arena auto-extend (XL, so not reached
    # by the M-size auto-lift). Same pool-gap reasoning as the entries
    # above — Alaric direction, lift it. Footprint-clip concern checked
    # against the catalog: 20 of 49 fieldboss slots hold an XL+ enemy in
    # vanilla (Draconic Tree Sentinel XL, Ulcerated Tree Spirit XXL, Flying
    # Dragon/Magma Wyrm GIGA, …), so the boss-tier world slots demonstrably
    # fit her size class. expects_boss_arena stays in the source tag (still
    # feeds the +10 arena-preference score), so she prefers real arenas but
    # is no longer locked out of boss-tier world slots.
    'c5030',  # Romina, Saint of the Bud   (XL, nightlord, MMV)
})


# ============================================================================
# v0.27.40: FREEZE-PRONE IMPORTS — placement gate (single source of truth)
# ----------------------------------------------------------------------------
# Imported single-entity bosses that disable their own AI during a phase-
# transition buff and rely on an external (home-arena) re-enable that is gone
# when the rando relocates them. emevd_patch.py's nb_phase_reenable injects
# the re-enable, but it addresses the boss by ENTITY id and so can only reach
# ENTITY-BEARING slots (entity_id != 0); name-marker slots (entity_id == 0,
# where the rando binds by Part identity, not entity) are unreachable by any
# EMEVD patch. So these imports must be gated to entity-bearing slots, or they
# freeze post-transition with no possible remedy at the slot.
#
# The set is loaded from data/phase_transition_imports.json — THE SAME FILE
# emevd_patch.py derives _AT_RISK_PHASE_MARKERS from. One file, two consumers:
# the markers drive the re-enable WaitFor; the c_prefixes drive this gate. Add
# a future import to that JSON and both the re-enable AND this gate pick it up
# with no second list to maintain (the override-drift hazard this avoids).
#
# Size-compat sanity (verified 2026-05 against nr_boss_slots + nr_slot_
# inventory): the gate is cheap. M-size imports keep ~328 of 495 size-
# compatible slots; GIGA imports (Scadutree/Radahn) keep 74 of 80 (giant
# bosses fit only large slots, which are entity-bearing boss arenas anyway).
# Far from the force-lift "0 placements" failure mode.
def _load_freeze_prone_imports():
    """Return frozenset of c_prefixes from data/phase_transition_imports.json
    that need EMEVD re-enable (and so must be gated to entity-bearing slots).
    Empty on failure -> gate is a no-op (safe: worst case is the pre-existing
    behavior where these could land at name-marker slots and freeze)."""
    try:
        with open(_data_path('phase_transition_imports.json'), encoding='utf-8') as f:
            data = json.load(f)
        return frozenset((data.get('markers', {}) or {}).keys())
    except (OSError, ValueError, TypeError):
        return frozenset()


V3_FREEZE_PRONE_IMPORTS = _load_freeze_prone_imports()


# ============================================================================
# v0.24.67: Gate 5.5 — boss-healthbar tier slots × grunt/trash targets
# ============================================================================
# Slots that pop a boss healthbar UI run an EMEVD chain on death that
# expects clean entity teardown — a normal death anim, a normal corpse,
# a single boss-reward dispense, etc. A small number of chrs have
# unusual death sequences (NpcParam spawner-generator fields that fire
# on death, dissolve/dissipate anims with no normal corpse, instant-
# detonate detonations) that don't fit this assumption and CTD the
# boss-clear chain.
#
# Discovered seed 877217 v0.24.65: c3664 Cemetery Shade landed at
# m32_00 pi=31 ent=32000810 — the encampment boss slot for the Elder
# Lion. NpcParam variants 36640020/32/35 reference child entity IDs
# (23664000, 366400700, 366400000) in the spawner-generator slot
# which fire on death. Vanilla NR's encampment boss-clear was
# authored expecting an Elder Lion death sequence (normal corpse,
# clean teardown), not a Cemetery Shade phase-spawn-then-dissipate.
# Player CTDed on kill.
#
# Rather than blacklist c3664 by name we close the broader risk
# surface: grunt-tier and trash-tier chrs are not designed for boss-
# bar slots in the first place. They have lightweight death anims,
# no boss-reward path, no expectation of being a fog-gate target.
# Most existing grunt-at-boss-bar placements survive because they
# happen to have completely normal death sequences — those are
# whitelisted in V3_FRAGILE_SAFE_CONFIRMED from playtest. The few
# that aren't in SAFE_CONFIRMED are the risk surface for both
# Cemetery-Shade-class CTDs AND for "Giant Rat is the named boss
# now" thematic embarrassments.
#
# Gate behavior (in _reject_target_for_slot, between Gate 5 and 6):
# if target.tier ∈ {grunt, trash} AND slot is in V3_BOSS_SLOT_CATALOG
# AND slot's catalog tier ∈ V3_BOSS_BAR_TIERS AND target ∉
# V3_FRAGILE_SAFE_CONFIRMED → reject with reason 'grunt_trash_at_boss_bar'.
#
# Boss-bar tier set chosen empirically — for each catalog_tier value,
# computed the %% of entries with eid > 0 (= event-bound = pops
# healthbar). Tiers with >=60%% event-coverage are included; tiers
# below (mountaintop 33%%, ruins_boss 0%%, fort_boss 0%%) are
# excluded — their entries are mostly thematic spawns, not event
# bosses. The gate also checks V3_BOSS_SLOT_CATALOG membership
# (which is itself event-bound by construction), so a borderline
# tier value at a non-event slot won't trip the gate.
#
# c3664 itself was removed from V3_FRAGILE_SAFE_CONFIRMED as part
# of this release — its v0.20.52 "working" confirmation was at a
# different slot type and didn't cover boss-bar tiers. The tier
# tag was also demoted from miniboss → grunt in nr_enemy_tags.json
# (the HP/weight profile matches grunt territory: hp_max=939,
# weight=130, vs Elder Lion's hp_max=2560/weight=300).
V3_BOSS_BAR_TIERS = frozenset({
    'remembrance',       # 100% event-bound in catalog (100/100)
    'named_boss',        # 100% (78/78)
    'fieldboss',         #  96% (47/49)
    'nightboss',         #  91% (39/43)
    'encampment',        #  86% (6/7)   ← seed 877217 origin
    'fort_suffix',       #  75% (3/4)
    'castle_interior',   #  70% (7/10)
    'noklateo',          #  67% (12/18)
    'crater',            #  62% (5/8)
    'boss_suffix',       # 100% (4/4)
    'cathedral',         # 100% (3/3)
})

V3_BOSS_BAR_GATED_TIERS = frozenset({'grunt', 'trash'})


def _load_script_spawn_boss_slots():
    """Load data/nr_script_spawn_boss_slots.json.

    Returns: (slot_set, slot_meta). Empty values on missing/malformed file.
    """
    path = _data_path('nr_script_spawn_boss_slots.json')
    if not os.path.isfile(path):
        return frozenset(), {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return frozenset(), {}
    slots = raw.get('script_spawn_boss_slots', [])
    if not isinstance(slots, list):
        return frozenset(), {}
    slot_set = set()
    slot_meta = {}
    for entry in slots:
        if not isinstance(entry, dict): continue
        msb = entry.get('msb')
        pi = entry.get('pi')
        if not msb or pi is None: continue
        try:
            pi_int = int(pi)
        except (ValueError, TypeError):
            continue
        slot_set.add((msb, pi_int))
        slot_meta[(msb, pi_int)] = entry
    return frozenset(slot_set), slot_meta


(V3_SCRIPT_SPAWN_BOSS_SLOTS,
 V3_SCRIPT_SPAWN_BOSS_SLOTS_META) = _load_script_spawn_boss_slots()


# v0.23.57: pipeline-metadata dict for spoiler diagnostics. dcx_batch and the
# engine populate this cooperatively as the run progresses; write_spoiler_logs
# folds the contents into the spoiler header so we can debug runs where MSBs
# don't make it to the shuffle loop, auto-include silently fails, etc.
#
# Cleared at the start of every cmd_shuffle_v3 call. Keys (all optional):
#   'in_dcx_dir':              str — the input directory the GUI/CLI passed in
#   'vanilla_dir':             str — staging dir where decompressed .msb live
#   'spawn_pool_source_dir':   str — auto-include source dir (None if unset)
#   'spawn_pool_include':      dict — {n_added, n_already_present, n_missing}
#   'input_msb_count':         int — how many .msb files the shuffler iterated
#   'input_msb_listing':       list[str] — sorted MSB names that hit the loop
#   'spawn_pool_in_input':     dict — {pool_msb: True/False} per V3_SPAWN_POOL_MSBS
#   'msb_results':             dict — {msb_name: result_tuple_or_None}
#   'spawn_pool_results':      dict — {pool_msb: detailed status} per pool MSB
V3_PIPELINE_METADATA = {}


def _reset_pipeline_metadata():
    """Clear the metadata dict at the start of each run."""
    V3_PIPELINE_METADATA.clear()


# v0.23.56: SPAWN-POOL MSB INVENTORY.
# These tiny (~4-7KB) MSBs each contain a single boss-tier chr at world
# origin (0,0,0). NR's engine-internal SmallBase attach system loads them
# as overlays at runtime, teleporting the chr to per-expedition attach
# points on live world MSBs. EMEVD doesn't do the teleporting — it only
# queries `SmallBaseAttached(attachPoint, poolId)` to detect bindings
# and gate progression on boss death flags.
#
# Vanilla NR ships these maps in the map/mapstudio folder. They're the
# rotation system: Tree Sentinels at the castle rooftop, BBH at Castle
# Basement, Death Rite Bird at random Field Boss arenas, etc.
#
# The rando's catalog (V3_BOSS_SLOT_CATALOG) tags pi=1 of each spawn-pool
# map as a boss slot. The OOPS_ALL_NB intercept fires correctly on these
# slots when they're in the input directory. Problem: most users' me3
# profiles only contain the live world MSBs they want randomized; the
# spawn-pool maps live in vanilla and ship un-overridden, so they always
# spawn the vanilla rotation chr.
#
# v0.23.56 introduces auto-inclusion: if dcx_batch.rando_pipeline is
# called with `spawn_pool_source_dir` set, any of these MSBs missing
# from `in_dcx_dir` get pulled from the source dir, shuffled normally,
# and written to the output. The user can then deploy them into me3.
#
# ──────────────────────────────────────────────────────────────────────
# FIXED v0.27.29: castle-variant spawn-pool MSBs now swap
# ──────────────────────────────────────────────────────────────────────
# Spawn-pool MSBs are m46 template tiles whose pi=1 boss is teleported into
# a live arena at runtime (SmallBaseAttached). They come in two shapes:
#   - FIELD-boss rotations (m46_52..m46_74): named "... (Field Boss)".
#   - CASTLE-variant rotations (m46_86/87/88/90/91/95): named with POI-
#     interior conventions — "(Castle Basement)", "(Castle)".
# Both shapes list pi=1 in V3_SPAWN_POOL_MSBS, pin it via
# V3_BOSS_TIER_PINNED_SLOTS (msb, 1), and have a V3_BOSS_SLOT_CATALOG entry.
#
# BUG (seen seed 670313 v0.27.28): every FIELD twin swapped (n_swaps=1)
# while every CASTLE variant shipped vanilla (n_swaps=0). Players met a
# vanilla Bell Bearing Hunter in the Castle Basement (m46_87) and vanilla
# Crucible Knight in the castle (m46_95), worst in all-SOTE mode.
#
# ROOT CAUSE (confirmed by reading the uncompressed castle MSBs + bisecting
# pick_target_cp): NOT a near-origin/cluster/placeholder/emerge-marker
# issue — those were all red herrings from stale comments. The castle
# tiles are structurally identical to the field twins (3 Parts: c1000
# marker + pi=1 boss + AEG asset, pi=1 named + real npc, eid %10000==800).
# The divergence was pure NAME-MARKER CLASSIFICATION in pick_target_cp:
# the arena / night-boss gates (the _arena_only and NIGHT_BOSS_ONLY pool
# subtractions) keyed on slot_variant_name matching the BROAD markers
# ("Field Boss"/"Night Boss") plus the catalog `arena` flag. The castle
# names match neither broad marker, and these entries carry arena:False
# + scope:extended, so the slot read as non-arena/non-NB, both subtractions
# fired, and in all-SOTE mode the small boss-tier SOTE pool emptied →
# pick_target_cp returned None → vanilla. (With the full roster the
# non-arena fallback pool still had boss-tier chrs, so the bug was less
# visible but still present.)
#
# FIX (v0.27.29, in pick_target_cp): a catalogued spawn-pool rotation
# source (V3_SPAWN_POOL_MSBS pi=1 AND in V3_BOSS_SLOT_CATALOG at any
# scope) now counts as arena + night-boss for those gates, regardless of
# name marker — mirroring the v0.24.98 catalog-membership override that
# already promotes the same slot's recipient_is_boss. Narrow: only the
# enumerated spawn-pool pi=1 slots qualify, so gating elsewhere is
# untouched, and boss-tier preserve still holds (no grunt leak — verified).
# ──────────────────────────────────────────────────────────────────────
#
# Format: { 'msb_basename_without_ext': 'description' }
V3_SPAWN_POOL_MSBS = {
    # Field-Boss tier rotation chrs (m46_5x_xx and m46_72/74)
    'm46_52_00_00': 'c3250 Draconic Tree Sentinel (Field Boss rotation)',
    'm46_53_00_00': 'c3251 Tree Sentinel (Field Boss rotation)',
    'm46_54_00_00': 'c3252 Royal Carian Knight (Field Boss rotation)',
    'm46_55_00_00': 'c3460 Leonine Misbegotten (Field Boss rotation)',
    'm46_56_00_00': 'c3100 Bell Bearing Hunter (Field Boss rotation)',
    'm46_57_00_00': 'c4270 Elder Lion (Field Boss rotation)',
    'm46_58_00_00': 'c4500 Flying Dragon (Field Boss rotation)',
    'm46_59_00_00': 'c4021 Royal Revenant (Field Boss rotation)',
    'm46_63_00_00': 'c4640 Demi-Human Queen (Field Boss rotation)',
    # v0.24.38: corrected labels for script_spawn entries. The chr name
    # in NR's roster differs from the older labels carried over from ER
    # data. See data/nr_script_spawn_boss_slots.json for the cross-
    # referenced catalog.
    'm46_64_00_00': 'c4670 Ancestor Spirit (Field Boss rotation, script_spawn)',
    'm46_65_00_00': 'c4690 Grafted Scion (Field Boss rotation, script_spawn)',  # was: "Putrid Avatar"
    'm46_66_00_00': 'c4770 Onyx Lord (Field Boss rotation)',
    'm46_67_00_00': 'c4810 Ulcerated Tree Spirit (Field Boss rotation)',
    'm46_68_00_00': 'c4910 Magma Wyrm (Field Boss rotation)',
    'm46_69_00_00': 'c7100 Crucible Knight Ordovis (Field Boss rotation)',
    'm46_72_00_00': 'c5011 [unknown] (Field Boss rotation)',
    'm46_74_00_00': 'c4980 Death Rite Bird (Field Boss rotation)',
    # Castle-variant rotation chrs (m46_8x — extended scope)
    'm46_81_00_00': 'c2100 Black Knife Assassin (Castle-variant rotation)',
    'm46_82_00_00': 'c3181 Red Wolf of Radagon (Castle-variant rotation)',
    'm46_86_00_00': 'c3460 Leonine Misbegotten (Castle-variant rotation)',
    'm46_87_00_00': 'c3100 Bell Bearing Hunter (Castle Basement rotation)',
    'm46_88_00_00': 'c4021 Royal Revenant (Castle-variant rotation)',
    'm46_90_00_00': 'c4670 Ancestor Spirit (Castle-variant rotation, script_spawn)',
    'm46_91_00_00': 'c4690 Grafted Scion (Castle-variant rotation, script_spawn)',  # was: "Putrid Avatar"
    'm46_95_00_00': 'c7100 Crucible Knight Ordovis (Castle-variant rotation)',
    # v0.27.30: m46_81 + m46_82 added. They were in V3_BOSS_SLOT_CATALOG and
    # the spawn-pool detector flagged them in spoilers, but were absent from
    # this curated list, so _is_spawn_pool_rotation_source returned False and
    # the v0.27.29 _is_catalogued_spawn_pool_boss gate (which ANDs on it) could
    # not fire — Black Knife Assassin (m46_81) and Red Wolf (m46_82) shipped
    # vanilla every seed (Alaric seed 230261 Red Wolf repro). MSB structure
    # verified byte-identical to m46_87: pi=0 c1000 marker / pi=1 boss eid…800
    # pos (0,0,0) / pi=2 AEG asset. m46_80 (The Oldest Gaol) deliberately NOT
    # added here — it is a 4-boss arena (pi=1..4 at distinct real positions),
    # not a single rotation source; the pi=1-is-the-boss model would mishandle
    # it. m46_80 needs the multi-slot arena path, tracked separately.
    # NOTE: m48_20_00_00 is NOT in this list. It contains c7910 at (0,0,0)
    # which superficially matches the spawn-pool pattern, but the MSB also
    # has c3970, c4505, and c7900 at real positions — it's a Night Boss
    # arena (likely a Nightlord Night-2 fight), not a rotation source.

    # v0.24.38: SCRIPT_SPAWN SUB-CATEGORY (m46_64/65/90/91)
    # ───────────────────────────────────────────────────────
    # These 4 entries reference c4670 Ancestor Spirit and c4690 Grafted
    # Scion, both `_source: script_spawn` (target-only c-prefixes). The
    # rando's main swap loop hits the `script_spawn_target_only_at_msb`
    # filter at line ~9963 and SKIPS them. Result: pi=1 stays vanilla
    # (n_swaps=0 in spoiler's spawn_pool_results), MSB ships back
    # unchanged.
    #
    # The vanilla EMEVD then runs SmallBaseAttached at runtime to ferry
    # the chr to the live arena (m46_91 castle interior, etc.). When the
    # ferry succeeds, the boss appears in vanilla form. When the ferry
    # FAILS (broken entity_id chain, chrbnd preload miss, NPCParam
    # remap collision, etc.), the boss is missing — Alaric's seed 271328
    # m46_91 case.
    #
    # Diagnosis without raw NR file access is limited. The hand-off
    # between rando-modified MSBs/EMEVD and vanilla EMEVD spawn chains
    # is the open mechanism question.
    #
    # Future direction: implement the "Fix path NOT YET IMPLEMENTED"
    # described above this dict (bypass the near-origin/target-only
    # filter for V3_SPAWN_POOL_MSBS pi=1 entries, let the rando pick a
    # non-script_spawn target chr). That puts these 4 slots under the
    # rando's control and ensures the chosen target has valid chrbnd.
    # Caveat: would need to verify the SmallBaseAttached system respects
    # post-rando swaps (it might not — see line 6177-6181 comment about
    # users seeing vanilla Tree Sentinels at Castle Roof even when the
    # rando does swap pi=1).
}


def _is_spawn_pool_rotation_source(msb_base, pi):
    """True if (msb_base, pi) is a spawn-pool MSB's rotation-source slot.

    Spawn-pool MSBs (V3_SPAWN_POOL_MSBS) all share the same structure:
    pi=0 c1000 placeholder, pi=1 the boss/rotation chr ferried into the
    live arena via SmallBaseAttached, pi=2 an AEG asset. Only pi=1 is
    a real swap candidate; pi=0 and pi=2 are infrastructure.

    Used by the swap loop's V3_TARGET_ONLY_SOURCES filter (see v0.24.97)
    to exempt the four script_spawn-source rotation entries — m46_64,
    m46_65, m46_90, m46_91 pi=1 (Ancestor Spirit and Grafted Scion) —
    from being skipped. Without this exemption those four slots ship
    vanilla every seed because their c-prefixes are tagged
    `_source: script_spawn`, defeating rotation randomization.

    Accepts msb_base WITH or WITHOUT the .msb suffix (callers in the
    swap loop pass the .msb form from msb_base; callers in tests may
    pass the bare form from V3_SPAWN_POOL_MSBS keys).
    """
    if msb_base.endswith('.msb'):
        msb_base = msb_base[:-4]
    return msb_base in V3_SPAWN_POOL_MSBS and pi == 1


def is_catalogued_boss_slot(msb_name, pi, scope='broad'):
    """Return True if (msb_name, pi) is in V3_BOSS_SLOT_CATALOG and the
    entry's scope is enabled by the requested OOPS_ALL_NB scope.

    scope='strict'   only matches catalog entries with scope='strict'
    scope='broad'    matches scope in ('strict', 'broad')
    scope='extended' matches scope in ('strict', 'broad', 'extended')
    """
    entry = V3_BOSS_SLOT_CATALOG.get((msb_name, pi))
    if entry is None: return False
    entry_scope = entry.get('scope', 'extended')
    if scope == 'strict':
        return entry_scope == 'strict'
    elif scope == 'broad':
        return entry_scope in ('strict', 'broad')
    else:  # extended
        return entry_scope in ('strict', 'broad', 'extended')


# v0.23.52: full MSB Part inventory diagnostic. When an MSB filename
# (without .dcx) is in this set, the engine writes EVERY Part of that
# MSB to the spoiler's diagnostic_trace, including npc=0 placeholders
# and Parts that get filtered out by source-exclude rules. Used to
# answer "where is X in this MSB" questions without needing offline
# Oodle decompression. Empty set = no diagnostic overhead.
#
# Pre-populated with the castle MSB to investigate the user's "BBH
# at castle basement" report. The castle has 16 missing pi indices
# in seed 257798's spoiler (gap from pi=43 to pi=58); inventory will
# show whether any of those are c3100 BBH Parts being filtered out.
V3_DIAGNOSTIC_INVENTORY_MSBS = {
    'm60_43_36_50.msb',
    # v0.23.58: dump every spawn-pool MSB's full Part inventory into the
    # spoiler trace. Cheap (~3-4 Parts per map × 23 maps = ~70 trace
    # entries) and confirms whether the MSB the rando saw matches what
    # vanilla NR ships. If a user's vanilla_msbs has FIA-modified spawn-pool
    # MSBs (or otherwise different structure), the inventory dump shows
    # the divergence — pi indices, c-prefixes, npc_param_ids, eids, and
    # positions, all read straight from the MSB binary the shuffler is
    # operating on.
}
# (Keep the spawn-pool addition out-of-line so the comment stays readable.)
V3_DIAGNOSTIC_INVENTORY_MSBS.update(
    b + '.msb' for b in (
        'm46_52_00_00', 'm46_53_00_00', 'm46_54_00_00', 'm46_55_00_00',
        'm46_56_00_00', 'm46_57_00_00', 'm46_58_00_00', 'm46_59_00_00',
        'm46_63_00_00', 'm46_64_00_00', 'm46_65_00_00', 'm46_66_00_00',
        'm46_67_00_00', 'm46_68_00_00', 'm46_69_00_00', 'm46_72_00_00',
        'm46_74_00_00', 'm46_86_00_00', 'm46_87_00_00', 'm46_88_00_00',
        'm46_90_00_00', 'm46_91_00_00', 'm46_95_00_00',
    )
)
# v0.23.68: hub MSB inventory dump. Identifies boss-tier interior chrs
# (e.g. Black Knife Assassin in Castle Watering Hole basement) so the
# user can add specific (msb, pi) entries to V3_BOSS_TIER_PINNED_SLOTS
# to enable randomization of those slots while still preserving NPC
# dialogues / quest triggers in the rest of the hub. Hub MSBs are
# normally passthrough so the rando never visits their interior; the
# inventory dump runs in shuffle_msb_v3 specifically when a hub is
# entered in pinned-only mode (and the inventory section runs
# unconditionally regardless of whether any pin matches), so the
# diagnostic surfaces every Part for review.
#
# v0.23.69: also include _99 expedition-mode variants. NR splits hub
# maps into _00 (static castle / Roundtable) and _99 (expedition
# instance — same map, different runtime context). The user's me3 may
# install only the _99 variants if they don't ship modifications to
# the static castle. Both variants need to be diagnosable; including
# both in this set is harmless when the file isn't in input_dir.
V3_DIAGNOSTIC_INVENTORY_MSBS.update(
    b + '.msb' for b in (
        'm13_00_00_00', 'm13_20_00_00',  # Castle Watering Hole + sub
        'm14_00_00_00',                  # other hub
        'm18_00_00_00',                  # Roundtable
        'm10_00_00_00', 'm11_00_00_00', 'm12_00_00_00',  # other hubs
        # _99 expedition-mode variants
        'm13_00_00_99', 'm13_20_00_99',
        'm14_00_00_99',
        'm18_00_00_99',
        'm10_00_00_99', 'm11_00_00_99', 'm12_00_00_99',
    )
)


V3_PROBLEM_SLOTS = {
    # (msb_name, part_index): 'reason for documentation'
    # Tier 3 manual override. Empty initially. Populate based on playtest.
    # v0.20.7: m30_30 fort basement Giant Rat source — bumpy stair geometry
    # traps slow-locomotion grounded enemies (loco=0/3). User playtest
    # showed Putrid Corpse stuck on terrain at this slot. Keeping the rat
    # vanilla — Giant Rat (M, loco=3) navigates basement bumps fine in
    # vanilla because that's literally what the slot was designed for.
    ('m30_30_00_00.msb', 22): 'fort basement bumpy stairs — slow loco-0 enemies stuck',
    # v0.20.11: All previous v0.20.9-10 entries (m45_51 + 35 preemptive
    # boss-tier-source origin slots) REMOVED. Replaced by automatic
    # detection in the main shuffle loop: any slot with entity_id == 0
    # AND position near origin is identified as a script-spawn marker
    # and skipped. Heuristic verified against confirmed CTD slots
    # (m45_01 pi=5, m45_51 pi=2). Cleaner than per-slot blocking
    # because it doesn't require knowing which slots are dangerous in
    # advance — the rule subsumes them.
    # v0.20.33: Miranda slot was added here briefly. v0.20.34 moves it
    # to V3_SENSITIVE_ONLY_SLOTS — fragile/RESILIENT was too aggressive
    # for a Field Boss slot that should still get a boss-class target.
    # v0.20.65 → v0.24.18: Cathedral basement Fire Monk source slot
    # MIGRATED from V3_PROBLEM_SLOTS to V3_POSITION_SHIFTS. v0.20.65 used
    # the SAFE-only fragility filter; user playtest reports continued
    # freezes ("a lot of guys frozen down there") indicated the SAFE
    # subset wasn't actually safe. The off-mesh-patch root cause is
    # spawn-position, not chr identity — escape via position shift
    # instead. See V3_POSITION_SHIFTS entry for m38_10 pi=6.
    # v0.20.69: Cathedral interior 1 upper-floor Guardian Golem source.
    # User playtest: c4620 Astel/Naturalborn of the Void placed here,
    # frozen. Slot is in fragile map m38_00 (Cathedral) — c4620 was
    # in SAFE_CONFIRMED so the SAFE filter allowed it. Astel is XXL
    # GIGA-class — confirmed working in v0.20.41 at outdoor slots
    # ("working astel off in the distance"), but cathedral interior
    # geometry doesn't accommodate the body size / scripted intro
    # animation. Narrow slot fix preserves Astel availability at
    # non-cathedral fragile slots.
    #
    # v0.24.75: kept in V3_PROBLEM_SLOTS for the SAFE-only base filter,
    # BUT now loosened via V3_PROBLEM_SLOT_EXTRA_ALLOWS to permit
    # large dragons (flying_dragon family + Magma Wyrm class) which
    # the user reports as working at this slot per playtest. See
    # V3_PROBLEM_SLOT_EXTRA_ALLOWS entry below.
    ('m38_00_00_00.msb', 51): 'Cathedral interior upper floor — Guardian Golem source, c4620 Astel froze (v0.24.75 loosened: dragons allowed via EXTRA_ALLOWS)',
    # v0.24.18 → v0.24.75 LIFTED → v0.24.77 RESTORED: Magic fort rampart.
    #
    # v0.24.18 originally added on c4441 Land Squirt CTD (emerge-from-
    # ground intro fails on roof tile geometry — no terrain to push
    # from). v0.24.75 lifted on user evidence that Centipede Demon
    # (c7710) worked there.
    #
    # v0.24.77 RESTORED after seed 886942 v0.24.75 CTD: c4810 Erdtree
    # Avatar (Remembrance) placed here, player CTD on leaving Fort.
    # Erdtree Avatar has the SAME "rise from the earth" emerge intro
    # as c4441 Land Squirt — so the Fort slot's emerge-failure pattern
    # is real, just chr-specific to emerge-class chrs. Centipede Demon
    # works because it has a different intro animation (DS1 ceiling
    # drop / pre-placed).
    #
    # The slot is now in V3_PROBLEM_SLOTS again (SAFE-only base
    # filter) AND in V3_PROBLEM_SLOT_EXTRA_ALLOWS (whitelisting the
    # known-working big chrs like Centipede Demon, Gaping Dragon) AND
    # in V3_PROBLEM_SLOT_EXTRA_BANS (specifically banning the emerge-
    # anim family). This three-layer config gives variety while
    # preventing the known failures.
    ('m30_30_00_00.msb', 45): 'Magic fort rampart — Guardian Golem (Fort) source on roof. Emerge-anim chrs CTD here (c4441 Land Squirt v0.24.18, c4810 Erdtree Avatar v0.24.77 seed 886942). EXTRA_ALLOWS opens big-creature pool, EXTRA_BANS blocks emerge-anim chrs.',
    # v0.24.60: SW-corner Putrid Corpse cluster (Limveld start tile).
    # The slot_repositions.json entries at these slots (added v0.24.48 +
    # v0.24.49 cross-phase) shift the spawn 7.07m inward (+5 X, -5 Z) to
    # escape the geographic SW-corner edge. Originally validated against
    # Centipede Grub + Basilisk freezes in seed 460401 — the shift seemed
    # to work for those chrs.
    #
    # User report seed 923958 (v0.24.58 engine fingerprint): c6060 Goat
    # at pi=19 (post-reposition position [-98.99, 108.14, 98.12]) and
    # c4120 Demi-Human Chief at pi=20 (post-reposition position
    # [-100.62, 105.48, 88.15]) BOTH froze. The 7.07m shift was NOT
    # sufficient for these chr types — narrower nav requirement than
    # Centipede Grub.
    #
    # Two-mechanism fix: slot_repositions.json keeps applying (shifts
    # the spawn position; helps chrs whose 7m clearance is enough); and
    # V3_PROBLEM_SLOTS now flags fragility (restricts the swap pool to
    # V3_FRAGILE_SAFE_CONFIRMED). c6060 / c6031 are not in SAFE_CONFIRMED
    # so they're auto-blocked. c4120 IS in SAFE_CONFIRMED — additional
    # V3_PROBLEM_SLOT_EXTRA_BANS entry below covers that.
    #
    # The slot_repositions and V3_PROBLEM_SLOTS mechanisms are orthogonal:
    # the JSON repos apply at DCX-write time; V3_PROBLEM_SLOTS applies at
    # the chr-pick stage. Both fire for these slots.
    ('m60_42_36_00.msb', 19): 'SW corner Putrid Corpse cluster (v0.24.49 repos insufficient) — c6060 Goat froze post-shift, seed 923958',
    ('m60_42_36_00.msb', 20): 'SW corner Putrid Corpse cluster (v0.24.49 repos insufficient) — c4120 Demi-Human Chief froze post-shift, seed 923958',
    ('m60_42_36_10.msb', 19): 'SW corner Putrid Corpse cluster — phase sibling of _00 pi=19',
    ('m60_42_36_10.msb', 20): 'SW corner Putrid Corpse cluster — phase sibling of _00 pi=20',
    ('m60_42_36_20.msb', 19): 'SW corner Putrid Corpse cluster — phase sibling of _00 pi=19',
    ('m60_42_36_20.msb', 20): 'SW corner Putrid Corpse cluster — phase sibling of _00 pi=20',
}


# v0.23.72-late: POSITION SHIFTS — fragile-slot rescue via XYZ translation.
# -----------------------------------------------------------------------
# Background. Most fragile-slot fixes work by RESTRICTING the eligible pool
# at that slot — only V3_RESILIENT_BIPEDS or V3_FRAGILE_SAFE_CONFIRMED chrs
# can land. That's correct but limiting: variety suffers because we can
# never put (e.g.) a Death Rite Bird at a slot whose fragility is "spawn
# point clips into a bumpy stair edge" when a 2-meter Y-lift would clear
# the geometry.
#
# Position shifting expands the eligible pool by NUDGING the slot's authored
# position to a known-better spot, then treating the slot as non-fragile
# for placement purposes. The chr spawns at the shifted position rather
# than the original.
#
# Trade-offs accepted by this mechanism (per user 2026-05-12):
#   - Visual position no longer matches what FromSoft authored. A small
#     XYZ shift is usually imperceptible; a large one will look weird.
#   - EMEVD events that reference the slot's vanilla position may misfire
#     (camera focuses, "enemy reached point X" triggers, partner-spawn
#     anchors). For this reason we ONLY shift slots that are known to be
#     non-event-anchored — see the curation criteria below.
#   - Cluster aesthetics: shifting a Part in a multi-Part cluster breaks
#     the cluster's spatial composition. The mechanism therefore skips
#     any Part that's in a cluster (cluster_id != None at apply time).
#
# Format:
#   V3_POSITION_SHIFTS[(msb_name, part_index)] = {
#       'dxyz': (dx, dy, dz),   # offset in world units
#       'note': 'reason — observed problem, why this shift works',
#       'observed_in': 'seed N playtest' | 'static analysis' | ...,
#   }
#
# Curation criteria (entries must meet ALL):
#   1. Slot is non-event-anchored. Verified by: no EMEVD common_func
#      reference to the entity_id, no Region trigger containing the
#      original position, no NPC param's "scripted spawn" flag.
#   2. Slot is non-cluster. Will be defensively skipped at apply time if
#      it sneaks in, but should be filtered here at curation.
#   3. Shift magnitude justified. Document the observed problem (e.g.
#      "spawns 1.5m below visible terrain, falls through floor") and why
#      the proposed shift addresses it (e.g. "+Y 2.0 lifts spawn above
#      sub-surface").
#   4. Tested. Either at a single seed where the issue was observed and
#      the shifted version was verified working, OR via the
#      sensitivity-test seed (planned, see TODO.md).
#
# What this is NOT:
#   - NOT collision authoring. We don't insert invisible platforms or
#     edit .hkx files. Just move the spawn marker.
#   - NOT a substitute for V3_PROBLEM_SLOTS. Slots where fragility is
#     "this whole region is rough and pool-narrowing is correct" stay in
#     PROBLEM_SLOTS. POSITION_SHIFTS is for the subset where the issue
#     is point-specific and a small move resolves it.
#   - NOT cluster-aware. Only solo Parts.
#
# Empty initially. Populate based on playtest observation. The companion
# sensitivity-test seed (TODO.md) will surface candidate slots
# systematically; for now this table is hand-curated.
V3_POSITION_SHIFTS = {
    # v0.24.18: First two real entries. Both are starting-guess shift
    # values without playtest validation — iterate if the shift direction
    # doesn't fix the freeze, or escalate to a tighter PROBLEM_SLOTS
    # restriction.
    #
    # ----- Cathedral basement Fire Monk / Mausoleum Knight source -----
    # Vanilla has a boss-healthbar-flagged Fire Monk (or Mausoleum
    # Knight variant) at this slot, but the spawn position falls on an
    # off-mesh patch between two navmesh tiles. v0.20.65 noted DTS
    # (c3250, normally SAFE) freezing here in playtest, leading to a
    # V3_PROBLEM_SLOTS entry restricting the pool to SAFE_CONFIRMED.
    # User report v0.24.x: "i've seen a lot of guys frozen down there"
    # — even SAFE chrs break, so the restriction was insufficient.
    # Switching strategy: relocate the spawn to nearby navmesh.
    #
    # Shift direction is a guess — (+2.0 X, +1.0 Y, +2.0 Z) nudges
    # diagonally to find adjacent tiles; if this doesn't break the
    # freeze, try larger horizontal magnitudes or different signs.
    # EMEVD anchoring concern: the boss healthbar trigger is region-
    # based and anchors on entity_id rather than position, so a small
    # shift should preserve it. If the healthbar stops appearing after
    # this shift, the region is tighter than assumed and we revert.
    #
    # NOTE: this slot's V3_PROBLEM_SLOTS entry was REMOVED in v0.24.18
    # — the shift mechanism implicitly clears fragility classification,
    # making the SAFE-only restriction redundant. If shift gets skipped
    # for cluster-bound placements (lookup_position_shift docs), the
    # slot will get a broader pool than before — accepting that risk
    # since the SAFE-only restriction wasn't actually safe.
    ('m38_10_00_00.msb', 6): {
        'dxyz': (2.0, 1.0, 2.0),
        'note': 'Cathedral basement off-mesh patch — Fire Monk / '
                'Mausoleum Knight boss-healthbar source. v0.20.65 DTS '
                'froze here under SAFE filter; v0.24.x user "a lot of '
                'guys frozen". Diagonal nudge to escape off-mesh '
                'patch. Tentative shift; iterate on values if freeze '
                'persists.',
        'observed_in': 'multiple playtest reports v0.20.65 → v0.24.17',
    },
    # ----- Demi-Human Queen anchor — quadruped pathlock -----
    # m46_77 pi=8 is the Queen's center anchor at exactly (0,0,0),
    # sized for a bipedal humanoid XL boss. Quadrupeds freeze here with
    # wider hit_radius + shorter hit_height — the AI can't pathfind out
    # to chase the player.
    #
    # Iteration history:
    #   v0.23.81  (3.0, 0.5, -3.0)   — Initial guess, "shift toward
    #     cluster center where mobs form natural open lane." Tentative
    #     based on assumed ±9-unit mob radius. RESULT: still froze.
    #     - seed 211409 (c3181 Red Wolf of Radagon, quadruped L):
    #         "the wolf froze too, looks like a map-based freeze"
    #     - seed 975181 (c5820 Great Red Bear, quadruped XL):
    #         "frozen still"
    #     Two distinct quadrupeds at the same dxyz → not a per-chr issue,
    #     the (+3, -3) corner is itself bad.
    #
    #   v0.24.18  (0.0, 0.5, -5.0)   — CURRENT. Empirical cluster scan
    #     of m46_77 (8 Parts total, 7 grunts + Queen anchor) shows the
    #     mob centroid is at (X=-0.49, Z=-3.11), median (X=+0.68, Z=-4.96)
    #     with grunts spread X∈[-7.1, +4.9], Z∈[-9.6, +4.1]. The cluster
    #     is roughly X-symmetric and extends into -Z. Three grunts (pi 2,
    #     3, 7) already live within ~3 units of (0, _, -5), so the
    #     navmesh there is demonstrably solid for chr footprints. Pure
    #     -Z shift down the symmetry axis sidesteps the +X / -X polarity
    #     question entirely.
    #
    # If THIS shift also freezes, the diagnosis branches:
    #   A) Try (0, +5, -5)  — same XZ, big Y lift. Tests whether the
    #      issue is off-mesh patch (Y matters) vs XZ pathlock.
    #   B) Try (0, +0.5, -7) — deeper into -Z, between pi=5 and pi=6.
    #      Most isolated point in cluster, ~4u from nearest grunt.
    #   C) If both fail, the arena's navmesh genuinely can't accept
    #      quadruped collision footprints here — promote to
    #      V3_PROBLEM_SLOTS with "no quadrupeds" restriction.
    #
    # Slot is non-cluster (Queen is solo-Part in m46_77; mobs are
    # separate Parts pi=1-7). EMEVD: m46_77 healthbar binds to entity
    # 46770800 by ID, position-agnostic.
    # ----- Castle basement POI boss slot (Leonine Misbegotten source) -----
    # v0.27.0: seed 568209 — c4680 Full-Grown Fallingstar Beast placed
    # here (castle_interior tier, swapped onto a Leonine Misbegotten
    # slot). Playtest: AI was ACTIVE — the boss attacked and was not
    # inert — but it was pinned to one spot, and the reward drop spawned
    # partly sunk into the floor. Diagnosis: this is a Class 2 (geometry-
    # stuck) case, not Class 1 (AI-off). The slot Part transform is the
    # (0,0,0) POI placeholder; the engine pull-in places the entity by
    # its MODEL ORIGIN, and c4680's origin (a flying_dragon-class anim)
    # sits lower relative to its feet than the humanoid Leonine it
    # replaced — so the whole entity, drop included, lands too low.
    #
    # This entry fixes THIS slot. The general fix is the per-c-prefix
    # V3_MODEL_Y_OFFSET table below — c4680 sinks on any humanoid-origin
    # POI slot, not just this one. Starting guess +1.0 (user eyeballed
    # the drop as ~1m sunk); iterate from playtest.
    ('m46_86_00_00.msb', 1): {
        'dxyz': (0.0, 1.0, 0.0),
        'note': 'c4680 Fallingstar Beast sinks into castle-basement '
                'floor — model origin lower than the humanoid slot '
                'occupant. +1.0 Y starting guess (seed 568209). See '
                'V3_MODEL_Y_OFFSET for the per-chr generalization.',
        'observed_in': 'seed 568209 (c4680 at m46_86 pi=1)',
    },
}


# ============================================================================
# v0.27.0 — PER-C-PREFIX MODEL Y-OFFSET
# ----------------------------------------------------------------------------
# V3_POSITION_SHIFTS above is keyed (msb, part_index) — it fixes one slot.
# Some height problems are not slot properties, they are CHR properties: a
# c-prefix whose model origin sits at a different height-above-feet than the
# humanoid the rando swapped it for. On a POI slot (Part transform = (0,0,0),
# engine pull-in places by model origin) such a chr lands too low (or high)
# everywhere it is placed, regardless of slot.
#
# Observed v0.27.0 seed 568209: c4680 Full-Grown Fallingstar Beast sank into
# the castle-basement floor; its reward drop spawned partly underground.
# c4680 is a flying_dragon-class anim — its origin is calibrated for an
# airborne pose, so it rides low on a ground POI slot. This is the same
# class of issue for any oversized non-humanoid boss on a humanoid POI slot.
#
# V3_MODEL_Y_OFFSET maps c-prefix -> dy (world units, +up). It is applied at
# MSB-write time IN ADDITION to any V3_POSITION_SHIFTS dxyz for the slot
# (slot shift handles slot-specific problems; this handles chr-specific
# ones; they stack). dy == 0.0 is a no-op.
#
# IMPORTANT — what does NOT belong here:
#   - V3_FRAGILE_SENSITIVE_TARGETS chrs. Those are Class 3 (locomotion /
#     terrain mismatch) — aquatic gait on land, true-quadruped navmesh
#     pathing, anchored AI. A height offset does NOT fix Class 3; lifting
#     a Land Octopus 1 unit just floats the same broken pathing higher.
#     SENSITIVE is handled by the fragile-slot blacklist, not here. Do not
#     pre-seed this table with SENSITIVE chrs.
#
# CALIBRATION: every value below is a playtest-derived guess. Only c4680
# has an observation behind it (and that is a coarse +1.0 eyeball — refine
# it). The rest are 0.0 placeholders, grouped by family, so the table
# structure exists and a playtest only needs to fill a number. A 0.0 entry
# ships nothing — it is a no-op until measured. Do NOT bulk-fill these.
V3_MODEL_Y_OFFSET = {
    # --- flying_dragon anim (origin calibrated for airborne pose; these
    #     are the most likely to sink on a ground POI slot) ---
    'c4680': 1.0,    # Full-Grown Fallingstar Beast — seed 568209, castle
                     #   basement, drop sank ~1m. STARTING GUESS, refine.
    # 'c4500': 0.0,  # Flying Dragon (Unscaled)         — untested
    # 'c4501': 0.0,  # Decaying Ekzykes (Unscaled)      — untested
    # 'c4502': 0.0,  # Decaying Ekzykes-class Dragon    — untested
    # 'c4503': 0.0,  # Borealis the Freezing Fog        — untested
    # 'c4505': 0.0,  # Flying Dragon (Small)            — untested
    # 'c4511': 0.0,  # Lichdragon Fortissax             — untested
    # 'c4911': 0.0,  # Great Wyrm Theodorix             — untested
    # 'c5860': 0.0,  # Ghostflame Dragon                — untested
    # 'c6260': 0.0,  # Death Rite Bird                  — untested
    # 'c7510': 0.0,  # Adel, Baron of Night             — untested
    # 'c7511': 0.0,  # Adel, Baron of Night             — untested
    # 'c7530': 0.0,  # Faurtis Stoneshield              — untested
    #
    # --- giga_boss anim (large ground bosses) ---
    # 'c4241': 0.0,  # Giant Fingercreeper              — untested
    # 'c4510': 0.0,  # Ancient Dragon                   — untested
    # 'c4580': 0.0,  # Giant Wormface                   — untested
    # 'c4620': 0.0,  # Astel, Stars of Darkness         — untested
    # 'c4660': 0.0,  # Guardian Golem                   — untested
    # 'c7700': 0.0,  # Gaping Dragon                    — untested
    # 'c7710': 0.0,  # Centipede Demon                  — untested
    #
    # --- quadruped_large anim ---
    # 'c4730': 0.0,  # Starscourge Radahn               — untested
    # 'c4910': 0.0,  # Magma Wyrm                       — untested
    # 'c5230': 0.0,  # Scadutree Avatar                 — untested
    #
    # c4900 / c4901 Caligo are GIGA but humanoid-anim — humanoid origin,
    # expected to need no offset; intentionally not listed.
    #
    # --- JOSTLE TEST (v0.27.0) ----------------------------------------
    # The entries below are NOT a known height fix. They are an
    # experiment: per Alaric's read of how these enemies path in-game,
    # a freeze at a fragile slot may be the enemy spawned wedged into
    # geometry and stuck in a depenetration state its AI cannot exit.
    # A +1.0 Y bump is a JOSTLE — nudge it off the exact wedged spot so
    # the AI re-evaluates and finds nearby valid terrain. This is the
    # same mechanism as the backstab-reposition theory, applied at spawn.
    #
    # These are all V3_FRAGILE_SENSITIVE_TARGETS quadruped-anim chrs.
    # The offset does NOT change their fragility status (V3_MODEL_Y_OFFSET
    # is not consulted by is_fragile_slot) — they stay SENSITIVE-gated
    # while the jostle is evaluated. If a jostle is confirmed to work in
    # playtest, that chr can be removed from SENSITIVE manually (the
    # SENSITIVE-retest workflow), not automatically.
    # Starting value +1.0 for the whole block; tune per chr from playtest.
    'c3181': 1.0,    # Red Wolf of Radagon  — JOSTLE TEST
    'c4070': 1.0,    # Wolf                 — JOSTLE TEST
    'c4071': 1.0,    # White Wolf           — JOSTLE TEST
    'c4080': 1.0,    # Rat                  — JOSTLE TEST
    'c4090': 1.0,    # Giant Rat            — JOSTLE TEST
    'c4150': 1.0,    # Basilisk             — JOSTLE TEST
    'c4160': 1.0,    # Large Stray          — JOSTLE TEST
    'c4161': 1.0,    # Stray                — JOSTLE TEST
    'c4164': 1.0,    # Large Bloodbane Stray — JOSTLE TEST
    'c4165': 1.0,    # Bloodbane Stray      — JOSTLE TEST
    'c4166': 1.0,    # Large Rotten Stray   — JOSTLE TEST
    'c4240': 1.0,    # Fingercreeper        — JOSTLE TEST
    'c4280': 1.0,    # Giant Ant            — JOSTLE TEST
    'c4960': 1.0,    # Giant Skeleton Torso — JOSTLE TEST
    'c5522': 1.0,    # Stray                — JOSTLE TEST
    'c5523': 1.0,    # Stray                — JOSTLE TEST
    'c6060': 1.0,    # Goat                 — JOSTLE TEST
}


def lookup_model_y_offset(c_prefix):
    """v0.27.0: Returns the model Y-offset (world units, +up) for a
    c-prefix, or 0.0 if none is defined. Applied at MSB-write time on
    top of any V3_POSITION_SHIFTS slot shift. See V3_MODEL_Y_OFFSET."""
    if not c_prefix:
        return 0.0
    return V3_MODEL_Y_OFFSET.get(c_prefix, 0.0)


def lookup_position_shift(slot_msb_name, slot_pi):
    """v0.23.72-late: Returns the position-shift entry for a slot, or None
    if no shift is defined for it.

    Result shape (when non-None):
      {'dxyz': (dx, dy, dz), 'note': str, 'observed_in': str}

    Callers:
      - is_fragile_slot: if a slot has a shift, it is treated as non-fragile
        (the shift is the fix — fragility no longer restricts the pool).
      - shuffle_msb_v3: when actually writing the MSB Part, the dxyz offset
        gets applied to the position field at +0x400. Skipped if the slot
        ended up in a cluster (cluster_id != None) — cluster aesthetics
        take priority over shifting.
    """
    if slot_msb_name is None or slot_pi is None:
        return None
    return V3_POSITION_SHIFTS.get((slot_msb_name, slot_pi))


# v0.23.62 PER-SLOT C-PREFIX EXTRA BANS
# ------------------------------------
# Companion to V3_PROBLEM_SLOTS. The PROBLEM_SLOTS list restricts a slot's
# pool to V3_FRAGILE_SAFE_CONFIRMED — which works well for most slot
# fragility but assumes "if it's been tested safe at SOME fragile slot,
# it's safe at THIS fragile slot." That assumption breaks for slots whose
# fragility is a specific scripted-intro-animation requirement: only c-
# prefixes whose anim bank includes the right wake-up will respond
# correctly.
#
# Empirical case: m38_00_00_00 pi=51 (Cathedral interior, Guardian Golem
# source). v0.20.69 confirmed c4620 Astel froze here and added the slot
# to V3_PROBLEM_SLOTS. v0.23.62 confirms c5010/c5011 Hippo also freeze
# here, despite being in V3_FRAGILE_SAFE_CONFIRMED. Both Astel and Hippo
# are XXL/GIGA large_boss_ground family — the hypothesis is that
# the Guardian Golem wake-up EMEVD event triggers anim bank 46600 which
# only c4660 owns; large_boss_ground chrs without the right anim entry
# stay in standby pose forever.
#
# Other Hippo placements at non-Cathedral fragile slots (the Remembrance
# Limveld arena at m60_42_36_20 pi=43) work fine, so we don't want to
# remove c5010/c5011 from SAFE_CONFIRMED globally — that would over-
# restrict and rule out legitimate Hippo fights at Limveld field-boss
# arenas.
#
# Solution: per-slot extra ban map. For (msb_name, pi) keys here, the
# fragile-slot filter additionally subtracts the listed c-prefixes from
# the pool, on top of the SAFE-only restriction. Surgical and precise.
#
# Not mutually exclusive with V3_PROBLEM_SLOTS — slots in this map should
# also be in V3_PROBLEM_SLOTS to get the SAFE-only base filter; this map
# adds further restrictions on top.

V3_PROBLEM_SLOT_EXTRA_BANS = {
    ('m38_00_00_00.msb', 51): {
        'c5010',  # Golden Hippopotamus — large_boss_ground GIGA, freezes
                  #   at Cathedral interior pi=51 (v0.23.62 playtest).
                  #   Same size/family profile as c4620 Astel which
                  #   was the v0.20.69 case for adding this slot to
                  #   V3_PROBLEM_SLOTS originally.
        'c5011',  # Golden Hippopotamus (Golden Wings) — same family,
                  #   same size/family, defensive add. Not directly
                  #   observed frozen at this slot but high probability
                  #   given c5010 result. Cheap to ban.
    },
    # v0.24.77: Magic fort rampart (Guardian Golem source). Emerge-from-
    # ground intro chrs CTD here because the rampart roof has no
    # subsurface terrain to push from. Two confirmed cases:
    #   - c4441 Land Squirt (Boss) CTD on approach, v0.24.18 seed 70502
    #   - c4810 Erdtree Avatar (Remembrance) CTD on leaving Fort,
    #     v0.24.75 seed 886942
    # Both chrs share the "rise out of the earth" scripted intro.
    # Banning all known emerge-anim chrs at this slot, defensive add
    # for c4811 Erdtree Avatar Variant (same family as c4810).
    ('m30_30_00_00.msb', 45): {
        'c4810',  # Erdtree Avatar (Remembrance) — confirmed CTD in
                  #   seed 886942 v0.24.75. Rise-from-earth intro fails
                  #   on Fort rampart geometry (no ground to emerge
                  #   from). Player CTD on leaving Fort.
        'c4811',  # Erdtree Avatar Variant — same family as c4810,
                  #   same rise-from-earth intro. Not directly observed
                  #   frozen but defensive add (cheap to ban).
        'c4441',  # Land Squirt (Boss) — confirmed CTD on approach in
                  #   seed 70502 v0.24.18. Original case that put this
                  #   slot in V3_PROBLEM_SLOTS. Burrowing/emerge intro
                  #   fails identically to c4810.
    },
    # v0.23.65: skeleton family banned from Oracle Envoys Cathedral
    # pi=12. Playtest report (4laric, 2026-05): killed all 4 enemies in
    # the Cathedral encounter (Ancestor Spirit pi=11, c3061 Giant Beast
    # Skeleton pi=12, Lordsworn Captain pi=13, Albinauric Archer pi=14)
    # but the Site of Grace never spawned and the skeleton's reanimation
    # VFX kept playing on the corpse indefinitely.
    #
    # Hypothesis (UNVERIFIED — needs EMEVD inspection): the Cathedral
    # encounter-complete EMEVD polls "is entity at pi=12 in Dead state?"
    # Skeletons have a unique two-phase death: ragdoll → reassemble check
    # → if hit-during-reassembly, set permanent-dead flag. The vanilla
    # source at pi=12 was c3620 Oracle Envoy which has a clean one-shot
    # death state. Replacing it with a skeleton breaks the EMEVD's
    # state-poll because the skeleton AI's reassembly cycle leaves the
    # entity in an ambiguous state for several seconds, possibly forever
    # if the AI's permanent-dead flag never propagates back to the
    # engine's "is dead" predicate that the EMEVD checks.
    #
    # Symptoms support the hypothesis:
    #   - Reanimation VFX plays forever (skeleton AI's reassembly state
    #     never transitions to permanent-dead, leaving the
    #     reassembling SpEffect looping).
    #   - Site of Grace doesn't spawn (encounter-complete EMEVD never
    #     sees the entity as "dead enough" to fire the trigger).
    #
    # Narrow fix: ban skeletons from THIS slot only. Other Cathedral
    # slots (pi=11/13/14 in this MSB, all m38_10 slots) might or might
    # not have the same issue — too few data points to widen safely.
    # If user reports the same symptom at another slot, add it here.
    ('m38_00_00_00.msb', 12): {
        'c3060',  # Giant Skeleton
        'c3061',  # Giant Beast Skeleton — confirmed broken (v0.23.65 playtest)
        'c3500',  # Large Skeleton (Spear)
        'c3510',  # Skeleton (Sword and Shield)
        'c4960',  # Giant Skeleton Torso (also has reanimate-able torso state)
    },
    # v0.23.74: cathedral cluster pi=11-14 chr-fragility bans. After the
    # c3620 source-exclude was lifted (Phase 1 audit invalidated the
    # cluster-dance CTD hypothesis), seed 940574 playtest sent c4340
    # Mad Pumpkin Head, c4420 Giant Crayfish, c5090 Gravebird, and
    # c3970 Azula Beastman to pi=11/12/13/14 respectively. Three worked
    # fine in-game; c3970 froze at pi=14. All four chrs are in
    # V3_FRAGILE_SAFE_CONFIRMED and all four have locomotion=0 — the
    # differentiator appears to be size/family:
    #   c4340 humanoid XL — works (large footprint, different nav)
    #   c4420 aquatic XXL — works (aquatic anim class)
    #   c5090 quadruped L — works (quadruped nav)
    #   c3970 humanoid M  — FREEZES
    # Hypothesis: cathedral cluster slots have a scripted intro / spawn
    # pose that humanoid-M chrs with loco=0 can't transition out of. The
    # specific freeze mode (player can lock on but chr doesn't engage) is
    # consistent with stuck-in-spawn-anim rather than terrain-trap.
    # Banning c3970 specifically across all 4 cluster slots; if more
    # humanoid-M-loco=0 chrs report freezes here, add them or escalate
    # to a wider size+loco-based ban heuristic.
    ('m38_00_00_00.msb', 11): {
        'c3970',  # Azula Beastman — humanoid M loco=0 freezes here
    },
    ('m38_00_00_00.msb', 13): {
        'c3970',  # Azula Beastman — humanoid M loco=0 freezes here
    },
    ('m38_00_00_00.msb', 14): {
        'c3970',  # Azula Beastman — humanoid M loco=0 confirmed frozen
                  # at this slot in seed 940574 playtest (v0.23.74)
    },
    # Note: pi=12 already has its own EXTRA_BANS entry above for the
    # skeleton family. If c3970 also breaks pi=12 in future playtests,
    # add it to that entry's set rather than creating a duplicate key.
    # v0.24.60: SW-corner cluster c4120 ban. c4120 Demi-Human Chief is
    # in V3_FRAGILE_SAFE_CONFIRMED (bulk-added v0.20.48 via mt=3 rule)
    # so the slot's V3_PROBLEM_SLOTS fragility flag alone wouldn't
    # exclude it. User seed 923958 confirms c4120 froze at pi=20
    # POST-reposition (post-shift position [-100.62, 105.48, 88.15]).
    # Six entries cover all phase tiles. The same chr-freeze symptom is
    # the c4101 (Large Demi-Human, already SENSITIVE) pattern — Demi-
    # Human family seems to have anim/locomotion quirks that don't
    # survive at fragile slots. If we get more c4120 freezes at
    # different fragile slots, escalate by removing c4120 from
    # V3_FRAGILE_SAFE_CONFIRMED entirely (broader fix). For now, just
    # block at these confirmed slots.
    ('m60_42_36_00.msb', 19): {
        'c4120',  # Demi-Human Chief — frozen here in seed 923958
    },
    ('m60_42_36_00.msb', 20): {
        'c4120',  # Demi-Human Chief — frozen here in seed 923958
    },
    ('m60_42_36_10.msb', 19): {
        'c4120',  # Demi-Human Chief — phase sibling of _00 pi=19
    },
    ('m60_42_36_10.msb', 20): {
        'c4120',  # Demi-Human Chief — phase sibling of _00 pi=20
    },
    ('m60_42_36_20.msb', 19): {
        'c4120',  # Demi-Human Chief — phase sibling of _00 pi=19
    },
    ('m60_42_36_20.msb', 20): {
        'c4120',  # Demi-Human Chief — phase sibling of _00 pi=20
    },
}


# v0.24.75: per-slot EXTRA-ALLOWS list. Symmetric counterpart to
# V3_PROBLEM_SLOT_EXTRA_BANS. When (msb, pi) is in this dict, the
# c-prefixes listed bypass the V3_FRAGILE_SAFE_CONFIRMED filter at
# that slot — allowed to land even though they aren't in the
# generally-safe whitelist.
#
# Use case: a fragile slot is in V3_PROBLEM_SLOTS for a specific
# known-broken chr (e.g. c4620 Astel froze at the Cathedral Guardian
# Golem source), but the SAFE-only restriction is over-conservative
# and excludes chrs that empirically work at that slot. EXTRA_ALLOWS
# whitelists those specific chrs back in without globally expanding
# V3_FRAGILE_SAFE_CONFIRMED (which would affect every fragile slot).
#
# Filter order at fragile slots (post-v0.24.75):
#   1. V3_FRAGILE_SENSITIVE_TARGETS: hard reject (no override possible)
#   2. EXTRA_ALLOWS check: if target_cp is in the slot's allow list,
#      skip the SAFE_CONFIRMED check
#   3. else: SAFE_CONFIRMED OR V3_RESILIENT_BIPEDS required
#   4. EXTRA_BANS check: per-slot post-filter ban (applies regardless
#      of EXTRA_ALLOWS, so it can fence off the broken-at-this-slot
#      specific c-prefixes)
#
# Not mutually exclusive with V3_PROBLEM_SLOTS — slots in this dict
# should also be in V3_PROBLEM_SLOTS to remain in the fragile path
# (otherwise the EXTRA_ALLOWS check is unreachable).
V3_PROBLEM_SLOT_EXTRA_ALLOWS = {
    # v0.24.75: Cathedral interior upper floor (Guardian Golem source).
    # Slot stayed in V3_PROBLEM_SLOTS after v0.20.69 c4620 Astel freeze,
    # which locked the pool to SAFE_CONFIRMED only. EXTRA_ALLOWS lets
    # specific c-prefixes bypass that restriction at this slot.
    #
    # With v0.24.75's removal of rig-compat restrictions globally
    # (xxl_giga_anim_drift dropped, V3_FORBIDDEN_BY_SOURCE_ANIM emptied,
    # base swap_compat._compat_rig neutered), the big-dragon
    # family becomes geometrically eligible at this slot. EXTRA_ALLOWS
    # below gets them past the remaining SAFE_CONFIRMED restriction.
    #
    # Note: c4510 Ancient Dragon and c4580 Giant Wormface are NOT
    # in this list — they're blocked by Gate 1 (nb_strict), which is
    # NB-tier-based not family-based, and remains in effect.
    ('m38_00_00_00.msb', 51): {
        'c4910',  # Magma Wyrm — grounded big dragon (quadruped_large GIGA)
        'c4911',  # Great Wyrm Theodorix (flying_dragon GIGA)
        'c4540',  # Lichdragon (flying_dragon GIGA, heritage)
        'c4541',  # Lichdragon Fortissax variant (MMV)
        'c4520',  # Dragon (flying_dragon GIGA, heritage)
        'c5860',  # Ghostflame Dragon (flying_dragon, heritage)
        'c4241',  # Giant Fingercreeper (giga_boss GIGA — already
                  #   compatible upstream, EXTRA_ALLOWS gives SAFE bypass)
        'c7700',  # Gaping Dragon (DS1 import, script_spawn giga_boss)
        'c7710',  # Centipede Demon (DS1 import, script_spawn giga_boss
                  #   — user-confirmed working at Fort GG slot)
        # c4660 Guardian Golem itself stays implicitly allowed via the
        # primary-identity preserve path — doesn't need to be here.
    },

    # v0.24.77: Magic fort rampart (Guardian Golem source). Restored to
    # V3_PROBLEM_SLOTS after Erdtree Avatar CTD (see V3_PROBLEM_SLOTS
    # comment). EXTRA_ALLOWS preserves the "big creatures at Fort"
    # variety the user got from the v0.24.75 lift. Same set as
    # Cathedral pi=51 except for the emerge-anim entries which are
    # confirmed-broken at this slot (see EXTRA_BANS below).
    ('m30_30_00_00.msb', 45): {
        'c4910',  # Magma Wyrm — grounded big dragon (quadruped_large GIGA)
        'c4911',  # Great Wyrm Theodorix (flying_dragon GIGA)
        'c4540',  # Lichdragon (flying_dragon GIGA, heritage)
        'c4541',  # Lichdragon Fortissax variant (MMV)
        'c4520',  # Dragon (flying_dragon GIGA, heritage)
        'c5860',  # Ghostflame Dragon (flying_dragon, heritage)
        'c4241',  # Giant Fingercreeper (giga_boss GIGA)
        'c7700',  # Gaping Dragon (DS1 import, script_spawn giga_boss)
        'c7710',  # Centipede Demon — user-confirmed working at this slot
                  #   ("we've had Centipede Demon there successfully")
    },
}


# v0.20.34: per-slot SENSITIVE-only treatment. Sibling to V3_PROBLEM_SLOTS
# but a softer mechanism. When a slot is in this set, the engine subtracts
# V3_FRAGILE_SENSITIVE_TARGETS from the target pool but does NOT restrict
# to V3_RESILIENT_BIPEDS — the slot keeps its normal tier-strength pool.
#
# Use case: boss-tier slots that should still get a real boss-class
# replacement (so Field Boss → some other field boss, not a soldier
# downgrade) but a few specific boss-tier targets are known to break
# at this slot's geometry. The Miranda Blossom dungeon slot is the
# motivating example — its sessile-plant arena fails for combat-arena
# XXL bosses like Dancing Lion, but a normal arena boss (Hippo, Tree
# Sentinel, Wormface) lands fine.
#
# Slots should NOT be in both V3_PROBLEM_SLOTS and V3_SENSITIVE_ONLY_SLOTS.
# Full fragile (V3_PROBLEM_SLOTS) supersedes — its RESILIENT restriction
# already excludes everything in V3_FRAGILE_SENSITIVE_TARGETS.
V3_SENSITIVE_ONLY_SLOTS = {
    # (msb_name, part_index): 'reason for documentation'
    ('m46_71_00_00.msb', 1): 'Miranda Blossom (Field Boss) sessile arena — '
                              'XXL combat-arena bosses freeze (Dancing Lion '
                              'confirmed). Other boss-tier targets fine.',
}


# v0.20.21: per-slot tier promotion. Force the target pool at a specific
# (msb, pi) to a higher tier than the source variant's auto-tagged tier
# would normally select. Used for vanilla "encounter-anchor" slots where
# the source variant is auto-tagged is_boss=False (e.g. variant name
# doesn't carry a Boss/Field Boss/Encampment marker) but vanilla NR
# clearly designs the slot as a notable encounter — randomizing it to a
# grunt feels deflating.
#
# v0.20.22: extended to a (msb, pi) → mode dict. Modes:
#   'bossy'        Force recipient_is_boss=True. Target pool restricts
#                  to V3_BOSS_STRENGTH_TIERS (night_boss/field_boss/
#                  miniboss/nightlord). Picks the boss variant when
#                  available. Use when the slot's source tier was wrong
#                  (e.g. fort Guardian Golem auto-tagged as field but
#                  the (Fort) qualifier should have made it boss).
#   'boss_reward'  Like 'bossy' BUT additionally requires the chosen
#                  c-prefix to have has_boss_reward=True. This filters
#                  out miniboss-tier humanoids (Highwayman, Bloodhound
#                  Knight, etc.) that have boss-variants but don't fire
#                  the boss-arena event chain. Use when the vanilla slot
#                  IS a boss-arena encounter (fog wall + healthbar)
#                  that needs a real arena-class boss to function.
#
# Mechanism: when slot is matched, recipient_is_boss is overridden to
# True for tier filtering AND the source variant for variant-picking is
# treated as boss-tier so the chosen variant is the (Boss) form when
# available. In 'boss_reward' mode, the additional has_boss_reward
# filter is applied to the pool inside pick_target_cp.
#
# Distinct from V3_PROBLEM_SLOTS (T3 fragile-restrict, narrows to
# V3_RESILIENT_BIPEDS) — promote-slots widens to bosses, not narrows to
# resilient. Both sets can technically overlap a slot but currently don't.
V3_BOSSY_PROMOTE_SLOTS = {
    # (msb, pi): 'mode'    — see above for mode semantics
    # v0.20.21: m30_30 fort GG slot. Vanilla source is Guardian Golem
    # (Fort), is_boss=False (the (Fort) qualifier doesn't auto-tag as
    # boss). Playtest with seed 42 swapped this to a Highwayman grunt
    # — coherent per the engine's tier rules but wrong vibe for the
    # fort's centerpiece encounter.
    # v0.20.22: upgraded from 'bossy' to 'boss_reward'. The fort GG
    # IS the fort's boss encounter (the fort is built around it),
    # so requiring has_boss_reward=True keeps Highwayman-class minibosses
    # out and lands a real arena boss instead.
    ('m30_30_00_00.msb', 45): 'boss_reward',
    # v0.20.22: m32_20 Madness Encampment Frenzied Flame Troll. Vanilla
    # source is c4600 (Frenzied Flame Troll, Encampment), is_boss=True.
    # Engine tier-preserves it as boss-class but in seed 42 it got
    # c4377 Highwayman (Scholar Remembrance) — Highwayman is auto-tagged
    # miniboss because its (Scholar Remembrance) variant carries the
    # Remembrance boss marker, but Highwayman has_boss_reward=False
    # (no real boss arena). Result: ghost/spirit summon visible but
    # no boss healthbar, no fog wall, encounter doesn't fire. Same
    # treatment as the fort GG slot.
    ('m32_20_00_00.msb', 63): 'boss_reward',
}


def _is_edge_sentinel_pos(pos):
    """v0.20.16: NR script-spawn-placeholder edge-sentinel position detector.

    Some MSBs (notably overworld m60_xx) author script-spawn placeholders at
    (any_x, ~0, ~1). Unlike the v0.20.15 shared-position cluster pattern,
    each placeholder has a UNIQUE x — so the cluster check (threshold 3 at
    same rounded position) lets them through as singletons. 264 such slots
    in m60_xx alone in a typical run; original c-prefixes are dominated
    by filler types (c3000 Misbegotten ~50%, c3010/c3020 soldiers, c4300
    Wandering Noble) which is the placeholder-authoring fingerprint.

    Unlike the v0.20.11/.12/.15 placeholder classes (which produce no
    visible enemy and get skipped), these slots DO render a visible
    enemy in-game. They just need a target that activates without the
    spawn-script's help. So we treat them as fragile (target restricted
    to V3_RESILIENT_BIPEDS) rather than skipping. Frozen-prone targets
    (c4181 Jellyfish, c5110 Tendril, c3610 Envoy, c4201 Op Bat — all
    Maris-cluster-adjacent) at these slots are the user-reported
    "frozen guys on the slope" symptom.

    Tolerance: |y|<2 absorbs y=-0.04 / y=0.0 / y=0.3 jitter; |z-1|<1
    absorbs z=1.0 ± snap. Tighten if false positives surface."""
    return (pos is not None
            and abs(pos[1]) < 2
            and abs(pos[2] - 1) < 1)


def is_fragile_slot(slot_msb_name, slot_pi, slot_variant_name, slot_pos=None,
                     ignore_position_shifts=False):
    """v0.19.2: Returns True if the given slot is fragile (needs target
    restriction to V3_RESILIENT_BIPEDS). Three-tier detection:
      T3 manual blocklist > T2 fragile maps > T1 variant qualifiers.
    Any tier match returns True; misses on all three return False.

    v0.22: T2.8 per-slot roughness override. Slots that are coarse-fragile
    via T1 / T2 / T2.7 may be released back to the unrestricted pool if
    their AABB-derived terrain signal looks benign (flat horizontal
    polygon under the slot). T2.8 explicitly does NOT override T3
    (V3_PROBLEM_SLOTS) or T2.5 (edge-sentinel) — those are hand-curated
    or coordinate-pattern signals that bypass terrain analysis.

    v0.23.72-late: T0 position-shift override. Slots in V3_POSITION_SHIFTS
    are treated as non-fragile — the shift IS the fix, so pool-narrowing
    isn't needed. Caller can opt out via ignore_position_shifts=True for
    diagnostic queries that want the "would be fragile without the shift"
    answer (used by the shift-application path itself to confirm the
    slot was a real fragility candidate).

    Caller passes:
      slot_msb_name: e.g., 'm60_43_37_20.msb' (basename only)
      slot_pi: integer Part index within the MSB
      slot_variant_name: source variant's variant_name (e.g., 'Wolf' or
                         'Guardian Golem (Cathedral)'). Empty string if unknown.
    """
    # T0: position-shift override. Highest precedence; checked first so any
    # slot with a curated shift entry skips all fragility tiers below.
    # When ignore_position_shifts=True, fall through to normal tier checks.
    if not ignore_position_shifts and lookup_position_shift(slot_msb_name, slot_pi):
        return False
    # T3: manual blocklist (most specific, checked first). NEVER overridden by T2.8.
    if (slot_msb_name, slot_pi) in V3_PROBLEM_SLOTS:
        return True
    # T2.5 (v0.20.16): edge-sentinel position pattern (?, ~0, ~1).
    # Script-spawn-placeholder slots that produce visible enemies but
    # can't activate frozen-prone targets via the spawn script. See
    # _is_edge_sentinel_pos docstring for details. NEVER overridden by T2.8 —
    # this is a coordinate-pattern signal independent of terrain.
    if _is_edge_sentinel_pos(slot_pos):
        return True
    # T2: whole-map fragile — exact name OR prefix match (v0.20.14).
    # T2.8 (v0.22) may release if per-slot navmesh signal is benign.
    if slot_msb_name in V3_FRAGILE_MAPS:
        if _is_t2_8_releasable(slot_msb_name, slot_pi):
            return False
        return True
    if any(slot_msb_name.startswith(p) for p in V3_FRAGILE_MAP_PREFIXES):
        if _is_t2_8_releasable(slot_msb_name, slot_pi):
            return False
        return True
    # T2.6 (v0.20.47, RETIRED in v0.20.64): per-slot off-mesh navmesh
    # fragility. The original idea was to treat off-mesh slots as fully
    # fragile (restrict to SAFE_CONFIRMED), but in practice the slot_terrain
    # navmesh-extraction tagging produced too many false positives — entire
    # cathedrals showing up as off-mesh because the extractor missed the
    # floor mesh. The override list grew unwieldy. New approach (v0.20.64):
    # off-mesh slots are NOT classified as fragile, but pick_target_cp does
    # an additional pass to exclude SENSITIVE c-prefixes from off-mesh slot
    # pools — that's a softer restriction that catches the actual CTD risk
    # (sensitive c-prefixes breaking at no-navmesh slots) without the
    # over-restriction symptom (jellies/imps everywhere). The
    # _load_off_mesh_slots() data is still used by pick_target_cp; this
    # T2.6 line just no longer routes to fragile.
    # T1: variant qualifier
    # v0.20.17: also match the '(Q- ...)' hyphen-suffix form. NR uses both
    # '(Encampment)' and '(Encampment- by tower)' / '(Encampment- middle)'
    # to label slots in the same encampment, plus similar (Mountaintop-,
    # Ruins-, Noklateo-) forms elsewhere. The original substring check
    # f'({q})' missed all hyphen-suffix variants — 16 slots in this run's
    # spoiler — leaking non-resilient targets into encampment surroundings
    # (Banished/Leyndell/Redmane Knights, Snowfield Trolls, Mausoleum
    # Knights). Both forms now fire.
    # T2.8 (v0.22) may release if per-slot navmesh signal is benign.
    if slot_variant_name:
        for q in V3_FRAGILE_SOURCE_QUALIFIERS:
            if f'({q})' in slot_variant_name or f'({q}-' in slot_variant_name:
                if _is_t2_8_releasable(slot_msb_name, slot_pi):
                    return False
                return True
    # T2.7 (v0.20.71): POI proximity fragility. Slots within
    # V3_T1_PROXIMITY_RADIUS of a T1-qualifier-tagged source slot
    # (Cathedral / Crater / Encampment / etc.) inherit the same
    # boss-arena geometry constraints. Originally added in response to
    # user CTD report near a Demi-Human Queen (Crater) — surrounding
    # mob slots had generic source names ('Slug', 'Guilty', 'Wolf') so
    # T1 didn't fire for them, but they share the rocky/sloped Crater
    # terrain that breaks pathing for SENSITIVE c-prefixes. Anchor
    # positions are loaded from t1_anchors.json (extracted from
    # spoiler — anchors are vanilla source positions, stable across
    # seeds). See _load_t1_anchors() docstring for details.
    # T2.8 (v0.22) may release if per-slot navmesh signal is benign.
    if _is_t1_proximity_fragile(slot_msb_name, slot_pos):
        if _is_t2_8_releasable(slot_msb_name, slot_pi):
            return False
        return True
    return False


# Aerial-source alternatives (v0.10). When a SOURCE c-prefix's vanilla
# placement is at an elevated position (y >= threshold), restrict the swap
# target chosen_pool to a curated whitelist of c-prefixes that are
# vanilla-validated to handle high-y placements (cling to walls, float,
# climb cliffs, etc).
#
# This SUPERSEDES the previous V3_AERIAL_SOURCE_SKIP for bats. Where
# V3_AERIAL_SOURCE_SKIP would skip the swap entirely (kept the bat
# vanilla), this mechanism allows a VARIETY of aerial-capable enemies
# to fill those positions instead.
#
# Whitelist composition was empirically validated by checking each
# candidate's vanilla y-distribution:
#
#   c4180 Spirit Jellyfish:        12/32 vanilla at y>=30 (floats)
#   c4280 Giant Ant:               37/48 vanilla at y>=30 (climbs cliffs)
#   c4170 Putrid Flesh:            27/41 vanilla at y>=30 (clings to walls)
#   c4440 Land Squirt:             27/27 vanilla at y>=30 (clings everywhere)
#   c4040 Slug:                    18/47 vanilla at y>=30 (climbs)
#   c2041 Kindred of Rot Larva:    22/25 vanilla at y>=30 (on walls)
#   c4200 Man-Bat:                 61/115 vanilla at y>=30 (own family)
#   c4201 Operatic Bat:             6/13 vanilla at y>=30 (own family)
#
# All are FromSoft-designed for aerial/wall placements; they handle
# bat-perch positions without freezing. Spider Scorpion (c5190/c5192/
# c5193) is included experimentally — has no vanilla data to validate
# but matches the user wishlist; will be removed if reports indicate
# freezes.
#
# If the recipient slot's chosen_pool intersects the alternatives at all
# (after compat, size, etc.), pick from the intersection. If
# it's empty (e.g. no aerial-capable enemy passes the strict pool
# filters), fall back to skipping the swap (keep vanilla bat) — same
# semantics as the old V3_AERIAL_SOURCE_SKIP.
V3_AERIAL_SOURCE_ALT = {}  # v0.20.0: emptied — bats use universal pool

# Force-include set — c-prefixes that are added to EVERY recipient's
# compatible_pool regardless of anim_bank/size/loco match. Used for
# untagged cluster-only entities that the user wants to see standalone
# (Maris' Tendril, Maris' Jellyfish, Oracle Envoy, Oracle Envoy Large).
#
# Historical context (pre-v0.20.0): the pool builder used to be
# build_compat_lookups → bank_to_prefixes / loose_to_prefixes lookups,
# and untagged prefixes would never appear in either dict. This set
# force-included them so they could still be picked.
#
# v0.20.0+: universal pool — compatible_pool() returns ALL c-prefixes
# v0.20.0: V3_FORCE_INCLUDE_UNTAGGED_TARGETS and V3_FORCE_INCLUDE_NARROW_THRESHOLD
# retired. The force-include mechanism widened narrow source pools by adding
# untagged candidates; the universal pool from tags (no anim_bank/size/loco
# filter) obsoleted it. Historical thresholds: ∞ (v0.10), 8 (v0.11),
# 16 (v0.19.14), 60 (v0.19.18). Note from history: "small-size at-risk
# weighting starves Maris out of those tiny pools" — the small-size at-risk
# weighting itself is also retired (see V3_OFF_MESH_PREFERRED_TARGETS removal).
# v0.24.86-patch7: removed; no remaining code references.


# v0.19.24: trace buffer — captures diagnostic firing decisions as a list
# v0.19.24: trace buffer for diagnostic events. Each entry is a dict
# with at least 'event': <event_name>. Other keys vary by event type.
# Examples preserved as permanent regression guards: TAGS_INTEGRITY,
# EXCLUDE_INTEGRITY, EXCLUDE_SNAPSHOT_AT_RUN_START, TAG_OVERRIDES_APPLIED.
# The v0.20.1–v0.20.4 FI scaffolding (FI_RETURNED_COUNTS, FI_STAGE_TRACKER,
# FI_DROP_FIRST_OBSERVED) was retired in v0.23.72-late after the
# investigations that motivated it stabilized — see TODO.md "Diagnostic
# event trim pass" for the resolution notes.
_V3_TRACE_BUFFER = []

# v0.20.12 → v0.23.72: spawn-marker auto-skip BREAKDOWN counter REMOVED.
#
# Historical: between v0.20.11 and v0.23.72, the engine had three
# script-spawn-placeholder skip filters (near_origin, none_pos,
# position_cluster) that left such slots vanilla. _V3_SPAWN_MARKER_SKIP_
# BREAKDOWN tracked which class fired per run.
#
# v0.23.72 ripped the filters out (they were eating legitimate boss
# slots — see "AERIAL-SKIP / SPAWN-MARKER FILTERS REMOVED" comment in
# shuffle_msb_v3 around line ~9035). The counter survived for a cycle
# zeroed but never incremented, then was removed in v0.23.72-late.
#
# The remaining placeholder-aware code (placeholder_pos_counts /
# placeholder_positions / V3_PLACEHOLDER_POSITION_THRESHOLD /
# V3_OOPS_ALL_NB_PLACEHOLDER_CAP) is unrelated to the removed
# counter: it caps how many OOPS_ALL_NB intercepts can fire at one
# placeholder-block position to prevent N-stacks of XL chrs CTDing on
# cell load. It doesn't skip slots, just rate-limits stamping.

# v0.20.18: preserved-source log. Captures slots whose source c-prefix is
# in V3_EXCLUDE_SOURCE_PREFIXES (so the slot stays vanilla and gets no
# entry in the main swap log) AND whose c-prefix is in V3_TRACKED_C_PREFIXES.
# Used to render an "unrandomized X" subsection in the spoiler, so the user
# can see where Oracle Envoys (c3610, c3620) and other source-excluded
# tracked enemies are still standing in their seed. List of dicts:
# {map, part_index, c_prefix, npc_param_id, name, position}.
_V3_PRESERVED_SOURCE_LOG = []

# v0.20.19: unaccounted-vanilla log. Captures slots that fell through the
# main swap loop without producing a swap entry AND weren't deliberately
# left vanilla (excludes / heuristic skips / cluster-vanilla-by-config).
# An empty section in the spoiler is the success state — confirmation
# that every Part the engine saw was either swapped or had a documented
# reason to stay vanilla. A non-empty section is a leak: probable bug.
#
# Reasons captured:
#   no_variants            cur_cp not in prefix_variants — model has
#                          no event-trigger-filtered variants. Suspicious;
#                          c-prefix probably needs an entry in
#                          nr_enemy_tags.json + variants in nr_enemy_roster.json
#                          (with `_source: 'script_spawn'` if it has 0 MSB
#                          Parts), or the variant filter is over-aggressive.
#                          v0.20.20: only fires for Enemy-class Parts
#                          (c-prefix beginning cN); AEG/h asset & collision
#                          Parts are skipped silently to avoid swamping
#                          the section.
#   script_spawn_target_only_at_msb
#                          A c-prefix marked target-only (script_spawn)
#                          showed up as an MSB Part. Common at heritage
#                          arena maps for Ancestor Spirit / Nameless
#                          King / Grafted Scion — these stay vanilla
#                          and that's correct architecture, not a bug.
#                          Kept logged so unexpected ones still surface.
#   cluster_pick_failed    Cluster has members but cluster_target_cp
#                          resolved to None. pick_target_cp couldn't
#                          find a cluster-compatible target.
#   no_target_found        Main path: pick_target returned None.
#                          Pool empty after all filters.
#   variant_for_tier_none  Niche modes (terrain test / oops-all): the
#                          tier+target c-prefix pair has no usable
#                          variant. Catalog gap.
#
# Each entry is a dict {map, part_index, c_prefix, npc_param_id,
#                       entity_id, position, reason}.
_V3_UNACCOUNTED_VANILLA_LOG = []

# v0.20.0/0.20.1: Strength-tier buckets for tier-preserve.
# v0.20.2: cluster_member kept as a recognized field-strength tag for
# backward compatibility with stale nr_enemy_tags.json files. v0.20.0
# retired the cluster_member tier (Maris Tendril/Jellyfish/Oracle Envoy/
# Miranda Sprout reclassified to grunt; large Oracle Envoy → miniboss),
# but if a user updates oops_v3.py without copying the new
# nr_enemy_tags.json, those cps still have tier='cluster_member' and
# would fall outside both buckets — filtered to nothing during tier-
# preserve. Treating cluster_member as field-strength means legacy data
# still admits them to grunt-source pools, just like the new tagging.
V3_BOSS_STRENGTH_TIERS = {'night_boss', 'field_boss', 'miniboss', 'nightlord'}
# v0.20.29: mount_component (Kaiden's Horse, Funeral Steed, etc.) and
# non_combat (merchants, scarabs, training posts) are field-strength
# slots conceptually but were previously NOT in either strength set —
# meaning the per-slot tier filter at line ~2129 fell through to the
# unfiltered branch and let boss-tier targets land at horse/merchant
# slots. Bisection on the v0.20.27 Limveld CTD localized the failure
# to m60_44_36_20.msb pi=29: c4060 horse slot → c4810 Erdtree Avatar
# (Remembrance) at pos (109.47, 79.53, 1.32). Across the seed-42
# spoiler, 40 weird-tier-source slots got boss-tier targets — pi=29 is
# only one of many. Adding both tiers here closes the gap.
V3_FIELD_STRENGTH_TIERS = {'grunt', 'trash', 'cluster_member',
                            'mount_component', 'non_combat'}

# v0.27.13 FIELD-SLOT TIER ROLL
# ------------------------------
# A non-catalogued slot — no (msb, pi) entry in V3_BOSS_SLOT_CATALOG,
# i.e. catalog_tier=None in the spoiler — is the generic field-grunt
# population (~3400 of ~3760 placements/seed). Pre-v0.27.13 the picker
# tier-preserved off the *vanilla occupant's* tag tier, so a field
# position whose vanilla enemy happened to be a beefy-but-not-boss chr
# tagged 'miniboss' (Fingercreeper Large, Land Octopus, ...) opened the
# full boss-strength pool — the leak that put c6200 Slave Knight Gael
# P2 (NB2) and c5130 Messmer (NB2) onto open-field slots and CTD'd on
# hawk-traversal tile streaming.
#
# Now: a non-catalogued slot ignores its occupant's tier and rolls
# grunt-base, with a small configurable chance to upgrade. One uniform
# draw per slot, seeded off (run seed, msb, pi) so it is reproducible
# and processing-order-independent. x + y must be <= 1.0. Realized
# upgrade counts run BELOW these probabilities — the fallback ladder in
# pick_target_cp degrades a roll back toward grunt when the rolled tier
# has no compat-fitting candidate.
#
# ~3400 field slots, so expected upgrades ~= pct * 3400. Defaults are
# deliberately low: 1.5% miniboss (~50/seed), 0.5% field_boss (~17/seed),
# 0.2% night_boss (~7/seed, on top of the 23 dedicated NB-arena slots).
# Tune by direct module edit — same workflow as the OOPS_ALL_NB_* knobs.
#
# v0.28.x: FIELD_BOSS tier separation. The night_boss tier was historically
# overloaded — it carried both true arena-class bosses (Margit, Maliketh,
# Malenia, Bayle, Rellana, Godfrey, Mohg, etc.) AND overworld boss-fight
# encounters (Tree Sentinel, Tibia Mariner, Magma Wyrm, Borealis, Death
# Bird, Ulcerated Tree Spirit, Hippopotamus Golden Wings, Putrescent Knight,
# Furnace Golem, etc.). The split moves ~24 of those overworld encounters
# to field_boss tier, separating the "scary thing you find walking around"
# from the "Day 3 climactic arena fight." The field roll gains a dedicated
# field_boss% so those chrs surface at field slots at a tunable rate, and a
# secondary FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT lets a field_boss roll
# upgrade to night_boss with a configurable chance — the "rare moment when
# a field encounter turns out to be a real fight" knob. Setting that to
# 0.0 keeps the two tiers entirely independent; raising it gradually blurs
# the line.
#
# Probability model (all 4 constants, summed):
#   miniboss_pct + fieldboss_pct + nightboss_pct must be <= 1.0
#   fieldboss_to_nightboss_promote_pct must be in [0.0, 1.0]
#
#   P(grunt)       = 1 - miniboss_pct - fieldboss_pct - nightboss_pct
#   P(miniboss)    = miniboss_pct
#   P(field_boss)  = fieldboss_pct * (1 - fieldboss_to_nightboss_promote_pct)
#   P(night_boss)  = nightboss_pct
#                  + fieldboss_pct * fieldboss_to_nightboss_promote_pct
#
# Default totals: P(grunt)≈97.8%, P(miniboss)=1.5%, P(field_boss)≈0.5%,
# P(night_boss)≈0.2% (promote=0.0 by default → independence).
#
# Excludes still apply: pick_target_cp subtracts V3_EXCLUDE_TARGET_
# PREFIXES from the pool BEFORE this tier filter, so dropping a chr
# (e.g. c6200 while its MMV import is incomplete) into that set keeps
# it out of every roll outcome — no separate field-pool plumbing needed.
V3_FIELD_UPGRADE_MINIBOSS_PCT = 0.015
V3_FIELD_UPGRADE_FIELDBOSS_PCT = 0.005   # v0.28.x: field_boss tier dedicated roll
V3_FIELD_UPGRADE_NIGHTBOSS_PCT = 0.002

# v0.28.x: when a field_boss tier is rolled (by the FIELDBOSS_PCT slice),
# this is the conditional chance it promotes upward to night_boss tier.
# Set to 0.0 to keep field_boss and night_boss tiers fully independent —
# a field_boss roll always picks from the field_boss-tier pool. Setting
# to 1.0 collapses field_boss back into night_boss (every field_boss
# roll becomes a night_boss roll); intermediate values blur the line
# in proportion. Use cases: 0.05–0.20 for "occasional scary encounter,"
# 0.5+ for "field bosses feel as menacing as night bosses." Tuned by
# direct module edit; reproducible per (seed, msb, pi) via the existing
# _field_slot_roll digest.
#
# v0.28.x+ (Alaric, post-tier-audit + NB-slot fixes): set to 0.5 — the
# centerpoint where field-tier encounters split roughly evenly between
# field_boss flavor (Tree Sentinels, Avatars, Wyrms, Hippo P2) and
# night_boss flavor (Margit, Morgott, Malenia, Metyr, etc.) appearing
# in the open world. Sim at promote=0.5 over 4878 non-cat slots × 20
# seeds: NB rolls ≈ 23/seed, FB rolls ≈ 11/seed. NB pool cap budget
# (~50-60 across all NB chrs × their caps) absorbs this comfortably —
# the layer-2 "NB roll → NB placement" rate stays at 96.2%, so caps
# are not a bottleneck even at the new rate. See
# dev/sim_fb_to_nb_promote_sweep.py for the full sweep data.
V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = 0.5

# v0.27.35: per-slot field-tier PINS. A non-catalogued field slot listed
# here skips the random field roll and is assigned the pinned effective
# tier deterministically (every seed, every roll). Use for known slot
# GROUPS that need a fixed tier the random roll can't reliably deliver and
# that shouldn't be promoted into the boss catalog (which would route them
# through the boss pool / NB-arena promotion).
#
# Seed motivation — the m49_43 castle Crucible Knight room:
#   m49_43 is a castle-interior room of 10 c2500 Crucible Knight (Castle)
#   Parts (a Roundtable-style mob room, NOT a single set-piece boss). It is
#   not in V3_BOSS_SLOT_CATALOG, so its slots take the field roll, which
#   returns 'grunt' ~98.3% of the time. But c2500 is tagged
#   tier='night_boss' + has_reward=True, so the field roll sets
#   src_tier='grunt' and then the has_reward preservation gate restricts the
#   target pool to grunt-tier chrs that ALSO have has_reward — of which
#   there are effectively zero (only c5240, itself unusable here). The pool
#   empties and pick_target_cp returns None for all 10 slots, so the whole
#   MSB ships ZERO_CHANGE_PASSTHROUGH (observed seed 435226 v0.27.33: all 10
#   castle Crucibles vanilla). Pinning these slots to 'miniboss' routes them
#   to the miniboss pool, which has 73 has_reward-bearing eligible targets,
#   so the gate is satisfied and the room randomizes into tougher-than-grunt
#   mobs (Alaric direction — middle ground, not 10 boss-caliber enemies).
#   The miniboss tier-ladder ('miniboss','grunt') still degrades to grunt if
#   a miniboss candidate can't be found, so the slot never re-strands.
V3_FIELD_SLOT_TIER_PIN = {
    ('m49_43_00_00.msb', pi): 'miniboss' for pi in range(10)
}

# Set at shuffle start (see cmd_shuffle_v3_impl). Module global rather
# than a threaded param to keep pick_target_cp's signature stable; the
# field roll is a pure function of (seed, msb, pi).
_V3_RUN_SEED = 0

def _field_slot_roll(slot_msb_name, slot_pi):
    """Uniform [0,1) roll for a field slot, stable per (run seed, msb, pi).

    Uses a SHA-1 digest of the slot identity rather than the builtin
    hash() — builtin string hashing is per-process salted (PYTHONHASHSEED)
    and would not reproduce across runs. Uses a dedicated Random rather
    than the shared shuffle rng stream, so adding/removing slots
    elsewhere never shifts an unrelated slot's roll."""
    import hashlib
    key = f"{_V3_RUN_SEED}|{slot_msb_name}|{slot_pi}".encode()
    h = int.from_bytes(hashlib.sha1(key).digest()[:8], 'big')
    return random.Random(h).random()

def _slot_decision_rng(slot_msb_name, slot_pi):
    """Per-slot Random for the target-cp decision, stable per (run seed,
    msb, pi) and independent of the shared shuffle stream — same rationale
    and SHA-1 keying as _field_slot_roll, with a distinct 'decision'
    namespace so it never collides with the field-tier roll for the same
    slot. Making the cp pick a pure function of slot identity is what
    removes the input-ordering dependence (a contaminated/reordered base
    no longer cascades into a different world) and lets
    simulate_engine.py reproduce the cp decision exactly."""
    import hashlib
    key = f"{_V3_RUN_SEED}|decision|{slot_msb_name}|{slot_pi}".encode()
    h = int.from_bytes(hashlib.sha1(key).digest()[:8], 'big')
    return random.Random(h)

def _big_proximity_priority(slot_msb_name, slot_pi):
    """Order-independent priority key for the big-proximity tie-break
    (V3_BIG_PROXIMITY_HASH_TIEBREAK). Higher wins. Pure function of
    (run seed, msb, pi) with a distinct 'big_proximity' SHA-1 namespace
    so it never collides with the target-cp decision roll for the same
    slot — same keying rationale as _slot_decision_rng. Returns an int
    that resolve_big_proximity_priority sorts on."""
    import hashlib
    key = f"{_V3_RUN_SEED}|big_proximity|{slot_msb_name}|{slot_pi}".encode()
    return int.from_bytes(hashlib.sha1(key).digest()[:8], 'big')

def field_roll_tier_for(slot_msb_name, slot_pi):
    """Rolled effective tier for a non-catalogued field slot.

    Returns one of 'grunt' | 'miniboss' | 'field_boss' | 'night_boss', or
    None if the slot IS catalogued (a boss/terrain/POI slot — left to its
    own catalog handling). Shared by pick_target_cp and the spoiler
    writer so both agree on the outcome.

    v0.28.x: 4-tier ladder. The roll first slices into
    {grunt, miniboss, field_boss, night_boss} using the three PCT
    constants. If the field_boss slice is hit, a second roll consults
    V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT — if it passes, the result
    upgrades to night_boss (the "field encounter turns out to be a real
    fight" knob). The promote draw is keyed off a distinct namespace so
    adding/removing FIELDBOSS_PCT doesn't shift any pre-existing slot's
    grunt/miniboss/night_boss outcome. Same reproducibility guarantees
    as the primary roll.
    """
    if slot_msb_name is None or slot_pi is None:
        return None
    if (slot_msb_name, slot_pi) in V3_BOSS_SLOT_CATALOG:
        return None
    # v0.27.35: deterministic per-slot tier pin (skips the random roll).
    _pin = V3_FIELD_SLOT_TIER_PIN.get((slot_msb_name, slot_pi))
    if _pin is not None:
        return _pin
    r = _field_slot_roll(slot_msb_name, slot_pi)
    # Order: night_boss → miniboss → field_boss → grunt fall-through.
    # Layout in the unit interval (cumulative):
    #   [0,                                NB)                  → night_boss
    #   [NB,                               NB + MB)             → miniboss
    #   [NB + MB,                          NB + MB + FB)        → field_boss (possibly promoted)
    #   [NB + MB + FB,                     1)                   → grunt
    #
    # Why this order? It places NB at the low end (stable: bumping NB% only
    # steals from MB+FB+grunt territory in that priority order), MB in the
    # middle (also stable wrt smaller changes), and FB just before grunt so
    # that BUMPING FB% only steals from grunt — never reclassifies an
    # already-rolled NB or MB outcome. This makes the "make field encounters
    # more common" knob safe to tune without disturbing the boss-tier rates.
    nb = V3_FIELD_UPGRADE_NIGHTBOSS_PCT
    mb = V3_FIELD_UPGRADE_MINIBOSS_PCT
    fb = V3_FIELD_UPGRADE_FIELDBOSS_PCT
    if r < nb:
        return 'night_boss'
    if r < nb + mb:
        return 'miniboss'
    if r < nb + mb + fb:
        # Conditional promote: a second roll keyed off a distinct namespace.
        # The 'fbpromote' tag ensures this draw doesn't collide with the
        # primary field roll or the picker's _slot_decision_rng.
        import hashlib
        key = (f"{_V3_RUN_SEED}|fbpromote|{slot_msb_name}|{slot_pi}").encode()
        h = int.from_bytes(hashlib.sha1(key).digest()[:8], 'big')
        if random.Random(h).random() < V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT:
            return 'night_boss'
        return 'field_boss'
    return 'grunt'

# v0.20.8: Arena-only target c-prefixes. These enemies need flat boss-arena
# terrain to function (XXL grounded with locomotion=0 — too many feet, no
# pathfinding tolerance for outdoor uneven ground). Only placed at slots
# where the source variant has a boss marker (Field Boss, Night Boss,
# Evergaol, Remembrance, Encampment, Ruins Boss, etc.) — i.e. arena slots
# designed flat by FromSoft.
#
# Without this restriction these get TGT_EXCL'd entirely. With it they
# still appear in the run, just only at slots where they have a chance
# to work. The is_boss_tier_variant check (recipient_is_boss=True) is
# the gate: variant marker is the most reliable arena-vs-field signal.
# Chrs needing tighter restrictions (open-arena vs sub-arena
# geometry) escalate to V3_NIGHT_BOSS_ONLY_TARGETS (excludes
# Encampment/Evergaol sub-arenas) or V3_NIGHT_BOSS_STRICT_TARGETS
# (the dedicated-NB-anchor-only gate).
#
# v0.28.x TODO Step 3: editorial base sourced from
# data/placement_budget.json at module-load. load_data() still extends
# this set via `expects_boss_arena`-tag auto-detection + M-size lift +
# V3_ARENA_ONLY_FORCE_LIFT subtraction (idempotent composition with the
# JSON's post-load snapshot — see engine/placement_budget.py docs).
# Historical entries documented in git: c5210 (Dancing Lion),
# c4650 (Dragonkin Soldier), c4620 (Astel), c4660 (Guardian Golem),
# c4580 (Large Wormface).
V3_ARENA_ONLY_TARGETS: set[str] = set()

# v0.20.81: NIGHT_BOSS_ONLY restriction. Strictly tighter than
# V3_ARENA_ONLY_TARGETS — only allows placement at slots whose recipient
# variant carries one of V3_NIGHT_BOSS_NAME_MARKERS (Night Boss / Field
# Boss / Castle Boss / Fort Boss / Ruins Boss / (Crater) / (Noklateo) /
# Remembrance). Excludes 'Encampment' and 'Evergaol' qualifiers which
# ARENA_ONLY accepts but which sometimes refer to compact authored
# sub-arenas where giga-class chrs still freeze (cf v0.20.78 c4620 at
# m32_10 pi=49 "Encampment- in tower").
#
# Mechanism: pick_target_cp subtracts V3_NIGHT_BOSS_ONLY_TARGETS from
# the pool unless the recipient slot's variant satisfies
# is_night_boss_variant. See filter pass right after the ARENA_ONLY
# subtraction in pick_target_cp.
#
# v0.20.83: populated with the heritage night-boss roster from base
# Nightreign (PC Gamer per-Expedition Night 1 / Night 2 boss table,
# cross-referenced against our roster). Intent: shuffle the heritage
# bosses across the heritage night-boss arena slots (Crucible Knight
# might appear at a Death Rite Bird arena, Death Rite at a Wormface
# arena, etc.) while keeping them out of regular field/encampment
# slots where they'd over-power the encounter or freeze. User: "I want
# the Night Boss pool to be pretty small and powerful... It would be
# enough to just take everything that's a night boss in base NR but
# just randomize them all across all the nightlord encounters". Mohg
# (c4800) is intentionally NOT here — see V3_NIGHT_OR_FIELD_BOSS_ONLY.
V3_NIGHT_BOSS_ONLY_TARGETS = {
    'c2130',  # Morgott (Fell Omen) — XL
    'c2500',  # Crucible Knight — M
    'c3050',  # Outland/Battlefield Commander — L
    'c3100',  # Bell Bearing Hunter — L
    'c3150',  # Night's Cavalry (Glaive + Flail variants) — M
    'c3250',  # Draconic Tree Sentinel — XL
    'c3251',  # Tree Sentinel — XL
    'c3252',  # Royal Carian Knight — XL (v0.20.84 add). Heritage XL
              #   mounted boss; PC Gamer table calls this "Royal
              #   Cavalryman" (slipped past the v0.20.83 keyword
              #   mapping). Same paired-chr problem as c3251 Tree
              #   Sentinel — rides c3160 Funeral Steed which is
              #   EXCLUDED, so c3252 standalone at non-vanilla slots
              #   is a horseless rider. v0.20.83 spoiler had c3252 at
              #   m32_00 pi=31 (Elder Lion Encampment) and m32_20
              #   pi=63 (Frenzied Flame Troll Encampment) — likely
              #   user CTD. Restricting to NB slots concentrates it
              #   at vanilla mount-cluster-preserved arenas.
    'c3560',  # Godskin Apostle — L (duo with c3570)
    'c3570',  # Godskin Noble — XL (duo with c3560)
    'c4130',  # Demi-Human Queen — XL
    'c4353',  # Leyndell Knight (Royal Cavalryman) — M
    'c4510',  # Ancient Dragon — GIGA (also EXCLUDED, no-op add)
    'c4580',  # Large Wormface — GIGA (also ARENA_ONLY)
    # v0.23.06: c4640 lifted from NIGHT_BOSS_ONLY per playtest. Originally
    # added defensively (comment notes "tier=night_boss in tags; not in
    # PC Gamer table — likely vanilla Field Boss"). Combined with the
    # tier override 'c4640': {'tier': 'miniboss'} in V3_TAG_OVERRIDES,
    # this gets it appearing at field-encounter slots for variety. XXL
    # size class handled by BIG_PROXIMITY demotion if multiple pile up.
    # 'c4640',  # Ulcerated Tree Spirit — XXL (lifted v0.23.06)
    'c4650',  # Dragonkin Soldier (Nox) — XXL (also SENSITIVE+ARENA_ONLY)
    # v0.23.06: c4680 lifted from NIGHT_BOSS_ONLY per playtest. Same
    # rationale as c4640: tagged night_boss but only 3 variants, no
    # PC Gamer Night Boss listing, expects_boss_arena=False. Tier
    # override 'c4680': {'tier': 'field_boss'} in V3_TAG_OVERRIDES
    # opens it to field_boss source slots (overworld giant slots).
    # Stays in V3_FRAGILE_SENSITIVE_TARGETS — that protection prevents
    # placement at off-mesh / narrow / SENSITIVE-only slots where its
    # flying_dragon rig + weight=30000 would break.
    # 'c4680',  # Fallingstar Beast — GIGA (lifted v0.23.06)
    'c4750',  # Grafted Monarch — L
    'c4770',  # Valiant Gargoyle — XXL
    'c4910',  # Magma Wyrm (Crater) — GIGA
    'c4911',  # Great Wyrm — GIGA (also EXCLUDED, no-op add)
    'c4950',  # Tibia Mariner — XL (also EXCLUDED, no-op add)
    'c4980',  # Death Rite Bird — XXL
    'c5010',  # Golden Hippopotamus (non-NB variant) — XXL
    'c5011',  # Golden Hippopotamus (Night Boss) — XXL
    'c5810',  # Demi-Human Swordmaster — XS (also EXCLUDED, no-op add)
    'c7900',  # Nameless King — scripted
    'c7910',  # Nameless King (Mount) — scripted
    'c7100',  # Ancient Hero of Zamor — L (v0.20.88 add). Heritage
              #   ER boss. Has two variants: (Field Boss) renders as
              #   normal solid model, (Ruins) renders as translucent
              #   ghost. v0.20.86 added (Ruins) npc=71000110 to
              #   V3_AVOID_VARIANT_NPC_IDS so variant pick prefers
              #   (Field Boss) when alternatives exist — but at
              #   non-boss slots, the field-tier filter excludes
              #   (Field Boss) and the only non-marker variant is
              #   (Ruins), so the avoidance falls back. Adding c7100
              #   to NIGHT_BOSS_ONLY restricts it to boss-marker
              #   slots where (Field Boss) is the variant pick —
              #   ghost rendering issue resolved at the cost of
              #   non-boss slot placements (consistent with the
              #   heritage XL boss tier roster).
}

# v0.20.83: NIGHT_OR_FIELD_BOSS_ONLY tier — strictly tighter than
# NIGHT_BOSS_ONLY. Only allows placement at slots whose recipient
# variant carries 'Night Boss' or 'Field Boss' markers. Excludes
# Castle/Fort/Ruins-interior boss slots, (Crater)/(Noklateo) Shifting
# Earth slots, and Remembrance heritage-ER slots — all of which
# NIGHT_BOSS_ONLY accepts.
#
# Created for c4800 Mohg the Omen. User obs: "I've seen Mohg watching
# around and he's chill" (working at vanilla Field Boss slots in
# v0.20.78 spoiler at "Lordsworn Captain (Mountaintop)"); user
# decision: restrict him to true Night Boss + Field Boss arena slots
# only. Mohg is tier=field_boss in our tags (not night_boss), so this
# is the appropriate tier — he gets slotted into the Limveld outdoor
# boss-arena rotation alongside the heritage night bosses.
#
# Mechanism: pick_target_cp subtracts V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS
# from the pool unless the recipient slot's variant satisfies
# is_night_or_field_boss_variant. Filter pass sits right after the
# NIGHT_BOSS_ONLY pass.
V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS = {
    'c4800',  # Mohg the Omen — tier=field_boss heritage boss
}


# v0.23.11 → v0.26.x: V3_NIGHT_BOSS_STRICT_TARGETS retired. Originally a
# "strictest geometric gate" subset of NB-CALIBER for chrs whose footprint
# was too large for Field Boss / Castle Boss / Fort Boss slots. Removed
# in v0.26.x: the gate matched on the source slot's variant name string
# containing "Night Boss", which is a string filter, not a geometric one.
# Real geometric concerns are handled by V3_ARENA_ONLY_TARGETS (chrs
# requiring arena rooms) and V3_FRAGILE_SENSITIVE_TARGETS (chrs whose
# rigs misbehave on rough/narrow terrain). Sim (dev/sim_reservation_
# health.py) showed the variant-name filter was blocking ~7 marquee NB
# chrs (Midra, Romina, Metyr, Fortissax, Dragonslayer Armor, plus
# vanilla c4510 Ancient Dragon and c4580 Giant Wormface) from finding
# qualifying reservation slots at 65-81% rates. Per user direction:
# "I want night bosses at field boss slots, as long as they can traverse"
# — traversal IS the concern, and traversal is what arena_only /
# fragile_sensitive / swap compat handle. Empty set retained so
# downstream code that reads this constant doesn't crash; population
# sites in load_data() were also removed.
#
# v0.28.x TODO Step 3: placeholder type-hint only. data/placement_budget.json
# is the source of truth; the gate is currently empty there too (the
# `nb_strict` field is False for all 446 entries).
V3_NIGHT_BOSS_STRICT_TARGETS: set[str] = set()


# v0.27.28: V3_FORBIDDEN_BY_SOURCE_ANIM REMOVED. This dict keyed forbidden
# target c-prefixes off the SOURCE chr's family; it had been empty ({})
# since v0.24.75 (its CTD theories were misattributed asset-load gaps), so
# the Gate 3 that consulted it was a no-op. Removed wholesale along with the
# family field it depended on. If a real playtest-confirmed source→target
# CTD pattern ever resurfaces, gate it on a concrete property with evidence.


# v0.24.19 / rewritten v0.26.x: getSoul floor overrides. Vanilla NR has
# many chrs authored with getSoul=0 (or getSoul far below their visual
# threat level) because in vanilla they appear in contexts where the
# kill isn't player-facing — cluster swarm mobs, scripted intro chrs,
# Nightlords whose drops don't matter because the run ends on kill.
# When the rando relocates these chrs to overworld slots and the player
# kills them in isolation, the engine's pity-reward floor (~80 runes)
# kicks in and produces a "this beefy chr dropped 80 runes" disconnect.
#
# Policy (v0.26.x): uplift any chr whose getSoul is below its tier's
# vanilla median up to that median; leave everything at/above alone.
# This is a pure floor — it never lowers a drop.
#
# The floors below are the PLACEMENT-WEIGHTED vanilla medians: for each
# tier, take every vanilla NR chr's authored getSoul, weight it by the
# chr's vanilla placement count (from nr_all_slots.json), and take the
# median of that distribution. Placement-weighting means the floor
# reflects what a typical *encounter* of that tier pays in vanilla, not
# what a typical roster entry pays — a tier's median isn't skewed by
# rare chrs with few placements.
#
# Earlier versions hand-curated a per-c-prefix dict, which let chrs
# slip through uncovered (e.g. c4181 Maris' Jellyfish). This is now
# tier-driven: dev/emit_getsoul_overrides.py walks every NpcParam row,
# looks up the chr's tier, and floors the row if it's below the tier
# median. No per-chr list to drift out of date.
#
# Note: night_boss median < nightlord median here. Both are honest
# placement-weighted vanilla numbers; vanilla simply pays night-boss
# encounters less per-placement than the rarer nightlord encounters.
#
# STATUS (v0.30.x): APPLIED AT RUNTIME. The v0.26.x decision to leave this
# opt-in was predicated on the rando having no way to patch a regulation.bin
# (the WitchyBND/AES concern). That premise is gone: the AES-256-CBC + ZSTD
# regulation codec now exists (regulation_io) and the pipeline already patches
# the reg every seed for the merchant shop, drops, and reward mapping. So these
# floors are now consumed at runtime by npcparam_getsoul_fill.py, which floors
# getSoul on the installed reg as a second NpcParam pass alongside the reward
# fill — no manual Smithbox import needed. The floor is seed-independent (a
# fixed correction), so it does not affect per-seed determinism.
#
# Consumed by BOTH the runtime pass (npcparam_getsoul_fill.py) and the dev CSV
# emitter (dev/emit_getsoul_overrides.py, still useful for a hand-built reg). If
# you edit these floors, both pick up the change automatically; regenerate
# data/npcparam_getsoul_overrides.csv (python3 dev/emit_getsoul_overrides.py)
# only if you ship that CSV.
V3_GETSOUL_TIER_FLOORS = {
    'nightlord':  4375,
    # v0.28.x: night_boss 3750 -> 2910. Re-derived (placement-weighted
    # vanilla median per tier) after the tier-separation pass demoted
    # 24 chrs from night_boss to field_boss. The demoted set included
    # the high-rune-value overworld encounters (Tree Sentinel, Tibia
    # Mariner, Death Bird, Hippopotamus Golden Wings, Putrescent
    # Knight, Furnace Golem, Borealis, Ancient Dragon, Fallingstar
    # Beast, Magma Wyrm, Ulcerated Tree Spirit, Dragonkin Soldier),
    # so removing them drops night_boss to the climactic arena bosses
    # only. c2500 Crucible Knight (the m46_60 Alabaster Evergaol; 17
    # placements at rep=2910 rune value) anchors the new weighted
    # median. Test surface: test_getsoul_overrides::test_floors_match_
    # placement_weighted_medians.
    'night_boss': 2910,
    # v0.28.x: field_boss 1605 -> 4687. Re-derived after the tier-
    # separation pass moved 24 chrs INTO field_boss. The demoted set
    # carries higher rune values than the pre-v0.28.x field_boss
    # residual (c4450 Walking Mausoleum only), so the placement-
    # weighted median jumps. c4680 Full-Grown Fallingstar Beast (18
    # placements, rep=5000) anchors the new median.
    'field_boss': 4687,
    # v0.27.13: miniboss 475 -> 450. Re-derived (placement-weighted
    # vanilla median per tier — see test_getsoul_overrides.py) after
    # c4050 Kaiden Sellsword and c5840 Black Knight were bumped into
    # the miniboss tier for the rider/mount-role feature. Kaiden in
    # particular is heavily placement-weighted (24 inventory slots) and
    # has a low vanilla rune value, pulling the weighted median down a
    # bucket. NOTE: these two were retiered for MECHANICAL reasons
    # (role-pool + cap compatibility), not because they are miniboss-
    # strength rewards — so they mildly skew this floor. Acceptable at
    # one bucket; if more mount-role chrs are added and the skew grows,
    # the right fix is to exclude mount_role-tagged chrs from the
    # derivation (see docs/OPEN_ISSUES.md).
    'miniboss':    450,
    'grunt':       100,
}


# v0.23.07: Night Boss caliber pool. SOURCE-side restriction at Night Boss
# arena slots. When a slot's source variant carries a Night Boss marker
# (per is_night_boss_variant), pick_target_cp intersects its candidate
# pool with this set — restricting Night Boss arena replacements to
# encounters that feel "epic" rather than the broader boss-tier set
# (which currently includes XL/L humanoid mooks like Depraved Perfumer,
# Banished Knight, Cleanrot Knight that have a "Boss" name marker
# somewhere but are mechanically field encounters).
#
# Symmetry note: V3_NIGHT_BOSS_ONLY_TARGETS restricts where these
# c-prefixes can appear (target side: NB targets must land at NB-marker
# slots). V3_NIGHT_BOSS_CALIBER_TARGETS is the inverse (source side: NB
# slots must receive a target from this set). Both gates fire in
# pick_target_cp; together they guarantee NB arenas are populated by
# NB-caliber chrs. Identity preservation: the source's own c-prefix
# is implicitly in the set (since vanilla NR Night Bosses are the
# core 22 entries of this set).
#
# Curation rationale: hand-picked 48 c-prefixes that are either (a)
# the vanilla c-prefix of one of the 22 NR Night Boss arenas, or (b)
# an XL+/GIGA field boss that reads as a true encounter (Astel,
# Borealis, Dragons, Fallingstar, Walking Mausoleum, Mohg, Dancing
# Lion, etc.). Excluded: M-tier humanoid bosses (Cleanrot, Cuckoo,
# Battlemage, Bloodfiend, Banished, Demi-Human normal, Perfumer,
# Page, Mausoleum Knight, Highwayman, etc.) — the v0.23 playtest
# hit a Bell Bearing Hunter slot getting Perfumer and that's the
# anti-pattern this gates against. Also excluded c2276 Giant Death
# Crab — XXL but reads as overgrown crab not "epic boss," fine as
# part of an encounter group but not anchoring an arena solo.
#
# Heritage extension: add local heritage-pack bosses below the
# vanilla list as your install grows. Already in-set: c5860 Ghostflame
# Dragon, c5210 Dancing Lion, c5820 Great Red Bear, c5010/c5011 Hippo,
# c7100 Zamor, c3252 Loretta.
# v0.28.x TODO Step 3: editorial base sourced from
# data/placement_budget.json at module-load. load_data() still
# unions in tag-tier-derived caliber adds (tier=night_boss /
# nightlord chrs not in the exclude set) and pack-loader
# caliber_adds stats — composes idempotently with the JSON
# snapshot's post-load contents.
# Historical curation (preserved in git): 48 hand-picked vanilla
# c-prefixes (22 NR Night Bosses + XL+/GIGA field bosses); plus
# heritage bosses c5860, c5210, c5820, c5010/c5011, c7100, c3252.
V3_NIGHT_BOSS_CALIBER_TARGETS: set[str] = set()


# v0.23.09: NB-arena-only target exclusions. Subset of chrs that pass the
# generic boss-tier filter but break specifically at Night Boss anchor
# slots due to scripted-intro dependencies. They remain valid targets at
# field/grunt slots (where they spawn and aggro normally) — only the NB
# anchor slot's intro trigger fails to fire on them.
#
# Distinct from V3_NIGHT_BOSS_CALIBER_TARGETS (whitelist of who CAN go
# to NB) and V3_EXCLUDE_TARGET_PREFIXES (full target ban). This is a
# narrow blacklist for NB-only.
#
# Pattern of failure: chr spawns visually but stays in idle pose ("arms
# crossed, doing nothing"). NR's NB arena trigger looks for an
# aggro-state transition that the imported chr never enters because its
# behavior graph expects a different cinematic trigger.
#
# Confirmed members:
#   c4490 Jar Warrior (Alexander) — multiple sightings of "stands with
#     arms crossed" at NB anchor slots. Vanilla NR's c4490 is the
#     quest-NPC variant, designed to wait for player challenge dialogue
#     before initiating combat. No equivalent dialogue at NB anchors.
#   c8300 Dragonslayer Armor (DS3 MMV) — v0.23.72-late: user reported AI
#     freeze at m49_29 NB1 slot (Sentient Pest seed 35300). Boss spawned,
#     healthbar appeared, but AI never engaged — fight could not be
#     completed (necessitated the boss_clear_watchdog EMEVD patch as a
#     defensive net). Works fine at other arena types this seed (m49_21
#     pi=5 also NB1 — but that one wasn't approached so not confirmed;
#     c8300 was previously vindicated at named_boss/ruins_boss tiers in
#     v0.23.46-post-vindication playtest). Likely interaction between
#     c8300's DS3-port animation graph and NB-arena's specific EMEVD
#     setup (the 90015023 multi-boss handler, wave-grunt SpEffect
#     triggers, or the named/anonymous chrEntityId pattern unique to
#     NB-tier).
#
# v0.24.73: c8300 LIFTED from this set. The boss_clear_watchdog patch
# referenced above ("necessitated the boss_clear_watchdog EMEVD patch
# as a defensive net") has shipped — 300s timeout inside the L0 loop.
# v0.24.71 added preboss_wake_timeout (90s) on the outer chrAreaFlag
# wait. Combined, the worst-case stall at an NB1 arena is now ~7 min
# auto-resolution. User reported seeing Dragonslayer Armor working as
# Night Boss in subsequent playtests. Cap=1 retained via existing
# entry in V3_UNIQUE_TARGET_CAPS, so at worst one stall per seed.
V3_NIGHT_BOSS_EXCLUDE_TARGETS = {
    'c4490',  # Jar Warrior — NPC-style "wait for challenge" idle, no NB trigger
    'c4640',  # Ulcerated Tree Spirit — XXL large_boss_ground; lacks the
              #   scripted-intro wake-up anim bank, so it CTDs at strict NB
              #   arenas (seed 677311 m49_29, Demi-Human Queen duo). Same
              #   failure class as Astel/Hippo at m38_00 pi51. Dropped from
              #   NB eligibility per user; still valid as field content.
    # 'c8300', # LIFTED v0.24.73 — Dragonslayer Armor freeze covered by
              #                  boss_clear_watchdog (300s) +
              #                  preboss_wake_timeout (90s) EMEVD patches
}


# v0.23.07: per-c-prefix uniqueness caps. After this many placements of
# a given c-prefix have been committed across the run, that c-prefix is
# removed from the candidate pool for all subsequent slots. Implementation:
# a pre-pass computes which slots get reserved (one slot per cap unit),
# scoring candidate slots by quality (compat, terrain, MSB
# class). Reserved slots commit their c-prefix directly; all other slots
# subtract exhausted-cap c-prefixes from their pool.
#
# Why: at scale (~3000 placements per run), even thoughtfully-tagged
# big-creature chrs end up appearing 6-17 times in a run. That dilutes
# their impact ("oh, another Tree Spirit" on the third encounter) and
# creates the "swarm of Fingercreepers" perception. Capping converts
# them from "common" to "rare encounter." For named bosses (Borealis,
# Magma Wyrm, etc.), capping at 1 also reduces failure rate enough that
# previously-CTD-prone chrs become safe to re-enable: a single die roll
# at a quality slot vs. N die rolls including bad ones.
#
# Naming convention:
#   cap=1: named bosses, encounter-as-event chrs (Borealis the Freezing
#          Fog, Astel Stars of Darkness, Ulcerated Tree Spirit). One
#          per map. Never two.
#   cap=2: unnamed archetype giants (Giant Crab, Giant Fingercreeper).
#          Rare but not quite singular — "you might see one in the
#          north and one in the south."
#
# Vanilla-preservation interaction: if a c-prefix is unique-capped AND
# its source slot is preserved (via V3_EXCLUDE_SOURCE_NPC_PARAMS or
# similar), that preservation counts toward the cap. So if Margit is
# cap=1 and her vanilla slot is source-preserved, no additional Margit
# placements get reserved.
#
# Heritage chrs are NOT in this constant — extend locally if your
# install has imported heritage chrs you want capped (Metyr, Promised
# Consort Radahn, Crucible Knight Devonia, etc.). Same dict shape.
# v0.28.x TODO Step 3: editorial caps sourced from
# data/placement_budget.json at module-load. load_data() still
# applies tier-derived caps in its tier loops:
#   - miniboss tier  → cap=4  (~L3990 in load_data)
#   - mount_role     → cap=30 (~L4013)
#   - grunt tier     → cap=40 (~L4061)
#   - _RARE_NOVELTY_CAPS overrides (c4442, …) → cap=4 (~L4086)
# These are item-assignments (dict[cp] = N); composed on top of
# the JSON-pre-loaded dict, they are idempotent (same chr always
# gets the same cap from its tier classification).
#
# Historical curation (preserved in git history): 77 hand-picked
# editorial caps from v0.20.x onward — vanilla single-spawn bosses
# (c4670, c7910, c6200 at cap=1), mini-boss curation, mount-role
# pool sizing, force-included DLC bosses. JSON `cap` field per chr
# is the current source; `rationale` / `since` per entry capture
# the editorial story (populated lazily as entries are revisited).
V3_UNIQUE_TARGET_CAPS: dict[str, int] = {}


# ============================================================================
# v0.26.x: floor/ceiling cap split — V3_RESERVATION_FLOORS
# ============================================================================
# V3_UNIQUE_TARGET_CAPS (above) was historically doing double duty:
#   (a) reservation-pre-pass target — "try to reserve N quality slots
#       for this chr" (a *floor* / minimum-guarantee semantic)
#   (b) runtime ceiling — "never have more than N placements per seed"
#       (a *ceiling* / max-allowed semantic)
# These two concepts are independent in principle. The Dancer (c7920)
# visibility issue surfaced the conflation: bumping cap=2 → cap=3 to
# strengthen guarantee (a) inflated the ceiling (b) past intent, and
# the reservation pre-pass's strict slot-scoring was still failing to
# seat even 2 quality slots for some script_spawn-tagged chrs, so the
# higher number didn't help anyway.
#
# v0.26.x split:
#   V3_UNIQUE_TARGET_CAPS    — runtime CEILING. Maximum placements per
#                              seed (named here for backward compat;
#                              read by runtime cap-check call sites).
#   V3_RESERVATION_FLOORS    — pre-pass FLOOR. Minimum guaranteed
#                              placements per seed. Reservation pre-
#                              pass tries to seat at least N quality
#                              slots for each chr listed here.
#                              Failure → logged in spoiler's
#                              unique_unplaced; chr falls back to
#                              organic placement against the ceiling.
#
# A chr can be in CEILINGS without being in FLOORS (cap-only — limit
# but don't guarantee). A chr in FLOORS MUST also have a CEILINGS
# entry with floor ≤ ceiling; the engine asserts this at load time
# (see test_v3_reservation_floors.py::test_floors_le_ceilings).
#
# Initial v0.26.x policy:
#   - All night_boss-tier chrs + NB-caliber MMV imports get floor=1.
#     Result: the marquee NB roster guaranteed to appear ≥1×/seed.
#   - Mini-bosses, grunts, field-bosses, trash: ceiling-only (no
#     reservation guarantee, placed organically). Their existing
#     V3_UNIQUE_TARGET_CAPS values stay as ceilings.
#   - Exception: c7910 Storm King NOT in FLOORS. Paired-only with
#     c7900 Nameless King in vanilla; reserving Storm King
#     independently risks divorcing them across slots. The c7900
#     reservation pulls c7910 along via vanilla pairing.
V3_RESERVATION_FLOORS = {
    # NR night_boss-tier (vanilla NR Night Boss roster)
    'c2130': 1,  # Margit
    'c2500': 1,  # Crucible Knight
    'c3050': 1,  # Commander
    'c3100': 1,  # Elemer of the Briar
    'c3560': 1,  # Godskin Apostle
    'c3570': 1,  # Godskin Noble
    'c4130': 1,  # Demi-Human Queen
    'c4510': 1,  # Ancient Dragon
    'c4580': 1,  # Giant Wormface
    'c4750': 1,  # Godrick the Grafted
    'c4911': 1,  # Great Wyrm Theodorix
    'c5011': 1,  # Golden Hippopotamus (Golden Wings)
    'c5810': 1,  # Demi-Human Swordmaster Onze
    # DS-heritage night-boss tier (reclassified script_spawn→nr_placed
    # in v0.26.x after UTF-16-LE MSB audit confirmed actual placements)
    'c7700': 1,  # Gaping Dragon       (m47_80)
    'c7710': 1,  # Centipede Demon     (m47_90)
    'c7820': 1,  # Smelter Demon       (m48_10)
    'c7900': 1,  # Nameless King       (m48_20 + m19_00; paired with c7910)
    'c7920': 1,  # Dancer of the Boreal Valley (m48_30)
    # Note c7910 Storm King intentionally NOT in floors — paired-only
    # with c7900; reservation rides on c7900.
    #
    # NB-caliber MMV imports (Elden Ring SoTE bosses + DS3 DLC bosses
    # imported via More Map Variations). Promoted to NB caliber in
    # v0.25.3; given floor=1 here so they appear reliably.
    'c4511': 1,  # Lichdragon Fortissax       (SoTE MMV)
    'c5000': 1,  # Commander Gaius             (SoTE MMV)
    'c5030': 1,  # Romina, Saint of the Bud    (SoTE MMV)
    'c5051': 1,  # Midra, Lord of Frenzied Flame (SoTE MMV)
    'c5200': 1,  # Metyr, Mother of Fingers    (SoTE MMV)
    'c8300': 1,  # Dragonslayer Armor          (DS3 MMV) — EXCLUDED, floor kept per marquee-NB / nb-caliber-mmv floor policy (resumes if un-excluded)
}




# the spoiler markdown. Every slot where the c-prefix appears as source
# OR target gets enumerated under "## Tracked enemies". Easy to extend
# by editing this set.
V3_TRACKED_C_PREFIXES = {
    'c4660',  # Guardian Golem (field_boss) — keep eye on placements
    'c4580',  # Giant Wormface (night_boss) — keep eye on placements
    # v0.20.18: Oracle Envoys — source-excluded so they NEVER appear as
    # source slots in the swap entries. The preserved-source tracker
    # added in v0.20.18 enumerates their vanilla MSB locations under
    # "Source slots (preserved as vanilla)" so the user can see where
    # they're still standing in their seed.
    'c3610',  # Oracle Envoy
    'c3620',  # Oracle Envoy (Large; Cathedral)
    # v0.20.21: Maris cluster siblings — also source-excluded. Tracking
    # them so when "frozen Maris X" reports come in, the spoiler
    # already has their preserved-vanilla locations enumerated and
    # we can localize without spelunking the JSON.
    'c5110',  # Maris' Tendril
    'c4181',  # Maris' Jellyfish
}

# v0.26.x: V3_TAG_OVERRIDES REMOVED. The 45-entry tier-override dict
# (kept for years to apply manual tier corrections after pack loaders
# ran) was flattened into the source manifests directly:
#   - 33 entries into data/nr_enemy_tags.json (in-tree NR chrs)
#   - 7 entries into data/mmv_imports.json (MMV-imported chrs)
#   - 5 no-op entries (override matched native value) dropped
# Per-entry _tier_override_v0_26_x annotation marks the changes so
# future audits can trace what was overridden when. Eliminates the
# "is tier from the JSON or from a Python override?" ambiguity that
# made test design awkward and added no value to the runtime.


# v0.20.3: defensive exclude cleanup. If a stale .pyc is being loaded from
# __pycache__ that has c4181/c3610/c3620 in any target-exclude set
# (an old intermediate build added them by mistake), this restores the
# correct state at module load. Idempotent; no-op when sets are already
# clean. Diagnoses the FI-drop-at-after_excludes mystery: the user's
# v0.20.2 spoiler showed these cps universal=3779 / after_excludes=0,
# but the source had them in NO exclude set. Stale .pyc was loading.
#
# v0.20.69: c5110 Maris' Tendril REMOVED from this list — promoted to
# V3_EXCLUDE_TARGET_PREFIXES (paired-chr breaks-everywhere). The
# defensive cleanup must not undo that exclusion. c5110 is no longer a
# "reserved diagnostic target" because it's broken in all slot kinds —
# diagnostic forcing of a broken-everywhere c-prefix would just produce
# guaranteed CTDs.
#
# v0.23.15: c4181 Maris' Jellyfish REMOVED from this list — promoted to
# V3_EXCLUDE_TARGET_PREFIXES because the .chrbnd.dcx file doesn't actually
# ship with vanilla NR (chr/ Inventory tab Diagnose: missing on disk).
# Same rationale as v0.20.69 c5110: the defensive-cleanup must not undo
# a real exclusion.
#
# v0.24.39: c3610 Oracle Envoy (SMALL) REMOVED from this list — same
# protocol as v0.20.69/v0.23.15. Playtest report (seed 798229 v0.24.37,
# MP-safe off): c3610 placed at m45_01 pi=4 and m43_41 pi=7 starting
# encampments → "floating frozen, no animation" in-game. The chr is
# _cluster_only and the standalone slots don't satisfy the cluster
# handshake the chr's spawn script expects. The Large variant c3620
# (Cathedral) has the same _cluster_only tag but no in-game freeze
# reports yet, so it remains reserved.
_FI_CPS_RESERVED_FOR_TARGET = frozenset({'c3620'})  # was {'c3610', 'c3620'} pre-v0.24.39
_v3_dropped_from_excludes = []
for _set_name in ('V3_EXCLUDE_PREFIXES', 'V3_EXCLUDE_TARGET_PREFIXES',
                  'V3_GHOST_EXCLUDE_TARGET_PREFIXES'):
    _s = locals()[_set_name]
    for _fi_cp in _FI_CPS_RESERVED_FOR_TARGET:
        if _fi_cp in _s:
            _s.discard(_fi_cp)
            _v3_dropped_from_excludes.append((_set_name, _fi_cp))
del _set_name, _s, _fi_cp

# c-prefixes that should NEVER be added to expanded resilient pool even
# if they meet the tier+anim+size criteria. Empirical fragile-map
# misbehavior list.
# v0.23: dead — was fed _expanded_resilient_pool, removed with tier modes.
# Keeping the comment as a paper trail in case the empirical observation
# (Demi-Human Shaman c4110 freezing in cathedrals) gets reinvoked elsewhere.


# =====================================================================
# v0.19.21: Cooperative cancellation
# =====================================================================
# Threading event set by the GUI's cancel button. Checked at per-map
# loop boundaries in cmd_shuffle_v3 (and similar entry points). Latency
# is up to one map's processing time — typically 1-3 seconds.
#
# Always cleared at the start of a fresh run so a previously-cancelled
# state doesn't poison the next attempt.
_CANCEL_EVENT = threading.Event()


class CancelledError(Exception):
    """Raised by the engine when cancellation is requested mid-run.
    Caller (worker thread) should catch and clean up gracefully."""
    pass


def set_cancel_requested(value=True):
    """Request cancellation of the in-progress run. Idempotent — safe to
    call multiple times. Pass value=False to clear the request (or use
    clear_cancel_request()).
    """
    if value:
        _CANCEL_EVENT.set()
    else:
        _CANCEL_EVENT.clear()


def clear_cancel_request():
    """Reset the cancel flag. Called at the start of each new run."""
    _CANCEL_EVENT.clear()


def is_cancel_requested():
    """Non-raising check — for callers that want to peek at the flag
    without raising CancelledError."""
    return _CANCEL_EVENT.is_set()


def _check_cancel():
    """Raise CancelledError if cancellation has been requested. Called
    at safe checkpoints (per-map iteration in cmd_shuffle_v3)."""
    if _CANCEL_EVENT.is_set():
        raise CancelledError("Run cancelled by user")


# v0.19.5: Slot terrain classification cache.
#
# Loaded lazily from slot_terrain.json (built by build_slot_terrain.py from
# Havok navmesh AABB data). Used to determine whether a slot is on/off-mesh
# without relying on y-coordinate heuristics.
#
# Replaces the v0.10 y >= 50 threshold rule for V3_AERIAL_SOURCE_ALT.
# A slot's on/off-mesh status is independent of seed (positions are fixed
# per (msb, pi) regardless of randomization), so the cache is permanent.
#
# Falls back gracefully: if slot_terrain.json is missing or doesn't
# contain a particular slot, callers fall back to the legacy y-threshold
# rule (which was correct ~75% of the time, just imprecise).
_SLOT_TERRAIN_CACHE = None


def _get_slot_terrain():
    """Load slot_terrain.json once. Returns dict (msb, pi) -> status string
    where status is 'off_mesh' or 'no_match'. on_mesh slots are NOT in the
    dict (absence == on_mesh by convention). Returns empty dict if file
    is missing — callers fall back to legacy y-threshold rule."""
    global _SLOT_TERRAIN_CACHE
    if _SLOT_TERRAIN_CACHE is None:
        import json as _json, os as _os
        _SLOT_TERRAIN_CACHE = {}
        for _candidate in (
            _data_path('slot_terrain.json'),
            _os.path.join(_os.getcwd(), 'slot_terrain.json'),
        ):
            try:
                with open(_candidate, encoding='utf-8') as f:
                    _data = _json.load(f)
                for _msb, _slots in _data.get('off_mesh_slots', {}).items():
                    for _pi_str, _info in _slots.items():
                        try:
                            _SLOT_TERRAIN_CACHE[(_msb, int(_pi_str))] = _info.get('status', 'off_mesh')
                        except (ValueError, TypeError):
                            continue
                break  # loaded successfully
            except (FileNotFoundError, OSError):
                continue
            except Exception:
                # Corrupt JSON or unexpected schema — silently fall back to empty
                # cache (legacy y-threshold rule will engage)
                break
    return _SLOT_TERRAIN_CACHE


def lookup_slot_terrain(msb_name, pi):
    """Returns terrain status for a slot, or None if unknown / on-mesh.

    Returns:
      'off_mesh'  — slot is off the navmesh; needs aerial-only target
      'no_match'  — slot is a placeholder (e.g. pos=(*, 0, 1));
                    swap should be skipped to keep vanilla
      None        — either slot is on-mesh OR terrain data is unavailable
                    (caller should treat None as on-mesh)
    """
    if msb_name is None or pi is None:
        return None
    return _get_slot_terrain().get((msb_name, pi))



# v0.27.28: _build_size_drift_fallback_pool (formerly
# _build_anim_class_fallback_pool) REMOVED — it was unreferenced dead code.
# A size-drift candidate-pool helper that nothing called; its family
# filter had already been stripped in v0.24.100, leaving a size-only pool
# with no call sites. Reconstruct from git history if a fallback pool is
# ever needed again.


# ============================================================================
# v0.23.07: Unique-target reservation system
# ============================================================================
# See V3_UNIQUE_TARGET_CAPS comment block for design rationale. This section
# holds the runtime data structures and the pre-pass function that picks
# reserved slots for each capped c-prefix.
#
# Module-scoped because pick_target_cp doesn't take a "current run state"
# argument and adding one would touch dozens of call sites. Reset at the
# start of each run via _reset_unique_run_state(). cmd_shuffle_v3 is the
# only thing that should be calling these — internal API.

# (msb_name, pi) -> reserved c-prefix. When pick_target_cp is called for
# a slot in this dict, it returns the reserved cp directly and bumps the
# placed-count.
_V3_UNIQUE_RESERVATIONS = {}

# c-prefix -> count of placements committed during this run. Used to
# enforce caps for non-reserved slots that happen to roll a capped cp.
_V3_UNIQUE_PLACED_COUNTS = {}

# List of dicts, one per capped c-prefix that couldn't get a reservation.
# Emitted in spoiler header so user can decide whether to relax criteria.
# Format: {'cp': str, 'cap': int, 'reason': str, 'best_attempt': dict|None}
_V3_UNIQUE_UNPLACED_LOG = []


def _reset_unique_run_state():
    """Called at start of each cmd_shuffle_v3 invocation."""
    _V3_UNIQUE_RESERVATIONS.clear()
    _V3_UNIQUE_PLACED_COUNTS.clear()
    _V3_UNIQUE_UNPLACED_LOG.clear()


# v0.28: tiers whose enemies are big enough that an untagged (size_class
# None) member must still be density-gated. Storm King (c7910) and the
# other untagged night bosses live here — without this they were invisible
# to the per-tile XL cap and recycle stacked them (13 Storm Kings/cell).
V3_UNTAGGED_BIG_TIERS = frozenset({'night_boss', 'miniboss', 'boss', 'field_boss'})


def _effective_size_class(cp, tags):
    """size_class for the per-MSB density gate. Untagged boss-tier enemies
    are treated as XL so they can't cluster via recycle past the tile cap;
    untagged grunts stay None (small — cheap to repeat). Does NOT mutate the
    tag data — only the density gate + register_big consult this."""
    t = tags.get(cp) or {}
    sz = t.get('size_class')
    if sz is None and t.get('tier') in V3_UNTAGGED_BIG_TIERS:
        return 'XL'
    return sz


def _reject_target_for_slot(target_cp, src_cp, src_variant_name, tags,
                             *, chaos_mode=False, msb_base=None, pi=None,
                             slot_pos=None, run_ctx=None):
    """Mirror-semantic gate predicate. Body extracted to
    engine.rejection.reject_target_for_slot in v0.28.x; see that
    module's docstring for the full history and gate-by-gate
    rationale.

    The shim passes `globals()` as the namespace dict so the engine
    function reads V3_* constants and helper functions from THIS
    module's state. This makes the extraction work correctly under
    both normal `import oops_v3` and the
    `importlib.util.spec_from_file_location` path used by
    dev/simulate_engine.py (which loads oops_v3 as 'o' and would
    otherwise be invisible to a `sys.modules[__name__]` lookup).
    """
    from engine.rejection import reject_target_for_slot
    return reject_target_for_slot(
        globals(), target_cp, src_cp, src_variant_name, tags,
        chaos_mode=chaos_mode, msb_base=msb_base, pi=pi,
        slot_pos=slot_pos, run_ctx=run_ctx)



def _score_slot_for_unique(slot_info, target_cp, tags):
    """Score how well slot_info fits target_cp for a unique
    reservation. Body extracted (folded) into engine.rejection
    .score_slot_for_unique in v0.28.x — that module now houses both
    mirror functions (reject_target_for_slot + score_slot_for_unique)
    so the gate-mirror invariant lives in one place.

    The shim passes `globals()` as the namespace dict so the engine
    function reads V3_* state and the two oops_v3-side helpers
    (_shifting_earth_event, is_fragile_slot) from THIS module. The
    fold lets the engine.rejection module's score function call its
    sibling reject function directly (no shim hop), so the hot-path
    reservation scoring loop has one less function-call layer.
    """
    from engine.rejection import score_slot_for_unique as _impl
    return _impl(globals(), slot_info, target_cp, tags)



def _shifting_earth_event(msb_name):
    """Return event id for shifting-earth MSBs, or None for always-active /
    non-overworld MSBs.

    Identification: m60_XX_YY_ZZ where ZZ is two digits encoding event +
    LOD. Tens digit = event (1=Mountaintop, 2=Crater, 3=Rot Forest,
    5=Noklateo); ones digit = LOD level (0/1/2). Suffix _0X (X=any) is
    always-active overworld.

    Used by the unique-cap reservation pre-pass: shifting-earth tiles
    can't host reservations because only one shifting-earth event is
    active per Expedition. A reservation that lands on Crater wouldn't
    appear if the run rolls Mountaintop, defeating the whole point of
    capping. Caps still apply to organic picks at shifting-earth slots
    (they share the count budget with always-active), so a cap=1 chr
    can't appear on both always-active AND a shifting-earth tile in
    the same run.
    """
    parts = msb_name.replace('.msb', '').split('_')
    if len(parts) < 4:
        return None
    if parts[0] != 'm60':
        return None
    suffix = parts[3]
    if not (suffix.isdigit() and len(suffix) == 2):
        return None
    tens = int(suffix[0])
    if tens == 0:    # always-active
        return None
    if tens == 9:    # m60_00_00_99 special — exclude from shifting-earth scope
        return None
    return tens


def _enumerate_unique_candidate_slots(input_dir, inventory=None):
    """Walk all MSBs in input_dir, return list of slot_info dicts for
    every Part. Used by the reservation pre-pass.

    Each slot_info has:
      msb, pi, source_cp, source_npc, source_variant_name, position,
      cluster_id (if cluster-aware)

    Position is (x, y, z) tuple or None if read failed.

    v0.27.7: when `inventory` is given (a list of nr_slot_inventory.json
    records), the candidate list is built from it instead of parsing the
    MSBs in input_dir — this is what lets dev/simulate_engine.py run the
    reservation pre-pass with no MSBs. Hub filtering is identical to the
    binary path.
    """
    slots = []
    if inventory is not None:
        for rec in inventory:
            fname = rec['map']
            # Hub MSBs: skipped entirely unless they carry pinned slots,
            # in which case only the pinned Parts are walked. Mirrors the
            # binary path below.
            if fname in V3_HUB_MAPS:
                if not _msb_has_pinned_slots(fname):
                    continue
                if (fname, rec['part_index']) not in V3_BOSS_TIER_PINNED_SLOTS:
                    continue
            src_cp = rec['c_prefix']
            if not (src_cp.startswith('c') and src_cp[1:].isdigit()):
                continue
            pos = rec.get('position')
            if pos is not None:
                pos = (round(pos[0], 2), round(pos[1], 2), round(pos[2], 2))
            slots.append({
                'msb': fname,
                'pi': rec['part_index'],
                'source_cp': src_cp,
                'source_npc': rec['npc_param_id'],
                'source_variant_name': None,
                'position': pos,
                'cluster_id': None,
            })
        return slots
    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith('.msb'):
            continue
        # v0.23.68: hub MSBs are normally skipped from the reservation
        # pre-pass (they're passed through unchanged downstream), but if
        # a hub has pinned slots in V3_BOSS_TIER_PINNED_SLOTS we DO want
        # to walk it — the reservation algorithm needs to know about the
        # pinned Parts so target accounting (uniqueness caps, biome
        # reservations) covers them. See _msb_has_pinned_slots() docs.
        if fname in V3_HUB_MAPS and not _msb_has_pinned_slots(fname):
            continue  # hub MSBs without pinned slots: skip entirely
        path = os.path.join(input_dir, fname)
        try:
            with open(path, 'rb') as fp:
                data = fp.read()
            sections = parse_msb_sections(data)
            models = sections[0]
            midx_to_cp_full = {}
            for gi, eo in enumerate(models['entry_offsets']):
                info = parse_model_entry(data, eo)
                midx_to_cp_full[gi] = info.get('name', '')
            parts_section = next(s for s in sections
                                  if s['name'] == 'PARTS_PARAM_ST')
            # v0.23.68: when this MSB is a hub with pinned slots, restrict
            # the per-Part walk to those pinned (msb, pi) entries; non-pinned
            # Parts won't be shuffled downstream so reserving targets for
            # them would skew the global pool accounting.
            _is_pinned_hub = fname in V3_HUB_MAPS  # we only walk hubs that have pinned slots
            for pi, po in enumerate(parts_section['entry_offsets']):
                if _is_pinned_hub and (fname, pi) not in V3_BOSS_TIER_PINNED_SLOTS:
                    continue
                try:
                    midx = struct.unpack_from('<i', data,
                                              po + PART_OFF_MODEL_INDEX)[0]
                    raw_name = midx_to_cp_full.get(midx, '')
                    src_cp = raw_name.split('_')[0]
                    if not (src_cp.startswith('c') and src_cp[1:].isdigit()):
                        continue
                    npc = struct.unpack_from('<I', data,
                                             po + PART_OFF_NPC_PARAM)[0]
                    # position
                    if po + PART_OFF_POSITION + 12 <= len(data):
                        x, y, z = struct.unpack_from('<fff', data,
                                                      po + PART_OFF_POSITION)
                        pos = (round(x, 2), round(y, 2), round(z, 2))
                    else:
                        pos = None
                    slot_info = {
                        'msb': fname,
                        'pi': pi,
                        'source_cp': src_cp,
                        'source_npc': npc,
                        'source_variant_name': None,
                        'position': pos,
                        'cluster_id': None,  # v0.26.13: cluster system removed
                    }
                    slots.append(slot_info)
                except Exception:
                    continue
        except Exception:
            continue
    return slots


def _populate_variant_names(slots, prefix_variants):
    """Fill in source_variant_name for each slot by matching source_npc
    to the prefix_variants table. Mutates slots in place."""
    for s in slots:
        cp = s['source_cp']
        npc = s['source_npc']
        for v in prefix_variants.get(cp, []):
            if v.get('npc_param_id') == npc:
                s['source_variant_name'] = v.get('variant_name')
                break


def _compute_unique_reservations(input_dir, tags, prefix_variants, rng,
                                   already_placed_counts=None,
                                   run_ctx=None, inventory=None):
    """Pre-pass: pick reservations for every c-prefix in
    V3_UNIQUE_TARGET_CAPS. Body extracted to
    engine.reservations.compute_unique_reservations in v0.28.x — see
    that module's docstring for the full rationale.

    The shim passes `globals()` as the namespace dict so the engine
    function reads the four V3_* gate sets, the three per-run _V3_*
    log/counter dicts (legacy path; modern callers pass run_ctx),
    and the five helper functions (_enumerate_unique_candidate_slots,
    _load_variant_groups, _populate_variant_names,
    _score_slot_for_unique, _tile_xy) from THIS module's state.

    Mutation propagates: when run_ctx is None, the engine function
    aliases the _V3_* dicts into local names and mutates through
    those aliases. The dict objects are shared with this module's
    globals, so module-level _V3_UNIQUE_RESERVATIONS /
    _V3_UNIQUE_PLACED_COUNTS / _V3_UNIQUE_UNPLACED_LOG see the
    reservations exactly as before extraction.
    """
    from engine.reservations import compute_unique_reservations as _impl
    return _impl(
        globals(), input_dir, tags, prefix_variants, rng,
        already_placed_counts=already_placed_counts,
        run_ctx=run_ctx, inventory=inventory,
    )



def _choose_with_budget(chosen_pool, resident, budget, picker):
    """v0.28 hybrid pick: introduce fresh (new-to-tile) variety up to the
    per-MSB distinct budget, then recycle assets already resident on the
    tile (zero extra chrbnd load) instead of reverting to vanilla.

      chosen_pool : already shape-gated + global-block-filtered candidates.
      resident    : c-prefixes already committed in this MSB.
      budget      : max distinct c-prefixes this MSB may load (vanilla count).
      picker      : callable(sorted_seq) -> elem. The per-slot hashed RNG,
                    so the choice stays a pure function of slot identity.

    Returns (cp, kind) with kind in {'fresh','recycle','overflow'}, or
    (None, None) if nothing is placeable (slot stays vanilla).

    Pure — no globals, no mutation — so simulate_engine.py can import and
    share it verbatim and engine/simulator parity holds. With an empty
    resident and an unbounded budget this is exactly the plain hashed pick
    over sorted(chosen_pool), i.e. identical to the pre-v0.28 picker.
    """
    if not chosen_pool:
        return None, None
    fresh = [cp for cp in chosen_pool if cp not in resident]
    recyc = [cp for cp in chosen_pool if cp in resident]
    if len(resident) < budget and fresh:
        return picker(sorted(fresh)), 'fresh'        # variety while under budget
    if recyc:
        return picker(sorted(recyc)), 'recycle'      # budget hit -> reuse resident (free load)
    if fresh:
        # Budget hit but nothing resident fits this slot's shape (e.g. a
        # flier slot in an all-ground tile). One fresh distinct beats a
        # broken/vanilla slot, and vanilla would usually add load here too.
        return picker(sorted(fresh)), 'overflow'
    return None, None


def pick_target_cp(recipient_cp, tags,
                    prefix_variants, prefix_count, recipient_is_boss, rng,
                    target_count=None,
                    slot_y=None,
                    slot_msb_name=None, slot_pi=None, slot_variant_name=None,
                    slot_pos=None,
                    slot_eid=None,
                    slot_require_boss_reward=False,
                    disable_resilient_filter=False,
                    non_fragile_baseline_cp=None,
                    diagnostic_test_targets=None,
                    chaos_mode=False,
                    gates=None,
                    run_ctx=None):
    """Pick a target c-prefix for a swap slot. Body extracted to
    engine.picker.pick_target_cp in v0.28.x — see that module's
    docstring for the full gate cascade rationale.

    The shim passes `globals()` as the namespace dict so the engine
    function reads all 42 V3_* gate sets, the 2 _V3_* mutable state
    dicts, and the 8 helpers (5 underscore internals + 3 public
    functions) from THIS module's state. The engine function calls
    engine.rejection.reject_target_for_slot directly inside its
    gate cascade — no shim hop on the hot path.
    """
    from engine.picker import pick_target_cp as _impl
    return _impl(
        globals(), recipient_cp, tags,
        prefix_variants, prefix_count, recipient_is_boss, rng,
        target_count=target_count,
        slot_y=slot_y,
        slot_msb_name=slot_msb_name, slot_pi=slot_pi,
        slot_variant_name=slot_variant_name,
        slot_pos=slot_pos,
        slot_eid=slot_eid,
        slot_require_boss_reward=slot_require_boss_reward,
        disable_resilient_filter=disable_resilient_filter,
        non_fragile_baseline_cp=non_fragile_baseline_cp,
        diagnostic_test_targets=diagnostic_test_targets,
        chaos_mode=chaos_mode,
        gates=gates,
        run_ctx=run_ctx,
    )




def _variant_name(cp, npc_param_id, prefix_variants):
    """Look up the human-readable variant name for a (c_prefix, npc_param_id) pair."""
    if cp not in prefix_variants: return cp
    for v in prefix_variants[cp]:
        if v.get('npc_param_id') == npc_param_id:
            return v.get('variant_name', cp)
    return cp


def _log_unaccounted(reason, msb_basename, pi, cur_cp, npc,
                     data, po, prefix_variants):
    """v0.20.19: append an entry to the unaccounted-vanilla log.

    Reads position + entity_id from the MSB Part record, defensively. Used
    by the five no-swap leak paths in the main loop. Don't call this for
    deliberately-vanilla cases (excludes / heuristic-skips / cluster-vanilla-
    by-config) — that pollutes the bug-detection signal."""
    eid = (struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0]
           if po + PART_OFF_ENTITY_ID + 4 <= len(data) else None)
    pos = None
    if po + 0x400 + 12 <= len(data):
        try:
            x, y, z = struct.unpack_from('<fff', data, po + 0x400)
            if not (x != x or y != y or z != z):  # NaN check without math import
                pos = [round(x, 2), round(y, 2), round(z, 2)]
        except struct.error:
            pass
    _V3_UNACCOUNTED_VANILLA_LOG.append({
        'map':           msb_basename,
        'part_index':    pi,
        'entity_id':     eid,
        'position':      pos,
        'c_prefix':      cur_cp,
        'npc_param_id':  npc,
        'name':          _variant_name(cur_cp, npc, prefix_variants),
        'reason':        reason,
    })


def _emit_msb_part_inventory_trace(data, parts_section, midx_to_cp, msb_base):
    """v0.23.52: full MSB Part inventory diagnostic. Logs EVERY Part of
    the given MSB (including npc=0 placeholders and source-excluded
    preservations) to the trace buffer.

    Used in both shuffle_msb_v3 (when the MSB is shuffled normally) and
    in the passthrough path of rando_pipeline (so hub MSBs can also
    surface their internals — useful for identifying boss-tier interior
    pi indices when V3_BOSS_TIER_PINNED_SLOTS doesn't yet contain
    entries for that hub).

    Resolves "where the hell is BBH in this MSB" questions without
    needing Oodle for offline DCX decompression. Caller must check
    V3_DIAGNOSTIC_INVENTORY_MSBS membership before calling — the helper
    unconditionally emits a trace event."""
    inventory = []
    for _pi, _po in enumerate(parts_section['entry_offsets']):
        try:
            _npc = struct.unpack_from('<I', data, _po + PART_OFF_NPC_PARAM)[0]
            _midx = struct.unpack_from('<i', data, _po + PART_OFF_MODEL_INDEX)[0]
            _cp = midx_to_cp.get(_midx, '?')
            _eid = struct.unpack_from('<i', data, _po + PART_OFF_ENTITY_ID)[0]
            _pos = None
            try:
                _x, _y, _z = struct.unpack_from('<fff', data, _po + PART_OFF_POSITION)
                if not (_x != _x or _y != _y or _z != _z):
                    _pos = [round(_x, 2), round(_y, 2), round(_z, 2)]
            except struct.error:
                pass
            inventory.append({
                'pi': _pi, 'cp': _cp, 'npc': _npc, 'eid': _eid, 'pos': _pos,
            })
        except struct.error:
            pass
    _V3_TRACE_BUFFER.append({
        'event': 'MSB_PART_INVENTORY',
        'msb': msb_base,
        'n_parts': len(inventory),
        'parts': inventory,
    })


def shuffle_msb_v3(input_path, output_path, rng, tags, prefix_variants, prefix_count,
                    spoiler_entries=None, oops_all_target_cp=None,
                    target_count=None,
                    merchant_model_swap=False,
                    terrain_test_targets=None,
                    disable_resilient_filter=False,
                    non_fragile_baseline_cp=None,
                    diagnostic_test_targets=None,
                    chaos_mode=False,
                    mount_rider_swap=False,
                    oops_all_nb_target_cp=None,
                    oops_all_nb_marker_scope=None,
                    oops_all_nb_pinned_slot=None,
                    pinned_only_in_hub=False,
                    gates=None,
                    run_ctx=None):
    """Per-MSB shuffle driver. Body extracted to
    engine.shuffler.shuffle_msb_v3 in v0.28.x — see that module's
    docstring for the per-MSB pipeline rationale and the call into
    engine.picker via pick_target.

    The shim passes `globals()` as the namespace dict so the engine
    function reads all 28 V3_* gate sets, the 4 _V3_* read-only
    state references, and the 31 helper / module-level functions
    from THIS module's state. No flush needed — shuffle_msb_v3
    declares no globals (per-run state goes through run_ctx or the
    spoiler_entries list).
    """
    from engine.shuffler import shuffle_msb_v3 as _impl
    return _impl(
        globals(), input_path, output_path, rng, tags, prefix_variants,
        prefix_count,
        spoiler_entries=spoiler_entries,
        oops_all_target_cp=oops_all_target_cp,
        target_count=target_count,
        merchant_model_swap=merchant_model_swap,
        terrain_test_targets=terrain_test_targets,
        disable_resilient_filter=disable_resilient_filter,
        non_fragile_baseline_cp=non_fragile_baseline_cp,
        diagnostic_test_targets=diagnostic_test_targets,
        chaos_mode=chaos_mode,
        mount_rider_swap=mount_rider_swap,
        oops_all_nb_target_cp=oops_all_nb_target_cp,
        oops_all_nb_marker_scope=oops_all_nb_marker_scope,
        oops_all_nb_pinned_slot=oops_all_nb_pinned_slot,
        pinned_only_in_hub=pinned_only_in_hub,
        gates=gates,
        run_ctx=run_ctx,
    )



# =============================================================================
# Merchant model swap (v0.12)
# =============================================================================
# The merchants in Limveld (Nomadic Merchant c3200, Small Jar Merchant c4491)
# stand in fixed positions across the overworld. Their NPCParam configures
# the dialogue/shop interaction; their MODEL_INDEX determines what they
# look like.
#
# This post-pass swaps ONLY the MODEL_INDEX of merchant Parts, leaving
# NPCParam/ThinkParam intact. The merchant continues to function as a
# merchant (same shop, same dialogue) but visually appears as a different
# enemy. Doing it as a separate pass — distinct from the main rando —
# avoids the previous regression where merchants got their NPCParam
# swapped and turned into hostile enemies (or where enemy slots got the
# merchant's NPCParam and stopped fighting).
#
# Identified by NPCParam ID rather than c-prefix, since we want to be
# absolutely sure we're targeting actual merchant entities (not some
# other Part that happens to use the c3200 model).
V3_MERCHANT_NPC_PARAMS = {
    32000000,  # Nomadic Merchant
    44910000,  # Small Jar Merchant
}

V3_MERCHANT_MODEL_POOL = {
    # Curated visual alternatives for merchants. Picked for variety
    # plus "this would be funny as a merchant" energy. Sizes vary —
    # merchants are stationary so small/large doesn't break gameplay,
    # though some collision overlap is possible at the merchant's
    # podium/area.
    #
    # Knight family (armored merchants):
    'c3010',  # Banished Knight
    'c4290',  # Bloodhound Knight
    'c4351',  # Godrick Knight
    'c4353',  # Leyndell Knight (Encampment)
    'c4354',  # Redmane Knight (Encampment)
    'c4355',  # Mausoleum Knight
    # Soldier family:
    'c4313',  # Leyndell Soldier
    'c4314',  # Radahn Soldier
    'c4377',  # Highwayman (bandit-merchant — fitting)
    'c4321',  # Vulgar Militia
    # Boss-y characters as merchants:
    'c2140',  # Omen
    'c2500',  # Crucible Knight (Unscaled)
    'c3100',  # Elemer of the Briar
    'c4750',  # Godrick the Grafted (huge — would be hilarious)
    'c3950',  # Man-Serpent
    'c4570',  # Wormface
    'c5070',  # Death Knight
    # Beast-like characters:
    'c4101',  # Large Demi-Human
    'c4120',  # Demi-Human Chief
    'c4340',  # Mad Pumpkin Head
    'c4341',  # Thin Mad Pumpkin Head
    # Undead / weird:
    'c3060',  # Giant Skeleton
    'c3500',  # Large Skeleton
    'c3661',  # Putrid Corpse
    'c3470',  # Albinauric (smaller, sedentary — fits crouching merchant)
    # Robed/cultish:
    'c3700',  # Depraved Perfumer
    'c3701',  # Perfumer
    'c3702',  # Glintstone Sorcerer
    'c3703',  # Page
    'c3704',  # Battlemage
    'c3900',  # Fire Monk
    'c3901',  # Fire Monk variant
    # DLC additions:
    'c5160',  # Fire Knight
    'c5870',  # Imp (Lion Head)
    'c5900',  # Man-Fly (creepy little merchant)
    'c5040',  # Curseblade
    'c5250',  # Horned Warrior

    # v0.23.74: expansion sweep against the merged tag set (heritage +
    # post_dlc_dump + mmv_import). Last update predated several import
    # rounds; the new merchant candidates below preserve the "funny as a
    # merchant" curation energy with named-boss humanoids, additional
    # robed/cultish family members, and a few sedentary undead/jar chrs
    # whose vanilla pose lends itself to standing-at-a-podium framing.
    #
    # v0.24.75 RESTRICTED: ALL non-vanilla merchant candidates below are
    # commented out until MMV-asset-deploy reliability is nailed down.
    # User report seed 454841 v0.24.74 CTD'd mid-Day-2 exploration with
    # null-pointer-plus-offset deref pattern (0x...0024). Root cause:
    # the merchant pool was selecting MMV chrs (c1310 Outrider Knight,
    # c5030 Romina, c6200 Gael, c5300 Rellana, etc.) at Limveld merchant
    # slots, but the user's MMV asset deploy was incomplete — the chr
    # had a model-pool entry but no chrbnd on disk to render. When the
    # player approached the merchant's Limveld tile, the engine streamed
    # in the Part with a null chrbnd pointer and CTD'd on field-offset
    # access.
    #
    # The merchant-trick code path doesn't go through the same chr-asset
    # validation as the main shuffle (it only rewrites MODEL_INDEX, not
    # NPCParam/ThinkParam), so the diagnose tool's missing-chr check
    # caught the placement but the rando still wrote it. Easiest defense
    # is to restrict the merchant pool to chrs that ship with vanilla
    # NR — those are guaranteed to load regardless of MMV/heritage state.
    #
    # To restore: uncomment the lines below once MMV asset deployment is
    # reliable enough to guarantee these chrbnds are always present
    # (probably needs a runtime check at apply_merchant_model_swaps that
    # verifies the chrbnd exists in the user's me3 profile before
    # selecting). Reference: v0.24.75 release notes for context.

    # Heritage-pack additions (Knight family) — DISABLED v0.24.75:
    # 'c3800',  # Cleanrot Knight — Malenia's knight as a wandering merchant
    # Heritage-pack additions (Robed/cultish + Undead) — DISABLED v0.24.75:
    # 'c3510',  # Skeleton (Sword and Shield) — undead vendor
    # 'c3070',  # Dominula Celebrant — ritualistic merchant vibes
    # 'c3750',  # Clayman - Spear — sedentary clay-vendor
    # 'c3860',  # Avionette — small humanoid, podium-friendly
    # 'c4385',  # Disciple of Rot — cultish merchant
    # 'c4820',  # Omenkiller — alaric's emergent castle-basement variant;
    #           # red-eye speffect inheritance was a delightful side-effect

    # Manual-tag additions (Scholar Remembrance variants) — DISABLED v0.24.75:
    # 'c4352',  # Cuckoo Knight (Scholar Remembrance) — armored merchant

    # post_dlc_dump additions (NR-DLC era) — DISABLED v0.24.75:
    # 'c5081',  # Chief Bloodfiend — miniboss humanoid
    # 'c5320',  # Fat Inquisitor — squat, threatening, ideal merchant vibe
    # 'c5651',  # Messmer Foot Soldier — DLC soldier
    # 'c7720',  # Knight Artorias — iconic DS1 hero as a wandering merchant

    # MMV-import additions (cross-game cameos) — DISABLED v0.24.75:
    # 'c1310',  # Outrider Knight (DS3) — armored merchant
    # 'c2030',  # Rennala, Queen of the Full Moon — sitting cross-legged
    #           # vendor would be incredibly on-brand for her
    # 'c4720',  # Godfrey, First Elden Lord — Elden Lord selling potions
    # 'c4721',  # Hoarah Loux — bare-knuckle merchant
    # 'c5030',  # Romina, Saint of the Bud — DLC nightlord-tier. AI-broken
    #           # but model-safe — bypasses V3_EXCLUDE_TARGET_PREFIXES via
    #           # V3_MERCHANT_MODEL_AI_BROKEN_OK. See that set's comment.
    # 'c5130',  # Messmer the Impaler
    # 'c5300',  # Rellana, Twin Moon Knight
    # 'c5740',  # Kindred of Rot (MMV variant)
    # 'c5840',  # Black Knight (DS1) — armored merchant, iconic
    # 'c5880',  # Catacombs Sorcerer — robed cultish
    # 'c6200',  # Slave Knight Gael (DS3) — "selling you the dark soul"
    #           # energy; comedy gold
    # 'c6210',  # Corvian Knight (DS3) — armored merchant
    # 'c8300',  # Dragonslayer Armor (DS3) — armored hulk as merchant

    # Candidates considered but DEFERRED — flag for next playtest pass:
    #   c2110 Maliketh — too iconic / size+animation may not seat right
    #   c2120 Malenia — same; her seated cross-legged is in cutscene only
    #   c2130 Margit — fits but already overrepresented at boss slots;
    #                  let the world-side variety hold for one more cycle
    #   c4620 Astel — giga_boss, would overflow merchant podium geometry
    #   c5081 / c5080 Bloodfiend family — already covered via c5081
    #   c4961 Giant Skeleton Torso — torso-only, weird visual presentation
    #
    # v0.24.88-patch10 follow-up: the six chrs previously listed here as
    # "pending playtest confirmation" while in the speculative ghost-
    # exclude set are NO LONGER ghost-excluded. They're now eligible
    # for normal swap target placement. They do NOT need to be in
    # V3_MERCHANT_MODEL_AI_BROKEN_OK either — that set is specifically
    # for chrs whose AI is broken at combat slots but model loads fine
    # at merchant slots. These six are presumed-OK on both axes; the
    # ghost-exclude was speculation based on shape/vibe, not AI failure.
    #
    # If a future playtest reveals one of them DOES freeze in combat,
    # the right move is to add it BACK to V3_GHOST_EXCLUDE_TARGET_PREFIXES
    # with empirical evidence (seed, msb, pi), and THEN decide if it's
    # AI-driven enough to also belong here. Promoting them here
    # preemptively would re-create the same speculative-classification
    # problem.
    #
    # Former deferred-promotion list (kept for archaeology):
    #   c5240 Commoner (Pot), c5241 Commoner
    #   c5311 Inquisitor (Candles), c5312 Inquisitor (Staff)
    #   c5750 Living Jar Warrior, c5751 Living Jar
}


# v0.23.74: chrs that are in V3_EXCLUDE_TARGET_PREFIXES for AI/tick
# reasons but whose MODEL itself loads fine. Subtracted from the merchant
# filter at apply_merchant_model_swaps (see that function's
# active_excludes comment) so they remain usable as cosmetic merchant
# skins. The merchant code path does not modify NPCParam or ThinkParam,
# so the AI logic that CTDs these chrs at normal placement slots never
# runs at merchant slots.
#
# To add an entry: confirm via playtest that the CTD is AI-driven (e.g.
# per-tick speffect, transformation script, encounter-spawn handler)
# rather than model/asset (missing render data, malformed mesh, missing
# heritage pack file). Only AI-driven exclusions belong here.
V3_MERCHANT_MODEL_AI_BROKEN_OK = {
    'c5030',  # Romina, Saint of the Bud — AI CTD is the scarlet-rot
              # transformation FX (per-tick speffect chain). At a
              # merchant slot she just stands there as a skin, no FX
              # script fires. User-confirmed playtest-safe v0.23.74.
}


def apply_merchant_model_swaps(data, rng, spoiler_entries=None,
                                 map_name=None, gates=None):
    """Swap MODEL_INDEX of merchant Parts to random pool members.

    Operates on already-shuffled MSB data. Does NOT modify NPCParam or
    ThinkParam, so the merchant's interaction behavior is preserved —
    only the visual model changes.

    v0.24.21: optional `gates` parameter. When None (default), reads
    V3_GHOST_EXCLUDE_TARGET_PREFIXES and V3_EXCLUDE_TARGET_PREFIXES
    from the module — preserves all pre-existing call sites verbatim.
    When a GateState is passed, reads ghost_exclude_target_prefixes
    and exclude_target_prefixes from the snapshot. Useful so that
    callers inside cmd_shuffle_v3's apply_run_overrides scope can
    pass the effective in-scope state explicitly rather than relying
    on the module-globals-are-mutated invariant.

    Returns (new_data, n_swapped).
    """
    sections = parse_msb_sections(data)
    if len(sections) != 6:
        return data, 0

    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]
    midx_to_cp = {gi: parse_model_entry(data, eo)['name']
                  for gi, eo in enumerate(models['entry_offsets'])}

    # Find merchant Parts (NPCParam in V3_MERCHANT_NPC_PARAMS AND
    # currently using a known merchant model)
    merchant_parts = []
    for pi, po in enumerate(parts['entry_offsets']):
        npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0]
        if npc not in V3_MERCHANT_NPC_PARAMS:
            continue
        midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        cur_cp = midx_to_cp.get(midx, '?').split('_')[0]
        if cur_cp not in ('c3200', 'c4491'):
            # NPCParam matches but model doesn't — preserve as-is to be safe
            continue
        merchant_parts.append((pi, po, midx, cur_cp, npc))

    if not merchant_parts:
        return data, 0

    # For each merchant, pick a new model and rewrite MODEL_INDEX
    out = bytearray(data)
    # v0.23.10.2: filter merchant pool against active runtime excludes.
    # Without this, V3_MERCHANT_MODEL_POOL members that are also in the
    # ghost-exclude / target-exclude sets (e.g. heritage prefixes when
    # multiplayer_safe is ON) leak through this code path even though
    # the main pool blocks them. Heritage chrs that aren't on the user's
    # disk → CTD when player approaches the merchant.
    # active_excludes ↓ filters the merchant pool against:
    # (a) ghost-pack target excludes — heritage chrs that aren't on the
    #     user's disk → CTD when the player approaches the merchant (the
    #     MODEL needs to render even though the chr is AI-inert), AND
    # (b) general target excludes — chrs whose model itself is broken
    #     (missing assets, malformed render data), e.g. c4511 Lichdragon
    #     Fortissax "CTD before map loads".
    #
    # v0.23.74: subtract V3_MERCHANT_MODEL_AI_BROKEN_OK from the filter
    # so chrs that are target-excluded for AI/tick reasons (but whose
    # model loads fine) can still be merchant skins. The merchant code
    # path does NOT modify NPCParam or ThinkParam, so the AI logic that
    # CTDs these chrs in normal placements never runs at merchant slots.
    # c5030 Romina is the first such case (her CTD is the scarlet-rot
    # transformation FX, which is AI-driven — at a merchant slot she
    # just stands there as a skin).
    if gates is None:
        ghost_excludes = V3_GHOST_EXCLUDE_TARGET_PREFIXES
        target_excludes = V3_EXCLUDE_TARGET_PREFIXES
    else:
        ghost_excludes = gates.ghost_exclude_target_prefixes
        target_excludes = gates.exclude_target_prefixes
    active_excludes = ((set(ghost_excludes) | set(target_excludes))
                       - V3_MERCHANT_MODEL_AI_BROKEN_OK)
    pool_filtered = [cp for cp in V3_MERCHANT_MODEL_POOL
                     if cp not in active_excludes]
    pool_sorted = sorted(pool_filtered)  # deterministic order for rng
    if not pool_sorted:
        # Pool collapsed to empty — bail rather than crash. Should never
        # happen unless excludes are pathologically broad.
        return bytes(out), 0
    n_swapped = 0
    for pi, po, old_midx, old_cp, npc in merchant_parts:
        new_cp = rng.choice(pool_sorted)

        # Add model to MSB if not already present, get target index
        new_data, new_midx = find_or_add_model(bytes(out), new_cp, model_type=2)
        out = bytearray(new_data)
        # After find_or_add_model, parts/models offsets may have shifted if
        # a model was added. Re-parse to get fresh offsets.
        sections2 = parse_msb_sections(bytes(out))
        parts2 = next(s for s in sections2 if s['name'] == 'PARTS_PARAM_ST')
        models2 = sections2[0]
        po2 = parts2['entry_offsets'][pi]

        # Capture spoiler info
        if spoiler_entries is not None:
            position = None
            if po2 + 0x400 + 12 <= len(out):
                x, y, z = struct.unpack_from('<fff', bytes(out), po2 + 0x400)
                import math
                if not (math.isnan(x) or math.isnan(y) or math.isnan(z)):
                    position = [round(x, 2), round(y, 2), round(z, 2)]
            spoiler_entries.append({
                'map': map_name or '?',
                'part_index': pi,
                'kind': 'merchant_model_swap',
                'cluster_id': None,
                'is_boss': False,
                'position': position,
                'entity_id': None,
                'original': {'c_prefix': old_cp,
                             'name': 'Merchant (model)',
                             'npc_param_id': npc},
                'new':      {'c_prefix': new_cp,
                             'name': f'{new_cp} (still merchant — model only)',
                             'npc_param_id': npc},  # unchanged!
            })

        # Write only MODEL_INDEX (NPCParam/ThinkParam untouched)
        struct.pack_into('<i', out, po2 + PART_OFF_MODEL_INDEX, new_midx)
        # Update instance counts for old + new model entries
        old_e = models2['entry_offsets'][old_midx]
        new_e = models2['entry_offsets'][new_midx]
        c_old = struct.unpack_from('<i', out, old_e + 0x18)[0]
        struct.pack_into('<i', out, old_e + 0x18, max(0, c_old - 1))
        c_new = struct.unpack_from('<i', out, new_e + 0x18)[0]
        struct.pack_into('<i', out, new_e + 0x18, c_new + 1)
        n_swapped += 1

    return bytes(out), n_swapped


def cmd_shuffle_v3(input_dir, output_dir, seed,
                    oops_all_target_cp=None,
                    merchant_model_swap=False,
                    terrain_test_targets=None,
                    excluded_prefixes=None,
                    hub_maps=None,
                    multiplayer_safe=False,
                    disable_resilient_filter=False,
                    non_fragile_baseline_cp=None,
                    diagnostic_test_targets=None,
                    force_include_targets=None,
                    chaos_mode=False,
                    mount_rider_swap=False,
                    sote_mode=False,
                    oops_all_nb_target_cp=None,
                    oops_all_nb_marker_scope=None,
                    oops_all_nb_pinned_slot=None,
                    unique_cap_overrides=None,
                    caliber_pool_extras=None,
                    caliber_pool_removals=None,
                    field_upgrade_miniboss_pct=None,
                    field_upgrade_fieldboss_pct=None,
                    field_upgrade_nightboss_pct=None,
                    fieldboss_to_nightboss_promote_pct=None):
    """v0.20.27: excluded_prefixes / hub_maps / multiplayer_safe moved
    engine-side. Previously the GUI mutated module-level V3_* sets
    directly with a save-and-restore wrapper, which leaked state on
    mid-run exceptions and gave non-GUI callers (CLI, tests, scripts)
    no clean way to apply user-level overrides.

      excluded_prefixes: None → use V3_EXCLUDE_PREFIXES module default.
                        set → use that set as the hard-block source/target
                              exclude set for this run only. Sanitized
                              against V3_EXCLUDE_SOURCE_PREFIXES so
                              source-only entries don't leak into the
                              hard-block set (the v0.20.5 bug).
      hub_maps:         None → use V3_HUB_MAPS module default.
                        set → use that set as hub-passthrough MSB names
                              for this run only.
      multiplayer_safe: if True, the full V3_MP_SAFE_BLOCKLIST set
                        is unioned into the active ghost-exclude pool
                        for this run, blocking non-vanilla chrs from
                        being placed as swap targets so coop partners
                        without the matching mod packs don't CTD on
                        cell-load. v0.24.20: derived from `_source`
                        tagging (allow-list approach), supersedes the
                        old hand-curated V3_HERITAGE_ALL_PREFIXES gate.
      chaos_mode:       v0.23.11. Asymmetric tier mixing.
                        Default False (each tier stays in its lane).
                        True ⇒ true Night Boss chrs (V3_NIGHT_BOSS_ONLY_TARGETS)
                        become eligible at field-boss / overworld slots, AND
                        Night Boss anchor slots tighten from CALIBER (broad)
                        to NIGHT_BOSS_ONLY (strict). Result: NB chrs leak
                        DOWN into the world; field-tier giants (Trolls,
                        Runebears) can no longer leak UP into NB anchor
                        slots — preserving the climactic NB-arena moments
                        while opening the rest of the world to boss-tier
                        surprises (Maliketh wandering Limveld, etc).

    All four apply only for the duration of this call — module-level
    sets are NOT mutated permanently.
    """
    # v0.19.21: clear any stale cancel state from a previous run before
    # we begin. The GUI/CLI may have accidentally re-entered with an
    # event still set from a cancelled prior attempt.
    clear_cancel_request()

    # v0.20.27: per-run application of caller-supplied overrides for
    # excluded_prefixes / hub_maps / multiplayer_safe. Saves the
    # module-level defaults, swaps in the run-specific values, and
    # restores in a finally at the end of the run. This replaces the
    # earlier pattern where the GUI directly mutated oops_v3.V3_*
    # before each call — non-GUI callers (CLI, tests) had no clean
    # way to apply these overrides, and the GUI's save-and-restore
    # leaked state if the engine raised mid-run.
    #
    # v0.24.21: lifted into engine.runtime.apply_run_overrides — see
    # that file for the composition rules (sanitize / union /
    # subtract / ordering) and the atomic save/restore semantics. The
    # per-run state mutations now live in one place instead of being
    # spread across save lines, apply blocks, and restore lines here.
    if disable_resilient_filter:
        print("*** DIAGNOSTIC MODE: disable_resilient_filter=True ***")
        print("*** Fragile slots will use UNTESTED-only filter ***")
        print("*** (pool - RESILIENT - SENSITIVE = candidates for new test data). ***")
        print("*** Expect new freezes — this run is for capturing them. ***")
    if non_fragile_baseline_cp:
        print(f"*** DIAGNOSTIC MODE: non_fragile_baseline_cp={non_fragile_baseline_cp} ***")
        print(f"*** Non-fragile slots forced to {non_fragile_baseline_cp} — anything else ***")
        print("*** visible in the world is a fragile-slot test. ***")
    if diagnostic_test_targets:
        print(f"*** DIAGNOSTIC BATCH: diagnostic_test_targets={sorted(diagnostic_test_targets)} ***")
        print(f"*** Fragile slots restricted to {len(diagnostic_test_targets)} explicit ***")
        print("*** c-prefixes for batch CTD attribution. ***")
    if chaos_mode:
        print("*** CHAOS MODE: Night Boss chrs eligible at field-boss slots ***")
        print("*** AND Night Boss anchor slots restricted to true NBs only ***")
        print("*** (asymmetric flow — NB chrs leak DOWN, field bosses can't leak UP). ***")
    # v0.24.30: hoist load_data() so V3_MP_SAFE_BLOCKLIST (and the other
    # lazily-populated module globals — V3_EXCLUDE_TARGET_PREFIXES extensions,
    # V3_ARENA_ONLY_TARGETS auto-extensions,
    # V3_STARTING_ENCAMPMENT_MSBS) are filled BEFORE apply_run_overrides
    # composes its union. The blocklist is set() at module-load and only
    # populated at the end of load_data() (this lazy init was introduced
    # in v0.24.20 when the MP-safe set was switched from the hand-curated
    # V3_HERITAGE_ALL_PREFIXES to derivation-from-_source tags). Without
    # the hoist, the very first cmd_shuffle_v3 call in a process enters
    # apply_run_overrides with an empty blocklist, the multiplayer_safe
    # union becomes saved_ghost (7) ∪ ∅ = 7, and the gate silently no-ops.
    # _cmd_shuffle_v3_impl below calls load_data() a second time —
    # idempotent, rebuilds from the same data files, ~70ms cost on the dev
    # box (negligible relative to a full shuffle run).
    #
    # In-the-wild manifestation: seed 149569 (v0.24.27 spoiler). The
    # EXCLUDE_SNAPSHOT_AT_RUN_START trace recorded
    # V3_GHOST_EXCLUDE_TARGET_PREFIXES count=7 with multiplayer_safe=True
    # (should have been 7+149=156). Resulting spoiler placed 24
    # cross-engine c-prefixes (c7000/c7650/c7710-c7930/c7810/c8300/c1310)
    # at Noklateo Limveld tiles (m60_xx_xx_50.msb), and the user reported
    # a CTD on the Noklateo fly-in — the fly-in's wider asset preload trips
    # on a cross-engine chr that MP-safe was supposed to have blocked.
    #
    # Regression test: tests/test_runtime.py::TestMpSafeBlocklistHoist
    # which clears the blocklist, invokes cmd_shuffle_v3 with a captured
    # impl, and asserts the picker would have seen the populated union.
    load_data()
    # v0.27.21: per-run V3_SOTE_MODE application. Set the module global so
    # pick_target_cp's SOTE intersection (and the cap/floor bypass) is
    # active for this run, then restore it in finally so the flag never
    # leaks into a subsequent in-process run (GUI, test suite, batch CLI).
    # Mirrors the save/restore discipline apply_run_overrides uses for the
    # gate sets. load_data() above has already populated V3_SOTE_PREFIXES.
    global V3_SOTE_MODE
    _saved_sote_mode = V3_SOTE_MODE
    V3_SOTE_MODE = sote_mode
    try:
        with apply_run_overrides(
                excluded_prefixes=excluded_prefixes,
                hub_maps=hub_maps,
                multiplayer_safe=multiplayer_safe,
                force_include_targets=force_include_targets,
                field_upgrade_miniboss_pct=field_upgrade_miniboss_pct,
                field_upgrade_fieldboss_pct=field_upgrade_fieldboss_pct,
                field_upgrade_nightboss_pct=field_upgrade_nightboss_pct,
                fieldboss_to_nightboss_promote_pct=fieldboss_to_nightboss_promote_pct) as effective_gates:
            return _cmd_shuffle_v3_impl(
                input_dir, output_dir, seed,
                oops_all_target_cp=oops_all_target_cp,
                merchant_model_swap=merchant_model_swap,
                terrain_test_targets=terrain_test_targets,
                multiplayer_safe=multiplayer_safe,
                disable_resilient_filter=disable_resilient_filter,
                non_fragile_baseline_cp=non_fragile_baseline_cp,
                diagnostic_test_targets=diagnostic_test_targets,
                chaos_mode=chaos_mode,
                mount_rider_swap=mount_rider_swap,
                oops_all_nb_target_cp=oops_all_nb_target_cp,
                oops_all_nb_marker_scope=oops_all_nb_marker_scope,
                oops_all_nb_pinned_slot=oops_all_nb_pinned_slot,
                unique_cap_overrides=unique_cap_overrides,
                caliber_pool_extras=caliber_pool_extras,
                caliber_pool_removals=caliber_pool_removals,
                gates=effective_gates)
    finally:
        V3_SOTE_MODE = _saved_sote_mode


def _cmd_shuffle_v3_impl(input_dir, output_dir, seed,
                          oops_all_target_cp=None,
                          merchant_model_swap=False,
                          terrain_test_targets=None,
                          multiplayer_safe=False,
                          disable_resilient_filter=False,
                          non_fragile_baseline_cp=None,
                          diagnostic_test_targets=None,
                          chaos_mode=False,
                          mount_rider_swap=False,
                          oops_all_nb_target_cp=None,
                          oops_all_nb_marker_scope=None,
                          oops_all_nb_pinned_slot=None,
                          unique_cap_overrides=None,
                          caliber_pool_extras=None,
                          caliber_pool_removals=None,
                          gates=None,
                          run_ctx=None):
    """Per-run shuffle orchestrator. Body extracted to
    engine.cmd_shuffle.cmd_shuffle_v3_impl in v0.28.x.

    The shim passes `globals()` so the engine function reads
    V3_* state and helpers from THIS module and flushes the
    two per-run globals (_V3_RUN_SEED, _V3_TRACE_BUFFER) back
    via ns['X'] = X.
    """
    from engine.cmd_shuffle import cmd_shuffle_v3_impl as _impl
    # Build the kwargs dict by capturing locals at call entry,
    # minus the function name itself.
    import inspect
    _sig = inspect.signature(_cmd_shuffle_v3_impl)
    _kwargs = {n: locals()[n] for n in _sig.parameters}
    return _impl(globals(), **_kwargs)


# ===================================================================
# Seed CTD-risk checker (v0.27.34)
# ===================================================================
# Post-generation static audit of a fully-built seed's spoiler_entries,
# flagging placements that match known crash/freeze signatures. Runs on
# EVERY seed (called from cmd_shuffle_v3 right before the spoilers are
# written) so a risky placement is surfaced at generation time, not
# discovered in-game.
#
# This is intentionally a registry of independent checks so more can be
# added without touching the call site. Each check is a function
#   check(entries, tags) -> list[finding]
# where a finding is a dict with at minimum:
#   {'check': <str id>, 'severity': 'ctd'|'warn', 'map', 'part_index',
#    'entity_id', 'detail': <human string>}
# run_seed_ctd_checks() runs them all and returns the concatenated list.
#
# CHECK #1 — mount_target_at_non_mount_source
#   A mount-role chr (V3_MOUNT_PREFIXES — the horses c4060/c5890) placed
#   into a slot whose vanilla occupant was NOT itself a mount. A riderless
#   mount has no standalone AI brain: it spawns frozen / floats in place
#   (see the c3160/c3180 mount-exclusion rationale near line 463). The
#   rider/mount pool feature is supposed to keep mounts landing only on
#   other mount slots; a mount at a non-mount source means that invariant
#   broke for this seed and the placement is a freeze risk.

def _ctd_check_mount_target_at_non_mount_source(entries, tags):
    findings = []
    mounts = V3_MOUNT_PREFIXES  # live set, tracks tag edits
    if not mounts:
        return findings
    for e in entries:
        new = e.get('new') or {}
        orig = e.get('original') or {}
        new_cp = new.get('c_prefix')
        orig_cp = orig.get('c_prefix')
        if new_cp in mounts and orig_cp not in mounts:
            findings.append({
                'check': 'mount_target_at_non_mount_source',
                'severity': 'ctd',
                'map': e.get('map'),
                'part_index': e.get('part_index'),
                'entity_id': e.get('entity_id'),
                'detail': (f"mount-role chr {new_cp} "
                           f"({new.get('name') or '?'}) placed at non-mount "
                           f"source {orig_cp} ({orig.get('name') or '?'}); "
                           f"riderless mount has no AI — freeze/float risk"),
            })
    return findings


# Registry of active checks. Append new check fns here; the call site
# does not change.
_SEED_CTD_CHECKS = [
    _ctd_check_mount_target_at_non_mount_source,
]


def run_seed_ctd_checks(entries, tags):
    """Run every registered CTD-risk check over a seed's spoiler entries.
    Returns a flat list of finding dicts (empty if the seed is clean)."""
    findings = []
    for _check in _SEED_CTD_CHECKS:
        try:
            findings.extend(_check(entries, tags) or [])
        except Exception as _ex:  # a buggy check must never abort a build
            findings.append({
                'check': getattr(_check, '__name__', str(_check)),
                'severity': 'warn',
                'map': None, 'part_index': None, 'entity_id': None,
                'detail': f"check raised {type(_ex).__name__}: {_ex}",
            })
    return findings


def write_spoiler_logs(output_dir, entries, seed,
                        multiplayer_safe=False,
                        sote_mode=False,
                        disable_resilient_filter=False,
                        non_fragile_baseline_cp=None,
                        diagnostic_test_targets=None,
                        oops_all_nb_target_cp=None,
                        oops_all_nb_marker_scope=None,
                        oops_all_nb_pinned_slot=None):
    """Write _spoilers.json + _spoilers.md. Body extracted to
    engine.spoilers.write_spoiler_logs in v0.28.x; see that module's
    docstring for the full history.

    The shim passes `globals()` as the namespace dict so the engine
    function reads V3_* state, the six per-run `_V3_*` log/counter
    dicts, the `_data_path` helper, and the `__file__` reference all
    from THIS module's state. This keeps the spoiler archive
    directory anchored to the project root (not engine/) and works
    correctly under both normal `import oops_v3` and the
    `importlib.util.spec_from_file_location` path (dev/simulate_
    engine.py loads oops_v3 as 'o').
    """
    from engine.spoilers import write_spoiler_logs as _impl
    return _impl(
        globals(), output_dir, entries, seed,
        multiplayer_safe=multiplayer_safe,
        sote_mode=sote_mode,
        disable_resilient_filter=disable_resilient_filter,
        non_fragile_baseline_cp=non_fragile_baseline_cp,
        diagnostic_test_targets=diagnostic_test_targets,
        oops_all_nb_target_cp=oops_all_nb_target_cp,
        oops_all_nb_marker_scope=oops_all_nb_marker_scope,
        oops_all_nb_pinned_slot=oops_all_nb_pinned_slot,
    )



# v0.28.x: TODO Step 2 + 2b + 3 complete — placement_budget JSON loader.
#
# All V3_* placeholders above have been initialized as empty
# (set(), {}, 0); now read data/placement_budget.json and populate
# them. Post-Step-3 the JSON is the SOLE source of truth for the
# 9 covered sets — there is no inline-literal fallback. The empty
# placeholders exist only to make the names exist in the namespace
# before this call (so `global` declarations and module-load-time
# code like _load_missing_chr_files() don't NameError).
#
# JSON-sourced (9 of 10 sets covered by the JSON):
#   Pure-static (Step 2):
#     V3_GHOST_EXCLUDE_TARGET_PREFIXES, V3_FRAGILE_SENSITIVE_TARGETS,
#     V3_MAP_PREFIX_TARGET_EXCLUDES, V3_TARGET_PLACEMENT_CAP
#   Idempotently mutated by load_data (Step 2b):
#     V3_UNIQUE_TARGET_CAPS, V3_EXCLUDE_TARGET_PREFIXES,
#     V3_NIGHT_BOSS_STRICT_TARGETS, V3_NIGHT_BOSS_CALIBER_TARGETS,
#     V3_ARENA_ONLY_TARGETS
#
# NOT sourced (1 of 10): V3_MP_SAFE_BLOCKLIST. load_data computes it
# entirely from per-tag _source rules and wipes any pre-loaded value.
# The JSON's mp_safe_blocked field is snapshot-only.
#
# The Step 2b composition invariant: for the five idempotently-mutated
# sets, calling load_data() after this loader produces the same final
# state as calling load_data() against the pre-Step-3 inline-literal
# bases. All load_data operations on these sets are unions / item-
# assignments / set differences that compose idempotently with the
# JSON-pre-loaded post-load snapshot.
#
# Pass globals() rather than sys.modules[__name__]: under
# importlib.util.spec_from_file_location loads (e.g. dev/simulate_engine.py
# imports oops_v3 as 'o'), the module isn't registered in sys.modules
# at import-time, so the sys.modules lookup KeyErrors. globals() is the
# module's own namespace dict and is always correct.
#
# JSON is treated as MANDATORY post-Step-3: if the loader returns False
# (file missing or malformed), the engine has empty placeholders and
# every placement decision would be broken — fail loud at import time
# instead of producing subtly-broken runs.
if not _apply_placement_budget_overrides(globals()):
    raise RuntimeError(
        "data/placement_budget.json failed to load. After TODO Step 3 "
        "this file is the SOLE source of truth for editorial placement "
        "decisions (V3_UNIQUE_TARGET_CAPS, V3_EXCLUDE_TARGET_PREFIXES, "
        "V3_FRAGILE_SENSITIVE_TARGETS, V3_ARENA_ONLY_TARGETS, "
        "V3_NIGHT_BOSS_CALIBER_TARGETS, V3_NIGHT_BOSS_STRICT_TARGETS, "
        "V3_GHOST_EXCLUDE_TARGET_PREFIXES, V3_MAP_PREFIX_TARGET_EXCLUDES, "
        "V3_TARGET_PLACEMENT_CAP). Restore the file from git, or "
        "regenerate from a pre-Step-3 engine via "
        "`python3 dev/extract_placement_budget.py`. The inline V3_* "
        "definitions above are intentionally empty placeholders."
    )


if __name__ == '__main__':
    # Determinism guard: pin the process hash seed so that set/dict
    # iteration order is stable across runs. The shared seeded rng
    # consumes that order during reservation scoring (rng.random()
    # tiebreaks) and cap exhaustion, so without a fixed PYTHONHASHSEED the
    # same --seed yields a different layout every process. Re-exec once
    # with it set, before any placement work runs. (No effect under
    # `python -m`; invoke the script by path.)
    import os as _os, sys as _sys
    if _os.environ.get('PYTHONHASHSEED') != '0':
        _os.environ['PYTHONHASHSEED'] = '0'
        _os.execv(_sys.executable, [_sys.executable, *_sys.argv])
    # v0.23.72-late: snapshot subcommand. Save/inspect pool snapshots from
    # the CLI without going through cmd_shuffle_v3.
    #   oops_v3.py snapshot save <path> [--name NAME] [--description TEXT]
    #   oops_v3.py snapshot info <path>
    if len(sys.argv) >= 2 and sys.argv[1] == 'snapshot':
        if len(sys.argv) < 3:
            print("Usage:")
            print("  oops_v3.py snapshot save <path> [--name NAME] [--description TEXT]")
            print("  oops_v3.py snapshot info <path>")
            sys.exit(1)
        op = sys.argv[2]
        if op == 'save':
            if len(sys.argv) < 4:
                print("Usage: oops_v3.py snapshot save <path> [--name NAME] [--description TEXT]")
                sys.exit(1)
            snap_path = sys.argv[3]
            snap_name = os.path.basename(snap_path).replace('.snapshot.json', '').replace('.json', '')
            snap_desc = ''
            i = 4
            while i < len(sys.argv):
                if sys.argv[i] == '--name':
                    snap_name = sys.argv[i+1]; i += 2
                elif sys.argv[i] == '--description':
                    snap_desc = sys.argv[i+1]; i += 2
                else:
                    print(f"Unknown arg: {sys.argv[i]}"); sys.exit(1)
            written = save_pool_snapshot(snap_path, snap_name, description=snap_desc)
            print(f"Wrote snapshot: {written}")
            print(f"  name: {snap_name}")
            print(f"  packs captured: {len(_capture_current_pack_state())}")
            sys.exit(0)
        elif op == 'info':
            if len(sys.argv) < 4:
                print("Usage: oops_v3.py snapshot info <path>"); sys.exit(1)
            snap = load_pool_snapshot(sys.argv[3])
            print(f"Snapshot: {snap.get('name', '<unnamed>')}")
            print(f"  schema:     {snap.get('_schema')}")
            print(f"  created:    {snap.get('created', '?')}")
            print(f"  engine_ver: {snap.get('engine_version', '?')}")
            if snap.get('description'):
                print(f"  description:")
                # Wrap description at ~70 chars
                desc = snap['description']
                for line in desc.split('\n'):
                    while len(line) > 70:
                        cut = line[:70].rfind(' ')
                        if cut < 30: cut = 70
                        print(f"    {line[:cut]}")
                        line = line[cut:].lstrip()
                    if line: print(f"    {line}")
            po = snap.get('pack_overrides', {})
            if po:
                print(f"  pack_overrides ({len(po)}):")
                for fname, ov in sorted(po.items()):
                    state = 'enabled' if ov.get('enabled', True) else 'DISABLED'
                    extras = [k for k in ov if k != 'enabled' and not k.startswith('_')]
                    extra_str = f" [+{', '.join(extras)}]" if extras else ''
                    print(f"    {fname}: {state}{extra_str}")
            ek = snap.get('engine_kwargs', {})
            if ek:
                print(f"  engine_kwargs:")
                for k, v in sorted(ek.items()):
                    if isinstance(v, list) and len(v) > 6:
                        print(f"    {k}: [{', '.join(repr(x) for x in v[:3])}, ... +{len(v)-3} more]")
                    else:
                        print(f"    {k}: {v!r}")
            sys.exit(0)
        else:
            print(f"Unknown snapshot subcommand: {op}"); sys.exit(1)

    if len(sys.argv) < 4 or sys.argv[1] != 'shuffle':
        print("Usage: oops_v3.py shuffle <input_dir> <output_dir> [--seed N]")
        print("                   [--randomize-clusters] [--no-clusters]")
        print("                   [--merchant-models] [--snapshot PATH]")
        print()
        print("  Default behavior: clusters (multi-Part spawn groups) are LEFT VANILLA")
        print("  to avoid breaking shared-healthbar boss encounters (Crystalian Alliance,")
        print("  Oracle Envoys, Albinaurics, Pest Threads cluster, etc). Solo Parts get")
        print("  randomized normally.")
        print()
        print("  --randomize-clusters: opt back into v4.2 cluster preservation behavior")
        print("    (coordinated swaps with locked variants). More variety, but multi-Part")
        print("    boss encounters with shared healthbars may freeze / stuck-in-floor.")
        print()
        print("  --no-clusters: skip cluster computation entirely. Every Part rolls")
        print("    independently regardless of spatial proximity. Useful for testing")
        print("    whether cluster preservation is still necessary. Maris Tendrils, Oracle")
        print("    Envoys, Banished Knight encampments will all randomize per-Part.")
        print()
        print("  --merchant-models: post-pass that swaps the visual MODEL of merchant")
        print("    entities (Nomadic Merchant, Small Jar Merchant) to a curated pool of")
        print("    humanoid alternatives (knights, bosses, beasts). Their NPCParam stays")
        print("    intact — merchants remain functional merchants with shops/dialogue,")
        print("    they just look different.")
        print()
        print("  --sote: all-SOTE mode. Restricts every swap target to Shadow-of-the-")
        print("    Erdtree chrs. With the always-on rider/mount role restriction, a")
        print("    vanilla Kaiden Sellsword rider becomes the Black Knight (c5840) and")
        print("    his horse becomes the Black Knight Horse (c5890). Requires MMV +")
        print("    heritage SOTE assets staged; caps/floors are bypassed (heavy repeats).")
        print()
        print("  --snapshot PATH: load a pool snapshot before running. Snapshot file")
        print("    controls which asset packs feed the swap pool (heritage_pack,")
        print("    mmv_imports, etc.) and applies any engine_kwargs the snapshot records")
        print("    (excluded_prefixes, multiplayer_safe, etc.). Preset snapshots ship in")
        print("    data/snapshots/. Run 'oops_v3.py snapshot info <path>' to inspect one.")
        print()
        print("  snapshot subcommands (separate from 'shuffle'):")
        print("    oops_v3.py snapshot save <path> [--name NAME] [--description TEXT]")
        print("    oops_v3.py snapshot info <path>")
        sys.exit(1)
    in_dir, out_dir = sys.argv[2], sys.argv[3]
    seed = 42
    merchant_model_swap = False
    mount_rider_swap = False
    sote_mode = False
    snapshot_path = None
    i = 4
    while i < len(sys.argv):
        if sys.argv[i] == '--seed': seed = int(sys.argv[i+1]); i += 2
        elif sys.argv[i] == '--sote':
            # v0.27.21: all-SOTE mode toggle. Sets V3_SOTE_MODE so every
            # swap target is intersected with V3_SOTE_PREFIXES in
            # pick_target_cp. Combined with the always-on rider/mount role
            # restriction, a vanilla Kaiden rider slot draws SOTE ∩ riders
            # = {c5840} Black Knight and the paired mount slot draws
            # SOTE ∩ mounts = {c5890} Black Knight Horse. Requires MMV +
            # heritage SOTE assets staged (see the V3_SOTE_MODE block).
            sote_mode = True; i += 1
        elif sys.argv[i] == '--mode':
            # v0.23.72-late: --mode was a no-op since v0.20.0 (universal pool).
            # Accept-and-ignore the flag for back-compat with scripts/CI that
            # still pass it, but warn on stderr so callers know to remove it.
            print(f"warning: --mode is deprecated and ignored (universal pool since v0.20.0); "
                  f"flag value '{sys.argv[i+1]}' has no effect", file=sys.stderr)
            i += 2
        elif sys.argv[i] == '--merchant-models':
            merchant_model_swap = True; i += 1
        elif sys.argv[i] == '--mount-rider-swap':
            mount_rider_swap = True; i += 1
        elif sys.argv[i] == '--snapshot':
            snapshot_path = sys.argv[i+1]; i += 2
        else: print(f"Unknown arg: {sys.argv[i]}"); sys.exit(1)

    # v0.23.72-late: snapshot support. Apply the snapshot's pack_overrides
    # to module state before cmd_shuffle_v3 calls load_data, and splat the
    # snapshot's engine_kwargs into the call. Wrapped in try/finally so we
    # clear the overrides even if the run crashes.
    snap_kwargs = {}
    if snapshot_path:
        snap_kwargs = apply_pool_snapshot(snapshot_path)
        print(f"Loaded snapshot: {snapshot_path}")
        if snap_kwargs:
            print(f"  engine_kwargs from snapshot: {list(snap_kwargs.keys())}")
    try:
        cmd_shuffle_v3(in_dir, out_dir, seed,
                        merchant_model_swap=merchant_model_swap,
                        mount_rider_swap=mount_rider_swap,
                        sote_mode=sote_mode,
                        **snap_kwargs)
    finally:
        if snapshot_path:
            clear_pool_snapshot()