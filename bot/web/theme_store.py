"""Global UI themes with atomic persistence and legacy account migration."""

from __future__ import annotations

import copy
import base64
import binascii
import json
import math
import os
import re
import tempfile
import threading
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bot.runtime_paths import get_theme_library_path

BUILTIN_THEME_ID = "paper-daylight"
_THEME_ID = re.compile(r"theme_[0-9a-f]{32}\Z")
_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")
_CHAT_TYPOGRAPHY_DEFAULTS = {
    "chatBodyFontFamily": "sans",
    "chatBodyFontSize": "medium",
    "chatBodyLineHeight": "normal",
    "chatBodyParagraphSpacing": "normal",
}
_CHAT_TYPOGRAPHY_VALUES = {
    "chatBodyFontFamily": {"sans", "serif", "kai", "fangsong", "mono"},
    "chatBodyFontSize": {"small", "medium", "large"},
    "chatBodyLineHeight": {"tight", "normal", "relaxed"},
    "chatBodyParagraphSpacing": {"tight", "normal", "relaxed"},
}
_ILLUSTRATION_SURFACES = ("workbench", "chat", "topbar", "management")
_ILLUSTRATION_SET_IDS = (
    "none",
    "forest-grove",
    "tidal-grove",
    "desert-dusk",
    "alpine-fog",
    "moonlit-garden",
)
_ILLUSTRATION_UPLOAD_MIMES = {"image/png", "image/jpeg", "image/webp"}
_ILLUSTRATION_UPLOAD_MAX_BYTES = 512 * 1024
_ILLUSTRATION_UPLOAD_DATA = re.compile(
    r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})\Z"
)
_ILLUSTRATION_RESOURCE = re.compile(
    r"/assets/theme-illustrations/[a-z0-9]+(?:-[a-z0-9]+)*-(?:workbench|chat|topbar|management)\.svg\Z"
)
# All store instances in the host share the read/modify/replace boundary.
_STORE_LOCK = threading.RLock()


class ThemeStoreError(Exception):
    def __init__(self, status: int, code: str, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data or {}


def _invalid(message: str) -> None:
    raise ThemeStoreError(400, "invalid_theme", message)


def _object(value: Any, allowed: set[str], required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _invalid(f"{label}必须是对象")
    if value.keys() - allowed:
        _invalid(f"{label}包含不支持的字段：{', '.join(sorted(value.keys() - allowed))}")
    if required - value.keys():
        _invalid(f"{label}缺少字段：{', '.join(sorted(required - value.keys()))}")
    return value


def _schema(value: Any) -> None:
    if type(value) is not int or value != 1:
        raise ThemeStoreError(400, "unsupported_theme_schema", "不支持此主题数据版本，请更新应用后重试")


def _revision(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
        _invalid("主题库版本必须是非负安全整数")
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        _invalid("主题名称须为 1 到 80 个字符")
    if any(ord(char) < 32 for char in value):
        _invalid("主题名称不能包含控制字符")
    return value.strip()


def _default_illustrations() -> dict[str, Any]:
    return {
        "setId": "none",
        "opacity": 0,
        "surfaces": {surface: False for surface in _ILLUSTRATION_SURFACES},
    }


def _illustration_upload(value: Any) -> dict[str, str]:
    upload = _object(value, {"mimeType", "data"}, {"mimeType", "data"}, "illustrations.upload")
    mime_type = upload["mimeType"]
    data = upload["data"]
    if mime_type not in _ILLUSTRATION_UPLOAD_MIMES or not isinstance(data, str):
        _invalid("上传插画只支持 PNG、JPEG 或 WebP 文件")
    match = _ILLUSTRATION_UPLOAD_DATA.fullmatch(data)
    if not match or match.group(1) != mime_type:
        _invalid("上传插画数据无效")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error):
        _invalid("上传插画数据无效")
    if not raw or len(raw) > _ILLUSTRATION_UPLOAD_MAX_BYTES:
        _invalid("上传插画不能超过 512 KiB")
    valid_signature = (
        mime_type == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n")
    ) or (
        mime_type == "image/jpeg" and raw.startswith(b"\xff\xd8\xff")
    ) or (
        mime_type == "image/webp" and len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    )
    if not valid_signature:
        _invalid("上传插画文件内容与类型不匹配")
    return {"mimeType": mime_type, "data": data}


def builtin_library(builtin_override: dict[str, Any] | None = None) -> dict[str, Any]:
    theme = {
        "schemaVersion": 1,
        "id": BUILTIN_THEME_ID,
        "name": "纸感日间",
        "baseId": BUILTIN_THEME_ID,
        "appearance": {
            "colors": {"scheme": "light", "overrides": {}},
            "typography": dict(_CHAT_TYPOGRAPHY_DEFAULTS),
            "illustrations": _default_illustrations(),
        },
        "readonly": False,
        "updatedAt": "1970-01-01T00:00:00Z",
        "version": 1,
    }
    if builtin_override is not None:
        theme.update({
            "name": builtin_override["name"],
            "appearance": copy.deepcopy(builtin_override["appearance"]),
            "updatedAt": builtin_override["updatedAt"],
            "version": builtin_override["version"],
        })
    return {
        "schemaVersion": 1,
        "scope": "global",
        "revision": 0,
        "selectedThemeId": BUILTIN_THEME_ID,
        "themes": [theme],
    }


class ThemeStore:
    def __init__(self, library_path: Path | None = None, *, legacy_accounts_dir: Path | None = None,
                 catalog_path: Path | None = None):
        self.library_path = Path(library_path) if library_path is not None else get_theme_library_path()
        self.legacy_accounts_dir = (Path(legacy_accounts_dir) if legacy_accounts_dir is not None
                                    else self.library_path.parent / "accounts")
        self.catalog_path = catalog_path or Path(__file__).with_name("theme_catalog.json")
        self.illustration_catalog_path = Path(__file__).with_name("theme_illustrations.json")

    def _tokens(self) -> dict[str, dict[str, Any]]:
        try:
            catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            if type(catalog.get("schemaVersion")) is not int or catalog["schemaVersion"] != 1:
                raise ValueError("unsupported catalog")
            tokens = catalog["tokens"]
            if not isinstance(tokens, list) or not tokens:
                raise ValueError("empty catalog")
            result = {}
            for token in tokens:
                if not isinstance(token, dict) or not isinstance(token.get("key"), str):
                    raise ValueError("invalid token")
                if not token["key"] or token["key"] in result or type(token.get("allowAlpha")) is not bool:
                    raise ValueError("invalid token metadata")
                result[token["key"]] = token
            return result
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ThemeStoreError(500, "theme_catalog_unavailable", "主题颜色目录无法读取，请检查应用安装文件") from exc

    def _illustrations(self) -> dict[str, dict[str, str]]:
        try:
            catalog = json.loads(self.illustration_catalog_path.read_text(encoding="utf-8"))
            if not isinstance(catalog, dict) or set(catalog) != {"schemaVersion", "sets"}:
                raise ValueError("invalid illustration catalog")
            if type(catalog["schemaVersion"]) is not int or catalog["schemaVersion"] != 1:
                raise ValueError("unsupported illustration catalog")
            sets = catalog["sets"]
            if not isinstance(sets, dict) or set(sets) != set(_ILLUSTRATION_SET_IDS):
                raise ValueError("invalid illustration set IDs")
            result: dict[str, dict[str, str]] = {}
            for set_id in _ILLUSTRATION_SET_IDS:
                resources = sets[set_id]
                if not isinstance(resources, dict) or set(resources) != set(_ILLUSTRATION_SURFACES):
                    raise ValueError("invalid illustration surfaces")
                normalized: dict[str, str] = {}
                for surface in _ILLUSTRATION_SURFACES:
                    resource = resources[surface]
                    expected = f"/assets/theme-illustrations/{set_id}-{surface}.svg"
                    if not isinstance(resource, str) or resource != expected or not _ILLUSTRATION_RESOURCE.fullmatch(resource):
                        raise ValueError("invalid illustration resource")
                    normalized[surface] = resource
                result[set_id] = normalized
            return result
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
            raise ThemeStoreError(
                500,
                "theme_illustrations_unavailable",
                "主题插画目录无法读取，请检查应用安装文件",
            ) from exc

    def _appearance(self, value: Any) -> dict[str, Any]:
        appearance = _object(value, {"colors", "typography", "illustrations"}, {"colors"}, "appearance")
        colors = _object(appearance["colors"], {"scheme", "overrides"}, {"scheme", "overrides"}, "colors")
        if colors["scheme"] not in ("light", "dark"):
            _invalid("配色模式必须是 light 或 dark")
        overrides = colors["overrides"]
        if not isinstance(overrides, dict):
            _invalid("颜色覆盖必须是对象")
        tokens = self._tokens()
        normalized = {}
        for key, value in overrides.items():
            if key not in tokens:
                _invalid(f"未知颜色项目：{key}")
            if not isinstance(value, str) or not _HEX_COLOR.fullmatch(value.strip()):
                _invalid(f"{key} 须使用十六进制颜色，如 #RRGGBBAA")
            color = value.strip()[1:]
            if len(color) in (3, 4):
                color = "".join(char * 2 for char in color)
            if len(color) == 6:
                color += "FF"
            color = "#" + color.upper()
            if not tokens[key]["allowAlpha"] and color[-2:] != "FF":
                _invalid(f"{key} 不支持透明度")
            normalized[key] = color
        result = {"colors": {"scheme": colors["scheme"], "overrides": normalized}}
        if "typography" in appearance:
            typography = _object(
                appearance["typography"],
                set(_CHAT_TYPOGRAPHY_DEFAULTS),
                set(_CHAT_TYPOGRAPHY_DEFAULTS),
                "typography",
            )
            for key, choices in _CHAT_TYPOGRAPHY_VALUES.items():
                if not isinstance(typography[key], str) or typography[key] not in choices:
                    _invalid(f"{key} 包含不支持的值")
            result["typography"] = {key: typography[key] for key in _CHAT_TYPOGRAPHY_DEFAULTS}
        illustration_sets = self._illustrations()
        illustrations = appearance.get("illustrations", _default_illustrations())
        illustrations = _object(
            illustrations,
            {"setId", "upload", "opacity", "surfaces"},
            {"setId", "opacity", "surfaces"},
            "illustrations",
        )
        set_id = illustrations["setId"]
        if not isinstance(set_id, str) or (set_id != "upload" and set_id not in illustration_sets):
            _invalid("illustrations.setId 不是受支持的插画主题")
        upload = _illustration_upload(illustrations["upload"]) if "upload" in illustrations else None
        if (set_id == "upload") != (upload is not None):
            _invalid("上传插画配置与资源类型不匹配")
        opacity = illustrations["opacity"]
        if (
            isinstance(opacity, bool)
            or not isinstance(opacity, (int, float))
            or not math.isfinite(opacity)
            or not 0 <= opacity <= 0.25
        ):
            _invalid("illustrations.opacity 必须是 0 到 0.25 之间的数字")
        surfaces = _object(
            illustrations["surfaces"],
            set(_ILLUSTRATION_SURFACES),
            set(_ILLUSTRATION_SURFACES),
            "illustrations.surfaces",
        )
        if any(type(surfaces[surface]) is not bool for surface in _ILLUSTRATION_SURFACES):
            _invalid("illustrations.surfaces 的值必须是布尔值")
        result["illustrations"] = {
            "setId": set_id,
            "opacity": opacity,
            "surfaces": {surface: surfaces[surface] for surface in _ILLUSTRATION_SURFACES},
        }
        if upload is not None:
            result["illustrations"]["upload"] = upload
        return result

    def _read_file(self, path: Path, *, legacy: bool = False) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            if isinstance(exc, FileNotFoundError) and not legacy:
                return None
            raise ThemeStoreError(500, "theme_store_unreadable", "主题库文件无法读取，原文件已保留，请修复后重试") from exc
        try:
            fields = {"schemaVersion", "revision", "selectedThemeId", "themes"}
            required = set(fields)
            if not legacy:
                fields |= {"scope", "builtinTheme"}
                required.add("scope")
            data = _object(json.loads(raw), fields, required, "主题库")
            _schema(data["schemaVersion"])
            if not legacy and data["scope"] != "global":
                _invalid("主题库 scope 必须为 global")
            _revision(data["revision"])
            if not isinstance(data["themes"], list) or not isinstance(data["selectedThemeId"], str):
                _invalid("主题库结构无效")
            if "builtinTheme" in data:
                builtin = _object(
                    data["builtinTheme"],
                    {"name", "appearance", "updatedAt", "version"},
                    {"name", "appearance", "updatedAt", "version"},
                    "默认主题",
                )
                builtin["name"] = _name(builtin["name"])
                builtin["appearance"] = self._appearance(builtin["appearance"])
                if _revision(builtin["version"]) < 1:
                    _invalid("默认主题版本无效")
                if not isinstance(builtin["updatedAt"], str):
                    _invalid("默认主题更新时间无效")
                if datetime.fromisoformat(builtin["updatedAt"].replace("Z", "+00:00")).tzinfo is None:
                    _invalid("默认主题更新时间缺少时区")
            ids = {BUILTIN_THEME_ID}
            fields = {"schemaVersion", "id", "name", "baseId", "appearance", "readonly", "updatedAt", "version"}
            for theme in data["themes"]:
                _object(theme, fields, fields, "主题")
                _schema(theme["schemaVersion"])
                theme_id = theme["id"]
                if not isinstance(theme_id, str) or not _THEME_ID.fullmatch(theme_id) or theme_id in ids:
                    _invalid("主题 ID 无效或重复")
                ids.add(theme_id)
                if theme["baseId"] != BUILTIN_THEME_ID or theme["readonly"] is not False:
                    _invalid("自定义主题属性无效")
                _name(theme["name"])
                if _revision(theme["version"]) < 1:
                    _invalid("主题版本无效")
                if not isinstance(theme["updatedAt"], str):
                    _invalid("主题更新时间无效")
                if datetime.fromisoformat(theme["updatedAt"].replace("Z", "+00:00")).tzinfo is None:
                    _invalid("主题更新时间缺少时区")
                theme["appearance"] = self._appearance(theme["appearance"])
            if data["selectedThemeId"] not in ids:
                data["selectedThemeId"] = BUILTIN_THEME_ID
            return data
        except (ValueError, ThemeStoreError) as exc:
            detail = str(exc)
            raise ThemeStoreError(500, "theme_store_unreadable", f"主题库文件无法使用，原文件已保留，请修复后重试：{detail}") from exc

    def _read(self) -> dict[str, Any]:
        data = self._read_file(self.library_path)
        if data is not None:
            return data

        # Called under _STORE_LOCK. Validate every source before publishing the migration.
        try:
            paths = sorted((path for path in self.legacy_accounts_dir.iterdir()
                            if path.suffix.lower() == ".json"), key=lambda path: path.name)
        except FileNotFoundError:
            paths = []
        except OSError as exc:
            raise ThemeStoreError(500, "theme_store_unreadable",
                                  "旧主题库目录无法读取，原文件已保留，请修复后重试") from exc
        sources = [(path, self._read_file(path, legacy=True)) for path in paths]
        data = {**builtin_library(), "themes": []}
        reserved_ids = {theme["id"] for _, source in sources for theme in source["themes"]}
        seen: dict[str, set[str]] = {}
        for path, source in sources:
            for theme in source["themes"]:
                theme_id = theme["id"]
                content = json.dumps(theme, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                variants = seen.setdefault(theme_id, set())
                if content in variants:
                    continue
                if variants:
                    attempt = 0
                    while True:
                        replacement = "theme_" + uuid.uuid5(uuid.NAMESPACE_URL,
                            f"orbit-safe-claw:global-theme:{path.name}:{content}:{attempt}").hex
                        if replacement not in reserved_ids:
                            break
                        attempt += 1
                    reserved_ids.add(replacement)
                    theme = {**theme, "id": replacement}
                variants.add(content)
                data["themes"].append(theme)
        if sources:
            self._write(self.library_path, data)
        return data

    @staticmethod
    def _library(data: dict[str, Any]) -> dict[str, Any]:
        library = copy.deepcopy(data)
        builtin_override = library.pop("builtinTheme", None)
        library["themes"].insert(0, builtin_library(builtin_override)["themes"][0])
        return library

    def list_library(self) -> dict[str, Any]:
        with _STORE_LOCK:
            try:
                return self._library(self._read())
            except ThemeStoreError as exc:
                if exc.code != "theme_store_unreadable":
                    raise
                return {**builtin_library(), "error": exc.message}

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=f".{path.stem}-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise ThemeStoreError(500, "theme_store_write_failed", "主题库保存失败，已有主题保持不变，请重试") from exc
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()

    def _mutate(self, expected_revision: Any,
                change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        expected_revision = _revision(expected_revision)
        with _STORE_LOCK:
            data = self._read()
            if data["revision"] != expected_revision:
                raise ThemeStoreError(409, "theme_revision_conflict", "主题库已在其他页面更新，请重新加载后再保存",
                                      {"revision": data["revision"]})
            change(data)
            data["revision"] += 1
            self._write(self.library_path, data)
            return self._library(data)

    def _find(self, data: dict[str, Any], theme_id: Any, *, writable: bool = False) -> dict[str, Any]:
        if theme_id == BUILTIN_THEME_ID:
            return builtin_library(data.get("builtinTheme"))["themes"][0]
        for theme in data["themes"]:
            if theme["id"] == theme_id:
                return theme
        raise ThemeStoreError(404, "theme_not_found", "主题不存在")

    @staticmethod
    def _input(payload: Any, *, create: bool) -> dict[str, Any]:
        fields = {"schemaVersion", "expectedRevision", "name", "appearance", "activate"}
        required = {"schemaVersion", "expectedRevision"}
        if create:
            fields.add("sourceId")
            required |= {"sourceId", "name"}
        value = _object(payload, fields, required, "主题请求")
        _schema(value["schemaVersion"])
        if "activate" in value and type(value["activate"]) is not bool:
            _invalid("activate 必须是布尔值")
        if create and not isinstance(value["sourceId"], str):
            _invalid("sourceId 必须是主题 ID")
        return value

    def create(self, payload: Any) -> dict[str, Any]:
        value = self._input(payload, create=True)
        name = _name(value["name"])

        def change(data):
            source = self._find(data, value["sourceId"])
            appearance = self._appearance(value.get("appearance", source["appearance"]))
            theme = {
                "schemaVersion": 1, "id": "theme_" + uuid.uuid4().hex, "name": name,
                "baseId": BUILTIN_THEME_ID, "appearance": appearance, "readonly": False,
                "updatedAt": datetime.now(timezone.utc).isoformat(), "version": 1,
            }
            data["themes"].append(theme)
            if value.get("activate", False):
                data["selectedThemeId"] = theme["id"]

        return self._mutate(value["expectedRevision"], change)

    def import_themes(self, payload: Any) -> dict[str, Any]:
        fields = {"expectedRevision", "document"}
        value = _object(payload, fields, fields, "导入主题请求")
        theme_fields = {"schemaVersion", "name", "baseId", "appearance"}
        document = _object(value["document"], theme_fields | {"themes"}, {"schemaVersion"}, "主题文档")
        _schema(document["schemaVersion"])
        if "themes" in document:
            _object(document, {"schemaVersion", "themes"}, {"schemaVersion", "themes"}, "主题包")
            themes = document["themes"]
            if not isinstance(themes, list) or not themes:
                _invalid("主题包必须包含至少一个主题")
        else:
            themes = [document]

        imported = []
        for theme in themes:
            _object(theme, theme_fields, theme_fields, "主题")
            _schema(theme["schemaVersion"])
            if theme["baseId"] != BUILTIN_THEME_ID:
                _invalid("主题 baseId 必须为 paper-daylight")
            imported.append({
                "schemaVersion": 1, "name": _name(theme["name"]), "baseId": BUILTIN_THEME_ID,
                "appearance": self._appearance(theme["appearance"]),
            })

        def change(data):
            names = {theme["name"] for theme in data["themes"]}
            names.add(self._find(data, BUILTIN_THEME_ID)["name"])
            updated_at = datetime.now(timezone.utc).isoformat()
            for theme in imported:
                name = theme["name"]
                number = 2
                while name in names:
                    suffix = f" ({number})"
                    name = theme["name"][:80 - len(suffix)] + suffix
                    number += 1
                names.add(name)
                data["themes"].append({
                    **theme, "id": "theme_" + uuid.uuid4().hex, "name": name,
                    "readonly": False, "updatedAt": updated_at, "version": 1,
                })

        return self._mutate(value["expectedRevision"], change)

    def update(self, theme_id: str, payload: Any) -> dict[str, Any]:
        value = self._input(payload, create=False)

        def change(data):
            if theme_id == BUILTIN_THEME_ID:
                current = self._find(data, theme_id)
                data["builtinTheme"] = {
                    "name": _name(value["name"]) if "name" in value else current["name"],
                    "appearance": self._appearance(value["appearance"]) if "appearance" in value else current["appearance"],
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                    "version": current["version"] + 1,
                }
                if value.get("activate", False):
                    data["selectedThemeId"] = theme_id
                return
            theme = self._find(data, theme_id, writable=True)
            if "name" in value:
                theme["name"] = _name(value["name"])
            if "appearance" in value:
                theme["appearance"] = self._appearance(value["appearance"])
            theme["version"] += 1
            theme["updatedAt"] = datetime.now(timezone.utc).isoformat()
            if value.get("activate", False):
                data["selectedThemeId"] = theme_id

        return self._mutate(value["expectedRevision"], change)

    def delete(self, theme_id: str, payload: Any) -> dict[str, Any]:
        value = _object(payload, {"expectedRevision"}, {"expectedRevision"}, "删除主题请求")

        def change(data):
            if theme_id == BUILTIN_THEME_ID:
                raise ThemeStoreError(403, "theme_readonly", "默认主题不可删除")
            data["themes"].remove(self._find(data, theme_id, writable=True))
            if data["selectedThemeId"] == theme_id:
                data["selectedThemeId"] = BUILTIN_THEME_ID

        return self._mutate(value["expectedRevision"], change)

    def select(self, payload: Any) -> dict[str, Any]:
        value = _object(payload, {"themeId", "expectedRevision"}, {"themeId", "expectedRevision"}, "应用主题请求")
        if not isinstance(value["themeId"], str):
            _invalid("themeId 必须是主题 ID")

        def change(data):
            self._find(data, value["themeId"])
            data["selectedThemeId"] = value["themeId"]

        return self._mutate(value["expectedRevision"], change)
