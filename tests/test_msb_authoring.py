"""Tests for dev/msb_authoring.py.

Verify the authored XML matches MMV's reference format closely enough
that Witchy will round-trip it back to a valid .msb.dcx.
"""
import importlib.util
import os
import re
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MOD_PATH = os.path.join(_ROOT, 'dev', 'msb_authoring.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('msb_authoring', _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['msb_authoring'] = mod
    spec.loader.exec_module(mod)
    return mod


def _normalize_part(text: str) -> str:
    """Strip values from fields that legitimately vary between Parts.

    Leaves only the structural skeleton — wrapper element nesting,
    constant boilerplate, formatting. If two Parts' normalized forms
    match, they have the same shape even if the chrs differ.
    """
    text = text.replace('\r\n', '\n')
    substitutions = [
        (r'<Name>[^<]+</Name>', '<Name>_</Name>'),
        (r'<ModelName>[^<]+</ModelName>', '<ModelName>_</ModelName>'),
        (r'<InstanceID>\d+</InstanceID>', '<InstanceID>_</InstanceID>'),
        (r'<EntityID>\d+</EntityID>', '<EntityID>_</EntityID>'),
        (r'<NPCParamID>\d+</NPCParamID>', '<NPCParamID>_</NPCParamID>'),
        (r'<ThinkParamID>\d+</ThinkParamID>', '<ThinkParamID>_</ThinkParamID>'),
        (r'<TalkID>\d+</TalkID>', '<TalkID>_</TalkID>'),
        (r'(<[XYZ]>)-?[\d.]+(</[XYZ]>)', r'\1_\2'),
        (r'<UnkT3C>-?\d+</UnkT3C>', '<UnkT3C>_</UnkT3C>'),
    ]
    for pat, repl in substitutions:
        text = re.sub(pat, repl, text)
    return text


def _mmv_reference_part_path() -> str:
    """A canonical MMV Part to diff against.

    Uses /tmp/mmv_msb/ if present (the user's witchy-extracted MMV
    upload), else skips the test.
    """
    return '/tmp/mmv_msb/m46_56_00_00-msb-dcx/Part/Enemy/c3100_9000.xml'


def test_part_xml_matches_mmv_structure():
    """Authored Part XML must be byte-identical to MMV reference after
    value-normalization. Catches structural drift (wrong wrapper tags,
    missing/extra fields, wrong nesting)."""
    ref = _mmv_reference_part_path()
    if not os.path.exists(ref):
        import pytest
        pytest.skip('MMV reference not available')

    mod = _load_module()
    chr_ = mod.ChrSpec(c_prefix='c4770', npc_param=904770000,
                        think_param=304770010, entity_id=48900800)
    xml = mod.emit_part_enemy_xml(chr_)

    with open(ref, 'rb') as f:
        mmv = f.read().decode('utf-8')

    assert _normalize_part(xml) == _normalize_part(mmv), (
        "Authored Part XML structure diverged from MMV reference. "
        "Check the wrapper element names (Gparam vs Unk2, Unk8 vs Unk7), "
        "the TileLoad block, and the SpEffectSetParamID wrapper.")


def test_part_xml_includes_neverdisable():
    """The whole point of the authored MSB: chrs alive at map-load.
    GameEditionDisable MUST be NeverDisable on every Part."""
    mod = _load_module()
    chr_ = mod.ChrSpec(c_prefix='c4770', npc_param=1, think_param=1)
    xml = mod.emit_part_enemy_xml(chr_)
    assert '<GameEditionDisable>NeverDisable</GameEditionDisable>' in xml
    # And the activation gates must be clear
    assert '<ChrActivateCondParamID>0</ChrActivateCondParamID>' in xml
    assert '<Condition1>0</Condition1>' in xml
    assert '<Condition2>0</Condition2>' in xml
    # MapStudioLayer is 0xFFFFFFFF (visible on all layers)
    assert '<MapStudioLayer>4294967295</MapStudioLayer>' in xml


def test_part_xml_uses_canonical_block_names():
    """Wrapper elements must match MMV's names: Gparam (not Unk2),
    Unk8 (not Unk7 — and it only contains Unk00), separate TileLoad
    block, SpEffectSetParamID wrapper around the 4 trailing ints."""
    mod = _load_module()
    chr_ = mod.ChrSpec(c_prefix='c4770', npc_param=1, think_param=1)
    xml = mod.emit_part_enemy_xml(chr_)
    assert '<Gparam>' in xml, "Lighting block must be <Gparam>, not <Unk2>"
    assert '<Unk8>' in xml, "Unk8 wrapper missing"
    assert '<TileLoad>' in xml, "TileLoad block missing"
    assert '<SpEffectSetParamID>' in xml, (
        "SpEffectSetParamID wrapper around the 4 trailing ints is missing")
    # The bad names MUST NOT appear
    assert '<Unk2>' not in xml
    assert '<Unk7>' not in xml


def test_integer_floats_have_no_decimal_point():
    """Position 0 → <X>0</X> not <X>0.0</X>. Scale 1 → <X>1</X>.

    MMV writes integer-valued floats without a decimal point. Witchy's
    parser is probably tolerant of either, but matching the reference
    exactly is the safe default."""
    mod = _load_module()
    chr_ = mod.ChrSpec(c_prefix='c4770', npc_param=1, think_param=1,
                        position=(0.0, 0.0, 0.0))
    xml = mod.emit_part_enemy_xml(chr_)
    # No '.0' in position
    assert '<X>0.0</X>' not in xml
    assert '<X>0</X>' in xml
    # And scale defaults
    assert '<X>1</X>' in xml
    assert '<X>1.0</X>' not in xml


def test_authoring_writes_complete_directory():
    """Top-level author_msb() should write the manifest, all Parts,
    and all unique Models."""
    mod = _load_module()
    arena = mod.ArenaSpec(map_name='m48_90_00_00')
    arena.chrs = [
        mod.ChrSpec(c_prefix='c4770', npc_param=1, think_param=1, entity_id=48900800),
        mod.ChrSpec(c_prefix='c4580', npc_param=2, think_param=2, entity_id=48900810),
        # Two instances of same model — should produce ONE Model file
        mod.ChrSpec(c_prefix='c4770', npc_param=3, think_param=3,
                     entity_id=48900820, instance_id=9001),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = mod.author_msb(arena, tmp)
        assert os.path.isdir(path)
        assert os.path.isfile(os.path.join(path, '_witchy-msbe.xml'))
        # Three parts
        parts = os.listdir(os.path.join(path, 'Part', 'Enemy'))
        assert sorted(parts) == ['c4580_9000.xml', 'c4770_9000.xml',
                                   'c4770_9001.xml']
        # Two unique models (c4770 appears twice but registered once)
        models = os.listdir(os.path.join(path, 'Model', 'Enemy'))
        assert sorted(models) == ['c4580.xml', 'c4770.xml']


def test_authoring_uses_crlf_line_endings():
    """Witchy's reference output is CRLF. Our authored XML must match
    so the .msb.dcx round-trip is byte-stable."""
    mod = _load_module()
    arena = mod.ArenaSpec(map_name='m48_90_00_00')
    arena.chrs = [mod.ChrSpec(c_prefix='c4770', npc_param=1,
                               think_param=1, entity_id=48900800)]
    with tempfile.TemporaryDirectory() as tmp:
        mod.author_msb(arena, tmp)
        part_path = os.path.join(tmp, 'm48_90_00_00-msb-dcx',
                                  'Part', 'Enemy', 'c4770_9000.xml')
        with open(part_path, 'rb') as f:
            raw = f.read()
        crlf_count = raw.count(b'\r\n')
        lone_lf_count = raw.count(b'\n') - crlf_count
        assert crlf_count > 0, "No CRLF line endings found"
        assert lone_lf_count == 0, (
            f"Found {lone_lf_count} bare LF chars (should be all CRLF)")


def test_linear_roster_assigns_entity_ids_and_positions():
    """build_linear_roster spreads chrs along X axis and assigns EIDs
    in slot-spacing (+10) increments."""
    mod = _load_module()
    chrs = [
        mod.ChrSpec(c_prefix='c4770', npc_param=1, think_param=1),
        mod.ChrSpec(c_prefix='c4580', npc_param=2, think_param=2),
        mod.ChrSpec(c_prefix='c4510', npc_param=3, think_param=3),
    ]
    arena = mod.build_linear_roster('m48_90_00_00', chrs,
                                     x_spacing=5.0, base_eid=48900800)
    # Positions are 0, 5, 10 along X
    assert arena.chrs[0].position == (0.0, 0.0, 0.0)
    assert arena.chrs[1].position == (5.0, 0.0, 0.0)
    assert arena.chrs[2].position == (10.0, 0.0, 0.0)
    # EIDs are 48900800, 48900810, 48900820
    assert arena.chrs[0].entity_id == 48900800
    assert arena.chrs[1].entity_id == 48900810
    assert arena.chrs[2].entity_id == 48900820


def test_witchy_header_lists_unique_models_in_first_appearance_order():
    """If chrs are [c4770, c4580, c4770, c4510], models must be listed
    [c4770, c4580, c4510] — unique, first-appearance order."""
    mod = _load_module()
    arena = mod.ArenaSpec(map_name='m48_90_00_00')
    arena.chrs = [
        mod.ChrSpec(c_prefix='c4770', npc_param=1, think_param=1),
        mod.ChrSpec(c_prefix='c4580', npc_param=2, think_param=2),
        mod.ChrSpec(c_prefix='c4770', npc_param=3, think_param=3,
                     instance_id=9001),
        mod.ChrSpec(c_prefix='c4510', npc_param=4, think_param=4),
    ]
    header = mod.emit_witchy_header_xml(arena)
    # Order: c4770 appears at offset of first, then c4580, then c4510
    pos_4770 = header.find('name="c4770"')
    pos_4580 = header.find('name="c4580"')
    pos_4510 = header.find('name="c4510"')
    assert 0 < pos_4770 < pos_4580 < pos_4510
    # And c4770 appears only ONCE in models section
    models_section = header[header.find('<models>'):header.find('</models>')]
    assert models_section.count('name="c4770"') == 1
