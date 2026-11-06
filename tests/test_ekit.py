"""Unit tests for parsers, checks and the kit itself.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from ekit import gherkin
from ekit.checks import ac_definitions, br_definitions, parse_conformance
from ekit.kitsource import digest
from ekit.project import Kit, bundled_kit_dir

KIT = bundled_kit_dir()


def test_every_kit_yaml_parses():
    for p in KIT.rglob("*.y*ml"):
        yaml.safe_load(p.read_text(encoding="utf-8"))


def test_every_stack_resolves_to_existing_profiles_and_known_nfr_controls():
    kit = Kit.load(KIT)
    nfr_ids = {n["id"] for n in kit.nfr_catalog()["nfrs"]}
    for sid, stack in kit.stacks.items():
        roles = set()
        for pid in stack["profiles"]:
            data = kit.profile_data(pid)
            roles.add(data["metadata"]["role"])
            assert set(data.get("controls") or {}) <= nfr_ids, f"{pid} controls unknown NFR ids"
            for name, argv in (data.get("commands") or {}).items():
                assert isinstance(argv, list) and argv, f"{pid}:{name} must be an argv list"
        assert roles == {"backend", "frontend"}, sid
        assert set(stack["roots"]) == roles, sid


def test_policy_only_uses_registered_check_types():
    from ekit.checks import REGISTRY
    policy = Kit.load(KIT).policy()
    for gate in policy["spec"]["gates"]:
        for chk in gate["checks"]:
            assert chk["type"] in REGISTRY, chk


def test_extension_and_preset_files_exist():
    ext = yaml.safe_load((KIT / "extension/esdlc/extension.yml").read_text())
    for item in ext["provides"]["commands"] + ext["provides"]["templates"]:
        assert (KIT / "extension/esdlc" / item["file"]).is_file(), item
        if "templates/" in item["file"]:
            assert Path(item["file"]).stem == item["name"], "Spec Kit resolves templates by <name>.md"
    preset = yaml.safe_load((KIT / "preset/enterprise-baseline/preset.yml").read_text())
    for item in preset["provides"]["templates"]:
        assert (KIT / "preset/enterprise-baseline" / item["file"]).is_file(), item
        if item.get("strategy") == "wrap":
            assert "{CORE_TEMPLATE}" in (KIT / "preset/enterprise-baseline" / item["file"]).read_text()


def test_gherkin_parser_tags_outline_and_rule(tmp_path):
    f = tmp_path / "x.feature"
    f.write_text(
        "@FEAT-01\nFeature: F\n\n  Rule: r\n  @SCN-001-01 @AC-001\n  Scenario: a\n    Given x\n\n"
        "  @SCN-001-02 @AC-002\n  Scenario Outline: b\n    Given <n>\n    @ex-tag\n    Examples:\n      | n |\n      | 1 |\n",
        encoding="utf-8",
    )
    ff = gherkin.parse_feature(f)
    assert not ff.errors
    assert [s.name for s in ff.scenarios] == ["a", "b"]
    assert gherkin.scn_tags(ff.scenarios[1].tags) == ["SCN-001-02"]
    assert "@FEAT-01" in ff.scenarios[0].tags and "@ex-tag" not in ff.scenarios[1].tags


def test_cucumber_report_aggregates_outline_examples(tmp_path):
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps([{"tags": [], "elements": [
        {"type": "scenario", "tags": [{"name": "@SCN-001-02"}], "steps": [{"result": {"status": "passed"}}]},
        {"type": "scenario", "tags": [{"name": "@SCN-001-02"}], "steps": [{"result": {"status": "failed"}}]},
        {"type": "background", "steps": [{"result": {"status": "failed"}}]},
    ]}]))
    res = gherkin.read_cucumber_reports([rep])
    assert gherkin.aggregate(res["SCN-001-02"]) == "failed"


def test_pytest_bdd_report_shape_without_at_sign(tmp_path):
    """Real pytest-bdd (src/pytest_bdd/cucumber_json.py) writes tag names WITHOUT '@', keyword
    'Scenario', type 'scenario', one element per executed example, failed scenarios as 'failed'."""
    rep = tmp_path / "cucumber-backend.json"
    rep.write_text(json.dumps([{
        "keyword": "Feature", "uri": "features/a.feature", "name": "A", "id": "features/a.feature",
        "line": 2, "description": "", "language": "en",
        "tags": [{"name": "FEAT-01", "line": 1}],
        "elements": [
            {"keyword": "Scenario", "id": "test_a", "name": "a", "line": 5, "description": "",
             "tags": [{"name": "SCN-001-01", "line": 4}, {"name": "AC-001", "line": 4}], "type": "scenario",
             "steps": [{"keyword": "Given", "name": "x", "line": 6, "match": {"location": ""},
                        "result": {"status": "failed", "duration": 1, "error_message": "boom"}}]},
            {"keyword": "Scenario Outline", "id": "test_b", "name": "b", "line": 9, "description": "",
             "tags": [{"name": "SCN-001-02", "line": 8}], "type": "scenario",
             "steps": [{"keyword": "Given", "name": "y", "line": 10, "match": {"location": ""},
                        "result": {"status": "passed", "duration": 1}}]},
        ]}]))
    res = gherkin.read_cucumber_reports([rep])
    assert set(res) == {"SCN-001-01", "SCN-001-02"}
    assert gherkin.aggregate(res["SCN-001-01"]) == "failed"
    assert gherkin.aggregate(res["SCN-001-02"]) == "passed"


def test_id_definitions_and_conformance_rows():
    assert br_definitions("| BR-001 | x |\n| **BR-002** | y |\ntext BR-009") == ["BR-001", "BR-002"]
    assert ac_definitions("- **AC-001** (BR-001): a\n* AC-002: b\nsee AC-003") == ["AC-001", "AC-002"]
    rows = parse_conformance("| SEC-01 | Auth | Addressed | sec.py | |\n| `OBS-05` | Audit | Waived | later | ADR-0002 |")
    assert rows["SEC-01"]["status"] == "Addressed" and rows["OBS-05"]["adr"] == "ADR-0002"


def test_digest_ignores_line_endings_and_git(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d, nl in ((a, "\n"), (b, "\r\n")):
        d.mkdir()
        (d / "kit.yaml").write_bytes(f"x: 1{nl}y: 2{nl}".encode())
    (b / ".git").mkdir()
    (b / ".git" / "HEAD").write_text("ref")
    assert digest(a) == digest(b)


def test_env01_in_catalog_and_every_runtime_profile_declares_environment():
    kit = Kit.load(KIT)
    env01 = [n for n in kit.nfr_catalog()["nfrs"] if n["id"] == "ENV-01"]
    assert env01 and env01[0]["level"] == "mandatory" and env01[0]["scope"] == "platform"
    for stack in kit.stacks.values():
        for pid in stack["profiles"]:
            data = kit.profile_data(pid)
            if data.get("commands"):            # owns a runtime (not 'shares_runtime_with')
                env = data.get("environment")
                assert env and env.get("pin_file") and env.get("gitignore"), pid
                assert "ENV-01" in (data.get("controls") or {}), pid


def test_python_profile_never_uses_bare_pip_or_unlocked_uv():
    data = Kit.load(KIT).profile_data("backend/fastapi")
    for name, argv in data["commands"].items():
        assert argv[0] == "uv", name
        assert "--locked" in argv, f"{name} must run against uv.lock"
    assert "pip install" not in " ".join(" ".join(a) for a in data["commands"].values())


def test_venv_version_detection(tmp_path):
    from ekit.checks import venv_python_version, version_matches
    (tmp_path / "pyvenv.cfg").write_text("home = C:\\Python312\nimplementation = CPython\nversion_info = 3.12.4\n")
    assert venv_python_version(tmp_path) == "3.12.4"
    assert version_matches("3.12.4", "3.12") and version_matches("3.12.4", "3.12.4")
    assert version_matches("3.12.4", "cpython-3.12\n")
    assert not version_matches("3.11.9", "3.12") and not version_matches("3.12.4", "")


# ------------------------------------------------------------------ 0.1.2: frozen tests, empty steps
from types import SimpleNamespace  # noqa: E402

from ekit import checks, stepscan  # noqa: E402
from ekit.project import EkitError, dump_yaml  # noqa: E402

WEAK_STEPS = '''
import pytest
from pytest_bdd import scenarios, given, when, then, parsers

scenarios('/Volumes/Jassal/RS/Apps/mesenger/specs/001-user-admin/features/01-account-lifecycle.feature')

@given(parsers.parse('a user with username "{u}" already exists'))
def user_exists(client, u):
    pass

@when("the administrator deactivates the account")
def deactivate(client):
    """does nothing yet"""

@then("no duplicate account exists")
def no_duplicate(client):
    ...

@then("the account is deactivated")
def deactivated():
    assert True

@then("something real")
def real(response):
    assert response.status_code == 201

@then("deliberate")
def deliberate():  # ekit: allow-empty-step state is asserted by the previous step
    pass

def helper():
    pass
'''


def test_stepscan_flags_empty_steps_and_absolute_paths_but_not_real_ones():
    res = stepscan.scan_source(WEAK_STEPS)
    flagged = {i.name: i.step for i in res.steps}
    assert set(flagged) == {"user_exists", "deactivate", "no_duplicate", "deactivated"}
    assert flagged["user_exists"] == 'a user with username "{u}" already exists'   # text taken from parsers.parse(...)
    assert flagged["no_duplicate"] == "no duplicate account exists"
    assert [p for _, p in res.abs_paths] == ["/Volumes/Jassal/RS/Apps/mesenger/specs/001-user-admin/features/01-account-lifecycle.feature"]
    assert not res.error


def test_stepscan_relative_paths_and_syntax_errors():
    ok = stepscan.scan_source("from pathlib import Path\nscenarios(str(Path(__file__).parent / 'x.feature'))\nscenario('rel/x.feature', 'n')\n")
    assert not ok.abs_paths and not ok.steps
    assert stepscan.scan_source("@then('x')\ndef f(:\n").error


def _ctx(tmp_path, framework="pytest-bdd"):
    prof = SimpleNamespace(id="backend/fastapi", runs_bdd=True, bdd={"framework": framework}, root=tmp_path,
                           data={"layout": {"acceptance_tests": "tests/acceptance"}})
    project = SimpleNamespace(root=tmp_path, profiles=[prof], rel=lambda p: str(Path(p).relative_to(tmp_path)))
    feat = tmp_path / "specs" / "001-demo"
    return checks.GateContext(project=project, feature_dir=feat)


def _feature_project(tmp_path):
    (tmp_path / "specs/001-demo/features").mkdir(parents=True)
    (tmp_path / "specs/001-demo/features/a.feature").write_text("@SCN-001-01\nFeature: A\n  Scenario: s\n    Given x\n", encoding="utf-8")
    t = tmp_path / "tests/acceptance"
    t.mkdir(parents=True)
    (t / "test_a.py").write_text("from pytest_bdd import scenarios\nscenarios('../../specs/001-demo/features/a.feature')\n", encoding="utf-8")
    (t / "test_health.py").write_text("# SCN-000-01 belongs to the landing zone\n", encoding="utf-8")
    return _ctx(tmp_path)


def _record_red(ctx, tmp_path, with_fp=True):
    entry = {"phase": "red", "scenarios": {"SCN-001-01": "failed"}}
    if with_fp:
        entry["fingerprints"] = {checks._rel_posix(ctx, f): checks._sha(f) for f in checks._frozen_files(ctx, "specs/001-demo/features")}
    ledger = tmp_path / ".ekit/ledger/001-demo.yaml"
    ledger.parent.mkdir(parents=True)
    dump_yaml({"feature": "001-demo", "entries": [entry]}, ledger)


W = {"dir": "specs/001-demo/features"}


def test_frozen_files_are_the_feature_files_and_the_modules_that_bind_them(tmp_path):
    ctx = _feature_project(tmp_path)
    names = [checks._rel_posix(ctx, f) for f in checks._frozen_files(ctx, W["dir"])]
    assert names == ["specs/001-demo/features/a.feature", "tests/acceptance/test_a.py"]


def test_tests_unchanged_passes_then_catches_edit_delete_and_new_module(tmp_path):
    ctx = _feature_project(tmp_path)
    _record_red(ctx, tmp_path)
    assert checks.tests_unchanged(ctx, W) == []
    mod = tmp_path / "tests/acceptance/test_a.py"
    mod.write_bytes(mod.read_bytes().replace(b"\n", b"\r\n"))                 # line endings alone are not a change
    assert checks.tests_unchanged(ctx, W) == []
    mod.write_text(mod.read_text() + "# weakened\n", encoding="utf-8")
    f = checks.tests_unchanged(ctx, W)
    assert [x.level for x in f] == ["error"] and "test_a.py: changed since red" in f[0].message
    mod.unlink()
    assert "deleted since red" in checks.tests_unchanged(ctx, W)[0].message
    mod.write_text("from pytest_bdd import scenarios\nscenarios('../../specs/001-demo/features/a.feature')\n", encoding="utf-8")
    (tmp_path / "tests/acceptance/test_b.py").write_text("scenarios('a.feature')\n", encoding="utf-8")
    f = checks.tests_unchanged(ctx, W)
    assert [x.level for x in f] == ["warn"] and "test_b.py" in f[0].message


def test_tests_unchanged_without_ledger_red_or_fingerprints(tmp_path):
    ctx = _feature_project(tmp_path)
    assert checks.tests_unchanged(ctx, W) == []                                # no ledger: red_first reports it
    _record_red(ctx, tmp_path, with_fp=False)
    f = checks.tests_unchanged(ctx, W)
    assert [x.level for x in f] == ["warn"] and "re-run `ekit gate red`" in f[0].message


def test_vacuous_steps_check_scans_bound_modules_and_conftest_only(tmp_path):
    ctx = _feature_project(tmp_path)
    (tmp_path / "tests/acceptance/test_a.py").write_text(
        "from pytest_bdd import scenarios, then\nscenarios('../../specs/001-demo/features/a.feature')\n@then('x')\ndef x():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests/acceptance/test_health.py").write_text("from pytest_bdd import then\n@then('h')\ndef h():\n    pass\n", encoding="utf-8")  # landing zone: not this feature
    msgs = [f.message for f in checks.vacuous_steps(ctx, W)]
    assert len(msgs) == 1 and "test_a.py:4" in msgs[0] and "empty body" in msgs[0]
    (tmp_path / "tests/acceptance/conftest.py").write_text("from pytest_bdd import given\n@given('shared')\ndef shared():\n    pass\n", encoding="utf-8")
    assert any("conftest.py" in f.message for f in checks.vacuous_steps(ctx, W))


def test_vacuous_steps_check_is_informational_for_other_frameworks(tmp_path):
    f = checks.vacuous_steps(_ctx(tmp_path, framework="cucumber-jvm"), W)
    assert [x.level for x in f] == ["info"]


def test_kit_requiring_a_newer_ekit_is_refused(tmp_path):
    (tmp_path / "kit.yaml").write_text("metadata: {name: k, version: 9.9.9}\nrequires: {ekit: '>=99.0.0'}\n", encoding="utf-8")
    try:
        Kit.load(tmp_path)
    except EkitError as exc:
        assert "requires ekit >=99.0.0" in str(exc)
    else:
        raise AssertionError("expected EkitError")
    (tmp_path / "kit.yaml").write_text("metadata: {name: k, version: 9.9.9}\nrequires: {ekit: '>=0.0.1'}\n", encoding="utf-8")
    assert Kit.load(tmp_path).version == "9.9.9"


def test_bundled_kit_declares_the_new_checks_and_matching_requirement():
    pol = Kit.load(KIT).policy()["spec"]["gates"]
    ids = {c["id"] for g in pol for c in g["checks"]}
    assert {"RED-STEPS-ASSERT", "GREEN-TESTS-UNCHANGED"} <= ids
    assert yaml.safe_load((KIT / "kit.yaml").read_text())["requires"]["ekit"] == ">=0.7.0,<0.8"


# ------------------------------------------------------------------ 0.1.3: edit protection (freeze)
import json as _json  # noqa: E402

from ekit import freeze  # noqa: E402

FP = {
    "specs/001-demo/features/a.feature": "x",
    "specs/001-demo/features/b.feature": "y",
    "tests/acceptance/test_a.py": "z",
}


def _edit_rules(root):
    return _json.loads((root / "opencode.json").read_text())["permission"]["edit"]


def test_sync_creates_opencode_json_with_always_deny_rules_after_the_catch_all(tmp_path):
    freeze.sync_permissions(tmp_path)
    cfg = _json.loads((tmp_path / "opencode.json").read_text())
    assert cfg["$schema"] == "https://opencode.ai/config.json"
    rules = cfg["permission"]["edit"]
    assert list(rules)[0] == "*" and rules["*"] == "allow"            # catch-all first: the last match wins
    assert all(rules[p] == "deny" for p in (".ekit/*", "opencode.json", ".opencode/*"))


def test_sync_preserves_user_content_and_normalises_a_string_edit_rule(tmp_path):
    (tmp_path / "opencode.json").write_text(_json.dumps({
        "provider": {"ollama": {"name": "Ollama"}},
        "permission": {"bash": {"rm *": "deny"}, "edit": "ask"},
        "model": "ollama/qwen3:14b",
    }))
    freeze.sync_permissions(tmp_path)
    cfg = _json.loads((tmp_path / "opencode.json").read_text())
    assert cfg["provider"] == {"ollama": {"name": "Ollama"}} and cfg["model"] == "ollama/qwen3:14b"
    bash = cfg["permission"]["bash"]
    assert bash["rm *"] == "deny" and bash["*"] == "allow"            # the user's rule survives
    assert list(bash)[-len(freeze.ALWAYS_BASH):] == freeze.ALWAYS_BASH  # ekit's denies come last (last match wins)
    assert all(bash[p] == "deny" for p in freeze.ALWAYS_BASH)
    assert cfg["permission"]["edit"]["*"] == "ask"                    # the user's own default survives


def test_freeze_collapses_feature_files_denies_tests_and_unfreeze_lifts_with_audit(tmp_path):
    (tmp_path / "opencode.json").write_text(_json.dumps({"permission": {"edit": {"*": "allow", "docs/*": "ask"}}}))
    rules = freeze.freeze_feature(tmp_path, "001-demo", FP)
    assert "specs/001-demo/features/*" in rules and "tests/acceptance/test_a.py" in rules
    assert "specs/001-demo/features/a.feature" not in rules           # one directory pattern, so new files are covered too
    edit = _edit_rules(tmp_path)
    assert edit["docs/*"] == "ask" and edit["tests/acceptance/test_a.py"] == "deny"
    assert list(edit).index("*") < list(edit).index("tests/acceptance/test_a.py")
    assert freeze.verify(tmp_path) and all(ok for ok, *_ in freeze.verify(tmp_path))

    freeze.unfreeze_feature(tmp_path, "001-demo", "typo in step text; JIRA-9")
    edit = _edit_rules(tmp_path)
    assert "tests/acceptance/test_a.py" not in edit and edit["docs/*"] == "ask" and edit[".ekit/*"] == "deny"
    hist = freeze.load_state(tmp_path)["history"]
    assert hist[-1]["reason"] == "typo in step text; JIRA-9" and hist[-1]["feature"] == "001-demo" and hist[-1]["by"]


def test_unfreeze_needs_a_reason_and_a_frozen_feature(tmp_path):
    for call in (lambda: freeze.unfreeze_feature(tmp_path, "001-demo", "why"),      # not frozen
                 lambda: freeze.unfreeze_feature(tmp_path, "001-demo", "  ")):       # no reason
        try:
            call()
        except EkitError:
            pass
        else:
            raise AssertionError("expected EkitError")


def test_freeze_is_idempotent_and_refreezing_after_unfreeze_works(tmp_path):
    freeze.freeze_feature(tmp_path, "001-demo", FP)
    once = (tmp_path / "opencode.json").read_text()
    freeze.freeze_feature(tmp_path, "001-demo", FP)
    assert (tmp_path / "opencode.json").read_text() == once
    freeze.unfreeze_feature(tmp_path, "001-demo", "r")
    freeze.freeze_feature(tmp_path, "001-demo", FP)
    assert _edit_rules(tmp_path)["tests/acceptance/test_a.py"] == "deny"


def test_sync_refuses_to_touch_non_strict_json_and_says_what_to_add(tmp_path):
    (tmp_path / "opencode.json").write_text('{\n  // my notes\n  "model": "x"\n}\n')
    before = (tmp_path / "opencode.json").read_text()
    try:
        freeze.sync_permissions(tmp_path)
    except EkitError as exc:
        assert "not strict JSON" in str(exc) and ".ekit/*" in str(exc)
    else:
        raise AssertionError("expected EkitError")
    assert (tmp_path / "opencode.json").read_text() == before


def test_verify_reports_a_missing_or_tampered_rule(tmp_path):
    assert not freeze.verify(tmp_path)[0][0]                              # no opencode.json
    freeze.freeze_feature(tmp_path, "001-demo", FP)
    cfg = _json.loads((tmp_path / "opencode.json").read_text())
    cfg["permission"]["edit"]["tests/acceptance/test_a.py"] = "allow"      # someone relaxed it by hand
    (tmp_path / "opencode.json").write_text(_json.dumps(cfg))
    rows = freeze.verify(tmp_path)
    assert any(not ok and "001-demo frozen" in label for ok, label, _ in rows)


def test_red_gate_freezes_the_feature_in_opencode_json(tmp_path):
    ctx = _feature_project(tmp_path)
    fps = {checks._rel_posix(ctx, f): checks._sha(f) for f in checks._frozen_files(ctx, W["dir"])}
    freeze.freeze_feature(tmp_path, "001-demo", fps)
    edit = _edit_rules(tmp_path)
    assert edit["specs/001-demo/features/*"] == "deny" and edit["tests/acceptance/test_a.py"] == "deny"
    assert "tests/acceptance/test_health.py" not in edit                   # landing-zone tests stay editable


# ------------------------------------------------------------------ 0.1.4: CLI version pinning
import pytest  # noqa: E402

from ekit import gates, kitsource  # noqa: E402
from ekit import __version__ as EKIT_VERSION  # noqa: E402
from ekit.cli import main as ekit_main  # noqa: E402
from ekit.project import Project, parse_version, unmet_constraints  # noqa: E402


def test_version_constraints_support_ranges_and_reject_bad_specs():
    assert parse_version("0.1") == (0, 1, 0) and parse_version("v0.1.4") == (0, 1, 4)
    assert unmet_constraints("0.1.4", ">=0.1.4,<0.2") == []
    assert unmet_constraints("0.2.0", ">=0.1.4,<0.2") == ["<0.2"]
    assert unmet_constraints("0.1.3", ">=0.1.4, <0.2") == [">=0.1.4"]
    assert unmet_constraints("0.1.4", "==0.1.4") == [] and unmet_constraints("0.1.5", "==0.1.4") == ["==0.1.4"]
    with pytest.raises(EkitError):
        unmet_constraints("0.1.4", "~=0.1")
    with pytest.raises(EkitError):
        parse_version("0.1.4rc1")


def test_kit_with_an_upper_bound_refuses_a_newer_cli(tmp_path):
    (tmp_path / "kit.yaml").write_text("metadata: {name: k, version: 1.0.0}\nrequires: {ekit: '>=0.0.1,<0.0.2'}\n", encoding="utf-8")
    with pytest.raises(EkitError, match=r"not <0\.0\.2"):
        Kit.load(tmp_path)


def test_bundled_kit_accepts_this_cli():
    assert unmet_constraints(EKIT_VERSION, Kit.load(KIT).manifest["requires"]["ekit"]) == []


def _pinned_project(tmp_path):
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": "fastapi-jinja"}, root / ".ekit/project.yaml")
    src = kitsource.resolve("bundled")
    lock = kitsource.vendor(root, src)
    (root / "docs/requirements/loan").mkdir(parents=True)
    return root, lock


def _set_lock_cli(root, version):
    lock = yaml.safe_load((root / ".ekit/kit.lock.yaml").read_text(encoding="utf-8"))
    if version is None:
        lock.pop("ekit", None)
    else:
        lock["ekit"] = {"version": version}
    dump_yaml(lock, root / ".ekit/kit.lock.yaml")


def test_vendor_records_the_cli_version_and_cli_pin_compares_it(tmp_path):
    root, lock = _pinned_project(tmp_path)
    assert lock["ekit"]["version"] == EKIT_VERSION
    assert kitsource.cli_pin(root).matches
    _set_lock_cli(root, "0.0.9")
    pin = kitsource.cli_pin(root)
    assert not pin.matches and "pins ekit 0.0.9" in pin.message() and EKIT_VERSION in pin.message()
    _set_lock_cli(root, None)                                    # lock written by an older ekit
    pin = kitsource.cli_pin(root)
    assert pin.pinned is None and not pin.matches and "ekit upgrade" in pin.message()


def test_gates_note_a_cli_mismatch_without_failing_on_it(tmp_path):
    root, _ = _pinned_project(tmp_path)
    project = Project.load(root)
    _, notes = gates.run_gate(project, "intake", prd="docs/requirements/loan")
    assert not any("pins ekit" in n for n in notes)
    _set_lock_cli(root, "0.0.9")
    res, notes = gates.run_gate(Project.load(root), "intake", prd="docs/requirements/loan")
    assert "pins ekit 0.0.9" in notes[0]
    assert gates.render_json(res, notes).count("pins ekit 0.0.9") == 1     # visible in JSON reports for CI
    junit = gates.render_junit(res, notes)
    assert "<system-out>note: this is ekit" in junit and "pins ekit 0.0.9" in junit   # and in JUnit for CI
    import xml.dom.minidom
    xml.dom.minidom.parseString(junit)                                     # still well-formed XML


def test_strict_mode_refuses_to_gate_with_an_unpinned_cli(tmp_path, monkeypatch, capsys):
    root, _ = _pinned_project(tmp_path)
    monkeypatch.chdir(root)
    _set_lock_cli(root, "0.0.9")
    assert ekit_main(["gate", "intake", "--prd", "docs/requirements/loan"]) == 1   # files missing; mismatch is only a note
    monkeypatch.setenv(kitsource.STRICT_ENV, "1")
    assert ekit_main(["gate", "intake", "--prd", "docs/requirements/loan"]) == 2   # refused before judging
    assert "EKIT_REQUIRE_PINNED_CLI is set" in capsys.readouterr().err
    _set_lock_cli(root, EKIT_VERSION)
    assert ekit_main(["gate", "intake", "--prd", "docs/requirements/loan"]) == 1   # matching CLI: gate runs again


def test_red_ledger_entry_records_the_cli_version(tmp_path, monkeypatch):
    ctx = _feature_project(tmp_path)
    prof = ctx.project.profiles[0]
    prof.bdd = {"framework": "pytest-bdd", "report": "reports/cucumber.json"}
    ctx.project.kit = SimpleNamespace(version="9.9.9")
    report = [{"name": "A", "tags": [], "elements": [{"type": "scenario", "tags": [{"name": "SCN-001-01"}],
               "steps": [{"result": {"status": "failed"}}]}]}]

    def fake_run(profile, name, **_):
        (tmp_path / "reports").mkdir(exist_ok=True)
        (tmp_path / "reports/cucumber.json").write_text(_json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=1, output="1 failed", cwd=tmp_path)

    monkeypatch.setattr(checks, "run_profile_command", fake_run)
    monkeypatch.setattr("ekit.freeze.freeze_feature", lambda *a, **k: [])
    cr = gates.CheckResult(id="RED-RUN", type="bdd.run", severity="error")
    cr.findings = checks.bdd_run(ctx, {"expect": "red", "dir": W["dir"], "record": True})
    assert not [f for f in cr.findings if f.level == "error"], cr.findings
    # bdd.run only queues the write; flush_pending_records does it, same as run_gate does once the
    # whole gate has passed (see 0.2.4: a record must not land before a later check, e.g.
    # RED-CLEAN-FAILURE, has had a chance to reject the run).
    checks.flush_pending_records(ctx, [cr])
    entry = yaml.safe_load((tmp_path / ".ekit/ledger/001-demo.yaml").read_text())["entries"][-1]
    assert entry["ekit_version"] == EKIT_VERSION and entry["kit_version"] == "9.9.9"
