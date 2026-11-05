# ADR-0001: Record architecture decisions

**Status**: Accepted (installed with the golden landing zone)

## Context
Significant technical decisions and every waived NFR must be traceable (DOC-01, principle VIII).

## Decision
Decisions are recorded as numbered Markdown files in `docs/adr/`. New ADRs are created with
`ekit adr new "Title"`, which takes the next free number, so two ADRs never share one
(`BASE-ADR-UNIQUE`, `PLAN-ADR-UNIQUE`).

## Consequences
A `Waived` row in a conformance table cites an ADR id such as `ADR-0003`.
