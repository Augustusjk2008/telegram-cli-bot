#!/usr/bin/env python3
"""Monitor Web chat I/O and optional opencode native-agent events."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


TRACE_KIND_TOOL = {"tool_call", "tool_result", "permission"}
TOOL_FOLLOWUP_FINISH = {"tool-calls", "tool_calls", "tool-call", "tool_call"}


@dataclass
class Recorder:
    root: Path | None
    run_id: str
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def prepare(self) -> None:
        if self.root is None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "opencode_sessions").mkdir(parents=True, exist_ok=True)

    def append(self, relative_path: str, record: dict[str, Any]) -> None:
        if self.root is None:
            return
        payload = dict(record)
        payload.setdefault("run_id", self.run_id)
        payload.setdefault("ts_wall", wall_ts())
        payload.setdefault("ts_mono_ms", mono_ms())
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def write_json(self, relative_path: str, payload: dict[str, Any]) -> None:
        if self.root is None:
            return
        data = dict(payload)
        data.setdefault("run_id", self.run_id)
        data.setdefault("ts_wall", wall_ts())
        data.setdefault("ts_mono_ms", mono_ms())
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_text(self, relative_path: str, text: str) -> None:
        if self.root is None:
            return
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            path.write_text(text, encoding="utf-8")


@dataclass
class MonitorState:
    recorder: Recorder
    seen_message_ids: set[str] = field(default_factory=set)
    web_message_signatures: dict[str, str] = field(default_factory=dict)
    trace_counts: dict[str, int] = field(default_factory=dict)
    trace_signatures: dict[str, str] = field(default_factory=dict)
    current_opencode_text: dict[str, str] = field(default_factory=dict)
    known_native_session_ids: set[str] = field(default_factory=set)
    opencode_session_signatures: dict[str, str] = field(default_factory=dict)
    opencode_base_url: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor Orbit Safe Claw Web chat input/output and optional opencode events.",
    )
    parser.add_argument("--web-url", default="http://127.0.0.1:8765", help="Web API base URL.")
    parser.add_argument("--password", default="", help="Web API token. Also used as opencode password by default.")
    parser.add_argument("--alias", default="", help="Bot alias to monitor. Empty means all bots.")
    parser.add_argument("--agent-id", default="main", help="Agent id for Web history/stream scope.")
    parser.add_argument("--execution-mode", default="", choices=("", "cli", "native_agent"), help="History scope.")
    parser.add_argument("--interval", type=float, default=1.5, help="Polling interval seconds.")
    parser.add_argument("--limit", type=int, default=80, help="History items fetched per bot.")
    parser.add_argument("--once", action="store_true", help="Print current data once and exit.")
    parser.add_argument("--include-existing", action="store_true", help="Print already existing history on startup.")
    parser.add_argument("--show-trace", action="store_true", help="Fetch and print assistant trace/tool events.")
    parser.add_argument(
        "--opencode-url",
        default="",
        help="Optional opencode server base URL, e.g. http://127.0.0.1:4096. Use 'auto' to discover serve processes.",
    )
    parser.add_argument("--opencode-password", default="", help="Override opencode password.")
    parser.add_argument("--opencode-username", default="opencode", help="opencode basic-auth username.")
    parser.add_argument("--no-web", action="store_true", help="Only monitor opencode events.")
    parser.add_argument("--record-dir", default="", help="Directory for JSONL snapshots and reports.")
    parser.add_argument("--run-id", default="", help="Run id written into records.")
    parser.add_argument("--capture-web-stream", action="store_true", help="Actively POST Web chat/stream and record SSE.")
    parser.add_argument("--capture-opencode-sse", action="store_true", help="Record opencode /global/event SSE.")
    parser.add_argument("--capture-session-messages", action="store_true", help="Poll opencode session messages for known sessions.")
    parser.add_argument("--compare", action="store_true", help="Generate comparison_report.json/.md from record-dir.")
    parser.add_argument("--prompt", action="append", default=[], help="Prompt for --capture-web-stream. Repeatable. Use '-' for stdin.")
    parser.add_argument("--prompt-file", default="", help="One prompt per non-empty line for --capture-web-stream.")
    parser.add_argument("--post-done-seconds", type=float, default=10.0, help="Extra polling after Web stream done.")
    parser.add_argument("--web-stream-protocol", choices=("legacy", "ag-ui"), default="legacy", help="Web stream protocol.")
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
    basic: tuple[str, str] | None = None,
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
    if basic is not None:
        user, password = basic
        encoded = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")
    return json.loads(payload) if payload.strip() else {}


def stream_sse(
    url: str,
    *,
    token: str = "",
    basic: tuple[str, str] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> Iterable[dict[str, Any]]:
    headers = {"Accept": "text/event-stream"}
    data: bytes | None = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic is not None:
        user, password = basic
        encoded = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=None) as response:
        buffer = ""
        while True:
            chunk = response.read(4096)
            if not chunk:
                return
            buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                event = parse_sse_block(block)
                if event is not None:
                    yield event


def parse_sse_block(block: str) -> dict[str, Any] | None:
    event_name = ""
    data_lines: list[str] = []
    for line in str(block or "").split("\n"):
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    raw_data = "\n".join(data_lines)
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        payload = {"data": raw_data}
    if not isinstance(payload, dict):
        payload = {"data": payload}
    if event_name and "type" not in payload:
        payload["type"] = event_name
    return payload


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


def opencode_basic(args: argparse.Namespace) -> tuple[str, str]:
    return (args.opencode_username, args.opencode_password or args.password)


def poll_all(args: argparse.Namespace, state: MonitorState, *, initial: bool = False) -> None:
    if not args.no_web:
        poll_web_history(args, state, initial=initial)
        poll_web_session(args, state)
    if args.capture_session_messages:
        poll_opencode_session_messages(args, state)


def poll_web_history(args: argparse.Namespace, state: MonitorState, *, initial: bool = False) -> None:
    try:
        aliases = list_bot_aliases(args.web_url, args.password, args.alias)
    except Exception as exc:
        log(f"WEB bots fetch failed: {exc}")
        state.recorder.append("web_history_snapshots.jsonl", {"kind": "web_history_error", "error": str(exc)})
        return
    for alias in aliases:
        query = {
            "limit": max(1, int(args.limit)),
            "execution_mode": args.execution_mode,
            "agent_id": args.agent_id,
        }
        url = web_api_url(args.web_url, f"/api/bots/{urllib.parse.quote(alias)}/history", query)
        try:
            payload = request_json(url, token=args.password)
        except Exception as exc:
            log(f"WEB {alias} history fetch failed: {exc}")
            state.recorder.append(
                "web_history_snapshots.jsonl",
                {"kind": "web_history_error", "alias": alias, "error": str(exc)},
            )
            continue
        data = payload.get("data") if isinstance(payload, dict) else {}
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []
        record_web_history_snapshot(state, alias, items)
        for item in items:
            if not isinstance(item, dict):
                continue
            remember_native_session_id(state, native_session_id_from_web_message(item))
            message_id = str(item.get("id") or "").strip()
            if not message_id:
                continue
            signature = web_message_print_signature(item)
            with state.lock:
                previous_signature = state.web_message_signatures.get(message_id, "")
                changed = previous_signature != signature
                state.web_message_signatures[message_id] = signature
                already_seen = message_id in state.seen_message_ids
                if not already_seen:
                    state.seen_message_ids.add(message_id)
            if already_seen:
                if changed and should_print_seen_message_update(item):
                    print_web_message(alias, item)
                maybe_print_trace(args, state, alias, item)
                continue
            if initial and not args.include_existing:
                maybe_print_trace(args, state, alias, item)
                continue
            print_web_message(alias, item)
            maybe_print_trace(args, state, alias, item)


def web_message_print_signature(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return stable_json_signature(
        {
            "role": str(item.get("role") or ""),
            "state": str(item.get("state") or ""),
            "completion_state": str(meta.get("completion_state") or ""),
            "native_session_id": native_session_id_from_web_message(item),
            "content": str(item.get("content") or item.get("text") or ""),
        }
    )


def should_print_seen_message_update(item: dict[str, Any]) -> bool:
    return str(item.get("role") or "").strip().lower() == "assistant"


def record_web_history_snapshot(state: MonitorState, alias: str, items: list[Any]) -> None:
    assistant_items = [item for item in items if isinstance(item, dict) and str(item.get("role") or "").lower() == "assistant"]
    last_item = assistant_items[-1] if assistant_items else (items[-1] if items and isinstance(items[-1], dict) else {})
    summary = summarize_web_message(last_item) if isinstance(last_item, dict) else {}
    state.recorder.append(
        "web_history_snapshots.jsonl",
        {
            "kind": "web_history_snapshot",
            "alias": alias,
            "item_count": len(items),
            "items": items,
            **summary,
        },
    )


def print_web_message(alias: str, item: dict[str, Any]) -> None:
    role = str(item.get("role") or "?").strip()
    state_text = str(item.get("state") or "").strip()
    content = str(item.get("content") or item.get("text") or "").strip()
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    completion = str(meta.get("completion_state") or "").strip()
    native_session = native_session_id_from_web_message(item)
    suffix_items = [value for value in (state_text, completion, native_session) if value]
    suffix = f" ({', '.join(suffix_items)})" if suffix_items else ""
    log(f"WEB {alias} {role}{suffix}: {content}")


def maybe_print_trace(args: argparse.Namespace, state: MonitorState, alias: str, item: dict[str, Any]) -> None:
    should_fetch = args.show_trace or state.recorder.enabled
    if not should_fetch:
        return
    if str(item.get("role") or "").lower() != "assistant":
        return
    message_id = str(item.get("id") or "").strip()
    if not message_id:
        return
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    expected_count = int(meta.get("trace_count") or 0)
    with state.lock:
        known_count = state.trace_counts.get(message_id, 0)
    if args.show_trace and known_count >= expected_count and expected_count > 0:
        return
    query = {"execution_mode": args.execution_mode, "agent_id": args.agent_id}
    url = web_api_url(args.web_url, f"/api/bots/{urllib.parse.quote(alias)}/history/{message_id}/trace", query)
    try:
        payload = request_json(url, token=args.password)
    except Exception as exc:
        log(f"TRACE {alias} {message_id}: fetch failed: {exc}")
        state.recorder.append(
            "web_trace_snapshots.jsonl",
            {"kind": "web_trace_error", "alias": alias, "web_message_id": message_id, "error": str(exc)},
        )
        return
    data = payload.get("data") if isinstance(payload, dict) else {}
    traces = data.get("trace") if isinstance(data, dict) else []
    if not isinstance(traces, list):
        traces = []
    signature = stable_json_signature(traces)
    with state.lock:
        old_signature = state.trace_signatures.get(message_id, "")
        state.trace_signatures[message_id] = signature
        state.trace_counts[message_id] = len(traces)
    if state.recorder.enabled and signature != old_signature:
        trace_tool_count = sum(1 for trace in traces if isinstance(trace, dict) and is_web_trace_tool(trace))
        state.recorder.append(
            "web_trace_snapshots.jsonl",
            {
                "kind": "web_trace_snapshot",
                "alias": alias,
                "web_message_id": message_id,
                "native_session_id": native_session_id_from_web_message(item),
                "history_content": str(item.get("content") or ""),
                "trace_count": len(traces),
                "tool_count": trace_tool_count,
                "trace": traces,
            },
        )
    if not args.show_trace:
        return
    start = known_count
    for trace in traces[start:]:
        if not isinstance(trace, dict):
            continue
        kind = str(trace.get("kind") or "trace")
        tool = str(trace.get("tool_name") or "").strip()
        summary = str(trace.get("summary") or "").strip()
        label = f"{kind}:{tool}" if tool else kind
        log(f"TRACE {alias} {message_id} {label}: {summary}")


def poll_web_session(args: argparse.Namespace, state: MonitorState) -> None:
    try:
        aliases = list_bot_aliases(args.web_url, args.password, args.alias)
    except Exception:
        return
    for alias in aliases:
        query = {"execution_mode": args.execution_mode, "agent_id": args.agent_id}
        url = web_api_url(args.web_url, f"/api/bots/{urllib.parse.quote(alias)}", query)
        try:
            payload = request_json(url, token=args.password)
        except Exception as exc:
            state.recorder.append(
                "web_session_snapshots.jsonl",
                {"kind": "web_session_error", "alias": alias, "error": str(exc)},
            )
            continue
        data = payload.get("data") if isinstance(payload, dict) else {}
        session = data.get("session") if isinstance(data, dict) and isinstance(data.get("session"), dict) else {}
        session_ids = session.get("session_ids") if isinstance(session.get("session_ids"), dict) else {}
        native_session_id = str(session_ids.get("native_agent_session_id") or "").strip()
        remember_native_session_id(state, native_session_id)
        running_reply = session.get("running_reply") if isinstance(session.get("running_reply"), dict) else None
        state.recorder.append(
            "web_session_snapshots.jsonl",
            {
                "kind": "web_session_snapshot",
                "alias": alias,
                "native_session_id": native_session_id,
                "running_reply": running_reply,
                "session": session,
                "bot": data.get("bot") if isinstance(data, dict) else {},
            },
        )


def capture_web_stream_once(args: argparse.Namespace, state: MonitorState, alias: str, prompt: str) -> None:
    query = {"protocol": "ag-ui" if args.web_stream_protocol == "ag-ui" else ""}
    body: dict[str, Any] = {"message": prompt}
    if args.execution_mode:
        body["execution_mode"] = args.execution_mode
    if args.agent_id and args.agent_id != "main":
        body["agent_id"] = args.agent_id
    url = web_api_url(args.web_url, f"/api/bots/{urllib.parse.quote(alias)}/chat/stream", query)
    log(f"WEB stream start {alias}: {prompt}")
    state.recorder.append(
        "web_stream_events.jsonl",
        {
            "kind": "web_stream_start",
            "alias": alias,
            "prompt": prompt,
            "request": body,
            "url": url,
        },
    )
    for event in stream_sse(url, token=args.password, method="POST", json_body=body):
        normalized = normalize_web_stream_event(alias, prompt, event)
        remember_native_session_id(state, str(normalized.get("native_session_id") or ""))
        state.recorder.append("web_stream_events.jsonl", normalized)
        print_web_stream_event(alias, normalized)
        event_type = str(normalized.get("event_type") or "").strip()
        if event_type in {"done", "error", "RUN_FINISHED", "RUN_ERROR"}:
            break
    log(f"WEB stream end {alias}")


def run_web_stream_prompts(args: argparse.Namespace, state: MonitorState, prompts: list[str]) -> int:
    aliases = list_bot_aliases(args.web_url, args.password, args.alias)
    if len(aliases) != 1:
        log("--capture-web-stream 需要唯一 alias；请传 --alias")
        return 2
    alias = aliases[0]
    for prompt in prompts:
        done = threading.Event()
        errors: list[str] = []

        def worker() -> None:
            try:
                capture_web_stream_once(args, state, alias, prompt)
            except Exception as exc:
                errors.append(str(exc))
                state.recorder.append(
                    "web_stream_events.jsonl",
                    {"kind": "web_stream_error", "alias": alias, "prompt": prompt, "error": str(exc)},
                )
                log(f"WEB stream failed {alias}: {exc}")
            finally:
                done.set()

        thread = threading.Thread(target=worker, name=f"web-stream-{alias}", daemon=True)
        thread.start()
        while not done.is_set():
            poll_all(args, state)
            time.sleep(max(0.2, args.interval))
        thread.join(timeout=1.0)
        deadline = time.monotonic() + max(0.0, float(args.post_done_seconds))
        while time.monotonic() < deadline:
            poll_all(args, state)
            time.sleep(max(0.2, args.interval))
        poll_all(args, state)
        if errors:
            return 1
    return 0


def print_web_stream_event(alias: str, event: dict[str, Any]) -> None:
    event_type = str(event.get("event_type") or event.get("type") or "").strip()
    if event_type == "status":
        preview = str(event.get("snapshot_text") or "").strip()
        if preview:
            log(f"STREAM {alias} status: {preview[-160:]}")
        return
    if event_type == "trace":
        trace = event.get("trace") if isinstance(event.get("trace"), dict) else {}
        kind = str(trace.get("kind") or "trace").strip()
        tool = str(trace.get("tool_name") or "").strip()
        summary = str(trace.get("summary") or "").strip()
        label = f"{kind}:{tool}" if tool else kind
        log(f"STREAM {alias} trace {label}: {summary}")
        return
    if event_type in {"done", "error", "RUN_FINISHED", "RUN_ERROR"}:
        text = str(event.get("history_content") or event.get("snapshot_text") or "").strip()
        log(f"STREAM {alias} {event_type}: {text[:500]}")


def monitor_opencode(args: argparse.Namespace, state: MonitorState, *, max_events: int | None = None) -> None:
    basic = opencode_basic(args)
    base_url = state.opencode_base_url or resolve_opencode_url(args.opencode_url or "auto", basic=basic)
    state.opencode_base_url = base_url
    url = f"{base_url.rstrip('/')}/global/event"
    seen = 0
    for raw in stream_sse(url, basic=basic):
        if seen == 0:
            log(f"opencode SSE connected: {url}")
        print_opencode_event(args, raw, state)
        seen += 1
        if max_events is not None and seen >= max_events:
            return


def resolve_opencode_url(value: str, *, basic: tuple[str, str]) -> str:
    raw = str(value or "").strip()
    if raw and raw.lower() != "auto":
        return raw
    for candidate in discover_opencode_urls():
        try:
            request_json(f"{candidate.rstrip('/')}/global/health", basic=basic, timeout=2.0)
            return candidate
        except Exception:
            continue
    raise RuntimeError("未发现可连接的 opencode serve；请传 --opencode-url http://host:port")


def discover_opencode_urls() -> list[str]:
    urls: list[str] = []
    env_port = str(os.environ.get("NATIVE_AGENT_PORT") or "").strip()
    env_host = str(os.environ.get("NATIVE_AGENT_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    if env_port.isdigit() and int(env_port) > 0:
        urls.append(format_opencode_url(env_host, int(env_port)))
    for line in iter_opencode_command_lines():
        parsed = parse_opencode_command_url(line)
        if parsed:
            urls.append(parsed)
    deduped: list[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


def iter_opencode_command_lines() -> list[str]:
    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -match 'opencode' -and $_.CommandLine -match 'serve' } | "
                "ForEach-Object { $_.CommandLine }"
            ),
        ]
    else:
        command = ["ps", "-eo", "args="]
    try:
        output = subprocess.check_output(command, text=True, encoding="utf-8", errors="replace", timeout=6)
    except Exception:
        return []
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if os.name == "nt":
        return lines
    return [line for line in lines if "opencode" in line.lower() and "serve" in line.lower()]


def parse_opencode_command_url(command_line: str) -> str:
    port_match = re.search(r"--port(?:=|\s+)(\d{1,5})", command_line)
    if not port_match:
        return ""
    port = int(port_match.group(1))
    host_match = re.search(r"--host(?:name)?(?:=|\s+)([^\s\"']+)", command_line)
    host = host_match.group(1) if host_match else "127.0.0.1"
    return format_opencode_url(host, port)


def format_opencode_url(host: str, port: int) -> str:
    normalized = str(host or "127.0.0.1").strip().strip("\"'") or "127.0.0.1"
    if normalized in {"0.0.0.0", "::"}:
        normalized = "127.0.0.1"
    if ":" in normalized and not normalized.startswith("["):
        normalized = f"[{normalized}]"
    return f"http://{normalized}:{int(port)}"


def print_opencode_event(args: argparse.Namespace, raw: dict[str, Any], state: MonitorState) -> None:
    normalized = normalize_opencode_event(raw, alias=args.alias)
    session_id = str(normalized.get("native_session_id") or "").strip()
    remember_native_session_id(state, session_id)
    if args.capture_opencode_sse:
        state.recorder.append("opencode_events.jsonl", normalized)
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    event_type = str(normalized.get("event_type") or "event")
    role = str(normalized.get("role") or "").strip()
    message_id = str(normalized.get("opencode_message_id") or "").strip()
    delta = str(normalized.get("delta_text") or "").strip()
    text = str(normalized.get("snapshot_text") or "").strip()
    part_type = str(normalized.get("part_type") or "").strip()
    if delta and message_id:
        with state.lock:
            state.current_opencode_text[message_id] = state.current_opencode_text.get(message_id, "") + delta
    if event_type in {"message.part.delta", "message.part.updated"} and (delta or text):
        shown = delta or text
        label = f"{role or part_type or 'text'} {message_id}".strip()
        log(f"OPENCODE {label}: {shown}")
        return
    if event_type == "message.updated" and (text or role):
        finish = str(normalized.get("finish") or "").strip()
        suffix = f" finish={finish}" if finish else ""
        log(f"OPENCODE {role or 'message'} {message_id}{suffix}: {text}")
        return
    if normalized.get("tool_count"):
        tool = str(normalized.get("tool_name") or "tool").strip()
        status = str(normalized.get("status") or normalized.get("state") or "").strip()
        log(f"OPENCODE tool {tool} {status}: {json.dumps(payload, ensure_ascii=False)[:1200]}")
        return
    if event_type not in {"server.connected", "server.heartbeat", "session.status"}:
        directory = str(raw.get("directory") or raw.get("cwd") or "").strip()
        where = f" cwd={directory}" if directory else ""
        log(f"OPENCODE {event_type}{where}: {json.dumps(payload, ensure_ascii=False)[:1200]}")


def poll_opencode_session_messages(args: argparse.Namespace, state: MonitorState) -> None:
    base_url = ensure_opencode_base_url(args, state)
    if not base_url:
        return
    with state.lock:
        session_ids = sorted(state.known_native_session_ids)
    if not session_ids:
        return
    basic = opencode_basic(args)
    for session_id in session_ids:
        try:
            payload = request_json(f"{base_url.rstrip('/')}/session/{urllib.parse.quote(session_id)}/message", basic=basic, timeout=8.0)
        except Exception as exc:
            state.recorder.write_json(
                f"opencode_sessions/{safe_filename(session_id)}.messages.json",
                {
                    "kind": "opencode_session_messages_error",
                    "native_session_id": session_id,
                    "error": str(exc),
                },
            )
            continue
        messages = normalize_opencode_messages_payload(payload)
        signature = stable_json_signature(messages)
        with state.lock:
            old_signature = state.opencode_session_signatures.get(session_id, "")
            state.opencode_session_signatures[session_id] = signature
        if signature == old_signature:
            continue
        state.recorder.write_json(
            f"opencode_sessions/{safe_filename(session_id)}.messages.json",
            {
                "kind": "opencode_session_messages",
                "native_session_id": session_id,
                "message_count": len(messages),
                "messages": messages,
                "raw_payload": payload,
            },
        )


def ensure_opencode_base_url(args: argparse.Namespace, state: MonitorState) -> str:
    if state.opencode_base_url:
        return state.opencode_base_url
    try:
        state.opencode_base_url = resolve_opencode_url(args.opencode_url or "auto", basic=opencode_basic(args))
    except Exception as exc:
        log(f"opencode resolve failed: {exc}")
        return ""
    return state.opencode_base_url


def start_opencode_thread(args: argparse.Namespace, state: MonitorState) -> None:
    def worker() -> None:
        while True:
            try:
                monitor_opencode(args, state)
            except Exception as exc:
                log(f"opencode SSE disconnected: {exc}")
                time.sleep(max(0.2, args.interval))

    thread = threading.Thread(target=worker, name="opencode-monitor", daemon=True)
    thread.start()


def remember_native_session_id(state: MonitorState, session_id: str) -> None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    with state.lock:
        state.known_native_session_ids.add(normalized)


def summarize_web_message(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    message_id = str(item.get("id") or "").strip()
    return {
        "web_message_id": message_id,
        "assistant_message_id": message_id if str(item.get("role") or "").strip().lower() == "assistant" else "",
        "turn_id": str(item.get("turn_id") or meta.get("turn_id") or "").strip(),
        "conversation_id": str(item.get("conversation_id") or meta.get("conversation_id") or "").strip(),
        "role": str(item.get("role") or "").strip(),
        "state": str(item.get("state") or "").strip(),
        "completion_state": str(meta.get("completion_state") or "").strip(),
        "native_session_id": native_session_id_from_web_message(item),
        "history_content": str(item.get("content") or item.get("text") or ""),
        "trace_count": int(meta.get("trace_count") or 0),
        "tool_count": int(meta.get("tool_call_count") or 0),
    }


def native_session_id_from_web_message(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    native_source = meta.get("native_source") if isinstance(meta.get("native_source"), dict) else {}
    return str(meta.get("native_session_id") or native_source.get("session_id") or "").strip()


def normalize_web_stream_event(alias: str, prompt: str, event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type") or "").strip()
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
    native_session_id = str(event.get("native_session_id") or "").strip() or (native_session_id_from_web_message(message) if message else "")
    turn_id = str(event.get("turn_id") or message.get("turn_id") or meta.get("turn_id") or "").strip()
    assistant_message_id = str(
        event.get("assistant_message_id")
        or message.get("id")
        or event.get("message_id")
        or event.get("messageId")
        or ""
    ).strip()
    native_assistant_message_id = str(
        event.get("native_assistant_message_id")
        or event.get("opencode_message_id")
        or ""
    ).strip()
    output = str(event.get("output") or "")
    text = str(event.get("text") or event.get("delta") or "")
    snapshot = str(event.get("snapshot") or event.get("preview_text") or output)
    trace = event.get("event") if isinstance(event.get("event"), dict) else {}
    trace_payload = trace.get("payload") if isinstance(trace.get("payload"), dict) else {}
    if not native_assistant_message_id:
        native_assistant_message_id = _first_text(trace, trace_payload, keys=("messageID", "message_id", "messageId"))
    if not native_session_id:
        native_session_id = _first_text(trace, trace_payload, keys=("sessionID", "session_id", "sessionId"))
    if event_type == "RUN_FINISHED":
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        result_message = result.get("message") if isinstance(result.get("message"), dict) else {}
        message = result_message or message
        meta = message.get("meta") if isinstance(message.get("meta"), dict) else meta
        output = str(result.get("content") or message.get("content") or output)
        snapshot = output
        native_session_id = str(event.get("native_session_id") or "").strip() or (native_session_id_from_web_message(message) if message else native_session_id)
        turn_id = str(event.get("turn_id") or message.get("turn_id") or meta.get("turn_id") or turn_id).strip()
        assistant_message_id = str(event.get("assistant_message_id") or message.get("id") or assistant_message_id).strip()
    if event_type == "RUN_ERROR":
        snapshot = str(event.get("message") or snapshot)
    session = event.get("session") if isinstance(event.get("session"), dict) else {}
    session_ids = session.get("session_ids") if isinstance(session.get("session_ids"), dict) else {}
    if not native_session_id:
        native_session_id = str(session_ids.get("native_agent_session_id") or "").strip()
    web_message_id = str(message.get("id") or assistant_message_id or event.get("message_id") or event.get("messageId") or "").strip()
    return {
        "kind": "web_stream_event",
        "alias": alias,
        "prompt": prompt,
        "event_type": event_type,
        "web_message_id": web_message_id,
        "assistant_message_id": assistant_message_id,
        "native_assistant_message_id": native_assistant_message_id,
        "turn_id": turn_id,
        "native_session_id": native_session_id,
        "role": str(message.get("role") or "").strip(),
        "state": str(message.get("state") or "").strip(),
        "completion_state": str(meta.get("completion_state") or "").strip(),
        "delta_text": text,
        "snapshot_text": snapshot,
        "history_content": str(message.get("content") or output),
        "running_reply": session.get("running_reply") if isinstance(session.get("running_reply"), dict) else None,
        "trace_count": int(meta.get("trace_count") or 0),
        "tool_count": int(meta.get("tool_call_count") or 0),
        "trace": trace,
        "raw": event,
    }


def normalize_opencode_event(raw: dict[str, Any], *, alias: str = "") -> dict[str, Any]:
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    message = _first_dict(payload.get("message"), properties.get("message"), payload.get("info"), properties.get("info"))
    part = _first_dict(payload.get("part"), properties.get("part"))
    event_type = _first_text(payload, properties, message, part, raw, keys=("type", "event", "name")) or "event"
    permission = _permission_payload(event_type, payload, properties)
    message_id = _first_text(payload, properties, message, part, keys=("messageID", "message_id", "messageId"))
    if not message_id:
        message_id = _first_text(message, part, keys=("id",))
    part_id = _first_text(payload, properties, part, keys=("partID", "part_id", "partId"))
    if not part_id:
        part_id = _first_text(part, keys=("id",))
    call_id = _first_text(
        payload,
        properties,
        part,
        keys=("callID", "call_id", "toolCallID", "toolCallId", "tool_call_id"),
    )
    finish = _first_text(payload, properties, message, part, keys=("finish", "finish_reason", "finishReason"))
    part_state = part.get("state")
    state_records: list[dict[str, Any]] = [payload, properties]
    if isinstance(part_state, dict):
        state_records.append(part_state)
    state_records.append(part)
    status = _first_text(*state_records, keys=("status", "state"))
    state = _first_text(*state_records, keys=("state", "status"))
    part_type = _first_text(part, keys=("type", "kind"))
    tool_name = _first_text(part, properties, payload, keys=("tool", "toolName", "tool_name"))
    if not tool_name:
        tool_name = _first_text(part, keys=("name",))
    delta = _first_text(payload, properties, part, keys=("delta",))
    text = _first_text(payload, properties, message, part, keys=("content", "text", "snapshot", "output"))
    session_id = extract_native_session_id_from_opencode(raw, payload, properties, message, part, permission)
    raw_text = json.dumps(raw, ensure_ascii=False)
    abort_observed = "MessageAbortedError" in raw_text or "Tool execution aborted" in raw_text
    tool_count = 1 if (
        part_type == "tool"
        or bool(tool_name)
        or bool(call_id)
        or any(key in part for key in ("tool", "toolName", "callID", "toolCallId", "arguments", "raw_arguments"))
        or any(key in properties for key in ("tool", "toolName", "callID", "toolCallId", "arguments", "raw_arguments"))
        or any(key in payload for key in ("tool", "toolName", "callID", "toolCallId", "arguments", "raw_arguments"))
    ) else 0
    session_idle_seen = event_type == "session.idle" or state.lower() == "idle" or status.lower() == "idle"
    return {
        "kind": "opencode_event",
        "alias": alias,
        "event_type": event_type,
        "native_session_id": session_id,
        "opencode_message_id": message_id,
        "part_id": part_id,
        "call_id": call_id,
        "role": str(message.get("role") or "").strip(),
        "finish": finish,
        "status": status,
        "state": state,
        "part_type": part_type,
        "tool_name": tool_name,
        "permission": permission,
        "delta_text": delta,
        "snapshot_text": text,
        "tool_count": tool_count,
        "abort_seen": abort_observed,
        "abort_observed": abort_observed,
        "abort_inferred": False,
        "session_idle_seen": session_idle_seen,
        "raw": raw,
    }


def extract_native_session_id_from_opencode(
    raw: dict[str, Any],
    payload: dict[str, Any],
    properties: dict[str, Any],
    message: dict[str, Any],
    part: dict[str, Any],
    permission: dict[str, Any] | None = None,
) -> str:
    return _first_text(
        payload,
        properties,
        message,
        part,
        permission or {},
        raw,
        keys=("sessionID", "session_id", "sessionId"),
    )


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_text(*records: dict[str, Any], keys: tuple[str, ...]) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            value = record.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return ""


def _permission_payload(event_type: str, payload: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("permission"), dict):
        return dict(payload["permission"])
    if isinstance(properties.get("permission"), dict):
        return dict(properties["permission"])
    if event_type in {"permission.updated", "permission.replied"}:
        return dict(properties or payload)
    return {}


def normalize_opencode_messages_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            raw_items = payload["data"]
        elif isinstance(payload.get("messages"), list):
            raw_items = payload["messages"]
        elif isinstance(payload.get("items"), list):
            raw_items = payload["items"]
        else:
            raw_items = []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []
    return [flatten_opencode_message(item) for item in raw_items if isinstance(item, dict)]


def flatten_opencode_message(message: dict[str, Any]) -> dict[str, Any]:
    info = message.get("info") if isinstance(message.get("info"), dict) else {}
    parts = message.get("parts") if isinstance(message.get("parts"), list) else []
    flattened = dict(info)
    flattened.update({key: value for key, value in message.items() if key != "info"})
    message_id = (
        flattened.get("id")
        or flattened.get("messageID")
        or flattened.get("message_id")
        or flattened.get("messageId")
        or info.get("id")
        or info.get("messageID")
        or info.get("message_id")
        or info.get("messageId")
    )
    role = flattened.get("role") or info.get("role")
    finish = flattened.get("finish") or info.get("finish") or info.get("finishReason") or info.get("finish_reason")
    if message_id:
        flattened["id"] = str(message_id)
    if role:
        flattened["role"] = str(role)
    if finish:
        flattened["finish"] = str(finish)
    flattened["content"] = str(flattened.get("content") or flattened.get("text") or message_parts_text(parts) or "")
    flattened["parts"] = parts
    return flattened


def part_text(part: Any) -> str:
    if part is None:
        return ""
    if isinstance(part, str):
        return part
    if isinstance(part, (int, float, bool)):
        return str(part)
    if isinstance(part, list):
        return "".join(part_text(item) for item in part)
    if not isinstance(part, dict):
        return ""
    for key in ("text", "content", "value", "message", "summary", "delta"):
        value = part.get(key)
        if value is not None:
            text = part_text(value)
            if text:
                return text
    nested = part.get("part")
    if isinstance(nested, dict):
        return part_text(nested)
    return ""


def message_parts_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            kind = str(part.get("type") or part.get("kind") or "").strip().lower()
            if kind and kind not in {"text", "assistant_text", "message"}:
                continue
        text = part_text(part)
        if text:
            texts.append(text)
    return "".join(texts)


def is_web_trace_tool(trace: dict[str, Any]) -> bool:
    kind = str(trace.get("kind") or "").strip().lower()
    if kind in TRACE_KIND_TOOL:
        return True
    if str(trace.get("tool_name") or "").strip():
        return True
    return False


def message_expects_followup(message: dict[str, Any]) -> bool:
    finish = str(message.get("finish") or message.get("finish_reason") or message.get("finishReason") or "").strip().lower()
    return finish in TOOL_FOLLOWUP_FINISH


def contains_abort(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return "MessageAbortedError" in text or "Tool execution aborted" in text


def safe_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text[:160] or "session"


def load_prompts(args: argparse.Namespace) -> list[str]:
    prompts: list[str] = []
    for prompt in args.prompt or []:
        if str(prompt).strip() == "-":
            text = sys.stdin.read().strip()
        else:
            text = str(prompt)
        if text.strip():
            prompts.append(text.strip())
    if args.prompt_file:
        path = Path(args.prompt_file)
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text:
                prompts.append(text)
    return prompts


def generate_comparison_report(record_dir: str | Path, run_id: str) -> dict[str, Any]:
    root = Path(record_dir)
    history_records = read_jsonl(root / "web_history_snapshots.jsonl")
    trace_records = read_jsonl(root / "web_trace_snapshots.jsonl")
    session_records = read_jsonl(root / "web_session_snapshots.jsonl")
    stream_records = read_jsonl(root / "web_stream_events.jsonl")
    opencode_records = read_jsonl(root / "opencode_events.jsonl")
    opencode_sessions = read_opencode_session_files(root / "opencode_sessions")
    latest_web_by_turn = latest_web_assistant_by_turn(history_records)
    latest_trace_by_message = latest_trace_by_message_id(trace_records)
    latest_stream_done_by_turn = latest_stream_done_by_turn_id(stream_records)
    stream_windows = stream_windows_by_turn(stream_records)
    opencode_by_turn = summarize_opencode_by_turn(opencode_records, opencode_sessions, latest_web_by_turn, latest_stream_done_by_turn)
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    turn_keys = sorted(set(latest_web_by_turn) | set(latest_stream_done_by_turn) | set(opencode_by_turn))
    for turn_key in turn_keys:
        web_item = latest_web_by_turn.get(turn_key, {})
        op_item = opencode_by_turn.get(turn_key, {})
        stream_item = latest_stream_done_by_turn.get(turn_key, {})
        session_id = str(web_item.get("native_session_id") or stream_item.get("native_session_id") or op_item.get("native_session_id") or "").strip()
        web_message_id = str(web_item.get("web_message_id") or "")
        trace_item = latest_trace_by_message.get(web_message_id, {})
        web_content = normalize_compare_text(web_item.get("history_content"))
        op_final = normalize_compare_text(op_item.get("final_assistant_text"))
        stream_content = normalize_compare_text(stream_item.get("history_content"))
        completion_state = str(web_item.get("completion_state") or "").strip()
        checks.append(
            {
                "turn_key": turn_key,
                "turn_id": web_item.get("turn_id") or stream_item.get("turn_id") or "",
                "session_id": session_id,
                "web_message_id": web_message_id,
                "native_assistant_message_id": op_item.get("native_assistant_message_id") or stream_item.get("native_assistant_message_id") or "",
                "web_completion_state": completion_state,
                "web_trace_count": trace_item.get("trace_count", web_item.get("trace_count", 0)),
                "web_tool_count": trace_item.get("tool_count", web_item.get("tool_count", 0)),
                "opencode_tool_count": op_item.get("tool_count", 0),
                "opencode_abort_seen": op_item.get("abort_seen", False),
                "opencode_idle_seen": op_item.get("session_idle_seen", False),
                "web_equals_opencode_final": bool(web_content and op_final and web_content == op_final),
                "stream_equals_history": bool(not stream_content or not web_content or stream_content == web_content),
            }
        )
        if op_item.get("abort_seen") and completion_state == "completed":
            issues.append(
                issue(
                    "error",
                    "abort_completed",
                    "opencode 见到 abort，但 Web history 标 completed",
                    session_id=session_id,
                    web_message_id=web_message_id,
                )
            )
        if op_final and web_content and op_final != web_content:
            issues.append(
                issue(
                    "error",
                    "history_not_final_opencode_text",
                    "Web history 内容不等于 opencode 最终 assistant 文本",
                    session_id=session_id,
                    web_message_id=web_message_id,
                    web_preview=web_content[:500],
                    opencode_preview=op_final[:500],
                )
            )
        if stream_content and web_content and stream_content != web_content:
            issues.append(
                issue(
                    "error",
                    "stream_history_mismatch",
                    "Web stream 完成内容不等于刷新后 history",
                    session_id=session_id,
                    web_message_id=web_message_id,
                    stream_preview=stream_content[:500],
                    history_preview=web_content[:500],
                )
            )
        web_trace_tool_count = int(trace_item.get("tool_count") or web_item.get("tool_count") or 0)
        if int(op_item.get("tool_count") or 0) > 0 and web_trace_tool_count <= 0:
            issues.append(
                issue(
                    "warning",
                    "trace_missing_tool",
                    "opencode 有 tool activity，但 Web trace 未记录 tool",
                    session_id=session_id,
                    web_message_id=web_message_id,
                    opencode_tool_count=op_item.get("tool_count", 0),
                )
            )
        if completion_state == "completed" and opencode_records and not op_item.get("session_idle_seen"):
            issues.append(
                issue(
                    "warning",
                    "completed_without_captured_idle",
                    "Web completed，但记录中未见同 session 的 opencode idle",
                    session_id=session_id,
                    web_message_id=web_message_id,
                )
            )
        later_events = opencode_events_after_web_done_for_turn(turn_key, stream_item, stream_windows, opencode_records)
        if later_events:
            issues.append(
                issue(
                    "error",
                    "web_done_before_opencode_activity",
                    "Web done 后 opencode 仍有 tool/followup assistant activity",
                    session_id=session_id,
                    web_message_id=web_message_id,
                    later_event_count=len(later_events),
                    first_later_event=later_events[0],
                )
            )

    issues.extend(compare_session_id_consistency(session_records, latest_web_by_turn))
    issues.extend(compare_conversation_session_consistency(history_records))
    report = {
        "run_id": run_id,
        "generated_at": wall_ts(),
        "record_dir": str(root),
        "summary": {
            "web_history_snapshots": len(history_records),
            "web_trace_snapshots": len(trace_records),
            "web_session_snapshots": len(session_records),
            "web_stream_events": len(stream_records),
            "opencode_events": len(opencode_records),
            "opencode_sessions": len(opencode_sessions),
            "turns_compared": len(turn_keys),
            "sessions_compared": len({str(item.get("session_id") or "") for item in checks if str(item.get("session_id") or "")}),
            "issue_count": len(issues),
        },
        "issues": issues,
        "checks": checks,
        "turns": {
            turn_key: {
                "web": latest_web_by_turn.get(turn_key, {}),
                "stream_done": latest_stream_done_by_turn.get(turn_key, {}),
                "opencode": opencode_by_turn.get(turn_key, {}),
            }
            for turn_key in turn_keys
        },
    }
    (root / "comparison_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "comparison_report.md").write_text(render_comparison_markdown(report), encoding="utf-8")
    return report


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def read_opencode_session_files(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return result
    for file_path in sorted(path.glob("*.messages.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        session_id = str(payload.get("native_session_id") or file_path.name.removesuffix(".messages.json")).strip()
        if session_id:
            result[session_id] = payload
    return result


def compare_key(record: dict[str, Any]) -> str:
    turn_id = str(record.get("turn_id") or "").strip()
    if turn_id:
        return f"turn:{turn_id}"
    message_id = str(record.get("assistant_message_id") or record.get("web_message_id") or "").strip()
    if message_id:
        return f"message:{message_id}"
    prompt = str(record.get("prompt") or "").strip()
    session_id = str(record.get("native_session_id") or "").strip()
    if session_id and prompt:
        return f"session-prompt:{session_id}:{hashlib.sha1(prompt.encode('utf-8')).hexdigest()[:12]}"
    if session_id:
        return f"session:{session_id}"
    return ""


def latest_web_assistant_by_turn(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        items = record.get("items") if isinstance(record.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict) or str(item.get("role") or "").lower() != "assistant":
                continue
            session_id = native_session_id_from_web_message(item)
            if not session_id:
                continue
            summary = summarize_web_message(item)
            summary["ts_mono_ms"] = record.get("ts_mono_ms", 0)
            key = compare_key(summary)
            if key:
                result[key] = summary
    return result


def latest_trace_by_message_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("kind") != "web_trace_snapshot":
            continue
        message_id = str(record.get("web_message_id") or "").strip()
        if message_id:
            result[message_id] = record
    return result


def latest_stream_done_by_turn_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    latest_by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("kind") != "web_stream_event":
            continue
        key = compare_key(record)
        if key:
            cached = latest_by_key.setdefault(key, {})
            for field in ("native_session_id", "native_assistant_message_id", "assistant_message_id", "web_message_id", "turn_id"):
                value = str(record.get(field) or "").strip()
                if value:
                    cached[field] = value
        event_type = str(record.get("event_type") or "").strip()
        if event_type not in {"done", "RUN_FINISHED"}:
            continue
        if key:
            merged = {**latest_by_key.get(key, {}), **record}
            if not str(merged.get("native_assistant_message_id") or "").strip():
                merged["native_assistant_message_id"] = str(latest_by_key.get(key, {}).get("native_assistant_message_id") or "")
            result[key] = merged
    return result


def stream_windows_by_turn(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    windows: dict[str, dict[str, int]] = {}
    last_key = ""
    for record in records:
        if record.get("kind") != "web_stream_event":
            continue
        key = compare_key(record)
        if key:
            last_key = key
        elif last_key:
            key = last_key
        if not key:
            continue
        ts = int(record.get("ts_mono_ms") or 0)
        item = windows.setdefault(key, {"start": ts, "done": 0})
        if ts and (not item.get("start") or ts < int(item.get("start") or 0)):
            item["start"] = ts
        if str(record.get("event_type") or "").strip() in {"done", "RUN_FINISHED", "error", "RUN_ERROR"}:
            item["done"] = ts
            last_key = ""
    return windows


def summarize_opencode_by_turn(
    event_records: list[dict[str, Any]],
    session_files: dict[str, dict[str, Any]],
    web_by_turn: dict[str, dict[str, Any]],
    stream_done_by_turn: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    turn_records = {**web_by_turn, **stream_done_by_turn}
    result: dict[str, dict[str, Any]] = {}
    native_message_to_key = {
        str(record.get("native_assistant_message_id") or "").strip(): key
        for key, record in stream_done_by_turn.items()
        if str(record.get("native_assistant_message_id") or "").strip()
    }
    for key, record in turn_records.items():
        session_id = str(record.get("native_session_id") or "").strip()
        if not session_id:
            continue
        result.setdefault(
            key,
            {
                "native_session_id": session_id,
                "native_assistant_message_id": str(record.get("native_assistant_message_id") or "").strip(),
                "tool_count": 0,
                "abort_seen": False,
                "abort_observed": False,
                "abort_inferred": False,
                "session_idle_seen": False,
                "event_count": 0,
            },
        )
    for record in event_records:
        session_id = str(record.get("native_session_id") or "").strip()
        if not session_id:
            continue
        message_id = str(record.get("opencode_message_id") or "").strip()
        key = native_message_to_key.get(message_id, "")
        if not key:
            matching_keys = [
                item_key
                for item_key, item in turn_records.items()
                if str(item.get("native_session_id") or "").strip() == session_id
            ]
            key = matching_keys[-1] if len(matching_keys) == 1 else ""
        if not key:
            continue
        item = result.setdefault(
            key,
            {
                "native_session_id": session_id,
                "native_assistant_message_id": message_id,
                "tool_count": 0,
                "abort_seen": False,
                "abort_observed": False,
                "abort_inferred": False,
                "session_idle_seen": False,
                "event_count": 0,
            },
        )
        item["event_count"] = int(item.get("event_count") or 0) + 1
        item["tool_count"] = int(item.get("tool_count") or 0) + int(record.get("tool_count") or 0)
        item["abort_seen"] = bool(item.get("abort_seen")) or bool(record.get("abort_seen"))
        item["abort_observed"] = bool(item.get("abort_observed")) or bool(record.get("abort_observed"))
        item["session_idle_seen"] = bool(item.get("session_idle_seen")) or bool(record.get("session_idle_seen"))
    for session_id, payload in session_files.items():
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        keys_for_session = [
            key
            for key, record in turn_records.items()
            if str(record.get("native_session_id") or "").strip() == session_id
        ]
        if not keys_for_session:
            keys_for_session = [f"session:{session_id}"]
        for key in keys_for_session:
            expected_message_id = str(turn_records.get(key, {}).get("native_assistant_message_id") or "").strip()
            item = result.setdefault(
                key,
                {
                    "native_session_id": session_id,
                    "native_assistant_message_id": expected_message_id,
                    "tool_count": 0,
                    "abort_seen": False,
                    "abort_observed": False,
                    "abort_inferred": False,
                    "session_idle_seen": False,
                    "event_count": 0,
                },
            )
            final_message = assistant_message_by_id(messages, expected_message_id) if expected_message_id else final_assistant_message(messages)
            current_messages = messages_for_assistant(messages, expected_message_id) if expected_message_id else messages
            item["message_count"] = len(current_messages)
            item["final_assistant_message_id"] = str(final_message.get("id") or "")
            item["final_assistant_text"] = str(final_message.get("content") or "")
            item["tool_count"] = int(item.get("tool_count") or 0) + count_tool_parts(current_messages)
            messages_abort = contains_abort(current_messages)
            item["abort_seen"] = bool(item.get("abort_seen")) or messages_abort
            item["abort_observed"] = bool(item.get("abort_observed")) or messages_abort
            item["has_followup_required_message"] = any(
                isinstance(message, dict) and str(message.get("role") or "").lower() == "assistant" and message_expects_followup(message)
                for message in current_messages
            )
    return result


def assistant_message_by_id(messages: list[Any], message_id: str) -> dict[str, Any]:
    target = str(message_id or "").strip()
    if not target:
        return {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("id") or "").strip() == target and str(message.get("role") or "").lower() == "assistant":
            return message
    return {}


def messages_for_assistant(messages: list[Any], assistant_message_id: str) -> list[Any]:
    target = str(assistant_message_id or "").strip()
    if not target:
        return messages
    selected: list[Any] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("id") or "").strip() == target:
            selected.append(message)
            continue
        parts = message.get("parts") if isinstance(message.get("parts"), list) else []
        if any(isinstance(part, dict) and str(part.get("messageID") or part.get("message_id") or part.get("messageId") or "").strip() == target for part in parts):
            selected.append(message)
    return selected


def final_assistant_message(messages: list[Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() != "assistant":
            continue
        text = str(message.get("content") or "").strip()
        if not text:
            continue
        if not message_expects_followup(message):
            selected = message
    if selected:
        return selected
    for message in reversed(messages):
        if isinstance(message, dict) and str(message.get("role") or "").lower() == "assistant":
            return message
    return {}


def count_tool_parts(messages: list[Any]) -> int:
    count = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        parts = message.get("parts") if isinstance(message.get("parts"), list) else []
        for part in parts:
            if not isinstance(part, dict):
                continue
            kind = str(part.get("type") or part.get("kind") or "").strip().lower()
            if kind == "tool" or part.get("tool") or part.get("toolName") or part.get("callID"):
                count += 1
    return count


def opencode_events_after_web_done_for_turn(
    turn_key: str,
    stream_done: dict[str, Any],
    stream_windows: dict[str, dict[str, int]],
    opencode_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    done_ts = int(stream_done.get("ts_mono_ms") or 0)
    if not done_ts:
        return []
    session_id = str(stream_done.get("native_session_id") or "").strip()
    if not session_id:
        return []
    native_message_id = str(stream_done.get("native_assistant_message_id") or "").strip()
    next_start_ts = 0
    current_window = stream_windows.get(turn_key, {})
    current_start = int(current_window.get("start") or 0)
    for other_key, window in stream_windows.items():
        if other_key == turn_key:
            continue
        start_ts = int(window.get("start") or 0)
        if start_ts > done_ts and (not next_start_ts or start_ts < next_start_ts):
            next_start_ts = start_ts
    later: list[dict[str, Any]] = []
    for record in opencode_records:
        if str(record.get("native_session_id") or "").strip() != session_id:
            continue
        record_ts = int(record.get("ts_mono_ms") or 0)
        if record_ts <= done_ts:
            continue
        if next_start_ts and record_ts >= next_start_ts:
            continue
        if current_start and record_ts < current_start:
            continue
        record_message_id = str(record.get("opencode_message_id") or "").strip()
        if native_message_id and record_message_id and record_message_id != native_message_id:
            continue
        event_type = str(record.get("event_type") or "")
        role = str(record.get("role") or "").lower()
        if int(record.get("tool_count") or 0) > 0 or (event_type == "message.updated" and role == "assistant"):
            later.append(
                {
                    "ts_mono_ms": record.get("ts_mono_ms"),
                    "event_type": event_type,
                    "opencode_message_id": record.get("opencode_message_id"),
                    "finish": record.get("finish"),
                    "tool_name": record.get("tool_name"),
                }
            )
    return later


def compare_session_id_consistency(
    session_records: list[dict[str, Any]],
    latest_web_by_turn: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not session_records:
        return issues
    latest_by_alias: dict[str, dict[str, Any]] = {}
    for record in session_records:
        alias = str(record.get("alias") or "").strip()
        if alias:
            latest_by_alias[alias] = record
    history_session_ids = {
        str(item.get("native_session_id") or "").strip()
        for item in latest_web_by_turn.values()
        if str(item.get("native_session_id") or "").strip()
    }
    for alias, record in latest_by_alias.items():
        session_id = str(record.get("native_session_id") or "").strip()
        if session_id and history_session_ids and session_id not in history_session_ids:
            issues.append(
                issue(
                    "warning",
                    "session_id_mismatch",
                    "Web session native_agent_session_id 与 history native_session_id 不一致",
                    alias=alias,
                    session_native_session_id=session_id,
                    history_native_session_ids=sorted(history_session_ids),
                )
            )
    return issues


def compare_conversation_session_consistency(history_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_conversation: dict[str, set[str]] = {}
    for record in history_records:
        items = record.get("items") if isinstance(record.get("items"), list) else []
        for item in items:
            if not isinstance(item, dict) or str(item.get("role") or "").strip().lower() != "assistant":
                continue
            summary = summarize_web_message(item)
            conversation_id = str(summary.get("conversation_id") or "").strip()
            session_id = str(summary.get("native_session_id") or "").strip()
            if conversation_id and session_id:
                by_conversation.setdefault(conversation_id, set()).add(session_id)
    issues: list[dict[str, Any]] = []
    for conversation_id, session_ids in sorted(by_conversation.items()):
        if len(session_ids) <= 1:
            continue
        issues.append(
            issue(
                "error",
                "conversation_session_changed",
                "同 conversation 出现多个 native_session_id",
                conversation_id=conversation_id,
                native_session_ids=sorted(session_ids),
            )
        )
    return issues


def issue(severity: str, code: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "evidence": evidence}


def normalize_compare_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def render_comparison_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    lines = [
        "# I/O comparison report",
        "",
        f"- run_id: `{report.get('run_id') or ''}`",
        f"- record_dir: `{report.get('record_dir') or ''}`",
        f"- turns_compared: {summary.get('turns_compared', 0)}",
        f"- sessions_compared: {summary.get('sessions_compared', 0)}",
        f"- issue_count: {summary.get('issue_count', 0)}",
        "",
        "## Issues",
    ]
    if not issues:
        lines.append("")
        lines.append("No mismatch found in captured records.")
    else:
        for item in issues:
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            session_id = evidence.get("session_id") or evidence.get("session_native_session_id") or ""
            lines.append("")
            lines.append(f"- **{item.get('severity')} / {item.get('code')}**: {item.get('message')}")
            if evidence.get("turn_id"):
                lines.append(f"  - turn_id: `{evidence.get('turn_id')}`")
            if session_id:
                lines.append(f"  - session: `{session_id}`")
            if evidence.get("web_message_id"):
                lines.append(f"  - web_message_id: `{evidence.get('web_message_id')}`")
            if evidence.get("web_preview"):
                lines.append(f"  - web: {evidence.get('web_preview')}")
            if evidence.get("opencode_preview"):
                lines.append(f"  - opencode: {evidence.get('opencode_preview')}")
    lines.extend(["", "## Checks"])
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        lines.append(
            "- turn `{}` session `{}`: web_state={}, web_trace={}, opencode_tools={}, abort={}, idle={}, web_eq_opencode={}, stream_eq_history={}".format(
                check.get("turn_id") or check.get("turn_key", ""),
                check.get("session_id", ""),
                check.get("web_completion_state", ""),
                check.get("web_trace_count", 0),
                check.get("opencode_tool_count", 0),
                check.get("opencode_abort_seen", False),
                check.get("opencode_idle_seen", False),
                check.get("web_equals_opencode_final", False),
                check.get("stream_equals_history", False),
            )
        )
    lines.append("")
    return "\n".join(lines)


def maybe_generate_report(args: argparse.Namespace, state: MonitorState) -> None:
    if not args.compare:
        return
    if not state.recorder.enabled or state.recorder.root is None:
        log("--compare 需要 --record-dir")
        return
    report = generate_comparison_report(state.recorder.root, state.recorder.run_id)
    issue_count = int((report.get("summary") or {}).get("issue_count") or 0)
    log(f"comparison report written: {state.recorder.root / 'comparison_report.md'} ({issue_count} issues)")


def compare_only_requested(args: argparse.Namespace) -> bool:
    if not args.compare or not args.record_dir:
        return False
    return not (
        args.capture_web_stream
        or args.capture_opencode_sse
        or args.capture_session_messages
        or bool(str(args.opencode_url or "").strip())
        or args.once
        or args.include_existing
    )


def main() -> int:
    args = parse_args()
    run_id = args.run_id.strip() or datetime.now().strftime("%Y%m%d-%H%M%S")
    recorder = Recorder(Path(args.record_dir) if args.record_dir else None, run_id)
    recorder.prepare()
    state = MonitorState(recorder=recorder)
    if recorder.enabled:
        log(f"record-dir: {recorder.root}")
    if compare_only_requested(args):
        maybe_generate_report(args, state)
        return 0
    if not args.password and not args.no_web:
        log("--password 必填，除非只做 --compare --record-dir 或 --no-web")
        return 2
    if not (args.password or args.opencode_password) and (args.capture_opencode_sse or args.capture_session_messages or args.opencode_url):
        log("--password 或 --opencode-password 必填，用于 opencode basic auth")
        return 2
    try:
        if args.capture_session_messages:
            ensure_opencode_base_url(args, state)
        should_monitor_opencode = bool(args.capture_opencode_sse or (args.opencode_url and not args.capture_session_messages))
        if should_monitor_opencode and args.once:
            monitor_opencode(args, state, max_events=1)
        elif should_monitor_opencode:
            start_opencode_thread(args, state)
        if not args.no_web:
            poll_all(args, state, initial=True)
        if args.once:
            maybe_generate_report(args, state)
            return 0
        prompts = load_prompts(args)
        if args.capture_web_stream and prompts:
            code = run_web_stream_prompts(args, state, prompts)
            maybe_generate_report(args, state)
            return code
        if args.capture_web_stream and not prompts:
            log("--capture-web-stream 未提供 --prompt；仅轮询记录 history/session")
        while True:
            poll_all(args, state)
            time.sleep(max(0.2, args.interval))
    except KeyboardInterrupt:
        log("stopped")
        maybe_generate_report(args, state)
        return 130
    except Exception as exc:
        log(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
