"""Tests for the roster-subtype map — data/nr_roster_subtypes.json plus the
_roster_subtypes() loader (v0.27.x groundwork).

The map records c-prefixes whose NpcParam variants split into 2+ distinct
gameplay identities (c5250 -> Horned / Divine Bird / Divine Beast Warrior).
It changes no engine behavior yet; these tests keep the data file honest as
it is expanded — every c-prefix, variant name and npc_param_id it names must
exist in the roster, and the subtypes within a c-prefix must not claim
overlapping variants.
"""
import json

import oops_v3 as o

_PV = None


def _pv():
    """Per-prefix variant map, built once."""
    global _PV
    if _PV is None:
        # Use the POST-LOAD roster (includes MMV / heritage imports), not the
        # bare nr_enemy_roster.json — c-prefixes from MMV (e.g. c6200 Gael)
        # only exist in the merged roster, and the test must check against
        # the same view the engine uses.
        # MMV ships disabled (_meta.enabled=false is the intentional
        # user-facing default), so load through the everything_enabled
        # pool snapshot to get the dev-canonical merged roster this data
        # file was authored against. State is restored on context exit.
        from conftest import (EVERYTHING_ENABLED_SNAPSHOT,
                              isolated_pool_snapshot)
        with isolated_pool_snapshot(EVERYTHING_ENABLED_SNAPSHOT):
            roster, _ = o.load_data()
            _PV, _ = o.build_per_prefix_data(roster)
    return _PV


def _resolve(entry, variants):
    """npc_param_id set a subtype entry resolves to, given the c-prefix's
    variant list."""
    if 'variant_name' in entry:
        return {v.get('npc_param_id') for v in variants
                if (v.get('variant_name') or '').strip() == entry['variant_name']}
    return set(entry['npc_param_ids'])


def test_file_loads_and_loader_caches():
    st = o._roster_subtypes()
    assert isinstance(st, dict)
    # the loader caches — a second call hands back the same object
    assert o._roster_subtypes() is st


def test_every_c_prefix_exists_in_roster():
    pv = _pv()
    for cp in o._roster_subtypes():
        assert cp in pv, f"{cp} in nr_roster_subtypes.json is not in the roster"


def test_entries_well_formed():
    for cp, block in o._roster_subtypes().items():
        entries = block.get('entries', [])
        assert entries, f"{cp}: no entries"
        seen = set()
        for e in entries:
            sub = e.get('subtype')
            assert sub and isinstance(sub, str), f"{cp}: entry missing 'subtype'"
            assert sub not in seen, f"{cp}: duplicate subtype id {sub!r}"
            seen.add(sub)
            assert e.get('display_name'), f"{cp}/{sub}: missing display_name"
            # exactly one matcher
            assert ('variant_name' in e) != ('npc_param_ids' in e), (
                f"{cp}/{sub}: need exactly one of variant_name / npc_param_ids")


def test_matchers_resolve_to_real_variants():
    pv = _pv()
    for cp, block in o._roster_subtypes().items():
        variants = pv.get(cp, [])
        names = {(v.get('variant_name') or '').strip() for v in variants}
        ids = {v.get('npc_param_id') for v in variants}
        for e in block['entries']:
            if 'variant_name' in e:
                assert e['variant_name'] in names, (
                    f"{cp}/{e['subtype']}: variant_name {e['variant_name']!r} "
                    f"matches no variant under {cp}")
            else:
                for npc in e['npc_param_ids']:
                    assert npc in ids, (
                        f"{cp}/{e['subtype']}: npc_param_id {npc} not under {cp}")


def test_subtypes_do_not_overlap():
    pv = _pv()
    for cp, block in o._roster_subtypes().items():
        variants = pv.get(cp, [])
        all_ids = set()
        for e in block['entries']:
            s = _resolve(e, variants)
            dup = all_ids & s
            assert not dup, f"{cp}: npc_param_id(s) {dup} claimed by two subtypes"
            all_ids |= s


def test_c5250_seed():
    """The verified worked example: c5250 splits into three identities."""
    pv = _pv()
    block = o._roster_subtypes().get('c5250')
    assert block, "c5250 seed missing from nr_roster_subtypes.json"
    variants = pv['c5250']
    by_sub = {e['subtype']: _resolve(e, variants) for e in block['entries']}
    assert by_sub['divine_bird_warrior'] == {52500110, 52500120}
    assert by_sub['divine_beast_warrior'] == {52501210, 52501220}
    assert len(by_sub['horned_warrior']) == 14
