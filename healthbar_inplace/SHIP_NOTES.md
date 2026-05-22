# healthbar_inplace — ship notes

v0.24.0-dev development snapshot. Built during the in-transit work
session while waiting on Alaric to upload decompressed `.emevd` files.

## What was built

A complete Sekiro/ER/AC6/NR EMEVD binary parser and healthbar-nameId
in-place patcher. No DarkScript3 dependency. Inputs are raw `.emevd`
bytes (post-DCX-decompression); outputs are patched `.emevd` bytes
ready for DCX recompression via the project's existing `dcx.py`.

```
emevd.py             Sekiro+ EMEVD binary parser. Header + events +
                     instructions + args. Extracts healthbar callsites
                     by InitializeCommonEvent handler ID. Provides
                     byte-level rewrite primitives.

synth.py             Synthetic EMEVD generator for parser tests.
                     Builds valid (per our spec) EMEVD bytes from
                     a Python dict of event specs.

oracle.py            Parses DSAS3-decompiled .js files to extract
                     ground-truth healthbar callsite data. The cross-
                     check oracle for verifying the binary parser.

verify.py            Cross-checks binary parse vs .js oracle. The
                     pass/fail gate for shipping the parser.

rewriter.py          Decision policy: spoiler + chr-to-nameId catalog
                     -> per-callsite nameId decisions (reuse_vanilla /
                     fresh_allocation / heterogeneous_squad / unchanged).
                     Computes byte-offset edits ready for rewrite_many.

pipeline.py          End-to-end runner: spoiler.json + me3 event/ dir
                     -> patched event/ dir + fmg_additions.json +
                     apply_report.json. Single entry point for the
                     GUI checkbox.

gui_hook_design.py   Design + stub code for the oops_rando_gui.py
                     integration. Checkbox-first; curation tab as v0.24
                     follow-up.

tests/test_roundtrip.py   11 parser/synth round-trip tests, all pass
tests/test_rewriter.py    6 decision-policy tests, all pass

RUNBOOK_when_emevd_arrives.md
                     Step-by-step verification + ship checklist for
                     when the decompressed .emevd files land.
```

## What's verified

- **Parser internal consistency**: synthetic EMEVD bytes round-trip
  through the parser. Every healthbar handler (90015000/007/021/023/
  026/406) extracts correctly. Shared-bar 90015023 produces three
  name groups per call as expected.
- **Decision policy**: all four branches (reuse_vanilla, fresh_allocation,
  heterogeneous_squad, unchanged) exercise correctly with synthetic
  spoiler data.
- **Byte-level rewrite**: end-to-end test builds EMEVD, finds a
  callsite, rewrites its nameId in bytes, reparses, confirms the new
  value round-trips.
- **Bounds checking**: parser rejects bad magic, short files, and
  corrupt table offsets with structured exceptions.
- **.js oracle**: tested against the real DSAS3-decompiled .js files
  shipping in `patched_emevd/`. Correctly extracts 3 callsites from
  m48_50, 5 from m38_10, etc. Total 13 callsites across the 6 .js
  files in the repo.

## What's NOT verified yet (needs binary files)

- **Real EMEVD bytes parse**: the parser's header layout and per-
  record sizes are inferred from public SoulsFormats knowledge. The
  exact byte offsets I read for the header fields (event_count at
  0x10, instruction_count at 0x20, etc.) need confirmation against
  actual NR `.emevd` bytes. Most likely failure modes:
    1. Padding bytes I'm not accounting for (e.g. between magic and
       file_size). Header size might be 0x88 or 0x90 instead of 0x94.
    2. Event-layer-mask vs args-section ordering — I put args after
       event-layers; if they're swapped, the args_offset computation
       in synth.py is wrong but the parser would still work on real
       files (it follows the explicit offsets in the header).
    3. Instruction record size — I'm using 32 bytes (the long Sekiro+
       variant). If NR uses a 24-byte variant, the parser will
       read garbage past the first instruction. Easy to spot — the
       second instruction's `class` field would be a giant random
       value.
- **Cross-check passes**: verify.py needs the binary files to run
  against. Once it does, a clean PASS on m48_50 + m49_25 means we
  can ship.
- **Full corpus coverage**: build_offsets_manifest.py walks the whole
  vanilla NR EMEVD set and produces the offsets manifest. Not yet
  written (~20 lines, trivial; deferred until after parser
  verification).

## What's broken in adjacent code (worth fixing during this work)

`apply_healthbar_names.py` ships with `DEFAULT_FMG_ID_BASE = 9700000000`
(10-digit, 9.7B). That exceeds uint32 (max 4.29B), so any fresh
allocation past `4_294_967_295 - 9_700_000_000` is a negative number
mod 2^32, which would write garbage into the EMEVD args region and
display blank/garbage healthbar text in-game.

The current demo workflow probably never hit this in practice because
all the demos so far have been small enough to fit under uint32 if
counted from 9_700_000_000... no wait, 9.7B alone is over 2^32, so
the very FIRST fresh allocation already overflows.

Verify by reading the current allocator: `_build_fmg_id_allocator`
in apply_healthbar_names.py. If it stores nameIds as-is into the .js,
then DSAS3 might be silently truncating on recompile, OR the .js
rewrite path was never actually exercised for fresh allocations in
production demos (only reuse_vanilla path).

My `rewriter.py` uses `DEFAULT_FMG_ID_BASE = 970_000_000` (9-digit,
under 1B) which fits in uint32 with plenty of headroom. Recommend
fixing apply_healthbar_names.py to match. Backward compat is fine —
the old script generates name_table.json with the old base; the new
script doesn't read that, it reads spoiler + catalog directly.

Filed as a v0.24.0 housekeeping item.

## v0.24 follow-ups

- **FMG binary patcher**: today the pipeline emits `fmg_additions.json`
  and the user has to import it manually into a boss-name FMG via
  WitchyBND. With the same binary-format-parser approach used for
  EMEVD, we can ship an FMG patcher that does this step too. Adds the
  N new (nameId, text) entries to whichever FMG holds boss names and
  emits the patched FMG ready to drop in. Then the "Rewrite boss
  healthbars" checkbox is truly one-click — no FMG editor required.
- **Curation tab**: per `gui_hook_design.py`, the "Healthbar Names"
  tab where you can override each callsite's auto-name with a
  custom string before applying. Power-user / demo-prep feature.
  CLI flow (`healthbar_tools/`) still works for batch curation.
- **Per-NR-patch offsets manifest**: ship `healthbar_callsite_offsets.json`
  as a committed data file, regenerated when NR's vanilla EMEVD
  changes. Saves a parse pass at pipeline runtime — the patcher
  only needs to read the offsets manifest and rewrite specific bytes,
  no EMEVD parse needed at runtime. Optimization, not correctness.
- **Direct-spawn entity support**: EMEVD-direct-spawn entities (the
  castle basement Red Wolf case, mentioned in DEMO_PREP.md) don't
  appear in the spoiler so their healthbar nameIds can't be rewritten
  by this pipeline. Same limitation as the .js patcher.

## Format-spec confidence levels (for posterity if header layout
needs adjustment)

| Field / structure | Confidence | If wrong, fix where |
|---|---|---|
| Magic "EVD\\0" at +0x00 | high (universal) | n/a |
| Version flags at +0x04 (4 bytes) | high | emevd.VERSION_FLAGS_SEKIRO_PLUS |
| file_size u32 at +0x08 | high | Header.parse |
| event_count u64 at +0x10 (Sekiro+ long) | medium | Header.parse offsets |
| Header total size 0x94 | medium | Header.HEADER_SIZE |
| Event record 48 bytes | high | Header.EVENT_RECORD_SIZE |
| Instruction record 32 bytes (Sekiro+) | medium-high | Header.INSTRUCTION_RECORD_SIZE |
| InitializeCommonEvent = class 2000, idx 0 | high (stable since BB) | INSTRUCTION_INITIALIZE_COMMON_EVENT |
| Args layout: u32[slot, common_event_id, params...] | high | extract_healthbar_callsites |
| HEALTHBAR_HANDLER_SCHEMAS arg positions | very high (verified against .js oracle) | n/a |

The medium-confidence ones are the only things that could shift when
the binary arrives. All fixes are localized; the rest of the package
is independent of them.
