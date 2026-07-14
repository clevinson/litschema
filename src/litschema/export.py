"""Export the reviewed truth as flat files (`litschema export`).

The records are exactly what the explore store loads — error markers
skipped, review overrides applied, identifier backfilled — via the shared
``load_reviewed_records``. JSONL writes one record per line verbatim; CSV
uses the same schema-driven shaping as the DuckDB columns (scalar slots as
plain cells, multivalued/class-ranged slots as JSON strings).
"""

from __future__ import annotations

import csv
import json
from typing import TextIO

from .config import LitSchemaConfig
from .explore.loader import _derive_columns, _identifier_slot, load_reviewed_records
from .schema_resolution import resolve_extraction_schema

FORMATS = ("jsonl", "csv")


def export_records(cfg: LitSchemaConfig, fmt: str, out: TextIO) -> tuple[int, int]:
    """Write the reviewed records to ``out``; returns (records, with_overrides)."""
    schema = resolve_extraction_schema(cfg)
    id_slot = _identifier_slot(schema.view, schema.root_class)
    records, reviews_applied, _overrides = load_reviewed_records(cfg, id_slot=id_slot)

    if fmt == "jsonl":
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return len(records), reviews_applied

    columns = _derive_columns(schema.view, schema.root_class)
    writer = csv.writer(out)
    writer.writerow([name for name, _sql, _is_json in columns])
    for record in records:
        row = []
        for name, _sql, is_json in columns:
            value = record.get(name)
            if value is None:
                row.append("")
            elif is_json:
                row.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
            else:
                row.append(value)
        writer.writerow(row)
    return len(records), reviews_applied
