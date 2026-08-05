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


## 2026-07-26 — The party that chose the model is the party that records it

**Context:** two subagents extracted the same paper in the demo corpus, both
dispatched with the model pinned to sonnet and both told to publish with
`--model claude-sonnet-5`. One complied; the other substituted `claude-opus-5`,
reasoning that provenance should reflect what actually ran. At least one of the
two published records is false and nothing on disk indicates which. The
underlying cause is known: the model is not exposed to a skill through the
environment, so an agent's belief about its own identity is unverifiable.

**Decision:** an extracting agent may never describe its own model. It relays a
supplied value verbatim or omits the flags entirely. Where a conductor
dispatches per-article subagents, the conductor publishes — it chose the model,
so it alone knows it. Standalone extraction publishes itself with no model,
which is honest rather than lossy.

**Rejected:** trusting the extracting agent's self-report (the failure
observed); having the conductor pass the model down for the subagent to echo
back, which reintroduces the same substitution opportunity one step later;
and parsing the harness transcript to recover the true model, already rejected
for depending on an undocumented internal format.
