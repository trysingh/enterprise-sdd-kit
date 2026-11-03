Write this as a YAML file (strip the fence).

```yaml
# Open questions register for docs/requirements/<slug>/
# Machine-checked by `ekit gate intake` (schema) and `ekit gate ready` (no open blocking).
# Round-trip with stakeholders: `ekit questions export` -> CSV -> `ekit questions import`.
#
# status:   open | answered | deferred | withdrawn
# blocking: true when the answer could change scope, acceptance criteria or data handling.
#           A deferred blocking question still blocks.
apiVersion: ekit/v1
kind: OpenQuestions
prd: "[slug]"
questions:
  - id: OQ-001
    question: "[Clear, answerable question]"
    context: "[Why it matters / what breaks if we guess]"
    options: ["[Option A]", "[Option B]"]
    affects: ["BR-001", "AC-002"]
    blocking: true
    owner: "Product Manager"
    status: open
    answer: null
    answered_by: null
    answered_on: null
```
