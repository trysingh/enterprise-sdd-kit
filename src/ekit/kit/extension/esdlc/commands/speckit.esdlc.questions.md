---
description: "Work the open-questions register: answer interactively or export/import for the product manager; run gate ready"
handoffs:
  - label: Specify a feature
    agent: speckit.specify
    prompt: Specify the next PRD feature
---

# Open questions loop

The register `docs/requirements/<slug>/open-questions.yaml` is the single source of truth for
what is still unknown. Answers come from the customer / product manager, never from you.

## User Input

```text
$ARGUMENTS
```

Input may name the PRD slug, a mode (`ask`, `export`, `import <file>`), or nothing.
If there is exactly one folder under `docs/requirements/`, use it; otherwise ask which.

## Modes

**ask (default, a stakeholder is present in the session)**
1. Run `ekit questions list --prd docs/requirements/<slug> --status open` and present the
   questions grouped by blocking first, one at a time, with context and options.
2. Record each answer verbatim in the register: `status: answered`, `answer`, `answered_by`
   (ask the user who decided), `answered_on` (today, ISO date). A user may also mark a question
   `deferred` with a reason; a deferred *blocking* question still blocks.
3. Propagate answers: update `prd.md` (replace `[TBD: OQ-xxx]`, add/adjust ACs, add BRs only if
   the answer introduces a new business obligation and say so). New ambiguities become new
   questions — do not silently resolve them.

**export (stakeholder is not here)**
Run `ekit questions export --prd docs/requirements/<slug> --out docs/requirements/<slug>/questions-for-review.csv`
and tell the user to send the CSV (opens in Excel) to the product manager, who fills the
`answer` and `answered_by` columns.

**import <file>**
Run `ekit questions import --prd docs/requirements/<slug> <file>`, then do step 3 above for each
newly answered question.

## Gate

Finish with `ekit gate ready --prd docs/requirements/<slug>`.
- Pass → tell the user they can run `__SPECKIT_COMMAND_SPECIFY__` for a feature.
- Fail → list the remaining blocking questions and their owners. Do **not** proceed to specify.
