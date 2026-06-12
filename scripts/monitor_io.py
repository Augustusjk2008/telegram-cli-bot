#!/usr/bin/env python3
"""Monitor Web chat I/O and compare recorded native session output."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Recorder:
    root: Path | None
    run_id: str

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def prepare(self) -> None:
        if self.root is None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "native_sessions").mkdir(parents=True, exist_ok=True)

    def append(self, relative_path: str, record: dict[str, Any]) -> None:
        if self.root is None:
            return
        payload = {
            **record,
            "run_id": self.run_id,
            "ts_wall": wall_ts(),
            "ts_mono_ms": mono_ms(),
        }
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> None:
        if self.root is None:
            return
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class MonitorState:
    recorder: Recorder
    seen_message_ids: set[str] = field(default_factory=set)
    web_message_signatures: dict[str, str] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor Orbit Safe Claw Web chat I/O and compare recorded native sessions.",
    )
    parser.add_argument("--web-url", default="http://127.0.0.1:8765", help="Web API base URL.")
    parser.add_argument("--password", default="", help="Web API token.")
    parser.add_argument("--alias", default="", help="Bot alias to monitor. Empty means all bots.")
    parser.add_argument("--agent-id", default="main", help="Agent id for Web history scope.")
    parser.add_argument("--execution-mode", default="", choices=("", "cli", "native_agent"), help="History scope.")
    parser.add_argument("--interval", type=float, default=1.5, help="Polling interval seconds.")
    parser.add_argument("--limit", type=int, default=80, help="History items fetched per bot.")
    parser.add_argument("--once", action="store_true", help="Poll once and exit.")
    parser.add_argument("--include-existing", action="store_true", help="Print already existing history on startup.")
    parser.add_argument("--show-trace", action="store_true", help="Reserved for future trace output.")
    parser.add_argument("--record-dir", default="", help="Directory for JSONL snapshots and reports.")
    parser.add_argument("--run-id", default="", help="Run id written into records.")
    parser.add_argument("--compare", action="store_true", help="Generate comparison_report.json from record-dir.")
    parser.add_argument("--no-web", action="store_true", help="Skip live Web polling; only use compare/report flow.")
    return parser.parse_args()


def wall_ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mono_ms() -> int:
    return int(time.monotonic() * 1000)


def log(line: str) -> None:
    print(f"[{now_text()}] {line}", flush=True)


def stable_json_signature(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(data.encode("utf-8", errors="replace")).hexdigest()


def request_json(
    url: str,
    *,
    token: str = "",
    timeout: float = 20.0,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> Any:
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")
    return json.loads(payload) if payload.strip() else {}


def web_api_url(base_url: str, path: str, query: dict[str, Any] | None = None) -> str:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if query:
        pairs = {key: value for key, value in query.items() if value not in (None, "")}
        if pairs:
            url = f"{url}?{urllib.parse.urlencode(pairs)}"
    return url


def list_bot_aliases(base_url: str, password: str, requested_alias: str) -> list[str]:
    if requested_alias:
        return [requested_alias]
    payload = request_json(web_api_url(base_url, "/api/bots"), token=password)
    data = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(data, list):
        return []
    return [str(item.get("alias") or "").strip() for item in data if isinstance(item, dict) and item.get("alias")]


def poll_all(args: argparse.Namespace, state: MonitorState, *, initial: bool = False) -> None:
    if args.no_web:
        return
    poll_web_history(args, state, initial=initial)


def poll_web_history(args: argparse.Namespace, state: MonitorState, *, initial: bool = False) -> None:
    aliases = list_bot_aliases(args.web_url, args.password, getattr(args, "alias", ""))
    for alias in aliases:
        query = {
            "limit": int(getattr(args, "limit", 80) or 80),
            "execution_mode": getattr(args, "execution_mode", ""),
            "agent_id": getattr(args, "agent_id", "main"),
        }
        payload = request_json(
            web_api_url(args.web_url, f"/api/bots/{alias}/history", query),
            token=getattr(args, "password", ""),
        )
        data = payload.get("data") if isinstance(payload, dict) else {}
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            continue
        state.recorder.append(
            "web_history_snapshots.jsonl",
            {
                "kind": "web_history_snapshot",
                "alias": alias,
                "items": items,
            },
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or "").strip()
            if not message_id:
                continue
            signature = stable_json_signature(
                {
                    "role": item.get("role"),
                    "content": item.get("content"),
                    "state": item.get("state"),
                    "completion_state": (item.get("meta") or {}).get("completion_state")
                    if isinstance(item.get("meta"), dict)
                    else "",
                }
            )
            previous_signature = state.web_message_signatures.get(message_id)
            state.web_message_signatures[message_id] = signature
            if message_id not in state.seen_message_ids:
                state.seen_message_ids.add(message_id)
                if initial and getattr(args, "include_existing", False):
                    _print_web_history_item(alias, item)
                continue
            if previous_signature != signature and str(item.get("role") or "").strip().lower() == "assistant":
                _print_web_history_item(alias, item)


def _print_web_history_item(alias: str, item: dict[str, Any]) -> None:
    role = str(item.get("role") or "").strip().lower() or "assistant"
    state = str(item.get("state") or "").strip() or "done"
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    completion_state = str(meta.get("completion_state") or "").strip() or state
    content = str(item.get("content") or "").strip()
    log(f"WEB {alias} {role} ({state}, {completion_state}): {content}")


def normalize_web_stream_event(alias: str, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
    native_source = meta.get("native_source") if isinstance(meta.get("native_source"), dict) else {}
    assistant_message_id = str(payload.get("assistant_message_id") or message.get("id") or "").strip()
    return {
        "kind": "web_stream_event",
        "alias": alias,
        "prompt": prompt,
        "event_type": str(payload.get("type") or "").strip(),
        "turn_id": str(payload.get("turn_id") or "").strip(),
        "assistant_message_id": assistant_message_id,
        "web_message_id": assistant_message_id,
        "native_assistant_message_id": str(
            payload.get("native_assistant_message_id")
            or native_source.get("message_id")
            or native_source.get("native_assistant_message_id")
            or ""
        ).strip(),
        "native_session_id": str(
            payload.get("native_session_id")
            or native_source.get("session_id")
            or native_source.get("native_session_id")
            or ""
        ).strip(),
        "history_content": str(
            payload.get("output")
            or message.get("content")
            or payload.get("text")
            or ""
        ),
    }


def normalize_native_event(raw: dict[str, Any], *, alias: str = "") -> dict[str, Any]:
    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    payload = properties or raw
    permission = payload.get("permission") if isinstance(payload.get("permission"), dict) else {}
    part = payload.get("part") if isinstance(payload.get("part"), dict) else {}
    tool_name = str(
        part.get("toolName")
        or part.get("tool_name")
        or part.get("tool")
        or payload.get("toolName")
        or payload.get("tool_name")
        or payload.get("tool")
        or ""
    ).strip()
    return {
        "kind": "native_event",
        "alias": alias,
        "event_type": str(raw.get("type") or raw.get("event") or "").strip(),
        "native_session_id": str(
            payload.get("sessionID")
            or payload.get("session_id")
            or payload.get("sessionId")
            or ""
        ).strip(),
        "native_message_id": str(
            payload.get("messageID")
            or payload.get("message_id")
            or payload.get("messageId")
            or ""
        ).strip(),
        "part_id": str(payload.get("partID") or payload.get("part_id") or payload.get("partId") or "").strip(),
        "delta_text": str(payload.get("delta") or payload.get("text") or "").strip(),
        "status": str(payload.get("status") or permission.get("state") or "").strip(),
        "call_id": str(
            payload.get("toolCallId")
            or payload.get("tool_call_id")
            or payload.get("callID")
            or payload.get("call_id")
            or ""
        ).strip(),
        "tool_name": tool_name,
        "permission": permission,
        "tool_count": 1 if tool_name else 0,
    }


def compare_conversation_session_consistency(history_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sessions_by_conversation: dict[str, set[str]] = {}
    for snapshot in history_snapshots:
        items = snapshot.get("items") if isinstance(snapshot, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "").strip().lower() != "assistant":
                continue
            conversation_id = str(item.get("conversation_id") or "").strip()
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            native_session_id = str(meta.get("native_session_id") or "").strip()
            if not conversation_id or not native_session_id:
                continue
            sessions_by_conversation.setdefault(conversation_id, set()).add(native_session_id)
    issues: list[dict[str, Any]] = []
    for conversation_id, native_session_ids in sorted(sessions_by_conversation.items()):
        if len(native_session_ids) <= 1:
            continue
        issues.append(
            {
                "code": "conversation_session_changed",
                "message": "同一会话出现多个 native_session_id",
                "evidence": {
                    "conversation_id": conversation_id,
                    "native_session_ids": sorted(native_session_ids),
                },
            }
        )
    return issues


def generate_comparison_report(record_dir: Path, run_id: str) -> dict[str, Any]:
    history_snapshots = _read_jsonl(record_dir / "web_history_snapshots.jsonl")
    stream_events = _read_jsonl(record_dir / "web_stream_events.jsonl")
    native_messages = _load_native_session_messages(record_dir / "native_sessions")

    turns: dict[str, dict[str, Any]] = {}
    for snapshot in history_snapshots:
        items = snapshot.get("items") if isinstance(snapshot, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "").strip().lower() != "assistant":
                continue
            turn_id = str(item.get("turn_id") or "").strip()
            if not turn_id:
                continue
            turn_key = f"turn:{turn_id}"
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            turns.setdefault(turn_key, _empty_turn(turn_id))
            turns[turn_key]["history"] = {
                "assistant_message_id": str(item.get("id") or "").strip(),
                "final_assistant_text": str(item.get("content") or ""),
                "native_session_id": str(meta.get("native_session_id") or "").strip(),
            }

    for event in stream_events:
        if not isinstance(event, dict):
            continue
        turn_id = str(event.get("turn_id") or "").strip()
        if not turn_id:
            continue
        turn_key = f"turn:{turn_id}"
        turns.setdefault(turn_key, _empty_turn(turn_id))
        native_session_id = str(event.get("native_session_id") or "").strip()
        native_message_id = str(event.get("native_assistant_message_id") or "").strip()
        native_text = native_messages.get(native_session_id, {}).get(native_message_id, "")
        turns[turn_key]["stream"] = {
            "assistant_message_id": str(event.get("assistant_message_id") or "").strip(),
            "final_assistant_text": str(event.get("history_content") or ""),
            "native_session_id": native_session_id,
        }
        turns[turn_key]["native"] = {
            "session_id": native_session_id,
            "assistant_message_id": native_message_id,
            "final_assistant_text": native_text,
        }

    issue_count = 0
    for turn in turns.values():
        issues: list[dict[str, Any]] = []
        history_text = str((turn.get("history") or {}).get("final_assistant_text") or "")
        stream_text = str((turn.get("stream") or {}).get("final_assistant_text") or "")
        native_text = str((turn.get("native") or {}).get("final_assistant_text") or "")
        if history_text and stream_text and history_text != stream_text:
            issues.append({"code": "history_stream_mismatch", "history": history_text, "stream": stream_text})
        if history_text and native_text and history_text != native_text:
            issues.append({"code": "history_native_mismatch", "history": history_text, "native": native_text})
        turn["issues"] = issues
        issue_count += len(issues)

    issues = compare_conversation_session_consistency(history_snapshots)
    issue_count += len(issues)
    return {
        "run_id": run_id,
        "summary": {
            "turns_compared": len(turns),
            "issue_count": issue_count,
        },
        "turns": turns,
        "conversation_issues": issues,
    }


def _empty_turn(turn_id: str) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "history": {},
        "stream": {},
        "native": {},
        "issues": [],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _load_native_session_messages(root: Path) -> dict[str, dict[str, str]]:
    if not root.is_dir():
        return {}
    sessions: dict[str, dict[str, str]] = {}
    for path in sorted(root.glob("*.messages.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        session_id = str(payload.get("native_session_id") or payload.get("session_id") or "").strip()
        messages = payload.get("messages")
        if not session_id or not isinstance(messages, list):
            continue
        sessions[session_id] = {
            str(item.get("id") or "").strip(): str(item.get("content") or "")
            for item in messages
            if isinstance(item, dict) and str(item.get("role") or "").strip().lower() == "assistant"
        }
    return sessions


def main() -> int:
    args = parse_args()
    record_root = Path(args.record_dir).expanduser() if args.record_dir else None
    recorder = Recorder(record_root, args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S"))
    recorder.prepare()
    state = MonitorState(recorder=recorder)
    try:
        if args.compare:
            if record_root is None:
                raise RuntimeError("--compare 需要 --record-dir")
            report = generate_comparison_report(record_root, recorder.run_id)
            recorder.write_json("comparison_report.json", report)
            log(f"comparison complete: turns={report['summary']['turns_compared']} issues={report['summary']['issue_count']}")
            if args.no_web or args.once:
                return 0
        if args.no_web:
            return 0
        poll_all(args, state, initial=True)
        if args.once:
            return 0
        while True:
            time.sleep(max(0.1, float(args.interval or 1.5)))
            poll_all(args, state)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        log(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
