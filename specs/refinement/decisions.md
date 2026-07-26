# Decisions: refinement

Append-only. Newer entries supersede older ones.

## 2026-07-14 — Separate refinement from onboarding and same-schema reruns

**Context:** first-run onboarding, a one-article rerun, and a schema-wide
upgrade have different safety and completion conditions. Treating extraction
files as mutable made those boundaries implicit and made review reuse unsafe.

**Decision:** `/litschema-onboard` remains first-run only.
`/litschema-refine` edits the one current schema or domain context, pilots a
subset, freezes an approved schema hash, reprocesses the full corpus into
inactive lineage children, reconciles reviews conservatively, activates only
after readiness, then trashes user-designated abandoned runs through protected
CLI commands. A same-schema rerun is a separate one-article workflow.

**Rejected:** folding refinement into onboarding; mutating existing extraction
files; activating pilot runs before corpus readiness; treating LLM-proposed
review mappings as accepted; storing schema-history copies beside runs.


## 2026-07-14 — A tracked ledger freezes scope and proves completion

**Context:** filesystem inspection alone could not distinguish pending,
excluded, rejected, activated, or completed refinement work after interruption.

**Decision:** each corpus refinement owns one atomic, tracked
`refinements/<refinement-id>.json` ledger. It classifies every baseline article
as eligible or explicitly excluded, freezes scope at approval, references
candidate runs, persists ambiguous mapping decisions, records activation and
abandoned-candidate cleanup, and sets completion atomically only after its
predicate passes. Later-added and excluded articles stay outside the coverage
denominator and appear in the completion report.

**Rejected:** storing authoritative state under `.litschema/`; inferring phase
or completion from run directories; silently excluding failures; completing
with untrashed abandoned candidates.
