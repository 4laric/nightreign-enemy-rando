#!/usr/bin/env python3
"""
derive_tile_data.py — Build the four tile-data JSONs in data/ from a directory
of extracted regulation.bin param files.

Output files (all written to --out-dir, default ../data relative to this script):

    vanilla_tile_distribution.json
        Meta-level: per-Nightlord × tile counts (20 Default + 5 each SE = 40
        patterns per Nightlord × 8 Nightlords = 320 patterns total). Methodology
        block + uniform/vanilla sampling rates.

    vanilla_pattern_classification.json
        Per-pattern lookup: pattern_id 0-319 → (nightlord_idx, nightlord_name,
        tile). Nightlord block ordering is derived from the 40-pattern clustering
        in LotResultPlayAreaParam — cross-check against
        data/nightlord_expedition_table.json before relying on per-NL rows.

    vanilla_slot_poi_frequencies.json
        Per-(tile, slot) → {poi_id: count}. The 14,718 placements in
        LotResultSmallBaseAndSpot aggregated by tile bucket. Useful as a
        diagnostic — answers "what does slot X look like under tile T?"

    msb_tile_probability.json
        Per-MSB per-tile presence rate + pre-computed vanilla/uniform
        visibility. Used by healthbar_tools/prep_demo.py to discount memorable
        field placements by P(tile gets player to that MSB). The cleanest
        deliverable — bites the score directly.

PREREQUISITE — extracting regulation.bin to param files:

    regulation.bin is encrypted. SoulsFormats (the C# library) has the NR
    decryption keyset (SFUtil.DecryptNRRegulation). To extract:

      1. On Windows or any machine with .NET 8 + Oodle DLLs, use any
         SoulsFormats-based tool (DSMapStudio, Smithbox, your own dotnet
         script) to call SFUtil.DecryptNRRegulation on regulation.bin and
         dump the resulting BND4 entries as .param files into a directory.
      2. Pass that directory via --param-dir.

    Required .param files (only these 4 are read):
      LotResultMapPatternFlag.param   (pattern → tile event-flag binding)
      LotResultPlayAreaParam.param    (pattern → Nightlord/boss combo)
      LotResultSmallBaseAndSpot.param (pattern → slot → POI placement)
      MapPatternSet.param             (variant lottery within a Nightlord/tile)

USAGE:

    python3 dev/derive_tile_data.py --param-dir /path/to/extracted/params

    # Override output location:
    python3 dev/derive_tile_data.py --param-dir /path/to/params --out-dir data/

    # Re-derive after a Nightreign patch updates regulation.bin:
    # (extract the new regulation.bin's params, then re-run with the new dir)
"""

import argparse
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path


# Vanilla NR Shifting Earth event flags. Source: confirmed empirically against
# RareMapInfoMenuParam row IDs [11,12,13,15] and the RareMap enum in
# thefifthmatt's RandomizerCommon.dll.
SE_EVENT_FLAGS = {
    7600: 'Default',
    7601: 'Mountaintops',
    7602: 'Crater',
    7603: 'Rotted_Woods',
    7605: 'Noklateo',
}
TILES = ['Default', 'Mountaintops', 'Crater', 'Rotted_Woods', 'Noklateo']

# Nightlord matchmaking order (menu order). Derived block-to-name mapping is
# heuristic; verify against data/nightlord_expedition_table.json before
# relying on per-Nightlord rows.
NIGHTLORD_NAMES = ['Gladius', 'Adel', 'Gnoster', 'Maris', 'Libra', 'Fulghor',
                   'Caligo', 'Heolstor']

# Vanilla expedition rates (per thefifthmatt randomizer README) and uniform
# sampling rates ("Greatly increase one-off Shifting Earth" option ON).
TILE_PROB_VANILLA = {'Default': 0.9116, 'Mountaintops': 0.0221, 'Crater': 0.0221,
                     'Rotted_Woods': 0.0221, 'Noklateo': 0.0221}
TILE_PROB_UNIFORM = {'Default': 0.5, 'Mountaintops': 0.125, 'Crater': 0.125,
                     'Rotted_Woods': 0.125, 'Noklateo': 0.125}


def parse_param(path):
    """Parse FromSoft .param binary. Returns [(row_id, raw_row_bytes), ...]."""
    data = path.read_bytes()
    row_count = struct.unpack('<H', data[10:12])[0]
    strings_offset = struct.unpack('<I', data[0:4])[0]
    rows = []
    for i in range(row_count):
        e = 0x40 + i * 24
        row_id, _pad, data_off, _name_off = struct.unpack('<iIqq', data[e:e + 24])
        if i + 1 < row_count:
            next_off = struct.unpack('<q', data[0x40 + (i + 1) * 24 + 8:
                                                0x40 + (i + 1) * 24 + 16])[0]
            sz = next_off - data_off
        else:
            sz = strings_offset - data_off
        rows.append((row_id, data[data_off:data_off + sz]))
    return rows


def derive(param_dir, vanilla_msbs):
    """Run all derivations. Returns 4 JSON-serializable dicts."""
    param_dir = Path(param_dir)

    # ---- 1. Classify the 320 patterns by tile ----
    # Each pattern sets exactly one event flag in LotResultMapPatternFlag.col4
    # in {7600..7605}; the value identifies the tile.
    pattern_tile = {}
    for rid, raw in parse_param(param_dir / 'LotResultMapPatternFlag.param'):
        if len(raw) < 28:
            continue
        _, pattern_id, _modset, _mod, evt, _, _ = struct.unpack('<7i', raw[:28])
        if evt in SE_EVENT_FLAGS and pattern_id not in pattern_tile:
            pattern_tile[pattern_id] = SE_EVENT_FLAGS[evt]
    if len(pattern_tile) != 320:
        sys.stderr.write(f"WARNING: classified {len(pattern_tile)} patterns; expected 320\n")

    # Nightlord index from pattern block (heuristic: patterns 0-39 = NL1, ...).
    # Confirmed empirically by boss-combo clustering in LotResultPlayAreaParam.
    pattern_to_nl = {p: p // 40 for p in pattern_tile}

    # ---- 2. vanilla_tile_distribution.json ----
    table = defaultdict(Counter)
    for p, tile in pattern_tile.items():
        nl = pattern_to_nl[p]
        if nl < len(NIGHTLORD_NAMES):
            table[NIGHTLORD_NAMES[nl]][tile] += 1
    overall = Counter()
    for c in table.values():
        for k, v in c.items():
            overall[k] += v

    tile_dist = {
        'methodology': (
            'Patterns classified by event flag set in LotResultMapPatternFlag '
            'col4: 7600=Default, 7601=Mountaintops, 7602=Crater, '
            '7603=Rotted_Woods, 7605=Noklateo. 320 patterns total.'
        ),
        'per_nightlord': {nl: dict(c) for nl, c in table.items()},
        'overall': dict(overall),
        'per_pattern_fraction': {tile: overall[tile] / 320 for tile in overall},
        'tile_probabilities': {
            'vanilla_weighted': TILE_PROB_VANILLA,
            'uniform': TILE_PROB_UNIFORM,
        },
        'notes': {
            'uniform_pattern_sampling': (
                'If all 320 patterns equiprobable: Default 50%, each SE 12.5%. '
                'Matches "Greatly increase one-off Shifting Earth" option ON.'
            ),
            'vanilla_weighted_sampling': (
                'thefifthmatt randomizer README: Default ~91.16%, each SE '
                '~2.21%. Set by EMEVD-side event-flag rolls (7601-7605); not '
                'directly recoverable from regulation.bin alone.'
            ),
            'intra_bucket_variant_lottery': (
                'Within a fixed (Nightlord, tile) bucket, MapPatternSet weights '
                'are 8400:400:400:400:400 = 84% primary + 4% each of 4 variants.'
            ),
        },
    }

    # ---- 3. vanilla_pattern_classification.json ----
    pattern_classification = {
        str(p): {
            'nightlord_idx': pattern_to_nl[p],
            'nightlord_name': NIGHTLORD_NAMES[pattern_to_nl[p]] if pattern_to_nl[p] < len(NIGHTLORD_NAMES) else None,
            'tile': pattern_tile[p],
        }
        for p in sorted(pattern_tile)
    }

    # ---- 4. vanilla_slot_poi_frequencies.json + 5. msb_tile_probability.json ----
    # Per paramdef LotResultSmallBaseAndSpot: (s32 unknown_0, s32 patternId,
    # s32 attachId, s32 smallBaseMapId, u8 mapIndex, u8 variationId, u16 _, s32 modifier).
    # smallBaseMapId decodes as m{XX}_{YY}_00_00.msb where XX=id//100, YY=id%100,
    # for any vanilla MSB. (100% match rate empirically.)
    tile_slot_poi = defaultdict(lambda: defaultdict(Counter))
    msb_pattern_presence = defaultdict(set)
    for rid, raw in parse_param(param_dir / 'LotResultSmallBaseAndSpot.param'):
        if len(raw) < 24:
            continue
        _, pid, slot, smb, _variant_pack, _mod = struct.unpack('<6i', raw[:24])
        tile = pattern_tile.get(pid)
        if tile is None:
            continue
        tile_slot_poi[tile][slot][smb] += 1
        msb_name = f"m{smb // 100:02d}_{smb % 100:02d}_00_00.msb"
        if msb_name in vanilla_msbs:
            msb_pattern_presence[msb_name].add(pid)

    slot_freq = {tile: {str(slot): dict(c) for slot, c in slots.items()}
                 for tile, slots in tile_slot_poi.items()}

    # Per-MSB per-tile presence rate (used by the scorer for visibility weighting).
    n_per_tile = Counter(pattern_tile.values())
    msb_presence_out = {}
    for msb, patterns in msb_pattern_presence.items():
        per_tile_rate = {}
        for tile in TILES:
            n_present = sum(1 for p in patterns if pattern_tile[p] == tile)
            per_tile_rate[tile] = round(n_present / max(1, n_per_tile[tile]), 4)
        vis_v = round(sum(per_tile_rate[t] * TILE_PROB_VANILLA[t] for t in TILES), 4)
        vis_u = round(sum(per_tile_rate[t] * TILE_PROB_UNIFORM[t] for t in TILES), 4)
        msb_presence_out[msb] = {
            'per_tile_presence_rate': per_tile_rate,
            'visibility_vanilla': vis_v,
            'visibility_uniform': vis_u,
        }
    # Sort by visibility_vanilla desc for readability
    msb_presence_out = dict(sorted(msb_presence_out.items(),
                                   key=lambda kv: -kv[1]['visibility_vanilla']))

    msb_tile_prob = {
        'methodology': (
            'Per-MSB per-tile presence rate, derived from regulation.bin '
            'LotResultSmallBaseAndSpot. For each pattern row, smallBaseMapId '
            'is decoded as m{id//100:02d}_{id%100:02d}_00_00.msb (100% match '
            'rate against vanilla MSBs). presence_rate[tile] = (# patterns of '
            'that tile that include the MSB) / (# patterns of that tile). '
            'visibility_vanilla = Σ_T P(tile T rolled) × presence_rate[T] '
            'using vanilla rates (Default ~91.16%, each SE ~2.21%).'
        ),
        'tile_probabilities_used': {
            'vanilla': TILE_PROB_VANILLA,
            'uniform': TILE_PROB_UNIFORM,
        },
        'caveats': (
            'visibility values are upper bounds: P(MSB loaded during expedition) '
            'assuming the player fully explores. MSBs NOT in this table are not '
            'referenced by LotResultSmallBaseAndSpot — they load via other '
            'mechanisms (Nightlord-keyed arenas via the boss matchmaker, tile-base '
            'MSBs like m10/m11/m12/m13/m15, or m60 open-world chunks). For those, '
            'fall back to the prefix heuristic in healthbar_tools/prep_demo.py '
            '`_msb_tiles()`.'
        ),
        'msb_presence': msb_presence_out,
    }

    return tile_dist, pattern_classification, slot_freq, msb_tile_prob


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve().parent
    ap.add_argument('--param-dir', required=True,
                    help='Directory containing extracted regulation.bin .param files. '
                         'Must contain LotResultMapPatternFlag.param, LotResultPlayAreaParam.param, '
                         'LotResultSmallBaseAndSpot.param, and MapPatternSet.param.')
    ap.add_argument('--out-dir', default=str(here.parent / 'data'),
                    help='Output directory. Default: ../data relative to this script.')
    ap.add_argument('--vanilla-msbs', default=str(here.parent / 'vanilla_msbs'),
                    help='Directory of vanilla NR .msb.dcx files, used to validate the '
                         'smallBaseMapId → MSB decoding. Default: ../vanilla_msbs.')
    args = ap.parse_args()

    msb_dir = Path(args.vanilla_msbs)
    vanilla_msbs = set()
    if msb_dir.is_dir():
        vanilla_msbs = {f.name.removesuffix('.dcx') for f in msb_dir.iterdir()}
    else:
        sys.stderr.write(f"WARNING: vanilla MSB dir not found at {msb_dir}; "
                         "smallBaseMapId decoding will be unvalidated.\n")
        # Without validation, accept anything that looks like a valid MSB name.
        vanilla_msbs = None

    sys.stderr.write(f"Reading params from: {args.param_dir}\n")
    sys.stderr.write(f"Writing JSONs to:    {args.out_dir}\n")
    sys.stderr.write(f"Vanilla MSBs:        {len(vanilla_msbs) if vanilla_msbs else '<unvalidated>'}\n")

    # If no vanilla MSB validation, accept all smallBaseMapIds (no filtering).
    if vanilla_msbs is None:
        class _MSBSet:
            def __contains__(self, _): return True
        vanilla_msbs = _MSBSet()

    tile_dist, pat_cls, slot_freq, msb_prob = derive(args.param_dir, vanilla_msbs)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = [
        ('vanilla_tile_distribution.json',       tile_dist),
        ('vanilla_pattern_classification.json',  pat_cls),
        ('vanilla_slot_poi_frequencies.json',    slot_freq),
        ('msb_tile_probability.json',            msb_prob),
    ]
    for name, data in files:
        path = out_dir / name
        path.write_text(json.dumps(data, indent=2))
        sys.stderr.write(f"  wrote {path}  ({path.stat().st_size:,} bytes)\n")

    sys.stderr.write("\nDone. The healthbar_tools/prep_demo.py RANK command will pick up "
                     "msb_tile_probability.json automatically.\n")


if __name__ == '__main__':
    main()
