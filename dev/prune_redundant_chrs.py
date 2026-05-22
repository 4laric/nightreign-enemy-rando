"""prune_redundant_chrs.py — remove chr/script overlays that duplicate vanilla NR.

Why this exists
===============
Mod Engine 3 (me3) merges files across mod profiles and the vanilla game
install with a fall-through rule: if a file exists in the profile's chr/
directory, that copy is used; otherwise the vanilla NR file at the game
install's chr/ is used.

The rando's chr-import pipeline historically overlaid asset bundles for
every chr it placed, including chrs that exist in vanilla NR (the import
was originally designed for heritage chrs imported from Elden Ring).
This created a partial-overlay bug class: the rando ships some files for
a chr (e.g., chrbnd + anibnd + battle.luabnd) but not all (missing
logic.luabnd, missing texbnd, etc.). When the engine tries to use a
partial overlay, it loads what's there and then null-derefs trying to
find the missing pieces.

Concrete case: c4161 Stray. Vanilla NR has c4161 in its chr/ folder with
all files present. The rando profile overlaid c4161.chrbnd.dcx,
c4161_l.texbnd.dcx, c4161.anibnd.dcx, c4161.behbnd.dcx, and
416100_battle.luabnd.dcx — but NOT 416100_logic.luabnd.dcx. Result: when
a Stray spawned and the engine tried to evaluate its AI, the missing
logic.luabnd caused a null-deref CTD. (May 2026 playtest, Stray family
freeze v0.20.36-era issue rediscovered with new symptoms.)

What this tool does
===================
For each c-prefix overlaid in the rando profile's chr/ folder that ALSO
exists in vanilla NR's chr/ folder: delete all the overlaid files for
that c-prefix (chr files and matching script files). This forces the
engine to use vanilla NR's complete file set, eliminating partial-
overlay crashes.

Heritage-imported chrs (those present in the profile but NOT in vanilla
NR, e.g. Elden Ring imports like c1310) are left untouched — they need
the overlay to exist at all.

The tool is read-only by default (`dry_run=True`); call with
`dry_run=False` to actually delete.

Run via the GUI's chr inventory tab. Or standalone for scripted use:

    from dev.prune_redundant_chrs import prune_redundant_chrs
    report = prune_redundant_chrs(
        profile_root='/path/to/me3/profiles/onlyrando/nrando',
        nr_install_root='/path/to/Nightreign install',
        dry_run=False,
    )
    print(report.summary())
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from heritage_chr_import import (   # noqa: E402
    list_chr_prefixes,
    list_files_for_prefix,
    list_script_files_for_prefix,
    cp_to_script_prefix,
)


@dataclass
class PruneReport:
    """What the prune did (or would do, in dry-run)."""

    profile_chr_dir: str = ""
    profile_script_dir: Optional[str] = None
    nr_chr_dir: str = ""
    nr_script_dir: Optional[str] = None

    # c-prefixes in profile that ALSO exist in vanilla NR. These are the
    # pruning candidates.
    redundant_cps: list[str] = field(default_factory=list)
    # c-prefixes in profile that DON'T exist in vanilla NR. Left alone.
    heritage_cps: list[str] = field(default_factory=list)

    # Per-cp file lists actually pruned (or that would be pruned)
    pruned_files: dict[str, list[str]] = field(default_factory=dict)
    pruned_script_files: dict[str, list[str]] = field(default_factory=dict)

    # Counts for quick summary
    redundant_count: int = 0
    heritage_count: int = 0
    deleted_file_count: int = 0
    deleted_script_count: int = 0

    dry_run: bool = True
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        mode = "DRY-RUN (no files deleted)" if self.dry_run else "DELETED"
        lines.append(f"=== Prune redundant chrs — {mode} ===")
        lines.append(f"Profile chr/:  {self.profile_chr_dir}")
        if self.profile_script_dir:
            lines.append(f"Profile script/: {self.profile_script_dir}")
        lines.append(f"Vanilla NR chr/: {self.nr_chr_dir}")
        if self.nr_script_dir:
            lines.append(f"Vanilla NR script/: {self.nr_script_dir}")
        lines.append("")
        lines.append(f"Redundant c-prefixes (in profile AND vanilla NR): "
                     f"{self.redundant_count}")
        lines.append(f"Heritage c-prefixes (in profile only, NOT pruned): "
                     f"{self.heritage_count}")
        if self.heritage_cps:
            preview = ', '.join(self.heritage_cps[:10])
            more = f' (+{len(self.heritage_cps) - 10} more)' if len(self.heritage_cps) > 10 else ''
            lines.append(f"  Heritage chrs preserved: {preview}{more}")
        lines.append("")
        action_word = "Would delete" if self.dry_run else "Deleted"
        lines.append(f"{action_word} {self.deleted_file_count} chr files "
                     f"+ {self.deleted_script_count} script files")
        if self.errors:
            lines.append("")
            lines.append(f"Errors ({len(self.errors)}):")
            for e in self.errors[:10]:
                lines.append(f"  {e}")
        return "\n".join(lines)


def prune_redundant_chrs(
    profile_chr_dir: str,
    nr_chr_dir: str,
    profile_script_dir: Optional[str] = None,
    nr_script_dir: Optional[str] = None,
    dry_run: bool = True,
) -> PruneReport:
    """Prune chr/ overlays that duplicate vanilla NR.

    Args:
        profile_chr_dir: me3 profile's chr/ folder. The folder whose
            redundant files we delete (or list, in dry-run).
        nr_chr_dir: vanilla NR's chr/ folder. Used as the reference
            for "what's already in vanilla."
        profile_script_dir: me3 profile's script/ folder. Script files
            for pruned chrs are also pruned. Optional — if None or
            missing, scripts are not touched.
        nr_script_dir: vanilla NR's script/ folder. Used to confirm
            vanilla has the script files for the c-prefix before
            removing the profile's overlay. Optional.
        dry_run: When True (default), no files are deleted. The report
            shows what would be deleted.

    Returns:
        A PruneReport describing what was found and what was (or
        would be) deleted.
    """
    rep = PruneReport(
        profile_chr_dir=profile_chr_dir,
        profile_script_dir=profile_script_dir,
        nr_chr_dir=nr_chr_dir,
        nr_script_dir=nr_script_dir,
        dry_run=dry_run,
    )

    if not os.path.isdir(profile_chr_dir):
        rep.errors.append(f"Profile chr/ not found: {profile_chr_dir}")
        return rep
    if not os.path.isdir(nr_chr_dir):
        rep.errors.append(f"Vanilla NR chr/ not found: {nr_chr_dir}")
        return rep

    profile_cps = list_chr_prefixes(profile_chr_dir)
    nr_cps = list_chr_prefixes(nr_chr_dir)

    redundant = sorted(profile_cps & nr_cps)
    heritage = sorted(profile_cps - nr_cps)
    rep.redundant_cps = redundant
    rep.heritage_cps = heritage
    rep.redundant_count = len(redundant)
    rep.heritage_count = len(heritage)

    # For each redundant c-prefix, list (and optionally delete) its
    # chr files and matching script files.
    for cp in redundant:
        # ─── chr files ───
        chr_files = list_files_for_prefix(profile_chr_dir, cp)
        rep.pruned_files[cp] = chr_files
        for fname in chr_files:
            fpath = os.path.join(profile_chr_dir, fname)
            if dry_run:
                rep.deleted_file_count += 1
            else:
                try:
                    os.remove(fpath)
                    rep.deleted_file_count += 1
                except OSError as e:
                    rep.errors.append(f"Failed to delete {fpath}: {e}")

        # ─── script files ───
        # Only prune scripts if profile has them AND vanilla NR has
        # them — partial deletion (e.g., delete profile's logic.luabnd
        # when vanilla doesn't have one) would create a different
        # asset gap.
        if not profile_script_dir or not os.path.isdir(profile_script_dir):
            continue

        profile_scripts = list_script_files_for_prefix(profile_script_dir, cp)
        if not profile_scripts:
            continue

        # If we have an NR script dir, verify NR has the same chr's
        # scripts before pruning. If we don't have an NR script dir,
        # conservatively skip (don't prune scripts blindly).
        if nr_script_dir and os.path.isdir(nr_script_dir):
            nr_scripts = set(list_script_files_for_prefix(nr_script_dir, cp))
            # Only prune the profile scripts whose counterpart exists in
            # vanilla NR. (If profile ships e.g. 416100_battle.luabnd
            # but vanilla NR doesn't have it, deleting the profile copy
            # would leave a gap.)
            prunable = [f for f in profile_scripts if f in nr_scripts]
        else:
            # No NR script dir provided — can't verify safety, skip.
            prunable = []

        rep.pruned_script_files[cp] = prunable
        for fname in prunable:
            fpath = os.path.join(profile_script_dir, fname)
            if dry_run:
                rep.deleted_script_count += 1
            else:
                try:
                    os.remove(fpath)
                    rep.deleted_script_count += 1
                except OSError as e:
                    rep.errors.append(f"Failed to delete {fpath}: {e}")

    return rep


def main():
    """Standalone CLI for the prune. Run from the project root:

        python -m dev.prune_redundant_chrs --profile <path> --nr <path> [--apply]
    """
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--profile', required=True,
                     help="me3 profile mod root (chr/ and script/ are subdirs)")
    ap.add_argument('--nr', required=True,
                     help="Vanilla Nightreign install root")
    ap.add_argument('--apply', action='store_true',
                     help="Actually delete files (default is dry-run).")
    args = ap.parse_args()

    profile_chr = os.path.join(args.profile, 'chr')
    profile_script = os.path.join(args.profile, 'script')
    nr_chr = os.path.join(args.nr, 'chr')
    nr_script = os.path.join(args.nr, 'script')

    rep = prune_redundant_chrs(
        profile_chr_dir=profile_chr,
        nr_chr_dir=nr_chr,
        profile_script_dir=profile_script if os.path.isdir(profile_script) else None,
        nr_script_dir=nr_script if os.path.isdir(nr_script) else None,
        dry_run=not args.apply,
    )
    print(rep.summary())
    if args.apply:
        print("\n(Files actually deleted.)")
    else:
        print("\n(Dry-run. Re-run with --apply to delete.)")


if __name__ == '__main__':
    main()
