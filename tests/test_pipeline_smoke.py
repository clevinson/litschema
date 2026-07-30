"""End-to-end smoke over one complete project: CLI verbs, then the verifier API.

The unit suite covers each capability in isolation, which is exactly how a
project can be internally consistent and still not work: `status` counted
reviews at a path nothing writes, `/api/article` served a run the annotations
were not bound to, and every unit test stayed green through both. This walks a
real project the way a first user does — status, doctor, validate, export, then
the read surface the verifier actually calls — and asserts the numbers agree
with each other.

`verifier_flow` is the fixture because it is a state the product can produce:
two extracted articles with markdown, metadata, reasoning, and run.json hashes
matching the project schema, plus one deliberately unextracted article. That
third one matters — an assembled-but-unextracted document is the first thing a
new user has, and it used to be invisible.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import litschema.webapp.app as webapp
from litschema import cli
from litschema.config import load_config

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "projects" / "verifier_flow"

EXTRACTED = ("brenner-2021-cover-crops", "okafor-2023-biochar-trial")
UNEXTRACTED = "unextracted-2024-pending"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A writable copy, so review writes never touch the committed fixture."""
    destination = tmp_path / "project"
    shutil.copytree(FIXTURE, destination)
    return destination


@pytest.fixture
def run_cli(project: Path):
    def invoke(*args: str):
        return CliRunner().invoke(cli.app, ["--config", str(project / "litschema.yaml"), *args])

    return invoke


@pytest.fixture
def client(project: Path):
    cfg = load_config(project / "litschema.yaml", reload=True)
    webapp.app.dependency_overrides[webapp.get_config] = lambda: cfg
    yield TestClient(webapp.app)
    webapp.app.dependency_overrides.clear()


# ── the CLI a first user runs ────────────────────────────────────────────────


def test_doctor_reports_a_healthy_project(run_cli) -> None:
    result = run_cli("doctor")

    assert "extraction schema:" in result.output
    assert "cannot resolve the extraction schema" not in result.output


def test_status_counts_agree_with_what_is_on_disk(run_cli) -> None:
    result = run_cli("status")

    assert result.exit_code == 0, result.output
    # Three assembled articles, two of them extracted against the current schema.
    assert "articles:    3" in result.output
    assert "converted:   3" in result.output
    assert "runs:        2 published" in result.output
    assert "active:      2 articles with an active run" in result.output
    assert "current:     2 active runs on the current schema" in result.output
    assert "0 articles with reviews" in result.output


def test_validate_accepts_every_published_extraction(run_cli) -> None:
    result = run_cli("validate")

    assert result.exit_code == 0, result.output
    assert "2/2 valid" in result.output


def test_export_emits_one_record_per_extracted_article(run_cli) -> None:
    result = run_cli("export")

    assert result.exit_code == 0, result.output
    records = [json.loads(line) for line in result.output.splitlines() if line.startswith("{")]
    assert {r["article_id"] for r in records} == set(EXTRACTED)


# ── the read surface the verifier calls ──────────────────────────────────────


def test_articles_listing_includes_the_unextracted_one(client) -> None:
    """The first document a new user has is one nobody has extracted yet."""
    articles = client.get("/api/articles").json()["articles"]
    by_id = {a["article_id"]: a for a in articles}

    assert set(by_id) == {*EXTRACTED, UNEXTRACTED}
    assert by_id[UNEXTRACTED]["has_extraction"] is False
    assert by_id[UNEXTRACTED]["active_run_id"] is None

    for article_id in EXTRACTED:
        entry = by_id[article_id]
        assert entry["has_extraction"] is True
        assert entry["active_run_id"]
        assert entry["schema_error"] is None, entry["schema_error"]
        assert entry["review_error"] is None
        assert entry["n_fields"] > 0
        assert entry["n_reviewed"] == 0
        assert entry["active_run"]["model"] == "claude-sonnet-5"


def test_every_read_endpoint_serves_an_extracted_article(client) -> None:
    article_id = EXTRACTED[0]
    run_id = client.get("/api/articles").json()["articles"][0]["active_run_id"]

    extraction = client.get(f"/api/article/{article_id}").json()
    assert extraction["article_id"] == article_id

    reasoning = client.get(f"/api/reasoning/{article_id}").json()
    assert reasoning["fields"], "reasoning with no fields cites nothing"

    markdown = client.get(f"/api/markdown/{article_id}").json()
    assert markdown["markdown"].strip()

    bibliography = client.get(f"/api/bibliography/{article_id}").json()
    assert bibliography["title"]

    annotations = client.get(f"/api/annotations/{article_id}/{run_id}").json()
    assert annotations["annotations"] == []
    assert annotations["review_error"] is None

    fields = client.get("/api/schema/fields").json()["fields"]
    assert fields, "typed editors need schema field metadata"


def test_reads_404_for_the_unextracted_article_but_it_still_lists(client) -> None:
    assert client.get(f"/api/article/{UNEXTRACTED}").status_code == 404
    assert client.get(f"/api/reasoning/{UNEXTRACTED}").status_code == 404
    # Its prepared text and bibliography exist — that is why it is visible at all.
    assert client.get(f"/api/markdown/{UNEXTRACTED}").status_code == 200
    assert client.get(f"/api/bibliography/{UNEXTRACTED}").json()["title"]


# ── a review round trip, seen from both ends ─────────────────────────────────


def test_a_review_write_moves_the_numbers_the_cli_reports(client, run_cli) -> None:
    """The write path and the read paths must agree about the same file.

    `status` once counted reviews at the version-1 article-root path, so it
    reported zero however much review work existed. Asserting the API and the
    CLI against one write is what catches that class of drift.
    """
    article_id = EXTRACTED[0]
    listing = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}
    run_id = listing[article_id]["active_run_id"]

    saved = client.put(
        f"/api/annotations/{article_id}/{run_id}", json={"path": "site_country"}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["state"] == "verified"

    after = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}
    assert after[article_id]["n_verified"] == 1
    assert after[article_id]["n_reviewed"] == 1

    assert "1 articles with reviews" in run_cli("status").output
    assert "(1 entries on active runs)" in run_cli("status").output


def test_an_override_survives_into_the_export(client, run_cli) -> None:
    article_id = EXTRACTED[0]
    run_id = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}[
        article_id
    ]["active_run_id"]

    corrected = client.put(
        f"/api/annotations/{article_id}/{run_id}",
        json={"path": "site_name", "override": {"op": "replace", "value": "Corrected Site"}},
    )
    assert corrected.status_code == 200, corrected.text

    result = run_cli("export")
    records = {
        json.loads(line)["article_id"]: json.loads(line)
        for line in result.output.splitlines()
        if line.startswith("{")
    }
    assert records[article_id]["site_name"] == "Corrected Site"


# ── the fixture's own citations must be true ─────────────────────────────────


def test_every_fixture_citation_resolves_to_real_content() -> None:
    """A fixture with wrong citations cannot test citation handling.

    This fixture was hand-authored, and its first version had `source_lines`
    written by eye rather than read off the file: two citations landed on a
    blank line one past the sentence they meant. That is the same failure mode
    `21c4` exists to catch, sitting inside the fixture that work would be
    tested against.

    This is also a working miniature of the check `21c4` proposes — every
    `L<n>` in range, ranges well-ordered, and at least one cited line carrying
    content — which is why it is worth having even before that lands.
    """
    import re

    problems: list[str] = []
    for reasoning_path in sorted(FIXTURE.rglob("extraction-runs/*/agent-reasoning.json")):
        article_dir = reasoning_path.parent.parent.parent
        lines = (article_dir / "article.md").read_text().splitlines()
        payload = json.loads(reasoning_path.read_text())

        for entry in payload["fields"]:
            spec = entry["source_lines"]
            cited: list[int] = []
            for part in str(spec).split(","):
                span = re.fullmatch(r"L(\d+)(?:-L?(\d+))?", part.strip())
                assert span, f"{article_dir.name}: unparseable source_lines {spec!r}"
                start = int(span.group(1))
                end = int(span.group(2)) if span.group(2) else start
                if end < start:
                    problems.append(f"{article_dir.name} {entry['path']}: {spec} runs backwards")
                cited.extend(range(start, end + 1))

            out_of_range = [n for n in cited if not 1 <= n <= len(lines)]
            if out_of_range:
                problems.append(
                    f"{article_dir.name} {entry['path']}: {spec} exceeds "
                    f"{len(lines)} lines"
                )
                continue
            if not any(lines[n - 1].strip() for n in cited):
                problems.append(
                    f"{article_dir.name} {entry['path']}: {spec} cites only blank lines"
                )

    assert not problems, "fixture citations do not resolve:\n  " + "\n  ".join(problems)
