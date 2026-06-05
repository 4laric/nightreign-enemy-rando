"""Presence- and param-aware roster resolution.

The randomizer's roster is the set of enemy c-prefixes it *could* place, but
what it can *actually* place at generate time depends on two things the
roster alone doesn't capture:

  1. On-disk presence. Vanilla NR chrs always ship (packed or loose), so
     they're always available. Imported chrs (heritage pack + MMV) only
     exist if the user copied their assets in; detect_asset_packs is the
     presence authority, and the c-prefixes in each pack's 'missing' list
     are absent.
  2. Param-row backing. Each variant the engine writes to an MSB carries an
     explicit npc_param_id / think_param_id (PART_OFF_NPC_PARAM /
     PART_OFF_THINK_PARAM). If the installed regulation has no row for that
     id, the game CTDs or the chr is inert. This is the live-regulation
     upgrade of the static valid_think_param_ids guard — it checks the real
     installed regulation, both NpcParam and NpcThinkParam.

resolve_available_roster() folds both into one verdict so the generate-time
preflight, presence-gating, and the import wizard all share one source of
truth. It is pure: callers inject `ns` (the oops_v3 namespace, for
_data_path / detect_asset_packs), the loaded regulation (or None), the
roster, and the target chr dir.

Fail-open by design: reg=None (no installed regulation to check) means the
param layer is skipped and placeable == available, never blocking on
missing information. Variants whose id is 0 (no explicit param written) are
not gated.
"""
from __future__ import annotations

import json
import os


def _imported_prefixes(ns):
    """Union of c-prefixes defined by the two import packs (membership only,
    independent of enabled state — presence/absence is decided separately by
    detect_asset_packs)."""
    out = set()
    data_path = ns.get('_data_path')
    if data_path is None:
        return out
    for fname in ('heritage_pack.json', 'mmv_imports.json'):
        try:
            with open(data_path(fname), encoding='utf-8') as fh:
                out.update((json.load(fh).get('tags') or {}).keys())
        except (OSError, ValueError):
            continue
    return out


def _absent_prefixes(ns, target_chr_dir):
    """c-prefixes detect_asset_packs reports as not present on disk (the
    union of every pack's 'missing' list). Empty if detection is
    unavailable — callers treat that as 'nothing known to be absent'."""
    absent = set()
    detect = ns.get('detect_asset_packs')
    if detect is None or not target_chr_dir:
        return absent
    try:
        for info in (detect(target_chr_dir) or {}).values():
            absent.update(info.get('missing') or [])
    except Exception:
        pass
    return absent


def resolve_available_roster(ns, reg, roster, target_chr_dir):
    """Resolve which roster c-prefixes are placeable given on-disk presence
    and (if a regulation is supplied) param-row backing.

    Returns a dict:
      vanilla               sorted c-prefixes that always ship (always avail)
      imported_present      sorted imported c-prefixes whose assets are on disk
      imported_absent       sorted imported c-prefixes missing from disk
      available             vanilla + imported_present (assets resolved)
      param_checked         bool — whether the regulation param layer ran
      placeable             sorted subset of `available` with a usable target
                            variant (== available when param_checked is False)
      missing_npc_param     sorted c-prefixes with >=1 variant whose explicit
                            npc_param_id has no NpcParam row
      missing_think_param   same for NpcThinkParam
      no_target_after_params sorted c-prefixes where EVERY variant is
                            unplaceable on params (the hard exclusions)
      counts                sizes of the above sets
    """
    all_variants = roster.get('all_variants', []) if roster else []
    roster_prefixes = {v.get('c_prefix') for v in all_variants if v.get('c_prefix')}

    imported = _imported_prefixes(ns) & roster_prefixes
    absent = _absent_prefixes(ns, target_chr_dir)
    imported_absent = sorted(imported & absent)
    imported_present = sorted(imported - absent)
    vanilla = sorted(roster_prefixes - imported)
    available = sorted((set(vanilla) | set(imported_present)))

    missing_npc = set()
    missing_think = set()
    no_target = []
    param_checked = reg is not None
    placeable = list(available)

    if param_checked:
        try:
            npc_rows = set(reg.param_rows('NpcParam'))
            think_rows = set(reg.param_rows('NpcThinkParam'))
        except Exception:
            # If the regulation can't be queried, fail open like reg=None.
            npc_rows = think_rows = None

        if npc_rows is not None:
            avail = set(available)
            by_prefix = {}
            for v in all_variants:
                cp = v.get('c_prefix')
                if cp in avail:
                    by_prefix.setdefault(cp, []).append(v)

            placeable = []
            for cp in available:
                variants = by_prefix.get(cp, [])
                any_ok = False
                for v in variants:
                    npc = v.get('npc_param_id') or 0
                    think = v.get('think_param_id') or 0
                    npc_ok = (npc == 0) or (npc in npc_rows)
                    think_ok = (think == 0) or (think in think_rows)
                    if npc != 0 and npc not in npc_rows:
                        missing_npc.add(cp)
                    if think != 0 and think not in think_rows:
                        missing_think.add(cp)
                    if npc_ok and think_ok:
                        any_ok = True
                if any_ok:
                    placeable.append(cp)
                else:
                    no_target.append(cp)
            placeable = sorted(placeable)
        else:
            param_checked = False

    no_target_after_params = sorted(no_target)
    result = {
        'vanilla': vanilla,
        'imported_present': imported_present,
        'imported_absent': imported_absent,
        'available': available,
        'param_checked': param_checked,
        'placeable': placeable,
        'missing_npc_param': sorted(missing_npc),
        'missing_think_param': sorted(missing_think),
        'no_target_after_params': no_target_after_params,
    }
    result['counts'] = {
        'vanilla': len(vanilla),
        'imported_present': len(imported_present),
        'imported_absent': len(imported_absent),
        'available': len(available),
        'placeable': len(placeable),
        'no_target_after_params': len(no_target_after_params),
    }
    return result
