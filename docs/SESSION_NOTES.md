
## v0.24.8 — FMG v2 parser/writer + BND auto-splice + GUI wire-in

Built on v0.24.7's BND foundation to deliver the full FMG splice
pipeline: parse → splice → repack → write to disk, all wired into
the existing Step 4 of the run-shuffle flow.

### FMG v2 format

Format-spec derived empirically against `reference/NpcName.fmg` (see
that file's parser docstring for the chain of evidence). Key wrinkle:
the group structure has a non-standard field order
`(i32 first_id, i32 _zero, i32 first_string_idx, i32 last_id)` —
the middle two fields are swapped from what SoulsFormats reads for
standard FMG v2. Validated by mapping string idx 1 → ID 0 → "Wylder",
idx 11 → ID 10 → "Duchess", etc. matching the Nightfarer character
IDs.

String offsets are u64 absolute file offsets. Strings are UTF-16 LE
null-terminated.

Self-consistency: parse / write / re-parse preserves every entry
exactly (missing=0, added=0, changed=0 across all 610 unique
non-null IDs). Byte-exact round-trip is off by ~3800 bytes because
the original has a redundant empty-slot at ID 0 (group 0) plus
group-table padding our writer doesn't replicate — but the
information content is preserved fully.

### BND4 append-at-end relocation

The non-growing constraint in v0.24.7's writer was too tight for
real splice workloads (~55 boss-name additions = ~3KB strings +
~5KB offsets/groups). Extended `write_bnd4` with a `relocations`
parameter: pass `{entry_name: new_bytes}` and the writer appends
the new data at end-of-file with 16-byte alignment, updates the
entry's data_offset/sizes to point there, and leaves all other
entries (including the BND4 hash table region) byte-verbatim.

The original NpcName slot in the middle of the data section
becomes dead bytes the game won't read since the entry now points
elsewhere. The hash table doesn't reference data offsets — only
filename hashes — so it stays valid through relocation.

End-to-end verified: 55 mock boss-name additions at IDs 920000000+
spliced into the 2.4MB engUS Item bundle:
  - All 55 additions present and correct after re-parse ✓
  - All 5 spot-checked existing entries preserved (Wylder, Duchess,
    Tree Sentinel, Tibia Mariner, Heolstor the Nightlord) ✓
  - All 55 other BND entries (WeaponName, GoodsName, etc.) byte-
    identical ✓
  - Bundle grew 15,792 bytes (~3KB strings + ~13KB relocated FMG)

### Boss-name FMG IDs we now know

From parsing the vanilla NpcName.fmg:
  - Wylder = 0, Duchess = 10, Priestess = 20, Guardian = 30,
    Raider = 40, Ironeye = 50, Executor = 60, Recluse = 70
  - Tree Sentinel = 903250610
  - Tibia Mariner = 904911320
  - Heolstor the Nightlord = 907550004

EMEVD healthbar patcher should pick fresh IDs that don't collide
with the existing ~184 non-null entries.

### GUI: msg bundle path setters

Two new fields in the Folders frame: "Vanilla msg:" (file picker
for the user's `Data0_<hash>.fmg.bnd`) and "Mod msg:" (file picker
for where the patched bundle should be written). Mirrors the
EMEVD pattern with autopersist via trace_add → `.4laric_msg_paths.json`.

The Mod msg path is **assumed to be a me3 logical path** — i.e.,
`<me3_profile>/<package>/msg/engUS/<same-basename-as-vanilla>.fmg.bnd`.
Whether me3 actually picks up the modded bundle at that logical
path is **untested in-game** and is the first thing to verify after
shipping v0.24.8. If me3 doesn't pick it up:
  - Try moving the file to alternate logical paths
  - Or use me3's explicit override config to point at the modded file
  - Or fall back to overwriting the user's actual Game/msg/engUS/ file
    (destructive — needs backup)

### Step 4 wire-in

After the existing EMEVD patch block, dcx_batch.py now has a splice
block that triggers when:
  - Both `vanilla_msg_bundle` and `mod_msg_bundle` kwargs are set, AND
  - `healthbar_report['fmg_additions_count'] > 0`

Loads `fmg_additions.json`, reads the vanilla bundle, splices, writes
the output. Failure is logged loud but doesn't kill the run — the
user still has `fmg_additions.json` to splice manually as a fallback.

### Files added/changed in v0.24.8

  - healthbar_inplace/bnd.py: + `relocations` param on write_bnd4
  - healthbar_inplace/fmg.py: + parse_fmg, write_fmg, splice_fmg_entries
  - healthbar_inplace/bnd_splice_driver.py: NEW — high-level orchestration
  - oops_rando_gui.py: + msg bundle Tk vars, config helpers, picker rows,
    _browse_msg_bundle, wire-in to rando_pipeline kwargs
  - dcx_batch.py: + vanilla_msg_bundle/mod_msg_bundle kwargs on
    rando_pipeline, auto-splice block in Step 4

### Next iteration (v0.24.9)

In-game test from Alaric. Either:
  (a) modded bundle works on first try → ship as stable, move on to
      other features
  (b) me3 doesn't pick up the modded bundle → iterate on logical path
      conventions, possibly fall back to direct-overwrite mode
  (c) game loads bundle but boss names show as blank/garbled → FMG
      structure has a wrinkle we missed (likely the unused
      `_zero` field actually matters somewhere, or our group
      reconstruction loses information)

## v0.24.9 — Two-path UX: Game install + me3 package derive everything

User feedback on v0.24.8: bouncing through 7+ individual folder
pickers is friction. Replaced the per-subdir picker pattern with
two top-level parent paths that derive the rest automatically.

### New top-level pickers (at top of Folders frame)

  - **Game install:**  typically `<install>/Game/` (UXM-unpacked).
    If the user picks the install root (one level up), the code
    auto-appends `Game/`. Derives:
      - Vanilla MSBs ← `<game>/map/mapstudio/`
      - Vanilla event ← `<game>/event/`
      - Vanilla chr ← `<game>/chr/`
      - Vanilla msg bundle ← `<game>/msg/engUS/<discovered-basename>`
  - **me3 package:**  typically `<me3 profile>/<package>/`. Derives:
      - Output / Mod map ← `<me3>/map/mapstudio/`
      - Mod event ← `<me3>/event/`
      - Mod chr ← `<me3>/chr/`
      - Mod msg bundle ← `<me3>/msg/engUS/<same-basename>`

Persists to `.4laric_paths.json` via trace_add (same autopersist
pattern as the earlier per-subdir paths).

### Msg bundle basename auto-discovery

The msg bundle has a hash basename (typically
`Data0_15912862698882586866.fmg.bnd`) that varies per game version,
so we can't hardcode it. When `game_install_var` changes, the code
scans `<game>/msg/engUS/*.fmg.bnd`, size-filters to ~1-5MB candidates,
parses each with `bnd.parse_bnd4`, and picks the first whose entries
include a `NpcName.fmg` path (excluding `_dlc01` variants). Basename
gets cached in `msg_bundle_basename_var` and persisted to the same
JSON, so subsequent launches skip the rescan.

If discovery fails (no msg dir, no candidate files, parse errors),
the basename stays empty and the user can fill the msg picker rows
manually via the existing v0.24.8 picker.

### Old picker rows kept visible

The individual picker rows (Vanilla MSBs, Output, Mod map, Vanilla
event, Mod event, Vanilla msg, Mod msg) are still rendered in the
Folders frame below the two new parent pickers, with a separator
between. The derived values show through, so the user sees what
the rando will use. Anything they edit directly overrides the
derived value (until they change the parent path, which re-derives
all children).

### Tested

Fresh GUI-less unit test with FakeStringVar mocks confirmed all
9 derived paths (including the autodetected msg bundle basename)
populate correctly from a simulated UXM-unpacked install + me3
package layout. Auto-append-Game branch tested too: picking the
install root (one level above Game/) correctly walks down.

### Next: in-game test from Alaric

When the rando is launched fresh, the two parent pickers should
be the only things the user has to set in Folders. Verify by
unchecking and rechecking the saved JSON.

## v0.24.10 — Paths tab + auto-copy same-dir bug fix

### Bug fix: auto-copy WinError 32 spam (300 failures)

From Alaric's v0.24.9 run log: all 300 .msb.dcx files failed to
copy to mod folder with `WinError 32: The process cannot access
the file because it is being used by another process`.

Root cause: v0.24.9's parent-path derivation makes
`output_dir_var = mod_map_dir_var = <me3>/map/mapstudio`. The rando
writes its final files directly to that path (which IS the desired
behavior — write straight to the me3 deploy location). Then the
post-run auto-copy step tries to copy each file from that same
directory to itself. On Windows, `shutil.copy2(x, x)` raises
WinError 32 because opening x for read and x for write
simultaneously is undefined.

**Not a real concurrency/threading bug.** Auto-copy runs
sequentially after the rando completes. The error message is
misleading — Windows' way of saying "can't copy a file to
itself." No race condition, no missing locks, no need for
synchronization. Just src==dst.

Fix: `_copy_to_mod_folder` now canonicalizes both paths with
`os.path.normcase(os.path.realpath(...))` and skips the copy
when they're equal. Logs:

```
Skipping auto-copy: Output and Mod map are the same folder.
   C:\...\nightreign-mods\FIA\map\mapstudio
   The rando wrote .msb.dcx files there directly.

Launch the game via me3 to test.
```

Tested with `ntpath` to simulate Windows path normalization on
Linux — Alaric's mixed-slash paths
(`.../FIA/map/mapstudio` vs `.../FIA\map\mapstudio`) collapse to
the same canonical form and the skip fires correctly. Different-
dir cases still trigger the copy as expected.

### UX: individual pickers moved to a new Paths tab

v0.24.9 left all the individual path pickers visible on the
Generate tab under the two new parent pickers, which made the
front page taller and crowded. v0.24.10 moves the individual rows
to a dedicated **Paths** tab (right after Generate in the
notebook), grouped into two LabelFrames:

  - **Vanilla (read)**: Vanilla MSBs, Vanilla event/, Vanilla chr/,
    Vanilla msg
  - **Mod (write)**: Output, Mod map/mapstudio, Mod event/,
    Mod chr/, Mod msg

The Generate tab's Folders frame now shows only the two parent
pickers (Game install, me3 package) plus a short note saying
"everything else derives from these — override on the Paths tab
if needed."

Auto-derivation behavior unchanged: changing Game install or me3
package on the Generate tab still overwrites the corresponding
Paths-tab fields. Direct edits on the Paths tab persist until
the next parent-path change.

### What's still broken / to test

  - Auto-splice did fire successfully in Alaric's log (51 new FMG
    nameIds extracted) BUT it skipped because only one of (Vanilla
    msg, Mod msg) was set: `"FMG auto-splice skipped: only one of
    (Vanilla msg, Mod msg) is set"`. With v0.24.9's auto-discovery,
    if game_install is set BEFORE me3_package, vanilla_msg gets
    derived but mod_msg stays empty until me3_package is also set.
    Alaric likely had game_install set but me3_package not yet (or
    discovery couldn't find an Item bundle in his install layout).
    Worth verifying on next run.
  - In-game test of the modded NpcName.fmg at the me3 logical path
    `<pkg>/msg/engUS/<basename>.fmg.bnd` still pending.

## v0.24.11 — UXM-unpack reality check: NR uses item_dlc01.msgbnd.dcx

User's actual `<install>/Game/msg/engUS/` after UXM-unpacking contains
just three files:
  - `item_dlc01.msgbnd.dcx`  (~210KB compressed Oodle KRAK → ~2.4MB BND4)
  - `menu_dlc01.msgbnd.dcx`
  - `ngword.msgbnd.dcx`

Not the hash-named `Data0_<hash>.fmg.bnd` files I'd been working with
(those come from a pre-UXM Data0.bdt extract, not a typical unpack).
v0.24.9's autodetection was hunting for `*.fmg.bnd` in a 1-5MB size
window, so it found nothing in Alaric's actual install — hence the
`FMG auto-splice skipped: only one of (Vanilla msg, Mod msg) is set`
in his v0.24.9 run log: vanilla_msg was blank.

### Two fixes:

**Discovery rewrite.** `_discover_msg_bundle_basename` now scans for
any `item*.msgbnd*` or `item*.fmg.bnd*` filename (covers both
compressed-and-not, with-or-without _dlc01 suffix), picks the
largest. Dropped the content-verification step (parse for NpcName.fmg)
because that required DCX-decompression which needs Oodle, and we
don't want to require Oodle at GUI-init / parent-path-change time.

Tested against Alaric's exact three uploaded files: discovery
correctly picks `item_dlc01.msgbnd.dcx` and ignores menu/ngword.

**DCX-aware splice.** New `splice_npcname_into_bundle_file()` in
`bnd_splice_driver.py`: detects DCX magic on input, decompresses via
`dcx.DCX.decompress_bytes(file_bytes, oodle)`, runs the existing
splice, recompresses via `DCX.compress_bytes(..., compression=b'KRAK')`.
Round-trips the wrapper so the output drops in at the same logical
me3 path. Non-DCX input flows through unchanged (validates v0.24.8
raw-BND path is preserved).

Step 4 in `dcx_batch.py` now calls the DCX-aware variant and passes
the `oodle` instance that was already created at line 534 for
EMEVD/MSB compression — same Oodle DLL, no extra init cost.

### Unit tests

  - Discovery against Alaric's exact file set: ✓ picks
    `item_dlc01.msgbnd.dcx`
  - Discovery rejects hash-named pre-UXM files: ✓ (no 'item' prefix)
  - Non-DCX raw-BND splice through new dispatcher: ✓ 3/3 test
    additions readable, byte-grew within expected range
  - DCX magic branch fires correctly (test data malformed, but the
    detection-and-dispatch path executed)

### What's tested vs not

  - Tested on Linux without Oodle: discovery, non-DCX splice, DCX
    detection branch entry.
  - NOT tested on Linux (impossible without Oodle DLL): DCX KRAK
    decompress/recompress round-trip. Alaric's NR install has the
    DLL the rando already loads for emevd/msb work, so the same
    Oodle instance handles the msg bundle.

### Next test from Alaric

Re-run with v0.24.11. Expected outcome in the log:
  - "Vanilla msg" and "Mod msg" auto-populated to
    `<game>/msg/engUS/item_dlc01.msgbnd.dcx` and
    `<me3 pkg>/msg/engUS/item_dlc01.msgbnd.dcx` respectively.
  - Step 4 logs "Auto-spliced N name(s) into NpcName.fmg →
    <mod path>" with "Bundle DCX: 210KB → ~225KB" or similar.
  - In-game test of the modded NpcName.fmg via me3 still the
    open question — first time we'd actually see custom boss
    names appear over healthbars.

## v0.24.12 — Splice diagnostics for "not a BND4 file"

Alaric's v0.24.11 run got past the discovery and DCX-detection
hurdles (auto-splice block actually ran) but failed at parse with:

```
FMG auto-splice FAILED: not a BND4 file (magic b'A\x95\xbdK')
```

The bytes `0x41 0x95 0xBD 0x4B` don't match any container magic
I recognize — not BND4, not BND3, not DCX, not Sekiro msgbnd
prefix. Three hypotheses:

1. **Extra encryption layer**: msgbnd files in NR may be
   AES-encrypted under the DCX wrapper (similar to regulation.bin
   in ER), and UXM didn't strip that layer. KRAK would decompress
   to encrypted bytes that look random.
2. **Wrong file**: discovery picked something that isn't actually
   the Item bundle. The file matched `item*.msgbnd*` pattern but
   its inner content is a different format.
3. **New container format**: NR uses something post-BND4 that we
   haven't seen yet.

We don't have enough info to pick between these from the current
log. **v0.24.12 adds diagnostic logging** at every stage of the
splice:

  - Path being read
  - File size
  - First 16 bytes of raw file (hex)
  - DCX wrapper detected: yes/no
  - If DCX → first 64 bytes of decompressed payload
  - If decompressed-payload-isn't-BND4 → loud warning + the three
    hypotheses listed inline so the user knows what to check

Next run will tell us which branch we're in.

### UXM-side troubleshooting suggested for Alaric

He noted: "UXM selective unpacker says it can unpack NR to include
the msg files but doesn't do it when I run it on mine". Worth
checking:

  1. UXM version — UXM-SE (Selective Unpacker) by tremwil has the
     NR profile; older versions may not.
  2. UXM config — the unpack-categories selection might exclude
     msg by default. Verify "msg" / "language files" is enabled.
  3. Run UXM as administrator (NTFS permission edge cases).
  4. Verify post-unpack file size: a properly unpacked
     `item_dlc01.msgbnd.dcx` should be ~210KB. Anything wildly
     different (5KB stub, or 0 bytes, or the original encrypted
     ~2MB) suggests something's off.
  5. Alternative: try WitchyBND for direct msgbnd unpack instead
     of UXM.

### Potential future fallback (not in v0.24.12)

If UXM consistently fails to give us a clean msgbnd: read directly
from `<install>/Game/Data0.bhd` + `Data0.bdt` (the encrypted
archive). Requires implementing:

  - BHD5 parser (the file index, AES-decrypted)
  - BDT reader (the data blob, addressed by BHD5 entries)
  - File lookup by name hash

~300 lines of code plus the AES key for NR's data archives. Doable
but defer until we confirm UXM can't be made to work.

## v0.24.13 — Fallback nameId: ship without splice working

Selected name (per Alaric's pick): **902130014 — "Crucible Knight and more"**.
The text is literally correct in every shuffled fight since every
fight has at least one enemy in it (= "and more" Crucible Knights
than zero), so the deception layer is technically a truthful
observation. Comedy through pedantry.

### How it works

`make_fmg_allocator(base, fallback_id=N)` gets a new optional
`fallback_id` parameter. When set:
  - All calls to `allocate(text)` return `fallback_id` regardless
    of text
  - The internal `table` stays empty
  - `get_table()` returns `{}` → `fmg_additions.json` is empty
  - Step 4's splice block sees `n_fmg == 0` and skips automatically
  - No msgbnd file required, no UXM dependency, no Oodle KRAK on
    msg files, nothing

The ~108/158 vanilla-to-vanilla healthbar rewrites are unaffected —
those go through `reuse_vanilla` in `decide_rewrites` and never
touch the allocator. So Tree Sentinel slot → Tibia Mariner still
shows "Tibia Mariner" correctly. Only the ~50/158 cross-game
(heritage/MMV) and heterogeneous-squad cases get the fallback string.

### UI

Paths tab, below the Mod (write) frame, new "Fallback (skip splice)"
LabelFrame containing:
  - Checkbox: "Use vanilla nameId fallback for cross-game / mixed-
    squad healthbars (skips FMG splice)"
  - Entry: "Fallback nameId:" with default 902130014 + a dim hint
    explaining what it resolves to
  - Footer paragraph explaining the trade-off (~70% accurate, ~30%
    show the fallback string) and when to use it

Persists to `.4laric_paths.json` under `use_fallback_nameid` and
`fallback_nameid` keys.

### Plumbing

  - `rewriter.make_fmg_allocator(base, fallback_id=None)` — the
    actual short-circuit
  - `pipeline.apply_to_dir(..., fallback_nameid=None)` — passes
    through to the allocator
  - `dcx_batch.rando_pipeline(..., fallback_nameid=None)` — kwargs
    chain through Step 4, prints a log line when active:
    `Using vanilla nameId 902130014 as fallback for cross-game/
    heterogeneous bosses (splice will be skipped — no UXM msgbnd
    required)`
  - `oops_rando_gui._run_shuffle` — reads the Tk vars, only passes
    a non-None value when the checkbox is checked

### Tests

  - `make_fmg_allocator` with fallback_id: all calls return the same
    int, table stays empty ✓
  - Existing test_roundtrip and test_rewriter both still pass
    (11/11 + 6/6) — fallback is opt-in, default behavior unchanged

### How to use

1. Open Paths tab
2. Check "Use vanilla nameId fallback for cross-game / mixed-squad
   healthbars"
3. Leave default 902130014 in place (or pick another vanilla nameId)
4. Run the rando — should complete with no FMG splice, no UXM
   dependency, all the meme value of "Crucible Knight and more"
   appearing over the occasional shuffled heritage-import healthbar.

The v0.24.12 splice diagnostics still apply — if a future run sets
this checkbox OFF and supplies real msg paths, the diagnostics will
fire and we can keep iterating on getting splice working properly.

## v0.24.14 — Title pool + compose_name stub (wire-ready)

Shipped as preparation for the post-splice mashup format Alaric
wants. Stub is fully tested but no caller invokes it yet — wiring
happens in a future iteration once FMG splice is reliable.

### Added

- `data/title_pool.json` — 25-entry curated title list. Vanilla NR
  comma-tails (Beast of Night, Wisdom of Night, etc.), iconic ER
  borrows (Lord of Blood, Blade of Miquella), one meta entry weighted
  3× ("and more"). Format is a flat `"titles": [...]` array under
  `_doc` / `_pool_source_credits` documentation keys (runtime
  ignores anything starting with `_`).
- `data/title_pool_README.md` — editing guide, source credits,
  selection-logic explanation, length-budget caveat, ideas for
  custom entries.
- `rewriter.compose_name(original_name, replacement_name, original_c,
  replacement_c, title_pool, seed)` — pure function, deterministic,
  produces the mashup string.
- `rewriter.load_title_pool(path=None)` — loads + validates the JSON.
- `tests/test_compose_name.py` — 12 tests covering format branches,
  determinism, edge cases (unicode, empty pool, same-c-prefix).

### Format produced

  vanilla→vanilla swap:
    "<original_name> → <replacement_name>, <title>"
    e.g. "Tree Sentinel → Tibia Mariner, Beast of Night"

  heritage / no-original-name:
    "<replacement_name>, <title>"
    e.g. "Mohg, Lord of Blood"

  same c-prefix on both sides:
    "<replacement_name>, <title>"
    No arrow because it's not actually a swap.

### Selection determinism

MD5(f"{original_c}|{replacement_c}|{seed}")[:8] interpreted as int,
mod pool size. Same (original_c, replacement_c, run_seed) tuple
always picks the same title. Different seeds may pick differently.
Per-pair binding means players see consistent aliases within a run
("oh, Tree-Sentinel-shaped Tibia Mariners are always Naturalborn of
the Void") while different pairs roll independently for variety.

### Sample output at seed=42 against current 25-entry pool

  45c  Tree Sentinel → Tibia Mariner, Beast of Night
  50c  Crucible Knight → Banished Knight, Ascendant Light    [clip risk]
  38c  Banished Knight, Champion of Nightglow
  36c  Mohg, Lord of Blood, Miasma of Night                  [double-comma]
  41c  Tibia Mariner → Death Rite Bird, and more
  29c  Tree Sentinel, of Farum Azula
  45c  Albinauric Archers → Erdtree Avatar, of Zamor
  22c  Fell Omen, the Grafted
  44c  Heolstor the Nightlord, of the Boreal Valley
  40c  Crystalian Alliance, Consort of Miquella

Several land over the ~40-char healthbar clip threshold. Policy:
let them clip. Chaos-in-randomizer is on-brand. If we want to be
fancy later, add length-aware title selection (long pair → short
title).

### Wire-in checklist (next iteration, after splice is reliable)

1. In `decide_rewrites`, replace the two `unified_name` and
   `composite` paths with `compose_name(...)` calls, threading
   through the new title_pool + seed.
2. Resolve `original_name` from `cs.name_id` via reverse-lookup
   against the parsed vanilla NpcName.fmg (loaded once at the start
   of `apply_to_dir`).
3. Add a `--compose-names` flag to `apply_to_dir` (default off,
   gated behind splice availability).
4. GUI toggle on Paths tab: "[✓] Use mashup format (original →
   replacement, random title)" — disabled if Vanilla msg / Mod msg
   aren't both set.

### Tests

  - test_compose_name.py: 12/12 ✓ (format branches, determinism,
    seed variance, unicode, empty pool, missing file)
  - test_roundtrip.py: 11/11 ✓ (unchanged)
  - test_rewriter.py: 6/6 ✓ (unchanged)

Total: 29 tests, all green.

## v0.24.15 — Title pool expansion + template syntax

Alaric contributed 17 additional pool entries spanning pop culture
(WWE, The Big Lebowski, Anchorman, Breaking Bad, The Office, Guy
Fieri, Shaq, Princess Bride). Several are templates — phrases that
wrap the boss name itself — which required extending the pool format
beyond plain string epithets.

### Template syntax (v2 format)

Strings containing `{r}` or `{o}` are TEMPLATES. They REPLACE the
whole name rather than getting appended after a comma:

  - `{r}` substitutes the replacement name
  - `{o}` substitutes the original name (or replacement when
    original is None — avoids stray whitespace in heritage cases)

  "The Dread Pirate {r}"   →  "The Dread Pirate Tibia Mariner"
  "{o} 'The Rock' {r}"     →  "Tree Sentinel 'The Rock' Banished Knight"
  "'Stone Cold' {r}"       →  "'Stone Cold' Mohg"

Plain strings (no placeholders) continue to work as v1-format
epithets:  "<name>, <title>".

Dispatcher in `compose_name`: detects placeholder presence at
selection time and routes to the appropriate path. Pool can mix
both styles freely.

### Pool now at 42 entries (3× "and more" weight, ~7% appearance rate)

Source breakdown:
  - 8 vanilla NR comma-tails (Beast of Night, etc.)
  - 8 vanilla NR standalone (the Nightlord, Naturalborn of the Void, etc.)
  - 6 ER classics (Lord of Blood, Blade of Miquella, etc.)
  - 17 pop culture (Alaric submissions):
      Mayor of Flavortown
      #1pussyEater's brother
      The Dread Pirate {r}
      'Macho Man' {r}
      'Stone Cold' {r}
      {o} 'The Rock' {r}
      The Big Aristotle
      Mr Wonderful
      The King of Crunk
      Ice Cold
      San Diego's #1 rated newsman
      kind of a big deal
      The One who Knocks
      His Dudeness
      El Duderino
      Assistant to the Regional Manager
      'Husband to Bears,'
  - 3 meta ("and more" weighted)

### Sample output across multiple seeds

seed=42:
  Crucible Knight → Banished Knight, The Big Aristotle
  Fell Omen → Mohg, The King of Crunk
  Banished Knight, His Dudeness
  'Macho Man' Tibia Mariner
seed=7:
  'Stone Cold' Heolstor the Nightlord
  Tree Sentinel → Margit, Ice Cold
  Astel, and more
seed=100:
  Tibia Mariner → Death Rite Bird, 'Husband to Bears,'
  Fell Omen → Mohg, #1pussyEater's brother
  The Dread Pirate Banished Knight

Lots of clipping at the ~45-char healthbar threshold; on policy
(chaos is the genre).

### Tests

  - test_compose_name.py: 17/17 ✓ (12 original + 5 new template tests)
  - test_roundtrip.py: 11/11 ✓
  - test_rewriter.py: 6/6 ✓

Total: 34 tests, all green.

## v0.24.16 — Five more pool entries

Alaric round-two additions, pool now at 47 entries:

  - `"'Sugar' {r}"` — boxing-nickname template (Sugar Ray family)
  - `"The artist formerly known as {o}"` — Prince reference. Used
    `{o}` not `{r}` because the joke is the slot's *past* identity:
    "The artist formerly known as Tree Sentinel" appears over the
    Tibia Mariner that replaced it. Reads as "this used to be Tree
    Sentinel." Flagged as an interpretive call — flip to `{r}` for
    the absurdist read if preferred.
  - `"The G.O.A.T."` — standalone epithet
  - `"The Sultan of Swing"` — standalone epithet (Dire Straits;
    deliberately not "Sultan of Swat" / Babe Ruth)
  - `"'Shoeless' {r}"` — Shoeless Joe Jackson template

Notable outputs:
  - `'Shoeless' Mohg` (15c)
  - `Fell Omen → Mohg, The G.O.A.T.` (30c)
  - `The artist formerly known as Fell Omen` (38c) — coincidentally
    on-genre for Souls hidden-identity lore
  - `Astel 'The Rock' Astel` — heritage `{o}` fallback to `{r}`
    produces tautological gold

All 34 tests still green.


# Session notes — 2026-05-27

Root-caused the Spider Scorpion failure, found it was an 11-chr class,
shipped the fix, and cleared the c3360 Ancestral Follower of the same
suspicion. No engine fingerprint bump this session — work is a data fix
plus a new dev audit tool.

## The bug — heritage SpEffect-ID gate mismatch

The Spider Scorpion (c5190) spawns, aggros, circles, and never attacks.
Prior sessions had ruled out the missing-script bug (c5190 always had
`519000_battle.luabnd`). Root cause this session:

`519000_battle.lua` `Goal.Activate` picks attacks by populating a
`probabilities` table gated behind `ai:HasSpecialEffectId(TARGET_SELF,
<literal id>)` checks on the chr's variant-discriminator SpEffect tags.
Those tags are applied permanently via NpcParam `spEffectID*` slots.

The MMV importer copies SpEffect *contents* faithfully but remaps their
IDs from ER's literal range into NR-range `60000-69999` — including on
the `spEffectID*` slots that carry those discriminator tags. So the chr
ends up carrying `61400` where the script asks for `20011000`. Every
gate fails, `probabilities` stays empty, the scorpion never acts.

The bug lives in the seam between two internally-correct layers: a
literal magic number in the script vs. a remapped ID on the chr. That
is why per-layer diffs never caught it.

Severity depends on script structure:

- TOTAL — every `probabilities` populate path is behind a broken gate,
  no positional fallback. Empty table -> never attacks. The scorpion.
- DEGRADED — a positional/distance `if/elseif/else` chain populates
  `probabilities` independently; the broken gate only adds/removes
  entries afterward. The chr still fights, but silently loses its gated
  moves. The Fire Knight (c5160): hand-graded as losing Act04, Act11
  (its weight-1000 long-range engage), and the `20011748`-gated combo
  extensions on ~8 attacks — stuck in its base moveset.

## The sweep — 11 chrs

Built `audit_speffect_id_gate_mismatch.py` (see dev tool note below).
Per-row/per-slot diff of mod NpcParam vs vanilla-ER NpcParam: flag a
slot when vanilla held a script-referenced ID and the mod replaced it
with a `60000-69999` id. Script resolution via NpcThinkParam
`battleGoalID` so shared-script variants resolve. Validated against
c5190 as a known-positive control before trusting any output.

Detection requires DECOMPILED Lua — HKS bytecode stores numeric
constants as 8-byte doubles, not greppable ASCII; a `strings` scan
finds nothing and silently reads "clean" (false-negative trap, hit
twice during tool development).

Flagged — 11 heritage chrs, all confirmed by per-row mismatch:

- c5190 / c5192 / c5193  Spider Scorpion family — TOTAL
- c5040  Curseblade          | c5080  Bloodfiend
- c5081  Chief Bloodfiend     | c5090  Gravebird
- c5160  Fire Knight          | c5250  Horned Warrior
- c5311  Inquisitor (Candle)  | c5312  Inquisitor (Staff)

The 8 non-scorpion chrs were shipping unflagged — degraded AI nobody
had caught. The Imp (c5870) carries remap-range SpEffects too but is
NOT flagged: its remaps are not in script-gated slots. Clean by this
bug class.

Severity grading was NOT automated. Two attempts failed their controls
(line-based Lua block tracking cannot distinguish a variant-sibling's
dead branch from a real fallback). Abandoned as a blocker — the fix is
identical regardless of severity, so severity only ever affected triage
order, not the deliverable.

## The fix — shipped

`regulation_fixes/heritage_speffect_fix_npcparam.csv` — full Smithbox
NpcParam-export format (356-column header + 93 complete rows), one row
per affected variant across all 11 chrs. Every remap-range `spEffectID*`
cell on those rows reverted to its original ID.

Correctness notes:

- All 26 original SpEffect IDs verified to exist in mod `SpEffectParam`
  — every revert points at a real row.
- Reverts ALL 206 remap-range cells on the affected rows, not just the
  107 script-gated ones — a full-row import writes every cell, so a
  half-reverted row would import wrong values.
- One inferred cell: `61685 -> 20013250` on c5311 rows `53110020 /
  53110120 / 53111020` (rando-added rows, no vanilla counterpart;
  derived from sibling rows — every other c5311 row uses `20013250` in
  `spEffectID25`).

Application: re-randomize FIRST, then apply the CSV to the *output*
regulation. The rando regenerates regulation each run and reinstates
the `614xx` remap.

## c3360 Ancestral Follower — cleared

Investigated as a suspected same-class case (closed gate chain in
`336000_battle.lua`, structural resemblance to the scorpion).
DISPROVEN: the `131xx` discriminator tags are intact and unremapped on
every c3360 NpcParam row, the combat branches populate `probabilities`,
the Lua is clean. The resemblance was coincidence.

The real c3360 issue is unrelated and already correctly handled: a
v0.27.0 variant-level ban (`oops_v3.py`) — playtest found only 2 of 34
variants (`33600010` Axe-BGB, `33600510` Archer-BGB) render and fight.
All 34 variants are `_source=post_dlc_dump` with empty `sample_maps`,
so the automatic ghost-variant filter is blind for c3360, hence the
manual playtest-seeded ban. The ban sits in an `oops_v3.py` block whose
own comment states this break class's ground truth lives in the chr's
anibnd/behbnd (TAE animation events, behavior trees) — uninspectable
with current tooling. The 2-variant ban is correct; the cause is
asset-layer, not params or scripts. Nothing to fix in the Lua.

## Open / next

- Bake the SpEffect-ID reverts into the MMV import data source so every
  run applies them automatically (dev/TODO.md).
- Add an importer guard: SpEffect IDs a heritage chr's battle/logic Lua
  references by literal (`HasSpecialEffectId(<literal>)`) must import
  as-is, never remapped (dev/TODO.md).
- New dev tool: `audit_speffect_id_gate_mismatch.py` — promote from the
  scratch sweep into `dev/` so future heritage imports are checked
  pre-ship, not after a playtest. c5190-validated; requires decompiled
  Lua as input.