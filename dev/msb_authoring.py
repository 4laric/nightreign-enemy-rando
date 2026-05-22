#!/usr/bin/env python3
"""msb_authoring.py — author a mob-only overlay MSB matching MMV's pattern.

Path B of test-mode design (see dev/TEST_MODE.md).

What this does
==============
Emits a Witchy-compatible XML directory describing a custom mob-only
MSB. The user runs Witchy locally (Repack) to convert the XML directory
into a .msb.dcx file the engine can load.

Output directory shape (mirrors `witchy <path>.msb.dcx` extraction):
    <out_dir>/<map_name>-msb-dcx/
        _witchy-msbe.xml          # MSB manifest
        Part/Enemy/<name>.xml     # one per chr placement
        Model/Enemy/<cXXXX>.xml   # one per unique chr model

Design choices
==============
1. All chr Parts get GameEditionDisable=NeverDisable + MapStudioLayer=
   0xFFFFFFFF + Condition1/2=0 + ChrActivateCondParamID=0. Same canonical
   values MMV uses on every Part. This is what makes chrs alive at
   map-load.

2. We DON'T emit: regions, routes, assets, events, player spawns. Pure
   mob-only. The Limveld tile underneath (m60_xx) provides geometry.

3. Models registered = exactly the union of cXXXX referenced by Parts.
   MMV sometimes registers extra "unused" models — we don't bother.

4. Layout: chrs spaced 5 units apart along the X axis. Centered roughly
   at the slot's nominal origin. This puts them on a line so you can see
   the whole roster at a glance and walk down it.

5. EntityIDs follow the slot's convention: <slot_prefix>800, 810, 820,
   ... (e.g., for m48_80 → 48800800, 48800810). This matches what the
   vanilla EMEVD machinery references, so if we pair this MSB with the
   matching MMV-style EMEVD (via emit_mmv_style_arena_emevd.py) the
   healthbar / music / death tracking events resolve correctly.

Workflow
========
1. Define a ChrRoster (which chrs at which slots).
2. Call author_msb() → writes XML directory.
3. User: `WitchyBND.exe -r <out_dir>/<map_name>-msb-dcx` to repack into
   .msb.dcx. (Or whatever Witchy's CLI invocation is — confirm locally.)
4. Drop the .msb.dcx into the me3 profile at the path that overrides
   vanilla's MSB for the chosen slot.
5. Pair with a matching MMV-style EMEVD (via dev/emit_mmv_style_arena_emevd.py).
6. Launch game, walk to the slot's Limveld location, observe the roster.

Slot hijack strategy
====================
The simplest first run: pick a vanilla N1/N2 expedition arena slot to
override (e.g., m48_80). The engine loads our MSB instead of vanilla's.
Whatever expedition routes through that slot exercises our test roster.

Pick by which Nightlord's path you want to use as the test vehicle:
seed-routing dictates which slot the player visits. m48_90 is
Gaping Jaw-path N1; that's a reasonable first choice since it covers
the most-common boss-init pattern.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# Constants observed across all 31 MMV MSBs. These are the "boilerplate"
# field values on every Enemy Part.
PART_CONST = {
    'GameEditionDisable': 'NeverDisable',
    'MapStudioLayer': '4294967295',  # 0xFFFFFFFF
    'Condition1': '0',
    'Condition2': '0',
    'ChrActivateCondParamID': '0',
    'IsPointLightShadowSrc': '0',
    'UnkE0B': '0',
    'IsShadowSrc': 'false',
    'IsStaticShadowSrc': '0',
    'IsCascade3ShadowSrc': '0',
    'UnkE0F': '1',
    'UnkE10': '0',
    'IsShadowDest': 'true',
    'IsShadowOnly': 'false',
    'DrawByReflectCam': 'false',
    'DrawOnlyReflectCam': 'false',
    'EnableOnAboveShadow': '0',
    'DisablePointLightEffect': 'false',
    'UnkE17': '0',
    'UnkE18': '0',
    'UnkE3C': '-1',
    'UnkE3E': '0',
    'UnkC2': '0',
    'UnkC3': '0',
    'UnkC4': '-1',
    'UnkC6': '0',
    'LightSetID': '-1',
    'FogParamID': '-1',
    'LightScatteringID': '0',
    'EnvMapID': '0',
    'Unk00': '0',
    'MapID': '/////w==',
    'Unk04': '0',
    'Unk0C': '-1',
    'Unk10': '0',
    'CullingHeightBehavior': '-1',
    'PlatoonID': '0',
    'CharaInitID': '-1',
    'UnkT15': 'false',
    'UnkT24': '-1',
    'UnkT28': '0',
    'UnkT34': '0',
    'BackupEventAnimID': '-1',
    'UnkT84': '1',
    'isUsePartsDrawParamID': '0',
    'PartsDrawParamID': '0',
}

# Header file constants
WITCHY_HEADER_CONST = {
    'compression': 'DCX_DFLT',
    'dfltUnk04': '69632',
    'dfltUnk10': '68',
    'dfltUnk14': '76',
    'dfltUnk30': '9',
    'dfltUnk38': '15',
}
WITCHY_VERSION = '2080001'
LAYERS_VERSION = '79'  # MMV uses 79 for older maps, 80 for newer; 79 is safe default


# Field values that vary per chr. Talk ID is usually 0; -65281 for some
# bonfire-style "interactive" chrs (the c1000 hub Part in MMV). For
# test-mode bosses, always use 0 / 255.
@dataclass
class ChrSpec:
    """One chr to place in the MSB.

    Required: c_prefix (e.g., 'c4770'), npc_param, think_param.
    Optional everything else — defaults match a generic combat enemy.
    """
    c_prefix: str           # model name, e.g., 'c4770'
    npc_param: int          # NPCParamID
    think_param: int        # ThinkParamID
    instance_id: int = 9000 # MMV always uses 9000; second chr of same
                            #   prefix would be 9001, 9002, ...
    entity_id: int = 0      # slot's runtime entity ID; 0 = "no specific eid"
    talk_id: int = 0
    unk_t3c: int = 255      # 255 standard, -65281 for bonfire NPCs
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)

    @property
    def part_name(self) -> str:
        return f'{self.c_prefix}_{self.instance_id:04d}'


@dataclass
class ArenaSpec:
    """The whole authored MSB."""
    map_name: str           # e.g., 'm48_90_00_00'
    chrs: List[ChrSpec] = field(default_factory=list)

    @property
    def msb_filename(self) -> str:
        return f'{self.map_name}.msb.dcx'

    @property
    def witchy_dir_name(self) -> str:
        return f'{self.map_name}-msb-dcx'

    @property
    def unique_models(self) -> List[str]:
        """Unique c_prefixes in placement order (first appearance)."""
        seen = []
        for c in self.chrs:
            if c.c_prefix not in seen:
                seen.append(c.c_prefix)
        return seen


# ── Emit helpers ─────────────────────────────────────────────────────


_PART_HEADER = '\ufeff<?xml version="1.0" encoding="utf-8"?>'  # BOM + decl; no trailing nl


def _fmt_num(v) -> str:
    """Format a number: integer if whole, decimal otherwise.

    MMV writes <X>0</X> not <X>0.0</X>; <Y>-0.5</Y> when non-integer.
    """
    if isinstance(v, int):
        return str(v)
    if v == int(v):
        return str(int(v))
    return str(v)


def emit_part_enemy_xml(chr_: ChrSpec) -> str:
    """Generate the <Enemy>...</Enemy> XML for one Part.

    Structure mirrors MMV's reference XML exactly — see
    /tmp/mmv_msb/m46_56_00_00-msb-dcx/Part/Enemy/c3100_9000.xml as
    the canonical example.
    """
    L = [
        _PART_HEADER,
        '<Enemy xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
        f'  <Name>{chr_.part_name}</Name>',
        f'  <ModelName>{chr_.c_prefix}</ModelName>',
        f'  <InstanceID>{chr_.instance_id}</InstanceID>',
        '  <SibPath />',
        '  <Position>',
        f'    <X>{_fmt_num(chr_.position[0])}</X>',
        f'    <Y>{_fmt_num(chr_.position[1])}</Y>',
        f'    <Z>{_fmt_num(chr_.position[2])}</Z>',
        '  </Position>',
        '  <Rotation>',
        f'    <X>{_fmt_num(chr_.rotation[0])}</X>',
        f'    <Y>{_fmt_num(chr_.rotation[1])}</Y>',
        f'    <Z>{_fmt_num(chr_.rotation[2])}</Z>',
        '  </Rotation>',
        '  <Scale>',
        f'    <X>{_fmt_num(chr_.scale[0])}</X>',
        f'    <Y>{_fmt_num(chr_.scale[1])}</Y>',
        f'    <Z>{_fmt_num(chr_.scale[2])}</Z>',
        '  </Scale>',
        f'  <GameEditionDisable>{PART_CONST["GameEditionDisable"]}</GameEditionDisable>',
        f'  <MapStudioLayer>{PART_CONST["MapStudioLayer"]}</MapStudioLayer>',
        f'  <EntityID>{chr_.entity_id}</EntityID>',
        f'  <isUsePartsDrawParamID>{PART_CONST["isUsePartsDrawParamID"]}</isUsePartsDrawParamID>',
        f'  <PartsDrawParamID>{PART_CONST["PartsDrawParamID"]}</PartsDrawParamID>',
        f'  <IsPointLightShadowSrc>{PART_CONST["IsPointLightShadowSrc"]}</IsPointLightShadowSrc>',
        f'  <UnkE0B>{PART_CONST["UnkE0B"]}</UnkE0B>',
        f'  <IsShadowSrc>{PART_CONST["IsShadowSrc"]}</IsShadowSrc>',
        f'  <IsStaticShadowSrc>{PART_CONST["IsStaticShadowSrc"]}</IsStaticShadowSrc>',
        f'  <IsCascade3ShadowSrc>{PART_CONST["IsCascade3ShadowSrc"]}</IsCascade3ShadowSrc>',
        f'  <UnkE0F>{PART_CONST["UnkE0F"]}</UnkE0F>',
        f'  <UnkE10>{PART_CONST["UnkE10"]}</UnkE10>',
        f'  <IsShadowDest>{PART_CONST["IsShadowDest"]}</IsShadowDest>',
        f'  <IsShadowOnly>{PART_CONST["IsShadowOnly"]}</IsShadowOnly>',
        f'  <DrawByReflectCam>{PART_CONST["DrawByReflectCam"]}</DrawByReflectCam>',
        f'  <DrawOnlyReflectCam>{PART_CONST["DrawOnlyReflectCam"]}</DrawOnlyReflectCam>',
        f'  <EnableOnAboveShadow>{PART_CONST["EnableOnAboveShadow"]}</EnableOnAboveShadow>',
        f'  <DisablePointLightEffect>{PART_CONST["DisablePointLightEffect"]}</DisablePointLightEffect>',
        f'  <UnkE17>{PART_CONST["UnkE17"]}</UnkE17>',
        f'  <UnkE18>{PART_CONST["UnkE18"]}</UnkE18>',
        '  <EntityGroupIDs>',
    ]
    L.extend(['    <unsignedInt>0</unsignedInt>'] * 8)
    L.append('  </EntityGroupIDs>')
    L.append(f'  <UnkE3C>{PART_CONST["UnkE3C"]}</UnkE3C>')
    L.append(f'  <UnkE3E>{PART_CONST["UnkE3E"]}</UnkE3E>')

    # Unk1 block
    L.append('  <Unk1>')
    L.append('    <DisplayGroups>')
    L.append('      <unsignedInt>1</unsignedInt>')
    L.extend(['      <unsignedInt>0</unsignedInt>'] * 7)
    L.append('    </DisplayGroups>')
    L.append('    <DrawGroups>')
    L.extend(['      <unsignedInt>0</unsignedInt>'] * 8)
    L.append('    </DrawGroups>')
    L.append('    <CollisionMask>')
    L.extend(['      <unsignedInt>0</unsignedInt>'] * 32)
    L.append('    </CollisionMask>')
    L.append(f'    <Condition1>{PART_CONST["Condition1"]}</Condition1>')
    L.append(f'    <Condition2>{PART_CONST["Condition2"]}</Condition2>')
    L.append(f'    <UnkC2>{PART_CONST["UnkC2"]}</UnkC2>')
    L.append(f'    <UnkC3>{PART_CONST["UnkC3"]}</UnkC3>')
    L.append(f'    <UnkC4>{PART_CONST["UnkC4"]}</UnkC4>')
    L.append(f'    <UnkC6>{PART_CONST["UnkC6"]}</UnkC6>')
    L.append('  </Unk1>')

    # Gparam block (lighting/fog params)
    L.append('  <Gparam>')
    L.append(f'    <LightSetID>{PART_CONST["LightSetID"]}</LightSetID>')
    L.append(f'    <FogParamID>{PART_CONST["FogParamID"]}</FogParamID>')
    L.append(f'    <LightScatteringID>{PART_CONST["LightScatteringID"]}</LightScatteringID>')
    L.append(f'    <EnvMapID>{PART_CONST["EnvMapID"]}</EnvMapID>')
    L.append('  </Gparam>')

    # Unk8 block (just one field)
    L.append('  <Unk8>')
    L.append(f'    <Unk00>{PART_CONST["Unk00"]}</Unk00>')
    L.append('  </Unk8>')

    # TileLoad block
    L.append('  <TileLoad>')
    L.append(f'    <MapID>{PART_CONST["MapID"]}</MapID>')
    L.append(f'    <Unk04>{PART_CONST["Unk04"]}</Unk04>')
    L.append(f'    <Unk0C>{PART_CONST["Unk0C"]}</Unk0C>')
    L.append(f'    <Unk10>{PART_CONST["Unk10"]}</Unk10>')
    L.append(f'    <CullingHeightBehavior>{PART_CONST["CullingHeightBehavior"]}</CullingHeightBehavior>')
    L.append('  </TileLoad>')

    # Chr-identity tail
    L.append(f'  <ThinkParamID>{chr_.think_param}</ThinkParamID>')
    L.append(f'  <NPCParamID>{chr_.npc_param}</NPCParamID>')
    L.append(f'  <TalkID>{chr_.talk_id}</TalkID>')
    L.append(f'  <UnkT15>{PART_CONST["UnkT15"]}</UnkT15>')
    L.append(f'  <PlatoonID>{PART_CONST["PlatoonID"]}</PlatoonID>')
    L.append(f'  <CharaInitID>{PART_CONST["CharaInitID"]}</CharaInitID>')
    L.append('  <WalkRouteName> {1}</WalkRouteName>')  # leading space matches MMV
    L.append(f'  <UnkT24>{PART_CONST["UnkT24"]}</UnkT24>')
    L.append(f'  <UnkT28>{PART_CONST["UnkT28"]}</UnkT28>')
    L.append(f'  <ChrActivateCondParamID>{PART_CONST["ChrActivateCondParamID"]}</ChrActivateCondParamID>')
    L.append(f'  <UnkT34>{PART_CONST["UnkT34"]}</UnkT34>')
    L.append(f'  <BackupEventAnimID>{PART_CONST["BackupEventAnimID"]}</BackupEventAnimID>')
    L.append(f'  <UnkT3C>{chr_.unk_t3c}</UnkT3C>')
    L.append('  <SpEffectSetParamID>')
    L.extend(['    <int>0</int>'] * 4)
    L.append('  </SpEffectSetParamID>')
    L.append(f'  <UnkT84>{PART_CONST["UnkT84"]}</UnkT84>')
    L.append('</Enemy>')
    return '\n'.join(L)


def emit_model_enemy_xml(c_prefix: str) -> str:
    """Generate the 3-field Model/Enemy/<cXXXX>.xml registration."""
    return (
        _PART_HEADER + '\n'
        + '<Enemy xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
          'xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'
        + f'  <Name>{c_prefix}</Name>\n'
        + f'  <SibPath>W:\\CL\\data\\Model\\chr\\{c_prefix}\\sib\\{c_prefix}.sib</SibPath>\n'
        + '  <Unk1C>0</Unk1C>\n'
        + '</Enemy>'
    )


def emit_witchy_header_xml(arena: ArenaSpec) -> str:
    """Generate the _witchy-msbe.xml manifest."""
    L = [
        _PART_HEADER,
        f'<msbe WitchyVersion="{WITCHY_VERSION}">',
        f'  <filename>{arena.msb_filename}</filename>',
        f'  <compression>{WITCHY_HEADER_CONST["compression"]}</compression>',
        f'  <dfltUnk04>{WITCHY_HEADER_CONST["dfltUnk04"]}</dfltUnk04>',
        f'  <dfltUnk10>{WITCHY_HEADER_CONST["dfltUnk10"]}</dfltUnk10>',
        f'  <dfltUnk14>{WITCHY_HEADER_CONST["dfltUnk14"]}</dfltUnk14>',
        f'  <dfltUnk30>{WITCHY_HEADER_CONST["dfltUnk30"]}</dfltUnk30>',
        f'  <dfltUnk38>{WITCHY_HEADER_CONST["dfltUnk38"]}</dfltUnk38>',
        '  <events />',
        '  <regions />',
        '  <parts>',
    ]
    for chr_ in arena.chrs:
        L.append(f'    <part type="Enemy" name="{chr_.part_name}" />')
    L.append('  </parts>')
    L.append('  <models>')
    for c_prefix in arena.unique_models:
        L.append(f'    <model type="Enemy" name="{c_prefix}" />')
    L.append('  </models>')
    L.append('  <routes />')
    L.append(f'  <layers version="{LAYERS_VERSION}" />')
    L.append('</msbe>')
    return '\n'.join(L)


# ── Top-level authoring entry point ──────────────────────────────────


def author_msb(arena: ArenaSpec, out_dir: str) -> str:
    """Write the Witchy-format XML directory for one MSB.

    Files are written with CRLF line endings to match MMV's reference
    output (Witchy is a Windows tool — its XMLs are CRLF).

    Returns the path to the written <map_name>-msb-dcx directory.
    """
    target = os.path.join(out_dir, arena.witchy_dir_name)
    os.makedirs(os.path.join(target, 'Part', 'Enemy'), exist_ok=True)
    os.makedirs(os.path.join(target, 'Model', 'Enemy'), exist_ok=True)

    def _write_crlf(path: str, text: str):
        # Newline='' disables newline translation; we use explicit \r\n
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text.replace('\n', '\r\n'))

    _write_crlf(os.path.join(target, '_witchy-msbe.xml'),
                emit_witchy_header_xml(arena))

    for chr_ in arena.chrs:
        path = os.path.join(target, 'Part', 'Enemy', f'{chr_.part_name}.xml')
        _write_crlf(path, emit_part_enemy_xml(chr_))

    for c_prefix in arena.unique_models:
        path = os.path.join(target, 'Model', 'Enemy', f'{c_prefix}.xml')
        _write_crlf(path, emit_model_enemy_xml(c_prefix))

    return target


# ── Convenience: build a roster spread along the X axis ─────────────


def build_linear_roster(map_name: str, chrs: List[ChrSpec],
                         x_spacing: float = 5.0,
                         base_eid: int = 0) -> ArenaSpec:
    """Build an ArenaSpec where chrs are positioned in a line along X.

    If base_eid is set, entity IDs are assigned as base_eid, base_eid+10,
    base_eid+20, ... matching NR's slot-spacing convention (the boss-tier
    slot for m48_80 is 48800800, secondary is 48800810).
    """
    arena = ArenaSpec(map_name=map_name)
    for i, c in enumerate(chrs):
        # Clone with assigned position + eid (if not already set)
        positioned = ChrSpec(
            c_prefix=c.c_prefix,
            npc_param=c.npc_param,
            think_param=c.think_param,
            instance_id=c.instance_id,
            entity_id=c.entity_id or (base_eid + i*10 if base_eid else 0),
            talk_id=c.talk_id,
            unk_t3c=c.unk_t3c,
            position=c.position if c.position != (0.0, 0.0, 0.0)
                     else (i * x_spacing, 0.0, 0.0),
            rotation=c.rotation,
            scale=c.scale,
        )
        arena.chrs.append(positioned)
    return arena


# ── Smoke test / example ─────────────────────────────────────────────


def _example_roster() -> ArenaSpec:
    """A worked example: 4 boss-tier chrs at the m48_90 slot.

    NPCParamID and ThinkParamID values are illustrative. For real use,
    pull canonical values from oops_v3 / NpcParam mappings — or use
    vanilla NR's per-chr NpcParams which are baked into the engine.
    """
    # m48_90's boss-tier slot uses entity IDs starting at 48900800
    chrs = [
        ChrSpec(c_prefix='c4770', npc_param=904770000, think_param=304770010),  # Valiant Gargoyle
        ChrSpec(c_prefix='c4580', npc_param=904580600, think_param=304580010),  # Large Wormface
        ChrSpec(c_prefix='c4510', npc_param=904510000, think_param=304510010),  # Ancient Dragon
        ChrSpec(c_prefix='c4690', npc_param=904690000, think_param=304690010),  # Dragonkin Soldier
    ]
    return build_linear_roster('m48_90_00_00', chrs,
                                x_spacing=5.0, base_eid=48900800)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out-dir', default='dev/authored_msbs',
                     help='Where to write the <map_name>-msb-dcx directory')
    ap.add_argument('--example', action='store_true',
                     help='Emit the example roster (4 chrs at m48_90 slot)')
    args = ap.parse_args()

    if args.example:
        arena = _example_roster()
        target = author_msb(arena, args.out_dir)
        print(f'Wrote example roster to {target}/')
        print(f'  Parts: {len(arena.chrs)} chrs')
        print(f'  Models: {len(arena.unique_models)} unique')
        print()
        print(f'Next steps:')
        print(f'  1. Run Witchy locally to repack:')
        print(f'     WitchyBND.exe -r "{target}"')
        print(f'  2. This produces {arena.msb_filename} in the same parent dir')
        print(f'  3. Drop into me3 profile at .../map/mapstudio/{arena.msb_filename}')
        print(f'  4. Pair with an MMV-style EMEVD (use dev/emit_mmv_style_arena_emevd.py)')
        print(f'  5. Launch game, route an expedition through the slot')
    else:
        print("Use --example to generate the demo roster, or import this")
        print("module and call author_msb(arena_spec, out_dir) with your own roster.")


if __name__ == '__main__':
    main()
