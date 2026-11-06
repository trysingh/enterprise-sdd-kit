"""ekit 0.7.0: the happy-path lane at `ekit init`, and leaving W0 (the adoption point)."""
from __future__ import annotations

import json
import sys
import textwrap

import pytest
import yaml

from ekit import design, freeze, gates, golden, installer, landing, logbook, rigor, waves
from ekit.cli import main as ekit_main
from ekit.project import EkitError, Project, dump_yaml
from h070 import git, make_project, write_design, write_ports, write_reports

FAKE_SPECIFY = textwrap.dedent('''
    import json, sys
    from pathlib import Path
    a = sys.argv[1:]
    if a[0] == "init":
        root = Path.cwd() if "--here" in a else Path(a[1])
        (root / ".specify").mkdir(parents=True, exist_ok=True)
        (root / ".specify" / "integration.json").write_text(json.dumps({"installed_integrations": ["opencode"]}))
''')


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv(golden.SKIP_POST_INSTALL_ENV, "1")
    monkeypatch.setenv("EKIT_SMOKE_NO_RUN", "1")
    fake = tmp_path / "fake_specify.py"
    fake.write_text(FAKE_SPECIFY, encoding="utf-8")
    monkeypatch.setenv("EKIT_SPECIFY", f'"{sys.executable}" "{fake}"')


def _init(tmp_path, *extra, stack="fastapi-jinja", name="proj"):
    return installer.init(str(tmp_path / name), stack=stack, source="bundled", integration="opencode", force=False,
                          interactive=False, extra_specify=[], **dict(extra))


def test_choose_lane_defaults_and_refusals():
    c = installer.choose_lane
    assert c(None, "greenfield", "golden") == "happy-path"
    assert c(None, "greenfield", "generate") == "classic"
    assert c(None, "brownfield", "generate") == "classic"
    assert c("classic", "greenfield", "golden") == "classic"
    assert c("happy-path", "greenfield", "generate") == "happy-path"
    with pytest.raises(EkitError, match="greenfield"):
        c("happy-path", "brownfield", "generate")
    with pytest.raises(EkitError, match="must be"):
        c("fast", "greenfield", "golden")


def test_init_greenfield_golden_defaults_to_the_happy_path_lane(tmp_path):
    root = _init(tmp_path)
    p = Project.load(root)
    assert p.config["lane"] == "happy-path" and p.config["waves"] == "on"
    plan = p.wave_plan
    assert plan.ids == ["W0", "W1"] and plan.current == "W0"
    assert plan.wave("W0")["rigor"] == "skeleton" and plan.wave("W1")["rigor"] == "standard"
    assert rigor.level(p) == "skeleton"
    errors, _ = waves.validate(plan, p.kit, waves.catalog_ids(p.kit))
    assert errors == []
    assert "ekit design approve*" in json.loads((root / "opencode.json").read_text())["permission"]["bash"]
    assert (p.kit.component("extension") / "commands/speckit.esdlc.design.md").is_file()
    assert golden.read_lock(root)["version"] == "1.1.2"
    # the report of any gate names the level
    res, notes = gates.run_gate(p, "red")
    assert res.rigor == "skeleton" and any("rigor: skeleton" in n for n in notes)


def test_init_lane_classic_keeps_0_6_4(tmp_path):
    root = _init(tmp_path, ("lane", "classic"))
    p = Project.load(root)
    assert p.config["lane"] == "classic" and p.wave_plan is None and waves.project_mode(root) == "undecided"
    assert rigor.level(p) is None
    assert "design" not in gates.default_gate_ids(p) and "smoke" not in gates.default_gate_ids(p)


def test_init_non_golden_stack_stays_classic_by_default(tmp_path):
    root = _init(tmp_path, ("baseline", "generate"), stack="fastapi-react")
    assert Project.load(root).config["lane"] == "classic"


def test_cli_init_accepts_the_lane_option(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert ekit_main(["init", "app", "--stack", "fastapi-jinja", "--source", "bundled", "--non-interactive",
                      "--lane", "classic"]) == 0
    assert Project.load(tmp_path / "app").config["lane"] == "classic"


def test_wave_init_in_the_lane_proposes_w0_with_every_feature(tmp_path):
    p = make_project(tmp_path)
    waves.init_proposal(p.root)
    prop = waves.load_plan(p.root, waves.PROPOSAL)
    assert prop.ids == ["W0", "W1"] and prop.wave("W0")["rigor"] == "skeleton"
    assert prop.wave("W0")["scope"] == ["chat:FEAT-01", "chat:FEAT-02"]
    plan, notes = waves.approve(p.root, p.kit, "Priya")
    assert plan.current == "W0" and plan.wave("W0")["scope"] == ["chat:AC-001", "chat:AC-002"]
    assert plan.wave("W0")["rigor"] == "skeleton"


# ---------------------------------------------------------------- the adoption point
def _ready(tmp_path) -> Project:
    p = make_project(tmp_path)
    git(p.root, "init", "-q")
    git(p.root, "config", "user.email", "t@example.com")
    git(p.root, "config", "user.name", "t")
    installer.set_baseline_mode(p.root, "golden")
    installer.install_golden(Project.load(p.root), name="Chat", run_post=False)
    waves.init_proposal(p.root)
    waves.approve(p.root, p.kit, "Priya")
    write_design(p.root)
    write_reports(p.root)
    write_ports(p.root)
    j = p.root / "tests/acceptance/journeys"
    j.mkdir(parents=True, exist_ok=True)
    (j / "j01-exchange.feature").write_text("@J-01 @FEAT-01\nFeature: x\n", encoding="utf-8")
    git(p.root, "add", "-A")
    git(p.root, "commit", "-qm", "w0")
    return Project.load(p.root)


def test_leaving_w0_needs_approval_green_smoke_and_a_recorded_baseline(tmp_path):
    p = _ready(tmp_path)
    with pytest.raises(EkitError) as exc:
        waves.advance(p.root, p.kit, "Priya")
    msg = str(exc.value)
    assert "adoption point" in msg and "design is not approved" in msg and "baseline is not run" in msg
    design.approve(p, "Priya")
    landing.record(Project.load(p.root))
    write_reports(p.root, journeys={**json.loads((p.root / "reports/journeys.json").read_text()),
                                    "journeys": [{"id": "J-01", "scenario": "s", "features": ["FEAT-01", "FEAT-02"], "outcome": "failed"}]})
    with pytest.raises(EkitError, match="gate smoke: SMOKE-JOURNEYS-PASS"):
        waves.advance(p.root, p.kit, "Priya")
    write_reports(p.root)
    cur, nxt, notes = waves.advance(p.root, p.kit, "Priya")
    assert (cur, nxt) == ("W0", "W1")
    assert any("1 journey file(s) fingerprinted" in n and "rigor is now standard" in n for n in notes)
    q = Project.load(p.root)
    assert q.wave_plan.current == "W1" and rigor.level(q) == "standard"
    rec = yaml.safe_load((p.root / waves.W0_RECORD).read_text())
    assert list(rec["files"]) == ["tests/acceptance/journeys/j01-exchange.feature"] and rec["by"] == "Priya"
    ev = [e for e in logbook.iter_events(p.root) if e.get("kind") == "state.wave.advance"]
    assert ev and ev[-1]["by"] == "Priya"
    # the journeys are now a regression suite: changing one fails the smoke gate
    (p.root / "tests/acceptance/journeys/j01-exchange.feature").write_text("@J-01\nFeature: weakened\n", encoding="utf-8")
    res, _ = gates.run_gate(Project.load(p.root), "smoke")
    assert [c.id for c in res.checks if c.status == "fail"] == ["SMOKE-W0-INTACT"]
    assert res.rigor == "standard"


def test_a_stale_design_approval_blocks_the_adoption_point(tmp_path):
    p = _ready(tmp_path)
    design.approve(p, "Priya")
    landing.record(Project.load(p.root))
    (p.root / "docs/design/architecture.md").write_text((p.root / "docs/design/architecture.md").read_text() + "\nmore\n")
    with pytest.raises(EkitError, match="design changed after it was approved"):
        waves.advance(p.root, p.kit, "Priya")


def test_cli_wave_advance_out_of_w0(tmp_path, monkeypatch, capsys):
    p = _ready(tmp_path)
    design.approve(p, "Priya")
    landing.record(Project.load(p.root))
    monkeypatch.chdir(p.root)
    assert ekit_main(["wave", "advance", "--by", "Priya"]) == 0
    out = capsys.readouterr().out
    assert "fingerprinted in .ekit/ledger/w0-journeys.yaml" in out and "Moved from W0 to W1" in out
    assert ekit_main(["wave", "advance", "--by", "Priya"]) == 2
    assert "last wave" in capsys.readouterr().err


def test_ekit_status_shows_lane_rigor_and_design_state(tmp_path, monkeypatch, capsys):
    p = _ready(tmp_path)
    monkeypatch.chdir(p.root)
    assert ekit_main(["status"]) == 0
    assert "Lane: happy-path; rigor skeleton; design not approved" in capsys.readouterr().out
    design.approve(p, "Priya")
    assert ekit_main(["status"]) == 0
    assert "design approved by Priya" in capsys.readouterr().out
