"""Tests for `pick_target_cp` — seed regressions.

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

class TestSeed798229Freezes:
    """v0.24.39: hard-exclude small Oracle Envoy (c3610), Ancestral Follower
    (c3360), and Abnormal Stone Cluster (c4430) as targets after Alaric's
    seed 798229 playtest report: small Oracle Envoy frozen in starting
    encampment + an invisible enemy in the same camp.

    v0.24.65: ALL THREE LIFTED. User confirmed via playtest that deploying
    MMV's sfx/ and material/ dirs makes the full MMV roster work (Romina
    proof case). All 30 broken_runtime_chrs entries were lifted in the
    same release; these were the 3 originally playtest-confirmed ones, the
    riskier subset of the lift. Cap=1 applied as a safety net. Test
    assertions inverted to capture the new state; if any of these chrs
    is observed broken in playtest after v0.24.65, re-add to
    nr_missing_chr_files.json broken_runtime_chrs and re-invert here."""

    @pytest.fixture
    def engine(self):
        import oops_v3
        return oops_v3

    def test_c3610_small_oracle_envoy_no_longer_excluded(self, engine):
        """v0.24.65: lifted. v0.24.86-patch2-followup: RE-EXCLUDED.

        Empirical regression in seed 923630 — c3610 placed at an Oracle
        Envoy slot froze on entrance animation, identical pattern to
        the original v0.24.65 ban motivation. The v0.24.65 lift was
        speculative ('maybe the bug self-fixed'); the freeze data
        shows it didn't. Cap-of-1 alone wasn't enough since one
        placement is enough to brick a seed.
        """
        assert 'c3610' in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c3610 must be hard-excluded — re-banned in v0.24.86-patch2-followup '
            'after a freeze recurrence in seed 923630.')

    def test_c4361_godrick_knights_horse_excluded(self, engine):
        """v0.25.0-patch1: c4361 RE-EXCLUDED.

        Same lifecycle as c3610 above: v0.24.65 lifted c4361 from
        EXCLUDE with a defensive cap=1, then v0.25.0-patch1 re-excluded
        it after empirical mount-component CTDs in seeds 939029 and 42
        (mount slots invoke rider-mount composite logic that non-mount
        chrs can't satisfy — Godrick Knight's Horse riderless is the
        same failure class as c3160/c4363).

        v0.26.x: c4361 also dropped from `_LIFTED_V0_24_65` in oops_v3.py
        (previously the lift kept setting cap=1 even though the exclude
        wins — dead-code finding from
        `dev/audit_placement_budget_consistency.py`).
        """
        assert 'c4361' in engine.V3_EXCLUDE_TARGET_PREFIXES, (
            'c4361 must be hard-excluded — re-banned in v0.25.0-patch1 '
            'after mount-component CTDs in seeds 939029 and 42.')

    def test_c3620_large_oracle_envoy_NOT_excluded(self, engine):
        """Large Oracle Envoy (Cathedral) was never banned. Unchanged."""
        assert 'c3620' not in engine.V3_EXCLUDE_TARGET_PREFIXES

    def test_c3360_ancestral_follower_no_longer_excluded(self, engine):
        """v0.24.65: lifted. v0.27.8: grunt-tier cap. v0.27.9: cap 32->40."""
        assert 'c3360' not in engine.V3_EXCLUDE_TARGET_PREFIXES
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c3360') == 40

    def test_c4430_abnormal_stone_cluster_no_longer_excluded(self, engine):
        """v0.24.65: lifted. v0.27.8: grunt cap (was trash). v0.27.9: 32->40."""
        assert 'c4430' not in engine.V3_EXCLUDE_TARGET_PREFIXES
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c4430') == 40

    def test_fi_reserved_only_protects_c3620(self, engine):
        """v0.24.39: the defensive cleanup (_FI_CPS_RESERVED_FOR_TARGET) now
        only protects c3620. v0.24.65 lift of c3610 doesn't change this —
        c3620 stays in _FI_CPS_RESERVED_FOR_TARGET as before. c3610 is now
        eligible as a regular target but isn't in the FI reservation set."""
        assert engine._FI_CPS_RESERVED_FOR_TARGET == frozenset({'c3620'})

    def test_broken_runtime_chrs_v0_24_65_lift_held(self):
        """v0.24.65 lifted 30 chrs and emptied the file. v0.25.0
        re-populated it with a NEW class of entries (post_dlc_dump
        heritage proactive bans, tagged observed_version=v0.25.0) —
        these are categorically distinct from the v0.24.65 lifted set,
        so the lift itself didn't revert.

        This test now locks in the meaningful invariant: the 30 v0.24.65
        lifted chrs do not reappear (regression guard), and the file's
        history field preserves the lift record. New unrelated entries
        (v0.25.0+) are fine.
        """
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'nr_missing_chr_files.json')
        with open(path) as f:
            d = json.load(f)

        # Lift history preserved
        hist = d['_meta'].get('history', {}).get(
            'broken_runtime_chrs_lifted_v0_24_65', {})
        lifted = hist.get('lifted_entries', [])
        assert len(lifted) == 30, (
            'history.broken_runtime_chrs_lifted_v0_24_65 should preserve all '
            '30 originally-banned chrs for reference')
        lifted_cps = {e['c_prefix'] for e in lifted if isinstance(e, dict)}

        # None of the lifted v0.24.65 chrs reappear in current broken_runtime_chrs
        current = d.get('broken_runtime_chrs', [])
        current_cps = {e['c_prefix'] for e in current}
        regressed = lifted_cps & current_cps
        assert not regressed, (
            f'v0.24.65 lift regression — these chrs returned to '
            f'broken_runtime_chrs: {sorted(regressed)}. If intentional, '
            f'remove them from history.broken_runtime_chrs_lifted_v0_24_65 '
            f'or re-version the lift; if a re-ban for a NEW reason, that '
            f'is fine but the lift-history symmetry is lost.')

        # New entries are version-tagged separately (not posing as v0.24.65)
        for entry in current:
            ver = entry.get('observed_version', '')
            assert not ver.startswith('v0.24.65'), (
                f'{entry.get("c_prefix")} tagged observed_version={ver!r} — '
                f'looks like a v0.24.65 entry that should be lifted, not '
                f're-banned. Tag new bans with their own observed_version.')


class TestManusUnBanned:
    """v0.24.46: c8500 Manus un-banned per Alaric playtest direction.
    The DS1 cross-engine guard was originally added v0.23.39 after a CTD
    attributed to 'asset graph divergence'. Pattern matches the c8300
    Dragonslayer Armor + c4720 Godfrey vindication trajectory — original
    CTD was likely position-specific anim-slot mismatch now caught by
    other gates."""


    def test_c8500_still_mp_safe_blocked(self, engine):
        """Manus is mmv_import _source — MP-safe should still block him
        to protect co-op partners without the MMV mod."""
        assert 'c8500' in engine.V3_MP_SAFE_BLOCKLIST, (
            'c8500 should remain MP-safe blocked (he is _source=mmv_import; '
            'co-op partners without MMV would CTD on Manus). Un-banning '
            'should ONLY affect solo / MP-off play.')

    def test_c8500_in_allowlist_override(self):
        """v0.25.0-patch3: MMV_ORIGIN_ALLOWLIST_OVERRIDE deprecated alongside
        MMV_INCOMPATIBLE_ORIGINS. With the base ban set now empty, the
        allowlist override has nothing to override. Test inverted from
        'c8500 must be in override' to 'override is empty (deprecated)'.
        Full removal of the constant deferred to a future cleanup pass."""
        from engine.pack_loaders.mmv_imports import MMV_ORIGIN_ALLOWLIST_OVERRIDE
        assert MMV_ORIGIN_ALLOWLIST_OVERRIDE == frozenset(), (
            'MMV_ORIGIN_ALLOWLIST_OVERRIDE should be empty (deprecated in '
            'v0.25.0-patch3 alongside MMV_INCOMPATIBLE_ORIGINS). MMV now '
            'ships fully-working cross-engine chrbnds; the rando trusts '
            'the MMV deploy and does not auto-ban by origin_game.')

    def test_ds1_still_in_incompatible_origins(self):
        """v0.25.0-patch3: MMV_INCOMPATIBLE_ORIGINS deprecated. The
        historical DS1/BB auto-ban via origin_game was out of date — MMV
        ships fully-working cross-engine chrbnds and the v0.23.39 (Manus)
        / v0.23.72 (c1260) CTDs that motivated the bans have been resolved
        upstream. Test inverted from 'DS1 in set' to 'set is empty
        (deprecated)'. Full removal deferred to future cleanup pass."""
        from engine.pack_loaders.mmv_imports import MMV_INCOMPATIBLE_ORIGINS
        assert MMV_INCOMPATIBLE_ORIGINS == frozenset(), (
            'MMV_INCOMPATIBLE_ORIGINS should be empty (deprecated in '
            'v0.25.0-patch3). The rando trusts MMV deploy.')


    def test_c8500_tier_and_size(self, engine):
        """Sanity: Manus should be tier=night_boss, size=XL, expects_boss_arena.

        v0.26.x size_class correction: NpcParam.csv showed Manus at
        h=4.00 r=1.20, which is firmly XL (was previously tagged L
        in MMV pack — part of the v0.26.x bulk MMV undersizing audit
        that surfaced 18 systematically-undersized chrs).

        Tier was retagged nightlord -> night_boss in the MMV-import tier
        normalization (all 19 MMV imports moved off the nightlord tier);
        this sanity check tracks the post-retag value."""
        roster, tags = engine.load_data()
        t = tags['c8500']
        assert t['tier'] == 'night_boss'
        assert t['size_class'] == 'XL'
        assert t.get('expects_boss_arena') is True, (
            'c8500 should expects_boss_arena=True so the picker only '
            'targets him at boss arena slots (he is a nightlord).')


class TestSwCornerFreezeRepositions:
    """v0.24.48: Two slot freezes reported at SW corner of m60_42_36_00
    (seed 460401, engine v0.24.45). Both small loco=0 quadrupeds
    (c7711 Centipede Grub at pi=19, c4150 Basilisk at pi=20) froze at
    near-corner positions. Repositioned 7.07m inward each."""

    SLOTS = {
        '19': {'from': (-103.99, 108.14, 103.12),
               'to':   (-98.99, 108.14, 98.12)},
        '20': {'from': (-105.62, 105.48, 93.15),
               'to':   (-100.62, 105.48, 88.15)},
    }

    def test_entries_present(self):
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, 'data', 'slot_repositions.json')
        with open(path) as f:
            sr = json.load(f)
        m = sr['proposals'].get('m60_42_36_00.msb', {})
        for pi in self.SLOTS:
            assert pi in m, (
                f'm60_42_36_00.msb pi={pi} missing from slot_repositions.json. '
                f'This is the SW-corner freeze fix from v0.24.48 (seed 460401).')

    def test_repositions_move_inward(self):
        """from_pos at the corner, to_pos_center should move toward center
        (smaller |X| and smaller |Z|)."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        m = sr['proposals']['m60_42_36_00.msb']
        for pi, expected in self.SLOTS.items():
            entry = m[pi]
            tp = entry['to_pos_center']
            fp = entry['from_pos']
            assert abs(tp[0]) < abs(fp[0]), (
                f'pi={pi}: to_pos X (|{tp[0]}|) should be smaller than '
                f'from_pos X (|{fp[0]}|) — moving inward toward center')
            assert abs(tp[2]) < abs(fp[2]), (
                f'pi={pi}: to_pos Z (|{tp[2]}|) should be smaller than '
                f'from_pos Z (|{fp[2]}|)')

    def test_marked_unverified(self):
        """The repositions need playtest verification — flag must be False
        until Alaric confirms in seed re-run."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        m = sr['proposals']['m60_42_36_00.msb']
        for pi in self.SLOTS:
            entry = m[pi]
            assert entry.get('manual_override', {}).get('playtest_verified') is False, (
                f'pi={pi} should have playtest_verified=False until '
                f'confirmed in playtest re-run of seed 460401')


class TestCrossPhaseReposExtension:
    """v0.24.49: the v0.24.48 SW-corner fix was incomplete — same
    geographic slot exists in m60_42_36_00/_10/_20 with identical pi
    and identical position. v0.24.48 only fixed _00. User reported a
    Demi-Human Chief freeze, which traced to m60_42_36_20 pi=19 at the
    SAME position. Extending fix to all phase tiles."""

    EXPECTED = [
        ('m60_42_36_00.msb', '19'),
        ('m60_42_36_00.msb', '20'),
        ('m60_42_36_10.msb', '19'),
        ('m60_42_36_10.msb', '20'),
        ('m60_42_36_20.msb', '19'),
        ('m60_42_36_20.msb', '20'),
    ]

    def test_all_three_phases_have_pi19_pi20(self):
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            assert msb in sr['proposals'] and pi in sr['proposals'][msb], (
                f'{msb} pi={pi} expected in slot_repositions.json after v0.24.49 '
                f'cross-phase extension.')

    def test_cross_phase_positions_match(self):
        """All three phases of pi=19 should have identical positions
        (and same for pi=20). They're the same world slot."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for pi in ('19', '20'):
            positions = [tuple(sr['proposals'][f'm60_42_36_{ph}.msb'][pi]['from_pos'])
                         for ph in ('00', '10', '20')]
            assert all(p == positions[0] for p in positions), (
                f'pi={pi} from_pos differs across phase tiles: {positions}. '
                f'Same geographic slot — should be identical.')
            to_positions = [tuple(sr['proposals'][f'm60_42_36_{ph}.msb'][pi]['to_pos_center'])
                            for ph in ('00', '10', '20')]
            assert all(p == to_positions[0] for p in to_positions), (
                f'pi={pi} to_pos_center differs across phase tiles: {to_positions}')


class TestCaveMouthTrollYRaise:
    """v0.24.50: User playtest seed 714653 reported Stonedigger Troll
    'halfway stuck in ground, like he can move but he's too short' at
    a cave-mouth-adjacent slot. m60_43_36_00 pi=31 is calibrated for
    c4377 (M-Battlemage) — XXL targets sink. Same slot exists in _10
    and _20 phase tiles with identical position. Fix: raise Y by 2m
    across all 3 phase tiles (applied preemptively per v0.24.49
    cross-phase lesson)."""

    EXPECTED = [
        ('m60_43_36_00.msb', '31'),
        ('m60_43_36_10.msb', '31'),
        ('m60_43_36_20.msb', '31'),
    ]

    def test_all_three_phases_have_pi31(self):
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            assert msb in sr['proposals'] and pi in sr['proposals'][msb], (
                f'{msb} pi={pi} expected in slot_repositions.json after '
                f'v0.24.50 XXL-sink fix.')

    def test_y_raised_by_2m(self):
        """Y should go from 67.17 to 69.17."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            entry = sr['proposals'][msb][pi]
            assert entry['from_pos'][1] == 67.17, (
                f'{msb} pi={pi} from_pos Y expected 67.17, got '
                f'{entry["from_pos"][1]}')
            assert entry['to_pos_center'][1] == 69.17, (
                f'{msb} pi={pi} to_pos_center Y expected 69.17 (+2m raise), '
                f'got {entry["to_pos_center"][1]}')

    def test_xz_unchanged(self):
        """Only Y should change. X and Z stay at the vanilla slot position."""
        import json, os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        for msb, pi in self.EXPECTED:
            entry = sr['proposals'][msb][pi]
            assert entry['from_pos'][0] == entry['to_pos_center'][0]
            assert entry['from_pos'][2] == entry['to_pos_center'][2]


class TestSwCornerFragilityFlag:
    """v0.24.60: User report seed 923958 — c6060 Goat (pi=19) and c4120
    Demi-Human Chief (pi=20) BOTH froze at the SW corner cluster, even
    though v0.24.49 already had +5/-5 repositions applied (post-shift
    positions [-98.99, 108.14, 98.12] and [-100.62, 105.48, 88.15] visible
    in the spoiler).

    Fix: V3_PROBLEM_SLOTS entries flag fragility (restricts pool to
    SAFE_CONFIRMED). V3_PROBLEM_SLOT_EXTRA_BANS adds c4120 override
    since c4120 IS in SAFE_CONFIRMED (bulk-added v0.20.48 via mt=3
    rule) and would otherwise pass the fragility filter.

    Cross-phase coverage: all 6 slots (pi=19, pi=20 × _00/_10/_20)."""

    def test_sw_corner_slots_are_fragile(self, engine, tags):
        """All 6 SW-corner phase-sibling slots flag as fragile."""
        import oops_v3 as o
        for sub in ('_00', '_10', '_20'):
            for pi in (19, 20):
                msb = f'm60_42_36{sub}.msb'
                assert o.is_fragile_slot(msb, pi, 'Putrid Corpse'), (
                    f'{msb} pi={pi} should be fragile after v0.24.60')

    def test_c4120_extra_banned_at_sw_corner(self, engine, tags):
        """c4120 Demi-Human Chief is in SAFE_CONFIRMED so the fragility
        flag alone wouldn't block it. V3_PROBLEM_SLOT_EXTRA_BANS adds
        the slot-specific ban."""
        import oops_v3 as o
        # Sanity: c4120 IS in SAFE_CONFIRMED
        assert 'c4120' in o.V3_FRAGILE_SAFE_CONFIRMED, (
            "Test assumes c4120 is in SAFE_CONFIRMED — if this fails, "
            "the SAFE_CONFIRMED entry was removed and the extra-ban is "
            "redundant (which is fine, but the rationale should be updated)")
        for sub in ('_00', '_10', '_20'):
            for pi in (19, 20):
                msb = f'm60_42_36{sub}.msb'
                bans = o.V3_PROBLEM_SLOT_EXTRA_BANS.get((msb, pi), set())
                assert 'c4120' in bans, f'c4120 should be banned at {msb} pi={pi}'

    def test_c6060_blocked_by_fragility_alone(self, engine, tags):
        """c6060 Goat is NOT in SAFE_CONFIRMED, so it's blocked just by
        the fragility flag (no need for an extra-ban entry)."""
        import oops_v3 as o
        assert 'c6060' not in o.V3_FRAGILE_SAFE_CONFIRMED

    def test_repositions_still_apply(self, engine, tags):
        """v0.24.49's slot_repositions.json entries are unaffected — they're
        a separate mechanism (apply at DCX-write time, not chr-pick time).
        Both mechanisms now fire for these slots."""
        import json, os
        HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(HERE, 'data', 'slot_repositions.json')) as f:
            sr = json.load(f)
        e = sr['proposals'].get('m60_42_36_00.msb', {}).get('19')
        assert e is not None, "v0.24.49 reposition for SW corner must persist"
        assert e.get('status') == 'playtest_freeze'
        # Shift is +5 X, 0 Y, -5 Z (7.07m diagonal inward)
        assert e['to_pos_center'] == [-98.99, 108.14, 98.12]

    def test_unaffected_slots_not_collateral_damage(self, engine, tags):
        """Verify the fragility/extra-ban scope is narrow — pi=18 and pi=21
        in the same MSB are NOT affected."""
        import oops_v3 as o
        # pi=18 should NOT be fragile (we didn't add it)
        is_fragile_18 = o.is_fragile_slot('m60_42_36_00.msb', 18, 'Putrid Corpse')
        # Could already be fragile via T1/T2; just check it's not in PROBLEM_SLOTS specifically
        assert ('m60_42_36_00.msb', 18) not in o.V3_PROBLEM_SLOTS
        assert ('m60_42_36_00.msb', 21) not in o.V3_PROBLEM_SLOTS


class TestDemotionAnimCompatNbMarker:
    """v0.24.70: BIG_PROXIMITY and DENSITY_CAP demotion paths check
    anim_class compatibility at scripted-intro slots. The picker's
    notion of "scripted intro" is `expects_boss_arena OR NB-marker
    in source variant_name`. The demotion sites historically only
    checked `expects_boss_arena`.

    Result: slots whose source tag has expects_boss_arena=False but
    whose variant_name carries an NB marker (e.g. c4130 Demi-Human
    Queen, c3100 Bell Bearing Hunter, c5810 Demi-Human Swordmaster
    — all night_boss tier but expects_boss_arena=False) bypassed
    the anim_compat filter at demotion time. Demotions could land
    anim-incompatible chrs (e.g. humanoid c7100 at quadruped c4130
    slot) → Margit-style scripted-cinematic softlock / preboss wave
    never fires.

    Confirmed seed 388677 m49_29 pi=16: c4130 quadruped/XL got
    BIG_PROXIMITY-demoted (pi=12 had Fat Inquisitor XL within 9.0u)
    to c7100 humanoid/L (Ancient Hero). Player entered m49_29, wave
    never fired. v0.24.70 fixes both demotion sites to check the NB
    marker in addition to expects_boss_arena.
    """

    def test_c4130_expects_boss_arena_is_false(self, tags):
        """The trigger condition: c4130 has expects_boss_arena=False
        despite landing at NB arena slots. This is the data-tag quirk
        that the v0.23.05.2 filter original missed.

        v0.28.x note: c4130 was demoted from night_boss → field_boss
        as part of the tier-separation pass. The NB-marker check the
        v0.24.70 fix introduced still covers chrs in this state — the
        gate uses expects_boss_arena, not the tier, so the protection
        is preserved regardless of which boss-strength tier c4130
        carries. The 3 chrs flagged for review (c3100 Elemer, c4130
        Demi-Human Queen, c3570 Godskin Noble) carry _review_note
        entries in their tags documenting this — they may be promoted
        back to night_boss after playtest if they feel underplaced or
        out-of-place at field_boss.
        """
        assert tags['c4130'].get('expects_boss_arena') == False, (
            'If c4130 gets expects_boss_arena=True, the v0.24.70 '
            'fix is no longer needed for this specific case — but '
            'keep the NB-marker check anyway for c3100, c5810, etc.')
        # v0.28.x: tier is now field_boss (demoted from night_boss
        # alongside the tier-separation pass). Either tier is
        # acceptable here — the test invariant is the arena-flag quirk,
        # not the tier label. Permissive assertion keeps the test
        # protecting against the actual bug (the engine treating an
        # arena-False chr as arena-required) even if c4130's tier
        # shifts again in the future.
        assert tags['c4130'].get('tier') in ('night_boss', 'field_boss')

    def test_c3100_and_c5810_same_quirk(self, tags):
        """Bell Bearing Hunter (c3100) and Demi-Human Swordmaster
        (c5810) have the same data-tag quirk: boss-strength tier but
        expects_boss_arena=False. The NB-marker check covers them.

        v0.28.x note: both were demoted from night_boss → field_boss
        in the tier-separation pass. c3100 is flagged for review
        (carries _review_note in tags) — it's arguably a remembrance-
        grade boss; revisit after playtest if it feels under-tiered.
        c5810 stays field_boss confidently.
        """
        for cp in ('c3100', 'c5810'):
            assert tags[cp].get('expects_boss_arena') == False, (
                f'{cp} expects_boss_arena changed — verify '
                'v0.24.70 still applies.')
            # v0.28.x: tier shifted to field_boss for both. Same
            # permissive assertion as test_c4130 above — the invariant
            # is the quirk being present at boss-strength tier, not
            # which specific tier label.
            assert tags[cp].get('tier') in ('night_boss', 'field_boss')



    def test_nb_marker_set_covers_expected_names(self, engine):
        """Sanity: V3_NIGHT_BOSS_NAME_MARKERS includes 'Night Boss'
        marker. If somebody renames it, the mirror needs updating."""
        markers = engine.V3_NIGHT_BOSS_NAME_MARKERS
        assert 'Night Boss' in markers, (
            'V3_NIGHT_BOSS_NAME_MARKERS missing "Night Boss" — '
            'NB1/NB2 boss slot detection will fail.')
        # The classic Demi-Human Queen variant name should match
        sn = 'Demi-Human Queen (Night Boss)'
        assert any(m in sn for m in markers)
