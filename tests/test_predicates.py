"""Unit tests for the pure-ish predicate functions in oops_v3.

These functions take their main state as arguments (variant dicts, tags,
prefix_variants) and either return a boolean or a filtered list. They
read module globals (V3_BOSS_NAME_MARKERS, V3_EMERGE_VARIANT_MARKERS,
V3_AVOID_VARIANT_NPC_IDS, V3_HERITAGE_ALL_PREFIXES) but don't mutate
them, which makes them safe to test against the live module state.

Test cases are drawn from:
  - Function docstrings (explicit contract claims)
  - Code comments calling out specific cps / variants / bugs
  - Empirical spot-checks against the loaded fixture data

The c6200 Gael/Scarab case in particular comes straight from the
_filter_primary_identity docstring — it's the bug the function was
written to fix, so it's the canonical regression case.
"""
import oops_v3


# ---------------------------------------------------------------------------
# is_emerge_variant / filter_emerge_variants
# ---------------------------------------------------------------------------

class TestIsEmergeVariant:
    def test_plain_variant_is_not_emerge(self):
        v = {'variant_name': 'Tree Sentinel (Field Boss)'}
        assert oops_v3.is_emerge_variant(v) is False

    def test_spirit_marker_is_emerge(self):
        v = {'variant_name': 'Leyndell Knight (Spirit)'}
        assert oops_v3.is_emerge_variant(v) is True

    def test_phantom_marker_is_emerge(self):
        v = {'variant_name': 'Some Boss (Phantom)'}
        assert oops_v3.is_emerge_variant(v) is True

    def test_night_boss_spirit_marker_is_emerge(self):
        # Cluster-spirit summon marker, distinct from plain (Spirit).
        v = {'variant_name': 'Tree Spirit (Night Boss Spirit)'}
        assert oops_v3.is_emerge_variant(v) is True

    def test_missing_variant_name_is_not_emerge(self):
        # Defensive: empty-name variants should not crash, should fall
        # through as non-emerge. Documents the function's robustness.
        assert oops_v3.is_emerge_variant({}) is False
        assert oops_v3.is_emerge_variant({'variant_name': ''}) is False


class TestFilterEmergeVariants:
    def test_drops_only_emerge_variants(self):
        vs = [
            {'variant_name': 'Tree Sentinel (Field Boss)'},
            {'variant_name': 'Tree Sentinel (Spirit)'},
            {'variant_name': 'Tree Sentinel'},
        ]
        out = oops_v3.filter_emerge_variants(vs)
        assert len(out) == 2
        assert all('(Spirit)' not in v['variant_name'] for v in out)

    def test_all_emerge_falls_back_to_original(self):
        # Documented behavior: if filtering would empty the list, return
        # the original list rather than nothing. Preserves placement
        # coverage at the cost of letting an emerge variant through.
        vs = [
            {'variant_name': 'X (Spirit)'},
            {'variant_name': 'Y (Phantom)'},
        ]
        out = oops_v3.filter_emerge_variants(vs)
        assert out == vs

    def test_empty_list_returns_empty(self):
        assert oops_v3.filter_emerge_variants([]) == []


# ---------------------------------------------------------------------------
# is_boss_tier_variant / is_night_boss_variant / is_night_or_field_boss_variant
# ---------------------------------------------------------------------------

class TestBossTierVariantPredicates:
    """The three boss-marker predicates *roughly* form a containment
    hierarchy. The strict version (set-of-accepted-names containment)
    does NOT hold — `(Crater)` and `(Noklateo)` are night_boss markers
    that don't appear in V3_BOSS_NAME_MARKERS. But on real variant data
    the containment holds empirically because real NR variants always
    carry a base word ('Boss', 'Remembrance') alongside the Shifting
    Earth qualifier. See TestBossMarkerContainmentInvariant in
    test_tier_classification.py for the empirical version.

    is_boss_tier accepts: Boss, Night Boss, Field Boss, Ruins/Fort/Castle
        Boss, Remembrance, Evergaol, Encampment, Phase 1/2, (Boss
    is_night_boss accepts the broad arena subset: Night/Field/Castle/Fort/
        Ruins Boss + (Crater)/(Noklateo)/Remembrance — drops Encampment,
        Evergaol, bare Boss, Phase markers.
    is_night_or_field_boss is the tightest: only Night Boss or Field Boss.
    """

    def test_field_boss_matches_all_three(self):
        v = {'variant_name': 'Tree Sentinel (Field Boss)'}
        assert oops_v3.is_boss_tier_variant(v)
        assert oops_v3.is_night_boss_variant(v)
        assert oops_v3.is_night_or_field_boss_variant(v)

    def test_encampment_only_matches_boss_tier(self):
        # 'Encampment' is in V3_BOSS_NAME_MARKERS but not in the
        # tighter sets — that's the whole reason the tiered predicates
        # exist (Encampment slots are compact, can't host giga chrs).
        v = {'variant_name': 'Banished Knight (Encampment- Shield)'}
        assert oops_v3.is_boss_tier_variant(v)
        assert not oops_v3.is_night_boss_variant(v)
        assert not oops_v3.is_night_or_field_boss_variant(v)

    def test_castle_boss_in_night_but_not_field(self):
        # Castle Boss is in NIGHT_BOSS_NAME_MARKERS but not in
        # NIGHT_OR_FIELD_BOSS_NAME_MARKERS — castle-interior boss
        # arenas have different geometry than Limveld-overworld arenas.
        v = {'variant_name': 'Crucible Knight (Castle Boss)'}
        assert oops_v3.is_boss_tier_variant(v)
        assert oops_v3.is_night_boss_variant(v)
        assert not oops_v3.is_night_or_field_boss_variant(v)

    def test_remembrance_in_night_but_not_field(self):
        v = {'variant_name': 'Maliketh (Remembrance)'}
        assert oops_v3.is_boss_tier_variant(v)
        assert oops_v3.is_night_boss_variant(v)
        assert not oops_v3.is_night_or_field_boss_variant(v)

    def test_crater_qualifier_in_night_but_not_field(self):
        # (Crater) and (Noklateo) are Shifting Earth boss qualifiers —
        # arena geometry, but not Limveld-overworld.
        v = {'variant_name': 'Some Boss (Crater)'}
        assert oops_v3.is_night_boss_variant(v)
        assert not oops_v3.is_night_or_field_boss_variant(v)

    def test_plain_non_boss_variant_matches_none(self):
        v = {'variant_name': 'Tree Sentinel'}
        assert not oops_v3.is_boss_tier_variant(v)
        assert not oops_v3.is_night_boss_variant(v)
        assert not oops_v3.is_night_or_field_boss_variant(v)


# ---------------------------------------------------------------------------
# build_per_prefix_data
# ---------------------------------------------------------------------------

class TestBuildPerPrefixData:
    """build_per_prefix_data groups variants by c_prefix and sums their
    counts, filtering out V3_VARIANT_TRIGGER_MARKERS variants (Cutscene,
    Dummy, Trigger, etc — these aren't real placement candidates).
    """

    def test_groups_variants_by_c_prefix(self):
        roster = {'all_variants': [
            {'c_prefix': 'cTEST1', 'variant_name': 'a', 'count': 1},
            {'c_prefix': 'cTEST1', 'variant_name': 'b', 'count': 1},
            {'c_prefix': 'cTEST2', 'variant_name': 'c', 'count': 1},
        ]}
        pv, pc = oops_v3.build_per_prefix_data(roster)
        assert len(pv['cTEST1']) == 2
        assert len(pv['cTEST2']) == 1

    def test_sums_counts(self):
        roster = {'all_variants': [
            {'c_prefix': 'cTEST1', 'variant_name': 'a', 'count': 5},
            {'c_prefix': 'cTEST1', 'variant_name': 'b', 'count': 3},
        ]}
        _, pc = oops_v3.build_per_prefix_data(roster)
        assert pc['cTEST1'] == 8

    def test_missing_count_defaults_to_one(self):
        # The function uses v.get('count', 1) — variants without an
        # explicit count are treated as singletons.
        roster = {'all_variants': [
            {'c_prefix': 'cTEST1', 'variant_name': 'a'},
            {'c_prefix': 'cTEST1', 'variant_name': 'b', 'count': 2},
        ]}
        _, pc = oops_v3.build_per_prefix_data(roster)
        assert pc['cTEST1'] == 3

    def test_filters_trigger_variants(self):
        roster = {'all_variants': [
            {'c_prefix': 'cTEST1', 'variant_name': 'normal', 'count': 1},
            {'c_prefix': 'cTEST1', 'variant_name': 'Cutscene only', 'count': 1},
            {'c_prefix': 'cTEST1', 'variant_name': 'Dummy variant', 'count': 1},
            {'c_prefix': 'cTEST1', 'variant_name': 'Hidden Trigger', 'count': 1},
        ]}
        pv, pc = oops_v3.build_per_prefix_data(roster)
        assert len(pv['cTEST1']) == 1
        assert pv['cTEST1'][0]['variant_name'] == 'normal'
        # Counts only include the variants that survived filtering.
        assert pc['cTEST1'] == 1

    def test_unknown_prefix_yields_empty_list(self):
        # defaultdict semantics — querying a missing key returns [] not KeyError.
        roster = {'all_variants': []}
        pv, _ = oops_v3.build_per_prefix_data(roster)
        assert pv['cMISSING'] == []


# ---------------------------------------------------------------------------
# compatible_pool — trivial but worth pinning down post-v0.23.72-late
# ---------------------------------------------------------------------------

class TestCompatiblePool:
    def test_returns_all_tags_minus_recipient(self):
        # As of v0.20.0 this returns the universal pool minus self.
        # Test that 'self' is excluded and everything else is present.
        tags = {'cA': {}, 'cB': {}, 'cC': {}}
        out = oops_v3.compatible_pool('cA', tags)
        assert out == {'cB', 'cC'}

    def test_recipient_not_in_tags_returns_full_set(self):
        # Defensive: if recipient_cp isn't in tags, we still get
        # everything in tags (set subtraction of a missing element
        # is a no-op).
        tags = {'cA': {}, 'cB': {}}
        out = oops_v3.compatible_pool('cMISSING', tags)
        assert out == {'cA', 'cB'}

    def test_empty_tags_returns_empty(self):
        assert oops_v3.compatible_pool('cA', {}) == set()


# ---------------------------------------------------------------------------
# night_boss_pool
# ---------------------------------------------------------------------------

class TestNightBossPool:
    def test_includes_cps_with_night_boss_variant(self):
        prefix_variants = {
            'cA': [{'variant_name': 'A (Field Boss)'}],
            'cB': [{'variant_name': 'B (Encampment)'}],  # not in NB marker set
            'cC': [{'variant_name': 'C (Remembrance)'}],
        }
        out = oops_v3.night_boss_pool(prefix_variants)
        assert out == {'cA', 'cC'}

    def test_cp_with_any_qualifying_variant_included(self):
        # Only ONE variant needs to qualify for the cp to be in the pool.
        prefix_variants = {
            'cA': [
                {'variant_name': 'A (Trash)'},
                {'variant_name': 'A (Night Boss)'},
            ],
        }
        assert 'cA' in oops_v3.night_boss_pool(prefix_variants)

    def test_empty_prefix_variants_returns_empty_set(self):
        assert oops_v3.night_boss_pool({}) == set()


# ---------------------------------------------------------------------------
# Live-fixture sanity checks — depend on load_data() output
# ---------------------------------------------------------------------------

class TestAgainstLoadedFixture:
    """These tests assert against the real loaded roster/tags. They double
    as regression cover for the load_data pipeline AND as documentation
    of the canonical engine state.
    """

    def test_load_data_produces_expected_totals(self, tags, roster):
        # As of v0.24.20 with all packs enabled, post-DLC dump + heritage
        # + bfer v1/v2 + mmv: ~390 tags, ~3.4k variants. Numbers are
        # approximate guardrails — they shift slightly as packs update.
        # If these drift significantly, something changed in pack loading.
        assert 300 < len(tags) < 500, f'tags count drifted: {len(tags)}'
        n_variants = len(roster['all_variants'])
        assert 2500 < n_variants < 5000, f'variant count drifted: {n_variants}'

    def test_known_boss_cps_are_boss_tier(self, tags, prefix_variants):
        # Spot-check a handful of obviously-boss cps. These should be
        # boss-tier under is_boss_tier_prefix regardless of which leg of
        # its OR chain fires.
        for cp in ('c4500',     # Tree Sentinel (Field Boss)
                   'c2130',     # Margit (Night Boss)
                   'c4910',     # Magma Wyrm (Field Boss)
                   'c4630'):    # Runebear (Field Boss)
            assert oops_v3.is_boss_tier_prefix(cp, tags, prefix_variants), (
                f'{cp} should be boss-tier')

    def test_known_trash_cps_are_not_boss_tier(self, tags, prefix_variants):
        # Counter-cases. These have neither boss-marker variants nor
        # has_reward flags nor large hit_height — they should not
        # qualify as boss-tier.
        for cp in ('c3470',     # Albinauric (small, sedentary)
                   'c4170'):    # Banished Knight (trash variants, no boss)
            # c4170 may have an Encampment boss variant — it IS in
            # boss markers. Skip if so; this test is about pure-trash cps.
            if any(oops_v3.is_boss_tier_variant(v)
                   for v in prefix_variants.get(cp, [])):
                continue
            assert not oops_v3.is_boss_tier_prefix(cp, tags, prefix_variants), (
                f'{cp} should not be boss-tier')

    def test_mp_safe_blocklist_excludes_vanilla_sources(self, engine, tags):
        # Every cp in the blocklist must have a non-vanilla _source.
        # If this fails, the blocklist derivation has regressed.
        vanilla = engine.V3_VANILLA_NR_SOURCES
        for cp in engine.V3_MP_SAFE_BLOCKLIST:
            src = tags.get(cp, {}).get('_source')
            assert src not in vanilla, (
                f'{cp} in blocklist but has vanilla _source={src!r}')

    def test_vanilla_sourced_cps_are_not_blocked(self, engine, tags):
        # Inverse direction: every cp with a vanilla _source must NOT
        # be in the blocklist. Catches the failure mode where a future
        # patch over-blocks legitimate vanilla content.
        for cp, t in tags.items():
            if t.get('_source') in engine.V3_VANILLA_NR_SOURCES:
                assert cp not in engine.V3_MP_SAFE_BLOCKLIST, (
                    f'vanilla-sourced {cp} (_source={t.get("_source")!r}) '
                    f'wrongly blocked')

    def test_every_loaded_tag_has_an_explicit_source(self, tags):
        # Locks in the v0.24.21 cleanup. Pre-cleanup, 47 base
        # nr_enemy_tags.json entries lacked _source and got swept into
        # the MP-safe blocklist as <no _source>, which over-blocked 28
        # vanilla cps. After the cleanup every cp must have an explicit
        # _source so the audit print is clean and the allow-list /
        # block-list semantics are unambiguous.
        #
        # If this fails, a new tag was added without _source. Either:
        #   - Add _source to it (preferred — every cp should declare its
        #     origin)
        #   - Or accept the cp will be MP-safe-blocked under the
        #     V3_VANILLA_NR_SOURCES allow-list and document why.
        unsourced = [cp for cp, t in tags.items() if not t.get('_source')]
        assert not unsourced, (
            f'{len(unsourced)} cps lack _source: {sorted(unsourced)[:10]}'
            f'{"..." if len(unsourced) > 10 else ""}. Every tag should '
            f'declare _source.')
