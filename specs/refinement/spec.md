# Capability: refinement

Status: approved target.

## Implementation status

None of this spec ships. There is no `refinements/` ledger, no
`/litschema-refine` skill, and no same-schema rerun or schema-upgrade workflow.
It is the last capability in the immutable-runs line of work and has no tracked
issue yet — deliberately, since it is out of scope for v0.1.0 and its shape may
change once `tdv3` and `2gd1` are built. Consumers that reference a ledger
(verifier metrics, review-transfer proposals) are specified to degrade to null
or omission while it does not exist.

Refinement changes an established project's extraction contract without
rewriting history. The project-local `/litschema-refine` skill pilots schema or
domain-context changes, reprocesses the frozen eligible corpus into immutable
runs, reconciles reviews, activates accepted runs, and trashes abandoned
candidates.

## Workflow boundaries

| workflow | schema identity | activation |
|---|---|---|
| first-run onboarding | first current schema | successful first runs activate |
| same-schema rerun | unchanged `schema_hash` | explicit after inspection |
| schema upgrade | changed `schema_hash` | refinement activation phase |

Runs do not label themselves with a workflow kind. Comparing a candidate run's
`schema_hash` against its source's yields the distinction whenever it is
needed, and the ledger below records which workflow produced a candidate.

A domain-context-only corpus refinement counts as a same-schema rerun because
schema identity is hash-based. A one-article same-schema rerun does not invoke
the corpus refinement lifecycle.

## Authoritative refinement ledger

Refinement state lives at
`<project_root>/refinements/<refinement-id>.json`. The refinement capability
owns this file. It is durable project data, not `.litschema/` runtime/cache
state, and is intended for Git tracking.

The conductor creates the ledger before the pilot and atomically replaces it
after each state transition. Keys are sorted. Run IDs, review files, and schema
contents remain in their existing authorities; the ledger stores references and
workflow decisions only. At most one ledger may have a nonterminal phase.

Minimal shape:

```json
{
  "version": 1,
  "refinement_id": "01J2R8M4Y6N1P3Q5S7T9V2W4XZ",
  "phase": "reconcile",
  "created_at": "2026-07-14T22:00:00Z",
  "updated_at": "2026-07-14T22:40:00Z",
  "baseline_schema_hash": "sha256:…",
  "target_schema_hash": "sha256:…",
  "scope": {
    "eligible": {
      "article-a": {
        "source_run_id": "source-run",
        "candidate_run_id": "candidate-run",
        "source_schema": "resolved",
        "source_review": "valid",
        "reconciliation": {
          "status": "ready",
          "entries": {
            "experiments[0].ph": {
              "outcomes": [{"target_path": "experiments[0].ph", "disposition": "automatic"}]
            }
          }
        },
        "activation": "pending"
      }
    },
    "excluded": {
      "article-b": {"reason": "prepared text is unavailable"}
    }
  },
  "proposals": {},
  "abandoned_candidates": {},
  "completed_at": null
}
```

`phase` is `baseline`, `editing`, `pilot`, `reprocess`, `reconcile`,
`ready`, `activate`, `cleanup`, `abort_cleanup`, `complete`, or `aborted`.
`complete` and `aborted` are terminal only after their cleanup predicates pass.

Each eligible entry records the baseline source run or null, accepted candidate
or null, source-schema resolution (`not_applicable`, `pending`, `resolved`, or
`unavailable`), source-review state (`none`, `valid`, `corrupt`, or
`removed_with_ack`), reconciliation, and activation (`pending` or `active`).

Reconciliation is `not_applicable`, `pending`, or `ready`. For a source review,
`entries` records every source review decision and its target outcomes. Each
outcome has exactly one disposition: `automatic`, `confirmed`, `rejected`,
`omitted`, or `blocked`. `confirmed` references a confirmed proposal;
`rejected` references a rejected proposal; `omitted` carries a reason and
explicit acknowledgement. Article status is `ready` only when no outcome is
`blocked`, every outcome has a terminal disposition, and no related proposal is
pending. Mixed automatic, confirmed, rejected, and omitted outcomes are thus
representable without collapsing their audit trail.

## Article scope

Baseline discovery starts from every immediate article directory under the
configured article store, before reading manifests. Each discovered directory
must contain a valid `article-metadata.json` whose ID matches the directory;
missing, corrupt, or mismatched manifests block baseline creation. The baseline
universe is the validated result. Every baseline ID must then appear exactly
once under `eligible` or `excluded`.

An article is eligible by default when it has usable prepared text. An active
run is not required: an article without one receives a first candidate and has
no review source. An article with an active run receives a candidate whose
workflow follows from comparing its `schema_hash` to the source's.

Exclusion requires an explicit user decision and a durable reason before scope
freeze. Missing or empty prepared text and a documented project-scope rule are
valid reasons. A failed candidate extraction is not an exclusion; it blocks
readiness. A broken active pointer blocks baseline creation and cannot become an
exclusion.

For an eligible article with a source run, the ledger records source-review
state before reconciliation. A corrupt source review blocks reconciliation and
readiness. It must be repaired to `valid`, or the user must record an explicit
decision to discard the corrupt file before manual removal changes the state to
`removed_with_ack`. It never becomes empty, `ready`, or `not_applicable` by
inference.

Scope freezes at contract approval. Articles assembled afterward are outside
this refinement, do not block it, and appear in completion output as
`added_after_baseline`. Excluded articles do not require a candidate or active
target-schema run. Their prior state remains unchanged and completion reports
them by ID and reason. Changing eligibility or an exclusion after scope freeze
requires aborting this ledger and starting a new refinement.

## `/litschema-refine` lifecycle

1. **Baseline:** create the ledger, classify every baseline article, and stop on
   an integrity error.
2. **Edit:** change only the current schema and/or `domain_context.md`. Git
   retains earlier versions.
3. **Validate:** resolve one local tree root and prepare runtime schema context.
4. **Pilot:** run a user-selected eligible subset. Each iteration creates
   inactive candidates and records rejected candidates as abandoned.
5. **Approve contract:** record the user's approval and a clean Git checkpoint
   containing the schema and domain context. Freeze scope and the target schema
   hash.
6. **Reprocess:** create one inactive candidate for each eligible article.
   Existing active selections remain unchanged.
7. **Reconcile:** apply `specs/reviews/spec.md` to each source/candidate pair.
   Persist ambiguous proposals and user decisions in the ledger.
8. **Readiness:** require a valid target-hash candidate for every eligible
   article, source-schema resolution recorded, source review noncorrupt,
   reconciliation `ready` or `not_applicable`, no blocked disposition or pending
   proposal, unchanged frozen inputs, and no activation yet.
9. **Activate:** switch each eligible article to its accepted candidate. Record
   each successful pointer change. Mixed state is resumable but incomplete.
10. **Clean up:** mark every nonaccepted candidate created by this refinement as
    abandoned and trash it through `litschema runs`. Reviewed and corrupt-review
    candidates retain lifecycle confirmation requirements.
11. **Complete:** verify the completion predicate below, set `completed_at`,
    and atomically change the phase to `complete`.

## Proposals and confirmation

An ambiguous reconciliation proposal is authoritative workflow state but not
review state. The ledger stores a stable proposal ID, article/source/target run
IDs, source and target paths, the complete proposed mapping, and
`decision: pending|confirmed|rejected`. Confirmation or rejection is written
atomically before review entries change. The related reconciliation outcome
references that proposal as `confirmed` or `rejected`. Uncertainty for which no
proposal is generated records an `omitted` outcome with reason and explicit
acknowledgement. Reruns reuse a decision only when both run IDs and the mapping
are unchanged. No pending proposal, blocked outcome, or unacknowledged omission
may pass readiness or completion.

## Completion predicate

A refinement is complete only when all conditions hold:

- every baseline article is classified as eligible or excluded with a reason;
- every eligible article's active pointer equals its recorded valid candidate,
  and that run has the frozen target schema hash;
- every eligible source review is `none`, `valid`, or `removed_with_ack`;
- every eligible reconciliation is `ready` or `not_applicable`, every outcome
  has a terminal disposition, and every omission is acknowledged;
- no proposal is pending and no outcome is blocked;
- every nonaccepted candidate created by this refinement is listed as abandoned
  and has status `trashed`;
- the current schema bytes still hash to the frozen target;
- `completed_at` is written in the same atomic update that sets `phase:
  complete`.

Prior source runs are history, not abandoned candidates, unless the user
separately marks them for lifecycle cleanup. A candidate cannot be both retained
and abandoned. If the user declines the required confirmation to trash an
abandoned reviewed or corrupt-review candidate, the refinement remains in
`cleanup`.

Completion is scoped: output reports `eligible_active/eligible_total`,
`excluded_total` with reasons, and `added_after_baseline`. It must not claim
that excluded or later-added articles use the target schema.

## Failure and resume

Resume reads the sole nonterminal ledger and validates its referenced runs,
active pointers, frozen schema hash, source-review state, reconciliation
outcomes, proposal decisions, and abandoned candidate state. It continues from
the first incomplete recorded transition. The workflow never infers completion
from files alone.

A failure before activation leaves prior active selections intact. A failure
during activation records successful switches and resumes the remainder.
Reconciliation against the same source, target, and persisted decisions is
idempotent. A failed extraction stays inactive and blocks readiness.

An abort request, including a frozen schema or domain-context change, moves the
ledger to nonterminal `abort_cleanup`. Every candidate created by the refinement
is classified as abandoned and must reach `trashed` under normal lifecycle
protections. Only then may one atomic update record `abort_reason`,
`aborted_at`, and terminal `phase: aborted`. If reviewed/corrupt confirmation is
declined, the ledger stays resumable in `abort_cleanup` and a new refinement
cannot start.

## Same-schema rerun

A one-article same-schema rerun names one source run, publishes one inactive
child with the same schema hash, and leaves activation explicit. Reconciliation
is optional but follows the reviews contract when requested. This workflow does
not create a corpus refinement ledger.

## Invariants

- The current schema file is edited in place; Git is its history.
- The ledger is the sole authoritative refinement state and never duplicates
  run or review payloads.
- Scope is exhaustive at baseline and immutable after approval.
- Pilot and full-corpus candidates remain inactive until their gates pass.
- Proposal confirmation is durable and run-specific.
- Activation follows readiness; cleanup follows activation.
- Completion is an atomic, reproducible predicate over the ledger and referenced
  files.
- Interruption never mutates extraction payloads or guesses state.

## Test obligations

Implementation coverage must pin:

- ledger creation, atomic sorted writes, phase transitions, terminal records,
  and refusal of concurrent nonterminal ledgers;
- directory-first baseline discovery; missing/corrupt/mismatched manifest and
  broken-pointer blocking; exhaustive classification; valid exclusions;
  no-active-run eligibility; and later-added article reporting;
- scope freeze and restart requirement for scope or frozen-input changes;
- pilot rejection, immutable candidates, full eligible-corpus processing, and
  failed-candidate readiness blocking;
- valid/corrupt/removed source-review state, recorded discard before manual
  removal, and corrupt readiness blocking;
- per-entry automatic/confirmed/rejected/omitted/blocked dispositions,
  acknowledged nonproposal omissions, persistent proposals, decision reuse, and
  readiness gates;
- source-schema resolution status and mixed reconciliation outcomes;
- activation only after readiness, recorded partial activation, and resume;
- exact abandoned-candidate classification, reviewed/corrupt confirmation,
  normal and abort cleanup, declined-confirmation blocking, and terminal abort;
- the full completion predicate and scoped completion report;
- schema-changing, domain-context-only, and one-article same-schema flows.
