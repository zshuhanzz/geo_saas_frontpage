"""Ensure ``geo_analyzer/src`` is importable when running pytest from the
``geo_analyzer`` directory without installing the package."""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
