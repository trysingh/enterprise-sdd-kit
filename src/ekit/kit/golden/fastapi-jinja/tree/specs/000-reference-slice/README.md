# 000-reference-slice (exemplar)

One complete feature, already green, in the exact shape the pipeline expects. It is part of the
golden landing zone (frozen) and exists so a model writing a real feature has something concrete
to copy.

| Pipeline artifact | Here | In your feature `NNN-slug` |
|---|---|---|
| Gherkin | `specs/000-reference-slice/features/greeting.feature` | `specs/NNN-slug/features/*.feature`, tags `@SCN-NNN-nn @AC-xxx` |
| Step module | `tests/acceptance/test_000_reference_slice.py` | `tests/acceptance/test_NNN_slug.py` |
| Shared steps | `tests/acceptance/conftest.py` | reuse them; add only domain-language steps |
| Scenario state | `ctx: ScenarioContext`, `ctx.remember` / `ctx.recall` | the same; never a dict fixture |
| Feature package | `src/app/features/f000_reference/` | `ekit feature package NNN-slug` |
| Router registration | `app.main` (reference only) | `src/app/features/registry.py` |
| Unit tests | `tests/unit/test_reference_service.py` | `tests/unit/features/test_<slug>_*.py` |

Rules (`RED-NO-EXEMPLAR`): never import `app.features.f000_reference`, never bind
`greeting.feature`, never reuse `@SCN-000-*` ids, never name a feature after it.

It is mounted only outside production (`APP_ENV != prod`, `APP_REFERENCE_SLICE_ENABLED`).
