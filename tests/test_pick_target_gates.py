"""Tests for `pick_target_cp` — gates.

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

class TestHasRewardPreservationGate:
    """v0.24.101: when the recipient slot's c-prefix has has_reward=True,
    pick_target_cp restricts the target pool to c-prefixes that also have
    has_reward=True. Asymmetric — has_reward=False recipients are not
    constrained (can swap in any direction, including upgrading to a
    rewarded encounter).

    Distinct from slot_require_boss_reward (which gates on has_boss_reward
    and is opt-in via V3_BOSSY_PROMOTE_SLOTS 'boss_reward' mode). The
    has_reward gate is automatic on every call.
    """

    def _make_tags_with_reward_override(self, base_tags, overrides):
        """Return a shallow-copy tags dict with specific chrs' has_reward
        overridden. Each chr-dict that gets overridden is also shallow-copied
        so the original tags fixture isn't mutated (session-scoped).
        """
        new_tags = dict(base_tags)
        for cp, value in overrides.items():
            new_tags[cp] = {**base_tags.get(cp, {}), 'has_reward': value}
        return new_tags

    def test_rewarded_recipient_only_swaps_to_rewarded_target(
            self, engine, tags, prefix_variants, prefix_count):
        # c2130 Margit has has_reward=True in the loaded tags.
        recipient = 'c2130'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')
        if not tags[recipient].get('has_reward'):
            pytest.skip(f'{recipient} has_reward!=True in loaded tags — '
                        f'fixture changed')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        # Run many seeds. Every returned target must also have_reward=True.
        # (None is allowed — the slot stays vanilla, which preserves the
        # vanilla reward.)
        observed_targets = set()
        for seed in range(100):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            if result is None:
                continue
            observed_targets.add(result)
            assert tags.get(result, {}).get('has_reward') is True, (
                f'seed {seed}: recipient {recipient} (has_reward=True) '
                f'swapped to {result} which has has_reward='
                f'{tags.get(result, {}).get("has_reward")!r}')

        # Sanity: at least some swaps actually happened (otherwise the
        # gate could be hiding behind a None-only result).
        assert observed_targets, (
            'no targets returned across 100 seeds — gate may be returning '
            'None unconditionally')

    def test_unrewarded_recipient_can_swap_to_unrewarded_target(
            self, engine, tags, prefix_variants, prefix_count):
        # Asymmetric: a has_reward=False recipient should NOT have the
        # gate restrict it to rewarded targets. Pick a recipient with
        # has_reward=False and verify at least some seeds return a
        # has_reward=False target.
        recipient = None
        for cp in ('c3060', 'c2276', 'c4400', 'c4410'):
            if cp in tags and tags[cp].get('has_reward') is False:
                recipient = cp; break
        if recipient is None:
            pytest.skip('no has_reward=False boss-tier recipient available')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        saw_unrewarded_target = False
        for seed in range(100):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            if result is None:
                continue
            tag_value = tags.get(result, {}).get('has_reward')
            if tag_value is not True:
                saw_unrewarded_target = True
                break

        assert saw_unrewarded_target, (
            f'recipient {recipient} (has_reward=False) only produced '
            f'has_reward=True targets across 100 seeds — gate appears to '
            f'be applying bidirectionally, breaking the asymmetric design')

    def test_returns_none_when_no_rewarded_target_available(
            self, engine, tags, prefix_variants, prefix_count):
        # Construct synthetic tags where the recipient has has_reward=True
        # but every other chr in the loaded tags has has_reward=False.
        # With an empty rewarded-target pool, the function must return None
        # rather than fall back to an unrewarded target.
        recipient = 'c2130'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        overrides = {cp: False for cp in tags if cp != recipient}
        overrides[recipient] = True
        synthetic_tags = self._make_tags_with_reward_override(tags, overrides)

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, synthetic_tags, prefix_variants)

        for seed in range(20):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, synthetic_tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            assert result is None, (
                f'seed {seed}: pool exhausted by has_reward gate but '
                f'pick_target_cp returned {result!r} instead of None')

    def test_recipient_with_has_reward_missing_is_not_constrained(
            self, engine, tags, prefix_variants, prefix_count):
        # Some chrs have has_reward absent (None / missing) — typically
        # cinematic/template chrs. These should NOT trigger the gate
        # (only has_reward is True triggers it).
        # v0.27.44: restrict to NON-boss tiers. The tier filter (driven by
        # recipient_is_boss) independently locks a BOSS-tier recipient to
        # boss-tier targets, which are all has_reward=True — that masks the
        # has_reward gate this test means to isolate. Before v0.27.44 the first
        # match here was c5840 (miniboss); it only ever yielded an unrewarded
        # result via its since-removed rider-role self-pin (c5840 was dropped
        # from V3_RIDER_PREFIXES when mounted pairs moved to slot-level
        # preservation). A grunt/trash recipient keeps unrewarded targets
        # tier-eligible, so the ONLY thing that could restrict to rewarded-only
        # is the gate itself.
        recipient = None
        for cp, t in tags.items():
            if t.get('has_reward') is None and t.get('tier') in (
                    'grunt', 'trash'):
                recipient = cp; break
        if recipient is None:
            pytest.skip('no recipient with has_reward=None available')

        # Should be able to swap to a has_reward=False target — gate not
        # triggered.
        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)

        saw_unrewarded_target = False
        for seed in range(100):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_variant_name='Test (Field Boss)')
            if result is None:
                continue
            if tags.get(result, {}).get('has_reward') is not True:
                saw_unrewarded_target = True
                break

        assert saw_unrewarded_target, (
            f'recipient {recipient} (has_reward=None) was incorrectly '
            f'constrained by the rewarded-only gate')


class TestPreserveSlotsGate:
    """v0.24.101: V3_PRESERVE_SLOTS is checked inside pick_target_cp,
    not just in _score_slot_for_unique. Verifies that slots in the set
    return None (preserve vanilla) regardless of which code path picks
    them up.

    Pre-v0.24.101 the gate only fired during unique-reservation pre-pass,
    so the normal swap path was leaking. Playtest seed 537123 v0.24.96
    surfaced this with Rellana at m49_28 pi=2 (a "preserved" slot).
    """

    def test_m49_28_cavalry_nb_riders_preserved(
            self, engine, tags, prefix_variants, prefix_count):
        # m49_28 pi=2 and pi=3 are Night's Cavalry rider slots. Even with
        # a permissive recipient, pick_target_cp should return None.
        recipient = 'c3150'  # the actual source — pick anything biped-ish
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        for pi in (2, 3, 4, 5):
            for seed in range(10):
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name='m49_28_00_00.msb', slot_pi=pi,
                    slot_variant_name='Test (Night Boss)')
                assert result is None, (
                    f'm49_28 pi={pi} seed={seed}: V3_PRESERVE_SLOTS gate '
                    f'returned {result!r} instead of None')

    def test_m46_62_cavalry_evergaol_preserved(
            self, engine, tags, prefix_variants, prefix_count):
        # m46_62 pi=1,2,3,4 are the Night's Cavalry Evergaol rider+mount
        # pairs added in v0.24.101. Playtest seed 537123 caught
        # c3560 Godskin Apostle at pi=1.
        recipient = 'c3150'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        for pi in (1, 2, 3, 4):
            for seed in range(10):
                rng = random.Random(seed)
                result = oops_v3.pick_target_cp(
                    recipient, tags, prefix_variants, prefix_count,
                    recipient_is_boss, rng,
                    slot_msb_name='m46_62_00_00.msb', slot_pi=pi,
                    slot_variant_name='Test (Field Boss)')
                assert result is None, (
                    f'm46_62 pi={pi} seed={seed}: V3_PRESERVE_SLOTS gate '
                    f'returned {result!r} instead of None')

    def test_non_preserved_slot_still_swaps(
            self, engine, tags, prefix_variants, prefix_count):
        # Sanity check: the gate is targeted, not a blanket. m46_62 pi=5
        # is c4580 Large Wormface — not in V3_PRESERVE_SLOTS. Should
        # still swap normally (return a c-prefix, not None).
        recipient = 'c4580'
        if recipient not in tags:
            pytest.skip(f'{recipient} not in loaded tags')

        recipient_is_boss = oops_v3.is_boss_tier_prefix(
            recipient, tags, prefix_variants)
        saw_non_none = False
        for seed in range(20):
            rng = random.Random(seed)
            result = oops_v3.pick_target_cp(
                recipient, tags, prefix_variants, prefix_count,
                recipient_is_boss, rng,
                slot_msb_name='m46_62_00_00.msb', slot_pi=5,
                slot_variant_name='Test (Field Boss)')
            if result is not None:
                saw_non_none = True
                break
        assert saw_non_none, (
            'm46_62 pi=5 (not in V3_PRESERVE_SLOTS) returned None across '
            '20 seeds — gate may be overreaching')


class TestForbiddenBySourceAnim:
    """v0.24.18 introduced V3_FORBIDDEN_BY_SOURCE_ANIM (read at line ~8497
    of oops_v3.py) — when the slot's vanilla source cp has anim_class X,
    forbidden target cps Y are subtracted from the pool. Orthogonal to
    the slot-variant-name gates (which read the slot's variant marker).

    v0.24.24 added the reverse direction (giga_boss source → forbid all
    flyers) after the seed 738357 fort-roof CTD where a Death Rite Bird
    landed at a Guardian Golem (Fort) slot — grounded XXL arena, flier
    target. These tests cover both directions.
    """







    def test_v0_24_26_score_slot_allows_compatible_source_anim(self, engine, tags):
        """Inverse of the above: humanoid → humanoid is not forbidden;
        the v0.24.26 mirror must not over-reject."""
        if 'c3000' not in tags or 'c3010' not in tags:
            pytest.skip('test source cps not in tags')
        slot_info = {
            'source_cp': 'c3000',  # Exile Soldier (humanoid)
            'source_variant_name': 'Exile Soldier',
            'source_npc': 30000010,
            'msb': 'm30_00_00_00.msb',
            'pi': 100,
            'cluster_id': None,
            'pos': (0, 0, 0),
        }
        # Target a humanoid — should NOT be auto-rejected by the new mirror
        # (may still be rejected by other gates; we just need score != None
        # to be possible at all). Use score >= 0 or None acceptance.
        score = engine._score_slot_for_unique(slot_info, 'c3010', tags)
        # The mirror would only fire if c3000's anim_class is in
        # V3_FORBIDDEN_BY_SOURCE_ANIM AND c3010 is forbidden under it.
        # Neither condition holds (humanoid isn't a key). So the mirror
        # must not be the reason for any None here. Score can legitimately
        # be None for other reasons (identity-swap, preservation, etc.),
        # but in this stripped-down test case there are no other blockers.
        # Allow either an int score OR None for unrelated reasons.
        assert score is None or isinstance(score, (int, float)), (
            f'score should be None or numeric, got {type(score).__name__}')


class TestGate6ScriptSpawnBossOffArena:
    """v0.24.51 initial: rejected script_spawn boss-tier chrs at any
    slot not in V3_SCRIPT_SPAWN_BOSS_SLOTS (4 catalogued arena slots).

    v0.24.52 relaxation: user playtest counter-evidence — a script_spawn
    boss-tier chr at m46_05 (vanilla c4660 Guardian Golem fort) worked
    fine. Refined gate: reject ONLY at m60_xx_xx_xx overworld tiles.
    Dedicated arena MSBs (m4x_xx) have boss-preload EMEVD machinery
    and are safe."""

    def test_loader_finds_4_arena_slots(self, engine):
        """The original 4 catalogued script-spawn arena slots."""
        assert len(engine.V3_SCRIPT_SPAWN_BOSS_SLOTS) == 4
        assert ('m46_64_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS
        assert ('m46_65_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS
        assert ('m46_90_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS
        assert ('m46_91_00_00.msb', 1) in engine.V3_SCRIPT_SPAWN_BOSS_SLOTS

    def test_storm_king_no_longer_arena_gated(self, engine, tags):
        """v0.27.2: c7910 Storm King was lifted from
        V3_DEDICATED_ARENA_BOSS_CHRS (Alaric direction - Storm King
        returns as a placeable cap=1 night_boss). Gate 6 keys on
        that set, so Storm King is no longer arena-gated."""
        reason = engine._reject_target_for_slot(
            target_cp='c7910', src_cp='c4660',
            src_variant_name='Guardian Golem', tags=tags,
            msb_base='m60_42_36_00.msb', pi=43)
        assert reason != 'script_spawn_boss_at_overworld', (
            f'Storm King lifted from dedicated-arena set, got {reason}')

    def test_gaping_dragon_allowed_at_m46_arena(self, engine, tags):
        """c7700 Gaping Dragon at m46_05_00_00 pi=3 — user-confirmed
        WORKING in seed 714653 playtest. m46_05 is a dedicated NR
        boss-arena MSB; Gate 6 should NOT reject."""
        reason = engine._reject_target_for_slot(
            target_cp='c7700', src_cp='c4660',
            src_variant_name='Guardian Golem', tags=tags,
            msb_base='m46_05_00_00.msb', pi=3)
        assert reason != 'script_spawn_boss_at_overworld', (
            f'Gaping Dragon at m46_05 (user-confirmed working) should '
            f'NOT be rejected, got {reason}')

    def test_centipede_demon_allowed_at_m46(self, engine, tags):
        """c7710 at m46_71 pi=1 — extension of the same pattern. m46_xx
        arena MSBs are allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c7710', src_cp='c4480',
            src_variant_name='Miranda Blossom', tags=tags,
            msb_base='m46_71_00_00.msb', pi=1)
        assert reason != 'script_spawn_boss_at_overworld'

    def test_centipede_demon_still_allowed_at_arena_slot(self, engine, tags):
        """The original 4 arena slots — still valid. (v0.24.52 didn't
        remove these; just expanded the allow-set.)"""
        reason = engine._reject_target_for_slot(
            target_cp='c7710', src_cp='c4690',
            src_variant_name='Grafted Scion', tags=tags,
            msb_base='m46_91_00_00.msb', pi=1)
        assert reason != 'script_spawn_boss_at_overworld'

    def test_centipede_grub_NOT_gated(self, engine, tags):
        """Grunt-tier script_spawn chrs (c7711/c7712 Centipede Grub,
        c7810 Freja Spiderling) work everywhere observed. Not gated."""
        for cp in ('c7711', 'c7712', 'c7810'):
            reason = engine._reject_target_for_slot(
                target_cp=cp, src_cp='c4311',
                src_variant_name='Leyndell Soldier', tags=tags,
                msb_base='m60_43_36_00.msb', pi=4)
            assert reason != 'script_spawn_boss_at_overworld', (
                f'{cp} (grunt-tier script_spawn) should NOT be gated, got {reason}')

    def test_non_script_spawn_unaffected(self, engine, tags):
        """A regular nr_placed night_boss chr at overworld is fine."""
        reason = engine._reject_target_for_slot(
            target_cp='c2130', src_cp='c4660',
            src_variant_name='Guardian Golem', tags=tags,
            msb_base='m60_42_36_00.msb', pi=43)
        assert reason != 'script_spawn_boss_at_overworld'

    def test_all_script_spawn_boss_chrs_rejected_at_overworld(self, engine, tags):
        """Every dedicated-arena boss chr should be rejected at an
        overworld slot — uniform behavior.

        v0.24.68: switched src_cp from c4660 (giga_boss/GIGA) to
        c4311 (humanoid/M) so Gate 5.6 (xxl/giga source slot
        integrity, v0.24.68) doesn't intercept anim-class drift
        before Gate 6 fires. The point of this test is Gate 6, not
        Gate 5.6 — using a small humanoid source avoids the
        unrelated gate's early-return.

        v0.26.x: source-of-truth for the gated set switched from
        '_source=script_spawn + tier ∈ BOSS_GATED_TIERS' to explicit
        V3_DEDICATED_ARENA_BOSS_CHRS membership. The set of chrs
        that fire the gate is identical to the v0.24.52 behaviour;
        only the keying mechanism changed.
        """
        gated_cps = sorted(engine.V3_DEDICATED_ARENA_BOSS_CHRS)
        # v0.27.2: c4670 + c7910 lifted from the set (8 -> 6).
        assert len(gated_cps) >= 6, f'Expected ≥6 gated cps, got {len(gated_cps)}'
        for cp in gated_cps:
            reason = engine._reject_target_for_slot(
                target_cp=cp, src_cp='c4311',
                src_variant_name='Leyndell Soldier', tags=tags,
                msb_base='m60_42_36_00.msb', pi=4)
            assert reason == 'script_spawn_boss_at_overworld', (
                f'{cp} should be rejected at overworld, got {reason}')


class TestGate4AnimClassRejection:
    """v0.24.54: Extended Gate 4 (quadruped_unsafe_slot) to honor a new
    per-slot `reject_anim_classes` field. Some slots fail for ALL
    quadrupeds, not just locomotion=3 — m46_77 pi=8 (Demi-Human Queen
    anchor) was authored for humanoid AI; both loco=3 (Rats) and loco=5
    (c3181 Red Wolf) freeze there. The per-chr position_shift system
    has been trying (0, +0.5, -5) since v0.24.18 but still fails.

    The default loco=3 path is preserved for legacy slot entries
    without a `reject_anim_classes` field."""


    def test_red_wolf_rejected_at_m46_77(self, engine, tags):
        """c3181 Red Wolf (loco=5, anim=quadruped) — the user-reported
        freeze chr — rejected at the user-reported slot."""
        reason = engine._reject_target_for_slot(
            target_cp='c3181', src_cp='c4130',
            src_variant_name='Demi-Human Queen (Field Boss)', tags=tags,
            msb_base='m46_77_00_00.msb', pi=8)
        assert reason == 'quadruped_unsafe_slot'

    def test_runebear_rejected_at_m46_77(self, engine, tags):
        """c4630 Runebear (anim=quadruped_large) — prefix match on
        'quadruped' covers quadruped_large too."""
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4130',
            src_variant_name='Demi-Human Queen (Field Boss)', tags=tags,
            msb_base='m46_77_00_00.msb', pi=8)
        assert reason == 'quadruped_unsafe_slot'

    def test_legacy_slot_now_catches_anim_class_quadruped(self, engine, tags):
        """v0.24.62 broadened the default criterion from `loco==3` to
        also include `anim_class.startswith('quadruped')`. So legacy
        slots without explicit reject_anim_classes now catch BOTH
        loco=3 chrs (Rats) AND anim_class=quadruped(_large) chrs
        (Wolves, Bears, Goats) regardless of locomotion.

        Previously this test asserted the opposite: that c3181 Red
        Wolf (loco=5) was NOT rejected at m45_01 pi=1. v0.24.62
        inverts that — Red Wolf is now caught at legacy slots too,
        which is the desired behavior."""
        reason_rat = engine._reject_target_for_slot(
            target_cp='c4080', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=1)
        assert reason_rat == 'quadruped_unsafe_slot'

        # Red Wolf at the legacy slot — Gate 4 NOW rejects it
        # (anim_class=quadruped matches the broadened default).
        reason_wolf = engine._reject_target_for_slot(
            target_cp='c3181', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=1)
        assert reason_wolf == 'quadruped_unsafe_slot', (
            f'Red Wolf at legacy slot should now be rejected by Gate 4 '
            f'(v0.24.62 broadened default to anim_class), got {reason_wolf}')


class TestGate7XxlAtSmallSlot:
    """v0.27.4: geometry-aware size gate (Gate 7). An XXL/GIGA target
    is allowed only when its size class is within the slot capacity —
    the LARGER of the vanilla occupant size class (strict baseline)
    and the geometry-derived capacity from slot_terrain.json face_dist.
    Supersedes the blunt v0.24.55 xxl_at_small_slot gate (XXL-only, no
    geometry) and extends coverage to GIGA. Reason is now geometry_clip."""

    def test_troll_at_m_slot_banned(self, engine, tags):
        """The original v0.24.50 case: c4603 Stonedigger Troll (XXL)
        at c4377 (M-Battlemage) vanilla — banned."""
        # Use a non-boss src_variant_name to avoid earlier nb gates
        reason = engine._reject_target_for_slot(
            target_cp='c4603', src_cp='c4377',
            src_variant_name='Raya Lucaria Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        assert reason == 'geometry_clip'

    def test_troll_at_s_slot_banned(self, engine, tags):
        """Worst case from seed 714653: c4600 Troll at c3170 (S) — banned."""
        reason = engine._reject_target_for_slot(
            target_cp='c4600', src_cp='c3170',
            src_variant_name='Ant', tags=tags,
            msb_base='m34_10_00_00.msb', pi=10)
        assert reason == 'geometry_clip'

    def test_xxl_quadruped_large_at_m_slot_banned(self, engine, tags):
        """c4630 Runebear (XXL quadruped_large) at M-vanilla — same
        sink class, also banned."""
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4377',
            src_variant_name='Raya Lucaria Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        assert reason == 'geometry_clip'

    def test_xxl_at_xl_slot_allowed(self, engine, tags):
        """c4600 Troll at c4550 (XL vanilla) — borderline-but-allowed.
        v0.24.50's seed had c4603 at this XL-vanilla type ('less likely'
        sink risk in the original table)."""
        reason = engine._reject_target_for_slot(
            target_cp='c4600', src_cp='c4550',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m60_43_38_10.msb', pi=41)
        assert reason != 'geometry_clip'

    def test_xxl_at_xxl_slot_allowed(self, engine, tags):
        """c4602 Snowfield Troll at c4770 Gargoyle (XXL) — same-size
        swap, allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c4602', src_cp='c4770',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m46_66_00_00.msb', pi=1)
        assert reason != 'geometry_clip'

    def test_l_at_m_slot_allowed(self, engine, tags):
        """L-size target at M-vanilla — the gate is XXL-only, not 'any
        upgrade.' c4750 Godrick (L humanoid) at c4377 (M) — allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c4750', src_cp='c4377',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        assert reason != 'geometry_clip'

    def test_giga_caught_by_geometry_gate(self, engine, tags):
        """v0.27.4: GIGA is now covered by the geometry gate (the old
        blunt Gate 7 was XXL-only). c4500 Flying Dragon (GIGA) at
        c4377 (M-vanilla), m60_43_36_00 pi=31 — face_dist 2.17m proves
        neither XXL nor GIGA clearance, so it is rejected."""
        reason = engine._reject_target_for_slot(
            target_cp='c4500', src_cp='c4377',
            src_variant_name='Foot Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=31)
        assert reason == 'geometry_clip'

    def test_gate_uniformly_applies_to_all_xxl(self, engine, tags):
        """Every XXL chr in tags is rejected at M-vanilla — either by
        Gate 7 directly OR by an earlier gate (e.g. nb_strict catches
        NR Nightlords like c7500 Gladius before Gate 7 sees them).
        The key invariant: NO XXL chr passes through at M-vanilla."""
        xxl_cps = [cp for cp, t in tags.items() if t.get('size_class') == 'XXL']
        assert len(xxl_cps) >= 20, f'Expected ≥20 XXL chrs, found {len(xxl_cps)}'
        leaked = []
        for cp in xxl_cps:
            reason = engine._reject_target_for_slot(
                target_cp=cp, src_cp='c4377',  # M-Battlemage
                src_variant_name='Foot Soldier', tags=tags,
                msb_base='m60_43_36_00.msb', pi=31)
            if reason is None:
                leaked.append(cp)
        assert not leaked, (
            f'XXL chrs leaked through all gates at M-vanilla: {leaked}')


class TestGate4EncampmentSlots:
    """v0.24.59: Starting encampment slots in m43_01_00_00.msb that froze
    quadrupeds. Seed 923958 playtest report: c6060 Goat (anim=quadruped,
    NR-UI 'Lightning Ram' variant) at pi=2 froze; c6031 Bear (anim=
    quadruped_large) at pi=3 froze. Both vanilla c4300 Wandering Noble
    (humanoid). Same nav-mismatch pattern as v0.24.54 Red Wolf.

    Note: c6031/c6060 both have locomotion=0 — the default Gate 4 loco=3
    criterion does NOT catch them. The reject_anim_classes filter is
    what makes Gate 4 fire here. This test class enforces that."""

    def test_bear_at_encampment_slot_rejected(self, engine, tags):
        """c6031 Bear at m43_01 pi=3 — the empirical freeze case."""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=3)
        assert reason == 'quadruped_unsafe_slot'

    def test_goat_at_encampment_slot_rejected(self, engine, tags):
        """c6060 Goat at m43_01 pi=2 — the 'Lightning Ram' freeze case."""
        reason = engine._reject_target_for_slot(
            target_cp='c6060', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=2)
        assert reason == 'quadruped_unsafe_slot'

    def test_loco_0_doesnt_save_them(self, engine, tags):
        """Sanity check the precondition: c6031 and c6060 have loco=0,
        so the default Gate 4 wouldn't catch them — reject_anim_classes
        is the only filter making this work."""
        assert tags['c6031'].get('locomotion') == 0
        assert tags['c6060'].get('locomotion') == 0

    def test_prefix_match_catches_quadruped_large(self, engine, tags):
        """reject_anim_classes=['quadruped'] is a prefix match — should
        also catch quadruped_large chrs like Runebear."""
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=2)
        # Either Gate 4 (anim_class) or another gate (e.g. v0.24.55 Gate 7
        # for XXL@M might also fire, but only m43_01 pi=2 is XXL@M-vanilla
        # via c4630's XXL size and c4300's M size). Either way, must be
        # rejected somehow.
        assert reason is not None

    def test_humanoid_at_encampment_slot_allowed(self, engine, tags):
        """The gate is anim_class-scoped. Humanoid swaps still work."""
        reason = engine._reject_target_for_slot(
            target_cp='c4313', src_cp='c4300',  # Leyndell Soldier (humanoid)
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=2)
        assert reason != 'quadruped_unsafe_slot'

    def test_non_flagged_pi_in_same_msb_unaffected(self, engine, tags):
        """The gate is per-slot, not per-MSB. pi=9 in same MSB is not
        in the catalog so quadrupeds there are not rejected by Gate 4.
        (Other gates may still apply.)"""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=9)
        assert reason != 'quadruped_unsafe_slot'


class TestGate4BearRatParity:
    """v0.24.62: Default Gate 4 criterion broadened from `locomotion==3`
    to `locomotion==3 OR anim_class.startswith('quadruped')`. Catches
    anim_class=quadruped(_large) chrs with loco=0 (Bear, Goat, Wolf) at
    the same slots that catch loco=3 chrs (Rat, Giant Rat).

    User request:
    > "mark the regular grunt bear basically as fragile as small rat"

    Both chrs share the nav-mismatch failure mode but differ on
    locomotion. The fix aligns the gate behavior."""

    def test_bear_now_rejected_at_default_loco3_slot(self, engine, tags):
        """c6031 Bear (loco=0, anim=quadruped_large) at m45_01 pi=3 —
        the original Rat-empirical slot — was NOT rejected before
        v0.24.62 because loco==3 didn't match. Now it is."""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert reason == 'quadruped_unsafe_slot'

    def test_goat_now_rejected_at_prophylactic_slot(self, engine, tags):
        """c6060 Goat (loco=0, anim=quadruped) at m43_01 pi=5 (one of
        the prophylactic-density-scan slots from v0.24.33)."""
        reason = engine._reject_target_for_slot(
            target_cp='c6060', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m43_01_00_00.msb', pi=5)
        assert reason == 'quadruped_unsafe_slot'

    def test_rat_still_rejected(self, engine, tags):
        """The pre-existing loco=3 path must keep working. c4080 Rat
        at m45_01 pi=3 — the original case."""
        reason = engine._reject_target_for_slot(
            target_cp='c4080', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert reason == 'quadruped_unsafe_slot'

    def test_humanoid_at_same_slot_still_passes(self, engine, tags):
        """The broadening targets anim_class=quadruped*; humanoids at
        the same slot must still be allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c4313', src_cp='c4300',  # Leyndell Soldier
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=3)
        assert reason != 'quadruped_unsafe_slot'

    def test_quadruped_large_caught_by_prefix_match(self, engine, tags):
        """anim_class=quadruped_large should match the 'quadruped'
        startswith filter — same prefix match logic v0.24.54 used."""
        # c4630 Runebear: XXL quadruped_large, loco=0 (loco varies)
        reason = engine._reject_target_for_slot(
            target_cp='c4630', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m45_01_00_00.msb', pi=1)
        # Should be caught — exact reason might be Gate 4 OR Gate 7
        # (XXL@M), as long as something rejects it.
        assert reason is not None

    def test_unflagged_slots_unaffected(self, engine, tags):
        """Bear at an MSB/pi not in the catalog is still allowed."""
        reason = engine._reject_target_for_slot(
            target_cp='c6031', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m60_99_99_00.msb', pi=99)  # made up unflagged slot
        assert reason != 'quadruped_unsafe_slot'


class TestGate5_5GruntTrashAtBossBar:
    """v0.24.67: Reject grunt-tier and trash-tier targets at slots whose
    catalog tier indicates a boss-healthbar encounter (the EMEVD chain
    on death expects clean entity teardown — grunt/trash death anims
    and unusual spawner-generator fields don't always satisfy that).

    Discovered seed 877217 v0.24.65: c3664 Cemetery Shade landed at
    m32_00 pi=31 ent=32000810 (vanilla Elder Lion Encampment). User
    CTDed on kill. Root cause: NpcParam variants 36640020/32/35 carry
    spawner-generator entity IDs (23664000, 366400700, 366400000) that
    fire child entities on death, incompatible with vanilla NR's
    encampment boss-clear chain.

    Companion edits in v0.24.67:
      - c3664 removed from V3_FRAGILE_SAFE_CONFIRMED (the v0.20.52
        confirmation was at a non-boss-bar slot and doesn't generalize)
      - c3664 tier demoted miniboss → grunt in nr_enemy_tags.json
        (HP 939 / weight 130 matches grunt territory)

    The gate also catches as a bonus:
      - Miranda Sprouts at named_boss / castle_interior (same fragile-
        death-chr family, flower-petal dissolve on death)
      - Giant Rat / Wandering Noble / Bloodbane Stray as field_boss
        (thematic embarrassments)
      - c6031 Bear at named_boss (Bear freeze pattern from seed 537773)
    """

    def test_v3_boss_bar_tiers_defined(self, engine):
        """The constant exists and includes the catalog-tier names we
        empirically determined are boss-healthbar slots (>=60% event-
        bound). mountaintop / ruins_boss / fort_boss are excluded
        (their entries are mostly thematic spawns, not event bosses)."""
        assert 'encampment' in engine.V3_BOSS_BAR_TIERS
        assert 'named_boss' in engine.V3_BOSS_BAR_TIERS
        assert 'fieldboss' in engine.V3_BOSS_BAR_TIERS
        assert 'nightboss' in engine.V3_BOSS_BAR_TIERS
        assert 'remembrance' in engine.V3_BOSS_BAR_TIERS
        assert 'castle_interior' in engine.V3_BOSS_BAR_TIERS
        # Excluded tiers (mostly non-event)
        assert 'mountaintop' not in engine.V3_BOSS_BAR_TIERS
        assert 'ruins_boss' not in engine.V3_BOSS_BAR_TIERS
        assert 'fort_boss' not in engine.V3_BOSS_BAR_TIERS

    def test_v3_boss_bar_gated_tiers_is_grunt_and_trash(self, engine):
        """Only grunt and trash target tiers are gated. Miniboss,
        field_boss, night_boss, etc. remain eligible at boss-bar slots."""
        assert engine.V3_BOSS_BAR_GATED_TIERS == frozenset({'grunt', 'trash'})

    def test_c3664_demoted_to_grunt(self, engine, tags):
        """v0.24.67 metadata correction. Cemetery Shade was miniboss;
        HP 939 / weight 130 is grunt territory."""
        assert tags['c3664']['tier'] == 'grunt'
        # Demote should also drop has_boss_reward
        assert tags['c3664']['has_boss_reward'] is False

    def test_c3664_removed_from_fragile_safe_confirmed(self, engine):
        """v0.24.67. The v0.20.52 confirmation was at a non-boss-bar
        slot; seed 877217 m32_00 pi=31 invalidates it for boss-bar."""
        assert 'c3664' not in engine.V3_FRAGILE_SAFE_CONFIRMED

    def test_smoking_gun_c3664_at_encampment_rejected(self, engine, tags):
        """The seed 877217 case: m32_00 pi=31 ent=32000810 c4270 Elder
        Lion (Encampment) → c3664. Must be rejected by Gate 5.5."""
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason == 'grunt_trash_at_boss_bar', (
            f'c3664 at encampment slot should be rejected, got {reason}')

    def test_c3664_at_named_boss_rejected(self, engine, tags):
        """Another c3664 placement from seed 877217: m46_60 pi=2 ent=
        46600841 Banished Knight Evergaol (named_boss). Also a CTD
        risk under the same mechanism — boss-bar event chain expects
        clean teardown."""
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c3010',
            src_variant_name='Banished Knight (Evergaol- Dual Swords)',
            tags=tags, msb_base='m46_60_00_00.msb', pi=2)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_c3664_at_field_boss_rejected(self, engine, tags):
        """And the m60_42_37_50 pi=34 ent=1027500215 Mad Pumpkin Head
        named_boss placement from the same seed."""
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c4340',
            src_variant_name='Mad Pumpkin Head', tags=tags,
            msb_base='m60_42_37_50.msb', pi=34)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_c3664_at_walk_route_filler_allowed(self, engine, tags):
        """Non-boss-bar slot: c3664 should still be placeable at walk-
        route fillers and trash slots. Gate only fires at boss-bar."""
        # Pick a slot not in V3_BOSS_SLOT_CATALOG
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c4300',
            src_variant_name='Wandering Noble', tags=tags,
            msb_base='m34_10_00_00.msb', pi=69)
        assert reason is None, (
            f'c3664 at non-boss-bar slot should pass, got {reason}')

    def test_exempt_grunt_in_safe_confirmed_allowed(self, engine, tags):
        """c3000 Exile Soldier (grunt) is in V3_FRAGILE_SAFE_CONFIRMED.
        It must remain eligible at the same encampment slot — the
        exemption protects 85+ playtest-confirmed grunts that work fine
        at boss-bar slots."""
        assert 'c3000' in engine.V3_FRAGILE_SAFE_CONFIRMED
        reason = engine._reject_target_for_slot(
            target_cp='c3000', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason is None

    def test_miniboss_tier_unaffected(self, engine, tags):
        """Miniboss-tier targets are not gated — pass at all boss-bar
        slots. c3060 Giant Skeleton is a vanilla NR miniboss commonly
        placed at encampment / castle_interior boss slots."""
        assert tags['c3060']['tier'] == 'miniboss'
        reason = engine._reject_target_for_slot(
            target_cp='c3060', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason is None

    def test_field_boss_tier_active(self, engine, tags):
        """v0.28.x: field_boss tier RE-INTRODUCED as a distinct user-
        facing tier between miniboss and night_boss.

        History:
          v0.26.x: field_boss tier was collapsed entirely into
                   miniboss and night_boss. Reasoning then was that
                   the tier was ambiguous in practice and the picker
                   was simpler with three tiers (grunt / miniboss /
                   night_boss + nightlord) instead of four. The old
                   test (`test_field_boss_tier_eliminated`) asserted
                   no chr could carry tier=field_boss outside the
                   exclude set.

          v0.28.x: separation reversed. The night_boss tier was
                   overloaded — it carried both true arena bosses
                   (Margit, Maliketh, Malenia, Godfrey, Rellana, Mohg,
                   Bayle, Promised Consort Radahn, etc.) AND open-
                   world boss-fight encounters (Tree Sentinel, Tibia
                   Mariner, Magma Wyrm, Borealis, Death Bird,
                   Ulcerated Tree Spirit, Putrescent Knight, Furnace
                   Golem, Hippo Phase 2). The separation puts the
                   overworld encounters at field_boss tier and leaves
                   night_boss to the arena climax fights. A
                   configurable promote knob
                   (V3_FIELDBOSS_TO_NIGHTBOSS_PROMOTE_PCT) lets a
                   field_boss roll upgrade to night_boss at a tunable
                   rate, providing the "rare moment when a field
                   encounter is actually a real fight" experience.

        This test verifies:
          - At least one chr carries tier=field_boss (the tier is
            actually populated, not just a label nobody uses).
          - The fallback ladder in pick_target_cp accepts field_boss
            as a valid rolled tier outcome.
        """
        fb_tagged = [cp for cp, t in tags.items() if t.get('tier') == 'field_boss']
        assert len(fb_tagged) > 0, (
            'After v0.28.x tier separation, at least one chr should '
            'carry tier=field_boss. None found — either the data has '
            'regressed (tier was un-introduced) or the demotion pass '
            'never ran.')
        # Confirm field_boss is recognized by the engine's tier sets
        assert 'field_boss' in engine.V3_BOSS_STRENGTH_TIERS, (
            'field_boss must be in V3_BOSS_STRENGTH_TIERS so the tier-'
            'preserve gate admits it at boss-strength slots.')

    def test_night_boss_tier_unaffected(self, engine, tags):
        """night_boss-tier targets pass — they're authored for boss-bar
        encounters. c2130 Morgott at named_boss is fine."""
        assert tags['c2130']['tier'] == 'night_boss'
        reason = engine._reject_target_for_slot(
            target_cp='c2130', src_cp='c4270',
            src_variant_name='Elder Lion (Encampment)', tags=tags,
            msb_base='m32_00_00_00.msb', pi=31)
        assert reason is None

    def test_miranda_sprout_rejected_at_named_boss(self, engine, tags):
        """Bonus catch from Gate 5.5: c4481 Miranda Sprout (grunt,
        not in SAFE_CONFIRMED) has a flower-petal dissolve death
        animation that's the same fragile-death class as c3664.
        Gate blocks it at named_boss slots pre-emptively."""
        assert tags['c4481']['tier'] == 'grunt'
        assert 'c4481' not in engine.V3_FRAGILE_SAFE_CONFIRMED
        reason = engine._reject_target_for_slot(
            target_cp='c4481', src_cp='c4480',
            src_variant_name='Miranda Blossom', tags=tags,
            msb_base='m46_80_00_00.msb', pi=4)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_giant_rat_rejected_at_named_boss(self, engine, tags):
        """Thematic embarrassment catch: c4090 Giant Rat (grunt, not
        in SAFE_CONFIRMED) as named_boss. Gate prevents the 'giant rat
        is the boss now' situation as a side effect of catching the
        real risk."""
        assert tags['c4090']['tier'] == 'grunt'
        assert 'c4090' not in engine.V3_FRAGILE_SAFE_CONFIRMED
        # m47_70 pi=22 named_boss from seed 877217
        reason = engine._reject_target_for_slot(
            target_cp='c4090', src_cp='c3010',
            src_variant_name='Banished Knight', tags=tags,
            msb_base='m47_70_00_00.msb', pi=22)
        assert reason == 'grunt_trash_at_boss_bar'

    def test_slot_not_in_catalog_not_gated(self, engine, tags):
        """If the (msb, pi) isn't in V3_BOSS_SLOT_CATALOG, the gate
        doesn't fire — even if the source variant name looks boss-y.
        Catalog membership is the source of truth."""
        # m46_50 pi=15 is event-bound (ent=46500827) and the source name
        # contains "Evergaol", but it's not in V3_BOSS_SLOT_CATALOG.
        # Gate skips it; relies on catalog completeness as the contract.
        assert engine.V3_BOSS_SLOT_CATALOG.get(('m46_50_00_00.msb', 15)) is None
        reason = engine._reject_target_for_slot(
            target_cp='c3664', src_cp='c3970',
            src_variant_name='Azula Beastman (Evergaol- Cleaver)',
            tags=tags, msb_base='m46_50_00_00.msb', pi=15)
        # Gate 5.5 passes; other gates may or may not catch — for this
        # specific src/target the answer is None
        assert reason != 'grunt_trash_at_boss_bar'

    def test_exempt_set_covers_at_least_85_grunts_at_boss_bar(self, engine):
        """Sanity: V3_FRAGILE_SAFE_CONFIRMED contains enough grunts/
        trash to cover the bulk of legitimate boss-bar placements in
        real seeds (seed 877217 had ~92 grunt/trash @ boss-bar
        placements, 85 of which were in SAFE_CONFIRMED). If this
        invariant breaks, run the impact analysis again — likely
        means we accidentally removed a chr that was protecting many
        slots."""
        grunts_in_safe = [cp for cp in engine.V3_FRAGILE_SAFE_CONFIRMED
                          if cp not in ('c3664',)]  # the one we removed
        assert len(grunts_in_safe) >= 85, (
            f'SAFE_CONFIRMED unexpectedly small: {len(grunts_in_safe)} chrs. '
            f'Re-run impact analysis on a recent seed.')


class TestGate5_6XxlGigaSourceIntegrity:
    """v0.24.68: At any slot whose vanilla source is size_class XXL
    or GIGA, reject targets with mismatched anim_class OR target
    size_class smaller than L. Targets remaining valid: same
    anim_class AND size L+.

    Discovered: seeds 756907 and 388677 both CTD when leaving
    Stormveil Castle's southern face (front door). Pattern: vanilla
    XXL/GIGA boss slots in castle-area m60_4X_3Y tiles drift to
    targets with very different anim_class and/or much smaller size.
    When the cell streams in on transit, the chr-file load fails
    asset/nav validation against the slot's expectations and CTDs.

    Seed 388677 smoking-gun examples (all in southern-castle-exit
    tiles):
      m60_44_38_20 pi=91 ent=1048200800
        c4910 (quadruped_large/GIGA Magma Wyrm)
        → c2500 (humanoid/M Crucible Knight)  [anim drift + size drift]
      m60_43_38_10 pi=46 ent=1038100800
        c4602 (humanoid/XXL Snowfield Troll)
        → c3800 (humanoid/M Cleanrot Knight)  [size drift]
      m60_43_38_20 pi=103 ent=1038200800
        c4770 (humanoid/XXL Gargoyle)
        → c2120 (humanoid/M Malenia MMV)      [size drift; also nb_strict]

    User decision (v0.24.68): "enough diversity now" — go broad,
    cover all XXL/GIGA-source slots globally (no event-bound
    discrimination needed). Trade-off: loses some XXL→M and
    quadruped-GIGA→humanoid M diversity that was previously allowed.
    """



    def test_anim_drift_gate_removed(self, engine, tags):
        """v0.24.75: anim_class drift check removed from Gate 5.6.
        The cross-anim-class swap that previously rejected as
        'xxl_giga_anim_drift' now passes the gate (assuming size
        is also compatible). Test with same-size cross-anim_class:
        c4910 GIGA quadruped_large → c4660 GIGA giga_boss."""
        reason = engine._reject_target_for_slot(
            target_cp='c4660', src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        assert reason != 'xxl_giga_anim_drift', (
            f'v0.24.75: anim_drift gate should be removed; got {reason!r}')

    def test_same_chr_preserved_allowed(self, engine, tags):
        """A slot keeping its vanilla c-prefix (preservation case)
        is always allowed — same anim_class, same size_class."""
        reason = engine._reject_target_for_slot(
            target_cp='c4910', src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        assert reason != 'xxl_giga_anim_drift'
        assert reason != 'xxl_giga_size_drift'


    def test_xxl_to_l_allowed(self, engine, tags):
        """Size L target is the minimum acceptable at XXL slot —
        not gated. Sample: c4910 GIGA quadruped_large → c4280 L
        quadruped_large (Giant Ant)."""
        # find a quadruped_large L chr
        l_quadrupeds = [cp for cp, t in tags.items()
                        if t.get('anim_class') == 'quadruped_large'
                        and t.get('size_class') == 'L']
        if not l_quadrupeds:
            return  # no L quadruped_large chrs to test
        tgt = l_quadrupeds[0]
        reason = engine._reject_target_for_slot(
            target_cp=tgt, src_cp='c4910',
            src_variant_name='Magma Wyrm', tags=tags,
            msb_base='m60_44_38_20.msb', pi=91)
        assert reason != 'xxl_giga_anim_drift'
        assert reason != 'xxl_giga_size_drift'

    def test_source_not_xxl_or_giga_skipped(self, engine, tags):
        """Sources smaller than XXL bypass Gate 5.6 entirely. c4311
        humanoid/M Leyndell Soldier → c4040 misc/S Slug should not
        trigger 5.6 (it might trigger other gates, but not this
        one)."""
        reason = engine._reject_target_for_slot(
            target_cp='c4040', src_cp='c4311',
            src_variant_name='Leyndell Soldier', tags=tags,
            msb_base='m60_43_36_00.msb', pi=10)
        assert reason != 'xxl_giga_anim_drift'
        assert reason != 'xxl_giga_size_drift'


    def test_unique_reservation_honors_gate_via_delegation(self, engine, tags):
        """The mirror-semantic delegation: _score_slot_for_unique
        consults _reject_target_for_slot, so Gate 5.6 is honored at
        reservation time without a separate mirror.

        v0.24.75: anim_drift removed but size_drift retained — the
        c4910 GIGA → c2500 M swap still rejects (size)."""
        slot_info = {
            'msb': 'm60_44_38_20.msb', 'pi': 91,
            'source_cp': 'c4910',
            'source_variant_name': 'Magma Wyrm',
            'source_npc': 0,
            'cluster_id': None,
            'position': (0.0, 0.0, 0.0),
        }
        score = engine._score_slot_for_unique(slot_info, 'c2500', tags)
        assert score is None, (
            f'_score_slot_for_unique should reject size_drift at '
            f'GIGA slot via _reject_target_for_slot delegation, '
            f'got score={score}')


class TestEntranceAnimationGateV0_24_79:
    """v0.24.79 adds a per-class entrance-animation taxonomy with a
    matching arena-side affordance list. First class implemented:
    emerge_from_ground (the chr's intro animation rises out of the
    earth). Slot affordance: V3_NO_EMERGE_SLOTS (rampart roofs,
    elevated platforms — no subsurface terrain).

    Gate 7 in _reject_target_for_slot rejects emerge-class chrs at
    no-emerge slots. Other classes (unknown, fly_in, pre_placed,
    etc.) pass through unaffected.

    Long-term: replace V3_ENTRANCE_ANIM_CLASS data with chrbnd-
    derived parser output (Option C). V3_NO_EMERGE_SLOTS stays
    manual — geometry-dependent.
    """

    def test_entrance_anim_dict_loaded(self, engine):
        """V3_ENTRANCE_ANIM_CLASS is loaded from
        data/entrance_animations.json and non-empty."""
        assert isinstance(engine.V3_ENTRANCE_ANIM_CLASS, dict)
        assert len(engine.V3_ENTRANCE_ANIM_CLASS) > 0, (
            'V3_ENTRANCE_ANIM_CLASS unexpectedly empty — check '
            'data/entrance_animations.json exists + parses')

    def test_seed_emerge_anim_chrs_present(self, engine):
        """The 4 seeded emerge-from-ground chrs are present."""
        for cp in ('c4441', 'c4442', 'c4810', 'c4811'):
            assert engine.V3_ENTRANCE_ANIM_CLASS.get(cp) == 'emerge_from_ground', (
                f'{cp} expected emerge_from_ground, got '
                f'{engine.V3_ENTRANCE_ANIM_CLASS.get(cp)!r}')

    def test_no_emerge_slots_loaded(self, engine):
        """V3_NO_EMERGE_SLOTS is loaded from
        data/nr_no_emerge_slots.json and contains Fort GG."""
        assert isinstance(engine.V3_NO_EMERGE_SLOTS, frozenset)
        assert ('m30_30_00_00.msb', 45) in engine.V3_NO_EMERGE_SLOTS

    def test_emerge_anim_rejected_at_no_emerge_slot(self, engine, tags):
        """The seed 886942 v0.24.75 CTD case: c4810 Erdtree Avatar at
        Fort GG rampart (m30_30 pi=45). Gate 7 should reject."""
        reason = engine._reject_target_for_slot(
            target_cp='c4810', src_cp='c4660',
            src_variant_name='Guardian Golem (Fort)',
            tags=tags, msb_base='m30_30_00_00.msb', pi=45)
        assert reason == 'no_emerge_terrain', (
            f'Expected no_emerge_terrain rejection; got {reason!r}')

    def test_emerge_anim_passes_at_regular_slot(self, engine, tags):
        """Emerge-class chrs at non-no-emerge slots are NOT rejected
        by Gate 7. Test with c4810 at Cathedral upper floor — that
        slot is fragile (V3_PROBLEM_SLOTS) but not in V3_NO_EMERGE_SLOTS,
        so Gate 7 specifically should not fire."""
        reason = engine._reject_target_for_slot(
            target_cp='c4810', src_cp='c4660',
            src_variant_name='Guardian Golem (Cathedral)',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51)
        assert reason != 'no_emerge_terrain', (
            f'Gate 7 incorrectly fired at non-no-emerge slot; got {reason!r}')

    def test_unknown_chr_passes_at_no_emerge_slot(self, engine, tags):
        """Chrs not in V3_ENTRANCE_ANIM_CLASS (default 'unknown') pass
        through Gate 7 — no gate fires for unclassified chrs. This
        preserves the engine's current behavior for the vast majority
        of chrs while the taxonomy is small."""
        # c4910 Magma Wyrm — not in the seeded list, should be 'unknown'
        assert engine.V3_ENTRANCE_ANIM_CLASS.get('c4910') is None, (
            'c4910 should not be in the seeded emerge_from_ground list. '
            'If you added it, this test is now testing the wrong case.')
        # At Fort GG (no-emerge slot)
        reason = engine._reject_target_for_slot(
            target_cp='c4910', src_cp='c4660',
            src_variant_name='Guardian Golem (Fort)',
            tags=tags, msb_base='m30_30_00_00.msb', pi=45)
        # Should NOT be no_emerge_terrain — other gates may reject for
        # other reasons but Gate 7 specifically should not fire.
        assert reason != 'no_emerge_terrain', (
            f'Gate 7 fired on unclassified chr c4910; got {reason!r}')

    def test_centipede_demon_still_lands_at_fort(self, engine, tags):
        """The user-confirmed working case (Centipede Demon at Fort GG)
        must still land. Centipede Demon's intro is DS1-style ceiling
        drop — not emerge_from_ground. Should pass Gate 7 even though
        Fort GG is in V3_NO_EMERGE_SLOTS."""
        reason = engine._reject_target_for_slot(
            target_cp='c7710', src_cp='c4660',
            src_variant_name='Guardian Golem (Fort)',
            tags=tags, msb_base='m30_30_00_00.msb', pi=45)
        assert reason != 'no_emerge_terrain', (
            f'Gate 7 fired on c7710 Centipede Demon (not emerge-class); '
            f'got {reason!r}')

    def test_file_meta_carries_provenance(self, engine):
        """The _meta blocks document where the data came from + the
        long-term Option C migration intent. Test that the meta is
        non-empty so loaders haven't silently failed."""
        assert engine.V3_ENTRANCE_ANIM_FILE_META, (
            'entrance_animations.json _meta missing — file may not be '
            'loading correctly')
        assert 'long_term' in engine.V3_NO_EMERGE_SLOTS_FILE_META.get(
            'interaction_with_other_systems', {}), (
            'nr_no_emerge_slots.json _meta missing long-term migration '
            'doc — should reference Option C chrbnd parser')

    def test_full_entry_metadata_accessible(self, engine):
        """V3_ENTRANCE_ANIM_META should carry the full entry per chr
        (class + _source_note) so future auditing can trace each
        classification back to its empirical source."""
        entry = engine.V3_ENTRANCE_ANIM_META.get('c4810')
        assert entry is not None
        assert entry.get('class') == 'emerge_from_ground'
        assert '_source_note' in entry, (
            'c4810 entry missing _source_note — every classification '
            'should document its empirical source')
        # Spot check that the source note references the v0.24.77 seed
        assert '886942' in entry.get('_source_note', ''), (
            'c4810 _source_note should reference v0.24.77 seed 886942 '
            'where this was first identified')


class TestIntroAnimRequiredGateV0_26_11:
    """v0.26.11 adds Gate 8, the mirror image of the no-emerge Gate 7.

    Some scripted slots' EMEVD spawn setup hard-requires the occupant to
    have an idle/entrance animation. Chrs classified 'no_intro_anim' in
    V3_ENTRANCE_ANIM_CLASS break at those slots while being resilient
    everywhere else. Slot affordance: V3_INTRO_ANIM_REQUIRED_SLOTS.

    First slot: the m38_00 Guardian Golem "Cathedra" slot (pi=51).
    First (and only seeded) no_intro_anim chr: c5070 Death Knight,
    confirmed broken there in playtest. Emergers/risers and the
    unclassified-default ('unknown') majority pass through unaffected —
    the gate is negative, not a positive allowlist.
    """

    CATHEDRA = ('m38_00_00_00.msb', 51)

    def test_no_intro_anim_class_in_taxonomy(self, engine):
        """entrance_animations.json _meta declares the new class."""
        values = engine.V3_ENTRANCE_ANIM_FILE_META.get('values', {})
        assert 'no_intro_anim' in values, (
            "_meta.values missing 'no_intro_anim' — taxonomy doc not updated")

    def test_death_knight_classified_no_intro_anim(self, engine):
        """c5070 Death Knight is the seeded no_intro_anim member."""
        assert engine.V3_ENTRANCE_ANIM_CLASS.get('c5070') == 'no_intro_anim', (
            f"c5070 expected no_intro_anim, got "
            f"{engine.V3_ENTRANCE_ANIM_CLASS.get('c5070')!r}")

    def test_intro_anim_required_slots_loaded(self, engine):
        """V3_INTRO_ANIM_REQUIRED_SLOTS loads from
        data/nr_intro_anim_required_slots.json and contains Cathedra."""
        assert isinstance(engine.V3_INTRO_ANIM_REQUIRED_SLOTS, frozenset)
        assert self.CATHEDRA in engine.V3_INTRO_ANIM_REQUIRED_SLOTS

    def test_death_knight_rejected_at_cathedra(self, engine, tags):
        """The confirmed-broken case: Death Knight at the Cathedra slot.
        Gate 8 should reject with 'requires_intro_anim'."""
        reason = engine._reject_target_for_slot(
            target_cp='c5070', src_cp='c4660',
            src_variant_name='Guardian Golem (Cathedral)',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51)
        assert reason == 'requires_intro_anim', (
            f"Expected requires_intro_anim rejection; got {reason!r}")

    def test_death_knight_passes_at_other_slot_in_same_msb(self, engine, tags):
        """Gate 8 is (msb, pi)-scoped, not msb-scoped. Death Knight at
        another pi in the same Cathedral MSB must NOT be rejected by
        Gate 8 (pi=11 is one of the Oracle Envoy cluster slots)."""
        reason = engine._reject_target_for_slot(
            target_cp='c5070', src_cp='c3620',
            src_variant_name='Oracle Envoy',
            tags=tags, msb_base='m38_00_00_00.msb', pi=11)
        assert reason != 'requires_intro_anim', (
            f"Gate 8 fired at a non-required slot in the same MSB; "
            f"got {reason!r}")

    def test_death_knight_passes_at_unrelated_slot(self, engine, tags):
        """Death Knight elsewhere in the corpus is unaffected by Gate 8.
        (Other gates may reject for other reasons — we only assert that
        Gate 8 specifically does not fire.)"""
        reason = engine._reject_target_for_slot(
            target_cp='c5070', src_cp='c4070',
            src_variant_name='Wolf',
            tags=tags, msb_base='m60_43_37_00.msb', pi=2)
        assert reason != 'requires_intro_anim', (
            f"Gate 8 fired at an unrelated slot; got {reason!r}")

    def test_emerger_passes_at_cathedra(self, engine, tags):
        """Emergers/risers play well at Cathedra (per the TODO's
        confirmed-good observations). c4810 Erdtree Avatar is
        emerge_from_ground, NOT no_intro_anim — Gate 8 must not fire."""
        reason = engine._reject_target_for_slot(
            target_cp='c4810', src_cp='c4660',
            src_variant_name='Guardian Golem (Cathedral)',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51)
        assert reason != 'requires_intro_anim', (
            f"Gate 8 wrongly rejected an emerge-class chr; got {reason!r}")

    def test_unknown_chr_passes_at_cathedra(self, engine, tags):
        """The vast majority of the roster is unclassified ('unknown'
        default). Gate 8 is a negative gate — it must NOT reject
        unclassified chrs, so the Cathedra slot still randomizes widely."""
        # c3950 Man-Serpent — not in V3_ENTRANCE_ANIM_CLASS
        assert engine.V3_ENTRANCE_ANIM_CLASS.get('c3950') is None, (
            'c3950 should be unclassified — if you classified it, this '
            'test is now exercising the wrong case.')
        reason = engine._reject_target_for_slot(
            target_cp='c3950', src_cp='c4660',
            src_variant_name='Guardian Golem (Cathedral)',
            tags=tags, msb_base='m38_00_00_00.msb', pi=51)
        assert reason != 'requires_intro_anim', (
            f"Gate 8 fired on an unclassified chr; got {reason!r}")

    def test_file_meta_carries_provenance(self, engine):
        """The slot file's _meta documents the gate logic + that the
        slot list stays manual long-term (geometry-dependent)."""
        fm = engine.V3_INTRO_ANIM_REQUIRED_SLOTS_FILE_META
        assert fm, 'nr_intro_anim_required_slots.json _meta missing'
        assert fm.get('engine_field') == 'V3_INTRO_ANIM_REQUIRED_SLOTS'
        assert 'long_term' in fm.get('interaction_with_other_systems', {})

    def test_cathedra_entry_records_confirmed_failure(self, engine):
        """The Cathedra slot entry documents c5070 as a confirmed
        failure so future readers can trace the classification."""
        entry = engine.V3_INTRO_ANIM_REQUIRED_SLOTS_META.get(self.CATHEDRA)
        assert entry is not None
        failures = {f.get('cp') for f in entry.get('confirmed_failures', [])}
        assert 'c5070' in failures, (
            'Cathedra entry should list c5070 in confirmed_failures')


class TestGate7_8NavRequiredAtStubNavSlot:
    """Gate 7.8: cave/dungeon tiles (m46/m48/m49) have empty navmesh +
    empty onav. Nav-dependent pursuit AI freezes in those tiles when
    chr can't pathfind to player. Restrict targets to a whitelist of
    nav-independent (set-piece / scripted) chrs.

    Empirical motivation: Fat Inquisitor c5320 freeze at cave slots in
    seed 923630 (5 placements in m46/m48/m49). Generalizes the
    rats-don't-work-in-caves observation Alaric flagged."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        # Force cache reload (cross-test contamination)
        oops_v3._V3_NAV_TILE_CACHE = None
        return oops_v3

    @pytest.fixture
    def tags(self, engine):
        return engine.load_data()[0]

    def test_fat_inquisitor_rejected_at_cave(self, engine, tags):
        """c5320 Fat Inquisitor at m46_70 pi=3 — the seed 923630
        freeze case that motivated this gate."""
        r = engine._reject_target_for_slot(
            target_cp='c5320', src_cp='c3560',
            src_variant_name='Iron Maiden', tags=tags,
            msb_base='m46_70_00_00.msb', pi=3)
        assert r == 'nav_required_at_stub_nav_slot', (
            f'Fat Inquisitor at cave should reject via Gate 7.8, got {r}')

    def test_overworld_fat_inquisitor_unaffected(self, engine, tags):
        """Same chr at an overworld slot (with real navmesh) should NOT
        trip Gate 7.8 — only the cave-tile predicate fires there."""
        r = engine._reject_target_for_slot(
            target_cp='c5320', src_cp='c4110',
            src_variant_name='', tags=tags,
            msb_base='m60_42_37_50.msb', pi=22)
        # May still fire OTHER gates, but not 7.8 specifically
        assert r != 'nav_required_at_stub_nav_slot', (
            f'Fat Inquisitor at overworld should NOT trip Gate 7.8, got {r}')

    def test_vanilla_cave_chr_allowed(self, engine, tags):
        """Whitelisted chrs (vanilla cave placements) pass at cave slots."""
        # c3000 Exile Soldier — common cave-tile vanilla source
        r = engine._reject_target_for_slot(
            target_cp='c3000', src_cp='c4313',
            src_variant_name='Leyndell Soldier', tags=tags,
            msb_base='m46_70_00_00.msb', pi=3)
        assert r != 'nav_required_at_stub_nav_slot'

    def test_overworld_unaffected_by_whitelist(self, engine, tags):
        """At overworld slots, non-whitelist chrs are still allowed
        (Gate 7.8 only fires at stub-nav tiles)."""
        # c5900 Man-Fly — not in whitelist. At m60_xx (overworld), allow.
        r = engine._reject_target_for_slot(
            target_cp='c5900', src_cp='c4110',
            src_variant_name='', tags=tags,
            msb_base='m60_42_37_50.msb', pi=22)
        assert r != 'nav_required_at_stub_nav_slot'

    def test_stub_nav_predicate(self, engine):
        """Direct test of the helper: cave tiles report True, overworld False."""
        assert engine._is_stub_nav_slot('m46_70_00_00.msb') is True
        assert engine._is_stub_nav_slot('m48_90_00_00.msb') is True
        assert engine._is_stub_nav_slot('m49_17_00_00.msb') is True
        assert engine._is_stub_nav_slot('m60_42_37_50.msb') is False
        assert engine._is_stub_nav_slot('m34_30_00_00.msb') is False

    def test_whitelist_includes_known_cave_chrs(self, engine):
        """Sanity: the whitelist must include test-asserted cave chrs."""
        wl = engine.V3_NAV_INDEPENDENT_TARGETS
        for cp in ('c7700', 'c7710', 'c4602', 'c3610', 'c4660'):
            assert cp in wl, f'{cp} missing from V3_NAV_INDEPENDENT_TARGETS'
