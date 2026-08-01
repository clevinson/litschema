# Changelog

Notable changes to litschema, newest first.

## Before you upgrade

**litschema is early software. Extracted data may need regenerating
when you update it.**

Until version 1.0, an update can change the format of the files litschema
writes — the extraction JSON, the review file, the metadata manifest. When that
happens, litschema does not convert your old files. It expects you to
re-run the step that produced them, which is why every step is repeatable from
your PDFs.

What this means in practice:

- **Your PDFs and your schema are safe.** They are your inputs; litschema never
  rewrites them.
- **Extractions and prepared text can be regenerated** by re-running the
  pipeline. Doing so costs model time, not work.
- **Human review is the thing to protect.** Reviews are the one artifact you
  cannot regenerate. Keep your project in Git, and read the **Breaking changes**
  section of any release before you update a project you have reviewed.

Each release below says plainly whether it breaks a format. Once litschema
reaches 1.0, formats stop changing without a migration path.

______________________________________________________________________

## What goes in this file

Changes that affect someone *using* litschema: new capability, changed
behaviour, removed surface, fixed defect. Internal refactors, test-only work,
and anything implemented then reverted before a release do not appear.

Specs follow the same rule. A spec edit is listed only when it changes what the
product does or admits; correcting a spec to match code that never moved is
bookkeeping, not a release note. Where a spec described unbuilt behaviour, that
belongs under **Known limits** rather than **Removed** — nothing anyone relied
on went away.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-08-01

First tagged release. Not published to PyPI — install from a checkout (see the
README). There is no prior tag, so this entry describes what the release *is*
rather than what changed.

### Breaking changes

None — this is the first release.

### Added

**The article store**

- One directory per document under `data/papers/<article-id>/`: the source PDF,
  its prepared text, a bibliographic manifest, and one directory per extraction
  run. Plain JSON, readable and diffable without the tool ([#9](https://github.com/clevinson/litschema/pull/9))
- Offline, content-addressed intake: `assemble` derives a stable article id
  from each PDF and re-dropping the same file is a no-op ([`3776036`](https://github.com/clevinson/litschema/commit/3776036))

**Extraction runs**

- Immutable runs under `extraction-runs/<run-id>/`. `run.json` records the
  SHA-256 of every input — prepared text, domain context, and the conducting
  skill — with the schema hash and the model that produced it. Re-extracting
  creates a new run instead of overwriting ([`ab82e2d`](https://github.com/clevinson/litschema/commit/ab82e2d))
- `litschema runs list` and `runs activate` inspect published runs and choose
  the active one ([`0afef89`](https://github.com/clevinson/litschema/commit/0afef89))
- The conductor publishes the run, so the model recorded is the model that
  actually ran rather than one an agent reported about itself ([`ce047ed`](https://github.com/clevinson/litschema/commit/ce047ed))

**Schema and validation**

- One LinkML schema per project, validated closed-world — nothing the schema
  does not define gets in ([#9](https://github.com/clevinson/litschema/pull/9))
- The `tree_root` class must declare `article_id` as an identifier, so every
  consumer addresses a document the same way. Schemas may span multiple files;
  identity is the hash of the whole closure ([`6dc1290`](https://github.com/clevinson/litschema/commit/6dc1290), [`b7a6c5e`](https://github.com/clevinson/litschema/commit/b7a6c5e))
- `doctor` warns when a schema slot would silently store only identifiers and
  discard the rest of an object ([`ca20259`](https://github.com/clevinson/litschema/commit/ca20259))

**Reasoning and citations**

- Optional overall and per-field confidence in the reasoning file ([#14](https://github.com/clevinson/litschema/pull/14))
- `validate-reasoning` opens the prepared text and rejects citations naming
  lines outside the document, ranges that run backwards, and citations landing
  wholly on blank lines ([`d0145b6`](https://github.com/clevinson/litschema/commit/d0145b6))

**Review**

- Version 2 review model: one entry per field, stored inside the run it
  reviews, with verify / correct / remove and a run-explicit API ([`2369396`](https://github.com/clevinson/litschema/commit/2369396))
- `litschema verify` serves a loopback-only app with a dataset overview and a
  per-document review route ([`440e5c8`](https://github.com/clevinson/litschema/commit/440e5c8))
- The document view names the model and effort that produced what you are
  reviewing ([`f393868`](https://github.com/clevinson/litschema/commit/f393868))
- Optional ORCID attribution, and a project policy that can require a reviewer
  on every review ([`fa643b0`](https://github.com/clevinson/litschema/commit/fa643b0), [`b9f2b0e`](https://github.com/clevinson/litschema/commit/b9f2b0e))

**Bibliographic metadata**

- A `bib_metadata` block tagged `doi`, `auto`, or `manual`. Registry values
  lock the record; machines never overwrite a human edit without explicit
  consent ([#15](https://github.com/clevinson/litschema/pull/15))

**Output**

- `litschema export` writes review-applied extractions as JSONL or CSV
  ([`bf9d688`](https://github.com/clevinson/litschema/commit/bf9d688))
- `litschema mcp` derives a DuckDB database from the schema and serves it
  read-only over MCP. Experimental and frozen ([`1187b4e`](https://github.com/clevinson/litschema/commit/1187b4e))

**Getting started**

- `litschema init` scaffolds a project and installs the agent skills ([#9](https://github.com/clevinson/litschema/pull/9))
- `/litschema-onboard` drafts your schema from your own papers, runs intake,
  pilots one article, then batches the rest ([#17](https://github.com/clevinson/litschema/pull/17))
- `doctor` reports a schema it cannot resolve instead of passing silently
  ([`43f0c6f`](https://github.com/clevinson/litschema/commit/43f0c6f))
- `verify --no-browser` for scripted and headless use ([`a115eec`](https://github.com/clevinson/litschema/commit/a115eec))

### Security

- Dev-override approval is recorded in your own config, keyed by project path
  and content hash. An approval marker committed inside a repository grants
  nothing, so a hostile checkout cannot approve its own command ([`391376f`](https://github.com/clevinson/litschema/commit/391376f), [`77ce8c9`](https://github.com/clevinson/litschema/commit/77ce8c9))
- A `?filter=` expression arriving in a URL is displayed but never evaluated —
  including by the live preview — until you press Apply ([`fc61b79`](https://github.com/clevinson/litschema/commit/fc61b79), [`27c091e`](https://github.com/clevinson/litschema/commit/27c091e))
- Overrides are refused when the run's schema identity cannot be established,
  rather than typed against the wrong schema ([`2bdd0d9`](https://github.com/clevinson/litschema/commit/2bdd0d9))

### Known limits

- **Tables lose row-level provenance.** PDF conversion collapses some tables
  onto a single line, so a citation into a table names the table, not the row.
  Measured at ~10% of citations in a measurement-heavy corpus, ~2% in a
  prose-heavy one. The row structure is gone before extraction sees it.
- **Supplying omitted values is API-only.** The `add` override works through
  the annotation API; the verifier has no control for it, and added values do
  not yet render distinctly from extracted ones.
- **Multi-run selection is minimal.** `runs list` and `runs activate` ship;
  trash, restore, purge, and review reconciliation between runs do not.
- **One registry.** Bibliographic sync reads OpenAlex only. A DOI it does not
  hold fails rather than falling back.
- **No PyPI release.** Install from a checkout.
