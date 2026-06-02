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


def _compute_msb_budgets(o, prefix_variants, inventory):
    """v0.28 per-MSB distinct-c-prefix budget. Mirrors the pre-scan in
    shuffle_msb_v3 (~line 14465): count the distinct enemy c-prefixes
    among SWAPPABLE slots per MSB. Forced-vanilla slots (excluded
    sources, no-variants, pinned) aren't charged — their chrbnd is
    loaded vanilla-cheap. Working assumption from oops_v3 v0.28 notes:
    rando-introduced distinct cps are the only thing the budget caps.

    Pre-v0.28 simulate_engine.py omitted this and called begin_msb with
    the default distinct_budget=0, which short-circuits in
    pick_target_cp (`_budget = ... or (1 << 30)`) — silently disabling
    recycling and running the picker in fresh-only mode forever."""
    from collections import defaultdict
    excl_pref = o.V3_EXCLUDE_PREFIXES
    excl_src = o.V3_EXCLUDE_SOURCE_PREFIXES
    pinned_va = getattr(o, 'V3_BINARY_SEARCH_VANILLA_PINS', set())
    by_msb = defaultdict(set)
    for r in inventory:
        cp = r.get('c_prefix')
        npc = r.get('npc_param_id', 0)
        if not (cp and cp.startswith('c') and len(cp) > 1 and cp[1].isdigit()):
            continue
        if npc == 0 or npc == 0xFFFFFFFF:
            continue
        msb = r['map']
        msb_base = msb[:-4] if msb.endswith('.msb') else msb
        if (msb_base, r['part_index']) in pinned_va:
            continue
        if cp in excl_pref or cp in excl_src:
            continue
        if cp not in prefix_variants:
            continue
        by_msb[msb].add(cp)
    return {msb: len(cps) for msb, cps in by_msb.items()}


def _load_poi_clusters():
    """v0.28.x Phase 2: load slot_poi_clusters.json and return
    (clusters_by_msb, pi_to_cid_by_msb). The first is the raw
    {msb: [[pi,...], ...]} mapping; the second is the per-MSB reverse
    lookup {pi: cluster_id} for the simulator's slot loop. Returns
    (None, None) when the file isn't present (Phase 0 hasn't been
    built or the install layout omits it)."""
    from collections import defaultdict
    path = os.path.join(_ROOT, 'data/slot_poi_clusters.json')
    if not os.path.isfile(path):
        return None, None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    clusters = data.get('clusters', {})
    pi_to_cid_by_msb = {}
    for msb, clist in clusters.items():
        lut = {}
        for cid, members in enumerate(clist):
            for pi in members:
                lut[pi] = cid
        pi_to_cid_by_msb[msb] = lut
    return clusters, pi_to_cid_by_msb


def _compute_cluster_budgets(o, prefix_variants, inventory,
                              pi_to_cid_by_msb):
    """v0.28.x Phase 2: per-(MSB, cluster_id) distinct-cp budgets,
    same logic as _compute_msb_budgets but keyed on the cluster bucket
    each slot lives in. Slots whose (msb, pi) isn't in the cluster
    file go to a cluster_id=-1 bucket; the simulator iterates that
    bucket without arming a POI scope, so the picker falls back to
    MSB-level state for those slots."""
    from collections import defaultdict
    excl_pref = o.V3_EXCLUDE_PREFIXES
    excl_src = o.V3_EXCLUDE_SOURCE_PREFIXES
    pinned_va = getattr(o, 'V3_BINARY_SEARCH_VANILLA_PINS', set())
    by_scope = defaultdict(set)  # (msb, cid) -> set of cps
    for r in inventory:
        cp = r.get('c_prefix')
        npc = r.get('npc_param_id', 0)
        if not (cp and cp.startswith('c') and len(cp) > 1 and cp[1].isdigit()):
            continue
        if npc == 0 or npc == 0xFFFFFFFF:
            continue
        msb = r['map']
        msb_base = msb[:-4] if msb.endswith('.msb') else msb
        pi = r['part_index']
        if (msb_base, pi) in pinned_va:
            continue
        if cp in excl_pref or cp in excl_src:
            continue
        if cp not in prefix_variants:
            continue
        cid = pi_to_cid_by_msb.get(msb, {}).get(pi, -1)
        by_scope[(msb, cid)].add(cp)
    return {k: len(v) for k, v in by_scope.items()}


def simulate(seed, inventory, roster, tags, pv, pc, msb_budgets=None,
             pi_to_cid_by_msb=None, cluster_budgets=None,
             chaos_mode=False):
    """Run one MSB-free shuffle for `seed`. Returns a result dict.

    v0.28.x Phase 2: when pi_to_cid_by_msb is provided (Phase 0 clusters
    file present + V3_POI_SCOPE_RECYCLE on in oops_v3), slots are
    visited cluster-by-cluster inside each MSB, with begin_poi/end_poi
    bracketing each cluster's run. The picker then reads per-cluster
    resident/budget via run_ctx.active_*_cps(). Slots whose (msb, pi)
    aren't in the cluster file go in a cluster_id=-1 trailing bucket
    that runs without arming a POI scope — picker falls back to MSB
    state for those.

    v0.28.x: `chaos_mode` (default False) threads through to
    o.pick_target. When True, the picker activates the v0.23.11
    asymmetric NB-tier gating (NB chrs leak down to field slots, field
    bosses can't leak up to NB arenas). Pass-through only — the engine
    owns the semantics. See engine.picker / engine.rejection."""
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

        # arm the v0.27.5 proximity/density gates with this MSB's caps,
        # AND the v0.28 distinct-c-prefix budget for recycling.
        _budget = (msb_budgets or {}).get(msb_name, 0)
        if msb_name in o.V3_TUNNEL_MAPS:
            run_ctx.begin_msb(o.V3_TUNNEL_DENSITY_CAP_XL_PLUS,
                              o.V3_TUNNEL_DENSITY_CAP_L_PLUS,
                              distinct_budget=_budget,
                              caps=o.V3_UNIQUE_TARGET_CAPS)
        else:
            run_ctx.begin_msb(o.V3_DENSITY_CAP_XL_PLUS,
                              o.V3_DENSITY_CAP_L_PLUS,
                              distinct_budget=_budget,
                              caps=o.V3_UNIQUE_TARGET_CAPS)

        # v0.28: canonical part-index order. v0.27.13 had a per-MSB
        # shuffle, but it was reverted in v0.28 because the per-slot
        # hashed pick (_slot_decision_rng) makes the picked cp
        # independent of visit order; canonical order then makes the
        # order-dependent target_count cap consumption deterministic
        # and identical between production and this sim. See the
        # v0.28 comment block in shuffle_msb_v3 (~line 14523 of
        # oops_v3.py) for the full rationale.
        #
        # v0.28.x Phase 2: when POI scope is on, slots are grouped by
        # cluster_id first (then pi within cluster). Still fully
        # canonical — cluster_id is 0-indexed by min(pi) per the
        # builder, so cluster order is deterministic. -1 (slots
        # outside the cluster file) bucketed last.
        _msb_recs = list(by_msb[msb_name])
        if pi_to_cid_by_msb is not None:
            _pi_to_cid = pi_to_cid_by_msb.get(msb_name, {})
            _msb_recs.sort(key=lambda r: (_pi_to_cid.get(r['part_index'], -1)
                                          == -1,
                                          _pi_to_cid.get(r['part_index'], -1),
                                          r['part_index']))
        else:
            _pi_to_cid = None
            _msb_recs.sort(key=lambda r: r['part_index'])
        _current_cluster = None
        for rec in _msb_recs:
            pi = rec['part_index']
            # v0.28.x Phase 2: cluster transition detection. Fires once
            # per cluster with the cluster-grouped sort above.
            if _pi_to_cid is not None:
                _this_cluster = _pi_to_cid.get(pi, -1)
                if _this_cluster != _current_cluster:
                    if (_current_cluster is not None
                            and _current_cluster != -1
                            and hasattr(run_ctx, 'end_poi')):
                        run_ctx.end_poi()
                    if (_this_cluster != -1
                            and hasattr(run_ctx, 'begin_poi')
                            and cluster_budgets is not None):
                        _cb = cluster_budgets.get((msb_name, _this_cluster),
                                                  _budget)
                        run_ctx.begin_poi(_this_cluster, _cb)
                    _current_cluster = _this_cluster
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
                chaos_mode=chaos_mode, gates=None, run_ctx=run_ctx)
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

        # v0.28.x Phase 2: close any active POI scope before end_msb.
        # end_msb clears POI state defensively but closing explicitly
        # keeps current_poi_id=None for any code between the inner loop
        # and end_msb that reads run_ctx state.
        if _pi_to_cid is not None and hasattr(run_ctx, 'end_poi'):
            run_ctx.end_poi()
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
    msb_budgets = _compute_msb_budgets(o, pv, inventory)
    # v0.28.x Phase 2: load POI clusters and per-cluster budgets if
    # the cluster file is present AND POI scope is on in oops_v3.
    # Both must be true for the sim to mirror the engine's path.
    if getattr(o, 'V3_POI_SCOPE_RECYCLE', False):
        _clusters_raw, pi_to_cid_by_msb = _load_poi_clusters()
    else:
        _clusters_raw, pi_to_cid_by_msb = None, None
    cluster_budgets = None
    if pi_to_cid_by_msb is not None:
        cluster_budgets = _compute_cluster_budgets(
            o, pv, inventory, pi_to_cid_by_msb)
        print(f"loaded inventory: {len(inventory)} slots, "
              f"{len(set(r['map'] for r in inventory))} MSBs; "
              f"v0.28 per-MSB budgets: min={min(msb_budgets.values())} "
              f"median={sorted(msb_budgets.values())[len(msb_budgets)//2]} "
              f"max={max(msb_budgets.values())}; "
              f"v0.28.x Phase 2 POI scope ON: "
              f"{len(cluster_budgets)} cluster budgets\n")
    else:
        print(f"loaded inventory: {len(inventory)} slots, "
              f"{len(set(r['map'] for r in inventory))} MSBs; "
              f"v0.28 per-MSB budgets: min={min(msb_budgets.values())} "
              f"median={sorted(msb_budgets.values())[len(msb_budgets)//2]} "
              f"max={max(msb_budgets.values())} (POI scope OFF)\n")

    seeds = [int(a) for a in args]
    out_f = open(out_path, 'w') if out_path else None
    for seed in seeds:
        r = simulate(seed, inventory, roster, tags, pv, pc,
                     msb_budgets=msb_budgets,
                     pi_to_cid_by_msb=pi_to_cid_by_msb,
                     cluster_budgets=cluster_budgets)
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
