#!/usr/bin/env python3
"""Build a per-arena chr-role catalog by parsing vanilla decompiled EMEVDs.

This is the foundation for v0.25.1 options B + C + D. It walks every
overlay-MSB EMEVD (m4x/m45/m46/m47/m48/m49 etc.), finds every
InitializeCommonEvent call into the known boss-init helpers, extracts
the chr entity IDs by position in the event signature, and records the
role each entity plays in the boss-spawn chain.

Output: data/nr_boss_arena_chr_roles.json

Schema per MSB:
  {
    "m48_60_00_00.msb": {
      "actual_chr_eids":  [48605800],          # where EnableCharacter fires
      "hp_bar_ref_eids":  [48600800, 48600810, 48600820],  # HP bar anchors
      "companion_eids":   [48600811, 48600821, 48600801, ...],  # minions/spirits
      "helpers_used":     ["90015442", "90065050", "90065911", ...],
      "hardcoded_anims":  [20026, 20005],       # chr-specific anim IDs in EMEVD
      "is_multi_entity":  true,
      "is_multi_wave":    true,
      "complexity_score": 12,                   # rough heuristic
      "recommended_strategy": "preserve_vanilla"  # B / C-light / D
    }
  }

The "recommended_strategy" tells oops_v3's swap pipeline what to do:
  - "swap_actual_chr": safe to swap the actual_chr_eid slot, preserve
    HP-bar refs and companions vanilla (option B)
  - "preserve_primary": swap nothing; entire arena stays vanilla
    (option D — for complex multi-wave arenas where any swap risks
    breaking the wake-handshake choreography)
  - "swap_normal": no role-driven preservation needed; arena uses
    plain 90015000 boss-init and behaves like a single-entity slot

Run:
  python3 dev/build_arena_chr_roles.py \\
      /path/to/vanilla_decompressed_emevd \\
      data/nr_boss_arena_chr_roles.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any


# Event signatures for known boss-init helpers, expressed as the arg
# positions (0-indexed, AFTER eventSlot + eventID) where chr entity
# IDs appear. Each entry is (event_id, role -> list of arg indices).
#
# Sourced from common_func.emevd.js inspection. arg index = position
# in $InitializeCommonEvent(0, EVENT_ID, arg0, arg1, ...) — counted from
# arg0, NOT including the leading slot=0 and EVENT_ID.
EVENT_SIGNATURES: dict[int, dict[str, list[int]]] = {
    # 90015000(eventFlagId, chrEntityId, nameId, targetDistance, bgm, eventFlagId2)
    90015000: {
        'actual_chr': [1],
    },
    # 90015442(entityId, eventFlagId) — wave-sync region radius check, entityId
    # is the boss entity being checked against scripted spawn anchors. This
    # is the HP-bar-ref position typically.
    90015442: {
        'hp_bar_ref': [0],
    },
    # 90015443(entityId, eventFlagId) — wave-continue sync
    90015443: {
        'hp_bar_ref': [0],
    },
    # 90065910(eventFlagId, eventFlagId2, eventFlagId3, bgm, sfxId,
    #          chrEntityId, chrEntityId2, nameId, chrEntityId3, nameId2,
    #          chrEntityId4, nameId3)
    # chrEntityId = actual chr; chrEntityId2 = HP bar entity 1; etc.
    90065910: {
        'actual_chr':  [5],
        'hp_bar_ref':  [6, 8, 10],  # multi-bar entries (some 0)
    },
    # 90065911(eventFlagId, eventFlagId2, bgm, chrEntityId, chrEntityId2,
    #          nameId, chrEntityId3, nameId2, chrEntityId4, nameId3,
    #          chrEntityId5)
    # Death cleanup; chrEntityId5 is extra entity to force-kill.
    90065911: {
        'actual_chr':  [3],
        'hp_bar_ref':  [4, 6, 8],
        'companion':   [10],
    },
    # 90065900(entityId, value, assetEntityId, chrEntityId, textEffect,
    #          bgm, logObjectId, entityId2) — boss-defeated. entityId is
    # the death-flag eid (= HP bar ref typically). chrEntityId here is
    # an additional chr to EnableCharacter after defeat (post-boss spawn).
    90065900: {
        'hp_bar_ref':  [0, 7],
        'companion':   [3],  # post-defeat reveal (also acts as chr)
    },
    # 90065050(eventFlagId, eventFlagId2, eventFlagId3, bgm,
    #          chrEntityId, chrEntityId2, nameId, chrEntityId3, nameId2,
    #          chrEntityId4, nameId3, chrEntityId5, chrEntityId6)
    # Three-boss + two-mount complex multi-entity boss-init (Tree Sentinel
    # + 2 Royal Cavalrymen). chrEntityId is actual spawn chr;
    # chrEntityId2/3/4 are HP bar entities; chrEntityId5/6 are mount entities.
    90065050: {
        'actual_chr':  [4],
        'hp_bar_ref':  [5, 7, 9],
        'companion':   [11, 12],  # mounts
    },
    # 90065051(chrEntityId, chrEntityId2, chrEntityId3, eventFlagId)
    # — sub-helper for multi-entity. chrEntityId/2/3 are participating chrs.
    90065051: {
        'companion': [0, 1, 2],
    },
    # 90065052(chrEntityId, chrEntityId2, chrEntityId3, spEffect,
    #          dummypoly, eventFlagId, eventFlagId2)
    # — wave companion handler
    90065052: {
        'companion': [0, 1, 2],
    },
    # 90065053(chrEntityId, chrEntityId2, eventFlagId, eventFlagId2)
    90065053: {
        'companion': [0, 1],
    },
    # 90065054(chrEntityId, chrEntityId2, eventFlagId, eventFlagId2)
    90065054: {
        'companion': [0, 1],
    },
    # 90065055(chrEntityId, chrEntityId2, spEffect, eventFlagId, eventFlagId2)
    90065055: {
        'companion': [0, 1],
    },
    # 90065056(chrEntityId, chrEntityId2, chrEntityId3, spEffect,
    #          dummypoly, area, entity, eventFlagId, eventFlagId2)
    90065056: {
        'companion': [0, 1, 2],
    },
    # 90065057(chrEntityId, eventFlagId) — low-HP force-death helper
    90065057: {
        'companion': [0],
    },
    # 90065040(chrEntityId, chrEntityId2, eventFlagId, eventFlagId2)
    # — m49_29 Demi-Human Swordmaster pairing helper
    90065040: {
        'hp_bar_ref': [0],
        'companion':  [1],
    },
    # 90065041(chrEntityId, chrEntityId2, eventFlagId, eventFlagId2)
    # — m49_29 Demi-Human-side helper
    90065041: {
        'hp_bar_ref': [0],
        'companion':  [1],
    },
    # 90065920(chrEntityId, spEffectId) — per-chr SpEffect setup
    90065920: {
        'companion': [0],
    },
    # 90015002(value, eventFlagId, chrEntityId, chrEntityId2, textParam,
    #          bgm, voice, name, chrEntityId3)
    # — boss intro/discovery event. chrEntityId is the actual spawn chr;
    # chrEntityId2 is the HP bar tracker (often same eid for single-entity
    # arenas, different for multi-entity).
    # v0.25.2: position 2 is actual_chr (was hp_bar_ref). When the eid
    # appears in BOTH actual_chr and hp_bar_ref (single-entity arena),
    # v0.25.1's lift-from-patch3 logic correctly identifies it as swap-
    # eligible and removes the broad patch3 preservation.
    90015002: {
        'actual_chr': [2],
        'hp_bar_ref': [3, 8],
    },
    # 90015008(area, chrEntityId, bgm, chrEntityId2, sfxId, value)
    # v0.25.2: position 1 is actual_chr (was hp_bar_ref).
    90015008: {
        'actual_chr': [1],
        'hp_bar_ref': [3],
    },
    # 90015020(eventFlagId, chrEntityId)
    90015020: {
        'hp_bar_ref': [1],
    },
    # 90015023(eventFlagId, distance, value, chrEntityId, chrEntityId2,
    #          name, chrEntityId3, name2, chrEntityId4, name3, val5, val6)
    90015023: {
        'actual_chr': [3],
        'hp_bar_ref': [4, 6, 8],
    },
    # 90015030(eventFlagId, chrEntityId, distance, bgm, value)
    90015030: {
        'actual_chr': [1],
    },
    # 90015446(chrEntityId, eventFlagId, eventFlagId2, entityId)
    # — boss-arena state handler. chrEntityId may be actual or hp_bar_ref
    # depending on arena; we tag it as hp_bar_ref since the same eid is
    # typically passed as chrEntityId2 in 90065910/90065050.
    90015446: {
        'hp_bar_ref': [0],
    },
    # 90015460(entityId, chrEntityId)
    90015460: {
        'companion': [1],
    },
    # 90015470(entityId, eventFlagId, chrEntityId, chrEntityId2, chrEntityId3,
    #          val5, val6, chrEntityId4)
    90015470: {
        'actual_chr':  [2],
        'hp_bar_ref':  [3],
        'companion':   [4, 7],
    },
    # 90015475(entityId, chrEntityId)
    90015475: {
        'companion': [1],
    },
    # 90015011(chrEntityId, eventFlagId, eventFlagId2)
    90015011: {
        'actual_chr': [0],
    },
    # 90015012(chrEntityId, eventFlagId)
    90015012: {
        'actual_chr': [0],
    },
}


# Init-call pattern: `$InitializeCommonEvent(slot, eventID, arg0, arg1, ...);`
# We capture the whole args list as one string then split. Tolerant of
# whitespace/newlines inside the args.
_INIT_CALL_RE = re.compile(
    r'\$InitializeCommonEvent\s*\(\s*(\d+)\s*,\s*(\d+)\s*([^)]*)\)',
    re.DOTALL,
)

# Custom event definition pattern (for finding hardcoded anim refs etc.):
# `$Event(EVENT_ID, MODE, function(...) { BODY });`
_EVENT_DEF_RE = re.compile(
    r'\$Event\s*\(\s*(\d+)\s*,\s*\w+\s*,\s*function\s*\(',
    re.DOTALL,
)

# Hardcoded ForceAnimationPlayback call with a literal eid and anim ID:
# `ForceAnimationPlayback(48400800, 20005, false, false, false);`
_FORCEANIM_RE = re.compile(
    r'ForceAnimationPlayback\s*\(\s*(\d+)\s*,\s*(\d+)\s*,',
)


def _parse_args(args_text: str) -> list[int]:
    """Split the args of an InitializeCommonEvent call into integers.
    Non-integer args (e.g. Signed(0)) become None at that position so
    role-index lookups still align."""
    out: list[int | None] = []
    for raw in args_text.split(','):
        s = raw.strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except ValueError:
            # Could be Signed(0), expressions, etc. — record as None
            out.append(None)
    return out


def _looks_like_chr_eid(n: int | None) -> bool:
    """Heuristic: chr entity IDs in NR are 8-digit integers in the
    NN_NN_xxxx structure where the rightmost 4 digits (xxxx) follow the
    chr-eid pattern. We filter out:
      - eids ending in 22xx (regions / trigger volumes)
      - eids ending in 0200-0299 (area markers)
      - eids ending in 5899 (special spirit-anchor non-chr entities)
      - eids < 10_000_000 (not in NR map-eid range)
      - 0 (uninitialized)
    The remaining eids are chr Part candidates — actual MSB-inventory
    confirmation happens at consumer side via V3_BOSS_SLOT_CATALOG join.
    """
    if n is None or n == 0:
        return False
    if n < 10_000_000 or n > 999_999_999:
        return False
    mod10000 = n % 10000
    # Region/area marker patterns
    if 2200 <= mod10000 <= 2299:
        return False
    if 200 <= mod10000 <= 299:
        return False
    # Special non-chr anchors
    if mod10000 == 5899:
        return False
    # 8xxx pattern = chr (e.g. 800, 810, 820, 5800, 5810, 5820)
    # 5xxx pattern = secondary chr (e.g. 5210, 5220, 5800)
    # 0xxx pattern with 800+ = chr
    # 0xxx pattern with <200 = could be flag — but we keep these since
    # they may also be chr eids; consumer-side validation handles it.
    return True


def _msb_prefix_for_eid(eid: int) -> str | None:
    """Derive the MSB filename prefix from an eid: 48600800 → m48_60_00_00."""
    if not _looks_like_chr_eid(eid):
        return None
    # eid format: NN_NN_NN_NN (each 2-digit slot)
    s = f'{eid:09d}' if eid >= 100_000_000 else f'{eid:08d}'
    # Take first 8 digits as NN_NN_NN_NN; rightmost 3 digits are sub-eid
    if len(s) == 8:
        nn1, nn2, nn3, nn4 = s[0:2], s[2:4], s[4:6], s[6:8]
        # The last pair is usually entity-id-within-map (00-99 range);
        # the first 6 digits form the map prefix.
        # m48_60_00_00 = 48 60 00 00 → eid base 48_600_000
        return f'm{nn1}_{nn2}_00_00'
    return None


def parse_emevd(path: str) -> dict[str, Any]:
    """Parse a single .emevd.js file. Returns dict with:
      helpers_used (set of eventID strings),
      role_eids: dict[role -> set[int]],
      hardcoded_anims: dict[eid -> list[anim_ids]],
      n_init_calls, n_recognized_inits.
    """
    with open(path, encoding='utf-8') as f:
        txt = f.read()

    role_eids: dict[str, set[int]] = defaultdict(set)
    helpers_used: set[str] = set()
    n_init = 0
    n_recog = 0
    n_unmatched_signatures: dict[int, int] = defaultdict(int)

    for m in _INIT_CALL_RE.finditer(txt):
        n_init += 1
        slot, event_id_str, args_str = m.group(1), m.group(2), m.group(3)
        event_id = int(event_id_str)
        helpers_used.add(event_id_str)
        sig = EVENT_SIGNATURES.get(event_id)
        if sig is None:
            n_unmatched_signatures[event_id] += 1
            continue
        n_recog += 1
        args = _parse_args(args_str)
        for role, positions in sig.items():
            for pos in positions:
                if pos < len(args):
                    val = args[pos]
                    if _looks_like_chr_eid(val):
                        role_eids[role].add(val)

    # Find hardcoded ForceAnimationPlayback calls
    hardcoded_anims: dict[int, list[int]] = defaultdict(list)
    for m in _FORCEANIM_RE.finditer(txt):
        eid, anim = int(m.group(1)), int(m.group(2))
        if _looks_like_chr_eid(eid):
            hardcoded_anims[eid].append(anim)

    return {
        'helpers_used': sorted(helpers_used),
        'role_eids': {role: sorted(eids) for role, eids in role_eids.items()},
        'hardcoded_anims': {str(eid): anims for eid, anims in hardcoded_anims.items()},
        'n_init_calls': n_init,
        'n_recognized_inits': n_recog,
        'n_unmatched_per_event': dict(n_unmatched_signatures),
    }


def _classify_strategy(parsed: dict[str, Any]) -> tuple[str, int]:
    """Recommend a strategy + complexity score.
    Returns (strategy, score).

    v0.25.2 refinement: preserve_primary now requires actual evidence of
    multi-entity / multi-wave coordination, not just any hardcoded anim.
    Three false positives surfaced in playtest from the v0.25.1 heuristic:

      - m30_30 (Fort): 3 independent single-boss fort encounters
        (Crystalian, Glintstone Sorcerer, Guardian Golem) in one MSB.
        v0.25.1 over-classified as preserve_primary because of hardcoded
        anims [10, 11] on asset eids 30301200/30301201 — those are
        generic door/idle anims, not chr-init.
      - m38_10 (Cathedral): 2 cathedral encounters (Fire Monk, Mausoleum
        Knight), no multi-entity init helpers, no chr-init anims.
      - m46_80 (MMV Oldest Gaol): 2 named bosses (Ancient Dragon, Death
        Rite Bird), no multi-entity init helpers, no chr-init anims.

    All three should be swap_actual_chr, not preserve_primary. Refined
    criteria: hardcoded_anims must contain chr-init-tier anim IDs
    (>=20000, i.e. wakeup/intro/teleport range) AND be applied to chr-
    pattern eids (mod10000 in 800-899 / 5800-5899 / 0810-0899 range),
    not asset-pattern eids (mod10000 in 1200-1999 range).
    """
    role_eids = parsed['role_eids']
    actual = set(role_eids.get('actual_chr', []))
    hp_bar = set(role_eids.get('hp_bar_ref', []))
    companion = set(role_eids.get('companion', []))
    helpers = set(parsed['helpers_used'])
    hardcoded = parsed['hardcoded_anims']

    # v0.25.2: filter hardcoded_anims to those that are chr-init anims
    # on chr-pattern eids. Anim IDs:
    #   - 20005 / 20026: boss intro / wakeup (chr-init signal)
    #   - 30000+: cinematic camera anims (chr-init signal)
    #   - 10, 11, 12, 100: door/asset/generic anims (not chr-init)
    # Eid patterns: only count chr-eid-pattern eids (rightmost 4 digits
    # in chr range), not asset-pattern eids (1xxx mid-range).
    def _is_chr_init_anim_on_chr_eid(eid_str: str, anims: list[int]) -> bool:
        try: eid = int(eid_str)
        except ValueError: return False
        mod10000 = eid % 10000
        # Chr eid patterns: 800-899, 810-899, 5800-5899, 0810-0899
        if not (800 <= mod10000 <= 899 or 5800 <= mod10000 <= 5899 or
                810 <= mod10000 <= 819):
            return False
        # Chr-init anim threshold: 20000+ are wakeup/intro/teleport
        return any(a >= 20000 for a in anims)

    chr_init_hardcoded = {eid: anims for eid, anims in hardcoded.items()
                          if _is_chr_init_anim_on_chr_eid(eid, anims)}

    # Complexity heuristic: count distinct chr entities involved
    score = 0
    score += len(actual) * 2
    score += len(hp_bar) * 2
    score += len(companion) * 1
    score += len(chr_init_hardcoded) * 3   # v0.25.2: was len(hardcoded), now filtered
    # Multi-entity helper usage signals complexity
    if '90065050' in helpers: score += 5
    if '90065910' in helpers and (hp_bar - actual): score += 3
    if '90065911' in helpers: score += 2

    # Decision logic:
    if not (actual | hp_bar | companion):
        # No boss-init helpers recognized at all
        return ('none', 0)

    # v0.25.2: preserve_primary now requires HARD evidence:
    #   - 90065050 multi-entity boss-init OR
    #   - chr-init hardcoded anims (filtered) OR
    #   - many companions (>=4) under wave-sync coordination
    # Was previously: any hardcoded_anims OR many companions — too lenient.
    #
    # v0.26.16: added 90065130/131/132 — the Godskin-duo HP-bar helper
    # family. m48_80 (Godskin Duo NB) is a genuine two-entity simultaneous
    # fight (boss eids 48800800 + 48800810, two healthbars) but has no
    # hardcoded intro anim and isn't wave-based, so the v0.25.2 criteria
    # produced a false NEGATIVE: it classified swap_actual_chr, the Noble
    # half (48800800) got swapped to Apostle, and the duo intro handshake
    # hung — boss never started. The duo uses 90065130/131/132 rather than
    # the 90065050/040/041 family the classifier knew about. This helper
    # family is exclusive to m48_80, so the addition has zero blast radius
    # on other arenas.
    REAL_MULTI_ENTITY_HELPERS = {'90065050', '90065040', '90065041',
                                 '90065130', '90065131', '90065132'}
    has_real_me = bool(helpers & REAL_MULTI_ENTITY_HELPERS)
    if has_real_me or chr_init_hardcoded or len(companion) >= 4:
        return ('preserve_primary', score)

    # Has actual_chr distinct from hp_bar (split eid pattern) → swap
    if actual and (actual - hp_bar):
        return ('swap_actual_chr', score)

    # actual_chr == hp_bar_ref (single-entity arena)
    if actual and (actual & hp_bar):
        return ('swap_actual_chr', score)

    # Only hp_bar refs found, no actual_chr — could be simple. Conservative: preserve.
    # But v0.25.2: this is now LESS common since we tightened above.
    if hp_bar and not actual:
        return ('preserve_primary', score)

    return ('swap_normal', score)


def build_catalog(emevd_dir: str) -> dict[str, Any]:
    """Walk all MSB EMEVDs in emevd_dir and build the role catalog."""
    catalog: dict[str, Any] = {}
    counts = defaultdict(int)
    all_unmatched_events = defaultdict(int)

    for fname in sorted(os.listdir(emevd_dir)):
        if not fname.endswith('.emevd.js'): continue
        if fname.startswith('common'):  continue
        msb_key = fname.replace('.emevd.js', '.msb')

        parsed = parse_emevd(os.path.join(emevd_dir, fname))
        strategy, score = _classify_strategy(parsed)
        counts[strategy] += 1
        for eid, n in parsed.get('n_unmatched_per_event', {}).items():
            all_unmatched_events[eid] += n

        catalog[msb_key] = {
            'actual_chr_eids':   parsed['role_eids'].get('actual_chr', []),
            'hp_bar_ref_eids':   parsed['role_eids'].get('hp_bar_ref', []),
            'companion_eids':    parsed['role_eids'].get('companion', []),
            'helpers_used':      parsed['helpers_used'],
            'hardcoded_anims':   parsed['hardcoded_anims'],
            'n_init_calls':      parsed['n_init_calls'],
            'n_recognized':      parsed['n_recognized_inits'],
            'is_multi_entity':   len(parsed['role_eids'].get('hp_bar_ref', [])) > 1 or
                                 len(parsed['role_eids'].get('companion', [])) > 0,
            'is_multi_wave':     bool(parsed['hardcoded_anims']) or
                                 '90065050' in parsed['helpers_used'],
            'complexity_score':  score,
            'recommended_strategy': strategy,
        }

    meta = {
        'generator':           'v0.25.1 build_arena_chr_roles.py',
        'source_emevd_dir':    emevd_dir,
        'total_msbs':          len(catalog),
        'strategy_counts':     dict(counts),
        'top_unmatched_events':
            sorted(all_unmatched_events.items(), key=lambda kv: -kv[1])[:10],
        'schema_version': 1,
    }
    return {'_meta': meta, **catalog}


def main():
    p = argparse.ArgumentParser(description='Build per-arena chr-role catalog from vanilla EMEVDs.')
    p.add_argument('emevd_dir', help='Directory containing decompiled .emevd.js files')
    p.add_argument('out_path', help='Output JSON path (e.g. data/nr_boss_arena_chr_roles.json)')
    p.add_argument('--summary', action='store_true', help='Print human-readable summary instead of writing JSON')
    args = p.parse_args()

    if not os.path.isdir(args.emevd_dir):
        print(f'ERROR: emevd_dir not found: {args.emevd_dir}', file=sys.stderr)
        sys.exit(1)

    catalog = build_catalog(args.emevd_dir)
    meta = catalog['_meta']

    if args.summary:
        print(f"Parsed {meta['total_msbs']} MSB EMEVDs")
        print(f"Strategy distribution:")
        for strat, n in sorted(meta['strategy_counts'].items(), key=lambda kv: -kv[1]):
            print(f"  {strat:24s} {n:4d}")
        print(f"Top unmatched event IDs (most-frequent skipped helpers):")
        for eid, n in meta['top_unmatched_events']:
            print(f"  {eid}: skipped {n}x")
        return

    os.makedirs(os.path.dirname(args.out_path) or '.', exist_ok=True)
    with open(args.out_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2, sort_keys=False)
    print(f"Wrote {args.out_path}")
    print(f"Total MSBs: {meta['total_msbs']}")
    print(f"Strategy distribution: {meta['strategy_counts']}")


if __name__ == '__main__':
    main()