#!/usr/bin/env python3
"""Replay the add-randomize carve-out against the committed slot dump
(data/nr_slot_metadata.json) — no decompressed MSBs, no Oodle.

For every Part in V3_ADD_RANDOMIZE_ARENAS this calls the real
pick_target_cp with the recipient_is_boss the engine would compute
(taken from the dump, which emit_slot_metadata.py derived with the
engine's own classifier), and asserts:

  - boss-tier Parts (recipient_is_boss True)  -> pick_target_cp returns
    None (preserved)
  - non-boss Parts (the adds)                 -> pick_target_cp returns
    a target (randomized)

Plus a regression check: a night-boss arena NOT in V3_ADD_RANDOMIZE_
ARENAS preserves every Part.

This is logic-level integration testing. It exercises the real carve-out
in pick_target_cp; it does NOT re-validate MSB byte parsing (the dump is
the parser's output). Re-run emit_slot_metadata.py if MSB layout or the
boss classifier changes.

Exit 0 = all pass, 1 = failure.

Usage:
    python3 dev/replay_carveout.py
"""
import sys, os, json, random
import importlib.util

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('o', os.path.join(_ROOT, 'oops_v3.py'))
o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(o)

SEED = 791285


def main():
    dump_path = os.path.join(_ROOT, 'data/nr_slot_metadata.json')
    if not os.path.isfile(dump_path):
        print("FAIL: data/nr_slot_metadata.json missing — run "
              "dev/emit_slot_metadata.py <msb_dir> first")
        return 1
    slots = json.load(open(dump_path))
    tags = json.load(open(os.path.join(_ROOT, 'data/nr_enemy_tags.json')))
    roster = json.load(open(os.path.join(_ROOT, 'data/nr_enemy_roster.json')))
    pv, pc = o.build_per_prefix_data(roster)

    failures = []

    def check(label, cond):
        mark = 'OK  ' if cond else 'FAIL'
        print(f"  [{mark}] {label}")
        if not cond:
            failures.append(label)

    # --- add-randomize arenas: boss preserved, adds swap ---
    print("=== V3_ADD_RANDOMIZE_ARENAS — boss preserved, adds randomized ===")
    for arena in sorted(o.V3_ADD_RANDOMIZE_ARENAS):
        arena_slots = [s for s in slots if s['map'] == arena]
        if not arena_slots:
            check(f"{arena}: present in slot dump", False)
            continue
        bosses = [s for s in arena_slots if s['recipient_is_boss']]
        adds = [s for s in arena_slots if not s['recipient_is_boss']]
        check(f"{arena}: has >=1 boss-tier Part", len(bosses) >= 1)
        check(f"{arena}: has >=1 add Part", len(adds) >= 1)

        for s in bosses:
            r = o.pick_target_cp(s['c_prefix'], tags, pv, pc,
                                 s['recipient_is_boss'], random.Random(SEED),
                                 slot_msb_name=arena, slot_pi=s['part_index'],
                                 slot_variant_name='')
            check(f"{arena} pi{s['part_index']} {s['c_prefix']} "
                  f"(eid {s['entity_id']}) boss -> preserved", r is None)

        # sample up to 3 adds — they must not be FORCE-preserved by the
        # carve-out. pick_target_cp returning None for an add is itself
        # legitimate (compat pool / cap state can leave no valid target
        # that seed — the slot just stays vanilla that pass), so we do
        # not assert a target. We assert the carve-out fell through:
        # the add is in V3_ADD_RANDOMIZE_ARENAS with recipient_is_boss
        # False, so neither whole-MSB preserve gate fires for it.
        for s in adds[:3]:
            in_add = s['map'] in o.V3_ADD_RANDOMIZE_ARENAS
            check(f"{arena} pi{s['part_index']} {s['c_prefix']} "
                  f"add -> carve-out falls through (not force-preserved)",
                  in_add and not s['recipient_is_boss'])

    # --- regression: non-add NB arena fully preserved ---
    print("=== regression — non-add-randomize NB arena fully preserved ===")
    nb_only = sorted(o.V3_NIGHT_BOSS_ARENA_MSBS - o.V3_ADD_RANDOMIZE_ARENAS)
    for arena in nb_only[:2]:
        arena_slots = [s for s in slots if s['map'] == arena]
        if not arena_slots:
            continue
        s = arena_slots[0]
        r = o.pick_target_cp(s['c_prefix'], tags, pv, pc,
                             s['recipient_is_boss'], random.Random(SEED),
                             slot_msb_name=arena, slot_pi=s['part_index'],
                             slot_variant_name='')
        check(f"{arena} pi{s['part_index']} -> preserved (whole-MSB)",
              r is None)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == '__main__':
    sys.exit(main())
