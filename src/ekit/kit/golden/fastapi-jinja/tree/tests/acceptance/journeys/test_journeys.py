"""Binds every journey (*.feature in this folder) to the generic API steps of tests/acceptance/api_steps.py.

Add journeys as `<j-id>-<slug>.feature` here, tagged `@J-nn @FEAT-nn`. A journey that needs a step the
generic library cannot express adds it to a module next to this one and imports it here.
"""

from __future__ import annotations

from pytest_bdd import scenarios

scenarios(".")
