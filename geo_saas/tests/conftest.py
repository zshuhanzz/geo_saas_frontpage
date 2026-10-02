"""
pytest conftest — inserts ``geo_saas/src`` onto ``sys.path`` so the flat
``from database import ...`` / ``from routers import ...`` imports used by
the router modules resolve without installing the package.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))  # geo_saas/tests
SRC_ROOT = os.path.join(os.path.dirname(HERE), "src")  # geo_saas/src
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)
