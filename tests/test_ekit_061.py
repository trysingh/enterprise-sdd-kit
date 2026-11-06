"""ekit 0.6.1: non-golden red guidance; `ekit feature package` no longer errors outside golden;
agents stay inside the repository root."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ekit import kitsource
from ekit.cli import main as ekit_main
from ekit.project import bundled_kit_dir, dump_yaml


def _bare(tmp_path) -> Path:
    root = tmp_path / "proj"
    (root / ".ekit").mkdir(parents=True)
    dump_yaml({"apiVersion": "ekit/v1", "kind": "EkitProject", "stack": "fastapi-jinja"}, root / ".ekit/project.yaml")
    kitsource.vendor(root, kitsource.resolve("bundled"))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_feature_package_on_non_golden_project_prints_message_and_exits_zero(tmp_path, monkeypatch, capsys):
    root = _bare(tmp_path)
    (root / "specs/003-demo/features").mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.delenv("SPECIFY_FEATURE", raising=False)
    capsys.readouterr()
    assert ekit_main(["feature", "package", "003"]) == 0
    assert capsys.readouterr().out.strip() == \
        "no package convention (not a golden landing zone): put code where plan.md says"


def test_red_command_has_not_golden_guidance():
    text = (bundled_kit_dir() / "extension/esdlc/commands/speckit.esdlc.red.md").read_text(encoding="utf-8")
    assert "**Not golden**" in text
    assert "test_000_reference_slice.py" in text and "ekit gate red" in text


def test_agents_block_keeps_agents_inside_the_repository_root():
    text = (bundled_kit_dir() / "opencode/AGENTS.block.md").read_text(encoding="utf-8")
    assert "repository root only" in text
