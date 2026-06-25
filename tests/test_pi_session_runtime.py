from __future__ import annotations

from typing import Any, Callable

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


def test_runtime_match_accepts_refreshable_metadata_change():
    runtime = _runtime(client=FakeClient([]), reasoning_effort="high")
    runtime.state.command = "pi-old"
    runtime.state.model = "anthropic/claude-sonnet-4"
    runtime.state.agent_id = "reviewer"
    runtime.state.reasoning_effort = "high"
    runtime.state.system_prompt = "全局提示"
    runtime.state.append_system_prompt = "solo prompt"
    runtime.state.config_fingerprint = "old"
    runtime.state.env = {"TCB_CLUSTER_RUN_ID": "clr_old"}

    request = PiSessionRuntimeRequest(
        runtime_key="1:1:conv-1",
        owner_key="1:1",
        conversation_id="conv-1",
        cwd="C:/repo",
        command="pi-new",
        model="anthropic/claude-haiku-3",
        agent_id="reviewer",
        reasoning_effort="medium",
        system_prompt="新全局提示",
        append_system_prompt="solo prompt v2",
        config_fingerprint="new",
        env={"TCB_CLUSTER_RUN_ID": "clr_new"},
    )

    assert runtime.matches(request) is True


def test_runtime_match_rejects_owner_key_change():
    runtime = _runtime(client=FakeClient([]), reasoning_effort="high")

    assert runtime.matches(PiSessionRuntimeRequest(
        runtime_key="1:1:conv-1",
        owner_key="1:1:reviewer",
        conversation_id="conv-1",
        cwd="C:/repo",
        command="pi",
        model="anthropic/claude-sonnet-4",
        agent_id="reviewer",
        reasoning_effort="high",
    )) is False


def test_runtime_refresh_from_request_updates_metadata():
    runtime = _runtime(client=FakeClient([]), reasoning_effort="high")
    runtime.state.command = "pi-old"
    runtime.state.model = "anthropic/claude-haiku-3"
    runtime.state.agent_id = "main"
    runtime.state.reasoning_effort = "high"
    runtime.state.system_prompt = "旧提示"
    runtime.state.append_system_prompt = "旧追加"
    runtime.state.config_fingerprint = "old"
    runtime.state.env = {"TCB_CLUSTER_RUN_ID": "clr_old"}

    runtime.refresh_from_request(PiSessionRuntimeRequest(
        runtime_key="1:1:conv-1",
        owner_key="1:1",
        conversation_id="conv-1",
        cwd="C:/repo",
        command="pi-new",
        model="anthropic/claude-sonnet-4",
        agent_id="reviewer",
        reasoning_effort="medium",
        system_prompt="新提示",
        append_system_prompt="新追加",
        config_fingerprint="new",
        env={"TCB_CLUSTER_RUN_ID": "clr_new"},
    ))

    assert runtime.state.command == "pi-new"
    assert runtime.state.model == "anthropic/claude-sonnet-4"
    assert runtime.state.agent_id == "reviewer"
    assert runtime.state.reasoning_effort == "medium"
    assert runtime.state.system_prompt == "新提示"
    assert runtime.state.append_system_prompt == "新追加"
    assert runtime.state.config_fingerprint == "new"
    assert runtime.state.env == {"TCB_CLUSTER_RUN_ID": "clr_new"}
