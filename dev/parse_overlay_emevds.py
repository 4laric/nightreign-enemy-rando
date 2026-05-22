#!/usr/bin/env python3
"""parse_overlay_emevds.py — extract the chr-spawn vs HP-bar-ref eid
mapping for every overlay MSB.

Background (v0.25.0-patch3 / "Tricephalos N2 fail" investigation):
NR's boss-arena EMEVDs use common_func helper events (90015000,
90065910, 90065050, etc.) to coordinate boss-init / wake-handshake.
These helpers take the boss's chrEntityId as one argument and one or
more "secondary" chr entity IDs (chrEntityId2, chrEntityId3, ...) as
HP-bar / companion / damage-pair references.

For SOME arenas (e.g. m48_60 Tree Sentinel + Cavalrymen), the actual
spawned chr lives at a DIFFERENT entity_id from the one tracked in
nr_boss_slots.json. The catalog walks MSB Parts and tags boss-tier
slots by entity_id and "Night Boss" name marker — which finds the
HP-bar-anchor entity (eid pattern xxx800) but misses the actual-spawn
entity (e.g. eid 48605800 for m48_60).

Result: the rando swaps the HP-bar-ref entity's chr, leaves the actual
spawn chr vanilla, and the EMEVD's EnableCharacter call on the actual-
spawn entity executes — but with the original NpcParam, so the player
sees vanilla Tree Sentinel (or, sometimes, nothing at all if the
swap broke an upstream gate).

This tool reads the decompiled vanilla EMEVDs (DarkScript3 .js output)
and emits a JSON file mapping each MSB to its boss-init signature: which
helper events it uses, what arguments they're called with, and which
entity IDs play which role. Downstream consumers in oops_v3 use this to:

  (B) Swap the actual-spawn chr eid instead of (or in addition to) the
      HP-bar-ref eid, so the visible boss in-game is the randomized chr.

  (C) Rebuild the boss-slot catalog with both eid roles annotated, so
      the rando can apply the correct protection (boss-init wake-
      handshake, V3_PRESERVE_SLOTS) to each.

  (D) Identify multi-entity overlays for whole-MSB preservation fallback
      when finer-grained handling proves unreliable.

Usage:
  python3 dev/parse_overlay_emevds.py
    Reads dev/emevd_dump/*.emevd.js, writes data/nr_overlay_eid_map.json.

  python3 dev/parse_overlay_emevds.py --msb m48_60_00_00
    Detail view for a single MSB (debug mode).

  python3 dev/parse_overlay_emevds.py --check
    Re-parse and compare against existing data/nr_overlay_eid_map.json,
    exit nonzero on diff. CI-style smoke test.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict


# Path setup — script is in dev/, project root is parent of that.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
EMEVD_DIR = os.path.join(SCRIPT_DIR, 'emevd_dump')
OUTPUT_PATH = os.path.join(PROJECT_ROOT, 'data', 'nr_overlay_eid_map.json')


# Helper-event signatures, extracted from common_func.emevd.js. The arg name
# matters: `chrEntityId` (first one) is the actual spawn chr that gets
# EnableCharacter'd. Subsequent `chrEntityIdN` args are HP-bar references,
# damage-pair anchors, or companion-chr entities for multi-body bosses.
#
# Mapping built from running `extract_sig` against common_func.emevd.js
# during this tool's development. Maintained here as a frozen reference —
# if NR ships a regulation/EMEVD update that changes these signatures, the
# mapping needs regenerating.
HELPER_SIGNATURES = {
    '90015000': ['eventFlagId', 'chrEntityId', 'nameId', 'targetDistance', 'bgmBossConvParamId', 'eventFlagId2'],
    '90015002': ['eventFlagId', 'eventFlagId2', 'eventFlagId3', 'chrEntityId', 'textEffectParamId', 'bgmBossConvParamId', 'userDispLogParamId', 'logObjectId', 'entityId'],
    '90015005': ['assetEntityId', 'eventFlagId', 'eventFlagId2'],
    '90015008': ['eventFlagId', 'eventFlagId2', 'bgmBossConvParamId', 'chrEntityId', 'spEffectId', 'targetAmount'],
    '90015011': ['chrEntityId', 'eventFlagId', 'eventFlagId2'],
    '90015012': ['chrEntityId', 'eventFlagId'],
    '90015020': ['eventFlagId', 'eventFlagId2'],
    '90015023': ['eventFlagId', 'targetDistance', 'eventFlagId2', 'chrEntityId', 'chrEntityId2', 'nameId', 'chrEntityId3', 'nameId2', 'chrEntityId4', 'nameId3'],
    '90015030': ['eventFlagId', 'chrEntityId', 'targetDistance', 'bgmBossConvParamId', 'eventFlagId2'],
    '90015442': ['entityId', 'eventFlagId'],
    '90015443': ['entityId', 'eventFlagId'],
    '90015446': ['chrEntityId', 'eventFlagId', 'eventFlagId2', 'entityId'],
    '90015460': ['entityId', 'chrEntityId'],
    '90015470': ['entityId', 'eventFlagId', 'eventFlagId2', 'chrEntityId', 'chrEntityId2', 'chrEntityId3', 'chrEntityId4'],
    '90015475': ['entityId', 'chrEntityId'],
    '90015476': ['chrEntityId', 'entityId'],
    '90015478': ['chrEntityId', 'eventFlagId'],
    '90035000': ['eventFlagId'],
    '90035001': ['chrEntityId'],
    '90055000': ['chrEntityId', 'value', 'areaEntityId', 'eventFlagId'],
    '90055001': ['chrEntityId', 'value', 'eventFlagId', 'eventFlagId2'],
    '90065040': ['chrEntityId', 'chrEntityId2', 'eventFlagId', 'eventFlagId2'],
    '90065041': ['chrEntityId', 'chrEntityId2', 'eventFlagId', 'eventFlagId2'],
    '90065050': ['eventFlagId', 'eventFlagId2', 'eventFlagId3', 'bgmBossConvParamId', 'chrEntityId', 'chrEntityId2', 'nameId', 'chrEntityId3', 'nameId2', 'chrEntityId4', 'nameId3', 'chrEntityId5', 'chrEntityId6'],
    '90065051': ['chrEntityId', 'chrEntityId2', 'chrEntityId3', 'eventFlagId'],
    '90065052': ['chrEntityId', 'chrEntityId2', 'chrEntityId3', 'spEffectId', 'dummypolyId', 'eventFlagId', 'eventFlagId2'],
    '90065053': ['chrEntityId', 'chrEntityId2', 'eventFlagId', 'eventFlagId2'],
    '90065054': ['chrEntityId', 'chrEntityId2', 'eventFlagId', 'eventFlagId2'],
    '90065055': ['chrEntityId', 'chrEntityId2', 'spEffectId', 'eventFlagId', 'eventFlagId2'],
    '90065056': ['chrEntityId', 'chrEntityId2', 'chrEntityId3', 'spEffectId', 'dummypolyId', 'areaEntityId', 'entityId', 'eventFlagId', 'eventFlagId2'],
    '90065057': ['chrEntityId', 'eventFlagId'],
    '90065140': ['chrEntityId'],
    '90065900': ['entityId', 'value', 'assetEntityId', 'chrEntityId', 'textEffectParamId', 'bgmBossConvParamId', 'logObjectId', 'entityId2'],
    '90065910': ['eventFlagId', 'eventFlagId2', 'eventFlagId3', 'bgmBossConvParamId', 'sfxId', 'chrEntityId', 'chrEntityId2', 'nameId', 'chrEntityId3', 'nameId2', 'chrEntityId4', 'nameId3'],
    '90065911': ['eventFlagId', 'eventFlagId2', 'bgmBossConvParamId', 'chrEntityId', 'chrEntityId2', 'nameId', 'chrEntityId3', 'nameId2', 'chrEntityId4', 'nameId3', 'chrEntityId5'],
    '90065920': ['chrEntityId', 'spEffectId'],
}


# Subset of helpers that are diagnostic of "this is a Night Boss arena init":
# their presence in an MSB's EMEVD strongly suggests the MSB is an NB overlay.
NB_BOSS_INIT_HELPERS = {
    '90015000',  # standard NR boss-init (single-entity)
    '90015023',  # NB Map Variation 2 spawn (multi-HP-bar)
    '90065050',  # multi-entity boss-init (3-body + 2 companions)
    '90065910',  # multi-HP-bar boss-init
    '90065911',  # boss-defeat cleanup (always paired with 90065910/90065050)
}

# Helpers whose chrEntityId arg is *definitely* the actual spawn target
# (the chr that gets EnableCharacter'd, ForceAnimationPlayback'd, etc.).
# Excludes helpers like 90065900 (boss-completion tracker — chrEntityId is
# the rewards/asset reference, not the spawn) and 90065920 (SpEffect-only).
ACTUAL_SPAWN_HELPERS = {
    '90015000', '90015002', '90015011', '90015012',
    '90015023',  # arg name is chrEntityId — the actual spawn for MapVar 2
    '90015030', '90015446', '90015460', '90015470', '90015475',
    '90015476', '90015478',
    '90035001',
    '90065040', '90065041',
    '90065050',  # arg5 chrEntityId — the actual spawn for multi-entity arena
    '90065051', '90065052', '90065053', '90065054', '90065055',
    '90065056', '90065057', '90065140',
    '90065910',  # arg6 chrEntityId — the actual spawn for multi-HP-bar arena
    '90065911',  # arg4 chrEntityId
}


# Match: $InitializeCommonEvent(0, NNNNN, arg1, arg2, ...);  OR
#        $InitializeCommonEvent(1, NNNNN, arg1, ...);  (slot 1 — used in some MSBs)
# We capture the event_id and the comma-separated args string for further parsing.
INIT_CALL_RE = re.compile(
    r'\$InitializeCommonEvent\s*\(\s*\d+\s*,\s*(\d+)\s*(?:,\s*([^)]*))?\)\s*;'
)


def parse_init_args(args_str):
    """Parse comma-separated argument list from an InitializeCommonEvent
    call. Returns list of strings (numeric args left as strings — caller
    converts as needed).

    Handles whitespace and trailing commas. Does NOT handle nested parens
    — none of NR's boss-init InitializeCommonEvent calls use them (all
    args are bare integers).
    """
    if not args_str: return []
    return [a.strip() for a in args_str.split(',') if a.strip()]


def classify_arg_role(value, role_name):
    """Decide what kind of entity-ID this arg represents, based on its
    declared role name in the helper signature.

      Returns: 'actual_spawn' | 'secondary_chr' | 'event_flag' | 'param'
               | 'region' | 'asset' | 'sfx_bgm' | 'numeric' | 'unknown'

    The 'actual_spawn' / 'secondary_chr' distinction is the key one — it
    drives whether oops_v3 treats the entity as a swap target (actual_spawn)
    or a preserve-this-anchor entity (secondary_chr).
    """
    if role_name == 'chrEntityId':
        return 'actual_spawn'
    if role_name.startswith('chrEntityId'):
        # chrEntityId2, chrEntityId3, ... — HP-bar / damage-pair / companion refs
        return 'secondary_chr'
    if role_name.startswith('eventFlagId'):
        return 'event_flag'
    if role_name == 'entityId' or role_name == 'entityId2':
        # Bare entity ID — could be region, area, or chr in some events.
        # In wave-sync events (90015442/443), this is the boss-state tracker
        # entity that gets radius-checked against scripted spawn anchors.
        return 'region_or_tracker'
    if role_name == 'areaEntityId':
        return 'region'
    if role_name == 'assetEntityId':
        return 'asset'
    if role_name == 'dummypolyId':
        return 'dummypoly'
    if role_name in ('sfxId', 'bgmBossConvParamId', 'spEffectId',
                     'spEffectId2', 'spEffectId3', 'spEffectId4',
                     'textEffectParamId', 'nameId', 'nameId2', 'nameId3',
                     'userDispLogParamId', 'logObjectId',
                     'animationId', 'value', 'targetDistance', 'targetAmount',
                     'targetProbability'):
        return 'param'
    return 'unknown'


def extract_msb_overlay_signature(msb_basename, emevd_src):
    """For one MSB's EMEVD source, find every $InitializeCommonEvent call
    targeting a known helper, decode its args by helper signature, and
    return a structured summary.

    Returns dict shape:
      {
        'msb': 'm48_60_00_00.msb',
        'helpers_used': ['90015442', '90065050', ...],     # sorted unique
        'is_nb_overlay': bool,                              # any NB_BOSS_INIT_HELPER fires
        'actual_spawn_eids': sorted unique list,            # all chrEntityId values seen
        'secondary_chr_eids': sorted unique list,           # chrEntityId2/3/4/... values
        'event_flag_ids': sorted unique list,
        'region_or_tracker_eids': sorted unique list,
        'init_calls': [
            {'event': '90065050', 'args': [...]},   # one per call, in source order
            ...
        ],
        'unrecognized_event_ids': sorted unique list,       # called but not in HELPER_SIGNATURES
      }
    """
    helpers_used = set()
    actual_spawn = set()
    secondary_chr = set()
    event_flags = set()
    regions = set()
    init_calls = []
    unrecognized = set()

    for m in INIT_CALL_RE.finditer(emevd_src):
        event_id = m.group(1)
        args_raw = m.group(2) or ''
        args = parse_init_args(args_raw)

        sig = HELPER_SIGNATURES.get(event_id)
        if sig is None:
            unrecognized.add(event_id)
            continue

        helpers_used.add(event_id)
        # Map args to roles. Tolerate trailing extra args (some calls
        # append zeros beyond the declared signature length — those get
        # ignored cleanly).
        # Also tolerate fewer args than signature (rare; classify what we have).
        per_call = {'event': event_id, 'args': []}
        for i, role in enumerate(sig):
            if i >= len(args):
                break
            val_str = args[i]
            try:
                val = int(val_str)
            except ValueError:
                # Could be an EMEVD variable reference like Signed(0) — skip
                per_call['args'].append({'role': role, 'value': val_str, 'class': 'symbolic'})
                continue
            arg_class = classify_arg_role(val, role)
            per_call['args'].append({'role': role, 'value': val, 'class': arg_class})
            # Skip zero-valued args — they're "no entity here" sentinels
            # for optional chrEntityId3/4 slots in helpers like 90065910
            if val == 0:
                continue
            if arg_class == 'actual_spawn' and event_id in ACTUAL_SPAWN_HELPERS:
                actual_spawn.add(val)
            elif arg_class == 'secondary_chr':
                secondary_chr.add(val)
            elif arg_class == 'event_flag':
                event_flags.add(val)
            elif arg_class == 'region_or_tracker':
                regions.add(val)
        init_calls.append(per_call)

    return {
        'msb': msb_basename,
        'helpers_used': sorted(helpers_used),
        'is_nb_overlay': bool(helpers_used & NB_BOSS_INIT_HELPERS),
        'actual_spawn_eids': sorted(actual_spawn),
        'secondary_chr_eids': sorted(secondary_chr),
        'event_flag_ids': sorted(event_flags),
        'region_or_tracker_eids': sorted(regions),
        'init_calls': init_calls,
        'unrecognized_event_ids': sorted(unrecognized),
    }


def parse_all_overlays(emevd_dir=EMEVD_DIR):
    """Walk emevd_dir, parse every m*_*_00_00.emevd.js file, return
    {msb_filename → signature dict}."""
    result = {}
    if not os.path.isdir(emevd_dir):
        raise FileNotFoundError(
            f'EMEVD source directory not found: {emevd_dir}\n'
            f'Expected decompiled DarkScript3 output (one .emevd.js per MSB).'
        )
    # Only process map EMEVDs, not common.emevd.js / common_func.emevd.js
    pat = re.compile(r'^m\d{2}_\d{2}_\d{2}_\d{2}\.emevd\.js$')
    for fn in sorted(os.listdir(emevd_dir)):
        if not pat.match(fn):
            continue
        msb_name = fn.replace('.emevd.js', '.msb')
        with open(os.path.join(emevd_dir, fn), encoding='utf-8') as f:
            src = f.read()
        sig = extract_msb_overlay_signature(msb_name, src)
        result[msb_name] = sig
    return result


def build_summary_meta(all_sigs):
    """Aggregate stats across MSBs for the output _meta block."""
    n_msbs = len(all_sigs)
    n_nb_overlays = sum(1 for s in all_sigs.values() if s['is_nb_overlay'])
    n_actual_spawn_total = sum(len(s['actual_spawn_eids']) for s in all_sigs.values())
    n_secondary_total = sum(len(s['secondary_chr_eids']) for s in all_sigs.values())
    helper_use_counts = defaultdict(int)
    for s in all_sigs.values():
        for h in s['helpers_used']:
            helper_use_counts[h] += 1
    unrecognized_total = set()
    for s in all_sigs.values():
        unrecognized_total.update(s['unrecognized_event_ids'])
    return {
        'tool': 'dev/parse_overlay_emevds.py',
        'source_dir': 'dev/emevd_dump/',
        'n_msbs_parsed': n_msbs,
        'n_nb_overlays': n_nb_overlays,
        'n_actual_spawn_eids_total': n_actual_spawn_total,
        'n_secondary_chr_eids_total': n_secondary_total,
        'helper_use_counts': dict(sorted(helper_use_counts.items())),
        'unrecognized_event_ids_seen': sorted(unrecognized_total),
        'notes': [
            'actual_spawn_eids — chrEntityId values from helpers in ACTUAL_SPAWN_HELPERS. '
            'These are the entity IDs that get EnableCharacter / ForceAnimationPlayback. '
            'Swap targets for option B (swap-actual-spawn-instead-of-HP-bar-ref).',
            'secondary_chr_eids — chrEntityId2/3/4/5/6 values. HP-bar refs, damage-pair '
            'anchors, companion-chr entities. These are the slots that need PRESERVATION '
            '(option A v0.25.0-patch3) so the boss-init chain stays intact.',
            'For arenas where actual_spawn_eids and secondary_chr_eids overlap (e.g. '
            'm48_40 where 48400800 is both the actual spawn AND the HP-bar ref), the '
            'split-vs-single distinction is encounter-specific. Option A preserves both '
            'cases conservatively.',
        ],
    }


def write_output(all_sigs, output_path=OUTPUT_PATH):
    """Serialize parsed signatures + meta to JSON."""
    meta = build_summary_meta(all_sigs)
    # Compact init_calls for size — keep them ONLY for NB overlays (other
    # MSBs are mostly empty noise that bloats the file).
    out = {'_meta': meta}
    for msb, sig in all_sigs.items():
        # Trim init_calls from non-NB-overlay MSBs to keep file size reasonable
        if not sig['is_nb_overlay']:
            sig = {k: v for k, v in sig.items() if k != 'init_calls'}
        out[msb] = sig
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, sort_keys=False)
    return output_path, meta


def print_msb_detail(msb_name, sig):
    """Pretty-print one MSB's signature for --msb debug mode."""
    print(f'=== {msb_name} ===')
    print(f'  is_nb_overlay:       {sig["is_nb_overlay"]}')
    print(f'  helpers_used:        {sig["helpers_used"]}')
    print(f'  actual_spawn_eids:   {sig["actual_spawn_eids"]}')
    print(f'  secondary_chr_eids:  {sig["secondary_chr_eids"]}')
    print(f'  event_flag_ids:      {sig["event_flag_ids"][:8]}{"..." if len(sig["event_flag_ids"])>8 else ""}')
    print(f'  region_or_tracker:   {sig["region_or_tracker_eids"]}')
    if sig['unrecognized_event_ids']:
        print(f'  ⚠ unrecognized:      {sig["unrecognized_event_ids"]}')
    print(f'  init_calls ({len(sig.get("init_calls", []))}):')
    for c in sig.get('init_calls', []):
        chr_args = [a for a in c['args'] if a['class'] in ('actual_spawn', 'secondary_chr')]
        if not chr_args:
            continue
        flagged = []
        for a in chr_args:
            mark = '★' if a['class'] == 'actual_spawn' else '·'
            flagged.append(f'{mark}{a["role"]}={a["value"]}')
        print(f'    {c["event"]}: {", ".join(flagged)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--msb', help='Debug: print detail for one MSB and exit')
    ap.add_argument('--check', action='store_true',
                    help='Re-parse + compare against existing output; exit nonzero on diff')
    ap.add_argument('--output', default=OUTPUT_PATH,
                    help=f'Output path (default: {OUTPUT_PATH})')
    args = ap.parse_args()

    all_sigs = parse_all_overlays()

    if args.msb:
        key = args.msb if args.msb.endswith('.msb') else args.msb + '.msb'
        if not key.endswith('_00_00.msb'):
            # Tolerate short form "m48_60" by appending the suffix
            key = key.replace('.msb', '') + '_00_00.msb'
        sig = all_sigs.get(key)
        if sig is None:
            print(f'No EMEVD parsed for {key}', file=sys.stderr)
            return 1
        print_msb_detail(key, sig)
        return 0

    if args.check:
        # Compare against existing file
        if not os.path.isfile(args.output):
            print(f'No existing output at {args.output} — first run, nothing to check.')
            return 0
        with open(args.output, encoding='utf-8') as f:
            existing = json.load(f)
        from io import StringIO
        new_content = StringIO()
        meta = build_summary_meta(all_sigs)
        out = {'_meta': meta}
        for msb, sig in all_sigs.items():
            if not sig['is_nb_overlay']:
                sig = {k: v for k, v in sig.items() if k != 'init_calls'}
            out[msb] = sig
        json.dump(out, new_content, indent=2, sort_keys=False)
        with open(args.output, encoding='utf-8') as f:
            existing_content = f.read()
        if new_content.getvalue() == existing_content:
            print(f'OK — {args.output} matches re-parse.')
            return 0
        else:
            print(f'DIFF — {args.output} does not match re-parse. Re-run without --check to update.')
            return 1

    path, meta = write_output(all_sigs, args.output)
    print(f'Wrote {path}')
    print(f'  MSBs parsed:       {meta["n_msbs_parsed"]}')
    print(f'  NB overlays:       {meta["n_nb_overlays"]}')
    print(f'  Actual-spawn eids: {meta["n_actual_spawn_eids_total"]}')
    print(f'  Secondary eids:    {meta["n_secondary_chr_eids_total"]}')
    if meta['unrecognized_event_ids_seen']:
        print(f'  ⚠ Unrecognized event IDs (not in HELPER_SIGNATURES — review):')
        for ev in meta['unrecognized_event_ids_seen']:
            print(f'      {ev}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
