"""Day-0 seams (golden 1.1.0): dev-user principal, audit sink, request id, data owner."""

from __future__ import annotations

import base64

import pytest
from starlette.requests import Request

from app.core.audit import InMemoryAuditSink, LogAuditSink
from app.core.ownership import OWNER_COLUMN, OwnedMixin
from app.core.principal import SESSION_COOKIE, DevUserProvider
from app.core.requestid import REQUEST_ID_HEADER, request_id_for

USERS = "config/dev-users.yaml"


def _request(headers: dict[str, str]) -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_dev_users_are_refused_outside_dev_and_test() -> None:
    with pytest.raises(RuntimeError, match="dev/test only"):
        DevUserProvider(USERS, "prod")
    DevUserProvider(USERS, "dev")
    DevUserProvider(USERS, "test")


def test_basic_auth_identifies_a_dev_user_and_rejects_a_wrong_password() -> None:
    provider = DevUserProvider(USERS, "test")
    who = provider.authenticate(_request({"Authorization": _basic("asha", "asha-dev")}))
    assert who is not None and who.id == "asha" and who.roles == ("user",)
    assert provider.authenticate(_request({"Authorization": _basic("asha", "nope")})) is None
    assert provider.authenticate(_request({"Authorization": "Basic !!!"})) is None
    assert provider.authenticate(_request({})) is None


def test_session_cookie_round_trip_and_forgery() -> None:
    provider = DevUserProvider(USERS, "test")
    token = provider.issue_session("ravi")
    who = provider.authenticate(_request({"Cookie": f"{SESSION_COOKIE}={token}"}))
    assert who is not None and who.id == "ravi"
    forged = "admin." + token.rpartition(".")[2]
    assert provider.authenticate(_request({"Cookie": f"{SESSION_COOKIE}={forged}"})) is None


def test_audit_sinks_accept_the_same_call() -> None:
    sink = InMemoryAuditSink()
    sink.record("asha", "send", "message:1", {"to": "ravi"})
    assert sink.events == [("asha", "send", "message:1", {"to": "ravi"})]
    LogAuditSink().record("asha", "send", "message:1")


def test_request_id_is_kept_when_safe_and_generated_otherwise() -> None:
    assert request_id_for(_request({REQUEST_ID_HEADER: "req-12345678"})) == "req-12345678"
    generated = request_id_for(_request({REQUEST_ID_HEADER: "bad id!"}))
    assert generated != "bad id!" and len(generated) == 32


def test_data_owner_convention() -> None:
    assert OWNER_COLUMN == "owner_id" and "owner_id" in OwnedMixin.__annotations__
