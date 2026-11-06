"""ekit 0.7.1: fixes from the first happy-path test run (vehicle booking app)."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
import yaml

import ekit
from ekit import design, gates, golden, installer, stepbind, waves
from ekit.cli import main as ekit_main
from ekit.project import EkitError, Project
from h070 import HAPPY, PRD, design_data, errors, make_project, run, write_design, write_ports

TREE = Path(golden.__file__).parent / "kit" / "golden" / "fastapi-jinja" / "tree"
GOLDEN = TREE.parent


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("EKIT_SMOKE_NO_RUN", "1")
    monkeypatch.setenv(golden.SKIP_POST_INSTALL_ENV, "1")


def test_versions():
    assert ekit.__version__ == "0.7.2"
    assert yaml.safe_load((GOLDEN / "golden.yaml").read_text())["metadata"]["version"] == "1.1.2"


# ------------------------------------------------------------------ 1. SMOKE-RUN fails when `journeys` fails
def _smoke_proj(tmp_path):
    p = make_project(tmp_path)
    write_design(p.root)
    return Project.load(p.root)


def test_smoke_run_fails_with_exit_code_and_last_lines(tmp_path, monkeypatch):
    proj = _smoke_proj(tmp_path)
    monkeypatch.delenv("EKIT_SMOKE_NO_RUN")

    class R:
        returncode, output = 2, "\n".join(f"line {i}" for i in range(30)) + "\nno venv: run `uv sync`"
    monkeypatch.setattr("ekit.smoke.run_profile_command", lambda prof, name, **kw: R())
    out = run(proj, "smoke.run")
    assert out and out[0][0] == "error" and "exited 2" in out[0][1]
    assert "no venv" in out[0][1] and "line 29" in out[0][1] and "line 0\n" not in out[0][1]       # the tail, not everything


def test_smoke_run_passes_when_journeys_exit_zero(tmp_path, monkeypatch):
    proj = _smoke_proj(tmp_path)
    monkeypatch.delenv("EKIT_SMOKE_NO_RUN")

    class R:
        returncode, output = 0, "ok"
    monkeypatch.setattr("ekit.smoke.run_profile_command", lambda prof, name, **kw: R())
    assert [m for lv, m in run(proj, "smoke.run") if lv == "error"] == []


def test_smoke_gate_fails_on_a_nonzero_journeys_run(tmp_path, monkeypatch):
    proj = _smoke_proj(tmp_path)
    monkeypatch.delenv("EKIT_SMOKE_NO_RUN")

    class R:
        returncode, output = 2, "boom"
    monkeypatch.setattr("ekit.smoke.run_profile_command", lambda prof, name, **kw: R())
    res, _ = gates.run_gate(proj, "smoke")
    assert next(c for c in res.checks if c.id == "SMOKE-RUN").status == "fail"


# ------------------------------------------------------------------ 2. W0 scope from the design slices
def _wave_proj(tmp_path, slices=None):
    p = make_project(tmp_path)
    waves.write_happy_path_plan(p.root)
    data = design_data()
    if slices:
        data["slices"] = slices
    write_design(p.root, data)
    return Project.load(p.root)


def test_design_approval_places_w0_scope_and_proposes_the_rest_for_w1(tmp_path):
    prd = PRD.replace("## 4. Out of scope", "### FEAT-03: Reports\n\n**Satisfies**: BR-003\n\n- **AC-003** (BR-003): reports.\n\n## 4. Out of scope")
    proj = _wave_proj(tmp_path, slices=[{"id": "S0", "features": ["FEAT-01"], "journeys": ["J-01"]},
                                        {"id": "S1", "wave": "W1", "features": ["FEAT-02"], "journeys": []}])
    (proj.root / "docs/requirements/chat/prd.md").write_text(prd, encoding="utf-8")
    d = design_data()
    d["slices"] = [{"id": "S0", "features": ["FEAT-01"], "journeys": ["J-01"]},
                   {"id": "S1", "wave": "W1", "features": ["FEAT-02"], "journeys": []}]
    write_design(proj.root, d)
    proj = Project.load(proj.root)
    errs, _ = waves.validate(proj.wave_plan, proj.kit, waves.catalog_ids(proj.kit))
    assert any("not in any wave" in e for e in errs) and any("design approve" in e for e in errs)   # says what to do
    notes = design.approve(proj, "Priya")
    assert any("W0 scope placed" in n for n in notes) and any("proposed for W1" in n for n in notes)
    approved = yaml.safe_load((proj.root / ".ekit/waves.yaml").read_text())
    w0 = next(w for w in approved["waves"] if w["id"] == "W0")
    assert w0["scope"] == ["chat:AC-001"]
    rec = approved["placed_from_design"]
    assert rec["by"] == "Priya" and rec["on"] and rec["acs"] == ["chat:AC-001"]
    assert any(h["action"] == "place-from-design" and h["by"] == "Priya" for h in approved["history"])
    prop = yaml.safe_load((proj.root / "docs/planning/waves.proposed.yaml").read_text())
    assert next(w for w in prop["waves"] if w["id"] == "W1")["scope"] == ["chat:AC-002", "chat:AC-003"]
    # the person confirms the W1 proposal; the plan is then valid and keeps the who/when record
    plan, _ = waves.approve(proj.root, proj.kit, "Priya")
    assert plan.wave_of("chat:AC-001") == "W0" and plan.wave_of("chat:AC-003") == "W1"
    assert yaml.safe_load((proj.root / ".ekit/waves.yaml").read_text())["placed_from_design"]["by"] == "Priya"
    errs, _ = waves.validate(Project.load(proj.root).wave_plan, proj.kit, waves.catalog_ids(proj.kit))
    assert errs == []


def test_w0_placement_default_slice_is_w0_and_it_is_idempotent_and_lane_gated(tmp_path):
    proj = _wave_proj(tmp_path)
    design.approve(proj, "Priya")
    plan = Project.load(proj.root).wave_plan
    assert plan.acs_of("W0") == ["chat:AC-001", "chat:AC-002"]
    assert waves.place_from_design(proj.root, design.load_design(proj.root), "Priya") == []      # nothing new
    classic = make_project(tmp_path / "c", lane="classic")
    write_design(classic.root)
    assert waves.place_from_design(classic.root, design_data(), "Priya") == []                  # classic lane: untouched


def test_design_approval_without_a_wave_plan_just_approves(tmp_path):
    p = make_project(tmp_path)
    write_design(p.root)
    notes = design.approve(Project.load(p.root), "Priya")
    assert len(notes) == 1 and not (p.root / ".ekit/waves.yaml").exists()


def test_command_texts_say_where_w0_scope_comes_from():
    ext = Path(design.__file__).parent / "kit/extension/esdlc/commands"
    for name in ("brd", "design", "slice"):
        text = (ext / f"speckit.esdlc.{name}.md").read_text(encoding="utf-8")
        assert re.search(r"W0|slices", text) and ("wave" in text.lower()), name
    assert "placed in wave W0 automatically" in (ext / "speckit.esdlc.design.md").read_text(encoding="utf-8")
    assert "W0 scope comes from the design slices" in (ext / "speckit.esdlc.brd.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ 3. migrations convention and DB fixture
def test_golden_ships_an_initial_empty_revision_and_a_convention():
    src = (TREE / "migrations/versions/0001_initial.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assigns = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigns["revision"]) == "0001" and ast.literal_eval(assigns["down_revision"]) is None
    assert "ONE revision per slice" in src
    body = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert set(body) == {"upgrade", "downgrade"}
    manifest = yaml.safe_load((GOLDEN / "golden.yaml").read_text())
    assert "migrations/versions/0001_initial.py" in manifest["frozen"]
    assert "ONE revision per slice" in manifest["agent_rules"]


def test_test_fixture_builds_the_schema_from_metadata_in_a_temp_sqlite_file():
    src = (TREE / "tests/conftest.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert "Base.metadata.create_all" in src and "def db_schema" in src and "def db_session" in src
    assert re.search(r'"APP_DATABASE_URL", f"sqlite:///', src) and '"sqlite://"' not in src       # a file, not memory
    assert "def app(db_schema" in (TREE / "tests/acceptance/conftest.py").read_text(encoding="utf-8")


def test_slice_command_mentions_migrations_and_packages():
    text = (Path(design.__file__).parent / "kit/extension/esdlc/commands/speckit.esdlc.slice.md").read_text(encoding="utf-8")
    assert "one\n   revision per slice" in text and "migrations/versions" in text
    assert "one package per `FEAT-`" in text and "`package:`" in text


def test_db_fixture_really_creates_tables(tmp_path):
    sa = pytest.importorskip("sqlalchemy")
    src = (TREE / "tests/conftest.py").read_text(encoding="utf-8")
    m = re.search(r'os.environ.setdefault\("APP_DATABASE_URL", f"sqlite:///\{(.*?)\}"\)', src)
    assert m
    eng = sa.create_engine(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    class B(DeclarativeBase):
        pass

    class T(B):
        __tablename__ = "t"
        id: Mapped[int] = mapped_column(primary_key=True)
    B.metadata.create_all(eng)
    with eng.connect() as c:
        assert c.execute(sa.text("select count(*) from t")).scalar() == 0


# ------------------------------------------------------------------ 4. typed arguments and negative steps
def _steps_module():
    src = (TREE / "tests/acceptance/api_steps.py").read_text(encoding="utf-8")
    return src


def _arg_parser():
    src = _steps_module()
    ns: dict = {"re": re, "Any": object}
    arg = re.search(r"^ARG_RE = .*$", src, re.M).group(0)
    lit = re.search(r"^LITERALS = .*$", src, re.M).group(0)
    fn = re.search(r"^def parse_args\(.*?\n    return args\n", src, re.M | re.S).group(0)
    fn = fn.replace("ctx: ScenarioContext", "ctx")
    exec("\n".join([arg, lit, "def _value(ctx, raw):\n    return raw\n", fn]), ns)       # noqa: S102 - our own shipped source
    return ns["parse_args"]


def test_typed_arguments_parse_booleans_numbers_null_and_keep_quoted_text():
    parse = _arg_parser()
    got = parse(None, 'peer "ravi" and active true and archived false and count 3 and ratio 2.5 and note null and flag "true"')
    assert got == {"peer": "ravi", "active": True, "archived": False, "count": 3, "ratio": 2.5, "note": None, "flag": "true"}
    assert parse(None, 'body "is null and true"') == {"body": "is null and true"}
    assert parse(None, "") == {}


def test_negative_steps_exist_and_do_not_shadow():
    defs, dynamic = stepbind.visible_definitions(TREE / "tests/acceptance/journeys/test_journeys.py", TREE, {})
    assert dynamic == 0
    for text in ('the response does not contain "x"', "the call fails with status 404", "the list is empty",
                 'the list "items" is empty', 'the response contains "x"', "the call succeeds", "the response status is 200",
                 'the response contains "x" with count 1', 'I call "send" with active true and count 3'):
        hits = [d for d in defs if d.pattern is not None and d.pattern.fullmatch(text)]
        assert len(hits) == 1, (text, [d.source for d in hits])
    unbound = stepbind.unbound(stepbind.feature_steps(
        'Feature: f\n  Scenario: s\n    Given I am signed in as "asha"\n    When I call "x" with active true\n'
        '    Then the call fails with status 409\n    And the response does not contain "boom"\n'
        '    And the list "items" is empty\n'), defs)
    assert unbound == []


def test_negative_steps_assert_something():
    src = _steps_module()
    tree = ast.parse(src)
    for name in ("call_fails_with", "response_does_not_contain", "list_is_empty"):
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert any(isinstance(n, ast.Assert) for n in ast.walk(fn)), name


# ------------------------------------------------------------------ 5. packages
def _golden_proj(tmp_path, features):
    p = make_project(tmp_path)
    installer.set_baseline_mode(p.root, "golden")
    installer.install_golden(Project.load(p.root), name="VB", run_post=False)
    d = design_data()
    d["features"]["FEAT-01"].update(features.get("FEAT-01", {}))
    d["features"]["FEAT-02"].update(features.get("FEAT-02", {}))
    write_design(p.root, d)
    return Project.load(p.root)


def test_one_package_per_feat_by_default(tmp_path):
    proj = _golden_proj(tmp_path, {})
    assert golden.design_feature_package(proj, "FEAT-01") == "src/app/features/f001_messaging"
    assert golden.design_feature_package(proj, "FEAT-02") == "src/app/features/f002_unread_overview"
    with pytest.raises(EkitError, match="FEAT-nn"):
        golden.design_feature_package(proj, "001-x")
    with pytest.raises(EkitError, match="not under"):
        golden.design_feature_package(proj, "FEAT-09")


def test_package_key_groups_features_and_cli_honours_it(tmp_path, monkeypatch, capsys):
    proj = _golden_proj(tmp_path, {"FEAT-01": {"package": "chat"}, "FEAT-02": {"package": "chat"}})
    assert errors(proj, "design.schema") == []
    monkeypatch.chdir(proj.root)
    capsys.readouterr()
    assert ekit_main(["feature", "package", "FEAT-01"]) == 0
    assert capsys.readouterr().out.strip() == "src/app/features/chat"
    assert ekit_main(["feature", "package", "FEAT-02"]) == 0
    assert capsys.readouterr().out.strip() == "src/app/features/chat"


def test_package_key_must_be_a_snake_case_name(tmp_path):
    proj = _golden_proj(tmp_path, {"FEAT-01": {"package": "Bad-Name"}})
    assert any("package must be a snake_case" in e for e in errors(proj, "design.schema"))


# ------------------------------------------------------------------ 6. in-process adapters
INPROC = '''from typing import Protocol


class MessageStore(Protocol):
    def append(self, sender: str, body: str) -> int: ...
    def history(self, peer: str) -> list[str]: ...


class InMemoryMessageStore:
    def append(self, sender: str, body: str) -> int:
        return 1

    def history(self, peer: str) -> list[str]:
        return []


def get_message_store() -> MessageStore:
    return InMemoryMessageStore()
'''


def _ports_proj(tmp_path, text, **port):
    p = make_project(tmp_path)
    d = design_data()
    d["ports"][0].update(port)
    write_design(p.root, d)
    write_ports(p.root, text)
    return Project.load(p.root)


def test_single_class_port_fails_without_in_process_and_hints_at_the_fix(tmp_path):
    text = INPROC.replace("def get_message_store() -> MessageStore:\n    return InMemoryMessageStore()",
                          "def make_store() -> MessageStore:\n    return InMemoryMessageStore()\n\n\ndef get_message_store() -> MessageStore:\n    return make_store()")
    proj = _ports_proj(tmp_path, text)        # nothing declares or binds the single class as production
    errs = errors(proj, "design.ports_implemented")
    assert any("no adapter class" in e and "adapter: in-process" in e for e in errs)


def test_adapter_in_process_lets_one_class_satisfy_the_port(tmp_path):
    proj = _ports_proj(tmp_path, INPROC, adapter="in-process")
    assert errors(proj, "design.ports_implemented") == []
    assert not [m for lv, m in run(proj, "design.ports_implemented") if lv == "warn"]
    assert errors(proj, "design.ports") == []


def test_the_class_bound_by_the_dependency_function_is_the_production_adapter(tmp_path):
    proj = _ports_proj(tmp_path, INPROC)             # get_message_store() returns InMemoryMessageStore(): the production binding
    assert errors(proj, "design.ports_implemented") == []


def test_in_process_still_needs_a_class_with_every_method(tmp_path):
    proj = _ports_proj(tmp_path, INPROC.replace("    def history(self, peer: str) -> list[str]:\n        return []\n\n\ndef", "\n\ndef"),
                       adapter="in-process")
    assert any("no adapter class" in e or "lacks" in e for e in errors(proj, "design.ports_implemented"))


def test_adapter_value_is_validated(tmp_path):
    proj = _ports_proj(tmp_path, INPROC, adapter="somewhere")
    assert any("`adapter` must be one of" in e for e in errors(proj, "design.ports"))


# ------------------------------------------------------------------ 7. init warns instead of "Done."
def _capture(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(installer, "say", lines.append)
    return lines


def test_init_prints_done_with_warnings_when_uv_lock_failed(tmp_path, monkeypatch):
    p = make_project(tmp_path)
    installer.set_baseline_mode(p.root, "golden")
    lines = _capture(monkeypatch)
    monkeypatch.setattr(golden, "post_install", lambda g, root: ["!! `uv lock` failed (exit 1): no network. Fix and run it yourself."])
    installer.install_golden(Project.load(p.root), name="VB")
    assert installer.WARNINGS and "uv lock" in installer.WARNINGS[0]
    installer.next_steps(Project.load(p.root))
    text = "\n".join(lines)
    assert "Done with warnings" in text and "uv lock" in text and "Next step" in text and "\nDone. Stack" not in text
    assert installer.WARNINGS == []


def test_init_still_says_done_when_nothing_failed(tmp_path, monkeypatch):
    p = make_project(tmp_path)
    installer.set_baseline_mode(p.root, "golden")
    lines = _capture(monkeypatch)
    installer.install_golden(Project.load(p.root), name="VB")               # post-install skipped by env: a note, not a warning
    installer.next_steps(Project.load(p.root))
    text = "\n".join(lines)
    assert "Done. Stack" in text and "Done with warnings" not in text
