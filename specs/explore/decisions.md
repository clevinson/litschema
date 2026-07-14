# Decisions: explore

Append-only. Newer entries supersede older ones.

## 2026-07-07 — Initial scope: minimal core, deliberately frozen

**Context:** a full-surface audit asked whether the DuckDB/MCP layer was
premature. The evidence of prematurity was strong: one of three MCP tools
crashed on pip installs (a pandas call with pandas not a runtime
dependency), the author/institution registry tables were permanently
half-NULL from a producer/consumer key mismatch, neither defect had been
noticed by anyone, and the guided onboarding flow never even points at the
layer. The store's projection — one row per article, nested data as JSON
columns — is a guess about query patterns no user has demonstrated.

**Decision:** keep the core (schema-derived store with review overrides
baked in; three read-only MCP tools) because it is the only consumer of
review overrides, the MVP's last mile, and cheap to carry (two files,
lazily imported by one verb). Cut the registries: the `authors` /
`institutions` tables, their yaml ingestion, and the entire upstream
pipeline that fed them (`resolve_entities`, the CrossRef supplement — whose
cache had zero consumers — the `harvest` CLI verb, the legacy console
scripts, and the `jellyfish` dependency). Fix the one crash (plain
`fetchall` instead of pandas). Freeze everything else: no provenance
columns, no server test suite, no rebuild-on-schema-edit until a revisit
trigger fires.

**Revisit triggers:** someone asks a cross-article question that reading
the JSONs can't answer; a collection crosses ~1k documents; users ask for
per-experiment tidy tables (which reveals the right projection — likely an
`export` command for R/pandas rather than more SQL surface).

**Rejected:** deleting the layer entirely (throws away proven loader work
and leaves review overrides write-only); investing to production quality
now (every hour is speculation until a real query pattern exists); keeping
the registries (broken, unconsumed, and the only thing keeping the legacy
harvest complex alive).
