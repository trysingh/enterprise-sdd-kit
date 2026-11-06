"""ekit 0.5.0: change requests taken from the prompt (bug fixes, enhancements, features) for brownfield work.

Covers: `ekit change new|list|show|candidates|retire`, CR-id resolution, the gate checks
INTAKE-CHANGE-VALID / READY-CHANGE, RED-BUG-REPRODUCED, RED-/GREEN-CHANGE-SUPERSEDED, ledger rebase after a
retire (GREEN-TESTS-UNCHANGED, REDREC-COMMITTED, freeze), and golden package scoping for a change."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_ekit_030 import FEATURE, _bare, _golden_project

from ekit import changechecks, changes, checks, cli, freeze, golden
from ekit.project import EkitError, Kit, Project, bundled_kit_dir, dump_yaml, load_yaml


@pytest.fixture(autouse=True)
def _no_post_install(monkeypatch):
    monkeypatch.setenv(golden.SKIP_POST_INSTALL_ENV, "1")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _commit(root: Path, msg: str = "c") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg, "--allow-empty")


TWO_SCN = """Feature: Chat
  Background:
    Given the application is running

  @SCN-003-01 @AC-001
  Scenario: unread badge shows
    When I GET "/api/v1/chat"
    Then the response status is 200

  @SCN-003-02 @AC-002
  Scenario: badge stays after reading
    When I GET "/api/v1/chat/1"
    Then the response status is 200
"""


def _delivered(root: Path, name: str = "003-chat", text: str = TWO_SCN) -> Path:
    """A delivered (red-recorded, frozen) feature folder with a ledger fingerprinting its feature file."""
    d = root / "specs" / name / "features"
    d.mkdir(parents=True)
    f = d / "chat.feature"
    f.write_text(text, encoding="utf-8")
    (root / "specs" / name / "spec.md").write_text("# Chat\nUnread badge and conversation list.\n", encoding="utf-8")
    rel = f"specs/{name}/features/chat.feature"
    fp = {rel: checks._sha(f)}
    led = root / ".ekit/ledger" / f"{name}.yaml"
    led.parent.mkdir(parents=True, exist_ok=True)
    dump_yaml({"feature": name, "entries": [{"phase": "red", "scenarios": {"SCN-003-01": "failed", "SCN-003-02": "failed"},
                                             "fingerprints": fp}]}, led)
    freeze.freeze_feature(root, name, fp)
    return f


def _cr_feature(root: Path, cr_dir: Path, name: str = "008-cr0001-badge") -> Path:
    fd = root / "specs" / name
    (fd / "features").mkdir(parents=True)
    (fd / "features" / "badge.feature").write_text(FEATURE.replace("001", "008"), encoding="utf-8")
    dump_yaml({"apiVersion": "ekit/v1", "kind": "FeatureTrace", "feature": name, "prd": cr_dir.as_posix(), "acceptance_criteria": ["AC-001"]},
              fd / "trace.yaml")
    return fd


def _report(root: Path, sid: str, message: str) -> None:
    report = root / "reports/cucumber-backend.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    steps = [{"keyword": "When ", "name": "I GET", "result": {"status": "passed"}},
             {"keyword": "Then ", "name": "the response status is 200", "result": {"status": "failed", "error_message": message}}]
    report.write_text(json.dumps([{"name": "x", "tags": [], "elements": [
        {"type": "scenario", "tags": [{"name": sid}], "steps": steps}]}]), encoding="utf-8")


def _fill_bug(cr: Path, observed="badge stays at 3", expected="badge shows 0") -> None:
    data = changes.load(cr)
    data["bug"] = {"observed": observed, "expected": expected, "reproduction": "open chat 1, go back"}
    dump_yaml(data, cr / "change.yaml")


# ===================================================================== new / find
def test_new_numbers_keeps_request_verbatim_and_validates_affects(tmp_path):
    root = _bare(tmp_path)
    _delivered(root)
    req = 'After I open a chat the unread badge still says "3".\nExpected: 0.'
    d = changes.new(root, type_="bug", title="Unread badge does not clear", text=req, ticket="JIRA-9", affects=["003"])
    assert d.name == "cr-0001-unread-badge-does-not-clear"
    assert changes.request_text(d) == req
    data = changes.load(d)
    assert data["id"] == "CR-0001" and data["affects"]["features"] == ["003-chat"] and "bug" in data
    d2 = changes.new(root, type_="feature", title="Mark all read")
    assert d2.name.startswith("cr-0002-") and changes.PLACEHOLDER in (d2 / "request.md").read_text(encoding="utf-8")
    with pytest.raises(EkitError, match="not one feature folder"):
        changes.new(root, type_="bug", title="x", text="y", affects=["999"])
    with pytest.raises(EkitError, match="--type"):
        changes.new(root, type_="chore", title="x", text="y")
    for ref in ("CR-0001", "cr-1", "1", "0001", d.name):
        assert changes.find(root, ref) == d.resolve()
    assert Project.load(root).resolve_prd("CR-0002") == d2.resolve()


def test_candidates_rank_existing_features_by_overlap(tmp_path):
    root = _bare(tmp_path)
    _delivered(root)
    (root / "specs/004-login/features").mkdir(parents=True)
    (root / "specs/004-login/spec.md").write_text("Sign in with password.", encoding="utf-8")
    got = changes.candidates(root, "the unread badge on the chat list does not clear")
    assert got[0][0] == "003-chat" and "badge" in got[0][2]
    assert all(name != "004-login" for name, *_ in got)


# ===================================================================== change.valid
def test_change_valid_is_noop_for_an_ordinary_prd(tmp_path):
    root = _bare(tmp_path)
    (root / "docs/requirements/loan").mkdir(parents=True)
    ctx = checks.GateContext(project=Project.load(root))
    assert changechecks.change_valid(ctx, {"dir": "docs/requirements/loan"}) == []


def test_change_valid_requires_request_and_bug_facts_and_real_supersedes(tmp_path):
    root = _bare(tmp_path)
    _delivered(root)
    cr = changes.new(root, type_="bug", title="Badge", affects=["003-chat"])
    rel = cr.relative_to(root).as_posix()
    ctx = checks.GateContext(project=Project.load(root))
    msgs = " | ".join(f.message for f in changechecks.change_valid(ctx, {"dir": rel}))
    assert "request.md has no request text" in msgs and "bug.observed is empty" in msgs
    (cr / "request.md").write_text((cr / "request.md").read_text(encoding="utf-8").replace(changes.PLACEHOLDER, "badge stuck"),
                                   encoding="utf-8")
    _fill_bug(cr, observed="[TBD: OQ-001]")
    data = changes.load(cr)
    data["supersedes"] = ["SCN-003-02", "SCN-009-01"]
    dump_yaml(data, cr / "change.yaml")
    out = changechecks.change_valid(ctx, {"dir": rel})
    assert [f.message for f in out if f.level == "error"] == ["change.yaml supersedes SCN-009-01, which no feature in specs/ defines"]
    ready = [f.message for f in changechecks.change_valid(ctx, {"dir": rel, "ready": True}) if f.level == "error"]
    assert any("bug.observed is still [TBD: OQ-001]" in m for m in ready)


# ===================================================================== bug_reproduced
def _bug_setup(tmp_path):
    root = _bare(tmp_path)
    (root / "src/app").mkdir(parents=True)
    (root / "src/app/chat.py").write_text("def badge(): return 3\n", encoding="utf-8")
    _delivered(root)
    cr = changes.new(root, type_="bug", title="Badge", text="badge stuck", affects=["003-chat"])
    _fill_bug(cr)
    fd = _cr_feature(root, cr.relative_to(root))
    _commit(root)
    project = Project.load(root)
    return root, project, checks.GateContext(project=project, feature_dir=fd)


W = {"dir": "specs/008-cr0001-badge/features"}


def test_bug_red_passes_on_an_assertion_against_committed_code(tmp_path):
    root, _project, ctx = _bug_setup(tmp_path)
    _report(root, "SCN-008-01", "E   AssertionError: expected 0, got 3")
    assert changechecks.bug_reproduced(ctx, W) == []


def test_bug_red_rejects_a_stub_and_edited_production_code(tmp_path):
    root, _project, ctx = _bug_setup(tmp_path)
    _report(root, "SCN-008-01", "E   AssertionError: expected 200, got 501 application/problem+json")
    out = changechecks.bug_reproduced(ctx, W)
    assert len(out) == 1 and "failed on a stub" in out[0].message
    (root / "src/app/chat.py").write_text("def badge(): raise NotImplementedError\n", encoding="utf-8")
    _report(root, "SCN-008-01", "E   AssertionError: expected 0, got 3")
    out = changechecks.bug_reproduced(ctx, W)
    assert len(out) == 1 and "production source must be untouched at red" in out[0].message and "src/app/chat.py" in out[0].message


def test_bug_checks_are_noop_for_ordinary_features_and_feature_crs(tmp_path):
    root, project, ctx = _bug_setup(tmp_path)
    data = changes.load(changes.find(root, "CR-0001"))
    data["type"] = "feature"
    dump_yaml(data, changes.find(root, "CR-0001") / "change.yaml")
    _report(root, "SCN-008-01", "E   AssertionError: expected 200, got 501")
    assert changechecks.bug_reproduced(ctx, W) == []
    plain = checks.GateContext(project=project, feature_dir=root / "specs/003-chat")
    assert changechecks.bug_reproduced(plain, {"dir": "specs/003-chat/features"}) == []


# ===================================================================== supersede + retire
def _supersede_setup(tmp_path):
    root = _bare(tmp_path)
    f = _delivered(root)
    cr = changes.new(root, type_="enhancement", title="Badge clears on open", text="badge must clear", affects=["003-chat"])
    data = changes.load(cr)
    data["supersedes"] = ["SCN-003-02"]
    dump_yaml(data, cr / "change.yaml")
    fd = _cr_feature(root, cr.relative_to(root))
    _commit(root)
    return root, f, fd


def test_green_fails_until_the_superseded_scenario_is_retired_by_a_person(tmp_path):
    root, f, fd = _supersede_setup(tmp_path)
    project = Project.load(root)
    ctx = checks.GateContext(project=project, feature_dir=fd)
    out = changechecks.supersedes_retired(ctx, {})
    assert len(out) == 1 and "ekit change retire 003-chat SCN-003-02 --by CR-0001" in out[0].message

    old_fp = load_yaml(root / ".ekit/ledger/003-chat.yaml")["entries"][0]["fingerprints"]
    f.write_text(TWO_SCN.split("  @SCN-003-02")[0].rstrip() + "\n", encoding="utf-8")   # the person removes it
    msgs = changes.retire(project, "003-chat", ["SCN-003-02"], change="CR-0001", reason="CR-0001 changes it")
    assert "retired SCN-003-02 for CR-0001" in msgs[0]
    entries = load_yaml(root / ".ekit/ledger/003-chat.yaml")["entries"]
    assert entries[-1]["phase"] == "rebase" and entries[-1]["retired"] == ["SCN-003-02"]
    assert entries[-1]["fingerprints"] != old_fp
    assert changechecks.supersedes_retired(ctx, {}) == []
    assert changes.retired_scenarios(root) == {"SCN-003-02": "CR-0001"}

    # the delivered feature's own gates judge against the rebased fingerprints
    old = checks.GateContext(project=project, feature_dir=root / "specs/003-chat")
    assert [x for x in checks.tests_unchanged(old, {"dir": "specs/003-chat/features"}) if x.level == "error"] == []
    _commit(root, "retire")
    assert [x for x in checks.red_committed(old, {}) if x.level == "error"] == []
    assert "specs/003-chat/features/*" in freeze.desired_patterns(freeze.load_state(root))
    # and the change's intake still validates (the retired id is known)
    vctx = checks.GateContext(project=project)
    assert [x for x in changechecks.change_valid(vctx, {"dir": changes.find(root, "CR-0001").relative_to(root).as_posix()})
            if x.level == "error"] == []


def test_retire_refuses_edits_to_other_scenarios_unnamed_removals_and_unlisted_ids(tmp_path):
    root, f, _fd = _supersede_setup(tmp_path)
    project = Project.load(root)
    f.write_text(TWO_SCN.replace("unread badge shows", "unread badge is shown"), encoding="utf-8")
    with pytest.raises(EkitError, match="SCN-003-01 changed"):
        changes.retire(project, "003-chat", ["SCN-003-02"], change="CR-0001", reason="r")
    f.write_text(TWO_SCN, encoding="utf-8")
    with pytest.raises(EkitError, match="still present"):
        changes.retire(project, "003-chat", ["SCN-003-02"], change="CR-0001", reason="r")
    with pytest.raises(EkitError, match="does not list SCN-003-01"):
        changes.retire(project, "003-chat", ["SCN-003-01"], change="CR-0001", reason="r")
    f.write_text(TWO_SCN.split("  @SCN-003-01")[0].rstrip() + "\n", encoding="utf-8")
    with pytest.raises(EkitError, match="also removed SCN-003-01"):
        changes.retire(project, "003-chat", ["SCN-003-02"], change="CR-0001", reason="r")


def test_retire_is_denied_to_the_agent_shell():
    assert "ekit change retire*" in freeze.ALWAYS_BASH
    assert not any(p.startswith("ekit change new") for p in freeze.ALWAYS_BASH)


# ===================================================================== golden scoping
def test_golden_bug_fix_works_in_the_affected_feature_package(tmp_path):
    project = _golden_project(tmp_path)
    root = project.root
    (root / "specs/003-chat/features").mkdir(parents=True)
    cr = changes.new(root, type_="bug", title="Badge", text="stuck", affects=["003-chat"])
    _cr_feature(root, cr.relative_to(root))
    project = Project.load(root)
    assert golden.feature_packages(project, "008-cr0001-badge") == ["src/app/features/f003_chat"]
    data = changes.load(cr)
    data["type"] = "feature"
    dump_yaml(data, cr / "change.yaml")
    assert golden.feature_packages(project, "008-cr0001-badge") == ["src/app/features/f008_cr0001_badge"]


# ===================================================================== CLI + kit wiring
def test_cli_change_new_list_show(tmp_path, monkeypatch, capsys):
    root = _bare(tmp_path)
    _delivered(root)
    monkeypatch.chdir(root)
    assert cli.main(["change", "new", "--type", "bug", "--title", "Badge stuck", "--text", "badge says 3", "--affects", "003"]) == 0
    assert "CR-0001 docs/requirements/cr-0001-badge-stuck" in capsys.readouterr().out
    assert cli.main(["change", "list"]) == 0
    assert "CR-0001" in capsys.readouterr().out
    assert cli.main(["change", "show", "CR-0001"]) == 0
    assert "RED-BUG-REPRODUCED" in capsys.readouterr().out
    assert cli.main(["change", "candidates", "unread", "badge", "chat"]) == 0
    assert "003-chat" in capsys.readouterr().out


def test_policy_wires_the_change_checks_and_the_command_exists():
    kit = Kit.load(bundled_kit_dir())
    gates = {g["id"]: g for g in kit.policy()["spec"]["gates"]}
    ids = lambda g: [c["id"] for c in gates[g]["checks"]]
    assert "INTAKE-CHANGE-VALID" in ids("intake") and "READY-CHANGE" in ids("ready")
    assert ids("red")[-2:] == ["RED-BUG-REPRODUCED", "RED-CHANGE-SUPERSEDES"]
    assert ids("red").index("RED-BUG-REPRODUCED") > ids("red").index("RED-RUN")
    assert ids("green").index("GREEN-CHANGE-SUPERSEDED") < ids("green").index("GREEN-RUN")
    types = {c["type"] for g in gates.values() for c in g["checks"]}
    assert types <= set(checks.REGISTRY)
    ext = load_yaml(bundled_kit_dir() / "extension/esdlc/extension.yml")
    assert "speckit.esdlc.change" in {c["name"] for c in ext["provides"]["commands"]}
    assert (bundled_kit_dir() / "extension/esdlc/commands/speckit.esdlc.change.md").is_file()
    assert load_yaml(bundled_kit_dir() / "policy/models.policy.yaml")["commands"]["speckit.esdlc.change"] == "standard"
