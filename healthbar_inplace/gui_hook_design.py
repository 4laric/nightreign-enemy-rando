"""
gui_hook_design.py — Design notes + stub code for integrating the
healthbar in-place patcher into oops_rando_gui.py.

This file is a DESIGN doc that compiles. The actual integration goes
into oops_rando_gui.py once you're at the Windows box; the stub here
shows where the hooks attach and what they call.

Two integration points, paired:

  CHECKBOX (default flow):
    A single boolean toggle in the post-rando settings:
      [✓] Rewrite boss healthbars to match swapped chrs

    When checked, the rando finishes its MSB pass, then pipeline.py
    runs automatically with default policy (vanilla nameId reuse +
    composite names for heterogeneous squads). The patched .emevd.dcx
    files land in the same me3 profile event/ dir that
    _install_prepatched_emevd writes to.

    This handles the 80% case: "I just want the names to match."

  TAB (curation flow):
    "Healthbar Names" tab. After randomization, the tab populates
    with a table of every healthbar callsite that's about to change:

      callsite           | vanilla name        | new name (auto)     | override
      m49_27 / 90015000  | Battlefield Commander | Graven School    | [text input]
      m48_50 / 90015023#0 | Tree Sentinel       | TS + Royal Cav ×2 | [text input]
      ...

    User edits any "override" field to substitute a cute / custom
    name (the "Putrid Shaman of the King Consort" use case from
    DEMO_PREP.md). Click "Apply" -> pipeline.py runs with overrides
    passed in as a per-callsite override dict.

    This handles the 20% case: demos, content creation.

Failure modes the GUI should surface:
  - Vanilla EMEVD missing from input dir (vanilla NR not installed
    or me3 profile not set up): "Could not find m49_25_00_00.emevd.dcx
    in <event_dir>. Run vanilla NR once or set the event_dir option."
  - Offsets manifest mismatch (NR patched, callsite_offsets.json stale):
    "Healthbar offsets manifest doesn't match this EMEVD version. The
    rando ships a per-NR-patch manifest; if you're on a newer NR, the
    healthbar patcher will be skipped until the manifest is rebuilt."
  - FMG file not loaded / out-of-range nameIds: render the
    fmg_additions.json count + path; tell user to import into FMG.
    A future v0.24 follow-up is an automatic FMG patcher that does
    this step too, but v0.24.0-dev stops at emitting the JSON.
"""

# ────────────────────────────────────────────────────────────────────
# Stub: checkbox flow
# ────────────────────────────────────────────────────────────────────

# In oops_rando_gui.py near the post-rando settings frame:
"""
# >>> add to settings frame:
self.healthbar_rewrite_var = tk.BooleanVar(value=True)
ttk.Checkbutton(
    settings_frame,
    text="Rewrite boss healthbars to match swapped chrs",
    variable=self.healthbar_rewrite_var,
).pack(anchor='w', pady=2)

# >>> in the post-rando completion handler (after MSBs are written):
if self.healthbar_rewrite_var.get():
    self._run_healthbar_rewrite()

def _run_healthbar_rewrite(self):
    '''Run pipeline.run_pipeline() with current spoiler + me3 paths.
    Renders summary in the log pane.'''
    from healthbar_inplace.pipeline import run_pipeline, DEFAULT_FMG_ID_BASE
    paths = self._load_emevd_paths()
    me3_event_dir = paths.get('me3_event_dir')
    spoiler_path = os.path.join(self.last_output_dir, '_spoilers.json')
    chr_catalog = os.path.join(HERE, 'data', 'chr_to_nameid.json')
    if not me3_event_dir or not os.path.isdir(me3_event_dir):
        self._log("Healthbar rewrite: me3 event/ dir not configured; skipping.\\n", 'warn')
        return
    if not os.path.exists(chr_catalog):
        self._log("Healthbar rewrite: chr_to_nameid.json not built yet; skipping. "
                  "Run prep_demo.py BUILD-CATALOG once.\\n", 'warn')
        return
    try:
        report = run_pipeline(
            spoiler_path=spoiler_path,
            input_emevd_dir=me3_event_dir,
            output_emevd_dir=me3_event_dir,  # in-place; pipeline backs up to .bak first
            chr_to_nameid_path=chr_catalog,
            fmg_id_base=DEFAULT_FMG_ID_BASE,
        )
        n_ok = sum(1 for f in report['files'] if f['status'] == 'ok')
        n_rewrites = sum(f.get('rewrites', 0) for f in report['files'])
        self._log(f"Healthbar rewrite: patched {n_ok} files, "
                  f"{n_rewrites} rewrites, {report['fmg_additions_count']} "
                  f"new FMG entries.\\n", 'ok')
        if report['fmg_additions_count']:
            self._log(f"FMG additions JSON: {report['fmg_additions_path']}\\n"
                      f"Import these into your boss-name FMG before launching.\\n",
                      'info')
    except Exception as e:
        self._log(f"Healthbar rewrite FAILED: {e}\\n", 'err')
"""


# ────────────────────────────────────────────────────────────────────
# Stub: curation tab
# ────────────────────────────────────────────────────────────────────

# A new tab "Healthbar Names" added to the main notebook:
"""
# >>> add to main notebook setup:
self.healthbar_tab = ttk.Frame(self.notebook)
self.notebook.add(self.healthbar_tab, text='Healthbar Names')
self._build_healthbar_tab()

def _build_healthbar_tab(self):
    '''Layout:
      Top:   "Load from last rando" button (auto-fills from
             self.last_output_dir/_spoilers.json)
      Middle: Treeview with columns:
              file | callsite | swap (chr names) | auto-name | override
              Each row is editable on the 'override' column.
      Bottom: Apply / Reset / Export name_table buttons
    '''
    top = ttk.Frame(self.healthbar_tab)
    top.pack(fill='x', pady=4)
    ttk.Button(top, text='Load from last rando',
               command=self._load_healthbar_from_last_rando).pack(side='left')
    ttk.Button(top, text='Apply', command=self._apply_healthbar_curation).pack(side='right')

    tree = ttk.Treeview(self.healthbar_tab,
                        columns=('file', 'callsite', 'swap', 'auto', 'override'),
                        show='headings')
    for col in ('file', 'callsite', 'swap', 'auto', 'override'):
        tree.heading(col, text=col)
    tree.pack(fill='both', expand=True)
    self.healthbar_tree = tree
    # Bind double-click on 'override' column to inline edit
    tree.bind('<Double-1>', self._healthbar_inline_edit)

def _load_healthbar_from_last_rando(self):
    '''Run the pipeline in PREVIEW mode (decide_rewrites only, no
    byte writes), populate the treeview with the decisions.'''
    from healthbar_inplace import pipeline, rewriter, emevd, oracle
    # ... preview code ...
    pass

def _apply_healthbar_curation(self):
    '''Read overrides from the treeview, pass to pipeline as a
    per-callsite override dict, run for real.'''
    pass
"""


# ────────────────────────────────────────────────────────────────────
# Implementation order (Alaric's call which to do first)
# ────────────────────────────────────────────────────────────────────
#
# Option 1: Ship CHECKBOX first. Smallest GUI change, covers 80% of
# users. Add it to a dot release (v0.24.0 say) once the in-place
# patcher passes verify.py on every map in the corpus. Curation tab
# follows in v0.24.
#
# Option 2: Ship TAB first. More work but lets you (Alaric) start
# producing curated demos immediately. The checkbox can wire up to
# "Apply" with all-defaults internally.
#
# Recommendation: Option 1. The checkbox is one boolean + ~30 lines
# of glue, and it un-blocks every user who wants their healthbars to
# match. Curation is a power-user / demo workflow that already has a
# CLI flow in healthbar_tools/ — you can keep using that for demos
# while the tab is being built.
