# BFER integration audit — v0.23.12

**Status (v0.23.13): partially actioned.** Option 2 selected — added
Greyoll + Troll variant to `bfer_imports_v2.json`. Size_class override
philosophy adopted (`override_size_class` block patches 97 vanilla NR
overlap chrs). See v0.23.13 CHANGELOG entry for the shipped form.

Findings from auditing `Boss for Elden Ring` (forget909, Nexus mod 422)
CSV dumps against our existing roster + `bfer_imports.json` v1.

Three audit passes:
1. **Overlap audit** — 168 c-prefixes BFER touches that are also in vanilla NR
2. **Unnamed mass-mob audit** — 102 c-prefixes BFER added with no names, mooky geometry
3. **Unnamed boss-tier audit** — 26 c-prefixes BFER added with no names, boss-grade geometry

Headline conclusion: **only the boss-tier unnamed audit is worth acting on**, and
even that's optional. The other two found nothing actionable.

---

## Audit 1: Overlap (168 c-prefixes)

For each chr in both vanilla NR and BFER, compared geometry + size class.

**Results:**
- 97 size-class "drifts" — but **all are false positives**. Geometry is
  identical between NR and BFER; the difference is that my BFER size_class
  formula uses different thresholds than the vanilla NR tagger. Example:
  c2130 Margit, both tag him at h=3.6 r=0.9 — vanilla NR says XL, my
  formula says M. Same chr, threshold mismatch.
- 9 real geometry changes, all minor BFER scaling tweaks. Most stay in the
  same size class anyway. The notable ones:
  - c5210 Divine Beast Dancing Lion: NR h=7.0 → BFER h=2.4 (radius unchanged
    at 3.5). This is BFER using the lion's quadruped form rather than its
    standing form, which actually makes sense — DBDL has two stances.
  - c5190/c5192 Spider Scorpion: heights halved (2.8→1.6, 3.3→1.9). Probably
    just BFER rebalancing.
  - c3252 Loretta Tree Sentinel: r 2.0→1.55. Minor scaling.
- 69 essentially identical.

**Conclusion: skip.** BFER doesn't add value for chrs we already have. The
nine real geometry changes don't shift our placement decisions. Adopting
BFER's stats here would just introduce inconsistent thresholds.

---

## Audit 2: Unnamed mass mobs (102 c-prefixes)

Clustered by geometry signature:
- 42 humanoid_M_grunts (h≈2.4, r≈0.6, wt≈130) — generic humanoid mooks
- 40 low_wide_quadruped (h≈1.5, r≈0.5, wt≈100) — small beasts, dogs, scarabs
- 20 small_creature (h<1.8, r<0.5) — imps, rats, spirits
- humanoid_M_heavy (8) — likely horses/mounts (3.5/0.7/980 matches
  Lordsworn Knight's Horse profile)

**Conclusion: skip.** 102 c-prefixes is too many to investigate individually,
the marginal value of more grunt-tier variety is low (our rando already
has plenty of grunt-tier chrs), and most of these are probably BFER's
overworld decoration mobs that don't enhance the rando experience.

If a specific mob shows up in a playtest looking interesting and we want
to add it, the bvId pattern (`bvId = c-number × 100`) tells us its family —
but right now there's no signal to pick.

---

## Audit 3: Unnamed boss-tier (26 c-prefixes) — actionable

**The signal:** geometry profiles match real bosses, even without names.
Cross-referencing the bvId (which reveals chr family) gives high-confidence
guesses for several.

### High-confidence identifications

| c-prefix | bvId | Geometry | Likely identity |
|---|---|---|---|
| c4504 | 45000 | h=42 r=17 hp=12440 | **Greyoll** — bvId matches Flying Dragon family (c4500). Only chr in ER big enough for h=42 is Greyoll the colossal sleeping dragon. |
| c4601 | 46000 | h=7.2 r=1.8 hp=1901 | **Troll variant** — bvId matches c4600 (Troll). Probably a SOTE Troll variant or Headless Troll. |
| c5391 | 53900 | h=7.2 r=1.8 hp=1901 | **Variant of c5390** (same bvId). c5390 is also unnamed/uncertain. |
| c4502, c4641 | n/a | n/a | already tagged in `vanilla_promotions_v1.json` |

### Medium-confidence (geometry-clear, identity unclear)

| c-prefix | Geometry | What it might be |
|---|---|---|
| c5790 | h=12.5 r=2 wt=150000, 21 variants | Serpent — super-heavy weight + tall narrow profile = snake/serpent boss. Could be Magma Wyrm Makar variant or an SOTE dragon-form. |
| c5370 | h=14.1 r=7 hp=3128, 9 variants | Flying dragon profile. Possible Bayle variant or Glintstone Dragon. |
| c5580 | h=14 r=7 hp=2704, 6 variants | Same flying dragon profile as c5370. Variant or paired chr. |
| c4670 | h=10 r=5 wt=30000, 10 variants | XXL with mounted-chr weight. Possibly a boss horse (Tree Sentinel mount tier). |
| c4690 | h=4 r=2 wt=30000, 3 variants | Smaller mount variant of c4670. |
| c5390 | h=7.2 r=1.8 hp=1901, 10 variants | XL biped. Aspect of the Crucible variant? |
| c5960 | h=7.5 r=3.7 hp=2713, 6 variants | XL boss, possibly an SOTE late-game encounter. |
| c5780 | h=5 r=2.6 hp=2585, 6 variants | L boss biped. |
| c7930 | h=5 r=2.5 hp=2080, 8 variants | L boss biped. c7xxx range = special encounters. |
| c5630 | h=3.2 r=4.4 hp=876, 7 variants | Wide squatty — Watchdog / Furnace Pup tier. |
| c5591 | h=3 r=3.5 hp=1893, 7 variants | Wide-not-tall, large_boss_ground style. |

### Low-confidence (probably placeholders)

- **c4492**: h=12 r=5 **hp=0** — zero HP suggests this is a placeholder/unused
  data row. BFER may have set it up for future use but never finished.
- **c7660**: h=12 r=2.7 hp=992, 2 variants — c7xxx tall biped, very thin
  signal.
- **c7910**: h=10.1 r=5 hp=819, 4 variants — possibly a Furnace Golem variant?

### Recommendation

If we want to act, the cleanest move is a **`bfer_imports_v2.json`** with
just the high-confidence identifications:

- c4504 as Greyoll (anim_class=flying_dragon, tier=field_boss, strict_nb=True
  given the colossal size)
- c4601 as Troll variant (anim_class=quadruped_large or humanoid, tier=field_boss)

The medium-confidence chrs (~10) could be added as `_confidence: medium`
generic tags so the rando places them by geometry without claiming an
identity. If they look weird in-game, easy to exclude.

The low-confidence (3) and the unidentified rest (~10) — leave alone.

**Total potential v2 additions if we did all medium+: ~13 chrs.**

---

## What this audit means for our integration strategy

The user's strategic shift in v0.23.12 — **let mods do imports, we focus
on randomization** — is fully validated by this audit. The 30 named bosses
in `bfer_imports.json` v1 are 95% of BFER's value to us. The remaining 5%
sits in the 13ish identifiable boss-tier chrs above; the other 95% of
unnamed BFER additions (mass mobs, decorations) doesn't move the needle.

Future BFER updates: re-run the CSV diff, look for new named bosses,
add to v1. Don't bother re-doing the mass mob audit unless something
specific comes up in playtest.
