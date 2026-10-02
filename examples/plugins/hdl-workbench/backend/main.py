from __future__ import annotations

from hdl_parser import HdlParser
from hdl_project import ProjectScanner, ScanOptions
from hdl_views import HdlViews
from plugin_sdk import PluginServer


server = PluginServer("hdl-workbench")
parser: HdlParser | None = None
views: HdlViews | None = None


def initialize(_context: dict) -> None:
    global parser
    shutdown()
    parser = HdlParser()


def session_views() -> HdlViews:
    global views
    if parser is None:
        raise RuntimeError("HDL Workbench 尚未初始化")
    if views is None:
        views = HdlViews(parser, server.host_call, server.context, server.config)
    return views


def shutdown() -> None:
    global parser, views
    if views is not None:
        views.shutdown()
    views = None
    parser = None


def parse_source(params: dict) -> dict:
    if parser is None:
        raise RuntimeError("HDL Workbench 尚未初始化")
    path, content = params.get("path"), params.get("content")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("缺少 HDL 源码路径")
    if not isinstance(content, str):
        raise ValueError("缺少 Host 提供的 HDL 源码内容")
    return parser.parse(path, content).to_dict()


def analyze_project(params: dict) -> dict:
    if parser is None:
        raise RuntimeError("HDL Workbench 尚未初始化")
    host = server.context.get("host") or {}
    workspace_root = host.get("workspaceRoot")
    if not isinstance(workspace_root, str) or not workspace_root:
        raise ValueError("Host 未提供 workspaceRoot")
    path = params.get("path", ".")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("缺少 HDL 项目目录")
    options = ScanOptions.from_config(server.config)
    scanner = ProjectScanner(parser, server.host_call, workspace_root, options,
                             host_read_bytes=(host.get("limits") or {}).get("readBytes", options.max_file_bytes))
    return scanner.scan(path).to_dict()


if __name__ == "__main__":
    server.register_handler("plugin.parse_source", parse_source)
    server.register_handler("plugin.analyze_project", analyze_project)
    server.register_handler("plugin.open_view", lambda params: session_views().open_view(params))
    server.register_handler("plugin.get_view_window", lambda params: session_views().get_view_window(params))
    server.register_handler("plugin.invoke_action", lambda params: session_views().invoke_action(params))
    server.register_handler("plugin.dispose_view", lambda params: session_views().dispose_view(params))
    server.run(initialize=initialize, shutdown=shutdown)
