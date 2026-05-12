from pathlib import Path

from bot.plugins.installer import install_bundled_plugins


def _write_minimal_plugin(root: Path, plugin_id: str, *, name: str) -> None:
    plugin_dir = root / plugin_id
    backend_dir = plugin_dir / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (plugin_dir / "plugin.json").write_text(
        (
            "{\n"
            '  "schemaVersion": 1,\n'
            f'  "id": "{plugin_id}",\n'
            f'  "name": "{name}",\n'
            '  "version": "0.1.0",\n'
            '  "description": "install test plugin",\n'
            '  "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},\n'
            '  "views": [{"id": "preview", "title": "预览", "renderer": "waveform"}]\n'
            "}\n"
        ),
        encoding="utf-8",
    )


def test_install_bundled_plugins_installs_missing_and_skips_existing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    source_plugins_root = repo_root / "examples" / "plugins"
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    source_plugins_root.mkdir(parents=True)
    plugins_root.mkdir(parents=True)
    _write_minimal_plugin(source_plugins_root, "fresh-plugin", name="Fresh Plugin")
    _write_minimal_plugin(source_plugins_root, "existing-plugin", name="Existing Plugin")
    (plugins_root / "existing-plugin").mkdir()
    (plugins_root / "existing-plugin" / "plugin.json").write_text(
        (source_plugins_root / "existing-plugin" / "plugin.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    summary = install_bundled_plugins(
        repo_root=repo_root,
        plugins_root=plugins_root,
        source_plugins_root=source_plugins_root,
    )

    assert summary["installed"] == ["fresh-plugin"]
    assert summary["skipped"] == [{"id": "existing-plugin", "reason": "already_installed"}]
    assert (plugins_root / "fresh-plugin" / "plugin.json").exists()


def test_install_bundled_plugins_force_reinstalls_existing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    source_plugins_root = repo_root / "examples" / "plugins"
    plugins_root = tmp_path / "home" / ".tcb" / "plugins"
    source_plugins_root.mkdir(parents=True)
    plugins_root.mkdir(parents=True)
    _write_minimal_plugin(source_plugins_root, "existing-plugin", name="Existing Plugin")
    installed_dir = plugins_root / "existing-plugin"
    installed_dir.mkdir()
    (installed_dir / "plugin.json").write_text(
        (
            "{\n"
            '  "schemaVersion": 1,\n'
            '  "id": "existing-plugin",\n'
            '  "name": "Existing Plugin",\n'
            '  "version": "0.0.1",\n'
            '  "description": "old",\n'
            '  "runtime": {"type": "python", "entry": "backend/main.py", "protocol": "jsonrpc-stdio"},\n'
            '  "views": [{"id": "preview", "title": "预览", "renderer": "waveform"}]\n'
            "}\n"
        ),
        encoding="utf-8",
    )

    summary = install_bundled_plugins(
        repo_root=repo_root,
        plugins_root=plugins_root,
        source_plugins_root=source_plugins_root,
        force=True,
    )

    assert summary["installed"] == ["existing-plugin"]
    assert summary["skipped"] == []
    assert '"version": "0.1.0"' in (installed_dir / "plugin.json").read_text(encoding="utf-8")
