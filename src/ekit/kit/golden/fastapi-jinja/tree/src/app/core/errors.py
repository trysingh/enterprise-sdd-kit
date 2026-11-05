"""API-02: one error model, RFC 9457 problem documents (`application/problem+json`) with a stable `code`.

Domain code raises `AppError` subclasses; only this module turns them into HTTP responses.
Before a feature is implemented, its route calls `not_implemented()`: a 501 problem document, so
red tests fail on an assertion about the response rather than crashing the harness.
"""

from __future__ import annotations

from typing import Any, NoReturn

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
log = structlog.get_logger()


class AppError(Exception):
    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(self, detail: str = "", **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


class NotFound(AppError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "Conflict"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "Forbidden"


class Unauthorized(AppError):
    status, code, title = 401, "unauthorized", "Authentication required"


class NotImplementedYet(AppError):
    status, code, title = 501, "not_implemented", "Not implemented yet"


def not_implemented(what: str = "") -> NoReturn:
    """The only allowed body of a route stub before `ekit gate red` (and until implemented)."""
    raise NotImplementedYet(what or "This behaviour is specified but not implemented yet")


def problem(status: int, code: str, title: str, detail: str, request: Request, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"about:blank#{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": request.url.path,
    }
    cid = getattr(request.state, "correlation_id", None)
    if cid:
        body["correlation_id"] = cid
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.title, exc.detail, request, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
        return problem(
            422,
            "validation_failed",
            "Request validation failed",
            "One or more fields are invalid",
            request,
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(
            exc.status_code, "http_error"
        )
        return problem(exc.status_code, code, str(exc.detail), str(exc.detail), request)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", path=request.url.path, error_type=type(exc).__name__)
        return problem(
            500, "internal_error", "Internal server error", "An unexpected error occurred", request
        )
