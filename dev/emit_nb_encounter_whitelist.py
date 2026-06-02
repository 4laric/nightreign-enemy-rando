#!/usr/bin/env python3
"""emit_nb_encounter_whitelist.py — generate the LotResultSmallBaseAndSpot
patch CSV that constrains the game's NB-arena overlay lottery to the
arenas in data/nb_encounter_whitelist.json.

Companion to the engine-side `V3_NB_RANDOMIZE_WHITELIST` in oops_v3.py.
Both layers read the same whitelist JSON so they cannot drift; the engine
swaps boss Parts only at whitelisted arenas, and this script makes the
GAME only ever route NB attachments to those same arenas.

Mechanism
=========
`LotResultSmallBaseAndSpot` carries ~23.9k rows grouped by `patternId`.
A run rolls a `patternId`, and every row under that patternId is applied:
at attach point `attachId`, attach overlay `smallBaseMapId`, with the
paired `modifier`. NB arena MSBs appear as `smallBaseMapId` values that
match the four-digit form of the stem (e.g. 4910 = m49_10_00_00.msb,
Grafted Monarch; 4840 = m48_40_00_00.msb, Morgott).

For every row whose `smallBaseMapId` is one of the 22 dedicated NB
arenas:
  - classify the row as NB1 or NB2 by looking up the arena's vanilla
    pool membership in nightreign_arena_structure.json;
  - rewrite `smallBaseMapId` to the whitelist's NB1 (or NB2) pick;
  - rewrite `modifier` to the canonical modifier for that pick (the
    most common `(smbid, modifier)` pair across all vanilla rows
    carrying that smbid -- e.g. 4910 -> 436, 4840 -> 400);
  - leave every other column byte-identical.

The 4940-family rows (smbid 4940/4941/4942/4943, ~130 each, modifier 0)
are a different category -- probably variation-family / generic field-
tile rows rather than single-boss arena selections -- and are NOT
touched.

For arenas that don't appear in any expedition pool in arena_structure
(m48_70 Godskin Apostle Duo, m49_30 Royal Revenant, m49_90 Ulcerated
Tree Spirit), an attach-point heuristic classifies them: the regulation
dump shows m49_30 and m49_90 appear ONLY at the NB1-only attach points
(1111, 1114), so they're classified NB1. m48_70 doesn't appear in this
table at all in vanilla and is not classified.

Output
======
Smithbox-importable row-patch CSV: only NB-class rows are emitted, full
schema preserved, with smallBaseMapId and modifier rewritten and every
other column unchanged. Import in Smithbox over the user's regulation
(MMV-first, whitelist-last) to apply the constraint.

Usage
=====
    python3 dev/emit_nb_encounter_whitelist.py \\
        --param-dump /path/to/regulation/csv-dir \\
        [--whitelist data/nb_encounter_whitelist.json] \\
        [--out regulation_fixes/LotResultSmallBaseAndSpot_nb_whitelist_smithbox.csv] \\
        [--dry-run]

--dry-run prints (smbid, modifier, row-count) for every NB-classified
row the script would touch, plus the rewrite plan, without writing the
CSV. A normal re-run prints a row-count diff against the existing CSV at
--out for idempotency verification.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

DEFAULT_WHITELIST = os.path.join(REPO_ROOT, 'data', 'nb_encounter_whitelist.json')
DEFAULT_OUT = os.path.join(REPO_ROOT, 'regulation_fixes',
                           'LotResultSmallBaseAndSpot_nb_whitelist_smithbox.csv')
ARENA_STRUCTURE = os.path.join(REPO_ROOT, 'data', 'nightreign_arena_structure.json')

LOT_RESULT_CSV = 'LotResultSmallBaseAndSpot.csv'

# Attach-point geometry of `LotResultSmallBaseAndSpot`. Each NB-class row
# lands at one of six attach IDs, distributed across two physical grid
# cells (1111/1112/1113 and 1114/1115/1116). Per the 2026-05-31
# regulation-dump trace:
#   1111, 1114 -- "strict NB1" slots: in vanilla, carry only NB1-pool
#     arenas (per the PC Gamer expedition table) plus the two unmapped
#     arenas m49_30 and m49_90.
#   1113, 1116 -- "strict NB2" slots: only NB2-pool arenas plus a handful
#     of Bell Bearing Hunter (c3100) outliers.
#   1112, 1115 -- "wildcard" slots: mixed NB1 and NB2.
# Used by classify_unmapped_via_attach() to place arenas that don't
# appear in any expedition pool: an arena observed only at NB1-strict +
# wildcard slots (never at strict NB2) classifies as NB1, and vice versa.
STRICT_NB1_ATTACH_IDS = frozenset({1111, 1114})
STRICT_NB2_ATTACH_IDS = frozenset({1113, 1116})
WILDCARD_ATTACH_IDS = frozenset({1112, 1115})


def arena_stem_to_smbid(stem):
    """'m49_10_00_00' -> 4910. Strip the 'm', split on '_', take the
    first two pieces and concatenate. Anchors why 'm47_70' -> 4770."""
    assert stem.startswith('m') and '_' in stem, f"bad arena stem: {stem}"
    parts = stem[1:].split('_')
    return int(parts[0] + parts[1])


def smbid_to_arena_stem(smbid):
    s = str(int(smbid))
    assert len(s) == 4, f"expected 4-digit smbid, got {smbid}"
    return f'm{s[:2]}_{s[2:]}_00_00'


def load_arena_classification(structure_path):
    """Walk expedition_to_night_boss_pool in nightreign_arena_structure.json
    and return (nb1_arenas, nb2_arenas) -- sets of smbids. An arena that
    appears in any NB1 pool is NB1; in any NB2 pool is NB2; in both, it's
    classified by majority (count of pool appearances). Returns the
    intersection between the structure's nb arenas and rows actually
    present in LotResultSmallBaseAndSpot is computed by the caller."""
    with open(structure_path, encoding='utf-8') as f:
        struct = json.load(f)

    nb1_count = Counter()
    nb2_count = Counter()

    # walk known NB arenas: collect (stem -> smbid) from the canonical list
    known_arenas = {}  # stem -> smbid
    for stem in struct.get('night_boss_arenas', {}):
        if stem.startswith('_'):
            continue
        known_arenas[stem] = arena_stem_to_smbid(stem)

    for expedition, pools in struct.get('expedition_to_night_boss_pool', {}).items():
        if expedition.startswith('_'):
            continue
        for entry in pools.get('nb1_pool', []) or []:
            arena = entry.get('arena', '').strip().rstrip('?')
            # 'm49_10' style; expand to full stem
            if arena and not arena.startswith('m4'):
                continue
            full = arena if arena.endswith('_00_00') else f'{arena}_00_00'
            if full in known_arenas:
                nb1_count[known_arenas[full]] += 1
        for entry in pools.get('nb2_pool', []) or []:
            arena = entry.get('arena', '').strip().rstrip('?')
            if arena and not arena.startswith('m4'):
                continue
            full = arena if arena.endswith('_00_00') else f'{arena}_00_00'
            if full in known_arenas:
                nb2_count[known_arenas[full]] += 1

    nb1 = set()
    nb2 = set()
    ambiguous = set()
    unmapped = set()
    for stem, smbid in known_arenas.items():
        c1 = nb1_count.get(smbid, 0)
        c2 = nb2_count.get(smbid, 0)
        if c1 and not c2:
            nb1.add(smbid)
        elif c2 and not c1:
            nb2.add(smbid)
        elif c1 and c2:
            # both pools list it; majority wins, tiebreak NB1 (BBH-like
            # bosses lean NB1 in PC Gamer's table)
            (nb1 if c1 >= c2 else nb2).add(smbid)
            ambiguous.add(smbid)
        else:
            unmapped.add(smbid)

    return nb1, nb2, ambiguous, unmapped, known_arenas


def classify_unmapped_via_attach(rows, unmapped_smbids):
    """For arenas not in any expedition pool, classify by attach-point
    presence: NB1 if observed only at strict-NB1 attaches plus wildcards
    (i.e., never at strict-NB2 attaches); NB2 vice versa; ambiguous if
    observed at both. (m49_30 and m49_90 in vanilla appear at attaches
    {1111, 1112, 1114, 1115} -- strict-NB1 plus wildcards, never at
    strict-NB2 1113/1116 -- so they classify NB1.)"""
    by_smbid_attaches = defaultdict(set)
    for r in rows:
        sm = int(r['smallBaseMapId'])
        if sm in unmapped_smbids:
            by_smbid_attaches[sm].add(int(r['attachId']))

    nb1_extra = set()
    nb2_extra = set()
    still_unmapped = set()
    for sm, attaches in by_smbid_attaches.items():
        if not attaches:
            still_unmapped.add(sm)
            continue
        at_nb1 = bool(attaches & STRICT_NB1_ATTACH_IDS)
        at_nb2 = bool(attaches & STRICT_NB2_ATTACH_IDS)
        if at_nb1 and not at_nb2:
            nb1_extra.add(sm)
        elif at_nb2 and not at_nb1:
            nb2_extra.add(sm)
        else:
            still_unmapped.add(sm)
    return nb1_extra, nb2_extra, still_unmapped


def canonical_modifier(rows, smbid):
    """Most common modifier paired with `smbid` across all rows carrying
    it. Returns (modifier, support_count, total_count) where support_count
    is the count of rows backing that modifier and total_count is the
    arena's full row count -- caller can decide whether the support is
    sufficient (a clean 1:1 pair will have support == total)."""
    counts = Counter()
    for r in rows:
        if int(r['smallBaseMapId']) == smbid:
            counts[int(r['modifier'])] += 1
    if not counts:
        return None, 0, 0
    mod, support = counts.most_common(1)[0]
    return mod, support, sum(counts.values())


def load_whitelist(path):
    with open(path, encoding='utf-8') as f:
        raw = json.load(f)
    nb1 = list(raw.get('nb1', []))
    nb2 = list(raw.get('nb2', []))
    return nb1, nb2


def main(argv=None):
    p = argparse.ArgumentParser(
        description='Emit the LotResultSmallBaseAndSpot patch CSV that '
                    'constrains the game\'s NB-arena overlay lottery to the '
                    'whitelist in data/nb_encounter_whitelist.json.')
    p.add_argument('--param-dump', required=True,
                   help='Path to the directory containing the regulation\'s '
                        'CSV dump, including LotResultSmallBaseAndSpot.csv.')
    p.add_argument('--whitelist', default=DEFAULT_WHITELIST,
                   help=f'Whitelist JSON (default: {DEFAULT_WHITELIST}).')
    p.add_argument('--out', default=DEFAULT_OUT,
                   help=f'Output patch CSV (default: {DEFAULT_OUT}).')
    p.add_argument('--structure', default=ARENA_STRUCTURE,
                   help=f'Arena structure JSON (default: {ARENA_STRUCTURE}).')
    p.add_argument('--dry-run', action='store_true',
                   help='Print the rewrite plan; do not write the CSV.')
    args = p.parse_args(argv)

    lot_csv_path = os.path.join(args.param_dump, LOT_RESULT_CSV)
    if not os.path.isfile(lot_csv_path):
        print(f"ERROR: {lot_csv_path} not found.", file=sys.stderr)
        return 2

    # Read schema + all rows
    with open(lot_csv_path, encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        header = next(reader)
        all_rows = []
        for row in reader:
            if not row:
                continue
            d = dict(zip(header, row))
            all_rows.append(d)

    print(f"Loaded {len(all_rows)} rows from {LOT_RESULT_CSV}.")
    print(f"Schema: {len(header)} columns.")

    # Classification from the expedition pool table
    nb1_set, nb2_set, ambiguous, unmapped, known_arenas = \
        load_arena_classification(args.structure)
    print(f"\nPool-based classification from {os.path.basename(args.structure)}:")
    print(f"  NB1 arenas (in some expedition's nb1_pool): "
          f"{sorted(nb1_set)} ({len(nb1_set)})")
    print(f"  NB2 arenas (in some expedition's nb2_pool): "
          f"{sorted(nb2_set)} ({len(nb2_set)})")
    if ambiguous:
        print(f"  Ambiguous (in both pools, majority-classified): "
              f"{sorted(ambiguous)}")
    if unmapped:
        print(f"  Unmapped (in 22-arena set but in no expedition pool): "
              f"{sorted(unmapped)}")

    # Attach-point heuristic for unmapped
    if unmapped:
        nb1_extra, nb2_extra, still_unmapped = \
            classify_unmapped_via_attach(all_rows, unmapped)
        if nb1_extra:
            print(f"  Attach-heuristic adds to NB1 (never at strict-NB2 "
                  f"attaches 1113/1116): {sorted(nb1_extra)}")
            nb1_set |= nb1_extra
        if nb2_extra:
            print(f"  Attach-heuristic adds to NB2 (never at strict-NB1 "
                  f"attaches 1111/1114): {sorted(nb2_extra)}")
            nb2_set |= nb2_extra
        if still_unmapped:
            print(f"  Still unmapped (not present in CSV, or attaches span "
                  f"both strict-NB1 and strict-NB2 sides): "
                  f"{sorted(still_unmapped)}")

    all_nb_smbids = nb1_set | nb2_set

    # NB rows in the lot table
    nb_rows = [r for r in all_rows if int(r['smallBaseMapId']) in all_nb_smbids]
    print(f"\nNB rows in {LOT_RESULT_CSV}: {len(nb_rows)} "
          f"(out of {len(all_rows)} total).")

    # Per-arena summary
    by_sm = Counter(int(r['smallBaseMapId']) for r in nb_rows)
    by_attach = Counter(int(r['attachId']) for r in nb_rows)
    print(f"\nPer-arena row counts:")
    for sm in sorted(by_sm):
        side = 'NB1' if sm in nb1_set else 'NB2'
        stem = smbid_to_arena_stem(sm)
        mod, support, total = canonical_modifier(nb_rows, sm)
        marker = '' if support == total else f' ({support}/{total} 1:1 not clean)'
        print(f"  {sm} {stem} [{side}]: {by_sm[sm]} rows, "
              f"canonical modifier {mod}{marker}")
    print(f"\nPer-attachId row counts:")
    for at in sorted(by_attach):
        print(f"  attachId {at}: {by_attach[at]} rows")

    # Load whitelist + resolve picks
    wl_nb1, wl_nb2 = load_whitelist(args.whitelist)
    if not wl_nb1 or not wl_nb2:
        print(f"\nERROR: whitelist must have at least one arena per side. "
              f"Got nb1={wl_nb1}, nb2={wl_nb2}.", file=sys.stderr)
        return 2
    if len(wl_nb1) > 1 or len(wl_nb2) > 1:
        print(f"\nNOTE: whitelist has multiple arenas per side; v1 emitter "
              f"uses only the first entry of each (nb1={wl_nb1[0]}, "
              f"nb2={wl_nb2[0]}). Round-robin support is the Axis A growth "
              f"path; not implemented yet.")

    nb1_pick_smbid = arena_stem_to_smbid(wl_nb1[0])
    nb2_pick_smbid = arena_stem_to_smbid(wl_nb2[0])

    if nb1_pick_smbid not in all_nb_smbids and nb1_pick_smbid not in nb1_set | nb2_set:
        print(f"\nWARNING: NB1 pick {wl_nb1[0]} (smbid {nb1_pick_smbid}) is "
              f"not in the 22-arena NB set; routing rows to it anyway.",
              file=sys.stderr)
    if nb2_pick_smbid not in all_nb_smbids and nb2_pick_smbid not in nb1_set | nb2_set:
        print(f"\nWARNING: NB2 pick {wl_nb2[0]} (smbid {nb2_pick_smbid}) is "
              f"not in the 22-arena NB set; routing rows to it anyway.",
              file=sys.stderr)

    nb1_pick_mod, _, _ = canonical_modifier(nb_rows, nb1_pick_smbid)
    nb2_pick_mod, _, _ = canonical_modifier(nb_rows, nb2_pick_smbid)
    if nb1_pick_mod is None:
        print(f"\nERROR: NB1 pick {wl_nb1[0]} (smbid {nb1_pick_smbid}) has "
              f"no rows in the table; cannot derive canonical modifier.",
              file=sys.stderr)
        return 2
    if nb2_pick_mod is None:
        print(f"\nERROR: NB2 pick {wl_nb2[0]} (smbid {nb2_pick_smbid}) has "
              f"no rows in the table; cannot derive canonical modifier.",
              file=sys.stderr)
        return 2

    print(f"\nWhitelist picks (from {os.path.basename(args.whitelist)}):")
    print(f"  NB1 -> {wl_nb1[0]} (smbid {nb1_pick_smbid}, modifier {nb1_pick_mod})")
    print(f"  NB2 -> {wl_nb2[0]} (smbid {nb2_pick_smbid}, modifier {nb2_pick_mod})")

    # Build the rewrite plan: every NB row gets rewritten based on its
    # current smbid's NB1/NB2 classification.
    n_to_nb1 = 0
    n_to_nb2 = 0
    rewritten = []
    for r in nb_rows:
        sm = int(r['smallBaseMapId'])
        new_r = dict(r)
        if sm in nb1_set:
            new_r['smallBaseMapId'] = str(nb1_pick_smbid)
            new_r['modifier'] = str(nb1_pick_mod)
            n_to_nb1 += 1
        elif sm in nb2_set:
            new_r['smallBaseMapId'] = str(nb2_pick_smbid)
            new_r['modifier'] = str(nb2_pick_mod)
            n_to_nb2 += 1
        else:
            # shouldn't reach here -- nb_rows was filtered by all_nb_smbids
            continue
        rewritten.append(new_r)

    print(f"\nRewrite plan:")
    print(f"  {n_to_nb1} rows -> NB1 pick (smbid={nb1_pick_smbid}, "
          f"modifier={nb1_pick_mod})")
    print(f"  {n_to_nb2} rows -> NB2 pick (smbid={nb2_pick_smbid}, "
          f"modifier={nb2_pick_mod})")
    print(f"  {n_to_nb1 + n_to_nb2} rows total in patch CSV")

    if args.dry_run:
        print(f"\n--dry-run: not writing {args.out}.")
        return 0

    # Idempotent re-run: diff against existing if present
    existing_count = None
    if os.path.isfile(args.out):
        try:
            with open(args.out, encoding='utf-8') as f:
                existing = sum(1 for _ in csv.reader(f)) - 1
            existing_count = existing
        except (OSError, csv.Error):
            existing_count = None

    out_dir = os.path.dirname(args.out)
    os.makedirs(out_dir, exist_ok=True)
    # The source CSV has a trailing comma on the HEADER (so DictReader
    # sees an unnamed empty trailing field) but NOT on data rows. Match
    # that convention exactly so a byte-diff against the source on
    # unrewritten columns is clean. The header is written verbatim; data
    # rows are written via a csv.writer over the named columns only.
    named_fields = [c for c in header if c != '']
    header_line = ','.join(header) + '\r\n'
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        f.write(header_line)
        writer = csv.writer(f)
        for r in rewritten:
            writer.writerow([r.get(c, '') for c in named_fields])

    rel = os.path.relpath(args.out, REPO_ROOT)
    print(f"\nWrote {len(rewritten)} rows to {rel}.")
    if existing_count is not None:
        delta = len(rewritten) - existing_count
        if delta:
            sign = '+' if delta > 0 else ''
            print(f"  (was {existing_count} rows; {sign}{delta})")
        else:
            print(f"  (unchanged row count vs prior emission)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
