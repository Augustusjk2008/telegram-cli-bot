from pathlib import Path

from bot.assistant_home import ASSISTANT_SCHEMA_VERSION, bootstrap_assistant_home, load_assistant_home


def test_bootstrap_assistant_home_creates_manifest_and_required_directories(tmp_path: Path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()

    home = bootstrap_assistant_home(workdir)

    assert home.root == workdir / ".assistant"
    assert home.manifest_path.is_file()
    assert (home.root / "state" / "users").is_dir()
    assert (home.root / "memory" / "knowledge").is_dir()
    assert (home.root / "proposals").is_dir()
    assert (home.root / "upgrades" / "pending").is_dir()


def test_load_assistant_home_reads_existing_manifest(tmp_path: Path):
    workdir = tmp_path / "assistant-root"
    workdir.mkdir()
    created = bootstrap_assistant_home(workdir)

    loaded = load_assistant_home(workdir)

    assert loaded.assistant_id == created.assistant_id
    assert loaded.schema_version == ASSISTANT_SCHEMA_VERSION
