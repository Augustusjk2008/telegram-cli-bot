"""Host-backed HDL scanning and a static index; no local workspace I/O."""

from __future__ import annotations

import base64
from collections import deque
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import ntpath
import posixpath
from typing import Callable

from hdl_models import Diagnostic, IncludeDirective, Instance, Module, ParseResult, SourceLocation
from hdl_parser import HdlParser


HDL_EXTENSIONS = {".v", ".sv", ".vh", ".svh"}
DEFAULT_IGNORE_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".tcb", ".codegraph", ".tmp", ".venv", "venv",
    "__pycache__", "node_modules", "vendor", "site-packages", "build", "dist", "out", "target",
})
READ_CHUNK_BYTES = 1024 * 1024
HostCall = Callable[[str, dict], dict]


@dataclass(frozen=True)
class ScanOptions:
    top_modules: tuple[str, ...] = ()
    ignore_directories: frozenset[str] = DEFAULT_IGNORE_DIRECTORIES
    include_directories: tuple[str, ...] = ()
    max_files: int = 1000
    max_file_bytes: int = 4 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        for value in (self.max_files, self.max_file_bytes, self.max_total_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("HDL 扫描限额必须为正整数")

    @classmethod
    def from_config(cls, config: dict) -> ScanOptions:
        def names(key: str, default=()) -> tuple[str, ...]:
            value = config.get(key, default)
            if isinstance(value, str):
                value = value.split(",")
            if not isinstance(value, (tuple, list, frozenset)) or any(not isinstance(item, str) for item in value):
                raise ValueError(f"{key} 必须为字符串或字符串列表")
            return tuple(item.strip() for item in value if item.strip())

        return cls(
            top_modules=names("topModule"),
            ignore_directories=frozenset(name.casefold() for name in names("ignoreDirectories", tuple(DEFAULT_IGNORE_DIRECTORIES))),
            include_directories=names("includeDirectories"),
            max_files=config.get("maxFiles", 1000),
            max_file_bytes=config.get("maxFileBytes", 4 * 1024 * 1024),
            max_total_bytes=config.get("maxTotalBytes", 64 * 1024 * 1024),
        )


class WorkspacePaths:
    @staticmethod
    def normalize(value: str) -> str:
        text = value.replace("\\", "/")
        drive, tail = ntpath.splitdrive(text)
        if drive and (tail.startswith("/") or drive.startswith("//") and not tail):
            return drive + "/" + posixpath.normpath(tail or "/").lstrip("/")
        return posixpath.normpath(text)

    def __init__(self, root: str) -> None:
        self.root = self.normalize(root)
        drive, tail = ntpath.splitdrive(self.root)
        if not self.root.startswith("/") and not (drive and tail.startswith("/")):
            raise ValueError("Host 必须提供绝对 workspaceRoot")
        self.windows = bool(drive)

    def key(self, path: str) -> str:
        return path.casefold() if self.windows else path

    def absolute(self, base: str, value: str) -> str:
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError("HDL 路径无效")
        text = value.replace("\\", "/")
        drive, tail = ntpath.splitdrive(text)
        if drive and not tail.startswith("/") and not (drive.startswith("//") and not tail):
            raise ValueError(f"不支持驱动器相对路径：{value}")
        path = self.normalize(text if drive or text.startswith("/") else posixpath.join(base, text))
        root_key, path_key = self.key(self.root), self.key(path)
        if path_key != root_key and not path_key.startswith(root_key.rstrip("/") + "/"):
            raise ValueError(f"路径越界：{value}")
        return path


@dataclass(frozen=True)
class SourceFile:
    path: str
    size_bytes: int
    mtime_ns: str
    sha256: str
    result: ParseResult


@dataclass(frozen=True)
class IncludeResolution:
    source_path: str
    directive: IncludeDirective
    target_path: str | None
    status: str


@dataclass(frozen=True)
class InstanceReference:
    id: str
    owner_id: str
    instance: Instance
    candidate_ids: tuple[str, ...]
    status: str


def path_location(path: str) -> SourceLocation:
    return SourceLocation(path, 1, 1, 1, 1, 0, 0)


def cycle_edges(edges: dict[str, list[tuple[str, object]]]):
    """Yield DFS back edges without recursion or expanding instance paths."""
    colors: dict[str, int] = {}
    for root in edges:
        if colors.get(root):
            continue
        colors[root] = 1
        path = [root]
        active = {root: 0}
        stack = [(root, iter(edges[root]))]
        while stack:
            owner, children = stack[-1]
            edge = next(children, None)
            if edge is None:
                stack.pop()
                colors[owner] = 2
                active.pop(owner)
                path.pop()
                continue
            target, payload = edge
            if colors.get(target) == 1:
                yield tuple(path[active[target]:] + [target]), payload
            elif not colors.get(target) and target in edges:
                colors[target] = 1
                active[target] = len(path)
                path.append(target)
                stack.append((target, iter(edges[target])))


class ProjectIndex:
    def __init__(
        self, root_path: str, files: tuple[SourceFile, ...], includes: tuple[IncludeResolution, ...],
        diagnostics: list[Diagnostic], options: ScanOptions, *, scanned_file_count: int,
        source_bytes: int, incomplete: bool,
    ) -> None:
        self.root_path = root_path
        self.files = files
        self.includes = includes
        self.options = options
        self.scanned_file_count = scanned_file_count
        self.source_bytes = source_bytes
        self.incomplete = incomplete
        self._diagnostics = list(diagnostics)
        self.definitions: dict[str, Module] = {
            f"module:{file.path}:{module.location.start_byte}": module
            for file in files for module in file.result.modules
        }
        by_name: dict[str, list[str]] = {}
        for definition_id, module in self.definitions.items():
            by_name.setdefault(module.name, []).append(definition_id)
        self.modules_by_name = {name: tuple(ids) for name, ids in by_name.items()}
        for name, ids in self.modules_by_name.items():
            if len(ids) > 1:
                self._warn("duplicate_module", f"模块 {name} 有 {len(ids)} 个静态定义，保留全部候选", self.definitions[ids[0]].location)
        self.references: dict[str, InstanceReference] = {}
        self.references_by_owner: dict[str, tuple[InstanceReference, ...]] = {}
        referenced: set[str] = set()
        edges: dict[str, list[tuple[str, object]]] = {key: [] for key in self.definitions}
        for owner_id, module in self.definitions.items():
            references = []
            for instance in module.instances:
                candidates = self.modules_by_name.get(instance.module_name, ())
                status = "missing" if not candidates else "resolved" if len(candidates) == 1 else "ambiguous"
                reference_id = f"instance:{owner_id}:{instance.location.start_byte}"
                reference = InstanceReference(reference_id, owner_id, instance, candidates, status)
                self.references[reference_id] = reference
                references.append(reference)
                referenced.update(candidates)
                edges[owner_id].extend((target, reference) for target in candidates)
                if not candidates:
                    self._warn("missing_module", f"静态引用 {instance.module_name} 未找到模块定义（{instance.reference_kind}）", instance.location)
            self.references_by_owner[owner_id] = tuple(references)
        self.candidate_top_ids = tuple(key for key in self.definitions if key not in referenced)
        self.selected_top_ids = tuple(dict.fromkeys(
            key for name in options.top_modules for key in self.modules_by_name.get(name, ())
        ))
        for name in options.top_modules:
            if name not in self.modules_by_name:
                self._warn("missing_top", f"指定顶层 {name} 未找到模块定义", path_location(root_path))
        for cycle, reference in cycle_edges(edges):
            names = " → ".join(self.definitions[key].name for key in cycle)
            self._warn("instance_cycle", f"静态实例引用可能循环：{names}（条件未求值）", reference.instance.location)
        include_edges: dict[str, list[tuple[str, object]]] = {file.path: [] for file in files}
        for include in includes:
            if include.status == "resolved" and include.target_path in include_edges:
                include_edges[include.source_path].append((include.target_path, include))
        for cycle, include in cycle_edges(include_edges):
            names = " → ".join(posixpath.basename(path) for path in cycle)
            self._warn("include_cycle", f"静态 include 可能循环：{names}（宏保护未求值）", include.directive.location)
        self.diagnostics = tuple(self._diagnostics)

    def _warn(self, code: str, message: str, location: SourceLocation) -> None:
        self._diagnostics.append(Diagnostic(code, message, "warning", location))
        self.incomplete = True

    def module_summary(self, definition_id: str) -> dict:
        module = self.definitions[definition_id]
        return {
            "id": definition_id, "name": module.name, "location": asdict(module.location),
            "contexts": list(module.contexts), "incomplete": module.incomplete,
            "portCount": len(module.ports), "parameterCount": len(module.parameters), "instanceCount": len(module.instances),
        }

    def children(self, definition_id: str, ancestors: tuple[str, ...] = ()) -> list[dict]:
        if definition_id not in self.definitions or any(key not in self.definitions for key in ancestors):
            raise ValueError("模块定义不在当前项目索引中")
        active = {*ancestors, definition_id}
        children = []
        for reference in self.references_by_owner[definition_id]:
            cycles = tuple(key for key in reference.candidate_ids if key in active)
            target = reference.candidate_ids[0] if reference.status == "resolved" else None
            status = "cycle" if target in active else reference.status
            children.append({
                "id": reference.id, "name": reference.instance.name, "targetName": reference.instance.module_name,
                "status": status, "definitionId": target, "candidateIds": list(reference.candidate_ids),
                "cycleCandidateIds": list(cycles),
                "expandable": status == "ambiguous" or bool(target and status != "cycle" and self.references_by_owner[target]),
                "location": asdict(reference.instance.location), "contexts": list(reference.instance.contexts),
                "arrayDimensions": list(reference.instance.array_dimensions),
                "parameterOverrides": [asdict(item) for item in reference.instance.parameter_overrides],
            })
        return children

    def to_dict(self) -> dict:
        return {
            "rootPath": self.root_path, "incomplete": self.incomplete,
            "summary": {"fileCount": len(self.files), "scannedFileCount": self.scanned_file_count,
                        "sourceBytes": self.source_bytes, "moduleCount": len(self.definitions), "instanceCount": len(self.references)},
            "limits": {"maxFiles": self.options.max_files, "maxFileBytes": self.options.max_file_bytes,
                       "maxTotalBytes": self.options.max_total_bytes},
            "files": [{"path": file.path, "sizeBytes": file.size_bytes, "mtimeNs": file.mtime_ns,
                       "sha256": file.sha256, "incomplete": file.result.incomplete} for file in self.files],
            "modules": [self.module_summary(key) for key in self.definitions],
            "references": [{"id": reference.id, "ownerId": reference.owner_id, "name": reference.instance.name,
                            "targetName": reference.instance.module_name, "status": reference.status,
                            "candidateIds": list(reference.candidate_ids), "location": asdict(reference.instance.location),
                            "contexts": list(reference.instance.contexts)} for reference in self.references.values()],
            "includes": [asdict(include) for include in self.includes],
            "candidateTopIds": list(self.candidate_top_ids), "selectedTopIds": list(self.selected_top_ids),
            "allModuleIds": list(self.definitions), "diagnostics": [asdict(item) for item in self.diagnostics],
        }


class ProjectScanner:
    def __init__(self, parser: HdlParser, host_call: HostCall, workspace_root: str,
                 options: ScanOptions | None = None, *, host_read_bytes: int = 4 * 1024 * 1024) -> None:
        self.parser = parser
        self.host_call = host_call
        self.paths = WorkspacePaths(workspace_root)
        self.options = options or ScanOptions()
        if isinstance(host_read_bytes, bool) or not isinstance(host_read_bytes, int) or host_read_bytes < 1:
            raise ValueError("Host readBytes 必须为正整数")
        self.file_limit = min(host_read_bytes, self.options.max_file_bytes)

    def scan(self, root_path: str = ".") -> ProjectIndex:
        # Per-scan state is disposable; refreshing creates a complete new index.
        self.diagnostics: list[Diagnostic] = []
        self.files: dict[str, SourceFile] = {}
        self.includes: list[IncludeResolution] = []
        self.seen_files: set[str] = set()
        self.seen_directories: set[str] = set()
        self.source_bytes = 0
        self.scanned_file_count = 0
        self.incomplete = False
        self.file_limit_reached = False
        requested = self.paths.absolute(self.paths.root, root_path)
        root = self._stat(requested)
        if not root.get("exists") or not root.get("isDir"):
            raise ValueError("HDL 项目目录不存在或不是目录")
        self.root_path = root["path"]
        self.include_directories = tuple(self.paths.absolute(self.root_path, value) for value in self.options.include_directories)
        directories = deque([self.root_path])
        self.pending_files: deque[tuple[str, dict | None]] = deque()
        while (directories or self.pending_files) and not self.file_limit_reached:
            if self.pending_files:
                path, metadata = self.pending_files.popleft()
                self._scan_file(path, metadata)
                continue
            requested = directories.popleft()
            try:
                metadata = self._stat(requested)
                path = metadata["path"]
                key = self.paths.key(path)
                if key in self.seen_directories:
                    continue
                self.seen_directories.add(key)
                listing = self._host("host.workspace.list_dir", {"path": path})
                if self.paths.key(self.paths.absolute(self.paths.root, listing["path"])) != key:
                    raise ValueError("Host 目录身份与请求不一致")
                if listing.get("truncated"):
                    self._warn("directory_truncated", "Host 目录条目已截断，项目分析不完整", path_location(path))
                for entry in sorted(listing["entries"], key=lambda item: (not item["isDir"], item["name"].casefold())):
                    name = entry["name"]
                    if not isinstance(name, str) or name in {".", ".."} or "/" in name or "\\" in name:
                        raise ValueError("Host 返回无效目录条目")
                    child = self.paths.absolute(path, name)
                    if entry.get("isDir"):
                        if name.casefold() not in self.options.ignore_directories:
                            directories.append(child)
                    elif posixpath.splitext(name)[1].casefold() in HDL_EXTENSIONS:
                        self.pending_files.append((child, None))
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                self._warn("directory_error", f"无法完整扫描目录：{exc}", path_location(requested))
        files = tuple(sorted(self.files.values(), key=lambda file: self.paths.key(file.path)))
        includes = []
        for include in self.includes:
            target = self.files.get(self.paths.key(include.target_path)) if include.target_path else None
            if include.status == "resolved":
                include = replace(include, target_path=target.path if target else include.target_path,
                                  status="resolved" if target else "unread")
            includes.append(include)
        return ProjectIndex(self.root_path, files, tuple(includes), self.diagnostics, self.options,
                            scanned_file_count=self.scanned_file_count, source_bytes=self.source_bytes, incomplete=self.incomplete)

    def _warn(self, code: str, message: str, location: SourceLocation) -> None:
        self.diagnostics.append(Diagnostic(code, message, "warning", location))
        self.incomplete = True

    def _host(self, method: str, params: dict) -> dict:
        response = self.host_call(method, params)
        if response.get("error"):
            raise RuntimeError(str(response["error"].get("message") or f"Host 调用失败：{method}"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"Host 返回无效结果：{method}")
        return result

    def _stat(self, path: str) -> dict:
        path = self.paths.absolute(self.paths.root, path)
        result = self._host("host.workspace.stat", {"path": path})
        result["path"] = self.paths.absolute(self.paths.root, result["path"])
        return result

    def _read_source(self, metadata: dict) -> bytes:
        path, size, mtime = metadata["path"], metadata["size"], str(metadata["mtimeNs"])
        chunks = []
        offset = 0
        while offset < size or not chunks:
            length = min(READ_CHUNK_BYTES, size - offset)
            result = self._host("host.workspace.read_range", {"path": path, "offset": offset, "length": length})
            actual_path = self.paths.absolute(self.paths.root, result["path"])
            if (self.paths.key(actual_path) != self.paths.key(path) or result["fileSizeBytes"] != size
                    or str(result["mtimeNs"]) != mtime or result["offset"] != offset):
                raise ValueError("源码在读取期间发生变化或 Host 文件身份不一致，请刷新")
            encoded = result["contentBase64"]
            if not isinstance(encoded, str) or len(encoded) > ((length + 2) // 3) * 4:
                raise ValueError("Host 返回的源码范围超过请求长度")
            chunk = base64.b64decode(encoded, validate=True)
            self.source_bytes += len(chunk)
            if len(chunk) != length or result["length"] != len(chunk) or bool(result["eof"]) != (offset + len(chunk) == size):
                raise ValueError("Host 返回不完整源码范围，请刷新")
            chunks.append(chunk)
            offset += len(chunk)
            if offset == size:
                break
        final = self._stat(path)
        if (not final.get("exists") or final.get("isDir") or self.paths.key(final["path"]) != self.paths.key(path)
                or final["size"] != size or str(final["mtimeNs"]) != mtime):
            raise ValueError("源码在读取期间发生变化，请刷新")
        return b"".join(chunks)

    def _scan_file(self, requested: str, metadata: dict | None) -> None:
        try:
            metadata = metadata or self._stat(requested)
            path = metadata["path"]
            key = self.paths.key(path)
            if key in self.seen_files:
                previous = self.files.get(key)
                if previous and (metadata["size"] != previous.size_bytes or str(metadata["mtimeNs"]) != previous.mtime_ns):
                    self._warn("source_changed", "源码在项目扫描期间发生变化，请刷新", path_location(path))
                return
            if self.scanned_file_count >= self.options.max_files:
                self.file_limit_reached = True
                self._warn("file_count_limit", f"已达 {self.options.max_files} 个 HDL 文件限额，项目分析不完整", path_location(path))
                return
            self.seen_files.add(key)
            self.scanned_file_count += 1
            if not metadata.get("exists") or metadata.get("isDir"):
                raise ValueError("HDL 源码文件不存在或不是普通文件")
            size = metadata["size"]
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ValueError("Host 返回无效文件大小")
            if size > self.file_limit:
                self._warn("file_size_limit", f"文件 {size} 字节，超过有效单文件限额 {self.file_limit} 字节", path_location(path))
                return
            if self.source_bytes + size > self.options.max_total_bytes:
                self._warn("total_source_limit", f"总源码读取将超过 {self.options.max_total_bytes} 字节，项目分析不完整", path_location(path))
                return
            source = self._read_source(metadata)
            result = self.parser.parse(path, source)
            self.files[key] = SourceFile(path, size, str(metadata["mtimeNs"]), sha256(source).hexdigest(), result)
            self.diagnostics.extend(result.diagnostics)
            self.incomplete |= result.incomplete
            for directive in result.includes:
                self._include(path, directive)
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            self._warn("source_error", f"无法完整读取或解析源码：{exc}", path_location(requested))

    def _include(self, source_path: str, directive: IncludeDirective) -> None:
        if directive.target_path is None:
            self.includes.append(IncludeResolution(source_path, directive, None, "unresolved"))
            self.incomplete = True
            return
        base_directories = (posixpath.dirname(source_path), *self.include_directories)
        seen: set[str] = set()
        failures: list[str] = []
        boundary_error = False
        for directory in base_directories:
            try:
                candidate = self.paths.absolute(directory, directive.target_path)
            except ValueError as exc:
                boundary_error = True
                failures.append(str(exc))
                continue
            if self.paths.key(candidate) in seen:
                continue
            seen.add(self.paths.key(candidate))
            try:
                metadata = self._stat(candidate)
                if not metadata.get("exists") or metadata.get("isDir"):
                    continue
                target = metadata["path"]
                self.includes.append(IncludeResolution(source_path, directive, target, "resolved"))
                self.pending_files.append((target, metadata))
                return
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                failures.append(str(exc))
        code = "include_outside_workspace" if boundary_error else "missing_include"
        self._warn(code, f"无法解析 include {directive.expression}" + (f"：{failures[0]}" if failures else ""), directive.location)
        self.includes.append(IncludeResolution(source_path, directive, None, "unresolved"))
