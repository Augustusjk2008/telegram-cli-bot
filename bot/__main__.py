"""模块入口 (python -m bot)"""

import os
import sys

from bot.bootstrap import ensure_nofile_limit

# 确保 refactoring/ 在 sys.path 中
_this_dir = os.path.dirname(os.path.abspath(__file__))
_package_root = os.path.dirname(_this_dir)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

ensure_nofile_limit()

from bot.migrations.runner import run_pending_migrations

_MIGRATIONS_CHECKED_ARG = "--tcb-migrations-checked"
_migrations_checked = _MIGRATIONS_CHECKED_ARG in sys.argv[1:]
if _migrations_checked:
    sys.argv = [sys.argv[0], *(arg for arg in sys.argv[1:] if arg != _MIGRATIONS_CHECKED_ARG)]
else:
    run_pending_migrations(repo_root=_package_root)

from bot.main import main

if __name__ == "__main__":
    main()
