#!/usr/bin/env python3
"""
Oops! All Random — GUI for the Nightreign rando tool.

A tkinter wrapper around oops_v3.py that exposes the rando's main configuration
in a clickable interface. No external GUI library dependencies — uses the
tkinter that ships with Python.

Files needed alongside this script:
    oops_v3.py
    oops_all_anyone.py
    nr_enemy_roster.json
    nr_enemy_tags.json

Run with:
    python oops_rando_gui.py

Workflow:
    1. Point "Vanilla MSBs" at the folder of decompressed .msb files
    2. Choose where to put the shuffled output
    3. Pick a seed (or roll random)
    4. Optional: tweak excluded enemies, mode, hub maps
    5. Click Randomize
    6. Take the output folder + sidecar XMLs back through Yabber to repack
"""
import os, sys, json, random, threading, queue, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


# === Theme: dark + bonfire-amber accent ====================================
THEME = {
    'bg':           '#1a1a1d',  # main window background
    'surface':      '#23232a',  # raised panels (frames, labelframes)
    'surface_alt':  '#2c2c34',  # input fields, listboxes
    'border':       '#3a3a44',  # subtle dividers
    'text':         '#e8e8ea',  # primary text
    'text_dim':     '#9a9aa0',  # secondary text (labels, hints)
    'text_faint':   '#6a6a72',  # tertiary (status, hints)
    'accent':       '#d4a45e',  # bonfire amber — primary actions, highlights
    'accent_hi':    '#e8b87a',  # accent hover/active
    'accent_dim':   '#8a6a3e',  # accent disabled
    'success':      '#7ec07e',  # log success lines
    'warn':         '#e8b87a',  # log warning lines
    'error':        '#d47272',  # log errors
    'info':         '#7eb0d4',  # log informational lines
}


def _pick_mono_font():
    """First available monospace font, with sensible fallbacks."""
    candidates = ['Cascadia Code', 'JetBrains Mono', 'Consolas',
                  'SF Mono', 'Menlo', 'DejaVu Sans Mono', 'Courier New', 'Courier']
    try:
        from tkinter import font as tkfont
        available = set(tkfont.families())
        for c in candidates:
            if c in available: return c
    except Exception: pass
    return 'Courier'


def _pick_ui_font():
    """First available proportional UI font."""
    candidates = ['Segoe UI', 'SF Pro Text', 'Inter', 'Helvetica Neue',
                  'DejaVu Sans', 'Arial']
    try:
        from tkinter import font as tkfont
        available = set(tkfont.families())
        for c in candidates:
            if c in available: return c
    except Exception: pass
    return 'TkDefaultFont'


# --- Ensure backend is importable ----------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Defer the imports until we actually need them — let the GUI start even if
# the backend files have an issue, so we can show a nice error
def _import_backend():
    import oops_v3
    return oops_v3


# --- Default configuration (mirrors oops_v3 defaults) --------------------
# v0.20.5: DEFAULT_EXCLUDED mirrors only V3_EXCLUDE_PREFIXES (the "hard
# block" set — never used as source, never used as target). Earlier versions
# unioned in V3_EXCLUDE_SOURCE_PREFIXES and V3_EXCLUDE_TARGET_PREFIXES too,
# which broke the per-direction semantic: source-only excludes (Maris
# Tendril/Jellyfish, Oracle Envoys) ended up in the GUI's "excluded"
# list, and the run-start writeback `oops_v3.V3_EXCLUDE_PREFIXES =
# config['excluded']` then bloated the hard-block set with them, making
# them never appear as TARGETS either. The fix: GUI's list contains only
# V3_EXCLUDE_PREFIXES; per-direction excludes stay managed in oops_v3.py.
try:
    import oops_v3 as _oops_v3_for_defaults
    DEFAULT_EXCLUDED = set(_oops_v3_for_defaults.V3_EXCLUDE_PREFIXES)
    DEFAULT_HUB_MAPS = set(_oops_v3_for_defaults.V3_HUB_MAPS)
    # v0.23.71: pull the diagnostic baseline c-prefix from the engine
    # (was previously hardcoded in the GUI as 'c4373' at line 2483).
    # Engine is the source of truth for content/balance constants.
    DEFAULT_NON_FRAGILE_BASELINE_CP = getattr(
        _oops_v3_for_defaults, 'V3_DEFAULT_NON_FRAGILE_BASELINE_CP', 'c4373')
    # v0.23.71: same pattern — terrain validation test targets used to
    # be hardcoded inside the GUI's _run_shuffle (lines 2457/2463).
    DEFAULT_VALIDATION_TERRAIN_TEST_TARGETS = getattr(
        _oops_v3_for_defaults, 'V3_VALIDATION_TERRAIN_TEST_TARGETS',
        {'on_mesh': 'c4090', 'off_mesh': 'c4180'})
    # v0.23.71: data-file resolver. The engine's _data_path() checks
    # data/<file> first, falls back to <file> at project root. Importing
    # it here means the GUI doesn't duplicate the resolution rules and
    # both paths automatically agree.
    _data_path = _oops_v3_for_defaults._data_path
except Exception:
    # v0.23.71: import failure should fail loudly rather than silently
    # use stale duplicates of engine state. The previous fallback list
    # mirrored V3_EXCLUDE_PREFIXES, but it was a maintenance liability —
    # if the engine added a new exclusion (e.g. a Nightlord variant or
    # new placeholder prefix), the GUI fallback wouldn't track and a
    # malformed-data run could ship excluded chrs as targets.
    #
    # Empty set + minimum hub list lets the GUI start so the user can
    # see the import error in the log; downstream the engine will
    # complain loudly when its data files are missing, which is the
    # error the user actually needs to see.
    DEFAULT_EXCLUDED = set()
    DEFAULT_HUB_MAPS = set()
    DEFAULT_NON_FRAGILE_BASELINE_CP = 'c4373'
    DEFAULT_VALIDATION_TERRAIN_TEST_TARGETS = {
        'on_mesh': 'c4090', 'off_mesh': 'c4180',
    }
    # Inline fallback resolver — same behavior as the engine's helper.
    def _data_path(filename):
        here = os.path.dirname(os.path.abspath(__file__))
        new_loc = os.path.join(here, 'data', filename)
        if os.path.exists(new_loc):
            return new_loc
        return os.path.join(here, filename)


# --- The GUI itself -------------------------------------------------------
class AutocompleteCombobox(ttk.Combobox):
    """v0.23.05: ttk.Combobox subclass with live-lookup autocomplete.

    Filters its dropdown values on each KeyRelease — only items whose
    lowercased text contains the lowercased query remain. Up/Down arrows
    navigate the filtered list, Enter accepts. Empty query restores the
    full list.

    Use:
        cb = AutocompleteCombobox(parent, textvariable=var, width=50)
        cb.set_completion_list(['c4500  Flying Dragon', 'c4910  Magma Wyrm', ...])
        cb.pack(...)

    Implementation notes:
      - Filtering happens by mutating the `values` config; the dropdown,
        if open at the time, picks up the change on next render.
      - The dropdown is opened explicitly on the first character typed
        (after an empty state) so the user gets visual feedback that
        autocomplete is engaged. Subsequent keystrokes don't re-open
        an already-open dropdown.
      - Navigation keys (Up/Down/Return/Tab/Escape/Left/Right) skip the
        filter pass — they're for selecting from current dropdown.
    """
    _NAV_KEYS = {'Up', 'Down', 'Return', 'Tab', 'Escape', 'Left', 'Right'}

    def set_completion_list(self, items):
        self._all_items = list(items)
        self['values'] = self._all_items
        self.bind('<KeyRelease>', self._on_keyrelease)

    def _on_keyrelease(self, event):
        if event.keysym in self._NAV_KEYS:
            return
        text = self.get().lower()
        if not text:
            self['values'] = self._all_items
            return
        filtered = [it for it in self._all_items if text in it.lower()]
        self['values'] = filtered
        # v0.23.44: Open the dropdown so the user sees filtered matches,
        # but DO NOT steal keyboard focus from the entry field. The naive
        # ttk::combobox::Post call moves focus to the listbox, breaking
        # subsequent typing — the user has to click back into the entry
        # before the next character registers. Workaround: post the
        # dropdown, then explicitly restore focus to the entry and
        # re-anchor the insertion cursor at end-of-text. Use after_idle
        # so the focus restoration happens after Tk's own focus shuffle
        # from the post completes.
        try:
            self.tk.eval(f'ttk::combobox::Post {self}')
            cursor_pos = self.index('insert')
            def _restore_focus():
                try:
                    self.focus_set()
                    self.icursor(cursor_pos)
                except tk.TclError:
                    pass
            self.after_idle(_restore_focus)
        except tk.TclError:
            pass


# ----------------------------------------------------------------------
# v0.23.23: Tooltip + info-icon helpers.
#
# Originated from the user note "there's some text in the GUI that
# definitely would be better off in an 'i' or a hover-over tooltip".
# A few of the dim-label descriptions had grown into 5+ line explainers
# that visually dominated the surrounding controls. They're useful when
# the user actually wants to read them, but unhelpful when they're just
# trying to flip a checkbox. Tooltip-on-hover-of-info-icon is the right
# affordance: discoverable for new users (the small "(i)" glyph), out
# of the way for experienced ones.
#
# Tooltip is the underlying primitive — bind any widget to show a
# borderless toplevel near the cursor on Enter, hide on Leave. It uses
# Tk's overrideredirect+wm_geometry pattern (no native tooltip API in
# Tk 8.x). InfoIcon wraps Tooltip in a small clickable Label widget
# that pack()s into a parent container next to the control it
# annotates.
# ----------------------------------------------------------------------

class Tooltip:
    """Hover-tooltip attached to any Tk widget. Borderless toplevel
    appears near the cursor after a short delay; disappears on Leave."""

    DELAY_MS = 350         # delay before tooltip appears on hover-in
    WRAP_PIXELS = 360      # word wrap inside the tooltip body

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._tip = None
        self._after_id = None
        widget.bind('<Enter>', self._on_enter, add='+')
        widget.bind('<Leave>', self._on_leave, add='+')
        widget.bind('<ButtonPress>', self._on_leave, add='+')

    def _on_enter(self, _event=None):
        self._cancel_pending()
        self._after_id = self.widget.after(self.DELAY_MS, self._show)

    def _on_leave(self, _event=None):
        self._cancel_pending()
        self._hide()

    def _cancel_pending(self):
        if self._after_id is not None:
            try: self.widget.after_cancel(self._after_id)
            except tk.TclError: pass
            self._after_id = None

    def _show(self):
        if self._tip is not None: return
        # Position near the widget, slightly below + right of its bbox
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        self._tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            # On macOS this stops the tooltip from stealing focus
            tw.tk.call("::tk::unsupported::MacWindowStyle", "style",
                       tw._w, "help", "noActivates")
        except tk.TclError:
            pass
        tw.wm_geometry(f'+{x}+{y}')
        # Use the dim theme so it visually reads as a tooltip
        bg = THEME.get('surface_alt', '#2a2a2a')
        fg = THEME.get('text', '#e0e0e0')
        border = THEME.get('border', '#444444')
        frame = tk.Frame(tw, background=border, borderwidth=0)
        frame.pack()
        tk.Label(frame, text=self.text, background=bg, foreground=fg,
                 justify='left', wraplength=self.WRAP_PIXELS,
                 padx=8, pady=6, font=('Segoe UI', 9)).pack(padx=1, pady=1)

    def _hide(self):
        if self._tip is not None:
            try: self._tip.destroy()
            except tk.TclError: pass
            self._tip = None


def make_info_icon(parent, tooltip_text, **pack_kwargs):
    """Create a small "(i)" label whose hover-tooltip is `tooltip_text`,
    pack it into `parent`, and return it. Pass pack-options as kwargs
    (defaults: side='left', padx=(4, 0))."""
    pack_kwargs.setdefault('side', 'left')
    pack_kwargs.setdefault('padx', (4, 0))
    icon = ttk.Label(parent, text='ⓘ', style='Dim.TLabel',
                     cursor='question_arrow')
    icon.pack(**pack_kwargs)
    Tooltip(icon, tooltip_text)
    return icon


# v0.26.x: status indicators for live path validation + setup-status panel.
# A StatusIndicator is a tiny Label showing one of four glyphs (✓/✗/⚠/·)
# with a state-driven color and a hover-tooltip that explains the detail.
# Designed as a one-liner alongside a path Entry or in a multi-row setup-
# status checklist. Use .set(state, detail) to update.
class StatusIndicator:
    """Reusable ✓/✗/⚠/· status icon with hover tooltip.

    States (passed to .set()):
      'ok'      ✓ green  — check passed
      'warn'    ⚠ amber  — non-fatal issue (e.g. dir exists but is empty)
      'error'   ✗ red    — check failed
      'unknown' ·         — not yet evaluated (e.g. empty path field)

    The widget is a plain ttk.Label with foreground recolored by state.
    Hover tooltip carries the detail message; clicking does nothing —
    indicators are passive status only. To trigger an action, place a
    button next to the indicator (e.g. a "Re-detect" button).
    """

    _GLYPHS = {
        'ok':      '✓',
        'warn':    '⚠',
        'error':   '✗',
        'unknown': '·',
    }
    _COLORS = {
        # Tuned to the existing dark theme (set per-widget rather than
        # via ttk styles since each indicator has its own color state).
        'ok':      '#4caf50',  # green
        'warn':    '#ffb74d',  # amber
        'error':   '#ef5350',  # red
        'unknown': '#888888',  # dim
    }

    def __init__(self, parent, initial_state='unknown',
                 initial_detail='Not yet checked'):
        self.label = tk.Label(parent, text=self._GLYPHS[initial_state],
                              fg=self._COLORS[initial_state],
                              bg=THEME.get('bg', '#1e1e1e'),
                              font=('Segoe UI', 11, 'bold'),
                              cursor='question_arrow', width=2)
        # Wrap the existing Tooltip helper. We hold a reference so we
        # can update text on subsequent .set() calls.
        self._tooltip = Tooltip(self.label, initial_detail)
        self.state = initial_state
        self.detail = initial_detail

    def set(self, state, detail):
        """Update glyph + color + tooltip text. Idempotent: setting
        the same state+detail is a no-op."""
        if state == self.state and detail == self.detail:
            return
        if state not in self._GLYPHS:
            raise ValueError(f'Unknown status state {state!r}; expected '
                             f'one of {sorted(self._GLYPHS)}')
        self.state = state
        self.detail = detail
        self.label.configure(text=self._GLYPHS[state],
                              fg=self._COLORS[state])
        self._tooltip.text = detail

    def pack(self, **kwargs):
        """Pass-through to label.pack() so the indicator behaves like
        a normal pack-able widget at call sites."""
        self.label.pack(**kwargs)
        return self

    def grid(self, **kwargs):
        self.label.grid(**kwargs)
        return self


# v0.26.x: Tier 2 UX #8 — collapsible section for hiding advanced
# / diagnostic controls behind a click. The Heritage tab uses one for
# its engine-validation toggles (disable_resilient_filter,
# diagnostic batch) so first-time users don't see several unfamiliar
# diagnostic checkboxes on top of the normal options.
class CollapsibleSection:
    """A clickable header with a toggleable body. Click the header
    (arrow + label) to expand/collapse the body Frame. Caller adds
    children to .body — same as packing into any Frame.

    Default state is collapsed (expanded=False) since the primary use
    case is hiding diagnostic toggles. Pass expanded=True for sections
    that should default to visible.

    Pack the section via .pack(**kwargs) just like a normal widget.
    """

    GLYPH_EXPANDED = '▼'
    GLYPH_COLLAPSED = '▶'

    def __init__(self, parent, label, expanded=False, body_padding=(20, 4)):
        self.label_text = label
        self.expanded = expanded
        self.body_padding = body_padding

        self.frame = ttk.Frame(parent)

        header = ttk.Frame(self.frame)
        header.pack(fill='x')
        self._arrow = ttk.Label(
            header,
            text=self.GLYPH_EXPANDED if expanded else self.GLYPH_COLLAPSED,
            cursor='hand2',
            style='Dim.TLabel')
        self._arrow.pack(side='left', padx=(0, 4))
        self._title = ttk.Label(
            header, text=label, cursor='hand2',
            font=(_pick_ui_font(), 10, 'bold'))
        self._title.pack(side='left')
        # Both arrow + title are clickable for easier targeting
        self._arrow.bind('<Button-1>', self._toggle)
        self._title.bind('<Button-1>', self._toggle)

        # Body frame — caller adds children via .body
        self.body = ttk.Frame(self.frame)
        if expanded:
            self.body.pack(fill='x',
                            padx=(body_padding[0], 0),
                            pady=(body_padding[1], 0))

    def _toggle(self, *_args):
        if self.expanded:
            self.body.pack_forget()
            self._arrow.configure(text=self.GLYPH_COLLAPSED)
        else:
            self.body.pack(fill='x',
                            padx=(self.body_padding[0], 0),
                            pady=(self.body_padding[1], 0))
            self._arrow.configure(text=self.GLYPH_EXPANDED)
        self.expanded = not self.expanded

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)
        return self

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)
        return self


def validate_path_kind(path, kind):
    """Return (state, detail) for a path that should match a particular
    kind. Pure function — no Tk dependency, so it's unit-testable.

    Recognised kinds:
      'nr_install'      <install>/Game/ — has map/mapstudio with .msb*
      'er_install'      <install>/Game/ — has chr/ with .chrbnd files
      'me3_profile'     directory we'll write outputs into; doesn't need
                        to exist yet (will be created), but parent must
      'mapstudio_dir'   contains .msb or .msb.dcx files
      'event_dir'       contains .emevd or .emevd.dcx files
      'chr_dir'         contains .chrbnd or .chrbnd.dcx files
      'general_dir'     dir exists, no content-shape check

    Returns ('ok'|'warn'|'error'|'unknown', detail_string).
    """
    import os, glob
    if not path or not path.strip():
        return ('unknown', 'Path not set')
    path = path.strip()

    # Common: does the path itself exist?
    if not os.path.isdir(path):
        if kind == 'me3_profile':
            # me3 profile output dir gets auto-created on Run; check parent
            parent = os.path.dirname(path.rstrip(os.sep)) or path
            if os.path.isdir(parent):
                return ('warn', f"Doesn't exist yet (parent OK; will be "
                                f"created on Run): {path}")
            return ('error', f"Parent directory missing: {parent}")
        if kind == 'me3_launcher_exe':
            # File kind, not a directory — the early isdir gate doesn't
            # apply. Fall through to its own branch below, which treats
            # a missing file as 'warn' (the binary is auto-discovered).
            pass
        else:
            return ('error', f"Directory does not exist: {path}")

    if kind == 'nr_install':
        # Conventional UXM layout: <install>/Game/map/mapstudio/m*.msb.dcx
        candidates = [
            os.path.join(path, 'map', 'mapstudio'),
            os.path.join(path, 'Game', 'map', 'mapstudio'),
        ]
        for d in candidates:
            if os.path.isdir(d):
                msbs = glob.glob(os.path.join(d, 'm*.msb*'))
                if msbs:
                    return ('ok', f"NR install OK ({len(msbs)} MSBs at "
                                  f"{d.replace(path, '<install>')})")
                return ('warn', f"map/mapstudio exists but has no .msb "
                                f"files — looks unpopulated. Did UXM "
                                f"finish unpacking?")
        return ('error', "No map/mapstudio subdirectory — NR isn't "
                         "UXM-unpacked yet, or this isn't an NR install.")

    if kind == 'er_install':
        candidates = [
            os.path.join(path, 'chr'),
            os.path.join(path, 'Game', 'chr'),
        ]
        for d in candidates:
            if os.path.isdir(d):
                chrs = glob.glob(os.path.join(d, '*.chrbnd*'))
                if chrs:
                    return ('ok', f"ER install OK ({len(chrs)} chr files "
                                  f"available for heritage imports)")
                return ('warn', f"chr/ exists but is empty — UXM unpack "
                                f"may not be complete")
        return ('error', "No chr/ subdirectory — ER isn't UXM-unpacked, "
                         "or this isn't an ER install.")

    if kind == 'me3_profile':
        # Profile dir exists. No deeper check — me3 profile shape varies.
        return ('ok', f"OK: {path}")

    if kind == 'mapstudio_dir':
        msbs = glob.glob(os.path.join(path, 'm*.msb*'))
        if msbs:
            return ('ok', f"{len(msbs)} MSB files")
        return ('warn', "No .msb / .msb.dcx files found")

    if kind == 'event_dir':
        evts = glob.glob(os.path.join(path, '*.emevd*'))
        if evts:
            return ('ok', f"{len(evts)} EMEVD files")
        return ('warn', "No .emevd / .emevd.dcx files found")

    if kind == 'chr_dir':
        chrs = glob.glob(os.path.join(path, '*.chrbnd*'))
        if chrs:
            return ('ok', f"{len(chrs)} chr files")
        return ('warn', "No .chrbnd / .chrbnd.dcx files found")

    if kind == 'general_dir':
        return ('ok', f"Directory exists: {path}")

    if kind == 'me3_launcher_exe':
        # File (not dir) kind. The me3 binary is auto-discovered at
        # launch time (find_me3_binary scans the standard install
        # locations) even when this field is blank or wrong, so this
        # row never reports 'error' — the worst case is 'warn'. The
        # field is purely an override for non-standard installs.
        if not os.path.isfile(path):
            return ('warn', f"File not found: {path}. me3 is still "
                            f"auto-discovered at launch — only set this "
                            f"if it's installed somewhere non-standard.")
        basename = os.path.basename(path).lower()
        # Recognised binary names. The me3 project ships as `me3` /
        # `me3.exe`; the older Mod Engine 2 ships as
        # `modengine2_launcher.exe`. Either is accepted — both invoke
        # the same way for our purposes.
        if basename in ('me3', 'me3.exe', 'modengine2_launcher.exe'):
            return ('ok', f"me3 launcher: {basename}")
        return ('warn',
                f"File exists but doesn't look like the me3 launcher "
                f"(expected me3 / me3.exe / modengine2_launcher.exe; "
                f"got {basename}). Launch may still work — Run to test.")

    return ('unknown', f"Unknown path kind {kind!r}")


# ---------------------------------------------------------------------
# v0.26.x: Tier 1 UX #2 — first-launch setup wizard.
# ---------------------------------------------------------------------
# Triggered when no saved root-paths config exists (zero-state user)
# or when the user runs `python3 oops_rando_gui.py --setup`. Sequences
# the same 6 environment checks the Setup Status panel shows, but as
# one-decision-at-a-time guided screens instead of a checklist.
#
# Module-level helpers (testable without Tk):


def _root_paths_config_path():
    """Where the saved root-paths JSON lives. Matches the RandoGUI
    instance method; broken out so the wizard + the static main()
    code can find it without instantiating the full GUI."""
    return os.path.join(HERE, '.4laric_paths.json')


def _load_saved_paths():
    """Load saved root-paths JSON, returning {} if missing or invalid."""
    try:
        with open(_root_paths_config_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_paths_to_disk(paths):
    """Persist root-paths dict before the main GUI even starts.
    Lets the wizard's results flow into RandoGUI.__init__'s
    _load_root_paths call naturally."""
    try:
        with open(_root_paths_config_path(), 'w', encoding='utf-8') as f:
            json.dump(paths, f, indent=2)
        return True
    except OSError:
        return False


def should_run_wizard(saved_config):
    """Decide whether to run the first-launch wizard.

    True iff all three root paths are empty/missing in the saved
    config — meaning this is a fresh install or a config-wipe. If
    *any* of the three is already set, we assume the user has been
    here before and don't intercept startup with a modal. The
    `--setup` CLI flag forces the wizard regardless.

    Pure function — no filesystem access, no Tk dependency. The
    caller decides where saved_config comes from.
    """
    if not isinstance(saved_config, dict):
        return True
    for key in ('game_install', 'er_install', 'me3_package'):
        if saved_config.get(key, '').strip():
            return False
    return True


def wizard_summary_lines(config):
    """Return a list of (indicator_state, text) tuples summarising the
    user's configured paths. Used by the Done screen to show
    'here's what you have' before the wizard closes. Pure function."""
    lines = []
    for key, label in (
            ('game_install', 'Nightreign install'),
            ('er_install',   'Elden Ring install'),
            ('me3_package',  'ME3 output')):
        val = (config.get(key) or '').strip()
        if not val:
            if key == 'er_install':
                lines.append(('unknown',
                              f'{label}: (skipped — no heritage chrs)'))
            else:
                lines.append(('warn', f'{label}: not set'))
            continue
        kind = {'game_install': 'nr_install',
                'er_install':   'er_install',
                'me3_package':  'me3_profile'}[key]
        state, _detail = validate_path_kind(val, kind)
        lines.append((state, f'{label}: {val}'))
    return lines


class FirstLaunchWizard:
    """4-screen modal wizard for first-launch configuration.

    Builds a Toplevel modal that walks the user through the same
    environment checks the Setup Status panel shows — but one decision
    at a time, with Back/Next/Skip nav, instead of a full checklist
    they have to read top-down.

    Usage:
        wiz = FirstLaunchWizard(root, initial_config=saved_paths)
        root.wait_window(wiz.top)
        if wiz.completed or wiz.config != initial_config:
            _save_paths_to_disk(wiz.config)
        # ...continue with normal RandoGUI startup; it reads the
        # saved paths via _load_root_paths.

    Public attributes after wait_window returns:
        config     dict of configured root paths (game_install, er_install,
                   me3_package). Reflects whatever the user entered, even
                   if they closed the wizard mid-flow.
        completed  True iff user reached the Done screen and clicked
                   'All set.' False if they closed via the X or Skip link.
    """

    SCREEN_NAMES = ['welcome', 'output', 'oodle', 'done']

    def __init__(self, parent, initial_config=None):
        self.parent = parent
        self.config = dict(initial_config or {})
        self.completed = False
        self.current = 0
        # Indicators built lazily per-screen so they're available for
        # _validate_current_screen to consult.
        self._screen_indicators = {}

        self.top = tk.Toplevel(parent)
        self.top.title("4laric's Nightreign Rando — Setup")
        self.top.geometry('700x460')
        # v0.26.x: don't bind transient(parent) when parent is/becomes
        # withdrawn — on Windows + some Linux WMs the wizard Toplevel
        # then never maps to the display, producing a silent hang (the
        # wait_window blocks forever because the user can't see/close
        # the invisible wizard). grab_set alone is sufficient for modal
        # behavior; transient() is just for "child of parent" window-
        # manager semantics (z-order, taskbar grouping) which we don't
        # need when parent is hidden anyway.
        try:
            parent_mapped = bool(parent.winfo_viewable())
        except tk.TclError:
            parent_mapped = False
        if parent_mapped:
            self.top.transient(parent)
        # Modal: block interaction with the main window until closed
        self.top.grab_set()
        self.top.protocol('WM_DELETE_WINDOW', self._on_close)
        # Theme-friendly background (parent might not be visible yet)
        try:
            self.top.configure(background=THEME['bg'])
        except Exception:
            pass

        # Header bar — shows current screen index + total
        self._header = ttk.Frame(self.top)
        self._header.pack(fill='x', padx=20, pady=(16, 0))
        self._step_label = ttk.Label(
            self._header, text='', style='Dim.TLabel',
            font=(_pick_ui_font(), 10))
        self._step_label.pack(side='left')

        # Body — gets rebuilt per screen
        self.body = ttk.Frame(self.top)
        self.body.pack(fill='both', expand=True, padx=20, pady=12)

        # Nav row at bottom
        nav = ttk.Frame(self.top)
        nav.pack(fill='x', padx=20, pady=(0, 16), side='bottom')
        self.back_btn = ttk.Button(nav, text='← Back', command=self._on_back)
        self.back_btn.pack(side='left')
        self.next_btn = ttk.Button(nav, text='Next →', command=self._on_next,
                                    style='Accent.TButton')
        self.next_btn.pack(side='right')
        # Skip link — saves whatever's entered and drops into main GUI
        skip = ttk.Label(nav, text='Skip — set up in main GUI later',
                         style='Dim.TLabel', cursor='hand2')
        skip.bind('<Button-1>', lambda *_: self._on_close())
        skip.pack(side='right', padx=(0, 12))

        # Builder dispatch — methods named _build_{screen_name}
        self._show(0)

    # ---- screen navigation ----

    def _show(self, idx):
        self.current = idx
        # Clear body
        for child in self.body.winfo_children():
            child.destroy()
        self._screen_indicators.clear()
        # Update header
        self._step_label.configure(
            text=f'Step {idx + 1} of {len(self.SCREEN_NAMES)}')
        # Update nav buttons
        self.back_btn.configure(state='normal' if idx > 0 else 'disabled')
        if idx == len(self.SCREEN_NAMES) - 1:
            self.next_btn.configure(text='All set.')
        else:
            self.next_btn.configure(text='Next →')
        # Build screen
        screen_name = self.SCREEN_NAMES[idx]
        builder = getattr(self, f'_build_{screen_name}')
        builder()

    def _on_back(self):
        if self.current > 0:
            self._show(self.current - 1)

    def _on_next(self):
        if not self._validate_current():
            return
        if self.current >= len(self.SCREEN_NAMES) - 1:
            self._finish()
        else:
            self._show(self.current + 1)

    def _on_close(self):
        """X-button or Skip link. Caller persists self.config regardless;
        completed stays False so the main GUI can decide what to do."""
        self.completed = False
        try:
            self.top.grab_release()
            self.top.destroy()
        except tk.TclError:
            pass

    def _finish(self):
        self.completed = True
        try:
            self.top.grab_release()
            self.top.destroy()
        except tk.TclError:
            pass

    def _validate_current(self):
        """Per-screen gate. Override behavior with screen-specific rules.
        Default: allow advance. Each builder may attach a custom
        validator by setting self._current_validator to a callable that
        returns True/False (or pops up a message and returns False)."""
        validator = getattr(self, '_current_validator', None)
        if validator is None:
            return True
        return validator()

    def _set_validator(self, fn):
        """Each screen builder calls this to install its gating logic."""
        self._current_validator = fn

    # ---- helpers used by multiple screens ----

    def _add_path_row(self, parent, label, key, kind,
                      tooltip=None, optional=False):
        """Add a labelled row with: text label, StatusIndicator, Entry,
        Browse button. Wires the Entry to self.config[key] and adds a
        live-update trace for the indicator. Returns the indicator so
        the screen's validator can query its state."""
        row = ttk.Frame(parent); row.pack(fill='x', pady=(4, 2))
        ttk.Label(row, text=label, width=22).pack(side='left')
        indicator = StatusIndicator(row)
        indicator.pack(side='left', padx=(0, 6))
        # Use a StringVar synced to self.config[key]
        var = tk.StringVar(value=self.config.get(key, ''))

        def _on_change(*_):
            self.config[key] = var.get().strip()
            state, detail = validate_path_kind(var.get().strip(), kind)
            # An empty optional path is a soft "unknown" not an error
            if optional and not var.get().strip():
                indicator.set('unknown', f'{label} — optional, leave blank '
                                          f'if not using heritage chrs')
            else:
                indicator.set(state, detail)
        var.trace_add('write', _on_change)
        # Initial state
        _on_change()

        ttk.Entry(row, textvariable=var).pack(
            side='left', fill='x', expand=True, padx=4)
        ttk.Button(row, text='Browse...',
                   command=lambda v=var: self._browse_into(v)).pack(side='left')
        return indicator

    def _browse_into(self, var):
        """Open a directory picker, set var to the chosen path. Local
        to the wizard so we don't depend on a RandoGUI instance."""
        chosen = filedialog.askdirectory(parent=self.top)
        if chosen:
            var.set(chosen)

    # ---- screen builders ----

    def _build_welcome(self):
        """Screen 1 — NR + ER auto-detect confirmation."""
        head = ttk.Label(self.body,
            text="Let's get set up.",
            font=(_pick_ui_font(), 16, 'bold'))
        head.pack(anchor='w', pady=(0, 4))
        sub = ttk.Label(self.body,
            text="This takes about a minute. I'll find your game installs, "
                 "pick a place to write the shuffled files, and make sure "
                 "the Oodle DLL is available.",
            wraplength=620, justify='left', style='Dim.TLabel')
        sub.pack(anchor='w', pady=(0, 16))

        section = ttk.LabelFrame(self.body, text="Game installs", padding=10)
        section.pack(fill='x', pady=4)
        nr_ind = self._add_path_row(
            section, 'Nightreign install:', 'game_install', 'nr_install',
            tooltip='Required. Point at your UXM-unpacked NIGHTREIGN '
                    'install (typically <install>/Game/).')
        er_ind = self._add_path_row(
            section, 'Elden Ring install:', 'er_install', 'er_install',
            optional=True,
            tooltip='Optional. Only needed if you want to import heritage '
                    'chrs (Death Knight, Banished Knight, etc.) from ER.')
        ttk.Label(section,
            text="(Auto-detected from Steam where possible. Use Browse… to "
                 "override or set manually.)",
            style='Dim.TLabel', wraplength=620, justify='left'
            ).pack(anchor='w', pady=(6, 0))

        self._set_validator(self._validate_welcome)
        self._screen_indicators['nr'] = nr_ind
        self._screen_indicators['er'] = er_ind

    def _validate_welcome(self):
        """NR install required to advance; ER is optional."""
        nr_state = self._screen_indicators['nr'].state
        if nr_state in ('ok', 'warn'):
            # warn = path exists but empty (UXM not finished); let user
            # proceed since they may have other things to set up first.
            # The main GUI's Setup Status panel will keep nagging.
            return True
        messagebox.showerror(
            'Nightreign install required',
            "Please set the Nightreign install path before continuing.\n\n"
            "If you don't have NR installed via Steam, click Skip — the "
            "main GUI will let you point at any folder containing "
            "m*.msb.dcx files (e.g. an existing mod's mapstudio).",
            parent=self.top)
        return False

    def _build_output(self):
        """Screen 2 — ME3 output destination."""
        head = ttk.Label(self.body,
            text='Where should the shuffled files go?',
            font=(_pick_ui_font(), 16, 'bold'))
        head.pack(anchor='w', pady=(0, 4))
        sub = ttk.Label(self.body,
            text="Pick your me3 mod profile's folder. The rando writes "
                 "the shuffled MSBs into <this>/map/mapstudio/ — me3 "
                 "loads them as an overlay on top of vanilla.",
            wraplength=620, justify='left', style='Dim.TLabel')
        sub.pack(anchor='w', pady=(0, 16))

        section = ttk.LabelFrame(self.body, text="Output destination",
                                  padding=10)
        section.pack(fill='x', pady=4)
        me3_ind = self._add_path_row(
            section, 'ME3 mod profile:', 'me3_package', 'me3_profile',
            tooltip='Required. The rando writes shuffled MSBs into '
                    '<this>/map/mapstudio/. me3 picks them up as an '
                    'overlay when you launch NR through it.')

        # Inline help — "What's a me3 profile?"
        help_frame = ttk.Frame(self.body); help_frame.pack(fill='x', pady=(16, 0))
        ttk.Label(help_frame,
            text="Don't have an me3 profile yet?",
            style='Dim.TLabel').pack(anchor='w')
        ttk.Label(help_frame,
            text="me3 is mod engine 3 — a runtime mod loader for FromSoft "
                 "games. Install it from GitHub (search 'mod engine 3'), "
                 "create an empty mod profile folder anywhere (e.g. "
                 "Documents/me3-profiles/my-rando/), and point this field "
                 "at that folder.",
            wraplength=620, justify='left', style='Dim.TLabel'
            ).pack(anchor='w', pady=(2, 0))

        self._set_validator(self._validate_output)
        self._screen_indicators['me3'] = me3_ind

    def _validate_output(self):
        state = self._screen_indicators['me3'].state
        if state in ('ok', 'warn'):
            return True
        messagebox.showerror(
            'ME3 output required',
            "Please set the ME3 mod profile path before continuing.\n\n"
            "If you don't have me3 set up yet, click Skip — the main "
            "GUI lets you configure it later and run the rando anyway "
            "(you just need an output folder).",
            parent=self.top)
        return False

    def _build_oodle(self):
        """Screen 3 — Oodle DLL discovery / cache."""
        head = ttk.Label(self.body,
            text='Last thing: Oodle DLL.',
            font=(_pick_ui_font(), 16, 'bold'))
        head.pack(anchor='w', pady=(0, 4))
        sub = ttk.Label(self.body,
            text="Nightreign uses Oodle to compress its .dcx files. The "
                 "rando needs the same DLL to read and re-pack them.",
            wraplength=620, justify='left', style='Dim.TLabel')
        sub.pack(anchor='w', pady=(0, 16))

        # Live-check Oodle status
        try:
            sys.path.insert(0, os.path.join(HERE, 'dev'))
            import install_discovery
            dll = install_discovery.find_oodle_dll()
            nr_install = install_discovery.find_nightreign_install()
            er_install = install_discovery.find_elden_ring_install()
        except Exception as e:
            dll = None
            nr_install = None
            er_install = None
            ttk.Label(self.body,
                text=f'(Discovery error: {e})',
                style='Dim.TLabel').pack(anchor='w')

        section = ttk.LabelFrame(self.body, text="Oodle status", padding=10)
        section.pack(fill='x', pady=4)
        status_row = ttk.Frame(section); status_row.pack(fill='x')
        ind = StatusIndicator(status_row,
                              'ok' if dll else 'error',
                              f'Found: {dll}' if dll else 'Not found')
        ind.pack(side='left', padx=(0, 6))
        ttk.Label(status_row,
            text=(f'Found: {dll}' if dll
                  else 'Not found — needs manual setup'),
            wraplength=560, justify='left',
            ).pack(side='left', fill='x', expand=True)

        # Action: depends on current state
        action_row = ttk.Frame(section); action_row.pack(fill='x', pady=(10, 0))
        if dll and os.path.dirname(os.path.abspath(dll)) != HERE:
            # DLL exists but lives in NR/ER install. Offer to cache it
            # so future launches don't re-scan Steam.
            ttk.Label(action_row,
                text="Optionally copy it next to the rando so launches "
                     "are faster:",
                style='Dim.TLabel', wraplength=620,
                ).pack(anchor='w', pady=(0, 6))
            def _do_copy():
                try:
                    dest = install_discovery.copy_oodle_dll_local()
                    if dest:
                        messagebox.showinfo(
                            'Cached', f'Oodle DLL copied to:\n{dest}',
                            parent=self.top)
                        # Rebuild this screen to show the new state
                        self._show(self.current)
                except Exception as e:
                    messagebox.showerror(
                        'Copy failed', f'{e}', parent=self.top)
            ttk.Button(action_row, text='Cache locally', command=_do_copy
                       ).pack(side='left')
        elif dll:
            # Already cached locally
            ttk.Label(action_row,
                text="✓ Already cached locally — no action needed.",
                ).pack(anchor='w')
        elif nr_install or er_install:
            # Not found, but a source game is detected — offer to copy
            src_label = 'Nightreign' if nr_install else 'Elden Ring'
            src_path = nr_install or er_install
            ttk.Label(action_row,
                text=f"Auto-detected {src_label} install at:\n  {src_path}\n"
                     f"Click the button to copy the bundled Oodle DLL into "
                     f"this folder.",
                wraplength=620, justify='left',
                ).pack(anchor='w', pady=(0, 6))
            def _do_copy_from_install():
                try:
                    dest = install_discovery.copy_oodle_dll_local()
                    if dest:
                        messagebox.showinfo(
                            'Copied',
                            f'Oodle DLL copied to:\n{dest}\n\n'
                            f"You're good to go.",
                            parent=self.top)
                        self._show(self.current)
                    else:
                        messagebox.showerror(
                            'Copy failed',
                            'Discovery found a source game but the DLL '
                            "wasn't where we expected. Browse to "
                            f'{src_path} and copy oo2core_*.dll next to '
                            'oops_rando_gui.py manually.',
                            parent=self.top)
                except Exception as e:
                    messagebox.showerror('Copy failed', f'{e}', parent=self.top)
            ttk.Button(action_row, text=f'Copy from {src_label} install',
                       command=_do_copy_from_install).pack(side='left')
        else:
            # No game install detected. Manual instructions.
            ttk.Label(action_row,
                text="No Nightreign or Elden Ring install detected on this "
                     "machine. To get the Oodle DLL:\n"
                     "  1. On any machine with NR or ER installed, find "
                     "<Steam>/steamapps/common/ELDEN RING NIGHTREIGN/Game/"
                     "oo2core_*_win64.dll\n"
                     "  2. Copy it next to oops_rando_gui.py\n"
                     "  3. Or set the OODLE_DLL environment variable to "
                     "point at it.\n\n"
                     "You can finish setup without it; the rando will "
                     "flag this in Setup Status when you try to run.",
                wraplength=620, justify='left', style='Dim.TLabel',
                ).pack(anchor='w')

        self._set_validator(lambda: True)  # always allow advance

    def _build_done(self):
        """Screen 4 — summary + next steps."""
        head = ttk.Label(self.body,
            text='Setup complete.',
            font=(_pick_ui_font(), 16, 'bold'))
        head.pack(anchor='w', pady=(0, 4))
        sub = ttk.Label(self.body,
            text="Here's what's configured:",
            style='Dim.TLabel')
        sub.pack(anchor='w', pady=(0, 12))

        summary = ttk.LabelFrame(self.body, text="Summary", padding=12)
        summary.pack(fill='x', pady=4)
        for state, text in wizard_summary_lines(self.config):
            row = ttk.Frame(summary); row.pack(fill='x', pady=1)
            ind = StatusIndicator(row, state, text)
            ind.pack(side='left', padx=(0, 6))
            ttk.Label(row, text=text, wraplength=560, justify='left'
                      ).pack(side='left', fill='x', expand=True)

        ttk.Label(self.body,
            text="Click 'All set.' to open the main GUI. You can revisit "
                 "this wizard any time with `python3 oops_rando_gui.py --setup`.",
            wraplength=620, justify='left', style='Dim.TLabel',
            ).pack(anchor='w', pady=(16, 0))

        self._set_validator(lambda: True)


class RandoGUI:
    # ------------------------------------------------------------------
    # v0.26.x: Recommended expedition guidance
    # ------------------------------------------------------------------
    # v0.26.6: DISABLED. The recommendation existed because most
    # Night Boss arenas could CTD/hang/stick on rando swaps and only
    # Tricephalos (Gladius) was validated. v0.26.x: the Night Boss
    # arena issues are resolved -- all NB arenas randomize by default
    # (the multi-entity boss-init break was fixed via the
    # regulation.bin modification) -- so the Nightlord-specific
    # warning the banner carried no longer applies. Keeping the
    # strings + flag plumbing in case the guidance is ever needed
    # again; flipping ACTIVE back to True restores the banner,
    # post-run-summary row, and help-overlay section, and re-greens
    # test_recommended_expedition.py.
    RECOMMENDED_EXPEDITION_ACTIVE = False
    RECOMMENDED_EXPEDITION_NIGHTLORD = 'Tricephalos (Gladius)'
    RECOMMENDED_EXPEDITION_SHORT = (
        f"Pick Tricephalos (Gladius) in-game until other "
        f"Night Boss arenas are validated.")
    RECOMMENDED_EXPEDITION_LONG = (
        "Until all Night Boss EMEVDs are validated end-to-end, "
        "use Tricephalos (Gladius) for your expedition. It's "
        "unlocked from a fresh save and has the most-tested arena. "
        "Other Nightlords may hit EMEVD compatibility gaps in this "
        "version of the rando — bosses idling, cutscenes stuck, "
        "wave-advance flags not firing, etc.")

    def __init__(self, root, progress_callback=None):
        """Construct the main rando GUI.

        progress_callback: optional callable(message:str) invoked at
            major init milestones (data loading, UI building, etc.).
            Used by main() to drive the splash screen's status line.
            Default None makes the parameter backward-compatible with
            any test that constructs RandoGUI directly.
        """
        self._progress_callback = progress_callback or (lambda msg: None)
        self._progress_callback('Starting up…')
        self.root = root
        root.title("4laric's Nightreign Enemy Randomizer")
        root.geometry("900x780")
        root.minsize(780, 640)
        self._apply_theme()

        # Backend state
        self.roster = None
        self.tags = None
        self.prefix_display = {}  # cp → display string for the listbox

        # UI state vars
        self.seed_var = tk.StringVar(value="42")
        # Folder paths — persisted across runs in .4laric_settings.json so the
        # user only has to pick them once. Fallback defaults are folders next
        # to the GUI script (only used if those folders actually exist —
        # release bundles don't ship vanilla data, so this falls back to blank
        # and the user picks their game's mapstudio dir).
        saved_settings = self._load_settings()
        default_input = os.path.join(HERE, "vanilla_msbs")
        if not os.path.isdir(default_input):
            default_input = ''
        self.input_dir_var = tk.StringVar(
            value=saved_settings.get('input_dir') or default_input)
        # v0.24.43: was `or os.path.join(HERE, "shuffled_msbs")` — removed
        # the project-relative default so the empty-guard in
        # _derive_from_me3 can correctly fill this in from the me3 path
        # for first-time users. If neither saved settings nor me3 path
        # is set, output_dir starts empty and the user picks via Browse.
        # (The old shuffled_msbs default was a sandbox-friendly fallback
        # but in practice tried to write into the project directory,
        # which confused users who expected it to go to their mod folder.)
        self.output_dir_var = tk.StringVar(
            value=saved_settings.get('output_dir', ''))
        # Mod map folder: optional. When set, the rando copies finished
        # *.msb.dcx files into this directory after shuffle so the user
        # doesn't have to do it manually. Typical value is the
        # map/mapstudio/ subdirectory of an me3 mod profile.
        self.mod_map_dir_var = tk.StringVar(
            value=saved_settings.get('mod_map_dir', ''))

        # v0.24.0: EMEVD path Tk vars. Source-of-truth file is
        # .4laric_emevd_paths.json (also written by the legacy prepatched-
        # install flow). Populate from there at startup; trace_add writes
        # any subsequent change (typed-in or Browse-picked) back to JSON
        # so _run_shuffle's Step 4 wiring picks up edits without an
        # explicit "Save" step.
        _emevd_paths_init = self._load_emevd_paths()
        self.vanilla_emevd_dir_var = tk.StringVar(
            value=_emevd_paths_init.get('vanilla_dcx', ''))
        self.output_emevd_dir_var = tk.StringVar(
            value=_emevd_paths_init.get('output_dir', ''))
        # Use trace_add to autopersist. Reads/writes the whole JSON on
        # every keystroke; the file is tiny so the cost is irrelevant.
        def _persist_emevd_paths(*_args):
            try:
                self._save_emevd_paths({
                    'vanilla_dcx': self.vanilla_emevd_dir_var.get().strip(),
                    'output_dir': self.output_emevd_dir_var.get().strip(),
                })
            except Exception:
                pass  # never let a save error block the run
        self.vanilla_emevd_dir_var.trace_add('write', _persist_emevd_paths)
        self.output_emevd_dir_var.trace_add('write', _persist_emevd_paths)

        # v0.24.8: Msg bundle paths for the boss-name FMG splicer.
        # Mirrors the EMEVD pattern but takes FULL FILE PATHS instead
        # of dirs since NR's bundles have hash names (e.g.
        # Data0_15912862698882586866.fmg.bnd) and the user knows the
        # exact bundle file. Source-of-truth file is .4laric_msg_paths.json.
        _msg_paths_init = self._load_msg_paths()
        self.vanilla_msg_bundle_var = tk.StringVar(
            value=_msg_paths_init.get('vanilla_bundle', ''))
        self.mod_msg_bundle_var = tk.StringVar(
            value=_msg_paths_init.get('mod_bundle', ''))
        def _persist_msg_paths(*_args):
            try:
                self._save_msg_paths({
                    'vanilla_bundle': self.vanilla_msg_bundle_var.get().strip(),
                    'mod_bundle': self.mod_msg_bundle_var.get().strip(),
                })
            except Exception:
                pass
        self.vanilla_msg_bundle_var.trace_add('write', _persist_msg_paths)
        self.mod_msg_bundle_var.trace_add('write', _persist_msg_paths)

        # v0.24.13: fallback nameId — every cross-game / heterogeneous-
        # squad healthbar routes to a single vanilla nameId instead of
        # allocating fresh FMG entries. No UXM/Oodle/encryption splice
        # needed. ~70% of healthbars still show correct names (vanilla-
        # to-vanilla shuffles via the chr_to_nameid catalog reuse_vanilla
        # path); ~30% cross-game cases show the fallback string.
        #
        # v0.24.105: hardwired ALWAYS-ON with nameId 902130014 = "Crucible
        # Knight and more". Previous GUI toggle removed — the user-facing
        # config surface for this was a footgun (state had to persist
        # correctly across runs, and any off-state silently broke cross-
        # game healthbar names). Hardwiring eliminates that entire failure
        # mode. If a future user wants per-config control again, reinstate
        # `use_fallback_nameid_var` and `fallback_nameid_var` as Tk vars
        # plus the persistence trace_add — see git history at v0.24.104.
        #
        # v0.24.106: the role shifted from "primary path for all cross-
        # game cases" to "safety net used only when the FMG auto-splicer
        # didn't complete". When the user has Vanilla msg + Mod msg bundle
        # paths configured, dcx_batch.rando_pipeline now patches EMEVDs
        # with FRESH nameIds and runs the pure-Python FMG splicer first —
        # which adds the actual per-chr names ("Centipede Demon", "Manus",
        # etc.) to NpcName.fmg. Only when splice fails or paths aren't
        # configured does the pipeline re-patch with this fallback nameId.
        # Net effect: per-chr names when possible, fallback string when
        # not, never "NPCName".
        #
        # v0.24.110: VERIFIED against stock NR's actual item.msgbnd.dcx
        # (Alaric uploaded clean vanilla file 2026-05-17). 902130014 maps
        # to "Crucible Knight and more" — perfect generic-multi fallback.
        # The brief v0.24.109 switch to 902500300 was based on a catalog
        # entry that wasn't actually present in stock NR's FMG. Returning
        # to 902130014.
        FALLBACK_NAMEID = 902130014  # "Crucible Knight and more"
        self.fallback_nameid_value = FALLBACK_NAMEID

        # v0.24.9: top-level "Game install" + "me3 package" pickers.
        # Replace the per-subdir bouncing-around-Folders pattern with
        # two parent paths and derive everything else from them. The
        # individual *_var fields (input_dir_var, vanilla_emevd_dir_var,
        # chr_source_dir_var, mod_map_dir_var, output_emevd_dir_var,
        # chr_target_dir_var, and the msg bundle pair) still exist and
        # are still wired into the run pipeline; they're just auto-
        # populated from the two parents now, with the existing rows
        # staying visible so the user can override individual paths
        # when their layout doesn't match the convention.
        _root_paths_init = self._load_root_paths()
        # v0.26.x: opportunistic auto-detect for first-launch UX. If a
        # given root path wasn't saved from a previous session, try to
        # discover the install location from Steam's library config so
        # the user doesn't have to Browse manually. Detection is a
        # silent fallback — if Steam isn't installed or the games
        # aren't found, the field stays empty and the user proceeds
        # with manual entry as before. Saved values always win over
        # detected ones (avoids re-clobbering an intentional override
        # after the user moves their install).
        _root_paths_init = self._apply_install_autodetect(_root_paths_init)
        self.game_install_var = tk.StringVar(
            value=_root_paths_init.get('game_install', ''))
        # v0.24.47: separate Elden Ring install path. Used for heritage
        # chr imports (the chr-asset-import tool that copies ER's chr/
        # files into the me3 mod profile). Previously chr_source_dir
        # was auto-derived from game_install/chr — but game_install is
        # NIGHTREIGN's install (NR doesn't ship the heritage chrs;
        # those have to come from a separate ER install). Splitting
        # the path makes the requirement explicit.
        self.er_install_var = tk.StringVar(
            value=_root_paths_init.get('er_install', ''))
        self.me3_package_var = tk.StringVar(
            value=_root_paths_init.get('me3_package', ''))
        # v0.26.x: me3 launcher binary path. Optional — find_me3_binary
        # auto-discovers in most cases. The Launch button uses this if
        # set, otherwise falls back to runtime discovery. Saved across
        # launches alongside the other root paths.
        self.me3_launcher_var = tk.StringVar(
            value=_root_paths_init.get('me3_launcher', ''))
        # v0.26.x: auto-launch after generate. When True, a successful
        # generate run automatically shells out to me3 via _launch_via_me3.
        # v0.26.x persistence: this checkbox is "set once and forget" —
        # users who enable it want it sticky across sessions.
        self.auto_launch_after_generate_var = tk.BooleanVar(
            value=saved_settings.get('auto_launch_after_generate', False))
        self.auto_launch_after_generate_var.trace_add('write',
            lambda *_: self._save_settings(
                auto_launch_after_generate=bool(
                    self.auto_launch_after_generate_var.get())))
        # v0.26.x: dismissal state for the recommended-expedition banner.
        # Persisted via _save_settings so a user who dismisses it once
        # doesn't see it on subsequent launches. The banner is wired to
        # check this AND RECOMMENDED_EXPEDITION_ACTIVE — flipping either
        # to False hides the banner.
        self.recommended_expedition_dismissed_var = tk.BooleanVar(
            value=saved_settings.get(
                'recommended_expedition_dismissed', False))
        self.recommended_expedition_dismissed_var.trace_add('write',
            lambda *_: self._save_settings(
                recommended_expedition_dismissed=bool(
                    self.recommended_expedition_dismissed_var.get())))

        # The discovered Item-bundle basename is cached separately so
        # the relatively expensive scan-and-parse only runs when the
        # game_install path actually changes.
        self.msg_bundle_basename_var = tk.StringVar(
            value=_root_paths_init.get('msg_basename', ''))

        def _persist_root_paths(*_args):
            try:
                self._save_root_paths({
                    'game_install': self.game_install_var.get().strip(),
                    'er_install': self.er_install_var.get().strip(),
                    'me3_package': self.me3_package_var.get().strip(),
                    'me3_launcher': self.me3_launcher_var.get().strip(),
                    'msg_basename': self.msg_bundle_basename_var.get().strip(),
                })
            except Exception:
                pass

        def _derive_from_game_install(*_args):
            game = self.game_install_var.get().strip()
            if not game:
                return
            # Convention is the UXM-unpacked layout: <install>/Game/...
            # If user picked the install root (not the Game/ subdir),
            # auto-append Game/ — most-common case.
            if (not game.rstrip(os.sep).endswith('Game') and
                    os.path.isdir(os.path.join(game, 'Game'))):
                game = os.path.join(game, 'Game')
                self.game_install_var.set(game)
                return
            if hasattr(self, 'input_dir_var') and not self.input_dir_var.get().strip():
                self.input_dir_var.set(os.path.join(game, 'map', 'mapstudio'))
            if hasattr(self, 'vanilla_emevd_dir_var') and not self.vanilla_emevd_dir_var.get().strip():
                self.vanilla_emevd_dir_var.set(os.path.join(game, 'event'))
            # v0.24.47: REMOVED `chr_source_dir_var.set(game/chr)` here.
            # game_install is NIGHTREIGN's install — NR doesn't ship the
            # heritage chrs that chr_source_dir is supposed to point at.
            # chr_source_dir now derives from er_install/chr instead
            # (see _derive_from_er_install below).
            # msg bundle is a FILE path with a hash basename — discover
            # it by scanning <game>/msg/engUS/ for *.fmg.bnd containing
            # NpcName.fmg. Cache the basename so we only do this once
            # per game_install change.
            # v0.24.43 BUGFIX: same fix as _derive_from_me3 — only set
            # child paths if currently empty. Treats derivation as
            # one-time first-setup convenience, not a binding override.
            self._discover_msg_bundle_basename(game)
            self._apply_msg_basename_derivation()
            _persist_root_paths()

        def _derive_from_er_install(*_args):
            """v0.24.47: derive chr_source_dir from the Elden Ring install.

            Heritage chrs (Death Knight, Banished Knight, Erdtree Avatar
            variants, etc.) come from ER, not NR. The chr-asset-import
            tool copies files from <er_install>/chr/ into the me3 mod's
            chr/ dir, so the source path must point at ER.

            Same empty-guard pattern as _derive_from_game_install /
            _derive_from_me3: only fills chr_source_dir if it's
            currently empty. User customizations stick.
            """
            er = self.er_install_var.get().strip()
            if not er:
                return
            # Auto-append Game/ if user picked the install root
            if (not er.rstrip(os.sep).endswith('Game') and
                    os.path.isdir(os.path.join(er, 'Game'))):
                er = os.path.join(er, 'Game')
                self.er_install_var.set(er)
                return
            if hasattr(self, 'chr_source_dir_var') and not self.chr_source_dir_var.get().strip():
                self.chr_source_dir_var.set(os.path.join(er, 'chr'))
            _persist_root_paths()

        def _derive_from_me3(*_args):
            me3 = self.me3_package_var.get().strip()
            if not me3:
                return
            # v0.24.43 BUGFIX: only derive child paths that are CURRENTLY EMPTY.
            # The previous behavior unconditionally overwrote output_dir,
            # mod_map_dir, output_emevd_dir, and chr_target_dir whenever
            # me3_package changed — which fires at startup when settings
            # load, clobbering any saved custom output_dir. User-reported
            # symptom: "the gui has a bug where it's overwriting the path
            # for shuffled msb output dir."
            #
            # New semantic: derivation is a one-time convenience default
            # for empty fields. Once the user (or saved settings) populate
            # a child path, _derive_from_me3 leaves it alone. To re-derive,
            # the user can clear the field manually.
            if hasattr(self, 'output_dir_var') and not self.output_dir_var.get().strip():
                self.output_dir_var.set(os.path.join(me3, 'map', 'mapstudio'))
            if hasattr(self, 'mod_map_dir_var') and not self.mod_map_dir_var.get().strip():
                self.mod_map_dir_var.set(os.path.join(me3, 'map', 'mapstudio'))
            if hasattr(self, 'output_emevd_dir_var') and not self.output_emevd_dir_var.get().strip():
                self.output_emevd_dir_var.set(os.path.join(me3, 'event'))
            if hasattr(self, 'chr_target_dir_var') and not self.chr_target_dir_var.get().strip():
                self.chr_target_dir_var.set(os.path.join(me3, 'chr'))
            self._apply_msg_basename_derivation()
            _persist_root_paths()

        self.game_install_var.trace_add('write', _derive_from_game_install)
        self.er_install_var.trace_add('write', _derive_from_er_install)
        self.me3_package_var.trace_add('write', _derive_from_me3)
        # v0.26.x: me3_launcher persists like the others but has no
        # derivation chain (it's a leaf — no child paths derived from it).
        self.me3_launcher_var.trace_add('write', _persist_root_paths)
        # Stash for later — we call these once at end of __init__ after
        # all child vars exist, to propagate any persisted parent paths
        # to their derived children on startup.
        self._derive_from_game_install = _derive_from_game_install
        self._derive_from_er_install = _derive_from_er_install
        self._derive_from_me3 = _derive_from_me3
        # v0.23.56: optional vanilla NR map/mapstudio path. When set, the
        # rando pulls in the 23 spawn-pool MSBs (m46_5x, m46_72/74,
        # m46_8x, m46_9x) from this directory so they get randomized
        # alongside the live world maps. Without this, NR's expedition
        # rotation system always spawns vanilla chrs (Tree Sentinels,
        # BBH at Castle Basement, Death Rite Bird, etc.) at their attach
        # points, because most me3 profiles don't override these tiny
        # maps. See V3_SPAWN_POOL_MSBS in oops_v3.py for the full list
        # and note on why m48_20 is explicitly excluded despite a
        # superficially similar pattern.
        self.spawn_pool_source_dir_var = tk.StringVar(
            value=saved_settings.get('spawn_pool_source_dir', ''))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_listbox())
        self.status_var = tk.StringVar(value="Ready")
        # v0.26.x: persist mode selection across launches. If a user
        # works primarily in "Oops! All NB" mode, having to re-select
        # it every session is friction.
        self.run_mode_var = tk.StringVar(
            value=saved_settings.get('run_mode', "Standard"))
        self.run_mode_var.trace_add('write',
            lambda *_: self._save_settings(
                run_mode=self.run_mode_var.get()))
        # v0.26.x: track the last confirmed mode for the Oops-mode
        # confirmation guard. Initialized here (not in _build_ui) so the
        # startup mode-change handler — which applies the restored
        # picker state — sees mode == last and doesn't spuriously prompt
        # for a restored Oops! All setting.
        self._last_confirmed_mode = self.run_mode_var.get()
        # v0.26.x: persist Oops! All target pick. Same logic as the
        # NB target/scope below — most users iterating on a probe
        # target want it sticky across launches.
        self.oops_all_target_var = tk.StringVar(
            value=saved_settings.get('oops_all_target', ''))
        self.oops_all_target_var.trace_add('write',
            lambda *_: self._save_settings(
                oops_all_target=self.oops_all_target_var.get()))
        # v0.23.39: NB-only oops-all variant. Forces every Night-Boss-tier
        # slot (under selectable scope) to one specific c-prefix. Field /
        # grunt slots randomize normally, so cross-game CTD-suspect chrs
        # can be probed against boss arenas without flooding the whole run.
        # Persist across launches so the user can iterate on a probe target
        # without re-typing each time.
        # v0.26.x: was previously saved only on Run (in _run_shuffle).
        # That meant changing the picker but not clicking Run lost the
        # change. Now persists live on every change.
        self.oops_all_nb_target_var = tk.StringVar(
            value=saved_settings.get('oops_all_nb_target', ''))
        self.oops_all_nb_target_var.trace_add('write',
            lambda *_: self._save_settings(
                oops_all_nb_target=self.oops_all_nb_target_var.get()))
        self.oops_all_nb_scope_var = tk.StringVar(
            value=saved_settings.get('oops_all_nb_scope', 'extended'))
        self.oops_all_nb_scope_var.trace_add('write',
            lambda *_: self._save_settings(
                oops_all_nb_scope=self.oops_all_nb_scope_var.get()))
        # Multiplayer-safe mode: blacklist all heritage-imported c-prefixes
        # so coop partners without the heritage pack don't CTD on cell-load.
        self.multiplayer_safe_var = tk.BooleanVar(
            value=saved_settings.get('multiplayer_safe', True))
        # v0.23.43: persist on toggle, not just on Run. Otherwise users who
        # toggle the box and close the app without running lose the change.
        self.multiplayer_safe_var.trace_add("write", lambda *_: self._save_settings(
            multiplayer_safe=bool(self.multiplayer_safe_var.get())))

        # v0.23.45: MMV integration toggle. Reads from + writes to the
        # `_meta.enabled` field of mmv_imports.json. The engine reads that
        # file at load_data time, so toggling the checkbox immediately
        # affects subsequent runs without restart. Persistence is implicit
        # (the JSON file IS the persistent store). Default reflects current
        # JSON state, so users who manually edited the file keep their
        # setting.
        self._mmv_initial_state = self._read_mmv_enabled()
        self.mmv_enabled_var = tk.BooleanVar(value=self._mmv_initial_state)
        self.mmv_enabled_var.trace_add("write",
            lambda *_: self._on_mmv_toggle())

        # v0.23.11: chr/ inventory tab — paths for the heritage_chr_import tool.
        # Persisted across runs so users don't re-pick every time.
        self.chr_source_dir_var = tk.StringVar(
            value=saved_settings.get('chr_source_dir', ''))
        self.chr_target_dir_var = tk.StringVar(
            value=saved_settings.get('chr_target_dir', ''))
        self.chr_overwrite_var = tk.BooleanVar(value=False)
        # v0.27.0: roster-import flow — separate MMV-mod and Elden-Ring
        # source folders. The importer routes each roster chr MMV-first,
        # ER-fallback. ER folder seeds from the existing chr_source_dir /
        # er_install if previously set, so upgrading users don't re-pick.
        self.roster_mmv_dir_var = tk.StringVar(
            value=saved_settings.get('roster_mmv_dir', ''))
        self.roster_er_dir_var = tk.StringVar(
            value=saved_settings.get('roster_er_dir', ''))

        # v0.24.9: now that ALL path vars exist, propagate any persisted
        # parent paths to their derived children. Without this, on a
        # second launch the user sees their saved game_install /
        # me3_package paths in the parent fields but the children
        # would be blank or stale until they re-pick.
        if self.game_install_var.get().strip():
            self._derive_from_game_install()
        if self.er_install_var.get().strip():
            self._derive_from_er_install()
        if self.me3_package_var.get().strip():
            self._derive_from_me3()

        # v0.20.35: diagnostic mode — disables the RESILIENT_BIPEDS whitelist
        # at fragile slots, leaving only the SENSITIVE blacklist active.
        # Goal is to surface freezes from non-RESILIENT c-prefixes so we
        # can grow SENSITIVE empirically and eventually retire RESILIENT.
        # Default OFF; only useful for diagnostic playtests.
        self.disable_resilient_filter_var = tk.BooleanVar(value=False)
        # v0.26.16: prefer canonical variants. When ON, the picker filters
        # each c-prefix to the variants vanilla NR actually placed
        # (sample_maps non-empty), skipping untested ghost variants that
        # can render glitched (T-pose, missing textures, off-scale FFX).
        # Soft filter — chrs with only ghost variants stay pickable.
        # Default ON for visual stability.
        self.prefer_canonical_variants_var = tk.BooleanVar(value=True)
        # v0.26.16 / v0.26.x: randomize the safe single-boss night-boss
        # arenas. Subsumed by randomize_all_nb_arenas (all 25 includes
        # the safe 12) and its checkbox was removed alongside the all-NB
        # one. Var kept declared so generate_run's config dict and
        # dcx_batch.rando_pipeline(randomize_safe_nb_arenas=...) still
        # have a defined input. Fixed False -- the all-NB flag covers it.
        self.randomize_safe_nb_arenas_var = tk.BooleanVar(value=False)
        # v0.26.16 / v0.26.x: randomize ALL 25 night-boss arenas incl.
        # the multi-entity ones. DEFAULT TRUE -- the multi-entity boss-
        # init investigation is closed (resolved by the regulation.bin
        # modification), so all-NB randomization is normal play now.
        # Checkbox removed in v0.26.x (no longer a diagnostic opt-in);
        # var kept declared since generate_run + dcx_batch read it.
        self.randomize_all_nb_arenas_var = tk.BooleanVar(value=True)
        # v0.20.42: diagnostic batch — when non-empty, fragile slots are
        # restricted to ONLY this comma-separated list of c-prefixes. Used
        # to attribute CTDs to a small batch of candidates instead of
        # rolling against ~100 untested c-prefixes. Empty = full untested
        # pool (existing v0.20.37 behavior).
        self.diagnostic_test_targets_var = tk.StringVar(value="")

        # v0.23.05 / v0.24.0: user force-include for boss-tier targets
        # normally blocked by V3_EXCLUDE_TARGET_PREFIXES /
        # V3_GHOST_EXCLUDE_TARGET_PREFIXES. UI removed in v0.24.0 (front-
        # page bloat); var kept so engine plumbing
        # (shuffle_msb_v3(force_include_targets=...)) still has a defined
        # input. Empty = vanilla behavior, which is now the only behavior
        # absent a re-introduced UI / CLI flag.
        self.force_include_targets = []  # list of c-prefixes
        # Picker StringVar — orphaned with UI removed in v0.24.0; left
        # declared so _force_include_add (also orphaned) doesn't fail
        # if it's ever called from a debug path.
        self.force_include_picker_var = tk.StringVar(value="")
        # merchant_model_swap: when True, swap visual models of merchants
        # (Nomadic, Small Jar) to humanoid alternatives. Merchant function
        # is preserved (still has shop/dialogue) — only the visual changes.
        # v0.19.27: default ON — playtested as solid, adds variety to NPCs.
        self.merchant_model_swap_var = tk.BooleanVar(value=True)
        # v0.23.19 / v0.24.0: Cinematic Chaos engine flag chaos_mode.
        # When ON, asymmetric NB-tier gating activates: Night Boss chrs
        # (Margit, Maliketh, Astel, etc.) become eligible at field-boss
        # / overworld slots, AND the NB arena gate tightens so field-tier
        # giants can't leak UP. UI removed in v0.24.0 (front-page bloat);
        # var kept since generate_run reads it and the engine path is
        # still live. Default OFF — without a UI, chaos_mode stays OFF.
        self.chaos_mode_var = tk.BooleanVar(value=False)
        # v0.26.15: mount/rider feature, cut 1 (detection foundation).
        # Experimental dev-section toggle. When ON, the engine detects
        # mount/rider Part pairs and logs them to the spoiler audit trace
        # — it does NOT yet change any swap target (the coordinated swap
        # is cut 2). Default OFF.
        self.mount_rider_swap_var = tk.BooleanVar(value=False)

        self.excluded = set(DEFAULT_EXCLUDED)
        self.hub_maps = set(DEFAULT_HUB_MAPS)

        # Worker thread state for non-blocking shuffle
        self.log_queue = queue.Queue()
        self.worker_thread = None

        self._progress_callback('Loading enemy data…')
        self._load_data()
        self._progress_callback('Building interface…')
        self._build_ui()
        # v0.26.x: if run_mode was restored from saved settings as
        # something other than "Standard", the matching picker frame
        # isn't visible yet (the combobox event didn't fire for the
        # initial StringVar value). Apply the side effect once so the
        # UI matches the restored state.
        self._on_mode_change()
        self._progress_callback('Wiring shortcuts…')
        self._bind_keyboard_shortcuts()
        self._progress_callback('Ready')
        self.root.after(100, self._drain_log_queue)

    def _parse_diag_test_targets(self):
        """Parse the diagnostic batch text entry into a set of c-prefixes.

        Empty string / whitespace / no valid entries → returns None
        (engine treats None as "no batch restriction"). Otherwise
        returns a frozenset of normalized c-prefix strings.

        Accepts comma- or space-separated, case-insensitive, with or
        without 'c' prefix on entries (silently normalizes).
        """
        raw = (self.diagnostic_test_targets_var.get() or '').strip()
        if not raw:
            return None
        import re
        tokens = re.split(r'[,\s]+', raw)
        out = set()
        for t in tokens:
            t = t.strip().lower()
            if not t:
                continue
            if not t.startswith('c'):
                t = 'c' + t
            # Validate basic shape: c followed by digits
            if re.match(r'^c\d{2,5}$', t):
                out.add(t)
        return frozenset(out) if out else None

    # ------------------------------------------------------------------
    # v0.26.x: keyboard shortcuts
    # ------------------------------------------------------------------
    # Bindings live on self.root so they fire from anywhere in the
    # window, regardless of which widget has focus. Each handler
    # returns 'break' so the event doesn't propagate into the
    # default Tk behavior (Ctrl+R in a Text widget would otherwise
    # do something unrelated).

    # Pure helper — kept as a class attribute so tests can introspect
    # the shortcut list without instantiating Tk. Tuples are
    # (key_combo_display, tk_binding_sequence, action_description,
    # handler_method_name).
    KEYBOARD_SHORTCUTS = [
        ('Ctrl+R / F5', ('<Control-r>', '<F5>'),
         'Randomize (or Cancel a running generate)',
         '_shortcut_randomize'),
        ('Ctrl+L', ('<Control-l>',),
         'Launch the active me3 profile',
         '_shortcut_launch'),
        ('Ctrl+Shift+R', ('<Control-R>',),  # Capital R = with Shift
         'Roll a new random seed (does not start a run)',
         '_shortcut_random_seed'),
        ('Ctrl+Q', ('<Control-q>',),
         'Quit the application',
         '_shortcut_quit'),
        ('F1', ('<F1>',),
         'Show this keyboard shortcuts cheatsheet',
         '_show_shortcuts_cheatsheet'),
    ]

    def _bind_keyboard_shortcuts(self):
        """Wire each KEYBOARD_SHORTCUTS entry to a handler on self.root.
        Called from __init__ after the UI is built so all the target
        widgets (run_btn, launch_btn) exist."""
        for _, sequences, _, handler_name in self.KEYBOARD_SHORTCUTS:
            handler = getattr(self, handler_name, None)
            if handler is None:
                continue  # graceful degrade if a handler is renamed
            for seq in sequences:
                self.root.bind(seq, handler)

    def _shortcut_randomize(self, event=None):
        """Ctrl+R / F5: invoke the run button. The button's command
        toggles between Randomize and Cancel based on worker state —
        invoking it does whichever is currently appropriate."""
        if hasattr(self, 'run_btn'):
            try:
                # Only invoke if the button is in 'normal' state — a
                # disabled button means we're in a transient state
                # where firing the shortcut would race the worker.
                state = str(self.run_btn['state'])
                if state == 'normal':
                    self.run_btn.invoke()
            except (tk.TclError, AttributeError):
                pass
        return 'break'

    def _shortcut_launch(self, event=None):
        """Ctrl+L: trigger the Launch button, if it's currently
        enabled (ME3 ready + package set). When disabled, do nothing —
        firing a shortcut into a disabled action would surprise users."""
        if hasattr(self, 'launch_btn'):
            try:
                state = str(self.launch_btn['state'])
                if state == 'normal':
                    self.launch_btn.invoke()
            except (tk.TclError, AttributeError):
                pass
        return 'break'

    def _shortcut_random_seed(self, event=None):
        """Ctrl+Shift+R: roll a fresh seed into the Seed entry."""
        try:
            self._random_seed()
        except Exception:
            pass
        return 'break'

    def _shortcut_quit(self, event=None):
        """Ctrl+Q: close the window. Cancels any running worker
        cleanly via the existing window-close protocol if one is set,
        else just destroys the root."""
        try:
            # Prefer the registered WM_DELETE handler if present so
            # cleanup logic (e.g. cancel a running worker) gets a
            # chance to run. Falls back to plain destroy().
            self.root.event_generate('<<QuitRequest>>')
        except tk.TclError:
            pass
        try:
            # Generate WM_DELETE_WINDOW via the actual protocol
            self.root.destroy()
        except tk.TclError:
            pass
        return 'break'

    # ------------------------------------------------------------------
    # v0.26.x: per-tab help overlays
    # ------------------------------------------------------------------
    # Each user-facing tab can carry a "?" button in its header that
    # opens a modal with tab-specific guidance. The cheatsheet modal
    # for keyboard shortcuts (F1) covers global hotkeys; this covers
    # "what does this tab do and what should I know before clicking
    # around?" — the kind of question new users have on their first
    # session.

    TAB_HELP_CONTENT = {
        'generate': {
            'title': 'Generate tab',
            'body': (
                "PURPOSE\n"
                "  This is the main page. Set your paths, pick a seed "
                "and mode, click Randomize.\n"
                "\n"
                "FIRST RUN\n"
                "  1. Set the three install paths in 'Folders':\n"
                "     • Nightreign install — your UXM-unpacked NR Game/\n"
                "     • Elden Ring install — UXM-unpacked ER Game/\n"
                "       (only needed for heritage chr imports)\n"
                "     • me3 package — your active me3 mod's package "
                "subdir.\n"
                "       Don't have one? Click 'Create new…' next to "
                "Browse.\n"
                "  2. Click Randomize. The rando derives every other "
                "path automatically.\n"
                "  3. Click 🎮 Launch via ME3 to start the game with "
                "your new mod loaded.\n"
                "\n"
                "MODES\n"
                "  • Standard — normal randomization across all slots.\n"
                "  • Oops! All — replace every slot with one chosen "
                "enemy.\n"
                "  • Oops! All NB — replace only Night Boss-tier slots "
                "with a chosen boss. Useful for testing one boss across "
                "every arena it could spawn in.\n"
                "  • Validation: rats/jellies — smoke-test mode with "
                "low-CTD-risk enemies. Use after config changes to "
                "confirm end-to-end works.\n"
                "\n"
                "SEED\n"
                "  Same seed + same options = same result. Share a seed "
                "to swap runs with a friend, or fix one for testing. "
                "Click 🎲 for a fresh seed.\n"
                "\n"
                "RECOMMENDED EXPEDITION (current rando version)\n"
                "  After generating + launching, pick Tricephalos "
                "(Gladius) at the expedition select screen. It's the "
                "first-unlocked Nightlord on a fresh save and its "
                "arena is the most-tested with the rando's swaps. "
                "Other Nightlord arenas may hit EMEVD compatibility "
                "gaps in this version — bosses idling, cutscenes "
                "stuck, wave-advance flags not firing.\n"
                "\n"
                "TROUBLESHOOTING\n"
                "  • The Setup Status panel at top shows what's OK / "
                "warning / missing. Red rows usually need attention "
                "before clicking Randomize.\n"
                "  • 'Launch via ME3' disabled? Hover the button — the "
                "tooltip explains what's missing.\n"
                "  • Want to skip heritage chrs entirely? See the "
                "Heritage / Multiplayer tab.\n"
            ),
        },
        'heritage': {
            'title': 'Heritage / Multiplayer tab',
            'body': (
                "PURPOSE\n"
                "  Controls which enemies the rando is allowed to use, "
                "plus advanced diagnostic toggles.\n"
                "\n"
                "MULTIPLAYER-SAFE (default ON)\n"
                "  When ON, the rando never uses 'heritage' chrs "
                "(imports from Elden Ring like Death Knight, Banished "
                "Knight, etc.).\n"
                "  Why default ON: heritage chrs CTD coop partners who "
                "don't have the heritage pack installed. Solo play is "
                "fine, but ANY session that might involve coop should "
                "leave this ON.\n"
                "  Turn OFF only if you've coordinated with your coop "
                "partners (everyone has heritage chrs) or you're "
                "playing solo.\n"
                "\n"
                "MMV INTEGRATION (default OFF)\n"
                "  When ON, ~41 cross-game bosses (Malenia, Maliketh, "
                "Slave Knight Gael, Dragonslayer Armor, etc.) become "
                "eligible for swap. Boss-tier pool roughly doubles.\n"
                "  REQUIRES the More Map Variations mod installed in "
                "your me3 profile. Without those assets, enabling this "
                "CTDs the game on cell load.\n"
                "  Get MMV: "
                "https://www.nexusmods.com/eldenringnightreign/mods/578\n"
                "  (also linked on the About tab)\n"
                "\n"
                "VANILLA MAPSTUDIO (advanced, collapsed by default)\n"
                "  Optional spawn-pool source for rotation-pool bosses "
                "(Tree Sentinels, Bell-Bearing Hunter, etc). Most users "
                "leave this blank.\n"
                "\n"
                "DIAGNOSTIC (advanced, collapsed by default)\n"
                "  Engine-validation tools for the modders working on "
                "the rando itself. NOT for normal play — these change "
                "the swap distribution in ways that will look weird if "
                "you're trying to enjoy a run.\n"
            ),
        },
        'er_assets': {
            'title': 'Elden Ring Assets tab',
            'body': (
                "PURPOSE\n"
                "  Manage heritage chr files imported from Elden Ring "
                "into your me3 profile's chr/ folder.\n"
                "\n"
                "WHY THIS MATTERS\n"
                "  Heritage chrs (Death Knight, Banished Knight, etc.) "
                "ship with Elden Ring, not Nightreign. The rando can "
                "REFERENCE them in shuffled MSBs, but the chr binary "
                "files (.chrbnd.dcx) have to physically exist in your "
                "me3 profile's chr/ folder or the game CTDs on cell "
                "load.\n"
                "\n"
                "WORKFLOW\n"
                "  Setup (one-time):\n"
                "    1. Set 'Unpacked Elden Ring folder' to your UXM-"
                "unpacked ER Game/.\n"
                "    2. Set 'me3 mod folder' to your me3 profile's "
                "package dir.\n"
                "    3. Click 'Import all available' — bulk-copies "
                "every heritage chr the rando might ever use into your "
                "me3 chr/.\n"
                "\n"
                "  Per-run (if you want to be precise):\n"
                "    1. Click 'Auto-find' next to Spoiler to pick the "
                "latest run's spoiler.\n"
                "    2. Click 'Diagnose' — reports which heritage chrs "
                "are missing for THIS run.\n"
                "    3. Click 'Import' — copies only the chrs this "
                "run actually uses.\n"
                "\n"
                "OVERWRITE EXISTING FILES\n"
                "  Default OFF — skips chr files already in your me3 "
                "chr/. Turn ON for a clean re-import (e.g. after a "
                "previous import was interrupted).\n"
                "\n"
                "PACK STATUS\n"
                "  Lists each enemy pack the rando knows about plus "
                "whether the matching chr files are present on disk. "
                "Green = all chrs present, red = some missing.\n"
            ),
        },
        'paths': {
            'title': 'Paths tab',
            'body': (
                "PURPOSE\n"
                "  Override individual file/folder paths the rando "
                "uses. Most users never need this tab.\n"
                "\n"
                "WHY THIS EXISTS\n"
                "  The Generate tab's two root paths (Nightreign "
                "install + me3 package) auto-derive every other path "
                "the rando needs:\n"
                "    Vanilla MSBs    ← <NR>/map/mapstudio/\n"
                "    Vanilla event/  ← <NR>/event/\n"
                "    Vanilla chr/    ← <ER>/chr/\n"
                "    Mod map/        ← <me3>/map/mapstudio/\n"
                "    Mod event/      ← <me3>/event/\n"
                "    Mod chr/        ← <me3>/chr/\n"
                "    Mod msg/        ← <me3>/msg/engUS/<bundle>\n"
                "\n"
                "WHEN TO OVERRIDE\n"
                "  • Your UXM-unpacked layout doesn't match the "
                "convention (e.g. you keep map/mapstudio at the root, "
                "not under Game/).\n"
                "  • You want vanilla MSBs from one source but vanilla "
                "EMEVDs from another.\n"
                "  • Your msg bundle file has been renamed or lives "
                "in a non-default location.\n"
                "\n"
                "EDITING SAFELY\n"
                "  Each row is an independent override. Editing one "
                "doesn't affect the others. Clear a field to fall "
                "back to the auto-derived default.\n"
                "\n"
                "EMEVD + MSG paths persist immediately to their own "
                "JSON sidecar files (.4laric_emevd_paths.json, "
                ".4laric_msg_paths.json). No 'Save' button needed.\n"
            ),
        },
        'excluded': {
            'title': 'Excluded Enemies tab',
            'body': (
                "PURPOSE\n"
                "  Pin specific enemy c-prefixes so they stay vanilla "
                "during randomization. Excluded enemies are removed "
                "from BOTH the candidate pool (won't be swapped TO) "
                "AND their original slots keep their vanilla chr.\n"
                "\n"
                "WHEN TO USE\n"
                "  • An enemy CTDs your game and you want to keep it "
                "out of swaps while you investigate.\n"
                "  • You want to preserve a few specific encounters "
                "as they originally appear (e.g. story bosses you "
                "don't want surprised by).\n"
                "  • Engine work: testing a specific c-prefix in "
                "isolation by excluding others.\n"
                "\n"
                "DEFAULTS\n"
                "  The Reset button restores the rando's curated "
                "DEFAULT_EXCLUDED list — c-prefixes known to crash, "
                "not have working models, or break engine assumptions. "
                "Removing items from this default list is risky and "
                "can cause CTDs.\n"
                "\n"
                "INTERFACE\n"
                "  • Left list: all enemies (filtered by Search).\n"
                "  • Right list: currently excluded.\n"
                "  • Use Exclude → / ← Include to move selections "
                "between lists. Multi-select with Ctrl/Shift-click.\n"
                "  • Search filters BOTH lists (handy for finding a "
                "specific c-prefix to add/remove).\n"
                "\n"
                "SCOPE\n"
                "  Exclusions apply to the SWAP POOL, not to spawn "
                "elimination. The vanilla slots that hold excluded "
                "enemies are kept as-is — they just aren't randomized.\n"
            ),
        },
        'hub_maps': {
            'title': 'Hub Maps tab',
            'body': (
                "PURPOSE\n"
                "  Mark specific maps as 'hubs' so the rando leaves "
                "their NPCs/enemies completely alone. The defaults "
                "cover Roundtable Hold and its variants.\n"
                "\n"
                "WHY THIS EXISTS\n"
                "  Some maps are social/utility spaces (vendors, "
                "story characters, quest-givers) where randomizing "
                "would break the gameplay loop or replace named NPCs "
                "with hostile chrs. The rando skips hub maps entirely "
                "during shuffle.\n"
                "\n"
                "WHEN TO MODIFY\n"
                "  Rarely — the defaults are correct for vanilla NR. "
                "Add a map if you've installed a mod that introduces "
                "a new hub area you want preserved.\n"
                "\n"
                "  Remove a map if you intentionally WANT hostiles in "
                "that space (advanced; expect breakage if the map's "
                "NPCs are story-relevant).\n"
                "\n"
                "MAP FORMAT\n"
                "  Maps are entered as the MSB stem (e.g. 'm60_42_36_00' "
                "without extension). Wrong format = the rando ignores "
                "the entry silently. To check the right stem, look at "
                "the filenames in <NR>/map/mapstudio/.\n"
            ),
        },
        'spoiler': {
            'title': 'Spoiler tab',
            'body': (
                "PURPOSE\n"
                "  Inspect what got swapped to what in a previous "
                "randomizer run, filtered by map / enemy / boss-only.\n"
                "\n"
                "LOADING A SPOILER\n"
                "  • Browse… — pick any _spoilers.json from your "
                "filesystem.\n"
                "  • Load latest — auto-find the most recent spoiler "
                "in your configured Output dir.\n"
                "  • Reload — re-read the currently-loaded file (handy "
                "after a new generate run).\n"
                "\n"
                "  The post-run summary panel on the Generate tab "
                "also has a one-click 'View' button that opens the "
                "freshly-generated spoiler directly in this tab.\n"
                "\n"
                "RUN INFO PANEL\n"
                "  Shows the engine fingerprint, seed, total entry "
                "count, multiplayer-safe state, Oops! All NB target "
                "(if any), and diagnostic flags. Useful for "
                "double-checking the run produced what you expected.\n"
                "\n"
                "FILTERS\n"
                "  • Search — case-insensitive substring match across "
                "BOTH the original and the new enemy name.\n"
                "  • Map — narrow to one map at a time.\n"
                "  • Bosses only — show only entries flagged as "
                "is_boss=true (Night Boss anchors, field bosses, POI "
                "bosses).\n"
                "  • Clear filters — reset all three.\n"
                "\n"
                "ENTRY FORMAT\n"
                "  Each line shows:\n"
                "    [★ if boss]  pi=<part_index>  <original> → <new>"
                "  [tier]\n"
                "\n"
                "  part_index is the MSB Part index — useful for "
                "correlating with EMEVD references or debug logs.\n"
            ),
        },
    }

    def _show_tab_help(self, tab_key, event=None):
        """Open a modal showing TAB_HELP_CONTENT for the given key.
        Same Toplevel pattern as _show_shortcuts_cheatsheet — Esc closes,
        always-on-top, centered near the main window."""
        entry = self.TAB_HELP_CONTENT.get(tab_key)
        if entry is None:
            # No content registered for this tab — silently no-op
            # rather than showing an empty modal
            return 'break'
        modal = tk.Toplevel(self.root)
        modal.title(f"Help — {entry['title']}")
        modal.transient(self.root)
        try:
            modal.grab_set()
        except tk.TclError:
            pass
        try:
            x = self.root.winfo_rootx() + 80
            y = self.root.winfo_rooty() + 60
            modal.geometry(f'620x540+{x}+{y}')
        except tk.TclError:
            modal.geometry('620x540')

        outer = ttk.Frame(modal, padding=14); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text=entry['title'],
                  font=(self.ui_font, 13, 'bold')).pack(anchor='w')
        ttk.Label(outer,
            text="Press Esc to close, or use the Close button below.",
            style='Dim.TLabel').pack(anchor='w', pady=(0, 8))

        # Body — scrolledtext so long help fits
        body = scrolledtext.ScrolledText(
            outer, wrap='word', state='normal',
            font=(self.ui_font, 10),
            bg=THEME.get('surface_alt', '#262626'),
            fg=THEME.get('text', '#e0e0e0'),
            relief='flat', borderwidth=0, padx=10, pady=8)
        body.pack(fill='both', expand=True, pady=(0, 8))
        body.insert('1.0', entry['body'])
        # Style headers (ALL-CAPS lines at column 0)
        body.tag_configure('section',
            font=(self.ui_font, 10, 'bold'),
            foreground=THEME.get('accent', '#d4a017'))
        for line_num, line in enumerate(entry['body'].splitlines(), start=1):
            if line and line == line.upper() and not line.startswith(' '):
                body.tag_add('section', f'{line_num}.0',
                              f'{line_num}.end')
        body.configure(state='disabled')

        btn_row = ttk.Frame(outer); btn_row.pack(fill='x')
        close_btn = ttk.Button(btn_row, text="Close",
                                command=modal.destroy)
        close_btn.pack(side='right')
        modal.bind('<Escape>', lambda _e: modal.destroy())
        close_btn.focus_set()
        return 'break'

    def _add_help_button(self, parent, tab_key):
        """Pack a small '?' help button to the right of parent. Click
        opens _show_tab_help for the matching tab. Used by each
        _build_*_tab that wants a help affordance."""
        btn = ttk.Button(parent, text="?",
                          width=3,
                          command=lambda: self._show_tab_help(tab_key))
        btn.pack(side='right', padx=(0, 8))
        Tooltip(btn,
                "Open the help overlay for this tab. Explains what "
                "each section is for and how to use it.")
        return btn

    def _show_shortcuts_cheatsheet(self, event=None):
        """F1: show a modal listing all keyboard shortcuts. Built
        from KEYBOARD_SHORTCUTS so it can never go stale relative
        to the actual bindings — adding a shortcut updates the
        cheatsheet automatically."""
        modal = tk.Toplevel(self.root)
        modal.title("Keyboard shortcuts")
        modal.transient(self.root)
        try:
            modal.grab_set()
        except tk.TclError:
            pass  # if the root is already busy with another modal
        # Center near the main window
        try:
            x = self.root.winfo_rootx() + 80
            y = self.root.winfo_rooty() + 80
            modal.geometry(f'+{x}+{y}')
        except tk.TclError:
            pass
        outer = ttk.Frame(modal, padding=14); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text="Keyboard shortcuts",
                  font=(self.ui_font, 13, 'bold')).pack(anchor='w')
        ttk.Label(outer,
            text="Bindings work from anywhere in the window.",
            style='Dim.TLabel').pack(anchor='w', pady=(0, 10))
        # Build a two-column grid: shortcut on left, action on right
        grid = ttk.Frame(outer); grid.pack(fill='x', pady=(0, 10))
        for i, (combo, _, description, _) in enumerate(self.KEYBOARD_SHORTCUTS):
            ttk.Label(grid, text=combo, width=16,
                       font=(self.mono_font, 10, 'bold')
                       ).grid(row=i, column=0, sticky='w', padx=(0, 12))
            ttk.Label(grid, text=description, justify='left'
                       ).grid(row=i, column=1, sticky='w')
        # Close button
        btn_row = ttk.Frame(outer); btn_row.pack(fill='x', pady=(4, 0))
        close_btn = ttk.Button(btn_row, text="Close",
                                command=modal.destroy)
        close_btn.pack(side='right')
        # Esc closes the modal too
        modal.bind('<Escape>', lambda _e: modal.destroy())
        close_btn.focus_set()
        return 'break'

    def _force_include_options(self):
        """v0.23.05: Build the picker list for the force-include autocomplete.

        Returns a list of display strings, one per c-prefix that:
          - is tagged with a tier in V3_BOSS_STRENGTH_TIERS, AND
          - is currently in V3_EXCLUDE_TARGET_PREFIXES or
            V3_GHOST_EXCLUDE_TARGET_PREFIXES (not hard-excluded — those
            placeholders/dummy c-prefixes don't have working models).

        Each display string is formatted as
          "c4500 — Flying Dragon (field_boss) [target-only]"
        so the user sees the c-prefix, the chr name, the tier, and the
        exclusion class. The autocomplete substring filter matches any of
        those tokens.
        """
        try:
            from oops_v3 import (V3_BOSS_STRENGTH_TIERS,
                                  V3_EXCLUDE_PREFIXES,
                                  V3_EXCLUDE_TARGET_PREFIXES,
                                  V3_GHOST_EXCLUDE_TARGET_PREFIXES)
        except ImportError:
            return []
        opts = []
        for cp, t in self.tags.items():
            tier = t.get('tier', '?')
            if tier not in V3_BOSS_STRENGTH_TIERS:
                continue
            # Skip hard-excludes (placeholder/dummy c-prefixes)
            if cp in V3_EXCLUDE_PREFIXES:
                continue
            # Only show currently-excluded targets — already-eligible chrs
            # don't need force-include (they're already in the pool).
            classes = []
            if cp in V3_EXCLUDE_TARGET_PREFIXES:
                classes.append('target-only')
            if cp in V3_GHOST_EXCLUDE_TARGET_PREFIXES:
                classes.append('ghost-exclude')
            if not classes:
                continue
            name = t.get('name', '?')
            opts.append(f"{cp} — {name} ({tier}) [{', '.join(classes)}]")
        return sorted(opts)

    def _force_include_add(self):
        """Pull the c-prefix out of the picker entry, append to list, refresh UI."""
        text = (self.force_include_picker_var.get() or '').strip()
        if not text:
            return
        # First token is the c-prefix (display format starts with "c1234 —…")
        import re
        m = re.match(r'^(c\d{2,5})', text)
        if not m:
            return
        cp = m.group(1)
        if cp in self.force_include_targets:
            self.force_include_picker_var.set("")
            return
        self.force_include_targets.append(cp)
        self.force_include_targets.sort()
        self.force_include_picker_var.set("")
        self._refresh_force_include_label()

    def _force_include_remove_last(self):
        if self.force_include_targets:
            self.force_include_targets.pop()
            self._refresh_force_include_label()

    def _force_include_clear(self):
        self.force_include_targets = []
        self._refresh_force_include_label()

    def _refresh_force_include_label(self):
        if not self.force_include_targets:
            self.force_include_label.config(text="(none — vanilla pool)",
                                             style='Dim.TLabel')
            return
        # Show "c4500 (Flying Dragon), c4910 (Magma Wyrm), …"
        parts = []
        for cp in self.force_include_targets:
            nm = self.tags.get(cp, {}).get('name', '?')
            parts.append(f"{cp} ({nm})")
        self.force_include_label.config(text=", ".join(parts),
                                         style='TLabel')

    def _apply_theme(self):
        """Apply dark theme + bonfire-amber accent across ttk and tk widgets."""
        self.mono_font = _pick_mono_font()
        self.ui_font = _pick_ui_font()

        T = THEME
        self.root.configure(bg=T['bg'])

        style = ttk.Style()
        # 'clam' is the most themable built-in ttk theme — others lock down colors
        try: style.theme_use('clam')
        except tk.TclError: pass

        # Base widget classes
        style.configure('.',
            background=T['bg'], foreground=T['text'],
            fieldbackground=T['surface_alt'], bordercolor=T['border'],
            lightcolor=T['border'], darkcolor=T['border'],
            insertcolor=T['text'],
            font=(self.ui_font, 10))

        style.configure('TFrame', background=T['bg'])
        style.configure('TLabel', background=T['bg'], foreground=T['text'])
        style.configure('Dim.TLabel', background=T['bg'], foreground=T['text_dim'])
        style.configure('Faint.TLabel', background=T['bg'], foreground=T['text_faint'])
        style.configure('Accent.TLabel', background=T['bg'], foreground=T['accent'],
                        font=(self.ui_font, 10, 'bold'))
        style.configure('Header.TLabel', background=T['bg'], foreground=T['accent'],
                        font=(self.ui_font, 18, 'bold'))
        style.configure('Subheader.TLabel', background=T['bg'], foreground=T['text_dim'],
                        font=(self.ui_font, 10))

        style.configure('TLabelframe', background=T['bg'],
                        bordercolor=T['border'], relief='solid', borderwidth=1)
        style.configure('TLabelframe.Label', background=T['bg'],
                        foreground=T['accent'], font=(self.ui_font, 10, 'bold'))

        style.configure('TButton',
            background=T['surface'], foreground=T['text'],
            bordercolor=T['border'], focuscolor=T['accent'],
            relief='flat', padding=(10, 6))
        style.map('TButton',
            background=[('active', T['surface_alt']), ('pressed', T['border'])],
            foreground=[('disabled', T['text_faint'])])

        # Bonfire-styled run button
        style.configure('Accent.TButton',
            background=T['accent'], foreground='#1a1a1d',
            bordercolor=T['accent'], focuscolor=T['accent_hi'],
            relief='flat', padding=(14, 10),
            font=(self.ui_font, 11, 'bold'))
        style.map('Accent.TButton',
            background=[('active', T['accent_hi']), ('disabled', T['accent_dim'])],
            foreground=[('disabled', T['surface'])])

        style.configure('TEntry',
            fieldbackground=T['surface_alt'], foreground=T['text'],
            bordercolor=T['border'], insertcolor=T['text'],
            relief='flat', padding=4)

        # Combobox: by default tkinter uses system colors which clash with
        # our dark theme (white field, blue selection highlight). Force dark.
        style.configure('TCombobox',
            fieldbackground=T['surface_alt'], background=T['surface'],
            foreground=T['text'], bordercolor=T['border'],
            arrowcolor=T['text_dim'], insertcolor=T['text'],
            relief='flat', padding=4,
            selectbackground=T['surface_alt'], selectforeground=T['text'])
        style.map('TCombobox',
            fieldbackground=[('readonly', T['surface_alt']),
                             ('disabled', T['surface'])],
            foreground=[('readonly', T['text']),
                        ('disabled', T['text_faint'])],
            selectbackground=[('readonly', T['surface_alt']),
                              ('!readonly', T['surface_alt'])],
            selectforeground=[('readonly', T['text']),
                              ('!readonly', T['text'])],
            arrowcolor=[('active', T['accent']),
                        ('!active', T['text_dim'])],
            bordercolor=[('focus', T['accent'])])
        # The dropdown POPUP (the list shown when expanded) is a Listbox, not
        # a ttk widget — needs option_add to style.
        self.root.option_add('*TCombobox*Listbox.background', T['surface_alt'])
        self.root.option_add('*TCombobox*Listbox.foreground', T['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', T['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#1a1a1d')
        self.root.option_add('*TCombobox*Listbox.borderWidth', 0)
        self.root.option_add('*TCombobox*Listbox.highlightThickness', 0)

        style.configure('TRadiobutton',
            background=T['bg'], foreground=T['text'])
        style.map('TRadiobutton',
            background=[('active', T['bg'])],
            foreground=[('active', T['accent'])])

        style.configure('TNotebook', background=T['bg'], borderwidth=0,
                        tabmargins=[2, 4, 2, 0])
        style.configure('TNotebook.Tab',
            background=T['surface'], foreground=T['text_dim'],
            bordercolor=T['border'], padding=[14, 6],
            font=(self.ui_font, 10))
        style.map('TNotebook.Tab',
            background=[('selected', T['bg']), ('active', T['surface_alt'])],
            foreground=[('selected', T['accent']), ('active', T['text'])],
            expand=[('selected', [1, 1, 1, 0])])

        style.configure('Vertical.TScrollbar',
            background=T['surface'], troughcolor=T['bg'],
            bordercolor=T['border'], arrowcolor=T['text_dim'],
            relief='flat')
        style.configure('Horizontal.TScrollbar',
            background=T['surface'], troughcolor=T['bg'],
            bordercolor=T['border'], arrowcolor=T['text_dim'],
            relief='flat')

        # Default options for raw tk widgets (Listbox, Text — these aren't ttk)
        self.root.option_add('*Listbox.background', T['surface_alt'])
        self.root.option_add('*Listbox.foreground', T['text'])
        self.root.option_add('*Listbox.selectBackground', T['accent'])
        self.root.option_add('*Listbox.selectForeground', '#1a1a1d')
        self.root.option_add('*Listbox.borderWidth', 0)
        self.root.option_add('*Listbox.highlightThickness', 0)
        self.root.option_add('*Listbox.font', (self.mono_font, 10))

    def _load_data(self):
        # v0.23.71: route through _data_path() so JSONs resolve from
        # data/ when present (the v0.23.71+ layout) and fall back to
        # the project root for older installs.
        roster_path = _data_path('nr_enemy_roster.json')
        tags_path = _data_path('nr_enemy_tags.json')
        missing = [p for p in (roster_path, tags_path) if not os.path.exists(p)]
        if missing:
            here = os.path.dirname(os.path.abspath(__file__))
            messagebox.showerror("Rando data files missing",
                f"The rando can't find its core data files. Missing:\n"
                + "\n".join(f"  {p}" for p in missing) + "\n\n"
                f"This means the rando's data/ folder is incomplete. Most "
                f"likely the download or extraction missed some files.\n\n"
                f"Expected layout in: {here}\n"
                f"  oops_rando_gui.py\n"
                f"  oops_v3.py\n"
                f"  data/\n"
                f"    nr_enemy_roster.json   ← missing\n"
                f"    nr_enemy_tags.json     ← missing\n"
                f"    nr_boss_slots.json\n"
                f"    ... (other data files)\n\n"
                f"Re-download or re-extract the rando archive. If the files "
                f"are present elsewhere, copy them into the data/ folder "
                f"next to oops_rando_gui.py.")
            self.roster = None
            self.tags = None
            return
        with open(roster_path, encoding='utf-8') as f: self.roster = json.load(f)
        with open(tags_path, encoding='utf-8') as f: self.tags = json.load(f)
        # Build display strings: "c4070  Wolf  loco=0 size=S"
        names_by_cp = {}
        for v in self.roster.get('all_variants', []):
            cp = v['c_prefix']
            names_by_cp.setdefault(cp, set()).add(v.get('variant_name', '?'))
        for cp, names in sorted(names_by_cp.items()):
            t = self.tags.get(cp, {})
            # v0.23.44: prefer the tag's authoritative `name` field for the
            # display label. Falling back to alphabetically-first variant
            # name picks the wrong one when a c-prefix has unrelated minor
            # variants — e.g. c6200's MMV import is Slave Knight Gael but
            # one of its variants is named "Scarab" (cross-c-prefix naming
            # collision in the modded dump). The tag name is hand-curated
            # for headline c-prefixes; falling back to variant names only
            # when the tag has no name keeps the picker labels accurate.
            tag_name = (t.get('name') if isinstance(t, dict) else None) or ''
            if tag_name and not tag_name.startswith('c') and tag_name != '?':
                display_name = tag_name
            else:
                display_name = sorted(names)[0] if names else '?'
            self.prefix_display[cp] = (
                f"{cp}  {display_name}  "
                f"loco={t.get('locomotion','?')} "
                f"size={t.get('size_class','?')}"
            )

    def _build_ui(self):
        # Header strip
        header = ttk.Frame(self.root, padding=(16, 14, 16, 6))
        header.pack(fill='x')
        ttk.Label(header, text="4laric's Nightreign Enemy Randomizer",
                  style='Header.TLabel').pack(anchor='w')
        ttk.Label(header,
                  text="Vanilla-aware enemy shuffle  ·  EMEVD-aware",
                  style='Subheader.TLabel').pack(anchor='w', pady=(2, 0))

        # Subtle separator under header
        sep = tk.Frame(self.root, height=1, bg=THEME['border'])
        sep.pack(fill='x', padx=16, pady=(6, 0))

        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True, padx=12, pady=(8, 0))
        # v0.23.72-late: expose for the compatibility banner's jump-to-tab.
        self.nb = nb

        # Tab 1: main controls
        tab1 = ttk.Frame(nb)
        nb.add(tab1, text='  Generate  ')
        self._progress_callback('Building Generate tab…')
        self._build_main_tab(tab1)

        # Tab 1b (v0.24.10): individual folder pickers, moved off the
        # Generate tab so the front page is just Game install + me3
        # package. Anyone whose layout doesn't match the convention
        # can override individual derived paths here.
        tab_paths = ttk.Frame(nb)
        nb.add(tab_paths, text='  Paths  ')
        self._build_paths_tab(tab_paths)

        # Tab 2: excluded enemies
        tab2 = ttk.Frame(nb)
        nb.add(tab2, text='  Excluded Enemies  ')
        self._build_excluded_tab(tab2)

        # Tab 3: hub maps (advanced)
        tab3 = ttk.Frame(nb)
        nb.add(tab3, text='  Hub Maps  ')
        self._build_hub_tab(tab3)

        # Tab 4: heritage / multiplayer
        tab_h = ttk.Frame(nb)
        nb.add(tab_h, text='  Heritage / Multiplayer  ')
        self._progress_callback('Building Heritage tab…')
        self._build_heritage_tab(tab_h)

        # Tab 5: ER asset import — heritage chr + script file import for me3 profile
        tab_chr = ttk.Frame(nb)
        nb.add(tab_chr, text='  Elden Ring Assets  ')
        self._progress_callback('Building Elden Ring Assets tab…')
        self._build_chr_inventory_tab(tab_chr)

        # v0.26.x: Tier 3 UX #11 — Spoiler viewer. Loads the engine's
        # _spoilers.json output and renders a filterable, searchable
        # by-map listing of every swap. The post-run summary panel
        # already shows the spoiler path with an Open button (which
        # opens raw JSON in a text editor); this tab is the better
        # interactive alternative.
        tab_spoiler = ttk.Frame(nb)
        nb.add(tab_spoiler, text='  Spoiler  ')
        self._build_spoiler_tab(tab_spoiler)

        # Tab 6: about
        tab4 = ttk.Frame(nb)
        nb.add(tab4, text='  About  ')
        self._build_about_tab(tab4)

        # Status bar
        statusbar = tk.Frame(self.root, bg=THEME['surface'], height=24)
        statusbar.pack(fill='x', side='bottom')
        statusbar.pack_propagate(False)
        ttk.Label(statusbar, textvariable=self.status_var,
                  style='Faint.TLabel',
                  background=THEME['surface']).pack(side='left', padx=12)
        ttk.Label(statusbar, text="v0.20.90 — 4laric",
                  style='Faint.TLabel',
                  background=THEME['surface']).pack(side='right', padx=12)
        # v0.26.x: shortcut discovery hint. Clickable so a casual
        # click also opens the cheatsheet — Tk doesn't natively make
        # Labels look clickable so users may not realize it works,
        # but the F1 hint itself is the primary discovery path.
        shortcuts_hint = ttk.Label(statusbar, text="F1 for shortcuts",
                                    style='Faint.TLabel', cursor='hand2',
                                    background=THEME['surface'])
        shortcuts_hint.pack(side='right', padx=(0, 16))
        shortcuts_hint.bind('<Button-1>',
                             lambda _e: self._show_shortcuts_cheatsheet())

    def _build_main_tab(self, parent):
        # v0.19.27 / v0.24.0: wrap the main tab in a scrollable canvas.
        # Even with the v0.24.0 front-page cleanup (Run flavor, EMEVD
        # patches, Force-include sections removed), the tab still
        # exceeds typical window heights once tier modes + multiplayer-
        # safe + run button + output log stack up.
        # We build a Canvas + ttk.Scrollbar pair, embed a Frame inside
        # the canvas as the content host, and rebind `parent` to that
        # frame so the rest of the function (unchanged) builds inside it.
        # Mousewheel bindings activate while the cursor is over the
        # canvas region — Enter/Leave swaps the global wheel handler on
        # and off so other tabs (Excluded, Hub Maps) keep their own
        # listbox-scroll behavior.
        scroll_canvas = tk.Canvas(parent, highlightthickness=0,
                                   bg=THEME['bg'])
        vsb = ttk.Scrollbar(parent, orient='vertical',
                             command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        scroll_canvas.pack(side='left', fill='both', expand=True)

        scroll_frame = ttk.Frame(scroll_canvas)
        scroll_window = scroll_canvas.create_window(
            (0, 0), window=scroll_frame, anchor='nw')

        def _on_frame_configure(_e=None):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox('all'))
        scroll_frame.bind('<Configure>', _on_frame_configure)

        def _on_canvas_configure(event):
            # Stretch the inner frame to the canvas width so labels wrap
            # naturally and don't get clipped at small window sizes.
            scroll_canvas.itemconfig(scroll_window, width=event.width)
        scroll_canvas.bind('<Configure>', _on_canvas_configure)

        def _on_mousewheel(event):
            # Cross-platform wheel handling: Windows/macOS use event.delta
            # (positive = up), Linux uses Button-4/Button-5 events.
            if event.num == 4 or (getattr(event, 'delta', 0) > 0):
                scroll_canvas.yview_scroll(-1, 'units')
            elif event.num == 5 or (getattr(event, 'delta', 0) < 0):
                scroll_canvas.yview_scroll(1, 'units')

        def _bind_wheel(_e=None):
            scroll_canvas.bind_all('<MouseWheel>', _on_mousewheel)
            scroll_canvas.bind_all('<Button-4>', _on_mousewheel)
            scroll_canvas.bind_all('<Button-5>', _on_mousewheel)

        def _unbind_wheel(_e=None):
            scroll_canvas.unbind_all('<MouseWheel>')
            scroll_canvas.unbind_all('<Button-4>')
            scroll_canvas.unbind_all('<Button-5>')

        scroll_canvas.bind('<Enter>', _bind_wheel)
        scroll_canvas.bind('<Leave>', _unbind_wheel)

        # Rebind parent so the rest of this function builds inside the
        # scrollable frame instead of the raw tab.
        parent = scroll_frame

        # v0.26.x: Setup Status panel (Tier 1 UX #1) — environment
        # readiness checklist at the very top of the tab. Lists Python,
        # Tk, Oodle DLL, NR install, ER install, ME3 output with
        # v0.26.x: per-tab help button (Tier 2 UX continuation).
        # Slim row at the top so the affordance is discoverable
        # without taking visual real estate from the Setup Status
        # panel below.
        help_row = ttk.Frame(parent)
        help_row.pack(fill='x', padx=8, pady=(8, 0))
        self._add_help_button(help_row, 'generate')

        # ✓/✗/⚠ indicators. Refreshes on every path-field change so it
        # stays current as the user configures. The compat banner below
        # covers a different axis (chr deployment state, not env readiness).
        self._setup_status_frame = ttk.LabelFrame(
            parent, text="Setup Status", padding=6)
        self._setup_status_frame.pack(fill='x', padx=8, pady=(8, 0))
        self._build_setup_status_panel()
        self._refresh_setup_status()

        # v0.23.72-late: compatibility banner — surfaces failed/warned
        # checks before the user starts generating. Pulls from oops_v3's
        # compatibility_preflight(); the chr/ Inventory tab's existing
        # Asset Packs panel gives deeper detail, so this is just a
        # headline + jump-to-tab affordance.
        self._compat_banner_frame = ttk.Frame(parent)
        self._compat_banner_frame.pack(fill='x', padx=8, pady=(8, 0))
        self._refresh_compat_banner()

        # v0.26.x: recommended-expedition banner. Surfaces the
        # "use Tricephalos until other Nightlord arenas are validated"
        # guidance so new users see it BEFORE they pick a Nightlord
        # in-game. Dismissable; the dismissal persists across launches
        # so a power user only sees it once.
        self._recommended_expedition_frame = ttk.Frame(parent)
        self._recommended_expedition_frame.pack(fill='x', padx=8, pady=(8, 0))
        self._refresh_recommended_expedition_banner()

        # Seed + run mode row
        f1 = ttk.LabelFrame(parent, text="Seed & Mode", padding=8)
        f1.pack(fill='x', padx=8, pady=(8, 4))

        row = ttk.Frame(f1); row.pack(fill='x')
        ttk.Label(row, text="Seed:").pack(side='left')
        seed_entry = ttk.Entry(row, textvariable=self.seed_var, width=12)
        seed_entry.pack(side='left', padx=(4, 0))
        Tooltip(seed_entry,
                "Same seed + same options = same randomized result. "
                "Share a seed to swap runs with a friend, or fix one "
                "for testing. Non-numeric text gets hashed to an int.")
        random_btn = ttk.Button(row, text="🎲 Random",
                                command=self._random_seed)
        random_btn.pack(side='left', padx=(4, 16))
        Tooltip(random_btn,
                "Roll a fresh random seed into the Seed field. "
                "Doesn't run the rando — click Randomize after.")
        ttk.Label(row, text="Mode:").pack(side='left')
        mode_combo = ttk.Combobox(row, textvariable=self.run_mode_var,
                                   values=["Standard", "Oops! All …",
                                           "Oops! All NB (boss probe) …",
                                           "Validation: rats / jellies"],
                                   state='readonly', width=32)
        mode_combo.pack(side='left', padx=4)
        Tooltip(mode_combo,
                "Standard: normal seeded randomization across all slots.\n"
                "Oops! All …: replace EVERY slot with one chosen enemy "
                "(picker below).\n"
                "Oops! All NB: like Oops! All, but only Night Boss-tier "
                "slots get the target — for testing one boss at a time.\n"
                "Validation: rats/jellies: smoke-test mode that fills "
                "the world with low-CTD-risk enemies. Use to confirm "
                "the engine works end-to-end after a config change.")
        mode_combo.bind('<<ComboboxSelected>>', lambda *_: self._on_mode_change())
        # v0.26.x: stickiness guards. A readonly Combobox flips on mouse-
        # wheel scroll and on up/down arrows whenever it has focus — easy
        # to trigger by accident while scrolling the window, which
        # silently switches the run into a destructive Oops! All mode.
        # Eat scroll-wheel events on the combobox (return 'break' so they
        # don't change the selection — the window still scrolls because
        # the event isn't consumed at the parent). The confirmation
        # dialog in the mode-change handler is the backstop for an
        # accidental keyboard change.
        def _eat_scroll(_e):
            return 'break'
        mode_combo.bind('<MouseWheel>', _eat_scroll)   # Windows / macOS
        mode_combo.bind('<Button-4>', _eat_scroll)      # Linux scroll up
        mode_combo.bind('<Button-5>', _eat_scroll)      # Linux scroll down
        self._mode_combo = mode_combo

        # (Multiplayer-safe / heritage controls live on their own tab now —
        # see _build_heritage_tab. The main tab focuses on the most-used
        # generation knobs.)

        # v0.19.27: cluster-aware and merchant-model toggles removed from
        # the main tab to keep the UI compact. Their BooleanVars still
        # exist and are read into the config dict — defaults are now the
        # right values for almost everyone (cluster_aware=False for max
        # variety per encampment, merchant_model_swap=True for the visual
        # variety it adds without breaking shop function). Anyone who
        # wants to flip them can edit the BooleanVar `value=` in the
        # __init__ block. Config dict pickup is unchanged.

        # Oops! All target picker — only shown when mode is "Oops! All …"
        self.oops_all_frame = ttk.Frame(f1)
        # (packed/unpacked dynamically by _on_mode_change)
        ttk.Label(self.oops_all_frame, text="Replace everything with:",
                  style='Dim.TLabel').pack(side='left')
        # Build the picker list — c-prefix + display name, sorted
        self.oops_all_options = []  # list of display strings
        self.oops_all_lookup = {}   # display string → c_prefix
        for cp, display in sorted(self.prefix_display.items()):
            self.oops_all_options.append(display)
            self.oops_all_lookup[display] = cp
        self.oops_all_combo = AutocompleteCombobox(
            self.oops_all_frame, textvariable=self.oops_all_target_var,
            state='normal', width=50)
        self.oops_all_combo.set_completion_list(self.oops_all_options)
        self.oops_all_combo.pack(side='left', padx=8, fill='x', expand=True)
        Tooltip(self.oops_all_combo,
                "Pick the enemy that replaces every slot in the world. "
                "Type to filter — the picker shows c-prefix + display "
                "name (e.g. 'c5070 Death Knight'). If the chosen enemy "
                "has no variant compatible with a given slot's tier, "
                "the engine falls back to vanilla random for that slot.")

        # v0.23.39: NB-only oops-all picker — only shown when mode is
        # "Oops! All NB (boss probe) …". Lets the user pick a c-prefix to
        # force at every Night-Boss-tier slot under a selectable scope.
        self.oops_all_nb_frame = ttk.Frame(f1)
        # (packed/unpacked dynamically by _on_mode_change)
        ttk.Label(self.oops_all_nb_frame, text="Replace boss-tier slots with:",
                  style='Dim.TLabel').pack(side='left')
        # Reuse the same option list as the global oops-all picker — every
        # c-prefix is a valid candidate; if the picked chr has no NB-tier
        # variant, the engine falls through to vanilla random for that slot.
        self.oops_all_nb_combo = AutocompleteCombobox(
            self.oops_all_nb_frame, textvariable=self.oops_all_nb_target_var,
            state='normal', width=42)
        self.oops_all_nb_combo.set_completion_list(self.oops_all_options)
        self.oops_all_nb_combo.pack(side='left', padx=8, fill='x', expand=True)
        Tooltip(self.oops_all_nb_combo,
                "Pick the boss to force at every Night Boss-tier slot "
                "in the run. Non-boss slots still randomize normally. "
                "Useful for testing one boss's compatibility across "
                "every arena it could spawn in.")
        # Scope picker — strict / broad / extended.
        ttk.Label(self.oops_all_nb_frame, text="Scope:",
                  style='Dim.TLabel').pack(side='left', padx=(8, 2))
        self.oops_all_nb_scope_combo = ttk.Combobox(
            self.oops_all_nb_frame, textvariable=self.oops_all_nb_scope_var,
            values=['strict', 'broad', 'extended'],
            state='readonly', width=10)
        self.oops_all_nb_scope_combo.pack(side='left')
        Tooltip(self.oops_all_nb_scope_combo,
                "Which boss-tier slots get force-replaced.\n"
                "strict: Night Boss anchors only (the canonical 8 arenas).\n"
                "broad: + Field bosses + POI bosses (encampments, etc.).\n"
                "extended: + Castle interior + Basement + Cathedrals + "
                "Mountaintop + Underground Forts + Group Bosses + bare "
                "(Boss) Nightlord forms.")
        # Inline help — one line, dim style.
        scope_help = ttk.Frame(f1)
        self._oops_all_nb_help_frame = scope_help  # toggled with the picker
        ttk.Label(scope_help,
            text=("strict ≈ NB anchors only  ·  broad ≈ NB+Field+POI bosses  "
                  "·  extended ≈ broad + Castle interior + Basement + "
                  "Encampments + Cathedrals + Mountaintop + Underground "
                  "Forts + Group Bosses + bare (Boss) Nightlord forms"),
            style='Dim.TLabel').pack(side='left', padx=(2, 0))

        # Directory pickers
        f2 = ttk.LabelFrame(parent, text="Folders", padding=8)
        f2.pack(fill='x', padx=8, pady=4)

        # v0.27.0: auto-collapsing Folders box. When every path row is
        # non-red (ok / warn / unknown — i.e. nothing actually broken),
        # the rows collapse behind a one-line summary header so the
        # front page stays compact; the box re-expands itself the
        # moment any row goes red. A manual click on the header always
        # overrides the auto-state until the next red transition.
        # All rows live in _folders_body so a single pack_forget hides
        # the lot. _folders_header is the always-visible clickable line.
        self._folders_header = ttk.Label(
            f2, cursor='hand2', style='Dim.TLabel',
            font=(_pick_ui_font(), 9))
        self._folders_header.pack(fill='x')
        self._folders_body = ttk.Frame(f2)
        self._folders_body.pack(fill='x')
        # State: None = follow auto rule; True/False = user-pinned.
        self._folders_user_pinned = None
        self._folders_collapsed = False
        self._folders_header.bind(
            '<Button-1>', self._toggle_folders_collapse)
        # Rows pack into the body frame, not f2 directly.
        _folders_parent = self._folders_body

        # v0.24.9: TWO TOP-LEVEL PARENT PATHS. Pick these once and the
        # rando derives every other path below (vanilla map/event/chr/msg
        # from <game>, and the matching mod sides from <me3>) so the
        # user doesn't have to bounce around through individual picker
        # rows. The derived rows stay visible below as overrides — if
        # a user's UXM-unpacked layout doesn't match the convention,
        # they can fix the specific path that's wrong without redoing
        # the others.
        for label, var, tip, kind, autodetect_key in [
            ("Nightreign install:", self.game_install_var,
             "Path to your UXM-unpacked NIGHTREIGN install (typically "
             "<install>/Game/). The rando derives Vanilla map / event / "
             "msg paths from this. This is NOT the Elden Ring install — "
             "those paths are below.",
             'nr_install', 'game_install'),
            ("Elden Ring install:", self.er_install_var,
             "Path to your UXM-unpacked ELDEN RING install (typically "
             "<install>/Game/). Used by the chr-asset-import tool to "
             "copy heritage chrs (Death Knight, Banished Knight, etc.) "
             "into the me3 mod profile. NR doesn't ship these chrs — "
             "they have to come from an ER install. Leave blank if you "
             "aren't using heritage chr imports.",
             'er_install', 'er_install'),
            ("me3 package:", self.me3_package_var,
             "Path to the active me3 mod package (typically "
             "<me3 profile>/<package>/). The rando derives Mod map/event/"
             "chr/msg paths from this.",
             'me3_profile', None),
            ("me3 launcher:", self.me3_launcher_var,
             "Path to the me3 launcher binary (me3.exe / me3 / "
             "modengine2_launcher.exe). The 'Launch NR' button uses "
             "this to start Nightreign with your mod profile loaded. "
             "Auto-discovered when possible — only set this manually "
             "if me3 is installed in a non-standard location.",
             'me3_launcher_exe', 'me3_launcher'),
        ]:
            row = ttk.Frame(_folders_parent); row.pack(fill='x', pady=2)
            ttk.Label(row, text=label, width=18).pack(side='left')
            # v0.26.x: live status indicator (Tier 1 UX #3). Updates on
            # every value change via _refresh_path_indicators.
            indicator = StatusIndicator(row)
            indicator.pack(side='left', padx=(0, 4))
            self._register_path_indicator(indicator, var, kind)
            ttk.Entry(row, textvariable=var).pack(
                side='left', fill='x', expand=True, padx=4)
            # v0.26.x: file vs directory picker. me3_launcher is the
            # only file-kind row in this loop — every other path is a
            # directory. Use askopenfilename for the file kind.
            if kind == 'me3_launcher_exe':
                browse_cmd = lambda v=var: self._browse_file(
                    v, title='Select me3 launcher',
                    filetypes=[('me3 launcher',
                                'me3.exe modengine2_launcher.exe me3'),
                               ('All files', '*.*')])
            else:
                browse_cmd = lambda v=var: self._browse_dir(v)
            ttk.Button(row, text="Browse...",
                       command=browse_cmd).pack(side='left')
            # v0.26.x: Tier 2 UX #7 — "Create new…" button on the me3
            # package row. Lets new users scaffold a fresh me3 profile
            # without leaving the rando to do it manually. Only the
            # me3_profile row gets this button; the others are existing
            # installs the rando can't create from scratch.
            if kind == 'me3_profile':
                ttk.Button(row, text="Create new…",
                           command=self._create_me3_profile
                           ).pack(side='left', padx=(2, 0))
            # v0.26.x: Re-detect button + "(auto-detected)" badge for the
            # two root paths (Tier 1 UX #5). The me3 package isn't
            # auto-detectable from anywhere, so it gets neither.
            if autodetect_key:
                if not hasattr(self, '_autodetect_badge_labels'):
                    self._autodetect_badge_labels = {}
                badge = ttk.Label(row, text='', style='Dim.TLabel', width=15)
                badge.pack(side='left', padx=(4, 0))
                self._autodetect_badge_labels[autodetect_key] = badge
                ttk.Button(row, text="Re-detect",
                           command=lambda k=autodetect_key: self._redetect_path(k)
                           ).pack(side='left', padx=(2, 0))
                # When the user manually edits the field, clear the
                # auto-detected flag (so the badge disappears).
                var.trace_add('write',
                    lambda *_, k=autodetect_key: self._mark_manual_edit(k))
        cap = ttk.Frame(_folders_parent); cap.pack(fill='x', pady=(2, 4))
        ttk.Label(cap, text="    ", width=14).pack(side='left')
        ttk.Label(cap,
            text="(everything else — Vanilla/Mod map, event, chr, msg — derives from these. "
                 "Override individual paths on the Paths tab if your layout differs.)",
            style='Dim.TLabel', wraplength=580, justify='left').pack(side='left', padx=4)

        # v0.26.x: now that the indicators + badge labels exist, populate
        # them with their initial state. _apply_install_autodetect ran
        # before any of this so the StringVars already hold the saved-or-
        # detected values; the indicator widgets just need a first paint.
        # Subsequent updates fire automatically via the trace_add hooks
        # registered in _register_path_indicator and the badge mark/clear
        # callbacks.
        self._refresh_path_indicators()
        self._refresh_autodetect_badges()

        # v0.23.56: Spawn-pool source directory (optional, advanced).
        # MOVED in v0.23.64 to the Heritage / Multiplayer tab — it's an
        # advanced optional-content toggle, not a daily-use folder picker,
        # so it doesn't belong on the front-page Folders box. The
        # variable (self.spawn_pool_source_dir_var) is still wired into
        # generate_run; this front-page row was just the picker UI. New
        # location: Heritage / Multiplayer tab → "Vanilla mapstudio
        # (optional)" frame.

        # v0.24.0: Cinematic Chaos UI removed from front page (engine
        # flag chaos_mode_var still declared in __init__ and read by
        # generate_run; defaults to False, so the behavior matches an
        # un-toggled checkbox). If a hidden re-entry point is wanted
        # later, expose via a debug menu rather than top-level UI.

        # Run button — bonfire-amber accent
        f4 = ttk.Frame(parent, padding=8); f4.pack(fill='x')
        self.run_btn = ttk.Button(f4, text="⚙   Randomize",
                                   command=self._run_shuffle,
                                   style='Accent.TButton')
        self.run_btn.pack(side='left', fill='x', expand=True, ipady=2)
        Tooltip(self.run_btn,
                "Start the randomizer with the current seed + mode + "
                "paths. Becomes a Cancel button while running.\n\n"
                "Shortcut: Ctrl+R or F5")
        # v0.26.x: Tier 2 UX #6 — one-click launch through ME3.
        # Sits next to Randomize so the flow "Generate → Launch" is one
        # natural pair of buttons. Auto-detects me3 binary + the owning
        # .me3 profile from the configured me3_package path; disabled
        # when prerequisites aren't met, with the tooltip explaining why.
        self.launch_btn = ttk.Button(f4, text="🎮  Launch via ME3",
                                      command=self._launch_via_me3)
        self.launch_btn.pack(side='left', padx=(8, 0), ipady=2)
        # Tooltip + initial state populated by _refresh_launch_button_state,
        # which is called below and on every relevant path change.
        self._launch_btn_tooltip = Tooltip(self.launch_btn, 'Checking ME3…')
        self._refresh_launch_button_state()
        # Hook the same trace machinery the Setup Status panel uses, so
        # the button state stays in sync as the user fills in paths.
        for var in (self.me3_package_var,):
            var.trace_add('write',
                lambda *_: self._refresh_launch_button_state())
        # v0.26.x: companion "Launch after generate" checkbox. The flag
        # is read by _drain_log_queue's __DONE__ handler — if checked
        # AND the generate completed cleanly (not cancelled), kicks off
        # the same _launch_via_me3 path the button uses, but with
        # from_auto_launch=True so failures log quietly instead of
        # popping a modal over the freshly-finished run.
        self._auto_launch_check = ttk.Checkbutton(
            f4, text="Launch after generate",
            variable=self.auto_launch_after_generate_var)
        self._auto_launch_check.pack(side='left', padx=(8, 0))
        Tooltip(self._auto_launch_check,
                "When checked, a successful generate automatically "
                "launches NR through me3. Same as clicking Launch by "
                "hand. Cancelled runs don't auto-launch.")

        # v0.24.0: "EMEVD patches (optional)" and "Force-include excluded
        # targets (optional)" UI sections removed from front page. The
        # bug-fix EMEVDs are now folded into the standard install flow;
        # _install_prepatched_emevd / _apply_emevd_patches methods kept
        # in case a hidden re-entry is wanted later (advanced menu, CLI).
        # Engine plumbing for force_include_targets still wired in
        # __init__ -> generate_run; without the UI it stays empty so the
        # engine sees None, same as default.

        # v0.26.x: Tier 3 UX #10 — host frame for the post-run summary
        # panel. Stays empty until a successful generate populates it
        # via _render_run_summary. Living above the log puts it where
        # the user's eyes land after the worker finishes, instead of
        # buried below a scrolled-to-bottom log.
        self._summary_frame_host = ttk.Frame(parent)
        self._summary_frame_host.pack(fill='x', padx=8)

        # Log output
        f5 = ttk.LabelFrame(parent, text="Output", padding=4)
        f5.pack(fill='both', expand=True, padx=8, pady=(4, 8))
        # v0.26.x: Tier 3 UX #12 — header row with Copy/Clear log buttons.
        # When something goes wrong, the user needs to paste log content
        # into a support channel. Copy-log adds an environment-info
        # header (engine fingerprint, Python version, platform, configured
        # paths) so the recipient doesn't have to ask follow-up questions.
        log_header = ttk.Frame(f5)
        log_header.pack(fill='x', pady=(0, 2))
        ttk.Label(log_header, text="Log",
                  style='Dim.TLabel').pack(side='left', padx=(4, 0))
        ttk.Button(log_header, text="Clear",
                   command=self._clear_log).pack(side='right', padx=2)
        copy_btn = ttk.Button(log_header, text="📋 Copy log",
                              command=self._copy_log_to_clipboard)
        copy_btn.pack(side='right', padx=2)
        Tooltip(copy_btn,
                "Copies the full log to your clipboard, prefixed with "
                "environment info (engine version, paths, platform). "
                "Paste it into a Discord / GitHub issue when reporting "
                "a problem so the recipient doesn't have to ask "
                "follow-up questions.")
        self.log = scrolledtext.ScrolledText(
            f5, height=14, wrap='word', state='disabled',
            font=(self.mono_font, 10),
            bg=THEME['surface_alt'], fg=THEME['text'],
            insertbackground=THEME['text'],
            selectbackground=THEME['accent'], selectforeground='#1a1a1d',
            relief='flat', borderwidth=0, padx=8, pady=6)
        self.log.pack(fill='both', expand=True)
        # Color tags
        self.log.tag_configure('success', foreground=THEME['success'])
        self.log.tag_configure('warn',    foreground=THEME['warn'])
        self.log.tag_configure('error',   foreground=THEME['error'])
        self.log.tag_configure('info',    foreground=THEME['info'])
        self.log.tag_configure('dim',     foreground=THEME['text_dim'])
        self.log.tag_configure('accent',  foreground=THEME['accent'])
        self._log("Ready. Set folders and click Randomize.\n", 'dim')

    def _build_paths_tab(self, parent):
        """v0.24.10: every individual path picker lives here. Most users
        never need to touch this tab — set Game install and me3 package
        on the Generate tab and the rows below auto-derive. This tab
        exists for layouts that don't match the convention (heritage
        chr imports from a non-NR install, msg bundles in a non-default
        location, etc.) so users can override any single derived path
        without redoing the others.
        """
        # Helpful banner explaining what this tab is and isn't for.
        banner = ttk.Frame(parent, padding=(8, 8, 8, 0))
        banner.pack(fill='x')
        ttk.Label(banner,
            text="These paths auto-fill from Game install + me3 package on the Generate tab. "
                 "Edit individual rows here only if your layout differs from the convention.",
            style='Dim.TLabel', wraplength=720, justify='left').pack(side='left', anchor='w')
        self._add_help_button(banner, 'paths')

        # === Vanilla side ===
        f_van = ttk.LabelFrame(parent, text="Vanilla (read)", padding=8)
        f_van.pack(fill='x', padx=8, pady=(8, 4))
        for label, var, browse_cmd in [
            ("Vanilla MSBs:", self.input_dir_var,
             lambda v=self.input_dir_var: self._browse_dir(v)),
            ("Vanilla event/:", self.vanilla_emevd_dir_var,
             lambda v=self.vanilla_emevd_dir_var: self._browse_dir(v)),
            ("Vanilla chr/:", self.chr_source_dir_var,
             lambda v=self.chr_source_dir_var: self._browse_dir(v)),
            # v0.24.109: removed "Vanilla msg:" row. vanilla_msg_bundle_var
            # now derives silently from game_install_var via
            # _discover_msg_bundle_basename + _apply_msg_basename_derivation
            # (no user-facing widget). If the auto-discovery fails (NR
            # install isn't UXM-unpacked, msg/engUS/ missing, etc.) the
            # var stays empty and dcx_batch's Phase 2 splice no-ops —
            # Phase 3 fallback ("Crucible Knight and more") handles
            # everything cleanly.
        ]:
            row = ttk.Frame(f_van); row.pack(fill='x', pady=2)
            ttk.Label(row, text=label, width=16).pack(side='left')
            ttk.Entry(row, textvariable=var).pack(
                side='left', fill='x', expand=True, padx=4)
            ttk.Button(row, text="Browse...", command=browse_cmd).pack(side='left')

        # === Mod side ===
        f_mod = ttk.LabelFrame(parent, text="Mod (write)", padding=8)
        f_mod.pack(fill='x', padx=8, pady=4)
        for label, var, browse_cmd in [
            ("Output:", self.output_dir_var,
             lambda v=self.output_dir_var: self._browse_dir(v)),
            ("Mod map/mapstudio:", self.mod_map_dir_var,
             lambda v=self.mod_map_dir_var: self._browse_dir(v)),
            ("Mod event/:", self.output_emevd_dir_var,
             lambda v=self.output_emevd_dir_var: self._browse_dir(v)),
            ("Mod chr/:", self.chr_target_dir_var,
             lambda v=self.chr_target_dir_var: self._browse_dir(v)),
            # v0.24.109: removed "Mod msg:" row. mod_msg_bundle_var derives
            # silently from me3_package_var (see counterpart comment in
            # the Vanilla section above).
        ]:
            row = ttk.Frame(f_mod); row.pack(fill='x', pady=2)
            ttk.Label(row, text=label, width=16).pack(side='left')
            ttk.Entry(row, textvariable=var).pack(
                side='left', fill='x', expand=True, padx=4)
            ttk.Button(row, text="Browse...", command=browse_cmd).pack(side='left')

        # === Fallback (when splice can't be done) ===
        # v0.24.105: removed. Fallback nameId is now hardwired ON with
        # nameId 902130014 ("Crucible Knight and more") — see
        # FALLBACK_NAMEID at the Tk-var init site. No user-facing UI
        # for this anymore; if you want to change the fallback nameId,
        # edit that constant directly.

        # Footer note about derivation behavior
        foot = ttk.Frame(parent, padding=(8, 4, 8, 8))
        foot.pack(fill='x')
        ttk.Label(foot,
            text="Changing Game install or me3 package on the Generate tab overwrites "
                 "the corresponding fields here. Direct edits here persist until the next "
                 "parent-path change.",
            style='Dim.TLabel', wraplength=720, justify='left').pack(anchor='w')

    def _build_excluded_tab(self, parent):
        # Header / explanation
        h = ttk.Frame(parent, padding=8); h.pack(fill='x')
        ttk.Label(h, text="Enemies in this list will not appear as swap targets and their slots will stay vanilla.",
                  wraplength=800).pack(side='left', anchor='w')
        self._add_help_button(h, 'excluded')

        # Search bar
        s = ttk.Frame(parent, padding=(8, 4)); s.pack(fill='x')
        ttk.Label(s, text="Search:").pack(side='left')
        ttk.Entry(s, textvariable=self.search_var).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(s, text="Clear", command=lambda: self.search_var.set("")).pack(side='left')
        ttk.Button(s, text="Reset to default",
                   command=lambda: self._set_excluded(DEFAULT_EXCLUDED)).pack(side='left', padx=4)

        # Two-pane: All enemies (left) | Excluded (right)
        body = ttk.Frame(parent); body.pack(fill='both', expand=True, padx=8, pady=4)

        left = ttk.LabelFrame(body, text="Available", padding=4)
        left.pack(side='left', fill='both', expand=True, padx=(0,4))
        self.all_listbox = tk.Listbox(left, selectmode='extended', font=('Courier', 9))
        sb1 = ttk.Scrollbar(left, command=self.all_listbox.yview)
        self.all_listbox.config(yscrollcommand=sb1.set)
        sb1.pack(side='right', fill='y')
        self.all_listbox.pack(side='left', fill='both', expand=True)

        mid = ttk.Frame(body); mid.pack(side='left', padx=4, fill='y')
        ttk.Button(mid, text="Exclude →", command=self._exclude_selected).pack(pady=8)
        ttk.Button(mid, text="← Include", command=self._include_selected).pack()

        right = ttk.LabelFrame(body, text="Excluded", padding=4)
        right.pack(side='left', fill='both', expand=True, padx=(4,0))
        self.excluded_listbox = tk.Listbox(right, selectmode='extended', font=('Courier', 9))
        sb2 = ttk.Scrollbar(right, command=self.excluded_listbox.yview)
        self.excluded_listbox.config(yscrollcommand=sb2.set)
        sb2.pack(side='right', fill='y')
        self.excluded_listbox.pack(side='left', fill='both', expand=True)

        # Footer count
        self.count_label = ttk.Label(parent, text="", padding=4)
        self.count_label.pack(anchor='w', padx=8)

        self._refresh_listbox()

    def _build_hub_tab(self, parent):
        h = ttk.Frame(parent, padding=8); h.pack(fill='x')
        ttk.Label(h, text="Maps that should be left vanilla (NPCs preserved). The defaults cover Roundtable Hold and its variants.",
                  wraplength=800).pack(side='left', anchor='w')
        self._add_help_button(h, 'hub_maps')

        body = ttk.Frame(parent); body.pack(fill='both', expand=True, padx=8, pady=4)
        self.hub_listbox = tk.Listbox(body, selectmode='extended', font=('Courier', 9))
        sb = ttk.Scrollbar(body, command=self.hub_listbox.yview)
        self.hub_listbox.config(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.hub_listbox.pack(side='left', fill='both', expand=True)

        # Refresh hub list
        self._refresh_hub_listbox()

        # Buttons
        btns = ttk.Frame(parent, padding=8); btns.pack(fill='x')
        ttk.Button(btns, text="Add map...", command=self._add_hub_map).pack(side='left')
        ttk.Button(btns, text="Remove selected", command=self._remove_hub_map).pack(side='left', padx=4)
        ttk.Button(btns, text="Reset to defaults",
                   command=lambda: (self.hub_maps.update(DEFAULT_HUB_MAPS),
                                     self._refresh_hub_listbox())).pack(side='left', padx=4)

    def _build_heritage_tab(self, parent):
        """Heritage / Multiplayer-safety toggle + heritage explainer."""
        self._build_heritage_safety_subtab(parent)

    def _build_heritage_safety_subtab(self, parent):
        """The original Heritage tab content — multiplayer-safe toggle + explainer."""
        # v0.25.8: wrap in a scrollable canvas. With the stack of
        # diagnostic checkboxes below the Diagnostic section, the
        # heritage tab content exceeds typical laptop window heights
        # the new checkbox lands off-screen with no way to reach it.
        # Same Canvas + Scrollbar pattern as _build_main_tab; see that
        # method's block comment for mousewheel-binding rationale.
        scroll_canvas = tk.Canvas(parent, highlightthickness=0,
                                   bg=THEME['bg'])
        vsb = ttk.Scrollbar(parent, orient='vertical',
                             command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        scroll_canvas.pack(side='left', fill='both', expand=True)

        scroll_frame = ttk.Frame(scroll_canvas)
        scroll_window = scroll_canvas.create_window(
            (0, 0), window=scroll_frame, anchor='nw')

        def _on_frame_configure(_e=None):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox('all'))
        scroll_frame.bind('<Configure>', _on_frame_configure)

        def _on_canvas_configure(event):
            scroll_canvas.itemconfig(scroll_window, width=event.width)
        scroll_canvas.bind('<Configure>', _on_canvas_configure)

        def _on_mousewheel(event):
            if event.num == 4 or (getattr(event, 'delta', 0) > 0):
                scroll_canvas.yview_scroll(-1, 'units')
            elif event.num == 5 or (getattr(event, 'delta', 0) < 0):
                scroll_canvas.yview_scroll(1, 'units')

        def _bind_wheel(_e=None):
            scroll_canvas.bind_all('<MouseWheel>', _on_mousewheel)
            scroll_canvas.bind_all('<Button-4>', _on_mousewheel)
            scroll_canvas.bind_all('<Button-5>', _on_mousewheel)

        def _unbind_wheel(_e=None):
            scroll_canvas.unbind_all('<MouseWheel>')
            scroll_canvas.unbind_all('<Button-4>')
            scroll_canvas.unbind_all('<Button-5>')

        scroll_canvas.bind('<Enter>', _bind_wheel)
        scroll_canvas.bind('<Leave>', _unbind_wheel)

        # Rebind parent so the rest of this function builds inside the
        # scrollable frame instead of the raw tab.
        parent = scroll_frame

        f = ttk.Frame(parent, padding=16); f.pack(fill='both', expand=True)

        # v0.26.x: title row with the ? button on the right
        title_row = ttk.Frame(f); title_row.pack(fill='x')
        ttk.Label(title_row, text="Heritage / Multiplayer-safety",
                  font=(self.ui_font, 14, 'bold'),
                  foreground=THEME['accent'],
                  background=THEME['bg']).pack(side='left', anchor='w')
        self._add_help_button(title_row, 'heritage')
        ttk.Label(f,
            text="Controls how the rando handles heritage-imported chrs in coop sessions.",
            style='Dim.TLabel').pack(anchor='w', pady=(0, 12))

        toggle_frame = ttk.LabelFrame(f, text="Coop-safety toggle", padding=10)
        toggle_frame.pack(fill='x', pady=(0, 12))
        cb_row = ttk.Frame(toggle_frame); cb_row.pack(fill='x')
        mp_safe_check = ttk.Checkbutton(cb_row,
                         text="Multiplayer-safe (skip heritage chrs)",
                         variable=self.multiplayer_safe_var,
                         style='TCheckbutton')
        mp_safe_check.pack(side='left')
        Tooltip(mp_safe_check,
                "When ON, the rando refuses to swap any slot to a "
                "heritage chr (imported from Elden Ring). Vanilla NR + "
                "DLC chrs only. Default ON because heritage chrs "
                "desync coop partners who don't have them installed — "
                "anyone joining your session needs the heritage chr "
                "pack OR they CTD on cell load.")
        ttk.Label(toggle_frame,
            text="(default ON — safest setting for any session that might involve coop)",
            style='Dim.TLabel').pack(anchor='w', pady=(4, 0))

        # v0.23.45: MMV integration toggle. Reads/writes mmv_imports.json
        # _meta.enabled directly. When enabled, MMV's 41 cross-game boss
        # imports (Malenia, Maliketh, Slave Knight Gael, Dragonslayer
        # Armor, etc.) are folded into the swap pool. When disabled, the
        # rando uses vanilla NR + DLC content only.
        mmv_frame = ttk.LabelFrame(f, text="MMV integration (optional)", padding=10)
        mmv_frame.pack(fill='x', pady=(0, 12))
        mmv_row = ttk.Frame(mmv_frame); mmv_row.pack(fill='x')
        mmv_check = ttk.Checkbutton(mmv_row,
                         text="Enable MMV cross-game boss imports",
                         variable=self.mmv_enabled_var,
                         style='TCheckbutton')
        mmv_check.pack(side='left')
        Tooltip(mmv_check,
                "When ON, includes MMV's 41 cross-game boss imports "
                "(Malenia, Maliketh, Slave Knight Gael, etc.) in the "
                "swap pool. Boss-tier pool roughly doubles.\n\n"
                "REQUIRES the More Map Variations mod installed in "
                "your me3 profile — without those assets, enabling "
                "this CTDs the game on cell load. See the ⓘ icon for "
                "the full asset list.\n\n"
                "Get MMV: nexusmods.com/eldenringnightreign/mods/578\n"
                "(also linked on the About tab)")
        make_info_icon(mmv_row, tooltip_text=(
            "Default: OFF\n\n"
            "When ON, the rando includes MMV's 41 cross-game boss imports "
            "(Malenia, Maliketh, Godfrey, Slave Knight Gael, Dragonslayer "
            "Armor, etc.) in the swap pool. Boss-tier swap pool roughly "
            "doubles.\n\n"
            "REQUIRES: More Map Variations mod installed in your me3 "
            "profile, OR you've copied MMV's regulation.bin + chr/ + "
            "action/ + sd/ + script/ + msg/ + event/ + material/ files "
            "into your active mod. Without those assets, enabling this "
            "will CTD the game on cell load — the rando will reference "
            "chrs that don't exist in your active regulation.\n\n"
            "Get MMV from: "
            "https://www.nexusmods.com/eldenringnightreign/mods/578\n"
            "(also linked on the About tab)\n\n"
            "When OFF, the rando uses vanilla NR + Forsaken Hollows DLC "
            "content only. Safe for any setup."))
        ttk.Label(mmv_frame,
            text=("(reads/writes mmv_imports.json _meta.enabled — toggling "
                  "takes effect on the next run)"),
            style='Dim.TLabel').pack(anchor='w', pady=(4, 0))

        # v0.23.64: Vanilla mapstudio path. Moved here from the Generate
        # tab's Folders box because it's an advanced optional-content
        # toggle (like MMV above), not a daily-use folder picker. Most
        # users never set this and most runs work fine without it.
        # v0.26.x: wrapped in CollapsibleSection — collapsed by default
        # so first-time users don't see this advanced override.
        self._vanilla_mapstudio_section = CollapsibleSection(
            f, "Vanilla mapstudio (optional, advanced)", expanded=False)
        self._vanilla_mapstudio_section.pack(fill='x', pady=(0, 12))
        sp_body = self._vanilla_mapstudio_section.body
        sp_row = ttk.Frame(sp_body); sp_row.pack(fill='x')
        ttk.Label(sp_row, text="Path:", width=8).pack(side='left')
        ttk.Entry(sp_row, textvariable=self.spawn_pool_source_dir_var).pack(
            side='left', fill='x', expand=True, padx=4)
        ttk.Button(sp_row, text="Browse...",
                   command=lambda: self._browse_dir(
                       self.spawn_pool_source_dir_var)).pack(side='left')
        ttk.Label(sp_body,
            text=("Not needed for normal use. The bundled vanilla_msbs/ "
                  "already includes all 23 spawn-pool MSBs, so rotation-"
                  "pool bosses (Bell-Bearing Hunter at Castle Basement, "
                  "Tree Sentinels, Death Rite Bird, etc.) are randomized "
                  "automatically. Only set this if you've pointed the "
                  "input folder at your own NR install that's missing the "
                  "spawn-pool maps — then they get backfilled from here. "
                  "Leave blank otherwise."),
            style='Dim.TLabel', wraplength=720,
            justify='left').pack(anchor='w', pady=(4, 0))

        # v0.26.x: Tier 2 UX #8 — wrap the diagnostic / engine-validation
        # section in a CollapsibleSection so first-time users don't see
        # 3+ unfamiliar diagnostic toggles by default. Expand on click
        # for users who actually need them (CTD attribution, freeze
        # reports, engine-change validation).
        self._diagnostic_section = CollapsibleSection(
            f, "Diagnostic / engine validation (advanced)", expanded=False)
        self._diagnostic_section.pack(fill='x', pady=(0, 12))

        # v0.20.35: diagnostic mode for fragile-slot policy. Off by default.
        # v0.20.37: refined to "untested-only" — pool excludes both RESILIENT
        # (known good) and SENSITIVE (known bad), so every placement at a
        # fragile slot is a real test of an untested c-prefix.
        # v0.20.38: when ON, also forces non-fragile slots to a single
        # baseline c-prefix (Foot Soldier c4373) so the world is visually
        # uniform at safe slots. Anything different in-game IS a test.
        diag_frame = ttk.LabelFrame(self._diagnostic_section.body,
            text="Diagnostic — untested at fragile + Foot-Soldier baseline elsewhere",
            padding=10)
        diag_frame.pack(fill='x', pady=(0, 12))
        diag_row = ttk.Frame(diag_frame); diag_row.pack(fill='x')
        diag_check = ttk.Checkbutton(diag_row,
                         text="Diagnostic: untested targets at fragile slots + Foot Soldier everywhere else",
                         variable=self.disable_resilient_filter_var,
                         style='TCheckbutton')
        diag_check.pack(side='left')
        Tooltip(diag_check,
                "Engine-validation mode (not for normal play).\n\n"
                "Fragile slots draw from untested c-prefixes only "
                "(excludes known-good RESILIENT + known-bad SENSITIVE). "
                "Non-fragile slots get Foot Soldier (c4373) so the world "
                "is visually uniform — anything visually different in-game "
                "is a fragile-slot test result. Easy to report freezes "
                "by c-prefix.")
        make_info_icon(diag_row, tooltip_text=(
            "Default: OFF\n\n"
            "When ON, fragile slots draw from a pool that excludes both "
            "RESILIENT (known-good) and SENSITIVE (known-bad) c-prefixes — "
            "leaving only untested c-prefixes. At non-fragile slots, every "
            "spawn is forced to Foot Soldier (c4373) so the world is "
            "visually uniform at safe slots.\n\n"
            "Anything visually different in-game IS a fragile-slot test. "
            "Easy to report freezes by c-prefix."
        ))

        # v0.20.42: optional batch-restriction. When non-empty, fragile
        # slots only spawn the named c-prefixes. Used for CTD attribution.
        batch_row = ttk.Frame(diag_frame); batch_row.pack(fill='x', pady=(8, 0))
        ttk.Label(batch_row, text="Batch (comma-separated c-prefixes, optional):",
                   style='Dim.TLabel').pack(side='left')
        batch_entry = ttk.Entry(batch_row,
                                 textvariable=self.diagnostic_test_targets_var,
                                 width=50)
        batch_entry.pack(side='left', padx=(6, 0))
        Tooltip(batch_entry,
                "Optional CTD-attribution tool. When non-empty, fragile "
                "slots are restricted to ONLY the listed c-prefixes "
                "(bypasses RESILIENT / SAFE / SENSITIVE filters). Any "
                "CTD in the run is attributable to one of those.\n\n"
                "Example: c3000, c3500, c4100, c4321\n\n"
                "Empty = use the full untested pool (default).")
        make_info_icon(batch_row, tooltip_text=(
            "Empty = full untested pool (default).\n\n"
            "Example: c3000, c3500, c4100, c4321 — restricts fragile slots to "
            "those 4 c-prefixes. Bypasses RESILIENT / SAFE / SENSITIVE filters; "
            "user is in full control. CTDs in this run are attributable to one "
            "of the listed c-prefixes."
        ))

        # v0.26.16: prefer-canonical-variants toggle.
        cv_row = ttk.Frame(diag_frame); cv_row.pack(fill='x', pady=(8, 0))
        cv_check = ttk.Checkbutton(cv_row,
                         text="Prefer canonical variants: skip untested ghost NPCParam variants",
                         variable=self.prefer_canonical_variants_var,
                         style='TCheckbutton')
        cv_check.pack(side='left')
        Tooltip(cv_check,
                "When ON, each c-prefix is filtered to the variants "
                "vanilla NR actually placed somewhere (sample_maps "
                "non-empty). Ghost variants — present in the NPCParam "
                "table but never instantiated by vanilla NR — often "
                "have untested asset integration and can render glitched "
                "(T-pose, missing textures, off-scale, absent FFX).\n\n"
                "Soft filter: a c-prefix with ONLY ghost variants is "
                "still pickable, so no chr is lost.")
        make_info_icon(cv_row, tooltip_text=(
            "Default: ON\n\n"
            "ON  — picker prefers canonical variants; a ghost variant "
            "is used only when its c-prefix has no canonical.\n"
            "OFF — full pool including ghost variants: more visual "
            "variety, higher glitch risk. Block individual bad ghosts "
            "by npc_param_id if you want variety without this filter.\n\n"
            "Mechanically every variant works; only visuals are at "
            "risk with ghosts."
        ))

        # v0.26.x: the "Randomize safe night-boss arenas" and
        # "Randomize ALL night-boss arenas" checkboxes were removed
        # here. All-NB randomization is now the default (see
        # randomize_all_nb_arenas_var above) -- the multi-entity
        # boss-init investigation closed once regulation.bin was
        # modified, so it is no longer a diagnostic opt-in.


        # v0.26.15: mount/rider pair detection (cut 1 — experimental).
        mr_row = ttk.Frame(diag_frame); mr_row.pack(fill='x', pady=(8, 0))
        mr_check = ttk.Checkbutton(mr_row,
                         text="Mount/rider pair detection (experimental — audit only, no swap yet)",
                         variable=self.mount_rider_swap_var,
                         style='TCheckbutton')
        mr_check.pack(side='left')
        Tooltip(mr_check,
                "Experimental — cut 1 of the mount/rider feature.\n\n"
                "When ON, the engine detects mount/rider Part pairs "
                "(Kaiden + Horse, Night's Cavalry + Steed, etc.) and logs "
                "each one to the spoiler audit trace. It does NOT change "
                "any swap target yet — the coordinated swap is a later "
                "cut. Safe to leave on; produces audit data only.")
        make_info_icon(mr_row, tooltip_text=(
            "Default: OFF\n\n"
            "Cut 1 of the mount/rider pair-tracking feature. When ON, "
            "every MSB is scanned for mount/rider Part pairs and the "
            "results are written to the spoiler trace (MOUNT_RIDER_DETECT "
            "events) so the detection can be playtest-audited.\n\n"
            "This cut does NOT randomize mount or rider slots — those "
            "stay vanilla via the existing source-exclusion. The "
            "coordinated swap (mount slot gets a random mount, rider slot "
            "a random humanoid) is cut 2, pending playtest input on the "
            "pre-attached visual-mount behaviour."
        ))

        # v0.23.23: Heritage essay converted from always-visible body text
        # to a collapsible "Read more" expander. The full text is preserved
        # — it's substantive and worth reading once — but it no longer
        # dominates the tab visually for users who already understand the
        # toggle.
        info = ttk.LabelFrame(f, text="What is heritage?", padding=10)
        info.pack(fill='both', expand=True)
        body = (
            "The 'heritage_pack' modding tool imports character models from earlier\n"
            "FromSoft games — Dark Souls 3, Sekiro, Bloodborne, Demon's Souls, etc —\n"
            "into a local Nightreign install. These chrs are NOT shipped with vanilla\n"
            "NR; they exist only on machines where the heritage pack has been\n"
            "installed.\n\n"
            "WHEN HERITAGE CHRS ARE SAFE:\n"
            "  • Solo play (you're the only loader of the maps)\n"
            "  • Coop where every partner has the heritage pack installed locally\n\n"
            "WHEN HERITAGE CHRS BREAK COOP:\n"
            "  • Host has heritage pack, client(s) don't:\n"
            "    → Client CTDs the moment they enter a cell containing a heritage chr.\n"
            "  • The CTD looks like a generic 'connection lost' but is caused by the\n"
            "    client failing to load the unknown chrXXXX model.\n\n"
            "WHAT MULTIPLAYER-SAFE MODE DOES:\n"
            "  • Adds every heritage c-prefix to the rando's target-exclusion list\n"
            "    at runtime (does not modify your saved exclusion preferences).\n"
            "  • Slots that would have rolled a heritage chr stay vanilla instead.\n"
            "  • Has no effect on roster / spoiler reporting other than fewer\n"
            "    'heritage' targets appearing.\n\n"
            "RECOMMENDATION:\n"
            "  • Leave ON unless you're 100% sure every coop partner has the heritage\n"
            "    pack. There's no cost in solo (heritage chrs are still rare in\n"
            "    vanilla overall) and the CTD-prevention benefit is large."
        )
        # Header row with the toggle button
        self._heritage_essay_visible = tk.BooleanVar(value=False)
        toggle_row = ttk.Frame(info); toggle_row.pack(fill='x')
        self._heritage_essay_btn = ttk.Button(
            toggle_row, text="▶ Read more",
            command=lambda: self._toggle_heritage_essay(body),
            style='TButton')
        self._heritage_essay_btn.pack(side='left')
        ttk.Label(toggle_row,
            text="When heritage chrs are safe, when they break coop, what the toggle does.",
            style='Dim.TLabel').pack(side='left', padx=(8, 0))
        # The body — created hidden, toggled by _toggle_heritage_essay
        self._heritage_essay_body = ttk.Label(
            info, text=body, justify='left', font=(self.ui_font, 9))
        # Note: NOT packed yet — the toggle method packs/unpacks it

        try:
            import oops_v3 as _ov3
            n_heritage = len(_ov3.V3_HERITAGE_ALL_PREFIXES)
            count_text = f"Known heritage prefixes in this build: {n_heritage}"
        except Exception:
            count_text = ""
        if count_text:
            ttk.Label(f, text=count_text,
                      style='Dim.TLabel').pack(anchor='w', pady=(8, 0))

    def _toggle_heritage_essay(self, _body_unused=None):
        """v0.23.23: toggle the Heritage tab's "Read more" expander."""
        if self._heritage_essay_visible.get():
            # Currently visible — hide
            self._heritage_essay_body.pack_forget()
            self._heritage_essay_btn.config(text="▶ Read more")
            self._heritage_essay_visible.set(False)
        else:
            self._heritage_essay_body.pack(anchor='w', pady=(8, 0))
            self._heritage_essay_btn.config(text="▼ Hide")
            self._heritage_essay_visible.set(True)

    def _build_chr_inventory_tab(self, parent):
        """chr/ asset inventory + heritage import tool. Lets user verify their
        me3 profile chr/ folder against a spoiler's placement requirements,
        and copy missing chr files from a source game's chr/ folder
        (typically unpacked Elden Ring) into the me3 profile."""
        # v0.23.15: vertical PanedWindow split — top pane holds controls
        # (paths, asset packs, actions), bottom pane holds the Output log.
        # The v0.23.14 asset-pack panel made the tab tall enough that the
        # Output log was pushed below the fold on shorter windows. The
        # draggable sash lets the user reclaim output space when needed.
        # log_frame is created here so it's a sibling pane of `f` rather
        # than a child of `f`; the rest of the function builds into `f`
        # exactly as before.
        paned = ttk.PanedWindow(parent, orient='vertical')
        paned.pack(fill='both', expand=True)
        f = ttk.Frame(paned, padding=16)
        log_frame = ttk.LabelFrame(paned, text="Output", padding=10)
        paned.add(f, weight=2)
        paned.add(log_frame, weight=1)
        # Defer initial sash placement until geometry is known — gives the
        # output log roughly 1/3 of the visible area on first paint, so it's
        # visible without dragging on a default-size window.
        def _set_initial_sash():
            try:
                total_h = paned.winfo_height()
                if total_h > 200:
                    paned.sashpos(0, int(total_h * 0.66))
            except Exception:
                pass
        parent.after(60, _set_initial_sash)

        # v0.26.x: title row with the ? button on the right
        title_row = ttk.Frame(f); title_row.pack(fill='x')
        ttk.Label(title_row, text="Elden Ring Assets — import to me3",
                  font=(self.ui_font, 14, 'bold'),
                  foreground=THEME['accent'],
                  background=THEME['bg']).pack(side='left', anchor='w')
        self._add_help_button(title_row, 'er_assets')
        ttk.Label(f,
            text=("Point at your unpacked Elden Ring install and your me3 "
                  "mod folder, and copy over the assets the rando needs "
                  "(chr models, AI scripts, etc.) so heritage content loads "
                  "correctly."),
            style='Dim.TLabel', wraplength=720, justify='left'
            ).pack(anchor='w', pady=(0, 12))

        # === Path configuration ===
        # v0.23.72-late: paths now point at game-root folders, not chr/
        # subdirs. The tool auto-resolves chr/ and script/ as subdirectories.
        # Lets users pick the obvious "unpacked-ER root" and "me3-mod root"
        # without having to know about the chr-subfolder convention.
        # === Paths (v0.27.0 roster-import flow) ===
        # Two source folders + one target. The importer walks the
        # roster (heritage chrs + MMV pack tags), and for each chr
        # looks in the MMV folder first, then the Elden Ring folder.
        path_frame = ttk.LabelFrame(f, text="Paths", padding=10)
        path_frame.pack(fill='x', pady=(0, 12))

        def _path_row(parent, label, var, tip, save_key=None):
            row = ttk.Frame(parent); row.pack(fill='x', pady=(0, 6))
            ttk.Label(row, text=label, width=24, anchor='w',
                      style='Dim.TLabel').pack(side='left')
            ent = ttk.Entry(row, textvariable=var, width=48)
            ent.pack(side='left', padx=(6, 6), fill='x', expand=True)
            ttk.Button(row, text="...", width=4,
                       command=lambda: self._pick_dir(var, save_key)
                       ).pack(side='left')
            Tooltip(ent, tip)
            # v0.27.0: persist on manual typing too, not just picker use.
            if save_key:
                var.trace_add(
                    'write',
                    lambda *_a, v=var, k=save_key: self._save_settings(
                        **{k: v.get().strip()}))
            return row

        _path_row(path_frame, "MMV mod folder:", self.roster_mmv_dir_var,
                  "Root of your installed More Map Variations mod "
                  "(the folder with chr/, script/, sfx/, material/ "
                  "subdirs). Searched first for every roster chr. "
                  "Leave blank if you don't use MMV.",
                  save_key='roster_mmv_dir')
        _path_row(path_frame, "Elden Ring folder:", self.roster_er_dir_var,
                  "Root of your UXM-unpacked Elden Ring install. "
                  "Used as the fallback source for any roster chr "
                  "the MMV folder doesn't provide.",
                  save_key='roster_er_dir')
        _path_row(path_frame, "me3 mod folder (target):",
                  self.chr_target_dir_var,
                  "Root of your me3 mod profile — where chr/, "
                  "script/, sfx/, material/ files are copied to. "
                  "Subfolders are created if missing.",
                  save_key='chr_target_dir')

        ttk.Label(path_frame,
            text=("Both source folders are game-root folders — the "
                  "ones containing chr/ as a subfolder, not chr/ "
                  "itself. Either may be left blank; at least one "
                  "is required."),
            style='Dim.TLabel', wraplength=720, justify='left'
            ).pack(anchor='w', pady=(4, 0))

        # === Actions ===
        # v0.27.0: trimmed to two — Diagnose (plan only, no copy) and
        # Import (plan + execute). The old spoiler-scoped and per-pack
        # bulk buttons were removed; the roster import subsumes them.
        actions = ttk.LabelFrame(f, text="Actions", padding=12)
        actions.pack(fill='x', pady=(0, 12))

        btn_row = ttk.Frame(actions); btn_row.pack(fill='x')
        ttk.Button(btn_row, text="Diagnose",
                   command=lambda: self._roster_import(dry_run=True),
                   style='Accent.TButton', width=16
                   ).pack(side='left', padx=(0, 8), ipady=2)
        ttk.Button(btn_row, text="Import roster",
                   command=lambda: self._roster_import(dry_run=False),
                   style='Accent.TButton', width=16
                   ).pack(side='left', padx=(0, 8), ipady=2)

        overwrite_check = ttk.Checkbutton(btn_row,
                         text="Overwrite existing files",
                         variable=self.chr_overwrite_var,
                         style='TCheckbutton')
        overwrite_check.pack(side='left', padx=(16, 0))
        Tooltip(overwrite_check,
                "When OFF (default), files already in the target are "
                "skipped — re-running the import is cheap and safe. "
                "Turn ON only to refresh stale/broken files from "
                "source.")

        make_info_icon(actions, tooltip_text=(
            "Diagnose: build the import plan and report it — how many "
            "chrs are wanted, how many each source provides, what is "
            "missing — without copying anything.\n\n"
            "Import roster: run the plan. Copies chr + AI-script files "
            "per chr (MMV folder first, Elden Ring folder as "
            "fallback), then bulk-syncs the sfx/ and material/ dirs. "
            "Idempotent — safe to re-run; only missing files copy.\n\n"
            "Run once after pointing at your folders; you should not "
            "need to think about chr assets again."),
            side='left', padx=(8, 0))

        # === Output log ===
        # log_frame is created up top as the bottom PanedWindow pane.
        # We just populate it here.

        self.chr_log = scrolledtext.ScrolledText(
            log_frame, wrap='word', height=14,
            bg=THEME['surface_alt'], fg=THEME['text'],
            insertbackground=THEME['text'],
            font=(self.mono_font, 10),
            relief='flat', borderwidth=0)
        self.chr_log.pack(fill='both', expand=True)
        self.chr_log.configure(state='disabled')

    def _resolve_asset_subdir(self, root_path, subname):
        """v0.23.72-late: resolve a subdirectory inside a user-picked
        game-root path. Returns the resolved path string (may not exist
        on disk yet) or empty string if root_path is empty.

        Strategy:
          1. If root_path itself looks like a sibling-named subdir (e.g. user
             saved 'chr/' from the v0.23.71 GUI), use the parent for sibling
             lookups. E.g. root=...elden_ring/chr, subname=script →
             ...elden_ring/script.
          2. Otherwise, return root_path/<subname> (the standard case where
             root_path is the game-root).

        We treat 'chr', 'script', 'sfx', and 'material' as KNOWN_SUBDIRS
        for back-compat purposes: if root_path ends in one of these, we
        resolve relative to its parent. Other arbitrary base names (e.g.
        user named their mod folder 'msg/') aren't treated specially —
        they just get a subdir appended.

        v0.24.66: extended KNOWN_SUBDIRS to include 'sfx' and 'material'
        so that the new SFX + material auto-copy in chr-import can
        sibling-resolve from a chr/-rooted path.
        """
        KNOWN_SUBDIRS = {'chr', 'script', 'sfx', 'material'}
        if not root_path:
            return ''
        root = root_path.rstrip('/\\')
        base = os.path.basename(root).lower()
        # If they're asking for the same dir name as the path's leaf, that's
        # them (e.g. asking for chr/ when path is already chr/) — use as-is.
        if base == subname.lower():
            return root
        # Back-compat: if path ends in a KNOWN_SUBDIRS leaf (chr/), treat
        # the parent as the game-root and resolve siblings from there.
        if base in KNOWN_SUBDIRS:
            return os.path.join(os.path.dirname(root), subname)
        # Standard case: root is the game-root, subname is a subdir of it.
        return os.path.join(root, subname)

    def _resolve_target_chr_dir(self):
        return self._resolve_asset_subdir(
            self.chr_target_dir_var.get().strip(), 'chr')

    # v0.24.66: SFX and material sibling-dir resolvers. The source and
    # target paths are derived from the chr_source/target paths,
    # treating chr/ as a known leaf so the parent serves as the
    # game-root for sibling lookups. This means a user pointing at
    # a chr/ folder gets <root>/sfx, <root>/material, <root>/script
    # all resolved automatically.

    def _pick_dir(self, var, save_key=None):
        """Generic directory picker. If save_key given, persist to settings."""
        d = filedialog.askdirectory(initialdir=var.get() or HERE,
                                     title="Pick a folder")
        if d:
            var.set(d)
            if save_key:
                self._save_settings(**{save_key: d})
            # v0.27.0: when the target chr dir changes, refresh the
            # Generate-tab compatibility banner. (The old asset-pack
            # status panel was removed with the import-tab rework.)
            if save_key == 'chr_target_dir' and hasattr(
                self, '_compat_banner_frame'):
                self._refresh_compat_banner()

    def _chr_log_write(self, msg):
        self.chr_log.configure(state='normal')
        self.chr_log.insert('end', msg)
        self.chr_log.see('end')
        self.chr_log.configure(state='disabled')
        self.root.update_idletasks()

    def _chr_log_clear(self):
        self.chr_log.configure(state='normal')
        self.chr_log.delete('1.0', 'end')
        self.chr_log.configure(state='disabled')
    # v0.27.0: roster-import flow (Diagnose / Import roster).
    # Replaces the old spoiler-scoped + per-pack bulk import buttons.
    def _roster_import(self, dry_run=False):
        """One-time roster-driven chr import. dry_run=True is the
        Diagnose button (plan + report, no copy); dry_run=False is
        Import roster (plan + execute). Routes each roster chr from
        the MMV folder first, the Elden Ring folder as fallback."""
        mmv_dir = self.roster_mmv_dir_var.get().strip()
        er_dir = self.roster_er_dir_var.get().strip()
        target = self.chr_target_dir_var.get().strip()
        overwrite = self.chr_overwrite_var.get()

        self._chr_log_clear()
        if not mmv_dir and not er_dir:
            self._chr_log_write(
                "ERR: set at least one source folder — the MMV mod "
                "folder, the Elden Ring folder, or both.\n")
            return
        if not target:
            self._chr_log_write(
                "ERR: set the me3 mod folder (target).\n")
            return
        for label, d in (("MMV", mmv_dir), ("Elden Ring", er_dir)):
            if d and not os.path.isdir(d):
                self._chr_log_write(
                    f"ERR: {label} folder does not exist: {d}\n")
                return

        # target chr/ is a subdir of the me3 mod folder
        target_chr = os.path.join(target, 'chr')

        def _worker():
            try:
                if 'oops_v3' in sys.modules:
                    ov3 = sys.modules['oops_v3']
                else:
                    sys.path.insert(0, HERE)
                    import oops_v3 as ov3

                self._chr_log_write(
                    f"=== Roster import "
                    f"{'(DIAGNOSE — no files copied)' if dry_run else ''} ===\n"
                    f"  MMV folder:    {mmv_dir or '(not set)'}\n"
                    f"  Elden Ring:    {er_dir or '(not set)'}\n"
                    f"  Target (me3):  {target}\n"
                    f"  Overwrite:     {'YES' if overwrite else 'no (skip existing)'}\n\n")

                plan = ov3.plan_roster_import(
                    mmv_dir or None, er_dir or None, target_chr)
                t = plan['totals']
                self._chr_log_write(
                    f"Plan:\n"
                    f"  Roster chrs wanted (heritage + MMV):  {t['wanted']}\n"
                    f"  Already in target (nothing to do):    {t['already_present']}\n"
                    f"  Will copy:                            {t['copyable']}\n"
                    f"     from MMV folder:                   {t['from_mmv']}\n"
                    f"     from Elden Ring folder:            {t['from_er']}\n"
                    f"  Wanted but in neither source:         {t['unavailable']}\n"
                    f"  AI-script files to copy:              {t['script_files']}\n"
                    f"  Estimated chr+script size:            "
                    f"{t['bytes']/(1024*1024):.1f} MB\n\n")

                if plan['unavailable']:
                    self._chr_log_write(
                        f"=== {len(plan['unavailable'])} chr(s) in neither "
                        f"source folder ===\n"
                        f"  (Missing a DLC, or that game is not "
                        f"UXM-unpacked. The rando skips placements that "
                        f"need these — they fall back to vanilla.)\n")
                    for cp, wanted_by in plan['unavailable'][:30]:
                        self._chr_log_write(f"    {cp}  ({wanted_by})\n")
                    if len(plan['unavailable']) > 30:
                        self._chr_log_write(
                            f"    ... +{len(plan['unavailable']) - 30} more\n")
                    self._chr_log_write("\n")

                if dry_run:
                    if t['copyable']:
                        self._chr_log_write("Chrs that would be copied:\n")
                        for e in plan['entries']:
                            self._chr_log_write(
                                f"    {e['cp']}  [{e['origin'].upper()}]  "
                                f"{len(e['chr_files'])} chr + "
                                f"{len(e['script_files'])} script file(s)\n")
                    self._chr_log_write(
                        "\nDiagnose only — nothing was copied. Click "
                        "'Import roster' to apply.\n")
                    return

                # Real copy.
                self._chr_log_write("Copying...\n")
                res = ov3.execute_roster_import(
                    plan, mmv_dir or None, er_dir or None,
                    overwrite=overwrite)
                self._chr_log_write(
                    f"\n=== Done ===\n"
                    f"  chr files copied:       {res['chr_files_copied']}\n"
                    f"  AI-script files copied: {res['script_files_copied']}\n"
                    f"  sfx files copied:       {res['sfx_files_copied']}\n"
                    f"  material files copied:  {res['material_files_copied']}\n"
                    f"  skipped (already had):  {res['files_skipped']}\n"
                    f"  total bytes copied:     "
                    f"{res['bytes_copied']/(1024*1024):.1f} MB\n")
                if res['errors']:
                    self._chr_log_write(
                        f"\n  {len(res['errors'])} error(s):\n")
                    for msg in res['errors'][:20]:
                        self._chr_log_write(f"    {msg}\n")
                    if len(res['errors']) > 20:
                        self._chr_log_write(
                            f"    ... +{len(res['errors']) - 20} more\n")
                else:
                    self._chr_log_write("\n  No errors.\n")
            except Exception as e:
                import traceback
                self._chr_log_write(
                    f"\nUNEXPECTED ERROR: {type(e).__name__}: {e}\n"
                    f"{traceback.format_exc()}\n")

        threading.Thread(target=_worker, daemon=True).start()


    # ------------------------------------------------------------------
    # v0.26.x: Setup Status panel (#1 in Tier 1 UX tracker)
    # ------------------------------------------------------------------
    # The panel lives at the top of the Generate tab and shows ✓/✗/⚠/·
    # for the six environment checks that determine whether a Run will
    # work: Python, Tk, Oodle DLL, NR install, ER install, ME3 output.
    # Each row uses the reusable StatusIndicator + a label; refresh
    # re-evaluates all six checks and pushes new state into the widgets.
    # Called once at end of __init__ and on every path-field change so
    # the panel stays current as the user fills things in.

    def _build_setup_status_panel(self):
        """Build the rows of the setup-status checklist. Each row has a
        StatusIndicator + a label. Indicator state and label text update
        on _refresh_setup_status() — this method just constructs the
        widgets and stashes references."""
        if not hasattr(self, '_setup_status_frame'):
            return  # frame wasn't created (e.g. degraded build path)
        # Rows: (key, label_text). Order is the natural setup order.
        rows_spec = [
            ('python',      'Python'),
            ('tk',          'Tkinter'),
            ('oodle',       'Oodle DLL'),
            ('nr_install',  'Nightreign install'),
            ('er_install',  'Elden Ring install'),
            ('me3_package', 'ME3 output'),
        ]
        # v0.26.16: collapsible header. When every check is green the
        # six rows hide behind this one-line summary; click to expand.
        # Auto-expands again the moment any check regresses.
        self._setup_status_all_ok = None
        self._setup_status_collapsed = False
        self._setup_status_summary_state = 'unknown'
        self._setup_status_row_frames = []
        hdr = ttk.Frame(self._setup_status_frame)
        hdr.pack(fill='x', pady=1)
        self._setup_status_summary_row = hdr
        self._setup_status_caret = ttk.Label(
            hdr, text='▼', width=2, style='Dim.TLabel')
        self._setup_status_caret.pack(side='left')
        self._setup_status_summary_ind = StatusIndicator(
            hdr, 'unknown', 'Environment readiness')
        self._setup_status_summary_ind.pack(side='left', padx=(0, 6))
        self._setup_status_summary_label = ttk.Label(
            hdr, text='Environment checks', style='Dim.TLabel')
        self._setup_status_summary_label.pack(side='left', fill='x',
                                              expand=True)
        for _w in (hdr, self._setup_status_caret,
                   self._setup_status_summary_label):
            _w.configure(cursor='hand2')
            _w.bind('<Button-1>', self._toggle_setup_status)
        Tooltip(hdr, 'Click to show or hide the full environment '
                     'checklist. It collapses automatically once '
                     'every check passes.')
        self._setup_status_rows = {}
        for key, label in rows_spec:
            row = ttk.Frame(self._setup_status_frame)
            row.pack(fill='x', pady=1)
            self._setup_status_row_frames.append(row)
            indicator = StatusIndicator(row, 'unknown', 'Not yet checked')
            indicator.pack(side='left', padx=(0, 6))
            text_label = ttk.Label(row, text=f'{label}: …', style='Dim.TLabel')
            text_label.pack(side='left', fill='x', expand=True)
            self._setup_status_rows[key] = (indicator, text_label, label)

    def _refresh_setup_status(self, *_args):
        """Re-evaluate all environment checks and push state to the
        indicators + labels. Cheap enough to call on every path change
        (validate_path_kind + install_discovery are both fast); the
        Oodle DLL check is the most expensive bit and that one is
        cached by install_discovery via its global state."""
        if not hasattr(self, '_setup_status_rows'):
            return

        # 1. Python — informational
        ind, lbl, prefix = self._setup_status_rows['python']
        py_ver = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
        ind.set('ok', f'Python {py_ver} — required 3.10+')
        lbl.configure(text=f'{prefix}: {py_ver}')

        # 2. Tkinter — if we're rendering this panel, Tk is fine
        ind, lbl, prefix = self._setup_status_rows['tk']
        ind.set('ok', 'Tkinter loaded successfully')
        lbl.configure(text=f'{prefix}: OK')

        # 3. Oodle DLL via install_discovery
        ind, lbl, prefix = self._setup_status_rows['oodle']
        try:
            sys.path.insert(0, os.path.join(HERE, 'dev'))
            import install_discovery
            dll = install_discovery.find_oodle_dll()
        except Exception as e:
            dll = None
            ind.set('warn', f'Discovery failed: {e}')
            lbl.configure(text=f'{prefix}: discovery error')
        if dll:
            ind.set('ok', f'Found: {dll}')
            lbl.configure(text=f'{prefix}: {os.path.basename(dll)}')
        elif dll is None:
            # Distinguish "couldn't find" from "discovery errored". The
            # discovery-error branch above already set the indicator; only
            # set the not-found state when discovery returned None cleanly.
            if ind.state != 'warn':
                ind.set('error', 'Not found — copy oo2core_*.dll from your '
                                 'NR/ER install (Setup tab has details), '
                                 'or rando will fail at first .dcx write.')
                lbl.configure(text=f'{prefix}: not found')

        # 4. NR install
        ind, lbl, prefix = self._setup_status_rows['nr_install']
        nr = self.game_install_var.get().strip() if hasattr(self, 'game_install_var') else ''
        if not nr:
            ind.set('error', 'Required: set the Nightreign install path below.')
            lbl.configure(text=f'{prefix}: not set')
        else:
            state, detail = validate_path_kind(nr, 'nr_install')
            ind.set(state, detail)
            lbl.configure(text=f'{prefix}: {os.path.basename(nr.rstrip(os.sep)) or nr}')

        # 5. ER install — optional (only matters for heritage imports)
        ind, lbl, prefix = self._setup_status_rows['er_install']
        er = self.er_install_var.get().strip() if hasattr(self, 'er_install_var') else ''
        if not er:
            ind.set('unknown', "Optional — set this only if you're "
                               "importing heritage chrs from Elden Ring.")
            lbl.configure(text=f'{prefix}: not set (optional)')
        else:
            state, detail = validate_path_kind(er, 'er_install')
            ind.set(state, detail)
            lbl.configure(text=f'{prefix}: {os.path.basename(er.rstrip(os.sep)) or er}')

        # 6. ME3 output
        ind, lbl, prefix = self._setup_status_rows['me3_package']
        me3 = self.me3_package_var.get().strip() if hasattr(self, 'me3_package_var') else ''
        if not me3:
            ind.set('error', 'Required: pick the ME3 mod profile to write '
                             'shuffled MSBs into.')
            lbl.configure(text=f'{prefix}: not set')
        else:
            state, detail = validate_path_kind(me3, 'me3_profile')
            ind.set(state, detail)
            lbl.configure(text=f'{prefix}: {os.path.basename(me3.rstrip(os.sep)) or me3}')

        # v0.26.16: collapse the checklist once every check is green.
        # Recompute the aggregate from the six indicator states, then
        # let the auto policy collapse (all green) or expand (anything
        # else); a manual toggle is honored until the aggregate flips.
        _states = [self._setup_status_rows[k][0].state
                   for k in ('python', 'tk', 'oodle', 'nr_install',
                             'er_install', 'me3_package')]
        _has_error = 'error' in _states
        _has_warn = 'warn' in _states
        _all_ok = not _has_error and not _has_warn
        self._setup_status_summary_state = (
            'error' if _has_error else 'warn' if _has_warn else 'ok')
        _prev = self._setup_status_all_ok
        self._setup_status_all_ok = _all_ok
        if _prev != _all_ok:
            self._setup_status_collapsed = _all_ok
        self._apply_setup_status_collapse()

    def _apply_setup_status_collapse(self):
        """Show or hide the six checklist rows per the collapse state.
        Rows are hidden only when every check is green; if anything is
        wrong they stay visible regardless of the toggle so the user
        sees the problem. Also refreshes the summary glyph + text."""
        if not hasattr(self, '_setup_status_summary_row'):
            return
        all_ok = bool(self._setup_status_all_ok)
        collapsed = bool(self._setup_status_collapsed) and all_ok
        for row in self._setup_status_row_frames:
            if collapsed:
                row.pack_forget()
            else:
                row.pack(fill='x', pady=1)
        state = self._setup_status_summary_state
        if all_ok:
            detail = 'All environment checks passed.'
            text = 'All checks passed'
        elif state == 'error':
            detail = 'A required check failed — see the list below.'
            text = 'Setup needs attention'
        else:
            detail = 'A check raised a warning — see the list below.'
            text = 'Setup needs attention'
        self._setup_status_summary_ind.set(state, detail)
        self._setup_status_caret.configure(text='▶' if collapsed
                                           else '▼')
        self._setup_status_summary_label.configure(text=text)

    def _toggle_setup_status(self, *_event):
        """Header click handler. Flip the checklist collapse state;
        only has a visible effect when all checks pass (otherwise the
        checklist is force-expanded by _apply_setup_status_collapse)."""
        self._setup_status_collapsed = not self._setup_status_collapsed
        self._apply_setup_status_collapse()

    # ------------------------------------------------------------------
    # v0.26.x: Live path-field validation indicators (#3 in Tier 1)
    # ------------------------------------------------------------------
    # An indicator widget is placed next to each path Entry. The
    # variable's trace_add('write', _refresh_path_indicators) fires on
    # every change and rewalks the registered fields.

    def _register_path_indicator(self, indicator, var, kind):
        """Track an indicator so _refresh_path_indicators can update it.
        kind is one of validate_path_kind's recognised kinds. Also
        registers a trace on the variable so the indicator (and the
        Setup Status panel that mirrors a subset) refresh whenever the
        path field changes."""
        if not hasattr(self, '_path_indicators'):
            self._path_indicators = []
        self._path_indicators.append((indicator, var, kind))
        var.trace_add('write', self._refresh_path_indicators)

    def _refresh_path_indicators(self, *_args):
        """Recompute and apply status for every registered path field."""
        if not hasattr(self, '_path_indicators'):
            return
        for indicator, var, kind in self._path_indicators:
            state, detail = validate_path_kind(var.get().strip(), kind)
            indicator.set(state, detail)
        # The Setup Status panel mirrors a subset of these; refresh it too.
        self._refresh_setup_status()
        # v0.27.0: drive the Folders box auto-collapse off the freshly
        # computed indicator states.
        self._refresh_folders_collapse()

    # ------------------------------------------------------------------
    # v0.27.0: auto-collapsing Folders box
    # ------------------------------------------------------------------

    def _folders_has_error(self):
        """True if any path row in the Folders box is red ('error')."""
        if not hasattr(self, '_path_indicators'):
            return False
        return any(ind.state == 'error'
                   for ind, _var, _kind in self._path_indicators)

    def _refresh_folders_collapse(self):
        """Collapse the Folders body when no row is red; expand it when
        one is. A manual header click pins the state (_folders_user_pinned)
        until the next red transition, which always force-expands and
        clears the pin so a real problem is never hidden."""
        if not hasattr(self, '_folders_header'):
            return
        has_error = self._folders_has_error()
        if has_error:
            # A red row always wins: force-expand, drop any user pin so
            # the auto rule resumes once the error clears.
            self._folders_user_pinned = None
            want_collapsed = False
        elif self._folders_user_pinned is not None:
            want_collapsed = self._folders_user_pinned
        else:
            want_collapsed = True  # all clear -> tidy away
        self._apply_folders_collapse(want_collapsed)

    def _apply_folders_collapse(self, collapsed):
        """Show/hide the body frame and repaint the header summary."""
        if collapsed and not self._folders_collapsed:
            self._folders_body.pack_forget()
        elif not collapsed and self._folders_collapsed:
            self._folders_body.pack(fill='x')
        self._folders_collapsed = collapsed
        arrow = '\u25b6' if collapsed else '\u25bc'
        if collapsed:
            warn = 0
            if hasattr(self, '_path_indicators'):
                warn = sum(1 for ind, _v, _k in self._path_indicators
                           if ind.state == 'warn')
            tail = ('all paths OK' if warn == 0
                    else f'{warn} warning{"s" if warn != 1 else ""}, '
                         f'none blocking')
            self._folders_header.configure(
                text=f'{arrow}  Folders \u2014 {tail} (click to edit)')
        else:
            self._folders_header.configure(
                text=f'{arrow}  Folders (click to collapse)')

    def _toggle_folders_collapse(self, *_args):
        """Header click: pin the opposite of the current state. Ignored
        in spirit when a red row is present — _refresh_folders_collapse
        will immediately re-expand on the next refresh — but we still
        record the pin so it takes once the error clears."""
        self._folders_user_pinned = not self._folders_collapsed
        self._refresh_folders_collapse()

    # ------------------------------------------------------------------
    # v0.26.x: Re-detect button + "(auto-detected)" badge (#5 in Tier 1)
    # ------------------------------------------------------------------

    def _refresh_autodetect_badges(self, *_args):
        """Update the "(auto-detected)" label next to game_install_var
        and er_install_var. Shows the badge only when the current value
        equals what auto-detect filled in originally — if the user
        edits the field manually, the badge disappears."""
        if not hasattr(self, '_autodetect_badge_labels'):
            return
        for key, label_widget in self._autodetect_badge_labels.items():
            in_set = key in getattr(self, '_autodetected_keys', set())
            label_widget.configure(text='(auto-detected)' if in_set else '')

    def _redetect_path(self, key):
        """Re-run install_discovery for one of the root paths and
        clobber the field with the discovered value. Wired to the
        Re-detect button next to game_install and er_install rows.
        After clobber, the value is once again auto-detected so the
        badge reappears."""
        try:
            sys.path.insert(0, os.path.join(HERE, 'dev'))
            import install_discovery
            if key == 'game_install':
                new_value = install_discovery.find_nightreign_install()
                var = self.game_install_var
                name = 'Nightreign'
            elif key == 'er_install':
                new_value = install_discovery.find_elden_ring_install()
                var = self.er_install_var
                name = 'Elden Ring'
            elif key == 'me3_launcher':
                new_value = install_discovery.find_me3_binary()
                var = self.me3_launcher_var
                name = 'me3 launcher'
            else:
                return
        except Exception as e:
            messagebox.showerror('Re-detect failed',
                f'Auto-detection raised an error:\n  {e}\n\n'
                f"Browse to the path manually instead.")
            return

        if not new_value:
            messagebox.showinfo(f'{name} not found',
                f"Couldn't auto-detect a {name} install on this machine.\n\n"
                f"Make sure {name} is installed via Steam, or browse to the "
                f"install path manually. To debug discovery, run:\n"
                f"  python3 dev/install_discovery.py")
            return

        # Setting the variable triggers all the existing traces
        # (_derive_from_*, _persist_root_paths, _refresh_path_indicators,
        # _refresh_setup_status, _refresh_autodetect_badges).
        var.set(new_value)
        # Mark this key as auto-detected (set was overwritten by detect)
        if not hasattr(self, '_autodetected_keys'):
            self._autodetected_keys = set()
        self._autodetected_keys.add(key)
        self._refresh_autodetect_badges()

    def _mark_manual_edit(self, key):
        """When the user types or browses to a value, remove the
        'auto-detected' flag for that key. Triggered from each root
        path's trace callback."""
        if hasattr(self, '_autodetected_keys'):
            self._autodetected_keys.discard(key)
            self._refresh_autodetect_badges()

    # ------------------------------------------------------------------
    # v0.26.x: One-click ME3 launch (Tier 2 UX #6)
    # ------------------------------------------------------------------
    # The Launch button on the main tab finds the user's me3 binary,
    # walks up from me3_package_var to find the owning .me3 file, and
    # invokes `me3 launch -g nightreign -p <profile.me3>` via subprocess.
    # State refresh + tooltip live here; the actual launch is _launch_via_me3.

    def _resolve_me3_launch_state(self):
        """Decide what the Launch button can do right now. Returns a
        dict: {'ready': bool, 'me3_binary': str|None, 'profile': str|None,
                'reason': str (human-readable why disabled, or empty)}.

        Pure-ish: no Tk dependency, doesn't touch widgets. Lets the
        caller test the state independently of the button UI."""
        try:
            sys.path.insert(0, os.path.join(HERE, 'dev'))
            import install_discovery
            binary = install_discovery.find_me3_binary()
            pkg = (self.me3_package_var.get().strip()
                   if hasattr(self, 'me3_package_var') else '')
            profile = (install_discovery.find_me3_profile_for_package(pkg)
                       if pkg else None)
        except Exception as e:
            return {'ready': False, 'me3_binary': None, 'profile': None,
                    'reason': f'Discovery error: {e}'}

        if not binary:
            return {'ready': False, 'me3_binary': None, 'profile': profile,
                    'reason': (
                        "ME3 binary not detected. Install ME3 from "
                        "github.com/garyttierney/me3 and re-open this app, "
                        "or add me3 to your PATH.")}
        if not pkg:
            return {'ready': False, 'me3_binary': binary, 'profile': None,
                    'reason': (
                        "ME3 mod profile path isn't set yet. Configure "
                        "the 'me3 package' field above, then click "
                        "Launch.")}
        if not profile:
            return {'ready': False, 'me3_binary': binary, 'profile': None,
                    'reason': (
                        f"No .me3 file found at or above:\n  {pkg}\n\n"
                        "Either point me3_package at a directory inside "
                        "an me3 profile (typically <profile-root>/packages/"
                        "<your-pkg>/), or create a .me3 file at the "
                        "profile root.")}
        return {'ready': True, 'me3_binary': binary, 'profile': profile,
                'reason': ''}

    def _refresh_launch_button_state(self, *_args):
        """Enable/disable the Launch button + update its tooltip based on
        what _resolve_me3_launch_state finds. Called once at build time
        and on every me3_package_var change."""
        if not hasattr(self, 'launch_btn'):
            return
        state = self._resolve_me3_launch_state()
        if state['ready']:
            self.launch_btn.configure(state='normal')
            self._launch_btn_tooltip.text = (
                f"Will run:\n"
                f"  {os.path.basename(state['me3_binary'])} launch "
                f"-g nightreign -p \"{state['profile']}\"\n\n"
                f"Click to launch Nightreign through ME3 with your "
                f"mod profile active. NR's window may take a few "
                f"seconds to appear.\n\n"
                f"Shortcut: Ctrl+L")
        else:
            self.launch_btn.configure(state='disabled')
            self._launch_btn_tooltip.text = state['reason'] or (
                "Launch button isn't ready yet.")

    def _launch_via_me3(self, *, from_auto_launch=False):
        """Fire-and-forget Popen of the me3 launch command. Captures
        stderr asynchronously and writes any failure output into the
        log so the user can see why a launch failed without leaving
        the rando UI.

        from_auto_launch=True is set by the post-generate hook when
        the "Launch after generate" checkbox triggers a launch. In
        that mode, prerequisite-check failures log a one-liner instead
        of popping a modal, since the user just finished reading the
        generate output and a modal would feel intrusive.
        """
        state = self._resolve_me3_launch_state()
        if not state['ready']:
            if from_auto_launch:
                self._log(f"Auto-launch skipped: {state['reason']}\n",
                          'warn')
            else:
                messagebox.showinfo(
                    "Launch not ready", state['reason'],
                    parent=self.root)
            return

        import subprocess
        # Construct the command. ME3 docs:
        #   me3 launch -g <game> -p <profile-name-or-path>
        # Passing the full .me3 path (not just the name) avoids
        # ambiguity if the user has multiple profiles or runs from a
        # non-standard location.
        cmd = [
            state['me3_binary'],
            'launch',
            '-g', 'nightreign',
            '-p', state['profile'],
        ]
        self._log(f"\n[ME3 launch] {' '.join(cmd)}\n", 'info')

        try:
            # Popen so the GUI doesn't block on NR's lifetime. ME3
            # itself returns quickly after kicking off NR; we capture
            # its output briefly to surface any startup errors.
            # v0.26.x: pass CREATE_NO_WINDOW on Windows so the ME3
            # subprocess doesn't pop a separate console window in
            # front of (or behind) the GUI. flag value is 0x08000000
            # documented in Microsoft's CreateProcessW page; the
            # subprocess module exposes the constant on Windows only.
            popen_kwargs = dict(
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            if sys.platform == 'win32':
                popen_kwargs['creationflags'] = (
                    getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000))
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError:
            messagebox.showerror(
                "ME3 binary not found",
                f"The me3 binary at:\n  {state['me3_binary']}\n"
                f"vanished between auto-detect and launch. Most likely "
                f"it was moved or uninstalled. Re-launch this rando to "
                f"re-detect, or reinstall ME3.",
                parent=self.root)
            return
        except OSError as e:
            messagebox.showerror(
                "ME3 launch failed",
                f"Couldn't start the me3 process:\n  {e}\n\n"
                f"On Linux, make sure me3 has execute permission "
                f"(chmod +x). On Windows, check whether your antivirus "
                f"or Windows Defender is blocking the binary.",
                parent=self.root)
            return

        # Drain ME3's output in a background thread so the GUI stays
        # responsive. ME3 typically prints a few INFO lines then exits
        # once NR is hooked; if it errors during startup, those lines
        # are the user's only diagnostic.
        import threading
        def _drain():
            try:
                for line in proc.stdout:
                    self._log(f"[me3] {line}", 'dim')
                ret = proc.wait()
                if ret != 0:
                    self._log(f"[ME3] exited with status {ret}\n", 'warn')
                else:
                    self._log("[ME3] launcher exited cleanly — NR should "
                              "be running.\n", 'success')
            except Exception as e:
                self._log(f"[ME3] drain error: {e}\n", 'warn')
        threading.Thread(target=_drain, daemon=True).start()

    # ------------------------------------------------------------------
    # v0.26.x: Tier 2 UX #7 — me3 profile scaffold
    # ------------------------------------------------------------------

    def _create_me3_profile(self):
        """Interactive scaffold flow: ask the user for a target dir,
        call install_discovery.scaffold_me3_profile, then populate the
        me3_package field with the new package_dir so the user can
        immediately Run.

        Validates the chosen dir is empty (via the scaffold helper)
        and surfaces clean errors if anything goes wrong. On success,
        also offers to set the matching .me3 file as the launch target
        if the me3 launcher path is already configured.
        """
        # Step 1 — pick the target directory. Default to a sibling of
        # any existing me3_package_var path (so a user with one profile
        # likely wants the next one nearby).
        cur_pkg = self.me3_package_var.get().strip()
        if cur_pkg and os.path.isdir(cur_pkg):
            # The user's me3_package usually points inside a profile;
            # the target dir for a NEW profile sits next to it.
            default_parent = os.path.dirname(os.path.dirname(cur_pkg))
        else:
            # No existing profile — default to Documents or HOME.
            default_parent = (os.path.expanduser('~/Documents')
                              if os.path.isdir(os.path.expanduser('~/Documents'))
                              else os.path.expanduser('~'))

        target = filedialog.askdirectory(
            title="Pick a folder for the new me3 profile",
            initialdir=default_parent,
            mustexist=False)
        if not target:
            return  # user cancelled

        # Step 2 — run the scaffold
        try:
            sys.path.insert(0, os.path.join(HERE, 'dev'))
            import install_discovery
            result = install_discovery.scaffold_me3_profile(target)
        except FileExistsError as e:
            messagebox.showerror("Can't create profile here",
                f"{e}\n\nTip: Browse... above to enter a new folder "
                f"name (e.g. ~/Documents/me3-profiles/my-rando) — the "
                f"directory will be created if it doesn't exist.",
                parent=self.root)
            return
        except OSError as e:
            messagebox.showerror("Filesystem error",
                f"Couldn't scaffold the profile:\n\n{e}\n\n"
                f"Common causes:\n"
                f"  • Permission denied — pick a folder under your user "
                f"directory.\n"
                f"  • Disk full — free up space or pick a different drive.",
                parent=self.root)
            return
        except Exception as e:
            messagebox.showerror("Scaffold failed",
                f"Unexpected error creating the profile:\n  {e}\n\n"
                f"Browse to an existing me3 profile dir manually as a "
                f"workaround, or report this if it persists.",
                parent=self.root)
            return

        # Step 3 — populate me3_package_var with the new package dir.
        # Setting the var fires _derive_from_me3, which fills mod
        # map/event/chr paths automatically; _persist_root_paths saves
        # the choice; _refresh_path_indicators / _refresh_setup_status
        # update the visual indicators.
        self.me3_package_var.set(result['package_dir'])

        # Step 4 — celebrate. Tell the user what was created and where.
        messagebox.showinfo("Profile created",
            f"New me3 profile scaffolded:\n"
            f"  {result['profile_dir']}\n\n"
            f"  ✓ {os.path.basename(result['me3_file'])} (profile config)\n"
            f"  ✓ {result['profile_name']}/ (package — where the rando "
            f"writes output)\n"
            f"  ✓ README.md (explains the layout)\n\n"
            f"The me3 package path above has been set to the new "
            f"package directory. Click Randomize when ready.",
            parent=self.root)
        self._log(
            f"[Profile scaffold] Created {result['me3_file']} "
            f"+ {result['package_dir']}/\n", 'info')

    # ------------------------------------------------------------------
    # v0.26.x: recommended-expedition banner
    # ------------------------------------------------------------------

    def _refresh_recommended_expedition_banner(self):
        """Build / refresh the 'pick Tricephalos' banner on the Generate
        tab. Three hide conditions, any one of which suppresses the
        banner:
          1. RECOMMENDED_EXPEDITION_ACTIVE class-attribute is False
             (set when all Night Boss EMEVDs are validated).
          2. User dismissed it earlier (persisted via _save_settings).
          3. The host frame wasn't constructed (degraded build path).
        Otherwise renders a single-row notice with the recommendation
        + a 'Got it, hide' button.

        Safe to call any time after _build_main_tab — pack_forget +
        winfo_children().destroy() are idempotent."""
        if not hasattr(self, '_recommended_expedition_frame'):
            return
        # Clear any previous banner contents so re-calls don't stack
        for child in self._recommended_expedition_frame.winfo_children():
            child.destroy()

        if not self.RECOMMENDED_EXPEDITION_ACTIVE:
            # Validation complete — nothing to surface
            return
        if self.recommended_expedition_dismissed_var.get():
            # User dismissed; respect that across the session
            return

        # Build the banner: amber accent-bordered notice with text +
        # dismiss button. Using tk.Frame for the colored border since
        # ttk.Frame doesn't expose configurable borderwidth/bg cleanly.
        accent = THEME.get('warn', '#ffb74d')
        bg = THEME.get('surface_alt', '#262626')
        fg = THEME.get('text', '#e0e0e0')
        outer = tk.Frame(self._recommended_expedition_frame,
                          bg=accent, padx=1, pady=1)
        outer.pack(fill='x')
        inner = tk.Frame(outer, bg=bg, padx=10, pady=8)
        inner.pack(fill='x')

        # Headline row: ⚠ icon + title + dismiss button
        head = tk.Frame(inner, bg=bg); head.pack(fill='x')
        tk.Label(head, text='⚠',
                  bg=bg, fg=accent,
                  font=('TkDefaultFont', 12, 'bold')
                  ).pack(side='left', padx=(0, 6))
        tk.Label(head,
                  text=f"Recommended: {self.RECOMMENDED_EXPEDITION_NIGHTLORD}",
                  bg=bg, fg=accent,
                  font=('TkDefaultFont', 10, 'bold')
                  ).pack(side='left')
        # Dismiss on the right
        dismiss_btn = ttk.Button(head, text='Got it, hide',
                                  command=self._dismiss_recommended_expedition_banner,
                                  width=14)
        dismiss_btn.pack(side='right')
        Tooltip(dismiss_btn,
                "Hide this notice. The dismissal is remembered across "
                "launches. To bring it back, delete "
                "'recommended_expedition_dismissed' from "
                ".4laric_settings.json.")

        # Body row: explanation
        tk.Label(inner, text=self.RECOMMENDED_EXPEDITION_LONG,
                  bg=bg, fg=fg,
                  font=('TkDefaultFont', 9),
                  wraplength=720, justify='left'
                  ).pack(anchor='w', pady=(4, 0))

    def _dismiss_recommended_expedition_banner(self):
        """Mark the banner as dismissed. The BooleanVar's trace_add
        hook persists the change to .4laric_settings.json; refreshing
        the banner here hides it immediately so the user sees the
        feedback."""
        self.recommended_expedition_dismissed_var.set(True)
        self._refresh_recommended_expedition_banner()

    def _refresh_compat_banner(self):
        """v0.23.72-late: build/refresh the compatibility banner at the top
        of the Generate tab. Pulls a structured report from oops_v3's
        compatibility_preflight() and renders a compact 1-2 line summary
        with severity color + 'Open chr/ Inventory' jump button.

        Banner is recreated from scratch each call (cheaper than diffing
        which checks changed)."""
        # Clear prior contents
        if not hasattr(self, '_compat_banner_frame'):
            return
        for widget in self._compat_banner_frame.winfo_children():
            widget.destroy()

        target = self._resolve_target_chr_dir() if hasattr(
            self, 'chr_target_dir_var') else ''

        try:
            if 'oops_v3' in sys.modules:
                ov3 = sys.modules['oops_v3']
            else:
                sys.path.insert(0, HERE)
                import oops_v3 as ov3
            report = ov3.compatibility_preflight(target)
        except Exception as e:
            # Don't let a banner failure crash the tab — just suppress
            ttk.Label(self._compat_banner_frame,
                       text=f"(compatibility preflight unavailable: {type(e).__name__})",
                       style='Dim.TLabel').pack(anchor='w')
            return

        # Cache for the copy-report button on the chr Inventory tab
        self._last_compat_report = report

        status = report['status']
        if status == 'ok':
            # Don't bother showing a banner on full pass — just a one-line
            # OK note. Keeps the UI quiet when there's nothing to fix.
            row = ttk.Frame(self._compat_banner_frame); row.pack(fill='x')
            ttk.Label(row, text="✓", foreground=THEME['success'],
                       background=THEME['bg'],
                       font=(self.ui_font, 11, 'bold')
                       ).pack(side='left', padx=(2, 6))
            ttk.Label(row,
                       text="Compatibility: all checks passed.",
                       foreground=THEME['success'],
                       background=THEME['bg']
                       ).pack(side='left')
            return

        # Warn or fail — render a more prominent banner
        color = THEME['warn'] if status == 'warn' else THEME['error']
        icon = '⚠' if status == 'warn' else '✗'

        banner = ttk.LabelFrame(self._compat_banner_frame,
                                 text=("Compatibility — needs attention"
                                       if status == 'warn'
                                       else "Compatibility — fix before generating"),
                                 padding=8)
        banner.pack(fill='x')

        row1 = ttk.Frame(banner); row1.pack(fill='x')
        ttk.Label(row1, text=icon, foreground=color,
                   background=THEME['surface'],
                   font=(self.ui_font, 12, 'bold')
                   ).pack(side='left', padx=(0, 6))
        ttk.Label(row1, text=report['summary'],
                   foreground=color,
                   background=THEME['surface'],
                   font=(self.ui_font, 10, 'bold')
                   ).pack(side='left')

        # Brief details — show at most 3 non-OK checks
        non_ok = [c for c in report.get('checks', [])
                   if c.get('severity') not in ('ok', 'info')]
        for chk in non_ok[:3]:
            line = ttk.Frame(banner); line.pack(fill='x', pady=(2, 0))
            ttk.Label(line, text=f"  • {chk['name']}: {chk['message']}",
                       style='Dim.TLabel', wraplength=720, justify='left'
                       ).pack(anchor='w')
        if len(non_ok) > 3:
            ttk.Label(banner,
                       text=f"  ({len(non_ok) - 3} more — see chr/ Inventory tab for full list)",
                       style='Dim.TLabel'
                       ).pack(anchor='w', pady=(2, 0))

        # Action buttons
        btns = ttk.Frame(banner); btns.pack(fill='x', pady=(6, 0))
        ttk.Button(btns, text="Open chr/ Inventory →",
                   command=self._jump_to_chr_inventory_tab,
                   style='TButton'
                   ).pack(side='left')
        ttk.Button(btns, text="Copy report",
                   command=self._copy_compat_report,
                   style='TButton'
                   ).pack(side='left', padx=(6, 0))
        ttk.Button(btns, text="Refresh",
                   command=self._refresh_compat_banner,
                   style='TButton'
                   ).pack(side='left', padx=(6, 0))

    def _jump_to_chr_inventory_tab(self):
        """Switch the Notebook to the Elden Ring Assets tab (formerly 'chr/
        Inventory'). The tab index isn't hard-coded — we walk siblings until
        we find one matching by text."""
        try:
            nb = self.nb if hasattr(self, 'nb') else None
            if nb is None:
                # Fall back: walk widget tree for the Notebook
                for w in self.root.winfo_children():
                    if isinstance(w, ttk.Notebook):
                        nb = w; break
            if nb is None:
                return
            for i in range(nb.index('end')):
                tab_text = nb.tab(i, 'text').lower()
                # Match either new name ('elden ring assets') or
                # backwards-compat with 'chr' keyword.
                if 'elden ring' in tab_text or 'asset' in tab_text or 'chr' in tab_text:
                    nb.select(i)
                    return
        except Exception:
            pass

    # ------------------------------------------------------------------
    # v0.26.x: Tier 3 UX #12 — Copy/Clear log
    # ------------------------------------------------------------------

    @staticmethod
    def _build_log_export_header(engine_fingerprint=None, paths=None):
        """Pure function — build the environment-info header that
        prefixes a copied log. Kept pure so we can unit-test it without
        Tk. Caller passes the engine fingerprint string (e.g. 'v0.26.0')
        and a dict of configured root paths; missing values become '(not set)'.
        Returns a multi-line string ending in a separator line.
        """
        import platform, datetime
        paths = paths or {}
        lines = []
        lines.append('=== 4laric Nightreign Rando — log export ===')
        lines.append(f'Timestamp:       {datetime.datetime.now().isoformat(timespec="seconds")}')
        lines.append(f'Engine:          {engine_fingerprint or "(unknown)"}')
        lines.append(f'Python:          {sys.version.split()[0]}')
        lines.append(f'Platform:        {platform.system()} {platform.release()} '
                     f'({platform.machine()})')
        lines.append('')
        lines.append('Configured paths:')
        for key in ('game_install', 'er_install', 'me3_package',
                    'me3_launcher'):
            val = (paths.get(key) or '').strip() or '(not set)'
            lines.append(f'  {key:14s} {val}')
        lines.append('=' * 60)
        lines.append('')
        return '\n'.join(lines)

    def _gather_paths_for_log(self):
        """Collect the current path values into a dict. Defensive: each
        var lookup is guarded so a missing attribute doesn't blow up
        log export (we want the log out the door even if the GUI is
        in a degraded state)."""
        paths = {}
        for key, attr in (('game_install', 'game_install_var'),
                          ('er_install',   'er_install_var'),
                          ('me3_package',  'me3_package_var'),
                          ('me3_launcher', 'me3_launcher_var')):
            try:
                paths[key] = getattr(self, attr).get().strip()
            except Exception:
                paths[key] = ''
        return paths

    def _copy_log_to_clipboard(self):
        """Copy the log widget content (plus an environment-info header)
        to the system clipboard. Useful for pasting into bug reports.
        Surfaces a brief confirmation in the status bar."""
        try:
            log_text = self.log.get('1.0', 'end-1c')
        except tk.TclError as e:
            messagebox.showerror('Copy log failed',
                f"Couldn't read the log widget: {e}")
            return
        # Try to pull engine fingerprint for the header
        engine = None
        try:
            if 'oops_v3' in sys.modules:
                engine = sys.modules['oops_v3'].V3_ENGINE_FINGERPRINT
            else:
                import oops_v3
                engine = oops_v3.V3_ENGINE_FINGERPRINT
        except Exception:
            pass
        header = self._build_log_export_header(
            engine_fingerprint=engine,
            paths=self._gather_paths_for_log())
        full_text = header + log_text
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(full_text)
            self.root.update()  # ensure clipboard persists past app close
            line_count = full_text.count('\n')
            self.status_var.set(f"Log copied to clipboard ({line_count} lines)")
            self._log(f"[Copy log] {line_count} lines copied.\n", 'dim')
        except tk.TclError as e:
            messagebox.showerror('Clipboard error',
                f"Could not access the system clipboard:\n  {e}\n\n"
                f"Try selecting the log text manually and Ctrl+C / Cmd+C.")

    def _clear_log(self):
        """Empty the log widget. Cheap utility — useful when the user
        wants a clean slate before re-running with different settings,
        or before triggering a Copy log to capture only the new run.
        Doesn't ask for confirmation: clearing isn't destructive (the
        log can always be re-generated by re-running)."""
        try:
            self.log.configure(state='normal')
            self.log.delete('1.0', 'end')
            self.log.configure(state='disabled')
        except tk.TclError:
            pass

    def _copy_compat_report(self):
        """v0.23.72-late: render and copy the compatibility report to the
        system clipboard. Suitable for pasting into Discord / friend-zip
        instructions / GitHub issues."""
        """v0.23.72-late: render and copy the compatibility report to the
        system clipboard. Suitable for pasting into Discord / friend-zip
        instructions / GitHub issues."""
        try:
            target = self._resolve_target_chr_dir() if hasattr(
                self, 'chr_target_dir_var') else ''
            if 'oops_v3' in sys.modules:
                ov3 = sys.modules['oops_v3']
            else:
                sys.path.insert(0, HERE)
                import oops_v3 as ov3
            report = ov3.compatibility_preflight(target)
            text = ov3.render_compatibility_report_text(report)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            # Force the clipboard contents to persist past app close
            self.root.update()
            # Feedback in the chr log (if visible) — non-fatal if log doesn't exist
            if hasattr(self, 'chr_log'):
                self._chr_log_write(
                    f"=== Compatibility report copied to clipboard "
                    f"({len(text.splitlines())} lines) ===\n{text}\n\n")
        except Exception as e:
            try:
                if hasattr(self, 'chr_log'):
                    self._chr_log_write(f"Copy report failed: {type(e).__name__}: {e}\n")
            except Exception:
                pass


    # ------------------------------------------------------------------
    # v0.26.x: Tier 3 UX #11 — Spoiler viewer tab
    # ------------------------------------------------------------------
    # Loads _spoilers.json from a previous run and renders an
    # interactive view: run metadata at top, filter controls in the
    # middle, by-map swap listing in the main body. Lets users browse
    # what got randomized without opening the raw JSON in a text editor.

    @staticmethod
    def _summarize_spoiler_metadata(spoiler):
        """Pure helper — extract the headline metadata from a parsed
        spoiler dict into a list of (label, value) tuples for display.

        Tolerates missing keys (older spoiler formats, partial parses).
        Returns an empty list for a non-dict input.
        """
        if not isinstance(spoiler, dict):
            return []
        rows = []
        rows.append(('Engine', spoiler.get('engine_fingerprint')
                                or spoiler.get('engine_version') or '(unknown)'))
        rows.append(('Seed', str(spoiler.get('seed', '(unknown)'))))
        rows.append(('Entries', str(spoiler.get('entry_count')
                                     or len(spoiler.get('entries') or []))))
        # Multiplayer-safe / MMV / heritage flags
        mp = spoiler.get('multiplayer_safe')
        rows.append(('Multiplayer-safe', 'ON' if mp else 'OFF'))
        # Oops! All NB metadata if present
        nb_cp = spoiler.get('oops_all_nb_target_cp')
        if nb_cp:
            scope = spoiler.get('oops_all_nb_marker_scope', '(broad)')
            rows.append(('Oops! All NB', f'{nb_cp} ({scope})'))
        # Diagnostic mode hints
        if spoiler.get('disable_resilient_filter'):
            rows.append(('Mode', 'DIAGNOSTIC — resilient filter OFF'))
        if spoiler.get('non_fragile_baseline_cp'):
            rows.append(('Mode',
                          f"DIAGNOSTIC — baseline "
                          f"{spoiler['non_fragile_baseline_cp']}"))
        diag_batch = spoiler.get('diagnostic_test_targets')
        if diag_batch:
            rows.append(('Diagnostic batch', ', '.join(diag_batch)))
        return rows

    @staticmethod
    def _group_spoiler_entries_by_map(entries):
        """Pure helper — group spoiler entries by their 'map' field.
        Returns an OrderedDict-like dict mapping map_name → list of
        entries. Maps appear in first-seen order from the input."""
        if not entries:
            return {}
        groups = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            map_name = entry.get('map') or '(unknown map)'
            groups.setdefault(map_name, []).append(entry)
        return groups

    @staticmethod
    def _filter_spoiler_entries(entries, *,
                                 search_text='',
                                 map_filter='',
                                 boss_only=False):
        """Pure helper — apply UI filters to a list of entries.

        search_text: case-insensitive substring match against the
                     'original.name' and 'new.name' fields.
        map_filter:  exact match against the 'map' field (or '' for any).
        boss_only:   when True, drop entries where 'is_boss' is falsy.
        """
        if not entries:
            return []
        search_lower = (search_text or '').strip().lower()
        out = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if map_filter and entry.get('map') != map_filter:
                continue
            if boss_only and not entry.get('is_boss'):
                continue
            if search_lower:
                orig = ((entry.get('original') or {}).get('name') or '').lower()
                new = ((entry.get('new') or {}).get('name') or '').lower()
                if search_lower not in orig and search_lower not in new:
                    continue
            out.append(entry)
        return out

    def _build_spoiler_tab(self, parent):
        """Build the Spoiler viewer tab: file picker + run-info + filters
        + scrolled list of swaps. State (loaded spoiler, current filters)
        lives on self for the render method to consult."""
        # v0.26.x: header row for the per-tab help button. Sits above
        # the file picker so the affordance is discoverable.
        header_row = ttk.Frame(parent, padding=(8, 8, 8, 0))
        header_row.pack(fill='x')
        ttk.Label(header_row, text="Spoiler viewer",
                  font=(self.ui_font, 11, 'bold')).pack(side='left')
        self._add_help_button(header_row, 'spoiler')

        # --- File picker row ---
        picker_row = ttk.Frame(parent, padding=(8, 4, 8, 4))
        picker_row.pack(fill='x')
        ttk.Label(picker_row, text="Spoiler file:",
                  width=14).pack(side='left')
        self.spoiler_path_var = tk.StringVar(value='')
        spoiler_entry = ttk.Entry(picker_row,
                                   textvariable=self.spoiler_path_var)
        spoiler_entry.pack(side='left', fill='x', expand=True, padx=4)
        Tooltip(spoiler_entry,
                "Path to a _spoilers.json file from a previous run. "
                "Click Browse to pick one, or 'Load latest' to auto-find "
                "the most recent spoiler in your output directory.")
        ttk.Button(picker_row, text="Browse...",
                   command=self._spoiler_browse).pack(side='left')
        latest_btn = ttk.Button(picker_row, text="Load latest",
                                command=self._spoiler_load_latest)
        latest_btn.pack(side='left', padx=(4, 0))
        Tooltip(latest_btn,
                "Auto-find and load the most recent _spoilers.json from "
                "your configured output directory. Same file the post-run "
                "summary panel points at.")
        ttk.Button(picker_row, text="Reload",
                   command=self._spoiler_reload).pack(side='left', padx=(4, 0))

        # --- Run-info panel ---
        self.spoiler_info_frame = ttk.LabelFrame(parent,
            text="Run info", padding=8)
        self.spoiler_info_frame.pack(fill='x', padx=8, pady=(0, 4))
        # Placeholder until a spoiler is loaded
        ttk.Label(self.spoiler_info_frame,
            text="No spoiler loaded. Use Browse or Load latest above.",
            style='Dim.TLabel').pack(anchor='w')

        # --- Filter controls ---
        filter_row = ttk.LabelFrame(parent, text="Filters", padding=8)
        filter_row.pack(fill='x', padx=8, pady=(0, 4))
        # Search text
        search_inner = ttk.Frame(filter_row); search_inner.pack(fill='x')
        ttk.Label(search_inner, text="Search:",
                  width=10).pack(side='left')
        self.spoiler_search_var = tk.StringVar(value='')
        search_entry = ttk.Entry(search_inner,
                                  textvariable=self.spoiler_search_var)
        search_entry.pack(side='left', fill='x', expand=True, padx=4)
        Tooltip(search_entry,
                "Filter the swap list by enemy name (matches both the "
                "original and the new enemy). Case-insensitive. Leave "
                "empty to show everything.")
        self.spoiler_search_var.trace_add('write',
            lambda *_: self._render_spoiler_entries())
        # Map filter
        map_inner = ttk.Frame(filter_row); map_inner.pack(fill='x', pady=(4, 0))
        ttk.Label(map_inner, text="Map:", width=10).pack(side='left')
        self.spoiler_map_filter_var = tk.StringVar(value='(any)')
        self.spoiler_map_combo = ttk.Combobox(map_inner,
            textvariable=self.spoiler_map_filter_var,
            values=['(any)'], state='readonly', width=20)
        self.spoiler_map_combo.pack(side='left', padx=4)
        self.spoiler_map_combo.bind('<<ComboboxSelected>>',
            lambda *_: self._render_spoiler_entries())
        # Boss-only toggle
        self.spoiler_boss_only_var = tk.BooleanVar(value=False)
        boss_check = ttk.Checkbutton(map_inner,
            text="Bosses only",
            variable=self.spoiler_boss_only_var,
            command=self._render_spoiler_entries)
        boss_check.pack(side='left', padx=(12, 0))
        Tooltip(boss_check,
                "Show only entries flagged as is_boss=true (Night Boss "
                "anchors, field bosses, POI bosses, etc.). Useful for "
                "checking what got rolled at the canonical boss slots.")
        ttk.Button(map_inner, text="Clear filters",
                   command=self._spoiler_clear_filters
                   ).pack(side='right')

        # --- Entries view ---
        self._spoiler_data = None  # current parsed spoiler dict
        body = ttk.LabelFrame(parent, text="Swaps", padding=4)
        body.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.spoiler_text = scrolledtext.ScrolledText(
            body, height=22, wrap='none', state='disabled',
            font=(self.mono_font, 10),
            bg=THEME['surface_alt'], fg=THEME['text'],
            insertbackground=THEME['text'],
            selectbackground=THEME['accent'], selectforeground='#1a1a1d',
            relief='flat', borderwidth=0, padx=8, pady=6)
        self.spoiler_text.pack(fill='both', expand=True)
        # Tag styles
        self.spoiler_text.tag_configure('map_header',
            foreground=THEME['accent'],
            font=(self.mono_font, 11, 'bold'))
        self.spoiler_text.tag_configure('boss',
            foreground=THEME.get('warn', '#ffb74d'))
        self.spoiler_text.tag_configure('dim',
            foreground=THEME.get('text_dim', '#888'))

    def _spoiler_browse(self):
        """File picker for a _spoilers.json."""
        path = filedialog.askopenfilename(
            title='Select spoiler file',
            initialdir=(os.path.dirname(self.spoiler_path_var.get())
                         if self.spoiler_path_var.get()
                         else self.output_dir_var.get() if hasattr(
                             self, 'output_dir_var') else HERE),
            filetypes=[('Spoiler JSON', '*.json'),
                        ('All files', '*.*')])
        if path:
            self.spoiler_path_var.set(path)
            self._spoiler_load(path)

    def _spoiler_load_latest(self):
        """Auto-locate the most recent _spoilers.json from the
        configured output directory and load it."""
        out_dir = self.output_dir_var.get().strip() if hasattr(
            self, 'output_dir_var') else ''
        if not out_dir:
            messagebox.showinfo("Output dir not set",
                "Set the output directory on the Generate tab first, "
                "then click 'Load latest' to find the most recent "
                "spoiler there.",
                parent=self.root)
            return
        # Reuse the same discovery helper the post-run summary uses
        seed = 0  # not used when _spoilers.json is the first candidate
        path = self._find_spoiler_for_run(out_dir, seed)
        if not path:
            messagebox.showinfo("No spoiler found",
                f"No _spoilers.json (or similar) found in:\n  {out_dir}\n\n"
                f"Run the rando first, then come back to view its spoiler.",
                parent=self.root)
            return
        self.spoiler_path_var.set(path)
        self._spoiler_load(path)

    def _spoiler_reload(self):
        """Re-read the currently-loaded spoiler from disk. Useful if
        the user ran the rando again and wants to refresh without
        clicking Load latest."""
        path = self.spoiler_path_var.get().strip()
        if not path:
            messagebox.showinfo("No spoiler loaded",
                "Load a spoiler first (Browse or Load latest).",
                parent=self.root)
            return
        self._spoiler_load(path)

    def _spoiler_load(self, path):
        """Parse a spoiler JSON from disk and refresh the views."""
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            messagebox.showerror("Spoiler not found",
                f"File doesn't exist:\n  {path}\n\n"
                f"It may have been moved or deleted.",
                parent=self.root)
            return
        except json.JSONDecodeError as e:
            messagebox.showerror("Spoiler is not valid JSON",
                f"Couldn't parse {path}:\n  {e}\n\n"
                f"The file may be corrupted or truncated. Try opening "
                f"it in a text editor to inspect.",
                parent=self.root)
            return
        except OSError as e:
            messagebox.showerror("Could not read spoiler",
                f"OS error reading {path}:\n  {e}",
                parent=self.root)
            return
        self._spoiler_data = data
        self._render_spoiler_info()
        # Refresh the map-filter dropdown with the maps actually present
        groups = self._group_spoiler_entries_by_map(data.get('entries') or [])
        map_choices = ['(any)'] + sorted(groups.keys())
        self.spoiler_map_combo['values'] = map_choices
        if self.spoiler_map_filter_var.get() not in map_choices:
            self.spoiler_map_filter_var.set('(any)')
        self._render_spoiler_entries()

    def _render_spoiler_info(self):
        """Refresh the Run info panel from self._spoiler_data."""
        for child in self.spoiler_info_frame.winfo_children():
            child.destroy()
        if not self._spoiler_data:
            ttk.Label(self.spoiler_info_frame,
                text="No spoiler loaded.",
                style='Dim.TLabel').pack(anchor='w')
            return
        rows = self._summarize_spoiler_metadata(self._spoiler_data)
        # Two-column grid: label + value
        grid = ttk.Frame(self.spoiler_info_frame); grid.pack(fill='x')
        for i, (label, value) in enumerate(rows):
            ttk.Label(grid, text=f"{label}:", width=18,
                      style='Dim.TLabel'
                      ).grid(row=i, column=0, sticky='w', padx=(0, 4))
            ttk.Label(grid, text=value
                      ).grid(row=i, column=1, sticky='w')

    def _render_spoiler_entries(self, *_args):
        """Re-render the swap list applying current filters."""
        if not hasattr(self, 'spoiler_text'):
            return
        self.spoiler_text.configure(state='normal')
        self.spoiler_text.delete('1.0', 'end')
        if not self._spoiler_data:
            self.spoiler_text.insert('end',
                "(no spoiler loaded — use Browse or Load latest)\n",
                'dim')
            self.spoiler_text.configure(state='disabled')
            return
        entries = self._spoiler_data.get('entries') or []
        search = self.spoiler_search_var.get()
        map_filter = self.spoiler_map_filter_var.get()
        if map_filter == '(any)':
            map_filter = ''
        boss_only = self.spoiler_boss_only_var.get()
        filtered = self._filter_spoiler_entries(
            entries,
            search_text=search,
            map_filter=map_filter,
            boss_only=boss_only)
        if not filtered:
            self.spoiler_text.insert('end',
                "(no entries match the current filters)\n", 'dim')
            self.spoiler_text.configure(state='disabled')
            return
        # Group by map; render headers + indented entries
        groups = self._group_spoiler_entries_by_map(filtered)
        for map_name in sorted(groups.keys()):
            map_entries = groups[map_name]
            self.spoiler_text.insert('end',
                f"\n{map_name}  ({len(map_entries)} swap{'s' if len(map_entries) != 1 else ''})\n",
                'map_header')
            for entry in map_entries:
                orig = entry.get('original') or {}
                new = entry.get('new') or {}
                orig_label = f"{orig.get('name', '?')} ({orig.get('c_prefix', '?')})"
                new_label = f"{new.get('name', '?')} ({new.get('c_prefix', '?')})"
                pi = entry.get('part_index', '?')
                tier = entry.get('catalog_tier') or ''
                boss_mark = '★ ' if entry.get('is_boss') else '  '
                line = f"  {boss_mark}pi={pi:>4}  {orig_label:38s} → {new_label}"
                if tier:
                    line += f"   [{tier}]"
                line += '\n'
                self.spoiler_text.insert('end', line,
                    'boss' if entry.get('is_boss') else None)
        # Footer
        total = len(entries)
        shown = len(filtered)
        self.spoiler_text.insert('end',
            f"\n— showing {shown} of {total} entries —\n", 'dim')
        self.spoiler_text.configure(state='disabled')

    def _spoiler_clear_filters(self):
        """Reset search/map/boss filters."""
        self.spoiler_search_var.set('')
        self.spoiler_map_filter_var.set('(any)')
        self.spoiler_boss_only_var.set(False)
        # Each set triggers a render via trace_add already, but for the
        # BooleanVar we need to call render explicitly (Checkbutton's
        # `command=` doesn't fire for programmatic set)
        self._render_spoiler_entries()

    def _open_spoiler_in_viewer(self, path):
        """Load the given spoiler into the Spoiler tab and switch to it.
        Called from the post-run summary panel's 'View' button.

        Falls back to opening in the OS file manager if the Spoiler tab
        wasn't built (degraded build path) — graceful rather than silent."""
        if not hasattr(self, 'spoiler_path_var'):
            # Spoiler tab wasn't constructed — open externally instead
            self._open_in_file_manager(path)
            return
        self.spoiler_path_var.set(path)
        self._spoiler_load(path)
        # Switch the Notebook to the Spoiler tab. Walk children of root
        # to find the Notebook — there's only one in the GUI.
        for widget in self.root.winfo_children():
            if isinstance(widget, ttk.Notebook):
                nb = widget
                for i in range(nb.index('end')):
                    if 'Spoiler' in nb.tab(i, 'text'):
                        nb.select(i)
                        return
                return

    def _build_about_tab(self, parent):
        f = ttk.Frame(parent, padding=20); f.pack(fill='both', expand=True)
        ttk.Label(f, text="Oops! All Random — Nightreign Rando",
                  font=('TkDefaultFont', 14, 'bold')).pack(anchor='w')
        ttk.Label(f, text="Vanilla-aware enemy randomizer for Elden Ring Nightreign.",
                  font=('TkDefaultFont', 10)).pack(anchor='w', pady=(0, 16))

        ttk.Label(f, text="How it works:", font=('TkDefaultFont', 10, 'bold')).pack(anchor='w')
        body = (
            "• Reads each Part's vanilla c-prefix from the MSB Models section\n"
            "• Picks a swap target that matches anim_bank/size/locomotion\n"
            "• Boss-tier slots get boss-tier targets, field-tier get field-tier\n"
            "• Models section is patched to include the new enemy types\n"
            "• Each Part's ModelIndex, NPCParam, and ThinkParam are rewritten\n"
            "\n"
            "Pipeline (vanilla .msb.dcx input):\n"
            "1. Point Vanilla MSBs at <NR>/map/mapstudio/ (the .msb.dcx folder)\n"
            "2. Pick an Output folder (will hold the shuffled .msb.dcx files)\n"
            "3. Optional: set Mod map/mapstudio to your me3 profile path so the\n"
            "   shuffled files get auto-copied there after the run\n"
            "4. Click Randomize — decompress / shuffle / recompress is automatic\n"
            "5. Launch the game via me3 to test\n"
        )
        ttk.Label(f, text=body, justify='left', font=('TkDefaultFont', 9)).pack(anchor='w', pady=4)

        # v0.26.x: Helpful links section. Each row is a clickable label
        # (cursor=hand2, underlined-on-hover, opens via webbrowser.open).
        # Centralizes the external tools / mods the rando references in
        # tooltips and help overlays — gives users a copy-paste-free
        # path to install them.
        ttk.Separator(f, orient='horizontal').pack(fill='x', pady=(16, 8))
        ttk.Label(f, text="Helpful links:",
                  font=('TkDefaultFont', 10, 'bold')).pack(anchor='w')
        ttk.Label(f,
            text="Click any entry to open in your default browser.",
            style='Dim.TLabel').pack(anchor='w', pady=(0, 6))

        links = [
            ('me3',
             'https://me3-mod.github.io/',
             'Mod loader for Nightreign — required to run the rando.'),
            ('UXM Selective Unpacker',
             'https://github.com/Nordgaren/UXM-Selective-Unpack',
             'Unpacks the game archives so the rando can read MSBs '
             '(only needed for advanced workflows — the rando ships '
             'with bundled vanilla MSBs).'),
            ('More Map Variations (MMV)',
             'https://www.nexusmods.com/eldenringnightreign/mods/578',
             'Optional — alternate map layouts. Enable on the '
             'Heritage tab to fold MMV-imported chrs into the swap pool.'),
            ('WitchyBND',
             'https://github.com/ividyon/WitchyBND',
             'Optional — FromSoftware file format unpacker. Useful '
             'for inspecting chrbnd files.'),
            ('DarkScript3',
             'https://github.com/AinTunez/DarkScript3',
             'Optional — EMEVD decompiler/recompiler. Only needed '
             'for manual EMEVD patching.'),
        ]
        for label, url, desc in links:
            self._add_link_row(f, label, url, desc)

    def _add_link_row(self, parent, label, url, description):
        """Add a single clickable-link row to the parent frame. Row
        layout: [clickable link label]  [description]."""
        row = ttk.Frame(parent); row.pack(fill='x', pady=2)
        link_label = tk.Label(row,
            text=label,
            fg=THEME.get('accent', '#d4a017'),
            bg=THEME.get('bg', '#1e1e1e'),
            cursor='hand2',
            font=('TkDefaultFont', 9, 'underline'))
        link_label.pack(side='left', padx=(0, 8))
        link_label.bind('<Button-1>', lambda _e: self._open_url(url))
        Tooltip(link_label, url)
        ttk.Label(row, text=description,
                  style='Dim.TLabel',
                  wraplength=520, justify='left').pack(side='left',
                                                        anchor='w')

    def _open_url(self, url):
        """Open url in the user's default browser. Wrapped in
        try/except so a missing webbrowser module or environment
        issue doesn't crash the GUI."""
        import webbrowser
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            messagebox.showerror("Couldn't open link",
                f"Tried to open:\n  {url}\n\n"
                f"But got: {e}\n\n"
                f"You can copy the URL manually from this dialog.")

    # --- UI event handlers ------------------------------------------------
    def _random_seed(self):
        self.seed_var.set(str(random.randint(0, 999999)))

    def _on_mode_change(self):
        """Show or hide the right target picker based on mode.

        v0.26.x: switching INTO an Oops! All mode requires confirmation.
        Oops modes replace every (or every NB) slot with one chosen
        enemy — a deliberate diagnostic choice, not something to land on
        by a stray keypress. If the user cancels, revert to the last
        confirmed mode. Switching back to Standard / Validation is free
        (non-destructive), so those don't prompt."""
        mode = self.run_mode_var.get()

        # Confirm destructive Oops modes. Only prompt on a real change
        # into an Oops mode — not when the mode is unchanged (e.g. this
        # method called for a reason other than user selection).
        if mode.startswith("Oops") and mode != self._last_confirmed_mode:
            ok = messagebox.askyesno(
                "Switch to Oops! All mode?",
                f"'{mode}' replaces "
                + ("every Night Boss slot"
                   if mode.startswith("Oops! All NB")
                   else "every enemy slot")
                + " with a single chosen enemy.\n\n"
                "This is a diagnostic mode for probing one enemy at a "
                "time — not a normal randomized run. Switch to it?",
                icon='warning', default='no')
            if not ok:
                # Revert. Setting the var re-enters this method, but the
                # reverted value == _last_confirmed_mode so it won't
                # re-prompt, and the picker-frame logic below still runs.
                self.run_mode_var.set(self._last_confirmed_mode)
                return

        self._last_confirmed_mode = mode

        # Hide all dynamic mode-frames first; pack the right one.
        self.oops_all_frame.pack_forget()
        self.oops_all_nb_frame.pack_forget()
        self._oops_all_nb_help_frame.pack_forget()
        if mode.startswith("Oops! All NB"):
            self.oops_all_nb_frame.pack(fill='x', pady=(8, 0))
            self._oops_all_nb_help_frame.pack(fill='x', padx=8, pady=(2, 0))
        elif mode.startswith("Oops"):
            self.oops_all_frame.pack(fill='x', pady=(8, 0))

    def _browse_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or HERE)
        if d: var.set(d)

    def _browse_file(self, var, title='Select file', filetypes=None):
        """File picker for the me3 launcher and any other single-file
        path. Mirrors _browse_dir's pattern of "no change on cancel".

        filetypes is a list of (label, glob) pairs in tkinter's
        askopenfilename format.
        """
        cur = var.get()
        init_dir = os.path.dirname(cur) if cur else HERE
        kwargs = dict(title=title, initialdir=init_dir)
        if filetypes:
            kwargs['filetypes'] = filetypes
        path = filedialog.askopenfilename(**kwargs)
        if path:
            var.set(path)

    def _browse_msg_bundle(self, var, save=False):
        """File picker for the msg bundle (Data0_<hash>.fmg.bnd). When
        save=True, uses asksaveasfilename so the user can name a new
        file in their me3 profile's msg/engUS/ dir. When save=False,
        uses askopenfilename for selecting their vanilla bundle.
        Initial dir: the current value's parent if set, else HERE."""
        cur = var.get()
        init_dir = os.path.dirname(cur) if cur else HERE
        init_file = os.path.basename(cur) if cur else ''
        kwargs = dict(
            initialdir=init_dir,
            initialfile=init_file,
            filetypes=[("BND files", "*.fmg.bnd *.msgbnd *.msgbnd.dcx"),
                       ("All files", "*.*")],
        )
        if save:
            path = filedialog.asksaveasfilename(**kwargs)
        else:
            path = filedialog.askopenfilename(**kwargs)
        if path:
            var.set(path)

    # ========================================================================
    # EMEVD patch flow — guided GUI for applying our patches via DarkScript3
    # ========================================================================
    # ========================================================================
    # Settings persistence — remembers folder picks across runs
    # ========================================================================
    def _settings_path(self):
        return os.path.join(HERE, '.4laric_settings.json')

    def _load_settings(self):
        """Return saved settings dict (or {} if file missing/unreadable)."""
        try:
            with open(self._settings_path(), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_settings(self, **kwargs):
        """Update settings file with provided kwargs. Reads existing file
        first so we don't clobber unrelated keys."""
        s = self._load_settings()
        s.update(kwargs)
        try:
            with open(self._settings_path(), 'w', encoding='utf-8') as f:
                json.dump(s, f, indent=2)
        except OSError as e:
            self._log(f"  (couldn't save settings: {e})\n", 'dim')

    # ========================================================================
    # v0.23.45: MMV manifest enabled-state — read/write helpers.
    # The JSON file IS the persistent store; the GUI checkbox is just a
    # convenience for editing that one field. Engine reads at load_data
    # time so toggling immediately affects the next run.
    # ========================================================================
    def _mmv_path(self):
        # v0.23.71: route through _data_path() so this resolves under
        # data/ for the new layout, root for legacy.
        return _data_path('mmv_imports.json')

    def _read_mmv_enabled(self):
        """Read current _meta.enabled from mmv_imports.json. Returns False
        on any error (file missing, malformed, no _meta key) — disabled
        is the safe default for users without MMV installed."""
        try:
            with open(self._mmv_path(), encoding='utf-8') as f:
                return bool(json.load(f).get('_meta', {}).get('enabled', False))
        except (OSError, ValueError):
            return False

    def _write_mmv_enabled(self, value):
        """Write _meta.enabled into mmv_imports.json. Preserves all other
        manifest content. Used by the GUI checkbox's trace_add hook."""
        try:
            with open(self._mmv_path(), encoding='utf-8') as f:
                manifest = json.load(f)
            manifest.setdefault('_meta', {})['enabled'] = bool(value)
            with open(self._mmv_path(), 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except (OSError, ValueError) as e:
            try: self._log(f"  (couldn't update mmv_imports.json: {e})\n", 'dim')
            except Exception: pass

    def _on_mmv_toggle(self):
        """Persist MMV state on toggle + flag the picker as needing refresh.
        The roster/picker was built once at init from load_data(); a runtime
        toggle changes which c-prefixes the engine knows about, which means
        the picker needs to be rebuilt to surface (or hide) MMV chrs.
        Cheapest correct UX: write the new state + tell the user to restart
        for picker visibility, since the next Run will use the new state
        regardless. Skip the prompt if state matches initial state (user
        flipped twice and ended up where they started)."""
        new_value = bool(self.mmv_enabled_var.get())
        self._write_mmv_enabled(new_value)
        if new_value != self._mmv_initial_state:
            state_label = 'enabled' if new_value else 'disabled'
            try:
                messagebox.showinfo(
                    "MMV setting changed",
                    f"MMV integration is now {state_label}.\n\n"
                    f"The next run will use this setting. To see MMV chrs "
                    f"in the picker dropdowns, restart the GUI.")
            except Exception:
                pass
            # Update the snapshot so subsequent toggles back to the same
            # value don't re-trigger the message.
            self._mmv_initial_state = new_value

    def _emevd_config_path(self):
        return os.path.join(HERE, '.4laric_emevd_paths.json')

    def _load_emevd_paths(self):
        try:
            with open(self._emevd_config_path(), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_emevd_paths(self, paths):
        try:
            with open(self._emevd_config_path(), 'w', encoding='utf-8') as f:
                json.dump(paths, f, indent=2)
        except OSError as e:
            self._log(f"Warning: could not save paths: {e}\n", 'warn')

    # v0.24.8: parallel helpers for msg bundle paths
    def _msg_config_path(self):
        return os.path.join(HERE, '.4laric_msg_paths.json')

    def _load_msg_paths(self):
        try:
            with open(self._msg_config_path(), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_msg_paths(self, paths):
        try:
            with open(self._msg_config_path(), 'w', encoding='utf-8') as f:
                json.dump(paths, f, indent=2)
        except OSError as e:
            self._log(f"Warning: could not save msg paths: {e}\n", 'warn')

    # v0.24.9: parallel helpers for the two top-level parent paths
    # (game install + me3 package) that derive everything else.
    def _root_paths_config(self):
        return os.path.join(HERE, '.4laric_paths.json')

    def _load_root_paths(self):
        try:
            with open(self._root_paths_config(), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _apply_install_autodetect(self, saved):
        """Fill empty 'game_install' / 'er_install' entries in the saved
        root-paths dict with Steam auto-detection results. Returns a
        new dict; doesn't mutate the input.

        Called once at GUI startup, just after _load_root_paths(). Saved
        non-empty values always win — auto-detect only fires for fields
        that haven't been set yet. If the user manually clears a saved
        value to re-detect, they can do so by emptying the field via
        the Browse dialog (clearing it and saving with empty path).

        Detection failures are silent. The dev/install_discovery module
        is designed to never raise; we wrap the call in a try/except as
        defense-in-depth in case a future change breaks that contract.

        Side effect: populates self._autodetected_keys with the set of
        keys this call filled, so the UI can show "(auto-detected)"
        badges and "Re-detect" buttons next to those fields. Re-running
        autodetect (via the Re-detect button) re-populates the set.
        """
        # Initialize / reset the provenance tracker. Used by the UI to
        # decide which path fields display an "(auto-detected)" badge.
        if not hasattr(self, '_autodetected_keys'):
            self._autodetected_keys = set()
        result = dict(saved)
        # Early-out if all four discoverable paths already set
        if (result.get('game_install', '').strip()
                and result.get('er_install', '').strip()
                and result.get('me3_launcher', '').strip()):
            return result
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dev'))
            import install_discovery
            if not result.get('game_install', '').strip():
                nr_path = install_discovery.find_nightreign_install()
                if nr_path:
                    result['game_install'] = nr_path
                    self._autodetected_keys.add('game_install')
            if not result.get('er_install', '').strip():
                er_path = install_discovery.find_elden_ring_install()
                if er_path:
                    result['er_install'] = er_path
                    self._autodetected_keys.add('er_install')
            # v0.26.x: me3 launcher binary. The Launch button still
            # falls back to runtime discovery if this stays empty, but
            # filling it on first launch makes the path field
            # actionable (browse / re-detect) instead of mysterious.
            if not result.get('me3_launcher', '').strip():
                me3_path = install_discovery.find_me3_binary()
                if me3_path:
                    result['me3_launcher'] = me3_path
                    self._autodetected_keys.add('me3_launcher')
        except Exception:
            # Discovery is best-effort. Any failure (import error,
            # registry-read failure on a locked-down system, etc.)
            # falls back silently to empty fields.
            pass
        return result

    def _save_root_paths(self, paths):
        try:
            with open(self._root_paths_config(), 'w', encoding='utf-8') as f:
                json.dump(paths, f, indent=2)
        except OSError as e:
            self._log(f"Warning: could not save root paths: {e}\n", 'warn')

    def _discover_msg_bundle_basename(self, game_dir):
        """Scan <game_dir>/msg/engUS/ for the engUS Item bundle (the
        one containing NpcName.fmg). If found, cache its basename in
        self.msg_bundle_basename_var so subsequent derivations from
        either game_install or me3_package can compute the file path
        without rescanning.

        v0.24.109: if the scan finds nothing (NR install not UXM-unpacked,
        msg/engUS/ missing, etc.), fall back to the canonical NR default
        basename so derivation still produces a path. The downstream
        splicer will report "file not found" cleanly at runtime instead
        of leaving the user staring at an empty derived path field.
        Phase 3 fallback ("Crucible Knight and more") then covers the
        in-game display regardless.

        v0.24.110 finding: NR has NO `item.msgbnd.dcx` (the non-dlc form).
        UXM unpack of stock NR produces only three files in msg/engUS/:
        `item_dlc01.msgbnd.dcx`, `menu_dlc01.msgbnd.dcx`, `ngword.msgbnd.dcx`.
        The non-dlc variants exist only as dictionary entries in UXM's
        EldenRingNightreignDictionary.txt that don't correspond to any
        actual archive content. NR uses the `_dlc01` filename for what
        would have been the base bundle in ER. Files we previously found
        named `item.msgbnd.dcx` (e.g., in fifthmatt's map randomizer)
        are custom mod-created bundles, not stock content.

        So the splice target is correct as `item_dlc01.msgbnd.dcx` — that's
        where the boss healthbar NpcName.fmg lives in stock NR.
        """
        NR_DEFAULT_BASENAME = 'item_dlc01.msgbnd.dcx'
        msg_dir = os.path.join(game_dir, 'msg', 'engUS')
        if not os.path.isdir(msg_dir):
            # No unpacked msg dir. Set the canonical default so derivation
            # still fires; downstream splicer will surface the missing-
            # file error cleanly.
            self.msg_bundle_basename_var.set(NR_DEFAULT_BASENAME)
            return
        candidates = []
        try:
            for name in os.listdir(msg_dir):
                low = name.lower()
                if not low.startswith('item'):
                    continue
                # Accept *.msgbnd, *.msgbnd.dcx, *.fmg.bnd, *.fmg.bnd.dcx
                if not (low.endswith('.msgbnd') or low.endswith('.msgbnd.dcx')
                        or low.endswith('.fmg.bnd') or low.endswith('.fmg.bnd.dcx')):
                    continue
                path = os.path.join(msg_dir, name)
                try:
                    sz = os.path.getsize(path)
                except OSError:
                    continue
                candidates.append((sz, name))
        except OSError:
            self.msg_bundle_basename_var.set(NR_DEFAULT_BASENAME)
            return
        if not candidates:
            self.msg_bundle_basename_var.set(NR_DEFAULT_BASENAME)
            return
        # v0.24.111: prefer .dcx-suffixed candidates. NR's loader requests
        # the .dcx path; me3 will only serve loose-file overrides that
        # match the requested filename. If both a raw `.msgbnd` and
        # `.msgbnd.dcx` exist in the user's install (e.g. UXM unpack
        # produced both, or a Yabber roundtrip left an extracted file
        # next to the dcx), we must pick the dcx variant so the rando
        # output also gets written with .dcx suffix and DCX-wrapped.
        # Picking by file size alone would prefer the raw (~2.4MB) over
        # the dcx (~210KB) — wrong.
        dcx_candidates = [c for c in candidates if c[1].lower().endswith('.dcx')]
        chosen_pool = dcx_candidates if dcx_candidates else candidates
        # Within the chosen pool, pick the largest (Item bundle is the
        # biggest of menu/item/ngword for both raw and dcx forms).
        chosen_pool.sort(reverse=True)
        self.msg_bundle_basename_var.set(chosen_pool[0][1])

    def _apply_msg_basename_derivation(self):
        """If we have a cached Item-bundle basename plus a parent
        path, set the corresponding msg bundle Tk var. Called on
        any of: game_install change, me3_package change, basename
        discovery completing. Safe to call when basename is empty
        (no-op)."""
        basename = self.msg_bundle_basename_var.get().strip()
        if not basename:
            return
        game = self.game_install_var.get().strip()
        if game and hasattr(self, 'vanilla_msg_bundle_var'):
            self.vanilla_msg_bundle_var.set(
                os.path.join(game, 'msg', 'engUS', basename))
        me3 = self.me3_package_var.get().strip()
        if me3 and hasattr(self, 'mod_msg_bundle_var'):
            self.mod_msg_bundle_var.set(
                os.path.join(me3, 'msg', 'engUS', basename))

    def _install_prepatched_emevd(self):
        """One-click install: copy ALL bundled patched EMEVD files into
        the user's me3 profile event/ directory. Includes common_func.emevd.dcx
        plus per-map .emevd.dcx files for maps with inline scripts that
        common_func patches can't reach."""
        import shutil
        import glob

        # Find all patched EMEVD files in the bundle
        patched_dir = os.path.join(HERE, 'patched_emevd')
        if not os.path.isdir(patched_dir):
            messagebox.showerror("Pre-patched dir missing",
                f"Could not find:\n{patched_dir}\n\n"
                "The bundle may be incomplete. Re-download the rando, or use\n"
                "the manual patcher flow instead.")
            return

        # All .emevd.dcx files (common_func + per-map)
        prepatched_files = sorted(glob.glob(os.path.join(patched_dir, '*.emevd.dcx')))
        if not prepatched_files:
            messagebox.showerror("Pre-patched files missing",
                f"No *.emevd.dcx files in:\n{patched_dir}\n\n"
                "The bundle may be incomplete.")
            return

        # The critical file — refuse to proceed if it's not present
        common_func = os.path.join(patched_dir, 'common_func.emevd.dcx')
        if not os.path.exists(common_func):
            messagebox.showerror("Pre-patched file missing",
                f"Could not find:\n{common_func}\n\n"
                "common_func.emevd.dcx is required.\n"
                "The bundle may be incomplete.")
            return

        per_map_files = [f for f in prepatched_files
                         if os.path.basename(f) != 'common_func.emevd.dcx']

        # Intro
        msg = ("This will copy all pre-patched EMEVD files into your me3\n"
               "profile, applying every rando fix in one click.\n\n"
               f"Files to install ({len(prepatched_files)} total):\n"
               f"  • common_func.emevd.dcx    (5 patches: death_timeout,\n"
               f"      permissive_boss_wake, permissive_spawn_emerge,\n"
               f"      disable_corpse_collision, boss_reward_inject)\n")
        if per_map_files:
            msg += f"  • {len(per_map_files)} per-map .emevd.dcx files\n"
            msg += f"      (inline-script fixes for maps that common_func\n"
            msg += f"      handlers can't reach: " + ", ".join(
                os.path.basename(f).replace('.emevd.dcx', '')
                for f in per_map_files) + ")\n"
        msg += ("\nWhat it fixes:\n"
                "  • Killed bosses not dropping runes\n"
                "  • Sleeping enemies not waking up\n"
                "  • Frozen mining/spawn-emerge enemies\n"
                "  • Persistent corpses blocking Sites of Grace\n"
                "  • Inline-script encounters in Guardian Golem (Fort),\n"
                "    cathedral interiors, and dense overworld cells\n\n"
                "Existing files at the destination will be backed up to\n"
                "*.bak before overwriting.\n\n"
                "Click OK to pick the destination directory.")
        if not messagebox.askokcancel("Install pre-patched EMEVDs", msg):
            return

        paths = self._load_emevd_paths()
        last_out = paths.get('output_dir', '')
        initial_out = last_out if last_out and os.path.isdir(last_out) else HERE

        output_dir = filedialog.askdirectory(
            title="me3 profile event/ directory",
            initialdir=initial_out)
        if not output_dir:
            self._log("EMEVD install: cancelled\n", 'dim')
            return

        # Save for next time (re-use the same key as the manual flow)
        paths['output_dir'] = output_dir
        self._save_emevd_paths(paths)

        # Copy each file with backup
        copied = 0
        backed_up = 0
        for src in prepatched_files:
            fname = os.path.basename(src)
            final_dest = os.path.join(output_dir, fname)
            # Backup existing if present
            if os.path.exists(final_dest):
                backup = final_dest + '.bak'
                try:
                    shutil.copy(final_dest, backup)
                    backed_up += 1
                except OSError as e:
                    self._log(f"Could not back up {fname}: {e}\n", 'warn')
                    if not messagebox.askyesno("Backup failed",
                        f"Could not back up:\n{final_dest}\n{e}\n\n"
                        "Proceed with overwrite anyway?"):
                        return
            # Copy
            try:
                shutil.copy(src, final_dest)
                copied += 1
                self._log(f"  ✓ {fname}\n", 'success')
            except OSError as e:
                self._log(f"Failed to copy {fname}: {e}\n", 'error')
                messagebox.showerror("Install failed",
                    f"Could not write:\n{final_dest}\n{e}")
                return

        if backed_up:
            self._log(f"Backed up {backed_up} existing file(s) → *.bak\n", 'dim')
        self._log(f"\n✓ Pre-patched EMEVDs installed ({copied} files)\n", 'success')
        self._log(f"   {output_dir}\n", 'success')
        self._log(f"\nLaunch the game via me3 to test.\n", 'info')

        messagebox.showinfo("EMEVD installed",
            f"{copied} pre-patched EMEVD file(s) copied to:\n{output_dir}\n\n"
            f"Launch the game via me3 to test.\n\n"
            f"If encounter bugs persist after install, your NR build may be a\n"
            f"different version than this file was patched against. Use the\n"
            f"\"Apply patches manually (advanced)\" option in that case.")

    def _open_file_explorer(self, path):
        """Cross-platform: open file explorer to the given directory."""
        import subprocess, platform
        try:
            if platform.system() == 'Windows':
                os.startfile(path)
            elif platform.system() == 'Darwin':
                subprocess.run(['open', path], check=False)
            else:
                subprocess.run(['xdg-open', path], check=False)
        except Exception as e:
            self._log(f"  (couldn't open file explorer: {e})\n", 'dim')

    def _apply_emevd_patches(self):
        """Guided flow: copy vanilla → user decompiles in DarkScript3 → we
        patch the JS → user recompiles in DarkScript3 → copy result to me3
        profile."""
        import tempfile, shutil, io
        try:
            import emevd_patch
        except ImportError as e:
            messagebox.showerror("emevd_patch not found",
                f"Could not import emevd_patch.py:\n{e}\n\n"
                "Make sure emevd_patch.py is in the same folder as this GUI.")
            return

        # Intro
        if not messagebox.askokcancel(
            "Apply EMEVD patches",
            "This will guide you through applying our EMEVD patches.\n\n"
            "You'll need:\n"
            "  • A copy of vanilla NR's common_func.emevd.dcx\n"
            "  • DarkScript3 installed\n"
            "  • A me3 profile to drop the patched file into\n\n"
            "The flow has two manual DarkScript3 steps (decompile, recompile)\n"
            "with everything else automated.\n\n"
            "Click OK to begin, Cancel to abort."
        ):
            return

        paths = self._load_emevd_paths()

        # === Pick vanilla common_func.emevd.dcx ===
        last_dcx = paths.get('vanilla_dcx', '')
        initial_dir = os.path.dirname(last_dcx) if last_dcx and os.path.exists(last_dcx) else HERE
        vanilla_dcx = filedialog.askopenfilename(
            title="Select vanilla common_func.emevd.dcx",
            initialdir=initial_dir,
            filetypes=[('common_func', 'common_func.emevd.dcx'),
                       ('All files', '*.*')])
        if not vanilla_dcx:
            self._log("EMEVD patch: cancelled (no vanilla file)\n", 'dim')
            return
        if not os.path.basename(vanilla_dcx).startswith('common_func'):
            if not messagebox.askyesno("Unexpected filename",
                f"Expected 'common_func.emevd.dcx', got:\n"
                f"  {os.path.basename(vanilla_dcx)}\n\n"
                "Continue anyway?"):
                return

        # === Pick output dir (me3 profile event/) ===
        last_out = paths.get('output_dir', '')
        initial_out = last_out if last_out and os.path.isdir(last_out) else HERE
        output_dir = filedialog.askdirectory(
            title="Output directory (typically <me3 profile>/<package>/event/)",
            initialdir=initial_out)
        if not output_dir:
            self._log("EMEVD patch: cancelled (no output dir)\n", 'dim')
            return

        # Cache for next time
        self._save_emevd_paths({'vanilla_dcx': vanilla_dcx, 'output_dir': output_dir})

        # === Set up working dir ===
        work_dir = tempfile.mkdtemp(prefix='4laric_emevd_')
        self._log(f"\n=== EMEVD patch flow ===\n", 'accent')
        self._log(f"Working dir: {work_dir}\n", 'dim')

        work_dcx = os.path.join(work_dir, 'common_func.emevd.dcx')
        try:
            shutil.copy(vanilla_dcx, work_dcx)
        except OSError as e:
            self._log(f"Failed to copy vanilla file: {e}\n", 'error')
            messagebox.showerror("Copy failed", f"Could not copy vanilla file:\n{e}")
            return

        # === Step 1: User decompiles in DarkScript3 ===
        self._open_file_explorer(work_dir)
        self._log("Step 1: Waiting for user to decompile in DarkScript3...\n", 'info')

        if not messagebox.askokcancel(
            "Step 1 of 2 — Decompile",
            f"File Explorer is open to:\n{work_dir}\n\n"
            "In DarkScript3:\n"
            "  1. Open common_func.emevd.dcx (drag-drop or File > Open)\n"
            "  2. Save the JavaScript file (Ctrl+S — produces\n"
            "     common_func.emevd.dcx.js next to the original)\n\n"
            "Click OK when DarkScript3 has saved the JS file."
        ):
            self._log("EMEVD patch: cancelled at decompile step\n", 'dim')
            return

        # Find the .js file
        js_files = [f for f in os.listdir(work_dir) if f.endswith('.emevd.dcx.js')]
        if not js_files:
            messagebox.showerror("JavaScript not found",
                f"Expected to find a .emevd.dcx.js file in:\n{work_dir}\n\n"
                "Did DarkScript3 save the JS file there? You may need\n"
                "to use File > Save As and pick that location.")
            return
        self._log(f"  Found: {js_files[0]}\n", 'success')

        # === Step 2: Apply our patches ===
        patched_dir = os.path.join(work_dir, 'patched')
        os.makedirs(patched_dir, exist_ok=True)

        self._log("\nApplying patches...\n", 'info')
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            emevd_patch.cmd_patch(work_dir, patched_dir)
        except Exception as e:
            sys.stdout = old_stdout
            self._log(f"Patch failed: {e}\n", 'error')
            self._log(traceback.format_exc(), 'error')
            messagebox.showerror("Patch failed", f"emevd_patch raised an error:\n{e}")
            return
        finally:
            sys.stdout = old_stdout
        # Indent captured output for readability
        for line in captured.getvalue().splitlines():
            self._log(f"  {line}\n", 'dim')

        patched_files = [f for f in os.listdir(patched_dir)
                         if f.endswith('.emevd.dcx.js')]
        if not patched_files:
            messagebox.showerror("No patches applied",
                "No files were modified. The vanilla file may not match\n"
                "the expected NR EMEVD content (different game version?), or\n"
                "the patches may already be applied.")
            return

        # === Step 3: User recompiles in DarkScript3 ===
        self._open_file_explorer(patched_dir)
        self._log("\nStep 2: Waiting for user to recompile in DarkScript3...\n", 'info')

        if not messagebox.askokcancel(
            "Step 2 of 2 — Recompile",
            f"Patches applied. Patched JS is at:\n{patched_dir}\n\n"
            "In DarkScript3:\n"
            "  1. Open the patched common_func.emevd.dcx.js\n"
            "  2. Save the file (Ctrl+S — produces an updated\n"
            "     common_func.emevd.dcx in the same folder)\n\n"
            "Click OK when DarkScript3 has saved the recompiled DCX."
        ):
            self._log("EMEVD patch: cancelled at recompile step\n", 'dim')
            return

        # Find the recompiled .dcx
        recompiled_dcx = os.path.join(patched_dir, 'common_func.emevd.dcx')
        if not os.path.exists(recompiled_dcx):
            messagebox.showerror("Recompiled DCX not found",
                f"Expected to find common_func.emevd.dcx in:\n{patched_dir}\n\n"
                "Did DarkScript3 save it there? It usually saves next to the\n"
                "JS file by default.")
            return

        # === Step 4: Copy to output ===
        final_dest = os.path.join(output_dir, 'common_func.emevd.dcx')
        try:
            # Backup any existing file at the destination
            if os.path.exists(final_dest):
                backup = final_dest + '.bak'
                shutil.copy(final_dest, backup)
                self._log(f"  (backed up existing file → {os.path.basename(backup)})\n", 'dim')
            shutil.copy(recompiled_dcx, final_dest)
        except OSError as e:
            self._log(f"Failed to copy to output: {e}\n", 'error')
            messagebox.showerror("Copy failed", f"Could not copy to output:\n{e}")
            return

        self._log(f"\n✓ EMEVD patches applied successfully\n", 'success')
        self._log(f"   {final_dest}\n", 'success')
        self._log(f"\nLaunch the game via me3 to test.\n", 'info')

        messagebox.showinfo("EMEVD patches applied",
            f"Patched common_func.emevd.dcx written to:\n{final_dest}\n\n"
            f"Launch the game via me3 to test the encounter fixes.")

    def _set_excluded(self, items):
        self.excluded = set(items)
        self._refresh_listbox()

    def _refresh_listbox(self):
        if not hasattr(self, 'all_listbox'): return
        search = self.search_var.get().lower()
        self.all_listbox.delete(0, 'end')
        self.excluded_listbox.delete(0, 'end')
        for cp, disp in sorted(self.prefix_display.items()):
            if search and search not in disp.lower(): continue
            (self.excluded_listbox if cp in self.excluded else self.all_listbox).insert('end', disp)
        self.count_label.config(text=f"Excluded: {len(self.excluded)} c-prefixes")

    def _exclude_selected(self):
        for i in self.all_listbox.curselection():
            disp = self.all_listbox.get(i)
            cp = disp.split()[0]
            self.excluded.add(cp)
        self._refresh_listbox()

    def _include_selected(self):
        for i in self.excluded_listbox.curselection():
            disp = self.excluded_listbox.get(i)
            cp = disp.split()[0]
            self.excluded.discard(cp)
        self._refresh_listbox()

    def _refresh_hub_listbox(self):
        if not hasattr(self, 'hub_listbox'): return
        self.hub_listbox.delete(0, 'end')
        for fn in sorted(self.hub_maps):
            self.hub_listbox.insert('end', fn)

    def _add_hub_map(self):
        from tkinter.simpledialog import askstring
        v = askstring("Add hub map", "MSB filename (e.g. m10_00_00_00.msb):", parent=self.root)
        if v:
            v = v.strip()
            if not v.endswith('.msb'): v += '.msb'
            self.hub_maps.add(v)
            self._refresh_hub_listbox()

    def _remove_hub_map(self):
        for i in reversed(self.hub_listbox.curselection()):
            fn = self.hub_listbox.get(i)
            self.hub_maps.discard(fn)
        self._refresh_hub_listbox()

    # --- Shuffle execution ------------------------------------------------
    def _cancel_shuffle(self):
        """v0.19.21: Cancel an in-progress rando run. Sets the engine's
        threading event; the worker exits at the next per-map checkpoint
        (latency ~1-3 seconds per map). The button is greyed out while
        cancellation propagates."""
        if not (self.worker_thread and self.worker_thread.is_alive()):
            return
        try:
            import oops_v3
            oops_v3.set_cancel_requested(True)
        except Exception:
            pass
        self.run_btn.config(text="Cancelling...", state='disabled')
        self.status_var.set("Cancelling at next checkpoint…")
        self.log_queue.put("\n--- Cancellation requested ---\n")

    def _run_shuffle(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("Already running",
                "A rando is already being generated. Wait for it to finish.")
            return

        # v0.26.x: track run start for duration in the post-run summary
        # panel. Use monotonic so DST / wall-clock changes don't produce
        # negative durations.
        import time as _time
        self._run_start_time = _time.monotonic()
        # If a previous summary panel is visible, hide it now — the new
        # run hasn't completed yet and the old summary is misleading.
        self._hide_post_run_summary()

        try:
            seed = int(self.seed_var.get())
        except ValueError:
            seed_str = self.seed_var.get()
            seed = abs(hash(seed_str)) % (2**31)
            self._log(f"Seed '{seed_str}' is not an integer — using hashed seed {seed}\n")

        in_dir = self.input_dir_var.get()
        out_dir = self.output_dir_var.get()
        mod_map_dir = self.mod_map_dir_var.get().strip()
        if not os.path.isdir(in_dir):
            messagebox.showerror("Bad input directory",
                f"Input directory does not exist:\n{in_dir or '(blank)'}\n\n"
                f"Set the input folder to your NR install's mapstudio dir,\n"
                f"typically:\n"
                f"  <Steam>\\steamapps\\common\\ELDEN RING NIGHTREIGN\\Game\\map\\mapstudio\\\n"
                f"\n"
                f"It's the folder full of m*.msb.dcx files. If that folder\n"
                f"doesn't exist or is empty, your NR install is still packed\n"
                f"in .bhd/.bdt archives — run UXM Selective Unpacker first:\n"
                f"  https://github.com/Nordgaren/UXM-Selective-Unpack")
            return
        # Sanity-check: input dir exists but has no .msb files? Most likely
        # they pointed at an unpacked dir but UXM didn't unpack the map files,
        # or they pointed somewhere wrong entirely.
        try:
            has_msb = any(f.endswith('.msb') or f.endswith('.msb.dcx')
                          for f in os.listdir(in_dir))
        except OSError:
            has_msb = False
        if not has_msb:
            messagebox.showerror("No map files in input",
                f"Input directory exists but contains no .msb or .msb.dcx files:\n{in_dir}\n\n"
                f"Expected to see m*.msb.dcx files (NR's vanilla map data).\n"
                f"Likely causes:\n"
                f"  • Wrong folder — should be <NR install>/Game/map/mapstudio/\n"
                f"  • NR install is still packed — run UXM to unpack it first")
            return
        # v0.24.43: explicit empty-output check. Previously
        # `os.makedirs("")` would fail below with a cryptic error;
        # this surfaces the missing-path case with a clearer message.
        # Becomes more reachable since v0.24.43 also removed the
        # project-default `shuffled_msbs` fallback (which always made
        # out_dir non-empty regardless of user setup).
        if not out_dir.strip():
            messagebox.showerror("Output directory not set",
                "Please pick an output directory for the shuffled MSBs.\n\n"
                "Typical choice is your me3 mod profile's map/mapstudio/ folder.\n"
                "If you set the me3 package path, the output dir auto-fills "
                "from it — leave the field empty and re-pick the me3 path, "
                "or type/Browse a custom output dir.")
            return
        try:
            os.makedirs(out_dir, exist_ok=True)
        except PermissionError:
            messagebox.showerror("Output dir — permission denied",
                f"Can't create the output directory:\n  {out_dir}\n\n"
                f"Windows is blocking writes to that path. Common causes:\n"
                f"  • Path is inside Program Files / a system folder. Pick a\n"
                f"    location under your user profile instead (Documents,\n"
                f"    Desktop, or anywhere on a non-system drive).\n"
                f"  • Antivirus is blocking the writer. Add Python or this\n"
                f"    folder to your AV's exclusion list.\n"
                f"  • A read-only flag was set on a parent directory.")
            return
        except FileNotFoundError:
            # makedirs(exist_ok=True) only raises FileNotFoundError if a
            # parent directory in the path is itself missing AND can't be
            # created — usually because the drive doesn't exist (typo'd
            # drive letter) or a symlink in the path is broken.
            messagebox.showerror("Output dir — invalid path",
                f"The output directory's parent doesn't exist:\n  {out_dir}\n\n"
                f"Most likely you typo'd a drive letter (D:\\ when you meant\n"
                f"C:\\), or the path refers to a removable drive that isn't\n"
                f"mounted. Try Browse... to pick a real folder.")
            return
        except OSError as e:
            messagebox.showerror("Output dir — couldn't create",
                f"Couldn't create the output directory:\n  {out_dir}\n\n"
                f"Filesystem error: {e}\n\n"
                f"Try a different location, ideally under your user profile.")
            return
        # Validate mod map folder if set — we don't auto-create it because
        # accidentally creating an empty directory inside someone's mod profile
        # would be confusing. If they typed a path, they meant a real folder.
        if mod_map_dir and not os.path.isdir(mod_map_dir):
            if not messagebox.askyesno(
                "Mod map folder doesn't exist",
                f"The mod map folder you picked doesn't exist:\n{mod_map_dir}\n\n"
                f"Skip the auto-copy step and just run the rando? "
                f"(Pick 'No' to cancel and fix the path.)"):
                return
            mod_map_dir = ''  # disable the copy step for this run

        # v0.23.56: optional vanilla mapstudio path for spawn-pool inclusion.
        spawn_pool_source_dir = self.spawn_pool_source_dir_var.get().strip()
        if spawn_pool_source_dir and not os.path.isdir(spawn_pool_source_dir):
            if not messagebox.askyesno(
                "Vanilla mapstudio folder doesn't exist",
                f"The vanilla mapstudio folder you picked doesn't exist:\n"
                f"{spawn_pool_source_dir}\n\n"
                f"Skip the spawn-pool auto-include step and just run the rando? "
                f"(Pick 'No' to cancel and fix the path.) "
                f"Skipping means rotation bosses (BBH at Castle Basement, "
                f"Tree Sentinels in the field, Death Rite Bird, etc.) will "
                f"appear in their vanilla form."):
                return
            spawn_pool_source_dir = ''  # disable for this run

        # Persist folder picks for next launch
        self._save_settings(
            input_dir=in_dir,
            output_dir=out_dir,
            mod_map_dir=mod_map_dir,
            spawn_pool_source_dir=spawn_pool_source_dir,
            oops_all_nb_target=self.oops_all_nb_target_var.get(),
            oops_all_nb_scope=self.oops_all_nb_scope_var.get(),
            multiplayer_safe=bool(self.multiplayer_safe_var.get()))

        # v0.19.21: Run button becomes a Cancel button while the worker
        # is active. Clicking it sets the cancel flag in the engine; the
        # worker exits gracefully at the next per-map checkpoint.
        self.run_btn.config(text="✕   Cancel", state='normal',
                             command=self._cancel_shuffle)
        self.status_var.set("Running rando…")

        # Resolve Oops! All target if mode is Oops! All
        oops_all_target_cp = None
        oops_all_nb_target_cp = None
        oops_all_nb_marker_scope = None
        run_mode = self.run_mode_var.get()
        if run_mode.startswith("Oops! All NB"):
            picked = self.oops_all_nb_target_var.get().strip()
            if not picked:
                messagebox.showerror(
                    "No target picked",
                    "Oops! All NB mode requires picking a target enemy "
                    "from the dropdown.")
                self.run_btn.config(text="⚙   Randomize", state='normal',
                                     command=self._run_shuffle)
                self.status_var.set("Ready")
                return
            oops_all_nb_target_cp = self.oops_all_lookup.get(picked, picked.split()[0])
            oops_all_nb_marker_scope = self.oops_all_nb_scope_var.get() or 'broad'
        elif run_mode.startswith("Oops"):
            picked = self.oops_all_target_var.get().strip()
            if not picked:
                messagebox.showerror(
                    "No target picked",
                    "Oops! All mode requires picking a target enemy from the dropdown.")
                self.run_btn.config(text="⚙   Randomize", state='normal',
                                     command=self._run_shuffle)
                self.status_var.set("Ready")
                return
            # Resolve display string back to c_prefix; also accept a raw c_prefix
            oops_all_target_cp = self.oops_all_lookup.get(picked, picked.split()[0])

        # v0.20.67: Validation mode — rats at on-mesh slots (the
        # "should-be-safe" slots), jellies at off-mesh slots (the
        # "fragile" slots). Stress-tests the slot classification by
        # placing a known-broken c-prefix everywhere we consider
        # placement-safe; if any of those slots actually freeze, they
        # need to be marked off-mesh / V3_PROBLEM_SLOTS.
        #
        # v0.23.71: c-prefix choices moved to engine (V3_VALIDATION_
        # TERRAIN_TEST_TARGETS). GUI no longer hardcodes 'c4090' and
        # 'c4180' — those are content/balance decisions about which
        # the engine has authoritative knowledge of SENSITIVE / safe
        # status.
        terrain_test_targets = None
        if self.run_mode_var.get().startswith("Validation"):
            terrain_test_targets = dict(DEFAULT_VALIDATION_TERRAIN_TEST_TARGETS)

        # Snapshot config for the worker
        config = {
            'seed': seed,
            'in_dir': in_dir,
            'out_dir': out_dir,
            'mod_map_dir': mod_map_dir,
            'spawn_pool_source_dir': spawn_pool_source_dir,
            'excluded': set(self.excluded),
            'hub_maps': set(self.hub_maps),
            'oops_all_target_cp': oops_all_target_cp,
            'oops_all_nb_target_cp': oops_all_nb_target_cp,
            'oops_all_nb_marker_scope': oops_all_nb_marker_scope,
            'multiplayer_safe': bool(self.multiplayer_safe_var.get()),
            'disable_resilient_filter': bool(self.disable_resilient_filter_var.get()),
            'prefer_canonical_variants': bool(self.prefer_canonical_variants_var.get()),
            'randomize_safe_nb_arenas': bool(self.randomize_safe_nb_arenas_var.get()),
            'randomize_all_nb_arenas': bool(self.randomize_all_nb_arenas_var.get()),
            # v0.20.38: auto-couple non_fragile_baseline_cp to the diagnostic
            # checkbox. When diagnostic is ON, force every non-fragile slot
            # to the engine's V3_DEFAULT_NON_FRAGILE_BASELINE_CP (Leyndell
            # Foot Soldier) so the world is visually uniform at safe slots
            # and any non-baseline enemy in-game is by construction a
            # fragile-slot test placement. Off when diagnostic is off —
            # production runs randomize normally.
            #
            # v0.23.71: c-prefix used to be hardcoded as 'c4373' here in
            # the GUI. Moved to the engine constant so balance/content
            # decisions live next to other engine constants and the GUI
            # stays a thin presentation layer.
            'non_fragile_baseline_cp': (DEFAULT_NON_FRAGILE_BASELINE_CP
                                         if self.disable_resilient_filter_var.get()
                                         else None),
            # v0.20.42: parse the batch text entry into a set, or None
            # if empty/whitespace.
            'diagnostic_test_targets': self._parse_diag_test_targets(),
            # v0.23.05: user-managed force-include set. Bypasses the engine's
            # V3_EXCLUDE_TARGET_PREFIXES + V3_GHOST_EXCLUDE_TARGET_PREFIXES
            # for the listed c-prefixes. Tier-preserve still applies, so a
            # field_boss-tier force-include only lands at boss-tier slots.
            # Empty list = vanilla pool.
            'force_include_targets': frozenset(self.force_include_targets) or None,
            # v0.20.67: validation mode dict, or None if mode != Validation.
            'terrain_test_targets': terrain_test_targets,
            'merchant_model_swap': bool(self.merchant_model_swap_var.get()),
            # v0.23.19: Cinematic Chaos — asymmetric NB-tier gating.
            # See chaos_mode_var declaration in __init__ for full semantics.
            'chaos_mode': bool(self.chaos_mode_var.get()),
            # v0.26.15: mount/rider detection (cut 1 — audit only).
            'mount_rider_swap': bool(self.mount_rider_swap_var.get()),
        }

        # v0.20.89: clear any lingering cancel flag from a prior cancelled
        # run before starting the worker. Without this reset, the second
        # "Randomize" click after a cancellation would inherit
        # set_cancel_requested(True) from the previous run and the worker
        # would exit at its first checkpoint with no apparent action taken.
        # Symptom that surfaced this: "after you hit the gui cancel button
        # once, you can't randomize until you restart the gui".
        try:
            import oops_v3
            oops_v3.set_cancel_requested(False)
        except Exception:
            pass

        self.worker_thread = threading.Thread(
            target=self._worker, args=(config,), daemon=True)
        self.worker_thread.start()

    def _worker(self, config):
        """Background thread that runs the shuffle. Communicates via log_queue."""
        try:
            self.log_queue.put(f"\n--- Run started ---\n")
            if config.get('terrain_test_targets'):
                tts = config['terrain_test_targets']
                mode_label = (f"Validation (on_mesh→{tts['on_mesh']}, "
                              f"off_mesh→{tts['off_mesh']})")
            elif config['oops_all_target_cp']:
                mode_label = f"Oops! All {config['oops_all_target_cp']}"
            elif config.get('oops_all_nb_target_cp'):
                mode_label = (f"Oops! All NB {config['oops_all_nb_target_cp']} "
                              f"(scope={config.get('oops_all_nb_marker_scope','broad')})")
            else:
                mode_label = "Standard"
            self.log_queue.put(f"Seed: {config['seed']}, mode: {mode_label}\n")
            self.log_queue.put(f"Input:  {config['in_dir']}\n")
            self.log_queue.put(f"Output: {config['out_dir']}\n")

            try:
                oops_v3 = _import_backend()
            except Exception as e:
                self.log_queue.put(f"ERROR: could not import backend: {e}\n")
                self.log_queue.put(traceback.format_exc())
                return

            # v0.20.27: pass user overrides as kwargs to the engine —
            # excluded_prefixes / hub_maps / multiplayer_safe are now
            # engine-side concerns. The GUI no longer mutates module-
            # level oops_v3.V3_* sets. The earlier save-and-restore
            # pattern leaked state if the engine raised mid-run; the
            # engine wrapper now handles the swap-and-restore itself.
            if config.get('multiplayer_safe'):
                self.log_queue.put(
                    "Multiplayer-safe: ON — heritage chrs blocked\n")
            else:
                self.log_queue.put(
                    "Multiplayer-safe: OFF — heritage chrs allowed "
                    "(every coop partner needs the heritage pack)\n")
            # v0.23.41: Surface MMV manifest state. Users without MMV won't
            # notice the engine "mmv_imports: skipped" line buried in startup
            # output; users WITH MMV who haven't enabled the manifest will
            # wonder why no cross-game bosses appear. A clear banner solves
            # both confusions.
            try:
                import json as _json, os as _os
                # v0.23.71: route through _data_path() — resolves from
                # data/ when present, root for legacy installs.
                _mmv_path = _data_path('mmv_imports.json')
                if _os.path.isfile(_mmv_path):
                    with open(_mmv_path, encoding='utf-8') as _f:
                        _mmv_meta = _json.load(_f).get('_meta', {})
                    if _mmv_meta.get('enabled'):
                        self.log_queue.put(
                            "MMV integration: ON — cross-game bosses in pool "
                            "(requires More Map Variations installed in me3)\n")
                    else:
                        self.log_queue.put(
                            "MMV integration: OFF — vanilla NR + DLC content only "
                            "(enable via mmv_imports.json _meta.enabled=true if "
                            "you have MMV installed)\n")
            except Exception:
                pass
            if config.get('disable_resilient_filter'):
                self.log_queue.put(
                    "*** DIAGNOSTIC: disable_resilient_filter=ON — fragile slots "
                    "use UNTESTED-only filter (pool - RESILIENT - SENSITIVE). "
                    "Expect new freezes ***\n")
            if config.get('non_fragile_baseline_cp'):
                self.log_queue.put(
                    f"*** DIAGNOSTIC BASELINE: non_fragile_baseline_cp="
                    f"{config['non_fragile_baseline_cp']} — non-fragile slots "
                    f"forced to a single c-prefix. Anything visually different "
                    f"in-game IS a fragile-slot test ***\n")
            if config.get('diagnostic_test_targets'):
                tts = sorted(config['diagnostic_test_targets'])
                self.log_queue.put(
                    f"*** DIAGNOSTIC BATCH: fragile slots restricted to "
                    f"{len(tts)} explicit c-prefixes — {', '.join(tts)} ***\n"
                    f"*** Any CTD this run is attributable to one of those. ***\n")
            if config.get('chaos_mode'):
                self.log_queue.put(
                    "*** CINEMATIC CHAOS: chaos_mode=ON — Night Boss chrs "
                    "are eligible at field slots; Night arenas tightened to "
                    "the strict NB-only set ***\n")
            if config.get('oops_all_nb_target_cp'):
                scope_descs = {
                    'strict': 'strict (Night Boss anchors only)',
                    'broad': 'broad (NB+Field+POI bosses)',
                    'extended': ('extended (broad + Castle interior + Basement + '
                                 'Encampments + Cathedrals + Mountaintop + '
                                 'Underground Forts + Group Bosses + bare '
                                 '(Boss) Nightlord forms)'),
                }
                scope = config.get('oops_all_nb_marker_scope', 'broad')
                self.log_queue.put(
                    f"*** OOPS! ALL NB: every boss-tier slot under "
                    f"{scope_descs.get(scope, scope)} forced to "
                    f"{config['oops_all_nb_target_cp']}. ***\n"
                    f"*** Field/grunt slots randomize normally; this is a "
                    f"surgical CTD-isolation mode for cross-game imports. ***\n")

            # Common kwargs for both DCX and direct paths.
            engine_kwargs = dict(
                seed=config['seed'],
                oops_all_target_cp=config['oops_all_target_cp'],
                oops_all_nb_target_cp=config.get('oops_all_nb_target_cp'),
                oops_all_nb_marker_scope=config.get('oops_all_nb_marker_scope'),
                merchant_model_swap=config['merchant_model_swap'],
                excluded_prefixes=set(config['excluded']),
                hub_maps=set(config['hub_maps']),
                multiplayer_safe=bool(config.get('multiplayer_safe')),
                disable_resilient_filter=bool(config.get('disable_resilient_filter')),
                non_fragile_baseline_cp=config.get('non_fragile_baseline_cp'),
                diagnostic_test_targets=config.get('diagnostic_test_targets'),
                terrain_test_targets=config.get('terrain_test_targets'),
                force_include_targets=config.get('force_include_targets'),
                chaos_mode=bool(config.get('chaos_mode')),
                mount_rider_swap=bool(config.get('mount_rider_swap')),
            )

            # Temporarily redirect the backend's prints to our log queue
            import io
            buf = io.StringIO()
            old_stdout = sys.stdout
            class StreamingBuf:
                def __init__(self, q):
                    self.q = q
                    self._partial = ''
                def write(self, s):
                    # Stream lines as they come in
                    self._partial += s
                    while '\n' in self._partial:
                        line, self._partial = self._partial.split('\n', 1)
                        self.q.put(line + '\n')
                def flush(self): pass
            sys.stdout = StreamingBuf(self.log_queue)
            try:
                # v0.26.16: variant-pool preference. Set before the
                # pipeline branch so it applies to both the DCX
                # (rando_pipeline) and raw-MSB (cmd_shuffle_v3) paths.
                import oops_v3
                oops_v3.V3_PREFER_CANONICAL_VARIANTS = bool(
                    config.get('prefer_canonical_variants', True))
                # Auto-detect input format: if the input dir has any .msb.dcx
                # files, run the full DCX pipeline (decompress → shuffle →
                # recompress). Otherwise treat as raw MSB input.
                has_dcx = any(f.endswith('.msb.dcx')
                              for f in os.listdir(config['in_dir']))
                if has_dcx:
                    self.log_queue.put(
                        "Detected .msb.dcx input — running full DCX pipeline\n")
                    import dcx_batch
                    # v0.24.0: EMEVD paths come straight from the Tk vars
                    # (which autopersist to .4laric_emevd_paths.json via
                    # trace_add). Both blank = Step 4 skipped gracefully.
                    # chr_to_nameid.json ships in data/ if built.
                    vanilla_emevd = self.vanilla_emevd_dir_var.get().strip()
                    output_emevd = self.output_emevd_dir_var.get().strip()
                    # v0.24.8: msg bundle paths for the FMG auto-splicer.
                    # Both blank = splice skipped; user must splice manually
                    # from healthbar_report['fmg_additions_path'].
                    vanilla_msg = self.vanilla_msg_bundle_var.get().strip()
                    mod_msg = self.mod_msg_bundle_var.get().strip()
                    # v0.24.105: fallback_nameid is now hardwired.
                    # Previously a GUI toggle (use_fallback_nameid_var); removed
                    # because off-state silently broke cross-game healthbar
                    # names (heritage Souls bosses, MMV imports, DLC chrs)
                    # by routing them to fresh-allocated FMG ids that the
                    # splice step often failed to apply, leaving the in-game
                    # display as "NPCName" placeholder text.
                    # See FALLBACK_NAMEID at the Tk-var init site.
                    #
                    # v0.24.106: this value is now used by dcx_batch as a
                    # safety net (Phase 3 re-patch), not as the primary
                    # nameId. When msg bundle paths are set and splice
                    # succeeds, per-chr names are used. Otherwise this
                    # value is written to all cross-game / heterogeneous-
                    # squad bars. Either way, the user never sees "NPCName".
                    fallback_nameid = self.fallback_nameid_value
                    chr_nameid = os.path.join(HERE, 'data', 'chr_to_nameid.json')
                    # v0.24.61: default the EMEVD overlay to the bundled
                    # patched_emevd/ directory if present. This carries
                    # emevd_patch.py output (common_func with semantic
                    # patches + per-map inline-script fixes) into the
                    # rando pipeline so those patches survive re-rolls
                    # instead of being clobbered. User can disable by
                    # deleting/renaming the dir.
                    bundled_overlay = os.path.join(HERE, 'patched_emevd')
                    emevd_overlay = (bundled_overlay
                                     if os.path.isdir(bundled_overlay) else None)
                    dcx_batch.rando_pipeline(
                        config['in_dir'], config['out_dir'],
                        spawn_pool_source_dir=config.get('spawn_pool_source_dir'),
                        emevd_vanilla_dir=vanilla_emevd or None,
                        emevd_out_dir=output_emevd or None,
                        emevd_overlay_dir=emevd_overlay,
                        vanilla_msg_bundle=vanilla_msg or None,
                        mod_msg_bundle=mod_msg or None,
                        fallback_nameid=fallback_nameid,
                        chr_to_nameid_path=chr_nameid if os.path.exists(chr_nameid) else None,
                        randomize_safe_nb_arenas=bool(config.get('randomize_safe_nb_arenas')),
                        randomize_all_nb_arenas=bool(config.get('randomize_all_nb_arenas')),
                        **engine_kwargs)
                else:
                    # cmd_shuffle_v3 takes (input_dir, output_dir, seed, ...)
                    # but seed lives in engine_kwargs — pop it for the
                    # positional slot.
                    kwargs_no_seed = {k: v for k, v in engine_kwargs.items()
                                      if k != 'seed'}
                    oops_v3.cmd_shuffle_v3(
                        config['in_dir'], config['out_dir'],
                        engine_kwargs['seed'],
                        **kwargs_no_seed)
            finally:
                sys.stdout = old_stdout

            self.log_queue.put(f"--- Run complete ---\n")

            # Auto-copy *.msb.dcx files to the user's mod profile if a path
            # was set. We deliberately copy ONLY .msb.dcx (the compressed
            # files the game loads), not .msb (intermediate decompressed),
            # not Yabber sidecars (.xml), and not spoiler files. The mod
            # profile only needs the .dcx files.
            mod_map_dir = config.get('mod_map_dir', '')
            if mod_map_dir:
                self._copy_to_mod_folder(config['out_dir'], mod_map_dir)

            # v0.26.x: Tier 3 UX #10 — emit a structured run-summary
            # payload right before __DONE__. The drain handler picks it
            # up and renders the "Last run" panel above the log so the
            # user sees a tidy "✓ N MSBs written, click Launch to play"
            # card instead of just a status-bar "Done" and a wall of
            # log text. Wrapped in try/except so a summary collection
            # failure (e.g. output dir unreadable) doesn't suppress
            # __DONE__ and leave the Run button stuck on "Cancel".
            try:
                summary = self._build_run_summary(config)
                self.log_queue.put(('__SUMMARY__', summary))
            except Exception as e:
                self.log_queue.put(
                    f"(post-run summary collection failed: {e})\n")
        except Exception as e:
            # v0.19.21: differentiate cancellation from real errors
            try:
                import oops_v3
                cancel_class = oops_v3.CancelledError
            except (ImportError, AttributeError):
                cancel_class = None
            if cancel_class is not None and isinstance(e, cancel_class):
                self.log_queue.put("Run cancelled by user. "
                                    "Output directory may contain partial files.\n")
                self.log_queue.put('__CANCELLED__')
                return
            self.log_queue.put(f"ERROR: {e}\n")
            self.log_queue.put(traceback.format_exc())
        finally:
            self.log_queue.put('__DONE__')

    def _copy_to_mod_folder(self, src_dir, dest_dir):
        """Copy *.msb.dcx files from src_dir into dest_dir.

        Runs on the worker thread (called from _worker after a successful
        shuffle). Logs to log_queue (not self._log) for thread-safety —
        anything from the worker thread must go through the queue.

        Existing files in dest_dir are overwritten. Other files in dest_dir
        (vanilla .dcx files for maps the rando didn't process, like hub
        passthrough maps) are left alone — we only touch files we generate.

        v0.24.10: if src_dir and dest_dir resolve to the same path (the
        common case when the rando writes directly to the me3 package's
        map/mapstudio/ dir — which is what v0.24.9's parent-path
        derivation defaults to), skip the copy entirely. Without this,
        shutil.copy2 raises WinError 32 for every file ("being used by
        another process") since copying to itself is undefined behavior
        on Windows.
        """
        import shutil
        # Normalize both paths so mixed slash conventions, case, and
        # symlinks/junctions don't trip us up.
        try:
            src_canon = os.path.normcase(os.path.realpath(src_dir))
            dst_canon = os.path.normcase(os.path.realpath(dest_dir))
        except OSError:
            src_canon = os.path.normcase(os.path.normpath(src_dir))
            dst_canon = os.path.normcase(os.path.normpath(dest_dir))
        if src_canon == dst_canon:
            self.log_queue.put(
                f"\nSkipping auto-copy: Output and Mod map are the same folder.\n"
                f"   {dest_dir}\n"
                f"   The rando wrote .msb.dcx files there directly.\n"
                f"\nLaunch the game via me3 to test.\n")
            return

        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as e:
            self.log_queue.put(f"Could not create mod map folder: {e}\n")
            return

        try:
            files = sorted(f for f in os.listdir(src_dir)
                           if f.endswith('.msb.dcx'))
        except OSError as e:
            self.log_queue.put(f"Could not list output folder: {e}\n")
            return

        if not files:
            self.log_queue.put(
                f"No .msb.dcx files found in output folder — "
                f"is the rando set up to compress to .dcx?\n")
            self.log_queue.put(
                f"  (output: {src_dir})\n")
            return

        self.log_queue.put(
            f"\nCopying {len(files)} .msb.dcx files to mod folder…\n")
        n_copied = 0
        n_failed = 0
        for f in files:
            src = os.path.join(src_dir, f)
            dst = os.path.join(dest_dir, f)
            try:
                shutil.copy2(src, dst)
                n_copied += 1
            except OSError as e:
                self.log_queue.put(f"  Failed to copy {f}: {e}\n")
                n_failed += 1

        if n_failed == 0:
            self.log_queue.put(
                f"✓ Copied {n_copied} files to mod folder.\n")
            self.log_queue.put(
                f"   {dest_dir}\n")
            self.log_queue.put(
                f"\nLaunch the game via me3 to test.\n")
        else:
            self.log_queue.put(
                f"Copied {n_copied} of {len(files)} files; "
                f"{n_failed} failures (see above).\n")

    # ------------------------------------------------------------------
    # v0.26.x: Tier 3 UX #10 — Post-run summary panel
    # ------------------------------------------------------------------
    # After a successful generate, render a tidy panel above the log
    # showing what was written, where the spoiler lives, and a prominent
    # Launch button. Closes the "what did I just make and what should
    # I do now?" gap that current "Done" status leaves open.

    @staticmethod
    def _count_msb_dcx_in_dir(directory):
        """Pure helper — count .msb.dcx files in a directory. Returns
        the count, or 0 if the directory doesn't exist / can't be read.
        Used by _build_run_summary to report how many MSBs the engine
        wrote. Defensive: never raises."""
        if not directory or not os.path.isdir(directory):
            return 0
        try:
            return sum(1 for f in os.listdir(directory)
                       if f.lower().endswith('.msb.dcx'))
        except OSError:
            return 0

    @staticmethod
    def _find_spoiler_for_run(out_dir, seed):
        """Pure helper — locate the spoiler file the engine just wrote.
        Engine writes <out_dir>/_spoilers.json (since v0.20.0); older
        per-seed naming conventions are still checked as a fallback for
        archived runs.
        Returns the absolute path if found, or None.
        Defensive: never raises."""
        if not out_dir:
            return None
        candidates = [
            # Canonical name written by write_spoiler_logs
            os.path.join(out_dir, '_spoilers.json'),
            # Historical / per-seed naming patterns
            os.path.join(out_dir, f'spoiler_{seed}.json'),
            os.path.join(out_dir, f'spoiler.{seed}.json'),
            os.path.join(out_dir, 'spoiler.json'),
            os.path.join(os.path.dirname(out_dir.rstrip(os.sep)),
                          'spoilers', f'{seed}.json'),
        ]
        for path in candidates:
            try:
                if os.path.isfile(path):
                    return path
            except OSError:
                continue
        # Last resort: glob for spoiler-shaped names in out_dir
        try:
            for name in os.listdir(out_dir):
                low = name.lower()
                if (low.startswith('spoiler') or low.startswith('_spoiler')) \
                        and low.endswith('.json'):
                    return os.path.join(out_dir, name)
        except OSError:
            pass
        return None

    def _build_run_summary(self, config):
        """Collect post-run summary data into a dict. Reads from the
        passed-in config plus filesystem state of the output dir.

        Runs on the worker thread (called from _worker right before
        __DONE__), so no Tk access. Keep it side-effect-free aside
        from the os.listdir calls in the helpers.

        Returns a dict with keys:
          seed         int — the seed used
          mode_label   str — human-readable mode (e.g. 'Standard',
                         'Oops! All Nightreign')
          out_dir      str — output directory (absolute path)
          mod_map_dir  str — me3 mod map dir if mirror-copy happened
          msb_count    int — number of .msb.dcx in out_dir
          spoiler_path str|None — full path to the spoiler JSON
          multiplayer_safe  bool
          heritage_enabled  bool — whether MMV / heritage modes ran
        """
        out_dir = config.get('out_dir', '') or ''
        seed = config.get('seed', 0)
        # Mode label: prefer the human-readable form if present,
        # else derive from the run_mode key
        mode_label = config.get('mode_label') or config.get('run_mode', 'Standard')
        if config.get('oops_all_target_cp'):
            mode_label = f"Oops! All — {config['oops_all_target_cp']}"
        elif config.get('oops_all_nb_target_cp'):
            mode_label = (f"Oops! All NB — {config['oops_all_nb_target_cp']} "
                          f"({config.get('oops_all_nb_marker_scope', 'broad')})")

        return {
            'seed':        seed,
            'mode_label':  mode_label,
            'out_dir':     out_dir,
            'mod_map_dir': config.get('mod_map_dir', '') or '',
            'msb_count':   self._count_msb_dcx_in_dir(out_dir),
            'spoiler_path': self._find_spoiler_for_run(out_dir, seed),
            'multiplayer_safe': bool(config.get('multiplayer_safe')),
            'heritage_enabled': bool(
                config.get('chr_target_dir')
                or config.get('spawn_pool_source_dir')),
        }

    def _hide_post_run_summary(self):
        """Clear the post-run summary panel. Called from _run_shuffle at
        the start of a new run so the old "Last run" panel doesn't sit
        there stale while the new run is in progress — gets re-populated
        by _render_run_summary when the new run completes and pushes a
        __SUMMARY__ tuple onto the log queue.

        Safe to call when the host frame doesn't exist yet (older
        _build_main_tab path) or has no children (first run after
        startup). v0.26.4: method body added — call site existed in
        _run_shuffle since v0.26.x but the method definition was
        missed, producing AttributeError on every Randomize click."""
        if not hasattr(self, '_summary_frame_host') or self._summary_frame_host is None:
            return
        try:
            for child in self._summary_frame_host.winfo_children():
                child.destroy()
        except tk.TclError:
            # Frame torn down (window closing during run) — silently OK
            pass

    def _render_run_summary(self, summary):
        """Materialize (or update) the post-run summary panel above the
        log. Called from _drain_log_queue when it pulls a __SUMMARY__
        tuple off the queue. Runs on the GUI thread."""
        if not hasattr(self, '_summary_frame_host') or self._summary_frame_host is None:
            # Host frame was never created (older _build_main_tab path).
            # Bail silently — the user still gets the log, just no panel.
            return
        # Clear any previous summary panel (re-runs overwrite, not stack)
        for child in self._summary_frame_host.winfo_children():
            child.destroy()

        panel = ttk.LabelFrame(self._summary_frame_host,
                                text="Last run", padding=10)
        panel.pack(fill='x', pady=(0, 4))

        # Headline — "✓ N MSBs written"
        headline = ttk.Frame(panel); headline.pack(fill='x', pady=(0, 6))
        ttk.Label(headline, text='✓',
                  foreground=THEME.get('success', '#4caf50'),
                  background=THEME.get('bg', '#1e1e1e'),
                  font=(self.ui_font, 14, 'bold')
                  ).pack(side='left', padx=(0, 6))
        ttk.Label(headline,
                  text=(f"Randomized {summary['msb_count']} MSB"
                        f"{'s' if summary['msb_count'] != 1 else ''}"
                        f" — seed {summary['seed']}, mode "
                        f"{summary['mode_label']}"),
                  foreground=THEME.get('success', '#4caf50'),
                  background=THEME.get('bg', '#1e1e1e'),
                  font=(self.ui_font, 11, 'bold')
                  ).pack(side='left')

        # Details — labeled rows
        details = ttk.Frame(panel); details.pack(fill='x', pady=2)
        self._summary_add_row(details, 'Output:',
                               summary['out_dir'],
                               open_action=summary['out_dir'])
        if summary['mod_map_dir']:
            self._summary_add_row(details, 'Mod map:',
                                   summary['mod_map_dir'],
                                   open_action=summary['mod_map_dir'])
        if summary['spoiler_path']:
            spoiler_row = ttk.Frame(details); spoiler_row.pack(fill='x', pady=1)
            ttk.Label(spoiler_row, text='Spoiler:', width=10,
                      style='Dim.TLabel').pack(side='left')
            ttk.Label(spoiler_row, text=summary['spoiler_path'],
                      wraplength=540, justify='left'
                      ).pack(side='left', fill='x', expand=True, padx=(0, 8))
            ttk.Button(spoiler_row, text="View",
                       command=lambda p=summary['spoiler_path']:
                           self._open_spoiler_in_viewer(p),
                       width=6
                       ).pack(side='right', padx=(0, 2))
            ttk.Button(spoiler_row, text="Open",
                       command=lambda p=summary['spoiler_path']:
                           self._open_in_file_manager(p),
                       width=6
                       ).pack(side='right')
        else:
            self._summary_add_row(details, 'Spoiler:',
                                   '(not found in expected locations)')

        flags = []
        if summary['multiplayer_safe']:
            flags.append('multiplayer-safe')
        if summary['heritage_enabled']:
            flags.append('heritage imports')
        if flags:
            self._summary_add_row(details, 'Options:',
                                   ' · '.join(flags))

        # v0.26.x: post-run reminder of the recommended expedition
        # guidance. The Generate-tab banner shows this BEFORE the run;
        # this surfaces it again RIGHT BEFORE launch — last chance to
        # remind users to pick Tricephalos instead of the buggy ones.
        # Suppressed if validation is complete or the user dismissed
        # the banner (same conditions as the banner).
        if (self.RECOMMENDED_EXPEDITION_ACTIVE
                and not self.recommended_expedition_dismissed_var.get()):
            tip_row = ttk.Frame(panel); tip_row.pack(fill='x', pady=(6, 0))
            ttk.Label(tip_row,
                text='💡 ' + self.RECOMMENDED_EXPEDITION_SHORT,
                style='Dim.TLabel',
                wraplength=720, justify='left').pack(anchor='w')

        # Action row — Launch button (prominent, the natural next step)
        actions = ttk.Frame(panel); actions.pack(fill='x', pady=(8, 0))
        launch_btn = ttk.Button(actions, text="🎮  Launch via ME3",
                                command=self._launch_via_me3,
                                style='Accent.TButton')
        launch_btn.pack(side='left', ipady=2)
        Tooltip(launch_btn,
                "Launch Nightreign with this generated mod profile "
                "loaded through ME3. Same as the Launch button at the "
                "top of the tab.")

    def _summary_add_row(self, parent, label, value, open_action=None):
        """Add a labeled detail row to the summary panel. If
        open_action is a filesystem path, an "Open" button appears
        next to the row that opens the file or its parent dir in
        the OS file manager."""
        row = ttk.Frame(parent); row.pack(fill='x', pady=1)
        ttk.Label(row, text=label, width=10,
                  style='Dim.TLabel').pack(side='left')
        ttk.Label(row, text=value, wraplength=620, justify='left'
                  ).pack(side='left', fill='x', expand=True, padx=(0, 8))
        if open_action:
            ttk.Button(row, text="Open",
                       command=lambda p=open_action: self._open_in_file_manager(p),
                       width=6
                       ).pack(side='right')

    def _open_in_file_manager(self, path):
        """Open the given path in the OS file manager. For a file,
        opens its containing directory and (on platforms that support
        it) selects the file. Best-effort across platforms; silently
        falls back to opening the parent dir when selection isn't
        supported."""
        import subprocess
        if not path or not os.path.exists(path):
            messagebox.showinfo("Path not found",
                f"Couldn't open:\n  {path}\n\nIt may have been moved "
                f"or deleted since the run finished.")
            return
        try:
            if sys.platform == 'win32':
                # Windows: explorer /select,<file> selects the file
                if os.path.isfile(path):
                    subprocess.Popen(['explorer', '/select,', path])
                else:
                    subprocess.Popen(['explorer', path])
            elif sys.platform == 'darwin':
                # macOS: open -R reveals in Finder
                if os.path.isfile(path):
                    subprocess.Popen(['open', '-R', path])
                else:
                    subprocess.Popen(['open', path])
            else:
                # Linux: xdg-open the parent directory (file selection
                # isn't standardised across file managers)
                target = path if os.path.isdir(path) else os.path.dirname(path)
                subprocess.Popen(['xdg-open', target])
        except (OSError, FileNotFoundError) as e:
            messagebox.showerror("Couldn't open path",
                f"OS error opening:\n  {path}\n\n{e}")

    def _drain_log_queue(self):
        """Pull pending log lines from worker thread into the GUI text widget."""
        try:
            while True:
                item = self.log_queue.get_nowait()
                # v0.26.x: tuple-form messages carry structured payloads
                # alongside the legacy string log lines. Currently used for
                # ('__SUMMARY__', dict) — the run-summary payload that
                # populates the post-run panel. Pattern is extensible for
                # any future structured signals from the worker.
                if isinstance(item, tuple) and len(item) == 2:
                    tag, payload = item
                    if tag == '__SUMMARY__':
                        try:
                            self._render_run_summary(payload)
                        except Exception as e:
                            self._log(f"(summary render failed: {e})\n",
                                       'warn')
                    else:
                        # Unknown tuple tag — log it for debugging
                        self._log(f"(unknown queue tag: {tag!r})\n", 'dim')
                    continue
                if item == '__DONE__':
                    self.run_btn.config(text="⚙   Randomize",
                                         state='normal',
                                         command=self._run_shuffle)
                    if self.status_var.get() != "Cancelled":
                        self.status_var.set("Done")
                        # v0.26.x: auto-launch hook. Only fires on a
                        # clean completion (Cancelled runs skip it —
                        # there's nothing meaningful to launch into).
                        # _launch_via_me3 with from_auto_launch=True
                        # logs failures inline instead of popping a
                        # modal over the just-finished output.
                        if (hasattr(self, 'auto_launch_after_generate_var')
                                and self.auto_launch_after_generate_var.get()):
                            try:
                                self._launch_via_me3(from_auto_launch=True)
                            except Exception as e:
                                self._log(
                                    f"Auto-launch raised: {e}\n", 'warn')
                elif item == '__CANCELLED__':
                    # v0.19.21: distinct status from successful completion
                    self.status_var.set("Cancelled")
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

    def _log(self, msg, tag=None):
        """Append a line to the log. If tag is None, auto-detect by content."""
        if tag is None:
            low = msg.lower()
            if 'error' in low or 'traceback' in low or 'failed' in low:
                tag = 'error'
            elif 'warn' in low or 'skipped' in low:
                tag = 'warn'
            elif msg.startswith('---') or msg.startswith('==='):
                tag = 'accent'
            elif 'processed' in low or 'complete' in low or 'done' in low:
                tag = 'success'
            elif msg.startswith('  ') or 'detected' in low or 'building' in low:
                tag = 'info'
        self.log.config(state='normal')
        if tag:
            self.log.insert('end', msg, tag)
        else:
            self.log.insert('end', msg)
        self.log.see('end')
        self.log.config(state='disabled')


class SplashWindow:
    """Small undecorated window shown during RandoGUI initialization.

    The first launch and any cold-cache run takes ~0.5–2 seconds while
    _load_data parses JSON files and _build_ui constructs ~6 tabs of
    widgets. Without feedback, the user sees a blank/grey window (or
    on Windows, a "Not Responding" hint) and may think the app froze.

    Usage:
        splash = SplashWindow(root)
        splash.update_status("Loading data files…")
        # ... slow init ...
        splash.update_status("Building interface…")
        # ... slow init ...
        splash.close()

    Each update_status call forces a Tk repaint via update_idletasks,
    so the user sees the message progress as actual milestones get hit
    rather than the splash freezing on the first message.
    """

    def __init__(self, root):
        self.root = root
        self.top = tk.Toplevel(root)
        # overrideredirect strips the OS title bar / borders for a
        # clean splash-screen look. On some Linux WMs this also makes
        # the window not appear in the taskbar.
        try:
            self.top.overrideredirect(True)
        except tk.TclError:
            pass
        # Always-on-top so a slow init doesn't bury the splash behind
        # other windows the user clicks on while waiting.
        try:
            self.top.attributes('-topmost', True)
        except tk.TclError:
            pass

        # Theme: match the main app's dark theme if THEME exists
        bg = THEME.get('bg', '#1e1e1e') if 'THEME' in globals() else '#1e1e1e'
        fg = THEME.get('text', '#e0e0e0') if 'THEME' in globals() else '#e0e0e0'
        dim = THEME.get('text_dim', '#888') if 'THEME' in globals() else '#888'
        accent = THEME.get('accent', '#d4a017') if 'THEME' in globals() else '#d4a017'

        # Size + center on screen (NOT on root, which may not be
        # sized/positioned yet — first launch root has default position)
        W, H = 380, 160
        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        x = (sw - W) // 2
        y = (sh - H) // 2
        self.top.geometry(f'{W}x{H}+{x}+{y}')
        self.top.configure(bg=bg)

        # Content
        outer = tk.Frame(self.top, bg=bg, padx=24, pady=20)
        outer.pack(fill='both', expand=True)
        title = tk.Label(outer, text="Oops! All Random",
                          bg=bg, fg=fg,
                          font=('TkDefaultFont', 14, 'bold'))
        title.pack(anchor='w')
        subtitle = tk.Label(outer,
                             text="Nightreign Enemy Randomizer",
                             bg=bg, fg=dim,
                             font=('TkDefaultFont', 10))
        subtitle.pack(anchor='w', pady=(0, 14))

        self._status_var = tk.StringVar(value='Starting up…')
        self._status_label = tk.Label(outer, textvariable=self._status_var,
                                       bg=bg, fg=accent,
                                       font=('TkDefaultFont', 10),
                                       anchor='w')
        self._status_label.pack(fill='x')

        # Thin separator + version line for visual interest
        sep = tk.Frame(outer, bg=dim, height=1)
        sep.pack(fill='x', pady=(12, 6))
        version = tk.Label(outer, text='v0.20.90 — 4laric',
                            bg=bg, fg=dim,
                            font=('TkDefaultFont', 8))
        version.pack(anchor='w')

        # Initial paint so the splash appears before any heavy work
        self._paint()

    def update_status(self, msg):
        """Update the status line and force a repaint. Safe to call
        from any point during init — if the splash has already been
        closed (or never shown), silently no-ops."""
        try:
            self._status_var.set(msg)
            self._paint()
        except tk.TclError:
            pass  # splash was closed; carry on

    def _paint(self):
        try:
            self.top.update_idletasks()
            self.top.update()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass


def main():
    # v0.26.x: --setup CLI flag forces the first-launch wizard even if
    # saved paths exist. Useful when the user wants to redo setup or
    # debug discovery on a machine where things have moved.
    import argparse
    parser = argparse.ArgumentParser(
        description="4laric's Nightreign enemy randomizer")
    parser.add_argument('--setup', action='store_true',
        help='Force the first-launch setup wizard regardless of saved config')
    args, _unknown = parser.parse_known_args()

    root = tk.Tk()
    try:
        # Try a slightly nicer theme if available
        s = ttk.Style()
        if 'clam' in s.theme_names():
            s.theme_use('clam')
    except Exception:
        pass

    # v0.26.x: first-launch wizard (Tier 1 UX #2). Runs when no saved
    # root paths exist or when --setup is passed. Hides the main window
    # while it's open so the modal feels like its own start-up step
    # instead of a popup over a half-built GUI. Wizard writes its
    # config directly to .4laric_paths.json before RandoGUI's __init__
    # runs, so the saved-paths load flow picks it up naturally — no
    # extra plumbing required.
    saved = _load_saved_paths()
    if args.setup or should_run_wizard(saved):
        root.withdraw()  # hide main window during wizard
        try:
            wiz = FirstLaunchWizard(root, initial_config=saved)
            root.wait_window(wiz.top)
            # Persist whatever the user entered, even if they Skipped —
            # saves them from re-entering the same paths next launch.
            if wiz.config != saved:
                _save_paths_to_disk(wiz.config)
        except Exception as e:
            # Wizard failure mustn't block startup. Log and fall through.
            print(f"(setup wizard error: {e}; opening main GUI)",
                  file=sys.stderr)
        finally:
            root.deiconify()

    # v0.26.x: splash screen during RandoGUI init. The init does
    # ~0.5–2 seconds of file I/O + widget construction; without
    # feedback the user sees a blank window (or "Not Responding"
    # on Windows). The splash is undecorated, centered, and updates
    # its status message at each major milestone so the user can
    # see actual progress rather than guessing whether the app froze.
    splash = SplashWindow(root)
    try:
        RandoGUI(root, progress_callback=splash.update_status)
    finally:
        splash.close()

    # v0.26.x: bring the main window to the foreground. On Windows
    # particularly, the launching terminal (PowerShell, cmd, or a
    # double-click cmd flash) tends to stay in front of the newly-
    # created Tk window. The lift + topmost flicker is the standard
    # Tk trick: set topmost true, force focus, then set topmost false
    # after the event loop has had a chance to honor the raise. Without
    # the final false reset, the window would stay always-on-top, which
    # is annoying — we just want a one-time raise.
    try:
        root.lift()
        root.attributes('-topmost', True)
        root.focus_force()
        root.after_idle(root.attributes, '-topmost', False)
    except tk.TclError:
        pass  # non-fatal; cosmetic only

    root.mainloop()


if __name__ == '__main__':
    main()