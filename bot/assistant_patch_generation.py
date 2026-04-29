from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.assistant_home import AssistantHome
from bot.assistant_upgrade import write_upgrade_metadata
from bot.assistant_upgrade_diff import parse_patch_files
from bot.cli import build_cli_command, normalize_cli_type, resolve_cli_executable
from bot.cli_params import CliParamsConfig
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
    cmd, use_stdin = build_cli_command(
        cli_type=cli_type,
        resolved_cli=resolved_cli,
        user_text=prompt,
        env=env,
        params_config=CliParamsConfig(),
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


def _ensure_clean_worktree_slot(target_repo_root: Path, worktree_path: Path, regenerate: bool) -> None:
    if not worktree_path.exists():
        return
    if not regenerate:
        raise FileExistsError(str(worktree_path))
    _run_git(target_repo_root, ["worktree", "remove", "--force", str(worktree_path)], check=False)
    _run_git(target_repo_root, ["worktree", "prune"], check=False)
    if worktree_path.exists():
        shutil.rmtree(worktree_path)


def generate_pending_patch(
    home: AssistantHome,
    proposal: dict[str, Any],
    *,
    target: dict[str, Any],
    generated_by: str,
    regenerate: bool = False,
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

    worktree_path = home.root / "upgrades" / "worktrees" / proposal_id
    pending_patch = home.root / "upgrades" / "pending" / f"{proposal_id}.patch"
    pending_metadata = home.root / "upgrades" / "pending" / f"{proposal_id}.json"
    if not regenerate and (pending_patch.exists() or pending_metadata.exists()):
        raise FileExistsError(str(pending_patch if pending_patch.exists() else pending_metadata))

    log_path = home.root / "upgrades" / "logs" / f"{proposal_id}.generate.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(event: str, **payload: Any) -> None:
        row = {"event": event, "created_at": datetime.now(UTC).isoformat(), **payload}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")

    log("started", proposal_id=proposal_id)
    if regenerate:
        _clear_pending_outputs(home, proposal_id)
    _ensure_clean_worktree_slot(target_repo_root, worktree_path, regenerate)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _run_git(target_repo_root, ["worktree", "add", "--detach", str(worktree_path), base_commit])
    log("worktree_created", worktree_path=str(worktree_path), base_commit=base_commit)

    generator = _run_generator_cli(
        worktree_path,
        _build_generation_prompt(proposal),
        {"cli_type": target.get("cli_type"), "cli_path": target.get("cli_path")},
    )
    log("cli_finished", status=generator.get("status"), elapsed_seconds=generator.get("elapsed_seconds"))

    _run_git(worktree_path, ["add", "-N", "--", "."])
    diff_text = _run_git(worktree_path, ["diff", "--binary", "--", "."]).stdout
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
    pending_patch.write_text(diff_text, encoding="utf-8")
    metadata = {
        "id": proposal_id,
        "proposal_id": proposal_id,
        "state": "pending",
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
            "status": str(generator.get("status") or ""),
            "elapsed_seconds": int(generator.get("elapsed_seconds") or 0),
        },
        "dry_run": {"ok": False, "checked_at": "", "stderr": ""},
        **summary,
    }
    saved = write_upgrade_metadata(home, proposal_id, "pending", metadata)
    if saved["sensitive_hits"]:
        log("sensitive_path_blocked", files=saved["sensitive_hits"])
    log("patch_exported", patch_path=str(pending_patch), files=saved["changed_files"])
    log("succeeded", proposal_id=proposal_id)
    return saved
