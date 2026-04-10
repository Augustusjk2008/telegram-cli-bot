"""TunnelService 重启续用行为测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.web.tunnel_service import TunnelService


@pytest.mark.asyncio
async def test_tunnel_service_reuses_persisted_quick_tunnel_without_starting_new_process(tmp_path: Path):
    state_file = tmp_path / "web-tunnel-state.json"
    state_file.write_text(
        json.dumps(
            {
                "mode": "cloudflare_quick",
                "source": "quick_tunnel",
                "public_url": "https://stable.trycloudflare.com",
                "local_url": "http://127.0.0.1:8765",
                "pid": 4321,
            }
        ),
        encoding="utf-8",
    )

    service = TunnelService(
        host="127.0.0.1",
        port=8765,
        mode="cloudflare_quick",
        state_file=str(state_file),
    )

    with patch.object(service, "_is_cloudflared_process", return_value=True), \
         patch("bot.web.tunnel_service.subprocess.Popen", side_effect=AssertionError("should not spawn cloudflared")):
        snapshot = await service.start()

    assert snapshot["status"] == "running"
    assert snapshot["source"] == "quick_tunnel"
    assert snapshot["public_url"] == "https://stable.trycloudflare.com"
    assert snapshot["pid"] == 4321
