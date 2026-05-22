"""Unit tests for is_boss_tier_prefix's decision tree.

The function has five independent positive paths (any of which can flip
the result to True) plus a final False fallthrough:

  1. tag.has_boss_reward = True
  2. tag.has_reward = True
  3. tag.hit_height_median >= 4.0
  4. cp in V3_HERITAGE_ALL_PREFIXES AND tag.hp_median >= 300
  5. Any variant in prefix_variants[cp] carries a V3_BOSS_NAME_MARKERS name

These tests isolate each leg with synthetic data — a tag dict that
satisfies exactly one criterion, and prefix_variants either empty or
crafted to either match or not match. Plus a few live-fixture spot
checks that confirm real cps land where we expect.
"""
import pytest

import oops_v3


# ---------------------------------------------------------------------------
# Individual decision legs
# ---------------------------------------------------------------------------

class TestIsBossTierPrefixLegs:
    """Each test isolates one leg of the boss-tier OR chain."""

    def test_has_boss_reward_alone_qualifies(self):
        tags = {'cTEST': {'has_boss_reward': True}}
        assert oops_v3.is_boss_tier_prefix('cTEST', tags, {})

    def test_has_reward_alone_qualifies(self):
        tags = {'cTEST': {'has_reward': True}}
        assert oops_v3.is_boss_tier_prefix('cTEST', tags, {})

    def test_hit_height_median_4m_alone_qualifies(self):
        tags = {'cTEST': {'hit_height_median': 4.0}}
        assert oops_v3.is_boss_tier_prefix('cTEST', tags, {})

    def test_hit_height_median_just_under_4m_does_not_qualify(self):
        # Boundary check: < 4.0 doesn't qualify, but other legs are clear.
        tags = {'cTEST': {'hit_height_median': 3.99}}
        assert not oops_v3.is_boss_tier_prefix('cTEST', tags, {})

    def test_boss_marker_variant_alone_qualifies(self):
        # No tag-driven leg satisfied; only a variant name fires.
        tags = {'cTEST': {}}
        pv = {'cTEST': [{'variant_name': 'Test (Field Boss)'}]}
        assert oops_v3.is_boss_tier_prefix('cTEST', tags, pv)

    def test_non_boss_variant_alone_does_not_qualify(self):
        tags = {'cTEST': {}}
        pv = {'cTEST': [{'variant_name': 'Test (regular)'}]}
        assert not oops_v3.is_boss_tier_prefix('cTEST', tags, pv)

    def test_any_one_boss_variant_in_list_qualifies(self):
        # Mixed list — boss-marker on ANY variant trips the OR.
        tags = {'cTEST': {}}
        pv = {'cTEST': [
            {'variant_name': 'Test (regular)'},
            {'variant_name': 'Test (Phase 1)'},
            {'variant_name': 'Test (trash)'},
        ]}
        assert oops_v3.is_boss_tier_prefix('cTEST', tags, pv)

    def test_empty_inputs_does_not_qualify(self):
        # No tag, no variants — not boss.
        assert not oops_v3.is_boss_tier_prefix('cMISSING', {}, {})

    def test_missing_cp_in_tags_does_not_crash(self):
        # tags.get(cp, {}) defaults to empty — function should not raise.
        # Variants-only path can still qualify.
        pv = {'cTEST': [{'variant_name': 'Test (Field Boss)'}]}
        assert oops_v3.is_boss_tier_prefix('cTEST', {}, pv)


# ---------------------------------------------------------------------------
# The heritage hp_median leg — the trickiest one
# ---------------------------------------------------------------------------

class TestHeritageHpMedianLeg:
    """The heritage-pack-curated mid-boss leg:

        cp in V3_HERITAGE_ALL_PREFIXES AND tag.hp_median >= 300

    This catches chrs like Pumpkin Head, Bloodfiend, etc. whose variant
    names lack 'Boss' markers but the heritage pack has tagged them as
    significant enemies with boss-grade HP. This is the leg that uses
    a module global (V3_HERITAGE_ALL_PREFIXES), so monkeypatching it
    is required to test in isolation.
    """

    def test_heritage_cp_with_high_hp_qualifies(self, monkeypatch):
        monkeypatch.setattr(oops_v3, 'V3_HERITAGE_ALL_PREFIXES', {'cHERIT'})
        tags = {'cHERIT': {'hp_median': 350}}
        assert oops_v3.is_boss_tier_prefix('cHERIT', tags, {})

    def test_heritage_cp_with_hp_at_threshold_qualifies(self, monkeypatch):
        monkeypatch.setattr(oops_v3, 'V3_HERITAGE_ALL_PREFIXES', {'cHERIT'})
        tags = {'cHERIT': {'hp_median': 300}}
        assert oops_v3.is_boss_tier_prefix('cHERIT', tags, {})

    def test_heritage_cp_with_low_hp_does_not_qualify(self, monkeypatch):
        # Below threshold — heritage membership alone is not enough.
        monkeypatch.setattr(oops_v3, 'V3_HERITAGE_ALL_PREFIXES', {'cHERIT'})
        tags = {'cHERIT': {'hp_median': 299}}
        assert not oops_v3.is_boss_tier_prefix('cHERIT', tags, {})

    def test_non_heritage_cp_with_high_hp_does_not_qualify(self, monkeypatch):
        # HP alone — no heritage membership — doesn't fire this leg.
        # And no other leg satisfied either.
        monkeypatch.setattr(oops_v3, 'V3_HERITAGE_ALL_PREFIXES', set())
        tags = {'cTEST': {'hp_median': 9999}}
        assert not oops_v3.is_boss_tier_prefix('cTEST', tags, {})

    def test_heritage_cp_with_missing_hp_does_not_qualify(self, monkeypatch):
        # Missing hp_median defaults to 0 — doesn't reach threshold.
        # Verifies the `or 0` clause guards against KeyError / None.
        monkeypatch.setattr(oops_v3, 'V3_HERITAGE_ALL_PREFIXES', {'cHERIT'})
        tags = {'cHERIT': {}}
        assert not oops_v3.is_boss_tier_prefix('cHERIT', tags, {})

    def test_heritage_cp_with_none_hp_does_not_qualify(self, monkeypatch):
        # Defensive: hp_median=None should not crash, should evaluate
        # as 0 via the `or 0` short-circuit.
        monkeypatch.setattr(oops_v3, 'V3_HERITAGE_ALL_PREFIXES', {'cHERIT'})
        tags = {'cHERIT': {'hp_median': None}}
        assert not oops_v3.is_boss_tier_prefix('cHERIT', tags, {})


# ---------------------------------------------------------------------------
# Live-fixture cross-checks — confirms decision tree against real data
# ---------------------------------------------------------------------------

class TestIsBossTierPrefixLive:
    """Spot-checks against the loaded fixture. Each test names a real cp
    and which leg of the OR chain we expect to fire. If the function
    diverges, either the leg semantics changed or the underlying data
    drifted — both worth catching.
    """

    def test_c4500_tree_sentinel_is_boss_via_variant_marker(
            self, tags, prefix_variants):
        # Tree Sentinel has '(Field Boss)' variants. Should qualify
        # via the variant-marker leg even if no tag-side signal fires.
        assert oops_v3.is_boss_tier_prefix('c4500', tags, prefix_variants)

    def test_c2130_margit_is_boss_via_variant_marker(
            self, tags, prefix_variants):
        # Margit has '(Night Boss)' variants — classic NB.
        assert oops_v3.is_boss_tier_prefix('c2130', tags, prefix_variants)

    def test_c4910_magma_wyrm_is_boss(self, tags, prefix_variants):
        # Magma Wyrm — has '(Field Boss)' variant.
        assert oops_v3.is_boss_tier_prefix('c4910', tags, prefix_variants)

    def test_c3470_albinauric_not_boss(self, tags, prefix_variants):
        # Trash sentry — no boss marker, no reward, low height/HP.
        assert not oops_v3.is_boss_tier_prefix(
            'c3470', tags, prefix_variants)

    def test_unknown_cp_does_not_crash(self, tags, prefix_variants):
        # Defensive: cp not in tags + not in prefix_variants — must
        # return False, not raise.
        assert not oops_v3.is_boss_tier_prefix(
            'cTOTALLY_FAKE', tags, prefix_variants)


# ---------------------------------------------------------------------------
# is_boss_tier_variant invariants — for completeness, since the prefix
# function calls into the same marker set indirectly
# ---------------------------------------------------------------------------

class TestBossMarkerContainmentInvariant:
    """The three predicates *partially* form a containment hierarchy.
    Documenting what actually holds vs what doesn't:

        is_night_or_field_boss ⇒ is_night_boss   ✓ holds (both
            'Night Boss' and 'Field Boss' are in NIGHT_BOSS_NAME_MARKERS)

        is_night_boss ⇒ is_boss_tier   ✗ DOES NOT hold. Shifting Earth
            qualifier-only variants — those whose variant_name contains
            '(Crater)' or '(Noklateo)' but no base 'Boss'/'Remembrance'
            word — satisfy is_night_boss but not is_boss_tier.

    The non-containment may be intentional: Shifting Earth boss variants
    might be deliberately scoped to SE arenas only, not general boss-
    tier slots. Or it may be a tagging gap: '(Crater)'/'(Noklateo)'
    arguably should also be in V3_BOSS_NAME_MARKERS. The current state
    is preserved by these tests; flag for triage if you want it changed.
    """

    def test_every_night_or_field_marker_satisfies_night_boss(self):
        # The tight containment direction. Holds for synthetic strings.
        for marker in oops_v3.V3_NIGHT_OR_FIELD_BOSS_NAME_MARKERS:
            v = {'variant_name': f'X {marker}'}
            assert oops_v3.is_night_or_field_boss_variant(v), marker
            assert oops_v3.is_night_boss_variant(v), marker

    def test_real_night_or_field_variants_all_satisfy_night_boss(self, roster):
        # Empirical version of the above. Should always pass; if it
        # ever fails, the marker sets have drifted out of sync.
        offenders = []
        for v in roster['all_variants']:
            if oops_v3.is_night_or_field_boss_variant(v):
                if not oops_v3.is_night_boss_variant(v):
                    offenders.append(v.get('variant_name'))
        assert not offenders, (
            f"{len(offenders)} variants satisfy is_night_or_field_boss "
            f"but not is_night_boss — first 5: {offenders[:5]}")

    def test_shifting_earth_qualifier_only_variants_break_night_boss_containment(
            self, roster):
        # Locks in the current behavior: variants whose only boss-marker
        # is '(Crater)' or '(Noklateo)' satisfy is_night_boss (so they
        # land at NB-anchor slots during SE events) but NOT is_boss_tier
        # (so they're excluded from the general boss-tier pool).
        #
        # This test ASSERTS the quirk exists. If a future change fixes
        # the asymmetry (e.g. by adding the qualifiers to BOSS_NAME_MARKERS),
        # this test will fail and you'll need to either update or delete
        # it — both fine. The point is that the asymmetry doesn't change
        # silently.
        broken = [v for v in roster['all_variants']
                  if oops_v3.is_night_boss_variant(v)
                  and not oops_v3.is_boss_tier_variant(v)]
        assert len(broken) > 0, (
            "Expected some variants to satisfy is_night_boss but not "
            "is_boss_tier (the Shifting Earth qualifier-only quirk). "
            "If this is now zero, the asymmetry has been resolved — "
            "delete this test.")
        # Every offender should have a Shifting Earth qualifier.
        for v in broken:
            name = v.get('variant_name', '')
            assert '(Crater)' in name or '(Noklateo)' in name, (
                f"Unexpected night_boss-but-not-boss_tier variant: "
                f"{name!r} — doesn't match the known SE quirk pattern. "
                f"Either a new quirk type appeared or a tagging bug exists.")
