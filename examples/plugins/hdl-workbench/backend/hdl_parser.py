"""Parse Host-supplied UTF-8 source without reading the filesystem."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Iterator

from hdl_models import Connection, Diagnostic, Instance, Module, Parameter, ParseResult, Port, SourceLocation

if TYPE_CHECKING:
    from tree_sitter import Node


DEPENDENCIES = {"tree-sitter": "0.26.0", "tree-sitter-verilog": "1.0.3"}
IDENTIFIERS = {"simple_identifier", "escaped_identifier"}
PARAMETER_TYPES = {"parameter_declaration", "local_parameter_declaration"}
INSTANCE_TYPES = {"module_instantiation", "checker_instantiation", "udp_instantiation",
                  "program_instantiation", "interface_instantiation"}
SCOPES = {
    "module_declaration", "interface_declaration", "program_declaration",
    "package_declaration", "class_declaration", "checker_declaration",
    "function_declaration", "task_declaration", "always_construct", "initial_construct",
    "final_construct", "sequential_block", "parallel_block",
}


def walk(node: Node, *, stop: set[str] | frozenset[str] = frozenset()) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        if current.type not in stop:
            stack.extend(reversed(current.named_children))


def first(node: Node, types: set[str]) -> Node | None:
    return next((child for child in node.named_children if child.type in types), None)


class HdlParser:
    def __init__(self) -> None:
        requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
        install = f'"{sys.executable}" -m pip install -r "{requirements}"'
        if sys.platform == "win32":
            install = f"& {install}"
        try:
            for package, expected in DEPENDENCIES.items():
                actual = version(package)
                if actual != expected:
                    raise ValueError(f"{package}=={actual}，需要 {expected}")
            bindings = import_module("tree_sitter")
            grammar = import_module("tree_sitter_verilog")
            self._parser = bindings.Parser(bindings.Language(grammar.language()))
        except (PackageNotFoundError, ImportError, OSError, AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"HDL Workbench 解析依赖缺失或不兼容：{exc}。请使用插件运行时的 Python 安装：{install}"
            ) from exc

    def parse(self, path: str, content: str | bytes) -> ParseResult:
        if isinstance(content, str):
            source = content.encode("utf-8")
        else:
            source = content
        try:
            source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("HDL 源码必须为 UTF-8；请先转换文件编码") from exc
        tree = self._parser.parse(source)
        return _Extraction(path, source).extract(tree.root_node)


class _Extraction:
    def __init__(self, path: str, source: bytes) -> None:
        self.path = path
        self.source = source
        self.line_starts = [0] + [index + 1 for index, byte in enumerate(source) if byte == 10]
        self.recovered: set[int] = set()
        self.diagnostics: list[Diagnostic] = []
        self.macro_offsets: list[int] = []
        self.macro_contexts: list[tuple[str, ...]] = []

    def text(self, node: Node | None) -> str:
        return self.source[node.start_byte:node.end_byte].decode("utf-8").strip() if node else ""

    def location(self, node: Node) -> SourceLocation:
        return self.range_location(node.start_byte, node.end_byte)

    def range_location(self, start: int, end: int) -> SourceLocation:
        start_row = bisect_right(self.line_starts, start) - 1
        end_row = bisect_right(self.line_starts, end) - 1
        # Editor columns count UTF-16 code units; Tree-sitter columns count bytes.
        start_column = len(self.source[self.line_starts[start_row]:start].decode("utf-8").encode("utf-16-le")) // 2 + 1
        end_column = len(self.source[self.line_starts[end_row]:end].decode("utf-8").encode("utf-16-le")) // 2 + 1
        return SourceLocation(self.path, start_row + 1, start_column, end_row + 1, end_column, start, end)

    def warn(self, node: Node, code: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(code, message, "warning", self.location(node)))

    def recover(self, node: Node) -> None:
        self.recovered.update(item.id for item in walk(node))

    def contexts(self, node: Node) -> tuple[str, ...]:
        offset = bisect_right(self.macro_offsets, node.start_byte) - 1
        contexts = list(self.macro_contexts[offset]) if offset >= 0 else []
        generated: list[str] = []
        child = node
        ancestor = node.parent
        while ancestor is not None and ancestor.type != "module_declaration":
            if ancestor.type == "generate_region":
                generated.append("generate")
            elif ancestor.type in {"if_generate_construct", "loop_generate_construct", "case_generate_construct"}:
                block = first(ancestor, {"generate_block", "case_generate_item"})
                end = block.start_byte if block else ancestor.end_byte
                label = self.source[ancestor.start_byte:end].decode("utf-8").strip()
                blocks = [item for item in ancestor.named_children if item.type == "generate_block"]
                if ancestor.type == "if_generate_construct" and len(blocks) > 1 and child == blocks[-1]:
                    label = f"else of {label}"
                generated.append(label)
            child, ancestor = ancestor, ancestor.parent
        return tuple(contexts + list(reversed(generated)))

    def macro_conditions(self, root: Node) -> None:
        stack: list[tuple[str, str]] = []
        for node in walk(root):
            if node.type not in {"id_directive", "zero_directive"}:
                continue
            text = self.text(node)
            directive = text.split(maxsplit=1)[0]
            if directive in {"`ifdef", "`ifndef"}:
                stack.append((text, text))
                self.warn(node, "unexpanded_macro_condition", "宏条件未求值；保留各分支的静态声明")
            elif directive in {"`elsif", "`else"} and stack:
                opening, _ = stack[-1]
                stack[-1] = (opening, f"{text} of {opening}")
            elif directive == "`endif" and stack:
                stack.pop()
            else:
                continue
            self.macro_offsets.append(node.end_byte)
            self.macro_contexts.append(tuple(branch for _, branch in stack))

    def type_parts(self, node: Node | None) -> tuple[str, str]:
        if node is None:
            return "", ""
        excluded_types = {"packed_dimension", "port_direction", "comment"}
        excluded = [item for item in walk(node, stop={"struct_union_member", "enum_base_type"} | excluded_types)
                    if item.type in {"packed_dimension", "port_direction", "comment"}]
        dimensions = [self.text(item) for item in excluded if item.type == "packed_dimension"]
        cursor = node.start_byte
        pieces: list[str] = []
        for item in excluded:
            pieces.append(self.source[cursor:item.start_byte].decode("utf-8"))
            cursor = item.end_byte
        pieces.append(self.source[cursor:node.end_byte].decode("utf-8"))
        return " ".join(piece.strip() for piece in pieces if piece.strip()), " ".join(dimensions)

    def ansi_ports(self, header: Node) -> list[Port]:
        ports: list[Port] = []
        direction: str | None = None
        type_expression = width_expression = ""
        type_location = None
        for declaration in walk(header, stop={"parameter_port_list"}):
            if declaration.type != "ansi_port_declaration":
                continue
            identifier = first(declaration, {"port_identifier"})
            if identifier is None or not self.text(identifier):
                self.warn(declaration, "unsupported_port", "未能提取此端口声明；请查看源码")
                continue
            port_header = first(declaration, {"variable_port_header", "net_port_header1", "interface_port_header"})
            if port_header is not None:
                direction_node = next((item for item in walk(port_header) if item.type == "port_direction"), None)
                if direction_node is not None:
                    direction = self.text(direction_node)
                type_expression, width_expression = self.type_parts(port_header)
                type_location = self.location(port_header)
            default = first(declaration, {"constant_expression", "expression"})
            ports.append(Port(
                self.text(identifier), direction, type_expression, width_expression,
                tuple(self.text(item) for item in declaration.named_children if item.type in {"unpacked_dimension", "variable_dimension"}),
                self.text(default) if default else None, self.location(identifier), type_location,
                self.contexts(identifier),
            ))
        return ports

    def nonansi_ports(self, header: Node | None, body: list[Node]) -> list[Port]:
        ports: list[Port] = []
        for declaration in body:
            if declaration.type not in {"input_declaration", "output_declaration", "inout_declaration", "ref_declaration"}:
                continue
            port_type = first(declaration, {"net_port_type1", "variable_port_type", "data_type", "data_type_or_implicit1"})
            type_expression, width_expression = self.type_parts(port_type)
            identifiers = next((item for item in declaration.named_children if item.type.startswith("list_of_")), None)
            if identifiers is None:
                continue
            for group in self.connection_groups(identifiers, allow_empty=False):
                identifier = next((item for item in group if item.type == "port_identifier"), None)
                if identifier is None:
                    continue
                dimensions = tuple(self.text(item) for item in group
                                   if item.type in {"unpacked_dimension", "variable_dimension"})
                default = next((item for item in group if item.type in {"constant_expression", "expression"}), None)
                ports.append(Port(
                    self.text(identifier), declaration.type.removesuffix("_declaration"),
                    type_expression, width_expression, dimensions, self.text(default) if default else None,
                    self.location(identifier),
                    self.location(port_type) if port_type else None, self.contexts(identifier),
                ))
        # Verilog permits a separate net/variable declaration for an output port.
        for declaration in body:
            if declaration.type not in {"data_declaration", "net_declaration"}:
                continue
            type_nodes = [item for item in declaration.named_children
                          if item.type in {"data_type_or_implicit1", "data_type", "net_type"}]
            parts = [self.type_parts(item) for item in type_nodes]
            type_expression = " ".join(part[0] for part in parts if part[0])
            width_expression = " ".join(part[1] for part in parts if part[1])
            type_location = self.range_location(type_nodes[0].start_byte, type_nodes[-1].end_byte) if type_nodes else None
            for assignment in walk(declaration):
                if assignment.type not in {"variable_decl_assignment", "net_decl_assignment"}:
                    continue
                identifier = first(assignment, IDENTIFIERS)
                for index, port in enumerate(ports):
                    if self.text(identifier) == port.name and self.contexts(assignment) == port.contexts:
                        ports[index] = replace(port, type_expression=type_expression or port.type_expression,
                                               width_expression=width_expression or port.width_expression,
                                               type_location=type_location or port.type_location)
        ordered: list[Port] = []
        if header is not None:
            for entry in walk(header, stop={"parameter_port_list"}):
                if entry.type != "port":
                    continue
                references = [item for item in walk(entry) if item.type == "port_identifier"]
                if len(references) != 1 or any(child.type == "." for child in entry.children):
                    self.warn(entry, "unsupported_port", "非 ANSI 端口别名或复合表达式尚未提取；请查看源码")
                    continue
                identifier = references[0]
                matches = [port for port in ports if port.name == self.text(identifier)]
                if matches:
                    ordered.extend(matches)
                else:
                    ordered.append(Port(self.text(identifier), None, "", "", (), None, self.location(identifier),
                                        contexts=self.contexts(identifier)))
                    self.warn(identifier, "undeclared_port", "端口缺少方向声明，解析信息不完整")
        return ordered or ports

    def parameters(self, declaration: Node, *, inherited: tuple[str, str] = ("parameter", "")) -> list[Parameter]:
        kind, type_expression = inherited
        explicit = first(declaration, PARAMETER_TYPES) if declaration.type == "parameter_port_declaration" else declaration
        if declaration.type == "list_of_param_assignments":
            explicit = None
        node = explicit if explicit is not None else declaration
        assignments = node if node.type == "list_of_param_assignments" else first(node, {"list_of_param_assignments", "list_of_type_assignments"})
        if assignments is None:
            return []
        if explicit is not None:
            kind = "localparam" if explicit.type == "local_parameter_declaration" else "parameter"
            type_node = first(node, {"data_type_or_implicit1", "data_type"})
            type_expression = self.text(type_node)
            if assignments.type == "list_of_type_assignments":
                type_expression = "type"
        parameters: list[Parameter] = []
        for assignment in assignments.named_children:
            if assignment.type not in {"param_assignment", "type_assignment"}:
                continue
            identifier = first(assignment, {"parameter_identifier"} | IDENTIFIERS)
            if identifier is None:
                continue
            if not self.text(identifier):
                # Grammar 1.0.3 mistakes an inherited name for a type and inserts a missing name.
                candidate = first(node, {"data_type"})
                if (explicit is None and candidate is not None and len(candidate.named_children) == 1
                        and candidate.named_children[0].type in IDENTIFIERS):
                    self.recover(identifier)
                    identifier = candidate.named_children[0]
                else:
                    continue
            elif explicit is None:
                type_expression = self.text(first(node, {"data_type"}))
            default = first(assignment, {"constant_param_expression", "data_type"})
            parameters.append(Parameter(self.text(identifier), kind, type_expression,
                                        self.text(default) if default else None, self.location(identifier),
                                        self.contexts(identifier)))
        return parameters

    def connection_groups(self, container: Node, *, allow_empty: bool) -> list[list[Node]]:
        groups: list[list[Node]] = [[]]
        depth = 0
        named = any(item.type in {"named_port_connection", "formal_port_identifier"}
                    for item in container.named_children)
        for node in container.children:
            if node.type in {"comment", "attribute_instance"}:
                continue
            if allow_empty and not named and node.is_error and self.text(node) == ",":
                self.recover(node)
                groups.append([])
            elif node.type == "," and depth == 0:
                groups.append([])
            else:
                groups[-1].append(node)
                if node.type == "(":
                    depth += 1
                elif node.type == ")":
                    depth -= 1
        return groups if any(groups) or len(groups) > 1 else []

    def connections(self, container: Node, *, allow_empty: bool = False) -> tuple[Connection, ...]:
        result: list[Connection] = []
        groups = self.connection_groups(container, allow_empty=allow_empty)
        previous_end = container.start_byte
        for position, group in enumerate(groups):
            if not group:
                result.append(Connection(None, "", position, self.range_location(previous_end, previous_end)))
                continue
            wrapper = group[0]
            nodes = wrapper.children if wrapper.type in {"named_port_connection", "named_parameter_assignment"} else group
            name_node = next((item for item in nodes if item.type in {"port_identifier", "parameter_identifier", "formal_port_identifier"}), None)
            if name_node is not None:
                name = self.text(name_node)
                expression_node = next((item for item in nodes if item.type in {"expression", "param_expression", "property_expr"}), None)
                expression = self.text(expression_node) if expression_node else ("" if any(item.type == "(" for item in nodes) else name)
            elif any(item.type in {".*", "*"} for item in nodes):
                name, expression = "*", None
            else:
                name = None
                expression = self.source[group[0].start_byte:group[-1].end_byte].decode("utf-8").strip()
            location = self.range_location(group[0].start_byte, group[-1].end_byte)
            result.append(Connection(name, expression, position, location))
            previous_end = group[-1].end_byte
        return tuple(result)

    def instance_connections(self, instance: Node) -> tuple[Connection, ...]:
        connections = first(instance, {"list_of_port_connections"})
        if connections is not None:
            return self.connections(connections, allow_empty=True)
        # Checker/UDP parses expose the argument tokens directly instead of a list node.
        opening = next((child for child in instance.children if child.type == "("), None)
        closing = next((child for child in reversed(instance.children) if child.type == ")"), None)
        if opening is None or closing is None:
            return ()
        return self.connections(_ArgumentNodes(instance, opening.end_byte, closing.start_byte), allow_empty=True)

    def instances(self, declaration: Node) -> list[Instance]:
        target = first(declaration, IDENTIFIERS | {"checker_identifier", "program_identifier", "interface_identifier"})
        if target is None:
            return []
        overrides = first(declaration, {"parameter_value_assignment"})
        assignments = first(overrides, {"list_of_parameter_assignments"}) if overrides else None
        parameter_overrides = self.connections(assignments) if assignments else ()
        kind = {"module_instantiation": "module", "checker_instantiation": "module_or_checker",
                "udp_instantiation": "module_or_primitive", "program_instantiation": "module_or_program",
                "interface_instantiation": "module_or_interface"}[declaration.type]
        nodes = [declaration] if declaration.type == "checker_instantiation" else [
            child for child in declaration.named_children if child.type in {"hierarchical_instance", "udp_instance"}
        ]
        result: list[Instance] = []
        for node in nodes:
            name = first(node, {"name_of_instance"})
            identifier = first(name, {"instance_identifier"}) if name else None
            if identifier is None or not self.text(identifier):
                continue
            result.append(Instance(
                self.text(identifier), self.text(target), kind, self.instance_connections(node), parameter_overrides,
                tuple(self.text(item) for item in name.named_children if item.type == "unpacked_dimension"),
                self.location(identifier), self.contexts(node),
            ))
        return result

    def module(self, node: Node) -> Module | None:
        header = first(node, {"module_header"})
        identifier = first(header, IDENTIFIERS) if header else None
        if identifier is None or not self.text(identifier):
            return None
        port_header = first(node, {"module_ansi_header", "module_nonansi_header"})
        body = [item for child in node.named_children if child not in {header, port_header}
                for item in walk(child, stop=SCOPES | PARAMETER_TYPES | INSTANCE_TYPES)]
        ports = self.ansi_ports(port_header) if port_header and port_header.type == "module_ansi_header" else self.nonansi_ports(port_header, body)
        parameters: list[Parameter] = []
        if port_header is not None:
            parameter_list = first(port_header, {"parameter_port_list"})
            if parameter_list is not None:
                inherited = ("parameter", "")
                for declaration in parameter_list.named_children:
                    if declaration.type not in {"parameter_port_declaration", "list_of_param_assignments"}:
                        continue
                    parsed = self.parameters(declaration, inherited=inherited)
                    parameters.extend(parsed)
                    if parsed:
                        inherited = parsed[-1].kind, parsed[-1].type_expression
        parameters.extend(parameter for item in body if item.type in PARAMETER_TYPES for parameter in self.parameters(item))
        instances = [instance for item in body if item.type in INSTANCE_TYPES for instance in self.instances(item)]
        for item in body:
            if item.type in {"generate_region", "if_generate_construct", "case_generate_construct", "loop_generate_construct"}:
                self.warn(item, "unelaborated_generate", "generate 未展开；实例及条件保留源码表达式")
        return Module(self.text(identifier), self.location(identifier), tuple(ports), tuple(parameters), tuple(instances),
                      False, self.contexts(identifier))

    def syntax_diagnostics(self, root: Node) -> None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.id in self.recovered:
                continue
            if node.is_error or node.is_missing:
                message = f"缺少 {node.type}" if node.is_missing else "语法区域未能解析（宏未展开时也可能出现）；此文件解析不完整"
                self.diagnostics.append(Diagnostic("syntax_error", message, "error", self.location(node)))
                if node.is_error:
                    continue
            stack.extend(reversed(node.children))

    def extract(self, root: Node) -> ParseResult:
        self.macro_conditions(root)
        definitions = [node for node in walk(root, stop=SCOPES) if node.type == "module_declaration"]
        parsed = [(self.module(node), node) for node in definitions]
        self.syntax_diagnostics(root)
        incomplete_locations = [item.location.start_byte for item in self.diagnostics
                                if item.severity == "error" or item.code in {"unsupported_port", "undeclared_port"}]
        modules = tuple(replace(module, incomplete=any(node.start_byte <= offset <= node.end_byte
                                                      for offset in incomplete_locations))
                        for module, node in parsed if module is not None)
        diagnostics = tuple(sorted(self.diagnostics, key=lambda item: item.location.start_byte))
        return ParseResult(self.path, modules, diagnostics, any(module.incomplete for module in modules)
                           or any(item.severity == "error" for item in diagnostics))


class _ArgumentNodes:
    """A view of original syntax children, retaining their byte positions."""

    def __init__(self, node: Node, start: int, end: int) -> None:
        self.start_byte = start
        self.end_byte = end
        self.children = [child for child in node.children if child.start_byte >= start and child.end_byte <= end]
        self.named_children = [child for child in self.children if child.is_named]
