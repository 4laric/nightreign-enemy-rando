# Data files

JSON data files loaded by the engine at runtime. Moved here in stages:
- v0.23.06: bulk slot / anchor / heritage-import-plan files
- v0.23.71: full consolidation — all roster, tag, import, terrain, and
  promotion JSONs moved here too

The engine's `_data_path()` helper checks `data/<file>` first, then
falls back to the project root if a file isn't found. So older installs
that still have JSONs at root keep working transparently.

## Files

### Roster + tagging (always loaded)

| File | Purpose | Loaded by |
|------|---------|-----------|
| `nr_enemy_roster.json` | Every NPCParam variant of every NR enemy: name, tier, anim hints, base movement params. ~770KB. | `oops_v3.load_data` |
| `nr_enemy_tags.json` | Per-c-prefix tag bundle: name, size, locomotion, anim_class, team, has_reward, source. The authoritative content/balance metadata. | `oops_v3.load_data`, GUI |
| `manual_promotions.json` | Vanilla NR enemies with NpcParam data but never placed in any MSB (Storm King, Nameless King, Ancestor Spirit, Grafted Scion). Re-introduced as swap targets via tagging only. | `oops_v3.load_data` |
| `vanilla_promotions_v1.json` | Additional vanilla NR chrs surfaced by tagging only (no Smithbox imports needed). `_source: vanilla_promotions_v1`. | `oops_v3.load_data` |

### Slot + terrain catalogs (built once per major change)

| File | Purpose | Loaded by |
|------|---------|-----------|
| `nr_all_slots.json` | Every recipient slot: map + part_index + source c_prefix. Used for cluster-lock map detection and SE-suffix MSB enumeration. | `oops_v3.load_data`, `_compute_se_msbs` |
| `nr_boss_slots.json` | Subset of `nr_all_slots.json` where the source is a boss-tier chr. Used for size-down rescue's at-risk tail computation. | `oops_v3.shuffle_msb_v3` rescue path |
| `t1_anchors.json` | Per-MSB anchor positions for POI proximity fragility detection. Anchors include placeholder clusters and encampments. | `oops_v3._load_t1_anchors`, `_compute_se_msbs` |
| `slot_terrain.json` | Per-slot terrain classification (on-mesh / off-mesh / edge-sentinel). Used for fragility-aware target filtering. | `oops_v3._load_slot_roughness`, `_load_off_mesh_slots` |

### Optional asset packs (gated by `_meta.enabled`)

| File | Purpose | Default state |
|------|---------|---------------|
| `bfer_imports.json` | Boss for Elden Ring v1 — 30+ ER/SOTE bosses ported to NR. | `_meta.enabled` based on user install |
| `bfer_imports_v2.json` | BFER v2 additions (Greyoll, Troll variant, size_class overrides). | Same |
| `er_heritage_imports.json` | DEPRECATED in v0.23.12. Early authoring experiment, replaced by BFER. `_meta.enabled=false` by default. | OFF |
| `heritage_pack.json` | 47 SOTE-flavored creatures (Bears, Imps, Messmer Soldiers). | OFF by default |
| `mmv_imports.json` | More Map Variations (MMV) cross-game boss imports — Malenia, Maliketh, Slave Knight Gael, etc. | OFF by default; flip via GUI checkbox |

### Other (build-time / dev)

| File | Purpose |
|------|---------|
| `batch_import_plan_comprehensive.json` | Heritage pack's import manifest. Used by the GUI's heritage-scan tab to show pretty names during chr/ folder scan. |
| `nightlord_pools.json`, `nightlord_expedition_table.json` | Nightlord targeting tables, used by `oops_all_anyone.py`. |

## When to regenerate

Most users never touch these. If you're modifying the engine and adding
new chrs, regenerate via the dev tools:

- `nr_enemy_roster.json` — `dev/build_roster.py`
- `nr_enemy_tags.json` — hand-curated; see CHANGELOG entries for tag-edit history
- `nr_all_slots.json` — `dev/extract_msb_slots.py`
- `nr_boss_slots.json` — manual filter from `nr_all_slots.json` keeping only entries where the source c-prefix is boss-tier
- `t1_anchors.json` — `dev/audit_encampment_anchors.py` and `dev/audit_placeholder_clusters.py`
- `slot_terrain.json` — `build_slot_terrain.py` (works against a vanilla MSB dump)

## Backwards compatibility

If you're upgrading from a pre-v0.23.71 install, these files used to be
at the project root. The engine's `_data_path()` helper falls back to
root, so legacy layouts keep working without changes. You can move
the JSONs into `data/` whenever you like; no functional difference.

To consolidate manually:

```
mkdir -p data
mv *.json data/   # if you have other top-level JSONs to keep, move only the listed ones
```

The engine will pick them up from `data/` on next run.
