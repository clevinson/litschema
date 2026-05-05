"""ERW Research data ingestion pipeline.

Pipeline phases:
  01_openalex_harvest    - Fetch structured metadata from OpenAlex API
  02_crossref_harvest    - Supplement missing fields from CrossRef
  04_pdf_to_markdown     - Convert PDFs to markdown (pymupdf4llm)
  06_resolve_entities    - Deduplicate authors and institutions
  09_llm_extraction      - Extract non-bibliographic fields (via agent skill)
  10_assemble_corpus     - Legacy export of LinkML-valid corpus.yaml
"""
