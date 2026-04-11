"""多Bot生命周期管理器"""

import asyncio
import html
import json
import logging
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional

from telegram import Update
from telegram.error import NetworkError, TimedOut

# 捕获底层 httpx 连接错误
try:
    from httpx import ConnectError, ConnectTimeout, RemoteProtocolError
except ImportError:
    ConnectError = None
    ConnectTimeout = None
    RemoteProtocolError = None
from telegram.ext import Application
from telegram.request import HTTPXRequest

from bot.assistant_home import bootstrap_assistant_home
from bot.cli import resolve_cli_executable, validate_cli_type
from bot.cli_params import coerce_param_value
from bot.config import (
    ALLOWED_USER_IDS,
    BOT_ALIAS_RE,
    CLI_PATH,
    CLI_TYPE,
    get_proxy_kwargs,
    MANAGED_BOTS_FILE,
    NETWORK_ERROR_BASE_DELAY,
    NETWORK_ERROR_MAX_DELAY,
    NETWORK_ERROR_MAX_RETRIES,
    NETWORK_ERROR_LOG_SUPPRESS_WINDOW,
    POLLING_BOOTSTRAP_RETRIES,
    POLLING_TIMEOUT,
    POLLING_WATCHDOG_INTERVAL,
    RESERVED_ALIASES,
    WORKING_DIR,
)
from bot.handlers import register_handlers
from bot.models import BotProfile
from bot.platform.paths import truncate_path_for_display
from bot.sessions import clear_bot_sessions, is_bot_processing, update_bot_alias, update_bot_working_dir

logger = logging.getLogger(__name__)


class _ManagerNotificationHandler(logging.Handler):
    """监听 bot.manager 的 warning/error，并交给当前 manager 投递。"""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING or record.name != logger.name:
            return

        manager = MultiBotManager._active_notification_manager
        if manager is None:
            return

        manager._enqueue_manager_alert(record)


class MultiBotManager:
    _notification_handler: Optional[_ManagerNotificationHandler] = None
    _active_notification_manager: Optional["MultiBotManager"] = None

    def __init__(self, main_profile: BotProfile, storage_file: str):
        self.main_profile = main_profile
        self.storage_file = Path(storage_file)
        self.managed_profiles: Dict[str, BotProfile] = {}
        self.applications: Dict[str, Application] = {}
        self.bot_id_to_alias: Dict[int, str] = {}
        self._polling_restart_locks: Dict[str, asyncio.Lock] = {}
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_stop_event: Optional[asyncio.Event] = None
        self._lock = asyncio.Lock()
        # 网络错误日志抑制状态: {alias: (error_type, last_log_time, count)}
        self._network_error_log_state: Dict[str, tuple] = {}
        # 主bot连续网络错误计数（用于触发程序重启）
        self._main_bot_network_error_count = 0
        self._pending_manager_alerts: Deque[dict] = deque()
        self._manager_alert_task: Optional[asyncio.Task] = None
        self._main_bot_alert_retry_delay = 1.0
        self._manager_alerts_enabled = True
        self._manager_alert_lock = asyncio.Lock()
        try:
            self._loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        self._activate_manager_notifications()
        self._load_profiles()

    def _activate_manager_notifications(self) -> None:
        MultiBotManager._active_notification_manager = self
        if MultiBotManager._notification_handler is None:
            handler = _ManagerNotificationHandler()
            handler.setLevel(logging.WARNING)
            logger.addHandler(handler)
            MultiBotManager._notification_handler = handler

    @staticmethod
    def _profile_uses_telegram(profile: BotProfile) -> bool:
        return bool((profile.token or "").strip())

    def _enqueue_manager_alert(self, record: logging.LogRecord) -> None:
        if not self._manager_alerts_enabled or not ALLOWED_USER_IDS:
            return

        payload = {
            "level": record.levelname,
            "created": float(record.created),
            "message": record.getMessage(),
        }

        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue_manager_alert, payload)
        else:
            self._queue_manager_alert(payload)

    def _queue_manager_alert(self, payload: dict) -> None:
        if not self._manager_alerts_enabled:
            return
        self._pending_manager_alerts.append(payload)
        self._ensure_manager_alert_task()

    def _ensure_manager_alert_task(self) -> None:
        if self._loop is None or not self._loop.is_running():
            return
        if self._manager_alert_task is not None and not self._manager_alert_task.done():
            return
        self._manager_alert_task = self._loop.create_task(self._deliver_manager_alerts())

    def _main_bot_is_idle(self) -> bool:
        main_app = self.applications.get(self.main_profile.alias)
        if main_app is None:
            return False

        main_bot_id = main_app.bot_data.get("bot_id")
        if not isinstance(main_bot_id, int):
            return False

        return not is_bot_processing(main_bot_id)

    def _format_manager_alert_text(self, payload: dict) -> str:
        level = str(payload["level"])
        icon = "⚠️" if level == "WARNING" else "🚨"
        timestamp = datetime.fromtimestamp(float(payload["created"])).strftime("%Y-%m-%d %H:%M:%S")
        message = str(payload["message"])
        if len(message) > 3000:
            message = message[:3000] + "\n...(已截断)"

        return (
            f"{icon} <b>后台告警</b>\n"
            f"级别: <code>{html.escape(level)}</code>\n"
            f"时间: <code>{html.escape(timestamp)}</code>\n\n"
            f"<pre>{html.escape(message)}</pre>"
        )

    async def _send_manager_alert(self, payload: dict) -> bool:
        main_app = self.applications.get(self.main_profile.alias)
        if main_app is None:
            return False

        text = self._format_manager_alert_text(payload)
        sent_any = False
        for user_id in ALLOWED_USER_IDS:
            try:
                await main_app.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="HTML",
                )
                sent_any = True
            except Exception as exc:
                logger.debug("发送 manager 告警失败 user_id=%s: %s", user_id, exc)

        return sent_any

    async def _deliver_manager_alerts(self) -> None:
        current_task = asyncio.current_task()
        try:
            async with self._manager_alert_lock:
                while self._pending_manager_alerts and self._manager_alerts_enabled:
                    if not self._main_bot_is_idle():
                        await asyncio.sleep(self._main_bot_alert_retry_delay)
                        continue

                    payload = self._pending_manager_alerts[0]
                    if await self._send_manager_alert(payload):
                        self._pending_manager_alerts.popleft()
                    else:
                        await asyncio.sleep(self._main_bot_alert_retry_delay)
        finally:
            if self._manager_alert_task is current_task:
                self._manager_alert_task = None
            if self._pending_manager_alerts and self._manager_alerts_enabled:
                self._ensure_manager_alert_task()

    async def _stop_manager_alerts(self) -> None:
        self._manager_alerts_enabled = False
        self._pending_manager_alerts.clear()

        task = self._manager_alert_task
        self._manager_alert_task = None
        if task is None:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _make_error_handler(self, alias: str):
        """全局错误处理器，对网络错误静默处理"""
        async def _on_error(update: object, context) -> None:
            error = context.error
            is_network_error = isinstance(error, (NetworkError, TimedOut)) or (
                ConnectError is not None and isinstance(error, (ConnectError, ConnectTimeout, RemoteProtocolError))
            )
            if is_network_error:
                logger.debug("Handler网络错误(已忽略) alias=%s: %s", alias, error)
            else:
                logger.error("Handler异常 alias=%s: %s", alias, error, exc_info=error)
        return _on_error

    def _make_polling_error_callback(self, alias: str):
        """轮询错误回调，带智能日志抑制（适合网络不稳定环境）"""
        def _on_polling_error(error: Exception) -> None:
            # 判断是否为网络错误
            is_network_error = isinstance(error, (NetworkError, TimedOut)) or (
                ConnectError is not None and isinstance(error, (ConnectError, ConnectTimeout))
            ) or (
                RemoteProtocolError is not None and isinstance(error, RemoteProtocolError)
            )
            
            if not is_network_error:
                # 非网络错误直接记录
                logger.warning("轮询异常 alias=%s: %s", alias, error)
                return
            
            # 网络错误：使用智能抑制
            if NETWORK_ERROR_LOG_SUPPRESS_WINDOW <= 0:
                # 禁用抑制，直接记录
                logger.warning("网络错误 alias=%s: %s", alias, error)
                return
            
            now = time.monotonic()
            error_type = type(error).__name__
            state = self._network_error_log_state.get(alias)
            
            if state is None:
                # 首次错误，记录 WARNING 并初始化状态
                logger.warning("网络错误 alias=%s: %s", alias, error)
                self._network_error_log_state[alias] = (error_type, now, 1)
            else:
                last_type, last_time, count = state
                elapsed = now - last_time
                
                if elapsed >= NETWORK_ERROR_LOG_SUPPRESS_WINDOW:
                    # 超过抑制窗口，重置计数并记录 WARNING
                    logger.warning(
                        "网络错误 alias=%s (过去%d秒发生%d次): %s", 
                        alias, int(elapsed), count + 1, error
                    )
                    self._network_error_log_state[alias] = (error_type, now, 1)
                else:
                    # 在抑制窗口内，使用 DEBUG 级别避免刷屏
                    logger.debug(
                        "网络错误(抑制) alias=%s [%d/%ds]: %s", 
                        alias, int(elapsed), NETWORK_ERROR_LOG_SUPPRESS_WINDOW, error
                    )
                    # 更新计数但不更新时间（保持窗口起点）
                    self._network_error_log_state[alias] = (last_type, last_time, count + 1)

        return _on_polling_error

    def _handle_network_error_exhausted(self, alias: str):
        """处理网络错误重试耗尽的情况"""
        if alias != "main":
            return

        self._main_bot_network_error_count += 1
        logger.warning(
            "主bot网络错误计数: %d/10",
            self._main_bot_network_error_count
        )

        if self._main_bot_network_error_count >= 10:
            main_app = self.applications.get(self.main_profile.alias)
            main_bot_id = main_app.bot_data.get("bot_id") if main_app else None
            if not isinstance(main_bot_id, int):
                logger.warning("主bot连续网络错误达到10次，但无法确定 bot_id，暂不触发重启")
                return
            # 检查是否有活跃的CLI会话
            if not is_bot_processing(main_bot_id):
                logger.critical("主bot连续网络错误达到10次且无活跃会话，触发程序重启")
                import bot.config as config
                if config.RESTART_EVENT:
                    config.RESTART_REQUESTED = True
                    config.RESTART_EVENT.set()
            else:
                logger.warning("主bot连续网络错误达到10次，但有活跃CLI会话，暂不重启")

    async def _start_updater_polling_with_retry(self, app: Application, alias: str):
        """带指数退避重试的启动轮询"""
        retry_count = 0
        base_delay = NETWORK_ERROR_BASE_DELAY
        max_delay = NETWORK_ERROR_MAX_DELAY

        while retry_count < NETWORK_ERROR_MAX_RETRIES:
            try:
                await self._start_updater_polling(app, alias)
                if retry_count > 0:
                    logger.info("轮询恢复成功 alias=%s (重试%d次)", alias, retry_count)
                    # 清除日志抑制状态，让下次错误能正常记录
                    self._network_error_log_state.pop(alias, None)
                # 成功后重置主bot错误计数
                if alias == "main":
                    self._main_bot_network_error_count = 0
                return
            except (NetworkError, TimedOut) as e:
                retry_count += 1
                if retry_count >= NETWORK_ERROR_MAX_RETRIES:
                    logger.error("网络错误重试耗尽 alias=%s: %s", alias, e)
                    self._handle_network_error_exhausted(alias)
                    raise

                # 指数退避: 1s, 2s, 4s, 8s... 最高60s
                delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                logger.warning(
                    "网络错误，将在%.1f秒后重试 alias=%s (第%d/%d次): %s",
                    delay, alias, retry_count, NETWORK_ERROR_MAX_RETRIES, e
                )
                await asyncio.sleep(delay)
            except Exception as e:
                # 检查是否是 httpx 连接错误的包装
                if ConnectError is not None and isinstance(e, (ConnectError, ConnectTimeout, RemoteProtocolError)):
                    retry_count += 1
                    if retry_count >= NETWORK_ERROR_MAX_RETRIES:
                        logger.error("HTTPX连接错误重试耗尽 alias=%s: %s", alias, e)
                        self._handle_network_error_exhausted(alias)
                        raise

                    delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                    logger.warning(
                        "HTTPX连接错误，将在%.1f秒后重试 alias=%s (第%d/%d次): %s",
                        delay, alias, retry_count, NETWORK_ERROR_MAX_RETRIES, e
                    )
                    await asyncio.sleep(delay)
                    continue
                # 其他错误不重试，直接抛出
                raise

        raise RuntimeError(f"无法启动轮询 alias={alias}: 重试次数已耗尽")

    async def _start_updater_polling(self, app: Application, alias: str):
        if app.updater is None:
            raise RuntimeError("Application.updater 不可用，无法启动轮询")
        await app.updater.start_polling(
            poll_interval=0.0,
            timeout=POLLING_TIMEOUT,
            bootstrap_retries=POLLING_BOOTSTRAP_RETRIES,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            error_callback=self._make_polling_error_callback(alias),
        )

    async def _restart_polling_if_needed(self, alias: str, app: Application):
        if alias not in self.applications:
            return
        if bool(app.bot_data.get("stopping", False)):
            return
        if app.updater is None or not app.running:
            return
        if app.updater.running:
            return

        lock = self._polling_restart_locks.setdefault(alias, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            current = self.applications.get(alias)
            if current is not app:
                return
            if bool(app.bot_data.get("stopping", False)):
                return
            if app.updater is None or not app.running or app.updater.running:
                return

            try:
                logger.warning("检测到轮询已停止，正在自动重启 alias=%s", alias)
                await self._start_updater_polling_with_retry(app, alias)
                logger.info("轮询自动恢复成功 alias=%s", alias)
                # 清除日志抑制状态
                self._network_error_log_state.pop(alias, None)
            except Exception as e:
                logger.error("轮询自动恢复失败 alias=%s: %s", alias, e)

    async def _watchdog_loop(self):
        stop_event = self._watchdog_stop_event
        if stop_event is None:
            return

        while not stop_event.is_set():
            await asyncio.sleep(POLLING_WATCHDOG_INTERVAL)
            apps_snapshot = list(self.applications.items())
            for alias, app in apps_snapshot:
                try:
                    await self._restart_polling_if_needed(alias, app)
                except Exception as e:
                    logger.debug("watchdog 检查异常 alias=%s: %s", alias, e)

    async def start_watchdog(self):
        if self._watchdog_task and not self._watchdog_task.done():
            return
        self._watchdog_stop_event = asyncio.Event()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop_watchdog(self):
        task = self._watchdog_task
        event = self._watchdog_stop_event
        self._watchdog_task = None
        self._watchdog_stop_event = None
        if event:
            event.set()
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _load_profiles(self):
        self.managed_profiles = {}
        if not self.storage_file.exists():
            return

        try:
            raw = self.storage_file.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as e:
            logger.error(f"读取托管Bot配置失败: {e}")
            return

        items = data.get("bots", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            logger.warning("托管Bot配置格式无效，已忽略")
            return

        migrated_legacy_mode = False
        for item in items:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias", "")).strip().lower()
            token = str(item.get("token", "")).strip()
            if not alias or alias in RESERVED_ALIASES:
                continue
            raw_cli_type = str(item.get("cli_type", CLI_TYPE)).strip() or CLI_TYPE
            try:
                cli_type = validate_cli_type(raw_cli_type)
            except ValueError:
                logger.warning("子Bot `%s` 的 cli_type 无效(%s)，回退为 %s", alias, raw_cli_type, CLI_TYPE)
                cli_type = CLI_TYPE
            # 使用 from_dict 以支持 cli_params 字段
            profile_data = {
                "alias": alias,
                "token": token,
                "cli_type": cli_type,
                "cli_path": str(item.get("cli_path", CLI_PATH)).strip() or CLI_PATH,
                "working_dir": os.path.abspath(
                    os.path.expanduser(str(item.get("working_dir", WORKING_DIR)).strip() or WORKING_DIR)
                ),
                "enabled": bool(item.get("enabled", True)),
                "bot_mode": str(item.get("bot_mode", "cli")).strip().lower(),
            }
            if profile_data["bot_mode"] == "webcli":
                logger.warning("子Bot `%s` 的 webcli 模式已弃用，自动回退为 cli", alias)
                profile_data["bot_mode"] = "cli"
                migrated_legacy_mode = True
            # 如果有 cli_params 配置，一并传递
            if "cli_params" in item:
                profile_data["cli_params"] = item["cli_params"]
            self.managed_profiles[alias] = BotProfile.from_dict(profile_data)

        assistant_aliases = [alias for alias, profile in self.managed_profiles.items() if profile.bot_mode == "assistant"]
        if len(assistant_aliases) > 1:
            raise ValueError("配置中只允许一个 assistant 型 Bot")
        if len(assistant_aliases) == 1:
            bootstrap_assistant_home(self.managed_profiles[assistant_aliases[0]].working_dir)

        if migrated_legacy_mode:
            self._save_profiles()

    def _save_profiles(self):
        payload = {
            "bots": [
                self.managed_profiles[k].to_dict()
                for k in sorted(self.managed_profiles.keys())
            ]
        }
        self.storage_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_profile(self, alias: str) -> BotProfile:
        if alias == self.main_profile.alias:
            return self.main_profile
        if alias not in self.managed_profiles:
            raise KeyError(f"未知的 bot alias: `{alias}`")
        return self.managed_profiles[alias]

    def _get_profile_for_update(self, alias: str) -> BotProfile:
        """获取可更新的 profile（支持主 Bot 和托管 Bot）"""
        if alias == self.main_profile.alias:
            return self.main_profile
        if alias not in self.managed_profiles:
            raise ValueError(f"不存在 alias `{alias}`")
        return self.managed_profiles[alias]

    def _validate_alias(self, alias: str):
        if not BOT_ALIAS_RE.fullmatch(alias):
            raise ValueError("alias 仅允许字母/数字/_/-，长度 2-32")
        if alias in RESERVED_ALIASES:
            raise ValueError(f"alias `{alias}` 为保留名称")

    def _count_assistant_profiles(self) -> int:
        return sum(1 for profile in self.managed_profiles.values() if profile.bot_mode == "assistant")

    async def _send_startup_greeting(self, app: Application, profile: BotProfile):
        """向所有授权用户发送启动问候消息"""
        if not ALLOWED_USER_IDS:
            return

        import html as _html
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        greeting = (
            f"🤖 <b>Bot 已上线！</b>\n\n"
            f"⏰ 当前时间: <code>{_html.escape(now)}</code>\n"
            f"🔧 Coding CLI: <code>{_html.escape(profile.cli_type)}</code>"
            f" (<code>{_html.escape(profile.cli_path)}</code>)\n"
            f"📁 工作目录: <code>{_html.escape(profile.working_dir)}</code>\n\n"
            f"发送 /start 查看帮助"
        )

        for user_id in ALLOWED_USER_IDS:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=greeting,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"向用户 {user_id} 发送问候消息失败: {e}")

    async def _send_shutdown_goodbye(self, app: Application, profile: BotProfile):
        """向所有授权用户发送关闭告别消息"""
        if not ALLOWED_USER_IDS:
            return

        import html as _html
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        goodbye = (
            f"😴 <b>Bot 已下线</b>\n\n"
            f"⏰ 下线时间: <code>{_html.escape(now)}</code>\n"
            f"🔧 Coding CLI: <code>{_html.escape(profile.cli_type)}</code>\n"
            f"📁 工作目录: <code>{_html.escape(profile.working_dir)}</code>\n\n"
            f"感谢使用，再见！"
        )

        for user_id in ALLOWED_USER_IDS:
            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=goodbye,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"向用户 {user_id} 发送告别消息失败: {e}")

    async def _start_profile(self, profile: BotProfile, is_main: bool = False) -> Optional[Application]:
        if profile.alias in self.applications:
            return self.applications[profile.alias]
        if not self._profile_uses_telegram(profile):
            logger.info("Bot `%s` 未配置 Telegram token，跳过 Telegram 启动，仅保留 Web 访问", profile.alias)
            return None

        builder = Application.builder().token(profile.token)
        # 应用代理配置
        proxy_kwargs = get_proxy_kwargs()
        if proxy_kwargs:
            builder = builder.proxy_url(proxy_kwargs["proxy_url"])
        # 增加连接池大小和超时时间以适应多bot并发请求
        request = HTTPXRequest(
            connection_pool_size=32,
            read_timeout=60,
            write_timeout=60,
            connect_timeout=30,
            pool_timeout=30,
            **({"proxy": proxy_kwargs["proxy_url"]} if proxy_kwargs else {}),
        )
        app = (
            builder
            .request(request)
            .get_updates_request(HTTPXRequest(
                connection_pool_size=8,
                read_timeout=60,
                write_timeout=60,
                connect_timeout=30,
                pool_timeout=30,
                **({"proxy": proxy_kwargs["proxy_url"]} if proxy_kwargs else {}),
            ))
            .build()
        )
        app.bot_data["manager"] = self
        app.bot_data["bot_alias"] = profile.alias
        app.bot_data["is_main"] = is_main
        app.bot_data["bot_mode"] = profile.bot_mode

        # 注册全局错误处理器（网络错误静默重试）
        app.add_error_handler(self._make_error_handler(profile.alias))

        register_handlers(app, include_admin=is_main)

        initialized = False
        started = False
        updater_started = False
        try:
            await app.initialize()
            initialized = True
            me = await app.bot.get_me()
            app.bot_data["bot_id"] = me.id
            app.bot_data["bot_username"] = me.username or ""
            app.bot_data["stopping"] = False

            await app.start()
            started = True

            await self._start_updater_polling_with_retry(app, profile.alias)
            updater_started = True

            self.applications[profile.alias] = app
            self.bot_id_to_alias[int(me.id)] = profile.alias
            logger.info(
                "Bot已启动 alias=%s username=@%s",
                profile.alias,
                app.bot_data.get("bot_username") or "unknown",
            )

            # 发送启动问候消息（仅主 bot，使用 shield 保护，防止被取消）
            if is_main:
                await asyncio.shield(asyncio.create_task(self._send_startup_greeting(app, profile)))

            return app
        except Exception:
            if updater_started and app.updater:
                try:
                    await app.updater.stop()
                except Exception:
                    pass
            if started:
                try:
                    await app.stop()
                except Exception:
                    pass
            if initialized:
                try:
                    await app.shutdown()
                except Exception:
                    pass
            raise

    async def _stop_application(self, alias: str):
        app = self.applications.get(alias)
        if not app:
            return

        app.bot_data["stopping"] = True
        bot_id = app.bot_data.get("bot_id")
        profile = self.get_profile(alias)

        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
        except Exception as e:
            logger.warning(f"停止 updater 失败 alias={alias}: {e}")

        try:
            if app.running:
                await app.stop()
        except Exception as e:
            logger.warning(f"停止 app 失败 alias={alias}: {e}")

        try:
            await app.shutdown()
        except Exception as e:
            logger.warning(f"关闭 app 失败 alias={alias}: {e}")

        self.applications.pop(alias, None)
        self._polling_restart_locks.pop(alias, None)
        if isinstance(bot_id, int):
            self.bot_id_to_alias.pop(bot_id, None)
            clear_bot_sessions(bot_id)

        logger.info("Bot已停止 alias=%s", alias)

    async def start_all(self):
        await self._start_profile(self.main_profile, is_main=True)
        for alias, profile in list(self.managed_profiles.items()):
            if not profile.enabled:
                continue
            try:
                await self._start_profile(profile, is_main=False)
            except Exception as e:
                logger.error(f"启动子Bot失败 alias={alias}: {e}")

    async def shutdown_all(self):
        await self.stop_watchdog()
        await self._stop_manager_alerts()
        aliases = list(self.applications.keys())
        for alias in aliases:
            if alias != self.main_profile.alias:
                await self._stop_application(alias)
        if self.main_profile.alias in self.applications:
            await self._stop_application(self.main_profile.alias)

    async def add_bot(
        self,
        alias: str,
        token: str,
        cli_type: Optional[str] = None,
        cli_path: Optional[str] = None,
        working_dir: Optional[str] = None,
        bot_mode: Optional[str] = None,
    ) -> BotProfile:
        alias = alias.strip().lower()
        token = token.strip()
        self._validate_alias(alias)

        cli_type = validate_cli_type(cli_type or CLI_TYPE)
        cli_path = (cli_path or CLI_PATH).strip()
        bot_mode = (bot_mode or "cli").strip().lower()

        if bot_mode == "webcli":
            raise ValueError("webcli 模式已弃用，请使用 'cli' 或 'assistant'")

        if bot_mode not in ("cli", "assistant"):
            raise ValueError(f"bot_mode 必须是 'cli' 或 'assistant'，当前值: {bot_mode}")

        if bot_mode == "assistant":
            if working_dir is None or not str(working_dir).strip():
                raise ValueError("assistant 型 Bot 必须显式提供工作目录")
            working_dir = os.path.abspath(os.path.expanduser(str(working_dir).strip()))
        else:
            working_dir = os.path.abspath(os.path.expanduser((working_dir or WORKING_DIR).strip()))

        if not os.path.isdir(working_dir):
            raise ValueError(f"工作目录不存在: {working_dir}")

        if resolve_cli_executable(cli_path, working_dir) is None:
            raise ValueError(
                f"未找到CLI可执行文件: {cli_path} "
                f"(请使用可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
            )

        async with self._lock:
            if alias in self.managed_profiles:
                raise ValueError(f"alias `{alias}` 已存在")
            if token and (token == self.main_profile.token or any(p.token == token for p in self.managed_profiles.values() if p.token)):
                raise ValueError("该 token 已被使用")
            if bot_mode == "assistant" and self._count_assistant_profiles() >= 1:
                raise ValueError("当前机器只允许一个 assistant 型 Bot")

            profile = BotProfile(
                alias=alias,
                token=token,
                cli_type=cli_type,
                cli_path=cli_path,
                working_dir=working_dir,
                enabled=True,
                bot_mode=bot_mode,
            )

            if bot_mode == "assistant":
                bootstrap_assistant_home(working_dir)

            await self._start_profile(profile, is_main=False)
            self.managed_profiles[alias] = profile
            self._save_profiles()
            return profile

    async def remove_bot(self, alias: str):
        alias = alias.strip().lower()
        if alias == self.main_profile.alias:
            raise ValueError(f"无法移除主 Bot `{alias}`")
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            await self._stop_application(alias)
            del self.managed_profiles[alias]
            self._save_profiles()

    async def start_bot(self, alias: str):
        alias = alias.strip().lower()
        if alias == self.main_profile.alias:
            raise ValueError(f"主 Bot `{alias}` 已在运行，无需启动")
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            profile.enabled = True
            self._save_profiles()
            await self._start_profile(profile, is_main=False)

    async def stop_bot(self, alias: str):
        alias = alias.strip().lower()
        if alias == self.main_profile.alias:
            raise ValueError(f"主 Bot `{alias}` 无法通过此接口停止，请使用系统级管理")
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            profile.enabled = False
            self._save_profiles()
            await self._stop_application(alias)

    async def set_bot_cli(self, alias: str, cli_type: str, cli_path: str):
        alias = alias.strip().lower()
        cli_type = validate_cli_type(cli_type)
        cli_path = cli_path.strip()
        if not cli_path:
            raise ValueError("cli_path 不能为空")

        async with self._lock:
            profile = self._get_profile_for_update(alias)
            if resolve_cli_executable(cli_path, profile.working_dir) is None:
                raise ValueError(
                    f"未找到CLI可执行文件: {cli_path} "
                    f"(请使用可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
                )
            profile.cli_type = cli_type
            profile.cli_path = cli_path
            self._save_profiles()

    async def rename_bot(self, alias: str, new_alias: str):
        alias = alias.strip().lower()
        new_alias = new_alias.strip().lower()
        if alias == self.main_profile.alias:
            raise ValueError(f"主 Bot `{alias}` 不支持改名")
        self._validate_alias(new_alias)

        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            if new_alias == alias:
                raise ValueError("新旧 alias 不能相同")
            if new_alias == self.main_profile.alias or new_alias in self.managed_profiles:
                raise ValueError(f"alias `{new_alias}` 已存在")

            profile = self.managed_profiles.pop(alias)
            profile.alias = new_alias
            self.managed_profiles[new_alias] = profile

            app = self.applications.pop(alias, None)
            if app is not None:
                self.applications[new_alias] = app
                app.bot_data["bot_alias"] = new_alias
                bot_id = app.bot_data.get("bot_id")
                if isinstance(bot_id, int):
                    self.bot_id_to_alias[bot_id] = new_alias

            lock = self._polling_restart_locks.pop(alias, None)
            if lock is not None:
                self._polling_restart_locks[new_alias] = lock

            update_bot_alias(alias, new_alias)
            self._save_profiles()
            return profile

    async def set_bot_workdir(self, alias: str, working_dir: str):
        alias = alias.strip().lower()
        working_dir = os.path.abspath(os.path.expanduser(working_dir.strip()))
        if not os.path.isdir(working_dir):
            raise ValueError(f"工作目录不存在: {working_dir}")

        async with self._lock:
            profile = self._get_profile_for_update(alias)
            if profile.bot_mode == "assistant":
                raise ValueError("assistant 型 Bot 不允许修改默认工作目录")
            profile.working_dir = working_dir
            self._save_profiles()
            # 同时更新所有已存在的会话的工作目录
            update_bot_working_dir(alias, working_dir)

    async def get_bot_cli_params(self, alias: str, cli_type: Optional[str] = None) -> dict:
        """获取 Bot 的 CLI 参数配置"""
        alias = alias.strip().lower()
        async with self._lock:
            profile = self._get_profile_for_update(alias)
            if cli_type:
                return profile.cli_params.get_params(cli_type)
            return profile.cli_params.to_dict()

    async def set_bot_cli_param(self, alias: str, cli_type: str, key: str, value):
        """设置 Bot 的 CLI 参数"""
        alias = alias.strip().lower()
        cli_type = cli_type.lower().strip()
        
        async with self._lock:
            profile = self._get_profile_for_update(alias)
            coerced_value = coerce_param_value(cli_type, key, value)
            profile.cli_params.set_param(cli_type, key, coerced_value)
            self._save_profiles()

    async def reset_bot_cli_params(self, alias: str, cli_type: Optional[str] = None):
        """重置 Bot 的 CLI 参数为默认值"""
        alias = alias.strip().lower()
        
        async with self._lock:
            profile = self._get_profile_for_update(alias)
            profile.cli_params.reset_to_default(cli_type)
            self._save_profiles()

    def get_status_lines(self) -> List[str]:
        """生成美观的 Bot 状态列表，使用 HTML 格式"""
        lines: List[str] = []
        lines.append("<b>📊 Bot 状态概览</b>\n")

        # 辅助函数：生成状态标签
        def status_badge(status: str) -> str:
            badges = {
                "running": "🟢 <code>运行中</code>",
                "working": "🔵 <code>处理中</code>",
                "stopped": "🔴 <code>已停止</code>",
                "enabled": "✅ 已启用",
                "disabled": "⚪ 已禁用",
            }
            return badges.get(status, status)

        # 主 Bot 信息
        main_app = self.applications.get(self.main_profile.alias)
        if main_app:
            main_bot_id = main_app.bot_data.get("bot_id")
            main_working = is_bot_processing(main_bot_id) if isinstance(main_bot_id, int) else False
            main_status = "working" if main_working else "running"
        else:
            main_status = "stopped"
        main_username = (main_app.bot_data.get("bot_username") if main_app else "") or "unknown"

        lines.append(
            f"<b>👑 主 Bot</b>\n"
            f"  <b>别名:</b> <code>main</code>\n"
            f"  <b>用户名:</b> @{main_username}\n"
            f"  <b>状态:</b> {status_badge(main_status)}\n"
            f"  <b>CLI:</b> <code>{self.main_profile.cli_type}</code>\n"
            f"  <b>工作目录:</b> <code>{truncate_path_for_display(self.main_profile.working_dir, 30)}</code>\n"
        )

        # 子 Bot 列表
        if self.managed_profiles:
            lines.append("<b>🤖 托管 Bot</b> (<code>{}</code> 个)\n".format(len(self.managed_profiles)))
            for alias in sorted(self.managed_profiles.keys()):
                profile = self.managed_profiles[alias]
                app = self.applications.get(alias)
                if app:
                    bot_id = app.bot_data.get("bot_id")
                    is_working = is_bot_processing(bot_id) if isinstance(bot_id, int) else False
                    run_status = "working" if is_working else "running"
                else:
                    run_status = "stopped"
                username = (app.bot_data.get("bot_username") if app else "") or "unknown"
                enable_status = "enabled" if profile.enabled else "disabled"

                lines.append(
                    f"  ┌ <b>别名:</b> <code>{alias}</code>\n"
                    f"  ├ <b>用户名:</b> @{username}\n"
                    f"  ├ <b>运行状态:</b> {status_badge(run_status)}\n"
                    f"  ├ <b>启用状态:</b> {status_badge(enable_status)}\n"
                    f"  ├ <b>CLI:</b> <code>{profile.cli_type}</code>\n"
                    f"  └ <b>工作目录:</b> <code>{truncate_path_for_display(profile.working_dir, 28)}</code>\n"
                )
        else:
            lines.append("<i>💤 暂无托管 Bot</i>")

        return lines
