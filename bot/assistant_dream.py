from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bot.assistant_home import AssistantHome
from bot.assistant_proposals import create_proposal
from bot.models import BotProfile, UserSession

if TYPE_CHECKING:
    from bot.web.chat_history_service import ChatHistoryService

_DREAM_RESULT_RE = re.compile(r"<DREAM_RESULT>\s*(\{.*\})\s*</DREAM_RESULT>\s*$", re.DOTALL)
_SAFE_BUCKET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")
_WORKING_MEMORY_LIMITS: dict[str, tuple[int, int]] = {
    "current_goal": (3, 180),
    "open_loops": (8, 180),
    "user_prefs": (10, 180),
    "recent_summary": (8, 220),
}


@dataclass(frozen=True)
class AssistantDreamConfig:
    prompt: str
    lookback_hours: int = 24
    history_limit: int = 40
    capture_limit: int = 20
    deliver_mode: str = "silent"

    @classmethod
    def from_task_payload(cls, payload: dict[str, Any] | None) -> "AssistantDreamConfig":
        data = dict(payload or {})
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("dream task.prompt 不能为空")
        lookback_hours = int(data.get("lookback_hours") or 24)
        history_limit = int(data.get("history_limit") or 40)
        capture_limit = int(data.get("capture_limit") or 20)
        if lookback_hours <= 0 or history_limit <= 0 or capture_limit <= 0:
            raise ValueError("dream 上下文窗口参数必须大于 0")
        deliver_mode = str(data.get("deliver_mode") or "silent").strip().lower() or "silent"
        if deliver_mode not in {"chat_handoff", "silent"}:
            raise ValueError("dream deliver_mode 仅支持 chat_handoff 或 silent")
        return cls(
            prompt=prompt,
            lookback_hours=lookback_hours,
            history_limit=history_limit,
            capture_limit=capture_limit,
            deliver_mode=deliver_mode,
        )


@dataclass(frozen=True)
class AssistantDreamPreparedPrompt:
    prompt_text: str
    context_stats: dict[str, Any]


@dataclass(frozen=True)
class AssistantDreamApplyResult:
    summary: str
    applied_paths: list[str]
    proposal_id: str | None
    audit_path: str


def _read_optional_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _clip_text(value: str, *, limit: int) -> str:
    compact = str(value or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iter_recent_capture_records(home: AssistantHome, *, capture_limit: int, cutoff: datetime) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    captures_dir = home.root / "inbox" / "captures"
    for path in sorted(captures_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        created_at = _parse_iso_datetime(str(payload.get("created_at") or ""))
        if created_at is None or created_at < cutoff:
            continue
        items.append(payload)
        if len(items) >= capture_limit:
            break
    items.reverse()
    return items


def _format_history_items(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        role = str(item.get("role") or "unknown").strip() or "unknown"
        created_at = str(item.get("created_at") or "").strip()
        content = _clip_text(str(item.get("content") or ""), limit=600)
        if not content:
            continue
        lines.append(f"- [{created_at}] {role}: {content}")
    return "\n".join(lines)


def _format_capture_items(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        created_at = str(item.get("created_at") or "").strip()
        user_text = _clip_text(str(item.get("user_text") or ""), limit=320)
        assistant_text = _clip_text(str(item.get("assistant_text") or ""), limit=480)
        lines.append(f"- [{created_at}] user: {user_text}")
        lines.append(f"  assistant: {assistant_text}")
    return "\n".join(lines)


def prepare_dream_prompt(
    home: AssistantHome,
    *,
    profile: BotProfile,
    session: UserSession,
    history_service: ChatHistoryService,
    config: AssistantDreamConfig,
    visible_text: str,
) -> AssistantDreamPreparedPrompt:
    cutoff = datetime.now(UTC) - timedelta(hours=config.lookback_hours)
    raw_history = history_service.list_history(profile, session, limit=config.history_limit)
    recent_history = [
        item
        for item in raw_history
        if (_parse_iso_datetime(str(item.get("created_at") or "")) or datetime.min.replace(tzinfo=UTC)) >= cutoff
    ]
    recent_captures = _iter_recent_capture_records(
        home,
        capture_limit=config.capture_limit,
        cutoff=cutoff,
    )

    current_goal = _read_optional_text(home.root / "memory" / "working" / "current_goal.md")
    open_loops = _read_optional_text(home.root / "memory" / "working" / "open_loops.md")
    user_prefs = _read_optional_text(home.root / "memory" / "working" / "user_prefs.md")
    recent_summary = _read_optional_text(home.root / "memory" / "working" / "recent_summary.md")
    agents_text = _read_optional_text(home.workdir / "AGENTS.md")
    claude_text = _read_optional_text(home.workdir / "CLAUDE.md")

    history_block = _format_history_items(recent_history) or "- 无"
    capture_block = _format_capture_items(recent_captures) or "- 无"

    prompt_text = "\n\n".join(
        [
            "你正在执行一个后台 dream 自维护任务。任务必须单轮完成，不能向用户提问，不能要求额外确认。",
            "原则：只基于提供的证据归纳；拿不准的内容写到 open_loops 或 proposal；不要编造用户状态。",
            "边界：不要直接修改业务源码；涉及代码、长期规则、技能安装或协议升级时，只能通过 proposal 提交。",
            "你需要先输出 1 到 3 句中文摘要，然后在最后输出一个严格的 JSON envelope，格式必须是 <DREAM_RESULT>{json}</DREAM_RESULT>。",
            (
                "JSON 必须包含 summary、working_memory、knowledge_entries、proposal 四个字段；"
                "working_memory 只允许 current_goal/open_loops/user_prefs/recent_summary 四个 key；"
                "knowledge_entries 是数组；proposal 可以为 null。"
            ),
            f"用户配置的 dream 提示词：{config.prompt}",
            f"当前这轮任务的可见提示词：{visible_text}",
            "## 当前工作记忆",
            f"### current_goal\n{current_goal or '- 无'}",
            f"### open_loops\n{open_loops or '- 无'}",
            f"### user_prefs\n{user_prefs or '- 无'}",
            f"### recent_summary\n{recent_summary or '- 无'}",
            "## 当前协议",
            f"### AGENTS.md\n{agents_text or '- 无'}",
            f"### CLAUDE.md\n{claude_text or '- 无'}",
            "## 最近聊天历史",
            history_block,
            "## 最近 captures",
            capture_block,
        ]
    )

    return AssistantDreamPreparedPrompt(
        prompt_text=prompt_text,
        context_stats={
            "lookback_hours": config.lookback_hours,
            "history_count": len(recent_history),
            "capture_count": len(recent_captures),
            "history_limit": config.history_limit,
            "capture_limit": config.capture_limit,
        },
    )


def _extract_dream_payload(raw_output: str) -> tuple[dict[str, Any], str]:
    text = str(raw_output or "").strip()
    match = _DREAM_RESULT_RE.search(text)
    if match is None:
        raise ValueError("dream 输出缺少 <DREAM_RESULT> JSON")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"dream JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("dream JSON 顶层必须是对象")
    summary = str(payload.get("summary") or text[: match.start()]).strip()
    return payload, summary


def _normalize_list_items(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.splitlines()
    elif isinstance(value, list):
        candidates = [str(item) for item in value]
    else:
        raise ValueError("dream 列表字段必须是字符串或字符串数组")

    items: list[str] = []
    for raw_item in candidates:
        stripped = str(raw_item or "").strip()
        if not stripped:
            continue
        stripped = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", stripped)
        items.append(_clip_text(stripped, limit=max_chars))
        if len(items) >= max_items:
            break
    return items


def _render_markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item).strip()


def _validate_working_memory(payload: Any) -> dict[str, str]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("dream working_memory 必须是对象")
    normalized: dict[str, str] = {}
    for key, value in payload.items():
        if key not in _WORKING_MEMORY_LIMITS:
            raise ValueError(f"不支持的 working_memory key: {key}")
        max_items, max_chars = _WORKING_MEMORY_LIMITS[key]
        items = _normalize_list_items(value, max_items=max_items, max_chars=max_chars)
        if items:
            normalized[key] = _render_markdown_list(items)
    return normalized


def _normalize_knowledge_entries(payload: Any) -> list[tuple[str, str, str]]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("dream knowledge_entries 必须是数组")
    entries: list[tuple[str, str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("dream knowledge entry 必须是对象")
        bucket = str(item.get("bucket") or "").strip()
        if not _SAFE_BUCKET_RE.fullmatch(bucket):
            raise ValueError(f"非法 knowledge bucket: {bucket}")
        title = _clip_text(str(item.get("title") or "").strip(), limit=120)
        body_items = _normalize_list_items(item.get("body"), max_items=12, max_chars=220)
        if not body_items:
            raise ValueError("dream knowledge entry 不能为空")
        body = _render_markdown_list(body_items)
        entries.append((bucket, title, body))
    return entries


def _normalize_proposal(payload: Any) -> dict[str, str] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("dream proposal 必须是对象或 null")
    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not title or not body:
        raise ValueError("dream proposal 需要 title 和 body")
    kind = str(payload.get("kind") or "rule").strip() or "rule"
    return {
        "kind": kind,
        "title": _clip_text(title, limit=120),
        "body": body,
    }


def _slugify(value: str) -> str:
    slug = _SAFE_SLUG_RE.sub("-", value.lower()).strip("-")
    return slug[:48] or "entry"


def _dream_audit_path(home: AssistantHome, *, run_id: str, job_id: str | None, scheduled_at: str | None) -> Path:
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(job_id or "adhoc")).strip("-") or "adhoc"
    safe_scheduled_at = re.sub(r"[^0-9A-Za-z._-]+", "-", str(scheduled_at or datetime.now(UTC).isoformat())).strip("-")
    return home.root / "audit" / "dream" / f"{safe_scheduled_at}--{safe_job_id}--{run_id}.json"


def _write_dream_audit(
    home: AssistantHome,
    *,
    raw_output: str,
    visible_text: str,
    prompt_excerpt: str,
    context_stats: dict[str, Any],
    run_id: str,
    job_id: str | None,
    scheduled_at: str | None,
    context_user_id: int | None,
    synthetic_user_id: int,
    summary: str,
    applied_paths: list[str],
    proposal_id: str | None,
    error: str,
) -> str:
    path = _dream_audit_path(home, run_id=run_id, job_id=job_id, scheduled_at=scheduled_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "job_id": job_id or "",
        "task_mode": "dream",
        "scheduled_at": scheduled_at or "",
        "created_at": datetime.now(UTC).isoformat(),
        "context_user_id": context_user_id,
        "synthetic_user_id": synthetic_user_id,
        "visible_text": visible_text,
        "prompt_excerpt": prompt_excerpt,
        "context_stats": context_stats,
        "summary": summary,
        "applied_paths": applied_paths,
        "proposal_id": proposal_id,
        "error": error,
        "raw_output": raw_output,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def apply_dream_result(
    home: AssistantHome,
    *,
    raw_output: str,
    visible_text: str,
    prompt_excerpt: str,
    context_stats: dict[str, Any],
    run_id: str,
    job_id: str | None,
    scheduled_at: str | None,
    context_user_id: int | None,
    synthetic_user_id: int,
) -> AssistantDreamApplyResult:
    applied_paths: list[str] = []
    proposal_id: str | None = None
    summary = ""
    try:
        payload, summary = _extract_dream_payload(raw_output)
        working_memory = _validate_working_memory(payload.get("working_memory"))
        knowledge_entries = _normalize_knowledge_entries(payload.get("knowledge_entries"))
        proposal_payload = _normalize_proposal(payload.get("proposal"))
        summary = _clip_text(summary or "dream 已完成", limit=240)

        for key, content in working_memory.items():
            path = home.root / "memory" / "working" / f"{key}.md"
            path.write_text(content + "\n", encoding="utf-8")
            applied_paths.append(str(path))

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        for index, (bucket, title, body) in enumerate(knowledge_entries, start=1):
            bucket_dir = home.root / "memory" / "knowledge" / bucket
            bucket_dir.mkdir(parents=True, exist_ok=True)
            slug = _slugify(title)
            path = bucket_dir / f"{timestamp}-{index:02d}-{slug}.md"
            content = f"# {title}\n\n{body}\n" if title else body + "\n"
            path.write_text(content, encoding="utf-8")
            applied_paths.append(str(path))

        if proposal_payload is not None:
            proposal = create_proposal(
                home,
                kind=proposal_payload["kind"],
                title=proposal_payload["title"],
                body=proposal_payload["body"],
            )
            proposal_id = str(proposal.get("id") or "").strip() or None

        audit_path = _write_dream_audit(
            home,
            raw_output=raw_output,
            visible_text=visible_text,
            prompt_excerpt=prompt_excerpt,
            context_stats=context_stats,
            run_id=run_id,
            job_id=job_id,
            scheduled_at=scheduled_at,
            context_user_id=context_user_id,
            synthetic_user_id=synthetic_user_id,
            summary=summary,
            applied_paths=applied_paths,
            proposal_id=proposal_id,
            error="",
        )
        return AssistantDreamApplyResult(
            summary=summary,
            applied_paths=applied_paths,
            proposal_id=proposal_id,
            audit_path=audit_path,
        )
    except Exception as exc:
        audit_path = _write_dream_audit(
            home,
            raw_output=raw_output,
            visible_text=visible_text,
            prompt_excerpt=prompt_excerpt,
            context_stats=context_stats,
            run_id=run_id,
            job_id=job_id,
            scheduled_at=scheduled_at,
            context_user_id=context_user_id,
            synthetic_user_id=synthetic_user_id,
            summary=summary,
            applied_paths=applied_paths,
            proposal_id=proposal_id,
            error=str(exc),
        )
        raise RuntimeError(f"dream 结果处理失败，审计已写入: {audit_path}") from exc
