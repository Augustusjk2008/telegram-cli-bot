from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "examples/plugins/hdl-workbench"


@pytest.fixture
def hdl_module(monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "backend"))
    spec = importlib.util.spec_from_file_location("tested_hdl_parser", PLUGIN / "backend/hdl_parser.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def parser(hdl_module):
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_verilog")
    return hdl_module.HdlParser()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_ansi_structure_expressions_and_real_source_locations(parser, newline):
    source = (PLUGIN / "samples/ports.sv").read_bytes().replace(b"\n", newline)
    result = parser.parse("rtl/ports.sv", source)

    assert not result.incomplete
    assert not result.diagnostics
    assert [module.name for module in result.modules] == ["top", "child"]
    top = result.modules[0]
    assert top.location.path == "rtl/ports.sv"
    assert top.location.start_line == 2
    assert [(port.name, port.direction, port.location.start_line) for port in top.ports] == [
        ("a", "input", 6), ("b", "input", 7), ("clk", "input", 8),
        ("result", "output", 9), ("data", "output", 10),
    ]
    assert [(port.type_expression, port.width_expression) for port in top.ports[:2]] == [
        ("logic signed", "[WIDTH-1:0]"), ("logic signed", "[WIDTH-1:0]"),
    ]
    assert top.ports[2].width_expression == ""
    assert top.ports[4].unpacked_dimensions == ("[DEPTH]",)
    assert [(param.name, param.kind, param.type_expression, param.default_expression) for param in top.parameters] == [
        ("WIDTH", "parameter", "int", "8"), ("DEPTH", "parameter", "int", "2"),
        ("T", "parameter", "type", "logic [WIDTH-1:0]"),
        ("OFFSET", "localparam", "integer", "1"), ("LAST", "localparam", "integer", "WIDTH - 1"),
    ]
    for item in (top, *top.ports, *top.parameters, *top.instances):
        location = item.location
        assert source[location.start_byte:location.end_byte].decode("utf-8") == item.name
    named, second, positional = top.instances
    assert [(item.name, item.module_name, item.location.start_line) for item in top.instances] == [
        ("u_named", "child", 14), ("u_second", "child", 15), ("u_positional", "child", 16),
    ]
    assert [(conn.name, conn.expression) for conn in named.connections] == [
        ("clk", "clk"), ("a", "a"), ("result", ""), ("*", None),
    ]
    assert named.parameter_overrides == second.parameter_overrides
    assert [(conn.name, conn.expression) for conn in named.parameter_overrides] == [("WIDTH", "WIDTH"), ("DEPTH", "DEPTH")]
    assert [(conn.position, conn.name, conn.expression) for conn in positional.connections] == [
        (0, None, "clk"), (1, None, ""), (2, None, "{a, b}"),
    ]
    assert [conn.expression for conn in positional.parameter_overrides] == ["WIDTH", "DEPTH"]
    json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False)


def test_nonansi_ports_merge_separate_variable_types_and_keep_declaration_locations(parser):
    result = parser.parse("classic.v", (PLUGIN / "samples/classic.v").read_bytes())

    assert not result.incomplete
    module, = result.modules
    assert module.name == "classic"
    assert [port.name for port in module.ports] == ["a", "b", "result", "clk"]
    result_port = module.ports[2]
    assert (result_port.direction, result_port.type_expression, result_port.width_expression) == ("output", "reg", "[8:0]")
    assert result_port.location.start_line == 5
    assert result_port.type_location.start_line == 6
    instance, = module.instances
    assert (instance.module_name, instance.name) == ("child", "u_child")
    assert [(conn.name, conn.expression) for conn in instance.connections] == [("a", "a"), ("clk", "clk")]


def test_grammar_ambiguity_keeps_named_implicit_wildcard_and_empty_positional_connections(parser):
    result = parser.parse("connections.sv", """module top;
child u_named (.a(a), .b, .z(), .*);
child u_pos (a, , c,);
child #() u_empty ();
endmodule
""")

    assert not result.incomplete
    named, positional, empty = result.modules[0].instances
    assert named.reference_kind == "module_or_checker"
    assert [(conn.name, conn.expression) for conn in named.connections] == [("a", "a"), ("b", "b"), ("z", ""), ("*", None)]
    assert positional.reference_kind == "module_or_primitive"
    assert [conn.expression for conn in positional.connections] == ["a", "", "c", ""]
    assert empty.connections == empty.parameter_overrides == ()


def test_grouped_header_parameters_inherit_type_and_kind_without_inventing_missing_names(parser):
    result = parser.parse("parameters.sv", """module params #(
parameter W=8, D=2, parameter int X=1, Y=3,
parameter type T=logic, U=int, localparam L=4, M=5) ();
parameter signed [W-1:0] V=2, Z=3;
endmodule
""")

    assert not result.incomplete
    assert [(param.name, param.kind, param.type_expression, param.default_expression) for param in result.modules[0].parameters] == [
        ("W", "parameter", "", "8"), ("D", "parameter", "", "2"),
        ("X", "parameter", "int", "1"), ("Y", "parameter", "int", "3"),
        ("T", "parameter", "type", "logic"), ("U", "parameter", "type", "int"),
        ("L", "localparam", "", "4"), ("M", "localparam", "", "5"),
        ("V", "parameter", "signed [W-1:0]", "2"), ("Z", "parameter", "signed [W-1:0]", "3"),
    ]


def test_legacy_parameter_header_and_separate_net_widths_are_not_omitted(parser):
    result = parser.parse("legacy.v", """module legacy #(W=8, D=2) (a, y, z);
input a;
wire [W-1:0] a;
output reg [7:0] y [0:D-1], z [0:3];
endmodule
""")

    assert not result.incomplete
    module, = result.modules
    assert [(param.name, param.default_expression) for param in module.parameters] == [("W", "8"), ("D", "2")]
    a, y, z = module.ports
    assert (a.type_expression, a.width_expression) == ("wire", "[W-1:0]")
    assert a.location.start_line == 2
    assert a.type_location.start_line == 3
    assert y.unpacked_dimensions == ("[0:D-1]",)
    assert z.unpacked_dimensions == ("[0:3]",)


def test_utf8_comments_and_editor_columns_do_not_shift_identifiers(parser):
    source = "/* 中文😀 module fake; endmodule */ module \\real.name (input a); endmodule\r\n"
    result = parser.parse("中文.sv", source)

    module, = result.modules
    assert module.name == "\\real.name"
    prefix = source[:source.index("\\real.name")]
    assert module.location.start_line == 1
    assert module.location.start_column == len(prefix.encode("utf-16-le")) // 2 + 1
    assert source.encode("utf-8")[module.location.start_byte:module.location.end_byte] == b"\\real.name"


def test_macro_and_generate_branches_retain_static_context_and_expressions(parser):
    result = parser.parse("conditional.sv", """`ifdef USE_ALT
module alt; endmodule
`else
module base(input a);
`ifdef USE_CHILD
child u_macro(.a(a));
`endif
generate
if (SIZE > 1) begin : many
  child u_generated[3:0] (.a(a));
end else begin : other
  child u_else(.a(a));
end
endgenerate
endmodule
`endif
""")

    assert not result.incomplete
    alt, base = result.modules
    assert alt.contexts == ("`ifdef USE_ALT",)
    assert base.contexts == ("`else of `ifdef USE_ALT",)
    macro, generated, alternative = base.instances
    assert macro.contexts[-1] == "`ifdef USE_CHILD"
    assert generated.array_dimensions == ("[3:0]",)
    assert generated.contexts[-2:] == ("generate", "if (SIZE > 1)")
    assert alternative.contexts[-1] == "else of if (SIZE > 1)"
    assert {diagnostic.code for diagnostic in result.diagnostics} == {"unexpanded_macro_condition", "unelaborated_generate"}


def test_callable_scope_declarations_and_comment_modules_are_excluded(parser):
    result = parser.parse("scopes.sv", """// module fake(input bad); endmodule
module visible(input logic a);
parameter WIDTH = 8;
function automatic logic foo(input logic hidden);
  parameter HIDDEN = 1;
endfunction
task helper(input x); endtask
child u (.x(foo(a)));
endmodule
""")

    module, = result.modules
    assert [port.name for port in module.ports] == ["a"]
    assert [param.name for param in module.parameters] == ["WIDTH"]
    assert module.instances[0].connections[0].expression == "foo(a)"


@pytest.mark.parametrize("broken", ["module broken(input logic a\nassign a = ;\nendmodule\n", "module broken #(parameter int = 2) (); endmodule\n"])
def test_real_syntax_errors_mark_only_affected_modules_incomplete(parser, broken):
    result = parser.parse("broken.sv", broken + "module good(input clk); endmodule\n")

    assert result.incomplete
    assert [module.name for module in result.modules] == ["broken", "good"]
    assert result.modules[0].incomplete
    assert not result.modules[1].incomplete
    errors = [item for item in result.diagnostics if item.code == "syntax_error"]
    assert errors and errors[0].location.path == "broken.sv"
    assert errors[0].location.start_line == 1


def test_missing_syntax_token_reports_a_real_zero_length_location(parser):
    source = "module m; assign a = 1 endmodule"
    result = parser.parse("missing.sv", source)

    assert result.incomplete
    diagnostic, = result.diagnostics
    assert diagnostic.code == "syntax_error"
    assert diagnostic.location.start_line == 1
    assert diagnostic.location.start_byte == diagnostic.location.end_byte == source.index(" endmodule")


def test_named_connection_syntax_errors_are_not_hidden_as_unconnected_ports(parser):
    result = parser.parse("bad.sv", "module m; child u (.a(a),, .b(b)); endmodule")
    assert result.incomplete
    assert any(item.code == "syntax_error" for item in result.diagnostics)


def test_non_utf8_source_is_rejected_without_replacement(parser):
    with pytest.raises(ValueError, match="UTF-8"):
        parser.parse("legacy.v", b"//\xff\nmodule m; endmodule")


@pytest.mark.parametrize("missing", [True, False])
def test_dependency_errors_name_the_runtime_python_and_install_command(hdl_module, monkeypatch, missing):
    def package_version(_name):
        if missing:
            raise hdl_module.PackageNotFoundError("tree-sitter")
        return "0.0.0"

    monkeypatch.setattr(hdl_module, "version", package_version)
    with pytest.raises(RuntimeError) as error:
        hdl_module.HdlParser()
    message = str(error.value)
    assert sys.executable in message
    assert str(PLUGIN / "requirements.txt") in message
    assert "-m pip install -r" in message


def test_copied_backend_parses_host_content_through_stdio(parser, tmp_path):
    copied = tmp_path / "hdl-workbench"
    shutil.copytree(PLUGIN, copied, ignore=shutil.ignore_patterns("__pycache__"))
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "plugin.initialize", "params": {"context": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "plugin.parse_source", "params": {"path": "rtl/中文.sv", "content": "// 中文\nmodule m(input a); endmodule"}},
        {"jsonrpc": "2.0", "id": 3, "method": "plugin.shutdown"},
    ]
    completed = subprocess.run(
        [sys.executable, str(copied / "backend/main.py")],
        input="\n".join(json.dumps(item, ensure_ascii=False) for item in requests) + "\n",
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        capture_output=True, encoding="utf-8", timeout=15, check=True,
    )
    initialized, parsed, stopped = [json.loads(line) for line in completed.stdout.splitlines()]
    assert initialized["result"]["ok"]
    assert parsed["result"]["modules"][0]["location"]["path"] == "rtl/中文.sv"
    assert parsed["result"]["modules"][0]["location"]["start_line"] == 2
    assert stopped["result"]["ok"]


def test_initialization_reports_missing_dependencies_over_stdio(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-S", str(PLUGIN / "backend/main.py")],
        input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "plugin.initialize"}) + "\n",
        cwd=tmp_path, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        capture_output=True, encoding="utf-8", timeout=15, check=True,
    )
    response = json.loads(completed.stdout)
    assert response["error"]["code"] == -32000
    assert "requirements.txt" in response["error"]["message"]
    assert "-m pip install -r" in response["error"]["message"]
