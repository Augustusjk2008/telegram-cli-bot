"""多Bot生命周期管理器"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application

from bot.cli import resolve_cli_executable, validate_cli_type
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
    POLLING_BOOTSTRAP_RETRIES,
    POLLING_TIMEOUT,
    POLLING_WATCHDOG_INTERVAL,
    RESERVED_ALIASES,
    WORKING_DIR,
)
from bot.handlers import register_handlers
from bot.models import BotProfile
from bot.sessions import clear_bot_sessions, is_bot_processing, update_bot_working_dir

logger = logging.getLogger(__name__)


class MultiBotManager:
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
        self._load_profiles()

    def _make_polling_error_callback(self, alias: str):
        """轮询错误回调，记录不同类型的错误"""
        def _on_polling_error(error: Exception) -> None:
            if isinstance(error, (NetworkError, TimedOut)):
                logger.warning("网络错误 alias=%s: %s", alias, error)
            else:
                logger.warning("轮询异常 alias=%s: %s", alias, error)

        return _on_polling_error

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
                return
            except (NetworkError, TimedOut) as e:
                retry_count += 1
                if retry_count >= NETWORK_ERROR_MAX_RETRIES:
                    logger.error("网络错误重试耗尽 alias=%s: %s", alias, e)
                    raise

                # 指数退避: 1s, 2s, 4s, 8s... 最高60s
                delay = min(base_delay * (2 ** (retry_count - 1)), max_delay)
                logger.warning(
                    "网络错误，将在%.1f秒后重试 alias=%s (第%d/%d次): %s",
                    delay, alias, retry_count, NETWORK_ERROR_MAX_RETRIES, e
                )
                await asyncio.sleep(delay)
            except Exception:
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

        for item in items:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias", "")).strip().lower()
            token = str(item.get("token", "")).strip()
            if not alias or not token or alias in RESERVED_ALIASES:
                continue
            raw_cli_type = str(item.get("cli_type", CLI_TYPE)).strip() or CLI_TYPE
            try:
                cli_type = validate_cli_type(raw_cli_type)
            except ValueError:
                logger.warning("子Bot `%s` 的 cli_type 无效(%s)，回退为 %s", alias, raw_cli_type, CLI_TYPE)
                cli_type = CLI_TYPE
            self.managed_profiles[alias] = BotProfile(
                alias=alias,
                token=token,
                cli_type=cli_type,
                cli_path=str(item.get("cli_path", CLI_PATH)).strip() or CLI_PATH,
                working_dir=os.path.abspath(
                    os.path.expanduser(str(item.get("working_dir", WORKING_DIR)).strip() or WORKING_DIR)
                ),
                enabled=bool(item.get("enabled", True)),
                bot_mode=str(item.get("bot_mode", "cli")).strip().lower(),
            )

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
        return self.managed_profiles.get(alias, self.main_profile)

    def _validate_alias(self, alias: str):
        if not BOT_ALIAS_RE.fullmatch(alias):
            raise ValueError("alias 仅允许字母/数字/_/-，长度 2-32")
        if alias in RESERVED_ALIASES:
            raise ValueError(f"alias `{alias}` 为保留名称")

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

    async def _start_profile(self, profile: BotProfile, is_main: bool = False) -> Application:
        if profile.alias in self.applications:
            return self.applications[profile.alias]

        builder = Application.builder().token(profile.token)
        # 应用代理配置
        proxy_kwargs = get_proxy_kwargs()
        if proxy_kwargs:
            builder = builder.proxy_url(proxy_kwargs["proxy_url"])
        # 增加超时时间以适应网络不稳定情况
        app = (
            builder
            .read_timeout(60)
            .write_timeout(60)
            .connect_timeout(30)
            .pool_timeout(30)
            .build()
        )
        app.bot_data["manager"] = self
        app.bot_data["bot_alias"] = profile.alias
        app.bot_data["is_main"] = is_main
        app.bot_data["bot_mode"] = profile.bot_mode

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

            # 发送启动问候消息（使用 shield 保护，防止被取消）
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

        # 发送关闭告别消息（使用 shield 保护，防止被取消）
        try:
            await asyncio.shield(asyncio.create_task(self._send_shutdown_goodbye(app, profile)))
        except Exception as e:
            logger.debug(f"发送告别消息时发生异常 alias={alias}: {e}")

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

        if not token:
            raise ValueError("token 不能为空")

        cli_type = validate_cli_type(cli_type or CLI_TYPE)
        cli_path = (cli_path or CLI_PATH).strip()
        working_dir = os.path.abspath(os.path.expanduser((working_dir or WORKING_DIR).strip()))
        bot_mode = (bot_mode or "cli").strip().lower()

        if bot_mode not in ("cli", "assistant"):
            raise ValueError(f"bot_mode 必须是 'cli' 或 'assistant'，当前值: {bot_mode}")

        if not os.path.isdir(working_dir):
            raise ValueError(f"工作目录不存在: {working_dir}")

        # 只有 CLI 模式需要验证 CLI 可执行文件
        if bot_mode == "cli":
            if resolve_cli_executable(cli_path, working_dir) is None:
                raise ValueError(
                    f"未找到CLI可执行文件: {cli_path} "
                    f"(请使用可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
                )

        async with self._lock:
            if alias in self.managed_profiles:
                raise ValueError(f"alias `{alias}` 已存在")
            if token == self.main_profile.token or any(p.token == token for p in self.managed_profiles.values()):
                raise ValueError("该 token 已被使用")

            profile = BotProfile(
                alias=alias,
                token=token,
                cli_type=cli_type,
                cli_path=cli_path,
                working_dir=working_dir,
                enabled=True,
                bot_mode=bot_mode,
            )

            await self._start_profile(profile, is_main=False)
            self.managed_profiles[alias] = profile
            self._save_profiles()
            return profile

    async def remove_bot(self, alias: str):
        alias = alias.strip().lower()
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            await self._stop_application(alias)
            del self.managed_profiles[alias]
            self._save_profiles()

    async def start_bot(self, alias: str):
        alias = alias.strip().lower()
        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            profile.enabled = True
            self._save_profiles()
            await self._start_profile(profile, is_main=False)

    async def stop_bot(self, alias: str):
        alias = alias.strip().lower()
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
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            if resolve_cli_executable(cli_path, profile.working_dir) is None:
                raise ValueError(
                    f"未找到CLI可执行文件: {cli_path} "
                    f"(请使用可执行名或完整路径，例如 Windows 可能需要 claude.cmd)"
                )
            profile.cli_type = cli_type
            profile.cli_path = cli_path
            self._save_profiles()

    async def set_bot_workdir(self, alias: str, working_dir: str):
        alias = alias.strip().lower()
        working_dir = os.path.abspath(os.path.expanduser(working_dir.strip()))
        if not os.path.isdir(working_dir):
            raise ValueError(f"工作目录不存在: {working_dir}")

        async with self._lock:
            if alias not in self.managed_profiles:
                raise ValueError(f"不存在 alias `{alias}`")
            profile = self.managed_profiles[alias]
            profile.working_dir = working_dir
            self._save_profiles()
            # 同时更新所有已存在的会话的工作目录
            update_bot_working_dir(alias, working_dir)

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

        # 辅助函数：智能截断路径，优先保留盘符和最下级文件夹
        def truncate_path(path: str, max_len: int = 30) -> str:
            if len(path) <= max_len:
                return path
            
            # 统一使用反斜杠处理 Windows 路径
            normalized = path.replace("/", "\\")
            
            # 提取盘符（如 H:）
            drive = ""
            if len(normalized) >= 2 and normalized[1] == ":":
                drive = normalized[:2]  # e.g., "H:"
                rest = normalized[2:]   # e.g., "\WorkSpace\KimiAgent\game_agents"
            else:
                rest = normalized
            
            # 分割路径获取各级文件夹
            parts = [p for p in rest.split("\\") if p]
            if not parts:
                return path[:max_len - 3] + "..."
            
            # 最下级文件夹
            last_folder = parts[-1]
            
            # 尝试 "盘符\...\最下级文件夹" 格式
            # 预留 5 个字符给 "\...\" 或类似的省略标记
            # 实际使用 "..." 作为中间省略
            middle_ellipsis = "..."
            
            # 计算需要的空间：盘符 + 反斜杠 + 省略号 + 反斜杠 + 最下级文件夹
            # 如：H:\...\game_agents
            if drive:
                candidate = f"{drive}\\{middle_ellipsis}\\{last_folder}"
            else:
                candidate = f"{middle_ellipsis}\\{last_folder}"
            
            if len(candidate) <= max_len:
                return candidate
            
            # 如果最下级文件夹本身太长，截断它
            if len(last_folder) > max_len - len(drive) - 6:  # 预留 \...\ 的空间
                available = max_len - len(drive) - 6
                if available > 0:
                    truncated_last = last_folder[:available] + "..."
                    if drive:
                        return f"{drive}\\...\\{truncated_last}"
                    return f"...\\{truncated_last}"
            
            # 兜底：简单截断
            return path[:max_len - 3] + "..."

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
            f"  <b>工作目录:</b> <code>{truncate_path(self.main_profile.working_dir, 30)}</code>\n"
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
                    f"  └ <b>工作目录:</b> <code>{truncate_path(profile.working_dir, 28)}</code>\n"
                )
        else:
            lines.append("<i>💤 暂无托管 Bot</i>")

        return lines
