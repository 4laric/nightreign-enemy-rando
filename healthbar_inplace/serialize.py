"""
serialize.py — append-only EMEVD binary serializer.

v0.27.0 — Alaric. The inverse of emevd.py's parser, scoped deliberately
NARROW: it can reproduce a parsed EMEVD byte-for-byte (identity round-
trip) and it can APPEND new events / new instructions. It cannot edit
or re-lay-out existing instructions — that would require re-serializing
the Parameters table and is out of scope (see the project discussion;
the in-place-rewrite emevd_patch patches still need DarkScript3, the
append-type ones — proximity_wake — do not).

Why identity-first
------------------
A serializer that cannot reproduce its own input byte-for-byte has no
business writing files the game loads. So the foundation here is
`reserialize_identity(raw)`: parse the section layout, slice the file
into its 8 regions, and stitch them back. If that is not bit-identical
to the input across the whole vanilla corpus, nothing else is trusted.
Run the round-trip test (test_serialize_roundtrip.py) before relying on
the append path.

The section model
-----------------
A Sekiro+/NR EMEVD is:
    [Header][Events][Instructions][EventLayers][Args][Parameters]
    [LinkedFiles][Strings]
all little-endian, sections in that fixed order. The header at 0x00
holds (offset, count/size) for each. This module treats EventLayers,
Parameters, LinkedFiles and Strings as OPAQUE byte blobs — it never
parses or rewrites their contents, only relocates them and fixes the
header offsets. Events / Instructions / Args are the only sections it
understands well enough to grow.

Append model
------------
`EmevdEditor` wraps a parsed file and exposes:
  * append_event(event_id, rest_behavior, instructions)
  * append_instructions_to_event(event_index, instructions, at='end')
Both only ever GROW the Events / Instructions / Args tables. Existing
records keep their bytes; their cross-references (an event's
first_instruction_offset) are recomputed only when the Instructions
table is spliced — see append_instructions_to_event's docstring for
the reindex rule. Opaque sections are copied verbatim and the header
offsets are recomputed for the new layout.
"""

import struct

# Local import — same package. Reuse the parser's constants + Header.
try:
    from . import emevd as _emevd
except ImportError:                       # run as a loose script
    import emevd as _emevd


MAGIC = _emevd.MAGIC
HEADER_SIZE = 0x90        # observed in vanilla NR: events start at 0x90.
                          # (emevd.Header.HEADER_SIZE is 0x94; the real
                          # files put events at 0x90 — we trust the
                          # parsed event_offset, this is only a fallback.)


# ─────────────────────────────────────────────────────────────────────
# Section slicing
# ─────────────────────────────────────────────────────────────────────

class Sections:
    """The 8 regions of an EMEVD file, sliced from raw bytes by the
    header's offset chain. header is bytes; the rest are bytes blobs.

    The four 'opaque' blobs (event_layers, parameters, linked_files,
    strings) are never interpreted — only relocated.
    """

    __slots__ = ('header', 'events', 'instructions', 'event_layers',
                 'args', 'parameters', 'linked_files', 'strings',
                 'trailing', '_h')

    def __init__(self, raw):
        h = _emevd.Header.parse(raw)
        self._h = h

        # Section boundaries come straight from the header. The format
        # fixes section order, so each section runs from its own offset
        # to the next section's offset.
        ev_start = h.event_offset
        in_start = h.instruction_offset
        # EventLayers may be empty; when count==0 its offset still
        # points somewhere sane (== args_offset in practice).
        el_start = h.event_layer_offset
        ar_start = h.args_offset
        pa_start = h.parameter_offset
        lf_start = h.linked_files_offset
        st_start = h.strings_offset
        st_end = h.strings_offset + h.strings_size

        self.header = raw[0:ev_start]
        self.events = raw[ev_start:in_start]
        # instructions end at event_layers if present, else args.
        in_end = el_start if h.event_layer_count > 0 else ar_start
        self.instructions = raw[in_start:in_end]
        self.event_layers = raw[el_start:ar_start] \
            if h.event_layer_count > 0 else b''
        # v0.31: slice Args by its KNOWN size, and derive Parameters from the
        # end of Args rather than from parameter_offset. SoulsFormats writes
        # parameter_offset == args_offset for zero-parameter files (synth.py
        # mirrors this), and the old `raw[ar_start:pa_start]` slice then
        # produced an EMPTY args section and folded the real arg bytes into
        # `parameters`. reserialize_identity still round-tripped (the bytes
        # are merely relabeled), which is why the identity test never caught
        # it — but the append path must separate Args from Parameters to grow
        # Args, and there the mis-slice corrupts the output. Slicing Args by
        # args_size is byte-identical on the normal [args][params] layout
        # (params immediately follow args) and correct on the aliased layout.
        self.args = raw[ar_start:ar_start + h.args_size]
        params_start = ar_start + h.args_size
        # parameters run to linked_files.
        self.parameters = raw[params_start:lf_start]
        self.linked_files = raw[lf_start:st_start]
        self.strings = raw[st_start:st_end]
        # Anything after strings (alignment padding some files carry).
        self.trailing = raw[st_end:]


# ─────────────────────────────────────────────────────────────────────
# Identity round-trip
# ─────────────────────────────────────────────────────────────────────

def reserialize_identity(raw):
    """Parse `raw` into sections and stitch them straight back, with no
    edits. MUST return bytes identical to `raw` for any valid EMEVD —
    that property is the correctness foundation for everything else.

    Returns the rebuilt bytes. Callers / tests assert == raw.
    """
    s = Sections(raw)
    return (s.header + s.events + s.instructions + s.event_layers
            + s.args + s.parameters + s.linked_files + s.strings
            + s.trailing)


# ─────────────────────────────────────────────────────────────────────
# Record codecs (Sekiro+/NR long variant)
# ─────────────────────────────────────────────────────────────────────

# Event record, 48 bytes:
#   id u64 | instr_count u64 | first_instr_offset u64 |
#   param_count u64 | first_param_offset i64 | rest_behavior u32 | pad u32
_EVENT_FMT = "<QQQQqII"
_EVENT_SIZE = 48

# Instruction record, 32 bytes:
#   class u32 | index u32 | args_size u64 | first_arg_offset i64 |
#   event_layer_offset i64
_INSTR_FMT = "<IIQqq"
_INSTR_SIZE = 32


def _pack_event(event_id, instr_count, first_instr_off,
                param_count, first_param_off, rest_behavior):
    rec = struct.pack(_EVENT_FMT, event_id, instr_count, first_instr_off,
                      param_count, first_param_off, rest_behavior, 0)
    assert len(rec) == _EVENT_SIZE
    return rec


def _pack_instr(instr_class, instr_index, args_size,
                first_arg_off, event_layer_off):
    rec = struct.pack(_INSTR_FMT, instr_class, instr_index, args_size,
                      first_arg_off, event_layer_off)
    assert len(rec) == _INSTR_SIZE
    return rec


def _unpack_event(blob, i):
    off = i * _EVENT_SIZE
    (eid, ic, fio, pc, fpo, rb, _pad) = struct.unpack_from(
        _EVENT_FMT, blob, off)
    return {'event_id': eid, 'instr_count': ic, 'first_instr_off': fio,
            'param_count': pc, 'first_param_off': fpo,
            'rest_behavior': rb}


# ─────────────────────────────────────────────────────────────────────
# Append-only editor
# ─────────────────────────────────────────────────────────────────────

class NewInstruction:
    """An instruction to be appended. args is a list of uint32 ints
    (literal args only — the append path does not emit Parameters-table
    references). event_layer_offset defaults to -1 (no layer mask)."""

    __slots__ = ('cls', 'index', 'args', 'event_layer_offset')

    def __init__(self, cls, index, args, event_layer_offset=-1):
        self.cls = cls
        self.index = index
        self.args = list(args)
        self.event_layer_offset = event_layer_offset


class EmevdEditor:
    """Wraps a parsed EMEVD and supports append-only edits, then
    serializes the result. Identity-preserving: an editor with no
    edits serializes bit-identical to its input.
    """

    def __init__(self, raw):
        self._raw = raw
        self._sections = Sections(raw)
        h = self._sections._h
        if self._sections._h.event_record_size != _EVENT_SIZE:
            raise ValueError(
                f"event record size {h.event_record_size} != "
                f"{_EVENT_SIZE}; append serializer supports only the "
                f"Sekiro+/NR 48-byte event record")
        if h.instruction_record_size != _INSTR_SIZE:
            raise ValueError(
                f"instruction record size {h.instruction_record_size} "
                f"!= {_INSTR_SIZE}; append serializer supports only the "
                f"Sekiro+/NR 32-byte instruction record")
        # Pending appends, applied at serialize() time.
        self._new_events = []          # list of (event_id, rb, [NewInstruction])
        self._instr_inserts = {}       # event_index -> [NewInstruction]

    # -- query -------------------------------------------------------
    def event_count(self):
        return self._sections._h.event_count

    def event_ids(self):
        blob = self._sections.events
        return [_unpack_event(blob, i)['event_id']
                for i in range(self.event_count())]

    # -- append API --------------------------------------------------
    def append_event(self, event_id, rest_behavior, instructions):
        """Queue a brand-new event with its own instruction list.
        instructions: list[NewInstruction]."""
        self._new_events.append(
            (event_id, rest_behavior, list(instructions)))

    def append_instructions_to_event(self, event_index, instructions):
        """Queue instructions to be appended to the END of an existing
        event's instruction run.

        Because EMEVD events address their instructions as a contiguous
        (first_instruction_offset, count) span, inserting into the
        middle of the Instructions table shifts every later event's
        first_instruction_offset. serialize() handles that reindex.
        """
        if not 0 <= event_index < self.event_count():
            raise IndexError(f"event_index {event_index} out of range "
                             f"(0..{self.event_count() - 1})")
        self._instr_inserts.setdefault(event_index, []).extend(instructions)

    # -- serialize ---------------------------------------------------
    def to_bytes(self):
        """Materialize the edited EMEVD. With no pending edits this is
        byte-identical to the input (delegates to reserialize_identity).
        """
        if not self._new_events and not self._instr_inserts:
            return reserialize_identity(self._raw)

        s = self._sections
        h = s._h

        # --- decode existing events + instructions into mutable form -
        events = [_unpack_event(s.events, i)
                  for i in range(h.event_count)]
        # Existing instruction records stay as raw 32-byte blobs — we
        # never edit them, only relocate. Per-event slices:
        instr_blob = s.instructions
        # args stay as a single growable blob; existing arg bytes keep
        # their offsets (we only append), so existing instruction
        # records' first_arg_offset values remain valid.
        args = bytearray(s.args)

        # Build the new Instructions table event-by-event so inserts
        # land contiguously inside the right event.
        new_instr = bytearray()
        instr_cursor = 0          # index into the existing instr_blob
        for ei, ev in enumerate(events):
            # copy this event's existing instruction records verbatim
            ev_first = len(new_instr)
            cnt = ev['instr_count']
            seg = instr_blob[instr_cursor * _INSTR_SIZE:
                             (instr_cursor + cnt) * _INSTR_SIZE]
            new_instr += seg
            instr_cursor += cnt
            # append any queued instructions for this event
            extra = self._instr_inserts.get(ei, [])
            for ni in extra:
                a_off, a_size = _emit_args(args, ni.args)
                new_instr += _pack_instr(
                    ni.cls, ni.index, a_size, a_off,
                    ni.event_layer_offset)
            ev['instr_count'] = cnt + len(extra)
            ev['first_instr_off'] = ev_first

        # --- append brand-new events ---------------------------------
        for (eid, rb, instrs) in self._new_events:
            ev_first = len(new_instr)
            for ni in instrs:
                a_off, a_size = _emit_args(args, ni.args)
                new_instr += _pack_instr(
                    ni.cls, ni.index, a_size, a_off,
                    ni.event_layer_offset)
            events.append({
                'event_id': eid, 'instr_count': len(instrs),
                'first_instr_off': ev_first,
                'param_count': 0, 'first_param_off': -1,
                'rest_behavior': rb,
            })

        # --- re-pack the Events table --------------------------------
        new_events = bytearray()
        for ev in events:
            new_events += _pack_event(
                ev['event_id'], ev['instr_count'], ev['first_instr_off'],
                ev['param_count'], ev['first_param_off'],
                ev['rest_behavior'])

        # --- recompute the layout + header ---------------------------
        return _assemble(s, h, bytes(new_events), bytes(new_instr),
                         bytes(args))


def _emit_args(args_blob, arg_values):
    """Append uint32 args to args_blob; return (offset, size) of the
    block. offset is relative to the start of the Args section, which
    is what an instruction record's first_arg_offset wants."""
    if not arg_values:
        return -1, 0
    off = len(args_blob)
    for v in arg_values:
        # EMEVD args are written as raw 4-byte cells; ints only on the
        # append path (literal args, see module docstring).
        args_blob += struct.pack("<I", v & 0xFFFFFFFF)
    return off, len(arg_values) * 4


def _assemble(sections, h, new_events, new_instr, new_args):
    """Stitch a file from edited Events/Instructions/Args plus the
    untouched opaque sections, recomputing every header offset."""
    header = bytearray(sections.header)   # keep magic/version/etc.

    event_layers = sections.event_layers
    parameters = sections.parameters
    linked_files = sections.linked_files
    strings = sections.strings
    trailing = sections.trailing

    # New section offsets, in fixed format order.
    event_offset = len(header)
    instr_offset = event_offset + len(new_events)
    elayer_offset = instr_offset + len(new_instr)
    args_offset = elayer_offset + len(event_layers)
    param_offset = args_offset + len(new_args)
    linked_offset = param_offset + len(parameters)
    strings_offset = linked_offset + len(linked_files)
    file_size = strings_offset + len(strings) + len(trailing)

    new_event_count = len(new_events) // _EVENT_SIZE
    new_instr_count = len(new_instr) // _INSTR_SIZE

    # Header field offsets — see emevd.Header.parse for the map.
    struct.pack_into("<I", header, 0x0C, file_size & 0xFFFFFFFF)
    struct.pack_into("<Q", header, 0x10, new_event_count)
    struct.pack_into("<Q", header, 0x18, event_offset)
    struct.pack_into("<Q", header, 0x20, new_instr_count)
    struct.pack_into("<Q", header, 0x28, instr_offset)
    # 0x30/0x38 unk1 — leave as-is (always 0 in NR).
    struct.pack_into("<Q", header, 0x40, h.event_layer_count)
    struct.pack_into("<Q", header, 0x48, elayer_offset)
    struct.pack_into("<Q", header, 0x50, h.parameter_count)
    struct.pack_into("<Q", header, 0x58, param_offset)
    struct.pack_into("<Q", header, 0x60, h.linked_files_count)
    struct.pack_into("<Q", header, 0x68, linked_offset)
    struct.pack_into("<Q", header, 0x70, len(new_args))
    struct.pack_into("<Q", header, 0x78, args_offset)
    struct.pack_into("<Q", header, 0x80, len(strings))
    struct.pack_into("<Q", header, 0x88, strings_offset)

    return (bytes(header) + new_events + new_instr + event_layers
            + new_args + parameters + linked_files + strings + trailing)
