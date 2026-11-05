# Engineering Baseline Conformance (platform scope)

**Stack**: fastapi-jinja | **Baseline**: enterprise-sdd-kit golden landing zone 1.0.0 | **Last reviewed**: installed by `ekit init`

Rows are parsed by `ekit gate baseline`. Keep the column order. This record ships with the golden
landing zone and is frozen with it: it changes together with the code it describes.

## Engineering Baseline Conformance

| NFR | Title | Status | Evidence / Justification | ADR |
|-----|-------|--------|--------------------------|-----|
| SEC-01 | Authentication via central identity provider | Addressed | src/app/core/security.py (`current_user`, OIDC JWT via JWKS); src/app/core/settings.py refuses `auth_mode=dev` in prod; tests/unit/test_core_settings.py | |
| SEC-04 | Secrets never in source | Addressed | src/app/core/settings.py (environment / `.env` only); .gitignore (`.env*`); .pre-commit-config.yaml (gitleaks) | |
| SEC-05 | Dependency and vulnerability scanning | Addressed | uv.lock committed; `ekit run sca` (pip-audit) | |
| SEC-06 | HTTP security headers and CORS | Addressed | src/app/core/middleware.py (`SECURITY_HEADERS`, explicit CORS origins); SCN-000-03 | |
| SEC-08 | CSRF protection for cookie-based sessions | Addressed | src/app/core/middleware.py (`CsrfCookieMiddleware`); src/app/web/__init__.py (`require_csrf` on every `web_router`); SCN-000-15, SCN-000-16 | |
| API-02 | Standard error model | Addressed | src/app/core/errors.py (RFC 9457 problem documents with `code`); SCN-000-02; tests/unit/test_core_errors.py | |
| API-03 | Versioning and backward compatibility | Addressed | src/app/api/__init__.py (`/api/v1`); src/app/main.py mounts every feature API under it | |
| OBS-01 | Structured logging | Addressed | src/app/core/logging.py (structlog JSON, `redact`); tests/unit/test_core_logging.py | |
| OBS-02 | Correlation / trace propagation | Addressed | src/app/core/middleware.py (`CorrelationMiddleware`: X-Correlation-ID / traceparent, bound to log context); SCN-000-01 | |
| OBS-03 | Health and readiness endpoints | Addressed | src/app/api/health.py (`/health/live`, `/health/ready` checks the database); SCN-000-01 | |
| OBS-04 | Metrics and tracing (OpenTelemetry) | Addressed | src/app/main.py (`FastAPIInstrumentor` when `APP_OTEL_ENABLED`; exporter via OTEL_* variables) | |
| REL-01 | Timeouts on all outbound calls | Addressed | src/app/core/http.py (shared client, connect/read timeouts); src/app/core/db.py (pool timeout) | |
| REL-03 | Graceful shutdown | Addressed | src/app/main.py (`lifespan` closes HTTP client and DB pool); Dockerfile (`--timeout-graceful-shutdown 20`) | |
| DATA-01 | Versioned schema migrations | Addressed | alembic.ini; migrations/env.py (URL from settings); migrations/versions/ | |
| PERF-02 | Frontend performance budget | Addressed | src/app/static (no framework, one small ES module); server-rendered pages | |
| QA-03 | Coverage floor | Addressed | `ekit run coverage` (`--cov-fail-under=80`) | |
| QA-04 | Lint, format and static analysis | Addressed | pyproject.toml (`[tool.ruff]`, `[tool.mypy] strict`); `ekit run lint`, `ekit run typecheck` | |
| ENV-01 | Isolated, pinned, reproducible runtime environment | Addressed | .python-version (3.12); uv-managed `.venv` (`ekit run install`); .gitignore (`.venv/`) | |
| CFG-01 | Twelve-factor configuration | Addressed | src/app/core/settings.py (`Settings`, fail-fast validation; feature settings use their own prefix) | |
| OPS-01 | Reproducible build and container image | Addressed | Dockerfile (multi-stage, `uv sync --locked`, `USER 10001`) | |
| OPS-02 | Pipeline-ready commands | Addressed | profile commands via `ekit run …` (argv lists, non-interactive) | |
| UX-02 | Internationalization-ready | Addressed | src/app/core/i18n.py (`t()` exposed to templates; features `register()` strings) | |

## Notes

- Feature-scope NFRs (authorisation per route, input validation, audit, accessibility, budgets …)
  are assessed in each feature's plan; the core provides `require()`, Pydantic boundaries and
  `app.core.db.Base` for them.
- The reference slice (`src/app/features/f000_reference`) is not mounted in production.
