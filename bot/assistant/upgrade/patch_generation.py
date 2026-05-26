from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from bot.assistant.home import AssistantHome
from bot.assistant.upgrade.service import ensure_upgrade_repo_clean, read_upgrade_metadata, write_upgrade_metadata
from bot.assistant.upgrade.diff import parse_patch_files
from bot.cli import build_cli_command, normalize_cli_type, resolve_cli_executable
from bot import config
from bot.cli_params import CliParamsConfig, with_global_extra_args
from bot.platform.processes import build_hidden_process_kwargs

SENSITIVE_PATH_PATTERNS = (
    ".env",
    ".env.",
    ".pem",
    ".key",
    "id_rsa",
    "id_ed25519",
    "secret",
    "token",
    ".web_auth_secret.json",
    ".web_users.json",
    ".web_register_codes.json",
)
PATCH_SIZE_LIMIT_BYTES = 2 * 1024 * 1024
PATCH_FILE_LIMIT = 100
GENERATOR_TIMEOUT_SECONDS = 600
PatchGenerationEventCallback = Callable[[dict[str, Any]], None]
_ACTIVE_PATCH_GENERATIONS: set[str] = set()
_ACTIVE_PATCH_GENERATIONS_LOCK = threading.Lock()


def _run_git(cwd: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            ["git", *args],
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def _write_lf_text(path: Path, text: str) -> None:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    path.write_bytes(normalized.encode("utf-8"))


def _emit_event(
    event_callback: PatchGenerationEventCallback | None,
    event_type: str,
    **payload: Any,
) -> None:
    if event_callback is None:
        return
    event_callback({"type": event_type, **payload})


def _summarize_completed_process(
    returncode: int,
    started_at: float,
    *,
    stdout: str = "",
    stderr: str = "",
) -> str:
    parts = [
        f"Exit code: {returncode}",
        f"Wall time: {max(time.perf_counter() - started_at, 0):.1f}s",
    ]
    if stdout.strip():
        parts.append(stdout.strip()[-500:])
    if stderr.strip():
        parts.append(stderr.strip()[-500:])
    return "\n".join(parts)


def _run_git_traced(
    cwd: Path,
    args: list[str],
    *,
    event_callback: PatchGenerationEventCallback | None = None,
    call_id: str = "",
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    _emit_event(
        event_callback,
        "trace",
        event={
            "kind": "tool_call",
            "summary": "git " + " ".join(args),
            "tool_name": "git",
            "call_id": call_id,
        },
    )
    started_at = time.perf_counter()
    try:
        completed = _run_git(cwd, args, check=check)
    except subprocess.CalledProcessError as exc:
        _emit_event(
            event_callback,
            "trace",
            event={
                "kind": "tool_result",
                "summary": _summarize_completed_process(
                    exc.returncode,
                    started_at,
                    stdout=exc.output or "",
                    stderr=exc.stderr or "",
                ),
                "tool_name": "git",
                "call_id": call_id,
            },
        )
        raise
    _emit_event(
        event_callback,
        "trace",
        event={
            "kind": "tool_result",
            "summary": _summarize_completed_process(
                completed.returncode,
                started_at,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            ),
            "tool_name": "git",
            "call_id": call_id,
        },
    )
    return completed


def _build_generation_prompt(proposal: dict[str, Any]) -> str:
    return (
        "你在隔离 git worktree 中。目标是按下方 proposal 实现最小代码改动。\n\n"
        "约束：\n"
        "- 不要 commit。\n"
        "- 不要 push。\n"
        "- 不要修改原目标工程工作区。\n"
        "- 不要修改 .assistant/upgrades 目录。\n"
        "- 不要读取、打印或写入密钥、token、cookie、密码。\n"
        "- 避免修改 .env、*.pem、id_rsa、*secret* 等敏感文件。\n"
        "- 优先沿用现有代码风格和测试。\n"
        "- 完成后简要说明改了哪些文件、运行了哪些验证。\n\n"
        f"Proposal:\n{proposal.get('title') or proposal.get('id')}\n{proposal.get('body') or ''}\n"
    )


def _run_generator_cli(worktree_path: Path, prompt: str, metadata: dict[str, Any]) -> dict[str, Any]:
    cli_type = normalize_cli_type(str(metadata.get("cli_type") or "codex"))
    cli_path = str(metadata.get("cli_path") or cli_type)
    resolved_cli = resolve_cli_executable(cli_path, str(worktree_path))
    if resolved_cli is None:
        raise FileNotFoundError(cli_path)
    env = os.environ.copy()
    params_config = with_global_extra_args(CliParamsConfig(), config.CLI_GLOBAL_EXTRA_ARGS)
    cmd, use_stdin = build_cli_command(
        cli_type=cli_type,
        resolved_cli=resolved_cli,
        user_text=prompt,
        env=env,
        params_config=params_config,
        working_dir=str(worktree_path),
    )
    started_at = time.perf_counter()
    completed = subprocess.run(
        cmd,
        input=(prompt + "\n") if use_stdin else None,
        cwd=worktree_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GENERATOR_TIMEOUT_SECONDS,
        **build_hidden_process_kwargs(),
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            cmd,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return {
        "status": "succeeded",
        "elapsed_seconds": int(round(time.perf_counter() - started_at)),
        "stdout_tail": (completed.stdout or "")[-2000:],
        "stderr_tail": (completed.stderr or "")[-2000:],
    }


def _is_sensitive_path(path: str) -> bool:
    lowered = str(path or "").replace("\\", "/").lower()
    name = Path(lowered).name
    for marker in SENSITIVE_PATH_PATTERNS:
        token = marker.lower()
        if token.startswith(".") and token.endswith("."):
            if name.startswith(token):
                return True
            continue
        if token.startswith(".") and "/" not in token and name == token:
            return True
        if token in lowered:
            return True
    return False


def _summarize_patch(diff_text: str) -> dict[str, Any]:
    files = parse_patch_files(diff_text)
    changed_files = [str(item.get("path") or "") for item in files if str(item.get("path") or "")]
    return {
        "changed_files": changed_files,
        "additions": sum(int(item.get("additions") or 0) for item in files),
        "deletions": sum(int(item.get("deletions") or 0) for item in files),
        "sensitive_hits": [path for path in changed_files if _is_sensitive_path(path)],
        "file_count": len(files),
    }


def _clear_pending_outputs(home: AssistantHome, proposal_id: str) -> None:
    for path in (
        home.root / "upgrades" / "pending" / f"{proposal_id}.patch",
        home.root / "upgrades" / "pending" / f"{proposal_id}.json",
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def _remove_worktree(target_repo_root: Path, worktree_path: Path) -> None:
    _run_git(target_repo_root, ["worktree", "remove", "--force", str(worktree_path)], check=False)
    _run_git(target_repo_root, ["worktree", "prune"], check=False)
    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)


def _generation_slot_key(home: AssistantHome, proposal_id: str) -> str:
    return f"{home.root.resolve()}::{proposal_id}"


def _mark_generation_active(home: AssistantHome, proposal_id: str) -> bool:
    key = _generation_slot_key(home, proposal_id)
    with _ACTIVE_PATCH_GENERATIONS_LOCK:
        if key in _ACTIVE_PATCH_GENERATIONS:
            return False
        _ACTIVE_PATCH_GENERATIONS.add(key)
    return True


def _clear_generation_active(home: AssistantHome, proposal_id: str) -> None:
    key = _generation_slot_key(home, proposal_id)
    with _ACTIVE_PATCH_GENERATIONS_LOCK:
        _ACTIVE_PATCH_GENERATIONS.discard(key)


def _is_generation_active(home: AssistantHome, proposal_id: str) -> bool:
    key = _generation_slot_key(home, proposal_id)
    with _ACTIVE_PATCH_GENERATIONS_LOCK:
        return key in _ACTIVE_PATCH_GENERATIONS


def _recover_generation_slot(
    home: AssistantHome,
    proposal_id: str,
    *,
    target_repo_root: Path,
    worktree_path: Path,
    regenerate: bool,
    event_callback: PatchGenerationEventCallback | None,
) -> None:
    pending_patch = home.root / "upgrades" / "pending" / f"{proposal_id}.patch"
    pending_metadata_path = home.root / "upgrades" / "pending" / f"{proposal_id}.json"
    pending_metadata = read_upgrade_metadata(home, proposal_id, "pending")
    has_pending_outputs = pending_patch.exists() or pending_metadata_path.exists()
    lifecycle = str((pending_metadata or {}).get("lifecycle") or "").strip().lower()

    if regenerate:
        if has_pending_outputs or worktree_path.exists():
            _emit_event(
                event_callback,
                "status",
                phase="recover",
                message="清理旧 patch 产物",
                lifecycle="running",
            )
        _clear_pending_outputs(home, proposal_id)
        if worktree_path.exists():
            _remove_worktree(target_repo_root, worktree_path)
        return

    if lifecycle == "running":
        if _is_generation_active(home, proposal_id):
            raise FileExistsError(str(pending_metadata_path if pending_metadata_path.exists() else worktree_path))
        _emit_event(
            event_callback,
            "status",
            phase="recover",
            message="清理残留运行态",
            lifecycle="running",
        )
        _clear_pending_outputs(home, proposal_id)
        if worktree_path.exists():
            _remove_worktree(target_repo_root, worktree_path)
        return

    if lifecycle == "failed":
        _emit_event(
            event_callback,
            "status",
            phase="recover",
            message="清理上次失败记录",
            lifecycle="failed",
        )
        _clear_pending_outputs(home, proposal_id)
        if worktree_path.exists():
            _remove_worktree(target_repo_root, worktree_path)
        return

    if worktree_path.exists() and not has_pending_outputs:
        if _is_generation_active(home, proposal_id):
            raise FileExistsError(str(worktree_path))
        _emit_event(
            event_callback,
            "status",
            phase="recover",
            message="清理残留 worktree",
            lifecycle="running",
        )
        _remove_worktree(target_repo_root, worktree_path)
        return

    if has_pending_outputs:
        raise FileExistsError(str(pending_patch if pending_patch.exists() else pending_metadata_path))


def _build_generation_metadata(
    proposal_id: str,
    *,
    target: dict[str, Any],
    target_repo_root: Path,
    base_commit: str,
    worktree_path: Path,
    generated_by: str,
    lifecycle: str,
    generator_status: str,
    error: str = "",
    generator_elapsed_seconds: int = 0,
    changed_files: list[str] | None = None,
    additions: int = 0,
    deletions: int = 0,
    sensitive_hits: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": proposal_id,
        "proposal_id": proposal_id,
        "state": "pending",
        "lifecycle": lifecycle,
        "target_alias": str(target.get("alias") or ""),
        "target_working_dir": str(target.get("working_dir") or ""),
        "target_repo_root": str(target_repo_root),
        "base_commit": base_commit,
        "worktree_path": str(worktree_path),
        "patch_path": f"upgrades/pending/{proposal_id}.patch",
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": str(generated_by),
        "generator": {
            "cli_type": str(target.get("cli_type") or ""),
            "cli_path": str(target.get("cli_path") or ""),
            "status": generator_status,
            "elapsed_seconds": int(generator_elapsed_seconds or 0),
        },
        "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
        "sensitive_hits": list(sensitive_hits or []),
        "changed_files": list(changed_files or []),
        "additions": int(additions or 0),
        "deletions": int(deletions or 0),
        **({"error": error} if error else {}),
    }


def _normalize_error_message(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return str(exc.stderr or exc.output or exc)
    return str(exc)


def generate_pending_patch(
    home: AssistantHome,
    proposal: dict[str, Any],
    *,
    target: dict[str, Any],
    generated_by: str,
    regenerate: bool = False,
    event_callback: PatchGenerationEventCallback | None = None,
) -> dict[str, Any]:
    proposal_id = str(proposal.get("id") or "").strip()
    if not proposal_id:
        raise ValueError("missing_proposal_id")
    if proposal.get("status") != "approved":
        raise PermissionError("proposal_not_approved")
    target_repo_root = Path(str(target.get("repo_root") or "")).resolve()
    base_commit = str(target.get("head") or "").strip()
    if not base_commit:
        raise ValueError("upgrade_target_no_head")
    ensure_upgrade_repo_clean(target_repo_root)

    worktree_path = home.root / "upgrades" / "worktrees" / proposal_id
    pending_patch = home.root / "upgrades" / "pending" / f"{proposal_id}.patch"

    log_path = home.root / "upgrades" / "logs" / f"{proposal_id}.generate.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(event: str, **payload: Any) -> None:
        row = {"event": event, "created_at": datetime.now(UTC).isoformat(), **payload}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")

    log("started", proposal_id=proposal_id)
    _emit_event(event_callback, "status", phase="setup", message="准备生成 patch", lifecycle="running")
    _emit_event(event_callback, "log", text="开始生成 patch")
    _recover_generation_slot(
        home,
        proposal_id,
        target_repo_root=target_repo_root,
        worktree_path=worktree_path,
        regenerate=regenerate,
        event_callback=event_callback,
    )
    if not _mark_generation_active(home, proposal_id):
        raise FileExistsError(str(home.root / "upgrades" / "pending" / f"{proposal_id}.json"))

    generator_elapsed_seconds = 0
    try:
        running_metadata = _build_generation_metadata(
            proposal_id,
            target=target,
            target_repo_root=target_repo_root,
            base_commit=base_commit,
            worktree_path=worktree_path,
            generated_by=generated_by,
            lifecycle="running",
            generator_status="running",
        )
        write_upgrade_metadata(home, proposal_id, "pending", running_metadata)

        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        _emit_event(event_callback, "status", phase="worktree", message="创建隔离 worktree", lifecycle="running")
        _run_git_traced(
            target_repo_root,
            ["worktree", "add", "--detach", str(worktree_path), base_commit],
            event_callback=event_callback,
            call_id=f"{proposal_id}:git-worktree-add",
        )
        log("worktree_created", worktree_path=str(worktree_path), base_commit=base_commit)

        cli_label = str(target.get("cli_type") or target.get("cli_path") or "cli")
        _emit_event(event_callback, "status", phase="cli", message=f"调用 {cli_label} 生成 patch", lifecycle="running")
        _emit_event(
            event_callback,
            "trace",
            event={
                "kind": "tool_call",
                "summary": f"{cli_label} generate patch",
                "tool_name": cli_label,
                "call_id": f"{proposal_id}:generator-cli",
            },
        )
        cli_started_at = time.perf_counter()
        try:
            generator = _run_generator_cli(
                worktree_path,
                _build_generation_prompt(proposal),
                {"cli_type": target.get("cli_type"), "cli_path": target.get("cli_path")},
            )
        except subprocess.CalledProcessError as exc:
            generator_elapsed_seconds = int(round(max(time.perf_counter() - cli_started_at, 0)))
            _emit_event(
                event_callback,
                "trace",
                event={
                    "kind": "tool_result",
                    "summary": _summarize_completed_process(
                        exc.returncode,
                        cli_started_at,
                        stdout=exc.output or "",
                        stderr=exc.stderr or "",
                    ),
                    "tool_name": cli_label,
                    "call_id": f"{proposal_id}:generator-cli",
                },
            )
            raise
        generator_elapsed_seconds = int(generator.get("elapsed_seconds") or 0)
        _emit_event(
            event_callback,
            "trace",
            event={
                "kind": "tool_result",
                "summary": _summarize_completed_process(
                    0,
                    cli_started_at,
                    stdout=str(generator.get("stdout_tail") or ""),
                    stderr=str(generator.get("stderr_tail") or ""),
                ),
                "tool_name": cli_label,
                "call_id": f"{proposal_id}:generator-cli",
            },
        )
        assistant_text = str(generator.get("assistant_text") or "").strip()
        stdout_tail = str(generator.get("stdout_tail") or "").strip()
        stderr_tail = str(generator.get("stderr_tail") or "").strip()
        if assistant_text:
            _emit_event(event_callback, "log", text=assistant_text)
        elif stdout_tail:
            _emit_event(event_callback, "log", text=stdout_tail)
        if stderr_tail:
            _emit_event(event_callback, "log", text=stderr_tail)
        log("cli_finished", status=generator.get("status"), elapsed_seconds=generator.get("elapsed_seconds"))

        _emit_event(event_callback, "status", phase="diff", message="导出 diff", lifecycle="running")
        _run_git_traced(
            worktree_path,
            ["add", "-N", "--", "."],
            event_callback=event_callback,
            call_id=f"{proposal_id}:git-add-intent",
        )
        diff_text = _run_git_traced(
            worktree_path,
            ["diff", "--binary", "--", "."],
            event_callback=event_callback,
            call_id=f"{proposal_id}:git-diff",
        ).stdout
        if not diff_text.strip():
            log("failed", code="empty_patch")
            raise ValueError("empty_patch")

        encoded = diff_text.encode("utf-8")
        summary = _summarize_patch(diff_text)
        if len(encoded) > PATCH_SIZE_LIMIT_BYTES:
            log("failed", code="patch_too_large", bytes=len(encoded))
            raise ValueError("patch_too_large")
        if int(summary["file_count"]) > PATCH_FILE_LIMIT:
            log("failed", code="patch_file_limit", file_count=summary["file_count"])
            raise ValueError("patch_file_limit")

        pending_patch.parent.mkdir(parents=True, exist_ok=True)
        _write_lf_text(pending_patch, diff_text)
        saved = write_upgrade_metadata(
            home,
            proposal_id,
            "pending",
            _build_generation_metadata(
                proposal_id,
                target=target,
                target_repo_root=target_repo_root,
                base_commit=base_commit,
                worktree_path=worktree_path,
                generated_by=generated_by,
                lifecycle="pending",
                generator_status=str(generator.get("status") or "succeeded"),
                generator_elapsed_seconds=int(generator.get("elapsed_seconds") or 0),
                changed_files=list(summary["changed_files"]),
                additions=int(summary["additions"]),
                deletions=int(summary["deletions"]),
                sensitive_hits=list(summary["sensitive_hits"]),
            ),
        )
        if saved["sensitive_hits"]:
            log("sensitive_path_blocked", files=saved["sensitive_hits"])
        log("patch_exported", patch_path=str(pending_patch), files=saved["changed_files"])
        log("succeeded", proposal_id=proposal_id)
        _emit_event(event_callback, "status", phase="done", message="patch 已生成", lifecycle="pending")
        return saved
    except Exception as exc:
        error_message = _normalize_error_message(exc).strip() or "patch_generation_failed"
        log("failed", code=type(exc).__name__, error=error_message)
        try:
            if pending_patch.exists():
                pending_patch.unlink()
        except FileNotFoundError:
            pass
        failed_metadata = write_upgrade_metadata(
            home,
            proposal_id,
            "pending",
            _build_generation_metadata(
                proposal_id,
                target=target,
                target_repo_root=target_repo_root,
                base_commit=base_commit,
                worktree_path=worktree_path,
                generated_by=generated_by,
                lifecycle="failed",
                generator_status="failed",
                error=error_message,
                generator_elapsed_seconds=generator_elapsed_seconds,
            ),
        )
        _emit_event(event_callback, "status", phase="failed", message="patch 生成失败", lifecycle="failed")
        _emit_event(event_callback, "log", text=error_message)
        _emit_event(
            event_callback,
            "error",
            code="patch_generation_failed",
            message=error_message,
            metadata=failed_metadata,
        )
        raise
    finally:
        if worktree_path.exists():
            _remove_worktree(target_repo_root, worktree_path)
        _clear_generation_active(home, proposal_id)
