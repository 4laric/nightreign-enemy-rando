"""vanilla_night_bosses.py  --  v2 (emevd-derived)

Canonical night-boss arena registry + the closed-pool swap gate.

WHAT CHANGED FROM v1
--------------------
v1 hardcoded each arena's bosses as (XX0800, XX0810) -- a guess from
entity numbering. That was wrong two ways, and the emevd proves it:

  * It MISSED the third actor in m48_50 / m48_60. Those arenas register
    three combatants in their 90065911 handshake (XX0800/0810/0820),
    each paired with its own NpcParam. v1's gate saw the third as a
    field slot and would have swapped a boss to a trash mob.

  * It WRONGLY ADMITTED adds. m49_26 / m49_27 carry adds at the XX0810
    entity number (c3010, c3000). v1 treated XX0810 as a boss slot by
    convention, so those add c-prefixes leaked into the boss pool.

v2 derives each arena's actor set from the only authoritative source:
the entities the arena's 90065911 night-boss handshake registers,
intersected with entities actually carried by an MSB enemy part. No
entity-number convention is trusted. See derive_arena_registry().

WHAT THE EMEVD DOES *NOT* TELL US
---------------------------------
Whether a solo boss is internally phased (Nameless King's dragon->king)
is NOT an arena event -- it is intrinsic to the boss chr's behavior.
It cannot be auto-detected here. Internally-phased bosses that are
unsafe to randomize must be hand-listed in EXCLUDED_ARENAS.

ACTOR COUNT is reliable (solo / duo / trio). MULTI-PHASE scripting is
reliable (the dedicated 90065120-122 handler; only m49_25 uses it).
ADD COUNT is reliable (straight from the MSB) -- and it is the count of
independent randomization slots in the arena, i.e. how much variety the
encounter exposes per seed.
"""

import os
import re

import msbe_parts


# ---------------------------------------------------------------------------
# The registry. Derived by derive_arena_registry() against vanilla NR emevd
# + MSBs, then frozen here so the module works without those files on hand.
# Re-derive any time with:  python vanilla_night_bosses.py <emevd_dir> <msb_dir>
#
#   actors      : {entity_id: model}  -- registered combatants (90065911)
#   add_count   : int                 -- vanilla non-actor enemy parts
#   multiphase  : bool                -- uses the 90065120-122 phase handler
# ---------------------------------------------------------------------------
NB_ARENAS = {
    'm48_00_00_00': {'actors': {48000800: 'c7800'}, 'add_count': 27, 'multiphase': False},
    'm48_10_00_00': {'actors': {48100800: 'c7820'}, 'add_count': 3,  'multiphase': False},
    'm48_20_00_00': {'actors': {48200800: 'c7910', 48200801: 'c7900'}, 'add_count': 2, 'multiphase': False},
    'm48_30_00_00': {'actors': {48300800: 'c7920'}, 'add_count': 3,  'multiphase': False},
    'm48_40_00_00': {'actors': {48400800: 'c2130'}, 'add_count': 2,  'multiphase': False},
    'm48_50_00_00': {'actors': {48500800: 'c3250', 48500810: 'c4353', 48500820: 'c4353'}, 'add_count': 12, 'multiphase': False},
    'm48_60_00_00': {'actors': {48600800: 'c3251', 48600810: 'c4353', 48600820: 'c4353'}, 'add_count': 14, 'multiphase': False},
    'm48_70_00_00': {'actors': {48700800: 'c3560'}, 'add_count': 5,  'multiphase': False},
    'm48_80_00_00': {'actors': {48800800: 'c3570', 48800810: 'c3560'}, 'add_count': 5, 'multiphase': False},
    'm48_90_00_00': {'actors': {48900800: 'c4580'}, 'add_count': 23, 'multiphase': False},
    'm49_10_00_00': {'actors': {49100800: 'c4750'}, 'add_count': 5,  'multiphase': False},
    'm49_17_00_00': {'actors': {49170800: 'c4770'}, 'add_count': 6,  'multiphase': False},
    'm49_18_00_00': {'actors': {49180800: 'c4911'}, 'add_count': 5,  'multiphase': False},
    'm49_19_00_00': {'actors': {49190800: 'c4510'}, 'add_count': 7,  'multiphase': False},
    'm49_20_00_00': {'actors': {49200800: 'c4680'}, 'add_count': 5,  'multiphase': False},
    'm49_21_00_00': {'actors': {49210800: 'c4980'}, 'add_count': 5,  'multiphase': False},
    'm49_23_00_00': {'actors': {49230800: 'c4650'}, 'add_count': 6,  'multiphase': False},
    'm49_24_00_00': {'actors': {49240800: 'c3100'}, 'add_count': 8,  'multiphase': False},
    'm49_25_00_00': {'actors': {49250800: 'c2500', 49250810: 'c5011'}, 'add_count': 5, 'multiphase': True},
    'm49_26_00_00': {'actors': {49260800: 'c3050'}, 'add_count': 8,  'multiphase': False},
    'm49_27_00_00': {'actors': {49270800: 'c3050'}, 'add_count': 13, 'multiphase': False},
    'm49_28_00_00': {'actors': {49280800: 'c3150', 49280810: 'c3150'}, 'add_count': 4, 'multiphase': False},
    'm49_29_00_00': {'actors': {49290800: 'c4130', 49290810: 'c5810'}, 'add_count': 16, 'multiphase': False},
    'm49_30_00_00': {'actors': {49300800: 'c4021'}, 'add_count': 7,  'multiphase': False},
    'm49_90_00_00': {'actors': {49900800: 'c4640'}, 'add_count': 3,  'multiphase': False},
}

# ---------------------------------------------------------------------------
# Arenas whose boss slot must NOT be randomized, and whose boss chr must NOT
# be used as a swap target anywhere.
#
#   m48_00  Nameless King -- internally 2-phase (c7800 dragon -> c7810 king).
#           The transition is intrinsic boss behavior, not an arena event;
#           swapping the slot leaves the phase logic handing off to a body
#           that no longer exists. Best case no transition, worst case CTD.
#   m49_28  Night's Cavalry Duo -- mounted (rider+horse) multi-part actor;
#           does not survive randomization cleanly.
#
# CONFIRM AND EXTEND THIS. It is a domain-knowledge list, not a derived one.
# If other vanilla night bosses are internally phased or otherwise swap-
# hostile (other mounted bosses, anything with a scripted body-swap), add
# their arena stems here.
# ---------------------------------------------------------------------------
EXCLUDED_ARENAS = frozenset({
    'm48_00_00_00',   # Nameless King -- internal phase transition
    'm49_28_00_00',   # Night's Cavalry Duo -- mounted multi-part
})

NB_ARENA_STEMS = frozenset(NB_ARENAS)

# entity -> arena stem, for every registered actor
_ENTITY_TO_ARENA = {
    e: stem for stem, info in NB_ARENAS.items() for e in info['actors']
}

# Closed boss-swap pool: every registered actor c-prefix EXCEPT those in
# excluded arenas. This is both the target set for boss slots and the set
# subtracted from field slots.
VANILLA_NB_POOL = frozenset(
    cp
    for stem, info in NB_ARENAS.items() if stem not in EXCLUDED_ARENAS
    for cp in info['actors'].values()
)
# Back-compat alias for v1 callers.
VANILLA_NIGHT_BOSSES_STATIC = VANILLA_NB_POOL


def msb_stem(msb_filename):
    """'m49_24_00_00.msb' / '....msb.dcx' / bare stem -> 'm49_24_00_00'."""
    base = os.path.basename(msb_filename)
    for suffix in ('.msb.dcx', '.msb', '.emevd.js', '.emevd'):
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base


def is_night_boss_part(msb_stem_or_name, part):
    """True iff `part` (an msbe_parts enemy-part dict) is a registered boss
    actor of a night-boss arena. Identified by arena membership AND entity
    id -- never by model -- so a swapped part is still recognised after the
    swap. Returns True for excluded arenas too (Nameless's slot IS a boss
    slot); use classify_slot() / is_excluded_arena() to gate randomization.
    """
    info = NB_ARENAS.get(msb_stem(msb_stem_or_name))
    if info is None:
        return False
    return part.get('entity_id', 0) in info['actors']


def is_excluded_arena(msb_stem_or_name):
    """True iff this arena is hand-listed as do-not-randomize."""
    return msb_stem(msb_stem_or_name) in EXCLUDED_ARENAS


def arena_actor_ids(msb_stem_or_name):
    """The set of registered boss-actor entity ids for an arena ({} if none)."""
    info = NB_ARENAS.get(msb_stem(msb_stem_or_name))
    return set(info['actors']) if info else set()


def arena_add_count(msb_stem_or_name):
    """Vanilla add-part count for an arena -- the number of independent
    randomization slots it exposes. Higher = more variety per seed.
    -1 if the stem is not a night-boss arena.
    """
    info = NB_ARENAS.get(msb_stem(msb_stem_or_name))
    return info['add_count'] if info else -1


def classify_slot(msb_stem_or_name, part):
    """Classify an enemy part for the randomizer:

        'frozen' -- boss slot of an excluded arena; do NOT randomize.
        'boss'   -- boss slot; randomize only within VANILLA_NB_POOL.
        'field'  -- everything else; randomize only outside the pool.
    """
    if is_night_boss_part(msb_stem_or_name, part):
        return 'frozen' if is_excluded_arena(msb_stem_or_name) else 'boss'
    return 'field'


def gate_target_pool(candidates, msb_stem_or_name, recipient_part,
                     nb_pool=VANILLA_NB_POOL):
    """Restrict a candidate c-prefix pool for the closed-pool swap.

        boss slot   -> candidates & nb_pool
        field slot  -> candidates - nb_pool
        frozen slot -> empty set  (no legal target; caller leaves it alone)

    Returns a new set; does not mutate the input. Recommended caller loop:

        stem = msb_stem(filename)
        for part in msbe_parts.enemy_parts(data):
            kind = classify_slot(stem, part)
            if kind == 'frozen':
                continue                       # keep the vanilla boss
            pool = gate_target_pool(cands, stem, part, nb_pool)
            ...
    """
    kind = classify_slot(msb_stem_or_name, recipient_part)
    if kind == 'frozen':
        return set()
    cand = set(candidates)
    if kind == 'boss':
        return cand & set(nb_pool)
    return cand - set(nb_pool)


def build_vanilla_nb_pool(msb_dir=None):
    """Return (pool, roster).

    pool   : VANILLA_NB_POOL -- the closed boss-swap c-prefix set.
    roster : {c-prefix: [(stem, entity_id), ...]} over non-excluded arenas.

    If msb_dir is given, the roster's models are re-verified against the
    actual MSBs and a mismatch raises -- a guard against registry drift.
    """
    roster = {}
    for stem, info in NB_ARENAS.items():
        if stem in EXCLUDED_ARENAS:
            continue
        for entity, cp in info['actors'].items():
            roster.setdefault(cp, []).append((stem, entity))

    if msb_dir is not None:
        for stem, info in NB_ARENAS.items():
            path = os.path.join(msb_dir, stem + '.msb')
            if not os.path.exists(path):
                raise FileNotFoundError(f'arena MSB missing: {path}')
            parts = {p['entity_id']: p['model_name']
                     for p in msbe_parts.enemy_parts(open(path, 'rb').read())}
            for entity, cp in info['actors'].items():
                got = parts.get(entity)
                if got != cp:
                    raise ValueError(
                        f'{stem} actor {entity}: registry says {cp}, '
                        f'MSB says {got} -- re-derive the registry')
    return VANILLA_NB_POOL, roster


def derive_arena_registry(emevd_dir, msb_dir):
    """Regenerate the NB_ARENAS table from source. Provenance + reproducibility.

    For each arena: parse the 90065911 InitializeCommonEvent line, take the
    XX08xx entities it names, intersect with entities actually carried by an
    MSB enemy part (drops handshake args that are regions/flags, not bodies),
    and count the remaining enemy parts as adds. multiphase = the arena uses
    a 90065120-122 event.

    Returns a dict shaped like NB_ARENAS. Compare against the baked table to
    detect drift; print it to refresh the literal above.
    """
    out = {}
    for stem in sorted(NB_ARENAS):
        js = os.path.join(emevd_dir, stem + '.emevd.js')
        txt = open(js, encoding='utf-8', errors='ignore').read()
        prefix = stem[1:3] + stem[4:6]                      # 'm48_50_..' -> '4850'
        m911 = re.search(r'90065911[^;]*', txt)
        named = {int(x) for x in re.findall(prefix + r'08\d\d', m911.group())} if m911 else set()

        parts = msbe_parts.enemy_parts(open(os.path.join(msb_dir, stem + '.msb'), 'rb').read())
        by_entity = {p['entity_id']: p['model_name'] for p in parts}

        actors = {e: by_entity[e] for e in sorted(named) if e in by_entity}
        add_count = sum(1 for p in parts if p['entity_id'] not in actors)
        multiphase = re.search(r'9006512[0-9]', txt) is not None
        out[stem] = {'actors': actors, 'add_count': add_count, 'multiphase': multiphase}
    return out


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3:
        derived = derive_arena_registry(sys.argv[1], sys.argv[2])
        drift = [s for s in derived if derived[s] != NB_ARENAS.get(s)]
        for stem in sorted(derived):
            info = derived[stem]
            n = len(info['actors'])
            shape = ('trio' if n >= 3 else 'duo' if n == 2 else 'solo')
            if info['multiphase']:
                shape += '/multiphase'
            mark = '  <-- DRIFT' if stem in drift else ''
            print(f'  {stem}: {shape:16s} actors={info["actors"]} '
                  f'adds={info["add_count"]}{mark}')
        print(f'\n{"DRIFT: " + ", ".join(drift) if drift else "registry in sync."}')

    pool, roster = build_vanilla_nb_pool()
    print(f'\nclosed boss-swap pool: {len(pool)} c-prefixes '
          f'(excludes {len(EXCLUDED_ARENAS)} arenas)')
    print(f'  {sorted(pool)}')
    trio = [s for s, i in NB_ARENAS.items() if len(i['actors']) >= 3]
    horde = sorted((i['add_count'], s) for s, i in NB_ARENAS.items())[-5:]
    print(f'  trios: {trio}')
    print(f'  highest add-count arenas: {[s for _, s in reversed(horde)]}')