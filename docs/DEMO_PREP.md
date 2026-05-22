## Demo prep: per-seed boss healthbar names

This is the workflow for producing a randomized run where every on-screen boss
healthbar shows a name that matches the chr you're actually fighting — including
composite "Troll + Ulcerated Tree Spirit" labels for shared-bar squads where the
rando produced a heterogeneous group.

**If you're not doing the healthbar-rename demo and just want to rank seeds for
visually-interesting tile rolls, skip everything below and use:**

```
python healthbar_tools/prep_demo.py RANK-LITE --seeds-root seeds/ --top 10
```

That uses only the spoiler-driven criteria (NB arena distinctiveness +
tile-weighted memorable field placements). No `callsites.json`, no EMEVD
decompile, no FMG steps. The rest of this doc covers the full demo pipeline
which is heavier.

---

Tools (this folder):

  `audit_healthbar_callsites.py` — one-time static scan of `.emevd.dcx.js`
  `simulate_seeds.py` — local batch runner over a seed range
  `prep_demo.py` — ranks candidate seeds + builds the chr→nameId catalog
  `apply_healthbar_names.py` — generates a curatable name_table, then rewrites
                                `.js` files + emits an FMG additions JSON

The chr→nameId catalog and the callsite manifest are seed-agnostic and only
need to be rebuilt when the vanilla EMEVD changes (NR patch).

The seed-ranking step (`prep_demo.py RANK`) is tile-weighted: memorable field
placements are discounted by the per-MSB tile-presence rate in
`../data/msb_tile_probability.json`. See "Tile weighting" below.


## One-time setup

Decompile vanilla NR EMEVD with DarkScript3:

```
DarkScript3.exe path\to\nightreign\event\*.emevd.dcx
```

This drops `*.emevd.dcx.js` files next to the originals. Copy or symlink
them into a single dir, e.g. `vanilla_emevd_js/`.

```
python audit_healthbar_callsites.py SCAN vanilla_emevd_js/ \
    --out callsites.json
```

This produces `callsites.json`: every boss-wake handler call across all
EMEVD, with the schema info needed to know which arg position is a
chrEntityId vs a nameId vs a shared-bar group.


## Per-demo workflow

### 1. Sweep seeds

```
python simulate_seeds.py \
    --vanilla-msbs path\to\decompressed_vanilla_msbs \
    --out-root seeds \
    --seed-start 10000 \
    --seed-count 50 \
    --spoilers-only
```

`--spoilers-only` deletes the MSB outputs after each run so the seed dir
stays small (just `_spoilers.json` per seed). If you don't pass it, you
get full MSBs too — useful if you might play the seed directly.

### 2. Build the chr→nameId catalog

Any one spoiler from step 1 works:

```
python prep_demo.py BUILD-CATALOG \
    --callsites callsites.json \
    --spoiler seeds/seed10000/_spoilers.json \
    --out chr_to_nameid.json
```

This derives "vanilla c-prefix X used nameId N at callsite Y" from the
intersection of the callsite manifest and the spoiler's
`original.c_prefix` data. Used downstream so that when a swap targets a
c-prefix that already has a vanilla NR name (e.g. Tree Sentinel), we
reuse the existing FMG entry rather than minting a new one.

### 3. Rank candidates

```
python prep_demo.py RANK \
    --seeds-root seeds/ \
    --callsites callsites.json \
    --top 10
```

Scores every spoiler in `seeds/` on demo-fitness criteria:
- NB arena distinctiveness (heaviest weight)
- Distinct chrs hit at callsites
- Heterogeneous squad count (the squad-annotation demo moment)
- Memorable field placements (tile-weighted; see below)
- nameId collisions (small penalty)

Prints the top N with a breakdown. Pick a seed manually from this
shortlist — the score is a heuristic, not a verdict.

#### Tile weighting

The "Memorable field placements" criterion is multiplied by
P(player encounters the MSB in a vanilla expedition). This is computed from
`../data/msb_tile_probability.json` (or `msb_tile_probability.json` next to
`prep_demo.py` if you've placed it there). The file is auto-discovered.

CLI flag: `--tile-weighting {off|uniform|vanilla}` (default `vanilla`).

- `vanilla` (default): Default tile rolls 91.16%, each Shifting Earth 2.21%
  (vanilla EMEVD rates). A Cathedral swap (~85% presence) ends up at
  visibility ≈ 0.86; a Fingercreeper-nest swap (~5% presence) ends up at
  visibility ≈ 0.05. The score reflects how often the demo viewer will
  actually see each swap.
- `uniform`: Each tile equiprobable at 1/5. Matches the "Greatly increase
  one-off Shifting Earth" engine option being ON.
- `off`: Tile-agnostic MSBs sum to 1.0 (legacy behavior for the current
  MEMORABLE_FIELD list); tile-specific MSBs are still discounted to 0.2 per
  tile. Use this if you want to disable the visibility weighting.

If `msb_tile_probability.json` isn't found, `prep_demo.py` falls back to
the prefix heuristic in `_msb_tiles()` and prints a warning to stderr.

### 4. Generate the name table

For the chosen seed:

```
python apply_healthbar_names.py GENERATE \
    --spoiler seeds/seed12345/_spoilers.json \
    --callsites callsites.json \
    --chr-nameid chr_to_nameid.json \
    --out name_table.json
```

`name_table.json` lists every active healthbar slot in this seed with
the default name + nameId the tool picked. Status values per entry:

- `reuse_vanilla`: swapped chr matches a c-prefix already in
  `chr_to_nameid.json`. No FMG addition needed.
- `fresh_allocation`: swapped chr isn't in the vanilla catalog. A new
  nameId was allocated (starting from `fmg_id_base`, default 9700000000).
- `heterogeneous_squad`: shared-bar callsite with multiple distinct
  swapped chrs. A composite name was generated using "list with count"
  policy ("X + Y ×2"). Always requires fresh nameId.

### 5. Curate (optional but this is where the cute names go)

Open `name_table.json` and for any entry you want to override, edit
`user_override.new_name` to your custom string. The "Putrid Shaman of
the King Consort" mashup-name play happens here. You can also leave
all defaults — they're already correct chr names, just less playful.

### 6. Apply

```
python apply_healthbar_names.py APPLY \
    --name-table name_table.json \
    --in-emevd vanilla_emevd_js/ \
    --out-emevd patched_emevd_js/ \
    --fmg-additions fmg_additions.json
```

Produces:
- `patched_emevd_js/`: all the input `.js` files copied; the ones with
  rewrites get their nameId args modified at the precise arg positions.
- `fmg_additions.json`: mapping from new nameId → text. Feed this into
  your FMG editor (WitchyBND, etc.) to add the entries to whichever
  boss-name FMG NR loads.

### 7. Compile & ship

```
DarkScript3.exe patched_emevd_js/*.emevd.dcx.js
```

Drop the recompiled `.emevd.dcx` files into your me3 profile under
`<profile>/<package>/event/`. Drop the updated FMG into wherever your
mod loader expects it.

### 8. Test once before recording

Boot the seed, walk to one of the renamed encounters, confirm the
healthbar reads correctly. If it shows the vanilla name, the FMG
addition probably wasn't loaded; if it shows a blank or "???", the
nameId might be outside the FMG's expected range — bump `--fmg-id-base`
to a different prefix and re-run APPLY.


## Notes & caveats

- **CRLF preservation**: the rewriter preserves CRLF when present. Don't
  let your editor normalize line endings on the patched `.js` between
  rewrite and DSAS3 compile.

- **Auto-allocated nameId stability**: within a single run, identical
  text gets the same nameId (deduplication). Across runs, ids are
  allocated in the order the rewriter visits callsites — change the
  name_table contents and ids can shift. If you need stable ids across
  re-runs, set `user_override.new_name_id` explicitly on any entry you
  want pinned.

- **What this doesn't fix**: EMEVD-direct-spawn entities (the castle
  basement Red Wolf case) won't appear in the spoiler, so their
  callsites mark as `inactive_in_seed` and their nameIds stay vanilla.
  Those need the Generator-rewire workstream from the v0.24 plan.

- **Heterogeneous squad policy**: default is "list with count". If you
  want a different policy globally (e.g. "Squad of N"), the path is to
  set `user_override.new_name` per callsite during curation — the tool
  is intentionally policy-light beyond the default.

- **Tile data freshness**: `data/msb_tile_probability.json` is derived
  from `regulation.bin` at the version present when the data was
  generated. If a Nightreign patch updates regulation.bin (new patterns,
  altered POI placements), re-run `dev/derive_tile_data.py` against
  the new extracted params. See `dev/derive_tile_data.py --help` for
  the prerequisite (regulation.bin → .param files via SoulsFormats).

- **MSBs not in the tile-probability table** (Nightlord arenas, tile-base
  MSBs like m10/m11/m12/m13/m15, m60 open-world chunks) fall back to a
  prefix heuristic in `prep_demo.py:_msb_tiles()`. This is correct: those
  MSBs aren't POI-rolled, they're loaded by other game mechanisms. Keep
  them out of `MEMORABLE_FIELD` to avoid double-counting them against
  the `NB_ARENAS` criterion.
