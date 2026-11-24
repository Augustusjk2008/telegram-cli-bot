"""Git page operations that keep running after the page that started them closes.

The page starts an operation, receives its ID at once and polls it. The work
runs as a server task, so leaving the Git page neither cancels it nor loses its
result, and a page opened later can attach to the running operation.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from bot.remote_workspace.transport import RemoteWorkspaceError

from .api_common import WebApiError, web_api_error_from_remote

logger = logging.getLogger(__name__)

GIT_SYNC_OPERATIONS = ("fetch", "pull", "merge", "push")
GIT_OPERATION_KINDS = (*GIT_SYNC_OPERATIONS, "commit", "commit_message")
GIT_OPERATION_NOTICES = {
    "fetch": "已抓取远端更新",
    "pull": "已拉取远端更新",
    "merge": "已合并远端更新",
    "push": "已推送本地提交",
    "commit": "已创建提交",
    "commit_message": "已生成提交说明",
}
_GIT_OPERATION_LABELS = {
    "fetch": "Fetch",
    "pull": "Pull",
    "merge": "Merge",
    "push": "Push",
    "commit": "提交",
    "commit_message": "生成提交说明",
}

GitOperationRunner = Callable[[], Awaitable[dict[str, Any]]]


class GitOperationRegistry:
    """Runs at most one page operation per Bot and keeps the latest one."""

    def __init__(self) -> None:
        self._operations: dict[str, dict[str, Any]] = {}
        self._latest_by_alias: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, alias: str, kind: str, runner: GitOperationRunner) -> dict[str, Any]:
        latest = self._latest(alias)
        if latest is not None and latest["status"] == "running":
            label = _GIT_OPERATION_LABELS.get(latest["kind"], latest["kind"])
            raise WebApiError(
                409,
                "git_operation_running",
                f"已有 Git 操作正在进行：{label}",
                {"operation": self.snapshot(latest)},
            )
        if latest is not None:
            self._operations.pop(latest["operation_id"], None)
        operation_id = f"gop_{uuid.uuid4().hex}"
        operation: dict[str, Any] = {
            "operation_id": operation_id,
            "alias": alias,
            "kind": kind,
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "notice": "",
            "commit_message": "",
            "overview": None,
            "error": None,
        }
        self._operations[operation_id] = operation
        self._latest_by_alias[alias] = operation_id
        # The task belongs to the server, not to the request that started it.
        self._tasks[operation_id] = asyncio.create_task(self._run(operation, runner))
        return self.snapshot(operation)

    def active(self, alias: str) -> dict[str, Any] | None:
        latest = self._latest(alias)
        return self.snapshot(latest) if latest is not None else None

    def get(self, alias: str, operation_id: str) -> dict[str, Any]:
        operation = self._operations.get(operation_id)
        if operation is None or operation["alias"] != alias:
            raise WebApiError(404, "git_operation_not_found", "未找到 Git 操作")
        return self.snapshot(operation)

    @staticmethod
    def snapshot(operation: dict[str, Any]) -> dict[str, Any]:
        error = operation.get("error")
        return {
            "operation_id": operation["operation_id"],
            "alias": operation["alias"],
            "kind": operation["kind"],
            "status": operation["status"],
            "started_at": operation["started_at"],
            "finished_at": operation["finished_at"],
            "notice": operation["notice"],
            "commit_message": operation["commit_message"],
            "overview": operation["overview"],
            "error": dict(error) if isinstance(error, dict) else None,
        }

    def _latest(self, alias: str) -> dict[str, Any] | None:
        operation_id = self._latest_by_alias.get(alias)
        return self._operations.get(operation_id) if operation_id else None

    async def _run(self, operation: dict[str, Any], runner: GitOperationRunner) -> None:
        try:
            result = await runner()
        except WebApiError as exc:
            self._fail(operation, exc)
        except RemoteWorkspaceError as exc:
            self._fail(operation, web_api_error_from_remote(exc))
        except asyncio.CancelledError:
            self._fail(operation, WebApiError(503, "git_operation_interrupted", "Git 操作已中断，请刷新后确认结果"))
            raise
        except Exception as exc:
            logger.exception("Git operation %s failed: %s", operation["kind"], exc)
            self._fail(operation, WebApiError(500, "internal_error", str(exc) or "Git 操作失败"))
        else:
            overview = result.get("overview")
            operation.update(
                status="succeeded",
                notice=str(result.get("notice") or GIT_OPERATION_NOTICES.get(operation["kind"], "")),
                commit_message=str(result.get("commit_message") or ""),
                overview=overview if isinstance(overview, dict) else None,
            )
        finally:
            operation["finished_at"] = time.time()
            self._tasks.pop(operation["operation_id"], None)

    @staticmethod
    def _fail(operation: dict[str, Any], exc: WebApiError) -> None:
        operation.update(
            status="failed",
            error={"status": exc.status, "code": exc.code, "message": exc.message, "data": dict(exc.data)},
        )
