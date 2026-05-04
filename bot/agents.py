from __future__ import annotations

import hashlib
import re
from datetime import datetime

AGENT_MAIN_ID = "main"
AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
MAX_AGENT_NAME_LENGTH = 32
MAX_AGENT_PROMPT_CHARS = 12000


def now_iso() -> str:
    return datetime.now().isoformat()


def normalize_agent_id(value: object, *, allow_main: bool = True) -> str:
    agent_id = str(value or "").strip().lower()
    if agent_id == AGENT_MAIN_ID:
        if allow_main:
            return AGENT_MAIN_ID
        raise ValueError("不能使用 main 作为子 agent id")
    if not AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError("agent id 仅允许小写字母/数字/_/-，长度 2-32，且以字母开头")
    return agent_id


def normalize_agent_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("agent 名称不能为空")
    if len(name) > MAX_AGENT_NAME_LENGTH:
        raise ValueError(f"agent 名称不能超过 {MAX_AGENT_NAME_LENGTH} 字符")
    return name


def normalize_agent_prompt(value: object) -> str:
    prompt = str(value or "")
    if len(prompt) > MAX_AGENT_PROMPT_CHARS:
        raise ValueError(f"agent 系统提示词不能超过 {MAX_AGENT_PROMPT_CHARS} 字符")
    return prompt


def hash_agent_prompt(prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_agent_prompt_input(user_text: str, system_prompt: str) -> tuple[str, str]:
    prompt = str(system_prompt or "").strip()
    if not prompt:
        return user_text, ""
    prompt_hash = hash_agent_prompt(prompt)
    wrapped = (
        "<tcbridge_agent_system_prompt>\n"
        f"{prompt}\n"
        "</tcbridge_agent_system_prompt>\n\n"
        "<user_message>\n"
        f"{user_text}\n"
        "</user_message>"
    )
    return wrapped, prompt_hash
