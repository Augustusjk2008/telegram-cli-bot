from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from zip_parser import build_archive_index, extract_archive  # noqa: E402


def _zip_bytes(*members: tuple[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return output.getvalue()


def _tar_gz_bytes(*members: tuple[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def _extract_to(tmp_path: Path):
    def write_bytes(path: str, content: bytes, *, overwrite: bool, error_message: str):
        target = tmp_path / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise RuntimeError(error_message)
        target.write_bytes(content)
        return {"path": path}

    def make_directory(path: str, *, error_message: str):
        del error_message
        (tmp_path / Path(path)).mkdir(parents=True, exist_ok=True)
        return {"path": path}

    return write_bytes, make_directory


def test_zip_preview_and_extract_preserve_nested_paths(tmp_path: Path) -> None:
    content = _zip_bytes(("docs/readme.txt", b"hello"), ("empty/", b""))
    index = build_archive_index("packs/sample.zip", content)

    assert index.archive_format == "zip"
    assert index.get_nodes()[0]["label"] == "docs"
    assert index.summary()["actions"][0]["id"] == "extract-here"

    write_bytes, make_directory = _extract_to(tmp_path)
    files, total, archive_format = extract_archive(
        "packs/sample.zip",
        content,
        {"maxEntries": 2000, "maxExtractBytes": 1024, "overwriteExisting": True},
        write_bytes=write_bytes,
        make_directory=make_directory,
    )

    assert (tmp_path / "packs/docs/readme.txt").read_bytes() == b"hello"
    assert (tmp_path / "packs/empty").is_dir()
    assert (files, total, archive_format) == (1, 5, "zip")


def test_tar_gz_preview_and_extract(tmp_path: Path) -> None:
    content = _tar_gz_bytes(("src/main.py", b"print(1)"))
    index = build_archive_index("packs/source.tar.gz", content)
    assert index.archive_format == "tar"

    write_bytes, make_directory = _extract_to(tmp_path)
    extract_archive(
        "packs/source.tar.gz",
        content,
        write_bytes=write_bytes,
        make_directory=make_directory,
    )
    assert (tmp_path / "packs/src/main.py").read_bytes() == b"print(1)"


def test_standalone_gzip_extracts_next_to_source(tmp_path: Path) -> None:
    import gzip

    content = gzip.compress(b"plain text")
    index = build_archive_index("packs/readme.txt.gz", content)
    assert [node["label"] for node in index.get_nodes()] == ["readme.txt"]

    write_bytes, make_directory = _extract_to(tmp_path)
    extract_archive("packs/readme.txt.gz", content, write_bytes=write_bytes, make_directory=make_directory)
    assert (tmp_path / "packs/readme.txt").read_bytes() == b"plain text"


def test_archive_paths_cannot_escape_destination() -> None:
    content = _zip_bytes(("../outside.txt", b"unsafe"))
    with pytest.raises(RuntimeError, match="不安全路径"):
        build_archive_index("sample.zip", content)
