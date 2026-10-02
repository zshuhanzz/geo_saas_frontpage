"""geo_agent internal services layer.

Keeps framework-agnostic logic (reporting, rendering, task execution helpers)
out of the HTTP router files so they can be reused from pipelines, background
jobs, and future surfaces (PDF export, email rendering, etc.).
"""
