"""Root conftest for backend tests.

Adds the backend source root to ``sys.path`` so tests can import
``service.*`` directly, matching how the backend runs in production
(``python main.py`` with cwd = ``backend/``).
"""

from __future__ import annotations

import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
