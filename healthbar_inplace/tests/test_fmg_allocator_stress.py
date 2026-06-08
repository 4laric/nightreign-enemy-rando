"""test_fmg_allocator_stress.py — stress / property tests for the FMG
nameId allocator (rewriter.make_fmg_allocator).

The allocator hands out fresh uint32 nameIds for healthbar text the
randomizer must splice into NpcName.fmg. Its safety contract is load-
bearing: a duplicate, out-of-range, or vanilla-colliding ID renders the
wrong string (or `?NpcName?`) on a boss healthbar. These tests hammer
the contract that the unit tests in test_rewriter.py only touch lightly:

  * idempotency on identical text (any order, heavy duplication)
  * distinct text -> distinct, contiguous IDs from `base`
  * get_table() stays consistent with what was handed out
  * uint32 ceiling raises OverflowError and never emits an out-of-range ID
  * fresh IDs never collide with committed vanilla nameIds (real data
    from data/chr_to_nameid.json) within the available headroom
  * fallback_id mode short-circuits cleanly (empty table)
  * pathological text (empty / unicode / newlines / very long) is fine

Run from the tests/ directory (mirrors sibling test_rewriter.py):
    cd healthbar_inplace/tests && python3 -m pytest test_fmg_allocator_stress.py
"""
import json
import os
import random
import sys

sys.path.insert(0, '..')

from rewriter import make_fmg_allocator, DEFAULT_FMG_ID_BASE  # noqa: E402

UINT32 = 1 << 32
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHR_TO_NAMEID = os.path.join(REPO_ROOT, 'data', 'chr_to_nameid.json')


def _vanilla_nameids():
    """Every committed vanilla nameId the rewriter may reuse."""
    with open(CHR_TO_NAMEID, encoding='utf-8') as f:
        d = json.load(f)
    ids = set()
    for v in d.values():
        if v is None:
            continue
        if isinstance(v, list):
            ids.update(x for x in v if isinstance(x, int) and x > 0)
        elif isinstance(v, int) and v > 0:
            ids.add(v)
    return ids


# ── idempotency / uniqueness / contiguity ─────────────────────────────

def test_idempotent_under_heavy_duplication_and_shuffle():
    alloc, get_table = make_fmg_allocator()
    rng = random.Random(1234)
    unique = [f"Boss #{i}" for i in range(500)]
    # 20k calls, ~40x duplication, shuffled
    seq = [rng.choice(unique) for _ in range(20000)]
    first_seen = {}
    for text in seq:
        nid = alloc(text)
        if text in first_seen:
            assert nid == first_seen[text], f"id drifted for {text!r}"
        else:
            first_seen[text] = nid
    # every distinct text that actually appeared got exactly one id
    appeared = set(seq)
    assert set(first_seen) == appeared
    assert len(set(first_seen.values())) == len(appeared), "duplicate IDs issued"


def test_ids_are_contiguous_from_base_in_first_seen_order():
    alloc, _ = make_fmg_allocator(base=DEFAULT_FMG_ID_BASE)
    texts = [f"name-{i}" for i in range(2000)]
    ids = [alloc(t) for t in texts]  # all distinct, in order
    assert ids == list(range(DEFAULT_FMG_ID_BASE, DEFAULT_FMG_ID_BASE + 2000))


def test_table_matches_issued_ids_exactly():
    alloc, get_table = make_fmg_allocator()
    rng = random.Random(7)
    texts = [f"t{rng.randint(0, 999)}" for _ in range(5000)]
    issued = {}
    for t in texts:
        issued[t] = alloc(t)
    table = get_table()
    # one table entry per unique text, id->text is the inverse of text->id
    assert len(table) == len(issued)
    for text, nid in issued.items():
        assert table[nid] == text
    # no duplicate IDs in the table keys
    assert len(set(table)) == len(table)


def test_get_table_is_a_snapshot_copy():
    alloc, get_table = make_fmg_allocator()
    alloc("a")
    t1 = get_table()
    alloc("b")
    assert "a" in t1.values() and "b" not in t1.values(), "table not a copy"


# ── determinism ───────────────────────────────────────────────────────

def test_same_sequence_two_allocators_identical_mapping():
    texts = [f"x{i}" for i in range(1000)]
    a1, g1 = make_fmg_allocator()
    a2, g2 = make_fmg_allocator()
    for t in texts:
        a1(t)
    for t in texts:
        a2(t)
    assert g1() == g2()


# ── uint32 ceiling ────────────────────────────────────────────────────

def test_overflow_raises_at_ceiling_and_never_emits_out_of_range():
    base = UINT32 - 3            # room for exactly 3 IDs: 2^32-3, -2, -1
    alloc, _ = make_fmg_allocator(base=base)
    got = [alloc("a"), alloc("b"), alloc("c")]
    assert got == [base, base + 1, base + 2]
    assert all(g < UINT32 for g in got)
    try:
        alloc("d")
    except OverflowError:
        pass
    else:
        raise AssertionError("expected OverflowError at uint32 ceiling")


def test_realistic_volume_stays_in_uint32_from_default_base():
    alloc, _ = make_fmg_allocator()
    last = alloc("z" * 0)  # base
    for i in range(1, 10000):
        last = alloc(f"name-{i}")
    assert last < UINT32


# ── collision with vanilla nameIds (real committed data) ──────────────

def test_base_sits_below_nearest_vanilla_id_above_it():
    vanilla = _vanilla_nameids()
    above = sorted(v for v in vanilla if v >= DEFAULT_FMG_ID_BASE)
    assert above, "expected some vanilla nameIds at/above the base"
    headroom = above[0] - DEFAULT_FMG_ID_BASE
    # The base must live in a real gap; if this shrinks toward zero the
    # band has drifted and fresh allocations risk shadowing a vanilla group.
    assert headroom > 0, (
        f"base {DEFAULT_FMG_ID_BASE} collides with vanilla id {above[0]}")
    assert headroom >= 1000, (
        f"only {headroom} IDs of headroom before vanilla id {above[0]}; "
        f"base may have drifted into a claimed FMG range")


def test_fresh_ids_disjoint_from_vanilla_within_headroom():
    vanilla = _vanilla_nameids()
    above = sorted(v for v in vanilla if v >= DEFAULT_FMG_ID_BASE)
    headroom = above[0] - DEFAULT_FMG_ID_BASE
    # Allocate up to (but not into) the next vanilla id; assert disjoint.
    n = min(headroom, 50000)
    alloc, get_table = make_fmg_allocator()
    for i in range(n):
        alloc(f"stress-{i}")
    issued = set(get_table())
    assert issued.isdisjoint(vanilla), (
        f"fresh IDs collided with vanilla: "
        f"{sorted(issued & vanilla)[:5]}")
    assert max(issued) < above[0]


# ── fallback_id mode ──────────────────────────────────────────────────

def test_fallback_mode_returns_constant_and_empty_table():
    FALLBACK = 902130014
    alloc, get_table = make_fmg_allocator(fallback_id=FALLBACK)
    for t in ["a", "b", "a", "", "x" * 500, "ünïçødé"]:
        assert alloc(t) == FALLBACK
    assert get_table() == {}, "fallback mode must not populate the splice table"


# ── pathological text ─────────────────────────────────────────────────

def test_weird_text_keys_are_handled_and_idempotent():
    alloc, get_table = make_fmg_allocator()
    weird = ["", " ", "\n", "\t\r\n", "x" * 5000, "ünïçødé ✦ 龍",
             "Tree Sentinel → Tibia Mariner", "name", "name "]  # trailing-space distinct
    ids = {t: alloc(t) for t in weird}
    # distinct keys -> distinct ids (incl. "name" vs "name ")
    assert len(set(ids.values())) == len(weird)
    # idempotent on re-call
    for t in weird:
        assert alloc(t) == ids[t]
    table = get_table()
    assert all(table[nid] == t for t, nid in ids.items())
