# Phase 1 v0.25.0 stubs — promotion review

Editorial review of the 14 `tags_stub` entries in
`data/phase1_v0.25.0_stubs.json`, executed during the v0.26.x dead-cap
audit session. The stubs were staged at v0.25.0 with `_confidence: low`
on the editorial fields (`tier`, `size_class`, `anim_class`,
`expects_boss_arena`); this pass cross-references each against
established sibling chrs in `nr_enemy_tags.json` and dimension/HP
conventions, producing per-chr promotion verdicts.

## Pre-flight checks (passed across all 14)

- **No tag collisions.** None of these c-prefixes are already present in
  `nr_enemy_tags.json`.
- **Not in `IMPORT_PLAN_COLLISIONS.md`.** None are among the ★★★ "NR
  reused this c-prefix for a different chr" cases that would block
  promotion outright.
- **All 14 are in `dev/import_heritage_ai_scripts.py:IMPORT_PLAN`** —
  the staging is consistent with the AI-script import set.
- **All 14 have `NpcParam.csv` rows** matching the stub's `variants`
  count — the regulation deployment is real.

## Still required before merging into `nr_enemy_tags.json`

Run `dev/audit_chr_assets_vs_roster.py` against the user's deploy to
confirm chrbnd / anibnd / behbnd / texbnd files exist for each c-prefix
below. Chrs with full asset packs go to `nr_enemy_tags.json` and
`nr_enemy_roster.json`. Chrs missing assets go to
`nr_missing_chr_files.broken_runtime_chrs` instead, OR get removed
from `IMPORT_PLAN` entirely.

This review can't run that audit (no deploy on hand) — but the editorial
work is done, so post-audit promotion is mechanical.

## Verdicts

### PROMOTE AS-IS (10)

Editorial fields hold up against sibling/reference comparison. Lift
verbatim into `nr_enemy_tags.json` once asset audit passes.

| c-prefix | name                              | tier        | size | anim              | arena | notes                                                                              |
|----------|-----------------------------------|-------------|------|-------------------|-------|------------------------------------------------------------------------------------|
| c5020    | Putrescent Knight                 | field_boss  | L    | quadruped_large   | True  | SOTE mounted boss; anim driven by steed                                            |
| c5310    | Inquisitor (Base)                 | field_boss  | M    | humanoid          | False | siblings c5311/c5312 miniboss; Base's HP=2239 outranks them, field_boss defensible |
| c5430    | Owl                               | trash       | S    | misc              | False | tiny flier (h=0.6); `is_flier=True` already set per stub                           |
| c5500    | Living Magma                      | grunt       | S    | misc              | False | SOTE Yelough Anix; teamType=51 unusual but not blocking                            |
| c5600    | Catacomb Skeleton                 | grunt       | M    | humanoid          | False | mirrors c3510 exactly (tier=grunt, M humanoid, hp=281)                             |
| c5661    | Shadow Militia                    | grunt       | S    | humanoid          | False | h=1.2 small for humanoid but consistent across 24 variants                         |
| c5800    | Crucible Knight Devonia           | field_boss  | M    | humanoid          | True  | SOTE singular boss; ref c2500 is NB at M humanoid arena=True                       |
| c5850    | Giant Ram                         | miniboss    | L    | quadruped_large   | False | SOTE Cerulean Coast / Jagged Peak                                                  |
| c5950    | Leonine Misbegotten (SOTE)        | miniboss    | M    | quadruped         | False | mirrors c3460 (miniboss M quadruped); hp 564 vs 664 — scaled-down variant          |
| c6310    | Fallingstar Beast (Base/Field)    | field_boss  | XL   | quadruped_large   | False | smaller variant of c4680 NB (h=6/r=4 vs h=11/r=5.5); editorial OK for the scaled-down form |

### PROMOTE WITH CORRECTION (2)

Editorial mismatch with established convention; fix the listed field
before lifting.

| c-prefix | name                          | issue                                                                | fix                                                                       |
|----------|-------------------------------|----------------------------------------------------------------------|---------------------------------------------------------------------------|
| c5360    | Giant Beast Skeleton (family) | stub `tier=grunt` but reference c3500 (same hp=148, M humanoid) is `tier=trash` | change `tier` → `trash` to match c3500 pattern                            |
| c5560    | Fingercreeper (Small)         | stub `anim_class=misc` but reference c4250 Small Fingercreeper is `anim_class=quadruped` (same hand-creature archetype) | change `anim_class` → `quadruped` to match c4250                          |

### DEFER (2)

Promotion would land a chr with a non-obvious failure mode that needs
playtest validation before merging. Keep in `phase1_v0.25.0_stubs.json`
until empirically cleared.

| c-prefix | name                  | risk                                                                                                                                                                                                                |
|----------|-----------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| c5513    | Cemetery Shade        | stub note: "moveType=13 unusual for humanoid; may have float anim". Ghost-type chrs with float anim can ground-clip or hover-no-aggro at standard slots (same failure class as the heritage-idle-roaring `WONTFIX`). Validate in-game first. |
| c5620    | Tibia Mariner (Field) | reference c4950 Tibia Mariner (NB form) is in `V3_EXCLUDE_TARGET_PREFIXES` because Tibia is a boat-rider component requiring summoned skeletons + boat physics. The "field" variant may or may not have the same dependency. Risk-bounded: place once, observe, then decide. |

## Suggested promotion order at the workstation

1. Run `python3 dev/audit_chr_assets_vs_roster.py` against the live
   deploy. Note which of the 14 have full asset packs.
2. For the 10 in PROMOTE AS-IS with full assets: lift the stub's
   `{name, anim_class, size_class, tier, expects_boss_arena, hp_max,
   hp_median, hit_height_median, hit_radius_median, weight_median,
   variants, n_reward_variants, n_noreward_variants, team, move_type,
   locomotion, anim_bank, anim_bank_count, _heritage_imported,
   _source}` fields into `nr_enemy_tags.json`. Drop the `_confidence`
   and `_stub_note` keys (they're staging metadata).
3. For c5360 and c5560: apply the listed correction, then lift the
   same way.
4. For c5513 and c5620: leave in `phase1_v0.25.0_stubs.json` until
   playtest gives signal. Add to a watch list if there's one.
5. Lifted entries should be removed from `phase1_v0.25.0_stubs.json`
   (or marked with a `_promoted_in: v0.26.x` field) so the file
   shrinks to just the deferred set.
