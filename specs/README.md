# specs/

Capability specifications for litschema. Loosely inspired by
[OpenSpec](https://github.com/Fission-AI/OpenSpec) and
[spec-kit](https://github.com/github/spec-kit), adopted deliberately small.

## What lives here

```
specs/
  <capability>/
    spec.md        # CURRENT TRUTH: architecture, user surface, invariants
    decisions.md   # append-only, dated decision log (ADR-lite)
```

- **`spec.md` describes what IS built, not what might be.** It is the canonical
  reference for a shipped capability: its data model, every user-facing surface
  (CLI verbs, HTTP endpoints, UI affordances, pipeline writers), and the
  invariants the implementation upholds. Behavioral requirements use WHEN/THEN
  phrasing where precision matters.
- **`spec.md` is updated in the same commit/PR as any behavior change.** A PR
  that changes a capability's surface or invariants without updating its spec
  is incomplete. The test suite is the executable form of the invariants; the
  spec is the legible form.
- **`decisions.md` records why.** Each entry is dated and states the context,
  the decision, the rationale, and the alternatives rejected. Entries are never
  rewritten — a reversed decision gets a new entry that supersedes the old one.

## Process for new features

Start a new capability folder with a draft `spec.md` — the proposal IS the
first version of the truth, refined during review, and merged when the
implementation lands. There is no separate change-proposal tree yet; one will
be added if parallel in-flight features ever make drafts-vs-truth ambiguous.

## For agents

Read the capability's `spec.md` (and skim `decisions.md`) before modifying any
part of its surface. If your change alters behavior described in the spec,
update the spec in the same change.
