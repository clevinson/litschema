# Spike findings: PDF rendering with source highlights

Exploratory work for kata `b85y`. Nothing here is wired into the app.

## Verdict

**Feasible, and the hard part is not what I expected.** Locating a citation in
the PDF works well. Making the highlight *readable* is where the design work
is, and a naive implementation produces something actively worse than the
markdown pane it would replace.

## Measured, against the six-paper soc-field-trials demo

Two-tier localisation — exact phrase search first, token matching as fallback:

| article | located / cited |
|---|---|
| francioli-2016 | 7 / 9 |
| poffenbarger-2017 | 8 / 10 |
| sun-2016 | 30 / 47 |
| zhang-2019 | 39 / 47 |

Phrase search carries most of it (39 of 41 on zhang). Token fallback recovers
tables and reflowed text.

Almost every remaining miss is `too-short` or `no-tokens` — the agent cited a
blank or near-empty markdown line. That is an extraction-quality defect, not a
localisation failure, and it is filed separately as kata `21c4`. Fixing it
raises this feature's apparent success rate without touching this code.

## The finding that matters

The first render highlighted **every matching word wherever it appeared**,
including "the", "was", "in". The result stippled marks across the whole page
and was unusable — see the difference between the two renders in the commit.

Two changes fixed it:

1. **Drop stopwords.** A citation is identified by its rare words. Matching
   common ones highlights half the page.
2. **Highlight a passage, not the matches.** Take the densest vertical run of
   matching words, then highlight *everything on those lines* — including the
   words in between. That is what a marker pen does, and it reads as one
   coherent passage instead of confetti.

After both, table rows highlight as whole rows and prose highlights as
paragraphs.

## Architecture, if this proceeds

Compute rectangles server-side with PyMuPDF (already a dependency — no new
package) and serve `(page, rects)` per cited line; render client-side with
PDF.js, overlaying absolutely-positioned boxes. Server-side localisation is the
right split: both the PDF and the markdown live there, the mapping is
deterministic and cacheable per immutable run, and the client stays a renderer.
PDF.js must be **vendored**, not loaded from a CDN — the verifier is
offline-first by contract.

## The alternative I would cost first

Everything here reconstructs information that `prepare-text` destroyed.
PyMuPDF knows exactly where each span sits when it builds the markdown; only
`pymupdf4llm.to_markdown` being a black box forces this guesswork afterwards.
Emitting a sidecar of markdown-line → (page, rects) at conversion time would
be **exact**, tables included, and would make all of the fuzzy matching above
unnecessary.

The cost is owning more of the conversion. The benefit is deleting a permanent
source of approximation. I would compare these properly before building the
fuzzy path, because the fuzzy path is complexity that never goes away.
