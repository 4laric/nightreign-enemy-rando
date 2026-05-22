"""
inspect.py — One-shot inspector. Run this on a real .emevd file the
moment you have one decompressed; it dumps everything the parser
extracted so you can sanity-check by eye.

  python inspect.py /path/to/m48_50_00_00.emevd

Or with a .js oracle for cross-check:

  python inspect.py /path/to/m48_50_00_00.emevd /path/to/m48_50_00_00.emevd.dcx.js

If the parser explodes on the file, the traceback will name the
specific field/offset that didn't parse — that's the fix-point for
the format-spec adjustment.
"""

import sys
import struct
from emevd import (
    EMEVD, Header, extract_healthbar_callsites,
    EMEVDParseError, UnsupportedVariantError, CorruptOffsetError,
)


def hex_dump(raw, start, length=64, columns=16):
    out = []
    for off in range(start, min(start + length, len(raw)), columns):
        chunk = raw[off:off + columns]
        hexs = ' '.join(f'{b:02x}' for b in chunk)
        ascii_ = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        out.append(f"  {off:08x}  {hexs:<{columns*3}}  {ascii_}")
    return '\n'.join(out)


def inspect(path, js_path=None):
    print(f"=== inspecting {path} ===\n")
    with open(path, 'rb') as f:
        raw = f.read()
    print(f"File size: {len(raw):,} bytes")
    print(f"First 16 bytes:")
    print(hex_dump(raw, 0, 16))
    print()

    # Step 1: header
    try:
        header = Header.parse(raw)
    except UnsupportedVariantError as e:
        print(f"FAIL: unsupported variant — {e}")
        print(f"Header[0x00-0x10]:")
        print(hex_dump(raw, 0, 0x10))
        print()
        print("The version flags need to be added to VERSION_FLAGS_SEKIRO_PLUS")
        print("in emevd.py, OR the field at +0x04 is being read as the wrong width.")
        sys.exit(1)
    except CorruptOffsetError as e:
        print(f"FAIL: corrupt offset — {e}")
        print(f"This usually means a table offset is being read at the wrong byte")
        print(f"position. Inspect bytes 0x00-0x94 (first 148 bytes) and compare to")
        print(f"the Header.parse layout in emevd.py:")
        print(hex_dump(raw, 0, 0x94))
        sys.exit(1)
    except EMEVDParseError as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    print("Header:")
    print(f"  magic                  {header.magic!r}")
    print(f"  version_flags          {header.version_flags.hex()}")
    print(f"  file_size              {header.file_size:,}  (actual {len(raw):,})")
    print(f"  event_count            {header.event_count:,}")
    print(f"  event_offset           0x{header.event_offset:08x}")
    print(f"  event_record_size      {header.event_record_size}  (was 48 in v0.24.0-dev fallback)")
    print(f"  instruction_count      {header.instruction_count:,}")
    print(f"  instruction_offset     0x{header.instruction_offset:08x}")
    print(f"  instruction_record_size {header.instruction_record_size}  (was 32 in v0.24.0-dev fallback)")
    print(f"  event_layer_count      {header.event_layer_count}")
    print(f"  event_layer_offset     0x{header.event_layer_offset:08x}")
    print(f"  event_layer_record_size {header.event_layer_record_size}")
    print(f"  args_size              {header.args_size:,}")
    print(f"  args_offset            0x{header.args_offset:08x}")
    print(f"  strings_size           {header.strings_size}")
    print(f"  strings_offset         0x{header.strings_offset:08x}")
    print()

    # Sanity check arithmetic
    expected_event_end = header.event_offset + header.event_count * 48
    if expected_event_end != header.instruction_offset:
        print(f"NOTE: event_table_end (0x{expected_event_end:08x}) != "
              f"instruction_offset (0x{header.instruction_offset:08x}) — "
              f"there's {header.instruction_offset - expected_event_end} bytes "
              f"of padding/other-data between, OR event record size is wrong.")
        print()

    # Step 2: events
    try:
        parsed = EMEVD.parse(raw)
    except Exception as e:
        print(f"FAIL during event/instruction parse: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print(f"Parsed {len(parsed.events)} events.")
    # First 3 events for sanity
    for i, ev in enumerate(parsed.events[:3]):
        print(f"  Event[{i}]: id={ev.event_id} "
              f"rest={ev.rest_behavior} "
              f"instrs={ev.instruction_count} "
              f"params={ev.parameter_count}")
        for j, instr in enumerate(ev.instructions[:3]):
            print(f"    Instr[{j}]: class={instr.instruction_class} "
                  f"idx={instr.instruction_index} "
                  f"args_size={instr.args_size}")
        if len(ev.instructions) > 3:
            print(f"    ... +{len(ev.instructions) - 3} more")
    if len(parsed.events) > 3:
        print(f"  ... +{len(parsed.events) - 3} more events")
    print()

    # Step 3: healthbar callsites
    callsites = extract_healthbar_callsites(parsed)
    print(f"Healthbar callsites (load-bearing path — byte-scan): {len(callsites)}")
    for c in callsites[:20]:
        print(f"  handler={c.handler_id} group={c.name_group_index} "
              f"nameId={c.name_id} chr={c.chr_entity_ids} "
              f"@byte 0x{c.name_id_file_offset:08x}")
        actual = struct.unpack_from("<I", raw, c.name_id_file_offset)[0]
        if actual != c.name_id:
            print(f"    !! ALERT: bytes at offset say {actual}, not {c.name_id}")
    if len(callsites) > 20:
        print(f"  ... +{len(callsites) - 20} more")
    print()

    # Step 3b: diagnostic byte-scan over WHOLE file vs args region
    from emevd import find_handler_id_hits
    hits_args = find_handler_id_hits(raw, header.args_offset,
                                      header.args_offset + header.args_size)
    hits_all = find_handler_id_hits(raw)
    print(f"Diagnostic raw-byte hits (handler IDs as uint32 LE):")
    print(f"  inside claimed args_region: {len(hits_args)}")
    print(f"  anywhere in file:           {len(hits_all)}")
    if hits_all and not hits_args:
        print(f"  --> args_offset/args_size pointer is WRONG")
    elif not hits_all:
        print(f"  --> handler IDs not present as raw uint32 — different encoding")
    elif hits_args:
        print(f"  First few hits inside args_region:")
        for off, hid in hits_args[:5]:
            print(f"    0x{off:08x}: handler {hid}")
    print()

    # Step 3c: legacy structural extractor — diagnostic only, shows
    # whether the events/instructions tree parses correctly
    from emevd import _extract_healthbar_callsites_structural
    struct_callsites = _extract_healthbar_callsites_structural(parsed)
    print(f"Healthbar callsites (legacy structural path, diagnostic): {len(struct_callsites)}")
    if len(struct_callsites) != len(callsites):
        print(f"  Mismatch with byte-scan ({len(callsites)}) — "
              f"structural walk is broken; byte-scan is load-bearing.")
    print()

    # Step 4: optional .js oracle cross-check
    if js_path:
        print(f"=== cross-checking against .js oracle ===")
        from verify import verify_pair
        ok, _ = verify_pair(path, js_path)
        if ok:
            print("\nSHIP STATUS: parser verified, ready to wire into pipeline.")
        else:
            print("\nSHIP STATUS: discrepancies above — see RUNBOOK_when_emevd_arrives.md "
                  "step 3 for triage.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python inspect.py <emevd_file> [emevd_js_file]", file=sys.stderr)
        sys.exit(2)
    inspect(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
