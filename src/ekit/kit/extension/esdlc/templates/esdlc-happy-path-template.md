# Happy path: [INITIATIVE NAME]

**PRD**: [prd.md](./prd.md) | **Version**: 0.1 | **Status**: Draft

The first delivery covers **every key feature** working together as a POC-grade app: real
persistence, several users, state that changes and is seen by others, variation in data. "Happy"
means no error or edge handling yet, not one trivial rule per scenario. Gate `intake` checks that
every key feature appears in at least one journey.

## 1. Features

One section per PRD feature. `Key: yes` (default) means the first delivery must cover it.

### FEAT-01: [Feature name]

- **Key**: yes
- **Who**: [persona or dev user, e.g. asha]
- **Does**: [what they do]
- **Sees**: [what they, and other users, then see]

### FEAT-02: [Feature name]

- **Key**: yes
- **Who**: ...
- **Does**: ...
- **Sees**: ...

## 2. Journeys

Sequences that span several features the way real use does (e.g. user A creates something, user B
finds it and acts on it, A sees the result). Each journey becomes a Gherkin feature tagged `@J-01`.

### J-01: [Journey name]

- **Features**: FEAT-01, FEAT-02
- **Users**: [asha, ravi]
- **Steps**: [asha does X; ravi sees X and does Y; asha sees Y]
- **Data variation**: [two or three example rows]

## 3. Cross-cutting concerns the BRD implies

Identity, audit, tracing, retention, ... Day 0 uses seams with dummy implementations; list what
the real controls will need to be (they are layered on in later waves).

- [e.g. every message is audited with actor and time]
