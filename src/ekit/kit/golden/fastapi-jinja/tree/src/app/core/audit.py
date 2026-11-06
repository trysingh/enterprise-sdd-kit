"""Day-0 seam "audit": who did what to which target. `LogAuditSink` writes a structured log line.

Feature services call `sink.record(actor, action, target, data)` for every state change; a later wave
swaps the sink for a durable, tamper-evident store behind `get_audit_sink`.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Protocol

import structlog


class AuditSink(Protocol):
    def record(self, actor: str, action: str, target: str, data: Mapping[str, Any] | None = None) -> None: ...


class LogAuditSink:
    def record(self, actor: str, action: str, target: str, data: Mapping[str, Any] | None = None) -> None:
        structlog.get_logger("audit").info("audit", actor=actor, action=action, target=target, data=dict(data or {}))


class InMemoryAuditSink:
    """For unit tests: `events` keeps every record."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str, dict[str, Any]]] = []

    def record(self, actor: str, action: str, target: str, data: Mapping[str, Any] | None = None) -> None:
        self.events.append((actor, action, target, dict(data or {})))


@lru_cache(maxsize=1)
def get_audit_sink() -> AuditSink:
    return LogAuditSink()
