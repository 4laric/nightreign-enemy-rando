# ER heritage v1 — Smithbox CSV imports

These two CSVs add NpcParam and NpcThinkParam rows for the 12 c2xxx ER NB-tier
bosses defined in `er_heritage_imports.json`. Without these rows in your
regulation.bin, the chr files will load but the rando-written placements
won't have stats/AI/drops — chrs will be silent statues at best, CTD at worst.

## CSV format quirks

Smithbox's CSV import uses naive comma-splitting (doesn't respect quoted
fields), and its exported headers carry a trailing comma that creates a
phantom empty column. The CSVs in this folder match that format exactly:

- Header line ends with a trailing comma (e.g., `...endPadding,`)
- Data rows have N-1 commas (one fewer than the header) and NO trailing comma
- Names contain no commas (replaced with spaces or other separators)
- Names contain no quote characters

If you regenerate these CSVs, follow the same conventions or Smithbox will
reject the import with a "wrong number of columns" error.

## What's in here

```
NpcParam_er_heritage_v1.csv      — 24 rows (12 chrs × 2 variants each)
NpcThinkParam_er_heritage_v1.csv — 12 rows (one think_param per chr)
```

The synthetic IDs follow the project's standard convention
(`cp_int * 10000 + variant_offset`), matching what the rando writes into
shuffled MSBs:

| chr  | NpcParam IDs           | NpcThinkParam ID | Template (NR analog)     |
|------|------------------------|------------------|--------------------------|
| c2010 Margit | 20100000, 20100010 | 20100000 | c2130 Morgott (same family) |
| c2030 Rennala P1 | 20300000, 20300010 | 20300000 | c4750 Grafted Monarch |
| c2031 Rennala P2 | 20310000, 20310010 | 20310000 | c4750 Grafted Monarch |
| c2050 Radagon | 20500000, 20500010 | 20500000 | c4750 Grafted Monarch |
| c2060 Mohg LoB | 20600000, 20600010 | 20600000 | c2130 Morgott (Mohg's twin) |
| c2110 Maliketh | 21100000, 21100010 | 21100000 | c2130 Morgott |
| c2120 Malenia | 21200000, 21200010 | 21200000 | c4750 Grafted Monarch |
| c2131 Morgott P2 | 21310000, 21310010 | 21310000 | c2130 Morgott (same chr) |
| **c2160 Astel** | 21600000, 21600010 | 21600000 | **c4620 Astel (same chr)** |
| **c2190 Godrick** | 21900000, 21900010 | 21900000 | **c4750 Godrick (same chr)** |
| c2191 Godrick P2 | 21910000, 21910010 | 21910000 | c4750 Godrick |
| c2200 Godfrey | 22000000, 22000010 | 22000000 | c4750 Grafted Monarch |

## How template inheritance works

Each new param row is a verbatim copy of the template chr's lowest-ID row,
with only `ID` and `Name` fields changed. This means imported chrs inherit:

- HP (e.g., Margit will spawn with Morgott's 2521 HP)
- Defense values
- `behaviorVariationId` → so attack pattern, hitboxes, and damage values
  use the template chr's existing AtkParam_Npc + BehaviorParam_Npc rows
- Drop tables (`itemLotId_enemy`, `itemLotId_map`)
- AI gates (think → battle goal IDs)
- All 356 NpcParam fields and all 110 NpcThinkParam fields

Practical implication: **Margit will fight like Morgott, Rennala will fight
like Grafted Monarch, Astel-c2160 will fight like Astel-c4620.** The chr
*model* (skeleton, animations, look) is c2010/c2030/c2160/etc. — that's
the whole visual point. The *behavior* mirrors a known-working NR chr.

The four "perfect-match" cases (c2131 Morgott, c2160 Astel, c2190 Godrick,
c2191 Godrick P2) inherit from their NR-shipping versions of the same chr,
so they should behave indistinguishably from the originals. The 8 others
inherit from a humanoid-boss-tier proxy.

## Import workflow with Smithbox

1. Open Smithbox, load your NR regulation.bin
2. Param Editor → navigate to `NpcParam`
3. File → Import CSV → select `NpcParam_er_heritage_v1.csv`
   - Smithbox should report "24 rows imported, 0 conflicts" (these IDs are
     all new — none exist in vanilla NR's regulation, by design)
4. Repeat for `NpcThinkParam` with `NpcThinkParam_er_heritage_v1.csv`
   (12 rows imported)
5. File → Save (writes back to regulation.bin)
6. Place the modified regulation.bin in your me3 mod profile

Verification: after save, search NpcParam for ID `21600000` — should
show "Astel, Naturalborn (Field Boss)" with HP 2708. If the row's there,
the import worked.

## What the rando does with these IDs

When the engine picks one of the 12 ER heritage chrs as a swap target, it
writes the synthetic `npc_param_id` (e.g., `21600000`) into the shuffled
MSB's Part entry. At runtime, the game looks up that ID in regulation.bin
to fetch HP / AI / drops. Two outcomes:

- **You imported the CSVs:** lookup succeeds → chr spawns with full stats
  inherited from the template, AI engages, killable, drops items.
- **You skipped the CSVs:** lookup fails → behavior is undefined per the
  game engine. Empirically (per the user's earlier Astel fight), the chr
  may still spawn with default/fallback stats and engage. Or it may
  silent-statue. Or it may CTD. Without imports, treat this as untested.

For coop: import the CSVs into ALL participating regulation.bins (host +
clients) so stats sync. If only the host has them, clients diverge.
Alternatively, leave `multiplayer_safe` ON in the rando GUI to keep these
chrs out of coop runs entirely.

## Updating these CSVs

If you regenerate `er_heritage_imports.json` (e.g., to add the 4 uncertain
c2xxx prefixes — c2051, c2070, c2170, c2180), regenerate these CSVs with:

```
python dev/er_heritage_csvs/generate.py
```

(Generator script TBD — reads er_heritage_imports.json, picks analogs,
writes CSVs. Currently the CSVs were generated one-off; a reproducible
script can be added if the batch grows.)

## Removing these imports

If you've already imported and want to roll back:

1. **Delete `er_heritage_imports.json`** from the project — engine no
   longer writes these IDs into MSBs (rando placements stop happening).
2. **In Smithbox**, navigate to NpcParam, filter by ID range
   `20100000 - 22000010`, delete the matching rows. Same for NpcThinkParam.
3. Save regulation.bin.

The IDs are all in the `20xxxxxx - 22xxxxxx` range (cp_int 2010-2200), and
none collide with vanilla NR rows (vanilla NR has zero rows in this range
for these specific c-prefixes — that's why we're authoring them).
