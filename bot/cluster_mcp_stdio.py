from importlib import import_module
from pathlib import Path
import sys

if __name__ == "__main__":
    _REPO_ROOT = Path(__file__).resolve().parents[1]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    raise SystemExit(import_module("bot.cluster.mcp_stdio").main())

sys.modules[__name__] = import_module("bot.cluster.mcp_stdio")
