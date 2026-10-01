from __future__ import annotations

import base64
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class CsvSourceIdentity:
    source_path: str
    file_size: int
    mtime_ns: str
    sha256: str


@dataclass
class TemporaryCsvSource:
    identity: CsvSourceIdentity
    temporary_path: Path
    directory: tempfile.TemporaryDirectory

    def close(self) -> None:
        self.directory.cleanup()


def copy_csv_source(
    path: str,
    context: dict[str, Any],
    call_host: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> TemporaryCsvSource:
    directory = tempfile.TemporaryDirectory(prefix="csv-preview-")
    temporary_path = Path(directory.name) / "source.csv"
    try:
        identity_parts: tuple[str, int, str] | None = None
        offset = 0
        digest = hashlib.sha256()
        read_limit = ((context.get("host") or {}).get("limits") or {}).get("readBytes")
        with temporary_path.open("wb") as handle:
            while True:
                response = call_host(
                    "host.workspace.read_range",
                    {"path": path, "offset": offset, "length": READ_CHUNK_BYTES},
                )
                if response.get("error"):
                    raise RuntimeError(
                        str(response["error"].get("message") or "读取 CSV 失败")
                    )
                result = response.get("result") or {}
                size = result.get("fileSizeBytes")
                if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                    raise ValueError("CSV 分段读取返回无效的文件大小")
                if read_limit is not None and size > int(read_limit):
                    raise ValueError(f"文件超过插件读取限额: {size} > {read_limit}")
                current = (
                    str(result.get("path") or path),
                    size,
                    str(result.get("mtimeNs") or ""),
                )
                if identity_parts is not None and identity_parts != current:
                    raise ValueError("CSV 源文件在读取过程中发生变化，请重新打开")
                identity_parts = current
                try:
                    content = base64.b64decode(
                        str(result.get("contentBase64") or ""), validate=True
                    )
                except ValueError as exc:
                    raise ValueError("CSV 分段读取返回无效的 base64 数据") from exc
                if (
                    result.get("offset") != offset
                    or result.get("length") != len(content)
                    or len(content) > READ_CHUNK_BYTES
                ):
                    raise ValueError("CSV 分段读取返回无效的数据块")
                if offset + len(content) > size or bool(result.get("eof")) != (
                    offset + len(content) == size
                ):
                    raise ValueError("CSV 分段读取不完整")
                if not content and not result.get("eof"):
                    raise ValueError("CSV 分段读取不完整")
                handle.write(content)
                digest.update(content)
                offset += len(content)
                if result.get("eof"):
                    break
        if identity_parts is None:
            raise ValueError("CSV 分段读取没有返回文件身份")
        return TemporaryCsvSource(
            CsvSourceIdentity(*identity_parts, digest.hexdigest()),
            temporary_path,
            directory,
        )
    except BaseException:
        directory.cleanup()
        raise
