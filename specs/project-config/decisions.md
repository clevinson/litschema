# Decisions: project-config

Append-only. Newer entries supersede older ones.

## 2026-07-07 — Spec backfilled as-built

**Context:** this capability shipped before the specs/ convention existed;
its behavior was documented only in code, tests, and skill text. A
three-lens audit of the full surface inventoried it.

**Decision:** the spec documents the capability exactly as built at audit
time, including known deviations, which are flagged inline and tracked in
`specs/improvements.md` rather than silently normalized. Future behavior
changes update the spec in the same PR, per `specs/README.md`.
