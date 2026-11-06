"""ekit 0.4.0: RED-GLUE-TYPED (type-check the frozen test module, because red never runs steps after the
first failure) and RED-ROUTE-STUBBED (a golden scenario fails with 501 from a stub, never 404)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_ekit_030 import CTX_MODULE, _feature, _golden_project

from ekit import checks, golden, redchecks
from ekit.project import Kit, Project, bundled_kit_dir

W = {"dir": "specs/001-chat/features"}
GLUE = "tests/acceptance/test_001_chat.py"


@pytest.fixture(autouse=True)
def _no_post_install(monkeypatch):
    monkeypatch.setenv(golden.SKIP_POST_INSTALL_ENV, "1")


def _ctx(project: Project) -> checks.GateContext:
    return checks.GateContext(project=project, feature_dir=project.root / "specs/001-chat")


def _fake_typecheck(project: Project, tmp_path: Path, line: str) -> None:
    script = tmp_path / "fake_mypy.py"
    script.write_text(f"import sys\nprint({line!r})\nprint('args', *sys.argv[1:])\n", encoding="utf-8")
    project.profiles[0].data["commands"]["typecheck_glue"] = [sys.executable, str(script)]


# ------------------------------------------------------------------ parse_mypy
def test_parse_mypy_keeps_logic_codes_in_bound_files_only(tmp_path):
    bound = tmp_path / "tests/acceptance/test_a.py"
    bound.parent.mkdir(parents=True)
    bound.write_text("", encoding="utf-8")
    out = (
        'tests/acceptance/test_a.py:12: error: "Client" has no attribute "put"  [attr-defined]\n'
        "tests/acceptance/test_a.py:13:5: error: Argument 1 has incompatible type  [arg-type]\n"
        "tests/acceptance/test_a.py:14: error: Untyped decorator makes function untyped  [untyped-decorator]\n"
        "tests/acceptance/test_a.py:15: error: something odd  [misc]\n"
        "tests/acceptance/test_a.py:16: error: no code at all\n"
        'src/app/other.py:3: error: "X" has no attribute "y"  [attr-defined]\n'
        "tests/acceptance/test_a.py:17: note: not an error"
    )
    got = redchecks.parse_mypy(out, tmp_path, [bound], redchecks.GLUE_LOGIC_CODES)
    assert [(g[1], g[3]) for g in got] == [(12, "attr-defined"), (13, "arg-type")]
    assert got[0][2] == '"Client" has no attribute "put"'
    assert redchecks.parse_mypy(out, tmp_path, [bound], {"misc"})[0][1] == 15


def test_parse_mypy_handles_absolute_and_drive_letter_paths(tmp_path):
    bound = tmp_path / "t.py"
    bound.write_text("", encoding="utf-8")
    out = f"{bound}:2: error: bad  [name-defined]\nC:\\x\\t.py:2: error: bad  [name-defined]"
    assert len(redchecks.parse_mypy(out, tmp_path, [bound], redchecks.GLUE_LOGIC_CODES)) == 1


# ------------------------------------------------------------------ glue_typecheck
def test_glue_typecheck_reports_errors_from_the_fake_command(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    _fake_typecheck(project, tmp_path, f'{GLUE}:7: error: "Resp" has no attribute "jsn"  [attr-defined]')
    ctx = _ctx(project)
    out = redchecks.glue_typecheck(ctx, W)
    assert len(out) == 1 and out[0].level == "error"
    assert out[0].message.startswith(f'{GLUE}:7 "Resp" has no attribute "jsn" [attr-defined] — ')
    assert "Fix it now." in out[0].message
    assert GLUE in ctx.outputs["backend/fastapi:typecheck_glue"]            # file passed relative to cwd


def test_glue_typecheck_is_clean_when_only_style_noise(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    _fake_typecheck(project, tmp_path, f"{GLUE}:7: error: Untyped decorator  [untyped-decorator]")
    assert redchecks.glue_typecheck(_ctx(project), W) == []


def test_glue_typecheck_warns_when_the_command_cannot_start(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    project.profiles[0].data["commands"]["typecheck_glue"] = [str(tmp_path / "missing-binary")]
    out = redchecks.glue_typecheck(_ctx(project), W)
    assert len(out) == 1 and out[0].level == "warn" and "typecheck_glue" in out[0].message


def test_glue_typecheck_skips_without_a_command_and_without_bound_files(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    project.profiles[0].data["commands"].pop("typecheck_glue", None)
    out = redchecks.glue_typecheck(_ctx(project), W)
    assert [(f.level, f.message) for f in out] == [("info", "skipped: no typecheck_glue command in this stack")]
    _fake_typecheck(project, tmp_path, "x")
    (project.root / GLUE).unlink()
    assert redchecks.glue_typecheck(_ctx(project), W) == []


# ------------------------------------------------------------------ route_stubbed
def _report(project: Project, message: str) -> None:
    report = project.root / "reports/cucumber-backend.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    steps = [{"keyword": "Given ", "name": "the app", "result": {"status": "passed"}},
             {"keyword": "Then ", "name": "the response status is 200",
              "result": {"status": "failed", "error_message": message}}]
    report.write_text(json.dumps([{"name": "Chat", "tags": [], "elements": [
        {"type": "scenario", "tags": [{"name": "SCN-001-01"}], "steps": steps}]}]), encoding="utf-8")


def test_route_stubbed_flags_404_but_not_501(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    _report(project, "E   AssertionError: expected 200, got 404 application/json: {}")
    out = redchecks.route_stubbed(_ctx(project), W)
    assert len(out) == 1 and out[0].level == "error"
    assert "SCN-001-01: failed with 404 at step 'Then the response status is 200', not 501" in out[0].message
    _report(project, "E   AssertionError: expected 200, got 501 application/json: {}")
    assert redchecks.route_stubbed(_ctx(project), W) == []


def test_route_stubbed_ignores_an_expected_404(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    _report(project, "E   AssertionError: expected 404, got 404 text/html: x")
    assert redchecks.route_stubbed(_ctx(project), W) == []


def test_route_stubbed_is_golden_only(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    _report(project, "E   AssertionError: expected 200, got 404 text/html: x")
    project.config.setdefault("baseline", {})["mode"] = "minimal"
    assert redchecks.route_stubbed(_ctx(project), W) == []


# ------------------------------------------------------------------ policy wiring
def test_red_gate_order_has_the_new_checks_in_place():
    gates = Kit.load(bundled_kit_dir()).policy()["spec"]["gates"]
    red = next(g for g in gates if g["id"] == "red")
    assert [c["id"] for c in red["checks"]][:8] == [   # 0.5.0 appends RED-BUG-REPRODUCED, RED-CHANGE-SUPERSEDES
        "RED-STEPS-ASSERT", "RED-STEPS-BOUND", "RED-STATE-TYPED", "RED-GLUE-TYPED",
        "RED-NO-EXEMPLAR", "RED-RUN", "RED-CLEAN-FAILURE", "RED-ROUTE-STUBBED"]
    types = {c["id"]: c["type"] for c in red["checks"]}
    assert types["RED-GLUE-TYPED"] == "bdd.glue_typecheck" and types["RED-ROUTE-STUBBED"] == "bdd.route_stubbed"
    assert {"bdd.glue_typecheck", "bdd.route_stubbed"} <= set(checks.REGISTRY)
