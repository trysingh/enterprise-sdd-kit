# Engineering Baseline Conformance (platform scope)

**Stack**: [stack id] | **Baseline**: [catalog name + version] | **Last reviewed**: [YYYY-MM-DD]

Rows are parsed by `ekit gate baseline`. Keep the column order. Allowed statuses:
`Addressed` (evidence required), `N/A` (justification required),
`Waived` (justification **and** ADR id required).

## Engineering Baseline Conformance

| NFR | Title | Status | Evidence / Justification | ADR |
|-----|-------|--------|--------------------------|-----|
| SEC-01 | Authentication via central identity provider | Addressed | src/app/core/security.py; SCN-000-02 | |

## Notes

- [Anything reviewers should know: environment-specific controls, shared platform services, etc.]
