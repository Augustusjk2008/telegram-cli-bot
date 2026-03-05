"""程序入口：启动/重启循环"""

import asyncio
import logging
import os
import sys
import time

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
    TELEGRAM_BOT_TOKEN,
    WORKING_DIR,
    reexec_current_process,
)
from bot.manager import MultiBotManager
from bot.messages import get_messages
from bot.models import BotProfile

logger = logging.getLogger(__name__)


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
    await manager.start_all()
    await manager.start_watchdog()

    logger.info("主Bot与已启用子Bot已启动")
    logger.info("托管配置文件: %s", MANAGED_BOTS_FILE)

    try:
        await config.RESTART_EVENT.wait()
    finally:
        await manager.shutdown_all()
        config.RESTART_EVENT = None


def main():
    msgs = get_messages()
    
    if TELEGRAM_BOT_TOKEN == "your_bot_token_here":
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
    print(msgs.get("startup", "loaded"))

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
            # 短暂等待让启动问候消息的发送任务完成
            time.sleep(0.5)
            try:
                reexec_current_process()
            except Exception as e:
                print(f"进程级重启失败: {e}")
                break
        break


if __name__ == "__main__":
    main()
