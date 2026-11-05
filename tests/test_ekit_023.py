"""ekit 0.2.3: `ekit fix-red` — unfreeze, temporarily revert a feature's production source to its
last-red state (not `git stash`, which has nothing to grab once that source is already committed —
the common case by the time a frozen-test bug is found), run `ekit gate red`, restore the source
either way. It never commits.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ekit import checks, fixred, freeze, kitsource
from ekit.project import EkitError, dump_yaml


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
    (root / "src/app/stub.py").write_text("VALUE = 'red'\n", encoding="utf-8")
    (root / "docs/requirements/loan").mkdir(parents=True)
    (root / "specs/001-demo/features").mkdir(parents=True)
    (root / "specs/001-demo/features/a.feature").write_text(FEATURE_TEXT, encoding="utf-8")
    (root / "tests/acceptance").mkdir(parents=True)
    (root / "tests/acceptance/test_a.py").write_text(MODULE, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "red: 001-demo")
    red_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()

    fp = {"specs/001-demo/features/a.feature": checks._sha(root / "specs/001-demo/features/a.feature"),
          "tests/acceptance/test_a.py": checks._sha(root / "tests/acceptance/test_a.py")}
    ledger = root / ".ekit/ledger/001-demo.yaml"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    dump_yaml({"feature": "001-demo", "entries": [
        {"phase": "red", "at": "2026-01-01T00:00:00+00:00", "git_head": red_head,
         "scenarios": {"SCN-001-01": "failed"}, "fingerprints": fp}]}, ledger)
    freeze.freeze_feature(root, "001-demo", fp)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "chore: freeze")

    # "implementation": production source changes, committed (the realistic case — not a dirty tree)
    (root / "src/app/stub.py").write_text("VALUE = 'implemented'\n", encoding="utf-8")
    (root / "src/app/new_module.py").write_text("ADDED = True\n", encoding="utf-8")   # a file that didn't exist at red
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "feat: implement 001-demo")
    return root


def _fake_run(seen: dict, status: str, error_message: str | None = None):
    def fake(prof, name, **_):
        seen["stub_content_during_red"] = (prof.root / "src/app/stub.py").read_text(encoding="utf-8")
        seen["new_module_present_during_red"] = (prof.root / "src/app/new_module.py").is_file()
        report = prof.root / prof.bdd["report"]
        report.parent.mkdir(parents=True, exist_ok=True)
        result = {"status": status}
        if error_message:
            result["error_message"] = error_message
        report.write_text(json.dumps([{"name": "Demo", "tags": [], "elements": [
            {"type": "scenario", "tags": [{"name": "SCN-001-01"}], "steps": [{"result": result}]}
        ]}]), encoding="utf-8")
        return SimpleNamespace(returncode=0 if status == "passed" else 1, output=status, cwd=prof.root)
    return fake


def test_fix_red_reverts_source_during_the_run_and_restores_it_after(tmp_path, monkeypatch):
    root = _project(tmp_path)
    from ekit.project import Project
    project = Project.load(root)
    seen: dict = {}
    monkeypatch.setattr(checks, "run_profile_command", _fake_run(seen, "failed", "tests/x.py:1: in f\n    assert False\nE   AssertionError\n"))

    clean, report = fixred.fix_red(project, "001-demo", "step glue fix")

    assert clean, report
    assert seen["stub_content_during_red"] == "VALUE = 'red'\n"           # reverted while the gate ran
    assert seen["new_module_present_during_red"] is False                  # file added since red was moved aside
    assert (root / "src/app/stub.py").read_text(encoding="utf-8") == "VALUE = 'implemented'\n"   # restored after
    assert (root / "src/app/new_module.py").is_file()                                            # moved back


def test_fix_red_restores_source_even_when_red_is_still_not_clean(tmp_path, monkeypatch):
    root = _project(tmp_path)
    from ekit.project import Project
    project = Project.load(root)
    seen: dict = {}
    monkeypatch.setattr(checks, "run_profile_command", _fake_run(seen, "failed", "tests/x.py:10: in f\n    y = d['missing']\nE   KeyError: 'missing'\n"))

    clean, report = fixred.fix_red(project, "001-demo", "still investigating")

    assert not clean
    assert "KeyError" in report
    assert (root / "src/app/stub.py").read_text(encoding="utf-8") == "VALUE = 'implemented'\n"   # restored anyway
    assert (root / "src/app/new_module.py").is_file()


def test_fix_red_refuses_a_dirty_source_tree(tmp_path, monkeypatch):
    root = _project(tmp_path)
    from ekit.project import Project
    (root / "src/app/stub.py").write_text("VALUE = 'uncommitted'\n", encoding="utf-8")   # dirty, not committed
    project = Project.load(root)
    with pytest.raises(EkitError, match="uncommitted changes"):
        fixred.fix_red(project, "001-demo", "reason")


def test_fix_red_refuses_an_unfrozen_feature(tmp_path):
    root = _project(tmp_path)
    from ekit.project import Project
    freeze.unfreeze_feature(root, "001-demo", "already unfrozen")
    project = Project.load(root)
    with pytest.raises(EkitError, match="not frozen"):
        fixred.fix_red(project, "001-demo", "reason")


def test_fix_red_is_denied_to_the_agents_shell_tool():
    assert "ekit fix-red*" in freeze.ALWAYS_BASH


def test_source_dirs_and_patterns_for_fastapi_jinja(tmp_path):
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": "fastapi-jinja"}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    from ekit.project import Project
    project = Project.load(root)
    dirs = freeze.source_dirs(project)
    assert "src/app" in dirs
    assert all(p.endswith("/**") for p in freeze.source_patterns(project))


def test_bundled_kit_requires_the_023_cli():
    from ekit.project import Kit, bundled_kit_dir
    assert yaml.safe_load((bundled_kit_dir() / "kit.yaml").read_text())["requires"]["ekit"] == ">=0.2.5,<0.3"
