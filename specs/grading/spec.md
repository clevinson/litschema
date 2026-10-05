# Capability: grading

Status: current.

`litschema grade` asks a separate model to check each extracted value against
the evidence the extractor cited. The grader sees the value, the extractor's
basis and note, and the evidence, and returns per reasoning entry a
`confidence`: the probability (0-1) that the value is correct as stated and
supported by its cited lines. It is not confidence in a verdict; there is no
verdict. `confidence` is `null` only when the field cannot be judged. Fields
below 0.9, or null, carry a one-line `issue`. Grades sit beside the immutable
run like reviews do and never change the extraction.

## Bands

Bands are derived from `confidence`, never stored per field:

| band | confidence |
|---|---|
| `high` | >= 0.9 |
| `check` | >= 0.6 and < 0.9 |
| `low` | < 0.6 |
| `cannot_verify` | null |

The thresholds live in `litschema.grading.BANDS` and are copied into each
grade's `grader.bands`; readers use the grade's own `bands` when present, so a
report and the app agree on an old grade after the thresholds move. Flags are
`check`, `low`, and `cannot_verify`.

Runs and the active pointer are owned by `specs/article-store/spec.md`; the
reasoning contract by `specs/extraction/spec.md`; how the verifier shows grades
by `specs/verifier/spec.md`.

## Command

```
litschema grade <article_id> | --all [--run <run-id>] [--model <model>] [--force] [--concurrency N]
```

- WHEN an article id is given THEN its active run is graded, or the run named by
  `--run`. An unknown article, no active run, an unpublished run, or an
  error-marker run exits 1 (unknown or malformed ids exit 2) without calling
  the grader.
- WHEN `--all` is given THEN every article's active run is graded, except runs
  that already have a current, complete grade from the same model (requested or
  reported) under the same rubric hash. `--force` grades those too. Articles
  without an active run and error-marker runs are skipped.
- An article id and `--all` together, neither, or `--run` with `--all` exit 2.
- `--model` defaults to `claude-sonnet-5`; `--model claude-haiku-4-5` is a
  cheap pass. `--concurrency` (default 2) is the number of runs graded at once.
- The verb enforces the project's version pin like every project verb.
- Exit 0 when every requested run was graded with every field graded; 1
  otherwise, naming the articles that were not fully graded.

Each graded run prints its low, check, and can't-verify counts, the reported model, the cost
estimate, and wall time; `--all` ends with a total.

## The grader call

One `claude -p` call per run, through the user's own Claude Code install:

```
claude -p "Grade the fields described on stdin." --model <model>
  --output-format json --json-schema <GRADE_SCHEMA>
  --setting-sources project --strict-mcp-config --no-session-persistence
  --tools Read --allowedTools Read --add-dir <article dir>
```

The prompt goes on stdin; the working directory is the article directory.
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_BASE_URL` are
removed from the child environment so the call uses the logged-in account.
`--bare` is never passed. A missing `claude` on PATH exits 1 with install
instructions. A non-zero exit, `is_error: true`, output that is not JSON, or a
result with no usable grades fails that run and writes nothing.

The grade records the harness version from `claude --version` and the model
from the result's `modelUsage`: the entry with the most output tokens, using its
`canonicalModel` when present.

## Evidence

The prompt holds the rubric, then one block per reasoning entry, numbered from
0 in file order:

- the entry's path;
- the schema slot's description, looked up by the path with indices dropped;
- the value, read from the extraction at that path (the reasoning entry's
  `value` when the path does not resolve);
- the extractor's `basis` (`(not given)` for old runs) and its `note`, or the
  old free-text `reasoning` when there is no note;
- the cited lines of `article.md`, each shown whole and marked `>`, with two
  lines of context either side trimmed to 300 characters, gaps shown as `...`,
  at most 40 lines per field and a note of how many more were hidden;
- a cited figure line (`![](figures/NAME)`) replaced by the image's absolute
  path, which the grader opens with Read, or marked missing;
- a note when a citation points past the end of the document, and
  `(no citation)` when there is none.

## Rubric

The rubric text lives in `litschema.grading.RUBRIC`; its SHA-256 is recorded on
every grade and pinned by a test, so changing it is deliberate. It tells the
grader:

- a value stated plainly in the evidence: about 0.95 or higher;
- a routine conversion or a clear mapping onto a schema enum stays high if
  correct;
- an inference, a choice among alternatives, or outside knowledge lowers the
  confidence;
- evidence about a different site, setup, sample, or treatment, or evidence
  that contradicts the value: low;
- `null` only for an unreadable figure or no citation;
- the basis and note say what to check; they are claims, not evidence.

## Parsing

The JSON schema asks for `{"grades": [{id, confidence, issue}]}` with
`confidence` a number in 0-1 or null and `issue` a string, empty when the value
is high. An optional `issue` was left out for about half the flagged fields. The first grade per known id wins;
unknown ids, repeats, and grades without a numeric or null confidence are
ignored; confidence is clamped to 0-1. An `issue` is kept only when the band is
not `high`. Entries the grader skipped are listed in `ungraded`. A grade with
any ungraded entry is stored, fails the command, and does not count as complete
for `--all`.

## Storage

`data/papers/<id>/extraction-runs/<run-id>/grades/<grade-id>.json`, one file
per grading pass, written atomically and never overwritten. The grade id is a
ULID.

```json
{
  "version": 2,
  "grade_id": "01K…",
  "article_id": "…", "run_id": "…",
  "created_at": "…",
  "grader": {"harness": "claude-code", "harness_version": "2.1.283",
             "requested_model": "claude-haiku-4-5", "model": "claude-haiku-4-5",
             "rubric_sha256": "sha256:…", "bands": {"high": 0.9, "check": 0.6},
             "litschema_version": "…"},
  "inputs": {"extraction": "sha256:…", "reasoning": "sha256:…", "prepared_text": "sha256:…"},
  "fields": [{"path": "experiments[0].ph", "confidence": 0.72,
              "issue": "pH read from a figure axis, not the text."},
             {"path": "experiments[0].depth_cm", "confidence": 0.97}],
  "ungraded": [],
  "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0, "cost_estimate_usd": 0.0}
}
```

Field paths are canonical (no leading dot). `inputs` hashes the run's
`agent-extraction.json`, `agent-reasoning.json`, and the article's `article.md`.

- The current grade is the newest grade (by `created_at`, then id) whose
  `inputs` match the run's files now.
- A newer grade whose inputs don't match is stale: it is ignored and reported.
- A grade file that is not valid JSON or not a version 1 or 2 grade is
  corrupt; readers raise rather than skip it.
- Version-1 grades stored `verdict`, `confidence`, and `reasoning` per field.
  Readers map the verdict to a band (`supported` high, `partial` check,
  `unsupported` low, `cannot_verify` cannot_verify) and show no percentage,
  since that confidence was in the verdict.

A grade applies to its path and, like evidence, to every leaf beneath it that
has no grade of its own.

## Out of scope

Changing extractions; choosing between runs or comparing models; calibrating
the grader against human reviews; grading with agents other than Claude Code.

## Test obligations

`tests/test_grading.py` pins: citation parsing; evidence windows, whole cited
lines, trimmed context, gaps, the 40-line cap, figure paths, missing citations,
and citations past the end; the rubric hash; slot descriptions and values in
the prompt, with the extractor's basis and note; parsing with missing, extra,
repeated, invalid, and null-confidence grades; band thresholds and the
version-1 verdict mapping; the
reported model; credential stripping; newest-grade selection, stale and corrupt
grades; and the command end to end against a fake `claude` placed first on
PATH: the stored record, the exact flags and environment, `--run`, `--all`
skipping and `--force`, regrading after a stale grade, ungraded fields, failed
calls, a missing `claude`, bad selections, and the version pin.
