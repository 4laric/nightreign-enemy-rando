"""tests/test_build_test_arena.py

Tests for dev/build_test_arena.py — the authored-MSB test arena builder.

The most important guarantee these tests provide is **byte-equivalence
with MMV's witchy'd reference files for the fields we emit**. If those
diverge, Witchy may fail to repack the binary correctly.

Note: many of the references are at /tmp/mmv_msb/m46_56_00_00-msb-dcx
(extracted by the user via Witchy Extract). Tests that require those
references skip cleanly when the path is missing — so this test file
can run in CI without the MMV anchor files.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).parent.parent
_BUILDER = _ROOT / 'dev' / 'build_test_arena.py'
_MMV_REF = Path('/tmp/mmv_msb/m46_56_00_00-msb-dcx')


@pytest.fixture(scope='module')
def builder():
    """Load build_test_arena.py as a module."""
    spec = importlib.util.spec_from_file_location('build_test_arena', _BUILDER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['build_test_arena'] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def sample_arena(builder, tmp_path_factory):
    """Build a 3-chr test arena and yield its path."""
    out_dir = tmp_path_factory.mktemp('authored_arena')
    spec = builder.ArenaSpec(
        host_arena_short='m48_70_00_00',
        player_marker_eid=48700500,
        bonfire_asset_eid=48701500,
    )
    spec.test_chrs = [
        builder.TestChr(c_prefix='c4580', npc_param=904580600,
                        eid=48700800, instance_id=9000),
        builder.TestChr(c_prefix='c2280', npc_param=228000000,
                        eid=48700810, instance_id=9001,
                        position=(10.0, 0.0, 0.0)),
        builder.TestChr(c_prefix='c4770', npc_param=477000000,
                        eid=48700820, instance_id=9002,
                        position=(20.0, 0.0, 0.0)),
    ]
    template_dir = _MMV_REF if _MMV_REF.exists() else out_dir / 'fallback'
    out = builder.apply_to_dir(spec, out_dir, template_dir)
    yield out


def test_manifest_has_required_top_level_fields(sample_arena):
    manifest = (sample_arena / '_witchy-msbe.xml').read_text(encoding='utf-8')
    # The WitchyVersion + dfltUnk* fields must match MMV's known-working values
    # or Witchy may produce an incompatible binary.
    for field, expected in [
        ('WitchyVersion', '2080001'),
        ('compression', 'DCX_DFLT'),
        ('dfltUnk04', '69632'),
        ('dfltUnk10', '68'),
        ('dfltUnk14', '76'),
        ('dfltUnk30', '9'),
        ('dfltUnk38', '15'),
    ]:
        assert f'{field}="{expected}"' in manifest or \
               f'<{field}>{expected}</{field}>' in manifest, (
            f'Manifest missing or wrong {field}={expected}')


def test_manifest_lists_all_parts_and_models(sample_arena):
    """Every chr in test_chrs must be listed in <parts> and <models>."""
    manifest = (sample_arena / '_witchy-msbe.xml').read_text(encoding='utf-8')
    # Test chrs
    for cp, inst in [('c4580', '9000'), ('c2280', '9001'), ('c4770', '9002')]:
        assert f'name="{cp}_{inst}"' in manifest, \
            f'Manifest missing Part {cp}_{inst}'
        assert f'name="{cp}"' in manifest, \
            f'Manifest missing Model {cp}'
    # Player marker + bonfire always present
    assert 'name="c1000_9000"' in manifest
    assert 'name="AEG099_060_9000"' in manifest


def test_every_listed_part_has_a_file(sample_arena):
    """Every part name in the manifest must have a corresponding XML file."""
    manifest = (sample_arena / '_witchy-msbe.xml').read_text(encoding='utf-8')
    enemy_parts = re.findall(r'<part type="Enemy" name="([^"]+)"', manifest)
    asset_parts = re.findall(r'<part type="Asset" name="([^"]+)"', manifest)
    for name in enemy_parts:
        assert (sample_arena / 'Part' / 'Enemy' / f'{name}.xml').is_file(), \
            f'Missing Part/Enemy/{name}.xml'
    for name in asset_parts:
        assert (sample_arena / 'Part' / 'Asset' / f'{name}.xml').is_file(), \
            f'Missing Part/Asset/{name}.xml'


def test_every_listed_model_has_a_file(sample_arena):
    """Every model name in the manifest must have a corresponding XML file."""
    manifest = (sample_arena / '_witchy-msbe.xml').read_text(encoding='utf-8')
    enemy_models = re.findall(r'<model type="Enemy" name="([^"]+)"', manifest)
    asset_models = re.findall(r'<model type="Asset" name="([^"]+)"', manifest)
    for name in enemy_models:
        assert (sample_arena / 'Model' / 'Enemy' / f'{name}.xml').is_file(), \
            f'Missing Model/Enemy/{name}.xml'
    for name in asset_models:
        assert (sample_arena / 'Model' / 'Asset' / f'{name}.xml').is_file(), \
            f'Missing Model/Asset/{name}.xml'


def test_each_part_has_neverdisable(sample_arena):
    """The whole point of authoring our own MSB: chrs alive at map-load.
    If any Part lacks GameEditionDisable=NeverDisable, that chr won't
    spawn on load."""
    for fn in (sample_arena / 'Part' / 'Enemy').iterdir():
        content = fn.read_text(encoding='utf-8')
        assert '<GameEditionDisable>NeverDisable</GameEditionDisable>' in content, \
            f'{fn.name}: missing GameEditionDisable=NeverDisable'
        assert '<MapStudioLayer>4294967295</MapStudioLayer>' in content, \
            f'{fn.name}: missing MapStudioLayer=4294967295'
        assert '<ChrActivateCondParamID>0</ChrActivateCondParamID>' in content, \
            f'{fn.name}: missing ChrActivateCondParamID=0'


def test_test_chr_part_has_correct_chr_specific_fields(sample_arena):
    """Verify NPCParamID, ThinkParamID, EntityID, ModelName match input."""
    part = (sample_arena / 'Part' / 'Enemy' / 'c4580_9000.xml').read_text(encoding='utf-8')
    assert '<ModelName>c4580</ModelName>' in part
    assert '<EntityID>48700800</EntityID>' in part
    assert '<NPCParamID>904580600</NPCParamID>' in part
    assert '<InstanceID>9000</InstanceID>' in part


def test_chr_positions_are_distinct(sample_arena):
    """Confirm positions from test_chrs are emitted distinctly so we can
    walk down a line of mobs rather than have them all stack at (0,0,0)."""
    c0 = (sample_arena / 'Part' / 'Enemy' / 'c4580_9000.xml').read_text(encoding='utf-8')
    c1 = (sample_arena / 'Part' / 'Enemy' / 'c2280_9001.xml').read_text(encoding='utf-8')
    c2 = (sample_arena / 'Part' / 'Enemy' / 'c4770_9002.xml').read_text(encoding='utf-8')
    assert '<X>0</X>' in c0
    assert '<X>10</X>' in c1
    assert '<X>20</X>' in c2


@pytest.mark.skipif(not _MMV_REF.exists(),
                     reason='MMV reference at /tmp/mmv_msb not present')
def test_player_marker_byte_identical_to_mmv_modulo_eid(sample_arena):
    """The c1000_9000 player marker is lifted directly from MMV. Its XML
    bytes should be identical to MMV's reference except for the EntityID
    field (which we set per host arena)."""
    mmv_path = _MMV_REF / 'Part' / 'Enemy' / 'c1000_9000.xml'
    ours_path = sample_arena / 'Part' / 'Enemy' / 'c1000_9000.xml'

    mmv = mmv_path.read_bytes()
    ours = ours_path.read_bytes()

    eid_re = re.compile(rb'<EntityID>\d+</EntityID>')
    mmv_norm = eid_re.sub(b'<EntityID>EID</EntityID>', mmv)
    ours_norm = eid_re.sub(b'<EntityID>EID</EntityID>', ours)

    if mmv_norm != ours_norm:
        # Useful diagnostic on failure
        for i, (a, b) in enumerate(zip(mmv_norm, ours_norm)):
            if a != b:
                ctx = f'MMV[{i}:i+30]={mmv_norm[i:i+30]!r}\nOurs[{i}:i+30]={ours_norm[i:i+30]!r}'
                pytest.fail(f'First byte diff at offset {i}:\n{ctx}')
        if len(mmv_norm) != len(ours_norm):
            pytest.fail(f'Length differs: MMV={len(mmv_norm)} ours={len(ours_norm)}')


@pytest.mark.skipif(not _MMV_REF.exists(),
                     reason='MMV reference at /tmp/mmv_msb not present')
def test_test_chr_part_byte_identical_to_mmv_modulo_chr_specific(sample_arena):
    """A test chr Part should be byte-identical to MMV's reference except
    for chr-specific values (Name, ModelName, EntityID, NPCParamID,
    ThinkParamID, InstanceID, Position, Rotation)."""
    mmv_path = _MMV_REF / 'Part' / 'Enemy' / 'c3100_9000.xml'
    ours_path = sample_arena / 'Part' / 'Enemy' / 'c4580_9000.xml'

    def normalize(s: bytes) -> bytes:
        s = re.sub(rb'<(Name|ModelName)>c\d+(?:_\d+)?</\1>',
                    rb'<\1>CHR</\1>', s)
        s = re.sub(rb'<EntityID>\d+</EntityID>',
                    b'<EntityID>EID</EntityID>', s)
        s = re.sub(rb'<NPCParamID>\d+</NPCParamID>',
                    b'<NPCParamID>NPC</NPCParamID>', s)
        s = re.sub(rb'<ThinkParamID>\d+</ThinkParamID>',
                    b'<ThinkParamID>TP</ThinkParamID>', s)
        s = re.sub(rb'<X>-?[\d.]+</X>', b'<X>POS</X>', s)
        s = re.sub(rb'<InstanceID>\d+</InstanceID>',
                    b'<InstanceID>INST</InstanceID>', s)
        return s

    mmv_n = normalize(mmv_path.read_bytes())
    ours_n = normalize(ours_path.read_bytes())
    if mmv_n != ours_n:
        for i, (a, b) in enumerate(zip(mmv_n, ours_n)):
            if a != b:
                ctx = f'MMV[{i}:i+40]={mmv_n[i:i+40]!r}\nOurs[{i}:i+40]={ours_n[i:i+40]!r}'
                pytest.fail(f'First byte diff at offset {i}:\n{ctx}')
        if len(mmv_n) != len(ours_n):
            pytest.fail(f'Length differs: MMV={len(mmv_n)} ours={len(ours_n)}')


def test_emit_matching_emevd_produces_parseable_binary(builder, tmp_path):
    """The EMEVD output must parse via emevd.EMEVD.parse and reference
    the chr eids the MSB declares — otherwise the two halves are out of
    sync."""
    spec = builder.ArenaSpec(
        host_arena_short='m48_70_00_00',
        player_marker_eid=48700500,
        bonfire_asset_eid=48701500,
    )
    spec.test_chrs = [
        builder.TestChr(c_prefix='c4580', npc_param=904580600,
                        eid=48700800, instance_id=9000),
        builder.TestChr(c_prefix='c2280', npc_param=228000000,
                        eid=48700810, instance_id=9001),
        builder.TestChr(c_prefix='c4770', npc_param=477000000,
                        eid=48700820, instance_id=9002),
    ]

    emevd_path = tmp_path / 'm48_70_00_00.emevd'
    builder.emit_matching_emevd(spec, emevd_path)
    assert emevd_path.exists() and emevd_path.stat().st_size > 0

    # Parse via the project's emevd module
    sys.path.insert(0, str(_ROOT / 'healthbar_inplace'))
    from emevd import EMEVD
    import struct
    raw = emevd_path.read_bytes()
    parsed = EMEVD.parse(raw)
    assert len(parsed.events) >= 1

    # Extract all uint32 args from all instructions
    all_args = []
    for e in parsed.events:
        for instr in e.instructions:
            ab = instr.args_raw
            if ab:
                for off in range(0, len(ab), 4):
                    if off + 4 <= len(ab):
                        all_args.append(struct.unpack('<I', ab[off:off+4])[0])

    # All test chr eids must be referenced
    for chr_spec in spec.test_chrs:
        assert chr_spec.eid in all_args, (
            f'Chr eid {chr_spec.eid} not referenced in matching EMEVD. '
            f'MSB will declare a chr the EMEVD never spawns/manages.')

    # Support eids must be referenced (player marker for distance checks,
    # bonfire for wake-region events)
    assert spec.player_marker_eid in all_args, \
        'Player marker eid not in EMEVD (required by 9005810 wake event)'
    assert spec.bonfire_asset_eid in all_args, \
        'Bonfire asset eid not in EMEVD (required by 90015005 + 9005810)'
