# specs/

Capability specifications for litschema. Loosely inspired by
[OpenSpec](https://github.com/Fission-AI/OpenSpec) and
[spec-kit](https://github.com/github/spec-kit), adopted deliberately small.

## What lives here

```
specs/
  <capability>/
    spec.md        # normative contract, with explicit status
    decisions.md   # append-only, dated decision log (ADR-lite)
```

- **`spec.md` is the normative contract.** A status line says `current`,
  `partially current`, `approved target`, or `draft`. `current` describes
  shipped behavior. `partially current` means some of the contract ships today
  and some does not; the spec must then carry an **Implementation status**
  section naming the boundary and the issue tracking the rest — a reader must
  never have to guess which half they are reading. `approved target` records an
  accepted behavior change before implementation; its implementation and tests
  may lag, but competing current prose must be removed. `draft` is not
  approved. Behavioral requirements use WHEN/THEN phrasing where precision
  matters.
- **Specs record test obligations.** An approved target must name the behavior
  that implementation tests will pin. A behavior PR is incomplete until those
  tests pass and the status becomes `current`.
- **`decisions.md` records why.** Each entry is dated and states the context,
  the decision, the rationale, and the alternatives rejected. Entries are never
  rewritten — a reversed decision gets a new entry that supersedes the old one.

## Normative ownership

- `article-store`: article identity, run layout, active selection, trash, and
  run CLI safety;
- `project-config`: the current schema, schema identity, discovery, and shared
  CLI rules;
- `extraction`: extraction/reasoning contents, validation, and publication
  inputs;
- `reviews`: stored and effective review state, hierarchy, and reconciliation;
- `onboarding`: first-run flow;
- `refinement`: its durable workflow ledger, same-schema reruns, schema
  upgrades, and `/litschema-refine`;
- `explore`: export views, audit sidecars, DuckDB, and MCP;
- `verifier`: web routes, read surfaces, and frontend constraints;
- `source-metadata`: bibliographic data and provenance.

Other specs cross-link these rules instead of redefining them.

## Alpha status: no backwards compatibility

litschema is pre-release alpha software. Until a release with a version
number has been published:

- Specs describe either current behavior or one explicitly approved target.
  They do not document legacy fallbacks or runtime compatibility shims.
- Backwards compatibility and legacy-format migration inside the framework are
  non-goals. Format changes land clean. Conservative review reconciliation
  between first-class runs is current product behavior, not legacy support.
- Existing corpus data is updated in its own (domain) repo when a format
  changes — typically agent-driven, using the framework's own CLI as the
  write surface.

This section is superseded the day a versioned release ships.

## Process for new features

Start a capability folder with a draft `spec.md`. After human approval, mark it
`approved target`; implementation follows in a later change. Mark it `current`
only after its test obligations pass. There is no separate proposal tree.

When implementation lands in stages, move the status to `partially current`
and keep its Implementation status section accurate in the same change that
ships the code. The status line and that section are the primary signal of
what actually works — they are maintained as the code moves, not at release
boundaries.

## For agents

Read the capability's `spec.md` (and skim `decisions.md`) before modifying any
part of its surface. If your change alters behavior described in the spec,
update the spec in the same change.

Repo-wide conventions that aren't capability behavior — build/test commands,
project layout, git and PR conventions, issue tracking — live in `AGENTS.md`
at the repo root, not here.
