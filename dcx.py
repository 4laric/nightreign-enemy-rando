#!/usr/bin/env python3
"""
dcx.py — Standalone DCX (Sekiro/ER/NR) compressor/decompressor.

Replaces the Yabber/Witchy step. Uses the Oodle DLL via ctypes (shipped with
NR/ER/Sekiro, no Anthropic-side bundling needed).

Format — empirically verified against m48_50_00_00.msb.dcx:
    Offset  Type        Field           Value (typical for NR)
    0x00    char[4]     magic           'DCX\\0'
    0x04    u32 BE      version         0x00011000
    0x08    u32 BE      dcs_offset      0x18
    0x0c    u32 BE      dcp_offset      0x24
    0x10    u32 BE      dca_offset      0x44
    0x14    u32 BE      data_offset     0x4C

    0x18    char[4]     dcs_magic       'DCS\\0'
    0x1c    u32 BE      uncompressed
    0x20    u32 BE      compressed

    0x24    char[4]     dcp_magic       'DCP\\0'
    0x28    char[4]     compression     'KRAK' (NR), 'DFLT' (older), 'EDGE' (DS3)
    0x2c    u32 BE      dcp_size        0x20
    0x30    u8          level           6 (NR uses level 6)
    0x31..  u8[3]       padding
    0x34    u32         zero
    0x38    u32         zero
    0x3c    u32         zero
    0x40    u32 BE      flags           0x00010100

    0x44    char[4]     dca_magic       'DCA\\0'
    0x48    u32 BE      dca_size        0x08

    0x4c    bytes       compressed payload, length = compressed

Usage:
    from dcx import DCX
    raw_bytes = DCX.decompress_file('foo.msb.dcx')
    DCX.compress_file('foo.msb', 'foo.msb.dcx')
"""
import ctypes, os, struct, sys
from ctypes import c_int, c_int64, c_void_p, c_char_p, POINTER, c_ubyte


# --- Oodle binding -------------------------------------------------------

# OodleLZ_Compressor enum values (from Oodle headers)
OODLE_KRAKEN  = 8   # 'KRAK'
OODLE_LEVIATHAN = 13  # 'LEVI' (newer titles)
OODLE_LZNA    = 6   # 'LZNA'
OODLE_LZB16   = 14
OODLE_FUZZ_SAFE_YES = 1
OODLE_FUZZ_SAFE_NO  = 0
OODLE_CHECK_CRC_NO  = 0
OODLE_CHECK_CRC_YES = 1
OODLE_VERBOSITY_NONE = 0

# Compression level for OodleLZ_Compress
OODLE_LEVEL_NORMAL = 4
OODLE_LEVEL_OPTIMAL2 = 6  # v0.24.111: game-shipping level for From titles
OODLE_LEVEL_OPTIMAL5 = 9


def _oodle_not_found_message() -> str:
    """Build a context-aware error message for the missing-Oodle case.

    Looks at the environment to give a specific actionable next step:
    if Nightreign or Elden Ring is detected on Steam, point the user at
    the DLL they already own; otherwise fall back to a manual-acquisition
    explanation. The goal is "user reads the error, knows the one thing
    to do next" — not a generic 'set the env var or place the DLL'
    list of all possibilities.
    """
    # Try to identify a source game that already has the DLL
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(here, 'dev'))
        import install_discovery
        nr = install_discovery.find_nightreign_install()
        er = install_discovery.find_elden_ring_install()
    except Exception:
        nr, er = None, None

    msg = "Oodle DLL not found.\n\n"
    msg += ("This rando needs oo2core_*.dll to compress/decompress NR's "
            ".dcx files.\n")
    msg += "It's the same DLL that ships with NR/ER/Sekiro Steam installs.\n\n"

    if nr:
        msg += "Easiest fix — copy from your Nightreign install:\n"
        msg += f"  Source: {nr}/oo2core_*_win64.dll\n"
        msg += f"  Dest:   {os.path.dirname(os.path.abspath(__file__))}\n"
        msg += ("  Or programmatically: "
                "`python3 -c \"import sys; sys.path.insert(0, 'dev'); "
                "import install_discovery; "
                "print(install_discovery.copy_oodle_dll_local())\"`\n")
    elif er:
        msg += "Easiest fix — copy from your Elden Ring install:\n"
        msg += f"  Source: {er}/oo2core_*_win64.dll\n"
        msg += f"  Dest:   {os.path.dirname(os.path.abspath(__file__))}\n"
    else:
        msg += ("No NR/ER Steam install auto-detected. Options:\n"
                "  1. If you own NR/ER, copy oo2core_*_win64.dll from\n"
                "     <install>/Game/ into this folder.\n"
                "  2. Set the OODLE_DLL environment variable to a full\n"
                "     path to an oo2core_*_win64.dll you already have.\n"
                "  3. Run install_discovery to check what was auto-detected:\n"
                "     `python3 dev/install_discovery.py`\n")
    return msg


class _Oodle:
    """ctypes wrapper for OodleLZ_Compress / OodleLZ_Decompress."""

    _instance = None

    @classmethod
    def get(cls, dll_path=None):
        if cls._instance is None:
            cls._instance = cls(dll_path)
        return cls._instance

    def __init__(self, dll_path=None):
        if dll_path is None:
            dll_path = self._auto_find()
        if dll_path is None or not os.path.exists(dll_path):
            raise FileNotFoundError(_oodle_not_found_message())
        self.dll_path = dll_path
        self.dll = ctypes.CDLL(dll_path)

        # OodleLZ_Decompress signature:
        # SINTa OodleLZ_Decompress (
        #   const void* compBuf, SINTa compBufSize,
        #   void*       rawBuf,  SINTa rawLen,
        #   OodleLZ_FuzzSafe   fuzzSafe = Yes,
        #   OodleLZ_CheckCRC   checkCRC = No,
        #   OodleLZ_Verbosity  verbosity = None,
        #   void* decBufBase = NULL, SINTa decBufSize = 0,
        #   t_OodleDecompressCallback* fpCallback = NULL, void* userdata = NULL,
        #   void* decoderMemory = NULL, SINTa decoderMemorySize = 0,
        #   OodleLZ_Decode_ThreadPhase threadPhase = Unthreaded);
        self.dll.OodleLZ_Decompress.argtypes = [
            c_void_p, c_int64,           # compBuf, compBufSize
            c_void_p, c_int64,           # rawBuf, rawLen
            c_int, c_int, c_int,         # fuzzSafe, checkCRC, verbosity
            c_void_p, c_int64,           # decBufBase, decBufSize
            c_void_p, c_void_p,          # callback, userdata
            c_void_p, c_int64,           # decoderMemory, decoderMemorySize
            c_int                        # threadPhase
        ]
        self.dll.OodleLZ_Decompress.restype = c_int64

        # OodleLZ_Compress signature:
        # SINTa OodleLZ_Compress (
        #   OodleLZ_Compressor compressor, const void* rawBuf, SINTa rawLen,
        #   void* compBuf, OodleLZ_CompressionLevel level,
        #   const OodleLZ_CompressOptions* options = NULL,
        #   const void* dictionaryBase = NULL, const void* lrm = NULL,
        #   void* scratch = NULL, SINTa scratchSize = 0);
        self.dll.OodleLZ_Compress.argtypes = [
            c_int,                       # compressor enum
            c_void_p, c_int64,           # rawBuf, rawLen
            c_void_p,                    # compBuf
            c_int,                       # level
            c_void_p,                    # options
            c_void_p, c_void_p,          # dictionaryBase, lrm
            c_void_p, c_int64,           # scratch, scratchSize
        ]
        self.dll.OodleLZ_Compress.restype = c_int64

        # OodleLZ_GetCompressedBufferSizeNeeded(compressor, rawSize) — gives upper bound
        self.dll.OodleLZ_GetCompressedBufferSizeNeeded.argtypes = [c_int, c_int64]
        self.dll.OodleLZ_GetCompressedBufferSizeNeeded.restype = c_int64

    @staticmethod
    def _auto_find():
        """Try a few common locations and any oo2core_*_win64.dll filename.

        NR actually ships oo2core_9_win64.dll. Yabber is built against the name
        oo2core_6_win64.dll, so users sometimes rename it for Yabber's sake. Our
        code loads any version — the OodleLZ_* ABI is stable across 2.x versions.

        v0.26.x: delegated to install_discovery.find_oodle_dll() which
        does the same env-var → local → game-install search, but using
        Steam's libraryfolders.vdf for the game-install step instead of
        hardcoded Windows paths. Falls back to the legacy hardcoded
        glob if install_discovery is unavailable (defense-in-depth in
        case of a future import-cycle or move).
        """
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, os.path.join(here, 'dev'))
            import install_discovery
            hit = install_discovery.find_oodle_dll()
            if hit:
                return hit
        except Exception:
            pass

        # Legacy fallback: env var + alongside-this-script only. The
        # Steam-paths-on-Windows scan that used to live here is now in
        # install_discovery; if discovery is unavailable we skip the
        # scan rather than maintain two copies of it.
        import glob
        env = os.environ.get('OODLE_DLL')
        if env and os.path.exists(env):
            return env
        here = os.path.dirname(os.path.abspath(__file__))
        local = sorted(glob.glob(os.path.join(here, 'oo2core_*_win64.dll')),
                       reverse=True)
        if local:
            return local[0]
        return None

    def decompress(self, comp_data: bytes, uncompressed_size: int) -> bytes:
        out = (c_ubyte * uncompressed_size)()
        comp_buf = (c_ubyte * len(comp_data)).from_buffer_copy(comp_data)
        n = self.dll.OodleLZ_Decompress(
            ctypes.cast(comp_buf, c_void_p), len(comp_data),
            ctypes.cast(out, c_void_p), uncompressed_size,
            OODLE_FUZZ_SAFE_YES, OODLE_CHECK_CRC_NO, OODLE_VERBOSITY_NONE,
            None, 0, None, None, None, 0, 0)
        if n != uncompressed_size:
            raise RuntimeError(
                f"OodleLZ_Decompress returned {n}, expected {uncompressed_size}")
        return bytes(out)

    def compress(self, raw: bytes,
                  compressor: int = OODLE_KRAKEN,
                  level: int = OODLE_LEVEL_OPTIMAL5) -> bytes:
        max_size = self.dll.OodleLZ_GetCompressedBufferSizeNeeded(compressor, len(raw))
        if max_size <= 0:
            # Older Oodle: GetCompressedBufferSizeNeeded takes one arg (rawSize) only.
            # Fallback: compute upper bound manually (rawLen + 274 per ~256KB block).
            max_size = len(raw) + ((len(raw) + 0x3FFFF) // 0x40000) * 274 + 274
        out = (c_ubyte * max_size)()
        in_buf = (c_ubyte * len(raw)).from_buffer_copy(raw)
        n = self.dll.OodleLZ_Compress(
            compressor,
            ctypes.cast(in_buf, c_void_p), len(raw),
            ctypes.cast(out, c_void_p), level,
            None, None, None, None, 0)
        if n <= 0:
            raise RuntimeError(f"OodleLZ_Compress returned {n}")
        return bytes(out[:n])


# --- DCX wrapper ---------------------------------------------------------

class DCX:
    """Read and write .msb.dcx (and other DCX-wrapped) files."""

    HEADER_SIZE = 0x4C
    DEFAULT_VERSION = 0x00011000
    DEFAULT_DCS_OFFSET = 0x18
    DEFAULT_DCP_OFFSET = 0x24
    DEFAULT_DCA_OFFSET = 0x44
    DEFAULT_DATA_OFFSET = 0x4C
    DEFAULT_DCP_SIZE = 0x20
    DEFAULT_DCA_SIZE = 0x08
    DEFAULT_FLAGS = 0x00010100

    def __init__(self, raw: bytes, compression: bytes = b'KRAK', level: int = 6):
        self.raw = raw
        self.compression = compression
        self.level = level

    @staticmethod
    def decompress_file(path: str, oodle: _Oodle = None) -> bytes:
        with open(path, 'rb') as f: data = f.read()
        return DCX.decompress_bytes(data, oodle)

    @staticmethod
    def decompress_bytes(data: bytes, oodle: _Oodle = None) -> bytes:
        if data[:4] != b'DCX\x00':
            raise ValueError(f"Not a DCX file (magic={data[:4]!r})")
        # Read big-endian header fields
        version       = struct.unpack('>I', data[0x04:0x08])[0]
        dcs_offset    = struct.unpack('>I', data[0x08:0x0c])[0]
        dcp_offset    = struct.unpack('>I', data[0x0c:0x10])[0]
        dca_offset    = struct.unpack('>I', data[0x10:0x14])[0]
        data_offset   = struct.unpack('>I', data[0x14:0x18])[0]

        if data[dcs_offset:dcs_offset+4] != b'DCS\x00':
            raise ValueError(f"Bad DCS magic at 0x{dcs_offset:x}")
        uncompressed_size = struct.unpack('>I', data[dcs_offset+4:dcs_offset+8])[0]
        compressed_size   = struct.unpack('>I', data[dcs_offset+8:dcs_offset+12])[0]

        if data[dcp_offset:dcp_offset+4] != b'DCP\x00':
            raise ValueError(f"Bad DCP magic at 0x{dcp_offset:x}")
        compression = data[dcp_offset+4:dcp_offset+8]

        if data[dca_offset:dca_offset+4] != b'DCA\x00':
            raise ValueError(f"Bad DCA magic at 0x{dca_offset:x}")

        comp_payload = data[data_offset:data_offset + compressed_size]
        if len(comp_payload) != compressed_size:
            raise ValueError(
                f"Truncated payload: got {len(comp_payload)}, expected {compressed_size}")

        if compression == b'KRAK':
            if oodle is None: oodle = _Oodle.get()
            return oodle.decompress(comp_payload, uncompressed_size)
        elif compression == b'DFLT':
            import zlib
            return zlib.decompress(comp_payload)
        else:
            raise NotImplementedError(f"Compression type {compression!r} not implemented")

    @staticmethod
    def compress_file(in_path: str, out_path: str,
                       compression: bytes = b'KRAK', level: int = 6,
                       oodle: _Oodle = None):
        with open(in_path, 'rb') as f: raw = f.read()
        out = DCX.compress_bytes(raw, compression, level, oodle)
        with open(out_path, 'wb') as f: f.write(out)

    @staticmethod
    def compress_bytes(raw: bytes, compression: bytes = b'KRAK', level: int = OODLE_LEVEL_OPTIMAL2,
                        oodle: _Oodle = None) -> bytes:
        # v0.24.111: switched default from OPTIMAL5 (level=9, aggressive)
        # to OPTIMAL2 (level=6, game-shipping). Playtest report: post-
        # splice item_dlc01.msgbnd.dcx still showed "?NpcName?" in-game
        # despite splice reporting success and writing the correct bytes
        # (47% smaller than vanilla due to OPTIMAL5 being more aggressive
        # than NR's shipping compression). Hypothesis: NR's DCX loader
        # rejects compression levels that don't match its expected range,
        # OR the level byte we write into the DCX header (0x30) must
        # match the actual level used. OPTIMAL2 is the typical FROM
        # shipping level and pairs with our existing header level=6.
        # If this works, "?NpcName?" goes away; if not, the issue is
        # elsewhere (me3 not loading msg files, etc.).
        if compression == b'KRAK':
            if oodle is None: oodle = _Oodle.get()
            comp = oodle.compress(raw, OODLE_KRAKEN, level)
        elif compression == b'DFLT':
            import zlib
            comp = zlib.compress(raw, 9)
        else:
            raise NotImplementedError(f"Compression type {compression!r} not implemented")

        # Build the DCX wrapper bytes
        out = bytearray(DCX.HEADER_SIZE + len(comp))
        out[0:4] = b'DCX\x00'
        struct.pack_into('>I', out, 0x04, DCX.DEFAULT_VERSION)
        struct.pack_into('>I', out, 0x08, DCX.DEFAULT_DCS_OFFSET)
        struct.pack_into('>I', out, 0x0c, DCX.DEFAULT_DCP_OFFSET)
        struct.pack_into('>I', out, 0x10, DCX.DEFAULT_DCA_OFFSET)
        struct.pack_into('>I', out, 0x14, DCX.DEFAULT_DATA_OFFSET)

        out[0x18:0x1c] = b'DCS\x00'
        struct.pack_into('>I', out, 0x1c, len(raw))
        struct.pack_into('>I', out, 0x20, len(comp))

        out[0x24:0x28] = b'DCP\x00'
        out[0x28:0x2c] = compression
        struct.pack_into('>I', out, 0x2c, DCX.DEFAULT_DCP_SIZE)
        out[0x30] = level  # v0.24.111: now honestly reflects the level used
        # 0x31..0x33 already zero
        # 0x34..0x3c zero (3 u32s)
        struct.pack_into('>I', out, 0x40, DCX.DEFAULT_FLAGS)

        out[0x44:0x48] = b'DCA\x00'
        struct.pack_into('>I', out, 0x48, DCX.DEFAULT_DCA_SIZE)

        out[DCX.HEADER_SIZE:] = comp
        # v0.24.111: pad to 16-byte alignment after the compressed payload.
        # Stock NR DCX files have trailing zero padding so the total file
        # size is a multiple of 16. Without this padding, NR's loader
        # rejects the file (symptom: "?NpcName?" in healthbars).
        # Confirmed by byte-diffing genuine UXM-unpacked vanilla against
        # our rando output: vanilla had +1 trailing zero, ours had 0
        # (both KRAK/6, otherwise byte-identical headers).
        result = bytes(out)
        align = 16
        pad = (align - len(result) % align) % align
        if pad:
            result = result + b'\x00' * pad
        return result


# --- CLI -----------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCommands:")
        print("  dcx.py decompress <input.dcx> [output]")
        print("  dcx.py compress <input> [output.dcx]")
        print("  dcx.py roundtrip <input.dcx>     (verify decompress→compress→decompress matches)")
        print("  dcx.py info <input.dcx>          (just print header fields)")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'info':
        with open(sys.argv[2], 'rb') as f: data = f.read()
        magic = data[:4]
        if magic != b'DCX\x00':
            print(f"Not DCX (magic={magic!r})"); sys.exit(1)
        ver = struct.unpack('>I', data[0x04:0x08])[0]
        dcs_off = struct.unpack('>I', data[0x08:0x0c])[0]
        dcp_off = struct.unpack('>I', data[0x0c:0x10])[0]
        dca_off = struct.unpack('>I', data[0x10:0x14])[0]
        data_off = struct.unpack('>I', data[0x14:0x18])[0]
        u_size = struct.unpack('>I', data[dcs_off+4:dcs_off+8])[0]
        c_size = struct.unpack('>I', data[dcs_off+8:dcs_off+12])[0]
        compr = data[dcp_off+4:dcp_off+8]
        print(f"  File size: {len(data):,} bytes")
        print(f"  Version: 0x{ver:08x}")
        print(f"  Compression: {compr.decode('ascii', errors='replace')}")
        print(f"  Uncompressed: {u_size:,} bytes")
        print(f"  Compressed:   {c_size:,} bytes (ratio {c_size/u_size*100:.1f}%)")
        print(f"  Offsets: dcs=0x{dcs_off:x} dcp=0x{dcp_off:x} dca=0x{dca_off:x} data=0x{data_off:x}")

    elif cmd == 'decompress':
        in_path = sys.argv[2]
        out_path = sys.argv[3] if len(sys.argv) > 3 else in_path.replace('.dcx','')
        if out_path == in_path:
            out_path = in_path + '.decompressed'
        raw = DCX.decompress_file(in_path)
        with open(out_path, 'wb') as f: f.write(raw)
        print(f"Decompressed {in_path} → {out_path} ({len(raw):,} bytes)")

    elif cmd == 'compress':
        in_path = sys.argv[2]
        out_path = sys.argv[3] if len(sys.argv) > 3 else in_path + '.dcx'
        DCX.compress_file(in_path, out_path)
        print(f"Compressed {in_path} → {out_path}")

    elif cmd == 'roundtrip':
        in_path = sys.argv[2]
        with open(in_path, 'rb') as f: orig_dcx = f.read()
        # Decompress
        raw = DCX.decompress_bytes(orig_dcx)
        # Recompress
        re_dcx = DCX.compress_bytes(raw)
        # Decompress again
        raw2 = DCX.decompress_bytes(re_dcx)
        # Verify
        if raw == raw2:
            print(f"✅ Roundtrip OK: {in_path}")
            print(f"   Original DCX:    {len(orig_dcx):,} bytes")
            print(f"   Decompressed:    {len(raw):,} bytes")
            print(f"   Recompressed:    {len(re_dcx):,} bytes")
            if len(re_dcx) != len(orig_dcx):
                print(f"   Note: re-compressed size differs ({len(re_dcx)} vs {len(orig_dcx)}) — "
                      f"that's normal, Oodle output isn't guaranteed bit-identical across runs, "
                      f"as long as it decompresses correctly.")
        else:
            print(f"❌ Roundtrip FAILED: decompressed payloads differ")
            sys.exit(1)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()