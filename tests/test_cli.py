"""
CLI 模块测试

直接导入 bot.cli 中的真实函数进行测试
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.cli import (
    ClaudeJsonStreamParser,
    CodexJsonStreamParser,
    _build_codex_status_terminal_argv,
    _should_finish_codex_status_poll,
    build_cli_command,
    extract_codex_status,
    normalize_cli_type,
    parse_claude_stream_json_line,
    parse_claude_stream_json_output,
    parse_codex_json_line,
    parse_codex_json_output,
    read_codex_status_from_terminal,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
    validate_cli_type,
)
from bot.cli_params import (
    CliParamsConfig,
    clamp_unsafe_cli_params,
    coerce_param_value,
    get_cli_output_limits,
    get_params_schema,
    normalize_cli_model_options,
    with_global_extra_args,
)

class TestValidateCliType:
    """测试 validate_cli_type"""

    def test_valid_types(self):
        assert validate_cli_type("claude") == "claude"
        assert validate_cli_type("codex") == "codex"

    def test_invalid_type(self):
        with pytest.raises(ValueError):
            validate_cli_type("unsupported")

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

    def test_codex_defaults_include_model_and_reasoning_effort_without_yolo(self):
        env = {}
        cmd, use_stdin = build_cli_command(
            cli_type="codex",
            resolved_cli="codex",
            user_text="hello",
            env=env,
            params_config=CliParamsConfig(),
        )
        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
        assert "--model" in cmd
        model_index = cmd.index("--model")
        assert cmd[model_index + 1] == "gpt-5.4"
        assert '-c' in cmd
        config_index = cmd.index("-c")
        assert cmd[config_index + 1] == 'model_reasoning_effort="xhigh"'

    @pytest.mark.parametrize("reasoning_effort", ["max", "ultra"])
    def test_codex_new_reasoning_efforts_are_valid_and_forwarded(self, reasoning_effort: str):
        assert reasoning_effort in get_params_schema("codex")["reasoning_effort"]["enum"]
        assert coerce_param_value("codex", "reasoning_effort", reasoning_effort) == reasoning_effort
        params_config = CliParamsConfig()
        params_config.codex["reasoning_effort"] = reasoning_effort

        cmd, _ = build_cli_command(
            cli_type="codex",
            resolved_cli="codex",
            user_text="hello",
            env={},
            params_config=params_config,
        )

        assert f'model_reasoning_effort="{reasoning_effort}"' in cmd

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

    def test_with_global_extra_args_copies_and_appends_by_type(self):
        params_config = CliParamsConfig()
        params_config.codex["extra_args"] = ["--bot-codex"]
        params_config.claude["extra_args"] = ["--bot-claude"]

        merged = with_global_extra_args(
            params_config,
            {
                "codex": ["--global-codex"],
                "claude": ["--global-claude"],
            },
        )

        assert params_config.codex["extra_args"] == ["--bot-codex"]
        assert params_config.claude["extra_args"] == ["--bot-claude"]
        assert merged.codex["extra_args"] == ["--bot-codex", "--global-codex"]
        assert merged.claude["extra_args"] == ["--bot-claude", "--global-claude"]

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


class TestParseCodexJsonOutput:
    """测试 parse_codex_json_output"""

    def test_response_item_and_event_msg_output(self):
        text, thread_id = parse_codex_json_output(
            "\n".join(
                [
                    '{"type":"thread.started","thread_id":"thread-1"}',
                    '{"type":"response_item","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"我先检查目录结构。"}]}}',
                    '{"type":"event_msg","payload":{"type":"agent_message","message":"目录已读取完成。"}}',
                ]
            )
        )

        assert text == "目录已读取完成。"
        assert thread_id == "thread-1"

class TestParseClaudeStreamJsonOutput:
    """测试 Claude stream-json 完整输出解析"""

    def test_prefers_result_text(self):
        text, session_id = parse_claude_stream_json_output(
            "\n".join(
                [
                    '{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}}',
                    '{"type":"result","subtype":"success","session_id":"sess-1","result":"Hi there"}',
                ]
            )
        )

        assert text == "Hi there"
        assert session_id == "sess-1"


class TestIncrementalCliParsers:
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

    def test_claude_parser_prefers_result_and_keeps_error_tail_bounded(self):
        parser = ClaudeJsonStreamParser(raw_tail_max_bytes=80, final_text_max_bytes=1024)

        parser.consume_line(
            '{"type":"stream_event","session_id":"sess-9","event":{"type":"content_block_delta",'
            '"delta":{"type":"text_delta","text":"partial"}}}\n'
        )
        for index in range(20):
            parser.consume_line(f'plain stderr {index}\n')
        parser.consume_line(
            '{"type":"result","subtype":"success","session_id":"sess-9","result":"complete"}\n'
        )

        result = parser.result()

        assert result.final_text == "complete"
        assert result.session_id == "sess-9"
        assert len(result.raw_tail.encode("utf-8")) <= 80

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
