"""One app-server process per owner/conversation, with exactly one active turn."""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import copy
import hashlib
import json
import os
import threading
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from bot.cli_params import CliParamsConfig
from .client import CodexServerClient, CodexServerError
from .events import CodexServerEventMapper, TOKEN_FIELDS, tokens
from .params import ServerParams, _config_value, check_git_directory, convert_params


@dataclass(frozen=True)
class CodexServerRuntimeRequest:
    owner_key: tuple[int, int, str]
    conversation_id: str
    command: str
    cwd: str
    env: dict[str, str]
    params_config: CliParamsConfig
    thread_id: str = ""


def _config_fingerprint(params: ServerParams, env: dict[str, str]) -> tuple:
    home = Path(env.get("CODEX_HOME") or Path(env.get("USERPROFILE") or env.get("HOME") or Path.home()) / ".codex")
    paths = {home / "config.toml"}
    directory = Path(params.cwd)
    paths.update(parent / ".codex" / "config.toml" for parent in (directory, *directory.parents))
    paths.update(Path(env[key]) for key in ("TCB_CLUSTER_MCP_CONFIG", "TCB_REMOTE_MCP_CONFIG") if env.get(key))
    # Referenced MCP JSON files may retain the same path while their bridge changes.
    def config_paths(value):
        if isinstance(value, (list, tuple)):
            for child in value:
                config_paths(child)
        elif isinstance(value, dict):
            for child in value.values():
                config_paths(child)
        elif isinstance(value, str) and value.endswith((".json", ".toml")):
            path = Path(value)
            paths.add(path if path.is_absolute() else directory / path)
    for argument in params.argv:
        if "=" in argument:
            config_paths(_config_value(argument.split("=", 1)[1]))
    signatures = []
    for path in sorted(paths, key=str):
        try:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        except FileNotFoundError:
            digest = None
        except OSError as exc:
            raise CodexServerError(f"无法检查 app-server 配置文件 {path}: {exc}") from exc
        signatures.append((str(path), digest))
    executable_stats = []
    for value in params.argv[:params.argv.index("app-server")]:
        path = Path(value)
        if path.is_file():
            stat = path.stat()
            executable_stats.append((str(path), stat.st_size, stat.st_mtime_ns))
    return (tuple(params.argv), params.cwd, tuple(sorted(env.items())),
            json.dumps(params.thread, sort_keys=True), tuple(params.add_dirs), tuple(signatures), tuple(executable_stats))


def _transcript_total(path: str | None) -> dict[str, int] | None:
    """Bounded read of the thread's real rollout, to exclude pre-resume billing."""
    if not path:
        return None
    try:
        with open(path, "rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 256 * 1024))
            lines = stream.read().splitlines()
        for raw in reversed(lines):
            try:
                item = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            payload = item.get("payload") or {}
            if item.get("type") == "event_msg" and payload.get("type") == "token_count":
                total = (payload.get("info") or {}).get("total_token_usage")
                if isinstance(total, dict):
                    return {key: max(0, total.get(key, 0)) for key in TOKEN_FIELDS.values()}
    except (OSError, TypeError, ValueError):
        pass
    return None


class CodexServerRuntime:
    def __init__(self, request: CodexServerRuntimeRequest, params: ServerParams, fingerprint: tuple, client: CodexServerClient):
        self.request = request
        self.params = params
        self.fingerprint = fingerprint
        self.client = client
        self.loop = asyncio.get_running_loop()
        self.thread_id = ""
        self.returncode: int | None = None
        self.context_usage: dict[str, Any] = {}
        self._total_usage: dict[str, int] | None = None
        self._default_model: str | None = None
        self._default_effort: str | None = None
        self._mapper: CodexServerEventMapper | None = None
        self._reader: asyncio.Task | None = None
        self._streaming = False
        self._closed = False
        self._turn_id = ""
        self._previous_turns: deque[str] = deque(maxlen=256)
        self._outgoing: deque[dict] = deque()
        self._terminal: dict | None = None
        self._available = asyncio.Event()
        self._turn_done = asyncio.Event()
        self._turn_done.set()
        self._interrupt_lock = asyncio.Lock()
        self._steer_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._failure: Exception | None = None
        self._output_bytes = 0
        self._wire_bytes = 0

    @property
    def active(self) -> bool:
        return self._streaming

    @property
    def alive(self) -> bool:
        return not self._closed and self._failure is None and self.client.alive

    @property
    def terminal_usage(self) -> dict[str, int] | None:
        return dict(self._mapper.usage) if self._mapper and self._mapper.usage is not None else None

    @classmethod
    async def create(cls, request: CodexServerRuntimeRequest, params: ServerParams, fingerprint: tuple):
        await asyncio.to_thread(check_git_directory, params, request.env)
        client = await CodexServerClient.start(params.argv, cwd=params.cwd, env=request.env)
        runtime = cls(request, params, fingerprint, client)
        try:
            config_result = await client.request("config/read", {"cwd": params.cwd, "includeLayers": False})
            config = config_result.get("config") or {}
            runtime._default_model = config.get("model")
            runtime._default_effort = config.get("model_reasoning_effort")
            if not runtime._default_model or not runtime._default_effort:
                catalog = await client.request("model/list", {})
                default_model = next((item for item in catalog.get("data", []) if item.get("isDefault")), {})
                runtime._default_model = runtime._default_model or default_model.get("model")
                model_info = next((item for item in catalog.get("data", [])
                                   if item.get("model") == runtime._default_model), default_model)
                runtime._default_effort = runtime._default_effort or model_info.get("defaultReasoningEffort")
            thread_params = {"cwd": params.cwd, **params.thread}
            if params.add_dirs:
                roots = (config.get("sandbox_workspace_write") or {}).get("writable_roots") or []
                thread_params["config"] = {"sandbox_workspace_write.writable_roots": list(dict.fromkeys([*roots, *params.add_dirs]))}
            if params.model:
                thread_params["model"] = params.model
            # Native Plan Mode is never enabled by the project Plan prompt.
            if request.thread_id:
                thread_params.pop("ephemeral", None)
                thread_params.update(threadId=request.thread_id, excludeTurns=True)
                response = await client.request("thread/resume", thread_params)
            else:
                response = await client.request("thread/start", thread_params)
            thread = response.get("thread") or {}
            runtime.thread_id = str(thread.get("id") or "")
            if not runtime.thread_id or (request.thread_id and runtime.thread_id != request.thread_id):
                raise CodexServerError("不兼容的 thread 响应：thread.id 缺失或与请求不符（不能使用 sessionId）")
            runtime._default_model = runtime._default_model or (response.get("model") if not params.model else None)
            runtime._default_effort = runtime._default_effort or response.get("reasoningEffort")
            runtime._total_usage = _transcript_total(thread.get("path")) if request.thread_id else tokens({})
            runtime._reader = asyncio.create_task(runtime._read_events(), name="codex-server-runtime-reader")
            return runtime
        except BaseException:
            await client.close()
            raise

    def _publish(self, events: list[dict]) -> None:
        for event in events:
            if event.get("type") in {"turn.completed", "turn.failed"}:
                if self._terminal is None:
                    self._terminal = event
                    self.returncode = 0 if event["type"] == "turn.completed" else (130 if event.get("status") == "interrupted" else 1)
                    self._turn_done.set()
            else:
                self._output_bytes += len(json.dumps(event, ensure_ascii=False).encode("utf-8"))
                if len(self._outgoing) >= 256 or self._output_bytes > self.client.limits.max_total_bytes:
                    raise CodexServerError("codex server 当轮输出超过有界缓冲限制")
                self._outgoing.append(event)
        self._available.set()

    def _finish_failure(self, exc: Exception) -> None:
        self._failure = exc
        if self._mapper is not None and self._terminal is None:
            # Retain queued partial output and usage even when the output limit hit.
            events = self._mapper.finish(error=str(exc))
            if not events:
                events = [{"type": "error", "message": str(exc)},
                          {"type": "turn.failed", "status": "failed", "thread_id": self.thread_id,
                           "turn_id": self._turn_id}]
                if self._mapper.usage is not None:
                    events[-1]["usage"] = dict(self._mapper.usage)
            self._outgoing.extend(events[:-1])
            self._terminal = events[-1]
            self.returncode = 1
        self._turn_done.set()
        self._available.set()

    async def _read_events(self) -> None:
        try:
            async for packet in self.client.events():
                payload = packet.get("params") or {}
                if payload.get("threadId") != self.thread_id:
                    continue
                incoming = str(payload.get("turnId") or (payload.get("turn") or {}).get("id") or "")
                if not self._streaming:
                    if packet.get("method") == "thread/tokenUsage/updated":
                        self._total_usage = tokens((payload.get("tokenUsage") or {}).get("total") or {})
                    continue
                if incoming in self._previous_turns:
                    continue
                if self._mapper.turn_id and incoming and incoming != self._mapper.turn_id:
                    continue
                self._wire_bytes += len(json.dumps(packet, ensure_ascii=False).encode("utf-8"))
                if self._wire_bytes > self.client.limits.max_total_bytes:
                    raise CodexServerError("codex server 当轮协议数据超过限制")
                if packet.get("method") == "turn/started":
                    self._turn_id = incoming
                events = self._mapper.consume(packet)
                self._total_usage = self._mapper.total_usage
                self.context_usage = dict(self._mapper.context_usage)
                model = self.params.model or self._default_model
                if self.context_usage and model:
                    self.context_usage["model"] = model
                self._publish(events)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._finish_failure(exc)
            await self.client.close()

    async def stream_turn(self, prompt: str):
        if self._streaming:
            raise CodexServerError("codex server 同一运行时只允许一个活动 turn")
        if not self.alive:
            raise self._failure or CodexServerError("codex server 运行时已关闭，请重新 open_or_create")
        self._streaming = True
        self.returncode = None
        self._turn_id = ""
        self._terminal = None
        self._outgoing.clear()
        self._output_bytes = 0
        self._wire_bytes = 0
        self.context_usage = {}
        self._turn_done.clear()
        self._available.clear()
        self._mapper = CodexServerEventMapper(self.thread_id, self._total_usage,
                                             text_limit=self.client.limits.final_text_max_bytes)
        try:
            yield {"type": "thread.started", "thread_id": self.thread_id}
            params = {"threadId": self.thread_id, "input": [{"type": "text", "text": prompt}, *self.params.inputs],
                      "model": self.params.model or self._default_model,
                      "effort": self.params.effort or self._default_effort, **self.params.turn}
            response = await self.client.request("turn/start", params)
            turn_id = str((response.get("turn") or {}).get("id") or "")
            if not turn_id or (self._turn_id and self._turn_id != turn_id):
                raise CodexServerError("不兼容的 turn/start 响应：turn.id 缺失或不匹配")
            self._turn_id = self._mapper.turn_id = turn_id
            timeout = float(self.request.env.get("TCB_CODEX_SERVER_TURN_TIMEOUT", "1800"))
            deadline = self.loop.time() + max(1, timeout)
            while True:
                while self._outgoing:
                    yield self._outgoing.popleft()
                if self._terminal is not None:
                    yield self._terminal
                    break
                self._available.clear()
                await asyncio.wait_for(self._available.wait(), max(0.001, deadline - self.loop.time()))
        except (asyncio.CancelledError, GeneratorExit):
            await asyncio.shield(self.interrupt())
            raise
        except Exception as exc:
            self._finish_failure(exc)
            await self.client.close()
            while self._outgoing:
                yield self._outgoing.popleft()
            if self._terminal is not None:
                yield self._terminal
        finally:
            if not self._turn_done.is_set():
                await self.interrupt()
            if self._turn_id:
                self._previous_turns.append(self._turn_id)
            self._streaming = False

    async def interrupt(self) -> None:
        async with self._interrupt_lock:
            if self._turn_done.is_set():
                return
            if not self._turn_id or not self.client.alive:
                self._finish_failure(CodexServerError("Codex turn interrupted before start acknowledgement"))
                await self.client.close()
                return
            try:
                await self.client.request("turn/interrupt", {"threadId": self.thread_id, "turnId": self._turn_id}, timeout=10)
                await asyncio.wait_for(self._turn_done.wait(), 10)
            except Exception as exc:
                self._finish_failure(CodexServerError(f"Codex turn interrupt failed: {exc}"))
                await self.client.close()

    async def steer(self, prompt: str, *, expected_turn_id: str | None = None) -> None:
        async with self._steer_lock:
            if not self.alive:
                raise CodexServerError("codex server 运行时已关闭，无法 steer")
            if not self._streaming:
                raise CodexServerError("codex server 当前没有活动 turn，无法 steer")
            if not self.thread_id:
                raise CodexServerError("codex server 当前 turn 缺少 thread_id，无法 steer")
            turn_id = self._turn_id
            if not turn_id:
                raise CodexServerError("codex server 当前 turn 缺少 turn_id，无法 steer")
            if expected_turn_id is not None and expected_turn_id != turn_id:
                raise CodexServerError(
                    f"codex server turn 不匹配：expected {expected_turn_id!r}, current {turn_id!r}"
                )
            await self.client.request("turn/steer", {
                "threadId": self.thread_id,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": prompt}],
            })

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            await self.interrupt()
            await self.client.close()
            if self._reader and self._reader is not asyncio.current_task():
                self._reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader


class CodexServerRegistry:
    def __init__(self):
        self._runtimes: dict[tuple[int, int, str], CodexServerRuntime] = {}
        self._opening: set[tuple[int, int, str]] = set()
        self._closing: dict[tuple[int, int, str], concurrent.futures.Future] = {}
        self._retiring: dict[tuple[int, int, str], CodexServerRuntime] = {}
        self._opening_threads: dict[tuple[int, int, str], str] = {}
        self._opening_done: dict[tuple[int, int, str], concurrent.futures.Future] = {}
        self._epochs: dict[tuple[int, int, str], int] = {}
        self._lock = threading.RLock()

    async def open_or_create(self, request: CodexServerRuntimeRequest) -> CodexServerRuntime:
        owner = request.owner_key
        with self._lock:
            if owner in self._opening:
                raise CodexServerError("codex server owner 正在打开运行时")
            if request.thread_id and (
                any(r.thread_id == request.thread_id for key, r in {**self._runtimes, **self._retiring}.items() if key != owner)
                or any(thread == request.thread_id for key, thread in self._opening_threads.items() if key != owner)
            ):
                raise CodexServerError("Codex thread 已由另一个 owner 绑定")
            self._opening.add(owner)
            self._opening_threads[owner] = request.thread_id
            opening_done: concurrent.futures.Future = concurrent.futures.Future()
            self._opening_done[owner] = opening_done
            epoch = self._epochs.get(owner, 0)
            closing = self._closing.get(owner)
        try:
            if closing:
                await asyncio.shield(asyncio.wrap_future(closing))
            env = {**os.environ, **request.env}
            request = replace(request, env=env, params_config=copy.deepcopy(request.params_config))
            params = convert_params(request.command, request.cwd, request.params_config)
            fingerprint = await asyncio.to_thread(_config_fingerprint, params, env)
            with self._lock:
                existing = self._runtimes.get(owner)
                # Do not allow another owner to write an already loaded thread.
                if request.thread_id and any(r.thread_id == request.thread_id and r.alive
                                             for key, r in self._runtimes.items() if key != owner):
                    raise CodexServerError("Codex thread 已由另一个 owner 绑定")
            if existing:
                if existing.active:
                    raise CodexServerError("codex server owner 当前 turn 尚未完成")
                if existing.loop is not asyncio.get_running_loop():
                    raise CodexServerError("codex server owner 绑定到其他 event loop；请先 release_owner")
                same_conversation = existing.request.conversation_id == request.conversation_id
                same_thread = not request.thread_id or request.thread_id == existing.thread_id
                if existing.alive and same_conversation and same_thread and existing.fingerprint == fingerprint:
                    existing.params = params
                    existing.request = request
                    return existing
                if same_conversation and same_thread and not request.thread_id:
                    request = replace(request, thread_id=existing.thread_id)
                await existing.close()
            runtime = await CodexServerRuntime.create(request, params, fingerprint)
            with self._lock:
                released = self._epochs.get(owner, 0) != epoch
                if not released:
                    self._runtimes[owner] = runtime
            if released:
                await runtime.close()
                raise CodexServerError("codex server owner 在初始化期间已释放")
            return runtime
        finally:
            with self._lock:
                self._opening.discard(owner)
                self._opening_threads.pop(owner, None)
                self._opening_done.pop(owner, None)
                opening_done.set_result(None)

    def release_owner(self, owner_key: tuple[int, int, str]):
        with self._lock:
            self._epochs[owner_key] = self._epochs.get(owner_key, 0) + 1
            runtime = self._runtimes.pop(owner_key, None)
            if runtime is None:
                return self._closing.get(owner_key) or self._opening_done.get(owner_key)
            completion: concurrent.futures.Future = concurrent.futures.Future()
            self._closing[owner_key] = completion
            self._retiring[owner_key] = runtime
        async def close():
            try:
                await runtime.close()
                with self._lock:
                    opening = self._opening_done.get(owner_key)
                if opening:
                    await asyncio.shield(asyncio.wrap_future(opening))
                completion.set_result(None)
            except BaseException as exc:
                completion.set_exception(exc)
            finally:
                with self._lock:
                    if self._closing.get(owner_key) is completion:
                        self._closing.pop(owner_key, None)
                    self._retiring.pop(owner_key, None)
        try:
            if runtime.loop.is_running() and not runtime.loop.is_closed():
                runtime.loop.call_soon_threadsafe(lambda: runtime.loop.create_task(close()))
            else:
                runtime.client.close_sync()
                runtime._closed = True
                completion.set_result(None)
                with self._lock:
                    self._closing.pop(owner_key, None)
                    self._retiring.pop(owner_key, None)
        except RuntimeError:
            runtime.client.close_sync()
            runtime._closed = True
            completion.set_result(None)
            with self._lock:
                self._closing.pop(owner_key, None)
                self._retiring.pop(owner_key, None)
        return completion

    def release_bot(self, bot_id: int):
        with self._lock:
            owners = set(self._runtimes) | self._opening | set(self._closing)
        return [self.release_owner(owner) for owner in owners if owner[0] == bot_id]

    async def close_owner(self, owner_key: tuple[int, int, str]) -> None:
        future = self.release_owner(owner_key)
        if future:
            await asyncio.shield(asyncio.wrap_future(future))

    async def steer_owner(self, owner_key: tuple[int, int, str], turn_id: str, prompt: str) -> None:
        with self._lock:
            runtime = self._runtimes.get(owner_key)
        if runtime is None:
            raise CodexServerError("codex server owner 没有运行时，无法 steer")
        await runtime.steer(prompt, expected_turn_id=turn_id)

    async def close_bot(self, bot_id: int) -> None:
        for future in self.release_bot(bot_id):
            if future:
                await asyncio.shield(asyncio.wrap_future(future))

    async def aclose(self) -> None:
        with self._lock:
            owners = set(self._runtimes) | self._opening | set(self._closing)
        futures = [self.release_owner(owner) for owner in owners]
        for future in futures:
            if future:
                await asyncio.shield(asyncio.wrap_future(future))


_registry = CodexServerRegistry()


def get_codex_server_registry() -> CodexServerRegistry:
    return _registry


def release_owner(owner_key: tuple[int, int, str]):
    return _registry.release_owner(owner_key)


def release_bot(bot_id: int):
    return _registry.release_bot(bot_id)


async def steer_owner(owner_key: tuple[int, int, str], turn_id: str, prompt: str) -> None:
    await _registry.steer_owner(owner_key, turn_id, prompt)
