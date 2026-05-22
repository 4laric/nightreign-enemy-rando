# anibnd_tools

Tooling and research artifacts for FromSoftware BND4/TAE analysis. Built
v0.24.79–v0.24.81 to support Option C — chrbnd/anibnd-derived classification
of entrance animations.

## Files

### Parser tooling
- `bnd4_reader.py` — Parses BND4 container format. Entry size 0x24 bytes,
  UTF-16-LE names. Validated on NR's chrbnd and anibnd files. No DCX
  decompression — assumes raw BND4 (use Yabber to extract DCX-wrapped
  archives first).
- `tae_anim_ids.py` — Skims animation IDs from a chr's TAE inside an
  anibnd. Returns None for skeleton-only variant chrs (which inherit
  anims from parents per the variant-inheritance pattern).

### Research artifacts (from v0.24.81 corpus scan, 396 chrs in 0xxx-5xxx)
- `RESEARCH_NOTES.md` — Comprehensive log of hypotheses tested + findings.
  All 6 hypotheses tested, all dead ends at the anibnd level. The true
  emerge signature lives in Havok keyframe data or behavior tree files.
- `emerge_candidates_for_playtest.json` — 8 game-knowledge candidates
  for the next entrance_animations.json expansion. All have anim 9000
  (TAE-consistent). Highest priority: c4570 Wormface.
- `high_confidence_not_emerge.json` — 105 chrs that lack anim 9000
  (bespoke cinematic intros instead). Reference for future fly_in /
  scripted_intro classification.

## Practical use

When a new CTD surfaces during playtest:
1. Check `high_confidence_not_emerge.json` — if the chr is there, the
   issue is NOT a generic emerge classification miss. Look elsewhere.
2. Check `emerge_candidates_for_playtest.json` — if the chr is there,
   it was already flagged. Add it to `data/entrance_animations.json`
   with the new CTD evidence.
3. Otherwise: do TAE inspection with `tae_anim_ids.py`. If anim 9000
   is present and the chr family / game knowledge suggests emerge,
   add to entrance_animations.json.

## TAE format (partial reverse-engineering)

Header (offset 0x00–0x110):
- 0x00 (4 bytes): magic "TAE "
- 0x08 (4 bytes): version (0x0001000D = ER/NR)
- 0x0C (4 bytes): file size
- 0x50 (4 bytes): chr_id encoded as 200000 + cp_number (e.g. 204810 = c4810)
- 0x54 (4 bytes): animation entry count
- 0x110: start of animation entry table

Animation entry table (each entry 16 bytes):
- 0x00: anim_id (uint32)
- 0x04: padding
- 0x08: pointer to animation record
- 0x0C: padding

Animation record (48 bytes):
- 0x00 (8 bytes): ptr1 — event group structure
- 0x08 (8 bytes): ptr2 — event references
- 0x10 (8 bytes): ptr3 — float times array
- 0x18 (8 bytes): ptr4 — file reference metadata
- 0x20 (4 bytes): event_group_count
- 0x24 (4 bytes): event_count
- 0x28 (4 bytes): time_count

Event payload structure (in ptr1's region, partially decoded):
- Magic "129" at offset +0x18
- Event count at offset +0x28
- Signature parameter at offset +0x2C (sfx_param_id; chr-specific or sentinel)
- Flags 0x01000000 at offset +0x38
- Event type byte at offset +0x44 (value 255 observed across all chrs;
  not yet matched to a known event type table)

## Variant inheritance

Variant chrs (c4441, c4442, c4811, c4482, c4483, etc.) ship with
skeleton-only anibnds — no TAE, no animation hkx files. They inherit
animations from their parent chr at runtime. Parent resolution heuristic:
last-digit zeroing (c4441 → c4440, c4811 → c4810, c4482 → c4480).
Validated on the 4000-series bulk dump: 71 of 150 chrs are skeleton-only.

## Coverage as of v0.24.81

Corpus scanned: 396 chrs across c0xxx through c5xxx. Missing: c6xxx,
c7xxx, c8xxx (partial), c9xxx. The 4xxx range is most relevant for
field-boss CTDs and is fully covered.
