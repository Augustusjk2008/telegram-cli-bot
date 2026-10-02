from __future__ import annotations

import base64
from collections import Counter
from hashlib import sha256
import importlib
from pathlib import Path
import posixpath

import pytest


BACKEND = Path(__file__).resolve().parents[1] / "examples/plugins/hdl-workbench/backend"


@pytest.fixture
def hdl_project(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    return importlib.import_module("hdl_project")


@pytest.fixture
def parser(hdl_project):
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_verilog")
    return hdl_project.HdlParser()


class MemoryHost:
    """A virtual workspace; any accidental local source reads would fail."""

    def __init__(self, files, *, aliases=None, truncated=(), corrupt_range=None):
        self.files = {f"/workspace/project/{name}": data.encode("utf-8") if isinstance(data, str) else data
                      for name, data in files.items()}
        self.aliases = aliases or {}
        self.truncated = set(truncated)
        self.corrupt_range = corrupt_range
        self.calls = []
        self.mtimes = Counter()
        self.directories = {"/workspace", "/workspace/project"}
        for path in (*self.files, *self.aliases):
            parent = posixpath.dirname(path)
            while parent not in {"", "/"}:
                self.directories.add(parent)
                parent = posixpath.dirname(parent)

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        requested = posixpath.normpath(params["path"])
        path = self.aliases.get(requested, requested)
        if method == "host.workspace.stat":
            return {"result": {"path": path, "exists": path in self.files or path in self.directories,
                               "isDir": path in self.directories, "size": len(self.files.get(path, b"")),
                               "mtimeNs": 7 + self.mtimes[path]}}
        if method == "host.workspace.list_dir":
            entries = []
            for child in sorted(self.directories | set(self.files) | set(self.aliases)):
                if posixpath.dirname(child) != path:
                    continue
                canonical = self.aliases.get(child, child)
                entries.append({"name": posixpath.basename(child), "path": child,
                                "isDir": canonical in self.directories, "size": len(self.files.get(canonical, b"")), "mtimeNs": 7})
            truncated = path in self.truncated
            return {"result": {"path": path, "entries": entries[:1] if truncated else entries,
                               "truncated": truncated, "entryLimit": 1 if truncated else 2000}}
        assert method == "host.workspace.read_range", f"unexpected Host call {method}"
        content = self.files[path]
        offset, length = params["offset"], params["length"]
        chunk = content[offset:offset + length]
        result = {"path": path, "offset": offset, "length": len(chunk), "fileSizeBytes": len(content),
                  "mtimeNs": str(7 + self.mtimes[path]), "contentBase64": base64.b64encode(chunk).decode("ascii"),
                  "eof": offset + len(chunk) >= len(content)}
        if self.corrupt_range:
            self.corrupt_range(result, params, self)
        return {"result": result}

    def reads(self):
        return [params for method, params in self.calls if method == "host.workspace.read_range"]


def scan(hdl_project, parser, host, **options):
    return hdl_project.ProjectScanner(parser, host, "/workspace", hdl_project.ScanOptions(**options)).scan("project")


def definition(index, name):
    key, = index.modules_by_name[name]
    return key


def test_cross_file_index_tops_and_lazy_children_keep_override_and_source_location(hdl_project, parser):
    host = MemoryHost({
        "top.sv": "module top(input clk);\nchild #(.W(8)) u_child (.clk(clk));\nendmodule",
        "nested/child.sv": "module child #(parameter W=4) (input clk); endmodule",
        "other.v": "module other; endmodule",
        "build/ignored.v": "module ignored; endmodule",
        ".venv/ignored.sv": "module ignored; endmodule",
        "node_modules/ignored.vh": "module ignored; endmodule",
        "README.txt": "module fake; endmodule",
    })
    index = scan(hdl_project, parser, host)

    assert not index.incomplete
    assert set(index.modules_by_name) == {"top", "child", "other"}
    assert {index.definitions[key].name for key in index.candidate_top_ids} == {"top", "other"}
    children = index.children(definition(index, "top"))
    child, = children
    assert (child["name"], child["status"], child["definitionId"], child["expandable"]) == ("u_child", "resolved", definition(index, "child"), False)
    assert child["location"]["path"] == "/workspace/project/top.sv"
    assert child["location"]["start_line"] == 2
    assert child["parameterOverrides"][0]["expression"] == "8"
    assert "children" not in child
    assert {call["path"] for call in host.reads()} == {file.path for file in index.files}
    assert index.to_dict()["summary"]["fileCount"] == 3


def test_configured_tops_and_invalid_selection_do_not_pick_an_arbitrary_module(hdl_project, parser):
    host = MemoryHost({"a.v": "module a; endmodule", "b.v": "module b; endmodule"})
    selected = scan(hdl_project, parser, host, top_modules=("b",))
    assert selected.selected_top_ids == (definition(selected, "b"),)
    missing = scan(hdl_project, parser, host, top_modules=("missing",))
    assert missing.selected_top_ids == ()
    assert missing.incomplete and any(item.code == "missing_top" for item in missing.diagnostics)
    assert len(missing.definitions) == 2


def test_duplicate_definitions_and_missing_targets_remain_explicit_candidates(hdl_project, parser):
    host = MemoryHost({
        "top.sv": "module top; leaf u(); absent u_missing(); endmodule",
        "one.v": "module leaf; endmodule", "two.v": "module leaf; endmodule",
    })
    index = scan(hdl_project, parser, host, top_modules=("leaf",))

    assert index.incomplete
    assert len(index.modules_by_name["leaf"]) == 2
    ambiguous, missing = index.children(definition(index, "top"))
    assert ambiguous["status"] == "ambiguous" and ambiguous["candidateIds"] == list(index.modules_by_name["leaf"])
    assert ambiguous["definitionId"] is None and ambiguous["expandable"]
    assert missing["status"] == "missing" and not missing["expandable"]
    assert missing["candidateIds"] == []
    assert index.selected_top_ids == index.modules_by_name["leaf"]
    assert {item.code for item in index.diagnostics} == {"duplicate_module", "missing_module"}


def test_instance_cycles_stop_at_the_current_hierarchy_path(hdl_project, parser):
    index = scan(hdl_project, parser, MemoryHost({
        "a.v": "module a; b u_b(); endmodule", "b.v": "module b; a u_a(); endmodule",
    }))
    a, b = definition(index, "a"), definition(index, "b")

    assert index.candidate_top_ids == () and len(index.definitions) == 2
    assert index.children(a)[0]["expandable"]
    terminal, = index.children(b, (a,))
    assert terminal["status"] == "cycle" and not terminal["expandable"]
    assert terminal["cycleCandidateIds"] == [a]
    assert any(item.code == "instance_cycle" and item.location.path == "/workspace/project/b.v" for item in index.diagnostics)


def test_cycle_detection_and_hierarchy_do_not_recurse_through_a_deep_design(hdl_project, parser):
    size = 1050
    source = "\n".join(f"module m{i}; m{(i + 1) % size} u(); endmodule" for i in range(size))
    index = scan(hdl_project, parser, MemoryHost({"deep.sv": source}))
    assert len(index.definitions) == size
    assert sum(item.code == "instance_cycle" for item in index.diagnostics) == 1
    ancestors = tuple(definition(index, f"m{i}") for i in range(size - 1))
    assert index.children(definition(index, f"m{size - 1}"), ancestors)[0]["status"] == "cycle"


def test_conditional_definitions_and_generate_expressions_are_not_elaborated(hdl_project, parser):
    index = scan(hdl_project, parser, MemoryHost({"conditional.sv": """`ifdef ALT
module leaf; endmodule
`else
module leaf; endmodule
`endif
module top;
generate if (W > 1) begin
leaf u_leaf[3:0] ();
end endgenerate
endmodule
"""}))
    assert len(index.modules_by_name["leaf"]) == 2
    child, = index.children(definition(index, "top"))
    assert child["status"] == "ambiguous" and child["arrayDimensions"] == ["[3:0]"]
    assert "if (W > 1)" in child["contexts"]
    assert {index.definitions[key].contexts for key in index.modules_by_name["leaf"]} == {("`ifdef ALT",), ("`else of `ifdef ALT",)}


def test_literal_include_search_uses_configured_directories_and_reads_shared_files_once(hdl_project, parser):
    host = MemoryHost({
        "rtl/a.sv": '`include "defs.svh"\nmodule a; leaf u(); endmodule',
        "rtl/b.sv": '`include "defs.svh"\nmodule b; endmodule',
        "headers/defs.svh": "module leaf; endmodule",
    })
    index = hdl_project.ProjectScanner(parser, host, "/workspace", hdl_project.ScanOptions(include_directories=("../headers",))).scan("project/rtl")

    assert not index.incomplete
    assert set(index.modules_by_name) == {"a", "b", "leaf"}
    assert [(item.target_path, item.status) for item in index.includes] == [("/workspace/project/headers/defs.svh", "resolved")] * 2
    counts = Counter(call["path"] for call in host.reads())
    assert counts["/workspace/project/headers/defs.svh"] == 1


def test_include_cycles_and_scan_aliases_do_not_duplicate_definitions_or_loop(hdl_project, parser):
    host = MemoryHost({
        "a.v": '`include "b.svh"\nmodule a; endmodule',
        "b.svh": '`include "a.v"\nmodule b; endmodule',
    }, aliases={"/workspace/project/again": "/workspace/project", "/workspace/project/alias.v": "/workspace/project/a.v"})
    index = scan(hdl_project, parser, host)

    assert len(index.files) == 2 and set(index.modules_by_name) == {"a", "b"}
    assert all(count == 1 for count in Counter(call["path"] for call in host.reads()).values())
    assert sum(method == "host.workspace.list_dir" for method, _ in host.calls) == 1
    assert sum(item.code == "include_cycle" for item in index.diagnostics) == 1
    assert not any(item.code == "duplicate_module" for item in index.diagnostics)


def test_repeated_include_notices_a_previously_indexed_file_changing(hdl_project, parser):
    def change_header(result, _params, host):
        if result["path"].endswith("b_top.sv"):
            host.mtimes["/workspace/project/a_header.svh"] += 1

    host = MemoryHost({"a_header.svh": "module leaf; endmodule",
                       "b_top.sv": '`include "a_header.svh"\nmodule top; leaf u(); endmodule'}, corrupt_range=change_header)
    index = scan(hdl_project, parser, host)
    assert index.incomplete
    assert any(item.code == "source_changed" for item in index.diagnostics)
    assert len(host.reads()) == 2


def test_macro_and_missing_include_paths_are_retained_as_unresolved(hdl_project, parser):
    index = scan(hdl_project, parser, MemoryHost({"top.sv": '`include `HEADER\n`include "missing.svh"\nmodule top; endmodule'}))
    assert index.incomplete
    assert [include.status for include in index.includes] == ["unresolved", "unresolved"]
    assert {item.code for item in index.diagnostics} == {"unresolved_include", "missing_include"}
    assert "top" in index.modules_by_name


def test_include_paths_cannot_read_outside_the_workspace(hdl_project, parser):
    host = MemoryHost({"top.sv": '`include "../../secret.vh"\nmodule top; endmodule'})
    index = scan(hdl_project, parser, host)
    assert index.incomplete
    assert any(item.code == "include_outside_workspace" and item.location.start_line == 1 for item in index.diagnostics)
    assert not any(params["path"] == "/secret.vh" for _, params in host.calls)


def test_project_and_include_directory_configuration_reject_workspace_escape(hdl_project, parser):
    host = MemoryHost({"top.v": "module top; endmodule"})
    scanner = hdl_project.ProjectScanner(parser, host, "/workspace")
    with pytest.raises(ValueError, match="越界"):
        scanner.scan("../outside")
    assert host.calls == []
    with pytest.raises(ValueError, match="越界"):
        scan(hdl_project, parser, host, include_directories=("../../outside",))
    assert not host.reads()


def test_host_returned_symlink_targets_outside_workspace_are_never_read(hdl_project, parser):
    host = MemoryHost({"inside.v": "module inside; endmodule"}, aliases={"/workspace/project/alias.v": "/outside/secret.v"})
    host.files["/outside/secret.v"] = b"module secret; endmodule"
    index = scan(hdl_project, parser, host)
    assert index.incomplete and set(index.modules_by_name) == {"inside"}
    assert all(call["path"].startswith("/workspace/") for call in host.reads())
    assert any(item.code == "source_error" for item in index.diagnostics)


@pytest.mark.parametrize(("root", "value", "expected"), [
    ("C:\\Workspace", "c:/workspace/rtl/../top.v", "c:/workspace/top.v"),
    ("C:/", "rtl/top.v", "C:/rtl/top.v"),
    ("//server/share", "rtl/top.v", "//server/share/rtl/top.v"),
])
def test_windows_paths_preserve_drive_and_share_roots(hdl_project, root, value, expected):
    paths = hdl_project.WorkspacePaths(root)
    assert paths.absolute(paths.root, value) == expected


@pytest.mark.parametrize("root", ["C:/", "//server/share/"])
def test_drive_and_share_projects_accept_default_path_and_current_include_directory(hdl_project, parser, root):
    def host(method, params):
        assert params["path"] == root
        if method == "host.workspace.stat":
            return {"result": {"path": root, "exists": True, "isDir": True, "size": 0, "mtimeNs": 7}}
        assert method == "host.workspace.list_dir"
        return {"result": {"path": root, "entries": [], "truncated": False}}

    scanner = hdl_project.ProjectScanner(parser, host, root, hdl_project.ScanOptions(include_directories=(".",)))
    index = scanner.scan()
    assert index.root_path == root and not index.incomplete
    assert scanner.include_directories == (root,)


@pytest.mark.parametrize("value", ["C:/Workspace-other/top.v", "D:/Workspace/top.v", "../top.v", "C:top.v"])
def test_windows_boundaries_reject_prefix_drive_and_parent_escapes(hdl_project, value):
    paths = hdl_project.WorkspacePaths("C:/Workspace")
    with pytest.raises(ValueError):
        paths.absolute(paths.root, value)


def test_directory_truncation_and_file_count_limits_surface_partial_analysis(hdl_project, parser):
    files = {"a.v": "module a; endmodule", "b.v": "module b; endmodule"}
    truncated = scan(hdl_project, parser, MemoryHost(files, truncated=("/workspace/project",)))
    assert truncated.incomplete and len(truncated.files) == 1
    assert any(item.code == "directory_truncated" for item in truncated.diagnostics)
    host = MemoryHost(files)
    limited = scan(hdl_project, parser, host, max_files=1)
    assert limited.incomplete and len(limited.files) == 1
    assert limited.scanned_file_count == 1 and len(host.reads()) == 1
    assert any(item.code == "file_count_limit" for item in limited.diagnostics)
    exact = scan(hdl_project, parser, MemoryHost({"a.v": files["a.v"]}), max_files=1)
    assert not exact.incomplete


def test_file_and_total_source_byte_budgets_are_checked_before_reading(hdl_project, parser):
    source = "module m; endmodule"
    host = MemoryHost({"a.v": source})
    oversized = scan(hdl_project, parser, host, max_file_bytes=len(source) - 1)
    assert not oversized.files and not host.reads()
    assert any(item.code == "file_size_limit" for item in oversized.diagnostics)
    exact = scan(hdl_project, parser, MemoryHost({"a.v": source}), max_file_bytes=len(source), max_total_bytes=len(source))
    assert not exact.incomplete
    host = MemoryHost({"a.v": source, "b.v": "module n; endmodule"})
    limited = scan(hdl_project, parser, host, max_total_bytes=len(source))
    assert limited.source_bytes == len(source) and len(host.reads()) == 1
    assert any(item.code == "total_source_limit" for item in limited.diagnostics)


def test_host_read_limit_applies_to_the_whole_file(hdl_project, parser):
    host = MemoryHost({"a.v": "module a; endmodule"})
    index = hdl_project.ProjectScanner(parser, host, "/workspace", host_read_bytes=8).scan("project")
    assert index.incomplete and not host.reads()
    assert any(item.code == "file_size_limit" for item in index.diagnostics)


def test_read_range_is_chunked_and_keeps_a_verified_file_fingerprint(hdl_project, parser):
    source = b"//" + b"x" * (hdl_project.READ_CHUNK_BYTES + 10) + b"\r\nmodule big; endmodule"
    host = MemoryHost({"big.sv": source})
    index = scan(hdl_project, parser, host)
    assert not index.incomplete
    assert [call["offset"] for call in host.reads()] == [0, hdl_project.READ_CHUNK_BYTES]
    assert all(call["length"] <= 1024 * 1024 for call in host.reads())
    file, = index.files
    assert file.size_bytes == index.source_bytes == len(source)
    assert file.mtime_ns == "7" and file.sha256 == sha256(source).hexdigest()
    assert index.definitions[definition(index, "big")].location.start_line == 2


def test_empty_sources_are_verified_without_a_nonprogressing_read_loop(hdl_project, parser):
    host = MemoryHost({"empty.vh": b""})
    index = scan(hdl_project, parser, host)
    assert not index.incomplete and len(index.files) == 1
    assert host.reads() == [{"path": "/workspace/project/empty.vh", "offset": 0, "length": 0}]


@pytest.mark.parametrize("corruption", ["mtime", "size", "short", "offset", "base64"])
def test_changed_or_incomplete_host_reads_never_produce_a_partial_module_index(hdl_project, parser, corruption):
    def corrupt(result, _params, _host):
        if corruption == "mtime":
            result["mtimeNs"] = "99"
        elif corruption == "size":
            result["fileSizeBytes"] += 1
        elif corruption == "short":
            result["contentBase64"], result["length"] = "", 0
        elif corruption == "offset":
            result["offset"] += 1
        else:
            result["contentBase64"] = "!"

    index = scan(hdl_project, parser, MemoryHost({"a.v": "module a; endmodule"}, corrupt_range=corrupt))
    assert index.incomplete and not index.files and not index.definitions
    assert any(item.code == "source_error" for item in index.diagnostics)


def test_final_stat_change_discards_the_completed_read(hdl_project, parser):
    def mutate_after_read(result, _params, host):
        host.mtimes[result["path"]] += 1

    index = scan(hdl_project, parser, MemoryHost({"a.v": "module a; endmodule"}, corrupt_range=mutate_after_read))
    assert index.incomplete and not index.definitions
    assert index.source_bytes > 0


def test_unread_include_and_source_syntax_errors_keep_other_modules(hdl_project, parser):
    host = MemoryHost({"top.sv": '`include "bad.svh"\nmodule top; endmodule', "bad.svh": b"\xff"})
    index = scan(hdl_project, parser, host)
    assert index.incomplete and "top" in index.modules_by_name
    assert index.includes[0].status == "unread"
    broken = scan(hdl_project, parser, MemoryHost({"bad.sv": "module broken(input a\nassign a = ;\nendmodule\nmodule good; endmodule"}))
    assert broken.incomplete and "good" in broken.modules_by_name
    assert any(item.code == "syntax_error" for item in broken.diagnostics)


def test_config_validation_keeps_defaults_and_rejects_invalid_limits(hdl_project):
    options = hdl_project.ScanOptions.from_config({"topModule": "a, b", "includeDirectories": ["include"]})
    assert options.top_modules == ("a", "b") and options.include_directories == ("include",)
    assert (options.max_files, options.max_file_bytes, options.max_total_bytes) == (1000, 4 * 1024 * 1024, 64 * 1024 * 1024)
    assert "node_modules" in options.ignore_directories
    for value in (0, -1, True, "1000"):
        with pytest.raises(ValueError):
            hdl_project.ScanOptions.from_config({"maxFiles": value})
