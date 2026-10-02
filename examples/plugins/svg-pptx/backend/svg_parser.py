"""Static SVG subset with explicit diagnostics for unrepresentable editable text."""

from __future__ import annotations

import base64
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from io import BytesIO

import cssselect2
import tinycss2
from defusedxml import ElementTree as SafeET
from PIL import Image
from tinycss2.color3 import parse_color

import fonts


SVG = "http://www.w3.org/2000/svg"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"
INHERITED = {
    "color", "fill", "fill-opacity", "fill-rule", "clip-rule", "stroke", "stroke-width",
    "stroke-opacity", "stroke-dasharray", "stroke-dashoffset", "stroke-linecap",
    "stroke-linejoin", "stroke-miterlimit", "visibility", "font-family", "font-size",
    "font-weight", "font-style", "font-variant", "font-stretch", "text-anchor",
    "dominant-baseline", "direction", "writing-mode", "letter-spacing", "word-spacing",
    "text-decoration", "text-rendering", "shape-rendering", "image-rendering",
    "marker-start", "marker-mid", "marker-end", "paint-order", "white-space",
}
DEFAULTS = {
    "color": "black", "fill": "black", "fill-opacity": "1", "stroke": "none",
    "visibility": "visible", "font-family": "sans-serif", "font-size": "16px",
    "font-weight": "normal", "font-style": "normal", "text-anchor": "start",
    "dominant-baseline": "auto", "letter-spacing": "normal", "word-spacing": "normal",
}
PRESENTATION = INHERITED | {
    "display", "opacity", "filter", "mask", "clip-path", "alignment-baseline",
    "baseline-shift", "unicode-bidi", "mix-blend-mode", "isolation", "transform",
    "transform-origin", "transform-box", "stop-color", "stop-opacity",
}
DEFINITIONS = {"defs", "symbol", "clipPath", "mask", "pattern", "marker", "linearGradient", "radialGradient", "filter"}
GRAPHICS = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "image", "use"}


def tag(element) -> str:
    return str(element.tag).split("}")[-1]


def label(element) -> str:
    return f"<{tag(element)}{(' #' + element.get('id')) if element.get('id') else ''}>"


def limit(config: dict, name: str, default: int, maximum: int) -> int:
    try:
        return min(maximum, max(1, int(config.get(name, default))))
    except (ValueError, TypeError):
        return default


def length(value: str, reference: float = 0, font_size: float = 16, root_font: float = 16) -> float:
    match = re.fullmatch(rf"\s*({NUMBER})\s*(px|pt|pc|in|cm|mm|q|em|ex|rem|%)?\s*", str(value), re.I)
    if not match:
        raise ValueError(f"不支持的长度: {value}")
    number, unit = float(match[1]), (match[2] or "px").lower()
    factor = {"px": 1, "pt": 96 / 72, "pc": 16, "in": 96, "cm": 96 / 2.54,
              "mm": 96 / 25.4, "q": 96 / 101.6, "em": font_size, "ex": font_size / 2,
              "rem": root_font, "%": reference / 100}[unit]
    result = number * factor
    if not math.isfinite(result) or abs(result) > 1e7:
        raise ValueError(f"长度超出范围: {value}")
    return result


@dataclass(frozen=True)
class Matrix:
    a: float = 1
    b: float = 0
    c: float = 0
    d: float = 1
    e: float = 0
    f: float = 0

    def then(self, other: Matrix) -> Matrix:
        return Matrix(self.a * other.a + self.c * other.b, self.b * other.a + self.d * other.b,
                      self.a * other.c + self.c * other.d, self.b * other.c + self.d * other.d,
                      self.a * other.e + self.c * other.f + self.e, self.b * other.e + self.d * other.f + self.f)

    def point(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f

    def similarity(self) -> tuple[float, float]:
        scale = math.hypot(self.a, self.b)
        if (scale < 1e-8 or self.a * self.d - self.b * self.c <= 0
                or not math.isclose(self.a * self.c + self.b * self.d, 0, abs_tol=1e-7 * scale**2)
                or not math.isclose(scale, math.hypot(self.c, self.d), rel_tol=1e-7)):
            raise ValueError("文字的倾斜、镜像、非等比缩放或退化变换暂不支持")
        return scale, math.degrees(math.atan2(self.b, self.a))


def transform(value: str) -> Matrix:
    if value.strip() == "none":
        return Matrix()
    result, end = Matrix(), 0
    for match in re.finditer(r"([a-zA-Z]+)\s*\(([^)]*)\)", value):
        if value[end:match.start()].strip(" ,\t\r\n"):
            raise ValueError(f"无效的变换: {value}")
        pieces = re.findall(NUMBER, match[2])
        if re.sub(NUMBER, "", match[2]).strip(" ,\t\r\n"):
            raise ValueError(f"无效的变换参数: {value}")
        values = [float(piece) for piece in pieces]
        if any(not math.isfinite(v) or abs(v) > 1e7 for v in values):
            raise ValueError("变换参数超出范围")
        name = match[1]
        if name == "matrix" and len(values) == 6:
            local = Matrix(*values)
        elif name == "translate" and len(values) in {1, 2}:
            local = Matrix(e=values[0], f=values[1] if len(values) == 2 else 0)
        elif name == "scale" and len(values) in {1, 2}:
            local = Matrix(a=values[0], d=values[-1])
        elif name == "rotate" and len(values) in {1, 3}:
            angle = math.radians(values[0])
            local = Matrix(math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle))
            if len(values) == 3:
                local = Matrix(e=values[1], f=values[2]).then(local).then(Matrix(e=-values[1], f=-values[2]))
        elif name in {"skewX", "skewY"} and len(values) == 1:
            tangent = math.tan(math.radians(values[0]))
            local = Matrix(c=tangent) if name == "skewX" else Matrix(b=tangent)
        else:
            raise ValueError(f"不支持的变换: {value}")
        result, end = result.then(local), match.end()
    if value[end:].strip(" ,\t\r\n"):
        raise ValueError(f"无效的变换: {value}")
    return result


@dataclass
class Run:
    text: str
    face: fonts.Face
    size: float
    bold: bool
    italic: bool
    color: tuple[int, int, int]
    alpha: float
    decoration: str
    width: float
    ascent: float
    descent: float
    x_height: float


@dataclass
class TextBox:
    x: float
    y: float
    matrix: Matrix
    anchor: str
    baseline: str
    runs: list[Run] = field(default_factory=list)

    @property
    def width(self) -> float:
        return sum(run.width for run in self.runs)


@dataclass
class Layer:
    elements: list[ET.Element]


@dataclass
class Scene:
    root: ET.Element
    width: float
    height: float
    viewbox: tuple[float, float, float, float]
    styles: dict[ET.Element, dict[str, str]] = field(default_factory=dict)
    specified_styles: dict[ET.Element, dict[str, str]] = field(default_factory=dict)
    spaces: dict[ET.Element, bool] = field(default_factory=dict)
    references: dict[ET.Element, set[ET.Element]] = field(default_factory=dict)
    items: list[TextBox | Layer] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def report(self) -> dict:
        return {"width": self.width, "height": self.height,
                "textCount": sum(isinstance(item, TextBox) for item in self.items),
                "layerCount": sum(isinstance(item, Layer) for item in self.items),
                "warnings": self.warnings, "errors": self.errors}


def _tokens_safe(tokens, element: ET.Element, ids: dict, references: dict, images: list[int]):
    for token in tokens:
        if token.type == "error":
            raise ValueError(f"{label(element)} 无效的 CSS")
        if token.type == "url":
            _resource(token.value, element, ids, references, images, image=False)
        elif token.type == "function":
            if token.lower_name == "url":
                args = [t for t in token.arguments if t.type not in {"whitespace", "comment"}]
                if len(args) != 1 or args[0].type not in {"string", "url"}:
                    raise ValueError(f"{label(element)} 无效的资源引用")
                _resource(args[0].value, element, ids, references, images, image=False)
            elif token.lower_name in {"var", "env"}:
                raise ValueError(f"{label(element)} CSS 变量暂不支持")
            else:
                _tokens_safe(token.arguments, element, ids, references, images)
        elif hasattr(token, "content"):
            _tokens_safe(token.content, element, ids, references, images)


def _resource(value: str, element: ET.Element, ids: dict, references: dict, images: list[int], *, image: bool):
    value = value.strip()
    if value.startswith("#") and len(value) > 1:
        if value[1:] not in ids:
            raise ValueError(f"{label(element)} 内部引用不存在: {value}")
        references.setdefault(element, set()).add(ids[value[1:]])
        return
    match = re.fullmatch(r"data:image/(png|jpeg|gif|webp);base64,(.*)", value, re.I | re.S) if image else None
    if not match:
        raise ValueError(f"{label(element)} 拒绝外部资源；仅支持内部引用和内嵌 PNG/JPEG/GIF/WebP 图片")
    try:
        content = base64.b64decode("".join(match[2].split()), validate=True)
        with Image.open(BytesIO(content)) as picture:
            if picture.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
                raise ValueError("不支持的图片格式")
            pixels = picture.width * picture.height
            if pixels > 16_777_216 or sum(images) + pixels > 33_554_432:
                raise ValueError("内嵌图片像素超过限制")
            images.append(pixels)
            picture.verify()
    except Exception as exc:
        raise ValueError(f"{label(element)} 内嵌图片无效: {exc}") from exc


def _declarations(content) -> list[tuple[str, str, bool]]:
    result = []
    for declaration in tinycss2.parse_declaration_list(content, skip_comments=True, skip_whitespace=True):
        if declaration.type != "declaration":
            raise ValueError("无效的 CSS 声明")
        name, value = declaration.lower_name, tinycss2.serialize(declaration.value).strip()
        if name == "font":
            match = re.fullmatch(r"(?:(italic|oblique|normal)\s+)?(?:(bold|normal|[1-9]00)\s+)?(" + NUMBER + r"(?:px|pt|em|rem|%))(?:/normal)?\s+(.+)", value)
            if not match:
                raise ValueError("暂不支持此 font 简写；请分别设置 font-family/font-size/font-weight/font-style")
            result.extend((key, val, declaration.important) for key, val in {
                "font-style": match[1] or "normal", "font-weight": match[2] or "normal",
                "font-size": match[3], "font-family": match[4],
            }.items())
        else:
            result.append((name, value, declaration.important))
    return result


def _styles(scene: Scene) -> None:
    matcher = cssselect2.Matcher()
    namespace = {"svg": SVG}
    if scene.root.tag.startswith("{"):
        namespace[None] = SVG
    for element in scene.root.iter():
        if tag(element) != "style":
            continue
        for rule in tinycss2.parse_stylesheet("".join(element.itertext()), skip_comments=True, skip_whitespace=True):
            if rule.type != "qualified-rule":
                raise ValueError("内部 CSS 仅支持普通选择器规则；@import/@font-face/@media 等规则暂不支持")
            for selector in cssselect2.compile_selector_list(rule.prelude, namespaces=namespace):
                if selector.pseudo_element is not None:
                    raise ValueError("CSS 伪元素暂不支持")
                matcher.add_selector(selector, _declarations(rule.content))
    for wrapper in cssselect2.ElementWrapper.from_xml_root(scene.root).iter_subtree():
        element = wrapper.etree_element
        parent_style = scene.styles.get(wrapper.parent.etree_element, DEFAULTS) if wrapper.parent else DEFAULTS
        style = {key: parent_style[key] for key in INHERITED if key in parent_style}
        winners = {key: (False, (0, 0, 0, 0), -1, val) for key, val in element.attrib.items() if key in PRESENTATION}
        for specificity, order, _, declarations in matcher.match(wrapper):
            for key, value, important in declarations:
                candidate = (important, (0, *specificity), order, value)
                if key not in winners or candidate[:3] >= winners[key][:3]:
                    winners[key] = candidate
        for key, value, important in _declarations(element.get("style", "")):
            candidate = (important, (1, 0, 0, 0), 0, value)
            if key not in winners or candidate[:3] >= winners[key][:3]:
                winners[key] = candidate
        scene.specified_styles[element] = {key: winner[3] for key, winner in winners.items()}
        if element is scene.root and any(key in winners for key in {"width", "height"}):
            raise ValueError("CSS 画布尺寸暂不支持；请使用 SVG width/height 属性")
        parent_space = scene.spaces.get(wrapper.parent.etree_element, False) if wrapper.parent else False
        scene.spaces[element] = {"preserve": True, "default": False}.get(element.get(XML_SPACE), parent_space)
        for key, (_, _, _, value) in winners.items():
            if value == "inherit" or (value == "unset" and key in INHERITED):
                if key in parent_style:
                    style[key] = parent_style[key]
                else:
                    style.pop(key, None)
            elif value in {"initial", "unset"}:
                if key in DEFAULTS:
                    style[key] = DEFAULTS[key]
                else:
                    style.pop(key, None)
            else:
                style[key] = value
        parent_size = length(parent_style.get("font-size", "16px"))
        root_size = length(scene.styles.get(scene.root, DEFAULTS)["font-size"])
        size_value = style.get("font-size", "16px")
        keywords = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16, "large": 18, "x-large": 24, "xx-large": 32}
        if size_value in keywords:
            size = keywords[size_value]
        elif size_value in {"smaller", "larger"}:
            size = parent_size * (0.8 if size_value == "smaller" else 1.2)
        else:
            size = length(size_value, parent_size, parent_size, root_size)
        if size <= 0 or size > 4096:
            raise ValueError(f"{label(element)} 字号超出范围 (0, 4096]")
        style["font-size"] = f"{size:g}px"
        scene.styles[element] = style


def _canvas(root) -> tuple[float, float, tuple, Matrix]:
    viewbox_value = root.get("viewBox")
    viewbox = tuple(float(v) for v in re.split(r"[\s,]+", viewbox_value.strip())) if viewbox_value else None
    if viewbox and (len(viewbox) != 4 or any(not math.isfinite(v) or abs(v) > 1e7 for v in viewbox) or min(viewbox[2:]) <= 0):
        raise ValueError("viewBox 必须包含四个有限数值，宽高为正数")
    width_value, height_value = root.get("width"), root.get("height")
    width = length(width_value, viewbox[2] if viewbox else 0) if width_value else None
    height = length(height_value, viewbox[3] if viewbox else 0) if height_value else None
    if width is None and viewbox:
        width = height * viewbox[2] / viewbox[3] if height else viewbox[2]
    if height is None and viewbox:
        height = width * viewbox[3] / viewbox[2] if width else viewbox[3]
    if not width or not height or min(width, height) <= 0 or max(width, height) / min(width, height) > 56:
        raise ValueError("SVG 必须有正数画布尺寸（width/height 或 viewBox），宽高比不能超过 56:1")
    viewbox = viewbox or (0, 0, width, height)
    x, y, vw, vh = viewbox
    sx, sy = width / vw, height / vh
    aspect = root.get("preserveAspectRatio", "xMidYMid meet").strip().split()
    if aspect and aspect[0] == "defer":
        aspect = aspect[1:]
    alignment = aspect[0] if aspect else "xMidYMid"
    if alignment == "none":
        matrix = Matrix(a=sx, d=sy, e=-x * sx, f=-y * sy)
    else:
        if not re.fullmatch("x(Min|Mid|Max)Y(Min|Mid|Max)", alignment) or (len(aspect) > 1 and aspect[1] not in {"meet", "slice"}):
            raise ValueError("无效的 preserveAspectRatio")
        scale = max(sx, sy) if len(aspect) > 1 and aspect[1] == "slice" else min(sx, sy)
        factors = {"Min": 0, "Mid": 0.5, "Max": 1}
        matrix = Matrix(a=scale, d=scale, e=-x * scale + (width - vw * scale) * factors[alignment[1:4]],
                        f=-y * scale + (height - vh * scale) * factors[alignment[5:8]])
    return width, height, viewbox, matrix


def _text_runs(text: str, element, style: dict, scene: Scene) -> list[Run]:
    size = length(style["font-size"])
    weight = style.get("font-weight", "normal")
    if weight in {"normal", "bold"}:
        bold = weight == "bold"
    elif weight.isdigit() and 1 <= int(weight) <= 1000:
        bold = int(weight) >= 600
    else:
        raise ValueError(f"不支持的 font-weight: {weight}")
    italic_value = style.get("font-style", "normal")
    if italic_value not in {"normal", "italic", "oblique"}:
        raise ValueError(f"不支持的 font-style: {italic_value}")
    fill = style.get("fill", "black")
    if fill.lower() == "currentcolor":
        fill = style.get("color", "black")
    color = parse_color(fill) if fill != "none" else (0, 0, 0, 0)
    if color is None or isinstance(color, str):
        raise ValueError("文字填充仅支持纯色，不支持渐变/图案")
    alpha = color[3] * float(style.get("fill-opacity", "1")) * float(style.get("opacity", "1"))
    if not math.isfinite(alpha):
        raise ValueError("无效的文字透明度")
    if style.get("visibility") in {"hidden", "collapse"}:
        alpha = 0
    result = []
    for content, face in fonts.resolve(style["font-family"], bold, italic_value != "normal", text, scene.warnings):
        width, ascent, descent, x_height = fonts.measure(face, size, content)
        result.append(Run(content, face, size, bold, italic_value != "normal", tuple(round(c * 255) for c in color[:3]),
                          max(0, min(1, alpha)), style.get("text-decoration", "none"), width, ascent, descent, x_height))
    return result


def _validate_text(element, scene, effects: list[str]) -> None:
    style = scene.styles[element]
    if effects:
        raise ValueError("文字受 " + "、".join(effects) + " 影响，暂不支持")
    for node in element.iter():
        kind, own = tag(node), scene.styles[node]
        if kind not in {"text", "tspan", "title", "desc"}:
            raise ValueError(f"{label(node)} 文字结构暂不支持（包括 textPath）")
        for key in ("textLength", "lengthAdjust"):
            if key in node.attrib:
                raise ValueError(f"{label(node)} {key} 暂不支持")
        if node.get("rotate", "0").strip() not in {"0", "0.0"}:
            raise ValueError(f"{label(node)} 逐字符旋转暂不支持")
        if node is not element and own.get("transform", "none") != "none":
            raise ValueError(f"{label(node)} tspan 独立变换暂不支持")
        restrictions = {
            "stroke": {"none"}, "filter": {"none"}, "mask": {"none"}, "clip-path": {"none"},
            "writing-mode": {"horizontal-tb", "lr", "lr-tb"}, "direction": {"ltr"},
            "unicode-bidi": {"normal"}, "baseline-shift": {"baseline", "0", "0px"},
            "letter-spacing": {"normal", "0", "0px"}, "word-spacing": {"normal", "0", "0px"},
            "font-variant": {"normal"}, "font-stretch": {"normal", "100%"},
            "mix-blend-mode": {"normal"}, "white-space": {"normal", "pre"},
        }
        for key, allowed in restrictions.items():
            if key in own and own[key] not in allowed:
                raise ValueError(f"{label(node)} {key}={own[key]} 暂不支持")
        if any(key in own for key in {"x", "y", "dx", "dy", "inline-size", "text-align", "line-height"}):
            raise ValueError(f"{label(node)} CSS 文字位置/自动排版暂不支持；请使用 x/y/dx/dy 属性")
        if own.get("text-anchor", "start") not in {"start", "middle", "end"}:
            raise ValueError(f"{label(node)} 不支持的 text-anchor")
        if own.get("dominant-baseline", "auto") not in {"auto", "alphabetic", "middle", "central", "text-before-edge", "text-after-edge"}:
            raise ValueError(f"{label(node)} dominant-baseline 暂不支持")
        if own.get("alignment-baseline", "auto") not in {"auto", "baseline"}:
            raise ValueError(f"{label(node)} alignment-baseline 暂不支持")
        if own.get("text-decoration", "none") not in {"none", "underline", "line-through", "underline line-through"}:
            raise ValueError(f"{label(node)} text-decoration 暂不支持")
        if node is not element and own.get("opacity", "1") != "1":
            raise ValueError(f"{label(node)} tspan 组合透明度暂不支持；请使用 fill-opacity")


def _text(element, matrix: Matrix, scene: Scene, effects: list[str]) -> list[TextBox]:
    _validate_text(element, scene, effects)
    matrix.similarity()
    pieces: list[tuple[str, ET.Element, bool]] = []

    def flatten(node, preserve: bool):
        if scene.styles[node].get("display") == "none":
            return
        preserve = node.get(XML_SPACE, "") == "preserve" or (preserve and node.get(XML_SPACE) != "default") or scene.styles[node].get("white-space") == "pre"
        pieces.append(("", node, preserve))
        if node.text:
            pieces.append((node.text, node, preserve))
        for child in node:
            if tag(child) not in {"title", "desc"}:
                flatten(child, preserve)
            if child.tail:
                pieces.append((child.tail, node, preserve))

    flatten(element, scene.spaces[element])
    # Ignore pretty-print indentation, but keep literal separating spaces.
    pieces = [(re.sub(r"[\t\r\n]", " ", text) if preserve else re.sub(r"\s+", " ", text), node, preserve)
              for text, node, preserve in pieces if not text or preserve or text.strip() or not re.search(r"[\r\n]", text)]
    text_indices = [i for i, (text, _, _) in enumerate(pieces) if text]
    if text_indices:
        for i, trim in [(text_indices[0], str.lstrip), (text_indices[-1], str.rstrip)]:
            text, node, preserve = pieces[i]
            if not preserve:
                pieces[i] = (trim(text), node, preserve)
    x, y = 0.0, 0.0
    boxes: list[TextBox] = []
    chunk: list[TextBox] = []
    current: TextBox | None = None
    chunk_width = 0.0
    previous_space = False

    def finish_chunk():
        nonlocal chunk_width
        if chunk:
            factor = {"start": 0, "middle": 0.5, "end": 1}[chunk[0].anchor]
            for box in chunk:
                box.x -= factor * chunk_width
            chunk.clear()
        chunk_width = 0

    for text, node, preserve in pieces:
        style = scene.styles[node]
        if not text:
            positioned = any(key in node.attrib for key in {"x", "y", "dx", "dy"})
            if positioned:
                if "x" in node.attrib or "y" in node.attrib:
                    finish_chunk()
                size = length(style["font-size"])
                for key in ("x", "y", "dx", "dy"):
                    if key not in node.attrib:
                        continue
                    reference = scene.viewbox[2] if key in {"x", "dx"} else scene.viewbox[3]
                    try:
                        value = length(node.get(key), reference, size)
                    except ValueError as exc:
                        raise ValueError(f"{label(node)} {key} 仅支持单个位置: {exc}") from exc
                    if key == "x":
                        x = value
                    elif key == "y":
                        y = value
                    elif key == "dx":
                        x += value
                        if chunk:
                            chunk_width += value
                    else:
                        y += value
                current = None
            continue
        if not preserve and previous_space:
            text = text.lstrip(" ")
        if not text:
            continue
        if len(text) > 16_384:
            raise ValueError(f"{label(node)} 单段文字超过 16384 字符")
        run_style = dict(style)
        if node is not element:
            run_style["opacity"] = scene.styles[element].get("opacity", "1")
        runs = _text_runs(text, node, run_style, scene)
        baseline = style.get("dominant-baseline", "auto")
        anchor = style.get("text-anchor", "start")
        if current is None or current.y != y or current.baseline != baseline or current.anchor != anchor:
            current = TextBox(x, y, matrix, anchor, baseline)
            boxes.append(current)
            chunk.append(current)
        current.runs.extend(runs)
        advance = sum(run.width for run in runs)
        x += advance
        chunk_width += advance
        previous_space = text.endswith(" ") and not preserve
    finish_chunk()
    return boxes


def parse(source: bytes, config: dict | None = None) -> Scene:
    config = config or {}
    if len(source) > limit(config, "maxSourceBytes", 2_097_152, 33_554_432):
        raise ValueError("SVG 源文件超过大小限制")
    # PI events are normally discarded by ElementTree. Check them explicitly.
    for _, instruction in SafeET.iterparse(BytesIO(source), events=("pi",), forbid_dtd=True, forbid_entities=True, forbid_external=True):
        if str(instruction.text or "").strip():
            raise ValueError("SVG 不接受处理指令或外部样式表")
    root = SafeET.fromstring(source, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if tag(root) != "svg" or (root.tag.startswith("{") and root.tag != f"{{{SVG}}}svg"):
        raise ValueError("根元素必须是 SVG")
    nodes = list(root.iter())
    if len(nodes) > 20_000:
        raise ValueError("SVG 元素超过 20000 个")
    parents = {child: parent for parent in nodes for child in parent}
    for node in nodes:
        ancestor, depth = node, 0
        while ancestor in parents:
            ancestor, depth = parents[ancestor], depth + 1
            if depth > 128:
                raise ValueError("SVG 嵌套超过 128 层")
    width, height, viewbox, initial_matrix = _canvas(root)
    scene = Scene(root, width, height, viewbox)
    ids, references, images = {}, {}, []
    for element in nodes:
        if element.get("id"):
            if element.get("id") in ids:
                raise ValueError(f"重复的元素 ID: {element.get('id')}")
            ids[element.get("id")] = element
    for element in nodes:
        kind = tag(element)
        if kind in {"script", "foreignObject", "animate", "animateTransform", "animateMotion", "set", "discard"}:
            raise ValueError(f"{label(element)} 不支持脚本、动画或外部 HTML")
        for key, value in element.attrib.items():
            local = key.split("}")[-1]
            if local.lower().startswith("on") or local == "base":
                raise ValueError(f"{label(element)} 拒绝事件处理器或外部基路径")
            if local == "href":
                _resource(value, element, ids, references, images, image=kind == "image")
            elif local == "style" or local in PRESENTATION:
                _tokens_safe(tinycss2.parse_component_value_list(value), element, ids, references, images)
        if kind == "style":
            _tokens_safe(tinycss2.parse_component_value_list("".join(element.itertext())), element, ids, references, images)
        if kind in {"text", "tspan", "textPath"}:
            ancestor = parents.get(element)
            while ancestor is not None:
                if tag(ancestor) in DEFINITIONS:
                    scene.errors.append(f"{label(element)} 定义/遮罩/图案中的文字暂不支持可编辑转换")
                    break
                ancestor = parents.get(ancestor)
    visiting, checked = set(), set()

    def check_references(element):
        if element in visiting:
            raise ValueError(f"{label(element)} 循环内部引用")
        if element in checked:
            return
        visiting.add(element)
        for referenced in references.get(element, ()):
            check_references(referenced)
            if tag(element) == "use" and any(tag(node) in {"text", "tspan", "textPath"} for node in referenced.iter()):
                scene.errors.append(f"{label(element)} use 引用文字暂不支持可编辑转换")
        # A reference to a containing group can also cycle through its children.
        for child in element:
            check_references(child)
        visiting.remove(element)
        checked.add(element)

    check_references(root)
    scene.references = references
    _styles(scene)
    pending: list[ET.Element] = []

    def flush():
        if pending:
            scene.items.append(Layer(list(pending)))
            pending.clear()

    def walk(element, matrix: Matrix, effects: list[str]):
        kind, style = tag(element), scene.styles[element]
        if kind in DEFINITIONS or kind in {"style", "title", "desc", "metadata"} or style.get("display") == "none":
            return
        own_effects = list(effects)
        for key in ("filter", "mask", "clip-path", "mix-blend-mode"):
            if style.get(key, "none" if key != "mix-blend-mode" else "normal") not in {"none", "normal"}:
                own_effects.append(key)
        if kind not in {"text", "tspan"} and style.get("opacity", "1") != "1":
            own_effects.append("组合透明度")
        if kind == "svg" and element is not root:
            own_effects.append("嵌套 SVG 视口")
        if kind == "switch":
            own_effects.append("switch 条件分支")
        if kind in {"flowRoot", "flowPara", "flowSpan", "flowDiv", "flowRegion", "flowRegionExclude"}:
            scene.errors.append(f"{label(element)} 流式文字结构暂不支持可编辑转换")
            return
        if style.get("transform-origin", "0 0") not in {"0 0", "0px 0px"} or "transform-box" in style:
            own_effects.append("CSS transform-origin/transform-box")
        try:
            matrix = matrix.then(transform(style.get("transform", "")))
            if kind == "text":
                flush()
                scene.items.extend(_text(element, matrix, scene, own_effects))
            elif kind in GRAPHICS:
                if style.get("visibility") not in {"hidden", "collapse"}:
                    pending.append(element)
            else:
                for child in element:
                    walk(child, matrix, own_effects)
        except ValueError as exc:
            scene.errors.append(f"{label(element)}: {exc}")

    walk(root, initial_matrix, [])
    flush()
    if scene.report()["textCount"] > limit(config, "maxTextBoxes", 500, 500):
        scene.errors.append("可编辑文本框数量超过限制")
    if scene.report()["layerCount"] > limit(config, "maxLayers", 100, 100):
        scene.errors.append("图形图片层数量超过限制")
    return scene
