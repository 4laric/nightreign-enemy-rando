"""Tests for `pick_target_cp` — variants and tags.

Split from `tests/test_pick_target.py` in v0.28.x to make the
5,279-line monolith navigable. See sibling `test_pick_target*.py`
files for other themes; the split is enforced by
`tests/test_pick_target_split_lock.py` (lock the (class, method)
set across files).
"""
import random
import pytest
import oops_v3
from engine.state import GateState

class TestCanonicalVariantPreference:
    """Tests for V3_PREFER_CANONICAL_VARIANTS and variant-source classification.

    Background: c-prefixes have a mix of canonical variants (sample_maps
    non-empty, vanilla NR places them) and ghost variants (sample_maps=[],
    post-DLC dump entries vanilla never instantiated). Ghost variants tend
    to visually glitch. The picker now prefers canonical variants when
    available; falls back to ghosts when no canonical exists for the cp.
    """

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    @pytest.fixture
    def loaded(self, engine):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = engine.load_data()
        from collections import defaultdict
        prefix_variants = defaultdict(list)
        for v in roster['all_variants']:
            if isinstance(v, dict) and 'c_prefix' in v:
                prefix_variants[v['c_prefix']].append(v)
        return roster, tags, prefix_variants

    # --- Classifier tests ---------------------------------------------------

    def test_classify_canonical(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        # c4640 npc=46400020 is the canonical Ulcerated Tree Spirit
        r = engine._classify_variant_source(
            'c4640', 46400020, prefix_variants, tags)
        assert r == 'canonical', (
            f'c4640 npc=46400020 should classify as canonical, got {r!r}')

    def test_classify_ghost_variant(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        # c4640 npc=46400030 — the variant that triggered the v0.24.35 fix.
        # post_dlc_dump, sample_maps=[], visually glitches
        r = engine._classify_variant_source(
            'c4640', 46400030, prefix_variants, tags)
        assert r == 'ghost_variant', (
            f'c4640 npc=46400030 should classify as ghost_variant '
            f'(visually glitches), got {r!r}')

    def test_classify_imported_chr(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        # c6031 Bear — heritage import (cross-engine from another From game).
        # Whole chr is wholesale-imported, not in vanilla NR placement pool.
        r = engine._classify_variant_source(
            'c6031', 60310000, prefix_variants, tags)
        assert r == 'imported_chr', (
            f'c6031 Bear (heritage) should classify as imported_chr, got {r!r}')

    def test_classify_unknown_cp_returns_unknown(self, engine, loaded):
        roster, tags, prefix_variants = loaded
        r = engine._classify_variant_source(
            'c99999', 99999999, prefix_variants, tags)
        assert r == 'unknown'

    # --- Picker tests -------------------------------------------------------

    def test_picker_prefers_canonical_when_available(self, engine, loaded,
                                                     monkeypatch):
        """When canonical-prefer is ENABLED, and canonical variants exist,
        the picker picks them at any slot tier.

        v0.28.2: V3_PREFER_CANONICAL_VARIANTS now defaults False (variety
        pass — see the flag's rationale block in oops_v3). This test
        exercises the filter's behaviour, so it force-enables the flag
        rather than relying on the default; the default itself is locked
        by test_v3_prefer_canonical_default_is_false below.
        """
        roster, tags, prefix_variants = loaded
        import random
        monkeypatch.setattr(engine, 'V3_PREFER_CANONICAL_VARIANTS', True)
        # Disable the variant prune list so we test canonical-prefer in
        # ISOLATION — same pattern as test_picker_with_canonical_pref_disabled.
        # The prune list is a separate, unconditional gate that runs before
        # canonical-preference; with it active for c4640 it currently drops
        # the canonical (46400020) and keeps a ghost (see docs/TODO.md prune-
        # list finding), which is a prune-data bug tracked separately, not a
        # canonical-prefer regression.
        monkeypatch.setattr(engine, '_V3_VARIANT_PRUNE_IDS', set())
        monkeypatch.setattr(engine, 'V3_APPLY_VARIANT_PRUNE_LIST', False)
        # c4640 has 1 canonical (46400020) + 5 ghosts. With canonical-prefer
        # ON, 100% of picks should land on 46400020.
        picks = set()
        for seed in range(50):
            rng = random.Random(seed)
            v = engine.pick_variant_for_tier(
                'c4640', True, prefix_variants, rng, tags=tags)
            if v: picks.add(v.get('npc_param_id'))
        assert picks == {46400020}, (
            f'c4640 with canonical-prefer should only pick npc=46400020, '
            f'got {picks}. If ghosts (46400000/10/30/110/700) are in this '
            f'set, the canonical-prefer filter is not active.')

    def test_picker_falls_back_when_no_canonical(self, engine, loaded):
        """For cps with 0 canonical variants, picker still picks (soft filter)."""
        roster, tags, prefix_variants = loaded
        # Find a cp with 0 canonical variants and >0 total variants
        no_canonical_cps = []
        for cp, variants in prefix_variants.items():
            if not variants: continue
            if not any(v.get('sample_maps') for v in variants):
                no_canonical_cps.append((cp, len(variants)))
        if not no_canonical_cps:
            pytest.skip('No 0-canonical cps in roster (unexpected)')
        cp, n_variants = max(no_canonical_cps, key=lambda x: x[1])
        # Should pick something — the soft filter returns all variants when
        # no canonical exists, so the tier-fallback picks from the ghost pool
        import random
        rng = random.Random(0)
        v = engine.pick_variant_for_tier(cp, False, prefix_variants, rng,
                                          tags=tags)
        assert v is not None, (
            f'{cp} (0 canonical, {n_variants} ghosts) should still pick '
            f'(soft fallback), got None')

    def test_picker_with_canonical_pref_disabled(self, engine, loaded,
                                                  monkeypatch):
        """With V3_PREFER_CANONICAL_VARIANTS=False, ghost variants are eligible.

        The variant prune list (v0.27.x) is a separate, unconditional ghost
        gate that runs BEFORE the canonical-preference logic, so it must be
        disabled here to test the V3_PREFER_CANONICAL_VARIANTS flag in
        isolation — otherwise the prune list removes c4640's ghost rows
        regardless of the flag and there is nothing for this test to assert.
        """
        roster, tags, prefix_variants = loaded
        monkeypatch.setattr(engine, 'V3_PREFER_CANONICAL_VARIANTS', False)
        # Force the prune cache empty for this test (monkeypatch reverts it).
        monkeypatch.setattr(engine, '_V3_VARIANT_PRUNE_IDS', set())
        monkeypatch.setattr(engine, 'V3_APPLY_VARIANT_PRUNE_LIST', False)
        import random
        # c4640 at a FIELD slot (not boss) — without canonical-prefer, the
        # picker can land on any variant. Several rolls should produce
        # at least one ghost.
        picks = set()
        for seed in range(100):
            rng = random.Random(seed)
            v = engine.pick_variant_for_tier(
                'c4640', False, prefix_variants, rng, tags=tags)
            if v: picks.add(v.get('npc_param_id'))
        # We expect to see at least one ghost variant in the picks now.
        # (At boss slots tier-1/2 narrow to reward-bearing which is the
        # canonical here, so we test at field slot.)
        ghost_npcs = {46400000, 46400010, 46400030, 46400110, 46400700}
        assert picks & ghost_npcs, (
            f'With prefer_canonical=False at field slot, c4640 should be '
            f'able to land on at least one ghost variant across 100 rolls. '
            f'Got picks={picks}, ghosts available={ghost_npcs}')

    # --- Filter primitive tests ---------------------------------------------

    def test_filter_canonical_variants_with_canonicals(self, engine):
        variants = [
            {'npc_param_id': 1, 'sample_maps': ['m10_00.msb']},
            {'npc_param_id': 2, 'sample_maps': []},
            {'npc_param_id': 3, 'sample_maps': ['m20_00.msb', 'm30_00.msb']},
        ]
        result = engine._filter_canonical_variants(variants)
        assert {v['npc_param_id'] for v in result} == {1, 3}

    def test_filter_canonical_variants_no_canonicals_falls_back(self, engine):
        # All ghosts — should return input unchanged
        variants = [
            {'npc_param_id': 1, 'sample_maps': []},
            {'npc_param_id': 2, 'sample_maps': []},
        ]
        result = engine._filter_canonical_variants(variants)
        assert {v['npc_param_id'] for v in result} == {1, 2}, (
            'When no canonical variants exist, filter must return all '
            'variants unchanged (soft fallback for c70003/c3360/etc.)')

    def test_filter_canonical_variants_empty_input(self, engine):
        # Defensive: empty input returns empty (no canonicals possible)
        assert engine._filter_canonical_variants([]) == []

    # --- Config sanity ------------------------------------------------------

    def test_v3_prefer_canonical_default_is_false(self, engine):
        # History: v0.24.101 True->False ("open the floodgates" variety).
        # v0.24.109 briefly True. v0.26.16 flipped back to True + GUI
        # checkbox. v0.28.2 flipped to False again — the bad ghost
        # variants that motivated the True stance are now isolated by
        # other mechanisms (per-chr exclusions, the variant prune list,
        # prefix-level filters), so the soft canonical-prefer filter is
        # no longer load-bearing and the default restores the fuller
        # variant pool for variety. The filter, GUI checkbox, and soft
        # fallback all remain intact for anyone who wants the old
        # behaviour. See the flag's rationale block in oops_v3.
        assert engine.V3_PREFER_CANONICAL_VARIANTS is False, (
            'V3_PREFER_CANONICAL_VARIANTS should default False as of '
            'v0.28.2 — variety pass; bad ghosts are isolated at their '
            'proper level (per-variant blocklist / prefix exclusion), '
            'and the GUI checkbox re-enables canonical-prefer on demand.')


class TestDumpOnlyChrHardExclude:
    """The chr-asset-import tool flagged 8 c-prefixes as missing source files
    (no .chrbnd in NR's installed assets or any From game install). They're
    `_source: post_dlc_dump` entries — captured from regulation data dump but
    never actually shipped as game assets. v0.24.36 hard-excludes them.

    Previously MP-safe-only blocked. With MP-safe OFF (e.g., chaos testing),
    these chrs could be picked → no file to load → invisible placement →
    missing boss / empty grunt slot. The hard exclude blocks them in every
    run mode.

    Seed 271328 (v0.24.33, MP-safe OFF) is the smoking gun: 66 placements of
    these 8 chrs across the seed, including m46_82 pi=1 (a castle_interior
    boss anchor that got c7930 Demon in Pain — likely the source of the
    'missing castle basement boss' Alaric reported)."""

    DUMP_ONLY_NO_FILE_CPS = [
        'c4358', 'c4801', 'c7610', 'c7650', 'c7651',
        'c7660', 'c7720', 'c7930',
    ]

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    @pytest.fixture
    def loaded(self, engine):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = engine.load_data()
        return roster, tags

    def test_all_8_in_hard_exclude(self, engine):
        """Source-of-truth: all 8 must be in V3_EXCLUDE_TARGET_PREFIXES.
        If any drop out by accident, the missing-castle-boss bug returns."""
        missing = [cp for cp in self.DUMP_ONLY_NO_FILE_CPS
                   if cp not in engine.V3_EXCLUDE_TARGET_PREFIXES]
        assert not missing, (
            f'These no-file dump-only chrs are MISSING from '
            f'V3_EXCLUDE_TARGET_PREFIXES: {missing}. They have no .chrbnd '
            'files; placing them at boss slots produces invisible bosses '
            '(no health bar, no guy). See v0.24.36 commit message.')

    def test_dump_only_chrs_are_post_dlc_source(self, engine, loaded):
        """Sanity check the classification: these all originated from
        the post-DLC data dump (regulation-only, no asset files).

        v0.24.100 introduced the `manual_retier_v0.24.100` source as a
        retag for chrs whose original post_dlc_dump classification
        needed manual review — but the underlying "no chrbnd on disk"
        property is unchanged; only the provenance tag moved. Accept
        either source as evidence of the dump-only origin.
        """
        roster, tags = loaded
        valid_sources = {'post_dlc_dump', 'manual_retier_v0.24.100'}
        for cp in self.DUMP_ONLY_NO_FILE_CPS:
            t = tags.get(cp, {})
            assert t.get('_source') in valid_sources, (
                f'{cp} expected _source in {valid_sources}, got '
                f'{t.get("_source")!r}. If the source changed beyond '
                f'a v0.24.100-style retier, the hard-exclude rationale '
                f'needs revisiting.')

    def test_dump_only_chrs_have_no_canonical_variants(self, engine, loaded):
        """Cross-check: dump-only chrs by definition have 0 canonical
        variants (sample_maps non-empty would imply vanilla placed them,
        but the asset-copy tool says vanilla doesn't have the chr file).
        If a canonical variant appears, our roster data is inconsistent."""
        roster, _ = loaded
        for cp in self.DUMP_ONLY_NO_FILE_CPS:
            canonical = [v for v in roster['all_variants']
                         if v.get('c_prefix') == cp and v.get('sample_maps')]
            assert not canonical, (
                f'{cp} has {len(canonical)} canonical variants (sample_maps '
                'non-empty) but the chr-asset-import tool reports no file. '
                'Data inconsistency — either the asset tool needs rerunning '
                'with a different source, or the sample_maps entries are stale.')


class TestDataDrivenNoFileChrs:
    """v0.24.37: the no-file chr list migrated from hard-coded to
    data/nr_missing_chr_files.json. The data file is the source of truth;
    hard-coded entries remain as a safety net for the load_data_lock test
    and pre-load_data() queries."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_data_file_exists_and_loads(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_missing_chr_files.json')
        assert os.path.isfile(path), (
            'data/nr_missing_chr_files.json missing — v0.24.37 data-driven '
            'loader has no source. Hard-coded fallback still works but '
            'the migration is incomplete.')
        with open(path) as f:
            d = json.load(f)
        assert 'missing_chrs' in d
        assert len(d['missing_chrs']) >= 8

    def test_all_data_file_entries_in_exclude_set(self, engine):
        import json, os
        path = os.path.join(os.path.dirname(engine.__file__),
                            'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)
        for entry in d['missing_chrs']:
            cp = entry['c_prefix']
            assert cp in engine.V3_EXCLUDE_TARGET_PREFIXES, (
                f'{cp} in data/nr_missing_chr_files.json but NOT in '
                'V3_EXCLUDE_TARGET_PREFIXES — _load_missing_chr_files() '
                'did not merge the data file. Check the loader.')


class TestProactiveNoTagDataBan:
    """v0.24.40: after seed 798229 confirmed c3360 and c4430 (no-tag-data
    post_dlc_dump chrs) were broken, proactively ban all 26 sibling chrs
    matching the same profile. Avoids the wait-for-playtest-report cycle
    for each individual chr."""

    PROACTIVE_BANS = [
        # v0.24.102: c2273/c2275/c2277 (Crab variants), c4162/c4163/c4167
        # (dog variants), c4190/c4192 (Large Scarab) intentionally removed
        # from the auto-cap=1 set per user req. They're trash-tier critters
        # and the defensive cap was blocking organic distribution. Excluded
        # from this expectation list so the test reflects the v0.24.102
        # state. If they recurse-flooding becomes a problem in playtest,
        # restore them to both _LIFTED_V0_24_65 (in oops_v3.py) and here.
        #
        # v0.26.x: c4361 (Godrick Knight's Horse) ALSO removed from this
        # list. v0.25.0-patch1 re-excluded c4361 from V3_EXCLUDE_TARGET_
        # PREFIXES after a mount-component CTD (seeds 939029 and 42); the
        # v0.24.65 lift was superseded. Symmetrically removed from
        # _LIFTED_V0_24_65 in oops_v3.py — see also the test_c4361_excluded
        # lock-in test in TestSeed798229Freezes.
        'c3370',                                # Ancestral Follower Shaman
        'c4140',                                # Spiritcaller Snail (Boss)
        'c4312', 'c4316', 'c4356', 'c4376',    # Soldier/Knight family
        'c4441', 'c4442',                       # Land Squirt family
        'c4482', 'c4483',                       # Fading Miranda Sprout family
        'c4601', 'c4811',                       # Troll Knight, Erdtree Avatar Variant
        'c52309', 'c52312', 'c52313',          # DLC Remembrance variants
        'c6001',                                # Eagle
    ]

    @pytest.fixture
    def engine(self):
        """v0.24.103: explicit load_data() call. The v0.24.65 auto-cap
        runs INSIDE load_data(), so without this the test sees only the
        module-level explicit cap entries (3 of 25) and reports the
        other 22 as uncapped. Was previously passing by coincidence —
        whichever test ran first happened to trigger load_data() via
        conftest's session-scoped fixture and mutate module-level
        V3_UNIQUE_TARGET_CAPS in place. New tests added in v0.24.103
        changed pytest collection order, exposing the latent bug."""
        import oops_v3
        if not hasattr(oops_v3, '_test_loaded'):
            oops_v3.load_data()
            oops_v3._test_loaded = True
        return oops_v3


    def test_all_26_proactive_bans_capped(self, engine):
        """v0.27.8: the v0.24.65 defensive cap=1 safety net was removed.
        Each proactive-ban chr is now either excluded outright or carries
        its tier cap (grunt=32, miniboss=4) — none is left uncapped."""
        excl = (engine.V3_EXCLUDE_PREFIXES
                | engine.V3_EXCLUDE_TARGET_PREFIXES
                | engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
        uncapped = [cp for cp in self.PROACTIVE_BANS
                    if cp not in excl
                    and engine.V3_UNIQUE_TARGET_CAPS.get(cp) is None]
        assert not uncapped, (
            f'eligible proactive-ban chrs should carry a tier cap; '
            f'uncapped: {uncapped}')

    def test_proactive_bans_have_proactive_ban_flag(self):
        """Data file entries for proactive bans should be tagged
        proactive_ban=true. Lets future code distinguish 'playtest-confirmed
        broken' from 'banned by pattern match'."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)
        proactive_set = set(self.PROACTIVE_BANS)
        for entry in d['broken_runtime_chrs']:
            if entry['c_prefix'] in proactive_set:
                assert entry.get('proactive_ban') is True, (
                    f'{entry["c_prefix"]} should have proactive_ban=true')

    def test_playtest_confirmed_have_observed_metadata(self):
        """Every broken_runtime_chrs entry must record SOME provenance —
        either an observed_seed (playtest-found) or an observed_version
        (static-analysis-found, e.g. v0.25.0 added 4 entries gated by
        per-chr script absence rather than a specific playtest seed).

        Originally this asserted "not proactive_ban → has observed_seed",
        but the v0.25.0 post_dlc_dump audit added a third category:
        symptom=no_ai_brain entries identified via static asset analysis,
        which legitimately have observed_version but no observed_seed.
        """
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)
        for entry in d['broken_runtime_chrs']:
            if entry.get('proactive_ban', False):
                continue  # proactive bans are pattern-matched, no provenance needed
            has_seed = bool(entry.get('observed_seed'))
            has_version = bool(entry.get('observed_version'))
            assert has_seed or has_version, (
                f'{entry["c_prefix"]} is not proactive_ban but has '
                f'neither observed_seed (playtest) nor observed_version '
                f'(static-analysis). Add one to record how the ban was '
                f'discovered.')

    def test_c2274_giant_sleep_crab_un_banned_v0_24_41(self, engine):
        """v0.24.41: c2274 Giant Sleep Crab confirmed working in playtest
        and un-banned. The regular-size crab siblings (c2273/c2275/c2277)
        remain banned as 'set dressing' — likely render fine but low-value
        placements; keep the safety net."""
        assert 'c2274' not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c2274 (Giant Sleep Crab) was un-banned in v0.24.41 — '
            'confirmed working in playtest. If this test fails, c2274 '
            'was re-added to a ban list somewhere.')


class TestTagBackfillV0_24_72:
    """v0.24.72: backfilled anim_class + size_class for 43 untagged chrs
    in nr_enemy_tags.json and mmv_imports.json. Justification per entry
    in scripts/backfill_tags_v0_24_72.py.

    These tests verify the canonical entries didn't lose their backfill,
    and that Gate 5.6 (and other anim_class filters) now correctly fire
    on the backfilled chrs. Catches regression where someone
    regenerates the tag files without preserving the backfill.

    Confirmed seed 388677 v0.24.71 m34_00 (Albinauric Village)
    pi=100/101 CTD: c4171 (large_boss_ground/XXL) → c4601 humanoid
    Troll Knight, slipped past Gate 5.6 because c4601 was untagged.
    Backfill resolves: c4601 = humanoid/XXL → Gate 5.6 catches the
    anim drift.
    """


    def test_gate_5_6_c4601_at_large_boss_ground_source_post_v0_24_75(self, engine, tags):
        """The seed-388677 fix verification, updated for v0.24.75.

        Pre-v0.24.75: at c4171 (Giant Putrid Flesh, large_boss_ground/XXL)
        source slot, Gate 5.6 rejected c4601 (humanoid/XXL) due to
        anim_class drift.

        Post-v0.24.75: anim_class drift gate removed per user directive.
        c4601 humanoid/XXL at c4171 large_boss_ground/XXL source now
        passes Gate 5.6 (sizes match, anim_class no longer checked).

        Whether the seed-388677 CTD recurs is now an open question —
        the original attribution may have been wrong (per user
        directive: "anim_class crashes were actually other root cause").
        If the CTD does recur in playtest, re-investigate root cause."""
        reason = engine._reject_target_for_slot(
            target_cp='c4601', src_cp='c4171',
            src_variant_name='Giant Putrid Flesh (Blood)', tags=tags,
            msb_base='m34_00_00_00.msb', pi=100)
        assert reason != 'xxl_giga_anim_drift', (
            f'v0.24.75: anim_drift gate removed; got {reason!r}')

    def test_gate_5_6_accepts_c4601_at_humanoid_xxl_source(self, engine, tags):
        """Sanity: at humanoid XXL source slots (the Troll family
        c4600/c4602/c4603), c4601 is a perfectly compat swap and
        must NOT be rejected. Gate 5.6 is anim-aware now."""
        reason = engine._reject_target_for_slot(
            target_cp='c4601', src_cp='c4602',
            src_variant_name='Snowfield Troll', tags=tags,
            msb_base='m60_43_38_10.msb', pi=46)
        assert reason is None


class TestGhostExcludeAudit:
    """v0.24.89-patch10: the ghost-exclude set was reduced from 7 to 1
    after audit. The 6 lifted entries (c5240/c5241/c5311/c5312/c5750/
    c5751) were inherited from April 2026 shape-association speculation
    and never empirically confirmed. Only c2040 Juvenile Scholar remains,
    backed by a confirmed tower-encounter freeze.

    This test class locks in the audit decision: don't let the
    speculative entries drift back in without empirical evidence."""

    def test_only_c2040_in_ghost_exclude(self, engine):
        """The ghost-exclude set should contain exactly c2040 — every
        other entry needs an empirical (seed, msb, pi) citation."""
        assert engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES == {'c2040'}, (
            f'V3_GHOST_EXCLUDE_TARGET_PREFIXES drifted from the v0.24.89 '
            f'audit baseline. If you added a new entry, document it with '
            f'a specific empirical citation (seed + msb + pi where the '
            f'freeze occurred), not by shape/vibe analogy. Current: '
            f'{sorted(engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)}')

    def test_lifted_ghost_excludes_can_be_targets(self, engine, tags):
        """The 6 lifted ghost-excludes should now pass the target-pool
        filter at normal slots."""
        lifted = ['c5240', 'c5241', 'c5311', 'c5312', 'c5750', 'c5751']
        ghost = engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES
        for cp in lifted:
            assert cp not in ghost, (
                f'{cp} was lifted in v0.24.89-patch10; do not re-add '
                f'without empirical citation')


class TestVariantPruneList:
    """Tests for the v0.27.x redundant-variant prune list.

    The prune list (data/variant_prune_list.json, generated by
    dev/audit_genuine_variants.py) drops context-duplicate / ghost
    NpcParam rows from the RANDOM pick path in pick_variant_for_tier.
    Each genuine variant keeps a representative, so no genuine variant
    is removed from the pool. The filter is soft: if pruning empties a
    pool the original is restored.
    """

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    @pytest.fixture
    def loaded(self, engine):
        import io
        from contextlib import redirect_stdout
        from collections import defaultdict
        buf = io.StringIO()
        with redirect_stdout(buf):
            roster, tags = engine.load_data()
        prefix_variants = defaultdict(list)
        for v in roster['all_variants']:
            if isinstance(v, dict) and 'c_prefix' in v:
                prefix_variants[v['c_prefix']].append(v)
        return roster, tags, prefix_variants

    def test_pruned_id_never_picked(self, engine, loaded, monkeypatch):
        """A npc_param_id in the prune set is never returned by the picker."""
        import random
        roster, tags, prefix_variants = loaded
        # Pick a c3010 (Banished Knight) variant id that exists in the pool.
        pool = prefix_variants['c3010']
        assert pool, 'c3010 should have variants'
        target = pool[0]['npc_param_id']
        monkeypatch.setattr(engine, 'V3_APPLY_VARIANT_PRUNE_LIST', True)
        monkeypatch.setattr(engine, '_V3_VARIANT_PRUNE_IDS', {target})
        for seed in range(300):
            v = engine.pick_variant_for_tier(
                'c3010', False, prefix_variants, random.Random(seed), tags=tags)
            if v:
                assert v.get('npc_param_id') != target, (
                    f'pruned id {target} was picked at seed {seed}')

    def test_control_pruned_id_reachable_when_set_empty(self, engine, loaded,
                                                        monkeypatch):
        """Control: with an empty prune set the same id IS reachable."""
        import random
        roster, tags, prefix_variants = loaded
        monkeypatch.setattr(engine, '_V3_VARIANT_PRUNE_IDS', set())
        seen = set()
        for seed in range(300):
            v = engine.pick_variant_for_tier(
                'c3010', False, prefix_variants, random.Random(seed), tags=tags)
            if v:
                seen.add(v.get('npc_param_id'))
        assert len(seen) > 1, (
            'c3010 should reach multiple variant ids with no prune set')

    def test_soft_fallback_when_prune_empties_pool(self, engine, loaded,
                                                   monkeypatch):
        """If the prune set covers EVERY row of a c-prefix, the soft
        fallback restores the pool rather than returning None."""
        import random
        roster, tags, prefix_variants = loaded
        all_c3010 = {v['npc_param_id'] for v in prefix_variants['c3010']}
        monkeypatch.setattr(engine, '_V3_VARIANT_PRUNE_IDS', all_c3010)
        got = None
        for seed in range(50):
            v = engine.pick_variant_for_tier(
                'c3010', False, prefix_variants, random.Random(seed), tags=tags)
            if v:
                got = v
                break
        assert got is not None, (
            'soft fallback should restore the pool when pruning empties it')

    def test_no_cprefix_emptied_by_real_prune_list(self, engine, loaded):
        """With the real on-disk prune list, every c-prefix that had a
        pool still yields a pick — no genuine variant fully lost."""
        import random
        roster, tags, prefix_variants = loaded
        # force a fresh load of the real prune file
        engine._V3_VARIANT_PRUNE_IDS = None
        prune = engine._variant_prune_ids()
        if not prune:
            pytest.skip('no prune list present in data/')
        # A target-excluded c-prefix is never in the random placement pool,
        # so an empty variant pool for it is harmless — skip those (otherwise
        # e.g. c3200 Nomadic Merchant / c61003 Wylder Remembrance, both
        # excluded, false-positive here). The invariant only matters for
        # c-prefixes the picker can actually land on.
        excluded = (engine.V3_EXCLUDE_TARGET_PREFIXES
                    | engine.V3_EXCLUDE_PREFIXES
                    | engine.V3_GHOST_EXCLUDE_TARGET_PREFIXES)
        emptied = []
        for cp, pool in prefix_variants.items():
            if not pool:
                continue
            if cp in excluded:
                continue
            v = engine.pick_variant_for_tier(
                cp, False, prefix_variants, random.Random(0), tags=tags)
            # None can legitimately happen for non-combat / filtered cps,
            # but only if it was None pre-prune too — check that here.
            if v is None:
                engine._V3_VARIANT_PRUNE_IDS = set()
                v_noprune = engine.pick_variant_for_tier(
                    cp, False, prefix_variants, random.Random(0), tags=tags)
                engine._V3_VARIANT_PRUNE_IDS = None
                if v_noprune is not None:
                    emptied.append(cp)
        assert not emptied, (
            f'prune list emptied the pickable pool for: {emptied}')


class TestMountAtNonMountSourceGate:
    """Regression for the riderless-mount freeze/float CTD.

    The v0.27.13 rider/mount pool gate restricted a mount-SOURCE slot to
    mount targets, but did NOT stop a mount (c4060/c5890 — the horses,
    mount_role='mount') from leaking onto an ORDINARY slot via the general
    compat pool. A horse has no standalone AI: placed away from a paired
    rider it spawns frozen / floats. The post-generation CTD checker
    (_ctd_check_mount_target_at_non_mount_source) was flagging 20+ of these
    per seed but doing nothing about them. v0.27.43 completes the gate: a
    non-role source slot drops V3_MOUNT_PREFIXES from its pool, confining
    mounts to mount-source slots (where the vanilla pair supplies a rider).

    Riders (c4050/c5840) are intentionally NOT gated — they are complete
    standalone enemies and stay broad-pool targets.
    """

    # Real non-role source c-prefixes that the leak landed mounts on
    # (observed in seed 789157's _ctd_risk findings). Used to find a
    # recipient whose compat pool actually contains a mount, so the test
    # exercises the gate instead of passing vacuously.
    _CANDIDATE_NONROLE_SOURCES = [
        'c4070', 'c4300', 'c3000', 'c4200', 'c4380', 'c4161', 'c4110',
        'c2271', 'c4230', 'c4315', 'c4313', 'c3500', 'c3620', 'c3661',
        'c4100', 'c4371', 'c4377', 'c4201', 'c3450',
    ]

    def _recipient_with_mount_in_pool(self, engine, tags):
        mounts = set(engine.V3_MOUNT_PREFIXES)
        for r in self._CANDIDATE_NONROLE_SOURCES:
            if r not in tags:
                continue
            if r in mounts or r in engine.V3_RIDER_PREFIXES:
                continue  # must be a NON-role source
            if engine.compatible_pool(r, tags) & mounts:
                return r
        return None

    def test_mount_prefixes_populated(self, engine):
        """Sanity: the feature is active (else the gate is a no-op and the
        rest of this class would pass vacuously)."""
        assert engine.V3_MOUNT_PREFIXES, (
            'V3_MOUNT_PREFIXES empty — mount-role pool feature inactive; '
            'this regression test needs it loaded.')

    def test_non_mount_source_never_draws_a_mount(
            self, engine, tags, prefix_variants, prefix_count):
        """The core regression: a non-role source whose compat pool DOES
        contain a horse must still never be assigned one, across many
        seeds. Pre-fix this returned a mount on a meaningful fraction of
        seeds (the 24 leaks in seed 789157); post-fix it must be zero."""
        recipient = self._recipient_with_mount_in_pool(engine, tags)
        if recipient is None:
            pytest.skip('no non-role recipient with a mount in its compat '
                        'pool in the loaded data')
        mounts = set(engine.V3_MOUNT_PREFIXES)
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        saved = dict(engine._V3_UNIQUE_PLACED_COUNTS)
        try:
            for seed in range(80):
                engine._V3_UNIQUE_PLACED_COUNTS.clear()
                engine._V3_UNIQUE_PLACED_COUNTS.update(saved)
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng, slot_variant_name=None)
                assert result not in mounts, (
                    f'seed {seed}: non-role source {recipient} drew mount '
                    f'{result} — riderless-mount CTD leak is back '
                    f'(v0.27.43 gate regression).')
        finally:
            engine._V3_UNIQUE_PLACED_COUNTS.clear()
            engine._V3_UNIQUE_PLACED_COUNTS.update(saved)

    def test_seed_ctd_check_clean_on_synthetic_nonmount_placement(self, engine):
        """The CTD checker fires on a mount-at-non-mount-source entry (so
        the audit half still works), but the gate prevents the picker from
        producing such entries. Here we feed the checker a synthetic entry
        directly to prove the check itself is correct + still wired."""
        mounts = sorted(engine.V3_MOUNT_PREFIXES)
        if not mounts:
            pytest.skip('no mounts loaded')
        mount = mounts[0]
        entries = [{
            'map': 'm60_42_36_00.msb', 'part_index': 7, 'entity_id': 0,
            'original': {'c_prefix': 'c3080', 'name': 'Imp'},
            'new': {'c_prefix': mount, 'name': 'Black Knight Horse'},
        }]
        findings = engine.run_seed_ctd_checks(entries, {})
        assert any(f['check'] == 'mount_target_at_non_mount_source'
                   and f['severity'] == 'ctd' for f in findings), (
            'CTD checker should still flag a mount at a non-mount source.')


class TestRiderMountFamilyConsistency:
    """v0.27.44: rider+mount pairs are PRESERVED VANILLA at the slot level,
    superseding the v0.27.43 c5840<->c5890 coordinated-swap family.

    History: v0.27.43 made a swapped Kaiden cluster co-place as the matched
    Black Knight pair (c5840 rider + c5890 mount) to avoid the mismatched
    Kaiden-rig-on-Black-Knight-Horse CTD. An MSB scan of vanilla ER SOTE then
    showed c5890 "Black Knight Horse" is an MMV/NR fabrication with no real
    mount template, and the matched pair ALSO CTDs at runtime. So the approach
    changed (Alaric): ban c5890 outright and keep every vanilla rider+mount
    pair STOCK instead of swapping it. The pair is found by
    _detect_mount_rider_slots (RIDER_MOUNT_PAIRS prefix combo + proximity) and
    BOTH Parts are added to V3_PRESERVE_SLOTS via
    _preserve_detected_rider_mount_pairs, so only the actual paired Parts stay
    vanilla -- a SOLO rider (a dismounted Leyndell Knight c4353, or a foot
    Kaiden c4050) keeps randomizing, which a c-prefix-wide source exclude
    would have wrongly frozen.

    The detector itself is covered by tests/test_mount_rider_detect.py
    (including solo-rider and too-distant cases returning no pair); these tests
    cover the c5890 ban, the now-inert family helpers, the preserve glue, and
    the end-to-end gate behavior.
    """

    def _pick(self, engine, recipient, tags, prefix_variants, prefix_count,
              seed, msb=None, pi=None, preload=None):
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        saved = dict(engine._V3_UNIQUE_PLACED_COUNTS)
        try:
            engine._V3_UNIQUE_PLACED_COUNTS.clear()
            if preload:
                engine._V3_UNIQUE_PLACED_COUNTS.update(preload)
            rng = random.Random(seed)
            return oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng, slot_variant_name=None,
                slot_msb_name=msb, slot_pi=pi)
        finally:
            engine._V3_UNIQUE_PLACED_COUNTS.clear()
            engine._V3_UNIQUE_PLACED_COUNTS.update(saved)

    def test_c5890_banned_and_unplaceable(self, engine, prefix_variants):
        """c5890 Black Knight Horse is banned outright (fabricated mount; the
        matched pair runtime-CTDs)."""
        assert 'c5890' in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c5890 must be target-excluded (banned).')
        import copy
        pv = copy.copy(prefix_variants)
        pv.setdefault('c5890', [58900000])  # ensure presence: the False is the BAN
        assert not engine._placeable_as_target('c5890', pv), (
            'c5890 is banned, so it must never be placeable as a target.')

    def test_family_swap_now_inert(self, engine, prefix_variants):
        """With c5890 banned the c5840<->c5890 swap family can never resolve:
        the mount half is unplaceable, so _selected_swap_family returns None
        even when the rider half (c5840) is placeable. The family machinery is
        kept only as defensive scaffolding (see comment at its definition)."""
        import copy
        pv = copy.copy(prefix_variants)
        pv.setdefault('c5840', [58401000])
        pv.setdefault('c5890', [58900000])
        assert engine._selected_swap_family(pv) is None, (
            'c5890 is banned -> mount half unplaceable -> no family selected '
            '(the swap is superseded by slot-level preservation).')

    def test_no_family_when_a_half_unplaceable(self, engine, prefix_variants):
        """Belt-and-suspenders: dropping either half also yields no family
        (never a half-swap)."""
        import copy
        pv = copy.copy(prefix_variants)
        pv.pop('c5890', None)
        assert engine._selected_swap_family(pv) is None

    def test_preserve_helper_adds_both_pair_slots(self):
        """_preserve_detected_rider_mount_pairs freezes BOTH the rider Part and
        the mount Part of each detected pair, keyed (msb, pi)."""
        saved = dict(oops_v3.V3_PRESERVE_SLOTS)
        try:
            detected = [
                {'rider_pi': 7, 'rider_cp': 'c4050', 'mount_pi': 8,
                 'mount_cp': 'c4060', 'dist': 0.0, 'pilot_active': True},
                {'rider_pi': 12, 'rider_cp': 'c4353', 'mount_pi': 13,
                 'mount_cp': 'c4363', 'dist': 1.2, 'pilot_active': False},
            ]
            added = oops_v3._preserve_detected_rider_mount_pairs(
                detected, 'm60_44_38_20.msb')
            for pi in (7, 8, 12, 13):
                assert ('m60_44_38_20.msb', pi) in oops_v3.V3_PRESERVE_SLOTS, (
                    f'pi {pi} (a paired rider or mount) should be preserved.')
            assert added == {('m60_44_38_20.msb', pi) for pi in (7, 8, 12, 13)}
        finally:
            oops_v3.V3_PRESERVE_SLOTS.clear()
            oops_v3.V3_PRESERVE_SLOTS.update(saved)

    def test_preserve_helper_idempotent_and_scoped(self):
        """Second call adds nothing; a pre-existing key is never overwritten,
        and unrelated (solo) slots are never touched."""
        saved = dict(oops_v3.V3_PRESERVE_SLOTS)
        try:
            key_pre = ('m60_44_38_20.msb', 7)
            oops_v3.V3_PRESERVE_SLOTS[key_pre] = 'MANUAL - do not overwrite'
            detected = [{'rider_pi': 7, 'rider_cp': 'c4050', 'mount_pi': 8,
                         'mount_cp': 'c4060', 'dist': 0.0, 'pilot_active': True}]
            added = oops_v3._preserve_detected_rider_mount_pairs(
                detected, 'm60_44_38_20.msb')
            assert key_pre not in added, 'must not re-add a pre-existing key.'
            assert oops_v3.V3_PRESERVE_SLOTS[key_pre] == 'MANUAL - do not overwrite'
            assert ('m60_44_38_20.msb', 8) in added
            assert ('m60_44_38_20.msb', 99) not in oops_v3.V3_PRESERVE_SLOTS
            assert oops_v3._preserve_detected_rider_mount_pairs(
                detected, 'm60_44_38_20.msb') == set(), 'second call is a no-op.'
        finally:
            oops_v3.V3_PRESERVE_SLOTS.clear()
            oops_v3.V3_PRESERVE_SLOTS.update(saved)

    def test_preserved_pair_slot_returns_none_from_picker(
            self, engine, tags, prefix_variants, prefix_count):
        """End-to-end: a slot the helper preserved makes pick_target_cp return
        None, so the Part stays vanilla through the strict (msb, pi) gate.

        We first find a recipient that normally yields a non-None target at the
        test slot (proving no earlier gate short-circuits it), then preserve the
        slot and confirm the picker now returns None -- isolating the effect to
        the preserve gate the helper feeds."""
        test_msb, test_pi = 'm99_99_99_99.msb', 3
        recipient = baseline = None
        for cand in sorted(tags):
            r0 = self._pick(engine, cand, tags, prefix_variants, prefix_count,
                            seed=0, msb=test_msb, pi=test_pi)
            if r0 is not None:
                recipient, baseline = cand, r0
                break
        if recipient is None:
            pytest.skip('no recipient yields a target at the test slot')
        saved = dict(oops_v3.V3_PRESERVE_SLOTS)
        try:
            detected = [{'rider_pi': test_pi, 'rider_cp': recipient,
                         'mount_pi': test_pi + 1, 'mount_cp': 'c4060',
                         'dist': 0.0, 'pilot_active': False}]
            oops_v3._preserve_detected_rider_mount_pairs(detected, test_msb)
            r = self._pick(engine, recipient, tags, prefix_variants,
                           prefix_count, seed=0, msb=test_msb, pi=test_pi)
            assert r is None, (
                f'slot ({test_msb}, {test_pi}) was preserved but the picker '
                f'returned {r!r} (baseline without preserve was {baseline!r}).')
        finally:
            oops_v3.V3_PRESERVE_SLOTS.clear()
            oops_v3.V3_PRESERVE_SLOTS.update(saved)

    def test_general_slot_still_excludes_mounts(
            self, engine, tags, prefix_variants, prefix_count):
        """A non-role source still never draws a horse (the riderless-mount
        CTD guard is independent of the pairing approach)."""
        mounts = set(engine.V3_MOUNT_PREFIXES)
        if not mounts:
            pytest.skip('no mount prefixes loaded')
        recipient = None
        for cand in ['c4070', 'c4300', 'c3000', 'c4200', 'c4380', 'c4110',
                     'c4230', 'c3500', 'c3620', 'c4100']:
            if (cand in tags and cand not in mounts
                    and cand not in engine.V3_RIDER_PREFIXES
                    and engine.compatible_pool(cand, tags) & mounts):
                recipient = cand
                break
        if recipient is None:
            pytest.skip('no non-role recipient with a mount in its compat pool')
        for seed in range(40):
            r = self._pick(engine, recipient, tags, prefix_variants,
                           prefix_count, seed)
            assert r not in mounts, (
                f'seed {seed}: non-role source {recipient} drew mount {r!r}.')
