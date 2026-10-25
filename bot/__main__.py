"""模块入口 (python -m bot)"""

import os
import json
import sys
from pathlib import Path

from bot.bootstrap import ensure_nofile_limit

# 确保 refactoring/ 在 sys.path 中
_this_dir = os.path.dirname(os.path.abspath(__file__))
_package_root = os.path.dirname(_this_dir)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

ensure_nofile_limit()

if __name__ == "__main__" and getattr(sys.modules.get("bot"), "__path__", None) != []:
    import atexit
    from bot.update_state import begin_host_execution
    _host_execution_lease = begin_host_execution(_package_root)
    atexit.register(_host_execution_lease.close)

from bot.migrations.runner import run_pending_migrations

_MIGRATIONS_CHECKED_ARG = "--tcb-migrations-checked"
_migrations_checked = _MIGRATIONS_CHECKED_ARG in sys.argv[1:]
if _migrations_checked:
    sys.argv = [sys.argv[0], *(arg for arg in sys.argv[1:] if arg != _MIGRATIONS_CHECKED_ARG)]
else:
    storage_module_path = Path(_this_dir) / "storage_migration.py"
    package_path = getattr(sys.modules.get("bot"), "__path__", None)
    if storage_module_path.is_file() and package_path != []:
        from bot import runtime_paths
        from bot.storage_migration import StorageMigrationError, StorageMigrationService

        locator = runtime_paths.read_storage_locator()
        if locator is not None:
            try:
                StorageMigrationService(Path(_package_root)).finalize_startup()
            except StorageMigrationError as exc:
                journal_path = runtime_paths.get_storage_journal_path()
                try:
                    journal = json.loads(journal_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    journal = {}
                if str(journal.get("state") or "").strip().lower() != "cleanup_pending":
                    raise
                print(f"TCB 原始数据清理尚未完成，将使用新目录启动并允许稍后重试: {exc}")
    run_pending_migrations(repo_root=_package_root)

from bot.main import main

# Importing main also loads config; isolated entrypoint fixtures may supply only main.
_runtime_config = sys.modules.get("bot.config")
if _runtime_config is not None:
    _runtime_config.MIGRATIONS_READY = True

if __name__ == "__main__":
    main()
