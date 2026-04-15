#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "[错误] 未找到 .env，请先运行 install.sh 或 install.bat 生成配置。" >&2
  exit 1
fi

export CLI_BRIDGE_SUPERVISOR=1
export WEB_ENABLED="true"

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

"$PYTHON_BIN" -m bot.updater apply-pending --repo-root "$SCRIPT_DIR"
show_tunnel_hint

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
