#!/usr/bin/env python3
"""check_patches_shipped.py — Verify timeout/safety-net patches landed.

Greps a patched-EMEVD bundle (typically patched_emevd/ in the repo, or a
me3 profile's event/ directory) for the expected fingerprint of each
registered patch. Reports coverage per patch.

Usage:
    python dev/check_patches_shipped.py <bundle_dir>

Or, to check the live shipped bundle in the me3 profile:
    python dev/check_patches_shipped.py "<me3_profile>/<package>/event"

Notes:
    - For .emevd.dcx files (no .js), decompress them first or run against
      the .emevd.dcx.js source bundle (typically what's in patched_emevd/).
    - Each check reports "n/N present" where N is the expected count and
      n is what was found. Mismatch = patch didn't apply OR didn't ship.
    - "ALL N missing" usually means the build pipeline didn't run
      emevd_patch.py before DSAS3, or DSAS3 didn't recompile, or the
      output didn't get copied into the running event/ dir.
"""
import argparse
import os
import re
import sys


def _read(path):
    with open(path, 'rb') as f:
        return f.read().decode('utf-8', errors='replace')


def check_nb_speffect_wait_timeout(bundle):
    """v0.24.74: WaitFor(CharacterHasSpEffect(...)) lines get
    || ElapsedSeconds(10) appended. Expected scope:
    - common_func event 90065040 (1 wait)
    - per-map files: m49_29 (~1), m48_50/60 (variable), more
    Lower bound check: m49_29 must have at least one such line."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('nb_speffect_wait_timeout', 'common_func missing', False)
    cf_text = _read(cf)
    cf_hits = len(re.findall(
        r'WaitFor\(.*CharacterHasSpEffect.*ElapsedSeconds', cf_text))
    m49_29 = os.path.join(bundle, 'm49_29_00_00.emevd.dcx.js')
    arena_hits = 0
    if os.path.exists(m49_29):
        arena_hits = len(re.findall(
            r'WaitFor\(.*CharacterHasSpEffect.*ElapsedSeconds',
            _read(m49_29)))
    ok = cf_hits >= 1 and arena_hits >= 1
    detail = f'common_func: {cf_hits} hits, m49_29: {arena_hits} hits'
    return ('nb_speffect_wait_timeout', detail, ok)


def check_preboss_wave_timeout(bundle):
    """v0.24.103: 90015442 in common_func gets 6 ElapsedSeconds(90)
    timeouts (one per per-tile WaitFor)."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('preboss_wave_timeout', 'common_func missing', False)
    text = _read(cf)
    # Extract event 90015442's body
    m = re.search(r'\$Event\(90015442,.*?^\}\);', text, re.DOTALL | re.MULTILINE)
    if not m:
        return ('preboss_wave_timeout', 'event 90015442 not found in common_func', False)
    body = m.group(0)
    n_timed = len(re.findall(r'ElapsedSeconds\(90\)', body))
    expected = 6
    ok = n_timed >= expected
    return ('preboss_wave_timeout', f'{n_timed}/{expected} 90s timeouts in 90015442', ok)


def check_post_intro_aggro_kick(bundle):
    """v0.24.104: 5 boss-wake handlers in common_func (90005250/251/260/
    261/271) get a WaitFixedTimeSeconds(5) + RequestCharacterAIReplan
    sequence after their terminal EnableCharacterAI."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('post_intro_aggro_kick', 'common_func missing', False)
    text = _read(cf)
    n_replan = 0
    for evid in (90005250, 90005251, 90005260, 90005261, 90005271):
        m = re.search(
            rf'\$Event\({evid},.*?^\}}\);', text, re.DOTALL | re.MULTILINE)
        if m and 'RequestCharacterAIReplan' in m.group(0):
            n_replan += 1
    ok = n_replan == 5
    return ('post_intro_aggro_kick', f'{n_replan}/5 boss-wake handlers patched', ok)


def check_xxxx2810_trigger_timeout(bundle):
    """v0.24.106: Each NB arena's $Event(XXXX2810) gets `|| ElapsedSeconds(90)`
    appended to the WaitFor(EventFlag(eventFlagId3)) gate. Expected: 25 NB
    arena files have the timed form."""
    nb_stems = (
        'm48_00_00_00', 'm48_10_00_00', 'm48_20_00_00', 'm48_30_00_00',
        'm48_40_00_00', 'm48_50_00_00', 'm48_60_00_00', 'm48_70_00_00',
        'm48_80_00_00', 'm48_90_00_00',
        'm49_10_00_00', 'm49_17_00_00', 'm49_18_00_00', 'm49_19_00_00',
        'm49_20_00_00', 'm49_21_00_00', 'm49_23_00_00', 'm49_24_00_00',
        'm49_25_00_00', 'm49_26_00_00', 'm49_27_00_00', 'm49_28_00_00',
        'm49_29_00_00', 'm49_30_00_00', 'm49_90_00_00',
    )
    timed = 0
    missing_files = 0
    for stem in nb_stems:
        path = os.path.join(bundle, f'{stem}.emevd.dcx.js')
        if not os.path.exists(path):
            missing_files += 1
            continue
        text = _read(path)
        # The pattern is content-keyed: a WaitFor that mentions both
        # eventFlagId3 AND ElapsedSeconds is the post-patch shape.
        for line in text.splitlines():
            m = re.match(r'^\s*WaitFor\((.+?)\);', line)
            if not m: continue
            expr = m.group(1)
            if 'eventFlagId3' in expr and 'ElapsedSeconds' in expr:
                timed += 1
                break
    expected = 25
    note = ''
    if missing_files:
        note = f' ({missing_files} files not in bundle)'
    ok = timed == expected
    return ('xxxx2810_trigger_timeout', f'{timed}/{expected} arenas timed{note}', ok)


def check_death_timeout_present(bundle):
    """v0.23.x death_timeout in common_func. Coarse check: presence of the
    timeout addition somewhere in common_func."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('death_timeout', 'common_func missing', False)
    text = _read(cf)
    # The death_timeout fingerprint varies; look for ElapsedSeconds in
    # any death-related event.
    ok = 'ElapsedSeconds' in text
    return ('death_timeout', 'common_func contains ElapsedSeconds', ok)


def check_nb_wave_bypass_retired(bundle):
    """v0.24.105 nb_wave_bypass was retired in v0.24.106. The build should
    NOT contain $Event(99055100). If it does, the user is running a stale
    build with the (broken) retired patch artifacts."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('nb_wave_bypass (retired)', 'common_func missing', False)
    text = _read(cf)
    if '$Event(99055100' in text:
        return ('nb_wave_bypass (retired)',
                'STALE — $Event(99055100) still in common_func; rebuild from vanilla',
                False)
    return ('nb_wave_bypass (retired)', 'no stale artifacts', True)


def check_nb_boss_force_enable_watchdog(bundle):
    """v0.24.110: $Event(99055200) in common_func + 25 per-arena
    $InitializeCommonEvent(0, 99055200, triggerFlag, boss1, boss2)
    registrations. Force-enable recovery watchdog, armed per-arena on
    encounter-start flag. PlaySE tracers for diagnostics."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('nb_boss_force_enable_watchdog', 'common_func missing', False)
    text = _read(cf)
    if '$Event(99055200,' not in text:
        return ('nb_boss_force_enable_watchdog', 'event 99055200 not found', False)
    # Extract event body
    m = re.search(r'\$Event\(99055200,.*?^\}\);', text, re.DOTALL | re.MULTILINE)
    if not m:
        return ('nb_boss_force_enable_watchdog',
                'could not extract event body', False)
    body = m.group(0)
    # v110 shape: parameterized event taking (triggerFlag, bossEntity1, bossEntity2)
    if 'function(triggerFlag, bossEntity1, bossEntity2)' not in body:
        return ('nb_boss_force_enable_watchdog',
                'event signature not v110 (expected (triggerFlag, bossEntity1, bossEntity2))',
                False)
    # Body should EnableCharacter on the parameters (not literals)
    if 'EnableCharacter(bossEntity1);' not in body or 'EnableCharacter(bossEntity2);' not in body:
        return ('nb_boss_force_enable_watchdog',
                'event body missing EnableCharacter on parameters', False)
    has_tracers = 'PlaySE(20000' in body
    tracer_note = ', tracers' if has_tracers else ' (no tracers)'

    # Count per-arena registrations
    nb_stems = (
        'm48_00_00_00', 'm48_10_00_00', 'm48_20_00_00', 'm48_30_00_00',
        'm48_40_00_00', 'm48_50_00_00', 'm48_60_00_00', 'm48_70_00_00',
        'm48_80_00_00', 'm48_90_00_00',
        'm49_10_00_00', 'm49_17_00_00', 'm49_18_00_00', 'm49_19_00_00',
        'm49_20_00_00', 'm49_21_00_00', 'm49_23_00_00', 'm49_24_00_00',
        'm49_25_00_00', 'm49_26_00_00', 'm49_27_00_00', 'm49_28_00_00',
        'm49_29_00_00', 'm49_30_00_00', 'm49_90_00_00',
    )
    n_registered = 0
    for stem in nb_stems:
        path = os.path.join(bundle, f'{stem}.emevd.dcx.js')
        if os.path.exists(path) and 'InitializeCommonEvent(0, 99055200' in _read(path):
            n_registered += 1
    ok = n_registered == 25
    return ('nb_boss_force_enable_watchdog',
            f'event present, {n_registered}/25 arenas registered{tracer_note}', ok)


def check_nb_arena_entry_trigger(bundle):
    """v0.24.109: $Event(99055300) in common_func + 25 per-arena
    $InitializeCommonEvent(0, 99055300, anchor, flag) registrations.
    Player-initiated arena trigger; coexists idempotently with vanilla
    ring-close flow."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('nb_arena_entry_trigger', 'common_func missing', False)
    cf_text = _read(cf)
    has_event = '$Event(99055300,' in cf_text
    if not has_event:
        return ('nb_arena_entry_trigger',
                'event 99055300 not in common_func', False)
    # Count per-arena registrations
    nb_stems = (
        'm48_00_00_00', 'm48_10_00_00', 'm48_20_00_00', 'm48_30_00_00',
        'm48_40_00_00', 'm48_50_00_00', 'm48_60_00_00', 'm48_70_00_00',
        'm48_80_00_00', 'm48_90_00_00',
        'm49_10_00_00', 'm49_17_00_00', 'm49_18_00_00', 'm49_19_00_00',
        'm49_20_00_00', 'm49_21_00_00', 'm49_23_00_00', 'm49_24_00_00',
        'm49_25_00_00', 'm49_26_00_00', 'm49_27_00_00', 'm49_28_00_00',
        'm49_29_00_00', 'm49_30_00_00', 'm49_90_00_00',
    )
    n_registered = 0
    for stem in nb_stems:
        path = os.path.join(bundle, f'{stem}.emevd.dcx.js')
        if os.path.exists(path) and 'InitializeCommonEvent(0, 99055300' in _read(path):
            n_registered += 1
    ok = n_registered == 25
    return ('nb_arena_entry_trigger',
            f'event present, {n_registered}/25 arenas registered',
            ok)


def check_nb_arena_hold_trigger(bundle):
    """v0.24.111: $Event(99055400) in common_func + 25 per-arena
    $InitializeCommonEvent(0, 99055400, anchor, flag) registrations.
    Hold-to-trigger arena starter with AV feedback (loud SFX +
    boss-defeat banner)."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('nb_arena_hold_trigger', 'common_func missing', False)
    cf_text = _read(cf)
    if '$Event(99055400,' not in cf_text:
        return ('nb_arena_hold_trigger', 'event 99055400 not in common_func', False)
    # Verify the AV feedback is present
    m = re.search(r'\$Event\(99055400,.*?^\}\);', cf_text, re.DOTALL | re.MULTILINE)
    if not m:
        return ('nb_arena_hold_trigger',
                'could not extract event body', False)
    body = m.group(0)
    has_sfx = 'PlaySE(20000' in body
    has_banner = 'DisplayTextEffectId' in body
    if not (has_sfx and has_banner):
        return ('nb_arena_hold_trigger',
                f'event present but missing AV feedback (sfx={has_sfx}, banner={has_banner})',
                False)
    # Count per-arena registrations
    nb_stems = (
        'm48_00_00_00', 'm48_10_00_00', 'm48_20_00_00', 'm48_30_00_00',
        'm48_40_00_00', 'm48_50_00_00', 'm48_60_00_00', 'm48_70_00_00',
        'm48_80_00_00', 'm48_90_00_00',
        'm49_10_00_00', 'm49_17_00_00', 'm49_18_00_00', 'm49_19_00_00',
        'm49_20_00_00', 'm49_21_00_00', 'm49_23_00_00', 'm49_24_00_00',
        'm49_25_00_00', 'm49_26_00_00', 'm49_27_00_00', 'm49_28_00_00',
        'm49_29_00_00', 'm49_30_00_00', 'm49_90_00_00',
    )
    n_registered = 0
    for stem in nb_stems:
        path = os.path.join(bundle, f'{stem}.emevd.dcx.js')
        if os.path.exists(path) and 'InitializeCommonEvent(0, 99055400' in _read(path):
            n_registered += 1
    ok = n_registered == 25
    return ('nb_arena_hold_trigger',
            f'event present + AV feedback, {n_registered}/25 arenas registered', ok)


def check_nb_boss_init_diag_tracers(bundle):
    """v0.24.112/113 (diagnostic-only): PlaySE+DisplayTextEffectId tracers
    inserted at top of 90015000/30/02 common_func boss-init events.

    v0.24.113 revision: all three events share SFX 888880000 (the proven-
    audible vanilla boss-defeat emphasis sound) but each shows a different
    DisplayTextEffectId banner (1020/2200/2300) so the player can VISUALLY
    distinguish which event fired.

    NOT a production patch — should be removed once we know which events
    fire during a real NB encounter."""
    cf = os.path.join(bundle, 'common_func.emevd.dcx.js')
    if not os.path.exists(cf):
        return ('nb_boss_init_diag_tracers', 'common_func missing', False)
    text = _read(cf)
    expected = {
        90015000: 1020,
        90015030: 2200,
        90015002: 2300,
    }
    found = []
    for event_id, banner_id in expected.items():
        # Look for the event followed shortly by our SFX + banner pair
        m = re.search(
            rf'\$Event\({event_id},.*?'
            rf'PlaySE\(20000, SoundType\.SFX, 888880000\);.*?'
            rf'DisplayTextEffectId\({banner_id}\);',
            text, re.DOTALL)
        if m:
            found.append(f'{event_id}=banner{banner_id}')
    if not found:
        return ('nb_boss_init_diag_tracers', 'no tracers present', False)
    ok = len(found) == 3
    note = ', '.join(found)
    return ('nb_boss_init_diag_tracers',
            f'{len(found)}/3 tracers ({note})', ok)


CHECKS = [
    check_nb_speffect_wait_timeout,
    check_preboss_wave_timeout,
    check_post_intro_aggro_kick,
    check_xxxx2810_trigger_timeout,
    check_nb_boss_force_enable_watchdog,
    check_nb_arena_entry_trigger,
    check_nb_arena_hold_trigger,
    check_nb_boss_init_diag_tracers,
    check_death_timeout_present,
    check_nb_wave_bypass_retired,
]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('bundle_dir',
                   help='Path to patched EMEVD bundle (.emevd.dcx.js files)')
    args = p.parse_args()

    if not os.path.isdir(args.bundle_dir):
        print(f'ERROR: bundle dir not found: {args.bundle_dir}', file=sys.stderr)
        sys.exit(2)

    n_files = sum(1 for f in os.listdir(args.bundle_dir)
                  if f.endswith('.emevd.dcx.js'))
    print(f'Bundle: {args.bundle_dir} ({n_files} .emevd.dcx.js files)')
    print()

    all_ok = True
    for check in CHECKS:
        name, detail, ok = check(args.bundle_dir)
        mark = '✓' if ok else '✗'
        print(f'  {mark} {name:34}  {detail}')
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print('All checks passed. The build pipeline shipped the expected patches.')
        return 0
    else:
        print('One or more checks failed. The build pipeline may not have shipped')
        print('the latest patches. To rebuild from vanilla:')
        print('  python emevd_patch.py patch <vanilla_dir> <bundle_dir>')
        print('Then recompile via DSAS3 and re-deploy to the me3 profile.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
