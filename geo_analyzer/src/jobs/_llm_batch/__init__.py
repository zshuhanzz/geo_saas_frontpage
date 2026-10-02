"""
Internal helpers for the ``llm_batch_discovery`` job.

Split out from a 500-line monolith into:
    loaders.py    — DB readers (clients / config / samples).
    prompt.py     — Bilingual extraction prompt builder.
    gemini_call.py — google-genai async invocation + tolerant JSON parse.
    upsert.py     — UPSERT into geo_settings_candidates.

The job's CLI entrypoint stays at ``src/jobs/llm_batch_discovery.py`` so
existing ``python -m src.jobs.llm_batch_discovery`` invocations keep working.
"""
