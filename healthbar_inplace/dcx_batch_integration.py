"""dcx_batch_integration.py — Integration sketch for dcx_batch.py.

v0.24.0-dev — paste-target code for wiring the healthbar in-place
patcher into the existing MSB pipeline.

dcx_batch.py already has working Oodle integration for MSBs. The
.dcx format is format-agnostic (same DCX/Kraken wrapper for any
FromSoft binary), so adding EMEVD support is mostly extension-filter
duplication plus a single new pipeline-pass call.

Three additions, in order:

  1. emevd_decompress_dir(in_dir, out_dir) — sister of decompress_dir.
     Same code, different filter and message.
  2. emevd_compress_dir(in_dir, out_dir) — sister of compress_dir.
  3. Patch rando_pipeline to call the new EMEVD pass between MSB
     compress and final output.

Below is the literal paste-target code, lifted from dcx_batch.py's
existing decompress_dir / compress_dir with the necessary edits
marked with CHANGED comments.
"""

# ────────────────────────────────────────────────────────────────────
# Addition 1: emevd_decompress_dir
# Paste into dcx_batch.py, right after decompress_dir().
# ────────────────────────────────────────────────────────────────────

EMEVD_DECOMPRESS_DIR = '''
def emevd_decompress_dir(in_dir, out_dir, oodle=None):
    """v0.24.0: Decompress every .emevd.dcx in in_dir to .emevd in out_dir.

    Sister of decompress_dir. Identical mechanics — DCX format is the
    same regardless of payload type — just a different file-extension
    filter and a slightly different message string.

    Unlike decompress_dir there's no passthrough_set fast-path; EMEVD
    files don't have a HUB_MAPS-style untouched set. Every healthbar-
    candidate file gets decompressed, scanned, and potentially patched.
    """
    os.makedirs(out_dir, exist_ok=True)
    if oodle is None: oodle = _Oodle.get()
    files = sorted(f for f in os.listdir(in_dir) if f.endswith('.emevd.dcx'))
    n_workers = _worker_count()
    print(f"Decompressing {len(files)} .emevd.dcx files (workers={n_workers})...")
    t0 = time.time()

    def _one(f):
        src = os.path.join(in_dir, f)
        dst = os.path.join(out_dir, f[:-4])  # strip .dcx
        try:
            raw = DCX.decompress_file(src, oodle=oodle)
            with open(dst, 'wb') as fp:
                fp.write(raw)
            return (f, len(raw), None)
        except Exception as e:
            return (f, 0, str(e))

    from concurrent.futures import ThreadPoolExecutor
    failed = []
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        for f, sz, err in ex.map(_one, files):
            if err:
                failed.append((f, err))
    dt = time.time() - t0
    print(f"  done in {dt:.2f}s ({len(files) - len(failed)}/{len(files)} ok)")
    for f, err in failed:
        print(f"  FAILED: {f}: {err}")
    return failed
'''


# ────────────────────────────────────────────────────────────────────
# Addition 2: emevd_compress_dir
# Paste into dcx_batch.py, right after compress_dir().
# ────────────────────────────────────────────────────────────────────

EMEVD_COMPRESS_DIR = '''
def emevd_compress_dir(in_dir, out_dir, oodle=None):
    """v0.24.0: Compress every .emevd in in_dir to .emevd.dcx in out_dir.

    Sister of compress_dir. NR's DCX header for EMEVDs uses the same
    Kraken/level-6 configuration as MSBs (empirically — DCX is set per
    archive bnd, and NR's BNDs nest .msb.dcx and .emevd.dcx with the
    same compression knobs).
    """
    os.makedirs(out_dir, exist_ok=True)
    if oodle is None: oodle = _Oodle.get()
    files = sorted(f for f in os.listdir(in_dir) if f.endswith('.emevd'))
    n_workers = _worker_count()
    print(f"Compressing {len(files)} .emevd files (workers={n_workers})...")
    t0 = time.time()

    def _one(f):
        src = os.path.join(in_dir, f)
        dst = os.path.join(out_dir, f + '.dcx')
        try:
            DCX.compress_file(src, dst, oodle=oodle)
            return (f, None)
        except Exception as e:
            return (f, str(e))

    from concurrent.futures import ThreadPoolExecutor
    failed = []
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        for f, err in ex.map(_one, files):
            if err:
                failed.append((f, err))
    dt = time.time() - t0
    print(f"  done in {dt:.2f}s ({len(files) - len(failed)}/{len(files)} ok)")
    for f, err in failed:
        print(f"  FAILED: {f}: {err}")
    return failed
'''


# ────────────────────────────────────────────────────────────────────
# Addition 3: hook into rando_pipeline
# Insert the new section into dcx_batch.rando_pipeline after the MSB
# compress step. The exact insertion point will depend on the current
# rando_pipeline shape in dcx_batch.py — find the "compress MSBs back
# to .dcx" step and add the healthbar pass after it.
# ────────────────────────────────────────────────────────────────────

RANDO_PIPELINE_HOOK = '''
    # ──────────────────────────────────────────────────────────────
    # v0.24.0: Healthbar in-place patcher.
    #
    # Sits between MSB compress and final-output stage. Same Oodle
    # passes as MSBs (Kraken/level-6); patcher itself is pure Python
    # operating on raw .emevd bytes.
    #
    # Opt-in via the rewrite_healthbars kwarg (GUI sets it from the
    # checkbox in oops_rando_gui.py). When disabled, this block is a
    # no-op and the vanilla .emevd.dcx files stay as the game finds
    # them.
    # ──────────────────────────────────────────────────────────────
    if rewrite_healthbars:
        # Validate prerequisites: chr_to_nameid catalog must exist.
        chr_catalog = os.path.join(HERE, 'data', 'chr_to_nameid.json')
        if not os.path.exists(chr_catalog):
            print("Healthbar rewrite SKIPPED: chr_to_nameid.json not built. "
                  "Run prep_demo.py BUILD-CATALOG once to generate it.")
        else:
            # Per-run temp dirs. Persist them inside out_dcx_dir for
            # debuggability — if a run goes wrong, the raw .emevd files
            # are right there to inspect.
            raw_emevd_tmp = os.path.join(out_dcx_dir, '_healthbar_raw_emevd')
            patched_emevd_tmp = os.path.join(out_dcx_dir, '_healthbar_patched_emevd')

            # Source dir: same place we read vanilla MSBs from. Vanilla
            # .emevd.dcx files live alongside .msb.dcx in NR's
            # map/mapstudio/.. hierarchy. The caller passes the
            # corresponding emevd-source dir (TBD per dcx_batch
            # invocation shape).
            print(f"Healthbar rewrite: decompressing EMEVDs...")
            emevd_decompress_dir(vanilla_emevd_dcx_dir, raw_emevd_tmp)

            print(f"Healthbar rewrite: applying byte edits...")
            from healthbar_inplace.pipeline import apply_to_dir
            report = apply_to_dir(
                emevd_dir=raw_emevd_tmp,
                output_dir=patched_emevd_tmp,
                spoiler_path=spoiler_path,
                chr_to_nameid_path=chr_catalog,
            )
            n_ok = sum(1 for f in report['files'] if f['status'] == 'ok')
            n_rewrites = sum(f.get('rewrites', 0) for f in report['files'])
            print(f"  {n_ok} files patched, {n_rewrites} healthbar rewrites")
            print(f"  FMG additions: {report['fmg_additions_count']} new "
                  f"-> {report['fmg_additions_path']}")

            print(f"Healthbar rewrite: recompressing EMEVDs...")
            emevd_compress_dir(patched_emevd_tmp, out_dcx_dir)
'''


# ────────────────────────────────────────────────────────────────────
# CLI integration: the rando_pipeline argparse needs a new flag.
# ────────────────────────────────────────────────────────────────────

CLI_FLAG = '''
    # Add to dcx_batch.rando_pipeline argparse:
    ap.add_argument('--rewrite-healthbars', action='store_true',
                    help='v0.24.0: Patch boss healthbar nameIds to match swapped '
                         'chrs. Requires data/chr_to_nameid.json (run '
                         'prep_demo.py BUILD-CATALOG once).')

    # And in the rando_pipeline function signature:
    def rando_pipeline(in_dcx_dir, out_dcx_dir, *, seed=42, mode='loose',
                       rewrite_healthbars=False,
                       vanilla_emevd_dcx_dir=None,
                       spoiler_path=None,
                       ...):
'''


# ────────────────────────────────────────────────────────────────────
# What's left for Alaric to decide
# ────────────────────────────────────────────────────────────────────

OPEN_QUESTIONS = """
1. Vanilla EMEVD source dir. The MSB pipeline takes in_dcx_dir as the
   vanilla source. EMEVDs are in the same NR install (under
   action/event/ relative to the game root I believe). Decision:
     a) reuse in_dcx_dir and assume it's the game root with both MSBs
        and EMEVDs underneath (simplest; matches MSB convention)
     b) take an explicit --vanilla-emevd-dir arg (more flexible; lets
        users point at any decompressed EMEVD source)
   Recommendation: (a). Add the path-resolution inside emevd_decompress_dir
   to figure out the actual subdirectory (NR puts EMEVDs in event/
   per the standard FromSoft layout).

2. Per-run tmp dir cleanup. The hook writes raw_emevd_tmp and
   patched_emevd_tmp into out_dcx_dir for debuggability. Some users
   might not want those left behind. Decision:
     a) leave them (debuggability, ~700 KB common_func + 30 map files
        ~ 5 MB total; trivial)
     b) cleanup at end
     c) keep on failure, cleanup on success
   Recommendation: (a) for v0.24.0, revisit if anyone complains.

3. FMG additions handling. Today the pipeline emits
   fmg_additions.json and the user has to import into a boss-name
   FMG manually via WitchyBND. v0.24.0 ships that workflow. The
   FMG binary patcher is the obvious v0.24.x follow-up — once that
   lands, this step becomes invisible.
"""


if __name__ == "__main__":
    print(__doc__)
    print("=== Addition 1: emevd_decompress_dir ===")
    print(EMEVD_DECOMPRESS_DIR)
    print("=== Addition 2: emevd_compress_dir ===")
    print(EMEVD_COMPRESS_DIR)
    print("=== Addition 3: rando_pipeline hook ===")
    print(RANDO_PIPELINE_HOOK)
    print("=== CLI flag ===")
    print(CLI_FLAG)
    print("=== Open questions ===")
    print(OPEN_QUESTIONS)
