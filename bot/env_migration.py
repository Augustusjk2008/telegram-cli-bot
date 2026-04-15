from __future__ import annotations

import argparse
import re
from pathlib import Path


_LEGACY_WEB_HOST = "127.0.0.1"
_WILDCARD_WEB_HOST = "0.0.0.0"
_UTF8_BOM = b"\xef\xbb\xbf"
_WEB_HOST_LINE_RE = re.compile(r"^\s*WEB_HOST\s*=\s*(?P<value>.+?)\s*$")


def _unquote_env_value(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def migrate_legacy_web_host(env_path: str | Path) -> bool:
    path = Path(env_path)
    if not path.exists():
        return False

    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(_UTF8_BOM) else "utf-8"
    text = raw.decode(encoding)
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]

    changed = False
    migrated_lines: list[str] = []

    for line in lines:
        line_body = line.rstrip("\r\n")
        line_ending = line[len(line_body):]
        stripped = line_body.lstrip()
        if stripped.startswith("#"):
            migrated_lines.append(line)
            continue

        match = _WEB_HOST_LINE_RE.match(line_body)
        if match and _unquote_env_value(match.group("value")) == _LEGACY_WEB_HOST:
            migrated_lines.append(f"WEB_HOST={_WILDCARD_WEB_HOST}{line_ending}")
            changed = True
            continue

        migrated_lines.append(line)

    if not changed:
        return False

    path.write_text("".join(migrated_lines), encoding=encoding, newline="")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy CLI Bridge .env values.")
    parser.add_argument("--env-path", default=".env", help="Path to the .env file to migrate.")
    args = parser.parse_args(argv)
    migrate_legacy_web_host(args.env_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
