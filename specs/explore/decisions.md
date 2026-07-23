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

Alongside the freeze, `litschema export` (JSONL/CSV of the same reviewed
records) was added as the cheap bet on the likelier real need — researchers
reaching for R/pandas/jq — and as the stable consumer surface while the SQL
projection stays experimental.

**Revisit triggers:** someone asks a cross-article question that flat files
can't answer; a collection crosses ~1k documents; users ask for
per-experiment tidy tables (which reveals the right projection).

**Rejected:** deleting the layer entirely (throws away proven loader work
and leaves review overrides write-only); investing to production quality
now (every hour is speculation until a real query pattern exists); keeping
the registries (broken, unconsumed, and the only thing keeping the legacy
harvest complex alive).


## 2026-07-14 — Export active runs as all-data or audited-data

**Context:** one reviewed-record projection cannot serve both exploratory and
human-audited analysis, and first-class active runs replace article-root
extraction files.

**Decision:** export resolves one active run per article and offers `all` and
`audited` views. Both apply the review overlay. Audited-data includes only
effective reviewed values. Optional audit JSONL stores the canonical review
frontier once per article with run and schema identity; inherited coverage is
never expanded. DuckDB remains on the all-data view under the existing freeze.

**Rejected:** combining artifacts across runs; treating absence of review as
verified; serializing a review flag on every descendant; unfreezing DuckDB
provenance work.


## 2026-07-14 — Export preserves array indexes and structural identity

**Context:** omitting removed or unaudited array elements would renumber paths
and disconnect data from the canonical audit frontier.

**Decision:** element removal and audited masking preserve the effective array
basis with JSON null placeholders. All-data and audited-data share those
indexes. Audited output retains effective LinkML identifier slots as structural
context without promoting them to reviewed state. CSV serializes placeholders
as literal JSON null inside nested JSON cells; an empty cell means the
top-level slot is absent.

**Rejected:** array splicing; resurrecting removed identifiers; treating
structural identifiers as audited; using empty CSV cells as array placeholders.
