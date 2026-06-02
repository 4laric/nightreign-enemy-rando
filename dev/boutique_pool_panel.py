"""boutique_pool_panel.py — the "Boutique Pool" GUI tab.

v0.28.x: ships with the promotion-rate controls only. Subsequent work
will fold in the per-tier whitelist UI per dev/BOUTIQUE_RUN_SPEC.md
("boutique run" = hand-curated rosters per tier, like building a deck).

Self-contained mixin folded into RandoGUI. Owns four engine knobs:

  V3_FIELD_UPGRADE_MINIBOSS_PCT
  V3_FIELD_UPGRADE_FIELDBOSS_PCT
  V3_FIELD_UPGRADE_NIGHTBOSS_PCT
  V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT

These are the per-field-slot upgrade probabilities — see the comment
block at oops_v3.V3_FIELD_UPGRADE_MINIBOSS_PCT for engine semantics.
Currently tuned by direct module edit; this panel exposes them as
sliders with live probability readouts. Wired through
engine.runtime.apply_run_overrides as per-run kwargs, so the module
defaults are never mutated globally — each run sees its own values.

The host GUI calls:
  - self._boutique_init_state()              once, before _build_ui
  - self._build_boutique_pool_tab(parent)    to render the tab
  - self.boutique_pool_engine_config()       at run time -> dict of kwargs
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# Pull the host GUI's dark palette so the panel matches the rest of the
# app. Falls back to a self-contained dark palette for standalone preview.
try:
    import sys as _sys
    if _ROOT not in _sys.path:
        _sys.path.insert(0, _ROOT)
    from oops_rando_gui import THEME as _THEME
except Exception:  # noqa: BLE001
    _THEME = {
        'bg':       '#1e1e1e',
        'surface':  '#252525',
        'fg':       '#e0e0e0',
        'fg_muted': '#9a9a9a',
        'accent':   '#cd853f',
        'border':   '#3a3a3a',
    }


# Engine defaults — re-read at init to follow whatever the engine
# currently ships as defaults. Used for the "Reset" button.
def _engine_defaults():
    """Read live defaults from oops_v3. Falls back to hardcoded if
    import fails (e.g. standalone preview)."""
    try:
        import oops_v3 as o
        return {
            'miniboss':         float(o.V3_FIELD_UPGRADE_MINIBOSS_PCT),
            'fieldboss':        float(o.V3_FIELD_UPGRADE_FIELDBOSS_PCT),
            'nightboss':        float(o.V3_FIELD_UPGRADE_NIGHTBOSS_PCT),
            'fb_to_nb_promote': float(o.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT),
        }
    except Exception:  # noqa: BLE001
        return {
            'miniboss':         0.015,
            'fieldboss':        0.005,
            'nightboss':        0.002,
            'fb_to_nb_promote': 0.5,
        }


# Approximate field-slot count for the "expected upgrades/seed" readout.
# Hardcoded — slot count is stable across the roster lifetime. See
# oops_v3 comment "~3400 field slots".
_APPROX_FIELD_SLOTS = 3400


class BoutiquePoolPanelMixin:
    """Mixed into RandoGUI. Exposes promotion-rate controls."""

    _BP_AVAILABLE = True

    # ------------------------------------------------------------------
    # Lifecycle hooks (called by RandoGUI)
    # ------------------------------------------------------------------
    def _boutique_init_state(self):
        """Initialize tk.DoubleVars from saved settings (or engine
        defaults). Called once during RandoGUI.__init__."""
        defaults = _engine_defaults()
        saved = {}
        try:
            saved = self._load_settings().get('boutique_pool', {}) or {}
        except Exception:  # noqa: BLE001
            pass

        def _f(key, fallback):
            v = saved.get(key, fallback)
            try:
                v = float(v)
                if 0.0 <= v <= 1.0:
                    return v
            except (TypeError, ValueError):
                pass
            return fallback

        self._bp_miniboss_var = tk.DoubleVar(
            value=_f('miniboss', defaults['miniboss']))
        self._bp_fieldboss_var = tk.DoubleVar(
            value=_f('fieldboss', defaults['fieldboss']))
        self._bp_nightboss_var = tk.DoubleVar(
            value=_f('nightboss', defaults['nightboss']))
        self._bp_fb_to_nb_var = tk.DoubleVar(
            value=_f('fb_to_nb_promote', defaults['fb_to_nb_promote']))

        # Cache defaults so the Reset button has a target.
        self._bp_defaults = defaults

        # Persist on change. Wired here (not in _build) so even if the
        # tab never opens, programmatic changes still persist.
        for var in (self._bp_miniboss_var, self._bp_fieldboss_var,
                    self._bp_nightboss_var, self._bp_fb_to_nb_var):
            var.trace_add('write', lambda *_: self._bp_save_and_refresh())

    def boutique_pool_engine_config(self):
        """Return dict of kwargs threaded into cmd_shuffle_v3. Values
        are floats. None for any kwarg = engine default unchanged; we
        always emit floats here so the GUI's choice is explicit, but
        the engine handles None too (e.g. CLI callers that don't touch
        promotion rates)."""
        # Defensive: clamp into [0, 1] even if a user typed something
        # out-of-range in the Spinbox. The engine will also validate.
        def _clamp(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                return None
            return max(0.0, min(1.0, v))

        return {
            'field_upgrade_miniboss_pct':         _clamp(self._bp_miniboss_var.get()),
            'field_upgrade_fieldboss_pct':        _clamp(self._bp_fieldboss_var.get()),
            'field_upgrade_nightboss_pct':        _clamp(self._bp_nightboss_var.get()),
            'fieldboss_to_nightboss_promote_pct': _clamp(self._bp_fb_to_nb_var.get()),
        }

    # ------------------------------------------------------------------
    # Persistence + live-probability refresh
    # ------------------------------------------------------------------
    def _bp_save_and_refresh(self):
        """Persist current values + refresh the live readout. Called on
        every variable write."""
        try:
            self._save_settings(boutique_pool={
                'miniboss':         float(self._bp_miniboss_var.get()),
                'fieldboss':        float(self._bp_fieldboss_var.get()),
                'nightboss':        float(self._bp_nightboss_var.get()),
                'fb_to_nb_promote': float(self._bp_fb_to_nb_var.get()),
            })
        except Exception:  # noqa: BLE001
            pass
        # The readout labels are built lazily and may not exist before
        # the tab is rendered. _bp_refresh_readout handles the absence.
        self._bp_refresh_readout()

    def _bp_refresh_readout(self):
        """Recompute and display:
            P(grunt) = 1 - sum(three upgrade slices)
            P(mini)  = miniboss_pct
            P(field) = fieldboss_pct * (1 - fb_to_nb_promote_pct)
            P(night) = nightboss_pct + fieldboss_pct * fb_to_nb_promote_pct
        Plus per-tier expected /seed counts at _APPROX_FIELD_SLOTS slots.
        """
        if not hasattr(self, '_bp_readout_labels'):
            return  # tab not built yet
        try:
            mb = float(self._bp_miniboss_var.get())
            fb = float(self._bp_fieldboss_var.get())
            nb = float(self._bp_nightboss_var.get())
            pr = float(self._bp_fb_to_nb_var.get())
        except (TypeError, ValueError, tk.TclError):
            return

        triple_sum = mb + fb + nb
        p_grunt = max(0.0, 1.0 - triple_sum)
        p_mini  = mb
        p_field = fb * (1.0 - pr)
        p_night = nb + fb * pr

        S = _APPROX_FIELD_SLOTS
        def _fmt(p, label):
            return f'P({label}) = {p*100:5.2f}%   →   ~{p*S:5.1f} slots/seed'

        self._bp_readout_labels['grunt'].configure(text=_fmt(p_grunt, 'grunt'))
        self._bp_readout_labels['mini'].configure(text=_fmt(p_mini,  'miniboss'))
        self._bp_readout_labels['field'].configure(text=_fmt(p_field, 'field_boss'))
        self._bp_readout_labels['night'].configure(text=_fmt(p_night, 'night_boss'))

        # Sum-violation warning
        warn = self._bp_readout_labels['warn']
        if triple_sum > 1.0 + 1e-9:
            warn.configure(
                text=(f'⚠ miniboss + field_boss + night_boss = '
                      f'{triple_sum*100:.2f}% exceeds 100% — engine will reject this'),
                foreground='#e07a5f')
        else:
            warn.configure(text='', foreground=_THEME.get('fg', '#e0e0e0'))

    # ------------------------------------------------------------------
    # Tab builder
    # ------------------------------------------------------------------
    def _build_boutique_pool_tab(self, parent):
        """Render the tab into `parent` (a ttk.Frame inside the host
        notebook)."""
        wrap = ttk.Frame(parent, padding=12)
        wrap.pack(fill='both', expand=True)

        # Header + blurb
        ttk.Label(
            wrap, text='Boutique Pool',
            font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 4))
        ttk.Label(
            wrap,
            text=('Promotion rates — tune how often the ~3400 non-catalogued '
                  'field slots roll up from grunt baseline into higher-tier '
                  'encounters. Engine defaults are deliberately low so most '
                  'open-world slots stay populated by their normal grunt mobs.'),
            wraplength=720, justify='left',
            foreground=_THEME.get('fg_muted', '#9a9a9a')).pack(
                anchor='w', pady=(0, 12))

        # Spinbox-per-rate grid
        grid = ttk.Frame(wrap)
        grid.pack(fill='x', anchor='w', pady=(0, 12))

        ROWS = [
            ('Miniboss promotion rate',
             self._bp_miniboss_var,
             'Probability that a field slot upgrades to a miniboss roll. '
             'Default 1.5% (≈50/seed).'),
            ('Field Boss promotion rate',
             self._bp_fieldboss_var,
             'Probability that a field slot upgrades to a field_boss roll. '
             'Default 0.5% (≈17/seed). v0.28.x split moved overworld bosses '
             '(Tree Sentinel, Borealis, Furnace Golem, etc.) into this tier.'),
            ('Night Boss promotion rate',
             self._bp_nightboss_var,
             'Probability that a field slot upgrades to a night_boss roll. '
             'Default 0.2% (≈7/seed, on top of the 23 dedicated NB-arena '
             'slots).'),
            ('Field → Night Boss upgrade',
             self._bp_fb_to_nb_var,
             'Conditional probability that a rolled field_boss promotes '
             'further to night_boss. Default 50% — centerpoint where '
             'field-tier encounters split roughly evenly between '
             'field-flavor and night-boss-flavor. 0.0 = full independence; '
             '1.0 = field_boss tier collapses into night_boss.'),
        ]
        for r, (label, var, blurb) in enumerate(ROWS):
            ttk.Label(grid, text=label).grid(
                row=r*2, column=0, sticky='w', padx=(0, 12), pady=(6, 0))
            # Spinbox in % units (×100). Step in 0.1% increments.
            wrap_var = _PctProxyVar(var)
            sb = ttk.Spinbox(
                grid, from_=0.0, to=100.0, increment=0.1,
                textvariable=wrap_var, width=8, format='%.2f')
            sb.grid(row=r*2, column=1, sticky='w', pady=(6, 0))
            ttk.Label(grid, text='%',
                      foreground=_THEME.get('fg_muted', '#9a9a9a')
                      ).grid(row=r*2, column=2, sticky='w', padx=(2, 0),
                             pady=(6, 0))
            ttk.Label(grid, text=blurb, wraplength=560, justify='left',
                      foreground=_THEME.get('fg_muted', '#9a9a9a')).grid(
                row=r*2+1, column=0, columnspan=4, sticky='w',
                padx=(0, 0), pady=(0, 6))

        # ── Effective probabilities readout ──
        sep = ttk.Separator(wrap, orient='horizontal')
        sep.pack(fill='x', pady=(8, 8))

        ttk.Label(
            wrap, text='Effective probabilities per field slot',
            font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(0, 4))

        readout_frame = ttk.Frame(wrap)
        readout_frame.pack(anchor='w', pady=(0, 8))
        self._bp_readout_labels = {}
        for r, key in enumerate(('grunt', 'mini', 'field', 'night')):
            lbl = ttk.Label(readout_frame, text='', font=('Consolas', 10))
            lbl.grid(row=r, column=0, sticky='w', pady=1)
            self._bp_readout_labels[key] = lbl

        warn_lbl = ttk.Label(wrap, text='', font=('Segoe UI', 10, 'bold'))
        warn_lbl.pack(anchor='w', pady=(0, 8))
        self._bp_readout_labels['warn'] = warn_lbl

        # Reset button
        btn_row = ttk.Frame(wrap)
        btn_row.pack(anchor='w', pady=(4, 0))
        ttk.Button(btn_row, text='Reset to engine defaults',
                   command=self._bp_reset).pack(side='left')

        # Initial readout populate
        self._bp_refresh_readout()

    def _bp_reset(self):
        d = self._bp_defaults
        # Use set() to trigger trace callbacks — saves and refreshes.
        self._bp_miniboss_var.set(d['miniboss'])
        self._bp_fieldboss_var.set(d['fieldboss'])
        self._bp_nightboss_var.set(d['nightboss'])
        self._bp_fb_to_nb_var.set(d['fb_to_nb_promote'])


class _PctProxyVar:
    """Adapter exposing a [0, 100] percentage view over a backing
    [0.0, 1.0] DoubleVar. The Spinbox shows percentages (user types
    "1.5" for 1.5%, not "0.015"); the underlying DoubleVar — which
    the engine config reads — stays in [0.0, 1.0] semantics.

    Implements the small subset of tk.Variable that ttk.Spinbox
    actually calls: get(), set(), trace_add().
    """
    def __init__(self, backing: tk.DoubleVar):
        self._var = backing

    def get(self) -> float:
        return self._var.get() * 100.0

    def set(self, value):
        try:
            pct = float(value)
        except (TypeError, ValueError):
            return
        self._var.set(pct / 100.0)

    def trace_add(self, mode, callback):
        return self._var.trace_add(mode, callback)

    # ttk.Spinbox uses textvariable= which needs a name. tk.Variable
    # subclasses get a name automatically; we proxy that too so Spinbox
    # treats us like a real Variable.
    def __str__(self):
        return str(self._var)


# Standalone preview — `python dev/boutique_pool_panel.py`
if __name__ == '__main__':
    root = tk.Tk()
    root.title('Boutique Pool — preview')
    root.geometry('760x540')
    root.configure(bg=_THEME.get('bg', '#1e1e1e'))

    class _Stub(BoutiquePoolPanelMixin):
        def _load_settings(self): return {}
        def _save_settings(self, **kw): pass

    stub = _Stub()
    stub._boutique_init_state()
    frame = ttk.Frame(root)
    frame.pack(fill='both', expand=True)
    stub._build_boutique_pool_tab(frame)
    root.mainloop()
