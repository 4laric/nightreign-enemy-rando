"""Compare a known-good true-vanilla item_dlc01.msgbnd.dcx against the
rando-patched output, to find structural differences that might cause
NR to reject the patched file.

Usage:
    python diff_vanilla_vs_patched.py [vanilla_path] [patched_path]
    
Defaults:
    vanilla = the file you uploaded most recently — adjust below
    patched = me3 nrando profile output
"""
import os, sys, struct

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dcx import DCX
from healthbar_inplace.bnd import parse_bnd4
from healthbar_inplace.fmg import parse_fmg


def report(path, label):
    print(f"\n=== {label}: {path}")
    if not os.path.exists(path):
        print(f"  NOT FOUND")
        return None
    with open(path, 'rb') as f:
        raw = f.read()
    print(f"  Compressed size: {len(raw):,} bytes")
    
    if raw[:4] == b'DCX\x00':
        dcs = struct.unpack('>I', raw[0x1c:0x20])[0]
        comp = struct.unpack('>I', raw[0x20:0x24])[0]
        print(f"  DCX: decompressed={dcs:,} comp={comp:,} type={raw[0x28:0x2c]!r} level={raw[0x30]}")
        data = DCX.decompress_bytes(raw)
    else:
        data = raw
    print(f"  BND4 size: {len(data):,}")
    
    bnd = parse_bnd4(data)
    print(f"  BND entries: {len(bnd.entries)}")
    
    # NpcName.fmg
    npc = next((e for e in bnd.entries if 'NpcName.fmg' in e.name and 'dlc' not in e.name.lower()), None)
    if not npc:
        print(f"  NpcName.fmg NOT FOUND")
        return None
    print(f"  NpcName.fmg size: {len(npc.data):,}")
    
    # FMG header
    print(f"  FMG first 32 bytes: {npc.data[:32].hex(' ')}")
    
    fmg = parse_fmg(npc.data)
    non_empty = {k: v for k, v in fmg.entries.items() if v}
    print(f"  FMG entries: total={len(fmg.entries)} non-empty={len(non_empty)}")
    
    return {
        'raw_size': len(raw),
        'bnd_size': len(data),
        'bnd_entries': len(bnd.entries),
        'fmg_size': len(npc.data),
        'fmg_entries': len(fmg.entries),
        'fmg_non_empty': len(non_empty),
        'fmg_data': fmg,
        'npc_raw': npc.data,
    }


def main():
    # Default paths
    vanilla_path = sys.argv[1] if len(sys.argv) > 1 else \
        r"C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING NIGHTREIGN\Game\msg\engUS\item_dlc01.msgbnd.dcx"
    patched_path = sys.argv[2] if len(sys.argv) > 2 else \
        r"C:\Users\alari\AppData\Local\garyttierney\me3\config\profiles\onlyrando\nrando\msg\engUS\item_dlc01.msgbnd.dcx"
    
    print(f"Vanilla path: {vanilla_path}")
    print(f"Patched path: {patched_path}")
    
    # If you've already overwritten the install dir's vanilla with our patched, the vanilla
    # path won't really be vanilla. To get a real vanilla, you'd need to either:
    #  - re-UXM-unpack
    #  - restore from your earlier backup if you made one
    
    v = report(vanilla_path, "VANILLA")
    p = report(patched_path, "PATCHED")
    
    if not v or not p:
        return
    
    print(f"\n=== DIFFERENCES ===")
    print(f"DCX compressed:      vanilla={v['raw_size']:>9,}  patched={p['raw_size']:>9,}  diff={p['raw_size']-v['raw_size']:+,}")
    print(f"BND4 decompressed:   vanilla={v['bnd_size']:>9,}  patched={p['bnd_size']:>9,}  diff={p['bnd_size']-v['bnd_size']:+,}")
    print(f"BND entry count:     vanilla={v['bnd_entries']:>9}  patched={p['bnd_entries']:>9}")
    print(f"NpcName.fmg size:    vanilla={v['fmg_size']:>9,}  patched={p['fmg_size']:>9,}  diff={p['fmg_size']-v['fmg_size']:+,}")
    print(f"FMG total entries:   vanilla={v['fmg_entries']:>9}  patched={p['fmg_entries']:>9}")
    print(f"FMG non-empty:       vanilla={v['fmg_non_empty']:>9}  patched={p['fmg_non_empty']:>9}")
    
    # Find IDs lost/changed
    v_fmg = v['fmg_data'].entries
    p_fmg = p['fmg_data'].entries
    v_ne = {k: x for k, x in v_fmg.items() if x}
    p_ne = {k: x for k, x in p_fmg.items() if x}
    
    lost = sorted(set(v_ne) - set(p_ne))
    gained = sorted(set(p_ne) - set(v_ne))
    changed = sorted(k for k in (set(v_ne) & set(p_ne)) if v_ne[k] != p_ne[k])
    
    print(f"\nFMG content diff:")
    print(f"  IDs in vanilla but lost in patched: {len(lost)}")
    if lost:
        for k in lost[:5]:
            print(f"    {k}: {v_ne[k]!r}")
    print(f"  IDs only in patched (new fresh-alloc): {len(gained)}")
    if gained:
        for k in gained[:3]:
            print(f"    {k}: {p_ne[k]!r}")
    print(f"  IDs with changed text: {len(changed)}")
    if changed:
        for k in changed[:5]:
            print(f"    {k}: {v_ne[k]!r} -> {p_ne[k]!r}")
    
    # First-byte diff for NpcName.fmg
    print(f"\nNpcName.fmg first 32 bytes:")
    print(f"  vanilla: {v['npc_raw'][:32].hex(' ')}")
    print(f"  patched: {p['npc_raw'][:32].hex(' ')}")
    
    # Header decode
    print(f"\nFMG header (binary fields):")
    def fmg_header(data, label):
        sig = struct.unpack('<I', data[:4])[0]
        unk1 = struct.unpack('<I', data[4:8])[0]
        fsize = struct.unpack('<I', data[8:12])[0]
        groups = struct.unpack('<I', data[12:16])[0]
        strings = struct.unpack('<I', data[16:20])[0]
        unk2 = struct.unpack('<I', data[20:24])[0]
        offs_table = struct.unpack('<Q', data[24:32])[0]
        print(f"  {label}: sig={sig:#x} unk1={unk1:#x} file_size={fsize:,} "
              f"groups={groups} strings={strings} unk2={unk2:#x} string_offsets_table={offs_table:#x}")
    fmg_header(v['npc_raw'], 'vanilla')
    fmg_header(p['npc_raw'], 'patched')


if __name__ == '__main__':
    main()
