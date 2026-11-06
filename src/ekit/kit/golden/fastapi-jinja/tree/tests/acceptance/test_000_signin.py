"""Day-0 seam scenarios (golden core). Every step comes from conftest / api_steps."""

from __future__ import annotations

from pytest_bdd import scenarios

from tests.acceptance.support import feature_file

scenarios(feature_file("000-landing-zone", "signin.feature"))
