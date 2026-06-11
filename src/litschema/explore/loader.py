"""LinkML extraction JSON → DuckDB loader for `litschema mcp`.

Schema-driven and domain-agnostic: introspects the project's extraction
schema (root class detected via `tree_root: true`) and generates a
DuckDB `articles` table with one column per top-level slot. Scalar
slots become typed columns; multivalued or class-ranged slots become
JSON columns. Every column is queryable directly — LLMs use SQL for
scalars and DuckDB JSON functions (`json_extract`, `->`, `->>`) for
nested structures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from linkml_runtime.utils.schemaview import SchemaView

from ..articles import (
    article_files,
    article_id_from_extraction_path,
    iter_extraction_paths,
)
from ..config import LitSchemaConfig
from ..reviews import read_reviews
from ..schema_resolution import resolve_extraction_schema


@dataclass
class LoadSummary:
    extractions_loaded: int
    reviews_applied: int
    overrides_applied: int
    authors_loaded: int
    institutions_loaded: int
    article_columns: list[tuple[str, str]]  # (column_name, sql_type)
    db_path: Path


# ── Review-override application (review.json, one entry per field) ────────


_PATH_SEG = re.compile(r"(?:^|\.)([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def _parse_path(path: str) -> list[str | int]:
    """Parse `a.b[2].c` (or legacy `.a.b[2].c`) into ['a', 'b', 2, 'c']."""
    segs: list[str | int] = []
    for m in _PATH_SEG.finditer(path):
        if m.group(1) is not None:
            segs.append(m.group(1))
        else:
            segs.append(int(m.group(2)))
    return segs


def _apply_override(record: dict, path: str, value: Any) -> bool:
    """Set record at path to value. Returns False on path-resolve failure."""
    segs = _parse_path(path)
    if not segs:
        return False
    cur: Any = record
    for seg in segs[:-1]:
        try:
            cur = cur[seg]
        except (KeyError, IndexError, TypeError):
            return False
    last = segs[-1]
    try:
        cur[last] = value
        return True
    except (KeyError, IndexError, TypeError):
        return False


def _build_override_map(cfg: LitSchemaConfig) -> dict[str, list[dict]]:
    """{article_id: [{path, value, timestamp}, ...] sorted by timestamp ascending}."""
    by_article: dict[str, list[dict]] = {}
    for extraction_path in iter_extraction_paths(cfg):
        article_id = article_id_from_extraction_path(extraction_path)
        fields = read_reviews(article_files(cfg, article_id))
        overrides = [
            {"path": path, "value": entry["override_value"], "timestamp": entry.get("timestamp")}
            for path, entry in fields.items()
            if "override_value" in entry
        ]
        if overrides:
            overrides.sort(key=lambda o: o["timestamp"] or "")
            by_article[article_id] = overrides
    return by_article


def _apply_overrides_to_extraction(
    extraction: dict,
    overrides: list[dict],
) -> tuple[dict, int]:
    """Apply review overrides in chronological order."""
    record = json.loads(json.dumps(extraction))  # deep copy
    count = 0
    for override in overrides:
        if _apply_override(record, override["path"], override["value"]):
            count += 1
    return record, count


# ── Schema-driven column-shape derivation ──────────────────────────────────


def _linkml_scalar_to_duckdb(range_name: str | None) -> str:
    """Map a LinkML scalar range to a DuckDB column type.

    Anything not recognized falls back to VARCHAR — DuckDB will accept
    string-coerced values without complaint.
    """
    return {
        "integer": "BIGINT",
        "float": "DOUBLE",
        "double": "DOUBLE",
        "decimal": "DOUBLE",
        "boolean": "BOOLEAN",
        "date": "DATE",
        "datetime": "TIMESTAMP",
        "time": "TIME",
    }.get(range_name or "string", "VARCHAR")


def _derive_columns(
    sv: SchemaView,
    class_name: str,
) -> list[tuple[str, str, bool]]:
    """Return [(column_name, sql_type, is_json), ...] for a class.

    Schema rules:
    - Multivalued slot (any range) → JSON column
    - Class-ranged slot (nested object) → JSON column
    - Scalar slot → typed column (VARCHAR fallback for unknown types)
    """
    induced = sv.class_induced_slots(class_name)
    columns: list[tuple[str, str, bool]] = []
    classes = set(sv.all_classes().keys())
    for slot in induced:
        slot_range = slot.range
        is_class_ref = slot_range in classes
        is_json = bool(slot.multivalued) or is_class_ref
        if is_json:
            columns.append((slot.name, "JSON", True))
        else:
            columns.append((slot.name, _linkml_scalar_to_duckdb(slot_range), False))
    return columns


def _identifier_slot(sv: SchemaView, class_name: str) -> str | None:
    """Return the slot marked `identifier: true` for the class, if any."""
    for slot in sv.class_induced_slots(class_name):
        if slot.identifier:
            return slot.name
    return None


# ── Table-creation and inserts ─────────────────────────────────────────────


def _create_articles_table(
    con: Any,
    columns: list[tuple[str, str, bool]],
    id_slot: str | None,
) -> None:
    con.execute("DROP TABLE IF EXISTS articles")
    col_defs = []
    for name, sql_type, _is_json in columns:
        suffix = " PRIMARY KEY" if name == id_slot else ""
        col_defs.append(f'  "{name}" {sql_type}{suffix}')
    ddl = "CREATE TABLE articles (\n" + ",\n".join(col_defs) + "\n)"
    con.execute(ddl)


def _insert_articles(
    con: Any,
    columns: list[tuple[str, str, bool]],
    records: list[dict],
) -> None:
    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(f'"{name}"' for name, _t, _j in columns)
    sql = f"INSERT INTO articles ({col_list}) VALUES ({placeholders})"
    rows = []
    for r in records:
        row = []
        for name, _sql_type, is_json in columns:
            v = r.get(name)
            if is_json:
                # NULL stays NULL; everything else gets serialized.
                row.append(json.dumps(v) if v is not None else None)
            else:
                row.append(v)
        rows.append(tuple(row))
    if rows:
        con.executemany(sql, rows)


def _insert_registries(
    con: Any,
    authors: list[dict],
    institutions: list[dict],
) -> None:
    """Generic registries — these classes are part of schema-base, not domain.

    Both tables carry a `_raw JSON` column for any domain-specific
    fields beyond the well-known scalars.
    """
    con.execute("DROP TABLE IF EXISTS authors")
    con.execute(
        """
        CREATE TABLE authors (
            id            VARCHAR PRIMARY KEY,
            family_name   VARCHAR,
            given_name    VARCHAR,
            orcid         VARCHAR,
            openalex_id   VARCHAR,
            _raw          JSON
        )
        """
    )
    if authors:
        con.executemany(
            "INSERT INTO authors VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    a.get("id"),
                    a.get("family_name"),
                    a.get("given_name"),
                    a.get("orcid"),
                    a.get("openalex_id"),
                    json.dumps(a),
                )
                for a in authors
            ],
        )

    con.execute("DROP TABLE IF EXISTS institutions")
    con.execute(
        """
        CREATE TABLE institutions (
            id              VARCHAR PRIMARY KEY,
            name            VARCHAR,
            ror             VARCHAR,
            country_code    VARCHAR,
            _raw            JSON
        )
        """
    )
    if institutions:
        con.executemany(
            "INSERT INTO institutions VALUES (?, ?, ?, ?, ?)",
            [
                (
                    i.get("id"),
                    i.get("name"),
                    i.get("ror"),
                    i.get("country_code"),
                    json.dumps(i),
                )
                for i in institutions
            ],
        )


# ── Rebuild detection + main entry ─────────────────────────────────────────


def _needs_rebuild(db_path: Path, source_paths: list[Path]) -> bool:
    if not db_path.exists():
        return True
    db_mtime = db_path.stat().st_mtime
    for p in source_paths:
        if not p.exists():
            continue
        if p.is_file():
            if p.stat().st_mtime > db_mtime:
                return True
            continue
        for f in p.rglob("*"):
            if f.is_file() and f.stat().st_mtime > db_mtime:
                return True
    return False


def build_store(
    cfg: LitSchemaConfig,
    db_path: Path | None = None,
    force_rebuild: bool = False,
) -> LoadSummary:
    """Build (or reuse) the DuckDB explore store.

    Reuses an existing DuckDB if all source files are older than it and
    `force_rebuild=False`.
    """
    import duckdb

    authors_path = cfg.data_dir / "authors.yaml"
    institutions_path = cfg.data_dir / "institutions.yaml"

    if db_path is None:
        db_path = cfg.project_root / ".litschema" / "explore.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sources = [
        cfg.article_store_dir,
        authors_path,
        institutions_path,
    ]
    if not force_rebuild and not _needs_rebuild(db_path, sources):
        con = duckdb.connect(str(db_path))
        try:

            def _count(table: str) -> int:
                try:
                    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except Exception:
                    return 0

            n_articles = _count("articles")
            n_authors = _count("authors")
            n_institutions = _count("institutions")
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name='articles' ORDER BY ordinal_position"
            ).fetchall()
        finally:
            con.close()
        if n_articles > 0:
            return LoadSummary(
                extractions_loaded=n_articles,
                reviews_applied=0,  # unknown on cache-hit
                overrides_applied=0,
                authors_loaded=n_authors,
                institutions_loaded=n_institutions,
                article_columns=[(c[0], c[1]) for c in cols],
                db_path=db_path,
            )

    # Full rebuild: schema introspection drives column shape.
    extraction_schema = resolve_extraction_schema(cfg)
    columns = _derive_columns(extraction_schema.view, extraction_schema.root_class)
    id_slot = _identifier_slot(extraction_schema.view, extraction_schema.root_class)

    override_map = _build_override_map(cfg)

    records: list[dict] = []
    reviews_applied = 0
    overrides_applied = 0
    for ext_path in iter_extraction_paths(cfg):
        article_id = article_id_from_extraction_path(ext_path)
        data = json.loads(ext_path.read_text())
        if data.get("error"):
            continue
        # Honor either an in-record id or fall back to filename stem when
        # the schema's id_slot isn't `article_id`.
        if id_slot and id_slot not in data:
            data[id_slot] = article_id
        overrides = override_map.get(article_id) or []
        if overrides:
            data, applied = _apply_overrides_to_extraction(data, overrides)
            reviews_applied += 1
            overrides_applied += applied
        records.append(data)

    authors = yaml.safe_load(authors_path.read_text()) if authors_path.exists() else []
    institutions = (
        yaml.safe_load(institutions_path.read_text()) if institutions_path.exists() else []
    )

    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        _create_articles_table(con, columns, id_slot)
        _insert_articles(con, columns, records)
        _insert_registries(con, authors or [], institutions or [])
    finally:
        con.close()

    return LoadSummary(
        extractions_loaded=len(records),
        reviews_applied=reviews_applied,
        overrides_applied=overrides_applied,
        authors_loaded=len(authors or []),
        institutions_loaded=len(institutions or []),
        article_columns=[(name, sql_type) for name, sql_type, _j in columns],
        db_path=db_path,
    )


__all__ = ["LoadSummary", "build_store"]
