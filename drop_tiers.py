"""drop_tiers.py — tier-gated rarity model for the item-drop randomizer.

Pure / regulation-free: everything derives from committed data files
(regulation_pools.json, drop_rarity_by_tier.json, NpcParam.csv,
nr_enemy_roster.json, nr_enemy_tags.json). mob_drop_fill consults this to
pick a NEW item per drop slot whose RARITY is biased by the owning enemy's
difficulty tier — quality correlates with difficulty, while the item is still
fully rerolled (more varied than vanilla).

Design + decisions: dev/DESIGN_tiered_drop_rarity.md.
"""
from __future__ import annotations

import csv
import json
import os

RARITIES = ("Common", "Uncommon", "Rare", "Legendary")
# severity order for "take the highest tier among a lot's owners"
_TIER_RANK = {"grunt": 1, "miniboss": 2, "field_boss": 3,
              "night_boss": 4, "nightlord": 5}
# tiers in nr_enemy_tags that aren't combat difficulty -> neutral curve
_NEUTRAL_TIERS = {"cinematic", "non_combat", "mount_component"}


def _data_path(data_dir, name):
    return os.path.join(data_dir, name)


class DropTierModel:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        pools = json.load(open(_data_path(data_dir, "regulation_pools.json"),
                               encoding="utf-8"))
        self.id_to_kind = {}
        self.id_to_rarity = {}
        self.by_kind_rarity = {}          # (kind, rarity) -> [ids]
        for kind in ("weapon", "talisman", "good"):
            for iid, _name, rar in pools[kind]:
                self.id_to_kind[iid] = kind
                self.id_to_rarity[iid] = rar
                self.by_kind_rarity.setdefault((kind, rar), []).append(iid)
        for k in self.by_kind_rarity:
            self.by_kind_rarity[k].sort()
        # rarities present per kind (for renormalization)
        self.kind_rarities = {}
        for (kind, rar) in self.by_kind_rarity:
            self.kind_rarities.setdefault(kind, set()).add(rar)

        # id -> set of kinds it belongs to (ids are NOT unique across kinds:
        # a talisman and a good can share an integer). Used to learn the
        # category->kind mapping from UNAMBIGUOUS ids only.
        self.id_kinds = {}
        for (kind, _r), ids in self.by_kind_rarity.items():
            for i in ids:
                self.id_kinds.setdefault(i, set()).add(kind)

        self.matrix = json.load(open(
            _data_path(data_dir, "drop_rarity_by_tier.json"),
            encoding="utf-8"))["tiers"]

        self.cat_to_kind = self._build_cat_to_kind(pools)
        self.lot_to_tier = self._build_lot_to_tier(data_dir)

    # ---- mapping construction ------------------------------------------
    def _build_cat_to_kind(self, pools):
        """Fallback kind for a lotItemCategory, from how rarity-tagged ids of
        each kind distribute across categories in this regulation. Used only
        when an original item id isn't itself rarity-tagged."""
        # (filled by the caller via observe(); start empty, resolve lazily)
        return {}

    def _build_lot_to_tier(self, data_dir):
        roster = json.load(open(_data_path(data_dir, "nr_enemy_roster.json"),
                                encoding="utf-8"))
        tags = json.load(open(_data_path(data_dir, "nr_enemy_tags.json"),
                              encoding="utf-8"))
        npc_to_cp = {}
        for v in roster.get("all_variants", []):
            npc = v.get("npc_param_id")
            cp = v.get("c_prefix")
            if npc and cp:
                npc_to_cp.setdefault(npc, cp)
        lot_to_tier = {}
        path = _data_path(data_dir, "NpcParam.csv")
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    npc = int(row["ID"])
                    lot = int(row["itemLotId_enemy"])
                except (KeyError, ValueError):
                    continue
                if not lot:
                    continue
                cp = npc_to_cp.get(npc)
                tier = (tags.get(cp, {}) or {}).get("tier") if cp else None
                if not tier or tier in _NEUTRAL_TIERS:
                    continue
                # take the highest-ranked tier among a shared lot's owners
                cur = lot_to_tier.get(lot)
                if cur is None or _TIER_RANK.get(tier, 0) > _TIER_RANK.get(cur, 0):
                    lot_to_tier[lot] = tier
        return lot_to_tier

    def observe_categories(self, cat_id_pairs):
        """Learn the dominant kind per lotItemCategory from (cat, item_id)
        pairs seen in the lots being randomized. Call once before picking."""
        import collections
        counts = collections.defaultdict(collections.Counter)
        for cat, iid in cat_id_pairs:
            kinds = self.id_kinds.get(iid)
            if kinds and len(kinds) == 1:        # unambiguous ids only
                counts[cat][next(iter(kinds))] += 1
        for cat, c in counts.items():
            self.cat_to_kind[cat] = c.most_common(1)[0][0]

    # ---- queries -------------------------------------------------------
    def tier_for_lot(self, lot_id):
        return self.lot_to_tier.get(lot_id, "unknown")

    def kind_for(self, item_id, lot_category):
        # The lotItemCategory is authoritative for which item PARAM (hence
        # kind) a slot draws from. Item ids are only unique within a kind
        # (a talisman and a good can share an integer id), so we must NOT
        # infer kind from the raw id. Categories with no confident kind
        # (e.g. armor, or unseen) return None -> caller does a legacy reroll.
        return self.cat_to_kind.get(lot_category)

    def _rarity_weights(self, tier, kind):
        """Tier weights restricted to the rarities `kind` actually has,
        renormalized to sum to 1. Returns [(rarity, weight)] or None."""
        base = self.matrix.get(tier) or self.matrix["unknown"]
        present = self.kind_rarities.get(kind, set())
        pairs = [(r, base.get(r, 0.0)) for r in RARITIES if r in present]
        total = sum(w for _, w in pairs)
        if total <= 0:
            # tier gives zero weight to every rarity this kind has -> uniform
            n = len(pairs) or 1
            return [(r, 1.0 / n) for r, _ in pairs] or None
        return [(r, w / total) for r, w in pairs]

    def pick_item(self, rng, kind, tier):
        """Pick a new item id of `kind`, rarity drawn per `tier`. Returns an
        id, or None if `kind` has no pooled items at all."""
        weights = self._rarity_weights(tier, kind)
        if not weights:
            return None
        rar = _weighted_choice(rng, weights)
        bucket = self.by_kind_rarity.get((kind, rar))
        if not bucket:                      # nearest-rarity fallback
            bucket = self._nearest_bucket(kind, rar)
        return rng.choice(bucket) if bucket else None

    def _nearest_bucket(self, kind, rarity):
        i = RARITIES.index(rarity)
        order = sorted(range(len(RARITIES)), key=lambda j: abs(j - i))
        for j in order:
            b = self.by_kind_rarity.get((kind, RARITIES[j]))
            if b:
                return b
        return None

    # ---- ItemTableParam (loot-table) reroll -----------------------------
    # Entry layout within an ItemTableParam row: 10 entries x 36 bytes;
    # each entry has itemCategory @ +4 (u8) and itemId @ +8 (s32). Derived +
    # validated against the Smithbox dump (table 4000000 -> cat4/id6110, ...).
    _TBL_ENTRY_STRIDE = 36
    _TBL_ID_OFF = 8

    def _kind_of_item(self, iid, W, A, G, P):
        in_a, in_w, in_g = iid in A, iid in W, iid in G
        if in_a and not in_w and not in_g: return "talisman"
        if in_w and not in_a and not in_g: return "weapon"
        if in_g and not in_a and not in_w: return "good"
        if iid in P: return "protector"
        if in_a: return "talisman"          # ambiguous -> prefer accessory
        if in_g: return "good"
        if in_w: return "weapon"
        return None

    def load_tables(self, reg):
        """Classify the regulation's ItemTableParam rows by resolved kind +
        rarity and build table pools for the within-kind table reroll. Cached;
        safe no-op if ItemTableParam is absent. Only weapon/talisman/good
        tables are rerollable; protector/unknown/nested-dead tables are left
        for the caller to preserve."""
        if getattr(self, "_tables_loaded", False):
            return
        self._tables_loaded = True
        self.table_kind = {}
        self.table_by_kind = {}
        self.table_by_kind_rarity = {}
        self.table_kind_rarities = {}
        import struct
        import collections as _c
        try:
            off, _sz, rows = reg._param("ItemTableParam")
            W = set(reg.param_rows("EquipParamWeapon"))
            A = set(reg.param_rows("EquipParamAccessory"))
            G = set(reg.param_rows("EquipParamGoods"))
        except Exception:
            return
        try:
            P = set(reg.param_rows("EquipParamProtector"))
        except Exception:
            P = set()
        bnd = reg.bnd
        soffs = sorted(rows.values())
        stride = (soffs[1] - soffs[0]) if len(soffs) > 1 else 360
        table_ids = set(rows)
        kid_rar = {(k, i): r for (k, r), ids in self.by_kind_rarity.items()
                   for i in ids}

        def entries(tid):
            o = off + rows[tid]
            out = []
            for e in range(0, stride, self._TBL_ENTRY_STRIDE):
                if e + 12 > stride:
                    break
                iid = struct.unpack_from("<i", bnd, o + e + self._TBL_ID_OFF)[0]
                if iid:
                    out.append(iid)
            return out

        seen = {}

        def classify(tid, depth=0):
            if tid in seen:
                return seen[tid]
            if depth > 4:
                return None
            seen[tid] = None  # cycle guard
            ks = _c.Counter()
            for iid in entries(tid):
                k = (classify(iid, depth + 1) if iid in table_ids
                     else self._kind_of_item(iid, W, A, G, P))
                if k:
                    ks[k] += 1
            res = ks.most_common(1)[0][0] if ks else None
            seen[tid] = res
            return res

        def rarity_of(tid):
            rs = _c.Counter()
            for iid in entries(tid):
                if iid in table_ids:
                    continue
                for kk in ("talisman", "weapon", "good"):
                    if (kk, iid) in kid_rar:
                        rs[kid_rar[(kk, iid)]] += 1
            return rs.most_common(1)[0][0] if rs else None

        for tid in table_ids:
            k = classify(tid)
            self.table_kind[tid] = k
            if k in ("weapon", "talisman", "good"):
                self.table_by_kind.setdefault(k, []).append(tid)
                rar = rarity_of(tid)
                if rar:
                    self.table_by_kind_rarity.setdefault((k, rar), []).append(tid)
                    self.table_kind_rarities.setdefault(k, set()).add(rar)
        for k in self.table_by_kind:
            self.table_by_kind[k].sort()
        for key in self.table_by_kind_rarity:
            self.table_by_kind_rarity[key].sort()

    def table_kind_of(self, table_id):
        return getattr(self, "table_kind", {}).get(table_id)

    def pick_table(self, rng, kind, tier):
        """Reroll a table-ref to another table of the same `kind`, rarity-gated
        by `tier`. Falls back to any table of the kind (incl. unranked)."""
        present = getattr(self, "table_kind_rarities", {}).get(kind, set())
        base = self.matrix.get(tier) or self.matrix["unknown"]
        pairs = [(r, base.get(r, 0.0)) for r in RARITIES if r in present]
        tot = sum(w for _, w in pairs)
        if pairs and tot > 0:
            rar = _weighted_choice(rng, [(r, w / tot) for r, w in pairs])
            bucket = self.table_by_kind_rarity.get((kind, rar))
            if bucket:
                return rng.choice(bucket)
        allk = getattr(self, "table_by_kind", {}).get(kind)
        return rng.choice(allk) if allk else None


def _weighted_choice(rng, pairs):
    r = rng.random()
    acc = 0.0
    for val, w in pairs:
        acc += w
        if r < acc:
            return val
    return pairs[-1][0]
