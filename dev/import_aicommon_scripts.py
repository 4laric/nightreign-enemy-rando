#!/usr/bin/env python3
"""
import_aicommon_scripts.py
==========================

Stages ER's aicommon luabnd files (the SHARED AI library, not per-chr
battle scripts) into heritage_pack's script overlay. Companion to
import_heritage_ai_scripts.py — same target directory, same .dcx
convention, complementary content.

Background
----------

heritage_pack chrs need TWO layers of AI working:

  1. Per-chr battle.luabnd — the chr's combat AI module. Already
     handled by import_heritage_ai_scripts.py.

  2. SHARED aicommon library — Goal/Logic ID definitions, helper
     functions that every chr's battle script requires(). Lives in:

         script/aicommon.luabnd.dcx        (~120-170 lua files)
         script/aicommon_dlc01.luabnd.dcx  (~1-2 lua files, ER DLC1)
         script/aicommon_dlc02.luabnd.dcx  (~5-10 lua files, SOTE)

     Vanilla NR ships a SUBSET of ER's aicommon (~118 vs ER's ~169
     scripts; the deficit was characterized in
     diagnose_aicommon_gap.py). NR also ships NO dlc01/dlc02 variant
     at all, which causes silent-fail for SoTE chrs whose battle
     scripts `require()` SOTE-specific helpers.

This importer pulls those three files from ER source and stages them
into heritage_pack/script/. me3 loads heritage_pack's script/ on top
of vanilla NR's, so any aicommon file present there wins.

Replace vs additive
-------------------

aicommon is *replace*, not additive. There's no merging at the lua
level — me3 picks ONE aicommon.luabnd.dcx per name (vanilla NR's, or
heritage_pack's overlay). Importing ER's aicommon REPLACES NR's
aicommon wholesale. Because ER's aicommon is a strict superset of
NR's (audited via diagnose_aicommon_gap.py: every helper NR's
aicommon defines, ER's also defines), the replacement is safe — chrs
that worked under NR's aicommon continue to work under ER's, and chrs
that need ER-only helpers now work too.

The dlc01 and dlc02 variants are pure additions — NR ships nothing
under those names, so staging them in heritage_pack/script/ adds new
files rather than overriding existing ones.

Usage
-----

  python3 dev/import_aicommon_scripts.py \\
      --er-source /path/to/ER/script \\
      --heritage-overlay /path/to/heritage_pack/script \\
      [--variants base dlc01 dlc02]   # subset, default = all available
      [--dry-run]
      [--force]                       # overwrite without prompt
      [--decompress]                  # also leave .luabnd uncompressed
                                      #   next to the .dcx (for diffing)

  # OR — read straight from a packed ER install:

  python3 dev/import_aicommon_scripts.py \\
      --source-game "/path/to/ELDEN RING/Game" \\
      --heritage-overlay /path/to/heritage_pack/script

Validation
----------

After staging, run dev/diagnose_aicommon_gap.py to verify the staged
aicommon resolves the missing helpers a representative chr needed:

  python3 dev/diagnose_aicommon_gap.py \\
      --er-aicommon /path/to/ER/script/aicommon.luabnd.dcx \\
      --mod-aicommon /path/to/heritage_pack/script/aicommon.luabnd.dcx \\
      --chr-script /path/to/heritage_pack/script/521000_battle.luabnd.dcx

The gap should be empty (mod aicommon and ER aicommon report the same
file set), proving the replacement is complete.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Catalog of aicommon variants
# ---------------------------------------------------------------------------
#
# Each entry: variant_label -> (basename, severity, doc)
# severity matches chr_asset_resolver.SHARED_DEPS — "AI_REQUIRED" for the
# load-bearing files, plus what they unlock.

AICOMMON_VARIANTS = {
    'base': (
        'aicommon.luabnd',
        'AI_REQUIRED',
        'Core AI Goal/Logic library. Replaces vanilla NR\'s subset wholesale; '
        'ER ships a strict superset, so replacement is safe.',
    ),
    'dlc01': (
        'aicommon_dlc01.luabnd',
        'AI_REQUIRED',
        'ER DLC1 goal-table manifest. Tiny (~1-2 lua files). NR ships nothing '
        'under this name, so staging is purely additive.',
    ),
    'dlc02': (
        'aicommon_dlc02.luabnd',
        'AI_REQUIRED',
        'SOTE DLC2 goal-table manifest. ~5-10 lua files for Shadow of the '
        'Erdtree boss/enemy helpers (Bayle, Messmer, Romina, Putrescent '
        'Knight, etc.). NR ships nothing under this name; required for '
        'heritage SOTE chrs to find their AI helpers.',
    ),
}


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def find_source_file(er_dir: Path, basename: str) -> Path | None:
    """Look for basename.dcx or basename in ER source dir.

    Prefer .dcx (already-compressed — what me3 loads natively). Fall
    back to uncompressed .luabnd, in which case the staging step
    flags the file for recompression before deploy.
    """
    dcx_path = er_dir / f'{basename}.dcx'
    if dcx_path.is_file():
        return dcx_path
    plain_path = er_dir / basename
    if plain_path.is_file():
        return plain_path
    return None


def target_filename(source: Path) -> str:
    """me3 loads from script/ as .luabnd.dcx — preserve that suffix.

    Mirrors import_heritage_ai_scripts.target_filename so behaviour
    matches across the two importers.
    """
    name = source.name
    if name.endswith('.dcx'):
        return name
    # Uncompressed source: target name still gets the .dcx suffix
    # (the user will need to recompress before deploying — flagged in
    # the staging report).
    return f'{name}.dcx'


def _materialize_er_aicommon(er_game: Path, cache_root: Path | None = None) -> Path | None:
    """Read aicommon files straight from a packed ER install's archives.

    Mirrors import_heritage_ai_scripts._materialize_er_scripts pattern.
    Returns the cache's script/ subdir (usable as --er-source), or None
    if the ER archives can't be opened.
    """
    import os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from er_source import EldenRingSource
    except Exception:
        return None
    src = EldenRingSource(str(er_game))
    if not src.has_archive:
        return None
    # All three aicommon variants — script/ paths inside the archive
    rels = [f'/script/{basename}.dcx' for basename, _, _ in AICOMMON_VARIANTS.values()]
    if cache_root is None:
        cache_root = Path(_root) / '.er_cache'
    src.materialize(rels, str(cache_root))
    return cache_root / 'script'


# ---------------------------------------------------------------------------
# Hash audit (so the user knows when a stage replaces existing content)
# ---------------------------------------------------------------------------


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()[:12]


# ---------------------------------------------------------------------------
# Optional: decompress staged .dcx alongside (for diffing convenience)
# ---------------------------------------------------------------------------


def _try_decompress_alongside(dcx_path: Path) -> Path | None:
    """If the dcx module is importable, write the inflated .luabnd next
    to the .dcx for diffing convenience. Returns the inflated path or
    None on any failure (silent — this is best-effort).
    """
    import os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from dcx import DCX
    except Exception:
        return None
    try:
        raw = DCX.decompress_file(str(dcx_path))
    except Exception as e:
        # Oodle missing, format mismatch, etc. — non-fatal.
        return None
    out = dcx_path.with_suffix('')  # strip .dcx → .luabnd
    out.write_bytes(raw)
    return out


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------


def stage_aicommon(er_dir: Path,
                   overlay_dir: Path,
                   variants: list[str],
                   *,
                   dry_run: bool = False,
                   force: bool = False,
                   decompress: bool = False,
                   ) -> tuple[list[dict], list[str], list[str]]:
    """Returns (staged, missing, warnings).

    staged: list of dicts with keys (variant, source, target,
            replaces_hash, new_hash, decompressed) — one per file actually
            copied (or that *would* be copied under --dry-run).
    missing: variant labels whose source wasn't found in er_dir.
    warnings: human-readable warnings (uncompressed source, etc.).
    """
    staged = []
    missing = []
    warnings = []

    for variant in variants:
        basename, severity, _doc = AICOMMON_VARIANTS[variant]
        src = find_source_file(er_dir, basename)
        if src is None:
            missing.append(variant)
            continue

        tgt = overlay_dir / target_filename(src)
        replaces_hash = _hash(tgt) if tgt.exists() else None
        new_hash = _hash(src)

        if replaces_hash == new_hash:
            # File is byte-identical — nothing to do.
            staged.append({
                'variant': variant,
                'source': src,
                'target': tgt,
                'replaces_hash': replaces_hash,
                'new_hash': new_hash,
                'decompressed': None,
                'no_op': True,
            })
            continue

        if not src.name.endswith('.dcx'):
            warnings.append(
                f'{variant}: source is uncompressed ({src.name}); '
                f'recompress before deploy with WitchyBND or Yabber'
            )

        record = {
            'variant': variant,
            'source': src,
            'target': tgt,
            'replaces_hash': replaces_hash,
            'new_hash': new_hash,
            'decompressed': None,
            'no_op': False,
        }

        if not dry_run:
            if tgt.exists() and not force and replaces_hash:
                # Could prompt here, but interactive prompts in --dry-run
                # land paths are confusing. Stick to the convention used by
                # import_heritage_ai_scripts: just overwrite (shutil.copy2
                # does), and report what was replaced in the summary.
                pass
            shutil.copy2(src, tgt)
            if decompress:
                inflated = _try_decompress_alongside(tgt)
                if inflated is not None:
                    record['decompressed'] = inflated
                else:
                    warnings.append(
                        f'{variant}: --decompress requested but the dcx '
                        f'module / Oodle DLL was unavailable; staged the '
                        f'.dcx only'
                    )
        staged.append(record)

    return staged, missing, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Stage ER aicommon luabnd files into heritage_pack overlay.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--er-source', required=False, type=Path, default=None,
                        help="Path to unpacked vanilla ER script/ dir containing "
                             "aicommon[.dlc01|.dlc02].luabnd[.dcx] files")
    parser.add_argument('--source-game', type=Path, default=None,
                        help="Packed Elden Ring install dir (.../ELDEN RING/Game). "
                             "Reads the aicommon luabnds straight from ER's .bhd/.bdt "
                             "archives instead of an unpacked --er-source.")
    parser.add_argument('--heritage-overlay', required=True, type=Path,
                        help="Path to heritage_pack's script/ overlay dir "
                             "(target for staging)")
    parser.add_argument('--variants', nargs='+',
                        choices=sorted(AICOMMON_VARIANTS),
                        default=None,
                        help=f"Subset of variants to import (default: all available). "
                             f"Choices: {sorted(AICOMMON_VARIANTS)}")
    parser.add_argument('--dry-run', action='store_true',
                        help="Show plan without copying anything")
    parser.add_argument('--force', action='store_true',
                        help="Overwrite existing files without prompting "
                             "(NB: replaces vanilla NR's aicommon — this is "
                             "intentional and safe per the module docstring)")
    parser.add_argument('--decompress', action='store_true',
                        help="Also write an inflated .luabnd alongside each staged .dcx "
                             "(for diffing; requires the project's dcx module + Oodle DLL)")
    args = parser.parse_args()

    # Source resolution: --source-game wins by materializing into a cache.
    if args.source_game and args.er_source is None:
        cache_script = _materialize_er_aicommon(args.source_game)
        if cache_script is None:
            print(f"error: couldn't read the ER archives at {args.source_game}; "
                  "pass --er-source with an unpacked script/ dir instead.",
                  file=sys.stderr)
            return 2
        args.er_source = cache_script
        print(f"Read aicommon scripts from ER archives → {cache_script}")
    if args.er_source is None:
        print("error: pass --er-source (unpacked ER script/ dir) or --source-game "
              "(packed ER Game dir).", file=sys.stderr)
        return 2

    if not args.er_source.is_dir():
        print(f"error: ER source dir not found: {args.er_source}", file=sys.stderr)
        return 2
    if not args.heritage_overlay.is_dir():
        print(f"error: heritage_pack overlay dir not found: {args.heritage_overlay}",
              file=sys.stderr)
        return 2

    variants = args.variants or sorted(AICOMMON_VARIANTS)
    print(f"=== Import plan ({len(variants)} aicommon variant(s)) ===")
    if args.dry_run:
        print("(--dry-run: no files will be copied)\n")
    else:
        print(f"target: {args.heritage_overlay}\n")

    staged, missing, warnings = stage_aicommon(
        args.er_source, args.heritage_overlay, variants,
        dry_run=args.dry_run, force=args.force, decompress=args.decompress,
    )

    # Per-variant report
    for record in staged:
        v = record['variant']
        src, tgt = record['source'], record['target']
        if record.get('no_op'):
            print(f"  {v:6s} : already up-to-date  ({tgt.name}, sha256={record['new_hash']})")
        elif record['replaces_hash']:
            verb = "would replace" if args.dry_run else "replaced"
            print(f"  {v:6s} : {verb}  {tgt.name}")
            print(f"           old sha256={record['replaces_hash']} → new sha256={record['new_hash']}")
        else:
            verb = "would stage" if args.dry_run else "staged"
            print(f"  {v:6s} : {verb}  {src.name} → {tgt.name}")
            print(f"           new file, sha256={record['new_hash']}")
        if record.get('decompressed'):
            print(f"           also wrote: {record['decompressed'].name} "
                  "(inflated, for diffing)")

    if warnings:
        print(f"\n=== Warnings ===")
        for w in warnings:
            print(f"  {w}")

    if missing:
        print(f"\n=== Missing in ER source dir ({len(missing)}) ===")
        for v in missing:
            basename, _, _ = AICOMMON_VARIANTS[v]
            print(f"  {v}: {basename}[.dcx] not found in {args.er_source}")
        print("\nThese variants ship in ER but not in the ER source dir you supplied.")
        print("Check that --er-source points at the unpacked vanilla ER /script dir")
        print("(.../ELDEN RING/Game/script). For dlc01/dlc02, the game must include")
        print("the relevant DLC; --source-game on a base-game install won't have dlc02.")

    print(f"\n=== Summary ===")
    nochange = sum(1 for r in staged if r.get('no_op'))
    replaced = sum(1 for r in staged if r['replaces_hash'] and not r.get('no_op'))
    new = sum(1 for r in staged if not r['replaces_hash'])
    print(f"  Staged: {len(staged)} variant(s)")
    print(f"    new files:        {new}")
    print(f"    replaced:         {replaced}")
    print(f"    already current:  {nochange}")
    print(f"  Missing in source:  {len(missing)}")
    print(f"  Warnings:           {len(warnings)}")

    if args.dry_run:
        print("\n(dry-run — re-run without --dry-run to actually copy)")
        return 0

    print(f"\nNext steps:")
    print(f"  1. Repack heritage_pack via your normal build process")
    print(f"  2. Validate the gap is closed:")
    print(f"     python3 dev/diagnose_aicommon_gap.py \\")
    print(f"       --er-aicommon {args.er_source}/aicommon.luabnd.dcx \\")
    print(f"       --mod-aicommon {args.heritage_overlay}/aicommon.luabnd.dcx \\")
    print(f"       --chr-script {args.heritage_overlay}/521000_battle.luabnd.dcx")
    print(f"     Expected: 0 unmet requires (the staged aicommon is a strict")
    print(f"     superset of NR's, so the gap should be empty).")
    print(f"  3. Spot-check a heritage chr in-game that was previously")
    print(f"     standing-still: Spider Scorpion c5190, SoTE Troll c5390,")
    print(f"     Messmer Foot Soldier c5651 are good first targets.")

    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
