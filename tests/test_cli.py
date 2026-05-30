"""
CLI 模块测试

直接导入 bot.cli 中的真实函数进行测试
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.cli import (
    _build_codex_status_terminal_argv,
    _should_finish_codex_status_poll,
    build_cli_command,
    extract_codex_status,
    normalize_cli_type,
    parse_claude_stream_json_line,
    parse_claude_stream_json_output,
    parse_codex_json_line,
    parse_codex_json_output,
    parse_kimi_stream_json_line,
    parse_kimi_stream_json_output,
    read_codex_status_from_terminal,
    resolve_cli_executable,
    should_mark_claude_session_initialized,
    should_reset_claude_session,
    should_reset_codex_session,
    validate_cli_type,
)
from bot.cli_params import CliParamsConfig, normalize_cli_model_options, with_global_extra_args

class TestValidateCliType:
    """测试 validate_cli_type"""

    def test_valid_types(self):
        assert validate_cli_type("claude") == "claude"
        assert validate_cli_type("codex") == "codex"
        assert validate_cli_type("kimi") == "kimi"

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
        assert cmd[permission_mode_index + 1] == "bypassPermissions"
        assert cmd.count("--permission-mode") == 1

    def test_codex_defaults_include_model_yolo_and_reasoning_effort(self):
        env = {}
        cmd, use_stdin = build_cli_command(
            cli_type="codex",
            resolved_cli="codex",
            user_text="hello",
            env=env,
            params_config=CliParamsConfig(),
        )
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert "--model" in cmd
        model_index = cmd.index("--model")
        assert cmd[model_index + 1] == "gpt-5.4"
        assert '-c' in cmd
        config_index = cmd.index("-c")
        assert cmd[config_index + 1] == 'model_reasoning_effort="xhigh"'

    def test_kimi_command_uses_print_stream_json_stdin_and_session(self, temp_dir: Path):
        env = {}
        params_config = CliParamsConfig()

        cmd, use_stdin = build_cli_command(
            cli_type="kimi",
            resolved_cli="kimi",
            user_text="hello",
            env=env,
            params_config=params_config,
            session_id="kimi-session-1",
            resume_session=True,
            working_dir=str(temp_dir),
        )

        assert cmd[:1] == ["kimi"]
        assert "--print" in cmd
        assert "--output-format" in cmd
        assert cmd[cmd.index("--output-format") + 1] == "stream-json"
        assert "--session" in cmd
        assert cmd[cmd.index("--session") + 1] == "kimi-session-1"
        assert "--work-dir" in cmd
        assert cmd[cmd.index("--work-dir") + 1] == str(temp_dir)
        assert use_stdin is True

    def test_with_global_extra_args_copies_and_appends_by_type(self):
        params_config = CliParamsConfig()
        params_config.codex["extra_args"] = ["--bot-codex"]
        params_config.claude["extra_args"] = ["--bot-claude"]
        params_config.kimi["extra_args"] = ["--bot-kimi"]

        merged = with_global_extra_args(
            params_config,
            {
                "codex": ["--global-codex"],
                "claude": ["--global-claude"],
                "kimi": ["--global-kimi"],
            },
        )

        assert params_config.codex["extra_args"] == ["--bot-codex"]
        assert params_config.claude["extra_args"] == ["--bot-claude"]
        assert params_config.kimi["extra_args"] == ["--bot-kimi"]
        assert merged.codex["extra_args"] == ["--bot-codex", "--global-codex"]
        assert merged.claude["extra_args"] == ["--bot-claude", "--global-claude"]
        assert merged.kimi["extra_args"] == ["--bot-kimi", "--global-kimi"]


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

class TestParseKimiStreamJson:
    """测试 Kimi stream-json 输出解析"""

    def test_extracts_last_assistant_text(self):
        raw = "\n".join([
            '{"role":"assistant","content":"我先看目录。","tool_calls":[{"type":"function","id":"tc_1","function":{"name":"Shell","arguments":"{\\"command\\":\\"Get-ChildItem\\"}"}}]}',
            '{"role":"tool","tool_call_id":"tc_1","content":"README.md\\nbot"}',
            '{"role":"assistant","content":[{"type":"think","think":"略"},{"type":"text","text":"目录里有 README.md 和 bot。"}]}',
        ])

        text = parse_kimi_stream_json_output(raw)

        assert text == "目录里有 README.md 和 bot。"

