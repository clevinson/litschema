# Domain: Agricultural research

Agricultural research is a broad, heterogeneous field. Papers span
field trials, greenhouse pot studies, lab incubations, modeling work,
and synthesis papers (reviews + meta-analyses). The same paper may
combine more than one methodology. The fields populated in the
extraction will differ accordingly — see the rules below.

## Extraction Rules

- **One `Experiment` per distinct site / soil / treatment-set context** —
  NOT per treatment. A paper comparing three cover-crop treatments at
  one Iowa site is ONE experiment with three treatments. A paper running
  the same trial at three sites is THREE experiments.
- **Outcomes nest under `Treatment`, not under `Experiment`.** Each
  `{treatment, outcome variable}` pair carries its own
  `effect_direction`. This captures the natural meta-analysis unit: same
  variable measured under several treatments, with potentially different
  directions of effect.
- **For reviews and meta-analyses: leave `experiments` empty.** Do not
  re-extract the underlying studies' data. Extract only what the review
  itself contributes (`study_type=review` or `meta_analysis`,
  `crops`, `confidence`, `reasoning`).
- **For pure modeling papers (no empirical data of their own): leave
  `experiments` empty.** Set `study_type=modeling`. If a paper combines
  modeling AND original empirical work, populate `experiments` for the
  empirical portion and pick the dominant `study_type`.
- **`soil_source` vs `site`** — only populate `soil_source` when soil
  was collected from a different location than where the experiment ran
  (typical for greenhouse / lab studies). For field trials, leave
  `soil_source` null — the site IS the source.
- **IGNORE the References / Bibliography section.** Extract only from
  the paper's own narrative, methods, results, and tables.
- **Preserve exact numbers** — do NOT round, average, or estimate. If
  the paper reports a range, capture the range; if it reports a mean,
  capture the mean.
- **Omit unknown fields** rather than guessing. Empty / null is
  meaningful — it tells the reviewer "the paper didn't report this."

## Field Guidance

- **`study_type`** — single-valued enum. Pick the dominant methodology.
  Use `field_trial` for replicated outdoor trials; `greenhouse` /
  `lab` / `modeling` / `review` / `meta_analysis` as appropriate. If a
  paper is a mix, pick the one that best describes the *primary*
  contribution.
- **`crops`** — free-form common names (e.g. `corn`, `soybean`,
  `tomato`). Prefer common names over scientific names. Multivalued.
- **`experiments[].site`** — country is required where reported;
  `admin_boundary` is the state / province / region. Coordinates only
  when explicitly given.
- **`experiments[].soil`** — populate `texture_class` whenever the paper
  names a USDA texture class. Always populate `sand_pct` / `silt_pct` /
  `clay_pct` when reported (they refine the class). `taxonomy_system`
  is `USDA` / `WRB` / `FAO` — pick whichever the paper uses;
  `taxonomy_class` is the order / suborder / great group as written
  (`Mollisol`, `Calcisol`, `Acrisol`, etc.).
- **`experiments[].treatments[].type`** — enum. `cover_crop` for
  cover-cropping interventions; `tillage` for tillage manipulations
  (no-till, reduced-till, conventional); `amendment` for biochar,
  compost, lime, and other soil amendments; `fertilizer` for synthetic
  N/P/K; `irrigation` for water-management treatments; `other` for
  combined / hybrid / unusual treatments.
- **`experiments[].treatments[].rate`** — free-form, preserve units as
  reported (e.g. `5 t/ha`, `120 kg N/ha`, `10 mm/week`).
- **`experiments[].treatments[].outcomes[].effect_direction`** — enum.
  `positive` / `negative` / `neutral` / `mixed` relative to the
  experiment's control. Use `mixed` when an outcome was significant in
  one direction at one timepoint or stratum and the opposite in
  another; otherwise pick the direction the paper reports as the
  headline result.
- **`sample_size`** — total replicate count (plot count for field
  trials, pot count for greenhouse). Leave null when the paper
  reports replicates per treatment but not a total.
- **`confidence`** — your overall extraction certainty (0.0–1.0).
  Lower it when the paper is ambiguous, when key fields had to be
  inferred from figures, or when terminology is non-standard.
- **`reasoning`** — 1–3 sentences for the human reviewer summarizing
  the most consequential extraction choices (especially `study_type`,
  whether `experiments` was populated, and any unusual treatment
  encoding).
