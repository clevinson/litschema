# `agriculture` template

A starter LinkML schema for extracting structured data from agricultural
research literature. Use this as a starting point — fork it, narrow it
to your sub-domain, or extend via `is_a` inheritance.

## What it models

One `AgricultureExtraction` per article, with:

- Bibliographic-adjacent: `article_id`, `confidence`, `reasoning`
- Method classification: `study_type` (field_trial / greenhouse / lab / modeling / review / meta_analysis)
- Subject: `crops` (free-form names)
- A list of **`experiments`** — one entry per distinct experimental run. A
  paper running the same trial at three sites has three experiments; a
  modeling-only paper has zero. Bundles together the things that hang
  together at the per-experiment level (inspired by ERW's
  `ExperimentalSetup` pattern):
  - `site` (`Region`) — where the experiment ran
  - `soil_source` (`Region`, optional) — where the soil came from when it
    differs from `site`. Set this for lab/greenhouse studies; leave null
    for field trials (the site IS the source)
  - `soil` (`Soil`) — texture class, sand/silt/clay percentages, plus
    optional taxonomy (USDA/WRB/FAO + class name)
  - `treatments` (list of `Treatment`) — each treatment carries:
    - `name`, `type`, `rate`
    - **its own `outcomes` list** (variable, unit, effect direction).
      Putting outcomes under each treatment captures the natural
      meta-analysis unit: a paper comparing cover-crop / no-till /
      combined treatments can record different effect directions per
      treatment on the same shared outcome variables (e.g. yield neutral
      under cover-crop alone, positive under no-till, positive under
      the combination).
- `sample_size`: total replicate count across the study, when reported

The root class is `AgricultureExtraction`, marked `tree_root: true`.

The template also ships a `domain_context.md` alongside the schema —
this is the prompt-side companion read by the `extract-article` skill.
Fork both together when you adapt the template.

## Try it yourself: four open-access papers

These four real papers exercise distinct corners of the schema. All are
CC-BY (Wittwer / Chahal / She — Scientific Reports) or CC-BY-NC-ND
(Qiu — Nature Communications); the PDFs are freely downloadable from
the publisher.

| `article_id`   | DOI                              | `study_type`    | What it exercises                                                                  |
|----------------|----------------------------------|-----------------|------------------------------------------------------------------------------------|
| `wittwer-2017` | `10.1038/srep41911`              | `field_trial`   | Multi-species cover-crop comparison in Switzerland; many treatments, shared outcomes |
| `chahal-2020`  | `10.1038/s41598-020-70224-6`     | `field_trial`   | Long-term cumulative cover-crop effects on SOC + profitability (Canada, temperate humid) |
| `she-2018`     | `10.1038/s41598-018-33040-7`     | `greenhouse`    | Biochar × saline-irrigation factorial on tomato — exercises `soil_source` ≠ `site` |
| `qiu-2024`     | `10.1038/s41467-024-54536-z`     | `meta_analysis` | Global cover-crop synthesis — exercises the "leave `experiments` empty" rule       |

Suggested order:

1. **`wittwer-2017`** — the cleanest field trial; good for sanity-checking
   the basic `Experiment` → `treatments[]` → `outcomes[]` shape.
2. **`she-2018`** — confirms the greenhouse path: soil collected from one
   place, experiment run elsewhere, populating `soil_source`.
3. **`qiu-2024`** — confirms the meta-analysis short-circuit: no
   `experiments`, just `study_type=meta_analysis` plus the high-level
   metadata.
4. **`chahal-2020`** — long-term cumulative time-series; useful for
   stress-testing how you encode treatments that change over years.

To run the demo end-to-end:

```bash
# 1. drop the four PDFs into your project's papers/ directory
# 2. converting (PDF → markdown) and extraction:
uv run litschema convert
uv run litschema extract       # invokes the extract-article skill,
                               # which reads domain_context.md + schema
uv run litschema validate
uv run litschema status
```

## Usage patterns

### A. Use as-is

```yaml
# litschema.yaml in your project
schema_dir: schema
extraction_schema_file: agriculture_extraction.yaml
```

Then drop a copy of `agriculture_extraction.yaml` into your project's
`schema/` directory.

### B. Extend via inheritance

```yaml
# my_organic.yaml
imports:
  - agriculture_extraction       # the template above

classes:
  OrganicAgricultureExtraction:
    is_a: AgricultureExtraction   # inherit all 9 base slots
    tree_root: true                # mark this as your root
    attributes:
      certification_body:
        description: e.g. USDA Organic, EU Organic, JAS.
      organic_practices:
        multivalued: true
        description: Practices used (cover cropping, crop rotation, etc.).
```

`AgricultureExtraction.tree_root` is **not** inherited — you must mark
your subclass `tree_root: true` explicitly. (LinkML treats tree_root as
a per-class assertion about that specific class's role as a document
root.)

## License

Apache-2.0. Free to fork and adapt.
