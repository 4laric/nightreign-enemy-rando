"""Force-test diagnostic for FMG splice in the 902-909M ID range.

Per HEALTHBAR_INVESTIGATION_FOLLOWUP.md, MMV proves NR's loader accepts
spliced NpcName.fmg entries when they're placed in the 902M-909M range
between/around existing vanilla groups — and rejects (or appears to
reject) the 911M / extend-g108 placement the rando used in Fix 7/8.

This script runs a Fix-9-strict force test at one specific ID
(905_500_000, in a clean vanilla gap between 905_320_000 "Great Red
Bear" and 905_810_000 "Ancient Hero of Zamor", not touched by MMV
either):

  1. Splice one entry {905_500_000: "RANDO TEST BOSS"} into the
     vanilla item_dlc01.msgbnd → write modified .msgbnd.dcx
  2. For every .emevd in the user's emevd dir, rewrite every healthbar
     callsite's nameId field to 905_500_000 → write patched .emevd,
     DCX-compress
  3. Drop the outputs into a me3-package-shaped tree the user can
     symlink or copy under their NR install.

Expected outcome:
  * If every boss healthbar in-game reads "RANDO TEST BOSS" → loader
    accepts the splice. The 911M placement choice was the bug.
    DEFAULT_FMG_ID_BASE in rewriter.py becomes a tunable in 902-909M.
  * If every bar still reads "?NpcName?" → placement isn't the var
    either. Move to the whole-bundle-repack hypothesis from the
    investigation doc's Open Question 1.

Usage:
  python scripts/test_fmg_splice_905500000.py \
      --vanilla-msgbnd data/vanilla_msg/item_dlc01.msgbnd \
      --raw-emevd     <path to dir of decompressed vanilla .emevd files> \
      --out-dir       test_905_out

  # If you only have the DCX version of the msgbnd, pass --vanilla-msgbnd
  # pointed at the .dcx file; the script will decompress.

  # If you don't have raw_emevd handy: run dcx_batch.py once with --keep-tempdir
  # and grab the decompressed .emevd files from its tempdir's raw_emevd
  # subdir.

After running, copy out_dir/Game/* into your me3 mod package and load
NR. Walk into any boss arena. The bar should read "RANDO TEST BOSS".
"""
import argparse
import os
import sys
import time
from pathlib import Path

# Make project root importable so we can use the healthbar_inplace libs
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))
# healthbar_inplace/pipeline.py does sibling-style `from emevd import ...`,
# so the inner package dir must also be on sys.path.
sys.path.insert(0, str(PROJECT_ROOT / 'healthbar_inplace'))

from healthbar_inplace.bnd import parse_bnd4, write_bnd4
from healthbar_inplace.fmg import parse_fmg, write_fmg, FMGGroup
from healthbar_inplace.emevd import (
    EMEVD, extract_healthbar_callsites, rewrite_many,
)
from healthbar_inplace.pipeline import HANDLER_DEFINITION_FILES
from dcx import DCX, _Oodle


# ---------------------------------------------------------------------------
# Custom splice. Why not use healthbar_inplace.fmg.splice_fmg_entries?
#
# splice_fmg_entries (fmg.py line 383) always APPENDS new groups at the end
# of the groups table. That preserves sort order only when the base ID is
# >= the last existing group's first_id (i.e. >= 911000070 for NpcName).
# All historical rando attempts (970M, 911.1M, 911000151) happen to satisfy
# this, but a 905500000 base would break it: the new group would end up at
# index 109 with first_id=905500000 after g108 at first_id=911000070,
# breaking the [first_id ascending] invariant that holds in both vanilla
# (109 groups, 0 inversions) and MMV (136 groups, 0 inversions).
#
# This custom splice also breaks the previous group's BOUNDARY CLAIM.
# Empirical discovery from the MMV control test: NR's FMG lookup uses
# linear scan with [first_id, last_id] inclusive, returning the FIRST
# matching group's first_string_idx clamped to its actual slot range.
# Vanilla NR has 77 of 109 groups with last_id == next_group.first_id
# (a wide-claim convention extending each group's last_id to touch the
# next group's first_id). When we insert a new group at first_id=X,
# if the previous group's last_id >= X, the previous group "wins" the
# lookup for nameId X and the new entry is never reached. Fix: shrink
# the previous group's last_id to X - 1.
# ---------------------------------------------------------------------------
def splice_one_sorted(fmg_bytes, nameid, text):
    """Splice ONE (nameid, text) entry into an FMG, preserving the
    first_id ascending invariant and breaking the boundary claim of
    the previous group so the lookup for `nameid` cleanly reaches the
    new group. Returns new FMG bytes."""
    fmg = parse_fmg(fmg_bytes)

    # Find insertion index (first group whose first_id > nameid)
    insert_idx = len(fmg.groups)
    for gi, g in enumerate(fmg.groups):
        if g.first_id > nameid:
            insert_idx = gi
            break

    # Break the previous group's wide claim so the lookup for nameid
    # doesn't get caught there first. (See module docstring for why.)
    if insert_idx > 0:
        prev = fmg.groups[insert_idx - 1]
        if prev.last_id >= nameid:
            prev.last_id = nameid - 1

    if insert_idx < len(fmg.groups):
        # We're inserting in the middle. The new group takes over
        # the string slot the next group currently starts at.
        new_string_idx = fmg.groups[insert_idx].first_string_idx
        # Shift all subsequent groups' first_string_idx by +1
        for g in fmg.groups[insert_idx:]:
            g.first_string_idx += 1
        # Shift all strings_by_idx entries at slot >= new_string_idx by +1
        # (iterate in descending order to avoid clobbering)
        old_idx_keys = sorted(
            (k for k in fmg.strings_by_idx if k >= new_string_idx),
            reverse=True,
        )
        for k in old_idx_keys:
            fmg.strings_by_idx[k + 1] = fmg.strings_by_idx.pop(k)
    else:
        # Appending at end (would only hit if nameid is the largest)
        if fmg.groups:
            last = fmg.groups[-1]
            new_string_idx = last.first_string_idx + last.count
        else:
            new_string_idx = 0

    new_group = FMGGroup(
        first_id=nameid,
        first_string_idx=new_string_idx,
        last_id=nameid,    # tight bound: just the one ID
        count=1,
    )
    fmg.groups.insert(insert_idx, new_group)
    fmg.strings_by_idx[new_string_idx] = text

    return write_fmg(fmg)


def splice_msgbnd_one(bundle_bytes, nameid, text):
    """Splice one entry into the NpcName.fmg inside a (raw) msgbnd
    bundle, returning new bundle bytes.

    Uses the project's repack=True BND4 write path. Per bnd.py line 172-183
    + bnd_splice_driver.py line 176-185, the project's splice path
    discovered that NR's loader rejects the append-at-end relocation
    layout and switched to full-repack. We inherit that fix here."""
    bnd = parse_bnd4(bundle_bytes)
    npcname_entry = None
    for e in bnd.entries:
        if e.name.endswith('NpcName.fmg') and 'dlc' not in e.name.lower():
            npcname_entry = e
            break
    if npcname_entry is None:
        raise SystemExit("NpcName.fmg not found in bundle")

    new_fmg = splice_one_sorted(npcname_entry.data, nameid, text)
    npcname_entry.data = new_fmg
    # repack=True lays out all entries contiguously, mirroring vanilla
    # BND4 layout. Required when the spliced FMG grows past the original
    # entry's slot — which it does for any new-id splice.
    return write_bnd4(bnd, original_raw=bundle_bytes, repack=True)

# The pick: a vanilla gap MMV doesn't touch, deep in the 902-909M band
# MMV proves works. Vanilla NR has nothing in (905320000, 905810000).
TEST_NAMEID = 905_500_000
TEST_TEXT = "RANDO TEST BOSS"

DCX_MAGIC = b'DCX\x00'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vanilla-msgbnd', required=True,
                    help='Path to vanilla item_dlc01.msgbnd (raw BND4) OR '
                         'item_dlc01.msgbnd.dcx (will decompress)')
    ap.add_argument('--raw-emevd', required=True,
                    help='Directory containing decompressed vanilla .emevd files '
                         '(name pattern m*_*_*_*.emevd, plus common.emevd, '
                         'common_func.emevd). Easiest source: a dcx_batch run '
                         '--keep-tempdir, then look in <tempdir>/raw_emevd.')
    ap.add_argument('--out-dir', required=True,
                    help='Where to write the test output bundle')
    ap.add_argument('--nameid', type=int, default=TEST_NAMEID,
                    help=f'Override test nameId (default {TEST_NAMEID:_})')
    ap.add_argument('--text', default=TEST_TEXT,
                    help=f'Override test string (default {TEST_TEXT!r})')
    args = ap.parse_args()

    nameid = args.nameid
    text = args.text
    out_dir = Path(args.out_dir)

    # Layout the output tree to match me3's expected internal paths:
    out_msg = out_dir / 'Game' / 'msg' / 'engUS'
    out_event = out_dir / 'Game' / 'event'
    out_msg.mkdir(parents=True, exist_ok=True)
    out_event.mkdir(parents=True, exist_ok=True)

    print(f"=== FMG splice force-test at nameId {nameid:_} ===")
    print(f"Text: {text!r}")
    print(f"Output dir: {out_dir}")
    print()

    # --- Step 1: splice ---
    print(f"[1/3] Splicing nameId={nameid} → {text!r} into NpcName.fmg "
          f"(sorted-insertion, MMV-pattern)")
    vanilla_path = Path(args.vanilla_msgbnd)
    vanilla_bytes = vanilla_path.read_bytes()
    print(f"  Read vanilla bundle: {vanilla_path} ({len(vanilla_bytes):_} bytes, "
          f"{'DCX' if vanilla_bytes[:4] == DCX_MAGIC else 'raw BND4'})")

    oodle = _Oodle.get()  # finds the user's local oo2core_*.dll

    if vanilla_bytes[:4] == DCX_MAGIC:
        # Decompress, splice, recompress at same params as input
        input_compression = vanilla_bytes[0x28:0x2c]
        input_level = vanilla_bytes[0x30]
        raw_bnd = DCX.decompress_bytes(vanilla_bytes, oodle)
        spliced_raw = splice_msgbnd_one(raw_bnd, nameid, text)
        spliced_dcx = DCX.compress_bytes(
            spliced_raw, compression=input_compression,
            level=input_level, oodle=oodle,
        )
    else:
        spliced_raw = splice_msgbnd_one(vanilla_bytes, nameid, text)
        spliced_dcx = DCX.compress_bytes(
            spliced_raw, compression=b'KRAK', level=6, oodle=oodle,
        )

    raw_out = out_msg / 'item_dlc01.msgbnd'
    dcx_out = out_msg / 'item_dlc01.msgbnd.dcx'
    raw_out.write_bytes(spliced_raw)
    dcx_out.write_bytes(spliced_dcx)

    print(f"  Wrote raw spliced bundle: {raw_out} ({raw_out.stat().st_size:_} bytes)")
    print(f"  Wrote DCX spliced bundle: {dcx_out} ({dcx_out.stat().st_size:_} bytes)")

    # Self-verify the splice landed correctly: parse the output, check
    # the new group is at the right sorted position, group count is +1,
    # text is present.
    _bnd = parse_bnd4(spliced_raw)
    for _e in _bnd.entries:
        if _e.name.endswith('NpcName.fmg'):
            _fmg = parse_fmg(_e.data)
            _g_idx = next((gi for gi, g in enumerate(_fmg.groups)
                           if g.first_id == nameid), None)
            if _g_idx is None:
                raise SystemExit(f"  SELF-CHECK FAILED: nameid {nameid} not "
                                  f"found in spliced FMG groups")
            _g = _fmg.groups[_g_idx]
            _txt = _fmg.strings_by_idx.get(_g.first_string_idx)
            if _txt != text:
                raise SystemExit(f"  SELF-CHECK FAILED: spliced text "
                                  f"{_txt!r} != expected {text!r}")
            # Verify sort invariant
            _firsts = [g.first_id for g in _fmg.groups]
            if not all(_firsts[i] <= _firsts[i+1] for i in range(len(_firsts)-1)):
                raise SystemExit(f"  SELF-CHECK FAILED: groups not sorted "
                                  f"by first_id after splice")
            print(f"  SELF-CHECK OK: new group at index {_g_idx}/"
                  f"{len(_fmg.groups)-1}, sort invariant preserved, "
                  f"text matches.")
            break

    # --- Step 2: force-patch all healthbar callsites in every .emevd ---
    print()
    print(f"[2/3] Force-patching healthbar callsites in all .emevd files "
          f"→ nameId={nameid}")
    raw_emevd_dir = Path(args.raw_emevd)
    if not raw_emevd_dir.is_dir():
        sys.exit(f"--raw-emevd is not a directory: {raw_emevd_dir}")
    patched_emevd_dir = out_dir / '_patched_emevd_raw'
    patched_emevd_dir.mkdir(parents=True, exist_ok=True)

    # Mirror the project's canonical exclusion: common.emevd / common_func.emevd
    # define handlers but don't *invoke* them with nameId args. Patching them
    # would corrupt the definitions.
    SKIP = set(HANDLER_DEFINITION_FILES)

    total_callsites = 0
    total_files = 0
    files_patched = 0
    for path in sorted(raw_emevd_dir.iterdir()):
        if path.suffix != '.emevd':
            continue
        if path.name in SKIP:
            continue
        total_files += 1
        raw = path.read_bytes()
        try:
            parsed = EMEVD.parse(raw)
        except Exception as e:
            print(f"  {path.name}: PARSE FAILED ({e}); copying unchanged")
            (patched_emevd_dir / path.name).write_bytes(raw)
            continue
        callsites = extract_healthbar_callsites(parsed)
        if not callsites:
            (patched_emevd_dir / path.name).write_bytes(raw)
            continue
        edits = {cs.name_id_file_offset: nameid for cs in callsites}
        patched = rewrite_many(raw, edits)
        (patched_emevd_dir / path.name).write_bytes(patched)
        files_patched += 1
        total_callsites += len(callsites)
        print(f"  {path.name}: {len(callsites)} callsites → all forced to "
              f"{nameid}")

    print(f"  {total_files} files scanned, {files_patched} patched, "
          f"{total_callsites} total callsites rewritten")

    # --- Step 3: DCX-compress patched EMEVDs ---
    print()
    print(f"[3/3] DCX-compressing patched .emevd files → {out_event}")
    _t0 = time.time()
    from concurrent.futures import ThreadPoolExecutor
    emevd_files = sorted(p for p in patched_emevd_dir.iterdir()
                          if p.suffix == '.emevd')
    def _compress_one(p):
        dst = out_event / (p.name + '.dcx')
        DCX.compress_file(str(p), str(dst), compression=b'KRAK',
                          level=6, oodle=oodle)
        return p.name
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_compress_one, emevd_files))
    print(f"  Compressed {len(emevd_files)} .emevd files "
          f"({time.time() - _t0:.1f}s)")

    print()
    print(f"=== DONE ===")
    print(f"Drop these into your me3 mod package (or directly into <NR install>):")
    print(f"  - {dcx_out}     → Game/msg/engUS/item_dlc01.msgbnd.dcx")
    print(f"  - {out_event}/  → Game/event/*.emevd.dcx")
    print()
    print(f"Then load NR, walk to any boss arena. Every healthbar should read:")
    print(f"  >>>  {text!r}  <<<")
    print()
    print(f"If yes → loader accepts the splice; 911M placement was the bug.")
    print(f"If no  → next experiment: whole-bundle repack (re-pack every "
          f"FMG, not just NpcName).")


if __name__ == "__main__":
    main()
