# Capability: reviews

Per-article human review state — a reviewer's verdict on **what the extraction
SAYS**, field by field: verify, flag, override. Introduced by PR #16
(`feat/review-json`). Distinct from source metadata (what the document IS,
`specs/source-metadata/spec.md`) and from the extraction itself, which
reviewers never edit directly.

## Data model

One file per article: `data/papers/<id>/review.json`. The current
verification state IS the file — not an event log:

```json
{
  "version": 1,
  "base_extraction_sha256": "…",
  "fields": {
    "experiments[0].ph": {
      "author": "0000-0002-1825-0097",
      "signal": "flagged",
      "timestamp": "2026-07-07T…",
      "override_value": "6.5",
      "note": "table 2 says 6.5, not 6.8"
    }
  }
}
```

- **Paths are canonical**: bracket indices, no leading dot
  (`experiments[0].ph`). `canonical_review_path` normalizes dotted event
  syntax (`.experiments.0.ph`) on the way in.
- **Entries**: `author` (ORCID or empty), `signal` (`verified` | `flagged`),
  `timestamp`, plus optional `override_value`, `note`, `source`, `batch_id`.
- **One review per field, total.** A save replaces THE entry at that path,
  whoever wrote it. `author` is git-diff attribution, not partitioning —
  when reviewer B overwrites reviewer A, the review.json diff in the PR
  shows exactly that, and the PR is where disagreement is resolved.
  Multi-reviewer coordination is deliberately git's job, not the app's.
- Keys are sorted and writes are atomic (tmp + rename), so diffs are stable
  and a crash never leaves a torn file. A review.json that would be empty is
  deleted instead — no review state means no file.

## Staleness

Reviews are written against a specific `agent-extraction.json`. Every
non-empty write stamps `base_extraction_sha256` (hash of the extraction at
write time). If the article is later re-extracted, field paths may silently
misattach — so `GET /api/annotations/<id>` returns `base_stale: true` when
the stamp no longer matches, and the verifier shows a warning. Reviews are
still served alongside the warning (stale ≠ discarded). No stamp, no review
file, or no extraction at all mean "not stale" — nothing to misattach.

## User surface

**HTTP API** (the webapp keeps its historical names; the endpoint boundary
maps `status/reviewer/correct_value` ↔ storage's
`signal/author/override_value`):

- `GET /api/annotations/{id}` — one annotation per reviewed field path, plus
  `base_stale`.
- `PUT /api/annotations/{id}` — upsert one field's review. Requires `path` +
  `status`; `status ∈ verified | flagged`; **flags require a reviewer ORCID**
  (an anonymous "looks right" is acceptable; an anonymous objection is not).
- `DELETE /api/annotations/{id}/{path}` — drop THE entry, whoever wrote it.
  Clearing is not an attributable action, so nothing is recorded.

**Verifier UI:**

- Per-field review controls (verify / flag / override / clear) writing
  through the API above.
- **Typed inline editors**: `GET /api/schema/fields` reports an editor
  `kind` for every scalar slot (`enum` with permissible values, `integer`,
  `float`, `boolean`, `string`), so overrides are entered with a dropdown /
  number field / toggle instead of free text.
- **Extraction confidence** (read from `agent-reasoning.json`, never from
  the extraction) renders as a colored dot — red < 0.6 ≤ yellow ≤ 0.85 <
  green — per field and as an overall chip; a queue filter surfaces
  low-confidence fields.
- **Unextracted articles are first-class**: assembled articles with no
  extraction (or an error-marked one) still appear in the list with zeroed
  progress and render a "not yet extracted" placeholder — header and PDF
  work, so metadata review can precede extraction.
- Review progress (`n_reviewed`, `is_complete`, `has_flags`) counts leaf
  paths of the current extraction.

## Invariants

- **One entry per path.** WHEN a save lands on an already-reviewed path,
  THEN it replaces the entry regardless of author.
- **Empty means absent.** WHEN the last entry is cleared, THEN review.json
  is deleted, not left as an empty husk.
- **Stamped writes.** WHEN a non-empty review.json is written AND an
  extraction exists, THEN it carries `base_extraction_sha256`.
- **Stale is a warning, not a gate.** WHEN the stamp mismatches the current
  extraction, THEN `base_stale` is true AND the annotations are still
  served.
- **Anonymous flags are refused.** WHEN a flag arrives without a reviewer,
  THEN 400. Verifications may be anonymous.
- **No legacy awareness.** The framework reads and writes `review.json` and
  nothing else. WHEN unknown files (e.g. a pre-release `reviews.jsonl`) sit
  in the article directory, THEN they are inert and untouched — pruning them
  is the domain repo's business (alpha policy, `specs/README.md`).
- **Unreadable review.json is inert.** WHEN review.json fails to parse, THEN
  it reads as empty and is left in place for a human — never overwritten
  blind, never crashed on.
- **Atomic writes.** Same tmp + rename discipline as manifests.

## Code map

`src/litschema/reviews.py` (storage, canonical paths, staleness) ·
`src/litschema/webapp/app.py` (annotation endpoints, `/api/schema/fields`,
placeholder-aware article list) · `src/litschema/webapp/static/index.html`
(review controls, typed editors, confidence dots, placeholder). Tests:
`test_reviews.py`, `test_webapp_app.py`, `test_verifier_static.py`.
