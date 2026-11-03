# Product Requirements: [INITIATIVE NAME]

**Slug**: `[slug]` | **BRD**: [brd.md](./brd.md) | **Questions**: [open-questions.yaml](./open-questions.yaml)
**Product owner**: [name / role] | **Version**: 0.1 | **Status**: Draft

## 1. Goals and success metrics

| Metric | Target | Timeframe | Source (BR / OQ) |
|--------|--------|-----------|------------------|
| [e.g. Median application decision time] | [≤ 2 min] | [3 months after go-live] | BR-002 |

## 2. Users and personas

- **[Persona]**: [goal, context, frequency]

## 3. Features

Each feature becomes one Spec Kit feature (`specs/NNN-name/`). Acceptance criteria are
numbered globally in this PRD (`AC-001`…) and always cite the BRs they satisfy.

### FEAT-01: [Feature name]

**Satisfies**: BR-001, BR-002
**Summary**: [one paragraph]

Acceptance criteria:

- **AC-001** (BR-001): Given [context], when [action], then [observable outcome].
- **AC-002** (BR-002): Given ..., when ..., then ...

Business NFRs stated by the BRD (if any):

- [e.g. "Decision returned within 2 s at p95" (BR-004)]

### FEAT-02: [Feature name]

...

## 4. Out of scope

Every BR not covered by an AC must be listed here with a reason.

- BR-0xx — [reason: deferred to phase 2 / handled by system X / rejected by owner on DATE]

## 5. Dependencies and integrations

- [Upstream/downstream systems, owners, interface type]

## 6. Release slicing

| Release | Features | Notes |
|---------|----------|-------|
| MVP | FEAT-01 | |
