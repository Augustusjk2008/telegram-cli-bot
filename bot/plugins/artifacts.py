from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", str(filename or "").strip(), flags=re.UNICODE)
    return cleaned or "artifact.bin"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    bot_alias: str
    plugin_id: str
    filename: str
    path: Path
    size_bytes: int


class ArtifactStore:
    def __init__(self, repo_root: Path | str) -> None:
        self.root = Path(repo_root) / ".plugins" / "artifacts"
        self._records: dict[str, ArtifactRecord] = {}

    def write(self, *, bot_alias: str, plugin_id: str, filename: str, content: bytes) -> ArtifactRecord:
        artifact_id = f"artifact-{uuid.uuid4().hex}"
        target_dir = self.root / bot_alias / plugin_id
        target_dir.mkdir(parents=True, exist_ok=True)
        record = ArtifactRecord(
            artifact_id=artifact_id,
            bot_alias=bot_alias,
            plugin_id=plugin_id,
            filename=_sanitize_filename(filename),
            path=target_dir / f"{artifact_id}-{_sanitize_filename(filename)}",
            size_bytes=len(content),
        )
        record.path.write_bytes(content)
        self._records[artifact_id] = record
        return record

    def get(self, *, bot_alias: str, artifact_id: str) -> ArtifactRecord:
        record = self._records[artifact_id]
        if record.bot_alias != bot_alias:
            raise KeyError(f"未知插件产物: {bot_alias}/{artifact_id}")
        if not record.path.exists():
            raise KeyError(f"插件产物不存在: {artifact_id}")
        return record

    def clear_plugin(self, plugin_id: str, *, bot_alias: str | None = None) -> list[ArtifactRecord]:
        removed: list[ArtifactRecord] = []
        for artifact_id, record in list(self._records.items()):
            if record.plugin_id != plugin_id:
                continue
            if bot_alias is not None and record.bot_alias != bot_alias:
                continue
            self._records.pop(artifact_id, None)
            removed.append(record)
            try:
                record.path.unlink(missing_ok=True)
            except TypeError:
                if record.path.exists():
                    record.path.unlink()
        return removed

    def clear_all(self) -> None:
        for artifact_id, record in list(self._records.items()):
            self._records.pop(artifact_id, None)
            try:
                record.path.unlink(missing_ok=True)
            except TypeError:
                if record.path.exists():
                    record.path.unlink()
