#!/usr/bin/env python3
"""
enrich_boss_slots_with_intro_anchored.py — bump nr_boss_slots.json from
schema v1 to v2 by adding an `intro_anchored: bool` field to every slot
entry. The field comes from joining against scripted_intro_slots.json.

`intro_anchored: True`  → slot's chr entity_id appears as a chrEntityId arg
                          of one of the NB-anchor templates
                          (90015000/90015007/90015021/90015023/90015026)
                          OR as the arg to an inline DisplayBossHealthBar
                          call in the host map's EMEVD. This is the
                          structural "live boss encounter" signal.

`intro_anchored: False` → slot is tagged by chr-name match (e.g. "Astel",
                          "Mad Pumpkin Head", "Banished Knight") or by
                          suffix marker, but isn't wired through any NB
                          anchor in this MSB. Includes WONTFIX-class
                          frozen-pose risk slots and the broader
                          shifting-earth geometry-reuse population.

Use when the catalog's tier label alone isn't enough — e.g. when sampling
boss-tier sources for templating, or when gating intro-dependent chr
placements at boss-tier targets.

Re-run after every regeneration of scripted_intro_slots.json (which itself
re-runs after game patches or catalog rebuilds).

Usage:
    python enrich_boss_slots_with_intro_anchored.py \\
        --boss-slots data/nr_boss_slots.json \\
        --scripted-intro data/scripted_intro_slots.json \\
        --out data/nr_boss_slots.json   # overwrite in place
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boss-slots", required=True, type=Path)
    ap.add_argument("--scripted-intro", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--since-version",
        default="v0.24.85",
        help="Version string for schema v2 since_version (default v0.24.85)",
    )
    args = ap.parse_args()

    bs = json.loads(args.boss_slots.read_text(encoding="utf-8"))
    si = json.loads(args.scripted_intro.read_text(encoding="utf-8"))

    # Build the lookup: (msb, part_index) -> True for anchored slots
    anchored = {
        (s["msb"], s["part_index"]) for s in si["slots"]
    }

    # Validate schema we're operating on
    cur_schema = bs.get("_meta", {}).get("schema_version")
    if cur_schema is not None and cur_schema >= 2:
        print(
            f"Warning: input already at schema_version {cur_schema}. "
            "Re-enriching anyway (idempotent — overwrites intro_anchored).",
            file=sys.stderr,
        )

    # Apply the field
    stats = Counter()
    by_tier = {"anchored": Counter(), "not_anchored": Counter()}
    total_with_eid = 0
    total_zero_eid = 0
    for key, entries in bs.items():
        if key.startswith("_"):
            continue
        for s in entries:
            pi = s["pi"]
            eid = s.get("eid", 0)
            is_anchored = (key, pi) in anchored
            s["intro_anchored"] = is_anchored
            if eid == 0:
                total_zero_eid += 1
                stats["zero_eid"] += 1
                by_tier["not_anchored"][s["tier"]] += 1
            else:
                total_with_eid += 1
                if is_anchored:
                    stats["anchored"] += 1
                    by_tier["anchored"][s["tier"]] += 1
                else:
                    stats["geometry_or_secondary"] += 1
                    by_tier["not_anchored"][s["tier"]] += 1

    # Update _meta — preserve everything, bump version, add field doc
    meta = bs.setdefault("_meta", {})
    prior_version = meta.get("schema_version", 1)
    meta["schema_version"] = 2
    meta["schema_v2_since_version"] = args.since_version
    meta["schema_v2_added_at"] = datetime.now(timezone.utc).isoformat()
    meta["schema_v2_changelog"] = (
        f"Bumped from v{prior_version} to v2: added per-slot "
        "`intro_anchored: bool` field, derived by joining against "
        "data/scripted_intro_slots.json. No slot entries added or "
        "removed; all v1 fields preserved unchanged. See "
        "schema_v2_field_doc for semantics."
    )
    meta["schema_v2_field_doc"] = {
        "intro_anchored": (
            "True if the slot's chr entity_id is wired through an NB-anchor "
            "scripted intro in the host map's EMEVD (templated via "
            "90015000/7/21/23/26 or inline DisplayBossHealthBar). False "
            "otherwise — including catalog-tagged 'boss-tier' slots whose "
            "chrs are present in the MSB but not wired as live "
            "encounters (geometry-reuse in shifting-earth tiles, "
            "secondary-cohort chrs in multi-chr arenas, etc.). Source "
            "of truth: scripted_intro_slots.json _meta.emevd_signature. "
            "Use this field — not tier alone — when an operation needs to "
            "distinguish 'live boss encounter slot' from 'chr placed at "
            "boss-shaped geometry without scripted intro'."
        ),
    }
    meta["schema_v2_intro_anchored_stats"] = {
        "anchored": stats["anchored"],
        "geometry_or_secondary": stats["geometry_or_secondary"],
        "zero_eid": stats["zero_eid"],
        "total": total_with_eid + total_zero_eid,
        "by_tier_anchored": dict(by_tier["anchored"]),
        "by_tier_not_anchored": dict(by_tier["not_anchored"]),
    }

    args.out.write_text(json.dumps(bs, indent=2), encoding="utf-8")
    print(f"Wrote {args.out}")
    print(f"  schema_version: {prior_version} -> 2")
    print(f"  anchored: {stats['anchored']}")
    print(f"  geometry_or_secondary: {stats['geometry_or_secondary']}")
    print(f"  zero_eid: {stats['zero_eid']}")
    print(f"  total: {total_with_eid + total_zero_eid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
