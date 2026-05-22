# Reference binaries — ground-truth file format examples

Vanilla NR files shipped with the rando so the next time someone
(human or AI) needs to reason about file formats, they reach for these
**before** guessing at byte layouts from memory or public docs.

## Lesson behind this directory

v0.24.0 through v0.24.3 of the healthbar patcher worked on speculative
Sekiro+ EMEVD header layouts. Four iterations:

  v0.24.0  hardcoded INSTRUCTION_RECORD_SIZE=32; 42 silent parse crashes
  v0.24.1  better Step 4 diagnostics, distinguished failure states
  v0.24.2  auto-detected record sizes via offset chain math
  v0.24.3  pivot to byte-scan over args region; still 0 callsites
           found because args_offset itself was wrong

Then Alaric uploaded one decompressed m48_50_00_00.emevd, I hex-dumped
the first 0x90 bytes, and the actual field positions were obvious:
parameter_count/parameter_offset live at 0x50/0x58 (which I was
calling args_size/args_offset), and args_size/args_offset are at
0x70/0x78 (which I was calling strings_size/strings_offset). Every
field shifted by one slot.

Total iterations to fix once I had real bytes: 1. Total iterations
spent on the wrong layout before that: 4. So:

**Ground-truth file in the repo > format docs from memory.**

## Files

- `m48_50_00_00.emevd` — Tree Sentinel arena vanilla, 12,768 bytes,
  decompressed (post-DCX-Krak). The canonical healthbar test case:
  - One InitializeCommonEvent(0, 90015023, ...) call that produces
    3 healthbar callsites (one shared-bar + two singles).
  - Used by `healthbar_inplace/inspect_emevd.py` and as the auto-
    diagnostic probe target in dcx_batch's Step 4.
- `m48_50_00_00.emevd.dcx.js` — DSAS3 decompile of the same file.
  Lets you cross-check the structural decode against bytes.

Reference values from this file (cross-checked between binary parser
and .js audit, byte for byte):
  - args region: 0x1d40 .. 0x28c0 (2,944 bytes)
  - handler 90015023 at byte 0x20c8
  - 3 healthbar callsites:
      group 0  nameId=903250600  chr=[48505800, 48500800]
      group 1  nameId=904351000  chr=[48500810]
      group 2  nameId=904351000  chr=[48500820]
  - 9 events, 216 instructions, 67 parameters, 2 linked files,
    176 bytes strings

## Convention going forward

When format work is needed, the workflow is:

  1. Hex-dump the relevant section of `reference/m48_50_00_00.emevd`
     (or whatever other binary lives here). `xxd` or
     `python -c "print(open('reference/m48_50_00_00.emevd','rb')
       .read(0x100).hex())"` is enough.
  2. Cross-check parser output against the .js decompile in the same
     directory — they should agree byte-for-byte.
  3. Only after that does speculation about field offsets earn its
     keep.

If someone needs an MSB reference, drop one in here too with the same
naming pattern: `<map>.msb` (raw, post-DCX) + ideally a metadata
README entry listing what it contains.

## MSB reference (added v0.24.6)

- `m60_45_37_20.msb` — Limveld overworld tile, vanilla, post-DCX
  decompressed, 951,832 bytes. Magic `b'MSB '` (with trailing space).
  An overworld tile (not a boss arena), so it complements the
  m48_50 EMEVD with different content shape: many Part entries,
  walk_routes, regions, layered Parts groupings.

If you need to reason about MSB byte layout — Part record sizes,
walk_route serialization, region offsets, etc. — hex-dump this
before reaching for memory or external docs. Same convention as
the EMEVD: real bytes first, speculation last.

## NpcName.fmg reference (added v0.24.7)

- `NpcName.fmg` — engUS boss/NPC name FMG version 2, 13,096 bytes,
  extracted from the engUS Item bundle
  `Data0_15912862698882586866.fmg.bnd`. Contains every boss-name
  entry the healthbar engine looks up via the nameId arg in
  90015023/0/7/21/26/406 callsites.

  BND container layout reference values for the engUS bundle:
    - magic `BND4`, header 0x40 bytes
    - 56 entries × 36 bytes each (per_entry_size at header +0x20)
    - entry layout: flags(u32) + sentinel(i32=-1) + csize(u64) +
      dsize(u64) + data_offset(u32, ABSOLUTE) + fmg_id(u32) +
      name_offset(u32)
    - NpcName entry: fmg_id=18, data_offset=0x36400, size=13096
    - name path inside BND:
      `W:\CL\data\Target\INTERROOT_win64\msg\engUS\NpcName.fmg`
    - hash table region 0x2410..0x2634 (300+ bytes) after name strings;
      must be preserved verbatim for the game to find entries by name

If you ever need to redo the FMG splice work, hex-dump this file +
the full bundle and confirm the parser output against these reference
values before changing anything.

**The bundle itself (Data0_15912862698882586866.fmg.bnd) is not
shipped in the repo** — it's user-provided content from their own
game install, configured via a GUI path setter at v0.24.8. The
NpcName.fmg standalone file is small enough (13KB) to ship as a
content-spec example.
