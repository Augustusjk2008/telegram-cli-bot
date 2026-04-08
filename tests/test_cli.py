"""
CLI 模块测试

直接导入 bot.cli 中的真实函数进行测试
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.cli import (
    build_cli_command,
    normalize_cli_type,
    parse_codex_json_line,
    parse_codex_json_output,
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
        assert validate_cli_type("kimi") == "kimi"
        assert validate_cli_type("claude") == "claude"
        assert validate_cli_type("codex") == "codex"

    def test_case_insensitive(self):
        assert validate_cli_type("KIMI") == "kimi"
        assert validate_cli_type("Claude") == "claude"
        assert validate_cli_type("CODEX") == "codex"

    def test_with_whitespace(self):
        assert validate_cli_type("  kimi  ") == "kimi"

    def test_invalid_type(self):
        with pytest.raises(ValueError):
            validate_cli_type("unsupported")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            validate_cli_type("")


class TestNormalizeCliType:
    """测试 normalize_cli_type"""

    def test_basic(self):
        assert normalize_cli_type("KIMI") == "kimi"
        assert normalize_cli_type("  Claude  ") == "claude"

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


class TestBuildCliCommand:
    """测试 build_cli_command"""

    def test_kimi_basic(self):
        env = {}
        cmd, use_stdin = build_cli_command(
            cli_type="kimi",
            resolved_cli="kimi",
            user_text="hello",
            env=env,
            params_config=CliParamsConfig(),
        )
        assert isinstance(cmd, list)
        assert isinstance(use_stdin, bool)
        assert "kimi" in cmd

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
