"""Web 访问模式支持。"""

__all__ = ["WebApiServer"]


def __getattr__(name: str):
    if name == "WebApiServer":
        from .server import WebApiServer

        return WebApiServer
    raise AttributeError(name)
