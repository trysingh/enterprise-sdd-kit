"""ekit 0.2.5: an agent treated the illustrative example in a command's "active feature" step as a
real feature to implement, when $ARGUMENTS was empty and the example read like a literal fallback
value rather than a shape. Found live, mid-`/speckit.implement`, on the same real project.

0.2.5 fixed it in wording. 0.3.0 removes the judgement altogether: the commands no longer print any
example feature name and instead run `ekit feature current --for red|implement "$ARGUMENTS"`, which
prints one real folder or fails (behaviour tested in test_ekit_030.py). These tests guard the text.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

from ekit.project import bundled_kit_dir


def _flat(rel: str) -> str:
    # normalize whitespace so a phrase that wraps across a Markdown line break still matches
    return " ".join((bundled_kit_dir() / rel).read_text(encoding="utf-8").split())


def test_implement_command_asks_ekit_for_the_feature_and_prints_no_example():
    text = _flat("preset/enterprise-baseline/commands/speckit.implement.md")
    assert 'ekit feature current --for implement "$ARGUMENTS"' in text
    assert "001-user-admin" not in text and "do not choose a feature yourself" in text


def test_red_command_asks_ekit_for_the_feature_and_prints_no_example():
    text = _flat("extension/esdlc/commands/speckit.esdlc.red.md")
    assert 'ekit feature current --for red "$ARGUMENTS"' in text
    assert "001-user-admin" not in text and "do not choose a feature yourself" in text


def test_no_command_text_in_the_kit_carries_an_example_feature_name():
    for f in bundled_kit_dir().rglob("*.md"):
        if "golden" in f.parts:
            continue
        assert "001-user-admin" not in f.read_text(encoding="utf-8"), f
