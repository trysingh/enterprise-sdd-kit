

## Traceability *(mandatory — enterprise baseline)*

**PRD**: [docs/requirements/<slug>/prd.md] | **PRD feature(s)**: [FEAT-xx]

| Acceptance criterion | Business requirement(s) | Covered by (FR / user story) |
|----------------------|-------------------------|------------------------------|
| AC-001 | BR-001 | FR-001, User Story 1 |

Every AC listed in `trace.yaml` must appear in this table (`ekit gate spec`).

## Data Classification *(mandatory when Key Entities exist)*

| Entity / attribute | Classification (Public / Internal / Confidential / Restricted) | PII? | Retention |
|--------------------|-----------------------------------------------------------------|------|-----------|
| [Entity.attribute] | [Confidential] | [Yes] | [per policy / TBD: OQ-xxx] |

## Business Non-Functional Requirements *(only those stated in BRD/PRD)*

- [e.g. p95 decision latency ≤ 2 s (BR-004)]

Engineering NFRs (security, logging, resilience, …) are **not** repeated here; they come from
the engineering baseline and are assessed in plan.md.
