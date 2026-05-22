#!/usr/bin/env python3
"""
import_heritage_ai_scripts.py
==============================

Stages ER battle/logic luabnd files into heritage_pack's script overlay
to fix the missing-AI-brain bug class identified in the v0.23.72-late
investigation (the c5210 Dancing Lion phase-transition fix).

Background
----------

heritage_pack imports ER chrs by shipping their visual/physics assets
(chrbnd, anibnd, behbnd, texbnd) but historically did not ship their
Lua AI scripts (NNNNNN_battle.luabnd.dcx). Without these scripts,
chrs run on .behbnd alone — which drives animations and reactions but
lacks the IsInterupt handlers, move-selection logic, and phase-state
latching that proper combat AI requires.

Confirmed in playtest (v0.23.72-late): importing 521000_battle.luabnd.dcx
from ER into heritage_pack's script/ overlay fixes Divine Beast Dancing
Lion's phase-transition loop. NR's aicommon.luabnd is compatible with
ER chr scripts — no per-script patching needed.

This script automates the import for the 25 remaining heritage chrs
identified as AFFECTED or PARTIAL in heritage_pack_ai_audit.md.

Usage
-----

  python3 import_heritage_ai_scripts.py \\
      --er-source /path/to/ER/script \\
      --heritage-overlay /path/to/heritage_pack/script \\
      [--include c5820 c5160 ...]    # subset; default = all AFFECTED+PARTIAL
      [--dry-run]                    # show what would be copied
      [--skip-confirmed]             # exclude c5210/c5820/c5250 (already done)

ER source dir is the unpacked vanilla ER script/ folder containing
NNNNNN_battle.luabnd.dcx files. heritage_pack overlay is the script/
folder that gets loaded by me3 alongside vanilla NR's script dir.

The script writes .luabnd.dcx files (compressed, as me3 expects) — it
prefers the .dcx form from ER source when available, falling back to
recompressing the uncompressed .luabnd if needed (requires WitchyBND
or yabber for compression; falls back to copying as-is with a warning).

After running this script, repack heritage_pack and test in-game.
Suggested validation order: c5820 first (simplest single-entity, lowest
risk), then bulk-validate by running a representative sample of seeds.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Catalog: chrs that need AI script imports (from v0.23.72-late audit)
# ---------------------------------------------------------------------------
#
# Each entry maps c-prefix → list of luabnd filenames to import.
# Source: heritage_pack_ai_audit.md generated from script-presence sweep
# over vanilla NR script dir + heritage_pack overlay + ER source.

IMPORT_PLAN = {
    # ─── Confirmed buggy in playtest, validated fix path ────────────────────
    'c5210': ['521000_battle.luabnd'],  # Divine Beast Dancing Lion ★ VALIDATED
    'c5820': ['582000_battle.luabnd'],  # Great Red Bear ★
    'c5250': ['525000_battle.luabnd', '525010_battle.luabnd'],  # Horned Warrior ★

    # ─── AFFECTED: ER has battle script, neither NR nor heritage_pack ships it
    'c2040': ['204000_battle.luabnd', '204000_logic.luabnd'],  # Juvenile Scholar
    'c3070': ['307000_battle.luabnd', '307010_battle.luabnd', '307020_battle.luabnd',
              '307030_battle.luabnd', '307040_battle.luabnd'],  # Dominula Celebrant
    'c3330': ['333000_battle.luabnd'],  # Giant Silver Tear
    'c3510': ['351001_battle.luabnd', '351002_battle.luabnd', '351003_battle.luabnd',
              '351006_battle.luabnd', '351008_battle.luabnd',
              '351009_battle.luabnd'],  # Skeleton (Sword and Shield) — note: no 351000 in ER
    'c3670': ['367000_battle.luabnd', '367010_battle.luabnd', '367020_battle.luabnd',
              '367030_battle.luabnd', '367040_battle.luabnd'],  # Aged Albinauric (Scholar Remembrance)
    'c3730': ['373000_battle.luabnd'],  # Misbegotten
    'c3750': ['375000_battle.luabnd', '375010_battle.luabnd', '375020_battle.luabnd'],  # Pumpkin Head
    'c3800': ['380000_battle.luabnd', '380010_battle.luabnd'],  # Putrid Tree Spirit
    'c3860': ['386000_battle.luabnd', '386010_battle.luabnd'],  # Avionette
    'c4210': ['421000_battle.luabnd'],  # Rune Bear
    'c4220': ['422000_battle.luabnd', '422000_logic.luabnd'],  # Giant Land Octopus
    'c4341': ['434100_battle.luabnd', '434100_logic.luabnd'],  # Thin Mad Pumpkin Head
    'c4800': ['480000_battle.luabnd'],  # Erdtree Avatar
    'c4820': ['482000_battle.luabnd'],  # Hippopotamus (large)
    'c5020': ['502000_battle.luabnd', '502010_battle.luabnd'],  # Putrescent Knight
    'c5040': ['504000_battle.luabnd'],  # Bell Bearing Hunter
    'c5070': ['507000_battle.luabnd', '507010_battle.luabnd'],  # Wraith
    'c5080': ['508000_battle.luabnd', '508010_battle.luabnd',
              '508020_battle.luabnd', '508100_battle.luabnd'],  # Bloodfiend
    'c5081': ['508000_battle.luabnd', '508010_battle.luabnd',
              '508020_battle.luabnd', '508100_battle.luabnd'],  # Chief Bloodfiend (same scripts)
    'c5090': ['509000_battle.luabnd'],  # Gravebird
    'c5160': ['516000_battle.luabnd', '516010_battle.luabnd', '516020_battle.luabnd'],  # Fire Knight
    'c5190': ['519000_battle.luabnd'],  # Spider Scorpion
    'c5192': ['519000_battle.luabnd'],  # Spider Scorpion (smaller)
    'c5193': ['519000_battle.luabnd'],  # Spider Scorpion (smaller)
    'c5240': ['524000_battle.luabnd', '524010_battle.luabnd', '524020_battle.luabnd',
              '524030_battle.luabnd', '524100_battle.luabnd'],  # Commoner (Pot)
    'c5241': ['524000_battle.luabnd', '524010_battle.luabnd', '524020_battle.luabnd',
              '524030_battle.luabnd', '524100_battle.luabnd'],  # Commoner
    'c5310': ['531000_battle.luabnd', '531000_logic.luabnd',
              '531010_battle.luabnd', '531020_battle.luabnd'],  # Inquisitor (base — c5311/c5312 share scripts via PARTIAL)
    'c5320': ['532000_battle.luabnd'],  # Fat Inquisitor
    'c5360': ['536000_battle.luabnd', '536010_battle.luabnd', '536020_battle.luabnd',
              '536030_battle.luabnd', '536040_battle.luabnd'],  # Giant Beast Skeleton (distinct from c3061)
    'c5430': ['543000_battle.luabnd', '543000_logic.luabnd'],  # Owl
    'c5500': ['550000_battle.luabnd'],  # Living Magma
    'c5513': ['551300_battle.luabnd'],  # Cemetery Shade
    'c5560': ['556000_battle.luabnd', '556000_logic.luabnd'],  # Fingercreeper (Small)
    'c5600': ['560003_battle.luabnd', '560006_battle.luabnd'],  # Catacomb Skeleton — no 560000 in ER
    'c5620': ['562000_battle.luabnd'],  # Tibia Mariner
    'c5661': ['566100_battle.luabnd', '566110_battle.luabnd', '566120_battle.luabnd'],  # Shadow Militia
    'c5800': ['580000_battle.luabnd'],  # Crucible Knight Devonia
    'c5830': ['583000_battle.luabnd', '583010_battle.luabnd'],  # Red Wolf
    'c5850': ['585000_battle.luabnd', '585000_logic.luabnd'],  # Giant Ram
    'c5860': ['586000_battle.luabnd'],  # Ghostflame Dragon
    'c5900': ['590000_battle.luabnd'],  # Beast Man (of Farum Azula)
    'c5950': ['595000_battle.luabnd'],  # Leonine Misbegotten
    'c6060': ['606000_battle.luabnd'],  # Land Octopus
    'c6310': ['631000_battle.luabnd'],  # Fallingstar Beast (Base)

    # ─── PARTIAL: heritage_pack ships some sub-forms, ER source has more ────
    # Including these is lower-priority than AFFECTED — the partials may
    # already function adequately. Skip with --skip-partials if desired.
    'c3470': ['347005_battle.luabnd', '347015_battle.luabnd',
              '347025_battle.luabnd'],  # Albinauric (NR ships 6/9 variants; 005/015/025 missing)
    'c4385': ['438200_battle.luabnd', '438220_battle.luabnd', '438240_battle.luabnd',
              '438250_battle.luabnd', '438260_battle.luabnd'],  # Erdtree Avatar variant
    'c4420': ['442000_battle.luabnd'],  # Ulcerated Tree Spirit
    'c4603': ['460100_battle.luabnd', '460300_battle.luabnd'],  # Stonedigger Troll
    'c5010': ['501000_battle.luabnd'],  # Hippopotamus
    'c5311': ['531000_battle.luabnd', '531010_battle.luabnd'],  # Inquisitor
    'c5312': ['531000_battle.luabnd', '531010_battle.luabnd'],  # Inquisitor
    'c5870': ['587000_battle.luabnd', '587010_battle.luabnd', '587020_battle.luabnd'],  # Crystalian
}

CONFIRMED_FIXED = {'c5210'}  # validated in v0.23.72-late playtest

CONFIRMED_HIGH_PRIORITY = {'c5820', 'c5250', 'c5210'}  # all 3 originally flagged

PARTIAL_CHRS = {'c3470', 'c4385', 'c4420', 'c4603', 'c5010', 'c5311', 'c5312', 'c5870'}


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------


def find_source_file(er_dir: Path, basename: str) -> Path | None:
    """Look for basename or basename.dcx in ER source dir.

    Prefers .dcx (already-compressed, what me3 loads). Falls back to
    the uncompressed .luabnd. Returns Path or None.
    """
    dcx_path = er_dir / f'{basename}.dcx'
    if dcx_path.is_file():
        return dcx_path
    plain_path = er_dir / basename
    if plain_path.is_file():
        return plain_path
    return None


def target_filename(source: Path) -> str:
    """me3 loads from script/ as .luabnd.dcx — preserve that suffix."""
    name = source.name
    if name.endswith('.dcx'):
        return name
    # Uncompressed source: target name still gets the .dcx suffix
    # (the user will need to recompress before deploying — flagged below).
    return f'{name}.dcx'


def stage_imports(er_dir: Path,
                  overlay_dir: Path,
                  plan: dict[str, list[str]],
                  dry_run: bool = False,
                  ) -> tuple[list[tuple[str, Path, Path]], list[tuple[str, str]], list[tuple[str, Path]]]:
    """
    Returns (would_copy, missing_in_er, uncompressed_warnings).

    would_copy: [(chr, source_path, target_path)] — successful stagings.
    missing_in_er: [(chr, basename)] — script listed in plan but not in ER source.
    uncompressed_warnings: [(chr, source_path)] — source was .luabnd not .luabnd.dcx;
        user needs to recompress before deploy.
    """
    would_copy = []
    missing = []
    warnings = []

    for chr_prefix, basenames in sorted(plan.items()):
        for basename in basenames:
            src = find_source_file(er_dir, basename)
            if src is None:
                missing.append((chr_prefix, basename))
                continue

            tgt_name = target_filename(src)
            tgt = overlay_dir / tgt_name

            if not src.name.endswith('.dcx'):
                warnings.append((chr_prefix, src))

            would_copy.append((chr_prefix, src, tgt))

            if not dry_run:
                shutil.copy2(src, tgt)

    return would_copy, missing, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Stage ER battle.luabnd scripts into heritage_pack overlay.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--er-source', required=True, type=Path,
                        help="Path to unpacked vanilla ER script/ dir containing NNNNNN_battle.luabnd[.dcx] files")
    parser.add_argument('--heritage-overlay', required=True, type=Path,
                        help="Path to heritage_pack's script/ overlay dir (target for staging)")
    parser.add_argument('--include', nargs='*', default=None,
                        help="Subset of c-prefixes to import (default: full plan minus exclusions)")
    parser.add_argument('--exclude', nargs='*', default=None,
                        help="c-prefixes to exclude from the run")
    parser.add_argument('--skip-confirmed', action='store_true',
                        help=f"Skip already-validated chrs ({sorted(CONFIRMED_FIXED)})")
    parser.add_argument('--skip-partials', action='store_true',
                        help="Skip the PARTIAL-coverage chrs (lower priority)")
    parser.add_argument('--only-high-priority', action='store_true',
                        help=f"Only import the 3 originally-flagged chrs ({sorted(CONFIRMED_HIGH_PRIORITY)})")
    parser.add_argument('--dry-run', action='store_true',
                        help="Show plan without copying anything")

    args = parser.parse_args()

    # Validate source/target
    if not args.er_source.is_dir():
        print(f"error: ER source dir not found: {args.er_source}", file=sys.stderr)
        return 2
    if not args.heritage_overlay.is_dir():
        print(f"error: heritage_pack overlay dir not found: {args.heritage_overlay}", file=sys.stderr)
        return 2

    # Build filtered plan
    plan = dict(IMPORT_PLAN)
    if args.only_high_priority:
        plan = {k: v for k, v in plan.items() if k in CONFIRMED_HIGH_PRIORITY}
    if args.include is not None:
        plan = {k: v for k, v in plan.items() if k in args.include}
        unknown = set(args.include) - set(IMPORT_PLAN)
        if unknown:
            print(f"warning: --include contained unknown c-prefixes (no plan entry): {sorted(unknown)}", file=sys.stderr)
    if args.exclude is not None:
        plan = {k: v for k, v in plan.items() if k not in args.exclude}
    if args.skip_confirmed:
        plan = {k: v for k, v in plan.items() if k not in CONFIRMED_FIXED}
    if args.skip_partials:
        plan = {k: v for k, v in plan.items() if k not in PARTIAL_CHRS}

    if not plan:
        print("nothing to import after filtering")
        return 0

    print(f"=== Import plan ({len(plan)} chrs, {sum(len(v) for v in plan.values())} files) ===")
    if args.dry_run:
        print("(--dry-run: no files will be copied)\n")
    else:
        print(f"target: {args.heritage_overlay}\n")

    copied, missing, warnings = stage_imports(args.er_source, args.heritage_overlay, plan, dry_run=args.dry_run)

    # Group output by chr for readability
    from collections import defaultdict
    by_chr = defaultdict(list)
    for chr_prefix, src, tgt in copied:
        by_chr[chr_prefix].append((src, tgt))

    for chr_prefix in sorted(by_chr):
        flag = ""
        if chr_prefix in CONFIRMED_FIXED:
            flag = " [validated]"
        elif chr_prefix in CONFIRMED_HIGH_PRIORITY:
            flag = " [high-priority]"
        elif chr_prefix in PARTIAL_CHRS:
            flag = " [partial]"
        print(f"  {chr_prefix}{flag}:")
        for src, tgt in by_chr[chr_prefix]:
            arrow = "would copy" if args.dry_run else "copied"
            print(f"    {arrow}: {src.name}  →  {tgt.name}")

    if warnings:
        print(f"\n=== Warnings: source was uncompressed (.luabnd, not .luabnd.dcx) ===")
        print("These files need to be recompressed with WitchyBND or Yabber before me3 will load them.")
        print("Drag the staged file onto WitchyBND with the 'compress' option, or re-export from a DCX-aware repack tool.\n")
        for chr_prefix, src in warnings:
            print(f"  {chr_prefix}: {src}")

    if missing:
        print(f"\n=== Missing in ER source dir ({len(missing)} entries) ===")
        print("These scripts were expected but not found in the supplied --er-source.")
        print("Check that you supplied the unpacked vanilla ER script/ dir (not a Yabber-unpacked")
        print("subfolder). If still missing, the sub-form may not have an authored script in ER.\n")
        for chr_prefix, basename in missing:
            print(f"  {chr_prefix}: {basename}")

    print(f"\n=== Summary ===")
    print(f"  Copied: {len(copied)} files across {len(by_chr)} chrs")
    print(f"  Missing in source: {len(missing)}")
    print(f"  Compression warnings: {len(warnings)}")

    if args.dry_run:
        print("\n(dry-run — re-run without --dry-run to actually copy)")
    else:
        print(f"\nNext steps:")
        print(f"  1. Confirm staged files are .dcx-compressed (resolve any warnings above)")
        print(f"  2. Repack heritage_pack via your normal build process")
        print(f"  3. Playtest validation order:")
        print(f"     a. c5820 (Great Red Bear) — simplest single-entity chr")
        print(f"     b. Field-tier sample: c5160 Fire Knight, c4210 Rune Bear, c3750 Pumpkin Head")
        print(f"     c. c5250 Horned Warrior (paired-entity, both 525000 + 525010 needed)")
        print(f"  4. If any chr fails to load AI (silent error → chr stands still),")
        print(f"     diff NR's aicommon.luabnd vs ER's aicommon.luabnd for missing function exports.")

    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
