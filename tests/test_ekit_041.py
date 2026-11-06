"""ekit 0.4.1: GREEN-LINT failed on Spec Kit's own scripts (`.specify/scripts/python/*.py`, E501),
because the fastapi profile ran `ruff check .` over the whole repository. Tooling folders are not
project code: lint and format now exclude .specify, .opencode and .ekit, in the profile command
(golden and generated projects) and in the golden pyproject (editors, pre-commit, plain `ruff`)."""
from __future__ import annotations

import tomllib

import yaml

from ekit.project import bundled_kit_dir

TOOLING = {".specify", ".opencode", ".ekit"}


def test_fastapi_lint_and_format_exclude_tooling_dirs():
    prof = yaml.safe_load((bundled_kit_dir() / "profiles/backend/fastapi/profile.yaml").read_text(encoding="utf-8"))
    for name in ("lint", "format"):
        argv = prof["commands"][name]
        i = argv.index("--extend-exclude")
        assert set(argv[i + 1].split(",")) == TOOLING, name


def test_golden_pyproject_excludes_tooling_dirs():
    py = tomllib.loads((bundled_kit_dir() / "golden/fastapi-jinja/tree/pyproject.toml").read_text(encoding="utf-8"))
    assert set(py["tool"]["ruff"]["extend-exclude"]) == TOOLING
