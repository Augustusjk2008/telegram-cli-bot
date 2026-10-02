from __future__ import annotations

import importlib
import json

import pytest

from tests.test_hdl_project import BACKEND, MemoryHost


@pytest.fixture
def hdl_views(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    return importlib.import_module("hdl_views")


@pytest.fixture
def parser(hdl_views):
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_verilog")
    return importlib.import_module("hdl_parser").HdlParser()


@pytest.fixture
def make_views(hdl_views, parser):
    def make(files, config=None, **host_options):
        host = MemoryHost(files, **host_options)
        context = {"host": {"workspaceRoot": "/workspace", "botAlias": "bot", "limits": {"readBytes": 4 * 1024 * 1024}}}
        return hdl_views.HdlViews(parser, host, context, config or {}), host
    return make


def tree(views):
    return views.open_view({"viewId": "module-tree", "input": {"path": "project"}})


def children(views, opened, node=None):
    return views.get_view_window({"sessionId": opened["sessionId"], "op": "children", "nodeId": node})["nodes"]


def module_node(views, opened, name):
    return next(node for node in children(views, opened, opened["initialWindow"]["nodes"][1]["id"]) if node["label"] == name)


def action(views, opened, action_id, **payload):
    return views.invoke_action({"viewId": "module-tree" if opened["renderer"] == "tree" else "module-details",
                               "sessionId": opened["sessionId"], "actionId": action_id, "payload": payload})


def detail_input(views, opened, node):
    return action(views, opened, "open-details", nodeId=node["id"])["hostEffects"][0]["input"]


def details(views, opened, node):
    return views.open_view({"viewId": "module-details", "input": detail_input(views, opened, node)})


def test_signal_rows_show_inference_evidence_and_navigate_each_trusted_occurrence(make_views):
    source = """`ifdef ACTIVE
module sequential(input logic clk, rst_n, data, output logic q);
always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= 1'b0;
    else q <= data;
end
endmodule
`endif
"""
    views, _host = make_views({"rtl/sequential.sv": source})
    opened = tree(views)
    table = details(views, opened, module_node(views, opened, "sequential"))
    window = views.get_view_window({"sessionId": table["sessionId"], "query": "候选"})
    assert window["totalRows"] == 3
    assert [(row["cells"]["kind"], row["cells"]["name"]) for row in window["rows"]] == [
        ("时钟候选", "clk"), ("复位候选", "rst_n"), ("复位候选", "rst_n"),
    ]
    assert len({row["id"] for row in window["rows"]}) == 3
    for row, (line, expression) in zip(window["rows"], [(3, "clk"), (3, "rst_n"), (4, "rst_n")]):
        assert row["cells"]["evidence"] and row["cells"]["context"] == "`ifdef ACTIVE"
        column = source.splitlines()[line - 1].index(expression) + 1
        effect, = action(views, table, "open-declaration", rowId=row["id"], path="/forged.sv", line=999)["hostEffects"]
        assert effect == {"type": "open_file", "path": "/workspace/project/rtl/sequential.sv", "line": line, "column": column}


def test_tree_is_lazy_and_occurrence_ids_preserve_independent_cycle_paths(make_views):
    views, _host = make_views({"design.sv": """module top;
middle left(); middle right();
endmodule
module middle; leaf child(); endmodule
module leaf; middle back(); endmodule
"""})
    opened = tree(views)
    roots = opened["initialWindow"]["nodes"]
    assert len(roots) == 3 and len(views._sessions[opened["sessionId"]].nodes) == 3
    assert all("children" not in node for node in roots)
    top = module_node(views, opened, "top")
    assert [item["id"] for item in top["actions"]] == ["open-details", "open-definition"]
    assert all(item["target"] == "plugin" for item in top["actions"])
    assert top["secondaryText"] == "design.sv:1"
    left, right = children(views, opened, top["id"])
    left_child, = children(views, opened, left["id"])
    right_child, = children(views, opened, right["id"])
    assert left_child["id"] != right_child["id"]
    assert left_child["label"] == right_child["label"] == "child : leaf"
    cycle, = children(views, opened, left_child["id"])
    assert not cycle["hasChildren"] and cycle["badges"]
    assert children(views, opened, cycle["id"]) == []
    size = len(views._sessions[opened["sessionId"]].nodes)
    assert children(views, opened, left["id"])[0]["id"] == left_child["id"]
    assert len(views._sessions[opened["sessionId"]].nodes) == size


def test_ambiguous_targets_expand_choices_and_missing_targets_stay_terminal(make_views):
    views, _host = make_views({
        "top.v": "module top; leaf ambiguous(); absent missing(); endmodule",
        "a.v": "module leaf; leaf recursive(); endmodule",
        "b.v": "module leaf; endmodule",
    })
    opened = tree(views)
    ambiguous, missing = children(views, opened, module_node(views, opened, "top")["id"])
    assert ambiguous["hasChildren"] and not missing["hasChildren"]
    assert ambiguous["badges"] and missing["badges"]
    candidates = children(views, opened, ambiguous["id"])
    assert len(candidates) == 2 and candidates[0]["id"] != candidates[1]["id"]
    assert all(node["actions"][0]["id"] == "open-details" for node in candidates)
    with pytest.raises(ValueError):
        action(views, opened, "open-details", nodeId=ambiguous["id"], definitionId="forged")
    assert children(views, opened, missing["id"]) == []
    recursive_choice = next(node for node in candidates if node["hasChildren"])
    recursive, = children(views, opened, recursive_choice["id"])
    recursive_candidates = children(views, opened, recursive["id"])
    terminal = next(node for node in recursive_candidates if node["secondaryText"].endswith("a.v:1"))
    assert not terminal["hasChildren"] and children(views, opened, terminal["id"]) == []


def test_search_is_bounded_stateless_and_reuses_ids_with_indexed_actions(make_views):
    source = "\n".join(f"module item_{i}; endmodule" for i in range(225))
    source += "\nmodule owner; absent searchable(); endmodule"
    views, _host = make_views({"all.v": source})
    opened = tree(views)
    params = {"sessionId": opened["sessionId"], "op": "search", "query": "all.v", "limit": 3}
    window = views.get_view_window(params)
    assert len(window["nodes"]) == 3 and window["stats"] == {"matched": 228, "returned": 3, "truncated": True}
    assert all("children" not in node and not node["hasChildren"] and node["actions"] for node in window["nodes"])
    count = len(views._sessions[opened["sessionId"]].nodes)
    assert [node["id"] for node in views.get_view_window(params)["nodes"]] == [node["id"] for node in window["nodes"]]
    assert len(views._sessions[opened["sessionId"]].nodes) == count
    instance = views.get_view_window({**params, "query": "searchable"})["nodes"][0]
    assert instance["actions"][-1]["id"] == "open-instance"
    diagnostic = views.get_view_window({**params, "query": "missing_module"})["nodes"][0]
    assert diagnostic["actions"][0]["id"] == "open-diagnostic"
    empty = views.get_view_window({**params, "query": ""})
    assert [node["id"] for node in empty["nodes"]] == [node["id"] for node in opened["initialWindow"]["nodes"]]
    assert len(children(views, opened, opened["initialWindow"]["nodes"][1]["id"])) == 226


@pytest.mark.parametrize("overrides", [
    ".W(BASE + 1), .T(int), .D(2), .LOCKED(99)",
    "BASE + 1, int, 2",
])
def test_parameter_overrides_follow_declaration_order_without_overriding_localparams(make_views, overrides):
    views, host = make_views({"design.sv": f"""module top;
target #({overrides}) u ();
endmodule
module target #(parameter W=4, localparam LOCKED=2, parameter type T=logic, parameter D=3)
(input logic [W-1:0] a [0:D-1], output y);
localparam BODY = W + 1;
endmodule
"""})
    opened = tree(views)
    instance, = children(views, opened, module_node(views, opened, "top")["id"])
    before = len(host.calls)
    table = details(views, opened, instance)
    assert len(host.calls) == before
    rows = {row["cells"]["name"]: row for row in table["initialWindow"]["rows"]}
    assert rows["W"]["cells"]["override"] == "BASE + 1"
    assert rows["T"]["cells"]["override"] == "int"
    assert rows["T"]["cells"]["type"] == "type" and rows["T"]["cells"]["default"] == "logic"
    assert rows["D"]["cells"]["override"] == "2"
    assert rows["LOCKED"]["cells"]["override"] is None and rows["BODY"]["cells"]["override"] is None
    assert rows["a"]["cells"]["width"] == "[W-1:0] [0:D-1]"
    assert rows["W"]["cells"]["default"] == "4"
    assert rows["W"]["cells"]["source"].startswith("design.sv:4:")
    effect = action(views, table, "open-declaration", rowId=rows["W"]["id"], path="/secret", line=999)["hostEffects"][0]
    assert effect["path"] == "/workspace/project/design.sv" and effect["line"] == 4


def test_table_pages_query_and_sort_preserve_trusted_row_ids(make_views):
    source = "module ports(\n" + ",\n".join(f"input logic p{i}" for i in range(60)) + "\n); endmodule"
    views, _host = make_views({"ports.sv": source})
    opened = tree(views)
    table = details(views, opened, module_node(views, opened, "ports"))
    assert [column["id"] for column in table["summary"]["columns"]] == [
        "kind", "name", "direction", "type", "width", "default", "override", "context", "evidence", "source",
    ]
    assert table["summary"]["totalRows"] == 60 and len(table["initialWindow"]["rows"]) == 50
    page = views.get_view_window({"sessionId": table["sessionId"], "offset": 50, "limit": 999})
    assert page["limit"] == 500 and len(page["rows"]) == 10
    row = page["rows"][0]
    assert row["cells"]["name"] == "p50"
    assert action(views, table, "open-declaration", rowId=row["id"])["hostEffects"][0]["line"] == 52
    filtered = views.get_view_window({"sessionId": table["sessionId"], "query": "p1", "sort": {"columnId": "name", "direction": "desc"}})
    assert filtered["totalRows"] == 11 and filtered["rows"][0]["cells"]["name"] == "p19"
    assert views.get_view_window({"sessionId": table["sessionId"], "offset": 50})["rows"][0]["id"] == row["id"]
    for params in ({"offset": -1}, {"offset": True}, {"limit": 0}, {"sort": {"columnId": "path", "direction": "asc"}}):
        with pytest.raises(ValueError):
            views.get_view_window({"sessionId": table["sessionId"], **params})


def test_details_preserve_instance_and_declaration_conditions_without_elaboration(make_views):
    views, _host = make_views({"conditional.sv": """module top;
`ifdef ENABLE
generate
if (SIZE > 1) begin : g
leaf u[3:0] ();
end
endgenerate
`endif
endmodule
`ifdef DECL
module leaf #(parameter WIDTH=4) (input clk); endmodule
`endif
"""})
    opened = tree(views)
    instance, = children(views, opened, module_node(views, opened, "top")["id"])
    assert any("[3:0]" in badge["text"] for badge in instance["badges"])
    table = details(views, opened, instance)
    for row in table["initialWindow"]["rows"]:
        context = row["cells"]["context"]
        assert "`ifdef ENABLE" in context and "if (SIZE > 1)" in context and "`ifdef DECL" in context


def test_source_actions_use_indexed_locations_and_detect_same_size_same_mtime_changes(make_views):
    views, host = make_views({"top.sv": "// 中文😀\r\nmodule top(input logic a); endmodule\r\n"})
    opened = tree(views)
    node = module_node(views, opened, "top")
    before = len(host.calls)
    effect = action(views, opened, "open-definition", nodeId=node["id"], path="/secret", line=999, column=999)["hostEffects"][0]
    assert effect == {"type": "open_file", "path": "/workspace/project/top.sv", "line": 2, "column": 8}
    assert [method for method, _params in host.calls[before:]] == ["host.workspace.stat", "host.workspace.read_range", "host.workspace.stat"]
    table = details(views, opened, node)
    row = table["initialWindow"]["rows"][0]
    host.files["/workspace/project/top.sv"] = host.files["/workspace/project/top.sv"].replace(b"top", b"bad")
    for result in (action(views, opened, "open-definition", nodeId=node["id"]),
                   action(views, table, "open-declaration", rowId=row["id"]), action(views, table, "open-definition")):
        assert result["hostEffects"] == [] and result["message"] and result["refresh"] == "none"


@pytest.mark.parametrize("corruption", ["identity", "offset", "short", "mtime", "oversize", "base64"])
def test_unverifiable_source_ranges_never_navigate(make_views, corruption):
    views, host = make_views({"top.v": "module top; endmodule"})
    opened = tree(views)
    node = module_node(views, opened, "top")
    def corrupt(result, params, _host):
        if corruption == "identity":
            result["path"] = "/outside/secret.v"
        elif corruption == "offset":
            result["offset"] += 1
        elif corruption == "short":
            result["contentBase64"], result["length"] = "", 0
        elif corruption == "mtime":
            result["mtimeNs"] = "99"
        elif corruption == "oversize":
            result["contentBase64"] = "A" * (params["length"] * 4 + 4)
        else:
            result["contentBase64"] = "!"
    host.corrupt_range = corrupt
    assert action(views, opened, "open-definition", nodeId=node["id"])["hostEffects"] == []


def test_changed_canonical_stat_identity_never_reads_or_navigates(make_views):
    views, host = make_views({"top.v": "module top; endmodule", "other.v": "module alt; endmodule"})
    opened = tree(views)
    node = module_node(views, opened, "top")
    host.aliases["/workspace/project/top.v"] = "/workspace/project/other.v"
    before = len(host.reads())
    assert action(views, opened, "open-definition", nodeId=node["id"])["hostEffects"] == []
    assert len(host.reads()) == before


def test_source_fingerprint_verification_reads_large_files_in_bounded_chunks(make_views, hdl_views):
    views, host = make_views({"top.sv": b"//" + b"x" * (hdl_views.READ_CHUNK_BYTES + 10) + b"\nmodule top; endmodule"})
    opened = tree(views)
    node = module_node(views, opened, "top")
    host.calls.clear()
    assert action(views, opened, "open-definition", nodeId=node["id"])["hostEffects"]
    assert [params["offset"] for params in host.reads()] == [0, hdl_views.READ_CHUNK_BYTES]
    assert all(params["length"] <= hdl_views.READ_CHUNK_BYTES for params in host.reads())


def test_sessions_share_only_valid_parent_resources_and_release_independently(make_views):
    views, host = make_views({"top.v": "module top; leaf u(); endmodule", "leaf.v": "module leaf(input a); endmodule"})
    first, second = tree(views), tree(views)
    first_node = module_node(views, first, "top")
    second_node = module_node(views, second, "top")
    first_instance, = children(views, first, first_node["id"])
    second_instance, = children(views, second, second_node["id"])
    payload = detail_input(views, first, first_instance)
    foreign_ref = detail_input(views, second, second_instance)["referenceId"]
    before = len(host.calls)
    for invalid in (
        {**payload, "parentSessionId": "missing"}, {**payload, "path": "/workspace"},
        {**payload, "referenceId": foreign_ref}, {**payload, "referenceId": "forged"},
        {**payload, "definitionId": detail_input(views, first, first_node)["definitionId"]},
    ):
        with pytest.raises(ValueError):
            views.open_view({"viewId": "module-details", "input": invalid})
    assert len(host.calls) == before
    table = views.open_view({"viewId": "module-details", "input": payload})
    sibling = views.open_view({"viewId": "module-details", "input": payload})
    resource = views._sessions[first["sessionId"]].resource
    assert len({first["sessionId"], second["sessionId"], table["sessionId"], sibling["sessionId"]}) == 4
    assert resource.references == 3 and views._sessions[table["sessionId"]].resource is resource
    assert views._sessions[second["sessionId"]].resource is not resource
    second_resource = views._sessions[second["sessionId"]].resource
    assert len(views._resources) == 2 and len(host.calls) == before
    with pytest.raises(ValueError):
        children(views, second, first_node["id"])
    with pytest.raises(ValueError):
        children(views, second, False)
    with pytest.raises(ValueError):
        action(views, second, "open-definition", nodeId=first_node["id"])
    with pytest.raises(ValueError):
        action(views, table, "open-declaration", rowId=sibling["initialWindow"]["rows"][0]["id"])
    assert views.dispose_view({"sessionId": first["sessionId"]}) == {"disposed": True}
    assert resource.references == 2 and action(views, table, "open-definition")["hostEffects"]
    with pytest.raises(ValueError):
        views.open_view({"viewId": "module-details", "input": payload})
    views.dispose_view({"sessionId": table["sessionId"]})
    views.dispose_view({"sessionId": sibling["sessionId"]})
    assert resource.references == 0 and resource.id not in views._resources
    assert views.dispose_view({"sessionId": sibling["sessionId"]}) == {"disposed": False}
    views.shutdown()
    assert not views._resources and not views._sessions and second_resource.references == 0
    with pytest.raises(ValueError):
        children(views, second)


def test_standalone_details_validate_definition_without_parent_sharing(make_views):
    views, host = make_views({"top.v": "module top(input a); endmodule"})
    opened = tree(views)
    node = module_node(views, opened, "top")
    payload = detail_input(views, opened, node)
    payload.pop("parentSessionId")
    count = len(host.reads())
    table = views.open_view({"viewId": "module-details", "input": payload})
    assert len(host.reads()) > count and len(views._resources) == 2
    assert views._sessions[table["sessionId"]].resource is not views._sessions[opened["sessionId"]].resource
    with pytest.raises(ValueError):
        views.open_view({"viewId": "module-details", "input": {**payload, "definitionId": "forged"}})
    assert len(views._resources) == 2


def test_initial_scope_is_immutable_and_cross_bot_requests_are_rejected(hdl_views, parser):
    host = MemoryHost({"top.v": "module top; endmodule", "other.v": "module other; endmodule"})
    context = {"host": {"workspaceRoot": "/workspace", "botAlias": "bot"}}
    config = {"topModule": ["top"]}
    views = hdl_views.HdlViews(parser, host, context, config)
    context["host"]["workspaceRoot"] = "/outside"
    context["host"]["botAlias"] = "changed"
    config["topModule"].append("other")
    opened = tree(views)
    roots = opened["initialWindow"]["nodes"]
    assert [node["label"] for node in children(views, opened, roots[0]["id"])] == ["top"]
    node = module_node(views, opened, "top")
    count = len(host.calls)
    foreign = {"host": {"botAlias": "foreign", "workspaceRoot": "/outside"}}
    for method, params in (
        (views.open_view, {"viewId": "module-tree", "input": {"path": "project"}}),
        (views.get_view_window, {"sessionId": opened["sessionId"], "op": "children"}),
        (views.invoke_action, {"sessionId": opened["sessionId"], "viewId": "module-tree", "actionId": "open-definition", "payload": {"nodeId": node["id"]}}),
        (views.dispose_view, {"sessionId": opened["sessionId"]}),
    ):
        with pytest.raises(ValueError):
            method({**params, "context": foreign})
    assert len(host.calls) == count and opened["sessionId"] in views._sessions
    query = views.get_view_window({"sessionId": opened["sessionId"], "op": "search", "query": "other",
                                   "context": {"host": {"botAlias": "bot", "workspaceRoot": "/outside"}, "plugin": {"config": {"topModule": "missing"}}}})
    assert query["nodes"][0]["label"] == "other"


def test_parser_only_initialization_cannot_acquire_workspace_scope_from_a_request(hdl_views, parser):
    host = MemoryHost({"top.v": "module top; endmodule"})
    views = hdl_views.HdlViews(parser, host, {}, {})
    with pytest.raises(ValueError):
        views.open_view({"viewId": "module-tree", "input": {"path": "project"},
                         "context": {"host": {"workspaceRoot": "/workspace"}}})
    assert not host.calls and not views._sessions and not views._resources


def test_large_hierarchy_bounds_each_window_and_preserves_search_paging_and_cleanup(make_views, hdl_views):
    count = hdl_views.CHILD_LIMIT + 25
    source = "module top;\n" + "\n".join(f"leaf u{i}();" for i in range(count)) + "\nendmodule\n"
    source += "module leaf(\n" + ",\n".join(f"input logic p{i}" for i in range(600)) + "\n); endmodule"
    views, _host = make_views({"large.sv": source})
    opened = tree(views)
    assert len(views._sessions[opened["sessionId"]].nodes) == 3
    top = module_node(views, opened, "top")
    window = children(views, opened, top["id"])
    assert len(window) == hdl_views.CHILD_LIMIT + 1
    assert window[-1]["badges"] == [{"text": "窗口截断", "tone": "warning"}]
    assert not window[-1]["hasChildren"] and "搜索" in window[-1]["secondaryText"]
    assert len(json.dumps(window, ensure_ascii=False).encode("utf-8")) < 8 * 1024 * 1024
    search = views.get_view_window({"sessionId": opened["sessionId"], "op": "search", "query": f"u{count - 1}"})
    late, = search["nodes"]
    table = details(views, opened, late)
    assert table["summary"]["totalRows"] == 600 and len(table["initialWindow"]["rows"]) == 50
    page = views.get_view_window({"sessionId": table["sessionId"], "offset": 550, "limit": 500})
    assert len(page["rows"]) == 50 and page["rows"][-1]["cells"]["name"] == "p599"
    resource = views._sessions[table["sessionId"]].resource
    views.dispose_view({"sessionId": opened["sessionId"]})
    assert resource.references == 1
    views.dispose_view({"sessionId": table["sessionId"]})
    assert resource.references == 0 and not views._sessions and not views._resources


def test_project_summary_and_diagnostics_expose_missing_references_and_scan_truncation(make_views):
    views, _host = make_views({
        "a.v": "module top; absent unresolved(); endmodule",
        "b.v": "module omitted; endmodule",
    }, {"maxFiles": 1})
    opened = tree(views)
    assert "分析不完整" in opened["summary"]["statsText"]
    assert "1 个未解析引用" in opened["summary"]["statsText"]
    diagnostic_root = opened["initialWindow"]["nodes"][2]
    codes = {badge["text"] for node in children(views, opened, diagnostic_root["id"]) for badge in node["badges"]}
    assert {"missing_module", "file_count_limit"} <= codes
