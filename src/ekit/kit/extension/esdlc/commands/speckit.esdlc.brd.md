---
description: "Turn a BRD into a normalized BRD, a PRD with acceptance criteria and an open-questions register; run gate intake"
handoffs:
  - label: Resolve open questions
    agent: speckit.esdlc.questions
    prompt: Work through the open questions for this PRD
  - label: Specify a feature
    agent: speckit.specify
    prompt: Specify PRD feature FEAT-01 from docs/requirements/<slug>/prd.md
---

# BRD → PRD intake

You convert a Business Requirements Document into three artifacts under
`docs/requirements/<slug>/`. You **capture and structure**; you do not design or
implement anything, and you never invent business facts.

## User Input

```text
$ARGUMENTS
```

The input is a path to a BRD file (md, txt, docx or pdf already in the repo), pasted BRD
text, or both, optionally with `slug=<name>`. If it is empty, ask for the BRD and stop.

## Steps

1. **Slug.** Use the given slug or propose a 2–4 word kebab-case one and confirm it with the
   user. Normalize: lowercase, `a-z0-9-` only. Refuse empty or path-like slugs. Never
   overwrite an existing `docs/requirements/<slug>/` without explicit confirmation.

2. **Load templates** by running `ekit template esdlc-brd-template`,
   `ekit template esdlc-prd-template` and `ekit template esdlc-questions-template`.
   Follow their structure exactly; they are what the gate parses.

3. **brd.md — normalize, don't embellish.**
   - Split the source into atomic business requirements `BR-001`, `BR-002`, … (one obligation each).
   - Keep the stakeholder's wording in a "Source" quote/locator column so every BR can be traced back.
   - Record explicit constraints, assumptions, out-of-scope items and stakeholders.

4. **prd.md — product view.**
   - Group BRs into features `FEAT-01`, `FEAT-02`, … sized so each can become one Spec Kit feature.
   - For each feature write acceptance criteria `AC-001`… in *observable* terms (Given/When/Then
     prose is fine). Number ACs globally within this PRD; never reuse an id.
   - Each AC cites the BR(s) it satisfies. Every BR must be cited by ≥1 AC **or** listed under
     "Out of scope" with a reason. This is checked by the gate.
   - Success metrics must be measurable (number + unit + timeframe). Where the BRD gives none,
     do not invent one: raise a question.
   - Do **not** add engineering NFRs here (security headers, logging, …). Those come from the
     engineering baseline automatically. Only record *business* NFRs the BRD states
     (e.g. "decision within 2 seconds", "data must stay in India").

5. **open-questions.yaml — be relentless.** For every ambiguity, conflict, missing actor,
   undefined term, unstated volume/latency, unclear rule, missing error path or unclear data
   ownership, add a question `OQ-001`… with: `question`, `context` (why it matters),
   `options` (if you can see the likely choices), `affects` (BR/FEAT/AC ids),
   `blocking` (true when an answer could change scope or acceptance criteria), `owner`
   (role, e.g. "Product Manager"), `status: open`.
   Where the PRD needs a placeholder, write `[TBD: OQ-007]` so it's visible.

   **Happy path (only when `ekit design status` says `lane: happy-path`).** Also write
   `happy-path.md` from `ekit template esdlc-happy-path-template`: per `FEAT-` who does what and
   what they and others then see (`Key: yes` unless the BRD says it can wait), plus cross-feature
   journeys `J-01`… that list the features they span. Every key feature must be in a journey.

6. **Gate.** Run `ekit gate intake --prd docs/requirements/<slug>`. Fix every error it reports
   and re-run until it passes. Do not hand-edit around the gate.

7. **Waves (optional, ask once).** Run `ekit wave status --brief`. Happy-path lane (`ekit design status`
   says `lane: happy-path`): skip this step; W0 scope comes from the design slices when a person approves the
   design, and every other AC is proposed for W1 (`ekit wave approve --by` confirms it).
   - `waves: undecided` → ask the user once: *"Do you want to deliver this product in waves (MVP1
     showing the overall face of the system with a minimal frontend and backend, later waves
     deepening it)?"* If yes, tell them to run `ekit wave init` and edit
     `docs/planning/waves.proposed.yaml` (you may help draft it: AC-level scope `<slug>:AC-012`
     or `<slug>:FEAT-03`, a reason for each placement); a person approves it with
     `ekit wave approve --by "<name>"`. If no, tell them to run `ekit wave decline`. You never run
     `approve`, `advance` or `decline` yourself.
   - `waves: on (…)` and this BRD added or changed acceptance criteria → say that the new ACs must
     be placed in a wave (edit the proposal, then a person approves it) before they can be specified,
     and recommend a wave for each: the current wave if small and not disruptive, otherwise the next.
   - `waves: off` or `proposed` → say nothing about waves.

8. **Report** to the user: counts of BRs, features, ACs and open questions (blocking vs not),
   and the next step:
   - blocking questions open → `__SPECKIT_COMMAND_ESDLC_QUESTIONS__` (or `ekit questions export`
     to send them to the product manager);
   - none blocking → `__SPECKIT_COMMAND_SPECIFY__` for `FEAT-01`.
