"""UX-02: user-facing strings come from a catalogue through `t()`, exposed to every template."""

from __future__ import annotations

CATALOG: dict[str, dict[str, str]] = {
    "en": {
        "app.skip_to_content": "Skip to content",
        "home.title": "Welcome",
        "home.body": "The application is running.",
    },
}
DEFAULT_LOCALE = "en"


def t(key: str, locale: str = DEFAULT_LOCALE, **params: str) -> str:
    text = CATALOG.get(locale, {}).get(key) or CATALOG[DEFAULT_LOCALE].get(key) or key
    return text.format(**params) if params else text


def register(locale: str, strings: dict[str, str]) -> None:
    """Feature packages add their strings at import time: `register("en", {"chat.title": "Chat"})`."""
    CATALOG.setdefault(locale, {}).update(strings)
