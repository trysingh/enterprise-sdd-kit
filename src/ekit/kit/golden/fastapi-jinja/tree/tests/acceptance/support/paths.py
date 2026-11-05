"""Feature files are read from specs/, never copied, and paths never depend on the machine."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def feature_file(feature_dir: str, name: str) -> str:
    """`scenarios(feature_file("003-conversation-history", "history.feature"))`."""
    path = REPO_ROOT / "specs" / feature_dir / "features" / name
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist (feature folder and file name must match specs/)")
    return str(path)
