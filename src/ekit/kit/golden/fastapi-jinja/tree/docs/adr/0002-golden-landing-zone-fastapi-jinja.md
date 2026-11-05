# ADR-0002: Start from the golden fastapi-jinja landing zone

**Status**: Accepted (installed with the golden landing zone)

## Context
__PROJECT_NAME__ uses the `fastapi-jinja` stack of the enterprise SDD kit. A landing zone generated
from nothing by a model varies from run to run, and smaller models in particular loop on it or
rewrite it later during feature work.

## Decision
The project starts from the kit's golden landing zone (FastAPI, server-rendered Jinja2, uv,
pytest-bdd): a reviewed codebase that already meets every platform-scope NFR. Its core files are
frozen against agent edits; features extend it through seams (feature packages, the router
registry, feature templates, migrations). Kit upgrades bring new golden revisions as a
three-way merge; conflicts are resolved by a person.

## Consequences
- `ekit gate baseline` and `ekit gate green` fail when a core file differs from
  `.ekit/golden.lock.yaml` (`BASE-GOLDEN-INTACT`, `GREEN-GOLDEN-INTACT`).
- Changing core behaviour is a reviewed change: `ekit baseline unfreeze --reason`, edit,
  `ekit baseline accept --reason`, with an ADR when it changes a decision.
