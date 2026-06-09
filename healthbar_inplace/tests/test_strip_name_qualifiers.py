"""test_strip_name_qualifiers.py — the healthbar editor strips slot-context
qualifiers ("(Field Boss)", "(Encampment)", "(Large)", ...) from a boss
name so the in-game bar reads just the enemy's name.

Covers the helper directly and end-to-end through decide_rewrites: the
fresh-allocation and heterogeneous-composite paths (which splice the
rando's spoiler name) must emit the cleaned name.
"""
import sys

sys.path.insert(0, '..')

from emevd import EMEVD, extract_healthbar_callsites          # noqa: E402
from synth import build_minimal_emevd, healthbar_instruction  # noqa: E402
from rewriter import (                                         # noqa: E402
    decide_rewrites, make_fmg_allocator, strip_name_qualifiers,
)


def test_strip_helper_cases():
    cases = {
        'Beast Clergyman (Field Boss)': 'Beast Clergyman',
        'Tree Sentinel (Night Boss)': 'Tree Sentinel',
        'Demi-Human Queen (Large) (SoTE)': 'Demi-Human Queen',
        'Maris - Fathom of Night (Everdark Sovereign Phase 2)':
            'Maris - Fathom of Night',
        'Knight (Castle- Dual Swords)': 'Knight',
        'Banished Knight': 'Banished Knight',            # nothing to strip
        "Night's Cavalry": "Night's Cavalry",            # apostrophe untouched
        'Margit ((nested))': 'Margit',                   # nested groups
    }
    for raw, expected in cases.items():
        assert strip_name_qualifiers(raw) == expected, raw


def test_strip_falls_back_when_only_a_qualifier():
    # Degenerate input that is ONLY a parenthetical → keep original rather
    # than producing a blank bar.
    assert strip_name_qualifiers('(Encampment)') == '(Encampment)'


def test_strip_handles_empty_and_none():
    assert strip_name_qualifiers('') == ''
    assert strip_name_qualifiers(None) is None


def _solo(eid):
    return build_minimal_emevd([{
        'event_id': 49270100, 'rest_behavior': 0,
        'instructions': [healthbar_instruction(
            0, 90015000, 10001, eid, 902500300, 40, 690047, 10002)],
    }])


def test_fresh_allocation_uses_stripped_name():
    raw = _solo(49270800)
    callsites = extract_healthbar_callsites(EMEVD.parse(raw))
    alloc, get_table = make_fmg_allocator()
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr={
            49270800: {'c_prefix': 'c2110', 'name': 'Beast Clergyman (Field Boss)'}},
        chr_to_vanilla_name_id={},               # force fresh allocation
        file_id='t.emevd', fmg_id_allocator=alloc)
    d = decisions[0]
    assert d.status == 'fresh_allocation'
    assert d.new_name_text == 'Beast Clergyman'
    assert d.new_name_id in get_table()
    assert get_table()[d.new_name_id] == 'Beast Clergyman'


def test_heterogeneous_composite_uses_stripped_labels():
    # 90015023 shared bar, group 0 covers two different swapped chrs.
    raw = build_minimal_emevd([{
        'event_id': 48500100, 'rest_behavior': 0,
        'instructions': [healthbar_instruction(
            0, 90015023, 10003, 40, 10004,
            48500800, 48500810, 903251600,
            48500820, 904351000, 48500830, 904351000)],
    }])
    callsites = extract_healthbar_callsites(EMEVD.parse(raw))
    alloc, _ = make_fmg_allocator()
    decisions = decide_rewrites(
        binary_callsites=callsites,
        spoiler_entity_to_chr={
            48500800: {'c_prefix': 'c3010', 'name': 'Banished Knight (Encampment)'},
            48500810: {'c_prefix': 'c4470', 'name': 'Abductor Virgin (Large)'},
        },
        chr_to_vanilla_name_id={}, file_id='t.emevd', fmg_id_allocator=alloc)
    g0 = [d for d in decisions
          if d.handler_id == 90015023 and d.name_group_index == 0][0]
    assert g0.status == 'heterogeneous_squad'
    assert '(Encampment)' not in g0.new_name_text
    assert '(Large)' not in g0.new_name_text
    assert 'Banished Knight' in g0.new_name_text
    assert 'Abductor Virgin' in g0.new_name_text
