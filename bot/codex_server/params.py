"""Convert the existing filtered Codex argument semantics without executing exec."""
from __future__ import annotations

import copy
import json
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bot.cli_params import CliParamsConfig, build_cli_args_from_config, build_codex_project_trust_config_arg
from bot.platform.executables import build_executable_invocation, resolve_cli_executable
from bot.platform.processes import build_hidden_process_kwargs
from .client import APP_SERVER_VERSION, CodexServerError


@dataclass
class ServerParams:
    argv: list[str]
    cwd: str
    model: str | None = None
    effort: str | None = None
    thread: dict[str, Any] = field(default_factory=dict)
    turn: dict[str, Any] = field(default_factory=dict)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    add_dirs: list[str] = field(default_factory=list)
    skip_git_check: bool = True


def _config_value(value: str) -> Any:
    try:
        return tomllib.loads("value=" + value)["value"]
    except tomllib.TOMLDecodeError:
        return value


def convert_params(command: str, cwd: str, params_config: CliParamsConfig) -> ServerParams:
    executable = resolve_cli_executable(command or "codex", cwd)
    if not executable:
        raise CodexServerError(f"未找到 Codex 可执行文件: {command}")
    invocation = build_executable_invocation(executable)
    # Copy the independently stored, already permission-filtered server settings.
    config = CliParamsConfig.from_dict({"codex": copy.deepcopy(params_config.get_params("codex_server"))})
    args, _ = build_cli_args_from_config("codex", executable, config, "protocol input", working_dir=cwd)
    options = args[len(invocation) + 1:-1]
    result = ServerParams([*invocation, "app-server", "--stdio"], str(Path(cwd).expanduser().resolve()),
                          skip_git_check=bool(config.codex.get("skip_git_check")))
    config_args: list[str] = []
    config_overrides: dict[str, Any] = {}
    add_dirs: list[str] = []
    index = 0
    while index < len(options):
        raw = options[index]
        flag, has_equals, inline = raw.partition("=")
        index += 1
        def value() -> str:
            nonlocal index
            if has_equals:
                return inline
            if index >= len(options):
                raise CodexServerError(f"codex server 参数 {flag} 缺少值")
            answer = options[index]
            index += 1
            return answer

        if flag in {"--json", "--skip-git-repo-check"}:
            if flag == "--skip-git-repo-check":
                result.skip_git_check = True
        elif flag in {"-c", "--config"}:
            entry = value()
            key, separator, text = entry.partition("=")
            key = key.strip()
            if not separator or not key:
                raise CodexServerError(f"无效 codex server 配置覆盖: {entry}")
            parsed = _config_value(text)
            if key in {"model", "model_reasoning_effort"}:
                config_overrides[key] = parsed
            else:
                config_args.extend(["-c", entry])
        elif flag in {"--model", "-m"}:
            result.model = value()
        elif flag in {"--sandbox", "-s"}:
            sandbox = value()
            if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
                raise CodexServerError(f"不支持的 sandbox: {sandbox}")
            result.thread["sandbox"] = sandbox
        elif flag in {"--ask-for-approval", "--approval-policy", "-a"}:
            policy = value()
            if policy not in {"untrusted", "on-request", "never"}:
                raise CodexServerError(f"{APP_SERVER_VERSION} app-server 不支持 approvalPolicy: {policy}")
            result.thread["approvalPolicy"] = policy
        elif flag in {"--dangerously-bypass-approvals-and-sandbox", "--yolo"}:
            result.thread.update(approvalPolicy="never", sandbox="danger-full-access")
        elif flag == "--full-auto":
            result.thread.update(approvalPolicy="on-request", sandbox="workspace-write")
        elif flag in {"--cd", "-C"}:
            directory = Path(value()).expanduser()
            result.cwd = str((directory if directory.is_absolute() else Path(cwd) / directory).resolve())
        elif flag in {"--image", "-i"}:
            for path in value().split(","):
                image = Path(path).expanduser()
                result.inputs.append({"type": "localImage", "path": str(image if image.is_absolute() else Path(cwd) / image)})
        elif flag == "--output-schema":
            schema = Path(value()).expanduser()
            if not schema.is_absolute():
                schema = Path(cwd) / schema
            try:
                result.turn["outputSchema"] = json.loads(schema.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise CodexServerError(f"无法读取 --output-schema: {exc}") from exc
        elif flag == "--ephemeral":
            result.thread["ephemeral"] = True
        elif flag == "--search":
            config_args.extend(["-c", 'web_search="live"'])
        elif flag in {"--enable", "--disable"}:
            config_args.extend(["-c", f"features.{value()}={'true' if flag == '--enable' else 'false'}"])
        elif flag == "--add-dir":
            directory = Path(value()).expanduser()
            add_dirs.append(str((directory if directory.is_absolute() else Path(cwd) / directory).resolve()))
        elif flag == "--color":
            if value() not in {"auto", "always", "never"}:
                raise CodexServerError("--color 必须为 auto/always/never")
        else:
            raise CodexServerError(f"codex server 无法等效转换参数 {raw}；不会回退 codex exec")
    result.add_dirs = add_dirs
    if result.cwd != str(Path(cwd).expanduser().resolve()):
        config_args.extend(["-c", build_codex_project_trust_config_arg(result.cwd)])
    result.model = result.model or config_overrides.get("model")
    result.effort = config_overrides.get("model_reasoning_effort")
    result.argv.extend(config_args)
    return result


def check_git_directory(params: ServerParams, env: dict[str, str]) -> None:
    if params.skip_git_check:
        return
    try:
        result = subprocess.run(["git", "-C", params.cwd, "rev-parse", "--git-dir"], env=env,
                                capture_output=True, timeout=10, **build_hidden_process_kwargs())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodexServerError(f"codex server Git 仓库检查失败: {exc}") from exc
    if result.returncode:
        raise CodexServerError("当前目录不是 Git 仓库；需启用 skip_git_check 才能继续")
