"""
Offline / scheduled jobs for GEO Analyzer (v1.2).

Each module under ``geo_analyzer.src.jobs`` is an independent Cloud Run Job
entry point — runnable as::

    python -m src.jobs.<name> --flag ...

They share DB access helpers from ``src.core.database`` but do NOT run as part
of the per-report analysis pipeline in ``main.py``.
"""
