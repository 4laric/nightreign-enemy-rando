"""Tests for dev/audit_placement_budget_consistency.py.

Hits the pure-function detectors with synthetic inputs so we can exercise
each finding category in isolation. The CLI's `_load_engine_constants`
path is covered separately by the engine fixture in conftest.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'dev'))

from audit_placement_budget_consistency import (  # noqa: E402
    BUILTIN_ALLOWLIST,
    SEV_HIGH,
    SEV_LOW,
    SEV_MEDIUM,
    detect_grunt_tier_caps,
    detect_orphan_caps,
    detect_shadowed_caps,
    detect_sibling_same_tier_divergence,
    detect_trash_tier_caps,
    run_audit,
)


# Synthetic tag fixtures. Keep these minimal — only the fields the
# detectors read.

def _tag(name, tier, **extra):
    return {'name': name, 'tier': tier, **extra}


# -----------------------------------------------------------------------------
# detect_shadowed_caps
# -----------------------------------------------------------------------------

class TestDetectShadowedCaps:
    def test_cap_and_exclude_is_dead(self):
        """The c7800 Freja case: capped AND excluded → HIGH finding."""
        caps = {'c7800': 2}
        excludes = {'c7800'}
        tags = {'c7800': _tag('Duke\'s Dear Freja', 'night_boss')}
        out = detect_shadowed_caps(caps, excludes, tags,
                                    category='cap_shadowed_by_exclude',
                                    source_label='V3_EXCLUDE_TARGET_PREFIXES')
        assert len(out) == 1
        assert out[0].c_prefix == 'c7800'
        assert out[0].severity == SEV_HIGH
        assert 'cap is dead code' in out[0].message

    def test_cap_without_exclude_is_clean(self):
        caps = {'c7700': 2}
        excludes = set()
        tags = {'c7700': _tag('Gaping Dragon', 'night_boss')}
        out = detect_shadowed_caps(caps, excludes, tags,
                                    category='x', source_label='Y')
        assert out == []

    def test_exclude_without_cap_is_clean(self):
        caps = {}
        excludes = {'c4504'}
        tags = {'c4504': _tag('Elder Dragon Greyoll', 'night_boss')}
        out = detect_shadowed_caps(caps, excludes, tags,
                                    category='x', source_label='Y')
        assert out == []


# -----------------------------------------------------------------------------
# detect_trash_tier_caps
# -----------------------------------------------------------------------------

class TestDetectTrashTierCaps:
    def test_trash_tier_cap_is_flagged(self):
        caps = {'c4170': 2}
        tags = {'c4170': _tag('Putrid Flesh', 'trash')}
        out = detect_trash_tier_caps(caps, tags)
        assert len(out) == 1
        assert out[0].severity == SEV_MEDIUM
        assert out[0].c_prefix == 'c4170'

    def test_boss_tier_cap_is_clean(self):
        caps = {'c4500': 1}
        tags = {'c4500': _tag('Flying Dragon', 'field_boss')}
        out = detect_trash_tier_caps(caps, tags)
        assert out == []

    def test_untagged_chr_not_in_trash_check(self):
        """Orphan caps fall under detect_orphan_caps, not here."""
        caps = {'c9999': 1}
        tags = {}
        out = detect_trash_tier_caps(caps, tags)
        assert out == []


# -----------------------------------------------------------------------------
# detect_grunt_tier_caps
# -----------------------------------------------------------------------------

class TestDetectGruntTierCaps:
    def test_grunt_cap_no_override_flagged(self):
        caps = {'c4240': 2}
        tags = {'c4240': _tag('Fingercreeper', 'grunt')}
        out = detect_grunt_tier_caps(caps, tags, overrides={})
        assert len(out) == 1
        assert out[0].c_prefix == 'c4240'

    def test_grunt_cap_with_explicit_override_not_flagged(self):
        """If V3_TAG_OVERRIDES has a tier patch, the cap is intentional
        even if base data says grunt (the override should bump tier at
        load, but this protects against any future override that
        doesn't promote tier yet keeps the cap intentional)."""
        caps = {'c4601': 6}
        # Note: post-load tier reflects the override here ('miniboss'),
        # so we wouldn't normally hit this branch — but if we did,
        # presence of the override should suppress.
        tags = {'c4601': _tag('Troll Knight', 'grunt')}
        overrides = {'c4601': {'tier': 'miniboss'}}
        out = detect_grunt_tier_caps(caps, tags, overrides=overrides)
        assert out == []


# -----------------------------------------------------------------------------
# detect_orphan_caps
# -----------------------------------------------------------------------------

class TestDetectOrphanCaps:
    def test_cap_with_no_tag_is_orphan(self):
        caps = {'c9999': 1}
        tags = {}
        out = detect_orphan_caps(caps, tags)
        assert len(out) == 1
        assert out[0].c_prefix == 'c9999'
        assert out[0].severity == SEV_MEDIUM

    def test_cap_with_tag_is_clean(self):
        caps = {'c4500': 1}
        tags = {'c4500': _tag('Flying Dragon', 'field_boss')}
        out = detect_orphan_caps(caps, tags)
        assert out == []


# -----------------------------------------------------------------------------
# detect_sibling_same_tier_divergence
# -----------------------------------------------------------------------------

class TestDetectSiblingDivergence:
    def test_same_tier_same_cap_is_clean(self):
        caps = {'c4500': 1, 'c4501': 1, 'c4502': 1}
        tags = {cp: _tag('Dragon', 'field_boss') for cp in caps}
        out = detect_sibling_same_tier_divergence(caps, set(), tags)
        assert out == []

    def test_majority_cap_flags_only_the_outlier(self):
        """Dragons c4500/c4501/c4502/c4503 all cap=1, c4505 cap=2.
        Only c4505 should be flagged — not the four majority members."""
        caps = {'c4500': 1, 'c4501': 1, 'c4502': 1, 'c4503': 1, 'c4505': 2}
        tags = {cp: _tag(f'Dragon {cp}', 'field_boss') for cp in caps}
        out = detect_sibling_same_tier_divergence(caps, set(), tags)
        cps = [f.c_prefix for f in out]
        assert cps == ['c4505']

    def test_no_majority_flags_both_members(self):
        """c4810 cap=2, c4811 cap=1, both field_boss — no majority,
        both should be surfaced for review."""
        caps = {'c4810': 2, 'c4811': 1}
        tags = {cp: _tag(f'Erdtree {cp}', 'field_boss') for cp in caps}
        out = detect_sibling_same_tier_divergence(caps, set(), tags)
        cps = sorted(f.c_prefix for f in out)
        assert cps == ['c4810', 'c4811']

    def test_cross_tier_siblings_not_flagged(self):
        """Siblings at different tiers shouldn't show up — different
        tiers usually mean different cap rationale (e.g. named-singular
        upgraded variant vs base form)."""
        caps = {'c5010': 2, 'c5011': 3}
        tags = {
            'c5010': _tag('Golden Hippo', 'field_boss'),
            'c5011': _tag('Golden Hippo (Wings)', 'night_boss'),
        }
        out = detect_sibling_same_tier_divergence(caps, set(), tags)
        assert out == []

    def test_six_digit_cinematic_ids_ignored(self):
        """c50001/c50002 are 6-char cinematic objects and shouldn't
        be lumped into family c5000."""
        caps = {'c5000': 2}
        tags = {
            'c5000': _tag('Commander Gaius', 'field_boss'),
            'c50001': _tag('Roundtable Object', 'cinematic'),
            'c50002': _tag('System', 'cinematic'),
        }
        out = detect_sibling_same_tier_divergence(caps, set(), tags)
        assert out == []

    def test_excluded_sibling_counted_in_majority(self):
        """An EXCLUDE in the family is one of the policies; if it's
        majority, capped siblings should be flagged. If exclude is
        minority and caps are aligned, no flag."""
        caps = {'c4500': 1, 'c4501': 1, 'c4502': 1, 'c4503': 1, 'c4505': 1}
        excludes = {'c4504'}
        tags = {
            'c4500': _tag('a', 'field_boss'),
            'c4501': _tag('b', 'field_boss'),
            'c4502': _tag('c', 'field_boss'),
            'c4503': _tag('d', 'field_boss'),
            'c4504': _tag('Greyoll', 'field_boss'),
            'c4505': _tag('e', 'field_boss'),
        }
        out = detect_sibling_same_tier_divergence(caps, excludes, tags)
        # Majority is cap=1 (5 members), exclude (c4504) is the outlier.
        # Excludes ARE flagged because the policy diverges.
        cps = [f.c_prefix for f in out]
        assert cps == ['c4504']


# -----------------------------------------------------------------------------
# run_audit (integration over all detectors)
# -----------------------------------------------------------------------------

class TestRunAudit:
    def test_empty_inputs_returns_no_findings(self):
        out = run_audit(caps={}, excl_target=set(), ghost_excl=set(),
                         tags={}, overrides={}, allowlist=[])
        assert out == []

    def test_findings_sorted_by_severity(self):
        caps = {'c7800': 2, 'c4170': 2, 'c4810': 2, 'c4811': 1}
        excl = {'c7800'}
        tags = {
            'c7800': _tag('Freja', 'night_boss'),
            'c4170': _tag('Putrid Flesh', 'trash'),
            'c4810': _tag('Erdtree Avatar', 'field_boss'),
            'c4811': _tag('Erdtree Avatar Variant', 'field_boss'),
        }
        out = run_audit(caps=caps, excl_target=excl, ghost_excl=set(),
                         tags=tags, overrides={}, allowlist=[])
        severities = [f.severity for f in out]
        # HIGH first, then MEDIUM, then LOW
        assert severities == sorted(severities,
                                     key={SEV_HIGH: 0, SEV_MEDIUM: 1,
                                          SEV_LOW: 2}.__getitem__)
        # All three categories present
        cats = {f.category for f in out}
        assert 'cap_shadowed_by_exclude' in cats
        assert 'cap_on_trash_tier_likely_dead' in cats
        assert 'sibling_same_tier_cap_divergence' in cats

    def test_allowlist_suppresses_matching_findings(self):
        caps = {'c4170': 2}
        tags = {'c4170': _tag('Putrid Flesh', 'trash')}
        allow = [{'category': 'cap_on_trash_tier_likely_dead',
                  'c_prefix': 'c4170',
                  'rationale': 'safety_net'}]
        out = run_audit(caps=caps, excl_target=set(), ghost_excl=set(),
                         tags=tags, overrides={}, allowlist=allow)
        assert out == []

    def test_allowlist_misses_when_category_differs(self):
        caps = {'c7800': 2}
        excl = {'c7800'}
        tags = {'c7800': _tag('Freja', 'night_boss')}
        # Wrong category in allowlist — should NOT suppress.
        allow = [{'category': 'cap_on_trash_tier_likely_dead',
                  'c_prefix': 'c7800'}]
        out = run_audit(caps=caps, excl_target=excl, ghost_excl=set(),
                         tags=tags, overrides={}, allowlist=allow)
        assert len(out) == 1
        assert out[0].category == 'cap_shadowed_by_exclude'


# -----------------------------------------------------------------------------
# Live engine snapshot — guards against regressions in the real data
# -----------------------------------------------------------------------------

class TestLiveEngineSnapshot:
    """Run the audit against the actual loaded engine state. These
    aren't strict (the engine is allowed to evolve), but we snapshot
    what the audit currently surfaces so any unexpected new findings
    show up in test diffs."""

    def test_audit_runs_against_live_engine(self, engine):
        from audit_placement_budget_consistency import (
            run_audit, BUILTIN_ALLOWLIST)
        roster, tags = engine.load_data()
        findings = run_audit(
            caps=dict(engine.V3_UNIQUE_TARGET_CAPS),
            excl_target=set(engine.V3_EXCLUDE_TARGET_PREFIXES),
            ghost_excl=set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES),
            tags=tags,
            # v0.26.x: V3_TAG_OVERRIDES removed (flattened)
            overrides={},
            allowlist=BUILTIN_ALLOWLIST,
        )
        # Audit must complete and return Findings of the right shape
        assert isinstance(findings, list)
        for f in findings:
            assert f.severity in (SEV_HIGH, SEV_MEDIUM, SEV_LOW)
            assert f.c_prefix.startswith('c')
            assert f.message  # non-empty

    def test_known_high_severity_findings_at_v0_26_0(self, engine):
        """v0.26.0 snapshot: after the dead-cap cleanup, no HIGH findings
        should remain. The three pre-cleanup entries (c3610, c4361, c7800)
        were resolved by:
          - c7800: dropped from V3_UNIQUE_TARGET_CAPS literal (no chrbnd
                   on disk; `_load_missing_chr_files()` excludes it)
          - c3610: removed from _LIFTED_V0_24_65 frozenset (re-excluded
                   for cluster-only freeze; lift was superseded)
          - c4361: removed from _LIFTED_V0_24_65 frozenset (re-excluded
                   in v0.25.0-patch1 for mount-component CTD)

        If a HIGH finding reappears, it likely means a cap was added for
        a c-prefix that's also in V3_EXCLUDE_TARGET_PREFIXES (the dead-
        cap class). Investigate the underlying conflict — don't just
        append to expected_high without rationale.
        """
        from audit_placement_budget_consistency import (
            run_audit, BUILTIN_ALLOWLIST, SEV_HIGH)
        roster, tags = engine.load_data()
        findings = run_audit(
            caps=dict(engine.V3_UNIQUE_TARGET_CAPS),
            excl_target=set(engine.V3_EXCLUDE_TARGET_PREFIXES),
            ghost_excl=set(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES),
            tags=tags,
            # v0.26.x: V3_TAG_OVERRIDES removed (flattened)
            overrides={},
            allowlist=BUILTIN_ALLOWLIST,
        )
        high_cps = sorted(f.c_prefix for f in findings
                          if f.severity == SEV_HIGH)
        expected_high: list[str] = []
        assert high_cps == expected_high, (
            f'HIGH-severity findings changed:\n'
            f'  was: {expected_high}\n'
            f'  now: {high_cps}\n'
            f'Either fix the underlying issue or update the snapshot.')
