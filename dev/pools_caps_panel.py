"""pools_caps_panel.py — the "Pools & Caps" GUI tab (v0.27.x rebuild).

Self-contained mixin folded into RandoGUI. It owns three things the engine
exposes as per-run overrides (see engine.runtime.compose_pool_cap_overrides):

  1. POOL MEMBERSHIP (replaces the old Excluded Enemies tab)
     Two-pane include/exclude of c-prefixes. The excluded set drives
     engine_kwargs['excluded_prefixes'] exactly as the old tab did, so
     removing that tab loses no capability — it's absorbed here.

  2. CALIBER POOL (the "all DLC run" lever)
     Per-prefix membership in V3_NIGHT_BOSS_CALIBER_TARGETS — the set
     eligible to anchor Night-Boss arena slots. extras get unioned in,
     removals subtracted. SoTE/MMV-import bosses aren't in the base
     caliber set, so this is how you make them anchor NB arenas.

  3. CAPS
     Per-prefix placement-ceiling overrides merged onto
     V3_UNIQUE_TARGET_CAPS. >= 1 (a 0 would starve the reservation pass;
     use exclude instead).

Design: reads data/*.json and the oops_v3 engine constants directly so it
can be previewed standalone (python dev/pools_caps_panel.py). All run-scoped
state lives on the host GUI as self._pc_* attributes; nothing mutates engine
globals here — the engine does that per-run via compose_pool_cap_overrides
and restores via apply_run_overrides.

The host GUI calls:
  - self._pc_init_state()              once, before _build_ui
  - self._build_pools_caps_tab(parent) to render the tab
  - self.pools_caps_engine_config()    at run time -> dict of the 3 overrides
  - self._pc_excluded_set()            -> the live excluded prefix set
"""
import os
import json
import tkinter as tk
from tkinter import ttk

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_DATA = os.path.join(_ROOT, 'data')

# Pull the host GUI's dark palette so the panel matches the rest of the app.
# Falls back to a self-contained dark palette for standalone preview.
try:
    import sys as _sys
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)
    from oops_rando_gui import THEME as _THEME
except Exception:  # noqa: BLE001
    _THEME = {
        'bg': '#1a1a1d', 'surface': '#23232a', 'surface_alt': '#2c2c34',
        'border': '#3a3a44', 'text': '#e8e8ea', 'text_dim': '#9a9aa0',
        'text_faint': '#6a6a72', 'accent': '#d4a45e',
    }


def _c(key, default='#1a1a1d'):
    return _THEME.get(key, default)


def _load_engine_defaults():
    """Pull caliber set + caps + roster prefix->name from the live engine.

    Falls back to empty/standalone data if oops_v3 can't import (e.g. when
    previewing this module in isolation without the engine on the path).

    Returns (caliber, caps, prefixes, excluded, hidden) where:
      prefixes : {cp -> display name}, combat-placeable chrs only
      hidden   : {cp} of non-combat tiers filtered out of the lists
                 (templates, players, NPCs, Revenants, mount pieces)
    """
    caliber, caps, prefixes, excluded = set(), {}, {}, set()
    tier_of, name_of = {}, {}
    try:
        import sys
        if _ROOT not in sys.path:
            sys.path.insert(0, _ROOT)
        import oops_v3
        caliber = set(oops_v3.V3_NIGHT_BOSS_CALIBER_TARGETS)
        caps = dict(oops_v3.V3_UNIQUE_TARGET_CAPS)
        excluded = set(getattr(oops_v3, 'V3_EXCLUDE_PREFIXES', set()))
    except Exception as e:  # noqa: BLE001
        print(f"[pools_caps_panel] engine defaults unavailable ({e!r}); "
              f"standalone preview mode")
    # tags.json: authoritative tier + name (one entry per prefix)
    try:
        tags = json.load(open(os.path.join(_DATA, 'nr_enemy_tags.json')))
        for cp, t in tags.items():
            if isinstance(t, dict):
                tier_of[cp] = t.get('tier', '')
                if t.get('name'):
                    name_of[cp] = t['name']
    except Exception as e:  # noqa: BLE001
        print(f"[pools_caps_panel] tags unavailable ({e!r})")
    # roster: fills names tags didn't have (prefer first NON-blank)
    try:
        roster = json.load(open(os.path.join(_DATA, 'nr_enemy_roster.json')))
        for v in roster.get('all_variants', []):
            cp = v.get('c_prefix')
            if not cp:
                continue
            nm = (v.get('variant_name') or '').strip()
            if nm and not name_of.get(cp):
                name_of[cp] = nm
            name_of.setdefault(cp, '')   # ensure the prefix is known
    except Exception as e:  # noqa: BLE001
        print(f"[pools_caps_panel] roster unavailable ({e!r})")

    # Filter out non-combat tiers — these are never placeable enemies and
    # only clutter the lists: cinematic (player/template/NPC/Revenant
    # cutscene actors), non_combat, and mount_component (horse/mount pieces
    # placed via the rider, never standalone).
    HIDE_TIERS = {'cinematic', 'non_combat', 'mount_component'}
    hidden = set()
    for cp in list(name_of):
        if tier_of.get(cp, '') in HIDE_TIERS:
            hidden.add(cp)
        else:
            prefixes[cp] = name_of[cp]
    return caliber, caps, prefixes, excluded, hidden


class PoolsCapsPanelMixin:
    """Mixin providing the Pools & Caps tab. See module docstring."""

    _PC_AVAILABLE = True

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def _pc_init_state(self):
        """Initialize panel state. Call before _build_ui.

        Reads engine defaults once. self._pc_excluded is seeded from the
        host's self.excluded if it already exists (so the old DEFAULT_EXCLUDED
        seeding still applies), else from the engine's hard-exclude set.
        """
        caliber, caps, prefixes, eng_excluded, hidden = _load_engine_defaults()
        self._pc_default_caliber = caliber
        self._pc_default_caps = caps
        self._pc_prefix_names = prefixes        # cp -> name, combat chrs only
        self._pc_hidden_prefixes = hidden       # non-combat tiers, filtered out
        # exclusion set: prefer whatever the host already set up
        seed_excluded = getattr(self, 'excluded', None)
        if seed_excluded is None:
            seed_excluded = set(eng_excluded)
        self.excluded = set(seed_excluded)      # canonical exclude set
        self._pc_excluded = self.excluded       # alias the panel mutates

        # caliber extras/removals are deltas vs the engine default
        self._pc_caliber_extras = set()         # cp added to NB-anchor pool
        self._pc_caliber_removals = set()       # cp removed from NB-anchor pool
        # cap overrides: cp -> int (only entries the user changed)
        self._pc_cap_overrides = {}

        self._pc_search_var = None              # built lazily in the tab
        self._pc_widgets_ready = False

    def _pc_all_prefixes(self):
        """Sorted (cp, name) for every roster prefix."""
        return sorted(self._pc_prefix_names.items())

    def _pc_excluded_set(self):
        """The live excluded prefix set (for engine_kwargs)."""
        return set(self.excluded)

    # ------------------------------------------------------------------
    # engine config — called at run time
    # ------------------------------------------------------------------
    def pools_caps_engine_config(self):
        """Return the 3 override kwargs for the run config.

        Empty selections come back as None so an untouched panel produces a
        run byte-identical to a pre-panel run. Pool membership (excluded) is
        threaded separately via engine_kwargs['excluded_prefixes'] — it's not
        returned here to avoid double-sourcing.
        """
        caps = ({cp: int(v) for cp, v in self._pc_cap_overrides.items()}
                if self._pc_cap_overrides else None)
        extras = (sorted(self._pc_caliber_extras)
                  if self._pc_caliber_extras else None)
        removals = (sorted(self._pc_caliber_removals)
                    if self._pc_caliber_removals else None)
        return {
            'unique_cap_overrides': caps,
            'caliber_pool_extras': extras,
            'caliber_pool_removals': removals,
        }

    # ------------------------------------------------------------------
    # presets
    # ------------------------------------------------------------------
    def _pc_apply_all_dlc(self):
        """All-DLC preset: union every SoTE/heritage-import prefix into the
        caliber (NB-anchor) extras so DLC bosses can anchor Night arenas.

        Heritage-import prefixes are those flagged _heritage_imported in the
        roster; SoTE bosses are mmv_import chrs. We approximate "DLC content"
        as any roster prefix not already in the base caliber set whose chr is
        a known boss-tier import. To stay conservative and avoid promoting
        trash mobs to NB anchors, we only add prefixes that already carry a
        cap (caps are authored for notable/unique chrs).
        """
        candidates = set(self._pc_default_caps) - self._pc_default_caliber
        self._pc_caliber_extras |= candidates
        self._pc_caliber_removals -= candidates
        self._pc_refresh_caliber()
        self._pc_log(f"All-DLC preset: +{len(candidates)} prefixes into the "
                     f"caliber (NB-anchor) pool")

    def _pc_reset_all(self):
        # Only prompt if there's actually something to lose — keeps the
        # button friction-free when the panel is already at defaults.
        has_changes = bool(self._pc_caliber_extras or self._pc_caliber_removals
                           or self._pc_cap_overrides
                           or self.excluded != getattr(self, '_pc_seed_excluded',
                                                       self.excluded))
        if has_changes:
            try:
                from tkinter import messagebox
                if not messagebox.askyesno(
                        "Reset to engine defaults?",
                        "This clears every override in this panel and restores "
                        "the engine defaults for caps, the caliber (NB-anchor) "
                        "pool, and pool membership.\n\nContinue?"):
                    return
            except Exception:  # noqa: BLE001
                pass  # headless / no Tk — just proceed
        self._pc_caliber_extras.clear()
        self._pc_caliber_removals.clear()
        self._pc_cap_overrides.clear()
        self.excluded = set(getattr(self, '_pc_seed_excluded', self.excluded))
        self._pc_excluded = self.excluded
        self._pc_refresh_all()
        self._pc_log("reset to engine defaults (caps, caliber pool, "
                     "pool membership)")

    def _pc_tooltip(self, widget, text):
        """Attach a hover tooltip using the host GUI's Tooltip helper if
        available; silently no-op otherwise (standalone preview)."""
        try:
            from oops_rando_gui import Tooltip
            Tooltip(widget, text)
        except Exception:  # noqa: BLE001
            pass

    def _pc_log(self, msg):
        """Best-effort status line; no-op if host has no log sink."""
        q = getattr(self, 'log_queue', None)
        if q is not None:
            try:
                q.put(f"[Pools & Caps] {msg}\n")
                return
            except Exception:  # noqa: BLE001
                pass
        print(f"[Pools & Caps] {msg}")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_pools_caps_tab(self, parent):
        self._pc_seed_excluded = set(self.excluded)  # for Reset
        self._pc_search_var = tk.StringVar()
        self._pc_search_var.trace_add('write',
                                      lambda *_: self._pc_refresh_membership())

        # header
        h = ttk.Frame(parent, padding=8)
        h.pack(fill='x')
        ttk.Label(
            h,
            text=("Tune the per-run enemy pool: include/exclude chrs, adjust "
                  "which can anchor Night-Boss arenas (caliber pool), and set "
                  "per-enemy placement caps. Untouched = identical to a "
                  "default run."),
            wraplength=820).pack(side='left', anchor='w')
        if hasattr(self, '_add_help_button'):
            try:
                self._add_help_button(h, 'pools_caps')
            except Exception:  # noqa: BLE001
                pass

        # toolbar: presets
        tb = ttk.Frame(parent, padding=(8, 0))
        tb.pack(fill='x')
        b_dlc = ttk.Button(tb, text="All-DLC run",
                           command=self._pc_apply_all_dlc)
        b_dlc.pack(side='left')
        b_reset = ttk.Button(tb, text="Reset to engine defaults",
                             command=self._pc_reset_all)
        b_reset.pack(side='left', padx=6)
        # tooltips spell out exactly what each preset does, so "reset"
        # isn't ambiguous about what it reverts.
        self._pc_tooltip(
            b_dlc,
            "Add every DLC / heritage-import boss prefix to the caliber "
            "(Night-Boss anchor) pool in one click. Leaves caps and pool "
            "membership alone.")
        self._pc_tooltip(
            b_reset,
            "Revert ALL three sections to the engine defaults:\n"
            "  • Caps  -> the built-in V3_UNIQUE_TARGET_CAPS values\n"
            "  • Caliber pool -> the default NB-anchor set\n"
            "  • Pool membership -> the default exclude list\n"
            "Clears every override you've set in this panel.")
        self._pc_summary_label = ttk.Label(tb, text="")
        self._pc_summary_label.pack(side='right')

        # inner notebook: Membership | Caliber Pool | Caps
        inner = ttk.Notebook(parent)
        inner.pack(fill='both', expand=True, padx=8, pady=6)

        tab_mem = ttk.Frame(inner)
        inner.add(tab_mem, text='  Pool Membership  ')
        self._pc_build_membership(tab_mem)

        tab_cal = ttk.Frame(inner)
        inner.add(tab_cal, text='  Caliber (NB Anchors)  ')
        self._pc_build_caliber(tab_cal)

        tab_caps = ttk.Frame(inner)
        inner.add(tab_caps, text='  Caps  ')
        self._pc_build_caps(tab_caps)

        self._pc_widgets_ready = True
        self._pc_refresh_all()

    # ---- section 1: membership (was the Excluded tab) ----
    def _pc_build_membership(self, parent):
        s = ttk.Frame(parent, padding=(0, 4))
        s.pack(fill='x')
        ttk.Label(s, text="Search:").pack(side='left')
        ttk.Entry(s, textvariable=self._pc_search_var).pack(
            side='left', fill='x', expand=True, padx=4)
        ttk.Button(s, text="Clear",
                   command=lambda: self._pc_search_var.set("")).pack(
            side='left')
        ttk.Button(s, text="Reset to default",
                   command=self._pc_reset_membership).pack(
            side='left', padx=4)

        body = ttk.Frame(parent)
        body.pack(fill='both', expand=True, pady=4)

        left = ttk.LabelFrame(body, text="In pool (eligible)", padding=4)
        left.pack(side='left', fill='both', expand=True, padx=(0, 4))
        self._pc_avail_lb = tk.Listbox(left, selectmode='extended',
                                       font=('Courier', 9))
        sb1 = ttk.Scrollbar(left, command=self._pc_avail_lb.yview)
        self._pc_avail_lb.config(yscrollcommand=sb1.set)
        sb1.pack(side='right', fill='y')
        self._pc_avail_lb.pack(side='left', fill='both', expand=True)

        mid = ttk.Frame(body)
        mid.pack(side='left', padx=4, fill='y')
        ttk.Button(mid, text="Exclude →",
                   command=self._pc_exclude_selected).pack(pady=8)
        ttk.Button(mid, text="← Include",
                   command=self._pc_include_selected).pack()

        right = ttk.LabelFrame(body, text="Excluded (stays vanilla)",
                               padding=4)
        right.pack(side='left', fill='both', expand=True, padx=(4, 0))
        self._pc_excl_lb = tk.Listbox(right, selectmode='extended',
                                      font=('Courier', 9))
        sb2 = ttk.Scrollbar(right, command=self._pc_excl_lb.yview)
        self._pc_excl_lb.config(yscrollcommand=sb2.set)
        sb2.pack(side='right', fill='y')
        self._pc_excl_lb.pack(side='left', fill='both', expand=True)

    def _pc_disp(self, cp):
        name = self._pc_prefix_names.get(cp, '')
        return f"{cp}  {name}".rstrip()

    def _pc_cp_from_disp(self, disp):
        return disp.split()[0] if disp else ''

    def _pc_refresh_membership(self):
        if not self._pc_widgets_ready:
            return
        search = (self._pc_search_var.get() or '').lower()
        self._pc_avail_lb.delete(0, 'end')
        self._pc_excl_lb.delete(0, 'end')
        for cp, name in self._pc_all_prefixes():
            disp = self._pc_disp(cp)
            if search and search not in disp.lower():
                continue
            (self._pc_excl_lb if cp in self.excluded
             else self._pc_avail_lb).insert('end', disp)
        self._pc_update_summary()

    def _pc_exclude_selected(self):
        for i in self._pc_avail_lb.curselection():
            self.excluded.add(self._pc_cp_from_disp(self._pc_avail_lb.get(i)))
        self._pc_refresh_membership()

    def _pc_include_selected(self):
        for i in self._pc_excl_lb.curselection():
            self.excluded.discard(
                self._pc_cp_from_disp(self._pc_excl_lb.get(i)))
        self._pc_refresh_membership()

    def _pc_reset_membership(self):
        self.excluded = set(self._pc_seed_excluded)
        self._pc_excluded = self.excluded
        self._pc_refresh_membership()

    # ---- section 2: caliber pool ----
    def _pc_build_caliber(self, parent):
        ttk.Label(
            parent, padding=(0, 6),
            text=("Prefixes eligible to anchor Night-Boss arena slots. "
                  "Move chrs IN to let them headline a Night fight (the "
                  "all-DLC lever), or OUT to keep them at field/grunt slots "
                  "only. Base caliber set is the engine default."),
            wraplength=820).pack(fill='x')

        body = ttk.Frame(parent)
        body.pack(fill='both', expand=True, pady=4)

        left = ttk.LabelFrame(body, text="NOT caliber (field/grunt)",
                              padding=4)
        left.pack(side='left', fill='both', expand=True, padx=(0, 4))
        self._pc_noncal_lb = tk.Listbox(left, selectmode='extended',
                                        font=('Courier', 9))
        sb1 = ttk.Scrollbar(left, command=self._pc_noncal_lb.yview)
        self._pc_noncal_lb.config(yscrollcommand=sb1.set)
        sb1.pack(side='right', fill='y')
        self._pc_noncal_lb.pack(side='left', fill='both', expand=True)

        mid = ttk.Frame(body)
        mid.pack(side='left', padx=4, fill='y')
        ttk.Button(mid, text="→ Make anchor",
                   command=self._pc_caliber_add).pack(pady=8)
        ttk.Button(mid, text="← Remove anchor",
                   command=self._pc_caliber_remove).pack()

        right = ttk.LabelFrame(body, text="Caliber (NB anchors)", padding=4)
        right.pack(side='left', fill='both', expand=True, padx=(4, 0))
        self._pc_cal_lb = tk.Listbox(right, selectmode='extended',
                                     font=('Courier', 9))
        sb2 = ttk.Scrollbar(right, command=self._pc_cal_lb.yview)
        self._pc_cal_lb.config(yscrollcommand=sb2.set)
        sb2.pack(side='right', fill='y')
        self._pc_cal_lb.pack(side='left', fill='both', expand=True)

    def _pc_effective_caliber(self):
        """Engine default ∪ extras − removals."""
        return (self._pc_default_caliber | self._pc_caliber_extras) \
            - self._pc_caliber_removals

    def _pc_refresh_caliber(self):
        if not self._pc_widgets_ready:
            return
        eff = self._pc_effective_caliber()
        self._pc_noncal_lb.delete(0, 'end')
        self._pc_cal_lb.delete(0, 'end')
        for cp, name in self._pc_all_prefixes():
            disp = self._pc_disp(cp)
            (self._pc_cal_lb if cp in eff
             else self._pc_noncal_lb).insert('end', disp)
        self._pc_update_summary()

    def _pc_caliber_add(self):
        for i in self._pc_noncal_lb.curselection():
            cp = self._pc_cp_from_disp(self._pc_noncal_lb.get(i))
            # adding: if it was a removal of a default, just un-remove;
            # else it's an extra
            if cp in self._pc_default_caliber:
                self._pc_caliber_removals.discard(cp)
            else:
                self._pc_caliber_extras.add(cp)
        self._pc_refresh_caliber()

    def _pc_caliber_remove(self):
        for i in self._pc_cal_lb.curselection():
            cp = self._pc_cp_from_disp(self._pc_cal_lb.get(i))
            if cp in self._pc_default_caliber:
                self._pc_caliber_removals.add(cp)
            else:
                self._pc_caliber_extras.discard(cp)
        self._pc_refresh_caliber()

    # ---- section 3: caps ----
    def _pc_build_caps(self, parent):
        ttk.Label(
            parent, padding=(0, 6),
            text=("Per-enemy placement ceilings. Blank = engine default "
                  "(shown in parens). Set an integer ≥ 1 to override; to "
                  "remove a chr entirely use Pool Membership, not a cap of "
                  "0."),
            wraplength=820).pack(fill='x')

        # scrollable table of capped prefixes (engine caps + any user adds)
        wrap = ttk.Frame(parent)
        wrap.pack(fill='both', expand=True, pady=4)
        canvas = tk.Canvas(wrap, highlightthickness=0,
                           bg=_c('bg'), bd=0)
        sb = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview)
        self._pc_caps_inner = ttk.Frame(canvas)
        self._pc_caps_inner.bind(
            '<Configure>',
            lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        _win = canvas.create_window((0, 0), window=self._pc_caps_inner,
                                    anchor='nw')
        # keep the inner frame's width pinned to the canvas so the dark
        # surface fills the whole area (no white void to the right) and the
        # rows don't float in an unstyled gap.
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfigure(_win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        self._pc_cap_vars = {}   # cp -> StringVar
        self._pc_build_cap_rows()

    def _pc_build_cap_rows(self):
        for w in self._pc_caps_inner.winfo_children():
            w.destroy()
        self._pc_cap_vars = {}
        hdr = ttk.Frame(self._pc_caps_inner)
        hdr.pack(fill='x', pady=(0, 2))
        ttk.Label(hdr, text="c-prefix", width=10,
                  font=('Courier', 9, 'bold')).pack(side='left')
        ttk.Label(hdr, text="cap", width=6,
                  font=('Courier', 9, 'bold')).pack(side='left')
        ttk.Label(hdr, text="default", width=10,
                  font=('Courier', 9, 'bold')).pack(side='left')
        ttk.Label(hdr, text="name", width=44,
                  font=('Courier', 9, 'bold')).pack(side='left')

        # show every engine-capped prefix, plus any user override not in it
        capped = sorted(set(self._pc_default_caps) |
                        set(self._pc_cap_overrides))
        for cp in capped:
            row = ttk.Frame(self._pc_caps_inner)
            row.pack(fill='x')
            default = self._pc_default_caps.get(cp)
            name = self._pc_prefix_names.get(cp, '')
            ttk.Label(row, text=cp, width=10,
                      font=('Courier', 9)).pack(side='left')
            # cap input + default come BEFORE the name so a long name can
            # never push the editable field off-screen.
            var = tk.StringVar(
                value=str(self._pc_cap_overrides.get(cp, '')))
            self._pc_cap_vars[cp] = var
            e = ttk.Entry(row, textvariable=var, width=5)
            e.pack(side='left', padx=(0, 2))
            var.trace_add('write',
                          lambda *_a, c=cp: self._pc_cap_changed(c))
            dflt = '–' if default is None else str(default)
            ttk.Label(row, text=dflt, width=10,
                      font=('Courier', 8)).pack(side='left')
            ttk.Label(row, text=name[:44], width=44, anchor='w',
                      font=('Courier', 9)).pack(side='left')

    def _pc_cap_changed(self, cp):
        raw = (self._pc_cap_vars[cp].get() or '').strip()
        if raw == '':
            self._pc_cap_overrides.pop(cp, None)
        else:
            try:
                v = int(raw)
            except ValueError:
                return  # ignore non-int while typing
            if v >= 1:
                self._pc_cap_overrides[cp] = v
            else:
                self._pc_cap_overrides.pop(cp, None)
        self._pc_update_summary()

    # ---- shared refresh / summary ----
    def _pc_refresh_all(self):
        self._pc_refresh_membership()
        self._pc_refresh_caliber()
        if hasattr(self, '_pc_build_cap_rows'):
            self._pc_build_cap_rows()
        self._pc_update_summary()

    def _pc_update_summary(self):
        if not getattr(self, '_pc_summary_label', None):
            return
        eff_cal = len(self._pc_effective_caliber())
        self._pc_summary_label.config(
            text=(f"excluded {len(self.excluded)}  •  "
                  f"caliber {eff_cal} "
                  f"(+{len(self._pc_caliber_extras)}/"
                  f"-{len(self._pc_caliber_removals)})  •  "
                  f"cap overrides {len(self._pc_cap_overrides)}"))


# standalone preview ----------------------------------------------------
if __name__ == '__main__':
    class _Preview(PoolsCapsPanelMixin):
        def __init__(self):
            self._pc_init_state()
            self.root = tk.Tk()
            self.root.title("Pools & Caps — standalone preview")
            self.root.geometry("900x600")
            self._build_pools_caps_tab(ttk.Frame(self.root))
            for child in self.root.winfo_children():
                child.pack(fill='both', expand=True)

    p = _Preview()
    print("engine config sample:", p.pools_caps_engine_config())
    p.root.mainloop()
