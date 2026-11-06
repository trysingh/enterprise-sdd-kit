---
description: Create the feature specification from a PRD feature, gated by open questions and traced to acceptance criteria.
strategy: wrap
---

## Enterprise pre-flight (runs before the core workflow)

1. If the input references a PRD feature (`FEAT-xx`, a path under `docs/requirements/`, or
   the user says "next feature"), resolve the PRD folder `docs/requirements/<slug>/`.
   If there is exactly one PRD folder, use it. Otherwise ask.
   If the input names a **change request** (`CR-0007`), the PRD folder is the one
   `ekit change show CR-0007` prints, the feature is its `FEAT-01`, and the new spec folder's short
   name starts with `cr0007-` (e.g. `cr0007-unread-badge`). Write `change: CR-0007` into `trace.yaml`.
2. Run `ekit gate ready --prd docs/requirements/<slug>` (or `--prd CR-0007`).
   **If it fails, STOP.** Show the blocking questions and suggest
   `__SPECKIT_COMMAND_ESDLC_QUESTIONS__`. Do not create a feature branch or spec.
3. **Waves.** Run `ekit wave scope FEAT-xx --prd docs/requirements/<slug>`.
   If waves are in use, include **only** the acceptance criteria it lists for the current wave.
   ACs listed under "later" are not part of this slice: mention them in the spec as
   "planned for Wn" without specifying them. When this is a later slice of a feature that already
   has a spec folder, create a new feature (name it with the wave, e.g. `loan-application-w2`) rather
   than editing the earlier one. `ekit gate spec` (`SPEC-WAVE-SCOPE`) fails on an AC from a later wave.
4. Build the feature description for the core workflow from the PRD: feature summary, its
   acceptance criteria verbatim with their `AC-` ids, cited `BR-` ids, business NFRs and the
   answers to related questions. Treat that as the user's feature description below.
   If the input is a free-text request with no PRD, `FEAT-` or `CR-` id (a bug, a change, an idea),
   do not specify it untraced: tell the user to run `__SPECKIT_COMMAND_ESDLC_CHANGE__ <the same text>`
   (it takes the text as typed and records it as a change request), and stop.

{CORE_TEMPLATE}

## Enterprise post-flight (runs after the spec is written)

5. Fill the **Traceability** and **Data Classification** sections of `spec.md` (they come
   from the enterprise template). Every AC of the PRD feature appears in the traceability table.
   Do not add `[NEEDS CLARIFICATION]` for business facts — add a question to the PRD's
   `open-questions.yaml` and reference it as `[TBD: OQ-xxx]`; a new blocking question means
   the spec stays in Draft.
6. Write `specs/<NNN-name>/trace.yaml` from `ekit template esdlc-trace-template` with the
   feature directory name, number, PRD folder, FEAT ids, AC ids (only this slice's ACs when waves are
   in use), BR ids and, for a change request, `change: CR-NNNN`.
7. Run `ekit gate spec`. Fix and re-run until it passes.
8. Next step: `__SPECKIT_COMMAND_ESDLC_GHERKIN__`, then `__SPECKIT_COMMAND_PLAN__`.
