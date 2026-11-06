"""Day-0 seam "request_id": `X-Request-Id` in or generated, echoed on the response, on every log line.

A later wave replaces it with OpenTelemetry trace context (OBS-04); log lines keep the same field.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_HEADER = "X-Request-Id"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def request_id_for(request: Request) -> str:
    given = request.headers.get(REQUEST_ID_HEADER, "")
    return given if _SAFE.match(given) else uuid.uuid4().hex


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request_id_for(request)
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response
