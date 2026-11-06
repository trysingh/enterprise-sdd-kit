# Architecture: [INITIATIVE NAME]

**Status**: Draft | **Approved by**: (a person runs `ekit design approve --by`) | **Facts**: [design.yaml](./design.yaml)

One to two pages. `design.yaml` holds the same facts in machine-readable form and is what gates and
traceability read; keep the two in step. Everything after this note is written in the language of
its ports and operations.

## 1. Topology

[The chosen shape (e.g. central server, single deployable) in two or three sentences.]
**Rejected option**: [what else was considered and why not.]

## 2. Ports

| Port | Methods | Dependency | Why it is a seam |
|------|---------|------------|------------------|
| [MessageStore] | [append, history] | [get_message_store] | [persistence may change] |

Each port is a `Protocol` with one adapter and one in-memory fake.

## 3. Core data model

[Entities, keys, relations; every feature table has an owner or participant column (`owner_id`).]

## 4. Interface

[Operations by FastAPI `operation_id` (= OpenAPI operationId) and pages, per feature. See
`features:` in design.yaml.]

## 5. Day-0 seams

| Seam | Day 0 | Replaced later by |
|------|-------|-------------------|
| principal | dev users (`config/dev-users.yaml`) | OIDC / SSO |
| audit | log sink | durable store |
| request_id | middleware | OpenTelemetry trace context |
| config | environment | vault / platform config |
| data_owner | `owner_id` column | row-level authorization |

## 6. Slices

| Slice | Features | Journeys |
|-------|----------|----------|
| S0 | [FEAT-01, FEAT-02] | [J-01] |

## 7. Decisions

| Id | Title | Status | ADR |
|----|-------|--------|-----|
| D1 | Topology | accepted | ADR-0002 |
