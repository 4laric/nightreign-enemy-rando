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
V3_ENGINE_VERSION = 'v0.23'
V3_ENGINE_FINGERPRINT = 'v0.28.0'  # MUST bump on each release — appears in spoilers

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
    # Sub-components and non-combat
    'c4960','c4961','c4000','c4491','c6001','c8130','c8131','c8132',
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
V3_EXCLUDE_TARGET_PREFIXES = {
    # v0.27.44 (Alaric): ban c5890 "Black Knight Horse" outright. The MSB scan of
    # vanilla ER SOTE confirmed c5890 is an MMV/NR fabrication (zero vanilla
    # occurrences, no real rider-mount template); the matched c5840+c5890 pair
    # CTDs at runtime. Target-excluding it means it is never placed as a swap
    # result anywhere. With this ban the v0.27.43 c5840<->c5890 family swap
    # (V3_RIDER_MOUNT_TARGET_FAMILIES) is inert (the mount half is unplaceable).
    # Separately, genuine mounted rider+mount pairs are preserved VANILLA at the
    # slot level (_preserve_detected_rider_mount_pairs), so c5890 is not needed to
    # keep clusters coherent. NOTE: the riders (c4050/c5840) are NOT excluded —
    # their solo instances still randomize.
    'c5890',  # Black Knight Horse (fabricated mount; matched pair runtime-CTDs)
    'c4060',  # Kaiden's Horse — same mount-component failure mode as c3180 Albinauric Wolf; paired with c4050 Kaiden Sellsword
    'c5090',
    # v0.28 (Alaric): ban c4140 "Spiritcaller Snail" outright. DLC import
    # (post_dlc_dump, 0 vanilla NR placements) and a summoner whose
    # invulnerable-until-summon-killed mechanic doesn't survive randomization
    # — the spirit-summon EMEVD doesn't fire in arbitrary field slots, so it's
    # unkillable at best and CTDs during summon at worst (never observed
    # working in play). Target-excluding it means it's never placed as a swap
    # result. The _LIFTED_V0_24_65 entry and the miniboss cap on c4140 are now
    # dead (the exclude wins).
    'c4140',  # Spiritcaller Snail (summoner; never works when randomized)
    # v0.27.13: DLC SHADER GAP CLASS. Heritage chrs whose matbins'
    # ShaderPath fields reference DLC-only `.spx` shaders not in NR's
    # `shaderbdle.shaderbdlebnd.dcx`. Symptom: chr loads correctly but
    # renders invisible (matbin's ShaderPath fails to resolve) or
    # partially invisible (some matbins point at NR-resident shaders,
    # some don't). Class-level doc: dev/DLC_SHADER_GAP_CLASS.md.
    # NOTE: fix shape is *matbin ShaderPath rewrite*, NOT FLVER MTD
    # rewrite as the class doc originally stated (FLVER→matbin
    # resolves fine; matbin→.spx is the broken layer). PK precedent
    # was the same shape; the class doc was inverted on this point.
    #
    # v0.27.14: matbin ShaderPath patches shipped for c5500 / c5511 /
    # c5512 — un-excluded and rendering. c5513 also confirmed visually
    # functional WITHOUT patches (FLVER parse showed 2 of its 7 matbins
    # already reference NR-resident Glow[Int] shaders, and the other 5
    # apparently bind acceptably too — never DLC-broken to begin with).
    # Kept excluded anyway: c5513 Cemetery Shade is a near-duplicate of
    # the existing vanilla NR Cemetery Shade — admitting it just splits
    # the pool weight between two functionally identical chrs. Same
    # "redundant archetype" rule as the v0.26.x c4910 Magma Wyrm cap
    # removal. NOTE: c5513's textures (c5513_Body_em.dds emissive +
    # full a/m/n set, c5513_Crab_em.dds, c5513_Fur a/m/n, c5513_Wepon
    # a/m/n) look visually distinctive — candidate texture donor for
    # the patched-but-plain c5511/c5512 Shades and possibly the
    # lampreys. See dev/DLC_SHADER_GAP_CLASS.md "Texture donor opportunities".
    'c5513',  # Cemetery Shade — visually fine but functionally duplicate of vanilla Cemetery Shade; pool kept clean
    # v0.27.2: playable-character (Nightfarer class) models. The c523xx
    # range scraped by post_dlc_dump includes three NR PLAYABLE class
    # models that were sitting in the target pool as tier='grunt'
    # enemies. Placing a player class as a world enemy is never wanted.
    # Found via the 98-seed sim (2026-05-26): all three at 0 placements,
    # but they remained pool-eligible and could surface on other seeds.
    # Alaric named Priestess/Duchess + Executor; c52312 'Witch of the
    # Wheel (Recluse Remembrance)' is the Recluse class — same family,
    # excluded on the same grounds (flag if that read is wrong).
    'c52309',  # Priestess (Duchess) — NR playable Nightfarer class
    'c52312',  # Witch of the Wheel (Recluse) — NR playable Nightfarer class
    'c52313',  # Executor — NR playable Nightfarer class
    # Mount/companion models that only function as cluster members in vanilla.
    # When placed standalone in a generic slot, they appear inert (no AI, no
    # aggression) because their NPCParam is configured for "ride-along" rather
    # than "combat". Our cluster-shape catalog still places them correctly
    # in mount+rider cluster swaps via member-by-member shape matching.
    # v0.25.0-patch1: c4361 Godrick Knight's Horse — same failure mode as
    # c4363 but escaped the original audit because nr_enemy_tags has it
    # tagged tier='grunt' (the other Knight's Horse variants are correctly
    # tier='mount_component'). Two structural defenses both missed it:
    # (1) hardcoded mount ban below didn't list it, (2) mmv_imports auto-
    # ban only fires for mount_component-tier chrs. Empirical leak:
    # placed once in seed 939029 (m60_43_37_00 pi=52 from c4380 Starcaller
    # slot) AND once in seed 42 (m34_20_00_00 pi=24 from c4570 Wormface
    # slot). Tag fix in nr_enemy_tags.json (grunt → mount_component) ships
    # alongside this to close the structural gap too.
    'c4361',  # Godrick Knight's Horse — paired with c4353 Leyndell Knight
    'c4460',  # Flame Chariot (XXL multi-part: cart + horses + rider) —
              #   v0.20.53 added to SENSITIVE; v0.20.69 promoting to
              #   EXCLUDED. Multi-physics-body compound chr; subcomponent
              #   anchors fail at random slots.
    # v0.24.18: Frenzied Nomad (Marsh Group Boss) — auto-imported via
    # post_dlc_dump with tier='trash' but "Marsh Group Boss" name marker
    # tricks the boss-tier slot filter into accepting it everywhere. 15
    # unrestricted placements in seed 70502 caused fly-in CTD with red
    # madness fog visible. Same shape as the cluster-only chrs above:
    # expects EMEVD scaffolding to instantiate its marsh-group spawn
    # pattern; at solo slots the chr emits its persistent madness AoE
    # while AI never fully inits, blowing the particle/AI budget during
    # overworld load. Zero vanilla source slots — exclusion costs
    # nothing. If the broader "auto-tagged post_dlc chr with misleading
    # name marker" class produces more reports, escalate to a tier-vs-
    # name-marker audit pass; candidates listed in OPEN_ISSUES.md.
    'c3201',  # Frenzied Nomad (Marsh Group Boss) — auto-import cluster-only

    # v0.27.0-late: c3361 Putrid Ancestral Follower — full target exclude.
    # Extends the v0.27.0 c3360 finding. The c3360 playtest established
    # that only the Axe (33600010) and Archer (33600510) Blacksmith-Group-
    # Boss variants render and fight; the other 32 c3360 variants are
    # broken (see V3_AVOID_VARIANT_NPC_IDS). c3361 is the SOTE rotted
    # reskin of c3360 — same skeleton and animation family — and all 16
    # of its variants are plain-named "Putrid Ancestral Follower" with no
    # Blacksmith-Group-Boss working subset (15 are post_dlc_dump ghosts,
    # 1 canonical). Nothing distinguishes a working variant, so unlike
    # c3360 there is no Axe/Archer pair to keep — the whole c-prefix is
    # excluded as a target rather than enumerating 16 ids in the variant
    # avoid-set. Empirical leak: 28 placements in seed 617175. (c3361 was
    # previously listed in V3_FRAGILE_SAFE_CONFIRMED on a stale v0.20.43
    # "ancestral shaman good" note — removed alongside this, since that
    # note refers to the Shaman c3370 and a target-excluded chr cannot be
    # placed at a fragile slot anyway. Sibling c3371 Putrid Ancestral
    # Shaman is the same situation but is left for a separate call.)
    'c3361',  # Putrid Ancestral Follower — broken-variant family (c3360 kin)

    # v0.23.72-late: c5110 Maris' Tendril REMOVED from EXCLUDED — moved
    # back to V3_FRAGILE_SENSITIVE_TARGETS where it lived in v0.20.55-69.
    # Reason: user playtest reports that Tendril at non-fragile slots
    # plays really well — its friendly-fire on grunts creates fun
    # strategic bait opportunities (lure grunts into tendril sweeps).
    # The "no functional AI standalone" framing from v0.20.69 turned
    # out to be overstated — Tendril's whip-sweep AI fires fine at
    # non-cluster slots, it's just visually weird without the Maris
    # main body to anchor to. The visual oddity is fine; the
    # fragile-slot CTDs are what we actually need to avoid. SENSITIVE
    # classification handles that precisely.
    #
    # NOT moving the source side: vanilla Maris encounter slots
    # (m60_xx Limveld procedural Maris tiles) stay protected via
    # V3_MAP_PREFIX_TARGET_EXCLUDES['m60_'] for now — the Maris fight
    # is its own thing and we don't randomize INTO Maris boss slots.
    # The TODO "broader EMEVD cluster-anim audit" covers the eventual
    # path to revisiting that protection too.
    # v0.23.72-late: c4504 Elder Dragon Greyoll. XXL field-spawn dragon
    # with a uniquely script-dependent fight: in ER her HP is gated by
    # killing the four ambient dragons that spawn around her — without
    # that EMEVD chain firing, she's an unkillable static dragon.
    # Placing her at any non-vanilla slot has zero chance of preserving
    # that scripting. Plus her size is non-arena-friendly even where it
    # fits. The Pass A name/tier corrections (variant_name='Elder Dragon
    # Greyoll', tier='night_boss') are kept for spoiler-label hygiene
    # since the engine still references her in compatibility checks.
    'c4504',  # Elder Dragon Greyoll — scripted multi-part fight (4 ambient
              #   dragons gate HP); plus XXL field-spawn (hp=12440) too
              #   big for non-vanilla placement anyway.
    # v0.19.28: Marionette (c3850) re-excluded — variants include
    # "Sparring Grounds Dummy" (npc=38502100) which is a passive training
    # dummy with no aggressive AI. When the random variant picker rolls
    # that variant for a real combat slot, the slot gets a non-aggressive
    # enemy that doesn't fight back. Vanilla ER has aggressive Marionette
    # Soldiers in Caria Manor that we could heritage-import for AI later;
    # for now exclude as target. Tier=grunt humanoid M (8 variants).
    'c3850',  # Marionette — Sparring Grounds Dummy variant has no combat AI
    # v0.19.31: Skull Plate Giant Ant (c4281) — quadruped_large XL with
    # locomotion=5 (spider-jump pathing). Empirically breaks on rubble /
    # uneven stone geometry. Originally fully excluded as a workaround
    # for missing per-chr terrain filtering.
    #
    # v0.24.89-patch11: DEMOTED from EXCLUDE to V3_FRAGILE_SENSITIVE_TARGETS.
    # The v0.19.31 rationale predates the SENSITIVE list itself. Same-
    # family chr c4240 Fingercreeper (XL, loco=5 — identical profile)
    # has been at SENSITIVE since v0.20.87 without escalation. Treating
    # c4281 differently was exception-by-history, not exception-by-
    # failure-mode. SENSITIVE routes c4281 to FRAGILE_SAFE_CONFIRMED
    # slots only, which is the correct filter for "multi-leg insect on
    # rubble" since the SAFE slots are the ones empirically cleared of
    # uneven stone geometry. See c4240/c4241/c4280 for precedent.
    # NOTE v0.20.9: c4650 Dragonkin Soldier moved from TGT_EXCL to
    # V3_ARENA_ONLY_TARGETS. The CTD at m45_51 pi=2 was traced to the
    # SLOT being a c2130 Margit summon-script marker (position 0,0,1),
    # not to c4650 itself. Slot now in V3_PROBLEM_SLOTS. c4650 placed
    # at real boss arenas should work.
    # v0.19.11: Bosses with hard-coded environment-emergence spawn scripts.
    # Their entry animations require specific arena geometry (magma surface,
    # crater floor, cliff perch, etc) that random target slots don't provide.
    # When placed at a normal slot, the spawn anim plays but the boss
    # disappears through the floor / out of bounds and gets culled.
    # Confirmed via seed 246135: c4910 Magma Wyrm at Fallingstar Beast Night
    # Boss slot (m49_20) "spawned in then disappeared" per playtest report.
    # v0.23.07: c4910/c4510/c4500/c4501/c4503/c4505/c4911 lifted —
    # uniqueness cap (V3_UNIQUE_TARGET_CAPS) replaces the wholesale
    # exclude. The reservation pre-pass picks one quality slot per
    # capped dragon (high score for arena-flagged source, expects_boss_
    # arena=True, high altitude for flying types, non-fragile, non-cluster).
    # If no quality slot is found, the cp goes unplaced for that run
    # (logged in spoiler header). Net effect: dragons go from "0 per run
    # because excluded" to "0-1 per run, only at high-quality slots."
    # 'c4910',  # Magma Wyrm (Crater) — lifted v0.23.07; cap=1
    # 'c4510',  # Ancient Dragon — lifted v0.23.07; cap=1
    # v0.26.x: c4500/c4505 moved here from V3_EXCLUDE_PREFIXES — they
    # were wrongly SOURCE-excluded. Target-excluded only now; vanilla
    # dragon slots stay source-eligible and still randomize.
    #
    # Ban rationale ("no sauce"): c4500 (Agheel-class base) and c4505
    # (small variant) are flying dragons with no element or status —
    # plain bite/tail/fire-breath movesets. Every dragon swap should
    # land on something visually or mechanically interesting, so the
    # bland variants are kept out of the target pool while the saucy
    # ones stay in: c4501/c4502 Ekzykes (scarlet rot), c4503 Borealis
    # (ice), c4510 Ancient (lightning), c5860 Ghostflame (death), c7700
    # Gaping Dragon (bile). This SHRINKS the pool; the plan to also
    # WIDEN it is the "ER dragon heritage imports" item in dev/TODO.md
    # (Smarag, Adula, Glintstone Dragon — magic-element dragons). See
    # that TODO before lifting these bans.
    'c4500',  # Flying Dragon (Agheel-class, "no sauce" base dragon)
    # 'c4501',  # Decaying Ekzykes (Unscaled) — lifted v0.23.07; cap=1
    # 'c4503',  # Borealis the Freezing Fog — lifted v0.23.07; cap=1
    'c4505',  # Flying Dragon (Small) — "no sauce" small dragon
    # v0.26.16: c2273/c2275/c2277 unverified crab imports moved here
    # from V3_EXCLUDE_PREFIXES (c2277 confirmed CTD seed 704822).
    # imported_chr — zero vanilla source slots, so target-exclude is
    # the only meaningful exclusion for them anyway.
    'c2273',  # Crab (Maggots)      — unverified import, CTD-suspect
    'c2275',  # Crab (Clean)        — unverified import, CTD-suspect
    'c2277',  # Crab (Golden Tufts) — confirmed CTD, seed 704822
    # 'c4911',  # Great Wyrm Theodorix — lifted v0.23.07; cap=1
    # v0.23.76: c5810 Demi-Human Swordmaster REMOVED from target-exclude.
    # Lifted together with c4110 Shaman source-exclusion since the original
    # rationale was a paired concern about the small Shaman compat pool.
    # With the broader compat pool now, Swordmaster is fine as a target.
    # OLD COMMENT (kept for context):
    #   Demi-Human Swordmaster — only 2 vanilla variants total, but flagged
    #   boss-tier overall (Night Boss + Mountaintop), so it dominated the
    #   small Demi-Human Shaman compat pool when allowed as a target. Keep
    #   it at its native Demi-Human Queen Night Boss arena (m49_29) only.
    #   Paired with c4110 Shaman source-exclusion (above) to preserve the
    #   Demi-Human family ecosystem.
    # 'c5810',  # LIFTED v0.23.76
    # v0.23.71: MMV chrbnd-preload CTD set. These MMV-imported chrs
    # consistently CTD before the map finishes loading (asset preload
    # failure), or freeze on first encounter due to missing dependency
    # chains. NR preloads specific chrbnds per arena; MMV chrs not in
    # those preload lists crash on spawn. The proper fix is per-arena
    # preload mapping in the engine (separate workstream), but until
    # then these are excluded from placement.
    #
    # Confirmed via user playtest:
    #   c4511 Lichdragon Fortissax    — CTD before map loads
    #   c5030 Romina, Saint of the Bud — CTD (scarlet-rot transformation FX)
    #   c5051 Midra, Lord of Frenzied Flame — CTD
    #   c5200 Metyr, Mother of Fingers — CTD on encounter spawn
    #
    # All four SoTE-origin nightlord-tier MMV imports — pattern: SoTE
    # boss chrbnds need DLC-specific asset preload that NR doesn't do
    # by default. Working counterexamples (Scadutree c5230, Messmer
    # c8200?, Maliketh) are bosses whose vanilla SoTE encounter is
    # comparatively script-light. The CTD bucket is the cinematic-heavy
    # SoTE bosses: Fortissax descent intro, Metyr eclipse FX chain,
    # Midra frenzied-flame VFX, Romina scarlet-rot transformation FX.
    #
    # v0.24.73 LIFTED — per v0.24.65 directive "the ENTIRE MMV roster
    # is back on the table. lift it dude" + the data-file lift comment
    # which states the full MMV deploy formula (chr files + per-chr
    # battle/logic scripts + bundled aicommon + MMV sfx/ + material/)
    # restores SoTE chrs to working state. Specific datapoint cited:
    # Romina (c5030) confirmed functional in user playtest after full
    # deploy. The exclusion at the data-file `broken_runtime_chrs` got
    # lifted but this hardcoded entry was missed. Lifting now.
    #
    # Safety net: cap=1 in V3_UNIQUE_TARGET_CAPS limits each to a
    # single placement per seed, so if one of them is still broken
    # under specific arena conditions the blast radius is bounded.
    # Plus boss_clear_watchdog (300s) + preboss_wake_timeout (90s,
    # v0.24.71) catch the encounter-stall failure modes.
    # 'c4511',  # LIFTED v0.24.73 — Lichdragon Fortissax
    # 'c5030',  # LIFTED v0.24.73 — Romina, Saint of the Bud
    # 'c5051',  # LIFTED v0.24.73 — Midra, Lord of Frenzied Flame
    # 'c5200',  # LIFTED v0.24.73 — Metyr, Mother of Fingers
    # =====================================================================
    # Untagged-by-design prefixes — never standalone enemies.
    #
    # These appear in vanilla NR only as cluster members or as non-enemy
    # entities (projectiles, NPCs, item-drop critters). They have no
    # size_class because they aren't independent combatants.
    #
    # Selective inclusion as of v0.11 — the four cluster-member prefixes
    # (c4181 Maris' Jellyfish, c5110 Maris' Tendril, c3610 Oracle Envoy,
    # c3620 Oracle Envoy Large) were previously here and are now allowed
    # as swap targets per user feedback: "i've seen it work in a lot of
    # slots already, including the like giant rat in small castle
    # basement that doesn't have a ton of candidates." Their absence of
    # family tags means they bypass the swap_compat filter (the
    # "untagged candidate bypass" path in pick_target_cp), so they appear
    # broadly via anim_bank pool matching. If a specific placement
    # produces a broken-looking standalone Tendril (rooted in midair
    # with no anchor, etc.), add it back here as a hard exclusion or
    # tag it properly so swap_compat can place it more selectively.
    # =====================================================================
    'c2150',  # Lightning Ball      — projectile, not an enemy
    'c4191',  # Scarab              — item-drop critter, runs on contact
    'c3200',  # Nomadic Merchant    — NPC merchant, not combatant
    'c8911',  # (no name)           — single roster entry, no slot, unknown
    # v0.23.11: visual + behavior failures from playtest.
    # Silver Tear (c3320) and Giant Silver Tear (c3330): user-confirmed
    # "visually glitching" at randomized slots. ER Silver Tears are
    # shape-shifting mimics whose default behavior is to morph into
    # whatever player/enemy is nearby. The transform-target identification
    # is tied to ER's specific area scripts (Nokron, Crystal Cave events);
    # at NR random slots it has nothing valid to mimic and renders as a
    # broken/incomplete mesh. Mimic-class chrs are categorically risky for
    # rando placement — the "what to look like" data is event-bound.
    'c3320',  # Silver Tear (Unscaled)         — shape-shifting mimic, no anchor
    'c3330',  # Giant Silver Tear (Unscaled)   — same family, same failure
    # c7580 — _unknown=True scanner flag, name='c7580' (no human name),
    # tier=nightlord (highest boss strength, so passes every tier filter),
    # misc-family, expects_boss_arena=False, hp_max=0, 3 unnamed
    # variants. User report: replaced Bell Bearing Hunter NB anchor in
    # playtest, didn't aggro, died in 1 hit, looked like Two Fingers /
    # Metyr (decorative NPC chr). Almost certainly a NR companion-NPC /
    # Recluse summon model that got mis-tagged with tier=nightlord by an
    # earlier scanner heuristic. Until we identify what c7580 actually
    # is and whether it has a real combat variant, exclude as target.
    # The tier=nightlord misclassification meant it was passing the
    # boss-strength filter and competing at every NB anchor — exactly
    # the wrong outcome for a 0-HP non-combat chr.
    'c7580',  # (unknown) — _unknown=True, mis-tagged as nightlord, hp=0
    # v0.23.15: model-variant phantoms — chrs whose .chrbnd.dcx files do
    # not actually ship with vanilla NR (or with vanilla ER, verified). The
    # tagger surfaced these as standalone placeable c-prefixes from
    # chrModelParam / NpcParam / cluster-shape catalog rows, but they're
    # behbnd-internal model variants of their parent c-prefix — placing
    # them references chr files that don't exist, causing CTD on cell-load.
    # Diagnosed via chr/ Inventory tab Diagnose against a target chr/
    # folder (250 prefixes on disk, 197 spoiler-required, exactly these
    # three missing) cross-referenced against an unpacked ER chr/ (also
    # missing). This is a third chr-availability failure mode beyond
    # "needs heritage pack" and "needs BFER" — these chrs aren't anywhere.
    #
    # Companion edits below this set: c4181 also removed from
    # _FI_CPS_RESERVED_FOR_TARGET (defensive-cleanup must not undo this
    # exclusion — same pattern as v0.20.69 c5110 promotion).
    # v0.24.101: c4181 LIFTED from V3_EXCLUDE_TARGET_PREFIXES — part of
    # the "open the floodgates" variety pass. Original v0.23.12 ban was
    # for a Rotting Woods Day 2 CTD that traced to 6× c4181 placements
    # in m34_xx cells (spoiler 412746). Engine has evolved significantly
    # since v0.23.12; if Rotting Woods Day 2 CTD recurs, restore this
    # entry. Source-exclusion (V3_EXCLUDE_SOURCE_PREFIXES) stays — vanilla
    # jellyfish slots remain preserved.
    # 'c4181',  # Maris' Jellyfish — lifted v0.24.101 (see above)
    'c4641',  # Weapon-Bequeathed Harmonia (Everdark Worm) — tier='nightlord',
              #   Raid mode boss. Same family as c7620 Harmonia (which is in
              #   V3_EXCLUDE_PREFIXES — full ban, prevents source AND target
              #   placement). c4641 has 0 MSB Parts so source-side moot;
              #   target-side ban prevents engine from picking it for random
              #   slots where the Raid-arena-specific wake events would fail.
              #   v0.23.72-late: comment corrected — the v0.23.12-era ban was
              #   filed under "Tree Spirit (Unscaled, variant)" from
              #   vanilla_promotions_v1, but post_dlc_dump identifies it as
              #   Harmonia. The ban itself remains correct; only the rationale
              #   was wrong.
    # v0.23.85: Lamprey c5060/c5061 — MMV-imported, asset-invisible at
    # placement. User playtest seed 397159 reported a Lamprey in place of
    # the m30_30 Fort Guardian Golem, no visible model in the arena. MMV
    # was ON for the run (expected to provide the asset) but the chr still
    # rendered invisible — suggests the asset isn't in the standard MMV
    # chrbnd preload set or fails to register for the Fort arena. Plus
    # v0.23.86: c3860 Avionette + c3370 Ancestral Follower Shaman were
    # added here on a misread of the user's playtest report. The two
    # freezes at the Lordsworn Captain Fort were SLOT-side fragility
    # (specific m30_xx Fort slot geometry breaks otherwise-OK chrs) NOT
    # chr-side fragility. Reverted v0.23.87. The slot-side fix lives in
    # the slot-reposition / slot-fragility infrastructure, not here.

    # v0.24.36 + v0.24.37: dump-only chrs with no .chrbnd files.
    # See `_load_missing_chr_files()` below and data/nr_missing_chr_files.json.
    # These entries are loaded at module import. The constants below are
    # placeholders that document the intent and seed the static set so
    # `c4358 in V3_EXCLUDE_TARGET_PREFIXES` works pre-load_data() (used by
    # signature/lock tests). Loader replaces the placeholders if the data
    # file has different content.
    'c4358',  # Castle Knight Variant         (post_dlc_dump, no file)
    'c4801',  # Lord of Blood Spear           (post_dlc_dump, no file)
    'c7610',  # Traitorous Straghess          (post_dlc_dump, no file)
    'c7650',  # Dreg Corpse                   (post_dlc_dump, no file)
    'c7651',  # Large Dreg Corpse             (post_dlc_dump, no file)
    'c7660',  # Dreg Wormface                 (post_dlc_dump, no file)
    'c7720',  # Knight Artorias               (post_dlc_dump, no file)
    'c7930',  # Demon from Below              (post_dlc_dump, no file)

    # v0.25.6: MMV Nightlord-phase chrs with hard scripted-context
    # dependencies. Confirmed crash in seed 66782 v0.25.5 for c8500
    # Manus, and c8200/c8400 share the same untagged-leakage risk class.
    #
    # v0.26.x: c8500 Manus UN-BANNED per playtest direction — confirmed
    # working in subsequent seeds. Same vindication trajectory as c8300
    # Dragonslayer Armor (v0.23.46) and c4720 Godfrey (v0.23.55): the
    # original seed-66782 CTD was a position-specific anim-slot mismatch
    # now caught by V3_FLYING_REQUIRED_SLOTS / V3_QUADRUPED_UNSAFE_SLOTS,
    # not a fundamental scripted-context dependency. c8500 is now fully
    # tagged (tier=nightlord, XL, expects_boss_arena) so it's arena-only-
    # gated rather than free-leaking. c8200/c8400 remain banned — still
    # untagged, never validated.
    #
    # Why c8200/c8400 stay banned:
    #   They are still untagged + uncapped, full chr files deployed in
    #   heritage_pack but never validated as swap targets — leakage from
    #   the heritage import pipeline. Future heritage imports should be
    #   tag-gated, not file-gated.
    'c8200',  # MMV Nightlord-phase chr (untagged, never validated)
    'c8400',  # MMV Nightlord-phase chr (untagged, never validated)
    # v0.26.x: redundant-archetype simplification. Each of the c-prefixes
    # below has a same-shape sibling tagged night_boss in the engine.
    # The picker treats these as variant clutter in the field_boss pool
    # rather than meaningfully distinct fights, so we let only the NB
    # sibling represent the archetype. Source-side vanilla placements
    # are preserved (engine doesn't ban them as source), so each
    # excluded chr still appears in its single vanilla spot per seed —
    # the ban only stops them from being PICKED as targets at random
    # slots. Existing per-cap entries dropped (would shadow with EXCL
    # and surface as dead-cap findings in the placement-budget audit).
    #
    # Underlying principle (per Alaric, while sending c3252): the
    # Night-Boss-tagged variants in NR generally have more attacks /
    # more polished movesets than the Field-Boss variants for the same
    # archetype. Draconic Tree Sentinel is the named example: c3250
    # NB variant has more attacks in NR than the FB variant. The same
    # quality gradient likely holds for other NB-vs-FB pairs in this
    # engine, so when we collapse a redundant archetype we keep the
    # NB version on quality grounds, not just frequency.
    'c5010',  # Golden Hippopotamus — c5011 Golden Hippopotamus (Golden
              #   Wings) is the NB-tier same-chr variant. Vanilla c5010
              #   slot at the m48_77 NB arena (or wherever vanilla
              #   places it) stays vanilla; everywhere else the picker
              #   draws from c5011 only.
    'c4910',  # Magma Wyrm — c4911 Great Wyrm Theodorix is the NB-tier
              #   named variant. NB-side cap=1 means total Wyrm budget
              #   drops from 2/seed (c4910 cap=1 + c4911 cap=1) to
              #   1/seed; acceptable per simplification trade-off.
              #   If Wyrm placement feels too sparse in playtest,
              #   either bump c4911 cap to 2, or lift c4910 here.
    'c3252',  # "Loretta Tree Sentinel" → actually Royal Carian Knight
              #   (the tag NAME claimed Loretta but all 4 NpcParam
              #   variants are named Royal Carian Knight — vestigial
              #   ER-origin assumption that didn't match what NR ships
              #   under c3252; tag name fixed in nr_enemy_tags.json to
              #   reflect the actual chr). Same-shape sibling: c3251
              #   Tree Sentinel (NB) and c3250 Draconic Tree Sentinel
              #   (NB) cover the XL-quadruped_large knight-on-horse
              #   archetype. RCK's only distinguishing visual is the
              #   armor; the NB Tree Sentinel pair has more attacks in
              #   NR (per Alaric), so collapsing to those two is a
              #   net quality improvement.
    # Small Oracle Envoy. c3610 is a _cluster_only chr: placed standalone
    # at a generic slot it floats frozen on the entrance animation, off
    # its Maris cluster. v0.24.65 lifted the ban speculatively ("maybe the
    # bug self-fixed") with a defensive cap=1 as a safety net.
    # v0.24.86-patch2-followup RE-EXCLUDED it: seed 923630 (m49_43_00_00
    # pi=7) reproduced the freeze, identical to the original v0.24.65 ban
    # motivation. Cap=1 wasn't enough — one placement bricks the seed. The
    # exclude wins over the cap; the dead cap entry was dropped from the
    # `_LIFTED_V0_24_65` set (see the c3610 note in that set's comment,
    # which cross-references this entry — keep the two in sync). Distinct
    # from c3620 Oracle Envoy (Large; Cathedral), which stays placeable.
    'c3610',  # small Oracle Envoy — cluster_only standalone freeze
    # Walking Mausoleum. c4450 carried a residual tier='field_boss' that
    # the v0.26.x tier collapse missed (it was tagged field_boss by its
    # post_dlc_dump source manifest, not via the old V3_TAG_OVERRIDES
    # dict, so the flatten never touched it). Rather than re-tier it to
    # miniboss/night_boss, it is parked here as a target exclusion: it is
    # an XXL (~59m tall) ambient crawling structure with has_boss_reward=
    # false and has_drops=false — not a combatant. Placed at any generic
    # slot it clips through geometry. Already excluded as a SOURCE (and
    # target) via V3_EXCLUDE_PREFIXES ("keep at home"); this entry makes
    # the target exclusion explicit in the canonical set. Companion
    # cleanup: c4450 dropped from V3_NIGHT_BOSS_CALIBER_TARGETS in the
    # same change (a target-excluded chr can't be an NB-arena pick, so
    # the caliber entry would be dead — would surface in
    # dev/audit_placement_budget_consistency.py). Surfaced by
    # test_pick_target::test_field_boss_tier_eliminated.
    'c4450',  # Walking Mausoleum — ~59m ambient structure, not a target
}


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
V3_GHOST_EXCLUDE_TARGET_PREFIXES = {
    'c2040',  # Juvenile Scholar          — confirmed freeze, April 2026
}

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
V3_MAP_PREFIX_TARGET_EXCLUDES = {
    'm60_': {
        # v0.24.101: c5110 Maris' Tendril LIFTED — "open the floodgates"
        # variety pass. The m60_ block was added at v0.20.x to fix a
        # Limveld CTD caused by the Maris path event chain referencing
        # Maris-cluster chrs that the v0.20 engine was scattering as
        # randomized placements. Engine has evolved substantially since;
        # if the Limveld CTD recurs in playtest, re-add c5110 here.
        # v0.24.101: c4181 Maris' Jellyfish also LIFTED for the same
        # reason — paired with the global V3_EXCLUDE_TARGET_PREFIXES
        # lift above. The other Maris-cluster chrs (Sprout/Bats/Envoys)
        # stay blocked for now — separate ship calls.
        # 'c5110',  # Maris' Tendril — lifted v0.24.101
        # 'c4181',  # Maris' Jellyfish — lifted v0.24.101
        'c4481',  # Miranda Sprout
        'c4200',  # Man-Bat
        'c4201',  # Operatic Bat
        'c3610',  # Oracle Envoy
        'c3620',  # Oracle Envoy (Large; Cathedral)
    },
    # v0.23.04.1: indoor-MSB block list — chrs whose vanilla spawn requires
    # an outdoor environmental context that doesn't exist inside tunnels,
    # caves, mines, or catacombs. Without the context, the chr's spawn
    # script either silently no-ops (resulting in invisible/inert Parts)
    # or fails initialization mid-load (CTD on cell streaming).
    #
    # NIGHTREIGN TUNNEL MAP TAXONOMY (v0.23.71 audit):
    #   m20_xx, m21_xx — Fallingstar Beast boss-arena tiles. NOT generic
    #       tunnels; each is a 1-chr boss room with c4680 + occasional
    #       Mausoleum escorts. Vanilla puts a GIGA here (Fallingstar Beast),
    #       so GIGA is fine. No size/anim restrictions needed.
    #   m32_xx — Limgrave-Tunnels-style mine complexes. 60-90 chrs each,
    #       composed of M-humanoid grunts (Wandering Noble, Foot Soldier,
    #       Misbegotten) and S-quadruped Strays. Vanilla GIGA: none.
    #       Vanilla XXL: c4460 Flame Chariot at m32_20 + c4600 Troll at m32_20.
    #   m34_xx — Caelid/Catacomb-style large underground complexes.
    #       100-150 chrs each, M-humanoid grunts dominant + S-imps + S-strays
    #       + L-aquatic Spirit Jellyfish swarms (m34_00 has 20+ vanilla
    #       Jellyfish — aquatic IS the design intent here). Vanilla XXL/GIGA:
    #       c4171 Giant Putrid Flesh (m34_00), c4630 Runebear (m34_10),
    #       c4580 Giant Wormface (m34_20). All large-chr placements are
    #       hand-authored arena slots with hand-tuned navmesh; broader
    #       tunnel corridors don't accommodate GIGA pathfinding.
    #   m43_xx — caves/mines. Same protection profile as m32_.
    #   m47_xx — catacombs. Same protection profile as m32_.
    #
    # CHR-LEVEL EXCLUSIONS (apply to all tunnel prefixes m32_/m34_/m43_/m47_):
    #   c4481 Miranda Sprout — confirmed CTD in seed 887995 m47_70 pi=8
    #     (Bloodhound-Knight-guarded catacomb entrance). Same root cause
    #     as v0.21 castle edge-sentinel CTD: c4481's spawn handler iterates
    #     the surrounding sprout-cluster and indexes into a per-cluster
    #     anim table; when the cluster is empty (no other Mirandas nearby),
    #     the index lookup falls through into invalid memory. Outdoors with
    #     cluster co-members it works; indoors solo it crashes.
    #
    # SIZE/ANIM-CLASS EXCLUSIONS (m32_ + m34_):
    # v0.23.71: Astel-Naturalborn-in-a-tunnel freeze. User playtest at
    # m32_10 pi=49 — c4620 (GIGA giga_boss, post_dlc_dump source) placed
    # in tunnel. Astel's primary moveset is short-range teleports computed
    # via navmesh queries; tunnel navmesh has limited node graph + low
    # ceiling clearance, teleport destination resolution hangs or loops
    # without resolving → game freezes (not CTDs) mid-combat. Distinct
    # failure class from the cinematic-FX CTDs (Fortissax/Metyr) — this
    # is AI state-machine deadlock rather than asset preload failure.
    #
    # General principle: GIGA + giga_boss + flying_dragon chrs are
    # designed for open-air boss arenas, not corridor combat. Even when
    # they don't freeze, they clip into ceilings, can't path properly,
    # and feel wrong. Block them at the source — much less surgical than
    # waiting for each specific freeze report.
    #
    # Carve-outs we considered but didn't apply:
    #   - m34_20 Wormface arena. Vanilla has c4580 GIGA Giant Wormface
    #     here, so the slot could in theory receive a GIGA replacement.
    #     But m34_20 is the SOURCE for that slot — the rando doesn't
    #     need to PLACE a GIGA there to preserve variety. Blocking
    #     receipt is safe.
    #
    # Future candidates to audit and potentially add here: heritage flying
    # chrs in tunnels (c4210 Warhawk, c3860 Avionette, c5090 Gravebird).
    # Their tag family is 'humanoid' or 'quadruped_large' (mis-tagged
    # — they DO fly in-game), so the size filter below doesn't
    # catch them. If hangs or stuck-in-ceiling reports appear, add their
    # c-prefixes explicitly.
    'm32_': {
        'c4481',  # Miranda Sprout — needs outdoor sprout-cluster context
        # v0.23.71 tunnel size/anim block — see comment above
        'c4500',  # Flying Dragon — GIGA, can't path corridors
        'c4501',  # Decaying Ekzykes — GIGA flying_dragon
        'c4503',  # Glintstone Dragon — GIGA flying_dragon
        'c4505',  # Ancient Dragon — GIGA flying_dragon
        'c4510',  # Borealis Magma Wyrm — GIGA flying_dragon
        'c4580',  # Giant Wormface — GIGA giga_boss
        'c4620',  # Astel, Naturalborn of the Void — GIGA giga_boss, teleport-hang
        'c4660',  # Fire Giant — GIGA giga_boss
        'c4680',  # Full-Grown Fallingstar Beast — GIGA flying_dragon
        'c4910',  # Magma Wyrm — GIGA quadruped_large (post-v0.23.71 retag)
        'c4911',  # Great Wyrm — GIGA giga_boss
        'c5860',  # Greyoll — GIGA quadruped_large
    },
    'm34_': {
        'c4481',  # Miranda Sprout — needs outdoor sprout-cluster context
        # v0.23.71 tunnel size/anim block — see comment above
        'c4500',  # Flying Dragon
        'c4501',  # Decaying Ekzykes
        'c4503',  # Glintstone Dragon
        'c4505',  # Ancient Dragon
        'c4510',  # Borealis Magma Wyrm
        'c4580',  # Giant Wormface — note: m34_20 has this as SOURCE, fine
        'c4620',  # Astel
        'c4660',  # Fire Giant
        'c4680',  # Full-Grown Fallingstar Beast
        'c4910',  # Magma Wyrm
        'c4911',  # Great Wyrm
        'c5860',  # Greyoll
        # v0.24.86-patch3: heritage size-L target ban for m34_ tunnels.
        # m34_xx rooms are tight arenas (low slot_roughness.n10);
        # vanilla chrs are M-sized humanoids and S-quadrupeds. L
        # heritage imports clip arena walls and the engine freezes
        # movement. Catalogue empirically as observed.
        'c7100',  # Ancient Hero of Zamor — L size_class, hit_height
                  #   2.6m. Empirical freeze: seed 923630
                  #   m34_30_00_00 pi=12 (vanilla c3970 Azula
                  #   Beastman M-Ruins-Boss slot, n10=74).
    },
    'm43_': {
        'c4481',  # Miranda Sprout — needs outdoor sprout-cluster context
    },
    'm47_': {
        'c4481',  # Miranda Sprout — needs outdoor sprout-cluster context
    },
}

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
V3_PREFER_CANONICAL_VARIANTS = True


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

    return resolved


def load_data():
    # v0.23.34: globals declared at function top so all later assignments work,
    # even those in nested conditional blocks earlier in the function.
    global V3_EXCLUDE_TARGET_PREFIXES, V3_NIGHT_BOSS_CALIBER_TARGETS, V3_NIGHT_BOSS_STRICT_TARGETS

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
    global V3_MP_SAFE_BLOCKLIST
    _mp_blocked = set()
    _mp_blocked_by_source = {}
    for cp, t in tags.items():
        src = t.get('_source')  # None for unsourced — treated as non-vanilla
        if src not in V3_VANILLA_NR_SOURCES:
            _mp_blocked.add(cp)
            _mp_blocked_by_source.setdefault(src or '<no _source>', []).append(cp)
    V3_MP_SAFE_BLOCKLIST = _mp_blocked
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
    global V3_ARENA_ONLY_TARGETS
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
        print(f"V3_ARENA_ONLY_TARGETS: force-lifted -{len(_force_lift)} "
              f"MMV nightlord imports ({sorted(_force_lift)})")

    # v0.23.72: PROBE_TARGET_VARIANT application. After all variant data
    # is loaded (heritage + MMV + post_dlc_dump), if PROBE_TARGET_VARIANT
    # is set, narrow V3_AVOID_VARIANT_NPC_IDS to leave ONLY the target
    # variant eligible within its c-prefix. See the constant definition
    # near line 1290 for workflow notes.
    global V3_AVOID_VARIANT_NPC_IDS
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
    # v0.27.6: cap policy is now "4 across the board" — every
    # miniboss-tier chr is capped at 4, overriding the v0.27.3 cap=6
    # default AND every pre-existing hand-tuned 1/2/8 (Elder Lion 8->4;
    # the singular-boss 1/2 values raised to 4). Power-of-2 ceiling;
    # pairs with the floor=1 (guarantee 1, allow up to 4). Exempt: the
    # _LIFTED_V0_24_65 defensive cap=1 chrs (bug-blast-radius limits,
    # not feel-tuning) keep their cap.
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
        # v0.27.6: 4 across the board — override any prior cap. As of
        # v0.27.8 there is no exemption: the _LIFTED_V0_24_65 defensive
        # cap=1 mechanism was removed, so every miniboss-tier chr —
        # c4140/c4441/c4601/c4811/c5930/c6220 included — is capped at 4.
        if V3_UNIQUE_TARGET_CAPS.get(_cp) != 4:
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
        if V3_UNIQUE_TARGET_CAPS.get(_cp) != 40:
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
    global V3_SOTE_PREFIXES
    V3_SOTE_PREFIXES = {_cp for _cp, _t in tags.items()
                        if isinstance(_t, dict)
                        and (_t.get('origin_game') == 'SoTE'
                             or _t.get('sote_eligible') is True)}

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
    global V3_RIDER_PREFIXES, V3_MOUNT_PREFIXES
    V3_RIDER_PREFIXES = set()
    V3_MOUNT_PREFIXES = {_cp for _cp, _t in tags.items()
                         if isinstance(_t, dict)
                         and _t.get('mount_role') == 'mount'}
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
    global _V3_SLOT_POI_CLUSTERS
    _clusters_path = _data_path('slot_poi_clusters.json')
    if os.path.isfile(_clusters_path):
        try:
            with open(_clusters_path, encoding='utf-8') as f:
                _clusters_data = json.load(f)
            _V3_SLOT_POI_CLUSTERS = _clusters_data.get('clusters', {})
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
    else:
        _V3_SLOT_POI_CLUSTERS = None

    return roster, tags


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


def compatibility_preflight(target_chr_dir):
    """v0.23.72-late: comprehensive compatibility check rolling up all the
    things that have to be true before a rando run will work without CTDs.

    Returns a dict:
        {
            'status': 'ok' | 'warn' | 'fail',  # worst severity across checks
            'summary': 'short headline string',
            'checks': [
                {
                    'id': 'check_id',
                    'name': 'human-readable name',
                    'severity': 'ok'|'info'|'warn'|'fail',
                    'message': 'what this means for the user',
                    'detail': 'longer explanation / suggested action',
                },
                ...
            ],
            'asset_packs': <output of detect_asset_packs>,
        }

    Severities cascade: 'fail' = will crash, fix before generating. 'warn' =
    will generate something but likely degraded. 'info' = informational.
    'ok' = no issue.

    Suitable for rendering as a banner at the top of the Generate tab, or
    as a textual report a user can copy/paste when asking for help (or when
    sharing their config with a friend they're packaging a build for).
    """
    import os

    checks = []
    target = (target_chr_dir or '').strip()

    # === Check 1: target chr/ dir exists ===
    if not target:
        checks.append({
            'id': 'target_chr_dir_set',
            'name': 'Target chr/ folder configured',
            'severity': 'warn',
            'message': "No me3 profile chr/ folder set. Compatibility detection skipped.",
            'detail': ("Open the 'chr/ Inventory' tab and point 'Target chr/ folder' "
                       "at your me3 profile's chr/ subfolder so the rando can verify "
                       "your installed chr assets."),
        })
        return {
            'status': 'warn',
            'summary': "Compatibility check incomplete — target chr/ folder not set.",
            'checks': checks,
            'asset_packs': {},
        }
    if not os.path.isdir(target):
        checks.append({
            'id': 'target_chr_dir_exists',
            'name': 'Target chr/ folder exists',
            'severity': 'fail',
            'message': f"Target chr/ folder doesn't exist: {target}",
            'detail': "Check the path on the 'chr/ Inventory' tab — there's a typo or the directory was moved.",
        })
        return {
            'status': 'fail',
            'summary': "Target chr/ folder path is broken.",
            'checks': checks,
            'asset_packs': {},
        }
    checks.append({
        'id': 'target_chr_dir_exists',
        'name': 'Target chr/ folder exists',
        'severity': 'ok',
        'message': target,
        'detail': '',
    })

    # === Check 2: asset packs status ===
    packs = detect_asset_packs(target)

    # Roll up: any pack enabled + requires_external + missing chrs is a problem
    for pack_id, info in packs.items():
        if not info.get('enabled'):
            continue
        if not info.get('requires_external'):
            continue
        det = info.get('detected', 0)
        exp = info.get('expected', 0)
        if exp == 0:
            continue
        name = info.get('description', pack_id)
        if det == 0:
            checks.append({
                'id': f'pack_{pack_id}',
                'name': f"Pack: {name}",
                'severity': 'fail',
                'message': f"Enabled but ZERO of {exp} chr-prefixes present in target.",
                'detail': (f"This pack is enabled in the rando config but the chr files "
                           f"aren't installed in {target}. Either install the mod (URL: "
                           f"{info.get('url') or 'see CHANGELOG'}), copy its chr files via "
                           f"the 'chr/ Inventory' tab, or disable the pack in its _meta block."),
            })
        elif det < exp:
            n_missing = exp - det
            preview = ', '.join(info.get('missing', [])[:5])
            more = (f" (+{n_missing - 5} more)" if n_missing > 5 else '')
            checks.append({
                'id': f'pack_{pack_id}',
                'name': f"Pack: {name}",
                'severity': 'warn',
                'message': f"{det}/{exp} chr-prefixes present — {n_missing} missing.",
                'detail': (f"Missing: {preview}{more}. Use chr/ Inventory → Diagnose for the "
                           f"full list. Slots that would have rolled these chrs will fall back "
                           f"to vanilla."),
            })
        else:
            checks.append({
                'id': f'pack_{pack_id}',
                'name': f"Pack: {name}",
                'severity': 'ok',
                'message': f"All {exp} chr-prefixes present.",
                'detail': '',
            })

    # === Check 3: DLC ownership signal ===
    # If any enabled pack has origin_game=SoTE chrs, the user needs SoTE
    # in their NR install. We can't directly check NR install — but we
    # can check if the DLC-origin chrs are present (with valid chrbnds)
    # in the target. The detect_asset_packs above checks all chrs as a
    # batch; here we slice by origin_game to be specific about *what* is
    # missing when it's DLC-origin content.
    sote_packs_with_issues = []
    for pack_id, info in packs.items():
        if not info.get('enabled'):
            continue
        if not info.get('requires_external'):
            continue
        ob = info.get('origin_breakdown', {})
        n_sote = ob.get('SoTE', 0)
        if n_sote and info.get('missing'):
            # Need to look at which missing chrs are SoTE-origin — load
            # the pack JSON to cross-reference.
            try:
                # Find the matching pack file by description (clunky but works)
                here = os.path.dirname(os.path.abspath(__file__))
                fname_map = {
                    'heritage_pack_v1': 'heritage_pack.json',
                    'mmv_imports_v1': 'mmv_imports.json',
                }
                fname = fname_map.get(pack_id)
                if not fname:
                    continue
                with open(_data_path(fname), encoding='utf-8') as f:
                    pack_data = json.load(f)
                tags = pack_data.get('tags', {})
                sote_missing = [cp for cp in info['missing']
                                if (tags.get(cp, {}).get('origin_game') == 'SoTE')]
                if sote_missing:
                    sote_packs_with_issues.append((info.get('description', pack_id),
                                                    sote_missing))
            except Exception:
                pass
    if sote_packs_with_issues:
        for desc, sote_missing in sote_packs_with_issues:
            preview = ', '.join(sote_missing[:5])
            more = (f" (+{len(sote_missing) - 5} more)" if len(sote_missing) > 5 else '')
            checks.append({
                'id': 'dlc_sote_assets',
                'name': "SoTE DLC chr assets",
                'severity': 'warn',
                'message': f"{len(sote_missing)} SoTE-origin chrs missing in '{desc}'.",
                'detail': (f"These chrs need Shadow of the Erdtree DLC assets. Either install "
                           f"SoTE locally and re-extract chr files via UXM, or the rando will "
                           f"fall back to vanilla on those slots. Affected: {preview}{more}"),
            })

    # === Roll-up status ===
    severities = [c['severity'] for c in checks]
    if 'fail' in severities:
        status = 'fail'
        summary = "Rando will likely CTD — fix the items below before generating."
    elif 'warn' in severities:
        status = 'warn'
        summary = "Rando will run but with degraded coverage — see warnings below."
    else:
        status = 'ok'
        summary = "All compatibility checks passed."

    return {
        'status': status,
        'summary': summary,
        'checks': checks,
        'asset_packs': packs,
    }


def plan_bulk_chr_import(source_chr_dir, target_chr_dir,
                          include_disabled_packs=False,
                          source_script_dir=None, target_script_dir=None):
    """v0.23.72-late: 'copy everything we can use' planner.

    Surveys every known asset pack (heritage_pack, mmv_imports, etc.), gathers
    the union of all c-prefixes declared by enabled packs (or all if
    include_disabled_packs=True), and returns a plan showing exactly which
    chr files would be copied from source → target.

    v0.23.72-late+: also plans script-dir AI luabnd imports. ER chrs ported
    into heritage_pack without their AI Lua scripts run on .behbnd alone,
    which lacks phase-state latching and produces the c5210-class "phase
    transition loop" bug. The script-side import maps each c-prefix to
    its battle.luabnd / logic.luabnd files (cXXXX → XXX000_battle, etc.)
    and stages them from source script/ to target script/.

    Args:
        source_chr_dir: ER chr/ folder (the unpacked one).
        target_chr_dir: me3 profile chr/ folder (where files are copied to).
        source_script_dir: ER script/ folder. If None, defaults to a sibling
            of source_chr_dir (../script).
        target_script_dir: me3 profile script/ folder. If None, defaults to
            a sibling of target_chr_dir.

    This is complementary to the spoiler-driven import flow: that one copies
    just what's needed for ONE specific rando run. This one populates the
    target with EVERYTHING the rando might ever ask for across all configs,
    so the user only does it once and never sees CTDs (or AI-degraded fights)
    on cell-load.

    Returns a dict:
        {
            'in_source_missing_in_target': [(cp, [chr_files], [script_files], total_bytes), ...],
            'already_present_in_target': [cp, ...],
            'wanted_but_not_in_source': [(cp, pack_name, origin_game), ...],
            'per_pack_breakdown': {pack_id: {'wanted': N, 'have': N, 'copyable': N}},
            'script_dirs': {'source': ..., 'target': ...},  # resolved paths
            'totals': {
                'wanted_unique_prefixes': N,
                'already_present': N,
                'copyable_now': N,
                'unavailable': N,  # in pack but not in source
                'estimated_bytes': N,
                'script_files_copyable': N,  # NEW: # script files to be staged
            },
        }
    """
    import os, json, re
    from collections import defaultdict

    source = (source_chr_dir or '').strip()
    target = (target_chr_dir or '').strip()

    # Resolve script dirs — default to sibling of chr/. Heuristic only;
    # user can override. None values become empty strings (skip-script behavior).
    def _sibling_script(chr_dir):
        if not chr_dir: return ''
        parent = os.path.dirname(os.path.abspath(chr_dir))
        candidate = os.path.join(parent, 'script')
        return candidate if os.path.isdir(candidate) else ''

    src_script = (source_script_dir.strip() if source_script_dir
                  else _sibling_script(source))
    tgt_script = (target_script_dir.strip() if target_script_dir
                  else _sibling_script(target))
    # Don't insist tgt_script exists — execute_bulk_chr_import will create it.
    # But it does need to be DERIVABLE, so fall back to chr_dir-parent + 'script'
    # if the heuristic gave us empty.
    if not tgt_script and target:
        tgt_script = os.path.join(os.path.dirname(os.path.abspath(target)),
                                   'script')

    chr_re = re.compile(r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')
    # Script files use a numeric-prefix naming convention. A chr cNNNX's
    # battle/logic scripts are named after its MODEL: usually the chr's
    # own number (cNNNX -> NNNX00_*.luabnd, e.g. c5210 -> 521000,
    # c3252 -> 325200), but for a variant that shares its base model's
    # scripts, the BASE number (cNNNX -> NNN000, e.g. c5192 and c5193
    # both run 519000_battle.luabnd). So the lookup must try the chr's
    # own 4 digits first, then fall back to the base model (variant
    # digit forced to 0). v0.27.0: earlier code used only cp[1:5] and
    # silently failed to import scripts for every base-model-sharing
    # variant chr.
    # Both _battle and _logic are AI scripts (battle = combat brain,
    # logic = navigation/idle). Match both, with or without .dcx wrapper.
    script_re = re.compile(r'^(\d{4})\d{2}_(battle|logic)\.luabnd(\.dcx)?$')

    def list_chr_prefixes(d):
        if not d or not os.path.isdir(d): return set()
        out = set()
        for fn in os.listdir(d):
            m = chr_re.match(fn)
            if m: out.add(m.group(1))
        return out

    def list_chr_files_for_prefix(d, cp):
        if not os.path.isdir(d): return []
        out = []
        for fn in os.listdir(d):
            m = chr_re.match(fn)
            if m and m.group(1) == cp:
                out.append(fn)
        return sorted(out)

    def cp_to_script_prefix(cp, *indexes):
        """Resolve cp to the 4-digit key its scripts are indexed under.
        Tries the chr's own number (cp[1:5]) first, then the base-model
        number (cp[1:4]+'0'). `indexes` are the script dicts to probe
        for the literal key; if none contain it, the base key is used.
        E.g. c3252 -> '3252' (own script), c5192 -> '5190' (shares the
        c5190 base-model script)."""
        if len(cp) < 5:
            return None
        lit = cp[1:5]
        if any(lit in idx for idx in indexes):
            return lit
        return cp[1:4] + '0'

    # Pre-index script source files by chr prefix for fast lookup
    src_scripts_by_chr = defaultdict(list)
    if src_script and os.path.isdir(src_script):
        for fn in os.listdir(src_script):
            m = script_re.match(fn)
            if m:
                src_scripts_by_chr[m.group(1)].append(fn)

    # And target script files by chr prefix (for "already have" detection)
    tgt_scripts_by_chr = defaultdict(set)
    if tgt_script and os.path.isdir(tgt_script):
        for fn in os.listdir(tgt_script):
            m = script_re.match(fn)
            if m:
                tgt_scripts_by_chr[m.group(1)].add(fn)

    def list_script_files_for_prefix(cp):
        """Return list of script files in source for this c-prefix that
        AREN'T already in target. Compares basename ignoring .dcx wrapper
        (source may be uncompressed .luabnd while target is .luabnd.dcx)."""
        chr_prefix = cp_to_script_prefix(cp, src_scripts_by_chr,
                                         tgt_scripts_by_chr)
        if not chr_prefix: return []
        src_files = src_scripts_by_chr.get(chr_prefix, [])
        if not src_files: return []
        # Normalize for comparison: strip .dcx
        tgt_basenames = set()
        for tfn in tgt_scripts_by_chr.get(chr_prefix, set()):
            tgt_basenames.add(tfn[:-4] if tfn.endswith('.dcx') else tfn)
        out = []
        for sfn in sorted(src_files):
            base = sfn[:-4] if sfn.endswith('.dcx') else sfn
            if base not in tgt_basenames:
                out.append(sfn)
        return out

    source_have = list_chr_prefixes(source)
    target_have = list_chr_prefixes(target)

    # Gather wanted prefixes from every enabled pack. Reuse the KNOWN_PACKS
    # list from detect_asset_packs by parsing the pack JSONs directly.
    PACK_FILES = [
        'heritage_pack.json',
        'mmv_imports.json',
    ]
    wanted = {}  # cp → (pack_id, pack_name, origin_game)
    per_pack = {}

    for fname in PACK_FILES:
        path = _data_path(fname)
        if not os.path.isfile(path): continue
        try:
            with open(path, encoding='utf-8') as fh:
                pack = json.load(fh)
        except Exception:
            continue
        meta = pack.get('_meta', {})
        enabled = meta.get('enabled', True)
        if not enabled and not include_disabled_packs:
            continue
        # Some packs ship with base NR and don't need chr imports —
        # detect via requires_external_chr_assets metadata.
        if not meta.get('requires_external_chr_assets', True):
            continue

        pack_id = fname.replace('.json','').replace('_imports','_imports_v1')\
                       .replace('heritage_pack','heritage_pack_v1')
        pack_name = meta.get('user_facing_name') or pack_id
        tags = pack.get('tags', {}) or {}
        per_pack[pack_id] = {
            'name': pack_name,
            'wanted': len(tags),
            'have': sum(1 for cp in tags if cp in target_have),
            'copyable': sum(1 for cp in tags
                            if cp in source_have and cp not in target_have),
        }
        for cp, tinfo in tags.items():
            if cp not in wanted:
                wanted[cp] = (pack_id, pack_name,
                              (tinfo.get('origin_game') or '?'))

    # Categorize. Now we ALSO check for script-only updates: a chr might be
    # already-present-in-target (chrbnd exists) but missing AI scripts.
    # Such chrs should appear in in_source_missing_in_target with an empty
    # chr_files list but populated script_files — the c5210 case exactly.
    in_source_missing = []
    already_present = []
    wanted_not_in_source = []
    total_bytes = 0
    script_files_copyable_count = 0

    for cp in sorted(wanted.keys()):
        chr_files = []
        chr_bytes = 0
        if cp not in target_have:
            if cp in source_have:
                chr_files = list_chr_files_for_prefix(source, cp)
                chr_bytes = sum(os.path.getsize(os.path.join(source, f))
                                for f in chr_files)

        # Script files: always check, even for chrs already in target
        script_files = list_script_files_for_prefix(cp)
        script_bytes = 0
        if script_files and src_script:
            script_bytes = sum(os.path.getsize(os.path.join(src_script, f))
                                for f in script_files)
        script_files_copyable_count += len(script_files)

        cp_total_bytes = chr_bytes + script_bytes

        if cp in target_have and not script_files:
            # Fully covered: chr in target, no script work to do
            already_present.append(cp)
        elif chr_files or script_files:
            # Either chr files or script files to copy (or both)
            in_source_missing.append((cp, chr_files, script_files, cp_total_bytes))
            total_bytes += cp_total_bytes
        else:
            # Wanted, not in target, source doesn't have it either
            pack_id, pack_name, origin = wanted[cp]
            wanted_not_in_source.append((cp, pack_name, origin))

    return {
        'in_source_missing_in_target': in_source_missing,
        'already_present_in_target': already_present,
        'wanted_but_not_in_source': wanted_not_in_source,
        'per_pack_breakdown': per_pack,
        'script_dirs': {
            'source': src_script,
            'target': tgt_script,
            'source_exists': bool(src_script and os.path.isdir(src_script)),
        },
        'totals': {
            'wanted_unique_prefixes': len(wanted),
            'already_present': len(already_present),
            'copyable_now': len(in_source_missing),
            'unavailable': len(wanted_not_in_source),
            'estimated_bytes': total_bytes,
            'script_files_copyable': script_files_copyable_count,
        },
    }


def execute_bulk_chr_import(source_chr_dir, target_chr_dir, plan,
                             overwrite=False, progress_cb=None,
                             source_script_dir=None, target_script_dir=None):
    """v0.23.72-late: execute a plan returned by plan_bulk_chr_import.

    `progress_cb`, if given, is called as progress_cb(cp, fname, copied_bytes,
    total_bytes, status_str) for each file. Use to drive a GUI progress bar
    or to stream a log.

    v0.23.72-late+: also copies script-dir files when plan entries include
    them. Reads script_dirs from plan if source_script_dir/target_script_dir
    not explicitly provided.

    Returns a dict:
        {'files_copied': N, 'files_skipped': N, 'bytes_copied': N,
         'chr_files_copied': N, 'script_files_copied': N, 'errors': [...]}
    """
    import os, shutil
    source = (source_chr_dir or '').strip()
    target = (target_chr_dir or '').strip()

    # Resolve script dirs: prefer explicit args, fall back to plan, fall back
    # to nothing (no script copy).
    script_dirs = plan.get('script_dirs', {}) if plan else {}
    src_script = (source_script_dir.strip() if source_script_dir
                  else script_dirs.get('source', ''))
    tgt_script = (target_script_dir.strip() if target_script_dir
                  else script_dirs.get('target', ''))

    if not os.path.isdir(source):
        raise ValueError(f"Source dir doesn't exist: {source}")
    os.makedirs(target, exist_ok=True)
    if tgt_script:
        os.makedirs(tgt_script, exist_ok=True)

    files_copied = 0
    files_skipped = 0
    bytes_copied = 0
    chr_files_copied = 0
    script_files_copied = 0
    errors = []

    # Total bytes for progress calc — sum across plan entries
    total = sum(entry[-1] for entry in plan.get('in_source_missing_in_target', []))
    seen = 0

    def _copy_one(src_dir, dst_dir, fname, cp, kind):
        """Inner: copy one file. Returns (status, size). kind = 'chr' or 'script'."""
        nonlocal files_copied, files_skipped, bytes_copied
        nonlocal chr_files_copied, script_files_copied, seen
        src = os.path.join(src_dir, fname)
        dst = os.path.join(dst_dir, fname)
        try:
            sz = os.path.getsize(src)
        except OSError as e:
            errors.append(f"{kind} {fname}: stat failed: {e}")
            return 'error', 0
        seen += sz
        if os.path.exists(dst) and not overwrite:
            files_skipped += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'skip-exists ({kind})')
            return 'skip', sz
        try:
            shutil.copy2(src, dst)
            files_copied += 1
            bytes_copied += sz
            if kind == 'chr':
                chr_files_copied += 1
            else:
                script_files_copied += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'copied ({kind})')
            return 'copied', sz
        except Exception as e:
            errors.append(f"{kind} {fname}: {type(e).__name__}: {e}")
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'error: {e}')
            return 'error', sz

    for entry in plan.get('in_source_missing_in_target', []):
        # Entry shape: (cp, chr_files, script_files, total_bytes)
        cp = entry[0]
        chr_files = entry[1]
        script_files = entry[2] if len(entry) >= 4 else []
        # chr files from source chr dir
        for fname in chr_files:
            _copy_one(source, target, fname, cp, 'chr')
        # script files from source script dir (if it's available)
        if script_files and src_script and os.path.isdir(src_script) and tgt_script:
            for fname in script_files:
                _copy_one(src_script, tgt_script, fname, cp, 'script')
        elif script_files:
            errors.append(
                f"{cp}: {len(script_files)} script files NOT copied — "
                f"script source dir not available "
                f"(expected sibling of chr/, set explicitly to override)")

    return {
        'files_copied': files_copied,
        'files_skipped': files_skipped,
        'bytes_copied': bytes_copied,
        'chr_files_copied': chr_files_copied,
        'script_files_copied': script_files_copied,
        'errors': errors,
    }
def plan_roster_import(mmv_dir, er_dir, target_chr_dir,
                       target_script_dir=None):
    """v0.27.0: one-time roster-driven chr import planner.

    Builds the set of c-prefixes the rando may need on disk and works out,
    for each, where its asset files come from. This is the planner behind
    the GUI's "Import roster" flow (Diagnose + Import).

    The import set = the union of:
      * heritage pack chrs -- every c_prefix keyed in heritage_pack.json's
        `tags` (ER/cross-game enemies the rando references but vanilla NR
        does not ship assets for); and
      * MMV pack chrs -- every c_prefix keyed in mmv_imports.json's `tags`
        (cross-game boss ports; disjoint from the heritage prefixes).
    Vanilla nr_placed chrs are NOT in the set -- their files already ship
    with NR, so copying them is a no-op.

    v0.27.0: the heritage half reads heritage_pack.json, the single
    source of truth (regenerated by dev/build_heritage_pack.py), NOT the
    roster's per-variant `_heritage_imported` flags. detect_asset_packs
    reads the same file, so Diagnose and the compatibility report agree.

    Source routing, per c-prefix: look in `mmv_dir` first, fall back to
    `er_dir`. MMV-first is deliberate -- a chr that is an MMV port must
    get MMV's build of the asset (MMV re-authors some shared prefixes);
    ER is only the source for genuine ER-heritage chrs MMV doesn't ship.
    A chr found in neither dir is reported as unavailable (the user is
    missing a DLC or hasn't UXM-unpacked that game).

    `mmv_dir` and `er_dir` are GAME-ROOT folders (containing chr/, script/,
    sfx/, material/ as subdirs), not the chr/ subdir itself -- matching the
    GUI's existing "folder" convention.

    SFX / material are NOT planned here -- they are shared bundles that
    cannot be matched per-chr (sfxbnd_commoneffects etc.). The executor
    bulk-syncs those dirs separately. See execute_roster_import.

    Returns a dict:
        {
          'entries': [
             {'cp', 'origin' ('mmv'|'er'),
              'src_chr_dir', 'src_script_dir',
              'chr_files': [...], 'script_files': [...],
              'bytes': N}, ...],          # only chrs with something to copy
          'already_present': [cp, ...],   # chr + scripts already in target
          'unavailable': [(cp, wanted_by), ...],   # in neither source dir
          'target_dirs': {'chr', 'script'},
          'totals': {'wanted', 'already_present', 'copyable',
                     'unavailable', 'bytes', 'script_files',
                     'from_mmv', 'from_er'},
        }
    """
    import os, re, json
    from collections import defaultdict

    chr_re = re.compile(
        r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')
    script_re = re.compile(r'^(\d{4})\d{2}_(battle|logic)\.luabnd(\.dcx)?$')

    def _sub(root, name):
        """Resolve <root>/<name>, also accepting <root>/Game/<name>."""
        if not root:
            return ''
        root = root.strip()
        for cand in (os.path.join(root, name),
                     os.path.join(root, 'Game', name)):
            if os.path.isdir(cand):
                return cand
        return ''

    mmv_chr = _sub(mmv_dir, 'chr')
    er_chr = _sub(er_dir, 'chr')
    mmv_script = _sub(mmv_dir, 'script')
    er_script = _sub(er_dir, 'script')

    tgt_chr = (target_chr_dir or '').strip()
    if target_script_dir:
        tgt_script = target_script_dir.strip()
    elif tgt_chr:
        tgt_script = os.path.join(
            os.path.dirname(os.path.abspath(tgt_chr)), 'script')
    else:
        tgt_script = ''

    def _index_chr(d):
        """{c_prefix: [filenames]} for one chr dir."""
        idx = defaultdict(list)
        if d and os.path.isdir(d):
            for fn in os.listdir(d):
                m = chr_re.match(fn)
                if m:
                    idx[m.group(1)].append(fn)
        return idx

    def _index_scripts(d):
        """{4-digit prefix: [filenames]} for one script dir."""
        idx = defaultdict(list)
        if d and os.path.isdir(d):
            for fn in os.listdir(d):
                m = script_re.match(fn)
                if m:
                    idx[m.group(1)].append(fn)
        return idx

    mmv_chr_idx = _index_chr(mmv_chr)
    er_chr_idx = _index_chr(er_chr)
    mmv_script_idx = _index_scripts(mmv_script)
    er_script_idx = _index_scripts(er_script)
    tgt_chr_idx = _index_chr(tgt_chr)
    tgt_script_idx = _index_scripts(tgt_script)

    # --- assemble the wanted set: heritage_pack tags + MMV pack tags ---
    # v0.27.0: the heritage half reads heritage_pack.json, NOT the
    # roster's per-variant `_heritage_imported` flags. Those two used
    # to be independent sources for the same question ("which heritage
    # chrs does the rando need on disk?") and drifted apart — the
    # Diagnose flow (this function) and the compatibility report
    # (detect_asset_packs, which reads heritage_pack.json) disagreed by
    # 10+ c-prefixes. heritage_pack.json is now the single source of
    # truth, regenerated from the four-set diff by
    # dev/build_heritage_pack.py. detect_asset_packs already reads it;
    # routing this function through the same file means the two reports
    # cannot disagree. The roster's `_heritage_imported` flag is left
    # in place but is no longer consulted by the import path.
    wanted = {}  # cp -> human label of what wants it
    try:
        heritage = json.load(open(_data_path('heritage_pack.json'),
                                   encoding='utf-8'))
        for cp in (heritage.get('tags') or {}):
            wanted.setdefault(cp, 'heritage pack chr')
    except Exception:
        pass
    try:
        mmv = json.load(open(_data_path('mmv_imports.json'),
                              encoding='utf-8'))
        for cp in (mmv.get('tags') or {}):
            wanted.setdefault(cp, 'MMV pack')
    except Exception:
        pass

    def _scripts_to_copy(cp, src_script_idx):
        """Source script files for cp not already in target (basename
        compare, ignoring the .dcx wrapper).

        v0.27.0 bugfix: a chr cNNNX's battle/logic scripts are named
        after the chr's MODEL, which is sometimes the chr's own number
        (cNNNX -> NNNX00, e.g. c3252 -> 325200) and sometimes the
        base-model number when the variant shares the base model's
        scripts (cNNNX -> NNN000, e.g. c5192/c5193 Spider Scorpion both
        run 519000_battle.luabnd, indexed under '5190'). The old key
        cp[1:5] only handled the first case, so every variant chr that
        shared a base-model script (last digit != 0) silently got no AI
        script imported -- it ran behbnd-only. The fix tries the literal
        key first, then falls back to the base-model key. This raised
        heritage-pack script coverage from 43/71 to 67/71."""
        if len(cp) < 5:
            return []
        # try the chr's own number, then fall back to its base model
        src = src_script_idx.get(cp[1:5])
        sp = cp[1:5]
        if not src:
            sp = cp[1:4] + '0'
            src = src_script_idx.get(sp, [])
        if not src:
            return []
        tgt_bases = set()
        for tfn in tgt_script_idx.get(sp, []):
            tgt_bases.add(tfn[:-4] if tfn.endswith('.dcx') else tfn)
        return sorted(fn for fn in src
                      if (fn[:-4] if fn.endswith('.dcx') else fn)
                      not in tgt_bases)

    entries = []
    already_present = []
    unavailable = []
    tot_bytes = 0
    tot_scripts = 0
    from_mmv = from_er = 0

    for cp in sorted(wanted):
        # MMV-first source routing.
        if cp in mmv_chr_idx:
            origin, src_chr, src_script_dir, src_script_idx = (
                'mmv', mmv_chr, mmv_script, mmv_script_idx)
        elif cp in er_chr_idx:
            origin, src_chr, src_script_dir, src_script_idx = (
                'er', er_chr, er_script, er_script_idx)
        else:
            unavailable.append((cp, wanted[cp]))
            continue

        src_idx = mmv_chr_idx if origin == 'mmv' else er_chr_idx
        chr_files = ([] if cp in tgt_chr_idx
                     else sorted(src_idx.get(cp, [])))
        script_files = _scripts_to_copy(cp, src_script_idx)

        if not chr_files and not script_files:
            already_present.append(cp)
            continue

        b = 0
        for fn in chr_files:
            try:
                b += os.path.getsize(os.path.join(src_chr, fn))
            except OSError:
                pass
        for fn in script_files:
            try:
                b += os.path.getsize(os.path.join(src_script_dir, fn))
            except OSError:
                pass
        entries.append({
            'cp': cp, 'origin': origin,
            'src_chr_dir': src_chr, 'src_script_dir': src_script_dir,
            'chr_files': chr_files, 'script_files': script_files,
            'bytes': b,
        })
        tot_bytes += b
        tot_scripts += len(script_files)
        if origin == 'mmv':
            from_mmv += 1
        else:
            from_er += 1

    return {
        'entries': entries,
        'already_present': already_present,
        'unavailable': unavailable,
        'target_dirs': {'chr': tgt_chr, 'script': tgt_script},
        'totals': {
            'wanted': len(wanted),
            'already_present': len(already_present),
            'copyable': len(entries),
            'unavailable': len(unavailable),
            'bytes': tot_bytes,
            'script_files': tot_scripts,
            'from_mmv': from_mmv,
            'from_er': from_er,
        },
    }


def execute_roster_import(plan, mmv_dir, er_dir,
                          overwrite=False, progress_cb=None):
    """v0.27.0: execute a plan from plan_roster_import.

    Copies chr + script files (each entry carries its own resolved source
    dir, so MMV-origin and ER-origin chrs are handled in one pass), then
    bulk-syncs the sfx/ and material/ directories.

    SFX / material sync follows the same MMV-first, ER-fallback rule as
    the chr routing: if the MMV dir has an sfx/ (or material/) subdir it
    is used; otherwise the ER dir's is. These are bulk dir-to-dir copies
    -- the bundles are shared and not per-chr matchable. Idempotent
    skip-existing keeps re-runs cheap.

    `progress_cb`, if given, is called progress_cb(cp, fname, seen, total,
    status) per file, mirroring execute_bulk_chr_import.

    Returns a dict:
        {'chr_files_copied', 'script_files_copied', 'files_skipped',
         'bytes_copied', 'sfx_files_copied', 'material_files_copied',
         'errors': [...]}
    """
    import os, shutil

    tgt = plan.get('target_dirs', {})
    tgt_chr = (tgt.get('chr') or '').strip()
    tgt_script = (tgt.get('script') or '').strip()
    if not tgt_chr:
        raise ValueError("plan has no target chr dir")
    os.makedirs(tgt_chr, exist_ok=True)
    if tgt_script:
        os.makedirs(tgt_script, exist_ok=True)

    res = {'chr_files_copied': 0, 'script_files_copied': 0,
           'files_skipped': 0, 'bytes_copied': 0,
           'sfx_files_copied': 0, 'material_files_copied': 0,
           'errors': []}

    total = sum(e['bytes'] for e in plan.get('entries', []))
    seen = 0

    def _copy(src_dir, dst_dir, fname, cp, kind):
        nonlocal seen
        src = os.path.join(src_dir, fname)
        dst = os.path.join(dst_dir, fname)
        try:
            sz = os.path.getsize(src)
        except OSError as e:
            res['errors'].append(f"{kind} {fname}: stat failed: {e}")
            return
        seen += sz
        if os.path.exists(dst) and not overwrite:
            res['files_skipped'] += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'skip-exists ({kind})')
            return
        try:
            shutil.copy2(src, dst)
            res['bytes_copied'] += sz
            if kind == 'chr':
                res['chr_files_copied'] += 1
            else:
                res['script_files_copied'] += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'copied ({kind})')
        except Exception as e:
            res['errors'].append(f"{kind} {fname}: {type(e).__name__}: {e}")
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'error: {e}')

    for e in plan.get('entries', []):
        cp = e['cp']
        for fn in e['chr_files']:
            _copy(e['src_chr_dir'], tgt_chr, fn, cp, 'chr')
        if e['script_files'] and e['src_script_dir'] and tgt_script:
            for fn in e['script_files']:
                _copy(e['src_script_dir'], tgt_script, fn, cp, 'script')
        elif e['script_files']:
            res['errors'].append(
                f"{cp}: {len(e['script_files'])} script files NOT copied "
                f"-- no script source/target dir resolved")

    # --- SFX + material bulk sync (MMV-first, ER-fallback) ---
    def _pick_subdir(name):
        for root in (mmv_dir, er_dir):
            if not root:
                continue
            for cand in (os.path.join(root.strip(), name),
                         os.path.join(root.strip(), 'Game', name)):
                if os.path.isdir(cand):
                    return cand
        return ''

    tgt_parent = os.path.dirname(os.path.abspath(tgt_chr))
    for name, key in (('sfx', 'sfx_files_copied'),
                      ('material', 'material_files_copied')):
        src_dir = _pick_subdir(name)
        if not src_dir:
            continue
        dst_dir = os.path.join(tgt_parent, name)
        os.makedirs(dst_dir, exist_ok=True)
        for fn in sorted(os.listdir(src_dir)):
            sp = os.path.join(src_dir, fn)
            if not os.path.isfile(sp):
                continue
            dp = os.path.join(dst_dir, fn)
            if os.path.exists(dp) and not overwrite:
                res['files_skipped'] += 1
                continue
            try:
                sz = os.path.getsize(sp)
                shutil.copy2(sp, dp)
                res[key] += 1
                res['bytes_copied'] += sz
            except Exception as ex:
                res['errors'].append(
                    f"{name}/{fn}: {type(ex).__name__}: {ex}")
    return res




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

    v0.23.72-late: bank_to_prefixes / loose_to_prefixes / mode dropped from
    signature (see pick_target_cp docstring).

    v0.24.21: `gates` parameter — threads through to pick_target_cp.
    See engine/state.py.

    v0.24.21 (Phase 5): `run_ctx` parameter — threads runtime
    bookkeeping (unique counters / reservations) through. See
    engine/runctx.py."""
    target_cp = pick_target_cp(
        recipient_cp, tags,
        prefix_variants, prefix_count, recipient_is_boss, rng,
        target_count=target_count, slot_y=slot_y,
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
        run_ctx=run_ctx)
    if target_cp is None:
        return None, None
    # v0.27.13: if this slot was reserved for a specific variant group
    # (group-floor pass in _compute_unique_reservations), read that
    # group back out of the reservation dict and pin the variant pick
    # to it. The reservation value is a (cp, group) tuple for grouped
    # reservations, a bare cp string otherwise. run_ctx.unique_reservations
    # is the same dict pick_target_cp's early-return consults.
    _pinned_group = None
    if (run_ctx is not None and slot_msb_name is not None
            and slot_pi is not None):
        _rv = run_ctx.unique_reservations.get((slot_msb_name, slot_pi))
        if isinstance(_rv, tuple) and _rv[0] == target_cp:
            _pinned_group = _rv[1]
    target_variant = pick_variant_for_tier(target_cp, recipient_is_boss,
                                            prefix_variants, rng, tags=tags,
                                            run_ctx=run_ctx,
                                            pinned_group=_pinned_group)
    if target_variant is None:
        # v0.23.04.1: All variants for this c-prefix were filtered out
        # (e.g., empty-name phantom-only variants). Return (None, None)
        # so the caller's existing target_cp-None guard preserves the
        # slot vanilla. Better than crashing in swap_plan.append, and
        # better than silently picking an invalid variant.
        return None, None
    return target_cp, target_variant


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
V3_TARGET_PLACEMENT_CAP = 50

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
V3_FRAGILE_SENSITIVE_TARGETS = {
    'c3470',  # Albinauric (cartwheel) — v0.20.17 (Madness Camp freeze)
    'c3610',  # Oracle Envoy (M grunt) — v0.20.39
    'c4070',  # Wolf                    — v0.20.44 (batch validation;
              #                          true 4-legged S quadruped)
    'c4071',  # White Wolf              — v0.20.44 (same family)
    'c4080',  # Rat                    — v0.20.39
    'c4090',  # Giant Rat              — v0.20.39
    'c4101',  # Large Demi-Human       — v0.20.17 (Madness Camp freeze)
    'c4150',  # Basilisk               — v0.20.38
    'c4160',  # Large Stray            — v0.20.36 (Stray family freeze)
    'c4161',  # Stray                  — v0.20.36
    'c4164',  # Large Bloodbane Stray  — v0.20.36
    'c4165',  # Bloodbane Stray        — v0.20.36
    'c4166',  # Large Rotten Stray     — v0.20.36
    'c4230',  # Small Land Octopus     — v0.20.32 (aquatic anim on land)
    'c4300',  # Wandering Noble        — v0.20.23 (m32_20 encampment freeze)
    'c4440',  # Land Squirt            — v0.20.36 (poison-pod freeze)
    'c4442',  # Land Squirt Variant    — v0.24.92-patch13. Family-
              #   uniformity demotion to match c4440 base. Same M
              #   aquatic-grunt profile; was unclassified previously
              #   without empirical justification. If c4442 turns out
              #   to be MORE permissive than c4440 (different AI that
              #   handles fragile slots fine), it can be removed —
              #   but family-uniformity is the default. c4441 Land
              #   Squirt Boss is intentionally NOT added — miniboss
              #   tier filters to different slot pool already.
    'c4570',  # Wormface (XL grunt)    — v0.20.30 (playtest freeze report).
              # Not the Giant (c4580 night_boss) — only the regular XL
              # Wormface is in this set. c4580 is boss-tier and wouldn't
              # land at fragile slots anyway via the existing tier filter.
    'c4630',  # Runebear (XXL field_boss) — v0.20.36
    'c4680',  # Fallingstar Beast (GIGA flying_dragon) — v0.20.36
    # v0.23.72-late: Maris' Tendril re-added (was here v0.20.55-69 before
    # the v0.20.69 promotion to EXCLUDED). User playtest reports that at
    # non-fragile slots, Tendril's friendly-fire on grunts creates
    # genuinely fun strategic moments — bait grunts into the tendril
    # sweeps. SENSITIVE classification gates it to non-fragile slots
    # only, which sidesteps the "tendril anchor confusion at narrow/
    # cluttered slots" failure mode that motivated v0.20.55.
    'c5110',  # Maris' Tendril (L Maris boss whip-tendril) — v0.23.72-late
    # v0.23.07: dragons lifted from V3_EXCLUDE_TARGET_PREFIXES with
    # uniqueness cap. Adding to SENSITIVE so the existing fragile-slot
    # filter still keeps them off off-mesh / narrow / problem slots even
    # when the reservation pass is bypassed (e.g., if a non-reserved
    # slot happens to roll one — though cap should prevent that).
    'c4500',  # Flying Dragon (Unscaled) — v0.23.07
    'c4501',  # Decaying Ekzykes (Unscaled) — v0.23.07
    'c4503',  # Borealis the Freezing Fog — v0.23.07
    'c4505',  # Flying Dragon (Small) — v0.23.07
    'c4510',  # Ancient Dragon — v0.23.07
    'c4910',  # Magma Wyrm — v0.23.07
    'c4911',  # Great Wyrm Theodorix — v0.23.07
    # c5193 Spider Scorpion (small) — was here from v0.20.38. LIFTED
    #   v0.27.36 (Alaric direction: "lift fully"). Re-enabled for SOTE-mode
    #   placement alongside c5190/c5192. The original v0.20.38 entry cited a
    #   CTD; if it recurs, re-add with a (seed, msb, pi) cite.
    'c5210',  # Divine Beast Dancing Lion — v0.20.33 (Miranda Blossom freeze)
    'c5522',  # Stray                  — v0.20.36
    'c5523',  # Stray                  — v0.20.36
    'c5860',  # Ghostflame Dragon (GIGA flying_dragon) — v0.20.36
    # c3160 Funeral Steed — was here from v0.20.50; PROMOTED in v0.20.69
    #   to V3_EXCLUDE_TARGET_PREFIXES (paired-chr breaks-everywhere).
    # c4950 Tibia Mariner — was here from v0.20.50; PROMOTED in v0.20.69
    #   to V3_EXCLUDE_TARGET_PREFIXES (paired-chr breaks-everywhere).
    'c5820',  # Great Red Bear (XXL field_boss quadruped_large) — v0.20.51
              #   (user: "giant red bear broken"). Same fragility profile
              #   as c4630 Runebear (also XXL quadruped_large move_type=13).
              #   Bear-class scripted-intro pattern — XXL bear-class chrs
              #   appear to have the same "wake from sleep" or anchor-pose
              #   intro animation that fails at non-vanilla slot geometry.
              #   The regular M Bear (c6031) is a grunt without the boss-
              #   tier scripted intro and is a separate test.
    'c6031',  # Bear (M grunt) — v0.23.86 resolves the c5820 "separate
              #   test" open question. User reported "lot of frozen
              #   small bear" — confirms the regular grunt Bear shares
              #   the family's fragility despite being grunt-tier and
              #   M-sized. Bear-anim-rig is quadruped_large even at
              #   the M size class; the rig mismatch may explain why
              #   it fails at slots designed for M humanoid/quadruped
              #   chrs.
    # c4460 Flame Chariot — was here from v0.20.53; PROMOTED in v0.20.69
    #   to V3_EXCLUDE_TARGET_PREFIXES (multi-part chr breaks-everywhere).
    'c6060',  # Goat (S quadruped mt=4) — v0.20.54 (user: "sheep broke" —
              #   user identified this as "sheep" but the only goat/sheep
              #   c-prefix in the roster is c6060 Goat; small white-ish
              #   quadrupeds visually look sheep-ish). Confirms the
              #   move_type=4 small-quadruped predicted-broken cluster
              #   (rats, wolves, basilisks, strays — all small mt=4
              #   quadrupeds in SENSITIVE). Adds another data point to
              #   that rule: small mt=4 quadrupeds are reliably broken.
    'c4290',  # Bloodhound Knight (S humanoid mt=4) — v0.20.55 (user:
              #   "C4270 bloodhound knight immediate CTD"). User typed
              #   c4270 but called it bloodhound knight; c4290 IS the
              #   Bloodhound Knight in roster, c4270 is Elder Lion.
              #   Assumed typo for c4290 based on visual identification.
              #   Bloodhound Knight in vanilla has rapid 4-limb dash anim
              #   (the "bloodhound step" weapon art mirrors this) and is
              #   tagged mt=4. Confirms the small-mt=4 broken cluster
              #   even for humanoid-tagged enemies that primarily
              #   four-limb-locomote.
    'c4481',  # Miranda Sprout (M misc mt=None) — v0.20.55 (user: "c4481
              #   sensitive"). Same chr family as c4480 Miranda Blossom
              #   (BROKEN, the original v0.20.33 Dancing Lion freeze
              #   trigger). Sprout is the smaller plant-pod variant.
              #   Both Miranda variants share the bloom-stationary-attack
              #   anim that's tied to specific arena geometry.
    # c5110 Maris' Tendril — was here from v0.20.55; PROMOTED in v0.20.69
    #   to V3_EXCLUDE_TARGET_PREFIXES (boss-component breaks-everywhere).
    # c5190 + c5192 Spider Scorpion (L) — were here from v0.20.55 (user
    #   reported "c5190 CTD" / "c5192 CTD"). LIFTED v0.27.36 (Alaric
    #   direction: "lift fully"). Re-enabled for SOTE-mode placement with
    #   c5193. If the CTD recurs, re-add with a (seed, msb, pi) cite.
    'c4650',  # Dragonkin Soldier (Ice Lightning) (XXL large_boss_ground
              #   mt=12) — v0.20.56 (user: "c4650 CTD"). Confirms the
              #   mt=12 100%-broken predictor (Dancing Lion was the
              #   only previous mt=12 entry, also BROKEN). Both are
              #   XXL large_boss_ground arena bosses with sessile
              #   stationary-attack patterns; they need flat arena
              #   geometry to function, breaking at non-vanilla slots.
    'c4270',  # Elder Lion (L quadruped_large mt=4) — v0.20.56 (user:
              #   "c4270 CTD"). User had earlier typo'd this c-prefix
              #   when reporting Bloodhound Knight; subsequent direct
              #   test confirms c4270 ALSO broken. Mid-tier lion-class
              #   chr — shares anim family with c5210 Dancing Lion
              #   (XXL, BROKEN). The lion anim family appears broken
              #   across size classes.
    'c4021',  # Royal Revenant (XL quadruped_large mt=4) — v0.20.56
              #   (user: "c4021 sensitive but works as guardian golem").
              #   Bigger boss-tier version of c4020 Royal Revenant.
              #   User noted that some c4021 placements visually appear
              #   as Guardian Golem (similar hunched-large silhouette)
              #   and those work — but the c-prefix as a whole is
              #   unreliable. Marking SENSITIVE conservatively. Could
              #   investigate variant-level filtering if Royal-Revenant-
              #   variant-specific gating turns out to matter, but for
              #   now the c-prefix is excluded entirely.
    'c4960',  # Giant Skeleton Torso (S quadruped mt=1) — v0.20.56 (user:
              #   "c4960 CTD"). Half-skeleton dragging on hands —
              #   unusual locomotion (no legs, drag-walk on arms).
              #   The chr's mt=1 + drag-anim doesn't gracefully handle
              #   non-vanilla slot geometry.
    'c4241',  # Giant Fingercreeper (GIGA giga_boss mt=1) — v0.20.56
              #   (user: "I think ok terrain-wise but just causes a
              #   crash if there's too many on top of each other").
              #   Different failure mode from typical SENSITIVE — the
              #   chr handles individual slot terrain fine but crashes
              #   when multiple instances spawn in same cluster /
              #   overlapping positions. Marking SENSITIVE conservatively
              #   until cluster-density limiter mechanism exists. TODO:
              #   add per-cprefix max-instance-per-cluster cap which
              #   would let c4241 spawn safely (1 per cluster cap).
    'c2271',  # Crab (S aquatic mt=None) — v0.20.56 (user: "small crab
              #   also sensitive"). Confirms small-aquatic-on-land
              #   broken pattern (cf c4080 Rat, c5193 Spider Scorpion
              #   small, c4230 Small Land Octopus). The aquatic family
              #   on land doesn't render correctly; the chr's idle/walk
              #   anims expect water surface they can't find.
    'c4280',  # Giant Ant (L quadruped mt=4) — v0.20.76 (user: "encampment
              #   got a big frozen ant"). Demoted from SAFE_CONFIRMED.
              #   The L+ mt=4 size cutoff rule (v0.20.57) held for
              #   non-insectoid large quadrupeds (crabs, hippo, crayfish,
              #   royal revenant L) but breaks for the multi-leg
              #   insectoid locomotion at encampment scaffolding/stake
              #   geometry — same class of failure as c4281 Skull Plate
              #   Giant Ant which is EXCLUDED for rubble locomotion. Open
              #   overworld c4280 placements work fine; the failure
              #   mode is encampment-specific authored unevenness.
    # c3320 Silver Tear — was added here in v0.20.77 (suspected
    #   encampment CTD culprit). v0.20.79 RE-PROMOTED back to
    #   SAFE_CONFIRMED. The actual encampment CTD was attributed to
    #   c4171 Giant Putrid Flesh and c6031 Bear M (both demoted
    #   v0.20.78); audit and user assessment cleared Silver Tear.
    'c4171',  # Giant Putrid Flesh (XXL large_boss_ground) — v0.20.78.
              #   Demoted from SAFE_CONFIRMED. v0.20.60 user CTD
              #   "big purple gaseous sphere near flask church" was
              #   partially-addressed by retiring from
              #   OFF_MESH_PREFERRED_TARGETS, but kept in SAFE on the
              #   theory that off-mesh placement was the issue. Wrong
              #   theory — c4171 broke at ground-level encampment slots
              #   too (5 landings in user's overworld-encampment CTD
              #   maps per v0.20.76 audit). The XXL air-emergence intro
              #   anim is the actual problem regardless of slot
              #   position. Smaller c4170 Putrid Flesh stays SAFE for
              #   now (no CTD evidence yet), but is on the watch list.
    'c6031',  # Bear (M quadruped_large mt=13) — v0.20.78. Demoted
              #   from SAFE_CONFIRMED. v0.20.57 SAFE addition was
              #   "closes the mt=13 stragglers" — based on the
              #   M-bear-OK / XXL-bear-broken split. v0.20.78 user
              #   audit at overworld-encampment CTD identified
              #   multiple c6031 landings at encampment-themed Limveld
              #   slots (Demi-Human, Godrick Soldier, Rotten Stray
              #   sources). The bear-class fragility split now refines
              #   to: bears generally fragile at encampments
              #   regardless of tier — the bear-on-uneven-geometry
              #   failure is independent of the scripted-intro one
              #   that affected the XXL bears.
    'c3181',  # Red Wolf of Radagon (L quadruped mt=4) — v0.20.82.
              #   Demoted from SAFE_CONFIRMED. User spawn-CTD near
              #   Mountaintop pointed at m60_42_38_10 pi=7 placement
              #   (Albinauric Archer src in Mountaintop Ruins area).
              #   c3181 has the Caria Manor scripted Radagon-transform
              #   intro — same failure class as c4630 Runebear / c5820
              #   Great Red Bear (already SENSITIVE for scripted-intro
              #   reasons). The L+ mt=4 size cutoff rule held for
              #   plain L wolves; this is a separate failure mode.
    'c3730',  # Graven School (L humanoid mt=0) — v0.20.85. Demoted
              #   from SAFE_CONFIRMED. User: "we gotta give the
              #   sensitive treatment to sphere of faces". Spotted in
              #   Limveld at a Banished Knights healthbar slot —
              #   visually striking but the floating-sphere-of-fused-
              #   faces locomotion doesn't fit standard humanoid slot
              #   geometry. SAFE classification was from v0.20.58
              #   min-risk batch (single obs); didn't hold up under
              #   real-seed encampment-class exposure.
    'c4281',  # Skull Plate Giant Ant (XL quadruped_large, loco=5) —
              #   v0.24.89-patch11. DEMOTED from V3_EXCLUDE_TARGET_PREFIXES
              #   where v0.19.31 had it as a workaround for missing per-chr
              #   terrain filtering. Same locomotion=5 multi-leg-insect-on-
              #   rubble failure mode as c4240/c4241; treating c4281
              #   differently was exception-by-history. SENSITIVE routes
              #   to FRAGILE_SAFE_CONFIRMED slots, sidestepping the rubble
              #   geometry that originally motivated the exclusion.
    'c4240',  # Fingercreeper (XL multi-leg insectoid) — v0.20.87.
              #   Demoted from SAFE_CONFIRMED. User overworld CTD on
              #   v0.20.85 same-run as the c7100 ghost screenshot;
              #   audit identified c4240 as the most pattern-match
              #   suspect. Same multi-leg insectoid failure family as
              #   demoted c4280 Giant Ant and EXCLUDED c4281 Skull
              #   Plate Giant Ant. Original "big hand safe" obs from
              #   v0.20.41 was a non-fragile slot; doesn't hold at
              #   fragile-class slots (encampments, cathedral
              #   approaches, Limveld POI uneven authored geometry).
              #   c4250 Small Fingercreeper remains SAFE for now —
              #   on watchlist as next likely demotion if user
              #   reports continued similar CTDs.
    'c3860',  # Avionette (locomotion=5 spider-jump) — v0.23.89. User
              #   playtest seed 397159: substituted at m30_30 pi=16
              #   (where vanilla c4040 Slug worked fine) and froze.
              #   The slot is geometrically healthy (area_5m=78, reach=11,
              #   on a thin floor poly with leaf_y=4.75u) — none of the
              #   polygon/AABB fragility rules can flag it. Failure is
              #   chr-side: loco=5 spider-jump can't navigate the thin
              #   floor poly that c4040's ground-crawler handles fine.
              #   Treating Avionette as fragile-sensitive routes it to
              #   slots where vanilla placed similar chrs (empirical
              #   compatibility), sidestepping the loco=5/thin-poly
              #   mismatch we can't predict geometrically.
}


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
    'c4961',  # [Revenant] Sebastian (M humanoid mt=None) — safe.
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

# v0.20.61: maps where slot_terrain.json's off-mesh classification is a
# false positive — the navmesh extraction missed valid navigable floors,
# so the slots got tagged off-mesh despite being genuinely navigable.
# Effect: slots in these maps bypass the V3_OFF_MESH_SLOTS membership
# check.
#
# v0.20.64: now MOSTLY MOOT. T2.6 (off-mesh-slot fragility) was retired
# in is_fragile_slot, so off-mesh slots are no longer fragile by that
# tier. The override list now only suppresses the soft SENSITIVE-only
# check at off-mesh slots — meaning slots in these maps allow the FULL
# pool (including SENSITIVE) at non-fragile slots. Kept for completeness
# and reversibility, but new entries shouldn't generally be needed.
#
# Each entry is a map prefix that matches all weather/time variants
# (Limveld m60_xx procedurals are 5-variant — _00, _10, _20, _30, _50).
#
# Discovery flow: user reports a specific in-game location where the
# enemy population looks "all off-mesh-preferred" (jellies, slugs, bats,
# imps, fleshes) — that's the visible signature of slot_terrain over-
# tagging the map. Cross-ref the spoiler placement counts to identify
# which m60_xx maps have anomalously-high off-mesh-preferred ratios
# (typical baseline ~20%; false-positive maps run 50-60%+).
V3_OFF_MESH_FALSE_POSITIVE_MAP_PREFIXES = ()  # RETIRED in v0.20.66 — see below.

# RETIREMENT NOTE (v0.20.66):
# This list previously held maps where slot_terrain.json's off-mesh
# classification was a false positive (cathedral-interior maps where the
# navmesh extractor missed the floor mesh). When v0.20.47 made off-mesh
# slots fragile (T2.6), the override prevented over-restriction.
#
# v0.20.64 retired T2.6 — off-mesh slots stopped being fragile. The soft
# SENSITIVE-exclusion at off-mesh slots replaced the fragility approach.
# But the override was still applied to _load_off_mesh_slots(), meaning
# the soft SENSITIVE check ALSO didn't fire at override-listed maps.
#
# v0.20.65 spoiler audit: 60 SENSITIVE-classified c-prefixes (rats, wolves,
# basilisks, bloodhound knights, strays, etc.) landed at slots that ARE
# off-mesh per slot_terrain raw data BUT excluded by the override. Those
# placements were the CTD vector — SENSITIVE chrs at no-navmesh slots
# break exactly as their classification says.
#
# Retiring the list entirely. Both purposes the list served are now
# obsolete: (1) over-restriction protection — moot since off-mesh isn't
# fragile anymore; (2) entry-point growth — moot since v0.20.64's softer
# approach handles cathedrals correctly via SAFE_CONFIRMED dominance.
# Soft SENSITIVE check now uses full raw off-mesh data — 779 slots
# instead of 570 — restoring CTD prevention at all off-mesh slots.
#
# The variable name is kept (set to empty tuple) for traceability and
# easy reversal if needed. Old entries documented in v0.20.65 source
# history.


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
        # v0.20.61: skip maps in the false-positive override list — the
        # navmesh extraction tagged these as off-mesh erroneously.
        if any(msb.startswith(p) for p in V3_OFF_MESH_FALSE_POSITIVE_MAP_PREFIXES):
            continue
        for pi_str, info in slot_dict.items():
            if info.get('status') in V3_OFF_MESH_STATUSES:
                try:
                    out.add((msb, int(pi_str)))
                except ValueError:
                    pass
    V3_OFF_MESH_SLOTS = frozenset(out)
    return V3_OFF_MESH_SLOTS


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
# deliberately low: 1.5% miniboss (~50/seed), 0.2% night_boss (~7/seed,
# on top of the 23 dedicated NB-arena slots). Tune by direct module
# edit — same workflow as the OOPS_ALL_NB_* knobs.
#
# Excludes still apply: pick_target_cp subtracts V3_EXCLUDE_TARGET_
# PREFIXES from the pool BEFORE this tier filter, so dropping a chr
# (e.g. c6200 while its MMV import is incomplete) into that set keeps
# it out of every roll outcome — no separate field-pool plumbing needed.
V3_FIELD_UPGRADE_MINIBOSS_PCT = 0.015
V3_FIELD_UPGRADE_NIGHTBOSS_PCT = 0.002

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

def field_roll_tier_for(slot_msb_name, slot_pi):
    """Rolled effective tier ('grunt'|'miniboss'|'night_boss') for a
    non-catalogued field slot, or None if the slot IS catalogued (a
    boss/terrain/POI slot — left to its own catalog handling). Shared by
    pick_target_cp and the spoiler writer so both agree on the outcome."""
    if slot_msb_name is None or slot_pi is None:
        return None
    if (slot_msb_name, slot_pi) in V3_BOSS_SLOT_CATALOG:
        return None
    # v0.27.35: deterministic per-slot tier pin (skips the random roll).
    _pin = V3_FIELD_SLOT_TIER_PIN.get((slot_msb_name, slot_pi))
    if _pin is not None:
        return _pin
    r = _field_slot_roll(slot_msb_name, slot_pi)
    if r < V3_FIELD_UPGRADE_NIGHTBOSS_PCT:
        return 'night_boss'
    if r < V3_FIELD_UPGRADE_NIGHTBOSS_PCT + V3_FIELD_UPGRADE_MINIBOSS_PCT:
        return 'miniboss'
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
V3_ARENA_ONLY_TARGETS = {
    'c5210',  # Divine Beast Dancing Lion — XXL loco=0, needs flat arena
    # v0.20.9: Dragonkin Soldier (Ice Lightning). Both variants (Night Boss
    # npc=46500010, Noklateo npc=46500230) carry boss markers, so
    # pick_variant_for_tier returns one of them at any boss-marker slot.
    # The v0.20.7 CTD was traced to a c2130 Margit summon-script slot
    # (m45_51 pi=2 at position 0,0,1) where the failure was the slot, not
    # c4650. Allowing c4650 at real arenas should be safe.
    'c4650',  # Dragonkin Soldier — heritage XXL, boss-arena variants only
    # v0.20.75: Astel/Naturalborn of the Void. GIGA giga_boss. User
    # request: "yeah do it, its too big". Astel is a multi-tentacled
    # alien-octopus boss with a wide hitbox; its scripted intro
    # animation hovers from above and lands in the arena, requiring
    # significant vertical and horizontal clearance. Confirmed working
    # at outdoor open-arena slots (v0.20.41 user obs: "working astel
    # off in the distance"); confirmed broken at cathedral interior
    # (v0.20.69 m38_00 pi=51, addressed via V3_PROBLEM_SLOTS). The
    # field_boss tier classification let it land at miniboss / castle
    # / ruins-boss slots in v0.20.74 spoiler — those don't always have
    # the open floor area Astel needs. Restricting to boss-marker
    # variant slots only (Night Boss / Field Boss / Crater / Noklateo
    # qualifiers) where the arena is purpose-built. Smaller-tier slots
    # vanilla-preserve.
    'c4620',  # Astel - Naturalborn of the Void — GIGA, needs purpose-built arena
    # v0.20.80: Guardian Golem and Large Wormface. Both GIGA, both
    # SAFE-classified (heritage from early-version sweeps), both
    # repeatedly observed landing at non-boss-variant slots where
    # their size doesn't fit. v0.20.78 spoiler audit (user CTD at
    # spawn, no screenshot) showed:
    #   c4660: Cathedral interior slots (m38_00 pi=11 Oracle Envoy,
    #     m38_10 pi=19 Mausoleum Knight), Putrid Ancestral Follower
    #     Shaman slot (m43_30 pi=5), Banished Knight Evergaol-Halberd
    #     (m46_60 pi=3), 2× Giant Crab overworld slots.
    #   c4580: Lordsworn Captain Fort (m30_00 pi=17), Banished Knight
    #     (m49_10 pi=3), Highwayman (m60_42_37_10 pi=33).
    # Same fit-the-arena pattern that put c4620 Astel here in v0.20.75.
    # User: "Yeah you can ARENA_ONLY them both."
    #
    # v0.23.72-late+: TIGHTENED. The gate at line ~7759 was source-side
    # (recipient_is_boss = source c-prefix's tier classification), which
    # had false positives when a source c-prefix appears in some boss-
    # tier variants elsewhere. A second slot-marker-based gate at
    # ~line 7821 now also subtracts V3_ARENA_ONLY_TARGETS when the
    # destination slot's variant name lacks a V3_BOSS_NAME_MARKERS
    # token. The two gates layer — cheap source-side gate first, then
    # the slot-marker gate catches the false positives. Closes the
    # c4580 leaks documented above.
    # Chrs needing tighter restrictions (open-arena vs sub-arena
    # geometry) escalate to V3_NIGHT_BOSS_ONLY_TARGETS (excludes
    # Encampment/Evergaol sub-arenas) or V3_NIGHT_BOSS_STRICT_TARGETS
    # (the dedicated-NB-anchor-only gate).
    'c4660',  # Guardian Golem — GIGA, was SAFE-everywhere (heritage)
    'c4580',  # Large Wormface — GIGA, was SAFE-everywhere (heritage)
}

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
V3_NIGHT_BOSS_STRICT_TARGETS: set = set()


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
# STATUS (v0.26.x): OPTIONAL, MANUAL. The rando does NOT ship or patch
# a regulation.bin, and runtime regulation-patching was scoped and
# declined (it needs a WitchyBND/AES dependency that cuts against the
# mod's zero-setup direction — see the getSoul thread in dev notes).
# Rune rewards on relocated chrs are therefore intentionally left a bit
# wacky in the default experience. This table + emitter remain as an
# OPT-IN tool: a user who wants consistent rune drops can run
# dev/emit_getsoul_overrides.py and import the resulting CSV into their
# own regulation via Smithbox themselves. It is not part of any
# pipeline or release flow.
#
# Consumed by the CSV emitter only — never by the rando engine. If you
# edit these floors, regenerate data/npcparam_getsoul_overrides.csv
# (python3 dev/emit_getsoul_overrides.py).
V3_GETSOUL_TIER_FLOORS = {
    'nightlord':  4375,
    'night_boss': 3750,
    # v0.27.13: field_boss 2500 -> 1605. Re-derived (placement-weighted
    # vanilla median per tier) after the field_boss tier collapse pulled
    # c4021 Royal Revenant (-> miniboss) and c5170 Furnace Golem (->
    # night_boss) out of the tier. The only field_boss-tagged chr left
    # in nr_enemy_tags.json is c4450 Walking Mausoleum (target-excluded),
    # so the derived median is now just c4450's placement-weighted value.
    # field_boss is effectively a dead tier post-collapse — see
    # docs/OPEN_ISSUES.md for the question of dropping it from the floor
    # system entirely. Surfaced by
    # test_getsoul_overrides::test_floors_match_placement_weighted_medians.
    'field_boss': 1605,
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
V3_NIGHT_BOSS_CALIBER_TARGETS = {
    # ---- The 22 vanilla NR Night Boss bosses ----
    'c2130',  # Morgott (Fell Omen)
    'c2500',  # Crucible Knight
    'c3050',  # Commander (Outland / Battlefield)
    'c3100',  # Bell Bearing Hunter / Elemer of the Briar
    'c3150',  # Night's Cavalry
    'c3250',  # Draconic Tree Sentinel
    'c3251',  # Tree Sentinel
    'c3560',  # Godskin Apostle
    'c3570',  # Godskin Noble
    'c4021',  # Royal Revenant (NR variant)
    'c4130',  # Demi-Human Queen
    'c4510',  # Ancient Dragon
    'c4580',  # Large Wormface
    'c4640',  # Ulcerated Tree Spirit
    'c4650',  # Dragonkin Soldier (Ice Lightning)
    'c4680',  # Full-Grown Fallingstar Beast
    'c4750',  # Grafted Monarch / Godrick
    'c4770',  # Valiant Gargoyle
    'c4911',  # Great Wyrm Theodorix
    'c4950',  # Tibia Mariner
    'c4980',  # Death Rite Bird
    'c5011',  # Golden Hippopotamus (Golden Wings, Night Boss variant)
    # ---- Field-boss-tier giants that read epic enough for NB arenas ----
    'c3181',  # Red Wolf of Radagon (heritage)
    'c3252',  # Loretta Tree Sentinel
    # v0.23.08: c4220 Giant Land Octopus + c4420 Giant Crayfish removed from
    # caliber. aquatic-family doesn't navigate NR's humanoid-anchored NB
    # arenas — they get picked, fail to spawn, leave the arena empty.
    # Confirmed on seed 821747 at m48_40 Morgott NB arena: c4220 picked, no
    # spawn. Both chrs remain valid targets at non-NB slots (their compat
    # range still includes plenty of field encounters).
    'c4241',  # Giant Fingercreeper (GIGA)
    # v0.27.13: c4450 Walking Mausoleum REMOVED from caliber. It is now
    # in V3_EXCLUDE_TARGET_PREFIXES (residual field_boss-tier cleanup),
    # so it can never be picked as an NB-arena target — this caliber
    # entry would be dead code and surface as a HIGH-severity finding in
    # dev/audit_placement_budget_consistency.py. Same dead-entry rule as
    # the v0.26.x c4910/c5010 cap removals.
    'c4460',  # Flame Chariot
    'c4500',  # Flying Dragon
    'c4501',  # Decaying Ekzykes
    'c4503',  # Borealis the Freezing Fog
    'c4505',  # Flying Dragon (Small)
    'c4561',  # Bloodbane Giant Crow
    'c4600',  # Troll
    'c4602',  # Snowfield Troll
    'c4603',  # Stonedigger Troll
    'c4620',  # Astel, Stars of Darkness
    'c4630',  # Runebear
    'c4660',  # Guardian Golem
    'c4800',  # Mohg the Omen (heritage)
    'c4810',  # Erdtree Avatar
    'c4910',  # Magma Wyrm
    'c5010',  # Golden Hippopotamus (field variant)
    'c5210',  # Divine Beast Dancing Lion (heritage)
    'c5820',  # Great Red Bear (heritage)
    'c5860',  # Ghostflame Dragon (heritage)
    'c7100',  # Ancient Hero of Zamor (heritage)
    # v0.23.11: ER heritage v1 batch — ER shardbearers + late-game NB-tier
    # bosses authored in er_heritage_imports.json. All are "true encounter"
    # caliber (ER plot bosses with full movesets and intro cinematics).
    # Adding here ensures they can land at NR's true Night Boss anchor
    # slots (m48_40, m49_xx, etc.) — without this, the source-side
    # caliber gate at NB slots subtracts them from the pool.
    'c2010',  # Margit, the Fell Omen
    'c2030',  # Rennala (Phase 1)
    'c2031',  # Rennala (Phase 2)
    'c2050',  # Radagon
    'c2060',  # Mohg, Lord of Blood
    'c2110',  # Maliketh
    'c2120',  # Malenia
    'c2131',  # Morgott (Phase 2)
    'c2160',  # Astel, Naturalborn of the Void (empirical anchor)
    'c2190',  # Godrick the Grafted
    'c2191',  # Godrick (Phase 2)
    'c2200',  # Godfrey / Hoarah Loux
    # v0.24.73: promoted to NB caliber after v0.24.72 tag backfill
    # gave Commander Gaius proper metadata (quadruped_large/XL).
    # SoTE field boss — fits the c4730 Starscourge Radahn /
    # c5230 Scadutree Avatar caliber slot (mounted/large humanoid
    # bosses with phase-style mechanics).
    'c5000',  # Commander Gaius (SoTE, boar-mounted centaur)
}


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
V3_UNIQUE_TARGET_CAPS = {
    # ----------------- cap = 1 (named, singular encounter) -----------------
    # v0.27.2: Storm King + Ancestor Spirit. Lifted from
    # V3_DEDICATED_ARENA_BOSS_CHRS this revision (see that set's docstring)
    # so they place at night_boss-tier world slots instead of being
    # arena-locked into the now-preserved NB arenas. cap=1 keeps each a
    # singular encounter. Alaric direction, 98-seed sim 2026-05-26.
    'c4670': 1,  # Ancestor Spirit — night_boss, was dedicated-arena only.
    'c7910': 1,  # Storm King — night_boss, was dedicated-arena only.
    # v0.27.13: Slave Knight Gael (DS3 MMV) — uncapped pre-v0.27.13, so
    # seed 333724 placed the c6200 "P2 (NB2)" asset 4x, three of them on
    # non-catalogued field slots — one on m60_44_39_20, the hawk-route
    # CTD. cap=1 makes Gael a singular encounter and routes the one
    # placement through the reservation pre-pass (quality night_boss-tier
    # slot). NB the asset audit still flags c6200 INCOMPLETE pending the
    # MMV bulk-import re-run; if it CTDs before then, the one-line bridge
    # is adding 'c6200' to V3_EXCLUDE_TARGET_PREFIXES (zero placements).
    'c6200': 1,  # Slave Knight Gael (DS3 MMV) — singular night_boss.
    # Dragons being lifted from V3_EXCLUDE_TARGET_PREFIXES in this revision —
    # uniqueness cap makes them safe by limiting failure rate to one die
    # roll. Each gets reserved at a quality slot via the reservation pass.
    'c4503': 1,  # Borealis the Freezing Fog — vanilla mountain-peak only;
                 # reservation pass picks high-altitude flat slot.
    'c4501': 1,  # Decaying Ekzykes — same Flying Dragon rig as c4500.
    # v0.27.13: c4500 cap removed. c4500 is in V3_EXCLUDE_TARGET_PREFIXES
    # (the "no sauce" flying-dragon ban), so this cap could never fire —
    # a cap on a target-excluded chr is a dead entry and surfaces as a
    # HIGH-severity finding in dev/audit_placement_budget_consistency.py.
    # Same dead-cap rule as the v0.26.x c4910/c5010 cap removals.
    # v0.26.x: c4910 Magma Wyrm cap removed — chr excluded from target
    # pool as a redundant archetype (c4911 Great Wyrm Theodorix is the
    # NB-tier same-shape variant). See V3_EXCLUDE_TARGET_PREFIXES
    # rationale near c4910 there.
    'c4911': 2,  # Great Wyrm Theodorix.
    'c4510': 2,  # Ancient Dragon — past playtest "spawned then disappeared"
                 # (seed 246135); cap=1 limits re-occurrence.
    # Lifted-and-tier-overridden in v0.23.06 (already field_boss tier);
    # cap=1 prevents 9+ Tree Spirits / 6+ Fallingstar Beasts per run.
    'c4640': 2,  # Ulcerated Tree Spirit
    'c4680': 2,  # Full-Grown Fallingstar Beast
    # v0.24.102: Tree-Sentinel-family (horse-lance bosses) capped at 1.
    # Seed 417416 baseline: 11 horse-mounted Tree-Sentinel-shaped placements
    # in one seed (4 Draconic + 2 Tree + 5 Loretta/Royal Carian Knight) —
    # visually overwhelming. Note c3252's c-prefix is shared between Loretta
    # Tree Sentinel and Royal Carian Knight variants, so cap applies to all
    # c3252 variants collectively.
    'c3250': 2,  # Draconic Tree Sentinel
    'c3251': 2,  # Tree Sentinel
    # v0.26.x: c3252 cap removed — chr excluded from target pool as a
    # redundant archetype (c3251 Tree Sentinel + c3250 Draconic Tree
    # Sentinel cover the XL-quadruped_large knight-on-horse archetype,
    # and the c3252 variants are all Royal Carian Knight rather than
    # the Loretta name the tag claimed). See V3_EXCLUDE_TARGET_PREFIXES
    # rationale near c3252 there.
    # v0.23.11: caps for boss-tier chrs that were originally promoted via
    # vanilla_promotions_v1 (retired v0.23.72-late — see CHANGELOG). Caps
    # prevent flooding since these had no playtest history at promotion
    # time. cap=1 also guarantees a quality slot via the reservation
    # pre-pass — if the chr is broken, the reservation slot stays vanilla
    # and the chr never appears (fail-safe). Increase caps after playtest
    # confirms each is well-behaved.
    'c4441': 1,  # Land Squirt (Boss) — XL large_boss_ground
    'c4442': 1,  # Land Squirt Variant — XL large_boss_ground
    'c4502': 1,  # Decaying Ekzykes-class Dragon — GIGA flying_dragon
    # v0.23.72-late: c4504 Elder Dragon Greyoll — NOT capped here; she's
    # in V3_EXCLUDE_TARGET_PREFIXES instead. The fight's defining mechanic
    # (kill the 4 ambient dragons to drain her HP) is script-driven via
    # EMEVD; without that chain initialized, placing her anywhere yields
    # an unkillable static dragon. Plus her size (XXL, hp=12440) is
    # non-arena-friendly. The Pass A name/tier corrections in
    # nr_enemy_tags.json are kept for spoiler-label hygiene — she's still
    # named "Elder Dragon Greyoll" wherever the engine references her,
    # she just never gets picked.
    # v0.23.72-late: c4641 entry REMOVED — c-prefix is in
    # V3_EXCLUDE_TARGET_PREFIXES (Weapon-Bequeathed Harmonia, Raid mode
    # boss). The cap was dead code, fully subsumed by the exclude. Was
    # left over from the vanilla_promotions_v1 misidentification of c4641
    # as "Tree Spirit (Unscaled, variant)".
    # v0.23.74: script-spawn boss-tier caps. After manual_promotions.json
    # was archived in v0.23.72-late, these chrs lost their target-pool
    # routing constraints and started flooding overworld tiles (seed 468558
    # produced 6 Nameless Kings, 5 Smelter Demons, 8 Grafted Scions, 4
    # Ancestor Spirits, 3 Frejas across Limveld — at least one of which
    # crashed the spirit-eagle approach intro). cap=1 here matches their
    # narrative singularity AND limits load-time failure rate to one die
    # roll per seed; if any of these chrs is broken at non-arena slots
    # (script_spawn chrs need EMEVD scaffolding to instantiate cleanly),
    # the reservation pass picks ONE quality slot for it and the rest of
    # the world is unaffected. Grafted Scion gets cap=2 because vanilla
    # already places multiples (Limgrave/Caelid tutorials) — it's clearly
    # tolerant of being placed twice without paired-only failure mode.
    # c4670 Ancestor Spirit kept at cap=1 (v0.24.102 revert)
    'c4670': 1,  # Ancestor Spirit
    'c4690': 2,  # Grafted Scion
    # v0.25.3: cap=1 → cap=2 for the 6 standalone heritage NBs.
    # c7910 Storm King (Nameless King's mount) stays at cap=1 — paired-
    # only failure mode, see existing comment below — so a 2nd c7900
    # Nameless King on a seed will appear on foot, but no Storm King
    # gets divorced from a rider.
    'c7700': 2,  # Gaping Dragon (DS1) — v0.25.3: 1→2
    'c7710': 2,  # Centipede Demon (DS1) — v0.25.3: 1→2
    # v0.26.x cleanup: c7800 cap REMOVED — dead code. The v0.25.3 1→2
    # raise was applied uniformly across the heritage NB roster, but
    # c7800 Duke's Dear Freja does not take a per-chr cap: it is a
    # vanilla nr_placed night_boss (reclassified from post_dlc_dump in
    # the v0.26.x byte-level MSB audit, which confirmed it IS real
    # vanilla content). It was also LIFTED from nr_missing_chr_files.json
    # that revision — the v0.24.44 asset-import 'no chrbnd' flag was a
    # false positive. c7800 is now a placeable night_boss, arena-gated
    # via V3_DEDICATED_ARENA_BOSS_CHRS / V3_ARENA_ONLY_TARGETS, and is
    # NOT in any exclude set. No cap needed (NB-tier vanilla chrs aren't
    # capped). Surfaced by `dev/audit_placement_budget_consistency.py`.
    # v0.26.x: heritage DS NB ceilings normalized to 2 alongside the
    # floor/ceiling cap split landing in this revision. The earlier
    # cap=2→3 bump (intended to compensate for cap=2 reservation
    # failures) is superseded by V3_RESERVATION_FLOORS guaranteeing
    # floor=1 per seed — a much easier-to-satisfy reservation target
    # than floor=2 or floor=3 was. With floor=1 reservation succeeding
    # reliably, ceiling=2 is the same uniform NB ceiling all other
    # NB-tier chrs get below.
    'c7820': 2,  # Smelter Demon (DS2)
    'c7900': 2,  # Nameless King (DS3)
    'c7910': 1,  # Storm King (DS3) — Nameless King's mount, paired-only
                 # in vanilla; cap=1 mirrors c7900's original baseline so
                 # they don't get divorced across multiple slots. Mount
                 # without rider likely useless/crash-prone in the same
                 # way Tibia's skeletons are without Tibia (paired-only
                 # failure mode). v0.26.x: explicitly NOT in
                 # V3_RESERVATION_FLOORS — c7910 only places when c7900
                 # pairs it; reserving independently could divorce them.
    'c7920': 2,  # Dancer of the Boreal Valley (DS3)
    # Supporting cast (c7711/c7712 Centipede Grubs, c7810 Freja Spiderling)
    # deliberately left UNCAPPED — they're minion-tier, not NB-caliber.
    # On watch list pending empirical evidence: if v0.23.74 testing
    # implicates them in load-time CTDs (Spiderling has no AI bank when
    # divorced from mother, same shape as Tibia skeletons), add caps here
    # or escalate to a heuristic auto-cap based on parent's paired-only
    # flag in nr_enemy_tags.json.
    # ----------------- cap = 2 (unnamed archetype) -----------------
    # v0.27.13: c4505 cap removed. c4505 is in V3_EXCLUDE_TARGET_PREFIXES
    # (the "no sauce" small flying-dragon ban) — a cap on a target-
    # excluded chr is dead code and surfaces as a HIGH-severity finding
    # in dev/audit_placement_budget_consistency.py. Same dead-cap rule
    # as the v0.26.x c4910/c5010 removals. (Former comment: "Smaller
    # dragon variant — vanilla uses in catacombs, cap=2 lets it appear
    # in two places" — moot now that c4505 is never a target.)
    # Frequency-driven caps from seed 394059 baseline (8-17 placements
    # per run before cap). Cap=2 normalizes "you might see one in the
    # north and one in the south" without becoming swarm.
    # v0.24.102: c4241 / c2270 / c2276 caps REMOVED (user req — undo all
    # crab/dog/bug caps; these critters can flood organically).
    'c4171': 2,  # Giant Putrid Flesh (Blood) (16)
    'c4170': 2,  # Giant Putrid Flesh
    'c4600': 6,  # Troll — v0.23.71: 2→6 (user req, "more trolls in overworld")
    # v0.23.72-late: c4601 Troll Knight added at cap=6 to match its
    # siblings. Previously had no cap entry — uncapped XXL field_boss
    # was rolling 25 placements per seed (Sentient Pest seed 35300),
    # contributing to a CTD near the Madness Tower POI at m60_44_38_00
    # where 3 Troll Knights spawned within 20u of each other replacing
    # a Commoner mob cluster, plus a Frenzied Nomad nearby — Madness
    # Tower EMEVD aggros the whole group simultaneously, exceeding the
    # asset/AI budget for the cell. Same cumulative-load failure mode
    # as the m34_10 tunnel CTD. Cap=6 brings c4601 in line with the
    # rest of the Troll family.
    'c4601': 6,  # Troll Knight
    'c4602': 6,  # Snowfield Troll — v0.23.71: 2→6
    'c4603': 6,  # Stonedigger Troll — v0.23.71: 2→6
    # v0.24.102: Elder Lion + Royal Revenant soft caps at 8. Seed 417416
    # baseline: Elder Lion 15/seed, Royal Revenant (miniboss) 20/seed —
    # high enough to feel like swarm-mode for two distinctive archetypes.
    # cap=8 keeps them frequent-but-bounded ("you'll see a handful per
    # seed" rather than "they're everywhere"). c4021 (the rare night-boss
    # Royal Revenant variant) intentionally NOT capped here — it's
    # arena-only via expects_boss_arena and was placing 0/seed already.
    'c4270': 8,  # Elder Lion (was uncapped, 15/seed)
    'c4020': 8,  # Royal Revenant (miniboss quadruped L, was uncapped, 20/seed)
    'c4630': 2,  # Runebear
    # v0.24.54: c3181 Red Wolf of Radagon cap=2 (user req — "and can
    # we cap red wolf at 2?"). Red Wolf is a quadruped field_boss
    # (size=L, anim=quadruped, loco=5); same archetype as Runebear
    # (c4630 cap=2). Multiple Red Wolves per seed felt over-frequent
    # in user playtest. Combined with the v0.24.54 m46_77 pi=8 Gate-4
    # fragile-locomotion rejection, this slot/chr pair now gets routed through
    # quality-slot reservation instead of organic random placement.
    'c3181': 2,  # Red Wolf of Radagon
    # v0.24.18: Red Bear cap=2. User req: "haunts my nightmares". Same
    # archetype as c4630 Runebear (XXL quadruped_large field_boss); cap=2
    # mirrors. c5820 also lives in V3_FRAGILE_SENSITIVE_TARGETS (scripted-
    # intro freeze class) — placements that DO land already get routed
    # away from fragile geometry.
    'c5820': 2,  # Great Red Bear
    # v0.24.63: c5860 Ghostflame Dragon cap=2. User playtest seed 618106
    # had 3 placements (m46_04 NB slot, m46_58 FB slot, m60_42_36_00
    # overworld) — felt over-frequent. c5860 is a heritage flying_dragon
    # (DS3 import); cap=2 matches the general pattern for unnamed
    # archetypes. The vanilla NR Flying Dragon at cap=1 (c4500) is named
    # / singular per expedition; Ghostflame Dragon is a heritage
    # variant, less iconic, so cap=2 allows "one north, one south" at
    # most.
    'c5860': 2,  # Ghostflame Dragon — heritage DS3 flying_dragon
    'c4660': 2,  # Guardian Golem (6)
    'c4810': 2,  # Erdtree Avatar (8)
    'c4220': 2,  # Giant Land Octopus
    'c4240': 2,  # Fingercreeper (XL — distinct from c4241 GIGA / c4250 S)
    # v0.23.11: c4480 dropped to cap=1. At cap=2, the reservation pre-pass
    # was scoring two specific slots highest (m30_30 pi=45 Guardian Golem
    # Fort, m38_00 pi=51 Guardian Golem Cathedral) and locking both in
    # every run — Miranda always landed at the same two interior fragile
    # slots, regardless of seed. cap=1 frees one of those slots for the
    # general boss-tier pool, restoring per-seed variety at standup-GG
    # placements.
    'c4480': 1,  # Miranda Blossom (7) — reservation lock-in fix
    'c4560': 2,  # Giant Crow (8)
    # v0.26.x: c5010 Golden Hippopotamus cap removed — chr excluded
    # from target pool as a redundant archetype (c5011 Golden
    # Hippopotamus (Golden Wings) is the NB-tier same-chr variant).
    # See V3_EXCLUDE_TARGET_PREFIXES rationale near c5010 there.
    'c4750': 2,  # Godrick the Grafted (Unscaled)
    'c3350': 2,  # Crystalian (10) — cluster spawner; cap might feel too
                 # restrictive in playtest, easy to remove if so.
    #
    # Vanilla cap=1 candidates deferred until playtest evidence:
    # 'c4620': 1,  # Astel, Stars of Darkness (3 baseline)
    # 'c4580': 1,  # Giant Wormface (1 baseline)
    # 'c4980': 1,  # Death Bird (1 baseline)
    #
    # v0.24.73: lifted MMVs get cap=1 as safety net per the same
    # rationale as v0.24.65 broken_runtime_chrs lift ("if any are
    # still broken under specific arena conditions the blast radius
    # is bounded"). One die roll per seed, reservation pre-pass picks
    # a quality slot, and if it stalls boss_clear_watchdog/preboss_
    # wake_timeout safety net catches it.
    # v0.25.3: heritage cap=1 → cap=2 (user req). Several seeds of
    # playtest data showed the cap=1 reservation-only routing meant
    # roughly half the heritage NB roster didn't appear in any given
    # seed (e.g. seed 154238 had c7800/c7820/c7920 all unplaced).
    # Bumping to cap=2 doubles the appearance budget while keeping
    # the bounded-failure safety property — 2 die rolls per seed
    # instead of 1, still recoverable if any chr is broken at scale.
    'c8300': 2,  # Dragonslayer Armor (DS3 MMV) — EXCLUDED, but cap kept: c8300 is a marquee NB / NB-caliber MMV, so the reservation policy (floor=1) requires a matching ceiling (floor⊆ceiling). Dormant while excluded; audit-allowlisted. v0.25.3: 1→2
    'c4511': 2,  # Lichdragon Fortissax (SoTE MMV)      — was globally excluded; v0.25.3: 1→2
    'c5030': 2,  # Romina, Saint of the Bud (SoTE MMV)  — was globally excluded; v0.25.3: 1→2
    'c5051': 2,  # Midra, Lord of Frenzied Flame (SoTE) — was globally excluded; v0.25.3: 1→2
    'c5200': 2,  # Metyr, Mother of Fingers (SoTE MMV)  — was globally excluded; v0.25.3: 1→2
    'c5000': 2,  # Commander Gaius (SoTE MMV)           — promoted to NB caliber; v0.25.3: 1→2

    # v0.25.3: previously-uncapped boss-tier caps. Audit (post-v0.25.2)
    # surfaced 14 uncapped night_boss + 7 uncapped field_boss chrs
    # using the default V3_TARGET_PLACEMENT_CAP=50. User direction:
    # cap the uncapped boss chrs. Crab/bug family (c2270/c2274/c2276
    # /c4241) explicitly skipped per v0.24.102 user preference
    # ("undo all crab/dog/bug caps; these critters can flood organically").
    #
    # Cap value rationale: principally driven by vanilla MSB anchor
    # count (how many vanilla Parts host this chr in nr_boss_slots
    # before randomization). The pattern roughly:
    #   1 vanilla anchor  → cap=1 (named singular)
    #   2-3 vanilla       → cap=2 (small archetype)
    #   4-6 vanilla       → cap=2 or 3 (named with multiple appearances)
    #   7+ vanilla        → cap=3 or higher (frequent archetype)
    # Where the chr is narratively-singular OR the existing source
    # comment ("deferred until playtest evidence") suggested cap=1,
    # cap=1 wins regardless of anchor count.

    # ----- Night boss (14 chrs) -----
    'c3050': 2,  # Commander (2 vanilla)
    'c2500': 2,  # Crucible Knight (Unscaled) — 7 vanilla anchors, 22 variants;
                 #   archetype (Sword / Spear / Pumpkin / Tree variants); cap=3
                 #   allows seeing 2-3 different sub-variants per seed
    'c4980': 2,  # Death Bird — v0.23.11 deferred-cap comment said cap=1
                 #   (1 vanilla baseline); actually 4 anchors per current
                 #   nr_boss_slots, so cap=2 matches Erdtree Avatar's pattern
    'c4130': 2,  # Demi-Human Queen (4 vanilla; she's narratively-singular
                 #   per encounter but appears 4× across NR maps as
                 #   variant queens)
    'c5810': 2,  # Demi-Human Swordmaster Onze — 1 vanilla anchor; named
                 #   singular. Plus involved in the m49_29 Tricephalos N1
                 #   companion bug — keeping at cap=1 minimizes blast radius
                 #   if a future arena-classification regression mis-places it
    'c4650': 2,  # Dragonkin Soldier (Ice Lightning) (3 vanilla)
    'c3100': 2,  # Elemer of the Briar (3 vanilla; narratively named but
                 #   the Briar Stalker pattern recurs)
    'c4770': 2,  # Gargoyle (3 vanilla, but Valiant Gargoyle pairs are
                 #   common at NB arenas; cap=2 prevents 4+ per seed)
    'c4580': 2,  # Giant Wormface — was 1 baseline; v0.26.x normalized to
                 #   ceiling=2 alongside other NB-tier chrs (uniform NB
                 #   ceiling=2 + floor=1 from V3_RESERVATION_FLOORS).
    'c3560': 2,  # Godskin Apostle (Unscaled) (2 vanilla; Apostle is the
                 #   Duo partner — see m48_70/m48_80 Duo arenas)
    'c3570': 2,  # Godskin Noble (Unscaled) — 1 vanilla anchor; Noble
                 #   appears only in the Duo, narratively rarer than Apostle
    'c5011': 2,  # Golden Hippopotamus (Golden Wings) (7 vanilla); larger
                 #   variant of c5010 (cap=2). cap=3 for the winged form.
    'c4353': 6,  # Leyndell Knight — 12 vanilla anchors, 29 variants,
                 #   only 2 reward variants. Tier-tagged night_boss but
                 #   plays as elite-grunt filler; cap=6 keeps frequency
                 #   bounded at "elite-tier filler" level (matches Troll
                 #   family cap=6 pattern). NOTE: tier review candidate —
                 #   this c-prefix may belong at miniboss or field_boss
                 #   tier rather than night_boss.
    'c2130': 2,  # Margit (2 vanilla; named arena boss, but also appears
                 #   as Marais variant — cap=2 covers both)

    # ----- Field boss (4 chrs; c2274/c2276/c4241 skipped per crab/bug exemption) -----
    'c7100': 2,  # Ancient Hero of Zamor (Base) (2 vanilla)
    'c4620': 1,  # Astel, Stars of Darkness — per v0.23.11 deferred-cap
                 #   comment (3 baseline, narratively-singular). cap=1.
    'c4811': 1,  # Erdtree Avatar Variant — 0 vanilla anchors (placement-
                 #   only via swap), variant sibling of c4810 Erdtree
                 #   Avatar (cap=2). cap=1 keeps the rare-variant feel.

    # =================================================================
    # v0.26.x tier-collapse flood caps. Per sim_cap_distribution.py run
    # immediately after the field_boss-tier collapse: 8 chrs surfaced as
    # uncapped floods (max=5 or 6 per seed) at their new home tier.
    # Alaric's spec: "leyndell for minis, 2 across the board for nbs"
    # — applied directly here as Leyndell-pattern cap=6 for miniboss
    # floods and cap=2 for the NB-tier promotions still missing a cap.
    # All 8 had cap=- (uncapped) pre-collapse; the collapse moved them
    # into pools where their organic placement frequency exceeds the
    # target. These caps bring them back into the same per-seed
    # frequency band as their tier peers (Leyndell at cap=6 averages
    # ~2/seed with max=4; NB cap=2 chrs in the same sim averaged
    # ~1.5/seed). Sim is upper-bound only — real engine has gates that
    # may reject some pairings; if any chr feels under-frequent in
    # actual playtest, easy to bump the cap up.
    'c4241': 2,  # Giant Fingercreeper (GIGA NB) — sim max=4, mean=2.0
    'c4800': 2,  # Mohg, the Omen (XL NB) — sim max=6 (Leyndell-level),
                 #   uncapped Remembrance boss; bring to NB headliner feel.
    'c5210': 2,  # Divine Beast Dancing Lion (XXL NB, arena_only) — sim
                 #   max=4, mean=2.4; the highest mean of any promoted
                 #   NB chr in the sim, so the cap actually engages here.
    'c2274': 6,  # Giant Sleep Crab (XL miniboss) — sim max=6 (matches
                 #   Leyndell exactly); cap aligns to that ceiling.
    'c2276': 6,  # Giant Death Crab (XXL miniboss) — sim max=5.
    'c4420': 6,  # Giant Crayfish (XXL aquatic miniboss, heritage) —
                 #   sim max=5; rounds out the aquatic-cluster caps with
                 #   c2274/c2276 above.
    'c5070': 6,  # Death Knight (M humanoid miniboss) — sim max=5. The
                 #   v0.24.47 "menace" promotion to field_boss was
                 #   reverted by the tier collapse; this cap restores
                 #   bounded-named-encounter behavior without
                 #   resurrecting the field_boss tier.
    'c5160': 6,  # Fire Knight (M humanoid miniboss, heritage) —
                 #   sim max=4 (already under cap=6 but flood-prone via
                 #   broad anim-compat eligibility); cap as safety net.
    'c3704': 6,  # Battlemage (L humanoid miniboss) — v0.27.0 cap audit:
                 #   uncapped, sim max=7 per seed. Leyndell-pattern cap=6
                 #   trims the spike to elite-filler band (user request).
    'c5260': 6,  # Golem Smith (L humanoid miniboss, heritage) — v0.27.0:
                 #   uncapped, sim spiked to 5-7/seed after the grunt->
                 #   miniboss retier. cap=6 to the miniboss flood band
                 #   alongside Battlemage (user request).

    # ----- v0.27.0 grunt caps (cap value corrected v0.27.13) -----
    # Centipede Grub feels over-present in playtest — not from raw
    # frequency (sim_per_run.py --grunts: c7711/c7712 both land at the
    # grunt-tier norm, ~14/seed, max ~27-29) but because the Grub aggros
    # from extreme range, so a normal count reads as a swarm. cap=4 cuts
    # felt presence well below the ~14 grunt-tier norm. (user request)
    # v0.27.13: cap restored to 4 — the v0.27.0 balance pass had left
    # these at 6; intended grunt-cap value is 4 (playtest confirmed).
    'c7711': 4,  # Centipede Grub
    'c7712': 4,  # Centipede Grub (variant)
    'c3664': 4,  # Cemetery Shade (grunt) — v0.27.0: uncapped, ~14/seed at
                 #   the grunt-tier norm but a playtest menace; cap=4 to
                 #   the grunt-cap band alongside c7711/c7712 (user req).
}


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
    """Shared predicate for "mirror-semantic" gates — those that
    pick_target_cp enforces at runtime AND that _score_slot_for_unique
    must replicate at reservation time. The reservation early-return
    in pick_target_cp (line ~8395, returns the reserved cp before any
    gate runs) bypasses runtime enforcement; without the mirror, the
    pre-pass commits placements that the runtime would have rejected.

    v0.24.27 introduced this predicate after the same bug-shape
    recurred three times:
      - v0.23.07: NB-caliber gate added → reservations bypassed it
      - v0.23.11: NB-strict gate added → reservations bypassed it
      - v0.24.24: V3_FORBIDDEN_BY_SOURCE_ANIM added → reservations
                  bypassed it (fixed in v0.24.26)
    Each fix mirrored the new gate into _score_slot_for_unique by hand.
    Easy to forget. By consolidating mirror-semantic gates into this
    predicate, both call sites get the gate for free, and future
    additions live in one place.

    Args:
        target_cp: candidate target c-prefix
        src_cp: vanilla c-prefix at this slot (= recipient_cp in the
            picker; = slot_info['source_cp'] in the scorer)
        src_variant_name: vanilla variant name at this slot (= slot_
            variant_name in the picker; = slot_info['source_variant_
            name'] in the scorer). May be '' or None.
        tags: tag database
        chaos_mode: NB-caliber gate tightens to NIGHT_BOSS_ONLY_TARGETS
            in chaos mode (caliber → strict subset). NB-strict and
            source-anim gates are geometric and don't honor chaos.
            Default False — the reservation path doesn't see
            chaos_mode (it's per-MSB), so the predicate is
            conservative by default. The runtime picker passes
            chaos_mode=True if the run is in chaos mode.
        msb_base: MSB filename (e.g. 'm45_01_00_00.msb'). Required
            for the quadruped-unsafe-slot gate (v0.24.31). If None,
            that gate is skipped — legacy callers that don't pass
            slot identity get pre-v0.24.31 behavior.
        pi: Part index integer. Required alongside msb_base for the
            quadruped-unsafe-slot gate.

    Returns:
        None  if (src, target) is allowed by all mirror-semantic gates.
        'nb_strict'             if rejected by NB-strict gate
        'nb_caliber'            if rejected by NB-caliber gate
        'forbidden_source_anim' if rejected by source-anim gate
        'quadruped_unsafe_slot' if rejected by quadruped-unsafe-slot gate
            (v0.24.31: target is loco=3 quadruped and (msb, pi) is in
            V3_QUADRUPED_UNSAFE_SLOTS catalog)
        'field_boss_at_strict_nb' if rejected by Gate 5.5 (v0.25.0-patch3:
            target is tier='field_boss' and slot is catalogued as
            tier='nightboss', scope='strict' — field-boss chrs lack
            the EMEVD wake-handshake integration strict NB arenas need)

    The caller distinguishes by reason because pick_target_cp's NB-
    caliber gate has empty-pool fallback semantics (caliber empties →
    caliber gate is dropped, original pool restored). NB-strict and
    source-anim are absolute (no fallback). The scorer doesn't care
    about reasons — any non-None means reject the reservation.

    NOT a complete picker gate set. Only the gates with mirror
    semantics are here. Picker-only gates (V3_ARENA_ONLY_TARGETS,
    V3_NIGHT_BOSS_ONLY_TARGETS, V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS,
    V3_NIGHT_BOSS_EXCLUDE_TARGETS, swap compat at scripted-
    intro slots) work on slot-side variant matching and don't need
    mirroring — the reservation pre-pass either won't pick a fragile
    target for those slots, or the rejected target will fail an
    earlier hard-rejection.
    """
    # Gate 1 (REMOVED v0.26.x): NB-strict was a variant-name string filter
    # that required source slots to contain "Night Boss" in their variant
    # name. Originally introduced (v0.23.11) as a "strictest geometric
    # gate" to keep XXL/GIGA chrs out of Field Boss slots whose arena
    # geometry couldn't accommodate them. Removed in v0.26.x: it was
    # masquerading as geometric but actually doing string matching, and
    # the real geometric concerns are covered by V3_ARENA_ONLY_TARGETS
    # (chrs needing arena geometry like Wormface), V3_FRAGILE_SENSITIVE_
    # TARGETS (chrs with rig issues on rough terrain like Ancient Dragon),
    # and the size_class compat checks in scoring. Per user
    # direction: "I want night bosses at field boss slots, as long as
    # they can traverse." The string filter was too restrictive — it
    # blocked NB chrs from ~all source slots in Limveld because almost
    # no source slot's variant name contains literally "Night Boss".
    # Sim showed Midra/Romina/Fortissax/etc. unplaceable at 65-81%
    # purely due to this gate. V3_NIGHT_BOSS_STRICT_TARGETS is now an
    # empty set; the population sites have been removed. If a specific
    # CTD pattern resurfaces (e.g., c4510 wingspan at Miranda Blossom),
    # add a targeted V3_FORBIDDEN_BY_SOURCE_ANIM rule with seed evidence
    # rather than resurrecting the variant-name filter.


    # Gate 2: NB-caliber (v0.23.07). At slots whose source variant
    # carries an NB marker, the target must be in the caliber set —
    # otherwise we'd place a Banished Knight at a Night Boss anchor
    # slot via a stray "Boss" marker variant. Chaos-overrideable: in
    # chaos mode, the set tightens to V3_NIGHT_BOSS_ONLY_TARGETS
    # (strict subset), giving the asymmetric "field giants don't
    # leak UP to NB slots but NB chrs leak DOWN" flow.
    if src_variant_name and any(m in src_variant_name
                                 for m in V3_NIGHT_BOSS_NAME_MARKERS):
        caliber_set = (V3_NIGHT_BOSS_ONLY_TARGETS if chaos_mode
                       else V3_NIGHT_BOSS_CALIBER_TARGETS)
        if caliber_set and target_cp not in caliber_set:
            return 'nb_caliber'

    # v0.27.28: Gate 3 (source-anim forbidden) REMOVED. It read the source
    # chr's family against V3_FORBIDDEN_BY_SOURCE_ANIM, but that table
    # has been empty ({}) since v0.24.x, so the gate never fired — it was
    # pure dead weight reading the now-expunged anim_class field. The
    # historical purpose (keep flying_dragon targets out of grounded-intro
    # giga_boss slots) belonged to the flying-vs-ground machinery, also
    # removed this version.

    # Gate 4: Locomotion-fragile-unsafe slot (v0.24.31, extended v0.24.32).
    # When the candidate target has fragile locomotion (the fragile_locomotion
    # tag, or locomotion=3) AND the (msb, pi) is catalogued in
    # V3_QUADRUPED_UNSAFE_SLOTS, reject UNLESS the slot has a verified-safe
    # reposition proposal. This catches empirically-observed spawn freezes
    # where biped-on-mesh slots turn out to be quadruped-off-mesh at the
    # wider sample radius these chrs use. NOT chaos-overrideable
    # (geometric/engine constraint, not thematic). Skipped if msb_base or
    # pi is None (legacy caller without slot identity).
    #
    # v0.24.32 release path: when an entry's reposition_proposed block
    # has playtest_verified=true, the gate is released for that slot.
    # The slot has been moved to a denser-navmesh position (via
    # slot_repositions.json) and quadrupeds at the new location have
    # been confirmed to spawn correctly. Unverified repositions (the
    # default) keep the gate active — repositioned slot is still safe
    # for bipeds, but the fragile-locomotion chrs remain blocked pending
    # playtest.
    #
    # v0.27.28: this gate used to read anim_class (reject_anim_classes per
    # slot, and a default `family.startswith('quadruped')` check). With
    # anim_class expunged, the "fragile locomotion" property it was a proxy
    # for is now carried explicitly by the fragile_locomotion tag (set on
    # the 70 former quadruped/quadruped_large chrs) — which crucially covers
    # the loco-0/loco-5 quadrupeds (Bear c6031, Runebear, etc.) that a pure
    # locomotion==3 check misses. The default branch keeps the loco==3 half
    # because it independently covers 4 non-quadruped chrs (Godskin
    # Apostle/Noble c3560/c3570, Revenant Follower c4000, Living Jar Warrior
    # c4490) that freeze at the same slots. Per-slot override: an entry's
    # `reject_fragile_locomotion: true` (migrated from the old
    # reject_anim_classes=['quadruped']) rejects every fragile-loco target,
    # which is the same set the default branch catches — kept as an explicit
    # per-slot marker for the slots authored for humanoid bipedal AI (e.g.
    # m46_77 pi=8, the Demi-Human Queen anchor).
    if msb_base is not None and pi is not None and V3_QUADRUPED_UNSAFE_SLOTS:
        if (msb_base, pi) in V3_QUADRUPED_UNSAFE_SLOTS:
            entry = V3_QUADRUPED_UNSAFE_SLOTS_META.get((msb_base, pi), {})
            repo = entry.get('reposition_proposed') or {}
            if not repo.get('playtest_verified'):
                target_tag = tags.get(target_cp, {})
                target_fragile = target_tag.get('fragile_locomotion') is True
                target_loco = target_tag.get('locomotion')
                if target_fragile or target_loco == 3:
                    # Catches fragile_locomotion chrs (former quadruped /
                    # quadruped_large — Bears, Wolves, Goats, etc., across
                    # all locomotion values) AND loco=3 chrs (Rats and the
                    # handful of non-quadruped loco=3 bipeds). Both share
                    # the spawn-time pathfinding failure mode at these
                    # constrained-navmesh slots.
                    return 'quadruped_unsafe_slot'

    # v0.27.28: Gate 5 (flying-required slots) REMOVED. Per Alaric, the
    # flying-vs-ground constraint isn't real — dragons start grounded and a
    # grounded enemy at a former dragon slot is fine. The seed-552688
    # "Astel at a Flying Dragon slot → CTD" was a best-guess attribution
    # that was never confirmed. This was the last consumer of is_flier /
    # the V3_FLYING_REQUIRED_SLOTS catalog, both also removed.

    # v0.24.67 Gate 5.5: grunt/trash target at boss-healthbar slot.
    # Slots whose vanilla catalog tier indicates a boss-healthbar
    # encounter (named_boss, fieldboss, nightboss, encampment,
    # remembrance, castle_interior, noklateo, crater, fort_suffix,
    # boss_suffix, cathedral) run an EMEVD boss-clear chain on kill
    # that expects clean entity teardown. Grunt-tier and trash-tier
    # chrs are not authored for that contract: some have spawner-
    # generator fields in NpcParam that fire child entities on death
    # (c3664 Cemetery Shade variants 36640020/32/35), some dissipate
    # rather than leaving a corpse, some have unusual death anim
    # timing. The mismatch CTDs the boss-clear chain.
    #
    # Discovered seed 877217 v0.24.65: c3664 Cemetery Shade at m32_00
    # pi=31 ent=32000810 (Elder Lion Encampment slot). Player CTDed
    # on kill.
    #
    # V3_FRAGILE_SAFE_CONFIRMED is the exemption — grunts/trash with
    # playtest-confirmed normal death sequences are whitelisted there
    # and remain eligible. c3664 was removed from SAFE_CONFIRMED in
    # this release; its v0.20.52 "working" confirmation was at a non-
    # boss-bar slot type. See V3_BOSS_BAR_TIERS docstring for the
    # empirical derivation of the tier set.
    if msb_base is not None and pi is not None and V3_BOSS_SLOT_CATALOG:
        target_tier = tags.get(target_cp, {}).get('tier')
        if target_tier in V3_BOSS_BAR_GATED_TIERS:
            if target_cp not in V3_FRAGILE_SAFE_CONFIRMED:
                _cat = V3_BOSS_SLOT_CATALOG.get((msb_base, pi))
                if _cat and _cat.get('tier') in V3_BOSS_BAR_TIERS:
                    return 'grunt_trash_at_boss_bar'

    # v0.25.0-patch3 Gate 5.5: Field-boss-tier at strict-NB catalog slot.
    #
    # Catalog-aware tier-vs-scope enforcement. Gate 2 (nb_caliber, line
    # ~9378) uses src_variant_name string-matching to identify NB slots
    # and includes field_boss-tier chrs in V3_NIGHT_BOSS_CALIBER_TARGETS
    # for the broader "boss-quality at boss-marker slots" semantic. But
    # strict-scope NB arenas in V3_BOSS_SLOT_CATALOG (catalog scope=
    # 'strict' AND tier='nightboss') have wake-handshake EMEVD
    # integration — SetNetworkconnectedEventFlagID + per-arena boss-init
    # common_func sequence — that only proper night-boss-tier chrs
    # satisfy. Field-boss-tier chrs (Flying Dragon, Magma Wyrm, Guardian
    # Golem, Astel, Mohg, Erdtree Avatar, etc.) are open-world boss
    # encounters in ER vanilla; they expect a field-spawn flow, not a
    # strict-arena wake handshake. When one lands at a strict slot, the
    # boss never starts and the expedition Night fails-to-start.
    #
    # Empirical discovery: seed 628653 Tricephalos N2 fail-to-start.
    # The m48_40 (Morgott) strict-NB arena got swapped to c4500 Flying
    # Dragon (Field Boss). c4500.tier='field_boss', caliber=True,
    # strict=False — slipped through both the caliber gate (because
    # "Morgott (Night Boss)" matches an NB name marker, activating
    # caliber, which c4500 satisfies) and the strict gate (because
    # c4500 isn't in V3_NIGHT_BOSS_STRICT_TARGETS, so gate 1 doesn't
    # apply to it). Audit shows 26 of 59 caliber-pool chrs are
    # field_boss-tier — this gate prevents that whole class at strict
    # slots without restricting their placement at non-strict (broad/
    # extended) NB-arena slots where they remain valid candidates.
    #
    # The likely earlier N1/N2 failures (seed 650833 m48_40 → c7700
    # Gaping Dragon; seed 42 m49_18 → c5081 Chief Bloodfiend) match
    # the same shape — both are field_boss-tier in caliber. After
    # v0.25.0-patch2 catalogued m49_18 / m49_19 / m49_20 / m48_90 as
    # strict, this gate now covers those slots too.
    #
    # NOT chaos-overrideable (geometric / EMEVD-integration constraint,
    # not thematic). Catalog scope='strict' is a hard structural
    # property of the slot, independent of chaos mode.
    if msb_base is not None and pi is not None and V3_BOSS_SLOT_CATALOG:
        _cat = V3_BOSS_SLOT_CATALOG.get((msb_base, pi))
        if (_cat
                and _cat.get('tier') == 'nightboss'
                and _cat.get('scope') == 'strict'):
            if tags.get(target_cp, {}).get('tier') == 'field_boss':
                return 'field_boss_at_strict_nb'

    # v0.24.68 Gate 5.6: XXL/GIGA source slot integrity.
    # Discovered: seeds 756907 and 388677 both CTD when leaving
    # Stormveil Castle's southern face. Pattern: vanilla XXL/GIGA
    # boss slots in castle-area tiles (m60_4X_3Y) drift to targets
    # with mismatched family and/or much smaller size_class.
    # When the cell streams in on transit, the chr-file load fails
    # asset/nav validation against the slot's expectations and the
    # game CTDs.
    #
    # User decision (v0.24.68): "enough diversity now" — go broad.
    # At any slot where the vanilla source size_class is XXL or GIGA,
    # require the target to:
    #   (a) share the source's family, AND
    #   (b) be size L or larger (i.e., not XS/S/M)
    #
    # No event-bound discrimination needed — source size XXL/GIGA is
    # a reliable proxy for "dedicated boss-tier slot." Non-event XXL/
    # GIGA slots are rare and still expect boss-tier behavior on load,
    # so the gate is uniform.
    #
    # Trade-off: this loses some XXL→M and quadruped-GIGA→humanoid
    # diversity that was previously allowed. The earlier rationale
    # for permitting drift was diversity; with 130 L+ chrs in the
    # pool (45 L, 35 XL, 29 XXL, 21 GIGA) per-anim-class subsets
    # remain large enough for variety.
    src_tag = tags.get(src_cp, {})
    src_size = src_tag.get('size_class', '')
    if src_size in ('XXL', 'GIGA'):
        tgt_tag = tags.get(target_cp, {})
        tgt_size = tgt_tag.get('size_class', '')
        # v0.24.75: anim_class drift check REMOVED. Per user directive,
        # the rig-compat CTD theories of v0.24.18/v0.24.68 were
        # misattributing crashes that had other root causes (missing
        # chr assets, AI script issues). Keeping ONLY the size_drift
        # check — big sources still need big targets so body geometry
        # fits the slot. rig match no longer required.
        #
        # v0.26.x: M lifted from the drift list per user direction —
        # "Midra should be eligible for any slot that's occupied by
        # an L, XL, XXL, or GIGA mob. It's asymmetrically compatible."
        # The slot has the geometric capacity for an M-sized
        # occupant; the visual surprise of an M-humanoid at a GIGA-
        # source slot is a marquee-NB feature, not a bug. Floor-tier
        # protection for the big chrs that NEED these slots is
        # handled by V3_RESERVATION_FLOORS — those chrs get their
        # reserved slot before organic competition kicks in. Non-
        # NB-caliber M-humanoids (Wandering Noble etc.) are still
        # filtered by the NB-CALIBER gate at NB-marker slots, so
        # this widening doesn't open a grunt-flood at NB arenas.
        # XS/S retained on the drift list: those are grunt-scale
        # and would feel jarring at a giga/xxl visual.
        if tgt_size in ('XS', 'S'):
            return 'xxl_giga_size_drift'

    # v0.24.51 Gate 6: dedicated-arena boss off-arena.
    # v0.24.52: RELAXED based on playtest counter-evidence — see below.
    # v0.26.x: switched from _source='script_spawn' check to explicit
    # V3_DEDICATED_ARENA_BOSS_CHRS membership. The _source-based check
    # was made stale by the v0.26.x reclassification pass that flipped
    # the affected chrs to _source='nr_placed' after the byte-level
    # MSB audit confirmed they ARE in vanilla MSBs. The gate's INTENT
    # — protect against placement at overworld tiles that lack the
    # arena's EMEVD preload machinery — is unchanged, and the set of
    # chrs covered is identical to the previous behaviour.
    #
    # Script-spawn _source chrs (c4670, c4690, c7700, c7710, c7800,
    # c7820, c7900, c7910, c7920) need vanilla-NR EMEVD script-side
    # asset preloads (SmallBaseAttached and similar) to load their
    # asset bundles. Initial v0.24.51 hypothesis was that this preload
    # only happens at the 4 catalogued arena slots (m46_64/65/90/91 pi=1).
    #
    # User playtest of seed 714653 (v0.24.50) confirmed this is too
    # narrow: a script_spawn boss-tier chr placed at m46_05 (vanilla
    # c4660 Guardian Golem fort) was fought successfully. That MSB is a
    # dedicated NR boss arena MSB — vanilla content is also boss-tier —
    # and apparently the slot's existing EMEVD machinery preloads any
    # boss-tier replacement.
    #
    # Refined hypothesis (v0.24.52): m4x_xx dedicated arena MSBs have
    # boss-asset preload infrastructure (vanilla content is boss-tier
    # for these slots). m60_xx_xx overworld tiles do NOT — they're
    # open-world streaming tiles with no boss preload. Placing a
    # dedicated-arena boss chr at an overworld slot leaves the asset
    # bundle unloaded → CTD on cell-load when the player approaches.
    #
    # Gate behavior: reject dedicated-arena boss targets ONLY at
    # m60_xx_xx_xx overworld MSBs. Dedicated arena MSBs (m4x_xx) are
    # allowed — they have the EMEVD machinery.
    #
    # The 4 catalogued arena slots in V3_SCRIPT_SPAWN_BOSS_SLOTS remain
    # documented as the original NR script-spawn arena slots but are
    # no longer the exclusive allow-list. They're kept available for
    # future refinement if we discover specific m4x_xx slots that
    # DON'T work (would need another playtest data point).
    #
    # Grunt-tier supporting cast (c7711/c7712/c7810) are NOT gated —
    # they've worked everywhere observed.
    if msb_base is not None and pi is not None:
        if target_cp in V3_DEDICATED_ARENA_BOSS_CHRS:
            # Reject ONLY at overworld m60_xx_xx_xx tiles. Dedicated
            # arena MSBs (m4x_xx) are allowed.
            if msb_base.startswith('m60_'):
                return 'script_spawn_boss_at_overworld'

    # v0.27.4 Gate 7: geometry-aware size gate. Replaces the blunt
    # v0.24.55 'xxl_at_small_slot' gate and extends coverage to GIGA.
    #
    # A slot's size capacity is the LARGER of (a) the vanilla occupant's
    # size class — strict baseline, FromSoft placed that size here so it
    # is proven safe, with NO grace step (an XL-vanilla slot does not
    # auto-qualify for XXL) — and (b) the geometry-derived capacity from
    # slot_terrain.json `face_dist`. An XXL/GIGA target is rejected
    # unless its size class falls within that capacity.
    #
    # This supersedes the old "XXL at XS/S/M/L source -> always reject"
    # rule: XXL/GIGA are now allowed wherever the navmesh geometry
    # demonstrates the clearance (recovering legit big slots the blunt
    # gate discarded) and blocked everywhere it doesn't — including the
    # XL-vanilla slots the blunt gate let XXL through on unconditionally.
    # Slots with no terrain data fall back to the strict vanilla
    # baseline (no upsize without proof). Only XXL/GIGA are gated —
    # XS..XL clear essentially any navmesh slot. Geometric / not chaos-
    # overrideable. The gate never rejects a target whose size class is
    # <= the vanilla occupant's, so the candidate pool can never be
    # fully drained by it.
    if (V3_GEOMETRY_GATE_ENABLED and msb_base is not None
            and pi is not None):
        _tgt_size = (tags.get(target_cp, {}) or {}).get('size_class')
        if _tgt_size in V3_GEOMETRY_GATED_SIZES:
            _src_size = (tags.get(src_cp, {}) or {}).get('size_class')
            _cap_rank = V3_SIZE_RANK.get(_src_size, -1)  # strict baseline
            _fd = _load_slot_face_dist().get((msb_base, pi))
            if _fd is not None:
                _g_rank = _geometry_capacity_rank(_fd)
                if _g_rank > _cap_rank:
                    _cap_rank = _g_rank
            if V3_SIZE_RANK[_tgt_size] > _cap_rank:
                return 'geometry_clip'

    # Gate 7.5 (revised v0.24.86-patch6.1): slope-aware size-up at
    # boss-tier slots. Tighter conjunction than v0.24.86-patch6 — the
    # old form (tier+size-up only) broke test_night_boss_tier_unaffected,
    # which asserts XL Morgott at L Elder Lion Encampment is allowed
    # (geometrically fine, playtest-confirmed). Encampment is flat
    # (3° slope); the freeze case (c7100 Zamor at c3970 Ruins-Boss)
    # is on a 20.1° slope. Polygon data discriminates.
    #
    # Three filters, all must fire to reject:
    #   1. target.size_class > slot.src.size_class (size-up)
    #   2. slot.src.tier in BOSS_ARENA_TIERS or expects_boss_arena
    #   3. slot.slope_deg >= V3_SLOPED_SIZE_UP_THRESHOLD (15.0°)
    #
    # Missing polygon data: gate doesn't fire (better to allow than to
    # reject blind). v0.24.86-patch6.1 ships polygon-augmented
    # slot_terrain.json built via dev/augment_slot_terrain_with_polygons.py.
    _SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA']
    _BOSS_ARENA_TIERS = {
        'miniboss', 'field_boss', 'night_boss', 'nightlord', 'remembrance',
    }
    _src_tag = tags.get(src_cp, {})
    if (_src_tag.get('tier') in _BOSS_ARENA_TIERS
            or _src_tag.get('expects_boss_arena')):
        _src_sz = _src_tag.get('size_class', 'M')
        _tgt_sz = tags.get(target_cp, {}).get('size_class', 'M')
        try:
            _size_up = (_SIZE_ORDER.index(_tgt_sz)
                        > _SIZE_ORDER.index(_src_sz))
        except ValueError:
            _size_up = False
        if _size_up and msb_base is not None and pi is not None:
            _slope = _get_slot_slope_deg(msb_base, pi)
            if _slope is not None and _slope >= V3_SLOPED_SIZE_UP_THRESHOLD:
                return 'sloped_size_up'

    # Gate 7.6 (wedged-against-wall) / Gate 7.7 (elevated-rampart),
    # v0.24.86-patch8. Apply at ALL tiers (unlike slope, which is
    # boss-arena-only) but still only on size-up. May 13 v0.23.88
    # calibration. Both fall through silently on missing slot data.
    if msb_base is not None and pi is not None:
        _SIZE_ORDER_8 = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA']
        _src_sz = tags.get(src_cp, {}).get('size_class', 'M')
        _tgt_sz = tags.get(target_cp, {}).get('size_class', 'M')
        try:
            _is_up = (_SIZE_ORDER_8.index(_tgt_sz)
                      > _SIZE_ORDER_8.index(_src_sz))
        except ValueError:
            _is_up = False
        if _is_up:
            if _is_slot_wedged(msb_base, pi):
                return 'wedged_size_up'
            if _is_slot_elevated(msb_base, pi):
                return 'elevated_size_up'

    # Gate 7.8 (nav_dependent_at_stub_nav_slot), v0.24.86-patch9.
    # If slot is on a stub-nav tile (cave/dungeon family where the game
    # ships empty navmesh + empty onav), reject any target NOT in
    # V3_NAV_INDEPENDENT_TARGETS. Nav-dependent AI (rats, slugs,
    # wandering humanoids) hangs in pursuit-AI-stalled state when
    # navmesh queries return nothing.
    if (msb_base is not None
            and _is_stub_nav_slot(msb_base)
            and target_cp not in V3_NAV_INDEPENDENT_TARGETS):
        return 'nav_required_at_stub_nav_slot'

    # Gate 7: no_emerge_terrain (v0.24.79). Reject emerge-from-ground
    # chr intros at slots that lack the subsurface terrain their
    # animation requires (rampart roofs, elevated platforms, etc.).
    # Data-driven via V3_NO_EMERGE_SLOTS (arena affordance list) +
    # V3_ENTRANCE_ANIM_CLASS (per-chr taxonomy). Defense-in-depth
    # with the per-slot EXTRA_BANS pattern — both can fire for the
    # same case, with EXTRA_BANS being more specific (per-slot).
    if msb_base is not None and pi is not None:
        if (msb_base, pi) in V3_NO_EMERGE_SLOTS:
            anim = V3_ENTRANCE_ANIM_CLASS.get(target_cp)
            if anim == 'emerge_from_ground':
                return 'no_emerge_terrain'

    # Gate 8: requires_intro_anim (v0.26.11). Mirror image of Gate 7.
    # Some slots' EMEVD spawn setup hard-requires the occupant to have an
    # idle/entrance animation; chrs classified 'no_intro_anim' break there
    # while being resilient everywhere else. First slot: the m38_00
    # Guardian Golem "Cathedra" slot (pi=51), where Death Knight (c5070)
    # is the confirmed failure and emergers/risers play well. Data-driven
    # via V3_INTRO_ANIM_REQUIRED_SLOTS (slot list) + V3_ENTRANCE_ANIM_CLASS
    # (per-chr taxonomy). Negative gate — only the explicitly-classified
    # no_intro_anim chrs are rejected; 'unknown'-default chrs pass, so the
    # slot still randomizes widely. Composes with the slot's existing
    # V3_PROBLEM_SLOTS / EXTRA_ALLOWS gates (different root cause).
    if msb_base is not None and pi is not None:
        if (msb_base, pi) in V3_INTRO_ANIM_REQUIRED_SLOTS:
            anim = V3_ENTRANCE_ANIM_CLASS.get(target_cp)
            if anim == 'no_intro_anim':
                return 'requires_intro_anim'

    # v0.27.5 Gate 8 (big-enemy proximity) + Gate 9 (per-MSB density).
    # Placement-time replacement for the BIG_PROXIMITY (v0.21) and
    # DENSITY_CAP (v0.23.61) swap-plan post-passes. Both run off the
    # per-MSB size state carried on run_ctx and armed by begin_msb():
    #
    #   Gate 9 density — once the MSB's XL+ count hits xl_cap, XL+
    #       targets are rejected; once L+ count hits l_cap, L+ targets
    #       are rejected. Tunnel MSBs carry tighter caps.
    #   Gate 8 proximity — an XL+ target landing within
    #       V3_BIG_PROXIMITY_RADIUS of a big already placed in this MSB
    #       is rejected.
    #
    # A rejected big simply drops out of the candidate pool and the
    # picker organically selects a smaller chr through its normal
    # pipeline — no separate demotion path, so the caliber / cap /
    # Gate-5.6 machinery the old post-passes had to re-implement is
    # gone. The gates are inert unless run_ctx.msb_size_gate_active is
    # set, which begin_msb() does only inside shuffle_msb_v3's slot
    # loop. The reservation pre-pass and the reservation early-return
    # never arm it, so a reserved big chr is never proximity/density-
    # rejected — this closes the reservation-floor-demotion bug. Loop
    # order is pi-ascending, so "low-pi wins" matches the post-passes'
    # "first-pi wins" / "highest-pi demoted" exactly. Geometric, not
    # chaos-overrideable.
    if (run_ctx is not None
            and getattr(run_ctx, 'msb_size_gate_active', False)):
        _gsz = _effective_size_class(target_cp, tags)
        if _gsz in V3_DENSITY_L_SIZE_CLASSES:  # L / XL / XXL / GIGA
            _is_xl = _gsz in V3_BIG_SIZE_CLASSES  # XL / XXL / GIGA
            # Gate 9: density
            if V3_DENSITY_CAP_ENABLED:
                if _is_xl and run_ctx.msb_xl_count >= run_ctx.msb_xl_cap:
                    return 'density_xl'
                if run_ctx.msb_l_count >= run_ctx.msb_l_cap:
                    return 'density_l'
            # Gate 8: proximity (XL+ only)
            if (V3_BIG_PROXIMITY_ENABLED and _is_xl
                    and slot_pos is not None
                    and run_ctx.msb_big_positions):
                _px, _py, _pz = slot_pos
                _rsq = V3_BIG_PROXIMITY_RADIUS ** 2
                for _bx, _by, _bz in run_ctx.msb_big_positions:
                    if ((_px - _bx) ** 2 + (_py - _by) ** 2
                            + (_pz - _bz) ** 2) < _rsq:
                        return 'big_proximity'

    return None


def _score_slot_for_unique(slot_info, target_cp, tags):
    """Score how well slot_info fits target_cp for a unique reservation.

    slot_info is a dict from _enumerate_unique_candidate_slots (see below).
    Higher = better. Returns None for hard-disqualifying slots.

    Hard requirements (return None):
      - source is in V3_EXCLUDE_SOURCE_PREFIXES (slot stays vanilla)
      - source npc_param in V3_EXCLUDE_SOURCE_NPC_PARAMS (preserved)
      - source is in a multi-Part cluster (cluster_id is not None)
      - incompatible with target (size/family)
      - slot is fragile (per is_fragile_slot) AND target is in
        V3_FRAGILE_SENSITIVE_TARGETS — they don't survive together

    Scoring (additive):
      +10  slot (msb, pi) is in V3_BOSS_SLOT_CATALOG (any scope)
      +5   source variant name carries a Night/Field/Castle/Fort Boss marker
      +3   source size_class is XL+ (matches big-creature feel)
      +2   target is flying_dragon AND slot Y altitude > 30 (sky-eligible)
     -10  target is flying_dragon AND slot is interior MSB (m4x_xx_xx
          dungeon/cave) — sky-spawn animation needs open ceiling
    """
    src_cp = slot_info['source_cp']

    # Hard: identity-swap rejection. If the slot's source already IS the
    # target c-prefix, reserving it accomplishes nothing — the slot would
    # already produce that c-prefix in vanilla, and the engine may even
    # skip the slot entirely (aerial-source preservation, etc.). Worse,
    # the count pre-bump would tie up a cap unit on a no-op reservation.
    if src_cp == target_cp:
        return None

    # Hard: shifting-earth disqualification. Only one shifting-earth event
    # activates per Expedition (Mountaintop OR Crater OR Rot Forest OR
    # Noklateo), so a reservation that lands on, e.g., a Crater tile
    # wouldn't appear if the run rolls Mountaintop. Disqualify all
    # shifting-earth slots from reservations entirely. Caps still apply
    # to organic picks at these slots via _V3_UNIQUE_PLACED_COUNTS, so
    # a cap=1 chr can't appear at both an always-active reservation AND
    # a shifting-earth tile in the same run — they share count budget.
    if _shifting_earth_event(slot_info['msb']) is not None:
        return None

    # v0.24.27: mirror-semantic gates consolidated into
    # _reject_target_for_slot. Previously this function had three
    # inline mirror blocks (NB-caliber from v0.23.07, NB-strict from
    # v0.23.11, source-anim from v0.24.26). Each was added as a hand-
    # written mirror of a new pick_target_cp gate. The pattern broke
    # three times in a row when a new gate landed in the picker but
    # the mirror was forgotten here. The predicate now owns the gate
    # logic; both call sites delegate. Future gate additions add to
    # the predicate and both paths inherit.
    src_variant_name = slot_info.get('source_variant_name') or ''
    if _reject_target_for_slot(target_cp, src_cp, src_variant_name,
                                tags,
                                msb_base=slot_info.get('msb'),
                                pi=slot_info.get('pi')) is not None:
        return None

    # Hard: source preservation
    if src_cp in V3_EXCLUDE_SOURCE_PREFIXES:
        return None
    if slot_info.get('source_npc') in V3_EXCLUDE_SOURCE_NPC_PARAMS:
        return None
    # v0.23.74: strict (msb, pi)-level preservation. See V3_PRESERVE_SLOTS
    # docstring. Used to back the m49_28 Night's Cavalry NB exemption
    # after the c3150/c3160 c-prefix-level protections were lifted.
    if (slot_info.get('msb'), slot_info.get('pi')) in V3_PRESERVE_SLOTS:
        return None
    # Hard: clusters skipped for v1 (cluster placements are too entangled
    # with cluster-shape matching to safely reserve a single Part)
    if slot_info.get('cluster_id') is not None:
        return None

    # v0.24.100: anim_class compat gate REMOVED. The historical block
    # imported _compat_rig from swap_compat and disqualified slots
    # whose source/target family differed without a compat-pair entry.
    # Since v0.24.75 the function was always-True (no-op); v0.24.100
    # deletes it outright. Flier-vs-ground separation is now enforced by
    # the flier-required slot gate above and by is_compatible at the
    # main swap-loop layer.
    src_tag = tags.get(src_cp, {})
    tgt_tag = tags.get(target_cp, {})

    # Hard: SENSITIVE-target × fragile-slot incompatibility. If the target
    # is in the SENSITIVE blacklist (Borealis is, c4500 is post-lift, etc.)
    # AND this slot is fragile per is_fragile_slot, the placement would be
    # filtered out at runtime anyway — disqualify upfront.
    #
    # v0.24.62: extended fragility filter for unique reservations.
    # Previously this only rejected SENSITIVE chrs at fragile slots. The
    # standard shuffle's filter restricts the chosen_pool to
    # V3_FRAGILE_SAFE_CONFIRMED ∪ V3_RESILIENT_BIPEDS — but uniques were
    # bypassing that broader restriction because _score_slot_for_unique
    # only consulted SENSITIVE. As a result, Nightlords (c4900/c7500/
    # c7520/c7540/c7600/c7910) and MMV imports could land at fragile
    # slots even though they aren't in SAFE_CONFIRMED. User seed 537773
    # v0.24.58: c7910 Storm King reserved m30_30 pi=45 (Guardian Golem
    # Fort rampart, in V3_PROBLEM_SLOTS since v0.24.18 for c4441 Land
    # Squirt CTD); player CTD walking away from the fort. Bringing
    # uniques onto the same fragility filter the standard shuffle uses.
    # Also honors V3_PROBLEM_SLOT_EXTRA_BANS at fragile slots.
    is_fragile = is_fragile_slot(slot_info['msb'], slot_info['pi'],
                                  slot_info.get('source_variant_name') or '',
                                  slot_pos=slot_info.get('position'))
    if is_fragile:
        # v0.27.0: WHITELIST -> BLACKLIST flip (mirrors the standard-
        # shuffle fragile filter in pick_target_cp). The old gate
        # required target_cp in V3_FRAGILE_SAFE_CONFIRMED; that whitelist
        # was archived. A unique reservation now lands at a fragile slot
        # unless target_cp is in the V3_FRAGILE_SENSITIVE_TARGETS
        # blacklist or the per-slot EXTRA_BANS. EXTRA_ALLOWS still
        # bypasses the SENSITIVE reject (its original purpose).
        extra_allows = V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
            (slot_info['msb'], slot_info['pi']))
        allowed_via_extra = extra_allows and target_cp in extra_allows
        if not allowed_via_extra:
            if target_cp in V3_FRAGILE_SENSITIVE_TARGETS:
                return None
        extra_bans = V3_PROBLEM_SLOT_EXTRA_BANS.get(
            (slot_info['msb'], slot_info['pi']))
        if extra_bans and target_cp in extra_bans:
            return None

    score = 0
    # v0.24.99: V3_BOSS_SLOT_CATALOG-authoritative score. Pre-v0.24.99 the
    # +10 came from src_tag.get('expects_boss_arena'), a prefix-level tag
    # that applies uniformly across all variants of a c-prefix. For
    # prefixes whose roster mixes boss and non-boss variants — c2500
    # Crucible Knight has 22 variants spanning NB1 / Evergaol / Castle
    # grunt (the 10-Part m49_43 Roundtable group) — every castle grunt
    # slot scored +10 equal with real evergaol/NB slots. Result was that
    # cap-bounded uniques (Godrick the Grafted cap=2, Elder Lion cap=8)
    # concentrated at the castle Roundtable because 10 m49_43 slots all
    # tied at 10 with the real boss-arena slots. Catalog membership is
    # slot-level (not prefix-level), built from careful vanilla MSB
    # inventory, and already authoritative for recipient_is_boss at the
    # swap loop (v0.24.98). Using it here distributes uniques across
    # actual catalogued boss arenas instead.
    #
    # NB: 35 vanilla slots have expects_boss_arena=True src_cp but are
    # not in the catalog. ~23 are correctly demoted by this change
    # (m49_43 castle Crucibles, m60_44_36 c3350 grunts, m46_05 c4660
    # field-Guardian-Golem encounters, m60_45_36 c4500 hub-passthrough).
    # ~11 are likely catalog-missing real boss slots (m46_70 pi=3 / m46_80
    # pi=1 Godskin Apostle (Evergaol/Oldest Gaol) — paired bosses with
    # already-catalogued NB1 anchors; m34_10 pi=88-91 Miranda Blossom
    # (Ruins); m34_00 pi=123-125,152-153 Ancient Hero (Ruins); m46_78
    # Morgott Random Encounter). Those slots lose the priority bonus but
    # remain eligible for organic swaps; catalog-add is a separate
    # follow-up.
    if (slot_info['msb'], slot_info['pi']) in V3_BOSS_SLOT_CATALOG:
        score += 10
    src_name = (slot_info.get('source_variant_name') or '')
    if any(m in src_name for m in V3_NIGHT_BOSS_NAME_MARKERS):
        score += 5
    if src_tag.get('size_class') in ('XL', 'XXL', 'GIGA'):
        score += 3

    # v0.27.28: aerial-target scoring REMOVED along with the rest of the
    # flying-vs-ground machinery. This soft preference nudged fliers toward
    # high-Y outdoor slots and penalized them at interior MSBs; with flying
    # no longer a tracked class (per Alaric — dragons start grounded, any
    # enemy is fine at any former dragon slot), there's nothing to score.

    return score


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
    """Pick a target c-prefix for a swap slot from the compatible pool,
    after applying excludes, tier-preserve, fragility, and frequency caps.

    v0.23.72-late: removed long-vestigial `bank_to_prefixes`,
    `loose_to_prefixes`, and `mode` parameters from the signature. They
    were threaded through to `compatible_pool()` which had been ignoring
    them since v0.20.0 (universal-pool refactor); the placement chain is
    "everything in tags, then post-filter" and has no use for them. See
    `compatible_pool` docstring for the cleanup notes.

    v0.23.72-late: removed the FI tracking scaffolding (FI_TRACKED set,
    _bump_stage per-stage counters, FI_DROP_FIRST_OBSERVED trace event,
    _V3_FI_RETURNED_COUNTS, _V3_FI_STAGE_TRACKER). These had been
    investigation-only tooling for the v0.20.1–v0.20.4 force-include
    debugging series and were no longer load-bearing. The four
    permanent regression guards (TAGS_INTEGRITY, EXCLUDE_INTEGRITY,
    EXCLUDE_SNAPSHOT_AT_RUN_START, TAG_OVERRIDES_APPLIED) remain in
    the trace buffer.

    v0.24.21: `gates` parameter. When None (default), reads
    V3_EXCLUDE_PREFIXES, V3_EXCLUDE_TARGET_PREFIXES,
    V3_GHOST_EXCLUDE_TARGET_PREFIXES, V3_ARENA_ONLY_TARGETS,
    V3_NIGHT_BOSS_STRICT_TARGETS, V3_NIGHT_BOSS_CALIBER_TARGETS from
    the module — preserves pre-existing behavior. When a GateState is
    passed, reads those values from the snapshot instead. See
    engine/state.py.

    v0.24.22: BFER gates (V3_BFER_ALL_PREFIXES,
    BFER_UNRESTRICTED_TEST_MODE) removed with the BFER asset pack
    cleanup (Phase 7)."""
    # Resolve the six mutable gate refs this function reads. The
    # gates=None path reads module globals directly (no GateState
    # coercion overhead — keeps the hot-path call cost identical to
    # pre-v0.24.21). The explicit-gates path reads from the snapshot.
    if gates is None:
        _exclude = V3_EXCLUDE_PREFIXES
        _exclude_target = V3_EXCLUDE_TARGET_PREFIXES
        _ghost_exclude = V3_GHOST_EXCLUDE_TARGET_PREFIXES
        _arena_only = V3_ARENA_ONLY_TARGETS
        _nb_strict = V3_NIGHT_BOSS_STRICT_TARGETS
        _nb_caliber = V3_NIGHT_BOSS_CALIBER_TARGETS
    else:
        _exclude = gates.exclude_prefixes
        _exclude_target = gates.exclude_target_prefixes
        _ghost_exclude = gates.ghost_exclude_target_prefixes
        _arena_only = gates.arena_only_targets
        _nb_strict = gates.night_boss_strict_targets
        _nb_caliber = gates.night_boss_caliber_targets
    # v0.24.21 (Phase 5): runtime bookkeeping refs. Same pattern as gates:
    # run_ctx=None reads/writes module dicts (preserving back-compat for
    # all pre-Phase 5 callers); explicit RunContext reads/writes the
    # snapshot's dicts. See engine/runctx.py.
    if run_ctx is None:
        _placed_counts = _V3_UNIQUE_PLACED_COUNTS
        _reservations = _V3_UNIQUE_RESERVATIONS
    else:
        _placed_counts = run_ctx.unique_placed_counts
        _reservations = run_ctx.unique_reservations
    # v0.20.38: non-fragile-baseline intercept. When this is set and the
    # slot is NOT fragile, return the baseline c-prefix immediately.
    # Used during diagnostic runs to force visual consistency at safe
    # slots — anything visibly different in the world becomes a definite
    # fragile-slot test. Bypasses tier/compat/excludes (similar to
    # oops_all_target_cp). If the slot IS fragile, fall through to the
    # normal flow (which respects disable_resilient_filter / SENSITIVE).
    if non_fragile_baseline_cp and slot_msb_name is not None:
        if not is_fragile_slot(slot_msb_name, slot_pi, slot_variant_name,
                                slot_pos=slot_pos):
            return non_fragile_baseline_cp

    # v0.26.16: NB-arena randomization override. Exempts an arena from
    # ALL THREE NB preservation gates below so its boss Part gets
    # swapped; EMEVD stays vanilla either way (the healthbar step
    # preserves NB-arena EMEVD separately). Two scopes, OR-combined:
    #   V3_RANDOMIZE_SAFE_NB_ARENAS — the 12 single-boss arenas only.
    #   V3_RANDOMIZE_ALL_NB_ARENAS  — all 25, incl. the multi-entity
    #     arenas whose synchronized boss-init is known to break (the
    #     experimental switch).
    _force_rando_nb = (
        slot_msb_name is not None
        and ((V3_RANDOMIZE_ALL_NB_ARENAS
              and slot_msb_name in V3_NIGHT_BOSS_ARENA_MSBS)
             or (V3_RANDOMIZE_SAFE_NB_ARENAS
                 and slot_msb_name in V3_SAFE_NB_RANDOMIZE_MSBS)))

    # v0.25.1: arena-chr-role catalog whole-MSB vanilla preservation.
    # MSBs in V3_OVERLAY_PRESERVE_VANILLA_MSBS are flagged
    # 'preserve_primary' by data/nr_boss_arena_chr_roles.json — multi-
    # wave / multi-entity / hardcoded-anim arenas where ANY Part swap
    # risks breaking the choreographed wake-handshake chain. Return
    # None for every Part in those MSBs, regardless of pi or tier.
    # See block comment near V3_OVERLAY_PRESERVE_VANILLA_MSBS for context.
    if (slot_msb_name is not None
            and slot_msb_name in V3_OVERLAY_PRESERVE_VANILLA_MSBS
            and not _force_rando_nb):
        # v0.27.0: add-randomize arenas preserve the boss Part only -
        # non-boss (add) Parts fall through to normal randomization.
        if not (slot_msb_name in V3_ADD_RANDOMIZE_ARENAS
                and not recipient_is_boss):
            return None

    # v0.26.16: night-boss-arena whole-MSB preservation. When test-mode
    # arenas are OFF (normal play), V3_PRESERVE_NIGHT_BOSS_ARENAS is True
    # and every Part in a night-boss arena is held vanilla — a catalog-
    # independent backstop. See block comment near V3_NIGHT_BOSS_ARENA_MSBS.
    if (V3_PRESERVE_NIGHT_BOSS_ARENAS and slot_msb_name is not None
            and slot_msb_name in V3_NIGHT_BOSS_ARENA_MSBS
            and not _force_rando_nb):
        # v0.27.0: add-randomize arenas preserve the boss Part only.
        if not (slot_msb_name in V3_ADD_RANDOMIZE_ARENAS
                and not recipient_is_boss):
            return None

    # v0.24.101: V3_PRESERVE_SLOTS strict (msb, pi)-level preservation gate.
    # When the slot is in V3_PRESERVE_SLOTS, return None so the Part stays
    # vanilla. Mirrors the check inside _score_slot_for_unique (line ~9549,
    # added v0.23.74) which only gated the unique-reservation pre-pass —
    # the normal swap path was bypassing the set entirely, so e.g. m49_28
    # pi=2/3 Cavalry NB riders were still getting swapped despite being
    # listed in V3_PRESERVE_SLOTS. Playtest seed 537123 v0.24.96 showed
    # Rellana and Bell Bearing Hunter at the supposedly-preserved m49_28
    # arena. Adding the gate here closes that loop.
    if slot_msb_name is not None and slot_pi is not None:
        if ((slot_msb_name, slot_pi) in V3_PRESERVE_SLOTS
                and not _force_rando_nb):
            return None

    # v0.23.07: Unique-target reservation early-return. If this slot was
    # reserved during the pre-pass for a capped c-prefix, commit that pick
    # directly (bypasses tier/compat — the pre-pass already validated
    # swap compat and source-preservation status). The pre-pass
    # already bumped _V3_UNIQUE_PLACED_COUNTS at reservation time so the
    # cap-exhausted gate sees this cp as filled before any per-MSB
    # processing — don't double-bump here.
    #
    # v0.27.13: skipped under V3_SOTE_MODE. The pre-pass is origin-blind,
    # so a reservation may name a non-SOTE cp; committing it here would
    # bypass the SOTE pool intersection below and leak a non-SOTE enemy
    # into a SOTE run. SOTE mode runs uncapped anyway, so dropping the
    # reservation shortcut costs nothing.
    #
    # v0.27.13: a reservation value is either a cp string (c-prefix
    # floor) or a (cp, group) tuple (variant-group floor). pick_target_cp
    # only deals in c-prefixes, so strip the tuple to its cp here. The
    # group half of the tuple is re-read independently by pick_target
    # (via _reserved_variant_group) to pin the variant pick — keeping
    # this function's contract unchanged (it still returns a bare cp).
    if (slot_msb_name is not None and slot_pi is not None
            and not V3_SOTE_MODE):
        _res_key = (slot_msb_name, slot_pi)
        if _res_key in _reservations:
            _rv = _reservations[_res_key]
            return _rv[0] if isinstance(_rv, tuple) else _rv

    pool = compatible_pool(recipient_cp, tags)
    pool = pool - _exclude - _exclude_target - _ghost_exclude
    # v0.23.07: Subtract cap-exhausted unique-target c-prefixes. Any cp
    # that has already hit its V3_UNIQUE_TARGET_CAPS limit can't be
    # picked at non-reserved slots. Reserved slots already early-returned
    # above. Cheap set-comprehension so the per-slot overhead is minimal.
    #
    # v0.27.13: skipped under V3_SOTE_MODE — SOTE runs are uncapped (the
    # SOTE set is small and meant to repeat freely).
    if not V3_SOTE_MODE:
        # v0.28: global-cap gate with MSB-boundary semantics. Use the set
        # frozen at begin_msb (cps already at/over cap when this MSB
        # started). A cp can overshoot its cap mid-MSB via free recycling
        # and only gets blocked from the NEXT MSB on. Falls back to live
        # computation when there is no frozen set (legacy callers / tests),
        # preserving pre-v0.28 behavior exactly.
        _blocked = getattr(run_ctx, 'msb_blocked_cps', None)
        if _blocked is None and _placed_counts:
            _blocked = {cp for cp, n in _placed_counts.items()
                        if n >= V3_UNIQUE_TARGET_CAPS.get(cp, 0)}
        if _blocked:
            pool = pool - _blocked
    # v0.20.20: per-map-prefix target-side excludes. See
    # V3_MAP_PREFIX_TARGET_EXCLUDES for rationale (Limveld Maris-cluster
    # CTD).
    if slot_msb_name:
        for _mp_prefix, _excl in V3_MAP_PREFIX_TARGET_EXCLUDES.items():
            if slot_msb_name.startswith(_mp_prefix):
                pool = pool - _excl
    pool = {cp for cp in pool if cp in prefix_variants and prefix_variants[cp]}
    # v0.27.13: ALL-SOTE MODE — intersect the target pool with the
    # Shadow-of-the-Erdtree set. Runs AFTER the hard excludes, so a
    # CTD-blacklisted / asset-missing SOTE chr stays out (its exclude
    # wins). The tier-preserve filter below still narrows per slot; if
    # the intersection empties the pool the slot falls through to the
    # `not pool` return and stays vanilla — acceptable for the thin
    # tails (e.g. a flier-required slot with no SOTE flier).
    if V3_SOTE_MODE and V3_SOTE_PREFIXES:
        pool = pool & V3_SOTE_PREFIXES

    # v0.27.13: RIDER / MOUNT pool restriction. If the slot's vanilla
    # occupant is a rider, the pool is restricted to riders; if a
    # mount, to mounts. Keeps a rider slot from drawing a mount and
    # vice versa. Runs after the SOTE intersection so under all-SOTE
    # mode the pool is (SOTE ∩ role) — e.g. a mount slot becomes
    # {c5890} alone, which is the whole reason this lightweight
    # approach is correct without cross-slot atomicity (see the
    # V3_RIDER_PREFIXES block comment). HARD: if the intersection
    # empties the pool the slot falls through to the `not pool` return
    # and stays vanilla — correct, a rider slot with no eligible rider
    # should not receive a non-rider.
    if recipient_cp in V3_RIDER_PREFIXES:
        pool = pool & V3_RIDER_PREFIXES
        # v0.27.43: cross-slot family consistency. A mounted cluster's two
        # halves are swapped by INDEPENDENT per-slot picks; the role gate
        # keeps a rider on the rider slot and a mount on the mount slot but
        # never made the two agree. Under all-SOTE the per-role pools were
        # singletons so they always matched, but in non-SOTE the rider pool
        # is {c4050, c5840} while every mount slot is forced to c5890 (c4060
        # Kaiden's-Horse is target-excluded), so a c4050 draw produced a
        # Kaiden on a Black Knight Horse — a mismatched rig that hard-CTDs
        # in game. Fix: decide the whole cluster from GLOBAL placeability
        # (both gates call _selected_swap_family with the same inputs, so
        # they reach the same verdict without talking to each other). If a
        # complete swap family is available, force this rider to the family
        # rider; otherwise pin to the vanilla source rider so the cluster
        # stays a matched vanilla pair (the mount gate pins to vanilla in
        # lockstep). Restores the all-SOTE singleton invariant in every mode.
        _fam = _selected_swap_family(prefix_variants, slot_msb_name)
        if _fam is not None:
            # Force the family rider, bypassing the unique-cap subtraction
            # above: the mounted family must stay a matched pair (like the
            # SOTE singletons, which run uncapped). _selected_swap_family
            # already confirmed it passes the REAL target filters (excludes
            # / SOTE / map), and it is compat with this rider source by
            # design, so only the soft variety cap is bypassed — over-cap
            # standalone Black Knights still stop appearing (the placed
            # count keeps climbing and the general-slot filter still drops
            # them) while the mount slot commits to the matching mount.
            pool = {_fam[0]}
        else:
            pool = pool & {recipient_cp}
    elif recipient_cp in V3_MOUNT_PREFIXES:
        pool = pool & V3_MOUNT_PREFIXES
        # v0.27.43: symmetric half of the family decision above. Same global
        # verdict, applied to the mount: force the family mount (cap-bypassed,
        # see rider branch) when a complete family is available, else pin to
        # the vanilla source mount (c4060, which being target-excluded leaves
        # the pool empty -> the slot keeps its vanilla Kaiden's-Horse), so the
        # mount never lands on a slot whose rider half couldn't become its
        # matching rider.
        _fam = _selected_swap_family(prefix_variants, slot_msb_name)
        if _fam is not None:
            pool = {_fam[1]}
        else:
            pool = pool & {recipient_cp}
    else:
        # v0.27.43: symmetric completion of the gate above. A NON-role
        # source slot must never draw a MOUNT. The horses (c4060/c5890,
        # mount_role='mount') have no standalone AI brain — placed away
        # from a paired rider they spawn frozen / float in place. The
        # one-directional gate above only kept a *mount-source* slot
        # restricted to mounts; it did nothing to stop a mount leaking
        # onto an ordinary slot (Imp, Wolf, Wandering Noble, …), which is
        # exactly the freeze/float placement that
        # _ctd_check_mount_target_at_non_mount_source was flagging AFTER
        # the fact (20+ findings/seed, doing nothing about them). Confining
        # mounts to mount-source slots — where the vanilla mounted-pair
        # adjacency supplies a rider — eliminates the leak at the source.
        # Riders are deliberately NOT excluded here: c4050/c5840 (Kaiden
        # Sellsword, Black Knight) are complete standalone enemies and
        # stay broad-pool targets; only the riderless horse is the hazard.
        if V3_MOUNT_PREFIXES:
            pool = pool - V3_MOUNT_PREFIXES

    # v0.27.43: starting-encampment trash gate. For slots in the spawn-
    # adjacent Expedition camps, restrict the pool to the trash-tier set so
    # the player's first fight can't roll a miniboss/night-boss-strength
    # enemy. Same intersection mechanism as the SOTE / rider-mount blocks
    # above: runs after the hard excludes, before the tier-preserve filter
    # (a no-op for trash — all grunt/field-strength), and an empty result
    # falls through to the `not pool` return leaving the slot vanilla (a
    # vanilla starting camp is grunts, so that's a safe floor). Placed AFTER
    # the v0.27.44 rider/mount family pinning on purpose: if that logic has
    # pinned the pool to a mounted-pair family for a camp slot, intersecting
    # with trash empties it and the slot stays its coherent vanilla pair
    # rather than getting half-randomized — mounts/riders are not trash, so
    # this is the correct interaction. The 16 sponge variants these chrs also
    # carry are handled at the variant level by V3_AVOID_VARIANT_NPC_IDS, so
    # an in-pool trash chr can't roll its beefy variant. slot_msb_name is the
    # '.msb' basename here (the .dcx is already stripped upstream), matching
    # V3_STARTING_ENCAMPMENT_MSBS — the same raw membership test the NB-arena
    # gates use.
    if (V3_STARTING_ENCAMPMENT_TRASH_GATE and V3_TRASH_PREFIXES
            and slot_msb_name is not None
            and slot_msb_name in V3_STARTING_ENCAMPMENT_MSBS):
        pool = pool & V3_TRASH_PREFIXES

    if not pool:
        return None

    # v0.20.0: tier-preserve filter — boss-tier source slots get boss-tier
    # targets, field-tier source slots get field-tier targets. Untyped
    # source falls through unfiltered. v0.23 simplification: prior to
    # retirement of tier modes, the bossy/grunt-promotion overrides could
    # set a more specific filter and skip this block; now the filter
    # always runs.
    src_tier = tags.get(recipient_cp, {}).get('tier')
    # v0.27.13: field-slot tier roll. A non-catalogued slot is decoupled
    # from its vanilla occupant's tier — it rolls grunt-base with a small
    # configurable upgrade chance (V3_FIELD_UPGRADE_*_PCT). Closes the
    # leak where a beefy-but-not-boss occupant tagged 'miniboss' opened
    # the boss-strength pool on an open-field position. recipient_is_boss
    # slots (real boss Parts in non-catalogued MSBs, e.g. add-randomize
    # arenas) keep occupant-tier-preserve.
    _field_roll_tier = (field_roll_tier_for(slot_msb_name, slot_pi)
                        if not recipient_is_boss else None)
    if _field_roll_tier is not None:
        # src_tier carries the rolled value downstream (the v0.25.6
        # remembrance size gate keys on it; rolled values never match
        # 'remembrance' so that gate is unaffected).
        src_tier = _field_roll_tier
        # Match the rolled tier EXACTLY — a miniboss roll must not yield
        # a night_boss — with a fallback ladder so a roll with no compat-
        # fitting candidate degrades toward grunt instead of leaving the
        # slot vanilla. 'grunt' resolves to the whole field-strength
        # bucket (grunt/trash/cluster_member/...).
        #
        # Exact-match deliberately excludes tier='nightlord' from every
        # field roll: the heaviest tier (true Nightlords + arena-bound
        # MMV boss imports — c6200 Gael, c5130 Messmer, c5300 Rellana,
        # all tagged 'nightlord') is never field-eligible. The night_boss
        # roll draws only from the 39 'night_boss'-tagged chrs. This is
        # what makes the c6200 hawk-route CTD structurally impossible
        # rather than merely improbable — no field slot, of any roll
        # outcome, can admit it.
        _ladder = {'night_boss': ('night_boss', 'miniboss', 'grunt'),
                   'miniboss':   ('miniboss', 'grunt'),
                   'grunt':      ('grunt',)}[_field_roll_tier]
        tier_pool = pool
        for _tname in _ladder:
            if _tname == 'grunt':
                _cand = {cp for cp in pool
                         if tags.get(cp, {}).get('tier')
                         in V3_FIELD_STRENGTH_TIERS}
            else:
                _cand = {cp for cp in pool
                         if tags.get(cp, {}).get('tier') == _tname}
            if _cand:
                tier_pool = _cand
                break
    elif src_tier in V3_BOSS_STRENGTH_TIERS:
        tier_pool = {cp for cp in pool
                     if tags.get(cp, {}).get('tier') in V3_BOSS_STRENGTH_TIERS}
    elif src_tier in V3_FIELD_STRENGTH_TIERS:
        tier_pool = {cp for cp in pool
                     if tags.get(cp, {}).get('tier') in V3_FIELD_STRENGTH_TIERS}
    else:
        tier_pool = pool
    if tier_pool:
        pool = tier_pool

    # v0.25.6: size_class restriction for tier=remembrance source slots.
    # Some remembrance catalog entries are based on small humanoid
    # encampments / patrols (e.g. Bloodhound Knight at m60_45_39_20 pi=28
    # — size=S, anim=humanoid), not proper boss arenas. Without a size
    # gate, the picker could place a GIGA chr (e.g. c4503 Borealis,
    # hit_height=20m, anim=flying_dragon) at a humanoid-scaled slot,
    # which CTDs on tile load (chr-init can't reconcile collision/navmesh
    # bounds against the slot's geometry).
    #
    # Rule: candidate's size_class must not exceed source's by more than
    # 2 steps along the ordered ladder [XS, S, M, L, XL, XXL, GIGA]. So
    # S source → up to L candidate; M → up to XL; L → up to XXL; XL/XXL/
    # GIGA → up to GIGA (already at or near top). Candidates with
    # size_class=None (typical of utility/grunt-tier chrs that won't be
    # GIGA anyway) bypass the gate as a safe fallback.
    #
    # Scoped to remembrance only by deliberate choice (user request,
    # v0.25.6 session): named_boss / field_boss / miniboss tiers either
    # have natural size constraints from their arena bounds or have
    # source variety wide enough that adding a gate here would
    # over-restrict legitimate placements. The remembrance tier is the
    # specific failure mode surfaced in playtest.
    #
    # Falls through to the empty-pool case if the gate produces no
    # candidates — better to leave the slot vanilla than force a bad
    # match. Other gates downstream may still narrow the pool further.
    if src_tier == 'remembrance':
        _SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'GIGA']
        _src_size = tags.get(recipient_cp, {}).get('size_class')
        if _src_size in _SIZE_ORDER:
            _max_idx = _SIZE_ORDER.index(_src_size) + 2
            def _size_ok(cp):
                _sz = tags.get(cp, {}).get('size_class')
                if _sz not in _SIZE_ORDER:
                    return True  # unknown size — safe fallback
                return _SIZE_ORDER.index(_sz) <= _max_idx
            size_pool = {cp for cp in pool if _size_ok(cp)}
            if size_pool:
                pool = size_pool
            # else: leave pool alone; the source slot will stay vanilla
            # if no other gate produces a fitting candidate downstream.

    # v0.20.22: per-slot has_boss_reward filter. Used by 'boss_reward' mode
    # in V3_BOSSY_PROMOTE_SLOTS — narrows the boss-tier pool to c-prefixes
    # that have a real boss reward / arena event. Filters out e.g. c4377
    # Highwayman whose (Scholar Remembrance) variant tags it as miniboss
    # but doesn't fire the boss-arena event chain. Applied after tier so
    # we're already restricted to V3_BOSS_STRENGTH_TIERS first.
    if slot_require_boss_reward:
        reward_pool = {cp for cp in pool
                       if tags.get(cp, {}).get('has_boss_reward')}
        if reward_pool:
            pool = reward_pool
        # else: leave pool alone, the slot will fall through other filters
        # and likely return None — better than silently losing the constraint.

    # v0.27.40: freeze-prone-import addressability gate. Imports in
    # V3_FREEZE_PRONE_IMPORTS (loaded from data/phase_transition_imports.json,
    # the same file emevd_patch.py derives its re-enable markers from) disable
    # their own AI during a phase transition and need the nb_phase_reenable
    # EMEVD event to recover. That event addresses the boss by ENTITY id, so it
    # can only reach entity-bearing slots; a name-marker slot (entity_id == 0)
    # is unreachable and the boss would freeze post-transition with no remedy.
    # So at a name-marker slot, drop freeze-prone imports from the pool. Single-
    # phase imports (Manus/Romina/etc.) are NOT in the set and stay eligible at
    # name-marker terrain slots. slot_eid is the live MSB read from the caller;
    # only gate when we actually know it's a name-marker slot (eid is not None
    # and <= 0) so a missing eid (older callers) never silently empties a pool.
    if (V3_FREEZE_PRONE_IMPORTS and slot_eid is not None and slot_eid <= 0):
        gated = pool - V3_FREEZE_PRONE_IMPORTS
        # If gating would empty the pool, leave it: the slot falls through and
        # likely returns None (stays vanilla) — never force a freeze-prone
        # import onto an unreachable slot, but also never hard-crash a slot.
        if gated:
            pool = gated

    # v0.24.101: asymmetric has_reward preservation. When the recipient slot's
    # c-prefix has has_reward=True (a rewarded encounter in vanilla), restrict
    # the target pool to has_reward=True c-prefixes too. This prevents the
    # "stiffed boss" failure mode where a vanilla rewarded slot gets swapped
    # to a chr that drops nothing on death.
    #
    # Asymmetric by design: recipients with has_reward=False/None can swap
    # in either direction (so a non-rewarded slot can be upgraded to a
    # rewarded encounter — strictly better for the player). Only the
    # rewarded-source case is constrained.
    #
    # Distinct from the slot_require_boss_reward gate above:
    #   - That gate is opt-in per slot (V3_BOSSY_PROMOTE_SLOTS 'boss_reward'
    #     mode), keys on has_boss_reward (rewardItemLot_1-anchored), and is
    #     about promoting non-boss slots TO real boss arenas.
    #   - This gate is automatic on every call, keys on has_reward (broader
    #     field, includes chaosMatchingRewardLotId), and is about preserving
    #     the source slot's reward when has_reward is already True.
    #
    # If the filtered pool is empty the slot gets None and stays vanilla —
    # we'd rather skip the swap than break the reward.
    #
    # v0.27.42: do NOT reward-preserve a slot that the field-roll has
    # decoupled to a grunt position. The field-roll (v0.27.13,
    # field_roll_tier_for) deliberately severs a non-catalogued field slot
    # from its vanilla occupant — a miniboss-tagged-but-field-placed occupant
    # is re-cast as a grunt-tier slot so it draws grunt-base enemies. But
    # has_reward is TIER-DERIVED (miniboss-and-above => True, per
    # dev/emit_has_reward.py), so the occupant still carries has_reward=True
    # without dropping any real loot, and this gate then re-couples the slot
    # to that spurious reward — contradicting the decoupling the roll just
    # performed. The intersection it forms, (grunt-rolled pool) ∩
    # (has_reward=True), is near-empty because grunts are tier-derived
    # NO-reward: in the full roster it collapses to a tiny rewarded-grunt set
    # (often emptying outright -> vanilla), and under all-SOTE it collapses
    # to a single chr (c5240 Shadowpot) that the downstream nav gate then
    # rejects -> empty -> vanilla. Net effect (bug): every Banished Knight
    # (c3010), Elder Lion (c4270), and Troll (c4600) inside the castle
    # (m49_41/42/43) shipped vanilla — in BOTH modes, but always-vanilla in
    # all-SOTE — while the no-reward grunts beside them (c3000 Exile Soldier,
    # c3020 Large Exile Soldier, c4490 Living Jar Warrior) randomized fine.
    #
    # Fix: skip the gate when _field_roll_tier is a field-strength (grunt)
    # roll. A grunt-rolled slot has no reward expectation, so there is
    # nothing to preserve; this restores the field-roll's intended grunt-base
    # draw. miniboss / night_boss field-rolls and catalogued boss/arena slots
    # (_field_roll_tier is None) are UNCHANGED — there the reward-preserve
    # pool is healthy (miniboss+ chrs are tier-derived has_reward=True) so it
    # never spuriously collapses, and genuine boss rewards stay protected.
    _reward_decoupled = (_field_roll_tier is not None
                         and _field_roll_tier not in V3_BOSS_STRENGTH_TIERS)
    if (tags.get(recipient_cp, {}).get('has_reward') is True
            and not _reward_decoupled):
        reward_preserve_pool = {cp for cp in pool
                                if tags.get(cp, {}).get('has_reward') is True}
        if not reward_preserve_pool:
            return None
        pool = reward_preserve_pool

    # v0.20.8: Arena-only target restriction. Some XXL grounded enemies
    # (Divine Beast Dancing Lion etc.) only function at flat boss-arena
    # slots. Variant marker presence (recipient_is_boss=True) is the
    # arena signal — flat-by-design slots all carry boss markers.
    if not recipient_is_boss:
        pool = pool - _arena_only

    # v0.23.72-late+: SECOND ARENA_ONLY gate — slot-marker-based.
    # The first gate (line ~7759) uses recipient_is_boss, which is the
    # SOURCE c-prefix's tier classification (via is_boss_tier_prefix
    # fallback). That gate catches obvious cases but has false positives:
    # when the source c-prefix appears in some boss-tier variants elsewhere
    # in the game (e.g. c4170 Lordsworn has both grunt 'Lordsworn' and
    # 'Lordsworn Captain Fort' variants), recipient_is_boss can be True
    # even at a non-arena slot. That left 3+ documented leaks in v0.20.78
    # (c4580 Large Wormface at Lordsworn Captain Fort m30_00 pi=17,
    # Banished Knight m49_10 pi=3, Highwayman m60_42_37_10 pi=33).
    #
    # This second gate reads the DESTINATION slot's variant name directly
    # and requires it to carry a V3_BOSS_NAME_MARKERS token. Strictly
    # tighter than the source-side gate above. The two layer: gate-1
    # catches the cheap cases without needing variant-name lookup;
    # gate-2 catches the source-classification false-positives.
    #
    # Marker set is the broad one (includes 'Field Boss', 'Castle Boss',
    # 'Encampment', 'Evergaol', 'Boss' bare, etc.). Chrs needing tighter
    # geometric restrictions escalate to V3_NIGHT_BOSS_ONLY_TARGETS or
    # V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS, which apply below.
    #
    # chaos_mode-overrideable to match NIGHT_BOSS_ONLY's chaos behavior:
    # in chaos mode, ARENA_ONLY chrs can leak to field-tier slots for
    # variety. Pure-geometric concerns escalate to NIGHT_BOSS_STRICT.
    #
    # v0.25.7: catalog-derived `arena` field augments the name-marker
    # check. The two paths are OR'd: either the slot variant name
    # carries a V3_BOSS_NAME_MARKERS token (the existing path, captures
    # named arena slots like "Lordsworn Captain Fort"), OR the slot's
    # catalog entry has `arena: True` (derived at module load from the
    # vanilla chr's expects_boss_arena / size_class — captures arena
    # slots whose variant names don't happen to carry marker tokens).
    # Strictly broadens the arena recognition set; never narrows.
    # v0.27.29: catalogued-spawn-pool-boss signal. The Day-2 rotation
    # MSBs (V3_SPAWN_POOL_MSBS pi=1) ferry a boss into a live arena at
    # runtime. The FIELD-twin tiles are named "... (Field Boss)" and so
    # match the markers below; the CASTLE-variant tiles (m46_86/87/88/90/
    # 91/95) use POI-interior names — "(Castle Basement)", "(Castle)" —
    # that only the EXTENDED marker set recognizes, and their catalog
    # `arena` flag is False. Result (bug, found via seed 670313): the
    # marker checks read these as non-arena / non-NB, the _arena_only and
    # NIGHT_BOSS_ONLY subtractions fire, and in all-SOTE mode the small
    # boss-tier SOTE pool empties → pick returns None → the castle boss
    # ships vanilla (user fought a vanilla Bell Bearing Hunter in the
    # Castle Basement). The slot was ALREADY promoted to recipient_is_boss
    # by the v0.24.98 catalog-membership override in shuffle_msb_v3; this
    # makes the arena / night-boss classification here consistent with
    # that promotion. Catalog membership at ANY scope qualifies — same
    # rule as the recipient_is_boss override — so the broad-vs-extended
    # scope split that hides these from the OOPS_ALL_NB picker doesn't
    # also strip their target pool. Narrow: only fires for the enumerated
    # V3_SPAWN_POOL_MSBS pi=1 slots, so it cannot loosen gating elsewhere.
    # v0.27.32: CONSOLIDATED catalogued-boss-arena signal. Replaces three
    # ad-hoc fixes of identical shape — v0.27.29 (_is_catalogued_spawn_pool_
    # boss: castle rotation tiles), v0.27.31 (_is_catalogued_named_boss:
    # evergaols) — plus the latent gaps they didn't reach (cathedral,
    # fort_suffix, mountaintop, boss_suffix, crater, noklateo,
    # castle_interior non-rotation tiles).
    #
    # Root pattern: a slot can be a genuine, scripted boss arena (catalogued
    # in V3_BOSS_SLOT_CATALOG, and already promoted to recipient_is_boss by
    # the v0.24.98 catalog-membership override in shuffle_msb_v3) yet have a
    # variant name whose tokens DON'T match V3_NIGHT_BOSS_NAME_MARKERS (which
    # deliberately excludes 'Evergaol'/'Encampment'/bare 'Boss'/POI-interior
    # names like '(Castle)'). The arena/NB classification here then diverges
    # from the recipient_is_boss promotion: the _arena_only / NIGHT_BOSS_ONLY
    # subtractions fire and, at nav-constrained slots in all-SOTE, strip the
    # only targets that survive the slot's nav gate → empty pool → the boss
    # ships vanilla. Confirmed three times in the field (seed 670313 Castle
    # BBH, seed 230261 Castle Red Wolf + evergaol Banished Knights).
    #
    # Fix: trust the catalog tier over the name markers for the set of tiers
    # that are GENUINELY sealed/scripted boss arenas (below), promoting both
    # _slot_is_arena and _slot_is_night_boss. This makes classification
    # consistent with the recipient_is_boss override across the whole boss-
    # arena tier family at once, instead of patching one slot-shape per
    # release.
    #
    # EXCLUDED tiers (kept on strict marker-based gating, NOT promoted):
    #   - terrain     (147 non-boss terrain anchors)
    #   - encampment  (7 field camp groups — Elder Lion / Mad Pumpkin camps;
    #                  field encounters, not sealed arenas)
    #   - remembrance (100 scholar/remembrance trash — Wandering Noble,
    #                  Cuckoo Knight, etc.; classify correctly via markers
    #                  already, and must NOT admit NB-only chrs)
    # Including the already-marker-correct boss tiers (nightboss / fieldboss
    # / ruins_boss / fort_boss) is a no-op (True OR True); the only NEW
    # promotions are the marker-missing tiers. Narrow: catalog membership at
    # a boss-arena tier only — cannot loosen gating at field/grunt/terrain
    # slots, which are absent from the catalog or in the excluded tiers.
    _slot_catalog_tier = None
    if slot_msb_name is not None and slot_pi is not None:
        _slot_catalog_tier = V3_BOSS_SLOT_CATALOG.get(
            (slot_msb_name, slot_pi), {}).get('tier')
    _is_catalogued_boss_arena = _slot_catalog_tier in V3_CATALOG_BOSS_ARENA_TIERS

    _slot_is_arena = bool(slot_variant_name) and any(
        m in slot_variant_name for m in V3_BOSS_NAME_MARKERS)
    if not _slot_is_arena and slot_msb_name is not None and slot_pi is not None:
        _slot_is_arena = V3_BOSS_SLOT_CATALOG.get(
            (slot_msb_name, slot_pi), {}).get('arena', False)
    if not _slot_is_arena and _is_catalogued_boss_arena:
        _slot_is_arena = True
    if not _slot_is_arena and not chaos_mode:
        pool = pool - _arena_only

    # v0.20.81: NIGHT_BOSS_ONLY restriction — strict subset of ARENA_ONLY.
    # Computed from slot_variant_name rather than recipient_is_boss
    # because V3_NIGHT_BOSS_NAME_MARKERS is a tighter marker set
    # (excludes 'Encampment'/'Evergaol'/bare 'Boss' to avoid compact
    # sub-arenas). See V3_NIGHT_BOSS_ONLY_TARGETS comment block for
    # the rationale.
    #
    # v0.23.11 chaos_mode: when chaos_mode=True, this subtraction is LIFTED
    # at non-NB slots — true Night Boss chrs (Margit, Maliketh, Astel, etc.)
    # become eligible to land at field-boss / overworld slots. Combined
    # with the tightened NB-slot intersection below, this creates a one-way
    # flow: NB chrs leak DOWN to field slots, but field bosses (Trolls,
    # Runebears) cannot leak UP to NB anchor slots — preserving the
    # climactic NB-arena moments while opening the rest of the world to
    # boss-tier surprises.
    _slot_is_night_boss = bool(slot_variant_name) and any(
        m in slot_variant_name for m in V3_NIGHT_BOSS_NAME_MARKERS)
    if not _slot_is_night_boss and _is_catalogued_boss_arena:
        # v0.27.32: consolidated boss-arena promotion. See the
        # _is_catalogued_boss_arena block above. A catalogued boss-arena
        # slot is a real scripted arena; keep night-boss-tier targets (incl.
        # the SOTE night_boss roster) eligible there so the NIGHT_BOSS_ONLY
        # subtraction can't empty the pool at nav-constrained arenas.
        # Subsumes the v0.27.29 (spawn-pool castle) and v0.27.31 (evergaol)
        # promotions and closes the cathedral / fort_suffix / mountaintop /
        # boss_suffix / crater / noklateo gaps that shared the same shape.
        _slot_is_night_boss = True
    if not _slot_is_night_boss and not chaos_mode:
        pool = pool - V3_NIGHT_BOSS_ONLY_TARGETS

    # v0.20.83: NIGHT_OR_FIELD_BOSS_ONLY tier — tightest gate. Only
    # 'Night Boss' / 'Field Boss' marker slots accept these chrs.
    # Excludes Castle/Fort/Ruins-interior + (Crater)/(Noklateo) +
    # Remembrance, which NIGHT_BOSS_ONLY allows.
    _slot_is_night_or_field_boss = bool(slot_variant_name) and any(
        m in slot_variant_name for m in V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS)
    if not _slot_is_night_or_field_boss:
        pool = pool - V3_NIGHT_OR_FIELD_BOSS_ONLY_TARGETS

    # NB-strict, NB-caliber, and source-anim gates all now go through
    # the consolidated _reject_target_for_slot predicate below. See
    # v0.24.27 comment.

    # v0.24.27: mirror-semantic gates consolidated. The three gates
    # below (NB-strict from v0.23.11, source-anim from v0.24.18, and
    # NB-caliber from v0.23.07) all enforce a constraint that the
    # reservation pre-pass must mirror at score-time (because the
    # reservation early-return at line ~8395 bypasses runtime
    # enforcement). They're now consolidated via _reject_target_for_
    # slot — both this picker site AND _score_slot_for_unique
    # delegate to the same predicate, so future gate additions can't
    # accidentally bypass at reservation time.
    #
    # Implementation detail: NB-caliber has empty-pool fallback
    # semantics (if the caliber intersection empties the pool, keep
    # the pre-caliber pool — better to place SOMETHING than nothing).
    # NB-strict and source-anim are absolute (no fallback). The
    # predicate returns the reason string, so we partition rejections
    # into "absolute" (always applied) and "caliber" (applied only if
    # non-empty).
    _absolute_rejected = set()
    _caliber_rejected = set()
    for _t in pool:
        _r = _reject_target_for_slot(_t, recipient_cp, slot_variant_name,
                                      tags, chaos_mode=chaos_mode,
                                      msb_base=slot_msb_name, pi=slot_pi,
                                      slot_pos=slot_pos, run_ctx=run_ctx)
        if _r is None:
            continue
        if _r == 'nb_caliber':
            _caliber_rejected.add(_t)
        else:
            _absolute_rejected.add(_t)
    # Apply absolute rejections unconditionally — NB-strict and
    # source-anim leak that drained the pool means the slot stays
    # vanilla, which is the desired outcome.
    pool = pool - _absolute_rejected
    # Apply caliber rejection only if non-empty — preserves the
    # original "intersect-or-keep" semantics.
    _caliber_filtered = pool - _caliber_rejected
    if _caliber_filtered:
        pool = _caliber_filtered

    # v0.23.09: NB-arena exclude set — subtract chrs that break specifically
    # at NB anchor slots (scripted-intro fails, chr stands idle). Doesn't
    # affect their availability at field slots.
    if _slot_is_night_boss and V3_NIGHT_BOSS_EXCLUDE_TARGETS:
        pool = pool - V3_NIGHT_BOSS_EXCLUDE_TARGETS

    # v0.23.05.2: compat at scripted-intro boss slots.
    # Margit-style softlock fix. Slots whose vanilla chr has
    # expects_boss_arena=True OR carries a Night Boss name marker run
    # scripted spawn cinematics that hardcode the source chr's family
    # — Margit's intro is a humanoid teleport-and-land, Crucible Knight's
    # is a humanoid sword-plant, Dragonkin's is a quadruped roar, etc.
    # Substituting a chr with an incompatible family (e.g., quadruped
    # Demi-Human Queen at humanoid Margit slot) means the cinematic plays
    # an animation the substitute doesn't have, the cinematic stalls
    # waiting for a "complete" signal that never fires, boss UI locks,
    # fight can't start → softlock.
    #
    # Confirmed in seeds 887995 + 974234: m48_40 pi=0 c2130 Margit Night
    # Boss → c4130 Demi-Human Queen (humanoid → quadruped). Same swap
    # both seeds, same softlock both seeds.
    #
    # v0.20.0 retired pool-level family pre-filtering, accepting the
    # broader cross-class swaps for variety. This fix is targeted: only
    # scripted-intro slots get the strict compat filter; grunt slots
    # and field encounters keep the loose v0.20.0 behavior. Variety cost
    # is contained to ~50-100 boss arena slots.
    #
    # Untagged candidates (no family) bypass — preserves the cluster-
    # member placements (c4181 Maris Jellyfish, c5110 Tendril, c3610
    # Oracle Envoy) that legitimately work via cluster-shape matching.
    # v0.24.100: scripted-intro anim_class compat filter REMOVED. The
    # previous block (v0.23.05.2) narrowed `pool` to candidates whose
    # family was compatible with the recipient's via _compat_rig.
    # Function is gone; the flier-vs-ground split that mattered is now
    # enforced upstream by is_compatible / the flier-required slot gate.
    _slot_is_arena = tags.get(recipient_cp, {}).get('expects_boss_arena', False)
    _is_scripted_intro = _slot_is_arena or _slot_is_night_boss

    chosen_pool = list(pool)

    # v0.20.34: SENSITIVE-only slots — softer than full fragile. Subtracts
    # V3_FRAGILE_SENSITIVE_TARGETS without restricting to RESILIENT.
    # See V3_SENSITIVE_ONLY_SLOTS docstring for design rationale.
    # Mutually exclusive with V3_PROBLEM_SLOTS in practice — full fragile
    # supersedes if a slot is somehow in both, since RESILIENT excludes
    # everything in SENSITIVE anyway.
    if (slot_msb_name is not None and slot_pi is not None
            and (slot_msb_name, slot_pi) in V3_SENSITIVE_ONLY_SLOTS
            and V3_FRAGILE_SENSITIVE_TARGETS):
        chosen_pool = [cp for cp in chosen_pool
                       if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
        if not chosen_pool:
            return None

    # v0.20.64: soft off-mesh slot check. Off-mesh slots are no longer
    # classified as fragile (T2.6 retired in is_fragile_slot), but they
    # still pose a CTD risk for SENSITIVE c-prefixes whose AI specifically
    # breaks at non-vanilla terrain. At slots that are off-mesh but NOT
    # otherwise fragile, just exclude SENSITIVE — don't restrict to SAFE,
    # don't prefer floaters. This keeps full enemy variety at most off-
    # mesh slots while still preventing the known-CTD interactions.
    if (slot_msb_name is not None
            and not is_fragile_slot(slot_msb_name, slot_pi, slot_variant_name,
                                     slot_pos=slot_pos)):
        off_mesh_set = _load_off_mesh_slots()
        if (slot_msb_name, slot_pi) in off_mesh_set:
            if V3_FRAGILE_SENSITIVE_TARGETS:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
                if not chosen_pool:
                    return None

    if slot_msb_name is not None and is_fragile_slot(
            slot_msb_name, slot_pi, slot_variant_name, slot_pos=slot_pos):
        if disable_resilient_filter and diagnostic_test_targets is not None:
            # v0.20.42: explicit batch-test mode. User has named the
            # exact c-prefixes they want to test at fragile slots, so
            # bypass ALL the inclusion/exclusion machinery (RESILIENT,
            # SAFE_CONFIRMED, SENSITIVE) and trust the explicit set.
            # Use case: batching CTD attribution — restrict each run
            # to a small set so CTDs are unambiguously tied to one of
            # those c-prefixes. Or retesting a SENSITIVE entry under
            # different conditions (tunnel-wakeup hypothesis, etc.).
            chosen_pool = [cp for cp in chosen_pool
                           if cp in diagnostic_test_targets]
            if not chosen_pool:
                return None
        elif disable_resilient_filter:
            # v0.20.35: diagnostic mode. v0.20.37: untested-only filter.
            # v0.20.40: also exclude V3_FRAGILE_SAFE_CONFIRMED — those
            # are already-tested-and-safe; re-testing them yields no new
            # info. v0.27.0: SAFE_CONFIRMED was retired as the *fragile
            # gate* (production now uses the SENSITIVE blacklist only),
            # but it is preserved as a data set precisely for this
            # diagnostic path — it is still the "known-tested" record,
            # so subtracting it here still yields the untested pool:
            #   pool - SAFE_CONFIRMED - SENSITIVE = not-yet-tested
            # This is the SENSITIVE-retest workflow's entry point: as
            # chrs are confirmed safe at fragile slots, ADD them to
            # SAFE_CONFIRMED to take them out of the diagnostic pool.
            # If empty, the slot stays vanilla (return None).
            resilient_set = V3_RESILIENT_BIPEDS
            chosen_pool = [cp for cp in chosen_pool
                           if cp not in resilient_set
                           and cp not in V3_FRAGILE_SAFE_CONFIRMED]
            if not chosen_pool:
                return None
            # Apply SENSITIVE blacklist below (untested-only path).
            if V3_FRAGILE_SENSITIVE_TARGETS:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
                if not chosen_pool:
                    return None
        else:
            # v0.20.48: at off-mesh slots in production mode, PREFER
            # floater-class c-prefixes (jellyfish family) — they don't
            # need navmesh, so they work where ground-pathing AI fails.
            # Fall through to standard fragile filter if no compat
            # overlap with floaters.
            # v0.20.40 / v0.24.86-patch7: production fragile-slot filter
            # uses RESILIENT ∪ SAFE_CONFIRMED. Each diagnostic confirmation
            # immediately expands fragile-slot variety in production runs.
            # (Patch7 collapsed the dead v0.20.48 floater-preference if-else
            # branch — V3_OFF_MESH_PREFERRED_TARGETS was empty since v0.20.68
            # and the if-arm never executed. Same filter logic, less code.)
            # v0.27.0: WHITELIST -> BLACKLIST flip. The production
            # fragile-slot filter used to be inclusion-only: a c-prefix
            # had to be in V3_FRAGILE_SAFE_CONFIRMED (a 157-entry hand-
            # curated playtest whitelist) to land at a fragile slot.
            # That whitelist was archived -- it had two fatal problems:
            # it rotted (every new chr / pack needed manual extension,
            # and all 41 MMV chrs were silently locked out of fragile
            # slots, which is what surfaced this), and it conflated
            # three distinct freeze classes under one flag. See the
            # three-freeze-class note at V3_FRAGILE_SENSITIVE_TARGETS.
            #
            # New rule: at a fragile slot, EVERY c-prefix is allowed
            # EXCEPT the V3_FRAGILE_SENSITIVE_TARGETS blacklist (the
            # locomotion/geometry-mismatch chrs a fragile slot genuinely
            # can't host) and the per-slot EXTRA_BANS below. The
            # SENSITIVE subtraction that follows is now the load-bearing
            # guard, not a redundant defensive pass.
            allowed_set = None  # None = "all allowed"; blacklist does the work
            _extra_allows = V3_PROBLEM_SLOT_EXTRA_ALLOWS.get(
                (slot_msb_name, slot_pi))
            # EXTRA_ALLOWS is now a no-op for inclusion (everything is
            # already allowed) but harmless; left wired in case a future
            # change reintroduces a per-slot inclusion gate.
            _ = _extra_allows
            # No inclusion filter — chosen_pool passes through. SENSITIVE
            # blacklist + EXTRA_BANS below are the only fragile-slot cuts.
            if V3_FRAGILE_SENSITIVE_TARGETS:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in V3_FRAGILE_SENSITIVE_TARGETS]
                if not chosen_pool:
                    return None
            # v0.23.62: per-slot extra c-prefix bans. See
            # V3_PROBLEM_SLOT_EXTRA_BANS docstring. Targets specific
            # SAFE-classified c-prefixes that nonetheless break at
            # particular fragile slots (e.g., large_boss_ground GIGA
            # at Cathedral Guardian Golem source — anim-bank-mismatch
            # freezes despite passing the SAFE filter).
            extra_bans = V3_PROBLEM_SLOT_EXTRA_BANS.get(
                (slot_msb_name, slot_pi))
            if extra_bans:
                chosen_pool = [cp for cp in chosen_pool
                               if cp not in extra_bans]
                if not chosen_pool:
                    return None

    if target_count is not None:
        # Global per-cprefix placement cap. v0.24.86-patch7 collapsed
        # the v0.20.65 per-cprefix dispatch — the tighter 25-cap was
        # paired with V3_OFF_MESH_PREFERRED_TARGETS (retired); with
        # floater-preference gone, all c-prefixes share the global cap.
        capped_pool = [cp for cp in chosen_pool
                       if target_count.get(cp, 0) < V3_TARGET_PLACEMENT_CAP]
        if capped_pool:
            chosen_pool = capped_pool

    if not chosen_pool:
        return None

    # v0.28: per-slot hashed pick. Keying the choice on (seed, msb, pi)
    # over a sorted pool makes the cp decision a pure function of slot
    # identity — order-independent, so a contaminated/reordered input no
    # longer cascades, and simulate_engine.py matches the engine. Uniform
    # over the same pool as before; only the per-slot selection is now
    # deterministic. Falls back to the shared rng for callers that don't
    # supply slot identity (slot_msb_name/slot_pi).
    if slot_msb_name is not None and slot_pi is not None:
        _picker = _slot_decision_rng(slot_msb_name, slot_pi).choice
    else:
        _picker = rng.choice  # sorting happens inside _choose_with_budget
    # v0.28 hybrid budget/recycle. No run_ctx or an unset (0) budget => an
    # empty resident set and an unbounded budget, which reduces this to the
    # plain hashed pick over sorted(chosen_pool) — identical to pre-v0.28.
    #
    # v0.28.x Phase 2 (POI recycling): route through active_* helpers so
    # when shuffle_msb_v3 has armed a cluster scope via run_ctx.begin_poi()
    # the picker reads the per-cluster resident set and budget instead of
    # the per-MSB ones. Picker code path unchanged — only the scope of
    # "resident" changes. Falls back to the direct attr read for
    # RunContext snapshots that predate the helpers.
    if run_ctx is None:
        _resident, _budget = set(), 1 << 30
    elif hasattr(run_ctx, 'active_resident_cps'):
        _resident = run_ctx.active_resident_cps() or set()
        _budget = run_ctx.active_distinct_budget() or (1 << 30)
    else:
        _resident = getattr(run_ctx, 'msb_resident_cps', None) or set()
        _budget = getattr(run_ctx, 'msb_distinct_budget', 0) or (1 << 30)
    result, _kind = _choose_with_budget(chosen_pool, _resident, _budget, _picker)
    if result is None:
        return None
    # v0.23.07: bump unique-cap counter for organic picks. Reserved picks
    # already pre-bumped during the reservation pre-pass; this catches
    # picks that landed on a capped cp via normal pool selection.
    if result in V3_UNIQUE_TARGET_CAPS:
        _placed_counts[result] = _placed_counts.get(result, 0) + 1
    return result



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
                    spoiler_entries=None,
                    oops_all_target_cp=None,
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
    """Returns (n_swaps, n_models_added, n_skipped_compat, n_clusters) on success,
    or None on parse fail.

    v0.23.72-late: bank_to_prefixes / loose_to_prefixes / mode dropped from
    signature (see compatible_pool docstring).

    pinned_only_in_hub:
      False (default) — process every Part normally.
      True — only process Parts whose (msb, pi) is in
              V3_BOSS_TIER_PINNED_SLOTS. All other Parts stay vanilla.
              Set internally by rando_pipeline when a HUB_MAP has
              pinned slots; preserves NPC dialogues / quest triggers
              while still randomizing explicitly-listed boss-tier
              slots inside hubs.
    """
    # v0.24.22 (Phase 5.5): runtime bookkeeping refs. Same resolve
    # pattern as pick_target_cp — run_ctx=None reads/writes the module
    # dicts (preserving back-compat for any direct caller that hasn't
    # been updated), explicit RunContext reads/writes its dicts. The
    # production cmd_shuffle_v3 path constructs a RunContext at the
    # top of every run and threads it through, so module-dict writes
    # are unreachable in production except via the final back-copy
    # at end of cmd_shuffle_v3 (kept for spoiler-emit observability).
    if run_ctx is None:
        _placed_counts = _V3_UNIQUE_PLACED_COUNTS
    else:
        _placed_counts = run_ctx.unique_placed_counts
    with open(input_path, 'rb') as f: data = bytearray(f.read())  # mutable for v0.23.04 collapse pass
    sections = parse_msb_sections(data)
    if len(sections) != 6: return None

    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]
    midx_to_cp = {gi: parse_model_entry(data, eo)['name']
                  for gi, eo in enumerate(models['entry_offsets'])}

    # v0.23.04: Rider+mount collapse pass — runs before cluster detection and
    # before the swap loop. Suppresses the mount Part of each detected pair
    # (npc_param := 0, vanilla "no spawn" convention) and copies the mount's
    # world position onto the rider Part so the rider's eventual swap target
    # spawns at the player-engagement coords. Already-preserved pairs (per
    # V3_EXCLUDE_SOURCE_PREFIXES / V3_EXCLUDE_SOURCE_NPC_PARAMS) are skipped,
    # so Tree Sentinel arenas and Night's Cavalry arena remain fully vanilla
    # in current ship.
    #
    # v0.24.101: DISABLED. The collapse pass zeroes the *combat* mount's
    # npc_param but doesn't address the visual mount that comes through the
    # rider's spawn cluster — playtest seed 537123 caught Godskin Apostle
    # visibly on the Cavalry horse at m46_62 Evergaol even though the c3160
    # combat Part was zeroed. Falling back to broad c-prefix exclusion of
    # all rider+mount pairs while this is debugged. After v0.24.101, with
    # c3150/c3160/c3170/c3180/c4050/c4060/c4363 all in both
    # V3_EXCLUDE_SOURCE_PREFIXES and V3_EXCLUDE_TARGET_PREFIXES, the
    # collapse pass would have nothing to do anyway (its first skip clause
    # at line ~1042 catches all 4 RIDER_MOUNT_PAIRS entries). Kept around
    # as dead code so the implementation isn't lost when revisited.
    #
    # TODO(v0.25+): re-enable the collapse pass after investigating the
    # rider-cluster visual-mount issue. Likely needs to also reset the
    # rider Part's cluster_id or break its anim cluster binding so the
    # new chr doesn't inherit the mount visual. May also need handling
    # for the Tree Sentinel-style "rider cluster includes pre-attached
    # mount model" pattern more generally. Once that lands, the broad
    # c3150 source-exclude (added v0.24.101) can be lifted again.
    rider_mount_collapses = []  # _collapse_rider_mount_pairs(data, parts, midx_to_cp)  # v0.24.101: disabled
    if rider_mount_collapses:
        _V3_TRACE_BUFFER.append({
            'event': 'RIDER_MOUNT_COLLAPSE',
            'msb': os.path.basename(input_path),
            'n_pairs': len(rider_mount_collapses),
            'pairs': rider_mount_collapses,
        })

    # v0.27.44 (Alaric): preserve EVERY rider+mount pair at the SLOT level.
    # Supersedes the v0.27.43 c5840<->c5890 coordinated-swap family AND avoids
    # the blunt c-prefix source-exclude: those would freeze the FOOT instances
    # of riders that also appear dismounted (Kaiden c4050, Leyndell/Lordsworn
    # Knight c4353, Albinauric Archer c3170) vanilla too. Instead, detect the
    # actual paired Parts (RIDER_MOUNT_PAIRS prefix combo + proximity; the
    # detector's 2.0u threshold is validated against vanilla — every known
    # pair sits <=1.78u apart) and add BOTH the rider Part and its mount Part
    # to V3_PRESERVE_SLOTS for this MSB. The existing strict (msb, pi) preserve
    # gate (see ~line 13180) then returns None for exactly those two slots, so
    # they stay vanilla. A SOLO rider or SOLO mount is never matched, so it
    # keeps randomizing normally. Runs every MSB (the old mount_rider_swap
    # toggle only logged the detection; it never acted on it). Reuses the
    # existing preserve gate, so spoiler/audit reporting stays consistent.
    _mr_detected = _detect_mount_rider_slots(data, parts, midx_to_cp)
    if _mr_detected:
        _mr_msb_key = os.path.basename(input_path)
        if _mr_msb_key.endswith('.dcx'):
            _mr_msb_key = _mr_msb_key[:-4]
        _mr_added = _preserve_detected_rider_mount_pairs(_mr_detected, _mr_msb_key)
        _V3_TRACE_BUFFER.append({
            'event': 'RIDER_MOUNT_PAIR_PRESERVE',
            'msb': _mr_msb_key,
            'n_pairs': len(_mr_detected),
            'n_newly_preserved': len(_mr_added),
            'preserved_pis': sorted(
                {_d['rider_pi'] for _d in _mr_detected}
                | {_d['mount_pi'] for _d in _mr_detected}),
            'pairs': _mr_detected,
        })


    # v0.26.13: cluster system removed. Every Part rolls independently.
    # n_clusters retained as a vestigial 0 in the return tuple to avoid a
    # return-arity change across callers / pipeline metadata / tests.
    n_clusters = 0

    # v0.20.15: shared-position placeholder pre-pass.
    # Some MSBs author script-spawn placeholder blocks where many Parts share
    # the same authored position; the spawn script reads NPCParam from each
    # placeholder slot at runtime to type-check what model to summon. The
    # v0.20.11/.12 heuristic only catches the eid==0 subset. The castle
    # m15_00 has a 39-Part block at (52.11, 0.3, 26.57) with sequential eids
    # 15000430–468 (basement boss event waves) that has eid != 0 and so
    # leaks through the older heuristic. m46_70 and m49_27 show the same
    # pattern at smaller scale.
    # Cluster-managed Parts are excluded from the count (they go through
    # the cluster path) so we don't accidentally flag e.g. Crystalian
    # triplets that happen to share a spawn point.
    placeholder_pos_counts = Counter()
    for _spi, _spo in enumerate(parts['entry_offsets']):
        if _spo + 0x400 + 12 > len(data):
            continue
        try:
            _sx, _sy, _sz = struct.unpack_from('<fff', data, _spo + 0x400)
            # NaN check without importing math
            if _sx != _sx or _sy != _sy or _sz != _sz:
                continue
            _rp = (round(_sx * 2) / 2,
                   round(_sy * 2) / 2,
                   round(_sz * 2) / 2)
            placeholder_pos_counts[_rp] += 1
        except struct.error:
            pass
    placeholder_positions = {p for p, n in placeholder_pos_counts.items()
                          if n >= V3_PLACEHOLDER_POSITION_THRESHOLD}
    # v0.23.60: per-MSB intercept counter for the placeholder-position cap.
    # Keyed by rounded position; values count OOPS_ALL_NB intercepts
    # that have fired at that position. See V3_OOPS_ALL_NB_PLACEHOLDER_CAP.
    _placeholder_intercept_counts = {}

    # === Build swap plan ===
    swap_plan = []
    n_skipped_compat = 0
    # v0.23.72-late+: n_skipped_aerial was removed. The aerial-skip filters
    # were ripped out in the v0.23.72 NB-boss-anchor bypass work (see comment
    # block ~line 9042 area, formerly here). The counter was kept at 0 for
    # a release cycle to avoid a return-signature churn, now cleaned up.
    # v0.23.51: hoist msb_base to outer scope so per-slot lookups
    # (V3_PROBLEM_SLOTS, V3_BOSS_TIER_PINNED_SLOTS) work in any branch
    # of the loop, not just the terrain_test branch where it was
    # originally defined.
    msb_base = os.path.basename(input_path)
    if msb_base.endswith('.dcx'):
        msb_base = msb_base[:-4]
    # v0.23.54: hoist effective OOPS_ALL_NB target/scope to function scope.
    # The pre-cluster intercept reads these per-slot, but the big-proximity
    # post-pass also needs them to know which slots to exempt from demotion.
    # Defining once at the top makes both accesses cheap and unambiguous.
    _eff_nb_target = (oops_all_nb_target_cp
                      if oops_all_nb_target_cp is not None
                      else OOPS_ALL_NB_TARGET_CP)
    _eff_nb_scope = (oops_all_nb_marker_scope
                     if oops_all_nb_marker_scope is not None
                     else OOPS_ALL_NB_MARKER_SCOPE) or 'broad'
    # v0.23.52: full MSB Part inventory diagnostic. When this MSB matches
    # the V3_DIAGNOSTIC_INVENTORY_MSBS set, log EVERY Part to the trace.
    # Resolves "where the hell is BBH in this MSB" questions without
    # needing Oodle for offline DCX decompression. Runs at zero cost
    # when the set is empty. v0.23.68: extracted to helper.
    if msb_base in V3_DIAGNOSTIC_INVENTORY_MSBS:
        _emit_msb_part_inventory_trace(data, parts, midx_to_cp, msb_base)
    # v0.28.x Phase 2: default POI scope vars to None at the outer level
    # so the slot loop below can reference them when run_ctx is None
    # (legacy/test paths that don't arm per-MSB state at all).
    _pi_to_cid = None
    _cluster_budgets = None
    # v0.27.5: arm the placement-time proximity/density gates for this
    # MSB. Caps follow the tunnel-vs-default profile the DENSITY_CAP
    # post-pass used.
    if run_ctx is not None:
        # v0.28: derive the per-MSB distinct budget + forced-vanilla
        # resident seed from a cheap read-only pre-scan of the same slots
        # the swap loop visits. budget = the count of distinct enemy
        # c-prefixes vanilla loads here; the loop introduces no more than
        # that, so the tile's chrbnd fan-out can't exceed vanilla's.
        # _preserved = enemy c-prefixes the loop keeps vanilla (excluded /
        # source-only / no-variants / pinned); they are already loaded, so
        # they seed resident and count against the budget.
        # v0.28: per-MSB rando-distinct budget. Working assumption: the
        # engine loads its own vanilla assets cheaply (bundled with the map,
        # not stressing the dynamic chr-registration path the respawn CTD
        # overflowed), so forced-vanilla slots are NOT charged against the
        # budget. The budget counts only distinct enemy c-prefixes on
        # SWAPPABLE slots — how many distinct *rando* chrbnds this tile may
        # introduce. Preserved slots still keep vanilla in the output.
        #
        # v0.28.x Phase 2 POI recycling: when V3_POI_SCOPE_RECYCLE is on
        # and slot_poi_clusters.json has an entry for this MSB, the same
        # pre-scan loop also builds a per-cluster swappable-distinct set
        # so the picker's resident/budget can scope to the smaller POI
        # cluster instead of the whole MSB. _pi_to_cid is the inverse map
        # from part_index to cluster_id within this MSB (-1 for slots
        # outside the cluster file, typically non-enemy parts).
        _poi_active = (V3_POI_SCOPE_RECYCLE
                       and _V3_SLOT_POI_CLUSTERS is not None
                       and _V3_SLOT_POI_CLUSTERS.get(msb_base) is not None)
        if _poi_active:
            _msb_clusters_for_iter = _V3_SLOT_POI_CLUSTERS[msb_base]
            _pi_to_cid = {}
            for _cid, _members in enumerate(_msb_clusters_for_iter):
                for _pi_m in _members:
                    _pi_to_cid[_pi_m] = _cid
            _cluster_swappable = defaultdict(set)
        else:
            _msb_clusters_for_iter = None
            _pi_to_cid = None
            _cluster_swappable = None

        _swappable_distinct = set()
        for _pi, _po in enumerate(parts['entry_offsets']):
            try:
                _npc = struct.unpack_from('<I', data, _po + PART_OFF_NPC_PARAM)[0]
                if _npc == 0 or _npc == 0xFFFFFFFF:
                    continue
                _midx = struct.unpack_from('<i', data, _po + PART_OFF_MODEL_INDEX)[0]
            except struct.error:
                continue
            _ccp = midx_to_cp.get(_midx, '?')
            if not (_ccp and _ccp[0] == 'c' and len(_ccp) > 1 and _ccp[1].isdigit()):
                continue
            if ((msb_base, _pi) in V3_BINARY_SEARCH_VANILLA_PINS
                    or (pinned_only_in_hub
                        and (msb_base, _pi) not in V3_BOSS_TIER_PINNED_SLOTS)
                    or _ccp in V3_EXCLUDE_PREFIXES
                    or _ccp in V3_EXCLUDE_SOURCE_PREFIXES
                    or _npc in V3_EXCLUDE_SOURCE_NPC_PARAMS
                    or _ccp not in prefix_variants):
                continue  # vanilla-kept: cheap, not charged against the budget
            _swappable_distinct.add(_ccp)
            if _cluster_swappable is not None:
                _cluster_swappable[_pi_to_cid.get(_pi, -1)].add(_ccp)
        _msb_budget = len(_swappable_distinct)
        if _cluster_swappable is not None:
            _cluster_budgets = {cid: len(cps)
                                for cid, cps in _cluster_swappable.items()}
        else:
            _cluster_budgets = None
        if msb_base in V3_TUNNEL_MAPS:
            run_ctx.begin_msb(V3_TUNNEL_DENSITY_CAP_XL_PLUS,
                              V3_TUNNEL_DENSITY_CAP_L_PLUS,
                              distinct_budget=_msb_budget,
                              caps=V3_UNIQUE_TARGET_CAPS)
        else:
            run_ctx.begin_msb(V3_DENSITY_CAP_XL_PLUS,
                              V3_DENSITY_CAP_L_PLUS,
                              distinct_budget=_msb_budget,
                              caps=V3_UNIQUE_TARGET_CAPS)
    # v0.27.13: per-MSB random slot order. The swap loop previously
    # iterated parts in strict ascending pi. That gave low-pi slots a
    # systematic advantage in any order-sensitive per-MSB accounting —
    # most notably the density caps (run_ctx.register_big /
    # V3_DENSITY_CAP_*), which accumulate as the loop runs: a big chr at
    # a low pi always got first crack at the density budget, a big chr
    # at a high pi was more often density-blocked, purely by Part index.
    # Shuffling the (pi, po) PAIRS per MSB removes that positional bias —
    # every slot has equal expected position in the processing order.
    #
    # Scope is within-MSB only: MSBs themselves stay in their original
    # order, because begin_msb/end_msb scopes the density caps per MSB
    # and a cross-MSB shuffle would interleave that accounting. pi stays
    # paired with its po (pi is an identity key downstream — catalog
    # lookups, spoiler entries, swap_plan); only the visit order changes.
    # swap_plan is applied in a separate pass that re-derives po from pi,
    # so the output is identical regardless of visit order — this shifts
    # only the order in which order-sensitive runtime state is touched.
    # Uses the shared seeded rng, so it is reproducible per seed.
    # v0.28: canonical (natural part-index) slot order. Previously this was
    # rng.shuffle'd off the shared stream, which made the processing order —
    # and thus the order-dependent target_count cap — input-dependent. With
    # the per-slot hashed pick (_slot_decision_rng) the order no longer
    # affects which enemy a slot gets, and a canonical order makes cap
    # consumption deterministic and identical to simulate_engine.py's
    # sorted(part_index) pass.
    #
    # v0.28.x Phase 2 POI recycling: when POI scope is active, slots are
    # reordered so same-cluster slots are adjacent. Order is still fully
    # canonical: clusters in cluster_id order (which the builder assigns
    # by min(part_index) within MSB), slots in pi order within cluster.
    # 50/124 multi-cluster MSBs already have pi-contiguous clusters; the
    # rest interleave (worst m60_42_36_50 at 60% pi-boundaries). The
    # cluster-grouped order produces ONE begin_poi/end_poi pair per
    # cluster instead of N inline transitions. -1 (slots outside the
    # cluster file, e.g. non-enemy parts that get filtered out in the
    # slot body anyway) is placed LAST so they pick up no POI scope.
    if _pi_to_cid is not None:
        _grouped = defaultdict(list)
        for _pi_g, _po_g in enumerate(parts['entry_offsets']):
            _grouped[_pi_to_cid.get(_pi_g, -1)].append((_pi_g, _po_g))
        _slot_order = []
        for _cid_o in sorted(_grouped, key=lambda c: (c == -1, c)):
            _slot_order.extend(_grouped[_cid_o])
    else:
        _slot_order = list(enumerate(parts['entry_offsets']))
    _current_cluster = None  # tracks POI scope transitions inside the loop
    for pi, po in _slot_order:
        # v0.28.x Phase 2: cluster-transition detection. When the
        # cluster_id for this pi differs from the active one, close the
        # previous POI scope and open the new one. -1 (slots outside the
        # cluster file) means no POI scope active — picker falls back
        # to MSB-level resident/budget. With cluster-grouped order
        # above, this fires exactly once per real cluster.
        if _pi_to_cid is not None and run_ctx is not None:
            _this_cluster = _pi_to_cid.get(pi, -1)
            if _this_cluster != _current_cluster:
                if (_current_cluster is not None and _current_cluster != -1
                        and hasattr(run_ctx, 'end_poi')):
                    run_ctx.end_poi()
                if (_this_cluster != -1 and hasattr(run_ctx, 'begin_poi')
                        and _cluster_budgets is not None):
                    run_ctx.begin_poi(
                        _this_cluster,
                        _cluster_budgets.get(_this_cluster, _msb_budget))
                _current_cluster = _this_cluster
        # v0.24.109 binary-search vanilla pins. For diagnostic A/B testing
        # of specific (msb, pi) slots — pinned slots skip the picker
        # entirely and remain vanilla in the output MSB. Used to bisect
        # framerate / CTD issues to specific slot subsets without
        # re-running the full rando. Set V3_BINARY_SEARCH_VANILLA_PINS
        # to the (msb_base, pi) tuples you want forced-vanilla, then
        # reroll with the same seed for a clean diff.
        if (msb_base, pi) in V3_BINARY_SEARCH_VANILLA_PINS:
            continue
        npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0]
        if npc == 0 or npc == 0xFFFFFFFF: continue  # placeholder
        # v0.23.68: HUB_MAPS pinned-only mode. When this flag is set
        # (rando_pipeline routes hub MSBs with pinned entries here), only
        # process slots that appear in V3_BOSS_TIER_PINNED_SLOTS for this
        # MSB. Every other Part stays vanilla — preserves NPC dialogues,
        # quest triggers, merchant interactions in hub interiors while
        # still randomizing explicitly-listed boss-tier slots inside.
        if pinned_only_in_hub and (msb_base, pi) not in V3_BOSS_TIER_PINNED_SLOTS:
            continue
        midx = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        cur_cp = midx_to_cp.get(midx, '?')
        if cur_cp in V3_EXCLUDE_PREFIXES: continue
        if cur_cp in V3_EXCLUDE_SOURCE_PREFIXES:
            # v0.20.18: log preserved-source slots for tracked c-prefixes
            # so the spoiler MD can render "Source slots (preserved as
            # vanilla)" for c3610/c3620 (Oracle Envoys), etc. Read the
            # position once for the log; we don't need slot_pos parsed
            # the same way the heuristic does.
            if cur_cp in V3_TRACKED_C_PREFIXES:
                _pres_pos = None
                if po + 0x400 + 12 <= len(data):
                    try:
                        _px, _py, _pz = struct.unpack_from('<fff', data, po + 0x400)
                        if not (_px != _px or _py != _py or _pz != _pz):
                            _pres_pos = [round(_px, 2), round(_py, 2), round(_pz, 2)]
                    except struct.error:
                        pass
                _pres_eid = (struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0]
                             if po + PART_OFF_ENTITY_ID + 4 <= len(data) else None)
                _V3_PRESERVED_SOURCE_LOG.append({
                    'map':           os.path.basename(input_path),
                    'part_index':    pi,
                    'entity_id':     _pres_eid,
                    'position':      _pres_pos,
                    'c_prefix':      cur_cp,
                    'npc_param_id':  npc,
                    'name':          _variant_name(cur_cp, npc, prefix_variants),
                })
            continue  # source-only exclusion
        if npc in V3_EXCLUDE_SOURCE_NPC_PARAMS: continue   # per-variant source exclusion
        if cur_cp not in prefix_variants:
            # v0.20.20: only log Enemy-class Parts (cur_cp starts with 'c'
            # followed by a digit). MSB Asset Parts (AEG_xxx geometry
            # decorations, AEG570_xxx world FX) and Collision Parts (h_xxx)
            # also iterate through this loop because parts['entry_offsets']
            # spans multiple Part subtypes; they correctly have no variants
            # and never get swapped, but logging them as bug candidates
            # drowns the signal. ~864 false-positive entries in seed-42
            # made this section unusable until the filter was added.
            if cur_cp and cur_cp[0] == 'c' and len(cur_cp) > 1 and cur_cp[1].isdigit():
                _log_unaccounted('no_variants',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
            continue
        # v0.19: target-only-promoted c-prefixes (script_spawn,
        # er_heritage_v1, etc.) keep their (rare/zero) MSB placements
        # vanilla. Their synthesized prefix_variants entries are for
        # picking npc/think IDs when chosen as a target — never used
        # as sources. Stays vanilla at any rare MSB placements like
        # Ancestor Spirit / Nameless King at special arena maps.
        #
        # v0.24.97: NARROW EXEMPTION for V3_SPAWN_POOL_MSBS pi=1.
        # The original "no MSB placements" rationale for this gate
        # (see V3_TARGET_ONLY_SOURCES docstring at line ~388) was
        # empirically wrong — c4670 and c4690 have 2 placements each
        # at m46_64/65/90/91 pi=1 (the spawn-pool rotation entries),
        # and the 19 sibling rotation entries (m46_52 c3250, m46_53
        # c3251, ...) already swap pi=1 successfully via this same
        # per-Part path. Without this exemption Grafted Scion and
        # Ancestor Spirit appear deterministically across every seed
        # at whichever live arena rolls those rotation entries,
        # defeating the randomization at those two pool slots each.
        #
        # TODO(broad-fix): drop `_source: script_spawn` from
        # V3_TARGET_ONLY_SOURCES entirely. That additionally unlocks
        # c7700/c7710/c77xx/c78xx/c79xx as sources at dedicated legacy
        # DS-import arena MSBs (m47_80, m47_90, m48_00, m48_10, m48_20,
        # m48_30). Different risk profile — those arenas are designed
        # around the specific boss footprint, so source-swap geometry
        # / chrbnd-preload mismatch is more plausible than the
        # rotation case. Audit case-by-case before lifting.
        if (cur_cp in tags
                and tags[cur_cp].get('_source') in V3_TARGET_ONLY_SOURCES
                and not _is_spawn_pool_rotation_source(msb_base, pi)):
            # v0.20.20: this is expected-vanilla architecture, not a bug.
            # See unaccounted-vanilla-log docstring — kept as a separate
            # reason so we can still surface unexpected occurrences but
            # they no longer count toward the "probable bugs" framing.
            _log_unaccounted('script_spawn_target_only_at_msb',
                             os.path.basename(input_path), pi, cur_cp, npc,
                             data, po, prefix_variants)
            continue

        # v0.23.58: PRE-CLUSTER OOPS_ALL_NB INTERCEPT — hoisted ABOVE the
        # eid==0 + near-origin filter and the shared-position placeholder
        # filter. Background:
        #
        # NR's spawn-pool MSBs (m46_5x_00_00 etc.) pack pi=0 c1000 +
        # pi=1 boss (+ pi=2 asset on the 3-Part FIELD tiles), all at world
        # origin (0,0,0). The shared-position placeholder pre-pass counts
        # how many Parts share a rounded position; >= V3_PLACEHOLDER_POSITION
        # _THRESHOLD (3) at one position marks it a script-spawn placeholder
        # block and the boss Part there is left vanilla. With all Parts
        # stacked at origin a 3-Part tile can trip this; pi=1 then stays
        # vanilla and the rotation chr appears un-randomized in-game.
        # (Historical: a separate eid==0 + near-origin filter and a cluster
        # builder also used to drop pi=1 here; both were removed —
        # near-origin v0.23.72, clustering v0.26.13. The placeholder
        # pre-pass is the one still live.)
        #
        # Mitigation: catalogued boss slots (V3_BOSS_SLOT_CATALOG) and
        # pinned slots (V3_BOSS_TIER_PINNED_SLOTS) are AUTHORITATIVE — if
        # the catalog/pin says this is a boss slot, the rando trusts that
        # over the placeholder heuristic and force-swaps it.
        #
        # Note: this force-swap intercept is gated on `_eff_nb_target`
        # (OOPS_ALL_NB boss-probe mode), so in a normal or all-SOTE run it
        # doesn't fire. That is BY DESIGN and was NOT the cause of the
        # castle-variant 0-swap bug (initially suspected here, but ruled
        # out — see the "castle-variant spawn-pool MSBs now swap" block
        # above; the real cause was name-marker classification in
        # pick_target_cp, fixed in v0.27.29). In normal/SOTE runs the
        # spawn-pool slots swap through the standard pick_target_cp path
        # like any other catalogued boss slot.
        #
        # _eff_nb_target / _eff_nb_scope hoisted to function scope above.
        _is_pinned = (msb_base, pi) in V3_BOSS_TIER_PINNED_SLOTS
        _is_catalogued = is_catalogued_boss_slot(msb_base, pi, _eff_nb_scope)
        # v0.23.60: pre-compute rounded position for the placeholder cap. We
        # need this BEFORE the intercept fires (the slot_pos read further
        # down is also fine, but it's after the early aerial/none-pos
        # skips, which we want to keep in front of the heavier work).
        _intercept_pos_key = None
        if po + 0x400 + 12 <= len(data):
            try:
                _ix, _iy, _iz = struct.unpack_from('<fff', data, po + 0x400)
                if not (_ix != _ix or _iy != _iy or _iz != _iz):  # NaN-safe
                    _intercept_pos_key = (round(_ix * 2) / 2,
                                          round(_iy * 2) / 2,
                                          round(_iz * 2) / 2)
            except struct.error:
                pass
        # Cap: if this slot's position is already a placeholder cluster AND
        # the intercept has fired V3_OOPS_ALL_NB_PLACEHOLDER_CAP times for
        # that position in this MSB, don't intercept this slot. Falls
        # through to the standard path; the placeholder filter below will
        # leave the slot vanilla. Prevents N-stacks of XL chrs at script-
        # spawn placeholder blocks (m15_00 (52.11,0.3,26.57) — 39 Parts).
        _intercept_capped = (
            _intercept_pos_key is not None
            and _intercept_pos_key in placeholder_positions
            and _placeholder_intercept_counts.get(_intercept_pos_key, 0)
                >= V3_OOPS_ALL_NB_PLACEHOLDER_CAP
        )
        if (_eff_nb_target
                and not terrain_test_targets
                and not oops_all_target_cp
                and (_is_pinned or _is_catalogued)
                and not _intercept_capped):
            # Force this slot to the OOPS_ALL_NB target, bypassing the
            # cluster-vanilla-preserve and solo-pick_target paths below.
            target_cp = _eff_nb_target
            target_variant = pick_variant_for_tier(
                target_cp, True, prefix_variants, rng, tags=tags,
                run_ctx=run_ctx)
            if target_variant is None:
                # Target c-prefix not loaded (e.g., MMV-only target with
                # MMV disabled). Log and fall through to standard handling.
                # This is NOT a silent failure — _log_unaccounted records
                # it, and the slot continues to the cluster/solo branches
                # so it still gets a swap (not left vanilla unexpectedly).
                _log_unaccounted('oops_all_nb_target_unavailable',
                                 msb_base, pi, cur_cp, npc,
                                 data, po, prefix_variants)
                # Fall through — don't 'continue' or 'append' here;
                # let cluster/solo branches handle the slot normally.
            else:
                swap_plan.append((pi, target_cp,
                                  target_variant['npc_param_id'],
                                  target_variant['think_param_id']))
                # v0.23.60: bump the per-position counter so subsequent
                # slots at this same placeholder cluster will hit the cap.
                if _intercept_pos_key is not None and _intercept_pos_key in placeholder_positions:
                    _placeholder_intercept_counts[_intercept_pos_key] = (
                        _placeholder_intercept_counts.get(_intercept_pos_key, 0) + 1)
                # Trace event so the spoiler shows the intercept fired
                _V3_TRACE_BUFFER.append({
                    'event':  'OOPS_ALL_NB_INTERCEPT',
                    'msb':    msb_base,
                    'pi':     pi,
                    'source': 'pin' if _is_pinned else 'catalog',
                    'tier':   (V3_BOSS_SLOT_CATALOG.get((msb_base, pi), {}).get('tier')
                               if _is_catalogued else 'pin'),
                    'target_cp':    target_cp,
                    'target_npc':   target_variant['npc_param_id'],
                })
                continue
        elif (_eff_nb_target
              and not terrain_test_targets
              and not oops_all_target_cp
              and (_is_pinned or _is_catalogued)
              and _intercept_capped):
            # v0.23.60: cap fired. Trace it (one entry per capped slot)
            # and fall through to the standard path; the placeholder filter
            # will leave this slot vanilla.
            _V3_TRACE_BUFFER.append({
                'event': 'OOPS_ALL_NB_INTERCEPT_CAPPED',
                'msb': msb_base,
                'pi': pi,
                'pos_key': list(_intercept_pos_key) if _intercept_pos_key else None,
                'cap': V3_OOPS_ALL_NB_PLACEHOLDER_CAP,
                'hits_at_pos': _placeholder_intercept_counts.get(_intercept_pos_key, 0),
            })

        # v0.20.0: slot_y read removed. Position-aware source skip and
        # AERIAL_SOURCE_SKIP are obsolete — empirical breakages handled
        # by V3_PROBLEM_SLOTS / V3_FRAGILE_MAPS / V3_EXCLUDE_*.
        slot_y = None

        # v0.23.72: AERIAL-SKIP / SPAWN-MARKER FILTERS REMOVED.
        #
        # Two filter blocks used to live here:
        #   1. eid==0 + near-origin (v0.20.11/.12) — caught EMEVD script-
        #      spawn placeholders by signature. The original v0.20.11 bug
        #      report ("frozen guy on overworld traversal") motivated this,
        #      but the actual CTD root cause was addressed elsewhere
        #      (swap_compat layer / merchant-model handling), so this filter
        #      stopped earning its keep.
        #   2. shared-position placeholder (v0.20.15) — caught eid!=0 slots
        #      that share position with N+ siblings. Same script-spawn-
        #      placeholder pattern by a different signature.
        #
        # The v0.23.71 pin-bypass tried to rescue legitimate slots that hit
        # these filters (spawn-pool m46 tiles with pi=1 boss at origin),
        # but pin coverage is incomplete — m49 NB arenas (and probably
        # others) aren't in t1_anchors, so their boss slots were silently
        # dropped from the swap pool. Symptom: NB1/NB2 encounter doesn't
        # start when the circle closes because the boss MSB part is missing
        # from the output. Confirmed via user playtest: Sentient Pest seed
        # 35300, m49_27 pi=? (entity 49270800) Battlefield Commander absent
        # from output MSB → empty arena.
        #
        # We still read slot_eid + slot_pos here because slot_pos is used
        # downstream (edge-sentinel detection in is_fragile_slot, line
        # ~8379). The reads are kept; only the early-exit filters were
        # removed.
        #
        # v0.23.72-late+: n_skipped_aerial counter removed from return
        # tuple. Was preserved-at-zero for one release cycle to avoid
        # signature churn; now cleaned out.
        slot_eid = struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0] \
                   if po + PART_OFF_ENTITY_ID + 4 <= len(data) else -1
        slot_pos = None
        if po + 0x400 + 12 <= len(data):
            try:
                _x, _y, _z = struct.unpack_from('<fff', data, po + 0x400)
                import math as _math
                if not (_math.isnan(_x) or _math.isnan(_y) or _math.isnan(_z)):
                    slot_pos = (_x, _y, _z)
            except struct.error:
                pass

        # Determine THIS Part's tier (used for variant selection regardless of clustering)
        recipient_variant = next((v for v in prefix_variants[cur_cp]
                                   if v['npc_param_id'] == npc), None)
        if recipient_variant is None:
            recipient_is_boss = is_boss_tier_prefix(cur_cp, tags, prefix_variants)
        else:
            recipient_is_boss = is_boss_tier_variant(recipient_variant)
        # v0.24.98: V3_BOSS_SLOT_CATALOG override. The catalog is the
        # authoritative source for slot-tier classification (per the
        # v0.23.58 comment block at line ~11584: "the catalog was built
        # from a careful inventory of NR's MSBs; if it says this is a
        # boss slot, the rando trusts that classification"). Pre-v0.24.98
        # that authoritativeness only flowed into the OOPS_ALL_NB intercept
        # — the normal recipient_is_boss decision relied on
        # is_boss_tier_variant's V3_BOSS_NAME_MARKERS substring check,
        # which misses the parenthesized-suffix tier categories: (Fort),
        # (Castle), (Cathedral), (Crater), (Noklateo), (Mountaintop),
        # plus the curated 'named_boss' entries (Crucible Knight,
        # Fallingstar Beast Random Encounter, etc.). 104 of 340 catalog
        # entries fell into that gap, including the three (Fort) slots
        # not already in V3_BOSSY_PROMOTE_SLOTS — m30_00 pi=17 (Lordsworn
        # Captain Fort), m30_00 pi=36 (Abductor Virgin Fort), m30_30 pi=7
        # (Crystalian Fort) — which were swapping to grunt/trash targets
        # like Mushroom Dog because the picker didn't restrict to
        # boss-strength tiers. With this override, catalog membership at
        # any scope promotes the slot's recipient_is_boss to True.
        #
        # Plain 'bossy' equivalent (V3_BOSS_STRENGTH_TIERS restriction
        # only). The four (Fort), three (Cathedral), and ten (Castle)
        # interior slots are likely also fog-wall encounters that would
        # benefit from 'boss_reward' mode (the stricter has_boss_reward
        # filter that excludes Highwayman/Bloodhound miniboss-class
        # humanoids), but that's an empirical playtest question per-tier.
        # V3_BOSSY_PROMOTE_SLOTS still applies below for per-slot
        # boss_reward upgrades when audit-confirmed.
        if (msb_base, pi) in V3_BOSS_SLOT_CATALOG:
            recipient_is_boss = True
        # v0.27.1: NB-anchor boss promotion. NR's Night Boss arenas use
        # entity_id % 10000 == 800 for the primary boss anchor (the same
        # signature the emerge-marker bypass below relies on). For some
        # vanilla boss c-prefixes — notably c3050 Commander — the variant
        # carries an empty variant_name, so is_boss_tier_variant returns
        # False and is_boss_tier_prefix('c3050') also fails (no reward, sub-4m
        # hit height, not heritage). That left recipient_is_boss=False for
        # the actual night boss. Harmless until v0.27.0's add-randomize
        # carve-out, which keys on recipient_is_boss: in V3_ADD_RANDOMIZE_
        # ARENAS the Commander anchor was being read as an add and SWAPPED
        # OUT (seed 791285: m49_26 pi8 + m49_27 pi13 c3050 -> Watchdog /
        # Elder Lion). Promote any 800-anchor in an m48_/m49_ map to
        # boss-tier so the carve-out preserves it. Unconditional — does not
        # depend on recipient_variant being empty-named.
        if (msb_base is not None
                and (msb_base.startswith('m48_')
                     or msb_base.startswith('m49_'))
                and slot_eid > 0 and slot_eid % 10000 == 800):
            recipient_is_boss = True
        # v0.23.22: source-side emerge-marker skip. The engine already has
        # filter_emerge_variants for TARGETS (so we never write an emerge-
        # placeholder NPCParam) but no equivalent for SOURCES. A source slot
        # whose vanilla NPCParam has an empty variant_name is by FromSoft convention
        # an event-driven spawn placeholder — vanilla EMEVD owns the spawn
        # via ForceAnimationPlayback + a follow-up "is the chr still the
        # expected NPCParam" check that despawns if not. Swapping those slots
        # produces visible bugs: the event fires, the swapped chr appears
        # briefly, then despawns when the verify step finds an unexpected
        # NPCParam. User-confirmed example (seed 373504, m48_40_00_00 pi=1):
        # vanilla c2140 emerge-marker (npc_param 21400220, empty name) was
        # swapped to c2271 Crab during Morgott Night Boss. EMEVD fired "A
        # Fell Omen Has Appeared", spawned the crab, then despawned it when
        # the recognition check failed.
        #
        # Detection: source variant's variant_name is empty/whitespace. This
        # mirrors the v0.23.04.1 target-side empty-name filter at
        # pick_variant_for_tier:1726.
        if (recipient_variant is not None
                and not (recipient_variant.get('variant_name') or '').strip()):
            # v0.23.72: NB-boss-anchor bypass. NR's Night Boss arena maps
            # (m49_xx, m48_xx) consistently use entity_id ending in 800 for
            # the primary boss anchor slot — e.g. m49_10 Grafted Monarch at
            # 49100800, m49_27 Battlefield Commander at 49270800. These are
            # NOT emerge-markers; they're the actual boss chr at the actual
            # boss slot. The empty-variant_name signal is a false positive
            # caused by missing metadata in nr_all_slots.json for some
            # vanilla boss c-prefixes (data-pipeline issue to fix
            # separately — see TODO). Confirmed via user playtest seed
            # 35300, Sentient Pest expedition: m49_27 pi=13 c3050
            # Battlefield Commander was filtered here and the NB1
            # encounter failed to start (empty arena when circle closed).
            #
            # Bypass criterion: slot is in an NB arena map (m48_/m49_) AND
            # entity_id mod 10000 == 800. This is narrow enough to not
            # rescue actual emerge-markers (which sit in field/grunt slot
            # entity ranges) but covers all 16 Nightlord NB1+NB2 anchors.
            _map_base = os.path.basename(input_path)
            _is_nb_anchor = (
                (_map_base.startswith('m48_') or _map_base.startswith('m49_'))
                and slot_eid > 0
                and slot_eid % 10000 == 800
            )
            if not _is_nb_anchor:
                n_skipped_compat += 1  # bucketed with compat skips for stat purposes
                _log_unaccounted('source_emerge_marker',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        # v0.20.21: per-slot bossy-tier promotion. Forces the slot to draw
        # from boss-strength target pools regardless of source-variant
        # tagging. See V3_BOSSY_PROMOTE_SLOTS docstring.
        # v0.20.22: dict-of-modes — 'bossy' or 'boss_reward'.
        _promote_mode = V3_BOSSY_PROMOTE_SLOTS.get(
            (os.path.basename(input_path), pi))
        if _promote_mode is not None:
            recipient_is_boss = True
        _slot_require_boss_reward = (_promote_mode == 'boss_reward')

        # Non-clustered: independent roll
        if (oops_all_nb_pinned_slot is not None
                and oops_all_nb_target_cp
                and (msb_base, pi) == oops_all_nb_pinned_slot):
            # v0.24.25: surgical single-slot pin. When oops_all_nb_
            # pinned_slot=(msb, pi) is set AND this is that slot, force
            # the target. Every other slot in this run rolls normally.
            # Use case: test a specific MMV / cross-engine boss at one
            # known-stable arena slot, without confounding the result
            # with the same chr appearing at other slots that might
            # CTD. Bypasses tier/compat/exclude gates entirely — the
            # whole point is to force-test a specific placement.
            #
            # Pairs naturally with oops_all_nb_target_cp; ignores
            # oops_all_nb_marker_scope (the pin IS the marker).
            target_cp = oops_all_nb_target_cp
            target_variant = pick_variant_for_tier(
                target_cp, recipient_is_boss, prefix_variants, rng,
                tags=tags, run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        elif terrain_test_targets:
            # v0.19.6: terrain test mode — pick c-prefix purely from
            # navmesh classification, bypass all fragile/problem/resilient
            # heuristics. Used to validate that terrain status alone is
            # sufficient for broken-slot detection.
            # v0.23.51: msb_base hoisted to loop top.
            terrain_status = lookup_slot_terrain(msb_base, pi)
            # v0.19.9: V3_PROBLEM_SLOTS manual blocklist also forces Jelly.
            # User can pin specific (msb, pi) entries (e.g., known-broken
            # encampment positions) without needing a whole-map flag.
            if (msb_base, pi) in V3_PROBLEM_SLOTS:
                target_cp = terrain_test_targets['off_mesh']
            elif terrain_status == 'no_match':
                # Sentinel — keep vanilla
                continue
            elif terrain_status in ('off_mesh', 'proximity_off_mesh', 'force_off_mesh'):
                target_cp = terrain_test_targets['off_mesh']
            else:
                # on_mesh OR unknown (slot not in cache) → on_mesh target
                target_cp = terrain_test_targets['on_mesh']
            target_variant = pick_variant_for_tier(
                target_cp, recipient_is_boss, prefix_variants, rng,
                tags=tags, run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        elif oops_all_target_cp:
            # Force every slot to the chosen c-prefix; bypass compat check.
            target_cp = oops_all_target_cp
            target_variant = pick_variant_for_tier(
                target_cp, recipient_is_boss, prefix_variants, rng,
                tags=tags, run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        elif (oops_all_nb_pinned_slot is None  # v0.24.25: pinned mode is exclusive
              and (_effective_nb_target_cp := (oops_all_nb_target_cp
                                            if oops_all_nb_target_cp is not None
                                            else OOPS_ALL_NB_TARGET_CP))
              and (_effective_scope := (oops_all_nb_marker_scope
                                        if oops_all_nb_marker_scope is not None
                                        else OOPS_ALL_NB_MARKER_SCOPE))
              and (
                  # v0.24.28: starting_encampment scope. When set,
                  # match is strictly MSB-membership. Does NOT also
                  # fire on V3_BOSS_TIER_PINNED_SLOTS or variant
                  # markers — the whole point of this scope is to
                  # test ONLY the starting encampment, surgically.
                  (_effective_scope == 'starting_encampment'
                   and msb_base in V3_STARTING_ENCAMPMENT_MSBS)
                  or
                  # Other scopes (strict/broad/extended): the
                  # existing fall-through chain — BOSS_TIER_PINNED
                  # slot match OR variant-marker match for the
                  # scope's marker set.
                  (_effective_scope != 'starting_encampment'
                   and (
                       (msb_base, pi) in V3_BOSS_TIER_PINNED_SLOTS
                       or (
                           recipient_variant is not None
                           and any(
                               _m in recipient_variant.get('variant_name', '')
                               for _m in (
                                   V3_NIGHT_BOSS_STRICT_NAME_MARKERS
                                   if _effective_scope == 'strict'
                                   else V3_NIGHT_BOSS_EXTENDED_NAME_MARKERS
                                   if _effective_scope == 'extended'
                                   else V3_NIGHT_BOSS_NAME_MARKERS
                               )
                           )
                       )
                   ))
              )):
            # v0.23.31: Force every Night Boss slot to OOPS_ALL_NB_TARGET_CP.
            # v0.23.38: marker scope is now tri-valued
            # (strict/broad/extended). Extended adds Castle interior,
            # Encampment, Evergaol, Mountaintop Ruins, Duo Night Boss
            # markers — useful for CTD probes that need to hit Day-2
            # Castle slots and POI bosses.
            # v0.23.39: kwargs override module-global fallback. GUI
            # passes config-driven values via the kwarg path; CLI /
            # legacy callers without these kwargs fall back to the
            # OOPS_ALL_NB_TARGET_CP / OOPS_ALL_NB_MARKER_SCOPE module
            # globals (preserves old direct-edit-the-source workflow).
            # Non-matching slots fall through to the normal pick_target path.
            target_cp = _effective_nb_target_cp
            target_variant = pick_variant_for_tier(
                target_cp, True, prefix_variants, rng, tags=tags,
                run_ctx=run_ctx)
            if target_variant is None:
                n_skipped_compat += 1
                _log_unaccounted('variant_for_tier_none',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
        else:
            target_cp, target_variant = pick_target(
                cur_cp, tags,
                prefix_variants, prefix_count, recipient_is_boss, rng,
                target_count=target_count, slot_y=slot_y,
                slot_msb_name=os.path.basename(input_path),
                slot_pi=pi,
                slot_variant_name=(recipient_variant.get('variant_name', '')
                                   if recipient_variant else ''),
                slot_pos=slot_pos,  # v0.20.16: edge-sentinel detection
                slot_eid=slot_eid,  # v0.27.40: freeze-prone addressability gate
                slot_require_boss_reward=_slot_require_boss_reward,  # v0.20.22
                disable_resilient_filter=disable_resilient_filter,  # v0.20.35
                non_fragile_baseline_cp=non_fragile_baseline_cp,  # v0.20.38
                diagnostic_test_targets=diagnostic_test_targets,  # v0.20.42
                chaos_mode=chaos_mode,  # v0.23.11
                gates=gates,  # v0.24.21
                run_ctx=run_ctx,  # v0.24.21 (Phase 5)
            )
            if target_cp is None:
                n_skipped_compat += 1
                _log_unaccounted('no_target_found',
                                 os.path.basename(input_path), pi, cur_cp, npc,
                                 data, po, prefix_variants)
                continue
            if target_count is not None:
                target_count[target_cp] = target_count.get(target_cp, 0) + 1

        swap_plan.append((pi, target_cp,
                          target_variant['npc_param_id'],
                          target_variant['think_param_id']))
        # v0.27.5: register the committed placement into per-MSB size
        # state so later slots in this MSB see it for the proximity /
        # density gates. Covers every commit path — pick_target,
        # oops_all, NB-forced, pinned — since it follows the unified
        # swap_plan.append.
        if run_ctx is not None:
            # v0.28: record the committed c-prefix as resident so later
            # slots in this MSB can recycle it (and so it counts against
            # the distinct budget). Idempotent; covers every commit path.
            #
            # v0.28.x Phase 2: add_resident_cp updates the per-cluster
            # resident set too when a POI scope is armed (begin_poi() was
            # called by the cluster-grouped swap loop). Falls back to a
            # direct msb_resident_cps.add for older RunContext snapshots.
            if hasattr(run_ctx, 'add_resident_cp'):
                run_ctx.add_resident_cp(target_cp)
            else:
                run_ctx.msb_resident_cps.add(target_cp)
            _committed_sz = _effective_size_class(target_cp, tags)
            if _committed_sz in V3_DENSITY_L_SIZE_CLASSES:
                run_ctx.register_big(_committed_sz, slot_pos)

    if run_ctx is not None:
        # v0.28.x Phase 2: close any active POI scope before end_msb.
        # end_msb() also clears POI state defensively, but closing
        # explicitly here keeps current_poi_id=None for any code between
        # the swap loop and end_msb that reads run_ctx state.
        if _pi_to_cid is not None and hasattr(run_ctx, 'end_poi'):
            run_ctx.end_poi()
        run_ctx.end_msb()  # v0.27.5: disarm per-MSB size gates
    if not swap_plan:
        with open(output_path, 'wb') as f: f.write(data)
        return (0, 0, n_skipped_compat, n_clusters)

    # v0.27.5: the v0.21 BIG_PROXIMITY and v0.23.61 DENSITY_CAP
    # swap-plan post-passes were removed here. Their work is now done
    # at placement time by Gates 8 (proximity) and 9 (density) in
    # _reject_target_for_slot — a big that would clip a neighbour or
    # bust the per-MSB budget drops out of the candidate pool and the
    # picker selects a smaller chr through its normal pipeline. Because
    # the gates never fire for reservations, a reserved big chr can no
    # longer be demoted (closes the reservation-floor-demotion bug).

    # === v0.23.66 FINAL-PASS EXTRA_BANS ENFORCEMENT ===
    # Belt-and-suspenders: scan the final swap_plan and revert any
    # entry whose (msb, pi, target_cp) lands in V3_PROBLEM_SLOT_EXTRA_BANS
    # to vanilla. This catches cases where pick_target_cp's per-slot ban
    # got bypassed by a code path I didn't anticipate (cluster picks,
    # intercept paths, demote post-passes that don't consult the ban).
    # Empirical motivation: seed 342245 v0.23.65 playtest had c5010 Hippo
    # land at m38_00 pi=51 despite the ban being in EXTRA_BANS — root
    # cause unidentified, but a final-pass check is robust regardless.
    #
    # When triggered, the slot is preserved as vanilla (entry removed
    # from swap_plan) and a trace event is logged so the failure mode is
    # visible.
    _msb_basename_for_finalpass = os.path.basename(input_path)
    _filtered_swap_plan = []
    for entry in swap_plan:
        _pi, _tcp = entry[0], entry[1]
        _bans_at_slot = V3_PROBLEM_SLOT_EXTRA_BANS.get(
            (_msb_basename_for_finalpass, _pi))
        if _bans_at_slot and _tcp in _bans_at_slot:
            _V3_TRACE_BUFFER.append({
                'event': 'FINALPASS_EXTRA_BANS_REVERT',
                'map': _msb_basename_for_finalpass,
                'pi': _pi,
                'attempted_cp': _tcp,
                'attempted_npc': entry[2],
            })
            continue  # drop this entry → slot stays vanilla
        _filtered_swap_plan.append(entry)
    swap_plan = _filtered_swap_plan

    # Step 1: ensure all target c-prefixes exist in Models section
    n_added = 0
    for cp in sorted(set(t for _, t, _, _ in swap_plan)):
        if find_model_index(data, cp) < 0:
            sib = f'W:\\CL\\data\\Model\\chr\\{cp}\\sib\\{cp}.sib'
            data, _ = add_model_entry(data, cp, sib, model_type=2)
            n_added += 1

    # Step 2: rebuild offsets after Models additions
    sections = parse_msb_sections(data)
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]
    target_to_idx = {parse_model_entry(data, eo)['name']: gi
                     for gi, eo in enumerate(models['entry_offsets'])}

    # Step 3: rewrite Parts in one pass
    out = bytearray(data)
    map_name = os.path.basename(input_path)
    # v0.23.72-late: track position shifts applied. Used by both the spoiler
    # write (each affected entry gets a 'position_shift' field) and the
    # end-of-MSB trace event.
    _pos_shifts_applied = []
    for pi, target_cp, target_npc, target_think in swap_plan:
        po = parts['entry_offsets'][pi]
        new_idx = target_to_idx[target_cp]
        old_idx = struct.unpack_from('<i', out, po + PART_OFF_MODEL_INDEX)[0]

        # v0.23.72-late: POSITION SHIFT — look up the slot's shift entry
        # (if any) and decide whether to apply it. Skipped if:
        #   - No shift entry for this (msb, pi)
        #   - Position field is past end of Part record (DummyEnemy etc.)
        #   - Position is NaN (treated as "no static position")
        #   - Part is in a cluster (cluster aesthetics > shift benefit)
        # All decisions are logged into the trace event regardless of
        # outcome so we can audit why a shift didn't apply.
        # v0.27.0: two independent contributions stack into one write:
        #   - V3_POSITION_SHIFTS slot dxyz (slot-specific geometry fix)
        #   - V3_MODEL_Y_OFFSET per-c-prefix dy (chr-specific origin fix)
        # Either may be absent; if both are, nothing is written.
        _shift_entry = lookup_position_shift(map_name, pi)
        _model_dy = lookup_model_y_offset(target_cp)
        _shift_applied = None
        _shift_skipped_reason = None
        if _shift_entry or _model_dy:
            if po + 0x400 + 12 > len(out):
                _shift_skipped_reason = 'no_position_field'
            else:
                _ox, _oy, _oz = struct.unpack_from('<fff', out, po + 0x400)
                import math as _m
                if _m.isnan(_ox) or _m.isnan(_oy) or _m.isnan(_oz):
                    _shift_skipped_reason = 'nan_position'
                else:
                    if _shift_entry:
                        _sdx, _sdy, _sdz = _shift_entry['dxyz']
                    else:
                        _sdx, _sdy, _sdz = 0.0, 0.0, 0.0
                    # model Y-offset stacks onto the slot shift's Y
                    _dx, _dy, _dz = _sdx, _sdy + _model_dy, _sdz
                    _nx, _ny, _nz = _ox + _dx, _oy + _dy, _oz + _dz
                    struct.pack_into('<fff', out, po + 0x400, _nx, _ny, _nz)
                    _shift_applied = {
                        'from': (round(_ox, 3), round(_oy, 3), round(_oz, 3)),
                        'to':   (round(_nx, 3), round(_ny, 3), round(_nz, 3)),
                        'dxyz': (_dx, _dy, _dz),
                        'slot_dxyz': (_sdx, _sdy, _sdz),
                        'model_dy': _model_dy,
                        'note': (_shift_entry.get('note', '')
                                 if _shift_entry else
                                 f'model Y-offset only ({target_cp})'),
                    }
            _pos_shifts_applied.append({
                'pi': pi,
                'target_cp': target_cp,
                'applied': _shift_applied,
                'skipped_reason': _shift_skipped_reason,
            })

        # Capture original values BEFORE overwriting (for spoiler log)
        if spoiler_entries is not None:
            orig_npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0]
            orig_cp = midx_to_cp.get(old_idx, '?')
            entity_id = (struct.unpack_from('<i', data, po + PART_OFF_ENTITY_ID)[0]
                         if po + PART_OFF_ENTITY_ID + 4 <= len(data) else None)
            # Position field at 0x400 may be past end of some Part subtypes.
            # v0.23.72-late: read from `data` (original) not `out` (already
            # shifted above) so the spoiler shows the AUTHORED position. The
            # shift, if any, is recorded separately in 'position_shift'.
            position = None
            if po + 0x400 + 12 <= len(data):
                x, y, z = struct.unpack_from('<fff', data, po + 0x400)
                # NaN values break json.dump; treat them as missing
                import math
                if not (math.isnan(x) or math.isnan(y) or math.isnan(z)):
                    position = [round(x, 2), round(y, 2), round(z, 2)]
            new_variant = next((v for v in prefix_variants.get(target_cp, [])
                                if v.get('npc_param_id') == target_npc), None)
            is_boss = is_boss_tier_variant(new_variant) if new_variant else \
                      is_boss_tier_prefix(target_cp, tags, prefix_variants)
            # v0.23.54: tag spoiler entries with their boss-slot catalog
            # tier (or None for non-boss slots). Makes it trivial to
            # filter the spoiler for "all catalogued boss slots" or
            # "what got placed at the Castle Field Boss arena" without
            # re-classifying.
            _cat_entry = V3_BOSS_SLOT_CATALOG.get((map_name, pi))
            from_catalog_tier = _cat_entry.get('tier') if _cat_entry else None
            from_catalog_scope = _cat_entry.get('scope') if _cat_entry else None
            # v0.27.13: rolled field-slot tier. Mirrors the roll
            # pick_target_cp made for this slot (same pure function), so
            # the spoiler shows which non-catalogued slots were upgraded.
            # Annotated only on actual upgrades — base grunt rolls and
            # catalogued/boss slots omit the field (None) to keep the
            # spoiler lean, matching the in_starting_encampment pattern.
            # NOTE (merge): the uploaded oops_v3.py used `recipient_is_boss`
            # here, which is NOT in scope in the spoiler writer — a latent
            # NameError. `is_boss` (computed just above from the actual
            # placed variant) is the correct in-scope value and is what
            # the field-roll exclusion wants anyway.
            _field_roll = (field_roll_tier_for(map_name, pi)
                           if not is_boss else None)
            _entry = {
                'map':         map_name,
                'part_index':  pi,
                'entity_id':   entity_id,
                'position':    position,
                'cluster_id':  None,  # v0.26.13: cluster system removed
                'is_boss':     is_boss,
                'catalog_tier':  from_catalog_tier,
                'catalog_scope': from_catalog_scope,
                **({'field_roll': _field_roll}
                   if _field_roll in ('miniboss', 'night_boss') else {}),
                # v0.24.28: starting-encampment annotation. True when this
                # placement is inside an MSB tagged as a starting encampment
                # in data/nr_starting_encampments.json. Helps post-run
                # CTD attribution ("I crashed near spawn — what was at
                # the starting encampment?") and serves as the filter
                # for oops_all_nb_marker_scope='starting_encampment'.
                # Omitted (rather than False) when not applicable so old
                # parsers don't see new fields they don't expect.
                **({'in_starting_encampment': True}
                   if map_name in V3_STARTING_ENCAMPMENT_MSBS
                   else {}),
                'original':    {'c_prefix': orig_cp,
                                'name': _variant_name(orig_cp, orig_npc, prefix_variants),
                                'npc_param_id': orig_npc},
                'new':         {'c_prefix': target_cp,
                                'name': _variant_name(target_cp, target_npc, prefix_variants),
                                'npc_param_id': target_npc,
                                # v0.24.35: classify the variant source so
                                # spoilers visibly distinguish canonical /
                                # ghost-variant / imported-chr placements.
                                # See _classify_variant_source docstring.
                                'variant_source': _classify_variant_source(
                                    target_cp, target_npc, prefix_variants, tags)},
            }
            # v0.23.72-late: surface the position shift in the spoiler so
            # users can tell at a glance which placements were shifted and
            # by how much (vs. originals).
            if _shift_applied is not None:
                _entry['position_shift'] = {
                    'applied': True,
                    'shifted_to': list(_shift_applied['to']),
                    'dxyz': list(_shift_applied['dxyz']),
                    'note': _shift_applied['note'],
                }
            elif _shift_entry is not None and _shift_skipped_reason:
                _entry['position_shift'] = {
                    'applied': False,
                    'skipped_reason': _shift_skipped_reason,
                    'note': _shift_entry.get('note', ''),
                }
            spoiler_entries.append(_entry)
        struct.pack_into('<i', out, po + PART_OFF_MODEL_INDEX, new_idx)
        struct.pack_into('<I', out, po + PART_OFF_NPC_PARAM, target_npc)
        struct.pack_into('<I', out, po + PART_OFF_THINK_PARAM, target_think)
        # Update instance counts on old + new
        old_e = models['entry_offsets'][old_idx]; new_e = models['entry_offsets'][new_idx]
        c_old = struct.unpack_from('<i', out, old_e + 0x18)[0]
        struct.pack_into('<i', out, old_e + 0x18, c_old - 1)
        c_new = struct.unpack_from('<i', out, new_e + 0x18)[0]
        struct.pack_into('<i', out, new_e + 0x18, c_new + 1)

    # v0.23.72-late: surface the per-MSB position-shift summary into the
    # trace buffer. Empty when V3_POSITION_SHIFTS is empty (current state).
    if _pos_shifts_applied:
        _V3_TRACE_BUFFER.append({
            'event': 'POSITION_SHIFTS',
            'msb': map_name,
            'shifts': _pos_shifts_applied,
        })

    # Merchant model swap (v0.12) — post-pass that swaps the visual model
    # of merchant Parts without touching their NPCParam/ThinkParam. The
    # merchant continues to function as a merchant; it just looks
    # different. Optional, off by default.
    n_merchants_swapped = 0
    if merchant_model_swap and V3_MERCHANT_MODEL_SWAP_ENABLED:
        merchant_data, n_merchants_swapped = apply_merchant_model_swaps(
            bytes(out), rng,
            spoiler_entries=spoiler_entries,
            map_name=map_name,
            gates=gates)
        out = bytearray(merchant_data)

    # v0.24.101: Model entry compaction post-pass. After all Part swaps
    # (including merchant model swap above), remove Enemy-type Model
    # entries that have zero Part references. Reduces .chrbnd load count
    # at map load and shrinks MSB size. See V3_REMOVE_UNUSED_ENEMY_MODELS
    # for kill switch.
    #
    # v0.25.0-patch3: pass `protect_names` derived from the boss-slot
    # catalog so chrs that the boss-init EMEVD spawns dynamically
    # (SpawnNPC + chr template) survive even when their static Parts
    # were all swapped away. Catalog entries are documented as
    # arena-relevant; ambient Limveld chrs (Perfumer, Wandering Noble)
    # outside the catalog are still compacted normally.
    #
    # Empirical motivation: across all 5 audited spoilers (seeds 42,
    # 939029, 650833, 49804, 628653), m48_40 Morgott reliably had
    # c4353 (Leyndell Knight Prelude) removed because the pi=4 Part
    # was swapped to another chr — but the catalog lists c4353 at
    # pi=4 as "Leyndell Knight (Night Boss Prelude)", suggesting the
    # boss-init flow expects c4353 to remain template-available.
    # Without the protection, seed 628653 N2 stall (Tricephalos rolled
    # m48_40 Morgott as N2; boss never spawned). Documented bug at
    # emevd_patch.py:1469-1474 cites "no boss spawn, no minion wave"
    # which matches a failed-prelude-then-stalled-boss-init signature.
    if V3_REMOVE_UNUSED_ENEMY_MODELS:
        pre_compact_size = len(bytes(out))
        msb_basename = os.path.basename(input_path)
        # v0.25.0-patch3: build protect set from boss-slot catalog entries
        # for this MSB. V3_BOSS_SLOT_CATALOG is flat keyed by (msb, pi);
        # iterate and filter.
        #
        # v0.26.5-patch: skip cp-less entries. The v0.26.x terrain-arena
        # merge (_load_boss_slot_catalog) injects entries from
        # nr_terrain_arena_slots.json that lack a 'cp' key — they're
        # promoted by geometry alone, with no vanilla chr identity to
        # protect. Pre-patch this raised KeyError: 'cp' on the first
        # affected MSB (147 such entries across 30 MSBs in v0.26.x data).
        protect = {entry['cp']
                   for (msb_key, _pi), entry in V3_BOSS_SLOT_CATALOG.items()
                   if msb_key == msb_basename and 'cp' in entry}
        compact_data, removed_models, _model_remap = remove_unused_model_entries(
            bytes(out), model_type_filter=2, protect_names=protect)
        if removed_models or protect:
            if removed_models:
                out = bytearray(compact_data)
            _V3_TRACE_BUFFER.append({
                'event': 'MODEL_COMPACTION',
                'msb': msb_basename,
                'n_removed': len(removed_models),
                'bytes_saved': pre_compact_size - len(compact_data) if removed_models else 0,
                'removed_names': [r['name'] for r in removed_models],
                'protected_names': sorted(protect),  # v0.25.0-patch3
            })

    with open(output_path, 'wb') as f: f.write(bytes(out))
    return (len(swap_plan), n_added, n_skipped_compat, n_clusters)


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
                    caliber_pool_removals=None):
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
                force_include_targets=force_include_targets) as effective_gates:
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
    """Internal implementation — see cmd_shuffle_v3 for kwarg semantics.

    v0.24.21: `gates` parameter — the effective GateState snapshot
    yielded by apply_run_overrides in the public wrapper. When passed,
    threaded into call sites that accept gates= (currently
    apply_merchant_model_swaps; future picker migrations will extend
    this). When None, callees fall back to reading module globals —
    which are still mutated by apply_run_overrides for the duration
    of the run, so behavior is unchanged for un-threaded callees.

    Caller is responsible for save/restore of V3_EXCLUDE_PREFIXES /
    V3_HUB_MAPS / V3_GHOST_EXCLUDE_TARGET_PREFIXES around this call;
    the public cmd_shuffle_v3 wrapper handles that via
    apply_run_overrides.

    v0.23.72-late: dropped the long-vestigial `mode='loose'` parameter
    (placement chain has been universal-pool/post-filter since v0.20.0;
    mode never reached any code that branched on its value). Also no
    longer calls build_compat_lookups (its outputs were unused)."""
    # v0.23.57: capture the input dir as soon as we have it. Other diagnostic
    # fields (input_msb_listing, msb_results, spawn_pool_*) get populated as
    # the run progresses. dcx_batch may have already set 'in_dcx_dir' and
    # 'spawn_pool_*' before calling us — preserve those.
    V3_PIPELINE_METADATA.setdefault('vanilla_dir', input_dir)
    rng = random.Random(seed)
    # v0.27.13: expose the run seed for field-slot tier rolls (a pure
    # function of seed + slot identity — see field_roll_tier_for).
    global _V3_RUN_SEED
    _V3_RUN_SEED = seed
    roster, tags = load_data()
    # v0.26.x: pool/cap overrides MUST be applied here — AFTER the impl's
    # own load_data() — not in the cmd_shuffle_v3-level apply_run_overrides
    # context manager. load_data folds pack-loader caliber/cap additions
    # into the gate sets, which clobbers any subtractive override applied
    # before it ran. See engine/runtime.compose_pool_cap_overrides for the
    # full rationale. Restoration is still the outer apply_run_overrides
    # CM's job (both gate sets are in its _OWNED_MODULE_FIELDS).
    if unique_cap_overrides or caliber_pool_extras or caliber_pool_removals:
        compose_pool_cap_overrides(
            unique_cap_overrides=unique_cap_overrides,
            caliber_pool_extras=caliber_pool_extras,
            caliber_pool_removals=caliber_pool_removals)
    prefix_variants, prefix_count = build_per_prefix_data(roster)

    # v0.23.39: NB target may come via kwargs (GUI) OR module global (CLI).
    # Resolve the effective values once for use in mode_label / spoiler emit.
    _eff_nb_target = (oops_all_nb_target_cp if oops_all_nb_target_cp is not None
                      else OOPS_ALL_NB_TARGET_CP)
    _eff_nb_scope = (oops_all_nb_marker_scope if oops_all_nb_marker_scope is not None
                     else OOPS_ALL_NB_MARKER_SCOPE)

    if terrain_test_targets:
        mode_label = (f"Terrain test (on_mesh→{terrain_test_targets['on_mesh']}, "
                      f"off_mesh→{terrain_test_targets['off_mesh']})")
    elif oops_all_target_cp:
        mode_label = f'Oops! All {oops_all_target_cp}'
    elif _eff_nb_target:
        mode_label = (f'Oops! All NB ({_eff_nb_target}, '
                      f'scope={_eff_nb_scope})')
    else:
        mode_label = 'Standard'
    # v0.19.22: print engine version up front so log scrubs reveal stale
    # installs immediately. If the GUI says v0.19.22 but this line says
    # v0.19.21, there's a stale .pyc / wrong-folder loading issue.
    print(f"Engine: {V3_ENGINE_VERSION}  ({V3_ENGINE_FINGERPRINT})")

    # Reset run-scoped diagnostic state.
    global _V3_TRACE_BUFFER
    _V3_TRACE_BUFFER = []  # v0.19.24: reset buffer (gets dumped into spoiler)
    _V3_PRESERVED_SOURCE_LOG.clear()  # v0.20.18
    _V3_UNACCOUNTED_VANILLA_LOG.clear()  # v0.20.19

    # v0.20.2: data integrity check — log the loaded tier for each FI cp.
    # If a stale tags.json (still has cluster_member tier for these) is
    # loaded, the FI cps would be filtered out by tier-preserve. The
    # cluster_member compat shim in V3_FIELD_STRENGTH_TIERS makes this
    # not-fatal, but we log the loaded values so the user can confirm
    # they're running the v0.20+ tags or the legacy ones.
    integrity = {cp: tags.get(cp, {}).get('tier', '<missing>')
                 for cp in ['c5110', 'c4181', 'c3610', 'c3620', 'c4481',
                            'c4200', 'c4201', 'c4660', 'c4580']}
    _V3_TRACE_BUFFER.append({'event': 'TAGS_INTEGRITY', 'tiers': integrity})
    # v0.20.3: log if any FI cps were defensively removed from exclude sets
    # at module load. If this list is non-empty, the user has a stale .pyc
    # in __pycache__ that was loaded with old buggy excludes.
    _V3_TRACE_BUFFER.append({
        'event': 'EXCLUDE_INTEGRITY',
        'fi_cps_in_excludes_at_load': list(_v3_dropped_from_excludes),
        'pyc_cleaned': bool(_v3_dropped_from_excludes),
    })
    # v0.20.4: snapshot exact contents of all three exclude sets so we can
    # see whether they're mutated between module-load (when EXCLUDE_INTEGRITY
    # records "clean") and pick_target_cp call time. v0.20.3 showed the
    # paradox: empty cleanup list AND FI cps drop at after_excludes anyway.
    # If these snapshots show FI cps in the sets, mutation happened between
    # load and run-start. If they don't, mutation is happening AFTER this
    # snapshot but before pick_target_cp's exclude line.
    _V3_TRACE_BUFFER.append({
        'event': 'EXCLUDE_SNAPSHOT_AT_RUN_START',
        'V3_EXCLUDE_PREFIXES': sorted(V3_EXCLUDE_PREFIXES),
        'V3_EXCLUDE_TARGET_PREFIXES': sorted(V3_EXCLUDE_TARGET_PREFIXES),
        'V3_GHOST_EXCLUDE_TARGET_PREFIXES': sorted(V3_GHOST_EXCLUDE_TARGET_PREFIXES),
        'fi_in_any': {
            cp: (cp in V3_EXCLUDE_PREFIXES
                 or cp in V3_EXCLUDE_TARGET_PREFIXES
                 or cp in V3_GHOST_EXCLUDE_TARGET_PREFIXES)
            for cp in ('c5110', 'c4181', 'c3610', 'c3620')
        },
    })

    print(f"v3 vanilla-aware shuffle  seed={seed}  mode={mode_label}")
    print(f"Per-prefix data: {len(prefix_variants)} c-prefixes with usable variants")


    # v0.23.07: Unique-target reservation pre-pass. Walks all input MSBs,
    # picks one or two quality slots per V3_UNIQUE_TARGET_CAPS entry. Must
    # run AFTER tags/roster load (uses swap compat scoring) but
    # BEFORE per-MSB shuffle loop (so reservations are visible to
    # pick_target_cp).
    #
    # v0.24.22 (Phase 5.5): RunContext flip. cmd_shuffle_v3 used to call
    # _reset_unique_run_state() to clear the module-level
    # _V3_UNIQUE_RESERVATIONS / _V3_UNIQUE_PLACED_COUNTS /
    # _V3_UNIQUE_UNPLACED_LOG dicts at the top of each run. Phase 5
    # introduced RunContext as an OPTIONAL alternative — predicate
    # functions accept run_ctx=None and fall back to module dicts. The
    # flip: construct a fresh RunContext here unless one was passed in
    # explicitly (legacy call paths or tests), and thread it through to
    # _compute_unique_reservations + the per-MSB shuffle loop. Module
    # dicts still get a final back-copy at end-of-run for spoiler-emit
    # observability (see ~line 11385), but are no longer authoritative
    # mid-run. Concurrent shuffles are now race-free as long as each
    # gets its own RunContext.
    if run_ctx is None:
        run_ctx = RunContext.fresh()
    else:
        # Caller passed an explicit RunContext (e.g. a test). Reset its
        # state so this is a clean run, but don't replace the object —
        # the caller is holding a reference.
        run_ctx.reset()
    # Keep module dicts in sync at run-start for downstream code paths
    # that haven't been migrated. The end-of-run back-copy at the
    # spoiler emit reconciles them.
    _V3_UNIQUE_RESERVATIONS.clear()
    _V3_UNIQUE_PLACED_COUNTS.clear()
    _V3_UNIQUE_UNPLACED_LOG.clear()
    if V3_UNIQUE_TARGET_CAPS and not oops_all_target_cp:
        # Skip in oops_all mode — that mode bypasses pool selection
        # entirely, so reservations are meaningless. Same reasoning for
        # diagnostic_test_targets / non_fragile_baseline_cp paths.
        if not (diagnostic_test_targets or non_fragile_baseline_cp):
            _compute_unique_reservations(input_dir, tags, prefix_variants, rng,
                                          run_ctx=run_ctx)

    os.makedirs(output_dir, exist_ok=True)
    total_files = total_swaps = total_added = total_skipped_compat = total_passthrough = 0
    target_count = {}  # cumulative target c-prefix placements across all maps
    total_clusters = 0
    n_parse_fail = 0
    spoiler_entries = []  # accumulated across all maps
    # v0.23.57: build the input MSB listing for diagnostics. We capture this
    # BEFORE the per-MSB loop so even an early-failing run records what was
    # in scope. spawn_pool_in_input answers "did the file we expected to
    # process actually exist in the input dir?" (True/False per pool MSB).
    _input_listing = sorted(f for f in os.listdir(input_dir) if f.endswith('.msb'))
    V3_PIPELINE_METADATA['input_msb_count'] = len(_input_listing)
    V3_PIPELINE_METADATA['input_msb_listing'] = _input_listing
    V3_PIPELINE_METADATA['spawn_pool_in_input'] = {
        b + '.msb': (b + '.msb') in set(_input_listing)
        for b in V3_SPAWN_POOL_MSBS
    }
    V3_PIPELINE_METADATA['msb_results'] = {}
    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith('.msb'): continue
        # v0.19.21: check for cancellation at each map boundary. Latency
        # is one map's processing time (~1-3 seconds typical). Output
        # directory will contain whatever was processed before cancel.
        _check_cancel()
        ip = os.path.join(input_dir, fname)
        op = os.path.join(output_dir, fname)

        # v0.23.68: hub MSBs without pinned slots get full passthrough;
        # hubs WITH pinned slots fall through to shuffle_msb_v3 in
        # pinned-only mode (only listed Parts get randomized, all others
        # stay vanilla — preserves NPC dialogues, quest triggers, etc.).
        _is_hub = fname in V3_HUB_MAPS
        _hub_pinned_mode = _is_hub and _msb_has_pinned_slots(fname)
        if _is_hub and not _hub_pinned_mode:
            shutil.copy(ip, op)
            total_passthrough += 1
            V3_PIPELINE_METADATA['msb_results'][fname] = 'hub_passthrough'
            # v0.23.68: even though we're passing through this hub
            # unchanged, dump its Part inventory if the user has flagged
            # this MSB for diagnostics (V3_DIAGNOSTIC_INVENTORY_MSBS).
            # Lets the user identify boss-tier interior pi indices to
            # add to V3_BOSS_TIER_PINNED_SLOTS without having to flip
            # the hub out of passthrough.
            if fname in V3_DIAGNOSTIC_INVENTORY_MSBS:
                try:
                    with open(ip, 'rb') as _fp:
                        _hub_data = _fp.read()
                    _hub_sections = parse_msb_sections(_hub_data)
                    _hub_models = _hub_sections[0]
                    _hub_midx_to_cp = {}
                    for _gi, _eo in enumerate(_hub_models['entry_offsets']):
                        _info = parse_model_entry(_hub_data, _eo)
                        _hub_midx_to_cp[_gi] = _info.get('name', '')
                    _hub_parts = next(s for s in _hub_sections
                                       if s['name'] == 'PARTS_PARAM_ST')
                    _hub_msb_base = fname[:-4] if fname.endswith('.dcx') else fname
                    _emit_msb_part_inventory_trace(
                        _hub_data, _hub_parts, _hub_midx_to_cp, _hub_msb_base)
                except Exception:
                    pass  # diagnostic best-effort; never block passthrough
            continue

        res = shuffle_msb_v3(ip, op, rng, tags, prefix_variants, prefix_count,
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
                              pinned_only_in_hub=_hub_pinned_mode,
                              gates=gates,
                              run_ctx=run_ctx)
        if res is None:
            shutil.copy(ip, op)
            n_parse_fail += 1
            V3_PIPELINE_METADATA['msb_results'][fname] = 'parse_fail'
        else:
            n_swaps, n_added, n_skipped, n_clust = res
            # v0.25.5: byte-identical passthrough for zero-change MSBs.
            # Bug surfaced in v0.25.4 with Gaping Jaw N1 fail-to-start
            # (seeds 349984, 755964): both m48_90 and m49_17 arenas had
            # n_swaps=0/n_added=0 (preserve_primary via v0.25.1 role
            # catalog) and were running through the full MSB recompile
            # pipeline — parse_msb_sections → rebuild offsets → write
            # bytes(out) — even though `out` was a vanilla copy of `data`.
            # The recompilation output evidently isn't byte-identical to
            # the input file (subtle differences in section padding,
            # offset table emission, or merchant-pass byte-handling), and
            # the boss-init for these arenas reads the MSB at a level
            # that's sensitive to those byte differences. Result: arena
            # loads, but the EnableCharacter() / boss-init chain never
            # fires; player walks into an empty room.
            #
            # The fix: when no actual changes happened (no swaps, no
            # model adds, no cluster moves), overwrite the output with
            # a byte-copy of the input. Guarantees the output file is
            # byte-identical to vanilla NR, matching what the boss-init
            # chain expects. No risk of regressing non-zero-change MSBs:
            # those still go through the recompile pipeline normally
            # (their content is meant to be different from vanilla, so
            # byte-drift from recompilation doesn't matter).
            #
            # n_skipped_compat is NOT checked — that just counts Parts
            # rejected by the preserve gates and doesn't mutate the
            # binary. Only the three change-counts that can mutate `out`
            # are gating: n_swaps (Parts modified), n_added (models
            # appended), n_clust (cluster post-pass moves).
            if n_swaps == 0 and n_added == 0 and n_clust == 0:
                shutil.copy(ip, op)
                _V3_TRACE_BUFFER.append({
                    'event': 'ZERO_CHANGE_PASSTHROUGH',
                    'msb': fname,
                    'reason': 'shuffle_msb_v3 reported no changes — byte-copying input to avoid recompilation drift',
                })
            total_files += 1
            total_swaps += n_swaps
            total_added += n_added
            total_skipped_compat += n_skipped
            total_clusters += n_clust
            # v0.23.57: store result tuple as a tagged dict so JSON
            # consumers can read fields by name.
            V3_PIPELINE_METADATA['msb_results'][fname] = {
                'n_swaps':         n_swaps,
                'n_models_added':  n_added,
                'n_skipped_compat': n_skipped,
                'n_clusters':      n_clust,
                'mode': ('hub_pinned_only' if _hub_pinned_mode else 'shuffled'),
            }

        # Always copy sidecar
        for suffix in SIDECAR_SUFFIXES:
            sc = ip + suffix
            if os.path.exists(sc):
                shutil.copy(sc, op + suffix)
                break

    print(f"\nProcessed {total_files} files, {total_swaps} swaps, {total_added} new model entries")
    print(f"Skipped (no compat targets found): {total_skipped_compat}")
    print(f"Hub passthrough: {total_passthrough}, Parse failures: {n_parse_fail}")

    # v0.23.57: build the spawn-pool diagnostic summary. For every MSB in
    # V3_SPAWN_POOL_MSBS, record:
    #   - was_in_input: did we see this filename in the input dir?
    #   - was_processed: did shuffle_msb_v3 run on it (vs. hub-passthrough/skip)?
    #   - parse_status: ok / parse_fail / not_processed
    #   - n_swaps: 0 if not processed or no swaps, otherwise count
    # This is the high-signal block the user asked us to capture so we can
    # see exactly what happened to each rotation-source MSB.
    _spawn_pool_results = {}
    for pool_base in V3_SPAWN_POOL_MSBS:
        pool_msb = pool_base + '.msb'
        was_in_input = V3_PIPELINE_METADATA['spawn_pool_in_input'].get(pool_msb, False)
        result = V3_PIPELINE_METADATA['msb_results'].get(pool_msb)
        if result is None:
            status = 'not_processed' if was_in_input else 'not_in_input'
            n_swaps = 0
        elif result == 'parse_fail':
            status = 'parse_fail'
            n_swaps = 0
        elif result == 'hub_passthrough':
            status = 'hub_passthrough'
            n_swaps = 0
        elif isinstance(result, dict):
            status = 'ok'
            n_swaps = result.get('n_swaps', 0)
        else:
            status = f'unknown_result:{type(result).__name__}'
            n_swaps = 0
        _spawn_pool_results[pool_msb] = {
            'was_in_input':   was_in_input,
            'status':         status,
            'n_swaps':        n_swaps,
            'description':    V3_SPAWN_POOL_MSBS[pool_base],
        }
    V3_PIPELINE_METADATA['spawn_pool_results'] = _spawn_pool_results

    # Write spoiler logs
    if spoiler_entries:
        # v0.24.22 (Phase 5.5): back-copy run_ctx state into the module
        # dicts so write_spoiler_logs's existing reads (line ~11423-11427)
        # see this run's results. The module dicts are no longer
        # authoritative during the run — run_ctx is — but write_spoiler_logs
        # hasn't been migrated to take a run_ctx parameter directly, so
        # this is the seam. Future: thread run_ctx into write_spoiler_logs
        # and drop the back-copy.
        _V3_UNIQUE_RESERVATIONS.clear()
        _V3_UNIQUE_RESERVATIONS.update(run_ctx.unique_reservations)
        _V3_UNIQUE_PLACED_COUNTS.clear()
        _V3_UNIQUE_PLACED_COUNTS.update(run_ctx.unique_placed_counts)
        _V3_UNIQUE_UNPLACED_LOG.clear()
        _V3_UNIQUE_UNPLACED_LOG.extend(run_ctx.unique_unplaced_log)
        write_spoiler_logs(output_dir, spoiler_entries, seed,
                           multiplayer_safe=multiplayer_safe,
                           sote_mode=V3_SOTE_MODE,
                           disable_resilient_filter=disable_resilient_filter,
                           non_fragile_baseline_cp=non_fragile_baseline_cp,
                           diagnostic_test_targets=diagnostic_test_targets,
                           oops_all_nb_target_cp=_eff_nb_target,
                           oops_all_nb_marker_scope=_eff_nb_scope,
                           oops_all_nb_pinned_slot=oops_all_nb_pinned_slot)
        print(f"Spoiler logs: {os.path.join(output_dir, '_spoilers.json')} "
              f"({len(spoiler_entries)} entries)")
        print(f"             {os.path.join(output_dir, '_spoilers.md')}")

        # v0.27.34: run the seed CTD-risk checker on every generated seed.
        # Static audit of the finished placement set against known crash
        # signatures. Findings are written to _ctd_risk.json and summarized
        # to the console. Non-fatal: a flagged seed still gets written (the
        # user decides whether to reroll), but the risk is surfaced now.
        _ctd_findings = run_seed_ctd_checks(spoiler_entries, tags)
        _ctd_path = os.path.join(output_dir, '_ctd_risk.json')
        try:
            with open(_ctd_path, 'w', encoding='utf-8') as _cf:
                json.dump({'seed': seed,
                           'engine': V3_ENGINE_FINGERPRINT,
                           'finding_count': len(_ctd_findings),
                           'findings': _ctd_findings}, _cf, indent=2)
        except OSError:
            pass
        if _ctd_findings:
            _n_ctd = sum(1 for f in _ctd_findings if f.get('severity') == 'ctd')
            print(f"*** CTD RISK CHECK: {len(_ctd_findings)} finding(s) "
                  f"({_n_ctd} ctd-severity) — see {_ctd_path} ***")
            for f in _ctd_findings:
                print(f"      [{f.get('severity')}] {f.get('map')} "
                      f"pi={f.get('part_index')} eid={f.get('entity_id')}: "
                      f"{f.get('detail')}")
        else:
            print(f"CTD risk check: clean ({os.path.basename(_ctd_path)})")


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
    """Write _spoilers.json (full) + _spoilers.md (organized summary).

    v0.23.72-late: dropped vestigial `mode` parameter (was always 'loose'
    since v0.20.0's universal-pool refactor).

    multiplayer_safe: bool — surfaced into the spoiler so users can
    confirm what mode the run used. Defaults to False so any caller
    who hasn't been updated still works (older callers from CLI tools
    or scripts won't pass the flag, and a False default is fine for
    those — the spoiler will say "OFF" which matches the engine's
    default behavior when no kwarg is set).

    disable_resilient_filter: bool — v0.20.35 diagnostic mode marker.
    v0.20.37: when True, fragile slots use UNTESTED-only filter
    (pool - RESILIENT - SENSITIVE). Surfaced in spoiler so freeze
    reports tied to a diagnostic run are unambiguously identifiable.

    non_fragile_baseline_cp: str | None — v0.20.38 diagnostic-mode
    companion. When set (e.g. 'c4373' Foot Soldier), every non-
    fragile slot is forced to that c-prefix instead of being randomized.
    Combined with disable_resilient_filter, this means the world is
    visually uniform at safe slots, so any non-baseline enemy the
    user sees in-game is by definition a fragile-slot test. Surfaced
    so the user can confirm the run was a diagnostic-instrumented one.
    """
    # v0.20.2 fix: tags is needed by the markdown tracker section but
    # not in this function's scope. Load it here.
    try:
        with open(_data_path('nr_enemy_tags.json'), 'r', encoding='utf-8') as f:
            tags = json.load(f)
    except Exception:
        tags = {}
    # JSON: machine-readable, full detail
    json_path = os.path.join(output_dir, '_spoilers.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            # v0.19.22: explicit engine version so spoilers self-identify the
            # build that produced them. Add a hash of a fix-marker string so
            # bad cache loads (stale .pyc) can be detected from the header.
            'engine_version': V3_ENGINE_VERSION,
            'engine_fingerprint': V3_ENGINE_FINGERPRINT,
            # v0.19.24: dump the trace buffer (TAGS_INTEGRITY, EXCLUDE_INTEGRITY,
            # FI-drop events, etc.) so we can see what happened without
            # needing the GUI log.
            'diagnostic_trace': list(_V3_TRACE_BUFFER),
            'seed': seed,
            # v0.23.72-late: 'mode' field dropped — the parameter was removed
            # from write_spoiler_logs's signature in the same revision (was
            # always 'loose' since v0.20.0's universal-pool refactor). The
            # body reference here was missed and produced NameError at
            # spoiler-write time. Confirmed no Python consumer reads this
            # spoiler key; historical spoilers showed mode='loose' uniformly,
            # so the field carried zero signal.
            # v0.20.27: explicit multiplayer_safe kwarg from cmd_shuffle_v3.
            # Was structurally inferred in v0.20.26 because the GUI mutated
            # V3_GHOST_EXCLUDE_TARGET_PREFIXES directly; that mutation now
            # happens engine-side under the kwarg, so we just record the
            # kwarg value.
            'multiplayer_safe': multiplayer_safe,
            # v0.23.31: oops-all-NB target — emitted so playtests are tagged.
            'oops_all_nb_target_cp': oops_all_nb_target_cp,
            'oops_all_nb_use_strict_markers': (oops_all_nb_marker_scope == 'strict'),
            'oops_all_nb_marker_scope': oops_all_nb_marker_scope,
            # v0.24.25: pinned-slot mode — when set, only one specific
            # (msb, pi) gets oops_all_nb_target_cp; all other slots roll
            # normally. Stored as [msb, pi] in JSON (tuples → lists).
            'oops_all_nb_pinned_slot': (list(oops_all_nb_pinned_slot)
                                         if oops_all_nb_pinned_slot is not None
                                         else None),
            # v0.23.54: boss-slot catalog summary — number of catalogued boss
            # slots in this build. Helps verify the catalog is loaded (a 0
            # here means data/nr_boss_slots.json wasn't found or failed to
            # parse, in which case OOPS_ALL_NB falls back to marker
            # heuristics for everything not in V3_BOSS_TIER_PINNED_SLOTS).
            'boss_slot_catalog_total': len(V3_BOSS_SLOT_CATALOG),
            'boss_slot_catalog_meta':  V3_BOSS_SLOT_CATALOG_META,
            # v0.23.56: spawn-pool MSB inventory total. Independent of the
            # main catalog — these are the rotation-source MSBs the rando
            # auto-includes when spawn_pool_source_dir is set in the GUI.
            # See V3_SPAWN_POOL_MSBS docstring for the list.
            'spawn_pool_msbs_total': len(V3_SPAWN_POOL_MSBS),
            # v0.23.57: full pipeline-metadata dump. dcx_batch + the engine
            # cooperatively populate V3_PIPELINE_METADATA as the run
            # progresses. Includes input/output paths, auto-include results,
            # input MSB listing, per-MSB result tuples, and per-spawn-pool
            # status. Use this to debug runs where MSBs you expected to be
            # processed didn't end up in the spoiler.
            'pipeline_metadata': dict(V3_PIPELINE_METADATA),
            # v0.20.35: diagnostic flag — RESILIENT whitelist disabled at
            # fragile slots when True. Used to expand SENSITIVE based on
            # observed freezes. Identifies a diagnostic run vs production.
            'disable_resilient_filter': disable_resilient_filter,
            # v0.20.38: diagnostic-mode companion. When set, non-fragile
            # slots were forced to this single c-prefix (e.g. 'c4373' Foot
            # Soldier) for visual-baseline diagnostic runs. Anything visible
            # in-game that isn't this c-prefix is, by construction, a
            # fragile-slot test placement.
            'non_fragile_baseline_cp': non_fragile_baseline_cp,
            # v0.20.42: diagnostic batch — when set, fragile slots were
            # restricted to ONLY these c-prefixes. Critical for CTD
            # attribution since the spoiler tells you which c-prefixes
            # could possibly be the cause.
            'diagnostic_test_targets': (sorted(diagnostic_test_targets)
                                         if diagnostic_test_targets else None),
            # v0.23.07: unique-target reservation state. Three sub-keys:
            # caps: the active cap dict at run time (so a regenerated
            #   spoiler from the same seed but different caps is
            #   identifiable). placed_counts: actual placements per
            #   capped cp at end of run. unplaced: list of cps that
            #   couldn't get a reservation, with the reason (so the user
            #   can decide whether to relax criteria for those cps).
            'unique_caps': dict(V3_UNIQUE_TARGET_CAPS),
            # v0.27.13: _V3_UNIQUE_PLACED_COUNTS now contains both string
            # c-prefix keys AND (c_prefix, group_name) tuple keys from the
            # variant-group accounting. JSON keys must be strings, so a
            # tuple key is rendered "c_prefix/group_name" (the same
            # display form used in the reservation-pass log lines). String
            # c-prefix keys pass through unchanged.
            'unique_placed_counts': {
                (f'{k[0]}/{k[1]}' if isinstance(k, tuple) else k): v
                for k, v in _V3_UNIQUE_PLACED_COUNTS.items()
            },
            'unique_unplaced': list(_V3_UNIQUE_UNPLACED_LOG),
            # v0.27.13: a reservation VALUE is either a cp string
            # (c-prefix floor) or a (cp, group) tuple (variant-group
            # floor). Emit cp always, plus group when the reservation
            # was group-scoped, so the spoiler distinguishes the two.
            'unique_reservations': [
                {'msb': k[0], 'pi': k[1],
                 'cp': (v[0] if isinstance(v, tuple) else v),
                 **({'group': v[1]} if isinstance(v, tuple) else {})}
                for k, v in sorted(_V3_UNIQUE_RESERVATIONS.items())
            ],
            'entry_count': len(entries),
            'entries': entries,
        }, f, indent=2, ensure_ascii=False)

    # Markdown: organized summary
    md_path = os.path.join(output_dir, '_spoilers.md')
    boss_entries = [e for e in entries if e['is_boss']]
    cluster_entries = [e for e in entries if e['cluster_id'] is not None and not e['is_boss']]
    field_entries = [e for e in entries if e['cluster_id'] is None and not e['is_boss']]

    # Group by map for easier scanning
    from collections import defaultdict
    def group_by_map(es):
        g = defaultdict(list)
        for e in es: g[e['map']].append(e)
        return dict(sorted(g.items()))

    def fmt(side):
        n = side['name']; cp = side['c_prefix']
        return n if n == cp else f"{n} ({cp})"

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# Spoiler log — seed {seed}\n\n")
        f.write(f"Total swaps: **{len(entries)}** "
                f"(bosses: {len(boss_entries)}, "
                f"clustered: {len(cluster_entries)}, "
                f"field: {len(field_entries)})\n\n")
        # v0.20.27: surface multiplayer-safe state directly from the
        # kwarg passed to cmd_shuffle_v3. Was structurally inferred in
        # v0.20.26 (heritage subset of ghost-excludes) but now that
        # multiplayer-safe is applied engine-side, the kwarg is the
        # source of truth.
        f.write(f"Multiplayer-safe: **{'ON' if multiplayer_safe else 'OFF'}**"
                f"{'' if multiplayer_safe else ' — heritage chrs allowed; coop partners need the heritage pack'}"
                f"\n\n")
        # v0.27.24: surface all-SOTE mode state so a run's spoiler makes it
        # obvious whether the SOTE restriction was active. The seed-505991
        # report ambiguity (was SOTE mode on or not?) is resolved by this
        # line existing. Sourced from V3_SOTE_MODE at write time (still set
        # — the restore happens in cmd_shuffle_v3's finally, after the impl
        # that calls this returns).
        if sote_mode:
            f.write("All-SOTE mode: **ON** — targets restricted to the "
                    "Shadow-of-the-Erdtree roster; unique-target caps/floors "
                    "bypassed. Requires MMV + heritage SOTE assets staged.\n\n")
        # v0.23.07: unique-target cap summary. Renders cleanly even if no
        # capped cps got reservations — the unplaced list tells the user
        # which caps to relax. Order: cap=1 first, alphabetical within.
        if V3_UNIQUE_TARGET_CAPS:
            f.write("## Unique-target caps\n\n")
            f.write("Capped c-prefixes are limited to N placements per run "
                    "(named bosses cap=1, unnamed archetypes cap=2). The "
                    "reservation pre-pass picks quality slots up front.\n\n")
            placed = dict(_V3_UNIQUE_PLACED_COUNTS)
            unplaced_cps = {u['cp'] for u in _V3_UNIQUE_UNPLACED_LOG}
            sorted_caps = sorted(V3_UNIQUE_TARGET_CAPS.items(),
                                  key=lambda kv: (kv[1], kv[0]))
            for cp, cap in sorted_caps:
                cnt = placed.get(cp, 0)
                if cp in unplaced_cps:
                    badge = '⊘ unplaced'
                elif cnt == 0:
                    badge = '○ unreserved'
                elif cnt == cap:
                    badge = '✓ filled'
                else:
                    badge = f'~ partial ({cnt}/{cap})'
                tag_name = tags.get(cp, {}).get('name', cp)
                f.write(f"- **{cp}** {tag_name} (cap={cap}): "
                        f"placed {cnt}/{cap} — {badge}\n")
            if _V3_UNIQUE_UNPLACED_LOG:
                f.write("\n### Unplaced (no qualifying slot)\n\n")
                f.write("These c-prefixes couldn't get a reservation this "
                        "run. To enable them, either relax the scoring "
                        "criteria in `_score_slot_for_unique` or add slot "
                        "candidates via tag adjustments.\n\n")
                for u in _V3_UNIQUE_UNPLACED_LOG:
                    f.write(f"- **{u['cp']}** (cap={u['cap']}): "
                            f"{u['reason']}\n")
            f.write("\n")
        # v0.20.35: surface diagnostic-mode state. Loud marker because
        # diagnostic spoilers should be obvious — they're for capturing
        # freeze evidence, not regular play.
        if disable_resilient_filter:
            f.write("> ⚠ **DIAGNOSTIC MODE** — `disable_resilient_filter=True`. "
                    "Fragile slots used UNTESTED-only filter (pool - RESILIENT - "
                    "SENSITIVE). Every fragile-slot placement is a candidate "
                    "test. Report c-prefixes that freeze so they can be added "
                    "to `V3_FRAGILE_SENSITIVE_TARGETS`.\n\n")
        if non_fragile_baseline_cp:
            f.write(f"> ⚠ **DIAGNOSTIC BASELINE** — `non_fragile_baseline_cp="
                    f"{non_fragile_baseline_cp}`. Every non-fragile slot was "
                    f"forced to this single c-prefix. **Anything you see in-game "
                    f"that is NOT `{non_fragile_baseline_cp}` is a fragile-slot "
                    f"test placement** — note its c-prefix and the freeze.\n\n")
        if diagnostic_test_targets:
            cps = sorted(diagnostic_test_targets)
            f.write(f"> ⚠ **DIAGNOSTIC BATCH** — `diagnostic_test_targets` ({len(cps)} c-prefixes). "
                    f"Fragile slots restricted to: `{', '.join(cps)}`. "
                    f"**Any CTD this run is attributable to one of these {len(cps)} "
                    f"c-prefixes — note which slot/area triggered it and we can "
                    f"narrow further by binary-searching the batch.**\n\n")
        f.write(f"To find a specific encounter: search this file or "
                f"`_spoilers.json` for the c-prefix or name of what you fought.\n\n")

        # v0.20.1: Tracker section — for c-prefixes the user wants to keep
        # an eye on, list every slot where they appeared as source (vanilla
        # was → now is) and as target (vanilla was → now this enemy).
        # Set V3_TRACKED_C_PREFIXES to extend.
        tracked = sorted(V3_TRACKED_C_PREFIXES)
        if tracked:
            f.write("## Tracked enemies\n\n")
            for cp in tracked:
                name = tags.get(cp, {}).get('name', cp)
                tier = tags.get(cp, {}).get('tier', '?')
                src_es = [e for e in entries if e['original']['c_prefix'] == cp]
                tgt_es = [e for e in entries if e['new']['c_prefix'] == cp]
                f.write(f"### {name} (`{cp}`, {tier})\n\n")
                f.write(f"Source slots (where vanilla {name} was) — "
                        f"{len(src_es)} placements:\n\n")
                if src_es:
                    f.write("| map | pi | original variant | → | new |\n")
                    f.write("|---|---|---|---|---|\n")
                    for e in src_es:
                        f.write(f"| {e['map']} | {e['part_index']} "
                                f"| {fmt(e['original'])} | → "
                                f"| **{fmt(e['new'])}** |\n")
                    f.write("\n")
                f.write(f"Target placements (where {name} now appears) — "
                        f"{len(tgt_es)} placements:\n\n")
                if tgt_es:
                    f.write("| map | pi | replaced | → | new variant |\n")
                    f.write("|---|---|---|---|---|\n")
                    for e in tgt_es:
                        f.write(f"| {e['map']} | {e['part_index']} "
                                f"| {fmt(e['original'])} | → "
                                f"| **{fmt(e['new'])}** |\n")
                    f.write("\n")
                if not src_es and not tgt_es:
                    f.write("*(no occurrences this run)*\n\n")

                # v0.20.18: preserved-source subsection — slots whose vanilla
                # cp was source-excluded (so they stayed vanilla and won't
                # appear in src_es above). Useful for tracking c3610/c3620
                # Oracle Envoys etc. — shows where they're still standing
                # in the user's seed.
                pres_es = [p for p in _V3_PRESERVED_SOURCE_LOG
                           if p['c_prefix'] == cp]
                if pres_es:
                    f.write(f"Source slots (preserved as vanilla — "
                            f"source-excluded) — {len(pres_es)} placements:\n\n")
                    f.write("| map | pi | variant | position |\n")
                    f.write("|---|---|---|---|\n")
                    for p in pres_es:
                        pos = p['position']
                        pos_str = f"({pos[0]}, {pos[1]}, {pos[2]})" if pos else "—"
                        # The variant name field can be empty for synthetic
                        # variants — fall back to just the c-prefix for
                        # readability.
                        variant_str = p['name'] or p['c_prefix']
                        f.write(f"| {p['map']} | {p['part_index']} "
                                f"| {variant_str} | {pos_str} |\n")
                    f.write("\n")

        # v0.20.19: unaccounted-vanilla section. Empty on a healthy run.
        # Non-empty entries are bug candidates: slots that fell through
        # the swap loop without a documented reason. Grouped by reason
        # so each leak class is visible at a glance. See
        # _V3_UNACCOUNTED_VANILLA_LOG docstring for what each reason means.
        if _V3_UNACCOUNTED_VANILLA_LOG:
            f.write("## Unaccounted vanilla slots\n\n")
            f.write(f"*{len(_V3_UNACCOUNTED_VANILLA_LOG)} slot(s) fell through "
                    f"the swap loop without producing a swap entry. The "
                    f"`script_spawn_target_only_at_msb` reason is expected "
                    f"architecture (heritage script-only c-prefixes at fixed "
                    f"arena slots). Other reasons indicate probable bugs.*\n\n")
            from collections import defaultdict as _dd
            by_reason = _dd(list)
            for u in _V3_UNACCOUNTED_VANILLA_LOG:
                by_reason[u['reason']].append(u)
            for reason in sorted(by_reason):
                rows = by_reason[reason]
                f.write(f"### {reason} ({len(rows)})\n\n")
                f.write("| map | pi | c_prefix | variant | npc | eid | position |\n")
                f.write("|---|---|---|---|---|---|---|\n")
                for u in rows:
                    pos = u['position']
                    pos_str = f"({pos[0]}, {pos[1]}, {pos[2]})" if pos else "—"
                    eid_str = (str(u['entity_id']) if u['entity_id'] is not None
                               else "—")
                    name = u['name'] or u['c_prefix']
                    f.write(f"| {u['map']} | {u['part_index']} | {u['c_prefix']} "
                            f"| {name} | {u['npc_param_id']} | {eid_str} | {pos_str} |\n")
                f.write("\n")
        else:
            # Visible "all clear" header so the absence is informative
            # (otherwise an unaccounted bug class that gets routed to a
            # different log might masquerade as a clean run).
            f.write("## Unaccounted vanilla slots\n\n")
            f.write("*No unaccounted slots — every Part either swapped or "
                    "had a documented reason to stay vanilla.*\n\n")

        # Boss-tier first — most interesting
        if boss_entries:
            f.write("## Boss-tier swaps\n\n")
            for map_name, es in group_by_map(boss_entries).items():
                f.write(f"### {map_name}\n\n")
                f.write("| entity_id | original | → | new | position |\n")
                f.write("|---|---|---|---|---|\n")
                for e in sorted(es, key=lambda x: x['entity_id'] or -1):
                    p = e['position']
                    pos_str = f"({p[0]}, {p[1]}, {p[2]})" if p else "—"
                    f.write(f"| `{e['entity_id']}` "
                            f"| {fmt(e['original'])} "
                            f"| → "
                            f"| **{fmt(e['new'])}** "
                            f"| {pos_str} |\n")
                f.write("\n")

        # Clustered swaps — multi-Part encounters
        if cluster_entries:
            f.write("## Clustered swaps (multi-part encounters)\n\n")
            f.write("Members of the same cluster share an encounter. Look for matching `cluster_id` in JSON.\n\n")
            for map_name, es in group_by_map(cluster_entries).items():
                f.write(f"### {map_name}\n\n")
                # Group by cluster within map
                by_cluster = defaultdict(list)
                for e in es: by_cluster[e['cluster_id']].append(e)
                for cid, members in sorted(by_cluster.items()):
                    f.write(f"**Cluster {cid}** ({len(members)} members):\n")
                    for m in members:
                        f.write(f"- entity `{m['entity_id']}`: "
                                f"{fmt(m['original'])} → **{fmt(m['new'])}**\n")
                    f.write("\n")

        # Field swaps — collapsed table per map
        if field_entries:
            f.write("## Field swaps\n\n")
            for map_name, es in group_by_map(field_entries).items():
                f.write(f"### {map_name} ({len(es)} swaps)\n\n")
                f.write("<details><summary>Show swaps</summary>\n\n")
                f.write("| entity_id | original | → | new |\n")
                f.write("|---|---|---|---|\n")
                for e in sorted(es, key=lambda x: x['entity_id'] or -1):
                    f.write(f"| `{e['entity_id']}` "
                            f"| {fmt(e['original'])} "
                            f"| → "
                            f"| {fmt(e['new'])} |\n")
                f.write("\n</details>\n\n")

    # v0.24.19: Persistent spoiler archive. The output_dir spoiler is volatile
    # — it gets overwritten on the next run, so users who re-shuffle before
    # grabbing the file lose their diagnostic data. Solution: also drop a
    # timestamped copy into <project>/spoilers/ as a permanent searchable log.
    #
    # Naming: YYYYMMDD_HHMMSS_seed<seed>_<fingerprint>.{json,md}
    # — sortable by time (newest at bottom), seed-searchable, engine-version
    # tagged so we can quickly tell which build produced a given spoiler.
    #
    # Failure is non-fatal: archive errors print a warning and the run still
    # succeeds. The output_dir spoiler (what the GUI surfaces and what the
    # user normally looks at) is the authoritative copy; the archive is
    # belt-and-suspenders.
    #
    # Pruning is intentionally not done here. The archive grows unbounded
    # until the user manually cleans it up — same model as a build log.
    # Rough storage footprint: ~150-300 KB per run (mostly the JSON), so
    # 1000 runs ≈ 150-300 MB. If that becomes a problem, add a retention
    # cap (keep newest N) in a future revision.
    try:
        import datetime, shutil
        _project_dir = os.path.dirname(os.path.abspath(__file__))
        _archive_dir = os.path.join(_project_dir, 'spoilers')
        os.makedirs(_archive_dir, exist_ok=True)
        _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        _stem = f"{_ts}_seed{seed}_{V3_ENGINE_FINGERPRINT}"
        shutil.copy2(json_path, os.path.join(_archive_dir, f"{_stem}.json"))
        shutil.copy2(md_path,   os.path.join(_archive_dir, f"{_stem}.md"))
        print(f"[v0.24.19] Spoiler archived: spoilers/{_stem}.json")
    except Exception as _archive_err:
        # Don't let archive failure break the run; just warn.
        print(f"[v0.24.19] WARNING: spoiler archive failed: {_archive_err}")


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