"""MMV-bundle control diagnostic.

We don't know whether the failed 905M splice test means:
  (A) the spliced .msgbnd.dcx isn't reaching NR's loader, or
  (B) it's reaching the loader but the loader rejects the new entry.

This script uses MMV's pre-existing .msgbnd.dcx — which we know works
in NR, since MMV ships and runs cleanly — as a control. It force-
rewrites every healthbar callsite to nameId 904_956_000, which is
"Twin Moon Knight" in MMV's NpcName.fmg (one of MMV's added entries
that's confirmed loadable). Then DCX-compresses the EMEVDs and drops
everything in an output tree.

If you load it and bars read "Twin Moon Knight":
  → MMV's bundle is reaching the loader from your install
  → our splice-script's output is the variable
  → byte-diff ours vs MMV to find the structural difference

If bars read "?NpcName?":
  → MMV's bundle isn't loading either
  → it's a me3 / install / mod-ordering issue
  → check that test_904_mmv_out/Game/msg/engUS/item_dlc01.msgbnd.dcx
    is actually being read at runtime by NR (verify your me3 package
    structure, mod activation, file priority)

Usage:
  python scripts/test_mmv_control.py \\
      --mmv-msgbnd    /path/to/mmv/item_dlc01.msgbnd.dcx \\
      --raw-emevd     <dir of decompressed vanilla .emevd files> \\
      --out-dir       test_904_mmv_out
"""
import argparse
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'healthbar_inplace'))

from healthbar_inplace.emevd import (
    EMEVD, extract_healthbar_callsites, rewrite_many,
)
from healthbar_inplace.pipeline import HANDLER_DEFINITION_FILES
from dcx import DCX, _Oodle

# MMV-added nameId, confirmed in MMV's NpcName.fmg (group #90, slot 427)
TEST_NAMEID = 904_956_000
TEST_TEXT_EXPECTED = "Twin Moon Knight"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mmv-msgbnd', required=True,
                    help='Path to MMV item_dlc01.msgbnd.dcx (raw KRAK-compressed; '
                         'this gets copied verbatim, no modification)')
    ap.add_argument('--raw-emevd', required=True,
                    help='Directory of decompressed vanilla NR .emevd files')
    ap.add_argument('--out-dir', required=True,
                    help='Output dir (drop into your me3 mod package)')
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_msg = out_dir / 'Game' / 'msg' / 'engUS'
    out_event = out_dir / 'Game' / 'event'
    out_msg.mkdir(parents=True, exist_ok=True)
    out_event.mkdir(parents=True, exist_ok=True)

    print(f"=== MMV-bundle control diagnostic ===")
    print(f"Target nameId: {TEST_NAMEID:_}")
    print(f"Expected text in-game: {TEST_TEXT_EXPECTED!r}")
    print()

    # --- Step 1: copy MMV's bundle verbatim ---
    print(f"[1/3] Copying MMV bundle (no modification)")
    src_bundle = Path(args.mmv_msgbnd)
    dst_bundle = out_msg / 'item_dlc01.msgbnd.dcx'
    dst_bundle.write_bytes(src_bundle.read_bytes())
    print(f"  {src_bundle} → {dst_bundle} ({dst_bundle.stat().st_size:_} bytes)")

    # --- Step 2: force-rewrite all healthbar callsites to TEST_NAMEID ---
    print()
    print(f"[2/3] Force-patching all healthbar callsites → nameId={TEST_NAMEID}")
    raw_emevd_dir = Path(args.raw_emevd)
    patched_dir = out_dir / '_patched_emevd_raw'
    patched_dir.mkdir(parents=True, exist_ok=True)

    SKIP = set(HANDLER_DEFINITION_FILES)
    total_files = 0
    files_patched = 0
    total_callsites = 0
    for p in sorted(raw_emevd_dir.iterdir()):
        if p.suffix != '.emevd' or p.name in SKIP:
            continue
        total_files += 1
        raw = p.read_bytes()
        try:
            parsed = EMEVD.parse(raw)
        except Exception as e:
            print(f"  {p.name}: PARSE FAILED ({e}); copying unchanged")
            (patched_dir / p.name).write_bytes(raw)
            continue
        callsites = extract_healthbar_callsites(parsed)
        if not callsites:
            (patched_dir / p.name).write_bytes(raw)
            continue
        edits = {cs.name_id_file_offset: TEST_NAMEID for cs in callsites}
        patched = rewrite_many(raw, edits)
        (patched_dir / p.name).write_bytes(patched)
        files_patched += 1
        total_callsites += len(callsites)

    print(f"  {total_files} files scanned, {files_patched} patched, "
          f"{total_callsites} total callsites rewritten")

    # --- Step 3: DCX-compress patched EMEVDs ---
    print()
    print(f"[3/3] DCX-compressing patched .emevd files → {out_event}")
    _t0 = time.time()
    oodle = _Oodle.get()
    emevd_files = sorted(p for p in patched_dir.iterdir() if p.suffix == '.emevd')

    def _compress_one(p):
        dst = out_event / (p.name + '.dcx')
        DCX.compress_file(str(p), str(dst), compression=b'KRAK',
                          level=6, oodle=oodle)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_compress_one, emevd_files))
    print(f"  Compressed {len(emevd_files)} .emevd files "
          f"({time.time() - _t0:.1f}s)")

    print()
    print(f"=== DONE ===")
    print(f"Drop test_904_mmv_out/Game/* into your me3 mod package.")
    print(f"Load NR, walk to any boss arena.")
    print()
    print(f"  bars read 'Twin Moon Knight'  → MMV bundle is loading; our splice")
    print(f"                                  script is producing something")
    print(f"                                  different from MMV's working file.")
    print(f"                                  Next: byte-diff our 905M splice")
    print(f"                                  output against MMV.")
    print()
    print(f"  bars read '?NpcName?'         → MMV bundle isn't loading either.")
    print(f"                                  It's a me3 / install / mod-ordering")
    print(f"                                  issue. Verify the .msgbnd.dcx is")
    print(f"                                  actually being read at runtime")
    print(f"                                  (mod priority, package structure).")


if __name__ == "__main__":
    main()
