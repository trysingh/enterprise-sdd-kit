"""Test-wide settings (golden core). Tests never talk to real infrastructure."""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_AUTH_MODE", "dev")
os.environ.setdefault("APP_LOG_JSON", "false")
os.environ.setdefault("APP_SESSION_COOKIE_SECURE", "false")
