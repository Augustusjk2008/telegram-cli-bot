"""Preset UI themes with atomic persistence and per-account selection."""

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

from bot.runtime_paths import get_theme_assets_dir, get_theme_library_path
from bot.web.theme_asset_store import MAX_THEME_ASSET_TOTAL_BYTES, ThemeAssetStore, ThemeAssetStoreError

BUILTIN_THEME_ID = "paper-daylight"
_THEME_ID = re.compile(r"theme_[0-9a-f]{32}\Z")
THEME_READONLY_MESSAGE = "预置主题由应用发布，不能修改"
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
_THEME_MATERIAL_VALUES = {
    "shape": {"sharp", "crisp", "soft", "round"},
    "glass": {"none", "frost", "deep"},
    "glow": {"none", "soft", "vivid"},
    "depth": {"flat", "print", "float"},
}
_ILLUSTRATION_SURFACES = ("workbench", "adminCenter", "agentManager")
_LEGACY_ILLUSTRATION_SURFACES = ("workbench", "chat", "topbar", "management")
_ILLUSTRATION_SET_IDS = (
    "none",
    "forest-grove",
    "tidal-grove",
    "desert-dusk",
    "alpine-fog",
    "moonlit-garden",
    "armor-core-hud",
    "apollo-plan",
    "mint-citrus",
    "cyberpunk-2077",
    "deepseek-big-fish",
    "k-on-light-music",
)
_ILLUSTRATION_UPLOAD_MIMES = {"image/png", "image/jpeg", "image/webp"}
_ILLUSTRATION_UPLOAD_MAX_BYTES = 4 * 1024 * 1024
_ILLUSTRATION_UPLOAD_DATA = re.compile(
    r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})\Z"
)
_ILLUSTRATION_ANCHORS = {"top", "left", "right", "bottom", "bottom-left", "bottom-right", "center"}
_ILLUSTRATION_LAYER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_ILLUSTRATION_SURFACE_FILENAMES = {
    "workbench": "workbench",
    "adminCenter": "admin-center",
    "agentManager": "agent-manager",
}
# All store instances in the host share the read/modify/replace boundary.
_STORE_LOCK = threading.RLock()


class ThemeStoreError(Exception):
    def __init__(self, status: int, code: str, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data or {}


def _invalid(message: str, code: str = "invalid_theme") -> None:
    raise ThemeStoreError(400, code, message)


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


def _selection_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        _invalid("主题选择映射必须是对象")
    if any(not isinstance(account_id, str) or not account_id.strip()
           or not isinstance(theme_id, str) or not theme_id.strip()
           for account_id, theme_id in value.items()):
        _invalid("主题选择映射包含无效值")
    return {account_id: theme_id for account_id, theme_id in value.items()}


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
        _invalid("主题名称须为 1 到 80 个字符")
    if any(ord(char) < 32 for char in value):
        _invalid("主题名称不能包含控制字符")
    return value.strip()


def _default_illustrations() -> dict[str, Any]:
    catalog = _read_illustration_catalog_file(Path(__file__).with_name("theme_illustrations.json"))
    return {
        "opacity": 0,
        "surfaces": {surface: False for surface in _ILLUSTRATION_SURFACES},
        "scenes": {
            surface: {
                "layers": [
                    {**layer, "asset": {"kind": "builtin", **layer["asset"]}}
                    for layer in catalog["none"][surface]["layers"]
                ],
            }
            for surface in _ILLUSTRATION_SURFACES
        },
    }


def _legacy_illustration_set_id(asset_id: Any, surface: str) -> str:
    if not isinstance(asset_id, str):
        return ""
    suffix = f"-{_ILLUSTRATION_SURFACE_FILENAMES[surface]}"
    return next((set_id for set_id in _ILLUSTRATION_SET_IDS if asset_id == f"{set_id}{suffix}"), "")


def _read_illustration_catalog_file(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(catalog, dict) or catalog.get("schemaVersion") != 3 or not isinstance(catalog.get("sets"), dict):
            raise ValueError("invalid illustration catalog")
        sets = catalog["sets"]
        if set(sets) != set(_ILLUSTRATION_SET_IDS):
            raise ValueError("invalid illustration set IDs")
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for set_id in _ILLUSTRATION_SET_IDS:
            resources = sets[set_id]
            if not isinstance(resources, dict) or set(resources) != set(_ILLUSTRATION_SURFACES):
                raise ValueError("invalid illustration surfaces")
            result[set_id] = {}
            for surface in _ILLUSTRATION_SURFACES:
                scene = resources[surface]
                if not isinstance(scene, dict) or set(scene) != {"layers"} or not isinstance(scene["layers"], list) or not scene["layers"] or len(scene["layers"]) > 32:
                    raise ValueError("invalid illustration layers")
                normalized_layers = []
                layer_ids: set[str] = set()
                for layer in scene["layers"]:
                    if not isinstance(layer, dict) or set(layer) - {"id", "asset", "anchor", "x", "y", "width", "height", "objectPosition", "opacity", "enabled"}:
                        raise ValueError("invalid illustration layer")
                    if not isinstance(layer.get("id"), str) or not _ILLUSTRATION_LAYER_ID.fullmatch(layer["id"]) or layer["id"] in layer_ids:
                        raise ValueError("invalid illustration layer ID")
                    layer_ids.add(layer["id"])
                    if layer.get("anchor") not in _ILLUSTRATION_ANCHORS or type(layer.get("enabled")) is not bool:
                        raise ValueError("invalid illustration layer placement")
                    for key, minimum, maximum in (("x", -100, 100), ("y", -100, 100), ("width", 0.01, 300), ("height", 0.01, 300), ("opacity", 0, 1)):
                        if key in layer and (isinstance(layer[key], bool) or not isinstance(layer[key], (int, float)) or not math.isfinite(layer[key]) or not minimum <= layer[key] <= maximum):
                            raise ValueError("invalid illustration layer placement")
                    if "objectPosition" in layer and (not isinstance(layer["objectPosition"], str) or len(layer["objectPosition"]) > 120):
                        raise ValueError("invalid illustration object position")
                    resource = layer.get("asset")
                    if not isinstance(resource, dict) or set(resource) != {"assetId", "mimeType", "width", "height", "sha256", "path"}:
                        raise ValueError("invalid illustration metadata")
                    expected_prefix = f"/assets/theme-illustrations/{set_id}/"
                    if not isinstance(resource["path"], str) or not resource["path"].startswith(expected_prefix) or not resource["path"].endswith(".webp"):
                        raise ValueError("invalid illustration resource")
                    if resource["mimeType"] not in {"image/webp", "image/png"} or type(resource["width"]) is not int or type(resource["height"]) is not int or resource["width"] < 1 or resource["height"] < 1:
                        raise ValueError("invalid illustration dimensions")
                    if not isinstance(resource["assetId"], str) or not re.fullmatch(r"[A-Za-z0-9-]+", resource["assetId"]):
                        raise ValueError("invalid illustration asset ID")
                    if not isinstance(resource["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", resource["sha256"], re.I):
                        raise ValueError("invalid illustration hash")
                    normalized_layers.append({
                        key: layer[key] for key in ("id", "anchor", "x", "y", "width", "height", "objectPosition", "opacity", "enabled") if key in layer
                    } | {"asset": {key: resource[key] for key in ("assetId", "mimeType", "width", "height", "sha256")}})
                result[set_id][surface] = {"layers": normalized_layers}
        return result
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise ThemeStoreError(500, "theme_illustrations_unavailable", "主题插画目录无法读取，请检查应用安装文件") from exc


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
        _invalid("上传插画不能超过 4 MiB")
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
        "name": "钢铁核心",
        "baseId": BUILTIN_THEME_ID,
        "appearance": {
            "colors": {"scheme": "light", "overrides": {}},
            "typography": dict(_CHAT_TYPOGRAPHY_DEFAULTS),
            "illustrations": _default_illustrations(),
        },
        "readonly": True,
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
                 catalog_path: Path | None = None, asset_root: Path | None = None,
                 presets_path: Path | None = None):
        self.library_path = Path(library_path) if library_path is not None else get_theme_library_path()
        self.legacy_accounts_dir = (Path(legacy_accounts_dir) if legacy_accounts_dir is not None
                                    else self.library_path.parent / "accounts")
        self.catalog_path = catalog_path or Path(__file__).with_name("theme_catalog.json")
        self.presets_path = Path(presets_path) if presets_path is not None else Path(__file__).with_name("theme_presets.json")
        self.illustration_catalog_path = Path(__file__).with_name("theme_illustrations.json")
        self.asset_store = ThemeAssetStore(asset_root if asset_root is not None else (
            get_theme_assets_dir() if library_path is None else self.library_path.parent / "assets"
        ))

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

    def _illustrations(self) -> dict[str, dict[str, dict[str, Any]]]:
        return _read_illustration_catalog_file(self.illustration_catalog_path)

    def _uploaded_asset_from_legacy(self, value: Any) -> dict[str, Any]:
        upload = _illustration_upload(value)
        match = _ILLUSTRATION_UPLOAD_DATA.fullmatch(upload["data"])
        if not match:
            _invalid("上传插画数据无效")
        try:
            raw = base64.b64decode(match.group(2), validate=True)
            return self.asset_store.store(raw, upload["mimeType"])
        except (ValueError, binascii.Error):
            _invalid("上传插画数据无效")
        except ThemeAssetStoreError as exc:
            raise ThemeStoreError(exc.status, exc.code, exc.message, exc.data) from exc

    def _illustrations_value(
        self,
        value: Any,
        *,
        asset_overrides: dict[str, tuple[dict[str, Any], bytes]] | None = None,
    ) -> dict[str, Any]:
        if value is None:
            return _default_illustrations()
        if not isinstance(value, dict):
            _invalid("主题插画配置必须是对象")
        catalog = self._illustrations()
        if "scenes" in value:
            illustrations = _object(value, {"opacity", "surfaces", "scenes"}, {"opacity", "surfaces", "scenes"}, "illustrations")
            set_id = None
        else:
            # First-read migration for the previous single-set format.
            illustrations = _object(value, {"setId", "upload", "opacity", "surfaces"}, {"setId", "opacity", "surfaces"}, "illustrations")
            set_id = illustrations["setId"]
            if not isinstance(set_id, str) or (set_id != "upload" and set_id not in catalog):
                _invalid("illustrations.setId 不是受支持的插画主题")
            upload_asset = self._uploaded_asset_from_legacy(illustrations["upload"]) if "upload" in illustrations else None
            if (set_id == "upload") != (upload_asset is not None):
                _invalid("上传插画配置与资源类型不匹配")
            legacy_surfaces = _object(illustrations["surfaces"], set(_LEGACY_ILLUSTRATION_SURFACES), set(_LEGACY_ILLUSTRATION_SURFACES), "illustrations.surfaces")
            if any(type(legacy_surfaces[surface]) is not bool for surface in _LEGACY_ILLUSTRATION_SURFACES):
                _invalid("illustrations.surfaces 的值必须是布尔值")
            base_set = "none" if set_id == "upload" else set_id
            illustrations = {
                "opacity": illustrations["opacity"],
                "surfaces": {
                    "workbench": bool(legacy_surfaces["workbench"] or legacy_surfaces["chat"] or legacy_surfaces["topbar"]),
                    "adminCenter": bool(legacy_surfaces["management"]),
                    "agentManager": bool(legacy_surfaces["management"]),
                },
                "scenes": {
                    surface: {
                        "layers": ([{
                            "id": f"{surface}-legacy",
                            "asset": upload_asset,
                            "anchor": "center",
                            "width": 100,
                            "height": 100,
                            "objectPosition": "50% 50%",
                            "enabled": True,
                        }] if upload_asset else [
                            {**layer, "asset": {"kind": "builtin", **layer["asset"]}}
                            for layer in catalog[base_set][surface]["layers"]
                        ]),
                    }
                    for surface in _ILLUSTRATION_SURFACES
                },
            }
        opacity = illustrations["opacity"]
        if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not math.isfinite(opacity) or not 0 <= opacity <= 1:
            _invalid("illustrations.opacity 必须是 0 到 1 之间的数字")
        surfaces = _object(illustrations["surfaces"], set(_ILLUSTRATION_SURFACES), set(_ILLUSTRATION_SURFACES), "illustrations.surfaces")
        if any(type(surfaces[surface]) is not bool for surface in _ILLUSTRATION_SURFACES):
            _invalid("illustrations.surfaces 的值必须是布尔值")
        scenes = _object(illustrations["scenes"], set(_ILLUSTRATION_SURFACES), set(_ILLUSTRATION_SURFACES), "illustrations.scenes")
        normalized_scenes: dict[str, Any] = {}
        uploaded_sizes: dict[str, int] = {}
        for surface in _ILLUSTRATION_SURFACES:
            raw_scene = scenes[surface]
            legacy_set_id = ""
            if isinstance(raw_scene, dict) and "layers" not in raw_scene and "kind" in raw_scene:
                if raw_scene.get("kind") == "builtin":
                    legacy_set_id = _legacy_illustration_set_id(raw_scene.get("assetId"), surface)
                if legacy_set_id:
                    raw_scene = {
                        "layers": [
                            {**layer, "asset": {"kind": "builtin", **layer["asset"]}}
                            for layer in catalog[legacy_set_id][surface]["layers"]
                        ],
                    }
                else:
                    raw_scene = {
                        "layers": [{
                            "id": f"{surface}-legacy",
                            "asset": raw_scene,
                            "anchor": "center",
                            "width": 100,
                            "height": 100,
                            "objectPosition": "50% 50%",
                            "enabled": True,
                        }],
                    }
            elif isinstance(raw_scene, dict) and isinstance(raw_scene.get("layers"), list) and len(raw_scene["layers"]) == 1:
                first_layer = raw_scene["layers"][0]
                first_asset = first_layer.get("asset") if isinstance(first_layer, dict) else None
                if isinstance(first_asset, dict) and first_asset.get("kind") == "builtin":
                    legacy_set_id = _legacy_illustration_set_id(first_asset.get("assetId"), surface)
                    if legacy_set_id:
                        raw_scene = {
                            "layers": [
                                {**layer, "asset": {"kind": "builtin", **layer["asset"]}}
                                for layer in catalog[legacy_set_id][surface]["layers"]
                            ],
                        }
            scene = _object(raw_scene, {"layers"}, {"layers"}, f"illustrations.scenes.{surface}")
            layers = scene["layers"]
            if not isinstance(layers, list) or not layers or len(layers) > 32:
                _invalid(f"illustrations.scenes.{surface}.layers 必须包含 1 到 32 个图层")
            normalized_layers = []
            layer_ids: set[str] = set()
            for index, raw_layer in enumerate(layers):
                layer = _object(
                    raw_layer,
                    {"id", "asset", "anchor", "x", "y", "width", "height", "objectPosition", "opacity", "enabled"},
                    {"id", "asset", "anchor", "enabled"},
                    f"illustrations.scenes.{surface}.layers[{index}]",
                )
                if not isinstance(layer["id"], str) or not _ILLUSTRATION_LAYER_ID.fullmatch(layer["id"]) or layer["id"] in layer_ids:
                    _invalid("主题插画图层 ID 无效")
                layer_ids.add(layer["id"])
                if layer["anchor"] not in _ILLUSTRATION_ANCHORS or type(layer["enabled"]) is not bool:
                    _invalid("主题插画图层定位无效")
                for key, minimum, maximum in (("x", -100, 100), ("y", -100, 100), ("width", 0.01, 300), ("height", 0.01, 300), ("opacity", 0, 1)):
                    if key in layer and (isinstance(layer[key], bool) or not isinstance(layer[key], (int, float)) or not math.isfinite(layer[key]) or not minimum <= layer[key] <= maximum):
                        _invalid("主题插画图层定位无效")
                if "objectPosition" in layer and (not isinstance(layer["objectPosition"], str) or len(layer["objectPosition"]) > 120):
                    _invalid("主题插画图层 objectPosition 无效")

                asset = _object(
                    layer["asset"],
                    {"kind", "assetId", "mimeType", "width", "height", "sha256"},
                    {"kind", "assetId", "mimeType", "width", "height", "sha256"},
                    f"illustrations.scenes.{surface}.layers[{index}].asset",
                )
                if asset["kind"] == "builtin":
                    match = next((item["asset"] for resources in catalog.values() for scene_data in resources.values() for item in scene_data["layers"] if item["asset"]["assetId"] == asset["assetId"]), None)
                    if match is None or any(asset[key] != match[key] for key in ("mimeType", "width", "height", "sha256")):
                        _invalid("内置场景插画元数据无效")
                    normalized_asset = {"kind": "builtin", **match}
                elif asset["kind"] == "uploaded":
                    try:
                        staged = asset_overrides.get(asset["assetId"]) if asset_overrides else None
                        if staged is not None:
                            normalized_asset, raw = staged
                            actual = self.asset_store.describe(raw, asset["mimeType"])
                            if any(asset[key] != actual[key] for key in ("assetId", "mimeType", "width", "height", "sha256")):
                                _invalid("主题引用的插画哈希或尺寸不匹配", "theme_asset_integrity_invalid")
                            size = len(raw)
                        else:
                            normalized_asset, size = self.asset_store.validate(asset)
                    except ThemeAssetStoreError as exc:
                        raise ThemeStoreError(exc.status, exc.code, exc.message, exc.data) from exc
                    uploaded_sizes[normalized_asset["assetId"]] = size
                else:
                    _invalid("场景插画资源类型无效")
                normalized_layers.append({
                    key: layer[key] for key in ("id", "anchor", "x", "y", "width", "height", "objectPosition", "opacity", "enabled") if key in layer
                } | {"asset": normalized_asset})
            normalized_scenes[surface] = {"layers": normalized_layers}
        if sum(uploaded_sizes.values()) > MAX_THEME_ASSET_TOTAL_BYTES:
            _invalid("单个主题的插画资源总量不能超过 12 MiB", "theme_asset_total_too_large")
        return {
            "opacity": opacity,
            "surfaces": {surface: surfaces[surface] for surface in _ILLUSTRATION_SURFACES},
            "scenes": normalized_scenes,
        }

    def _appearance(
        self,
        value: Any,
        *,
        asset_overrides: dict[str, tuple[dict[str, Any], bytes]] | None = None,
    ) -> dict[str, Any]:
        appearance = _object(value, {"colors", "typography", "material", "illustrations"}, {"colors"}, "appearance")
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
        if "material" in appearance:
            material = _object(
                appearance["material"],
                set(_THEME_MATERIAL_VALUES),
                set(_THEME_MATERIAL_VALUES),
                "material",
            )
            for key, choices in _THEME_MATERIAL_VALUES.items():
                if not isinstance(material[key], str) or material[key] not in choices:
                    _invalid(f"material.{key} 包含不支持的值")
            result["material"] = {key: material[key] for key in _THEME_MATERIAL_VALUES}
        result["illustrations"] = self._illustrations_value(
            appearance.get("illustrations"), asset_overrides=asset_overrides,
        )
        return result

    def _read_file(self, path: Path, *, legacy: bool = False, presets: bool = False) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            if isinstance(exc, FileNotFoundError) and not legacy:
                return None
            raise ThemeStoreError(500, "theme_store_unreadable", "主题库文件无法读取，原文件已保留，请修复后重试") from exc
        try:
            fields = {"schemaVersion", "revision", "selectedThemeId", "themes"}
            required = set(fields)
            fields.add("selectedThemeIds")
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
            if "selectedThemeIds" in data:
                _selection_map(data["selectedThemeIds"])
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
            ids = set() if presets else {BUILTIN_THEME_ID}
            fields = {"schemaVersion", "id", "name", "baseId", "appearance", "readonly", "updatedAt", "version"}
            for theme in data["themes"]:
                _object(theme, fields, fields, "主题")
                _schema(theme["schemaVersion"])
                theme_id = theme["id"]
                valid_id = theme_id == BUILTIN_THEME_ID or (isinstance(theme_id, str) and _THEME_ID.fullmatch(theme_id))
                if not isinstance(theme_id, str) or not valid_id or theme_id in ids:
                    _invalid("主题 ID 无效或重复")
                ids.add(theme_id)
                expected_readonly = True if presets else False
                if theme["baseId"] != BUILTIN_THEME_ID or theme["readonly"] is not expected_readonly:
                    _invalid("预置主题属性无效" if presets else "自定义主题属性无效")
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

    def _preset_library(self) -> dict[str, Any]:
        data = self._read_file(self.presets_path, presets=True)
        if data is None:
            raise ThemeStoreError(500, "theme_catalog_unavailable", "预置主题目录无法读取，请检查应用安装文件")
        if BUILTIN_THEME_ID not in {theme["id"] for theme in data["themes"]}:
            raise ThemeStoreError(500, "theme_catalog_unavailable", "预置主题目录缺少默认主题")
        data["revision"] = 0
        return data

    def _read_selection(self) -> tuple[int, str, dict[str, str]]:
        try:
            raw = self.library_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                _invalid("主题库结构无效")
            _schema(data.get("schemaVersion"))
            if data.get("scope", "global") != "global":
                _invalid("主题库 scope 必须为 global")
            revision = _revision(data.get("revision", 0))
            selected = data.get("selectedThemeId", BUILTIN_THEME_ID)
            if not isinstance(selected, str):
                _invalid("主题库 selectedThemeId 必须是字符串")
            selections = _selection_map(data["selectedThemeIds"]) if "selectedThemeIds" in data else {}
            return revision, selected, selections
        except FileNotFoundError:
            return 0, BUILTIN_THEME_ID, {}
        except (OSError, UnicodeError, ValueError, ThemeStoreError) as exc:
            detail = str(exc)
            raise ThemeStoreError(500, "theme_store_unreadable", f"主题库文件无法使用，原文件已保留，请修复后重试：{detail}") from exc

    def _read(self) -> dict[str, Any]:
        data = self._preset_library()
        if self.library_path.exists():
            revision, selected, selections = self._read_selection()
            data["revision"] = revision
            if selected in {theme["id"] for theme in data["themes"]}:
                data["selectedThemeId"] = selected
            if selections:
                data["selectedThemeIds"] = selections
        return data

    @staticmethod
    def _library(data: dict[str, Any], account_id: str | None = None) -> dict[str, Any]:
        library = copy.deepcopy(data)
        selections = library.pop("selectedThemeIds", {})
        if account_id and isinstance(selections, dict):
            selected = selections.get(account_id)
            theme_ids = {theme["id"] for theme in library["themes"]}
            if selected in theme_ids:
                library["selectedThemeId"] = selected
        library.pop("builtinTheme", None)
        return library

    def list_library(self, account_id: str | None = None) -> dict[str, Any]:
        with _STORE_LOCK:
            try:
                return self._library(self._read(), account_id)
            except ThemeStoreError as exc:
                if exc.code != "theme_store_unreadable":
                    raise
                try:
                    fallback = self._library(self._preset_library(), account_id)
                except ThemeStoreError:
                    fallback = builtin_library()
                return {**fallback, "error": exc.message}

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
                change: Callable[[dict[str, Any]], None],
                account_id: str | None = None) -> dict[str, Any]:
        expected_revision = _revision(expected_revision)
        with _STORE_LOCK:
            data = self._read()
            if data["revision"] != expected_revision:
                raise ThemeStoreError(409, "theme_revision_conflict", "主题库已在其他页面更新，请重新加载后再保存",
                                      {"revision": data["revision"]})
            change(data)
            data["revision"] += 1
            self._write(self.library_path, data)
            return self._library(data, account_id)

    def _find(self, data: dict[str, Any], theme_id: Any, *, writable: bool = False) -> dict[str, Any]:
        for theme in data["themes"]:
            if theme["id"] == theme_id:
                return theme
        if theme_id == BUILTIN_THEME_ID:
            return builtin_library(data.get("builtinTheme"))["themes"][0]
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
        raise ThemeStoreError(403, "theme_readonly", THEME_READONLY_MESSAGE)

    def import_themes(self, payload: Any) -> dict[str, Any]:
        raise ThemeStoreError(403, "theme_readonly", THEME_READONLY_MESSAGE)

    def update(self, theme_id: str, payload: Any) -> dict[str, Any]:
        raise ThemeStoreError(403, "theme_readonly", THEME_READONLY_MESSAGE)

    def delete(self, theme_id: str, payload: Any) -> dict[str, Any]:
        raise ThemeStoreError(403, "theme_readonly", THEME_READONLY_MESSAGE)

    def select(self, payload: Any, account_id: str | None = None) -> dict[str, Any]:
        value = _object(payload, {"themeId", "expectedRevision"}, {"themeId", "expectedRevision"}, "应用主题请求")
        if not isinstance(value["themeId"], str):
            _invalid("themeId 必须是主题 ID")
        if account_id is not None and (not isinstance(account_id, str) or not account_id.strip()):
            _invalid("账户 ID 无效")

        def change(data):
            self._find(data, value["themeId"])
            if account_id is None:
                data["selectedThemeId"] = value["themeId"]
            else:
                selections = data.setdefault("selectedThemeIds", {})
                if not isinstance(selections, dict):
                    _invalid("主题选择映射必须是对象")
                selections[account_id] = value["themeId"]

        return self._mutate(value["expectedRevision"], change, account_id)
