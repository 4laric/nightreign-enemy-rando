# MMV (More Map Variations) integration — optional

This rando supports an **optional** integration with **More Map Variations**
([Nexus #578](https://www.nexusmods.com/eldenringnightreign/mods/578)) by
Team Daybreak. MMV imports cross-game bosses (Elden Ring, Shadow of the
Erdtree, Dark Souls 3, Dark Souls 1) into Nightreign — Malenia, Maliketh,
Godfrey, Slave Knight Gael, Dragonslayer Armor, etc.

When MMV is installed in your me3 profile, you can enable the rando's
MMV manifest and its swap pool extends to include those imports.

## TL;DR

- **Default state: DISABLED.** Out of the box, the rando works on vanilla
  Nightreign + Forsaken Hollows DLC content only. No MMV references, no
  CTD risk.
- **If you have MMV installed**, edit `mmv_imports.json`, change
  `"_meta.enabled": false` to `"_meta.enabled": true`, run the rando.
  Cross-game bosses get folded into the swap pool.
- **If you don't have MMV installed**, leave it alone. Enabling the
  manifest without MMV will reference c-prefixes that don't exist in
  your regulation, which CTDs the game on cell load.

## What the integration does (when enabled)

41 c-prefixes worth of MMV imports get added to the rando's target pool:

- 19 ER + SoTE + DS3 nightlords (Malenia, Godfrey, Hoarah Loux, Maliketh,
  Starscourge Radahn, Lichdragon Fortissax, Romina, Midra, Messmer, Metyr,
  Scadutree Avatar, Rellana, Slave Knight Gael, Dragonslayer Armor, etc.)
- 11 field bosses (Death Rite Bird, Black Knight, Fire Demon, Outrider
  Knight, Commander Gaius, Lamprey, Crucible Knight variants, etc.)
- 7 minibosses + 2 grunts + 2 trash + 1 mount component

Boss-tier swap pool roughly doubles (87 → 102 caliber c-prefixes; 25 → 44
strict-NB c-prefixes). A boss-tier source slot has roughly equal
probability of becoming a vanilla NR boss, a Forsaken Hollows DLC boss, or
an MMV cross-game import.

## What's blacklisted under MMV

`mmv_imports.json` includes a `blacklist_when_active` section listing 16
c-prefixes that crash the game when MMV is active:

- **9 CTD-confirmed**: c2240, c3110, c4540, c4541, c5650, c6230, c8200,
  c8400, c8500. Most are unidentified MMV imports without resolved names.
  c8500 (DS1 Manus) was specifically tested under v0.23.38's boutique
  probe and CTDs on Limveld load. DS1's chr asset graph diverges too
  far from NR conventions.
- **7 DLC-asset-missing**: c4801, c7610, c7650, c7651, c7660, c7720,
  c7930. These are NR Forsaken Hollows DLC c-prefixes (Artorias, Demon
  from Below, the Dreglord ad chrs, Lord of Blood Spear) whose
  chrbnd/anibnd assets aren't in MMV's mod payload. With MMV's
  regulation active, references to them break.

Both lists apply only when `_meta.enabled=true`. Disabling the manifest
removes the blacklist — appropriate when running vanilla NR regulation
where MMV chrs don't exist but DLC chrs are functional.

## Conservatively-tagged content

8 of the 41 c-prefixes (c2240, c3110, c4540, c4541, c5650, c6230, c8200,
c8400) are MMV imports we couldn't identify by name from any extracted
NpcParam dump. They're tagged with conservative defaults and
`_confidence: 'low'`. All 8 are also in the CTD blacklist as a safety
measure. If you have MMV regulation extracts and can identify them, they
can be moved out of the blacklist on a per-c-prefix basis.

## How to enable MMV integration

**Prerequisite: MMV mod installed in your me3 profile.**

1. Open `mmv_imports.json` in any text editor.
2. Find the `"_meta"` block at the top:
   ```
   "_meta": {
     "enabled": false,
     ...
   }
   ```
3. Change `false` to `true`:
   ```
   "_meta": {
     "enabled": true,
     ...
   }
   ```
4. Save. Run the rando. The startup log will print:
   `mmv_imports: 41 tags + 373 variants loaded ...`

## How to disable MMV integration

If you uninstall MMV or want to test something on vanilla NR:

1. Open `mmv_imports.json`.
2. Set `"_meta.enabled": false`.
3. Run the rando. Startup log will print:
   `mmv_imports: skipped (_meta.enabled=false)`

The rando reverts to vanilla NR + DLC content only. No MMV references
are loaded, no MMV blacklist applies.

## Limitations

- **MMV-modified MSBs not folded in.** MMV claims field-boss pool went
  22→87 and night-boss pool 35→54 in their map data. Their MSB additions
  aren't in our placement dataset; we use MMV chrs at NR's vanilla
  slots, not at MMV's added slots. This is fine — there are plenty of
  vanilla slots — but you won't see chrs at MMV-only spawn points.
- **Version pinning.** The integration is built against MMV 2.0.5.
  Future MMV releases could shift tier characteristics or add
  c-prefixes. Extra c-prefixes would just be unrecognized (graceful
  skip) — no crash, just no extra coverage.
- **8 c-prefixes need re-identification** if you want them safely
  unblocked: c2240, c3110, c4540, c4541, c5650, c6230, c8200, c8400.
  Requires a full MMV regulation extract with FMG-resolved names.

## Boutique CTD-isolation mode

If a particular MMV chr CTDs and you want to identify which one, the GUI
has a **Oops! All NB (boss probe)** mode (run-mode dropdown). Pick a
target enemy and a scope, every boss-tier slot under that scope gets
forced to your target. If the run CTDs reproducibly, that chr is the
culprit.

Suggested probe order for the cross-game imports (highest CTD risk first):

1. ~~c8500 Manus~~ — already banned (DS1, asset graph too divergent)
2. c8300 Dragonslayer Armor (DS3)
3. c6200 Slave Knight Gael (DS3)
4. c5840 Black Knight (DS3)
5. c5930 Giant Skeleton (DS3)
6. c1310 Outrider Knight (DS3)
7. c4730 Starscourge Radahn (ER, XL)
8. c4511 Lichdragon Fortissax (ER, dragon)
9. c5230 Scadutree Avatar (SoTE, XXL)
10. c5200 Metyr / c5130 Messmer / c5051 Midra / c5030 Romina / c5300 Rellana (SoTE)
11. ~~c2120 Malenia~~ — confirmed working

Use scope='extended' for these probes — it covers Castle interior,
Encampments, and Evergaols where geometry-sensitive chrs typically fail.
