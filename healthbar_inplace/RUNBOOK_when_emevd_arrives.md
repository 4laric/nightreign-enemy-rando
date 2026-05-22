# When the binary EMEVD files arrive — runbook

v0.24.0-dev, healthbar in-place patcher.

This is the moment-of-truth checklist for verifying the parser and
shipping the feature. Everything in `healthbar_inplace/` is built and
tested against synthetic EMEVD bytes; the only thing not yet verified
is that real NR `.emevd` bytes parse the same way the synthetic ones do.

## Step 1 — Decompress the .emevd.dcx files

On the Windows box, with Oodle available:

```
python -c "from dcx import DCX; DCX.decompress_file('common_func.emevd.dcx', 'common_func.emevd')"
python -c "from dcx import DCX; DCX.decompress_file('m48_50_00_00.emevd.dcx', 'm48_50_00_00.emevd')"
python -c "from dcx import DCX; DCX.decompress_file('m38_00_00_00.emevd.dcx', 'm38_00_00_00.emevd')"
```

Or use the project's dcx.py CLI:

```
python dcx.py decompress common_func.emevd.dcx common_func.emevd
```

Upload the three resulting `.emevd` files (uncompressed binary).

## Step 2 — Sanity check parser parses

```
cd healthbar_inplace
python -c "
from emevd import EMEVD, extract_healthbar_callsites
raw = open('/path/to/m48_50_00_00.emevd', 'rb').read()
parsed = EMEVD.parse(raw)
print(f'events={parsed.header.event_count} instructions={parsed.header.instruction_count}')
callsites = extract_healthbar_callsites(parsed)
print(f'{len(callsites)} healthbar callsites')
for c in callsites[:5]:
    print(f'  event={c.event_id} handler={c.handler_id} nameId={c.name_id} chr={c.chr_entity_ids}')
"
```

Expected output for m48_50 (Tree Sentinel + 2× Royal Cavalryman):
- 3 healthbar callsites from one 90015023 (the shared bar)
- nameId 903251600 for group 0 (the Tree Sentinel)
- nameId 904351000 for groups 1, 2 (the two Cavalrymen)
- chr ids 48500800/810/820 across the three groups

If `EMEVD.parse` raises `UnsupportedVariantError` or `CorruptOffsetError`,
the header layout assumptions need fixing. Most likely culprit: the
version flags don't match my pattern, or the per-record sizes are
different in NR than in Sekiro/ER. Look at the first 0x94 bytes
manually with a hex dump to confirm.

## Step 3 — Cross-check against the .js oracle

For each binary file, point verify.py at it and its DSAS3 .js sibling:

```
python verify.py m48_50_00_00.emevd ../patched_emevd/timeout_v1/applied/m48_50_00_00.emevd.dcx.js
python verify.py m38_00_00_00.emevd ../patched_emevd/m38_10_00_00.emevd.dcx.js   # closest analog we have
```

Wait, m38_00 vs m38_10 — those are different maps. Better targets for
the .js oracle cross-check are the maps we have .js files for:

| binary needed | .js oracle available |
|---|---|
| common_func.emevd | patched_emevd/common_func.emevd.dcx.js |
| m48_50_00_00.emevd | patched_emevd/timeout_v1/applied/m48_50_00_00.emevd.dcx.js |
| m48_60_00_00.emevd | patched_emevd/timeout_v1/applied/m48_60_00_00.emevd.dcx.js |
| m49_25_00_00.emevd | patched_emevd/timeout_v1/applied/m49_25_00_00.emevd.dcx.js |
| m49_28_00_00.emevd | patched_emevd/timeout_v1/applied/m49_28_00_00.emevd.dcx.js |
| m38_10_00_00.emevd | patched_emevd/m38_10_00_00.emevd.dcx.js |
| m30_30_00_00.emevd | patched_emevd/m30_30_00_00.emevd.dcx.js |
| m60_43_37_00.emevd | patched_emevd/m60_43_37_00.emevd.dcx.js |

If the verifier reports `PASS` on at least three of those (including
m48_50 or m49_25 which have shared-bar 90015023 calls — the trickiest
schema), the parser is trustworthy.

If it reports `FAIL` with `ONLY IN ORACLE` or `ONLY IN BINARY` keys,
the (handler_id, event_id, chr_entity_ids) join key is mis-extracted
on one side. Look at the .js source line for the missing/extra entry
and inspect the binary at the inferred byte offset to figure out which
side is wrong.

If it reports `FAIL` with `NAMEID MISMATCHES`, the byte offset math is
off by some constant — the most likely culprit is the args region
addressing (the +8 bytes for slot+common_event_id at the start of
InitializeCommonEvent args). Check by reading the bytes at the offset
the verifier claims vs the actual nameId from the .js.

## Step 4 — Build the offsets manifest

Once verify.py passes on the sample files, build the manifest for the
whole vanilla NR EMEVD corpus:

```
python build_offsets_manifest.py \
    --emevd-dir /path/to/all/vanilla/emevd/files \
    --out ../data/healthbar_callsite_offsets.json
```

(Note: this script needs to be written. It's ~20 lines —
glob `*.emevd`, parse each, run `extract_healthbar_callsites`, emit
JSON keyed by filename. Add to v0.24.0-dev final ship.)

## Step 5 — End-to-end test

Pick a known seed (e.g. the seed 538711 Sentient Pest case from
timeout_v2). Run the pipeline against a stock me3 profile's event/ dir:

```
python pipeline.py \
    --spoiler /path/to/seed538711_spoilers.json \
    --in-emevd /path/to/me3/profile/event/ \
    --out-emevd /tmp/patched_event/ \
    --chr-nameid ../data/chr_to_nameid.json
```

Expected: `Patched N files, M healthbar rewrites total.` where N
includes m49_27 (the Sentient Pest N1 arena). Spot-check by parsing
the patched m49_27 and confirming a new nameId where the old was
902500300 (or whatever the vanilla Battlefield Commander id is).

## Step 6 — Drop into me3, boot, look at the bar

The proof. Boot seed 538711, walk into the Sentient Pest N1 arena. The
healthbar should show whichever chr the rando placed there. If it
shows blank or "???", the FMG additions weren't loaded — feed
`fmg_additions.json` into your FMG editor and re-load.

## Step 7 — Wire into oops_rando_gui

Per `gui_hook_design.py`, ship the checkbox first. The curation tab
follows in v0.24.

Add the checkbox to settings_frame. Wire to `_run_healthbar_rewrite`
which calls `pipeline.run_pipeline`. Done.

## Files Alaric needs to upload (recap)

Highest priority — required for verify.py:
- `m48_50_00_00.emevd` (raw bytes, post-DCX-decompress)
- `m49_25_00_00.emevd` (raw bytes, post-DCX-decompress)

Optional but quick wins:
- `common_func.emevd` (parser sanity check on big file)
- `m38_10_00_00.emevd` (cathedral inline scripts — exercises non-
  arena callsites)

Even-more-optional:
- The vanilla regulation.bin FMG data for boss names, so I can build
  the v0.24 FMG-binary patcher and remove the manual "import into FMG
  editor" step.

## Files NOT needed yet

- `chr_to_nameid.json` — built once per NR patch via
  `prep_demo.py BUILD-CATALOG`; runs against a spoiler, not the .emevd.
  Already documented; can be built on Windows post-ship.
- regulation.bin (unless we're shipping the FMG patcher in this
  release, which we're not — v0.24).
