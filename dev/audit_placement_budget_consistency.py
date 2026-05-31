#!/usr/bin/env python3
"""audit_placement_budget_consistency.py — surface dead-code and divergent
entries across the V3_* placement-budget constants in `oops_v3.py`.

Motivation
----------

The placement-budget surface (V3_UNIQUE_TARGET_CAPS, V3_EXCLUDE_TARGET_PREFIXES,
V3_GHOST_EXCLUDE_TARGET_PREFIXES, V3_TAG_OVERRIDES, ...) accumulated across the
v0.23–v0.25 series. The TODO entry "Factor out caps + pools as first-class
data" calls out three issues that this audit makes visible TODAY without
waiting for the bigger refactor:

  1. **Dead-code caps.** A cap entry can be fully shadowed by an exclude
     (e.g. c7800 Duke's Dear Freja is in BOTH V3_UNIQUE_TARGET_CAPS cap=2
     AND V3_EXCLUDE_TARGET_PREFIXES — the exclude wins, so the cap never
     fires). The TODO surfaced this as a v0.25.3 sim finding; this audit
     finds the same class systematically.

  2. **Caps on tier-filtered chrs.** Caps apply within boss-tier swap
     pools. A cap on a chr whose POST-LOAD tier is `trash` (or sometimes
     `grunt`) is suspect — the chr can't reach the gated pool to be
     constrained. May still be intentional (safety net for future
     retier), but worth flagging.

  3. **Sibling-variant cap inconsistencies.** Same-archetype variants
     (e.g. Erdtree Avatar c4810 cap=2 vs Erdtree Avatar Variant c4811
     cap=1) where the divergence isn't obviously motivated. The first
     example in this category was Giant Crow (c4560/c4561).

The audit runs against `oops_v3.load_data()` output so it sees the
POST-OVERRIDE tier state (V3_TAG_OVERRIDES is applied during load —
c4601 Troll Knight's auto-tagged 'grunt' becomes 'miniboss' there, which
this audit correctly reads, unlike a raw-JSON scan).

Output
------

Findings are grouped by severity:

  HIGH    — true dead code (cap shadowed by exclude)
  MEDIUM  — likely dead (cap on trash/grunt tier with no override) or
            orphan caps (chr has no tag entry at all)
  LOW     — same-tier sibling divergences (review-worthy; often intentional)

Exit code is 1 if any HIGH severity findings are present, else 0.
Use `--all-as-errors` to also fail on MEDIUM.

A `--ignore-file path.json` can be supplied to suppress known-intentional
findings. The file format is `[{"category": "...", "c_prefix": "...",
"rationale": "..."}, ...]`. Matching is exact on (category, c_prefix).

Usage
-----

  python3 dev/audit_placement_budget_consistency.py             # text report
  python3 dev/audit_placement_budget_consistency.py --json out.json
  python3 dev/audit_placement_budget_consistency.py --ignore-file dev/budget_audit_ignores.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from typing import Iterable


# -----------------------------------------------------------------------------
# Severity constants
# -----------------------------------------------------------------------------

SEV_HIGH = 'HIGH'
SEV_MEDIUM = 'MEDIUM'
SEV_LOW = 'LOW'

SEVERITY_ORDER = {SEV_HIGH: 0, SEV_MEDIUM: 1, SEV_LOW: 2}


# -----------------------------------------------------------------------------
# Built-in allowlist: documented-intentional divergences
# -----------------------------------------------------------------------------
#
# These pairings have explicit in-source rationale comments. Listed here so
# the audit doesn't surface them every run. Adding a new entry requires a
# comment explaining why the divergence is intentional.

BUILTIN_ALLOWLIST: list[dict] = [
    # c450 family — c4505 Flying Dragon (Small) intentionally cap=2 vs other
    # dragons cap=1. See oops_v3.py line ~9178: "Smaller dragon variant —
    # vanilla uses in catacombs, less iconic than the full-size dragons,
    # so cap=2 lets it appear in two places."
    {'category': 'sibling_same_tier_cap_divergence', 'c_prefix': 'c4505',
     'rationale': 'documented_smaller_variant_more_frequent'},
    # c435 family — c4353 Leyndell Knight cap=6 retained as safety-net after
    # v0.25.3 retier from night_boss → miniboss. See V3_TAG_OVERRIDES comment
    # at oops_v3.py line ~9445.
    {'category': 'sibling_same_tier_cap_divergence', 'c_prefix': 'c4353',
     'rationale': 'documented_safety_net_after_retier'},
    # c4060/c5890 — mount-component chrs (Kaiden's Horse, Black Knight Horse).
    # Excluded as standalone targets, but cap=30 is set dynamically in
    # load_data() (oops_v3.py ~L3945) so their mount-ROLE slots can fill —
    # the cap is live for the role-fill path, not dead code.
    {'category': 'cap_shadowed_by_exclude', 'c_prefix': 'c4060',
     'rationale': 'mount_role_cap_for_role_fill_path'},
    {'category': 'cap_shadowed_by_exclude', 'c_prefix': 'c5890',
     'rationale': 'mount_role_cap_for_role_fill_path'},
    # c8300 Dragonslayer Armor (DS3 MMV) — EXCLUDED (re-excluded for freeze),
    # but it is a marquee NB / NB-caliber MMV import, so the reservation-floor
    # policy requires floor=1, and floor⊆ceiling requires a matching cap.
    # The cap is dead for placement while excluded, but the entry is kept
    # consistent (dormant) so the NB reservation invariants hold and it resumes
    # cleanly if ever un-excluded. Not orphan cruft (cf. c4140, which had no
    # floor/nb-caliber role and was removed).
    {'category': 'cap_shadowed_by_exclude', 'c_prefix': 'c8300',
     'rationale': 'excluded_nb_caliber_mmv_cap_floor_kept_consistent'},
]


@dataclass
class Finding:
    category: str
    severity: str
    c_prefix: str
    name: str
    message: str
    suggestion: str = ''

    def key(self) -> tuple:
        return (self.category, self.c_prefix)


# -----------------------------------------------------------------------------
# Detectors (pure functions, unit-testable)
# -----------------------------------------------------------------------------

def detect_shadowed_caps(caps: dict, excludes: Iterable[str],
                          tags: dict, *, category: str,
                          source_label: str) -> list[Finding]:
    """Caps on chrs that are also in an exclude set. The exclude wins,
    so the cap entry is dead code."""
    findings = []
    for cp in sorted(set(caps) & set(excludes)):
        nm = tags.get(cp, {}).get('name', '?')
        findings.append(Finding(
            category=category,
            severity=SEV_HIGH,
            c_prefix=cp,
            name=nm,
            message=(f'cap={caps[cp]} in V3_UNIQUE_TARGET_CAPS but '
                     f'{cp} is also in {source_label} — exclude wins, '
                     f'cap is dead code'),
            suggestion=(f'Remove {cp} from V3_UNIQUE_TARGET_CAPS, or '
                        f'lift it from {source_label} if the chr is '
                        f'actually playable now'),
        ))
    return findings


def detect_trash_tier_caps(caps: dict, tags: dict) -> list[Finding]:
    """Caps on chrs whose POST-LOAD tier is `trash`. Caps gate within
    boss-tier swap pools — a trash-tier cap can never fire."""
    findings = []
    for cp in sorted(caps):
        tag = tags.get(cp)
        if tag is None:
            continue
        tier = tag.get('tier')
        if tier == 'trash':
            findings.append(Finding(
                category='cap_on_trash_tier_likely_dead',
                severity=SEV_MEDIUM,
                c_prefix=cp,
                name=tag.get('name', '?'),
                message=(f'cap={caps[cp]} but post-load tier={tier!r} '
                         f'— trash-tier chrs don\'t enter boss-tier '
                         f'pools where caps are evaluated'),
                suggestion=('Remove the cap, OR retier via '
                            'V3_TAG_OVERRIDES if the cap is intended '
                            'to engage'),
            ))
    return findings


def detect_grunt_tier_caps(caps: dict, tags: dict,
                            overrides: dict) -> list[Finding]:
    """Caps on chrs whose POST-LOAD tier is `grunt`. Similar to trash
    but somewhat softer — some pipelines do treat grunts as eligible.
    Skip entries that have a tier override (those are intentionally-
    bumped grunt-tagged chrs that became boss-tier post-override)."""
    findings = []
    for cp in sorted(caps):
        tag = tags.get(cp)
        if tag is None:
            continue
        tier = tag.get('tier')
        if tier != 'grunt':
            continue
        # If V3_TAG_OVERRIDES already bumped this chr (e.g. c4601 grunt
        # → miniboss), the post-load tier will already be the new value,
        # so we'd never see 'grunt' here. The override-check below is
        # belt-and-suspenders for any future override that doesn't
        # change tier.
        if cp in overrides and 'tier' in overrides[cp]:
            continue
        findings.append(Finding(
            category='cap_on_grunt_tier_suspect',
            severity=SEV_MEDIUM,
            c_prefix=cp,
            name=tag.get('name', '?'),
            message=(f'cap={caps[cp]} but post-load tier={tier!r} '
                     f'— grunt-tier caps usually only engage if '
                     f'something promotes them into the boss-tier pool'),
            suggestion=('Confirm the cap engages, OR remove it, OR '
                        'add a V3_TAG_OVERRIDES retier'),
        ))
    return findings


def detect_orphan_caps(caps: dict, tags: dict) -> list[Finding]:
    """Caps on chrs with no tag entry at all (after load_data — so all
    pack-loaders have run). These are caps with no chr behind them."""
    findings = []
    for cp in sorted(caps):
        if cp not in tags:
            findings.append(Finding(
                category='cap_on_untagged_chr',
                severity=SEV_MEDIUM,
                c_prefix=cp,
                name='(no tag entry)',
                message=(f'cap={caps[cp]} but {cp} has no entry in '
                         f'post-load tags — no chr to constrain'),
                suggestion=('Remove the cap, OR add a tags entry if '
                            'the chr should exist'),
            ))
    return findings


def _same_length_c_prefix_family(cp: str) -> str | None:
    """Family key for sibling grouping. Returns the first 4 chars of a
    5-char c-prefix (c + 4 digits), or None for non-conforming inputs.
    This filter intentionally skips 6-char cinematic ids like c50001
    that would otherwise pollute c500 with object/system entries."""
    if (len(cp) == 5 and cp.startswith('c') and cp[1:].isdigit()):
        return cp[:4]
    return None


def detect_sibling_same_tier_divergence(caps: dict,
                                         excludes: Iterable[str],
                                         tags: dict) -> list[Finding]:
    """Same-family (cXXX, 4-digit) sibling chrs at the SAME post-load
    tier with divergent cap policies. Cross-tier siblings are common
    and almost always intentional (named singular variant promoted up,
    base form stays uncapped), so we filter those out."""
    excl_set = set(excludes)
    families: dict[str, list[str]] = defaultdict(list)
    universe = set(caps) | excl_set | set(tags.keys())
    for cp in universe:
        fam = _same_length_c_prefix_family(cp)
        if fam:
            families[fam].append(cp)

    findings = []
    for fam in sorted(families):
        members = sorted(families[fam])
        if len(members) < 2:
            continue
        # Group members by tier
        by_tier: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for cp in members:
            tier = tags.get(cp, {}).get('tier', '?')
            if cp in excl_set:
                pol = 'EXCLUDE'
            elif cp in caps:
                pol = f'cap={caps[cp]}'
            else:
                pol = 'uncapped'
            by_tier[tier].append((cp, pol))
        for tier, items in by_tier.items():
            if tier == '?':
                continue  # don't flag untagged-pair noise here
            if tier == 'cinematic':
                continue  # cinematic chrs aren't placement candidates
            pols = {p for _, p in items}
            if len(pols) <= 1:
                continue
            # Family is interesting if it has any cap AND any divergence.
            # The earlier `if len(pols) <= 1: continue` ensures divergence;
            # requiring cap_vals filters out pure exclude-vs-uncapped
            # families (the broken-variant pattern), which are common
            # and almost always independent of sibling state.
            cap_vals = {p for p in pols if p.startswith('cap=')}
            if not cap_vals:
                continue
            # Emit findings only for OUTLIERS — members whose policy
            # differs from the family majority. If there's a clear
            # majority policy (>50% of members share it), divergent
            # members are the outliers. If no policy holds a majority
            # (e.g. 2-member family with one cap=2 and one cap=1),
            # all are flagged as ambiguous.
            pol_counts = Counter(pol for _, pol in items)
            total = len(items)
            majority_pol = None
            for pol, n in pol_counts.most_common():
                if n * 2 > total:  # strict majority
                    majority_pol = pol
                    break
            divergent = [(cp, pol) for cp, pol in items
                         if pol != majority_pol or majority_pol is None]
            # If we have a majority, only flag chrs that DEVIATE from it.
            # If we don't, flag all members (caller can allowlist a
            # canonical one).
            if majority_pol is not None:
                divergent = [(cp, pol) for cp, pol in items
                             if pol != majority_pol]
            else:
                divergent = list(items)
            for cp, pol in divergent:
                others = ', '.join(f'{c2}={p2}' for c2, p2 in items
                                    if c2 != cp)
                nm = tags.get(cp, {}).get('name', '?')
                majority_note = (
                    f'majority={majority_pol}; '
                    if majority_pol else 'no majority; ')
                findings.append(Finding(
                    category='sibling_same_tier_cap_divergence',
                    severity=SEV_LOW,
                    c_prefix=cp,
                    name=nm,
                    message=(f'family {fam} tier={tier}: {cp} {pol} '
                             f'({majority_note}siblings: {others})'),
                    suggestion=('If divergence is intentional, add an '
                                'allowlist entry with rationale; '
                                'otherwise align caps'),
                ))
    return findings


# -----------------------------------------------------------------------------
# Audit runner
# -----------------------------------------------------------------------------

def run_audit(*, caps: dict, excl_target: Iterable[str],
              ghost_excl: Iterable[str], tags: dict,
              overrides: dict | None = None,
              allowlist: Iterable[dict] | None = None) -> list[Finding]:
    """Run all detectors and return the merged finding list, minus any
    allowlisted entries. Pure function — no I/O, no module reads."""
    overrides = overrides or {}
    findings: list[Finding] = []
    findings += detect_shadowed_caps(
        caps, excl_target, tags,
        category='cap_shadowed_by_exclude',
        source_label='V3_EXCLUDE_TARGET_PREFIXES')
    findings += detect_shadowed_caps(
        caps, ghost_excl, tags,
        category='cap_shadowed_by_ghost_exclude',
        source_label='V3_GHOST_EXCLUDE_TARGET_PREFIXES')
    findings += detect_trash_tier_caps(caps, tags)
    findings += detect_grunt_tier_caps(caps, tags, overrides)
    findings += detect_orphan_caps(caps, tags)
    findings += detect_sibling_same_tier_divergence(caps, excl_target, tags)

    # Apply allowlist
    skip = set()
    for entry in (allowlist or []):
        skip.add((entry['category'], entry['c_prefix']))
    findings = [f for f in findings if f.key() not in skip]

    # Sort: severity → category → c_prefix
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity],
                                  f.category, f.c_prefix))
    return findings


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _load_engine_constants() -> tuple:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    sys.path.insert(0, root)
    import oops_v3  # noqa: E402
    roster, tags = oops_v3.load_data()
    # v0.26.x: V3_TAG_OVERRIDES removed (flattened into nr_enemy_tags.json
    # and mmv_imports.json). Return empty dict for backward-compat with
    # downstream consumers that still expect this position. Tier
    # overrides should be sourced from the JSON manifests directly now.
    return (
        dict(oops_v3.V3_UNIQUE_TARGET_CAPS),
        set(oops_v3.V3_EXCLUDE_TARGET_PREFIXES),
        set(oops_v3.V3_GHOST_EXCLUDE_TARGET_PREFIXES),
        tags,
        {},
    )


def _format_text_report(findings: list[Finding]) -> str:
    if not findings:
        return 'PASS: no placement-budget consistency issues found.'
    by_sev: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_sev[f.severity].append(f)
    out = []
    out.append(f'Placement-budget audit: {len(findings)} finding(s).')
    out.append('')
    for sev in (SEV_HIGH, SEV_MEDIUM, SEV_LOW):
        items = by_sev.get(sev, [])
        if not items:
            continue
        out.append(f'--- {sev} ({len(items)}) ---')
        for f in items:
            out.append(f'  [{f.category}] {f.c_prefix} — {f.name}')
            out.append(f'    {f.message}')
            if f.suggestion:
                out.append(f'    → {f.suggestion}')
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', metavar='PATH',
                     help='Write findings as JSON to PATH (in addition '
                          'to stdout text)')
    ap.add_argument('--ignore-file', metavar='PATH',
                     help='Path to a JSON allowlist of intentional '
                          'findings to suppress')
    ap.add_argument('--no-builtin-allowlist', action='store_true',
                     help='Disable the BUILTIN_ALLOWLIST (e.g. for '
                          'audit-the-audit purposes)')
    ap.add_argument('--all-as-errors', action='store_true',
                     help='Exit non-zero on MEDIUM findings too '
                          '(default: only HIGH)')
    args = ap.parse_args(argv)

    caps, excl_target, ghost_excl, tags, overrides = _load_engine_constants()

    allow = []
    if not args.no_builtin_allowlist:
        allow.extend(BUILTIN_ALLOWLIST)
    if args.ignore_file:
        with open(args.ignore_file, encoding='utf-8') as f:
            allow.extend(json.load(f))

    findings = run_audit(caps=caps, excl_target=excl_target,
                          ghost_excl=ghost_excl, tags=tags,
                          overrides=overrides, allowlist=allow)

    print(_format_text_report(findings))

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump([asdict(x) for x in findings], f,
                      indent=2, sort_keys=True)
        print(f'JSON report → {args.json}')

    threshold = SEVERITY_ORDER[SEV_MEDIUM] if args.all_as_errors \
        else SEVERITY_ORDER[SEV_HIGH]
    fail = any(SEVERITY_ORDER[f.severity] <= threshold for f in findings)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
