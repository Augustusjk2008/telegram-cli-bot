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
  local web_public_url web_tunnel_mode
  web_public_url="$(get_dotenv_value "WEB_PUBLIC_URL")"
  web_tunnel_mode="$(get_dotenv_value "WEB_TUNNEL_MODE")"
  if [[ -z "$web_public_url" && ( -z "$web_tunnel_mode" || "$web_tunnel_mode" == "disabled" ) ]]; then
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

if ! "$PYTHON_BIN" -m bot.env_migration --env-path "$SCRIPT_DIR/.env"; then
  echo "[错误] 迁移旧版 .env 配置失败。" >&2
  exit 1
fi

"$PYTHON_BIN" -m bot.updater apply-pending --repo-root "$SCRIPT_DIR"
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
