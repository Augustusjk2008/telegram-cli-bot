from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.web.api_common import AuthContext, WebApiError
from bot.web.auth_store import CAP_RUN_PLUGINS
from bot.web.plugin_api_service import install_plugin_runtime


def _manager(plugin_service=None):
    return SimpleNamespace(
        main_profile=SimpleNamespace(alias="main", working_dir="."),
        managed_profiles={},
        plugin_service=plugin_service,
    )


@pytest.mark.asyncio
async def test_runtime_install_requires_run_plugins_capability() -> None:
    auth = AuthContext(user_id=1, token_used=True, capabilities=set())

    with pytest.raises(WebApiError) as caught:
        await install_plugin_runtime(_manager(), "main", auth, "mermaid-visio", {})

    assert caught.value.status == 403


@pytest.mark.asyncio
async def test_runtime_install_rejects_plugin_supplied_parameters() -> None:
    auth = AuthContext(user_id=1, token_used=True, capabilities={CAP_RUN_PLUGINS})

    with pytest.raises(WebApiError) as caught:
        await install_plugin_runtime(
            _manager(),
            "main",
            auth,
            "mermaid-visio",
            {"runtimeId": "arbitrary", "path": "C:/outside"},
        )

    assert caught.value.code == "runtime_install_payload_forbidden"


@pytest.mark.asyncio
async def test_runtime_install_rejects_arbitrary_plugin_runtime() -> None:
    auth = AuthContext(user_id=1, token_used=True, capabilities={CAP_RUN_PLUGINS})

    with pytest.raises(WebApiError) as caught:
        await install_plugin_runtime(_manager(), "main", auth, "other-plugin", {})

    assert caught.value.code == "unsupported_plugin_runtime"
