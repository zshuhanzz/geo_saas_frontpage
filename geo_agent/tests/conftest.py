"""
pytest conftest — inserts ``geo_agent/src`` onto ``sys.path`` so the flat
``from database import ...`` / ``from graphs import ...`` imports used by
the agent modules resolve without installing the package.

NOTE: tests directory is currently a placeholder. P0 multi-tenant isolation tests
and SQL-injection safety tests will land here when the PG MCP migration (see
docs/roadmap.md §10 "🔴 geo_agent PG MCP 迁移 + P0 租户隔离测试") is executed.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))  # geo_agent/tests
SRC_ROOT = os.path.join(os.path.dirname(HERE), "src")  # geo_agent/src
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)
