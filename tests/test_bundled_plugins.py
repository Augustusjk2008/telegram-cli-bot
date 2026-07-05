from __future__ import annotations

from pathlib import Path

from bot.plugins.manifest import load_plugin_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_PLUGINS_ROOT = REPO_ROOT / "examples" / "plugins"


def test_bundled_plugin_manifests_load_with_basic_contracts() -> None:
    manifest_paths = sorted(BUNDLED_PLUGINS_ROOT.glob("*/plugin.json"))
    assert manifest_paths, "expected bundled plugin manifests"

    seen_ids: set[str] = set()
    for manifest_path in manifest_paths:
        manifest = load_plugin_manifest(manifest_path)

        assert manifest.root == manifest_path.parent.resolve()
        assert manifest.plugin_id
        assert manifest.plugin_id not in seen_ids
        seen_ids.add(manifest.plugin_id)
        assert manifest.schema_version == 2
        assert manifest.name
        assert manifest.version

        assert manifest.runtime.runtime_type
        assert manifest.runtime.entry
        assert manifest.runtime.protocol
        assert (manifest.root / manifest.runtime.entry).is_file()

        view_ids = {view.id for view in manifest.views}
        assert view_ids
        for view in manifest.views:
            assert view.title
            assert view.renderer
            assert view.view_mode in {"snapshot", "session"}
            assert view.data_profile in {"light", "heavy"}

        for handler in manifest.file_handlers:
            assert handler.id
            assert handler.label
            assert handler.view_id in view_ids
            assert handler.extensions
            assert all(extension.startswith(".") for extension in handler.extensions)
