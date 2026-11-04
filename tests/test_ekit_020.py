"""ekit 0.2.0: optional wave planning and model tiers.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml

from ekit import checks, freeze, gates, kitsource, models, waves
from ekit.project import EkitError, Project, dump_yaml

PRD = """# Product Requirements: Loans

## 1. Goals and success metrics

| Metric | Target | Timeframe | Source |
|--------|--------|-----------|--------|

## 3. Features

### FEAT-01: Sign-in and shell

- **AC-001** (BR-001): Given a user, when they sign in, then the shell shows.
- **AC-002** (BR-001): Given a locked user, when they sign in, then access is refused.

### FEAT-02: Loan application

- **AC-003** (BR-002): Given an applicant, when they apply, then an application is created.
- **AC-004** (BR-003): Given an application, when it is incomplete, then it is rejected.

### FEAT-03: Admin

- **AC-005** (BR-004): Given an admin, when they deactivate a user, then the user cannot sign in.

## 4. Out of scope

- BR-009 — phase 2
"""


def _project(tmp_path, stack="fastapi-react"):
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": stack}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    (root / "docs/requirements/loan").mkdir(parents=True)
    (root / "docs/requirements/loan/prd.md").write_text(PRD, encoding="utf-8")
    return root


def _proposal(root, waves_=None, defer=None, dependencies=None):
    data = {"apiVersion": "ekit/v1", "kind": "WavePlan",
            "waves": waves_ or [
                {"id": "W1", "goal": "face", "scope": ["loan:FEAT-01", "loan:AC-003"]},
                {"id": "W2", "goal": "deepen", "scope": ["loan:AC-004", "loan:FEAT-03"]},
            ],
            "defer": defer or [], "dependencies": dependencies or {}}
    dump_yaml(data, root / waves.PROPOSAL)
    return data


def _trace(root, feature, acs):
    d = root / "specs" / feature
    d.mkdir(parents=True, exist_ok=True)
    dump_yaml({"feature": feature, "prd": "docs/requirements/loan", "acceptance_criteria": acs}, d / "trace.yaml")
    return d


def _green(root, feature):
    dump_yaml({"feature": feature, "entries": [{"phase": "red", "scenarios": {}}, {"phase": "green", "scenarios": {}}]},
              root / ".ekit/ledger" / f"{feature}.yaml")


def _ctx(root, feature=None):
    p = Project.load(root)
    return checks.GateContext(project=p, feature_dir=(root / "specs" / feature) if feature else None)


# ------------------------------------------------------------------ PRD index
def test_prd_parser_attributes_acs_to_features_and_stops_at_other_sections():
    idx = waves.parse_prd(PRD)
    assert idx["acs"] == ["AC-001", "AC-002", "AC-003", "AC-004", "AC-005"]
    assert idx["features"] == {"FEAT-01": ["AC-001", "AC-002"], "FEAT-02": ["AC-003", "AC-004"], "FEAT-03": ["AC-005"]}


# ------------------------------------------------------------------ optional: nothing changes without a plan
def test_waves_off_changes_nothing(tmp_path):
    root = _project(tmp_path)
    p = Project.load(root)
    assert p.wave_plan is None and waves.project_mode(root) == "undecided"
    assert [x.id for x in p.active_profiles] == [x.id for x in p.profiles] and not p.inactive_profiles
    assert {n["id"] for n in p.applicable_nfrs()} >= {"UX-01", "PERF-02"}          # frontend NFRs still required
    _trace(root, "001-x", ["AC-005"])
    out = checks.wave_scope(_ctx(root, "001-x"), {"trace": "specs/001-x/trace.yaml"})
    assert [f.level for f in out] == ["info"]
    assert gates.wave_notes(p) == []


def test_decline_records_off_and_refuses_when_a_plan_is_approved(tmp_path):
    root = _project(tmp_path)
    waves.decline(root)
    assert waves.project_mode(root) == "off"
    _proposal(root)
    waves.approve(root, Project.load(root).kit, "Head of Product")
    with pytest.raises(EkitError, match="approved wave plan exists"):
        waves.decline(root)


# ------------------------------------------------------------------ validation
def _errors(root, **kw):
    _proposal(root, **kw)
    plan = waves.load_plan(root, waves.PROPOSAL)
    kit = Project.load(root).kit
    return waves.validate(plan, kit, waves.catalog_ids(kit))[0]


def test_validation_requires_every_ac_in_exactly_one_wave(tmp_path):
    root = _project(tmp_path)
    assert _errors(root) == []
    errs = _errors(root, waves_=[{"id": "W1", "scope": ["loan:FEAT-01", "loan:AC-001"]},
                                 {"id": "W2", "scope": ["loan:FEAT-02"]}])
    text = " | ".join(errs)
    assert "loan:AC-001 is planned in more than one wave" in text
    assert "loan:AC-005 is not in any wave" in text


def test_validation_rejects_unknown_scope_and_empty_waves(tmp_path):
    root = _project(tmp_path)
    assert any("does not define AC-099" in e for e in _errors(root, waves_=[{"id": "W1", "scope": ["loan:AC-099"]}]))
    assert any("no PRD" in e for e in _errors(root, waves_=[{"id": "W1", "scope": ["cards:AC-001"]}]))
    errs = _errors(root, waves_=[{"id": "W1", "scope": ["loan:FEAT-01", "loan:FEAT-02", "loan:FEAT-03"]},
                                 {"id": "W2", "scope": []}])
    assert errs == []                                                                    # a trailing empty wave is a placeholder
    errs = _errors(root, waves_=[{"id": "W1", "scope": ["loan:FEAT-01", "loan:FEAT-02"]}, {"id": "W2", "scope": []},
                                 {"id": "W3", "scope": ["loan:FEAT-03"]}])
    assert any("W2 has no scope" in e for e in errs)


def test_non_deferrable_and_incomplete_deferrals_are_rejected(tmp_path):
    root = _project(tmp_path)
    errs = " | ".join(_errors(root, defer=[
        {"nfr": "SEC-02", "until": "W2", "reason": "later", "approved_by": "PO"},     # non-deferrable
        {"nfr": "UX-01", "until": "W1", "reason": "x", "approved_by": "PO"},           # first wave
        {"nfr": "PERF-02", "until": "W2"},                                             # no reason/approver
        {"nfr": "NOPE-01", "until": "W2", "reason": "x", "approved_by": "PO"},         # unknown
    ]))
    assert "SEC-02 is non-deferrable" in errs and "first wave" in errs
    assert "`reason` is required" in errs and "`approved_by` is required" in errs and "not an NFR" in errs
    assert _errors(root, defer=[{"nfr": "UX-01", "until": "W2", "reason": "thin UI", "approved_by": "PO"}]) == []


def test_dependency_must_start_in_the_same_or_an_earlier_wave(tmp_path):
    root = _project(tmp_path)
    errs = _errors(root, dependencies={"loan:FEAT-01": ["loan:FEAT-03"]})          # FEAT-03 only in W2
    assert any("prerequisite loan:FEAT-03 only starts in W2" in e for e in errs)
    assert _errors(root, dependencies={"loan:FEAT-03": ["loan:FEAT-01"]}) == []


# ------------------------------------------------------------------ init / approve / advance
def test_init_writes_a_proposal_with_everything_in_w1(tmp_path):
    root = _project(tmp_path)
    waves.init_proposal(root)
    data = yaml.safe_load((root / waves.PROPOSAL).read_text())
    assert data["waves"][0]["scope"] == ["loan:FEAT-01", "loan:FEAT-02", "loan:FEAT-03"]
    assert waves.project_mode(root) == "proposed"
    with pytest.raises(EkitError, match="already exists"):
        waves.init_proposal(root)


def test_approve_needs_a_name_and_a_valid_proposal(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    _proposal(root)
    with pytest.raises(EkitError, match="--by"):
        waves.approve(root, kit, " ")
    _proposal(root, waves_=[{"id": "W1", "scope": ["loan:FEAT-01"]}])
    with pytest.raises(EkitError, match="not in any wave"):
        waves.approve(root, kit, "PO")
    assert not (root / waves.APPROVED).exists()                                    # nothing written on failure
    _proposal(root)
    plan, _ = waves.approve(root, kit, "Head of Product")
    data = yaml.safe_load((root / waves.APPROVED).read_text())
    assert data["current"] == "W1" and data["approved_by"] == "Head of Product" and data["history"][0]["action"] == "approve"
    assert waves.project_mode(root) == "on"


def test_advance_refuses_unfinished_scope_unless_carried(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    _proposal(root, defer=[{"nfr": "UX-01", "until": "W2", "reason": "thin UI", "approved_by": "PO"}])
    waves.approve(root, kit, "PO")
    _trace(root, "001-shell", ["AC-001", "AC-002"])
    _green(root, "001-shell")
    with pytest.raises(EkitError, match="1 acceptance criteria of W1 have no green feature"):
        waves.advance(root, kit, "PO")
    cur, nxt, notes = waves.advance(root, kit, "PO", carry=True)
    assert (cur, nxt) == ("W1", "W2")
    assert any("carried 1 AC" in n for n in notes) and any("UX-01" in n for n in notes)
    plan = waves.load_plan(root)
    assert plan.current == "W2" and plan.wave_of("loan:AC-003") == "W2"
    assert plan.data["history"][-1]["carried"] == ["loan:AC-003"]
    with pytest.raises(EkitError, match="last wave"):
        waves.advance(root, kit, "PO", carry=True)


def test_redeferral_is_counted_and_recorded(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    three = [{"id": "W1", "scope": ["loan:FEAT-01"]}, {"id": "W2", "scope": ["loan:FEAT-02"]},
             {"id": "W3", "scope": ["loan:FEAT-03"]}]
    _proposal(root, waves_=three, defer=[{"nfr": "UX-01", "until": "W2", "reason": "thin UI", "approved_by": "PO"}])
    waves.approve(root, kit, "PO")
    _proposal(root, waves_=three, defer=[{"nfr": "UX-01", "until": "W3", "reason": "still thin", "approved_by": "PO"}])
    _, notes = waves.approve(root, kit, "PO")
    plan = waves.load_plan(root)
    assert plan.deferrals()["UX-01"]["redeferred"] == 1
    assert any("re-deferral #1" in n for n in notes)
    assert plan.data["history"][-2]["action"] == "redefer"


# ------------------------------------------------------------------ gates with waves on
def _on(root, **kw):
    _proposal(root, **kw)
    waves.approve(root, Project.load(root).kit, "PO")


def test_spec_gate_refuses_acs_from_a_later_wave(tmp_path):
    root = _project(tmp_path)
    _on(root)
    _trace(root, "001-admin", ["AC-005"])
    out = checks.wave_scope(_ctx(root, "001-admin"), {"trace": "specs/001-admin/trace.yaml"})
    assert out[0].level == "error" and "planned for W2" in out[0].message
    _trace(root, "002-apply", ["AC-003"])
    assert [f.level for f in checks.wave_scope(_ctx(root, "002-apply"), {"trace": "specs/002-apply/trace.yaml"})] == ["info"]


def test_spec_gate_flags_an_ac_that_was_never_placed(tmp_path):
    root = _project(tmp_path)
    _on(root)
    (root / "docs/requirements/loan/prd.md").write_text(PRD.replace("## 4. Out of scope",
        "- **AC-006** (BR-005): Given a change request, when ..., then ...\n\n## 4. Out of scope"), encoding="utf-8")
    _trace(root, "003-cr", ["AC-006"])
    out = checks.wave_scope(_ctx(root, "003-cr"), {"trace": "specs/003-cr/trace.yaml"})
    assert out[0].level == "error" and "not in the approved wave plan" in out[0].message
    notes = gates.wave_notes(Project.load(root))
    assert any("no longer valid" in n for n in notes)
    _proposal(root)                                     # FEAT-03 shorthand now covers AC-006: placement is visible
    _, approve_notes = waves.approve(root, Project.load(root).kit, "PO")
    assert any("newly placed: loan:AC-006" in n for n in approve_notes)
    assert "loan:AC-006" in yaml.safe_load((root / waves.APPROVED).read_text())["waves"][1]["scope"]


def _conf(root, rows):
    lines = ["| NFR | Title | Status | Evidence / Justification | ADR |", "|---|---|---|---|---|"]
    lines += [f"| {nid} | t | {status} | {ev} | |" for nid, status, ev in rows]
    (root / "plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _levels_for(root, nid):
    out = checks.nfr_conformance(_ctx(root), {"file": "plan.md", "scope": "feature"})
    return [(f.level, f.message) for f in out if f.message.startswith(nid)]


def test_deferred_status_follows_the_approved_plan(tmp_path):
    root = _project(tmp_path)
    _conf(root, [("UX-01", "Deferred (W2)", ""), ("SEC-02", "Deferred (W2)", "")])
    assert "needs an approved wave plan" in _levels_for(root, "UX-01")[0][1]          # waves off
    _on(root, defer=[{"nfr": "UX-01", "until": "W2", "reason": "thin UI", "approved_by": "PO"}])
    assert _levels_for(root, "UX-01")[0][0] == "info"
    assert "non-deferrable" in _levels_for(root, "SEC-02")[0][1]
    _conf(root, [("UX-01", "Deferred (W3)", "")])
    assert "defers it until W2" in _levels_for(root, "UX-01")[0][1]
    _conf(root, [("UX-01", "Deferred (W2)", "")])
    _trace(root, "001-shell", ["AC-001", "AC-002", "AC-003"])
    _green(root, "001-shell")
    waves.advance(root, Project.load(root).kit, "PO")
    level, msg = _levels_for(root, "UX-01")[0]
    assert level == "error" and "W2 is now current" in msg


def test_inactive_profiles_are_skipped_and_named(tmp_path):
    root = _project(tmp_path)
    _on(root, waves_=[{"id": "W1", "profiles": ["backend"], "scope": ["loan:FEAT-01", "loan:FEAT-02"]},
                      {"id": "W2", "scope": ["loan:FEAT-03"]}])
    p = Project.load(root)
    assert [x.role for x in p.active_profiles] == ["backend"] and [x.role for x in p.inactive_profiles] == ["frontend"]
    ids = {n["id"] for n in p.applicable_nfrs()}
    assert "UX-01" not in ids and "PERF-02" not in ids and "SEC-02" in ids
    assert any("not active in W1: frontend/react" in n for n in gates.wave_notes(p))
    out = checks.required_paths(_ctx(root), {})
    assert out and all("[backend/fastapi]" in f.message for f in out)                  # frontend paths not demanded


# ------------------------------------------------------------------ agent cannot run approval commands
def test_opencode_denies_approval_commands_to_the_shell_tool(tmp_path):
    freeze.sync_permissions(tmp_path)
    bash = json.loads((tmp_path / "opencode.json").read_text())["permission"]["bash"]
    assert bash["*"] == "allow"
    for pat in ("ekit wave approve*", "ekit wave advance*", "ekit models*", "ekit unfreeze*"):
        assert bash[pat] == "deny"
    assert all(ok for ok, *_ in freeze.verify(tmp_path))


# ------------------------------------------------------------------ model tiers
def _commands(root, names=("speckit.esdlc.red", "speckit.implement", "speckit.plan", "speckit.specify")):
    d = root / ".opencode/commands"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / f"{n}.md").write_text(f"---\ndescription: {n}\n---\n\nBody of {n}.\n", encoding="utf-8")
    a = root / ".opencode/agents"
    a.mkdir(parents=True, exist_ok=True)
    (a / "test-author.md").write_text("---\ndescription: t\nmode: subagent\nmodel: ollama/old\n---\nYou write tests.\n")


def test_red_is_flagship_by_default_in_the_kit_policy(tmp_path):
    root = _project(tmp_path)
    pol = models.policy(Project.load(root).kit)
    assert pol["commands"]["speckit.esdlc.red"] == "flagship"
    assert pol["commands"]["speckit.implement"] == "standard"
    assert pol["agents"]["test-author"] == "flagship"


def test_routing_is_off_without_config(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    assert models.routes(root, kit) == ([], [])
    assert models.ledger_fields(root, kit, "speckit.esdlc.red") == {"model_configured": "session default (model routing off)"}
    assert models.doctor_rows(root, kit)[0][0] is True


def test_apply_writes_frontmatter_banner_and_small_model_then_off_restores(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    _commands(root)
    (root / "opencode.json").write_text(json.dumps({"model": "ollama/qwen3:14b"}))
    before = {f: f.read_text() for f in (root / ".opencode").rglob("*.md")}
    models.write_config(root, {"flagship": "anthropic/flagship-x", "standard": "ollama/qwen3:32b", "light": "ollama/gemma4:31b-cloud"})
    notes = models.apply(root, kit)
    assert "applied to 5" in notes[0]
    red = (root / ".opencode/commands/speckit.esdlc.red.md").read_text()
    assert "model: anthropic/flagship-x  # ekit-model" in red and "[ekit] tier: flagship · model: anthropic/flagship-x" in red
    assert "model: ollama/qwen3:32b  # ekit-model" in (root / ".opencode/commands/speckit.implement.md").read_text()
    agent = (root / ".opencode/agents/test-author.md").read_text()
    assert "model: anthropic/flagship-x  # ekit-model" in agent and "ollama/old" not in agent
    assert json.loads((root / "opencode.json").read_text())["small_model"] == "ollama/gemma4:31b-cloud"
    assert models.apply(root, kit)[0] == notes[0]                                        # idempotent
    assert red == (root / ".opencode/commands/speckit.esdlc.red.md").read_text()
    assert models.ledger_fields(root, kit, "speckit.esdlc.red") == {"model_tier": "flagship", "model_configured": "anthropic/flagship-x"}
    assert all(ok for ok, label, _ in models.doctor_rows(root, kit) if "context" not in label)
    models.off(root)
    assert {f: f.read_text() for f in (root / ".opencode").rglob("*.md")} == before      # original model: restored
    assert "small_model" not in json.loads((root / "opencode.json").read_text())


def test_doctor_notices_routing_lost_after_spec_kit_rewrites_a_command(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    _commands(root)
    models.write_config(root, {"flagship": "f/x", "standard": "s/y"})
    models.apply(root, kit)
    (root / ".opencode/commands/speckit.plan.md").write_text("---\ndescription: plan\n---\nregenerated\n")
    row = next(r for r in models.doctor_rows(root, kit) if r[1] == "model routing in command/agent files")
    assert row[0] is False and "speckit.plan" in row[2] and "ekit sync" in row[2]


def test_overrides_need_reason_approver_and_expiry(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    models.write_config(root, {"flagship": "f/x", "standard": "s/y"})
    cfg = yaml.safe_load((root / models.CONFIG).read_text())
    cfg["overrides"] = {
        "speckit.esdlc.red": {"tier": "standard", "reason": "flagship quota", "approved_by": "TL", "expires": "2999-01-01"},
        "speckit.plan": {"tier": "standard", "reason": "x"},
        "speckit.esdlc.brd": {"tier": "standard", "reason": "x", "approved_by": "TL", "expires": "2000-01-01"},
    }
    dump_yaml(cfg, root / models.CONFIG)
    rts, notes = models.routes(root, kit)
    by = {r.name: r for r in rts}
    assert by["speckit.esdlc.red"].tier == "standard" and by["speckit.esdlc.red"].overridden
    assert by["speckit.plan"].tier == "flagship" and by["speckit.esdlc.brd"].tier == "flagship"
    text = " | ".join(notes)
    assert "speckit.plan ignored" in text and "speckit.esdlc.brd expired" in text


def test_discovery_and_recommendation_read_opencode_config(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (root / "opencode.json").write_text(json.dumps({
        "model": "ollama/qwen3:32b", "small_model": "ollama/gemma4:31b-cloud",
        "provider": {"ollama": {"models": {"qwen3:32b": {"limit": {"context": 40000}},
                                           "gemma4:31b-cloud": {}}},
                     "anthropic": {"models": {"big": {"limit": {"context": 200000}}}}}}))
    found = {m["id"]: m for m in models.discover(root)}
    assert found["anthropic/big"]["context"] == 200000 and found["ollama/qwen3:32b"]["role"] == "model"
    assert models.recommend(list(found.values())) == {"flagship": "anthropic/big", "standard": "ollama/qwen3:32b",
                                                      "light": "ollama/gemma4:31b-cloud"}


# ------------------------------------------------------------------ CLI wiring
def _cli(root, *args):
    return subprocess.run([sys.executable, "-m", "ekit", *args], cwd=root, capture_output=True, text=True,
                          env={"PYTHONPATH": str(__import__("pathlib").Path(checks.__file__).parents[1]), "PATH": ""})


def test_cli_wave_and_models_round_trip(tmp_path):
    root = _project(tmp_path)
    assert "waves: undecided" in _cli(root, "wave", "status", "--brief").stdout
    assert _cli(root, "wave", "init").returncode == 0
    _proposal(root)
    r = _cli(root, "wave", "approve", "--by", "Head of Product")
    assert r.returncode == 0, r.stderr
    assert "waves: on (W1)" in _cli(root, "wave", "status", "--brief").stdout
    s = _cli(root, "wave", "scope", "FEAT-02")
    assert "current wave W1: AC-003" in s.stdout and "later, W2: AC-004" in s.stdout
    st = _cli(root, "wave")
    assert "-> W1" in st.stdout and "3 AC" in st.stdout
    _commands(root)
    r = _cli(root, "models", "setup", "--flagship", "f/x", "--standard", "s/y")
    assert r.returncode == 0, r.stderr
    show = _cli(root, "models").stdout
    assert "speckit.esdlc.red" in show and "flagship  f/x" in show
    assert _cli(root, "wave", "advance").returncode == 2                                 # --by required


def test_advance_refuses_to_move_into_an_empty_placeholder_wave(tmp_path):
    root = _project(tmp_path)
    kit = Project.load(root).kit
    _proposal(root, waves_=[{"id": "W1", "scope": ["loan:FEAT-01", "loan:FEAT-02", "loan:FEAT-03"]},
                            {"id": "W2", "scope": []}])
    waves.approve(root, kit, "PO")
    _trace(root, "001-all", ["AC-001", "AC-002", "AC-003", "AC-004", "AC-005"])
    _green(root, "001-all")
    with pytest.raises(EkitError, match="W2 has no scope yet"):
        waves.advance(root, kit, "PO")
