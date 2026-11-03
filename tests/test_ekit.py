"""Unit tests for parsers, checks and the kit itself. Run: uv run --with pytest --with pyyaml pytest -q"""
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
