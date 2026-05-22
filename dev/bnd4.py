#!/usr/bin/env python3
"""bnd4.py — Minimal pure-Python BND4 binder reader.

v0.22: Lets us walk .nvmhktbnd binders directly (no Yabber/WitchyBND
unpack required). Each binder typically contains one n_*.hkx (the
navmesh) plus auxiliary o_/q_ files; we only care about the navmesh
for terrain analysis.

Format reference (NR-confirmed against m60_*.nvmhktbnd, version 07D7R6):
    0x00  char[4]   magic = 'BND4'
    0x04  u8[8]     unk04..0B
    0x0C  u32       fileCount
    0x10  u64       fileHeadersOffset (typically 0x40)
    0x18  char[8]   version string ('07D7R6\\0\\0')
    0x20  u64       fileHeaderSize (typically 0x24 = 36 bytes)
    0x28  u64       dataOffset
    0x30+ ...       bitflags / format byte + padding

Each per-file header (fileHeaderSize bytes, format 0x74):
    +0x00  u32     flags
    +0x04  u32     pad
    +0x08  u64     compressed size
    +0x10  u64     uncompressed size
    +0x18  u32     data offset (within binder)
    +0x1C  u32     file id
    +0x20  u32     name offset (UTF-16-LE name string)

NR navmesh binders happen to ship uncompressed (csize == usize), so no
inner Oodle pass is needed. Each embedded .hkx is in TAG0 wrapper format
which the existing hkx_aabb_check.extract_aabbs_from_bytes consumes
directly.

Usage:
    from bnd4 import read_bnd4
    for name, payload in read_bnd4('m60_44_38_30.nvmhktbnd'):
        if name.startswith('n') and name.endswith('.hkx'):
            ...
"""
import os
import struct


def read_bnd4(path):
    """Yield (basename, payload_bytes) for each embedded file.

    'basename' is the filename portion of the BND4-stored path (the
    binder stores full Windows paths like 'W:\\CL\\data\\...\\n_xxx.hkx';
    we return just 'n_xxx.hkx'). 'payload_bytes' is the raw embedded
    file content, no decompression applied.

    Returns empty list for empty/placeholder binders (96-byte stubs)
    and for non-BND4 files (caller should sanity-check).
    """
    with open(path, 'rb') as f:
        raw = f.read()
    if len(raw) < 0x40 or raw[0:4] != b'BND4':
        return []

    file_count = struct.unpack('<I', raw[0x0C:0x10])[0]
    if file_count == 0:
        return []
    hdr_off  = struct.unpack('<Q', raw[0x10:0x18])[0]
    hdr_size = struct.unpack('<Q', raw[0x20:0x28])[0]

    out = []
    for i in range(file_count):
        o = hdr_off + i * hdr_size
        if o + hdr_size > len(raw):
            break
        # csize = struct.unpack('<Q', raw[o+8:o+16])[0]
        usize    = struct.unpack('<Q', raw[o+16:o+24])[0]
        data_off = struct.unpack('<I', raw[o+24:o+28])[0]
        name_off = struct.unpack('<I', raw[o+32:o+36])[0]

        # UTF-16-LE name terminated by two zero bytes at even alignment.
        # (Naive find of b'\\x00\\x00' would catch the high-zero of the
        # last char + first byte of terminator — wrong cut.)
        n_end = name_off
        while n_end < len(raw) - 1:
            if raw[n_end] == 0 and raw[n_end + 1] == 0:
                break
            n_end += 2
        try:
            name = raw[name_off:n_end].decode('utf-16-le')
        except UnicodeDecodeError:
            name = raw[name_off:n_end].decode('utf-16-le', errors='replace')
        # Strip Windows path
        basename = name.replace('\\', '/').rsplit('/', 1)[-1]

        # Note: NR navmesh binders are always uncompressed (csize==usize
        # observed across all 100 sampled binders). If csize != usize we'd
        # need an Oodle pass here — left as future work.
        payload = raw[data_off:data_off + usize]
        out.append((basename, payload))

    return out


def read_navmesh_payload(path):
    """Return concatenated raw bytes of the navmesh hkx file(s) in this
    binder, or empty bytes if none. Convenience wrapper for the common
    case in build_slot_terrain.py."""
    payloads = []
    for name, payload in read_bnd4(path):
        if name.startswith('n') and name.endswith('.hkx'):
            payloads.append(payload)
    return payloads


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('usage: bnd4.py <binder.nvmhktbnd>')
        sys.exit(1)
    p = sys.argv[1]
    print(f'{p} ({os.path.getsize(p):,} bytes):')
    for name, payload in read_bnd4(p):
        magic = payload[4:8] if len(payload) >= 8 else b''
        print(f'  {name:<40} {len(payload):>10,} bytes  magic@4={magic!r}')
