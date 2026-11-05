from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.errors import PROBLEM_JSON, Conflict, install_error_handlers, not_implemented
from app.core.middleware import install_middleware
from app.core.settings import Settings


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    install_middleware(app, Settings(env="test"))
    r = APIRouter()

    @r.get("/stub")
    def stub() -> None:
        not_implemented()

    @r.get("/conflict")
    def conflict() -> None:
        raise Conflict("already exists", field="name")

    app.include_router(r)
    return TestClient(app, raise_server_exceptions=False)


def test_a_stub_is_a_501_problem_document() -> None:
    res = _client().get("/stub")
    assert res.status_code == 501 and res.headers["content-type"].startswith(PROBLEM_JSON)
    assert res.json()["code"] == "not_implemented"


def test_domain_errors_carry_code_extra_fields_and_correlation_id() -> None:
    res = _client().get("/conflict", headers={"X-Correlation-ID": "unit-test-0001"})
    body = res.json()
    assert res.status_code == 409 and body["code"] == "conflict" and body["field"] == "name"
    assert body["correlation_id"] == "unit-test-0001" == res.headers["X-Correlation-ID"]
