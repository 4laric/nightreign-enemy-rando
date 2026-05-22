"""fmg.py — FMG v2 parser, writer, and splice function for the NR
Sekiro+ variant.

Format-spec derived empirically against `reference/NpcName.fmg`
(13096 bytes, FMG version 2, engUS boss/NPC name table). See
`reference/README.md` for the chain of evidence behind each field
interpretation, especially the unusual group layout below.

Header layout (0x20 bytes total):
  +0x00  u8   byte_order_marker = 0
  +0x01  u8   big_endian = 0
  +0x02  u8   version = 2
  +0x03  u8   padding = 0
  +0x04  u32  file_size (total FMG size in bytes)
  +0x08  u8   version_flag = 1
  +0x09  u8   padding (was 0xff sentinel in some variants — 0 here)
  +0x0A  u8   padding = 0
  +0x0B  u8   padding = 0
  +0x0C  u32  group_count
  +0x10  u32  string_count
  +0x14  u32  version_extra = 0xff (sentinel)
  +0x18  u32  string_offsets_table_offset (where the u64 offsets begin)
  +0x1C  u32  padding = 0

Groups (16 bytes each), starting at +0x20:
  +0x00  i32  first_id
  +0x04  i32  _zero (always 0; not last_id as in standard SoulsFormats)
  +0x08  i32  first_string_idx (index into string offsets table)
  +0x0C  i32  last_id

  Mapping: a group of count N (= next_group.first_string_idx -
  first_string_idx, or string_count - first_string_idx for the last
  group) covers string indices `first_string_idx..first_string_idx+N`,
  which map to IDs `first_id..first_id+N-1`.

  *Important*: Vanilla FMGs may have multiple groups whose ID ranges
  overlap (e.g., one group with first_id=0 first_str_idx=0 count=1, and
  another with first_id=0 first_str_idx=1 count=131). In such cases,
  the same logical ID maps to TWO distinct string slots. We preserve
  both for byte-perfect round-tripping.

String offsets table (8 bytes each, u64):
  Each entry is the absolute byte offset of a UTF-16 LE
  null-terminated string within the FMG. Offset 0 = no string.

Strings: UTF-16 LE null-terminated, packed sequentially from the
end of the string offsets table to file_size.
"""

import struct
from dataclasses import dataclass, field


@dataclass
class FMGGroup:
    first_id: int
    first_string_idx: int
    last_id: int
    # Number of string slots this group covers. Computed from
    # (next_group.first_string_idx - first_string_idx) at parse time,
    # or string_count - first_string_idx for the last group.
    count: int = 0

    def __lt__(self, other):
        return self.first_id < other.first_id


@dataclass
class FMG:
    """Parsed FMG.

    Internally indexed by string_idx (string slot number, not logical ID),
    because vanilla allows the same ID in multiple groups, so a single
    `id -> text` mapping would be lossy.

    Public `entries` property exposes id -> text for convenience (lossy
    for IDs that appear in multiple groups; downstream callers should
    use the splice function for safe modifications).
    """
    version: int = 2
    version_extra: int = 0xff
    version_flag: int = 1
    big_endian: bool = False
    pad_03: int = 0
    pad_09: int = 0
    pad_0a: int = 0
    pad_0b: int = 0

    # Authoritative storage:
    # - groups: list of FMGGroup (preserves vanilla group order/structure)
    # - strings_by_idx: dict[int, str | None]. None means slot has
    #   string_offset=0 ("no string"). "" means slot exists with an
    #   empty (but present) string.
    groups: list = field(default_factory=list)
    strings_by_idx: dict = field(default_factory=dict)
    # Bytes between groups-end and sotr-table-start (vanilla writes 0-8
    # bytes of mystery content here; preserve verbatim for round-trip).
    _gap_bytes: bytes = b''

    @property
    def entries(self) -> dict:
        """Convenience: id -> text. Lossy when vanilla had overlapping
        groups (last-write-wins, mirroring the old parser behavior so
        existing callers stay compatible)."""
        out = {}
        for g in self.groups:
            for k in range(g.count):
                string_idx = g.first_string_idx + k
                id_ = g.first_id + k
                text = self.strings_by_idx.get(string_idx)
                # None means "empty slot" — map to "" so dict-style access
                # treats it as a present-but-empty entry.
                out[id_] = "" if text is None else text
        return out


def parse_fmg(raw: bytes) -> FMG:
    """Parse an FMG version 2 file."""
    if raw[0] != 0:
        raise ValueError(f"FMG byte_order_marker != 0: 0x{raw[0]:02x}")
    big_endian = raw[1] != 0
    if big_endian:
        raise NotImplementedError("big-endian FMG not supported")
    version = raw[2]
    if version != 2:
        raise NotImplementedError(f"only FMG v2 supported, got v{version}")
    pad_03 = raw[3]

    file_size = struct.unpack_from('<I', raw, 0x04)[0]
    if file_size != len(raw):
        raise ValueError(
            f"FMG file_size header says {file_size} but raw bytes are {len(raw)}"
        )

    version_flag = raw[0x08]
    pad_09 = raw[0x09]
    pad_0a = raw[0x0A]
    pad_0b = raw[0x0B]
    group_count = struct.unpack_from('<I', raw, 0x0C)[0]
    string_count = struct.unpack_from('<I', raw, 0x10)[0]
    version_extra = struct.unpack_from('<I', raw, 0x14)[0]
    string_offsets_table_off = struct.unpack_from('<I', raw, 0x18)[0]

    # Parse groups
    groups = []
    for g in range(group_count):
        goff = 0x20 + g * 16
        first_id = struct.unpack_from('<i', raw, goff)[0]
        _zero = struct.unpack_from('<i', raw, goff + 4)[0]
        first_string_idx = struct.unpack_from('<i', raw, goff + 8)[0]
        last_id = struct.unpack_from('<i', raw, goff + 0xC)[0]
        groups.append(FMGGroup(
            first_id=first_id,
            first_string_idx=first_string_idx,
            last_id=last_id,
            count=0,  # filled in below
        ))

    # Compute per-group string counts. The next group's first_string_idx
    # is the boundary; for the last group, string_count is.
    for gi, g in enumerate(groups):
        if gi + 1 < len(groups):
            g.count = groups[gi + 1].first_string_idx - g.first_string_idx
        else:
            g.count = string_count - g.first_string_idx
        if g.count < 0:
            raise ValueError(f"FMG group {gi} has negative count {g.count}")

    # Capture bytes in the gap between groups-end and SOTR-start
    groups_end_offset = 0x20 + group_count * 16
    _gap_bytes = bytes(raw[groups_end_offset:string_offsets_table_off])

    # Parse strings indexed by string_idx (not by ID)
    strings_by_idx = {}
    for string_idx in range(string_count):
        sotr_off = string_offsets_table_off + string_idx * 8
        string_off = struct.unpack_from('<Q', raw, sotr_off)[0]
        if string_off == 0:
            strings_by_idx[string_idx] = None  # "no string" — slot is null
            continue
        # Decode UTF-16 LE null-terminated
        j = string_off
        chars = []
        while j < len(raw) - 1:
            c = struct.unpack_from('<H', raw, j)[0]
            if c == 0:
                break
            chars.append(c)
            j += 2
        strings_by_idx[string_idx] = ''.join(chr(c) for c in chars)

    return FMG(
        version=version,
        version_extra=version_extra,
        version_flag=version_flag,
        big_endian=big_endian,
        pad_03=pad_03,
        pad_09=pad_09,
        pad_0a=pad_0a,
        pad_0b=pad_0b,
        groups=groups,
        strings_by_idx=strings_by_idx,
        _gap_bytes=_gap_bytes,
    )


def write_fmg(fmg: FMG) -> bytes:
    """Serialize an FMG to bytes, faithfully reproducing the parsed
    structure. If you parse a vanilla FMG and immediately call write_fmg,
    the output is byte-identical to the input. Splice operations must
    update `fmg.groups` and `fmg.strings_by_idx` consistently before
    calling this.
    """
    if not fmg.groups:
        raise ValueError("cannot write FMG with no groups")

    # Validate group structure: first_string_idx + count of each group
    # must equal next group's first_string_idx.
    for gi in range(len(fmg.groups) - 1):
        prev = fmg.groups[gi]
        nxt = fmg.groups[gi + 1]
        if prev.first_string_idx + prev.count != nxt.first_string_idx:
            raise ValueError(
                f"group {gi+1} first_string_idx {nxt.first_string_idx} "
                f"doesn't follow group {gi} "
                f"(prev.first_str_idx={prev.first_string_idx} + "
                f"prev.count={prev.count})"
            )

    # Total string count = last_group.first_str_idx + last_group.count
    last = fmg.groups[-1]
    string_count = last.first_string_idx + last.count
    group_count = len(fmg.groups)

    # Layout:
    #   0x00..0x20: header
    #   0x20..0x20 + group_count * 16: groups
    #   8-byte mandatory trailer (always present in vanilla, function unclear
    #     but NR's loader appears to require it. Looks like a sentinel /
    #     upper-bound marker — first 4 bytes are typically related to the
    #     highest valid ID in the FMG, last 4 bytes are zero. Empirically
    #     EVERY FMG in vanilla NR has this 8-byte gap between groups-end
    #     and SOTR-start. Without it, NR loader rejects the FMG silently
    #     ("?NpcName?" symptom in-game).)
    #   string_offsets_table: u64 per string (count = string_count)
    #   strings region: UTF-16 LE null-terminated
    groups_end = 0x20 + group_count * 16
    # Empirical rule (verified across every FMG in vanilla NR
    # item_dlc01.msgbnd): gap between groups-end and SOTR-start is
    # ALWAYS exactly 8 bytes. Not more (we tried 16 — NR rejects), not
    # less (zero gap also rejected). The first 4 bytes of the gap
    # appear to be a high-id sentinel/upper-bound marker (e.g.,
    # NpcName: '50 04 5c 36' = 912000080 dec); last 4 bytes are 0.
    # If we have vanilla bytes for this slot, preserve them verbatim;
    # otherwise (purely-new file), zero-fill — but we always emit
    # exactly 8 bytes, never 0 or 16.
    sotr_off = groups_end + 8
    strings_region_start = sotr_off + string_count * 8

    # Build the strings blob in string_idx order.
    string_offsets = []
    strings_blob = bytearray()

    for string_idx in range(string_count):
        text = fmg.strings_by_idx.get(string_idx)
        if text is None:
            string_offsets.append(0)
            continue
        off_in_blob = len(strings_blob)
        string_offsets.append(strings_region_start + off_in_blob)
        strings_blob.extend(text.encode('utf-16-le'))
        strings_blob.extend(b'\x00\x00')  # null terminator

    strings_end = strings_region_start + len(strings_blob)
    # Trailing pad: vanilla pads file_size to 4-byte alignment.
    # (Verified across all 56 FMGs in vanilla NR item_dlc01.msgbnd —
    # fs % 4 == 0 in every case. Not 8, not 16 — just 4.)
    file_size = (strings_end + 3) & ~3

    out = bytearray(file_size)
    # Header
    out[0x00] = 0  # BOM
    out[0x01] = 1 if fmg.big_endian else 0
    out[0x02] = fmg.version
    out[0x03] = fmg.pad_03
    struct.pack_into('<I', out, 0x04, file_size)
    out[0x08] = fmg.version_flag
    out[0x09] = fmg.pad_09
    out[0x0A] = fmg.pad_0a
    out[0x0B] = fmg.pad_0b
    struct.pack_into('<I', out, 0x0C, group_count)
    struct.pack_into('<I', out, 0x10, string_count)
    struct.pack_into('<I', out, 0x14, fmg.version_extra)
    struct.pack_into('<I', out, 0x18, sotr_off)
    struct.pack_into('<I', out, 0x1C, 0)

    # Groups
    for g_idx, g in enumerate(fmg.groups):
        goff = 0x20 + g_idx * 16
        struct.pack_into('<i', out, goff, g.first_id)
        struct.pack_into('<i', out, goff + 4, 0)
        struct.pack_into('<i', out, goff + 8, g.first_string_idx)
        struct.pack_into('<i', out, goff + 0xC, g.last_id)

    # Gap bytes between groups-end and SOTR-start. Vanilla writes some
    # mystery content here (looks like a "phantom group" sentinel that
    # NR doesn't actually read since group_count caps the group walk,
    # but we preserve verbatim for byte-exact round-trip with vanilla).
    # For new files / appended groups, this is zero-filled.
    groups_end = 0x20 + group_count * 16
    gap_size = sotr_off - groups_end
    if gap_size > 0:
        gap = fmg._gap_bytes[:gap_size] if fmg._gap_bytes else b''
        # If preserved gap is shorter than the gap we need to fill,
        # zero-pad. If it's longer, truncate.
        gap = gap + b'\x00' * (gap_size - len(gap))
        out[groups_end:sotr_off] = gap[:gap_size]

    # String offsets table
    for i, off in enumerate(string_offsets):
        struct.pack_into('<Q', out, sotr_off + i * 8, off)

    # Strings blob
    out[strings_region_start:strings_region_start + len(strings_blob)] = strings_blob

    return bytes(out)


def splice_fmg_entries(fmg_bytes: bytes, additions: dict,
                        target_size: int = None) -> bytes:
    """Parse an FMG, merge in `additions` (id -> text), serialize back.

    Splicing semantics (v0.24.x post-loader-investigation):

      For each (id, text) in additions:
        * If id exactly matches an existing group's first_id, overwrite
          the string in that group's first slot. (The runtime lookup
          resolves first_id-matching groups directly when no earlier
          group's claimed range covers the id.)
        * Otherwise, insert a NEW single-slot group at the sorted
          position for `id`, with `last_id == first_id`. Shrink the
          PREVIOUS group's `last_id` to `id - 1` if it was claiming
          this id (vanilla NR groups routinely claim id-ranges up to
          the next group's first_id via the "boundary claim" convention,
          which would otherwise shadow our new entry).

      Before processing any additions, ALL vanilla boundary collisions
      are normalized — i.e., for every pair (group_i, group_i+1) where
      group_i.last_id == group_i+1.first_id, shrink group_i.last_id to
      group_i+1.first_id - 1. This fixes a latent vanilla miswiring
      where ~77 boundary IDs in NpcName.fmg were shadowed by the
      previous group's clamp (e.g. nameid 905_011_000, which by group
      structure should render "Demi-Human Swordmaster", actually
      rendered "Golden Hippopotamus" because group #81's last_id
      claimed 905_011_000 first). Verified in-game by Alaric on a real
      seed: bars passing through reuse_vanilla on a boundary id were
      consistently rendering the previous group's text. Normalization
      fixes all 77 cases — and since the count is derived from
      next_group.first_string_idx (not last_id), no interior IDs of any
      multi-entry group are clipped by the shrink. Confirmed
      empirically: vanilla has zero strict overlaps (last_id > next
      first_id) and zero non-adjacent overlaps, so this is a clean,
      universally-safe rewrite.

    Why no boundary-extension append-at-end mode anymore:
      The legacy implementation appended new groups at the end of the
      groups table. That only preserved sort order when the new ids
      were all > the last existing group's first_id. Worse, it didn't
      break the previous-group boundary claim, so even when sort order
      was technically maintained, the runtime lookup for the new id
      would walk into the previous group's claimed range, clamp to its
      first slot, and never reach the new entry. Verified in-game
      Sunday: this is why every prior splice attempt rendered as
      `?NpcName?` or as the previous group's text.

      The new semantics (sorted insertion + boundary shrink + vanilla-
      boundary normalization) was validated in-game by displaying
      "RANDO TEST BOSS" on a force-patched callsite, and then by a
      real seed where bars driven by both reuse_vanilla and fresh-
      allocated nameids resolved correctly.

    Lookup model the runtime appears to use:
      Linear scan through groups (sorted by first_id). Find the FIRST
      group where `first_id <= nameid <= last_id` (inclusive on both
      ends). Slot = first_string_idx + min(nameid - first_id, count - 1)
      where count is the next group's first_string_idx minus this one's
      (or strings_count - first_string_idx for the last group). Vanilla
      uses the wide-claim convention (last_id == next.first_id) but
      never references boundary ids from EMEVD, so the ambiguity is
      harmless in stock NR. Mods that DO reference boundary ids (MMV,
      or the rando's reuse_vanilla path) get the wrong text. To make
      boundary IDs reachable by their first_id group, the previous
      group's claim must end strictly below the boundary.

    `target_size`: if specified, pad to exactly this size; error if
    output would exceed it.
    """
    fmg = parse_fmg(fmg_bytes)

    # Pre-pass: normalize vanilla boundary collisions.
    # For every adjacent pair where group_i.last_id == group_i+1.first_id,
    # shrink group_i.last_id by 1 so group_i+1 wins the lookup for its
    # own first_id. Vanilla NR's count-derived-from-next-fsi invariant
    # means this never affects interior lookups of multi-entry groups
    # (the slot offset is bounded by count - 1, which depends on
    # first_string_idx, not last_id).
    #
    # Guard: never shrink to a value below the group's own first_id —
    # that would violate the `last_id >= first_id` invariant and may
    # cause NR's loader to misinterpret the field as a wrap-around u32.
    # The only group in vanilla NR base NpcName where this matters is
    # the degenerate g#0 (first_id=0, last_id=0) — both vanilla g#0 and
    # g#1 declare first_id=0, which is its own quirk. We leave g#0's
    # last_id at 0 and let g#0 keep claiming nameid 0; vanilla EMEVDs
    # don't reference nameid 0 anyway.
    for i in range(len(fmg.groups) - 1):
        cur = fmg.groups[i]
        nxt = fmg.groups[i+1]
        if cur.last_id == nxt.first_id and nxt.first_id - 1 >= cur.first_id:
            cur.last_id = nxt.first_id - 1

    # Process additions in ascending id order. This keeps the
    # insertion logic monotonic — each new group lands at or after the
    # position the previous iteration left things in, so the
    # `insert_idx > 0` cases compose cleanly.
    for id_ in sorted(additions.keys()):
        text = additions[id_]

        # Case 1: exact first_id match → overwrite that group's first
        # slot text in place. No structural change needed.
        exact_match = next(
            (g for g in fmg.groups if g.first_id == id_), None
        )
        if exact_match is not None:
            fmg.strings_by_idx[exact_match.first_string_idx] = text
            continue

        # Case 2: new id. Find sorted insertion position.
        insert_idx = next(
            (gi for gi, g in enumerate(fmg.groups) if g.first_id > id_),
            len(fmg.groups),
        )

        # Break the previous group's boundary claim if it extends over
        # the new id. Only shrink — never grow last_id beyond what
        # vanilla had.
        if insert_idx > 0:
            prev = fmg.groups[insert_idx - 1]
            if prev.last_id >= id_:
                prev.last_id = id_ - 1

        # Compute the string slot for the new entry. If we're inserting
        # in the middle, the new slot is whatever index the next group
        # currently starts at; downstream groups shift forward by 1,
        # and existing strings at slot >= new_slot shift up by 1.
        if insert_idx < len(fmg.groups):
            new_slot = fmg.groups[insert_idx].first_string_idx
            for g in fmg.groups[insert_idx:]:
                g.first_string_idx += 1
            # Iterate in descending order so we don't clobber values
            # we haven't moved yet.
            old_keys = sorted(
                (k for k in fmg.strings_by_idx if k >= new_slot),
                reverse=True,
            )
            for k in old_keys:
                fmg.strings_by_idx[k + 1] = fmg.strings_by_idx.pop(k)
        else:
            # Appending past the last group (id > all existing first_ids).
            if fmg.groups:
                last = fmg.groups[-1]
                new_slot = last.first_string_idx + last.count
            else:
                new_slot = 0

        # Single-slot group with tight last_id == first_id. We
        # deliberately do NOT use the wide-claim convention here: the
        # next splice (or vanilla group) covers anything past `id_`.
        fmg.groups.insert(insert_idx, FMGGroup(
            first_id=id_,
            first_string_idx=new_slot,
            last_id=id_,
            count=1,
        ))
        fmg.strings_by_idx[new_slot] = text

    out = write_fmg(fmg)
    if target_size is not None:
        if len(out) > target_size:
            raise ValueError(
                f"spliced FMG size {len(out)} exceeds target_size {target_size}"
            )
        if len(out) < target_size:
            out = out + b'\x00' * (target_size - len(out))
    return out