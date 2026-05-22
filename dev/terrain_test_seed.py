#!/usr/bin/env python3
"""terrain_test_seed.py — Generate a test seed using ONLY navmesh classification.

Throws away V3_FRAGILE_*, V3_PROBLEM_*, V3_RESILIENT_*, and other heuristic
problem-slot rules. Uses purely the slot_terrain.json classification:

  - on_mesh slots  → c4080 Rat (default)
  - off_mesh slots → c4180 Spirit Jellyfish (default)
  - no_match slots → keep vanilla (sentinels)
  - slots not in cache → treated as on_mesh (Rat)

Test design: walk the world. Any FROZEN Rat indicates a false negative
in the on_mesh classification. Jellies on off_mesh slots may or may not
work — they float, so should handle off-mesh better than ground enemies,
but bumpy/walled terrain might still trap them.

Usage:
    # On vanilla MSBs (already decompressed):
    python terrain_test_seed.py <vanilla_msb_dir> <output_msb_dir>

    # On vanilla MSB.dcx (will use dcx_batch pipeline):
    python terrain_test_seed.py <vanilla_dcx_dir> <output_dcx_dir>

    # With custom targets:
    python terrain_test_seed.py <in> <out> --on-mesh c4080 --off-mesh c4180

After running, drop output into me3 BBH profile at map/mapstudio/.
"""

import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input_dir',
                    help='Directory of vanilla .msb (or .msb.dcx) files')
    ap.add_argument('output_dir',
                    help='Output directory for modded MSBs')
    ap.add_argument('--on-mesh', default='c4080',
                    help='c-prefix for on-mesh slots (default: c4080 Rat)')
    ap.add_argument('--off-mesh', default='c4180',
                    help='c-prefix for off-mesh slots (default: c4180 Spirit Jellyfish)')
    ap.add_argument('--seed', type=int, default=42,
                    help='RNG seed (only affects variant picking; targets are '
                         'deterministic per slot)')
    args = ap.parse_args()

    # Ensure we're using the rando module from the same dir as this script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import oops_v3

    targets = {'on_mesh': args.on_mesh, 'off_mesh': args.off_mesh}
    print(f'Terrain test seed:')
    print(f'  on_mesh  → {args.on_mesh}')
    print(f'  off_mesh → {args.off_mesh}')
    print(f'  no_match → vanilla (skip)')
    print(f'  unknown  → on_mesh target')
    print()

    # Detect input format
    has_dcx = any(f.endswith('.msb.dcx') for f in os.listdir(args.input_dir)
                  if os.path.isfile(os.path.join(args.input_dir, f)))
    has_plain = any(f.endswith('.msb') and not f.endswith('.dcx')
                    for f in os.listdir(args.input_dir)
                    if os.path.isfile(os.path.join(args.input_dir, f)))

    os.makedirs(args.output_dir, exist_ok=True)

    if has_dcx:
        print(f'Detected .msb.dcx input — running DCX pipeline')
        import dcx_batch
        dcx_batch.rando_pipeline(
            args.input_dir, args.output_dir,
            seed=args.seed,
            terrain_test_targets=targets,
        )
    elif has_plain:
        print(f'Detected plain .msb input — running direct shuffle')
        oops_v3.cmd_shuffle_v3(
            args.input_dir, args.output_dir,
            args.seed,
            terrain_test_targets=targets,
        )
    else:
        print(f'ERROR: no .msb or .msb.dcx files found in {args.input_dir}',
              file=sys.stderr)
        sys.exit(1)

    print()
    print('Done. Walk the world and report any frozen Rats — those are')
    print('false negatives in the on-mesh classification.')


if __name__ == '__main__':
    main()
