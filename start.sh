#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

resolve_user_home() {
  local user_name="$1"
  local home_dir=""

  if command -v getent >/dev/null 2>&1; then
    home_dir="$(getent passwd "$user_name" 2>/dev/null | awk -F: '{ print $6 }' || true)"
  fi
  if [[ -z "$home_dir" ]] && command -v dscl >/dev/null 2>&1; then
    home_dir="$(dscl . -read "/Users/$user_name" NFSHomeDirectory 2>/dev/null | awk '{ print $2 }' || true)"
  fi
  if [[ -z "$home_dir" ]]; then
    home_dir="$(eval echo "~$user_name" 2>/dev/null || true)"
  fi
  if [[ "$home_dir" == "~$user_name" ]]; then
    home_dir=""
  fi
  printf '%s\n' "$home_dir"
}

build_user_path() {
  local home_dir="$1"
  local prefix="/opt/homebrew/bin:/usr/local/bin"

  if [[ -n "$home_dir" ]]; then
    printf '%s:%s/.npm-global/bin:%s/.local/bin:%s/.cargo/bin:%s/.bun/bin:%s\n' "$prefix" "$home_dir" "$home_dir" "$home_dir" "$home_dir" "$PATH"
  else
    printf '%s:%s\n' "$prefix" "$PATH"
  fi
}

if [[ "$(id -u)" -eq 0 && -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" && "${CLI_BRIDGE_ALLOW_ROOT:-}" != "1" ]]; then
  sudo_home="$(resolve_user_home "$SUDO_USER")"
  user_path="$(build_user_path "$sudo_home")"
  echo "[提示] 检测到 sudo 启动，已切换为用户 $SUDO_USER 运行，避免使用 root 的浏览器和 CLI 配置。"
  echo "[提示] 如确需 root 运行，请设置 CLI_BRIDGE_ALLOW_ROOT=1 后再启动。"
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -H -u "$SUDO_USER" env PATH="$user_path" bash "$SCRIPT_DIR/start.sh" "$@"
  elif command -v runuser >/dev/null 2>&1; then
    if [[ -n "$sudo_home" ]]; then
      exec runuser -u "$SUDO_USER" -- env HOME="$sudo_home" PATH="$user_path" bash "$SCRIPT_DIR/start.sh" "$@"
    fi
    exec runuser -u "$SUDO_USER" -- env PATH="$user_path" bash "$SCRIPT_DIR/start.sh" "$@"
  else
    echo "[错误] 当前以 root 运行，但找不到 sudo/runuser 来切换回 $SUDO_USER。" >&2
    echo "请改用: bash start.sh" >&2
    exit 1
  fi
fi

export PATH="$(build_user_path "${HOME:-}")"

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "[错误] 未找到 .env，请先运行 install.sh 或 install.bat 生成配置。" >&2
  exit 1
fi

export CLI_BRIDGE_SUPERVISOR=1
export WEB_ENABLED="true"

info() {
  printf '[信息] %s\n' "$1"
}

warn() {
  printf '[提示] %s\n' "$1"
}

fail() {
  printf '[错误] %s\n' "$1" >&2
}

is_truthy() {
  local value
  value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

raise_nofile_limit() {
  local target="${TCB_NOFILE_LIMIT:-8192}"
  if ! [[ "$target" =~ ^[0-9]+$ ]] || [[ "$target" -le 0 ]]; then
    return
  fi
  ulimit -n "$target" >/dev/null 2>&1 || true
}

get_dotenv_value() {
  local name="$1"
  awk -F= -v key="$name" '
    /^[[:space:]]*#/ { next }
    NF < 2 { next }
    $1 == key {
      value = substr($0, index($0, "=") + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      gsub(/^"|"$/, "", value)
      gsub(/^'\''|'\''$/, "", value)
      print value
      exit
    }
  ' "$SCRIPT_DIR/.env"
}

show_tunnel_hint() {
  local web_public_url web_tunnel_mode fixed_forward_enabled fixed_forward_url
  web_public_url="$(get_dotenv_value "WEB_PUBLIC_URL")"
  web_tunnel_mode="$(get_dotenv_value "WEB_TUNNEL_MODE")"
  fixed_forward_enabled="$(get_dotenv_value "WEB_FIXED_PUBLIC_FORWARD_ENABLED" | tr '[:upper:]' '[:lower:]')"
  fixed_forward_url="$(get_dotenv_value "WEB_FIXED_PUBLIC_FORWARD_URL")"
  local has_fixed_forward=0
  if [[ -n "$fixed_forward_url" && "$fixed_forward_enabled" =~ ^(1|true|yes|on)$ ]]; then
    has_fixed_forward=1
  fi
  if [[ -z "$web_public_url" && "$has_fixed_forward" -eq 0 && ( -z "$web_tunnel_mode" || "$web_tunnel_mode" == "disabled" ) ]]; then
    echo "[提示] 当前未配置公网访问。"
    echo "如需外网访问，可在 .env 中设置 WEB_TUNNEL_MODE=cloudflare_quick，或配置反向代理后填写 WEB_PUBLIC_URL。"
  fi
}

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "错误: 未找到 python3 或 python，请先安装 Python 并加入 PATH" >&2
  exit 127
fi

STARTUP_STATE_DIR="$SCRIPT_DIR/.tcb/startup"

ensure_project_venv() {
  if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
    return 0
  fi

  if is_truthy "${TCB_STARTUP_USE_SYSTEM_PYTHON:-}"; then
    return 0
  fi

  info "未检测到 .venv，正在创建项目虚拟环境..."
  if ! "$PYTHON_BIN" -m venv "$SCRIPT_DIR/.venv"; then
    fail "创建 .venv 失败。请先运行 bash install.sh，或安装 python3-venv 后重试。"
    exit 1
  fi
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
}

ensure_pip() {
  if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  if "$PYTHON_BIN" -m ensurepip --upgrade >/dev/null 2>&1; then
    return 0
  fi
  fail "当前 Python 无法使用 pip。请先运行 bash install.sh 修复运行环境。"
  exit 1
}

hash_startup_paths() {
  "$PYTHON_BIN" - "$SCRIPT_DIR" "$@" <<'PY'
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

root = Path(sys.argv[1])
files: list[Path] = []
ignored_parts = {"node_modules", "dist", "test-results", "__pycache__"}

for raw_path in sys.argv[2:]:
    path = root / raw_path
    if not path.exists():
        continue
    if path.is_file():
        files.append(path)
        continue
    if path.is_dir():
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            try:
                rel_parts = child.relative_to(root).parts
            except ValueError:
                continue
            if any(part in ignored_parts for part in rel_parts):
                continue
            files.append(child)

digest = hashlib.sha256()
for file_path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
    rel_path = file_path.relative_to(root).as_posix()
    digest.update(rel_path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(file_path.read_bytes())
    digest.update(b"\0")

print(digest.hexdigest())
PY
}

stamp_matches() {
  local stamp_path="$1"
  local expected_hash="$2"

  [[ -f "$stamp_path" ]] && [[ "$(cat "$stamp_path")" == "$expected_hash" ]]
}

write_stamp() {
  local stamp_path="$1"
  local value="$2"

  mkdir -p "$(dirname "$stamp_path")"
  printf '%s\n' "$value" > "${stamp_path}.tmp"
  mv "${stamp_path}.tmp" "$stamp_path"
}

sync_python_dependencies() {
  if is_truthy "${TCB_STARTUP_SKIP_DEP_SYNC:-}"; then
    warn "已跳过启动依赖同步。"
    return 0
  fi
  if [[ ! -f "$SCRIPT_DIR/requirements.txt" ]]; then
    fail "未找到 requirements.txt，无法检查后端依赖。"
    exit 1
  fi

  ensure_project_venv

  local requirements_hash stamp_path
  requirements_hash="$(hash_startup_paths requirements.txt)"
  stamp_path="$STARTUP_STATE_DIR/python-requirements.sha256"

  if stamp_matches "$stamp_path" "$requirements_hash" && ! is_truthy "${TCB_STARTUP_FORCE_DEP_INSTALL:-}"; then
    return 0
  fi

  info "检测到后端依赖清单变化，正在安装 requirements.txt..."
  ensure_pip
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$SCRIPT_DIR/requirements.txt"
  write_stamp "$stamp_path" "$requirements_hash"
}

sync_frontend_assets() {
  if is_truthy "${TCB_STARTUP_SKIP_DEP_SYNC:-}" || is_truthy "${TCB_STARTUP_SKIP_FRONTEND_BUILD:-}"; then
    return 0
  fi
  if [[ ! -f "$SCRIPT_DIR/front/package.json" ]]; then
    return 0
  fi

  local frontend_hash stamp_path build_script dist_index
  frontend_hash="$(
    hash_startup_paths \
      front/package.json \
      front/package-lock.json \
      front/index.html \
      front/vite.config.ts \
      front/tsconfig.json \
      front/src \
      front/public \
      scripts/build_web_frontend.sh
  )"
  stamp_path="$STARTUP_STATE_DIR/frontend-build.sha256"
  dist_index="$SCRIPT_DIR/front/dist/index.html"

  if stamp_matches "$stamp_path" "$frontend_hash" && [[ -f "$dist_index" ]] && ! is_truthy "${TCB_STARTUP_FORCE_FRONTEND_BUILD:-}"; then
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    fail "检测到前端资源需要重建，但未找到 npm。请先运行 bash install.sh 安装 Node.js 依赖。"
    exit 1
  fi

  info "检测到前端源码或依赖变化，正在安装并构建前端..."
  build_script="$SCRIPT_DIR/scripts/build_web_frontend.sh"
  if [[ -f "$build_script" ]]; then
    bash "$build_script"
  else
    (cd "$SCRIPT_DIR/front" && npm install && npm run build)
  fi
  frontend_hash="$(
    hash_startup_paths \
      front/package.json \
      front/package-lock.json \
      front/index.html \
      front/vite.config.ts \
      front/tsconfig.json \
      front/src \
      front/public \
      scripts/build_web_frontend.sh
  )"
  write_stamp "$stamp_path" "$frontend_hash"
}

sync_runtime_dependencies() {
  sync_python_dependencies
  sync_frontend_assets
}

sync_python_dependencies

if ! "$PYTHON_BIN" -m bot.env_migration --env-path "$SCRIPT_DIR/.env"; then
  echo "[错误] 迁移旧版 .env 配置失败。" >&2
  exit 1
fi

"$PYTHON_BIN" -m bot.updater apply-pending --repo-root "$SCRIPT_DIR"
sync_runtime_dependencies
if ! "$PYTHON_BIN" -m bot.migrations run --repo-root "$SCRIPT_DIR"; then
  echo "[错误] 运行数据迁移失败。" >&2
  exit 1
fi
show_tunnel_hint
raise_nofile_limit

while true; do
  set +e
  "$PYTHON_BIN" -m bot
  exit_code=$?
  set -e
  if [[ "$exit_code" -ne 75 ]]; then
    exit "$exit_code"
  fi
  sleep 1
done
