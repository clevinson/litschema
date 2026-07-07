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
  "fields": {
    "experiments[0].ph": {
      "author": "0000-0002-1825-0097",
      "signal": "flagged",
      "timestamp": "2026-07-07T…",
      "base_extraction_sha256": "…",
      "override_value": "6.5",
      "note": "table 2 says 6.5, not 6.8"
    }
  }
}
```

- **Paths are canonical**: bracket indices, no leading dot
  (`experiments[0].ph`) — exactly what the extraction leaf-path walkers on
  both sides produce. `canonical_review_path` strips the leading dot the
  frontend prefixes; nothing else is rewritten. Keys are canonicalized on
  read too, so hand-edited files round-trip through upsert and delete.
- **Entries**: `author` (a validated ORCID, or empty), `signal`
  (`verified` | `flagged`), `timestamp`, the `base_extraction_sha256` stamp
  (see Staleness), plus optional `override_value`, `note`, `source`,
  `batch_id`. `override_value` may be the sentinel `"__remove__"`, meaning
  "this field should not exist" — every consumer (the verifier's effective
  view, the explore loader) applies it as a removal, never as a value.
- **One review per field, total.** A save replaces THE entry at that path,
  whoever wrote it. `author` is git-diff attribution, not partitioning —
  when reviewer B overwrites reviewer A, the review.json diff in the PR
  shows exactly that, and the PR is where disagreement is resolved.
  Multi-reviewer coordination is deliberately git's job, not the app's.
- Keys are sorted and writes are atomic (tmp + rename), so diffs are stable
  and a crash never leaves a torn file. A review.json that would be empty is
  deleted instead — no review state means no file.

## Staleness

Reviews are written against a specific `agent-extraction.json`. Every saved
entry is stamped with `base_extraction_sha256` — the hash of the extraction
at ITS write time (omitted when no extraction exists). If the article is
later re-extracted, field paths may silently misattach — so
`GET /api/annotations/<id>` returns `base_stale: true` when ANY entry's
stamp mismatches the current extraction, and the verifier shows a warning
banner. Stamps are per entry precisely so a fresh save after re-extraction
never disarms the warning for older entries: it clears only when every stale
entry has been re-reviewed or removed (self-healing). Reviews are still
served alongside the warning (stale ≠ discarded). Unstamped entries, no
review file, or no extraction at all mean "not stale" — nothing to
misattach.

## User surface

**HTTP API** (the webapp keeps its historical names; the endpoint boundary
maps `status/reviewer/correct_value` ↔ storage's
`signal/author/override_value`):

- `GET /api/annotations/{id}` — one annotation per reviewed field path, plus
  `base_stale`.
- `PUT /api/annotations/{id}` — upsert one field's review. Requires `path` +
  `status`; `status ∈ verified | flagged`; **flags require a reviewer ORCID**
  (an anonymous "looks right" is acceptable; an anonymous objection is not).
  Any non-empty reviewer is validated and normalized as an ORCID (URL forms
  accepted). Malformed bodies are 400s, never 500s.
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
  green — on the selected field's evidence panel and as an overall chip.
  `/api/articles` carries each article's overall confidence so the queue
  filter (e.g. `confidence != null && confidence < 0.7`) works.
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
- **Stamped entries.** WHEN an entry is saved AND an extraction exists,
  THEN that entry carries the current `base_extraction_sha256`; other
  entries keep their own stamps.
- **Stale is a warning, not a gate.** WHEN any entry's stamp mismatches the
  current extraction, THEN `base_stale` is true AND the annotations are
  still served. A save never disarms staleness for entries it did not touch.
- **Anonymous flags are refused.** WHEN a flag arrives without a reviewer,
  THEN 400. Verifications may be anonymous.
- **No legacy awareness.** The framework reads and writes `review.json` and
  nothing else. WHEN unknown files (e.g. a pre-release `reviews.jsonl`) sit
  in the article directory, THEN they are inert and untouched — pruning them
  is the domain repo's business (alpha policy, `specs/README.md`).
- **Unreadable review.json is inert.** WHEN review.json fails to parse
  (bad JSON, bad encoding, wrong shape), THEN reads treat it as empty and
  leave it in place for a human, AND writes are refused (HTTP 409) — it is
  never overwritten blind, never deleted, never crashed on.
- **Atomic writes.** Same tmp + rename discipline as manifests.

## Code map

`src/litschema/reviews.py` (storage, canonical paths, staleness) ·
`src/litschema/webapp/app.py` (annotation endpoints, `/api/schema/fields`,
placeholder-aware article list) · `src/litschema/webapp/static/index.html`
(review controls, typed editors, confidence dots, placeholder). Tests:
`test_reviews.py`, `test_webapp_app.py`, `test_verifier_static.py`.
