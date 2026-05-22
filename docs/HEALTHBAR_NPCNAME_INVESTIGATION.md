# Healthbar NpcName Investigation — Post-Mortem

May 16-17 2026, v0.24.96 through v0.24.111+. Multi-session investigation
into why per-chr healthbar names couldn't be made to load in Nightreign,
and what we did about it.

## TL;DR

**Goal**: when the rando swaps chr X in for chr Y at some MSB Part, the
healthbar in-game should show X's name (or a fun mashup) instead of Y's
or "?NpcName?".

**Approach attempted**: splice new entries into NR's `NpcName.fmg` (and
its containing `item_dlc01.msgbnd` bundle), point EMEVD healthbar
callsites at the new nameIds.

**Outcome**: ~15 attempted fixes over two days, every one rejected by
NR's FMG loader with the same "?NpcName?" symptom in-game. Eventually
shipped a retreat: catalog-driven `reuse_vanilla` for ~117 c-prefixes
that have a vanilla nameId we can point at, fallback to `902130014`
("Crucible Knight and more") for everything else, **no FMG splice at
all**. The install dir's vanilla `item_dlc01.msgbnd.dcx` stays
untouched. Bars work.

**Remaining mystery**: MMV (More Map Variations, a confirmed-working
Nightreign mod) successfully splices new entries into NpcName.fmg. We
could not figure out what makes MMV's modified file acceptable to NR's
loader and ours rejected. Documented at end as `OPEN_QUESTIONS`.

## Background

### What NR's healthbar pipeline does at runtime

When a bar appears for an enemy, NR's renderer reads a `nameId` (uint32)
from the EMEVD event handler that spawned/named the entity. It looks
that nameId up in `msg/engUS/item_dlc01.msgbnd.dcx`'s `NpcName.fmg`
table and renders the resulting string. If the lookup fails or the
slot is empty, it renders `"?NpcName?"`.

### What the rando wants to do

The rando swaps chr identities at MSB Parts while preserving entity
IDs and positions, so most EMEVD logic survives. But the **nameId
field** baked into each handler still references the *original* chr's
nameId. After a swap, the bar shows the wrong name (or `?NpcName?` if
the original chr was a heritage/imported chr NR's stock localization
doesn't cover).

The fix is conceptually clean:

1. For each healthbar callsite in EMEVD, rewrite its 4-byte nameId
   field to point at whatever nameId names the new chr.
2. If no vanilla nameId names that chr, allocate a fresh nameId, splice
   a new entry into NpcName.fmg containing the desired text, and write
   that fresh nameId into the EMEVD.

Step 1 worked fine. Step 2 — splicing new entries — never worked.

## Two days of failed splice fixes

Each of these was implemented, verified to produce structurally clean
output, deployed, tested in-game. Every one resulted in `?NpcName?` on
every fresh-allocated bar.

### Fix 1: DCX wrap from KRAK to DFLT
**Theory**: NR rejects KRAK-compressed loose files; expects DFLT.
**Reality**: vanilla file IS KRAK. Reverted. DCX header was never the
issue once we matched vanilla's compression bytes.

### Fix 2: 16-byte file alignment for DCX output
**Theory**: DCX file size must be 16-byte-aligned. Real, vanilla had
this. Our output didn't. Fixed.
**In-game result**: still `?NpcName?`.

### Fix 3: BND4 entry record full repack (write FMG in place at vanilla
offset)
**Theory**: NR validates BND4 entry layout; FMG must be at its original
offset rather than appended at end.
**Reality**: confirmed structurally identical to vanilla. **In-game
result**: still `?NpcName?`.

### Fix 4: FMG writer rewrite preserving original group structure
**Theory**: our FMG writer was rebuilding the groups table from
sorted IDs, collapsing vanilla's overlapping groups and losing one
string slot per overlap.
**Reality**: yes, real bug. New writer makes all 56 vanilla FMGs
round-trip byte-identical. Splice preserves vanilla structure exactly,
appends new groups only.
**In-game result**: still `?NpcName?`.

### Fix 5: 8-byte sentinel/trailer between groups-end and SOTR-start
**Theory**: vanilla has 8 bytes of mystery content between the last
group entry and the string-offsets-table start (looks like a high-ID
sentinel `912000080` for NpcName). NR's loader requires this trailer
present.
**Reality**: empirically verified — every FMG in vanilla has exactly 8
bytes here. Our output now writes it.
**In-game result**: still `?NpcName?`.

### Fix 6: File-size alignment from 8-byte to 4-byte
**Theory**: vanilla aligns FMG file_size to 4 bytes (some FMGs have
`fs % 8 == 4`); our writer was forcing 8-byte alignment.
**In-game result**: still `?NpcName?`. (Later disproven anyway —
MMV's NpcName.fmg has `fs % 4 == 2`, so 4-byte alignment isn't a hard
requirement either.)

### Fix 7: ID range moved from 970M to 911.1M (under the gap sentinel)
**Theory**: gap sentinel `912000080` is a max-id upper-bound. Our
970M IDs exceeded it. Move to 911.1M (under sentinel) and the loader
should accept.
**In-game result**: still `?NpcName?`.

### Fix 8: ID range moved to 911000151 (extending vanilla g108 in place)
**Theory**: vanilla group 108 has `first_id=911000070, count=81,
claimed last_id=912000000`. A claimed range much wider than its
actual slot count. If we add IDs in [911000070, 912000000], they fall
within g108's claimed range. NR's loader may match g108 first,
compute a slot offset out of g108's actual count, and return junk.
Fix: extend g108 in place — set base = g108.first_id + g108.count =
911000151, so splice adds slots to g108 rather than appending a new
group.
**In-game result**: forced-test diagnostic showed `?NpcName?` on
every bar pointed at the extended g108. Hypothesis falsified.

### Fix 9 (the diagnostic that ended the chase)
**Setup**: hacked rewriter to force every healthbar callsite to use a
single fresh-allocated nameId (`911000151`) with text `"RANDO TEST
BOSS"`. Splice extends g108 by exactly one slot.
**Result**: `?NpcName?` on every bar.

This was conclusive: the issue isn't ID-range, isn't sentinel-bounds,
isn't group structure. NR's loader rejects something about our
modified FMG that we couldn't see in any byte diff.

## The MMV ground-truth gap

MMV (a Nightreign content mod) has its own `item_dlc01.msgbnd.dcx`
that adds 27 new groups and ~41 new strings to NpcName.fmg. **MMV
loads cleanly in NR**. We have both their compressed and decompressed
files for comparison.

Key facts about MMV's NpcName.fmg:

- 136 groups (vanilla: 109; ours: 110 when appending a new group)
- 652 strings (vanilla: 611; ours: 697 when adding 86 entries)
- All 27 new groups injected in **lower ID ranges** (902M-909M, between
  existing groups), not appended at the end
- MMV's last group is still g108-equivalent at first_id=911000070,
  matching vanilla
- MMV repacks every FMG in the bundle (MagicName, GoodsCaption, etc.
  are all slightly different sizes from vanilla — 2 bytes smaller in
  several cases)
- MMV's `file_size % 4 == 2` for NpcName.fmg (so 4-byte alignment is
  not a hard NR requirement)
- BND4 entry layout: 16-byte aligned `data_off` for every entry,
  matching us
- DCX compression: KRAK/6, matching us
- All file-format invariants we identified match between MMV and our
  output

We byte-diffed MMV against vanilla, MMV against our output, and our
output against vanilla in every direction we could think of. We could
not find a structural difference between MMV's accepted file and our
rejected one that would explain the divergent loader behavior.

## What we shipped (current state)

**v0.24.111-ish: catalog-driven, no-splice retreat.**

`dcx_batch.py` calls the healthbar pipeline with `fallback_nameid =
902130014` ("Crucible Knight and more"). The `make_fmg_allocator`
helper, when given a fallback ID, returns that ID for every call and
keeps `fmg_table` empty. Downstream:

- `fmg_table` empty → `n_fmg = 0` → splice step skipped entirely
- `item_dlc01.msgbnd.dcx` in the install dir is never touched
- Per-callsite decisions:
  - **reuse_vanilla**: chr is in `data/chr_to_nameid.json` catalog.
    Write its vanilla nameId to the EMEVD. Bar shows the real vanilla
    name (e.g., "Guardian Golem", "Gaping Dragon").
  - **fresh_allocation**: chr was swapped (in spoiler) but not in
    catalog. Allocator returns `902130014`. Bar shows "Crucible Knight
    and more". Honest-ish — there are usually multiple enemies in a
    fight, one of them probably has a Crucible Knight's worth of HP.
  - **unchanged**: callsite's `chr_entity_ids` don't match any
    spoiler entry. Original nameId stays. Bar shows whatever the
    EMEVD originally had — sometimes a real vanilla name (working
    correctly), sometimes `?NpcName?` if the original bar pointed at
    a heritage chr.

**Catalog coverage**: 117 c-prefixes mapped (out of 349 in the roster).
~16% of healthbar instances in a typical run go through
`reuse_vanilla`, ~21% go through `fresh_allocation` and get the
fallback, ~63% go through `unchanged`. Of the `unchanged` set, many
still display correct vanilla names; some show `?NpcName?` because
their original-bar nameId was for a chr NR doesn't localize.

**Catalog build**: from `NpcParam.csv` (npc_param_id → display name),
`nr_enemy_roster.json` (c_prefix → npc_param_ids), spoiler new-side
names, and vanilla NpcName.fmg + NpcName_dlc01.fmg. Matched by exact
text, parens-suffix-stripped, plural/singular variants. Most unmatched
chrs are heritage/imported (Morgott, Malenia, Demi-Human Page,
Messmer Soldier, etc.) — these chrs genuinely don't exist in vanilla
NR's stock localization.

## What works that didn't before

The investigation produced some real wins, even if the headline goal
wasn't reached:

- `healthbar_inplace/fmg.py` now does **byte-identical round-trip on
  all 56 vanilla FMGs** through parse → write. Old writer collapsed
  vanilla's overlapping groups; new writer preserves them exactly via
  `strings_by_idx` (indexed by string slot, not by logical ID) and
  preserves the 8-byte gap trailer via `_gap_bytes`. Used for splice
  in the diagnostic phase; safe to call even though we don't splice
  in the shipped path.
- `dcx_batch.py` mirrors `fmg_additions.json` and `apply_report.json`
  out of the per-run tempdir into `out_dcx_dir` so they survive
  post-run inspection.
- The `chr_to_nameid.json` build process is documented (matching
  strategies, sources). Anytime new chrs are added to the roster or a
  match is missed, rebuilding the catalog is straightforward.

## Open questions (for next time)

1. **What does MMV's NpcName.fmg do that ours doesn't?** We have the
   files. The byte-level invariants all match. The behavior differs.
   There's some validation NR's loader does that we haven't located.
   Possible avenues:

   - Try byte-substituting a single MMV group into our output and see
     if that one entry becomes loadable. Working bottom-up from a
     known-loadable byte sequence might reveal the constraint.

   - Strace / live-debug NR's process while it loads vanilla vs our
     file, see what file IO patterns differ. Probably requires reverse-
     engineering tooling we don't currently have.

   - Try matching MMV's exact behavior: inject new groups in the
     middle of the ID range (not appended; not extended-in-place), and
     repack every FMG in the bundle (not just NpcName). One of those
     two things might be what NR validates.

2. **Why are 63% of healthbar callsites going "unchanged"?** The
   rewriter only matches when callsite `chr_entity_ids` are in the
   spoiler. But the spoiler tracks MSB Parts; many EMEVD callsites
   reference entity IDs that don't correspond to a tracked Part (they
   might be "direct EMEVD spawn" entities or shared group bars). A
   smarter strategy: when callsite chr_entity_ids miss the spoiler,
   look up the original nameId in the catalog (reverse direction), find
   which chr it names, then check if any of that chr's instances
   were swapped. Would cut the "unchanged → ?NpcName?" residue.

3. **Is there a way to ship the "extend g108 in place" splice safely
   even if NR rejects new entries?** The empty-splice path is
   byte-identical to vanilla. Maybe a `--splice` flag, off by default,
   for users who want to experiment.

## Pointers

- `healthbar_inplace/fmg.py` — FMG parser/writer with faithful round-
  trip. Currently dormant in the ship path; splice machinery still
  works and tests pass.
- `healthbar_inplace/rewriter.py` — `DEFAULT_FMG_ID_BASE = 911_000_151`
  (the extend-g108-in-place ID; not actively used since splice is off
  but preserved for future re-tries).
- `data/chr_to_nameid.json` — 117 c-prefix → [vanilla_nameId] catalog.
- `dcx_batch.py` (~line 980) — Phase 1 invocation; `fallback_nameid =
  902130014` hardcoded.
- `/mnt/user-data/uploads` test corpus from the investigation contains
  stock vanilla raw + DCX, MMV raw + DCX, multiple rando outputs
  through the iterations. Useful for the next byte-diff attempt.

The work today wasn't all wasted. The FMG round-trip is genuinely
better than what we started with. The catalog covers more chrs than
the 3 we had. The pipeline diagnostics (fmg_additions.json /
apply_report.json mirrored to a persistent location) survive across
runs. We just didn't crack the loader-acceptance constraint and ended
up routing around it.
