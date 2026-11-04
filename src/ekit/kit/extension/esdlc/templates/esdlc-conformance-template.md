# Engineering Baseline Conformance (platform scope)

**Stack**: [stack id] | **Baseline**: [catalog name + version] | **Last reviewed**: [YYYY-MM-DD]

Rows are parsed by `ekit gate baseline`. Keep the column order. Allowed statuses:
`Addressed` (evidence required), `N/A` (justification required),
`Waived` (justification **and** ADR id required).
With an approved wave plan: `Deferred (W2)` for an NFR the plan defers until W2 (not for
non-deferrable NFRs); required again once W2 is current.

## Engineering Baseline Conformance

| NFR | Title | Status | Evidence / Justification | ADR |
|-----|-------|--------|--------------------------|-----|
| SEC-01 | Authentication via central identity provider | Addressed | src/app/core/security.py; SCN-000-02 | |

## Notes

- [Anything reviewers should know: environment-specific controls, shared platform services, etc.]
