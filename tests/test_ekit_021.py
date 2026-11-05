"""ekit 0.2.1: gaps found on the first real project (intranet messenger).

* red froze a test whose `Then` had no step definition (the scenario failed earlier, at a stub);
* the red evidence was not committed, so the ledger's commit did not contain it;
* `ekit status` did not show the landing zone; two ADRs shared a number.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import yaml

from ekit import checks, kitsource, landing, stepbind
from ekit.project import Kit, Project, bundled_kit_dir, dump_yaml

FEATURE = """@SCN-001-01
Feature: Delivery
  Background:
    Given the messenger is running

  Scenario: A stranger cannot read a conversation
    Given peer "alpha" has a conversation with "beta"
    When peer "gamma" requests that conversation
    Then access is forbidden
    And the response is a problem document

  Scenario Outline: Message length is checked
    When peer "alpha" sends a message of <length> characters
    Then the response status is <status>

    Examples:
      | length | status |
      | 0      | 422    |
      | 10     | 201    |
"""

MODULE = '''from pathlib import Path
from pytest_bdd import scenarios, given, when, then, parsers
from .common_steps import *  # noqa: F403
scenarios(str(Path(__file__).parents[2] / "specs/001-chat/features/delivery.feature"))

@given(parsers.parse('peer "{a}" has a conversation with "{b}"'))
def conv(a, b):
    assert a and b

@when(parsers.parse('peer "{p}" requests that conversation'), target_fixture="resp")
def req(p):
    return p

@when(parsers.re(r'peer "(?P<p>\\w+)" sends a message of (?P<n>\\d+) characters'), target_fixture="resp")
def send(p, n):
    return n

@given("the response is a problem document")
def problem(resp):
    assert resp
'''


def _bdd_project(tmp_path, module=MODULE, conftest=True, common=True):
    (tmp_path / "specs/001-chat/features").mkdir(parents=True)
    (tmp_path / "specs/001-chat/features/delivery.feature").write_text(FEATURE, encoding="utf-8")
    acc = tmp_path / "tests/acceptance"
    acc.mkdir(parents=True)
    (acc / "test_delivery.py").write_text(module, encoding="utf-8")
    if conftest:
        (acc / "conftest.py").write_text('from pytest_bdd import given\n@given("the messenger is running")\n'
                                         'def running(client):\n    assert client\n', encoding="utf-8")
    if common:
        (acc / "common_steps.py").write_text('from pytest_bdd import then, parsers\n'
                                             '@then(parsers.parse("the response status is {status:d}"))\n'
                                             'def status(resp, status):\n    assert resp.status_code == status\n',
                                             encoding="utf-8")
    prof = SimpleNamespace(id="backend/fastapi", runs_bdd=True, bdd={"framework": "pytest-bdd"}, root=tmp_path,
                           data={"layout": {"acceptance_tests": "tests/acceptance"}})
    proj = SimpleNamespace(root=tmp_path, profiles=[prof], rel=lambda p: Path(p).resolve().relative_to(tmp_path).as_posix())
    return checks.GateContext(project=proj, feature_dir=tmp_path / "specs/001-chat")


W = {"dir": "specs/001-chat/features"}


# ------------------------------------------------------------------ steps bound to definitions
def test_feature_steps_expand_background_outlines_and_inherit_keywords():
    steps = stepbind.feature_steps(FEATURE)
    texts = [(s.kind, s.text) for s in steps]
    assert ("given", "the messenger is running") in texts                      # background, per scenario
    assert texts.count(("given", "the messenger is running")) == 3              # 1 scenario + 2 example rows
    assert ("then", "the response is a problem document") in texts             # And after Then is a Then
    assert ("when", 'peer "alpha" sends a message of 0 characters') in texts    # outline substituted
    assert ("then", "the response status is 201") in texts


def test_unbound_then_is_an_error_naming_the_step_and_a_keyword_mismatch_hint(tmp_path):
    out = checks.steps_bound(_bdd_project(tmp_path), W)
    errors = [f.message for f in out if f.level == "error"]
    assert len(errors) == 2
    assert 'Then "access is forbidden"' in errors[0] and "no step definition visible to tests/acceptance/test_delivery.py" in errors[0]
    assert 'And "the response is a problem document"' in errors[1] and "a @given definition matches" in errors[1]


def test_all_bound_passes_with_conftest_imports_parse_and_re(tmp_path):
    module = MODULE.replace('@given("the response is a problem document")', '@then("the response is a problem document")')
    module += '\n@then("access is forbidden")\ndef forbidden(resp):\n    assert resp.status_code == 403\n'
    assert checks.steps_bound(_bdd_project(tmp_path, module=module), W) == []


def test_definitions_in_an_unimported_module_or_missing_conftest_are_not_visible(tmp_path):
    module = MODULE.replace("from .common_steps import *  # noqa: F403\n", "")
    out = checks.steps_bound(_bdd_project(tmp_path, module=module, conftest=False), W)
    msgs = " | ".join(f.message for f in out if f.level == "error")
    assert '"the messenger is running"' in msgs and '"the response status is 422"' in msgs


def test_parse_converters_are_respected():
    rx = stepbind._parse_to_regex("the response status is {status:d}")
    import re
    assert re.fullmatch(rx, "the response status is 201") and not re.fullmatch(rx, "the response status is ok")
    assert re.fullmatch(stepbind._parse_to_regex('a {{literal}} and "{name}"'), 'a {literal} and "x y"')


def test_dynamic_patterns_downgrade_to_warnings(tmp_path):
    module = MODULE + '\nPATTERN = "access is forbidden"\n@then(PATTERN)\ndef forbidden(resp):\n    assert resp\n'
    out = checks.steps_bound(_bdd_project(tmp_path, module=module), W)
    assert {f.level for f in out} == {"warn", "info"}


def test_other_frameworks_get_an_info_line(tmp_path):
    ctx = _bdd_project(tmp_path)
    ctx.project.profiles[0].bdd = {"framework": "cucumber-jvm"}
    assert [f.level for f in checks.steps_bound(ctx, W)] == ["info"]


# ------------------------------------------------------------------ red evidence committed
def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@x", "PATH": __import__("os").environ["PATH"], "HOME": str(root)})


def _ledger(ctx, root):
    files = ["specs/001-chat/features/delivery.feature", "tests/acceptance/test_delivery.py"]
    fp = {rel: checks._sha(root / rel) for rel in files}
    dump_yaml({"feature": "001-chat", "entries": [{"phase": "red", "scenarios": {}, "fingerprints": fp}]},
              root / ".ekit/ledger/001-chat.yaml")


def test_red_committed_requires_the_recorded_files_and_ledger_in_git(tmp_path):
    ctx = _bdd_project(tmp_path)
    _ledger(ctx, tmp_path)
    assert [f.level for f in checks.red_committed(ctx, {})] == ["warn"]          # not a git repo
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "tests")
    _git(tmp_path, "commit", "-qm", "tests only")
    msgs = [f.message for f in checks.red_committed(ctx, {})]
    assert any("specs/001-chat/features/delivery.feature" in m for m in msgs)     # feature file never committed
    assert any("ledger" in m and "not committed" in m for m in msgs)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "red")
    assert checks.red_committed(ctx, {}) == []
    (tmp_path / "tests/acceptance/test_delivery.py").write_text(MODULE + "\n# later edit\n", encoding="utf-8")
    assert checks.red_committed(ctx, {}) == []        # the recorded version is in history; GREEN-TESTS-UNCHANGED judges edits


# ------------------------------------------------------------------ ADR numbers
def test_duplicate_adr_numbers_are_an_error_with_the_next_free_number(tmp_path):
    adr = tmp_path / "docs/adr"
    adr.mkdir(parents=True)
    for name in ("0001-record-architecture-decisions.md", "0002-stack.md", "0001-trusted-intranet-chat.md", "README.md"):
        (adr / name).write_text("# x\n", encoding="utf-8")
    ctx = checks.GateContext(project=SimpleNamespace(root=tmp_path, rel=str))
    out = checks.adr_unique(ctx, {"dir": "docs/adr"})
    assert len(out) == 1 and "0001" in out[0].message and "next free number: 0003" in out[0].message
    (adr / "0001-trusted-intranet-chat.md").rename(adr / "0003-trusted-intranet-chat.md")
    assert checks.adr_unique(ctx, {"dir": "docs/adr"}) == []


# ------------------------------------------------------------------ landing zone in status
def _real_project(tmp_path):
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": "fastapi-react"}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    (root / "docs/engineering").mkdir(parents=True)
    (root / landing.CONFORMANCE).write_text("| NFR | Title | Status | Evidence | ADR |\n", encoding="utf-8")
    (root / "specs/000-landing-zone/features").mkdir(parents=True)
    (root / "specs/000-landing-zone/features/health.feature").write_text(
        "@SCN-000-01\nFeature: Health\n  Scenario: up\n    Given the app\n", encoding="utf-8")
    return root


def test_landing_zone_record_goes_stale_when_its_evidence_changes(tmp_path):
    root = _real_project(tmp_path)
    p = Project.load(root)
    assert landing.status(p)[0] == "not run"
    assert landing.record(p) is not None
    assert landing.record(p) is None                                              # unchanged: no rewrite
    assert landing.status(p)[0] == "passed"
    (root / landing.CONFORMANCE).write_text("changed\n", encoding="utf-8")
    state, detail = landing.status(Project.load(root))
    assert state == "stale" and "baseline-conformance.md changed" in detail and "ekit gate baseline" in detail


def test_landing_zone_goes_stale_when_a_wave_activates_a_profile(tmp_path):
    root = _real_project(tmp_path)
    dump_yaml({"waves": [{"id": "W1", "profiles": ["backend"], "scope": []}], "current": "W1"}, root / ".ekit/waves.yaml")
    landing.record(Project.load(root))
    dump_yaml({"waves": [{"id": "W1", "profiles": ["backend"], "scope": []}, {"id": "W2", "scope": []}],
               "current": "W2"}, root / ".ekit/waves.yaml")
    state, detail = landing.status(Project.load(root))
    assert state == "stale" and "newly active: frontend/react" in detail


def test_status_shows_the_landing_zone_and_keeps_000_out_of_features(tmp_path):
    import sys
    root = _real_project(tmp_path)
    landing.record(Project.load(root))
    out = subprocess.run([sys.executable, "-m", "ekit", "status"], cwd=root, capture_output=True, text=True,
                         env={"PYTHONPATH": str(Path(checks.__file__).parents[1]), "PATH": __import__("os").environ["PATH"]}).stdout
    assert "Landing zone\n  baseline: passed" in out
    assert "000-landing-zone: 1 smoke scenario(s) @SCN-000-01" in out
    features = out.split("Features", 1)[1]
    assert "000-landing-zone" not in features and "(none yet)" in features


# ------------------------------------------------------------------ the kit wires the new checks
def test_bundled_kit_wires_the_021_checks():
    pol = Kit.load(bundled_kit_dir()).policy()["spec"]["gates"]
    by_gate = {g["id"]: {c["id"] for c in g["checks"]} for g in pol}
    assert "RED-STEPS-BOUND" in by_gate["red"] and "GREEN-STEPS-BOUND" in by_gate["green"]
    assert "REDREC-COMMITTED" in by_gate["red-recorded"] and "GREEN-RED-COMMITTED" in by_gate["green"]
    assert "BASE-ADR-UNIQUE" in by_gate["baseline"] and "PLAN-ADR-UNIQUE" in by_gate["plan"]
    assert next(g for g in pol if g["id"] == "baseline")["record"] == ".ekit/ledger/baseline.yaml"
    assert yaml.safe_load((bundled_kit_dir() / "kit.yaml").read_text())["requires"]["ekit"] == ">=0.2.5,<0.3"
