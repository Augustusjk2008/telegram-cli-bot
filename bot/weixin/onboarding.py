"""Administrator QR-login flow for Tencent iLink personal Weixin bots."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from bot import config
from bot.web.env_service import EnvConfigService

from .client import ILINK_BASE_URL, WeixinClient, WeixinError

logger = logging.getLogger(__name__)


class WeixinOnboardingError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 409) -> None:
        self.code = str(code)
        self.message = str(message)
        self.status = int(status)
        super().__init__(self.message)


def _mask_account_id(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 8:
        return text
    return f"{text[:4]}…{text[-4:]}"


def _qr_data_url(content: str) -> str:
    value = str(content or "").strip()
    if not value:
        return ""
    try:
        import qrcode

        image = qrcode.make(value)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        return ""


class WeixinOnboardingService:
    def __init__(
        self,
        *,
        env_service: EnvConfigService | None = None,
        repo_root: Path | str | None = None,
        client_factory: Callable[..., Any] | None = None,
        now: Callable[[], float] | None = None,
        poll_interval: float = 1.5,
        setup_ttl_seconds: float = 300.0,
    ) -> None:
        self.env_service = env_service or EnvConfigService(repo_root or Path.cwd())
        self.client_factory = client_factory or WeixinClient
        self.now = now or time.time
        self.poll_interval = max(0.01, float(poll_interval))
        self.setup_ttl_seconds = max(1.0, float(setup_ttl_seconds))
        self._record: dict[str, Any] | None = None
        self._client: Any | None = None
        self._poll_task: asyncio.Task[Any] | None = None

    def _new_client(self) -> Any:
        try:
            return self.client_factory(base_url=ILINK_BASE_URL)
        except TypeError:
            try:
                return self.client_factory("")
            except TypeError:
                return self.client_factory()

    def _snapshot(self, record: dict[str, Any] | None = None) -> dict[str, Any]:
        item = record or self._record or {}
        status = str(item.get("status") or "idle")
        qr_content = str(item.get("qr_code_content") or "")
        result = {
            "setup_id": str(item.get("setup_id") or ""),
            "status": status,
            "account_id": _mask_account_id(str(item.get("account_id") or "")),
            "enabled": bool(item.get("enabled")) or bool(getattr(config, "WEIXIN_ENABLED", False)),
            "configured": bool(item.get("configured")) or bool(getattr(config, "WEIXIN_ACCOUNT_ID", "") and getattr(config, "WEIXIN_TOKEN", "")),
            "needs_restart": bool(item.get("needs_restart")),
            "expires_at": float(item.get("expires_at") or 0),
            "error_code": str(item.get("error_code") or ""),
            "error_message": str(item.get("error_message") or ""),
        }
        if status in {"waiting_scan", "scanned"}:
            result.update({
                "qr_code_url": qr_content,
                "qr_code_content": qr_content,
                "qr_code_image": str(item.get("qr_code_image") or _qr_data_url(qr_content)),
            })
        return result

    async def start_setup(self) -> dict[str, Any]:
        if self._record is not None and str(self._record.get("status")) in {"waiting_scan", "scanned"}:
            raise WeixinOnboardingError("weixin_setup_active", "已有一个微信扫码任务正在进行中。")
        client = self._new_client()
        try:
            qr = await client.get_bot_qrcode()
        except WeixinError as exc:
            await self._close_client(client)
            raise WeixinOnboardingError("weixin_setup_qr_failed", "获取微信二维码失败。", status=502) from exc
        if not isinstance(qr, dict) or not str(qr.get("qrcode") or "").strip():
            await self._close_client(client)
            raise WeixinOnboardingError("weixin_setup_qr_invalid", "iLink 返回的二维码无效。", status=502)
        setup_id = uuid.uuid4().hex
        self._client = client
        self._record = {
            "setup_id": setup_id,
            "status": "waiting_scan",
            "qrcode": str(qr.get("qrcode") or "").strip(),
            "qr_code_content": str(qr.get("qrcode_img_content") or qr.get("qr_code_url") or "").strip(),
            "qr_code_image": _qr_data_url(str(qr.get("qrcode_img_content") or qr.get("qr_code_url") or "")),
            "expires_at": self.now() + self.setup_ttl_seconds,
            "account_id": "",
            "needs_restart": False,
            "error_code": "",
            "error_message": "",
        }
        self._poll_task = asyncio.create_task(self._poll_setup(setup_id), name=f"weixin-setup-{setup_id}")
        return self._snapshot()

    async def _poll_setup(self, setup_id: str) -> None:
        try:
            while self._record and self._record.get("setup_id") == setup_id:
                if str(self._record.get("status")) not in {"waiting_scan", "scanned"}:
                    return
                if self.now() >= float(self._record.get("expires_at") or 0):
                    self._record["status"] = "expired"
                    self._record["error_code"] = "weixin_setup_expired"
                    await self._close_client(self._client)
                    self._client = None
                    return
                try:
                    result = await self._client.get_qrcode_status(str(self._record.get("qrcode") or ""))
                except asyncio.CancelledError:
                    raise
                except WeixinError:
                    self._record["status"] = "failed"
                    self._record["error_code"] = "weixin_setup_status_failed"
                    self._record["error_message"] = "查询微信扫码状态失败。"
                    await self._close_client(self._client)
                    self._client = None
                    return
                status = str(result.get("status") or "").strip().lower() if isinstance(result, dict) else ""
                if status in {"scaned", "scanned"}:
                    self._record["status"] = "scanned"
                elif status == "confirmed":
                    await self._confirm(result)
                    return
                elif status in {"expired", "timeout"}:
                    self._record["status"] = "expired"
                    self._record["error_code"] = "weixin_setup_expired"
                    await self._close_client(self._client)
                    self._client = None
                    return
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("微信扫码任务失败", exc_info=True)
            if self._record and self._record.get("setup_id") == setup_id:
                self._record["status"] = "failed"
                self._record["error_code"] = "weixin_setup_failed"
                self._record["error_message"] = "微信扫码任务失败。"
                await self._close_client(self._client)
                self._client = None

    async def _confirm(self, result: dict[str, Any]) -> None:
        token = str(result.get("bot_token") or result.get("token") or "").strip()
        account_id = str(result.get("ilink_bot_id") or result.get("account_id") or "").strip()
        user_id = str(result.get("ilink_user_id") or result.get("user_id") or "").strip()
        base_url = str(result.get("baseurl") or result.get("base_url") or ILINK_BASE_URL).strip() or ILINK_BASE_URL
        if not token or not account_id:
            self._record["status"] = "failed"
            self._record["error_code"] = "weixin_setup_missing_credentials"
            self._record["error_message"] = "iLink 未返回完整登录凭据。"
            return
        try:
            values: dict[str, Any] = {
                "WEIXIN_ENABLED": True,
                "WEIXIN_ACCOUNT_ID": account_id,
                "WEIXIN_TOKEN": token,
                "WEIXIN_BASE_URL": base_url,
            }
            existing_allowed_ids = getattr(config, "WEIXIN_ALLOWED_USER_IDS", set()) or set()
            if user_id and not existing_allowed_ids:
                values["WEIXIN_ALLOWED_USER_IDS"] = [user_id]
            self.env_service.patch({"values": values})
        except Exception as exc:
            self._record["status"] = "failed"
            self._record["error_code"] = "weixin_setup_save_failed"
            self._record["error_message"] = "微信登录成功，但配置保存失败。"
            logger.warning("微信扫码配置保存失败 (%s)", type(exc).__name__)
            return
        self._record["status"] = "confirmed"
        self._record["account_id"] = account_id
        self._record["enabled"] = True
        self._record["configured"] = True
        self._record["needs_restart"] = True
        await self._close_client(self._client)
        self._client = None

    async def get_setup(self, setup_id: str) -> dict[str, Any]:
        if not self._record or str(self._record.get("setup_id")) != str(setup_id or ""):
            raise WeixinOnboardingError("weixin_setup_not_found", "微信扫码任务不存在。", status=404)
        if str(self._record.get("status")) in {"waiting_scan", "scanned"} and self.now() >= float(self._record.get("expires_at") or 0):
            self._record["status"] = "expired"
            self._record["error_code"] = "weixin_setup_expired"
        return self._snapshot()

    async def cancel_setup(self, setup_id: str) -> dict[str, Any]:
        if not self._record or str(self._record.get("setup_id")) != str(setup_id or ""):
            raise WeixinOnboardingError("weixin_setup_not_found", "微信扫码任务不存在。", status=404)
        if str(self._record.get("status")) not in {"waiting_scan", "scanned"}:
            raise WeixinOnboardingError("weixin_setup_not_active", "微信扫码任务已结束。", status=409)
        self._record["status"] = "cancelled"
        self._record["error_code"] = "weixin_setup_cancelled"
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
        self._poll_task = None
        await self._close_client(self._client)
        self._client = None
        return self._snapshot()

    def status(self) -> dict[str, Any]:
        gateway_status = "disabled"
        if getattr(config, "WEIXIN_ENABLED", False):
            gateway_status = "configured" if getattr(config, "WEIXIN_ACCOUNT_ID", "") and getattr(config, "WEIXIN_TOKEN", "") else "needs_configuration"
            try:
                from .gateway import get_active_weixin_gateway

                gateway = get_active_weixin_gateway(str(getattr(config, "WEIXIN_ACCOUNT_ID", "") or ""))
                if gateway is not None:
                    gateway_status = gateway.state.gateway_status().get("status") or gateway_status
            except Exception:
                pass
        return {
            "enabled": bool(getattr(config, "WEIXIN_ENABLED", False)),
            "configured": bool(getattr(config, "WEIXIN_ACCOUNT_ID", "") and getattr(config, "WEIXIN_TOKEN", "")),
            "account_id": _mask_account_id(str(getattr(config, "WEIXIN_ACCOUNT_ID", "") or "")),
            "allowed_user_count": len(getattr(config, "WEIXIN_ALLOWED_USER_IDS", set()) or set()),
            "connection_status": gateway_status,
            "setup": self._snapshot() if self._record else None,
        }

    async def close(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
        self._poll_task = None
        await self._close_client(self._client)
        self._client = None

    @staticmethod
    async def _close_client(client: Any | None) -> None:
        if client is None:
            return
        close = getattr(client, "close", None)
        if callable(close):
            value = close()
            if asyncio.iscoroutine(value):
                await value


__all__ = ["WeixinOnboardingError", "WeixinOnboardingService"]
