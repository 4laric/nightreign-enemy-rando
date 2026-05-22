#!/usr/bin/env python3
"""v0.23.07 Phase 1 audit — exhaustive offline coverage of the placement layer.

Runs cmd_shuffle_v3 over a sweep of seeds with mp_safe ON/OFF and reports:

  1a. NB-caliber gate violations — non-caliber c-prefixes at NB arena slots
  1b. Uniqueness cap violations — count > cap for any capped c-prefix
  1c. Heritage leak violations — non-vanilla c-prefixes at mp_safe runs
  1d. Multi-entity arena diversity — same target appearing twice in arena
  1e. Performance regression — per-seed timing

Usage:
  python3 dev/v0_23_07_audit.py                # 5 seeds, default
  python3 dev/v0_23_07_audit.py --seeds 50     # wider sweep
  python3 dev/v0_23_07_audit.py --verbose      # show every NB placement
"""

import argparse
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from contextlib import redirect_stdout

# Run from repo root (parent of dev/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oops_v3


# The 22 NB arena MSBs (entity_id-sorted, see V0_23_07_TEST_PLAN.md)
NB_ARENAS = [
    'm47_70_00_00', 'm48_40_00_00', 'm48_50_00_00', 'm48_60_00_00',
    'm48_70_00_00', 'm48_80_00_00', 'm48_90_00_00', 'm49_10_00_00',
    'm49_17_00_00', 'm49_18_00_00', 'm49_19_00_00', 'm49_20_00_00',
    'm49_21_00_00', 'm49_23_00_00', 'm49_24_00_00', 'm49_25_00_00',
    'm49_26_00_00', 'm49_27_00_00', 'm49_28_00_00', 'm49_29_00_00',
    'm49_30_00_00', 'm49_90_00_00',
]

# Multi-entity arenas — within these, distinct targets are expected
# (same target appearing twice is the "anticlimactic" failure mode).
MULTI_ENTITY_ARENAS = [
    'm48_50_00_00',  # Tree Sentinel + Knight support
    'm48_60_00_00',
    'm48_80_00_00',  # Godskin Duo
    'm49_25_00_00',  # Crucible + Hippo
    'm49_28_00_00',  # Cavalry x2
    'm49_29_00_00',  # Queen + Swordmaster
]

DEFAULT_SEEDS = [394059, 555111, 222222, 887995, 974234]


def vanilla_models_set(msb_dir):
    """The 232 vanilla c-prefixes from base NR's MSB Models sections."""
    out = set()
    for path in glob.glob(os.path.join(msb_dir, '*.msb')):
        with open(path, 'rb') as fp:
            data = fp.read()
        sections = oops_v3.parse_msb_sections(data)
        for eo in sections[0]['entry_offsets']:
            nm = oops_v3.parse_model_entry(data, eo).get('name', '')
            cp = nm.split('_')[0]
            if cp.startswith('c') and cp[1:].isdigit():
                out.add(cp)
    return out


def run_seed(work_in, seed, mp_safe):
    """One shuffle invocation, returns (spoiler_dict, elapsed_seconds)."""
    work_out = tempfile.mkdtemp(prefix=f'audit_{seed}_{mp_safe}_')
    t0 = time.time()
    f = io.StringIO()
    with redirect_stdout(f):
        oops_v3.cmd_shuffle_v3(
            input_dir=work_in, output_dir=work_out,
            seed=seed, cluster_aware=True, multiplayer_safe=mp_safe,
        )
    elapsed = time.time() - t0
    with open(os.path.join(work_out, '_spoilers.json')) as fp:
        s = json.load(fp)
    shutil.rmtree(work_out, ignore_errors=True)
    return s, elapsed


def check_caliber(spoiler):
    """Count NB-arena slots whose target is not in the caliber set."""
    violations = []
    for e in spoiler['entries']:
        msb_base = e['map'].replace('.msb', '')
        if msb_base not in NB_ARENAS:
            continue
        if 'Night Boss' not in e['original'].get('name', ''):
            continue
        if e['new']['c_prefix'] not in oops_v3.V3_NIGHT_BOSS_CALIBER_TARGETS:
            violations.append((msb_base, e['part_index'],
                               e['original']['c_prefix'],
                               e['new']['c_prefix'],
                               e['new'].get('name', '')))
    return violations


def check_caps(spoiler):
    """Count placements per cp; report any over cap."""
    counts = Counter(e['new']['c_prefix'] for e in spoiler['entries'])
    violations = []
    for cp, cap in oops_v3.V3_UNIQUE_TARGET_CAPS.items():
        if counts.get(cp, 0) > cap:
            violations.append((cp, counts[cp], cap))
    return violations


def check_heritage_leaks(spoiler, vanilla_set):
    """For mp_safe runs, every target should be a vanilla NR c-prefix."""
    leaks = []
    for e in spoiler['entries']:
        if e['new']['c_prefix'] not in vanilla_set:
            leaks.append((e['map'], e['part_index'],
                          e['new']['c_prefix']))
    return leaks


def check_multi_entity_diversity(spoiler):
    """For each multi-entity arena, confirm the boss-marker slots get
    distinct c-prefixes. Same-target-twice is a finding to surface
    (may be legitimate cap=2 collision, but worth flagging)."""
    findings = []
    for arena in MULTI_ENTITY_ARENAS:
        msb = arena + '.msb'
        boss_slot_picks = []
        for e in spoiler['entries']:
            if e['map'] != msb:
                continue
            if 'Night Boss' not in e['original'].get('name', ''):
                continue
            # Skip Spirit-summon support entities — those are scripted-spawned,
            # not the headline duo participants
            if 'Spirit' in e['original'].get('name', ''):
                continue
            # Skip mount-half of rider+mount pairs (we want to compare riders)
            if 'Horse' in e['original'].get('name', '') or \
               'Steed' in e['original'].get('name', ''):
                continue
            boss_slot_picks.append((e['part_index'], e['new']['c_prefix']))
        if len(boss_slot_picks) >= 2:
            cps = [p[1] for p in boss_slot_picks]
            if len(set(cps)) < len(cps):
                findings.append((arena, boss_slot_picks))
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=5,
                    help='Number of seeds to sweep (default 5)')
    ap.add_argument('--seed-list', nargs='*', type=int,
                    help='Explicit seed list (overrides --seeds)')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='Show every NB-arena placement, not just violations')
    ap.add_argument('--msb-dir',
                    default='/home/claude/decompiled/nr_decompiled_msbs',
                    help='Path to vanilla NR decompiled MSBs')
    args = ap.parse_args()

    if args.seed_list:
        seeds = args.seed_list
    elif args.seeds <= len(DEFAULT_SEEDS):
        seeds = DEFAULT_SEEDS[:args.seeds]
    else:
        # Generate additional deterministic seeds
        import random as _r
        rng = _r.Random(0xC0DEFEED)
        seeds = list(DEFAULT_SEEDS)
        while len(seeds) < args.seeds:
            seeds.append(rng.randint(100000, 999999))

    print(f'v0.23.07 audit')
    print(f'  Engine: {oops_v3.V3_ENGINE_VERSION}'
          f' ({oops_v3.V3_ENGINE_FINGERPRINT})')
    print(f'  Caliber set size: {len(oops_v3.V3_NIGHT_BOSS_CALIBER_TARGETS)}')
    print(f'  Unique caps: {len(oops_v3.V3_UNIQUE_TARGET_CAPS)} entries')
    print(f'  Seeds: {len(seeds)} total')
    print(f'  Modes: mp_safe ON + OFF')
    print()

    # Set up workdir + load vanilla
    work_in = tempfile.mkdtemp(prefix='audit_in_')
    for src in glob.glob(os.path.join(args.msb_dir, '*.msb')):
        shutil.copy(src, work_in)
    vanilla = vanilla_models_set(args.msb_dir)

    # Aggregate counters
    total = {'caliber': 0, 'caps': 0, 'leaks': 0, 'diversity': 0}
    timings = []

    print(f'{"seed":<10}{"mp_safe":<9}{"calib":<7}{"caps":<6}'
          f'{"leak":<6}{"div":<6}{"time":<8}')
    print('-' * 70)
    for seed in seeds:
        for mp_safe in (True, False):
            spoiler, elapsed = run_seed(work_in, seed, mp_safe)
            timings.append(elapsed)

            cal_v = check_caliber(spoiler)
            cap_v = check_caps(spoiler)
            leak_v = check_heritage_leaks(spoiler, vanilla) if mp_safe else []
            div_v = check_multi_entity_diversity(spoiler)

            total['caliber'] += len(cal_v)
            total['caps'] += len(cap_v)
            total['leaks'] += len(leak_v)
            total['diversity'] += len(div_v)

            print(f'{seed:<10}{str(mp_safe):<9}'
                  f'{len(cal_v):<7}{len(cap_v):<6}'
                  f'{len(leak_v):<6}{len(div_v):<6}{elapsed:<8.2f}')

            # Show details on any violations
            for arena, pi, src_cp, new_cp, new_nm in cal_v:
                print(f'    CALIBER {arena} pi={pi}: '
                      f'{src_cp} -> {new_cp} ({new_nm[:30]})')
            for cp, n, cap in cap_v:
                print(f'    CAPS {cp}: {n} placements (cap={cap})')
            for msb, pi, cp in leak_v[:3]:  # cap leak detail at 3
                print(f'    LEAK {msb} pi={pi}: {cp}')
            if len(leak_v) > 3:
                print(f'    LEAK ... and {len(leak_v) - 3} more')
            for arena, picks in div_v:
                print(f'    DIVERSITY {arena} same-target: '
                      f'{[p[1] for p in picks]}')

            # Verbose: show every NB placement
            if args.verbose:
                for arena in NB_ARENAS:
                    for e in spoiler['entries']:
                        if e['map'] != arena + '.msb':
                            continue
                        if 'Night Boss' not in e['original'].get('name', ''):
                            continue
                        new_cp = e['new']['c_prefix']
                        in_cal = ('OK' if new_cp in
                                  oops_v3.V3_NIGHT_BOSS_CALIBER_TARGETS
                                  else 'NON-CAL')
                        print(f'    {arena} pi={e["part_index"]:<3} '
                              f'{e["original"]["c_prefix"]} -> {new_cp} '
                              f'[{in_cal}] {e["new"].get("name", "")[:30]}')

    shutil.rmtree(work_in, ignore_errors=True)

    # Summary
    print()
    print('=== Summary ===')
    print(f'  Total runs: {len(seeds) * 2}')
    print(f'  Caliber violations: {total["caliber"]}'
          f'  {"OK" if total["caliber"] == 0 else "FAIL"}')
    print(f'  Cap violations:     {total["caps"]}'
          f'  {"OK" if total["caps"] == 0 else "FAIL"}')
    print(f'  Heritage leaks:     {total["leaks"]}'
          f'  {"OK" if total["leaks"] == 0 else "FAIL"}')
    print(f'  Diversity findings: {total["diversity"]}'
          f'  (informational; same-target may be legitimate)')
    print(f'  Mean run time:      {sum(timings)/len(timings):.2f}s'
          f'  (range {min(timings):.2f}-{max(timings):.2f}s)')
    print()
    pass_phase1 = (total['caliber'] == 0
                   and total['caps'] == 0
                   and total['leaks'] == 0)
    print(f'Phase 1 audit: {"PASS" if pass_phase1 else "FAIL"}')
    return 0 if pass_phase1 else 1


if __name__ == '__main__':
    sys.exit(main())
