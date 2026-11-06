---
description: "Take a bug fix, enhancement or feature request straight from the prompt into a traced change request; run gate intake"
handoffs:
  - label: Specify the change
    agent: speckit.specify
    prompt: Specify the change request CR-xxxx
  - label: Resolve open questions
    agent: speckit.esdlc.questions
    prompt: Work through the open questions for this change request
---

# Change request from the prompt (brownfield)

The user describes a bug or a new capability in their own words. You turn it into a **change
request**: a small, traced requirements folder `docs/requirements/cr-NNNN-<slug>/` that the rest of
the pipeline (spec → Gherkin → plan → tasks → **red → green**) treats exactly like a PRD. You
**capture and structure**; you do not design, fix or implement anything here, and you never invent
business facts.

## User Input

```text
$ARGUMENTS
```

The input is the request itself, free text. It may start with `bug:`, `enhancement:` or `feature:`
and may contain `ticket=<ID>` or `affects=<NNN>`. If it is empty, ask the user what they want
changed and stop. A whole BRD document (many requirements, many features) belongs in
`__SPECKIT_COMMAND_ESDLC_BRD__`, not here: say so and stop.

## Steps

1. **Classify** (one word, decided once):
   - `bug`: existing behaviour differs from what it should be. You can state *observed* vs *expected*.
   - `enhancement`: changes or extends what an existing feature does.
   - `feature`: a new capability that does not change existing behaviour.
   Use the prefix if the user gave one. If you genuinely cannot tell, ask the user once.

2. **Find what it touches.** Run `ekit change candidates "<the request>"`. It ranks existing
   feature folders by overlap with their spec and scenarios. Read only the top one or two
   (`spec.md`, `features/*.feature`) and, for a bug, the code paths they name. Decide the
   affected feature folder(s). A `feature` may affect none.

3. **Record it.** Run
   `ekit change new --type <type> --title "<5-8 word title>" --affects <NNN-slug> [--ticket <ID>] --text "<the request>"`.
   It prints `CR-NNNN docs/requirements/cr-NNNN-<slug>`. `--text` must be the user's words unchanged.
   If the request contains quotes or line breaks, leave `--text` out and paste the request
   **verbatim** into `request.md` under `## Request (verbatim)` instead. Never paraphrase it there.
   Never edit `request.md` afterwards.

4. **change.yaml** (in that folder; you may edit it):
   - `bug:` → fill `observed`, `expected` and `reproduction` (steps, data, the route or page). Where
     the user did not say, write `[TBD: OQ-xxx]` and raise the question (step 6). Do not guess.
   - `supersedes:` → if the change makes an **existing scenario** wrong (it asserts the behaviour this
     request changes), list its id (`SCN-003-04`). Grep the affected feature's `.feature` files for it.
     A bug fix normally supersedes nothing: the old scenarios still hold, the bug was a gap.
   - `affects.paths:` → optional, files or modules you found in step 2.

5. **brd.md / prd.md** from `ekit template esdlc-brd-template` and `esdlc-prd-template`, kept small:
   - `brd.md`: one `BR-` row per obligation in the request; the "Source" column quotes `request.md`.
   - `prd.md`: normally **one** `FEAT-01`. Acceptance criteria `AC-001`… in observable terms:
     - bug → the expected behaviour, stated so it fails today ("Given chat 1 has 3 unread messages,
       when I open it and return to the list, then its badge shows 0"). Add an AC for an adjacent
       behaviour only if the request says it must not change.
     - enhancement / feature → the new or changed behaviour, as for any PRD.
   - No engineering NFRs here; they come from the baseline.

6. **open-questions.yaml** from `esdlc-questions-template`: every ambiguity (who, which data, which
   environment, what "should" means). `blocking: true` when the answer could change an AC.

7. **Gate.** Run `ekit gate intake --prd CR-NNNN`. Fix what it reports and re-run until it passes.

8. **Report** in a few lines: `CR-NNNN`, type, affected feature(s), ACs, open questions
   (blocking vs not), superseded scenarios. Then the next step:
   - blocking questions → `__SPECKIT_COMMAND_ESDLC_QUESTIONS__` (or `ekit questions export --prd CR-NNNN`);
   - otherwise → `__SPECKIT_COMMAND_SPECIFY__ CR-NNNN`. Name the spec folder `cr<NNNN>-<slug>`
     (Spec Kit adds the number: `008-cr0007-unread-badge`).
   - If `supersedes:` is not empty, tell the user: before `/speckit.implement` can go green, **a
     person** removes those scenarios from their feature file and runs
     `ekit change retire <feature> <SCN-ids> --by CR-NNNN --reason "..."`. You never run it.

## What the TDD cycle means for this change (tell the user once, briefly)

- **bug**: red reproduces the bug against the **committed, unmodified** code. The red step writes
  tests only; no stubs, no production edits. Each scenario must fail on an assertion that shows the
  observed behaviour (`RED-BUG-REPRODUCED`). Green is the fix, with every existing scenario still green.
- **enhancement / feature**: red as for any feature (501 stubs for new routes; in golden projects
  in the affected feature's package, `ekit feature package <feature>` prints it).
