from __future__ import annotations

from typing import Any, Callable

import pytest

from bot.native_agent.pi_session_runtime import (
    PiSessionRuntime,
    PiSessionRuntimeRequest,
    PiSessionRuntimeState,
)


class FakeClient:
    def __init__(self, events: list[dict[str, Any] | Callable[["FakeClient"], dict[str, Any]]]) -> None:
        self._events = list(events)
        self.sent: list[dict[str, Any]] = []
        self.prompt_calls: list[dict[str, str]] = []
        self.process = type("Process", (), {"poll": lambda _self: None})()

    async def prompt(
        self,
        text: str,
        *,
        conversation_id: str = "",
        agent_id: str = "",
        reasoning_effort: str = "",
    ) -> None:
        self.prompt_calls.append({
            "text": text,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "reasoning_effort": reasoning_effort,
        })

    async def send(self, packet: dict[str, Any]) -> None:
        self.sent.append(dict(packet))

    async def events(self):
        for item in self._events:
            if callable(item):
                yield item(self)
            else:
                yield item

    async def abort(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def kill(self) -> None:
        return None


def _runtime(*, client: FakeClient, reasoning_effort: str = "high") -> PiSessionRuntime:
    return PiSessionRuntime(
        client=client,
        state=PiSessionRuntimeState(
            pi_runtime_id="pir_1",
            runtime_key="1:1:conv-1",
            owner_key="1:1",
            conversation_id="conv-1",
            cwd="C:/repo",
            command="pi",
            model="anthropic/claude-sonnet-4",
            agent_id="reviewer",
            reasoning_effort=reasoning_effort,
        ),
    )


def test_runtime_match_rejects_reasoning_effort_change():
    runtime = _runtime(client=FakeClient([]), reasoning_effort="high")

    assert runtime.matches(PiSessionRuntimeRequest(
        runtime_key="1:1:conv-1",
        owner_key="1:1",
        conversation_id="conv-1",
        cwd="C:/repo",
        command="pi",
        model="anthropic/claude-sonnet-4",
        agent_id="reviewer",
        reasoning_effort="high",
    )) is True
    assert runtime.matches(PiSessionRuntimeRequest(
        runtime_key="1:1:conv-1",
        owner_key="1:1",
        conversation_id="conv-1",
        cwd="C:/repo",
        command="pi",
        model="anthropic/claude-sonnet-4",
        agent_id="reviewer",
        reasoning_effort="medium",
    )) is False


@pytest.mark.asyncio
async def test_runtime_routes_workspace_history_result_without_stream_competition():
    client = FakeClient([
        lambda current: {
            "type": "workspace_history_result",
            "id": str(current.sent[0]["id"]),
            "head": "head-1",
            "clean": True,
            "manual_change_count": 0,
        },
        {"type": "message_update", "message": {"role": "assistant", "content": "ok"}},
        {"type": "turn_end"},
    ])
    runtime = _runtime(client=client)

    payload = await runtime.request_workspace_history({"action": "status"})
    events = [event async for event in runtime.events()]

    assert client.sent == [{"type": "workspace_history", "id": client.sent[0]["id"], "action": "status"}]
    assert payload["head"] == "head-1"
    assert [event["type"] for event in events] == ["message_update", "turn_end"]
