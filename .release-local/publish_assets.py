"""Publish native release files without replacing assets from another platform."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def publish(repo: str, tag: str, files: list[Path], notes: Path | None) -> None:
    response = subprocess.run(["gh", "api", f"repos/{repo}/releases/tags/{tag}"], capture_output=True, text=True)
    if response.returncode:
        if "HTTP 404" not in response.stderr:
            raise SystemExit(response.stderr.strip() or response.returncode)
        cmd = ["gh", "release", "create", tag, "--repo", repo, "--verify-tag", "--title", tag]
        cmd += ["--notes-file", str(notes)] if notes else ["--generate-notes"]
        subprocess.run([*cmd, *files], check=True)
        return

    release = json.loads(response.stdout)
    if release["draft"]:
        raise SystemExit("An unpublished draft already owns this tag. Check the draft before adding assets.")
    assets = {item["name"]: item for item in release["assets"]}
    missing = []
    for path in files:
        asset = assets.get(path.name)
        if asset is None:
            missing.append(path)
        elif asset.get("digest") != sha256(path):
            raise SystemExit(f"Published file differs from the local build: {path.name}")
    if missing:
        subprocess.run(["gh", "release", "upload", tag, "--repo", repo, *missing], check=True)
    print(release["html_url"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    publish(args.repo, args.tag, args.files, args.notes_file)
