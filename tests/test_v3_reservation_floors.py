"""Tests for v0.26.x floor/ceiling cap split.

The single cap constant V3_UNIQUE_TARGET_CAPS was historically doing
two jobs at once:
  (1) reservation-pre-pass floor — "try to seat at least N quality
      slots for this chr" (a minimum-guarantee semantic)
  (2) runtime ceiling — "never have more than N placements per seed"
      (a max-allowed semantic)

v0.26.x split (1) out into V3_RESERVATION_FLOORS while (2) remains
under V3_UNIQUE_TARGET_CAPS (kept as the ceiling source for backward
compatibility with the many existing call sites).

This file guards the invariants of the split + the policy:
  - night_boss tier (+ NB-caliber MMV) get floor=1, ceiling=2
  - everyone else: ceiling-only (no floor entry)
  - exception: c7910 Storm King NOT in floors (paired-only with c7900)
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


@pytest.fixture(scope='module')
def engine():
    import oops_v3
    return oops_v3


@pytest.fixture(scope='module')
def tags(engine):
    _, t = engine.load_data()
    return t


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

class TestFloorCeilingStructural:
    """Basic shape + invariant checks for the two constants."""

    def test_floors_is_dict_of_positive_ints(self, engine):
        assert isinstance(engine.V3_RESERVATION_FLOORS, dict)
        assert engine.V3_RESERVATION_FLOORS, \
            'V3_RESERVATION_FLOORS should not be empty'
        for cp, floor in engine.V3_RESERVATION_FLOORS.items():
            assert isinstance(cp, str) and cp.startswith('c'), \
                f'Floor key {cp!r} should be a c-prefix string'
            assert isinstance(floor, int) and floor > 0, \
                f'Floor value for {cp} should be a positive int, got {floor!r}'

    def test_every_floor_has_a_ceiling(self, engine):
        """A chr in FLOORS must also have a CEILINGS entry — the
        reservation pre-pass would otherwise try to seat slots with
        no enforcement ceiling above it."""
        missing = [cp for cp in engine.V3_RESERVATION_FLOORS
                   if cp not in engine.V3_UNIQUE_TARGET_CAPS]
        assert not missing, (
            f'{len(missing)} chrs in V3_RESERVATION_FLOORS lack a '
            f'V3_UNIQUE_TARGET_CAPS ceiling: {sorted(missing)}')

    def test_floor_le_ceiling(self, engine):
        """floor <= ceiling for every chr in floors. Floor > ceiling
        would be a contradiction (can't guarantee N if max is < N)."""
        violations = []
        for cp, floor in engine.V3_RESERVATION_FLOORS.items():
            ceiling = engine.V3_UNIQUE_TARGET_CAPS.get(cp)
            if ceiling is None or floor > ceiling:
                violations.append((cp, floor, ceiling))
        assert not violations, (
            f'Floor > ceiling violations: {violations}. Floors must be '
            f'<= ceilings — would otherwise be unsatisfiable by design.')


# ---------------------------------------------------------------------------
# Policy: all night_boss-tier chrs have floor=1, ceiling=2
# ---------------------------------------------------------------------------

class TestNightBossFloorPolicy:
    """v0.26.x initial policy: every night_boss-tier chr (NR + heritage +
    MMV NB-caliber) gets floor=1 and ceiling=2. Storm King c7910 is the
    documented exception (paired-only with c7900)."""

    def test_storm_king_excluded_from_floors(self, engine):
        """c7910 Storm King paired-only with c7900 in vanilla. If we
        gave it floor=1, the reservation pass would seat it
        independently of c7900 — divorcing rider and mount across
        slots."""
        assert 'c7910' not in engine.V3_RESERVATION_FLOORS, (
            'c7910 Storm King should NOT have a reservation floor — '
            'paired-only with c7900 Nameless King in vanilla; independent '
            'reservation risks divorcing them across slots.')

    def test_storm_king_ceiling_is_1(self, engine):
        """The pairing constraint also applies to the ceiling — c7910
        capped at 1 ensures Storm King only appears via the c7900
        reservation's vanilla pairing."""
        assert engine.V3_UNIQUE_TARGET_CAPS.get('c7910') == 1, (
            'c7910 Storm King ceiling should be 1 (paired-only mount).')

    def test_marquee_nb_roster_has_floors(self, engine):
        """v0.26.x initial-policy marquee NB roster — the specific chrs
        that should always appear at least once per seed.

        Tier-sweep ("every chr with tier='night_boss' gets floor=1")
        was attempted but rejected: V3_TAG_OVERRIDES flatten brought
        many field-boss-routed-as-NB chrs (Trolls cap=6, Avatars,
        Dragons, etc.) into tier='night_boss' for engine-routing
        purposes. Those aren't the marquee roster Alaric meant —
        they get ceiling-only enforcement at their existing cap=6 /
        cap=2 values, no floor.

        Enumeration is the source of truth. Update this list when
        chrs join/leave the marquee roster."""
        marquee = {
            # NR vanilla named NB roster
            'c2130', 'c2500', 'c3050', 'c3100', 'c3560', 'c3570',
            'c4130', 'c4510', 'c4580', 'c4750', 'c4911',
            'c5011', 'c5810',
            # DS-heritage NB arena residents (reclassified v0.26.x)
            'c7700', 'c7710', 'c7820', 'c7900', 'c7920',
            # NB-caliber MMV imports
            'c4511', 'c5000', 'c5030', 'c5051', 'c5200', 'c8300',
            # v0.26.x-late: c3250, c3251, c4640, c4650, c4680, c4770,
            # c4980 unfloored — field-tier or generic large enemies
            # that compete freely with M-humanoid marquee NBs in the
            # XXL/GIGA slot pool post-M-lift. They keep ceiling=2 from
            # V3_UNIQUE_TARGET_CAPS but no floor.
        }
        floors = set(engine.V3_RESERVATION_FLOORS)
        missing = marquee - floors
        extra = floors - marquee
        assert not missing, (
            f'{len(missing)} marquee NB chrs missing from '
            f'V3_RESERVATION_FLOORS: {sorted(missing)}. Either add them '
            f'to the FLOORS dict or remove from the marquee list here.')
        # v0.27.3 deliberately added floor=1 to the whole miniboss
        # tier (76 chrs) on top of the marquee NB set, so FLOORS is now
        # a superset of `marquee`. The old "no extra" discipline check
        # is dropped — this test now only guards that every marquee NB
        # still carries a floor.
        _ = extra  # informational only

    def test_nb_caliber_mmv_imports_have_floor_1(self, engine):
        """NB-caliber MMV imports (Lichdragon Fortissax, Commander Gaius,
        Romina, Midra, Metyr, Dragonslayer Armor) should also have
        floor=1 alongside vanilla night_boss tier. These chrs are loaded
        by mmv_imports pack-loader at runtime (not in nr_enemy_tags.json)
        so the tier-based check above doesn't cover them — explicit list
        here."""
        nb_caliber_mmv = ['c4511', 'c5000', 'c5030', 'c5051', 'c5200', 'c8300']
        for cp in nb_caliber_mmv:
            assert engine.V3_RESERVATION_FLOORS.get(cp) == 1, (
                f'{cp} (NB-caliber MMV) should have floor=1; got '
                f'{engine.V3_RESERVATION_FLOORS.get(cp)!r}')

    def test_floored_chrs_have_a_ceiling(self, engine, tags):
        """v0.27.3 superseded the v0.26.x "all floored chrs ceiling=2"
        rule. The miniboss-tier floor pass gives each tier its own
        ceiling — marquee NB stays at 2, the newly-floored miniboss
        tier defaults to 6, and chrs with a pre-existing explicit cap
        keep it (some at 1 or 8). The invariant that still matters:
        every chr with a reservation FLOOR also has a finite CEILING,
        so the floor=1 guarantee is always bracketed by a cap — a
        floor with no ceiling would be an unbounded guarantee."""
        violations = []
        for cp in engine.V3_RESERVATION_FLOORS:
            ceiling = engine.V3_UNIQUE_TARGET_CAPS.get(cp)
            if ceiling is None:
                violations.append((cp, ceiling))
        assert not violations, (
            f'{len(violations)} V3_RESERVATION_FLOORS chrs have NO ceiling: '
            f'{violations}. Every floored chr must also carry a cap '
            f'in V3_UNIQUE_TARGET_CAPS to bound the guarantee.')


# ---------------------------------------------------------------------------
# Policy: non-night-boss tiers have NO floor (ceiling-only)
# ---------------------------------------------------------------------------

class TestNonNightBossCeilingOnly:
    """v0.27.x policy: field-bosses get ceiling-only enforcement (no
    reservation guarantee). Mini-bosses (v0.27.3) and grunts incl. the
    collapsed trash tier (v0.27.8) now carry reservation floors."""

    @pytest.mark.parametrize('cp,name', [
        # v0.27.3: miniboss tier (Royal Revenant, Grafted Scion, Land
        # Squirt, ...) carries floor=1 — removed from this list.
        # v0.27.8: grunt + trash tiers carry floor=4 — c4240/c4442/c4170
        # removed too. Only field_boss remains ceiling-only.
        ('c4500', 'Flying Dragon'),    # field_boss
        ('c4503', 'Borealis'),         # field_boss
        ('c4620', 'Astel'),            # field_boss
    ])
    def test_no_floor_for(self, engine, cp, name):
        assert cp not in engine.V3_RESERVATION_FLOORS, (
            f'{cp} ({name}) should NOT have a reservation floor — '
            f'non-night-boss tiers are ceiling-only per v0.26.x policy.')


# ---------------------------------------------------------------------------
# V3_DEDICATED_ARENA_BOSS_CHRS — the new arena-only gate
# ---------------------------------------------------------------------------

class TestDedicatedArenaBossChrs:
    """v0.26.x replaced the _source='script_spawn' arena-only signal
    with explicit V3_DEDICATED_ARENA_BOSS_CHRS membership after the
    byte-level MSB audit reclassified those chrs to nr_placed."""

    def test_contains_known_arena_residents(self, engine):
        """Documented residents of m47_xx/m48_xx/m19_xx boss arenas.
        Per the v0.26.x audit (dev/audit_source_tags.py against
        vanilla NR MSBs)."""
        expected = {
            # v0.27.2: c4670 Ancestor Spirit + c7910 Storm King lifted
            # from V3_DEDICATED_ARENA_BOSS_CHRS (returned as placeable
            # cap=1 bosses) — removed from this baseline.
            'c7700',   # Gaping Dragon       @ m47_80
            'c7710',   # Centipede Demon     @ m47_90
            'c7800',   # Duke's Dear Freja   @ m48_00
            'c7820',   # Smelter Demon       @ m48_10
            'c7900',   # Nameless King       @ m48_20 + m19_00
            'c7920',   # Dancer of the Boreal Valley @ m48_30
        }
        actual = set(engine.V3_DEDICATED_ARENA_BOSS_CHRS)
        missing = expected - actual
        extra = actual - expected
        assert not missing, f'Missing arena chrs: {missing}'
        # Extra is allowed (future additions); just document it
        if extra:
            # not a failure; informational
            print(f'V3_DEDICATED_ARENA_BOSS_CHRS has {len(extra)} '
                  f'chrs beyond the v0.26.x baseline: {sorted(extra)}')

    def test_grunt_supporting_cast_NOT_in_set(self, engine):
        """c7711/c7712 Centipede Grubs and c7810 Freja Spiderling are
        grunt-tier and not load-time CTD risk — they share their boss
        parent's chrbnd. Should NOT be in the strict arena set."""
        for cp in ('c7711', 'c7712', 'c7810'):
            assert cp not in engine.V3_DEDICATED_ARENA_BOSS_CHRS, (
                f'{cp} is grunt-tier supporting cast — should NOT be '
                f'in V3_DEDICATED_ARENA_BOSS_CHRS (gate is for the '
                f'boss-tier parents only).')

    def test_arena_set_is_in_arena_only_targets(self, engine):
        """After load_data runs the auto-extension, every chr in
        V3_DEDICATED_ARENA_BOSS_CHRS should be in V3_ARENA_ONLY_TARGETS
        — the auto-add merges them in."""
        # Trigger load_data so auto-extension runs
        engine.load_data()
        for cp in engine.V3_DEDICATED_ARENA_BOSS_CHRS:
            assert cp in engine.V3_ARENA_ONLY_TARGETS, (
                f'{cp} in V3_DEDICATED_ARENA_BOSS_CHRS but NOT in '
                f'V3_ARENA_ONLY_TARGETS after load_data — auto-extend '
                f'block at line ~2935 may have regressed.')
