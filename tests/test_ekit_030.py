"""ekit 0.3.0: golden landing zone for fastapi-jinja, and structural fixes for the 0.2.1–0.2.5 bug classes.

Each 0.2.x release fixed a gap found on the same real project (intranet messenger, fastapi-jinja)
by detecting it in a gate or by rewording a command. 0.3.0 removes the conditions that produced
them:

  0.2.1 unbound step hidden behind an early failure  -> shared step library in the frozen conftest
  0.2.1 two ADRs numbered 0001                       -> `ekit adr new` allocates the number
  0.2.2 KeyError from a shared dict read as a "red"  -> ScenarioContext + RED-STATE-TYPED; the error
                                                        it raises is named so RED-CLEAN-FAILURE sees it
  0.2.2/0.2.3 agent wandered into src while fixing   -> golden core frozen; helpers covered by
        a test; helpers/conftest not fingerprinted      GREEN-GOLDEN-INTACT (GREEN-TESTS-UNCHANGED skipped them)
  0.2.4 fix-red reverted the whole source tree       -> one package per feature; fix-red reverts only it
  0.2.5 agent took an example name as the feature    -> `ekit feature current` decides; no example names;
                                                        RED-NO-EXEMPLAR for the reference slice
  (pre) constitution I–VIII protected only by review -> deterministic ratify + BASE-CONSTITUTION

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ekit import checks, constitution, features, fixred, freeze, gherkin, golden, installer, kitsource, landing
from ekit import stepbind, stepscan
from ekit.cli import main as ekit_main
from ekit.project import EkitError, Kit, Project, bundled_kit_dir, dump_yaml

KIT = bundled_kit_dir()
GOLDEN_DIR = KIT / "golden" / "fastapi-jinja"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _no_post_install(monkeypatch):
    monkeypatch.setenv(golden.SKIP_POST_INSTALL_ENV, "1")    # `uv lock` needs network; never in unit tests


def _bare(tmp_path, stack="fastapi-jinja") -> Path:
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": stack}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    return root


def _golden_project(tmp_path, name="Demo Bank") -> Project:
    root = _bare(tmp_path)
    installer.set_baseline_mode(root, "golden")
    installer.install_golden(Project.load(root), name=name, run_post=False)
    return Project.load(root)


def _ctx(project: Project, feature: str | None = None) -> checks.GateContext:
    fd = (project.root / "specs" / feature) if feature else None
    return checks.GateContext(project=project, feature_dir=fd)


# ===================================================================== kit wiring
def test_kit_offers_golden_for_fastapi_jinja_only_and_policy_wires_the_new_checks():
    kit = Kit.load(KIT)
    assert kit.version == "0.3.0" and kit.manifest["requires"]["ekit"] == ">=0.3.0,<0.4"
    assert golden.for_stack(kit, "fastapi-jinja").version == "1.0.0"
    assert all(golden.for_stack(kit, s) is None for s in kit.stacks if s != "fastapi-jinja")
    ids = {c["id"] for g in kit.policy()["spec"]["gates"] for c in g["checks"]}
    assert {"BASE-CONSTITUTION", "BASE-GOLDEN-INTACT", "RED-STATE-TYPED", "RED-NO-EXEMPLAR",
            "GREEN-GOLDEN-INTACT", "GREEN-NO-EXEMPLAR"} <= ids
    types = {c["type"] for g in kit.policy()["spec"]["gates"] for c in g["checks"]}
    assert types <= set(checks.REGISTRY)


def test_golden_manifest_is_consistent_with_its_tree():
    g = golden.for_stack(Kit.load(KIT), "fastapi-jinja")
    tree = {p.relative_to(g.tree).as_posix() for p in g.tree.rglob("*") if p.is_file()}
    assert set(g.manifest["render"]) <= tree and set(g.manifest["rename"]) <= tree
    files = set(golden.materialize(g, "X"))
    for pat in g.frozen:                                     # every frozen pattern protects something real
        assert any(golden.matches(f, [pat]) for f in files), pat
    # the 0.2.2/0.2.3 gap: helpers and conftest were not fingerprinted by GREEN-TESTS-UNCHANGED
    assert golden.matches("tests/acceptance/conftest.py", g.frozen)
    assert golden.matches("tests/acceptance/support/context.py", g.frozen)
    assert golden.matches("tests/conftest.py", g.frozen)
    assert not golden.matches("src/app/features/registry.py", g.frozen)          # the seam stays editable
    assert not golden.matches("src/app/features/f003_chat/api.py", g.frozen)
    profile_paths = set()
    for pid in Kit.load(KIT).stacks["fastapi-jinja"]["profiles"]:
        profile_paths |= set((Kit.load(KIT).profile_data(pid).get("layout") or {}).get("required_paths") or [])
    missing = {p for p in profile_paths if not any(f == p or f.startswith(p.rstrip("/") + "/") for f in files)}
    assert missing == {"uv.lock"}                            # generated on the user's machine (post_install)


def test_golden_python_parses_and_has_no_untyped_state():
    g = golden.for_stack(Kit.load(KIT), "fastapi-jinja")
    for f in g.tree.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        ast.parse(src, str(f))
        assert checks._untyped_state_uses(src) == [], f
        res = stepscan.scan_source(src)
        assert not res.steps and not res.abs_paths, f


def test_golden_scenarios_parse_are_unique_and_every_step_is_bound():
    g = golden.for_stack(Kit.load(KIT), "fastapi-jinja")
    ids: list[str] = []
    for feat in sorted(g.tree.glob("specs/*/features/*.feature")):
        ff = gherkin.parse_feature(feat)
        assert not ff.errors, ff.errors
        for s in ff.scenarios:
            got = gherkin.scn_tags(s.tags)
            assert len(got) == 1 and got[0].startswith("SCN-000-"), (feat, s.name)
            ids += got
        binders = [m for m in g.tree.glob("tests/acceptance/test_*.py") if feat.name in m.read_text(encoding="utf-8")]
        assert len(binders) == 1, feat
        defs, dynamic = stepbind.visible_definitions(binders[0], g.tree, {})
        assert dynamic == 0
        unbound = stepbind.unbound(stepbind.feature_steps(feat.read_text(encoding="utf-8")), defs)
        assert unbound == [], [(s.keyword, s.text) for s in unbound]
    assert len(ids) == len(set(ids))


def test_shared_step_patterns_do_not_shadow_each_other():
    g = golden.for_stack(Kit.load(KIT), "fastapi-jinja")
    defs = stepbind.scan_definitions((g.tree / "tests/acceptance/conftest.py").read_text(encoding="utf-8")).defs
    samples = {
        'I GET "/x"': 1, 'I GET "/x" with header "A" set to "b"': 1, 'I POST JSON {"a": 1} to "/x"': 1,
        'I POST the form "a=1" to "/x"': 1, "the response status is 200": 1,
        'the response header "A" equals "b"': 1, 'the response header "A" is present': 1,
    }
    for text, want in samples.items():
        hits = [d for d in defs if d.pattern is not None and d.pattern.fullmatch(text)]
        assert len(hits) == want, (text, [d.source for d in hits])


# ===================================================================== install
def test_install_renders_renames_fingerprints_ratifies_and_freezes(tmp_path):
    project = _golden_project(tmp_path)
    root = project.root
    assert (root / ".gitignore").is_file() and (root / ".python-version").read_text().strip() == "3.12"
    assert not list(root.glob("dot_*"))
    assert 'name = "demo-bank"' in (root / "pyproject.toml").read_text()
    assert "__PROJECT_" not in (root / "src/app/core/settings.py").read_text()
    lock = golden.read_lock(root)
    assert lock["version"] == "1.0.0" and "src/app/main.py" in lock["files"] and lock["project_name"] == "Demo Bank"
    assert project.config["baseline"] == {"mode": "golden", "golden_version": "1.0.0"}
    # constitution: ratified without a model, principles intact
    text = (root / constitution.MEMORY).read_text()
    assert "# Demo Bank Constitution" in text and not constitution.placeholders(text)
    assert constitution.principles_drift(project)[0] == "intact"
    # golden core denied to the agent's edit tools; changing it is a person's command
    edit = json.loads((root / "opencode.json").read_text())["permission"]["edit"]
    assert edit["src/app/core/**"] == "deny" and edit["tests/acceptance/conftest.py"] == "deny"
    assert "src/app/features/registry.py" not in edit
    assert {"ekit baseline unfreeze*", "ekit baseline accept*", "ekit baseline install*"} <= set(freeze.ALWAYS_BASH)


def test_installed_golden_passes_the_static_baseline_checks(tmp_path):
    project = _golden_project(tmp_path)
    ctx = _ctx(project)
    conformance = checks.nfr_conformance(ctx, {"file": "docs/engineering/baseline-conformance.md", "scope": "platform"})
    assert [f for f in conformance if f.level != "info"] == []
    assert checks.golden_intact(ctx, {}) == []
    assert checks.constitution_intact(ctx, {}) == []
    assert checks.adr_unique(ctx, {"dir": "docs/adr"}) == []
    missing = [f.message for f in checks.required_paths(ctx, {})]
    assert len(missing) == 1 and "uv.lock" in missing[0]     # until `uv lock` runs on the user's machine


def test_agents_block_carries_the_golden_rules(tmp_path):
    project = _golden_project(tmp_path)
    block = installer.render_agents_block(project)
    assert "Golden landing zone (fastapi-jinja 1.0.0)" in block and "ekit feature package" in block
    assert "ekit adr new" in block and "ekit baseline unfreeze|accept|install" in block


def test_install_refuses_a_project_that_already_has_code(tmp_path):
    root = _bare(tmp_path)
    (root / "src/app").mkdir(parents=True)
    (root / "src/app/main.py").write_text("app = None\n", encoding="utf-8")
    installer.set_baseline_mode(root, "golden")
    with pytest.raises(EkitError, match="greenfield"):
        golden.install(Project.load(root), project_name="x", run_post=False)
    assert golden.read_lock(root) is None


def test_choose_baseline_defaults_and_refusals():
    kit = Kit.load(KIT)
    assert installer.choose_baseline(None, kit, "fastapi-jinja", "greenfield", False) == "golden"
    assert installer.choose_baseline(None, kit, "fastapi-jinja", "brownfield", False) == "generate"
    assert installer.choose_baseline(None, kit, "springboot-react", "greenfield", False) == "generate"
    with pytest.raises(EkitError):
        installer.choose_baseline("golden", kit, "springboot-react", "greenfield", False)
    with pytest.raises(EkitError):
        installer.choose_baseline("golden", kit, "fastapi-jinja", "brownfield", False)


# ===================================================================== core drift, accept
def test_drift_catches_changed_deleted_and_added_core_files_and_accept_records_them(tmp_path):
    project = _golden_project(tmp_path)
    root = project.root
    (root / "tests/acceptance/conftest.py").write_text("# simplified\n", encoding="utf-8")
    (root / "src/app/core/logging.py").unlink()
    (root / "src/app/core/shortcut.py").write_text("X = 1\n", encoding="utf-8")
    (root / "src/app/features/registry.py").write_text("# seams may change\n", encoding="utf-8")
    kinds = {(d.rel, d.kind) for d in golden.drift(root)}
    assert kinds == {("tests/acceptance/conftest.py", "changed"), ("src/app/core/logging.py", "deleted"),
                     ("src/app/core/shortcut.py", "added")}
    assert len([f for f in checks.golden_intact(_ctx(project), {}) if f.level == "error"]) == 3

    freeze.unfreeze_baseline(root, "ADR-0003: new logging backend")
    assert "src/app/core/**" not in json.loads((root / "opencode.json").read_text())["permission"]["edit"]
    with pytest.raises(EkitError):
        golden.accept(root, "  ")
    changed = golden.accept(root, "reviewed in PR 42")
    freeze.freeze_baseline(root, golden.read_lock(root)["frozen"])
    assert len(changed) == 3 and golden.drift(root) == []
    assert golden.read_lock(root)["history"][-1]["reason"] == "reviewed in PR 42"
    assert freeze.load_state(root)["history"][-1]["action"] == "unfreeze-baseline"
    assert json.loads((root / "opencode.json").read_text())["permission"]["edit"]["src/app/core/**"] == "deny"


def test_non_golden_projects_are_unaffected(tmp_path):
    project = Project.load(_bare(tmp_path))
    ctx = _ctx(project)
    assert [f.level for f in checks.golden_intact(ctx, {})] == ["info"]
    assert [f.level for f in checks.no_exemplar(ctx, {"dir": "specs"})] == ["info"]


# ===================================================================== upgrade: 3-way merge
def _new_revision(tmp_path) -> golden.Golden:
    new_dir = tmp_path / "golden-new"
    shutil.copytree(GOLDEN_DIR, new_dir)
    m = yaml.safe_load((new_dir / "golden.yaml").read_text())
    m["metadata"]["version"] = "1.1.0"
    (new_dir / "golden.yaml").write_text(yaml.safe_dump(m, sort_keys=False))
    t = new_dir / "tree"
    # 1) a core file the project never touched
    (t / "src/app/core/http.py").write_text((t / "src/app/core/http.py").read_text() + "\n# rev 1.1.0\n")
    # 2) the seam the project edited, changed elsewhere in the file
    reg = (t / "src/app/features/registry.py").read_text()
    (t / "src/app/features/registry.py").write_text(reg.replace('"""Seam:', '"""Seam (1.1.0):', 1))
    # 3) a line both sides change
    (t / "src/app/core/i18n.py").write_text((t / "src/app/core/i18n.py").read_text().replace(
        '"home.title": "Welcome"', '"home.title": "Welcome!"'))
    # 4) a new file
    (t / "src/app/core/ratelimit.py").write_text('"""new in 1.1.0"""\n')
    return golden.Golden(new_dir, m)


def test_upgrade_merges_three_ways_and_blocks_on_conflicts_until_resolved_and_accepted(tmp_path):
    project = _golden_project(tmp_path)
    root = project.root
    reg = root / "src/app/features/registry.py"
    reg.write_text(reg.read_text().replace("    return []\n\n\ndef web_routers",
                                           "    return []  # feature routers go here\n\n\ndef web_routers", 1))
    i18n = root / "src/app/core/i18n.py"                      # a person changed the core (accepted)
    i18n.write_text(i18n.read_text().replace('"home.title": "Welcome"', '"home.title": "Hello"'))
    golden.accept(root, "branding")

    new = _new_revision(tmp_path)
    report = golden.merge_upgrade(root, GOLDEN_DIR, new)
    assert report["updated"] == ["src/app/core/http.py"]
    assert report["merged"] == ["src/app/features/registry.py"]
    assert report["conflicts"] == ["src/app/core/i18n.py"]
    assert report["added"] == ["src/app/core/ratelimit.py"]
    text = reg.read_text()
    assert "Seam (1.1.0):" in text and "# feature routers go here" in text
    assert "<<<<<<< project" in i18n.read_text()
    lock = golden.read_lock(root)
    assert lock["version"] == "1.1.0" and lock["conflicts"] == ["src/app/core/i18n.py"]
    assert [(d.rel, d.kind) for d in golden.drift(root)] == [("src/app/core/i18n.py", "conflict")]
    with pytest.raises(EkitError, match="conflict markers"):
        golden.accept(root, "too early")

    i18n.write_text(i18n.read_text().split("<<<<<<< project\n")[0] + '        "home.title": "Hello!",\n'
                    + i18n.read_text().split(">>>>>>> golden-new\n")[1])
    assert [d.kind for d in golden.drift(root)] == ["changed"]
    golden.accept(root, "kept branding, took punctuation")
    assert golden.drift(root) == [] and golden.read_lock(root)["conflicts"] == []
    assert golden.merge_upgrade(root, GOLDEN_DIR, new) == {k: [] for k in report}    # idempotent


# ===================================================================== 0.2.2: typed state
FEATURE = """Feature: Chat
  Background:
    Given the application is running

  @SCN-001-01 @AC-001
  Scenario: s
    When I GET "/api/v1/chat"
    Then the response status is 200
"""

DICT_MODULE = '''from pytest_bdd import given, scenarios, then
from tests.acceptance.support import feature_file
scenarios(feature_file("001-chat", "chat.feature"))


@given("a thing")
def a_thing(scenario_state):
    scenario_state["x"] = 1


@then("it is read")
def read(scenario_state):
    assert scenario_state["ids"]
'''

CTX_MODULE = '''from pytest_bdd import given, scenarios, then
from tests.acceptance.support import ScenarioContext, feature_file
scenarios(feature_file("001-chat", "chat.feature"))


@given("a thing")
def a_thing(ctx: ScenarioContext) -> None:
    ctx.remember("x", 1)


@then("it is read")
def read(ctx: ScenarioContext) -> None:
    assert ctx.recall("x") == 1
'''


def _feature(project: Project, module: str, name="001-chat") -> None:
    d = project.root / "specs" / name / "features"
    d.mkdir(parents=True)
    (d / "chat.feature").write_text(FEATURE.replace("001", name[:3]), encoding="utf-8")
    (project.root / "tests/acceptance" / f"test_{name[:3]}_chat.py").write_text(
        module.replace("001-chat", name), encoding="utf-8")


def test_red_rejects_a_shared_dict_and_accepts_scenario_context(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, DICT_MODULE)
    out = checks.typed_state(_ctx(project, "001-chat"), {"dir": "specs/001-chat/features"})
    assert len(out) == 2 and all(f.level == "error" and "ScenarioContext" in f.message for f in out)
    (project.root / "tests/acceptance/test_001_chat.py").write_text(CTX_MODULE, encoding="utf-8")
    assert checks.typed_state(_ctx(project, "001-chat"), {"dir": "specs/001-chat/features"}) == []


def test_dict_fixture_definitions_are_flagged():
    src = "import pytest\n@pytest.fixture\ndef scenario_state():\n    return {}\n"
    assert checks._untyped_state_uses(src) == [(3, "fixture `scenario_state` returns a dict")]


def test_missing_scenario_state_is_recognised_and_rejected_as_broken_glue(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    report = project.root / "reports/cucumber-backend.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    msg = ("tests/acceptance/test_001_chat.py:12: in read\nE   tests.acceptance.support.context."
           "MissingScenarioStateError: 'ids' was never set in this scenario\n")
    report.write_text(json.dumps([{"name": "Chat", "tags": [], "elements": [{"type": "scenario",
                      "tags": [{"name": "SCN-001-01"}], "steps": [{"result": {"status": "failed", "error_message": msg}}]}]}]))
    el = gherkin.read_cucumber_elements([report])["SCN-001-01"][0]
    assert gherkin.failure_exception(el) == "MissingScenarioStateError"   # *Error: the reader sees it
    out = checks.clean_failure(_ctx(project, "001-chat"), {"dir": "specs/001-chat/features"})
    assert len(out) == 1 and "THIS scenario" in out[0].message


# ===================================================================== 0.2.5: no exemplar, no guessing
def test_features_must_not_use_or_be_the_reference_slice(tmp_path):
    project = _golden_project(tmp_path)
    _feature(project, CTX_MODULE)
    w = {"dir": "specs/001-chat/features"}
    assert checks.no_exemplar(_ctx(project, "001-chat"), w) == []
    pkg = project.root / "src/app/features/f001_chat"
    pkg.mkdir(parents=True)
    (pkg / "api.py").write_text("from app.features.f000_reference.service import greet\n", encoding="utf-8")
    out = checks.no_exemplar(_ctx(project, "001-chat"), w)
    assert len(out) == 1 and "f001_chat/api.py" in out[0].message
    out = checks.no_exemplar(_ctx(project, "000-reference-slice"), {"dir": "specs/000-reference-slice/features"})
    assert out and "is the reference slice" in out[0].message


def test_feature_current_decides_deterministically_and_never_picks_an_example(tmp_path, monkeypatch):
    project = _golden_project(tmp_path)
    root = project.root
    monkeypatch.delenv("SPECIFY_FEATURE", raising=False)
    for name in ("001-chat", "002-files"):
        (root / "specs" / name / "features").mkdir(parents=True)
        (root / "specs" / name / "features/a.feature").write_text("Feature: x\n", encoding="utf-8")
    dump_yaml({"feature": "001-chat", "entries": [{"phase": "red"}]}, root / ".ekit/ledger/001-chat.yaml")
    assert features.current(project, None, phase="red") == "002-files"
    assert features.current(project, None, phase="implement") == "001-chat"
    assert features.current(project, "002", phase="implement") == "002-files"          # explicit wins
    assert features.current(project, "$ARGUMENTS", phase="red") == "002-files"          # unexpanded = empty
    for bad, why in (("001-user-admin", "Real features: 001-chat, 002-files"), ("000-reference-slice", "never a feature"),
                     ("000", "never a feature")):
        with pytest.raises(EkitError, match=why):
            features.current(project, bad, phase="any")
    with pytest.raises(EkitError, match="Several features"):
        features.current(project, None, phase="any")


def test_cli_feature_current_package_and_adr_new(tmp_path, monkeypatch, capsys):
    project = _golden_project(tmp_path)
    (project.root / "specs/003-conversation-history/features").mkdir(parents=True)
    monkeypatch.chdir(project.root)
    monkeypatch.delenv("SPECIFY_FEATURE", raising=False)
    capsys.readouterr()
    assert ekit_main(["feature", "current"]) == 0
    assert capsys.readouterr().out.strip() == "003-conversation-history"
    assert ekit_main(["feature", "package", "003"]) == 0
    assert capsys.readouterr().out.strip() == "src/app/features/f003_conversation_history"
    assert ekit_main(["feature", "current", "001-user-admin"]) == 2
    assert ekit_main(["adr", "new", "Use", "Postgres"]) == 0                          # 0001, 0002 ship with golden
    assert capsys.readouterr().out.strip().endswith("docs/adr/0003-use-postgres.md")
    assert checks.adr_unique(_ctx(project), {"dir": "docs/adr"}) == []


# ===================================================================== 0.2.4: fix-red scope
def test_fix_red_reverts_only_the_feature_package_in_golden_projects(tmp_path):
    project = _golden_project(tmp_path)
    assert fixred._revert_scope(project, "003-chat") == ["src/app", "src/app/web"]   # no package yet: as in 0.2.x
    (project.root / "src/app/features/f003_chat").mkdir(parents=True)
    assert fixred._revert_scope(project, "003-chat") == ["src/app/features/f003_chat"]


# ===================================================================== constitution
def test_constitution_check_catches_a_reworded_principle_and_ratify_is_idempotent(tmp_path):
    project = _golden_project(tmp_path)
    mem = project.root / constitution.MEMORY
    assert constitution.ratify(project) == []
    mem.write_text(mem.read_text().replace("written and observed failing", "written"), encoding="utf-8")
    state, details = constitution.principles_drift(project)
    assert state == "changed" and details == ["principle IV differs from the kit template"]
    out = checks.constitution_intact(_ctx(project), {})
    assert out and out[0].level == "error"


def test_constitution_allows_project_principles_ix_plus(tmp_path):
    project = _golden_project(tmp_path)
    mem = project.root / constitution.MEMORY
    text = mem.read_text().replace("## Technology Stack",
                                   "### IX. Money as integers\nAmounts are integer minor units.\n\n## Technology Stack")
    mem.write_text(text, encoding="utf-8")
    assert constitution.principles_drift(project)[0] == "intact"


def test_unratified_constitution_is_a_warning_not_a_failure(tmp_path):
    project = Project.load(_bare(tmp_path))
    out = checks.constitution_intact(_ctx(project), {})
    assert out and all(f.level == "warn" for f in out)
    notes = constitution.ratify(project, name="Plain")
    assert notes and constitution.principles_drift(project)[0] == "intact"


# ===================================================================== evidence
def test_baseline_record_names_its_provenance_and_goes_stale_on_accept(tmp_path):
    project = _golden_project(tmp_path)
    _git(project.root, "add", "-A")
    _git(project.root, "commit", "-qm", "golden")
    landing.record(project)
    rec = yaml.safe_load((project.root / landing.RECORD).read_text())
    assert rec["baseline_mode"] == "golden" and rec["golden"] == {"stack": "fastapi-jinja", "version": "1.0.0"}
    assert landing.status(project)[0] == "passed" and "golden 1.0.0" in landing.status(project)[1]
    (project.root / "src/app/core/http.py").write_text("# changed\n", encoding="utf-8")
    golden.accept(project.root, "reviewed")
    state, detail = landing.status(project)
    assert state == "stale" and "re-accepted" in detail
