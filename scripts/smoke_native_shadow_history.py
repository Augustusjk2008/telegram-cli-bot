#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


EXIT_OK = 0
EXIT_FAILED = 1
# Skipped means this environment cannot exercise the live smoke path; the
# JSON summary carries the diagnostic, while CI can keep optional smoke nonfatal.
EXIT_SKIPPED = 0


class ApiError(RuntimeError):
    def __init__(
        self,
        *,
        method: str,
        url: str,
        status: int,
        code: str = "",
        message: str = "",
        text: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or text or f"{method} {url} -> {status}")
        self.method = method
        self.url = url
        self.status = int(status)
        self.code = str(code or "").strip()
        self.message = str(message or "").strip()
        self.text = str(text or "")
        self.payload = payload or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "text": self.text,
            "payload": self.payload,
        }


@dataclass
class HttpJson:
    status: int
    headers: dict[str, str]
    payload: dict[str, Any] | None
    text: str


class ApiClient:
    def __init__(self, base_url: str, token: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = max(1.0, float(timeout or 20.0))
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "native-shadow-history-smoke/1",
        }
        normalized_token = str(token or "").strip()
        if normalized_token:
            if normalized_token.lower().startswith("bearer "):
                self.headers["Authorization"] = normalized_token
            else:
                self.headers["Authorization"] = f"Bearer {normalized_token}"

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> HttpJson:
        url = self._url(path, query=query)
        body = None
        headers = dict(self.headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
                parsed = _parse_json_object(text)
                return HttpJson(
                    status=int(getattr(response, "status", 200) or 200),
                    headers=dict(response.headers.items()),
                    payload=parsed,
                    text=text,
                )
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            parsed = _parse_json_object(text)
            code, message = _extract_error_fields(parsed)
            raise ApiError(
                method=method.upper(),
                url=url,
                status=int(exc.code),
                code=code,
                message=message,
                text=text,
                payload=parsed if isinstance(parsed, dict) else None,
            ) from exc
        except urllib.error.URLError as exc:
            raise ApiError(
                method=method.upper(),
                url=url,
                status=0,
                code="connection_error",
                message=str(getattr(exc, "reason", exc) or exc),
            ) from exc

    def stream_sse(
        self,
        path: str,
        *,
        payload: dict[str, Any],
        query: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        url = self._url(path, query=query)
        headers = dict(self.headers)
        headers["Accept"] = "text/event-stream"
        headers["Content-Type"] = "application/json; charset=utf-8"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        events: list[dict[str, Any]] = []
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                event_name = "message"
                data_lines: list[str] = []
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                    if line.endswith("\r"):
                        line = line[:-1]
                    if not line:
                        if data_lines:
                            data_text = "\n".join(data_lines)
                            payload_obj = _parse_json_object(data_text)
                            record = {
                                "event": event_name,
                                "data": payload_obj if payload_obj is not None else data_text,
                            }
                            events.append(record)
                            if event_name in {"done", "error"}:
                                break
                        event_name = "message"
                        data_lines = []
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip() or "message"
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                return events
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            parsed = _parse_json_object(text)
            code, message = _extract_error_fields(parsed)
            raise ApiError(
                method="POST",
                url=url,
                status=int(exc.code),
                code=code,
                message=message,
                text=text,
                payload=parsed if isinstance(parsed, dict) else None,
            ) from exc
        except urllib.error.URLError as exc:
            raise ApiError(
                method="POST",
                url=url,
                status=0,
                code="connection_error",
                message=str(getattr(exc, "reason", exc) or exc),
            ) from exc

    def _url(self, path: str, *, query: dict[str, Any] | None) -> str:
        base = f"{self.base_url}/{str(path or '').lstrip('/')}"
        if not query:
            return base
        pairs: list[tuple[str, str]] = []
        for key, value in query.items():
            if value is None:
                continue
            pairs.append((str(key), str(value)))
        encoded = urllib.parse.urlencode(pairs)
        return f"{base}?{encoded}" if encoded else base


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="走现有 Web API 的 native shadow history smoke。缺路由/权限时给 skipped 诊断，不重启服务。"
    )
    parser.add_argument("--base-url", default=os.environ.get("TCB_BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--alias", default=os.environ.get("TCB_BOT_ALIAS", "main"))
    parser.add_argument("--token", default=os.environ.get("WEB_API_TOKEN", ""))
    parser.add_argument("--workspace", default="", help="目标 bot 工作目录。为空则创建临时工作目录后切换。")
    parser.add_argument("--timeout", type=float, default=20.0, help="普通 HTTP 超时秒数。")
    parser.add_argument("--turn-timeout", type=float, default=180.0, help="单轮 SSE 等待超时秒数。")
    parser.add_argument(
        "--artifact-dir",
        default="",
        help="结果目录。默认写系统临时目录下 tcb-smoke-native-shadow-history/<时间戳>。",
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="切 bot 工作目录遇到活动会话时允许 reset；会丢当前活动会话。",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="若脚本切过 bot 工作目录，结束后不切回。",
    )
    parser.add_argument(
        "--keep-probe",
        action="store_true",
        help="保留脚本创建的探针目录，默认结束后删除。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    artifact_dir = _resolve_artifact_dir(args.artifact_dir, run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    requested_workspace = str(args.workspace or "").strip()
    auto_workspace = ""
    if not requested_workspace:
        auto_workspace_path = artifact_dir / "workspace"
        auto_workspace_path.mkdir(parents=True, exist_ok=True)
        requested_workspace = str(auto_workspace_path)
        auto_workspace = requested_workspace
    client = ApiClient(args.base_url, args.token, args.timeout)

    summary: dict[str, Any] = {
        "status": "failed",
        "run_id": run_id,
        "base_url": args.base_url,
        "alias": args.alias,
        "artifact_dir": str(artifact_dir),
        "workspace_requested": str(args.workspace or ""),
        "workspace_auto_created": auto_workspace,
        "started_at": datetime.now(UTC).isoformat(),
        "checks": [],
        "notes": [],
    }
    exit_code = EXIT_FAILED
    switched_workdir = False
    original_workdir = ""
    active_native_conversation_id = ""
    smoke_conversation_id = ""
    current_workdir = ""

    probe_dir = f"__pi_shadow_history_smoke__/{run_id}"
    state_rel = f"{probe_dir}/state.txt"
    extra_rel = f"{probe_dir}/turn2.txt"

    try:
        pwd = client.request_json("GET", f"/api/bots/{args.alias}/pwd")
        current_workdir = str(((pwd.payload or {}).get("data") or {}).get("working_dir") or "")
        original_workdir = current_workdir
        summary["current_workdir"] = current_workdir
        _add_check(summary, "pwd", "passed", working_dir=current_workdir)
    except ApiError as exc:
        _add_check(summary, "pwd", "skipped", error=exc.to_dict(), message="无法连 Web API 或无权读取 pwd")
        summary["status"] = "skipped"
        summary["finished_at"] = datetime.now(UTC).isoformat()
        _write_summary(artifact_dir, summary)
        _print_summary(summary)
        return EXIT_SKIPPED

    try:
        conversations = client.request_json(
            "GET",
            f"/api/bots/{args.alias}/conversations",
            query={"execution_mode": "native_agent", "limit": 200},
        )
        items = (((conversations.payload or {}).get("data") or {}).get("items") or [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("active"):
                    active_native_conversation_id = str(item.get("id") or item.get("conversation_id") or "")
                    break
        _add_check(summary, "native_conversations", "passed", active_conversation_id=active_native_conversation_id)
    except ApiError as exc:
        _add_check(summary, "native_conversations", "skipped", error=exc.to_dict())

    target_workdir = requested_workspace or current_workdir
    summary["workspace_effective"] = target_workdir

    if target_workdir and target_workdir != current_workdir:
        try:
            client.request_json(
                "PATCH",
                f"/api/admin/bots/{args.alias}/workdir",
                payload={"working_dir": target_workdir, "force_reset": bool(args.force_reset)},
            )
            switched_workdir = True
            current_workdir = target_workdir
            _add_check(
                summary,
                "switch_workdir",
                "passed",
                from_workdir=original_workdir,
                to_workdir=target_workdir,
                force_reset=bool(args.force_reset),
            )
        except ApiError as exc:
            status = "skipped"
            message = "切目标工作目录失败"
            if exc.status == 409 and exc.code == "workdir_change_requires_reset":
                message = "切目录会丢当前会话，未传 --force-reset，跳过"
            elif exc.status == 409 and exc.code == "workdir_change_blocked_processing":
                message = "当前 bot 仍在处理任务，跳过"
            elif exc.status in {401, 403}:
                message = "无管理员权限切 bot 工作目录，跳过"
            _add_check(summary, "switch_workdir", status, error=exc.to_dict(), message=message)
            summary["status"] = "skipped"
            summary["finished_at"] = datetime.now(UTC).isoformat()
            _write_summary(artifact_dir, summary)
            _print_summary(summary)
            return EXIT_SKIPPED

    workspace_path = Path(current_workdir)
    state_path = workspace_path / state_rel
    extra_path = workspace_path / extra_rel
    summary["probe_paths"] = {
        "dir": probe_dir,
        "state": state_rel,
        "extra": extra_rel,
    }

    try:
        created = client.request_json(
            "POST",
            f"/api/bots/{args.alias}/conversations",
            payload={"title": f"native shadow history smoke {run_id}", "execution_mode": "native_agent"},
        )
        conversation = ((created.payload or {}).get("data") or {}).get("conversation") or {}
        smoke_conversation_id = str(conversation.get("id") or "")
        if not smoke_conversation_id:
            raise RuntimeError("create_conversation 未返回 id")
        summary["conversation_id"] = smoke_conversation_id
        _add_check(summary, "create_conversation", "passed", conversation_id=smoke_conversation_id)
    except (ApiError, RuntimeError) as exc:
        _add_check(summary, "create_conversation", "skipped", error=_error_payload(exc))
        summary["status"] = "skipped"
        exit_code = EXIT_SKIPPED
        return _finalize(
            summary,
            artifact_dir,
            exit_code,
            client,
            args,
            switched_workdir,
            original_workdir,
            active_native_conversation_id,
            probe_workspace=current_workdir,
            probe_dir=probe_dir,
        )

    try:
        turn1 = _run_turn(
            client,
            args=args,
            alias=args.alias,
            artifact_dir=artifact_dir,
            turn_name="turn1",
            message=(
                "在当前工作目录执行以下操作：\n"
                f"1. 创建目录 `{probe_dir}`\n"
                f"2. 创建文件 `{state_rel}`，内容必须完全等于：\n"
                "```text\nturn-1\n```\n"
                "3. 不改别的文件\n"
                "完成后仅回复 `SMOKE_OK_1`。"
            ),
        )
        summary["turn1"] = turn1
        _verify_text_file(state_path, "turn-1")
        if extra_path.exists():
            raise RuntimeError(f"turn1 后不应存在 {extra_rel}")
        _add_check(summary, "verify_turn1_files", "passed", state=str(state_path), extra_exists=False)

        turn2 = _run_turn(
            client,
            args=args,
            alias=args.alias,
            artifact_dir=artifact_dir,
            turn_name="turn2",
            message=(
                "继续在当前工作目录执行以下操作：\n"
                f"1. 把 `{state_rel}` 内容改成：\n"
                "```text\nturn-2\n```\n"
                f"2. 新建 `{extra_rel}`，内容必须完全等于：\n"
                "```text\nturn-2-extra\n```\n"
                "3. 不改别的文件\n"
                "完成后仅回复 `SMOKE_OK_2`。"
            ),
        )
        summary["turn2"] = turn2
        _verify_text_file(state_path, "turn-2")
        _verify_text_file(extra_path, "turn-2-extra")
        _add_check(summary, "verify_turn2_files", "passed", state=str(state_path), extra=str(extra_path))

        changes_result, changes_status = _try_changes(
            client=client,
            alias=args.alias,
            conversation_id=smoke_conversation_id,
            turn_id=str(turn2["turn_id"]),
        )
        summary["history_changes"] = changes_result
        _add_check(summary, "history_changes", changes_status, **changes_result)

        diff_result, diff_status = _try_diff(
            client=client,
            alias=args.alias,
            conversation_id=smoke_conversation_id,
            turn_id=str(turn2["turn_id"]),
            changes_result=changes_result,
            preferred_path=state_rel,
        )
        summary["history_diff"] = diff_result
        _add_check(summary, "history_diff", diff_status, **diff_result)

        rollback = client.request_json(
            "POST",
            f"/api/bots/{args.alias}/native-agent/history/rollback",
            payload={
                "conversation_id": smoke_conversation_id,
                "target_turn_id": str(turn1["turn_id"]),
            },
        )
        rollback_data = ((rollback.payload or {}).get("data") or {})
        summary["rollback"] = rollback_data
        _verify_text_file(state_path, "turn-1")
        if extra_path.exists():
            raise RuntimeError(f"rollback 后仍存在 {extra_rel}")
        _add_check(summary, "rollback", "passed", **rollback_data)

        final_status = "passed"
        if changes_status != "passed" or diff_status != "passed":
            final_status = "partial"
            summary["notes"].append("changes/diff 路由未通或不可用，rollback 已单独验证")
        summary["status"] = final_status
        exit_code = EXIT_OK if final_status == "passed" else EXIT_SKIPPED
        return _finalize(
            summary,
            artifact_dir,
            exit_code,
            client,
            args,
            switched_workdir,
            original_workdir,
            active_native_conversation_id,
            probe_workspace=current_workdir,
            probe_dir=probe_dir,
        )
    except (ApiError, RuntimeError) as exc:
        _add_check(summary, "smoke_run", "failed", error=_error_payload(exc))
        summary["status"] = "failed"
        exit_code = EXIT_FAILED
        return _finalize(
            summary,
            artifact_dir,
            exit_code,
            client,
            args,
            switched_workdir,
            original_workdir,
            active_native_conversation_id,
            probe_workspace=current_workdir,
            probe_dir=probe_dir,
        )


def _run_turn(
    client: ApiClient,
    *,
    args: argparse.Namespace,
    alias: str,
    artifact_dir: Path,
    turn_name: str,
    message: str,
) -> dict[str, Any]:
    events = client.stream_sse(
        f"/api/bots/{alias}/chat/stream",
        payload={"message": message, "execution_mode": "native_agent"},
        timeout=args.turn_timeout,
    )
    event_path = artifact_dir / f"{turn_name}.events.json"
    event_path.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    turn_id = ""
    assistant_message_id = ""
    done_output = ""
    error_payload: dict[str, Any] | None = None
    for event in events:
        event_name = str(event.get("event") or "")
        data = event.get("data")
        if isinstance(data, dict):
            if str(data.get("turn_id") or "").strip():
                turn_id = str(data.get("turn_id") or "").strip()
            if str(data.get("assistant_message_id") or "").strip():
                assistant_message_id = str(data.get("assistant_message_id") or "").strip()
            if event_name == "done":
                done_output = str(data.get("output") or "")
            elif event_name == "error":
                error_payload = data
    if error_payload is not None:
        raise RuntimeError(f"{turn_name} 返回 error: {json.dumps(error_payload, ensure_ascii=False)}")
    if not turn_id:
        raise RuntimeError(f"{turn_name} 未拿到 turn_id")
    return {
        "turn_id": turn_id,
        "assistant_message_id": assistant_message_id,
        "done_output": done_output.strip(),
        "event_count": len(events),
        "artifact": str(event_path),
    }


def _try_changes(
    *,
    client: ApiClient,
    alias: str,
    conversation_id: str,
    turn_id: str,
) -> tuple[dict[str, Any], str]:
    try:
        response = client.request_json(
            "GET",
            f"/api/bots/{alias}/native-agent/history/changes",
            query={"conversation_id": conversation_id, "turn_id": turn_id},
        )
        data = ((response.payload or {}).get("data") or {})
        files = data.get("files")
        if not isinstance(files, list):
            raise RuntimeError("changes 缺少 files")
        return {"supported": True, "data": data}, "passed"
    except ApiError as exc:
        if exc.status == 404 and not exc.code:
            return {"supported": False, "reason": "route_missing", "error": exc.to_dict()}, "skipped"
        return {"supported": True, "error": exc.to_dict()}, "failed"
    except RuntimeError as exc:
        return {"supported": True, "error": _error_payload(exc)}, "failed"


def _try_diff(
    *,
    client: ApiClient,
    alias: str,
    conversation_id: str,
    turn_id: str,
    changes_result: dict[str, Any],
    preferred_path: str,
) -> tuple[dict[str, Any], str]:
    if not changes_result.get("supported"):
        return {"supported": False, "reason": "changes_unavailable"}, "skipped"
    files = (((changes_result.get("data") or {}).get("files")) or [])
    if not isinstance(files, list) or not files:
        return {"supported": True, "reason": "no_changed_files"}, "failed"
    candidate = preferred_path
    available = {
        str(item.get("path") or ""): item
        for item in files
        if isinstance(item, dict) and str(item.get("path") or "")
    }
    if candidate not in available:
        candidate = next(iter(available.keys()), "")
    if not candidate:
        return {"supported": True, "reason": "no_diff_candidate"}, "failed"
    try:
        response = client.request_json(
            "GET",
            f"/api/bots/{alias}/native-agent/history/diff",
            query={"conversation_id": conversation_id, "turn_id": turn_id, "path": candidate},
        )
        data = ((response.payload or {}).get("data") or {})
        diff_text = str(data.get("diff") or "")
        if not diff_text.strip():
            raise RuntimeError("diff 为空")
        return {
            "supported": True,
            "path": candidate,
            "truncated": bool(data.get("truncated")),
            "diff_bytes": len(diff_text.encode("utf-8")),
        }, "passed"
    except ApiError as exc:
        if exc.status == 404 and not exc.code:
            return {"supported": False, "reason": "route_missing", "error": exc.to_dict()}, "skipped"
        return {"supported": True, "path": candidate, "error": exc.to_dict()}, "failed"
    except RuntimeError as exc:
        return {"supported": True, "path": candidate, "error": _error_payload(exc)}, "failed"


def _finalize(
    summary: dict[str, Any],
    artifact_dir: Path,
    exit_code: int,
    client: ApiClient,
    args: argparse.Namespace,
    switched_workdir: bool,
    original_workdir: str,
    active_native_conversation_id: str,
    *,
    probe_workspace: str = "",
    probe_dir: str = "",
) -> int:
    if probe_workspace and probe_dir and not bool(getattr(args, "keep_probe", False)):
        try:
            cleaned = _cleanup_probe_dir(Path(probe_workspace), probe_dir)
            _add_check(summary, "cleanup_probe_dir", "passed" if cleaned else "skipped", probe_dir=probe_dir)
        except RuntimeError as exc:
            _add_check(summary, "cleanup_probe_dir", "failed", error=_error_payload(exc), probe_dir=probe_dir)
            summary["notes"].append("探针目录未清理，请手工确认")
            if summary.get("status") == "passed":
                summary["status"] = "partial"
                exit_code = EXIT_SKIPPED

    if active_native_conversation_id and summary.get("status") in {"passed", "partial"} and not switched_workdir:
        try:
            client.request_json(
                "POST",
                f"/api/bots/{args.alias}/conversations/{active_native_conversation_id}/select",
                payload={"execution_mode": "native_agent"},
            )
            _add_check(summary, "restore_active_native_conversation", "passed", conversation_id=active_native_conversation_id)
        except ApiError as exc:
            _add_check(summary, "restore_active_native_conversation", "skipped", error=exc.to_dict())

    if switched_workdir and not args.keep_workdir and original_workdir:
        try:
            client.request_json(
                "PATCH",
                f"/api/admin/bots/{args.alias}/workdir",
                payload={"working_dir": original_workdir, "force_reset": True},
            )
            _add_check(summary, "restore_workdir", "passed", working_dir=original_workdir, force_reset=True)
        except ApiError as exc:
            _add_check(summary, "restore_workdir", "failed", error=exc.to_dict())
            summary["notes"].append("bot 工作目录未恢复；需手工确认")
            if summary.get("status") == "passed":
                summary["status"] = "partial"
                exit_code = EXIT_SKIPPED

    summary["finished_at"] = datetime.now(UTC).isoformat()
    _write_summary(artifact_dir, summary)
    _print_summary(summary)
    return exit_code


def _cleanup_probe_dir(workspace_path: Path, probe_dir: str) -> bool:
    root = workspace_path.expanduser().resolve()
    target = (root / probe_dir).resolve()
    if target == root or root not in target.parents:
        raise RuntimeError(f"拒绝清理工作区外路径: {target}")
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def _verify_text_file(path: Path, expected: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"缺少文件: {path}")
    actual = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if actual != expected:
        raise RuntimeError(f"文件内容不符: {path} -> {actual!r} != {expected!r}")


def _add_check(summary: dict[str, Any], name: str, status: str, **extra: Any) -> None:
    summary.setdefault("checks", []).append({"name": name, "status": status, **extra})


def _resolve_artifact_dir(raw: str, run_id: str) -> Path:
    candidate = str(raw or "").strip()
    if candidate:
        return Path(candidate).expanduser().resolve()
    return Path(tempfile.gettempdir()).resolve() / "tcb-smoke-native-shadow-history" / run_id


def _write_summary(artifact_dir: Path, summary: dict[str, Any]) -> None:
    (artifact_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_summary(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_error_fields(parsed: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(parsed, dict):
        return "", ""
    error_value = parsed.get("error")
    code = ""
    message = ""
    if isinstance(error_value, dict):
        code = str(error_value.get("code") or "").strip()
        message = str(error_value.get("message") or error_value.get("detail") or "").strip()
    elif error_value is not None:
        message = str(error_value or "").strip()
    if not code:
        code = str(parsed.get("code") or "").strip()
    if not message:
        message = str(parsed.get("message") or parsed.get("detail") or "").strip()
    if not message and isinstance(parsed.get("data"), dict):
        message = str(parsed["data"].get("message") or "").strip()
    return code, message


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ApiError):
        return exc.to_dict()
    return {"message": str(exc)}


if __name__ == "__main__":
    sys.exit(main())
