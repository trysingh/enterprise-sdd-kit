"""ekit 0.7.2: fixes from the second happy-path test run."""
from __future__ import annotations

import shutil
import subprocess
import types
from pathlib import Path

import pytest
import yaml

import ekit
from ekit import design, features, gates, golden, installer, stepbind
from ekit.project import EkitError, Project
from h070 import design_data, make_project, write_design

TREE = Path(golden.__file__).parent / "kit" / "golden" / "fastapi-jinja" / "tree"
GOLDEN = TREE.parent


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("EKIT_SMOKE_NO_RUN", "1")
    monkeypatch.setenv(golden.SKIP_POST_INSTALL_ENV, "1")


def test_versions():
    assert ekit.__version__ == "0.7.2"
    assert yaml.safe_load((GOLDEN / "golden.yaml").read_text())["metadata"]["version"] == "1.1.2"
    assert yaml.safe_load((GOLDEN.parent.parent / "kit.yaml").read_text())["metadata"]["version"] == "0.7.2"


# ------------------------------------------------------------------ 1. journey steps resolve remembered values
class _Ctx:
    def __init__(self):
        self.values, self.response = {}, None

    def remember(self, k, v):
        self.values[k] = v

    def recall(self, k):
        return self.values[k]            # KeyError, a LookupError, like MissingScenarioStateError


@pytest.fixture
def steps(monkeypatch):
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        monkeypatch.setitem(__import__("sys").modules, name, m)
    ident = lambda *a: (lambda f: f)                                           # noqa: E731
    mod("fastapi", FastAPI=object)
    mod("fastapi.testclient", TestClient=object)
    mod("pytest_bdd", given=ident, when=ident, then=ident, parsers=types.SimpleNamespace(re=lambda p: p))
    mod("tests"); mod("tests.acceptance")
    mod("tests.acceptance.support", ScenarioContext=_Ctx)
    mod("tests.acceptance.support.paths", REPO_ROOT=TREE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("api_steps_072", TREE / "tests/acceptance/api_steps.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _with_response(ctx, text):
    ctx.response = types.SimpleNamespace(text=text)
    ctx.last_response = ctx.response
    return ctx


def test_contains_and_not_contains_resolve_remembered_values(steps):
    ctx = _with_response(_Ctx(), '{"id": 7, "name": "ravi"}')
    ctx.remember("peer", "ravi")
    ctx.remember("gone", "zed")
    steps.response_contains(ctx, "{peer}")
    steps.response_does_not_contain(ctx, "{gone}")
    with pytest.raises(AssertionError):
        steps.response_does_not_contain(ctx, "{peer}")           # the old behaviour passed this vacuously
    with pytest.raises(AssertionError):
        steps.response_contains(ctx, "{gone}")
    steps.response_contains(ctx, "name")                         # literal text still works


def test_unknown_placeholders_are_errors_not_passes(steps):
    ctx = _with_response(_Ctx(), "<h1>hello</h1>")
    for bad in ("{nope}", "<x>", "pre {nope} post"):
        with pytest.raises(LookupError, match="not a remembered value"):
            steps.response_does_not_contain(ctx, bad)
        with pytest.raises(LookupError):
            steps.response_contains(ctx, bad)
    steps.response_contains(ctx, "<h1>")                         # a real tag is not a placeholder
    steps.response_does_not_contain(ctx, "<h2>")


def test_step_patterns_still_do_not_shadow():
    defs, dynamic = stepbind.visible_definitions(TREE / "tests/acceptance/journeys/test_journeys.py", TREE, {})
    assert dynamic == 0
    for text in ('the response contains "{id}"', 'the response does not contain "{id}"',
                 'the response contains the remembered "id"', 'the response contains "x" with count 1'):
        assert len([d for d in defs if d.pattern is not None and d.pattern.fullmatch(text)]) == 1, text


# ------------------------------------------------------------------ 2. ekit init: directory + git
def _fake_init(monkeypatch):
    monkeypatch.setattr(installer, "run_specify", lambda *a, **k: None)
    monkeypatch.setattr(installer, "installed_integrations", lambda root: {"opencode"})


def _init(target, **kw):
    return installer.init(str(target), stack=kw.get("stack", "springboot-react"), source="bundled", integration="opencode",
                          force=False, interactive=False, extra_specify=[], baseline="generate", lane="classic")


def _git_ok():
    return shutil.which("git") is not None


def _identity(monkeypatch):
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@e.x"), ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@e.x")):
        monkeypatch.setenv(k, v)


@pytest.mark.skipif(not _git_ok(), reason="git not installed")
def test_init_creates_a_missing_directory_and_commits(tmp_path, monkeypatch, capsys):
    _fake_init(monkeypatch)
    _identity(monkeypatch)
    target = tmp_path / "new" / "app"
    _init(target)
    assert (target / ".ekit").is_dir()
    assert (target / ".git").is_dir()
    log = subprocess.run(["git", "log", "--oneline"], cwd=target, capture_output=True, text=True).stdout
    assert "chore: ekit init" in log
    assert subprocess.run(["git", "status", "--porcelain"], cwd=target, capture_output=True, text=True).stdout.strip() == ""


@pytest.mark.skipif(not _git_ok(), reason="git not installed")
def test_init_never_commits_into_an_existing_repo(tmp_path, monkeypatch, capsys):
    _fake_init(monkeypatch)
    _identity(monkeypatch)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _init(tmp_path)
    assert subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=tmp_path, capture_output=True).returncode != 0   # no commit
    out = capsys.readouterr().out
    assert "already in a git repository" in out and "git add -A" in out


def test_init_without_git_prints_a_message(tmp_path, monkeypatch, capsys):
    _fake_init(monkeypatch)
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)
    target = tmp_path / "app"
    _init(target)
    out = capsys.readouterr().out
    assert "git not found" in out and not (target / ".git").exists()


@pytest.mark.skipif(not _git_ok(), reason="git not installed")
def test_init_commit_failure_is_a_message_not_a_crash(tmp_path, monkeypatch, capsys):
    real = installer._git

    def fake(root, *args):
        if args and args[0] == "commit":
            return subprocess.CompletedProcess(args, 1, "", "Author identity unknown")
        return real(root, *args)
    monkeypatch.setattr(installer, "_git", fake)
    assert installer.git_bootstrap(tmp_path) == "init-only"
    assert "initial commit failed" in capsys.readouterr().out


# ------------------------------------------------------------------ 3. gates before design approval
def _happy_project(tmp_path):
    from ekit import waves
    p = make_project(tmp_path)
    cfg = p.root / ".ekit" / "project.yaml"
    data = yaml.safe_load(cfg.read_text())
    data["lane"] = "happy-path"
    cfg.write_text(yaml.safe_dump(data))
    waves.write_happy_path_plan(p.root)
    return Project.load(p.root)


def test_before_design_approval_waves_note_is_info_not_a_problem(tmp_path):
    proj = _happy_project(tmp_path)
    notes = gates.wave_notes(proj)
    text = "\n".join(notes)
    assert "no longer valid" not in text
    assert "waves will be placed when the design is approved" in text and "ekit design approve" in text


def test_after_approval_a_broken_plan_is_still_reported(tmp_path):
    proj = _happy_project(tmp_path)
    (proj.root / design.APPROVAL).write_text("by: x\n")
    text = "\n".join(gates.wave_notes(Project.load(proj.root)))
    assert "no longer valid" in text and "waves will be placed" not in text


# ------------------------------------------------------------------ 4. DESIGN-DECISIONS: the ADR must be about the decision
def _decisions_gate(tmp_path, adr_text, decision=None):
    p = make_project(tmp_path)
    write_design(p.root)
    d = design.load_design(p.root)
    dec = decision or {"id": "D1", "title": "Topology", "status": "accepted", "adr": "ADR-0002"}
    d["decisions"] = [dec]
    (p.root / design.DESIGN_YAML).write_text(yaml.safe_dump(d))
    adr = p.root / "docs/adr"
    adr.mkdir(parents=True, exist_ok=True)
    for f in adr.glob("*.md"):
        f.unlink()
    (adr / "0002-something.md").write_text(adr_text, encoding="utf-8")
    res, _ = gates.run_gate(Project.load(p.root), "design")
    return [f.message for c in res.checks if c.id == "DESIGN-DECISIONS" for f in c.findings if f.level == "error"]


def test_unrelated_adr_is_rejected_with_a_hint(tmp_path):
    errs = _decisions_gate(tmp_path, "# ADR-0002: Use postgres\n\nBecause.\n")
    assert len(errs) == 1 and "does not mention D1" in errs[0] and "ekit adr new" in errs[0] and "--decision D1" in errs[0]


@pytest.mark.parametrize("text", ["# ADR-0002: x\n\nDecision: D1\n", "# ADR-0002: Pick the TOPOLOGY\n", "# ADR\n\nthe topology, then.\n"])
def test_adr_naming_the_id_or_title_passes(tmp_path, text):
    assert _decisions_gate(tmp_path, text) == []


def test_id_and_title_match_whole_words_only(tmp_path):
    assert _decisions_gate(tmp_path, "# ADR-0002: x\n\nD10 and topologyx and multitopology\n")


def test_adr_new_with_decision_writes_the_reference(tmp_path):
    p = make_project(tmp_path)
    write_design(p.root)
    path = features.new_adr(p.root, "Choose layout", decision="D1")
    text = path.read_text()
    assert "**Decision**: D1" in text and "Topology" in text
    with pytest.raises(EkitError, match="no decision D9"):
        features.new_adr(p.root, "Other", decision="D9")


def test_adr_new_decision_closes_the_loop_with_the_gate(tmp_path):
    p = make_project(tmp_path)
    write_design(p.root)
    path = features.new_adr(p.root, "Something unrelated in its title", decision="D1")
    num = path.name[:4]
    d = design.load_design(p.root)
    d["decisions"] = [{"id": "D1", "title": "Topology", "status": "accepted", "adr": f"ADR-{num}"}]
    (p.root / design.DESIGN_YAML).write_text(yaml.safe_dump(d))
    for f in (p.root / "docs/adr").glob("0002-*"):
        f.unlink()
    res, _ = gates.run_gate(Project.load(p.root), "design")
    assert not [c for c in res.checks if c.id == "DESIGN-DECISIONS" and c.status == "fail"]


def test_cli_adr_accepts_decision_flag():
    from ekit.cli import build_parser
    ns = build_parser().parse_args(["adr", "new", "T", "--decision", "D1"])
    assert ns.decision == "D1"
