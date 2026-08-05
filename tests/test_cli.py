"""
CLI 模块测试

直接导入 bot.cli 中的真实函数进行测试
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.cli import CodexJsonStreamParser, build_cli_command, parse_codex_json_line
from bot.cli_params import (
    CliParamsConfig,
    clamp_unsafe_cli_params,
    get_cli_output_limits,
)

class TestBuildCliCommand:
    """测试 build_cli_command"""

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
    def test_codex_parser_only_marks_explicit_failed_turns(self):
        failed = CodexJsonStreamParser(raw_tail_max_bytes=1024, final_text_max_bytes=1024)
        aborted = CodexJsonStreamParser(raw_tail_max_bytes=1024, final_text_max_bytes=1024)
        failed_then_aborted = CodexJsonStreamParser(
            raw_tail_max_bytes=1024,
            final_text_max_bytes=1024,
        )

        failed.consume_line(
            '{"type":"thread.started","thread_id":"thread-failed"}\n'
        )
        failed.consume_line(
            '{"type":"turn.failed","error":{"message":"boom"}}\n'
        )
        aborted.consume_line(
            '{"type":"event_msg","payload":{"type":"turn_aborted","reason":"interrupted"}}\n'
        )
        failed_then_aborted.consume_line(
            '{"type":"turn.failed","error":{"message":"stopped"}}\n'
        )
        failed_then_aborted.consume_line(
            '{"type":"event_msg","payload":{"type":"turn_aborted","reason":"interrupted"}}\n'
        )

        assert failed.result().turn_failed is True
        assert failed.result().session_id == "thread-failed"
        assert aborted.result().turn_failed is False
        assert failed_then_aborted.result().turn_failed is False

    def test_codex_parser_captures_terminal_token_usage(self):
        parser = CodexJsonStreamParser(raw_tail_max_bytes=1024, final_text_max_bytes=1024)

        parser.consume_line(
            '{"type":"turn.completed","usage":{"input_tokens":100,'
            '"cached_input_tokens":40,"output_tokens":20,"reasoning_output_tokens":8}}\n'
        )

        result = parser.result()

        assert result.token_usage is not None
        assert result.token_usage.token_usage.input_tokens == 100
        assert result.token_usage.token_usage.cached_input_tokens == 40
        assert result.token_usage.token_usage.output_tokens == 20
        assert result.token_usage.token_usage.reasoning_output_tokens == 8
        assert result.token_usage.completed_at.tzinfo is not None
        assert result.invalid_usage_count == 0
        assert result.duplicate_terminal_count == 0

    @pytest.mark.parametrize(
        "usage",
        [
            '{"input_tokens":true,"output_tokens":1}',
            '{"input_tokens":-1,"output_tokens":1}',
            '{"input_tokens":1,"cached_input_tokens":2,"output_tokens":1}',
            '{"input_tokens":1,"output_tokens":1,"reasoning_output_tokens":2}',
            '{"input_tokens":1.5,"output_tokens":1}',
        ],
    )
    def test_codex_parser_rejects_invalid_terminal_token_usage(self, usage: str):
        parser = CodexJsonStreamParser(raw_tail_max_bytes=1024, final_text_max_bytes=1024)

        parser.consume_line(f'{{"type":"turn.completed","usage":{usage}}}\n')

        result = parser.result()
        assert result.token_usage is None
        assert result.invalid_usage_count == 1

    def test_codex_parser_uses_latest_valid_duplicate_terminal_usage(self):
        parser = CodexJsonStreamParser(raw_tail_max_bytes=1024, final_text_max_bytes=1024)

        parser.consume_line(
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\n'
        )
        parser.consume_line(
            '{"type":"turn.completed","usage":{"input_tokens":12,'
            '"cached_input_tokens":3,"output_tokens":4}}\n'
        )

        result = parser.result()
        assert result.token_usage is not None
        assert result.token_usage.token_usage.input_tokens == 12
        assert result.token_usage.token_usage.cached_input_tokens == 3
        assert result.duplicate_terminal_count == 1

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
