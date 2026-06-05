"""Tests for engine.import_wizard: missing-import detection, plan
cross-reference, and the wizard step state machine. All pure — no Tk, no
display required (the Toplevel front-end is a thin renderer over these)."""
import json
import os
import re

import pytest

import engine.import_wizard as iw

_CHR_RE = re.compile(
    r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')


class FakeReg:
    def __init__(self, npc_ids, think_ids):
        self._npc = list(npc_ids)
        self._think = list(think_ids)

    def param_rows(self, name):
        if name == "NpcParam":
            return self._npc
        if name == "NpcThinkParam":
            return self._think
        raise KeyError(name)


def _make_env(tmp_path):
    """ns (synthetic _data_path + detect_asset_packs), a target chr dir with
    c9001 + c9100 present (c9002 absent), and a roster. heritage pack =
    {c9001, c9002}; mmv pack = {c9100}."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = tmp_path / "chr"
    target.mkdir()
    with open(data_dir / "heritage_pack.json", "w") as f:
        json.dump({"_meta": {"enabled": True},
                   "tags": {"c9001": {}, "c9002": {}}}, f)
    with open(data_dir / "mmv_imports.json", "w") as f:
        json.dump({"_meta": {"enabled": True},
                   "tags": {"c9100": {}}}, f)
    for cp in ("c9001", "c9100"):
        (target / f"{cp}.chrbnd.dcx").write_bytes(b"")

    def _data_path(fn):
        return os.path.join(str(data_dir), fn)

    def detect_asset_packs(t):
        present = set()
        if t and os.path.isdir(t):
            for fn in os.listdir(t):
                m = _CHR_RE.match(fn)
                if m:
                    present.add(m.group(1))
        out = {}
        for pid, fname in (("heritage_pack_v1", "heritage_pack.json"),
                           ("mmv_imports_v1", "mmv_imports.json")):
            with open(_data_path(fname)) as fh:
                cps = sorted((json.load(fh).get("tags") or {}).keys())
            out[pid] = {"enabled": True,
                        "missing": [c for c in cps if c not in present]}
        return out

    ns = {"_data_path": _data_path, "detect_asset_packs": detect_asset_packs}
    roster = {"all_variants": [
        {"c_prefix": "c1000", "npc_param_id": 10000000,
         "think_param_id": 10000000, "variant_name": "vanilla"},
        {"c_prefix": "c9001", "npc_param_id": 90010000,
         "think_param_id": 90010000, "variant_name": "good"},
        {"c_prefix": "c9100", "npc_param_id": 91000000,
         "think_param_id": 91000000, "variant_name": "paramless_think"},
        {"c_prefix": "c9002", "npc_param_id": 90020000,
         "think_param_id": 90020000, "variant_name": "absent_chr"},
    ]}
    return ns, roster, str(target)


# --------------------------------------------------------------------------
# missing_imports — split by source pack
# --------------------------------------------------------------------------

def test_missing_imports_splits_heritage_and_mmv(tmp_path):
    ns, roster, target = _make_env(tmp_path)
    reg = FakeReg(npc_ids=[10000000, 90010000, 91000000],
                  think_ids=[10000000, 90010000])
    m = iw.missing_imports(ns, reg, roster, target)
    assert m["heritage"] == ["c9002"]
    assert m["mmv"] == ["c9100"]
    assert set(m["all"]) == {"c9002", "c9100"}
    assert m["other"] == []


def test_missing_imports_empty_when_all_placeable(tmp_path):
    ns, roster, target = _make_env(tmp_path)
    open(os.path.join(target, "c9002.chrbnd.dcx"), "wb").close()
    reg = FakeReg(npc_ids=[10000000, 90010000, 90020000, 91000000],
                  think_ids=[10000000, 90010000, 90020000, 91000000])
    m = iw.missing_imports(ns, reg, roster, target)
    assert m["all"] == []


# --------------------------------------------------------------------------
# cross_reference_plan
# --------------------------------------------------------------------------

def test_cross_reference_splits_supplied_and_still_missing():
    missing = ["c9002", "c9100", "c9300"]
    plan = {
        "entries": [{"cp": "c9002", "origin": "er"},
                    {"cp": "c9100", "origin": "mmv"},
                    {"cp": "c1000", "origin": "er"}],
        "unavailable": [("c9300", "heritage")],
    }
    out = iw.cross_reference_plan(missing, plan)
    assert {e["cp"] for e in out["will_supply"]} == {"c9002", "c9100"}
    assert {e["cp"]: e["origin"] for e in out["will_supply"]} == {
        "c9002": "er", "c9100": "mmv"}
    assert out["still_missing"] == ["c9300"]
    assert out["unaccounted"] == []


def test_cross_reference_unaccounted_when_plan_silent():
    out = iw.cross_reference_plan(["c9002"], {"entries": [], "unavailable": []})
    assert out["will_supply"] == []
    assert out["still_missing"] == []
    assert out["unaccounted"] == ["c9002"]


# --------------------------------------------------------------------------
# ERImportWizardModel
# --------------------------------------------------------------------------

def _missing(**kw):
    base = {"all": [], "heritage": [], "mmv": [], "other": []}
    base.update(kw)
    return base


def test_model_detect_blocks_advance_when_nothing_missing():
    m = iw.ERImportWizardModel(_missing())
    assert m.step == "detect"
    assert m.can_advance() is False
    assert m.advance() is False
    assert m.step == "detect"


def test_model_detect_advances_when_detection_unavailable():
    m = iw.ERImportWizardModel(_missing(), detection_available=False)
    assert m.can_advance() is True
    assert m.advance() is True and m.step == "sources"


def test_model_sources_gate_requires_a_valid_dir(tmp_path):
    m = iw.ERImportWizardModel(_missing(all=["c9002"], heritage=["c9002"]))
    assert m.advance() is True and m.step == "sources"
    assert m.can_advance() is False
    m.set_sources(er_dir=str(tmp_path / "nope"))
    assert m.can_advance() is False
    m.set_sources(er_dir=str(tmp_path))
    assert m.can_advance() is True


def test_model_preview_required_before_import(tmp_path):
    m = iw.ERImportWizardModel(_missing(all=["c9002"], heritage=["c9002"]))
    m.advance()
    m.set_sources(er_dir=str(tmp_path))
    assert m.advance() is True and m.step == "preview"
    assert m.can_advance() is False
    m.set_preview({"will_supply": [{"cp": "c9002", "origin": "er"}],
                   "still_missing": [], "unaccounted": []})
    assert m.can_advance() is True
    assert m.advance() is True and m.step == "import"
    assert m.can_advance() is False


def test_model_back_invalidates_preview(tmp_path):
    m = iw.ERImportWizardModel(_missing(all=["c9002"], heritage=["c9002"]))
    m.advance()
    m.set_sources(er_dir=str(tmp_path))
    m.advance()
    m.set_preview({"will_supply": [], "still_missing": [], "unaccounted": []})
    assert m.back() is True and m.step == "sources"
    assert m.preview is None
