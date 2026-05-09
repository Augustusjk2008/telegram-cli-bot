from __future__ import annotations

from aiohttp import web


def register(app: web.Application, server) -> None:
    app.router.add_get("/api/bots/{alias}/pwd", server.get_pwd)
    app.router.add_get("/api/bots/{alias}/ls", server.get_ls)
    app.router.add_get("/api/bots/{alias}/workspace/quick-open", server.get_workspace_quick_open)
    app.router.add_get("/api/bots/{alias}/workspace/search", server.get_workspace_search)
    app.router.add_get("/api/bots/{alias}/workspace/outline", server.get_workspace_outline)
    app.router.add_post(
        "/api/bots/{alias}/workspace/resolve-definition",
        server.post_workspace_resolve_definition,
    )
    app.router.add_post("/api/bots/{alias}/cd", server.post_cd)
    app.router.add_post("/api/bots/{alias}/files/upload", server.upload_file)
    app.router.add_post("/api/bots/{alias}/chat/attachments", server.upload_chat_attachment)
    app.router.add_post("/api/bots/{alias}/chat/attachments/delete", server.delete_chat_attachment_view)
    app.router.add_post("/api/bots/{alias}/files/mkdir", server.create_directory_view)
    app.router.add_post("/api/bots/{alias}/files/reveal", server.post_files_reveal)
    app.router.add_post("/api/bots/{alias}/files/write", server.write_file_view)
    app.router.add_post("/api/bots/{alias}/files/create", server.create_text_file_view)
    app.router.add_post("/api/bots/{alias}/files/rename", server.rename_path_view)
    app.router.add_post("/api/bots/{alias}/files/copy", server.copy_path_view)
    app.router.add_post("/api/bots/{alias}/files/move", server.move_path_view)
    app.router.add_post("/api/bots/{alias}/files/delete", server.delete_path_view)
    app.router.add_get("/api/bots/{alias}/files/download", server.download_file)
    app.router.add_get("/api/bots/{alias}/files/read", server.read_file)

