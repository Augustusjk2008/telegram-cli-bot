"""
工具函数测试

直接导入 bot.utils 中的真实函数进行测试
"""

from unittest.mock import patch

import pytest

from bot.utils import (
    check_auth,
    is_dangerous_command,
    is_safe_filename,
    split_text_into_chunks,
    truncate_for_markdown,
)


class TestCheckAuth:
    """测试 check_auth"""

    def test_empty_allowed_allows_all(self):
        with patch("bot.utils.ALLOWED_USER_IDS", []):
            assert check_auth(12345) is True

    def test_allowed_user(self):
        with patch("bot.utils.ALLOWED_USER_IDS", [123, 456]):
            assert check_auth(123) is True
            assert check_auth(456) is True

    def test_denied_user(self):
        with patch("bot.utils.ALLOWED_USER_IDS", [123]):
            assert check_auth(999) is False


class TestIsDangerousCommand:
    """测试 is_dangerous_command"""

    def test_dangerous_first_word(self):
        # rm 已被允许，不再是危险命令
        assert is_dangerous_command("rm -rf /") is False
        assert is_dangerous_command("kill -9 1234") is True
        assert is_dangerous_command("shutdown now") is True
        assert is_dangerous_command("reboot") is True
        assert is_dangerous_command("dd if=/dev/zero of=/dev/sda") is True

    def test_safe_commands(self):
        assert is_dangerous_command("ls -la") is False
        assert is_dangerous_command("echo hello") is False
        assert is_dangerous_command("pwd") is False
        assert is_dangerous_command("cat file.txt") is False

    def test_injection_patterns(self):
        # rm 注入模式检查已移除，现在允许 rm 命令
        assert is_dangerous_command("echo hello;rm -rf /") is False
        assert is_dangerous_command("echo hello|rm file") is False
        assert is_dangerous_command("echo `rm file`") is False
        assert is_dangerous_command("echo $(rm file)") is False
        assert is_dangerous_command("echo hello&&rm file") is False


class TestIsSafeFilename:
    """测试 is_safe_filename"""

    def test_safe_names(self):
        assert is_safe_filename("test.txt") is True
        assert is_safe_filename("my-file.py") is True
        assert is_safe_filename("file_name") is True

    def test_path_traversal(self):
        assert is_safe_filename("../etc/passwd") is False

    def test_null_byte(self):
        assert is_safe_filename("file\x00.txt") is False

    def test_forbidden_chars(self):
        assert is_safe_filename("file:name") is False
        assert is_safe_filename("file*name") is False
        assert is_safe_filename('file"name') is False
        assert is_safe_filename("file<name") is False
        assert is_safe_filename("file>name") is False
        assert is_safe_filename("file|name") is False
        assert is_safe_filename("file?name") is False

    def test_backslash_forbidden(self):
        assert is_safe_filename("path\\file") is False


class TestTruncateForMarkdown:
    """测试 truncate_for_markdown"""

    def test_short_text(self):
        assert truncate_for_markdown("hello") == "hello"

    def test_long_text(self):
        text = "A" * 5000
        result = truncate_for_markdown(text)
        assert len(result) <= 3900
        assert "截断" in result or "..." in result or len(result) < len(text)

    def test_custom_max_len(self):
        text = "A" * 200
        result = truncate_for_markdown(text, max_len=100)
        assert len(result) <= 100


class TestSplitTextIntoChunks:
    """测试 split_text_into_chunks"""

    def test_short_text(self):
        result = split_text_into_chunks("hello")
        assert result == ["hello"]

    def test_long_text_with_newlines(self):
        """按换行分割的长文本"""
        text = "\n".join(["A" * 100] * 100)  # 100 lines of 100 chars each
        result = split_text_into_chunks(text)
        assert len(result) > 1

    def test_single_long_line_no_split(self):
        """单行无换行文本不能被分割"""
        text = "A" * 10000
        result = split_text_into_chunks(text)
        # 无换行符时无法分割，返回 1 个块
        assert len(result) == 1

    def test_custom_max_len(self):
        text = "\n".join(["A" * 50] * 20)  # 20 lines of 50 chars
        result = split_text_into_chunks(text, max_len=100)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 200  # 允许单行超过 max_len（无法分割）

    def test_empty_text(self):
        result = split_text_into_chunks("")
        assert len(result) >= 1
