#!/usr/bin/env python3
"""extract_npc_think_from_xml.py — mine (NPCParamID -> ThinkParamID) pairings
from WitchyBND-decompiled MSB directories (XML form).

WHY THIS EXISTS (companion to extract_npc_think_pairs.py)
The npc<->think pairing for an enemy is authored per Enemy Part in the MSB,
not in any param. extract_npc_think_pairs.py reads BINARY .msb files using
the repo's NR-tuned struct offsets. Those offsets are Nightreign-specific;
pointing them at Elden Ring MSBs risks silent misparse. WitchyBND decompiles
any MSB (ER or NR) to a stable XML schema, so parsing the XML sidesteps all
binary-format divergence. Use this tool whenever you have decompiled MSB
dirs; use the binary tool when you have raw .msb files from NR.

This is the source needed for the c5651 Messmer Foot Soldier think remap:
vanilla NR never places c5651, and it is an ER (SoTE) import, so decompile
ER's Land-of-Shadow MSBs and run this with --prefix c5651.

INPUT LAYOUT
Pass --root pointing at a directory that contains one or more WitchyBND
MSB dirs. Each MSB dir holds Part/Enemy/*.xml files shaped like:
    <Enemy>
      <ModelName>c5651</ModelName>
      <ThinkParamID>56510000</ThinkParamID>
      <NPCParamID>56510500</NPCParamID>
      ...
The tool recurses, so a whole "decompiled ER mapstudio" tree works in one go.

USAGE
    python3 extract_npc_think_from_xml.py \\
        --root /path/to/decompiled_er_msbs \\
        --out  c5651_pairs.json \\
        [--prefix c5651]

OUTPUT — identical schema to extract_npc_think_pairs.py, so the two are
interchangeable downstream:
{
  "_meta": { generator, root, n_msb_dirs, n_parts, prefix_filter, parse_failures },
  "pairs": {
    "<npc_param_id>": {
      "prefix": "cXXXX",                     # from <ModelName>
      "placements": <int>,
      "thinks": { "<think_param_id>": <count>, ... },
      "dominant_think": <think id with highest count>,
      "maps": [ <msb dir names where this npc id appears> ]
    }, ...
  }
}
"""
import argparse
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET


def _text(elem, tag):
    node = elem.find(tag)
    return node.text.strip() if node is not None and node.text else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True,
                    help='dir containing WitchyBND-decompiled MSB dirs')
    ap.add_argument('--out', required=True, help='output JSON path')
    ap.add_argument('--prefix', help='restrict to one chr prefix, e.g. c5651')
    args = ap.parse_args()

    enemy_xmls = glob.glob(os.path.join(args.root, '**', 'Part', 'Enemy', '*.xml'),
                           recursive=True)
    if not enemy_xmls:
        print(f"ERROR: no Part/Enemy/*.xml found under {args.root}")
        print("Pass --root at the dir holding the decompiled MSB dirs.")
        sys.exit(1)

    pairs = {}          # npc -> {prefix, placements, thinks{}, maps set}
    n_parts = 0
    parse_fail = []
    msb_dirs = set()

    for path in enemy_xmls:
        # msb dir = the directory two levels up from the xml (…/<msb>/Part/Enemy/x.xml)
        msb_dir = os.path.basename(os.path.dirname(os.path.dirname(
            os.path.dirname(path))))
        msb_dirs.add(msb_dir)
        try:
            root = ET.parse(path).getroot()
        except Exception as e:
            parse_fail.append((path, str(e)))
            continue
        model = _text(root, 'ModelName')
        npc = _text(root, 'NPCParamID')
        think = _text(root, 'ThinkParamID')
        if npc is None or think is None:
            continue
        prefix = model or ''
        if args.prefix and prefix != args.prefix:
            continue
        n_parts += 1
        rec = pairs.setdefault(npc, {'prefix': prefix, 'placements': 0,
                                     'thinks': {}, 'maps': set()})
        rec['placements'] += 1
        rec['thinks'][think] = rec['thinks'].get(think, 0) + 1
        rec['maps'].add(msb_dir)

    for npc, rec in pairs.items():
        rec['dominant_think'] = max(rec['thinks'].items(),
                                    key=lambda kv: kv[1])[0]
        rec['maps'] = sorted(rec['maps'])

    out = {
        '_meta': {
            'generator': 'extract_npc_think_from_xml.py',
            'root': os.path.abspath(args.root),
            'n_msb_dirs': len(msb_dirs),
            'n_parts': n_parts,
            'prefix_filter': args.prefix or '(none)',
            'parse_failures': parse_fail,
        },
        'pairs': {k: pairs[k] for k in sorted(pairs,
                  key=lambda x: int(x) if x.isdigit() else 0)},
    }
    with open(args.out, 'w') as f:
        json.dump(out, f, indent=1)

    multi = sum(1 for r in pairs.values() if len(r['thinks']) > 1)
    print(f"{len(msb_dirs)} MSB dirs | {n_parts} enemy parts"
          f"{' (prefix '+args.prefix+')' if args.prefix else ''} | "
          f"{len(pairs)} distinct npc ids")
    print(f"  npc ids placed with >1 distinct think: {multi}")
    if parse_fail:
        print(f"  parse failures: {len(parse_fail)}")
    print(f"  wrote {args.out}")
    if args.prefix and not pairs:
        print(f"\nNOTE: zero {args.prefix} parts found in this tree.")


if __name__ == '__main__':
    main()
