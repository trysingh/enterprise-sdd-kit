"""REL-01: the one outbound HTTP client, with connect/read timeouts. Feature adapters use `get_http()`."""

from __future__ import annotations

import httpx

from app.core.settings import get_settings

_client: httpx.AsyncClient | None = None


def get_http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(s.http_read_timeout_seconds, connect=s.http_connect_timeout_seconds)
        )
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
