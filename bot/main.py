"""程序入口：启动/重启循环"""

import asyncio
import ctypes
import logging
import os
import sys
import time

# Windows 电源管理常量
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_CONTINUOUS = 0x80000000

# 确保 refactoring/ 在 sys.path 中，以便 `python bot/main.py` 也能正确导入 bot 包
_this_dir = os.path.dirname(os.path.abspath(__file__))          # refactoring/bot/
_package_root = os.path.dirname(_this_dir)                       # refactoring/
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

import bot.config as config
from bot.cli import validate_cli_type
from bot.config import (
    CLI_TYPE,
    CLI_PATH,
    MAIN_LOOP_RETRY_DELAY,
    MANAGED_BOTS_FILE,
    SESSION_TIMEOUT,
    TELEGRAM_ENABLED,
    TELEGRAM_BOT_TOKEN,
    WEB_ENABLED,
    WEB_HOST,
    WEB_PORT,
    WORKING_DIR,
    reexec_current_process,
)
from bot.manager import MultiBotManager
from bot.messages import get_messages
from bot.models import BotProfile
from bot.web import WebApiServer

logger = logging.getLogger(__name__)


def disable_console_quick_edit():
    """禁用 Windows 控制台快速编辑模式，避免点击控制台导致程序暂停"""
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            # 获取标准输入句柄
            stdin_handle = kernel32.GetStdHandle(-10)
            # 获取当前控制台模式
            mode = ctypes.c_uint32()
            kernel32.GetConsoleMode(stdin_handle, ctypes.byref(mode))
            # 禁用快速编辑模式 (ENABLE_QUICK_EDIT_MODE = 0x0040)
            # 禁用插入模式 (ENABLE_INSERT_MODE = 0x0020)
            new_mode = mode.value & ~0x0040 & ~0x0020
            kernel32.SetConsoleMode(stdin_handle, new_mode)
            logger.info("已禁用控制台快速编辑模式")
        except Exception as e:
            logger.warning(f"禁用快速编辑模式失败: {e}")


def prevent_system_sleep():
    """阻止系统进入睡眠状态"""
    if sys.platform == "win32":
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: 持续阻止系统睡眠
        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if result:
            logger.info("已阻止系统进入睡眠状态")
        else:
            logger.warning("阻止系统睡眠失败")


def restore_system_sleep():
    """恢复系统睡眠功能"""
    if sys.platform == "win32":
        # ES_CONTINUOUS: 清除之前的设置，恢复默认行为
        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        if result:
            logger.info("已恢复系统睡眠功能")
        else:
            logger.warning("恢复系统睡眠失败")


async def run_all_bots():
    config.RESTART_EVENT = asyncio.Event()
    main_profile = BotProfile(
        alias="main",
        token=TELEGRAM_BOT_TOKEN,
        cli_type=CLI_TYPE,
        cli_path=CLI_PATH,
        working_dir=WORKING_DIR,
        enabled=True,
    )

    manager = MultiBotManager(main_profile=main_profile, storage_file=MANAGED_BOTS_FILE)
    web_server = WebApiServer(manager) if WEB_ENABLED else None

    if TELEGRAM_ENABLED:
        await manager.start_all()
        await manager.start_watchdog()
        logger.info("主Bot与已启用子Bot已启动")
        logger.info("托管配置文件: %s", MANAGED_BOTS_FILE)

    if web_server:
        await web_server.start()
        logger.info("Web API 已启用: http://%s:%s", WEB_HOST, WEB_PORT)

    if not TELEGRAM_ENABLED and not web_server:
        raise RuntimeError("TELEGRAM_ENABLED 与 WEB_ENABLED 不能同时为 false")

    try:
        await config.RESTART_EVENT.wait()
    finally:
        if web_server:
            await web_server.stop()
        if TELEGRAM_ENABLED:
            await manager.shutdown_all()
        config.RESTART_EVENT = None
        restore_system_sleep()


def main():
    msgs = get_messages()
    
    if TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        print("错误: 请设置 TELEGRAM_BOT_TOKEN 环境变量")
        sys.exit(1)

    try:
        validate_cli_type(CLI_TYPE)
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(msgs.get("startup", "banner"))
    print(msgs.get("startup", "title"))
    print(msgs.get("startup", "version"))
    print(msgs.get("startup", "banner"))
    print()
    print(msgs.get("startup", "loading_config"))
    print(f"   CLI类型: {CLI_TYPE}")
    print(f"   工作目录: {WORKING_DIR}")
    print(f"   会话超时: {SESSION_TIMEOUT}秒")
    print(f"   托管配置: {MANAGED_BOTS_FILE}")
    print(f"   Telegram: {'开启' if TELEGRAM_ENABLED else '关闭'}")
    print(f"   Web API: {'开启' if WEB_ENABLED else '关闭'}")
    if WEB_ENABLED:
        print(f"   Web地址: http://{WEB_HOST}:{WEB_PORT}")
    print(msgs.get("startup", "loaded"))

    # 禁用控制台快速编辑模式，避免点击控制台导致程序暂停
    disable_console_quick_edit()

    # 阻止系统进入睡眠状态
    prevent_system_sleep()

    while True:
        config.RESTART_REQUESTED = False
        try:
            asyncio.run(run_all_bots())
        except KeyboardInterrupt:
            print(f"\n{msgs.get('startup', 'shutdown')}")
            break
        except Exception as e:
            logger.exception("运行异常，%s秒后自动重试: %s", MAIN_LOOP_RETRY_DELAY, e)
            print(f"运行异常，将在 {MAIN_LOOP_RETRY_DELAY} 秒后自动重试: {e}")
            time.sleep(MAIN_LOOP_RETRY_DELAY)
            continue

        if config.RESTART_REQUESTED:
            print(msgs.get("startup", "restart"))
            # 恢复系统睡眠（重启前）
            restore_system_sleep()
            # 短暂等待让启动问候消息的发送任务完成
            time.sleep(0.5)
            try:
                reexec_current_process()
            except Exception as e:
                print(f"进程级重启失败: {e}")
                break
        break

    # 程序退出前恢复系统睡眠
    restore_system_sleep()


if __name__ == "__main__":
    main()
