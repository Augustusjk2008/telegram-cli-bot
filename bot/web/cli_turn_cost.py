from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bot.codex_usage.rollout import _timestamp
from bot.model_pricing import estimate_usage_cost
from bot.web.native_history_locator import locate_codex_transcript


class CliTurnCost:
    """终态汇总缺失时，仅对本轮已上报的用量计价。"""

    def __init__(self, cli_type: str, model: str) -> None:
        self.cli_type = cli_type
        self.model = model
        self.started_at = datetime.now(timezone.utc)
        self._messages: dict[str, tuple[str, dict[str, Any]]] = {}

    def observe(self, line: str) -> None:
        if self.cli_type != "claude":
            return
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(event, dict) or event.get("type") != "assistant" or event.get("parent_tool_use_id"):
            return
        message = event.get("message")
        if not isinstance(message, dict) or not message.get("id"):
            return
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return
        # 同一个回复可按内容块重复上报；替换快照，不能逐条相加。
        self._messages[str(message["id"])] = (
            str(message.get("model") or self.model),
            {key: value for key, value in usage.items() if key in {
                "input_tokens", "output_tokens", "cache_read_input_tokens",
                "cache_creation_input_tokens", "cache_creation",
            }},
        )

    def estimate_partial(self, session_id: str) -> dict[str, Any] | None:
        if self.cli_type == "codex":
            usages = self._codex_usages(session_id)
        else:
            usages = list(self._messages.values())
        costs = [
            cost for model, usage in usages
            if (cost := estimate_usage_cost(model, usage, protocol=self.cli_type, scope="turn")) is not None
        ]
        if not costs or len({cost["currency"] for cost in costs}) != 1:
            return None
        return {
            "model": ", ".join(dict.fromkeys(cost["model"] for cost in costs)),
            "currency": costs[0]["currency"],
            "scope": "turn",
            "is_partial": True,
            **{
                key: float(sum(Decimal(str(cost[key])) for cost in costs))
                for key in ("input", "cache_read", "cache_write", "output", "total")
            },
        }

    def _codex_usages(self, session_id: str) -> list[tuple[str, dict[str, int]]]:
        if not session_id:
            return []
        ref = locate_codex_transcript(session_id)
        if ref is None:
            return []
        fields = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")
        previous = dict.fromkeys(fields, 0)
        usages: dict[str, dict[str, int]] = {}
        model = self.model
        target_started = False
        deadline = time.monotonic() + 2.0
        try:
            with ref.path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if time.monotonic() >= deadline:
                        break
                    if not any(name in line for name in ('"token_count"', '"task_started"', '"turn_context"')):
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
                        continue
                    payload = event["payload"]
                    if event.get("type") == "turn_context":
                        event_time = _timestamp(event.get("timestamp"))
                        if target_started or (event_time is not None and event_time >= self.started_at):
                            model = str(payload.get("model") or model)
                    if payload.get("type") == "task_started":
                        if target_started:
                            break
                        event_time = _timestamp(event.get("timestamp"))
                        target_started = event_time is not None and event_time >= self.started_at
                        continue
                    if payload.get("type") != "token_count":
                        continue
                    info = payload.get("info")
                    total = info.get("total_token_usage") if isinstance(info, dict) else None
                    if not isinstance(total, dict) or not all(key in total for key in ("input_tokens", "output_tokens")):
                        continue
                    current = {key: total.get(key, 0) for key in fields}
                    if any(type(value) is not int or value < 0 for value in current.values()):
                        continue
                    delta = {key: current[key] - previous[key] for key in fields}
                    previous = current
                    # 累计快照可能重复或重置。重置处缺少可靠差值，跳过该段。
                    if not target_started or any(value < 0 for value in delta.values()):
                        continue
                    if delta["input_tokens"] + delta["output_tokens"] <= 0:
                        continue
                    if delta["cached_input_tokens"] + delta["cache_write_input_tokens"] > delta["input_tokens"]:
                        continue
                    collected = usages.setdefault(model, dict.fromkeys(fields, 0))
                    for key in fields:
                        collected[key] += delta[key]
        except OSError:
            pass
        return list(usages.items())
