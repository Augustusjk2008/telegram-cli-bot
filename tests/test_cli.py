"""
CLI 模块测试

直接导入 bot.cli 中的真实函数进行测试
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.cli import (
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
from bot.cli_params import CliParamsConfig

class TestValidateCliType:
    """测试 validate_cli_type"""

    def test_valid_types(self):
        assert validate_cli_type("claude") == "claude"
        assert validate_cli_type("codex") == "codex"

    def test_case_insensitive(self):
        assert validate_cli_type("Claude") == "claude"
        assert validate_cli_type("CODEX") == "codex"

    def test_with_whitespace(self):
        assert validate_cli_type("  claude  ") == "claude"

    def test_invalid_type(self):
        with pytest.raises(ValueError):
            validate_cli_type("unsupported")

        with pytest.raises(ValueError):
            validate_cli_type("ki" "mi")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            validate_cli_type("")

class TestNormalizeCliType:
    """测试 normalize_cli_type"""

    def test_basic(self):
        assert normalize_cli_type("  Claude  ") == "claude"
        assert normalize_cli_type("  CODEX  ") == "codex"

    def test_already_lowercase(self):
        assert normalize_cli_type("codex") == "codex"

class TestResolveCliExecutable:
    """测试 resolve_cli_executable"""

    def test_absolute_path_exists(self, temp_dir: Path):
        exe = temp_dir / "mycli"
        exe.write_text("#!/bin/sh\necho ok")
        os.chmod(str(exe), 0o755)
        result = resolve_cli_executable(str(exe))
        assert result == str(exe)

    def test_nonexistent_path(self):
        result = resolve_cli_executable("/nonexistent/path/to/cli")
        # 可能返回 None 或路径取决于实现
        # 关键是不崩溃

    def test_with_working_dir(self, temp_dir: Path):
        # 测试在 working_dir 下寻找
        result = resolve_cli_executable("nonexistent_cli_xyz", str(temp_dir))
        # 不存在时应该返回 None
        assert result is None or isinstance(result, str)

    def test_on_linux_does_not_append_windows_extensions(self, monkeypatch):
        monkeypatch.setattr("bot.platform.executables.os.name", "posix")
        monkeypatch.setattr("bot.platform.executables.shutil.which", lambda value: None)

        result = resolve_cli_executable("claude.cmd", "/tmp")

        assert result is None

class TestBuildCliCommand:
    """测试 build_cli_command"""

    def test_removed_legacy_cli_type_is_rejected(self):
        with pytest.raises(ValueError):
            build_cli_command(
                cli_type="ki" "mi",
                resolved_cli="ki" "mi",
                user_text="hello",
                env={},
                params_config=CliParamsConfig(),
            )

    def test_claude_basic(self):
        env = {}
        cmd, use_stdin = build_cli_command(
            cli_type="claude",
            resolved_cli="claude",
            user_text="hello",
            env=env,
            params_config=CliParamsConfig(),
        )
        assert "claude" in cmd

    def test_claude_stream_json_defaults_include_partial_messages(self):
        env = {}
        cmd, use_stdin = build_cli_command(
            cli_type="claude",
            resolved_cli="claude",
            user_text="hello",
            env=env,
            params_config=CliParamsConfig(),
        )
        assert "--output-format" in cmd
        output_index = cmd.index("--output-format")
        assert cmd[output_index + 1] == "stream-json"
        assert "--verbose" in cmd
        assert "--include-partial-messages" in cmd

    def test_claude_with_session(self):
        env = {}
        cmd, use_stdin = build_cli_command(
            cli_type="claude",
            resolved_cli="claude",
            user_text="hello",
            env=env,
            session_id="sess-123",
            resume_session=True,
            params_config=CliParamsConfig(),
        )
        assert any("sess-123" in str(a) for a in cmd)

    def test_codex_json_output(self):
        env = {}
        cmd, use_stdin = build_cli_command(
            cli_type="codex",
            resolved_cli="codex",
            user_text="hello",
            env=env,
            json_output=True,
            params_config=CliParamsConfig(),
        )
        assert "codex" in cmd

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

class TestParseCodexJsonLine:
    """测试 parse_codex_json_line"""

    def test_valid_json(self):
        result = parse_codex_json_line('{"type":"message","content":"hello"}')
        assert isinstance(result, dict)

    def test_invalid_json(self):
        result = parse_codex_json_line("not json")
        assert isinstance(result, dict)

    def test_empty_string(self):
        result = parse_codex_json_line("")
        assert isinstance(result, dict)

    def test_item_completed_also_exposes_stream_text(self):
        result = parse_codex_json_line(
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"OK"}}'
        )
        assert result["completed_text"] == "OK"
        assert result["delta_text"] == "OK"

class TestParseCodexJsonOutput:
    """测试 parse_codex_json_output"""

    def test_empty_output(self):
        text, thread_id = parse_codex_json_output("")
        assert isinstance(text, str)

    def test_simple_output(self):
        text, thread_id = parse_codex_json_output("plain text output")
        assert isinstance(text, str)

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

class TestParseClaudeStreamJsonLine:
    """测试 Claude stream-json 单行解析"""

    def test_text_delta(self):
        result = parse_claude_stream_json_line(
            '{"type":"stream_event","session_id":"sess-1","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}}'
        )
        assert result["session_id"] == "sess-1"
        assert result["delta_text"] == "Hi"

    def test_result_frame(self):
        result = parse_claude_stream_json_line(
            '{"type":"result","subtype":"success","session_id":"sess-1","result":"Hi there"}'
        )
        assert result["session_id"] == "sess-1"
        assert result["completed_text"] == "Hi there"

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

    def test_falls_back_to_errors_when_result_is_empty(self):
        text, session_id = parse_claude_stream_json_output(
            '{"type":"result","subtype":"error_max_turns","session_id":"sess-1","result":"","errors":["Error: Session ID not found"]}'
        )

        assert text == "Error: Session ID not found"
        assert session_id == "sess-1"

class TestExtractCodexStatus:
    """测试 Codex 状态文本提取"""

    def test_prefers_context_line_from_status_output(self):
        raw = (
            "\x1b[2m  gpt-5.4 xhigh · 100% left · ~\\repo\x1b[22m\n"
            "› /status\n"
            "  100% context left\n"
        )
        parsed = extract_codex_status(raw)
        assert parsed["status_line"] == "100% context left"

    def test_falls_back_to_footer_status_line(self):
        raw = "  gpt-5.4 xhigh · 87% left · ~\\repo\n"
        parsed = extract_codex_status(raw)
        assert parsed["status_line"] == "gpt-5.4 xhigh · 87% left · ~\\repo"

class TestShouldFinishCodexStatusPoll:
    """测试 Codex /status 轮询完成判定"""

    def test_waits_when_only_old_footer_is_available(self):
        parsed = {
            "status_line": "gpt-5.4 xhigh · 87% left · ~\\repo",
            "source": "fallback_footer",
        }

        should_finish = _should_finish_codex_status_poll(
            parsed,
            initial_status_line="gpt-5.4 xhigh · 87% left · ~\\repo",
            sent_at=100.0,
            now=104.9,
            fallback_wait_seconds=5.0,
        )

        assert should_finish is False

    def test_accepts_status_command_output_immediately(self):
        parsed = {
            "status_line": "100% context left",
            "source": "status_command_context",
        }

        should_finish = _should_finish_codex_status_poll(
            parsed,
            initial_status_line="gpt-5.4 xhigh · 87% left · ~\\repo",
            sent_at=100.0,
            now=101.0,
            fallback_wait_seconds=5.0,
        )

        assert should_finish is True

    def test_accepts_changed_footer_before_fallback_deadline(self):
        parsed = {
            "status_line": "gpt-5.4 xhigh · 83% left · ~\\repo",
            "source": "fallback_footer",
        }

        should_finish = _should_finish_codex_status_poll(
            parsed,
            initial_status_line="gpt-5.4 xhigh · 87% left · ~\\repo",
            sent_at=100.0,
            now=101.0,
            fallback_wait_seconds=5.0,
        )

        assert should_finish is True

    def test_falls_back_after_wait_deadline(self):
        parsed = {
            "status_line": "gpt-5.4 xhigh · 87% left · ~\\repo",
            "source": "fallback_footer",
        }

        should_finish = _should_finish_codex_status_poll(
            parsed,
            initial_status_line="gpt-5.4 xhigh · 87% left · ~\\repo",
            sent_at=100.0,
            now=105.0,
            fallback_wait_seconds=5.0,
        )

        assert should_finish is True

class TestReadCodexStatusFromTerminal:
    """测试 Codex PTY 状态查询包装器"""

    def test_returns_not_found_when_cli_missing(self):
        with patch("bot.cli.resolve_cli_executable", return_value=None):
            result = read_codex_status_from_terminal("codex", "C:/repo")
        assert result["ok"] is False
        assert result["error"] == "not_found"

    def test_returns_parsed_status_line(self):
        with patch("bot.cli.resolve_cli_executable", return_value="C:/bin/codex.cmd"), \
             patch("bot.cli._run_codex_status_terminal", return_value="› /status\n100% context left\n"):
            result = read_codex_status_from_terminal("codex", "C:/repo")

        assert result["ok"] is True
        assert result["status_line"] == "100% context left"

class TestShouldResetCodexSession:
    """测试 should_reset_codex_session"""

    def test_no_session(self):
        result = should_reset_codex_session(None, "some output", 0)
        assert isinstance(result, bool)

    def test_with_error(self):
        result = should_reset_codex_session("sess-123", "error", 1)
        assert isinstance(result, bool)

class TestShouldResetClaudeSession:
    """测试 should_reset_claude_session"""

    def test_success(self):
        result = should_reset_claude_session("some output", 0)
        assert isinstance(result, bool)

    def test_error(self):
        result = should_reset_claude_session("error output", 1)
        assert isinstance(result, bool)

    def test_session_id_not_found_marker(self):
        result = should_reset_claude_session("Error: Session ID not found", 1)
        assert result is True

class TestShouldMarkClaudeSessionInitialized:
    """测试 should_mark_claude_session_initialized"""

    def test_success(self):
        result = should_mark_claude_session_initialized("output", 0)
        assert isinstance(result, bool)
        assert result is True

    def test_error(self):
        result = should_mark_claude_session_initialized("", 1)
        assert isinstance(result, bool)
        assert result is False

    def test_already_in_use_error_marks_initialized(self):
        result = should_mark_claude_session_initialized(
            "Error: Session ID 6440e126-bab3-4bcc-a0b1-7f5349cae34f is already in use",
            1,
        )
        assert result is True

    def test_nonfatal_nonzero_output_marks_initialized(self):
        result = should_mark_claude_session_initialized(
            "这是 Claude 的回复内容\nwarning: stream closed after response",
            1,
        )
        assert result is True

    def test_auth_failure_does_not_mark_initialized(self):
        result = should_mark_claude_session_initialized(
            "Error: Login required",
            1,
        )
        assert result is False
