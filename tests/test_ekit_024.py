"""ekit 0.2.4: a scenario that errors on broken test glue (RED-CLEAN-FAILURE rejects it) must
leave the ledger alone.

Found live: a real `ekit fix-red` run got rejected by RED-CLEAN-FAILURE (an AttributeError, not a
clean AssertionError) but still recorded a new red ledger entry and re-froze the feature on that
invalid state anyway — because RED-RUN's own findings were clean (pytest-bdd reports an error and
a real assertion failure identically as "failed"), and the write happened before RED-CLEAN-FAILURE,
a later check in the same gate, had a chance to reject the run. That poisoned the ledger's "last
red" reference for any later `ekit fix-red` / `ekit gate red` on the same feature.

Fix: `bdd.run` (checks.py) only *queues* the write (`ctx.pending_records`); `run_gate` (gates.py)
flushes it via `checks.flush_pending_records` once the whole gate's result is known, and only on
a pass.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import yaml

from ekit import checks, gates, kitsource
from ekit.project import Project, dump_yaml


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


FEATURE_TEXT = """@SCN-001-01
Feature: Demo
  Scenario: s
    Given a thing
    Then it works
"""

MODULE = '''from pathlib import Path
from pytest_bdd import scenarios, given, then

scenarios(str(Path(__file__).parent.parent.parent / "specs" / "001-demo" / "features" / "a.feature"))


@given("a thing")
def a_thing(scenario_state):
    scenario_state["ready"] = True


@then("it works")
def it_works(scenario_state):
    assert scenario_state["ready"]
'''


def _project(tmp_path) -> Path:
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": "fastapi-jinja"}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "src/app/web").mkdir(parents=True)
    (root / "src/app/__init__.py").write_text("", encoding="utf-8")
    (root / "docs/requirements/loan").mkdir(parents=True)
    (root / "specs/001-demo/features").mkdir(parents=True)
    (root / "specs/001-demo/features/a.feature").write_text(FEATURE_TEXT, encoding="utf-8")
    (root / "tests/acceptance").mkdir(parents=True)
    (root / "tests/acceptance/test_a.py").write_text(MODULE, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _fake_run(status: str, error_message: str):
    def fake(prof, name, **_):
        report = prof.root / prof.bdd["report"]
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps([{"name": "Demo", "tags": [], "elements": [
            {"type": "scenario", "tags": [{"name": "SCN-001-01"}],
             "steps": [{"result": {"status": status, "error_message": error_message}}]}
        ]}]), encoding="utf-8")
        return SimpleNamespace(returncode=1, output=status, cwd=prof.root)
    return fake


def test_a_run_rejected_by_clean_failure_never_reaches_the_ledger(tmp_path, monkeypatch):
    root = _project(tmp_path)
    project = Project.load(root)
    monkeypatch.setattr(checks, "run_profile_command",
                         _fake_run("failed", "tests/x.py:10: in f\n    y = d['missing']\nE   KeyError: 'missing'\n"))

    res, notes = gates.run_gate(project, "red", feature="001-demo")

    assert not res.passed
    red_run = next(c for c in res.checks if c.type == "bdd.run")
    assert red_run.status == "pass"            # RED-RUN itself sees nothing wrong...
    clean_failure = next(c for c in res.checks if c.id == "RED-CLEAN-FAILURE")
    assert clean_failure.status == "fail"      # ...but RED-CLEAN-FAILURE rejects the run
    assert not (root / ".ekit/ledger/001-demo.yaml").exists()     # so nothing was ever recorded
    assert not (root / ".ekit/freeze.yaml").is_file()              # and the feature was never (re-)frozen


def test_a_genuinely_clean_red_still_records_and_freezes(tmp_path, monkeypatch):
    root = _project(tmp_path)
    project = Project.load(root)
    monkeypatch.setattr(checks, "run_profile_command",
                         _fake_run("failed", "tests/x.py:5: in f\n    assert False\nE   AssertionError\n"))

    res, notes = gates.run_gate(project, "red", feature="001-demo")

    assert res.passed, res
    ledger = yaml.safe_load((root / ".ekit/ledger/001-demo.yaml").read_text())
    assert ledger["entries"][-1]["phase"] == "red"
    state = yaml.safe_load((root / ".ekit/freeze.yaml").read_text())
    assert "001-demo" in state["frozen"]
