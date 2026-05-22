"""Pack loaders — extraction of the inline pack-loading logic in
oops_v3.load_data() into per-pack functions.

WHY THIS EXISTS
---------------
Five asset packs land in load_data via ~500 lines of inline code:
heritage_pack, er_heritage_imports, mmv_imports, and (formerly)
bfer_imports v1 + v2. Each is conceptually independent — reads one
JSON, contributes tags + variants + (sometimes) gate-set additions
per pack-specific merge rules — but the inline structure made it
hard to:

  - Test any single loader in isolation (load_data is monolithic)
  - Add a new pack without touching load_data's middle
  - Reason about the snapshot-override flow per-pack

The v0.24.20 mp_safe leak was a structural consequence: the
heritage-prefix gate had to be manually extended every time a new
pack landed, and one slipped. Phase pre-0 (the _source-tagging
patch) fixed that gate by deriving it from tag metadata; this
package addresses the upstream cause by giving each pack a clean
seam.

DESIGN
------
Each loader is a function in its own file:

    apply_<pack_name>(pack_data, *, tags, roster, ...) -> stats_dict

`pack_data` is the already-loaded JSON dict with snapshot overrides
ALREADY APPLIED to _meta. Caller (load_data) handles file I/O and
snapshot override application centrally — loaders only see
already-prepared dicts.

`tags` and `roster` are mutated in place. The function returns a
stats dict so load_data can print the per-pack log line. Loaders
that need to mutate gate sets (BFER added to V3_NIGHT_BOSS_CALIBER,
mmv mutates V3_EXCLUDE_TARGET_PREFIXES) take those as keyword args
and mutate them in place too.

EXTRACTION ORDER
----------------
1. heritage_pack — disable-only toggle, simplest. THIS PHASE.
2. er_heritage_imports — vanilla-wins additive merge, ~80 lines.
3. mmv_imports — most complex (override + blacklist mechanism).

The behavior-lock from Phase 6 catches any subtle drift during
extraction.
"""
