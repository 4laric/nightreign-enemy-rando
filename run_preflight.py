#!/usr/bin/env python3
"""run_preflight.py — pure pre-run validation + config mapping for the rando.

v0.33: extracted from oops_rando_gui._run_shuffle / _worker so the decision
logic is unit-testable (tests/test_run_preflight.py) and reusable by headless
/ CLI callers. STRICT SEPARATION: nothing in this module touches tkinter,
shows a dialog, or reads a Tk var — callers translate the returned status
codes into their own UI (messageboxes in the GUI, stderr in a CLI).

What lives here:
  check_input_dir      — input mapstudio folder validation
  ensure_output_dir    — output folder creation with differentiated failures
  resolve_oops_targets — Oops!-All mode target resolution from the dropdowns
  build_engine_kwargs  — the config-dict -> engine-kwargs mapping shared by
                         the DCX (rando_pipeline) and raw-MSB (cmd_shuffle_v3)
                         paths

The GUI's _run_shuffle remains the interactive orchestrator (profile
coherence, bundle preflight prompts, settings persistence); only its pure
decisions are delegated here.
"""
from __future__ import annotations

import os


def check_input_dir(in_dir: str) -> str:
    """Validate the vanilla-mapstudio input folder.

    Returns one of:
      'ok'       — directory exists and contains .msb / .msb.dcx files
      'missing'  — not a directory (or blank)
      'no_msbs'  — directory exists but has no map files (wrong folder, or
                   a packed install that hasn't been read/unpacked)
    """
    if not in_dir or not os.path.isdir(in_dir):
        return 'missing'
    try:
        has_msb = any(f.endswith('.msb') or f.endswith('.msb.dcx')
                      for f in os.listdir(in_dir))
    except OSError:
        has_msb = False
    return 'ok' if has_msb else 'no_msbs'


def ensure_output_dir(out_dir: str) -> tuple:
    """Create the output dir, differentiating the failure modes the GUI
    explains to the user. Returns (status, detail):

      ('ok', None)             — created / already exists
      ('unset', None)          — blank path
      ('permission', None)     — PermissionError (system folder, AV, RO flag)
      ('parent_missing', None) — FileNotFoundError (typo'd drive letter,
                                 unmounted removable drive, broken symlink)
      ('oserror', str(e))      — any other OSError, stringified for display
    """
    if not (out_dir or '').strip():
        return ('unset', None)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except PermissionError:
        return ('permission', None)
    except FileNotFoundError:
        return ('parent_missing', None)
    except OSError as e:
        return ('oserror', str(e))
    return ('ok', None)


def resolve_oops_targets(run_mode: str, *, nb_pick: str = '',
                         all_pick: str = '', lookup: dict = None,
                         nb_scope: str = '') -> tuple:
    """Resolve the Oops!-All target c-prefixes for the selected run mode.

    `lookup` maps dropdown display strings -> c_prefix; a pick not in the
    lookup falls back to its first whitespace token (so a raw typed
    'c4373' works). Returns (targets, error):

      targets — {'oops_all_target_cp', 'oops_all_nb_target_cp',
                 'oops_all_nb_marker_scope'} (None where not applicable)
      error   — None | 'nb_target_missing' | 'target_missing'
    """
    lookup = lookup or {}
    targets = {'oops_all_target_cp': None,
               'oops_all_nb_target_cp': None,
               'oops_all_nb_marker_scope': None}
    if run_mode.startswith("Oops! All NB"):
        picked = (nb_pick or '').strip()
        if not picked:
            return targets, 'nb_target_missing'
        targets['oops_all_nb_target_cp'] = lookup.get(picked,
                                                      picked.split()[0])
        targets['oops_all_nb_marker_scope'] = nb_scope or 'broad'
    elif run_mode.startswith("Oops"):
        picked = (all_pick or '').strip()
        if not picked:
            return targets, 'target_missing'
        targets['oops_all_target_cp'] = lookup.get(picked, picked.split()[0])
    return targets, None


def build_engine_kwargs(config: dict) -> dict:
    """Map the GUI's snapshotted run config onto the engine kwargs shared by
    both shuffle paths — dcx_batch.rando_pipeline (DCX) and
    oops_v3.cmd_shuffle_v3 (raw MSB, seed popped positionally).

    Required keys (KeyError = a GUI config-assembly bug, fail loud):
    seed, oops_all_target_cp, merchant_model_swap, excluded, hub_maps.
    Everything else defaults to None/False so headless callers can pass a
    minimal config.
    """
    return dict(
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
        sote_mode=bool(config.get('sote_mode')),
        # v0.27.x: Pools & Caps overrides — threaded into both the
        # rando_pipeline (DCX) and cmd_shuffle_v3 (raw MSB) paths.
        # None when the tab is untouched.
        unique_cap_overrides=config.get('unique_cap_overrides'),
        caliber_pool_extras=config.get('caliber_pool_extras'),
        caliber_pool_removals=config.get('caliber_pool_removals'),
        # v0.28.x: Boutique Pool — per-run promotion-rate overrides.
        # Defaults to None when the Boutique Pool panel didn't load,
        # so non-GUI callers and broken-tab scenarios both no-op.
        field_upgrade_miniboss_pct=config.get('field_upgrade_miniboss_pct'),
        field_upgrade_fieldboss_pct=config.get('field_upgrade_fieldboss_pct'),
        field_upgrade_nightboss_pct=config.get('field_upgrade_nightboss_pct'),
        fieldboss_to_nightboss_promote_pct=config.get(
            'fieldboss_to_nightboss_promote_pct'),
    )
