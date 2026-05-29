"""CLI 参数配置管理模块

支持每个 Bot 独立配置 CLI 调用参数，实现参数的可查、可改。
"""

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional, Tuple

from bot.platform.executables import build_executable_invocation

logger = logging.getLogger(__name__)

MODEL_OPTION_NONE = "none"
REMOVED_CLI_MODEL_OPTIONS = {"gpt-5.2", "gpt-5.3"}
REQUIRED_CLI_MODEL_OPTIONS = [MODEL_OPTION_NONE]

# ============ 各 CLI 的默认参数配置 ============

DEFAULT_CLAUDE_PARAMS = {
    # 基础参数
    "yolo": True,                    # --dangerously-skip-permissions
    "effort": "max",                 # --effort: max/high/medium/low
    "disable_prompts": True,         # CLAUDE_CODE_DISABLE_PROMPTS=1
    "stream_json": True,             # --output-format stream-json --verbose --include-partial-messages
    # 可选参数
    "session_id": None,              # --session-id / -r: 会话ID
    "model": None,                   # --model: 模型选择
    # 高级参数
    "extra_args": [],                # 额外参数列表
}

DEFAULT_CODEX_PARAMS = {
    # 基础参数 (exec 子命令)
    "yolo": True,                    # --dangerously-bypass-approvals-and-sandbox
    "skip_git_check": True,          # --skip-git-repo-check
    "reasoning_effort": "xhigh",     # -c model_reasoning_effort
    # 可选参数
    "json_output": True,             # --json: JSON格式输出
    "model": "gpt-5.4",              # --model: 模型选择
    # 高级参数
    "extra_args": [],                # 额外参数列表
}

DEFAULT_KIMI_PARAMS = {
    "yolo": True,
    "stream_json": True,
    "model": None,
    "thinking": None,
    "agent": None,
    "max_steps_per_turn": None,
    "extra_args": [],
}

# CLI 类型到默认参数的映射
DEFAULT_PARAMS_MAP = {
    "claude": DEFAULT_CLAUDE_PARAMS,
    "codex": DEFAULT_CODEX_PARAMS,
    "kimi": DEFAULT_KIMI_PARAMS,
}

# 支持的 CLI 类型
SUPPORTED_CLI_TYPES = set(DEFAULT_PARAMS_MAP.keys())

PARAM_SCHEMA_MAP = {
    "claude": {
        "yolo": {"type": "boolean", "description": "跳过权限确认"},
        "effort": {
            "type": "string",
            "description": "努力程度",
            "enum": ["max", "high", "medium", "low"],
        },
        "disable_prompts": {"type": "boolean", "description": "禁用交互式提示"},
        "stream_json": {"type": "boolean", "description": "启用 stream-json 流式输出"},
        "session_id": {"type": "string", "description": "会话 ID", "nullable": True},
        "model": {"type": "string", "description": "模型选择", "nullable": True},
        "extra_args": {"type": "string_list", "description": "额外参数"},
    },
    "codex": {
        "yolo": {"type": "boolean", "description": "绕过审批和沙箱"},
        "skip_git_check": {"type": "boolean", "description": "跳过 Git 仓库检查"},
        "reasoning_effort": {
            "type": "string",
            "description": "推理努力程度",
            "enum": ["xhigh", "high", "medium", "low"],
        },
        "json_output": {"type": "boolean", "description": "JSON 格式输出"},
        "model": {"type": "string", "description": "模型选择", "nullable": True},
        "extra_args": {"type": "string_list", "description": "额外参数"},
    },
    "kimi": {
        "yolo": {"type": "boolean", "description": "自动批准操作"},
        "stream_json": {"type": "boolean", "description": "启用 stream-json 输出"},
        "model": {"type": "string", "description": "模型选择", "nullable": True},
        "thinking": {
            "type": "string",
            "description": "Thinking 模式",
            "nullable": True,
            "enum": ["enabled", "disabled", "default"],
        },
        "agent": {"type": "string", "description": "内置 Agent", "nullable": True},
        "max_steps_per_turn": {
            "type": "number",
            "description": "单轮最大步数",
            "integer": True,
            "nullable": True,
        },
        "extra_args": {"type": "string_list", "description": "额外参数"},
    },
}


@dataclass
class CliParamsConfig:
    """CLI 参数配置类"""
    
    claude: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CLAUDE_PARAMS))
    codex: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CODEX_PARAMS))
    kimi: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_KIMI_PARAMS))
    
    def to_dict(self) -> Dict[str, Dict[str, Any]]:
        """转换为字典格式用于序列化"""
        return {
            "claude": copy.deepcopy(self.claude),
            "codex": copy.deepcopy(self.codex),
            "kimi": copy.deepcopy(self.kimi),
        }
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CliParamsConfig":
        """从字典加载配置，支持部分更新"""
        config = cls()
        if not isinstance(data, dict):
            return config
        
        for cli_type in SUPPORTED_CLI_TYPES:
            cli_data = data.get(cli_type)
            if isinstance(cli_data, dict):
                # 合并配置，保留默认值中不存在的键
                default = DEFAULT_PARAMS_MAP[cli_type].copy()
                default.update(cli_data)
                setattr(config, cli_type, default)
        
        return config
    
    def get_params(self, cli_type: str) -> Dict[str, Any]:
        """获取指定 CLI 类型的参数"""
        cli_type = cli_type.lower().strip()
        if cli_type not in SUPPORTED_CLI_TYPES:
            raise ValueError(f"不支持的 CLI 类型: {cli_type} (支持: {', '.join(SUPPORTED_CLI_TYPES)})")
        return getattr(self, cli_type)
    
    def set_param(self, cli_type: str, key: str, value: Any) -> None:
        """设置指定参数"""
        params = self.get_params(cli_type)
        params[key] = value
    
    def get_param(self, cli_type: str, key: str, default: Any = None) -> Any:
        """获取指定参数"""
        params = self.get_params(cli_type)
        return params.get(key, default)
    
    def reset_to_default(self, cli_type: Optional[str] = None) -> None:
        """重置为默认配置"""
        if cli_type is None:
            # 重置所有
            self.claude = copy.deepcopy(DEFAULT_CLAUDE_PARAMS)
            self.codex = copy.deepcopy(DEFAULT_CODEX_PARAMS)
            self.kimi = copy.deepcopy(DEFAULT_KIMI_PARAMS)
        else:
            cli_type = cli_type.lower().strip()
            if cli_type not in SUPPORTED_CLI_TYPES:
                raise ValueError(f"不支持的 CLI 类型: {cli_type}")
            setattr(self, cli_type, copy.deepcopy(DEFAULT_PARAMS_MAP[cli_type]))


def get_default_params(cli_type: str) -> Dict[str, Any]:
    """获取指定 CLI 类型的默认参数。"""
    cli_type = cli_type.lower().strip()
    if cli_type not in SUPPORTED_CLI_TYPES:
        raise ValueError(f"不支持的 CLI 类型: {cli_type}")
    return copy.deepcopy(DEFAULT_PARAMS_MAP[cli_type])


def get_params_schema(cli_type: str) -> Dict[str, Dict[str, Any]]:
    """获取指定 CLI 类型的参数 schema。"""
    cli_type = cli_type.lower().strip()
    if cli_type not in SUPPORTED_CLI_TYPES:
        raise ValueError(f"不支持的 CLI 类型: {cli_type}")
    return copy.deepcopy(PARAM_SCHEMA_MAP[cli_type])


def normalize_cli_model_options(options: Optional[List[str]]) -> List[str]:
    """标准化模型选项列表。"""
    normalized: List[str] = []
    seen: set[str] = set()

    def add_option(value: Any) -> None:
        candidate = str(value or "").strip()
        if not candidate or candidate in REMOVED_CLI_MODEL_OPTIONS or candidate in seen:
            return
        seen.add(candidate)
        normalized.append(candidate)

    for option in options or []:
        add_option(option)
    for option in REQUIRED_CLI_MODEL_OPTIONS:
        add_option(option)

    return normalized


def _normalize_cli_type(cli_type: str) -> str:
    return (cli_type or "").strip().lower()


def with_global_extra_args(
    params_config: CliParamsConfig,
    global_extra_args: Mapping[str, Sequence[str]] | None,
) -> CliParamsConfig:
    """Return a copy with global extra args appended per CLI type."""
    merged = CliParamsConfig.from_dict(params_config.to_dict())
    for cli_type, args in (global_extra_args or {}).items():
        params = getattr(merged, _normalize_cli_type(str(cli_type)), None)
        if isinstance(params, dict):
            params["extra_args"] = [
                *[str(x) for x in params.get("extra_args", []) if str(x).strip()],
                *[str(x) for x in args if str(x).strip()],
            ]
    return merged


def normalize_codex_project_path(working_dir: Optional[str]) -> Optional[str]:
    """Return the path key format Codex stores under [projects]."""
    value = str(working_dir or "").strip()
    if not value:
        return None
    normalized = os.path.abspath(os.path.expanduser(value))
    if os.name == "nt":
        normalized = normalized.replace("/", "\\").lower()
    return normalized


def build_codex_project_trust_config_arg(working_dir: Optional[str]) -> Optional[str]:
    project_path = normalize_codex_project_path(working_dir)
    if not project_path:
        return None
    return f"projects.{json.dumps(project_path, ensure_ascii=False)}.trust_level=\"trusted\""


def coerce_param_value(cli_type: str, key: str, value: Any) -> Any:
    """根据 schema 将外部输入转换为内部参数值。"""
    cli_type = cli_type.lower().strip()
    schema = get_params_schema(cli_type)
    if key not in schema:
        raise ValueError(f"未知参数: {key}")

    field = schema[key]
    field_type = field["type"]
    nullable = bool(field.get("nullable", False))

    if key == "model" and isinstance(value, str) and value.strip().lower() == MODEL_OPTION_NONE:
        value = None

    if cli_type == "kimi" and key == "thinking":
        normalized = str(value or "").strip().lower()
        if normalized in {"", "default", "none"}:
            return None
        if normalized in {"enabled", "true", "1", "yes", "on"}:
            return "enabled"
        if normalized in {"disabled", "false", "0", "no", "off"}:
            return "disabled"
        raise ValueError("参数 thinking 的可选值为: enabled, disabled, default")

    if nullable and (value is None or (isinstance(value, str) and not value.strip())):
        return None

    if field_type == "boolean":
        if isinstance(value, bool):
            coerced = value
        elif isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                coerced = True
            elif normalized in {"false", "0", "no", "off"}:
                coerced = False
            else:
                raise ValueError(f"参数 {key} 需要布尔值")
        else:
            coerced = bool(value)
    elif field_type == "number":
        try:
            coerced = int(value) if field.get("integer") else float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"参数 {key} 需要数字") from exc
    elif field_type == "string_list":
        if value is None:
            coerced = []
        elif isinstance(value, list):
            coerced = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                coerced = []
            else:
                parsed = None
                if stripped.startswith("["):
                    try:
                        loaded = json.loads(stripped)
                    except json.JSONDecodeError:
                        loaded = None
                    if isinstance(loaded, list):
                        parsed = loaded
                if parsed is not None:
                    coerced = [str(item).strip() for item in parsed if str(item).strip()]
                elif "\n" in stripped:
                    coerced = [item.strip() for item in stripped.splitlines() if item.strip()]
                else:
                    coerced = [item.strip() for item in stripped.split(",") if item.strip()]
        else:
            raise ValueError(f"参数 {key} 需要字符串列表")
    else:
        coerced = str(value).strip()
        if nullable and not coerced:
            coerced = None

    enum_values = field.get("enum")
    if enum_values and coerced is not None and coerced not in enum_values:
        raise ValueError(f"参数 {key} 的可选值为: {', '.join(enum_values)}")

    return coerced


def build_cli_args_from_config(
    cli_type: str,
    resolved_cli: str,
    params_config: CliParamsConfig,
    user_text: str,
    session_id: Optional[str] = None,
    resume_session: bool = False,
    working_dir: Optional[str] = None,
    task_mode: str = "standard",
) -> Tuple[List[str], bool]:
    """根据配置构建 CLI 命令行参数
    
    Returns:
        Tuple[List[str], bool]: (命令列表, 是否使用 stdin)
    """
    cli_type = cli_type.lower().strip()
    params = params_config.get_params(cli_type)
    
    # 检测 CLI 原生子命令（以 / 开头且为单个词）
    is_cli_subcommand = user_text.startswith("/") and len(user_text.split()) == 1

    if cli_type == "claude":
        return _build_claude_args(
            resolved_cli,
            params,
            user_text,
            is_cli_subcommand,
            session_id,
            resume_session,
            task_mode=task_mode,
        )

    if cli_type == "codex":
        return _build_codex_args(resolved_cli, params, user_text, is_cli_subcommand, session_id, working_dir)

    if cli_type == "kimi":
        return _build_kimi_args(resolved_cli, params, user_text, is_cli_subcommand, session_id, working_dir)

    raise ValueError(f"不支持的 CLI 类型: {cli_type}")


def _build_claude_args(
    resolved_cli: str,
    params: Dict[str, Any],
    user_text: str,
    is_cli_subcommand: bool,
    session_id: Optional[str],
    resume_session: bool,
    task_mode: str = "standard",
) -> Tuple[List[str], bool]:
    """构建 Claude CLI 参数
    
    Note: disable_prompts 通过环境变量设置，不在命令行中
    """
    cli_invocation = build_executable_invocation(resolved_cli)
    
    # 处理子命令
    if is_cli_subcommand:
        subcmd = user_text[1:]
        if subcmd in ("help", "usage"):
            return [*cli_invocation, "--help"], False
        return [*cli_invocation, subcmd], False
    
    cmd = [*cli_invocation, "-p"]
    
    # 添加基础参数
    if params.get("yolo"):
        cmd.append("--dangerously-skip-permissions")
    
    # effort 参数
    effort = params.get("effort")
    if effort:
        cmd.extend(["--effort", str(effort)])

    if params.get("stream_json"):
        cmd.extend(["--output-format", "stream-json", "--verbose", "--include-partial-messages"])

    # 模型参数
    if params.get("model"):
        cmd.extend(["--model", str(params["model"])])
    
    # 会话ID参数
    if session_id:
        if resume_session:
            cmd.extend(["-r", session_id])
        else:
            cmd.extend(["--session-id", session_id])
    
    extra_args = params.get("extra_args", [])
    if extra_args:
        if task_mode == "plan":
            cmd.extend(_filter_claude_plan_mode_extra_args(extra_args))
        else:
            cmd.extend([str(arg) for arg in extra_args])

    if task_mode == "plan":
        cmd.extend(["--permission-mode", "bypassPermissions" if params.get("yolo") else "default"])
    
    # 从 stdin 读取提示
    cmd.append("-")
    
    return cmd, True


def _filter_claude_plan_mode_extra_args(extra_args: Sequence[Any]) -> List[str]:
    filtered: List[str] = []
    skip_next = False
    for item in extra_args:
        arg = str(item)
        if skip_next:
            skip_next = False
            continue
        if arg == "--permission-mode":
            skip_next = True
            continue
        if arg.startswith("--permission-mode="):
            continue
        filtered.append(arg)
    return filtered


def _build_codex_args(
    resolved_cli: str,
    params: Dict[str, Any],
    user_text: str,
    is_cli_subcommand: bool,
    session_id: Optional[str],
    working_dir: Optional[str],
) -> Tuple[List[str], bool]:
    """构建 Codex CLI 参数"""
    cli_invocation = build_executable_invocation(resolved_cli)
    
    # 处理子命令
    if is_cli_subcommand:
        subcmd = user_text[1:]
        if subcmd in ("help", "usage"):
            return [*cli_invocation, "--help"], False
        return [*cli_invocation, subcmd], False
    
    # 构建 exec 选项
    exec_options = []
    
    if params.get("yolo"):
        exec_options.append("--dangerously-bypass-approvals-and-sandbox")
    if params.get("skip_git_check"):
        exec_options.append("--skip-git-repo-check")

    trust_config_arg = build_codex_project_trust_config_arg(working_dir)
    if trust_config_arg:
        exec_options.extend(["-c", trust_config_arg])
    
    # reasoning_effort
    reasoning_effort = params.get("reasoning_effort")
    if reasoning_effort:
        exec_options.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    
    # 模型参数
    if params.get("model"):
        exec_options.extend(["--model", str(params["model"])])
    
    # JSON 输出
    if params.get("json_output"):
        exec_options.append("--json")
    
    # 添加额外参数
    extra_args = params.get("extra_args", [])
    if extra_args:
        exec_options.extend([str(arg) for arg in extra_args])
    
    # 构建完整命令
    if session_id:
        cmd = [
            *cli_invocation,
            "exec",
            "resume",
            *exec_options,
            session_id,
            "-",
        ]
    else:
        cmd = [
            *cli_invocation,
            "exec",
            *exec_options,
            "-",
        ]
    
    return cmd, True


def _build_kimi_args(
    resolved_cli: str,
    params: Dict[str, Any],
    user_text: str,
    is_cli_subcommand: bool,
    session_id: Optional[str],
    working_dir: Optional[str],
) -> Tuple[List[str], bool]:
    """构建 Kimi CLI 参数"""
    cli_invocation = build_executable_invocation(resolved_cli)

    if is_cli_subcommand:
        subcmd = user_text[1:]
        if subcmd in ("help", "usage"):
            return [*cli_invocation, "--help"], False
        return [*cli_invocation, subcmd], False

    cmd = [*cli_invocation]
    if working_dir:
        cmd.extend(["--work-dir", str(working_dir)])
    if session_id:
        cmd.extend(["--session", str(session_id)])
    cmd.append("--print")
    if params.get("stream_json", True):
        cmd.extend(["--output-format", "stream-json"])
    if params.get("yolo"):
        cmd.append("--yolo")
    if params.get("model"):
        cmd.extend(["--model", str(params["model"])])
    if params.get("agent"):
        cmd.extend(["--agent", str(params["agent"])])
    thinking = params.get("thinking")
    if isinstance(thinking, bool):
        thinking = "enabled" if thinking else "disabled"
    else:
        thinking = str(thinking or "").strip().lower()
    if thinking == "enabled":
        cmd.append("--thinking")
    elif thinking == "disabled":
        cmd.append("--no-thinking")
    max_steps = params.get("max_steps_per_turn")
    if max_steps is not None:
        cmd.extend(["--max-steps-per-turn", str(int(max_steps))])
    cmd.extend([str(arg) for arg in params.get("extra_args", []) if str(arg).strip()])
    return cmd, True


def get_params_help(cli_type: str) -> str:
    """获取指定 CLI 类型的参数说明"""

    help_texts = {
        "claude": """
<b>Claude CLI 可配置参数:</b>

<code>yolo</code> - 跳过权限确认 (布尔值)
  默认: True
  对应参数: --dangerously-skip-permissions

<code>effort</code> - 努力程度 (字符串)
  默认: "max"
  对应参数: --effort
  可选值: "max", "high", "medium", "low"

<code>disable_prompts</code> - 禁用交互式提示 (布尔值)
  默认: True
  对应环境变量: CLAUDE_CODE_DISABLE_PROMPTS=1

<code>stream_json</code> - 启用 stream-json 流式输出 (布尔值)
  默认: True
  对应参数: --output-format stream-json --verbose --include-partial-messages

<code>model</code> - 模型选择 (字符串)
  默认: None
  对应参数: --model

<code>extra_args</code> - 额外参数 (字符串列表)
  默认: []
  示例: ["--verbose"]
""",
        "codex": """
<b>Codex CLI 可配置参数:</b>

<code>yolo</code> - 绕过审批和沙箱 (布尔值)
  默认: True
  对应参数: --dangerously-bypass-approvals-and-sandbox

<code>skip_git_check</code> - 跳过 Git 仓库检查 (布尔值)
  默认: True
  对应参数: --skip-git-repo-check

<code>reasoning_effort</code> - 推理努力程度 (字符串)
  默认: "xhigh"
  对应参数: -c model_reasoning_effort="..."
  可选值: "xhigh", "high", "medium", "low"

<code>json_output</code> - JSON 格式输出 (布尔值)
  默认: True
  对应参数: --json

<code>model</code> - 模型选择 (字符串)
  默认: None
  对应参数: --model

<code>extra_args</code> - 额外参数 (字符串列表)
  默认: []
  示例: ["--timeout", "120"]
""",
    }

    return help_texts.get(cli_type.lower(), "未知 CLI 类型")


def format_params_display(cli_type: str, params: Dict[str, Any]) -> str:
    """格式化参数显示"""
    lines = [f"<b>{cli_type.upper()} CLI 当前参数:</b>\n"]
    
    for key, value in sorted(params.items()):
        if key == "extra_args" and value:
            lines.append(f"  <code>{key}</code>: {value}")
        elif isinstance(value, bool):
            icon = "✅" if value else "❌"
            lines.append(f"  {icon} <code>{key}</code>: {value}")
        elif value is None:
            lines.append(f"  ⚪ <code>{key}</code>: (未设置)")
        else:
            lines.append(f"  🔹 <code>{key}</code>: <code>{value}</code>")
    
    return "\n".join(lines)
