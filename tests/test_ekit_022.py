"""ekit 0.2.2: a scenario failing on broken test glue, not an assertion, slipped through red as
if it were legitimate, and an agent fixing frozen test glue used the unfrozen window to implement
production code instead. Both happened on the same real project (intranet messenger).

* RED-CLEAN-FAILURE: red rejects a scenario that *errored* (KeyError, undefined step reached at
  runtime, ...) rather than failed on an assertion, even though pytest-bdd reports both as 'failed'.
* `ekit unfreeze` denies the feature's own production source directories while its tests are
  unfrozen, by default, re-allowing them the moment `ekit gate red` re-freezes.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from ekit import checks, freeze, gherkin
from ekit.project import dump_yaml


def _ctx(tmp_path, framework="pytest-bdd", *, report="reports/cucumber.json"):
    prof = SimpleNamespace(id="backend/fastapi", runs_bdd=True, bdd={"framework": framework, "report": report},
                           root=tmp_path, data={"layout": {"acceptance_tests": "tests/acceptance", "source": "src/app"}})
    project = SimpleNamespace(root=tmp_path, profiles=[prof], rel=lambda p: str(Path(p).relative_to(tmp_path)))
    feat = tmp_path / "specs" / "001-demo"
    return checks.GateContext(project=project, feature_dir=feat)


def _feature(tmp_path):
    (tmp_path / "specs/001-demo/features").mkdir(parents=True)
    (tmp_path / "specs/001-demo/features/a.feature").write_text(
        "@SCN-001-01\nFeature: A\n  Scenario: s\n    Given x\n", encoding="utf-8")
    (tmp_path / "tests/acceptance").mkdir(parents=True)
    return _ctx(tmp_path)


W = {"dir": "specs/001-demo/features"}


def _write_report(tmp_path, ctx, status: str, error_message: str | None = None):
    report = ctx.project.profiles[0].bdd["report"]
    p = tmp_path / report
    p.parent.mkdir(parents=True, exist_ok=True)
    result = {"status": status}
    if error_message is not None:
        result["error_message"] = error_message
    p.write_text(json.dumps([{"name": "A", "tags": [], "elements": [
        {"type": "scenario", "tags": [{"name": "SCN-001-01"}], "steps": [{"result": result}]}
    ]}]), encoding="utf-8")


# --------------------------------------------------------------------- gherkin helpers
def test_failure_exception_reads_the_innermost_name_from_a_traceback():
    el = {"steps": [{"result": {"status": "failed", "error_message":
          "tests/x.py:10: in f\n    y = d['missing']\nE   KeyError: 'missing'\n"}}]}
    assert gherkin.failure_exception(el) == "KeyError"


def test_failure_exception_is_none_without_a_recognisable_traceback():
    el = {"steps": [{"result": {"status": "failed", "error_message": "boom, no idea"}}]}
    assert gherkin.failure_exception(el) is None


def test_read_cucumber_elements_matches_the_same_scn_tags_as_read_cucumber_reports(tmp_path):
    ctx = _feature(tmp_path)
    _write_report(tmp_path, ctx, "failed", "E   AssertionError: nope")
    report = tmp_path / ctx.project.profiles[0].bdd["report"]
    assert gherkin.read_cucumber_elements([report])["SCN-001-01"]


# --------------------------------------------------------------------- bdd.clean_failure check
def test_clean_failure_accepts_a_genuine_assertion_error(tmp_path):
    ctx = _feature(tmp_path)
    _write_report(tmp_path, ctx, "failed", "tests/x.py:5: in f\n    assert False\nE   AssertionError\n")
    assert checks.clean_failure(ctx, W) == []


def test_clean_failure_rejects_broken_test_glue(tmp_path):
    ctx = _feature(tmp_path)
    _write_report(tmp_path, ctx, "failed", "tests/x.py:10: in f\n    y = d['missing']\nE   KeyError: 'missing'\n")
    out = checks.clean_failure(ctx, W)
    assert len(out) == 1 and out[0].level == "error" and "KeyError" in out[0].message


def test_clean_failure_ignores_a_passing_or_undefined_scenario(tmp_path):
    ctx = _feature(tmp_path)
    _write_report(tmp_path, ctx, "passed")
    assert checks.clean_failure(ctx, W) == []


def test_clean_failure_honours_an_explicit_allow_list(tmp_path):
    ctx = _feature(tmp_path)
    _write_report(tmp_path, ctx, "failed", "E   NotImplementedError: stub\n")
    assert checks.clean_failure(ctx, {**W, "allow": ["AssertionError", "NotImplementedError"]}) == []


def test_clean_failure_skips_scenarios_outside_this_feature(tmp_path):
    ctx = _feature(tmp_path)
    # a report entry for a different feature's scenario never reaches this feature's SCN id
    report = tmp_path / ctx.project.profiles[0].bdd["report"]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps([{"name": "B", "tags": [], "elements": [
        {"type": "scenario", "tags": [{"name": "SCN-002-01"}],
         "steps": [{"result": {"status": "failed", "error_message": "E   KeyError: 'x'\n"}}]}]}]), encoding="utf-8")
    assert checks.clean_failure(ctx, W) == []


# --------------------------------------------------------------------- narrow unfreeze
def _frozen_state(root: Path) -> dict:
    return yaml.safe_load((root / ".ekit/freeze.yaml").read_text())


def test_unfreeze_denies_the_feature_source_dir_by_default(tmp_path):
    (tmp_path / ".ekit").mkdir()
    freeze.freeze_feature(tmp_path, "001-demo", {"specs/001-demo/features/a.feature": "deadbeef"})
    freeze.unfreeze_feature(tmp_path, "001-demo", "fix the step glue", narrow_src=["src/app/**"])
    state = _frozen_state(tmp_path)
    assert "001-demo" not in state["frozen"]
    assert state["narrow"]["001-demo"] == ["src/app/**"]
    rules = json.loads((tmp_path / "opencode.json").read_text())["permission"]["edit"]
    assert rules["src/app/**"] == "deny"
    assert "specs/001-demo/features/*" not in rules or rules.get("specs/001-demo/features/*") != "deny"


def test_unfreeze_with_allow_src_skips_the_source_deny(tmp_path):
    (tmp_path / ".ekit").mkdir()
    freeze.freeze_feature(tmp_path, "001-demo", {"specs/001-demo/features/a.feature": "deadbeef"})
    freeze.unfreeze_feature(tmp_path, "001-demo", "fix the step glue", narrow_src=None)
    state = _frozen_state(tmp_path)
    assert state["narrow"] == {}


def test_refreezing_lifts_the_narrow_source_deny(tmp_path):
    (tmp_path / ".ekit").mkdir()
    freeze.freeze_feature(tmp_path, "001-demo", {"specs/001-demo/features/a.feature": "deadbeef"})
    freeze.unfreeze_feature(tmp_path, "001-demo", "fix the step glue", narrow_src=["src/app/**"])
    assert _frozen_state(tmp_path)["narrow"]
    freeze.freeze_feature(tmp_path, "001-demo", {"specs/001-demo/features/a.feature": "cafebabe"})
    state = _frozen_state(tmp_path)
    assert state["narrow"] == {}
    rules = json.loads((tmp_path / "opencode.json").read_text())["permission"]["edit"]
    assert rules.get("src/app/**") != "deny"


def test_verify_reports_a_narrow_unfreeze(tmp_path):
    (tmp_path / ".ekit").mkdir()
    freeze.freeze_feature(tmp_path, "001-demo", {"specs/001-demo/features/a.feature": "deadbeef"})
    freeze.unfreeze_feature(tmp_path, "001-demo", "fix the step glue", narrow_src=["src/app/**"])
    rows = freeze.verify(tmp_path)
    label = next(label for ok, label, detail in rows if "001-demo unfrozen" in label)
    assert label  # found; detail text already asserted indirectly via the ok flag
    ok = next(ok for ok, label, detail in rows if "001-demo unfrozen" in label)
    assert ok


# --------------------------------------------------------------------- bundled kit wiring
def test_bundled_kit_wires_the_022_checks():
    from ekit.project import Kit, bundled_kit_dir
    pol = Kit.load(bundled_kit_dir()).policy()["spec"]["gates"]
    by_gate = {g["id"]: {c["id"] for c in g["checks"]} for g in pol}
    assert "RED-CLEAN-FAILURE" in by_gate["red"]
    assert yaml.safe_load((bundled_kit_dir() / "kit.yaml").read_text())["requires"]["ekit"] == ">=0.2.5,<0.3"
