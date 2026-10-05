"""Isolated Codex 0.160.0 voice probe. Start the loopback service manually.

python -m scripts.codex_voice_probe --host 127.0.0.1 --port 0
python -m scripts.codex_voice_probe --check-text  # stdio only, no listening socket
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
import contextlib
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any

from aiohttp import web, WSMsgType

from bot.codex_server.client import (
    APP_SERVER_VERSION,
    REALTIME_CONVERSATION_VERSION,
    CodexServerClient,
    CodexServerError,
)
from bot.platform.executables import build_executable_invocation, resolve_cli_executable


BASELINE_PROMPT = (
    "Use the shell tool to read scripts/codex_voice_probe_fixture.txt. "
    "Report the value of verification_code from section one. Do not infer it without reading."
)
SLOW_PROMPT = (
    "Run one read-only shell command: print PROBE_STARTED, wait 15 seconds, "
    "read scripts/codex_voice_probe_fixture.txt, then print PROBE_FINISHED. Report section two's verification_code."
)
FIXTURE_PATH = Path(__file__).with_name("codex_voice_probe_fixture.txt")
REDACTED = "[redacted]"
M0_REQUIRED_CHECKS = (
    "realtime_started", "remote_sdp", "microphone_acquired", "remote_audio_track",
    "audio_playing", "user_transcript", "assistant_transcript", "turn_started",
    "tool_execution", "turn_completed", "history_read", "realtime_closed",
    "stop_voice_requested", "stop_voice_accepted", "interrupt_requested",
    "interrupt_accepted",
)
_TOOL_ITEM_TYPES = {
    "commandExecution", "command_execution", "mcpToolCall", "mcp_tool_call",
    "dynamicToolCall", "dynamic_tool_call", "fileChange", "file_change",
    "webSearch", "web_search", "collabAgentToolCall", "collab_agent_tool_call",
}
SECRET_KEYS = {
    "authorization", "cookie", "setcookie", "token", "accesstoken", "refreshtoken",
    "idtoken", "apikey", "secret", "clientsecret", "password", "credential", "credentials",
    "email", "sdp", "offer", "answer", "base64", "audiobase64",
}


def sanitize(value: Any, *, event: str = "") -> Any:
    """Keep event identities/text, never persist media, SDP or authentication payloads."""
    if isinstance(value, dict):
        kind = str(value.get("type") or value.get("method") or event)
        audio_delta = "audio" in kind.lower() and "transcript" not in kind.lower()
        result = {}
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if (normalized in SECRET_KEYS or normalized.endswith(("apikey", "accesstoken", "secret"))
                    or (normalized in {"data", "audio"} and isinstance(child, str))
                    or (normalized == "delta" and audio_delta)):
                result[key] = REDACTED
            else:
                result[key] = sanitize(child, event=kind)
        return result
    if isinstance(value, list):
        return [sanitize(item, event=event) for item in value]
    if isinstance(value, str):
        if re.search(r"(?:^|[\r\n])v=0(?:[\r\n]|$)|a=ice-(?:pwd|ufrag):", value):
            return REDACTED
        value = re.sub(r"(?i)\bBearer\s+[^\s\"',}]+", "Bearer " + REDACTED, value)
        value = re.sub(r"\b(?:sk-[A-Za-z0-9_-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", REDACTED, value)
        value = re.sub(r"(?i)((?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|password|token)[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,}]+", r"\1" + REDACTED, value)
        return re.sub(r"[A-Za-z0-9+/]{200,}={0,2}", REDACTED, value)
    return value


class VoiceProbe:
    def __init__(self, client: CodexServerClient, workspace: Path, log_path: Path):
        self.client = client
        self.workspace = workspace
        self.log_path = log_path
        self.log = log_path.open("x", encoding="utf-8")
        self.recent: deque[dict] = deque(maxlen=500)
        self.subscribers: set[asyncio.Queue] = set()
        self.sequence = 0
        self.thread_id = ""
        self.realtime_session_id = None
        self.voice_state = "idle"
        self.task_state = "idle"
        self.active_turn_id = None
        self.turns: dict[str, str] = {}
        self.turn_changed = asyncio.Event()
        self.ready = False
        self.closed = False
        self._checks = {name: False for name in M0_REQUIRED_CHECKS}
        self._observed = {name: 0 for name in M0_REQUIRED_CHECKS}
        self._voice_turn_ids: set[str] = set()
        # Created before the first account/config/thread/turn request, and never replaced.
        self.reader = asyncio.create_task(self._read_events(), name="voice-probe-events")

    def state(self) -> dict:
        return {
            "thread_id": self.thread_id, "voice_state": self.voice_state,
            "task_state": self.task_state, "active_turn_id": self.active_turn_id,
            "workspace": str(self.workspace), "log_path": str(self.log_path),
            "baseline_prompt": BASELINE_PROMPT, "slow_prompt": SLOW_PROMPT,
            "ready": self.ready and self.client.alive,
        }

    def publish(self, packet: dict) -> None:
        for queue in tuple(self.subscribers):
            try:
                queue.put_nowait(packet)
            except asyncio.QueueFull:
                # Disconnect a slow browser rather than block the sole protocol reader.
                self.subscribers.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "disconnect", "error": "Browser event buffer full; consult JSONL log"})

    def publish_state(self) -> None:
        self.publish({"type": "state", "state": self.state()})

    def _mark_check(self, name: str) -> None:
        self._observed[name] += 1
        self._checks[name] = True

    @staticmethod
    def _has_transcript_payload(data: dict) -> bool:
        item = data.get("item") if isinstance(data.get("item"), dict) else {}
        return any(isinstance(value, str) and value.strip()
                   for value in (data.get("text"), data.get("transcript"), data.get("delta"),
                                 item.get("text"), item.get("transcript"), item.get("delta")))

    def _transcript_role(self, name: str, data: dict) -> str | None:
        item = data.get("item") if isinstance(data.get("item"), dict) else {}
        role = item.get("role") or data.get("role")
        if role in {"user", "assistant"}:
            return role
        if name.startswith("conversation.item.input_audio_transcription."):
            return "user"
        if name.startswith(("response.audio_transcript.", "response.output_audio_transcript.",
                            "response.output_text.")):
            return "assistant"
        return None

    def _observe_event(self, source: str, name: str, data: dict) -> None:
        if source == "request":
            if name == "thread/realtime/stop":
                self._mark_check("stop_voice_requested")
            elif name == "turn/interrupt":
                self._mark_check("interrupt_requested")
            return

        if source == "response":
            if "error" in data:
                return
            if name == "thread/realtime/stop":
                self._mark_check("stop_voice_accepted")
            elif name == "turn/interrupt":
                self._mark_check("interrupt_accepted")
            elif name == "thread/read" and self._checks["realtime_started"]:
                thread = data.get("thread") if isinstance(data.get("thread"), dict) else {}
                turns = thread.get("turns")
                history_turn_ids = {
                    str(turn.get("id")) for turn in turns
                    if isinstance(turn, dict) and turn.get("id")
                } if isinstance(turns, list) else set()
                if (thread.get("id") == self.thread_id
                        and self._voice_turn_ids.intersection(history_turn_ids)):
                    self._mark_check("history_read")
            return

        if source == "browser":
            if name == "media.microphone_acquired":
                self._mark_check("microphone_acquired")
            elif name == "media.remote_track" and str(data.get("kind", "")).lower() == "audio":
                self._mark_check("remote_audio_track")
            elif name == "media.audio.playing":
                self._mark_check("audio_playing")

        if name == "thread/realtime/started" and source == "app-server":
            if data.get("realtimeSessionId"):
                self._mark_check("realtime_started")
        elif name == "thread/realtime/sdp" and source == "app-server":
            if isinstance(data.get("sdp"), str) and data["sdp"].strip():
                self._mark_check("remote_sdp")
        elif name == "thread/realtime/closed" and source == "app-server":
            self._mark_check("realtime_closed")

        # A baseline text turn must not satisfy the voice task checks.
        voice_task_seen = self._checks["realtime_started"]
        if name == "turn/started" and voice_task_seen:
            turn = data.get("turn") if isinstance(data.get("turn"), dict) else {}
            turn_id = turn.get("id") or data.get("turnId")
            if turn_id:
                self._voice_turn_ids.add(str(turn_id))
                self._mark_check("turn_started")
        elif name == "turn/completed" and voice_task_seen:
            turn = data.get("turn") if isinstance(data.get("turn"), dict) else {}
            turn_id = turn.get("id") or data.get("turnId")
            if turn_id and turn.get("status") == "completed":
                self._voice_turn_ids.add(str(turn_id))
                self._mark_check("turn_completed")

        if voice_task_seen and name.startswith("item/"):
            item = data.get("item") if isinstance(data.get("item"), dict) else {}
            item_type = item.get("type") or data.get("itemType") or data.get("type")
            known_item = item_type in _TOOL_ITEM_TYPES
            known_name = any(f"/{kind}/" in name for kind in _TOOL_ITEM_TYPES)
            if known_item or known_name:
                self._mark_check("tool_execution")

        if voice_task_seen and self._has_transcript_payload(data):
            role = self._transcript_role(name, data)
            if role == "user" and (name.startswith("thread/realtime/")
                                    or name.startswith("conversation.item.input_audio_transcription.")):
                self._mark_check("user_transcript")
            elif role == "assistant" and (name.startswith("thread/realtime/")
                                          or name.startswith("response.")):
                self._mark_check("assistant_transcript")

    def validation_summary(self) -> dict:
        missing = [name for name in M0_REQUIRED_CHECKS if not self._checks[name]]
        return {
            "status": "passed" if not missing else "incomplete",
            "checks": {name: self._checks[name] for name in M0_REQUIRED_CHECKS},
            "missing": missing,
            "observed": {name: self._observed[name] for name in M0_REQUIRED_CHECKS},
        }

    def record(self, source: str, name: str, data: dict, *, request_id=None, observe: bool = True) -> dict:
        if observe:
            self._observe_event(source, name, data)
        data = sanitize(data, event=name)
        item = data.get("item") if isinstance(data.get("item"), dict) else {}
        turn = data.get("turn") if isinstance(data.get("turn"), dict) else {}
        self.sequence += 1
        entry = {
            "sequence": self.sequence, "time": datetime.now(timezone.utc).isoformat(),
            "source": source, "name": name, "request_id": request_id,
            "thread_id": data.get("threadId") or data.get("thread_id") or self.thread_id or None,
            # Do not invent a turn association for flat, uncorrelated voice transcripts.
            "turn_id": data.get("turnId") or data.get("turn_id") or turn.get("id") or item.get("turn_id"),
            "realtime_session_id": data.get("realtimeSessionId") or item.get("realtimeSessionId") or self.realtime_session_id,
            "item_id": data.get("itemId") or data.get("item_id") or item.get("id"),
            "data": data,
        }
        self.log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.log.flush()
        self.recent.append(entry)
        self.publish({"type": "event", "event": entry})
        return entry

    async def rpc(self, method: str, params: dict, *, project=None) -> dict:
        # request() increments synchronously before its first await; this is its wire ID.
        request_id = self.client._sequence + 1
        self.record("request", method, params, request_id=request_id)
        try:
            result = await self.client.request(method, params)
        except CodexServerError as exc:
            unknown = not self.client.alive or "结果未知" in str(exc)
            self.record("response", method, {"error": str(exc), "outcome": "unknown" if unknown else "rejected"}, request_id=request_id)
            raise
        self.record("response", method, project(result) if project else result, request_id=request_id)
        return result

    async def initialize(self) -> None:
        await self.rpc("account/read", {"refreshToken": False}, project=lambda result: {
            "auth_type": (result.get("account") or {}).get("type"),
            "requiresOpenaiAuth": result.get("requiresOpenaiAuth"),
        })
        result = await self.rpc("config/read", {"cwd": str(self.workspace), "includeLayers": False},
                                project=lambda result: {"config": {
                                    key: value for key, value in result.get("config", {}).items()
                                    if key in {"model", "model_provider", "model_reasoning_effort", "realtime", "realtime_model", "realtime_conversation_version"}
                                }})
        # Disable configured external tools for this fixture-only thread. Keep model defaults.
        config = {f'mcp_servers.{name}.enabled': False for name in result.get("config", {}).get("mcp_servers", {})}
        result = await self.rpc("thread/start", {
            "cwd": str(self.workspace), "sandbox": "read-only", "approvalPolicy": "never",
            "runtimeWorkspaceRoots": [str(self.workspace)],
            "config": config,
            "developerInstructions": "This is an isolated voice probe. Only read the fixed fixture in the provided read-only workspace. Never write files, use network tools, or delegate to other agents. Give short factual answers based on actual tool results.",
        })
        self.thread_id = result["thread"]["id"]
        if result.get("sandbox", {}).get("type") != "readOnly" or result.get("approvalPolicy") != "never":
            raise CodexServerError("Probe requires effective readOnly sandbox and never approval policy")
        self.publish_state()

    def observe_turn(self, turn: dict) -> None:
        turn_id = turn.get("id")
        if not turn_id:
            return
        status = turn.get("status", "inProgress")
        if self.turns.get(turn_id) in {"completed", "interrupted", "failed"}:
            return  # A start acknowledgement may follow its terminal notification.
        self.turns[turn_id] = status
        if status == "inProgress":
            self.active_turn_id = turn_id
            self.task_state = status
        elif not self.active_turn_id or self.active_turn_id == turn_id:
            self.active_turn_id = None
            self.task_state = status
        self.turn_changed.set()

    async def _read_events(self) -> None:
        try:
            async for packet in self.client.events():
                method, params = packet["method"], packet.get("params") or {}
                self.record("app-server", method, params, request_id=packet.get("id"), observe=False)
                if params.get("threadId", self.thread_id) != self.thread_id:
                    continue
                self._observe_event("app-server", method, params)
                if method in {"turn/started", "turn/completed"}:
                    self.observe_turn(params.get("turn") or {})
                elif method == "thread/realtime/started":
                    self.realtime_session_id = params.get("realtimeSessionId")
                    self.voice_state = "started"
                elif method == "thread/realtime/sdp":
                    # SDP exists only in memory and on the authenticated local connection.
                    self.publish({"type": "sdp", "sdp": params["sdp"]})
                elif method == "thread/realtime/error":
                    self.voice_state = "error"
                elif method == "thread/realtime/closed":
                    self.voice_state = "closed"
                self.publish_state()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.closed:
                self.voice_state = "unknown"
                if self.active_turn_id or self.task_state == "submitting":
                    self.task_state = "unknown"
                self.record("probe", "reader/error", {"error": str(exc), "outcome": "unknown"})
                self.turn_changed.set()
                self.publish_state()

    async def text_turn(self, text: str) -> dict:
        if self.active_turn_id or self.task_state in {"submitting", "unknown"}:
            raise ValueError("A task is active or its outcome is unknown; use steer or observe its terminal event")
        self.task_state = "submitting"
        self.publish_state()
        try:
            result = await self.rpc("turn/start", {"threadId": self.thread_id, "input": [{"type": "text", "text": text}]})
            self.observe_turn(result.get("turn") or {})
            return result
        except CodexServerError:
            self.task_state = "unknown" if not self.client.alive else "failed"
            raise
        finally:
            self.publish_state()

    async def baseline(self, timeout: float = 180) -> dict:
        result = await self.text_turn(BASELINE_PROMPT)
        turn_id = result["turn"]["id"]
        async def wait_terminal():
            while self.turns.get(turn_id) not in {"completed", "failed", "interrupted"}:
                self.turn_changed.clear()
                if not self.client.alive:
                    raise CodexServerError("Baseline outcome unknown; app-server disconnected")
                await self.turn_changed.wait()
        try:
            await asyncio.wait_for(wait_terminal(), timeout)
        except asyncio.TimeoutError as exc:
            self.task_state = "unknown"
            self.record("probe", "baseline/timeout", {"turnId": turn_id, "outcome": "unknown"})
            raise CodexServerError("Baseline did not reach a terminal state; outcome unknown") from exc
        history = await self.rpc("thread/read", {"threadId": self.thread_id, "includeTurns": True})
        turn = next((item for item in history["thread"].get("turns", []) if item.get("id") == turn_id), {})
        items = turn.get("items", [])
        tool_ok = any(item.get("type") == "commandExecution" and item.get("exitCode") == 0
                      and "ORBIT-417" in (item.get("aggregatedOutput") or "") for item in items)
        answer_ok = any(item.get("type") == "agentMessage" and "ORBIT-417" in item.get("text", "") for item in items)
        self.ready = self.turns[turn_id] == "completed" and tool_ok and answer_ok
        summary = {"turnId": turn_id, "status": self.turns[turn_id], "tool_read_verified": tool_ok, "answer_verified": answer_ok}
        self.record("probe", "baseline/result", summary)
        self.publish_state()
        return summary

    async def command(self, message: dict) -> dict:
        op = message.get("op")
        if op == "summary":
            return self.validation_summary()
        if op == "browser_event":
            name, data = message.get("name"), message.get("data", {})
            if not isinstance(name, str) or len(name) > 160 or not isinstance(data, dict):
                raise ValueError("Invalid browser event")
            self.record("browser", name, data)
            return {}
        if op == "history":
            return sanitize(await self.rpc("thread/read", {"threadId": self.thread_id, "includeTurns": True}))
        if op in {"text", "steer"}:
            text = message.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 16000:
                raise ValueError("Text must contain 1–16000 characters")
            if op == "text":
                return await self.text_turn(text)
            turn_id = self.active_turn_id
            if not turn_id or message.get("expected_turn_id", turn_id) != turn_id:
                raise ValueError("No matching active turn to steer")
            return await self.rpc("turn/steer", {"threadId": self.thread_id, "expectedTurnId": turn_id,
                                                 "input": [{"type": "text", "text": text}]})
        if op == "interrupt":
            turn_id = self.active_turn_id
            if not turn_id:
                raise ValueError("No observed active turn to interrupt")
            result = await self.rpc("turn/interrupt", {"threadId": self.thread_id, "turnId": turn_id})
            # Acceptance is not a terminal state; only turn/completed can establish that.
            return {"accepted": True, "turn_id": turn_id, **result}
        if op == "start_voice":
            if not self.ready:
                raise ValueError("Text/tool baseline must pass before voice probing")
            if self.voice_state not in {"idle", "closed"}:
                raise ValueError("Voice session not closed; stop and observe before starting again")
            sdp = message.get("sdp")
            if not isinstance(sdp, str) or not sdp.startswith("v=0") or len(sdp) > 128000:
                raise ValueError("Invalid SDP offer")
            self.realtime_session_id = None
            self.voice_state = "starting"
            self.publish_state()
            try:
                return await self.rpc("thread/realtime/start", {"threadId": self.thread_id,
                    "outputModality": "audio", "version": REALTIME_CONVERSATION_VERSION,
                    "transport": {"type": "webrtc", "sdp": sdp}})
            except CodexServerError:
                self.voice_state = "unknown" if not self.client.alive else "error"
                self.publish_state()
                raise
        if op == "stop_voice":
            if self.voice_state in {"idle", "closed"}:
                return {"already_closed": True}
            self.voice_state = "stopping"
            self.publish_state()
            try:
                return await self.rpc("thread/realtime/stop", {"threadId": self.thread_id})
            except CodexServerError:
                self.voice_state = "unknown" if not self.client.alive else "error"
                self.publish_state()
                raise
        raise ValueError("Unknown probe operation")

    async def close(self) -> None:
        self.closed = True
        await self.client.close()
        self.reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.reader
        self.log.close()


def create_app(probe: VoiceProbe, access_token: str) -> web.Application:
    """One-use URL token exchanges for one local, HttpOnly browser session."""
    session = secrets.token_urlsafe(32)
    cookie_name = "voice_probe_" + secrets.token_hex(8)
    claimed = False
    connected = False
    sockets: set[web.WebSocketResponse] = set()

    @web.middleware
    async def boundary(request, handler):
        if request.host != request.transport.get_extra_info("sockname")[0] + ":" + str(request.transport.get_extra_info("sockname")[1]):
            raise web.HTTPForbidden(text="Use the printed loopback URL")
        if request.method != "GET" or request.path == "/ws":
            if request.headers.get("Origin") != f"http://{request.host}":
                raise web.HTTPForbidden(text="Same-origin browser required")
        response = await handler(request)
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"})
        return response

    async def page(request):
        return web.Response(text=Path(__file__).with_suffix(".html").read_text(encoding="utf-8"), content_type="text/html")

    async def claim(request):
        nonlocal claimed
        if request.cookies.get(cookie_name) != session:
            try:
                body = await request.json()
            except (ValueError, UnicodeDecodeError):
                raise web.HTTPBadRequest(text="Expected JSON")
            token = body.get("token") if isinstance(body, dict) else None
            if claimed or not isinstance(token, str) or not secrets.compare_digest(token, access_token):
                raise web.HTTPForbidden(text="Access token invalid or already used")
            claimed = True
        response = web.json_response({"ok": True})
        response.set_cookie(cookie_name, session, httponly=True, samesite="Strict")
        return response

    async def websocket(request):
        nonlocal connected
        if not claimed or request.cookies.get(cookie_name) != session:
            raise web.HTTPForbidden(text="Claim the probe token first")
        if connected:
            raise web.HTTPConflict(text="Probe already open in another tab")
        connected = True
        ws = web.WebSocketResponse(max_msg_size=160000, heartbeat=20)
        queue = asyncio.Queue(maxsize=1024)
        jobs: set[asyncio.Task] = set()
        seen: set[str] = set()
        sender = None
        try:
            await ws.prepare(request)
            sockets.add(ws)
            probe.subscribers.add(queue)
            for entry in probe.recent:
                queue.put_nowait({"type": "event", "event": entry})
            queue.put_nowait({"type": "state", "state": probe.state()})

            async def send():
                while True:
                    packet = await queue.get()
                    await ws.send_json(packet)
                    if packet["type"] == "disconnect":
                        await ws.close()
                        return

            async def execute(message):
                request_id = message["id"]
                try:
                    result = await probe.command(message)
                    reply = {"type": "result", "id": request_id, "ok": True, "result": sanitize(result)}
                except (ValueError, CodexServerError) as exc:
                    reply = {"type": "result", "id": request_id, "ok": False, "error": sanitize(str(exc)),
                             "outcome": "rejected" if probe.client.alive else "unknown"}
                await queue.put(reply)

            sender = asyncio.create_task(send())
            async for packet in ws:
                if packet.type != WSMsgType.TEXT:
                    continue
                try:
                    request_id = None
                    message = json.loads(packet.data)
                    request_id = message.get("id") if isinstance(message, dict) else None
                    if not isinstance(request_id, str) or not request_id or len(request_id) > 100:
                        raise ValueError("Each operation needs a bounded unique ID")
                    if request_id in seen or len(seen) >= 20000 or len(jobs) >= 16:
                        raise ValueError("Duplicate operation or probe request limit reached; request not sent")
                    seen.add(request_id)
                    job = asyncio.create_task(execute(message))
                    jobs.add(job)
                    job.add_done_callback(jobs.discard)
                except (ValueError, TypeError) as exc:
                    await queue.put({"type": "result", "id": request_id, "ok": False, "error": str(exc), "outcome": "rejected"})
        finally:
            sockets.discard(ws)
            probe.subscribers.discard(queue)
            if sender:
                sender.cancel()
                with contextlib.suppress(asyncio.CancelledError, ConnectionError):
                    await sender
            # Finish already submitted operations; cancelling one would kill the owned client.
            if jobs:
                await asyncio.gather(*jobs, return_exceptions=True)
            if probe.client.alive:
                with contextlib.suppress(CodexServerError):
                    await probe.command({"op": "stop_voice"})
            connected = False
        return ws

    app = web.Application(middlewares=[boundary], client_max_size=160000)
    app.add_routes([web.get("/", page), web.post("/claim", claim), web.get("/ws", websocket)])
    async def shutdown(app):
        for ws in tuple(sockets):
            await ws.close(code=1001, message=b"Probe exiting")
    app.on_shutdown.append(shutdown)
    return app


async def run(args) -> int:
    log_dir = Path(args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / (datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4) + ".jsonl")
    workspace = Path(FIXTURE_PATH.parent.parent)
    executable = resolve_cli_executable(args.codex, str(workspace))
    if not executable:
        raise CodexServerError("Codex executable not found")
    argv = [*build_executable_invocation(executable), "app-server", "--stdio",
            "-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"',
            "-c", "features.multi_agent=false", "-c", "features.apps=false",
            "-c", "features.plugins=false", "-c", 'web_search="disabled"']
    client = await CodexServerClient.start(argv, cwd=str(workspace), env=dict(os.environ),
                                           timeout=60, experimental_api=True)
    probe = VoiceProbe(client, workspace, log_path)
    runner = None
    print(f"Protocol: {APP_SERVER_VERSION}; log: {log_path}", flush=True)
    try:
        await probe.initialize()
        baseline = await probe.baseline()
        print(json.dumps(baseline, ensure_ascii=False), flush=True)
        if not probe.ready:
            print("Text/tool baseline failed; inspect the log before testing voice.", flush=True)
            return 1
        if args.check_text:
            return 0
        token = secrets.token_urlsafe(32)
        runner = web.AppRunner(create_app(probe, token), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, args.host, args.port)
        await site.start()
        port = runner.addresses[0][1]
        print(f"Open once: http://{args.host}:{port}/#token={token}", flush=True)
        print("Ctrl+C exits this probe and cleans up only its own app-server process.", flush=True)
        await asyncio.Event().wait()
    finally:
        if runner:
            await runner.cleanup()
        if not args.check_text:
            print(json.dumps(sanitize({"m0_validation": probe.validation_summary()}),
                             ensure_ascii=False, separators=(",", ":")), flush=True)
        await probe.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", default=0, type=int)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--log-dir", default="docs/runtime/codex-voice-probe")
    parser.add_argument("--check-text", action="store_true", help="Run the real text/tool baseline over stdio, then exit; no HTTP service")
    args = parser.parse_args()
    if not ipaddress.ip_address(args.host).is_loopback or not 0 <= args.port <= 65535:
        parser.error("A loopback host and a port in 0–65535 are required")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except (CodexServerError, OSError) as exc:
        print(sanitize(str(exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
