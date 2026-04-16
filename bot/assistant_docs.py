from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from bot.assistant_context import build_managed_memory_prompt, build_managed_memory_tail
from bot.assistant_home import AssistantHome

BEGIN_HOST_MANAGED_MEMORY_PROMPT = "<!-- BEGIN HOST_MANAGED_MEMORY_PROMPT -->"
END_HOST_MANAGED_MEMORY_PROMPT = "<!-- END HOST_MANAGED_MEMORY_PROMPT -->"


@dataclass(frozen=True)
class ManagedPromptSyncResult:
    agents_changed: bool
    claude_changed: bool
    managed_prompt_hash: str


def resolve_assistant_managed_template_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "assistant" / "managed_prompt_template.md"


def _load_template(path: Path) -> str:
    return path.read_text(encoding="utf-8").rstrip("\n")


def _build_memory_block(home: AssistantHome) -> str:
    body = build_managed_memory_tail(home).rstrip("\n")
    if body:
        return (
            f"{BEGIN_HOST_MANAGED_MEMORY_PROMPT}\n"
            f"{body}\n"
            f"{END_HOST_MANAGED_MEMORY_PROMPT}"
        )
    return (
        f"{BEGIN_HOST_MANAGED_MEMORY_PROMPT}\n"
        f"{END_HOST_MANAGED_MEMORY_PROMPT}"
    )


def _build_hash_memory_block(home: AssistantHome) -> str:
    body = build_managed_memory_prompt(home).rstrip("\n")
    if body:
        return (
            f"{BEGIN_HOST_MANAGED_MEMORY_PROMPT}\n"
            f"{body}\n"
            f"{END_HOST_MANAGED_MEMORY_PROMPT}"
        )
    return (
        f"{BEGIN_HOST_MANAGED_MEMORY_PROMPT}\n"
        f"{END_HOST_MANAGED_MEMORY_PROMPT}"
    )


def _compose_managed_prompt(template_text: str, memory_block: str) -> str:
    return f"{template_text.rstrip()}\n\n{memory_block}\n"


def compute_managed_prompt_hash(agents_text: str, claude_text: str) -> str:
    return hashlib.sha256(
        f"AGENTS.md\n{agents_text}\nCLAUDE.md\n{claude_text}".encode("utf-8")
    ).hexdigest()


def read_current_managed_prompt_hash(home: AssistantHome) -> str | None:
    if not home.agents_path.exists() or not home.claude_path.exists():
        return None

    return compute_managed_prompt_hash(
        home.agents_path.read_text(encoding="utf-8"),
        home.claude_path.read_text(encoding="utf-8"),
    )


def _write_if_changed(path: Path, expected_text: str) -> bool:
    current_text = path.read_text(encoding="utf-8") if path.exists() else None
    if current_text == expected_text:
        return False
    path.write_text(expected_text, encoding="utf-8")
    return True


def sync_managed_prompt_files(
    home: AssistantHome,
    *,
    template_path: str | Path | None = None,
) -> ManagedPromptSyncResult:
    resolved_template_path = (
        Path(template_path).resolve()
        if template_path is not None
        else resolve_assistant_managed_template_path()
    )
    template_text = _load_template(resolved_template_path)
    memory_block = _build_memory_block(home)
    managed_text = _compose_managed_prompt(template_text, memory_block)
    managed_prompt_hash = compute_managed_prompt_hash(managed_text, managed_text)

    return ManagedPromptSyncResult(
        agents_changed=_write_if_changed(home.agents_path, managed_text),
        claude_changed=_write_if_changed(home.claude_path, managed_text),
        managed_prompt_hash=managed_prompt_hash,
    )
