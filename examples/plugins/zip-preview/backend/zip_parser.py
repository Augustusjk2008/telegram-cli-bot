from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ZipMember:
    path: str
    ordinal: int
    size: int
    compressed_size: int


def _file_node(member: ZipMember) -> dict[str, object]:
    path, size, compressed = member.path, member.size, member.compressed_size
    current_path = PurePosixPath(path)
    parent = str(current_path.parent)
    return {
        "id": f"file:{member.ordinal}:{path}",
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
    return sorted(nodes, key=lambda item: (item.get("kind") != "folder", str(item.get("label") or "").lower()))


@dataclass(frozen=True)
class ZipIndex:
    path: str
    children: dict[str, list[str | ZipMember]]
    stats_text: str

    def get_nodes(self, node_id: str | None = None) -> list[dict[str, object]]:
        folder_path = ""
        if node_id is not None:
            if not node_id.startswith("dir:") or not node_id[4:] or node_id[4:] not in self.children:
                raise RuntimeError("ZIP 目录节点不存在")
            folder_path = node_id[4:]
        return _sorted_nodes([
            _folder_node(item, PurePosixPath(item).name) if isinstance(item, str) else _file_node(item)
            for item in self.children[folder_path]
        ])

    def summary(self) -> dict[str, object]:
        return {
            "path": self.path,
            "roots": self.get_nodes(),
            "statsText": self.stats_text,
            "searchable": False,
            "emptySearchText": "压缩包为空",
        }

    def snapshot(self) -> dict[str, object]:
        payload = self.summary()
        pending = list(payload["roots"])
        while pending:
            node = pending.pop()
            if node.get("kind") == "folder":
                nodes = self.get_nodes(str(node["id"]))
                node["children"] = nodes
                pending.extend(nodes)
        return payload


def build_zip_index(path: str, content: bytes, config: dict[str, object] | None = None) -> ZipIndex:
    max_entries = _clamp_int((config or {}).get("maxEntries"), DEFAULT_MAX_ENTRIES, 100, 10000)
    try:
        with ZipFile(BytesIO(content)) as archive:
            files = [
                (ordinal, info) for ordinal, info in enumerate(archive.infolist())
                if info.filename and not info.filename.endswith("/")
            ]
    except BadZipFile as exc:
        raise RuntimeError("ZIP 文件损坏或格式不支持") from exc

    truncated = len(files) > max_entries
    files = files[:max_entries]

    children: dict[str, list[str | ZipMember]] = {"": []}
    for ordinal, info in files:
        member_path = PurePosixPath(info.filename)
        for folder in reversed(member_path.parents):
            folder_path = str(folder)
            if not folder.name or folder_path in children:
                continue
            parent_path = str(folder.parent)
            children[parent_path if parent_path in children else ""].append(folder_path)
            children[folder_path] = []
        parent_path = str(member_path.parent)
        children[parent_path if parent_path in children else ""].append(
            ZipMember(str(member_path), ordinal, info.file_size, info.compress_size)
        )

    stats_text = f"{len(files)} 文件 · {len(children) - 1} 文件夹"
    if truncated:
        stats_text += f" · 仅预览前 {max_entries} 项"

    return ZipIndex(path, children, stats_text)


def parse_zip_tree(path: str, content: bytes, config: dict[str, object] | None = None) -> dict[str, object]:
    return build_zip_index(path, content, config).snapshot()
