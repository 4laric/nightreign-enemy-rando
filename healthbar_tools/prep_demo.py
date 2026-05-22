#!/usr/bin/env python3
"""
prep_demo.py — Two related jobs in one tool:

  BUILD-CATALOG: derive a vanilla c_prefix → [nameId, ...] catalog from
    (a) the callsite manifest and (b) a single spoiler. Each spoiler entry
    has both `original.c_prefix` and `entity_id`, and each callsite has
    `chr_entity_id_arg_values` + `name_id_arg_value`. Joining these gives
    "vanilla c-prefix X was bound to nameId N at this callsite". The
    catalog ships as an input to apply_healthbar_names.py GENERATE so
    swapped chrs that match vanilla c-prefixes can reuse the existing
    FMG entry rather than allocate a fresh one.

      python prep_demo.py BUILD-CATALOG \
          --callsites callsites.json \
          --spoiler seeds/seed10000/_spoilers.json \
          --out chr_to_nameid.json

  RANK: score every spoiler in a seed dir on demo-fitness and print the
    top candidates with a per-criterion breakdown so you can pick which
    seed to record against.

      python prep_demo.py RANK \
          --seeds-root seeds/ \
          --callsites callsites.json \
          --top 10 \
          --tile-weighting vanilla

Demo-fitness scoring criteria, in order of weight (see _score_spoiler):

  1. NB arena distinctiveness: how many canonical Night Boss arenas got a
     visually distinct, boss-tier swap? More is better.
  2. NameId reuse safety: how cleanly do the swaps map onto unique
     vanilla nameIds? Lower nameId collision = fewer FMG additions =
     simpler demo. (Reused vanilla nameIds are cheap.)
  3. Heterogeneous squad tiebreaker: bonus for at least one shared-bar
     callsite where the chrs swapped to a heterogeneous group. This is
     the "demo moment" the squad-annotation feature exists for.
  4. Memorable field placements: bonus if specific recognizable field
     boss slots (cathedral, fingercreeper nest, etc.) got distinctive
     swaps. TILE-WEIGHTED: each placement's contribution is multiplied by
     P(the tile that hosts this MSB is rolled during a vanilla expedition),
     so a Cathedral swap on Crater tile counts ~0.022 not 1.0. Toggle via
     --tile-weighting {off|uniform|vanilla}; default is 'vanilla'.

The criteria are heuristic — don't treat the top score as authoritative.
The point is to surface a small candidate set to manually inspect.
"""

import argparse
import json
import os
import sys
from collections import defaultdict


# Canonical Night Boss arenas — boss tile MSB names. Source: dev/spoiler_predict_nightlords.py
# already shipped with the rando. Keeping the same list here keeps demo
# selection consistent with that diagnostic tool.
NB_ARENAS = {
    'm47_70_00_00.msb':  'Tibia Mariner',
    'm48_40_00_00.msb':  'Morgott',
    'm48_50_00_00.msb':  'Draconic Tree Sentinel',
    'm48_60_00_00.msb':  'Tree Sentinel',
    'm48_70_00_00.msb':  'Godskin Apostle (solo)',
    'm48_80_00_00.msb':  'Godskin Duo',
    'm48_90_00_00.msb':  'Large Wormface',
    'm49_10_00_00.msb':  'Grafted Monarch',
    'm49_17_00_00.msb':  'Valiant Gargoyle',
    'm49_18_00_00.msb':  'Great Wyrm Theodorix',
    'm49_19_00_00.msb':  'Ancient Dragon',
    'm49_20_00_00.msb':  'Fallingstar Beast',
    'm49_21_00_00.msb':  'Death Rite Bird',
    'm49_23_00_00.msb':  'Dragonkin Soldier',
    'm49_24_00_00.msb':  'Bell Bearing Hunter',
    'm49_25_00_00.msb':  'Crucible Knight + Hippopotamus',
    'm49_26_00_00.msb':  'Outland Commander',
    'm49_27_00_00.msb':  'Battlefield Commander',
    'm49_28_00_00.msb':  "Night's Cavalry x2",
    'm49_29_00_00.msb':  'Demi-Human Queen + Swordmaster',
    'm49_30_00_00.msb':  'Royal Revenant',
    'm49_90_00_00.msb':  'Ulcerated Tree Spirit',
}

# Memorable field-boss MSBs — encounters where a swap is camera-worthy.
# Excludes Nightlord-arena MSBs (those live in NB_ARENAS) and excludes MSBs
# loaded by the boss matchmaker rather than POI rolls — m47_70 is Tibia
# Mariner's arena, not a field encounter, so it doesn't belong here.
MEMORABLE_FIELD = {
    'm38_00_00_00.msb':  'Cathedral interior',
    'm38_10_00_00.msb':  'Cathedral 2',
    'm46_03_00_00.msb':  'Fingercreeper nest',
    'm46_80_00_00.msb':  'Godskin Apostle + Death Bird catacomb',
    'm49_43_00_00.msb':  '10× Crucible Knight arena',
}


# -----------------------------------------------------------------------------
# Tile-frequency weighting (used to discount memorable-field placements that
# only show up on rare Shifting Earths).
# -----------------------------------------------------------------------------
#
# The vanilla engine rolls one of 5 expedition tiles. Per regulation.bin
# (see vanilla_tile_distribution.json), each Nightlord has 40 patterns split
# as 20 Default + 5 each of 4 Shifting Earths. Two interpretations of the
# rolling probabilities:
#   * 'vanilla': from thefifthmatt rando README — Default ≈ 91.16%, each SE
#     ≈ 2.21%. This is the EMEVD-side weighted roll (event flags 7601-7605).
#   * 'uniform': all 320 patterns equiprobable → Default 50%, each SE 12.5%.
#     Matches the "Greatly increase one-off Shifting Earth" option being ON.
# Pick whichever matches how the demo is actually played.

TILE_PROB_VANILLA = {
    'Default':      0.9116,
    'Mountaintops': 0.0221,
    'Crater':       0.0221,
    'Rotted_Woods': 0.0221,
    'Noklateo':     0.0221,
}
TILE_PROB_UNIFORM = {
    'Default':      0.500,
    'Mountaintops': 0.125,
    'Crater':       0.125,
    'Rotted_Woods': 0.125,
    'Noklateo':     0.125,
}
TILE_PROB_OFF = {  # uniform 0.2 across tiles → tile-agnostic MSBs sum to 1.0
    # (matches pre-weighting behavior for any MSB classified as tile-agnostic);
    # tile-specific MSBs are still discounted by 80%. Use --tile-weighting=off
    # if you want to disable the realistic-distribution weighting but still
    # treat tile classification as informational.
    'Default':      0.2,
    'Mountaintops': 0.2,
    'Crater':       0.2,
    'Rotted_Woods': 0.2,
    'Noklateo':     0.2,
}
# Manual tile-specificity overrides. The MSB-prefix heuristic in
# _msb_tiles() classifies all m30-m49 dungeon/POI MSBs as tile-agnostic
# (loadable from any pattern), which means they get visibility 1.0 under
# any weighting mode. This is correct as a CEILING — a dungeon's MSB CAN
# load on any tile if a pattern places it. But in practice some POIs are
# concentrated in specific tiles' pattern sets. If you have game-knowledge
# that an MSB only appears under one or two tiles, list it here. Anything
# in this dict overrides the prefix-based default.
#
# To populate this empirically, cross-reference vanilla_slot_poi_frequencies.json
# against a slot-id → MSB mapping (derivable from MSB Part data in
# nr_all_slots.json + LotResultSmallBaseAndSpot col2 if you build the join).
MSB_TILE_OVERRIDES = {
    # 'm38_00_00_00.msb': {'Default'},        # Cathedral interior — example, verify
    # 'm46_03_00_00.msb': {'Rotted_Woods'},   # Fingercreeper nest — example, verify
}


def _msb_tiles(msb_name):
    """
    Return the set of tiles on which this MSB can plausibly load in vanilla.

    Override first (MSB_TILE_OVERRIDES), then fall back to the prefix heuristic:
      m10*, m20*, m21*, m60* → Limveld base (Default tile only)
      m11* → Mountaintops only
      m12* → Crater only
      m13* → Rotted_Woods only
      m15* → Noklateo only
      m14*, m18*, m19* → non-expedition (lobby/tutorial); treat as no-tile
      everything else (m30-m49 dungeon/POI MSBs) → tile-agnostic, loadable
        on demand from any pattern, so all 5 tiles
    """
    if msb_name in MSB_TILE_OVERRIDES:
        return set(MSB_TILE_OVERRIDES[msb_name])
    prefix = msb_name[:3]  # 'm10', 'm38', etc.
    if prefix in ('m10', 'm20', 'm21', 'm60'):
        return {'Default'}
    if prefix == 'm11':
        return {'Mountaintops'}
    if prefix == 'm12':
        return {'Crater'}
    if prefix == 'm13':
        return {'Rotted_Woods'}
    if prefix == 'm15':
        return {'Noklateo'}
    if prefix in ('m14', 'm18', 'm19'):
        return set()  # lobby/menu/tutorial — not seen during expeditions
    # m30-m49 — POI dungeons, can spawn under any tile's pattern.
    return {'Default', 'Mountaintops', 'Crater', 'Rotted_Woods', 'Noklateo'}


# Empirical per-MSB per-tile presence rate, loaded lazily from an external JSON
# built by deriving from regulation.bin's LotResultSmallBaseAndSpot. When this
# table covers an MSB, _msb_visibility uses it directly; otherwise falls back
# to the prefix heuristic in _msb_tiles. See msb_tile_probability.json for the
# methodology block. Set EMPIRICAL_TILE_PROB to a dict like:
#   {'m38_00_00_00.msb': {'Default': 0.86, 'Mountaintops': 0.85, ...}, ...}
# or call load_empirical_tile_prob(path) to populate from JSON.
EMPIRICAL_TILE_PROB = {}


def load_empirical_tile_prob(path):
    """Load and install empirical per-MSB per-tile presence rates from JSON.

    Expected schema: top-level dict with 'msb_presence' key, whose value is
    {msb_name: {'per_tile_presence_rate': {tile: float, ...}, ...}}. This is
    the format emitted by the per-MSB derivation pipeline that scans
    LotResultSmallBaseAndSpot. Returns the number of MSBs loaded.
    """
    global EMPIRICAL_TILE_PROB
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    presence = data.get('msb_presence', data)  # accept either wrapped or bare
    EMPIRICAL_TILE_PROB = {
        msb: entry['per_tile_presence_rate']
        for msb, entry in presence.items()
        if isinstance(entry, dict) and 'per_tile_presence_rate' in entry
    }
    return len(EMPIRICAL_TILE_PROB)


def _msb_visibility(msb_name, tile_prob):
    """
    P(player sees this MSB during a random vanilla expedition).

    Two paths:
      1. If EMPIRICAL_TILE_PROB has this MSB, use the per-tile presence rate
         derived from regulation: visibility = Σ_T tile_prob[T] × presence[T].
         This is the right value for any MSB referenced by
         LotResultSmallBaseAndSpot (POI dungeons loaded on demand under
         specific patterns). For those MSBs, P(loaded | tile T) is just the
         empirical presence rate.
      2. Otherwise fall back to _msb_tiles() classification: sum tile_prob
         over the tiles where the MSB is loadable at all. This is an upper
         bound — it counts the tile-fraction without accounting for which
         patterns actually trigger the load.

    Tile-base MSBs (m10/m11/m12/m13/m15) and Nightlord-keyed arenas
    (m48*/m49* loaded by the boss matchmaker rather than POI rolls) typically
    aren't in EMPIRICAL_TILE_PROB, so they use the heuristic path. That's
    correct: an m11 expedition tile IS loaded with probability P(Mountaintops),
    and a Nightlord arena IS loaded once per expedition regardless of tile.
    """
    rates = EMPIRICAL_TILE_PROB.get(msb_name)
    if rates is not None:
        return sum(tile_prob.get(t, 0.0) * rates.get(t, 0.0) for t in tile_prob)
    tiles = _msb_tiles(msb_name)
    if not tiles:
        return 0.0
    return sum(tile_prob.get(t, 0.0) for t in tiles)


# -----------------------------------------------------------------------------
# Catalog build
# -----------------------------------------------------------------------------

def _index_spoiler_eid_to_orig(spoiler):
    """entity_id (int) -> original c_prefix from spoiler."""
    out = {}
    for e in spoiler.get('placements', spoiler.get('entries', [])):
        eid = e.get('entity_id')
        if eid is None:
            continue
        orig_cp = e.get('original', {}).get('c_prefix')
        if orig_cp:
            out[int(eid)] = orig_cp
    return out


def cmd_build_catalog(args):
    with open(args.callsites, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    with open(args.spoiler, 'r', encoding='utf-8') as f:
        spoiler = json.load(f)
    eid_to_orig = _index_spoiler_eid_to_orig(spoiler)

    # cp -> set of (nameId, callsite_count) seen. We keep all observed
    # nameIds per cp; the resolver in apply_healthbar_names picks the
    # first one. If a cp resolves to >1 distinct nameId across vanilla
    # callsites that's worth noting — it usually means context-specific
    # variants (e.g. "Banished Knight" vs "Banished Knight (boss arena)").
    cp_to_nameids = defaultdict(lambda: defaultdict(int))
    matched = 0
    unmatched = 0
    for cs in manifest['callsites']:
        if not cs.get('is_active', True):
            continue
        # For each chrEntityId in this callsite, look up its vanilla c-prefix
        # and credit the nameId to that cp. Multi-chr groups (shared bars)
        # credit ALL chrEntityIds to the same nameId.
        nameid = cs.get('name_id_arg_value')
        if not isinstance(nameid, int) or nameid == 0:
            continue
        for cid in cs['chr_entity_id_arg_values']:
            if not isinstance(cid, int) or cid == 0:
                continue
            cp = eid_to_orig.get(cid)
            if cp is None:
                unmatched += 1
                continue
            cp_to_nameids[cp][nameid] += 1
            matched += 1

    # Sort nameIds per cp by frequency (most-used first), then by id for
    # determinism.
    out = {}
    for cp, nameid_counts in cp_to_nameids.items():
        ranked = sorted(nameid_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        out[cp] = [nid for nid, _n in ranked]

    multi_nameid = sum(1 for cp, lst in out.items() if len(lst) > 1)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    sys.stderr.write(f"BUILD-CATALOG complete.\n")
    sys.stderr.write(f"  callsite chrEntityIds matched to spoiler vanilla c-prefix: {matched}\n")
    sys.stderr.write(f"  unmatched (no spoiler entry):                              {unmatched}\n")
    sys.stderr.write(f"  c-prefixes in catalog:                                     {len(out)}\n")
    sys.stderr.write(f"  c-prefixes with multiple vanilla nameIds:                  {multi_nameid}\n")
    sys.stderr.write(f"Wrote {args.out}\n")


# -----------------------------------------------------------------------------
# Ranking
# -----------------------------------------------------------------------------

def _index_spoiler_by_map(spoiler):
    """map_name -> list of entries."""
    by_map = defaultdict(list)
    for e in spoiler.get('placements', spoiler.get('entries', [])):
        by_map[e.get('map', '?')].append(e)
    return by_map


def _index_spoiler_eid(spoiler):
    out = {}
    for e in spoiler.get('placements', spoiler.get('entries', [])):
        eid = e.get('entity_id')
        if eid is not None:
            out[int(eid)] = e
    return out


def _score_spoiler(spoiler_path, callsites, tile_prob=TILE_PROB_OFF):
    """Return (score, breakdown_dict).

    `tile_prob` is the {tile: probability} weighting applied to
    memorable-field placements. Default (TILE_PROB_OFF) treats every tile
    as always-visible, matching the pre-weighting behavior.
    """
    with open(spoiler_path, 'r', encoding='utf-8') as f:
        sp = json.load(f)
    by_map = _index_spoiler_by_map(sp)
    eid_index = _index_spoiler_eid(sp)

    breakdown = {}

    # --- Criterion 1: NB arena distinctiveness ---
    # Count NB arenas where at least one slot got swapped to a different
    # c-prefix AND the new chr is in the "boss-tier" tag class. Without the
    # full tags JSON here we use a proxy: c-prefix changed AND new name
    # doesn't equal original name.
    nb_distinct = 0
    nb_swapped_chrs = []
    for arena, label in NB_ARENAS.items():
        entries = by_map.get(arena, [])
        for e in entries:
            orig_cp = e.get('original', {}).get('c_prefix')
            new_cp = e.get('new', {}).get('c_prefix')
            new_name = e.get('new', {}).get('name', '')
            if orig_cp and new_cp and orig_cp != new_cp and new_name:
                nb_distinct += 1
                nb_swapped_chrs.append((arena, label, new_name))
                break  # one distinct-swap per arena is enough
    breakdown['nb_arena_distinctiveness'] = {
        'count': nb_distinct,
        'examples': nb_swapped_chrs[:5],
        'weight': 4.0,
    }

    # --- Criterion 2: NameId reuse safety ---
    # For each callsite, check whether the swap at that chrEntityId would
    # collide (same vanilla nameId, multiple distinct swapped chrs). Each
    # collision is a small penalty — fresh nameIds get allocated, no big
    # deal, but cleaner is simpler. We do NOT reward cleanliness positively
    # (a trivial all-the-same-chr seed would max it out without being a
    # good demo). Variety lives in Criterion 5 instead.
    nameid_to_swapped_chrs = defaultdict(set)
    distinct_chrs_at_callsites = set()
    for cs in callsites:
        if not cs.get('is_active', True):
            continue
        for cid in cs['chr_entity_id_arg_values']:
            if not isinstance(cid, int) or cid == 0:
                continue
            sp_entry = eid_index.get(cid)
            if sp_entry is None:
                continue
            new_name = sp_entry.get('new', {}).get('name')
            if new_name:
                nameid_to_swapped_chrs[cs['name_id_arg_value']].add(new_name)
                distinct_chrs_at_callsites.add(new_name)
    n_colliding = sum(1 for v in nameid_to_swapped_chrs.values() if len(v) > 1)
    n_clean = sum(1 for v in nameid_to_swapped_chrs.values() if len(v) == 1)
    collision_ratio = (n_colliding / max(1, n_colliding + n_clean))
    breakdown['nameid_reuse_safety'] = {
        'vanilla_nameids_touched': len(nameid_to_swapped_chrs),
        'collision_count': n_colliding,
        'clean_count': n_clean,
        'collision_ratio': round(collision_ratio, 3),
        'weight': '-0.5 per collision',
    }

    # --- Criterion 3: Heterogeneous squad tiebreaker ---
    # Count shared-bar callsite groups where chrEntityIds resolve to >1
    # distinct swapped chr name. Each one is a "look the bar tells the
    # truth" moment in the video.
    heterogeneous_squads = 0
    squad_examples = []
    for cs in callsites:
        if not cs.get('is_active', True) or not cs.get('is_shared_bar'):
            continue
        names = set()
        chrs = []
        for cid in cs['chr_entity_id_arg_values']:
            if not isinstance(cid, int) or cid == 0:
                continue
            sp_entry = eid_index.get(cid)
            if sp_entry is None:
                continue
            n = sp_entry.get('new', {}).get('name')
            if n:
                names.add(n)
                chrs.append(n)
        if len(names) > 1:
            heterogeneous_squads += 1
            if len(squad_examples) < 3:
                squad_examples.append({
                    'file': cs['file'],
                    'line': cs['line'],
                    'chrs': chrs,
                })
    breakdown['heterogeneous_squads'] = {
        'count': heterogeneous_squads,
        'examples': squad_examples,
        'weight': 1.5,
    }

    # --- Criterion 4: Memorable field placements ---
    # Each memorable MSB contributes its placement-found indicator (1 if a
    # distinct swap was found there, 0 otherwise) MULTIPLIED by the tile-
    # visibility probability. With tile_prob=TILE_PROB_OFF every contribution
    # is 1.0 (legacy behavior). With vanilla tile weights, a swap in a
    # Cathedral that only loads on Crater tile (~2.2%) contributes 0.022
    # instead of 1.0 — reflecting how rarely the viewer will see it.
    field_distinct = 0       # raw count, kept for the breakdown display
    field_weighted = 0.0     # tile-weighted sum used in the final score
    field_examples = []
    for arena, label in MEMORABLE_FIELD.items():
        entries = by_map.get(arena, [])
        for e in entries:
            orig_cp = e.get('original', {}).get('c_prefix')
            new_cp = e.get('new', {}).get('c_prefix')
            new_name = e.get('new', {}).get('name', '')
            if orig_cp and new_cp and orig_cp != new_cp and new_name:
                vis = _msb_visibility(arena, tile_prob)
                field_distinct += 1
                field_weighted += vis
                if len(field_examples) < 5:
                    field_examples.append((arena, label, new_name, round(vis, 4)))
                break
    breakdown['memorable_field'] = {
        'count': field_distinct,
        'weighted': round(field_weighted, 3),
        'examples': field_examples,  # (arena, label, name, tile_visibility)
        'weight': 1.0,
    }

    # --- Criterion 5: Overall variety at callsites ---
    # How many distinct chrs appear at active callsites? A seed with 20+
    # distinct chrs across boss-wake handlers is visually varied; a seed
    # with 5 is monotonous regardless of how cleanly the nameIds map.
    breakdown['callsite_variety'] = {
        'distinct_chrs': len(distinct_chrs_at_callsites),
        'weight': 1.0,
    }

    # Weighted total. Caps prevent any one criterion from dominating.
    # Collisions are a small negative; variety is a moderate positive;
    # NB arena distinctiveness and heterogeneous squads are the main
    # positive drivers. The memorable-field term uses tile-weighted sum
    # (field_weighted, not field_distinct) so rare-tile placements get
    # discounted by how often the viewer actually sees them; with
    # tile_prob=TILE_PROB_OFF this is identical to the old field_distinct.
    score = (
        4.0 * min(nb_distinct, 12)
        + 1.0 * min(len(distinct_chrs_at_callsites), 30)
        - 0.5 * n_colliding
        + 1.5 * min(heterogeneous_squads, 6)
        + 1.0 * min(field_weighted, 6.0)
    )
    return score, breakdown, sp.get('seed')


def cmd_rank(args):
    with open(args.callsites, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    callsites = manifest['callsites']

    # Load empirical per-MSB tile probability table if available. Search order:
    #   1. --msb-tile-prob FILE (explicit)
    #   2. msb_tile_probability.json next to this script
    #   3. <parent>/data/msb_tile_probability.json
    #      (i.e., project_root/data/ when the script lives in healthbar_tools/)
    n_empirical = 0
    if args.msb_tile_prob:
        n_empirical = load_empirical_tile_prob(args.msb_tile_prob)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (os.path.join(here, 'msb_tile_probability.json'),
                     os.path.join(here, '..', 'data', 'msb_tile_probability.json')):
            if os.path.exists(cand):
                n_empirical = load_empirical_tile_prob(cand)
                break

    # Resolve the tile-weighting mode into a {tile: probability} dict.
    tile_prob = {
        'off':     TILE_PROB_OFF,
        'uniform': TILE_PROB_UNIFORM,
        'vanilla': TILE_PROB_VANILLA,
    }[args.tile_weighting]

    candidates = []
    n_scanned = 0
    n_failed = 0
    for entry in sorted(os.listdir(args.seeds_root)):
        full = os.path.join(args.seeds_root, entry)
        if not os.path.isdir(full):
            continue
        spoiler_path = os.path.join(full, '_spoilers.json')
        if not os.path.exists(spoiler_path):
            continue
        try:
            score, breakdown, seed = _score_spoiler(spoiler_path, callsites, tile_prob=tile_prob)
        except Exception as e:
            sys.stderr.write(f"  failed to score {entry}: {e!r}\n")
            n_failed += 1
            continue
        candidates.append({
            'dir': entry,
            'seed': seed,
            'spoiler_path': spoiler_path,
            'score': round(score, 2),
            'breakdown': breakdown,
        })
        n_scanned += 1
    candidates.sort(key=lambda c: -c['score'])

    sys.stderr.write(f"Scanned {n_scanned} spoilers ({n_failed} failed)\n")
    sys.stderr.write(f"Tile weighting: {args.tile_weighting}\n")
    if n_empirical:
        sys.stderr.write(f"Empirical per-MSB tile presence loaded: {n_empirical} MSBs\n")
    else:
        sys.stderr.write(f"Empirical per-MSB tile presence: NOT LOADED (using prefix heuristic only)\n")
    sys.stderr.write(f"Top {args.top}:\n\n")
    for i, c in enumerate(candidates[:args.top]):
        sys.stderr.write(f"  #{i+1}  seed={c['seed']}  score={c['score']}\n")
        bd = c['breakdown']
        sys.stderr.write(f"      NB arena distinct:   {bd['nb_arena_distinctiveness']['count']}\n")
        sys.stderr.write(f"      distinct chrs:       {bd['callsite_variety']['distinct_chrs']}\n")
        sys.stderr.write(f"      nameId collisions:   {bd['nameid_reuse_safety']['collision_count']}\n")
        sys.stderr.write(f"      het. squads:         {bd['heterogeneous_squads']['count']}\n")
        sys.stderr.write(f"      field placements:    {bd['memorable_field']['count']} raw"
                         f" / {bd['memorable_field']['weighted']} tile-weighted\n")
        if bd['nb_arena_distinctiveness']['examples']:
            sys.stderr.write(f"      sample NB swaps:\n")
            for _arena, label, name in bd['nb_arena_distinctiveness']['examples'][:3]:
                sys.stderr.write(f"        {label}: {name}\n")
        if bd['memorable_field']['examples']:
            sys.stderr.write(f"      sample field swaps:\n")
            for _arena, label, name, vis in bd['memorable_field']['examples'][:3]:
                sys.stderr.write(f"        {label}: {name}  (visibility: {vis:.4f})\n")
        if bd['heterogeneous_squads']['examples']:
            sys.stderr.write(f"      sample squad:\n")
            ex = bd['heterogeneous_squads']['examples'][0]
            sys.stderr.write(f"        {ex['file']}:{ex['line']} = {' + '.join(ex['chrs'])}\n")
        sys.stderr.write(f"      spoiler: {c['spoiler_path']}\n\n")

    # Also emit JSON to stdout so it's pipeable / archivable.
    print(json.dumps({
        'scanned': n_scanned,
        'failed': n_failed,
        'top_n': args.top,
        'tile_weighting': args.tile_weighting,
        'candidates': candidates,
    }, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    bc = sub.add_parser('BUILD-CATALOG')
    bc.add_argument('--callsites', required=True)
    bc.add_argument('--spoiler', required=True)
    bc.add_argument('--out', default='chr_to_nameid.json')
    bc.set_defaults(func=cmd_build_catalog)

    r = sub.add_parser('RANK')
    r.add_argument('--seeds-root', required=True)
    r.add_argument('--callsites', required=True)
    r.add_argument('--top', type=int, default=10)
    r.add_argument('--tile-weighting', choices=['off', 'uniform', 'vanilla'],
                   default='vanilla',
                   help="How to weight memorable-field placements by expedition-tile "
                        "frequency. 'off' = legacy behavior (every placement counts 1.0). "
                        "'uniform' = each tile 1/5 (matches 'Greatly increase one-off SE' ON: "
                        "Default 50%%, each SE 12.5%%). 'vanilla' (default) = ~91.16%% Default "
                        "and ~2.21%% per SE, matching vanilla expedition rates from the "
                        "thefifthmatt randomizer README.")
    r.add_argument('--msb-tile-prob', default=None,
                   help="Path to msb_tile_probability.json with empirical per-MSB per-tile "
                        "presence rates derived from regulation.bin (LotResultSmallBaseAndSpot). "
                        "When loaded, _msb_visibility uses these rates directly instead of the "
                        "prefix heuristic. If unset, the script looks for "
                        "msb_tile_probability.json next to prep_demo.py. If neither exists, "
                        "falls back to the prefix heuristic in _msb_tiles().")
    r.set_defaults(func=cmd_rank)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
