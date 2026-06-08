"""test_rewriter_fuzz.py — property / fuzz tests for the healthbar rewrite
path (decide_rewrites -> compute_byte_edits -> rewrite_many).

The unit tests in test_rewriter.py exercise each decision branch with a
hand-built EMEVD. This file throws hundreds of randomized configurations
at the same pipeline — varying event count, solo vs shared bars, which
entities the spoiler swaps, which c-prefixes have a vanilla nameId, and
the fun-rename compose settings — and asserts the invariants that must
hold for EVERY configuration:

  * decide_rewrites never raises and returns one decision per callsite
  * a swapped bar never gets empty display text (would render a blank bar)
  * every emitted nameId is a valid uint32; fresh/composite IDs land at
    or above the allocation base; reuse_vanilla IDs come from the catalog
  * compute_byte_edits never produces overlapping edits; rewrite_many
    succeeds, the result re-parses cleanly, and the nameIds present after
    the rewrite are exactly the multiset the decisions chose
  * the whole thing is deterministic: identical inputs -> identical output

Run from the tests/ directory (mirrors sibling test_rewriter.py):
    cd healthbar_inplace/tests && python3 -m pytest test_rewriter_fuzz.py
"""
import random
import sys

sys.path.insert(0, '..')

from emevd import EMEVD, extract_healthbar_callsites, rewrite_many  # noqa: E402
from synth import build_minimal_emevd, healthbar_instruction        # noqa: E402
from rewriter import (                                               # noqa: E402
    decide_rewrites, make_fmg_allocator, compute_byte_edits,
    DEFAULT_FMG_ID_BASE,
)

UINT32 = 1 << 32
VALID_STATUS = {'unchanged', 'reuse_vanilla', 'fresh_allocation',
                'heterogeneous_squad'}

CHR_POOL = [
    ('c3010', 'Banished Knight'), ('c4470', 'Abductor Virgin'),
    ('c2110', 'Beast Clergyman'), ('c3730', 'Graven School'),
    ('c3150', "Night's Cavalry"), ('c4500', 'Tibia Mariner'),
    ('c2240', 'Unicode Boss'), ('c5260', 'Tree Sentinel'),
]
TITLE_POOL = ['the Nightlord', '{r} the Eternal', "{o} 'X' {r}", 'of the Wheel']


def _solo_event(rng, eid_pool):
    chr_eid = eid_pool.pop()
    return {
        'event_id': rng.randint(40000000, 49999999), 'rest_behavior': 0,
        'instructions': [healthbar_instruction(
            0, 90015000, 10001, chr_eid, 902500300, 40, 690047, 10002)],
    }, [chr_eid]


def _shared_event(rng, eid_pool):
    c1, c2, c3, c4 = (eid_pool.pop(), eid_pool.pop(),
                      eid_pool.pop(), eid_pool.pop())
    return {
        'event_id': rng.randint(40000000, 49999999), 'rest_behavior': 0,
        'instructions': [healthbar_instruction(
            0, 90015023, 10003, 40, 10004,
            c1, c2, 903251600, c3, 904351000, c4, 904351000)],
    }, [c1, c2, c3, c4]


def _build_case(rng):
    n_events = rng.randint(1, 6)
    eid_pool = rng.sample(range(10_000_000, 99_999_999), n_events * 4 + 4)
    specs, tracked = [], []
    for _ in range(n_events):
        spec, eids = (rng.choice((_solo_event, _shared_event)))(rng, eid_pool)
        specs.append(spec)
        tracked.extend(eids)
    return build_minimal_emevd(specs), tracked


def _random_spoiler(rng, tracked):
    spoiler = {}
    for eid in tracked:
        if rng.random() < 0.7:
            cp, name = rng.choice(CHR_POOL)
            spoiler[eid] = {'c_prefix': cp, 'name': name,
                            'old_name': rng.choice(['Tree Sentinel', '']),
                            'old_c_prefix': 'c3251'}
    return spoiler


def _random_catalog(rng):
    cat = {}
    next_id = 902000000
    for cp, _ in CHR_POOL:
        if rng.random() < 0.5:
            cat[cp] = [next_id]
            next_id += 1
    return cat


def _decide(raw, spoiler, catalog, *, title_pool, seed, prob):
    parsed = EMEVD.parse(raw)
    callsites = extract_healthbar_callsites(parsed)
    alloc, get_table = make_fmg_allocator()
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr=spoiler,
        chr_to_vanilla_name_id=catalog,
        file_id='fuzz.emevd',
        fmg_id_allocator=alloc,
        title_pool=title_pool, seed=seed, compose_probability=prob,
    )
    return parsed, callsites, decisions, get_table()


def test_fuzz_invariants():
    rng = random.Random(0xF1227)
    cases = 0
    for _ in range(300):
        raw, tracked = _build_case(rng)
        spoiler = _random_spoiler(rng, tracked)
        catalog = _random_catalog(rng)
        title_pool = TITLE_POOL if rng.random() < 0.5 else None
        seed = rng.randint(1, 10**9) if rng.random() < 0.8 else None
        prob = rng.choice([0.0, 0.25, 0.5, 1.0])

        parsed, callsites, decisions, table = _decide(
            raw, spoiler, catalog, title_pool=title_pool, seed=seed, prob=prob)

        assert len(decisions) == len(callsites)

        catalog_ids = {i for ids in catalog.values() for i in ids}
        for d in decisions:
            assert d.status in VALID_STATUS, d.status
            assert 0 <= d.new_name_id < UINT32, d.new_name_id
            present = any(spoiler.get(e) for e in d.chr_entity_ids_after_swap)
            if d.status != 'unchanged' and present:
                assert d.new_name_text, f"blank bar text for {d}"
            if d.status == 'reuse_vanilla':
                assert d.new_name_id in catalog_ids
            elif d.status in ('fresh_allocation', 'heterogeneous_squad'):
                assert d.new_name_id >= DEFAULT_FMG_ID_BASE

        # byte-edit + rewrite roundtrip. synth EMEVDs don't surface a
        # stable event_id on re-extract, so assert on the multiset of
        # nameIds: after rewrite, the nameIds at the healthbar callsites
        # must be exactly the set the decisions chose.
        edits = compute_byte_edits(decisions, callsites)
        new_raw = rewrite_many(raw, edits)
        reparsed = EMEVD.parse(new_raw)
        new_ids = sorted(c.name_id
                         for c in extract_healthbar_callsites(reparsed))
        assert new_ids == sorted(d.new_name_id for d in decisions)

        # determinism: same inputs -> identical decisions + fmg table
        _, _, decisions2, table2 = _decide(
            raw, spoiler, catalog, title_pool=title_pool, seed=seed, prob=prob)
        assert [vars(d) for d in decisions] == [vars(d) for d in decisions2]
        assert table == table2
        cases += 1
    assert cases == 300


def test_fuzz_no_overlapping_edits_even_with_dense_shared_bars():
    """All-shared-bar EMEVDs with every entity swapped — the densest edit
    layout — must still yield non-overlapping byte edits."""
    rng = random.Random(99)
    for _ in range(100):
        eid_pool = rng.sample(range(10_000_000, 99_999_999), 24)
        specs, tracked = [], []
        for _ in range(rng.randint(1, 5)):
            spec, eids = _shared_event(rng, eid_pool)
            specs.append(spec)
            tracked.extend(eids)
        raw = build_minimal_emevd(specs)
        spoiler = {e: {'c_prefix': c, 'name': n}
                   for e in tracked for c, n in [rng.choice(CHR_POOL)]}
        parsed = EMEVD.parse(raw)
        callsites = extract_healthbar_callsites(parsed)
        alloc, _ = make_fmg_allocator()
        decisions = decide_rewrites(
            binary_callsites=callsites, spoiler_entity_to_chr=spoiler,
            chr_to_vanilla_name_id={}, file_id='f.emevd', fmg_id_allocator=alloc)
        edits = compute_byte_edits(decisions, callsites)
        rewrite_many(raw, edits)
