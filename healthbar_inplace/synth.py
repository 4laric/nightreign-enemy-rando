"""
synth.py — Synthetic EMEVD generator for parser tests.

v0.24.0-dev — health bar in-place patcher.

We can't verify the parser against real NR EMEVD files until Alaric
uploads them, but we CAN verify it's internally consistent: build an
EMEVD by hand using the same layout the parser claims is correct,
parse it, get back the same logical content. This catches arithmetic
mistakes, off-by-one in offset math, struct format string typos.

The synthetic EMEVD here intentionally exercises the InitializeCommonEvent
path with realistic-looking handler IDs (90015000, 90015023) and arg
counts, so extract_healthbar_callsites can be unit-tested on it.

The result is not byte-identical to a real NR EMEVD (we pad less, use
shorter strings, etc.), but every structural rule the parser enforces
should hold.
"""

import struct
from emevd import (
    MAGIC, VERSION_FLAGS_SEKIRO_PLUS, Header,
    INSTRUCTION_INITIALIZE_COMMON_EVENT,
)


def build_minimal_emevd(events_spec):
    """Build a synthetic EMEVD blob.

    events_spec: list of dicts, each describing one event:
        {
          'event_id': int,
          'rest_behavior': int (0/1/2),
          'instructions': [
            {
              'class': int,
              'index': int,
              'args': [int, ...],   # uint32 args, including slot and
                                    # common_event_id for InitializeCommonEvent
            },
            ...
          ]
        }
    """
    # Phase 1: lay out args region. Each instruction contributes a
    # contiguous block of (4 * len(args)) bytes; record per-instruction
    # offsets into the args region.
    args_blob = bytearray()
    arg_offsets_per_instr = []
    for ev in events_spec:
        for instr in ev['instructions']:
            offset_in_args = len(args_blob)
            for v in instr['args']:
                args_blob += struct.pack("<I", v)
            arg_offsets_per_instr.append(
                (offset_in_args, len(instr['args']) * 4)
            )

    # Phase 2: lay out instruction records. Sekiro+ instruction record
    # is 32 bytes: class(u32) + index(u32) + args_size(u64) +
    # first_arg_offset(i64) + event_layer_offset(i64).
    instr_blob = bytearray()
    instr_idx = 0
    instr_first_offset_per_event = []
    for ev in events_spec:
        instr_first_offset_per_event.append(len(instr_blob))
        for instr in ev['instructions']:
            args_off, args_size = arg_offsets_per_instr[instr_idx]
            if args_size == 0:
                first_arg_off = -1
            else:
                first_arg_off = args_off
            event_layer_off = -1  # no layer masks in synthetic
            rec = struct.pack(
                "<IIQqq",
                instr['class'], instr['index'],
                args_size, first_arg_off, event_layer_off,
            )
            assert len(rec) == 32
            instr_blob += rec
            instr_idx += 1

    # Phase 3: lay out event records. 48 bytes each.
    event_blob = bytearray()
    for ev, first_instr_off in zip(events_spec, instr_first_offset_per_event):
        rec = struct.pack(
            "<QQQQqII",
            ev['event_id'], len(ev['instructions']),
            first_instr_off,
            0,           # parameter_count
            -1,          # first_parameter_offset
            ev['rest_behavior'],
            0,           # padding
        )
        assert len(rec) == 48
        event_blob += rec

    # Phase 4: lay out the file. Header is 0x94 bytes; tables follow in
    # order: events, instructions, event_layers (empty), args, parameters
    # (empty), linked_files (empty), strings (empty).
    header_size = Header.HEADER_SIZE
    event_offset = header_size
    instruction_offset = event_offset + len(event_blob)
    event_layer_offset = instruction_offset + len(instr_blob)
    args_offset = event_layer_offset  # event_layers is empty
    linked_files_offset = args_offset + len(args_blob)
    strings_offset = linked_files_offset

    file_size = strings_offset

    version_flags = next(iter(VERSION_FLAGS_SEKIRO_PLUS))

    header = bytearray(header_size)
    header[0:4] = MAGIC
    header[4:8] = version_flags
    # v0.26.1: Fixed missing version field at 0x08.
    # Vanilla NR EMEVDs have:
    #   0x08: version int (0xCD for Sekiro+/NR; 0xCC was DS3)
    #   0x0C: file_size (u32)
    # Pre-v0.26.1 we wrote file_size at 0x08 and 0 at 0x0C — SoulsFormats
    # rejects this ("AssertInt32 expected 0xCC or 0xCD"). The game's loader
    # may have been silently falling back to vanilla EMEVDs because of this,
    # which would explain why test-mode arenas never seemed to take effect
    # in the v0.25.x debugging.
    struct.pack_into("<I", header, 0x08, 0xCD)         # version (Sekiro+/NR)
    struct.pack_into("<I", header, 0x0C, file_size)    # file_size
    struct.pack_into("<Q", header, 0x10, len(events_spec))
    struct.pack_into("<Q", header, 0x18, event_offset)
    total_instructions = sum(len(e['instructions']) for e in events_spec)
    struct.pack_into("<Q", header, 0x20, total_instructions)
    struct.pack_into("<Q", header, 0x28, instruction_offset)
    struct.pack_into("<Q", header, 0x30, 0)       # unk1_count
    struct.pack_into("<Q", header, 0x38, 0)       # unk1_offset
    struct.pack_into("<Q", header, 0x40, 0)       # event_layer_count
    struct.pack_into("<Q", header, 0x48, event_layer_offset)
    struct.pack_into("<Q", header, 0x50, 0)       # parameter_count (v0.24.4)
    struct.pack_into("<Q", header, 0x58, args_offset)  # parameter_offset (unused; point at args)
    struct.pack_into("<Q", header, 0x60, 0)       # linked_files_count
    struct.pack_into("<Q", header, 0x68, linked_files_offset)
    struct.pack_into("<Q", header, 0x70, len(args_blob))  # args_size
    struct.pack_into("<Q", header, 0x78, args_offset)     # args_offset
    struct.pack_into("<Q", header, 0x80, 0)       # strings_size
    struct.pack_into("<Q", header, 0x88, strings_offset)

    return bytes(header) + bytes(event_blob) + bytes(instr_blob) + bytes(args_blob)


def healthbar_call(slot, common_event_id, *params):
    """Convenience: build the args list for an InitializeCommonEvent."""
    return [slot, common_event_id] + list(params)


def healthbar_instruction(slot, common_event_id, *params):
    return {
        'class': INSTRUCTION_INITIALIZE_COMMON_EVENT[0],
        'index': INSTRUCTION_INITIALIZE_COMMON_EVENT[1],
        'args': healthbar_call(slot, common_event_id, *params),
    }
