# healthbar_inplace — in-place healthbar nameId patcher

**v0.24.0-dev draft.** Bumps to v0.24.0 on next rando update.

**Goal:** make healthbar nameIds match swapped chrs without needing
a DarkScript3 round-trip per rando run. DSAS3 is Windows-only and
heavy; this package is pure Python and slots into the existing
`dcx_batch.py` Oodle pipeline -- same Oodle calls the MSB pass uses,
just with `.emevd.dcx` extensions.

## Integration shape

`dcx.py` and `dcx_batch.py` already ship Oodle in production for the
MSB pipeline. DCX is format-agnostic (any Kraken-compressed FromSoft
binary), so EMEVD support is two sister functions plus a single
pipeline-pass call:

```
dcx_batch.rando_pipeline (existing):
    decompress_dir              .msb.dcx -> .msb
    [MSB shuffle in tmp]
    compress_dir                .msb -> .msb.dcx

dcx_batch.rando_pipeline (v0.24.0, with --rewrite-healthbars):
    [existing MSB flow as above]
    emevd_decompress_dir        .emevd.dcx -> .emevd        <- new sister
    healthbar_inplace.pipeline.apply_to_dir  (byte editor)  <- new pass
    emevd_compress_dir          .emevd -> .emevd.dcx        <- new sister
```

Paste-target code for the three additions is in
`dcx_batch_integration.py`.

## Package layout

```
emevd.py             Sekiro+ EMEVD binary parser.

synth.py             Synthetic EMEVD generator for parser tests.

oracle.py            Parses DSAS3-decompiled .js files for ground-
                     truth callsite data. Verified working on real
                     .js files in patched_emevd/ (13 callsites
                     across 6 files).

verify.py            Joins binary parse vs .js oracle, reports
                     nameId mismatches. Pass/fail gate for shipping.

rewriter.py          Decision policy: spoiler + catalog -> per-
                     callsite nameId decisions. DEFAULT_FMG_ID_BASE
                     = 970M (fits uint32; fixes the 9.7B overflow
                     in apply_healthbar_names.py).

pipeline.py          Pure byte editor. apply_to_dir() walks .emevd
                     files in a dir, applies edits, writes patched
                     .emevd files + fmg_additions.json + report.
                     Caller (dcx_batch) does the .dcx wrap/unwrap.

dcx_batch_integration.py
                     Paste-target code: emevd_decompress_dir,
                     emevd_compress_dir, rando_pipeline hook, CLI
                     flag, open questions.

gui_hook_design.py   oops_rando_gui.py integration sketch.

inspect_emevd.py     One-shot debug tool.

tests/               17 unit tests, all green.
```

## Status

| Component | Status |
|---|---|
| Parser | Built. Internally consistent. Real-EMEVD format-spec validation pending upload. |
| Oracle | Built. Verified on real .js files. |
| Verifier | Built. Awaiting real .emevd to run against the .js oracle. |
| Rewriter | Built. All 4 decision branches tested. |
| Pipeline | Built. Pure byte editor; dcx_batch is the caller. |
| dcx_batch integration sketch | Drafted (paste-target). |
| GUI hook | Drafted (paste-target). |
| Tests | 17 / 17 passing. |
| Offsets manifest builder | Pending -- trivial once parser verified. |
| FMG binary patcher | v0.24.x follow-up. |
| Curation tab | v0.24.x follow-up. |

## Next step

Drop three decompressed `.emevd` files (post-DCX, pre-DSAS3):

1. **m48_50_00_00.emevd** or **m49_25_00_00.emevd**  -- has shared-bar
   90015023 (trickiest schema)
2. **common_func.emevd**  -- big-file sanity check
3. **m38_10_00_00.emevd** or **m30_30_00_00.emevd**  -- we already
   have .js oracles for both

Then I run:

```
python inspect_emevd.py m48_50_00_00.emevd \
    ../patched_emevd/timeout_v1/applied/m48_50_00_00.emevd.dcx.js
```

PASS on m48_50 + one other -> parser verified, ship v0.24.0.

FAIL -> inspector prints the byte offset where the format-spec
assumption broke; fix is localized to `emevd.Header.parse` and re-
verify.

See `RUNBOOK_when_emevd_arrives.md` for step-by-step.
See `SHIP_NOTES.md` for per-field format-spec confidence.
See `dcx_batch_integration.py` for the integration code.
See `gui_hook_design.py` for the UI checkbox sketch.

## Quick sanity check (no real files required)

```
cd tests
python test_roundtrip.py
python test_rewriter.py
```

Both should print all green.
