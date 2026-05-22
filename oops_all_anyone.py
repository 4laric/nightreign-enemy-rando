#!/usr/bin/env python3
"""
Oops! All [X] — generalized enemy substitution tool for Nightreign.

Converts every spawnable enemy in every map to a target enemy type.
Choose any of 191 vanilla NR enemy types as your target.

USAGE:
    python oops_all_anyone.py list                              # list all targets
    python oops_all_anyone.py search <text>                     # search target names
    python oops_all_anyone.py convert <target> <input> <output> # batch-convert MSBs
    python oops_all_anyone.py cluster-report <input> [threshold] [--json out.json]
    python oops_all_anyone.py shuffle <input> <output> [--seed N] [--threshold T]

EXAMPLES:
    python oops_all_anyone.py list
    python oops_all_anyone.py search wolf
    python oops_all_anyone.py convert c4070 ./vanilla_msbs ./modded_msbs   # Oops! All Wolf
    python oops_all_anyone.py convert c3100 ./vanilla_msbs ./modded_msbs   # Oops! All BBH
    python oops_all_anyone.py convert c4500 ./vanilla_msbs ./modded_msbs   # Oops! All Dragon
    python oops_all_anyone.py cluster-report ./vanilla_msbs              # find multi-part spawn slots
    python oops_all_anyone.py cluster-report ./vanilla_msbs 2.5 --json clusters.json
    python oops_all_anyone.py shuffle ./vanilla_msbs ./shuffled_msbs --seed 42
    # ↑ v1: Cluster-aware randomizer with map-local pool. Maximum chaos
    #   ('Oops! All Cursed' — flying demi-humans, T-posers, civil wars).

    python oops_all_anyone.py shuffle ./vanilla_msbs ./v2_shuffled --seed 42 \
        --tags ./nr_enemy_tags.json --mode loose
    # ↑ v2: Compatibility-aware shuffle using auto-tagged NpcParam data.
    #   Tier 1 (anim_bank match) ∪ Tier 2 (size+locomotion+team match).
    #   Use --mode strict for Tier 1 only (most conservative, least variety).

Target accepts c-prefix (c4070) or name fragment (Wolf, Dragon, BBH).

Pipeline:
    1. Decompress vanilla map\\mapstudio\\*.msb.dcx with Yabber-DCX or Witchy
    2. Run this tool on the resulting folder of .msb (+ sidecar xml) files
    3. Recompress modded .msb files back to .msb.dcx using same tool
    4. Drop into me3 BBH profile at map\\mapstudio\\

The tool automatically copies sidecar XML manifests (.msb-yabber-dcx.xml or
.msb-wdcx.xml) so the output folder is ready for direct recompress.
"""
import json
import os
import re
import shutil
import struct
import sys


# v0.23.71: data-file resolver — checks data/<name> first, falls back
# to <name> at project root. Mirrors oops_v3._data_path so the layouts
# stay synced. Inlined here (not imported) so this file stays
# usable as a standalone CLI tool without dragging in oops_v3 unless
# the caller actually needs the engine.
def _data_path(filename):
    here = os.path.dirname(os.path.abspath(__file__))
    new_loc = os.path.join(here, 'data', filename)
    if os.path.exists(new_loc):
        return new_loc
    return os.path.join(here, filename)


ROSTER_PATH = _data_path('nr_enemy_roster.json')

# Empirical struct offsets (verified on m60_42_36_00 Enemy Parts):
ENEMY_PART_STRUCT_SIZE        = 0x3e0
ENEMY_PART_NAME_OFFSET        = 0x60
ENEMY_PART_ENTITY_ID_OFFSET   = 0x200
ENEMY_PART_THINK_PARAM_OFFSET = 0x258
ENEMY_PART_NPC_PARAM_OFFSET   = 0x25C
ENEMY_PART_POS_OFFSET         = 0x3a0   # X, Y, Z floats — discovered via hex dump

EXCLUDE_SOURCE_PREFIXES = {
    'c0000', 'c0100', 'c0110', 'c0120',  # player nightfarer templates
    'c1000',                              # standin / placeholder
    'c2070',                              # bonfire dummy
}

PART_STRUCT_NAME_PATTERN = re.compile(rb'c\x00\d\x00\d\x00\d\x00\d\x00_\x00\d\x00\d\x00\d\x00\d\x00\x00\x00')
ANY_PREFIX_PATTERN       = re.compile(rb'c\x00\d\x00\d\x00\d\x00\d\x00')

# Sidecar suffixes that pair with a .msb file (Yabber: -yabber-dcx.xml, Witchy: -wdcx.xml)
SIDECAR_SUFFIXES = ['-yabber-dcx.xml', '-wdcx.xml']


def load_roster():
    if not os.path.exists(ROSTER_PATH):
        print(f"ERROR: roster file not found at {ROSTER_PATH}"); sys.exit(1)
    with open(ROSTER_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def cmd_list():
    roster = load_roster()
    targets = sorted(roster['canonical_targets'], key=lambda t: t['default_name'])
    print(f"All {len(targets)} vanilla NR enemy types:\n")
    for t in targets:
        print(f"  {t['c_prefix']:<7} ({t['total_parts']:>4} parts)  {t['default_name']}")


def cmd_search(query):
    roster = load_roster()
    targets = roster['canonical_targets']
    q = query.lower()
    matches = sorted(
        [t for t in targets if q in t['default_name'].lower() or q in t['c_prefix'].lower()],
        key=lambda t: t['default_name'])
    if not matches:
        print(f"No targets matching '{query}'."); return
    for t in matches:
        print(f"  {t['c_prefix']:<7} ({t['total_parts']:>4} parts)  {t['default_name']}")


def resolve_target(query, roster):
    targets = roster['canonical_targets']
    if re.match(r'^c\d{4}$', query):
        for t in targets:
            if t['c_prefix'] == query: return t
        print(f"ERROR: c-prefix '{query}' not found."); sys.exit(1)
    q = query.lower()
    matches = [t for t in targets if q in t['default_name'].lower()]
    if not matches: print(f"ERROR: No target matching '{query}'."); sys.exit(1)
    if len(matches) > 1:
        print(f"ERROR: Multiple matches. Be specific:")
        for t in matches[:10]: print(f"  {t['c_prefix']}: {t['default_name']}")
        sys.exit(1)
    return matches[0]


def find_all_prefixes(data: bytes) -> set:
    seen = set()
    for m in ANY_PREFIX_PATTERN.finditer(data):
        prefix = m.group(0).decode('utf-16-le', errors='ignore')
        if re.match(r'^c\d{4}$', prefix):
            seen.add(prefix)
    return seen


def convert_msb(input_path, output_path, target):
    target_prefix = target['c_prefix']
    target_npc = target['default_npc_param_id']
    target_think = target['default_think_param_id']
    
    with open(input_path, 'rb') as f:
        data = bytearray(f.read())
    original_size = len(data)
    
    all_prefixes = find_all_prefixes(bytes(data))
    prefixes_to_substitute = {
        p for p in all_prefixes
        if p != target_prefix and p not in EXCLUDE_SOURCE_PREFIXES
    }
    
    parts_converted = 0
    npc_writes = 0
    think_writes = 0
    
    for m in PART_STRUCT_NAME_PATTERN.finditer(bytes(data)):
        name_pos = m.start()
        prefix = bytes(data[name_pos:name_pos+10]).decode('utf-16-le', errors='ignore')
        if prefix == target_prefix or prefix in EXCLUDE_SOURCE_PREFIXES: continue
        struct_start = name_pos - ENEMY_PART_NAME_OFFSET
        if struct_start < 0: continue
        
        parts_converted += 1
        
        npc_off = struct_start + ENEMY_PART_NPC_PARAM_OFFSET
        old_npc = struct.unpack_from('<I', data, npc_off)[0]
        if old_npc not in (0, 0xFFFFFFFF):
            struct.pack_into('<I', data, npc_off, target_npc)
            npc_writes += 1
        
        think_off = struct_start + ENEMY_PART_THINK_PARAM_OFFSET
        old_think = struct.unpack_from('<I', data, think_off)[0]
        if old_think not in (0, 0xFFFFFFFF):
            struct.pack_into('<I', data, think_off, target_think)
            think_writes += 1
    
    string_subs = 0
    for prefix in prefixes_to_substitute:
        old_bytes = prefix.encode('utf-16-le')
        new_bytes = target_prefix.encode('utf-16-le')
        n = bytes(data).count(old_bytes)
        if n > 0:
            string_subs += n
            data = bytearray(bytes(data).replace(old_bytes, new_bytes))
    
    if parts_converted == 0 and string_subs == 0:
        return None
    
    assert len(data) == original_size, f"Size changed: {original_size} → {len(data)}"
    with open(output_path, 'wb') as f:
        f.write(data)
    
    return {
        'parts_converted': parts_converted,
        'string_subs': string_subs,
    }


def copy_sidecars(input_dir, output_dir, msb_basename):
    """Copy any sidecar manifest files for this msb so the output is ready for re-pack."""
    copied = 0
    for suffix in SIDECAR_SUFFIXES:
        sidecar_name = msb_basename + suffix
        in_path = os.path.join(input_dir, sidecar_name)
        if os.path.exists(in_path):
            shutil.copy2(in_path, os.path.join(output_dir, sidecar_name))
            copied += 1
    return copied


def cmd_convert(target_query, input_dir, output_dir):
    roster = load_roster()
    target = resolve_target(target_query, roster)
    
    print(f"Target: {target['c_prefix']} — {target['default_name']}")
    print(f"  NpcParam:   {target['default_npc_param_id']}")
    print(f"  ThinkParam: {target['default_think_param_id']}\n")
    
    os.makedirs(output_dir, exist_ok=True)
    msb_files = sorted(f for f in os.listdir(input_dir) if f.endswith('.msb'))
    print(f"Processing {len(msb_files)} MSB files...\n")
    
    converted_maps = 0
    skipped_maps = 0
    total_parts = 0
    total_strings = 0
    sidecars_copied = 0
    
    for fname in msb_files:
        in_path = os.path.join(input_dir, fname)
        out_path = os.path.join(output_dir, fname)
        stats = convert_msb(in_path, out_path, target)
        if stats is None:
            skipped_maps += 1
            continue
        converted_maps += 1
        total_parts += stats['parts_converted']
        total_strings += stats['string_subs']
        sidecars_copied += copy_sidecars(input_dir, output_dir, fname)
    
    print(f"=== Summary ===")
    print(f"  Maps converted:              {converted_maps}")
    print(f"  Maps unchanged:              {skipped_maps}")
    print(f"  Enemy Parts (struct fields): {total_parts}")
    print(f"  String substitutions:        {total_strings}")
    print(f"  Sidecar manifests copied:    {sidecars_copied}")
    print(f"\n  Every spawn → {target['default_name']}")
    print(f"\nOutput .msb files (with sidecars) in: {output_dir}")
    print(f"Now: Yabber/Witchy on the output folder to repack to .msb.dcx,")
    print(f"     then drop the .msb.dcx files into BBH\\map\\mapstudio\\")


def extract_enemy_parts(data: bytes) -> list:
    """
    Extract all valid Enemy Part structs from MSB bytes.

    Filters: struct must fit within file bounds, name prefix must not be in
    EXCLUDE_SOURCE_PREFIXES, and the NPCParam slot must hold a plausible value
    (non-zero and not 0xFFFFFFFF) to avoid matching name strings that occur
    outside Enemy Part structs (e.g. in the Models section).
    """
    parts = []
    seen = set()
    for m in PART_STRUCT_NAME_PATTERN.finditer(data):
        name_pos = m.start()
        struct_start = name_pos - ENEMY_PART_NAME_OFFSET
        if struct_start < 0 or struct_start in seen: continue
        if struct_start + ENEMY_PART_STRUCT_SIZE > len(data): continue
        seen.add(struct_start)

        prefix = bytes(data[name_pos:name_pos+10]).decode('utf-16-le', errors='ignore')
        if prefix in EXCLUDE_SOURCE_PREFIXES: continue
        full_name = bytes(data[name_pos:name_pos+22]).decode('utf-16-le', errors='ignore').rstrip('\x00')

        npc = struct.unpack_from('<I', data, struct_start + ENEMY_PART_NPC_PARAM_OFFSET)[0]
        # Filter out matches that aren't actually inside Enemy Part structs
        if npc in (0, 0xFFFFFFFF): continue

        x, y, z = struct.unpack_from('<fff', data, struct_start + ENEMY_PART_POS_OFFSET)
        think = struct.unpack_from('<I', data, struct_start + ENEMY_PART_THINK_PARAM_OFFSET)[0]
        ent = struct.unpack_from('<I', data, struct_start + ENEMY_PART_ENTITY_ID_OFFSET)[0]
        parts.append({
            'name': full_name, 'prefix': prefix,
            'pos': (x, y, z),
            'npc': npc, 'think': think, 'ent': ent,
            'off': struct_start,
        })
    return parts


def find_position_clusters(parts: list, threshold: float) -> list:
    """Group Enemy Parts by spatial proximity using union-find. Returns lists of indices."""
    n = len(parts)
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb

    t2 = threshold * threshold
    for i in range(n):
        xi, yi, zi = parts[i]['pos']
        for j in range(i+1, n):
            xj, yj, zj = parts[j]['pos']
            d2 = (xi-xj)**2 + (yi-yj)**2 + (zi-zj)**2
            if d2 < t2: union(i, j)

    groups = {}
    for i in range(n): groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def cluster_spread(parts: list, indices: list) -> float:
    """Maximum pairwise distance between any two parts in the cluster."""
    if len(indices) < 2: return 0.0
    max_d2 = 0.0
    for i in range(len(indices)):
        for j in range(i+1, len(indices)):
            a = parts[indices[i]]['pos']; b = parts[indices[j]]['pos']
            d2 = (a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2
            if d2 > max_d2: max_d2 = d2
    return max_d2 ** 0.5


def classify_cluster(size: int, spread: float) -> str:
    """
    Classify a spatial cluster of Enemy Parts by its size + spread signature.

    Categories (in order of decreasing structural significance):

    multi_part    : size 2 or 3 with spread = 0.0
                    Parts at IDENTICAL MSB coordinates. Engine-level co-located
                    entities: rider+mount (Knight+Horse), duo bosses (Libra+Libra,
                    Adel+Gnoster), pre-staged paired spawns (Maris' Tendril).
                    THIS is the bug surface for Oops!-All conversion: each Part is
                    independently rewritten, producing N stacked targets per slot.

    template_pool : size >= 4 with spread = 0.0
                    Stacks of 4+ Parts at identical coords, typically with sequential
                    EntityIDs. Spawn-system templates that the runtime instantiates
                    elsewhere. Not actually placed enemies.

    tight_camp    : anything with spread > 0.0
                    Enemies placed near each other at DISTINCT coordinates. Not a
                    structural pairing — just spatial proximity. Convert handles
                    these correctly (each part converts independently at its own
                    coords). Same-prefix pairs with spread ~1.6-1.8 are common here:
                    they're enemies camping together, NOT multi-part entities.
    """
    if spread > 0.0:
        return 'tight_camp'
    if size >= 4:
        return 'template_pool'
    return 'multi_part'


def cmd_cluster_report(input_dir, threshold=2.0, json_out=None):
    """Scan MSB files for spatial clusters of Enemy Parts (multi-part spawn slots)."""
    from collections import Counter

    msb_files = sorted(f for f in os.listdir(input_dir) if f.endswith('.msb'))
    if not msb_files:
        print(f"No .msb files found in {input_dir}"); sys.exit(1)

    map_stats = []
    all_clusters_data = []
    prefix_combo_counts = {'multi_part': Counter(), 'tight_camp': Counter(), 'template_pool': Counter()}
    # Track map distribution per combo (only for multi_part — that's where it matters)
    multi_part_combo_maps = {}  # combo -> Counter(map -> count)
    cluster_size_counts = Counter()
    category_counts = Counter()
    total_parts = 0

    print(f"Scanning {len(msb_files)} MSBs with cluster threshold = {threshold} units...")

    for fname in msb_files:
        with open(os.path.join(input_dir, fname), 'rb') as f:
            data = f.read()
        parts = extract_enemy_parts(data)
        # Drop literal-origin parts (uninstantiated templates with no real position)
        placed = [p for p in parts if p['pos'] != (0.0, 0.0, 0.0)]
        clusters = find_position_clusters(placed, threshold)

        total_parts += len(placed)
        per_map_categories = Counter()
        for cl in clusters:
            spread = cluster_spread(placed, cl)
            cat = classify_cluster(len(cl), spread)
            per_map_categories[cat] += 1
            category_counts[cat] += 1
            cluster_size_counts[len(cl)] += 1

            cps = [placed[i] for i in cl]
            combo = ' + '.join(sorted(p['prefix'] for p in cps))
            prefix_combo_counts[cat][combo] += 1
            if cat == 'multi_part':
                multi_part_combo_maps.setdefault(combo, Counter())[fname] += 1

            all_clusters_data.append({
                'map': fname, 'category': cat, 'spread': round(spread, 3),
                'parts': [{'name': p['name'], 'prefix': p['prefix'], 'pos': p['pos'],
                           'ent': p['ent'], 'npc': p['npc']} for p in cps],
            })

        map_stats.append({
            'map': fname, 'placed_parts': len(placed),
            'origin_parts': len(parts) - len(placed),
            'cluster_count': len(clusters),
            'parts_in_clusters': sum(len(c) for c in clusters),
            'multi_part': per_map_categories['multi_part'],
            'tight_camp': per_map_categories['tight_camp'],
            'template_pool': per_map_categories['template_pool'],
        })

    print()
    print("=" * 72)
    print(f" Cluster Report — {len(msb_files)} maps, threshold {threshold} units")
    print("=" * 72)

    total_in = sum(ms['parts_in_clusters'] for ms in map_stats)
    pct = (100.0 * total_in / total_parts) if total_parts else 0.0

    print(f"\nTotals:")
    print(f"  Maps scanned:                {len(msb_files)}")
    print(f"  Maps with clusters:          {sum(1 for ms in map_stats if ms['cluster_count'] > 0)}")
    print(f"  Placed Enemy Parts:          {total_parts}")
    print(f"  Total clusters:              {sum(category_counts.values())}")
    print(f"  Parts inside clusters:       {total_in} ({pct:.1f}% of placed)")

    print(f"\nClusters by category:")
    print(f"  multi_part   (size 2-3, spread = 0.0):    {category_counts['multi_part']:>4}")
    print(f"      ↑ true multi-Part entities at IDENTICAL coords:")
    print(f"        rider+mount, duo bosses, paired pre-stages.")
    print(f"        These are what the Oops!-All convert silently doubles.")
    print(f"  tight_camp   (spread > 0.0):              {category_counts['tight_camp']:>4}")
    print(f"      ↑ enemies near each other at DISTINCT coords — not a tool problem.")
    print(f"  template_pool (size >= 4, spread = 0.0):  {category_counts['template_pool']:>4}")
    print(f"      ↑ stacks of identical-coord enemies; spawn-system templates.")

    print(f"\nCluster size distribution:")
    for size in sorted(cluster_size_counts):
        print(f"  size {size:>2}: {cluster_size_counts[size]:>4} clusters")

    print(f"\nTop 15 maps by multi_part cluster count:")
    for ms in sorted(map_stats, key=lambda m: -m['multi_part'])[:15]:
        if ms['multi_part'] == 0: break
        print(f"  {ms['map']:<28s} parts={ms['placed_parts']:>4}  "
              f"multi_part={ms['multi_part']:>3}  "
              f"camp={ms['tight_camp']:>3}  pool={ms['template_pool']:>3}")

    print(f"\nTop 25 c-prefix combinations in MULTI_PART clusters")
    print(f"(this is the rider+mount / duo / paired-pre-stage signature for stratification):")
    print(f"  {'count':>5}  {'maps':>4}  combo  →  top map (occurrences)")
    for combo, count in prefix_combo_counts['multi_part'].most_common(25):
        maps = multi_part_combo_maps.get(combo, Counter())
        n_maps = len(maps)
        if maps:
            top_map, top_count = maps.most_common(1)[0]
            scope = f"{top_map} ({top_count}x)"
            if n_maps == 1 and top_count == count:
                scope += "  ← single-map pattern"
        else:
            scope = ""
        print(f"  {count:>5}  {n_maps:>4}  {combo}  →  {scope}")

    if prefix_combo_counts['template_pool']:
        print(f"\nTop 10 c-prefix combinations in TEMPLATE_POOL clusters (FYI, not actionable):")
        for combo, count in prefix_combo_counts['template_pool'].most_common(10):
            short = combo if len(combo) < 90 else combo[:87] + '...'
            print(f"  {count:>4}x  {short}")

    if json_out:
        with open(json_out, 'w', encoding='utf-8') as f:
            json.dump({
                'threshold': threshold,
                'totals': {
                    'maps_scanned': len(msb_files),
                    'placed_parts': total_parts,
                    'total_clusters': sum(category_counts.values()),
                    'parts_in_clusters': total_in,
                    'category_counts': dict(category_counts),
                },
                'cluster_size_distribution': dict(cluster_size_counts),
                'prefix_combo_counts': {k: dict(v) for k, v in prefix_combo_counts.items()},
                'multi_part_combo_maps': {k: dict(v) for k, v in multi_part_combo_maps.items()},
                'per_map': map_stats,
                'clusters': all_clusters_data,
            }, f, indent=2)
        print(f"\nDetailed JSON written to: {json_out}")



def load_tags(tags_path: str) -> dict:
    """Load the auto-tag JSON produced by mining MMV's NpcParam dump."""
    with open(tags_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_compat_lookups(tags: dict):
    """
    Build the two lookups used for tag-aware compatibility:
      bank_to_prefixes : anim_bank ID -> set of c-prefixes that share it
                         (shared bank = guaranteed-safe animation swap)
      loose_to_prefixes : (size_class, locomotion, team) -> set of c-prefixes
                          (loose match = mostly-safe; weapon shape may still vary)
    """
    from collections import defaultdict
    bank_to_prefixes = defaultdict(set)
    loose_to_prefixes = defaultdict(set)
    for prefix, t in tags.items():
        if 'anim_bank' not in t: continue
        bank_to_prefixes[t['anim_bank']].add(prefix)
        loose_to_prefixes[(t['size_class'], t['locomotion'], t['team'])].add(prefix)
    return dict(bank_to_prefixes), dict(loose_to_prefixes)


def compatible_pool(recipient_prefix: str, map_local_prefixes: set,
                    tags: dict, bank_to_prefixes: dict, loose_to_prefixes: dict,
                    mode: str = 'loose') -> list:
    """
    Given a recipient slot's original c-prefix, return the candidate target pool
    restricted to c-prefixes that (a) are in this map's pool already, and (b)
    are tag-compatible with the recipient.

    mode='strict' : only same-anim_bank c-prefixes (Tier 1) — no animation jank
    mode='loose'  : Tier 1 ∪ Tier 2 (same size+locomotion+team) — wider pool,
                    accepts foot-soldier-with-miner-moveset class of jank but
                    avoids T-pose / clipping / civil war
    """
    rt = tags.get(recipient_prefix)
    if not rt or 'anim_bank' not in rt:
        return [recipient_prefix]  # untaggable — leave alone

    pool = set(bank_to_prefixes.get(rt['anim_bank'], ()))
    if mode == 'loose':
        pool |= loose_to_prefixes.get(
            (rt['size_class'], rt['locomotion'], rt['team']), set())

    pool &= map_local_prefixes
    pool.discard(recipient_prefix)  # no-op rolls handled by the picker
    pool.add(recipient_prefix)      # always include identity as a valid roll
    return sorted(pool)



def compatible_pool_global(recipient_prefix: str, tags: dict, bank_to_prefixes: dict,
                            loose_to_prefixes: dict, mode: str = 'loose') -> list:
    """
    Like compatible_pool but with NO map-local restriction — the donor can be any
    c-prefix in the global tag set. Used for model-shuffle (which adds models to
    the section as needed) rather than the original shuffle (which is map-pool-locked).
    """
    rt = tags.get(recipient_prefix)
    if not rt or 'anim_bank' not in rt:
        return [recipient_prefix]
    pool = set(bank_to_prefixes.get(rt['anim_bank'], ()))
    if mode == 'loose':
        pool |= loose_to_prefixes.get(
            (rt['size_class'], rt['locomotion'], rt['team']), set())
    pool.discard(recipient_prefix)
    pool.add(recipient_prefix)
    return sorted(pool)


def shuffle_msb(input_path, output_path, rng, threshold, canonical_by_prefix,
                tags=None, bank_to_prefixes=None, loose_to_prefixes=None, mode='loose'):
    """
    Shuffle every Enemy Part in this MSB. Cluster-aware: multi_part clusters
    all roll to the same target (preserves the structure); tight_camp/singleton
    Parts roll independently.

    Pool selection:
      tags=None → map-local random (v1; "Oops! All Cursed", maximum chaos)
      tags=dict → tag-aware compatibility filtering (v2; clean visuals,
                  fewer T-poses / no flying demi-humans / no civil wars)

    Rewrites: name prefix at +0x60, NPCParamID at +0x25C, ThinkParamID at
    +0x258 for each Part; plus all cXXXX_NNNN references elsewhere in the
    file (route/SIB/etc) whose old name is now stale.
    """
    with open(input_path, 'rb') as f:
        data = bytearray(f.read())

    parts = extract_enemy_parts(bytes(data))
    if not parts:
        return None

    # Pool: c-prefixes ALREADY used in this map's Parts (so Models section
    # already lists them — no Models surgery needed).
    map_local_pool = {p['prefix'] for p in parts if p['prefix'] in canonical_by_prefix}
    if len(map_local_pool) < 2:
        return None  # nothing to shuffle into

    # Cluster placed parts. Origin parts shuffle independently (each its own group).
    placed = [(idx, p) for idx, p in enumerate(parts) if p['pos'] != (0.0, 0.0, 0.0)]
    origin = [(idx, p) for idx, p in enumerate(parts) if p['pos'] == (0.0, 0.0, 0.0)]
    placed_only = [p for _, p in placed]
    placed_to_orig = [idx for idx, _ in placed]
    clusters = find_position_clusters(placed_only, threshold)

    # Build groups: each group is a list of indices into `parts`. Multi_part
    # clusters become one group; tight_camp/template_pool clusters split into
    # singletons; placed loners are singletons; origin parts are singletons.
    #
    # EXCEPTION: in coherent mode (tags provided), every Part is its own group.
    # We're not changing models here, so cluster integrity (= "rider and mount
    # roll to same target name") doesn't matter — and rolling them together
    # would force the mount Part to use rider-bank animations and T-pose.
    # Per-Part rolls let the rider get a knight-bank target and the mount get
    # a mount-bank target independently.
    groups = []
    in_cluster = set()
    if tags is None:
        for cl in clusters:
            spread = cluster_spread(placed_only, cl)
            if classify_cluster(len(cl), spread) == 'multi_part':
                groups.append([placed_to_orig[i] for i in cl])
                in_cluster.update(cl)
            else:
                for i in cl:
                    groups.append([placed_to_orig[i]])
                    in_cluster.add(i)
        for i in range(len(placed_only)):
            if i not in in_cluster:
                groups.append([placed_to_orig[i]])
    else:
        # Coherent mode: each placed Part is its own group.
        for i in range(len(placed_only)):
            groups.append([placed_to_orig[i]])
    for idx, _ in origin:
        groups.append([idx])

    # Roll a target per group. Build per-Part target map and per-name reference map.
    # Use part-index-keyed maps so duplicate names don't collide on writes.
    part_targets = {}    # part_index -> target c-prefix
    name_map = {}        # old_full_name -> new_full_name (for external references)
    name_collisions = 0
    for group in groups:
        # Determine the pool for this group. For multi_part clusters all Parts
        # share the same recipient slot, so we use the FIRST Part's c-prefix
        # to determine compatibility (in vanilla cluster, both Parts of a
        # rider+mount have related but distinct prefixes — we just need any
        # of them to find the pool, the cluster will all roll to one target).
        recipient_prefix = parts[group[0]]['prefix']
        if tags is not None:
            group_pool = compatible_pool(
                recipient_prefix, map_local_pool,
                tags, bank_to_prefixes, loose_to_prefixes, mode=mode)
        else:
            group_pool = sorted(map_local_pool)
        if not group_pool:
            continue  # no valid targets, leave this group untouched
        target = rng.choice(group_pool)
        for pi in group:
            part = parts[pi]
            if part['prefix'] == target:
                continue  # rolled the same prefix it already has
            new_full = target + part['name'][5:]
            if part['name'] in name_map and name_map[part['name']] != new_full:
                name_collisions += 1
            name_map[part['name']] = new_full
            part_targets[pi] = target

    if not part_targets:
        return {'reassigned': 0, 'cluster_groups': len(groups), 'pool_size': len(map_local_pool),
                'external_rewrites': 0, 'name_collisions': 0}

    # Pass 1: rewrite each affected Part's struct directly (name prefix at +0x60,
    # NPCParam at +0x25C, ThinkParam at +0x258). No string search — exact offsets
    # so duplicate names cannot cause cross-Part contamination.
    struct_name_positions = set()
    for pi, target in part_targets.items():
        struct_start = parts[pi]['off']
        name_pos = struct_start + ENEMY_PART_NAME_OFFSET
        struct_name_positions.add(name_pos)
        new_prefix_bytes = target.encode('utf-16-le')
        assert len(new_prefix_bytes) == 10
        data[name_pos : name_pos + 10] = new_prefix_bytes
        ct = canonical_by_prefix[target]
        struct.pack_into('<I', data, struct_start + ENEMY_PART_NPC_PARAM_OFFSET,
                         ct['default_npc_param_id'])
        struct.pack_into('<I', data, struct_start + ENEMY_PART_THINK_PARAM_OFFSET,
                         ct['default_think_param_id'])
    # Track ALL Part struct name positions (so the external-pass skips them)
    for p in parts:
        struct_name_positions.add(p['off'] + ENEMY_PART_NAME_OFFSET)

    # Pass 2: rewrite EXTERNAL cXXXX_NNNN references (route/SIB/etc). Skip
    # positions that are inside Part struct name slots (already handled above).
    external_rewrites = 0
    snapshot = bytes(data)
    for m in PART_STRUCT_NAME_PATTERN.finditer(snapshot):
        pos = m.start()
        if pos in struct_name_positions:
            continue
        old_full = snapshot[pos:pos+20].decode('utf-16-le')
        if old_full in name_map:
            new_bytes = name_map[old_full].encode('utf-16-le')
            assert len(new_bytes) == 20
            data[pos:pos+20] = new_bytes
            external_rewrites += 1

    with open(output_path, 'wb') as f:
        f.write(data)

    return {
        'reassigned': len(part_targets),
        'cluster_groups': len(groups),
        'pool_size': len(map_local_pool),
        'external_rewrites': external_rewrites,
        'name_collisions': name_collisions,
    }


def cmd_shuffle(input_dir, output_dir, seed, threshold=2.0, tags_path=None, mode='loose'):
    import random
    rng = random.Random(seed)

    roster = load_roster()
    canonical_by_prefix = {t['c_prefix']: t for t in roster['canonical_targets']}

    tags = None
    bank_to_prefixes = None
    loose_to_prefixes = None
    if tags_path:
        tags = load_tags(tags_path)
        bank_to_prefixes, loose_to_prefixes = build_compat_lookups(tags)
        print(f"Loaded compatibility tags from {tags_path}: {len(tags)} c-prefixes,")
        print(f"  {len(bank_to_prefixes)} anim banks, {len(loose_to_prefixes)} loose buckets, mode={mode}")
    else:
        print("No --tags provided: running v1 map-local random pool ('Oops! All Cursed' chaos mode)")

    os.makedirs(output_dir, exist_ok=True)
    msb_files = sorted(f for f in os.listdir(input_dir) if f.endswith('.msb'))
    print(f"Shuffling {len(msb_files)} MSBs (seed={seed!r}, threshold={threshold})\n")

    shuffled = 0
    skipped = 0
    total_reassigned = 0
    total_external = 0
    total_groups = 0
    total_collisions = 0

    for fname in msb_files:
        in_path = os.path.join(input_dir, fname)
        out_path = os.path.join(output_dir, fname)
        stats = shuffle_msb(in_path, out_path, rng, threshold, canonical_by_prefix,
                            tags=tags, bank_to_prefixes=bank_to_prefixes,
                            loose_to_prefixes=loose_to_prefixes, mode=mode)
        if stats is None:
            shutil.copy2(in_path, out_path)
            skipped += 1
        else:
            shuffled += 1
            total_reassigned += stats['reassigned']
            total_external += stats['external_rewrites']
            total_groups += stats['cluster_groups']
            total_collisions += stats['name_collisions']
        copy_sidecars(input_dir, output_dir, fname)

    print(f"=== Summary ===")
    print(f"  Maps shuffled:                {shuffled}")
    print(f"  Maps unchanged:               {skipped}")
    print(f"  Cluster groups assigned:      {total_groups}")
    print(f"  Parts reassigned:             {total_reassigned}")
    print(f"  External name refs rewritten: {total_external}")
    if total_collisions:
        print(f"  Name collisions detected:     {total_collisions}  ← input has duplicate Part names")
        print(f"      (vanilla MSBs have unique names; collisions suggest input was previously converted)")
    print(f"\nOutput .msb files (with sidecars) in: {output_dir}")
    print(f"Reproduce this exact shuffle with: --seed {seed!r}")


# MSB section structure (decoded empirically from NR MSBs):
# Each section starts with a header:
#   +0x00 i32 sentinel (= 0x50, fixed)
#   +0x04 i32 entryCount   (counts "section name slot" + N data entries)
#   +0x08 i64[entryCount+1] offsets (file-relative)
#         offsets[0]                = section name string (e.g. MODEL_PARAM_ST)
#         offsets[1..entryCount-1]  = data entry positions
#         offsets[entryCount]       = next section start (or EOF for last)
#
# The 6 sections appear in this order in NR MSBs:
#   MODEL, EVENT, POINT, ROUTE, LAYER, PARTS  (PARTS is LAST)
#
# Model data entry layout (variable length, 8-byte aligned):
#   +0x00 i64 nameOffset    (relative to entry start; typically 0x28)
#   +0x08 i32 modelType     (2 = enemy/character, 0 = MapPiece, etc)
#   +0x0c i32 subIndex      (sequence index within modelType)
#   +0x10 i64 sibPathOffset (relative to entry start)
#   +0x18 i32 instanceCount (how many Parts reference this Model)
#   +0x1c i32 reserved      (= 0)
#   +0x20 i64 padding       (= 0)
#   +0x28 UTF-16 name string + null
#   +0xXX UTF-16 SIB path string + null
#   padded to 8-byte boundary

# Part struct offsets (verified by hex dump on m48_50 + c4070 NPC=40700010 / Think=40700000)
# Note: yesterday's compact summary listed offsets that were 0x60 too low — they were
# computed from an inferred "struct_start = name_pos - 0x60" which is actually 0x60
# *into* the real struct. Real struct starts at parts.entry_offsets[i] from parse_msb_sections.
PART_STRUCT_SIZE = 0x3e0           # most Parts; some are 0x3d0 for non-Enemy types
PART_OFF_MODEL_INDEX = 0x014       # i32, GLOBAL index into MODEL section entries
PART_OFF_NAME = 0x0c0              # UTF-16 cXXXX_NNNN (variable per Part; this is typical)
PART_OFF_ENTITY_ID = 0x260         # i32 (in early sub-record region)
PART_OFF_THINK_PARAM = 0x2b8       # i32
PART_OFF_NPC_PARAM = 0x2bc         # i32
PART_OFF_POSITION = 0x400          # 3×float (X, Y, Z)

MSB_HEADER_SIZE = 0x10


def parse_msb_sections(data: bytes) -> list:
    """Walk the MSB section table and return a list of section info dicts."""
    sections = []
    cursor = MSB_HEADER_SIZE
    while cursor < len(data):
        # Section header: i32 sentinel/version, i32 entryCount, i64[entryCount+1] offsets.
        # The "sentinel" first int is NOT fixed across files (m48_50 has 0x50, m19 has 0x4f).
        # Validate by sanity-checking entry_count and that offsets[0] points at a *_PARAM_ST string.
        if cursor + 8 > len(data): break
        sentinel = struct.unpack_from('<i', data, cursor)[0]
        entry_count = struct.unpack_from('<i', data, cursor + 4)[0]
        if entry_count <= 0 or entry_count > 4096: break
        if cursor + 8 + (entry_count + 1) * 8 > len(data): break
        offsets = []
        for i in range(entry_count + 1):
            off = struct.unpack_from('<q', data, cursor + 8 + i * 8)[0]
            offsets.append(off)
        # Validate: offsets[0] should point at "*_PARAM_ST" UTF-16 string
        name_off = offsets[0]
        if name_off + 28 > len(data): break
        # Read up to ~30 bytes and check for _PARAM_ST suffix
        name_bytes = data[name_off:name_off + 60]
        end = 0
        while end < len(name_bytes) - 1 and name_bytes[end:end+2] != b'\x00\x00':
            end += 2
        try:
            section_name = name_bytes[:end].decode('utf-16-le')
        except UnicodeDecodeError:
            break
        if not section_name.endswith('_PARAM_ST'):
            break
        sections.append({
            'section_start': cursor,
            'sentinel': sentinel,
            'entry_count': entry_count,
            'name_offset': name_off,
            'name': section_name,
            'entry_offsets': offsets[1:-1],
            'next_section_offset': offsets[-1],
        })
        cursor = offsets[-1]
        if cursor == 0:
            break
    return sections


def parse_model_entry(data: bytes, entry_off: int) -> dict:
    """Parse a single Model entry from the MODEL_PARAM_ST section."""
    name_off = struct.unpack_from('<q', data, entry_off + 0x00)[0]
    model_type = struct.unpack_from('<i', data, entry_off + 0x08)[0]
    sub_index = struct.unpack_from('<i', data, entry_off + 0x0c)[0]
    sib_path_off = struct.unpack_from('<q', data, entry_off + 0x10)[0]
    instance_count = struct.unpack_from('<i', data, entry_off + 0x18)[0]

    # Read name string at entry_off + name_off
    np = entry_off + name_off
    end = np
    while end < len(data) - 1 and data[end:end+2] != b'\x00\x00':
        end += 2
    name = data[np:end].decode('utf-16-le', errors='replace')

    # Read SIB path string at entry_off + sib_path_off
    sp = entry_off + sib_path_off
    end = sp
    while end < len(data) - 1 and data[end:end+2] != b'\x00\x00':
        end += 2
    sib_path = data[sp:end].decode('utf-16-le', errors='replace')

    return {
        'entry_offset': entry_off,
        'name': name,
        'model_type': model_type,
        'sub_index': sub_index,
        'sib_path': sib_path,
        'instance_count': instance_count,
    }


MODEL_TYPE_NAMES = {
    0: 'MapPiece',
    1: 'Object',
    2: 'Enemy',
    3: 'Player',
    4: 'Collision',
    5: 'Asset',
    6: 'Other',
}


def add_model_entry(data: bytes, name: str, sib_path: str, model_type: int = 2):
    """
    Insert a new Model entry into MODEL_PARAM_ST. Returns (new_msb_bytes, new_global_index).
    The new global index is the value to write into Part.ModelIndex (+0x014) to reference this Model.

    File-layout side effects:
    - MODEL section's offsets array gains 1 slot (+8 bytes), shifting section name and existing entries
    - New entry data appended at end of MODEL section data (+entry_size bytes, 8-byte aligned)
    - All subsequent section headers' offsets patched by total shift (+8 + entry_size)
    """
    sections = parse_msb_sections(data)
    if not sections or sections[0]['name'] != 'MODEL_PARAM_ST':
        raise ValueError("MODEL_PARAM_ST must be first section")
    models = sections[0]

    # New entry's subIndex = next sequential within modelType
    type_count = sum(
        1 for e_off in models['entry_offsets']
        if struct.unpack_from('<i', data, e_off + 0x08)[0] == model_type
    )
    new_sub_index = type_count

    # Construct new entry bytes
    name_utf16 = name.encode('utf-16-le') + b'\x00\x00'
    sib_utf16 = sib_path.encode('utf-16-le') + b'\x00\x00'
    name_offset_in_entry = 0x28
    sib_offset_in_entry = name_offset_in_entry + len(name_utf16)

    entry = bytearray()
    entry += struct.pack('<q', name_offset_in_entry)
    entry += struct.pack('<i', model_type)
    entry += struct.pack('<i', new_sub_index)
    entry += struct.pack('<q', sib_offset_in_entry)
    entry += struct.pack('<i', 0)            # instanceCount (Parts will increment via update_model_instance_count)
    entry += struct.pack('<i', 0)            # reserved
    entry += struct.pack('<q', 0)            # padding
    assert len(entry) == 0x28
    entry += name_utf16
    entry += sib_utf16
    while len(entry) % 8 != 0:
        entry += b'\x00'
    new_entry_size = len(entry)

    new_global_index = len(models['entry_offsets'])
    shift_amount = 8 + new_entry_size

    out = bytearray()
    out += data[0:MSB_HEADER_SIZE]

    # MODEL section header
    out += struct.pack('<i', models['sentinel'])
    out += struct.pack('<i', models['entry_count'] + 1)
    out += struct.pack('<q', models['name_offset'] + 8)
    for old_e_off in models['entry_offsets']:
        out += struct.pack('<q', old_e_off + 8)
    out += struct.pack('<q', models['next_section_offset'] + 8)              # new entry position
    out += struct.pack('<q', models['next_section_offset'] + shift_amount)   # new next-section

    # MODEL section content + new entry
    out += data[models['name_offset']:models['next_section_offset']]
    out += entry

    # Subsequent sections with shifted offsets
    rest_start = models['next_section_offset']
    rest = bytearray(data[rest_start:])
    for sec in sections[1:]:
        pos_in_rest = sec['section_start'] - rest_start
        for i in range(sec['entry_count'] + 1):
            off_pos = pos_in_rest + 8 + i * 8
            old = struct.unpack_from('<q', rest, off_pos)[0]
            if old != 0:
                struct.pack_into('<q', rest, off_pos, old + shift_amount)
    out += rest

    return bytes(out), new_global_index


def find_model_index(data: bytes, name: str, model_type: int = 2) -> int:
    """Return the global index of the Model entry matching name+type, or -1 if not present."""
    sections = parse_msb_sections(data)
    models = sections[0]
    for gi, e_off in enumerate(models['entry_offsets']):
        m = parse_model_entry(data, e_off)
        if m['name'] == name and m['model_type'] == model_type:
            return gi
    return -1


def find_or_add_model(data: bytes, name: str, model_type: int = 2):
    """Return (data, global_index). Adds the model if not present, otherwise returns existing index."""
    existing = find_model_index(data, name, model_type)
    if existing >= 0:
        return data, existing
    sib = f'W:\\CL\\data\\Model\\chr\\{name}\\sib\\{name}.sib'
    return add_model_entry(data, name, sib, model_type)


def set_part_model_index(data: bytes, part_index: int, new_model_index: int) -> bytes:
    """Update a Part's ModelIndex (struct +0x014). part_index is index into PARTS section."""
    sections = parse_msb_sections(data)
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    if part_index >= len(parts['entry_offsets']):
        raise IndexError(f"part_index {part_index} >= {len(parts['entry_offsets'])}")
    out = bytearray(data)
    struct.pack_into('<i', out, parts['entry_offsets'][part_index] + PART_OFF_MODEL_INDEX, new_model_index)
    return bytes(out)


def update_model_instance_count(data: bytes, model_global_index: int, delta: int) -> bytes:
    """Adjust a Model entry's instanceCount by delta (used for bookkeeping after swaps)."""
    sections = parse_msb_sections(data)
    models = sections[0]
    e_off = models['entry_offsets'][model_global_index]
    out = bytearray(data)
    cur = struct.unpack_from('<i', out, e_off + 0x18)[0]
    struct.pack_into('<i', out, e_off + 0x18, cur + delta)
    return bytes(out)


def swap_part_model(data: bytes, part_index: int, target_name: str) -> bytes:
    """
    Reassign Part[part_index] to use Model named target_name.
    Adds the Model to the section if not already present.
    Updates instance counts on both old and new Model entries.
    """
    # Read Part's current ModelIndex
    sections = parse_msb_sections(data)
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    part_off = parts['entry_offsets'][part_index]
    old_index = struct.unpack_from('<i', data, part_off + PART_OFF_MODEL_INDEX)[0]

    # Find or add the target model
    data, new_index = find_or_add_model(data, target_name)
    if new_index == old_index:
        return data  # no-op

    # Rewrite Part's ModelIndex
    data = set_part_model_index(data, part_index, new_index)

    # Update instance counts
    data = update_model_instance_count(data, old_index, -1)
    data = update_model_instance_count(data, new_index, +1)
    return data


def compute_model_part_refs(data: bytes) -> dict:
    """Walk PARTS_PARAM_ST and count how many Parts reference each model
    by global index. Source of truth for "is this model still used" — the
    Model entries' own instance_count is bookkeeping that may drift if
    callers forgot to call update_model_instance_count. Returns
    {model_index: ref_count} including 0 for unreferenced models.
    """
    sections = parse_msb_sections(data)
    models = next((s for s in sections if s['name'] == 'MODEL_PARAM_ST'), None)
    parts = next((s for s in sections if s['name'] == 'PARTS_PARAM_ST'), None)
    if not models or not parts:
        return {}
    refs = {i: 0 for i in range(len(models['entry_offsets']))}
    for part_off in parts['entry_offsets']:
        if part_off + PART_OFF_MODEL_INDEX + 4 > len(data):
            continue
        mi = struct.unpack_from('<i', data, part_off + PART_OFF_MODEL_INDEX)[0]
        if mi in refs:
            refs[mi] += 1
    return refs


def remove_unused_model_entries(data: bytes, model_type_filter: int = 2,
                                protect_names: 'Optional[set]' = None):
    """Remove Model entries that no Part references, by global index. Returns
    (new_data, removed_entries, remap) where:
      - removed_entries is a list of dicts: {old_index, name, model_type, sib_path}
      - remap is {old_index: new_index} for surviving entries (removed ones absent)

    Only entries matching model_type_filter are eligible for removal (default 2
    = Enemy). Pass None to consider all types — discouraged: removing MapPiece
    or Collision entries can corrupt the map even if no Part references them
    because other systems (collision lookup, route bindings) may reference
    them out-of-band.

    protect_names (v0.25.0-patch3): if provided, model entries whose `name`
    field matches a value in this set are NEVER removed, even when no Part
    references them. Used to preserve boss-arena-relevant chrs from
    aggressive compaction — the boss-init EMEVD can SpawnNPC dynamically
    using chr model templates that must remain declared in the MSB even
    after all static Part instances of that chr have been swapped away.
    Without this protection, m48_40 Morgott's prelude Leyndell Knight
    (c4353) was compacted out because the pi=4 Part got swapped to
    something else, breaking the prelude minion wave and stalling the
    boss-init handshake ("N2 boss never spawns" bug, see emevd_patch.py
    nb_arena_entry_trigger comment). Caller computes this set from
    data/nr_boss_slots.json per MSB.

    Side effects on layout:
      - MODEL section's offsets array shrinks by 8 bytes per removed entry
      - MODEL section's entry data shrinks by sum(removed_entry_sizes)
      - All Parts' ModelIndex fields are remapped to surviving indices
      - All subsequent section headers' offsets are patched by the total
        byte savings (negative shift)

    Safe to call after the swap loop. Does not run if MODEL section is missing
    or no entries match the removal criteria — returns input unchanged.
    """
    sections = parse_msb_sections(data)
    if not sections or sections[0]['name'] != 'MODEL_PARAM_ST':
        return data, [], {}
    models = sections[0]
    parts = next((s for s in sections if s['name'] == 'PARTS_PARAM_ST'), None)
    if not parts:
        return data, [], {}

    refs = compute_model_part_refs(data)

    # Compute entry sizes: each entry runs from its offset to the next entry's
    # offset (or to next_section_offset for the last one).
    entry_offsets = list(models['entry_offsets'])
    entry_ends = entry_offsets[1:] + [models['next_section_offset']]
    entry_sizes = [end - start for start, end in zip(entry_offsets, entry_ends)]

    # Determine which entries to remove
    remove_indices = set()
    removed_entries = []
    skipped_for_protection = []
    for i, e_off in enumerate(entry_offsets):
        if refs.get(i, 0) != 0:
            continue
        model_type = struct.unpack_from('<i', data, e_off + 0x08)[0]
        if model_type_filter is not None and model_type != model_type_filter:
            continue
        m = parse_model_entry(data, e_off)
        # v0.25.0-patch3: skip removal if name is in the caller's protect set.
        # Keeps boss-arena-relevant chrs declared so EMEVD SpawnNPC can find
        # their template even after static Parts are swapped away.
        if protect_names is not None and m['name'] in protect_names:
            skipped_for_protection.append(m['name'])
            continue
        remove_indices.add(i)
        removed_entries.append({
            'old_index': i, 'name': m['name'],
            'model_type': m['model_type'], 'sib_path': m['sib_path'],
        })

    if not remove_indices:
        return data, [], {}

    # Build remap: surviving entries get sequential new indices
    remap = {}
    new_idx = 0
    for i in range(len(entry_offsets)):
        if i in remove_indices:
            continue
        remap[i] = new_idx
        new_idx += 1

    # Bytes saved: offsets array shrinks + removed entry data
    offsets_saved = 8 * len(remove_indices)
    entry_bytes_saved = sum(entry_sizes[i] for i in remove_indices)
    total_shift = offsets_saved + entry_bytes_saved  # positive; subtracted from subsequent offsets

    surviving_entry_indices = [i for i in range(len(entry_offsets))
                               if i not in remove_indices]
    new_entry_count = len(surviving_entry_indices)

    # Build new MSB
    out = bytearray()
    out += data[0:MSB_HEADER_SIZE]

    # New MODEL section header.
    # Raw entry_count field includes the name-string slot, so it's
    # n_entries + 1 (mirrors add_model_entry's `entry_count + 1` when
    # adding one). After removing K entries, raw count = old_raw - K.
    out += struct.pack('<i', models['sentinel'])
    out += struct.pack('<i', models['entry_count'] - len(remove_indices))
    # Name offset: was models['name_offset']; offsets array is now smaller by
    # offsets_saved, so name string lives offsets_saved bytes earlier.
    new_name_offset = models['name_offset'] - offsets_saved
    out += struct.pack('<q', new_name_offset)

    # Each surviving entry's new offset is: original offset
    #   - offsets_saved (offsets array shrank)
    #   - sum of removed entry sizes BEFORE this one (preceding entries gone)
    cumulative_removed_bytes = 0
    for survivor_idx in surviving_entry_indices:
        # How many bytes of removed entries precede this survivor?
        preceding_removed = sum(
            entry_sizes[j] for j in remove_indices if j < survivor_idx)
        new_offset = entry_offsets[survivor_idx] - offsets_saved - preceding_removed
        out += struct.pack('<q', new_offset)
    # New next_section_offset
    new_next = models['next_section_offset'] - total_shift
    out += struct.pack('<q', new_next)

    # MODEL section name string (unchanged content, position shifted earlier)
    name_str_bytes = data[models['name_offset']:entry_offsets[0]]
    out += name_str_bytes

    # Surviving entry data (in order)
    for survivor_idx in surviving_entry_indices:
        entry_start = entry_offsets[survivor_idx]
        entry_end = entry_ends[survivor_idx]
        out += data[entry_start:entry_end]

    # Subsequent sections: copy as-is but patch all 64-bit offsets in their
    # headers (sentinel + entry_count + offsets[entry_count+1])
    rest_start = models['next_section_offset']
    rest = bytearray(data[rest_start:])
    for sec in sections[1:]:
        pos_in_rest = sec['section_start'] - rest_start
        for i in range(sec['entry_count'] + 1):
            off_pos = pos_in_rest + 8 + i * 8
            old = struct.unpack_from('<q', rest, off_pos)[0]
            if old != 0:
                struct.pack_into('<q', rest, off_pos, old - total_shift)
    out += rest

    # Walk Parts in the rewritten data and remap ModelIndex fields
    new_data = bytes(out)
    new_sections = parse_msb_sections(new_data)
    new_parts = next(s for s in new_sections if s['name'] == 'PARTS_PARAM_ST')
    out2 = bytearray(new_data)
    for part_off in new_parts['entry_offsets']:
        if part_off + PART_OFF_MODEL_INDEX + 4 > len(out2):
            continue
        old_mi = struct.unpack_from('<i', out2, part_off + PART_OFF_MODEL_INDEX)[0]
        if old_mi in remap:
            new_mi = remap[old_mi]
            if new_mi != old_mi:
                struct.pack_into('<i', out2, part_off + PART_OFF_MODEL_INDEX, new_mi)
        # If old_mi was removed (shouldn't happen since we only remove
        # entries with refs=0), the index would be stale. Leave as-is —
        # the upstream invariant says no Part references a removed entry.

    return bytes(out2), removed_entries, remap


def cmd_dump_models(input_path):
    """Dump the Models section of an MSB to confirm the decoded structure."""
    with open(input_path, 'rb') as f:
        data = f.read()

    print(f"Reading {input_path} ({len(data)} bytes)\n")
    sections = parse_msb_sections(data)
    print(f"Found {len(sections)} sections:")
    for s in sections:
        print(f"  {s['name']:<18} @ 0x{s['section_start']:>5x}  "
              f"entries={len(s['entry_offsets']):>3}  next=0x{s['next_section_offset']:x}")

    # Find the Models section
    models = next((s for s in sections if s['name'] == 'MODEL_PARAM_ST'), None)
    if not models:
        print("\nNo MODEL_PARAM_ST section found.")
        return

    print(f"\n=== MODEL_PARAM_ST entries ({len(models['entry_offsets'])}) ===")
    print(f"  {'name':<14}  {'type':<10}  {'subIdx':>6}  {'parts':>5}  sibPath")
    by_type = {}
    for e_off in models['entry_offsets']:
        m = parse_model_entry(data, e_off)
        type_name = MODEL_TYPE_NAMES.get(m['model_type'], f"type{m['model_type']}")
        by_type.setdefault(m['model_type'], 0)
        by_type[m['model_type']] += 1
        # Trim sib path for display
        path = m['sib_path']
        if len(path) > 50:
            path = '...' + path[-47:]
        print(f"  {m['name']:<14}  {type_name:<10}  {m['sub_index']:>6}  "
              f"{m['instance_count']:>5}  {path}")

    print(f"\nBy model type:")
    for t, n in sorted(by_type.items()):
        type_name = MODEL_TYPE_NAMES.get(t, f"type{t}")
        print(f"  {type_name} (type {t}): {n} entries")


def model_shuffle_msb(input_path, output_path, rng, tags, mode, npc_think_lookup):
    """
    Apply MODEL-LEVEL shuffle to a single MSB.

    Unlike the original shuffle (which only rewrites NPCParam/ThinkParam at fixed
    Part offsets), this one swaps the Part's ModelIndex too — so the actual mesh
    rendered changes. It does this by adding new entries to the Models section
    (via add_model_entry) when a target c-prefix isn't already present.

    Returns (n_swaps, n_models_added) or False on parse failure.
    """
    bank_to_prefixes, loose_to_prefixes = build_compat_lookups(tags)

    with open(input_path, 'rb') as f:
        data = f.read()

    sections = parse_msb_sections(data)
    if len(sections) != 6:
        return False
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    models = sections[0]

    # Map global model index → c-prefix (for reading Part's current target)
    model_idx_to_prefix = {}
    for gi, eo in enumerate(models['entry_offsets']):
        m = parse_model_entry(data, eo)
        model_idx_to_prefix[gi] = m['name']

    # Build swap plan: for each Enemy Part, decide target c-prefix
    swap_plan = []
    for pi, po in enumerate(parts['entry_offsets']):
        npc = struct.unpack_from('<I', data, po + PART_OFF_NPC_PARAM)[0]
        if npc == 0 or npc == 0xFFFFFFFF:
            continue  # not a valid enemy
        cur_mi = struct.unpack_from('<i', data, po + PART_OFF_MODEL_INDEX)[0]
        cur_prefix = model_idx_to_prefix.get(cur_mi, '?')
        if cur_prefix in EXCLUDE_SOURCE_PREFIXES:
            continue
        # Compat pool — global, filtered by tags
        pool = compatible_pool_global(cur_prefix, tags, bank_to_prefixes, loose_to_prefixes, mode)
        # Restrict to c-prefixes we have NPC/Think param IDs for in the roster
        pool = [p for p in pool if p in npc_think_lookup]
        if not pool:
            continue
        target = rng.choice(pool)
        if target == cur_prefix:
            continue  # rolled identity, leave alone
        swap_plan.append((pi, target))

    if not swap_plan:
        # Nothing to do; just copy
        with open(output_path, 'wb') as f:
            f.write(data)
        return (0, 0)

    # Step 1: Ensure all unique targets exist in the Models section
    n_added = 0
    target_set = set(t for _, t in swap_plan)
    for target in sorted(target_set):
        if find_model_index(data, target) < 0:
            sib = f'W:\\CL\\data\\Model\\chr\\{target}\\sib\\{target}.sib'
            data, _ = add_model_entry(data, target, sib, model_type=2)
            n_added += 1

    # Step 2: Build target → global index mapping (after all additions)
    sections = parse_msb_sections(data)
    models = sections[0]
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    target_to_idx = {}
    for gi, eo in enumerate(models['entry_offsets']):
        m = parse_model_entry(data, eo)
        if m['name'] not in target_to_idx:
            target_to_idx[m['name']] = gi

    # Step 3: Apply Part rewrites in one byte-level pass
    out = bytearray(data)
    for pi, target in swap_plan:
        po = parts['entry_offsets'][pi]
        new_idx = target_to_idx[target]
        old_idx = struct.unpack_from('<i', out, po + PART_OFF_MODEL_INDEX)[0]

        # ModelIndex
        struct.pack_into('<i', out, po + PART_OFF_MODEL_INDEX, new_idx)
        # NPCParam / ThinkParam (so AI matches the new model)
        npc_id, think_id = npc_think_lookup[target]
        struct.pack_into('<I', out, po + PART_OFF_NPC_PARAM, npc_id)
        struct.pack_into('<I', out, po + PART_OFF_THINK_PARAM, think_id)

        # Update instance counts on both old and new model entries
        old_e_off = models['entry_offsets'][old_idx]
        new_e_off = models['entry_offsets'][new_idx]
        cur_old = struct.unpack_from('<i', out, old_e_off + 0x18)[0]
        struct.pack_into('<i', out, old_e_off + 0x18, cur_old - 1)
        cur_new = struct.unpack_from('<i', out, new_e_off + 0x18)[0]
        struct.pack_into('<i', out, new_e_off + 0x18, cur_new + 1)

    with open(output_path, 'wb') as f:
        f.write(bytes(out))
    return (len(swap_plan), n_added)


def cmd_model_shuffle(input_dir, output_dir, seed, tags_path, mode='loose'):
    import random
    rng = random.Random(seed)

    with open(tags_path, 'r', encoding='utf-8') as f:
        tags = json.load(f)

    roster = load_roster()
    npc_think_lookup = {}
    for entry in roster.get('all_variants', []):
        cp = entry['c_prefix']
        if cp not in npc_think_lookup:
            npc_think_lookup[cp] = (entry['npc_param_id'], entry['think_param_id'])
    print(f"Loaded {len(npc_think_lookup)} c-prefixes from roster")

    # Allow input to be either a directory or single .msb file
    is_file = os.path.isfile(input_dir) and input_dir.endswith('.msb')
    if is_file:
        in_paths = [input_dir]
        os.makedirs(os.path.dirname(output_dir) or '.', exist_ok=True)
        out_paths = [output_dir]
    else:
        os.makedirs(output_dir, exist_ok=True)
        in_paths, out_paths = [], []
        for fname in sorted(os.listdir(input_dir)):
            if fname.endswith('.msb'):
                in_paths.append(os.path.join(input_dir, fname))
                out_paths.append(os.path.join(output_dir, fname))

    total_files = total_swaps = total_added = total_skipped = 0
    for ip, op in zip(in_paths, out_paths):
        try:
            res = model_shuffle_msb(ip, op, rng, tags, mode, npc_think_lookup)
            if res is False:
                total_skipped += 1
                print(f"  SKIP {os.path.basename(ip)} (parse failure)")
                continue
            n_swaps, n_added = res
            total_files += 1
            total_swaps += n_swaps
            total_added += n_added
            print(f"  {os.path.basename(ip):<30}  swaps={n_swaps:<3}  models_added={n_added}")

            # Copy sidecar metadata (Yabber XML) so output zip is repackable
            for suffix in SIDECAR_SUFFIXES:
                sc = ip + suffix
                if os.path.exists(sc):
                    import shutil
                    shutil.copy(sc, op + suffix)
                    break
        except Exception as e:
            print(f"  ERROR {os.path.basename(ip)}: {e}")

    print(f"\nProcessed {total_files} files, {total_swaps} swaps, {total_added} new model entries added")
    if total_skipped:
        print(f"Skipped {total_skipped} files due to parse failures")


def cmd_model_swap(input_path, output_path, part_index, target_name):
    """Single-Part model swap, for smoke testing the binary surgery in-game."""
    with open(input_path, 'rb') as f:
        data = f.read()
    print(f"Loaded {input_path} ({len(data)} bytes)")

    # Show before
    sections = parse_msb_sections(data)
    parts = next(s for s in sections if s['name'] == 'PARTS_PARAM_ST')
    part_off = parts['entry_offsets'][part_index]
    old_idx = struct.unpack_from('<i', data, part_off + PART_OFF_MODEL_INDEX)[0]
    models = sections[0]
    old_model = parse_model_entry(data, models['entry_offsets'][old_idx])
    print(f"  Part[{part_index}] currently references model[{old_idx}] = {old_model['name']!r}")

    # Swap
    new_data = swap_part_model(data, part_index, target_name)
    new_sections = parse_msb_sections(new_data)
    new_parts = next(s for s in new_sections if s['name'] == 'PARTS_PARAM_ST')
    new_part_off = new_parts['entry_offsets'][part_index]
    new_idx = struct.unpack_from('<i', new_data, new_part_off + PART_OFF_MODEL_INDEX)[0]
    print(f"  Part[{part_index}] now references model[{new_idx}] = {target_name!r}")
    print(f"  File size: {len(data)} → {len(new_data)} ({len(new_data) - len(data):+d} bytes)")

    with open(output_path, 'wb') as f:
        f.write(new_data)
    print(f"Wrote {output_path}")


def main():
    if len(sys.argv) < 2: print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'list': cmd_list()
    elif cmd == 'search':
        if len(sys.argv) != 3: print("Usage: search <text>"); sys.exit(1)
        cmd_search(sys.argv[2])
    elif cmd == 'convert':
        if len(sys.argv) != 5: print("Usage: convert <target> <input> <output>"); sys.exit(1)
        cmd_convert(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == 'cluster-report':
        if len(sys.argv) < 3:
            print("Usage: cluster-report <input_dir> [threshold] [--json out.json]")
            sys.exit(1)
        input_dir = sys.argv[2]
        threshold = 2.0
        json_out = None
        i = 3
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == '--json':
                if i + 1 >= len(sys.argv): print("--json requires a path"); sys.exit(1)
                json_out = sys.argv[i+1]; i += 2
            else:
                try: threshold = float(arg); i += 1
                except ValueError: print(f"Unknown arg: {arg}"); sys.exit(1)
        cmd_cluster_report(input_dir, threshold, json_out)
    elif cmd == 'shuffle':
        if len(sys.argv) < 4:
            print("Usage: shuffle <input_dir> <output_dir> [--seed N] [--threshold T] [--tags JSON] [--mode strict|loose]")
            sys.exit(1)
        input_dir = sys.argv[2]
        output_dir = sys.argv[3]
        seed = None
        threshold = 2.0
        tags_path = None
        mode = 'loose'
        i = 4
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == '--seed':
                if i + 1 >= len(sys.argv): print("--seed requires a value"); sys.exit(1)
                seed_val = sys.argv[i+1]
                try: seed = int(seed_val)
                except ValueError: seed = seed_val
                i += 2
            elif arg == '--threshold':
                if i + 1 >= len(sys.argv): print("--threshold requires a value"); sys.exit(1)
                threshold = float(sys.argv[i+1]); i += 2
            elif arg == '--tags':
                if i + 1 >= len(sys.argv): print("--tags requires a path"); sys.exit(1)
                tags_path = sys.argv[i+1]; i += 2
            elif arg == '--mode':
                if i + 1 >= len(sys.argv): print("--mode requires strict|loose"); sys.exit(1)
                mode = sys.argv[i+1]
                if mode not in ('strict', 'loose'):
                    print("--mode must be 'strict' or 'loose'"); sys.exit(1)
                i += 2
            else:
                print(f"Unknown arg: {arg}"); sys.exit(1)
        cmd_shuffle(input_dir, output_dir, seed, threshold, tags_path, mode)
    elif cmd == 'dump-models':
        if len(sys.argv) != 3:
            print("Usage: dump-models <msb_file>")
            sys.exit(1)
        cmd_dump_models(sys.argv[2])
    elif cmd == 'model-shuffle':
        # Usage: model-shuffle <input> <output> [--seed N] [--tags JSON] [--mode loose|strict]
        if len(sys.argv) < 4:
            print("Usage: model-shuffle <input.msb|input_dir> <output.msb|output_dir> [--seed N] [--tags JSON] [--mode loose|strict]")
            sys.exit(1)
        in_path = sys.argv[2]
        out_path = sys.argv[3]
        seed = 42
        # v0.23.71: default to the engine-conventional location.
        tags_path = _data_path('nr_enemy_tags.json')
        mode = 'loose'
        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == '--seed':
                seed = int(sys.argv[i+1]); i += 2
            elif sys.argv[i] == '--tags':
                tags_path = sys.argv[i+1]; i += 2
            elif sys.argv[i] == '--mode':
                mode = sys.argv[i+1]; i += 2
            else:
                print(f"Unknown arg: {sys.argv[i]}"); sys.exit(1)
        cmd_model_shuffle(in_path, out_path, seed, tags_path, mode)
    elif cmd == 'model-swap':
        if len(sys.argv) != 6:
            print("Usage: model-swap <input.msb> <output.msb> <part_index> <target_cprefix>")
            print("Example: model-swap m48_50.msb out.msb 0 c4500")
            sys.exit(1)
        cmd_model_swap(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
    else: print(__doc__); sys.exit(1)


if __name__ == '__main__':
    main()
