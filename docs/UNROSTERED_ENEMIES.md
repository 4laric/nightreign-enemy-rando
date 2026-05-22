# Unrostered enemies — candidates for ER NPC_PARAM import

## Status

**32 c-prefixes** ship as model entries in vanilla NR's MSB Models sections —
chr files exist, animations exist, the model is loaded into one or more
maps — but **no Part instantiates them**. They are content NR loads but
never spawns.

The randomizer engine can't currently use them as placement targets
because we have no `npc_param` data for these c-prefixes (no rostered
variants → no entry in `nr_enemy_roster.json` → not in any compat pool).

Each of these chrs has a corresponding entry in base Elden Ring's
`NPC_PARAM_ST` table. Importing those rows into our roster would
unlock these as targets without needing to reverse-engineer params
from scratch.

ER documentation source for identifications: vawser's chr ID list
([github.com/vawser/ER-Documentation](https://github.com/vawser/ER-Documentation/blob/main/Info%20-%20Chr%20IDs.txt)).

## The 32 unrostered chrs

Sorted by c-prefix. "Sample MSB" = one of the maps where the chr
appears in the Models section; useful for confirming the chr file
loads correctly. "Family fit" = nearest already-rostered c-prefix
the engine could borrow stats/AI from if importing ER params doesn't
work cleanly.

### Crab variants (gaps in the c2270 family)
- **c2273** — Crab (Maggots). Family fit: c2272 Giant Black Crab.
- **c2274** — Giant Crab (Clean). Family fit: c2272 Giant Black Crab.
- **c2275** — Crab (Clean). Family fit: c2271 Crab.
- **c2277** — Crab (Golden Tufts). Family fit: c2271 Crab.

We already have c2270/c2271/c2272/c2276 rostered, so the family is
mostly covered — these four would round out the size×color matrix
(small/large × normal/clean/maggots/golden).

### Ancestral Follower variants
- **c3360** — Ancestral Follower. Family fit: c3361 Putrid Ancestral
  Follower (we have the Putrid variant rostered; this is the base).
- **c3370** — Ancestral Follower Shaman. Family fit: c3371 Putrid
  Shaman.

Two-chr family completion. Rare-feel chrs that would benefit from the
unique-cap system (cap=1 each since they're singular boss-feel).

### Snail (c4140)
- **c4140** — Snail. Family fit: c4150 Basilisk (closest small-creature
  rostered neighbor; Snail and Basilisk aren't related but anim_class
  may overlap).

The NR-shipping Snail model is interesting because there's no
rostered small-arena passive creature in NR; importing this would
add a unique slot type.

### Dog/Stray variants
- **c4162** — Large Braided Dog. Family fit: c4161 Stray.
- **c4163** — Braided Dog. Family fit: c4164 Large Bloodbane Stray.
- **c4167** — Mushroom Dog. Family fit: c4166 Large Rotten Stray.

NR has c4160-c4166 (excluding 162/163/167) rostered. Adding the gaps
would give 8 distinct dog variants instead of 5.

### Scarab variants
- **c4190** — Large Tear Scarab. Family fit: c4191 Scarab.
- **c4192** — Ash Scarab. Family fit: c4191 Scarab.

Scarabs are small ambient creatures in ER. In NR they're functionally
"loot drops with legs." Adding variants would expand small-target
variety.

### Soldier/Knight family — Castle (Limgrave) and Haligtree

The Soldier and Knight families in NR follow a tens-digit convention:
ones digit = which faction (0=base/Castle, 1=Godrick, 2=Cuckoo/Raya,
3=Leyndell, 4=Radahn, 5=Mausoleum/headless, 6=Haligtree). NR ships
chrs for the base+Haligtree variants but **doesn't roster them**.

#### Soldiers (c43XX)
- **c4310** — Soldier (Castle/base). Family fit: c4311 Godrick Soldier.
- **c4312** — Raya Lucaria Soldier. Family fit: c4313 Leyndell Soldier.
- **c4316** — Haligtree Soldier. Family fit: c4315 Mausoleum Soldier.

#### Knights (c435X)
- **c4350** — Castle Knight (base). Family fit: c4351 Godrick Knight.
- **c4356** — Haligtree Knight. Family fit: c4355 Mausoleum Knight.
- **c4358** — Vawser flags as "referenced in params but not present in
  chr" in ER. NR ships the model. Identity unclear — may be cut content.

#### Knight horses (c436X)
- **c4360** — Knight's Horse (base). Family fit: c4363 Lordsworn Horse.
- **c4361** — Godrick Knight's Horse. Family fit: c4363.

#### Foot soldiers (c437X)
- **c4370** — Foot Soldier (base). Family fit: c4371 Godrick Foot Soldier.
- **c4376** — Haligtree Foot Soldier. Family fit: c4375 Mausoleum Foot
  Soldier.

If imports work for these, the visual variety lift on encampments
would be substantial — 7 new humanoid grunt/knight variants. Castle
Knight (c4350) specifically is the most-used base ER soldier; would
look great as a frequent placement.

### Misc humanoids
- **c4430** — Abnormal Stone Cluster. Family fit: c4420 Giant Crayfish
  (closest c-prefix neighbor; not actually related). This may be a
  unique creature type.
- **c4441** — Giant Fungal Pod. Family fit: c4440 Land Squirt (the
  basic Fungal Pod). c4441 is the larger variant.
- **c4442** — Giant Rotten Pod. Family fit: c4440. Rotten variant of
  the giant.

### Miranda Sprout variants
- **c4482** — Fading Giant Miranda Sprout. Family fit: c4481 Miranda
  Sprout.
- **c4483** — Fading Miranda Sprout. Family fit: c4481.

The "Fading" variants are visually distinct from regular Mirandas
(decay textures). Capping these at 2 each via the unique-cap system
would let them feel like seasonal/regional variety.

### Dragon variants
- **c4502** — Dragon (Blade in Mouth). Family fit: c4500 Flying Dragon.
- **c4504** — Elder Dragon Greyoll. Family fit: c4500. **Greyoll is the
  giant dragon mother — would be iconic as a single-placement
  encounter.**

These are the most exciting candidates. c4504 Greyoll is one of the
most visually striking ER dragons. Both should be cap=1 in
`V3_UNIQUE_TARGET_CAPS` if imported.

### Troll variant
- **c4601** — Armored Troll Knight (Blade). Family fit: c4600 Troll
  Knight (which we already have rostered).

Variant of the existing Troll Knight family — visual diversity for
overworld trolls.

### Starscourge Radahn (?)
- **c4730** — Per ER docs, this is **Starscourge Radahn** (the boss
  fight chr). Family fit: no close rostered neighbor.

This is a famous boss model. Importing the param would let you
place Radahn somewhere. Caveat: his arena is heavily scripted in
ER (huge open field with mounted combat); placing him in a
non-arena slot may produce odd behavior. Treat with extreme
caution; cap=1 mandatory if enabled.

### Erdtree Avatar variant
- **c4811** — Erdtree Avatar (variant). Family fit: c4810 Erdtree
  Avatar.

Likely a visual or color variant. Low-risk import.

## Implementation plan

1. **Acquire ER `NPC_PARAM_ST` table.** Either via SoulsFormats library
   (extract from `regulation.bin` in your ER install) or pre-extracted
   CSV from a project like vawser's documentation repo or
   ER-Documentation tools.

2. **Filter to the 32 c-prefixes above.** ER's NPC_PARAM has thousands
   of entries; only ones whose row ID maps to a c-prefix in our list
   are needed.

3. **Map ER param fields to our roster schema.** Our `nr_enemy_roster.json`
   uses fields like `npc_param_id`, `think_param_id`, `mmv_name`,
   `c_prefix`, plus a few NR-specific fields. ER and NR share the same
   param schema for NPC_PARAM (same engine), so the field names should
   match directly. Need to verify.

4. **Stage as a separate JSON.** Write `imported_er_params.json`
   alongside `nr_enemy_roster.json`. Engine loads both, NR roster
   wins on duplicates (unlikely with this set since these are
   un-rostered in NR).

5. **Per-chr testing.** Each imported chr should be tested individually
   via the diagnostic-mode `non_fragile_baseline_cp` flag — force-spawn
   it at every non-fragile slot in a small map, confirm no CTDs.
   Especially critical for c4730 Radahn (scripted arena) and c4504
   Greyoll (huge size).

6. **Add to `V3_UNIQUE_TARGET_CAPS`** for the iconic ones (c4504, c4730,
   c4502) at cap=1. The grunt-tier imports (Knights, Foot Soldiers,
   etc.) don't need caps — they're meant to appear frequently.

## Risks

- **Param schema drift.** ER and NR share an engine but NR is a newer
  build; some param fields may differ. Worst case: imported params
  load but produce broken AI/stats (chr stands still, takes no damage,
  etc.). Medium-severity since it's recoverable per-chr.
- **Anim/talkscript dependencies.** Some chrs reference anim files or
  talkscripts that may not exist in NR. c4730 Radahn is the highest-risk
  here — his moveset references many specialized anims. If those are
  missing, the chr crashes when picking that anim.
- **Cluster/pair semantics.** A few of these chrs have rider/mount
  pairing in ER (Knight + Horse). If we import the Knight without
  re-establishing the pair, the chr may spawn in unintended ways.

## Notes

- This list is based on the v0.23.06-shipped `nr_enemy_roster.json`.
  If `manual_promotions.json` is later extended to add more chrs, this
  list should be regenerated.
- The **5 placed-but-unrostered** c-prefixes (c0000, c0100, c0120,
  c1000, c8910) are NOT in this list — they're system slots (player
  character, UI/cinematic actors, Nightlord placeholders) and should
  never be placement targets regardless.
- See `docs/EMEVD_PATCHES.md` for related discussion of scripted-arena
  chrs and their constraints.
