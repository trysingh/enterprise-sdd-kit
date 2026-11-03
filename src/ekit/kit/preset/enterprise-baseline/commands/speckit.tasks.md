---
description: Generate dependency-ordered, test-first tasks linked to scenarios and baseline NFRs.
strategy: wrap
---

## Enterprise pre-flight

1. Run `ekit gate plan`. **If it fails, STOP** and report.
2. Tests are mandatory in this project regardless of what the core instructions below say
   about optional tests. Apply the **Enterprise TDD Policy** section of the tasks template.

{CORE_TEMPLATE}

## Enterprise post-flight

3. Check that every `@SCN-…` tag in `features/` is referenced by at least one implementation
   task, and that every `Addressed` NFR row in plan.md has a task. Add missing tasks.
4. Next step: `__SPECKIT_COMMAND_ESDLC_RED__`.
