"""
night_role.py  —  map Nightreign night-boss arenas to the expedition + night they serve.

Source of truth: regulation `LotResultPlayAreaParam`. Each Nightlord has 50 rows
(one per map patternId); across all 50 the bossId1/bossId2 pair is identical, so
NB1/NB2 are FIXED per Nightlord and only the layout is randomized. `bossId` is the
arena map number (4929 -> m49_29_00_00.msb), which joins directly onto spoiler
entry['map'].

The table below is BAKED from a regulation dump so the spoiler generator needs no
regulation.bin at emit time. Regenerate with build_from_param(csv_path) whenever the
game patches (re-dump LotResultPlayAreaParam.csv and re-bake).

Roles: NB1 / NB2 = the scheduled Night-1 / Night-2 boss for that Nightlord.
       *-extra   = a rare per-pattern additional boss arena (not the main fight).
expedition is the in-game expedition title; nightlord is the param's label.
"""

EXPEDITION_BY_NIGHTLORD = {
    "Gladius": "Tricephalos", "Adel": "Gaping Jaw", "Gnoster": "Sentient Pest",
    "Maris": "Augur", "Libra": "Equilibrious Beast", "Fulghor": "Darkdrift Knight",
    "Caligo": "Fissure in the Fog", "Heolstor": "Night Aspect",
}

NIGHT_ROLE_BY_ARENA = {   'm47_70_00_00.msb': [   {   'expedition': 'Fissure in the Fog',
                                'night': 1,
                                'nightlord': 'Caligo',
                                'role': 'NB1',
                                'vanilla': 'Tibia Mariner'}],
    'm47_80_00_00.msb': [   {   'expedition': 'Gaping Jaw',
                                'night': 1,
                                'nightlord': 'Adel',
                                'role': 'NB1',
                                'vanilla': 'Gaping Dragon (DS1)'},
                            {   'expedition': '(Everdark/rotation)',
                                'night': 1,
                                'nightlord': None,
                                'role': 'NB1',
                                'vanilla': None}],
    'm47_90_00_00.msb': [   {   'expedition': 'Augur',
                                'night': 1,
                                'nightlord': 'Maris',
                                'role': 'NB1',
                                'vanilla': 'Centipede Demon (DS1)'}],
    'm48_00_00_00.msb': [   {   'expedition': 'Equilibrious Beast',
                                'night': 1,
                                'nightlord': 'Libra',
                                'role': 'NB1',
                                'vanilla': "Duke's Dear Freja (DS2)"}],
    'm48_10_00_00.msb': [   {   'expedition': 'Gaping Jaw',
                                'night': 1,
                                'nightlord': 'Adel',
                                'role': 'NB1-extra',
                                'vanilla': None},
                            {   'expedition': 'Sentient Pest',
                                'night': 1,
                                'nightlord': 'Gnoster',
                                'role': 'NB1',
                                'vanilla': 'Smelter Demon (DS2)'}],
    'm48_20_00_00.msb': [   {   'expedition': 'Fissure in the Fog',
                                'night': 2,
                                'nightlord': 'Caligo',
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm48_30_00_00.msb': [   {   'expedition': 'Darkdrift Knight',
                                'night': 2,
                                'nightlord': 'Fulghor',
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm48_40_00_00.msb': [   {   'expedition': 'Darkdrift Knight',
                                'night': 2,
                                'nightlord': 'Fulghor',
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm48_50_00_00.msb': [   {   'expedition': 'Sentient Pest',
                                'night': 2,
                                'nightlord': 'Gnoster',
                                'role': 'NB2',
                                'vanilla': 'Draconic Tree Sentinel + Royal Cav'},
                            {   'expedition': 'Augur',
                                'night': 2,
                                'nightlord': 'Maris',
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm48_60_00_00.msb': [   {   'expedition': 'Augur',
                                'night': 2,
                                'nightlord': 'Maris',
                                'role': 'NB2',
                                'vanilla': 'Tree Sentinel + Royal Cavalrymen'}],
    'm49_10_00_00.msb': [   {   'expedition': 'Tricephalos',
                                'night': 1,
                                'nightlord': 'Gladius',
                                'role': 'NB1-extra',
                                'vanilla': None},
                            {   'expedition': '(Everdark/rotation)',
                                'night': 1,
                                'nightlord': None,
                                'role': 'NB1-extra',
                                'vanilla': None}],
    'm49_17_00_00.msb': [   {   'expedition': 'Darkdrift Knight',
                                'night': 1,
                                'nightlord': 'Fulghor',
                                'role': 'NB1-extra',
                                'vanilla': None}],
    'm49_18_00_00.msb': [   {   'expedition': 'Tricephalos',
                                'night': 2,
                                'nightlord': 'Gladius',
                                'role': 'NB2',
                                'vanilla': 'Great Wyrm Theodorix (Magma Wyrm)'}],
    'm49_19_00_00.msb': [   {   'expedition': 'Gaping Jaw',
                                'night': 2,
                                'nightlord': 'Adel',
                                'role': 'NB2',
                                'vanilla': 'Ancient Dragon'},
                            {   'expedition': 'Night Aspect',
                                'night': 2,
                                'nightlord': 'Heolstor',
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm49_20_00_00.msb': [   {   'expedition': 'Equilibrious Beast',
                                'night': 2,
                                'nightlord': 'Libra',
                                'role': 'NB2',
                                'vanilla': 'Fallingstar Beast'},
                            {   'expedition': '(Everdark/rotation)',
                                'night': 2,
                                'nightlord': None,
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm49_21_00_00.msb': [   {   'expedition': 'Gaping Jaw',
                                'night': 2,
                                'nightlord': 'Adel',
                                'role': 'NB2-extra',
                                'vanilla': None},
                            {   'expedition': 'Darkdrift Knight',
                                'night': 2,
                                'nightlord': 'Fulghor',
                                'role': 'NB2',
                                'vanilla': 'Death Rite Bird'}],
    'm49_23_00_00.msb': [   {   'expedition': 'Gaping Jaw',
                                'night': 2,
                                'nightlord': 'Adel',
                                'role': 'NB2-extra',
                                'vanilla': None},
                            {   'expedition': '(Everdark/rotation)',
                                'night': 2,
                                'nightlord': None,
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm49_24_00_00.msb': [   {   'expedition': 'Tricephalos',
                                'night': 1,
                                'nightlord': 'Gladius',
                                'role': 'NB1',
                                'vanilla': 'Bell Bearing Hunter'},
                            {   'expedition': 'Darkdrift Knight',
                                'night': 1,
                                'nightlord': 'Fulghor',
                                'role': 'NB1',
                                'vanilla': 'Bell Bearing Hunter'},
                            {   'expedition': 'Darkdrift Knight',
                                'night': 1,
                                'nightlord': 'Fulghor',
                                'role': 'NB1-extra',
                                'vanilla': None},
                            {   'expedition': '(Everdark/rotation)',
                                'night': 1,
                                'nightlord': None,
                                'role': 'NB1-extra',
                                'vanilla': None}],
    'm49_25_00_00.msb': [   {   'expedition': 'Gaping Jaw',
                                'night': 2,
                                'nightlord': 'Adel',
                                'role': 'NB2-extra',
                                'vanilla': None},
                            {   'expedition': 'Fissure in the Fog',
                                'night': 2,
                                'nightlord': 'Caligo',
                                'role': 'NB2',
                                'vanilla': 'Crucible Knight + Hippopotamus'},
                            {   'expedition': '(Everdark/rotation)',
                                'night': 2,
                                'nightlord': None,
                                'role': 'NB2-extra',
                                'vanilla': None}],
    'm49_26_00_00.msb': [   {   'expedition': 'Night Aspect',
                                'night': 2,
                                'nightlord': 'Heolstor',
                                'role': 'NB2',
                                'vanilla': 'Outland Commander'}],
    'm49_27_00_00.msb': [   {   'expedition': 'Gaping Jaw',
                                'night': 1,
                                'nightlord': 'Adel',
                                'role': 'NB1-extra',
                                'vanilla': None}],
    'm49_29_00_00.msb': [   {   'expedition': '(Everdark/rotation)',
                                'night': 1,
                                'nightlord': None,
                                'role': 'NB1-extra',
                                'vanilla': None}],
    'm49_30_00_00.msb': [   {   'expedition': 'Night Aspect',
                                'night': 1,
                                'nightlord': 'Heolstor',
                                'role': 'NB1',
                                'vanilla': 'Royal Revenant'}],
    'm52_10_00_00.msb': [   {   'expedition': '(Everdark/rotation)',
                                'night': 2,
                                'nightlord': None,
                                'role': 'NB2',
                                'vanilla': None}],
    'm52_11_00_00.msb': [   {   'expedition': '(Everdark/rotation)',
                                'night': 2,
                                'nightlord': None,
                                'role': 'NB2',
                                'vanilla': None}],
    'm52_12_00_00.msb': [   {   'expedition': '(Everdark/rotation)',
                                'night': 2,
                                'nightlord': None,
                                'role': 'NB2',
                                'vanilla': None}],
    'm52_13_00_00.msb': [   {   'expedition': '(Everdark/rotation)',
                                'night': 2,
                                'nightlord': None,
                                'role': 'NB2',
                                'vanilla': None}]}

# Arenas that are a *scheduled* NB1/NB2 for a named expedition (excludes Everdark
# block and *-extra). These are the slots that MUST start via the wake-handshake;
# use them as a post-swap regression gate (all should come out is_boss=True).
STANDARD_NB_ARENAS = {
    arena for arena, roles in NIGHT_ROLE_BY_ARENA.items()
    for r in roles
    if r["role"] in ("NB1", "NB2") and r["expedition"] != "(Everdark/rotation)"
}


def _norm(map_name):
    """Accept 'm49_29', 'm49_29_00_00', '.../m49_29_00_00.msb' -> 'm49_29_00_00.msb'."""
    if not map_name:
        return None
    base = map_name.replace("\\", "/").rsplit("/", 1)[-1]
    if base.endswith(".msb"):
        base = base[:-4]
    parts = base.split("_")
    if len(parts) == 2:                 # 'm49_29' -> 'm49_29_00_00'
        parts += ["00", "00"]
    return "_".join(parts) + ".msb"


def roles_for(map_name):
    """List of role dicts for an arena, or [] if it is not a night-boss arena."""
    return NIGHT_ROLE_BY_ARENA.get(_norm(map_name), [])


def label_for(map_name, include_extra=False):
    """Compact human label, e.g. 'Tricephalos NB1'. '' if no night role."""
    roles = roles_for(map_name)
    if not include_extra:
        roles = [r for r in roles if not r["role"].endswith("-extra")] or roles
    return " + ".join(f"{r['expedition']} {r['role']}" for r in roles)


def stamp_entry(entry, key="night_role"):
    """Add entry[key] = list-of-roles when entry['map'] is a night-boss arena.
    No-op otherwise. Returns the roles added."""
    roles = roles_for(entry.get("map"))
    if roles:
        entry[key] = roles
    return roles


def build_from_param(csv_path):
    """Rebuild NIGHT_ROLE_BY_ARENA from a fresh LotResultPlayAreaParam.csv export."""
    import csv as _csv, re as _re
    def arena(b):
        b = int(b)
        return f"m{b//100:02d}_{b%100:02d}_00_00.msb" if b >= 0 else None
    table = {}
    def add(ar, role):
        if ar is None:
            return
        lst = table.setdefault(ar, [])
        if role not in lst:
            lst.append(role)
    seen = set()
    for r in _csv.DictReader(open(csv_path)):
        nm = r["Name"]; lord = nm.split(":")[0].strip() if ":" in nm else ""
        exped = EXPEDITION_BY_NIGHTLORD.get(lord, "(Everdark/rotation)" if lord == "" else lord)
        m = _re.search(r"NB1=(.*?)\s*NB2=(.*)", nm)
        nb1 = m.group(1).strip() if m else None
        nb2 = m.group(2).strip() if m else None
        key = (lord, arena(r["bossId1"]), arena(r["bossId2"]))
        first = key not in seen
        seen.add(key)
        if first:
            add(arena(r["bossId1"]), {"nightlord": lord or None, "expedition": exped, "night": 1, "role": "NB1", "vanilla": nb1})
            add(arena(r["bossId2"]), {"nightlord": lord or None, "expedition": exped, "night": 2, "role": "NB2", "vanilla": nb2})
        for ex, role in [(r["extraBossId1"], "NB1-extra"), (r["extraBossId2"], "NB2-extra")]:
            if ex not in ("-1", "", None):
                add(arena(ex), {"nightlord": lord or None, "expedition": exped,
                                "night": 1 if role.startswith("NB1") else 2, "role": role, "vanilla": None})
    return dict(sorted(table.items()))


if __name__ == "__main__":
    print(f"{len(NIGHT_ROLE_BY_ARENA)} night arenas; {len(STANDARD_NB_ARENAS)} scheduled NB1/NB2")
    for q in ("m49_29", "m49_29_00_00.msb", "m99_99_00_00.msb"):
        print(f"  {q:<20} -> {label_for(q)!r}")
