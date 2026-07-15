"""Admin .env read/write service."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import tempfile
from math import isfinite
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class EnvValidationError(ValueError):
    """Invalid env admin payload."""

    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


@dataclass(frozen=True)
class EnvField:
    key: str
    label: str
    description: str
    type: str
    default: str = ""
    category: str = "advanced"
    sensitive: bool = False
    restart_required: bool = True
    rebuild_required: bool = False
    options: tuple[str, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    integer: bool = False
    max_length: int = 4096


@dataclass
class EnvLine:
    raw: str
    key: str = ""
    value: str = ""
    prefix: str = ""
    separator: str = "="
    comment_suffix: str = ""
    newline: str = "\n"

    @property
    def is_key_value(self) -> bool:
        return bool(self.key)


_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_LINE_RE = re.compile(r"^(\s*(?:export\s+)?)(" + _KEY_RE.pattern[1:-1] + r")(\s*=\s*)(.*?)(\r?\n?)$")
_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


ENV_SCHEMA: tuple[EnvField, ...] = (
    EnvField("CLI_TYPE", "CLI 类型", "主 Bot 使用的本地 CLI。", "select", "codex", "basic", options=("codex", "claude")),
    EnvField("CLI_PATH", "CLI 路径", "CLI 可执行文件路径或 PATH 中的命令名。", "path", "codex", "basic"),
    EnvField("CLI_MODEL_OPTIONS", "模型选项", "聊天页模型选择器候选值。", "csv", "", "basic"),
    EnvField(
        "CLI_GLOBAL_EXTRA_ARGS",
        "全局 CLI 额外参数",
        "JSON 对象，按 codex/claude 配置额外参数数组。",
        "string",
        "{}",
        "basic",
        max_length=8192,
    ),
    EnvField("WORKING_DIR", "默认工作目录", "仅影响主 Bot 下次启动默认目录。", "path", "", "basic"),
    EnvField("NATIVE_AGENT_ENABLED", "启用原生 agent", "启用原生 agent run 命令。", "boolean", "false", "advanced"),
    EnvField("NATIVE_AGENT_COMMAND", "原生 agent 命令", "Pi run 可执行文件路径或 PATH 中的命令名；兼容旧 NATIVE_AGENT_PATH。", "path", "pi", "advanced"),
    EnvField("NATIVE_AGENT_PI_COMMAND", "Pi 命令", "Pi agent 可执行文件路径或 PATH 中的命令名。", "path", "pi", "advanced"),
    EnvField("NATIVE_AGENT_PI_HOME", "Pi HOME", "仅给 Pi 子进程使用的 HOME/USERPROFILE；留空使用系统默认。", "path", "", "advanced"),
    EnvField("NATIVE_AGENT_PI_AGENT", "Pi agent", "全局 Pi agent 名称；留空使用默认。", "string", "", "advanced"),
    EnvField("NATIVE_AGENT_WORKSPACE_HISTORY_ENABLED", "Pi 工作区历史", "是否启用 Pi workspace history。", "boolean", "true", "advanced"),
    EnvField(
        "NATIVE_AGENT_NO_PROGRESS_TIMEOUT_SECONDS",
        "原生 agent 无进展超时",
        "原生 agent 在无输出/无进展时的自动终止秒数；0 表示禁用。",
        "number",
        "0",
        "advanced",
        min_value=0,
    ),
    EnvField(
        "NATIVE_AGENT_REASONING_EFFORT",
        "Reasoning effort",
        "全局 reasoning effort，按模型支持填写。",
        "select",
        "",
        "advanced",
        options=("", "minimal", "low", "medium", "high"),
    ),
    EnvField("NATIVE_AGENT_THINKING_DEPTH", "Thinking depth", "全局 thinking token budget；0 表示不启用。", "number", "0", "advanced", min_value=0, integer=True),
    EnvField("WEB_ENABLED", "启用 Web", "Web 运行入口开关。", "boolean", "true", "web"),
    EnvField("WEB_HOST", "监听地址", "Web 服务监听地址。", "string", "0.0.0.0", "web"),
    EnvField("WEB_PORT", "监听端口", "Web 服务监听端口。", "number", "8765", "web", min_value=1, max_value=65535, integer=True),
    EnvField("WEB_API_TOKEN", "登录口令", "旧版 Web API 登录口令。", "password", "", "web", sensitive=True, max_length=8192),
    EnvField("WEB_ALLOWED_ORIGINS", "CORS 允许来源", "逗号分隔的允许来源。", "csv", "", "web"),
    EnvField("WEB_TERMINAL_SHELL_PATH", "Web 终端 Shell 路径", "Web 终端启动的 shell 可执行文件路径；留空使用系统默认 shell。", "path", "", "web"),
    EnvField("TCB_NODE_ID", "节点 ID", "Hub 固定公网转发节点 ID。", "string", "", "web", max_length=64),
    EnvField("WEB_BASE_PATH", "Web 子路径", "固定转发子路径，空或 /node/<节点 ID>。", "string", "", "web", rebuild_required=True),
    EnvField("VITE_BASE_PATH", "前端资源子路径", "构建期配置；留空则跟随 WEB_BASE_PATH。", "string", "", "frontend", rebuild_required=True),
    EnvField("VITE_API_BASE_URL", "前端 API 子路径", "构建期配置；留空则跟随 WEB_BASE_PATH。", "string", "", "frontend", rebuild_required=True),
    EnvField("WEB_PUBLIC_URL", "公网 URL", "反代或隧道公网访问地址。", "string", "", "tunnel"),
    EnvField("WEB_FIXED_PUBLIC_FORWARD_ENABLED", "固定公网转发", "启用 Hub 固定 IP/域名转发。", "boolean", "false", "tunnel"),
    EnvField("WEB_FIXED_PUBLIC_FORWARD_URL", "固定公网入口", "Hub 公网入口 URL，含 /node/<节点 ID>。", "string", "", "tunnel"),
    EnvField("TCB_HUB_FRPS_PORT", "Hub frps 端口", "Hub 分配给 frpc 连接 frps 的端口，不是公网 HTTP 访问端口。", "number", "", "tunnel", min_value=1, max_value=65535, integer=True),
    EnvField("TCB_HUB_NODE_TOKEN", "Hub 节点授权码", "Hub 分配给本节点的授权码。", "password", "", "tunnel", sensitive=True, max_length=8192),
    EnvField("TCB_HUB_FRPS_TOKEN", "Hub frps Token", "frpc 连接 Hub frps 使用的 token。", "password", "", "tunnel", sensitive=True, max_length=8192),
    EnvField("TCB_HUB_FRPC_PATH", "frpc 路径", "frpc 可执行文件路径；留空则使用 PATH 中的 frpc。", "path", "", "tunnel"),
    EnvField("TCB_HUB_FRPC_AUTOSTART", "frpc 自动启动", "Web 启动时自动拉起固定公网转发。", "boolean", "true", "tunnel"),
    EnvField("WEB_TUNNEL_MODE", "隧道模式", "内置隧道模式。", "select", "disabled", "tunnel", options=("disabled", "cloudflare_quick")),
    EnvField("WEB_TUNNEL_AUTOSTART", "自动启动隧道", "Web 启动时自动拉起隧道。", "boolean", "true", "tunnel"),
    EnvField("WEB_TUNNEL_CLOUDFLARED_PATH", "cloudflared 路径", "cloudflared 可执行文件路径。", "path", "", "tunnel"),
    EnvField("WEB_TUNNEL_STATE_FILE", "隧道状态文件", "隧道状态缓存文件路径。", "path", ".web_tunnel_state.json", "tunnel"),
    EnvField("APP_UPDATE_REPOSITORY", "更新仓库", "GitHub Releases 仓库 slug。", "string", "Augustusjk2008/telegram-cli-bot", "updates"),
    EnvField("CHAT_COMPLETION_NOTIFY_ENABLED", "聊天完成通知", "聊天完成后是否发送通知。", "boolean", "true", "notifications"),
    EnvField("PUSHPLUS_ENABLED", "PushPlus 开关", "是否启用 PushPlus 推送。", "boolean", "false", "notifications"),
    EnvField("PUSHPLUS_TOKEN", "PushPlus Token", "PushPlus 发送 token。", "password", "", "notifications", sensitive=True, max_length=8192),
    EnvField("PUSHPLUS_TOPIC", "PushPlus Topic", "PushPlus 群组 topic。", "string", "", "notifications"),
    EnvField("PUSHPLUS_TEMPLATE", "PushPlus 模板", "PushPlus 消息模板。", "string", "markdown", "notifications"),
    EnvField("PUSHPLUS_CHANNEL", "PushPlus 渠道", "PushPlus 发送渠道。", "string", "wechat", "notifications"),
    EnvField("PUSHPLUS_API_URL", "PushPlus API", "PushPlus API 地址。", "string", "https://www.pushplus.plus/send", "notifications"),
    EnvField("PUSHPLUS_TIMEOUT_SECONDS", "PushPlus 超时", "PushPlus 请求超时秒数。", "number", "5.0", "notifications", min_value=0),
    EnvField("PUSHPLUS_PREVIEW_CHARS", "通知预览长度", "通知内容预览字符数。", "number", "300", "notifications", min_value=0, integer=True),
    EnvField("TCB_DIAG_ENABLED", "诊断日志", "开启 Web 诊断日志。", "boolean", "false", "diagnostics"),
    EnvField("TCB_DIAG_SLOW_MS", "慢请求阈值", "慢请求日志阈值毫秒。", "number", "500", "diagnostics", min_value=0, integer=True),
    EnvField("TCB_DIAG_LOOP_LAG_MS", "事件循环卡顿阈值", "事件循环卡顿日志阈值毫秒。", "number", "1000", "diagnostics", min_value=0, integer=True),
    EnvField("NETWORK_ERROR_LOG_SUPPRESS_WINDOW", "网络错误抑制窗口", "同类网络错误 WARNING 抑制秒数。", "number", "60", "advanced", min_value=0, integer=True),
    EnvField("CLI_PROGRESS_UPDATE_INTERVAL", "CLI 进度间隔", "等待提示更新间隔秒数。", "number", "3", "advanced", min_value=0, integer=True),
    EnvField("MANAGED_BOTS_FILE", "托管 Bot 文件", "托管 Bot 配置文件路径。", "path", "managed_bots.json", "advanced"),
    EnvField("ALLOWED_USER_IDS", "允许用户 ID", "逗号分隔的允许用户 ID。", "csv", "", "advanced"),
    EnvField("CLAUDE_DONE_DETECTOR_ENABLED", "Claude 完成检测", "启用 Claude 输出完成检测。", "boolean", "false", "advanced"),
    EnvField("CLAUDE_DONE_QUIET_SECONDS", "Claude 静默秒数", "Claude 完成检测静默秒数。", "number", "2", "advanced", min_value=0),
    EnvField("CLAUDE_DONE_SENTINEL_MODE", "Claude Sentinel 模式", "Claude 完成检测 sentinel 模式。", "select", "nonce", "advanced", options=("nonce", "static", "off")),
    EnvField("ANTHROPIC_API_KEY", "Anthropic API Key", "Claude CLI 使用的 Anthropic API key。", "password", "", "advanced", sensitive=True, max_length=8192),
    EnvField("ANTHROPIC_MODEL", "Anthropic 模型", "Claude CLI 使用的 Anthropic 模型。", "string", "claude-3-5-sonnet-20241022", "advanced"),
    EnvField("ANTHROPIC_BASE_URL", "Anthropic Base URL", "Claude CLI 使用的 Anthropic 代理 API 地址。", "string", "", "advanced"),
    EnvField("TCB_CLUSTER_TEMPLATES_FILE", "集群模板文件", "自定义集群模板文件路径。", "path", "", "advanced"),
    EnvField("CLI_BRIDGE_UPDATE_PACKAGE_KIND", "更新包类型", "强制指定更新包类型。", "select", "", "advanced", options=("", "installer", "portable", "linux", "macos")),
    EnvField("MESSAGES_CONFIG", "消息配置", "自定义消息文案配置文件。", "path", "", "advanced"),
    EnvField("VITE_CHAT_TRACE_PREVIEW_MAX_LINES", "Trace 预览行数", "前端构建期 trace 预览最大行数。", "number", "5", "frontend", restart_required=False, rebuild_required=True, min_value=0, integer=True),
    EnvField("VITE_CHAT_TRACE_PREVIEW_MAX_CHARS", "Trace 预览字符数", "前端构建期 trace 预览最大字符数。", "number", "200", "frontend", restart_required=False, rebuild_required=True, min_value=0, integer=True),
)

_FIELD_BY_KEY = {field.key: field for field in ENV_SCHEMA}


def _split_value_comment(value_part: str) -> tuple[str, str]:
    stripped = value_part.lstrip()
    if stripped.startswith(("'", '"')):
        return value_part.strip(), ""
    for index, char in enumerate(value_part):
        if char != "#":
            continue
        if index == 0:
            return "", value_part
        if value_part[index - 1].isspace():
            return value_part[:index].rstrip(), value_part[index - 1 :]
    return value_part.strip(), ""


def _decode_value(value_part: str) -> str:
    value, _comment = _split_value_comment(value_part)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        inner = value[1:-1]
        if value[0] == '"':
            inner = (
                inner.replace(r"\n", "\n")
                .replace(r"\r", "\r")
                .replace(r"\t", "\t")
                .replace(r"\"", '"')
                .replace(r"\\", "\\")
            )
        return inner
    return value


def _parse_env_text(text: str) -> list[EnvLine]:
    lines: list[EnvLine] = []
    for raw in text.splitlines(keepends=True):
        match = _LINE_RE.match(raw)
        if not match:
            lines.append(EnvLine(raw=raw))
            continue
        prefix, key, separator, value_part, newline = match.groups()
        value_body, comment_suffix = _split_value_comment(value_part)
        lines.append(
            EnvLine(
                raw=raw,
                key=key,
                value=_decode_value(value_body),
                prefix=prefix,
                separator=separator,
                comment_suffix=comment_suffix,
                newline=newline or "\n",
            )
        )
    if text == "":
        return []
    if not text.endswith(("\n", "\r")) and (not lines or lines[-1].raw):
        lines[-1].newline = ""
    return lines


def _values_from_lines(lines: list[EnvLine]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        if line.is_key_value:
            values[line.key] = line.value
    return values


def _read_lines(path: Path) -> list[EnvLine]:
    try:
        return _parse_env_text(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return []


def _encode_value(value: str) -> str:
    if value == "":
        return ""
    if "\n" in value or "\r" in value:
        raise EnvValidationError("invalid_env_value", "配置值不能包含换行")
    if value != value.strip() or "#" in value or '"' in value or "'" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _line_for_value(line: EnvLine, value: str) -> str:
    newline = line.newline or "\n"
    separator = line.separator or "="
    prefix = line.prefix or ""
    return f"{prefix}{line.key}{separator}{_encode_value(value)}{line.comment_suffix}{newline}"


def _is_masked_keep(value: Any, field: EnvField) -> bool:
    if not field.sensitive or not isinstance(value, dict):
        return False
    if value.get("unchanged") is True:
        return True
    if value.get("masked") is True and "value" not in value:
        return True
    if value.get("masked") is True and str(value.get("value") or "") == "":
        return True
    return False


def _payload_values(payload: dict[str, Any]) -> dict[str, Any]:
    values = payload.get("values", payload)
    if not isinstance(values, dict):
        raise EnvValidationError("invalid_request", "values 必须是对象")
    return values


def _normalize_boolean(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    if text in _BOOL_TRUE:
        return "true"
    if text in _BOOL_FALSE:
        return "false"
    raise EnvValidationError("invalid_env_value", f"{key} 必须是布尔值", {"key": key})


def _normalize_number(field: EnvField, value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise EnvValidationError("invalid_env_value", f"{field.key} 必须是数字", {"key": field.key})
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise EnvValidationError("invalid_env_value", f"{field.key} 必须是数字", {"key": field.key}) from exc
    if field.min_value is not None and number < field.min_value:
        raise EnvValidationError("invalid_env_value", f"{field.key} 不能小于 {field.min_value:g}", {"key": field.key})
    if field.max_value is not None and number > field.max_value:
        raise EnvValidationError("invalid_env_value", f"{field.key} 不能大于 {field.max_value:g}", {"key": field.key})
    if not isfinite(number):
        raise EnvValidationError("invalid_env_value", f"{field.key} 必须是有限数字", {"key": field.key})
    if field.integer and not number.is_integer():
        raise EnvValidationError("invalid_env_value", f"{field.key} 必须是整数", {"key": field.key})
    if text.isdigit() or number.is_integer():
        return str(int(number))
    return str(number)


def _normalize_csv(value: Any) -> str:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(items)
    return ",".join(item.strip() for item in str(value).split(",") if item.strip())


def _normalize_base_path_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "/":
        return ""
    return text.rstrip("/")


def _normalize_value(field: EnvField, value: Any) -> str:
    if isinstance(value, dict):
        action = value.get("action")
        if action == "clear":
            value = ""
        elif action == "regenerate":
            if not field.sensitive:
                raise EnvValidationError("invalid_env_value", f"{field.key} 不支持重新生成", {"key": field.key})
            value = secrets.token_urlsafe(32)
        elif action:
            raise EnvValidationError("invalid_env_value", f"{field.key} 操作不支持", {"key": field.key})
        else:
            value = value.get("value", "")
    if value is None:
        value = ""
    if field.type == "boolean":
        normalized = _normalize_boolean(field.key, value)
    elif field.type == "number":
        normalized = _normalize_number(field, value)
    elif field.type == "csv":
        normalized = _normalize_csv(value)
    elif field.key in {"WEB_BASE_PATH", "VITE_BASE_PATH", "VITE_API_BASE_URL"}:
        normalized = _normalize_base_path_value(value)
    else:
        normalized = str(value).strip() if field.type == "select" else str(value)
    if "\n" in normalized or "\r" in normalized:
        raise EnvValidationError("invalid_env_value", f"{field.key} 不能包含换行", {"key": field.key})
    if len(normalized) > field.max_length:
        raise EnvValidationError("invalid_env_value", f"{field.key} 过长", {"key": field.key})
    if field.options and normalized not in field.options:
        raise EnvValidationError(
            "invalid_env_value",
            f"{field.key} 只能是: {', '.join(option for option in field.options if option)}",
            {"key": field.key, "options": list(field.options)},
        )
    return normalized


def _mask_value(value: str, *, sensitive: bool) -> tuple[str, bool, bool]:
    if not sensitive:
        return value, False, False
    return "", bool(value), bool(value)


class EnvConfigService:
    """Reads and writes repository .env while preserving unknown lines."""

    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root)
        self.env_path = self.repo_root / ".env"
        self.example_path = self.repo_root / ".env.example"

    def snapshot(self) -> dict[str, Any]:
        env_values = _values_from_lines(_read_lines(self.env_path))
        example_values = _values_from_lines(_read_lines(self.example_path))
        items = [
            self._serialize_field(field, env_values=env_values, example_values=example_values)
            for field in ENV_SCHEMA
        ]
        return {
            "envPath": str(self.env_path),
            "examplePath": str(self.example_path),
            "exists": self.env_path.exists(),
            "schema": [self._serialize_schema(field, example_values=example_values) for field in ENV_SCHEMA],
            "items": items,
        }

    def reload_preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        changes = self._prepare_changes(payload or {})
        changed_keys = self._ordered_keys(changes)
        return {
            **self.snapshot(),
            "changedKeys": changed_keys,
            "restartRequiredKeys": self._impact_keys(changed_keys, restart=True),
            "rebuildRequiredKeys": self._impact_keys(changed_keys, rebuild=True),
            "backupPath": "",
        }

    def patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        changes = self._prepare_changes(payload)
        changed_keys = self._ordered_keys(changes)
        if not changed_keys:
            return {
                "changedKeys": [],
                "restartRequiredKeys": [],
                "rebuildRequiredKeys": [],
                "backupPath": "",
            }
        backup_path = self._backup_env()
        lines = _read_lines(self.env_path)
        updated_text = self._render_updated_env(lines, changes)
        self._atomic_write(updated_text)
        return {
            "changedKeys": changed_keys,
            "restartRequiredKeys": self._impact_keys(changed_keys, restart=True),
            "rebuildRequiredKeys": self._impact_keys(changed_keys, rebuild=True),
            "backupPath": str(backup_path),
        }

    def _serialize_schema(self, field: EnvField, *, example_values: dict[str, str]) -> dict[str, Any]:
        default = example_values.get(field.key, field.default)
        return {
            "key": field.key,
            "label": field.label,
            "description": field.description,
            "type": field.type,
            "default": default,
            "category": field.category,
            "sensitive": field.sensitive,
            "restartRequired": field.restart_required,
            "rebuildRequired": field.rebuild_required,
            "options": list(field.options),
            "validation": {
                "min": field.min_value,
                "max": field.max_value,
                "integer": field.integer,
                "maxLength": field.max_length,
            },
        }

    def _serialize_field(
        self,
        field: EnvField,
        *,
        env_values: dict[str, str],
        example_values: dict[str, str],
    ) -> dict[str, Any]:
        file_has = field.key in env_values
        example_has = field.key in example_values
        file_value = env_values.get(field.key, "")
        fallback_value = file_value if file_has else example_values.get(field.key, field.default)
        process_has = field.key in os.environ
        process_value = os.environ.get(field.key, "")
        process_overridden = process_has and process_value != fallback_value
        if process_overridden:
            source = "process"
            effective_value = process_value
        elif file_has:
            source = "env"
            effective_value = file_value
        elif example_has:
            source = "example"
            effective_value = example_values[field.key]
        else:
            source = "default"
            effective_value = field.default
        value, masked, has_value = _mask_value(effective_value, sensitive=field.sensitive)
        process_display, process_masked, _process_has_value = _mask_value(process_value, sensitive=field.sensitive)
        return {
            **self._serialize_schema(field, example_values=example_values),
            "value": value,
            "source": source,
            "masked": masked,
            "hasValue": has_value,
            "envFileValuePresent": file_has,
            "processValuePresent": process_has,
            "processOverridden": process_overridden,
            "processValue": process_display,
            "processValueMasked": process_masked,
        }

    def _prepare_changes(self, payload: dict[str, Any]) -> dict[str, str]:
        values = _payload_values(payload)
        env_values = _values_from_lines(_read_lines(self.env_path))
        example_values = _values_from_lines(_read_lines(self.example_path))
        changes: dict[str, str] = {}
        for key, raw_value in values.items():
            normalized_key = str(key or "").strip()
            if not _KEY_RE.fullmatch(normalized_key):
                raise EnvValidationError("invalid_env_key", f"配置 key 不合法: {key}", {"key": str(key)})
            field = _FIELD_BY_KEY.get(normalized_key)
            if field is None:
                raise EnvValidationError("invalid_env_key", f"不支持修改配置: {normalized_key}", {"key": normalized_key})
            if _is_masked_keep(raw_value, field):
                continue
            normalized_value = _normalize_value(field, raw_value)
            current_value = env_values.get(normalized_key)
            if current_value is None:
                current_value = example_values.get(normalized_key, field.default)
            if normalized_value != current_value:
                changes[normalized_key] = normalized_value
        self._validate_combination(env_values, example_values, changes)
        return changes

    def _validate_combination(
        self,
        env_values: dict[str, str],
        example_values: dict[str, str],
        changes: dict[str, str],
    ) -> None:
        values: dict[str, str] = {}
        for field in ENV_SCHEMA:
            values[field.key] = env_values.get(field.key, example_values.get(field.key, field.default))
        values.update(changes)

        node_id = str(values.get("TCB_NODE_ID", "") or "").strip()
        if node_id and not _NODE_ID_RE.fullmatch(node_id):
            raise EnvValidationError(
                "invalid_env_value",
                "TCB_NODE_ID 只能包含字母、数字、下划线、短横线，且最长 64 字符",
                {"key": "TCB_NODE_ID"},
            )

        web_base_path = _normalize_base_path_value(values.get("WEB_BASE_PATH", ""))
        if web_base_path:
            expected = f"/node/{node_id}" if node_id else ""
            if not node_id or web_base_path != expected:
                raise EnvValidationError(
                    "invalid_env_value",
                    "WEB_BASE_PATH 必须为空或等于 /node/<TCB_NODE_ID>",
                    {"key": "WEB_BASE_PATH", "expected": expected or "/node/<TCB_NODE_ID>"},
                )

        for key in ("VITE_BASE_PATH", "VITE_API_BASE_URL"):
            value = _normalize_base_path_value(values.get(key, ""))
            if value and value != web_base_path:
                raise EnvValidationError(
                    "invalid_env_value",
                    f"{key} 必须为空或等于 WEB_BASE_PATH",
                    {"key": key, "expected": web_base_path},
                )

        fixed_enabled = _normalize_boolean("WEB_FIXED_PUBLIC_FORWARD_ENABLED", values.get("WEB_FIXED_PUBLIC_FORWARD_ENABLED", "false")) == "true"
        tunnel_mode = str(values.get("WEB_TUNNEL_MODE", "disabled") or "disabled").strip().lower() or "disabled"
        if fixed_enabled:
            if not str(values.get("WEB_FIXED_PUBLIC_FORWARD_URL", "") or "").strip():
                raise EnvValidationError(
                    "invalid_env_value",
                    "启用固定公网转发时必须填写 WEB_FIXED_PUBLIC_FORWARD_URL",
                    {"key": "WEB_FIXED_PUBLIC_FORWARD_URL"},
                )
            if not str(values.get("TCB_HUB_FRPS_PORT", "") or "").strip():
                raise EnvValidationError(
                    "invalid_env_value",
                    "启用固定公网转发时必须填写 Hub frps 端口",
                    {"key": "TCB_HUB_FRPS_PORT"},
                )
            if not str(values.get("TCB_HUB_NODE_TOKEN", "") or "").strip():
                raise EnvValidationError(
                    "invalid_env_value",
                    "启用固定公网转发时必须填写 Hub 节点授权码",
                    {"key": "TCB_HUB_NODE_TOKEN"},
                )
            if not str(values.get("TCB_HUB_FRPS_TOKEN", "") or "").strip():
                raise EnvValidationError(
                    "invalid_env_value",
                    "启用固定公网转发时必须填写 Hub frps token",
                    {"key": "TCB_HUB_FRPS_TOKEN"},
                )
            if tunnel_mode != "disabled":
                raise EnvValidationError(
                    "invalid_env_value",
                    "固定公网转发和 Cloudflare Quick Tunnel 不能同时启用",
                    {"key": "WEB_TUNNEL_MODE"},
                )
        if tunnel_mode == "cloudflare_quick" and fixed_enabled:
            raise EnvValidationError(
                "invalid_env_value",
                "Cloudflare Quick Tunnel 和固定公网转发不能同时启用",
                {"key": "WEB_FIXED_PUBLIC_FORWARD_ENABLED"},
            )

    def _render_updated_env(self, lines: list[EnvLine], changes: dict[str, str]) -> str:
        pending = dict(changes)
        key_line_indexes: dict[str, int] = {}
        for index, line in enumerate(lines):
            if line.is_key_value and line.key in pending:
                key_line_indexes[line.key] = index
        rendered: list[str] = []
        for index, line in enumerate(lines):
            if line.is_key_value and key_line_indexes.get(line.key) == index:
                rendered.append(_line_for_value(line, pending.pop(line.key)))
            else:
                rendered.append(line.raw)
        if rendered and not rendered[-1].endswith(("\n", "\r")):
            rendered[-1] = rendered[-1] + "\n"
        for key in self._ordered_keys(pending):
            rendered.append(f"{key}={_encode_value(pending[key])}\n")
        return "".join(rendered)

    def _backup_env(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        backup_path = self.repo_root / f".env.bak.{timestamp}"
        while backup_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            backup_path = self.repo_root / f".env.bak.{timestamp}"
        if self.env_path.exists():
            shutil.copy2(self.env_path, backup_path)
        else:
            backup_path.write_text("", encoding="utf-8")
        return backup_path

    def _atomic_write(self, text: str) -> None:
        self.repo_root.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=str(self.repo_root))
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            temp_path.replace(self.env_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @staticmethod
    def _ordered_keys(values: dict[str, Any] | list[str]) -> list[str]:
        value_keys = set(values.keys()) if isinstance(values, dict) else set(values)
        return [field.key for field in ENV_SCHEMA if field.key in value_keys]

    @staticmethod
    def _impact_keys(keys: list[str], *, restart: bool = False, rebuild: bool = False) -> list[str]:
        result: list[str] = []
        for key in keys:
            field = _FIELD_BY_KEY[key]
            if restart and field.restart_required:
                result.append(key)
            if rebuild and field.rebuild_required:
                result.append(key)
        return result
