"""ekit 0.4.0: append-only action log, `ekit log`, `ekit blocked`, OpenCode audit plugin.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ekit import installer, kitsource, logbook
from ekit.cli import main as ekit_main
from ekit.project import Project, dump_yaml, load_yaml


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _bare(tmp_path, stack="fastapi-jinja") -> Path:
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": stack}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    return root


def _events(root: Path) -> list[dict]:
    return list(logbook.iter_events(root))


def _lines(root: Path) -> list[str]:
    return logbook.current_file(root).read_text(encoding="utf-8").splitlines()


# ===================================================================== chain
def test_chain_seq_and_verify(tmp_path):
    root = tmp_path
    for i in range(3):
        rec = logbook.append(root, {"kind": "agent.note", "i": i})
        assert rec and rec["seq"] == i + 1 and rec["v"] == 1 and rec["ts"].endswith("Z")
    evs = _events(root)
    assert evs[0]["prev"] == "sha256:genesis"
    lines = _lines(root)
    import hashlib
    assert evs[1]["prev"] == "sha256:" + hashlib.sha256(lines[0].encode("utf-8")).hexdigest()
    assert len(evs[0]["ts"]) == len("2026-11-06T10:00:00.123Z")
    assert logbook.verify(root) == [] and logbook.count(root) == 3


def test_tampering_is_detected(tmp_path):
    for i in range(4):
        logbook.append(tmp_path, {"kind": "agent.note", "i": i})
    f = logbook.current_file(tmp_path)
    lines = f.read_text(encoding="utf-8").splitlines()
    edited = lines.copy()
    edited[1] = edited[1].replace('"i":1', '"i":99')
    f.write_text("\n".join(edited) + "\n", encoding="utf-8")
    assert any(":3:" in p and "prev" in p for p in logbook.verify(tmp_path))
    f.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")          # a deleted line
    assert any("seq" in p for p in logbook.verify(tmp_path))
    f.write_text("\n".join(lines[:2] + ["not json"] + lines[2:]) + "\n", encoding="utf-8")
    assert any("undecodable" in p for p in logbook.verify(tmp_path))


def test_rotation_continues_the_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(logbook, "ROTATE_BYTES", 300)
    for i in range(12):
        logbook.append(tmp_path, {"kind": "agent.note", "pad": "x" * 60, "i": i})
    assert logbook.rotated_files(tmp_path), "expected at least one rotated file"
    evs = _events(tmp_path)
    assert [e["seq"] for e in evs] == list(range(1, 13))
    assert logbook.verify(tmp_path) == []
    logbook.current_file(tmp_path).unlink()                  # current file gone: chain resumes from the rotated one
    last_rotated = [json.loads(x)["seq"] for x in logbook.rotated_files(tmp_path)[-1].read_text(encoding="utf-8").splitlines()][-1]
    assert logbook.append(tmp_path, {"kind": "agent.note"})["seq"] == last_rotated + 1
    assert logbook.verify(tmp_path) == []


def test_redaction():
    out = logbook.redact({
        "password": "hunter2", "Api_Key": "k", "nested": {"authorization": "Bearer abc"},
        "cmd": "curl -H 'Authorization: Bearer abc.def' --token=zzz --password hunter2 AKIA" + "A" * 16,
        "gh": "ghp_" + "a" * 36, "slack": "xoxb-123-abc", "pem": "-----BEGIN RSA PRIVATE KEY-----",
        "long": "y" * 600, "n": 5, "items": ["--secret=s3", "ok"],
    })
    assert out["password"] == "***" and out["Api_Key"] == "***" and out["nested"]["authorization"] == "***"
    assert "abc.def" not in out["cmd"] and "zzz" not in out["cmd"] and "hunter2" not in out["cmd"]
    assert "--token=***" in out["cmd"] and "AKIA" not in out["cmd"]
    assert out["gh"] == "***" and out["slack"] == "***" and out["pem"] == "***"
    assert out["long"] == "y" * 500 + "…(+100)" and out["n"] == 5 and out["items"] == ["--secret=***", "ok"]
    assert logbook.redact_argv(["--token", "abc", "x"]) == ["--token", "***", "x"]


def test_append_never_raises(tmp_path):
    blocker = tmp_path / "root"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    assert logbook.append(blocker, {"kind": "agent.note"}) is None
    assert logbook.append(tmp_path, {"kind": "agent.note", "bad": object()}) is not None   # unserialisable -> str()


def test_via_follows_the_actor_env(monkeypatch):
    monkeypatch.delenv("EKIT_ACTOR", raising=False)
    assert logbook.via() == "person"
    monkeypatch.setenv("EKIT_ACTOR", "agent")
    assert logbook.via() == "agent"


# ===================================================================== CLI wrapper
def test_cli_wrapper_writes_start_and_end(tmp_path, monkeypatch, capsys):
    root = _bare(tmp_path)
    (root / "specs" / "001-chat").mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("EKIT_SESSION", "s-1")
    assert ekit_main(["gate", "spec", "--feature", "001-chat", "--prd", "docs/requirements/sekret"]) == 1
    start, end = [e for e in _events(root) if e["kind"].startswith("cmd.")]
    assert (start["kind"], end["kind"]) == ("cmd.start", "cmd.end") and start["run_id"] == end["run_id"]
    assert start["cmd"] == "gate" and start["feature"] == "001-chat" and start["session"] == "s-1"
    assert start["args"] == ["spec", "--feature", "001-chat", "--prd", "docs/requirements/sekret"] and start["via"] == "person"
    assert end["exit"] == 1 and end["duration_ms"] >= 0 and end["ekit"] == start["ekit"]
    assert end["gate"]["name"] == "spec" and end["gate"]["result"] == "FAIL" and end["gate"]["checks"]
    assert end["gate"]["findings"] and end["feature"] == "001-chat"
    assert logbook.verify(root) == []
    capsys.readouterr()


def test_cli_wrapper_records_errors_and_skips_log_reads_and_non_projects(tmp_path, monkeypatch, capsys):
    root = _bare(tmp_path)
    monkeypatch.chdir(root)
    assert ekit_main(["unfreeze", "001-nope", "--reason", "x"]) == 2
    end = next(e for e in _events(root) if e["kind"] == "cmd.end")
    assert end["exit"] == 2 and "not found" in end["error"]
    n = logbook.count(root)
    assert ekit_main(["log", "tail"]) == 0 and ekit_main(["log", "verify"]) == 0
    assert logbook.count(root) == n
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.chdir(outside)
    assert ekit_main(["context"]) == 2 and not (outside / ".ekit").exists()
    capsys.readouterr()


def test_freeze_unfreeze_write_state_events(tmp_path):
    from ekit import freeze
    root = _bare(tmp_path)
    freeze.freeze_feature(root, "001-chat", {"specs/001-chat/features/a.feature": "h"})
    freeze.unfreeze_feature(root, "001-chat", "wrong step")
    kinds = [(e["kind"], e["feature"]) for e in _events(root)]
    assert kinds == [("state.freeze", "001-chat"), ("state.unfreeze", "001-chat")]
    assert _events(root)[1]["reason"] == "wrong step" and _events(root)[1]["via"] == "person"
    assert load_yaml(root / ".ekit/freeze.yaml")["history"][0]["action"] == "unfreeze"


# ===================================================================== blocked / log
def _blocked_project(tmp_path, monkeypatch) -> Path:
    root = _bare(tmp_path)
    (root / "specs" / "001-chat" / "features").mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("EKIT_ACTOR", "agent")
    return root


def test_blocked_writes_ledger_entry_log_event_and_status_shows_it(tmp_path, monkeypatch, capsys):
    root = _blocked_project(tmp_path, monkeypatch)
    dump_yaml({"feature": "001-chat", "entries": [{"phase": "red", "scenarios": {}}]}, root / ".ekit/ledger/001-chat.yaml")
    assert ekit_main(["blocked", "001-chat", "--reason", "step 'Given a user' is ambiguous", "--file", "tests/x.py",
                      "--scenario", "SCN-001-02"]) == 0
    out = capsys.readouterr().out
    assert "ekit unfreeze 001-chat" in out and "freeze.mode: split" in out
    entries = load_yaml(root / ".ekit/ledger/001-chat.yaml")["entries"]
    assert [e["phase"] for e in entries] == ["red", "blocked"]
    b = entries[1]
    assert b["reason"].startswith("step") and b["file"] == "tests/x.py" and b["scenario"] == "SCN-001-02"
    assert b["via"] == "agent" and b["git_head"] is None or isinstance(b["git_head"], str)
    ev = next(e for e in _events(root) if e["kind"] == "agent.blocked")
    assert ev["feature"] == "001-chat" and ev["reason"] == b["reason"] and ev["via"] == "agent"
    assert ekit_main(["status"]) == 0
    assert "blocked: 1 open" in capsys.readouterr().out
    # a later red/green entry closes it
    entries.append({"phase": "green", "scenarios": {}})
    dump_yaml({"feature": "001-chat", "entries": entries}, root / ".ekit/ledger/001-chat.yaml")
    assert ekit_main(["status"]) == 0
    assert "blocked:" not in capsys.readouterr().out
    from ekit import freeze
    assert not any(p.startswith("ekit blocked") for p in freeze.ALWAYS_BASH)


def test_blocked_creates_the_ledger_and_needs_a_reason(tmp_path, monkeypatch, capsys):
    root = _blocked_project(tmp_path, monkeypatch)
    assert ekit_main(["blocked", "001-chat", "--reason", "  "]) == 2
    assert ekit_main(["blocked", "001-chat", "--reason", "glue wrong"]) == 0
    assert load_yaml(root / ".ekit/ledger/001-chat.yaml")["entries"][0]["phase"] == "blocked"
    capsys.readouterr()


def test_log_append_refuses_bad_kinds_and_accepts_tool_calls(tmp_path, monkeypatch, capsys):
    root = _blocked_project(tmp_path, monkeypatch)
    assert ekit_main(["log", "append", "--json", '{"kind": "state.freeze"}']) == 2
    assert ekit_main(["log", "append", "--json", "[1]"]) == 2
    assert ekit_main(["log", "append", "--json", "{nope"]) == 2
    assert ekit_main(["log", "append", "--json", json.dumps(
        {"kind": "tool.call", "tool": "edit", "path": "specs/001-chat/features/a.feature", "outcome": "denied"})]) == 0
    ev = _events(root)[-1]
    assert ev["kind"] == "tool.call" and ev["via"] == "agent"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO('{"kind": "agent.note", "via": "person"}'))
    assert ekit_main(["log", "append"]) == 0 and _events(root)[-1]["via"] == "person"
    capsys.readouterr()


def test_log_why_tail_show_export_verify(tmp_path, monkeypatch, capsys):
    root = _blocked_project(tmp_path, monkeypatch)
    assert ekit_main(["blocked", "001-chat", "--reason", "assertion contradicts SCN-001-02"]) == 0
    ekit_main(["log", "append", "--json", json.dumps({"kind": "tool.call", "tool": "edit", "outcome": "denied",
                                                       "path": "specs/001-chat/features/a.feature"})])
    ekit_main(["log", "append", "--json", json.dumps({"kind": "tool.call", "tool": "edit", "outcome": "ok",
                                                       "path": "specs/001-chat/features/b.feature"})])
    ekit_main(["log", "append", "--json", json.dumps({"kind": "tool.call", "tool": "edit", "outcome": "ok",
                                                       "path": "tests/acceptance/test_f001_chat.py"})])
    ekit_main(["gate", "spec", "--feature", "001-chat"])
    capsys.readouterr()
    assert ekit_main(["log", "why", "001-chat"]) == 0
    why = capsys.readouterr().out
    assert "assertion contradicts SCN-001-02" in why and "BLOCKED" in why
    assert "edit specs/001-chat/features/a.feature [denied]" in why and "b.feature" not in why
    assert "gate spec FAIL" in why
    assert ekit_main(["log", "why", "001"]) == 0 and "BLOCKED" in capsys.readouterr().out      # NNN expands
    assert ekit_main(["log", "tail", "-n", "2", "--via", "agent"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 2
    assert ekit_main(["log", "tail", "--kind", "agent.blocked"]) == 0
    assert capsys.readouterr().out.count("agent.blocked") == 1
    run_id = next(e for e in _events(root) if e["kind"] == "cmd.start")["run_id"]
    assert ekit_main(["log", "show", run_id]) == 0 and run_id not in capsys.readouterr().err
    assert ekit_main(["log", "show", "nope"]) == 2
    capsys.readouterr()
    assert ekit_main(["log", "export", "--feature", "001-chat"]) == 0
    rows = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert rows and all(r["v"] == 1 for r in rows)
    assert ekit_main(["log", "export", "--since", "2999-01-01"]) == 0 and capsys.readouterr().out == ""
    assert ekit_main(["log", "verify"]) == 0 and "log intact" in capsys.readouterr().out
    f = logbook.current_file(root)
    f.write_text(f.read_text(encoding="utf-8").replace("assertion contradicts", "assertion matches", 1), encoding="utf-8")
    assert ekit_main(["log", "verify"]) == 1


# ===================================================================== installer / plugin
def test_plugin_is_in_the_kit_hash_and_installed(tmp_path):
    root = _bare(tmp_path)
    kit_plugin = root / ".ekit/kit/opencode/plugin/ekit-audit.js"
    assert kit_plugin.is_file()
    project = Project.load(root)
    installer.install_opencode_assets(project)
    dest = root / ".opencode/plugin/ekit-audit.js"
    text = dest.read_text(encoding="utf-8")
    assert dest.read_bytes() == kit_plugin.read_bytes()
    assert "export const EkitAudit" in text and 'process.env.EKIT_ACTOR = "agent"' in text
    assert "tool.execute.before" in text and "tool.execute.after" in text and "verified" not in text.split("\n")[0]
    # the vendored copy is covered by kit.lock.yaml's digest
    before = kitsource.digest(root / ".ekit/kit")
    kit_plugin.write_text(text + "// x\n", encoding="utf-8")
    assert kitsource.digest(root / ".ekit/kit") != before


def test_scaffold_ignores_logs_unless_the_project_commits_them(tmp_path):
    root = _bare(tmp_path)
    installer.scaffold(Project.load(root))
    installer.scaffold(Project.load(root))
    gi = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert gi.count(".ekit/logs/") == 1
    root2 = _bare(tmp_path / "two")
    cfg = load_yaml(root2 / ".ekit/project.yaml")
    cfg["log"] = {"commit": True}
    dump_yaml(cfg, root2 / ".ekit/project.yaml")
    installer.scaffold(Project.load(root2))
    assert ".ekit/logs/" not in (root2 / ".gitignore").read_text(encoding="utf-8")


def test_doctor_reports_log_and_plugin(tmp_path, capsys):
    root = _bare(tmp_path)
    project = Project.load(root)
    installer.doctor(project)
    out = capsys.readouterr().out
    assert "action log (.ekit/logs) — no events yet" in out and "[!!] OpenCode audit plugin" in out
    installer.install_opencode_assets(project)
    logbook.append(root, {"kind": "agent.note"})
    installer.doctor(project)
    out = capsys.readouterr().out
    assert "action log (.ekit/logs) — intact (1 events)" in out and "[ok] OpenCode audit plugin" in out
    logbook.append(root, {"kind": "agent.note"})
    f = logbook.current_file(root)
    f.write_text(f.read_text(encoding="utf-8").replace("agent.note", "agent.nope", 1), encoding="utf-8")
    installer.doctor(project)
    assert "[!!] action log" in capsys.readouterr().out


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node not installed")
def test_plugin_is_valid_javascript():
    plugin = Path(__file__).resolve().parents[1] / "src/ekit/kit/opencode/plugin/ekit-audit.js"
    r = subprocess.run(["node", "--check", str(plugin)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
