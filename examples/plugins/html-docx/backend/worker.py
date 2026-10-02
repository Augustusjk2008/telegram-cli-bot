"""One conversion stage per process; all HTML and image data arrive via stdin."""
from __future__ import annotations

import base64
import importlib.util
import json
import sys

DEPENDENCIES = {
    "docx": "python-docx", "lxml": "lxml", "tinycss2": "tinycss2",
    "cssselect2": "cssselect2", "PIL": "Pillow", "resvg_py": "resvg_py",
}


def handle(payload: dict) -> dict:
    missing = [package for module, package in DEPENDENCIES.items() if importlib.util.find_spec(module) is None]
    if missing:
        return {"ok": False, "error": "缺少转换依赖: " + ", ".join(missing), "missingDependencies": missing}
    import converter

    source = base64.b64decode(payload["sourceBase64"], validate=True)
    resources = payload.get("resources")
    if resources is not None:
        resources = {name: base64.b64decode(content, validate=True) for name, content in resources.items()}
    config = payload["config"]
    if len(source) > config["maxSourceBytes"]:
        raise ValueError("HTML 文件超过源文件限额")
    if sum(len(content) for content in (resources or {}).values()) > config["maxResourceBytes"]:
        raise ValueError("图片资源总量超过限额")
    operation = payload.get("operation")
    if operation == "inspect":
        return {"ok": True, "report": converter.inspect_html(source, resources=resources, config=config)}
    if operation != "export":
        raise ValueError(f"不支持的转换操作: {operation}")
    content, report = converter.export_docx(source, resources=resources, config=config)
    if report.get("errors"):
        return {"ok": True, "report": report}
    if not content or len(content) > int(payload["maxArtifactBytes"]):
        raise ValueError("DOCX 产物为空或超过宿主限额")
    return {"ok": True, "report": report, "contentBase64": base64.b64encode(content).decode("ascii")}


if __name__ == "__main__":
    try:
        result = handle(json.loads(sys.stdin.buffer.read()))
    except ImportError as exc:
        result = {"ok": False, "error": f"缺少转换依赖或无法加载: {exc}",
                  "missingDependencies": [exc.name or "转换依赖"]}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
