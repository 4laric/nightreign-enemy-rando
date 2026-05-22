"""Deep structural check on a patched item_dlc01.msgbnd.dcx.

Verifies:
  - DCX decompresses cleanly
  - BND4 parses, NpcName.fmg present
  - FMG entry/group tables are self-consistent
  - Fresh-alloc IDs (970xxxxxxx) resolve to real strings
  - Pre-existing IDs (e.g. 902130014) still resolve
  - Compares pre-existing-id values to a known-good reference (the
    bundled vanilla source) to detect data corruption from the splice

Run from rando project root:
    python check_patched_deep.py [path-to-patched-msgbnd.dcx]

Defaults to checking the me3 nrando profile.
"""
import os, sys, struct

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dcx import DCX
from healthbar_inplace.bnd import parse_bnd4
from healthbar_inplace.fmg import parse_fmg


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = r"C:\Users\alari\AppData\Local\garyttierney\me3\config\profiles\onlyrando\nrando\msg\engUS\item_dlc01.msgbnd.dcx"

    print(f"=== Reading: {path}")
    if not os.path.exists(path):
        print(f"NOT FOUND. Pass an alternate path as argv[1].")
        sys.exit(1)

    with open(path, 'rb') as f:
        raw = f.read()
    print(f"Size: {len(raw):,} bytes")
    print(f"First 64 bytes hex:")
    for i in range(0, 64, 16):
        print(f"  0x{i:02x}: {raw[i:i+16].hex(' ')}")
    
    # DCX header decode
    if raw[:4] == b'DCX\x00':
        dcs = struct.unpack('>I', raw[0x1c:0x20])[0]
        comp = struct.unpack('>I', raw[0x20:0x24])[0]
        comp_type = raw[0x28:0x2c]
        level = raw[0x30]
        print(f"\nDCX header:")
        print(f"  Decompressed size advertised: {dcs:,}")
        print(f"  Compressed payload: {comp:,}")
        print(f"  Compression type: {comp_type!r}")
        print(f"  Compression level: {level}")
        
        try:
            decompressed = DCX.decompress_bytes(raw)
            print(f"  Decompress OK: {len(decompressed):,} bytes")
            assert len(decompressed) == dcs, f"Size mismatch: header says {dcs}, got {len(decompressed)}"
        except Exception as e:
            print(f"  Decompress FAILED: {e}")
            sys.exit(1)
    else:
        decompressed = raw
    
    # BND4 parse
    print(f"\n=== BND4 parse ===")
    if decompressed[:4] != b'BND4':
        print(f"NOT a BND4: magic={decompressed[:4]!r}")
        sys.exit(1)
    
    bnd = parse_bnd4(decompressed)
    print(f"BND4 entries: {len(bnd.entries)}")
    print(f"BND4 first 12 entry names:")
    for e in bnd.entries[:12]:
        short = e.name.split('\\')[-1]
        print(f"  {short:<35} size={len(e.data):>7}")
    
    # NpcName.fmg specifically
    npc = next((e for e in bnd.entries if 'NpcName.fmg' in e.name and 'dlc' not in e.name.lower()), None)
    if npc is None:
        print(f"\nERROR: no NpcName.fmg (non-dlc) found in BND")
        sys.exit(1)
    
    print(f"\n=== NpcName.fmg ===")
    print(f"Size: {len(npc.data):,} bytes")
    print(f"First 32 bytes hex: {npc.data[:32].hex(' ')}")
    
    # FMG header decode
    if npc.data[:4] != b'\x00\x00\x00\x00':
        # FMG can start with various things; try parsing
        pass
    
    fmg = parse_fmg(npc.data)
    print(f"Total entries parsed: {len(fmg.entries)}")
    
    non_empty = sum(1 for v in fmg.entries.values() if v)
    print(f"Non-empty: {non_empty}")
    
    # Critical: are the fresh-alloc entries there?
    fresh = sorted(k for k in fmg.entries if 970000000 <= k < 980000000)
    print(f"\nFresh-alloc entries (970000000-979999999): {len(fresh)}")
    for k in fresh[:5]:
        print(f"  {k}: {fmg.entries[k]!r}")
    if len(fresh) > 5:
        print(f"  ... and {len(fresh) - 5} more")
    
    # Check key catalog IDs
    print(f"\n=== Catalog ID check (existing IDs that should NOT have changed) ===")
    targets = {
        902130014: 'Crucible Knight and more',
        903250610: 'Tree Sentinel',
        904911320: 'Tibia Mariner',
    }
    for id_, expected in targets.items():
        val = fmg.entries.get(id_)
        match = '✓' if val == expected else f'✗ (expected {expected!r})'
        print(f"  {id_}: {val!r}  {match}")
    
    # Compare with bundled vanilla to detect corruption
    print(f"\n=== Comparison with bundled vanilla ===")
    bundled = os.path.join(HERE, 'data', 'vanilla_msg', 'item_dlc01.msgbnd')
    if os.path.exists(bundled):
        with open(bundled, 'rb') as f:
            v_raw = f.read()
        v_bnd = parse_bnd4(v_raw)
        v_npc = next(e for e in v_bnd.entries if 'NpcName.fmg' in e.name and 'dlc' not in e.name.lower())
        v_fmg = parse_fmg(v_npc.data)
        v_non_empty = {k: v for k, v in v_fmg.entries.items() if v}
        print(f"Vanilla bundled NpcName.fmg: {len(v_non_empty)} non-empty entries")
        
        # How many vanilla entries survived correctly?
        preserved = 0
        broken = []
        for k, v in v_non_empty.items():
            if fmg.entries.get(k) == v:
                preserved += 1
            elif fmg.entries.get(k):
                broken.append((k, v, fmg.entries[k]))
        print(f"Preserved correctly: {preserved} / {len(v_non_empty)}")
        if broken:
            print(f"DIFFERENT (potential corruption): {len(broken)}")
            for k, vanilla, patched_val in broken[:5]:
                print(f"  {k}: vanilla={vanilla!r} -> patched={patched_val!r}")
    else:
        print(f"No bundled vanilla at {bundled}")


if __name__ == '__main__':
    main()
