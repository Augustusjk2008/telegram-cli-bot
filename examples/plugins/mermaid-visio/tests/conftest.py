from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_BACKEND = PLUGIN_ROOT / "backend"

for path in (REPO_ROOT, PLUGIN_BACKEND):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)
