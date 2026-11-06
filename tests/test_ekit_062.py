"""ekit 0.6.2: red gate warns on lint issues before freezing, so they are fixed before
green instead of after."""
from __future__ import annotations

import yaml

from ekit.project import bundled_kit_dir

KIT = bundled_kit_dir()


def _red_checks():
    policy = yaml.safe_load((KIT / "policy/gates.policy.yaml").read_text(encoding="utf-8"))
    red = next(g for g in policy["spec"]["gates"] if g["id"] == "red")
    return red["checks"]


def test_red_gate_has_lint_check_warning_not_blocking():
    checks = _red_checks()
    ids = [c["id"] for c in checks]
    assert "RED-LINT" in ids
    lint = next(c for c in checks if c["id"] == "RED-LINT")
    assert lint["type"] == "profile.command"
    assert lint["with"] == {"command": "lint"}
    assert lint["severity"] == "warn"


def test_red_lint_check_ordered_after_clean_failure_and_before_route_stubbed():
    ids = [c["id"] for c in _red_checks()]
    assert ids.index("RED-CLEAN-FAILURE") < ids.index("RED-LINT") < ids.index("RED-ROUTE-STUBBED")


def test_red_command_tells_agent_to_fix_lint_before_freeze():
    text = (KIT / "extension/esdlc/commands/speckit.esdlc.red.md").read_text(encoding="utf-8")
    assert "RED-LINT" in text
    assert "fix the lint issue now, in the same commit as red" in text
