

## Enterprise TDD Policy *(overrides any "OPTIONAL" test markers above)*

Tests are **mandatory** for every user story. Within each user-story phase, tasks are ordered:

1. **Scenarios** — confirm the story's `@SCN` scenarios exist in `features/` (gate `scenarios`).
2. **Red** — step definitions + unit tests written and failing (`ekit gate red`), ledger committed.
3. **Implement** — minimum code to make them pass, following the stack profile `controls`.
4. **Green** — `ekit gate green` passes (scenarios, unit, lint, coverage).
5. **Refactor** — keep green; no behaviour change.

Every task that implements behaviour names the scenario(s) it turns green, e.g.
`- [ ] T014 [US1] Implement approval service in src/app/services/approval.py (→ SCN-003-02, SCN-003-03)`.

Feature-scope NFRs marked `Addressed` in plan.md get explicit tasks (e.g. audit event,
authorization rule, input schema) linked to the scenario that proves them.

The last task of every feature is: `- [ ] Tnnn Run ekit gate green and fix until it passes`.
