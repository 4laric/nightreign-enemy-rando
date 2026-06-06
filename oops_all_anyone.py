"""MSB binary-format primitives for Nightreign / Elden Ring map files.

This module exposes the byte-level parse / mutate primitives that the
v3 engine (`oops_v3.py`) calls to operate on .msb files. It is NOT
the engine — the engine lives in `oops_v3.py`.

History
-------
Originally `oops_all_anyone.py` was a self-contained CLI tool for
applying single-target enemy substitutions ("Oops! All Wolves",
"Oops! All Bell-Bearing Hunters"). The CLI grew a v2 shuffle mode
that became the prototype for the v3 engine.

In v0.28.x the entire CLI surface — `cmd_list`, `cmd_search`,
`cmd_convert`, `cmd_cluster_report`, `cmd_shuffle`, `cmd_dump_models`,
`cmd_model_shuffle`, `cmd_model_swap`, plus the `shuffle_msb` /
`compatible_pool*` / `build_compat_lookups` / `load_tags`
infrastructure and the supporting helpers (`load_roster`,
`resolve_target`, `find_position_clusters`, etc.) — was removed.
None of it had external callers since v0.23.x; the v3 engine in
`oops_v3.py` had replaced every entrypoint. The module surface is now
just the MSB primitives that `oops_v3` imports.

The kept primitives are locked by `tests/test_oops_all_anyone_surface_lock.py`.
Adding a new external import requires updating that lock.

For the CLI behavior at retirement, see git history before v0.28.x.
"""
import re
import struct


# ---------------------------------------------------------------------------
# Constants — internal helpers consumed by extract_enemy_parts and the
# MSB section / model / part primitives. These reflect FromSoft's binary
# layout for Nightreign MSBs and were reverse-engineered against
# m60_42_36_00 and m48_50.
# ---------------------------------------------------------------------------

# Enemy Part struct offsets — verified against m60_42_36_00.
ENEMY_PART_STRUCT_SIZE        = 0x3e0
ENEMY_PART_NAME_OFFSET        = 0x60
ENEMY_PART_ENTITY_ID_OFFSET   = 0x200
ENEMY_PART_THINK_PARAM_OFFSET = 0x258
ENEMY_PART_NPC_PARAM_OFFSET   = 0x25C
ENEMY_PART_POS_OFFSET         = 0x3a0   # X, Y, Z floats

EXCLUDE_SOURCE_PREFIXES = {
    'c0000', 'c0100', 'c0110', 'c0120',  # player nightfarer templates
    'c1000',                              # standin / placeholder
    'c2070',                              # bonfire dummy
}

PART_STRUCT_NAME_PATTERN = re.compile(
    rb'c\x00\d\x00\d\x00\d\x00\d\x00_\x00\d\x00\d\x00\d\x00\d\x00\x00\x00'
)


# ---------------------------------------------------------------------------
# Surface constants — exported via the surface lock. Used by oops_v3 +
# other consumers. Offsets verified by hex dump on m48_50 + c4070
# (NPC=40700010 / Think=40700000). Real struct starts at
# parts.entry_offsets[i] from parse_msb_sections — earlier compact
# summaries were 0x60 too low because they reported offsets relative to
# the inferred name position rather than the actual struct start.
# ---------------------------------------------------------------------------

PART_OFF_MODEL_INDEX = 0x014       # i32, GLOBAL index into MODEL section entries
PART_OFF_ENTITY_ID   = 0x260       # i32 (in early sub-record region)
PART_OFF_THINK_PARAM = 0x2b8       # i32
PART_OFF_NPC_PARAM   = 0x2bc       # i32
PART_OFF_POSITION    = 0x400       # 3×float (X, Y, Z)

MSB_HEADER_SIZE = 0x10

# Sidecar suffixes that pair with an .msb file (Yabber: -yabber-dcx.xml,
# Witchy: -wdcx.xml).
SIDECAR_SUFFIXES = ['-yabber-dcx.xml', '-wdcx.xml']


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
