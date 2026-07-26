# Decisions: extraction

Append-only. Newer entries supersede older ones.

## 2026-07-07 — Spec backfilled as-built

**Context:** this capability shipped before the specs/ convention existed;
its behavior was documented only in code, tests, and skill text. A
three-lens audit of the full surface inventoried it.

**Decision:** the spec documents the capability exactly as built at audit
time, including known deviations, which are flagged inline and tracked in
`specs/improvements.md` rather than silently normalized. Future behavior
changes update the spec in the same PR, per `specs/README.md`.


## 2026-07-14 — Extraction publishes immutable run artifacts

**Context:** article-root outputs and manifest provenance could not represent
multiple attempts or safe active selection.

**Decision:** extraction writes staged `agent-extraction.json` and
`agent-reasoning.json`, validates them, records complete `run.json` provenance,
and atomically publishes a lineage run. Reasoning paths use the canonical
no-leading-dot review dialect. Reruns do not activate implicitly.

**Rejected:** overwriting article-root artifacts; provenance in the manifest;
partial published runs; two path dialects.
