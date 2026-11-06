"""ekit 0.4.0 split freeze: the red contract (Gherkin, step bindings, Then assertions) stays frozen;
step bodies (glue) may be fixed by the agent and are re-proved red.

Found on the intranet messenger: a step after the first failing one called a method that did not
exist. Red never ran it, green did, and the frozen module stalled the agent until a person unfroze it.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ekit import checks, contract, freeze
from ekit.project import dump_yaml

RED_MODULE = '''\
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../../specs/001-demo/features/a.feature")


@given("a peer is online", target_fixture="peer")
def peer(client):
    return client.peers.get("alice")


@when(parsers.parse('I send "{text}"'))
def send(client, peer, text):
    client.post_message(peer, text)


@then(parsers.parse("the response status is {code:d}"))
def status(ctx, code):
    assert ctx.last_response.status_code == code


@then("the message appears in the thread")
def appears(ctx):
    assert ctx.last_response.json()["text"] == "hello"
    assert ctx.last_response.json()["delivered"] is True
'''

# The fix an agent should be allowed to make: a step body called the wrong API.
GLUE_FIX = RED_MODULE.replace('client.peers.get("alice")', 'client.get_peer(name="alice")') \
                     .replace("client.post_message(peer, text)", 'client.post("/api/v1/messages", json={"to": peer, "text": text})')


def _ledger_ctx(tmp_path: Path, module_text: str, mode: str = "split"):
    root = tmp_path
    (root / ".ekit/ledger").mkdir(parents=True)
    dump_yaml({"freeze": {"mode": mode}}, root / ".ekit/project.yaml")
    (root / "specs/001-demo/features").mkdir(parents=True)
    (root / "specs/001-demo/features/a.feature").write_text("@SCN-001-01\nFeature: A\n  Scenario: s\n    Given a peer is online\n")
    (root / "tests/acceptance").mkdir(parents=True)
    mod = root / "tests/acceptance/test_001_demo.py"
    mod.write_text(RED_MODULE)
    prof = SimpleNamespace(id="backend/fastapi", runs_bdd=True, bdd={"framework": "pytest-bdd", "report": "r.json"},
                           root=root, data={"layout": {"acceptance_tests": "tests/acceptance", "source": "src/app"}})
    project = SimpleNamespace(root=root, profiles=[prof], rel=lambda p: str(Path(p).relative_to(root)))
    ctx = checks.GateContext(project=project, feature_dir=root / "specs/001-demo")
    rel = "tests/acceptance/test_001_demo.py"
    fp = {rel: checks._sha(mod), "specs/001-demo/features/a.feature": checks._sha(root / "specs/001-demo/features/a.feature")}
    con = contract.project_contract(root, "001-demo", {rel: RED_MODULE}, checks._known_test_files(ctx))
    dump_yaml({"feature": "001-demo", "entries": [
        {"phase": "red", "at": "2026-11-06T00:00:00+00:00", "git_head": None, "fingerprints": fp, "contract": con},
    ]}, root / ".ekit/ledger/001-demo.yaml")
    mod.write_text(module_text)
    return ctx


W = {"dir": "specs/001-demo/features"}


# ------------------------------------------------------------------------------ contract
def test_module_contract_records_bindings_then_asserts_and_hazards():
    c = contract.module_contract(RED_MODULE)
    assert "given('a peer is online', target_fixture='peer')" in c["bindings"]
    assert any(b.startswith("scenarios(") for b in c["bindings"])
    assert c["then_steps"]["then('the message appears in the thread')"]["asserts"] == 2
    assert set(c["hazards"].values()) == {0}


def test_glue_body_change_keeps_the_contract():
    assert contract.module_contract(GLUE_FIX)["bindings_sha256"] == contract.module_contract(RED_MODULE)["bindings_sha256"]
    red = {"modules": {"t.py": contract.module_contract(RED_MODULE)}}
    assert contract.compare_contract(red, {"t.py": GLUE_FIX}) == []
    assert contract.compare_weakening(red, {"t.py": GLUE_FIX}) == []


@pytest.mark.parametrize("change, expect", [
    (lambda s: s.replace('"I send \\"{text}\\""', '"I post \\"{text}\\""').replace("I send", "I post"), "bindings changed"),
    (lambda s: s.replace(', target_fixture="peer"', ""), "bindings changed"),
])
def test_binding_changes_break_the_contract(change, expect):
    red = {"modules": {"t.py": contract.module_contract(RED_MODULE)}}
    assert any(expect in m for m in contract.compare_contract(red, {"t.py": change(RED_MODULE)}))


@pytest.mark.parametrize("change, expect", [
    (lambda s: s.replace('    assert ctx.last_response.json()["delivered"] is True\n', ""), "may not lose assertions"),
    (lambda s: s.replace('== "hello"', '== "hi"'), "different expected values"),
    (lambda s: s.replace("def appears(ctx):\n", "def appears(ctx):\n    pytest.skip('later')\n"), "new skip"),
    (lambda s: s.replace("def status(ctx, code):\n", "@pytest.mark.xfail\ndef status(ctx, code):\n"), "xfail or skip mark"),
    (lambda s: s.replace("== code", "== code or True"), "or true"),
    (lambda s: s + "\n\n@then('x')\ndef x():\n    assert True\n", "assert constant"),
    (lambda s: s.replace("    assert ctx.last_response.status_code == code\n",
                         "    try:\n        assert ctx.last_response.status_code == code\n    except AssertionError:\n        pass\n"),
     "swallowed assert"),
    (lambda s: s.replace("def appears(ctx):\n", "def appears(ctx):\n    if ctx:\n        return\n"), "return before assert"),
])
def test_weakening_is_rejected(change, expect):
    red = {"modules": {"t.py": contract.module_contract(RED_MODULE)}}
    msgs = contract.compare_weakening(red, {"t.py": change(RED_MODULE)})
    assert any(expect in m for m in msgs), msgs


def test_unparsable_module_is_a_contract_error():
    red = {"modules": {"t.py": contract.module_contract(RED_MODULE)}}
    assert any("does not parse" in m for m in contract.compare_contract(red, {"t.py": "def (:\n"}))


# ------------------------------------------------------------------------------ mode
def test_mode_defaults_split_for_golden_strict_otherwise(tmp_path):
    (tmp_path / ".ekit").mkdir()
    assert contract.freeze_mode(tmp_path) == "strict"
    (tmp_path / ".ekit/golden.lock.yaml").write_text("version: 1.0.0\n")
    assert contract.freeze_mode(tmp_path) == "split"
    dump_yaml({"freeze": {"mode": "strict"}}, tmp_path / ".ekit/project.yaml")
    assert contract.freeze_mode(tmp_path) == "strict"


def test_split_freeze_denies_feature_files_but_not_glue(tmp_path):
    (tmp_path / ".ekit").mkdir()
    (tmp_path / ".ekit/golden.lock.yaml").write_text("version: 1.0.0\n")
    fp = {"specs/001-demo/features/a.feature": "a", "tests/acceptance/test_001_demo.py": "b",
          "tests/acceptance/steps.js": "c"}
    freeze.freeze_feature(tmp_path, "001-demo", fp)
    frozen = yaml.safe_load((tmp_path / ".ekit/freeze.yaml").read_text())["frozen"]["001-demo"]
    assert "specs/001-demo/features/*" in frozen
    assert "tests/acceptance/steps.js" in frozen          # only Python glue is split
    assert "tests/acceptance/test_001_demo.py" not in frozen
    rules = json.loads((tmp_path / "opencode.json").read_text())["permission"]["edit"]
    assert "tests/acceptance/test_001_demo.py" not in rules


def test_strict_mode_still_freezes_the_module(tmp_path):
    (tmp_path / ".ekit").mkdir()
    freeze.freeze_feature(tmp_path, "001-demo", {"tests/acceptance/test_001_demo.py": "b"})
    assert "tests/acceptance/test_001_demo.py" in yaml.safe_load((tmp_path / ".ekit/freeze.yaml").read_text())["frozen"]["001-demo"]


# ------------------------------------------------------------------------------ gate checks
def test_green_checks_accept_a_glue_fix(tmp_path):
    ctx = _ledger_ctx(tmp_path, GLUE_FIX)
    assert checks.tests_unchanged(ctx, W) == []      # split: glue no longer byte-compared
    assert checks.contract_intact(ctx, W) == []
    assert checks.glue_not_weakened(ctx, W) == []
    assert checks.no_shadow_glue(ctx, W) == []


def test_strict_mode_keeps_byte_comparison(tmp_path):
    ctx = _ledger_ctx(tmp_path, GLUE_FIX, mode="strict")
    assert any("changed since red" in f.message for f in checks.tests_unchanged(ctx, W))
    assert checks.contract_intact(ctx, W) == []      # split-only checks are silent


def test_green_rejects_a_weakened_then(tmp_path):
    ctx = _ledger_ctx(tmp_path, RED_MODULE.replace('== "hello"', '== "hi"'))
    assert any(f.level == "error" for f in checks.glue_not_weakened(ctx, W))


def test_feature_file_change_still_fails_in_split_mode(tmp_path):
    ctx = _ledger_ctx(tmp_path, GLUE_FIX)
    (tmp_path / "specs/001-demo/features/a.feature").write_text("@SCN-001-01\nFeature: A\n  Scenario: s\n    Given nothing\n")
    assert any("a.feature: changed since red" in f.message for f in checks.tests_unchanged(ctx, W))


def test_new_conftest_is_shadow_glue(tmp_path):
    ctx = _ledger_ctx(tmp_path, GLUE_FIX)
    (tmp_path / "tests/acceptance/conftest.py").write_text("from pytest_bdd import then\n")
    assert any("new conftest.py" in f.message for f in checks.no_shadow_glue(ctx, W))


def test_new_step_module_imported_by_glue_is_shadow_glue(tmp_path):
    ctx = _ledger_ctx(tmp_path, "from tests.acceptance.extra_steps import *\n" + GLUE_FIX)
    (tmp_path / "tests/acceptance/extra_steps.py").write_text(
        "from pytest_bdd import then\n\n@then('the message appears in the thread')\ndef ok():\n    pass\n")
    assert any("defines steps" in f.message for f in checks.no_shadow_glue(ctx, W))


def test_old_red_entry_without_contract_warns(tmp_path):
    ctx = _ledger_ctx(tmp_path, GLUE_FIX)
    ledger = tmp_path / ".ekit/ledger/001-demo.yaml"
    data = yaml.safe_load(ledger.read_text())
    del data["entries"][0]["contract"]
    dump_yaml(data, ledger)
    found = checks.contract_intact(ctx, W)
    assert found and found[0].level == "warn" and "--recontract" in found[0].message


# ------------------------------------------------------------------------------ replay
def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout


def test_replay_restores_red_code_then_puts_uncommitted_work_back(tmp_path, monkeypatch):
    root = tmp_path
    _git(root, "init", "-q")
    (root / ".ekit/ledger").mkdir(parents=True)
    pkg = root / "src/app/features/f001_demo"
    pkg.mkdir(parents=True)
    (pkg / "routes.py").write_text("def send():\n    not_implemented()\n")
    entry = {"phase": "red", "at": "2026-11-06T01:02:03+00:00", "git_head": None}
    dump_yaml({"feature": "001-demo", "entries": [entry]}, root / ".ekit/ledger/001-demo.yaml")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "red")
    red_rev = _git(root, "rev-parse", "HEAD").strip()
    # implementation since red: one committed change, one uncommitted change, one new untracked file
    (pkg / "routes.py").write_text("def send():\n    return 201\n")
    _git(root, "commit", "-qam", "impl")
    (pkg / "routes.py").write_text("def send():\n    return 201  # wip\n")
    (pkg / "store.py").write_text("STORE = []\n")
    index_before = _git(root, "diff", "--cached", "--stat")

    from ekit import fixred
    monkeypatch.setattr(fixred, "_revert_scope", lambda project, feature: ["src/app/features/f001_demo"])
    seen = {}

    def run():
        seen["routes"] = (pkg / "routes.py").read_text()
        seen["store_exists"] = (pkg / "store.py").exists()
        return ["ran"]

    rev, result = contract.replay_red(SimpleNamespace(root=root), "001-demo", entry, run)
    assert rev == red_rev and result == ["ran"]
    assert seen == {"routes": "def send():\n    not_implemented()\n", "store_exists": False}
    assert (pkg / "routes.py").read_text() == "def send():\n    return 201  # wip\n"
    assert (pkg / "store.py").read_text() == "STORE = []\n"
    assert _git(root, "diff", "--cached", "--stat") == index_before
    assert not (root / ".ekit/replay-backup").exists()


def test_replay_restores_even_when_the_run_raises(tmp_path, monkeypatch):
    root = tmp_path
    _git(root, "init", "-q")
    (root / ".ekit/ledger").mkdir(parents=True)
    pkg = root / "src/app/x"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text("red\n")
    entry = {"phase": "red", "at": "2026-11-06T01:02:03+00:00", "git_head": None}
    dump_yaml({"feature": "001-demo", "entries": [entry]}, root / ".ekit/ledger/001-demo.yaml")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "red")
    (pkg / "a.py").write_text("green wip\n")
    from ekit import fixred
    monkeypatch.setattr(fixred, "_revert_scope", lambda project, feature: ["src/app/x"])

    def boom():
        raise RuntimeError("runner crashed")

    with pytest.raises(RuntimeError):
        contract.replay_red(SimpleNamespace(root=root), "001-demo", entry, boom)
    assert (pkg / "a.py").read_text() == "green wip\n"


def test_red_evidence_commit_is_the_commit_that_recorded_red(tmp_path):
    root = tmp_path
    _git(root, "init", "-q")
    (root / "README").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "before red")
    head = _git(root, "rev-parse", "HEAD").strip()
    (root / ".ekit/ledger").mkdir(parents=True)
    entry = {"phase": "red", "at": "2026-11-06T09:09:09+00:00", "git_head": head}
    dump_yaml({"feature": "001-demo", "entries": [entry]}, root / ".ekit/ledger/001-demo.yaml")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "test(001): red")
    red_commit = _git(root, "rev-parse", "HEAD").strip()
    (root / "README").write_text("y\n")
    _git(root, "commit", "-qam", "later")
    assert contract.red_evidence_commit(root, "001-demo", entry) == red_commit


def test_glue_diff_evidence(tmp_path):
    rel = contract.write_glue_diff(tmp_path, "001-demo", "tests/acceptance/t.py", RED_MODULE, GLUE_FIX)
    text = (tmp_path / rel).read_text()
    assert rel == ".ekit/evidence/001-demo/glue-1.diff"
    assert "+    return client.get_peer(name=\"alice\")" in text


def test_replay_check_queues_the_amendment_and_green_writes_the_diff(tmp_path, monkeypatch):
    ctx = _ledger_ctx(tmp_path, GLUE_FIX)
    monkeypatch.setattr(contract, "replay_red", lambda project, feature, red, run: ("abc123def4567890", []))
    monkeypatch.setattr(contract, "file_at", lambda root, rev, rel: RED_MODULE.encode())
    found = checks.replay_red(ctx, W)
    assert found[0].level == "info" and "re-proved red" in found[0].message
    recs = checks._write_glue_evidence(ctx)
    assert recs[0]["file"] == "tests/acceptance/test_001_demo.py" and recs[0]["replay_red"] == "passed"
    assert "before" not in recs[0] and (tmp_path / recs[0]["diff"]).is_file()


def test_replay_check_fails_when_amended_glue_passes_against_red_code(tmp_path, monkeypatch):
    ctx = _ledger_ctx(tmp_path, GLUE_FIX)
    monkeypatch.setattr(contract, "replay_red", lambda project, feature, red, run: (
        "abc123def4567890", [checks.Finding("error", "SCN-001-01: PASSES before implementation")]))
    found = checks.replay_red(ctx, W)
    assert found[0].level == "error" and "PASSES before implementation" in found[0].message
    assert ctx.glue_amendments == []


def test_replay_check_is_silent_when_glue_unchanged(tmp_path, monkeypatch):
    ctx = _ledger_ctx(tmp_path, RED_MODULE)
    monkeypatch.setattr(contract, "replay_red", lambda *a: pytest.fail("must not replay"))
    assert checks.replay_red(ctx, W) == []


def test_red_ledger_entry_records_the_contract_and_split_freeze(tmp_path, monkeypatch):
    ctx = _ledger_ctx(tmp_path, RED_MODULE)
    (tmp_path / ".ekit/ledger/001-demo.yaml").unlink()
    ctx.project.kit = SimpleNamespace(version="0.4.0")
    rel = "tests/acceptance/test_001_demo.py"
    rec = {"expect": "red", "want": ["SCN-001-01"], "status": {"SCN-001-01": "failed"},
           "fingerprints": {rel: "x", "specs/001-demo/features/a.feature": "y"},
           "contract": contract.project_contract(tmp_path, "001-demo", {rel: RED_MODULE}, [rel])}
    ctx.pending_records.append(rec)
    cr = SimpleNamespace(type="bdd.run", findings=[])
    checks.flush_pending_records(ctx, [cr])
    entry = yaml.safe_load((tmp_path / ".ekit/ledger/001-demo.yaml").read_text())["entries"][-1]
    assert entry["contract"]["modules"][rel]["then_steps"]
    frozen = yaml.safe_load((tmp_path / ".ekit/freeze.yaml").read_text())["frozen"]["001-demo"]
    assert rel not in frozen and "specs/001-demo/features/*" in frozen
    assert any("stay editable" in f.message for f in cr.findings)
