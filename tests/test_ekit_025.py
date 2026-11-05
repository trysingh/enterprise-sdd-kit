"""ekit 0.2.5: an agent treated the illustrative example in a command's "active feature" step as a
real feature to implement, when $ARGUMENTS was empty and the example read like a literal fallback
value rather than a shape. Found live, mid-`/speckit.implement`, on the same real project.

Fix is wording-only (speckit.implement.md, speckit.esdlc.red.md): say explicitly that the examples
are illustrative, name them, and say never to fall back to them. This test just guards the wording
doesn't regress — it can't test agent comprehension, only that the kit's own text says the right
thing.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

from ekit.project import bundled_kit_dir


def _flat(rel: str) -> str:
    # normalize whitespace so a phrase that wraps across a Markdown line break still matches
    return " ".join((bundled_kit_dir() / rel).read_text(encoding="utf-8").split())


def test_implement_command_names_its_example_as_illustrative_only():
    text = _flat("preset/enterprise-baseline/commands/speckit.implement.md")
    assert "only examples" in text and "never fall back to an example name" in text
    assert "001-user-admin" in text   # the example itself is still there, just no longer ambiguous


def test_red_command_names_its_example_as_illustrative_only():
    text = _flat("extension/esdlc/commands/speckit.esdlc.red.md")
    assert "only examples" in text and "never fall back to an example name" in text
    assert "001-user-admin" in text
