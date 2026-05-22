"""
test_roundtrip.py — Parser round-trip tests using synthetic EMEVD bytes.

Run: python -m pytest test_roundtrip.py -v   (or just python test_roundtrip.py)
"""

import struct
import sys

sys.path.insert(0, '..')
from emevd import (
    EMEVD, Header, INSTRUCTION_INITIALIZE_COMMON_EVENT,
    HEALTHBAR_HANDLER_SCHEMAS,
    extract_healthbar_callsites, rewrite_uint32_le, rewrite_many,
)
from synth import build_minimal_emevd, healthbar_instruction


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_minimal_parse_single_event():
    """Single event, single instruction with no args."""
    raw = build_minimal_emevd([{
        'event_id': 12345,
        'rest_behavior': 1,  # Restart
        'instructions': [
            {'class': 1000, 'index': 0, 'args': []},
        ],
    }])
    parsed = EMEVD.parse(raw)
    _assert(parsed.header.event_count == 1, "event_count")
    _assert(parsed.header.instruction_count == 1, "instr_count")
    _assert(parsed.events[0].event_id == 12345, "event_id")
    _assert(parsed.events[0].rest_behavior == 1, "rest_behavior")
    _assert(len(parsed.events[0].instructions) == 1, "instr count in event")
    instr = parsed.events[0].instructions[0]
    _assert(instr.instruction_class == 1000, "instr_class")
    _assert(instr.instruction_index == 0, "instr_index")
    _assert(instr.args_size == 0, "args_size 0")
    print("✓ test_minimal_parse_single_event")


def test_parse_event_with_args():
    """Single event with one InitializeCommonEvent call with 4 args."""
    raw = build_minimal_emevd([{
        'event_id': 99,
        'rest_behavior': 0,
        'instructions': [
            healthbar_instruction(0, 90015000, 49250300, 49250800, 902500300, 40, 690047, 49250301),
        ],
    }])
    parsed = EMEVD.parse(raw)
    instr = parsed.events[0].instructions[0]
    _assert(instr.instruction_class == 2000, "class")
    _assert(instr.instruction_index == 0, "index")
    # 8 args × 4 bytes = 32 bytes
    _assert(instr.args_size == 32, f"args_size: {instr.args_size}")
    args = list(struct.unpack("<8I", instr.args_raw))
    _assert(args == [0, 90015000, 49250300, 49250800, 902500300, 40, 690047, 49250301],
            f"args: {args}")
    print("✓ test_parse_event_with_args")


def test_extract_healthbar_callsites_90015000():
    """One 90015000 call — should produce one HealthbarCallsite,
    nameId at arg pos 2 (params), chrEntityId at arg pos 1."""
    raw = build_minimal_emevd([{
        'event_id': 1000,
        'rest_behavior': 0,
        'instructions': [
            # slot=0, common_event_id=90015000, then params:
            #   eventFlagId=10001, chrEntityId=49250800, nameId=902500300,
            #   targetDistance=40, bgmBossConvParamId=690047,
            #   eventFlagId2=10002
            healthbar_instruction(0, 90015000,
                                  10001, 49250800, 902500300,
                                  40, 690047, 10002),
        ],
    }])
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    _assert(len(callsites) == 1, f"expected 1 callsite, got {len(callsites)}")
    cs = callsites[0]
    _assert(cs.handler_id == 90015000, "handler_id")
    _assert(cs.name_id == 902500300, f"name_id: {cs.name_id}")
    _assert(cs.chr_entity_ids == [49250800], f"chr_entity_ids: {cs.chr_entity_ids}")
    _assert(not cs.is_shared_bar, "is_shared_bar should be False for 90015000")
    # Verify the file offset actually points to the nameId bytes
    val_at_offset = struct.unpack_from("<I", raw, cs.name_id_file_offset)[0]
    _assert(val_at_offset == 902500300,
            f"byte offset {cs.name_id_file_offset} should hold 902500300, got {val_at_offset}")
    print("✓ test_extract_healthbar_callsites_90015000")


def test_extract_healthbar_callsites_90015023_shared_bar():
    """90015023 has 3 name groups per call. Test all three resolve."""
    # Schema:
    #   90015023: [(5, [3, 4]), (7, [6]), (9, [8])]
    # Args (after slot + common_event_id):
    #   [0] eventFlagId
    #   [1] targetDistance
    #   [2] eventFlagId2
    #   [3] chrEntityId
    #   [4] chrEntityId2
    #   [5] nameId          ← group 0
    #   [6] chrEntityId3
    #   [7] nameId2         ← group 1
    #   [8] chrEntityId4
    #   [9] nameId3         ← group 2
    raw = build_minimal_emevd([{
        'event_id': 2000,
        'rest_behavior': 0,
        'instructions': [
            healthbar_instruction(0, 90015023,
                                  10001,        # eventFlagId
                                  40,           # targetDistance
                                  10002,        # eventFlagId2
                                  48500800,     # chrEntityId
                                  48500810,     # chrEntityId2
                                  903251600,    # nameId (group 0)
                                  48500820,     # chrEntityId3
                                  904351000,    # nameId2 (group 1)
                                  48500830,     # chrEntityId4
                                  905451000,    # nameId3 (group 2)
                                  ),
        ],
    }])
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    _assert(len(callsites) == 3, f"expected 3 callsites, got {len(callsites)}")

    g0, g1, g2 = sorted(callsites, key=lambda c: c.name_group_index)
    _assert(g0.name_id == 903251600 and g0.chr_entity_ids == [48500800, 48500810],
            f"group 0 wrong: {g0}")
    _assert(g1.name_id == 904351000 and g1.chr_entity_ids == [48500820],
            f"group 1 wrong: {g1}")
    _assert(g2.name_id == 905451000 and g2.chr_entity_ids == [48500830],
            f"group 2 wrong: {g2}")
    _assert(g0.is_shared_bar and not g1.is_shared_bar,
            "g0 should be shared, g1 should not")
    print("✓ test_extract_healthbar_callsites_90015023_shared_bar")


def test_rewrite_uint32_le():
    raw = b"\x00\x01\x02\x03" + b"\x10\x20\x30\x40" + b"\xff\xff\xff\xff"
    new = rewrite_uint32_le(raw, 4, 0xCAFEBABE)
    _assert(new[0:4] == raw[0:4], "prefix changed")
    _assert(new[8:] == raw[8:], "suffix changed")
    _assert(struct.unpack_from("<I", new, 4)[0] == 0xCAFEBABE, "write didn't take")
    print("✓ test_rewrite_uint32_le")


def test_rewrite_in_real_layout():
    """End-to-end: build EMEVD, find a callsite, rewrite its nameId
    in the bytes, reparse, confirm the new value comes back."""
    raw = build_minimal_emevd([{
        'event_id': 3000,
        'rest_behavior': 0,
        'instructions': [
            healthbar_instruction(0, 90015000,
                                  10001, 49250800, 902500300,
                                  40, 690047, 10002),
        ],
    }])
    parsed = EMEVD.parse(raw)
    cs = extract_healthbar_callsites(parsed)[0]
    new_raw = rewrite_uint32_le(raw, cs.name_id_file_offset, 970000001)
    reparsed = EMEVD.parse(new_raw)
    cs2 = extract_healthbar_callsites(reparsed)[0]
    _assert(cs2.name_id == 970000001, f"reparse got {cs2.name_id}")
    # Everything else identical
    _assert(cs2.chr_entity_ids == cs.chr_entity_ids, "chr ids changed")
    _assert(cs2.handler_id == cs.handler_id, "handler changed")
    print("✓ test_rewrite_in_real_layout")


def test_rewrite_many_overlap_rejected():
    raw = b"\x00" * 16
    try:
        rewrite_many(raw, {0: 1, 2: 2})  # offset 2 overlaps offset 0..4
        _assert(False, "should have raised on overlap")
    except Exception as e:
        _assert("overlapping" in str(e), f"wrong error: {e}")
    print("✓ test_rewrite_many_overlap_rejected")


def test_validates_bad_magic():
    bad = b"XYZ\x00" + b"\x00" * 200
    try:
        EMEVD.parse(bad)
        _assert(False, "should have raised on bad magic")
    except Exception as e:
        _assert("magic" in str(e), f"wrong error: {e}")
    print("✓ test_validates_bad_magic")


def test_validates_too_short():
    try:
        EMEVD.parse(b"EVD\x00" + b"\x00" * 10)
        _assert(False, "should have raised on short file")
    except Exception as e:
        _assert("too short" in str(e), f"wrong error: {e}")
    print("✓ test_validates_too_short")


def test_validates_corrupt_offset():
    """Build a valid-looking header that points the event table past
    EOF. Parser should reject."""
    raw = build_minimal_emevd([{
        'event_id': 1,
        'rest_behavior': 0,
        'instructions': [{'class': 0, 'index': 0, 'args': []}],
    }])
    # Corrupt: bump event_offset to far past end of file.
    corrupted = bytearray(raw)
    struct.pack_into("<Q", corrupted, 0x18, 0x10000000)  # 256MB
    try:
        EMEVD.parse(bytes(corrupted))
        _assert(False, "should have raised on bad offset")
    except Exception as e:
        _assert("past file end" in str(e), f"wrong error: {e}")
    print("✓ test_validates_corrupt_offset")


def test_multiple_events_multiple_handlers():
    """Stress test: 3 events, multiple healthbar handler types."""
    raw = build_minimal_emevd([
        {
            'event_id': 100, 'rest_behavior': 0,
            'instructions': [
                healthbar_instruction(0, 90015000, 1, 1001, 9001, 40, 100, 2),
                healthbar_instruction(0, 90015007, 3, 2001, 1234567, 40, 9002, 100, 4),
            ],
        },
        {
            'event_id': 200, 'rest_behavior': 1,
            'instructions': [
                healthbar_instruction(0, 90015026, 5, 40, 6, 3001, 3002, 9003),
            ],
        },
        {
            'event_id': 300, 'rest_behavior': 0,
            'instructions': [
                # A non-healthbar instruction in between
                {'class': 1014, 'index': 0, 'args': [99, 1]},
                healthbar_instruction(0, 90015406, 7, 4001, 4002, 9004, 40, 9005, 8001, 9),
            ],
        },
    ])
    parsed = EMEVD.parse(raw)
    _assert(len(parsed.events) == 3, f"events: {len(parsed.events)}")
    callsites = extract_healthbar_callsites(parsed)
    handler_ids = sorted(c.handler_id for c in callsites)
    _assert(handler_ids == [90015000, 90015007, 90015026, 90015406],
            f"handlers: {handler_ids}")
    print("✓ test_multiple_events_multiple_handlers")


if __name__ == "__main__":
    tests = [
        test_minimal_parse_single_event,
        test_parse_event_with_args,
        test_extract_healthbar_callsites_90015000,
        test_extract_healthbar_callsites_90015023_shared_bar,
        test_rewrite_uint32_le,
        test_rewrite_in_real_layout,
        test_rewrite_many_overlap_rejected,
        test_validates_bad_magic,
        test_validates_too_short,
        test_validates_corrupt_offset,
        test_multiple_events_multiple_handlers,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
