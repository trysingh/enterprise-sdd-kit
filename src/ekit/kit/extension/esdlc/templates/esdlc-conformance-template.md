# Engineering Baseline Conformance (platform scope)

**Stack**: [stack id] | **Baseline**: [catalog name + version] | **Last reviewed**: [YYYY-MM-DD]

In a brownfield project this file is optional (a snapshot, `/speckit.esdlc.baseline snapshot`): the baseline applies
to new code, and a missing row means "inherited". One row per NFR: a duplicate is an error.

Rows are parsed by `ekit gate baseline`. Keep the column order. Allowed statuses:
`Addressed` (evidence required), `N/A` (justification required),
`Gap` (brownfield only: justification **and** a remediation ticket, task or ADR id; warns),
`Inherited` (brownfield only, 0.6.0: existing code, not assessed or not yet meeting the NFR, accepted as-is;
no evidence or ticket needed; info only; an error in a greenfield project; an NFR a person has enforced with
`ekit baseline enforce` can no longer be `Inherited` or `Gap`),
`Waived` (a person approved it: justification **and** ADR id required; the agent never invents one).
With an approved wave plan: `Deferred (W2)` for an NFR the plan defers until W2 (not for
non-deferrable NFRs); required again once W2 is current.

## Engineering Baseline Conformance

| NFR | Title | Status | Evidence / Justification | ADR |
|-----|-------|--------|--------------------------|-----|
| SEC-01 | Authentication via central identity provider | Addressed | src/app/core/security.py; SCN-000-02 | |

## Notes

- [Anything reviewers should know: environment-specific controls, shared platform services, etc.]
