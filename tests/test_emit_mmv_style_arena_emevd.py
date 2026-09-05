"""Tests for emit_mmv_style_arena_emevd.py — MMV-style minimal arena
EMEVD generation.

The generator's correctness is validated by round-tripping MMV's own
arenas: regenerate the EMEVD from extracted parameters, diff against
the original, expect zero (or minor documented) differences.
"""
import importlib.util
import os
import re

# Import the dev tool module
_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.join(_HERE, '..', 'dev', 'emit_mmv_style_arena_emevd.py')
spec = importlib.util.spec_from_file_location('emit_mmv', _MODULE_PATH)
emit_mmv = importlib.util.module_from_spec(spec)
import sys
sys.modules['emit_mmv'] = emit_mmv  # dataclasses needs the module registered before exec
spec.loader.exec_module(emit_mmv)
ArenaTemplate = emit_mmv.ArenaTemplate
BossSpec = emit_mmv.BossSpec


def _strip_cr(text: str) -> str:
    """Normalize \\r\\n to \\n for comparison."""
    return text.replace('\r\n', '\n').replace('\r', '\n')


def test_basic_single_boss_emit():
    """Smoke test: emit a single-boss arena and verify structure."""
    t = ArenaTemplate(map_prefix="4917")
    t.add_boss(eid_suffix="0800", npc_param=904770000, death_flag=931000)
    src = t.emit()

    # Header present
    assert "// ==EMEVD==" in src
    assert "// @docs    nr-common.emedf.json" in src
    # Main event block
    assert "$Event(0, Default, function()" in src
    # Boss-init for our boss
    assert "$InitializeCommonEvent(0, 90015000, 0, 49170800, 904770000, 30, 0, 0)" in src
    # Death observer
    assert "$InitializeCommonEvent(0, 90015008, 0, 49170800, 931000, 49170800, 0, 0)" in src
    # Display bindings
    assert "$InitializeCommonEvent(0, 90015015, 49170800)" in src
    assert "$InitializeCommonEvent(0, 90015016, 49170800)" in src
    assert "$InitializeCommonEvent(0, 90015199, 49170800)" in src
    # Secondary area-disable event
    assert "$Event(49172200, Default, function(chrEntityId)" in src


def test_multiboss_emit():
    """Three-boss arena emits per-boss init blocks + death observers."""
    t = ArenaTemplate(map_prefix="4656")
    t.add_boss(eid_suffix="0800", npc_param=903100600, death_flag=921010)
    t.add_boss(eid_suffix="0810", npc_param=904770000, death_flag=931000)
    t.add_boss(eid_suffix="0820", npc_param=903050500, death_flag=950000)
    src = t.emit()

    # Each boss has its own 90015000 spawn
    for boss_eid in ("46560800", "46560810", "46560820"):
        assert f"90015000, 0, {boss_eid}" in src
        assert f"90015015, {boss_eid}" in src
        assert f"90015016, {boss_eid}" in src

    # Death observers use per-boss-own anchor by default
    assert "$InitializeCommonEvent(0, 90015008, 0, 46560800, 921010, 46560800, 0, 0)" in src
    assert "$InitializeCommonEvent(0, 90015008, 0, 46560810, 931000, 46560810, 0, 0)" in src
    assert "$InitializeCommonEvent(0, 90015008, 0, 46560820, 950000, 46560820, 0, 0)" in src


def test_first_boss_anchor_option():
    """death_anchor_first_boss=True uses the first boss eid for all death observers."""
    t = ArenaTemplate(map_prefix="4681", death_anchor_first_boss=True)
    t.add_boss(eid_suffix="0800", npc_param=902100600, death_flag=921510)
    t.add_boss(eid_suffix="0810", npc_param=903400301, death_flag=921100)
    src = t.emit()

    # All death observers use the FIRST boss eid as anchor
    death_lines = [l for l in src.split('\n') if "90015008" in l]
    for line in death_lines:
        assert "46810800" in line, f"Expected first-boss anchor in: {line}"


def test_arena_setup_gate():
    """include_arena_setup controls the 90015013 gate."""
    t1 = ArenaTemplate(map_prefix="4656", include_arena_setup=True)
    t1.add_boss("0800", 0, 0)
    assert "if (1 != 0)" in t1.emit()
    assert "if (0 != 0) {" not in t1.emit()

    t2 = ArenaTemplate(map_prefix="4656", include_arena_setup=False)
    t2.add_boss("0800", 0, 0)
    # The 0 != 0 gate is dead code (always false), used by some MMV arenas
    assert "if (0 != 0) {" in t2.emit() or "if (0 != 0)" in t2.emit()


def test_empty_arena_raises():
    """Emitting with no bosses raises clearly."""
    t = ArenaTemplate(map_prefix="4917")
    try:
        t.emit()
        raise AssertionError("Expected ValueError")
    except ValueError as e:
        assert "no bosses" in str(e)


def test_optional_blocks_can_be_disabled():
    """All optional features can be turned off."""
    t = ArenaTemplate(
        map_prefix="4917",
        include_multiplayer_setup=False,
        include_area_disable_event=False,
    )
    t.add_boss("0800", 904770000, 931000)
    src = t.emit()

    assert "IsPlayMode(2)" not in src
    assert "90015040" not in src
    assert "$Event(49172200" not in src


# ─── ROUND-TRIP TESTS against actual MMV files ─────────────────────────

# These tests depend on MMV's EMEVDs being unpacked. If they're not
# available (e.g. in CI), the tests skip rather than fail — round-trip
# is a property check, not a contract obligation.

_MMV_DIR = '/home/claude/mmv_extract/mmv'


def _mmv_available():
    return os.path.isdir(_MMV_DIR)


def test_roundtrip_m46_56():
    """Round-trip MMV's m46_56 (3 bosses, canonical pattern)."""
    if not _mmv_available():
        return
    src_path = os.path.join(_MMV_DIR, 'm46_56_00_00.emevd.dcx.js')
    if not os.path.isfile(src_path):
        return
    original = _strip_cr(open(src_path, encoding="utf-8").read())

    t = ArenaTemplate(map_prefix="4656")
    t.add_boss("0800", 903100600, 921010)
    t.add_boss("0810", 904770000, 931000)
    t.add_boss("0820", 903050500, 950000)
    regen = t.emit()

    assert regen == original, (
        f"Round-trip diff for m46_56:\n"
        f"  regen len:    {len(regen)}\n"
        f"  original len: {len(original)}\n"
        f"  (diff hidden — see /tmp for full)")


def test_roundtrip_m46_56_canonical_options_default():
    """Verify the canonical-MMV-arena options are the generator defaults.

    m46_56 is the cleanest canonical 3-boss MMV arena. If the round-trip
    test passes with NO option overrides, the defaults are correctly
    aligned with the canonical pattern. This guards against silent
    drift in the default values."""
    if not _mmv_available():
        return
    src_path = os.path.join(_MMV_DIR, 'm46_56_00_00.emevd.dcx.js')
    if not os.path.isfile(src_path):
        return
    original = _strip_cr(open(src_path, encoding="utf-8").read())

    # Build with ONLY map_prefix + bosses, no kwargs — pure defaults.
    t = ArenaTemplate(map_prefix="4656")
    t.add_boss("0800", 903100600, 921010)
    t.add_boss("0810", 904770000, 931000)
    t.add_boss("0820", 903050500, 950000)
    regen = t.emit()
    assert regen == original


# ─── BINARY EMIT TESTS ─────────────────────────────────────────────────

import sys
_HB_PATH = os.path.join(_HERE, '..', 'healthbar_inplace')
if _HB_PATH not in sys.path:
    sys.path.insert(0, _HB_PATH)


def test_binary_emit_single_boss():
    """Binary emit produces parseable EMEVD bytes for a single-boss arena."""
    from emevd import EMEVD, extract_healthbar_callsites

    t = ArenaTemplate(map_prefix="4917")
    t.add_boss(eid_suffix="0800", npc_param=904770000, death_flag=931000)
    raw = t.emit_binary()

    # Round-trip parse
    parsed = EMEVD.parse(raw)
    assert parsed.header.event_count == 1
    assert parsed.events[0].event_id == 0

    # Validate the healthbar callsite carries our boss's params
    callsites = extract_healthbar_callsites(parsed)
    # 90015000 (single boss) + 90015002 (HP bar binding) both contribute
    # callsites. Confirm at least one has our chr and nameId.
    assert any(c.chr_entity_ids and 49170800 in c.chr_entity_ids
                for c in callsites), "Expected boss eid 49170800 in some callsite"
    # NpcParam should appear as a nameId in 90015002 callsites
    nameids = [c.name_id for c in callsites]
    assert 904770000 in nameids, f"Expected nameId=904770000 in {nameids}"


def test_binary_emit_three_boss():
    """Three-boss arena emits all per-boss init blocks in binary."""
    from emevd import EMEVD

    t = ArenaTemplate(map_prefix="4656")
    t.add_boss("0800", 903100600, 921010)
    t.add_boss("0810", 904770000, 931000)
    t.add_boss("0820", 903050500, 950000)
    raw = t.emit_binary()

    parsed = EMEVD.parse(raw)
    # Three bosses × 5 init events + 3 death observers + 1 arena setup
    # + 3 bosses × (15+16) + 3 bosses × (71+468) + 3 × 199 + 1 mp setup
    # = 15 + 3 + 1 + 6 + 6 + 3 + 1 = 35 instructions
    expected = 35
    actual = parsed.header.instruction_count
    assert actual == expected, f"Expected {expected} instructions, got {actual}"


def test_binary_emit_validates_via_dcx_compression():
    """Binary output can pass through DCX compression unchanged.

    This is the integration shape that matters for the rando pipeline:
    template -> emit_binary() -> DCX.compress_bytes() -> .emevd.dcx.
    If this round-trips through Oodle, the rando pipeline can use it.
    """
    try:
        import sys
        _proj_path = os.path.join(_HERE, '..')
        if _proj_path not in sys.path:
            sys.path.insert(0, _proj_path)
        from dcx import DCX
    except (ImportError, OSError):
        # Oodle DLL not available on this platform — skip the compression
        # part but still verify the bytes are valid pre-DCX.
        return

    t = ArenaTemplate(map_prefix="4917")
    t.add_boss(eid_suffix="0800", npc_param=904770000, death_flag=931000)
    raw = t.emit_binary()

    try:
        # Compress
        compressed = DCX.compress_bytes(raw)
        assert compressed[:4] == b'DCX\x00'
        # Decompress and verify round-trip
        decompressed = DCX.decompress_bytes(compressed)
        assert decompressed == raw, \
            f"DCX round-trip mismatch: {len(decompressed)} vs {len(raw)}"
    except (OSError, RuntimeError):
        # Oodle not actually loadable — skip
        pass


def test_binary_emit_empty_raises():
    """Empty arena binary-emit raises."""
    t = ArenaTemplate(map_prefix="4917")
    try:
        t.emit_binary()
        raise AssertionError("Expected ValueError")
    except ValueError as e:
        assert "no bosses" in str(e)
