"""pipeline.py — End-to-end healthbar patcher byte editor.

v0.24.0-dev. The shippable entry point.

CONTRACT: this module takes already-decompressed .emevd bytes and
returns patched .emevd bytes. It does NOT touch DCX wrapping. The
caller is expected to be dcx_batch.py (or the future emevd-specific
sister functions there), which already has working Oodle integration
in production for the MSB pipeline.

Two ways callers can use this:

  HIGH-LEVEL — operate on a directory of .emevd files:
    apply_to_dir(emevd_dir, output_dir, spoiler_path, chr_to_nameid_path)
    Reads .emevd files from emevd_dir, writes patched .emevd files to
    output_dir. dcx_batch is responsible for decompressing into
    emevd_dir and compressing out of output_dir.

  LOW-LEVEL — operate on raw bytes (one file at a time):
    patched_raw, decisions, n_edits, n_callsites = patch_emevd_bytes(
        raw, spoiler_entity_map=..., chr_catalog=..., file_id=...,
        fmg_id_allocator=...)
    Convenient for tests and for stream-style integration where
    dcx_batch is decompressing/compressing in-memory.

Both produce the same apply_report.json + fmg_additions.json side
outputs when given an output dir.

Integration plan for dcx_batch.py (v0.24.0):

    # in dcx_batch.rando_pipeline, after the MSB compress step:
    if healthbar_rewrite_enabled:
        # Sister of decompress_dir, EMEVD edition. (~10 lines, mostly
        # a copy of decompress_dir with the .msb.dcx filter changed
        # to .emevd.dcx.)
        emevd_decompress_dir(vanilla_emevd_dcx_dir, raw_emevd_tmp_dir)

        # New pass, runs in pure-Python on raw bytes:
        from healthbar_inplace.pipeline import apply_to_dir
        apply_to_dir(
            emevd_dir=raw_emevd_tmp_dir,
            output_dir=patched_emevd_tmp_dir,
            spoiler_path=spoiler_path,
            chr_to_nameid_path=chr_catalog_path,
        )

        # Sister of compress_dir.
        emevd_compress_dir(patched_emevd_tmp_dir, out_dcx_dir)

The patcher's runtime cost is dominated by parse + extract over the
~200 EMEVD corpus. Single-threaded estimate based on file sizes:
common_func is ~700 KB, parses + walks in tens of ms; map files are
mostly tiny stubs. End-to-end on the full corpus: comfortably under
a second. Doesn't need parallelization unless a profile says otherwise.
"""

import json
import os
import sys

from emevd import EMEVD, extract_healthbar_callsites, rewrite_many
from rewriter import (
    decide_rewrites, make_fmg_allocator, compute_byte_edits,
    load_spoiler_entity_map, load_spoiler_entity_map_by_map,
    decisions_to_summary, DEFAULT_FMG_ID_BASE,
    load_title_pool,
)


# Files we know to contain healthbar callsites per the .js audit. Used
# as a hint when scanning a directory. The pipeline is robust to extra
# or missing files (it skips files with no callsites silently and
# reports missing files in apply_report.json), so this isn't load-
# bearing — it's a documentation aid for what gets touched.
DEFAULT_PATCH_FILES = [
    # Night Boss arenas (N1 + N2 anchors per nightlord_pools.json)
    'm47_70_00_00.emevd', 'm48_20_00_00.emevd', 'm48_40_00_00.emevd',
    'm48_50_00_00.emevd', 'm48_60_00_00.emevd', 'm48_80_00_00.emevd',
    'm48_90_00_00.emevd', 'm49_10_00_00.emevd', 'm49_17_00_00.emevd',
    'm49_18_00_00.emevd', 'm49_19_00_00.emevd', 'm49_20_00_00.emevd',
    'm49_21_00_00.emevd', 'm49_23_00_00.emevd', 'm49_24_00_00.emevd',
    'm49_25_00_00.emevd', 'm49_26_00_00.emevd', 'm49_27_00_00.emevd',
    'm49_28_00_00.emevd', 'm49_29_00_00.emevd',
    # Encampment / cathedral / dense field tiles
    'm32_00_00_00.emevd', 'm32_10_00_00.emevd', 'm32_20_00_00.emevd',
    'm34_00_00_00.emevd', 'm34_10_00_00.emevd', 'm34_20_00_00.emevd',
    'm34_30_00_00.emevd',
    'm38_00_00_00.emevd', 'm38_10_00_00.emevd',
    # Overworld dense cells
    'm60_43_37_00.emevd', 'm60_43_37_10.emevd', 'm60_43_37_20.emevd',
]


# Files that DEFINE the healthbar handlers (90015000/007/021/023/026/406)
# rather than CALL them. The rewriter targets InitializeCommonEvent
# callsites, all of which live in map-specific .emevd files. By design
# these files have 0 callsites and produce 0 edits — but the
# "always write to output_dir" semantics below would still send their
# vanilla bytes through, clobbering any user-maintained overlay
# (e.g. the bundled patched_emevd/common_func.emevd.dcx, which carries
# death_timeout / permissive_boss_wake / permissive_spawn_emerge /
# disable_corpse_collision / boss_reward_inject). Skip them in the
# default scan so the overlay survives the downstream dcx_batch
# recompression (which is purely additive — see audit in v0.24.x).
HANDLER_DEFINITION_FILES = frozenset({
    'common_func.emevd',
    'common.emevd',
})


def patch_emevd_bytes(
    raw: bytes,
    *,
    spoiler_entity_map: dict,
    chr_catalog: dict,
    file_id: str,
    fmg_id_allocator,
    title_pool: list = None,
    seed: int = None,
    compose_probability: float = 0.5,
    compose_show_arrow: bool = False,
) -> tuple:
    """Patch a single .emevd in memory.

    Returns (new_raw, decisions_list, n_byte_edits, n_callsites_seen).

    new_raw is identical to raw if no edits were needed. decisions_list
    is the per-callsite rationale the GUI can render. n_byte_edits is
    a quick "did anything actually change" count. n_callsites_seen is
    how many healthbar callsites the parser found in this file
    (regardless of whether any got rewritten) — used by the dcx_batch
    summary to distinguish "parser found nothing" from "found callsites
    but no swaps changed anything".

    v0.24.107: title_pool + seed + compose_probability thread the fun-
    rename feature through to decide_rewrites. Pass title_pool=None to
    disable composition entirely.

    v0.24.x: compose_show_arrow toggles the "{original} → {replacement}, "
    prefix in composed names (debug mode). Default off."""
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr=spoiler_entity_map,
        chr_to_vanilla_name_id=chr_catalog,
        file_id=file_id,
        fmg_id_allocator=fmg_id_allocator,
        title_pool=title_pool,
        seed=seed,
        compose_probability=compose_probability,
        compose_show_arrow=compose_show_arrow,
    )
    edits = compute_byte_edits(decisions, callsites)
    if not edits:
        return raw, decisions, 0, len(callsites)
    new_raw = rewrite_many(raw, edits)
    return new_raw, decisions, len(edits), len(callsites)


def apply_to_dir(
    *,
    emevd_dir: str,
    output_dir: str,
    spoiler_path: str,
    chr_to_nameid_path: str,
    fmg_id_base: int = DEFAULT_FMG_ID_BASE,
    fallback_nameid: int = None,
    files_to_patch=None,
    exclude_files=None,
    title_pool_path: str = None,
    seed: int = None,
    compose_probability: float = 0.5,
    compose_show_arrow: bool = False,
):
    """Read .emevd files from emevd_dir, write patched .emevd files
    to output_dir. The caller (dcx_batch) handles decompression into
    emevd_dir and recompression out of output_dir.

    v0.24.13: when `fallback_nameid` is an int, fresh-allocation and
    heterogeneous-squad cases reuse that vanilla nameId instead of
    allocating new IDs. Skips the FMG splice dependency at the cost of
    losing per-boss accuracy for ~50/158 cross-game cases. See
    `make_fmg_allocator` docstring.

    v0.24.107: when `title_pool_path` is set AND `seed` is provided AND
    `fallback_nameid` is None (Phase 1 of the splice-with-fallback flow),
    each unified-prefix callsite rolls a deterministic `compose_probability`
    gate. Hits get a composed mashup name from the title pool ("Mushroom
    Dog, Consort of Miquella"); misses fall through to the normal
    reuse_vanilla / fresh_allocation paths. The Phase 3 fallback re-patch
    passes title_pool_path=None implicitly (fallback returns one nameId
    for everything, no composition needed).

    v0.24.x: `compose_show_arrow` (default False) toggles a debug mode
    that prepends "{vanilla_chr_name} → {new_chr_name}, " before the
    composed title, e.g. "Tree Sentinel → Tibia Mariner, of the Boreal
    Valley". Useful for verifying which vanilla slot a chr came from
    when triaging spoiler issues. Off by default — bars render the new
    chr name plus title only.

    v0.26.16: `exclude_files` is a set of .emevd filenames to drop from
    the patch list entirely — not parsed, not written to output_dir. The
    caller uses this to keep specific arenas byte-vanilla; with the file
    absent from output_dir, dcx_batch's recompress step never produces a
    modded copy and me3 serves the vanilla emevd. Used for the night-boss
    arenas when test-mode arenas are off.
    """
    # v0.27.43: load the spoiler keyed BY MAP. NR reuses entity_ids across
    # overworld map variations (m60_XX_YY_00/_10/_20, ...); a single global
    # {eid: chr} map collapses them last-write-wins, mislabeling every
    # healthbar in a non-last variation. Each .emevd below resolves its
    # entities against its OWN map's sub-dict.
    spoiler_by_map = load_spoiler_entity_map_by_map(spoiler_path)
    with open(chr_to_nameid_path) as f:
        chr_catalog = json.load(f)

    # v0.24.107: load title pool if path is set. Compose is only active
    # when (a) we have titles, (b) we have a seed, and (c) we're in
    # Phase 1 (fallback_nameid is None — otherwise the allocator returns
    # the fallback id for everything and composition would be wasted).
    title_pool = None
    if title_pool_path and seed is not None and fallback_nameid is None:
        try:
            title_pool = load_title_pool(title_pool_path)
        except (FileNotFoundError, ValueError) as e:
            print(f"  WARN: title_pool load failed ({e}); "
                  f"compose disabled for this run")
            title_pool = None

    allocator, fmg_table_fn = make_fmg_allocator(
        base=fmg_id_base, fallback_id=fallback_nameid)

    os.makedirs(output_dir, exist_ok=True)

    if files_to_patch is None:
        # Default: scan emevd_dir for any .emevd file; broad net.
        # DEFAULT_PATCH_FILES is documentation, not an enforcement set.
        # HANDLER_DEFINITION_FILES are excluded — they have 0 callsites by
        # design (they define the handlers the callsites invoke). Excluding
        # them keeps the user's hand-patched common_func overlay alive.
        # If a caller passes files_to_patch explicitly, that list is
        # respected as-is — they've opted in deliberately.
        files_to_patch = sorted(
            f for f in os.listdir(emevd_dir)
            if f.endswith('.emevd') and f not in HANDLER_DEFINITION_FILES
        )

    # v0.26.16: caller-supplied vanilla-preserve set. Files named here are
    # dropped from the patch list entirely — not parsed, not written to
    # output_dir. dcx_batch passes the 25 night-boss arenas when test-mode
    # arenas are off; with the files absent from output_dir they are never
    # recompressed into the mod event/ dir, so me3 serves the vanilla emevd.
    excluded_reports = []
    if exclude_files:
        _excluded = [f for f in files_to_patch if f in exclude_files]
        files_to_patch = [f for f in files_to_patch if f not in exclude_files]
        excluded_reports = [
            {'file': f, 'status': 'skipped_preserved_vanilla', 'rewrites': 0}
            for f in _excluded
        ]

    per_file_reports = list(excluded_reports)
    for fname in files_to_patch:
        in_path = os.path.join(emevd_dir, fname)
        if not os.path.exists(in_path):
            per_file_reports.append({
                'file': fname, 'status': 'skipped_not_found', 'rewrites': 0,
            })
            continue
        with open(in_path, 'rb') as f:
            raw = f.read()
        # v0.27.43: resolve THIS file's healthbar entities against only its
        # own map's placements. fname is e.g. 'm60_42_36_00.emevd' → mapcode
        # 'm60_42_36_00', matching the spoiler's `map` (minus '.msb'). Files
        # with no randomized entities (or non-map files) get an empty dict →
        # every callsite stays 'unchanged' (vanilla), which is correct.
        _mc = os.path.splitext(fname)[0]
        file_spoiler = spoiler_by_map.get(_mc, {})
        try:
            new_raw, decisions, n_edits, n_callsites = patch_emevd_bytes(
                raw,
                spoiler_entity_map=file_spoiler,
                chr_catalog=chr_catalog,
                file_id=fname,
                fmg_id_allocator=allocator,
                title_pool=title_pool,
                seed=seed,
                compose_probability=compose_probability,
                compose_show_arrow=compose_show_arrow,
            )
        except Exception as e:
            # v0.24.0: pass-through on parse failure. Better to ship
            # the vanilla bytes through to the mod event/ dir than to
            # drop the file entirely — the compress step would then be
            # missing files and the game would silently fall back to
            # the install's event/ which may not have other patches
            # (timeout_v2 wiring etc.) applied.
            new_raw = raw
            decisions = []
            n_edits = 0
            n_callsites = 0
            with open(os.path.join(output_dir, fname), 'wb') as f:
                f.write(new_raw)
            per_file_reports.append({
                'file': fname, 'status': f'parse_failed (passed through unmodified): {e}',
                'rewrites': 0,
                'callsites_seen': 0,
            })
            continue
        # Always write to output_dir, even if unchanged. That way
        # dcx_batch can blindly recompress everything in output_dir
        # without tracking which files changed vs not.
        out_path = os.path.join(output_dir, fname)
        with open(out_path, 'wb') as f:
            f.write(new_raw)
        # v0.24.1: distinguish three terminal states clearly:
        #   'ok'             — callsites found, edits applied
        #   'unchanged'      — callsites found, but no edits needed
        #                       (every swap mapped to same vanilla nameId
        #                        or entity not in spoiler)
        #   'no_callsites'   — parser found 0 healthbar callsites in the
        #                       file. Either the file genuinely has none
        #                       (e.g. hub maps), or the parser missed them.
        if n_edits:
            status = 'ok'
        elif n_callsites:
            status = 'unchanged'
        else:
            status = 'no_callsites'
        per_file_reports.append({
            'file': fname,
            'status': status,
            'rewrites': n_edits,
            'callsites_seen': n_callsites,
            'summary': decisions_to_summary(decisions),
        })

    # Side outputs: FMG additions + apply report
    fmg_table = fmg_table_fn()
    fmg_additions_path = os.path.join(output_dir, 'fmg_additions.json')
    with open(fmg_additions_path, 'w') as f:
        json.dump({str(k): v for k, v in fmg_table.items()},
                  f, indent=2, sort_keys=True)

    apply_report = {
        'version': 'healthbar_inplace v0.24.0-dev',
        'spoiler': spoiler_path,
        'fmg_id_base': fmg_id_base,
        'fmg_additions_count': len(fmg_table),
        'fmg_additions_path': fmg_additions_path,
        'files': per_file_reports,
    }
    report_path = os.path.join(output_dir, 'apply_report.json')
    with open(report_path, 'w') as f:
        json.dump(apply_report, f, indent=2, sort_keys=True)
    return apply_report


def main():
    """CLI entry — useful for manual runs / dcx-less testing where
    you've already decompressed the .emevd files by hand."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spoiler', required=True)
    ap.add_argument('--in-emevd', required=True,
                    help='Directory of decompressed .emevd files (NOT .dcx). '
                         'dcx_batch handles the .dcx wrap/unwrap in production.')
    ap.add_argument('--out-emevd', required=True)
    ap.add_argument('--chr-nameid', required=True,
                    help='Path to chr_to_nameid.json from prep_demo BUILD-CATALOG')
    ap.add_argument('--fmg-id-base', type=int, default=DEFAULT_FMG_ID_BASE)
    args = ap.parse_args()

    rep = apply_to_dir(
        emevd_dir=args.in_emevd,
        output_dir=args.out_emevd,
        spoiler_path=args.spoiler,
        chr_to_nameid_path=args.chr_nameid,
        fmg_id_base=args.fmg_id_base,
    )
    n_ok = sum(1 for f in rep['files'] if f['status'] == 'ok')
    n_rewrites = sum(f.get('rewrites', 0) for f in rep['files'])
    print(f"Patched {n_ok} files, {n_rewrites} healthbar rewrites total.")
    print(f"FMG additions: {rep['fmg_additions_count']} new nameIds "
          f"-> {rep['fmg_additions_path']}")


if __name__ == "__main__":
    main()  