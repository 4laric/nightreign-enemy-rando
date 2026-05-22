"""bnd_splice_driver.py — high-level orchestration for splicing FMG
additions into a NR engUS Item bundle.

Workflow:
  1. Read user's vanilla `<bundle>.fmg.bnd` from disk
  2. Parse the BND, locate NpcName.fmg entry by name suffix
  3. Splice the supplied (nameId -> text) dict into the FMG
  4. Repack: append the new FMG bytes at end of file via the BND
     writer's relocation mechanism, keeping the rest of the bundle
     verbatim
  5. Write the modified BND bytes to the mod folder

The relocation strategy means:
  - Total file grows by the size of the new NpcName.fmg (~13KB +
    ~3KB additions = ~16KB total, vs ~13KB original).
  - Original NpcName slot in the data section becomes dead bytes
    the game won't read.
  - BND4 hash table remains valid because we don't change any name
    strings, only the data_offset and sizes for one entry.
  - All other entries (WeaponName.fmg, GoodsName.fmg, etc.) are
    untouched.

If the relocation invariant ever breaks (game refuses to load the
patched bundle), the fallback is to also try with the relocation at
the end-of-original-data-section (before any non-data trailing bytes),
or to switch to fresh-layout BND writing. We'll cross that bridge
when in-game testing tells us we have a problem.
"""

from .bnd import parse_bnd4, write_bnd4
from .fmg import splice_fmg_entries


# Name suffix matches across all the BND's internal Sekiro-style
# Windows path naming — the entry path inside the BND is like
# `W:\CL\data\Target\INTERROOT_win64\msg\engUS\NpcName.fmg`.
NPCNAME_SUFFIX = 'NpcName.fmg'

DCX_MAGIC = b'DCX\x00'


def splice_npcname_into_bundle_file(file_bytes: bytes, name_additions: dict,
                                     oodle=None) -> bytes:
    """DCX-aware splice. Detects DCX-wrapping on the input, decompresses
    via the dcx.py helper if needed, runs the splice, recompresses if
    the input was wrapped.

    `file_bytes`: raw contents of a .msgbnd / .msgbnd.dcx / .fmg.bnd file
    `name_additions`: {nameId(int): name_text(str)}
    `oodle`: optional `dcx._Oodle` instance; if None, dcx.py will
             attempt to locate Oodle via the default search (typically
             `oo2core_*.dll` in the same dir as oodle wrappers).

    Returns: raw bytes ready to write back to disk. If input was DCX,
    output is also DCX-wrapped at the same compression level so it
    can be dropped in at the same logical path under me3.

    Importing dcx.py is deferred to this function so the splice module
    stays importable without Oodle being present (e.g., during test
    runs of the GUI on machines without the user's game install).
    """
    was_dcx = file_bytes[:4] == DCX_MAGIC
    input_compression = b'KRAK'  # default (overridden if DCX)
    input_level = 6
    if was_dcx:
        # v0.24.111-Sunday: capture the input's compression type and
        # level so we can round-trip them on the output. NR's item_dlc01
        # ships as DFLT (deflate), not KRAK. Hardcoding KRAK on output
        # produces files NR's loader rejects (symptom: "?NpcName?" in
        # healthbars in-game). Determined by byte-diffing UXM-unpacked
        # vanilla against Yabber-roundtripped vanilla — same bug.
        import struct
        input_compression = file_bytes[0x28:0x2c]
        input_level = file_bytes[0x30]
        # Late import — dcx.py needs Oodle for KRAK decompression,
        # which only works on systems with the user's game DLL.
        import sys
        import os
        # Ensure dcx.py's directory is on sys.path
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if here not in sys.path:
            sys.path.insert(0, here)
        from dcx import DCX
        raw_bnd = DCX.decompress_bytes(file_bytes, oodle)
        # v0.24.12: log post-decompress state so we can diagnose
        # bundles where KRAK decompresses to something that isn't a
        # BND4 (encrypted payload? wrong file? game-version mismatch?).
        # The Alaric v0.24.11 failure: 'not a BND4 file (magic
        # A\\x95\\xbdK)' came from this exact path with no context.
        if raw_bnd[:4] != b'BND4':
            print(f"  WARN: DCX decompressed but result is NOT BND4")
            print(f"  Decompressed size: {len(raw_bnd):,} bytes "
                  f"(DCX header advertised same)")
            print(f"  First 64 bytes of decompressed content:")
            print(f"    {raw_bnd[:64].hex(' ')}")
            print(f"  This usually means one of:")
            print(f"    1. The file has an additional encryption layer "
                  f"that UXM didn't strip")
            print(f"    2. The file isn't the Item bundle — discovery may "
                  f"have picked the wrong target")
            print(f"    3. NR uses a new container format we don't handle "
                  f"yet")
    else:
        raw_bnd = file_bytes

    spliced_bnd = splice_npcname_into_bundle(raw_bnd, name_additions)

    if was_dcx:
        from dcx import DCX
        print(f"  Re-wrapping output as DCX ({input_compression!r}, "
              f"level {input_level}) to match input")
        return DCX.compress_bytes(spliced_bnd, compression=input_compression,
                                  level=input_level, oodle=oodle)
    return spliced_bnd


def splice_npcname_into_bundle(bundle_bytes: bytes, name_additions: dict) -> bytes:
    """Read a fmg.bnd bundle, splice name_additions into its
    NpcName.fmg, and return the new bundle bytes.

    NpcName.fmg AND NpcName_dlc01.fmg both get boundary-normalization
    applied (splice_fmg_entries' pre-pass that shrinks vanilla's
    boundary-collision last_id values by 1, fixing latent miswirings
    where nameid X was shadowed by the previous group's wide claim).
    The DLC FMG is normalized with empty additions — we don't splice
    new entries there, just fix vanilla's latent bugs so the runtime's
    cross-FMG lookup resolves DLC nameids correctly.

    Discovered Sunday: NR's healthbar runtime resolves nameids against
    both FMGs. Catalog reuse_vanilla can return a DLC nameid (e.g.
    904_811_000 = "Omenkillers" by group structure), but DLC has 51
    boundary collisions of its own — without normalization, that
    lookup renders the previous group's text ("Putrid Avatar" in the
    Omenkiller case). The fix is identical to the base FMG case;
    we just hadn't been touching the DLC FMG at all.

    `name_additions`: dict mapping nameId (int) -> name text (str).
    Each entry will appear in the patched base NpcName FMG at the
    specified ID. Existing IDs are overwritten.

    Raises ValueError if the bundle doesn't contain NpcName.fmg
    (which means the user gave us the wrong msgbnd — log message,
    fail loud, let the caller report a useful error).
    """
    bnd = parse_bnd4(bundle_bytes)

    # Locate both FMGs. Base is required; DLC is optional (silently
    # skipped if absent — older NR builds may not have it). Matcher is
    # 'NpcName' in basename + .fmg extension, so it catches both
    # 'NpcName.fmg' and 'NpcName_dlc01.fmg'.
    npcname_entry = None
    npcname_dlc_entry = None
    for e in bnd.entries:
        basename = e.name.split('\\')[-1]
        if not basename.endswith('.fmg'):
            continue
        if 'NpcName' not in basename:
            continue
        if 'dlc' in basename.lower():
            npcname_dlc_entry = e
        else:
            npcname_entry = e
    if npcname_entry is None:
        names = ', '.join(e.name.split('\\')[-1] for e in bnd.entries[:10])
        raise ValueError(
            f"bundle has no NpcName.fmg entry — first entries are: {names}... "
            f"Are you sure this is the engUS Item bundle "
            f"(file size ~2.4MB, contains 56 entries including NpcName, "
            f"WeaponName, GoodsName, etc.)?"
        )

    original_fmg_bytes = npcname_entry.data
    new_fmg_bytes = splice_fmg_entries(original_fmg_bytes, name_additions)

    # Normalize DLC FMG boundaries — empty additions, just runs the
    # pre-pass that shrinks last_id values for boundary collisions.
    dlc_grew = False
    if npcname_dlc_entry is not None:
        original_dlc_bytes = npcname_dlc_entry.data
        new_dlc_bytes = splice_fmg_entries(original_dlc_bytes, {})
        # The pre-pass only modifies u32 values inside group records.
        # Group count and string count are unchanged; total size is
        # unchanged. Sanity-check that invariant before writing.
        if len(new_dlc_bytes) != len(original_dlc_bytes):
            # Unexpected — boundary normalization shouldn't change size.
            # Bail rather than silently corrupting the bundle.
            raise ValueError(
                f"DLC FMG normalization produced size change: "
                f"{len(original_dlc_bytes)} -> {len(new_dlc_bytes)}. "
                f"This is a bug — investigate before shipping."
            )
        npcname_dlc_entry.data = new_dlc_bytes

    # v0.24.111: prefer in-place overwrite when the new FMG fits in the
    # original slot. Previous versions always relocated via append-at-end,
    # which is structurally correct per BND4 spec (entry data_off updated
    # to point at appended region, vanilla bytes left as dead data) but
    # NR's loader refuses to load such files — symptom was "?NpcName?"
    # in-game despite parser-verified valid output. Whether NR rejects
    # because it validates monotonic data offsets, file_table_size bound,
    # or some other invariant is unknown — but in-place overwrite produces
    # a byte-layout-identical structure to vanilla, sidestepping the issue.
    #
    # In-place is viable when new_fmg_bytes fits in the original slot.
    # NpcName splice empirically produces same-size output because: (a)
    # NR's vanilla NpcName.fmg has many empty entries (697 total, 271
    # non-empty) — splice fills empty slots without resizing the FMG;
    # (b) splice_fmg_entries preserves the FMG's overall byte size when
    # all additions fit at existing-but-empty IDs.
    #
    # If size DOES grow (large-batch splice that exhausts empty slots),
    # fall back to relocations and accept whatever NR does with the file.
    if len(new_fmg_bytes) <= len(original_fmg_bytes):
        # Best case: new content fits in the original slot. In-place
        # overwrite — write_bnd4's non-repack path handles this.
        npcname_entry.data = new_fmg_bytes
        return write_bnd4(bnd, original_raw=bundle_bytes)

    # New FMG is larger than the original slot. We have to grow the
    # bundle. v0.24.111 (Sunday): use the proper repack path. The old
    # relocation-append path (append new FMG bytes at end of file +
    # update entry data_off to point there) produces a file NR's
    # loader REJECTS — confirmed by ~8 hours of debugging Sat/Sun.
    # The repack path lays out all entries contiguously with the new
    # NpcName.fmg expanded in its original position; subsequent entries
    # shift forward by the growth amount. This mirrors vanilla BND4
    # layout and NR's loader accepts it.
    npcname_entry.data = new_fmg_bytes
    return write_bnd4(bnd, original_raw=bundle_bytes, repack=True)


def get_existing_npcname_ids(bundle_bytes: bytes) -> set:
    """Returns the set of IDs that currently have a non-empty name
    in the bundle's NpcName.fmg. Useful for the EMEVD patcher to
    pick nameIds that don't conflict with existing entries (or to
    deliberately reuse them, depending on the strategy)."""
    from .fmg import parse_fmg
    bnd = parse_bnd4(bundle_bytes)
    npcname_entry = next(
        (e for e in bnd.entries if e.name.endswith(NPCNAME_SUFFIX) and 'dlc' not in e.name.lower()),
        None,
    )
    if npcname_entry is None:
        return set()
    fmg = parse_fmg(npcname_entry.data)
    return {id_ for id_, text in fmg.entries.items() if text}
