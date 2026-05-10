"""MCP server exposing the litschema explore DuckDB store to agent CLIs.

Three tools:
- `run_sql(query)`        — query the DuckDB store
- `describe_schema()`     — tables, columns, row counts, sample rows
- `get_linkml_schema()`   — the LinkML schema YAML (for semantic grounding)

### Read-only enforcement

The DuckDB connection is opened with `read_only=True`. DuckDB's storage
engine rejects every mutation (INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/
TRUNCATE/REPLACE/ATTACH/DETACH/COPY) at the engine layer with a clear
`InvalidInputException: Cannot execute statement of type "X" on database
"…" which is attached in read-only mode!`. We don't add an
application-layer regex gate on top — the engine is the right place to
enforce "this connection cannot mutate." The agent calling `run_sql`
sees the database error message verbatim if it tries.

If a future need arises to share a writable DuckDB across multiple
purposes, the right move is two `duckdb.connect()` calls with different
`read_only` flags (one per role) — same pattern, no application-layer
filtering required.

Transport defaults to stdio (pairs with `claude mcp add -- uv run
litschema mcp`). HTTP transport is also supported via FastMCP's built-in
streamable-http.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import LitSchemaConfig
from ..schema_resolution import extraction_schema_path


def _rows_to_tsv(columns: list[str], rows: list[tuple], max_rows: int) -> str:
    """Render rows as TSV with a header line. Truncates at max_rows."""
    lines = ["\t".join(columns)]
    for i, row in enumerate(rows):
        if i >= max_rows:
            lines.append(
                f"... ({len(rows) - max_rows} more rows omitted; "
                f"increase --max-rows or refine the query)"
            )
            break
        lines.append("\t".join("" if v is None else str(v) for v in row))
    return "\n".join(lines)


def build_server(
    cfg: LitSchemaConfig,
    db_path: Path,
    max_rows: int = 200,
) -> Any:
    """Construct a FastMCP server wired to the given DuckDB file.

    Returned object has `.run()` (stdio) and `.run(transport='streamable-http')`.
    """
    import duckdb
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("litschema")

    # Per-process connection. Read-only mode is what enforces "no mutations" —
    # there is no application-layer regex gate on queries. See the module
    # docstring above for the rationale.
    con = duckdb.connect(str(db_path), read_only=True)

    @mcp.tool()
    def run_sql(query: str) -> str:
        """Execute a SQL query against the litschema explore store.

        The store is a DuckDB database containing tables built from
        schema-validated extractions of scientific literature, with
        reviewer overrides applied (latest-wins per field). The
        connection is opened in read-only mode, so any attempt to
        mutate (INSERT / UPDATE / DELETE / DROP / CREATE / etc.) is
        rejected by DuckDB itself with a clear error.

        Use `describe_schema()` first to see the available tables and
        columns; use `get_linkml_schema()` for the underlying semantic
        model (slot descriptions, enum meanings).

        Returns query results as TSV (header row + bounded data rows),
        or an error message starting with `ERROR:` if DuckDB rejects
        the query.
        """
        try:
            result = con.execute(query)
            columns = [c[0] for c in (result.description or [])]
            rows = result.fetchall()
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
        if not columns:
            return "(no result rows; statement returned nothing)"
        return _rows_to_tsv(columns, rows, max_rows)

    @mcp.tool()
    def describe_schema() -> str:
        """Describe the tables in the explore store.

        Returns a markdown-flavored description of each table: name,
        columns with types, row count, and three sample rows. Call this
        before writing queries to understand the data shape.
        """
        out: list[str] = []
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' ORDER BY table_name"
            ).fetchall()
        ]
        for t in tables:
            cols_result = con.execute(f"DESCRIBE {t}").fetchall()
            # DuckDB DESCRIBE returns (column_name, column_type, null, key, default, extra)
            col_lines = [f"  {r[0]}: {r[1]}" for r in cols_result]
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            out.append(f"## {t} ({n} rows)")
            out.append("\n".join(col_lines))
            sample = con.execute(f"SELECT * FROM {t} LIMIT 3").fetchdf()
            if not sample.empty:
                out.append("\nsample:")
                out.append(sample.to_string(index=False, max_colwidth=80))
            out.append("")
        return "\n".join(out) or "(no tables)"

    @mcp.tool()
    def get_linkml_schema() -> str:
        """Return the root LinkML schema YAML.

        Use this when semantic context (enum meanings, slot
        descriptions, inlined vs referenced relationships) is needed to
        form a query. The DuckDB tables are a flattened view; this is
        the source of truth for what fields mean.
        """
        schema_path = extraction_schema_path(cfg)
        if not schema_path.exists():
            return f"ERROR: extraction schema not found at {schema_path}"
        return schema_path.read_text()

    return mcp


__all__ = ["build_server"]
