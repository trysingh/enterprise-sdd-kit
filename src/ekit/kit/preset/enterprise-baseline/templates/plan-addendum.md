

## Stack Profile *(enterprise baseline)*

**Stack**: [from `ekit context`] | **Profiles**: [backend/…, frontend/…]
Follow the profile `layout`, `controls` and `agent_rules`. Deviations need an ADR.

## Engineering Baseline Conformance *(mandatory — parsed by `ekit gate plan`)*

One row for **every feature-scope NFR** that `ekit context` lists for this stack.
Allowed statuses: `Addressed` (say how, name the scenario/test), `N/A` (why it does not apply
to this feature), `Waived` (why + ADR id). Keep the column order.
With an approved wave plan, `Deferred (W2)` is also allowed for an NFR the plan defers until W2
(never for a non-deferrable one); it becomes an error once W2 is current.

| NFR | Title | Status | Evidence / Justification | ADR |
|-----|-------|--------|--------------------------|-----|
| SEC-02 | Authorization enforced server-side | Addressed | `require("loan:approve")` on POST /api/v1/loans/{id}/approve; @SCN-003-04 | |

## Resilience and Data Boundaries

- Outbound dependencies: [name → timeout, retry policy, circuit breaker]
- Transaction boundaries: [write path → boundary, failure behaviour]
- Audit events: [operation → event name, fields]
