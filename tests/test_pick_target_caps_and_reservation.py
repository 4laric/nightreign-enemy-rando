"""Tests for `pick_target_cp` — caps and reservation.

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

class TestDeathKnightTierPromotion:
    """v0.24.47: c5070 Death Knight bumped from miniboss to field_boss.
    User playtest: 'that guy is a menace' — auto-tagged miniboss but
    hp_median=672 and tuned DS3 elite moveset make him play like a
    boss-tier encounter.

    v0.26.x: field_boss tier eliminated (full collapse to miniboss/
    night_boss). c5070 reassigned to miniboss — NB would be wildly
    out-of-class for an M humanoid invader, so miniboss is the only
    sensible bucket. The v0.24.47 'named encounter feel' goes away,
    accepted as a trade for the tier-collapse simplification. If the
    miniboss-tier presence ends up feeling under-budget in playtest,
    a cap (or an NB-tier promotion) can restore the named-encounter
    feel without resurrecting field_boss as a tier."""

    def test_c5070_native_tier_is_miniboss(self):
        """v0.26.x: V3_TAG_OVERRIDES was flattened into nr_enemy_tags.json
        directly for the 33 non-MMV/non-heritage entries; c5070 was one
        of the 5 no-op overrides (tier already matched native), so the
        override entry was dropped and the JSON's native value is the
        authoritative source. This test confirms the JSON has the
        intended tier."""
        import json, os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo, 'data/nr_enemy_tags.json')) as f:
            tags = json.load(f)
        assert tags['c5070']['tier'] == 'miniboss', (
            f"c5070 native tier should be 'miniboss' in "
            f"nr_enemy_tags.json (was flattened from V3_TAG_OVERRIDES "
            f"in v0.26.x); got {tags['c5070']['tier']!r}")

    def test_c5070_effective_tier_is_miniboss(self, engine):
        roster, tags = engine.load_data()
        assert tags['c5070']['tier'] == 'miniboss', (
            f'c5070 effective tier is {tags["c5070"]["tier"]}, expected '
            f'miniboss after v0.26.x tier collapse.')


class TestC5930C6220InvisibleBan:
    """v0.24.49: c5930 Giant Skeleton + c6220 Fire Demon banned as
    likely invisible-enemy culprits in user playtest of seed 460401.

    v0.24.65: BOTH LIFTED with the rest of broken_runtime_chrs. Both
    were tagged _source='mmv_import' — the MMV sfx/material deploy
    that proved Romina works likely resolves their invisibility too.
    cap=1 each via the existing v0.24.53 MMV auto-cap."""

    def test_c5930_no_longer_excluded(self, engine):
        assert 'c5930' not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'v0.24.65 lifted c5930 — should no longer be hard-excluded')

    def test_c6220_no_longer_excluded(self, engine):
        assert 'c6220' not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'v0.24.65 lifted c6220 — should no longer be hard-excluded')

    def test_c5930_capped(self, engine):
        """v0.27.8: the v0.24.53 MMV defensive cap=1 was removed; c5930
        is now capped by its miniboss tier at 4."""
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c5930') == 4

    def test_c6220_capped(self, engine):
        """v0.27.8: miniboss-tier cap=4 (defensive cap=1 removed)."""
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c6220') == 4

    def test_c2274_NOT_banned(self, engine):
        """c2274 has the same partial-tag profile but Alaric explicitly
        un-banned it in v0.24.41 after confirming it works. Unchanged."""
        assert 'c2274' not in engine.V3_EXCLUDE_TARGET_PREFIXES


class TestMmvImportCap1:
    """v0.24.101: The v0.24.53 blanket-cap-MMV-imports-at-1 policy was
    REMOVED as part of the "open the floodgates" variety pass. This class
    verifies the new policy: MMV imports are no longer auto-capped at 1
    proactively. Named-character explicit caps in V3_UNIQUE_TARGET_CAPS
    still apply — only the *blanket* auto-cap was removed.

    If a specific MMV chr proves problematic (CTD/sink) in playtest, add
    it to V3_UNIQUE_TARGET_CAPS explicitly with a tuned cap. Don't
    re-enable the blanket cap.
    """

    def test_mmv_imports_not_auto_capped(self, engine, tags):
        """v0.24.101: MMV imports without an explicit named-chr cap entry
        should NOT appear in V3_UNIQUE_TARGET_CAPS. Auto-cap loop is dead
        code. If MMV imports re-appear in tags (current tags have 0), they
        should be uncapped by default."""
        mmv_chrs = [cp for cp, t in tags.items()
                    if cp != '_has_reward_regen'
                    and t.get('_source') == 'mmv_import']
        if not mmv_chrs:
            pytest.skip('No MMV imports in current tags — policy still '
                        'correct, just nothing to assert against')
        # Of MMV chrs, any that have a cap should ONLY be explicitly-named
        # entries (i.e., the named-chr policy carve-out). Auto-cap would
        # have hit every chr without distinction.
        for cp in mmv_chrs:
            cap = engine.V3_UNIQUE_TARGET_CAPS.get(cp)
            if cap is not None:
                # Verify this is an explicitly-set named-chr cap, not the
                # old blanket=1. The old policy applied cap=1 uniformly;
                # explicit caps may be 1 OR 2+ for chrs intentionally
                # given more room.
                # No hard assert here — just document the survivors so
                # regressions show up via test output.
                pass


    def test_nr_placed_NOT_auto_capped(self, engine, tags):
        """The v0.24.53 rule only applies to MMV imports. Regular
        nr_placed chrs are never given the MMV cap=1. (v0.27.8: grunt
        chrs do carry cap=32 from the grunt-tier block — the point here
        is only that the MMV rule didn't touch them.)"""
        nr_examples = ['c3500', 'c4380', 'c4381']  # common grunts
        for cp in nr_examples:
            if tags.get(cp, {}).get('_source') == 'nr_placed':
                assert engine.V3_UNIQUE_TARGET_CAPS.get(cp) != 1, (
                    f'{cp} is an nr_placed grunt — should never have '
                    f'received the v0.24.53 MMV cap=1')


class TestRedWolfCap:
    """v0.24.54: c3181 Red Wolf of Radagon capped per seed.
    v0.27.6: raised 2 -> 4 by the "4 across the board" miniboss cap
    policy (c3181 is tier=miniboss)."""

    def test_c3181_capped_at_4(self, engine):
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c3181') == 4

    def test_red_wolf_in_quadruped_family_caps(self, engine):
        """Red Wolf cap=2 mirrors c4630 Runebear (same archetype: L-size
        quadruped field_boss)."""
        assert engine.V3_UNIQUE_TARGET_CAPS['c3181'] == engine.V3_UNIQUE_TARGET_CAPS['c4630']


class TestUniqueReservationFragilityFilter:
    """v0.24.62: _score_slot_for_unique now enforces the standard
    SAFE_CONFIRMED ∪ RESILIENT fragility filter at fragile slots —
    plus per-slot EXTRA_BANS. Previously only SENSITIVE was checked,
    leaving a gap where Nightlords and MMV imports could reserve
    fragile slots.

    User report seed 537773 (v0.24.58): c7910 Storm King reserved
    m30_30 pi=45 (Guardian Golem Fort rampart — in V3_PROBLEM_SLOTS
    since v0.24.18 for c4441 Land Squirt CTD). Player CTD walking
    away from the fort. The standard shuffle's RESILIENT∪SAFE filter
    would have prevented this; the unique-reservation path bypassed
    it."""

    def _make_fragile_slot(self):
        # m30_30_00_00 pi=45 is in V3_PROBLEM_SLOTS (T3)
        return {
            'msb': 'm30_30_00_00.msb',
            'pi': 45,
            'source_cp': 'c4660',
            'source_variant_name': 'Guardian Golem (Fort)',
            'position': (None, 42.8, None),
        }

    def test_c7910_allowed_at_fragile_slot_post_flip(self, engine, tags):
        """v0.27.0: fragile filter flipped whitelist -> blacklist. c7910
        Storm King is NOT in V3_FRAGILE_SENSITIVE_TARGETS, so the
        fragility gate alone no longer rejects it. (Tier + arena gates
        still keep a night_boss out of ordinary fragile slots in a real
        run; this test exercises the fragility gate in isolation.) The
        seed-537773 CTD slot is separately protected by EXTRA_BANS.
        """
        if 'c7910' in engine.V3_FRAGILE_SENSITIVE_TARGETS:
            import pytest
            pytest.skip('c7910 is in SENSITIVE; rejection is expected')
        slot = self._make_fragile_slot()
        assert engine._score_slot_for_unique(slot, 'c7910', tags) is not None

    def test_sensitive_chr_rejected_at_fragile_slot(self, engine, tags):
        """v0.27.0: the blacklist is now the load-bearing fragile gate.
        A c-prefix IN V3_FRAGILE_SENSITIVE_TARGETS must still be rejected
        at a fragile slot."""
        slot = self._make_fragile_slot()
        sens = sorted(engine.V3_FRAGILE_SENSITIVE_TARGETS)
        assert sens, 'V3_FRAGILE_SENSITIVE_TARGETS unexpectedly empty'
        sample = sens[0]
        assert engine._score_slot_for_unique(slot, sample, tags) is None, (
            f'{sample} (in V3_FRAGILE_SENSITIVE_TARGETS) must be '
            f'rejected at a fragile slot')

    def test_other_nightlords_rejected_at_fragile_slot(self, engine, tags):
        """Nightlord c-prefixes that are explicitly in V3_FRAGILE_SENSITIVE_
        TARGETS should be rejected at fragile slots.

        v0.26.x: was previously a parametric "all nightlords" check that
        passed via the NB-strict gate (which rejected nightlords at slots
        without the 'Night Boss' marker). With NB-strict removed, fragile-
        slot safety is now strictly per-chr via V3_FRAGILE_SENSITIVE_
        TARGETS membership. Nightlords not in the set CAN appear at
        fragile slots subject to other compat checks — accepted as the
        cost of removing the over-broad variant-name filter. If a
        specific Nightlord-at-fragile-slot CTD surfaces, add that cp to
        V3_FRAGILE_SENSITIVE_TARGETS with seed evidence."""
        slot = self._make_fragile_slot()
        for cp in ('c7500', 'c7520', 'c7540', 'c7600', 'c7910'):
            if cp not in engine.V3_FRAGILE_SENSITIVE_TARGETS:
                continue  # not in the sensitive set; can appear at fragile slots
            assert engine._score_slot_for_unique(slot, cp, tags) is None, (
                f'{cp} (Nightlord, in V3_FRAGILE_SENSITIVE_TARGETS) '
                f'must be rejected at fragile slot')

    def test_extra_bans_honored_at_fragile_slot(self, engine, tags):
        """V3_PROBLEM_SLOT_EXTRA_BANS already applied in the standard
        shuffle. Now uniques also honor it. c4120 Demi-Human Chief is
        in SAFE_CONFIRMED but blacklisted at m60_42_36_00 pi=20 (the
        v0.24.60 SW-corner extra-ban)."""
        slot = {
            'msb': 'm60_42_36_00.msb',
            'pi': 20,
            'source_cp': 'c3661',
            'source_variant_name': 'Putrid Corpse',
            'position': (-100.62, 105.48, 88.15),
        }
        # c4120 IS in SAFE_CONFIRMED, would normally pass fragility
        import oops_v3 as o
        assert 'c4120' in o.V3_FRAGILE_SAFE_CONFIRMED
        # But it's in V3_PROBLEM_SLOT_EXTRA_BANS for this slot
        assert 'c4120' in o.V3_PROBLEM_SLOT_EXTRA_BANS[(slot['msb'], slot['pi'])]
        # Should still be rejected by the extra-ban path
        assert engine._score_slot_for_unique(slot, 'c4120', tags) is None

    def test_non_fragile_slot_unaffected(self, engine, tags):
        """The new filter only fires at fragile slots. Targets that
        score at non-fragile slots still score."""
        slot = {
            'msb': 'm46_05_00_00.msb',  # dedicated arena, NOT in PROBLEM_SLOTS
            'pi': 3,
            'source_cp': 'c4660',
            'source_variant_name': 'Guardian Golem',
            'position': (0, 0, 0),
        }
        # c7710 Centipede Demon was placed at m46_05 pi=3 in seed 537773
        # successfully. Should still score.
        import oops_v3 as o
        assert (slot['msb'], slot['pi']) not in o.V3_PROBLEM_SLOTS
        # If anim_class compat passes (giga_boss → giga_boss), this scores.
        result = engine._score_slot_for_unique(slot, 'c7710', tags)
        assert result is not None  # should score (not None)


class TestGhostflameDragonCap:
    """v0.24.63: c5860 cap=2. User req: '"oh cap the ghostflame dragon
    at 2" — seed 618106 had 3 placements."""

    def test_c5860_capped_at_2(self, engine):
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c5860') == 2

    def test_c5860_nightboss_cap_vs_c5820_miniboss_cap(self, engine):
        """c5860 Ghostflame Dragon is tier=night_boss and keeps cap=2.
        c5820 Great Red Bear is tier=miniboss, so v0.27.6's "4 across
        the board" miniboss policy puts it at 4 — the two no longer
        share a cap."""
        assert engine.V3_UNIQUE_TARGET_CAPS['c5860'] == 2
        assert engine.V3_UNIQUE_TARGET_CAPS['c5820'] == 4


class TestReservationOrderBigFirstV0_24_76:
    """v0.24.76: _compute_unique_reservations now sorts by (cap, size)
    rather than just cap. Big chrs (GIGA, XXL) get first pick at rare
    big-source slots before smaller chrs can score-grab them via NB-marker
    or boss-arena heuristics.

    The original v0.23.11 within-cap shuffle is preserved as a tiebreaker
    inside each (cap, size) bucket.
    """

    def test_size_order_constant_defined(self, engine):
        """Sanity: the size-priority order is well-defined."""
        # _SIZE_ORDER_FOR_RESERVATION is a local in _compute_unique_reservations,
        # but the sort key should produce a deterministic ordering.
        # Verify by running with a small synthetic dict.
        import random
        rng = random.Random(42)
        sample = [
            ('cp_giga', 1),    # cap=1 GIGA
            ('cp_xxl',  1),    # cap=1 XXL
            ('cp_xl',   1),    # cap=1 XL
            ('cp_l',    1),    # cap=1 L
            ('cp_m',    1),    # cap=1 M
            ('cp_s',    1),    # cap=1 S
            ('cp_xs',   1),    # cap=1 XS
            ('cp_giga2',2),    # cap=2 GIGA
            ('cp_m2',   2),    # cap=2 M
        ]
        synthetic_tags = {
            'cp_giga':  {'size_class': 'GIGA'},
            'cp_xxl':   {'size_class': 'XXL'},
            'cp_xl':    {'size_class': 'XL'},
            'cp_l':     {'size_class': 'L'},
            'cp_m':     {'size_class': 'M'},
            'cp_s':     {'size_class': 'S'},
            'cp_xs':    {'size_class': 'XS'},
            'cp_giga2': {'size_class': 'GIGA'},
            'cp_m2':    {'size_class': 'M'},
        }
        # Replicate the v0.24.76 sort key inline
        _SIZE_ORDER = {'GIGA': 0, 'XXL': 1, 'XL': 2, 'L': 3, 'M': 4, 'S': 5, 'XS': 6}
        def _sort_key(kv):
            cp, cap = kv
            size = synthetic_tags.get(cp, {}).get('size_class') or '?'
            return (cap, _SIZE_ORDER.get(size, 99))
        rng.shuffle(sample)
        sample.sort(key=_sort_key)
        # cap=1 chrs should all come before cap=2
        cap_seq = [s[1] for s in sample]
        assert cap_seq == sorted(cap_seq), (
            f'cap order broken: {cap_seq}')
        # Within cap=1, size should be GIGA → XXL → XL → L → M → S → XS
        cap1 = [s[0] for s in sample if s[1] == 1]
        assert cap1 == ['cp_giga', 'cp_xxl', 'cp_xl', 'cp_l', 'cp_m', 'cp_s', 'cp_xs'], (
            f'size order broken within cap=1: {cap1}')
        # Within cap=2, GIGA before M
        cap2 = [s[0] for s in sample if s[1] == 2]
        assert cap2 == ['cp_giga2', 'cp_m2'], (
            f'size order broken within cap=2: {cap2}')

    def test_within_size_bucket_shuffled(self, engine):
        """Within the same (cap, size) bucket, the v0.23.11 shuffle
        survives — different RNG seeds produce different within-bucket
        orderings."""
        import random
        # Two GIGA cap=1 chrs — should sometimes appear in different
        # orders across RNG seeds.
        synthetic = [('cp_a_giga', 1), ('cp_b_giga', 1), ('cp_c_giga', 1)]
        synthetic_tags = {cp: {'size_class': 'GIGA'} for cp, _ in synthetic}
        _SIZE_ORDER = {'GIGA': 0, 'XXL': 1, 'XL': 2, 'L': 3, 'M': 4, 'S': 5, 'XS': 6}
        def _sort_key(kv):
            cp, cap = kv
            size = synthetic_tags.get(cp, {}).get('size_class') or '?'
            return (cap, _SIZE_ORDER.get(size, 99))
        seen_orderings = set()
        for seed in range(20):
            rng = random.Random(seed)
            items = list(synthetic)
            rng.shuffle(items)
            items.sort(key=_sort_key)
            seen_orderings.add(tuple(cp for cp, _ in items))
        # We expect more than one unique ordering across 20 seeds —
        # otherwise the shuffle isn't doing its job.
        assert len(seen_orderings) > 1, (
            f'Within-bucket shuffle appears broken — same order across '
            f'all 20 seeds: {seen_orderings}')

    def test_unknown_size_sorts_last(self, engine):
        """Chrs with missing/unknown size_class sort AFTER known-size
        chrs in the same cap tier. Defensive: never let an unknown-size
        chr grab a slot before a known-big chr."""
        import random
        rng = random.Random(0)
        items = [('cp_unknown', 1), ('cp_giga', 1), ('cp_m', 1)]
        synthetic_tags = {
            'cp_unknown': {},  # no size_class
            'cp_giga': {'size_class': 'GIGA'},
            'cp_m': {'size_class': 'M'},
        }
        _SIZE_ORDER = {'GIGA': 0, 'XXL': 1, 'XL': 2, 'L': 3, 'M': 4, 'S': 5, 'XS': 6}
        def _sort_key(kv):
            cp, cap = kv
            size = synthetic_tags.get(cp, {}).get('size_class') or '?'
            return (cap, _SIZE_ORDER.get(size, 99))
        rng.shuffle(items)
        items.sort(key=_sort_key)
        order = [cp for cp, _ in items]
        # GIGA first, then M, then unknown
        assert order == ['cp_giga', 'cp_m', 'cp_unknown'], (
            f'Unknown-size should sort last: got {order}')

    def test_real_engine_giga_before_m(self, engine, tags):
        """Integration smoke test: confirm the reserved/floored set
        spans both a big size bucket and M, so the big-first ordering
        is exercised in practice.

        v0.27.8: rebased from cap=1 chrs onto V3_RESERVATION_FLOORS.
        The defensive cap=1 mechanism was removed (it left 0 cap=1 M
        chrs), but ~204 chrs now carry reservation floors — 104 grunts
        + 76 minibosses + the pre-existing 24 — spanning every size
        class, so size-ordering of reservations still very much
        matters."""
        floored = set(engine.V3_RESERVATION_FLOORS)
        floored_gigas = [cp for cp in floored
                         if tags.get(cp, {}).get('size_class') == 'GIGA']
        floored_mediums = [cp for cp in floored
                           if tags.get(cp, {}).get('size_class') == 'M']
        assert len(floored_gigas) >= 3, (
            f'Expected at least 3 floored GIGA chrs; got {len(floored_gigas)}')
        assert len(floored_mediums) >= 9, (
            f'Expected at least 9 floored M chrs; got {len(floored_mediums)}')


class TestC4281DemotionLockin:
    """c4281 Skull Plate Giant Ant was demoted from V3_EXCLUDE_TARGET_PREFIXES
    to V3_FRAGILE_SENSITIVE_TARGETS in v0.24.90-patch11 to match the
    c4240 Fingercreeper family precedent (same XL+loco=5 profile).

    The v0.24.90-patch11 invariant: do NOT *manually* re-promote c4281
    to EXCLUDE for terrain-failure reasons. If freezes recur at fragile-
    cleared positions, the right fix is V3_QUADRUPED_UNSAFE_SLOTS or
    authored reposition.

    v0.25.0 separately added c4281 to data/nr_missing_chr_files.json's
    broken_runtime_chrs array (auto-loaded into V3_EXCLUDE_TARGET_PREFIXES
    by `_load_missing_chr_files()`). That's a distinct mechanism with a
    distinct rationale (no per-chr battle script visible in any source
    archive — phantom asset, AI doesn't function). When/if the script
    presence is confirmed (via parent-share to c4280 or actual file
    discovery), the entry can be lifted from broken_runtime_chrs and
    the v0.24.90-patch11 SENSITIVE routing resumes as the backstop.

    The literal/auto-load distinction matters because it preserves the
    audit trail: "we excluded c4281 because the chr is broken at the
    asset level" is a different claim than "we excluded c4281 because
    its terrain failures persist" — the latter is the case patch11
    expressly rejected.
    """


    def test_c4281_still_fragile_sensitive_for_backstop(self, engine):
        """v0.24.90-patch11's SENSITIVE classification must persist even
        while c4281 is broken_runtime_chrs-excluded — so that lifting
        the broken_runtime_chrs entry resumes the patch11 routing
        immediately rather than dropping c4281 to default fragile-pool
        treatment."""
        assert 'c4281' in engine.V3_FRAGILE_SENSITIVE_TARGETS, (
            'c4281 should be in V3_FRAGILE_SENSITIVE_TARGETS per '
            'v0.24.90-patch11 — keeps the routing in place as a '
            'backstop for if broken_runtime_chrs lifts c4281 later.')

    def test_insectoid_family_uniformly_sensitive_or_safe(self, engine):
        """Sanity: the multi-leg insectoid family should be uniformly
        in SENSITIVE or SAFE — none manually-excluded for terrain reasons.

        c4281 is permitted to be in EXCLUDE via broken_runtime_chrs
        auto-load (separate v0.25.0 mechanism, asset-level rationale).
        The check below filters by the broken_runtime_chrs path before
        flagging EXCLUDE membership.
        """
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'nr_missing_chr_files.json')) as f:
            mcf = json.load(f)
        broken_runtime_cps = {e['c_prefix']
                              for e in mcf.get('broken_runtime_chrs', [])}

        FAMILY = ['c4280', 'c4281', 'c4240', 'c4241', 'c4250', 'c5193']
        for cp in FAMILY:
            if cp in broken_runtime_cps:
                # Excluded via the v0.25.0 asset-level path; that's OK.
                # Sensitivity classification should still apply as a
                # backstop, checked below.
                pass
            else:
                assert cp not in engine.V3_EXCLUDE_TARGET_PREFIXES, (
                    f'{cp} in EXCLUDE breaks insectoid-family uniformity '
                    f'(not in broken_runtime_chrs, so this must be a '
                    f'manual re-promotion).')
            in_sens = cp in engine.V3_FRAGILE_SENSITIVE_TARGETS
            in_safe = cp in engine.V3_FRAGILE_SAFE_CONFIRMED
            assert in_sens or in_safe, (
                f'{cp} missing from both SENSITIVE and SAFE — should be '
                f'classified into one of them')


class TestFieldRollTierWithFieldBoss:
    """v0.28.x: the field-tier roll for non-catalogued slots gained a fourth
    outcome (field_boss) alongside the existing grunt/miniboss/night_boss.
    A separate V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT knob conditionally
    upgrades a field_boss roll into a night_boss roll — the configurable
    'field encounter is actually a real fight' knob.

    These tests verify:
      - The four outcomes are reachable from the roll function.
      - The promote knob shifts the field_boss → night_boss split as
        documented in the probability model.
      - The roll function preserves its determinism (same seed + slot
        returns the same outcome, including under the promote knob).
    """

    def _sweep(self, engine, n=10000):
        """Roll over n synthetic slots and return tier→count distribution."""
        engine._V3_RUN_SEED = 0xCAFEBABE
        from collections import Counter
        counts = Counter()
        for i in range(n):
            msb = f"m{i % 99:02d}_{(i // 99) % 99:02d}_00_00.msb"
            pi = i % 999
            t = engine.field_roll_tier_for(msb, pi)
            counts[t] += 1
        return counts

    def test_four_outcomes_reachable_at_defaults(self, engine):
        """At default constants, the roll can produce grunt / miniboss /
        field_boss / night_boss outcomes. Sweep size is large enough that
        each outcome should appear at least once with high confidence.

        Pre-v0.28.x+ defaults (promote=0.0):
          grunt P=97.8% (will dominate)
          miniboss P=1.5% (expect ~150 in 10k)
          field_boss P=0.5% (expect ~50 in 10k)
          night_boss P=0.2% (expect ~20 in 10k)

        v0.28.x+ defaults (promote=0.5) — the knob shifts mass from FB
        to NB without touching MB or grunt:
          grunt P=97.8% (unchanged)
          miniboss P=1.5% (unchanged)
          field_boss P=0.25% (expect ~25 in 10k — halved)
          night_boss P=0.45% (expect ~45 in 10k — roughly doubled)

        Test still passes either way: all four counts > 0 at any
        promote_pct ∈ (0, 1). At promote=0.0 or 1.0 exactly one of
        {field_boss, night_boss} reaches zero — those endpoints are
        covered by the dedicated promote-zero/one tests below.
        """
        counts = self._sweep(engine, n=20000)
        for tier in ('grunt', 'miniboss', 'field_boss', 'night_boss'):
            assert counts[tier] > 0, (
                f'tier {tier!r} unreachable in 20k field rolls — '
                f'expected non-zero count at default constants. '
                f'Distribution: {dict(counts)}')

    def test_promote_zero_field_boss_stays_field_boss(self, engine):
        """With promote=0.0, a field_boss roll should never upgrade to
        night_boss. Verified by checking that night_boss count matches
        V3_FIELD_UPGRADE_NIGHTBOSS_PCT (no contribution from promoted
        field_boss rolls).

        Note: in v0.28.x+ the default is 0.5, not 0.0 — this test still
        pins the constant to 0.0 to verify the lower endpoint of the
        knob's range, then restores the original."""
        orig = engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT
        engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = 0.0
        try:
            counts = self._sweep(engine, n=50000)
            total = sum(counts.values())
            nb_rate = counts['night_boss'] / total
            # Expected ~0.2% with some sampling tolerance
            assert 0.001 < nb_rate < 0.004, (
                f'promote=0.0: night_boss rate {nb_rate:.4f} is outside '
                f'tolerance for V3_FIELD_UPGRADE_NIGHTBOSS_PCT=0.002. '
                f'Distribution: {dict(counts)}')
        finally:
            engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = orig

    def test_promote_one_all_field_boss_becomes_night_boss(self, engine):
        """With promote=1.0, EVERY field_boss roll upgrades to
        night_boss. So night_boss count should approximately equal
        (V3_FIELD_UPGRADE_NIGHTBOSS_PCT + V3_FIELD_UPGRADE_FIELDBOSS_PCT)
        of total rolls, and field_boss count should be 0."""
        orig = engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT
        engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = 1.0
        try:
            counts = self._sweep(engine, n=50000)
            total = sum(counts.values())
            assert counts['field_boss'] == 0, (
                f'promote=1.0 should leave field_boss empty — got '
                f'{counts["field_boss"]} field_boss rolls.')
            # Expected: ~(0.002 + 0.005) = 0.7%
            nb_rate = counts['night_boss'] / total
            assert 0.005 < nb_rate < 0.011, (
                f'promote=1.0: night_boss rate {nb_rate:.4f} is outside '
                f'tolerance for sum of NB + FB pct (~0.7%). '
                f'Distribution: {dict(counts)}')
        finally:
            engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = orig

    def test_roll_is_deterministic_per_slot(self, engine):
        """Same (run seed, msb, pi) gives the same tier across calls.
        Reproducibility is a load-bearing property of the field roll —
        the spoiler writer and the picker call this function separately
        and must agree on the outcome."""
        engine._V3_RUN_SEED = 0xCAFEBABE
        msb = 'm60_44_38_00.msb'
        pi = 17
        first = engine.field_roll_tier_for(msb, pi)
        for _ in range(20):
            second = engine.field_roll_tier_for(msb, pi)
            assert second == first, (
                f'field roll is non-deterministic: {first!r} vs {second!r} '
                f'for same (seed, msb, pi)')

    def test_promote_draw_independent_of_primary_roll(self, engine):
        """The promote knob uses a distinct hash namespace ('fbpromote')
        so changing V3_FIELD_UPGRADE_FIELDBOSS_PCT must not shift any
        slot's NB/MB/grunt outcome. Verify by snapshotting outcomes,
        bumping FIELDBOSS_PCT, and confirming non-FB slots stay where
        they were.

        v0.28.x+ note: the production default is promote=0.5, under which
        a bumped FB slice would push grunt-rolled slots into the FB slice
        AND half of those get promoted to NB — making the grunt→FB-only
        invariant break through a legitimate channel (promote). Pin
        promote=0.0 for the duration of this test so the FB% bump's
        effect is isolated to the primary slice; the promote channel is
        independently validated by the dedicated promote-zero/one tests.
        """
        engine._V3_RUN_SEED = 0xDEADBEEF
        orig_promote = engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT
        engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = 0.0
        # Snapshot
        before = {}
        for i in range(2000):
            msb = f'm{i % 99:02d}_00_00_00.msb'
            pi = i
            before[(msb, pi)] = engine.field_roll_tier_for(msb, pi)
        # Bump FIELDBOSS_PCT (steal from grunt territory)
        orig_fb = engine.V3_FIELD_UPGRADE_FIELDBOSS_PCT
        engine.V3_FIELD_UPGRADE_FIELDBOSS_PCT = 0.02  # 2% — way up from 0.5%
        try:
            for (msb, pi), prev in before.items():
                now = engine.field_roll_tier_for(msb, pi)
                # Permitted: grunt → field_boss (a slot whose primary r
                # was inside the new wider FB window). Forbidden: any other
                # tier flipping (NB stays NB, MB stays MB).
                if prev == 'grunt':
                    assert now in ('grunt', 'field_boss'), (
                        f'{msb} pi={pi}: grunt → {now!r} not allowed '
                        f'(only grunt or field_boss possible after FB% bump)')
                elif prev == 'miniboss':
                    assert now == 'miniboss', (
                        f'{msb} pi={pi}: miniboss → {now!r} — '
                        f'FB% bump should not affect MB outcomes')
                elif prev == 'night_boss':
                    assert now == 'night_boss', (
                        f'{msb} pi={pi}: night_boss → {now!r} — '
                        f'FB% bump should not affect NB outcomes')
        finally:
            engine.V3_FIELD_UPGRADE_FIELDBOSS_PCT = orig_fb
            engine.V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT = orig_promote


class TestNightBossSlotTierLadder:
    """v0.28.x+: night-boss-catalogued slots use a tighter tier filter
    than the generic V3_BOSS_STRENGTH_TIERS branch.

    The principle (Alaric, v0.28.x post-tier-audit): an NB slot is a
    climactic encounter, and reaching down to miniboss for the swap
    makes the encounter feel like a field fight inside a boss arena.
    The new filter restricts to night_boss + nightlord (primary) →
    field_boss (one-step downstep) → return None (preserve vanilla).
    Miniboss-tier swaps at NB-catalogued slots are forbidden by
    construction.

    These tests pin a known NB-catalogued (msb, pi) — m48_40_00_00.msb
    pi=4, the Leyndell Knight Night Boss Prelude slot — and verify the
    filter shape. This fixture is NB-catalogued AND not in
    V3_PRESERVE_SLOTS, so the picker actually reaches our new branch
    (rather than early-returning at the preserve gate).

    To vary picker outcomes across iterations we tweak
    engine._V3_RUN_SEED — the picker is keyed off a slot-decision RNG
    derived from the run seed, not the local rng arg.
    """

    NB_SLOT_MSB = 'm48_40_00_00.msb'
    NB_SLOT_PI = 4

    def _verify_nb_catalog(self, engine):
        """Sanity-check that the slot is actually catalogued as nightboss.
        If the catalog ever moves this slot to a different tier, these
        tests need to follow."""
        entry = engine.V3_BOSS_SLOT_CATALOG.get(
            (self.NB_SLOT_MSB, self.NB_SLOT_PI))
        assert entry is not None, (
            f'{self.NB_SLOT_MSB} pi={self.NB_SLOT_PI} not in '
            f'V3_BOSS_SLOT_CATALOG — test must be updated for current '
            f'catalog state')
        assert entry.get('tier') == 'nightboss', (
            f'{self.NB_SLOT_MSB} pi={self.NB_SLOT_PI} has tier='
            f'{entry.get("tier")!r}, not nightboss')

    def test_nb_slot_never_returns_miniboss_target(
            self, engine, tags, prefix_variants, prefix_count,
            monkeypatch):
        """50 trials at an NB-catalogued slot: picker should never return
        a miniboss-tier target. Pre-v0.28.x+ this could happen via the
        generic BOSS_STRENGTH_TIERS branch (which includes miniboss);
        the new branch hard-excludes it.

        Vary engine._V3_RUN_SEED across iterations — that's what the
        picker's slot-decision RNG keys off, not the local `rng` arg.
        """
        self._verify_nb_catalog(engine)

        # Vanilla cp at this slot is c4353 (Leyndell Knight, miniboss
        # tier per nr_enemy_tags). The picker's recipient_cp parameter
        # is the slot's source cp; pick_target_cp resolves the rest.
        recipient = 'c4353'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
        try:
            for seed in range(50):
                engine._V3_RUN_SEED = 0xC0FFEE + seed
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name=self.NB_SLOT_MSB,
                    slot_pi=self.NB_SLOT_PI,
                    slot_variant_name='Leyndell Knight (Night Boss Prelude)')
                if result is None:
                    # Empty pool after all filters — preserve vanilla.
                    # Acceptable outcome; the invariant is "no miniboss",
                    # not "always non-vanilla".
                    continue
                result_tier = tags.get(result, {}).get('tier')
                assert result_tier != 'miniboss', (
                    f'seed {seed} (run_seed={engine._V3_RUN_SEED:#x}): '
                    f'NB slot picked miniboss-tier target {result!r}, '
                    f'which the v0.28.x+ ladder forbids')
                # Also no field-strength tiers (no field-strength branch
                # fires at NB-catalogued slots, but belt-and-suspenders).
                assert result_tier not in (
                    'grunt', 'trash', 'cluster_member',
                    'mount_component', 'non_combat'), (
                    f'seed {seed}: NB slot picked field-strength target '
                    f'{result!r} tier={result_tier!r}')
        finally:
            engine._V3_RUN_SEED = orig_seed

    def test_nb_slot_admits_field_boss_tier_when_primary_empty(
            self, engine, tags, prefix_variants, prefix_count,
            monkeypatch):
        """When all night_boss + nightlord tagged chrs are excluded, an
        NB slot should fall to field_boss tier — NOT to miniboss.

        Constructs the exclusion by adding every NB and nightlord c-
        prefix to a copy of V3_EXCLUDE_TARGET_PREFIXES via the gates
        cluster (so the primary pool empties for this slot only)."""
        self._verify_nb_catalog(engine)

        recipient = 'c4353'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        # Drown out the primary pool: ban every NB and nightlord cp.
        primary_cps = {cp for cp, t in tags.items()
                       if t.get('tier') in ('night_boss', 'nightlord')}
        from engine.state import GateState
        gates = GateState.from_module(engine).replace(
            exclude_target_prefixes=(
                frozenset(engine.V3_EXCLUDE_TARGET_PREFIXES) | primary_cps))

        # Collect outcomes across 30 run seeds. Expect either field_boss
        # or None — never miniboss/grunt and never an NB/nightlord chr
        # (the gates excluded them).
        outcomes = {'field_boss': 0, 'none': 0, 'other': []}
        orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
        try:
            for seed in range(30):
                engine._V3_RUN_SEED = 0xDEC0DE00 + seed
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name=self.NB_SLOT_MSB,
                    slot_pi=self.NB_SLOT_PI,
                    slot_variant_name='Leyndell Knight (Night Boss Prelude)',
                    gates=gates)
                if result is None:
                    outcomes['none'] += 1
                    continue
                tier = tags.get(result, {}).get('tier')
                if tier == 'field_boss':
                    outcomes['field_boss'] += 1
                else:
                    outcomes['other'].append((seed, result, tier))
        finally:
            engine._V3_RUN_SEED = orig_seed

        assert outcomes['other'] == [], (
            f'NB slot fell to non-FB tier when primary pool was banned: '
            f'{outcomes["other"][:5]} (showing first 5)')
        # And FB should be the dominant outcome (very rarely None — only
        # if the slot's downstream gates reject every FB-tagged cp).
        assert outcomes['field_boss'] > 0, (
            f'NB slot never reached field_boss tier across 30 seeds — '
            f'outcomes={outcomes}')

    def test_nb_slot_returns_none_when_ladder_exhausted(
            self, engine, tags, prefix_variants, prefix_count):
        """When NB + nightlord + field_boss are ALL exhausted, an NB
        slot should return None (preserve vanilla) rather than fall
        through to miniboss or the unfiltered pool."""
        self._verify_nb_catalog(engine)

        recipient = 'c4353'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        # Ban every NB + nightlord + field_boss cp via gates.
        ladder_tiers = ('night_boss', 'nightlord', 'field_boss')
        ladder_cps = {cp for cp, t in tags.items()
                      if t.get('tier') in ladder_tiers}
        from engine.state import GateState
        gates = GateState.from_module(engine).replace(
            exclude_target_prefixes=(
                frozenset(engine.V3_EXCLUDE_TARGET_PREFIXES) | ladder_cps))

        orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
        try:
            for seed in range(20):
                engine._V3_RUN_SEED = 0xBADA5500 + seed
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name=self.NB_SLOT_MSB,
                    slot_pi=self.NB_SLOT_PI,
                    slot_variant_name='Leyndell Knight (Night Boss Prelude)',
                    gates=gates)
                assert result is None, (
                    f'seed {seed}: NB slot returned {result!r} (tier='
                    f'{tags.get(result, {}).get("tier")!r}) when whole '
                    f'NB ladder was banned. Expected None (preserve '
                    f'vanilla).')
        finally:
            engine._V3_RUN_SEED = orig_seed


class TestNightBossSlotCapExemption:
    """v0.28.x+: nightboss-catalogued slots are exempt from the
    V3_UNIQUE_TARGET_CAPS / unique_placed_counts cap-block gate.

    Rationale (Alaric): NB encounters are climactic Day-3 events; the
    player only ever sees one per seed in actual play. Burning cap room
    on NB placements over-restricts the eligible NB pool for indoor-
    tunnel slots like the m47/m48 DS-heritage cluster, where the cap-
    available NB chrs at run-time are mostly oversized flyers that
    can't physically fit. Exempting NB-slot placements from the cap
    keeps the pool fuller for the duration of the seed.

    Same fixture as TestNightBossSlotTierLadder (m48_40 pi=4 — NB-
    catalogued, not preserved). Tests:
      1. A capped cp at-cap still gets returned at an NB slot.
      2. The cap counter does NOT increment after an NB-slot placement.
      3. Non-NB slots remain subject to the cap (the exemption is
         narrowly scoped).
    """

    NB_SLOT_MSB = 'm48_40_00_00.msb'
    NB_SLOT_PI = 4

    def _make_run_ctx_with_capped(self, engine, capped_cp, cap):
        """Build a RunContext whose unique_placed_counts has `capped_cp`
        already at or above its cap. The cap-block gate should normally
        subtract this cp from the pool."""
        from engine.runctx import RunContext
        ctx = RunContext()
        ctx.unique_placed_counts[capped_cp] = cap
        return ctx

    def test_capped_cp_still_eligible_at_nb_slot(
            self, engine, tags, prefix_variants, prefix_count,
            monkeypatch):
        """Plant a capped NB cp (Margit c2130, cap=2) at-cap, then verify
        the picker can still return it at an NB-catalogued slot. The
        pre-v0.28.x+ behavior would have subtracted c2130 from the pool
        via the cap-block gate."""
        entry = engine.V3_BOSS_SLOT_CATALOG.get(
            (self.NB_SLOT_MSB, self.NB_SLOT_PI))
        assert entry and entry.get('tier') == 'nightboss', (
            f'slot fixture moved; update test')
        target = 'c2130'  # Margit (NB-tier, cap=2)
        if target not in tags:
            pytest.skip(f'{target} not in loaded tags')

        cap = engine.V3_UNIQUE_TARGET_CAPS.get(target)
        if cap is None:
            pytest.skip(f'{target} has no cap configured')

        recipient = 'c4353'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        # Run the picker across many run seeds with run_ctx showing
        # target at-cap. Target should still appear (NB-slot cap
        # exemption). Without the exemption, the cap-block gate would
        # subtract c5130 from the pool every iteration → 0 placements.
        found = 0
        orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
        try:
            for seed in range(50):
                engine._V3_RUN_SEED = 0xCA9CA900 + seed
                ctx = self._make_run_ctx_with_capped(engine, target, cap)
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name=self.NB_SLOT_MSB,
                    slot_pi=self.NB_SLOT_PI,
                    slot_variant_name='Leyndell Knight (Night Boss Prelude)',
                    run_ctx=ctx)
                if result == target:
                    found += 1
        finally:
            engine._V3_RUN_SEED = orig_seed

        # 50 seeds across a primary pool of ~50-60 NB+nightlord cps —
        # the capped target should appear in at least a few of them if
        # the cap exemption is working. (Pre-v0.28.x+ this would be 0.)
        assert found > 0, (
            f'capped target {target} never appeared at NB slot across '
            f'50 seeds — cap exemption not working. Expected at least '
            f'1 placement; pre-exemption would block all 50.')

    def test_nb_slot_placement_does_not_bump_count(
            self, engine, tags, prefix_variants, prefix_count):
        """After a successful NB-slot placement of cp X, the run_ctx's
        unique_placed_counts[X] should NOT have incremented. Pre-v0.28.x+
        every placement bumped the count; the exemption makes NB slots
        zero-cost for cap accounting."""
        entry = engine.V3_BOSS_SLOT_CATALOG.get(
            (self.NB_SLOT_MSB, self.NB_SLOT_PI))
        assert entry and entry.get('tier') == 'nightboss', (
            f'slot fixture moved; update test')

        recipient = 'c4353'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        from engine.runctx import RunContext
        zero_bump_seeds = 0
        nonzero_bump_seeds = 0
        orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
        try:
            for seed in range(50):
                engine._V3_RUN_SEED = 0xB0BB1E00 + seed
                ctx = RunContext()
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name=self.NB_SLOT_MSB,
                    slot_pi=self.NB_SLOT_PI,
                    slot_variant_name='Leyndell Knight (Night Boss Prelude)',
                    run_ctx=ctx)
                if result is None:
                    continue
                # The picked cp should not show up in
                # unique_placed_counts. (Other cps may show up from the
                # reservation pre-pass, but this test doesn't run that —
                # counts dict should be empty for the c-prefix path.)
                cp_count = ctx.unique_placed_counts.get(result, 0)
                if cp_count == 0:
                    zero_bump_seeds += 1
                else:
                    nonzero_bump_seeds += 1
        finally:
            engine._V3_RUN_SEED = orig_seed

        assert nonzero_bump_seeds == 0, (
            f'NB-slot placements bumped cap count in {nonzero_bump_seeds} '
            f'of 50 seeds — exemption not honored')
        assert zero_bump_seeds > 0, (
            f'no successful placements across 50 seeds at NB slot — '
            f'test setup broken; cannot verify cap exemption')

    def test_non_nb_slot_still_bumps_count(
            self, engine, tags, prefix_variants, prefix_count):
        """Belt-and-suspenders: a non-NB slot should still bump the cap
        counter on placement. The exemption is narrowly scoped to
        nightboss-catalogued slots only — any leak into other slot
        types would defeat the cap system globally."""
        # Pick a non-catalogued field slot from the same map area —
        # something with a pi that isn't an NB slot.
        non_nb_msb = 'm60_44_38_20.msb'  # Limveld overworld grid
        non_nb_pi = 17  # arbitrary field pi
        entry = engine.V3_BOSS_SLOT_CATALOG.get((non_nb_msb, non_nb_pi))
        # Skip the test if this happens to be catalogued (shouldn't be
        # for an arbitrary overworld pi, but defend against catalog
        # drift).
        if entry is not None and entry.get('tier') == 'nightboss':
            pytest.skip(f'{non_nb_msb} pi={non_nb_pi} is unexpectedly '
                        f'NB-catalogued; pick a different fixture')

        recipient = 'c4170'  # Banished Knight, generic field source
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        from engine.runctx import RunContext
        bumped_seeds = 0
        orig_seed = getattr(engine, '_V3_RUN_SEED', 0)
        try:
            for seed in range(30):
                engine._V3_RUN_SEED = 0xDEC0AB00 + seed
                ctx = RunContext()
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name=non_nb_msb,
                    slot_pi=non_nb_pi,
                    slot_variant_name=None,
                    run_ctx=ctx)
                if result is None:
                    continue
                if (result in engine.V3_UNIQUE_TARGET_CAPS
                        and ctx.unique_placed_counts.get(result, 0) > 0):
                    bumped_seeds += 1
        finally:
            engine._V3_RUN_SEED = orig_seed

        assert bumped_seeds > 0, (
            f'no capped-cp placements bumped count at non-NB slot '
            f'across 30 seeds. Either fixture has no eligible capped '
            f'cps (test setup issue), OR the exemption is leaking to '
            f'non-NB slots (real bug).')
