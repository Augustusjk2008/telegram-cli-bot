"""Use installed font faces for both SVG measurements and editable PPTX runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


@dataclass(frozen=True)
class Face:
    family: str
    path: str
    index: int = 0


ALIASES = {
    "微软雅黑": "microsoft yahei", "宋体": "simsun", "黑体": "simhei",
    "sans-serif": "microsoft yahei" if os.name == "nt" else "dejavu sans",
    "serif": "simsun" if os.name == "nt" else "dejavu serif",
    "monospace": "consolas" if os.name == "nt" else "dejavu sans mono",
}


@lru_cache(maxsize=1)
def installed_faces() -> dict[str, list[tuple[Face, str]]]:
    roots = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"] if os.name == "nt" else [
        Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
        Path("/System/Library/Fonts"), Path("/Library/Fonts"),
    ]
    roots += [Path.home() / ".fonts", Path.home() / ".local/share/fonts"]
    if os.name == "nt":
        roots.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts")
    result: dict[str, list[tuple[Face, str]]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                continue
            # Collections can contain different families (e.g. SimSun / NSimSun).
            for index in range(16 if path.suffix.lower() == ".ttc" else 1):
                try:
                    family, style = ImageFont.truetype(str(path), 32, index=index).getname()
                except OSError:
                    break
                result.setdefault(family.casefold(), []).append((Face(family, str(path), index), style.casefold()))
    return result


@lru_cache(maxsize=256)
def font(face: Face, size: float) -> ImageFont.FreeTypeFont:
    # Oversampling retains fractional SVG sizes without rounding each glyph.
    return ImageFont.truetype(face.path, max(1, round(size * 4)), index=face.index)


def resolve(families: str, bold: bool, italic: bool, text: str, warnings: list[str]) -> list[tuple[str, Face]]:
    catalog = installed_faces()
    requested = [name.strip().strip("\"'") for name in families.split(",") if name.strip()]
    names = [ALIASES.get(name.casefold(), name.casefold()) for name in requested]
    fallbacks = ["microsoft yahei", "simsun", "noto sans cjk sc", "noto sans sc", "wenquanyi zen hei", "dejavu sans"]
    candidates: list[Face] = []
    for name in dict.fromkeys(names + fallbacks):
        entries = catalog.get(name, [])
        if entries:
            def rank(entry):
                style = entry[1]
                return (int(("bold" in style) != bold) + int(("italic" in style or "oblique" in style) != italic))
            candidates.append(min(entries, key=rank)[0])
    if not candidates:
        raise ValueError("没有可测量的系统字体；请安装 Microsoft YaHei 或 Noto Sans CJK SC")
    if not any(name in catalog for name in names):
        warning = f"字体 {families or '(默认)'} 未安装，使用 {candidates[0].family}"
        if warning not in warnings:
            warnings.append(warning)
    result: list[tuple[str, Face]] = []
    for char in text:
        chosen = next((face for face in candidates if has_glyph(face, char)), None)
        if chosen is None:
            raise ValueError(f"没有系统字体支持字符 U+{ord(char):04X}")
        if chosen != candidates[0]:
            warning = f"字体 {candidates[0].family} 缺少部分字符，使用 {chosen.family}"
            if warning not in warnings:
                warnings.append(warning)
        if result and result[-1][1] == chosen:
            result[-1] = (result[-1][0] + char, chosen)
        else:
            result.append((char, chosen))
    return result


@lru_cache(maxsize=8192)
def has_glyph(face: Face, char: str) -> bool:
    if char.isspace():
        return True
    instance = font(face, 16)
    mask = instance.getmask(char)
    missing = instance.getmask("\U0010ffff")
    return mask.size != missing.size or bytes(mask) != bytes(missing)


def measure(face: Face, size: float, text: str) -> tuple[float, float, float, float]:
    instance = font(face, size)
    ascent, descent = instance.getmetrics()
    x_box = instance.getbbox("x", anchor="ls")
    return instance.getlength(text) / 4, ascent / 4, descent / 4, -x_box[1] / 4
