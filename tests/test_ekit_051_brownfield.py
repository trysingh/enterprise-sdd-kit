"""ekit 0.5.1: brownfield baseline. `Gap` conformance status, required_paths as warnings, git diagnostics."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_ekit_030 import _bare, _ctx

from ekit import checks, project as project_mod
from ekit.project import Project, dump_yaml, git_state, load_yaml

CONF = "docs/engineering/baseline-conformance.md"


def _proj(tmp_path, mode: str | None) -> Project:
    root = _bare(tmp_path)
    if mode:
        data = load_yaml(root / ".ekit/project.yaml")
        data["mode"] = mode
        dump_yaml(data, root / ".ekit/project.yaml")
    return Project.load(root)


def _conformance(p: Project, status: str, evidence: str, adr: str = "") -> list[checks.Finding]:
    """Conformance table with every applicable platform NFR addressed except SEC-01, which gets the row under test."""
    rows = []
    for n in p.applicable_nfrs(scope="platform"):
        if n["id"] == "SEC-01":
            rows.append(f"| SEC-01 | {n['title']} | {status} | {evidence} | {adr} |")
        else:
            rows.append(f"| {n['id']} | {n['title']} | Addressed | src/app.py | |")
    f = p.root / CONF
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("| NFR | Title | Status | Evidence | ADR |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n",
                 encoding="utf-8")
    return [x for x in checks.nfr_conformance(_ctx(p), {"file": CONF, "scope": "platform"}) if "SEC-01" in x.message]


def test_is_brownfield_defaults_to_greenfield(tmp_path):
    assert _proj(tmp_path, None).is_brownfield is False
    assert _proj(tmp_path / "b", "brownfield").is_brownfield is True


@pytest.mark.parametrize("ref", ["ABC-123", "T012", "#45", "ADR-0007"])
def test_gap_with_remediation_ref_warns_in_brownfield(tmp_path, ref):
    out = _conformance(_proj(tmp_path, "brownfield"), "Gap", f"no central IdP yet, tracked as {ref}")
    assert [f.level for f in out] == ["warn"]
    assert "SEC-01 gap: no central IdP yet" in out[0].message and f"(remediation {ref})" in out[0].message


def test_gap_ref_may_sit_in_the_adr_column(tmp_path):
    out = _conformance(_proj(tmp_path, "brownfield"), "Gap", "no central IdP yet", "PAY-77")
    assert [f.level for f in out] == ["warn"]


def test_gap_without_ref_is_an_error(tmp_path):
    out = _conformance(_proj(tmp_path, "brownfield"), "Gap", "no central IdP yet")
    assert [(f.level, f.message) for f in out] == [
        ("error", "SEC-01: Gap needs a remediation reference (ticket, task or ADR id)")]


def test_nfr_and_scenario_ids_are_not_tickets(tmp_path):
    p = _proj(tmp_path, "brownfield")
    out = _conformance(p, "Gap", "see SEC-01 and SCN-003-01, missing")
    assert [f.level for f in out] == ["error"] and "remediation reference" in out[0].message


def test_gap_needs_justification(tmp_path):
    out = _conformance(_proj(tmp_path, "brownfield"), "Gap", "", "ABC-1")
    assert any(f.level == "error" and "needs evidence or justification" in f.message for f in out)


def test_gap_in_greenfield_is_an_error(tmp_path):
    out = _conformance(_proj(tmp_path, "greenfield"), "Gap", "no IdP yet, ABC-123")
    assert [(f.level, f.message) for f in out] == [
        ("error", "SEC-01: Gap is for adopted (brownfield) repositories; use Addressed, N/A, or Waived with an ADR")]


@pytest.mark.parametrize("mode", ["brownfield", "greenfield"])
def test_waived_still_needs_an_adr_not_a_ticket(tmp_path, mode):
    p = _proj(tmp_path, mode)
    bad = _conformance(p, "Waived", "deferred, tracked as ABC-123")
    assert [f.message for f in bad] == ["SEC-01: Waived requires an ADR reference (e.g. ADR-0007)"]
    assert _conformance(p, "Waived", "deferred by the architecture board", "ADR-0007") == []


def test_catalog_lists_gap_status():
    cat = project_mod.Kit.load(project_mod.bundled_kit_dir()).nfr_catalog()
    assert "Gap" in cat["statuses"]


# ------------------------------------------------------------------ required paths
def test_required_paths_greenfield_errors_with_uv_lock_hint(tmp_path):
    # 0.6.0: brownfield no longer warns about the skeleton (see test_ekit_060_forward.py)
    out = checks.required_paths(_ctx(_proj(tmp_path, "greenfield")), {})
    assert out and {f.level for f in out} == {"error"}
    assert any("uv.lock" in f.message and "uv lock" in f.message for f in out)


def test_missing_pin_file_stays_an_error_with_a_hint(tmp_path):
    p = _proj(tmp_path, "brownfield")
    out = checks.profile_environment(_ctx(p), {})
    pin = [f for f in out if "not pinned" in f.message]
    assert pin and pin[0].level == "error" and '(a one-line file, e.g. "3.12")' in pin[0].message


# ------------------------------------------------------------------ git diagnostics
def test_git_state_not_repo_and_ok(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    # a tmp dir below a repository would report ok; make the lookup stop at tmp_path
    import os
    old = os.environ.get("GIT_CEILING_DIRECTORIES")
    os.environ["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    try:
        assert git_state(d) == "not-repo"
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        assert git_state(d) == "ok"
    finally:
        if old is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES")
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = old


def test_git_state_no_git(monkeypatch, tmp_path):
    monkeypatch.setattr(project_mod.shutil, "which", lambda _n: None)
    assert git_state(tmp_path) == "no-git"


def test_git_state_dubious(monkeypatch, tmp_path):
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a, 128, "", "fatal: detected dubious ownership in repository at 'x'")
    monkeypatch.setattr(project_mod.shutil, "which", lambda _n: "/usr/bin/git")
    monkeypatch.setattr(project_mod.subprocess, "run", fake_run)
    assert git_state(tmp_path) == "dubious"


@pytest.mark.parametrize("state,needle", [
    ("dubious", "git config --global --add safe.directory"),
    ("not-repo", "git init && git add -A && git commit"),
    ("no-git", "install git"),
])
def test_environment_warning_names_cause_and_fix(monkeypatch, tmp_path, state, needle):
    p = _proj(tmp_path, "greenfield")   # 0.6.0: a brownfield project gets an error with the same text
    monkeypatch.setattr(checks, "git_state", lambda _r: state)
    out = checks.profile_environment(_ctx(p), {})
    warn = [f for f in out if f.level == "warn" and needle in f.message]
    assert warn
    if state == "not-repo":
        assert warn[0].message.startswith("not a git repository")


def test_prd_ids_are_not_remediation_refs():
    from ekit.checks import _remediation_ref

    class _Kit:
        def nfr_catalog(self):
            return {"nfrs": [{"id": "SEC-01"}]}

    class _Proj:
        kit = _Kit()

    class _Ctx:
        project = _Proj()

    assert _remediation_ref(_Ctx(), {"adr": "", "evidence": "see FEAT-01 and AC-03"}) is None
    assert _remediation_ref(_Ctx(), {"adr": "", "evidence": "fix in CR-0007"}) == "CR-0007"


def test_constitution_principles_i_to_viii_unchanged():
    """Principles I-VIII are frozen: changing them breaks BASE-CONSTITUTION in every existing project.
    A deliberate change needs an ADR, a new kit version and an update of this hash."""
    import hashlib
    import json
    from pathlib import Path

    from ekit.constitution import principles

    t = (Path(__file__).parents[1] / "src/ekit/kit/preset/enterprise-baseline/templates/constitution-template.md").read_text(encoding="utf-8")
    assert hashlib.sha256(json.dumps(principles(t), sort_keys=True).encode()).hexdigest() == "a84f8a599375ccaea868a2198200dc9862ca8147e2f5e66815b04d9cfb365c7a"
