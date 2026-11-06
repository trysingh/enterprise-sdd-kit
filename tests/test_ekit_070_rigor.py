"""ekit 0.7.0: rigor levels per wave; gate reports name the level and the checks it skipped."""
from __future__ import annotations

import json

import pytest

from ekit import gates, rigor, waves
from ekit.project import Kit, Project, bundled_kit_dir, dump_yaml
from h070 import make_project


def _plan(root, level_w0="skeleton", current="W0", w1="standard"):
    waves_ = [{"id": "W0", "goal": "happy", "scope": ["chat:FEAT-01", "chat:FEAT-02"], **({"rigor": level_w0} if level_w0 else {})},
              {"id": "W1", "goal": "depth", "scope": [], **({"rigor": w1} if w1 else {})}]
    dump_yaml({"apiVersion": "ekit/v1", "kind": "WavePlan", "current": current, "approved_by": "t", "approved_on": "2026-01-01",
               "waves": waves_}, root / ".ekit/waves.yaml")
    return Project.load(root)


def test_policy_names_only_things_that_exist():
    kit = Kit.load(bundled_kit_dir())
    pol = rigor.load_policy(kit)
    assert set(pol["levels"]) == {"skeleton", "standard", "enterprise"}
    gate_ids = {g["id"] for g in kit.policy()["spec"]["gates"]}
    check_ids = {c["id"] for g in kit.policy()["spec"]["gates"] for c in g["checks"]}
    aliases = set(pol["aliases"])
    for lv in pol["levels"].values():
        names = [n for n in (lv.get("on") if isinstance(lv.get("on"), list) else []) + (lv.get("off") or [])]
        assert set(names) <= gate_ids | check_ids | aliases, set(names) - (gate_ids | check_ids | aliases)
        assert set(lv.get("add") or []) - {"overlays"} <= check_ids
    for ids in pol["aliases"].values():
        assert set(ids) <= check_ids


def test_decide_per_level():
    pol = rigor.load_policy(Kit.load(bundled_kit_dir()))
    d = rigor.decide
    assert d(pol, None, "green", "GREEN-RUN") is None and d(pol, None, "green", "GREEN-NO-DUMMY") == "omit"
    assert "off at this level" in d(pol, "skeleton", "red", "RED-RUN")
    assert "'coverage'" in d(pol, "skeleton", "green", "GREEN-COVERAGE")
    assert "'sca'" in d(pol, "skeleton", "green", "GREEN-SCA")
    assert d(pol, "skeleton", "green", "GREEN-LINT") is None and d(pol, "skeleton", "green", "GREEN-UNIT") is None
    assert d(pol, "skeleton", "baseline", "BASE-GOLDEN-INTACT") is None
    assert d(pol, "skeleton", "smoke", "SMOKE-JOURNEYS-PASS") is None and d(pol, "skeleton", "design", "DESIGN-FILES") is None
    assert "off at this level" in d(pol, "skeleton", "plan", "PLAN-NFR-CONFORMANCE")
    assert d(pol, "standard", "red", "RED-RUN") is None
    assert "only runs at enterprise" in d(pol, "standard", "green", "GREEN-NO-DUMMY")
    assert d(pol, "enterprise", "green", "GREEN-NO-DUMMY") is None


def test_unconfigured_projects_behave_like_0_6_4(tmp_path):
    p = make_project(tmp_path, lane=None)
    assert rigor.level(p) is None
    res, notes = gates.run_gate(p, "baseline")
    assert res.rigor is None and not any(n.startswith("rigor") for n in notes)
    assert all(c.skipped is None for c in res.checks)
    green = [c["id"] for g in p.kit.policy()["spec"]["gates"] if g["id"] == "green" for c in g["checks"]]
    assert "GREEN-NO-DUMMY" in green                                            # in the policy ...
    assert "design" not in gates.default_gate_ids(p) and "smoke" not in gates.default_gate_ids(p)   # ... gate all unchanged
    # a wave plan whose waves name no rigor is also "not configured"
    q = _plan(p.root, level_w0=None, w1=None)
    assert rigor.level(q) is None


def test_skeleton_skips_and_names_the_checks(tmp_path):
    p = _plan(make_project(tmp_path).root)
    assert rigor.level(p) == "skeleton"
    res, notes = gates.run_gate(p, "red")            # no feature exists: every check is off, none needs one
    assert res.passed and res.rigor == "skeleton"
    assert all(c.status == "skipped" and c.skipped.startswith("rigor skeleton") for c in res.checks)
    assert any(n.startswith("rigor: skeleton; skipped because of it: RED-STEPS-ASSERT") for n in notes)
    text = gates.render_text(res, notes)
    assert "rigor: skeleton" in text and "[SKIP] RED-RUN" in text
    data = json.loads(gates.render_json(res, notes))
    assert data["rigor"] == "skeleton" and "RED-RUN" in data["rigor_skipped"]
    res, notes = gates.run_gate(p, "green")
    skipped = {c.id for c in res.checks if c.skipped}
    assert {"GREEN-COVERAGE", "GREEN-SCA", "GREEN-RUN", "GREEN-RED-FIRST", "GREEN-NO-DUMMY"} <= skipped
    assert not ({"GREEN-LINT", "GREEN-UNIT", "GREEN-ENV"} & skipped)


def test_standard_runs_everything_except_the_enterprise_check(tmp_path):
    p = _plan(make_project(tmp_path).root, current="W1")
    res, notes = gates.run_gate(p, "baseline")
    assert res.rigor == "standard" and not [c for c in res.checks if c.skipped]
    assert "rigor: standard; nothing skipped" in notes
    pol = rigor.load_policy(p.kit)
    assert rigor.decide(pol, "standard", "green", "GREEN-NO-DUMMY").startswith("rigor standard: only runs at enterprise")


def test_enterprise_runs_green_no_dummy(tmp_path):
    root = make_project(tmp_path).root
    dump_yaml({"apiVersion": "ekit/v1", "kind": "WavePlan", "current": "W2", "approved_by": "t", "approved_on": "2026-01-01",
               "waves": [{"id": "W0", "scope": [], "rigor": "skeleton"}, {"id": "W1", "scope": [], "rigor": "standard"},
                         {"id": "W2", "scope": [], "rigor": "enterprise"}]}, root / ".ekit/waves.yaml")
    p = Project.load(root)
    assert rigor.level(p) == "enterprise"
    assert rigor.decide(rigor.load_policy(p.kit), "enterprise", "green", "GREEN-NO-DUMMY") is None


def test_wave_plan_validation_rejects_an_unknown_rigor(tmp_path):
    p = _plan(make_project(tmp_path).root, level_w0="paranoid")
    errors, _ = waves.validate(p.wave_plan, p.kit, waves.catalog_ids(p.kit))
    assert any("rigor 'paranoid'" in e for e in errors)
    ok = _plan(p.root)
    errors, _ = waves.validate(ok.wave_plan, ok.kit, waves.catalog_ids(ok.kit))
    assert not errors


@pytest.mark.parametrize("gate", ["red", "scenarios", "plan", "spec", "red-recorded"])
def test_skeleton_switches_whole_gates_off(tmp_path, gate):
    p = _plan(make_project(tmp_path).root)
    res, _ = gates.run_gate(p, gate)
    assert res.passed and all(c.skipped for c in res.checks), gate
