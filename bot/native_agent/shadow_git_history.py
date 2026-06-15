from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from bot.runtime_paths import get_native_agent_data_dir

SHADOW_HISTORY_VERSION = 1
GIT_COMMAND_TIMEOUT_SECONDS = 30.0
MAX_TRACKED_FILES = 20000
SHADOW_GIT_AUTHOR_NAME = "Orbit Workspace History"
SHADOW_GIT_AUTHOR_EMAIL = "orbit@local"
EXCLUDE_DIR_NAMES = frozenset({
    ".git",
    ".tcb",
    ".worktrees",
    ".updates",
    ".tmp",
    ".codegraph",
    ".plugins",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".next",
    ".turbo",
    "coverage",
    "dist",
    "build",
    "tmp",
})
EXCLUDE_PATTERNS = (
    ".git/",
    ".tcb/",
    ".release-local/artifacts/",
    ".release-local/stage/",
    ".release-local/portable-win/artifacts/",
    ".release-local/portable-win/downloads/",
    ".release-local/portable-win/stage/",
    ".worktrees/",
    ".updates/",
    ".tmp/",
    ".codegraph/",
    ".plugins/",
    "node_modules/",
    "venv/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".cache/",
    ".next/",
    ".turbo/",
    "coverage/",
    "dist/",
    "build/",
    "tmp/",
    ".env",
    ".env.*",
    "*.pyc",
    "*.pyo",
)
STATUS_LABELS = {
    "A": "added",
    "D": "deleted",
    "M": "modified",
    "T": "modified",
    "R": "renamed",
    "C": "copied",
}
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ShadowHistoryStatus:
    head: str
    clean: bool
    manual_change_count: int
    degraded: bool = False
    message: str = ""
    locked_file_count: int = 0
    linear_index: int = 0


class ShadowGitHistory:
    def __init__(
        self,
        *,
        root_dir: Path | str | None = None,
        timeout_seconds: float = GIT_COMMAND_TIMEOUT_SECONDS,
        max_tracked_files: int = MAX_TRACKED_FILES,
    ) -> None:
        self.root_dir = Path(root_dir) if root_dir is not None else get_native_agent_data_dir() / "workspace-history"
        self.timeout_seconds = max(0.1, float(timeout_seconds or GIT_COMMAND_TIMEOUT_SECONDS))
        self.max_tracked_files = max(1, int(max_tracked_files or MAX_TRACKED_FILES))

    def status(self, *, cwd: Path | str, conversation_id: str) -> ShadowHistoryStatus:
        context = self._context(cwd, conversation_id)
        self._ensure_repo(context)
        head = self._head(context)
        count = self._manual_change_count(context)
        return ShadowHistoryStatus(head=head, clean=count == 0, manual_change_count=count)

    def snapshot(self, *, cwd: Path | str, conversation_id: str, label: str) -> ShadowHistoryStatus:
        context = self._context(cwd, conversation_id)
        self._ensure_repo(context)
        tracked_count = self._tracked_file_budget(context)
        if tracked_count > self.max_tracked_files:
            return ShadowHistoryStatus(
                head=self._head(context),
                clean=False,
                manual_change_count=tracked_count,
                degraded=True,
                message="workspace history 文件数量超过预算",
            )
        self._git(context, "add", "-A", "--", ".")
        has_head = bool(self._head(context))
        staged = self._has_staged_changes(context)
        if not has_head or staged:
            commit_args = ["commit"]
            if not staged:
                commit_args.append("--allow-empty")
            commit_args.extend(["-m", self._commit_message(label)])
            self._git(context, *commit_args)
        head = self._head(context)
        return ShadowHistoryStatus(head=head, clean=True, manual_change_count=0)

    def record_completed_turn(
        self,
        *,
        cwd: Path | str,
        conversation_id: str,
        turn_id: str,
        before_head: str,
        pi_session_id: str = "",
    ) -> ShadowHistoryStatus:
        context = self._context(cwd, conversation_id)
        after = self.snapshot(cwd=context.cwd, conversation_id=context.conversation_id, label=f"turn {turn_id} after")
        if after.degraded:
            return after
        state = self._read_state(context)
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            return ShadowHistoryStatus(
                head=after.head,
                clean=False,
                manual_change_count=0,
                degraded=True,
                message="turn_id 为空",
            )
        turns = [item for item in state.get("turns", []) if isinstance(item, dict)]
        existing = next((item for item in turns if str(item.get("turn_id") or "") == normalized_turn_id), None)
        if existing is None:
            active_indexes = [
                int(item.get("linear_index") or 0)
                for item in turns
                if not str(item.get("discarded_at") or "").strip()
            ]
            linear_index = max(active_indexes or [0]) + 1
            existing = {
                "turn_id": normalized_turn_id,
                "linear_index": linear_index,
                "created_at": _utc_now(),
                "status": "active",
                "discarded_at": "",
            }
            turns.append(existing)
        else:
            linear_index = int(existing.get("linear_index") or 0)
            existing["status"] = "active"
            existing["discarded_at"] = ""
        existing["before_head"] = str(before_head or "").strip() or self._previous_active_head(turns, normalized_turn_id)
        existing["after_head"] = after.head
        existing["workspace_history_head"] = after.head
        existing["pi_session_id"] = str(pi_session_id or "").strip()
        state["turns"] = turns
        state["updated_at"] = _utc_now()
        self._write_state(context, state)
        return ShadowHistoryStatus(head=after.head, clean=True, manual_change_count=0, linear_index=linear_index)

    def rollback(self, *, cwd: Path | str, conversation_id: str, target_head: str) -> ShadowHistoryStatus:
        context = self._context(cwd, conversation_id)
        self._ensure_repo(context)
        normalized_head = str(target_head or "").strip()
        if not normalized_head:
            return ShadowHistoryStatus(head="", clean=False, manual_change_count=0, degraded=True, message="目标 head 为空")
        state = self._read_state(context)
        target = self._turn_for_head(state, normalized_head)
        if target is None:
            return ShadowHistoryStatus(
                head=self._head(context),
                clean=False,
                manual_change_count=0,
                degraded=True,
                message="目标工作区记录不在当前会话链",
            )
        if self._manual_change_count(context) > 0:
            safety = self.snapshot(cwd=context.cwd, conversation_id=context.conversation_id, label="rollback safety")
            if safety.degraded:
                return safety
        self._git(context, "reset", "--hard", normalized_head)
        self._mark_discarded_after(state, int(target.get("linear_index") or 0))
        state["updated_at"] = _utc_now()
        self._write_state(context, state)
        return ShadowHistoryStatus(head=normalized_head, clean=True, manual_change_count=0)

    def changes(self, *, cwd: Path | str, conversation_id: str, turn_id: str) -> dict[str, Any]:
        context = self._context(cwd, conversation_id)
        self._ensure_repo(context)
        turn = self._active_turn(context, turn_id)
        base_head = str(turn.get("before_head") or "").strip()
        head = str(turn.get("after_head") or turn.get("workspace_history_head") or "").strip()
        files = self._diff_files(context, base_head, head) if base_head and head else []
        return {
            "conversation_id": context.conversation_id,
            "turn_id": str(turn.get("turn_id") or ""),
            "linear_index": int(turn.get("linear_index") or 0),
            "base_head": base_head,
            "head": head,
            "files": files,
        }

    def diff(
        self,
        *,
        cwd: Path | str,
        conversation_id: str,
        turn_id: str,
        path: str,
    ) -> dict[str, Any]:
        normalized_path = _normalize_relative_path(path)
        changes = self.changes(cwd=cwd, conversation_id=conversation_id, turn_id=turn_id)
        file_record = next(
            (
                item
                for item in changes["files"]
                if str(item.get("path") or "") == normalized_path
            ),
            None,
        )
        if file_record is None:
            raise KeyError(normalized_path)
        context = self._context(cwd, conversation_id)
        result = self._git(
            context,
            "diff",
            "--find-renames",
            "--binary",
            str(changes["base_head"]),
            str(changes["head"]),
            "--",
            normalized_path,
            check=False,
        )
        return {
            "conversation_id": context.conversation_id,
            "turn_id": str(changes["turn_id"] or ""),
            "path": normalized_path,
            "old_path": str(file_record.get("old_path") or ""),
            "status": str(file_record.get("status") or "unknown"),
            "binary": bool(file_record.get("binary", False)),
            "base_head": str(changes["base_head"] or ""),
            "head": str(changes["head"] or ""),
            "diff": result.stdout or "",
            "truncated": False,
        }

    def _context(self, cwd: Path | str, conversation_id: str) -> "_ShadowContext":
        resolved_cwd = Path(cwd or ".").expanduser().resolve()
        normalized_conversation_id = str(conversation_id or "").strip()
        if not normalized_conversation_id:
            raise ValueError("conversation_id is required")
        workspace_hash = hashlib.sha256(str(resolved_cwd).encode("utf-8", errors="ignore")).hexdigest()[:24]
        conversation_segment = _safe_segment(normalized_conversation_id)
        base_dir = self.root_dir / workspace_hash / conversation_segment
        return _ShadowContext(
            cwd=resolved_cwd,
            conversation_id=normalized_conversation_id,
            base_dir=base_dir,
            git_dir=base_dir / "repo.git",
            state_path=base_dir / "state.json",
        )

    def _ensure_repo(self, context: "_ShadowContext") -> None:
        context.base_dir.mkdir(parents=True, exist_ok=True)
        if not context.git_dir.is_dir():
            self._run(("git", "init", "--bare", str(context.git_dir)), cwd=context.base_dir)
        exclude_path = context.git_dir / "info" / "exclude"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8", errors="ignore") if exclude_path.is_file() else ""
        patterns = list(EXCLUDE_PATTERNS)
        shadow_pattern = self._shadow_root_exclude_pattern(context)
        if shadow_pattern:
            patterns.append(shadow_pattern)
        additions = [pattern for pattern in patterns if pattern not in existing.splitlines()]
        if additions:
            prefix = "" if existing.endswith("\n") or not existing else "\n"
            exclude_path.write_text(existing + prefix + "\n".join(additions) + "\n", encoding="utf-8")
        state = self._read_state(context)
        if not state:
            self._write_state(context, self._initial_state(context))

    def _git(self, context: "_ShadowContext", *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = (
            "git",
            "--git-dir",
            str(context.git_dir),
            "--work-tree",
            str(context.cwd),
            "-c",
            f"user.name={SHADOW_GIT_AUTHOR_NAME}",
            "-c",
            f"user.email={SHADOW_GIT_AUTHOR_EMAIL}",
            "-c",
            "core.autocrlf=false",
            *args,
        )
        return self._run(command, cwd=context.cwd, check=check)

    def _run(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
            check=False,
        )
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "git command failed").strip()
            raise RuntimeError(_safe_message(message, default="workspace history git 执行失败"))
        return result

    def _head(self, context: "_ShadowContext") -> str:
        result = self._git(context, "rev-parse", "--verify", "HEAD", check=False)
        if result.returncode != 0:
            return ""
        return str(result.stdout or "").strip()

    def _has_staged_changes(self, context: "_ShadowContext") -> bool:
        result = self._git(context, "diff", "--cached", "--quiet", "--", ".", check=False)
        return result.returncode == 1

    def _manual_change_count(self, context: "_ShadowContext") -> int:
        result = self._git(context, "status", "--porcelain", "--untracked-files=all", "--", ".", check=False)
        if result.returncode != 0:
            return 0
        return sum(1 for line in str(result.stdout or "").splitlines() if line.strip())

    def _tracked_file_budget(self, context: "_ShadowContext") -> int:
        result = self._git(context, "ls-files", "-co", "--exclude-standard", "--", ".", check=False)
        if result.returncode == 0:
            return sum(1 for line in str(result.stdout or "").splitlines() if line.strip())
        count = 0
        shadow_root = self.root_dir.expanduser().resolve()
        for root, dirs, files in os.walk(context.cwd):
            root_path = Path(root)
            dirs[:] = [
                name
                for name in dirs
                if name not in EXCLUDE_DIR_NAMES
                and (root_path / name).resolve() != shadow_root
            ]
            count += len(files)
            if count > self.max_tracked_files:
                return count
        return count

    def _shadow_root_exclude_pattern(self, context: "_ShadowContext") -> str:
        try:
            relative = self.root_dir.expanduser().resolve().relative_to(context.cwd)
        except ValueError:
            return ""
        value = _to_posix(str(relative)).strip("/")
        if not value:
            return ""
        return f"{value}/"

    def _read_state(self, context: "_ShadowContext") -> dict[str, Any]:
        if not context.state_path.is_file():
            return {}
        try:
            parsed = json.loads(context.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _write_state(self, context: "_ShadowContext", state: dict[str, Any]) -> None:
        context.base_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SHADOW_HISTORY_VERSION,
            "conversation_id": context.conversation_id,
            "cwd": str(context.cwd),
            "created_at": str(state.get("created_at") or _utc_now()),
            "updated_at": str(state.get("updated_at") or _utc_now()),
            "turns": [item for item in state.get("turns", []) if isinstance(item, dict)],
        }
        tmp = context.state_path.with_name(f"{context.state_path.name}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(context.state_path)

    def _initial_state(self, context: "_ShadowContext") -> dict[str, Any]:
        now = _utc_now()
        return {
            "version": SHADOW_HISTORY_VERSION,
            "conversation_id": context.conversation_id,
            "cwd": str(context.cwd),
            "created_at": now,
            "updated_at": now,
            "turns": [],
        }

    def _previous_active_head(self, turns: list[dict[str, Any]], turn_id: str) -> str:
        candidates = [
            item
            for item in turns
            if str(item.get("turn_id") or "") != turn_id and not str(item.get("discarded_at") or "").strip()
        ]
        candidates.sort(key=lambda item: int(item.get("linear_index") or 0), reverse=True)
        if not candidates:
            return ""
        return str(candidates[0].get("after_head") or candidates[0].get("workspace_history_head") or "").strip()

    def _turn_for_head(self, state: dict[str, Any], target_head: str) -> dict[str, Any] | None:
        active = [
            item
            for item in state.get("turns", [])
            if isinstance(item, dict) and not str(item.get("discarded_at") or "").strip()
        ]
        for item in active:
            if str(item.get("after_head") or item.get("workspace_history_head") or "").strip() == target_head:
                return item
        return None

    def _active_turn(self, context: "_ShadowContext", turn_id: str) -> dict[str, Any]:
        normalized_turn_id = str(turn_id or "").strip()
        state = self._read_state(context)
        for item in state.get("turns", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("turn_id") or "") != normalized_turn_id:
                continue
            if str(item.get("discarded_at") or "").strip():
                raise KeyError(normalized_turn_id)
            return item
        raise KeyError(normalized_turn_id)

    def _mark_discarded_after(self, state: dict[str, Any], linear_index: int) -> None:
        now = _utc_now()
        for item in state.get("turns", []):
            if not isinstance(item, dict):
                continue
            if int(item.get("linear_index") or 0) <= int(linear_index):
                continue
            if str(item.get("discarded_at") or "").strip():
                continue
            item["status"] = "discarded"
            item["discarded_at"] = now

    def _diff_files(self, context: "_ShadowContext", base_head: str, head: str) -> list[dict[str, Any]]:
        status_result = self._git(
            context,
            "diff",
            "--name-status",
            "--find-renames",
            base_head,
            head,
            "--",
            ".",
            check=False,
        )
        if status_result.returncode != 0:
            return []
        numstat = self._numstat_by_path(context, base_head, head)
        files: list[dict[str, Any]] = []
        for line in str(status_result.stdout or "").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            code = parts[0].strip()
            status_key = code[:1]
            old_path = ""
            if status_key in {"R", "C"} and len(parts) >= 3:
                old_path = _to_posix(parts[1])
                path = _to_posix(parts[2])
            elif len(parts) >= 2:
                path = _to_posix(parts[1])
            else:
                continue
            stats = numstat.get(path) or {"additions": 0, "deletions": 0, "binary": False}
            files.append({
                "path": path,
                "old_path": old_path,
                "status": STATUS_LABELS.get(status_key, "modified"),
                "additions": int(stats.get("additions") or 0),
                "deletions": int(stats.get("deletions") or 0),
                "binary": bool(stats.get("binary", False)),
            })
        return files

    def _numstat_by_path(self, context: "_ShadowContext", base_head: str, head: str) -> dict[str, dict[str, Any]]:
        result = self._git(context, "diff", "--numstat", "--find-renames", base_head, head, "--", ".", check=False)
        stats: dict[str, dict[str, Any]] = {}
        if result.returncode != 0:
            return stats
        for line in str(result.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            raw_additions, raw_deletions, raw_path = parts[0], parts[1], parts[-1]
            path = _to_posix(_rename_numstat_path(raw_path))
            binary = raw_additions == "-" or raw_deletions == "-"
            stats[path] = {
                "additions": 0 if binary else _safe_int(raw_additions),
                "deletions": 0 if binary else _safe_int(raw_deletions),
                "binary": binary,
            }
        return stats

    def _commit_message(self, label: str) -> str:
        normalized = str(label or "").strip()[:120]
        return normalized or "workspace snapshot"


@dataclass(frozen=True)
class _ShadowContext:
    cwd: Path
    conversation_id: str
    base_dir: Path
    git_dir: Path
    state_path: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_segment(value: str) -> str:
    candidate = _SAFE_SEGMENT_RE.sub("-", str(value or "").strip()).strip(".-")
    if candidate:
        return candidate[:80]
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()[:24]


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _safe_message(message: str, *, default: str) -> str:
    text = str(message or "").strip()
    if not text:
        return default
    if ":\\" in text or ":/" in text or "\\\\" in text:
        return default
    return text[:240]


def _to_posix(path: str) -> str:
    return str(path or "").replace("\\", "/")


def _rename_numstat_path(path: str) -> str:
    raw = str(path or "")
    if " => " not in raw:
        return raw
    return raw.split(" => ", 1)[1].rstrip("}")


def _normalize_relative_path(path: str) -> str:
    normalized = _to_posix(str(path or "").strip()).strip("/")
    if not normalized:
        raise ValueError("path is required")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("invalid path")
    return str(pure)
