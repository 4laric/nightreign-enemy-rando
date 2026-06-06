"""Tests for the v0.28.x catalog-coupled proximity-wake pass in
emevd_patch.patch_proximity_wake. Covers the nr_boss_slots.json loader and
the injection guards (catalog-only slots get a wake; fog-gated/explicit and
encounter-covered slots don't double or pre-fire; exclude set respected).

No game corpus needed — the loader is pointed at a temp JSON and the patch
runs on synthetic EMEVD-JS strings. The module-level caches are saved and
restored so these tests don't leak state into the rest of the suite.
"""
import json
import re

import pytest

import emevd_patch as ep

WAKE = ep._PROXIMITY_WAKE_EVENT_ID      # 99055500
RAD = ep._PROXIMITY_WAKE_RADIUS         # 15


@pytest.fixture
def clean_caches():
    """Save/restore the module caches + exclude set + feature flag."""
    saved = (ep._FRAGILE_SLOT_ENTITIES, ep._BOSS_CATALOG_WAKE_EIDS,
             ep._EVERGAOL_WAKE_ENTITIES,
             set(ep._PROXIMITY_WAKE_EXCLUDE_ENTITIES),
             ep._PROXIMITY_WAKE_FROM_CATALOG)
    # Isolate: start each test with an empty Evergaol catalog so the real
    # data/evergaol_wake_entities.json never leaks into the existing cases.
    # Tests that exercise the Evergaol pass set _EVERGAOL_WAKE_ENTITIES.
    ep._EVERGAOL_WAKE_ENTITIES = {}
    yield
    (ep._FRAGILE_SLOT_ENTITIES, ep._BOSS_CATALOG_WAKE_EIDS,
     ep._EVERGAOL_WAKE_ENTITIES,
     excl, ep._PROXIMITY_WAKE_FROM_CATALOG) = saved
    ep._PROXIMITY_WAKE_EXCLUDE_ENTITIES.clear()
    ep._PROXIMITY_WAKE_EXCLUDE_ENTITIES.update(excl)


def _ctor(*body_lines):
    """A minimal arena-file constructor event (the injection anchor)."""
    inner = "".join(f"    {l}\r\n" for l in body_lines)
    return "$Event(0, Default, function() {\r\n" + inner + "});\r\n"


def _count(needle, hay):
    return hay.count(needle)


# --------------------------------------------------------------------------
# loader
# --------------------------------------------------------------------------

def test_loader_strips_msb_skips_zero_and_nightboss(tmp_path, monkeypatch,
                                                    clean_caches):
    cat = {
        "_meta": {"x": 1},
        "m46_82_00_00.msb": [
            {"pi": 1, "eid": 46820800, "tier": "castle_interior"},
            {"pi": 2, "eid": 0, "tier": "castle_interior"},        # sentinel
            {"pi": 3, "eid": 46820800, "tier": "castle_interior"}, # dupe
        ],
        "m49_00_00_00.msb": [
            {"pi": 1, "eid": 49000800, "tier": "nightboss"},        # skipped
        ],
        "m38_00_00_00.msb": [
            {"pi": 51, "eid": 38000850, "tier": "cathedral"},
            {"pi": 9, "tier": "cathedral"},                         # no eid
        ],
    }
    p = tmp_path / "nr_boss_slots.json"
    p.write_text(json.dumps(cat))
    monkeypatch.setattr(ep, "_emevd_data_path", lambda fn: str(p))
    ep._BOSS_CATALOG_WAKE_EIDS = None        # force reload

    out = ep._load_boss_catalog_wake_eids()
    assert out["m46_82_00_00"] == [46820800]   # .msb stripped, 0 + dupe gone
    assert out["m38_00_00_00"] == [38000850]   # missing-eid row dropped
    assert "m49_00_00_00" not in out           # nightboss tier skipped


def test_loader_feature_flag_off_returns_empty(tmp_path, monkeypatch,
                                               clean_caches):
    monkeypatch.setattr(ep, "_PROXIMITY_WAKE_FROM_CATALOG", False)
    ep._BOSS_CATALOG_WAKE_EIDS = None
    assert ep._load_boss_catalog_wake_eids() == {}


# --------------------------------------------------------------------------
# injection — the promoted-slot fix
# --------------------------------------------------------------------------

def test_catalog_only_slot_gets_wake(clean_caches):
    # 46820800 is in the catalog, not in the fragile list, no encounter call,
    # no explicit EnableCharacterAI -> the promoted-slot gap. Must be woken.
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_82_00_00": [46820800]}
    content = _ctor("// nothing here")
    out, n = ep.patch_proximity_wake(content, "m46_82_00_00.emevd.dcx.js")
    assert f"{WAKE}, 46820800, {RAD}" in out
    assert n == 1


def test_explicit_enable_ai_is_not_pre_fired(clean_caches):
    # A slot that already enables its own AI (fog-gate boss) must be left
    # alone even though it's in the catalog.
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_82_00_00": [46820800]}
    content = _ctor("EnableCharacterAI(46820800);")
    out, n = ep.patch_proximity_wake(content, "m46_82_00_00.emevd.dcx.js")
    assert f"{WAKE}, 46820800" not in out
    assert n == 0


def test_encounter_covered_slot_not_doubled(clean_caches):
    # eid has a 90015000 encounter call (pass 1 wakes it) AND is in the
    # catalog -> exactly one wake, not two.
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_82_00_00": [46820800]}
    content = _ctor("$InitializeCommonEvent(0, 90015000, 111, 46820800, 0);")
    out, n = ep.patch_proximity_wake(content, "m46_82_00_00.emevd.dcx.js")
    assert _count(f"{WAKE}, 46820800", out) == 1


def test_exclude_set_blocks_catalog_wake(clean_caches):
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_82_00_00": [46820800]}
    ep._PROXIMITY_WAKE_EXCLUDE_ENTITIES.add(46820800)
    content = _ctor("// nothing")
    out, n = ep.patch_proximity_wake(content, "m46_82_00_00.emevd.dcx.js")
    assert f"{WAKE}, 46820800" not in out
    assert n == 0


def test_fragile_and_catalog_union_dedups(clean_caches):
    # Same eid in both sources -> injected once.
    ep._FRAGILE_SLOT_ENTITIES = {"m46_82_00_00": [46820800]}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_82_00_00": [46820800]}
    content = _ctor("// nothing")
    out, n = ep.patch_proximity_wake(content, "m46_82_00_00.emevd.dcx.js")
    assert _count(f"{WAKE}, 46820800", out) == 1
    assert n == 1


def test_catalog_adds_alongside_fragile(clean_caches):
    # A fragile eid and a distinct catalog-only eid both get wakes.
    ep._FRAGILE_SLOT_ENTITIES = {"m46_82_00_00": [46820111]}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_82_00_00": [46820800]}
    content = _ctor("// nothing")
    out, n = ep.patch_proximity_wake(content, "m46_82_00_00.emevd.dcx.js")
    assert f"{WAKE}, 46820111" in out
    assert f"{WAKE}, 46820800" in out
    assert n == 2


def test_common_func_still_appends_event_body(clean_caches):
    out, n = ep.patch_proximity_wake("// header\r\n",
                                     "common_func.emevd.dcx.js")
    assert f"$Event({WAKE}," in out
    assert n == 1


# --------------------------------------------------------------------------
# injection — the Evergaol catalog (90015026 family, no encounter-scan cover)
# --------------------------------------------------------------------------

def test_evergaol_only_slot_gets_wake(clean_caches):
    # An Evergaol boss in NEITHER the fragile list nor the boss catalog (the
    # uncovered case the new catalog exists to fix) must be woken.
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {}
    ep._EVERGAOL_WAKE_ENTITIES = {"m46_50_00_00": [46500830]}
    content = _ctor("// nothing here")
    out, n = ep.patch_proximity_wake(content, "m46_50_00_00.emevd.dcx.js")
    assert f"{WAKE}, 46500830, {RAD}" in out
    assert n == 1


def test_evergaol_dedups_against_other_catalogs(clean_caches):
    # Same eid in the boss catalog AND the Evergaol catalog -> injected once.
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_50_00_00": [46500830]}
    ep._EVERGAOL_WAKE_ENTITIES = {"m46_50_00_00": [46500830]}
    content = _ctor("// nothing")
    out, n = ep.patch_proximity_wake(content, "m46_50_00_00.emevd.dcx.js")
    assert _count(f"{WAKE}, 46500830", out) == 1
    assert n == 1


def test_evergaol_adds_alongside_other_catalogs(clean_caches):
    # Distinct fragile, catalog, and Evergaol eids each get a wake.
    ep._FRAGILE_SLOT_ENTITIES = {"m46_50_00_00": [46500801]}
    ep._BOSS_CATALOG_WAKE_EIDS = {"m46_50_00_00": [46500802]}
    ep._EVERGAOL_WAKE_ENTITIES = {"m46_50_00_00": [46500830]}
    content = _ctor("// nothing")
    out, n = ep.patch_proximity_wake(content, "m46_50_00_00.emevd.dcx.js")
    assert f"{WAKE}, 46500801" in out
    assert f"{WAKE}, 46500802" in out
    assert f"{WAKE}, 46500830" in out
    assert n == 3


def test_evergaol_encounter_covered_not_doubled(clean_caches):
    # An Evergaol eid that also has a 90015000 encounter call -> one wake only.
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {}
    ep._EVERGAOL_WAKE_ENTITIES = {"m46_50_00_00": [46500830]}
    content = _ctor("$InitializeCommonEvent(0, 90015000, 111, 46500830, 0);")
    out, n = ep.patch_proximity_wake(content, "m46_50_00_00.emevd.dcx.js")
    assert _count(f"{WAKE}, 46500830", out) == 1


def test_evergaol_exclude_set_blocks_wake(clean_caches):
    ep._FRAGILE_SLOT_ENTITIES = {}
    ep._BOSS_CATALOG_WAKE_EIDS = {}
    ep._EVERGAOL_WAKE_ENTITIES = {"m46_50_00_00": [46500830]}
    ep._PROXIMITY_WAKE_EXCLUDE_ENTITIES.add(46500830)
    content = _ctor("// nothing")
    out, n = ep.patch_proximity_wake(content, "m46_50_00_00.emevd.dcx.js")
    assert f"{WAKE}, 46500830" not in out
    assert n == 0


def test_shipped_evergaol_catalog_loads(clean_caches):
    # Smoke test against the committed data/evergaol_wake_entities.json: it
    # loads and carries the three Evergaol maps with positive boss-anchor eids.
    ep._EVERGAOL_WAKE_ENTITIES = None        # force a real load from disk
    cat = ep._load_evergaol_wake_entities()
    assert {"m46_50_00_00", "m46_60_00_00", "m46_70_00_00"} <= set(cat)
    assert 46500800 in cat["m46_50_00_00"]
    assert all(isinstance(e, int) and e > 0
               for eids in cat.values() for e in eids)
