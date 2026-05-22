#!/usr/bin/env python3
"""
audit_primary_identity.py — v0.23.59 audit for the primary-identity filter.

Loads tags + prefix_variants the same way oops_v3 does, then for each
c-prefix prints:

  - what the unfiltered variant pool looks like
  - what the filtered pool looks like (after _filter_primary_identity)
  - what's getting dropped

Highlights:
  * c-prefixes where the filter REMOVES variants (good — these are the
    multi-creature cases the patch is targeting)
  * c-prefixes where the filter would EMPTY the pool (bad — would silently
    fall through to unfiltered; means tag.name doesn't match any variant
    name and we're in soft-fallback territory)
  * c-prefixes in V3_PRIMARY_IDENTITY_NO_FILTER (skipped by design)

Run:    python3 audit_primary_identity.py
Run as: cd <rando_dir> && python3 audit_primary_identity.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

# Import the live functions/data from oops_v3
sys.path.insert(0, '.')
import oops_v3 as O


def load():
    """Mirror oops_v3's tag + variant load order."""
    # v0.23.71: route through engine's _data_path so the JSON resolves
    # under data/ (new layout) or root (legacy). Same path resolution
    # as the engine itself.
    tags = json.load(open(O._data_path('nr_enemy_tags.json')))
    mmv_path = O._data_path('mmv_imports.json')
    if Path(mmv_path).exists():
        mmv = json.load(open(mmv_path))
        for cp, t in mmv.get('tags', {}).items():
            tags[cp] = t
        prefix_variants = defaultdict(list)
        for v in mmv.get('variants', []):
            prefix_variants[v['c_prefix']].append(v)
    else:
        mmv = {}
        prefix_variants = defaultdict(list)
    return tags, prefix_variants, mmv


def main():
    tags, prefix_variants, mmv = load()

    no_filter = O.V3_PRIMARY_IDENTITY_NO_FILTER

    rows_filtered = []   # filter actually drops variants
    rows_unchanged = []  # filter is a no-op (already 1:1 or all match)
    rows_empty = []      # filter would empty the pool (soft fallback fires)
    rows_skipped = []    # in NO_FILTER

    for cp in sorted(prefix_variants.keys()):
        variants = prefix_variants[cp]
        if not variants:
            continue
        tag = tags.get(cp)
        name = (tag or {}).get('name', '') or '<no name>'
        # Run filter
        if cp in no_filter:
            rows_skipped.append((cp, name, len(variants)))
            continue
        filtered = O._filter_primary_identity(variants, tag)
        if not tag or not (tag.get('name') or '').strip():
            # No identity to match against → filter is a no-op
            rows_unchanged.append((cp, name, len(variants), len(filtered)))
            continue
        kept = {v['npc_param_id'] for v in filtered}
        dropped = [v for v in variants if v['npc_param_id'] not in kept]
        if not dropped:
            rows_unchanged.append((cp, name, len(variants), len(filtered)))
        elif filtered is variants:
            # Soft fallback fired: tag.name matched zero variants, pool unchanged
            rows_empty.append((cp, name, len(variants),
                               sorted({v.get('mmv_name', '') for v in variants})))
        else:
            rows_filtered.append((cp, name, len(variants), len(filtered),
                                  [v.get('mmv_name', '') for v in dropped]))

    print(f"=== Primary-identity filter audit ===\n")
    print(f"Total c-prefixes scanned: {len(prefix_variants)}")
    print(f"  Filter active and dropping variants:   {len(rows_filtered)}")
    print(f"  Filter active but no-op (already clean): {len(rows_unchanged)}")
    print(f"  Filter would empty pool (soft fallback): {len(rows_empty)}")
    print(f"  Skipped (in NO_FILTER list):           {len(rows_skipped)}")
    print()

    if rows_filtered:
        print(f"--- Variants dropped by primary-identity filter ---")
        print(f"(these were causing the head-only / wrong-creature rendering)")
        for cp, name, n_in, n_out, dropped in rows_filtered:
            print(f"\n  {cp}  '{name}'  {n_in} -> {n_out}")
            from collections import Counter
            for vname, ct in Counter(dropped).most_common():
                print(f"      drop  {ct}x  {vname!r}")

    if rows_empty:
        print(f"\n--- c-prefixes where filter would empty the pool (soft fallback) ---")
        print(f"(tag.name doesn't substring-match any variant; consider revising)")
        for cp, name, n, vnames in rows_empty:
            print(f"  {cp}  tag.name={name!r}  variants ({n}): {vnames[:5]}"
                  f"{'...' if len(vnames) > 5 else ''}")

    if rows_skipped:
        print(f"\n--- c-prefixes in V3_PRIMARY_IDENTITY_NO_FILTER (intentional) ---")
        for cp, name, n in rows_skipped:
            print(f"  {cp}  '{name}'  ({n} variants)")


if __name__ == '__main__':
    main()
