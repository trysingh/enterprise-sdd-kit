"""Shared pytest-bdd steps and fixtures (golden core, frozen).

Use these steps before writing your own. Every step takes `ctx: ScenarioContext`; a step that
needs something another step produced reads it from `ctx` of the SAME scenario.

  Given the application is running
  When I GET "<path>"
  When I GET "<path>" with header "<name>" set to "<value>"
  When I POST JSON <json object> to "<path>"
  When I POST the form "<field>=<value>&..." to "<path>"
  Then the response status is <code>
  Then the response header "<name>" is present
  Then the response header "<name>" equals "<value>"
  Then the response JSON field "<dotted.path>" equals "<value>"
  Then the response is a problem document with code "<code>"
  Then the page contains "<text>"
  Then the page does not contain "<text>"
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from tests.acceptance.support import ScenarioContext

PROBLEM_JSON = "application/problem+json"


@pytest.fixture(scope="session")
def app() -> FastAPI:
    from app.main import create_app

    return create_app()


@pytest.fixture
def ctx() -> ScenarioContext:
    return ScenarioContext()


def _body(ctx: ScenarioContext) -> str:
    r = ctx.last_response
    return f"{r.status_code} {r.headers.get('content-type', '')}: {r.text[:500]}"


def _field(data: Any, dotted: str) -> Any:
    cur = data
    for part in dotted.split("."):
        assert isinstance(cur, dict) and part in cur, f"JSON has no field '{dotted}' (at '{part}'): {data!r}"
        cur = cur[part]
    return cur


# ----------------------------------------------------------------------------------- Given
@given("the application is running")
def application_is_running(ctx: ScenarioContext, app: FastAPI) -> None:
    ctx.client = TestClient(app)


# ------------------------------------------------------------------------------------ When
@when(parsers.re(r'I GET "(?P<path>[^"]+)"'))
def get_path(ctx: ScenarioContext, path: str) -> None:
    ctx.response = ctx.http.get(path)


@when(parsers.re(r'I GET "(?P<path>[^"]+)" with header "(?P<name>[^"]+)" set to "(?P<value>[^"]*)"'))
def get_path_with_header(ctx: ScenarioContext, path: str, name: str, value: str) -> None:
    ctx.response = ctx.http.get(path, headers={name: value})


@when(parsers.re(r'I POST JSON (?P<body>\{.*\}) to "(?P<path>[^"]+)"'))
def post_json(ctx: ScenarioContext, body: str, path: str) -> None:
    ctx.response = ctx.http.post(path, json=json.loads(body))


@when(parsers.re(r'I POST the form "(?P<form>[^"]*)" to "(?P<path>[^"]+)"'))
def post_form(ctx: ScenarioContext, form: str, path: str) -> None:
    ctx.http.get("/")  # obtain the CSRF cookie like a browser would
    token = ctx.http.cookies.get("csrftoken", "")
    data = dict(parse_qsl(form, keep_blank_values=True)) | {"csrf_token": token}
    ctx.response = ctx.http.post(path, data=data)


# ------------------------------------------------------------------------------------ Then
@then(parsers.parse("the response status is {code:d}"))
def response_status(ctx: ScenarioContext, code: int) -> None:
    assert ctx.last_response.status_code == code, f"expected {code}, got {_body(ctx)}"


@then(parsers.re(r'the response header "(?P<name>[^"]+)" is present'))
def header_present(ctx: ScenarioContext, name: str) -> None:
    assert name in ctx.last_response.headers, f"no header {name}: {dict(ctx.last_response.headers)}"


@then(parsers.re(r'the response header "(?P<name>[^"]+)" equals "(?P<value>[^"]*)"'))
def header_equals(ctx: ScenarioContext, name: str, value: str) -> None:
    assert ctx.last_response.headers.get(name) == value, f"{name}: {ctx.last_response.headers.get(name)!r}"


@then(parsers.re(r'the response JSON field "(?P<field>[^"]+)" equals "(?P<value>[^"]*)"'))
def json_field_equals(ctx: ScenarioContext, field: str, value: str) -> None:
    assert "json" in ctx.last_response.headers.get("content-type", ""), f"not JSON: {_body(ctx)}"
    assert str(_field(ctx.last_response.json(), field)) == value, f"{field}: {_body(ctx)}"


@then(parsers.re(r'the response is a problem document with code "(?P<code>[^"]+)"'))
def problem_document(ctx: ScenarioContext, code: str) -> None:
    r = ctx.last_response
    assert r.headers.get("content-type", "").startswith(PROBLEM_JSON), f"not a problem document: {_body(ctx)}"
    assert r.json().get("code") == code, f"problem code: {_body(ctx)}"


@then(parsers.re(r'the page contains "(?P<text>[^"]+)"'))
def page_contains(ctx: ScenarioContext, text: str) -> None:
    assert text in ctx.last_response.text, f"'{text}' not in page: {_body(ctx)}"


@then(parsers.re(r'the page does not contain "(?P<text>[^"]+)"'))
def page_does_not_contain(ctx: ScenarioContext, text: str) -> None:
    assert text not in ctx.last_response.text, f"'{text}' unexpectedly in page"
