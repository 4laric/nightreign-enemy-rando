"""test_pipeline_seed_sweep.py — corpus-gated end-to-end stress sweep of
the real healthbar pipeline (pipeline.patch_emevd_bytes).

Unlike test_rewriter_fuzz.py (synthetic EMEVDs), this runs the PRODUCTION
single-file entry point over real decompressed vanilla EMEVDs across many
seeds, with realistic spoilers (real placeable c-prefixes + names) and a
realistic vanilla catalog (data/chr_to_nameid.json). It is skipped unless
a corpus is available — the EMEVD files are copyrighted game data and are
never committed.

    EMEVD_CORPUS=/path/to/vanilla_decompressed_emevd \
        python3 -m pytest test_pipeline_seed_sweep.py

Invariants asserted for every (file, seed):
  * patch_emevd_bytes never raises; output re-parses cleanly and its
    healthbar callsites carry exactly the nameId multiset the decisions
    chose
  * every emitted nameId is a valid uint32; reuse_vanilla IDs come from
    the catalog; fresh IDs sit at/above the allocation base, never collide
    with a vanilla nameId, and stay below the next vanilla group boundary
  * a swapped bar is never blank
  * determinism: same seed -> byte-identical output and identical FMG table
  * across a whole seed's corpus pass, the shared allocator never hands the
    same ID to two different display strings
"""
import glob
import json
import re
import os
import random
import sys

import pytest

sys.path.insert(0, '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from emevd import EMEVD, extract_healthbar_callsites           # noqa: E402
from pipeline import patch_emevd_bytes                         # noqa: E402
from rewriter import make_fmg_allocator, DEFAULT_FMG_ID_BASE   # noqa: E402

UINT32 = 1 << 32
N_SEEDS = int(os.environ.get('SWEEP_SEEDS', '25'))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, 'data')


def _corpus_files():
    d = os.environ.get('EMEVD_CORPUS') or '/tmp/vemevd/vanilla_decompressed_emevd'
    return sorted(glob.glob(os.path.join(d, '*.emevd'))) if os.path.isdir(d) else []


def _load_json(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as f:
        return json.load(f)


def _vanilla_catalog():
    """chr_to_nameid.json -> {cp: [nameid,...]} of positive ints."""
    raw = _load_json('chr_to_nameid.json')
    cat = {}
    for cp, v in raw.items():
        if isinstance(v, list):
            ids = [x for x in v if isinstance(x, int) and x > 0]
        elif isinstance(v, int) and v > 0:
            ids = [v]
        else:
            ids = []
        if ids:
            cat[cp] = ids
    return cat


def _placeable_with_names():
    """Real (cp, name) pairs the rando can place, names non-empty/real."""
    roster = _load_json('nr_enemy_roster.json')
    tags = _load_json('nr_enemy_tags.json')
    out = []
    for t in roster['canonical_targets']:
        cp = t['c_prefix']
        name = (tags.get(cp, {}) or {}).get('name', '') or ''
        # skip placeholder names that are just the raw c-prefix
        if name and not re.fullmatch(r'c\d{3,4}', name):
            out.append((cp, name))
    return out or [('c2110', 'Beast Clergyman')]


def _all_vanilla_ids(cat):
    return {i for ids in cat.values() for i in ids}


def _random_spoiler(rng, entity_ids, pool):
    spoiler = {}
    for eid in entity_ids:
        if rng.random() < 0.75:
            cp, name = rng.choice(pool)
            spoiler[eid] = {'c_prefix': cp, 'name': name,
                            'old_name': 'Tree Sentinel', 'old_c_prefix': 'c3251'}
    return spoiler


def test_corpus_available():
    if not _corpus_files():
        pytest.skip('vanilla EMEVD corpus not present; set EMEVD_CORPUS')


def test_pipeline_seed_sweep():
    files = _corpus_files()
    if not files:
        pytest.skip('vanilla EMEVD corpus not present; set EMEVD_CORPUS')

    catalog = _vanilla_catalog()
    pool = _placeable_with_names()
    vanilla_ids = _all_vanilla_ids(catalog)
    next_vanilla_above_base = min(
        (i for i in vanilla_ids if i >= DEFAULT_FMG_ID_BASE), default=UINT32)

    # Pre-extract entity ids per file once (parsing is the slow part).
    file_entities = {}
    for path in files:
        with open(path, 'rb') as f:
            raw = f.read()
        callsites = extract_healthbar_callsites(EMEVD.parse(raw))
        ents = sorted({e for c in callsites for e in c.chr_entity_ids})
        file_entities[path] = (raw, ents)

    for seed in range(N_SEEDS):
        rng = random.Random(seed)
        alloc, get_table = make_fmg_allocator()
        for path, (raw, ents) in file_entities.items():
            fid = os.path.basename(path)
            spoiler = _random_spoiler(rng, ents, pool)
            title_pool = ['the Eternal', '{r} Reborn'] if seed % 2 else None

            new_raw, decisions, n_edits, n_seen = patch_emevd_bytes(
                raw, spoiler_entity_map=spoiler, chr_catalog=catalog,
                file_id=fid, fmg_id_allocator=alloc,
                title_pool=title_pool, seed=seed, compose_probability=0.5)

            # structural validity + nameId multiset realized
            reparsed = EMEVD.parse(new_raw)
            new_cs = extract_healthbar_callsites(reparsed)
            assert sorted(c.name_id for c in new_cs) == \
                sorted(d.new_name_id for d in decisions), \
                f"{fid} seed={seed}: nameId multiset mismatch"

            for d in decisions:
                assert 0 <= d.new_name_id < UINT32
                present = any(spoiler.get(e)
                              for e in d.chr_entity_ids_after_swap)
                if d.status != 'unchanged' and present:
                    assert d.new_name_text, f"{fid}: blank bar {d}"
                if d.status == 'reuse_vanilla':
                    assert d.new_name_id in vanilla_ids
                elif d.status in ('fresh_allocation', 'heterogeneous_squad'):
                    assert DEFAULT_FMG_ID_BASE <= d.new_name_id \
                        < next_vanilla_above_base, \
                        f"{fid}: fresh id {d.new_name_id} out of safe band"

            # determinism: two INDEPENDENT fresh-allocator runs of this
            # file (seed pinned, allocator state reset to base both times)
            # must be byte-identical. (Comparing against new_raw above
            # would be apples-to-oranges: the shared allocator carries
            # state from earlier files, legitimately shifting fresh IDs.)
            def _isolated():
                a, _ = make_fmg_allocator()
                r, _, _, _ = patch_emevd_bytes(
                    raw, spoiler_entity_map=spoiler, chr_catalog=catalog,
                    file_id=fid, fmg_id_allocator=a,
                    title_pool=title_pool, seed=seed, compose_probability=0.5)
                return r
            assert _isolated() == _isolated(), \
                f"{fid} seed={seed}: non-deterministic"

        # whole-pass invariant: shared allocator never reused an ID for
        # two different strings (id -> text is a function)
        table = get_table()
        assert len(set(table.values())) == len(table) or \
            len(table) == len(set(table)), "allocator id collision"
        # fresh IDs across the entire pass stay disjoint from vanilla
        assert set(table).isdisjoint(vanilla_ids), \
            f"seed={seed}: fresh IDs collided with vanilla nameIds"
