"""Resolve Word formatting into the document renderer's restricted data model."""
from __future__ import annotations

import colorsys
import re
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = {"w": W[1:-1], "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
HIGHLIGHTS = {
    "black": "000000", "blue": "0000FF", "cyan": "00FFFF", "green": "00FF00",
    "magenta": "FF00FF", "red": "FF0000", "yellow": "FFFF00", "white": "FFFFFF",
    "darkBlue": "000080", "darkCyan": "008080", "darkGreen": "008000",
    "darkMagenta": "800080", "darkRed": "800000", "darkYellow": "808000",
    "darkGray": "808080", "lightGray": "C0C0C0",
}


def child(node: ET.Element | None, name: str) -> ET.Element | None:
    return node.find(f"w:{name}", NS) if node is not None else None


def attr(node: ET.Element | None, name: str = "val", default: str = "") -> str:
    return node.get(W + name, default) if node is not None else default


def integer(value: str, minimum: int | None = None) -> int | None:
    try:
        result = int(value)
    except (ValueError, TypeError):
        return None
    # Reject absurd optional values before converting to JSON/browser lengths.
    return result if abs(result) <= 2**31 - 1 and (minimum is None or result >= minimum) else None


def on_off(value: str) -> bool | None:
    if value.lower() in {"1", "true", "on"}:
        return True
    if value.lower() in {"0", "false", "off"}:
        return False
    return None


def merge(target: dict, source: dict) -> dict:
    for key, value in source.items():
        if isinstance(value, dict):
            merge(target.setdefault(key, {}), value)
        else:
            target[key] = value
    return target


def width(node: ET.Element | None) -> dict | None:
    unit = attr(node, "type", "dxa")
    value = integer(attr(node, "w"), 0)
    if unit == "nil":
        return {"unit": "px", "value": 0}
    if value is not None and unit in {"dxa", "pct"}:
        return {"unit": "px" if unit == "dxa" else "percent", "value": value / (15 if unit == "dxa" else 50)}
    return None


def padding(node: ET.Element | None) -> dict:
    result = {}
    for tag, key in (("top", "topPx"), ("bottom", "bottomPx"), ("left", "leftPx"),
                     ("right", "rightPx"), ("start", "leftPx"), ("end", "rightPx")):
        size = width(child(node, tag))
        if size is not None and size["unit"] == "px":
            result[key] = size["value"]
    return result


class Formatting:
    def __init__(self, styles: ET.Element | None, theme: ET.Element | None, settings: ET.Element | None):
        self.styles = {attr(s, "styleId"): s for s in styles.findall("w:style", NS)} if styles is not None else {}
        self.defaults = {}
        for key, style in self.styles.items():
            if on_off(attr(style, "default")):
                self.defaults[attr(style, "type")] = key
        defaults = child(styles, "docDefaults")
        self.default_run = child(child(defaults, "rPrDefault"), "rPr")
        self.default_paragraph = child(child(defaults, "pPrDefault"), "pPr")
        self.theme = theme
        self.east_asia_language = attr(child(settings, "themeFontLang"), "eastAsia", "zh-CN")
        self.colors = {}
        scheme = theme.find("a:themeElements/a:clrScheme", NS) if theme is not None else None
        for item in scheme if scheme is not None else []:
            if len(item):
                value = item[0].get("lastClr") or item[0].get("val", "")
                if re.fullmatch(r"[0-9a-fA-F]{6}", value):
                    self.colors[item.tag.rsplit("}", 1)[-1]] = value
        aliases = {"dark1": "dk1", "dark2": "dk2", "light1": "lt1", "light2": "lt2",
                   "text1": "dk1", "text2": "dk2", "background1": "lt1", "background2": "lt2",
                   "hyperlink": "hlink", "followedHyperlink": "folHlink"}
        mapping = child(settings, "clrSchemeMapping")
        for alias, key in aliases.items():
            mapping_name = {"text1": "t1", "text2": "t2", "background1": "bg1", "background2": "bg2"}.get(alias, alias)
            self.colors[alias] = self.colors.get(aliases.get(attr(mapping, mapping_name), attr(mapping, mapping_name)) or key, "")

    def chain(self, style_id: str, kind: str) -> list[ET.Element]:
        result, visited = [], set()
        while style_id and style_id not in visited:
            visited.add(style_id)
            style = self.styles.get(style_id)
            if style is None or attr(style, "type") != kind:
                break
            result.append(style)
            style_id = attr(child(style, "basedOn"))
        return list(reversed(result))

    def font(self, reference: str, language: str) -> str:
        if self.theme is None or reference not in {
            "majorAscii", "majorHAnsi", "majorEastAsia", "majorBidi",
            "minorAscii", "minorHAnsi", "minorEastAsia", "minorBidi",
        }:
            return ""
        family = self.theme.find(f"a:themeElements/a:fontScheme/a:{reference[:5]}Font", NS)
        if family is None:
            return ""
        slot = "ea" if reference.endswith("EastAsia") else "cs" if reference.endswith("Bidi") else "latin"
        node = family.find(f"a:{slot}", NS)
        value = node.get("typeface", "") if node is not None else ""
        if value or slot != "ea":
            return value
        language = language.lower()
        script = "Jpan" if language.startswith("ja") else "Hang" if language.startswith("ko") else (
            "Hant" if language in {"zh-tw", "zh-hk", "zh-mo", "zh-hant"} else "Hans"
        )
        return next((n.get("typeface", "") for n in family.findall("a:font", NS) if n.get("script") == script), "")

    def color(self, node: ET.Element | None, *, fill: bool = False) -> str | None:
        if node is None:
            return None
        value = attr(node, "fill" if fill else "val")
        theme = attr(node, "themeFill" if fill else "themeColor")
        themed = self.colors.get(theme)
        if themed:
            value = themed
            tint = attr(node, "themeFillTint" if fill else "themeTint")
            shade = attr(node, "themeFillShade" if fill else "themeShade")
            adjustment = tint or shade
            if re.fullmatch(r"[0-9a-fA-F]{2}", adjustment):
                rgb = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
                hue, light, saturation = colorsys.rgb_to_hls(*rgb)
                factor = int(adjustment, 16) / 255
                light = light * factor + (1 - factor if tint else 0)
                value = "".join(f"{round(c * 255):02X}" for c in colorsys.hls_to_rgb(hue, light, saturation))
        if value == "auto":
            return "transparent" if fill else "#000000"
        return "#" + value.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", value) else None

    def shading(self, node: ET.Element | None) -> str | None:
        if node is not None and attr(node) == "nil":
            return "transparent"
        if attr(node) == "solid":
            # Solid pattern uses the foreground color rather than the background fill.
            foreground = ET.Element(W + "color", {W + "val": attr(node, "color"), W + "themeColor": attr(node, "themeColor")})
            return self.color(foreground) or self.color(node, fill=True)
        return self.color(node, fill=True)

    def apply_run(self, result: dict, props: ET.Element | None, *, toggle: bool = False, language: str = "") -> None:
        if props is None:
            return
        for tag, key in (("b", "bold"), ("i", "italic")):
            node = child(props, tag)
            enabled = on_off(attr(node, default="true")) if node is not None else None
            if enabled is not None:
                if toggle:
                    if enabled:
                        result[key] = not result.get(key, False)
                else:
                    result[key] = enabled
        underline = child(props, "u")
        if underline is not None:
            value = attr(underline, default="single")
            if value in {"none", "0", "false", "off"}:
                result["underline"] = False
            elif value in {"single", "double", "words", "thick", "dotted", "dottedHeavy", "dash", "dashedHeavy",
                           "dashLong", "dashLongHeavy", "dotDash", "dashDotHeavy", "dotDotDash", "dashDotDotHeavy",
                           "wave", "wavyHeavy", "wavyDouble", "1", "true", "on"}:
                result["underline"] = True
        size = integer(attr(child(props, "sz")), 0)
        if size is not None:
            result["fontSizePx"] = size * 2 / 3
        color = self.color(child(props, "color"))
        if color is not None:
            result["color"] = color
        fonts = child(props, "rFonts")
        for key, slots in (("fontFamily", ("ascii", "hAnsi")), ("fontFamilyEastAsia", ("eastAsia",))):
            for slot in slots:
                value = self.font(attr(fonts, slot + "Theme"), language or self.east_asia_language) or attr(fonts, slot)
                if value.strip():
                    result[key] = value.strip()
                    break
        highlight = attr(child(props, "highlight"))
        if highlight == "none":
            result["highlightColor"] = "transparent"
        elif highlight in HIGHLIGHTS:
            result["highlightColor"] = "#" + HIGHLIGHTS[highlight]
        shading = self.shading(child(props, "shd"))
        if shading is not None:
            result["shadingColor"] = shading

    def run_style(self, layers: list[tuple[ET.Element | None, bool]]) -> dict:
        result = {}
        language = self.east_asia_language
        for props, _ in layers:
            language = attr(child(props, "lang"), "eastAsia") or language
        for props, toggle in layers:
            self.apply_run(result, props, toggle=toggle, language=language)
        return result

    def paragraph_format(self, layers: list[ET.Element | None]) -> dict:
        result, spacing = {}, {}
        for props in layers:
            align = attr(child(props, "jc"))
            align = {"start": "left", "end": "right", "both": "justify", "distribute": "justify"}.get(align, align)
            if align in {"left", "center", "right", "justify"}:
                result["align"] = align
            indent = child(props, "ind")
            for tag, key in (("left", "indentLeftPx"), ("start", "indentLeftPx"), ("right", "indentRightPx"), ("end", "indentRightPx"),
                             ("firstLine", "firstLineIndentPx"), ("hanging", "firstLineIndentPx")):
                value = integer(attr(indent, tag))
                if value is not None:
                    result[key] = value / (-15 if tag == "hanging" else 15)
            node = child(props, "spacing")
            for name in ("before", "after", "line"):
                value = integer(attr(node, name), 0)
                if value is not None:
                    spacing[name] = value
            rule = attr(node, "lineRule")
            if rule in {"auto", "exact", "atLeast"}:
                spacing["lineRule"] = rule
        for name, key in (("before", "spaceBeforePx"), ("after", "spaceAfterPx")):
            if name in spacing:
                result[key] = spacing[name] / 15
        if "line" in spacing:
            rule = spacing.get("lineRule", "auto")
            result["lineSpacing"] = {"mode": "multiple" if rule == "auto" else rule,
                                     "value": spacing["line"] / (240 if rule == "auto" else 15)}
        return result

    def borders(self, node: ET.Element | None) -> dict:
        result = {}
        for tag, key in (("top", "top"), ("bottom", "bottom"), ("left", "left"), ("right", "right"),
                         ("start", "left"), ("end", "right"), ("insideH", "insideHorizontal"), ("insideV", "insideVertical")):
            edge = child(node, tag)
            value = attr(edge)
            if not value:
                continue
            style = {"nil": "none", "none": "none", "single": "solid", "thick": "solid", "double": "double",
                     "dashed": "dashed", "dashSmallGap": "dashed", "dotDash": "dashed", "dotDotDash": "dashed",
                     "dotted": "dotted"}.get(value)
            if style is None:
                continue
            border = {"style": style}
            size = integer(attr(edge, "sz"), 0)
            if size is not None:
                border["widthPx"] = size / 6
            color_node = ET.Element(W + "color", dict(edge.attrib))
            color_node.set(W + "val", attr(edge, "color"))
            color = self.color(color_node)
            if color is not None:
                border["color"] = color
            result[key] = border
        return result

    def table_properties(self, props: ET.Element | None, *, cell: bool = False) -> dict:
        result = {}
        size = width(child(props, "tcW" if cell else "tblW"))
        if size is not None:
            result["width"] = size
        borders = self.borders(child(props, "tcBorders" if cell else "tblBorders"))
        if borders:
            result["borders"] = borders
        shading = self.shading(child(props, "shd"))
        if shading is not None:
            result["shadingColor"] = shading
        margins = padding(child(props, "tcMar" if cell else "tblCellMar"))
        if margins:
            result["padding" if cell else "cellPadding"] = margins
        align = attr(child(props, "vAlign"))
        if cell and align in {"top", "center", "bottom"}:
            result["verticalAlign"] = align
        return result
