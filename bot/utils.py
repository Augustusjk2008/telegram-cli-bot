"""与业务逻辑无关的通用工具函数"""

import os
import shlex
from typing import List

from bot.config import DANGEROUS_COMMANDS


def is_dangerous_command(command: str) -> bool:
    command_lower = command.lower().strip()
    first_word = command_lower.split()[0] if command_lower else ""
    return first_word in DANGEROUS_COMMANDS


def split_command_argv(command: str) -> List[str]:
    raw = str(command or "").strip()
    if os.name == "nt":
        argv = shlex.split(raw, posix=False)
        argv = [
            item[1:-1] if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"} else item
            for item in argv
        ]
    else:
        argv = shlex.split(raw, posix=True)
    if not argv:
        raise ValueError("empty command")
    return argv
