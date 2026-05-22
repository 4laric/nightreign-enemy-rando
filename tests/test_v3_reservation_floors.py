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
        # Extra is also a fail — keeps the marquee policy explicit and
        # disciplined. Adding a new floor should be a deliberate roster
        # decision, not a drive-by.
        assert not extra, (
            f'{len(extra)} chrs in V3_RESERVATION_FLOORS not on the '
            f'marquee list: {sorted(extra)}. If intentional, add them '
            f'to the marquee set in this test with rationale comment.')

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

    def test_night_boss_ceilings_normalized_to_2(self, engine, tags):
        """v0.26.x policy: night_boss-tier ceilings normalized to 2 for
        the marquee NB roster. Excluded from this rule:
          - c7910 Storm King (paired-only, stays at 1)
          - c4353 Leyndell Knight (retiered miniboss, cap=6 filler stays)
          - "flood-prone" night_boss-tier chrs that were field-boss-
            previously and now run as NB but with elevated ceilings
            (Trolls cap=6, Fire Knight cap=6, etc.) — they get
            ceiling-only enforcement with their existing higher caps,
            no floor.

        The policy applies to chrs in V3_RESERVATION_FLOORS specifically
        (i.e., the chrs we DO want guaranteed) — their ceilings should
        be 2 to bracket the floor=1 guarantee."""
        violations = []
        for cp in engine.V3_RESERVATION_FLOORS:
            ceiling = engine.V3_UNIQUE_TARGET_CAPS.get(cp)
            if ceiling != 2:
                violations.append((cp, ceiling))
        assert not violations, (
            f'{len(violations)} V3_RESERVATION_FLOORS chrs have ceilings != 2: '
            f'{violations}. Expected: all floored chrs ceiling=2 '
            f'(floor=1 + ceiling=2 = "guarantee 1, allow up to 2").')


# ---------------------------------------------------------------------------
# Policy: non-night-boss tiers have NO floor (ceiling-only)
# ---------------------------------------------------------------------------

class TestNonNightBossCeilingOnly:
    """v0.26.x policy: mini-bosses, grunts, field-bosses, trash get
    ceiling-only enforcement — no reservation guarantee."""

    @pytest.mark.parametrize('cp,name', [
        ('c4020', 'Royal Revenant'),   # miniboss
        ('c4690', 'Grafted Scion'),    # miniboss
        ('c4441', 'Land Squirt'),      # miniboss
        ('c4240', 'Fingercreeper'),    # grunt
        ('c4442', 'Land Squirt Var'),  # grunt
        ('c4170', 'Putrid Flesh'),     # trash
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
            'c4670',   # Ancestor Spirit
            'c7700',   # Gaping Dragon       @ m47_80
            'c7710',   # Centipede Demon     @ m47_90
            'c7800',   # Duke's Dear Freja   @ m48_00
            'c7820',   # Smelter Demon       @ m48_10
            'c7900',   # Nameless King       @ m48_20 + m19_00
            'c7910',   # Storm King          @ m48_20 + m19_00
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
