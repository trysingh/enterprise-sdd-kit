"""ekit 0.6.0: forward baseline for brownfield projects (pipeline readiness, Inherited, ratchet,
constitution lock, duplicate rows, report dirs, pin file encoding). Greenfield paths are pinned unchanged."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from test_ekit_030 import _bare, _ctx

from ekit import checks, constitution, freeze, ratchet, runner
from ekit.cli import main as ekit_main
from ekit.project import EkitError, Kit, Project, bundled_kit_dir, dump_yaml, load_yaml

CONF = "docs/engineering/baseline-conformance.md"
KIT = bundled_kit_dir()


def _proj(tmp_path, mode: str | None) -> Project:
    root = _bare(tmp_path)
    if mode:
        data = load_yaml(root / ".ekit/project.yaml")
        data["mode"] = mode
        dump_yaml(data, root / ".ekit/project.yaml")
    return Project.load(root)


def _table(p: Project, **rows: tuple[str, str, str]) -> None:
    """Conformance file: every applicable platform NFR Addressed, except those given as ID_WITH_UNDERSCORE=(status, evidence, adr)."""
    lines = []
    over = {k.replace("_", "-"): v for k, v in rows.items()}
    for n in p.applicable_nfrs(scope="platform"):
        st, ev, adr = over.pop(n["id"], ("Addressed", "src/app.py", ""))
        if st is None:
            continue
        lines.append(f"| {n['id']} | {n['title']} | {st} | {ev} | {adr} |")
    f = p.root / CONF
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("| NFR | Title | Status | Evidence | ADR |\n|---|---|---|---|---|\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _conf(p: Project, nid: str = "SEC-01") -> list[checks.Finding]:
    out = checks.nfr_conformance(_ctx(p), {"file": CONF, "scope": "platform"})
    return [f for f in out if nid in f.message]


# ================================================================ 1. pipeline readiness
def test_profiles_declare_pipeline_paths_inside_their_skeleton():
    kit = Kit.load(KIT)
    for prof in KIT.glob("profiles/*/*/profile.yaml"):
        layout = yaml.safe_load(prof.read_text(encoding="utf-8"))["layout"]
        assert "pipeline_paths" in layout, prof
        extra = set(layout["pipeline_paths"]) - set(layout["required_paths"])
        assert extra <= {"tests/unit"}, (prof, extra)
    fa = yaml.safe_load((KIT / "profiles/backend/fastapi/profile.yaml").read_text(encoding="utf-8"))
    assert fa["layout"]["pipeline_paths"] == ["pyproject.toml", "uv.lock", ".python-version", "tests/unit",
                                                "tests/acceptance/conftest.py", ".gitignore"]
    assert kit.version == "0.7.2"


def test_brownfield_requires_only_pipeline_paths(tmp_path):
    p = _proj(tmp_path, "brownfield")
    out = checks.required_paths(_ctx(p), {})
    errors = [f for f in out if f.level == "error"]
    assert {f.message.split()[2] for f in errors} == {"pyproject.toml", "uv.lock", ".python-version", "tests/unit",
                                                      "tests/acceptance/conftest.py", ".gitignore"}
    assert all("additive" in f.message and "does not touch existing code" in f.message for f in errors)
    assert not any("main.py" in f.message or "Dockerfile" in f.message for f in out)
    info = [f for f in out if f.level == "info" and f.message.startswith("[backend/fastapi]")]
    assert len(info) == 1 and info[0].message.startswith("[backend/fastapi] brownfield: ")
    assert info[0].message.endswith("skeleton path(s) not required; the baseline applies to new code")


def test_brownfield_passes_with_pipeline_paths_only(tmp_path):
    p = _proj(tmp_path, "brownfield")
    for rel in ["pyproject.toml", "uv.lock", ".python-version", "tests/acceptance/conftest.py", ".gitignore"]:
        f = p.root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x\n", encoding="utf-8")
    (p.root / "tests/unit").mkdir(parents=True)
    assert {f.level for f in checks.required_paths(_ctx(p), {})} == {"info"}   # one line per profile, no errors


def test_greenfield_required_paths_unchanged(tmp_path):
    out = checks.required_paths(_ctx(_proj(tmp_path, "greenfield")), {})
    assert out and {f.level for f in out} == {"error"}
    assert any("src/app/main.py" in f.message for f in out) and not any("additive" in f.message for f in out)


@pytest.mark.parametrize("state", ["not-repo", "dubious", "no-git"])
def test_environment_git_unusable_is_error_in_brownfield_warn_in_greenfield(monkeypatch, tmp_path, state):
    monkeypatch.setattr(checks, "git_state", lambda _r: state)
    brown = checks.profile_environment(_ctx(_proj(tmp_path / "b", "brownfield")), {})
    green = checks.profile_environment(_ctx(_proj(tmp_path / "g", None)), {})
    gb = [f for f in brown if "git" in f.message.lower() and f.level == "error" and "commits" in f.message]
    gg = [f for f in green if f.level == "warn" and "cannot verify" in f.message]
    assert gb and gg
    fix = {"dubious": "safe.directory", "not-repo": "git init", "no-git": "install git"}[state]
    assert fix in gb[0].message and fix in gg[0].message


def test_conformance_file_optional_in_brownfield(tmp_path):
    p = _proj(tmp_path, "brownfield")
    out = checks.nfr_conformance(_ctx(p), {"file": CONF, "scope": "platform"})
    assert [(f.level, f.message) for f in out] == [
        ("info", f"no snapshot ({CONF}); optional: /speckit.esdlc.baseline snapshot")]


def test_conformance_file_required_in_greenfield(tmp_path):
    out = checks.nfr_conformance(_ctx(_proj(tmp_path, None)), {"file": CONF, "scope": "platform"})
    assert out and all(f.level == "error" for f in out)


def test_feature_scope_table_stays_required_in_brownfield(tmp_path):
    p = _proj(tmp_path, "brownfield")
    out = checks.nfr_conformance(_ctx(p), {"file": "specs/x/plan.md", "scope": "feature"})
    assert out and all(f.level == "error" for f in out)


# ================================================================ 2. Inherited
def test_catalog_lists_inherited():
    assert {"Gap", "Inherited"} <= set(Kit.load(KIT).nfr_catalog()["statuses"])


def test_inherited_is_info_without_evidence_in_brownfield(tmp_path):
    p = _proj(tmp_path, "brownfield")
    _table(p, SEC_01=("Inherited", "", ""))
    out = _conf(p)
    assert [f.level for f in out] == ["info"] and "SEC-01 inherited" in out[0].message


def test_inherited_is_error_in_greenfield(tmp_path):
    p = _proj(tmp_path, None)
    _table(p, SEC_01=("Inherited", "legacy", ""))
    out = _conf(p)
    assert [(f.level, f.message) for f in out] == [
        ("error", "SEC-01: Inherited is for adopted (brownfield) repositories; use Addressed, N/A, or Waived with an ADR")]


def test_gap_unchanged_by_inherited(tmp_path):
    p = _proj(tmp_path, "brownfield")
    _table(p, SEC_01=("Gap", "no IdP yet", "ABC-123"))
    assert [f.level for f in _conf(p)] == ["warn"]


def test_brownfield_missing_row_is_info_greenfield_is_not(tmp_path):
    b = _proj(tmp_path / "b", "brownfield")
    _table(b, SEC_01=(None, "", ""))
    out = _conf(b)
    assert [f.level for f in out] == ["info"] and "inherited as-is" in out[0].message
    g = _proj(tmp_path / "g", None)
    _table(g, SEC_01=(None, "", ""))
    assert [f.level for f in _conf(g)] == ["error"]


# ================================================================ 3. ratchet
def test_enforce_writes_and_appends(tmp_path, monkeypatch, capsys):
    p = _proj(tmp_path, "brownfield")
    monkeypatch.chdir(p.root)
    assert ekit_main(["baseline", "enforce", "SEC-01", "--reason", "new payments code"]) == 0
    assert ekit_main(["baseline", "enforce", "SEC-01", next(i for i in ratchet.platform_ids(p) if i != "SEC-01"), "--reason", "second"]) == 0
    rows = yaml.safe_load((p.root / ".ekit/baseline-enforced.yaml").read_text(encoding="utf-8"))["enforced"]
    second = next(i for i in ratchet.platform_ids(p) if i != "SEC-01")
    assert [r["id"] for r in rows] == ["SEC-01", second]
    assert rows[0]["by"] == "t" and rows[0]["reason"] == "new payments code" and rows[0]["at"].endswith("Z")
    assert "already enforced" in capsys.readouterr().out


def test_enforce_validates_ids_and_reason(tmp_path, monkeypatch):
    p = _proj(tmp_path, "brownfield")
    feature_scope = next(n["id"] for n in p.kit.nfr_catalog()["nfrs"] if n["scope"] == "feature")
    for argv in (["baseline", "enforce", "NOPE-99", "--reason", "x"],
                 ["baseline", "enforce", feature_scope, "--reason", "x"],
                 ["baseline", "enforce", "SEC-01"],
                 ["baseline", "enforce", "--reason", "x"]):
        monkeypatch.chdir(p.root)
        assert ekit_main(argv) != 0
    assert not (p.root / ".ekit/baseline-enforced.yaml").exists()


def test_enforce_by_falls_back_to_env(tmp_path, monkeypatch):
    p = _proj(tmp_path, "brownfield")
    monkeypatch.setattr(ratchet, "git", lambda *a, **k: None)
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.setenv("USERNAME", "winuser")
    ratchet.enforce(p, ["SEC-01"], "r")
    assert ratchet.load(p.root)[0]["by"] == "winuser"


@pytest.mark.parametrize("row,needle", [
    (("Inherited", "legacy", ""), "Inherited is no longer accepted"),
    (("Gap", "no IdP yet", "ABC-123"), "Gap is no longer accepted"),
    ((None, "", ""), "has no row"),
    (("Deferred (W2)", "later", ""), "cannot be deferred"),
])
def test_enforced_nfr_rejects_inherited_gap_missing(tmp_path, row, needle):
    p = _proj(tmp_path, "brownfield")
    ratchet.enforce(p, ["SEC-01"], "r")
    _table(p, SEC_01=row)
    out = _conf(p)
    assert [f.level for f in out] == ["error"] and needle in out[0].message and "enforced" in out[0].message


def test_enforced_nfr_accepts_addressed_na_waived(tmp_path):
    p = _proj(tmp_path, "brownfield")
    ratchet.enforce(p, ["SEC-01"], "r")
    for row in (("Addressed", "src/sec.py", ""), ("N/A", "no users", ""), ("Waived", "board decision", "ADR-0007")):
        _table(p, SEC_01=row)
        assert _conf(p) == []


def test_enforced_nfr_needs_the_file(tmp_path):
    p = _proj(tmp_path, "brownfield")
    ratchet.enforce(p, ["SEC-01", "SEC-04"], "r")
    out = checks.nfr_conformance(_ctx(p), {"file": CONF, "scope": "platform"})
    assert {f.level for f in out} == {"error"} and len(out) == 2
    assert all("enforced" in f.message and "does not exist" in f.message for f in out)


def test_non_enforced_rows_stay_lenient_when_others_are_enforced(tmp_path):
    p = _proj(tmp_path, "brownfield")
    ratchet.enforce(p, ["SEC-01"], "r")
    _table(p, SEC_01=("Addressed", "x", ""), SEC_04=("Inherited", "", ""))
    assert [f.level for f in checks.nfr_conformance(_ctx(p), {"file": CONF, "scope": "platform"})] == ["info"]


def test_baseline_status_lists_enforced(tmp_path, monkeypatch, capsys):
    p = _proj(tmp_path, "brownfield")
    ratchet.enforce(p, ["SEC-01"], "payments")
    monkeypatch.chdir(p.root)
    assert ekit_main(["baseline", "status"]) == 0
    out = capsys.readouterr().out
    assert "Enforced NFRs" in out and "SEC-01" in out and "payments" in out


def test_no_unenforce_command():
    from ekit.cli import build_parser
    with pytest.raises(SystemExit):
        build_parser().parse_args(["baseline", "unenforce", "SEC-01"])


def test_person_only_commands_are_denied_to_the_agent():
    assert "ekit baseline enforce*" in freeze.ALWAYS_BASH and "ekit constitution lock*" in freeze.ALWAYS_BASH
    agents = (KIT / "opencode/AGENTS.block.md").read_text(encoding="utf-8")
    assert "enforce" in agents and "ekit constitution lock" in agents


# ================================================================ 4. constitution lock
def _ratified(p: Project) -> Path:
    constitution.ratify(p, name="Demo")
    return p.root / constitution.MEMORY


def test_lock_requires_brownfield(tmp_path):
    p = _proj(tmp_path, None)
    _ratified(p)
    with pytest.raises(EkitError, match="brownfield"):
        constitution.lock(p)


def test_lock_records_hashes_and_compares_v_to_viii_with_the_lock(tmp_path, monkeypatch):
    p = _proj(tmp_path, "brownfield")
    mem = _ratified(p)
    text = mem.read_text(encoding="utf-8")
    want = constitution.principles(text)
    # team rewrites principle V
    heading = [ln for ln in text.splitlines() if ln.startswith("### V.")][0]
    mem.write_text(text.replace(heading, heading + "\n\nTeam variant: do it our way."), encoding="utf-8")
    assert constitution.principles_drift(p)[0] == "changed"
    monkeypatch.chdir(p.root)
    assert ekit_main(["constitution", "lock"]) == 0
    lock = yaml.safe_load((p.root / constitution.LOCK).read_text(encoding="utf-8"))
    assert set(lock["principles"]) == {"V", "VI", "VII", "VIII"} and lock["by"] == "t" and lock["at"].endswith("Z")
    have = constitution.principles(mem.read_text(encoding="utf-8"))
    assert lock["principles"]["VI"] == hashlib.sha256(have["VI"].encode()).hexdigest()
    assert have["V"] != want["V"]
    assert constitution.principles_drift(p) == ("intact", [])
    # editing a locked principle again is drift, and the message names the lock
    mem.write_text(mem.read_text(encoding="utf-8").replace("Team variant", "Other variant"), encoding="utf-8")
    state, details = constitution.principles_drift(p)
    assert state == "changed" and "principle V differs from .ekit/constitution.lock.yaml" in details[0]


def test_i_to_iv_always_compared_with_the_kit_even_with_a_lock(tmp_path):
    p = _proj(tmp_path, "brownfield")
    mem = _ratified(p)
    constitution.lock(p)
    heading = [ln for ln in mem.read_text(encoding="utf-8").splitlines() if ln.startswith("### I.")][0]
    mem.write_text(mem.read_text(encoding="utf-8").replace(heading, heading + " (edited)"), encoding="utf-8")
    state, details = constitution.principles_drift(p)
    assert state == "changed" and details == ["principle I differs from the kit template"]
    findings = checks.constitution_intact(_ctx(p), {})
    assert findings and findings[0].level == "error" and "ekit constitution lock" in findings[0].message


def test_lock_refuses_when_i_to_iv_differ(tmp_path):
    p = _proj(tmp_path, "brownfield")
    mem = _ratified(p)
    heading = [ln for ln in mem.read_text(encoding="utf-8").splitlines() if ln.startswith("### II.")][0]
    mem.write_text(mem.read_text(encoding="utf-8").replace(heading, heading + " (edited)"), encoding="utf-8")
    with pytest.raises(EkitError, match="I–IV cannot be locked"):
        constitution.lock(p)


def test_brownfield_without_lock_compares_with_kit_and_mentions_lock(tmp_path):
    p = _proj(tmp_path, "brownfield")
    mem = _ratified(p)
    heading = [ln for ln in mem.read_text(encoding="utf-8").splitlines() if ln.startswith("### VII.")][0]
    mem.write_text(mem.read_text(encoding="utf-8").replace(heading, heading + " (team)"), encoding="utf-8")
    state, details = constitution.principles_drift(p)
    assert state == "changed" and "differs from the kit template" in details[0] and "ekit constitution lock" in details[0]


def test_greenfield_constitution_drift_unchanged(tmp_path):
    p = _proj(tmp_path, None)
    mem = _ratified(p)
    heading = [ln for ln in mem.read_text(encoding="utf-8").splitlines() if ln.startswith("### VII.")][0]
    mem.write_text(mem.read_text(encoding="utf-8").replace(heading, heading + " (team)"), encoding="utf-8")
    state, details = constitution.principles_drift(p)
    assert (state, details) == ("changed", ["principle VII differs from the kit template"])
    msg = checks.constitution_intact(_ctx(p), {})[0].message
    assert "Restore I–VIII" in msg and "lock" not in msg
    # a stray lock file is ignored in greenfield
    dump_yaml({"principles": {"VII": "0"}}, p.root / constitution.LOCK)
    assert constitution.principles_drift(p)[0] == "changed"


# ================================================================ 5. duplicate rows
@pytest.mark.parametrize("mode", ["brownfield", "greenfield"])
def test_duplicate_rows_are_an_error(tmp_path, mode):
    p = _proj(tmp_path, mode)
    _table(p)
    f = p.root / CONF
    f.write_text(f.read_text(encoding="utf-8") + "| SEC-01 | dup | N/A | not needed | |\n", encoding="utf-8")
    out = [x for x in checks.nfr_conformance(_ctx(p), {"file": CONF, "scope": "platform"}) if x.level == "error"]
    assert [x.message for x in out] == [f"SEC-01: 2 rows in {CONF}; keep one"]


# ================================================================ 6. report dirs
def test_prepare_report_dirs_creates_reports(tmp_path):
    p = _proj(tmp_path, None)
    prof = p.profiles[0]
    assert not (prof.root / "reports").exists()
    runner.prepare_report_dirs(prof)
    assert (prof.root / "reports").is_dir()


def test_run_profile_command_creates_report_parents(tmp_path):
    p = _proj(tmp_path, None)
    prof = p.profiles[0]
    prof.data["bdd"] = {"framework": "pytest-bdd", "report": "out/deep/cucumber.json"}
    prof.data["commands"] = {"acceptance": ["python", "-c", "pass"]}
    res = runner.run_profile_command(prof, "acceptance")
    assert res is not None and res.returncode == 0
    assert (prof.root / "reports").is_dir() and (prof.root / "out/deep").is_dir()


# ================================================================ 7. pin file encoding
@pytest.mark.parametrize("raw,problem,text", [
    ("3.12\n".encode("utf-16"), "UTF-16", "3.12"),                       # PowerShell 5.1 `echo 3.12 > f` (LE + BOM)
    ("3.12\r\n".encode("utf-16-le"), "UTF-16", "3.12"),                  # no BOM
    ("3.12\r\n".encode("utf-8-sig"), "UTF-8 with BOM", "3.12"),
    (b"3.12\n", None, "3.12"),
    (b"3.12\r\n", None, "3.12"),
])
def test_read_pin(tmp_path, raw, problem, text):
    f = tmp_path / ".python-version"
    f.write_bytes(raw)
    assert checks.read_pin(f) == (text, problem)


def _env_project(tmp_path, raw: bytes, venv_version="3.12.4") -> tuple[Project, str]:
    p = _proj(tmp_path, None)
    (p.root / ".python-version").write_bytes(raw)
    (p.root / ".venv").mkdir()
    (p.root / ".venv/pyvenv.cfg").write_text(f"version_info = {venv_version}\n", encoding="utf-8")
    return p, venv_version


@pytest.mark.parametrize("raw,enc", [("3.12\n".encode("utf-16"), "UTF-16"), ("3.12\n".encode("utf-8-sig"), "UTF-8 with BOM")])
def test_environment_reports_non_plain_pin(tmp_path, raw, enc):
    p, _ = _env_project(tmp_path, raw)
    out = checks.profile_environment(_ctx(p), {})
    hit = [f for f in out if "is " + enc in f.message]
    assert len(hit) == 1 and hit[0].level == "error"
    assert hit[0].message.endswith("(PowerShell redirect?); rewrite it with `uv python pin 3.12`")
    assert not any("pins" in f.message for f in out)   # decoded correctly: no bogus version mismatch


def test_plain_pin_has_no_encoding_error_and_odd_pin_is_shown_with_repr(tmp_path):
    p, _ = _env_project(tmp_path, b"3.12\n")
    assert not any("PowerShell" in f.message for f in checks.profile_environment(_ctx(p), {}))
    p2, _ = _env_project(tmp_path / "x", b"3.11 \xe2\x80\x93 beta\n", venv_version="3.12.4")
    msg = [f.message for f in checks.profile_environment(_ctx(p2), {}) if "pins" in f.message]
    assert msg and "pins '3.11 – beta'" in msg[0]
    p3, _ = _env_project(tmp_path / "y", b"3.11\n")
    msg3 = [f.message for f in checks.profile_environment(_ctx(p3), {}) if "pins" in f.message]
    assert msg3 and "pins 3.11;" in msg3[0]


# ================================================================ 8. prompts / templates
def test_baseline_prompt_describes_forward_brownfield():
    t = " ".join((KIT / "extension/esdlc/commands/speckit.esdlc.baseline.md").read_text(encoding="utf-8").split())
    for needle in ("pipeline readiness", "pipeline_paths", "snapshot", "`Inherited`", "Never invent a ticket",
                   "ekit baseline enforce", "ekit constitution lock", "Empty test"):
        assert needle in t, needle


def test_plan_prompt_and_addendum_cover_platform_nfrs_in_brownfield():
    for rel in ("preset/enterprise-baseline/commands/speckit.plan.md", "preset/enterprise-baseline/templates/plan-addendum.md"):
        t = (KIT / rel).read_text(encoding="utf-8")
        assert "platform-scope" in t and "Untouched legacy code" in t or "untouched legacy code" in t, rel


def test_conformance_template_documents_inherited():
    t = (KIT / "extension/esdlc/templates/esdlc-conformance-template.md").read_text(encoding="utf-8")
    assert "`Inherited`" in t and "brownfield" in t and "optional" in t


def test_context_shows_mode(tmp_path, monkeypatch, capsys):
    p = _proj(tmp_path, "brownfield")
    monkeypatch.chdir(p.root)
    assert ekit_main(["context", "--nfr", "platform"]) == 0
    assert "mode: brownfield" in capsys.readouterr().out


# ================================================================ 9. versions
def test_versions():
    import ekit
    assert ekit.__version__ == "0.7.2"
    assert 'version = "0.7.2"' in (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    kit = Kit.load(KIT)
    assert kit.version == "0.7.2" and kit.manifest["requires"]["ekit"] == ">=0.7.0,<0.8"
    from ekit import golden
    assert golden.for_stack(kit, "fastapi-jinja").version == "1.1.2"


def test_inherited_rejected_in_feature_plan_even_in_brownfield(tmp_path):
    p = _proj(tmp_path, "brownfield")
    feat = p.applicable_nfrs(scope="feature")
    assert feat
    nid = feat[0]["id"]
    rows = "\n".join(f"| {n['id']} | {n['title']} | {'Inherited' if n['id'] == nid else 'Addressed'} | src/x.py | |"
                     for n in feat)
    f = p.root / "specs/x/plan.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("| NFR | Title | Status | Evidence | ADR |\n|---|---|---|---|---|\n" + rows + "\n", encoding="utf-8")
    out = checks.nfr_conformance(_ctx(p), {"file": "specs/x/plan.md", "scope": "feature"})
    assert any(x.level == "error" and nid in x.message and "baseline snapshot" in x.message for x in out)


def test_fastapi_pipeline_paths_include_lockfile():
    import yaml
    from pathlib import Path
    prof = yaml.safe_load((Path(__file__).parents[1] / "src/ekit/kit/profiles/backend/fastapi/profile.yaml").read_text(encoding="utf-8"))
    assert "uv.lock" in prof["layout"]["pipeline_paths"]
