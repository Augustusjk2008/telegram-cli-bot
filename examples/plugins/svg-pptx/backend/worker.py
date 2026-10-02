"""One request per process; the source is supplied only through stdin."""

from __future__ import annotations

import base64
import importlib.util
import json
import sys


DEPENDENCIES = {
    "pptx": "python-pptx",
    "resvg_py": "resvg_py",
    "PIL": "Pillow",
    "tinycss2": "tinycss2",
    "cssselect2": "cssselect2",
    "defusedxml": "defusedxml",
}


def handle(payload: dict) -> dict:
    missing = [package for module, package in DEPENDENCIES.items() if importlib.util.find_spec(module) is None]
    if missing:
        return {"ok": False, "error": "缺少转换依赖: " + ", ".join(missing), "missingDependencies": missing}
    # Optional packages must never prevent the JSON-RPC adapter from starting.
    import converter

    if hasattr(converter, "dependency_status"):
        missing = converter.dependency_status()
        if missing:
            return {"ok": False, "error": "缺少转换依赖: " + ", ".join(missing), "missingDependencies": missing}
    source = base64.b64decode(payload["sourceBase64"], validate=True)
    config = payload.get("config") or {}
    if len(source) > config["maxSourceBytes"]:
        raise ValueError("SVG 文件超过源文件限额")
    operation = payload.get("operation")
    if operation == "inspect":
        return {"ok": True, "report": converter.inspect_svg(source, config)}
    if operation != "export":
        raise ValueError(f"不支持的转换操作: {operation}")
    content, report = converter.export_pptx(source, config)
    if report.get("errors"):
        return {"ok": True, "report": report}
    if len(content) > int(payload["maxArtifactBytes"]):
        raise ValueError("PPTX 产物大小超过宿主限额")
    return {"ok": True, "report": report, "contentBase64": base64.b64encode(content).decode("ascii")}


if __name__ == "__main__":
    try:
        result = handle(json.loads(sys.stdin.buffer.read()))
    except ImportError as exc:
        result = {"ok": False, "error": f"缺少转换依赖或无法加载: {exc}"}
        if exc.name != "converter":
            result["missingDependencies"] = [exc.name or "转换依赖"]
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
