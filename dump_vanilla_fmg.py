"""Dump YOUR installed vanilla NpcName.fmg so we can rebuild the
chr_to_nameid catalog from real-world content. Run from rando root.

Writes the full FMG contents to vanilla_npcname_dump.txt as
"id<TAB>text" pairs, sorted by id. Upload that file back.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dcx import DCX
from healthbar_inplace.bnd import parse_bnd4
from healthbar_inplace.fmg import parse_fmg


def main():
    candidates = [
        r"C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING NIGHTREIGN\Game\msg\engUS\item_dlc01.msgbnd.dcx",
        r"C:\Program Files\Steam\steamapps\common\ELDEN RING NIGHTREIGN\Game\msg\engUS\item_dlc01.msgbnd.dcx",
    ]
    path = None
    for p in candidates:
        if os.path.exists(p):
            path = p
            break
    if path is None:
        print("Could not find vanilla item_dlc01.msgbnd.dcx — edit script with your install path.")
        sys.exit(1)

    print(f"Reading: {path}")
    with open(path, 'rb') as f:
        data = f.read()
    print(f"Size on disk: {len(data):,} bytes")

    if data[:4] == b'DCX\x00':
        print("Decompressing...")
        data = DCX.decompress_bytes(data)
        print(f"Decompressed: {len(data):,} bytes")

    bnd = parse_bnd4(data)
    print(f"BND4 entries: {len(bnd.entries)}")

    out_path = os.path.join(HERE, 'vanilla_npcname_dump.txt')
    with open(out_path, 'w', encoding='utf-8') as out:
        for e in bnd.entries:
            short = e.name.split('\\')[-1]
            if not short.lower().endswith('.fmg'):
                continue
            try:
                fmg = parse_fmg(e.data)
            except Exception as ex:
                out.write(f"# FMG {short}: parse error {ex}\n")
                continue
            out.write(f"# FMG: {short} ({len(fmg.entries)} entries)\n")
            for id_ in sorted(fmg.entries):
                text = fmg.entries[id_]
                if text:
                    # Normalize newlines into \n literal so the dump stays single-line per entry
                    safe = text.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    out.write(f"{id_}\t{safe}\n")
    print(f"Wrote dump: {out_path}")
    print(f"Upload that file back so I can rebuild chr_to_nameid.json from real data.")


if __name__ == '__main__':
    main()
