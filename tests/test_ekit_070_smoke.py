"""ekit 0.7.0: the smoke gate, BASE-SEAMS-PRESENT, GREEN-NO-DUMMY, `ekit trace matrix` and `ekit trace postman`."""
from __future__ import annotations

import copy
import csv
import io
import json

import pytest

from ekit import design, gates, golden, installer, trace, waves
from ekit.cli import main as ekit_main
from ekit.project import Project
from h070 import (design_data, errors, git, journeys_report, make_project, openapi_doc, run, write_design, write_ports,
                  write_reports)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("EKIT_SMOKE_NO_RUN", "1")
    monkeypatch.setenv(golden.SKIP_POST_INSTALL_ENV, "1")


@pytest.fixture
def proj(tmp_path):
    p = make_project(tmp_path)
    write_design(p.root)
    write_reports(p.root)
    write_ports(p.root)
    return Project.load(p.root)


def _journeys(**edit):
    rep = journeys_report()
    for k, fn in edit.items():
        fn(rep)
    return rep


# ---------------------------------------------------------------- the gate as a whole
def test_smoke_gate_passes_with_a_complete_design_and_passing_journeys(proj):
    res, _ = gates.run_gate(proj, "smoke")
    assert res.passed, [(c.id, [f.message for f in c.findings]) for c in res.checks if c.status == "fail"]
    assert [c.id for c in res.checks] == ["SMOKE-RUN", "SMOKE-JOURNEYS-PASS", "SMOKE-OPERATION-EXISTS", "SMOKE-OPERATION-EXERCISED",
                                         "SMOKE-PAGE-REACHABLE", "SMOKE-FEATURE-COVERED", "SMOKE-W0-INTACT",
                                         "DESIGN-PORTS-IMPLEMENTED", "BASE-SEAMS-PRESENT"]


def test_smoke_gate_fails_without_reports_and_says_how_to_make_them(tmp_path):
    p = make_project(tmp_path)
    write_design(p.root)
    res, _ = gates.run_gate(p, "smoke")
    assert not res.passed
    msg = next(f.message for c in res.checks if c.id == "SMOKE-JOURNEYS-PASS" for f in c.findings)
    assert "ekit run journeys" in msg


def test_smoke_run_executes_the_journeys_command_and_removes_stale_reports(proj, monkeypatch):
    monkeypatch.delenv("EKIT_SMOKE_NO_RUN")
    calls = []

    class R:
        returncode, output = 1, "boom\nline"

    def fake(prof, name, **kw):
        calls.append((prof.id, name, (prof.root / "reports/journeys.json").exists()))
        return R()
    monkeypatch.setattr("ekit.smoke.run_profile_command", fake)
    out = run(proj, "smoke.run")
    assert calls and calls[0][1] == "journeys" and calls[0][2] is False          # stale report removed first
    assert out and out[0][0] == "error" and "exited 1" in out[0][1] and "boom" in out[0][1]      # 0.7.1: a failed run fails SMOKE-RUN


# ---------------------------------------------------------------- SMOKE-JOURNEYS-PASS
def test_journeys_pass(proj):
    assert errors(proj, "smoke.journeys_pass") == []
    write_reports(proj.root, _journeys(a=lambda r: r["journeys"][0].update(outcome="failed")))
    assert any("journey J-01 failed" in e for e in errors(proj, "smoke.journeys_pass"))
    write_reports(proj.root, _journeys(a=lambda r: r.update(journeys=[])))
    assert any("records no journeys" in e for e in errors(proj, "smoke.journeys_pass"))
    d = design_data()
    d["slices"][0]["journeys"] = ["J-01", "J-02"]
    write_design(proj.root, d)
    write_reports(proj.root)
    assert any("J-02 never ran" in e for e in errors(proj, "smoke.journeys_pass"))


# ---------------------------------------------------------------- SMOKE-OPERATION-EXISTS
def test_operation_exists(proj):
    assert errors(proj, "smoke.operation_exists") == []
    spec = openapi_doc()
    del spec["paths"]["/api/v1/unread"]
    write_reports(proj.root, openapi=spec)
    assert any("`list_unread` is in design.yaml but not in the app's OpenAPI" in e for e in errors(proj, "smoke.operation_exists"))
    (proj.root / "reports/openapi.json").unlink()
    assert any("OpenAPI" in e for e in errors(proj, "smoke.operation_exists"))


# ---------------------------------------------------------------- SMOKE-OPERATION-EXERCISED
def test_operation_exercised(proj):
    assert errors(proj, "smoke.operation_exercised") == []
    write_reports(proj.root, _journeys(a=lambda r: r["calls"].__setitem__(0, {**r["calls"][0], "status": 500})))
    assert any("`send_message` was called but never got a 2xx" in e for e in errors(proj, "smoke.operation_exercised"))
    write_reports(proj.root, _journeys(a=lambda r: r.update(calls=[c for c in r["calls"] if c["operation_id"] != "list_unread"])))
    assert any("`list_unread` was never called by any journey" in e for e in errors(proj, "smoke.operation_exercised"))
    # calls made outside a journey do not count
    write_reports(proj.root, _journeys(a=lambda r: [c.update(journey=None) for c in r["calls"]]))
    assert len(errors(proj, "smoke.operation_exercised")) == 3
    # a non-key feature is not required
    d = design_data()
    d["features"]["FEAT-02"]["key"] = False
    write_design(proj.root, d)
    assert not any("list_unread" in e for e in errors(proj, "smoke.operation_exercised"))


# ---------------------------------------------------------------- SMOKE-PAGE-REACHABLE
def test_page_reachable(proj):
    assert errors(proj, "smoke.page_reachable") == []
    write_reports(proj.root, _journeys(a=lambda r: r["calls"].__setitem__(3, {**r["calls"][3], "status": 302})))
    assert any("page `GET /chat/{peer}` never returned 200" in e for e in errors(proj, "smoke.page_reachable"))
    write_reports(proj.root, _journeys(a=lambda r: r["calls"].__setitem__(3, {**r["calls"][3], "principal": None})))
    assert errors(proj, "smoke.page_reachable")                                  # needs a signed-in dev user
    # matched by path pattern when the route template was not recorded
    write_reports(proj.root, _journeys(a=lambda r: r["calls"].__setitem__(3, {**r["calls"][3], "route": None})))
    assert errors(proj, "smoke.page_reachable") == []


# ---------------------------------------------------------------- SMOKE-FEATURE-COVERED
def test_feature_covered(proj):
    assert errors(proj, "smoke.feature_covered") == []
    write_reports(proj.root, _journeys(a=lambda r: r["journeys"][0].update(features=["FEAT-01"])))
    assert errors(proj, "smoke.feature_covered") == ["key feature FEAT-02 has no journey tagged @FEAT-02"]


# ---------------------------------------------------------------- SMOKE-W0-INTACT
def test_w0_journeys_are_fingerprinted_after_adoption(proj):
    from ekit.project import dump_yaml
    assert run(proj, "smoke.w0_intact")[0][0] == "info"
    j = proj.root / "tests/acceptance/journeys"
    j.mkdir(parents=True)
    (j / "j01.feature").write_text("Feature: x\n", encoding="utf-8")
    dump_yaml({"on": "2026-01-01", "by": "Priya", "files": waves.journey_files(proj.root)}, proj.root / waves.W0_RECORD)
    assert errors(proj, "smoke.w0_intact") == []
    (j / "j02.feature").write_text("Feature: new\n", encoding="utf-8")            # adding journeys is fine
    assert errors(proj, "smoke.w0_intact") == []
    (j / "j01.feature").write_text("Feature: x changed\n", encoding="utf-8")
    assert any("changed after the adoption point" in e for e in errors(proj, "smoke.w0_intact"))
    (j / "j01.feature").unlink()
    assert any("deleted after the adoption point" in e for e in errors(proj, "smoke.w0_intact"))


# ---------------------------------------------------------------- BASE-SEAMS-PRESENT
def _golden(tmp_path):
    root = tmp_path / "g"
    (root / ".ekit").mkdir(parents=True)
    from ekit import kitsource
    from ekit.project import dump_yaml
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": "fastapi-jinja"}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    git(root, "init", "-q")
    installer.set_baseline_mode(root, "golden")
    installer.install_golden(Project.load(root), name="Demo", run_post=False)
    return Project.load(root)


def test_seams_present_in_the_golden_core_and_missing_when_removed(tmp_path):
    g = _golden(tmp_path)
    assert errors(g, "base.seams_present") == []
    f = g.root / "src/app/core/audit.py"
    f.write_text(f.read_text().replace("class LogAuditSink", "class RenamedSink"), encoding="utf-8")
    assert errors(g, "base.seams_present") == ["seam audit: `LogAuditSink` is missing from src/app/core/audit.py"]
    (g.root / "src/app/core/ownership.py").unlink()
    assert any("seam data_owner" in e and "missing from the core" in e for e in errors(g, "base.seams_present"))


def test_seams_check_is_informational_without_a_golden_core_and_asks_for_1_1_0_on_old_ones(tmp_path):
    p = make_project(tmp_path)
    assert run(p, "base.seams_present")[0][0] == "info"
    g = _golden(tmp_path)
    lock = g.root / ".ekit/kit/golden/fastapi-jinja/golden.yaml"
    lock.write_text(lock.read_text().replace("day0_seams:", "old_seams:"), encoding="utf-8")
    assert any("needs 1.1.0" in e for e in errors(Project.load(g.root), "base.seams_present"))


# ---------------------------------------------------------------- GREEN-NO-DUMMY
def test_no_dummy(proj):
    msgs = errors(proj, "green.no_dummy")
    assert any("seam `principal` is still the Day-0 dummy `dev-users`" in e for e in msgs)
    assert any("seam `audit` is still the Day-0 dummy `log`" in e for e in msgs)
    d = design_data()
    d["seams"]["principal"] = {"impl": "oidc"}
    d["seams"]["audit"] = {"impl": "store"}
    write_design(proj.root, d)
    assert errors(proj, "green.no_dummy") == []
    (proj.root / ".env.prod").write_text("APP_ENV=prod\nAPP_PRINCIPAL_PROVIDER=dev-users\n", encoding="utf-8")
    assert any(".env.prod: a non-dev environment sets APP_PRINCIPAL_PROVIDER=dev-users" in e for e in errors(proj, "green.no_dummy"))
    (proj.root / ".env.prod").write_text("APP_ENV=prod\nAPP_PRINCIPAL_PROVIDER=oidc\n", encoding="utf-8")
    (proj.root / ".env.dev").write_text("APP_ENV=dev\nAPP_PRINCIPAL_PROVIDER=dev-users\n", encoding="utf-8")
    assert errors(proj, "green.no_dummy") == []
    (proj.root / "config").mkdir()
    (proj.root / "config/dev-users.yaml").write_text("users: {}\n# APP_ENV=prod APP_AUDIT_SINK=log\n", encoding="utf-8")
    assert errors(proj, "green.no_dummy") == []                                 # the dev-users file itself is allow-listed


# ---------------------------------------------------------------- trace matrix
def test_trace_matrix_rows_and_formats(proj):
    rows = trace.matrix(proj.root)
    by = {(r["br"], r["item"]): r for r in rows}
    assert by[("BR-001", "send_message")]["journeys"] == ["J-01"] and by[("BR-001", "send_message")]["result"] == "pass (201)"
    assert by[("BR-002", "send_message")]["feature"] == "FEAT-01" and by[("BR-003", "list_unread")]["result"] == "pass (200)"
    assert by[("BR-001", "GET /chat/{peer}")]["kind"] == "page"
    assert len(rows) == 3 * 2 + 1                                              # FEAT-01: 3 items x 2 BRs, FEAT-02: 1 x 1
    md = trace.render(rows, "md")
    assert md.splitlines()[0].startswith("| BR | Feature") and "| BR-003 | FEAT-02 | operation | `list_unread` | J-01 | pass (200) |" in md
    parsed = list(csv.reader(io.StringIO(trace.render(rows, "csv"))))
    assert parsed[0] == ["br", "feature", "kind", "item", "journeys", "result"] and len(parsed) == len(rows) + 1
    assert json.loads(trace.render(rows, "json"))[0]["feature"] == "FEAT-01"


def test_trace_matrix_shows_not_run_and_failures(proj):
    write_reports(proj.root, _journeys(a=lambda r: r.update(calls=[c for c in r["calls"] if c["operation_id"] != "list_unread"]),
                                       b=lambda r: r["calls"].__setitem__(0, {**r["calls"][0], "status": 500})))
    by = {r["item"]: r["result"] for r in trace.matrix(proj.root)}
    assert by["list_unread"] == "not run" and by["send_message"] == "FAIL (500)"
    (proj.root / "reports/journeys.json").unlink()                              # no report at all: everything "not run"
    assert {r["result"] for r in trace.matrix(proj.root)} == {"not run"}


def test_cli_trace_matrix(proj, monkeypatch, capsys):
    monkeypatch.chdir(proj.root)
    assert ekit_main(["trace", "matrix", "--format", "csv"]) == 0
    assert capsys.readouterr().out.startswith("br,feature,kind,item,journeys,result")
    assert ekit_main(["trace", "matrix"]) == 0 and "| BR-001 | FEAT-01 |" in capsys.readouterr().out
    assert ekit_main(["trace", "matrix", "--format", "json", "--out", "reports/m.json"]) == 0
    assert json.loads((proj.root / "reports/m.json").read_text())


# ---------------------------------------------------------------- postman
def test_postman_collection(proj):
    (proj.root / "config").mkdir()
    (proj.root / "config/dev-users.yaml").write_text("users:\n  asha: {password: asha-dev}\n  ravi: {password: ravi-dev}\n", encoding="utf-8")
    c = trace.postman(proj.root, base_url="http://x:1")
    assert c["info"]["schema"] == trace.POSTMAN_SCHEMA
    assert c["auth"]["type"] == "basic" and {v["key"]: v["value"] for v in c["variable"]} == {
        "baseUrl": "http://x:1", "dev_user": "asha", "dev_password": "asha-dev"}
    ops = {i["name"]: i["request"] for i in c["item"][0]["item"]}
    assert set(ops) == {"send_message", "list_messages", "list_unread"}
    assert ops["send_message"]["method"] == "POST" and json.loads(ops["send_message"]["body"]["raw"]) == {"peer": "string", "body": "string"}
    assert ops["list_messages"]["url"]["raw"] == "{{baseUrl}}/api/v1/messages/:peer" and ops["list_messages"]["url"]["variable"][0]["key"] == "peer"
    journeys = c["item"][1]["item"][0]
    assert journeys["name"].startswith("J-01") and [i["name"] for i in journeys["item"]] == [
        "1. send_message as asha", "2. list_unread as ravi", "3. list_messages as ravi"]
    assert journeys["item"][1]["request"]["auth"]["basic"][1]["value"] == "ravi-dev"
    json.dumps(c)


def test_cli_trace_postman_writes_a_file_and_needs_the_openapi(proj, monkeypatch, capsys):
    monkeypatch.chdir(proj.root)
    assert ekit_main(["trace", "postman"]) == 0
    assert (proj.root / "reports/postman_collection.json").is_file()
    (proj.root / "reports/openapi.json").unlink()
    assert ekit_main(["trace", "postman"]) == 2 and "OpenAPI" in capsys.readouterr().err
