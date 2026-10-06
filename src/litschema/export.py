"""Export extractions as flat files (`litschema export`).

The data records are the all-data view of `specs/explore/spec.md`: every
active-run value with review corrections applied, error markers skipped,
identifier backfilled. JSONL writes one record per line verbatim; CSV uses the
same schema-driven shaping as the DuckDB columns (scalar slots as plain cells,
multivalued/class-ranged slots as JSON strings).

Provenance and review state go to a separate audit file, one JSONL record per
article, so data rows keep the schema's shape and can't collide with its slots.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from typing import TextIO

from .bib_metadata import read_bib_metadata
from .config import LitSchemaConfig
from .explore.loader import ReviewedRecord, _derive_columns, _identifier_slot, iter_reviewed_records
from .grading import BAND_NAMES, FLAG_BANDS, band_counts, current_grade
from .reviews import effective_extraction, review_progress
from .schema_resolution import (
    ResolvedExtractionSchema,
    identifier_leaf_paths,
    resolve_extraction_schema,
)

FORMATS = ("jsonl", "csv")


@dataclass
class ExportSummary:
    records: int = 0
    with_overrides: int = 0
    complete: int = 0
    partial: int = 0
    unreviewed: int = 0
    audit: list[dict] = field(default_factory=list)


def export_records(
    cfg: LitSchemaConfig, fmt: str, out: TextIO, audit_out: TextIO | None = None
) -> ExportSummary:
    """Write the records to ``out`` and, when given, one audit record per article."""
    schema = resolve_extraction_schema(cfg)
    id_slot = _identifier_slot(schema.view, schema.root_class)
    items = list(iter_reviewed_records(cfg, id_slot=id_slot))

    summary = ExportSummary(records=len(items))
    for item in items:
        audit = audit_record(schema, item)
        if item.fields and any(e.get("override") for e in item.fields.values()):
            summary.with_overrides += 1
        status = audit["review"]["status"]
        if status == "complete":
            summary.complete += 1
        elif status == "partial":
            summary.partial += 1
        else:
            summary.unreviewed += 1
        summary.audit.append(audit)

    if fmt == "jsonl":
        for item in items:
            out.write(json.dumps(item.data, ensure_ascii=False, sort_keys=True) + "\n")
    else:
        _write_csv(schema, [item.data for item in items], out)

    if audit_out is not None:
        for audit in summary.audit:
            audit_out.write(json.dumps(audit, ensure_ascii=False, sort_keys=True) + "\n")
    return summary


def _write_csv(schema: ResolvedExtractionSchema, records: list[dict], out: TextIO) -> None:
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


def audit_record(schema: ResolvedExtractionSchema, item: ReviewedRecord) -> dict:
    """Where one article's values came from and how far review got.

    Missing provenance is null, never a default: a run without a recorded model
    or an article without a DOI says so.
    """
    run = item.run
    run_json = run.read_run_json()
    agent = run_json.get("agent") or {}
    bib = read_bib_metadata(run.article.read_metadata())
    return {
        "article_id": item.article_id,
        "doi": bib.get("doi"),
        "run_id": run.run_id,
        "schema_hash": run_json.get("schema_hash"),
        "extraction": {
            "provider": agent.get("provider"),
            "model": agent.get("model"),
            "litschema_version": (run_json.get("litschema") or {}).get("version"),
            "created_at": run_json.get("created_at"),
        },
        "review": _review_summary(schema, item),
        "grade": _grade_summary(run),
        "fields": item.fields,
    }


def _review_summary(schema: ResolvedExtractionSchema, item: ReviewedRecord) -> dict:
    # Same counting as the review app: identifier slots are identity, not
    # review work, in both the raw and the effective extraction.
    raw = json.loads(item.run.extraction.read_text())
    effective = effective_extraction(item.run, item.fields) if item.fields else raw
    exclude = identifier_leaf_paths(schema.view, schema.root_class, raw)
    exclude |= identifier_leaf_paths(schema.view, schema.root_class, effective)
    progress = review_progress(item.run, item.fields, exclude=exclude)
    if progress["n_reviewed"] == 0:
        status = "unreviewed"
    elif progress["is_complete"]:
        status = "complete"
    else:
        status = "partial"
    return {
        "status": status,
        "n_fields": progress["n_fields"],
        "n_reviewed": progress["n_reviewed"],
        "n_verified": progress["n_verified"],
        "n_overridden": progress["n_overridden"],
    }


def _grade_summary(run) -> dict | None:
    """Band counts from the run's current grade; null when it has none."""
    grade = current_grade(run).grade
    if grade is None:
        return None
    counts = band_counts(grade)
    grader = grade.get("grader") or {}
    return {
        "grade_id": grade.get("grade_id"),
        "model": grader.get("model") or grader.get("requested_model"),
        "flagged": sum(counts[name] for name in FLAG_BANDS),
        **{name: counts[name] for name in BAND_NAMES},
    }
