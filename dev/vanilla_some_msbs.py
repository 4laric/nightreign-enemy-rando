#!/usr/bin/env python3
"""vanilla_some_msbs.py — Revert specific MSBs to vanilla in a shuffled output.

For diagnosing non-deterministic Limveld load CTDs. The engine output is
deterministic, but Limveld procedurally composes m60_xx chunks at session
start — different sessions roll different rotation variants. If only some
sessions CTD, one specific variant is the trigger; this tool helps narrow
down which.

Workflow:
  1. Run the regular shuffle to produce <output_dir> (e.g. shuffled_msbs/).
  2. Pick a candidate chunk subset to revert to vanilla using one of:
       --include 'm60_4'         every msb whose name starts with m60_4
       --include 'm60_4,m60_5'   prefix list (comma-separated)
       --include-half east       reverts the eastern m60_xx half (cols 38-40)
       --include-half west       reverts the western m60_xx half (cols 35-37)
       --explicit m60_42_38_10.msb.dcx,m60_43_38_10.msb.dcx
  3. Run this tool — it copies the vanilla MSBs over the shuffled ones.
  4. Pass --mod-map-dir <path> so the changes auto-propagate to your me3
     profile. Without that the game launches whatever is already in the
     me3 profile, NOT what's in the shuffled output. Cf. v0.20.28 — first
     bisection attempt produced misleading results because the user
     didn't realize this.
  5. Launch into Limveld. If it still CTDs, the broken chunk wasn't in the
     reverted set. If it loads fine, the broken chunk WAS in the reverted
     set — bisect further.
  6. After 4-5 rounds, you've localized the broken chunk to one or two
     MSBs. Send the (msb_name) back to update V3_PROBLEM_SLOTS / a
     map-prefix exclude.

The tool is non-destructive: it creates a backup-and-replace setup so
you can restore the full shuffled output with --restore. --restore also
re-copies to --mod-map-dir if provided, so the me3 profile gets updated
in lockstep.

Usage:
    # Revert eastern half of m60 to vanilla AND propagate to me3:
    python vanilla_some_msbs.py shuffled_msbs/ \\
        --vanilla-dir 'vanilla msbs' \\
        --mod-map-dir '/path/to/me3/profile/map/mapstudio' \\
        --include-half east

    # Revert specific chunks:
    python vanilla_some_msbs.py shuffled_msbs/ \\
        --vanilla-dir 'vanilla msbs' \\
        --mod-map-dir '/path/to/me3/profile/map/mapstudio' \\
        --explicit m60_42_38_10.msb.dcx,m60_43_38_10.msb.dcx

    # Restore everything to the post-shuffle state (and propagate):
    python vanilla_some_msbs.py shuffled_msbs/ \\
        --mod-map-dir '/path/to/me3/profile/map/mapstudio' \\
        --restore
"""

import argparse
import os
import shutil
import sys


def collect_targets(out_dir, include_prefixes=None, explicit=None,
                    include_half=None):
    """Return list of MSB filenames in out_dir that match the inclusion
    criteria. Filenames are basenames (e.g. 'm60_42_38_10.msb.dcx')."""
    all_msbs = sorted(f for f in os.listdir(out_dir)
                      if (f.endswith('.msb') or f.endswith('.msb.dcx'))
                      and not f.endswith('.bak'))

    if explicit:
        explicit_set = {x.strip() for x in explicit.split(',')}
        return [f for f in all_msbs if f in explicit_set]

    if include_half:
        # Limveld is m60_NN_MM_VV. Treat MM (column) as the splitter.
        # Western: 35-37, Eastern: 38-40. The northern row (NN) doesn't
        # split evenly so use column.
        if include_half == 'east':
            cols = ('_38_', '_39_', '_40_')
        elif include_half == 'west':
            cols = ('_35_', '_36_', '_37_')
        else:
            print(f"ERROR: --include-half must be 'east' or 'west', got {include_half!r}",
                  file=sys.stderr)
            sys.exit(2)
        return [f for f in all_msbs if f.startswith('m60_')
                and any(c in f for c in cols)]

    if include_prefixes:
        prefixes = tuple(p.strip() for p in include_prefixes.split(','))
        return [f for f in all_msbs if f.startswith(prefixes)]

    return []


def revert_to_vanilla(out_dir, vanilla_dir, targets):
    """For each target MSB, back up the shuffled version to <name>.bak and
    copy the vanilla version into out_dir. Returns counts."""
    n_reverted = 0
    n_already_backed_up = 0
    n_missing_vanilla = 0

    for name in targets:
        out_path = os.path.join(out_dir, name)
        bak_path = out_path + '.bak'
        vanilla_path = os.path.join(vanilla_dir, name)

        if not os.path.exists(vanilla_path):
            print(f"  WARN: no vanilla source for {name}, skipping",
                  file=sys.stderr)
            n_missing_vanilla += 1
            continue

        # If a .bak already exists, the shuffled version was already
        # replaced — leave the .bak alone (we don't want to overwrite
        # the original shuffled output with a vanilla version we
        # already wrote into out_path).
        if os.path.exists(bak_path):
            n_already_backed_up += 1
        else:
            shutil.copy2(out_path, bak_path)

        shutil.copy2(vanilla_path, out_path)
        n_reverted += 1

    return n_reverted, n_already_backed_up, n_missing_vanilla


def restore_all(out_dir):
    """Restore every <file>.bak to <file> in out_dir. Returns the list of
    restored basenames so the caller can propagate them to mod_map_dir."""
    restored = []
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith('.bak'):
            continue
        bak_path = os.path.join(out_dir, name)
        out_path = bak_path[:-len('.bak')]
        shutil.move(bak_path, out_path)
        restored.append(os.path.basename(out_path))
    return restored


def copy_to_mod_map_dir(out_dir, mod_map_dir, only_basenames):
    """Copy a specific set of basenames from out_dir into mod_map_dir.

    Used after revert/restore to keep the me3 profile in lockstep with
    the bisector's working dir. Without this, the game continues loading
    whatever was in me3 before — making the bisection results meaningless.

    Returns (n_copied, n_failed)."""
    if not mod_map_dir:
        return (0, 0)
    try:
        os.makedirs(mod_map_dir, exist_ok=True)
    except OSError as e:
        print(f"ERROR: could not create mod-map-dir {mod_map_dir!r}: {e}",
              file=sys.stderr)
        return (0, len(only_basenames))

    n_copied = 0
    n_failed = 0
    for name in only_basenames:
        src = os.path.join(out_dir, name)
        dst = os.path.join(mod_map_dir, name)
        try:
            shutil.copy2(src, dst)
            n_copied += 1
        except OSError as e:
            print(f"  WARN: failed to copy {name} to mod-map-dir: {e}",
                  file=sys.stderr)
            n_failed += 1
    return (n_copied, n_failed)


def main():
    ap = argparse.ArgumentParser(
        description='Revert specific shuffled MSBs to vanilla for bisection testing.')
    ap.add_argument('out_dir',
                    help='Shuffled output directory (will be modified in-place).')
    ap.add_argument('--vanilla-dir', default='vanilla msbs',
                    help="Source dir of vanilla MSBs (default: 'vanilla msbs')")
    ap.add_argument('--mod-map-dir',
                    help='If set, every revert/restore is also propagated to '
                         'this directory (e.g. your me3 profile map/mapstudio). '
                         'Without this, the game keeps loading the previous '
                         'state of your me3 profile and bisection is a no-op.')
    ap.add_argument('--include',
                    help="Comma-separated MSB-name prefixes to revert "
                         "(e.g. 'm60_4' reverts every msb starting with m60_4)")
    ap.add_argument('--include-half', choices=['east', 'west'],
                    help='Convenience: revert the east or west half of m60_xx '
                         '(splits on column 35-37 / 38-40)')
    ap.add_argument('--explicit',
                    help='Comma-separated full filenames to revert exactly.')
    ap.add_argument('--restore', action='store_true',
                    help='Restore all backed-up MSBs to their shuffled versions.')
    ap.add_argument('--dry-run', action='store_true',
                    help='List targets without modifying files.')
    args = ap.parse_args()

    if not os.path.isdir(args.out_dir):
        print(f"ERROR: {args.out_dir!r} is not a directory", file=sys.stderr)
        sys.exit(1)

    if args.restore:
        restored = restore_all(args.out_dir)
        print(f"Restored {len(restored)} MSB(s) from .bak.")
        # Propagate the restored files to me3 too — otherwise the next
        # game launch is still using whatever was reverted.
        if restored and args.mod_map_dir:
            n, f = copy_to_mod_map_dir(args.out_dir, args.mod_map_dir, restored)
            print(f"Re-copied {n} file(s) to {args.mod_map_dir}"
                  + (f" ({f} failed)" if f else ""))
        elif restored and not args.mod_map_dir:
            print("(no --mod-map-dir set — me3 profile NOT updated; the "
                  "game may still load reverted versions)")
        return

    if not (args.include or args.include_half or args.explicit):
        print("ERROR: must specify --include / --include-half / --explicit "
              "(or --restore).", file=sys.stderr)
        sys.exit(2)

    if not os.path.isdir(args.vanilla_dir):
        print(f"ERROR: vanilla dir {args.vanilla_dir!r} not found", file=sys.stderr)
        sys.exit(1)

    targets = collect_targets(args.out_dir,
                              include_prefixes=args.include,
                              explicit=args.explicit,
                              include_half=args.include_half)

    if not targets:
        print("No MSBs matched the inclusion criteria.")
        return

    print(f"Targets to revert ({len(targets)}):")
    for t in targets:
        print(f"  {t}")

    if args.dry_run:
        print("\n(dry run — no files modified)")
        return

    n_reverted, n_backed, n_missing = revert_to_vanilla(
        args.out_dir, args.vanilla_dir, targets)

    print()
    print(f"Reverted: {n_reverted}")
    if n_backed:
        print(f"Already backed up (kept existing .bak): {n_backed}")
    if n_missing:
        print(f"WARN: {n_missing} target(s) missing vanilla source — skipped")

    # Propagate revert to me3 profile if specified.
    if args.mod_map_dir:
        n, f = copy_to_mod_map_dir(args.out_dir, args.mod_map_dir, targets)
        print()
        print(f"Copied {n} file(s) to mod-map-dir: {args.mod_map_dir}"
              + (f"  ({f} failed)" if f else ""))
    else:
        print()
        print("WARNING: --mod-map-dir not specified. The game launches files "
              "from your me3 profile, NOT from this directory. To make the "
              "revert take effect in-game, either copy the .msb.dcx files "
              "manually or re-run with --mod-map-dir set.")

    print()
    print(f"To restore the shuffled output later:")
    if args.mod_map_dir:
        print(f"  python {os.path.basename(__file__)} {args.out_dir} "
              f"--mod-map-dir {args.mod_map_dir!r} --restore")
    else:
        print(f"  python {os.path.basename(__file__)} {args.out_dir} --restore")


if __name__ == '__main__':
    main()
