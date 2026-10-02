from __future__ import annotations

from hdl_parser import HdlParser
from plugin_sdk import PluginServer


server = PluginServer("hdl-workbench")
parser: HdlParser | None = None


def initialize(_context: dict) -> None:
    global parser
    parser = HdlParser()


def parse_source(params: dict) -> dict:
    if parser is None:
        raise RuntimeError("HDL Workbench 尚未初始化")
    path, content = params.get("path"), params.get("content")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("缺少 HDL 源码路径")
    if not isinstance(content, str):
        raise ValueError("缺少 Host 提供的 HDL 源码内容")
    return parser.parse(path, content).to_dict()


if __name__ == "__main__":
    server.register_handler("plugin.parse_source", parse_source)
    server.run(initialize=initialize)
