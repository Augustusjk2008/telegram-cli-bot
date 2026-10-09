"""Web-facing adapter for the runtime storage migration service.

The migration implementation owns the source inventory and filesystem work.  This
module keeps the Web API contract small and makes the stop-all-agents boundary an
explicit callback supplied by the application lifecycle.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any


STORAGE_MIGRATION_STATES = frozenset(
    {
        "stopping",
        "copying",
        "verifying",
        "awaiting_restart",
        "cleanup_pending",
        "completed",
        "failed",
    }
)
_TERMINAL_STATES = frozenset({"completed", "failed"})
_PERSISTENT_MAINTENANCE_STATES = frozenset({"awaiting_restart", "cleanup_pending"})


class StorageMigrationApiError(Exception):
    def __init__(self, status: int, code: str, message: str, data: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code)
        self.message = str(message)
        self.data = dict(data or {})


class StorageMigrationApi:
    """Serialize migration operations and bind execution to a previewed plan."""

    def __init__(
        self,
        service: Any | None = None,
        *,
        stop_all_agents: Callable[[], Awaitable[object] | object] | None = None,
    ):
        self.service = service
        self.stop_all_agents = stop_all_agents
        self._lock = asyncio.Lock()
        self._maintenance = False
        self._plans: dict[str, dict[str, Any]] = {}
        self._status: dict[str, Any] = {
            "state": "failed",
            "message": "存储迁移服务尚未接入",
            "available": False,
            "maintenance": False,
        }
        self._task: asyncio.Task[None] | None = None

    @property
    def maintenance(self) -> bool:
        return self._maintenance

    def _require_service(self) -> Any:
        if self.service is None:
            raise StorageMigrationApiError(
                503,
                "storage_migration_unavailable",
                "存储迁移服务尚未接入应用生命周期",
                {"state": self._status.get("state", "failed"), "maintenance": self._maintenance},
            )
        return self.service

    @staticmethod
    async def _maybe_await(value: object) -> object:
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _mapping(value: object) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _field(data: Mapping[str, Any], *names: str, default: object = None) -> object:
        for name in names:
            if name in data:
                return data[name]
        return default

    @classmethod
    def _state(cls, data: Mapping[str, Any], default: str = "failed") -> str:
        value = str(cls._field(data, "state", "status", default=default) or default).strip().lower()
        return value if value in STORAGE_MIGRATION_STATES else default

    @classmethod
    def _publicize_source(cls, value: object) -> dict[str, Any]:
        source = cls._mapping(value)
        return {
            "id": str(cls._field(source, "id", "key", "kind", default="")),
            "label": str(cls._field(source, "label", "name", default="")),
            "path": str(cls._field(source, "path", "source_path", "sourcePath", default="")),
            "exists": bool(cls._field(source, "exists", default=False)),
            "sizeBytes": max(0, int(cls._field(source, "size_bytes", "sizeBytes", "bytes", default=0) or 0)),
            "fileCount": max(0, int(cls._field(source, "file_count", "fileCount", default=0) or 0)),
            "sizePending": bool(cls._field(source, "size_pending", "sizePending", default=False)),
        }

    @classmethod
    def _publicize(cls, value: object, *, maintenance: bool | None = None) -> dict[str, Any]:
        raw = cls._mapping(value)
        data = dict(raw)
        migration = raw.get("migration")
        if isinstance(migration, Mapping):
            for key, item in migration.items():
                data.setdefault(key, item)
            data.pop("migration", None)
        default_state = "completed" if "currentRoot" in data or "current_root" in data else "failed"
        state = cls._state(data, default=default_state)
        aliases = {
            "id": "planId",
            "plan_id": "planId",
            "target_root": "targetRoot",
            "source_root": "sourceRoot",
            "total_bytes": "totalBytes",
            "file_count": "fileCount",
            "cleanup_pending": "cleanupPending",
            "restart_required": "restartRequired",
            "confirm_stop_all_agents": "confirmStopAllAgents",
            "expires_at": "expiresAt",
            "error_code": "errorCode",
        }
        for source_name, public_name in aliases.items():
            if source_name in data and public_name not in data:
                data[public_name] = data[source_name]
            data.pop(source_name, None)
        data["state"] = state
        if "sources" in data and isinstance(data["sources"], list):
            data["sources"] = [cls._publicize_source(item) for item in data["sources"]]
        if "totalBytes" not in data and isinstance(data.get("sources"), list):
            data["totalBytes"] = sum(int(item.get("sizeBytes", 0) or 0) for item in data["sources"] if isinstance(item, Mapping))
        if "progress" not in data and "progressBytes" in data:
            total = int(data.get("totalBytes", 0) or 0)
            data["progress"] = min(1.0, max(0.0, int(data.get("progressBytes", 0) or 0) / total)) if total else 0.0
        if "canMigrate" in data and "available" not in data:
            data["available"] = True
        if maintenance is not None:
            data["maintenance"] = maintenance
        return data

    async def _call(self, name: str, *args: object, **kwargs: object) -> object:
        service = self._require_service()
        method = getattr(service, name, None)
        if not callable(method):
            raise StorageMigrationApiError(503, "storage_migration_api_missing", f"迁移服务缺少 {name} 接口")
        try:
            return await self._maybe_await(method(*args, **kwargs))
        except StorageMigrationApiError:
            raise
        except Exception as exc:
            raise StorageMigrationApiError(500, "storage_migration_failed", str(exc)) from exc

    async def _call_plan(self, name: str, plan_id: str) -> object:
        service = self._require_service()
        method = getattr(service, name, None)
        if not callable(method):
            raise StorageMigrationApiError(503, "storage_migration_api_missing", f"迁移服务缺少 {name} 接口")
        plan = self._plans.get(plan_id, {})
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        kwargs: dict[str, object] = {}
        if "plan_id" in parameters:
            kwargs["plan_id"] = plan_id
        elif "migration_id" in parameters:
            kwargs["migration_id"] = plan_id
        elif "plan" in parameters:
            kwargs["plan"] = plan
        try:
            if kwargs:
                return await self._maybe_await(method(**kwargs))
            if parameters:
                return await self._maybe_await(method(plan_id))
            return await self._maybe_await(method())
        except StorageMigrationApiError:
            raise
        except TypeError as exc:
            raise StorageMigrationApiError(500, "storage_migration_failed", str(exc)) from exc
        except Exception as exc:
            status = 409 if type(exc).__name__ in {"StorageMigrationError", "MigrationError"} else 500
            raise StorageMigrationApiError(status, "storage_migration_failed", str(exc)) from exc

    def _status_from(self, value: object, *, fallback: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = self._publicize(value if isinstance(value, Mapping) else fallback or {})
        if not data:
            data = dict(fallback or {})
        data["state"] = self._state(data, default=str(self._status.get("state") or "completed"))
        data["maintenance"] = self._maintenance or data["state"] in _PERSISTENT_MAINTENANCE_STATES
        data.setdefault("available", True)
        return data

    def _set_status(self, value: object, *, fallback: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self._status = self._status_from(value, fallback=fallback)
        state = self._status["state"]
        if state in _TERMINAL_STATES:
            self._maintenance = False
        elif state in _PERSISTENT_MAINTENANCE_STATES:
            self._maintenance = True
        self._status["maintenance"] = self._maintenance
        return dict(self._status)

    async def snapshot(self) -> dict[str, Any]:
        data = self._status_from(await self._call("snapshot"), fallback=self._status)
        if data["state"] in _PERSISTENT_MAINTENANCE_STATES:
            self._maintenance = True
        data["maintenance"] = self._maintenance
        data.setdefault("planId", self._status.get("planId", ""))
        return data

    async def preview(self, target_root: str) -> dict[str, Any]:
        target = str(target_root or "").strip()
        if not target:
            raise StorageMigrationApiError(400, "invalid_target_root", "目标目录不能为空")
        if self._maintenance:
            raise StorageMigrationApiError(
                409,
                "storage_migration_busy",
                "存储迁移正在进行中",
                {"state": self._status.get("state", "stopping"), "maintenance": True},
            )
        async with self._lock:
            if self._maintenance:
                raise StorageMigrationApiError(409, "storage_migration_busy", "存储迁移正在进行中")
            data = self._publicize(await self._call("preview", target))
            plan_id = str(self._field(data, "planId", "plan_id", "id", default="")).strip()
            if not plan_id:
                raise StorageMigrationApiError(502, "storage_migration_invalid_plan", "迁移预览未返回 planId")
            data["planId"] = plan_id
            data["targetRoot"] = str(self._field(data, "targetRoot", "target_root", default=target))
            if "state" not in data and "status" not in data:
                data["state"] = "verifying"
            self._plans[plan_id] = data
            return {**data, "maintenance": False}

    @staticmethod
    def _stop_ready(value: object) -> bool:
        if isinstance(value, Mapping):
            if value.get("ready") is not None:
                return bool(value.get("ready"))
            if value.get("stopped") is not None:
                return bool(value.get("stopped"))
            if value.get("ok") is not None:
                return bool(value.get("ok"))
            return False
        return value is True

    async def _ensure_agents_stopped(self) -> None:
        if self.stop_all_agents is None:
            raise StorageMigrationApiError(
                409,
                "agent_stop_not_ready",
                "尚未接入停止并 flush 全部智能体的生命周期 hook",
                {"state": "stopping", "maintenance": False, "ready": False},
            )
        try:
            result = await self._maybe_await(self.stop_all_agents())
        except Exception as exc:
            raise StorageMigrationApiError(
                409,
                "agent_stop_not_ready",
                f"全部智能体尚未停止或 flush 失败: {exc}",
                {"state": "stopping", "maintenance": False, "ready": False},
            ) from exc
        if not self._stop_ready(result):
            raise StorageMigrationApiError(
                409,
                "agent_stop_not_ready",
                "全部智能体尚未停止或 flush 完成",
                {"state": "stopping", "maintenance": False, "ready": False},
            )

    async def _run_plan(self, plan_id: str) -> None:
        try:
            execute_result = await self._call_plan("execute", plan_id)
            status = self._set_status(execute_result, fallback=self._status)
            if status["state"] in {"awaiting_restart", "cleanup_pending", "failed", "completed"}:
                return
            finalize_result = await self._call_plan("finalize", plan_id)
            self._set_status(finalize_result, fallback=status)
        except StorageMigrationApiError as exc:
            self._status = {
                **self._status,
                "state": "failed",
                "errorCode": exc.code,
                "message": exc.message,
                "maintenance": False,
            }
            self._maintenance = False
        finally:
            self._task = None

    async def begin(self, plan_id: str, *, confirm_stop_all_agents: bool) -> dict[str, Any]:
        normalized_plan_id = str(plan_id or "").strip()
        if not normalized_plan_id:
            raise StorageMigrationApiError(400, "invalid_plan_id", "planId 不能为空")
        if confirm_stop_all_agents is not True:
            raise StorageMigrationApiError(
                409,
                "confirm_stop_all_agents_required",
                "必须确认停止全部智能体后才能迁移",
                {"state": "stopping", "maintenance": False},
            )
        async with self._lock:
            if self._maintenance or (self._task is not None and not self._task.done()):
                raise StorageMigrationApiError(
                    409,
                    "storage_migration_busy",
                    "存储迁移正在进行中",
                    {"state": self._status.get("state", "stopping"), "maintenance": True},
                )
            plan = self._plans.get(normalized_plan_id)
            if plan is None:
                raise StorageMigrationApiError(409, "storage_migration_plan_invalid", "planId 无效或预览已失效")
            self._maintenance = True
            self._status = {
                **plan,
                "state": "stopping",
                "maintenance": True,
                "available": True,
            }
            try:
                await self._ensure_agents_stopped()
                result = await self._call_plan("begin", normalized_plan_id)
            except StorageMigrationApiError as exc:
                self._status.update({"state": "failed", "errorCode": exc.code, "message": exc.message})
                self._maintenance = False
                self._status["maintenance"] = False
                raise
            status = self._set_status(result, fallback=self._status)
            if status["state"] not in {"awaiting_restart", "cleanup_pending", "failed", "completed"}:
                self._task = asyncio.create_task(self._run_plan(normalized_plan_id))
            return status

    async def retry(self) -> dict[str, Any]:
        async with self._lock:
            if self._task is not None and not self._task.done():
                raise StorageMigrationApiError(409, "storage_migration_busy", "存储迁移正在进行中")
            if self.service is None:
                self._require_service()
            self._maintenance = True
            try:
                method_name = "retry_cleanup" if callable(getattr(self.service, "retry_cleanup", None)) else "retry"
                result = await self._call(method_name)
                status = self._set_status(result, fallback=self._status)
                if status["state"] not in {"awaiting_restart", "cleanup_pending", "failed", "completed"}:
                    plan_id = str(status.get("planId") or self._status.get("planId") or "")
                    if plan_id:
                        self._task = asyncio.create_task(self._run_plan(plan_id))
                return status
            except StorageMigrationApiError:
                self._maintenance = False
                self._status["maintenance"] = False
                raise

    async def finalize(self) -> dict[str, Any]:
        """Finalize a committed migration after the supervised restart."""

        async with self._lock:
            method_name = "finalize" if callable(getattr(self.service, "finalize", None)) else "finalize_startup"
            result = await self._call(method_name)
            status = self._set_status(result, fallback=self._status)
            return status
