#!/usr/bin/env python3
"""build_test_arena.py — Author a custom mob-only test-arena MSB by
emitting a Witchy-compatible XML directory ready for Witchy Repack.

Design rationale: see dev/TEST_MODE.md (Path B: Author our own MSB).

In short, this produces the "MMV side" of the matched-pair architecture:
chrs with GameEditionDisable=NeverDisable that are alive at map-load.
The matching EMEVD half is produced by dev/emit_mmv_style_arena_emevd.py
(formerly deprecated; still valid for this use case).

Workflow
========
1. Caller specifies host arena (e.g. m48_70_00_00) and a list of TestChr
   entries (chr prefix + NpcParam/ThinkParam + position).
2. This module writes a Witchy directory tree to <out_dir>:
     <out_dir>/<host>-msb-dcx/
       _witchy-msbe.xml          (manifest)
       Model/Enemy/cXXXX.xml     (one per unique c_prefix)
       Part/Enemy/cXXXX_NNNN.xml (one per chr instance)
       Part/Asset/AEG099_060_9000.xml  (Site of Grace asset)
       Event/PatrolInfo/         (empty)
       Region/, Route/           (empty)
3. User runs Witchy Repack on <out_dir>/<host>-msb-dcx/, producing
   <host>.msb.dcx.
4. User drops the .msb.dcx into the me3 profile's map/mapstudio/
   directory, replacing the vanilla one. Engine loads our MSB instead.
5. The matching EMEVD (built by emit_mmv_style_arena_emevd.py) goes into
   the same profile's map/mapstudio/ as <host>.emevd.dcx.

Reference: MMV's witchy'd MSBs at /tmp/mmv_msb/m*_xx_00_00-msb-dcx/
(particularly m46_56_00_00-msb-dcx as the canonical 'minimal arena').
Every field value here was empirically lifted from those references.

Host arena selection
====================
We RECOMMEND hijacking m48_70_00_00 as the first target:
- It's a single-boss N1/N2 expedition arena (vanilla pattern: 90065910)
- The eid layout (48700800-series) is simple and unambiguous
- Picking a single-boss host avoids multi-boss arg-shape complications
  in the matching EMEVD

Other viable hosts: m48_40, m49_10, m49_17, m49_18, m49_19, m49_20,
m49_21, m49_23 (all single-boss 90065910 arenas).

AVOID hijacking: m48_50/60 (Tricephalos, 3-boss), m48_80 (Godskin Duo),
m49_25 (BBH), m48_90 (multi-phase), m47_70 (Augur 4-wave).
"""
from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple


# ───────────────────────────────────────────────────────────────────
# Configuration / canonical values
# ───────────────────────────────────────────────────────────────────


# All these values were lifted verbatim from MMV's witchy'd m46_56 MSB.
# The MMV manifest header — these unknowns differ between MSB compilations.
# Empirically these are what works for MMV's overlay arenas. NR's vanilla
# MSBs may use slightly different unknowns; for a first attempt we copy
# MMV's values directly since they're a known-working overlay arena.
MSBE_HEADER_UNKNOWNS = {
    'WitchyVersion': '2080001',
    'compression': 'DCX_DFLT',
    'dfltUnk04': '69632',
    'dfltUnk10': '68',
    'dfltUnk14': '76',
    'dfltUnk30': '9',
    'dfltUnk38': '15',
    'layers_version': '79',
}


# Bonfire/marker asset — included in every MMV minimal arena. Mirrors
# Site of Grace functionality and is referenced by 9005810 calls in the
# matching EMEVD.
DEFAULT_BONFIRE_ASSET_MODEL = 'AEG099_060'
DEFAULT_BONFIRE_ASSET_INSTANCE = 9000

# Player-marker chr — every MMV arena ships c1000_9000 (the "player
# ghost" used for distance/aggro checks). The 9001x events reference
# entity 20000 globally for player position, but the c1000 marker is
# also kept as a non-aggressive entity at a known eid.
PLAYER_MARKER_C_PREFIX = 'c1000'
PLAYER_MARKER_INSTANCE = 9000


# ───────────────────────────────────────────────────────────────────
# Data classes
# ───────────────────────────────────────────────────────────────────


@dataclass
class TestChr:
    """One enemy instance in the test arena."""
    c_prefix: str             # e.g. 'c4580'
    npc_param: int             # NpcParamID (chr's stats; e.g. 904580600)
    think_param: int = 0       # ThinkParamID (AI; default 0 = derived
                                # by chr's regulation entry)
    eid: int = 0               # Part EntityID — must be in host arena's
                                # eid range (e.g. 48700800-48700899 for
                                # m48_70)
    instance_id: int = 9000    # MSB instance counter (must be unique
                                # per c_prefix within the MSB)
    # All positions are relative to the host map's overlay origin (which
    # is itself overlayed onto a Limveld tile). (0, 0, 0) places at
    # whatever the engine considers the overlay's center. Spreading
    # entries by X-offset is unverified — see note in module docstring.
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class ArenaSpec:
    """The full description of an authored test arena."""
    host_arena_short: str      # e.g. 'm48_70_00_00'
    test_chrs: List[TestChr] = field(default_factory=list)
    # Bonfire asset (Site of Grace). Use the host arena's expected eid
    # for the bonfire so vanilla EMEVD events that reference it still
    # resolve (or just match what our authored EMEVD expects).
    bonfire_asset_eid: int = 0
    # Player marker eid — referenced by 9005810 (bonfire register) in
    # the matching EMEVD.
    player_marker_eid: int = 0


# ───────────────────────────────────────────────────────────────────
# XML emit helpers
# ───────────────────────────────────────────────────────────────────


# Tested-against-MMV preamble: BOM + xml declaration + CRLF line endings.
# Witchy is sensitive to encoding/whitespace; we replicate MMV's output
# byte-style exactly. Notable quirks lifted from MMV reference files:
#   - UTF-8 BOM + xml declaration with CRLF terminator
#   - Body lines terminated with CRLF
#   - NO trailing CRLF after the closing tag (file ends with `</Tag>`)
#   - Integer-valued floats written as `0` not `0.0` (so we emit ints
#     when the float has no fractional part)
_XML_PROLOG = '\ufeff<?xml version="1.0" encoding="utf-8"?>\r\n'


def _fmt_num(v):
    """Format a numeric value matching MMV's style.

    Integer-valued floats render as '0', not '0.0'. Non-integer floats
    keep their float representation."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _xml_lines_to_str(lines: List[str]) -> str:
    """Join body lines into the final XML text. MMV files DON'T have a
    trailing CRLF after the closing tag — file ends with the last
    character of `</Tag>`. Replicate exactly."""
    return _XML_PROLOG + '\r\n'.join(lines)


def _emit_msbe_manifest(spec: ArenaSpec) -> str:
    """Top-level _witchy-msbe.xml."""
    H = MSBE_HEADER_UNKNOWNS
    parts_lines = []
    models_seen = set()
    # Player marker comes first (matches MMV ordering)
    parts_lines.append(
        f'    <part type="Enemy" name="{PLAYER_MARKER_C_PREFIX}_{PLAYER_MARKER_INSTANCE}" />')
    models_seen.add(PLAYER_MARKER_C_PREFIX)
    # Then each test chr
    for c in spec.test_chrs:
        parts_lines.append(
            f'    <part type="Enemy" name="{c.c_prefix}_{c.instance_id:04d}" />')
        models_seen.add(c.c_prefix)
    # Then the bonfire asset
    bf_name = f'{DEFAULT_BONFIRE_ASSET_MODEL}_{DEFAULT_BONFIRE_ASSET_INSTANCE:04d}'
    parts_lines.append(f'    <part type="Asset" name="{bf_name}" />')

    models_lines = []
    for cp in sorted(models_seen):
        models_lines.append(f'    <model type="Enemy" name="{cp}" />')
    models_lines.append(f'    <model type="Asset" name="{DEFAULT_BONFIRE_ASSET_MODEL}" />')

    lines = [
        f'<msbe WitchyVersion="{H["WitchyVersion"]}">',
        f'  <filename>{spec.host_arena_short}.msb.dcx</filename>',
        f'  <compression>{H["compression"]}</compression>',
        f'  <dfltUnk04>{H["dfltUnk04"]}</dfltUnk04>',
        f'  <dfltUnk10>{H["dfltUnk10"]}</dfltUnk10>',
        f'  <dfltUnk14>{H["dfltUnk14"]}</dfltUnk14>',
        f'  <dfltUnk30>{H["dfltUnk30"]}</dfltUnk30>',
        f'  <dfltUnk38>{H["dfltUnk38"]}</dfltUnk38>',
        '  <events>',
        '    <event type="PatrolInfo" name="{1}" />',
        '  </events>',
        '  <regions />',
        '  <parts>',
        *parts_lines,
        '  </parts>',
        '  <models>',
        *models_lines,
        '  </models>',
        '  <routes />',
        f'  <layers version="{H["layers_version"]}" />',
        '</msbe>',
    ]
    return _xml_lines_to_str(lines)


def _emit_model_enemy(c_prefix: str) -> str:
    """Model/Enemy/cXXXX.xml — just declares the chr's model exists."""
    lines = [
        '<Enemy xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
        f'  <Name>{c_prefix}</Name>',
        f'  <SibPath>W:\\CL\\data\\Model\\chr\\{c_prefix}\\sib\\{c_prefix}.sib</SibPath>',
        '  <Unk1C>0</Unk1C>',
        '</Enemy>',
    ]
    return _xml_lines_to_str(lines)


def _emit_model_asset(asset_name: str) -> str:
    """Model/Asset/AEG099_060.xml — asset model declaration."""
    lines = [
        '<Asset xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
        f'  <Name>{asset_name}</Name>',
        '  <SibPath />',
        '  <Unk1C>0</Unk1C>',
        '</Asset>',
    ]
    return _xml_lines_to_str(lines)


# These default field values are copied directly from MMV's m46_56
# c3100_9000.xml. Most are bookkeeping unknowns that we just want to
# match MMV's known-working values for. The fields that matter for
# our authored-arena behavior:
#   - GameEditionDisable: NeverDisable (chr alive at map-load)
#   - MapStudioLayer: 4294967295 (loaded on all layers)
#   - Condition1/2: 0 (no spawn conditions)
#   - ChrActivateCondParamID: 0 (no activation gate)
#   - EntityID: per-Part identifier (we set this)
#   - ModelName: chr prefix (we set this)
#   - NPCParamID: chr stats (we set this)
#   - ThinkParamID: chr AI (we set this, may default to 0)
#   - Position: per-Part location (we set this)


def _emit_part_enemy(c: TestChr) -> str:
    """Part/Enemy/cXXXX_NNNN.xml — one enemy instance."""
    name = f'{c.c_prefix}_{c.instance_id:04d}'
    lines = [
        '<Enemy xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
        f'  <Name>{name}</Name>',
        f'  <ModelName>{c.c_prefix}</ModelName>',
        f'  <InstanceID>{c.instance_id}</InstanceID>',
        '  <SibPath />',
        '  <Position>',
        f'    <X>{_fmt_num(c.position[0])}</X>',
        f'    <Y>{_fmt_num(c.position[1])}</Y>',
        f'    <Z>{_fmt_num(c.position[2])}</Z>',
        '  </Position>',
        '  <Rotation>',
        '    <X>0</X>',
        '    <Y>0</Y>',
        '    <Z>0</Z>',
        '  </Rotation>',
        '  <Scale>',
        '    <X>1</X>',
        '    <Y>1</Y>',
        '    <Z>1</Z>',
        '  </Scale>',
        '  <GameEditionDisable>NeverDisable</GameEditionDisable>',
        '  <MapStudioLayer>4294967295</MapStudioLayer>',
        f'  <EntityID>{c.eid}</EntityID>',
        '  <isUsePartsDrawParamID>0</isUsePartsDrawParamID>',
        '  <PartsDrawParamID>0</PartsDrawParamID>',
        '  <IsPointLightShadowSrc>0</IsPointLightShadowSrc>',
        '  <UnkE0B>0</UnkE0B>',
        '  <IsShadowSrc>false</IsShadowSrc>',
        '  <IsStaticShadowSrc>0</IsStaticShadowSrc>',
        '  <IsCascade3ShadowSrc>0</IsCascade3ShadowSrc>',
        '  <UnkE0F>1</UnkE0F>',
        '  <UnkE10>0</UnkE10>',
        '  <IsShadowDest>true</IsShadowDest>',
        '  <IsShadowOnly>false</IsShadowOnly>',
        '  <DrawByReflectCam>false</DrawByReflectCam>',
        '  <DrawOnlyReflectCam>false</DrawOnlyReflectCam>',
        '  <EnableOnAboveShadow>0</EnableOnAboveShadow>',
        '  <DisablePointLightEffect>false</DisablePointLightEffect>',
        '  <UnkE17>0</UnkE17>',
        '  <UnkE18>0</UnkE18>',
        '  <EntityGroupIDs>',
        *['    <unsignedInt>0</unsignedInt>'] * 8,
        '  </EntityGroupIDs>',
        '  <UnkE3C>-1</UnkE3C>',
        '  <UnkE3E>0</UnkE3E>',
        '  <Unk1>',
        '    <DisplayGroups>',
        '      <unsignedInt>1</unsignedInt>',
        *['      <unsignedInt>0</unsignedInt>'] * 7,
        '    </DisplayGroups>',
        '    <DrawGroups>',
        *['      <unsignedInt>0</unsignedInt>'] * 8,
        '    </DrawGroups>',
        '    <CollisionMask>',
        *['      <unsignedInt>0</unsignedInt>'] * 32,
        '    </CollisionMask>',
        '    <Condition1>0</Condition1>',
        '    <Condition2>0</Condition2>',
        '    <UnkC2>0</UnkC2>',
        '    <UnkC3>0</UnkC3>',
        '    <UnkC4>-1</UnkC4>',
        '    <UnkC6>0</UnkC6>',
        '  </Unk1>',
        '  <Gparam>',
        '    <LightSetID>-1</LightSetID>',
        '    <FogParamID>-1</FogParamID>',
        '    <LightScatteringID>0</LightScatteringID>',
        '    <EnvMapID>0</EnvMapID>',
        '  </Gparam>',
        '  <Unk8>',
        '    <Unk00>0</Unk00>',
        '  </Unk8>',
        '  <TileLoad>',
        '    <MapID>/////w==</MapID>',
        '    <Unk04>0</Unk04>',
        '    <Unk0C>-1</Unk0C>',
        '    <Unk10>0</Unk10>',
        '    <CullingHeightBehavior>-1</CullingHeightBehavior>',
        '  </TileLoad>',
        f'  <ThinkParamID>{c.think_param}</ThinkParamID>',
        f'  <NPCParamID>{c.npc_param}</NPCParamID>',
        '  <TalkID>0</TalkID>',
        '  <UnkT15>false</UnkT15>',
        '  <PlatoonID>0</PlatoonID>',
        '  <CharaInitID>-1</CharaInitID>',
        '  <WalkRouteName> {1}</WalkRouteName>',
        '  <UnkT24>-1</UnkT24>',
        '  <UnkT28>0</UnkT28>',
        '  <ChrActivateCondParamID>0</ChrActivateCondParamID>',
        '  <UnkT34>0</UnkT34>',
        '  <BackupEventAnimID>-1</BackupEventAnimID>',
        '  <UnkT3C>255</UnkT3C>',
        '  <SpEffectSetParamID>',
        *['    <int>0</int>'] * 4,
        '  </SpEffectSetParamID>',
        '  <UnkT84>1</UnkT84>',
        '</Enemy>',
    ]
    return _xml_lines_to_str(lines)


def _emit_part_player_marker(eid: int) -> str:
    """Part/Enemy/c1000_9000.xml — the player-distance marker.

    Lifted verbatim from MMV m46_56 c1000_9000.xml: position Y=-0.5
    (slightly below ground so it doesn't visually appear), NPCParamID
    10000000 (default player), TalkID 1000, UnkT3C -65281."""
    lines = [
        '<Enemy xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
        f'  <Name>{PLAYER_MARKER_C_PREFIX}_{PLAYER_MARKER_INSTANCE}</Name>',
        f'  <ModelName>{PLAYER_MARKER_C_PREFIX}</ModelName>',
        f'  <InstanceID>{PLAYER_MARKER_INSTANCE}</InstanceID>',
        '  <SibPath />',
        '  <Position>',
        '    <X>0</X>',
        '    <Y>-0.5</Y>',
        '    <Z>0</Z>',
        '  </Position>',
        '  <Rotation>',
        '    <X>0</X>',
        '    <Y>0</Y>',
        '    <Z>0</Z>',
        '  </Rotation>',
        '  <Scale>',
        '    <X>1</X>',
        '    <Y>1</Y>',
        '    <Z>1</Z>',
        '  </Scale>',
        '  <GameEditionDisable>NeverDisable</GameEditionDisable>',
        '  <MapStudioLayer>4294967295</MapStudioLayer>',
        f'  <EntityID>{eid}</EntityID>',
        '  <isUsePartsDrawParamID>0</isUsePartsDrawParamID>',
        '  <PartsDrawParamID>0</PartsDrawParamID>',
        '  <IsPointLightShadowSrc>0</IsPointLightShadowSrc>',
        '  <UnkE0B>0</UnkE0B>',
        '  <IsShadowSrc>false</IsShadowSrc>',
        '  <IsStaticShadowSrc>0</IsStaticShadowSrc>',
        '  <IsCascade3ShadowSrc>0</IsCascade3ShadowSrc>',
        '  <UnkE0F>1</UnkE0F>',
        '  <UnkE10>0</UnkE10>',
        '  <IsShadowDest>true</IsShadowDest>',
        '  <IsShadowOnly>false</IsShadowOnly>',
        '  <DrawByReflectCam>false</DrawByReflectCam>',
        '  <DrawOnlyReflectCam>false</DrawOnlyReflectCam>',
        '  <EnableOnAboveShadow>0</EnableOnAboveShadow>',
        '  <DisablePointLightEffect>false</DisablePointLightEffect>',
        '  <UnkE17>0</UnkE17>',
        '  <UnkE18>0</UnkE18>',
        '  <EntityGroupIDs>',
        *['    <unsignedInt>0</unsignedInt>'] * 8,
        '  </EntityGroupIDs>',
        '  <UnkE3C>-1</UnkE3C>',
        '  <UnkE3E>0</UnkE3E>',
        '  <Unk1>',
        '    <DisplayGroups>',
        '      <unsignedInt>1</unsignedInt>',
        *['      <unsignedInt>0</unsignedInt>'] * 7,
        '    </DisplayGroups>',
        '    <DrawGroups>',
        *['      <unsignedInt>0</unsignedInt>'] * 8,
        '    </DrawGroups>',
        '    <CollisionMask>',
        *['      <unsignedInt>0</unsignedInt>'] * 32,
        '    </CollisionMask>',
        '    <Condition1>0</Condition1>',
        '    <Condition2>0</Condition2>',
        '    <UnkC2>0</UnkC2>',
        '    <UnkC3>0</UnkC3>',
        '    <UnkC4>-1</UnkC4>',
        '    <UnkC6>0</UnkC6>',
        '  </Unk1>',
        '  <Gparam>',
        '    <LightSetID>-1</LightSetID>',
        '    <FogParamID>-1</FogParamID>',
        '    <LightScatteringID>0</LightScatteringID>',
        '    <EnvMapID>0</EnvMapID>',
        '  </Gparam>',
        '  <Unk8>',
        '    <Unk00>0</Unk00>',
        '  </Unk8>',
        '  <TileLoad>',
        '    <MapID>/////w==</MapID>',
        '    <Unk04>0</Unk04>',
        '    <Unk0C>-1</Unk0C>',
        '    <Unk10>0</Unk10>',
        '    <CullingHeightBehavior>-1</CullingHeightBehavior>',
        '  </TileLoad>',
        '  <ThinkParamID>1</ThinkParamID>',
        '  <NPCParamID>10000000</NPCParamID>',
        '  <TalkID>1000</TalkID>',
        '  <UnkT15>false</UnkT15>',
        '  <PlatoonID>0</PlatoonID>',
        '  <CharaInitID>-1</CharaInitID>',
        '  <UnkT24>-1</UnkT24>',
        '  <UnkT28>0</UnkT28>',
        '  <ChrActivateCondParamID>0</ChrActivateCondParamID>',
        '  <UnkT34>0</UnkT34>',
        '  <BackupEventAnimID>-1</BackupEventAnimID>',
        '  <UnkT3C>-65281</UnkT3C>',
        '  <SpEffectSetParamID>',
        *['    <int>0</int>'] * 4,
        '  </SpEffectSetParamID>',
        '  <UnkT84>1</UnkT84>',
        '</Enemy>',
    ]
    return _xml_lines_to_str(lines)


def _emit_part_bonfire(eid: int) -> str:
    """Part/Asset/AEG099_060_9000.xml — Site of Grace asset."""
    name = f'{DEFAULT_BONFIRE_ASSET_MODEL}_{DEFAULT_BONFIRE_ASSET_INSTANCE:04d}'
    # Asset Parts have a slightly different schema than Enemy Parts.
    # Including only the fields verified in MMV's AEG099_060_9000.xml.
    # NOTE: this is partially complete — the Asset Part schema in NR has
    # additional fields beyond what we capture here. For a known-working
    # baseline, we'd ideally copy AEG099_060_9000.xml from MMV m46_56
    # verbatim and patch only the EntityID. That's what `apply_to_dir`
    # does below.
    lines = [
        '<Asset xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
        f'  <Name>{name}</Name>',
        f'  <ModelName>{DEFAULT_BONFIRE_ASSET_MODEL}</ModelName>',
        f'  <InstanceID>{DEFAULT_BONFIRE_ASSET_INSTANCE}</InstanceID>',
        '  <SibPath />',
        '  <Position><X>0</X><Y>0</Y><Z>0</Z></Position>',
        '  <Rotation><X>0</X><Y>0</Y><Z>0</Z></Rotation>',
        '  <Scale><X>1</X><Y>1</Y><Z>1</Z></Scale>',
        '  <GameEditionDisable>NeverDisable</GameEditionDisable>',
        '  <MapStudioLayer>4294967295</MapStudioLayer>',
        f'  <EntityID>{eid}</EntityID>',
        '  <!-- INCOMPLETE: Asset Part schema needs more fields. -->',
        '  <!-- Use apply_to_dir() to copy MMV AEG099_060_9000.xml -->',
        '  <!-- verbatim, patching only the EntityID. -->',
        '</Asset>',
    ]
    return _xml_lines_to_str(lines)


# ───────────────────────────────────────────────────────────────────
# Apply to directory
# ───────────────────────────────────────────────────────────────────


def apply_to_dir(spec: ArenaSpec, out_dir: Path,
                 mmv_template_dir: Path) -> Path:
    """Write the Witchy directory tree.

    `mmv_template_dir` is a witchy'd MMV MSB used as the byte-level
    template for the Asset Part (which has fields we don't fully cover
    yet). Recommended: /tmp/mmv_msb/m46_56_00_00-msb-dcx.

    Returns the path to the created witchy directory.
    """
    arena_dir = out_dir / f'{spec.host_arena_short}-msb-dcx'
    if arena_dir.exists():
        shutil.rmtree(arena_dir)
    arena_dir.mkdir(parents=True)

    # Subdirs that Witchy expects
    (arena_dir / 'Event' / 'PatrolInfo').mkdir(parents=True)
    (arena_dir / 'Model' / 'Enemy').mkdir(parents=True)
    (arena_dir / 'Model' / 'Asset').mkdir(parents=True)
    (arena_dir / 'Part' / 'Enemy').mkdir(parents=True)
    (arena_dir / 'Part' / 'Asset').mkdir(parents=True)
    # Region/Route empty but the manifest references them
    # (Witchy may not require the dirs to exist if empty in manifest)

    # 1. Top-level manifest
    (arena_dir / '_witchy-msbe.xml').write_text(
        _emit_msbe_manifest(spec), encoding='utf-8')

    # 2. Models
    unique_chrs = sorted(set(c.c_prefix for c in spec.test_chrs))
    for cp in [PLAYER_MARKER_C_PREFIX] + unique_chrs:
        (arena_dir / 'Model' / 'Enemy' / f'{cp}.xml').write_text(
            _emit_model_enemy(cp), encoding='utf-8')
    (arena_dir / 'Model' / 'Asset' / f'{DEFAULT_BONFIRE_ASSET_MODEL}.xml').write_text(
        _emit_model_asset(DEFAULT_BONFIRE_ASSET_MODEL), encoding='utf-8')

    # 3. Parts — Enemy
    (arena_dir / 'Part' / 'Enemy' /
     f'{PLAYER_MARKER_C_PREFIX}_{PLAYER_MARKER_INSTANCE}.xml').write_text(
        _emit_part_player_marker(spec.player_marker_eid), encoding='utf-8')
    for c in spec.test_chrs:
        fn = f'{c.c_prefix}_{c.instance_id:04d}.xml'
        (arena_dir / 'Part' / 'Enemy' / fn).write_text(
            _emit_part_enemy(c), encoding='utf-8')

    # 4. Parts — Asset (bonfire)
    # Strategy: copy the MMV template asset Part XML verbatim, then patch
    # the EntityID. This guarantees byte-level field coverage including
    # all the bookkeeping fields we don't emit explicitly.
    bf_name = f'{DEFAULT_BONFIRE_ASSET_MODEL}_{DEFAULT_BONFIRE_ASSET_INSTANCE:04d}'
    template_asset = (mmv_template_dir / 'Part' / 'Asset' / f'{bf_name}.xml')
    out_asset = arena_dir / 'Part' / 'Asset' / f'{bf_name}.xml'
    if template_asset.exists():
        # Copy bytes verbatim, then patch EntityID via simple regex
        import re
        content = template_asset.read_text(encoding='utf-8')
        content = re.sub(
            r'<EntityID>\d+</EntityID>',
            f'<EntityID>{spec.bonfire_asset_eid}</EntityID>',
            content, count=1)
        out_asset.write_text(content, encoding='utf-8')
    else:
        # Fallback: our emitter (known to be incomplete)
        out_asset.write_text(_emit_part_bonfire(spec.bonfire_asset_eid),
                              encoding='utf-8')
        print(f'WARN: MMV template asset not found at {template_asset};')
        print(f'      using fallback emitter which may be incomplete.')

    return arena_dir


# ───────────────────────────────────────────────────────────────────
# Matching EMEVD emission (uses emit_mmv_style_arena_emevd)
# ───────────────────────────────────────────────────────────────────


def emit_matching_emevd(spec: ArenaSpec, out_path: Path) -> Path:
    """Generate the EMEVD binary that pairs with this MSB.

    Uses dev/emit_mmv_style_arena_emevd.py (the formerly-deprecated
    module that's the right tool now that we control the MSB to match).

    Writes <out_path>.emevd (binary, pre-DCX). The pipeline's DCX
    compression step will produce the .emevd.dcx the engine loads.
    """
    import importlib.util
    here = Path(__file__).parent
    emit_path = here / 'emit_mmv_style_arena_emevd.py'
    loader = importlib.util.spec_from_file_location(
        'emit_mmv_style_arena_emevd', emit_path)
    mod = importlib.util.module_from_spec(loader)
    import sys
    sys.modules['emit_mmv_style_arena_emevd'] = mod
    loader.loader.exec_module(mod)

    # Map prefix is the first 4 numeric digits of the host arena name
    # (m48_70_00_00 → '4870' so eids 48700800 = 4870 + 0800).
    parts = spec.host_arena_short.split('_')
    map_prefix = f'{parts[0][1:]}{parts[1]}'  # m48 → 48, 70 → 70 → '4870'

    tmpl = mod.ArenaTemplate(map_prefix=map_prefix)
    for i, c in enumerate(spec.test_chrs):
        # eid_suffix = last 4 digits of the chr's eid
        eid_suffix = f'{c.eid % 10000:04d}'
        # death_flag: pick a unique flag per chr in the arena's eid
        # namespace. MMV uses arbitrary flags here; we use eid + i*10000
        # to keep them sequential and easy to read in logs.
        death_flag = c.eid + (i + 1) * 10000  # e.g. 48710800, 48720800...
        # We have no nameId lookup; default 11290 matches MMV's choice
        # (text-table reference for boss name display).
        tmpl.add_boss(eid_suffix=eid_suffix, npc_param=c.npc_param,
                      death_flag=death_flag, name_id=11290)

    # The module's main public method is emit_binary()
    raw = tmpl.emit_binary()
    out_path.write_bytes(raw)
    return out_path


# A starter roster for testing. Pick varied chrs to exercise the
# substitution-survival hypothesis: a mainline boss, a field boss, a
# spirit/weird chr, etc. NpcParam values picked from observed vanilla
# placements (e.g. m48_90 vanilla Wormface uses 904580600).
DEFAULT_ROSTER = [
    # c_prefix, npc_param,  think_param, position_x
    ('c4580',   904580600,  0,           0),    # Large Wormface
    ('c2280',   228000000,  0,           10),   # Valiant Gargoyle (guess)
    ('c4770',   477000000,  0,           20),   # Valiant Gargoyle alt
    ('c3570',   903570000,  0,           30),   # Godskin Noble
    ('c4650',   904650601,  0,           40),   # Dragonkin Soldier
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='m48_70_00_00',
                     help='Host arena to hijack (default: m48_70_00_00)')
    ap.add_argument('--out-dir', default='/tmp/authored_arena',
                     help='Output directory for the witchy tree')
    ap.add_argument('--mmv-template-dir',
                     default='/tmp/mmv_msb/m46_56_00_00-msb-dcx',
                     help='Path to a witchy MMV MSB used as byte template')
    ap.add_argument('--eid-base', type=int, default=None,
                     help='EID base (default: derived from host, e.g. '
                          'm48_70 → 48700800)')
    args = ap.parse_args()

    # Derive eid base from host arena name (m48_70_00_00 → 48700000)
    if args.eid_base is None:
        # Parse the m48_70_00_00 form
        host_parts = args.host.split('_')
        # e.g. ['m48', '70', '00', '00'] → 48 70 00 00
        if len(host_parts) >= 2:
            major = int(host_parts[0][1:])  # strip 'm'
            minor = int(host_parts[1])
            args.eid_base = major * 1000000 + minor * 10000

    # Build the spec
    spec = ArenaSpec(
        host_arena_short=args.host,
        player_marker_eid=args.eid_base + 500,    # e.g. 48700500
        bonfire_asset_eid=args.eid_base + 1500,   # e.g. 48701500
    )
    # Space chr eids by 10 (MMV convention: 0800, 0810, 0820, ...).
    # Each chr also gets a unique instance_id to keep ModelName-shared
    # chrs (if any) distinct in the MSB.
    for i, (cp, npc, think, x) in enumerate(DEFAULT_ROSTER):
        spec.test_chrs.append(TestChr(
            c_prefix=cp,
            npc_param=npc,
            think_param=think,
            eid=args.eid_base + 800 + i * 10,    # 48700800, 48700810, ...
            instance_id=9000 + i,                 # unique per Part
            position=(float(x), 0.0, 0.0),
        ))

    out = apply_to_dir(spec, Path(args.out_dir),
                       Path(args.mmv_template_dir))
    print(f'\nWitchy directory written to: {out}')

    # Generate the matching EMEVD binary
    emevd_path = Path(args.out_dir) / f'{args.host}.emevd'
    emit_matching_emevd(spec, emevd_path)
    print(f'Matching EMEVD written to:   {emevd_path}')
    print(f'                              (pre-DCX; pipeline will compress)')

    print('\nNext steps (user-side):')
    print(f'  1. Run Witchy Repack on: {out}')
    print(f'     Produces: {out.parent}/{args.host}.msb.dcx')
    print(f'  2. DCX-compress the EMEVD with the pipeline\'s oodle path,')
    print(f'     OR drop the .emevd raw and let the build step compress.')
    print(f'  3. Drop both files into the me3 profile:')
    print(f'     <me3_profile>/map/mapstudio/{args.host}.msb.dcx')
    print(f'     <me3_profile>/map/mapstudio/{args.host}.emevd.dcx')
    print(f'  4. Launch and walk to where vanilla {args.host} would put')
    print(f'     you. The {len(spec.test_chrs)} test chrs should be alive on arrival.')


if __name__ == '__main__':
    main()
