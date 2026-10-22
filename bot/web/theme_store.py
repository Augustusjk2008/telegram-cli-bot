"""Personal UI themes, scoped to authenticated accounts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bot.runtime_paths import get_theme_accounts_dir

BUILTIN_THEME_ID = "paper-daylight"
_THEME_ID = re.compile(r"theme_[0-9a-f]{32}\Z")
_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")
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


def builtin_library() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "revision": 0,
        "selectedThemeId": BUILTIN_THEME_ID,
        "themes": [{
            "schemaVersion": 1,
            "id": BUILTIN_THEME_ID,
            "name": "纸感日间",
            "baseId": BUILTIN_THEME_ID,
            "appearance": {"colors": {"scheme": "light", "overrides": {}}},
            "readonly": True,
            "updatedAt": "1970-01-01T00:00:00Z",
            "version": 1,
        }],
    }


class ThemeStore:
    def __init__(self, accounts_dir: Path | None = None, *, catalog_path: Path | None = None):
        self.accounts_dir = Path(accounts_dir) if accounts_dir is not None else get_theme_accounts_dir()
        self.catalog_path = catalog_path or Path(__file__).with_name("theme_catalog.json")

    def _account_path(self, account_id: str) -> Path:
        if not isinstance(account_id, str) or not account_id.strip() or account_id == "guest":
            raise ThemeStoreError(403, "theme_readonly", "请登录正式账户后管理个人主题")
        filename = hashlib.sha256(account_id.encode("utf-8")).hexdigest() + ".json"
        return self.accounts_dir / filename

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

    def _appearance(self, value: Any) -> dict[str, Any]:
        appearance = _object(value, {"colors"}, {"colors"}, "appearance")
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
        return {"colors": {"scheme": colors["scheme"], "overrides": normalized}}

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"schemaVersion": 1, "revision": 0, "selectedThemeId": BUILTIN_THEME_ID, "themes": []}
        except (OSError, UnicodeError) as exc:
            raise ThemeStoreError(500, "theme_store_unreadable", "个人主题文件无法读取，原文件已保留，请修复后重试") from exc
        try:
            data = _object(json.loads(raw), {"schemaVersion", "revision", "selectedThemeId", "themes"},
                           {"schemaVersion", "revision", "selectedThemeId", "themes"}, "主题库")
            _schema(data["schemaVersion"])
            _revision(data["revision"])
            if not isinstance(data["themes"], list) or not isinstance(data["selectedThemeId"], str):
                _invalid("主题库结构无效")
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
                theme["name"] = _name(theme["name"])
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
            raise ThemeStoreError(500, "theme_store_unreadable", f"个人主题文件无法使用，原文件已保留，请修复后重试：{detail}") from exc

    @staticmethod
    def _library(data: dict[str, Any]) -> dict[str, Any]:
        library = copy.deepcopy(data)
        library["themes"].insert(0, builtin_library()["themes"][0])
        return library

    def list_for_account(self, account_id: str, *, guest: bool = False) -> dict[str, Any]:
        if guest or account_id == "guest":
            return builtin_library()
        with _STORE_LOCK:
            try:
                return self._library(self._read(self._account_path(account_id)))
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
            raise ThemeStoreError(500, "theme_store_write_failed", "个人主题保存失败，已有主题保持不变，请重试") from exc
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()

    def _mutate(self, account_id: str, expected_revision: Any,
                change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        expected_revision = _revision(expected_revision)
        path = self._account_path(account_id)
        with _STORE_LOCK:
            data = self._read(path)
            if data["revision"] != expected_revision:
                raise ThemeStoreError(409, "theme_revision_conflict", "主题库已在其他页面更新，请重新加载后再保存",
                                      {"revision": data["revision"]})
            change(data)
            data["revision"] += 1
            self._write(path, data)
            return self._library(data)

    @staticmethod
    def _find(data: dict[str, Any], theme_id: Any, *, writable: bool = False) -> dict[str, Any]:
        if theme_id == BUILTIN_THEME_ID:
            if writable:
                raise ThemeStoreError(403, "theme_readonly", "内置纸感日间是只读主题，请复制后编辑")
            return builtin_library()["themes"][0]
        for theme in data["themes"]:
            if theme["id"] == theme_id:
                return theme
        raise ThemeStoreError(404, "theme_not_found", "个人主题不存在")

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

    def create(self, account_id: str, payload: Any) -> dict[str, Any]:
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

        return self._mutate(account_id, value["expectedRevision"], change)

    def update(self, account_id: str, theme_id: str, payload: Any) -> dict[str, Any]:
        value = self._input(payload, create=False)

        def change(data):
            theme = self._find(data, theme_id, writable=True)
            if "name" in value:
                theme["name"] = _name(value["name"])
            if "appearance" in value:
                theme["appearance"] = self._appearance(value["appearance"])
            theme["version"] += 1
            theme["updatedAt"] = datetime.now(timezone.utc).isoformat()
            if value.get("activate", False):
                data["selectedThemeId"] = theme_id

        return self._mutate(account_id, value["expectedRevision"], change)

    def delete(self, account_id: str, theme_id: str, payload: Any) -> dict[str, Any]:
        value = _object(payload, {"expectedRevision"}, {"expectedRevision"}, "删除主题请求")

        def change(data):
            data["themes"].remove(self._find(data, theme_id, writable=True))
            if data["selectedThemeId"] == theme_id:
                data["selectedThemeId"] = BUILTIN_THEME_ID

        return self._mutate(account_id, value["expectedRevision"], change)

    def select(self, account_id: str, payload: Any) -> dict[str, Any]:
        value = _object(payload, {"themeId", "expectedRevision"}, {"themeId", "expectedRevision"}, "应用主题请求")
        if not isinstance(value["themeId"], str):
            _invalid("themeId 必须是主题 ID")

        def change(data):
            self._find(data, value["themeId"])
            data["selectedThemeId"] = value["themeId"]

        return self._mutate(account_id, value["expectedRevision"], change)
