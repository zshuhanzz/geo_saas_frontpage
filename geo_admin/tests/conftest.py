"""
pytest conftest — inserts ``geo_admin/src`` onto ``sys.path`` so the flat
``from database import ...`` / ``from routers import ...`` imports used by
the admin modules resolve without installing the package.

NOTE: tests directory is currently a placeholder. Unit tests for admin
routers / services will land here in future iterations.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))  # geo_admin/tests
SRC_ROOT = os.path.join(os.path.dirname(HERE), "src")  # geo_admin/src
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)
