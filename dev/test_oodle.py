#!/usr/bin/env python3
"""
test_oodle.py — Run this on Windows to verify the Oodle DLL integration works.

Place this script alongside:
    dcx.py
    oo2core_6_win64.dll  (from your NR install — Game/oo2core_*.dll)
    a sample .msb.dcx file

Usage:
    python test_oodle.py path/to/some.msb.dcx
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if len(sys.argv) != 2:
    print("Usage: test_oodle.py <some.msb.dcx>"); sys.exit(1)

dcx_path = sys.argv[1]
if not os.path.exists(dcx_path):
    print(f"File not found: {dcx_path}"); sys.exit(1)

print(f"=== Test 1: Locate Oodle DLL ===")
from dcx import _Oodle, DCX
try:
    oodle = _Oodle.get()
    print(f"  ✅ Loaded: {oodle.dll_path}")
except FileNotFoundError as e:
    print(f"  ❌ {e}")
    sys.exit(1)

print(f"\n=== Test 2: Read DCX header ===")
with open(dcx_path, 'rb') as f: orig = f.read()
print(f"  File size: {len(orig):,} bytes")
import struct
print(f"  Magic: {orig[:4]!r}")
print(f"  Compression: {orig[0x28:0x2c]!r}")
u_size = struct.unpack('>I', orig[0x1c:0x20])[0]
c_size = struct.unpack('>I', orig[0x20:0x24])[0]
print(f"  Uncompressed: {u_size:,}  Compressed: {c_size:,}")

print(f"\n=== Test 3: Decompress ===")
try:
    raw = DCX.decompress_bytes(orig, oodle)
    print(f"  ✅ Decompressed to {len(raw):,} bytes")
    print(f"  First 16 bytes: {raw[:16]!r}")
    if raw[:4] == b'MSB ':
        print(f"  ✅ Looks like a valid MSB file")
    else:
        print(f"  ⚠️ Doesn't start with 'MSB ' — may not be an MSB but decompression worked")
except Exception as e:
    print(f"  ❌ Decompression failed: {e}")
    sys.exit(1)

print(f"\n=== Test 4: Recompress ===")
try:
    re_dcx = DCX.compress_bytes(raw, oodle=oodle)
    print(f"  ✅ Recompressed to {len(re_dcx):,} bytes (orig was {len(orig):,})")
except Exception as e:
    print(f"  ❌ Compression failed: {e}")
    sys.exit(1)

print(f"\n=== Test 5: Roundtrip verify (decompress recompressed → matches original raw?) ===")
try:
    raw2 = DCX.decompress_bytes(re_dcx, oodle)
    if raw == raw2:
        print(f"  ✅ Roundtrip identical: {len(raw):,} bytes match perfectly")
    else:
        print(f"  ❌ Roundtrip MISMATCH: {len(raw)} vs {len(raw2)} or content differs")
        sys.exit(1)
except Exception as e:
    print(f"  ❌ Roundtrip decompression failed: {e}")
    sys.exit(1)

print(f"\n🎉 All tests passed. The DCX layer is working correctly on this machine.")
print(f"   You can now use:")
print(f"     python dcx_batch.py decompress <vanilla_dcx_dir> <output_msb_dir>")
print(f"     python dcx_batch.py compress <input_msb_dir> <output_dcx_dir>")
print(f"     python dcx_batch.py rando <vanilla_dcx_dir> <out_dcx_dir> --seed 42")
