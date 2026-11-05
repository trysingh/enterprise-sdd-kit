from __future__ import annotations

from app.features.f000_reference.service import greet


def test_greet_uses_the_word_and_trims_the_name() -> None:
    assert greet("  Ada ", "Hi") == "Hi, Ada"
