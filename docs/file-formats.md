# File formats

Every file is JSON. The [specs](https://github.com/clevinson/litschema/tree/main/specs)
define each format; these examples are shortened.

## `agent-reasoning.json`

One entry per extracted value. `note` is required unless `basis` is `stated`.

```json
{
  "fields": [
    {"path": ".site_name", "value": "Nsukka Research Farm",
     "source_lines": "L5", "basis": "stated"},
    {"path": ".latitude", "value": "6.87", "source_lines": "L6",
     "basis": "converted", "note": "Converted 6°52' N to decimal degrees."}
  ]
}
```

## `run.json`

Written by litschema when it publishes a run. The agent never writes this file.

```json
{
  "version": 1,
  "run_id": "01J2Q4Y7Y9K0M3T6W8X1Z5A9BC",
  "article_id": "beerling-2024",
  "created_at": "2026-07-26T18:04:11Z",
  "schema_hash": "sha256:9f2a…",
  "inputs": {
    "prepared_text": "sha256:c41d…",
    "domain_context": "sha256:7be0…",
    "skill": "sha256:1a88…"
  },
  "agent": {
    "harness": "claude-code", "harness_version": "2.1.219",
    "provider": "anthropic", "model": "claude-opus-5", "effort": "high"
  },
  "litschema": {"version": "0.1.2", "source": "release"},
  "conversion": {
    "tool": "pymupdf4llm", "tool_version": "1.28.2",
    "pdf_sha256": "sha256:5e0a…", "text_sha256": "sha256:c41d…"
  }
}
```

## `grades/<grade-id>.json`

One file per grading pass. The newest grade whose input hashes still match the
run is the current one.

```json
{
  "version": 2,
  "grader": {"harness": "claude-code", "model": "claude-sonnet-5",
             "rubric_sha256": "sha256:…", "bands": {"high": 0.9, "check": 0.6}},
  "inputs": {"extraction": "sha256:…", "reasoning": "sha256:…",
             "prepared_text": "sha256:…"},
  "fields": [
    {"path": "experiments[0].ph", "confidence": 0.72,
     "issue": "pH read from a figure axis, not the text."},
    {"path": "experiments[0].depth_cm", "confidence": 0.97}
  ]
}
```

## `review.json`

One entry per reviewed value. An empty entry means verified. `override`
replaces, removes, or adds a value.

```json
{
  "version": 2,
  "fields": {
    "experiments[0]": {},
    "experiments[0].ph": {
      "override": {"op": "replace", "value": 6.5},
      "note": "table 2 corrects the prose"
    },
    "experiments[1].yield": {"override": {"op": "remove"}}
  }
}
```
