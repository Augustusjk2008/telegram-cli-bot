from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path


REQUIRED_RELEASE_LEGAL_FILES = (
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "CONTRIBUTING.md",
    "front/dist/THIRD_PARTY_LICENSES.txt",
)
PORTABLE_RUNTIME_LICENSE_FILES = (
    "runtime/python/LICENSE.txt",
    "runtime/node/LICENSE",
    "tools/git/LICENSE.txt",
)


def _normalize_archive_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip("/")


def archive_file_members(archive_path: Path) -> set[str]:
    suffixes = [suffix.lower() for suffix in archive_path.suffixes]
    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            return {
                normalized
                for info in archive.infolist()
                if not info.is_dir() and (normalized := _normalize_archive_path(info.filename))
            }
    if suffixes[-2:] == [".tar", ".gz"] or archive_path.suffix.lower() == ".tgz":
        with tarfile.open(archive_path, "r:gz") as archive:
            return {
                normalized
                for info in archive.getmembers()
                if info.isfile() and (normalized := _normalize_archive_path(info.name))
            }
    raise ValueError(f"不支持的发布归档格式: {archive_path}")


def missing_release_legal_files(archive_path: Path) -> list[str]:
    members = archive_file_members(archive_path)
    required = list(REQUIRED_RELEASE_LEGAL_FILES)
    if any(
        member.startswith(("runtime/python/", "runtime/node/", "tools/git/"))
        for member in members
    ):
        required.extend(PORTABLE_RUNTIME_LICENSE_FILES)
    return [path for path in required if path not in members]


def main(argv: list[str] | None = None) -> int:
    archive_values = list(argv if argv is not None else sys.argv[1:])
    if not archive_values:
        print("用法: verify_release_legal_files.py <archive> [archive ...]", file=sys.stderr)
        return 2

    failed = False
    for value in archive_values:
        archive_path = Path(value).resolve()
        if not archive_path.is_file():
            print(f"[错误] 发布归档不存在或不是文件: {archive_path}", file=sys.stderr)
            failed = True
            continue
        try:
            missing = missing_release_legal_files(archive_path)
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
            print(f"[错误] 无法检查发布归档 {archive_path}: {exc}", file=sys.stderr)
            failed = True
            continue
        if missing:
            print(
                f"[错误] 发布归档缺少法律文件 {archive_path.name}: {', '.join(missing)}",
                file=sys.stderr,
            )
            failed = True
        else:
            print(f"[信息] 发布归档法律文件完整: {archive_path.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
