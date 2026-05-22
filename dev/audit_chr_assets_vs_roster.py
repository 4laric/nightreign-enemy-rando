#!/usr/bin/env python3
"""audit_chr_assets_vs_roster.py — cross-check the rando's tag roster
against the chr/script assets actually deployed in the user's me3 mod
folder. Surfaces gaps where the rando might try to place a chr whose
assets aren't installed.

WHAT IT DOES
   1. Walks the rando's nr_enemy_tags.json + mmv_imports.json tags
      to build the placeable c-prefix roster.
   2. Filters out chrs the rando WON'T try to place anyway
      (V3_EXCLUDE_TARGET_PREFIXES, cinematic-only, etc.) — no point
      flagging missing assets for chrs that never get picked.
   3. Walks the me3 mod folder's chr/ subdir to find what's deployed.
   4. Reports four buckets:
      - PRESENT — chr in placeable roster + assets deployed (good)
      - MISSING-CRITICAL — chr in placeable roster + assets NOT deployed
        (will CTD or stand-still if placed)
      - PRESENT-UNUSED — chr files deployed but not in placeable roster
        (harmless overhead, indicates user has extra DLC/mods)
      - SCRIPT-GAPS — chr deployed but missing battle.luabnd
        (the c5210 Dancing Lion pattern → AI brain missing)

   Optionally cross-references against a source MMV mod folder so the
   user knows where the missing files would come from.

USAGE
   python audit_chr_assets_vs_roster.py
   (Edit RANDO_DIR / MOD_DIR / MMV_DIR below if your paths differ.)

   No dependencies — only stdlib.

OUTPUT
   Console report. Exits 0 always — this is informational, not a
   pass/fail gate.
"""
import json
import os
import re
import sys
from collections import defaultdict


# ---- USER CONFIG ----
# RANDO_DIR is auto-detected (script + oops_v3.py + data/ folder live
# together). If you keep the script elsewhere, set this explicitly.
RANDO_DIR = None  # auto-detect, see below
MOD_DIR = r'C:\Users\alari\AppData\Local\garyttierney\me3\config\profiles\onlyrando\nrando'
MMV_DIR = r'C:\Users\alari\Downloads\More Map Variations-578-2-0-5-1774306525\mod'
# ER_DIR: root of your UXM-unpacked Elden Ring install — the folder
# containing chr/, script/, msg/, etc. as subdirectories. Heritage chrs
# (ER ports in heritage_pack) get their scripts from here, NOT from MMV.
# Set to None to skip ER-source checks.
ER_DIR = r'C:\Program Files (x86)\Steam\steamapps\common\ELDEN RING\Game'  # e.g., r'C:\Games\Elden Ring (unpacked)'

# Auto-detect RANDO_DIR: look in script's own dir, parent, cwd, and
# common nrando install paths. Stops at the first dir containing
# oops_v3.py AND a data/ subfolder.
def _auto_detect_rando_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        here,
        os.path.dirname(here),
        os.getcwd(),
        os.path.dirname(os.getcwd()),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, 'oops_v3.py')) and \
           os.path.isdir(os.path.join(c, 'data')):
            return c
    return None

if RANDO_DIR is None:
    RANDO_DIR = _auto_detect_rando_dir()
    if RANDO_DIR is None:
        print('ERR: could not auto-detect rando dir (containing oops_v3.py + data/).\n'
              '      Place this script next to oops_v3.py, or set RANDO_DIR explicitly.')
        sys.exit(1)


# ---- File patterns ----
CHR_FILE_RE = re.compile(
    r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$',
    re.IGNORECASE
)
SCRIPT_FILE_RE = re.compile(
    r'^(\d{4})\d{2}_(battle|logic)\.luabnd(\.dcx)?$',
    re.IGNORECASE
)


# ---- Helpers ----
def find_subdir(root, sub):
    """Find <root>/<sub> or <root>/Game/<sub> case-insensitively."""
    if not root or not os.path.isdir(root):
        return None
    for direct in (
        os.path.join(root, sub),
        os.path.join(root, sub.lower()),
        os.path.join(root, 'Game', sub),
        os.path.join(root, 'game', sub),
    ):
        if os.path.isdir(direct):
            return direct
    return None


def list_chr_prefixes_in_folder(folder):
    """Return set of c-prefixes (e.g., 'c5040') with at least one chr file."""
    if not folder or not os.path.isdir(folder):
        return set()
    prefixes = set()
    for fname in os.listdir(folder):
        m = CHR_FILE_RE.match(fname)
        if m:
            prefixes.add(m.group(1).lower())
    return prefixes


def list_chr_file_kinds(folder, cp):
    """For a c-prefix, return set of kinds present (chrbnd/anibnd/behbnd/texbnd)."""
    if not folder or not os.path.isdir(folder):
        return set()
    kinds = set()
    cp_lower = cp.lower()
    for fname in os.listdir(folder):
        m = CHR_FILE_RE.match(fname)
        if m and m.group(1).lower() == cp_lower:
            kinds.add(m.group(3).lower())
    return kinds


def list_script_prefixes_in_folder(folder):
    """Return set of 4-digit numeric prefixes that have at least one
    *_battle.luabnd present. (Logic scripts intentionally not required —
    many DS3-port chrs ship without logic.luabnd and work fine.)"""
    if not folder or not os.path.isdir(folder):
        return set()
    prefixes_with_battle = set()
    for fname in os.listdir(folder):
        m = SCRIPT_FILE_RE.match(fname)
        if m and m.group(2).lower() == 'battle':
            prefixes_with_battle.add(m.group(1))
    return prefixes_with_battle


def cp_to_script_prefix(cp):
    """c5840 → '5840'."""
    return cp[1:5] if len(cp) >= 5 and cp.startswith('c') else None


# ---- Tag loading ----
def load_tags(rando_dir):
    """Load nr_enemy_tags + MMV tags, merged. Return {cp: tag_dict}."""
    tags = {}

    nr_path = os.path.join(rando_dir, 'data', 'nr_enemy_tags.json')
    if os.path.isfile(nr_path):
        with open(nr_path, encoding='utf-8') as f:
            nr_tags = json.load(f)
        tags.update(nr_tags)
    else:
        print(f'WARN: nr_enemy_tags.json not found at {nr_path}')

    mmv_path = os.path.join(rando_dir, 'data', 'mmv_imports.json')
    if os.path.isfile(mmv_path):
        with open(mmv_path, encoding='utf-8') as f:
            mmv = json.load(f)
        # MMV tags are authoritative override per apply_mmv_imports semantics
        for cp, t in mmv.get('tags', {}).items():
            tags[cp] = t
    else:
        print(f'WARN: mmv_imports.json not found at {mmv_path}')

    return tags


def get_blacklisted_cps(rando_dir):
    """Return the set of c-prefixes the rando will NOT place
    (mmv blacklist + heritage AI known issues + obvious system chrs)."""
    blocked = set()

    mmv_path = os.path.join(rando_dir, 'data', 'mmv_imports.json')
    if os.path.isfile(mmv_path):
        with open(mmv_path, encoding='utf-8') as f:
            mmv = json.load(f)
        bl = mmv.get('blacklist_when_active', {})
        for k in ('ctd_unidentified', 'dlc_assets_missing_in_mmv', 'ai_broken'):
            blocked.update(bl.get(k, []))

    # System/placeholder c-prefixes — also un-placeable
    # (subset of V3_EXCLUDE_PREFIXES; sufficient for the audit)
    SYSTEM_CPS = {
        'c0000', 'c0010', 'c0100', 'c0110', 'c0120', 'c0130',
        'c1000', 'c1010', 'c10000', 'c19999', 'c50001', 'c50002',
        'c52000', 'c59999', 'c60003', 'c60004', 'c61003', 'c70003',
    }
    blocked.update(SYSTEM_CPS)
    return blocked


def is_placeable(cp, tag, blocked):
    """A chr is placeable if it has a tier, isn't blocked, and isn't
    obviously cinematic-only."""
    if cp in blocked:
        return False
    tier = tag.get('tier', '')
    if tier == 'cinematic':
        return False
    if tier == 'mount_component':
        return False
    return True


# ---- Main audit ----
def main():
    print(f'chr asset audit')
    print(f'  Rando dir: {RANDO_DIR}')
    print(f'  Mod dir:   {MOD_DIR}')
    print(f'  MMV dir:   {MMV_DIR}')

    # Resolve subdirs
    mod_chr = find_subdir(MOD_DIR, 'chr')
    mod_script = find_subdir(MOD_DIR, 'script')
    mmv_chr = find_subdir(MMV_DIR, 'chr')
    mmv_script = find_subdir(MMV_DIR, 'script')
    er_chr = find_subdir(ER_DIR, 'chr') if ER_DIR else None
    er_script = find_subdir(ER_DIR, 'script') if ER_DIR else None

    print()
    print(f'  Mod chr/:     {mod_chr or "NOT FOUND"}')
    print(f'  Mod script/:  {mod_script or "NOT FOUND"}')
    print(f'  MMV chr/:     {mmv_chr or "NOT FOUND"}')
    print(f'  MMV script/:  {mmv_script or "NOT FOUND"}')
    if ER_DIR is None:
        print(f'  ER chr/:      (ER_DIR not set — heritage script-gap checks will skip)')
        print(f'  ER script/:   (ER_DIR not set)')
    else:
        print(f'  ER chr/:      {er_chr or "NOT FOUND"}')
        print(f'  ER script/:   {er_script or "NOT FOUND"}')

    if not mod_chr:
        print('\nERR: mod chr/ folder not accessible — cannot audit. '
              'Check MOD_DIR.')
        return 1

    # Load roster
    tags = load_tags(RANDO_DIR)
    blocked = get_blacklisted_cps(RANDO_DIR)
    print(f'\nRoster: {len(tags)} tagged c-prefixes total, '
          f'{len(blocked)} blocked ({len(tags) - len(blocked)} potentially placeable)')

    # Inventory what's on disk
    mod_cps = list_chr_prefixes_in_folder(mod_chr)
    mod_script_prefixes = list_script_prefixes_in_folder(mod_script)
    mmv_cps = list_chr_prefixes_in_folder(mmv_chr) if mmv_chr else set()
    mmv_script_prefixes = list_script_prefixes_in_folder(mmv_script) if mmv_script else set()
    er_cps = list_chr_prefixes_in_folder(er_chr) if er_chr else set()
    er_script_prefixes = list_script_prefixes_in_folder(er_script) if er_script else set()

    print(f'\nDisk inventory:')
    print(f'  Mod chr/:    {len(mod_cps)} unique c-prefixes')
    print(f'  Mod script/: {len(mod_script_prefixes)} unique chrs with battle.luabnd')
    if mmv_chr:
        print(f'  MMV chr/:    {len(mmv_cps)} unique c-prefixes')
        print(f'  MMV script/: {len(mmv_script_prefixes)} unique chrs with battle.luabnd')
    if er_chr:
        print(f'  ER chr/:     {len(er_cps)} unique c-prefixes')
        print(f'  ER script/:  {len(er_script_prefixes)} unique chrs with battle.luabnd')

    # ============================================================
    # BUCKET 1: chrs in placeable roster, classified by asset state
    # ============================================================
    placeable_cps = {cp for cp, t in tags.items() if is_placeable(cp, t, blocked)}

    present = []         # in roster AND on disk
    missing_critical = []  # in roster, NOT on disk
    incomplete = []      # in roster + on disk but missing some asset types
    script_gaps = []     # chrs on disk but missing battle.luabnd
                         #   (cross-game/heritage only — vanilla NR chrs
                         #    use NR's stock scripts which are always present)

    # Sources we expect to have scripts deployed: MMV imports + heritage
    NEEDS_SCRIPT = set()
    mmv_path = os.path.join(RANDO_DIR, 'data', 'mmv_imports.json')
    if os.path.isfile(mmv_path):
        with open(mmv_path, encoding='utf-8') as f:
            mmv = json.load(f)
        NEEDS_SCRIPT.update(mmv.get('tags', {}).keys())
    # Heritage chrs (ER ports) also need their NNN000_battle.luabnd
    for cp, t in tags.items():
        if t.get('_source') == 'heritage' or t.get('_heritage_imported'):
            NEEDS_SCRIPT.add(cp)

    # Which chrs NEED deployment to the me3 mod chr/ folder?
    # Vanilla NR chrs live in <NR install>/Game/chr/ and ME3 layers
    # the mod folder on top. So vanilla chrs are assumed-present and
    # NOT flagged as missing from the mod folder.
    SOURCES_NEEDING_DEPLOYMENT = {'heritage', 'mmv_import'}

    def needs_deployment(cp, tag):
        """True if this chr needs to be in the me3 mod chr/ folder."""
        src = tag.get('_source', '')
        if src in SOURCES_NEEDING_DEPLOYMENT:
            return True
        # Cross-game origin tagged elsewhere also needs deployment
        if tag.get('origin_game') in ('DS1', 'DS3', 'BB'):
            return True
        return False

    vanilla_assumed_present = 0

    for cp in sorted(placeable_cps):
        t = tags[cp]
        cp_lower = cp.lower()
        name = t.get('name', '?')[:40]
        tier = t.get('tier', '?')
        source = t.get('_source', '?')
        origin = t.get('origin_game', '')
        if not needs_deployment(cp, t):
            # Vanilla NR/ER chrs — assumed-present via NR install layering.
            # Don't flag them as missing. If they ARE in the mod folder
            # (e.g., user deployed extras), count as PRESENT.
            if cp_lower in mod_cps:
                kinds = list_chr_file_kinds(mod_chr, cp)
                expected = {'chrbnd', 'anibnd', 'behbnd'}
                missing_kinds = expected - kinds
                if missing_kinds:
                    incomplete.append((cp, name, tier, source, sorted(missing_kinds)))
                else:
                    present.append((cp, name, tier, source, origin))
            else:
                vanilla_assumed_present += 1
            continue

        # Chrs that DO need deployment
        if cp_lower in mod_cps:
            kinds = list_chr_file_kinds(mod_chr, cp)
            expected = {'chrbnd', 'anibnd', 'behbnd'}  # texbnd is optional
            missing_kinds = expected - kinds
            if missing_kinds:
                incomplete.append((cp, name, tier, source, sorted(missing_kinds)))
            else:
                present.append((cp, name, tier, source, origin))
            # Script check — only meaningful for chrs that should have one
            if cp in NEEDS_SCRIPT:
                script_pfx = cp_to_script_prefix(cp)
                if script_pfx and script_pfx not in mod_script_prefixes:
                    # Route the "where would this come from" check:
                    # heritage chrs come from ER unpack, MMV chrs from MMV mod.
                    if source == 'heritage' or t.get('origin_game') in (None, '', 'ER'):
                        source_label = 'ER'
                        in_src = (script_pfx in er_script_prefixes
                                  if er_script else None)
                    elif source == 'mmv_import':
                        source_label = 'MMV'
                        in_src = (script_pfx in mmv_script_prefixes
                                  if mmv_script else None)
                    else:
                        source_label = '?'
                        in_src = None
                    script_gaps.append((cp, name, source, source_label, in_src))
        else:
            missing_critical.append((cp, name, tier, source, origin))

    # ============================================================
    # BUCKET 2: chrs on disk but NOT in placeable roster
    # ============================================================
    roster_lowered = {cp.lower() for cp in tags.keys()}
    present_unused = sorted(mod_cps - roster_lowered)

    # ============================================================
    # REPORT
    # ============================================================
    def section(title, n_total=None):
        bar = '=' * 70
        suffix = f' ({n_total})' if n_total is not None else ''
        print(f'\n{bar}\n{title}{suffix}\n{bar}')

    section('GOOD: placeable chrs with assets on disk', len(present))
    by_source = defaultdict(list)
    for cp, name, tier, source, origin in present:
        by_source[source].append((cp, name, tier, origin))
    for source in sorted(by_source):
        entries = by_source[source]
        print(f'\n  [{source}]  {len(entries)} chrs')
        # Don't dump all 200+ vanilla chrs — abbreviate
        if len(entries) > 12:
            for cp, name, tier, origin in entries[:5]:
                print(f'    ✓ {cp}  {name:<35}  tier={tier:<14} origin={origin}')
            print(f'    ... ({len(entries) - 5} more)')
        else:
            for cp, name, tier, origin in entries:
                print(f'    ✓ {cp}  {name:<35}  tier={tier:<14} origin={origin}')

    section('CRITICAL: placeable chrs WITHOUT chr assets', len(missing_critical))
    if missing_critical:
        print(f'\n  These chrs CAN be picked by the rando but will fail to load.')
        print(f'  → CTD or stand-still depending on what kind of asset is missing.')
        print()
        for cp, name, tier, source, origin in missing_critical:
            in_mmv = ' [in MMV source]' if cp.lower() in mmv_cps else ''
            print(f'    ✗ {cp}  {name:<35}  tier={tier:<14} '
                  f'src={source:<14} origin={origin}{in_mmv}')
    else:
        print('\n  None. All placeable chrs have chr assets deployed.')

    section('INCOMPLETE: chrs with some but not all asset types', len(incomplete))
    if incomplete:
        print(f'\n  These chrs have chrbnd/anibnd/behbnd partially present.')
        print(f'  → Risk of partial-load or runtime fallback to wrong asset.')
        print()
        for cp, name, tier, source, missing in incomplete:
            print(f'    ⚠ {cp}  {name:<35}  tier={tier:<14} missing={missing}')
    else:
        print('\n  None. All deployed chrs have core asset types.')

    section('SCRIPT GAPS: cross-game chrs missing battle.luabnd', len(script_gaps))
    if script_gaps:
        print(f'\n  Cross-game chrs without an AI brain script.')
        print(f'  → c5210 Dancing Lion pattern. Chr loads visually but '
              f'AI may stand still or loop on phase transitions.')
        print(f'  → Vanilla NR chrs don\'t need this — they use NR\'s '
              f'stock scripts. Only flagged for MMV/heritage chrs.')
        print(f'  → Heritage chrs source scripts from ER unpack; '
              f'MMV chrs source scripts from MMV mod.')
        print()
        for cp, name, source, source_label, in_src in script_gaps:
            if in_src is True:
                note = f' → AVAILABLE in {source_label} source, copy missing'
            elif in_src is False:
                note = f' → not in {source_label} source either (chr may use referenced goal-table)'
            else:  # in_src is None (source not configured)
                note = f' → set {source_label}_DIR to check source availability'
            print(f'    ⚠ {cp}  {name:<35}  src={source}{note}')
    else:
        print('\n  None. All cross-game chrs have battle.luabnd deployed.')

    section('EXTRA: chrs deployed but not in roster', len(present_unused))
    if present_unused:
        print(f'\n  Files in mod chr/ for c-prefixes the rando doesn\'t know about.')
        print(f'  → Harmless. Could be leftover from a previous mod, '
              f'or DLC chrs not yet tagged.')
        print()
        # Abbreviate if long
        if len(present_unused) > 20:
            print(f'    {present_unused[:20]}')
            print(f'    ... ({len(present_unused) - 20} more)')
        else:
            for cp in present_unused:
                print(f'    · {cp}')
    else:
        print('\n  None.')

    # ============================================================
    # SUMMARY
    # ============================================================
    section('SUMMARY')
    print(f'  Placeable c-prefixes in roster:     {len(placeable_cps)}')
    print(f'  └─ Vanilla (assumed in NR install): {vanilla_assumed_present}  (not flagged)')
    print(f'  └─ Assets present:                  {len(present)}  ✓')
    print(f'  └─ Critical (missing chr asset):    {len(missing_critical)}  '
          f'{"✗" if missing_critical else ""}')
    print(f'  └─ Incomplete (partial asset types):{len(incomplete)}  '
          f'{"⚠" if incomplete else ""}')
    print(f'  └─ Script gaps (cross-game only):   {len(script_gaps)}  '
          f'{"⚠" if script_gaps else ""}')
    print(f'  Extra deployed (not in roster):     {len(present_unused)}')

    if missing_critical or script_gaps:
        print(f'\n  Recommended action:')
        if missing_critical:
            available_in_mmv = [cp for cp, _, _, _, _ in missing_critical
                                if cp.lower() in mmv_cps]
            if available_in_mmv:
                print(f'    - Re-run bulk chr import. {len(available_in_mmv)} of the '
                      f'missing chrs are in MMV source and should be copyable.')
            other_missing = [cp for cp, _, _, _, _ in missing_critical
                             if cp.lower() not in mmv_cps]
            if other_missing:
                print(f'    - {len(other_missing)} missing chrs are NOT in MMV source. '
                      f'They may need ER unpack or are heritage-pack chrs. '
                      f'Check origin_game per chr.')
        if script_gaps:
            # Categorize by source label
            er_gaps = [g for g in script_gaps if g[3] == 'ER' and g[4] is True]
            mmv_gaps = [g for g in script_gaps if g[3] == 'MMV' and g[4] is True]
            no_source_gaps = [g for g in script_gaps if g[4] is False]
            no_check = [g for g in script_gaps if g[4] is None]
            if er_gaps:
                print(f'    - {len(er_gaps)} heritage script(s) AVAILABLE in ER unpack — '
                      f'point your importer at ER to grab them.')
            if mmv_gaps:
                print(f'    - {len(mmv_gaps)} MMV script(s) AVAILABLE in MMV source — '
                      f'point your importer at MMV to grab them.')
            if no_source_gaps:
                print(f'    - {len(no_source_gaps)} script(s) not in any configured source. '
                      f'Likely use NR\'s stock referenced goal-tables — usually harmless.')
            if no_check:
                print(f'    - {len(no_check)} script(s) skipped (source not configured). '
                      f'Set ER_DIR / MMV_DIR at top of script to check.')
    else:
        print(f'\n  No action needed. Asset deployment matches placeable roster.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
