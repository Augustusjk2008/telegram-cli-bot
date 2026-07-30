from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


ENTRYPOINT_PATH = Path("bot/__main__.py")
MIGRATIONS_CHECKED_ARG = "--tcb-migrations-checked"


def _run_entrypoint(
    monkeypatch: pytest.MonkeyPatch, entrypoint_args: list[str]
) -> tuple[list[str], list[list[str]]]:
    migration_calls: list[str] = []
    main_calls: list[list[str]] = []

    def record_pending_migration(*, repo_root: str) -> None:
        migration_calls.append(repo_root)

    package = ModuleType("bot")
    package.__path__ = []  # type: ignore[attr-defined]
    bootstrap = ModuleType("bot.bootstrap")
    bootstrap.ensure_nofile_limit = lambda: None  # type: ignore[attr-defined]
    runner = ModuleType("bot.migrations.runner")
    runner.run_pending_migrations = record_pending_migration  # type: ignore[attr-defined]
    main_module = ModuleType("bot.main")
    main_module.main = lambda: main_calls.append(list(sys.argv))  # type: ignore[attr-defined]

    package.bootstrap = bootstrap  # type: ignore[attr-defined]
    package.main = main_module  # type: ignore[attr-defined]
    migrations = ModuleType("bot.migrations")
    migrations.runner = runner  # type: ignore[attr-defined]
    package.migrations = migrations  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "bot", package)
    monkeypatch.setitem(sys.modules, "bot.bootstrap", bootstrap)
    monkeypatch.setitem(sys.modules, "bot.migrations", migrations)
    monkeypatch.setitem(sys.modules, "bot.migrations.runner", runner)
    monkeypatch.setitem(sys.modules, "bot.main", main_module)
    monkeypatch.setattr(sys, "argv", [str(ENTRYPOINT_PATH), *entrypoint_args])

    runpy.run_path(str(ENTRYPOINT_PATH), run_name="__main__")
    return migration_calls, main_calls


def test_main_skips_pending_migrations_only_for_explicit_preflight_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls, main_calls = _run_entrypoint(monkeypatch, [MIGRATIONS_CHECKED_ARG])

    assert migration_calls == []
    assert len(main_calls) == 1
    assert MIGRATIONS_CHECKED_ARG not in main_calls[0]


def test_main_runs_pending_migrations_without_preflight_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_calls, main_calls = _run_entrypoint(monkeypatch, [])

    assert migration_calls == [str(ENTRYPOINT_PATH.parent.parent.resolve())]
    assert len(main_calls) == 1


def _write_subprocess_fixture(package_root: Path) -> None:
    bot_dir = package_root / "bot"
    migrations_dir = bot_dir / "migrations"
    migrations_dir.mkdir(parents=True)
    (bot_dir / "__init__.py").write_text("", encoding="utf-8")
    (migrations_dir / "__init__.py").write_text("", encoding="utf-8")
    (bot_dir / "__main__.py").write_text(ENTRYPOINT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (bot_dir / "bootstrap.py").write_text("def ensure_nofile_limit():\n    return None\n", encoding="utf-8")
    (migrations_dir / "runner.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "def run_pending_migrations(*, repo_root):\n"
        "    Path(os.environ['MIGRATION_CALL_PATH']).write_text(str(repo_root), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (bot_dir / "main.py").write_text(
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "def main():\n"
        "    Path(os.environ['MAIN_CALL_PATH']).write_text(json.dumps(sys.argv), encoding='utf-8')\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("preflighted", [False, True])
def test_python_module_entrypoint_preflight_gate_in_a_real_subprocess(
    tmp_path: Path,
    preflighted: bool,
) -> None:
    package_root = tmp_path / "package"
    _write_subprocess_fixture(package_root)
    migration_call_path = tmp_path / "migration-call"
    main_call_path = tmp_path / "main-call"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(package_root),
            "MIGRATION_CALL_PATH": str(migration_call_path),
            "MAIN_CALL_PATH": str(main_call_path),
        }
    )
    args = [sys.executable, "-m", "bot"]
    if preflighted:
        args.append(MIGRATIONS_CHECKED_ARG)

    completed = subprocess.run(
        args,
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert migration_call_path.exists() is (not preflighted)
    forwarded_args = json.loads(main_call_path.read_text(encoding="utf-8"))
    assert MIGRATIONS_CHECKED_ARG not in forwarded_args
