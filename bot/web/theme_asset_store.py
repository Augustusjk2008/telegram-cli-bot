"""Content addressed storage and validation for UI theme illustration assets."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from bot.runtime_paths import get_theme_assets_dir

MAX_THEME_ASSET_BYTES = 4 * 1024 * 1024
MAX_THEME_ASSET_TOTAL_BYTES = 12 * 1024 * 1024
SUPPORTED_THEME_ASSET_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
_ASSET_ID = re.compile(r"asset_[0-9a-f]{64}\Z")
_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class ThemeAssetStoreError(Exception):
    def __init__(self, status: int, code: str, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data or {}


def _invalid(message: str, code: str = "invalid_theme_asset") -> None:
    raise ThemeAssetStoreError(400, code, message)


def _u24le(value: bytes) -> int:
    return int.from_bytes(value, "little")


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    _invalid("插画文件头不受支持", "theme_asset_header_invalid")


def image_dimensions(data: bytes, mime_type: str) -> tuple[int, int]:
    try:
        if mime_type == "image/png":
            if len(data) < 24 or data[12:16] != b"IHDR":
                raise ValueError
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if mime_type == "image/jpeg":
            offset = 2
            while offset + 3 < len(data):
                if data[offset] != 0xFF:
                    offset += 1
                    continue
                while offset < len(data) and data[offset] == 0xFF:
                    offset += 1
                marker = data[offset]
                offset += 1
                if marker in {0xD8, 0xD9}:
                    continue
                if offset + 2 > len(data):
                    break
                length = int.from_bytes(data[offset:offset + 2], "big")
                if length < 2 or offset + length > len(data):
                    break
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    if length < 7:
                        break
                    return int.from_bytes(data[offset + 3:offset + 5], "big"), int.from_bytes(data[offset + 5:offset + 7], "big")
                offset += length
            raise ValueError
        if mime_type == "image/webp":
            if len(data) < 30:
                raise ValueError
            chunk = data[12:16]
            if chunk == b"VP8X":
                return 1 + _u24le(data[24:27]), 1 + _u24le(data[27:30])
            if chunk == b"VP8 ":
                marker = data.find(b"\x9d\x01\x2a", 20)
                if marker >= 0 and marker + 7 < len(data):
                    return int.from_bytes(data[marker + 3:marker + 5], "little") & 0x3FFF, int.from_bytes(data[marker + 5:marker + 7], "little") & 0x3FFF
            if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
                bits = int.from_bytes(data[21:25], "little")
                return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
            raise ValueError
    except (IndexError, OverflowError):
        raise ValueError from None
    raise ValueError


class ThemeAssetStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else get_theme_assets_dir()

    def _path(self, asset_id: str, mime_type: str | None = None) -> Path:
        if not isinstance(asset_id, str) or not _ASSET_ID.fullmatch(asset_id):
            raise ThemeAssetStoreError(404, "theme_asset_not_found", "主题插画资源不存在")
        if mime_type not in _EXTENSIONS:
            for extension in _EXTENSIONS.values():
                candidate = self.root / f"{asset_id}{extension}"
                if candidate.is_file():
                    return candidate
            raise ThemeAssetStoreError(404, "theme_asset_not_found", "主题插画资源不存在")
        return self.root / f"{asset_id}{_EXTENSIONS[mime_type]}"

    @staticmethod
    def _descriptor(asset_id: str, mime_type: str, data: bytes, width: int, height: int) -> dict[str, Any]:
        return {
            "kind": "uploaded",
            "assetId": asset_id,
            "mimeType": mime_type,
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def describe(self, data: bytes, mime_type: str | None = None) -> dict[str, Any]:
        if not isinstance(data, (bytes, bytearray)):
            _invalid("上传插画数据无效")
        data = bytes(data)
        if not data or len(data) > MAX_THEME_ASSET_BYTES:
            raise ThemeAssetStoreError(413, "theme_asset_too_large", "单张插画不能超过 4 MiB")
        detected = sniff_mime(data)
        if mime_type and mime_type != detected:
            _invalid("上传插画的 MIME 与文件头不匹配", "theme_asset_mime_mismatch")
        mime_type = detected
        try:
            width, height = image_dimensions(data, mime_type)
        except ValueError:
            _invalid("无法读取插画尺寸", "theme_asset_dimensions_invalid")
        if not 1 <= width <= 10000 or not 1 <= height <= 10000:
            _invalid("插画尺寸必须在 1 到 10000 像素之间", "theme_asset_dimensions_invalid")
        digest = hashlib.sha256(data).hexdigest()
        asset_id = f"asset_{digest}"
        return self._descriptor(asset_id, mime_type, data, width, height)

    def store(self, data: bytes, mime_type: str | None = None) -> dict[str, Any]:
        descriptor = self.describe(data, mime_type)
        asset_id = descriptor["assetId"]
        mime_type = descriptor["mimeType"]
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{asset_id}{_EXTENSIONS[mime_type]}"
        if not path.exists():
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.root, prefix=".theme-asset-", suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            except OSError as exc:
                raise ThemeAssetStoreError(500, "theme_asset_write_failed", "主题插画保存失败，请重试") from exc
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
        return descriptor

    def validate(self, descriptor: Any) -> tuple[dict[str, Any], int]:
        if not isinstance(descriptor, dict) or set(descriptor) != {"kind", "assetId", "mimeType", "width", "height", "sha256"}:
            _invalid("主题引用的插画资源元数据无效")
        if descriptor.get("kind") != "uploaded":
            _invalid("上传插画资源类型无效")
        asset_id = descriptor.get("assetId")
        mime_type = descriptor.get("mimeType")
        if not isinstance(asset_id, str) or not _ASSET_ID.fullmatch(asset_id) or not isinstance(mime_type, str) or mime_type not in SUPPORTED_THEME_ASSET_MIMES:
            _invalid("上传插画资源标识无效")
        if type(descriptor.get("width")) is not int or type(descriptor.get("height")) is not int or descriptor["width"] < 1 or descriptor["height"] < 1:
            _invalid("上传插画尺寸无效")
        sha256 = descriptor.get("sha256")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256, re.I):
            _invalid("上传插画哈希无效")
        path = self._path(asset_id, mime_type)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ThemeAssetStoreError(400, "theme_asset_unavailable", "主题引用的插画资源不存在") from exc
        try:
            actual = self.describe(data, mime_type)
        except ThemeAssetStoreError as exc:
            if exc.code in {"theme_asset_too_large", "theme_asset_dimensions_invalid", "theme_asset_header_invalid"}:
                raise ThemeAssetStoreError(400, "theme_asset_integrity_invalid", "主题引用的插画资源内容无效") from exc
            raise
        if any(actual[key] != descriptor[key] for key in ("assetId", "mimeType", "width", "height", "sha256")) or sha256.lower() != actual["sha256"]:
            _invalid("主题引用的插画哈希或尺寸不匹配", "theme_asset_integrity_invalid")
        return actual, len(data)

    def read(self, asset_id: str) -> tuple[bytes, str]:
        path = self._path(asset_id)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ThemeAssetStoreError(404, "theme_asset_not_found", "主题插画资源不存在") from exc
        mime_type = sniff_mime(data)
        try:
            descriptor = self.describe(data, mime_type)
        except ThemeAssetStoreError as exc:
            raise ThemeAssetStoreError(400, "theme_asset_integrity_invalid", "主题插画资源内容无效") from exc
        if descriptor["assetId"] != asset_id:
            raise ThemeAssetStoreError(400, "theme_asset_integrity_invalid", "主题插画资源哈希与 ID 不匹配")
        return data, mime_type

