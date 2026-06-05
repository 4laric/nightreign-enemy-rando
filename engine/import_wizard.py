"""Pure logic for the guided ER/MMV import wizard (proposal #2).

The wizard's job is to connect the diagnostic the resolver now produces —
"these imported chrs can't be placed because their assets/params aren't
installed" — to its remedy, the existing roster import (point at your
unpacked Elden Ring / MMV folders and copy the chrs in). This module holds
the parts with real correctness stakes so they're unit-testable without a
display:

  * missing_imports()      — which imported c-prefixes the rando can't
                             place right now, split by the pack that
                             defines them (heritage = ER-sourced, mmv =
                             MMV-mod-sourced).
  * cross_reference_plan() — given that missing set and a
                             plan_roster_import() result, what the import
                             WILL supply vs. what's still missing after
                             (in neither source — missing DLC / not
                             UXM-unpacked).
  * ERImportWizardModel    — the step state machine (detect -> sources ->
                             preview -> import) with advance/back gating,
                             so the Tk Toplevel stays a thin renderer.

The Toplevel front-end injects the actual plan/execute calls and the
source-folder strings; nothing here touches Tk.
"""
from __future__ import annotations

import json
import os


def _pack_prefixes(ns, fname):
    """Set of c-prefixes a pack JSON defines (its tags' keys). Membership is
    stable regardless of _meta.enabled — we only use it to attribute a
    missing c-prefix to the source that would supply it."""
    _data_path = ns['_data_path']
    path = _data_path(fname)
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, encoding='utf-8') as fh:
            pack = json.load(fh)
    except Exception:
        return set()
    return set((pack.get('tags') or {}).keys())


def missing_imports(ns, reg, roster, target_chr_dir):
    """Imported c-prefixes the rando currently can't place, split by origin.

    Uses resolve_available_roster: the union of imported chrs whose files
    aren't on disk (imported_absent) and chrs on disk whose every variant's
    param row is absent (no_target_after_params). Splits the union into:
        heritage : defined by heritage_pack.json   (the ER import supplies)
        mmv      : defined by mmv_imports.json      (the MMV folder supplies)
        other    : in neither pack (e.g. a paramless vanilla chr)
    Returns those sorted lists plus 'all' and the raw resolver result.
    """
    from engine.roster_resolve import resolve_available_roster
    res = resolve_available_roster(ns, reg, roster, target_chr_dir)
    missing = set(res['imported_absent']) | set(res['no_target_after_params'])
    heritage = _pack_prefixes(ns, 'heritage_pack.json')
    mmv = _pack_prefixes(ns, 'mmv_imports.json')
    return {
        'all': sorted(missing),
        'heritage': sorted(missing & heritage),
        'mmv': sorted(missing & mmv),
        'other': sorted(missing - heritage - mmv),
        'resolver': res,
    }


def cross_reference_plan(missing_all, plan):
    """Split the missing-import set against a plan_roster_import() result.

    plan['entries']     -> [{ 'cp', 'origin', ... }]  chrs a source folder has
    plan['unavailable'] -> [(cp, wanted_by), ...]     chrs in neither source

    Returns:
        will_supply  : missing chrs the import will copy in (with origin)
        still_missing: missing chrs in neither source (missing DLC / not
                       UXM-unpacked) — the rando keeps skipping these
        unaccounted  : missing chrs the plan neither copies nor flags as
                       unavailable (already-present edge cases)
    """
    missing = set(missing_all)
    origin_by_cp = {e['cp']: e.get('origin', '?')
                    for e in (plan.get('entries') or []) if 'cp' in e}
    unavail_cps = {cp for (cp, _by) in (plan.get('unavailable') or [])}
    entry_cps = set(origin_by_cp)
    will_supply = [{'cp': cp, 'origin': origin_by_cp[cp]}
                   for cp in sorted(missing & entry_cps)]
    still_missing = sorted(missing & unavail_cps)
    unaccounted = sorted(missing - entry_cps - unavail_cps)
    return {
        'will_supply': will_supply,
        'still_missing': still_missing,
        'unaccounted': unaccounted,
    }


class ERImportWizardModel:
    """Step state machine for the guided import wizard.

    Steps: detect -> sources -> preview -> import. The model holds the
    missing-import breakdown, the chosen source folders, and the computed
    preview, and gates forward navigation. It is pure (no Tk); the view
    renders `step`, reads the data, and calls advance()/back(). The view is
    responsible for calling the real plan function and feeding the result
    back via set_preview().
    """

    STEPS = ('detect', 'sources', 'preview', 'import')

    def __init__(self, missing, detection_available=True):
        self.missing = dict(missing)
        # When False (e.g. no installed regulation to check against), the
        # detect step can't enumerate what's missing; the wizard falls back
        # to a plain guided import, so 'detect' must not block advancing.
        self.detection_available = bool(detection_available)
        self._i = 0
        self.er_dir = ''
        self.mmv_dir = ''
        self.preview = None  # cross_reference_plan() result, once computed

    @property
    def step(self):
        return self.STEPS[self._i]

    @property
    def step_index(self):
        return self._i

    def set_sources(self, er_dir='', mmv_dir=''):
        self.er_dir = (er_dir or '').strip()
        self.mmv_dir = (mmv_dir or '').strip()

    def sources_valid(self):
        def _ok(d):
            return bool(d) and os.path.isdir(d)
        return _ok(self.er_dir) or _ok(self.mmv_dir)

    def set_preview(self, preview):
        self.preview = preview

    def can_advance(self):
        """Whether the Next/Preview/Import button is enabled on this step."""
        if self.step == 'detect':
            return (not self.detection_available) or bool(self.missing.get('all'))
        if self.step == 'sources':
            return self.sources_valid()
        if self.step == 'preview':
            return self.preview is not None          # must preview first
        return False                                 # 'import' is terminal

    def advance(self):
        if self.can_advance() and self._i < len(self.STEPS) - 1:
            self._i += 1
            return True
        return False

    def back(self):
        if self._i == 0:
            return False
        self._i -= 1
        # A preview is only valid for the sources it was computed from; going
        # back to (or past) the sources step invalidates it.
        if self._i <= self.STEPS.index('sources'):
            self.preview = None
        return True
