from __future__ import annotations

from pathlib import Path


_PROMPTS_DIR = Path(__file__).resolve().parent / "data" / "prompts"


class PromptRenderError(ValueError):
    pass


class _PromptFormatMap(dict[str, object]):
    def __missing__(self, key: str) -> object:
        raise PromptRenderError(f"prompt 缺少变量: {key}") from None


def load_prompt_template(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("prompt name 不能为空")
    path = _PROMPTS_DIR / f"{normalized}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"prompt 模板不存在: {normalized}") from exc


def render_prompt(name: str, **kwargs: object) -> str:
    template = load_prompt_template(name)
    return template.format_map(_PromptFormatMap(kwargs))
