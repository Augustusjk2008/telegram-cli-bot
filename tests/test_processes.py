from __future__ import annotations

import inspect
import os
import signal
import subprocess
import sys
import time

import pytest

from bot.platform import processes


def test_process_tree_handle_terminates_job_after_root_process_exits(monkeypatch) -> None:
    class ExitedProcess:
        def poll(self) -> int:
            return 0

    class FakeJob:
        def __init__(self) -> None:
            self.terminate_calls = 0

        def terminate(self) -> None:
            self.terminate_calls += 1

        def close(self) -> None:
            return None

    fallback_calls: list[object] = []
    monkeypatch.setattr(
        processes,
        "terminate_process_tree_sync",
        lambda process: fallback_calls.append(process),
    )
    assert hasattr(processes, "ProcessTreeHandle"), "缺少跨根进程退出保留所有权的进程树句柄"
    job = FakeJob()
    handle = processes.ProcessTreeHandle(ExitedProcess(), job)

    handle.terminate()

    assert job.terminate_calls == 1
    assert fallback_calls == []


def test_process_tree_handle_termination_and_close_are_idempotent() -> None:
    class FakeJob:
        def __init__(self) -> None:
            self.terminate_calls = 0
            self.close_calls = 0

        def terminate(self) -> None:
            self.terminate_calls += 1

        def close(self) -> None:
            self.close_calls += 1

    job = FakeJob()
    handle = processes.ProcessTreeHandle(object(), job)

    handle.terminate()
    handle.terminate()
    handle.close()
    handle.close()
    handle.terminate()

    assert job.terminate_calls == 1
    assert job.close_calls == 1


def test_process_tree_handle_terminates_posix_group_after_leader_exits(monkeypatch) -> None:
    class ExitedProcess:
        pid = 4321

        def poll(self) -> int:
            return 0

    killpg_calls: list[tuple[int, int]] = []
    fallback_calls: list[object] = []
    monkeypatch.setattr(processes.os, "name", "posix")
    monkeypatch.setattr(
        processes.os,
        "killpg",
        lambda process_group_id, sig: killpg_calls.append((process_group_id, sig)),
        raising=False,
    )
    handle = processes.ProcessTreeHandle(
        ExitedProcess(),
        None,
        terminate_fallback=lambda process: fallback_calls.append(process),
        process_group_id=4321,
    )

    handle.terminate()

    assert killpg_calls
    assert killpg_calls[0] == (4321, signal.SIGTERM)
    assert fallback_calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended process contract")
def test_windows_chat_process_is_contained_before_it_is_resumed(tmp_path) -> None:
    assert "suspended" in inspect.signature(
        processes.build_chat_cli_process_kwargs
    ).parameters, "聊天 CLI 创建参数尚不支持原子 Job 绑定"
    assert hasattr(processes, "resume_suspended_process")
    marker = tmp_path / "started"
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
        **processes.build_chat_cli_process_kwargs(suspended=True),
    )
    process_tree = processes.attach_process_tree(process)
    try:
        time.sleep(0.2)
        assert marker.exists() is False
        assert process_tree.is_contained is True

        processes.resume_suspended_process(process, process_tree)

        assert process.wait(timeout=2) == 0
        assert marker.exists() is True
    finally:
        process_tree.terminate()
        process_tree.close()
