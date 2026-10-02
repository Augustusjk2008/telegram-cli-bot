"""Static HDL structure; expressions are source text, never evaluated."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SourceLocation:
    path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_byte: int
    end_byte: int


@dataclass(frozen=True)
class Port:
    name: str
    direction: str | None
    type_expression: str
    width_expression: str
    unpacked_dimensions: tuple[str, ...]
    default_expression: str | None
    location: SourceLocation
    type_location: SourceLocation | None = None
    contexts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Parameter:
    name: str
    kind: str
    type_expression: str
    default_expression: str | None
    location: SourceLocation
    contexts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Connection:
    name: str | None
    expression: str | None
    position: int
    location: SourceLocation


@dataclass(frozen=True)
class Instance:
    name: str
    module_name: str
    reference_kind: str
    connections: tuple[Connection, ...]
    parameter_overrides: tuple[Connection, ...]
    array_dimensions: tuple[str, ...]
    location: SourceLocation
    contexts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Module:
    name: str
    location: SourceLocation
    ports: tuple[Port, ...]
    parameters: tuple[Parameter, ...]
    instances: tuple[Instance, ...]
    incomplete: bool
    contexts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: str
    location: SourceLocation


@dataclass(frozen=True)
class ParseResult:
    path: str
    modules: tuple[Module, ...]
    diagnostics: tuple[Diagnostic, ...]
    incomplete: bool

    def to_dict(self) -> dict:
        return asdict(self)
