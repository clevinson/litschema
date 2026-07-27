"""Shared test fixtures for the run-shaped article store."""

from __future__ import annotations

import json
from pathlib import Path

from litschema.runs import is_error_marker

TEST_RUN_ID = "01TESTRUN0000000000000000A"


def _try_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def publish_test_run(
    article_dir: Path,
    extraction: dict | str,
    *,
    reasoning: dict | str | None = None,
    run_id: str = TEST_RUN_ID,
    schema_hash: str = "sha256:test",
    activate: bool = True,
) -> Path:
    """Materialize a published run (and active pointer) for a test article.

    A non-error run gets a reasoning file by default, because `publish_run`
    refuses to publish one without it — a fixture that omits it builds a run
    shape the product cannot actually produce, and then tests pass against a
    state no user can reach.
    """
    run_dir = article_dir / "extraction-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = extraction if isinstance(extraction, str) else json.dumps(extraction)
    (run_dir / "agent-extraction.json").write_text(payload)

    if reasoning is None:
        parsed = extraction if isinstance(extraction, dict) else _try_json(extraction)
        if not is_error_marker(parsed):
            reasoning = {"fields": []}
    if reasoning is not None:
        payload = reasoning if isinstance(reasoning, str) else json.dumps(reasoning)
        (run_dir / "agent-reasoning.json").write_text(payload)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": run_id,
                "article_id": article_dir.name,
                "created_at": "2026-01-01T00:00:00+00:00",
                "schema_hash": schema_hash,
                "inputs": {
                    "prepared_text": "sha256:test",
                    "domain_context": "sha256:test",
                    "skill": "sha256:test",
                },
                "agent": {},
            }
        )
        + "\n"
    )
    if activate:
        (article_dir / "active-run.json").write_text(json.dumps({"run_id": run_id}) + "\n")
    return run_dir
