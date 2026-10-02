"""
Analyzer pipeline phases (Phase 2.5b split from main.py).

The Cloud Run Job entrypoint (``geo_analyzer/main.py``) orchestrates these
six phases in order. Each module is independently testable / readable and
imports only the helpers it needs.

    Phase 0 — Load client config (brands / peers / products / domains / urls).
    Phase 1 — Per-result in-memory parse: brand / product / citation extraction.
    Phase 2a — Batch-classify the unique source domains seen in this batch.
    Phase 2b — Batch-extract sentiment + raw themes for long enough responses.
    Phase 3  — Persist brand_mentions / product_mentions / citations rows
               and mark the geo_results rows as analyzed.
    Phase B  — Once per run: normalize sentiment themes against the
               persistent dictionary.
"""
