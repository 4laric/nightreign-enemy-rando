#!/usr/bin/env python3
"""BND4 parser v2 — corrected entry layout.

Each entry is 0x24 bytes (36):
  +0x00 (i32) raw_flags  (always 0x40 in NR)
  +0x04 (i32) unknown    (always 0xFFFFFFFF)
  +0x08 (i64) compressed_size
  +0x10 (i64) uncompressed_size
  +0x18 (i32) data_offset    (offset in file)
  +0x1C (i32) id
  +0x20 (i32) name_offset    (offset in file)

Strings are UTF-16-LE, null-terminated, packed after the entry table.
File data follows the strings.
"""
import struct
import sys
import os


def parse_bnd4(data: bytes):
    if data[:4] != b'BND4':
        raise ValueError('Not a BND4 file')

    file_count = struct.unpack_from('<I', data, 0x0C)[0]
    header_size = struct.unpack_from('<Q', data, 0x10)[0]
    version = data[0x18:0x20].rstrip(b'\x00').decode('ascii', errors='replace')
    file_flags = data[0x20]

    entries = []
    ENTRY_SIZE = 0x24  # confirmed for NR anibnd + chrbnd

    for i in range(file_count):
        eo = header_size + i * ENTRY_SIZE
        raw_flags  = struct.unpack_from('<I', data, eo + 0x00)[0]
        unknown    = struct.unpack_from('<I', data, eo + 0x04)[0]
        csize      = struct.unpack_from('<Q', data, eo + 0x08)[0]
        usize      = struct.unpack_from('<Q', data, eo + 0x10)[0]
        doff       = struct.unpack_from('<I', data, eo + 0x18)[0]
        id_        = struct.unpack_from('<I', data, eo + 0x1C)[0]
        name_off   = struct.unpack_from('<I', data, eo + 0x20)[0]

        # UTF-16-LE name, null-terminated
        if name_off:
            end = name_off
            while end + 1 < len(data) and data[end:end+2] != b'\x00\x00':
                end += 2
            name = data[name_off:end].decode('utf-16-le', errors='replace')
        else:
            name = ''

        entries.append({
            'raw_flags': raw_flags,
            'compressed_size': csize,
            'uncompressed_size': usize,
            'data_offset': doff,
            'id': id_,
            'name_offset': name_off,
            'name': name,
        })

    return {
        'version': version,
        'file_count': file_count,
        'file_flags': file_flags,
        'entries': entries,
    }


def extract_entry(data: bytes, entry: dict) -> bytes:
    off = entry['data_offset']
    sz = entry['compressed_size']
    return data[off:off + sz]


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: bnd4_v2.py <file> [<file2> ...]')
        sys.exit(1)
    for path in sys.argv[1:]:
        with open(path, 'rb') as f:
            buf = f.read()
        try:
            info = parse_bnd4(buf)
        except Exception as e:
            print(f'{path}: {e}')
            continue
        print(f'=== {os.path.basename(path)} ===')
        print(f'  files={info["file_count"]} flags=0x{info["file_flags"]:02x}')
        # Group by extension
        from collections import Counter
        ext_counts = Counter()
        for e in info['entries']:
            name = e['name']
            if '.' in name.rsplit('\\', 1)[-1]:
                ext = name.rsplit('.', 1)[-1].lower()
            else:
                ext = '<noext>'
            ext_counts[ext] += 1
        print(f'  extensions: {dict(ext_counts)}')
        # Show first 10 entries
        for e in info['entries'][:10]:
            print(f'    [{e["id"]:>5}] off=0x{e["data_offset"]:08x} '
                  f'csize={e["compressed_size"]:>8} usize={e["uncompressed_size"]:>8} '
                  f'{e["name"][-60:]}')
        if info['file_count'] > 10:
            print(f'    ... and {info["file_count"] - 10} more')
