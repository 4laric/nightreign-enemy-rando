#!/usr/bin/env python3
"""
simulate_seeds.py — Run the rando over a seed range, dropping each spoiler
into its own per-seed output folder. The MSB outputs are written too but
typically you only care about the _spoilers.json files for demo-seed selection.

USAGE (Windows, where Oodle DLL is available):

  python simulate_seeds.py \
      --vanilla-msbs path\\to\\decompressed_vanilla_msbs \
      --out-root seeds \
      --seed-start 10000 \
      --seed-count 50

The output layout is:
  seeds/
    seed10000/
      _spoilers.json
      m10_00_00_00.msb
      m11_00_00_00.msb
      ...
    seed10001/
      _spoilers.json
      ...

Then feed `seeds/` to prep_demo.py for ranking.

Notes:
  - This calls the engine in-process (imports oops_v3) rather than shelling
    out. Faster, and lets us catch engine exceptions in Python.
  - Each seed produces ~50-100MB of MSB output. For 50 seeds that's a few GB.
    If you only need spoilers, delete the .msb files after each run with
    --spoilers-only.
  - Engine state is global, so we run serially. Parallelizing would require
    process-isolation (subprocess per seed).
"""

import argparse
import json
import os
import shutil
import sys
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vanilla-msbs', required=True,
                    help='Directory of decompressed vanilla NR .msb files')
    ap.add_argument('--out-root', required=True,
                    help='Per-seed output dirs are created under this')
    ap.add_argument('--seed-start', type=int, required=True)
    ap.add_argument('--seed-count', type=int, required=True)
    ap.add_argument('--mode', default='loose')
    ap.add_argument('--spoilers-only', action='store_true',
                    help='Delete the MSB outputs after each run, keeping only _spoilers.json')
    ap.add_argument('--engine-dir', default=None,
                    help='Path to the rando engine dir (containing oops_v3.py). '
                         'Defaults to the script\'s parent directory.')
    args = ap.parse_args()

    engine_dir = args.engine_dir or os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, engine_dir)
    import oops_v3  # noqa: E402

    os.makedirs(args.out_root, exist_ok=True)

    t0 = time.time()
    for i in range(args.seed_count):
        seed = args.seed_start + i
        out_dir = os.path.join(args.out_root, f'seed{seed}')
        if os.path.isdir(out_dir) and os.path.exists(os.path.join(out_dir, '_spoilers.json')):
            sys.stderr.write(f"[{i+1}/{args.seed_count}] seed {seed}: already done; skipping\n")
            continue
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir)
        t_seed = time.time()
        try:
            oops_v3.cmd_shuffle_v3(args.vanilla_msbs, out_dir, seed, args.mode)
        except Exception as e:
            sys.stderr.write(f"[{i+1}/{args.seed_count}] seed {seed}: FAILED ({e!r})\n")
            # Leave the dir in place so the user can inspect; move on.
            continue
        dur = time.time() - t_seed
        if args.spoilers_only:
            # Keep only _spoilers.json and any other non-MSB outputs.
            for f in os.listdir(out_dir):
                full = os.path.join(out_dir, f)
                if f.startswith('_'):
                    continue
                if os.path.isfile(full):
                    os.remove(full)
        sys.stderr.write(f"[{i+1}/{args.seed_count}] seed {seed}: done ({dur:.1f}s)\n")
    total = time.time() - t0
    sys.stderr.write(f"All done in {total:.1f}s ({total/max(1,args.seed_count):.1f}s/seed avg)\n")


if __name__ == '__main__':
    main()
