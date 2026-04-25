from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

DEFAULT_MAX_ENTRIES = 2000


def _clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _folder_node(path: str, label: str) -> dict[str, object]:
    return {
        "id": f"dir:{path}",
        "label": label,
        "kind": "folder",
        "hasChildren": True,
        "expandable": True,
        "children": [],
    }


def _file_node(path: str, size: int, compressed: int) -> dict[str, object]:
    current_path = PurePosixPath(path)
    parent = str(current_path.parent)
    return {
        "id": f"file:{path}",
        "label": current_path.name,
        "kind": "file",
        "secondaryText": "" if parent == "." else parent,
        "badges": [
            {"text": _size_label(size), "tone": "info"},
            {"text": f"zip {_size_label(compressed)}"},
        ],
        "payload": {
            "path": path,
            "size": size,
            "compressedSize": compressed,
        },
    }


def _sorted_nodes(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for node in sorted(nodes, key=lambda item: (item.get("kind") != "folder", str(item.get("label") or "").lower())):
        children = node.get("children")
        if isinstance(children, list) and children:
            node = {**node, "children": _sorted_nodes(children)}
        result.append(node)
    return result


def parse_zip_tree(path: str, content: bytes, config: dict[str, object] | None = None) -> dict[str, object]:
    max_entries = _clamp_int((config or {}).get("maxEntries"), DEFAULT_MAX_ENTRIES, 100, 10000)
    try:
        with ZipFile(BytesIO(content)) as archive:
            files = [info for info in archive.infolist() if info.filename and not info.filename.endswith("/")]
    except BadZipFile as exc:
        raise RuntimeError("ZIP 文件损坏或格式不支持") from exc

    truncated = len(files) > max_entries
    files = files[:max_entries]

    roots: list[dict[str, object]] = []
    folder_children: dict[str, list[dict[str, object]]] = {"": roots}
    folder_nodes: dict[str, dict[str, object]] = {}
    folder_count = 0

    def ensure_folder(folder_path: str) -> dict[str, object]:
        nonlocal folder_count
        clean_path = str(PurePosixPath(folder_path))
        if clean_path in {"", "."}:
            raise RuntimeError("ZIP 目录路径无效")
        existing = folder_nodes.get(clean_path)
        if existing is not None:
            return existing

        parent_path = str(PurePosixPath(clean_path).parent)
        if parent_path == ".":
          parent_path = ""
        parent_children = folder_children.setdefault(parent_path, roots if parent_path == "" else [])
        if parent_path and parent_path not in folder_nodes:
            ensure_folder(parent_path)
            parent_children = folder_children[parent_path]

        node = _folder_node(clean_path, PurePosixPath(clean_path).name)
        parent_children.append(node)
        folder_nodes[clean_path] = node
        folder_children[clean_path] = node["children"]  # type: ignore[assignment]
        folder_count += 1
        return node

    for info in files:
        clean_path = str(PurePosixPath(info.filename))
        parent_path = str(PurePosixPath(clean_path).parent)
        if parent_path != ".":
            ensure_folder(parent_path)
        children = folder_children["" if parent_path == "." else parent_path]
        children.append(_file_node(clean_path, info.file_size, info.compress_size))

    stats_text = f"{len(files)} 文件 · {folder_count} 文件夹"
    if truncated:
        stats_text += f" · 仅预览前 {max_entries} 项"

    return {
        "path": path,
        "roots": _sorted_nodes(roots),
        "statsText": stats_text,
        "searchable": False,
        "emptySearchText": "压缩包为空",
    }
