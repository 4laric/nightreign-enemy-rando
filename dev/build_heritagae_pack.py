#!/usr/bin/env python3
"""v0.27.0 — heritage_pack.json regenerator.

Rebuilds data/heritage_pack.json from a four-set diff instead of the
hand-curated / one-off-audit approach that produced the stale v2
manifest. Run this once per NR version (or whenever the chr-folder
contents change) and the heritage pack stays in sync.

WHY THIS EXISTS
---------------
"Heritage chr" has a precise definition the rando already states in
heritage_pack.json's _meta: a c-prefix that the rando's roster
references but vanilla NR's chr/ folder does not ship. The old v2
manifest was built from a diff of two chr-folder *scans* (vanilla NR
vs a modded me3 profile) — which meant it measured against whatever
chrs happened to be in one person's modded profile, not against the
authoritative source. That undercounted (it missed 30+ real heritage
chrs whose assets live in ER) and the result drifted out of sync with
nr_enemy_roster.json's own _heritage_imported flags. See the session
diagnosis: plan_roster_import and detect_asset_packs disagreed by 10
c-prefixes because they read different files.

THE DEFINITION, MADE PRECISE
----------------------------
A c-prefix belongs in heritage_pack.json iff ALL of:
  1. The rando references it          -> key in nr_enemy_tags.json
  2. Vanilla NR does NOT ship it       -> not in the NR chr/ folder
  3. Elden Ring CAN supply the asset   -> present in the ER chr/ folder
  4. It is not a System/object entry   -> see SYSTEM_NAMES rule
  5. It has the fields the placement   -> size_class AND locomotion
     picker hard-requires                 (locomotion may be inferred,
                                            see family-backfill below)

MMV-pack chrs are deliberately NOT heritage: they are the separate
mmv_imports.json concern. A prefix in mmv_imports.json's tags is
skipped here even if it would otherwise qualify.

FAMILY-BACKFILL OF locomotion
-----------------------------
Some genuine, named heritage chrs (Decaying Ekzykes, Greyoll, the
Crab variants, etc.) have a tag with anim_class + size_class but no
locomotion — the v0.24.72 backfill pass never reached them. Rather
than drop a real enemy over one missing field, this script infers
locomotion from anim_class for the anim_classes where that mapping
is empirically clean (>=80% purity, measured from chrs that have
both fields — see ANIM_LOCO). Ambiguous anim_classes (quadruped,
quadruped_large, large_boss_ground) are NOT inferred from — a missing
locomotion there is a real drop.

c4482 Giant Fading Miranda Sprout is a special case: its anim_class
(large_boss_ground) is in the ambiguous set, but every member of the
Miranda family (c4480/c4481/c4483) has locomotion=0, so it is
inferred from the family rather than the anim_class.

When locomotion is inferred, this script WRITES the value back into
nr_enemy_tags.json, marked with `_tags_backfilled_v0_27_0` and a
`_locomotion_backfill_v0_27_0` justification string — mirroring the
existing `_tags_backfilled_v0_24_72` convention so the provenance is
visible and a future reader knows the value was inferred, not
measured. Use --dry-run to preview without writing.

INPUTS
------
Two chr-folder listings are required (the NR and ER chr/ directory
contents). Point --nr-chr / --er-chr at the actual folders, OR pass
--nr-chr-list / --er-chr-list text files (one filename or c-prefix
per line) if you only have a dir listing. The script extracts the
c-prefix from any chr asset file (chrbnd/anibnd/behbnd/texbnd).

USAGE
-----
    python3 dev/build_heritage_pack.py \
        --nr-chr /path/to/NIGHTREIGN/Game/chr \
        --er-chr /path/to/ELDEN_RING/Game/chr
    python3 dev/build_heritage_pack.py ... --dry-run   # preview only
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# A c-prefix is extracted from any of these asset wrappers.
CHR_FILE_RE = re.compile(
    r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')

# Rule 4 — System/object exclusion. A tag whose `name` is one of these
# (or contains 'Template') is an engine-internal entity, never a
# placeable enemy. Excluded by rule so the heritage pack regenerates
# clean without hand-removal.
SYSTEM_NAMES = {'System', 'Interactable Object', 'Roundtable Object'}

# Family-backfill mapping: anim_class -> locomotion. Only anim_classes
# whose locomotion distribution is empirically clean (>=80% of tagged
# chrs that have both fields share one value) are listed. Ambiguous
# anim_classes are intentionally absent — a missing locomotion for
# those is a genuine drop, not something to guess.
#
# Derived from nr_enemy_tags.json (chrs with both anim_class and
# locomotion present):
#   flying_dragon  90% -> 5      large_boss_ground 73%  EXCLUDED (ambiguous)
#   aquatic        89% -> 0      quadruped         62%  EXCLUDED (ambiguous)
#   humanoid       80% -> 0      quadruped_large   40%  EXCLUDED (ambiguous)
#   misc          100% -> 0
#   giga_boss     100% -> 5
ANIM_LOCO = {
    'flying_dragon': 5,
    'aquatic': 0,
    'humanoid': 0,
    'misc': 0,
    'giga_boss': 5,
}

# Per-chr family overrides for locomotion inference. Takes precedence
# over ANIM_LOCO — used when a chr's anim_class is in the ambiguous
# set but its enemy family has a known-consistent locomotion.
#   c4482 Giant Fading Miranda Sprout: anim_class large_boss_ground is
#   ambiguous, but every Miranda (c4480/c4481/c4483) is locomotion 0.
FAMILY_LOCO_OVERRIDE = {
    'c4482': (0, 'miranda_family: c4480/c4481/c4483 all locomotion=0'),
}

BACKFILL_MARKER = '_tags_backfilled_v0_27_0'
BACKFILL_JUSTIFICATION_KEY = '_locomotion_backfill_v0_27_0'


def _data_path(filename):
    """Resolve a data file: data/<f> if present, else project root."""
    p = os.path.join(ROOT, 'data', filename)
    return p if os.path.exists(p) else os.path.join(ROOT, filename)


def chr_prefixes_from_dir(path):
    """Set of c-prefixes with a chr asset file in `path`."""
    out = set()
    if not path or not os.path.isdir(path):
        raise SystemExit(f"chr folder not found or not a directory: {path}")
    for fn in os.listdir(path):
        m = CHR_FILE_RE.match(fn)
        if m:
            out.add(m.group(1))
    return out


def chr_prefixes_from_list(path):
    """Set of c-prefixes from a text file. Accepts either chr asset
    filenames (c4680.chrbnd.dcx) or bare prefixes (c4680), one per
    line; anything matching c<4 digits> on the line is picked up."""
    out = set()
    if not path or not os.path.isfile(path):
        raise SystemExit(f"chr list file not found: {path}")
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = CHR_FILE_RE.match(line.strip())
            if m:
                out.add(m.group(1))
                continue
            for tok in re.findall(r'\bc\d{4}\b', line):
                out.add(tok)
    return out


def is_system(tag):
    name = (tag or {}).get('name', '')
    return name in SYSTEM_NAMES or 'Template' in name


def verify_anim_loco_mapping(tags):
    """Re-derive the anim_class->locomotion purity from the live tags
    and warn if ANIM_LOCO has drifted from the data it was built on.
    Doesn't change behavior — just flags a stale constant for a human."""
    dist = defaultdict(Counter)
    for t in tags.values():
        ac, lo = t.get('anim_class'), t.get('locomotion')
        if ac and lo is not None:
            dist[ac][lo] += 1
    for ac, expected in ANIM_LOCO.items():
        if ac not in dist:
            print(f"  [warn] ANIM_LOCO has '{ac}' but no tagged chr "
                  f"uses it — mapping may be stale.")
            continue
        d = dist[ac]
        top, topn = d.most_common(1)[0]
        purity = topn / sum(d.values())
        if top != expected:
            print(f"  [warn] ANIM_LOCO['{ac}']={expected} but the live "
                  f"data majority is {top} ({purity:.0%}). Mapping stale?")
        elif purity < 0.80:
            print(f"  [warn] ANIM_LOCO['{ac}'] purity dropped to "
                  f"{purity:.0%} (<80%). Consider removing it.")


def build(nr_chr, er_chr, dry_run=False):
    tags_path = _data_path('nr_enemy_tags.json')
    hp_path = _data_path('heritage_pack.json')
    mmv_path = _data_path('mmv_imports.json')

    with open(tags_path, encoding='utf-8') as f:
        tags = json.load(f)
    with open(hp_path, encoding='utf-8') as f:
        old_hp = json.load(f)
    try:
        with open(mmv_path, encoding='utf-8') as f:
            mmv_set = set((json.load(f).get('tags') or {}).keys())
    except (OSError, ValueError):
        mmv_set = set()

    rando_refs = set(tags.keys())

    print(f"NR chr/ ships:           {len(nr_chr)} c-prefixes")
    print(f"ER chr/ has:             {len(er_chr)} c-prefixes")
    print(f"rando references:        {len(rando_refs)} c-prefixes")
    print(f"mmv_imports.json tags:   {len(mmv_set)} (excluded — separate pack)")
    print()
    print("Checking anim_class->locomotion mapping against live tags:")
    verify_anim_loco_mapping(tags)
    print()

    # Rule 1-3: referenced, not shipped by NR, available from ER,
    #           and not an MMV-pack chr.
    candidates = sorted((rando_refs - nr_chr) & er_chr - mmv_set)

    kept = {}                 # cp -> heritage_pack tag entry
    inferred_writes = []      # (cp, locomotion, justification)
    dropped_system = []
    dropped_fields = []       # (cp, name, missing)

    for cp in candidates:
        t = tags.get(cp) or {}

        # Rule 4 — System/object exclusion
        if is_system(t):
            dropped_system.append(cp)
            continue

        # Rule 5 — placement-field gate: size_class AND locomotion.
        has_size = t.get('size_class') not in (None, '', '?')
        loco = t.get('locomotion')
        has_loco = loco not in (None, '')

        infer = None
        if not has_loco:
            # family-backfill: per-chr override first, then anim_class
            if cp in FAMILY_LOCO_OVERRIDE:
                infer = FAMILY_LOCO_OVERRIDE[cp]
            elif t.get('anim_class') in ANIM_LOCO:
                ac = t['anim_class']
                infer = (ANIM_LOCO[ac],
                         f'anim_class={ac}: empirically-clean '
                         f'anim_class->locomotion inference')
            if infer is not None:
                has_loco = True

        if not (has_size and has_loco):
            missing = []
            if not has_size:
                missing.append('size_class')
            if not has_loco:
                missing.append('locomotion')
            dropped_fields.append((cp, t.get('name', '?'), missing))
            continue

        if infer is not None:
            inferred_writes.append((cp, infer[0], infer[1]))

        # heritage_pack tag entry — mirrors the existing minimal shape
        # (name + provenance string).
        orig_src = t.get('_source', '<none>')
        kept[cp] = {
            'name': t.get('name', cp),
            '_inferred_source': f'four_set_diff_v0_27_0 (orig _source={orig_src})',
        }

    # --- write locomotion backfills into nr_enemy_tags.json ---
    if inferred_writes:
        for cp, loco_val, justification in inferred_writes:
            t = tags[cp]
            t['locomotion'] = loco_val
            t[BACKFILL_MARKER] = True
            t[BACKFILL_JUSTIFICATION_KEY] = justification
        if not dry_run:
            with open(tags_path, 'w', encoding='utf-8') as f:
                json.dump(tags, f, indent=2, ensure_ascii=False,
                          sort_keys=True)

    # --- assemble the new heritage_pack.json ---
    meta = dict(old_hp.get('_meta', {}))
    meta['version'] = 'v3'
    meta['engine_authored'] = 'v0.27.0'
    meta['confidence'] = 'four_set_diff_v0_27_0'
    meta['description'] = (
        "SOTE-flavored / cross-game chrs the rando's nr_enemy_tags.json "
        "references but vanilla NR's chr/ folder does not ship, that are "
        "importable from a vanilla Elden Ring chr/ folder.\n\n"
        "v3 regeneration rule (dev/build_heritage_pack.py): a c-prefix is "
        "included iff it is (1) referenced by nr_enemy_tags.json, (2) "
        "absent from the vanilla NR chr/ folder, (3) present in the "
        "vanilla ER chr/ folder, (4) not a System/object entry, and (5) "
        "has both size_class and locomotion in its tag (locomotion may "
        "be family-inferred — see the script). MMV-pack chrs are "
        "excluded as a separate concern.\n\n"
        "v3 supersedes v2 (v0.23.18), which was built from a chr-folder "
        "scan of one modded me3 profile and undercounted by ~30 entries "
        "as a result. Regenerate with dev/build_heritage_pack.py on any "
        "NR version bump.")
    new_hp = {'_meta': meta, 'tags': dict(sorted(kept.items()))}

    if not dry_run:
        with open(hp_path, 'w', encoding='utf-8') as f:
            json.dump(new_hp, f, indent=2, ensure_ascii=False)

    # --- report ---
    old_set = set((old_hp.get('tags') or {}).keys())
    new_set = set(kept.keys())
    print(f"=== heritage_pack.json v3 ===")
    print(f"  entries: {len(new_set)}  (was {len(old_set)} in v2)")
    print(f"  added:   {len(new_set - old_set)}")
    print(f"  removed: {len(old_set - new_set)}")
    if old_set - new_set:
        print(f"    removed -> {sorted(old_set - new_set)}")
    print(f"  locomotion backfills written to nr_enemy_tags.json: "
          f"{len(inferred_writes)}")
    for cp, loco_val, just in inferred_writes:
        print(f"    {cp}  locomotion<-{loco_val}  ({just})")
    print(f"  dropped — System/object rule: {len(dropped_system)}  "
          f"{dropped_system}")
    print(f"  dropped — missing placement fields: {len(dropped_fields)}")
    for cp, name, missing in dropped_fields:
        print(f"    {cp}  {name:34s} missing: {', '.join(missing)}")
    if dry_run:
        print(f"\n  [dry-run] no files written. Re-run without "
              f"--dry-run to apply.")
    else:
        print(f"\n  wrote {hp_path}")
        if inferred_writes:
            print(f"  wrote {tags_path} ({len(inferred_writes)} "
                  f"locomotion backfills)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--nr-chr', help='vanilla NIGHTREIGN chr/ folder')
    ap.add_argument('--er-chr', help='vanilla ELDEN RING chr/ folder')
    ap.add_argument('--nr-chr-list',
                    help='text file listing NR chr/ contents '
                         '(filenames or c-prefixes) — use instead of '
                         '--nr-chr if you only have a dir listing')
    ap.add_argument('--er-chr-list',
                    help='text file listing ER chr/ contents')
    ap.add_argument('--dry-run', action='store_true',
                    help='report what would change without writing '
                         'heritage_pack.json or nr_enemy_tags.json')
    args = ap.parse_args()

    if args.nr_chr:
        nr_chr = chr_prefixes_from_dir(args.nr_chr)
    elif args.nr_chr_list:
        nr_chr = chr_prefixes_from_list(args.nr_chr_list)
    else:
        ap.error('provide --nr-chr or --nr-chr-list')

    if args.er_chr:
        er_chr = chr_prefixes_from_dir(args.er_chr)
    elif args.er_chr_list:
        er_chr = chr_prefixes_from_list(args.er_chr_list)
    else:
        ap.error('provide --er-chr or --er-chr-list')

    build(nr_chr, er_chr, dry_run=args.dry_run)


if __name__ == '__main__':
    main()