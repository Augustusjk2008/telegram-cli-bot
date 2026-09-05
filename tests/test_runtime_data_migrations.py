from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from bot.migrations import runner


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _configure_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, data_root: Path) -> None:
    monkeypatch.setenv("TCB_DATA_DIR", str(data_root))
    monkeypatch.setattr(runner, "default_plugins_root", lambda: tmp_path / "plugins")


def _configured_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    data_root, repo_root = tmp_path / "runtime-data", tmp_path / "repo"
    _configure_runtime(monkeypatch, tmp_path, data_root)
    repo_root.mkdir()
    return data_root, repo_root


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _wait_for_path(path: Path, *, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


def _isolated_subprocess_env(tmp_path: Path, data_root: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "TCB_DATA_DIR": str(data_root),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    env.pop("HOMEDRIVE", None)
    env.pop("HOMEPATH", None)
    return env


def _run_migration_cli(repo_root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bot.migrations", "run", "--repo-root", str(repo_root)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )


def _start_worker(script: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script], cwd=PROJECT_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )


def test_migration_cli_lists_completed_items_then_reports_no_pending_without_rewriting_state(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    data_root = tmp_path / "runtime-data"
    env = _isolated_subprocess_env(tmp_path, data_root)

    first = _run_migration_cli(repo_root, env)

    assert first.returncode == 0, first.stderr

    state_path = data_root / "migrations" / "state.json"
    state_before = state_path.read_bytes()
    mtime_before = state_path.stat().st_mtime_ns

    second = _run_migration_cli(repo_root, env)

    assert second.returncode == 0, second.stderr
    assert state_path.read_bytes() == state_before
    assert state_path.stat().st_mtime_ns == mtime_before


def test_main_reports_migration_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fail_migration(*, repo_root: str | Path) -> None:
        raise ValueError(f"损坏的迁移状态: {repo_root}")

    monkeypatch.setattr(runner, "run_pending_migrations", fail_migration)

    assert runner.main(["run", "--repo-root", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "invalid_state",
    [
        "{not-json",
        "[]",
        json.dumps({"version": 1}),
        json.dumps({"version": 1, "completed": "not-a-list"}),
        json.dumps(
            {
                "version": 1,
                "completed": [],
                "last_repair": {"detail": {"targets": "not-a-list"}},
            }
        ),
    ],
)
def test_existing_invalid_migration_state_fails_without_overwriting_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invalid_state: str
) -> None:
    data_root, repo_root = _configured_repo(monkeypatch, tmp_path)
    state_path = data_root / "migrations" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(invalid_state, encoding="utf-8")
    state_before = state_path.read_bytes()

    with pytest.raises(ValueError, match="迁移状态文件"):
        runner.run_pending_migrations(repo_root)

    assert state_path.read_bytes() == state_before


def test_tcb_data_roots_keep_independent_idempotent_migration_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    first_root = tmp_path / "runtime-a"
    second_root = tmp_path / "runtime-b"
    _configure_runtime(monkeypatch, tmp_path, first_root)

    first = runner.run_pending_migrations(repo_root)
    assert first.completed == list(runner.MIGRATION_IDS)
    first_state_before = first.state_path.read_bytes()
    first_mtime_before = first.state_path.stat().st_mtime_ns

    repeated = runner.run_pending_migrations(repo_root)

    assert repeated.completed == []
    assert repeated.skipped == list(runner.MIGRATION_IDS)
    assert getattr(repeated, "repairs", None) == []
    assert first.state_path.read_bytes() == first_state_before
    assert first.state_path.stat().st_mtime_ns == first_mtime_before

    monkeypatch.setenv("TCB_DATA_DIR", str(second_root))
    second = runner.run_pending_migrations(repo_root)

    assert second.completed == list(runner.MIGRATION_IDS)
    assert second.skipped == []
    assert second.state_path != first.state_path
    assert second.state_path == second_root / "migrations" / "state.json"
    assert first.state_path.exists()
    assert second.state_path.exists()


def test_rerun_does_not_rewrite_historical_repair_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_root, repo_root = _configured_repo(monkeypatch, tmp_path)
    state_path = _write_json(
        data_root / "migrations" / "state.json",
        {
            "version": 1, "completed": [{"id": item} for item in runner.MIGRATION_IDS],
            "last_error": "", "last_repair": {"detail": {"targets": ["app_settings"]}},
        },
    )
    state_before = state_path.read_bytes()
    mtime_before = state_path.stat().st_mtime_ns

    result = runner.run_pending_migrations(repo_root)

    assert result.completed == []
    assert result.skipped == list(runner.MIGRATION_IDS)
    assert getattr(result, "repairs", None) == []
    assert state_path.read_bytes() == state_before
    assert state_path.stat().st_mtime_ns == mtime_before


@pytest.mark.parametrize("repair_already_completed", [False, True])
def test_app_settings_repair_state_is_idempotent_and_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repair_already_completed: bool
) -> None:
    data_root, repo_root = _configured_repo(monkeypatch, tmp_path)
    if repair_already_completed:
        _write_json(
            data_root / "migrations" / "state.json",
            {"version": 1, "completed": [{"id": item} for item in runner.MIGRATION_IDS],
             "completed_repairs": ["app_settings"], "last_error": ""},
        )
    else:
        runner.run_pending_migrations(repo_root)
    _write_json(
        repo_root / ".web_admin_settings.json",
        {"main_bot_profile": {"working_dir": "C:/legacy-workspace"}, "update_enabled": True},
    )
    app_settings_path = _write_json(
        data_root / "config" / "app_settings.json",
        {"main_bot_profile": {"working_dir": str(tmp_path / "pytest-of-user" / "workspace")}, "update_enabled": False},
    )
    target_before = app_settings_path.read_bytes()

    result = runner.run_pending_migrations(repo_root)

    assert result.completed == []
    assert result.skipped == list(runner.MIGRATION_IDS)
    assert result.repairs == ([] if repair_already_completed else ["app_settings"])
    if repair_already_completed:
        assert app_settings_path.read_bytes() == target_before


_LOCK_WORKER = textwrap.dedent(
    """
    import os
    import time
    from pathlib import Path

    from bot.migrations import runner

    signal_dir = Path(os.environ["MIGRATION_SIGNAL_DIR"])
    role = os.environ["MIGRATION_WORKER_ROLE"]
    original = runner._run_repo_state_migration

    def hold_repo_state_migration(repo_root):
        (signal_dir / f"entered-{role}").write_text("entered", encoding="utf-8")
        while not (signal_dir / "release").exists():
            time.sleep(0.02)
        return original(repo_root)

    runner._run_repo_state_migration = hold_repo_state_migration
    (signal_dir / f"ready-{role}").write_text("ready", encoding="utf-8")
    if role == "second":
        while not (signal_dir / "start-second").exists():
            time.sleep(0.02)
    runner.run_pending_migrations(Path(os.environ["MIGRATION_REPO_ROOT"]))
    (signal_dir / f"done-{role}").write_text("done", encoding="utf-8")
    """
)


def _stop_process(process: subprocess.Popen[str] | None, release_path: Path) -> None:
    release_path.touch(exist_ok=True)
    if process is None or process.poll() is not None:
        return
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.communicate(timeout=5)


def test_second_process_cannot_enter_migration_while_first_holds_the_lock(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    data_root = tmp_path / "runtime-data"
    signal_dir = tmp_path / "signals"
    signal_dir.mkdir()
    env = _isolated_subprocess_env(tmp_path, data_root)
    env.update({"MIGRATION_SIGNAL_DIR": str(signal_dir), "MIGRATION_REPO_ROOT": str(repo_root)})
    first: subprocess.Popen[str] | None = None
    second: subprocess.Popen[str] | None = None
    release_path = signal_dir / "release"

    try:
        first = _start_worker(_LOCK_WORKER, {**env, "MIGRATION_WORKER_ROLE": "first"})
        assert _wait_for_path(signal_dir / "entered-first"), "第一个迁移进程未进入临界区"

        second = _start_worker(_LOCK_WORKER, {**env, "MIGRATION_WORKER_ROLE": "second"})
        assert _wait_for_path(signal_dir / "ready-second"), "第二个迁移进程未准备就绪"
        (signal_dir / "start-second").touch()

        assert not _wait_for_path(signal_dir / "entered-second", timeout_seconds=1.5)

        release_path.touch()
        first_stdout, first_stderr = first.communicate(timeout=10)
        second_stdout, second_stderr = second.communicate(timeout=10)
        assert first.returncode == 0, first_stdout + first_stderr
        assert second.returncode == 0, second_stdout + second_stderr
        assert (signal_dir / "done-first").exists()
        assert (signal_dir / "done-second").exists()
    finally:
        _stop_process(first, release_path)
        _stop_process(second, release_path)

    state = json.loads((data_root / "migrations" / "state.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in state["completed"]] == list(runner.MIGRATION_IDS)


def test_lock_is_released_after_migration_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _data_root, repo_root = _configured_repo(monkeypatch, tmp_path)

    def fail_repo_state_migration(_repo_root: Path) -> dict[str, object]:
        raise RuntimeError("intentional migration failure")

    monkeypatch.setattr(runner, "_run_repo_state_migration", fail_repo_state_migration)
    with pytest.raises(RuntimeError, match="intentional migration failure"):
        runner.run_pending_migrations(repo_root)

    monkeypatch.setattr(runner, "_run_repo_state_migration", lambda _repo_root: {"targets": []})
    result = runner.run_pending_migrations(repo_root)

    assert result.completed == list(runner.MIGRATION_IDS)


_EXITING_LOCK_WORKER = textwrap.dedent(
    """
    import os
    from pathlib import Path

    from bot.migrations import runner

    signal_path = Path(os.environ["MIGRATION_EXIT_SIGNAL"])

    def exit_while_holding_lock(_repo_root):
        signal_path.write_text("entered", encoding="utf-8")
        os._exit(0)

    runner._run_repo_state_migration = exit_while_holding_lock
    runner.run_pending_migrations(Path(os.environ["MIGRATION_REPO_ROOT"]))
    """
)


def test_lock_is_released_when_holding_process_exits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_root, repo_root = _configured_repo(monkeypatch, tmp_path)
    signal_path = tmp_path / "entered"
    env = _isolated_subprocess_env(tmp_path, data_root)
    env.update({"MIGRATION_EXIT_SIGNAL": str(signal_path), "MIGRATION_REPO_ROOT": str(repo_root)})
    process = _start_worker(_EXITING_LOCK_WORKER, env)

    try:
        assert _wait_for_path(signal_path), "子进程未在迁移临界区内退出"
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stdout + stderr
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)

    result = runner.run_pending_migrations(repo_root)

    assert result.completed == list(runner.MIGRATION_IDS)
