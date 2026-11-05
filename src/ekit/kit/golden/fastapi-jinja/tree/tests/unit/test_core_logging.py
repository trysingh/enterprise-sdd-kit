from __future__ import annotations

from app.core.logging import REDACTED, redact


def test_sensitive_fields_are_redacted() -> None:
    event = redact(
        None, "info", {"event": "login", "password": "x", "Authorization": "Bearer y", "user": "u1"}
    )
    assert event["password"] == REDACTED and event["Authorization"] == REDACTED and event["user"] == "u1"
