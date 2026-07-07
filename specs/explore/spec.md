# Capability: explore

The queryable projection of the article store: a schema-derived DuckDB
database served to agents over MCP. `litschema mcp` builds (or reuses) the
store and serves it. Documented as-built from the 2026-07-07 audit.

## The store

`<project_root>/.litschema/explore.duckdb` (override: `--db-path`). Derived,
never authoritative — delete it freely; the article store and review files
are the source of truth.

**Main table** (named after the schema's tree-root class): one row per
article with a valid extraction (error markers excluded). Columns come from
the schema's induced slots:

- the `identifier: true` slot → PRIMARY KEY, backfilled from the article
  directory name when absent in the record;
- scalar slots → typed columns (integer → BIGINT, float/double/decimal →
  DOUBLE, boolean, date/time kinds, everything else VARCHAR — enums are
  strings);
- multivalued or class-ranged slots → JSON columns;
- extraction keys not in the schema are dropped.

**Review overrides are baked in.** Each article's extraction is deep-copied
and every `override_value` from `review.json` is applied before loading —
including the `__remove__` sentinel, which deletes dict fields and nulls
list slots (`specs/reviews/spec.md`). The store therefore reflects the
reviewed truth, not the raw agent output. There are no provenance columns;
overridden values are indistinguishable in-store (tracked in the
improvements backlog).

**Registries**: `authors` and `institutions` tables load from
`data/authors.yaml` / `data/institutions.yaml` when present (produced today
only by the legacy `harvest --resolve` leg; the producer/consumer key
mismatch is a known defect — improvements backlog).

**Rebuild semantics**: the store is reused when it exists, is non-empty, and
is newer than every file under the article store and both registry yamls;
`--rebuild` forces. Schema edits do NOT currently trigger a rebuild (known
gap — improvements backlog).

## The MCP server

`litschema mcp [--rebuild] [--db-path P] [--transport stdio|http] [--port
8765] [--max-rows 200]` — builds the store, prints a load summary (to
stderr under stdio so MCP framing stays clean), then serves three tools:

- `run_sql(query)` — arbitrary SQL, TSV out, truncated at `--max-rows` with
  a hint line; engine errors return as `ERROR: <type>: <message>` strings
  rather than raising.
- `describe_schema()` — tables, columns, row counts, sample rows.
- `get_linkml_schema()` — the project's raw schema YAML, for semantic
  grounding of column meanings.

Read-only is enforced at the engine level (`duckdb.connect(read_only=True)`)
— deliberately no query-text filtering, which is documented in the module as
the honest enforcement point.

## Invariants

- **Derived, disposable.** WHEN the DuckDB file is deleted, THEN the next
  `mcp` run rebuilds it losslessly from the store.
- **Schema drives shape.** WHEN a slot is multivalued or class-ranged, THEN
  its column is JSON; WHEN scalar, THEN typed; WHEN `identifier`, THEN
  primary key. (`test_loader_scenarios.py`)
- **Reviewed truth.** WHEN a field has a review `override_value`, THEN the
  store carries the override (or omits the field, for `__remove__`) — never
  the raw extracted value. (`test_loader_article_layout.py`,
  `test_review_overrides.py`)
- **Writes are impossible.** WHEN a tool submits INSERT/UPDATE/etc., THEN
  the read-only engine rejects it — no query-parsing gate to bypass.

## Code map

`src/litschema/explore/loader.py` (derivation, overrides, registries,
rebuild) · `src/litschema/explore/server.py` (MCP tools) ·
`src/litschema/cli.py` (`mcp` verb). Tests: `test_loader_scenarios.py`,
`test_loader_article_layout.py`, `test_review_overrides.py` (server.py is
currently untested — improvements backlog).
