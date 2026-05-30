#!/usr/bin/env python3
"""MSB-free simulation of the placement engine's shuffle decisions.

Reproduces what shuffle_msb_v3 + the reservation pre-pass DECIDE — the
swap_plan, the per-target placement counts, reservation honouring, and
the v0.27.4-6 size gates — entirely from data/nr_slot_inventory.json,
with no MSBs and no Oodle. The decision functions called here
(pick_target, _reject_target_for_slot, _compute_unique_reservations,
RunContext) are the engine's own, so the logic is the engine's logic.

What it does NOT do: write output .msb bytes (that genuinely needs the
binaries) and the diagnostic-only modes (oops_all / terrain_test /
pinned). Hub MSBs are skipped — in production they shuffle only
explicitly-pinned boss slots, normally none.

Usage:
    python3 dev/simulate_engine.py <seed> [<seed> ...]
    python3 dev/simulate_engine.py --validate <real_spoiler_dir> <seed>
"""
import sys, os, json, random, importlib.util
from collections import Counter

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    'o', os.path.join(_ROOT, 'oops_v3.py'))
o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(o)


def _load_inventory():
    path = os.path.join(_ROOT, 'data/nr_slot_inventory.json')
    return json.load(open(path))


def simulate(seed, inventory, roster, tags, pv, pc):
    """Run one MSB-free shuffle for `seed`. Returns a result dict."""
    rng = random.Random(seed)
    o._V3_RUN_SEED = seed  # v0.28: propagate seed to the per-slot hashed rolls
                           # (_field_slot_roll / _slot_decision_rng) so the
                           # sim's hashed decisions match the engine's.
    run_ctx = o.RunContext.fresh()

    # --- reservation pre-pass (inventory-fed; no MSBs) ---
    o._reset_unique_run_state()
    o._compute_unique_reservations(None, tags, pv, rng,
                                   run_ctx=run_ctx, inventory=inventory)

    # --- per-MSB shuffle loop ---
    by_msb = {}
    for rec in inventory:
        by_msb.setdefault(rec['map'], []).append(rec)

    swap_plan = []          # (msb, pi, target_cp)
    target_count = {}       # run-wide accumulator, as in the real engine
    n_slots = n_skipped = n_no_target = 0
    no_target = []          # diagnostic: slots that found no target

    for msb_name in sorted(by_msb):
        if msb_name in o.V3_HUB_MAPS:
            continue                         # hubs: pinned-only in prod
        msb_base = msb_name[:-4] if msb_name.endswith('.msb') else msb_name

        # arm the v0.27.5 proximity/density gates with this MSB's caps
        if msb_name in o.V3_TUNNEL_MAPS:
            run_ctx.begin_msb(o.V3_TUNNEL_DENSITY_CAP_XL_PLUS,
                              o.V3_TUNNEL_DENSITY_CAP_L_PLUS)
        else:
            run_ctx.begin_msb(o.V3_DENSITY_CAP_XL_PLUS,
                              o.V3_DENSITY_CAP_L_PLUS)

        for rec in sorted(by_msb[msb_name], key=lambda r: r['part_index']):
            pi = rec['part_index']
            cur_cp = rec['c_prefix']
            npc = rec['npc_param_id']
            n_slots += 1

            # --- skip logic (mirrors shuffle_msb_v3's loop top) ---
            if npc == 0 or npc == 0xFFFFFFFF:
                n_skipped += 1
                continue
            if cur_cp in o.V3_EXCLUDE_PREFIXES:
                n_skipped += 1
                continue
            if cur_cp in o.V3_EXCLUDE_SOURCE_PREFIXES:
                n_skipped += 1
                continue
            vname = rec.get('source_variant_name') or ''
            is_emerge = any(m in vname for m in o.V3_EMERGE_VARIANT_MARKERS)
            eid = rec.get('entity_id', -1)
            is_nb_anchor = ((msb_base.startswith('m48_')
                             or msb_base.startswith('m49_'))
                            and eid > 0 and eid % 10000 == 800)
            if is_emerge and not is_nb_anchor:
                n_skipped += 1
                continue

            # --- tier (inventory carries catalog + NB-anchor already) ---
            recipient_is_boss = bool(rec['recipient_is_boss'])
            require_boss_reward = False
            _pm = o.V3_BOSSY_PROMOTE_SLOTS.get((msb_base, pi))
            if _pm is not None:
                recipient_is_boss = True
                require_boss_reward = (_pm == 'boss_reward')

            slot_pos = rec.get('position')
            slot_pos = tuple(slot_pos) if slot_pos else None
            slot_y = slot_pos[1] if slot_pos else None

            # --- the pick (engine's own picker + gates + reservations) ---
            target_cp, _tv = o.pick_target(
                cur_cp, tags, pv, pc, recipient_is_boss, rng,
                target_count=target_count, slot_y=slot_y,
                slot_msb_name=msb_name, slot_pi=pi,
                slot_variant_name=vname, slot_pos=slot_pos,
                slot_require_boss_reward=require_boss_reward,
                chaos_mode=False, gates=None, run_ctx=run_ctx)
            if target_cp is None:
                n_no_target += 1
                no_target.append({
                    'msb': msb_name, 'pi': pi, 'source_cp': cur_cp,
                    'recipient_is_boss': recipient_is_boss,
                    'size_class': (tags.get(cur_cp, {}) or {}).get('size_class'),
                })
                continue

            target_count[target_cp] = target_count.get(target_cp, 0) + 1
            swap_plan.append((msb_name, pi, target_cp))
            _sz = (tags.get(target_cp, {}) or {}).get('size_class')
            if _sz in o.V3_DENSITY_L_SIZE_CLASSES:
                run_ctx.register_big(_sz, slot_pos)

        run_ctx.end_msb()

    placed = Counter(t for _, _, t in swap_plan)
    return {
        'seed': seed,
        'n_placements': len(swap_plan),
        'n_slots_seen': n_slots,
        'n_skipped': n_skipped,
        'n_no_target': n_no_target,
        'no_target_slots': no_target,
        'n_reservations': len(run_ctx.unique_reservations),
        'placed_counts': dict(placed),
        'unique_placed_counts': dict(run_ctx.unique_placed_counts),
        'swap_plan': swap_plan,  # v0.28: (msb, pi, target_cp) per slot
    }


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    out_path = None
    if args and args[0] == '--out':
        out_path = args[1]
        args = args[2:]

    inventory = _load_inventory()
    roster = json.load(open(os.path.join(_ROOT, 'data/nr_enemy_roster.json')))
    _roster2, tags = o.load_data()
    pv, pc = o.build_per_prefix_data(roster)
    print(f"loaded inventory: {len(inventory)} slots, "
          f"{len(set(r['map'] for r in inventory))} MSBs\n")

    seeds = [int(a) for a in args]
    out_f = open(out_path, 'w') if out_path else None
    for seed in seeds:
        r = simulate(seed, inventory, roster, tags, pv, pc)
        overcap = []
        for cp, n in r['placed_counts'].items():
            cap = o.V3_UNIQUE_TARGET_CAPS.get(cp)
            if cap is not None and n > cap:
                overcap.append((cp, n, cap))
        print(f"seed {seed}: {r['n_placements']} placements "
              f"({r['n_skipped']} skipped, {r['n_no_target']} no-target), "
              f"{r['n_reservations']} reservations, "
              f"{len(r['placed_counts'])} distinct targets")
        print(f"  cap violations: {overcap if overcap else 'none'}")
        top = sorted(r['placed_counts'].items(),
                     key=lambda kv: -kv[1])[:5]
        print(f"  most-placed: {top}")
        if out_f:
            out_f.write(json.dumps(r) + '\n')
    if out_f:
        out_f.close()
        print(f"\nwrote results -> {out_path}")


if __name__ == '__main__':
    main()
