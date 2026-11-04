"""ekit 0.1.5: governance gaps found while validating the quiz against the code.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
import yaml

from ekit import checks, gates, questions
from ekit.project import EkitError, dump_yaml

from test_ekit import W, _feature_project, _pinned_project


# ------------------------------------------------------------------ red: only a real failure counts
def _run_red(ctx, tmp_path, monkeypatch, status):
    prof = ctx.project.profiles[0]
    prof.bdd = {"framework": "pytest-bdd", "report": "reports/cucumber.json"}
    ctx.project.kit = SimpleNamespace(version="9.9.9")
    report = [{"name": "A", "tags": [], "elements": [{"type": "scenario", "tags": [{"name": "SCN-001-01"}],
               "steps": [{"result": {"status": status}}]}]}]

    def fake_run(profile, name, **_):
        (tmp_path / "reports").mkdir(exist_ok=True)
        (tmp_path / "reports/cucumber.json").write_text(json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=1, output="", cwd=tmp_path)

    monkeypatch.setattr(checks, "run_profile_command", fake_run)
    monkeypatch.setattr("ekit.freeze.freeze_feature", lambda *a, **k: [])
    return checks.bdd_run(ctx, {"expect": "red", "dir": W["dir"], "record": True})


def test_red_rejects_a_skipped_scenario_and_records_nothing(tmp_path, monkeypatch):
    ctx = _feature_project(tmp_path)
    out = _run_red(ctx, tmp_path, monkeypatch, "skipped")
    errs = [f.message for f in out if f.level == "error"]
    assert errs and "skipped" in errs[0] and "FAIL" in errs[0]
    assert not (tmp_path / ".ekit/ledger/001-demo.yaml").exists()


def test_red_accepts_a_failing_scenario(tmp_path, monkeypatch):
    ctx = _feature_project(tmp_path)
    out = _run_red(ctx, tmp_path, monkeypatch, "failed")
    assert not [f for f in out if f.level == "error"], out


def test_red_first_counts_only_failed_entries(tmp_path):
    ctx = _feature_project(tmp_path)
    ledger = tmp_path / ".ekit/ledger/001-demo.yaml"
    dump_yaml({"feature": "001-demo", "entries": [{"phase": "red", "scenarios": {"SCN-001-01": "skipped"}}]}, ledger)
    assert any("never recorded failing" in f.message for f in checks.red_first(ctx, W))
    dump_yaml({"feature": "001-demo", "entries": [{"phase": "red", "scenarios": {"SCN-001-01": "failed"}}]}, ledger)
    assert not [f for f in checks.red_first(ctx, W) if f.level == "error"]


# ------------------------------------------------------------------ Waived needs a real ADR reference
def test_adr_reference_is_not_satisfied_by_a_date():
    assert checks.ADR_REF_RE.search("ADR-0007") and checks.ADR_REF_RE.search("see adr 12")
    assert checks.ADR_REF_RE.search("docs/adr/0007-audit-deferral.md")
    assert not checks.ADR_REF_RE.search("audit store replaced 2026-12")
    assert not checks.ADR_REF_RE.search("until 2027-01-31")


# ------------------------------------------------------------------ overrides: reason, approver, expiry
def _overrides(root, data):
    dump_yaml({"overrides": data}, root / ".ekit/policy.overrides.yaml")
    return gates.load_overrides(SimpleNamespace(root=root))


def test_override_needs_reason_approver_and_future_expiry(tmp_path):
    (tmp_path / ".ekit").mkdir()
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    valid, notes = _overrides(tmp_path, {
        "GREEN-SCA": {"severity": "warn", "reason": "CVE fix pending", "approved_by": "Security Architect", "expires": future},
        "GREEN-COVERAGE": {"severity": "warn", "approved_by": "Tech Lead", "expires": future},           # no reason
        "BASE-LINT": {"enabled": False, "reason": "lint debt, ADR-0004", "expires": future},           # no approver
        "GREEN-UNIT": {"enabled": False, "reason": "flaky", "approved_by": "TL"},                      # no expiry
        "GREEN-LINT": {"enabled": False, "reason": "x", "approved_by": "TL", "expires": past},          # expired
    })
    assert set(valid) == {"GREEN-SCA"}
    text = " | ".join(notes)
    assert "GREEN-COVERAGE" in text and "`reason`" in text
    assert "BASE-LINT" in text and "`approved_by`" in text
    assert "GREEN-UNIT" in text and "`expires`" in text
    assert "GREEN-LINT expired" in text


# ------------------------------------------------------------------ blocking answers name who decided
def _register(prd, blocking=True, answered_by=None, status="open"):
    prd.mkdir(parents=True, exist_ok=True)
    q = {"id": "OQ-001", "question": "Re-apply window?", "blocking": blocking, "owner": "Product Manager",
         "status": status, "answer": "30 days" if status == "answered" else None, "answered_by": answered_by}
    dump_yaml({"questions": [q]}, prd / "open-questions.yaml")


def test_import_refuses_a_blocking_answer_without_answered_by(tmp_path):
    prd = tmp_path / "docs/requirements/loan"
    _register(prd)
    csv_file = tmp_path / "answers.csv"
    csv_file.write_text("id,answer,answered_by\nOQ-001,30 days,\n", encoding="utf-8")
    before = (prd / "open-questions.yaml").read_text()
    with pytest.raises(EkitError, match="answered_by"):
        questions.import_csv(prd, csv_file)
    assert (prd / "open-questions.yaml").read_text() == before                # nothing partially applied
    csv_file.write_text("id,answer,answered_by\nOQ-001,30 days,Head of Lending\n", encoding="utf-8")
    assert questions.import_csv(prd, csv_file) == ["OQ-001"]


def test_ready_gate_fails_a_blocking_answer_without_answered_by(tmp_path):
    prd = tmp_path / "docs/requirements/loan"
    _register(prd, status="answered")
    ctx = checks.GateContext(project=SimpleNamespace(root=tmp_path, rel=str))
    w = {"file": "docs/requirements/loan/open-questions.yaml"}
    assert [f.level for f in checks.no_open_blocking(ctx, w)] == ["error"]
    assert [f.level for f in checks.questions_valid(ctx, w)] == ["error"]
    _register(prd, status="answered", answered_by="Head of Lending")
    assert checks.no_open_blocking(ctx, w) == [] and checks.questions_valid(ctx, w) == []
    _register(prd, blocking=False, status="answered")                       # non-blocking: still only a warning
    assert [f.level for f in checks.questions_valid(ctx, w)] == ["warn"]


# ------------------------------------------------------------------ the bundled kit requires this CLI
def test_bundled_kit_requires_the_fixed_cli(tmp_path):
    root, lock = _pinned_project(tmp_path)
    kit = yaml.safe_load((root / ".ekit/kit/kit.yaml").read_text())
    assert kit["requires"]["ekit"] == ">=0.2.3,<0.3" and lock["kit"]["version"] == "0.2.3"
