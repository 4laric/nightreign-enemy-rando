"""Regression tests for v0.25.7 catalog-derived arena slot designation.

The boss-slot catalog now carries an `arena: bool` field per entry,
derived at module load via two rules:
  1. Vanilla chr's `expects_boss_arena` is True
  2. Vanilla chr's `size_class` is in {XXL, GIGA}

The pick_target_cp gate at line ~10935 reads this field as an OR-clause
augmenting the existing slot_variant_name marker check. These tests
verify the derivation and the gate wiring.
"""
import importlib.util
import json
import os

# Module-level import so tests can use it
spec = importlib.util.spec_from_file_location(
    'oops_v3',
    os.path.join(os.path.dirname(__file__), '..', 'oops_v3.py'))
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)


class TestArenaFieldDerivation:
    """v0.25.7: every catalog entry has an `arena: bool` field."""

    def test_every_entry_has_arena_field(self):
        assert len(o.V3_BOSS_SLOT_CATALOG) > 0, "Catalog must be loaded"
        missing = [(msb, pi) for (msb, pi), e in o.V3_BOSS_SLOT_CATALOG.items()
                    if 'arena' not in e]
        assert missing == [], f"Entries missing 'arena' field: {missing[:5]}"

    def test_arena_is_bool(self):
        non_bool = [(msb, pi) for (msb, pi), e in o.V3_BOSS_SLOT_CATALOG.items()
                     if not isinstance(e.get('arena'), bool)]
        assert non_bool == [], f"Entries with non-bool arena: {non_bool[:5]}"

    def test_meta_arena_counts_consistent(self):
        """meta.arena_slot_count should equal the count of True entries.
        v0.26.x: now includes terrain-derived arena slots in addition to
        the original two derivation rules."""
        meta_n = o.V3_BOSS_SLOT_CATALOG_META.get('arena_slot_count')
        actual_n = sum(1 for e in o.V3_BOSS_SLOT_CATALOG.values() if e.get('arena'))
        assert meta_n == actual_n, f"meta says {meta_n}, actual is {actual_n}"

    def test_expects_boss_arena_chrs_mark_arena(self):
        """Rule 1: vanilla chr's expects_boss_arena=True → slot is arena."""
        tags_path = os.path.join(os.path.dirname(__file__), '..', 'data',
                                  'nr_enemy_tags.json')
        with open(tags_path, encoding="utf-8") as f:
            tags = json.load(f)
        for (msb, pi), e in o.V3_BOSS_SLOT_CATALOG.items():
            cp = e.get('cp')
            if not cp: continue
            info = tags.get(cp, {})
            if info.get('expects_boss_arena') is True:
                assert e['arena'] is True, (
                    f"{msb} pi={pi} cp={cp} has expects_boss_arena=True "
                    f"but arena={e['arena']}")

    def test_xxl_giga_chrs_mark_arena(self):
        """Rule 2: vanilla chr's size_class in {XXL, GIGA} → slot is arena."""
        tags_path = os.path.join(os.path.dirname(__file__), '..', 'data',
                                  'nr_enemy_tags.json')
        with open(tags_path, encoding="utf-8") as f:
            tags = json.load(f)
        for (msb, pi), e in o.V3_BOSS_SLOT_CATALOG.items():
            cp = e.get('cp')
            if not cp: continue
            info = tags.get(cp, {})
            if info.get('size_class') in ('XXL', 'GIGA'):
                assert e['arena'] is True, (
                    f"{msb} pi={pi} cp={cp} has size_class={info.get('size_class')} "
                    f"but arena={e['arena']}")

    def test_total_arena_count_matches_rules_union(self):
        """arena_slot_count should equal the union of rule-1, rule-2, and
        rule-3 (v0.26.x terrain-derived) hits.

        Rule 3: slot is in data/nr_terrain_arena_slots.json (passed big-
        and-flat terrain criteria). Marked at catalog load time with
        _source='terrain_audit_v0_26_x' (or merged into an existing
        catalog entry to promote it to arena=True)."""
        tags_path = os.path.join(os.path.dirname(__file__), '..', 'data',
                                  'nr_enemy_tags.json')
        with open(tags_path, encoding="utf-8") as f:
            tags = json.load(f)
        terrain_path = os.path.join(os.path.dirname(__file__), '..', 'data',
                                     'nr_terrain_arena_slots.json')
        terrain_keys = set()
        if os.path.isfile(terrain_path):
            with open(terrain_path, encoding="utf-8") as f:
                td = json.load(f)
            terrain_keys = {(s['msb'], s['pi']) for s in td.get('slots', [])}

        expected_arena = 0
        for (msb, pi), e in o.V3_BOSS_SLOT_CATALOG.items():
            cp = e.get('cp')
            info = tags.get(cp, {}) if cp else {}
            rule_1 = info.get('expects_boss_arena') is True
            rule_2 = info.get('size_class') in ('XXL', 'GIGA')
            rule_3 = (msb, pi) in terrain_keys
            if rule_1 or rule_2 or rule_3:
                expected_arena += 1
        actual = sum(1 for e in o.V3_BOSS_SLOT_CATALOG.values() if e.get('arena'))
        assert actual == expected_arena, (
            f"Derivation drift: union of rules gives {expected_arena}, "
            f"catalog has {actual} arena=True entries")


class TestArenaGateWiring:
    """v0.25.7: pick_target_cp consults catalog arena field as a gate path."""

    def test_catalog_has_some_arena_slots(self):
        """Sanity: the derivation actually flags some slots, not zero.
        v0.26.x: bumped upper bound to accommodate terrain-derived
        additions (~147 new arena slots in v0.26.x baseline)."""
        n = sum(1 for e in o.V3_BOSS_SLOT_CATALOG.values() if e.get('arena'))
        assert n >= 50, f"Only {n} arena slots — derivation may be broken"
        assert n <= 400, f"{n} arena slots — derivation may be too broad"

    def test_gate_consumes_catalog_arena_field(self):
        """The pick_target_cp source must reference V3_BOSS_SLOT_CATALOG
        with .get('arena', ...). Smoke test that the wiring is in place."""
        src = open(os.path.join(os.path.dirname(__file__), '..',
                                 'oops_v3.py'), encoding="utf-8").read()
        # The new gate path should mention catalog + arena lookup
        assert "V3_BOSS_SLOT_CATALOG.get(" in src
        # And specifically reference 'arena' as a key
        assert ".get('arena'" in src or ".get(\"arena\"" in src


class TestTerrainArenaMerge:
    """v0.26.x: terrain-derived arena slots merge into V3_BOSS_SLOT_CATALOG
    via data/nr_terrain_arena_slots.json. Tests the merge contract."""

    def test_terrain_data_file_exists_and_loads(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'data',
                             'nr_terrain_arena_slots.json')
        assert os.path.isfile(path), (
            'data/nr_terrain_arena_slots.json should exist (output of '
            'dev/audit_terrain_arena_candidates.py)')
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert 'slots' in data, 'terrain file must have "slots" key'
        assert len(data['slots']) > 0, 'terrain file should have entries'

    def test_terrain_slots_are_all_arena_flagged(self):
        """Every entry in nr_terrain_arena_slots.json should appear in
        the catalog with arena=True, either as a new entry or by
        promoting an existing catalog entry."""
        terrain_path = os.path.join(os.path.dirname(__file__), '..', 'data',
                                     'nr_terrain_arena_slots.json')
        with open(terrain_path, encoding="utf-8") as f:
            terrain = json.load(f)
        for slot in terrain['slots']:
            key = (slot['msb'], slot['pi'])
            entry = o.V3_BOSS_SLOT_CATALOG.get(key)
            assert entry is not None, (
                f"Terrain slot {key} missing from catalog after merge")
            assert entry.get('arena') is True, (
                f"Terrain slot {key} present but arena={entry.get('arena')!r}")

    def test_terrain_added_count_matches_meta(self):
        """meta.arena_slot_via_terrain_new + ..._promoted should sum to
        the count of slots in nr_terrain_arena_slots.json."""
        terrain_path = os.path.join(os.path.dirname(__file__), '..', 'data',
                                     'nr_terrain_arena_slots.json')
        with open(terrain_path, encoding="utf-8") as f:
            terrain = json.load(f)
        n_in_file = len(terrain['slots'])
        n_new = o.V3_BOSS_SLOT_CATALOG_META.get('arena_slot_via_terrain_new', 0)
        n_promoted = o.V3_BOSS_SLOT_CATALOG_META.get(
            'arena_slot_via_terrain_promoted', 0)
        assert n_new + n_promoted == n_in_file, (
            f"Terrain merge accounting mismatch: file has {n_in_file} "
            f"slots, meta says {n_new} new + {n_promoted} promoted "
            f"= {n_new + n_promoted}")

    def test_new_terrain_entries_have_source_tag(self):
        """New entries (not promoted) should carry _source identifying
        them as terrain-audit-derived, for traceability."""
        terrain_entries = [
            e for e in o.V3_BOSS_SLOT_CATALOG.values()
            if e.get('_source') == 'terrain_audit_v0_26_x']
        # Should have at least some (assuming file has new-not-promoted entries)
        n_new = o.V3_BOSS_SLOT_CATALOG_META.get('arena_slot_via_terrain_new', 0)
        assert len(terrain_entries) == n_new, (
            f"Found {len(terrain_entries)} entries with terrain _source, "
            f"meta says {n_new} new")
