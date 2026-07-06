import json
from pathlib import Path

import pytest

from bot.web.inline_completion_config import (
    InlineCompletionConfigError,
    InlineCompletionConfigStore,
)


def test_inline_completion_config_masks_and_preserves_api_key(tmp_path: Path) -> None:
    store = InlineCompletionConfigStore(tmp_path / "inline.json")

    status = store.update(
        {
            "enabled": True,
            "base_url": "https://provider.test/v1",
            "api_key": "sk-secret",
            "model": "coder",
        }
    )

    assert status["api_key_set"] is True
    assert "api_key" not in status
    assert json.loads((tmp_path / "inline.json").read_text(encoding="utf-8"))["api_key"] == "sk-secret"

    status = store.update({"api_key": "", "model": "coder-lite"})

    assert status["api_key_set"] is True
    assert store.config.api_key == "sk-secret"
    assert store.config.model == "coder-lite"

    status = store.update({"clear_api_key": True})

    assert status["api_key_set"] is False
    assert store.config.api_key == ""


def test_inline_completion_config_rejects_invalid_base_url(tmp_path: Path) -> None:
    store = InlineCompletionConfigStore(tmp_path / "inline.json")

    with pytest.raises(InlineCompletionConfigError) as exc_info:
        store.update({"base_url": "file:///tmp/provider"})

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_inline_completion_base_url"
