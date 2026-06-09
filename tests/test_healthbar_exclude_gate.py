"""Regression test: the healthbar nameId exclude gate must stay in
lock-step with the enemy-swap gate (engine.picker._force_rando_nb).

Background — the "Beast Clergyman labeled Night's Cavalry" bug:
`dcx_batch.night_boss_hb_exclude` decides which night-boss-arena EMEVDs
ship byte-vanilla (excluded from healthbar patching). The MSB-side
`_force_rando_nb` decides which night-boss arenas get their boss Part
swapped. If an arena is randomized (boss swapped) but ALSO excluded from
healthbar patching, its bar keeps the vanilla nameId while the enemy
changes — the reported symptom. These two gates must agree: an arena is
excluded from healthbar patching IFF its boss is NOT randomized.
"""
import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dcx_batch import night_boss_hb_exclude  # noqa: E402

ALL_NB = (
    'm48_60_00_00.msb', 'm48_80_00_00.msb', 'm49_24_00_00.msb',
    'm49_10_00_00.msb', 'm49_28_00_00.msb', 'm47_70_00_00.msb',
)
SAFE = frozenset({'m49_10_00_00.msb', 'm49_28_00_00.msb'})


def _emevd(msbs):
    return {m.replace('.msb', '.emevd') for m in msbs}


def _fake(*, whitelist=frozenset(), all_nb=False, safe=False):
    return SimpleNamespace(
        V3_NIGHT_BOSS_ARENA_MSBS=ALL_NB,
        V3_NB_RANDOMIZE_WHITELIST=frozenset(whitelist),
        V3_SAFE_NB_RANDOMIZE_MSBS=SAFE,
        V3_RANDOMIZE_ALL_NB_ARENAS=all_nb,
        V3_RANDOMIZE_SAFE_NB_ARENAS=safe,
    )


def _force_rando_nb_mirror(msb, o):
    """Mirror of engine.picker._force_rando_nb (boss-swap gate)."""
    return (
        (o.V3_RANDOMIZE_ALL_NB_ARENAS and msb in o.V3_NIGHT_BOSS_ARENA_MSBS)
        or (o.V3_RANDOMIZE_SAFE_NB_ARENAS and msb in o.V3_SAFE_NB_RANDOMIZE_MSBS)
        or msb in o.V3_NB_RANDOMIZE_WHITELIST)


def test_empty_whitelist_excludes_everything():
    # Today's default preserve behavior: nothing randomized -> all excluded.
    o = _fake()
    assert night_boss_hb_exclude(o) == _emevd(ALL_NB)


def test_whitelisted_arena_is_not_excluded():
    # The actual bug: m48_60 is randomized via whitelist, so it MUST flow
    # through the healthbar patcher (NOT be excluded).
    o = _fake(whitelist={'m48_60_00_00.msb'})
    excl = night_boss_hb_exclude(o)
    assert 'm48_60_00_00.emevd' not in excl
    assert 'm48_80_00_00.emevd' in excl  # untouched arena still preserved


def test_randomize_all_excludes_nothing():
    o = _fake(all_nb=True)
    assert night_boss_hb_exclude(o) == set()


def test_randomize_safe_excludes_only_non_safe():
    o = _fake(safe=True)
    excl = night_boss_hb_exclude(o)
    assert excl == _emevd(set(ALL_NB) - SAFE)


def test_gates_are_in_lockstep():
    # The invariant that prevents the bug: an arena is excluded from
    # healthbar patching IFF its boss is NOT randomized, across every
    # flag combination.
    for whitelist in (frozenset(), {'m48_60_00_00.msb'}, set(ALL_NB)):
        for all_nb in (False, True):
            for safe in (False, True):
                o = _fake(whitelist=whitelist, all_nb=all_nb, safe=safe)
                excl = night_boss_hb_exclude(o)
                for msb in ALL_NB:
                    emevd = msb.replace('.msb', '.emevd')
                    randomized = _force_rando_nb_mirror(msb, o)
                    assert (emevd in excl) == (not randomized), (
                        f"{msb}: excluded={emevd in excl} "
                        f"randomized={randomized} (must be opposites)")
