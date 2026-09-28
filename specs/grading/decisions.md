# Decisions: grading

Append-only. Newer entries supersede older ones.

## 2026-09-28 — A separate grader, run through the user's claude CLI

**Context:** the extractor's field confidence is self-reported in the same pass
and was sparse in the pilot (69 of 650 fields). The model pilot
(`spikes/2026-09-28-model-pilot` in erw-research) found no fabricated values;
the useful signal was inferences the extractor presented as stated.

**Decision:** `litschema grade` sends each run's values and cited evidence to a
separate `claude -p` call with a strict rubric and stores per-field verdicts
beside the run. Cited lines are shown whole, because a converted line is often
a paragraph. Grades are keyed by input hashes so a re-prepared article makes
old grades stale instead of wrong.

**Rationale:** keeping the grader apart from what it grades gives separate
errors and no self-preference, and gives a component that can be calibrated
against human review later. Using the user's Claude Code login means no API key
handling in litschema.

**Rejected:** asking the extractor for more confidence values (same pass, same
blind spots); a lenient rubric (the pilot's grader called inferences
"supported" without the partial rule); overwriting a single grade file
(grades, like runs, stay as a history).

## 2026-09-28 — Can't-verify fields sort with the flagged ones

**Context:** the review order puts unsupported, then partial, then the
extractor's low-confidence fields first. A can't-verify verdict usually means
the deciding evidence is a figure the grader couldn't read.

**Decision:** in the verifier's flagged-first order, can't-verify fields come
after partial and before low extractor confidence. They are not counted in
Flags.

**Rationale:** those are the fields only a human looking at the figure can
check. Counting them as flags would inflate the overview for documents that
lean on figures.

## 2026-09-28 — One number per field: probability the value is right

**Context:** version-1 grades stored a verdict plus the grader's confidence in
that verdict, and the extractor stored its own confidence and free-text
reasoning. A reviewer saw two confidences that meant different things, and the
extractor's reasoning often restated the evidence.

**Decision:** the grader returns `confidence` as the probability that the value
is correct as stated and supported by its cited lines, with `null` for fields
it cannot judge, and a one-line `issue` below 0.9. Bands (high, check, low,
can't verify) are derived from fixed thresholds, not stored. The extractor
records a `basis` enum and a one-line `note` on how it derived any value it
did not read directly; it no longer rates its own confidence. Flags now count
can't-verify fields, superseding the entry above: with no verdict, a null
confidence is a field nobody has checked.

**Rejected:** keeping a verdict beside the confidence (two signals that can
disagree); storing the band per field (thresholds would be frozen into old
files and could drift from the app).
