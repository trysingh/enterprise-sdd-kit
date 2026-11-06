"""ekit 0.7.0: happy-path.md, design.yaml, the DESIGN-* checks, `ekit design`, DESIGN-PORTS-IMPLEMENTED."""
from __future__ import annotations

import copy
import json

import pytest
import yaml

from ekit import design, freeze, gates, logbook
from ekit.cli import main as ekit_main
from ekit.project import EkitError, Project
from h070 import (ARCH, HAPPY, PORTS_PY, design_data, errors, make_project, run, write_design, write_ports)


def _mut(fn):
    d = copy.deepcopy(design_data())
    fn(d)
    return d


@pytest.fixture
def proj(tmp_path):
    p = make_project(tmp_path)
    write_design(p.root)
    return Project.load(p.root)


# ---------------------------------------------------------------- happy-path.md (INTAKE-HAPPY-PATH)
def test_happy_path_parse():
    hp = design.parse_happy_path(HAPPY.replace("- **Key**: yes\n\n### FEAT-02", "- **Key**: no\n\n### FEAT-02", 1))
    assert hp["features"] == {"FEAT-01": {"key": False}, "FEAT-02": {"key": True}}
    assert hp["journeys"] == {"J-01": ["FEAT-01", "FEAT-02"]}


def test_intake_happy_path_pass_and_fail(tmp_path):
    p = make_project(tmp_path)
    f = "docs/requirements/chat/happy-path.md"
    assert errors(p, "happy_path.valid", file=f) == []
    (p.root / f).write_text(HAPPY.replace("- **Features**: FEAT-01, FEAT-02", "- **Features**: FEAT-01"), encoding="utf-8")
    assert any("FEAT-02 appears in no journey" in e for e in errors(p, "happy_path.valid", file=f))
    (p.root / f).write_text(HAPPY.replace("FEAT-01, FEAT-02", "FEAT-01, FEAT-09"), encoding="utf-8")
    assert any("unknown feature FEAT-09" in e for e in errors(p, "happy_path.valid", file=f))
    # not key => no journey needed
    (p.root / f).write_text(HAPPY.replace("- **Features**: FEAT-01, FEAT-02", "- **Features**: FEAT-01")
                            .replace("### FEAT-02: Unread overview\n\n- **Key**: yes", "### FEAT-02: Unread overview\n\n- **Key**: no"), encoding="utf-8")
    assert errors(p, "happy_path.valid", file=f) == []
    (p.root / f).unlink()
    assert any("missing" in e for e in errors(p, "happy_path.valid", file=f))          # happy-path lane
    classic = make_project(tmp_path / "c", lane="classic")
    (classic.root / f).unlink()
    assert errors(classic, "happy_path.valid", file=f) == []                            # classic: unchanged


def test_intake_gate_includes_the_check_and_is_unchanged_for_classic(tmp_path):
    p = make_project(tmp_path / "a", lane="classic")
    (p.root / "docs/requirements/chat/happy-path.md").unlink()
    res, _ = gates.run_gate(p, "intake", prd="docs/requirements/chat")
    hp = next(c for c in res.checks if c.id == "INTAKE-HAPPY-PATH")
    assert hp.status == "pass"


# ---------------------------------------------------------------- the design gate
def test_a_complete_design_passes_everything_but_approval(proj):
    res, _ = gates.run_gate(proj, "design")
    bad = {c.id: [f.message for f in c.findings if f.level == "error"] for c in res.checks if c.status == "fail"}
    assert list(bad) == ["DESIGN-APPROVED"], bad
    assert [c.id for c in res.checks] == ["DESIGN-FILES", "DESIGN-SECTIONS", "DESIGN-SCHEMA", "DESIGN-PORTS", "DESIGN-SEAMS",
                                         "DESIGN-FEATURES", "DESIGN-BRS-LISTED", "DESIGN-DECISIONS", "DESIGN-JOURNEYS",
                                         "DESIGN-APPROVED"]


def test_files_and_sections(tmp_path):
    p = make_project(tmp_path)
    res, _ = gates.run_gate(p, "design")
    assert next(c for c in res.checks if c.id == "DESIGN-FILES").status == "fail"
    write_design(p.root)
    (p.root / "docs/design/architecture.md").write_text(ARCH.replace("## 4. Interface", "## 4. Something else"), encoding="utf-8")
    assert any("'interface'" in e for e in errors(p, "design.sections"))
    (p.root / "docs/design/architecture.md").write_text(ARCH + "\n[TBD: later]\n", encoding="utf-8")
    assert any("placeholder" in e for e in errors(p, "design.sections"))


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.update(topology="TODO"), "topology"),
    (lambda d: d.pop("slices"), "`slices`"),
    (lambda d: d["features"]["FEAT-01"].update(operations=["Send-Message"]), "snake_case"),
    (lambda d: d["features"]["FEAT-01"].update(pages=["/chat/{peer}"]), "must look like"),
    (lambda d: d["features"].update({"feat1": {"operations": ["x_y"]}}), "FEAT-nn"),
])
def test_schema_errors(proj, mutate, needle):
    write_design(proj.root, _mut(mutate))
    assert any(needle in e for e in errors(proj, "design.schema")), errors(proj, "design.schema")


def test_ports_need_a_dependency_and_a_method(proj):
    assert errors(proj, "design.ports") == []
    write_design(proj.root, _mut(lambda d: d["ports"][0].update(methods=[])))
    assert any("at least one declared method" in e for e in errors(proj, "design.ports"))
    write_design(proj.root, _mut(lambda d: d["ports"][0].pop("dependency")))
    assert any("`dependency`" in e for e in errors(proj, "design.ports"))
    write_design(proj.root, _mut(lambda d: d["ports"].append(dict(d["ports"][0]))))
    assert any("declared twice" in e for e in errors(proj, "design.ports"))


def test_all_five_seams_are_required(proj):
    assert errors(proj, "design.seams") == []
    write_design(proj.root, _mut(lambda d: d["seams"].pop("audit")))
    assert any("seam `audit`" in e for e in errors(proj, "design.seams"))


def test_features_reachable_and_in_exactly_one_slice(proj):
    assert errors(proj, "design.features") == []
    write_design(proj.root, _mut(lambda d: d["features"]["FEAT-02"].update(operations=[])))
    assert any("FEAT-02 has no operation or page" in e for e in errors(proj, "design.features"))
    write_design(proj.root, _mut(lambda d: d["slices"].append({"id": "S1", "features": ["FEAT-01"], "journeys": []})))
    assert any("FEAT-01 is in 2 slices" in e for e in errors(proj, "design.features"))
    write_design(proj.root, _mut(lambda d: d["slices"][0].update(features=["FEAT-01"])))
    assert any("FEAT-02 is in no slice" in e for e in errors(proj, "design.features"))
    # a non-key feature needs neither
    write_design(proj.root, _mut(lambda d: (d["slices"][0].update(features=["FEAT-01"]),
                                            d["features"]["FEAT-02"].update(key=False, operations=[]))))
    assert errors(proj, "design.features") == []


def test_every_br_of_an_in_scope_feature_is_listed(proj):
    assert errors(proj, "design.brs_listed") == []
    write_design(proj.root, _mut(lambda d: d["features"]["FEAT-01"].update(brs=["BR-001"])))
    assert any("FEAT-01 does not list BR-002" in e for e in errors(proj, "design.brs_listed"))
    write_design(proj.root, _mut(lambda d: d["features"].pop("FEAT-02")))
    assert any("FEAT-02 is in the PRD but not under `features`" in e for e in errors(proj, "design.brs_listed"))


def test_decisions_need_status_and_an_existing_adr_when_accepted(proj):
    assert errors(proj, "design.decisions") == []
    write_design(proj.root, _mut(lambda d: d["decisions"][0].update(adr=None)))
    assert any("must cite an ADR" in e for e in errors(proj, "design.decisions"))
    write_design(proj.root, _mut(lambda d: d["decisions"][0].update(adr="ADR-0009")))
    assert any("does not exist" in e for e in errors(proj, "design.decisions"))
    write_design(proj.root, _mut(lambda d: d["decisions"][0].update(status="maybe")))
    assert any("needs a status" in e for e in errors(proj, "design.decisions"))
    write_design(proj.root, _mut(lambda d: d["decisions"][0].update(status="proposed", adr=None)))
    assert errors(proj, "design.decisions") == []


def test_slice_journeys_must_exist_in_happy_path(proj):
    assert errors(proj, "design.journeys_declared") == []
    write_design(proj.root, _mut(lambda d: d["slices"][0].update(journeys=["J-01", "J-07"])))
    assert any("J-07" in e for e in errors(proj, "design.journeys_declared"))


# ---------------------------------------------------------------- approval (a person)
def test_approval_is_required_and_goes_stale_on_edit(proj):
    assert any("not approved" in e for e in errors(proj, "design.approved"))
    notes = design.approve(proj, "Priya")
    assert "approved by Priya" in notes[0] and (proj.root / design.APPROVAL).is_file()
    assert errors(proj, "design.approved") == []
    (proj.root / "docs/design/design.yaml").write_text((proj.root / "docs/design/design.yaml").read_text() + "\n# edit\n", encoding="utf-8")
    assert any("changed after it was approved by Priya" in e for e in errors(proj, "design.approved"))


def test_approve_needs_a_name_and_a_valid_design_and_is_logged(proj):
    with pytest.raises(EkitError, match="--by is required"):
        design.approve(proj, "  ")
    write_design(proj.root, _mut(lambda d: d["features"]["FEAT-02"].update(operations=[])))
    with pytest.raises(EkitError, match="DESIGN-FEATURES"):
        design.approve(proj, "Priya")
    assert not (proj.root / design.APPROVAL).exists()
    write_design(proj.root)
    design.approve(proj, "Priya")
    ev = [e for e in logbook.iter_events(proj.root) if e.get("kind") == "state.design.approve"]
    assert ev and ev[-1]["by"] == "Priya"


def test_design_approve_is_denied_to_the_agent_shell():
    assert "ekit design approve*" in freeze.ALWAYS_BASH


def test_cli_design_status_init_and_approve(proj, monkeypatch, capsys):
    monkeypatch.chdir(proj.root)
    assert ekit_main(["design", "status"]) == 0
    out = capsys.readouterr().out
    assert "lane: happy-path" in out and "approval: none" in out
    assert ekit_main(["design", "approve", "--by", "Priya"]) == 0
    assert ekit_main(["design", "status"]) == 0 and "approval: Priya" in capsys.readouterr().out
    assert ekit_main(["design", "approve"]) == 2                                      # --by missing
    assert "--by is required" in capsys.readouterr().err
    assert ekit_main(["design", "init"]) == 2 and "already exists" in capsys.readouterr().err


# ---------------------------------------------------------------- design init
def test_init_copies_the_templates_and_the_draft_fails_the_gate(tmp_path, monkeypatch, capsys):
    p = make_project(tmp_path)
    monkeypatch.chdir(p.root)
    assert ekit_main(["design", "init"]) == 0
    assert "fill them" in capsys.readouterr().out
    assert (p.root / "docs/design/architecture.md").read_text().startswith("# Architecture")
    assert ekit_main(["gate", "design", "--format", "json"]) == 1
    capsys.readouterr()
    assert any("TODO" in e or "topology" in e for e in errors(p, "design.schema"))
    assert ekit_main(["design", "init", "--force"]) == 0


def test_init_from_code_drafts_ports_features_and_unassigned_operations(tmp_path, monkeypatch, capsys):
    p = make_project(tmp_path)
    write_ports(p.root)
    (p.root / "reports").mkdir()
    (p.root / "reports/openapi.json").write_text(json.dumps({"paths": {"/a": {"get": {"operationId": "list_unread"}}}}), encoding="utf-8")
    monkeypatch.chdir(p.root)
    assert ekit_main(["design", "init", "--from-code"]) == 0
    data = yaml.safe_load((p.root / "docs/design/design.yaml").read_text())
    assert data["ports"] == [{"name": "MessageStore", "methods": ["append", "history"], "dependency": "TODO"}]
    assert data["features"]["FEAT-01"]["brs"] == ["BR-001", "BR-002"] and data["features"]["FEAT-02"]["brs"] == ["BR-003"]
    assert data["unassigned_operations"] == ["list_unread"] and data["topology"] == "TODO"
    assert errors(p, "design.schema")                                                   # a person must complete it


def test_template_command_finds_the_yaml_template(tmp_path, monkeypatch, capsys):
    p = make_project(tmp_path)
    monkeypatch.chdir(p.root)
    assert ekit_main(["template", "esdlc-design-template"]) == 0
    assert "topology:" in capsys.readouterr().out


# ---------------------------------------------------------------- DESIGN-PORTS-IMPLEMENTED (AST scan)
def test_ports_implemented_pass(proj):
    write_ports(proj.root)
    assert run(proj, "design.ports_implemented") == []


@pytest.mark.parametrize("source,needle,level", [
    (PORTS_PY.replace("class MessageStore(Protocol)", "class MessageStore"), "no `class MessageStore(Protocol)`", "error"),
    (PORTS_PY.replace("    def history(self, peer: str) -> list[str]: ...\n", ""), "lacks declared method(s): history", "error"),
    (PORTS_PY.replace("def get_message_store", "def make_store"), "dependency function `get_message_store`", "error"),
    (PORTS_PY.replace("class SqlMessageStore", "class SqlMessageStoreX").replace("    def history(self, peer: str) -> list[str]:\n        return []\n\n\nclass InMemory", "\n\nclass InMemory", 1),
     "no adapter class", "error"),
    (PORTS_PY.replace("InMemoryMessageStore", "Other"), "no in-memory fake", "warn"),
])
def test_ports_implemented_failures(proj, source, needle, level):
    write_ports(proj.root, source)
    found = [(lv, m) for lv, m in run(proj, "design.ports_implemented") if needle in m]
    assert found and found[0][0] == level, run(proj, "design.ports_implemented")


def test_ports_implemented_without_a_design_is_informational(tmp_path):
    p = make_project(tmp_path)
    assert run(p, "design.ports_implemented")[0][0] == "info"
