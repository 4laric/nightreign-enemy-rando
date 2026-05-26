#!/usr/bin/env python3
"""audit_genuine_variants.py — measure real variant diversity per c-prefix,
and emit a prune list of redundant context-duplicate NpcParam rows.

The NR enemy roster carries ~3100 NpcParam rows, but most of those rows
are the SAME enemy re-authored once per placement context (Castle /
Evergaol / Encampment / field) plus untested post-DLC-dump "ghost" rows.
The model, animations and behavior the player sees are keyed on the
c-prefix, not on the NpcParam row, so context-duplicate rows are
interchangeable and pruning them does not degrade the rando pool.

GENUINE-IDENTITY KEY
--------------------
    (behaviorVariationId, think_param_id // 1000)

  * behaviorVariationId  — selects the behbnd behavior subset; a
    different value is a genuinely different fight (moveset).
  * think_param_id // 1000  — the AI-script FAMILY. For c3010 the
    families 30100 / 30101 / 30102 are exactly the Shield / Dual Swords
    / Halberd Banished Knights; the trailing 3 digits are per-placement
    think sub-variants and do NOT count as diversity. think_param_id==0
    (generic) collapses to one family, which is correct.

has_reward is DELIBERATELY NOT in the key. Reward is collapsed: two
rows identical except for has_reward are the same genuine variant. But
the prune list applies a REWARD-PREFERENCE RULE when picking which row
to keep — within a genuine cluster, if any row is has_reward=True the
non-reward rows are pruned and a reward row is kept. Because the kept
NpcParam row already carries its itemLotId/rewardItemLot, that variant
then drops its reward wherever the rando places it, with no change to
oops_v3.py. has_reward never gates the identity key, only the keep
choice.

Everything else NOT in the key (hp, getSoul, itemLotId_enemy,
rewardItemLot_*, scaling speffects) is per-placement bookkeeping the
rando re-derives, so it does not count toward genuine diversity.

KNOWN LIMITATION: think_param_id family is a strong loadout signal but
not perfect. Some chrs route a whole placement context through one
shared AI family regardless of weapon — e.g. c3010's Castle-context
Banished Knights all use think_family 30100, while the
Evergaol/Encampment ones split cleanly into 30100/30101/30102. So a
'genuine' count can slightly UNDER-count; it will not over-count.
Treat it as a tight lower bound and eyeball --show-clusters when a
cluster's name list looks broad.

GHOST ROWS
----------
A row is "ghost" when `_source == post_dlc_dump` or `sample_maps` is
empty — vanilla NR never instantiated it. _filter_canonical_variants
already drops these when real variants exist.

PRUNE LIST  (--emit-prune-list PATH)
------------------------------------
Writes JSON listing npc_param_ids safe to exclude from placement.
Within each (c_prefix, genuine-key) cluster:
  * REWARD-PREFERENCE: if any row is has_reward=True, only reward rows
    are eligible to keep; the non-reward duplicates are pruned (same
    fight, strictly worse — no drop).
  * among eligible rows, canonical (vanilla-placed) beats ghost.
  * default keeps all eligible canonical rows; a ghost-only cluster
    keeps one ghost so the variant is not lost.
This never fully drops a genuine variant — every cluster keeps >=1
row — so the rando pool's set of genuine variants is unchanged.

--collapse-canonical additionally keeps exactly one row per genuine
key (best by reward > canonical > lowest-id). Still pool-safe, but
discards intentional per-placement hp scaling on dropped rows — opt-in.

The output also reports tier_coverage: of miniboss-and-above
c-prefixes, how many have a reward row anywhere (fully handled by the
rule) versus the residual gap that would still need tier-driven
reward synthesis if you want EVERY miniboss+ slot rewarded.

VARIATION REPORT  (--variation-report)
--------------------------------------
Reports what NpcParam columns actually differ WITHIN each genuine
cluster, bucketed as scaling (hp / defense / poise / spEffects),
economy (runes, item lots), cosmetic (model masks, materials, sound,
LOD, networking), or meaningful (anything else). Answers "how much of
the variant explosion is just the same enemy rescaled / reskinned?"
Pair with --show-clusters for a per-cluster line.

Usage:
    python3 dev/audit_genuine_variants.py [--csv PATH] [--roster PATH]
        [--min-rows N] [--sort {inflation,rows,prefix}] [--show-clusters]
        [--emit-prune-list PATH] [--collapse-canonical]
        [--variation-report]

Exit code is always 0; this is a reporting tool.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_npcparam(csv_path):
    """ID(str) -> {col: value} for the columns we need."""
    wanted = ["behaviorVariationId", "teamType", "threatLv",
              "toughness", "hp", "getSoul"]
    out = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            out[row["ID"]] = {k: row.get(k, "") for k in wanted}
    return out


def load_npcparam_full(csv_path):
    """ID(str) -> full {col: value} row, plus the column list.

    Used by --variation-report, which needs every column to see what
    actually varies within a genuine cluster. Returns (rows, columns).
    """
    rows = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        cols = [c for c in (r.fieldnames or []) if c]
        for row in r:
            rows[row["ID"]] = row
    return rows, cols


def _column_category(col):
    """Bucket an NpcParam column for the variation report.

      ignore    — ID (row primary key, always differs; meaningless)
      label     — Name (the placement-context label, e.g. 'Castle- Shield')
      scaling   — hp/mp, defenses, poise/stamina, resists, spEffects
                  (NR scales enemies mostly through spEffect rows, not hp)
      economy   — runes, item lots, drop bookkeeping
      cosmetic  — model masks, materials, sounds, LOD, networking, hitbox
      meaningful— anything else (teamType, moveType, vowType, ...)

    'meaningful' is a deliberate catch-all: it over-counts (teamType
    variation usually just means a team=26 cinematic row is mixed in,
    which the avoid-list already handles), so treat it as an upper
    bound on genuine behavioural difference.
    """
    if col == "ID":
        return "ignore"
    if col == "Name":
        return "label"
    if col in ("hp", "mp"):
        return "scaling"
    if (col.startswith("def_") or col.endswith("DamageCutRate")
            or col.endswith("GuardCutRate") or col.startswith("resist_")
            or col.endswith("GuardResist") or col.startswith("resistCorrectId")
            or col.startswith("poiseBonusRate")):
        return "scaling"
    if col in ("toughness", "superArmorDurability", "saRecoveryRate",
               "saGuardCutRate", "stamina", "staminaRecoverBaseVel",
               "toughnessRecoverCorrection", "superArmorRecoverCorrection",
               "superArmorBrakeKnockbackDist", "poiseBonusMax",
               "knockbackRate", "flickDamageCutRate", "staminaGuardDef"):
        return "scaling"
    if (col.startswith("spEffectID") or col in (
            "day2SpEffectID", "multiPlayCorrectionParamId",
            "chaosMatchingCorrectParamId", "chaosMatchingSpEffectSetParamId")):
        return "scaling"
    if col in ("getSoul", "itemLotId_enemy", "itemLotId_map",
               "rewardItemLot_1", "rewardItemLot_2", "humanityLotId",
               "dropType", "sleepCollectorItemLotId_enemy",
               "sleepCollectorItemLotId_map", "chaosMatchingRewardLotId",
               "chaosMatchingItemLotId", "isSoulGetByBoss",
               "excludeGroupRewardCheck", "threatLv"):
        return "economy"
    if (col.startswith("modelDispMask") or "aterial" in col or "Sfx" in col
            or "Decal" in col or "decal" in col or "Sync" in col
            or "Lod" in col or "loth" in col
            or col.startswith("autoFootEffect") or col.startswith("ghostModel")
            or col.startswith("normalChange")
            or col.startswith("RetargetReference")
            or col.startswith("lockGazePoint")
            or col.startswith("dbgBehavior")
            or col in ("updateActivatePriolity", "SfxResBankId",
                       "SoundBankId", "SoundAddBankId", "paintRenderTargetSize",
                       "disableInitializeDead", "disableRespawn",
                       "hearingHeadSize", "defaultLodParamId", "hitHeight",
                       "hitRadius", "chrHitHeight", "chrHitRadius",
                       "hitYOffset", "sfxSize", "weight", "enableSoundObjDist",
                       "networkWarpDist")):
        return "cosmetic"
    return "meaningful"


def variation_report(records, full_rows, columns, show_clusters):
    """Print, per genuine cluster, what NpcParam columns vary and which
    category they fall in. Answers 'how much of the variant explosion
    is just rescaling/reskinning the same enemy?'"""
    from collections import Counter

    multi = []
    for d in records:
        for key, members in d["clusters"].items():
            ids = sorted({str(m["npc_param_id"]) for m in members
                          if str(m["npc_param_id"]) in full_rows})
            if len(ids) > 1:
                multi.append((d["cp"], d["name"], key, ids))

    buckets = Counter()
    meaningful_cols = Counter()
    scaling_examples = []
    for cp, name, key, ids in multi:
        varying = [c for c in columns
                   if len({full_rows[i].get(c) for i in ids}) > 1]
        cats = {_column_category(c) for c in varying}
        cats.discard("ignore")
        cats.discard("label")
        for c in varying:
            if _column_category(c) == "meaningful":
                meaningful_cols[c] += 1
        if not cats:
            buckets["identical apart from ID/Name"] += 1
        elif cats <= {"scaling"}:
            buckets["scaling only"] += 1
            if len(scaling_examples) < 8:
                hps = sorted({full_rows[i].get("hp") for i in ids},
                             key=lambda x: int(x) if str(x).isdigit() else 0)
                scaling_examples.append((cp, name, key, ids, hps))
        elif cats <= {"scaling", "economy"}:
            buckets["scaling + economy"] += 1
        elif cats <= {"scaling", "economy", "cosmetic"}:
            buckets["scaling + economy + cosmetic"] += 1
        else:
            buckets["has a meaningful diff"] += 1

        if show_clusters:
            bvid, tfam = key
            cat_list = ", ".join(sorted(cats)) or "none"
            print(f"  {cp} bvid={bvid} tf={tfam}  {len(ids)} rows  "
                  f"varies: {cat_list}")

    total = len(multi)
    print("=" * 78)
    print("VARIATION REPORT  —  what differs WITHIN a genuine cluster")
    print("=" * 78)
    print(f"multi-row genuine clusters analysed: {total}")
    print()
    order = ["identical apart from ID/Name", "scaling only",
             "scaling + economy", "scaling + economy + cosmetic",
             "has a meaningful diff"]
    for b in order:
        n = buckets.get(b, 0)
        pct = (100 * n / total) if total else 0
        print(f"  {b:32s} {n:>5}  ({pct:4.1f}%)")
    redundant = sum(buckets.get(b, 0) for b in order[:4])
    print("-" * 78)
    print(f"  effectively the same fight (top 4 rows): {redundant}/{total}  "
          f"({100*redundant/total:.1f}%)" if total else "  (no clusters)")
    print()
    print("meaningful columns ranked by clusters they vary in")
    print("(teamType usually = a team=26 cinematic row mixed in — already")
    print(" handled by V3_AVOID_VARIANT_NPC_IDS; treat as an upper bound):")
    for c, n in meaningful_cols.most_common(12):
        print(f"  {c:28s} {n}")
    print()
    print("scaling-only cluster examples (same enemy, different numbers):")
    for cp, name, key, ids, hps in scaling_examples:
        hp_note = (f"hp {hps[0]}..{hps[-1]}"
                   if len(hps) > 1 else "hp constant (speffect-scaled)")
        print(f"  {cp} ({name}) — {len(ids)} rows, {hp_note}")
    print("=" * 78)


def think_family(think_param_id):
    """AI-script family — floor the think param by 1000 so per-placement
    sub-variants collapse but real loadout families stay distinct."""
    try:
        return int(think_param_id) // 1000
    except (TypeError, ValueError):
        return 0


def identity_key(param_row, think_param_id):
    """Genuine-identity tuple for one variant row: (bvid, think_family).

    param_row may be None when the npc_param_id is absent from
    NpcParam.csv (MMV/ER imports). In that case bvid is a sentinel that
    cannot collapse with CSV-backed rows, so such variants are never
    silently merged.
    """
    bvid = param_row.get("behaviorVariationId", "") if param_row else "NO_CSV_ROW"
    return (bvid, think_family(think_param_id))


def is_ghost(variant):
    """Row vanilla NR never instantiated (dump-only / no placements)."""
    if variant.get("_source") == "post_dlc_dump":
        return True
    return not variant.get("sample_maps")


# Fallback if oops_v3.py cannot be scanned — keep loosely in sync with
# V3_VARIANT_TRIGGER_MARKERS in oops_v3.py.
_DEFAULT_TRIGGER_MARKERS = [
    "Night Horde", "Prelude", "Sparring", "Dummy", "Unlock Fight",
    "Cutscene", "Story", "Hidden", "Trigger", "Unused",
]


def load_trigger_markers(root):
    """Scan V3_VARIANT_TRIGGER_MARKERS out of oops_v3.py source.

    build_per_prefix_data drops any variant whose name contains one of
    these markers, so the prune generator must avoid keeping such a
    variant as a cluster's sole representative — otherwise that genuine
    variant would vanish from the random pool. Source-scanned (not
    imported) to dodge oops_v3's import-time side effects, same pattern
    as audit_team26_variants.py.
    """
    return _scan_str_list(root, "V3_VARIANT_TRIGGER_MARKERS",
                          _DEFAULT_TRIGGER_MARKERS)


# Fallback emerge markers — keep loosely in sync with
# V3_EMERGE_VARIANT_MARKERS in oops_v3.py.
_DEFAULT_EMERGE_MARKERS = [
    "(Spirit)", "(Night Boss Spirit)", "(Silvery)", "(Silver)",
    "(Phantom)", "(Apparition)", "(Echo)", "(Wraith)", "(Risen)",
    "(Summoned)", "(Summons)",
]


def load_emerge_markers(root):
    """Scan V3_EMERGE_VARIANT_MARKERS — emerge-spawn variants that
    pick_variant_for_tier filters (soft) and that glitch if placed."""
    return _scan_str_list(root, "V3_EMERGE_VARIANT_MARKERS",
                          _DEFAULT_EMERGE_MARKERS)


def load_avoid_ids(root):
    """Scan V3_AVOID_VARIANT_NPC_IDS out of oops_v3.py source.

    This is a HARD filter in pick_variant_for_tier — an avoid-listed
    npc_param_id is removed and can return None. The prune generator
    must therefore never keep an avoid-listed row as a cluster's
    representative while pruning its clean siblings. Returns a set of
    ints; empty set if the constant cannot be located.

    Comment-aware: the avoid block carries explanatory comments that
    mention OTHER npc_param_ids and seed numbers (e.g. "seed 356064").
    A naive number-grep sweeps those in as false avoid entries, which
    then makes innocent rows look non-survivable. Each line's code
    portion (before '#') is parsed; 8-digit ids only.
    """
    import re
    path = os.path.join(root, "oops_v3.py")
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return set()
    m = re.search(r"V3_AVOID_VARIANT_NPC_IDS\s*=\s*\{(.+?)\n\}",
                  src, re.DOTALL)
    if not m:
        return set()
    ids = set()
    for code in _code_lines(m.group(1)):
        ids.update(int(t) for t in re.findall(r"\b(\d{8,})\b", code))
    return ids


def _code_lines(block):
    """Yield the code portion (before any '#' comment) of non-blank
    lines in a source block. Lets the scanners ignore numbers/strings
    that appear only inside comments."""
    for line in block.splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            yield code


def _scan_str_list(root, const_name, fallback):
    """Scan a `CONST = [ 'a', 'b', ... ]` string list from oops_v3.py,
    ignoring quoted text that appears inside comments."""
    import re
    path = os.path.join(root, "oops_v3.py")
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return list(fallback)
    m = re.search(const_name + r"\s*=\s*\[(.+?)\]", src, re.DOTALL)
    if not m:
        return list(fallback)
    vals = []
    for code in _code_lines(m.group(1)):
        for a, b in re.findall(r"'([^']+)'|\"([^\"]+)\"", code):
            vals.append(a or b)
    return vals or list(fallback)


def is_trigger_variant(variant, markers):
    """True if the variant name carries a scripted-spawn marker."""
    name = variant.get("variant_name") or ""
    return any(mk in name for mk in markers)


def build_records(params, variants):
    """Per-c-prefix analysis. Returns (records, no_csv_total)."""
    by_prefix = defaultdict(list)
    for v in variants:
        by_prefix[v["c_prefix"]].append(v)

    records = []
    no_csv_total = 0
    for cp, rows in by_prefix.items():
        name = next((r.get("variant_name") for r in rows
                     if (r.get("variant_name") or "").strip()), "?")
        clusters = defaultdict(list)        # identity_key -> [rows]
        canonical_keys = set()
        no_csv_rows = 0
        for r in rows:
            prow = params.get(str(r["npc_param_id"]))
            if prow is None:
                no_csv_rows += 1
            key = identity_key(prow, r.get("think_param_id"))
            clusters[key].append(r)
            if not is_ghost(r):
                canonical_keys.add(key)
        no_csv_total += no_csv_rows
        records.append({
            "cp": cp, "name": name, "rows": len(rows),
            "genuine": len(clusters),
            "canon_genuine": len(canonical_keys),
            "ghost_rows": sum(1 for r in rows if is_ghost(r)),
            "no_csv": no_csv_rows,
            "inflation": len(rows) / len(clusters) if clusters else 0.0,
            "clusters": clusters,
        })
    return records, no_csv_total


def _is_survivable(m, avoid_ids):
    """A row that survives pick_variant_for_tier's HARD filters: it has
    a non-empty variant_name and is not in V3_AVOID_VARIANT_NPC_IDS.
    A cluster whose kept representative is non-survivable could empty a
    c-prefix's pickable pool — exactly the bug this guards against."""
    name_ok = bool((m.get("variant_name") or "").strip())
    avoid_ok = int(m["npc_param_id"]) not in avoid_ids
    return name_ok and avoid_ok


def _keep_rank(m, markers, emerge_markers):
    """Sort key for which row best represents a genuine variant; lower
    is better. Within an already-survivable, reward-filtered eligible
    set, prefer non-trigger over trigger, non-emerge over emerge,
    canonical over ghost, then lowest npc_param_id for determinism."""
    return (1 if is_trigger_variant(m, markers) else 0,
            1 if is_trigger_variant(m, emerge_markers) else 0,
            1 if is_ghost(m) else 0,
            int(m["npc_param_id"]))


def compute_prune(records, collapse_canonical, markers, emerge_markers,
                  avoid_ids):
    """Return (prune_ids set, kept count, reward_stats dict).

    Per genuine-key cluster, the kept representative is chosen so the
    rando's RANDOM pick path never loses a placeable variant:

      1. SURVIVABILITY FIRST. Rows that pass pick_variant_for_tier's
         hard filters (non-empty name, not avoid-listed) are preferred.
         If a cluster has any survivable row, only survivable rows are
         eligible to keep — keeping a non-survivable rep while pruning
         its survivable siblings would empty the c-prefix's pool. Only
         when a cluster has NO survivable row does the whole cluster
         become eligible (moot — that variant can't be placed anyway).
      2. REWARD-PREFERENCE, applied WITHIN the survivable set. If any
         eligible row is has_reward=True, the non-reward rows are
         pruned so the kept variant drops its reward. Survivability
         outranks reward: a placeable dropless variant beats an
         unplaceable rewarded one.
      3. _keep_rank orders the rest (non-trigger > non-emerge >
         canonical > lowest id).

    Default mode keeps all eligible canonical rows; --collapse-canonical
    keeps exactly one. Every cluster keeps >=1 row, so no genuine
    variant is removed from the pool.
    """
    prune = set()
    kept = 0
    clusters_total = 0
    clusters_with_reward = 0
    reward_only_ghost = 0
    clusters_no_survivable = 0
    for d in records:
        for key, members in d["clusters"].items():
            clusters_total += 1
            survivable = [m for m in members
                          if _is_survivable(m, avoid_ids)]
            base = survivable if survivable else members
            if not survivable:
                clusters_no_survivable += 1

            has_reward = any(m.get("has_reward") for m in base)
            if has_reward:
                clusters_with_reward += 1
                eligible = [m for m in base if m.get("has_reward")]
                if not any(not is_ghost(m) for m in eligible):
                    reward_only_ghost += 1
            else:
                eligible = base

            eligible.sort(key=lambda m: _keep_rank(m, markers, emerge_markers))
            canon_elig = [m for m in eligible if not is_ghost(m)]
            if collapse_canonical:
                keep = eligible[:1]
            else:
                keep = canon_elig if canon_elig else eligible[:1]

            keep_ids = {int(m["npc_param_id"]) for m in keep}
            kept += len(keep_ids)
            for m in members:
                pid = int(m["npc_param_id"])
                if pid not in keep_ids:
                    prune.add(pid)
    return prune, kept, {
        "genuine_clusters": clusters_total,
        "clusters_with_a_reward_row": clusters_with_reward,
        "clusters_no_reward_row_anywhere": clusters_total - clusters_with_reward,
        "clusters_reward_only_as_ghost": reward_only_ghost,
        "clusters_with_no_survivable_row": clusters_no_survivable,
    }


def main():
    root = repo_root()
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(root, "data", "NpcParam.csv"))
    ap.add_argument("--roster",
                    default=os.path.join(root, "data", "nr_enemy_roster.json"))
    ap.add_argument("--min-rows", type=int, default=1,
                    help="only report c-prefixes with at least this many rows")
    ap.add_argument("--sort", choices=["inflation", "rows", "prefix"],
                    default="inflation")
    ap.add_argument("--show-clusters", action="store_true",
                    help="print every genuine cluster, not just the summary")
    ap.add_argument("--emit-prune-list", metavar="PATH",
                    help="write redundant npc_param_ids to this JSON file")
    ap.add_argument("--variation-report", action="store_true",
                    help="report what NpcParam columns vary WITHIN each "
                         "genuine cluster (scaling vs cosmetic vs meaningful)")
    ap.add_argument("--collapse-canonical", action="store_true",
                    help="also collapse canonical duplicates to one per "
                         "genuine key (opt-in; discards per-placement scaling)")
    args = ap.parse_args()

    for p in (args.csv, args.roster):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")

    params = load_npcparam(args.csv)
    roster = json.load(open(args.roster, encoding="utf-8"))
    variants = roster["all_variants"]
    records, no_csv_total = build_records(params, variants)

    if args.sort == "inflation":
        records.sort(key=lambda d: (-d["inflation"], -d["rows"]))
    elif args.sort == "rows":
        records.sort(key=lambda d: -d["rows"])
    else:
        records.sort(key=lambda d: d["cp"])

    tot_rows = sum(d["rows"] for d in records)
    tot_genuine = sum(d["genuine"] for d in records)
    tot_canon = sum(d["canon_genuine"] for d in records)
    tot_ghost = sum(d["ghost_rows"] for d in records)

    # ---- variation-report mode ----
    if args.variation_report:
        full_rows, columns = load_npcparam_full(args.csv)
        variation_report(records, full_rows, columns, args.show_clusters)
        return

    # ---- prune-list mode ----
    if args.emit_prune_list:
        markers = load_trigger_markers(root)
        emerge_markers = load_emerge_markers(root)
        avoid_ids = load_avoid_ids(root)
        prune, kept, rstats = compute_prune(
            records, args.collapse_canonical, markers, emerge_markers,
            avoid_ids)
        n_reward_pruned = sum(
            1 for v in variants
            if int(v["npc_param_id"]) in prune and v.get("has_reward"))

        # Tier coverage diagnostic: of miniboss-and-above c-prefixes, how
        # many have at least one has_reward row anywhere? Those are fully
        # covered by the reward-preference rule. The rest are the residual
        # gap where tier-driven reward synthesis would still be needed.
        tier_cov = None
        tags_path = os.path.join(root, "data", "nr_enemy_tags.json")
        if os.path.exists(tags_path):
            tags = json.load(open(tags_path, encoding="utf-8"))
            MINIBOSS_PLUS = {"miniboss", "field_boss", "night_boss", "nightlord"}
            reward_prefixes = {v["c_prefix"] for v in variants
                               if v.get("has_reward")}
            mb = [cp for cp, t in tags.items()
                  if isinstance(t, dict) and t.get("tier") in MINIBOSS_PLUS]
            covered = [cp for cp in mb if cp in reward_prefixes]
            tier_cov = {
                "miniboss_plus_cprefixes": len(mb),
                "covered_have_a_reward_row": len(covered),
                "gap_no_reward_row_anywhere": sorted(set(mb) - set(covered)),
            }

        payload = {
            "generated_by": "dev/audit_genuine_variants.py",
            "genuine_key": "(behaviorVariationId, think_param_id // 1000)",
            "has_reward_in_key": False,
            "reward_preference_rule": (
                "within a genuine cluster, if any row is has_reward=True "
                "the non-reward rows are pruned and a reward row is kept"),
            "collapse_canonical": bool(args.collapse_canonical),
            "stats": {
                "roster_rows": tot_rows,
                "genuine_identities": tot_genuine,
                "kept_rows": kept,
                "pruned_rows": len(prune),
                "pruned_rows_that_npcparam_marked_has_reward": n_reward_pruned,
                **rstats,
            },
            "tier_coverage": tier_cov,
            "note": ("Exclude these npc_param_ids from the placement pool. "
                     "All are redundant duplicates of a kept row with the "
                     "same genuine identity; where a cluster had both "
                     "rewarded and non-rewarded rows, the rewarded one was "
                     "kept so the variant always drops its reward."),
            "prune_npc_param_ids": sorted(prune),
        }
        with open(args.emit_prune_list, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        print(f"wrote {args.emit_prune_list}")
        print(f"  roster rows:        {tot_rows}")
        print(f"  kept rows:          {kept}")
        print(f"  pruned rows:        {len(prune)}  "
              f"({100*len(prune)/tot_rows:.1f}% of roster)")
        print(f"  collapse-canonical: {bool(args.collapse_canonical)}")
        print(f"  genuine clusters:   {rstats['genuine_clusters']}  "
              f"({rstats['clusters_with_a_reward_row']} have a reward row, "
              f"{rstats['clusters_no_reward_row_anywhere']} do not)")
        if rstats["clusters_reward_only_as_ghost"]:
            print(f"  note: {rstats['clusters_reward_only_as_ghost']} cluster(s) "
                  f"had reward ONLY on a ghost row — kept the reward ghost "
                  f"per the rule (a ghost outranking a canonical here).")
        if tier_cov:
            gap = len(tier_cov["gap_no_reward_row_anywhere"])
            print(f"  miniboss+ tiers:    "
                  f"{tier_cov['covered_have_a_reward_row']}/"
                  f"{tier_cov['miniboss_plus_cprefixes']} have a reward row; "
                  f"{gap} have none (residual gap — see tier_coverage).")
        return

    # ---- report mode ----
    shown = [d for d in records if d["rows"] >= args.min_rows]
    print("=" * 78)
    print("GENUINE VARIANT AUDIT  —  NpcParam rows vs. distinct enemy identities")
    print("=" * 78)
    print(f"{'c-prefix':<9} {'rows':>5} {'genuine':>8} {'canon':>6} "
          f"{'ghost':>6} {'x':>6}  name")
    print("-" * 78)
    for d in shown:
        print(f"{d['cp']:<9} {d['rows']:>5} {d['genuine']:>8} "
              f"{d['canon_genuine']:>6} {d['ghost_rows']:>6} "
              f"{d['inflation']:>5.1f}x  {d['name']}")
        if args.show_clusters:
            for key, members in sorted(d["clusters"].items(),
                                       key=lambda kv: -len(kv[1])):
                ghost = sum(1 for m in members if is_ghost(m))
                bvid, tfam = key
                names = sorted({(m.get("variant_name") or "?").strip()
                                for m in members})
                print(f"            - {len(members):>3} row(s)"
                      f"  ({ghost} ghost)  bvid={bvid} think_family={tfam}"
                      f"  [{', '.join(names)}]")

    print("-" * 78)
    print(f"c-prefixes:                {len(records):>6}")
    print(f"NpcParam rows (roster):    {tot_rows:>6}")
    print(f"genuine variant identities:{tot_genuine:>6}  "
          f"({tot_rows / tot_genuine:.1f}x inflation)")
    print(f"  of which canonical:      {tot_canon:>6}  "
          f"(non-ghost — what _filter_canonical_variants keeps)")
    print(f"ghost rows (dump/unplaced):{tot_ghost:>6}")
    print(f"rows with no NpcParam.csv: {no_csv_total:>6}  "
          f"(MMV/ER imports — kept distinct, never merged)")
    print("=" * 78)
    print("Reading: 'genuine' = distinct (behaviorVariationId, think-script")
    print("family) tuples. 'x' is rows-per-genuine — high means the c-prefix")
    print("is mostly placement-context duplication and safe to collapse.")
    print("Run with --emit-prune-list PATH to write the exclusion set.")


if __name__ == "__main__":
    main()
