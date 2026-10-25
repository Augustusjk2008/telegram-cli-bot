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
SUBPROCESS_PACKAGE_ROOT_ENV = "TCB_TEST_PACKAGE_ROOT"
SUBPROCESS_ENTRYPOINT = (
    "import os, runpy, sys; "
    f"sys.path.insert(0, os.environ[{SUBPROCESS_PACKAGE_ROOT_ENV!r}]); "
    "sys.argv = ['bot', *sys.argv[1:]]; "
    "runpy.run_module('bot', run_name='__main__')"
)


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


@pytest.mark.parametrize("preflighted", [False, True])
def test_main_migration_preflight_gate(monkeypatch: pytest.MonkeyPatch, preflighted: bool) -> None:
    migration_calls, main_calls = _run_entrypoint(
        monkeypatch, [MIGRATIONS_CHECKED_ARG] if preflighted else []
    )

    assert migration_calls == ([] if preflighted else [str(ENTRYPOINT_PATH.parent.parent.resolve())])
    assert len(main_calls) == 1
    assert MIGRATIONS_CHECKED_ARG not in main_calls[0]


def _write_subprocess_fixture(package_root: Path) -> None:
    bot_dir = package_root / "bot"
    migrations_dir = bot_dir / "migrations"
    migrations_dir.mkdir(parents=True)
    (bot_dir / "__init__.py").write_text("", encoding="utf-8")
    (migrations_dir / "__init__.py").write_text("", encoding="utf-8")
    (bot_dir / "__main__.py").write_text(ENTRYPOINT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (bot_dir / "update_state.py").write_text(ENTRYPOINT_PATH.with_name("update_state.py").read_text(encoding="utf-8"), encoding="utf-8")
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
def test_python_module_entrypoint_preflight_gate_in_an_isolated_real_subprocess(
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
            SUBPROCESS_PACKAGE_ROOT_ENV: str(package_root),
            "MIGRATION_CALL_PATH": str(migration_call_path),
            "MAIN_CALL_PATH": str(main_call_path),
            "TCB_UPDATE_CONTROL_ROOT": str(tmp_path / "control"),
            "CLI_BRIDGE_UPDATE_PROTOCOL": "",
        }
    )
    args = [sys.executable, "-I", "-c", SUBPROCESS_ENTRYPOINT]
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


def test_update_unknown_migration_is_blocked_before_exit(tmp_path):
    from bot.update_migration_gate import validate_update_migrations
    current, staged = tmp_path / "current", tmp_path / "staged"
    for root, ids in ((current, "('001',)"), (staged, "('001', '002')")):
        directory = root / "bot" / "migrations"
        directory.mkdir(parents=True)
        (directory / "runner.py").write_text(f"MIGRATION_IDS = {ids}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="002"):
        validate_update_migrations(current, {"staging_dir": str(staged),
                                             "manifest": {"migrations": {"backward_compatible": True}}})


def test_update_migration_compatibility_must_be_boolean(tmp_path):
    from bot.update_migration_gate import validate_update_migrations
    for declaration in ({}, {"backward_compatible": "true"}, {"backward_compatible": False}):
        with pytest.raises(ValueError, match="向后兼容"):
            validate_update_migrations(tmp_path, {"staging_dir": str(tmp_path), "manifest": {"migrations": declaration}})


@pytest.mark.parametrize("name", ["bot/migrations/runner.py", "bot/migrations/__init__.py",
                                  "bot/storage_migration.py", "bot/storage_runtime.py"])
@pytest.mark.parametrize("operation", ["modify", "delete"])
def test_update_migration_implementation_changes_require_review(tmp_path, name, operation):
    from bot.update_migration_gate import validate_update_migrations
    current, staged = tmp_path / "current", tmp_path / "staged"
    for root in (current, staged):
        file = root / name
        file.parent.mkdir(parents=True)
        file.write_text("MIGRATION_IDS = ('001',)\ndef migrate():\n    return 1\n", encoding="utf-8")
    prepared = {"staging_dir": str(staged), "files": [name], "delete_paths": [],
                "manifest": {"migrations": {"backward_compatible": True}}}
    validate_update_migrations(current, prepared)
    if operation == "modify":
        (staged / name).write_text("MIGRATION_IDS = ('001',)\ndef migrate():\n    return 2\n", encoding="utf-8")
    else:
        (staged / name).unlink()
        prepared.update(files=[], delete_paths=[name])
    with pytest.raises(ValueError, match="实现变更"):
        validate_update_migrations(current, prepared)
