"""Tests for engine.roster_resolve.resolve_available_roster — pure, no game
assets required (synthetic ns / reg / roster / on-disk chr dir)."""
import json
import os
import re

import pytest

from engine.roster_resolve import resolve_available_roster

_CHR_RE = re.compile(r'^(c\d{4})(_[a-zA-Z0-9]+)?\.(chrbnd|anibnd|behbnd|texbnd)\.dcx$')


class FakeReg:
    def __init__(self, npc_ids, think_ids):
        self._npc, self._think = list(npc_ids), list(think_ids)

    def param_rows(self, name):
        if name == "NpcParam":
            return self._npc
        if name == "NpcThinkParam":
            return self._think
        raise KeyError(name)


def _make_ns(tmp_path):
    """ns with synthetic _data_path + detect_asset_packs and a target chr
    dir. heritage pack = {c9001, c9002}; mmv pack = {c9100}. c9001 + c9100
    present on disk; c9002 absent."""
    data = tmp_path / "data"; data.mkdir()
    target = tmp_path / "chr"; target.mkdir()
    (data / "heritage_pack.json").write_text(json.dumps(
        {"_meta": {}, "tags": {"c9001": {}, "c9002": {}}}))
    (data / "mmv_imports.json").write_text(json.dumps(
        {"_meta": {}, "tags": {"c9100": {}}}))
    for cp in ("c9001", "c9100"):
        (target / f"{cp}.chrbnd.dcx").write_bytes(b"")

    def _data_path(fn):
        return os.path.join(str(data), fn)

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
            cps = sorted((json.load(open(_data_path(fname), encoding="utf-8")).get("tags") or {}).keys())
            out[pid] = {"enabled": True, "missing": [c for c in cps if c not in present]}
        return out

    ns = {"_data_path": _data_path, "detect_asset_packs": detect_asset_packs}
    return ns, str(target)


def _roster():
    return {"all_variants": [
        {"c_prefix": "c1000", "npc_param_id": 10000000, "think_param_id": 10000000,
         "variant_name": "vanilla_a"},
        {"c_prefix": "c1000", "npc_param_id": 10000001, "think_param_id": 0,
         "variant_name": "vanilla_b"},
        {"c_prefix": "c9001", "npc_param_id": 90010000, "think_param_id": 90010000,
         "variant_name": "heritage_present"},
        {"c_prefix": "c9100", "npc_param_id": 91000000, "think_param_id": 91000000,
         "variant_name": "mmv_present"},
        {"c_prefix": "c9002", "npc_param_id": 90020000, "think_param_id": 90020000,
         "variant_name": "heritage_absent"},
    ]}


def test_classification_present_absent_vanilla(tmp_path):
    ns, target = _make_ns(tmp_path)
    res = resolve_available_roster(ns, None, _roster(), target)
    assert res["vanilla"] == ["c1000"]
    assert res["imported_present"] == ["c9001", "c9100"]
    assert res["imported_absent"] == ["c9002"]
    assert res["available"] == ["c1000", "c9001", "c9100"]


def test_reg_none_fails_open(tmp_path):
    ns, target = _make_ns(tmp_path)
    res = resolve_available_roster(ns, None, _roster(), target)
    assert res["param_checked"] is False
    assert res["placeable"] == res["available"]
    assert res["no_target_after_params"] == []


def test_all_params_present_all_placeable(tmp_path):
    ns, target = _make_ns(tmp_path)
    reg = FakeReg(npc_ids=[10000000, 10000001, 90010000, 91000000],
                  think_ids=[10000000, 90010000, 91000000])
    res = resolve_available_roster(ns, reg, _roster(), target)
    assert res["param_checked"] is True
    assert res["placeable"] == ["c1000", "c9001", "c9100"]
    assert res["no_target_after_params"] == []
    assert res["missing_npc_param"] == []
    assert res["missing_think_param"] == []


def test_missing_think_param_flagged_but_still_placeable(tmp_path):
    # c9100's think id absent. It's its only variant -> no usable target.
    ns, target = _make_ns(tmp_path)
    reg = FakeReg(npc_ids=[10000000, 10000001, 90010000, 91000000],
                  think_ids=[10000000, 90010000])  # no 91000000
    res = resolve_available_roster(ns, reg, _roster(), target)
    assert "c9100" in res["missing_think_param"]
    assert "c9100" in res["no_target_after_params"]
    assert "c9100" not in res["placeable"]


def test_missing_npc_param_one_variant_other_saves_prefix(tmp_path):
    # c1000 has two variants; kill only variant_b's npc id -> flagged but
    # c1000 stays placeable via variant_a.
    ns, target = _make_ns(tmp_path)
    reg = FakeReg(npc_ids=[10000000, 90010000, 91000000],  # no 10000001
                  think_ids=[10000000, 90010000, 91000000])
    res = resolve_available_roster(ns, reg, _roster(), target)
    assert "c1000" in res["missing_npc_param"]
    assert "c1000" in res["placeable"]
    assert "c1000" not in res["no_target_after_params"]


def test_absent_chr_never_placeable(tmp_path):
    # c9002 is absent on disk -> not in available -> not param-checked.
    ns, target = _make_ns(tmp_path)
    reg = FakeReg(npc_ids=[90020000], think_ids=[90020000])
    res = resolve_available_roster(ns, reg, _roster(), target)
    assert "c9002" not in res["available"]
    assert "c9002" not in res["placeable"]
    assert "c9002" in res["imported_absent"]


def test_zero_ids_not_gated(tmp_path):
    # vanilla_b has think_param_id 0; absence of a 0 row must not gate it.
    ns, target = _make_ns(tmp_path)
    reg = FakeReg(npc_ids=[10000000, 10000001, 90010000, 91000000],
                  think_ids=[10000000, 90010000, 91000000])  # no '0' row
    res = resolve_available_roster(ns, reg, _roster(), target)
    assert "c1000" in res["placeable"]


def test_presence_gating_set(tmp_path):
    # The set the worker excludes = imported_absent | no_target_after_params.
    ns, target = _make_ns(tmp_path)
    reg = FakeReg(npc_ids=[10000000, 10000001, 90010000, 91000000],
                  think_ids=[10000000, 90010000])  # c9100 paramless
    res = resolve_available_roster(ns, reg, _roster(), target)
    gating = set(res["imported_absent"]) | set(res["no_target_after_params"])
    assert gating == {"c9002", "c9100"}


def test_counts_consistent(tmp_path):
    ns, target = _make_ns(tmp_path)
    res = resolve_available_roster(ns, None, _roster(), target)
    assert res["counts"]["available"] == len(res["available"])
    assert res["counts"]["imported_absent"] == len(res["imported_absent"])
    assert res["counts"]["placeable"] == len(res["placeable"])


def test_real_data_smoke(tmp_path):
    # Against the real bundled packs + a real regulation, the call must not
    # raise and must return a coherent shape.
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        import oops_v3 as ov3
        roster, _tags = ov3.load_data()
    ns = vars(ov3)
    res = resolve_available_roster(ns, None, roster, str(tmp_path))
    assert set(res["available"]) == set(res["vanilla"]) | set(res["imported_present"])
    assert res["param_checked"] is False
    assert isinstance(res["counts"]["available"], int)
