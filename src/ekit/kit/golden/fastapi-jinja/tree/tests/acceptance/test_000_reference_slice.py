"""Reference slice (exemplar): the shape of a feature's step module.

1. Bind the feature file with `feature_file("<NNN-slug>", "<name>.feature")`.
2. Reuse the shared steps from conftest; write steps only for the feature's domain language.
3. Every step takes `ctx: ScenarioContext`; state set in one step is read with `ctx.recall` in a
   later step of the SAME scenario.
"""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.support import ScenarioContext, feature_file

scenarios(feature_file("000-reference-slice", "greeting.feature"))


@given(parsers.re(r'a visitor called "(?P<name>[^"]+)"'))
def a_visitor(ctx: ScenarioContext, name: str) -> None:
    ctx.remember("visitor", name)


@when("the visitor asks for a greeting")
def visitor_asks(ctx: ScenarioContext) -> None:
    ctx.response = ctx.http.get("/api/v1/reference/greeting", params={"name": ctx.recall("visitor")})


@then("the greeting names the visitor")
def greeting_names_visitor(ctx: ScenarioContext) -> None:
    assert ctx.last_response.status_code == 200, ctx.last_response.text
    assert ctx.last_response.json()["message"].endswith(ctx.recall("visitor"))
