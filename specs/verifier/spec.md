# Capability: verifier

`litschema verify` — the local review webapp. The bibliographic header is
`specs/source-metadata/spec.md`; the review model, annotation endpoints, and
typed editors are `specs/reviews/spec.md`. This spec covers everything else:
the read endpoints, the queue, the filter language and its trust boundary,
and the launch posture. Documented as-built from the 2026-07-07 audit.

## Launch

`litschema verify [--port/-p 8000]` starts uvicorn bound to **127.0.0.1
only** (never exposed beyond loopback) and opens the browser once. Config is
injected via app state; launching the app any other way fails loudly. Every
endpoint maps traversal-shaped article ids to HTTP 404 via the
`InvalidArticleIdError` handler.

## Read endpoints

- `GET /` — the single-file frontend (`static/index.html`).
- `GET /api/articles` — the queue. One entry per manifest in the store
  (sorted by article id), regardless of extraction state:
  - always: `article_id`, `doi`, `title`, `year`, `journal`, `authors[]`,
    `corporate_author`, `metadata_source`;
  - `has_extraction` (false for missing, unparseable, or error-marked
    extractions), `confidence` (overall, from `agent-reasoning.json`, else
    null);
  - extracted articles add `study_types`, `focus_areas`, `document_type`,
    `n_setups`, and review progress: `n_fields` (extraction leaf count),
    `n_reviewed`, `n_verified`, `n_flagged`, `is_complete`, `has_flags`
    (reviews whose paths no longer exist in the extraction are excluded
    from counts). Several of these fields are ERW-schema passthroughs in a
    generic surface — cleanup tracked in the improvements backlog.
- `GET /api/article/{id}` — the raw extraction JSON; 404 when absent.
- `GET /api/markdown/{id}` — the prepared text with the references section
  stripped (`strip_references`: truncates from the last references-like
  heading unless primary-content headings follow it); 404 when absent.
- `GET /api/reasoning/{id}` — the raw reasoning JSON; 404 when absent.
- `GET /api/pdf/{id}` — the article PDF: canonical `<id>.pdf` first, then
  the manifest `filename` under the article dir, then the inbox; 404
  otherwise.
- `GET /api/orcid/{orcid_id}` — the app's ONLY outbound network call:
  resolves a (regex-validated, URL-form-normalized) ORCID iD to a display
  name via `pub.orcid.org`, 8-second timeout; 400 invalid id, 404 unknown,
  502 anything else. Used by the reviewer-identity modal.
- `GET /api/schema/fields` — editor metadata (`specs/reviews/spec.md`).

## The frontend

Single HTML file, no build step. Layout: toolbar (article picker, prev/next,
filter, view-mode, theme) over two panels — the document (markdown with line
numbers, in-document search, PDF button, bibliographic header) and the
extraction review (review table / overview table / JSON tree) — plus a
docked evidence overlay showing the selected field's value, confidence dot,
reasoning, and source-line cycling. View state (`view`, `overview`) and the
queue filter persist in the URL; unextracted articles render a placeholder
(`specs/reviews/spec.md`).

**Queue filter = JavaScript, deliberately.** The filter box compiles its
expression with `new Function` and runs it against each article's summary
(deep fields lazy-loaded on first use). This is a power feature for a
local, single-user tool, and it is NOT a sandbox: **filter expressions are
code**, they run with full page privileges, and they arrive via the
shareable `?filter=` URL parameter. The trust boundary is the URL bar — do
not open verifier links from sources you wouldn't paste into the console.
(Tightening options tracked in the improvements backlog.)

Keyboard: Cmd+]/Cmd+[ cycle articles; n/p or arrow keys cycle evidence for
the selected field; Enter/Shift+Enter step search hits; Escape clears.

## Invariants

- **Loopback only.** WHEN the verifier launches, THEN it binds 127.0.0.1;
  there is no flag to expose it. (`test_webapp_app.py`)
- **Nothing is hidden from the queue.** WHEN an article has no extraction,
  no markdown, or an error marker, THEN it still lists (zeroed progress)
  and renders — only its extraction panel degrades.
  (`test_webapp_app.py`)
- **Invalid ids are 404s, never 500s.** WHEN a request path smuggles `..`
  or separators into an article id, THEN the id guard rejects it and the
  handler answers 404. (`test_webapp_app.py`)
- **One outbound call.** WHEN the verifier runs, THEN the ORCID lookup is
  the only endpoint that touches the network; everything else is local
  disk.

## Code map

`src/litschema/webapp/app.py` (endpoints, launch) ·
`src/litschema/webapp/search.py` (`strip_references`) ·
`src/litschema/webapp/static/index.html` (the app). Tests:
`test_webapp_app.py`, `test_verifier_static.py`, `test_smoke.py` (CLI
wiring).
