from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .service import PluginService


async def _install_bundled_plugins_async(
    repo_root: Path | str,
    *,
    plugins_root: Path | str | None = None,
    source_plugins_root: Path | str | None = None,
    install_ids: Sequence[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    service = PluginService(
        repo_root=repo_root,
        plugins_root=plugins_root,
        source_plugins_root=source_plugins_root,
    )
    try:
        installable = service.list_installable_plugins()
        selected: list[dict[str, Any]] = []
        if install_ids:
            installable_by_key: dict[str, dict[str, Any]] = {}
            for item in installable:
                installable_by_key[str(item["id"])] = item
                installable_by_key[str(item["pluginId"])] = item
            seen_ids: set[str] = set()
            for raw_id in install_ids:
                normalized_id = str(raw_id or "").strip()
                if not normalized_id:
                    continue
                item = installable_by_key.get(normalized_id)
                if item is None:
                    raise KeyError(f"未找到可安装插件: {normalized_id}")
                canonical_id = str(item["id"])
                if canonical_id in seen_ids:
                    continue
                seen_ids.add(canonical_id)
                selected.append(item)
        else:
            selected = installable

        installed: list[str] = []
        skipped: list[dict[str, str]] = []
        for item in selected:
            install_id = str(item["id"])
            if bool(item.get("installed")) and not force:
                skipped.append({"id": install_id, "reason": "already_installed"})
                continue
            await service.install_plugin(install_id, force=force)
            installed.append(install_id)

        return {
            "pluginsRoot": str(service.plugins_root),
            "sourcePluginsRoot": str(service.source_plugins_root),
            "installed": installed,
            "skipped": skipped,
        }
    finally:
        await service.shutdown()


def install_bundled_plugins(
    repo_root: Path | str,
    *,
    plugins_root: Path | str | None = None,
    source_plugins_root: Path | str | None = None,
    install_ids: Sequence[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        _install_bundled_plugins_async(
            repo_root=repo_root,
            plugins_root=plugins_root,
            source_plugins_root=source_plugins_root,
            install_ids=install_ids,
            force=force,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="安装 examples/plugins 中的示例插件")
    parser.add_argument("--repo-root", default=".", help="仓库根目录")
    parser.add_argument("--plugins-root", default=None, help="目标插件目录")
    parser.add_argument("--source-plugins-root", default=None, help="源插件目录")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="安装全部示例插件")
    group.add_argument("--plugin", action="append", dest="plugins", default=None, help="安装指定插件，可重复传入")
    parser.add_argument("--force", action="store_true", help="覆盖已安装插件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    return parser


def _print_summary(summary: dict[str, Any]) -> None:
    installed = [str(item) for item in list(summary.get("installed") or [])]
    skipped = [dict(item) for item in list(summary.get("skipped") or []) if isinstance(item, dict)]
    if not installed and not skipped:
        print("未发现可安装示例插件")
        return
    for plugin_id in installed:
        print(f"已安装示例插件: {plugin_id}")
    for item in skipped:
        plugin_id = str(item.get("id") or "")
        reason = str(item.get("reason") or "")
        if plugin_id and reason == "already_installed":
            print(f"已跳过已安装插件: {plugin_id}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    install_ids = None if args.all else list(args.plugins or [])
    summary = install_bundled_plugins(
        repo_root=Path(args.repo_root).resolve(),
        plugins_root=Path(args.plugins_root).resolve() if args.plugins_root else None,
        source_plugins_root=Path(args.source_plugins_root).resolve() if args.source_plugins_root else None,
        install_ids=install_ids,
        force=bool(args.force),
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
