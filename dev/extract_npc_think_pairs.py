#!/usr/bin/env python3
"""extract_npc_think_pairs.py — mine (NPCParamID -> ThinkParamID) pairings
from a directory of .msb files.

WHY THIS EXISTS
In Elden Ring / Nightreign the pairing between an enemy's NpcParam row and
its NpcThinkParam row is NOT a param fact and NOT derivable from the IDs.
It is authored per enemy Part inside the MSB: each Enemy Part carries an
<NPCParamID> and an <ThinkParamID> field. Empirically (4513 vanilla NR
placements) `think == npc` only ~5.5% of the time, and multi-variant
humanoids collapse many npc-blocks onto a few think rows irregularly. So
the only way to know "which think does npc X want" is to read the MSBs
that place X.

This tool walks every .msb in a directory, extracts every Enemy Part, and
aggregates npc -> think. Because a single npc id can legitimately appear
with different thinks in different placements, the output records a COUNT
per think so you can pick the dominant one.

USAGE
    # run from the repo root (needs oops_all_anyone.py on the path)
    python3 dev/extract_npc_think_pairs.py \\
        --msb-dir /path/to/msbs \\
        --out dev/npc_think_pairs.json
        [--prefix c5651]      # optional: restrict to one chr prefix

For the c5651 Messmer Foot Soldier remap specifically: point --msb-dir at
MMV's modified MSBs (the .msb files shipped by the More Map Variations
mod — vanilla NR MSBs do NOT place c5651, it is a SoTE/MMV import), then
--prefix c5651. The resulting table is the verified pairing source the
think_param_id remap needs.

OUTPUT (JSON)
{
  "_meta": { generator, msb_dir, n_msbs, n_parts, prefix_filter },
  "pairs": {
    "<npc_param_id>": {
      "prefix": "cXXXX",
      "placements": <int>,
      "thinks": { "<think_param_id>": <count>, ... },
      "dominant_think": <think_param_id with the highest count>
    },
    ...
  }
}
"""
import argparse
import glob
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--msb-dir', required=True, help='directory of .msb files')
    ap.add_argument('--out', required=True, help='output JSON path')
    ap.add_argument('--prefix', help='restrict to one chr prefix, e.g. c5651')
    ap.add_argument('--repo-root', default=None,
                    help='repo root holding oops_all_anyone.py '
                         '(default: parent of this script)')
    args = ap.parse_args()

    repo = args.repo_root or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)
    try:
        from oops_all_anyone import extract_enemy_parts
    except Exception as e:
        print(f"ERROR: could not import extract_enemy_parts from {repo}\n  {e}")
        print("Run from the repo, or pass --repo-root.")
        sys.exit(1)

    msbs = sorted(glob.glob(os.path.join(args.msb_dir, '*.msb')))
    if not msbs:
        print(f"ERROR: no .msb files in {args.msb_dir}")
        sys.exit(1)

    # npc -> {prefix, placements, thinks: Counter}
    pairs = {}
    n_parts = 0
    parse_fail = []
    for path in msbs:
        try:
            parts = extract_enemy_parts(open(path, 'rb').read())
        except Exception as e:
            parse_fail.append((os.path.basename(path), str(e)))
            continue
        for pt in parts:
            pref = pt['prefix'].rstrip('\x00')
            if args.prefix and pref != args.prefix:
                continue
            n_parts += 1
            npc = str(pt['npc'])
            rec = pairs.setdefault(npc, {'prefix': pref, 'placements': 0,
                                         'thinks': {}})
            rec['placements'] += 1
            t = str(pt['think'])
            rec['thinks'][t] = rec['thinks'].get(t, 0) + 1

    for npc, rec in pairs.items():
        rec['dominant_think'] = max(rec['thinks'].items(),
                                    key=lambda kv: kv[1])[0]

    out = {
        '_meta': {
            'generator': 'extract_npc_think_pairs.py',
            'msb_dir': os.path.abspath(args.msb_dir),
            'n_msbs': len(msbs),
            'n_parts': n_parts,
            'prefix_filter': args.prefix or '(none)',
            'parse_failures': parse_fail,
        },
        'pairs': {k: pairs[k] for k in sorted(pairs, key=lambda x: int(x))},
    }
    with open(args.out, 'w') as f:
        json.dump(out, f, indent=1)

    multi = sum(1 for r in pairs.values() if len(r['thinks']) > 1)
    print(f"{len(msbs)} MSBs | {n_parts} enemy parts"
          f"{' (prefix '+args.prefix+')' if args.prefix else ''} | "
          f"{len(pairs)} distinct npc ids")
    print(f"  npc ids placed with >1 distinct think: {multi}")
    if parse_fail:
        print(f"  parse failures: {len(parse_fail)}")
    print(f"  wrote {args.out}")
    if args.prefix and not pairs:
        print(f"\nNOTE: zero {args.prefix} parts found. If this was meant to "
              f"be MMV's MSBs, confirm you dumped the modded set — vanilla "
              f"NR MSBs do not place imported chrs.")


if __name__ == '__main__':
    main()
