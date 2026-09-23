"""Bounded agent operations on the Web host's shared SSH connection."""
from __future__ import annotations

from bot.remote_workspace import windows
from bot.remote_workspace.chat import validate_tool_arguments
from bot.remote_workspace.transport import RemoteWorkspaceError, get_remote_workspace_service, join_remote_path


def resolve_remote_directory(connection, path: str, root: str, platform: str = "posix") -> str:
    candidate = join_remote_path(root, path, platform)
    if candidate != root and not candidate.startswith(root.rstrip("/") + "/"):
        raise RemoteWorkspaceError(403, "forbidden_path", "Path escapes the remote workspace root")
    directory = connection.canonical_root(candidate)
    if directory != root and not directory.startswith(root.rstrip("/") + "/"):
        raise RemoteWorkspaceError(403, "forbidden_path", "Path escapes the remote workspace root")
    return directory


def execute_remote_tool(config: dict, tool: str, arguments: dict) -> dict:
    args = validate_tool_arguments(tool, arguments)
    connection = get_remote_workspace_service().get(config)
    root = config["root"]
    if tool == "exec":
        directory = resolve_remote_directory(connection, args["cwd"], root, config.get("platform", "posix"))
        command = windows.batch(args["commands"]) if config.get("platform") == "windows" else "set -e\n" + "\n".join(args["commands"])
        return connection.execute(
            command, root=directory,
            timeout=args["timeout_seconds"], max_output=args["max_output_chars"],
        )
    if tool == "list":
        data = connection.list_directory(args["path"], root=root)
        entries = data["entries"]
        selected = []
        characters = 0
        for entry in entries[:args["max_entries"]]:
            characters += len(str(entry.get("name") or ""))
            if characters > 64000:
                break
            selected.append(entry)
        return {"path": data["working_dir"], "entries": selected, "truncated": len(selected) < len(entries)}
    if tool == "read":
        data = connection.read_file(args["path"], root=root, offset=args["offset"], limit=args["limit"])
        content = data["content"]
        truncated = len(content) > args["max_chars"]
        return {
            "path": data.get("path", args["path"]), "content": content[:args["max_chars"]],
            "offset": args["offset"], "is_full_content": data.get("is_full_content", False) and not truncated,
            "truncated": truncated, "last_modified_ns": data["last_modified_ns"],
        }
    if tool == "write":
        return connection.write_file(args["path"], args["content"], root=root)
    if tool == "edit":
        data = connection.read_file(args["path"], root=root)
        if data["content"].count(args["old_text"]) != 1:
            raise RemoteWorkspaceError(409, "remote_edit_ambiguous", "old_text must match exactly once; read the current file before editing")
        content = data["content"].replace(args["old_text"], args["new_text"], 1)
        return connection.write_file(
            args["path"], content, root=root, expected_mtime_ns=data["last_modified_ns"],
            encoding=data.get("encoding", "utf-8"),
        )
    raise ValueError("Unknown remote tool")
