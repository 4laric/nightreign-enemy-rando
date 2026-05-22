# IMPORT_PLAN ↔ tags naming-collision audit — v0.25.0

**Status: open investigation.** The v0.25.0 audit that produced
`data/phase1_v0.25.0_stubs.json` exposed an orthogonal issue: many
existing IMPORT_PLAN entries import ER battle scripts for chrs
whose c-prefix is used by a DIFFERENT chr in NR's merged tags. This
file catalogues those collisions for systematic triage.

The seed-939029 CTD investigation (Elder Lion encampment in
m32_20_00_00, fighting next to a c5870 "Imp (Lion Head)" placement)
was the prompt — that placement is one of the cases below.

## What "collision" means here

`dev/import_heritage_ai_scripts.py`'s `IMPORT_PLAN` ships ER battle
scripts (e.g. `380000_battle.luabnd`) into the heritage_pack overlay's
`script/` folder under the same c-prefix the ER source used (c3800).
At runtime, NR loads whatever chrbnd happens to live at that c-prefix
in the deploy. If heritage_pack ships a chrbnd for c3800 that is
ITSELF an ER chr renamed to "Cleanrot Knight" in NR's tag system,
then the script and the chrbnd are aligned at the asset-format level
even though the name in tags disagrees with the IMPORT_PLAN comment.
If heritage_pack ships a chrbnd that is genuinely a different chr
(NR repurposed the c-prefix), the script and chrbnd target different
chrs — runtime risk: high.

**Without inspecting actual chrbnd content per c-prefix in the
deploy folder we can't tell the two cases apart from the data
alone.** The catalogue below flags each case for that determination.

## Methodology

```
for cp, scripts in IMPORT_PLAN.items():
    comment_name = parse_comment_for(cp)        # what we think we're importing
    tag_name = merged_tags[cp].name             # what NR's runtime says it is
    if not fuzzy_match(comment_name, tag_name):
        FLAG(cp, comment_name, tag_name)
```

Run as part of the v0.25.0 audit; reproducible via the inline Python
in this session's transcript or a future `dev/audit_import_plan_names.py`.

## Cases (13 hard collisions, 2 partial)

Sorted by escalation risk. The "merged-tags from" column shows which
table contributes the tag (`heritage_pack.json.tags` mostly — these
are heritage-shipped chrs).

| c-prefix | IMPORT_PLAN ships scripts for (ER) | NR tags say it is | tag source | risk |
|----------|-------------------------------------|-------------------|------------|------|
| c5870    | Crystalian (XL humanoid boss)       | Imp (Lion Head) (S humanoid trash) | heritage_pack | ★★★ CTD-class size/tier mismatch — implicated in seed-939029 |
| c4420    | Ulcerated Tree Spirit (XXL large_boss_ground) | Giant Crayfish (?) | heritage_pack | ★★★ size/anim_class mismatch |
| c4800    | Erdtree Avatar (XXL large_boss_ground) | Mohg- the Omen (L humanoid) | heritage_pack | ★★★ extreme anim_class mismatch |
| c4820    | Hippopotamus (large) (L quadruped_large) | Omenkiller (M humanoid) | heritage_pack | ★★★ anim_class mismatch |
| c6060    | Land Octopus (M aquatic-ish) | Goat (S quadruped) | heritage_pack | ★★ anim/locomotion mismatch |
| c4210    | Rune Bear (L quadruped_large) | Warhawk (humanoid mounted) | heritage_pack | ★★ anim mismatch but moveType might align |
| c5040    | Bell Bearing Hunter (M humanoid) | Curseblade (M humanoid) | heritage_pack | ★ same shape — likely safe; just name relabel |
| c5070    | Wraith (M humanoid) | Death Knight (M humanoid) | heritage_pack | ★ same shape — likely safe |
| c5830    | Red Wolf (M quadruped) | Messmer Soldier (M humanoid) | heritage_pack | ★★ anim_class mismatch (added v0.25.0 — recent regression) |
| c5900    | Beast Man (of Farum Azula) (M humanoid) | Man-Fly (S flier?) | heritage_pack | ★★ size/anim mismatch |
| c3750    | Pumpkin Head (M humanoid) | Clayman - Spear (M humanoid) | heritage_pack | ★ similar shape — name relabel |
| c3800    | Putrid Tree Spirit (XL large_boss_ground) | Cleanrot Knight (M humanoid) | heritage_pack | ★★★ extreme anim mismatch |
| c3730    | Misbegotten (M quadruped) | Graven School (?) | heritage_pack | ★★ unknown identity for Graven School |

Plus two "no comment" entries the audit caught structurally but whose
script-import is likely correct (comment just wasn't written):

| c-prefix | merged-tags name | likely status |
|----------|------------------|---------------|
| c5080    | Bloodfiend (heritage_pack) | ER's c5080 IS Bloodfiend — comment missing, but alignment is real |
| c5081    | Chief Bloodfiend (heritage_pack) | ER's c5081 IS Chief Bloodfiend — comment missing, alignment real |

## Triage workflow per case

For each ★★★ case:

1. **Inspect actual chrbnd content in deploy.** Use FromBNDTool or
   equivalent on `<deploy>/chr/c<prefix>.chrbnd.dcx`. Read the
   internal `.flver` model name and compare against ER's known
   c-prefix model and against NR's tag-name. The chrbnd's internal
   model name is the source of truth.

2. **Three outcomes per c-prefix:**
   - **chrbnd is ER's chr (matches IMPORT_PLAN comment)**: leave IMPORT_PLAN
     entry intact, fix the NR tag name to match. Heritage author
     renamed the chr but kept the asset.
   - **chrbnd is NR's tag-name chr**: heritage_pack repurposed the
     c-prefix. Remove the IMPORT_PLAN entry — ER's script is the wrong
     AI brain for this chr. If the tag-name chr needs an AI script,
     find it by its own original c-prefix in ER.
   - **chrbnd is neither**: heritage_pack invented a chrbnd. Mark
     as cap=1 in `nr_missing_chr_files.broken_runtime_chrs` until
     investigated further.

3. **Run audit_chr_assets_vs_roster.py.** Cross-check the chrbnd hash
   against ER's source archive. If they match ER's chr exactly, the
   chrbnd IS the ER chr regardless of what the tag-name says. If
   they don't match, the chrbnd is a derivative or invention.

## Why these probably happened

**The chrbnd-rename hypothesis:** the heritage_pack author imported
ER's c5870 Crystalian into NR, decided that visually it was suitable
as an "Imp (Lion Head)" given NR's existing imp roster, and updated
the tag-name without updating the chrbnd. The AI script we're now
importing IS Crystalian's — paired with Crystalian's chrbnd renamed
to Imp Lion Head, this would work, but it would mean the chr behaves
mechanically as a Crystalian (defense/parry breakpoints, attack
animations) under an Imp visual identity. Possibly intentional, but
not what the IMPORT_PLAN comment claims.

**The chrbnd-replacement hypothesis:** heritage_pack replaced ER's
chrbnd at c5870 with a different chr (NR's actual Imp Lion Head model
from somewhere else). Then our ER Crystalian script lands next to a
chrbnd it wasn't built for. AI script tries to drive Imp Lion Head
using Crystalian's behavior tree. CTD or freeze likely.

Which hypothesis holds varies per case — that's why the chrbnd
inspection (step 1 above) is the gate.

## Action items (v0.25.1+)

- [ ] Inspect chrbnd internals for the 4 ★★★ cases first
  (c5870, c4420, c4800, c4820, c3800). These are the highest-risk.
- [ ] Add `chrbnd_identity` column to nr_enemy_tags entries so
  future audits can spot the IMPORT_PLAN/tag-name divergence
  automatically without manual investigation.
- [ ] Promote the audit logic into `dev/audit_import_plan_names.py`
  so it runs as part of the v-bump check before each ship.
- [ ] Decide policy: should IMPORT_PLAN comments be authoritative
  (we know what ER chr we're importing) and tag-names follow,
  or should tag-names be authoritative (NR's runtime identity)?
  Currently inconsistent.

## Cross-references

- `data/phase1_v0.25.0_stubs.json` — the 14 new chrs added in
  v0.25.0 with NO existing tags. Separate problem from this collision
  audit but exposed in the same v0.25.0 review.
- `dev/audit_chr_assets_vs_roster.py` — existing tool, run against
  deploy to verify chrbnd file presence per c-prefix.
- Seed 939029 CTD investigation (m32_20_00_00, pi=61 Elder Lion
  encampment) — c5870 placement was in the same MSB and is the
  prime collision candidate per this audit.
