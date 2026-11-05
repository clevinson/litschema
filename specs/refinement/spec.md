# Capability: refinement

Status: deferred — planned for 0.2.0, not started.

Refinement is the future workflow for changing an established project's
extraction contract — editing the schema or domain context, re-extracting the
corpus into fresh runs, carrying existing human reviews forward where that is
provably safe, and switching each article to its accepted new run.

Nothing here ships in this release. Re-extracting does preserve the prior run
and activate the new one, and `runs activate` selects between published runs.
What this release lacks is the rest of the lifecycle: inactive candidates and
carrying reviews across runs. The immutable run layout and hash-based schema
identity in `specs/article-store` and `specs/project-config` exist so this
capability can arrive later without a format change. Its contract — a durable
workflow ledger, the `/litschema-refine` skill, review reconciliation rules —
is not written yet; the design reasoning so far is in `decisions.md`.
