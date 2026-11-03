---
description: Implement tasks only after red is recorded; finish only when gate green passes.
strategy: wrap
---

## Enterprise pre-flight

1. Check that a red ledger entry exists for this feature: `ekit gate red-recorded`.
   **If there is none, STOP** and run `__SPECKIT_COMMAND_ESDLC_RED__` first. Never write
   production behaviour before the tests that prove it have been seen failing.
2. Run `ekit context` and follow the profile `agent_rules` and `controls` while coding.
3. Do not edit `.feature` files or weaken assertions to get green. If a scenario is wrong,
   stop and say so; the fix goes through the spec (and possibly an open question).

{CORE_TEMPLATE}

## Enterprise post-flight

4. Run `ekit gate green`. Fix code (not tests) until it passes. If a check cannot pass for a
   legitimate reason, explain it to the user; do not edit the policy.
5. Tick the remaining tasks in `tasks.md`, commit code together with the `.ekit/ledger/` entry,
   and report: scenarios green, coverage, any warnings (e.g. SCA).
