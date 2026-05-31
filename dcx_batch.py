#!/usr/bin/env python3
"""
dcx_batch.py — Batch DCX compress/decompress for full pipeline integration.

Replaces the Yabber/Witchy steps in the rando workflow:
    Before: Game .msb.dcx → Yabber → .msb + .xml → rando → Yabber → .msb.dcx
    After:  Game .msb.dcx → dcx_batch decompress → .msb → rando → dcx_batch compress → .msb.dcx

Examples:
    # Decompress a whole mapstudio folder
    python dcx_batch.py decompress "C:\\path\\to\\Game\\map\\mapstudio" ./vanilla_msbs

    # Compress a folder of modded MSBs back to DCX
    python dcx_batch.py compress ./shuffled_msbs ./out_dcx

    # End-to-end: decompress, run rando, recompress (single command)
    python dcx_batch.py rando "C:\\...\\mapstudio" ./out_dcx --seed 42
"""
import argparse, os, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dcx import DCX, _Oodle

# v0.23.75: rewired_msbs/ holds MSB binaries with rewired Generator
# spawnPartIndices (see rewired_msbs/REWIRES.md). They override the
# decompressed vanilla MSBs of the same name during rando_pipeline before
# the shuffle step. The rewire pass is one-time / static — these files
# ship in the repo alongside the toolchain, no per-run generation.
REWIRES_DIR = os.path.join(HERE, 'rewired_msbs')


# =============================================================================
# DIAGNOSTIC OVERRIDES — set to a c-prefix to force visual-baseline behavior.
# Defaults are None (normal randomization). Edit these for a diagnostic run,
# then revert to None for normal play. Both can be active simultaneously.
#
# WALK_ROUTE_FORCE_CP: every walk_route procedural spawn becomes this c-prefix
#   regardless of seed. Step 2a bypasses its tier-aware picker entirely.
#   Example: 'c4180' -> all walk_route patrols spawn Spirit Jellyfish.
#
# PLACED_PART_FORCE_CP: every placed Part (fragile OR non-fragile) becomes
#   this c-prefix. Routes through oops_all_target_cp which short-circuits
#   the fragile filter, compat checks, tier-preserve — every swap slot gets
#   this c-prefix. Variant within the c-prefix is rolled per-slot, so e.g.
#   different Foot Soldier variants (with/without shield, etc.) will appear.
#   Example: 'c4373' -> every placed slot is some Leyndell Foot Soldier variant.
#
# Combined effect: the world is visually uniform (Foot Soldiers + Jellyfish).
# Anything visible in-game that ISN'T one of those two is by construction
# either (a) something neither system covers — rewired generator clones,
# sentinels, type=15 squads tied to PIs that pick_variant_for_tier rejected,
# or (b) c-prefix-without-valid-variant edge cases (visible in console as
# "n_skipped_compat" increments).
# =============================================================================
WALK_ROUTE_FORCE_CP = None

# v0.24.93-patch14: walk_route_rewrite disabled by default. The Step 2a/3
# pass rewrites c-prefixes in walk_route_cXXXX event names across 81
# MSBs per seed. Per Alaric direction: was never demonstrably effective
# and kept only because of "no obvious downsides." Suspected contributor
# to Day-2 explore-CTD class (walk_route renames may produce event-name
# byte strings pointing to chrs not preloaded for the tile).
#
# Set True to re-enable. No other changes needed — the Step 2a/3 block
# guards on this flag and falls through to Step 3/4 cleanly when False.
WALK_ROUTE_REWRITE_ENABLED = False  # v0.24.93-patch14: see header
PLACED_PART_FORCE_CP = None        # e.g., 'c4373' for foot-soldier baseline


# =============================================================================
# SLOT REPOSITIONING — apply slot_repositions.json to vanilla MSBs before
# the shuffle runs. Each entry moves a Part's position field (offset 0x400)
# from an off-navmesh location to the center of the nearest tight navmesh
# leaf, making the slot walkable so randomized enemies can path.
#
# SLOT_REPOSITIONS_PATH: filesystem path to the slot_repositions.json built
#   by dev/build_slot_repositions.py. None disables the pass entirely. The
#   default checks for data/slot_repositions.json next to dcx_batch.py.
#
# SLOT_REPOSITIONS_ONLY_MAPS: optional set of MSB filenames to limit the
#   pass to. None means apply to every map present in the JSON. Use this
#   to scope empirical playtests to a known-easy-to-visit region (e.g.,
#   the castle tiles at (43,37) / (44,37)) before opening it up corpus-wide.
#
# SLOT_REPOSITIONS_USE_FLOOR: pick AABB floor-Y (True) vs center-Y (False)
#   as the relocated Y coordinate. Center is fine for most leaves; floor
#   is safer for slanted polys where center-Y can float above the surface.
# =============================================================================
SLOT_REPOSITIONS_PATH = os.path.join(HERE, 'data', 'slot_repositions.json')
SLOT_REPOSITIONS_ONLY_MAPS = None  # e.g., {'m60_43_37_00.msb', ...} or None
SLOT_REPOSITIONS_USE_FLOOR = False


# v0.23.71: Parallel DCX worker count.
#
# Oodle compression releases the GIL during the C call (it's a ctypes
# CDLL invocation operating on caller-owned buffers — no Python state
# touched mid-call), so a ThreadPoolExecutor gives near-linear speedup
# up to the physical core count. Default cap is 8 to avoid thrashing
# on very-many-core machines (Oodle's per-call working set is small
# but the OS scheduler overhead at >8 concurrent compressions started
# costing more than it saved on test runs). Override via the
# DCX_BATCH_WORKERS env var if you want to tune for your hardware.
#
# Setting DCX_BATCH_WORKERS=1 forces serial execution (useful for
# debugging — failures print in a predictable order, no inter-thread
# interleaving in error messages).
def _worker_count():
    env = os.environ.get('DCX_BATCH_WORKERS')
    if env:
        try:
            n = int(env)
            return max(1, n)
        except ValueError:
            pass
    cpu = os.cpu_count() or 4
    return min(8, cpu)


def decompress_dir(in_dir, out_dir, oodle=None,
                   passthrough_dcx_dest=None, passthrough_set=None):
    """Decompress every .msb.dcx in in_dir to .msb in out_dir.

    v0.23.07: optional skip-decompress fast path. If passthrough_set is a
    non-empty set of filenames (.msb.dcx basenames) and passthrough_dcx_dest
    is given, those files get copied straight from in_dir to
    passthrough_dcx_dest WITHOUT decompression. Used by rando_pipeline to
    short-circuit HUB_MAPS — they don't get shuffled, so there's no point
    decompressing them and recompressing identically. The caller is
    responsible for not adding decompressed copies of these files into
    out_dir (they aren't there).

    For files NOT in passthrough_set, normal decompress behavior — the
    decompressed .msb lands in out_dir.

    v0.23.71: parallelized via ThreadPoolExecutor. See _worker_count()
    for how the worker count is chosen. Determinism is preserved: the
    Oodle output bytes are a pure function of input bytes, and the
    final summary is order-independent.
    """
    os.makedirs(out_dir, exist_ok=True)
    if oodle is None: oodle = _Oodle.get()
    files = sorted(f for f in os.listdir(in_dir) if f.endswith('.msb.dcx'))
    if passthrough_set and passthrough_dcx_dest:
        os.makedirs(passthrough_dcx_dest, exist_ok=True)
    n_workers = _worker_count()
    print(f"Decompressing {len(files)} .msb.dcx files (workers={n_workers})...")
    t0 = time.time()
    import shutil as _shutil

    # Per-file unit of work, returns ('ok'|'pass'|'fail', filename, error_msg_or_None).
    # Defined as a closure so it captures oodle / dirs without per-task arg-passing.
    def _decompress_one(f):
        # v0.19.21: cancel check at each file boundary. Threading.Event
        # is already thread-safe; this just observes the flag.
        try:
            import oops_v3
            oops_v3._check_cancel()
        except ImportError:
            pass  # oops_v3 not available, skip cancel support
        in_path = os.path.join(in_dir, f)
        # v0.23.07: passthrough fast path
        if passthrough_set and passthrough_dcx_dest and f in passthrough_set:
            try:
                _shutil.copy(in_path, os.path.join(passthrough_dcx_dest, f))
                return ('pass', f, None)
            except Exception as e:
                # Fall through to normal decompress on copy failure
                print(f"  passthrough copy failed for {f}: {e} (falling back to decompress)")
        out_path = os.path.join(out_dir, f[:-4])  # strip .dcx
        try:
            raw = DCX.decompress_file(in_path, oodle)
            with open(out_path, 'wb') as fp: fp.write(raw)
            return ('ok', f, None)
        except Exception as e:
            return ('fail', f, str(e))

    n_ok = n_fail = n_passthrough = 0
    if n_workers == 1:
        # Serial path — preserves exact pre-v0.23.71 behavior for
        # debugging. Iteration order matches the sorted file list.
        for f in files:
            status, fname, err = _decompress_one(f)
            if status == 'ok': n_ok += 1
            elif status == 'pass': n_passthrough += 1
            else:
                print(f"  FAIL {fname}: {err}")
                n_fail += 1
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # CancelledError needs to escape the pool intact. We catch other
        # exceptions per-file inside _decompress_one; a CancelledError
        # raised by _check_cancel propagates as the future's exception.
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_decompress_one, f): f for f in files}
            try:
                for fut in as_completed(futures):
                    status, fname, err = fut.result()
                    if status == 'ok': n_ok += 1
                    elif status == 'pass': n_passthrough += 1
                    else:
                        print(f"  FAIL {fname}: {err}")
                        n_fail += 1
            except Exception:
                # If a CancelledError bubbles up from any worker, drain
                # outstanding futures (don't leak threads) and re-raise.
                for fut in futures:
                    fut.cancel()
                raise

    dt = time.time() - t0
    if n_passthrough:
        print(f"Done: {n_ok} OK, {n_passthrough} passthrough (no decompress), "
              f"{n_fail} failed, {dt:.1f}s")
    else:
        print(f"Done: {n_ok} OK, {n_fail} failed, {dt:.1f}s")
    return n_ok, n_fail


def compress_dir(in_dir, out_dir, oodle=None,
                 vanilla_dir=None, original_dcx_dir=None,
                 skip_identity_files=None):
    """Compress every .msb in in_dir to .msb.dcx in out_dir.

    v0.23.07: optional identity-skip fast path. When both vanilla_dir and
    original_dcx_dir are provided, for each shuffled .msb in in_dir we
    compare its bytes to the corresponding vanilla .msb in vanilla_dir.
    If they match exactly (no swaps committed), we copy the original
    .msb.dcx from original_dcx_dir straight to out_dir instead of
    recompressing. Saves the Oodle round-trip on unchanged tiles —
    typically ~50% of files in a standard run.

    Determinism note: Oodle compression is not byte-exact across versions
    (different LZ-block boundaries possible), so naively recompressing an
    untouched MSB might produce slightly different DCX bytes than the
    original game's. Copying the ORIGINAL .msb.dcx avoids that uncertainty
    entirely — the bytes the game shipped with are guaranteed to be valid.

    v0.23.71: parallelized via ThreadPoolExecutor. See _worker_count().
    The identity-skip path is preserved per-file inside the worker, so
    you still get the ~50% skip rate alongside the speedup.

    v0.23.75: `skip_identity_files` opts files out of identity-skip. Used
    for rewired MSBs: their vanilla_dir bytes are the REWIRED bytes (the
    rewire step overwrote them), but original_dcx_dir still holds the
    user's untouched vanilla DCX. If identity-skip fires for a rewired
    file (no swaps committed → shuffled bytes == vanilla_dir rewired
    bytes), it'd copy the ORIGINAL vanilla DCX into the output —
    silently regressing the rewires. Forcing recompress on these files
    means we emit the actual rewired bytes as DCX.
    """
    os.makedirs(out_dir, exist_ok=True)
    if oodle is None: oodle = _Oodle.get()
    files = sorted(f for f in os.listdir(in_dir) if f.endswith('.msb'))
    n_workers = _worker_count()
    print(f"Compressing {len(files)} .msb files to .msb.dcx (workers={n_workers})...")
    t0 = time.time()
    import shutil as _shutil
    skip_identity_files = skip_identity_files or set()

    def _compress_one(f):
        try:
            import oops_v3
            oops_v3._check_cancel()
        except ImportError:
            pass
        in_path = os.path.join(in_dir, f)
        out_path = os.path.join(out_dir, f + '.dcx')
        # v0.23.07: identity-skip — copy original .msb.dcx if shuffled bytes
        # match vanilla bytes. Defensive: any I/O or comparison failure
        # silently falls through to normal recompress, so this can never
        # produce a *wrong* DCX, only a slower one in the failure case.
        # v0.23.75: rewired files opt out — see compress_dir docstring.
        if vanilla_dir and original_dcx_dir and f not in skip_identity_files:
            vanilla_msb = os.path.join(vanilla_dir, f)
            original_dcx = os.path.join(original_dcx_dir, f + '.dcx')
            if os.path.exists(vanilla_msb) and os.path.exists(original_dcx):
                try:
                    with open(in_path, 'rb') as fp_a:
                        a = fp_a.read()
                    with open(vanilla_msb, 'rb') as fp_b:
                        b = fp_b.read()
                    if a == b:
                        _shutil.copy(original_dcx, out_path)
                        return ('skip', f, None)
                except Exception:
                    pass  # fall through to real compress
        try:
            DCX.compress_file(in_path, out_path, oodle=oodle)
            return ('ok', f, None)
        except Exception as e:
            return ('fail', f, traceback.format_exc())

    n_ok = n_fail = n_skipped = 0
    if n_workers == 1:
        for f in files:
            status, fname, err = _compress_one(f)
            if status == 'ok': n_ok += 1
            elif status == 'skip': n_skipped += 1
            else:
                print(f"  FAIL {fname}: {err}")
                n_fail += 1
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_compress_one, f): f for f in files}
            try:
                for fut in as_completed(futures):
                    status, fname, err = fut.result()
                    if status == 'ok': n_ok += 1
                    elif status == 'skip': n_skipped += 1
                    else:
                        print(f"  FAIL {fname}: {err}")
                        n_fail += 1
            except Exception:
                for fut in futures:
                    fut.cancel()
                raise

    dt = time.time() - t0
    if n_skipped:
        print(f"Done: {n_ok} compressed, {n_skipped} skipped (identical to vanilla), "
              f"{n_fail} failed, {dt:.1f}s")
    else:
        print(f"Done: {n_ok} OK, {n_fail} failed, {dt:.1f}s")
    return n_ok, n_fail


def emevd_decompress_dir(in_dir, out_dir, oodle=None, overlay_dir=None):
    """v0.24.0: Decompress every .emevd.dcx in in_dir to .emevd in out_dir.

    Sister of decompress_dir, EMEVD edition. DCX format is the same
    regardless of payload (Kraken/level-6 wrapping); only the file
    extension filter changes. Used by rando_pipeline's Step 4
    (healthbar nameId patching).

    Unlike decompress_dir there's no passthrough_set fast path — EMEVD
    files don't have a HUB_MAPS-style untouched set; every file gets
    scanned and (potentially) patched.

    v0.24.61: overlay_dir parameter. When set, for each .emevd.dcx file
    in in_dir, if a same-named file exists in overlay_dir, the overlay
    version is decompressed instead of the vanilla version. This is
    used to inject emevd_patch.py output (common_func with semantic JS
    patches + bundled per-map fixes) into the auto-pipeline so those
    patches survive across rando re-rolls instead of being clobbered
    when the pipeline writes its healthbar-patched output back.

    The overlay may contain EITHER pre-compressed .emevd.dcx files OR
    already-decompressed .emevd files (same basename as vanilla, minus the
    .dcx). A decompressed overlay file is the raw form this function emits
    anyway, so it's copied straight through — no oodle needed for it. This
    lets the project ship patched_emevd/ as plain .emevd (git-friendly,
    smaller, no Windows-only recompress step) and still have the overlay
    apply on the user's machine. Files in overlay_dir without a vanilla
    counterpart are ignored (the file list comes from in_dir). Files NOT in
    overlay fall through to vanilla — overlay is sparse, not exhaustive."""
    import shutil
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(out_dir, exist_ok=True)
    if oodle is None: oodle = _Oodle.get()
    files = sorted(f for f in os.listdir(in_dir) if f.endswith('.emevd.dcx'))
    n_workers = _worker_count()
    # v0.24.61 / v0.27.x: map each vanilla .emevd.dcx -> overlay source, if
    # any. The overlay file may be .emevd.dcx (compressed) or .emevd (raw).
    # Value is (src_path, is_raw).
    overlay_src = {}
    if overlay_dir and os.path.isdir(overlay_dir):
        present = set(os.listdir(overlay_dir))
        for f in files:                      # f ends with .emevd.dcx
            if f in present:                 # compressed overlay
                overlay_src[f] = (os.path.join(overlay_dir, f), False)
            elif f[:-4] in present:          # decompressed overlay (.emevd)
                overlay_src[f] = (os.path.join(overlay_dir, f[:-4]), True)
    if overlay_src:
        print(f"Decompressing {len(files)} .emevd.dcx files "
              f"({len(overlay_src)} from overlay {overlay_dir}, "
              f"{len(files) - len(overlay_src)} from vanilla; "
              f"workers={n_workers})...")
    else:
        print(f"Decompressing {len(files)} .emevd.dcx files (workers={n_workers})...")
    t0 = time.time()

    def _one(f):
        dst = os.path.join(out_dir, f[:-4])  # strip .dcx -> .emevd
        try:
            if f in overlay_src:
                src, is_raw = overlay_src[f]
                if is_raw:
                    # overlay file is already decompressed — copy as-is.
                    shutil.copyfile(src, dst)
                    return (f, None)
            else:
                src = os.path.join(in_dir, f)
            raw = DCX.decompress_file(src, oodle=oodle)
            with open(dst, 'wb') as fp:
                fp.write(raw)
            return (f, None)
        except Exception as e:
            return (f, str(e))

    failed = []
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        for f, err in ex.map(_one, files):
            if err:
                failed.append((f, err))
    dt = time.time() - t0
    print(f"Done: {len(files) - len(failed)} OK, {len(failed)} failed, {dt:.1f}s")
    for f, err in failed:
        print(f"  FAILED: {f}: {err}")
    return failed


def emevd_compress_dir(in_dir, out_dir, oodle=None):
    """v0.24.0: Compress every .emevd in in_dir to .emevd.dcx in out_dir.

    Sister of compress_dir, EMEVD edition. NR's DCX header for EMEVDs
    uses the same Kraken/level-6 configuration as MSBs (DCX wrap is
    set per archive, and NR ships .msb.dcx and .emevd.dcx with the
    same compression knobs).
    """
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(out_dir, exist_ok=True)
    if oodle is None: oodle = _Oodle.get()
    files = sorted(f for f in os.listdir(in_dir) if f.endswith('.emevd'))
    n_workers = _worker_count()
    print(f"Compressing {len(files)} .emevd files (workers={n_workers})...")
    t0 = time.time()

    def _one(f):
        src = os.path.join(in_dir, f)
        dst = os.path.join(out_dir, f + '.dcx')
        try:
            DCX.compress_file(src, dst, oodle=oodle)
            return (f, None)
        except Exception as e:
            return (f, str(e))

    failed = []
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        for f, err in ex.map(_one, files):
            if err:
                failed.append((f, err))
    dt = time.time() - t0
    print(f"Done: {len(files) - len(failed)} OK, {len(failed)} failed, {dt:.1f}s")
    for f, err in failed:
        print(f"  FAILED: {f}: {err}")
    return failed


def include_spawn_pool_msbs(vanilla_dir, spawn_pool_source_dir, oodle=None):
    """v0.23.56: auto-include vanilla spawn-pool MSBs into vanilla_dir.

    NR's expedition system loads 23 tiny "spawn-pool" MSBs at runtime
    via the engine-internal SmallBase attach system, teleporting their
    chr Parts to per-expedition attach points on live world MSBs. These
    are the rotation bosses (Tree Sentinels, BBH at Castle Basement,
    Death Rite Bird, etc.) Most users' me3 profiles only contain the
    live world maps they want randomized — the spawn-pool MSBs ship from
    vanilla NR un-overridden, so the rotation bosses always appear
    in their vanilla form.

    Auto-include fixes this: walk V3_SPAWN_POOL_MSBS, find any that
    aren't already in vanilla_dir, decompress from spawn_pool_source_dir
    (a vanilla NR map/mapstudio path) into vanilla_dir. The shuffler
    treats them as normal inputs from there. The catalog already tags
    pi=1 of each spawn-pool map as a boss slot, so OOPS_ALL_NB intercept
    fires on them automatically.

    Returns (n_added, n_already_present, n_missing). 'missing' counts
    spawn-pool MSBs that aren't in either vanilla_dir or
    spawn_pool_source_dir — these will continue to ship vanilla.

    v0.23.57: results also get logged to oops_v3.V3_PIPELINE_METADATA
    under 'spawn_pool_include' for spoiler diagnostics.
    """
    import oops_v3
    if not spawn_pool_source_dir or not os.path.isdir(spawn_pool_source_dir):
        oops_v3.V3_PIPELINE_METADATA['spawn_pool_include'] = {
            'n_added': 0, 'n_already_present': 0, 'n_missing': 0,
            'skipped_reason': ('source_dir_unset' if not spawn_pool_source_dir
                               else 'source_dir_not_a_directory'),
            'added_msbs': [],
        }
        return (0, 0, 0)
    if oodle is None: oodle = _Oodle.get()
    n_added = n_already_present = n_missing = 0
    added_msbs = []
    missing_msbs = []
    for msb_base in sorted(oops_v3.V3_SPAWN_POOL_MSBS.keys()):
        msb_name = msb_base + '.msb'
        if os.path.exists(os.path.join(vanilla_dir, msb_name)):
            n_already_present += 1
            continue
        # Try .msb.dcx first (vanilla format), fall back to raw .msb
        src_dcx = os.path.join(spawn_pool_source_dir, msb_name + '.dcx')
        src_raw = os.path.join(spawn_pool_source_dir, msb_name)
        dst = os.path.join(vanilla_dir, msb_name)
        if os.path.isfile(src_dcx):
            try:
                raw = DCX.decompress_file(src_dcx, oodle)
                with open(dst, 'wb') as fp: fp.write(raw)
                n_added += 1
                added_msbs.append(msb_name)
            except Exception as e:
                print(f"  spawn-pool decompress failed for {msb_name}: {e}")
                missing_msbs.append(msb_name + ' (decompress_failed)')
                n_missing += 1
        elif os.path.isfile(src_raw):
            import shutil as _shutil
            _shutil.copy(src_raw, dst)
            n_added += 1
            added_msbs.append(msb_name)
        else:
            missing_msbs.append(msb_name)
            n_missing += 1
    oops_v3.V3_PIPELINE_METADATA['spawn_pool_include'] = {
        'n_added': n_added,
        'n_already_present': n_already_present,
        'n_missing': n_missing,
        'added_msbs': added_msbs,
        'missing_msbs': missing_msbs,
    }
    return (n_added, n_already_present, n_missing)


def rando_pipeline(in_dcx_dir, out_dcx_dir, seed=42, mode='loose',
                    keep_intermediates=False, oops_all_target_cp=None,
                    randomize_clusters=False, cluster_shape=False,
                    cluster_aware=True,
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
                    unique_cap_overrides=None,
                    caliber_pool_extras=None,
                    caliber_pool_removals=None,
                    spawn_pool_source_dir=None,
                    emevd_vanilla_dir=None,
                    emevd_out_dir=None,
                    emevd_overlay_dir=None,
                    vanilla_msg_bundle=None,
                    mod_msg_bundle=None,
                    fallback_nameid=None,
                    chr_to_nameid_path=None,
                    randomize_safe_nb_arenas=False,
                    randomize_all_nb_arenas=False):
    """Full pipeline: decompress → shuffle → recompress.

    Cluster modes (multi-Part encounters within 2m of each other):
      randomize_clusters=False (default): leave clusters vanilla. Solo Parts
        are randomized; multi-Part encounters stay intact (Crystalian Alliance,
        paired bosses, rider+mount combos preserved).
      randomize_clusters=True, cluster_shape=False: coordinated swap — every
        member of a cluster becomes the same new c-prefix. More variety, but
        rider+mount semantic is lost.
      randomize_clusters=True, cluster_shape=True: shape-matched swap from a
        catalog of vanilla clusters. Best fidelity — rider+mount becomes
        rider+mount of a different family.
      cluster_aware=False: skip cluster computation entirely. Every Part
        rolls independently. Maris Tendril, Banished Knight encampments,
        etc. all randomize per-Part regardless of spatial proximity.
    """
    import tempfile, shutil
    import oops_v3

    # v0.23.57: reset pipeline metadata at the start of every full pipeline run.
    # We populate input/spawn-pool fields here, the engine populates per-MSB
    # results during shuffle, and write_spoiler_logs dumps everything into the
    # spoiler header. cmd_shuffle_v3 doesn't reset — that would clobber what we
    # set here.
    oops_v3._reset_pipeline_metadata()
    oops_v3.V3_PIPELINE_METADATA['in_dcx_dir'] = in_dcx_dir
    oops_v3.V3_PIPELINE_METADATA['out_dcx_dir'] = out_dcx_dir
    oops_v3.V3_PIPELINE_METADATA['spawn_pool_source_dir'] = spawn_pool_source_dir
    oops_v3.V3_PIPELINE_METADATA['pipeline'] = 'dcx_batch.rando_pipeline'

    # v0.26.16: night-boss-arena preservation gate. All 25 NB arenas
    # ship byte-vanilla on the EMEVD side; the healthbar step below
    # applies the matching exclusion. See V3_NIGHT_BOSS_ARENA_MSBS in
    # oops_v3.py.
    oops_v3.V3_PRESERVE_NIGHT_BOSS_ARENAS = True
    # v0.26.16: safe-NB-arena MSB randomization. When on, the 12 single-
    # boss N1/N2 arenas in V3_SAFE_NB_RANDOMIZE_MSBS get their boss Part
    # swapped; EMEVD stays vanilla via the healthbar-step NB exclude.
    oops_v3.V3_RANDOMIZE_SAFE_NB_ARENAS = randomize_safe_nb_arenas
    # v0.26.x: all-NB-arena MSB randomization. Randomizes all 25 NB
    # arenas incl. the multi-entity ones; the boss-init breakage there
    # is resolved via the regulation.bin modification. Supersedes the
    # safe-NB flag -- all 25 includes the safe 12.
    oops_v3.V3_RANDOMIZE_ALL_NB_ARENAS = randomize_all_nb_arenas

    work_dir = tempfile.mkdtemp(prefix='oops_rando_')
    try:
        vanilla_dir = os.path.join(work_dir, 'vanilla')
        shuffled_dir = os.path.join(work_dir, 'shuffled')
        os.makedirs(vanilla_dir, exist_ok=True)
        os.makedirs(shuffled_dir, exist_ok=True)

        oodle = _Oodle.get()

        # v0.23.07: short-circuit HUB_MAPS at decompress time. They aren't
        # shuffled, so decompressing them just to recompress identical
        # output bytes is wasted Oodle work on both ends. Pass them through
        # to the output DCX dir directly. The shuffler still expects to see
        # them at vanilla_dir (it walks the dir to find MSBs to skip), so
        # we don't add them to the passthrough set if the directory is also
        # the shuffler's input. Concretely: HUB_MAPS skip the
        # decompress-recompress round trip entirely.
        os.makedirs(out_dcx_dir, exist_ok=True)
        hub_passthrough = set()
        try:
            hub_passthrough = {f + '.dcx' for f in oops_v3.V3_HUB_MAPS
                               if os.path.exists(os.path.join(in_dcx_dir,
                                                              f + '.dcx'))}
        except Exception:
            hub_passthrough = set()

        print(f"=== Step 1/4: Decompressing vanilla DCX files ===")
        decompress_dir(in_dcx_dir, vanilla_dir, oodle,
                       passthrough_dcx_dest=out_dcx_dir,
                       passthrough_set=hub_passthrough)

        # v0.23.75: apply rewired MSBs over the decompressed vanilla. The
        # rewires are static (shipped in the repo) and override specific
        # maps' MSB Parts with versions that have rewired Generator
        # spawnPartIndices — see rewired_msbs/REWIRES.md. By decompressing
        # them into vanilla_dir AFTER the initial decompress, we
        # overwrite the same-name .msb files; the shuffler then sees the
        # rewired versions as its input. Skipped silently if the directory
        # doesn't exist (lets the toolchain run without rewires for
        # diagnostic A/B testing — see the toggle below if you need that).
        if os.path.isdir(REWIRES_DIR):
            rewire_files = [f for f in os.listdir(REWIRES_DIR)
                            if f.endswith('.msb.dcx')]
            if rewire_files:
                print(f"=== Step 1a/3: Applying {len(rewire_files)} rewired "
                      f"MSBs from {os.path.basename(REWIRES_DIR)}/ ===")
                n_ok, n_fail = decompress_dir(REWIRES_DIR, vanilla_dir, oodle)
                if n_fail:
                    print(f"  WARNING: {n_fail} rewire(s) failed to decompress")
                # Record on metadata so the spoiler captures which maps
                # were running on rewired input vs pure vanilla.
                oops_v3.V3_PIPELINE_METADATA['rewires_applied'] = sorted(
                    f[:-len('.dcx')] for f in rewire_files)

        # v0.23.56: spawn-pool auto-include. After decompressing the user's
        # input dir, pull any missing rotation-boss MSBs from the vanilla
        # source (typically the user's vanilla NR map/mapstudio folder) so
        # they reach the shuffler. Without this, Tree Sentinels at the
        # castle rooftop, BBH at Castle Basement, Death Rite Bird at random
        # arenas, etc. always appear in their vanilla form because most me3
        # profiles only override the live world MSBs.
        if spawn_pool_source_dir:
            print(f"=== Step 1b/3: Including spawn-pool MSBs from "
                  f"{spawn_pool_source_dir} ===")
            n_added, n_present, n_missing = include_spawn_pool_msbs(
                vanilla_dir, spawn_pool_source_dir, oodle)
            print(f"  Added {n_added} spawn-pool MSBs to input "
                  f"({n_present} already present in input, "
                  f"{n_missing} missing from source)")
            if n_missing:
                print(f"  WARNING: {n_missing} spawn-pool MSBs not found in "
                      f"source — those rotation bosses will continue to "
                      f"appear in vanilla form.")

        if terrain_test_targets:
            mode_label = (f"Terrain test (on→{terrain_test_targets['on_mesh']}, "
                          f"off→{terrain_test_targets['off_mesh']})")
        elif oops_all_target_cp:
            mode_label = f'Oops! All {oops_all_target_cp}'
        elif oops_all_nb_target_cp:
            mode_label = (f'Oops! All NB {oops_all_nb_target_cp} '
                          f'(scope={oops_all_nb_marker_scope or "broad"})')
        else:
            mode_label = 'Standard'

        # v0.23.83 Step 1b: apply slot repositions if a JSON is present.
        # Reads slot_repositions.json and rewrites Part position fields
        # (offset 0x400) for every off-mesh slot to the nearest navmesh
        # leaf center. Pre-shuffle so the shuffle sees the corrected
        # positions and the off_mesh_slots restriction in slot_terrain.json
        # gets satisfied (target_pool no longer needs to soft-restrict
        # those slots). Same in-place byte substitution discipline as
        # Step 2a (walk_route renames).
        if SLOT_REPOSITIONS_PATH and os.path.exists(SLOT_REPOSITIONS_PATH):
            import json as _json
            print(f"\n=== Step 1b/3: Applying slot repositions ===")
            _rp = _json.load(open(SLOT_REPOSITIONS_PATH, encoding='utf-8'))
            _proposals = _rp.get('proposals', {})
            _scope = SLOT_REPOSITIONS_ONLY_MAPS
            print(f"  slot_repositions.json: {len(_proposals)} maps, "
                  f"{_rp.get('metadata',{}).get('total_relocations','?')} relocations")
            if _scope:
                _filtered = {m: v for m, v in _proposals.items() if m in _scope}
                print(f"  SCOPED to {len(_filtered)} maps via "
                      f"SLOT_REPOSITIONS_ONLY_MAPS")
                _proposals = _filtered
            if SLOT_REPOSITIONS_USE_FLOOR:
                print(f"  Using to_pos_floor (AABB min-Y)")

            import sys as _sys
            _sys.path.insert(0, os.path.join(HERE, 'dev'))
            from apply_slot_repositions import relocate_one_msb as _relocate_one_msb

            _total_written = 0
            _total_attempted = 0
            _maps_touched = 0
            _per_map_log = {}
            for _msb_name, _msb_props in _proposals.items():
                _in = os.path.join(vanilla_dir, _msb_name)
                if not os.path.exists(_in):
                    continue
                _result = _relocate_one_msb(
                    _in, _in,  # in-place: overwrite the decompressed vanilla
                    _msb_props,
                    use_floor=SLOT_REPOSITIONS_USE_FLOOR,
                    dry_run=False,
                )
                if 'error' in _result:
                    print(f"  {_msb_name}: ERROR {_result['error']}")
                    continue
                _total_attempted += _result['n_attempted']
                _total_written  += _result['n_written']
                if _result['n_written'] > 0:
                    _maps_touched += 1
                    _per_map_log[_msb_name] = {
                        'n_written': _result['n_written'],
                        'n_attempted': _result['n_attempted'],
                        'n_failed': len(_result['failures']),
                    }
            print(f"  {_total_written}/{_total_attempted} relocations applied "
                  f"across {_maps_touched} MSBs")
            oops_v3.V3_PIPELINE_METADATA['slot_repositions'] = {
                'json_path':    SLOT_REPOSITIONS_PATH,
                'scoped_to':    sorted(SLOT_REPOSITIONS_ONLY_MAPS) if SLOT_REPOSITIONS_ONLY_MAPS else None,
                'use_floor':    SLOT_REPOSITIONS_USE_FLOOR,
                'n_attempted':  _total_attempted,
                'n_written':    _total_written,
                'maps_touched': _maps_touched,
                'per_map':      _per_map_log,
            }

        cluster_label = ('IGNORED (per-Part chaos)' if not cluster_aware
                         else 'shape-matched' if cluster_shape
                         else 'coordinated' if randomize_clusters
                         else 'vanilla')
        print(f"\n=== Step 2/4: Running rando "
              f"(seed={seed}, mode={mode_label}, clusters={cluster_label}) ===")
        # v0.23.82: diagnostic override. If the module-level constant
        # PLACED_PART_FORCE_CP is set, force ALL placed Parts (fragile and
        # non-fragile) to that c-prefix by routing through oops_all_target_cp,
        # which short-circuits compat/fragile/tier checks at the swap site
        # (oops_v3.py line 9757). Variant within the c-prefix is rolled per-
        # slot via pick_variant_for_tier so e.g. Foot Soldier variants vary.
        # Used for visual-baseline diagnostic runs paired with WALK_ROUTE_FORCE_CP.
        if PLACED_PART_FORCE_CP is not None:
            print(f"  DIAGNOSTIC: oops_all_target_cp forced to "
                  f"{PLACED_PART_FORCE_CP!r} (was {oops_all_target_cp!r})")
            oops_all_target_cp = PLACED_PART_FORCE_CP
        # `mode` is rando_pipeline's local log-label variable only —
        # cmd_shuffle_v3 has no `mode` parameter, so it is not forwarded.
        # v0.26.x: the cluster triad (randomize_clusters / cluster_shape /
        # cluster_aware) was retired from cmd_shuffle_v3's signature when
        # the shuffler was refactored; the GUI dropped its cluster toggles
        # back at v0.19.27. These three remain as inert rando_pipeline
        # parameters (for the cluster_label log line above and backward-
        # compatible callers) but are NOT forwarded — passing them raised
        # "unexpected keyword argument 'randomize_clusters'".
        oops_v3.cmd_shuffle_v3(vanilla_dir, shuffled_dir, seed,
                                oops_all_target_cp=oops_all_target_cp,
                                merchant_model_swap=merchant_model_swap,
                                terrain_test_targets=terrain_test_targets,
                                excluded_prefixes=excluded_prefixes,
                                hub_maps=hub_maps,
                                multiplayer_safe=multiplayer_safe,
                                disable_resilient_filter=disable_resilient_filter,
                                non_fragile_baseline_cp=non_fragile_baseline_cp,
                                diagnostic_test_targets=diagnostic_test_targets,
                                force_include_targets=force_include_targets,
                                chaos_mode=chaos_mode,
                                mount_rider_swap=mount_rider_swap,
                                sote_mode=sote_mode,
                                oops_all_nb_target_cp=oops_all_nb_target_cp,
                                oops_all_nb_marker_scope=oops_all_nb_marker_scope,
                                unique_cap_overrides=unique_cap_overrides,
                                caliber_pool_extras=caliber_pool_extras,
                                caliber_pool_removals=caliber_pool_removals)

        if not WALK_ROUTE_REWRITE_ENABLED:
            print(f"\n=== Step 2a/3: walk_route_rewrite DISABLED (v0.24.93-patch14) ===")
            print(f"  Skipping 554-event rewrite across 81 MSBs. "
                  f"Set WALK_ROUTE_REWRITE_ENABLED=True in dcx_batch.py to re-enable.")
        else:
            print(f"\n=== Step 2a/3: Rewriting walk_route procedural-spawn names ===")
            # v0.23.77: walk_route_cXXXX events drive NR's procedural Limveld
            # spawn engine — chrs of c-prefix cXXXX spawn at the route's points
            # at runtime, independent of any MSB Part placements. Until v0.23.76
            # these events were untouched by the rando, so vanilla c4100 Demi-
            # Humans (and 63 other c-prefixes) spawned at fixed locations even
            # in oops-all runs. This pass substitutes the c-prefix in the event
            # name with a target picked by oops_v3.pick_target_cp — same picker
            # the main shuffle uses, so walk_routes get the full tier-aware
            # grunt-pool treatment (excludes V3_EXCLUDE_TARGET_PREFIXES,
            # respects V3_MAP_PREFIX_TARGET_EXCLUDES, applies unique-cap
            # exhaustion). v0.23.78: recipient_is_boss=False forces field-tier
            # picks since walk_routes are procedural ambient-mob spawns, not
            # boss encounters. In-place byte substitution preserves all MSB
            # offsets — c-prefix is always 5 chars. See dev/rewrite_walk_routes.py.
            import sys as _sys
            _sys.path.insert(0, os.path.join(HERE, 'dev'))
            from rewrite_walk_routes import rewrite_one_msb as _rewrite_walk_routes_one
            import random as _random

            # Build roster-backed picker — wraps oops_v3.pick_target_cp with
            # the per-MSB context the walk_route pass has (slot_msb_name only;
            # no slot_pi/slot_variant_name since walk_routes are events not Parts).
            _tags = oops_v3._load_tags() if hasattr(oops_v3, '_load_tags') else None
            # _load_tags isn't a stable public API — fall back to direct json load
            # if the function isn't present.
            if _tags is None:
                import json as _json
                _tags = _json.load(open(oops_v3._data_path('nr_enemy_tags.json'), encoding='utf-8'))
                _roster = _json.load(open(oops_v3._data_path('nr_enemy_roster.json'), encoding='utf-8'))
                _prefix_variants, _prefix_count = oops_v3.build_per_prefix_data(_roster)
            else:
                _prefix_variants, _prefix_count = oops_v3.build_per_prefix_data(
                    oops_v3._load_roster() if hasattr(oops_v3, '_load_roster')
                    else _json.load(open(oops_v3._data_path('nr_enemy_roster.json'), encoding='utf-8')))

            def _walk_route_picker(source_cp, rng, slot_msb_name=None):
                # v0.23.81 diagnostic: if WALK_ROUTE_FORCE_CP is set, ignore
                # tier/excludes/seed entirely and return the forced c-prefix.
                # This pairs with NON_FRAGILE_BASELINE_OVERRIDE for visual-
                # baseline runs (everything's a Foot Soldier except procedural
                # spawns which are all Jellyfish, anomalies are fragile slots).
                if WALK_ROUTE_FORCE_CP is not None:
                    return WALK_ROUTE_FORCE_CP
                return oops_v3.pick_target_cp(
                    recipient_cp=source_cp,
                    tags=_tags,
                    prefix_variants=_prefix_variants,
                    prefix_count=_prefix_count,
                    recipient_is_boss=False,  # walk_routes are field-tier
                    rng=rng,
                    slot_msb_name=slot_msb_name,
                    slot_pi=None,
                    slot_variant_name=None,
                    slot_pos=None,
                )

            if WALK_ROUTE_FORCE_CP is not None:
                print(f"  DIAGNOSTIC: walk_route picker forced to "
                      f"{WALK_ROUTE_FORCE_CP!r} (bypassing tier-aware picker)")
            wr_per_map = {}
            wr_total_routes = 0
            wr_total_renamed = 0
            for _fn in sorted(os.listdir(shuffled_dir)):
                if not _fn.endswith('.msb'):
                    continue
                _in = os.path.join(shuffled_dir, _fn)
                # Deterministic per-file sub-RNG so file ordering doesn't matter.
                _sub_rng = _random.Random(f'walk_route:{seed}:{_fn}')
                _result = _rewrite_walk_routes_one(_in, _in, _sub_rng,
                                                   pick_target_fn=_walk_route_picker,
                                                   dry_run=False)
                if _result.get('n_walk_routes', 0) > 0:
                    wr_per_map[_fn] = _result
                    wr_total_routes += _result['n_walk_routes']
                    wr_total_renamed += _result['n_renamed']
            print(f"  {wr_total_renamed}/{wr_total_routes} walk_routes renamed "
                  f"across {len(wr_per_map)} MSBs")
            # Record on metadata so spoiler shows what changed.
            oops_v3.V3_PIPELINE_METADATA['walk_route_rewrite'] = {
                'picker':         (f'FORCED({WALK_ROUTE_FORCE_CP!r})' if WALK_ROUTE_FORCE_CP
                                   else 'oops_v3.pick_target_cp(recipient_is_boss=False)'),
                'n_msbs_touched': len(wr_per_map),
                'n_routes_seen':  wr_total_routes,
                'n_renamed':      wr_total_renamed,
                'per_map':        {fn: {'n_walk_routes': r['n_walk_routes'],
                                        'n_renamed': r['n_renamed'],
                                        'renames': [{'evt': x['event_idx'],
                                                     'src': x['source'],
                                                     'tgt': x['target']}
                                                    for x in r['renames']
                                                    if x.get('target')]}
                                   for fn, r in wr_per_map.items()},
            }

            # v0.23.80: write_spoiler_logs snapshots V3_PIPELINE_METADATA inside
            # cmd_shuffle_v3 (oops_v3.py line 11316: `'pipeline_metadata': dict(...)`)
            # before Step 2a runs, so the walk_route_rewrite key we just set
            # wouldn't reach the spoiler without a re-write. Cleanest fix is to
            # patch the on-disk JSON in place — the .json sits in shuffled_dir,
            # which is the same dir the recompress step reads next, so the
            # downstream copy will pick up the updated version.
            import json as _json
            _spoiler_json_path = os.path.join(shuffled_dir, '_spoilers.json')
            if os.path.exists(_spoiler_json_path):
                try:
                    with open(_spoiler_json_path, 'r', encoding='utf-8') as _f:
                        _spoiler = _json.load(_f)
                    _spoiler.setdefault('pipeline_metadata', {})['walk_route_rewrite'] = (
                        oops_v3.V3_PIPELINE_METADATA['walk_route_rewrite'])
                    with open(_spoiler_json_path, 'w', encoding='utf-8') as _f:
                        _json.dump(_spoiler, _f, indent=2)
                    print(f"  walk_route_rewrite metadata injected into {os.path.basename(_spoiler_json_path)}")
                except Exception as _e:
                    print(f"  WARNING: failed to patch spoiler JSON: {_e}")

        print(f"\n=== Step 3/4: Recompressing shuffled MSBs to DCX ===")
        # v0.23.07: pass vanilla_dir + in_dcx_dir to enable identity-skip.
        # Files whose shuffled bytes match vanilla bytes get their
        # original .msb.dcx copied straight from in_dcx_dir, skipping
        # Oodle entirely. ~50% of MSBs are unchanged in a typical run.
        # v0.23.75: rewired MSBs opt out of identity-skip so their
        # rewired bytes (not the user's untouched vanilla DCX) reach the
        # output. See compress_dir docstring.
        rewire_skip_identity = set()
        if os.path.isdir(REWIRES_DIR):
            rewire_skip_identity = {f[:-len('.dcx')]
                                    for f in os.listdir(REWIRES_DIR)
                                    if f.endswith('.msb.dcx')}
        compress_dir(shuffled_dir, out_dcx_dir, oodle,
                     vanilla_dir=vanilla_dir,
                     original_dcx_dir=in_dcx_dir,
                     skip_identity_files=rewire_skip_identity)

        # Spoiler logs are written into shuffled_dir; copy them out alongside DCX
        for fname in ('_spoilers.json', '_spoilers.md'):
            src = os.path.join(shuffled_dir, fname)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(out_dcx_dir, fname))

        # ─────────────────────────────────────────────────────────────
        # Step 4/4: Healthbar nameId patcher.
        #
        # v0.24.0 introduces a DSAS3-free in-place EMEVD byte patcher
        # that rewrites boss healthbar nameIds so the on-screen name
        # matches the chr that actually spawned. Decompresses
        # .emevd.dcx with the same Oodle path Step 1 uses for MSBs,
        # patches nameId bytes in place via healthbar_inplace.pipeline,
        # recompresses. Pure Python + Oodle; no DSAS3 round-trip.
        #
        # Gracefully skips if any prerequisite is missing:
        #   - emevd_vanilla_dir: source .emevd.dcx (typically the
        #     game install's Game/event/ directory; configured via the
        #     GUI's .4laric_emevd_paths.json).
        #   - emevd_out_dir: where to drop patched .emevd.dcx (typically
        #     the me3 profile's event/ directory).
        #   - chr_to_nameid_path: vanilla nameId catalog from
        #     healthbar_tools/prep_demo.py BUILD-CATALOG. Without it
        #     every swap would route to fresh_allocation requiring FMG
        #     edits; skipping is safer than spamming garbage names.
        #
        # Spoiler metadata: writes a healthbar_rewrite block into
        # _spoilers.json/_spoilers.md alongside walk_route_rewrite.
        # ─────────────────────────────────────────────────────────────
        healthbar_status = 'skipped (no emevd_vanilla_dir configured)'
        healthbar_report = None
        if emevd_vanilla_dir and emevd_out_dir:
            if not chr_to_nameid_path or not os.path.exists(chr_to_nameid_path):
                healthbar_status = ('skipped (chr_to_nameid.json missing — '
                                    'run healthbar_tools/prep_demo.py BUILD-CATALOG)')
                print(f"\n=== Step 4/4: Healthbar patcher: SKIPPED ===")
                print(f"  {healthbar_status}")
            elif not os.path.isdir(emevd_vanilla_dir):
                healthbar_status = f'skipped (emevd_vanilla_dir not found: {emevd_vanilla_dir})'
                print(f"\n=== Step 4/4: Healthbar patcher: SKIPPED ===")
                print(f"  {healthbar_status}")
            else:
                print(f"\n=== Step 4/4: Patching boss healthbar nameIds ===")
                try:
                    import sys as _sys
                    _sys.path.insert(0, os.path.join(HERE, 'healthbar_inplace'))
                    from pipeline import apply_to_dir as _apply_to_dir
                    _hb_t0 = time.time()
                    raw_emevd = os.path.join(work_dir, 'raw_emevd')
                    patched_emevd = os.path.join(work_dir, 'patched_emevd')
                    # v0.26.16: the 25 night-boss arenas ship byte-
                    # vanilla — exclude them from healthbar patching so
                    # they are never written to the mod event/ dir (me3
                    # then serves the vanilla emevd). Mirrors the MSB-side
                    # V3_PRESERVE_NIGHT_BOSS_ARENAS gate.
                    hb_exclude = {m.replace('.msb', '.emevd')
                                  for m in oops_v3.V3_NIGHT_BOSS_ARENA_MSBS}
                    if hb_exclude:
                        print(f"  Night-boss arenas: preserving "
                              f"{len(hb_exclude)} vanilla "
                              f"— excluded from healthbar patching")
                    # Decompress vanilla .emevd.dcx -> raw .emevd
                    # v0.24.61: overlay_dir lets us substitute pre-patched
                    # files (typically project's patched_emevd/) for the
                    # vanilla version on a per-file basis. emevd_patch.py
                    # output goes here so semantic JS patches survive
                    # the auto-pipeline.
                    emevd_decompress_dir(emevd_vanilla_dir, raw_emevd, oodle,
                                          overlay_dir=emevd_overlay_dir)
                    # Patch nameId bytes per the spoiler
                    spoiler_path = os.path.join(shuffled_dir, '_spoilers.json')
                    # v0.24.106: splice-with-fallback. Phase 1 always fresh-
                    # allocates so the splice step has real per-chr names to
                    # write into NpcName.fmg. Phase 3 (after splice attempt
                    # below) re-patches with `fallback_nameid` if splice
                    # didn't complete — ensures no "NPCName" placeholder
                    # reaches the game even when msg bundle paths aren't
                    # configured.
                    print(f"  Phase 1: patching EMEVDs with fresh nameIds "
                          f"(targeting per-chr names via FMG splice)")
                    # v0.24.x post-investigation: splice path is back.
                    # splice_fmg_entries (fmg.py) now sorts-inserts new
                    # groups and shrinks the previous group's last_id to
                    # carve a reachable gap, breaking vanilla's wide-claim
                    # boundary shadow that defeated every prior splice
                    # attempt. NR's loader accepts entries placed in the
                    # 902M-909M band (proven by MMV and confirmed in-game
                    # via "RANDO TEST BOSS" rendering at nameId
                    # 905_500_000). Phase 3 below still acts as a safety
                    # net when the user's caller passes a fallback_nameid
                    # to rando_pipeline — splice runs by default.
                    #
                    # Compose / fun-rename: v0.24.107's design picks a
                    # title from data/title_pool.json and composes it
                    # with the chr's base name ("Mushroom Dog, Consort
                    # of Miquella"). Probability 1.0 = every unified-
                    # prefix bar gets a composed name. Probability 0.5
                    # was the original design; 1.0 is for the post-
                    # investigation victory lap.
                    #
                    # compose_show_arrow=True prepends the vanilla slot's
                    # name to the rendered output (e.g. "Tree Sentinel →
                    # Mushroom Dog, Consort of Miquella"). Useful for
                    # debugging — tells you which slot a swap came from.
                    # Default off for cleanest in-game presentation.
                    _title_pool_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        'data', 'title_pool.json',
                    )
                    healthbar_report = _apply_to_dir(
                        emevd_dir=raw_emevd,
                        output_dir=patched_emevd,
                        spoiler_path=spoiler_path,
                        chr_to_nameid_path=chr_to_nameid_path,
                        fallback_nameid=None,
                        title_pool_path=_title_pool_path,
                        seed=seed,
                        compose_probability=1.0,
                        exclude_files=hb_exclude,
                        # compose_show_arrow=True,  # ← debug mode
                    )
                    # Recompress patched .emevd -> .emevd.dcx into emevd_out_dir
                    emevd_compress_dir(patched_emevd, emevd_out_dir, oodle)
                    # v0.24.x: mirror healthbar diagnostic artifacts into
                    # out_dcx_dir so they survive tempdir cleanup. The
                    # pipeline writes them into patched_emevd (a tempdir
                    # subdir that gets wiped at end of run); copy them
                    # next to _spoilers.json for post-run inspection.
                    for _diag_fname in ('fmg_additions.json',
                                         'apply_report.json'):
                        _diag_src = os.path.join(patched_emevd, _diag_fname)
                        if os.path.exists(_diag_src):
                            try:
                                shutil.copy(_diag_src,
                                            os.path.join(out_dcx_dir,
                                                         _diag_fname))
                            except Exception as _copy_e:
                                print(f"  WARN: could not mirror "
                                      f"{_diag_fname} to out_dcx_dir: {_copy_e}")
                    n_files_ok = sum(1 for f in healthbar_report['files']
                                     if f['status'] == 'ok')
                    n_unchanged = sum(1 for f in healthbar_report['files']
                                      if f['status'] == 'unchanged')
                    n_no_callsites = sum(1 for f in healthbar_report['files']
                                         if f['status'] == 'no_callsites')
                    n_failed = sum(1 for f in healthbar_report['files']
                                   if f['status'].startswith('parse_failed'))
                    n_rewrites = sum(f.get('rewrites', 0)
                                     for f in healthbar_report['files'])
                    n_callsites_total = sum(f.get('callsites_seen', 0)
                                             for f in healthbar_report['files'])
                    n_fmg = healthbar_report['fmg_additions_count']
                    _hb_dt = time.time() - _hb_t0
                    print(f"  {n_files_ok} files patched, "
                          f"{n_unchanged} unchanged (callsites found, no swap needed), "
                          f"{n_no_callsites} no callsites found, "
                          f"{n_failed} parse failures")
                    print(f"  {n_callsites_total} total callsites extracted across all files, "
                          f"{n_rewrites} healthbar rewrites, "
                          f"{n_fmg} new FMG nameIds ({_hb_dt:.1f}s)")
                    if n_callsites_total == 0:
                        # The audit script knows there are ~337 callsites
                        # in vanilla NR's 197 .emevd files. If our binary
                        # parser extracts ZERO across the entire corpus,
                        # it's a format-spec mismatch.
                        print(f"  WARN: 0 callsites extracted across {len(healthbar_report['files'])} "
                              f"files (the .js audit expects ~337).")
                        # v0.24.2: auto-diagnostic. Scan the raw bytes
                        # of one known-callsite file for handler IDs as
                        # uint32 LE. If they're THERE in the bytes,
                        # the args_offset/args_size header pair is wrong
                        # (handler IDs exist outside our claimed args
                        # region). If they're NOT in the file at all,
                        # handler IDs aren't stored as raw uint32 in NR
                        # — encoding is something we don't know yet.
                        try:
                            from emevd import find_handler_id_hits, Header
                            probe_file = os.path.join(raw_emevd,
                                                       'm48_50_00_00.emevd')
                            if os.path.exists(probe_file):
                                with open(probe_file, 'rb') as _f:
                                    probe_raw = _f.read()
                                hdr = Header.parse(probe_raw)
                                hits_args = find_handler_id_hits(
                                    probe_raw, hdr.args_offset,
                                    hdr.args_offset + hdr.args_size)
                                hits_all = find_handler_id_hits(probe_raw)
                                print(f"  Auto-diagnostic on m48_50_00_00.emevd:")
                                print(f"    handler IDs found within claimed args_region "
                                      f"(0x{hdr.args_offset:x}..0x{hdr.args_offset+hdr.args_size:x}): "
                                      f"{len(hits_args)}")
                                print(f"    handler IDs found anywhere in file (full scan): "
                                      f"{len(hits_all)}")
                                if hits_all and not hits_args:
                                    print(f"    --> args_offset/args_size header pair is "
                                          f"WRONG. Handler IDs exist but outside the claimed region.")
                                    print(f"    First hit at byte offset 0x{hits_all[0][0]:x} "
                                          f"(handler={hits_all[0][1]}).")
                                elif not hits_all:
                                    print(f"    --> handler IDs do not appear in the file as "
                                          f"raw uint32 LE. Different encoding (varint? compressed?).")
                                else:
                                    print(f"    --> handler IDs are in args_region but extract "
                                          f"is still failing. Run inspect_emevd.py for the "
                                          f"structural dump.")
                            else:
                                print(f"  Auto-diagnostic skipped: m48_50_00_00.emevd "
                                      f"not present at {probe_file}")
                        except Exception as _diag_e:
                            print(f"  Auto-diagnostic failed: {_diag_e}")
                        print(f"  For deeper inspection: "
                              f"`python healthbar_inplace/inspect_emevd.py "
                              f"<decompressed.emevd>`")
                    if n_failed:
                        # Print a few sample failure reasons so the user has
                        # actionable info without grepping the report file.
                        failures = [f for f in healthbar_report['files']
                                    if f['status'].startswith('parse_failed')]
                        print(f"  Parse failures (first 5):")
                        for f in failures[:5]:
                            print(f"    {f['file']}: {f['status']}")
                        print(f"  Full per-file report: "
                              f"{os.path.join(emevd_out_dir, 'apply_report.json')}")
                    # v0.24.106: track splice outcome at function scope so the
                    # final healthbar_status reflects what happened even when
                    # n_fmg=0 (no cross-game cases needed special handling).
                    splice_succeeded = False
                    if n_fmg:
                        print(f"  FMG additions: {healthbar_report['fmg_additions_path']}")
                        # v0.24.8: auto-splice the additions into the user's
                        # vanilla NpcName.fmg if both bundle paths are set.
                        # v0.24.106: track splice outcome so Phase 3 fallback
                        # re-patch can fire if splice didn't complete.
                        if vanilla_msg_bundle and mod_msg_bundle:
                            try:
                                import json as _json
                                from healthbar_inplace.bnd_splice_driver import (
                                    splice_npcname_into_bundle_file,
                                )
                                with open(healthbar_report['fmg_additions_path'], encoding='utf-8') as _f:
                                    raw_additions = _json.load(_f)
                                # JSON keys are strings; FMG IDs are ints
                                additions = {int(k): v for k, v in raw_additions.items()}
                                # v0.24.110: bundled-vanilla fallback. If the
                                # on-disk vanilla msg path doesn't exist (NR
                                # install isn't UXM-unpacked or UXM failed on
                                # msg specifically), fall back to the bundled
                                # raw BND4 at data/vanilla_msg/. The bundled
                                # file is unwrapped so it can be parsed
                                # without Oodle for the read step — only the
                                # output DCX-wrap step needs the DLL.
                                _src_path = vanilla_msg_bundle
                                if not os.path.exists(_src_path):
                                    # Bundled fallback path: raw BND4 of
                                    # stock-or-modded NR item_dlc01.msgbnd.
                                    _bundled = os.path.join(
                                        HERE, 'data', 'vanilla_msg',
                                        'item_dlc01.msgbnd')
                                    if os.path.exists(_bundled):
                                        print(f"  Vanilla msg not on disk at "
                                              f"{vanilla_msg_bundle}")
                                        print(f"  Falling back to bundled: "
                                              f"{_bundled}")
                                        _src_path = _bundled
                                with open(_src_path, 'rb') as _f:
                                    bundle_bytes = _f.read()
                                # v0.24.12: log enough state on splice
                                # failure to diagnose without a re-run.
                                _is_dcx = bundle_bytes[:4] == b'DCX\x00'
                                print(f"  Reading: {_src_path}")
                                print(f"  Size: {len(bundle_bytes):,} bytes")
                                print(f"  First 16 bytes (raw): "
                                      f"{bundle_bytes[:16].hex(' ')}")
                                print(f"  DCX wrapper detected: {_is_dcx}")
                                _splice_t0 = time.time()
                                # DCX-aware: detects compression on input,
                                # round-trips it on output. When input is raw
                                # BND4 (bundled-vanilla case) the splice
                                # output is also raw — we DCX-wrap below
                                # before writing since me3 expects .dcx at
                                # the mod path.
                                patched = splice_npcname_into_bundle_file(
                                    bundle_bytes, additions, oodle=oodle)
                                # v0.24.110: ensure output is DCX-wrapped at
                                # the .dcx mod path. If the splice came from
                                # a raw bundled source, patched is raw BND4
                                # — wrap it now.
                                if (mod_msg_bundle.lower().endswith('.dcx')
                                        and patched[:4] != b'DCX\x00'):
                                    from dcx import DCX as _DCX
                                    _wrap_t0 = time.time()
                                    patched_to_write = _DCX.compress_bytes(
                                        patched, compression=b'KRAK',
                                        oodle=oodle)
                                    _wrap_dt = time.time() - _wrap_t0
                                    print(f"  DCX-wrapping output "
                                          f"(raw BND4 → DCX, {_wrap_dt:.1f}s, "
                                          f"{len(patched):,} → "
                                          f"{len(patched_to_write):,} bytes)")
                                else:
                                    patched_to_write = patched
                                os.makedirs(os.path.dirname(mod_msg_bundle) or '.',
                                            exist_ok=True)
                                with open(mod_msg_bundle, 'wb') as _f:
                                    _f.write(patched_to_write)
                                _splice_dt = time.time() - _splice_t0
                                grew = len(patched_to_write) - len(bundle_bytes)
                                print(f"  Auto-spliced {len(additions)} name(s) "
                                      f"into NpcName.fmg → {mod_msg_bundle}")
                                print(f"  Bundle in ({('DCX' if _is_dcx else 'raw')}) "
                                      f"{len(bundle_bytes):,} → out "
                                      f"{len(patched_to_write):,} bytes "
                                      f"({grew:+,}) ({_splice_dt:.1f}s)")
                                splice_succeeded = True
                            except Exception as _se:
                                # v0.24.106: Phase 3 fallback re-patch handles
                                # this case below — no need for manual splice
                                # instructions any more.
                                import traceback as _tb
                                print(f"  FMG auto-splice FAILED: {_se}")
                                _tb.print_exc()
                        elif vanilla_msg_bundle or mod_msg_bundle:
                            print(f"  FMG auto-splice skipped: only one of "
                                  f"(Vanilla msg, Mod msg) is set — both required.")
                        else:
                            print(f"  FMG auto-splice skipped: Vanilla msg + "
                                  f"Mod msg bundles not configured in Folders.")

                        # v0.24.106 Phase 3: fallback re-patch when splice
                        # didn't complete. Re-runs the EMEVD patcher with
                        # `fallback_nameid` so cross-game / heterogeneous-
                        # squad bars display the fallback string (default
                        # "Crucible Knight and more") instead of "NPCName".
                        # Overwrites the Phase 1 output in patched_emevd and
                        # the compressed output in emevd_out_dir.
                        if not splice_succeeded and fallback_nameid is not None:
                            print(f"  Phase 3: re-patching EMEVDs with "
                                  f"fallback nameId {fallback_nameid} "
                                  f"(no FMG splice → safety net for {n_fmg} "
                                  f"cross-game bars)")
                            # v0.24.109: updated guidance. Vanilla / Mod
                            # msg paths are no longer user-settable; they
                            # derive from game_install + me3_package. If
                            # the vanilla file is missing, NR install
                            # likely isn't UXM-unpacked — that's the
                            # actual gating step for per-chr names.
                            print(f"    To get per-chr names instead, "
                                  f"UXM-unpack your NR install so")
                            print(f"    <NR install>/Game/msg/engUS/"
                                  f"item_dlc01.msgbnd.dcx exists on disk.")
                            try:
                                _fb_t0 = time.time()
                                healthbar_report = _apply_to_dir(
                                    emevd_dir=raw_emevd,
                                    output_dir=patched_emevd,
                                    spoiler_path=spoiler_path,
                                    chr_to_nameid_path=chr_to_nameid_path,
                                    fallback_nameid=fallback_nameid,
                                    exclude_files=hb_exclude,
                                )
                                emevd_compress_dir(patched_emevd,
                                                    emevd_out_dir, oodle)
                                # v0.24.x: re-mirror diagnostic artifacts
                                # after Phase 3, in case it overwrote the
                                # Phase 1 outputs with the fallback state.
                                for _diag_fname in ('fmg_additions.json',
                                                     'apply_report.json'):
                                    _diag_src = os.path.join(patched_emevd,
                                                              _diag_fname)
                                    if os.path.exists(_diag_src):
                                        try:
                                            shutil.copy(_diag_src,
                                                        os.path.join(out_dcx_dir,
                                                                     _diag_fname))
                                        except Exception:
                                            pass
                                _fb_dt = time.time() - _fb_t0
                                print(f"    Phase 3 complete "
                                      f"({_fb_dt:.1f}s); "
                                      f"{n_fmg} bars now display fallback "
                                      f"string.")
                                # Refresh the counters from the new report.
                                # n_fmg should be 0 after fallback re-patch
                                # since fallback returns same id every time
                                # (no new FMG entries needed).
                                n_files_ok = sum(1 for f in healthbar_report['files']
                                                 if f['status'] == 'ok')
                                n_rewrites = sum(f.get('rewrites', 0)
                                                 for f in healthbar_report['files'])
                            except Exception as _fb_e:
                                import traceback as _tb
                                print(f"  Phase 3 fallback re-patch FAILED: "
                                      f"{_fb_e}")
                                print(f"  Phase 1 output (with fresh "
                                      f"nameIds) is still in place. Cross-"
                                      f"game bars may display 'NPCName' "
                                      f"in-game without manual FMG splice.")
                                _tb.print_exc()
                    healthbar_status = (f'ok ({n_files_ok} files, {n_rewrites} rewrites, '
                                        f'{n_fmg} new FMG entries, '
                                        f'splice_succeeded={splice_succeeded if n_fmg else "n/a"})')
                except Exception as e:
                    import traceback as _tb
                    healthbar_status = f'failed: {e}'
                    print(f"  FAILED: {e}")
                    _tb.print_exc()

        # Inject healthbar_rewrite metadata into _spoilers.json so the
        # run record reflects what happened (matches walk_route_rewrite
        # precedent from Step 2a).
        spoiler_json_path = os.path.join(out_dcx_dir, '_spoilers.json')
        if os.path.exists(spoiler_json_path):
            try:
                import json as _json
                with open(spoiler_json_path, encoding='utf-8') as _f:
                    _spoiler_data = _json.load(_f)
                _spoiler_data.setdefault('_meta', {})['healthbar_rewrite'] = {
                    'status': healthbar_status,
                    'report': healthbar_report,
                    'engine': 'healthbar_inplace v0.24.0',
                }
                with open(spoiler_json_path, 'w', encoding='utf-8') as _f:
                    _json.dump(_spoiler_data, _f, indent=2, sort_keys=True)
            except Exception as _e:
                print(f"  WARN: could not inject healthbar metadata into spoilers: {_e}")


        if keep_intermediates:
            target = os.path.join(out_dcx_dir, '_intermediate')
            shutil.copytree(work_dir, target, dirs_exist_ok=True)
            print(f"Intermediate files kept at: {target}")
    finally:
        if not keep_intermediates:
            shutil.rmtree(work_dir, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(description='Batch DCX operations for NR rando.')
    sub = p.add_subparsers(dest='cmd', required=True)

    pd = sub.add_parser('decompress', help='Decompress all .msb.dcx in a folder')
    pd.add_argument('input_dir')
    pd.add_argument('output_dir')

    pc = sub.add_parser('compress', help='Compress all .msb in a folder to .msb.dcx')
    pc.add_argument('input_dir')
    pc.add_argument('output_dir')

    pr = sub.add_parser('rando', help='End-to-end pipeline: decompress, shuffle, recompress')
    pr.add_argument('input_dcx_dir', help='Folder of vanilla .msb.dcx (e.g. Game/map/mapstudio)')
    pr.add_argument('output_dcx_dir', help='Folder where shuffled .msb.dcx will be written')
    pr.add_argument('--seed', type=int, default=42)
    pr.add_argument('--mode', choices=['loose','strict'], default='loose')
    pr.add_argument('--keep-intermediates', action='store_true',
                    help='Keep the intermediate decompressed/shuffled folders for debugging')
    pr.add_argument('--emevd-out-dir',
                    help='Output directory for patched .emevd.dcx files '
                         '(typically <me3 profile>/<package>/event/).')

    pi = sub.add_parser('info', help='Print header info for one .dcx file')
    pi.add_argument('input_path')

    args = p.parse_args()

    if args.cmd == 'decompress':
        decompress_dir(args.input_dir, args.output_dir)
    elif args.cmd == 'compress':
        compress_dir(args.input_dir, args.output_dir)
    elif args.cmd == 'rando':
        rando_pipeline(args.input_dcx_dir, args.output_dcx_dir,
                        args.seed, args.mode, args.keep_intermediates,
                        emevd_out_dir=args.emevd_out_dir)
    elif args.cmd == 'info':
        # Reuse dcx.py's info command
        import dcx as dcx_mod
        sys.argv = ['dcx.py', 'info', args.input_path]
        dcx_mod.main()


if __name__ == '__main__':
    # Determinism guard — see oops_v3.py. Pin the hash seed before the
    # build runs so set/dict iteration (consumed by the shared seeded rng)
    # is reproducible; same --seed -> same layout. (No effect under
    # `python -m`; invoke by path.)
    import os as _os, sys as _sys
    if _os.environ.get('PYTHONHASHSEED') != '0':
        _os.environ['PYTHONHASHSEED'] = '0'
        _os.execv(_sys.executable, [_sys.executable, *_sys.argv])
    main()