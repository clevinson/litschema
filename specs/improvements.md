# Improvements backlog — 2026-07-07 audit

Point-in-time backlog from the full-surface audit that backfilled the
capability specs. NOT current-truth documentation: each item is a suggested
change, ordered by priority within its group. Delete entries as they land
(this file is the one exception to the append-only rule — it is a to-do
list, not a record). Alpha policy applies throughout: no compatibility
shims, no migrations — deletions land clean.

## 1. Correctness

- **`prepare-text` writes manifests with a raw `write_text`**
  (`ingest/pdf_to_markdown.py:128`), bypassing `write_article_metadata` —
  violates the atomic-manifest invariant and makes prepare-text an
  undocumented identity writer with its own duplicate slugifier whose empty
  fallback is WEAKER than assemble's (raw stem instead of `"article"`).
  Route through the one writer and the one slugifier, or drop the
  side-effect (assemble is the intake step).
- **Two manifest readers with contradictory corrupt-file semantics**:
  `ArticleFiles.read_metadata` silently returns `{}` on unparseable JSON —
  so a torn manifest is silently REBUILT on the next write, losing the
  `manual` protection tag — while `read_article_metadata` raises. Converge
  on raising loudly (the reviews capability already models this: lenient
  reads, refusing writes).
- **Explore rebuild ignores schema edits**: `_needs_rebuild` watches the
  article store but not `schema_dir`, so column shapes go silently stale
  after schema changes (`--rebuild` is the workaround). DEFERRED under the
  explore freeze (`specs/explore/decisions.md`).
- **`litschema validate a.json b.json` silently ignores `b.json`** — only
  `args[0]` is consumed. Accept multiple targets or reject extras.
- **`/api/pdf` joins the manifest `filename` unsanitized** — a hand-edited
  `"filename": "../../x.pdf"` escapes the article dir, bypassing the id
  guard's rationale. Validate at the endpoint.
- **`prepare-text` exits 0 even when every article failed** (`missing`/
  `errors` counts nonzero) — agents get no signal; the skill compensates by
  re-checking file sizes. Exit nonzero, at least for the single-article
  form.
- **Assemble's interrupt heuristic string-matches `"KeyboardInterrupt"`**
  in exception text (`article_assembly.py:51`) — a legit error containing
  the word is misclassified as a cancellation. Walk the `__cause__` chain
  instead.
- **Re-running `agent record-extraction` wholesale-replaces the
  `extraction` dict** (shallow manifest merge) — re-recording without
  `--provider` silently drops the previously recorded provider. Merge
  per-key or document as intended.

## 2. Delete (dead / superseded / broken surface)

- **Dead config keys**: `references_dir`, `tracking_xlsx` (paper-tracking
  spreadsheet residue), `static_site_dir` — zero consumers — and `data_dir`,
  which nothing reads since the explore-registry cut (it survives as a
  layout convention only). Delete the dataclass fields, shrink every test
  `_cfg()` helper, and drop `openpyxl` from runtime deps (nothing reads
  xlsx).
- **`schema_root` config key** — written by `init`, present in all
  fixtures, read by NOTHING. Drop from init output and fixtures. While
  there: promote `extraction_schema_file` from `cfg.raw` to a real field
  (it is the only live key without one).
- **`src/litschema/analysis/`** — wholly ERW-specific DataFrame flattening,
  unreachable from the CLI, hardcodes domain fields, and imports pandas
  (dev-only dep), so it crashes on import for pip installs. Delete; the
  schema-agnostic explore layer supersedes it.
- **`extract` stub command** — permanently exits 2 pointing at the skills.
  Demote to help text or make it print the skill instructions and exit 0.
- **`EXPERIMENTAL_SKILLS = {"litschema-builder"}`** — no such skill exists;
  `skills install --experimental` does nothing. Delete.
- **Legacy compat shim in `prepare_schema_context`** — unlinks a retired
  `schema_context.json` artifact on every run. Remove after a sweep.
- **Frontend dead nodes**: the static-deploy PDF-button branch (also buggy
  on 127.0.0.1), `#stat-articles` (never written), `#stat-citations`
  (write-only, hidden), the `n_annotated` alias of `n_reviewed`, and the
  `standard_filename` manifest fallback in `/api/pdf`.
- **Module-directory config-discovery fallback** (`config.py:95`) — walks
  site-packages parents in installed layouts; can silently bind the wrong
  project. Keep explicit / env / cwd-walk only.

## 3. Rename (names that no longer match concepts)

- **ERW residue in generic surfaces**: package docstring ("ERW Research
  Article Schema"), FastAPI `title="ERW Extraction Verifier"`,
  `erw-theme` / `erw-reviewer-profile` / `erw-reviewer-id` localStorage
  keys, filter-help text citing "~25 grey-lit papers" and ERW schema fields
  (`experimental_setups`, `feedstock`, ...) as examples, `n_setups` +
  `study_types`/`focus_areas`/`document_type` hardcoded passthroughs in
  `/api/articles`, `erw_articles.yaml` fixture naming. Rename to
  `litschema-*`; derive filter examples from `/api/schema/fields`; make the
  queue passthrough fields schema-driven or drop them.
- **`status` label drift**: prints "annotations" (spec: reviews),
  "converted" (spec: prepared text), "domain dir" (spec: project root).
  Also `init`'s argument is named `domain` and the config hint says
  "init <domain-name>". One vocabulary: project, reviews, prepared.
- **`ArticleFiles.reviews` (plural) → `review.json` (singular)** — rename
  the property `review`.
- **Annotation wire shape**: the API speaks `status`/`reviewer`/
  `correct_value`, storage speaks `signal`/`author`/`override_value`, and a
  translation layer bridges them for one consumer (our own frontend). Alpha
  policy: converge the wire on the spec names and delete the mapping.
- **Two path dialects for the same leaf paths**: reasoning uses jq-style
  with a leading dot (`.experiments[0].ph`); reviews are canonical without
  (`experiments[0].ph`). Unify on the canonical form (reasoning writers are
  our own skills).
- **`webapp/search.py` contains no search** — it is `strip_references`.
  Rename or fold into the app module.
- **`mcp` verb hides the explore capability behind a transport name** —
  consider `litschema explore [--serve ...]` or at least a `build-store`
  alias, so the store can be rebuilt without starting a server.
- **Error-marker shape**: skill mandates `{"error": true, "reason": ...}`
  but consumers accept any truthy `error` (one test uses a string). Pick
  the boolean+reason shape and validate it.

## 4. Harden / decide

- **The queue filter is URL-borne JavaScript** (`?filter=` compiles via
  `new Function` and runs on page load, in an origin with write APIs). The
  verifier spec now names the trust boundary; consider requiring a
  confirmation click before executing URL-sourced expressions, or an
  interpreted expression grammar.
- **ORCID lookup blocks the event loop** — sync `urlopen` (8s timeout)
  inside an async handler. Thread-offload it; consider a small cache.
- **CDN dependencies in a local-first app** — marked, Shoelace, Google
  Fonts load from CDNs; offline use breaks markdown rendering. Vendor the
  assets.
- **Explore store carries no override provenance** — reviewed and raw
  values are indistinguishable in SQL, and cache-hit summaries print
  "0 overrides applied" indistinguishably from truly zero. DEFERRED under
  the explore freeze (`specs/explore/decisions.md`).
- **`Project.article_dir` bypasses the id guard** — second unguarded
  path-join; delegate to `article_files` or delete the wrapper class.
- **`agent record-extraction` accepts a bare directory** as a known
  article while `meta` verbs require a manifest — use one `_require_article`
  everywhere.
- **`reload=True` clears the whole config cache**, not one entry; and
  `LITSCHEMA_CONFIG` is implemented twice (typer envvar + config.py). Minor
  consolidations.
- **Namespace the schemas deliberately** — `https://example.org/...`
  placeholder ids in the bundled reasoning schema and init's draft schema.

## 5. Test gaps (invariants without pins)

- `strip_references` (zero unit tests) and the `/api/markdown`, `/api/pdf`,
  `/api/article`, `/api/reasoning` happy paths.
- `explore/server.py` entirely (tool registration, TSV truncation,
  read-only rejection, error-string contract) and the loader's mtime
  cache-hit path. DEFERRED under the explore freeze.
- `validate`'s error-marker skip (core skill contract, untested);
  reasoning-confidence bounds rejection (1.5 → invalid).
- `prepare-text`'s `empty`/`errors`/`missing` paths, inbox-scan fallback,
  and manifest side-effect.
- Assemble: idempotent re-drop of an already hash-suffixed article; the
  `.processed` archival OSError path.
- Wheel entry points and console-script importability.

## 6. Product-shaped (from earlier sessions, still open)

- **Schema library**: `init --schema <ref>` importing/extending published
  LinkML base extraction classes (`specs/onboarding/spec.md` § Future
  work). The unreachable `templates/agriculture/` demo should either wire
  into this (`init --template agriculture`) or move to docs/examples.
- **`--email` (polite pool) is not forwarded by `meta set --sync`** —
  deliberate DOI-only surface; revisit if registry rate limits bite.
