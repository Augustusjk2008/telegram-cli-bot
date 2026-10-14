"""
CLI 模块测试

直接导入 bot.cli 中的真实函数进行测试
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.cli import (
    AntigravityJsonStreamParser,
    ClaudeJsonStreamParser,
    CliStreamParseResult,
    CodexJsonStreamParser,
    build_cli_command,
    parse_antigravity_json_output,
    parse_codex_json_line,
)
from bot.cli_params import (
    CliParamsConfig,
    clamp_unsafe_cli_params,
    get_cli_output_limits,
    get_default_params,
)
from bot.web.native_history_adapter import create_stream_trace_state, consume_stream_trace_chunk


ANTIGRAVITY_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "antigravity"


@pytest.mark.parametrize("cli_type", ["codex", "claude"])
@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (["first-model", "second-model", "none"], "first-model"),
        (["none", "first-model"], None),
        ([], None),
    ],
)
def test_cli_model_defaults_follow_configured_order(monkeypatch, cli_type, options, expected):
    monkeypatch.setattr("bot.config.CLI_MODEL_OPTIONS", options)
    config = CliParamsConfig.from_dict({cli_type: {"yolo": True}})
    assert config.get_param(cli_type, "model") == expected
    assert get_default_params(cli_type)["model"] == expected
    config.set_param(cli_type, "model", "custom-model")
    config.reset_to_default(cli_type)
    assert config.get_param(cli_type, "model") == expected
    config.set_param(cli_type, "model", "custom-model")
    config.reset_to_default()
    assert config.get_param(cli_type, "model") == expected


@pytest.mark.parametrize("cli_type", ["codex", "claude"])
@pytest.mark.parametrize("model", ["saved-model", None])
def test_cli_model_defaults_preserve_explicit_saved_choice(monkeypatch, cli_type, model):
    from bot.models import BotProfile

    monkeypatch.setattr("bot.config.CLI_MODEL_OPTIONS", ["first-model", "none"])
    profile = BotProfile.from_dict({"alias": "saved", "cli_params": {cli_type: {"model": model}}})
    restored = BotProfile.from_dict(profile.to_dict())
    assert restored.cli_params.get_param(cli_type, "model") == model


class TestBuildCliCommand:
    """测试 build_cli_command"""

    def test_codex_resume_keeps_mcp_and_builtin_config_in_one_argument_scope(self, tmp_path):
        params_config = CliParamsConfig()
        params_config.codex.update({
            "reasoning_effort": "high",
            "model": "test-model",
            "json_output": True,
            "extra_args": [
                "--sandbox", "workspace-write",
                "-c", 'mcp_servers.tcb-remote.command="python"',
                "-c", 'mcp_servers.tcb-remote.args=["remote.py"]',
                "-c", 'mcp_servers.tcb-cluster.command="cluster"',
            ],
        })
        kwargs = dict(cli_type="codex", resolved_cli="codex", user_text="hello", env={},
                      params_config=params_config, working_dir=str(tmp_path))
        fresh, _ = build_cli_command(**kwargs)
        resumed, use_stdin = build_cli_command(**kwargs, session_id="saved-thread", resume_session=True)

        # Codex replaces global -c values across subcommand levels instead of
        # merging them. A resumed turn must retain the fresh turn's option scope.
        resume_index = resumed.index("resume")
        assert resumed[:resume_index] == fresh[:-1]
        assert resumed[resume_index + 1:] == ["saved-thread", "-"]
        assert use_stdin

    def test_claude_plan_mode_overrides_native_plan_permission_mode(self):
        params_config = CliParamsConfig()
        params_config.claude["extra_args"] = [
            "--permission-mode",
            "plan",
            "--keep",
            "--permission-mode=plan",
            "--permission-mode",
            "acceptEdits",
        ]

        cmd, _ = build_cli_command(
            cli_type="claude",
            resolved_cli="claude",
            user_text="hello",
            env={},
            params_config=params_config,
            task_mode="plan",
        )

        assert "--keep" in cmd
        plan_arg_pairs = list(zip(cmd, cmd[1:]))
        assert ("--permission-mode", "plan") not in plan_arg_pairs
        assert "--permission-mode=plan" not in cmd
        permission_mode_index = cmd.index("--permission-mode")
        assert cmd[permission_mode_index + 1] == "default"
        assert cmd.count("--permission-mode") == 1

    def test_cli_yolo_flags_require_explicit_config(self):
        env = {}
        params_config = CliParamsConfig()
        params_config.codex["yolo"] = True
        params_config.claude["yolo"] = True

        codex_cmd, _ = build_cli_command(
            cli_type="codex",
            resolved_cli="codex",
            user_text="hello",
            env=env,
            params_config=params_config,
        )
        claude_cmd, _ = build_cli_command(
            cli_type="claude",
            resolved_cli="claude",
            user_text="hello",
            env=env,
            params_config=params_config,
        )

        assert "--dangerously-bypass-approvals-and-sandbox" in codex_cmd
        assert "--dangerously-skip-permissions" in claude_cmd

    def test_clamp_unsafe_cli_params_filters_extra_args(self):
        params_config = CliParamsConfig()
        params_config.codex["extra_args"] = [
            "--safe",
            "--dangerously-bypass-approvals-and-sandbox",
            "--approval-policy",
            "never",
            "--sandbox=danger-full-access",
            "-c",
            "sandbox_mode=\"danger-full-access\"",
        ]
        params_config.claude["extra_args"] = [
            "--keep",
            "--dangerously-skip-permissions",
            "--permission-mode",
            "bypassPermissions",
        ]

        clamped = clamp_unsafe_cli_params(params_config, allow_unsafe_cli=False)
        allowed = clamp_unsafe_cli_params(params_config, allow_unsafe_cli=True)

        assert clamped.codex["extra_args"] == ["--safe"]
        assert clamped.claude["extra_args"] == ["--keep"]
        assert allowed.codex["extra_args"] == params_config.codex["extra_args"]


class TestParseCodexJsonLine:
    @pytest.mark.parametrize(
        "line",
        [
            '{"type":"item.completed","item":{"type":"assistant_message","text":"最终答复"}}',
            '{"type":"event_msg","payload":{"type":"agent_message","message":"最终答复"}}',
            '{"type":"response_item","item":{"type":"message","role":"assistant","phase":"final","content":[{"type":"output_text","text":"最终答复"}]}}',
        ],
    )
    def test_terminal_events_are_not_replayed_as_delta(self, line: str):
        parsed = parse_codex_json_line(line)

        assert parsed["completed_text"] == "最终答复"
        assert parsed["delta_text"] is None

    @pytest.mark.parametrize(
        "line",
        [
            '{"type":"event_msg","payload":{"type":"agent_message","phase":"commentary","message":"过程说明"}}',
            '{"type":"item.completed","item":{"type":"assistant_message","phase":"commentary","text":"过程说明"}}',
        ],
    )
    def test_commentary_agent_message_remains_a_delta(self, line: str):
        parsed = parse_codex_json_line(line)

        assert parsed["completed_text"] is None
        assert parsed["delta_text"] == "过程说明"


class TestIncrementalCliParsers:
    @pytest.mark.parametrize(
        ("parser_type", "terminal_type", "last_terminal_type", "cache_usage"),
        [
            (CodexJsonStreamParser, "turn.completed", "turn.failed", {
                "cached_input_tokens": 8,
                "cache_write_input_tokens": 2,
            }),
            (ClaudeJsonStreamParser, "result", "result", {
                "cache_read_input_tokens": 8,
                "cache_creation_input_tokens": 4,
                "cache_creation": {"ephemeral_5m_input_tokens": 1, "ephemeral_1h_input_tokens": 3},
            }),
        ],
    )
    def test_terminal_usage_keeps_last_valid_snapshot_only(
        self, parser_type, terminal_type, last_terminal_type, cache_usage,
    ):
        parser = parser_type(raw_tail_max_bytes=96, final_text_max_bytes=1024)
        usage = {"input_tokens": 100, "output_tokens": 20, **cache_usage}
        parser.consume_line(json.dumps({"type": "assistant", "usage": usage}))
        assert parser.result().terminal_usage is None

        parser.consume_line(json.dumps({"type": terminal_type, "usage": usage}))
        first_result = parser.result()
        final_usage = {**usage, "input_tokens": 200, "output_tokens": 0}
        terminal = json.dumps({
            "type": last_terminal_type,
            "usage": {**final_usage, "unrelated": {"large": "x" * 1000}},
            "modelUsage": {"another-model": {"inputTokens": 9000}},
        })
        parser.consume_line(terminal)
        parser.consume_line(terminal)
        for invalid_usage in (
            None, [], {}, {"input_tokens": 7},
            {"input_tokens": True, "output_tokens": 1},
            {"input_tokens": -1, "output_tokens": 1},
            {"input_tokens": "7", "output_tokens": 1},
            {**final_usage, next(iter(cache_usage)): "invalid"},
        ):
            parser.consume_line(json.dumps({"type": terminal_type, "usage": invalid_usage}))
        parser.consume_line('{"type":')
        parser.consume_line('[]')

        assert first_result.terminal_usage == usage
        assert parser.result().terminal_usage == final_usage
        assert len(parser.result().raw_tail.encode("utf-8")) <= 96

    def test_parse_result_terminal_usage_is_optional(self):
        result = CliStreamParseResult("done", None, None, "", 0, False)

        assert result.terminal_usage is None

    def test_codex_parser_keeps_final_text_and_bounded_raw_tail(self):
        parser = CodexJsonStreamParser(raw_tail_max_bytes=96, final_text_max_bytes=1024)

        for index in range(50):
            parser.consume_line(
                f'{{"type":"item.delta","item":{{"type":"assistant_message","delta":"step-{index}"}}}}\n'
            )
        parser.consume_line('{"type":"thread.started","thread_id":"thread-9"}\n')
        parser.consume_line(
            '{"type":"event_msg","payload":{"type":"agent_message","message":"最终答复"}}\n'
        )

        result = parser.result()

        assert result.final_text == "最终答复"
        assert result.session_id == "thread-9"
        assert len(result.raw_tail.encode("utf-8")) <= 96
        assert result.total_bytes > len(result.raw_tail.encode("utf-8"))

    def test_cli_output_limits_are_configurable_and_clamped(self):
        limits = get_cli_output_limits(
            {
                "TCB_CLI_STDOUT_QUEUE_MAX_CHUNKS": "2",
                "TCB_CLI_MAX_LINE_BYTES": "16",
                "TCB_CLI_MAX_TOTAL_BYTES": "8",
                "TCB_CLI_RAW_TAIL_MAX_BYTES": "0",
                "TCB_CLI_FINAL_TEXT_MAX_BYTES": "32",
            }
        )

        assert limits.queue_max_chunks == 2
        assert limits.max_line_bytes == 16
        assert limits.max_total_bytes == 16
        assert limits.raw_tail_max_bytes == 1
        assert limits.final_text_max_bytes == 32


def test_antigravity_command_uses_prompt_stream_json_and_conversation() -> None:
    params = CliParamsConfig.from_dict({
        "antigravity": {
            "model": "gemini-3.8-flash-medium",
            "effort": "high",
            "agent": "reviewer",
            "sandbox": True,
            "yolo": True,
            "print_timeout": 30,
            "extra_args": ["--log-file", "agy.log"],
        },
    })
    command, use_stdin = build_cli_command(
        cli_type="antigravity",
        resolved_cli="agy.exe",
        user_text="hello world",
        env={},
        params_config=params,
        session_id="conversation-1",
    )

    assert use_stdin is False
    assert command == [
        "agy.exe", "-p", "hello world", "--output-format", "stream-json",
        "--model", "gemini-3.8-flash-medium", "--effort", "high",
        "--agent", "reviewer", "--sandbox", "--dangerously-skip-permissions",
        "--print-timeout", "30", "--conversation", "conversation-1",
        "--log-file", "agy.log",
    ]


def test_antigravity_parser_reads_nested_stream_events_and_usage() -> None:
    raw = (ANTIGRAVITY_FIXTURE_DIR / "success.jsonl").read_text(encoding="utf-8")
    result = parse_antigravity_json_output(raw)

    assert result.final_text == "OK"
    assert result.session_id == "agy-conv-success"
    assert result.terminal_status == "SUCCESS"
    assert result.terminal_usage == {
        "input_tokens": 11,
        "output_tokens": 2,
        "thinking_tokens": 3,
        "cache_read_tokens": 4,
        "total_tokens": 20,
    }
    assert result.error_text is None


def test_antigravity_parser_marks_soft_permission_denial_as_failure() -> None:
    raw = (ANTIGRAVITY_FIXTURE_DIR / "denied.jsonl").read_text(encoding="utf-8")
    result = parse_antigravity_json_output(raw)

    assert result.terminal_status == "SUCCESS"
    assert result.denied_actions == [{"action": "command", "display_name": "RunCommand"}]
    assert result.terminal_error == "command — RunCommand"
    assert result.error_text == "command — RunCommand"


def test_antigravity_parser_preserves_structured_error() -> None:
    raw = (ANTIGRAVITY_FIXTURE_DIR / "error.jsonl").read_text(encoding="utf-8")
    result = parse_antigravity_json_output(raw)

    assert result.terminal_status == "ERROR"
    assert result.terminal_error == "invalid model selection"
    assert result.error_text == "invalid model selection"


def test_antigravity_tool_step_maps_to_call_and_result_trace() -> None:
    raw = (ANTIGRAVITY_FIXTURE_DIR / "tool.jsonl").read_text(encoding="utf-8")
    state = create_stream_trace_state("antigravity")
    events = []
    for line in raw.splitlines(keepends=True):
        events.extend(consume_stream_trace_chunk("antigravity", line, state))

    assert [event["kind"] for event in events] == ["tool_call", "tool_result"]
    assert events[0]["tool_name"] == "run_command"
    assert events[0]["call_id"] == "agy-conv-tool:4:run_command"
    assert events[1]["call_id"] == events[0]["call_id"]
