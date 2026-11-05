"""Landing-zone smoke scenarios (golden core). Every step comes from the shared steps in conftest."""

from __future__ import annotations

from pytest_bdd import scenarios

from tests.acceptance.support import feature_file

scenarios(feature_file("000-landing-zone", "smoke.feature"))
