---
description: "Fix the system's shape before any test: architecture note + design.yaml (topology, ports, data, interface, seams, slices); run gate design"
handoffs:
  - label: Build slice S0
    agent: speckit.esdlc.slice
    prompt: Build slice S0 from docs/design/design.yaml
---

# Design (stage 2)

You write the short architecture that everything after it is expressed in. You **decide and
record**; you write no application code. Prerequisite: `ekit gate intake` passes and
`docs/requirements/<slug>/happy-path.md` exists (if not, create it from
`ekit template esdlc-happy-path-template` first, from the PRD).

## User Input

```text
$ARGUMENTS
```

Optional: a slug or constraints (topology, existing systems). Empty is fine.

## Steps

1. Run `ekit design init` (add `--from-code` when code already exists). It creates
   `docs/design/architecture.md` and `docs/design/design.yaml` from the kit templates.
2. Read `prd.md`, `brd.md`, `happy-path.md` and `ekit context`. Do not read code except for
   `--from-code` drafts.
3. Fill `design.yaml` and `architecture.md` (same facts, both files):
   - **topology** and the option you rejected; one ADR per real decision (`ekit adr new "Title" --decision D1`; an accepted decision's ADR must mention its id or title).
   - **ports**: every external or swappable dependency as a Protocol with its methods and the
     FastAPI dependency name that provides it.
   - **core data model**: entities, keys, and the `owner_id` (owner or participant) column.
   - **features**: for every PRD `FEAT-`, its `brs` (all of the PRD feature's `Satisfies`), the
     `operations` (snake_case `operation_id`s) and `pages` a user can call. Mark `key: false` only
     if the happy path does not need it.
   - **seams**: keep the five Day-0 seams; they are dummies by design.
   - **slices**: S0 holds every key feature; each slice lists the journeys of `happy-path.md`. The ACs of
     the features in the W0 slices are placed in wave W0 automatically when a person approves the design
     (recorded in `.ekit/waves.yaml`); every other AC is proposed for W1.
   - **packages**: one package per FEAT- by default; to group features in one package add `package: <name>` to
     each of them under `features`. A port whose single class is also the production binding (no separate
     database or service) takes `adapter: in-process`.
4. Run `ekit gate design`. Fix every error (DESIGN-APPROVED fails until a person approves).
5. Report the topology, ports, slices and open decisions. Tell the user to review and run
   `ekit design approve --by "<name>"`. You never run `approve` yourself.

## Rules

- Names you choose here are binding: red tests and slices use these ports and operation ids.
- Do not invent business facts; raise an open question (`ekit questions list`) instead.
- Keep `architecture.md` to two pages. No implementation detail below the port level.
