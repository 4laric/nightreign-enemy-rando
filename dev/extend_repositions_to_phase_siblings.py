#!/usr/bin/env python3
"""extend_repositions_to_phase_siblings.py

Auto-extend manual slot_repositions.json entries to phase-sibling MSBs.

# Background

Many NR overworld tiles `m60_<col>_<row>_<sub>` are phase variants of the
same geographic tile. Subs `_00`/`_10`/`_20` typically share identical
vanilla part positions for the same `pi`; `_50` is the night-boss layer
and often has different content.

When a slot reposition is added manually (e.g. after a playtest freeze
report), the fix usually applies to ALL phase siblings with matching
positions — not just the one the user encountered. We've done this
manually three times already (v0.24.48→.49 patch, v0.24.50 preemptive),
which is the pattern this tool automates.

# What it does

1. Load `data/slot_repositions.json` and `data/nr_all_part_positions.json`.
2. For each existing manual reposition entry on an `m60_*` MSB:
   - Find sibling MSBs (same col+row, different sub).
   - For each sibling, look up the vanilla position at the same `pi`.
   - If positions match (within float tolerance) AND the sibling doesn't
     already have a reposition entry, that's a candidate extension.
3. Dry-run by default: print candidates. With `--apply`, write extension
   entries to slot_repositions.json mirroring the source's shift, with
   `manual_override.reason="auto_phase_sibling_extension"` and a
   `parent_fix` pointer.

# Manual entries

The tool considers an entry "manual" when its `status` starts with
`playtest_` (currently: `playtest_freeze`, `playtest_xxl_sink`). Auto-
built repositions from build_slot_repositions.py use status values like
`elevated_narrow`/`off_mesh`/`wedged_on_mesh` and already cover all
phase tiles independently via the global polygon scan — no extension
needed.

Pass `--include-all-manual` to also consider entries with a
`manual_override` block but a non-playtest status (e.g. cross-collision
nudges from distribute_stacked_repositions). Generally not recommended —
those are slot-specific and don't have a cross-phase guarantee.

# Usage

  python3 dev/extend_repositions_to_phase_siblings.py            # dry-run
  python3 dev/extend_repositions_to_phase_siblings.py --apply    # write entries
  python3 dev/extend_repositions_to_phase_siblings.py --verbose  # show matches

# Safety

- Never overwrites an existing entry at the sibling slot.
- Position tolerance: 0.01m on each axis (float-precision-tolerant).
- Always updates `_meta.total_relocations` and appends a
  `post_processing` log entry.
- Designed to be idempotent: running twice produces the same result the
  second time (already-extended siblings are skipped).
"""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import sys
from copy import deepcopy

# --- paths --------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # one level up from dev/
SLOT_REPOS_PATH = os.path.join(ROOT, 'data', 'slot_repositions.json')
PART_POSITIONS_PATH = os.path.join(ROOT, 'data', 'nr_all_part_positions.json')

# --- core helpers -------------------------------------------------------

OVERWORLD_MSB_RE = re.compile(r'^(m60_\d{2}_\d{2})_(\d{2})\.msb$')

POSITION_TOLERANCE = 0.01  # meters per axis


def parse_tile_id(msb_name: str):
    """Return (tile_base, sub) if msb_name is an m60 overworld tile, else None.

    tile_base is "m60_<col>_<row>", sub is the 2-digit phase suffix.
    """
    m = OVERWORLD_MSB_RE.match(msb_name)
    if not m:
        return None
    return m.group(1), m.group(2)


def positions_match(a, b, tol=POSITION_TOLERANCE):
    """Per-axis float comparison."""
    if a is None or b is None:
        return False
    return all(math.isclose(ax, bx, abs_tol=tol) for ax, bx in zip(a, b))


def is_manual_playtest_entry(entry):
    """Default filter: manual playtest entries only."""
    status = entry.get('status') or ''
    return status.startswith('playtest_')


def is_any_manual_entry(entry):
    """Loose filter: anything with a manual_override block."""
    return isinstance(entry.get('manual_override'), dict)


# --- finding candidates -------------------------------------------------

def find_extension_candidates(slot_repos, all_positions, manual_filter, verbose=False):
    """Walk slot_repos['proposals'] and find phase siblings to extend.

    Returns list of dicts:
      {
        'source_msb':    str,
        'source_pi':     str,
        'source_entry':  dict (the original entry),
        'sibling_msb':   str,
        'sibling_pi':    str (same as source_pi),
        'sibling_vanilla_position': [x,y,z],
        'skip_reason':   None | str,   # populated if we won't extend
      }
    """
    proposals = slot_repos['proposals']
    candidates = []
    seen_tiles = {}  # tile_base -> {sub: msb_name} from positions data
    # Pre-index all m60 MSBs from the positions data
    for msb in all_positions['positions']:
        parsed = parse_tile_id(msb)
        if parsed:
            tile_base, sub = parsed
            seen_tiles.setdefault(tile_base, {})[sub] = msb

    for source_msb in sorted(proposals.keys()):
        parsed = parse_tile_id(source_msb)
        if not parsed:
            continue  # not an m60 overworld tile
        tile_base, source_sub = parsed
        sibling_subs = {sub: m for sub, m in seen_tiles.get(tile_base, {}).items()
                        if sub != source_sub}
        if not sibling_subs:
            continue

        for source_pi_str, source_entry in proposals[source_msb].items():
            if not manual_filter(source_entry):
                continue
            source_from_pos = source_entry.get('from_pos')
            if not source_from_pos:
                continue

            for sub, sibling_msb in sorted(sibling_subs.items()):
                # Does the sibling have a part at this pi?
                sib_positions = all_positions['positions'].get(sibling_msb, {})
                sib_vanilla = sib_positions.get(source_pi_str)
                if sib_vanilla is None:
                    if verbose:
                        candidates.append({
                            'source_msb': source_msb, 'source_pi': source_pi_str,
                            'source_entry': source_entry,
                            'sibling_msb': sibling_msb, 'sibling_pi': source_pi_str,
                            'sibling_vanilla_position': None,
                            'skip_reason': 'no_part_at_pi_in_sibling',
                        })
                    continue

                if not positions_match(source_from_pos, sib_vanilla):
                    if verbose:
                        candidates.append({
                            'source_msb': source_msb, 'source_pi': source_pi_str,
                            'source_entry': source_entry,
                            'sibling_msb': sibling_msb, 'sibling_pi': source_pi_str,
                            'sibling_vanilla_position': sib_vanilla,
                            'skip_reason': f'position_mismatch ({source_from_pos} vs {sib_vanilla})',
                        })
                    continue

                # Position matches — is there already a reposition entry?
                existing = proposals.get(sibling_msb, {}).get(source_pi_str)
                if existing is not None:
                    if verbose:
                        candidates.append({
                            'source_msb': source_msb, 'source_pi': source_pi_str,
                            'source_entry': source_entry,
                            'sibling_msb': sibling_msb, 'sibling_pi': source_pi_str,
                            'sibling_vanilla_position': sib_vanilla,
                            'skip_reason': 'already_has_entry',
                        })
                    continue

                # Genuine extension candidate
                candidates.append({
                    'source_msb': source_msb, 'source_pi': source_pi_str,
                    'source_entry': source_entry,
                    'sibling_msb': sibling_msb, 'sibling_pi': source_pi_str,
                    'sibling_vanilla_position': sib_vanilla,
                    'skip_reason': None,
                })
    return candidates


# --- building extension entries -----------------------------------------

def build_extension_entry(source_entry, source_msb, source_pi, sibling_msb,
                          version_tag):
    """Make a new reposition entry for the sibling slot.

    Mirrors the source's from_pos / to_pos shift exactly. Tags the entry
    so it's distinguishable from human-curated entries.
    """
    new_entry = deepcopy(source_entry)
    # Annotate the manual_override block
    mo = new_entry.setdefault('manual_override', {})
    parent_reason = mo.get('reason', 'unspecified')
    mo['reason'] = 'auto_phase_sibling_extension'
    mo['parent_fix'] = {
        'msb': source_msb,
        'pi': source_pi,
        'reason': parent_reason,
    }
    mo['set_by'] = version_tag
    mo['playtest_verified'] = False  # extensions inherit unverified state
    # Replace description with extension note
    mo['description'] = (
        f"Auto-extended from {source_msb} pi={source_pi} by "
        f"extend_repositions_to_phase_siblings.py. Sibling phase tile "
        f"shares vanilla position; same shift applies."
    )
    # Adjust evidence to indicate extension
    src_evidence = new_entry.get('evidence', '')
    new_entry['evidence'] = (
        f"Phase-sibling auto-extension of {source_msb} pi={source_pi}. "
        f"Parent evidence: {src_evidence}"
    )
    new_entry['src'] = new_entry.get('src', '') + '_phase_ext'
    return new_entry


# --- CLI ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true',
                    help='Write extensions to slot_repositions.json. Default: dry-run.')
    ap.add_argument('--include-all-manual', action='store_true',
                    help='Include any entry with a manual_override block (not just '
                         'playtest_* status). Generally not recommended.')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='Print all skipped candidates with reasons.')
    ap.add_argument('--version-tag', default='auto',
                    help='Tag for manual_override.set_by on new entries (default: "auto").')
    ap.add_argument('--slot-repos', default=SLOT_REPOS_PATH)
    ap.add_argument('--part-positions', default=PART_POSITIONS_PATH)
    args = ap.parse_args()

    # Load
    with open(args.slot_repos) as f:
        slot_repos = json.load(f)
    with open(args.part_positions) as f:
        all_positions = json.load(f)

    manual_filter = (is_any_manual_entry if args.include_all_manual
                     else is_manual_playtest_entry)

    candidates = find_extension_candidates(
        slot_repos, all_positions, manual_filter, verbose=args.verbose)

    actionable = [c for c in candidates if c['skip_reason'] is None]
    skipped = [c for c in candidates if c['skip_reason'] is not None]

    # Dedupe: when multiple source entries propose extending to the same
    # sibling (msb, pi) — e.g. both _00 and _20 propose extending to _10 —
    # keep only the first. The entries are identical in content (same shift,
    # same from_pos), so the choice of "parent" is arbitrary; first wins.
    seen_targets = set()
    deduped = []
    for c in actionable:
        key = (c['sibling_msb'], c['sibling_pi'])
        if key in seen_targets:
            continue
        seen_targets.add(key)
        deduped.append(c)
    duplicate_count = len(actionable) - len(deduped)
    actionable = deduped

    # Report
    print(f"Filter: {'all manual_override entries' if args.include_all_manual else 'playtest_* status only'}")
    print(f"Source entries scanned: {sum(1 for msb in slot_repos['proposals'] for pi, e in slot_repos['proposals'][msb].items() if parse_tile_id(msb) and manual_filter(e))}")
    print(f"Extension candidates found: {len(actionable)}"
          f"{f' (after deduping {duplicate_count} redundant proposals)' if duplicate_count else ''}")
    if skipped and args.verbose:
        print(f"Skipped (verbose): {len(skipped)}")
        for s in skipped:
            print(f"  SKIP {s['source_msb']} pi={s['source_pi']} → {s['sibling_msb']}: "
                  f"{s['skip_reason']}")
    print()

    if not actionable:
        print("Nothing to extend — all playtest fixes already cover their phase siblings.")
        return 0

    # List actionable candidates
    print("Actionable extensions:")
    for c in actionable:
        sp = c['source_entry'].get('from_pos')
        tp = c['source_entry'].get('to_pos_center')
        print(f"  {c['source_msb']} pi={c['source_pi']}  ──►  "
              f"{c['sibling_msb']} pi={c['sibling_pi']}")
        print(f"    from {sp} to {tp}  "
              f"(reason: {c['source_entry'].get('manual_override', {}).get('reason', '?')})")
    print()

    if not args.apply:
        print(f"Dry-run only. Re-run with --apply to write {len(actionable)} entries.")
        return 0

    # Apply
    for c in actionable:
        new_entry = build_extension_entry(
            c['source_entry'], c['source_msb'], c['source_pi'],
            c['sibling_msb'], args.version_tag)
        slot_repos['proposals'].setdefault(c['sibling_msb'], {})[c['sibling_pi']] = new_entry

    # Update metadata
    md = slot_repos.setdefault('_meta', slot_repos.setdefault('metadata', {}))
    # The file uses 'metadata' key, not '_meta'. Match the existing schema.
    md = slot_repos['metadata']
    md['total_relocations'] = md.get('total_relocations', 0) + len(actionable)
    md.setdefault('post_processing', []).append({
        'tool': 'extend_repositions_to_phase_siblings.py',
        'version_tag': args.version_tag,
        'filter': 'all_manual' if args.include_all_manual else 'playtest_only',
        'entries_added': len(actionable),
        'slots': [f"{c['sibling_msb']} pi={c['sibling_pi']} (from {c['source_msb']} pi={c['source_pi']})"
                  for c in actionable],
    })

    with open(args.slot_repos, 'w') as f:
        json.dump(slot_repos, f, indent=2)
    print(f"Wrote {len(actionable)} new entries to {args.slot_repos}")
    print(f"total_relocations now: {md['total_relocations']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
