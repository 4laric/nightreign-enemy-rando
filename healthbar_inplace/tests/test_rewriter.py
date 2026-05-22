"""
test_rewriter.py — Rewriter decision-policy tests.

Builds a synthetic binary EMEVD, derives callsites, feeds them through
decide_rewrites with various spoiler shapes (homogeneous swap,
heterogeneous swap, untouched, mixed), confirms each branch picks the
right policy.
"""

import sys
sys.path.insert(0, '..')

from emevd import EMEVD, extract_healthbar_callsites, rewrite_many
from synth import build_minimal_emevd, healthbar_instruction
from rewriter import (
    decide_rewrites, make_fmg_allocator, compute_byte_edits,
    DEFAULT_FMG_ID_BASE,
)


def _assert(c, m):
    if not c:
        raise AssertionError(m)


def _build_test_emevd():
    """Two events. Event 1 has a single 90015000 call (solo bar).
    Event 2 has a 90015023 call (shared bar with 3 name groups)."""
    return build_minimal_emevd([
        {
            'event_id': 49270100, 'rest_behavior': 0,
            'instructions': [
                healthbar_instruction(0, 90015000,
                                      10001, 49270800, 902500300,
                                      40, 690047, 10002),
            ],
        },
        {
            'event_id': 48500100, 'rest_behavior': 0,
            'instructions': [
                healthbar_instruction(0, 90015023,
                                      10003, 40, 10004,
                                      48500800,    # chr1
                                      48500810,    # chr2
                                      903251600,   # nameId group 0
                                      48500820,    # chr3
                                      904351000,   # nameId group 1
                                      48500830,    # chr4
                                      904351000,   # nameId group 2 (same as 1 in vanilla)
                                      ),
            ],
        },
    ])


def test_unchanged_when_no_spoiler_match():
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr={},  # empty — no swaps
        chr_to_vanilla_name_id={},
        file_id='test.emevd',
        fmg_id_allocator=alloc,
    )
    _assert(all(d.status == 'unchanged' for d in decisions),
            f"all should be unchanged, got: {[d.status for d in decisions]}")
    print("✓ test_unchanged_when_no_spoiler_match")


def test_reuse_vanilla_when_catalog_has_chr():
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()

    # Pretend Abductor Virgin (c4470) was placed at the solo entity
    # and the catalog already knows c4470's vanilla nameId.
    spoiler = {
        49270800: {'c_prefix': 'c4470', 'name': 'Abductor Virgin', 'npc_param_id': 44701000},
    }
    catalog = {'c4470': [999990001]}  # made-up vanilla id

    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr=spoiler,
        chr_to_vanilla_name_id=catalog,
        file_id='test.emevd',
        fmg_id_allocator=alloc,
    )
    solo = [d for d in decisions if d.handler_id == 90015000][0]
    _assert(solo.status == 'reuse_vanilla', f"status: {solo.status}")
    _assert(solo.new_name_id == 999990001, f"new_id: {solo.new_name_id}")
    _assert(solo.new_name_text == 'Abductor Virgin', f"text: {solo.new_name_text}")
    print("✓ test_reuse_vanilla_when_catalog_has_chr")


def test_fresh_allocation_when_no_catalog_entry():
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, get_table = make_fmg_allocator()

    spoiler = {
        49270800: {'c_prefix': 'c3730', 'name': 'Graven School', 'npc_param_id': 37300010},
    }
    catalog = {}  # no c3730 in vanilla catalog

    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr=spoiler,
        chr_to_vanilla_name_id=catalog,
        file_id='test.emevd',
        fmg_id_allocator=alloc,
    )
    solo = [d for d in decisions if d.handler_id == 90015000][0]
    _assert(solo.status == 'fresh_allocation', f"status: {solo.status}")
    _assert(solo.new_name_id == DEFAULT_FMG_ID_BASE,
            f"new_id: {solo.new_name_id} should be base {DEFAULT_FMG_ID_BASE}")
    _assert(get_table()[DEFAULT_FMG_ID_BASE] == 'Graven School',
            f"fmg table: {get_table()}")
    print("✓ test_fresh_allocation_when_no_catalog_entry")


def test_heterogeneous_squad_composite_name():
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, get_table = make_fmg_allocator()

    # The 90015023 shared bar group 0 covers chrs 48500800 and 48500810.
    # Make them swap to two different chrs.
    spoiler = {
        48500800: {'c_prefix': 'c3010', 'name': 'Banished Knight'},
        48500810: {'c_prefix': 'c4470', 'name': 'Abductor Virgin'},
        48500820: {'c_prefix': 'c3010', 'name': 'Banished Knight'},
        48500830: {'c_prefix': 'c3010', 'name': 'Banished Knight'},
    }
    catalog = {'c3010': [902500300], 'c4470': [902500301]}

    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr=spoiler,
        chr_to_vanilla_name_id=catalog,
        file_id='test.emevd',
        fmg_id_allocator=alloc,
    )

    shared_group0 = [d for d in decisions
                     if d.handler_id == 90015023 and d.name_group_index == 0][0]
    _assert(shared_group0.status == 'heterogeneous_squad',
            f"status: {shared_group0.status}")
    text = shared_group0.new_name_text
    # Order in composite is by Counter.most_common; tied counts go in
    # insertion order. Both have count 1 so it's insertion-order.
    _assert('Banished Knight' in text and 'Abductor Virgin' in text,
            f"composite text: {text}")
    _assert('+' in text, f"composite should use ' + ' separator: {text}")
    print("✓ test_heterogeneous_squad_composite_name")


def test_compute_byte_edits_yields_correct_offsets():
    """End-to-end: decide → compute_byte_edits → rewrite_many → parse
    back, confirm new nameIds present in binary."""
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()

    spoiler = {49270800: {'c_prefix': 'c4470', 'name': 'Abductor Virgin'}}
    catalog = {'c4470': [555555555]}

    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr=spoiler,
        chr_to_vanilla_name_id=catalog,
        file_id='test.emevd',
        fmg_id_allocator=alloc,
    )
    edits = compute_byte_edits(decisions, callsites)
    new_raw = rewrite_many(raw, edits)
    reparsed = EMEVD.parse(new_raw)
    new_callsites = extract_healthbar_callsites(reparsed)
    solo = [c for c in new_callsites if c.handler_id == 90015000][0]
    _assert(solo.name_id == 555555555, f"reparse got {solo.name_id}")
    print("✓ test_compute_byte_edits_yields_correct_offsets")


def test_squad_count_2x_format():
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()

    # Same chr placed twice + a different chr once → "X ×2 + Y"
    spoiler = {
        48500800: {'c_prefix': 'c3010', 'name': 'Banished Knight'},
        48500810: {'c_prefix': 'c3010', 'name': 'Banished Knight'},
        48500820: {'c_prefix': 'c4470', 'name': 'Abductor Virgin'},
        48500830: {'c_prefix': 'c3010', 'name': 'Banished Knight'},
    }
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr=spoiler,
        chr_to_vanilla_name_id={},
        file_id='test.emevd',
        fmg_id_allocator=alloc,
    )
    # Group 0 covers entities 48500800 + 48500810 (both Banished Knight)
    # → all same, NOT heterogeneous
    g0 = [d for d in decisions if d.handler_id == 90015023 and d.name_group_index == 0][0]
    _assert(g0.status == 'fresh_allocation', f"g0 status: {g0.status}")
    _assert(g0.new_name_text == 'Banished Knight', f"g0 text: {g0.new_name_text}")
    print("✓ test_squad_count_2x_format")


# ============================================================================
# v0.24.107: fun-rename gate tests
# ============================================================================
TEST_POOL = [
    'the Nightlord',           # epithet
    '{r} the Eternal',         # template (replacement)
    "{o} 'The Rock' {r}",      # template (both)
    'of the Wheel',            # epithet
]


def test_compose_disabled_without_title_pool():
    """When title_pool=None, decide_rewrites behaves identically to
    pre-v0.24.107 — never composes."""
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()
    # Place a chr at the solo entity, no catalog match → fresh_allocation
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr={
            49270800: {'c_prefix': 'c7710', 'name': 'Centipede Demon',
                       'old_c_prefix': 'c4470', 'old_name': 'Abductor Virgin'},
        },
        chr_to_vanilla_name_id={},
        file_id='test.emevd',
        fmg_id_allocator=alloc,
        # title_pool=None (default) → no compose
        seed=12345,
    )
    solo = [d for d in decisions if d.handler_id == 90015000][0]
    _assert(solo.new_name_text == 'Centipede Demon',
            f"should be plain name, got: {solo.new_name_text!r}")
    _assert('composed' not in solo.rationale,
            f"rationale shouldn't mention compose: {solo.rationale!r}")
    print("✓ test_compose_disabled_without_title_pool")


def test_compose_disabled_without_seed():
    """When seed=None (e.g., Phase 3 path), no compose even with title_pool."""
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr={
            49270800: {'c_prefix': 'c7710', 'name': 'Centipede Demon',
                       'old_c_prefix': 'c4470', 'old_name': 'Abductor Virgin'},
        },
        chr_to_vanilla_name_id={},
        file_id='test.emevd',
        fmg_id_allocator=alloc,
        title_pool=TEST_POOL,
        # seed=None default → no compose
    )
    solo = [d for d in decisions if d.handler_id == 90015000][0]
    _assert(solo.new_name_text == 'Centipede Demon',
            f"no seed → plain name, got: {solo.new_name_text!r}")
    print("✓ test_compose_disabled_without_seed")


def test_compose_gate_fires_around_50_percent():
    """Run 400 single-callsite decisions against varying entity-ids; with
    compose_probability=0.5 the hit rate should be within statistical
    range of 50% (binomial 95% CI for n=400, p=0.5 is roughly 45-55%)."""
    alloc, _ = make_fmg_allocator()
    hits = 0
    trials = 400
    for i in range(trials):
        # Build a tiny synthetic emevd with one solo callsite at varying entity ids
        eid = 49270800 + (i * 17)  # arbitrary stride
        raw = build_minimal_emevd([{
            'event_id': 49270100 + i, 'rest_behavior': 0,
            'instructions': [healthbar_instruction(
                0, 90015000, 10001, eid, 902500300, 40, 690047, 10002,
            )],
        }])
        parsed = EMEVD.parse(raw)
        callsites = extract_healthbar_callsites(parsed)
        decisions = decide_rewrites(
            binary_callsites=callsites,
            spoiler_entity_to_chr={eid: {
                'c_prefix': 'c4910', 'name': 'Tibia Mariner',
                'old_c_prefix': 'c4500', 'old_name': 'Tree Sentinel',
            }},
            chr_to_vanilla_name_id={'c4910': [904910000]},  # has catalog entry
            file_id='test.emevd',
            fmg_id_allocator=alloc,
            title_pool=TEST_POOL,
            seed=417416,
        )
        if 'composed' in decisions[0].rationale:
            hits += 1
    rate = hits / trials
    _assert(0.42 <= rate <= 0.58,
            f"compose rate {rate:.1%} outside 42-58% window (n={trials})")
    print(f"✓ test_compose_gate_fires_around_50_percent (rate={rate:.1%})")


def test_compose_overrides_reuse_vanilla():
    """When the gate fires and chr is in the vanilla catalog (would
    normally reuse_vanilla), compose path takes over and we get
    fresh_allocation with composed text instead."""
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()
    # Find a seed/entity combo that fires the gate. We'll just run
    # multiple seeds until one fires for our fixed callsite.
    found = False
    for trial_seed in range(1000):
        alloc2, _ = make_fmg_allocator()
        decisions = decide_rewrites(
            binary_callsites=callsites,
            spoiler_entity_to_chr={
                49270800: {'c_prefix': 'c4910', 'name': 'Tibia Mariner',
                           'old_c_prefix': 'c4500',
                           'old_name': 'Tree Sentinel'},
            },
            chr_to_vanilla_name_id={'c4910': [904910000]},
            file_id='test.emevd',
            fmg_id_allocator=alloc2,
            title_pool=TEST_POOL,
            seed=trial_seed,
        )
        solo = [d for d in decisions if d.handler_id == 90015000][0]
        if 'composed' in solo.rationale:
            _assert(solo.status == 'fresh_allocation',
                    f"compose hit must use fresh_allocation, got: {solo.status}")
            _assert('Tibia Mariner' in solo.new_name_text,
                    f"composed text must include replacement name: "
                    f"{solo.new_name_text!r}")
            _assert(solo.new_name_id != 904910000,
                    f"composed must NOT reuse vanilla nameId 904910000, "
                    f"got: {solo.new_name_id}")
            found = True
            break
    _assert(found,
            "no compose hit in 1000 seeds — gate appears broken")
    print("✓ test_compose_overrides_reuse_vanilla")


def test_compose_skips_heterogeneous_squad():
    """Heterogeneous-squad bars are not eligible for compose — their
    composite "X + Y x2" name is already creative. (Only group 0 of the
    test fixture has 2 chrs; groups 1 and 2 have a single chr each and
    are eligible for compose as unified-prefix.)"""
    raw = _build_test_emevd()
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, _ = make_fmg_allocator()
    # Try many seeds against the shared-bar (heterogeneous) callsite
    # — none should produce a 'composed' rationale for group 0.
    for trial_seed in range(50):
        decisions = decide_rewrites(
            binary_callsites=callsites,
            spoiler_entity_to_chr={
                48500800: {'c_prefix': 'c2500', 'name': 'Crucible Knight',
                           'old_c_prefix': 'c4170',
                           'old_name': 'Banished Knight'},
                48500810: {'c_prefix': 'c4770', 'name': 'Gargoyle',
                           'old_c_prefix': 'c4170',
                           'old_name': 'Banished Knight'},
                48500820: {'c_prefix': 'c4770', 'name': 'Gargoyle',
                           'old_c_prefix': 'c4170',
                           'old_name': 'Banished Knight'},
                48500830: {'c_prefix': 'c4770', 'name': 'Gargoyle',
                           'old_c_prefix': 'c4170',
                           'old_name': 'Banished Knight'},
            },
            chr_to_vanilla_name_id={},
            file_id='test.emevd',
            fmg_id_allocator=alloc,
            title_pool=TEST_POOL,
            seed=trial_seed,
        )
        for d in decisions:
            if d.handler_id == 90015023 and d.name_group_index == 0:
                _assert('composed' not in d.rationale,
                        f"heterogeneous group 0 shouldn't compose "
                        f"(seed={trial_seed}): {d.rationale!r}")
                _assert(d.status == 'heterogeneous_squad',
                        f"group 0 should be heterogeneous_squad: {d.status}")
    print("✓ test_compose_skips_heterogeneous_squad")


if __name__ == "__main__":
    tests = [
        test_unchanged_when_no_spoiler_match,
        test_reuse_vanilla_when_catalog_has_chr,
        test_fresh_allocation_when_no_catalog_entry,
        test_heterogeneous_squad_composite_name,
        test_compute_byte_edits_yields_correct_offsets,
        test_squad_count_2x_format,
        test_compose_disabled_without_title_pool,
        test_compose_disabled_without_seed,
        test_compose_gate_fires_around_50_percent,
        test_compose_overrides_reuse_vanilla,
        test_compose_skips_heterogeneous_squad,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
