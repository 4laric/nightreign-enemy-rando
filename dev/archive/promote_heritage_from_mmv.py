"""promote_heritage_from_mmv.py

One-time-batch promotion: for every c-prefix listed in
data/heritage_pack.json that doesn't yet have engine-side identity in
data/nr_enemy_tags.json, fold in tag + variant data from
data/mmv_imports.json so the chr survives MMV being disabled.

Why this exists
---------------
heritage_pack.json is a manifest of OWNERSHIP — it tells the
heritage_pack loader "these c-prefixes are heritage; remove them when
the pack is disabled." It does NOT carry the tag data (tier, sizing,
arena flags) or the variant data (npc_param_id, think_param_id,
variant_name, hp) that the engine needs to actually PLACE a chr at a
slot. That data has to already live in nr_enemy_tags.json + the
roster JSON.

For chrs that were registered in heritage_pack.json but only have
their tag/variant data in mmv_imports.json, that means: under MMV
ENABLED the engine sees them via MMV's authoritative override (and
they work, modulo any MMV-blacklist), but under MMV DISABLED the
mmv_imports loader early-returns and the chrs have no engine identity
at all. heritage_pack.json registration alone is dormant.

This script does a one-time data-layer promotion: it copies the
MMV tag+variant data over into nr_enemy_tags.json + the roster JSON,
rewriting `_source: "mmv_import"` → `_source: "heritage"` and tagging
with `_heritage_promoted_from_mmv: true` for provenance.

CAVEAT: this is DATA-LAYER ONLY. The promotion makes the chr survive
MMV disable in the engine's bookkeeping. Whether the chr is actually
PLAYABLE in-game still depends on the underlying chrbnd/anibnd files
being on disk. For chrs whose only on-disk assets are in the user's
MMV install (the typical case for the 19 migrations), disabling MMV
will leave the engine *trying* to spawn the chr but the chr files
won't be found at runtime. The full migration story is:

  1. heritage_chr_import.py copies ER chr assets → NR's chr/ dir
  2. This script promotes tag+variant data MMV → heritage layer
  3. heritage_pack.json carries the manifest registration (already
     done out-of-band)
  4. MMV can then be removed entirely or kept around for additional
     cross-game bosses

Without step 1, you've changed bookkeeping but the chr is still
runtime-dependent on MMV. Use this script accordingly.

Semantics
---------
For each cp in heritage_pack.json['tags']:

  Case A: cp NOT in nr_enemy_tags.json AND cp has MMV tag
    → PROMOTE. Build heritage-flavored tag from MMV tag (strip MMV-
      specific keys, add heritage markers). Build heritage-flavored
      variants from MMV variants. Write both.

  Case B: cp NOT in nr_enemy_tags.json AND cp has NO MMV tag
    → SKIP with warning. Needs heritage_chr_import.py + manual
      tag/variant authoring (the chr was added to heritage_pack
      ahead of its data; this is true for things like c5120 Bayle,
      c5131/c5132/c5140/c5141 Messmer phase 2, c5194 Spider Scorpion
      small variant).

  Case C: cp already in nr_enemy_tags.json with _source = 'heritage'
    → SKIP silently. Already promoted in an earlier pass.

  Case D: cp already in nr_enemy_tags.json with _source != 'heritage'
    → SKIP with warning. The cp has an existing tag from another
      source (e.g. manual_retier_v0.24.x). The user can decide
      whether to re-source to heritage. This script does not
      overwrite existing tag data.

Idempotency
-----------
Running twice with no other changes is a no-op on the second run.
All four cases short-circuit on second invocation: Case A becomes
Case C, Case B stays Case B, etc.

MMV BLACKLIST INTERACTION (important)
-------------------------------------
Two of the promotable cps (c2030 Rennala, c6231 Perfumer) are in
MMV's blacklist_when_active for legitimate MMV-specific reasons
(c2030: ai_broken in MMV's port; c6231: ctd_unidentified in MMV's
port). After promotion:

  - With MMV ENABLED: MMV's tag overwrites the heritage tag (per
    mmv_imports loader semantics, MMV is authoritative). The
    blacklist still fires against c2030/c6231 c-prefixes. NO CHANGE
    in behavior from before promotion.

  - With MMV DISABLED: the heritage tag survives in
    nr_enemy_tags.json. No blacklist. The chr is engine-available
    PROVIDED the chr assets are on disk (which they won't be unless
    heritage_chr_import.py has run, per the caveat above).

So promotion is safe; whether c2030/c6231 actually play is a
separate gating question downstream.
"""
import json
import sys
from pathlib import Path
from collections import OrderedDict


# Keys in MMV tags that don't translate to heritage tag schema.
# These are MMV-specific provenance, blacklist reasoning, and audit
# notes that don't apply to a heritage chr (which has its own
# provenance fields).
MMV_TAG_KEYS_TO_DROP = {
    '_source',
    '_confidence',
    '_tier_note',
    '_size_correction_v0_26_x',
    '_placement_bias_note_v0_23_71',
    '_placement_bias_note_v0_23_72',
    # 'variants' (the count) is kept — it matches heritage schema
}

# Keys in MMV variants that don't translate to heritage variant
# schema. Heritage variants are leaner (no sample_maps, no
# _source string, no count).
MMV_VARIANT_KEYS_TO_DROP = {
    '_source',
    'count',
    'sample_maps',
}


def build_heritage_tag(cp, mmv_tag, heritage_pack_entry):
    """Convert an MMV tag into a heritage-flavored tag.

    Strips MMV-specific provenance keys, adds heritage markers,
    and harmonizes the display name with what heritage_pack
    declares (heritage_pack's name wins; it's the manifest of
    record for human-readable names).
    """
    out = OrderedDict()
    # Heritage-specific markers, ordered first for readability.
    out['_heritage_imported'] = True
    out['_heritage_promoted_from_mmv'] = True
    out['_source'] = 'heritage'

    # Copy MMV fields, dropping MMV-specific keys and the name+source
    # we're rewriting.
    for k, v in mmv_tag.items():
        if k in MMV_TAG_KEYS_TO_DROP:
            continue
        if k in ('name', '_source'):
            continue
        out[k] = v

    # Name from heritage_pack — it's the canonical manifest.
    out['name'] = heritage_pack_entry.get('name', mmv_tag.get('name', cp))
    return dict(out)


def build_heritage_variant(mmv_variant):
    """Convert an MMV variant into a heritage-flavored variant."""
    out = OrderedDict()
    # Copy through, dropping MMV-specific keys.
    for k, v in mmv_variant.items():
        if k in MMV_VARIANT_KEYS_TO_DROP:
            continue
        out[k] = v

    # Heritage marker — same field the existing heritage variants use.
    out['_heritage_imported'] = True

    # `hp` field: heritage variants carry it as a top-level field.
    # MMV variants don't have it (their tag carries hp_median at the
    # tag level instead). Leave hp absent here; downstream consumers
    # fall back to the tag's hp_median when variant hp is missing.

    return dict(out)


def main(project_root: Path, heritage_pack_path: Path, dry_run: bool):
    data_dir = project_root / 'data'

    # --- Load inputs ---
    with open(heritage_pack_path, encoding='utf-8') as f:
        heritage_pack = json.load(f)
    with open(data_dir / 'mmv_imports.json', encoding='utf-8') as f:
        mmv = json.load(f)
    with open(data_dir / 'nr_enemy_tags.json', encoding='utf-8') as f:
        nr_tags = json.load(f)
    with open(data_dir / 'nr_enemy_roster.json', encoding='utf-8') as f:
        nr_roster = json.load(f)

    hp_tags = heritage_pack['tags']
    mmv_tags = mmv['tags']

    # Index MMV variants by c_prefix for O(1) lookup.
    mmv_variants_by_cp = {}
    for v in mmv.get('variants', []):
        mmv_variants_by_cp.setdefault(v['c_prefix'], []).append(v)

    # Existing variant npc_param_ids in roster — used to de-dup when
    # appending heritage variants.
    existing_variant_npc_ids = {
        v.get('npc_param_id') for v in nr_roster.get('all_variants', [])
    }

    # --- Categorize ---
    promoted = []          # Case A
    skipped_no_source = [] # Case B
    skipped_already_heritage = []  # Case C
    skipped_other_source = []      # Case D

    for cp in sorted(hp_tags.keys()):
        if cp in nr_tags:
            existing_src = nr_tags[cp].get('_source', '?')
            if existing_src == 'heritage':
                skipped_already_heritage.append(cp)
            else:
                skipped_other_source.append((cp, existing_src))
            continue
        # Not in nr_tags — needs promotion or skip.
        if cp not in mmv_tags:
            skipped_no_source.append(cp)
            continue
        promoted.append(cp)

    # --- Apply promotions ---
    new_tags_count = 0
    new_variants_count = 0

    for cp in promoted:
        # Tag
        heritage_tag = build_heritage_tag(cp, mmv_tags[cp], hp_tags[cp])
        nr_tags[cp] = heritage_tag
        new_tags_count += 1

        # Variants
        for mv in mmv_variants_by_cp.get(cp, []):
            nid = mv.get('npc_param_id')
            if nid in existing_variant_npc_ids:
                # Variant already in roster — don't double-add.
                continue
            heritage_variant = build_heritage_variant(mv)
            nr_roster.setdefault('all_variants', []).append(heritage_variant)
            existing_variant_npc_ids.add(nid)
            new_variants_count += 1

    # --- Report ---
    print(f"Promotion report ({'DRY RUN' if dry_run else 'APPLIED'})")
    print('=' * 60)
    print(f"Promoted (Case A): {len(promoted)} cps")
    for cp in promoted:
        nvar = len(mmv_variants_by_cp.get(cp, []))
        print(f"  {cp}: {hp_tags[cp]['name']} ({nvar} variants)")
    print()
    print(f"Skipped — no MMV source data (Case B): {len(skipped_no_source)} cps")
    for cp in skipped_no_source:
        print(f"  {cp}: {hp_tags[cp]['name']}")
    if skipped_no_source:
        print("  → these need heritage_chr_import.py or manual tag/variant authoring")
    print()
    print(f"Skipped — already heritage (Case C): {len(skipped_already_heritage)} cps")
    print()
    print(f"Skipped — other _source (Case D): {len(skipped_other_source)} cps")
    for cp, src in skipped_other_source:
        print(f"  {cp}: _source={src!r}")
    print()
    print(f"Net added: {new_tags_count} tags, {new_variants_count} variants")

    if dry_run:
        print("\nDRY RUN — no files written.")
        return

    # --- Write outputs ---
    out_tags_path = data_dir / 'nr_enemy_tags.json'
    out_roster_path = data_dir / 'nr_enemy_roster.json'
    with open(out_tags_path, 'w', encoding='utf-8') as f:
        json.dump(nr_tags, f, indent=2, ensure_ascii=False)
    with open(out_roster_path, 'w', encoding='utf-8') as f:
        json.dump(nr_roster, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_tags_path}")
    print(f"Wrote {out_roster_path}")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--project-root', default='.',
                   help='nightreign-enemy-rando repo root (default: cwd)')
    p.add_argument('--heritage-pack',
                   help=('Path to heritage_pack.json to use as the manifest '
                         '(default: <project-root>/data/heritage_pack.json). '
                         'Provide an alternate path when running with a '
                         'modified heritage_pack that has not yet been '
                         'committed to the project tree.'))
    p.add_argument('--dry-run', action='store_true',
                   help='Print the report but do not write any files.')
    args = p.parse_args()

    root = Path(args.project_root).resolve()
    hp_path = Path(args.heritage_pack).resolve() if args.heritage_pack \
        else root / 'data' / 'heritage_pack.json'

    if not root.exists():
        print(f"ERROR: project root not found: {root}", file=sys.stderr)
        sys.exit(1)
    if not hp_path.exists():
        print(f"ERROR: heritage_pack not found: {hp_path}", file=sys.stderr)
        sys.exit(1)

    main(root, hp_path, args.dry_run)
