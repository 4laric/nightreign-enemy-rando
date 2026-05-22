# ER heritage imports (v1)

Authored c-prefix tags + variants for ER Night-Boss-tier chrs whose chr files
ship in NR's `chr/` folder (per `ChrModelParam`) but have no `NpcParam` rows
in NR's regulation. Without these tags + variants the rando cannot place
those chrs as swap targets — they're invisible to the engine despite the
chr files being on disk.

## Empirical anchor

**c2160 Astel, Naturalborn of the Void** has been confirmed working in
playtest at one point (encountered and fought). This is the proof-of-concept
that c2xxx chrs whose chr files NR ships can in fact be placed and behave.
The other 11 entries in this batch are authored on the same hypothesis: if
the chr file ships, an authored tag + synthetic variant is sufficient for the
rando's placement path.

## Regulation.bin dependency

For these chrs to actually function (HP, AI, drops, attacks), your
`regulation.bin` needs corresponding NpcParam + NpcThinkParam rows at the
synthetic IDs the rando writes. Smithbox-importable CSVs are at
[`dev/er_heritage_csvs/`](../dev/er_heritage_csvs/) — see that folder's
README for the per-chr template-inheritance map (Margit inherits Morgott's
stats, Astel inherits Astel's stats, etc.) and the import workflow.

Two CSVs:

- `NpcParam_er_heritage_v1.csv` — 24 rows (12 chrs × 2 variants)
- `NpcThinkParam_er_heritage_v1.csv` — 12 rows

All synthetic IDs verified collision-free against vanilla NR's regulation.

Without these imports, rando-placed chrs may CTD or silent-statue at
runtime depending on how the engine handles missing param lookups. The
empirical Astel encounter that anchors this batch was probably running
against a regulation that already had matching rows merged from a prior
test build.

## What's included (12 c-prefixes)

| CP | Identity | Size | Anim |
|------|----------|------|------|
| c2010 | Margit, the Fell Omen | M | humanoid |
| c2030 | Rennala (Phase 1) | M | humanoid |
| c2031 | Rennala, Queen of the Full Moon (Phase 2) | M | humanoid |
| c2050 | Radagon of the Golden Order | L | humanoid |
| c2060 | Mohg, Lord of Blood | L | humanoid |
| c2110 | Maliketh, the Black Blade | L | humanoid |
| c2120 | Malenia, Blade of Miquella | M | humanoid |
| c2131 | Morgott, the Omen King | L | humanoid |
| c2160 | Astel, Naturalborn of the Void | GIGA | aquatic |
| c2190 | Godrick the Grafted | XL | humanoid |
| c2191 | Godrick the Grafted (Phase 2) | XL | humanoid |
| c2200 | Godfrey, First Elden Lord (Hoarah Loux) | L | humanoid |

Each chr gets 2 synthetic variants tagged `(Field Boss)` and `(Night Boss)`
so the engine's tier-routing logic can pick the right variant per slot
class. The synthetic `npc_param_id` follows the standard convention
(`cp_int * 10000 + variant_offset`); whether those IDs resolve to actual
data depends on the user's regulation.bin. If they don't resolve, the chr
loads with default stats — empirically this still produced a working Astel
encounter.

## Source-tag convention

Every entry — tag and variant — carries `_source: "er_heritage_v1"`. This
is the project's convention for "imports authored by the maintainer that
can be removed as a unit if they don't pan out."

The engine treats `er_heritage_v1` identically to `script_spawn`: target-
only. They're picked AS swap targets but never randomized away from their
(zero) MSB placements. The engine site is the `V3_TARGET_ONLY_SOURCES`
frozenset in `oops_v3.py`.

## Excluding at-will (three escape hatches)

### 1. Disable in-place (cleanest reversible toggle)

Edit `er_heritage_imports.json`:

```json
"_meta": {
  ...
  "enabled": false,
  ...
}
```

Re-shuffle. The loader sees `enabled: false`, prints `er_heritage_imports:
skipped (_meta.enabled=false)`, and the entire batch is excluded for that
run. Flip back to `true` to re-enable. No code changes needed.

### 2. Delete the file (permanent removal)

Just delete `er_heritage_imports.json`. The loader's `os.path.isfile` check
fails, no entries load, no error. Engine runs as if the batch was never
authored. This is the cleanest "expunge for good" option.

### 3. Surgical removal (one chr at a time)

Remove the chr's entry from BOTH the `tags` and `variants_per_prefix`
sections of the JSON. The other entries continue working. Useful when a
specific chr (say, Malenia) turns out to CTD or stay dormant in playtest
but the rest behave.

You can find every reference to the batch with:

```
grep -r 'er_heritage_v1' /path/to/project
```

## Relationship to other source tags

| Tag | Origin | Removable how |
|-----|--------|---------------|
| (no `_source`) | Auto-detected from MSB scan against vanilla NR | Edit `nr_enemy_tags.json` / `nr_enemy_roster.json` directly |
| `script_spawn` | `manual_promotions.json` (Ancestor Spirit, Grafted Scion, Nameless King, Storm King) | Edit `manual_promotions.json` |
| `er_heritage_v1` | This file | Delete `er_heritage_imports.json` or set `enabled: false` |

If a future batch (`er_heritage_v2`, `dlc_heritage_v1`, etc.) is added later,
it goes in its own file with its own source tag and gets added to
`V3_TARGET_ONLY_SOURCES`. Each batch stays cleanly removable.

## Uncertain prefixes (NOT included — opt-in later)

The c2xxx range has 4 more chr-only prefixes whose identity I couldn't
confirm without ER docs:

- **c2051** — possibly Elden Beast (Radagon's second phase) or a Marika
  variant
- **c2070** — uncertain; already in `V3_EXCLUDE_PREFIXES` (system/template
  exclusion). May be a Mohg variant or cinematic-only chr.
- **c2170** — possibly Lichdragon Fortissax
- **c2180** — possibly Dragonlord Placidusax

To opt in: identify them in playtest (force-spawn via the diagnostic-mode
`non_fragile_baseline_cp` flag) then extend `er_heritage_imports.json`
with appropriate tags + variants. Same `_source: "er_heritage_v1"` so they
fold into the same removal mechanism.

## Risks / playtest checklist

The playtest verification approach mirrors `manual_promotions.json`:

1. **CTD on cell-load.** If a chr's chr file is incomplete in NR (asset
   present in `chr/` but missing required components for the model loader),
   the cell containing a placement crashes. Symptom: client CTDs entering
   the area where the rando placed the chr. Mitigation: remove that chr's
   entry from this file.

2. **Dormant spawn (the failure mode of the previous Tier-A dormant_imported
   work).** Chr appears but never aggros — stuck in idle pose, doesn't
   respond to player presence. Different from CTD: the cell loads fine, but
   AI never activates. Mitigation: same — remove the entry. May also
   indicate `npc_param_id` resolution failure (the synthetic ID points at
   nothing in regulation.bin).

3. **Wrong-tier placement.** A boss-class chr lands at a humanoid-grunt
   slot and the encounter feels off (fights happen in narrow corridors,
   chr clips into geometry). Mitigation: add the chr to
   `V3_NIGHT_BOSS_CALIBER_TARGETS` so the engine routes it only to NB
   anchor slots, plus `V3_UNIQUE_TARGET_CAPS = 1` for once-per-run
   discipline.

4. **Multiplayer compatibility.** The chr files ship in NR's regulation,
   so coop partners on vanilla NR have them on disk too. But if their
   regulation.bin doesn't have matching `NpcParam` for the synthetic IDs,
   sync behavior diverges between host and client. Test in coop before
   relying on these in non-solo runs. Currently NOT added to
   `V3_HERITAGE_ALL_PREFIXES` so `multiplayer_safe` toggle does not gate
   them — flip that to add it if coop CTDs are observed.

## Workflow for testing one chr at a time

To probe a single chr (say, c2010 Margit), use the diagnostic-mode flag
in the GUI:

1. Set `disable_resilient_filter` ON (forces fragile-slot placements to
   come from the diagnostic pool)
2. Set `diagnostic_test_targets` to `c2010` (limits the diagnostic pool to
   just this chr)
3. Re-shuffle, install MSBs in me3, walk a few maps

Margit will show up at every fragile-slot placement that's chr-compatible.
If you encounter several without CTD or dormancy, the import is functional.
Repeat per chr.

If a chr fails this test, remove only its entry from
`er_heritage_imports.json` and continue with the rest.
