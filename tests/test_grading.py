"""`litschema grade`: evidence, parsing, storage, and the CLI against a fake claude."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from litschema import cli, grading
from litschema.articles import article_files
from litschema.config import load_config
from litschema.runs import run_files

FIXTURE = Path(__file__).parent / "fixtures" / "projects" / "verifier_flow"
ARTICLE = "brenner-2021-cover-crops"
RUN_ID = "01FLOWRUN0000000000000000"

FAKE_CLAUDE = """#!{python}
import json, os, re, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({{"args": args, "env": sorted(os.environ), "cwd": os.getcwd(), "prompt": prompt}}) + "\\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "crash":
    print("boom", file=sys.stderr)
    sys.exit(1)
if mode == "error":
    print(json.dumps({{"type": "result", "is_error": True, "subtype": "error_max_turns", "result": "ran out of turns"}}))
    sys.exit(1)
ids = [int(n) for n in re.findall(r"^### Field (\\d+):", prompt, re.M)]
verdicts = ["unsupported", "partial", "cannot_verify"]
grades = [
    {{"id": i, "verdict": verdicts[i] if i < len(verdicts) else "supported",
     "confidence": 0.9, "reasoning": f"field {{i}} reason"}}
    for i in ids
]
if mode == "missing":
    grades = grades[:-1] + [{{"id": 999, "verdict": "supported", "confidence": 1, "reasoning": "extra"}}]
print(json.dumps({{
    "type": "result", "is_error": False, "subtype": "success",
    "total_cost_usd": 0.0123,
    "usage": {{"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
              "cache_creation_input_tokens": 40}},
    "modelUsage": {{"claude-test-1": {{"outputTokens": 20, "canonicalModel": "claude-test-1"}}}},
    "structured_output": {{"grades": grades}},
}}))
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    copy = tmp_path / "project"
    shutil.copytree(FIXTURE, copy)
    return copy


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(FAKE_CLAUDE.format(python=sys.executable))
    script.chmod(0o755)
    log = tmp_path / "claude-calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    return log


def _calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _grade(project: Path, *args: str):
    return CliRunner(mix_stderr=False).invoke(
        cli.app, ["--config", str(project / "litschema.yaml"), "grade", *args]
    )


def _run(project: Path, article: str = ARTICLE):
    cfg = load_config(project / "litschema.yaml", reload=True)
    return run_files(article_files(cfg, article), RUN_ID)


# ── evidence ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("L7", [7]),
        ("L8-L9", [8, 9]),
        ("L8-9", [8, 9]),
        ("L3-L5,L9", [3, 4, 5, 9]),
        ("l2, L2", [2]),
        ("", []),
        (None, []),
    ],
)
def test_cited_lines(spec, expected) -> None:
    assert grading.cited_lines(spec) == expected


def test_evidence_shows_cited_lines_whole_and_trims_context(tmp_path) -> None:
    lines = [f"line {n} " + "x" * 400 for n in range(1, 21)]

    evidence = grading.build_evidence(lines, "L10", tmp_path).splitlines()

    assert [row.split(":")[0] for row in evidence] == [" L8", " L9", ">L10", " L11", " L12"]
    assert evidence[2] == f">L10: {lines[9]}"
    assert evidence[0] == f" L8: {lines[7][:300]}"


def test_evidence_marks_gaps_between_windows(tmp_path) -> None:
    lines = [f"line {n}" for n in range(1, 31)]

    evidence = grading.build_evidence(lines, "L3,L20", tmp_path).splitlines()

    assert "   ..." in evidence
    assert evidence[evidence.index("   ...") + 1] == " L18: line 18"


def test_evidence_caps_lines_and_says_how_many_are_hidden(tmp_path) -> None:
    lines = [f"line {n}" for n in range(1, 101)]

    evidence = grading.build_evidence(lines, "L1-L60", tmp_path).splitlines()

    assert len([row for row in evidence if row.lstrip(">").startswith(("L", " L"))]) == 40
    assert evidence[-1] == "   ... (22 more lines not shown)"


def test_evidence_without_a_citation(tmp_path) -> None:
    assert grading.build_evidence(["a"], "", tmp_path) == "(no citation)"


def test_evidence_notes_citations_past_the_end(tmp_path) -> None:
    evidence = grading.build_evidence(["a", "b"], "L9", tmp_path)

    assert "cited L9 is past the end of the document, 2 lines" in evidence


def test_evidence_gives_figure_paths_for_cited_figure_lines(tmp_path) -> None:
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "fig1.png").write_bytes(b"png")
    lines = ["intro", "![](figures/fig1.png)", "![Map](figures/gone.png)", "after"]

    evidence = grading.build_evidence(lines, "L2-L3", tmp_path)

    assert f">L2: [figure image: {tmp_path / 'figures' / 'fig1.png'}]" in evidence
    assert ">L3: [figure image missing: figures/gone.png]" in evidence


def test_rubric_hash_is_the_sha256_of_the_rubric_text() -> None:
    expected = "sha256:" + hashlib.sha256(grading.RUBRIC.encode()).hexdigest()

    assert expected == grading.RUBRIC_SHA256
    # Pinned: a rubric edit changes which grades count as current, so it
    # must be a deliberate change here too.
    assert grading.RUBRIC_SHA256 == (
        "sha256:51126430921013397f8c8c68c43af7b5b041c0c4027e2aa012c54b6e3372daaa"
    )


def test_prompt_carries_value_meaning_note_and_evidence(project) -> None:
    run = _run(project)
    cfg = load_config(project / "litschema.yaml", reload=True)
    targets = grading.grade_targets(run)
    lines = run.article.markdown.read_text().split("\n")

    prompt = grading.build_prompt(
        targets, lines, grading.slot_descriptions(cfg), run.article.article_dir
    )

    temp = prompt.split("### Field 2: mean_annual_temperature_c\n")[1].split("###")[0]
    assert "Meaning: Site mean annual temperature in degrees Celsius." in temp
    assert "Value: 9.4" in temp
    assert "Extractor's note: (none)" in temp
    assert ">L8: annual temperature at the site is 9.4 °C." in temp
    measurement = prompt.split("### Field 6: measurements[0]\n")[1].split("###")[0]
    assert "Meaning: Reported soil measurements." in measurement
    assert '"outcome": "soil organic carbon"' in measurement


# ── parsing the result ──────────────────────────────────────────────────────


def _targets(n: int) -> list[grading.GradeTarget]:
    return [
        grading.GradeTarget(path=f"f{i}", value=i, note=None, source_lines="L1") for i in range(n)
    ]


def test_parse_keeps_known_ids_and_lists_missing_ones() -> None:
    result = {
        "structured_output": {
            "grades": [
                {"id": 2, "verdict": "partial", "confidence": 0.6, "reasoning": "r2"},
                {"id": 0, "verdict": "supported", "confidence": 1.4, "reasoning": "r0"},
                {"id": 0, "verdict": "unsupported", "confidence": 0.1, "reasoning": "dup"},
                {"id": 7, "verdict": "supported", "confidence": 0.9, "reasoning": "extra"},
                {"id": 3, "verdict": "maybe", "confidence": 0.9, "reasoning": "bad verdict"},
            ]
        }
    }

    fields, ungraded = grading.parse_grades(result, _targets(4))

    assert fields == [
        {"path": "f0", "verdict": "supported", "confidence": 1.0, "reasoning": "r0"},
        {"path": "f2", "verdict": "partial", "confidence": 0.6, "reasoning": "r2"},
    ]
    assert ungraded == ["f1", "f3"]


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"structured_output": None},
        {"structured_output": {"grades": []}},
        {
            "structured_output": {
                "grades": [{"id": 9, "verdict": "supported", "confidence": 1, "reasoning": ""}]
            }
        },
    ],
)
def test_parse_refuses_a_result_that_grades_nothing(result) -> None:
    with pytest.raises(grading.GradeError):
        grading.parse_grades(result, _targets(2))


@pytest.mark.parametrize(
    ("model_usage", "expected"),
    [
        (
            {"claude-haiku-4-5": {"outputTokens": 5, "canonicalModel": "claude-haiku-4-5"}},
            "claude-haiku-4-5",
        ),
        (
            {
                "claude-haiku-4-5": {"outputTokens": 5},
                "claude-sonnet-5": {"outputTokens": 900},
            },
            "claude-sonnet-5",
        ),
        ({}, None),
        (None, None),
    ],
)
def test_reported_model_comes_from_model_usage(model_usage, expected) -> None:
    assert grading.reported_model({"modelUsage": model_usage}) == expected


def test_grader_env_strips_api_credentials() -> None:
    env = grading.grader_env(
        {
            "ANTHROPIC_API_KEY": "k",
            "ANTHROPIC_AUTH_TOKEN": "t",
            "ANTHROPIC_BASE_URL": "u",
            "ANTHROPIC_MODEL": "kept",
            "HOME": "/home/x",
        }
    )

    assert env == {"ANTHROPIC_MODEL": "kept", "HOME": "/home/x"}


# ── storage ─────────────────────────────────────────────────────────────────


def _stored(run, grade_id: str, created_at: str, **overrides) -> dict:
    record = {
        "version": 1,
        "grade_id": grade_id,
        "article_id": run.article.article_id,
        "run_id": run.run_id,
        "created_at": created_at,
        "grader": {"requested_model": "m", "model": "m", "rubric_sha256": grading.RUBRIC_SHA256},
        "inputs": grading.input_hashes(run),
        "fields": [
            {"path": "site_name", "verdict": "partial", "confidence": 0.5, "reasoning": grade_id}
        ],
        "ungraded": [],
        "usage": {},
        **overrides,
    }
    grading.write_grade(run, record)
    return record


def test_current_grade_is_the_newest(project) -> None:
    run = _run(project)
    _stored(run, "01A", "2026-09-01T00:00:00+00:00")
    _stored(run, "01C", "2026-09-03T00:00:00+00:00")
    _stored(run, "01B", "2026-09-02T00:00:00+00:00")

    status = grading.current_grade(run)

    assert status.grade["grade_id"] == "01C"
    assert status.stale == []
    assert sorted(p.name for p in grading.grades_dir(run).iterdir()) == [
        "01A.json",
        "01B.json",
        "01C.json",
    ]


def test_a_grade_whose_inputs_changed_is_stale(project) -> None:
    run = _run(project)
    _stored(run, "01A", "2026-09-01T00:00:00+00:00")
    run.article.markdown.write_text(run.article.markdown.read_text() + "\nedited\n")
    _stored(run, "01B", "2026-09-02T00:00:00+00:00")
    _stored(run, "01C", "2026-09-03T00:00:00+00:00", inputs={"extraction": "sha256:old"})

    status = grading.current_grade(run)

    assert status.grade["grade_id"] == "01B"
    assert [g["grade_id"] for g in status.stale] == ["01C"]


def test_no_current_grade_when_every_grade_is_stale(project) -> None:
    run = _run(project)
    _stored(run, "01A", "2026-09-01T00:00:00+00:00")
    run.article.markdown.write_text("rewritten\n")

    status = grading.current_grade(run)

    assert status.grade is None
    assert [g["grade_id"] for g in status.stale] == ["01A"]


def test_a_corrupt_grade_file_raises(project) -> None:
    run = _run(project)
    grading.grades_dir(run).mkdir()
    (grading.grades_dir(run) / "01X.json").write_text("{not json")

    with pytest.raises(grading.GradeCorruptError):
        grading.current_grade(run)


# ── the command ─────────────────────────────────────────────────────────────


def test_grade_writes_a_grade_beside_the_run(project, fake_claude) -> None:
    result = _grade(project, ARTICLE)

    assert result.exit_code == 0, result.output + result.stderr
    assert "8 fields: 1 unsupported, 1 partial, 1 can't verify" in result.output
    run = _run(project)
    [path] = list(grading.grades_dir(run).glob("*.json"))
    record = json.loads(path.read_text())
    assert path.stem == record["grade_id"] and len(record["grade_id"]) == 26
    assert record["version"] == 1
    assert (record["article_id"], record["run_id"]) == (ARTICLE, RUN_ID)
    assert record["grader"] == {
        "harness": "claude-code",
        "harness_version": "9.9.9",
        "requested_model": "claude-sonnet-5",
        "model": "claude-test-1",
        "rubric_sha256": grading.RUBRIC_SHA256,
        "litschema_version": record["grader"]["litschema_version"],
    }
    assert record["inputs"] == grading.input_hashes(run)
    assert record["fields"][0] == {
        "path": "site_name",
        "verdict": "unsupported",
        "confidence": 0.9,
        "reasoning": "field 0 reason",
    }
    assert record["ungraded"] == []
    assert record["usage"] == {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 40,
        "cost_estimate_usd": 0.0123,
    }


def test_grade_invokes_claude_without_api_credentials(project, fake_claude) -> None:
    assert _grade(project, ARTICLE, "--model", "claude-haiku-4-5").exit_code == 0

    [call] = _calls(fake_claude)
    args = call["args"]
    article_dir = str((project / "data" / "papers" / ARTICLE).resolve())
    assert args[0] == "-p"
    assert args[args.index("--model") + 1] == "claude-haiku-4-5"
    assert args[args.index("--output-format") + 1] == "json"
    assert json.loads(args[args.index("--json-schema") + 1]) == grading.GRADE_SCHEMA
    assert args[args.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in args
    assert args[args.index("--tools") + 1] == "Read"
    assert args[args.index("--allowedTools") + 1] == "Read"
    assert args[args.index("--add-dir") + 1] == article_dir
    assert "--bare" not in args
    assert Path(call["cwd"]).resolve() == Path(article_dir)
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"} & set(
        call["env"]
    )


def test_grade_run_option_grades_a_named_run(project, fake_claude) -> None:
    article_dir = project / "data" / "papers" / ARTICLE
    other = article_dir / "extraction-runs" / "01OTHERRUN000000000000000"
    shutil.copytree(article_dir / "extraction-runs" / RUN_ID, other)

    result = _grade(project, ARTICLE, "--run", other.name)

    assert result.exit_code == 0, result.output
    assert len(list((other / "grades").glob("*.json"))) == 1
    assert not (article_dir / "extraction-runs" / RUN_ID / "grades").exists()


def test_grade_all_skips_runs_already_graded_by_the_same_model(project, fake_claude) -> None:
    first = _grade(project, "--all", "--model", "claude-haiku-4-5")
    assert first.exit_code == 0, first.output
    assert len(_calls(fake_claude)) == 2  # two extracted articles; one is unextracted

    again = _grade(project, "--all", "--model", "claude-haiku-4-5")
    assert again.exit_code == 0, again.output
    assert "already graded by claude-haiku-4-5" in again.output
    assert len(_calls(fake_claude)) == 2

    other_model = _grade(project, "--all", "--model", "claude-sonnet-5")
    assert other_model.exit_code == 0
    assert len(_calls(fake_claude)) == 4

    forced = _grade(project, "--all", "--model", "claude-haiku-4-5", "--force")
    assert forced.exit_code == 0
    assert len(_calls(fake_claude)) == 6
    assert len(list(grading.grades_dir(_run(project)).glob("*.json"))) == 3


def test_grade_all_regrades_a_stale_grade(project, fake_claude) -> None:
    assert _grade(project, "--all").exit_code == 0
    markdown = project / "data" / "papers" / ARTICLE / "article.md"
    markdown.write_text(markdown.read_text() + "\nappendix\n")

    result = _grade(project, "--all")

    assert result.exit_code == 0
    assert len(_calls(fake_claude)) == 3


def test_ungraded_fields_are_stored_and_fail_the_command(project, fake_claude, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "missing")

    result = _grade(project, ARTICLE)

    assert result.exit_code == 1
    assert "1 fields left ungraded" in result.output
    [path] = list(grading.grades_dir(_run(project)).glob("*.json"))
    record = json.loads(path.read_text())
    assert record["ungraded"] == ["measurements[1]"]
    assert len(record["fields"]) == 7
    assert not grading.has_current_grade(_run(project), "claude-sonnet-5")


@pytest.mark.parametrize(("mode", "message"), [("error", "ran out of turns"), ("crash", "boom")])
def test_a_failed_claude_call_writes_nothing_and_exits_1(
    project, fake_claude, monkeypatch, mode, message
) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)

    result = _grade(project, ARTICLE)

    assert result.exit_code == 1
    assert message in result.output
    assert f"not fully graded: {ARTICLE}" in result.output
    assert not grading.grades_dir(_run(project)).exists()


def test_missing_claude_says_how_to_install(project, tmp_path, monkeypatch) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    result = _grade(project, ARTICLE)

    assert result.exit_code == 1
    assert "claude is not on PATH; install Claude Code" in result.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "give an article id or --all"),
        ([ARTICLE, "--all"], "give an article id or --all"),
        (["--all", "--run", RUN_ID], "--run needs a single article"),
    ],
)
def test_grade_rejects_bad_selections(project, args, message) -> None:
    result = _grade(project, *args)

    assert result.exit_code == 2
    assert message in result.output


@pytest.mark.parametrize(
    ("article", "message"),
    [("unextracted-2024-pending", "has no active run"), ("nope", "unknown article")],
)
def test_grade_refuses_articles_it_cannot_grade(project, fake_claude, article, message) -> None:
    result = _grade(project, article)

    assert result.exit_code in (1, 2)
    assert message in result.output
    assert _calls(fake_claude) == []


def test_grade_enforces_the_version_pin(project, fake_claude) -> None:
    config = project / "litschema.yaml"
    config.write_text(config.read_text() + 'litschema_version: "0.0.1"\n')

    result = _grade(project, ARTICLE)

    assert result.exit_code == 3
    assert "pinned to litschema 0.0.1" in result.stderr
    assert _calls(fake_claude) == []


# ── the verifier's read surface ─────────────────────────────────────────────


@pytest.fixture
def client(project):
    from fastapi.testclient import TestClient

    import litschema.webapp.app as webapp

    cfg = load_config(project / "litschema.yaml", reload=True)
    webapp.app.dependency_overrides[webapp.get_config] = lambda: cfg
    yield TestClient(webapp.app)
    webapp.app.dependency_overrides.clear()


def test_grades_endpoint_returns_the_current_grade(project, client) -> None:
    run = _run(project)
    assert client.get(f"/api/grades/{ARTICLE}").json() == {
        "run_id": RUN_ID,
        "grade": None,
        "stale": [],
    }
    _stored(run, "01A", "2026-09-01T00:00:00+00:00")
    _stored(run, "01B", "2026-09-02T00:00:00+00:00", inputs={"extraction": "sha256:old"})

    body = client.get(f"/api/grades/{ARTICLE}", params={"run_id": RUN_ID}).json()

    assert body["grade"]["grade_id"] == "01A"
    assert body["stale"] == ["01B"]


@pytest.mark.parametrize(
    ("url", "status"),
    [
        ("/api/grades/unextracted-2024-pending", 404),
        (f"/api/grades/{ARTICLE}?run_id=01NOSUCHRUN", 404),
        ("/api/grades/..", 404),
    ],
)
def test_grades_endpoint_404s_without_a_run(client, url, status) -> None:
    assert client.get(url).status_code == status


def test_grades_endpoint_reports_a_corrupt_grade(project, client) -> None:
    run = _run(project)
    grading.grades_dir(run).mkdir()
    (grading.grades_dir(run) / "01X.json").write_text("[]")

    response = client.get(f"/api/grades/{ARTICLE}")

    assert response.status_code == 409
    assert "01X.json" in response.json()["detail"]


def test_listing_carries_flag_counts_from_the_current_grade(project, client) -> None:
    run = _run(project)
    _stored(
        run,
        "01A",
        "2026-09-01T00:00:00+00:00",
        fields=[
            {"path": "site_name", "verdict": "unsupported", "confidence": 0.9, "reasoning": ""},
            {"path": "crops", "verdict": "partial", "confidence": 0.7, "reasoning": ""},
            {"path": "tillage", "verdict": "cannot_verify", "confidence": 0.5, "reasoning": ""},
            {"path": "replicates", "verdict": "supported", "confidence": 1, "reasoning": ""},
        ],
    )

    by_id = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}

    assert by_id[ARTICLE]["grade"] == {
        "grade_id": "01A",
        "created_at": "2026-09-01T00:00:00+00:00",
        "model": "m",
        "flags": 2,
        "unsupported": 1,
        "partial": 1,
        "cannot_verify": 1,
    }
    assert by_id[ARTICLE]["grade_error"] is None
    assert by_id["okafor-2023-biochar-trial"]["grade"] is None
    assert by_id["unextracted-2024-pending"]["grade"] is None


def test_listing_survives_a_corrupt_grade(project, client) -> None:
    run = _run(project)
    grading.grades_dir(run).mkdir()
    (grading.grades_dir(run) / "01X.json").write_text("{")

    by_id = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}

    assert by_id[ARTICLE]["grade"] is None
    assert "01X.json" in by_id[ARTICLE]["grade_error"]
