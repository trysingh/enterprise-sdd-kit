---
description: Create the implementation plan within the stack profile and assess every feature-scope NFR of the engineering baseline.
strategy: wrap
---

## Enterprise pre-flight

1. Run `ekit gate spec` and `ekit gate scenarios`. **If either fails, STOP** and report the
   errors (missing trace, uncovered AC, unresolved clarification, missing scenarios).
2. Run `ekit context` and treat its output as binding Technical Context: language/version,
   frameworks, test tools, project layout, profile `controls` and `agent_rules`.
   Do not propose a different stack; if the feature truly needs one, record an ADR proposal
   and ask the user.

{CORE_TEMPLATE}

## Enterprise post-flight

3. Fill **Stack Profile** and **Engineering Baseline Conformance** in `plan.md`: one row per
   feature-scope NFR listed by `ekit context --nfr feature`. Use the profile `controls` for the
   "how", and name the scenario (`@SCN-…`) or test that proves it.
   `N/A` needs a reason; `Waived` needs a reason and an ADR id (a person approves waivers; never
   invent one). Create every ADR with
   `ekit adr new "<title>"` (it takes the next free number); never number one by hand.
   Golden landing zone (`ekit baseline status`): name the feature package (`ekit feature package <feature>`)
   in the plan's project structure; core files stay as they are (they are frozen).
   Brownfield (`ekit context` shows `mode: brownfield`; 0.6.0): the baseline applies forward. The same table
   also gets one row per platform-scope NFR (`ekit context --nfr platform`) for the code **this feature adds
   or changes**, assessed as `Addressed` / `N/A` / `Waived`, never `Inherited`. Untouched legacy code is out
   of scope: do not assess it, do not edit it to conform. Never invent a ticket or ADR id.
4. Fill **Resilience and Data Boundaries**.
5. Run `ekit gate plan`. Fix and re-run until it passes.
