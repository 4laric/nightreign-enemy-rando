"""bnd.py — BND4 parser and writer for the NR Sekiro+ variant.

The format-spec was derived empirically from
`reference/Data0_15912862698882586866.fmg.bnd` (the engUS Item bundle
containing NpcName.fmg and friends). See `reference/README.md` for
the chain of evidence behind each field interpretation.

Header layout (0x40 bytes total):
  +0x00  4s   magic "BND4"
  +0x04  4s   flags (0 in our reference)
  +0x08  4s   more flags
  +0x0C  u32  file_count
  +0x10  u64  header_size (0x40)
  +0x18  8s   timestamp ("07D7R6\0\0" or similar)
  +0x20  u64  per_entry_size (36 in our reference)
  +0x28  u64  file_table_size (entries + name strings combined)
  +0x30  u64  data_start_alignment (where the first packed data block
              begins, after some alignment padding; not used for offset
              computation since per-entry data_offset is absolute)
  +0x38  u32  format_flags (0x10000024 in our reference)
  +0x3C  u32  pad (0)

Entry layout (36 bytes):
  +0x00  u32  raw_flags (0x40)
  +0x04  i32  sentinel (-1)
  +0x08  u64  compressed_size
  +0x10  u64  uncompressed_size (equal to compressed when not compressed)
  +0x18  u32  data_offset (ABSOLUTE file offset, not relative)
  +0x1C  u32  fmg_id (numeric id used by entry indexing)
  +0x20  u32  name_offset (absolute file offset to UTF-16 LE null-
              terminated name string)

Name strings: UTF-16 LE null-terminated. Stored sequentially in the
names region between the entry table and the data section. Each
entry's name_offset points to the start of its name.

This module supports a strict round-trip: read a BND, write it back,
the bytes match exactly. That's the correctness benchmark — if the
round-trip fails, splice/repack of NpcName.fmg will produce a broken
container that the game can't read.
"""

import struct
from dataclasses import dataclass


BND4_MAGIC = b'BND4'
SENTINEL_M1 = -1
EXPECTED_HEADER_SIZE = 0x40
EXPECTED_ENTRY_SIZE = 36


@dataclass
class BNDEntry:
    """One file inside the BND. Pure data class — no parsing logic."""
    name: str
    data: bytes
    fmg_id: int
    raw_flags: int = 0x40

    # Internal: original positions (for round-trip exact match)
    _orig_data_offset: int = None
    _orig_name_offset: int = None


@dataclass
class BND4:
    """Parsed BND4 container. Round-trips losslessly if untouched."""
    # Header metadata that's not derivable from entries:
    flags_04: bytes = b'\x00\x00\x00\x00'
    flags_08: bytes = b'\x00\x00\x01\x00'
    timestamp: bytes = b'07D7R6\x00\x00'
    per_entry_size: int = EXPECTED_ENTRY_SIZE
    file_table_size: int = 0  # entries + names + padding to next 16-byte boundary
    data_start: int = 0
    format_flags: int = 0x10000024

    entries: list = None  # list[BNDEntry]

    def __post_init__(self):
        if self.entries is None:
            self.entries = []


def parse_bnd4(raw: bytes) -> BND4:
    """Parse a NR-style BND4 file."""
    if raw[0:4] != BND4_MAGIC:
        raise ValueError(f"not a BND4 file (magic {raw[0:4]!r})")

    bnd = BND4()
    bnd.flags_04 = raw[0x04:0x08]
    bnd.flags_08 = raw[0x08:0x0C]
    file_count = struct.unpack_from('<I', raw, 0x0C)[0]
    header_size = struct.unpack_from('<Q', raw, 0x10)[0]
    bnd.timestamp = raw[0x18:0x20]
    bnd.per_entry_size = struct.unpack_from('<Q', raw, 0x20)[0]
    bnd.file_table_size = struct.unpack_from('<Q', raw, 0x28)[0]
    bnd.data_start = struct.unpack_from('<Q', raw, 0x30)[0]
    bnd.format_flags = struct.unpack_from('<I', raw, 0x38)[0]

    if header_size != EXPECTED_HEADER_SIZE:
        raise ValueError(
            f"unexpected header_size 0x{header_size:x} (expected 0x{EXPECTED_HEADER_SIZE:x})"
        )
    if bnd.per_entry_size != EXPECTED_ENTRY_SIZE:
        raise ValueError(
            f"unexpected per_entry_size {bnd.per_entry_size} (expected {EXPECTED_ENTRY_SIZE})"
        )

    entries = []
    for i in range(file_count):
        eoff = header_size + i * bnd.per_entry_size
        raw_flags = struct.unpack_from('<I', raw, eoff + 0x00)[0]
        sentinel = struct.unpack_from('<i', raw, eoff + 0x04)[0]
        if sentinel != SENTINEL_M1:
            raise ValueError(
                f"entry {i} sentinel != -1: got 0x{sentinel:x}"
            )
        csize = struct.unpack_from('<Q', raw, eoff + 0x08)[0]
        dsize = struct.unpack_from('<Q', raw, eoff + 0x10)[0]
        data_off = struct.unpack_from('<I', raw, eoff + 0x18)[0]
        fmg_id = struct.unpack_from('<I', raw, eoff + 0x1C)[0]
        name_off = struct.unpack_from('<I', raw, eoff + 0x20)[0]

        # Read name (UTF-16 LE, null-terminated)
        j = name_off
        chars = []
        while j < len(raw) - 1:
            c = struct.unpack_from('<H', raw, j)[0]
            if c == 0:
                break
            chars.append(c)
            j += 2
        name = ''.join(chr(c) for c in chars)

        # Read data
        data = bytes(raw[data_off:data_off + dsize])
        if len(data) != dsize:
            raise ValueError(
                f"entry {i} ({name!r}) truncated: expected {dsize} bytes "
                f"at 0x{data_off:x}, got {len(data)}"
            )
        # csize == dsize in NR (no per-entry compression)
        if csize != dsize:
            raise ValueError(
                f"entry {i} ({name!r}) csize {csize} != dsize {dsize}; "
                f"compressed entries not supported"
            )

        entries.append(BNDEntry(
            name=name, data=data, fmg_id=fmg_id, raw_flags=raw_flags,
            _orig_data_offset=data_off, _orig_name_offset=name_off,
        ))
    bnd.entries = entries
    return bnd


def write_bnd4(bnd: BND4, original_raw: bytes = None, relocations: dict = None,
               repack: bool = False) -> bytes:
    """Serialize a BND4 back to bytes.

    Modes:
      1. **Round-trip preserving** (`original_raw` provided, no
         `relocations`, no `repack`): byte-perfect output. v0.24.7 demo.
      2. **Append-at-end with relocation** (`original_raw` + `relocations`):
         the entries listed in `relocations` get fresh data_offset
         values past the end of `original_raw`, and the output file
         grows accordingly. Other entries keep their original
         positions verbatim, as does the name-strings region and the
         BND4 hash table (whose contents are name-based, not offset-
         based; so relocating data bytes doesn't invalidate it).
         IMPORTANT: NR's loader REJECTS files produced this way. The
         appended-at-end layout breaks something in the loader's
         validation. Use `repack=True` instead.
      3. **Full repack** (`original_raw` + `repack=True`, modified entry
         data already on entries): rewrite the file with all entries
         laid out contiguously in their original order (by data_off).
         Entry data uses whatever bytes are currently on the BNDEntry
         objects. Resulting file mirrors vanilla BND4 layout — no
         relocation tricks, no dead bytes. Entries after a grown entry
         shift forward by the growth amount. This is the layout NR's
         loader expects and accepts.

    For NpcName splice with growth: set the new bytes on the entry
    (`npcname_entry.data = new_fmg_bytes`) and call with `repack=True`.
    """
    file_count = len(bnd.entries)

    if original_raw is None:
        raise NotImplementedError(
            "fresh BND4 layout not implemented yet — pass original_raw."
        )

    relocations = relocations or {}

    if repack:
        return _write_bnd4_repack(bnd, original_raw)

    # Phase 1: compute append region. Each relocated entry gets a
    # fresh offset starting at end-of-original-file, padded to 16-
    # byte alignment between entries (matching observed BND4 conv).
    appended_blocks = []  # list of (name, bytes, offset_in_output)
    cursor = len(original_raw)
    # Align cursor to 16-byte boundary
    if cursor % 16 != 0:
        cursor = (cursor + 15) & ~15
    for entry_name, new_data in relocations.items():
        # Look up the entry to confirm it exists
        e = next((x for x in bnd.entries if x.name == entry_name), None)
        if e is None:
            raise ValueError(f"relocation target {entry_name!r} not in BND entries")
        appended_blocks.append((entry_name, new_data, cursor))
        cursor += len(new_data)
        # Align next entry's start
        if cursor % 16 != 0:
            cursor = (cursor + 15) & ~15

    total_size = cursor
    out = bytearray(total_size)
    out[:len(original_raw)] = original_raw

    # Phase 2: write appended data
    for entry_name, new_data, off in appended_blocks:
        out[off:off + len(new_data)] = new_data

    # Phase 3: build a lookup of name -> (new_offset, new_size) for
    # relocated entries.
    relocation_map = {
        name: (off, len(data))
        for name, data, off in appended_blocks
    }

    # Phase 4: overwrite header
    out[0x00:0x04] = BND4_MAGIC
    out[0x04:0x08] = bnd.flags_04
    out[0x08:0x0C] = bnd.flags_08
    struct.pack_into('<I', out, 0x0C, file_count)
    struct.pack_into('<Q', out, 0x10, EXPECTED_HEADER_SIZE)
    out[0x18:0x20] = bnd.timestamp.ljust(8, b'\x00')[:8]
    struct.pack_into('<Q', out, 0x20, bnd.per_entry_size)
    struct.pack_into('<Q', out, 0x28, bnd.file_table_size)
    struct.pack_into('<Q', out, 0x30, bnd.data_start)
    struct.pack_into('<I', out, 0x38, bnd.format_flags)
    struct.pack_into('<I', out, 0x3C, 0)

    # Phase 5: overwrite each entry record
    for i, e in enumerate(bnd.entries):
        if e._orig_data_offset is None or e._orig_name_offset is None:
            raise NotImplementedError(
                f"entry {i} ({e.name!r}) lacks original offsets"
            )
        eoff = EXPECTED_HEADER_SIZE + i * bnd.per_entry_size
        struct.pack_into('<I', out, eoff + 0x00, e.raw_flags)
        struct.pack_into('<i', out, eoff + 0x04, SENTINEL_M1)

        # If this entry is being relocated, use the new offset/size
        if e.name in relocation_map:
            new_off, new_size = relocation_map[e.name]
            struct.pack_into('<Q', out, eoff + 0x08, new_size)
            struct.pack_into('<Q', out, eoff + 0x10, new_size)
            struct.pack_into('<I', out, eoff + 0x18, new_off)
            struct.pack_into('<I', out, eoff + 0x1C, e.fmg_id)
            struct.pack_into('<I', out, eoff + 0x20, e._orig_name_offset)
            # Note: we leave the original data slot intact in `out`.
            # Those bytes become dead — game won't read them since
            # the entry now points to the appended region.
        else:
            # Unchanged entry: keep original positions and sizes
            struct.pack_into('<Q', out, eoff + 0x08, len(e.data))
            struct.pack_into('<Q', out, eoff + 0x10, len(e.data))
            struct.pack_into('<I', out, eoff + 0x18, e._orig_data_offset)
            struct.pack_into('<I', out, eoff + 0x1C, e.fmg_id)
            struct.pack_into('<I', out, eoff + 0x20, e._orig_name_offset)
            # Only overwrite data if it's different from the original
            # (and fits in the slot). For untouched entries with
            # unmodified data, the bytes are already correct from
            # the original_raw copy.
            if len(e.data) > _slot_capacity(bnd, i, len(original_raw)):
                raise ValueError(
                    f"entry {i} ({e.name!r}) new data is {len(e.data)} bytes "
                    f"but original slot holds at most {_slot_capacity(bnd, i, len(original_raw))} "
                    f"— either pass via `relocations` to append at end, or shrink."
                )
            out[e._orig_data_offset:e._orig_data_offset + len(e.data)] = e.data
            original_dsize = _original_dsize(bnd, original_raw, i)
            if len(e.data) < original_dsize:
                slack_start = e._orig_data_offset + len(e.data)
                slack_end = e._orig_data_offset + original_dsize
                for k in range(slack_start, slack_end):
                    out[k] = 0

    return bytes(out)


def _write_bnd4_repack(bnd: BND4, original_raw: bytes) -> bytes:
    """Repack the BND4 with contiguous entry layout. Entries are placed
    in order of their original data_off, using whatever bytes are
    currently on the BNDEntry.data field. Subsequent entries shift
    forward if any entry grows beyond its original size.

    Layout invariants preserved from original_raw:
      - BND4 header (0x00-0x40)
      - file_table entries' raw_flags, sentinel, fmg_id, name_off fields
      - Name strings region (immediately after file_table)
      - Hash table region (between name strings and data_start)
      - First entry's data_off (preserved from original)
      - Relative order of entries by data_off
      - 16-byte alignment of each entry's data_off

    What changes:
      - Each entry's dsize/csize field reflects len(e.data) for that
        entry (may differ from original_raw if a caller modified the
        bytes)
      - Each entry's data_off may shift forward (never backward) by
        the cumulative growth of any preceding-by-offset entries

    The resulting file mimics a vanilla BND4's layout — entries laid
    out tightly in increasing data_off, no dead bytes, no relocation
    appendix. This is the layout NR's loader expects.
    """
    file_count = len(bnd.entries)

    # Sort entries by their original data_off, keeping their original
    # index (which is what entry-record position uses).
    by_offset = sorted(
        enumerate(bnd.entries),
        key=lambda pair: pair[1]._orig_data_offset,
    )

    # The first entry by offset keeps its original data_off. We then
    # walk forward, placing each entry at the next 16-byte-aligned
    # position past the previous entry's end. Build a map of
    # original_index -> (new_offset, new_size).
    new_layout = {}  # original_idx -> (new_offset, new_size)
    cursor = by_offset[0][1]._orig_data_offset  # anchor at first entry's original off
    for original_idx, e in by_offset:
        size = len(e.data)
        new_layout[original_idx] = (cursor, size)
        cursor += size
        # Align next entry to 16-byte boundary (BND4 convention)
        if cursor % 16 != 0:
            cursor = (cursor + 15) & ~15

    # Total file size is the cursor position after laying out all
    # entries (the last alignment step may have advanced past the last
    # entry's end; that trailing padding is fine and matches what
    # vanilla files contain).
    total_size = cursor

    out = bytearray(total_size)
    # Copy header + file_table + name strings + hash table from original.
    # data_start is where data begins in the original; that's the boundary.
    data_start = bnd.data_start
    if data_start > len(original_raw):
        raise ValueError(
            f"data_start {data_start:#x} exceeds original_raw length "
            f"{len(original_raw):#x}; cannot repack"
        )
    out[:data_start] = original_raw[:data_start]

    # Write each entry's data at its new offset
    for original_idx, e in enumerate(bnd.entries):
        new_off, new_size = new_layout[original_idx]
        if new_off + new_size > total_size:
            raise ValueError(
                f"entry {original_idx} ({e.name!r}) at new_off={new_off:#x} "
                f"size={new_size} overruns total_size={total_size:#x}"
            )
        out[new_off:new_off + new_size] = e.data
        # Zero-fill any alignment padding between this entry's end and
        # the next entry's start (or the file end).
        end = new_off + new_size
        next_start = total_size
        for other_idx, (other_off, _) in new_layout.items():
            if other_off > new_off and other_off < next_start:
                next_start = other_off
        for k in range(end, next_start):
            out[k] = 0

    # Overwrite BND4 header
    out[0x00:0x04] = BND4_MAGIC
    out[0x04:0x08] = bnd.flags_04
    out[0x08:0x0C] = bnd.flags_08
    struct.pack_into('<I', out, 0x0C, file_count)
    struct.pack_into('<Q', out, 0x10, EXPECTED_HEADER_SIZE)
    out[0x18:0x20] = bnd.timestamp.ljust(8, b'\x00')[:8]
    struct.pack_into('<Q', out, 0x20, bnd.per_entry_size)
    struct.pack_into('<Q', out, 0x28, bnd.file_table_size)
    struct.pack_into('<Q', out, 0x30, bnd.data_start)
    struct.pack_into('<I', out, 0x38, bnd.format_flags)
    struct.pack_into('<I', out, 0x3C, 0)

    # Overwrite each entry record with new (offset, size)
    for i, e in enumerate(bnd.entries):
        if e._orig_data_offset is None or e._orig_name_offset is None:
            raise NotImplementedError(
                f"entry {i} ({e.name!r}) lacks original offsets"
            )
        new_off, new_size = new_layout[i]
        eoff = EXPECTED_HEADER_SIZE + i * bnd.per_entry_size
        struct.pack_into('<I', out, eoff + 0x00, e.raw_flags)
        struct.pack_into('<i', out, eoff + 0x04, SENTINEL_M1)
        struct.pack_into('<Q', out, eoff + 0x08, new_size)  # csize
        struct.pack_into('<Q', out, eoff + 0x10, new_size)  # dsize
        struct.pack_into('<I', out, eoff + 0x18, new_off)   # data_off
        struct.pack_into('<I', out, eoff + 0x1C, e.fmg_id)
        struct.pack_into('<I', out, eoff + 0x20, e._orig_name_offset)

    return bytes(out)



def _slot_capacity(bnd: BND4, entry_idx: int, total_size: int) -> int:
    """How many bytes can entry `entry_idx` occupy without overlapping
    the next entry's data slot? Determined by the next entry's
    original data_offset (or end-of-file if last)."""
    e = bnd.entries[entry_idx]
    # Find the next entry by original data_offset position
    next_offset = total_size
    for other in bnd.entries:
        if other is e:
            continue
        if other._orig_data_offset is not None and other._orig_data_offset > e._orig_data_offset:
            if other._orig_data_offset < next_offset:
                next_offset = other._orig_data_offset
    return next_offset - e._orig_data_offset


def _original_dsize(bnd: BND4, original_raw: bytes, entry_idx: int) -> int:
    """Read the dsize field for entry `entry_idx` from the original
    bytes — used to zero-fill slack when shrinking."""
    eoff = EXPECTED_HEADER_SIZE + entry_idx * bnd.per_entry_size
    return struct.unpack_from('<Q', original_raw, eoff + 0x10)[0]
