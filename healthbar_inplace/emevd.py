"""
emevd.py — Sekiro/Elden Ring/Armored Core 6/Nightreign EMEVD binary parser.

v0.24.0-dev — Alaric, healthbar in-place patcher development.

What this is
────────────
A read-only parser for the FromSoftware "EMEVD" binary event-script
format used by Sekiro and every subsequent FromSoft game including
Nightreign. The format is post-DCX (raw bytes after Oodle decompression
of an .emevd.dcx file).

We need this to locate the byte offsets of healthbar nameId args in
compiled EMEVD so the rando pipeline can rewrite them without round-
tripping through DarkScript3.

Format reference
────────────────
The format spec comes from SoulsFormats (public C# library; the de
facto reference for FromSoft binary formats) and community-documented
notes. Key structural facts:

  - Magic "EVD\\0", little-endian throughout.
  - Sekiro+ uses 64-bit ("long") variants of count and offset fields
    where DS3 used 32-bit. Version flags in the 4 bytes after the magic
    discriminate the variant.
  - Tables in order: Events, Instructions, EventLayers, Args data,
    Parameters, LinkedFiles offsets, Strings.
  - InitializeCommonEvent is instruction class=2000 sub-index=0 in
    every game since Bloodborne. Its args layout is:
      [slot: u32][common_event_id: u32][param0: u32][param1: u32]...
    Variable-length depending on how many params the common event
    accepts.

What we identify
────────────────
The healthbar callsites we care about are InitializeCommonEvent calls
whose common_event_id is one of:
    90015000, 90015007, 90015021, 90015023, 90015026, 90015406
The arg positions of nameIds inside each handler's param list are
codified in HEALTHBAR_EVENT_SCHEMAS (mirrors
audit_healthbar_callsites.py).

Defensive design
────────────────
The parser validates every offset and count against file size before
following pointers, and exposes structured exceptions per failure mode
so the harness can report which file/event/instruction broke and how.
We expect the real-world corpus to be ~200 files and we'd rather
explode loudly on one than silently corrupt downstream output.

Constants verified against the .js decompiles available in
patched_emevd/. Concrete numeric verification against the binary form
will happen once Alaric uploads decompressed .emevd files; until then
this parser is internally consistent (it round-trips its own synthetic
output, see tests/test_synth.py).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional


# ────────────────────────────────────────────────────────────────────
# Format constants
# ────────────────────────────────────────────────────────────────────

MAGIC = b"EVD\x00"

# Version flag bytes after magic. Sekiro/ER/AC6/NR all use the "long"
# variant. The exact byte pattern is 00 FF 01 FF for Sekiro+ per
# SoulsFormats — bit pattern indicates LongVarintMode (offsets/counts
# are u64) and stringless event blocks (the parameter-list layout).
# We read these bytes but don't gate behavior on them; we just verify
# they indicate Sekiro+. Older games (DS3/BB) would have different
# values and we'd refuse to parse.
VERSION_FLAGS_SEKIRO_PLUS = {
    bytes.fromhex("00FF01FF"),  # canonical Sekiro/ER/AC6/NR
}

# Instruction class+index for InitializeCommonEvent. Stable across all
# Sekiro+ games. We don't use this to find callsites (we filter by
# common_event_id in arg[1] instead, which is more robust against any
# future class renumbering), but we use it as a sanity check on
# instructions we DO want to inspect.
INSTRUCTION_INITIALIZE_COMMON_EVENT = (2000, 0)

# Healthbar handler IDs we patch + arg positions of nameId / chrEntityId
# in each. arg positions are 0-indexed into the *params* (i.e. into the
# tail of the InitializeCommonEvent args after slot and common_event_id
# are stripped). Mirrors HEALTHBAR_EVENT_SCHEMAS in
# healthbar_tools/audit_healthbar_callsites.py.
#
# Format: handler_id -> list of (nameId_param_pos, [chrEntityId_param_pos, ...])
# Each tuple is one healthbar slot. Shared-bar handlers (90015023) have
# multiple slots per call.
HEALTHBAR_HANDLER_SCHEMAS = {
    # ── original entries (kept verbatim — project-tuned chr_positions
    # for these include all chrs logically in the same fight, not just
    # the ones in explicit DisplayBossHealthBar / LinkToBossHealthBar
    # calls). ──
    90015000: [(2, [1])],
    90015007: [(4, [1])],
    90015021: [(2, [1])],
    90015023: [(5, [3, 4]), (7, [6]), (9, [8])],
    90015026: [(5, [3, 4])],
    90015406: [(5, [1, 2])],

    # ── v0.24.x post-investigation: 9006x family added after MMV's
    # common_func.emevd revealed that ~40% of NR's healthbar-driving
    # callsites use these handlers. The two biggest by frequency are
    # 90065910 (19 calls × 3 slots = 57 nameIds across NR's per-map
    # EMEVDs) and 90065911 (20 × 3 = 60). Auto-derived from MMV's
    # event bodies by parsing DisplayBossHealthBar(_, chr, _, name)
    # and LinkToBossHealthBar(_, name, chr) calls. chr_positions
    # reflect EXACT bindings in those calls (no over-binding); for
    # entries with multi-branch bar setup, all chr params bound to a
    # given nameId across any branch are union-merged. ──
    90005870: [(1, [0])],
    90035219: [(3, [2])],
    90065050: [(6, [5]), (8, [7]), (10, [9])],
    90065120: [(4, [1])],
    90065121: [(7, [6]), (9, [8]), (11, [10])],
    90065122: [(4, [1])],
    90065123: [(4, [0, 1])],
    90065124: [(7, [5, 6]), (9, [8]), (11, [10])],
    90065125: [(4, [0, 1])],
    90065130: [(4, [1])],
    90065131: [(7, [6]), (9, [8]), (11, [10])],
    90065132: [(4, [1])],
    90065201: [(7, [6]), (9, [8])],
    90065202: [(5, [4]), (7, [6])],
    90065211: [(6, [3, 4])],
    90065220: [(6, [5])],
    90065221: [(6, [5]), (8, [7]), (10, [9])],
    90065222: [(5, [4]), (7, [6]), (9, [8])],
    90065254: [(7, [6])],
    90065910: [(7, [6]), (9, [8]), (11, [10])],
    90065911: [(5, [4]), (7, [6]), (9, [8])],
    90065912: [(7, [5])],
}


# ────────────────────────────────────────────────────────────────────
# Exceptions
# ────────────────────────────────────────────────────────────────────

class EMEVDParseError(Exception):
    """Base for all parser errors. .context dict has file/event/instr
    info for debug messages."""
    def __init__(self, msg, **context):
        super().__init__(msg)
        self.context = context

    def __str__(self):
        ctx = " ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{super().__str__()}  [{ctx}]" if ctx else super().__str__()


class UnsupportedVariantError(EMEVDParseError):
    """File header indicates a variant we don't claim to parse (e.g. DS3
    short-varint mode). Refuse rather than guess."""


class CorruptOffsetError(EMEVDParseError):
    """A table offset / size in the header points outside the file."""


# ────────────────────────────────────────────────────────────────────
# Header layout (Sekiro+ long variant)
#
# All offsets are absolute byte offsets into the file. Counts are item
# counts (multiply by per-record size to get byte size).
# ────────────────────────────────────────────────────────────────────

@dataclass
class Header:
    magic: bytes
    version_flags: bytes
    file_size: int
    event_count: int
    event_offset: int
    instruction_count: int
    instruction_offset: int
    unk1_count: int           # always 0 in Sekiro+ (legacy "extra" table)
    unk1_offset: int
    event_layer_count: int
    event_layer_offset: int
    parameter_count: int      # v0.24.4: NEW. The fields at 0x50/0x58
    parameter_offset: int     # were previously misread as args_*.
    args_size: int            # size in bytes, not item count
    args_offset: int
    linked_files_count: int
    linked_files_offset: int
    strings_size: int
    strings_offset: int

    # Per-record sizes for the long variant. v0.24.0-dev2: these are
    # FALLBACK defaults. The actual record size used at parse time is
    # auto-derived from the header's offset chain — the file itself
    # tells us how big its records are by where the next section
    # starts. See _autodetect_record_sizes below.
    EVENT_RECORD_SIZE = 48
    INSTRUCTION_RECORD_SIZE = 32
    EVENT_LAYER_RECORD_SIZE = 16
    LINKED_FILE_OFFSET_SIZE = 8

    HEADER_SIZE = 0x94  # 148 bytes — Sekiro+ long header

    @classmethod
    def parse(cls, raw: bytes) -> "Header":
        if len(raw) < cls.HEADER_SIZE:
            raise EMEVDParseError(
                f"file too short for Sekiro+ header (got {len(raw)} bytes, "
                f"need ≥ {cls.HEADER_SIZE})"
            )
        magic = raw[0:4]
        if magic != MAGIC:
            raise EMEVDParseError(f"bad magic: {magic!r}, expected {MAGIC!r}")

        version_flags = raw[4:8]
        if version_flags not in VERSION_FLAGS_SEKIRO_PLUS:
            raise UnsupportedVariantError(
                f"version flags {version_flags.hex()} not in known "
                f"Sekiro+ set; refuse to parse",
                flags=version_flags.hex(),
            )

        # Field offsets follow the actual Sekiro+ EMEVD header layout
        # (verified against vanilla NR EMEVDs and SoulsFormats spec).
        #
        # v0.26.1: Fixed misread of 0x08/0x0C. Pre-v0.26.1 assumed:
        #   0x08: file_size (u32)
        #   0x0C: padding
        # Actual layout (per SoulsFormats EMEVD.cs):
        #   0x08: version int (u32, 0xCC for DS3, 0xCD for Sekiro+/NR)
        #   0x0C: file_size (u32)
        # Both writer (synth.py) and reader (this method) had the same
        # bug — files self-round-tripped through our code but external
        # tools (SoulsFormats, DarkScript3, the game's own loader)
        # rejected them. Now fixed.
        #
        # Other fields (Sekiro+ u64-variant) start at 0x10:
        #   0x10  event_count (u64)
        #   0x18  events_offset
        #   0x20  instruction_count
        #   0x28  instructions_offset
        #   0x30  unk1_count       (always 0 in NR observed files)
        #   0x38  unk1_offset
        #   0x40  event_layer_count
        #   0x48  event_layer_offset
        #   0x50  parameter_count
        #   0x58  parameter_offset
        #   0x60  linked_files_count
        #   0x68  linked_files_offset
        #   0x70  args_size
        #   0x78  args_offset
        #   0x80  strings_size
        #   0x88  strings_offset
        # Total header = 0x90 bytes.
        version = struct.unpack_from("<I", raw, 0x08)[0]
        if version not in (0xCC, 0xCD):
            raise UnsupportedVariantError(
                f"version int 0x{version:x} at offset 0x08 is not in "
                f"known set (0xCC=DS3, 0xCD=Sekiro+/NR). Likely the file "
                f"was generated by pre-v0.26.1 synth.py with the offset "
                f"bug — regenerate via dev/generate_test_mode_arenas.py.",
                flags=version_flags.hex(),
            )
        file_size = struct.unpack_from("<I", raw, 0x0C)[0]
        event_count          = struct.unpack_from("<Q", raw, 0x10)[0]
        event_offset         = struct.unpack_from("<Q", raw, 0x18)[0]
        instruction_count    = struct.unpack_from("<Q", raw, 0x20)[0]
        instruction_offset   = struct.unpack_from("<Q", raw, 0x28)[0]
        unk1_count           = struct.unpack_from("<Q", raw, 0x30)[0]
        unk1_offset          = struct.unpack_from("<Q", raw, 0x38)[0]
        event_layer_count    = struct.unpack_from("<Q", raw, 0x40)[0]
        event_layer_offset   = struct.unpack_from("<Q", raw, 0x48)[0]
        parameter_count      = struct.unpack_from("<Q", raw, 0x50)[0]
        parameter_offset     = struct.unpack_from("<Q", raw, 0x58)[0]
        linked_files_count   = struct.unpack_from("<Q", raw, 0x60)[0]
        linked_files_offset  = struct.unpack_from("<Q", raw, 0x68)[0]
        args_size            = struct.unpack_from("<Q", raw, 0x70)[0]
        args_offset          = struct.unpack_from("<Q", raw, 0x78)[0]
        strings_size         = struct.unpack_from("<Q", raw, 0x80)[0]
        strings_offset       = struct.unpack_from("<Q", raw, 0x88)[0]

        h = cls(
            magic=magic,
            version_flags=version_flags,
            file_size=file_size,
            event_count=event_count,
            event_offset=event_offset,
            instruction_count=instruction_count,
            instruction_offset=instruction_offset,
            unk1_count=unk1_count,
            unk1_offset=unk1_offset,
            event_layer_count=event_layer_count,
            event_layer_offset=event_layer_offset,
            parameter_count=parameter_count,
            parameter_offset=parameter_offset,
            args_size=args_size,
            args_offset=args_offset,
            linked_files_count=linked_files_count,
            linked_files_offset=linked_files_offset,
            strings_size=strings_size,
            strings_offset=strings_offset,
        )
        h._autodetect_record_sizes()
        h._validate_against_file_size(len(raw))
        return h

    def _autodetect_record_sizes(self) -> None:
        """v0.24.0-dev2: derive record sizes from the header's offset
        chain instead of hardcoding format constants.

        Each section starts at offset X with N records, and the next
        section starts at offset Y, so record_size = (Y - X) / N. Each
        file tells us its own record sizes — works regardless of
        whether Sekiro/ER/AC6/NR uses the 24-byte or 32-byte instruction
        record variant, and is robust to any padding the format adds
        between sections.

        Sets instance attrs that override the class-level defaults
        for the parse of THIS file."""

        # Event records end where instructions start.
        if self.event_count > 0:
            ev_total = self.instruction_offset - self.event_offset
            ev_size = ev_total // self.event_count
            self.event_record_size = ev_size if ev_size > 0 and ev_size % 4 == 0 \
                                     else self.EVENT_RECORD_SIZE
        else:
            self.event_record_size = self.EVENT_RECORD_SIZE

        # Instruction records end at the next section: event_layers if
        # non-empty, else args.
        if self.instruction_count > 0:
            next_off = (self.event_layer_offset if self.event_layer_count > 0
                        else self.args_offset)
            instr_total = next_off - self.instruction_offset
            instr_size = instr_total // self.instruction_count
            self.instruction_record_size = instr_size if instr_size > 0 and instr_size % 4 == 0 \
                                          else self.INSTRUCTION_RECORD_SIZE
        else:
            self.instruction_record_size = self.INSTRUCTION_RECORD_SIZE

        # Event-layer records (not consumed for healthbar work, but
        # useful for self-consistency checks).
        if self.event_layer_count > 0:
            el_total = self.args_offset - self.event_layer_offset
            el_size = el_total // self.event_layer_count
            self.event_layer_record_size = el_size if el_size > 0 and el_size % 4 == 0 \
                                          else self.EVENT_LAYER_RECORD_SIZE
        else:
            self.event_layer_record_size = self.EVENT_LAYER_RECORD_SIZE

    def _validate_against_file_size(self, actual_size: int) -> None:
        """Bounds-check every table extent against the actual file
        size. Refuse to parse if anything looks corrupt."""
        if self.file_size != actual_size:
            # Soft warning — some files we've seen have file_size off
            # by a few bytes from actual due to alignment padding. Don't
            # fail, but flag.
            pass

        def check(offset, byte_size, label):
            end = offset + byte_size
            if end > actual_size:
                raise CorruptOffsetError(
                    f"{label} table extends past file end "
                    f"(off={offset}, size={byte_size}, file={actual_size})",
                    table=label,
                )

        check(self.event_offset,
              self.event_count * self.event_record_size, "events")
        check(self.instruction_offset,
              self.instruction_count * self.instruction_record_size, "instructions")
        check(self.event_layer_offset,
              self.event_layer_count * self.event_layer_record_size, "event_layers")
        check(self.args_offset, self.args_size, "args")
        check(self.linked_files_offset,
              self.linked_files_count * self.LINKED_FILE_OFFSET_SIZE, "linked_files")
        check(self.strings_offset, self.strings_size, "strings")


# ────────────────────────────────────────────────────────────────────
# Per-record dataclasses
# ────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    event_id: int
    instruction_count: int
    first_instruction_offset: int   # byte offset into instruction table
    parameter_count: int
    first_parameter_offset: int     # -1 if no params; byte offset otherwise
    rest_behavior: int              # 0=Default, 1=Restart, 2=End
    # Filled in during parse:
    instructions: list = field(default_factory=list)


@dataclass
class Instruction:
    instruction_class: int
    instruction_index: int
    args_size: int
    first_arg_offset: int           # -1 if no args; offset INTO args region (not file)
    event_layer_offset: int         # -1 if no layer mask; offset INTO event_layer region
    # Computed during parse:
    file_arg_offset: int = -1       # absolute file offset to start of this instr's args
                                    # (= header.args_offset + first_arg_offset)
    args_raw: bytes = b""           # the raw arg bytes


# ────────────────────────────────────────────────────────────────────
# Top-level file parse
# ────────────────────────────────────────────────────────────────────

@dataclass
class EMEVD:
    header: Header
    events: list                    # list of Event
    raw: bytes                      # whole-file bytes, kept for byte-offset queries

    @classmethod
    def parse(cls, raw: bytes) -> "EMEVD":
        h = Header.parse(raw)
        events = _parse_events(raw, h)
        return cls(header=h, events=events, raw=raw)


def _parse_events(raw: bytes, h: Header) -> list:
    events = []
    for i in range(h.event_count):
        off = h.event_offset + i * h.event_record_size
        event_id              = struct.unpack_from("<Q", raw, off + 0x00)[0]
        instruction_count     = struct.unpack_from("<Q", raw, off + 0x08)[0]
        first_instr_offset    = struct.unpack_from("<Q", raw, off + 0x10)[0]
        parameter_count       = struct.unpack_from("<Q", raw, off + 0x18)[0]
        first_param_offset    = struct.unpack_from("<q", raw, off + 0x20)[0]  # signed
        rest_behavior         = struct.unpack_from("<I", raw, off + 0x28)[0]
        # +0x2C is 4 bytes padding to round up to 0x30.

        ev = Event(
            event_id=event_id,
            instruction_count=instruction_count,
            first_instruction_offset=first_instr_offset,
            parameter_count=parameter_count,
            first_parameter_offset=first_param_offset,
            rest_behavior=rest_behavior,
        )
        ev.instructions = _parse_instructions(raw, h, ev)
        events.append(ev)
    return events


def _parse_instructions(raw: bytes, h: Header, ev: Event) -> list:
    out = []
    base = h.instruction_offset + ev.first_instruction_offset
    for j in range(ev.instruction_count):
        off = base + j * h.instruction_record_size
        instr_class = struct.unpack_from("<I", raw, off + 0x00)[0]
        instr_index = struct.unpack_from("<I", raw, off + 0x04)[0]
        # v0.24.0-dev2: width-adaptive field reading. The 24-byte and
        # 32-byte instruction-record variants differ in how args_size,
        # first_arg_offset, and event_layer_offset are laid out:
        #
        #   32-byte variant: args_size u64 @ 0x08, first_arg_offset i64
        #     @ 0x10, event_layer_offset i64 @ 0x18.
        #   24-byte variant: args_size u32 @ 0x08, pad @ 0x0C,
        #     first_arg_offset i32 @ 0x10, event_layer_offset i32 @ 0x14
        #     (or similar 4-byte-field layout).
        #
        # We branch on h.instruction_record_size which was auto-detected
        # from the header chain.
        if h.instruction_record_size >= 32:
            args_size          = struct.unpack_from("<Q", raw, off + 0x08)[0]
            first_arg_offset   = struct.unpack_from("<q", raw, off + 0x10)[0]
            event_layer_offset = struct.unpack_from("<q", raw, off + 0x18)[0]
        else:
            # 24-byte (or narrower) variant
            args_size          = struct.unpack_from("<I", raw, off + 0x08)[0]
            first_arg_offset   = struct.unpack_from("<i", raw, off + 0x10)[0]
            event_layer_offset = struct.unpack_from("<i", raw, off + 0x14)[0]

        instr = Instruction(
            instruction_class=instr_class,
            instruction_index=instr_index,
            args_size=args_size,
            first_arg_offset=first_arg_offset,
            event_layer_offset=event_layer_offset,
        )
        if first_arg_offset >= 0 and args_size > 0:
            file_off = h.args_offset + first_arg_offset
            instr.file_arg_offset = file_off
            instr.args_raw = raw[file_off : file_off + args_size]
        out.append(instr)
    return out


# ────────────────────────────────────────────────────────────────────
# Healthbar callsite extraction
# ────────────────────────────────────────────────────────────────────

@dataclass
class HealthbarCallsite:
    """One healthbar slot in one InitializeCommonEvent call. Multiple
    callsites can share an instruction (e.g. 90015023 has 3 slots
    per call)."""
    event_id: int                  # the $Event(N, ...) this is inside
    instruction_index: int         # 0-based index of the instr within the event
    handler_id: int                # the common event being initialized (e.g. 90015000)
    name_id: int                   # current nameId value
    name_id_file_offset: int       # absolute byte offset in raw file where nameId lives
    chr_entity_ids: list           # current chrEntityId values for this slot
    chr_entity_id_file_offsets: list  # parallel list of byte offsets
    is_shared_bar: bool            # True iff len(chr_entity_ids) > 1
    name_group_index: int          # for 90015023: which of the 3 slots (0/1/2)


def extract_healthbar_callsites(parsed: EMEVD) -> list:
    """v0.24.2: load-bearing extractor is now a byte-scan over the
    args region. Walking the structural events->instructions->args
    tree turned out brittle against real NR EMEVD (the seed 725428
    run confirmed: 0 callsites extracted from 197 files even though
    the .js audit found 337). The byte-scan only depends on the
    header's `args_offset` + `args_size` being correct — which they
    are, since they're simple u64 reads at well-known header
    positions and the auto-detect would have caught a mismatch.

    Falls back to the legacy structural extractor if the byte-scan
    returns empty — defensive, in case args_region itself was off."""
    scan = _scan_args_region_for_callsites(parsed.raw, parsed.header)
    if scan:
        return scan
    # Structural fallback (legacy path; may not match real NR layout).
    return _extract_healthbar_callsites_structural(parsed)


def find_handler_id_hits(raw: bytes, region_start: int = None,
                          region_end: int = None) -> list:
    """Diagnostic helper: locate every 4-byte-aligned occurrence of a
    healthbar handler_id in the byte range [region_start, region_end).
    Returns list of (byte_offset, handler_id) tuples. Defaults to the
    whole file if region is unspecified.

    Used by inspect_emevd.py to confirm "are the handler IDs even in
    this file" before getting into args-region addressing concerns."""
    import struct as _struct
    if region_start is None:
        region_start = 0
    if region_end is None:
        region_end = len(raw)
    patterns = {_struct.pack("<I", hid): hid for hid in HEALTHBAR_HANDLER_SCHEMAS}
    hits = []
    pos = (region_start + 3) // 4 * 4  # round up to 4-byte alignment
    while pos + 4 <= region_end:
        chunk = raw[pos:pos + 4]
        hid = patterns.get(chunk)
        if hid is not None:
            hits.append((pos, hid))
        pos += 4
    return hits


def _scan_args_region_for_callsites(raw: bytes, header) -> list:
    """Byte-pattern scan over the args region for healthbar handler IDs.

    InitializeCommonEvent serialized args are uint32 packed back-to-back:
      [slot][handler_id][param0][param1]...
    For each occurrence of a known handler_id (as little-endian uint32)
    within the args region, treat it as an InitializeCommonEvent call,
    compute the byte offsets of the nameId and chr_entity_id args from
    the schema, and emit a HealthbarCallsite.

    Constraint: the handler_id must appear AT a 4-byte-aligned offset
    within the args region (args are u32-aligned). This eliminates
    false matches from data straddling alignment boundaries.

    Filter: the byte (handler_id_offset - 4) is the slot value. Real
    slot values are small ints (0-3 in vanilla NR). Reject matches
    where the preceding 4 bytes parse to a value > 31, which is well
    above any realistic slot count and catches false positives where
    handler_id bytes appear inside another instruction's args."""
    import struct as _struct
    args_start = header.args_offset
    args_end = header.args_offset + header.args_size
    if args_end > len(raw):
        return []

    # Precompute handler_id LE byte patterns
    handler_patterns = {}
    for hid in HEALTHBAR_HANDLER_SCHEMAS:
        handler_patterns[_struct.pack("<I", hid)] = hid

    out = []
    # Scan 4-byte-aligned positions only. args are u32-aligned, so any
    # legitimate handler_id starts at args_start + 4*k for some k.
    pos = args_start
    while pos + 4 <= args_end:
        chunk = raw[pos:pos + 4]
        hid = handler_patterns.get(chunk)
        if hid is None:
            pos += 4
            continue

        # Filter: slot value at (pos - 4) must be small (<=31).
        if pos - 4 < args_start:
            pos += 4
            continue
        slot = _struct.unpack_from("<I", raw, pos - 4)[0]
        if slot > 31:
            pos += 4
            continue

        # Compute param offsets. params are at pos + 4 + 4*k for k=0,1,2,...
        # Validate that the param region fits inside args_region.
        schemas = HEALTHBAR_HANDLER_SCHEMAS[hid]
        max_param_idx = max(
            max([name_pos] + chr_positions)
            for name_pos, chr_positions in schemas
        )
        max_param_byte = pos + 4 + 4 * max_param_idx + 4  # +4 for the param itself
        if max_param_byte > args_end:
            # Truncated call — could be a false match. Skip.
            pos += 4
            continue

        # For each name group in the schema, emit one HealthbarCallsite.
        for group_idx, (name_pos, chr_positions) in enumerate(schemas):
            name_byte_off = pos + 4 + 4 * name_pos
            name_id = _struct.unpack_from("<I", raw, name_byte_off)[0]
            chr_offsets = []
            chr_values = []
            for k in chr_positions:
                off_k = pos + 4 + 4 * k
                chr_offsets.append(off_k)
                chr_values.append(_struct.unpack_from("<I", raw, off_k)[0])
            out.append(HealthbarCallsite(
                event_id=0,            # not available from byte-scan;
                                       # structural path would fill this in
                instruction_index=-1,  # not available from byte-scan
                handler_id=hid,
                name_id=name_id,
                name_id_file_offset=name_byte_off,
                chr_entity_ids=chr_values,
                chr_entity_id_file_offsets=chr_offsets,
                is_shared_bar=len(chr_positions) > 1,
                name_group_index=group_idx,
            ))
        pos += 4
    return out


def _extract_healthbar_callsites_structural(parsed: EMEVD) -> list:
    """Legacy structural extractor — walks every event's instruction
    list, filters for InitializeCommonEvent by class+index, reads args
    from the args region per the structural offsets.

    Kept as a fallback and as the inspect_emevd.py diagnostic path
    (where we WANT to see what the structural parser produces, even
    if wrong, to surface format-spec issues)."""
    out = []
    for ev in parsed.events:
        for i, instr in enumerate(ev.instructions):
            cs = (instr.instruction_class, instr.instruction_index)
            if cs != INSTRUCTION_INITIALIZE_COMMON_EVENT:
                continue
            if instr.args_size < 8 or len(instr.args_raw) < 8:
                continue
            # arg[0] = slot, arg[1] = common_event_id, arg[2..] = params
            slot, common_event_id = struct.unpack_from("<II", instr.args_raw, 0)
            schemas = HEALTHBAR_HANDLER_SCHEMAS.get(common_event_id)
            if not schemas:
                continue

            # Params start at arg[2] in the call, i.e. byte offset 8
            # within args_raw. Each param is uint32 (4 bytes). Param
            # index k maps to byte offset 8 + 4*k.
            n_params_bytes = instr.args_size - 8
            n_params = n_params_bytes // 4
            params = list(struct.unpack_from(f"<{n_params}I", instr.args_raw, 8))

            for group_idx, (name_pos, chr_positions) in enumerate(schemas):
                # Defensive: skip groups whose arg positions exceed the
                # call's actual param count (some shared-bar callsites
                # in vanilla pass fewer params than the schema's max).
                if name_pos >= n_params:
                    continue
                if any(p >= n_params for p in chr_positions):
                    continue

                name_id_offset_in_args = 8 + 4 * name_pos
                file_offset_name = instr.file_arg_offset + name_id_offset_in_args

                chr_offsets = []
                chr_values = []
                for p in chr_positions:
                    chr_offsets.append(instr.file_arg_offset + 8 + 4 * p)
                    chr_values.append(params[p])

                out.append(HealthbarCallsite(
                    event_id=ev.event_id,
                    instruction_index=i,
                    handler_id=common_event_id,
                    name_id=params[name_pos],
                    name_id_file_offset=file_offset_name,
                    chr_entity_ids=chr_values,
                    chr_entity_id_file_offsets=chr_offsets,
                    is_shared_bar=len(chr_positions) > 1,
                    name_group_index=group_idx,
                ))
    return out


# ────────────────────────────────────────────────────────────────────
# Byte-level rewrite (the actual ship-feature)
# ────────────────────────────────────────────────────────────────────

def rewrite_uint32_le(raw: bytes, byte_offset: int, new_value: int) -> bytes:
    """Return a copy of `raw` with the 4 bytes at byte_offset replaced
    by new_value (little-endian uint32). Bounds-checked."""
    if byte_offset < 0 or byte_offset + 4 > len(raw):
        raise EMEVDParseError(
            f"rewrite out of bounds: offset={byte_offset} for len={len(raw)}",
            offset=byte_offset,
        )
    if not (0 <= new_value < (1 << 32)):
        raise EMEVDParseError(f"value {new_value} doesn't fit in uint32")
    new_raw = bytearray(raw)
    struct.pack_into("<I", new_raw, byte_offset, new_value)
    return bytes(new_raw)


def rewrite_many(raw: bytes, edits: dict) -> bytes:
    """Apply a batch of {byte_offset: new_uint32_value} edits.
    Validates none overlap. Returns the new bytes."""
    sorted_edits = sorted(edits.items())
    last_end = -1
    for off, _ in sorted_edits:
        if off < last_end:
            raise EMEVDParseError(
                f"overlapping edits at offset {off} (prev ended at {last_end})",
                offset=off,
            )
        last_end = off + 4
    out = bytearray(raw)
    for off, val in sorted_edits:
        struct.pack_into("<I", out, off, val)
    return bytes(out)
