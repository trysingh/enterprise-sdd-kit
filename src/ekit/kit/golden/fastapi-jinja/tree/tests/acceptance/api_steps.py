"""Generic API step library for journeys (golden core, frozen). Imported by conftest.py.

Journeys are Gherkin through the HTTP API. Operations are addressed by `operation_id` (resolved
from the app's OpenAPI), the caller is a dev user from config/dev-users.yaml, and values are chained
with remember / recall, so most journeys need no step code of their own.

  Given I am signed in as "<dev user>"
  When I call "<operation_id>"
  When I call "<operation_id>" with <name> "<value>" [and <name> "<value>" ...]
        typed arguments: numbers unquoted (3, 2.5), booleans true / false, null; "true" in quotes stays text
  When I open the page "<path>"
  Then the call succeeds
  Then/And I remember "<dotted.field>" from the response as "<name>"          (use later as "{name}")
  Then the response contains "<text>"                                      ("{name}" inside it is the remembered value)
  Then the response contains the remembered "<name>"
  Then the response contains "<text>" with <field> <number>              (an object holding both)
  Then the response has at least <n> items
  Then the response does not contain "<text>"
  Then the call fails with status <code>                                  (a negative path: 400, 403, 404, 409 ...)
  Then the list is empty / the list "<dotted.field>" is empty              (the response itself, or a field of it)
  And the call to "<operation_id>" now shows "<text>" with <field> <number>

A value written as "{name}" is replaced by the remembered value; in `the response contains` / `does not contain`
it may sit inside the text, and an unknown {name} or <name> is an error, not a literal. Path parameters, query parameters
and JSON body fields are told apart by the operation's OpenAPI description.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from tests.acceptance.support import ScenarioContext
from tests.acceptance.support.paths import REPO_ROOT

USERS_FILE = REPO_ROOT / "config" / "dev-users.yaml"
ARG_RE = re.compile(r'(\w+) (?:"([^"]*)"|(-?\d+(?:\.\d+)?)|(true|false|null)\b)')
LITERALS = {"true": True, "false": False, "null": None}


def dev_users() -> dict[str, Any]:
    data = yaml.safe_load(USERS_FILE.read_text(encoding="utf-8")) or {}
    return dict(data.get("users") or {})


def _value(ctx: ScenarioContext, raw: str) -> Any:
    m = re.fullmatch(r"\{(\w+)\}", raw)
    return ctx.recall(m.group(1)) if m else raw


PLACEHOLDER_RE = re.compile(r"\{(\w+)\}|<(\w+)>")
HTML_TAGS = frozenset("a b body br button div em form h1 h2 h3 h4 h5 h6 head hr html i img input label li link meta nav "
                      "ol option p pre script section select small span strong style table tbody td textarea th thead title tr ul".split())


def resolve_text(ctx: ScenarioContext, text: str) -> str:
    """Replace each `{name}` with the value remembered in this scenario. An unknown `{name}` (or a `<name>` left
    unexpanded from a Scenario Outline) is an error, never a literal: otherwise a negative check passes vacuously."""
    def one(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        if m.group(2) and name.lower() in HTML_TAGS:
            return m.group(0)                # a real tag in an HTML assertion, not a placeholder
        try:
            return str(ctx.recall(name))
        except LookupError as exc:           # MissingScenarioStateError: broken test glue, not a red
            raise type(exc)(
                f'"{m.group(0)}" in "{text}" is not a remembered value and looks like an unexpanded placeholder; '
                f'remember it first with `I remember "<field>" from the response as "{name}"` ({exc})'
            ) from None
    return PLACEHOLDER_RE.sub(one, text)


def _text(value: Any) -> str:
    return json.dumps(value) if isinstance(value, bool) or value is None else str(value)


def parse_args(ctx: ScenarioContext, text: str | None) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for name, quoted, number, literal in ARG_RE.findall(text or ""):
        if literal:
            args[name] = LITERALS[literal]
        elif number:
            args[name] = float(number) if "." in number else int(number)
        else:
            args[name] = _value(ctx, quoted)
    return args


def operation(app: FastAPI, operation_id: str) -> tuple[str, str, dict[str, Any]]:
    known: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, item in app.openapi().get("paths", {}).items():
        for method, spec in item.items():
            if isinstance(spec, dict) and spec.get("operationId"):
                known[spec["operationId"]] = (method.upper(), path, spec)
    assert operation_id in known, f'no operation "{operation_id}" in the OpenAPI document; known: {sorted(known)}'
    return known[operation_id]


def call_operation(ctx: ScenarioContext, app: FastAPI, operation_id: str, args: dict[str, Any]) -> None:
    method, path, spec = operation(app, operation_id)
    declared = {p["name"]: p["in"] for p in spec.get("parameters", [])}
    rest = dict(args)
    url = path
    for name, where in declared.items():
        if where == "path":
            assert name in rest, f'operation "{operation_id}" needs the path parameter "{name}"'
            url = url.replace("{" + name + "}", quote(_text(rest.pop(name)), safe=""))
    query = {n: rest.pop(n) for n, where in declared.items() if where == "query" and n in rest}
    assert not rest or "requestBody" in spec, f'operation "{operation_id}" takes no argument(s) {sorted(rest)}'
    ctx.response = ctx.http.request(method, url, params=query or None, json=rest or None)


def walk(data: Any) -> Iterator[Any]:
    yield data
    if isinstance(data, dict):
        for v in data.values():
            yield from walk(v)
    elif isinstance(data, list):
        for v in data:
            yield from walk(v)


def shows(data: Any, text: str, field: str, number: str) -> bool:
    for o in walk(data):
        if isinstance(o, dict) and ((text in map(str, o.values()) and str(o.get(field)) == number) or str(o.get(text)) == number):
            return True
    return False


# ----------------------------------------------------------------------------------- Given
@given(parsers.re(r'I am signed in as "(?P<user>[^"]+)"$'))
def signed_in_as(ctx: ScenarioContext, app: FastAPI, user: str) -> None:
    users = dev_users()
    assert user in users, f'"{user}" is not a dev user in config/dev-users.yaml (known: {sorted(users)})'
    token = base64.b64encode(f"{user}:{users[user]['password']}".encode()).decode()
    ctx.client = TestClient(app, headers={"Authorization": f"Basic {token}"})
    ctx.remember("user", user)


# ------------------------------------------------------------------------------------ When
@when(parsers.re(r'I call "(?P<op>[^"]+)"(?: with (?P<args>.+))?$'))
def call_by_operation_id(ctx: ScenarioContext, app: FastAPI, op: str, args: str | None) -> None:
    call_operation(ctx, app, op, parse_args(ctx, args))


@when(parsers.re(r'I open the page "(?P<path>[^"]+)"$'))
def open_page(ctx: ScenarioContext, path: str) -> None:
    ctx.response = ctx.http.get(path)


# ------------------------------------------------------------------------------------ Then
@then("the call succeeds")
def call_succeeds(ctx: ScenarioContext) -> None:
    r = ctx.last_response
    assert 200 <= r.status_code < 300, f"expected a 2xx response, got {r.status_code}: {r.text[:300]}"


@then(parsers.re(r'the call fails with status (?P<code>\d{3})$'))
def call_fails_with(ctx: ScenarioContext, code: str) -> None:
    r = ctx.last_response
    assert r.status_code == int(code), f"expected status {code}, got {r.status_code}: {r.text[:300]}"


@then(parsers.re(r'the response does not contain "(?P<text>[^"]*)"$'))
def response_does_not_contain(ctx: ScenarioContext, text: str) -> None:
    text = resolve_text(ctx, text)
    assert text not in ctx.last_response.text, f'"{text}" is in the response but should not be: {ctx.last_response.text[:300]}'


@then(parsers.re(r'the list(?: "(?P<field>[^"]+)")? is empty$'))
def list_is_empty(ctx: ScenarioContext, field: str | None) -> None:
    cur: Any = ctx.last_response.json()
    for part in (field.split(".") if field else []):
        assert isinstance(cur, dict) and part in cur, f'the response has no field "{field}" (at "{part}"): {cur!r}'
        cur = cur[part]
    assert isinstance(cur, list), f"expected a list{f' at {field!r}' if field else ''}, got {type(cur).__name__}: {cur!r}"
    assert cur == [], f"expected an empty list, got {len(cur)} item(s): {str(cur)[:300]}"


@then(parsers.re(r'I remember "(?P<field>[^"]+)" from the response as "(?P<name>[^"]+)"$'))
def remember_field(ctx: ScenarioContext, field: str, name: str) -> None:
    cur: Any = ctx.last_response.json()
    for part in field.split("."):
        assert isinstance(cur, dict) and part in cur, f'the response has no field "{field}" (at "{part}"): {cur!r}'
        cur = cur[part]
    ctx.remember(name, cur)


@then(parsers.re(r'the response contains "(?P<text>[^"]*)"$'))
def response_contains(ctx: ScenarioContext, text: str) -> None:
    text = resolve_text(ctx, text)
    assert text in ctx.last_response.text, f'"{text}" not in the response: {ctx.last_response.text[:300]}'


@then(parsers.re(r'the response contains the remembered "(?P<name>[^"]+)"$'))
def response_contains_remembered(ctx: ScenarioContext, name: str) -> None:
    value = str(ctx.recall(name))
    assert value in json.dumps(ctx.last_response.json()) or value in ctx.last_response.text, (
        f'remembered "{name}" ({value}) not in the response: {ctx.last_response.text[:300]}'
    )


@then(parsers.re(r'the response contains "(?P<text>[^"]*)" with (?P<field>\w+) (?P<number>-?\d+)$'))
def response_contains_with(ctx: ScenarioContext, text: str, field: str, number: str) -> None:
    assert shows(ctx.last_response.json(), text, field, number), (
        f'no entry "{text}" with {field} {number} in: {ctx.last_response.text[:300]}'
    )


@then(parsers.re(r'the response has at least (?P<n>\d+) items?$'))
def response_has_items(ctx: ScenarioContext, n: str) -> None:
    data = ctx.last_response.json()
    items = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
    assert len(items) >= int(n), f"expected at least {n} items, got {len(items)}: {ctx.last_response.text[:300]}"


@then(parsers.re(r'the call to "(?P<op>[^"]+)" now shows "(?P<text>[^"]*)" with (?P<field>\w+) (?P<number>-?\d+)$'))
def call_now_shows(ctx: ScenarioContext, app: FastAPI, op: str, text: str, field: str, number: str) -> None:
    call_operation(ctx, app, op, {})
    call_succeeds(ctx)
    assert shows(ctx.last_response.json(), text, field, number), (
        f'after calling "{op}", no entry "{text}" with {field} {number} in: {ctx.last_response.text[:300]}'
    )
