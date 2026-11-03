# [PROJECT_NAME] Constitution

<!-- Principles I–VIII are fixed by the enterprise baseline (enterprise-sdd-kit).
     /speckit.constitution may refine wording and add project principles (IX+),
     but must not weaken or remove I–VIII. Changes to them need an ADR. -->

## Core Principles

### I. Traceability end to end (NON-NEGOTIABLE)
Every line of production behaviour traces back through a Gherkin scenario (`@SCN-…`) to an
acceptance criterion (`AC-…`) in a PRD, and from there to a business requirement (`BR-…`) in a
BRD. Work that cannot be traced is either out of scope or needs a new requirement first.

### II. No guessing business facts
Ambiguities are recorded in the PRD's `open-questions.yaml` and answered by the accountable
business owner. Blocking questions stop specification of the affected feature
(`ekit gate ready`). Engineers and agents never invent business rules, thresholds or data.

### III. Specification before code
BRD → PRD → spec → plan → tasks is mandatory and each hand-off passes its `ekit gate`.
`[NEEDS CLARIFICATION]` markers never survive into a plan.

### IV. Test-first (NON-NEGOTIABLE)
Acceptance scenarios and unit tests are written and observed failing (`ekit gate red`, recorded
in `.ekit/ledger/`) before implementation. A feature is done only when `ekit gate green` passes.

### V. Engineering baseline by default
The enterprise baseline (`ekit context`) applies to every feature. Platform-scope NFRs are met
once in the landing zone; feature-scope NFRs are assessed in every plan. Deviations are
`Waived` with an ADR, never silent.

### VI. Secure by design
Deny by default, validate at the boundary, encode on output, least privilege, no secrets in the
repository, dependencies pinned and scanned.

### VII. Observable and operable
Structured logs with correlation ids, health/readiness, metrics and audit trails for business
state changes are part of the definition of done, not later hardening.

### VIII. Simplicity and reversibility
Prefer the stack's conventions and the smallest design that meets the spec. Every significant
or irreversible decision is an ADR in `docs/adr/`.

[PRINCIPLE_9_NAME]
[PRINCIPLE_9_DESCRIPTION]
<!-- Optional project-specific principles. Remove these placeholders if none. -->

## Technology Stack

[SECTION_2_CONTENT]
<!-- Filled from `ekit context`: stack id, profiles, runtime versions. Changing the stack needs an ADR. -->

## Quality Gates

| Stage | Gate | Command |
|-------|------|---------|
| BRD → PRD | intake | `ekit gate intake --prd docs/requirements/<slug>` |
| PRD → spec | ready | `ekit gate ready --prd docs/requirements/<slug>` |
| spec → plan | spec | `ekit gate spec` |
| spec → Gherkin | scenarios | `ekit gate scenarios` |
| plan → tasks | plan | `ekit gate plan` |
| tests → code | red | `ekit gate red` |
| code → done | green | `ekit gate green` |
| landing zone | baseline | `ekit gate baseline` |

Gate policy: `.ekit/kit/policy/gates.policy.yaml`. Relaxations only through
`.ekit/policy.overrides.yaml` with a reason, reviewed in the pull request.

## Governance

This constitution supersedes other practices. Amendments to principles I–VIII require an ADR
and an update of the enterprise kit version (`ekit upgrade`). Reviews verify gate results, not
only code.

**Version**: [CONSTITUTION_VERSION] | **Ratified**: [RATIFICATION_DATE] | **Last Amended**: [LAST_AMENDED_DATE]
