"""Acceptance test support (golden core, frozen): typed scenario state and feature-file paths."""

from tests.acceptance.support.context import MissingScenarioStateError, ScenarioContext
from tests.acceptance.support.paths import feature_file

__all__ = ["MissingScenarioStateError", "ScenarioContext", "feature_file"]
