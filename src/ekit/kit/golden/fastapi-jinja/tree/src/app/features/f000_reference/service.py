"""Use cases: plain Python, no FastAPI imports, unit tested directly."""

from __future__ import annotations


def greet(name: str, word: str = "Hello") -> str:
    return f"{word}, {name.strip()}"
