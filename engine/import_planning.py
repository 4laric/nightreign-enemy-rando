"""Pack-import planning + execution (extracted from oops_v3.py).

WHAT THIS IS
------------
The GUI / CLI has an "import packs" workflow that copies enemy chr
files from a source FromSoftware game install into the Nightreign
target install. This module contains the planning + execution
functions for that workflow:

  compatibility_preflight(ns, target_chr_dir):
      Walks the configured asset packs and reports per-pack
      missing-chr stats — what would be missing if the user
      enables this pack against their current target install.
      Used to warn before a destructive import.

  plan_bulk_chr_import(ns, source_chr_dir, target_chr_dir, ...):
      Builds the per-file "in source, missing in target", "in
      source AND target (overwrite candidate)", "skip" partitions
      from a raw source/target chr directory pair. Used by the
      bulk-import GUI workflow.

  execute_bulk_chr_import(source_chr_dir, target_chr_dir, plan, ...):
      Acts on the plan, copying files with progress callbacks and
      overwrite handling. Pure — no module-level deps.

  plan_roster_import(ns, mmv_dir, er_dir, target_chr_dir, ...):
      The "roster" import variant — sources from Mod Manager
      (MMV) and Elden Ring (ER) packs. Cross-references the
      target install to find what's importable. Used by the
      heritage import workflow.

  execute_roster_import(plan, mmv_dir, er_dir, overwrite, progress_cb):
      Executes a roster plan. Pure — no module-level deps.

WHY EXTRACTED
-------------
~914 lines across 5 related functions. They form a cohesive
unit (the import workflow) and have minimal dependencies (1-3
each), so they're a clean cut. Two of the five are pure (zero
module-level deps); the other three only need `_data_path` and/or
`detect_asset_packs` from oops_v3.

NS PATTERN
----------
Functions with deps take `ns` as the first parameter. Pure
functions could go without `ns`, but for uniformity ALL 5 take
`ns` first (so the shim pattern is identical across the module).
The pure functions just ignore `ns`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from collections import defaultdict


def compatibility_preflight(ns, target_chr_dir):
    """v0.23.72-late: comprehensive compatibility check rolling up all the
    things that have to be true before a rando run will work without CTDs.

    Returns a dict:
        {
            'status': 'ok' | 'warn' | 'fail',  # worst severity across checks
            'summary': 'short headline string',
            'checks': [
                {
                    'id': 'check_id',
                    'name': 'human-readable name',
                    'severity': 'ok'|'info'|'warn'|'fail',
                    'message': 'what this means for the user',
                    'detail': 'longer explanation / suggested action',
                },
                ...
            ],
            'asset_packs': <output of detect_asset_packs>,
        }

    Severities cascade: 'fail' = will crash, fix before generating. 'warn' =
    will generate something but likely degraded. 'info' = informational.
    'ok' = no issue.

    Suitable for rendering as a banner at the top of the Generate tab, or
    as a textual report a user can copy/paste when asking for help (or when
    sharing their config with a friend they're packaging a build for).
    """
    # Bind module-level dependencies from ns.
    _data_path = ns['_data_path']
    detect_asset_packs = ns['detect_asset_packs']
    import os

    checks = []
    target = (target_chr_dir or '').strip()

    # === Check 1: target chr/ dir exists ===
    if not target:
        checks.append({
            'id': 'target_chr_dir_set',
            'name': 'Target chr/ folder configured',
            'severity': 'warn',
            'message': "No me3 profile chr/ folder set. Compatibility detection skipped.",
            'detail': ("Open the 'chr/ Inventory' tab and point 'Target chr/ folder' "
                       "at your me3 profile's chr/ subfolder so the rando can verify "
                       "your installed chr assets."),
        })
        return {
            'status': 'warn',
            'summary': "Compatibility check incomplete — target chr/ folder not set.",
            'checks': checks,
            'asset_packs': {},
        }
    if not os.path.isdir(target):
        checks.append({
            'id': 'target_chr_dir_exists',
            'name': 'Target chr/ folder exists',
            'severity': 'fail',
            'message': f"Target chr/ folder doesn't exist: {target}",
            'detail': "Check the path on the 'chr/ Inventory' tab — there's a typo or the directory was moved.",
        })
        return {
            'status': 'fail',
            'summary': "Target chr/ folder path is broken.",
            'checks': checks,
            'asset_packs': {},
        }
    checks.append({
        'id': 'target_chr_dir_exists',
        'name': 'Target chr/ folder exists',
        'severity': 'ok',
        'message': target,
        'detail': '',
    })

    # === Check 2: asset packs status ===
    packs = detect_asset_packs(target)

    # Roll up: any pack enabled + requires_external + missing chrs is a problem
    for pack_id, info in packs.items():
        if not info.get('enabled'):
            continue
        if not info.get('requires_external'):
            continue
        det = info.get('detected', 0)
        exp = info.get('expected', 0)
        if exp == 0:
            continue
        name = info.get('description', pack_id)
        if det == 0:
            checks.append({
                'id': f'pack_{pack_id}',
                'name': f"Pack: {name}",
                'severity': 'fail',
                'message': f"Enabled but ZERO of {exp} chr-prefixes present in target.",
                'detail': (f"This pack is enabled in the rando config but the chr files "
                           f"aren't installed in {target}. Either install the mod (URL: "
                           f"{info.get('url') or 'see CHANGELOG'}), copy its chr files via "
                           f"the 'chr/ Inventory' tab, or disable the pack in its _meta block."),
            })
        elif det < exp:
            n_missing = exp - det
            preview = ', '.join(info.get('missing', [])[:5])
            more = (f" (+{n_missing - 5} more)" if n_missing > 5 else '')
            checks.append({
                'id': f'pack_{pack_id}',
                'name': f"Pack: {name}",
                'severity': 'warn',
                'message': f"{det}/{exp} chr-prefixes present — {n_missing} missing.",
                'detail': (f"Missing: {preview}{more}. Use chr/ Inventory → Diagnose for the "
                           f"full list. Slots that would have rolled these chrs will fall back "
                           f"to vanilla."),
            })
        else:
            checks.append({
                'id': f'pack_{pack_id}',
                'name': f"Pack: {name}",
                'severity': 'ok',
                'message': f"All {exp} chr-prefixes present.",
                'detail': '',
            })

    # === Check 3: DLC ownership signal ===
    # If any enabled pack has origin_game=SoTE chrs, the user needs SoTE
    # in their NR install. We can't directly check NR install — but we
    # can check if the DLC-origin chrs are present (with valid chrbnds)
    # in the target. The detect_asset_packs above checks all chrs as a
    # batch; here we slice by origin_game to be specific about *what* is
    # missing when it's DLC-origin content.
    sote_packs_with_issues = []
    for pack_id, info in packs.items():
        if not info.get('enabled'):
            continue
        if not info.get('requires_external'):
            continue
        ob = info.get('origin_breakdown', {})
        n_sote = ob.get('SoTE', 0)
        if n_sote and info.get('missing'):
            # Need to look at which missing chrs are SoTE-origin — load
            # the pack JSON to cross-reference.
            try:
                # Find the matching pack file by description (clunky but works)
                here = os.path.dirname(os.path.abspath(__file__))
                fname_map = {
                    'heritage_pack_v1': 'heritage_pack.json',
                    'mmv_imports_v1': 'mmv_imports.json',
                }
                fname = fname_map.get(pack_id)
                if not fname:
                    continue
                with open(_data_path(fname), encoding='utf-8') as f:
                    pack_data = json.load(f)
                tags = pack_data.get('tags', {})
                sote_missing = [cp for cp in info['missing']
                                if (tags.get(cp, {}).get('origin_game') == 'SoTE')]
                if sote_missing:
                    sote_packs_with_issues.append((info.get('description', pack_id),
                                                    sote_missing))
            except Exception:
                pass
    if sote_packs_with_issues:
        for desc, sote_missing in sote_packs_with_issues:
            preview = ', '.join(sote_missing[:5])
            more = (f" (+{len(sote_missing) - 5} more)" if len(sote_missing) > 5 else '')
            checks.append({
                'id': 'dlc_sote_assets',
                'name': "SoTE DLC chr assets",
                'severity': 'warn',
                'message': f"{len(sote_missing)} SoTE-origin chrs missing in '{desc}'.",
                'detail': (f"These chrs need Shadow of the Erdtree DLC assets. Either install "
                           f"SoTE locally and re-extract chr files via UXM, or the rando will "
                           f"fall back to vanilla on those slots. Affected: {preview}{more}"),
            })

    # === Roll-up status ===
    severities = [c['severity'] for c in checks]
    if 'fail' in severities:
        status = 'fail'
        summary = "Rando will likely CTD — fix the items below before generating."
    elif 'warn' in severities:
        status = 'warn'
        summary = "Rando will run but with degraded coverage — see warnings below."
    else:
        status = 'ok'
        summary = "All compatibility checks passed."

    return {
        'status': status,
        'summary': summary,
        'checks': checks,
        'asset_packs': packs,
    }


def plan_bulk_chr_import(ns, source_chr_dir, target_chr_dir,
                          include_disabled_packs=False,
                          source_script_dir=None, target_script_dir=None):
    """v0.23.72-late: 'copy everything we can use' planner.

    Surveys every known asset pack (heritage_pack, mmv_imports, etc.), gathers
    the union of all c-prefixes declared by enabled packs (or all if
    include_disabled_packs=True), and returns a plan showing exactly which
    chr files would be copied from source → target.

    v0.23.72-late+: also plans script-dir AI luabnd imports. ER chrs ported
    into heritage_pack without their AI Lua scripts run on .behbnd alone,
    which lacks phase-state latching and produces the c5210-class "phase
    transition loop" bug. The script-side import maps each c-prefix to
    its battle.luabnd / logic.luabnd files (cXXXX → XXX000_battle, etc.)
    and stages them from source script/ to target script/.

    Args:
        source_chr_dir: ER chr/ folder (the unpacked one).
        target_chr_dir: me3 profile chr/ folder (where files are copied to).
        source_script_dir: ER script/ folder. If None, defaults to a sibling
            of source_chr_dir (../script).
        target_script_dir: me3 profile script/ folder. If None, defaults to
            a sibling of target_chr_dir.

    This is complementary to the spoiler-driven import flow: that one copies
    just what's needed for ONE specific rando run. This one populates the
    target with EVERYTHING the rando might ever ask for across all configs,
    so the user only does it once and never sees CTDs (or AI-degraded fights)
    on cell-load.

    Returns a dict:
        {
            'in_source_missing_in_target': [(cp, [chr_files], [script_files], total_bytes), ...],
            'already_present_in_target': [cp, ...],
            'wanted_but_not_in_source': [(cp, pack_name, origin_game), ...],
            'per_pack_breakdown': {pack_id: {'wanted': N, 'have': N, 'copyable': N}},
            'script_dirs': {'source': ..., 'target': ...},  # resolved paths
            'totals': {
                'wanted_unique_prefixes': N,
                'already_present': N,
                'copyable_now': N,
                'unavailable': N,  # in pack but not in source
                'estimated_bytes': N,
                'script_files_copyable': N,  # NEW: # script files to be staged
            },
        }
    """
    # Bind module-level dependencies from ns.
    _data_path = ns['_data_path']
    import os, json, re
    from collections import defaultdict

    source = (source_chr_dir or '').strip()
    target = (target_chr_dir or '').strip()

    # Resolve script dirs — default to sibling of chr/. Heuristic only;
    # user can override. None values become empty strings (skip-script behavior).
    def _sibling_script(chr_dir):
        if not chr_dir: return ''
        parent = os.path.dirname(os.path.abspath(chr_dir))
        candidate = os.path.join(parent, 'script')
        return candidate if os.path.isdir(candidate) else ''

    src_script = (source_script_dir.strip() if source_script_dir
                  else _sibling_script(source))
    tgt_script = (target_script_dir.strip() if target_script_dir
                  else _sibling_script(target))
    # Don't insist tgt_script exists — execute_bulk_chr_import will create it.
    # But it does need to be DERIVABLE, so fall back to chr_dir-parent + 'script'
    # if the heuristic gave us empty.
    if not tgt_script and target:
        tgt_script = os.path.join(os.path.dirname(os.path.abspath(target)),
                                   'script')

    chr_re = re.compile(r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')
    # Script files use a numeric-prefix naming convention. A chr cNNNX's
    # battle/logic scripts are named after its MODEL: usually the chr's
    # own number (cNNNX -> NNNX00_*.luabnd, e.g. c5210 -> 521000,
    # c3252 -> 325200), but for a variant that shares its base model's
    # scripts, the BASE number (cNNNX -> NNN000, e.g. c5192 and c5193
    # both run 519000_battle.luabnd). So the lookup must try the chr's
    # own 4 digits first, then fall back to the base model (variant
    # digit forced to 0). v0.27.0: earlier code used only cp[1:5] and
    # silently failed to import scripts for every base-model-sharing
    # variant chr.
    # Both _battle and _logic are AI scripts (battle = combat brain,
    # logic = navigation/idle). Match both, with or without .dcx wrapper.
    script_re = re.compile(r'^(\d{4})\d{2}_(battle|logic)\.luabnd(\.dcx)?$')

    def list_chr_prefixes(d):
        if not d or not os.path.isdir(d): return set()
        out = set()
        for fn in os.listdir(d):
            m = chr_re.match(fn)
            if m: out.add(m.group(1))
        return out

    def list_chr_files_for_prefix(d, cp):
        if not os.path.isdir(d): return []
        out = []
        for fn in os.listdir(d):
            m = chr_re.match(fn)
            if m and m.group(1) == cp:
                out.append(fn)
        return sorted(out)

    def cp_to_script_prefix(cp, *indexes):
        """Resolve cp to the 4-digit key its scripts are indexed under.
        Tries the chr's own number (cp[1:5]) first, then the base-model
        number (cp[1:4]+'0'). `indexes` are the script dicts to probe
        for the literal key; if none contain it, the base key is used.
        E.g. c3252 -> '3252' (own script), c5192 -> '5190' (shares the
        c5190 base-model script)."""
        if len(cp) < 5:
            return None
        lit = cp[1:5]
        if any(lit in idx for idx in indexes):
            return lit
        return cp[1:4] + '0'

    # Pre-index script source files by chr prefix for fast lookup
    src_scripts_by_chr = defaultdict(list)
    if src_script and os.path.isdir(src_script):
        for fn in os.listdir(src_script):
            m = script_re.match(fn)
            if m:
                src_scripts_by_chr[m.group(1)].append(fn)

    # And target script files by chr prefix (for "already have" detection)
    tgt_scripts_by_chr = defaultdict(set)
    if tgt_script and os.path.isdir(tgt_script):
        for fn in os.listdir(tgt_script):
            m = script_re.match(fn)
            if m:
                tgt_scripts_by_chr[m.group(1)].add(fn)

    def list_script_files_for_prefix(cp):
        """Return list of script files in source for this c-prefix that
        AREN'T already in target. Compares basename ignoring .dcx wrapper
        (source may be uncompressed .luabnd while target is .luabnd.dcx)."""
        chr_prefix = cp_to_script_prefix(cp, src_scripts_by_chr,
                                         tgt_scripts_by_chr)
        if not chr_prefix: return []
        src_files = src_scripts_by_chr.get(chr_prefix, [])
        if not src_files: return []
        # Normalize for comparison: strip .dcx
        tgt_basenames = set()
        for tfn in tgt_scripts_by_chr.get(chr_prefix, set()):
            tgt_basenames.add(tfn[:-4] if tfn.endswith('.dcx') else tfn)
        out = []
        for sfn in sorted(src_files):
            base = sfn[:-4] if sfn.endswith('.dcx') else sfn
            if base not in tgt_basenames:
                out.append(sfn)
        return out

    source_have = list_chr_prefixes(source)
    target_have = list_chr_prefixes(target)

    # Gather wanted prefixes from every enabled pack. Reuse the KNOWN_PACKS
    # list from detect_asset_packs by parsing the pack JSONs directly.
    PACK_FILES = [
        'heritage_pack.json',
        'mmv_imports.json',
    ]
    wanted = {}  # cp → (pack_id, pack_name, origin_game)
    per_pack = {}

    for fname in PACK_FILES:
        path = _data_path(fname)
        if not os.path.isfile(path): continue
        try:
            with open(path, encoding='utf-8') as fh:
                pack = json.load(fh)
        except Exception:
            continue
        meta = pack.get('_meta', {})
        enabled = meta.get('enabled', True)
        if not enabled and not include_disabled_packs:
            continue
        # Some packs ship with base NR and don't need chr imports —
        # detect via requires_external_chr_assets metadata.
        if not meta.get('requires_external_chr_assets', True):
            continue

        pack_id = fname.replace('.json','').replace('_imports','_imports_v1')\
                       .replace('heritage_pack','heritage_pack_v1')
        pack_name = meta.get('user_facing_name') or pack_id
        tags = pack.get('tags', {}) or {}
        per_pack[pack_id] = {
            'name': pack_name,
            'wanted': len(tags),
            'have': sum(1 for cp in tags if cp in target_have),
            'copyable': sum(1 for cp in tags
                            if cp in source_have and cp not in target_have),
        }
        for cp, tinfo in tags.items():
            if cp not in wanted:
                wanted[cp] = (pack_id, pack_name,
                              (tinfo.get('origin_game') or '?'))

    # Categorize. Now we ALSO check for script-only updates: a chr might be
    # already-present-in-target (chrbnd exists) but missing AI scripts.
    # Such chrs should appear in in_source_missing_in_target with an empty
    # chr_files list but populated script_files — the c5210 case exactly.
    in_source_missing = []
    already_present = []
    wanted_not_in_source = []
    total_bytes = 0
    script_files_copyable_count = 0

    for cp in sorted(wanted.keys()):
        chr_files = []
        chr_bytes = 0
        if cp not in target_have:
            if cp in source_have:
                chr_files = list_chr_files_for_prefix(source, cp)
                chr_bytes = sum(os.path.getsize(os.path.join(source, f))
                                for f in chr_files)

        # Script files: always check, even for chrs already in target
        script_files = list_script_files_for_prefix(cp)
        script_bytes = 0
        if script_files and src_script:
            script_bytes = sum(os.path.getsize(os.path.join(src_script, f))
                                for f in script_files)
        script_files_copyable_count += len(script_files)

        cp_total_bytes = chr_bytes + script_bytes

        if cp in target_have and not script_files:
            # Fully covered: chr in target, no script work to do
            already_present.append(cp)
        elif chr_files or script_files:
            # Either chr files or script files to copy (or both)
            in_source_missing.append((cp, chr_files, script_files, cp_total_bytes))
            total_bytes += cp_total_bytes
        else:
            # Wanted, not in target, source doesn't have it either
            pack_id, pack_name, origin = wanted[cp]
            wanted_not_in_source.append((cp, pack_name, origin))

    return {
        'in_source_missing_in_target': in_source_missing,
        'already_present_in_target': already_present,
        'wanted_but_not_in_source': wanted_not_in_source,
        'per_pack_breakdown': per_pack,
        'script_dirs': {
            'source': src_script,
            'target': tgt_script,
            'source_exists': bool(src_script and os.path.isdir(src_script)),
        },
        'totals': {
            'wanted_unique_prefixes': len(wanted),
            'already_present': len(already_present),
            'copyable_now': len(in_source_missing),
            'unavailable': len(wanted_not_in_source),
            'estimated_bytes': total_bytes,
            'script_files_copyable': script_files_copyable_count,
        },
    }


def execute_bulk_chr_import(ns, source_chr_dir, target_chr_dir, plan,
                             overwrite=False, progress_cb=None,
                             source_script_dir=None, target_script_dir=None):
    """v0.23.72-late: execute a plan returned by plan_bulk_chr_import.

    `progress_cb`, if given, is called as progress_cb(cp, fname, copied_bytes,
    total_bytes, status_str) for each file. Use to drive a GUI progress bar
    or to stream a log.

    v0.23.72-late+: also copies script-dir files when plan entries include
    them. Reads script_dirs from plan if source_script_dir/target_script_dir
    not explicitly provided.

    Returns a dict:
        {'files_copied': N, 'files_skipped': N, 'bytes_copied': N,
         'chr_files_copied': N, 'script_files_copied': N, 'errors': [...]}
    """
    # (no module-level dependencies)
    import os, shutil
    source = (source_chr_dir or '').strip()
    target = (target_chr_dir or '').strip()

    # Resolve script dirs: prefer explicit args, fall back to plan, fall back
    # to nothing (no script copy).
    script_dirs = plan.get('script_dirs', {}) if plan else {}
    src_script = (source_script_dir.strip() if source_script_dir
                  else script_dirs.get('source', ''))
    tgt_script = (target_script_dir.strip() if target_script_dir
                  else script_dirs.get('target', ''))

    if not os.path.isdir(source):
        raise ValueError(f"Source dir doesn't exist: {source}")
    os.makedirs(target, exist_ok=True)
    if tgt_script:
        os.makedirs(tgt_script, exist_ok=True)

    files_copied = 0
    files_skipped = 0
    bytes_copied = 0
    chr_files_copied = 0
    script_files_copied = 0
    errors = []

    # Total bytes for progress calc — sum across plan entries
    total = sum(entry[-1] for entry in plan.get('in_source_missing_in_target', []))
    seen = 0

    def _copy_one(src_dir, dst_dir, fname, cp, kind):
        """Inner: copy one file. Returns (status, size). kind = 'chr' or 'script'."""
        nonlocal files_copied, files_skipped, bytes_copied
        nonlocal chr_files_copied, script_files_copied, seen
        src = os.path.join(src_dir, fname)
        dst = os.path.join(dst_dir, fname)
        try:
            sz = os.path.getsize(src)
        except OSError as e:
            errors.append(f"{kind} {fname}: stat failed: {e}")
            return 'error', 0
        seen += sz
        if os.path.exists(dst) and not overwrite:
            files_skipped += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'skip-exists ({kind})')
            return 'skip', sz
        try:
            shutil.copy2(src, dst)
            files_copied += 1
            bytes_copied += sz
            if kind == 'chr':
                chr_files_copied += 1
            else:
                script_files_copied += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'copied ({kind})')
            return 'copied', sz
        except Exception as e:
            errors.append(f"{kind} {fname}: {type(e).__name__}: {e}")
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'error: {e}')
            return 'error', sz

    for entry in plan.get('in_source_missing_in_target', []):
        # Entry shape: (cp, chr_files, script_files, total_bytes)
        cp = entry[0]
        chr_files = entry[1]
        script_files = entry[2] if len(entry) >= 4 else []
        # chr files from source chr dir
        for fname in chr_files:
            _copy_one(source, target, fname, cp, 'chr')
        # script files from source script dir (if it's available)
        if script_files and src_script and os.path.isdir(src_script) and tgt_script:
            for fname in script_files:
                _copy_one(src_script, tgt_script, fname, cp, 'script')
        elif script_files:
            errors.append(
                f"{cp}: {len(script_files)} script files NOT copied — "
                f"script source dir not available "
                f"(expected sibling of chr/, set explicitly to override)")

    return {
        'files_copied': files_copied,
        'files_skipped': files_skipped,
        'bytes_copied': bytes_copied,
        'chr_files_copied': chr_files_copied,
        'script_files_copied': script_files_copied,
        'errors': errors,
    }


def plan_roster_import(ns, mmv_dir, er_dir, target_chr_dir,
                       target_script_dir=None):
    """v0.27.0: one-time roster-driven chr import planner.

    Builds the set of c-prefixes the rando may need on disk and works out,
    for each, where its asset files come from. This is the planner behind
    the GUI's "Import roster" flow (Diagnose + Import).

    The import set = the union of:
      * heritage pack chrs -- every c_prefix keyed in heritage_pack.json's
        `tags` (ER/cross-game enemies the rando references but vanilla NR
        does not ship assets for); and
      * MMV pack chrs -- every c_prefix keyed in mmv_imports.json's `tags`
        (cross-game boss ports; disjoint from the heritage prefixes).
    Vanilla nr_placed chrs are NOT in the set -- their files already ship
    with NR, so copying them is a no-op.

    v0.27.0: the heritage half reads heritage_pack.json, the single
    source of truth (regenerated by dev/build_heritage_pack.py), NOT the
    roster's per-variant `_heritage_imported` flags. detect_asset_packs
    reads the same file, so Diagnose and the compatibility report agree.

    Source routing, per c-prefix: look in `mmv_dir` first, fall back to
    `er_dir`. MMV-first is deliberate -- a chr that is an MMV port must
    get MMV's build of the asset (MMV re-authors some shared prefixes);
    ER is only the source for genuine ER-heritage chrs MMV doesn't ship.
    A chr found in neither dir is reported as unavailable (the user is
    missing a DLC or hasn't UXM-unpacked that game).

    `mmv_dir` and `er_dir` are GAME-ROOT folders (containing chr/, script/,
    sfx/, material/ as subdirs), not the chr/ subdir itself -- matching the
    GUI's existing "folder" convention.

    SFX / material are NOT planned here -- they are shared bundles that
    cannot be matched per-chr (sfxbnd_commoneffects etc.). The executor
    bulk-syncs those dirs separately. See execute_roster_import.

    Returns a dict:
        {
          'entries': [
             {'cp', 'origin' ('mmv'|'er'),
              'src_chr_dir', 'src_script_dir',
              'chr_files': [...], 'script_files': [...],
              'bytes': N}, ...],          # only chrs with something to copy
          'already_present': [cp, ...],   # chr + scripts already in target
          'unavailable': [(cp, wanted_by), ...],   # in neither source dir
          'target_dirs': {'chr', 'script'},
          'totals': {'wanted', 'already_present', 'copyable',
                     'unavailable', 'bytes', 'script_files',
                     'from_mmv', 'from_er'},
        }
    """
    # Bind module-level dependencies from ns.
    _data_path = ns['_data_path']
    import os, re, json
    from collections import defaultdict

    chr_re = re.compile(
        r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')
    script_re = re.compile(r'^(\d{4})\d{2}_(battle|logic)\.luabnd(\.dcx)?$')

    def _sub(root, name):
        """Resolve <root>/<name>, also accepting <root>/Game/<name>."""
        if not root:
            return ''
        root = root.strip()
        for cand in (os.path.join(root, name),
                     os.path.join(root, 'Game', name)):
            if os.path.isdir(cand):
                return cand
        return ''

    mmv_chr = _sub(mmv_dir, 'chr')
    er_chr = _sub(er_dir, 'chr')
    mmv_script = _sub(mmv_dir, 'script')
    er_script = _sub(er_dir, 'script')

    tgt_chr = (target_chr_dir or '').strip()
    if target_script_dir:
        tgt_script = target_script_dir.strip()
    elif tgt_chr:
        tgt_script = os.path.join(
            os.path.dirname(os.path.abspath(tgt_chr)), 'script')
    else:
        tgt_script = ''

    def _index_chr(d):
        """{c_prefix: [filenames]} for one chr dir."""
        idx = defaultdict(list)
        if d and os.path.isdir(d):
            for fn in os.listdir(d):
                m = chr_re.match(fn)
                if m:
                    idx[m.group(1)].append(fn)
        return idx

    def _index_scripts(d):
        """{4-digit prefix: [filenames]} for one script dir."""
        idx = defaultdict(list)
        if d and os.path.isdir(d):
            for fn in os.listdir(d):
                m = script_re.match(fn)
                if m:
                    idx[m.group(1)].append(fn)
        return idx

    mmv_chr_idx = _index_chr(mmv_chr)
    er_chr_idx = _index_chr(er_chr)
    mmv_script_idx = _index_scripts(mmv_script)
    er_script_idx = _index_scripts(er_script)
    tgt_chr_idx = _index_chr(tgt_chr)
    tgt_script_idx = _index_scripts(tgt_script)

    # --- assemble the wanted set: heritage_pack tags + MMV pack tags ---
    # v0.27.0: the heritage half reads heritage_pack.json, NOT the
    # roster's per-variant `_heritage_imported` flags. Those two used
    # to be independent sources for the same question ("which heritage
    # chrs does the rando need on disk?") and drifted apart — the
    # Diagnose flow (this function) and the compatibility report
    # (detect_asset_packs, which reads heritage_pack.json) disagreed by
    # 10+ c-prefixes. heritage_pack.json is now the single source of
    # truth, regenerated from the four-set diff by
    # dev/build_heritage_pack.py. detect_asset_packs already reads it;
    # routing this function through the same file means the two reports
    # cannot disagree. The roster's `_heritage_imported` flag is left
    # in place but is no longer consulted by the import path.
    wanted = {}  # cp -> human label of what wants it
    try:
        heritage = json.load(open(_data_path('heritage_pack.json'),
                                   encoding='utf-8'))
        for cp in (heritage.get('tags') or {}):
            wanted.setdefault(cp, 'heritage pack chr')
    except Exception:
        pass
    try:
        mmv = json.load(open(_data_path('mmv_imports.json'),
                              encoding='utf-8'))
        for cp in (mmv.get('tags') or {}):
            wanted.setdefault(cp, 'MMV pack')
    except Exception:
        pass

    def _scripts_to_copy(cp, src_script_idx):
        """Source script files for cp not already in target (basename
        compare, ignoring the .dcx wrapper).

        v0.27.0 bugfix: a chr cNNNX's battle/logic scripts are named
        after the chr's MODEL, which is sometimes the chr's own number
        (cNNNX -> NNNX00, e.g. c3252 -> 325200) and sometimes the
        base-model number when the variant shares the base model's
        scripts (cNNNX -> NNN000, e.g. c5192/c5193 Spider Scorpion both
        run 519000_battle.luabnd, indexed under '5190'). The old key
        cp[1:5] only handled the first case, so every variant chr that
        shared a base-model script (last digit != 0) silently got no AI
        script imported -- it ran behbnd-only. The fix tries the literal
        key first, then falls back to the base-model key. This raised
        heritage-pack script coverage from 43/71 to 67/71."""
        if len(cp) < 5:
            return []
        # try the chr's own number, then fall back to its base model
        src = src_script_idx.get(cp[1:5])
        sp = cp[1:5]
        if not src:
            sp = cp[1:4] + '0'
            src = src_script_idx.get(sp, [])
        if not src:
            return []
        tgt_bases = set()
        for tfn in tgt_script_idx.get(sp, []):
            tgt_bases.add(tfn[:-4] if tfn.endswith('.dcx') else tfn)
        return sorted(fn for fn in src
                      if (fn[:-4] if fn.endswith('.dcx') else fn)
                      not in tgt_bases)

    entries = []
    already_present = []
    unavailable = []
    tot_bytes = 0
    tot_scripts = 0
    from_mmv = from_er = 0

    for cp in sorted(wanted):
        # MMV-first source routing.
        if cp in mmv_chr_idx:
            origin, src_chr, src_script_dir, src_script_idx = (
                'mmv', mmv_chr, mmv_script, mmv_script_idx)
        elif cp in er_chr_idx:
            origin, src_chr, src_script_dir, src_script_idx = (
                'er', er_chr, er_script, er_script_idx)
        else:
            unavailable.append((cp, wanted[cp]))
            continue

        src_idx = mmv_chr_idx if origin == 'mmv' else er_chr_idx
        chr_files = ([] if cp in tgt_chr_idx
                     else sorted(src_idx.get(cp, [])))
        script_files = _scripts_to_copy(cp, src_script_idx)

        if not chr_files and not script_files:
            already_present.append(cp)
            continue

        b = 0
        for fn in chr_files:
            try:
                b += os.path.getsize(os.path.join(src_chr, fn))
            except OSError:
                pass
        for fn in script_files:
            try:
                b += os.path.getsize(os.path.join(src_script_dir, fn))
            except OSError:
                pass
        entries.append({
            'cp': cp, 'origin': origin,
            'src_chr_dir': src_chr, 'src_script_dir': src_script_dir,
            'chr_files': chr_files, 'script_files': script_files,
            'bytes': b,
        })
        tot_bytes += b
        tot_scripts += len(script_files)
        if origin == 'mmv':
            from_mmv += 1
        else:
            from_er += 1

    return {
        'entries': entries,
        'already_present': already_present,
        'unavailable': unavailable,
        'target_dirs': {'chr': tgt_chr, 'script': tgt_script},
        'totals': {
            'wanted': len(wanted),
            'already_present': len(already_present),
            'copyable': len(entries),
            'unavailable': len(unavailable),
            'bytes': tot_bytes,
            'script_files': tot_scripts,
            'from_mmv': from_mmv,
            'from_er': from_er,
        },
    }


def execute_roster_import(ns, plan, mmv_dir, er_dir,
                          overwrite=False, progress_cb=None):
    """v0.27.0: execute a plan from plan_roster_import.

    Copies chr + script files (each entry carries its own resolved source
    dir, so MMV-origin and ER-origin chrs are handled in one pass), then
    bulk-syncs the sfx/ and material/ directories.

    SFX / material sync follows the same MMV-first, ER-fallback rule as
    the chr routing: if the MMV dir has an sfx/ (or material/) subdir it
    is used; otherwise the ER dir's is. These are bulk dir-to-dir copies
    -- the bundles are shared and not per-chr matchable. Idempotent
    skip-existing keeps re-runs cheap.

    `progress_cb`, if given, is called progress_cb(cp, fname, seen, total,
    status) per file, mirroring execute_bulk_chr_import.

    Returns a dict:
        {'chr_files_copied', 'script_files_copied', 'files_skipped',
         'bytes_copied', 'sfx_files_copied', 'material_files_copied',
         'errors': [...]}
    """
    # (no module-level dependencies)
    import os, shutil

    tgt = plan.get('target_dirs', {})
    tgt_chr = (tgt.get('chr') or '').strip()
    tgt_script = (tgt.get('script') or '').strip()
    if not tgt_chr:
        raise ValueError("plan has no target chr dir")
    os.makedirs(tgt_chr, exist_ok=True)
    if tgt_script:
        os.makedirs(tgt_script, exist_ok=True)

    res = {'chr_files_copied': 0, 'script_files_copied': 0,
           'files_skipped': 0, 'bytes_copied': 0,
           'sfx_files_copied': 0, 'material_files_copied': 0,
           'errors': []}

    total = sum(e['bytes'] for e in plan.get('entries', []))
    seen = 0

    def _copy(src_dir, dst_dir, fname, cp, kind):
        nonlocal seen
        src = os.path.join(src_dir, fname)
        dst = os.path.join(dst_dir, fname)
        try:
            sz = os.path.getsize(src)
        except OSError as e:
            res['errors'].append(f"{kind} {fname}: stat failed: {e}")
            return
        seen += sz
        if os.path.exists(dst) and not overwrite:
            res['files_skipped'] += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'skip-exists ({kind})')
            return
        try:
            shutil.copy2(src, dst)
            res['bytes_copied'] += sz
            if kind == 'chr':
                res['chr_files_copied'] += 1
            else:
                res['script_files_copied'] += 1
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'copied ({kind})')
        except Exception as e:
            res['errors'].append(f"{kind} {fname}: {type(e).__name__}: {e}")
            if progress_cb:
                progress_cb(cp, fname, seen, total, f'error: {e}')

    for e in plan.get('entries', []):
        cp = e['cp']
        for fn in e['chr_files']:
            _copy(e['src_chr_dir'], tgt_chr, fn, cp, 'chr')
        if e['script_files'] and e['src_script_dir'] and tgt_script:
            for fn in e['script_files']:
                _copy(e['src_script_dir'], tgt_script, fn, cp, 'script')
        elif e['script_files']:
            res['errors'].append(
                f"{cp}: {len(e['script_files'])} script files NOT copied "
                f"-- no script source/target dir resolved")

    # --- SFX + material bulk sync (MMV-first, ER-fallback) ---
    def _pick_subdir(name):
        for root in (mmv_dir, er_dir):
            if not root:
                continue
            for cand in (os.path.join(root.strip(), name),
                         os.path.join(root.strip(), 'Game', name)):
                if os.path.isdir(cand):
                    return cand
        return ''

    tgt_parent = os.path.dirname(os.path.abspath(tgt_chr))
    for name, key in (('sfx', 'sfx_files_copied'),
                      ('material', 'material_files_copied')):
        src_dir = _pick_subdir(name)
        if not src_dir:
            continue
        dst_dir = os.path.join(tgt_parent, name)
        os.makedirs(dst_dir, exist_ok=True)
        for fn in sorted(os.listdir(src_dir)):
            sp = os.path.join(src_dir, fn)
            if not os.path.isfile(sp):
                continue
            dp = os.path.join(dst_dir, fn)
            if os.path.exists(dp) and not overwrite:
                res['files_skipped'] += 1
                continue
            try:
                sz = os.path.getsize(sp)
                shutil.copy2(sp, dp)
                res[key] += 1
                res['bytes_copied'] += sz
            except Exception as ex:
                res['errors'].append(
                    f"{name}/{fn}: {type(ex).__name__}: {ex}")
    return res
