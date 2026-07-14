# Capability: explore (experimental)

The consumable projections of the reviewed truth: `litschema export` writes
it as flat files (JSONL/CSV), and `litschema mcp` serves a schema-derived
DuckDB database over MCP. Both are built from the same record definition —
`load_reviewed_records`: error markers skipped, review overrides applied,
identifier backfilled.

**Status: experimental — deliberately frozen pending user signal.** The
thesis (SQL over the reviewed truth) is core to the product, but the right
table projection depends on how people actually query the data, which no
user has shown us yet. The current shape is kept minimal and correct;
further investment (provenance columns, per-experiment projections, a
human-facing query surface) waits for one of the revisit triggers in
`decisions.md`.

## The store

`<project_root>/.litschema/explore.duckdb` (override: `--db-path`). Derived,
never authoritative — delete it freely; the article store and review files
are the source of truth.

One table, named `articles` (not derived from the schema's tree-root class
name): one row per article with a valid extraction (error markers
excluded). Columns come from the schema's induced slots:

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
overridden values are indistinguishable in-store (deferred with the freeze).

**Rebuild semantics**: the store is reused when it exists, is non-empty, and
is newer than every file under the article store; `--rebuild` forces.
Schema edits do NOT currently trigger a rebuild (known gap, deferred with
the freeze — use `--rebuild` after schema changes).

## Export: `litschema export`

`litschema export [--format jsonl|csv] [--output PATH]` writes the reviewed
records to stdout (pipeable) or a file; a summary line goes to stderr.

- **jsonl** (default): one record per line, keys sorted — ready for pandas,
  jq, or an agent to read directly.
- **csv**: the same schema-driven shaping as the DuckDB columns — scalar
  slots as plain cells, multivalued/class-ranged slots as JSON strings,
  absent slots empty. Ready for R or a spreadsheet.

Unknown formats and missing/rootless schemas are exit 2 with a one-line
remedy. This is the stable, dependency-free consumer surface; the SQL layer
below is the experimental one.

## The MCP server

`litschema mcp [--rebuild] [--db-path P] [--transport stdio|http] [--port
8765] [--max-rows 200]` — builds the store, prints a load summary (to
stderr under stdio so MCP framing stays clean), then serves three tools:

- `run_sql(query)` — arbitrary SQL, TSV out, truncated at `--max-rows` with
  a hint line; engine errors return as `ERROR: <type>: <message>` strings
  rather than raising.
- `describe_schema()` — tables, columns, row counts, sample rows (plain
  tab-separated text; no pandas dependency).
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
- **Reviewed truth, one definition.** WHEN a field has a review
  `override_value`, THEN the store and every export carry the override (or
  omit the field, for `__remove__`) — never the raw extracted value; both
  surfaces share `load_reviewed_records`.
  (`test_loader_article_layout.py`, `test_review_overrides.py`,
  `test_export.py`)
- **Writes are impossible.** WHEN a tool submits INSERT/UPDATE/etc., THEN
  the read-only engine rejects it — no query-parsing gate to bypass.
- **No dependencies beyond the declared ones.** WHEN litschema is
  pip-installed, THEN every MCP tool works — nothing in this layer imports
  packages outside the runtime dependency set.

## Code map

`src/litschema/explore/loader.py` (record definition, derivation,
overrides, rebuild) · `src/litschema/export.py` (flat-file export) ·
`src/litschema/explore/server.py` (MCP tools) · `src/litschema/cli.py`
(`export` and `mcp` verbs). Tests: `test_export.py`,
`test_loader_scenarios.py`, `test_loader_article_layout.py`,
`test_review_overrides.py` (server.py is untested — accepted under the
freeze).
